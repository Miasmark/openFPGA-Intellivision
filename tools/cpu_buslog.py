#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""cpu_buslog: export the CP1610 model's bus-phase log for the RTL lockstep
bench (sim/tb/tb_cpu.sv, build step 3 of DESIGN.md section 9).

Two case sets, one file each:

  tests   every program in sim/tests/cpu that assembles (the asm-error
          tests have no program), run on tools/cp1610.py with the test's
          own start, stop, request lines, BEXT conditions and options, as
          tools/run_cpu_tests.py runs them. Strict tests run non-strict:
          the RTL takes the model's default choice where strict raises.
          A run ends where the test ends (before the instruction at the
          stop label), five cycles into a halt, at a fetch from a word the
          test never defined (the test bus's trap), or at maxcycles.
  sweep   every one of the 1024 opcodes once, after SDBD where that is a
          double-byte read, and each branch both taken and not taken, with
          the registers run_cpu_tests.py's cycle sweep uses, run for at
          least 40 cycles.

Each case also lists save points for the bench's save/restore round trip:
cycles inside the interrupt sequence (INTAK, DW, after IAB), inside a
bus-request wait, in the middle of direct, write and SDBD sequences, in a
halt, and pseudo-random ones (seeded by the case name).

  fuzz    random programs: all 64K words filled by fill_word() (the bench
          computes the same), random registers and flags, random INTRM,
          INTR and BUSRQ windows, random HLT and SDBD+R6 options, about
          600 cycles each. Random words reach every opcode in every
          context the tests do not (pointer as destination, SDBD before
          anything, jumps to anywhere, interrupts in any state).

File format (one record per line, numbers in hex unless said):
  CASE name
  OPT hlt_imm sdbd_r6_mame bext_mask reset_vector intr_vector
  INIT r0 .. r7 szoc i            registers to load before cycle 0 (sweep, fuzz)
  FILL seed                       memory holds fill_word(seed, addr) (fuzz)
  R kind lo hi                    request line kind (0 INTRM, 1 INTR,
                                  2 BUSRQ) asserted for cycles lo..hi
                                  (hi = ffffffff: to the end)
  M addr word                     memory before reset
  C ph addr data flags            one per cycle from 0: phase code
                                  {BDIR,BC2,BC1}, address and data as the
                                  model logs them (0 where none),
                                  flags bit 0 BUSAK, bit 1 halted
  E cycle r0 .. r7 szoc i d       a step (instruction, interrupt, bus wait,
                                  halted cycle) ends at cycle
  T cycle / P cycle               TCI pulse / SIN hook (model cycle)
  S cycle                         save point
  END cycles r0 .. r7 szoc i d halted

Use: cpu_buslog.py OUTDIR [NFUZZ]   writes OUTDIR/tests.vec, sweep.vec and
                                    fuzz.vec (NFUZZ cases, default 300)
"""

import glob
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import as1610  # noqa: E402
import cp1610  # noqa: E402
import run_cpu_tests as rct  # noqa: E402

PHASE_CODE = {"NACT": 0, "ADAR": 1, "IAB": 2, "DTB": 3, "BAR": 4, "DW": 5,
              "DWS": 6, "INTAK": 7}
LINE_KIND = {"intrm": 0, "intr": 1, "busrq": 2}
HALT_TAIL = 5          # halted cycles kept after the CPU halts


class RecBus(rct.TestBus):
    """The test bus, recording the TCI and SIN hook cycles."""

    def __init__(self, prog, spec):
        super().__init__(prog, spec)
        self.tci_at, self.sin_at = [], []

    def tci(self, cycle):
        super().tci(cycle)
        self.tci_at.append(cycle)

    def sin(self, cycle):
        super().sin(cycle)
        self.sin_at.append(cycle)


class SweepBus(rct._SweepBus):
    def __init__(self):
        super().__init__()
        self.tci_at, self.sin_at = [], []

    def tci(self, cycle):
        self.tci_at.append(cycle)

    def sin(self, cycle):
        self.sin_at.append(cycle)


def _regs_line(regs, flags, i, d):
    return " ".join("%x" % x for x in regs) + " %x %x %x" % (flags, i, d)


def _run(cpu, bus, stop=None, stop_halt=False, maxcycles=200000, mincycles=None):
    """Step the model; return (events, end_cycle, final (regs, flags, i, d,
    halted))."""
    init = (list(cpu.r), cpu.flags, cpu.I, cpu.D, int(cpu.halted))
    events, nhalt, end, halted = [], 0, None, int(cpu.halted)
    while True:
        if cpu.cycle > maxcycles:
            end = cpu.cycle
            break
        if mincycles is not None and cpu.cycle >= mincycles:
            end = cpu.cycle
            break
        c0 = cpu.cycle
        try:
            ev = cpu.step()
        except rct.TrapFetch:
            end = c0
            break
        if ev.kind == "insn" and stop is not None and ev.pc == stop:
            end = ev.cycle
            break
        events.append(ev)
        halted = int(cpu.halted)
        if ev.kind == "halt":
            nhalt += 1
            if nhalt >= HALT_TAIL:
                end = cpu.cycle
                break
    final = init
    if events:
        e = events[-1]
        final = (e.regs, e.flags, e.i, e.d, halted)
    return events, end, final


def _save_points(name, log, events, end):
    """Cycles at which the bench saves and restores the CPU."""
    pts = set()
    ints = [e for e in events if e.kind == "intr"]
    for e in ints[:2]:
        pts.update((e.cycle + 1, e.cycle + 3, e.cycle + 6, e.cycle + 8))
    for e in [e for e in events if e.kind == "busak" and e.cycles >= 2][:2]:
        pts.add(e.cycle + 1)
    for e in [e for e in events if e.kind == "insn" and e.text == "HLT"][:2]:
        pts.add(e.cycle + e.cycles + 1)     # halt pending, next instruction
    halts = [e for e in events if e.kind == "halt"]
    if halts:
        pts.add(halts[0].cycle + 1)
    seen = set()
    for c, ph, _a, _d in log:
        if ph in ("ADAR", "DW", "DWS") and ph not in seen:
            seen.add(ph)
            pts.add(c)
    # SDBD reads: the cycle of the second BAR
    for k in range(3, len(log)):
        if log[k][1] == "BAR" and log[k - 1][1] == "DTB" and log[k - 3][1] == "BAR":
            pts.add(log[k][0])
            break
    rnd = random.Random(name)
    for _ in range(4):
        if end > 2:
            pts.add(rnd.randrange(1, end))
    return sorted(p for p in pts if 0 < p < end)


def fill_word(seed, a):
    """Memory contents of a fuzz case (tb_cpu.sv fill_word is the same)."""
    x = (a * 2654435761 + seed) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 2246822519) & 0xFFFFFFFF
    x ^= x >> 13
    return x & 0xFFFF


def _emit(out, name, opts, init, ranges, mem, cpu, bus, events, end, final, saves,
          fill=None):
    log = [x for x in cpu.buslog if x[0] < end]
    if [c for c, *_ in log] != list(range(end)):
        raise RuntimeError("%s: bus log does not cover cycles 0..%d" % (name, end - 1))
    busak, halted = set(), set()
    for e in events:
        if e.kind == "busak":
            busak.update(range(e.cycle, e.cycle + e.cycles))
        elif e.kind == "halt":
            halted.add(e.cycle)
    w = out.write
    w("CASE %s\n" % name)
    w("OPT %x %x %x %x %x\n" % opts)
    if init is not None:
        w("INIT %s\n" % " ".join("%x" % x for x in init))
    if fill is not None:
        w("FILL %x\n" % fill)
    for kind, lo, hi in ranges:
        w("R %x %x %x\n" % (kind, lo, 0xFFFFFFFF if hi is None else hi))
    for a in sorted(mem):
        w("M %x %x\n" % (a, mem[a] & 0xFFFF))
    for c, ph, a, d in log:
        fl = (1 if c in busak else 0) | (2 if c in halted else 0)
        w("C %x %x %x %x\n" % (PHASE_CODE[ph], a or 0, d or 0, fl))
    for e in events:
        w("E %x %s\n" % (e.cycle + e.cycles, _regs_line(e.regs, e.flags, e.i, e.d)))
    for c in bus.tci_at:
        if c < end:
            w("T %x\n" % c)
    for c in bus.sin_at:
        if c < end:
            w("P %x\n" % c)
    for s in saves:
        w("S %x\n" % s)
    regs, flags, i, d, h = final
    w("END %x %s %x\n" % (end, _regs_line(regs, flags, i, d), h))
    return log


def export_tests(out, files):
    n = 0
    for path in files:
        name = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as f:
            src = f.read()
        spec = rct.parse_spec(src)
        if spec["asm_error"]:
            continue                    # no program to run
        prog = as1610.assemble(src)
        spec["start"] = prog.symbols[spec["start"]]
        stop_halt = spec["stop"] == "halt"
        stop = None if stop_halt else prog.symbols.get(spec["stop"])
        bus = RecBus(prog, spec)
        o = spec["options"]
        sdbd_r6, hlt = o.get("sdbd_r6", "wiki"), o.get("hlt", "manual")
        cpu = cp1610.CP1610(bus, strict=False, sdbd_r6=sdbd_r6, hlt=hlt, buslog=True)
        events, end, final = _run(cpu, bus, stop=stop, stop_halt=stop_halt,
                                  maxcycles=spec["maxcycles"])
        ranges = [(LINE_KIND[k], lo, hi) for k, rs in sorted(spec["ranges"].items())
                  for lo, hi in rs]
        bext = sum(1 << c for c in spec["bext"])
        opts = (int(hlt == "immediate"), int(sdbd_r6 == "mame"), bext,
                spec["start"], bus.vector)
        log = [x for x in cpu.buslog if x[0] < end]
        saves = _save_points(name, log, events, end)
        _emit(out, name, opts, None, ranges, prog.words, cpu, bus, events, end,
              final, saves)
        n += 1
        print("  %-22s %6d cycles %5d steps %2d save points" % (name, end, len(events), len(saves)))
    return n


def sweep_cases():
    """(name, op, sdbd, taken) as run_cpu_tests.sweep_cycles makes them."""
    for op in range(0x400):
        for sdbd in (False, True):
            if sdbd and not (op >= 0x280 and (op >> 3) & 7 != 0):
                continue
            for taken in ((False, True) if 0x200 <= op < 0x240 else (False,)):
                yield ("op%03x%s%s" % (op, "_sdbd" if sdbd else "",
                                       "_t" if taken else ""), op, sdbd, taken)


def export_sweep(out):
    n = 0
    for name, op, sdbd, taken in sweep_cases():
        bus = SweepBus()
        words = ([0x001] if sdbd else []) + [op, 0x0010, 0x0123]
        mem = {0x5000 + k: w for k, w in enumerate(words)}
        for a, w in mem.items():
            bus.mem[a] = w
        cpu = cp1610.CP1610(bus, buslog=True)
        cpu.r[6] = 0x0300
        for r in range(1, 6):
            cpu.r[r] = 0x0200 + r
        if 0x200 <= op < 0x240:
            if op & 0x10:
                bus.bext_true = set(range(16)) if taken else set()
            else:
                found = False
                for nib in range(16):
                    cpu._set_flags_nibble(nib)
                    S, Z, O, C = cpu.S, cpu.Z, cpu.O, cpu.C
                    t = (True, C, O, not S, Z, S ^ O, Z or (S ^ O), S ^ C)[op & 7]
                    if (bool(t) != bool(op & 8)) == taken:
                        found = True
                        break
                if not found:
                    continue
        init = list(cpu.r) + [cpu.flags, cpu.I]
        events, end, final = _run(cpu, bus, mincycles=40)
        bext = sum(1 << c for c in bus.bext_true)
        opts = (0, 0, bext, 0x5000, 0x1004)
        log = [x for x in cpu.buslog if x[0] < end]
        rnd = random.Random(name)
        saves = sorted({rnd.randrange(1, min(end, 14))})
        _emit(out, name, opts, init, [], mem, cpu, bus, events, end, final, saves)
        n += 1
    return n


class FuzzBus(rct._SweepBus):
    def __init__(self, seed, ranges, bext):
        super().__init__()
        self.mem = [fill_word(seed, a) for a in range(65536)]
        self.ranges, self.bext_true = ranges, bext
        self.tci_at, self.sin_at = [], []

    def tci(self, cycle):
        self.tci_at.append(cycle)

    def sin(self, cycle):
        self.sin_at.append(cycle)


def export_fuzz(out, n):
    for k in range(n):
        name = "fuzz%03d" % k
        rnd = random.Random(name)
        seed = rnd.getrandbits(32)
        ranges = {}
        for kind in ("intrm", "intr", "busrq"):
            rs, c = [], rnd.randrange(0, 200)
            for _ in range(rnd.randrange(0, 4) if kind != "intr" else rnd.randrange(0, 2)):
                ln = rnd.choice((1, 2, 3, 8, 30, 120)) if kind == "busrq" else rnd.randrange(1, 300)
                rs.append((c, c + ln - 1))
                c += ln + rnd.randrange(1, 200)
            if rs:
                ranges[kind] = rs
        bext = {c for c in range(16) if rnd.random() < 0.5}
        bus = FuzzBus(seed, ranges, bext)
        start = rnd.getrandbits(16)
        bus.start = start
        hlt = rnd.choice(("manual", "immediate"))
        sdbd_r6 = rnd.choice(("wiki", "mame"))
        cpu = cp1610.CP1610(bus, sdbd_r6=sdbd_r6, hlt=hlt, buslog=True)
        for r in range(7):
            cpu.r[r] = rnd.getrandbits(16)
        cpu._set_flags_nibble(rnd.getrandbits(4))
        cpu.I = rnd.getrandbits(1)
        init = list(cpu.r) + [cpu.flags, cpu.I]
        events, end, final = _run(cpu, bus, mincycles=600)
        opts = (int(hlt == "immediate"), int(sdbd_r6 == "mame"),
                sum(1 << c for c in bext), start, 0x1004)
        log = [x for x in cpu.buslog if x[0] < end]
        saves = _save_points(name, log, events, end)
        lranges = [(LINE_KIND[kd], lo, hi) for kd, rs in sorted(ranges.items())
                   for lo, hi in rs]
        _emit(out, name, opts, init, lranges, {}, cpu, bus, events, end, final, saves,
              fill=seed)
    return n


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in (1, 2):
        print(__doc__)
        return 2
    outdir = argv[0]
    nfuzz = int(argv[1]) if len(argv) > 1 else 300
    os.makedirs(outdir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(rct.TEST_DIR, "*.asm")))
    with open(os.path.join(outdir, "tests.vec"), "w") as f:
        n = export_tests(f, files)
    print("tests: %d programs (%d files, %d asm-error tests have no program)"
          % (n, len(files), len(files) - n))
    with open(os.path.join(outdir, "sweep.vec"), "w") as f:
        n = export_sweep(f)
    print("sweep: %d cases" % n)
    with open(os.path.join(outdir, "fuzz.vec"), "w") as f:
        n = export_fuzz(f, nfuzz)
    print("fuzz: %d cases" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
