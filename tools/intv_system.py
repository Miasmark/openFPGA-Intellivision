#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""intv_system: the Intellivision as build steps 3-4 have it, around cp1610.py.

The golden model for the RTL bus fabric (src/fpga/core/intv_bus.sv and the
modules around it; DESIGN.md 2.5, 2.6, 9 steps 3-4). It runs our CP1610
model on a system bus with the same devices and the same frame timing as
the RTL:

  $0000-$003F  STIC (tools/stic.py, build step 4): registers read and
               written as MAME's stic_device::read/write do (MAME
               stic.cpp:1139-1309; bits read back fixed per register
               class, design 13.7), the handshake and the mode latch as the
               step-3 stub had them; the background picture, the row
               fetches from System RAM and BUSRQ. Write-only aliases at
               $4000, $8000, $C000 (DESIGN 2.6).
  $0100-$01EF  scratchpad RAM, 8-bit (upper byte reads 0, DESIGN 2.5)
  $01F0-$01FF  PSG (AY-3-8914, tools/psg.py, build step 6): 14 registers
               with MAME's read masks and register order (MAME
               ay8910.cpp:1445-1450, 1533), tone, noise and envelope
               generators clocked from the CPU cycle count (a tick at the
               end of cycles 0, 4, 8, ...); $01FE / $01FF read the hand
               controllers (self.pad, $FF = nothing pressed). Upper byte 0.
  $0200-$035F  System RAM, 16-bit
  $1000-$1FFF  EXEC ROM, 10 bits (upper 6 bits 0, as MAME's ROM region)
  $3000-$37FF  GROM, $FF00 | byte (MAME stic.cpp:1317-1322)
  $3800-$3FFF  GRAM, 512 x 8, mirrored every 512 words; write-only aliases
               at $7800, $B800, $F800 (DESIGN 2.6)
  cartridge    tools/mapper's CartModel (the loader's page table); it sees
               every write, as the RTL's cartridge port does
  ECS          tools/ecs.py (build step 9), when attached: UART stub
               $00E0-$00E3, PSG #2 $00F0-$00FF, ECS RAM $4000-$47FF, ECS
               ROMs at $2000 / $7000 / $E000 on their pages. Where the ECS
               answers, the cartridge does not (its page selects and bank
               registers still see the write).
  Intellivoice tools/sp0256.py VoiceBus (build step 10), when on: $0080-$0081
               on the CPU's cycle count (the sample enable, the busy window);
               off (or None) leaves them unmapped.
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

The STIC model has three modes (tools/stic.py): "none" (the default, the
step-3 system: no BUSRQ, so tools that drive the bus as step 3 did see no
change), "stic" (the hardware: BUSRQ per card row, the CPU held at its
next interruptible boundary) and "mame" (MAME as it runs: no stolen
cycles, MAME's row-fetch timers, MAME's 59.92 Hz frame and clock; see
MameTiming and mame_quirks). A run loop calls SystemBus.boundary after
every CPU step.

Usage
  python3 tools/intv_system.py run [--cart IMG] [--frames N] [--stic-mode M]
        run the model, print a summary per picture (display on/off,
        vertical delay, BUSRQ requests and stolen cycles, rows loaded)
  python3 tools/intv_system.py mame TRACE [--cart IMG]
        [--timing trace|computed] [--stic-mode mame]
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

import stic as sticm  # noqa: E402
import psg as psgm  # noqa: E402
import intv_input as inm  # noqa: E402
import ecs as ecsm  # noqa: E402
from stic import FRAME, VBLANK, STIC_DEF, STIC_REGS, STIC_DER, STIC_GMR  # noqa: E402,F401

VEC_RESET, VEC_INTR = 0x1000, 0x1004

# MAME's frame: 59.92 Hz screen, 894,886 Hz CPU (MAME intv.cpp:445, 456),
# both in attoseconds as MAME's HZ_TO_ATTOSECONDS gives them.
MAME_FRAME_AS = int(1e18 / 59.92)
MAME_CYCLE_AS = 10 ** 18 // 894886

# AY-3-8914: register at $01F0 + n is AY-3-8910 register MAP[n] (MAME
# ay8910.cpp:1533); read masks per AY-3-8910 register (ay8910.cpp:1445-1450).
PSG_MAP = psgm.MAP8910
PSG_MASK = psgm.MASK


def _bank0():
    import cartfmt
    return list(cartfmt.BANK0)


# intv_psg's state words 14-20 in reset (PSG #2 while the ECS is off): counts 0, LFSR 1,
# envelope step 15, tick phase 3
PSG_RESET_WORDS = (0, 0, 0, 0, 1, 0, 0xCF)


def load_words(path):
    data = open(path, "rb").read()
    return [data[i] << 8 | data[i + 1] for i in range(0, len(data) - 1, 2)]


