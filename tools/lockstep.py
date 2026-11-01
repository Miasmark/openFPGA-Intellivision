#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""lockstep: run the CP1610 model against a MAME instruction trace.

The trace comes from tools/refs/mame_trace.sh (one line per instruction:
total cycles, frame, beam line, R0-R7, flags, PC, disassembly; then that
instruction's bus reads and writes; MAME's "(interrupted at PC, IRQ 1)"
line where INTRM was taken). See tools/refs/README.md.

What the model owns, and what is replayed from the trace
  The model runs the CPU and the memory a CPU-only system has: EXEC ROM
  ($1000-$1FFF), GROM ($3000-$37FF, 8-bit), the cartridge ROM segments,
  scratchpad RAM ($0100-$01EF, 8-bit) and System RAM ($0200-$035F)
  (DESIGN 2.6). Reads of those come from the model's own memory and are
  checked against the trace. Everything else (STIC registers, PSG and
  controllers, GRAM, Intellivoice, unmapped probes) lies outside the CPU:
  those reads take their value from the trace. The interrupt is injected
  on INTRM at the instruction boundary where the trace shows it; the model
  must agree that the boundary is interruptible and that I is set.

What is compared, instruction by instruction
  - PC, R0-R7 and S Z O C before each instruction (the trace shows the
    state at the start of each instruction);
  - every bus read and write, in order, with address and data;
  - the cycle count of each instruction against the trace's cycle delta.
    MAME charges the STIC's stolen cycles in one lump when it raises the
    interrupt (MAME intv_m.cpp:668, 680). In the traces so far that lump is
    always 0, so the delta across an interrupt must be exactly instruction +
    interrupt; a larger lump is accepted only up to --max-lump N (default 0,
    for later traces where STIC stealing shows up). Cycle differences are
    tallied per mnemonic; only those in KNOWN_CYCLE_DIFF (SETC 4 vs 6,
    SARC Rr,2 8 vs 6, docs/CPU_NOTES.md rows 3-4) are accepted, any other
    one is a divergence.

MAME shows SDBD and the instruction it prefixes as one trace step; the
lockstep merges the two model steps to match.

Usage
  python3 tools/lockstep.py                       all three captured games
  python3 tools/lockstep.py astrosmash --context 12
  python3 tools/lockstep.py --trace T.log --cart G.int --map "5000-5FFF"
