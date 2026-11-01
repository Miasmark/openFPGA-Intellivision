#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Run the CP1610 model tests: sim/tests/cpu/*.asm plus built-in sweeps.

Each .asm test is assembled with as1610.py and run on cp1610.py from reset.
Expected results are written by hand from the documents, in comment lines
that start with ';!':

  ;! start LABEL            reset vector (default: label 'start')
  ;! stop LABEL             stop on arrival at LABEL (default: 'done');
                            'stop halt': the test ends when the CPU halts.
                            In any other test a halt is a failure.
  ;! options strict sdbd_r6=mame hlt=immediate
  ;! intrm FROM-TO          INTRM* asserted for cycles FROM..TO (TO may be
                            empty: until the end); also 'intr', 'busrq'
  ;! bext N ...             external branch conditions that read true
  ;! maxcycles N            give up after N cycles (default 200000)
  ;! expect LABEL[#K]: CHECKS   checked on the K-th arrival at LABEL (before
                            the instruction there runs); 'end' = at the stop.
                            An expectation that is never reached fails.
  ;! cycles A B = N         cycles from the first arrival at A to the first at B
                            (fails if either label is never reached)
  ;! words LABEL = W ...    assembled words at LABEL
  ;! undefined LABEL        the instruction at LABEL is marked undefined
  ;! raises TEXT            the run must raise UndefinedBehaviour (strict)
  ;! asm-error TEXT         assembling must fail with TEXT in the message

CHECKS: R0..R7=V  S= Z= O= C= I= D=  SZOC=bbbb  CYC=N (cycle at which the
instruction starts)  [ADDR]=V  INTS=N (interrupts taken)  BUSAK=N (cycles
waited)  TCI=N  SIN=N  HALT=0|1. Values are as1610 expressions.

The test bus fails a test that fetches an instruction from a word that was
neither assembled nor written (unassembled memory reads as 0, which is HLT,
so a wild jump would otherwise just halt).