# Scripted keys (the step-6 play benches; tools/refs/mame_psg.sh presses
# the same keys in MAME). The lines each key pulls low: DESIGN 7.1, MAME
# handctrl.cpp:124-135 inverted (KEYPAD port, names as MAME's PORT_NAME);
# the disc directions of MAME's digital disc (DISC_DG, handctrl.cpp:37-53,
# bit 15 "Up" down to bit 0 "Up-Up-Left") pull ~disc_table[bit]
# (handctrl.cpp:130-135, 160-166).
KEYCODE = {"1": 0x81, "2": 0x41, "3": 0x21, "4": 0x82, "5": 0x42, "6": 0x22,
           "7": 0x84, "8": 0x44, "9": 0x24, "Clear": 0x88, "0": 0x48, "Enter": 0x28,
           "Upper": 0xA0, "Lower-Left": 0x60, "Lower-Right": 0xC0}
DISC_NAMES = ["Up", "Up-Up-Right", "Up-Right", "Right-Up-Right", "Right", "Right-Down-Right",
              "Down-Right", "Down-Down-Right", "Down", "Down-Down-Left", "Down-Left",
              "Left-Down-Left", "Left", "Left-Up-Left", "Up-Left", "Up-Up-Left"]
_MAME_DISC_TABLE = [0xf3, 0xe3, 0xe7, 0xf7, 0xf6, 0xe6, 0xee, 0xfe,
                    0xfc, 0xec, 0xed, 0xfd, 0xf9, 0xe9, 0xeb, 0xfb]
for _i, _n in enumerate(DISC_NAMES):
    KEYCODE[_n] = ~_MAME_DISC_TABLE[15 - _i] & 0xFF


# Pocket buttons for "pocket:" presses (tools/intv_input.py's bit numbers)
POCKET_BTN = {"up": inm.UP, "down": inm.DOWN, "left": inm.LEFT, "right": inm.RIGHT, "A": inm.A, "B": inm.B,
              "X": inm.X, "Y": inm.Y, "L": inm.L1, "R": inm.R1}


def parse_presses(text):
    """"F1-F2:KEY,..." (KEY held from MAME's frame notifier F1 until F2)
    -> [(F1, F2, lines pulled low)]. KEY is a hand-controller input (KEYCODE)
    or "pocket:B1+B2..." (Pocket buttons, POCKET_BTN), which gives
    (F1, F2, ("pocket", button bits)): press_pads combines the Pocket buttons
    held in a frame and maps them through the input model (tools/intv_input.py,
    Layer mode, player 1 on the Pocket), as intv_input.sv does on the core.
    "ecs:K1+K2..." holds ECS keyboard keys (tools/ecs.py KEYPOS names) and
    "synth:N1+N2..." synthesizer keys (0 = C2 ... 48 = C6; bit 8 row +
    column of the matrix, MAME ecs_ctrl.cpp SYNTH.n): (F1, F2, ("ecs",
    matrix bits)), read by press_keys."""
    out = []
    for p in filter(None, (text or "").split(",")):
        fr, key = p.split(":", 1)
        f1, f2 = (int(x) for x in fr.split("-"))
        if key.startswith("ecs:") or key.startswith("synth:"):
            bits = 0
            for k in key.split(":", 1)[1].split("+"):
                if key.startswith("synth:"):
                    n = int(k)
                    bits |= 1 << (63 if n == 48 else n)     # C6: row 6, column 7 (MAME SYNTH.6 bit 7)
                else:
                    if k not in ecsm.KEYPOS:
                        raise SystemExit("unknown ECS key %r" % k)
                    bits |= ecsm.keybits(k)
            out.append((f1, f2, ("ecs", bits)))
            continue
        if key.startswith("pocket:"):
            bits = 0
            for b in key[7:].split("+"):
                if b not in POCKET_BTN:
                    raise SystemExit("unknown Pocket button %r" % b)
                bits |= 1 << POCKET_BTN[b]
            out.append((f1, f2, ("pocket", bits)))
            continue
        if key not in KEYCODE:
            raise SystemExit("unknown key %r" % key)
        out.append((f1, f2, KEYCODE[key]))
    return out


def pocket_lines(bits):
    """The lines the Pocket's buttons `bits` pull low on player 1's hand
    controller (the input model, Layer mode, slot type 1)."""
    v = dict(key1=(1 << 28) | bits, joy1=0x80808080, key2=0, joy2=0x80808080, key3=0, joy3=0, trig3=0,
             mode=inm.LAYER, swap=0)
    return ~inm.ports(v)[1] & 0xFF


