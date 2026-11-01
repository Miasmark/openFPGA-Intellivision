#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""cp1610: instruction-level model of the GI CP1610 with a bus-phase log.

Written from the documents, not from any emulator's code:
  S1   GI CP-1600 Microprocessor Users Manual, May 1975: pins p.12-14, state
       flow p.21-25, timing diagrams p.27-37 (interrupt sequence p.35),
       instruction formats p.44-52, instruction set and cycles p.53-58.
  wiki wiki.intellivision.us: CP1610 (interruptibility, flags), Bus_Phases,
       Double_Byte_Data, the opcode pages.
MAME's cp1610.cpp (BSD-3) was read only to cross-check facts; where it
differs it is listed in docs/CPU_NOTES.md, with the choice made here.

Model
  - Registers R0-R7 (R6 stack pointer, R7 program counter), flags S Z O C,
    interrupt enable I, double byte data D, the "previous instruction was
    interruptible" latch, the INTRM edge latch.
  - One call to step() runs one instruction, or one interrupt sequence, or
    one bus-request wait, and returns a record (see Event).
  - Every bus access is made through the bus object at the cycle of its bus
    phase; with buslog=True each phase (BAR, NACT, ADAR, DTB, DW, DWS, IAB,
    INTAK) is recorded with its cycle, so the RTL CPU can be checked in
    lockstep later.
  - Cycle counts are the documented ones (S1 p.53-58, wiki opcode pages);
    the phase sequences that make them up are in _seq_* below. Timing "f"
    (the default, the core's) adds the console fit's three longer cases
    (f_extra; docs/TIMING_FIT.md); timing "doc" keeps the documents' counts.

Bus object (duck typed; only read and write are required):
  read(addr, cycle, kind) -> int    kind: 'fetch', 'operand', 'adar', 'data'
  write(addr, value, cycle)
  iab(cycle, reason) -> address     reason 'reset' or 'intr' (default $1000 /
                                    $1004, the Intellivision's vectors)
  intak(addr, cycle)                interrupt acknowledge with the stack address
  intrm(cycle) -> bool              True while INTRM* is asserted (low)
  intr(cycle) -> bool               True while INTR* is asserted (low)
  busrq(cycle) -> bool              True while BUSRQ* is asserted (low)
  bext(cond, cycle) -> bool         external branch condition (EBCI)
  tci(cycle), sin(cycle)            TCI and PCIT* output pulses
Instead of intrm/intr/busrq methods, a host may set cpu.intrm_line etc.

Trace: trace_line(event) gives one line per instruction:
  cycle PC  words  disassembly  R0..R7  SZOC  ID  cycles
"""

import argparse
import sys

__all__ = ["CP1610", "Event", "UndefinedBehaviour", "disassemble",
           "trace_header", "trace_line", "INTERRUPT_CYCLES", "f_extra"]

S_FLAG, Z_FLAG, O_FLAG, C_FLAG = 8, 4, 2, 1     # SZOC, as GSWD's nibble
INTERRUPT_CYCLES = 9    # S1 p.35: INTAK NACT DW DWS NACT IAB NACT NACT NACT
BUSRQ_EXIT = 2          # NACT cycles after BUSRQ* is seen high (S1 p.36, G82 p.29)
TIMINGS = ("f", "doc")  # CP1610(timing=): the console's family F, or the documents' counts


def f_extra(op, dbd):
    """The cycles timing "f" adds to an instruction's documented count (docs/TIMING_FIT.md,
    the console fit F of 2026-11-01; one NACT at the end of the instruction):
      J, JE, JD, JSR, JSRE, JSRD ($004)     13, not 12 (the fit lengthened the whole family)
      PULR R7 (MVI@ R6, R7)                  12, not 11
      SDBD + MVI@ R4 / R5, R7                15, not 14 (the EXEC dispatcher's jump; hw_frame2)
    The console's interrupt path (each ISR has one JSR and one PULR R7) and hw_frame2's SDBD
    JUMP 15 need them; which other jumps or loads into R7 are longer too is not observable
    (TIMING_FIT "Not observable")."""
    if op == 0x004:
        return 1
    if op >= 0x240 and (op >> 6) & 7 == 2 and op & 7 == 7:
        m = (op >> 3) & 7
        if m == 6 or (dbd and m in (4, 5)):
            return 1
    return 0

BRANCH_NAMES = ["B", "BC", "BOV", "BPL", "BEQ", "BLT", "BLE", "BUSC",
                "NOPP", "BNC", "BNOV", "BMI", "BNEQ", "BGE", "BGT", "BESC"]
SHIFT_NAMES = ["SWAP", "SLL", "RLC", "SLLC", "SLR", "SAR", "RRC", "SARC"]
REGREG_NAMES = {2: "MOVR", 3: "ADDR", 4: "SUBR", 5: "CMPR", 6: "ANDR", 7: "XORR"}
EXT_NAMES = {1: "MVO", 2: "MVI", 3: "ADD", 4: "SUB", 5: "CMP", 6: "AND", 7: "XOR"}
IMPLIED_NAMES = {0: "HLT", 1: "SDBD", 2: "EIS", 3: "DIS", 5: "TCI",
                 6: "CLRC", 7: "SETC"}
SINGLE_NAMES = {1: "INCR", 2: "DECR", 3: "COMR", 4: "NEGR", 5: "ADCR", 7: "RSWD"}


class UndefinedBehaviour(Exception):
    """Raised in strict mode for a case the documents leave undefined."""


class Event:
    """What one step() did."""
    __slots__ = ("kind", "cycle", "pc", "words", "cycles", "text", "regs",
                 "flags", "i", "d", "undefined", "interruptible")

    def __init__(self, kind, cycle, pc):
        self.kind = kind          # 'insn', 'intr', 'busak', 'halt'
        self.cycle = cycle        # cycle at the start
        self.pc = pc              # PC at the start
        self.words = []
        self.cycles = 0
        self.text = ""
        self.undefined = None
        self.interruptible = True

    def __repr__(self):
        return "<Event %s @%d pc=%04X +%d %s>" % (self.kind, self.cycle,
                                                  self.pc, self.cycles, self.text)


# ---------------------------------------------------------------- disassembly
def _r(n):
    return "R%d" % n


def disassemble(words, pc=0, sdbd=False):
    """Disassemble the instruction at words[0] (words = the next 1-3 words).
    Returns (text, length). Syntax follows S1 and as1610.py."""
    w = words[0] & 0x3FF
    if w == 0x004:
        a2 = words[1] if len(words) > 1 else 0
        a3 = words[2] if len(words) > 2 else 0
        bb, ii = (a2 >> 8) & 3, a2 & 3
        addr = ((a2 >> 2) & 0x3F) << 10 | (a3 & 0x3FF)
        if ii == 3:
            return "JUMP? $%04X (BB=%d II=3)" % (addr, bb), 3
        if bb == 3:
            return "%s $%04X" % (("J", "JE", "JD")[ii], addr), 3
        return "%s R%d, $%04X" % (("JSR", "JSRE", "JSRD")[ii], bb + 4, addr), 3
    if w < 0x008:
        return IMPLIED_NAMES[w], 1
    if w < 0x040:
        op, r = w >> 3, w & 7
        if op == 6:
            if r < 4:
                return "GSWD R%d" % r, 1
            return ("NOP" if r < 6 else "SIN") + (" 1" if r & 1 else ""), 1
        return "%s R%d" % (SINGLE_NAMES[op], r), 1
    if w < 0x080:
        op, n, r = (w >> 3) & 7, (w >> 2) & 1, w & 3
        return "%s R%d%s" % (SHIFT_NAMES[op], r, ", 2" if n else ""), 1
    if w < 0x200:
        op, s, d = w >> 6, (w >> 3) & 7, w & 7
        if op == 2 and s == d:
            return "TSTR R%d" % s, 1
        if op == 2 and d == 7:
            return "JR R%d" % s, 1
        if op == 7 and s == d:
            return "CLRR R%d" % d, 1
        return "%s R%d, R%d" % (REGREG_NAMES[op], s, d), 1
    if w < 0x240:
        disp = words[1] if len(words) > 1 else 0
        rev, ext, cond = (w >> 5) & 1, (w >> 4) & 1, w & 15
        tgt = (pc + 2 + (disp ^ (0xFFFF if rev else 0))) & 0xFFFF
        if ext:
            return "BEXT $%04X, %d" % (tgt, cond), 2
        if cond == 8:
            return "NOPP", 2
        return "%s $%04X" % (BRANCH_NAMES[cond], tgt), 2
    op, m, r = (w >> 6) & 7, (w >> 3) & 7, w & 7
    name = EXT_NAMES[op]
    nxt = words[1] if len(words) > 1 else 0
    if m == 0:
        if op == 1:
            return "MVO R%d, $%04X" % (r, nxt), 2
        return "%s $%04X, R%d" % (name, nxt, r), 2
    if m == 7:
        if op == 1:
            return "MVOI R%d, $%04X" % (r, nxt), 2
        if sdbd:
            v = (nxt & 0xFF) | ((words[2] if len(words) > 2 else 0) & 0xFF) << 8
            return "%sI #$%04X, R%d" % (name, v, r), 3
        return "%sI #$%04X, R%d" % (name, nxt, r), 2
    if m == 6 and op == 1:
        return "PSHR R%d" % r, 1
    if m == 6 and op == 2:
        return "PULR R%d" % r, 1
    if op == 1:
        return "MVO@ R%d, R%d" % (r, m), 1
    return "%s@ R%d, R%d" % (name, m, r), 1


# --------------------------------------------------------------------- model
class _DefaultBus:
    def __init__(self):
        self.mem = [0] * 65536

    def read(self, addr, cycle, kind):
        return self.mem[addr]

    def write(self, addr, value, cycle):
        self.mem[addr] = value


class CP1610:
    """Options:
      strict      raise UndefinedBehaviour for undocumented cases (default:
                  apply the choice listed in docs/CPU_NOTES.md and mark the
                  event's .undefined)
      sdbd_r6     'wiki' (default): SDBD + indirect through R6 decrements R6
                  once and reads that location twice, 10 cycles (wiki
                  Undocumented_SDBD_Behavior, MVI@); 'mame': decrements twice,
                  reads both, 13 cycles (MAME cp1610.cpp sdbd_*_d)
      hlt         'manual' (default): HLT stops the CPU after the next
                  interruptible instruction (G82 p.33); 'immediate':
                  stops at once (wiki HLT)
      buslog      record every bus phase in self.buslog as
                  (cycle, phase, addr, data)
      timing      'f' (default): the console's family F (docs/TIMING_FIT.md; the
                  core's cp1610.sv): f_extra() adds one NACT at the end of the
                  jumps ($004), PULR R7 and SDBD + MVI@ R4 / R5, R7; 'doc': the
                  documented counts (S1, G82, the wiki), as MAME's CPU runs them
                  (the MAME comparisons: tools/intv_system.py mode "mame",
                  tools/lockstep.py)
    """

    def __init__(self, bus=None, strict=False, sdbd_r6="wiki", hlt="manual",
                 buslog=False, timing="f"):
        if sdbd_r6 not in ("wiki", "mame"):
            raise ValueError("sdbd_r6 must be 'wiki' or 'mame'")
        if hlt not in ("manual", "immediate"):
            raise ValueError("hlt must be 'manual' or 'immediate'")
        if timing not in TIMINGS:
            raise ValueError("timing must be 'f' or 'doc'")
        self.timing = timing
        self.bus = bus if bus is not None else _DefaultBus()
        self.strict = strict
        self.sdbd_r6 = sdbd_r6
        self.hlt_mode = hlt
        self.buslog = [] if buslog else None
        self.intrm_line = False
        self.intr_line = False
        self.busrq_line = False
        self.reset()

    # -- state ------------------------------------------------------------
    def reset(self):
        # S1 p.21: registers and status are undefined after MSYNC; the
        # interrupt system is disabled. The model starts them at zero.
        self.r = [0] * 8
        self.S = self.Z = self.O = self.C = 0
        self.I = 0
        self.D = 0
        self.cycle = 0
        self.interruptible = False   # no check before the first instruction
        self.intrm_pending = False
        self.intrm_prev = False
        self.intr_pending = False
        self.intr_prev = False
        self.halt_pending = False
        self.halted = False
        self._und = None
        # S1 p.21: after MSYNC the CPU issues IAB and loads the PC from the bus.
        self.r[7] = self._iab("reset") & 0xFFFF

    def state(self):
        """A dict of all run-time state (for save-state checks)."""
        return {"r": list(self.r), "S": self.S, "Z": self.Z, "O": self.O,
                "C": self.C, "I": self.I, "D": self.D, "cycle": self.cycle,
                "interruptible": self.interruptible,
                "intrm_pending": self.intrm_pending, "intrm_prev": self.intrm_prev,
                "intr_pending": self.intr_pending, "intr_prev": self.intr_prev,
                "halt_pending": self.halt_pending, "halted": self.halted}

    def set_state(self, st):
        for k, v in st.items():
            setattr(self, k, list(v) if k == "r" else v)

    @property
    def flags(self):
        return self.S << 3 | self.Z << 2 | self.O << 1 | self.C

    def _set_flags_nibble(self, n):
        self.S, self.Z, self.O, self.C = (n >> 3) & 1, (n >> 2) & 1, (n >> 1) & 1, n & 1

    # -- bus helpers -------------------------------------------------------
    def _log(self, t, phase, addr=None, data=None):
        if self.buslog is not None:
            self.buslog.append((self.cycle + t, phase, addr, data))

    def _hook(self, name, *args, default=None):
        f = getattr(self.bus, name, None)
        return f(*args) if f is not None else default

    def _iab(self, reason, t=0):
        default = 0x1000 if reason == "reset" else 0x1004
        v = self._hook("iab", self.cycle + t, reason, default=default)
        return default if v is None else v

    def _line(self, name, attr, t=0):
        f = getattr(self.bus, name, None)
        if f is not None:
            return bool(f(self.cycle + t))
        return bool(getattr(self, attr))

    # Each *_seq helper logs the phases of one documented bus sequence at
    # offset self._t, makes the bus call at its phase's cycle, and advances
    # self._t. The read helpers return the data read.
    def _idle(self, n):
        for k in range(n):
            self._log(self._t + k, "NACT")
        self._t += n

    def _read_seq(self, addr, kind, tail=True):
        # wiki Bus_Phases "Instruction Fetch or Indirect/Immediate-Mode Data
        # Read"; S1 p.29-30: BAR, NACT, DTB, NACT (4 cycles)
        t = self._t
        self._log(t, "BAR", addr)
        self._log(t + 1, "NACT")
        v = self.bus.read(addr, self.cycle + t + 2, kind) & 0xFFFF
        self._log(t + 2, "DTB", addr, v)
        if tail:
            self._log(t + 3, "NACT")
        self._t += 4 if tail else 3
        return v

    def _read2_seq(self, a1, a2):
        # wiki Bus_Phases "Indirect/Immediate Addressing Mode Read with SDBD":
        # BAR NACT DTB BAR NACT DTB (6 cycles), low byte first
        t = self._t
        self._log(t, "BAR", a1)
        self._log(t + 1, "NACT")
        lo = self.bus.read(a1, self.cycle + t + 2, "data") & 0xFFFF
        self._log(t + 2, "DTB", a1, lo)
        self._log(t + 3, "BAR", a2)
        self._log(t + 4, "NACT")
        hi = self.bus.read(a2, self.cycle + t + 5, "data") & 0xFFFF
        self._log(t + 5, "DTB", a2, hi)
        self._t += 6
        self._raw2 = (lo, hi)
        return (lo & 0xFF) | (hi & 0xFF) << 8

    def _write_seq(self, addr, v):
        # wiki Bus_Phases "Indirect/Immediate-Mode Data Write": BAR NACT DW
        # DWS NACT (5 cycles); the device sees the data from DW on.
        t = self._t
        self._log(t, "BAR", addr)
        self._log(t + 1, "NACT")
        self._log(t + 2, "DW", addr, v)
        self.bus.write(addr, v & 0xFFFF, self.cycle + t + 2)
        self._log(t + 3, "DWS", addr, v)
        self._log(t + 4, "NACT")
        self._t += 5

    def _direct_addr_seq(self, pc):
        # S1 p.30 and wiki Bus_Phases "Direct Addressing Mode": BAR(PC) NACT
        # ADAR NACT; the word at PC becomes the address of the next phase.
        t = self._t
        self._log(t, "BAR", pc)
        self._log(t + 1, "NACT")
        a = self.bus.read(pc, self.cycle + t + 2, "adar") & 0xFFFF
        self._log(t + 2, "ADAR", pc, a)
        self._log(t + 3, "NACT")
        self._t += 4
        return a

    def _direct_read_seq(self, pc):
        a = self._direct_addr_seq(pc)
        t = self._t
        v = self.bus.read(a, self.cycle + t, "data") & 0xFFFF
        self._log(t, "DTB", a, v)
        self._log(t + 1, "NACT")
        self._t += 2
        return a, v

    def _direct_write_seq(self, pc, v):
        a = self._direct_addr_seq(pc)
        t = self._t
        self._log(t, "DW", a, v)
        self.bus.write(a, v & 0xFFFF, self.cycle + t)
        self._log(t + 1, "DWS", a, v)
        self._log(t + 2, "NACT")
        self._t += 3
        return a

    def _undefined(self, what):
        if self.strict:
            raise UndefinedBehaviour("%04X: %s" % (self.r[7], what))
        self._und = what

    # -- ALU -----------------------------------------------------------------
    def _sz(self, v):
        self.S = (v >> 15) & 1
        self.Z = int(v == 0)

    def _add(self, a, b, cin=0):
        """a + b + cin with S Z O C (S1 p.45: C = carry out, OV = two's
        complement overflow). Subtraction is a + ~b + 1 (S1 p.45)."""
        full = a + b + cin
        res = full & 0xFFFF
        self.C = (full >> 16) & 1
        self.O = int(((a ^ res) & (b ^ res) & 0x8000) != 0)
        self._sz(res)
        return res

    def _sub(self, a, b):
        return self._add(a, b ^ 0xFFFF, 1)

    # -- execution -----------------------------------------------------------
    def step(self):
        """Run one instruction, interrupt sequence or bus-request wait."""
        if self.halted:
            ev = Event("halt", self.cycle, self.r[7])
            self._t = 0
            self._idle(1)
            ev.cycles = 1
            self.cycle += 1
            ev.text = "(halted)"
            self._fill(ev)
            return ev
        if self.interruptible:
            ev = self._boundary()
            if ev is not None:
                return ev
        return self._execute()

    def run(self, until_cycle=None, max_steps=None, stop_pc=None):
        """Step until a limit; returns the list of events."""
        evs = []
        while True:
            if until_cycle is not None and self.cycle >= until_cycle:
                break
            if max_steps is not None and len(evs) >= max_steps:
                break
            if stop_pc is not None and self.r[7] == stop_pc and evs and \
                    evs[-1].kind != "busak":
                break
            evs.append(self.step())
        return evs

    def _sample_irq(self):
        # wiki CP1610 (Signal Pins): a high-to-low transition requests an
        # interrupt; if the line goes high again before it is taken, the
        # request is dropped. Sampled at each instruction boundary.
        lv = self._line("intrm", "intrm_line")
        if lv and not self.intrm_prev:
            self.intrm_pending = True
        if not lv:
            self.intrm_pending = False
        self.intrm_prev = lv
        lv = self._line("intr", "intr_line")
        if lv and not self.intr_prev:
            self.intr_pending = True
        if not lv:
            self.intr_pending = False
        self.intr_prev = lv

    def _boundary(self):
        """After an interruptible instruction: bus request first, then
        interrupts (S1 p.24-25)."""
        if self._line("busrq", "busrq_line"):
            ev = Event("busak", self.cycle, self.r[7])
            self._t = 0
            n = 0
            # S1 p.24: BUSAK* low and NACT on the bus until BUSRQ* goes high.
            while self._line("busrq", "busrq_line", n):
                self._log(n, "NACT")
                n += 1
                if n > 1 << 24:
                    raise RuntimeError("BUSRQ held forever")
            # S1 p.36, G82 Fig. 16 (p.29), O81 p.2-13: the cycle whose TS1
            # samples BUSRQ* high and one more stay NACT, BUSAK* still low;
            # BAR (or INTAK) and BUSAK* high come in the cycle after them.
            for k in range(BUSRQ_EXIT):
                self._log(n + k, "NACT")
            self._t = n + BUSRQ_EXIT
            ev.cycles = n + BUSRQ_EXIT
            ev.text = "BUSAK %d" % n
            self.cycle += n + BUSRQ_EXIT
            self._sample_irq()
            self._fill(ev)
            # The boundary stays open: the next step() checks BUSRQ again,
            # then the interrupt requests (S1 p.25: bus requests first).
            self.interruptible = True
            return ev
        return self._take_irq()

    def _take_irq(self):
        if not (self.intr_pending or (self.intrm_pending and self.I)):
            return None
        reason = "intr"
        ev = Event("intr", self.cycle, self.r[7])
        self._t = 0
        sp, pc = self.r[6], self.r[7]
        # S1 p.24-25, p.35: INTAK with the stack pointer, DW/DWS the PC,
        # IAB loads the new PC, then three NACTs before the next fetch.
        self._log(0, "INTAK", sp)
        self._hook("intak", sp, self.cycle)
        self._log(1, "NACT")
        self._t = 2
        self._log(2, "DW", sp, pc)
        self.bus.write(sp, pc, self.cycle + 2)
        self._log(3, "DWS", sp, pc)
        self._log(4, "NACT")
        vec = self._iab(reason, 5) & 0xFFFF
        self._log(5, "IAB", None, vec)
        self._t = 6
        self._idle(3)
        assert self._t == INTERRUPT_CYCLES
        self.r[6] = (sp + 1) & 0xFFFF
        self.r[7] = vec
        if self.intr_pending:
            self.intr_pending = False
        else:
            self.intrm_pending = False
        ev.cycles = INTERRUPT_CYCLES
        ev.text = "INTERRUPT -> $%04X" % vec
        self.cycle += INTERRUPT_CYCLES
        self.interruptible = False
        self._fill(ev)
        return ev

    def _fill(self, ev):
        ev.regs = list(self.r)
        ev.flags = self.flags
        ev.i, ev.d = self.I, self.D

    def _execute(self):
        pc0 = self.r[7]
        ev = Event("insn", self.cycle, pc0)
        self._t = 0
        self._und = None
        self._words = words = []

        def fetch(kind="operand"):
            a = self.r[7]
            v = self._read_seq(a, kind)
            words.append(v)
            self.r[7] = (a + 1) & 0xFFFF
            return v

        op = fetch("fetch") & 0x3FF      # bits 15-10 are "future use" (S1 p.46)
        dbd = self.D
        self.D = 0                      # D lasts for one instruction (wiki Double_Byte_Data)
        intr_ok = True
        r = self.r

        if op < 0x008:
            intr_ok = self._implied(op, words, fetch)
        elif op < 0x040:
            o, n = op >> 3, op & 7
            self._idle(2)
            if o == 1:      # INCR
                r[n] = (r[n] + 1) & 0xFFFF
                self._sz(r[n])
            elif o == 2:    # DECR
                r[n] = (r[n] - 1) & 0xFFFF
                self._sz(r[n])
            elif o == 3:    # COMR
                r[n] ^= 0xFFFF
                self._sz(r[n])
            elif o == 4:    # NEGR: two's complement, ALU 0 + ~x + 1 (wiki NEGR)
                r[n] = self._add(0, r[n] ^ 0xFFFF, 1)
            elif o == 5:    # ADCR
                r[n] = self._add(r[n], 0, self.C)
            elif o == 6:
                if n < 4:   # GSWD: SZOC0000SZOC0000 (S1 p.56)
                    f = self.flags << 4
                    r[n] = f << 8 | f
                elif n < 6:
                    pass    # NOP
                else:       # SIN: pulse on PCIT* (S1 p.13); interruptible
                    self._hook("sin", self.cycle + 2)
            elif o == 7:    # RSWD: bits 7-4 to S Z O C (S1 p.56)
                self._set_flags_nibble((r[n] >> 4) & 15)
        elif op < 0x080:
            intr_ok = False                   # S1 p.53: shifts not interruptible
            self._shift((op >> 3) & 7, (op >> 2) & 1, op & 3)
        elif op < 0x200:
            o, s, d = op >> 6, (op >> 3) & 7, op & 7
            self._idle(2)
            if o == 2:      # MOVR, +1 cycle with R6/R7 as destination (S1 p.53)
                r[d] = r[s]
                self._sz(r[d])
                if d >= 6:
                    self._idle(1)
            elif o == 3:
                r[d] = self._add(r[d], r[s])
            elif o == 4:
                r[d] = self._sub(r[d], r[s])
            elif o == 5:
                self._sub(r[d], r[s])
            elif o == 6:
                r[d] &= r[s]
                self._sz(r[d])
            else:
                r[d] ^= r[s]
                self._sz(r[d])
        elif op < 0x240:
            self._branch(op, fetch)
        else:
            intr_ok = self._external(op, dbd, fetch)

        if self.D and op != 0x001:
            self.D = 0
        if self.timing == "f" and f_extra(op, dbd):
            self._idle(1)               # TIMING_FIT F: one more NACT at the end
        ev.words = words
        ev.cycles = self._t
        ev.text = disassemble(words + [0, 0], pc0, sdbd=bool(dbd))[0]
        ev.undefined = self._und
        ev.interruptible = intr_ok
        self.cycle += self._t
        # G82 p.33 "Halt after next interruptable instruction is executed"
        # (S1 p.56: "after next instruction"): an earlier HLT stops the CPU
        # at the end of the first interruptible instruction after it, as
        # STPST* does (G82 p.11); HLT itself is not interruptible, so a
        # second HLT runs on. docs/CPU_NOTES.md row 7.
        if self.halt_pending and intr_ok:
            self.halt_pending = False
            self.halted = True
        # Sample the request lines at every boundary, act only after an
        # interruptible instruction (wiki CP1610 Interruptibility).
        self._sample_irq()
        self.interruptible = intr_ok and not self.halted
        self._fill(ev)
        return ev

    def _implied(self, op, words, fetch):
        """$000-$007: 4 cycles (fetch only), not interruptible, except the
        jump family at $004 (12 cycles, interruptible). S1 p.56."""
        if op == 0x000:     # HLT
            if self.hlt_mode == "immediate":
                self.halted = True
            else:
                self.halt_pending = True
            return False
        if op == 0x001:     # SDBD
            self.D = 1
            return False
        if op == 0x002:
            self.I = 1
            return False
        if op == 0x003:
            self.I = 0
            return False
        if op == 0x005:     # TCI: pulse on the TCI pin
            self._hook("tci", self.cycle + 3)
            return False
        if op == 0x006:
            self.C = 0
            return False
        if op == 0x007:
            self.C = 1
            return False
        # $004: J/JE/JD/JSR/JSRE/JSRD. S1 p.52: word 2 = BB AAAAAA II, word 3
        # = AAAAAAAAAA. Return address (PC+3) goes to R(4+BB) when BB != 3.
        a2 = fetch() & 0x3FF
        a3 = fetch() & 0x3FF
        bb, ii = a2 >> 8, a2 & 3
        target = ((a2 >> 2) & 0x3F) << 10 | a3
        if ii == 3:
            self._undefined("jump with II=11 (reserved; wiki Jump, S1 p.52)")
        if bb != 3:
            self.r[4 + bb] = self.r[7]
        self.r[7] = target
        if ii in (1, 3):    # II=11 enables interrupts as JE (the owner's Model 2609, hw_cpuodd, 2026-10-31)
            self.I = 1
        elif ii == 2:
            self.I = 0
        return True

    def _shift(self, o, n, rr):
        """S1 p.50, p.53; wiki SWAP/SLL/RLC/SLLC/SLR/SAR/RRC/SARC. 6 cycles,
        8 for two positions. Right shifts and SWAP take S from bit 7."""
        self._idle(4 if n else 2)
        v = self.r[rr]
        s7 = False
        if o == 0:          # SWAP; twice = low byte into both halves (wiki SWAP)
            v = (v & 0xFF) << 8 | (v & 0xFF) if n else (v << 8 | v >> 8) & 0xFFFF
            s7 = True
        elif o == 1:        # SLL
            v = (v << (n + 1)) & 0xFFFF
        elif o == 2:        # RLC through C (and O for two)
            if n:
                nv = (v << 2 | self.C << 1 | self.O) & 0xFFFF
                self.C, self.O = (v >> 15) & 1, (v >> 14) & 1
            else:
                nv = (v << 1 | self.C) & 0xFFFF
                self.C = (v >> 15) & 1
            v = nv
        elif o == 3:        # SLLC
            if n:
                self.C, self.O = (v >> 15) & 1, (v >> 14) & 1
                v = (v << 2) & 0xFFFF
            else:
                self.C = (v >> 15) & 1
                v = (v << 1) & 0xFFFF
        elif o == 4:        # SLR
            v >>= n + 1
            s7 = True
        elif o == 5:        # SAR
            sign = v & 0x8000
            for _ in range(n + 1):
                v = v >> 1 | sign
            s7 = True
        elif o == 6:        # RRC: C into bit 15 (one); O to 15, C to 14 (two)
            if n:
                nv = v >> 2 | self.O << 15 | self.C << 14
                self.C, self.O = v & 1, (v >> 1) & 1
            else:
                nv = v >> 1 | self.C << 15
                self.C = v & 1
            v = nv
            s7 = True
        else:               # SARC
            sign = v & 0x8000
            if n:
                self.C, self.O = v & 1, (v >> 1) & 1
            else:
                self.C = v & 1
            for _ in range(n + 1):
                v = v >> 1 | sign
            s7 = True
        self.r[rr] = v
        self.Z = int(v == 0)
        self.S = (v >> 7) & 1 if s7 else (v >> 15) & 1

    def _branch(self, op, fetch):
        """S1 p.47, p.54: displacement word added to PC+2 (forward), or its
        one's complement added (backward). 9 cycles taken, 7 not taken."""
        rev, ext, cond = (op >> 5) & 1, (op >> 4) & 1, op & 15
        if ext:
            taken = bool(self._hook("bext", cond, self.cycle + self._t,
                                    default=False))
        else:
            c = cond & 7
            S, Z, O, C = self.S, self.Z, self.O, self.C
            t = (True, C, O, not S, Z, S ^ O, Z or (S ^ O), S ^ C)[c]
            taken = bool(t) != bool(cond & 8)
        if taken:
            disp = fetch()
            self._idle(1)
            self.r[7] = (self.r[7] + (disp ^ (0xFFFF if rev else 0))) & 0xFFFF
        else:
            # 7 cycles: the trailing NACT of the displacement read is not
            # there (estimated; wiki Branch gives only the count).
            a = self.r[7]
            v = self._read_seq(a, "operand", tail=False)
            self._words.append(v)
            self.r[7] = (a + 1) & 0xFFFF

    def _external(self, op, dbd, fetch):
        """$240-$3FF: MVO MVI ADD SUB CMP AND XOR in modes direct (0),
        indirect R1-R3, post-increment R4/R5, stack R6, immediate R7.
        S1 p.46-49, p.55-58."""
        o, m, rg = (op >> 6) & 7, (op >> 3) & 7, op & 7
        r = self.r
        if o == 1:          # MVO: not interruptible (wiki CP1610 table)
            if dbd:
                self._undefined("SDBD before MVO (S1 p.49: double byte data is for reads)")
            v = r[rg]
            if m == 0:      # MVO SSS, A: 11 cycles
                if rg == 7:     # R7 is written after the address word's fetch: the next PC
                    v = (r[7] + 1) & 0xFFFF     # (MAME cp1610.cpp cp1610_mvo; step 9, Mind Strike)
                self._words.append(self._direct_write_seq(r[7], v))
                r[7] = (r[7] + 1) & 0xFFFF
            else:           # MVO@ / PSHR / MVOI: 9 cycles
                a = r[m]
                if rg == m and m >= 4:
                    self._undefined("MVO@ with the pointer as source (S1 p.55: not supported)")
                    if m < 7:   # the incremented pointer is written (the owner's Model 2609, hw_cpuodd)
                        v = (a + 1) & 0xFFFF
                self._write_seq(a, v)
                if m == 7:
                    self._words.append(v)
                if m >= 4:
                    r[m] = (a + 1) & 0xFFFF
            return False
        if m == 0:          # direct: 10 cycles
            if dbd:
                # the address comes as double byte data, from the next two words (low bytes,
                # as SDBD immediate): the owner's Model 2609 (hw_cpuodd, 2026-10-31) showed the
                # word after the instruction taken (its store never ran: 0000)
                self._undefined("SDBD with direct mode (S1 p.49: not supported)")
                a = self._read2_seq(r[7], (r[7] + 1) & 0xFFFF)
                self._words.extend(self._raw2)
                r[7] = (r[7] + 2) & 0xFFFF
                data = self._read_seq(a, "data")
            else:
                a, data = self._direct_read_seq(r[7])
                self._words.append(a)
                r[7] = (r[7] + 1) & 0xFFFF
        elif dbd:           # double byte data, S1 p.49 fig 3.2.6/3.2.7
            if m < 4:       # same location twice
                data = self._read2_seq(r[m], r[m])
            elif m == 6:
                self._undefined("SDBD with R6 (S1 p.49: not supported)")
                if self.sdbd_r6 == "mame":
                    self._idle(3)
                    a1 = (r[6] - 1) & 0xFFFF
                    a2 = (r[6] - 2) & 0xFFFF
                    data = self._read2_seq(a1, a2)
                    r[6] = a2
                else:
                    a1 = (r[6] - 1) & 0xFFFF
                    data = self._read2_seq(a1, a1)
                    r[6] = a1
            else:           # R4, R5, R7: two locations, pointer +2
                a = r[m]
                data = self._read2_seq(a, (a + 1) & 0xFFFF)
                if m == 7:
                    self._words.extend(self._raw2)
                r[m] = (a + 2) & 0xFFFF
        else:
            if m == 6:      # stack: pre-decrement, 3 more cycles (S1 p.55)
                self._idle(3)
                r[6] = (r[6] - 1) & 0xFFFF
                data = self._read_seq(r[6], "data")
            else:
                a = r[m]
                data = self._read_seq(a, "operand" if m == 7 else "data")
                if m == 7:
                    self._words.append(data)
                if m >= 4:
                    r[m] = (a + 1) & 0xFFFF
        if o == 2:
            r[rg] = data
        elif o == 3:
            r[rg] = self._add(r[rg], data)
        elif o == 4:
            r[rg] = self._sub(r[rg], data)
        elif o == 5:
            self._sub(r[rg], data)
        elif o == 6:
            r[rg] &= data
            self._sz(r[rg])
        else:
            r[rg] ^= data
            self._sz(r[rg])
        return True


# ----------------------------------------------------------------- trace
def trace_header():
    return ("     cycle PC   words           instruction             "
            "R0   R1   R2   R3   R4   R5   R6   R7   SZOC ID  cyc")


def trace_line(ev):
    ws = " ".join("%04X" % w if w is not None else "...." for w in ev.words[:3])
    if ev.kind == "intr":
        ws = "INT"
    elif ev.kind == "busak":
        ws = "BUS"
    elif ev.kind == "halt":
        ws = "HLT"
    f = ev.flags
    fl = "".join(c if f & b else "-" for c, b in (("S", 8), ("Z", 4), ("O", 2), ("C", 1)))
    idf = ("I" if ev.i else "-") + ("D" if ev.d else "-")
    text = ev.text + (" ?" if ev.undefined else "")
    return "%10d %04X %-15s %-23s %s %s %s %3d" % (
        ev.cycle, ev.pc, ws, text, " ".join("%04X" % x for x in ev.regs),
        fl, idf, ev.cycles)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run a program on the CP1610 model.")
    ap.add_argument("src", help=".asm source (assembled with as1610.py)")
    ap.add_argument("--steps", type=int, default=1000)
    ap.add_argument("--cycles", type=int)
    ap.add_argument("--start", help="start address or label (default 'start' or $1000)")
    ap.add_argument("--buslog", action="store_true")
    a = ap.parse_args(argv)
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import as1610
    with open(a.src, encoding="utf-8") as f:
        prog = as1610.assemble(f.read())
    bus = _DefaultBus()
    for addr, w in prog.words.items():
        bus.mem[addr] = w
    start = prog.symbols.get("start", 0x1000)
    if a.start:
        start = prog.symbols.get(a.start) if a.start in prog.symbols else int(a.start.lstrip("$"), 16)
    bus.iab = lambda cycle, reason, s=start: s if reason == "reset" else 0x1004
    cpu = CP1610(bus, buslog=a.buslog)
    print(trace_header())
    n = 0
    while n < a.steps and (a.cycles is None or cpu.cycle < a.cycles):
        ev = cpu.step()
        print(trace_line(ev))
        n += 1
        if ev.kind == "halt":
            break
    if a.buslog:
        for c, ph, ad, da in cpu.buslog:
            print("%10d %-5s %s %s" % (c, ph, "" if ad is None else "%04X" % ad,
                                       "" if da is None else "%04X" % da))
    return 0


if __name__ == "__main__":
    sys.exit(main())