The BIOS, game images and traces are the user's and stay outside the
repository: give them with --bios-dir, --trace-root and --game-dir, or the
environment variables INTV_BIOS_DIR, INTV_TRACE_ROOT and INTV_GAME_DIR.
Nothing derived from a game is written by this tool.
"""

import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cp1610 import CP1610, INTERRUPT_CYCLES  # noqa: E402

# Where the user's files are: none of them is in the repository.
DEF_BIOS = os.environ.get("INTV_BIOS_DIR")      # exec.bin, grom.bin
DEF_TRACES = os.environ.get("INTV_TRACE_ROOT")  # <game>/trace.log
DEF_GAMES = os.environ.get("INTV_GAME_DIR")     # <game>.int

# Layouts from research/test-assets/rom_classes.csv (MAME xml region CRCs):
# the image's segments in file order.
GAMES = {
    "astrosmash": "5000-5FFF",
    "towerofdoom": "5000-6FFF 9000-AFFF D000-DFFF F000-FFFF",
    "b17bomb": "5000-6FFF D000-DFFF",
}

# --------------------------------------------------------------- trace file
LINE_RE = re.compile(
    r"^c=(\d+) f=(\d+) y=(\d+) R=((?:[0-9A-F]{4} ){7}[0-9A-F]{4}) "
    r"F=([0-9A-F]{2}) ([0-9A-F]{4}): (.*)$")
ACC_RE = re.compile(r"^  ([RW]) ([0-9A-F]{4}) ([0-9A-F]{4})$")
INT_RE = re.compile(r"^\s*\(interrupted at ([0-9A-F]{4}), IRQ (\d)\)$")


class Rec:
    __slots__ = ("idx", "lineno", "cycle", "frame", "y", "regs", "flags",
                 "pc", "text", "acc", "intr", "intr_acc", "raw")

    def __init__(self, idx, lineno, m):
        self.idx = idx
        self.lineno = lineno
        self.cycle = int(m.group(1))
        self.frame = int(m.group(2))
        self.y = int(m.group(3))
        self.regs = [int(x, 16) for x in m.group(4).split()]
        self.flags = int(m.group(5), 16) >> 4      # MAME S=80 Z=40 OV=20 C=10
        self.pc = int(m.group(6), 16)
        self.text = m.group(7).strip()
        self.acc = []
        self.intr = None
        self.intr_acc = []
        self.raw = m.group(0)


def read_trace(path):
    recs = []
    cur = None
    with open(path) as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n")
            m = LINE_RE.match(line)
            if m:
                cur = Rec(len(recs), n, m)
                recs.append(cur)
                continue
            m = ACC_RE.match(line)
            if m and cur is not None:
                a = (m.group(1), int(m.group(2), 16), int(m.group(3), 16))
                (cur.intr_acc if cur.intr is not None else cur.acc).append(a)
                continue
            m = INT_RE.match(line)
            if m and cur is not None:
                cur.intr = int(m.group(1), 16)
                continue
            if line.strip():
                raise ValueError("%s:%d: unparsed line %r" % (path, n, line))
    return recs


# --------------------------------------------------------------- memory map
def parse_map(text):
    segs = []
    for part in text.replace(",", " ").split():
        lo, hi = part.split("-")
        segs.append((int(lo, 16), int(hi, 16)))
    return segs


def load_words(path, big_endian=True):
    data = open(path, "rb").read()
    if len(data) % 2:
        raise ValueError("%s: odd size" % path)
    if big_endian:
        return [data[i] << 8 | data[i + 1] for i in range(0, len(data), 2)]
    return [data[i + 1] << 8 | data[i] for i in range(0, len(data), 2)]


class Memory:
    """The CPU-side memory the model owns. owner[a] is a region name, or
    None for addresses replayed from the trace."""

    def __init__(self, exec_path, grom_path, cart_path, segs):
        self.mem = [0xFFFF] * 65536
        self.owner = [None] * 65536
        self.width = [0xFFFF] * 65536
        self.writable = [False] * 65536
        ex = load_words(exec_path)
        if len(ex) != 4096:
            raise ValueError("EXEC must be 4096 words")
        self._place(0x1000, ex, "EXEC", 0x3FF)
        grom = open(grom_path, "rb").read()
        if len(grom) != 2048:
            raise ValueError("GROM must be 2048 bytes")
        # GROM drives DB0-7 only; DB8-15 float high on the pulled-up bus
        # (DESIGN 2.5; MAME stic.cpp:1319 returns 0xFF00 | byte).
        self._place(0x3000, [0xFF00 | b for b in grom], "GROM", 0xFFFF)
        words = load_words(cart_path)
        off = 0
        for lo, hi in segs:
            n = hi - lo + 1
            if off + n > len(words):
                raise ValueError("cart image shorter than its map")
            self._place(lo, words[off:off + n], "cart", 0xFFFF)
            off += n
        if off != len(words):
            raise ValueError("cart image has %d words, map covers %d"
                             % (len(words), off))
        # DESIGN 2.6; 8-bit RAM reads drive DB8-15 to 0 (DESIGN 2.5).
        self._ram(0x0100, 0x01EF, "scratchpad", 0xFF)
        self._ram(0x0200, 0x035F, "system RAM", 0xFFFF)

    def _place(self, base, words, name, mask):
        for i, w in enumerate(words):
            a = base + i
            self.mem[a] = w & mask
            self.owner[a] = name
            self.width[a] = mask

    def _ram(self, lo, hi, name, mask):
        for a in range(lo, hi + 1):
            self.mem[a] = 0          # MAME clears RAM at start
            self.owner[a] = name
            self.width[a] = mask
            self.writable[a] = True


def region(a):
    for lo, hi, name in ((0x0000, 0x003F, "STIC"), (0x0040, 0x007F, "STIC-VB"),
                         (0x0080, 0x0081, "Intellivoice"),
                         (0x0100, 0x01EF, "scratchpad"), (0x01F0, 0x01FF, "PSG"),
                         (0x0200, 0x035F, "system RAM"), (0x1000, 0x1FFF, "EXEC"),
                         (0x3000, 0x37FF, "GROM"), (0x3800, 0x3FFF, "GRAM")):
        if lo <= a <= hi:
            return name
    return "other"


# --------------------------------------------------------------------- bus
class Divergence(Exception):
    def __init__(self, kind, msg):
        Exception.__init__(self, msg)
        self.kind = kind
        self.msg = msg


class LockBus:
    """Serves the model from Memory and the trace, and checks every access
    against the trace's list for the current step."""

    def __init__(self, mem):
        self.m = mem
        self.expect = []
        self.pos = 0
        self.intrm_level = False
        self.replayed = collections.Counter()
        self.ram_mismatch = []

    def start(self, accesses):
        self.expect = accesses
        self.pos = 0

    def _next(self, kind, addr):
        if self.pos >= len(self.expect):
            raise Divergence("bus", "model %s $%04X, trace has no more accesses"
                             % (kind, addr))
        e = self.expect[self.pos]
        self.pos += 1
        if e[0] != kind or e[1] != addr:
            raise Divergence("bus", "model %s $%04X, trace %s $%04X %04X"
                             % (kind, addr, e[0], e[1], e[2]))
        return e[2]

    def read(self, addr, cycle, kind):
        tv = self._next("R", addr)
        if self.m.owner[addr] is None:
            self.replayed[region(addr)] += 1
            return tv
        v = self.m.mem[addr]
        if v != tv:
            raise Divergence("data", "read $%04X (%s): model %04X, trace %04X"
                             % (addr, self.m.owner[addr], v, tv))
        return v

    def write(self, addr, value, cycle):
        tv = self._next("W", addr)
        if tv != value:
            raise Divergence("data", "write $%04X: model %04X, trace %04X"
                             % (addr, value, tv))
        if self.m.writable[addr]:
            self.m.mem[addr] = value & self.m.width[addr]

    def end(self):
        if self.pos != len(self.expect):
            e = self.expect[self.pos]
            raise Divergence("bus", "trace has %d more access(es), next %s $%04X %04X"
                             % (len(self.expect) - self.pos, e[0], e[1], e[2]))

    def intrm(self, cycle):
        return self.intrm_level