def press_pads(presses, k):
    """Both hand controllers' byte after frame notifier k: MAME's notifier
    k runs before the CPU sees frame k + 1, so frame k + 1 (timing.frame,
    the picture numbering) reads press_pads(presses, k). Pocket presses
    held at k are combined as buttons first (L + right is one turned
    direction, not two discs)."""
    v = 0xFF
    pocket = 0
    for f1, f2, code in presses:
        if f1 <= k < f2:
            if isinstance(code, tuple):
                if code[0] == "pocket":
                    pocket |= code[1]
            else:
                v &= ~code & 0xFF
    if pocket:
        v &= ~pocket_lines(pocket) & 0xFF
    return v


def press_keys(presses, k):
    """The ECS keyboard's pressed switches after frame notifier k (as
    press_pads)."""
    v = 0
    for f1, f2, code in presses or ():
        if f1 <= k < f2 and isinstance(code, tuple) and code[0] == "ecs":
            v |= code[1]
    return v


class FrameTiming:
    """Frame k starts at cycle k x FRAME (the RTL's timing)."""

    first = 0                           # frame 0 starts at cycle 0

    def frame(self, c):
        return c // FRAME

    def vb(self, c):
        return c % FRAME < VBLANK

    line = vb                           # INTRM: the same window

    def start(self, k):
        return k * FRAME

    def boundary(self, c):
        pass


class ListTiming:
    """Frame starts from a list (MAME mode): no VBlank before the first.

    A start is the cycle of the first instruction MAME runs in the new
    frame. MAME raises INTRM and the bus-copy window from a timer that fires
    between its CPU time slices, so the instruction that was running when
    VBlank began finishes first; the CPU then runs one more instruction
    before it checks the line (MAME cp1610.cpp execute_run checks after
    each instruction). So the bus copy window opens at the start and the
    line is first seen at the boundary after it."""

    first = 1

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

    def start(self, k):
        return self.starts[k - 1] if 0 < k <= len(self.starts) else None

    def vstart(self, k):
        """MAME's k-th vblank in CPU cycles, rounded down: a MAME timer at
        time T fires at the first instruction boundary at or after
        floor(T) (the CPU's time slice is a whole number of cycles and runs
        until its cycle count is used up)."""
        return (k * MAME_FRAME_AS) // MAME_CYCLE_AS

    def boundary(self, c):
        pass


class MameTiming(ListTiming):
    """MAME's frame timing without a trace (MAME intv.cpp:445-456,
    intv_m.cpp:643-684): frame k starts at the first instruction boundary
    at or after vstart(k); the bus-copy window holds for instructions that
    start before vstart(k) + VBLANK (MAME's interrupt_complete timer); the
    CPU sees INTRM from the boundary after the start until then. The run
    loop reports every boundary (SystemBus.boundary). Checked against the
    frame numbers of MAME's traces (mame_compare --timing computed)."""

    def __init__(self):
        ListTiming.__init__(self, [])
        self.s = 0                      # start of the instruction now running

    def boundary(self, c):
        self.s = c
        if c >= self.vstart(len(self.starts) + 1):
            self.starts.append(c)

    def vb(self, c):
        k = self.frame(self.s)
        return k > 0 and self.s < self.vstart(k) + VBLANK

    def line(self, c):
        k = self.frame(c)
        return k > 0 and self.starts[k - 1] < c < self.vstart(k) + VBLANK


