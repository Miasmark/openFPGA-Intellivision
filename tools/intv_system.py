#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""intv_system: the Intellivision as build step 3 has it, around cp1610.py.

The golden model for the RTL bus fabric (src/fpga/core/intv_bus.sv and the
modules around it; DESIGN.md 2.5, 2.6, 9 step 3). It runs our CP1610 model
on a system bus with the same devices and the same frame timing as the RTL:

  $0000-$003F  STIC registers (stub, no picture): read and write as MAME's
               stic_device::read/write do (MAME stic.cpp:1139-1309; bits
               read back fixed per register class, design 13.7). Write-only
               aliases at $4000, $8000, $C000 (DESIGN 2.6).
  $0100-$01EF  scratchpad RAM, 8-bit (upper byte reads 0, DESIGN 2.5)
  $01F0-$01FF  PSG register stub (AY-3-8914): 14 registers with MAME's
               read masks and register order (MAME ay8910.cpp:1445-1450,
               1533); $01FE / $01FF read the hand controllers (no input yet:
               $FF). Upper byte 0.
  $0200-$035F  System RAM, 16-bit
  $1000-$1FFF  EXEC ROM, 10 bits (upper 6 bits 0, as MAME's ROM region)
  $3000-$37FF  GROM, $FF00 | byte (MAME stic.cpp:1317-1322)
  $3800-$3FFF  GRAM, 512 x 8, mirrored every 512 words; write-only aliases
               at $7800, $B800, $F800 (DESIGN 2.6)
  cartridge    tools/mapper's CartModel (the loader's page table); it sees
               every write, as the RTL's cartridge port does
  anything else reads $FFFF (pull-ups, DESIGN 2.5). Devices that answer
  together give the AND of their words (the pulled-up bus).

Frame timing (DESIGN 2.4; MAME stic.h:47-50): a frame is FRAME = 14,934 CPU
cycles; it starts with VBlank, and INTRM is held for the first VBLANK =
3,790 cycles. The same window is the STIC's bus-copy window (MAME
intv_m.cpp:660-666, 643-647): STIC registers and GRAM are open to the CPU
inside it, or at any time while the STIC handshake is clear. A write to
STIC register $20 (display enable) sets the handshake; the start of every
frame clears it (MAME stic.cpp:1111-1116, 1270-1274). Closed accesses read
the address offset and drop writes (MAME intv_m.cpp:484-512). The RTL
releases the CPU from reset so that its reset IAB is the last cycle of a
frame: model cycle 0 (the first fetch) is cycle 0 of a frame.

IAB answers $1000 the first time after reset, then $1004 (MAME
intv_m.cpp:550-561; DESIGN 2.1: U9 supplies the vectors).

Usage
  python3 tools/intv_system.py run [--cart IMG] [--frames N]
        run the model, print a summary per frame
  python3 tools/intv_system.py mame TRACE [--cart IMG]
        compare the model with a MAME trace (tools/refs/mame_trace.sh):
        PC, registers and flags before every instruction, every bus access
        with its data, and where INTRM is taken. Nothing is replayed from
        the trace. The frame starts are taken from the trace (MAME's frame
        number changes at its VBlank interrupt), and the model's cycle count
        runs on MAME's clock (the SETC / SARC ,2 differences of
        docs/CPU_NOTES.md rows 3-4 are added back), so the device stubs are
        what is checked.