# ----------------------------------------------------------------- lockstep
def fmt_state(regs, flags):
    return "R=%s SZOC=%s" % (" ".join("%04X" % r for r in regs),
                             format(flags, "04b"))


# Cycle differences against MAME that docs/CPU_NOTES.md lists and decides
# (rows 3 and 4): (mnemonic, model cycles, MAME cycles). Every other cycle
# difference, and any interrupt step shorter than instruction + interrupt,
# fails the lockstep.
KNOWN_CYCLE_DIFF = frozenset({("SETC", 4, 6), ("SARC ,2", 8, 6)})


def mnemonic(text):
    t = text.split()
    if not t:
        return "?"
    m = t[0]
    if m in ("SARC", "SAR", "SLL", "SLLC", "SLR", "RLC", "RRC", "SWAP"):
        return m + (" ,2" if text.rstrip().endswith(",2") or
                    text.rstrip().endswith(", 2") else "")
    return m


class Result:
    def __init__(self, name):
        self.name = name
        self.steps = 0
        self.interrupts = 0
        self.divergences = []           # (kind, rec index, message, context)
        self.cycle_diff = collections.Counter()    # (mnemonic, model, mame) -> n
        self.cycle_examples = {}
        self.lumps = []
        self.replayed = None
        self.frames = 0
        self.cover = {}                 # model mnemonic -> [count, flags seen]
        self.undefined = collections.Counter()