class SystemBus:
    """The step-3 system around the CPU model (see the module docstring)."""

    def __init__(self, exec_words, grom_bytes, cart=None, timing=None, stic_mode="none", ecs=None,
                 voice=None, jlp=None):
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
        self.vid = sticm.Stic(self, stic_mode)   # the STIC (tools/stic.py)
        self.snd = psgm.ClockedPsg()    # the PSG (tools/psg.py)
        self.pad = (0xFF, 0xFF)         # $01FE right, $01FF left: no input
        self.presses = None             # scripted keys (press_pads): override self.pad
        self.zero = ()                  # MAME mode: unmapped ranges MAME reads as 0
        self.mame_map = False           # MAME's memory map (MAME_MAP_ZERO, no aliases)
        self.ecs = ecs                  # tools/ecs.py Ecs, or None (no ECS at all)
        self.voice = voice              # tools/sp0256.py VoiceBus (on or off), or None (step 10)
        self.jlp = jlp                  # tools/jlp.py Jlp, or None (step 11)
        self.replay = None              # MAME check: {addr: value} reads taken from the trace
        self.bank0 = _bank0()           # no cartridge: intv_cart's bank registers (kept over resets)
        self.reset()

    def reset(self):
        """Machine reset: STIC and PSG registers (MAME stic.cpp:478-488,
        ay8910.cpp ay8910_reset_ym), the vector select, the page selects.
        RAM keeps its contents."""
        self.vid.reset()
        self.snd.reset()
        self.iab_reset = True
        if self.cart is not None:
            self.cart.reset()
        self.sel0 = [0] * 16            # no cartridge: intv_cart's page selects still take writes
        if self.ecs is not None:
            self.ecs.reset()
        if self.voice is not None:
            self.voice.reset()
        if self.jlp is not None:
            self.jlp.reset()

    # -- the PSG's registers ----------------------------------------------
    @property
    def psg(self):
        return self.snd.regs

    # -- the STIC's registers, as the step-3 stub had them ------------------
    @property
    def stic(self):
        return self.vid.regs

    @property
    def csmode(self):
        return self.vid.csmode

    # -- timing ----------------------------------------------------------
    def _t(self, cycle):
        return cycle + self.bias

    tcycle = _t

    def vb(self, cycle):
        return self.timing.vb(self._t(cycle))

    def handshake(self, cycle):
        return self.vid.handshake(self.timing.frame(self._t(cycle)))

    def boundary(self, cycle):
        """The run loop calls this after every CPU step (cycle = cpu.cycle):
        MAME's frame starts and the STIC's boundary-timed events."""
        t = self._t(cycle)
        self.timing.boundary(t)
        self.vid.advance(t, boundary=True)

    def stic_open(self, cycle):
        return self.vb(cycle) or not self.handshake(cycle)

    # -- CPU hooks -------------------------------------------------------
    def intrm(self, cycle):
        return self.timing.line(self._t(cycle))

    def intr(self, cycle):
        return False

    def busrq(self, cycle):
        return self.vid.busrq(cycle)

    def intak(self, sp, cycle):
        self.vid.intak(self._t(cycle))

    def bext(self, cond, cycle):
        return False

    def iab(self, cycle, reason):
        v = VEC_RESET if self.iab_reset else VEC_INTR
        self.iab_reset = False
        return v

    def read(self, addr, cycle, kind="data"):
        v = 0xFFFF
        a = addr & 0xFFFF
        self.vid.advance(self._t(cycle))
        if a < 0x40:
            v &= self._stic_read(a, cycle)
        elif a & 0x3FFF == STIC_GMR and not self.mame_map:
            # $x021 read reaches the mode latch (DESIGN 2.6)
            self.vid.alias_mode_read(self.stic_open(cycle))
        if 0x100 <= a <= 0x1EF:
            v &= self.scratch[a & 0xFF]
        elif 0x1F0 <= a <= 0x1FF:
            n = a & 0xF
            pads = self.pad
            if self.presses is not None:
                p = press_pads(self.presses, self.timing.frame(self._t(cycle)) - 1)
                pads = (p, p)
            v &= self.snd.read(n, pads)
        elif 0x200 <= a <= 0x35F:
            v &= self.sysram[a - 0x200]
        elif 0x1000 <= a <= 0x1FFF:
            v &= self.exec[a - 0x1000]
        elif 0x3000 <= a <= 0x37FF:
            v &= 0xFF00 | self.grom[a - 0x3000]
        elif 0x3800 <= a <= (0x3BFF if self.mame_map else 0x3FFF):
            v &= self.gram[a & 0x1FF] if self.stic_open(cycle) else a & 0x1FF
        if self.voice is not None and self.voice.on and 0x80 <= a <= 0x81:
            v &= self.voice.access(self._t(cycle), ('R', a))
        if self.ecs is not None and self.ecs.owns(a):
            if self.ecs.keys_at is None and self.presses is not None:
                self.ecs.keys_at = lambda f: press_keys(self.presses, f - 1)
            return v & self.ecs.read(a, self._t(cycle), self.timing.frame(self._t(cycle)))
        if self.jlp is not None:
            if self.jlp.blocks(self._t(cycle)):
                return v                        # a flash command runs: the cartridge port is silent
            if self.jlp.owns(a):
                return v & self.jlp.read(a, self._t(cycle))
        if self.cart is not None:
            c = self.cart.read(a)
            if c is not None:
                v &= c
        if self.replay is not None and a in self.replay:
            return self.replay[a]
        for lo, hi in self.zero + (MAME_MAP_ZERO if self.mame_map else ()):
            if lo <= a <= hi:
                v = 0
        return v

    def _stic_read(self, a, cycle):
        return self.vid.read(a, self.timing.frame(self._t(cycle)), self.stic_open(cycle))

    def write(self, addr, value, cycle):
        a = addr & 0xFFFF
        value &= 0xFFFF
        self.vid.advance(self._t(cycle))
        if a & 0x3FFF < 0x40 and (a < 0x40 or not self.mame_map):
            self._stic_write(a & 0x3F, value, cycle)   # $0000, aliases $4000 $8000 $C000
        if 0x100 <= a <= 0x1EF:
            self.scratch[a & 0xFF] = value & 0xFF
        elif 0x1F0 <= a <= 0x1FD:
            self.snd.bus_write(a & 0xF, value, self._t(cycle))   # MAME mode: on MAME's clock
        elif 0x200 <= a <= 0x35F:
            self.sysram[a - 0x200] = value
        if a & 0x3800 == 0x3800 and (0x3800 <= a <= 0x3BFF or not self.mame_map):
            if self.stic_open(cycle):  # $3800, $7800, $B800, $F800 (+ $7FF)
                self.gram[a & 0x1FF] = value & 0xFF
        if self.voice is not None and self.voice.on and 0x80 <= a <= 0x81:
            self.voice.access(self._t(cycle), ('W', a, value))
        own = self.ecs is not None and self.ecs.owns(a)
        if self.ecs is not None:
            self.ecs.write(a, value, self._t(cycle))
        if self.jlp is not None:
            own |= self.jlp.blocks(self._t(cycle)) or self.jlp.stores(a)
            self.jlp.write(a, value, self._t(cycle))
        if self.cart is not None:
            if own:
                self.cart.write(a, value, store=False)
            else:
                self.cart.write(a, value)
        else:
            if a & 0xFFF == 0xFFF and (value & 0xFFF0) == ((a & 0xF000) | 0x0A50):
                self.sel0[a >> 12] = value & 0xF
            if 0x40 <= a <= 0x5F:
                self.bank0[a & 0x1F] = value & 0xFF

    def _stic_write(self, n, value, cycle):
        t = self._t(cycle)
        self.vid.write(n, value, self.timing.frame(t), self.stic_open(cycle), t)

    def state(self, cycle):
        """The machine's state at the start of cycle `cycle` (the bench's
        dumps); psgx: the PSG's state words 14-20 (intv_psg.sv)."""
        self.snd.advance(self._t(cycle) - 1)
        return {"psgx": self.snd.state(self._t(cycle) % 4)[14:],
                "scratch": list(self.scratch), "sysram": list(self.sysram),
                "gram": list(self.gram), "stic": list(self.stic),
                "psg": list(self.psg), "handshake": int(self.handshake(cycle)),
                "csmode": self.csmode,
                "sel": list(self.cart.sel) if self.cart is not None else list(self.sel0),
                # no cartridge: the loader still finishes and sets the bank registers to their
                # start (identity, intv_cart.sv; step 8's review); the model's cart is None then
                "bank": list(getattr(self.cart, "bank", [0] * 32)) if self.cart is not None else list(self.bank0),
                "fifo": list(self.vid.fifo), "counter": self.vid.counter,
                "ecs": self.ecs.state() if self.ecs is not None else [0],
                "psg2": list(self.ecs.psg.regs) if self.ecs is not None else [0] * 14,
                "psg2x": self._psg2x(cycle),
                "ecsram": self.ecs.ram_words() if self.ecs is not None else [0] * 512,
                "voice": self._voice_words(cycle)}

    def _voice_words(self, cycle):
        """intv_voice.sv's words 20-22 at the start of cycle `cycle` (step 10)."""
        if self.voice is None or not self.voice.on:
            return [0, 1, 0]                    # reset: snap_lrq 1, mode off
        self.voice.run_to(self._t(cycle))
        return self.voice.state_words()

    def _psg2x(self, cycle):
        if self.ecs is None or not self.ecs.on:
            return list(PSG_RESET_WORDS)        # intv_ecs holds PSG #2 in reset
        self.ecs.psg.advance(self._t(cycle) - 1)
        return self.ecs.psg.state(self._t(cycle) % 4)[14:]