The BIOS and the game images are the user's: --bios-dir or INTV_BIOS_DIR
(exec.bin, grom.bin), and image paths. Nothing derived from them is written
by this tool.
"""

import argparse
import collections
import os
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "mapper"))
from cp1610 import CP1610  # noqa: E402

FRAME = 14934           # CPU cycles per frame (57 x 262)
VBLANK = 3790           # INTRM / bus-copy window at the start of a frame
VEC_RESET, VEC_INTR = 0x1000, 0x1004

# STIC register classes, as MAME's stic_device::read returns them:
# (fixed bits, kept bits). Kept bits are stored; the rest read as fixed.
STIC_DEF = [(0x3FFF, 0x0000)] * 0x40
for _i in range(8):
    STIC_DEF[0x00 + _i] = (0x3800, 0x07FF)     # MXR
    STIC_DEF[0x08 + _i] = (0x3000, 0x0FFF)     # MYR
    STIC_DEF[0x10 + _i] = (0x0000, 0x3FFF)     # MAR
    STIC_DEF[0x18 + _i] = (0x3C00, 0x03FF)     # MCR
for _i in (0x28, 0x29, 0x2A, 0x2B, 0x2C):       # CSR0-3, BCR
    STIC_DEF[_i] = (0x3FF0, 0x000F)
STIC_DEF[0x30] = STIC_DEF[0x31] = (0x3FF8, 0x0007)   # HDR, VDR
STIC_DEF[0x32] = (0x3FFC, 0x0003)              # CBR
STIC_REGS = 0x33
STIC_DER, STIC_GMR = 0x20, 0x21

# AY-3-8914: register at $01F0 + n is AY-3-8910 register MAP[n] (MAME
# ay8910.cpp:1533); read masks per AY-3-8910 register (ay8910.cpp:1445-1450).
PSG_MAP = (0, 2, 4, 11, 1, 3, 5, 12, 7, 6, 13, 8, 9, 10, 14, 15)
_MASK8910 = (0xFF, 0x0F, 0xFF, 0x0F, 0xFF, 0x0F, 0x1F, 0xFF,
             0x3F, 0x3F, 0x3F, 0xFF, 0xFF, 0x0F, 0xFF, 0xFF)
PSG_MASK = tuple(_MASK8910[PSG_MAP[n]] for n in range(14))


def load_words(path):
    data = open(path, "rb").read()
    return [data[i] << 8 | data[i + 1] for i in range(0, len(data) - 1, 2)]


class FrameTiming:
    """Frame k starts at cycle k x FRAME (the RTL's timing)."""

    def frame(self, c):
        return c // FRAME

    def vb(self, c):
        return c % FRAME < VBLANK

    line = vb                           # INTRM: the same window


class ListTiming:
    """Frame starts from a list (MAME mode): no VBlank before the first.

    A start is the cycle of the first instruction MAME runs in the new
    frame. MAME raises INTRM and the bus-copy window from a timer that fires
    between its CPU time slices, so the instruction that was running when
    VBlank began finishes first; the CPU then runs one more instruction
    before it checks the line (MAME cp1610.cpp execute_run checks after
    each instruction). So the bus copy window opens at the start and the
    line is first seen at the boundary after it."""

    def __init__(self, starts):
        self.starts = list(starts)

    def frame(self, c):
        lo, hi = 0, len(self.starts)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.starts[mid] <= c:
                lo = mid + 1
            else:
                hi = mid
        return lo                       # number of starts <= c

    def vb(self, c):
        k = self.frame(c)
        return k > 0 and c - self.starts[k - 1] < VBLANK

    def line(self, c):
        k = self.frame(c)
        return k > 0 and 0 < c - self.starts[k - 1] < VBLANK


class SystemBus:
    """The step-3 system around the CPU model (see the module docstring)."""

    def __init__(self, exec_words, grom_bytes, cart=None, timing=None):
        if len(exec_words) != 4096 or len(grom_bytes) != 2048:
            raise ValueError("EXEC must be 4096 words, GROM 2048 bytes")
        self.exec = [w & 0x3FF for w in exec_words]
        self.grom = list(grom_bytes)
        self.cart = cart
        self.timing = timing or FrameTiming()
        self.bias = 0                   # MAME mode: model cycle -> timing cycle
        self.scratch = [0] * 256
        self.sysram = [0] * 352
        self.gram = [0] * 512
        self.stic = [0] * STIC_REGS
        self.psg = [0] * 14
        self.pad = (0xFF, 0xFF)         # $01FE right, $01FF left: no input
        self.zero = ()                  # MAME mode: unmapped ranges MAME reads as 0
        self.reset()

    def reset(self):
        """Machine reset: STIC and PSG registers (MAME stic.cpp:478-488,
        ay8910.cpp ay8910_reset_ym), the vector select, the page selects.
        RAM keeps its contents."""
        self.stic = [0] * STIC_REGS
        self.hs_frame = None            # frame in which the handshake was set
        self.csmode = 0
        self.psg = [0] * 14
        self.iab_reset = True
        if self.cart is not None:
            self.cart.reset()

    # -- timing ----------------------------------------------------------
    def _t(self, cycle):
        return cycle + self.bias

    def vb(self, cycle):
        return self.timing.vb(self._t(cycle))

    def handshake(self, cycle):
        return self.hs_frame is not None and \
            self.hs_frame == self.timing.frame(self._t(cycle))

    def stic_open(self, cycle):
        return self.vb(cycle) or not self.handshake(cycle)

    # -- CPU hooks -------------------------------------------------------
    def intrm(self, cycle):
        return self.timing.line(self._t(cycle))

    def intr(self, cycle):
        return False

    def busrq(self, cycle):
        return False

    def bext(self, cond, cycle):
        return False

    def iab(self, cycle, reason):
        v = VEC_RESET if self.iab_reset else VEC_INTR
        self.iab_reset = False
        return v

    def read(self, addr, cycle, kind="data"):
        v = 0xFFFF
        a = addr & 0xFFFF
        if a < 0x40:
            v &= self._stic_read(a, cycle)
        elif a & 0x3FFF == STIC_GMR and self.stic_open(cycle):
            self.csmode = 1             # $x021 read reaches the mode latch (DESIGN 2.6)
        if 0x100 <= a <= 0x1EF:
            v &= self.scratch[a & 0xFF]
        elif 0x1F0 <= a <= 0x1FF:
            n = a & 0xF
            v &= self.pad[n - 14] if n >= 14 else self.psg[n]
        elif 0x200 <= a <= 0x35F:
            v &= self.sysram[a - 0x200]
        elif 0x1000 <= a <= 0x1FFF:
            v &= self.exec[a - 0x1000]
        elif 0x3000 <= a <= 0x37FF:
            v &= 0xFF00 | self.grom[a - 0x3000]
        elif 0x3800 <= a <= 0x3FFF:
            v &= self.gram[a & 0x1FF] if self.stic_open(cycle) else a & 0x1FF
        if self.cart is not None:
            c = self.cart.read(a)
            if c is not None:
                v &= c
        for lo, hi in self.zero:
            if lo <= a <= hi:
                v = 0
        return v

    def _stic_read(self, a, cycle):
        if not self.stic_open(cycle):
            return a                    # MAME intv_m.cpp:484-490
        if a == STIC_GMR:
            self.csmode = 1
        if a >= STIC_REGS:
            return 0x3FFF
        fixed, keep = STIC_DEF[a]
        return fixed | (self.stic[a] & keep)

    def write(self, addr, value, cycle):
        a = addr & 0xFFFF
        value &= 0xFFFF
        if a & 0x3FFF < 0x40:          # $0000, aliases $4000 $8000 $C000
            self._stic_write(a & 0x3F, value, cycle)
        if 0x100 <= a <= 0x1EF:
            self.scratch[a & 0xFF] = value & 0xFF
        elif 0x1F0 <= a <= 0x1FD:
            n = a & 0xF
            self.psg[n] = value & PSG_MASK[n]
        elif 0x200 <= a <= 0x35F:
            self.sysram[a - 0x200] = value
        if a & 0x3800 == 0x3800:       # $3800, $7800, $B800, $F800 (+ $7FF)
            if self.stic_open(cycle):
                self.gram[a & 0x1FF] = value & 0xFF
        if self.cart is not None:
            self.cart.write(a, value)

    def _stic_write(self, n, value, cycle):
        if not self.stic_open(cycle):
            return
        if n == STIC_DER:
            self.hs_frame = self.timing.frame(self._t(cycle))
        elif n == STIC_GMR:
            self.csmode = 0
        if n < STIC_REGS:
            if 0x18 <= n < 0x20:
                value &= ~(1 << (n & 7))   # MAME stic.cpp:1258-1266
            self.stic[n] = value & STIC_DEF[n][1]

    def state(self, cycle):
        return {"scratch": list(self.scratch), "sysram": list(self.sysram),
                "gram": list(self.gram), "stic": list(self.stic),
                "psg": list(self.psg), "handshake": int(self.handshake(cycle)),
                "csmode": self.csmode,
                "sel": list(self.cart.sel) if self.cart is not None else [0] * 16}


# ----------------------------------------------------------------- loading
def bios_paths(bios_dir):
    d = bios_dir or os.environ.get("INTV_BIOS_DIR")
    if not d:
        raise SystemExit("give --bios-dir or INTV_BIOS_DIR (exec.bin, grom.bin)")
    return os.path.join(d, "exec.bin"), os.path.join(d, "grom.bin")


def load_cart(path):
    """(CartModel, crc, words) as the loader maps the image, or None."""
    if not path:
        return None
    import intv_mapper
    import intvcart as m
    data = m.load_image_bytes(path)
    words = m.bytes_to_words(data)
    crc = zlib.crc32(data) & 0xFFFFFFFF
    cart, lid, flags, hit = intv_mapper.Tables().model(words, crc)
    return cart, crc, lid, flags, hit


def make_system(bios_dir=None, cart_path=None, timing=None, buslog=True):
    ex, gr = bios_paths(bios_dir)
    cart = load_cart(cart_path)
    bus = SystemBus(load_words(ex), open(gr, "rb").read(),
                    cart[0] if cart else None, timing)
    cpu = CP1610(bus=bus, buslog=buslog)
    return bus, cpu


# -------------------------------------------------------------- MAME check
KNOWN_CYCLE_DIFF = {"SETC": 2, "SARC2": -2}     # MAME minus model


def _cycle_key(text):
    t = text.split()
    if not t:
        return None
    if t[0] == "SETC":
        return "SETC"
    if t[0] == "SARC" and text.replace(" ", "").endswith(",2"):
        return "SARC2"
    return None


# MAME maps nothing at the Intellivoice's $0080-$0081 on plain intv and
# reads 0 there; the pulled-up bus reads $FFFF (DESIGN 2.5; refs NOTES: B-17's
# probe). --mame-voice-zero lets the comparison go past that probe.
MAME_VOICE_ZERO = ((0x0080, 0x0081),)


def mame_compare(trace_path, bios_dir=None, cart_path=None, context=6,
                 out=sys.stdout, voice_zero=False):
    sys.path.insert(0, HERE)
    import lockstep
    recs = lockstep.read_trace(trace_path)
    starts = []
    for i in range(1, len(recs)):
        if recs[i].frame != recs[i - 1].frame:
            starts.append(recs[i].cycle)
    bus, cpu = make_system(bios_dir, cart_path, ListTiming(starts), buslog=False)
    if voice_zero:
        bus.zero = MAME_VOICE_ZERO
    log = []

    class Rec:                          # what the model did in one trace step
        pass

    hist = collections.deque(maxlen=context)
    acc = []
    orig_read, orig_write = bus.read, bus.write

    def rd(addr, cycle, kind="data"):
        v = orig_read(addr, cycle, kind)
        acc.append(("R", addr, v))
        return v

    def wr(addr, value, cycle):
        acc.append(("W", addr, value & 0xFFFF))
        orig_write(addr, value, cycle)

    bus.read, bus.write = rd, wr
    stats = collections.Counter()
    k = 0
    n = len(recs)
    while k < n:
        rec = recs[k]
        if (list(cpu.r), cpu.flags) != (rec.regs, rec.flags):
            return _mame_fail(out, hist, rec, "state: model R=%s SZOC=%s, MAME R=%s SZOC=%s" % (
                " ".join("%04X" % r for r in cpu.r), format(cpu.flags, "04b"),
                " ".join("%04X" % r for r in rec.regs), format(rec.flags, "04b")), stats)
        if bus._t(cpu.cycle) != rec.cycle:
            return _mame_fail(out, hist, rec, "cycle: model (MAME clock) %d, MAME %d"
                              % (bus._t(cpu.cycle), rec.cycle), stats)
        acc.clear()
        ev = cpu.step()
        if ev.kind == "intr":
            return _mame_fail(out, hist, rec, "model takes INTRM before $%04X, MAME does not"
                              % rec.pc, stats)
        if ev.text.startswith("SDBD"):          # MAME shows SDBD + next as one step
            ev2 = cpu.step()
            ev.text += " / " + ev2.text
        want = list(rec.acc)
        if acc != want:
            return _mame_fail(out, hist, rec, "accesses: model %s, MAME %s" % (
                _fmt_acc(acc), _fmt_acc(want)), stats)
        key = _cycle_key(rec.text)
        if key:
            bus.bias += KNOWN_CYCLE_DIFF[key]
            stats["bias " + key] += 1
        stats["steps"] += 1
        hist.append("%6d c=%d %04X %s" % (k, rec.cycle, rec.pc, rec.text))
        if rec.intr is not None:
            acc.clear()
            if not cpu.interruptible:
                return _mame_fail(out, hist, rec, "MAME takes INTRM after $%04X, model not interruptible"
                                  % rec.pc, stats)
            ev = cpu.step()
            if ev.kind != "intr":
                return _mame_fail(out, hist, rec, "MAME takes INTRM after $%04X, model does not"
                                  % rec.pc, stats)
            if acc != list(rec.intr_acc):
                return _mame_fail(out, hist, rec, "interrupt accesses: model %s, MAME %s" % (
                    _fmt_acc(acc), _fmt_acc(rec.intr_acc)), stats)
            stats["interrupts"] += 1
        k += 1
    out.write("MAME_COMPARE pass: %d steps, %d interrupts, %d frames; MAME clock "
              "bias SETC %d, SARC ,2 %d; every read and write equal\n" % (
                  stats["steps"], stats["interrupts"], len(starts) + 1,
                  stats["bias SETC"], stats["bias SARC2"]))
    return True


def _fmt_acc(a):
    return " ".join("%s %04X %04X" % x for x in a) or "(none)"


def _mame_fail(out, hist, rec, msg, stats):
    out.write("MAME_COMPARE FAIL at trace line %d (step %d, c=%d, PC $%04X %s): %s\n"
              % (rec.lineno, rec.idx, rec.cycle, rec.pc, rec.text, msg))
    for h in hist:
        out.write("  before: %s\n" % h)
    return False


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--cart")
    r.add_argument("--frames", type=int, default=10)
    r.add_argument("--bios-dir")
    mm = sub.add_parser("mame")
    mm.add_argument("trace")
    mm.add_argument("--cart")
    mm.add_argument("--bios-dir")
    mm.add_argument("--mame-voice-zero", action="store_true",
                    help="read $0080-$0081 as 0, as MAME's plain intv does")
    a = ap.parse_args()
    if a.cmd == "run":
        bus, cpu = make_system(a.bios_dir, a.cart, buslog=False)
        n = 0
        intr = 0
        f = 0
        while cpu.cycle < a.frames * FRAME:
            ev = cpu.step()
            n += ev.kind == "insn"
            intr += ev.kind == "intr"
            if cpu.cycle >= (f + 1) * FRAME:
                f += 1
                print("frame %d: %d instructions, %d interrupts, PC $%04X" % (f, n, intr, cpu.r[7]))
        return 0
    return 0 if mame_compare(a.trace, a.bios_dir, a.cart, voice_zero=a.mame_voice_zero) else 1


if __name__ == "__main__":
    sys.exit(main())