def run(name, recs, mem, context=8, keep_going=False, max_div=20, max_lump=0,
        **cpu_opts):
    res = Result(name)
    bus = LockBus(mem)
    cpu_opts.setdefault("timing", "doc")    # MAME's CPU: the documented counts (TIMING_FIT F is not MAME's)
    cpu = CP1610(bus=bus, **cpu_opts)
    hist = collections.deque(maxlen=context)
    n = len(recs)
    k = 0

    def fail(kind, msg, rec):
        ctx = list(hist)
        res.divergences.append((kind, rec.idx, msg, ctx, rec))
        if not keep_going or len(res.divergences) >= max_div:
            return True
        # Resynchronise on the trace and go on.
        cpu.r = list(rec.regs)
        cpu._set_flags_nibble(rec.flags)
        return False

    while k < n:
        rec = recs[k]
        st = (list(cpu.r), cpu.flags)
        if st[0] != rec.regs or st[1] != rec.flags:
            diffs = []
            for i in range(8):
                if st[0][i] != rec.regs[i]:
                    diffs.append("R%d model %04X trace %04X" % (i, st[0][i], rec.regs[i]))
            if st[1] != rec.flags:
                diffs.append("SZOC model %s trace %s" % (format(st[1], "04b"),
                                                         format(rec.flags, "04b")))
            if fail("state", "before %04X %s: %s" % (rec.pc, rec.text,
                                                     "; ".join(diffs)), rec):
                break
        # One trace step: the instruction (with SDBD merged into it).
        bus.start(rec.acc)
        bus.intrm_level = rec.intr is not None
        try:
            cyc = 0
            texts = []
            while True:
                f0 = cpu.flags
                ev = cpu.step()
                if ev.kind != "insn":
                    raise Divergence("flow", "model took %s (%s) where the trace runs "
                                     "an instruction" % (ev.kind, ev.text))
                cyc += ev.cycles
                texts.append(ev.text)
                c = res.cover.setdefault(ev.text.split()[0], [0, 0])
                c[0] += 1
                c[1] |= cpu.flags & ~f0
                if ev.undefined:
                    res.undefined[ev.undefined] += 1
                if ev.words and (ev.words[0] & 0x3FF) == 0x001:
                    continue                    # SDBD: MAME shows it with the next
                break
            bus.end()
            hist.append("  %6d c=%-7d %04X %-22s | model %-24s %s" % (
                rec.idx, rec.cycle, rec.pc, rec.text, " ; ".join(texts),
                fmt_state(cpu.r, cpu.flags)))
            # Interrupt where the trace has one.
            icyc = 0
            if rec.intr is not None:
                if cpu.r[7] != rec.intr:
                    raise Divergence("flow", "trace interrupts with return PC %04X, "
                                     "model PC %04X" % (rec.intr, cpu.r[7]))
                if not cpu.interruptible:
                    raise Divergence("intr", "trace takes INTRM after %s, which the "
                                     "model treats as not interruptible" % rec.text)
                if not cpu.I:
                    raise Divergence("intr", "trace takes INTRM with I=0 in the model")
                bus.start(rec.intr_acc)
                ev = cpu.step()
                if ev.kind != "intr":
                    raise Divergence("intr", "model did not take INTRM (%s)" % ev.kind)
                bus.end()
                bus.intrm_level = False
                icyc = ev.cycles
                res.interrupts += 1
                hist.append("         (interrupt, return %04X) | model %s" %
                            (rec.intr, ev.text))
            elif cpu.interruptible and cpu.intrm_pending:
                raise Divergence("intr", "model has INTRM pending without a trace interrupt")
        except Divergence as d:
            hist.append("  %6d c=%-7d %04X %-22s | (diverged)" %
                        (rec.idx, rec.cycle, rec.pc, rec.text))
            if fail(d.kind, "at %04X %s: %s" % (rec.pc, rec.text, d.msg), rec):
                break
            # resync: skip to the next record with model state from the trace
            k += 1
            if k < n:
                cpu.r = list(recs[k].regs)
                cpu._set_flags_nibble(recs[k].flags)
                cpu.intrm_pending = False
                cpu.interruptible = False
                bus.intrm_level = False
            continue
        # Cycles. Only the documented disagreements in KNOWN_CYCLE_DIFF are
        # accepted; any other difference is a divergence.
        if k + 1 < n:
            dt = recs[k + 1].cycle - rec.cycle
            mn = mnemonic(rec.text)
            bad = None
            if rec.intr is None:
                if dt != cyc:
                    key = (mn, cyc, dt)
                    res.cycle_diff[key] += 1
                    res.cycle_examples.setdefault(key, "%04X %s" % (rec.pc, rec.text))
                    if key not in KNOWN_CYCLE_DIFF:
                        bad = "%s takes %d cycles in the model, %d in MAME" % (mn, cyc, dt)
            else:
                res.lumps.append(dt - cyc - icyc)
                if dt < cyc + icyc or dt - cyc - icyc > max_lump:
                    key = (mn + " +INT", cyc + icyc, dt)
                    res.cycle_diff[key] += 1
                    res.cycle_examples.setdefault(key, "%04X %s" % (rec.pc, rec.text))
                    bad = ("%s + interrupt takes %d + %d cycles in the model, MAME's "
                           "delta is %d (lump allowed: 0..%d)"
                           % (mn, cyc, icyc, dt, max_lump))
            if bad is not None:
                hist.append("  %6d c=%-7d %04X %-22s | (cycles differ)" %
                            (rec.idx, rec.cycle, rec.pc, rec.text))
                if fail("cycles", "at %04X %s: %s" % (rec.pc, rec.text, bad), rec):
                    res.steps += 1
                    k += 1
                    break
        res.steps += 1
        k += 1
    res.replayed = bus.replayed
    res.frames = recs[min(k, n - 1)].frame + 1 if recs else 0
    res.done = k
    res.total = n
    return res