# ----------------------------------------------------------------- loading
def bios_paths(bios_dir):
    d = bios_dir or os.environ.get("INTV_BIOS_DIR")
    if not d:
        raise SystemExit("give --bios-dir or INTV_BIOS_DIR (exec.bin, grom.bin)")
    return os.path.join(d, "exec.bin"), os.path.join(d, "grom.bin")


def load_cart(path, cfg_path=None):
    """(cartridge model, crc, layout, flags, hit) as the loader maps the image (and its CFG,
    build step 8: tools/mapper/cartfmt.py, any format), or None."""
    if not path:
        return None
    import intv_mapper
    import intvcart as m
    import cartfmt
    data = m.load_image_bytes(path)
    cfg = open(cfg_path, "rb").read() if cfg_path else None
    tab = intv_mapper.Tables()
    ld = cartfmt.load(data, cfg, tab, tab.pages)
    return cartfmt.MapCart(ld), ld.crc, ld.layout, ld.flags, ld.hit


def make_jlp(cart, flash=None):
    """The JLP a cartridge asks for (build step 11: its CFG's or .rom tag's mode and flash
    sectors, tools/mapper/cartfmt.py jlp_config), or None. flash: the nonvolatile store's
    words, else erased."""
    ld = getattr(cart, "ld", None)
    if ld is None or not ld.jlp_mode:
        return None
    import jlp as jlpm
    return jlpm.Jlp(ld.jlp_mode, ld.jlp_sectors, flash)