Use: run_cpu_tests.py [-v] [-k SUBSTR] [--trace DIR] [files...]
"""

import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import as1610  # noqa: E402
import cp1610  # noqa: E402
from g82_cycles import g82_cycles  # noqa: E402

REPO = os.path.dirname(HERE)
TEST_DIR = os.path.join(REPO, "sim", "tests", "cpu")


class TrapFetch(Exception):
    """An instruction fetch from a word the test never defined."""


class TestBus:
    def __init__(self, prog, spec):
        self.mem = [0] * 65536
        for a, w in prog.words.items():
            self.mem[a] = w
        self.defined = set(prog.words)     # assembled or written words
        self.start = spec["start"]
        self.vector = prog.symbols.get("isr", 0x1004)
        self.ranges = spec["ranges"]
        self.bext_true = spec["bext"]
        self.tci_n = self.sin_n = 0
        self.intak_log = []

    def read(self, addr, cycle, kind):
        if kind == "fetch" and self.defined is not None and addr not in self.defined:
            raise TrapFetch("fetch from unassembled word $%04X at cycle %d" % (addr, cycle))
        return self.mem[addr]

    def write(self, addr, value, cycle):
        self.mem[addr] = value
        if self.defined is not None:
            self.defined.add(addr)

    def iab(self, cycle, reason):
        return self.start if reason == "reset" else self.vector

    def intak(self, addr, cycle):
        self.intak_log.append((addr, cycle))

    def _in(self, name, cycle):
        for lo, hi in self.ranges.get(name, ()):
            if lo <= cycle and (hi is None or cycle <= hi):
                return True
        return False

    def intrm(self, cycle):
        return self._in("intrm", cycle)

    def intr(self, cycle):
        return self._in("intr", cycle)

    def busrq(self, cycle):
        return self._in("busrq", cycle)

    def bext(self, cond, cycle):
        return cond in self.bext_true

    def tci(self, cycle):
        self.tci_n += 1

    def sin(self, cycle):
        self.sin_n += 1


def _val(text, prog):
    return as1610._Expr(text, lambda n: prog.symbols[n], 0).value()


def parse_spec(src):
    spec = {"start": "start", "stop": "done", "options": {}, "ranges": {},
            "bext": set(), "maxcycles": 200000, "expect": [], "cycles": [],
            "words": [], "undefined": [], "raises": None, "asm_error": None}
    for lineno, line in enumerate(src.splitlines(), 1):
        m = re.match(r"\s*;!\s*(\S+)\s*(.*)$", line)
        if not m:
            continue
        key, rest = m.group(1).lower(), m.group(2).strip()
        if key in ("start", "stop"):
            spec[key] = rest
        elif key == "options":
            for o in rest.split():
                k, _, v = o.partition("=")
                spec["options"][k] = v if v else True
        elif key in ("intrm", "intr", "busrq"):
            for part in rest.split():
                lo, _, hi = part.partition("-")
                spec["ranges"].setdefault(key, []).append(
                    (int(lo), int(hi) if hi else None))
        elif key == "bext":
            spec["bext"] |= {int(x) for x in rest.split()}
        elif key == "maxcycles":
            spec["maxcycles"] = int(rest)
        elif key == "expect":
            where, _, checks = rest.partition(":")
            lab, _, k = where.strip().partition("#")
            spec["expect"].append((lineno, lab.strip(), int(k or 1), checks.strip()))
        elif key == "cycles":
            m2 = re.match(r"(\S+)\s+(\S+)\s*=\s*(.+)$", rest)
            spec["cycles"].append((lineno, m2.group(1), m2.group(2), m2.group(3)))
        elif key == "words":
            lab, _, ws = rest.partition("=")
            spec["words"].append((lineno, lab.strip(), ws.split()))
        elif key == "undefined":
            spec["undefined"].append((lineno, rest))
        elif key == "raises":
            spec["raises"] = rest
        elif key == "asm-error":
            spec["asm_error"] = rest
        else:
            raise ValueError("line %d: unknown directive ;! %s" % (lineno, key))
    return spec


CHECK_RE = re.compile(r"(\[[^\]]+\]|[A-Za-z0-9]+)\s*=\s*(\S+)")


def run_checks(checks, prog, cpu, bus, extra):
    """Return a list of failure strings."""
    fails = []
    for name, want_s in CHECK_RE.findall(checks):
        want = _val(want_s, prog)
        up = name.upper()
        if up.startswith("["):
            addr = _val(name[1:-1], prog) & 0xFFFF
            got, want = bus.mem[addr], want & 0xFFFF
            label = "[$%04X]" % addr
        elif re.fullmatch(r"R[0-7]", up):
            got, want, label = cpu.r[int(up[1])], want & 0xFFFF, up
        elif up in ("S", "Z", "O", "C", "I", "D"):
            got, label = getattr(cpu, up), up
        elif up == "SZOC":
            got, want, label = cpu.flags, int(want_s, 2), up
        elif up == "CYC":
            got, label = extra["cyc"], up
        elif up in ("INTS", "BUSAK"):
            got, label = extra[up.lower()], up
        elif up == "TCI":
            got, label = bus.tci_n, up
        elif up == "SIN":
            got, label = bus.sin_n, up
        elif up == "HALT":
            got, label = int(cpu.halted), up
        else:
            fails.append("unknown check %s" % name)
            continue
        if got != want:
            if label in ("SZOC",):
                fails.append("%s=%s, want %s" % (label, format(got, "04b"), want_s))
            elif label.startswith("R") or label.startswith("["):
                fails.append("%s=$%04X, want $%04X" % (label, got, want))
            else:
                fails.append("%s=%d, want %d" % (label, got, want))
    return fails


def run_asm_test(path, trace_dir=None, verbose=False):
    name = os.path.relpath(path, REPO)
    with open(path, encoding="utf-8") as f:
        src = f.read()
    spec = parse_spec(src)
    try:
        prog = as1610.assemble(src)
    except as1610.AsmError as e:
        if spec["asm_error"] and spec["asm_error"] in str(e):
            return name, [], 1
        return name, ["assembly failed: %s" % e], 0
    if spec["asm_error"]:
        return name, ["assembly should fail with '%s'" % spec["asm_error"]], 0
    fails, nchecks = [], 0
    for lineno, lab, ws in spec["words"]:
        a = prog.symbols[lab]
        got = [prog.words.get((a + k) & 0xFFFF) for k in range(len(ws))]
        want = [_val(w, prog) & 0xFFFF for w in ws]
        nchecks += 1
        if got != want:
            fails.append("line %d: words at %s = %s, want %s" % (
                lineno, lab, " ".join("$%04X" % w if w is not None else "-" for w in got),
                " ".join("$%04X" % w for w in want)))
    if spec["start"] not in prog.symbols:
        return name, fails or ["no label '%s'" % spec["start"]], nchecks
    spec["start"] = prog.symbols[spec["start"]]
    stop_on_halt = spec["stop"] == "halt"
    stop = None if stop_on_halt else prog.symbols.get(spec["stop"])
    if stop is None and not stop_on_halt:
        fails.append("no stop label '%s'" % spec["stop"])
    reached = set()                 # line numbers of expectations evaluated
    bus = TestBus(prog, spec)
    opts = spec["options"]
    try:
        cpu = cp1610.CP1610(bus, strict=bool(opts.get("strict")),
                            sdbd_r6=opts.get("sdbd_r6", "wiki"),
                            hlt=opts.get("hlt", "manual"))
    except ValueError as e:
        return name, ["bad options: %s" % e], nchecks
    # arrivals: label address -> list of expectations
    watch = {}
    for lineno, lab, k, checks in spec["expect"]:
        if lab == "end":
            continue
        if lab not in prog.symbols:
            fails.append("line %d: no label '%s'" % (lineno, lab))
            continue
        watch.setdefault(prog.symbols[lab], []).append((lineno, lab, k, checks))
    first_arrival = {}
    arrivals = {}
    undefined_at = {prog.symbols[l]: (ln, l) for ln, l in spec["undefined"]
                    if l in prog.symbols}
    seen_undef = set()
    extra = {"ints": 0, "busak": 0, "cyc": 0}
    trace = [cp1610.trace_header()] if trace_dir else None
    raised = None
    end_state = False
    pending = []
    while True:
        if cpu.cycle > spec["maxcycles"]:
            fails.append("ran past %d cycles (PC=$%04X)" % (spec["maxcycles"], cpu.r[7]))
            break
        pc = cpu.r[7]
        # pre-step evaluation, committed only if the step runs the
        # instruction at this PC
        pre = []
        if pc in watch and not cpu.halted:
            n = arrivals.get(pc, 0) + 1
            for lineno, lab, k, checks in watch[pc]:
                if k == n:
                    pre.append((lineno, lab, k, checks))
        snap = None
        if pre or pc == stop:
            snap = (cpu.state(), list(bus.mem))
        try:
            ev = cpu.step()
        except cp1610.UndefinedBehaviour as e:
            raised = str(e)
            break
        except TrapFetch as e:
            fails.append(str(e))
            break
        if trace is not None:
            trace.append(cp1610.trace_line(ev))
        if ev.kind == "intr":
            extra["ints"] += 1
        elif ev.kind == "busak":
            extra["busak"] += ev.cycles
        if ev.kind == "insn":
            arrivals[ev.pc] = arrivals.get(ev.pc, 0) + 1
            first_arrival.setdefault(ev.pc, ev.cycle)
            if ev.undefined and ev.pc in undefined_at:
                seen_undef.add(ev.pc)
            elif ev.undefined and verbose:
                print("  note: undefined at $%04X: %s" % (ev.pc, ev.undefined))
            if snap is not None and ev.pc == pc:
                cur = (cpu.state(), list(bus.mem))
                cpu.set_state(snap[0])
                bus.mem = snap[1]
                extra["cyc"] = ev.cycle
                for lineno, lab, k, checks in pre:
                    nchecks += 1
                    reached.add(lineno)
                    for f in run_checks(checks, prog, cpu, bus, extra):
                        fails.append("line %d: at %s#%d: %s" % (lineno, lab, k, f))
                if pc == stop:
                    end_state = True
                    extra_end = dict(extra)
                    for lineno, lab, k, checks in spec["expect"]:
                        if lab == "end":
                            nchecks += 1
                            reached.add(lineno)
                            for f in run_checks(checks, prog, cpu, bus, extra_end):
                                fails.append("line %d: at end: %s" % (lineno, f))
                    break
                cpu.set_state(cur[0])
                bus.mem = cur[1]
        if ev.kind == "halt":
            if not stop_on_halt:
                fails.append("CPU halted at $%04X (cycle %d) before reaching the stop "
                             "label; only ';! stop halt' tests may end in a halt"
                             % (ev.pc, ev.cycle))
                break
            extra["cyc"] = ev.cycle
            for lineno, lab, k, checks in spec["expect"]:
                if lab == "end":
                    nchecks += 1
                    reached.add(lineno)
                    for f in run_checks(checks, prog, cpu, bus, extra):
                        fails.append("line %d: at end (halted): %s" % (lineno, f))
            end_state = True
            break
    if trace_dir and trace is not None:
        os.makedirs(trace_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(path))[0]
        with open(os.path.join(trace_dir, base + ".trace"), "w") as f:
            f.write("\n".join(trace) + "\n")
    if spec["raises"] is not None:
        nchecks += 1
        if raised is None:
            fails.append("expected UndefinedBehaviour '%s', none raised" % spec["raises"])
        elif spec["raises"] not in raised:
            fails.append("raised '%s', want '%s'" % (raised, spec["raises"]))
        # Expects placed before the raise point must still be reached.
        for lineno, lab, k, checks in spec["expect"]:
            if lab != "end" and lineno not in reached:
                fails.append("line %d: expect %s#%d never reached" % (lineno, lab, k))
    elif raised is not None:
        fails.append("unexpected UndefinedBehaviour: %s" % raised)
    else:
        if not end_state:
            fails.append("did not reach the stop (%s)" % spec["stop"])
        for lineno, lab, k, checks in spec["expect"]:
            if lineno not in reached:
                fails.append("line %d: expect %s#%d never reached" % (lineno, lab, k))
    for addr, (lineno, lab) in undefined_at.items():
        nchecks += 1
        if addr not in seen_undef and raised is None:
            fails.append("line %d: instruction at %s not marked undefined" % (lineno, lab))
    for lineno, a, b, n in spec["cycles"]:
        nchecks += 1
        try:
            ca, cb = first_arrival[prog.symbols[a]], first_arrival[prog.symbols[b]]
        except KeyError:
            fails.append("line %d: cycles %s %s: label not reached" % (lineno, a, b))
            continue
        want = _val(n, prog)
        if cb - ca != want:
            fails.append("line %d: cycles %s..%s = %d, want %d" % (lineno, a, b, cb - ca, want))
    return name, fails, nchecks


# ------------------------------------------------------------ built-in sweeps
# Documented cycle counts per opcode, written from the S1 tables (p.53-58)
# and the wiki opcode pages, independently of cp1610.py's sequences.
def doc_cycles(op, taken=False, sdbd=False):
    if op <= 0x007 and op != 0x004:
        return 4
    if op == 0x004:
        return 12
    if op < 0x040:
        return 6
    if op < 0x080:
        return 8 if op & 4 else 6
    if op < 0x200:
        if op < 0x0C0 and (op & 7) >= 6:     # MOVR to R6/R7
            return 7
        return 6
    if op < 0x240:
        return 9 if taken else 7
    o, m = (op >> 6) & 7, (op >> 3) & 7
    if o == 1:
        return 11 if m == 0 else 9
    if m == 0:
        return 10
    if sdbd:
        return 10                             # wiki MVI@, ADD@...: 10 with SDBD
    return 11 if m == 6 else 8


def doc_interruptible(op):
    # wiki CP1610 table; S1 p.53, p.56 ("Not Interruptable"); SIN per S1 p.13
    if op <= 0x007:
        return op == 0x004
    if 0x040 <= op < 0x080:
        return False
    if 0x240 <= op < 0x280:
        return False
    return True


class _SweepBus(TestBus):
    def __init__(self):
        self.mem = [0] * 65536
        self.defined = None                # no fetch trap in the sweeps
        self.start, self.vector = 0x5000, 0x1004
        self.ranges, self.bext_true = {}, set()
        self.tci_n = self.sin_n = 0
        self.intak_log = []


def f_extra(op, sdbd):
    """docs/TIMING_FIT.md, family F (the console fit of 2026-11-01), written here apart from
    cp1610.f_extra: the jump family 13 cycles, PULR R7 (MVI@ R6, R7) 12, SDBD + MVI@ R4 or
    R5, R7 15 (the instruction's own 11 after SDBD's 4)."""
    if op == 0x004:
        return 1
    if op in (0x2B7,) or (sdbd and op in (0x2A7, 0x2AF)):
        return 1
    return 0


def sweep_cycles(timing="f"):
    """The cycles of every opcode: timing "doc" exactly the documents' (S1 / wiki and G82),
    timing "f" (the core's) the documents' plus F's extra cycle where TIMING_FIT says."""
    fails, n = [], 0
    for op in range(0x400):
        for sdbd in (False, True):
            if sdbd and not (op >= 0x280 and (op >> 3) & 7 not in (0,)):
                continue
            for taken in ((False, True) if 0x200 <= op < 0x240 else (False,)):
                bus = _SweepBus()
                base = 0x5000
                words = ([0x001] if sdbd else []) + [op, 0x0010, 0x0123]
                for k, w in enumerate(words):
                    bus.mem[base + k] = w
                cpu = cp1610.CP1610(bus, timing=timing)
                cpu.r[6] = 0x0300
                for r in range(1, 6):
                    cpu.r[r] = 0x0200 + r
                if 0x200 <= op < 0x240:
                    # make the condition true or false as wanted
                    if op & 0x10:
                        bus.bext_true = set(range(16)) if taken else set()
                    else:
                        want = taken
                        found = False
                        for nib in range(16):
                            cpu._set_flags_nibble(nib)
                            c = op & 7
                            S, Z, O, C = cpu.S, cpu.Z, cpu.O, cpu.C
                            t = (True, C, O, not S, Z, S ^ O, Z or (S ^ O), S ^ C)[c]
                            if (bool(t) != bool(op & 8)) == want:
                                found = True
                                break
                        if not found:
                            continue
                if sdbd:
                    cpu.step()
                ev = cpu.step()
                fx = f_extra(op, sdbd) if timing == "f" else 0
                want = doc_cycles(op, taken, sdbd) + fx
                n += 1
                if ev.cycles != want:
                    fails.append("op $%03X%s%s: %d cycles, want %d" % (
                        op, " sdbd" if sdbd else "", " taken" if taken else "",
                        ev.cycles, want))
                g = g82_cycles(op, taken, sdbd) + fx   # a third source (G82 p.45, p.52-53)
                if ev.cycles != g:
                    fails.append("op $%03X%s%s: %d cycles, G82 %d" % (
                        op, " sdbd" if sdbd else "", " taken" if taken else "",
                        ev.cycles, g))
                if ev.interruptible != doc_interruptible(op):
                    fails.append("op $%03X: interruptible=%s, want %s" % (
                        op, ev.interruptible, doc_interruptible(op)))
    return ("builtin: cycles (S1/wiki and G82%s) and interruptibility of all 1024 opcodes, timing %s"
            % (" + TIMING_FIT F" if timing == "f" else "", timing), fails, n)


def sweep_cycles_doc():
    return sweep_cycles("doc")


def sweep_buslog():
    """Every cycle of every opcode appears exactly once in the bus log."""
    fails, n = [], 0
    for op in range(0x400):
        bus = _SweepBus()
        for k, w in enumerate([op, 0x0010, 0x0123]):
            bus.mem[0x5000 + k] = w
        cpu = cp1610.CP1610(bus, buslog=True)
        cpu.r[6] = 0x0300
        ev = cpu.step()
        cycles = [c for c, *_ in cpu.buslog]
        n += 1
        if cycles != list(range(ev.cycle, ev.cycle + ev.cycles)):
            fails.append("op $%03X: bus log cycles %s for %d cycles" % (op, cycles, ev.cycles))
        if cpu.buslog[0][1] != "BAR" or cpu.buslog[2][1] != "DTB":
            fails.append("op $%03X: does not start with a fetch" % op)
    return "builtin: bus log covers every cycle", fails, n


# Bus phase sequences, written from the wiki Bus_Phases tables and S1 p.30
# (direct mode) and p.35 (interrupt sequence).
F = ["BAR", "NACT", "DTB", "NACT"]
PHASES = [
    ("NOP", [0x034], F + ["NACT", "NACT"]),
    ("SLL R0, 2", [0x04C], F + ["NACT"] * 4),
    ("MOVR R0, R7", [0x087], F + ["NACT"] * 3),
    ("MVI direct", [0x280, 0x0200], F + ["BAR", "NACT", "ADAR", "NACT", "DTB", "NACT"]),
    ("MVO direct", [0x240, 0x0200], F + ["BAR", "NACT", "ADAR", "NACT", "DW", "DWS", "NACT"]),
    ("MVO@ R0, R1", [0x248], F + ["BAR", "NACT", "DW", "DWS", "NACT"]),
    ("MVI@ R1, R0", [0x288], F + ["BAR", "NACT", "DTB", "NACT"]),
    ("MVII", [0x2B8, 0x1234], F + F),
    # TIMING_FIT F: one NACT more at the end of a jump, PULR R7, SDBD + MVI@ R4 / R5, R7
    ("J", [0x004, 0x0300, 0x0000], F + F + F + ["NACT"]),
    ("PULR R7", [0x2B7], F + ["NACT"] * 3 + F + ["NACT"]),
    ("B taken", [0x200, 0x0000], F + F + ["NACT"]),
    ("NOPP", [0x208, 0x0000], F + ["BAR", "NACT", "DTB"]),
    ("SDBD; MVI@ R4, R0", [0x001, 0x2A0],
     F + F + ["BAR", "NACT", "DTB", "BAR", "NACT", "DTB"]),
    ("SDBD; MVI@ R4, R7", [0x001, 0x2A7],
     F + F + ["BAR", "NACT", "DTB", "BAR", "NACT", "DTB", "NACT"]),
]


def sweep_phases():
    fails, n = [], 0
    for name, words, want in PHASES:
        bus = _SweepBus()
        for k, w in enumerate(words):
            bus.mem[0x5000 + k] = w
        cpu = cp1610.CP1610(bus, buslog=True)
        cpu.r[1] = cpu.r[4] = 0x0200
        cpu.step()
        if words[0] == 0x001:
            cpu.step()
        got = [ph for _, ph, _, _ in cpu.buslog]
        n += 1
        if got != want:
            fails.append("%s: %s, want %s" % (name, " ".join(got), " ".join(want)))
    # interrupt sequence, S1 p.35
    bus = _SweepBus()
    bus.mem[0x5000] = 0x034
    bus.ranges = {"intrm": [(0, None)]}
    cpu = cp1610.CP1610(bus, buslog=True)
    cpu.I = 1
    cpu.r[6] = 0x0300
    cpu.step()
    cpu.buslog.clear()
    ev = cpu.step()
    got = [ph for _, ph, _, _ in cpu.buslog]
    want = ["INTAK", "NACT", "DW", "DWS", "NACT", "IAB", "NACT", "NACT", "NACT"]
    n += 1
    if ev.kind != "intr" or got != want:
        fails.append("interrupt: %s %s" % (ev.kind, " ".join(got)))
    return "builtin: bus phase sequences", fails, n


def sweep_roundtrip():
    """Disassemble every opcode and assemble the text again."""
    fails, n = [], 0
    for op in range(0x400):
        if op == 0x004:
            seqs = [[0x004, bb << 8 | 0x14 << 2 | ii, 0x123]
                    for bb in range(4) for ii in range(3)]
        elif 0x200 <= op < 0x240:
            seqs = [[op, 0x0005]] if (op & 0x1F) != 8 else [[op, 0]]
            if op & 0x2F == 0x28:   # NOPP backward: assembles as forward
                continue
        elif op >= 0x240 and ((op >> 3) & 7) in (0, 7):
            seqs = [[op, 0x0234]]
        else:
            seqs = [[op]]
        for ws in seqs:
            text, length = cp1610.disassemble(ws + [0, 0], 0x5000)
            src = "  ORG $5000\n  " + text + "\n"
            n += 1
            try:
                prog = as1610.assemble(src)
            except as1610.AsmError as e:
                fails.append("$%03X '%s': %s" % (op, text, e))
                continue
            got = [prog.words.get(0x5000 + k) for k in range(length)]
            if got != ws[:length]:
                fails.append("$%03X '%s' -> %s" % (op, text, " ".join(
                    "%04X" % w if w is not None else "-" for w in got)))
    return "builtin: disassemble/assemble round trip", fails, n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-k", help="only tests whose path contains this")
    ap.add_argument("--trace", help="write one .trace per test into this directory")
    ap.add_argument("--no-builtin", action="store_true")
    a = ap.parse_args(argv)
    files = a.files or sorted(glob.glob(os.path.join(TEST_DIR, "*.asm")))
    if a.k:
        files = [f for f in files if a.k in f]
    results = []
    for f in files:
        results.append(run_asm_test(f, a.trace, a.verbose))
    if not a.no_builtin and not a.files and not a.k:
        for fn in (sweep_cycles, sweep_cycles_doc, sweep_buslog, sweep_phases, sweep_roundtrip):
            results.append(fn())
    bad = 0
    total = 0
    for name, fails, n in results:
        total += n
        if fails:
            bad += 1
            print("FAIL %s" % name)
            for f in fails[:20]:
                print("     %s" % f)
            if len(fails) > 20:
                print("     ... %d more" % (len(fails) - 20))
        elif a.verbose or True:
            print("ok   %s (%d checks)" % (name, n))
    print("%d of %d tests passed, %d checks" % (len(results) - bad, len(results), total))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