def report(res, out=sys.stdout):
    p = lambda *a: print(*a, file=out)  # noqa: E731
    ok = not res.divergences
    p("== %s: %s, %d of %d trace steps, %d interrupts, frames 0..%d" % (
        res.name, "AGREE" if ok else "DIVERGE", res.steps, res.total,
        res.interrupts, res.frames - 1))
    for kind, idx, msg, ctx, rec in res.divergences[:1]:
        p("first divergence (%s) at trace step %d (line %d, frame %d):"
          % (kind, idx, rec.lineno, rec.frame))
        p("  " + msg)
        p("  context (trace step, cycle, PC, trace text | model):")
        for c in ctx:
            p(c)
    if len(res.divergences) > 1:
        p("further divergences: %d" % (len(res.divergences) - 1))
        for kind, idx, msg, _, _ in res.divergences[1:]:
            p("  step %d (%s): %s" % (idx, kind, msg))
    p("replayed reads (outside the CPU): %s" % dict(sorted(res.replayed.items())))
    if res.cycle_diff:
        p("cycle differences, model vs MAME (mnemonic, model, MAME: count, first):")
        for key, cnt in sorted(res.cycle_diff.items()):
            p("  %-10s %2d %2d: %5d  %s%s" % (
                key[0], key[1], key[2], cnt, res.cycle_examples.get(key, ""),
                "" if key in KNOWN_CYCLE_DIFF else "  (not allowed)"))
    else:
        p("cycle counts: all equal outside interrupts")
    if res.undefined:
        p("instructions the model marks undefined: %s" % dict(res.undefined))
    flagnames = "SZOC"
    cov = ["%s:%d/%s" % (m, c[0], "".join(flagnames[i] if c[1] >> (3 - i) & 1 else "-"
                                       for i in range(4)))
           for m, c in sorted(res.cover.items())]
    p("coverage (model mnemonic:count/flags it raised from 0 to 1):")
    for i in range(0, len(cov), 8):
        p("  " + " ".join(cov[i:i + 8]))
    if res.lumps:
        p("cycles MAME adds at each interrupt beyond instruction + %d: %s"
          % (INTERRUPT_CYCLES, res.lumps))
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("games", nargs="*", help="preset names: %s" % ", ".join(GAMES))
    ap.add_argument("--trace", help="trace file (with --cart and --map)")
    ap.add_argument("--cart", help="raw .int image")
    ap.add_argument("--map", help='segments in file order, e.g. "5000-6FFF D000-DFFF"')
    ap.add_argument("--bios-dir", default=DEF_BIOS)
    ap.add_argument("--exec", dest="exec_path")
    ap.add_argument("--grom")
    ap.add_argument("--trace-root", default=DEF_TRACES)
    ap.add_argument("--game-dir", default=DEF_GAMES)
    ap.add_argument("--context", type=int, default=10)
    ap.add_argument("--keep-going", action="store_true",
                    help="resync on the trace after a divergence and go on")
    ap.add_argument("--max-div", type=int, default=20)
    ap.add_argument("--sdbd-r6", default="wiki", choices=("wiki", "mame"))
    ap.add_argument("--max-lump", type=int, default=0,
                    help="cycles MAME may add at an interrupt beyond instruction + "
                         "interrupt (default 0: none in the traces so far)")
    a = ap.parse_args(argv)
    if not (a.exec_path and a.grom) and not a.bios_dir:
        ap.error("give --bios-dir (or INTV_BIOS_DIR), or --exec and --grom")
    if not a.trace and not (a.trace_root and a.game_dir):
        ap.error("give --trace-root and --game-dir (or INTV_TRACE_ROOT and "
                 "INTV_GAME_DIR), or --trace, --cart and --map")
    exec_path = a.exec_path or os.path.join(a.bios_dir, "exec.bin")
    grom = a.grom or os.path.join(a.bios_dir, "grom.bin")
    jobs = []
    if a.trace:
        if not (a.cart and a.map):
            ap.error("--trace needs --cart and --map")
        jobs.append((os.path.basename(os.path.dirname(a.trace)) or a.trace,
                     a.trace, a.cart, a.map))
    for g in a.games or ([] if a.trace else list(GAMES)):
        if g not in GAMES:
            ap.error("unknown game %r" % g)
        jobs.append((g, os.path.join(a.trace_root, g, "trace.log"),
                     os.path.join(a.game_dir, g + ".int"), GAMES[g]))
    all_ok = True
    for name, tr, cart, mp in jobs:
        recs = read_trace(tr)
        mem = Memory(exec_path, grom, cart, parse_map(mp))
        res = run(name, recs, mem, context=a.context, keep_going=a.keep_going,
                  max_div=a.max_div, max_lump=a.max_lump, sdbd_r6=a.sdbd_r6)
        all_ok &= report(res)
    print("LOCKSTEP %s" % ("pass" if all_ok else "FAIL"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