ECS_OVERRIDES = {"auto": ecsm.OVERRIDE_AUTO, "on": ecsm.OVERRIDE_ON, "off": ecsm.OVERRIDE_OFF}


def make_ecs(cart, ecs, bios_dir=None, mame=False):
    """The ECS for a system (build step 9): ecs None (no ECS device: the
    systems of steps 3-8) or (override, ECS ROM path or None) with override
    "auto" / "on" / "off" (the menu's ECS item; Auto = DESIGN 20's rule from
    the cartridge, tools/ecs.py auto_mode). The ROM path defaults to
    ECS.bin (or ecs.bin) in the BIOS directory; a missing file means no ECS
    ROM slot."""
    if ecs is None:
        return None
    override, rom_path = ecs
    if rom_path is None:
        d = bios_dir or os.environ.get("INTV_BIOS_DIR") or ""
        for n in ("ECS.bin", "ecs.bin"):
            if os.path.exists(os.path.join(d, n)):
                rom_path = os.path.join(d, n)
                break
    rom = ecsm.load_rom(rom_path) if rom_path and os.path.exists(rom_path) else None
    auto = ecsm.auto_mode(*ecsm.cart_inputs(cart))
    return ecsm.Ecs(rom, ecsm.mode_for(ECS_OVERRIDES[override], auto), mame=mame)


def make_system(bios_dir=None, cart_path=None, timing=None, buslog=True, stic_mode="none", cfg_path=None,
                ecs=None, mame_ecs=False, jlp_flash=None):
    ex, gr = bios_paths(bios_dir)
    cart = load_cart(cart_path, cfg_path)
    dev = make_ecs(cart[0] if cart else None, ecs, bios_dir, mame_ecs)
    bus = SystemBus(load_words(ex), open(gr, "rb").read(),
                    cart[0] if cart else None, timing, stic_mode, ecs=dev,
                    jlp=make_jlp(cart[0] if cart else None, jlp_flash))
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

# MAME's intv memory map (MAME intv.cpp:278-303) leaves these ranges
# unmapped: they read 0 there and writes go nowhere. MAME maps GRAM at
# $3800-$3BFF only and the STIC at $0000-$003F only (no $3C00-$3FFF GRAM
# alias, no write aliases at $4000/$8000/$C000 and $7800/$B800/$F800, no
# mode switch through $x021). SystemBus.mame_map applies all of it; the
# model's own map follows the hardware sources (DESIGN 2.5, 2.6). Found by
# step 4's longer traces: the EXEC reads $0040 (no cartridge, frame 87),
# Diner reads $3C00.
MAME_MAP_ZERO = ((0x0040, 0x00FF), (0x0360, 0x03FF), (0x0500, 0x0FFF), (0x3C00, 0x3FFF))


def iter_trace(path):
    """MAME trace records one at a time (lockstep.read_trace's format and
    parser, without holding the whole trace)."""
    import lockstep
    cur = None
    idx = 0
    with open(path) as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n")
            m = lockstep.LINE_RE.match(line)
            if m:
                if cur is not None:
                    yield cur
                cur = lockstep.Rec(idx, n, m)
                idx += 1
                continue
            m = lockstep.ACC_RE.match(line)
            if m and cur is not None:
                a = (m.group(1), int(m.group(2), 16), int(m.group(3), 16))
                (cur.intr_acc if cur.intr is not None else cur.acc).append(a)
                continue
            m = lockstep.INT_RE.match(line)
            if m and cur is not None:
                cur.intr = int(m.group(1), 16)
                continue
            if line.strip():
                raise ValueError("%s:%d: unparsed line %r" % (path, n, line))
    if cur is not None:
        yield cur


def mame_compare(trace_path, bios_dir=None, cart_path=None, context=6,
                 out=sys.stdout, voice_zero=False, timing="trace", stic_mode="mame",
                 on_bus=None, ecs=None, presses=None, voice_replay=False, cfg_path=None):
    """Run the model against a MAME trace (see the module docstring).
    timing "trace" takes the frame starts from the trace's frame numbers;
    "computed" uses MameTiming and checks every record's frame number
    against it. stic_mode is the STIC model's mode (tools/stic.py); with
    "stic" the CPU sees BUSRQ, which MAME never shows, so the comparison
    is expected to fail at the first stolen cycle. on_bus(bus) is called
    once the system exists (to set up frame capture). ecs: as make_system
    (MAME's intvecs: ("on", None); the ECS then runs as MAME's, tools/ecs.py
    MAME mode). presses: parse_presses text, the keys the trace's run
    pressed. voice_replay: the Intellivoice ($0080-$0081, build step 10)
    reads are taken from the trace."""
    tm = ListTiming([]) if timing == "trace" else MameTiming()
    bus, cpu = make_system(bios_dir, cart_path, tm, buslog=False, stic_mode=stic_mode, ecs=ecs,
                           mame_ecs=True, cfg_path=cfg_path)
    bus.mame_map = True
    if presses:
        bus.presses = parse_presses(presses)
    if voice_zero:
        bus.zero = MAME_VOICE_ZERO
    if on_bus is not None:
        on_bus(bus)

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

    def step():
        ev = cpu.step()
        key = mame_quirks(bus, cpu, ev)
        if key:
            stats["bias " + key] += 1
        if not ev.text.startswith("SDBD"):      # MAME runs SDBD + next as one step
            bus.boundary(cpu.cycle)
        return ev

    bus.read, bus.write = rd, wr
    stats = collections.Counter()
    prev_frame = 0
    for rec in iter_trace(trace_path):
        if rec.frame != prev_frame:
            if timing == "trace":
                tm.starts.append(rec.cycle)
            prev_frame = rec.frame
        if timing != "trace" and tm.frame(rec.cycle) != rec.frame:
            return _mame_fail(out, hist, rec, "frame: computed %d, MAME %d"
                              % (tm.frame(rec.cycle), rec.frame), stats)
        if (list(cpu.r), cpu.flags) != (rec.regs, rec.flags):
            return _mame_fail(out, hist, rec, "state: model R=%s SZOC=%s, MAME R=%s SZOC=%s" % (
                " ".join("%04X" % r for r in cpu.r), format(cpu.flags, "04b"),
                " ".join("%04X" % r for r in rec.regs), format(rec.flags, "04b")), stats)
        if bus._t(cpu.cycle) != rec.cycle:
            return _mame_fail(out, hist, rec, "cycle: model (MAME clock) %d, MAME %d"
                              % (bus._t(cpu.cycle), rec.cycle), stats)
        acc.clear()
        if voice_replay:
            bus.replay = {a: d for k, a, d in rec.acc if k == "R" and 0x80 <= a <= 0x81}
        ev = step()
        if ev.kind == "busak":
            return _mame_fail(out, hist, rec, "model takes a bus request (%s) before $%04X, "
                              "MAME does not" % (ev.text, rec.pc), stats)
        if ev.kind == "intr":
            return _mame_fail(out, hist, rec, "model takes INTRM before $%04X, MAME does not"
                              % rec.pc, stats)
        if ev.text.startswith("SDBD"):          # MAME shows SDBD + next as one step
            ev2 = step()
            ev.text += " / " + ev2.text
        want = list(rec.acc)
        if acc != want:
            return _mame_fail(out, hist, rec, "accesses: model %s, MAME %s" % (
                _fmt_acc(acc), _fmt_acc(want)), stats)
        stats["steps"] += 1
        hist.append("%6d c=%d %04X %s" % (rec.idx, rec.cycle, rec.pc, rec.text))
        if rec.intr is not None:
            acc.clear()
            if not cpu.interruptible:
                return _mame_fail(out, hist, rec, "MAME takes INTRM after $%04X, model not interruptible"
                                  % rec.pc, stats)
            ev = step()
            if ev.kind != "intr":
                return _mame_fail(out, hist, rec, "MAME takes INTRM after $%04X, model does not"
                                  % rec.pc, stats)
            if acc != list(rec.intr_acc):
                return _mame_fail(out, hist, rec, "interrupt accesses: model %s, MAME %s" % (
                    _fmt_acc(acc), _fmt_acc(rec.intr_acc)), stats)
            stats["interrupts"] += 1
    out.write("MAME_COMPARE pass: %d steps, %d interrupts, %d frames (%s frame starts); "
              "MAME clock bias SETC %d, SARC ,2 %d; MAME NEGR carry %d; every read and write "
              "equal\n" % (stats["steps"], stats["interrupts"], prev_frame + 1, timing,
                           stats["bias SETC"], stats["bias SARC2"], stats["bias NEGR0"]))
    return True


def _fmt_acc(a):
    return " ".join("%s %04X %04X" % x for x in a) or "(none)"


def _mame_fail(out, hist, rec, msg, stats):
    out.write("MAME_COMPARE FAIL at trace line %d (step %d, c=%d, PC $%04X %s): %s\n"
              % (rec.lineno, rec.idx, rec.cycle, rec.pc, rec.text, msg))
    for h in hist:
        out.write("  before: %s\n" % h)
    return False


def mame_quirks(bus, cpu, ev):
    """After a model step in a MAME-compatible run: follow MAME where our
    CPU model knowingly differs (docs/CPU_NOTES.md "Where the sources
    disagree"): its clock (rows 3-4, the cycle bias) and NEGR, which never
    sets C in MAME (row 5; MAME cp1610.cpp:196-205). Returns the quirk's
    name or None."""
    if ev.kind != "insn":
        return None
    key = _cycle_key(ev.text)
    if key:
        bus.bias += KNOWN_CYCLE_DIFF[key]
        return key
    if ev.text.startswith("NEGR") and cpu.C:
        cpu.C = 0
        return "NEGR0"
    return None


# ------------------------------------------------------------------ runs
def run_pictures(bus, cpu, last, mame_clock=False, max_cycles=None):
    """Run until the STIC has drawn picture `last` (picture n is drawn at
    the start of frame n: MAME's snapshot at its n-th frame). With
    mame_clock the model's cycle count runs on MAME's clock."""
    events = collections.Counter()
    while bus.vid.last_drawn < last:
        ev = cpu.step()
        events[ev.kind] += 1
        if mame_clock:
            mame_quirks(bus, cpu, ev)
            if ev.text.startswith("SDBD"):      # MAME runs SDBD + next as one step
                continue
        bus.boundary(cpu.cycle)
        if max_cycles is not None and cpu.cycle > max_cycles:
            raise RuntimeError("picture %d not drawn by cycle %d" % (last, max_cycles))
    return events


def system_for(mode, bios_dir=None, cart_path=None, buslog=False, ecs=None, cfg_path=None):
    """(bus, cpu, mame_clock) for a STIC mode: "mame" runs on MAME's frame
    timing, clock and memory map, "stic" and "none" on the RTL's. ecs: as
    make_system (in "mame" mode the ECS is MAME's)."""
    tm = MameTiming() if mode == "mame" else FrameTiming()
    bus, cpu = make_system(bios_dir, cart_path, tm, buslog=buslog, stic_mode=mode, ecs=ecs,
                           mame_ecs=mode == "mame", cfg_path=cfg_path)
    bus.mame_map = mode == "mame"
    return bus, cpu, mode == "mame"


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--cart")
    r.add_argument("--frames", type=int, default=10)
    r.add_argument("--bios-dir")
    r.add_argument("--stic-mode", choices=sticm.MODES, default="stic",
                   help="STIC timing (tools/stic.py); default stic (BUSRQ on)")
    r.add_argument("--ecs", choices=sorted(ECS_OVERRIDES), help="attach the ECS (menu override)")
    r.add_argument("--ecs-rom", help="ECS.bin (default: the BIOS directory's)")
    r.add_argument("--presses", help="parse_presses text")
    r.add_argument("--cfg", help="the cartridge's CFG (BIN + CFG)")
    mm = sub.add_parser("mame")
    mm.add_argument("trace")
    mm.add_argument("--cart")
    mm.add_argument("--bios-dir")
    mm.add_argument("--mame-voice-zero", action="store_true",
                    help="read $0080-$0081 as 0, as MAME's plain intv does")
    mm.add_argument("--timing", choices=("trace", "computed"), default="trace",
                    help="frame starts from the trace, or computed from MAME's "
                         "59.92 Hz and checked against the trace")
    mm.add_argument("--stic-mode", choices=sticm.MODES, default="mame")
    mm.add_argument("--cfg", help="the cartridge's CFG (BIN + CFG)")
    mm.add_argument("--ecs", choices=sorted(ECS_OVERRIDES), help="MAME's intvecs: on")
    mm.add_argument("--ecs-rom")
    mm.add_argument("--presses", help="parse_presses text: what the MAME run pressed")
    mm.add_argument("--voice-replay", action="store_true",
                    help="Intellivoice reads ($0080-$0081) from the trace (intvecs)")
    a = ap.parse_args()
    ecs = (a.ecs, a.ecs_rom) if a.ecs else None
    if a.cmd == "run":
        bus, cpu, mclk = system_for(a.stic_mode, a.bios_dir, a.cart, ecs=ecs, cfg_path=a.cfg)
        if a.presses:
            bus.presses = parse_presses(a.presses)
        done = [0]

        def show(n, pic, info):
            st = info["stats"]
            print("picture %d: display %s, VDR %d, BUSRQ %d stolen %d cycles, rows loaded %d, "
                  "PC $%04X" % (n, "on" if st["enabled"] else "off", st["vdr"],
                                st["requests"], st["stolen"], st["loaded"], cpu.r[7]))
        bus.vid.keep_frames = set()
        bus.vid.on_frame = show
        run_pictures(bus, cpu, a.frames, mclk)
        return 0
    return 0 if mame_compare(a.trace, a.bios_dir, a.cart, voice_zero=a.mame_voice_zero,
                             timing=a.timing, stic_mode=a.stic_mode, ecs=ecs, presses=a.presses,
                             voice_replay=a.voice_replay, cfg_path=a.cfg) else 1


if __name__ == "__main__":
    sys.exit(main())
