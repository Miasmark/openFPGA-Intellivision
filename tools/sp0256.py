#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""sp0256: model of the Intellivoice, the SP0256-012 speech processor behind the SPB640 speech
buffer (build step 10). The golden model for the RTL to come (DESIGN.md 9 step 10); facts, sources
and where they disagree are in docs/VOICE_NOTES.md. Source codes used below:
  G81  GI, SP-0256 Design Objective Specification, rev. Nov 1981 (sheets 6-7: the coefficient table
       T(X) x 512, 16-bit information lines; sheet 12: R, P, A, AI, PI; sheet 31: 7-bit PWM DAC)
  IS   SP0256 Instruction Set, J. Zbiciak and F. Palazzolo, rev. 23-Sep-2000 (reverse engineered):
       the opcodes, the data formats by MODE, bit order
  SM   Mattel Intellivoice Service Manual (Model 3330): 3.12 MHz resonator Y1, SPB640 "10 bit x 64
       FIFO", PWM output, the filters, EXT AUDIO
  M    MAME sound/sp0256.cpp and bus/intv/voice.cpp (BSD-3), read for facts: the SPB640 registers,
       the FIFO address, and the sample-by-sample behaviour the references are compared with
No code is taken from MAME or jzIntv: this is our own implementation of those facts.

The bus (SPB640 at $0080-$0081, M intv.cpp:308, sp0256.cpp spb640_r/w):
  read  $0080   bit 15 = LRQ: 1 = the SP0256 takes a new command (the last one was picked up)
  read  $0081   bit 15 = 1 when the FIFO holds 64 decles (full)
  write $0080   the command (8 bits, ALD): ignored while LRQ is 0; else LRQ := 0 and the
                microsequencer jumps to byte $1000 + 2 x command when it is next idle
  write $0081   bit 10 set: reset the FIFO and the SP0256; else push the 10 LSBs into the FIFO
                (ignored when it is full)
Command 0 lands at byte $1800, the SPB640's FIFO (SM: "Execute from SPB640"): the sequencer reads
its bits from the FIFO, 10 per decle, LSB first.

Timing: one sample every 312 cycles of the 3.12 MHz clock (10 kHz: SM Y1; the AL2 data sheet's
"0 to 5 kHz" response, G81's 5 kHz output filter). MAME runs the stream at 3.12 MHz / 336 =
9,285 Hz (sp0256.cpp CLOCK_DIVIDER 7*6*8; VOICE_NOTES 5 row 1), so compare maps MAME's times to
samples at MAME_HZ. The model itself is sample-stepped and does not care: step() makes one sample;
a bus access lands before the sample after the one its time falls in (MAME's stream rule, compare).
"""
import argparse
import copy
import os
import struct
import sys

SAMPLE_HZ = 10000                  # the chip: 3.12 MHz / 312 (SM Y1; AL2 "0 to 5 kHz", G81 5 kHz LPF)
MAME_HZ = 3120000 // 336           # MAME's stream rate, 9285 Hz (sp0256.cpp CLOCK_DIVIDER 7*6*8)
CPU_HZ = 3579545.0 / 4             # the CP1610's cycle rate (M intv.cpp:445)
ROM_BASE = 0x1000                  # the resident ROM's byte address (IS: "RESROM starts at $1000")
FIFO_BYTE = 0x1800                 # the SPB640's byte address (M sp0256.cpp FIFO_ADDR)
FIFO_DEPTH = 64                    # SM: "10 BIT x 64 FIFO"
PER_NOISE = 64                     # unvoiced and pause periods in samples (G81 sheet 12: 64 x R)

# G81 sheets 6-7: the coefficient table, |T(X)| x 512 for X = 0..127 (the sheets give negative
# values for positive inputs); identical to MAME's qtbl.
QTBL = (
    0, 9, 17, 25, 33, 41, 49, 57, 65, 73, 81, 89, 97, 105, 113, 121,
    129, 137, 145, 153, 161, 169, 177, 185, 193, 201, 209, 217, 225, 233, 241, 249,
    257, 265, 273, 281, 289, 297, 301, 305, 309, 313, 317, 321, 325, 329, 333, 337,
    341, 345, 349, 353, 357, 361, 365, 369, 373, 377, 381, 385, 389, 393, 397, 401,
    405, 409, 413, 417, 421, 425, 427, 429, 431, 433, 435, 437, 439, 441, 443, 445,
    447, 449, 451, 453, 455, 457, 459, 461, 463, 465, 467, 469, 471, 473, 475, 477,
    479, 481, 482, 483, 484, 485, 486, 487, 488, 489, 490, 491, 492, 493, 494, 495,
    496, 497, 498, 499, 500, 501, 502, 503, 504, 505, 506, 507, 508, 509, 510, 511)

# register numbers (IS "registers"; the order of the parameter file)
AM, PR, B0, F0, B1, F1, B2, F2, B3, F3, B4, F4, B5, F5, IA, IP = range(16)

# The data formats (IS, by opcode and MODE). Each field: (register, bits, shift, kind) with kind
# 'v' (replace the register by the bits << shift), 'f' (replace only the bits << shift: the MSBs;
# IS "SETMSB"), 'd' (add the sign-extended bits << shift: IS "DELTA"). Fields narrower than the
# register are MSB justified (IS); a B coefficient without its S bit has an implied sign 0, so it
# sits one bit lower (shift = 7 - bits). Per opcode: clear-all first (IS "setting the unspecified
# coefficients to zero"), clear B5/F5 in modes 00 and 10 (IS SETMSB notes).


def _load(bits_b, bits_f, signed_b):
    """One B/F pair of a LOAD format: (B field, F field)."""
    def one(reg, n, signed):
        return (reg, n, (8 - n) if signed else (7 - n), 'v')
    return bits_b, bits_f, signed_b, one


def _pairs(spec):
    """spec: [(pair, bB, bF, B signed)] -> fields."""
    out = []
    for pair, nb, nf, sb in spec:
        out.append((B0 + 2 * pair, nb, (8 - nb) if sb else (7 - nb), 'v'))
        out.append((F0 + 2 * pair, nf, 8 - nf, 'v'))
    return out


_AP = [(AM, 6, 2, 'v'), (PR, 8, 0, 'v')]
_INT5 = [(IA, 5, 0, 'v'), (IP, 5, 0, 'v')]
_LC_LO = _pairs([(0, 3, 5, False), (1, 3, 5, False), (2, 3, 5, False), (3, 4, 6, False), (4, 7, 6, True)])
_LC_HI = _pairs([(0, 6, 6, False), (1, 6, 6, False), (2, 6, 6, False), (3, 6, 7, False), (4, 8, 8, True)])
_P5 = _pairs([(5, 8, 8, True)])
_L4_LO = _pairs([(3, 4, 6, False), (4, 7, 6, True)])
_L4_HI = _pairs([(3, 6, 7, False), (4, 8, 8, True)])


def _msb(regs, n):
    return [(r, n, 8 - n, 'f') for r in regs]


def _delta(spec):
    """spec: [(reg, bits, msbs)] -> delta fields at the register's top msbs bits."""
    return [(r, n, 8 - m, 'd') for r, n, m in spec]


_D_AP = _delta([(AM, 4, 6), (PR, 5, 8)])
_D9_LO = _delta([(B0, 3, 4), (F0, 3, 5), (B1, 3, 4), (F1, 3, 5), (B2, 3, 4), (F2, 3, 5),
                 (B3, 3, 5), (F3, 4, 6), (B4, 4, 7), (F4, 4, 6)])
_D9_HI = _delta([(B0, 4, 7), (F0, 4, 6), (B1, 4, 7), (F1, 4, 6), (B2, 4, 7), (F2, 4, 6),
                 (B3, 4, 7), (F3, 5, 7), (B4, 5, 8), (F4, 5, 8)])
_DD_LO = _delta([(B3, 3, 5), (F3, 4, 6), (B4, 4, 7), (F4, 4, 6)])
_DD_HI = _delta([(B3, 4, 7), (F3, 5, 7), (B4, 5, 8), (F4, 5, 8)])
_D_5 = _delta([(B5, 5, 8), (F5, 5, 8)])

# FORMATS[opcode (IS notation, MSB first)][mode 0..3] = (clear all, clear B5/F5, fields)
FORMATS = {
    0b0001: [(True, False, [(AM, 8, 0, 'v'), (PR, 8, 0, 'v')] + _pairs([(p, 8, 8, True) for p in range(6)])
              + extra) for extra in ([], [(IA, 8, 0, 'v'), (IP, 8, 0, 'v')]) * 2],    # LOADALL: 8-bit A
    0b0010: [(True, False, _AP + _LC_LO + _INT5), (True, False, _AP + _LC_LO + _P5 + _INT5),
             (True, False, _AP + _LC_HI + _INT5), (True, False, _AP + _LC_HI + _P5 + _INT5)],  # LOAD_2
    0b1100: [(True, False, _AP + _LC_LO), (True, False, _AP + _LC_LO + _P5),
             (True, False, _AP + _LC_HI), (True, False, _AP + _LC_HI + _P5)],          # LOAD_C
    0b0100: [(True, False, _AP + _L4_LO), (True, False, _AP + _L4_LO + _P5),
             (True, False, _AP + _L4_HI), (True, False, _AP + _L4_HI + _P5)],          # LOAD_4
    # SETMSB_3: IS shows no pitch field; MAME reads one (as SETMSB_5): VOICE_NOTES 5 row 4
    0b0011: [(False, c5, [(AM, 6, 2, 'v'), (PR, 8, 0, 'v')] + _msb((F0, F1, F2), n) + _INT5)
             for c5, n in ((True, 5), (False, 5), (True, 6), (False, 6))],
    0b0101: [(False, c5, [(AM, 6, 2, 'v'), (PR, 8, 0, 'v')] + _msb((F0, F1, F2), n))
             for c5, n in ((True, 5), (False, 5), (True, 6), (False, 6))],             # SETMSB_5
    0b1010: [(False, c5, [(AM, 6, 2, 'v')] + _msb((F0, F1, F2), n))
             for c5, n in ((True, 5), (False, 5), (True, 6), (False, 6))],             # SETMSB_A
    0b0110: [(False, True, [(AM, 6, 2, 'v')] + _msb((F3, F4), 6)),
             (False, False, [(AM, 6, 2, 'v')] + _msb((F3, F4), 6) + _msb((F5,), 8)),
             (False, True, [(AM, 6, 2, 'v'), (F3, 7, 1, 'f'), (F4, 8, 0, 'f')]),
             (False, False, [(AM, 6, 2, 'v'), (F3, 7, 1, 'f'), (F4, 8, 0, 'f'), (F5, 8, 0, 'f')])],  # SETMSB_6
    0b1001: [(False, False, _D_AP + _D9_LO), (False, False, _D_AP + _D9_LO + _D_5),
             (False, False, _D_AP + _D9_HI), (False, False, _D_AP + _D9_HI + _D_5)],  # DELTA_9
    0b1101: [(False, False, _D_AP + _DD_LO), (False, False, _D_AP + _DD_LO + _D_5),
             (False, False, _D_AP + _DD_HI), (False, False, _D_AP + _DD_HI + _D_5)],  # DELTA_D
    0b1110: [(False, False, _AP)] * 4,                                                   # LOAD_E
    0b1111: [(True, False, [])] * 4,                                                     # PAUSE
}


def rev(x, n):
    """x's n low bits in reverse order."""
    r = 0
    for i in range(n):
        r = (r << 1) | ((x >> i) & 1)
    return r


def s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def coef(x):
    """An 8-bit coefficient register to its multiplier (x 512). G81 says the registers are sign
    magnitude; MAME takes the negative ones as two's complement (qtbl[0x7F & -x]): VOICE_NOTES
    5 row 3; sign and magnitude makes the games' filters blow up. The model follows MAME (the references are MAME's)."""
    return QTBL[(-x) & 0x7F] if x & 0x80 else -QTBL[x]


class Voice:
    """The SPB640 + SP0256-012 as the CP1610 bus sees them, sample-stepped."""

    def __init__(self, rom):
        self.mem = bytearray(0x10000)
        self.mem[ROM_BASE:ROM_BASE + len(rom)] = rom
        self.fifo = [0] * FIFO_DEPTH
        self.trace = None                     # a list: (sample, PC or FIFO (decle, bit), op, imm, MODE)
        self.underruns = 0                    # FIFO reads past the head (never reset)
        self.reset()

    # ---------------------------------------------------------------- state
    def reset(self):
        """Power-up and the $0081 bit-10 reset (M device_reset)."""
        self.fhead = self.ftail = self.fbit = 0
        self.r = [0] * 16                     # the encoded parameter registers
        self.amp = self.per = self.cnt = 0
        self.rpt = -1
        self.rng = 1
        self.bc = [0] * 6
        self.fc = [0] * 6
        self.z0 = [0] * 6
        self.z1 = [0] * 6
        self.interp = False
        self.halted = True
        self.lrq = 1
        self.ald = 0
        self.pc = 0                           # bit address
        self.stack = 0
        self.fsel = False
        self.mode = 0                         # bits 1-2: MODE, bits 4-5: repeat prefix
        self.page = ROM_BASE << 3
        self.samples = 0

    # ------------------------------------------------------------------ bus
    def read(self, addr):
        if addr & 1 == 0:
            return self.lrq << 15
        return 0x8000 if self.fhead - self.ftail >= FIFO_DEPTH else 0

    def write(self, addr, data):
        if addr & 1 == 0:
            if self.lrq:                      # a command while busy is dropped
                self.lrq = 0
                self.ald = (data & 0xFF) << 4
            return
        if data & 0x400:
            self.reset()
            return
        if self.fhead - self.ftail >= FIFO_DEPTH:
            return
        self.fifo[self.fhead % FIFO_DEPTH] = data & 0x3FF
        self.fhead += 1

    # ---------------------------------------------------------- the sequencer
    def getb(self, n):
        """n bits at the PC, LSB first, from the ROM space or the FIFO."""
        if self.fsel:
            if self.ftail + (self.fbit + n > 10) >= self.fhead:
                self.underruns += 1           # bits past the last decle pushed (M: stale FIFO words)
            d = self.fifo[self.ftail % FIFO_DEPTH] | (self.fifo[(self.ftail + 1) % FIFO_DEPTH] << 10)
            v = (d >> self.fbit) & ((1 << n) - 1)
            self.fbit += n
            if self.fbit >= 10:
                self.ftail += 1
                self.fbit -= 10
            return v
        a = self.pc >> 3
        d = self.mem[a & 0xFFFF] | (self.mem[(a + 1) & 0xFFFF] << 8)
        self.pc += n
        return (d >> ((self.pc - n) & 7)) & ((1 << n) - 1)

    def micro(self):
        """Run instructions until the filter has a repeat count (or the sequencer halts)."""
        while self.rpt <= 0:
            if self.halted and not self.lrq:          # a command is waiting: take it
                self.pc = self.ald | (ROM_BASE << 3)
                self.fsel = False
                self.halted = False
                self.lrq = 1
                self.ald = 0
                self.r = [0] * 16
            if self.halted:
                self.rpt = 1
                self.lrq = 1
                self.ald = 0
                self.r = [0] * 16
                return
            at = (self.ftail, self.fbit) if self.fsel else self.pc
            imm = self.getb(4)
            op = rev(self.getb(4), 4)                  # IS notation
            if self.trace is not None:
                self.trace.append((self.samples, at, op, imm, (self.mode >> 1) & 3))
            repeat = 0
            xfer = False
            if op == 0b0000:
                if imm:                                 # SETPAGE
                    self.page = rev(imm, 4) << 15
                else:                                   # RTS (an empty stack halts)
                    t, self.stack = self.stack, 0
                    if t:
                        self.pc = t
                    else:
                        self.halted = True
                        self.pc = 0
                    xfer = True
            elif op in (0b0111, 0b1011):                # JMP, JSR
                lo = self.getb(8)
                t = self.page | (rev(imm, 4) << 11) | (rev(lo, 8) << 3)
                if op == 0b1011:
                    self.stack = (self.pc + 7) & ~7
                self.pc = t
                xfer = True
            elif op == 0b1000:                          # SETMODE
                self.mode = ((imm & 8) >> 2) | (imm & 4) | ((imm & 3) << 4)
            else:
                repeat = imm | (self.mode & 0x30)
            if op != 0b1000:
                self.mode &= 0x0F                       # the repeat prefix lasts one instruction
            if xfer:
                self.fsel = self.pc == FIFO_BYTE << 3
                if self.fsel and self.fbit:             # a jump into the FIFO drops a partial decle
                    if self.ftail < self.fhead:
                        self.ftail += 1
                    self.fbit = 0
                continue
            if not repeat:
                continue
            self.rpt = repeat + 1
            clra, clr5, fields = FORMATS[op][(self.mode >> 1) & 3]
            if clra:
                self.r = [0] * 16
            if clr5:
                self.r[B5] = self.r[F5] = 0
            for reg, n, shf, kind in fields:
                v = self.getb(n)
                if kind == 'd' and v & (1 << (n - 1)):
                    v -= 1 << n
                v = (v << shf) & 0xFF
                if kind == 'f':
                    self.r[reg] = (self.r[reg] & ((1 << shf) - 1)) | v
                elif kind == 'd':
                    self.r[reg] = (self.r[reg] + v) & 0xFF
                else:
                    self.r[reg] = v
            if op == 0b1111:
                self.r[PR] = PER_NOISE
            self.regdec()
            return

    def regdec(self):
        self.amp = (self.r[AM] & 0x1F) << (self.r[AM] >> 5)
        self.cnt = 0
        self.per = self.r[PR]
        for i in range(6):
            self.bc[i] = coef(self.r[B0 + 2 * i])
            self.fc[i] = coef(self.r[F0 + 2 * i])
        self.interp = bool(self.r[IA] or self.r[IP])

    # -------------------------------------------------------------- the filter
    def filt(self):
        """One filter step: the sample, or None when the repeat count ran out at this step's
        excitation (the step is then made again with the next parameters)."""
        do_int = False
        if self.per:
            if self.cnt <= 0:
                self.cnt += self.per
                x = self.amp
                self.rpt -= 1
                do_int = self.interp
                self.z0 = [0] * 6
                self.z1 = [0] * 6
            else:
                x = 0
                self.cnt -= 1
        else:
            self.cnt -= 1
            if self.cnt <= 0:
                do_int = self.interp
                self.cnt = PER_NOISE
                self.rpt -= 1
                self.z0 = [0] * 6
                self.z1 = [0] * 6
            bit = self.rng & 1
            self.rng = (self.rng >> 1) ^ (0x4001 if bit else 0)
            x = self.amp if bit else -self.amp
        if do_int:
            self.r[AM] = (self.r[AM] + self.r[IA]) & 0xFF
            self.r[PR] = (self.r[PR] + self.r[IP]) & 0xFF
            self.amp = (self.r[AM] & 0x1F) << (self.r[AM] >> 5)
            self.per = self.r[PR]
        if self.rpt <= 0:
            return None
        s = x & 0xFFFF                                  # 16-bit information lines (G81 sheet 6)
        for j in range(6):
            s = (s + ((self.bc[j] * s16(self.z1[j])) >> 9)) & 0xFFFF
            s = (s + ((self.fc[j] * s16(self.z0[j])) >> 8)) & 0xFFFF
            self.z1[j] = self.z0[j]
            self.z0[j] = s16(s)
        return s16(s)

    def step(self):
        """One 10 kHz sample: the filter output, 16-bit signed (before the DAC)."""
        while True:
            if self.rpt <= 0:
                self.micro()
            v = self.filt()
            if v is not None:
                self.samples += 1
                return v


# ------------------------------------------------------------- RTL table
SVH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src', 'fpga', 'core', 'sp0256_fmt.svh')
KIND = {'v': 0, 'f': 1, 'd': 2}


def gen_svh():
    """sp0256_fmt.svh: FORMATS as two SystemVerilog functions for sp0256.sv (generated, like
    intv_ss_pkg.sv from savestate.py): fmt_hdr(op, mode) = {clear all, clear B5/F5, field count}
    and fmt_fld(op, mode, i) = {register, bits, shift, kind (0 v, 1 f, 2 d)}."""
    L = ['// Generated by tools/sp0256.py gen from sp0256.FORMATS: do not edit.',
         '// fmt_hdr(op, mode): {clear all, clear B5/F5, fields[4:0]}; ops not listed have no data.',
         '// fmt_fld(op, mode, i): {register[3:0], bits[3:0], shift[2:0], kind[1:0] (0 v, 1 f, 2 d)}.',
         '', 'function automatic logic [6:0] fmt_hdr(input logic [3:0] op, input logic [1:0] mode);',
         '    case ({op, mode})']
    for op in sorted(FORMATS):
        for m in range(4):
            clra, clr5, flds = FORMATS[op][m]
            L.append("        6'b%s: fmt_hdr = {1'b%d, 1'b%d, 5'd%d};" % (format(op << 2 | m, '06b'), clra, clr5, len(flds)))
    L += ["        default: fmt_hdr = 7'd0;", '    endcase', 'endfunction', '',
          'function automatic logic [12:0] fmt_fld(input logic [3:0] op, input logic [1:0] mode, input logic [4:0] i);',
          '    case ({op, mode, i})']
    for op in sorted(FORMATS):
        for m in range(4):
            for i, (reg, n, shf, kind) in enumerate(FORMATS[op][m][2]):
                L.append("        11'b%s: fmt_fld = {4'd%d, 4'd%d, 3'd%d, 2'd%d};" % (
                    format(op << 7 | m << 5 | i, '011b'), reg, n, shf, KIND[kind]))
    L += ["        default: fmt_fld = 13'd0;", '    endcase', 'endfunction', '',
          '// qtbl(x): |T(x)| x 512, G81 sheets 6-7 (QTBL)',
          'function automatic logic [8:0] qtbl(input logic [6:0] x);', '    case (x)']
    for i, q in enumerate(QTBL):
        L.append("        7'd%d: qtbl = 9'd%d;" % (i, q))
    L += ["        default: qtbl = 9'd0;", '    endcase', 'endfunction', '']
    return '\n'.join(L)


class VoiceBus:
    """The Intellivoice on the CPU bus as intv_voice.sv puts it (VOICE_NOTES 8.2): the sample
    enable a phase accumulator on CPU cycles (+inc per cycle, a sample each time it passes wrap;
    88 / 7,875 = exactly 10 kHz on NTSC clk_sys, 472.5 / 11 MHz, a cycle every 48 clocks), and the
    busy window: a sample fires at the end of cycle c, after that cycle's access; accesses at the
    ends of cycles c + 1 .. c + win read
    the values $0080 / $0081 had at the sample, and a write among them is held until the end of
    cycle c + win. Cycle numbers are the machine's (cycle 0: the first after reset, as the PSG's).
    Accesses must come in cycle order; access(cycle) first runs every cycle before it."""

    INC, WRAP, WIN = 88, 7875, 8
    MAME_INC, MAME_WRAP = 12480000, 1202727120          # 3,120,000 / 336 Hz on the CPU clock

    def __init__(self, rom, on=True, inc=None, wrap=None, win=None):
        self.v = Voice(rom)
        self.inc = inc or self.INC
        self.wrap = wrap or self.WRAP
        self.win_len = win or self.WIN
        self.on = on
        self.samples = []                               # (cycle, sample) as fired
        self.reset()

    def reset(self):
        self.v.reset()
        self.acc = 0
        self.win = 0
        self.held = None
        self.snap = (1, 0)
        self.done = 0                                   # cycles whose ce has run: 0 .. done - 1

    def _ce(self, k, acc_rw=None):
        """The ce that ends cycle k, with this cycle's access acc_rw = ('R', a) / ('W', a, d)."""
        val = None
        if acc_rw is not None:
            if acc_rw[0] == 'R':
                if self.win:
                    val = (self.snap[acc_rw[1] & 1]) << 15
                else:
                    val = self.v.read(acc_rw[1])
            elif self.win:
                self.held = (acc_rw[1], acc_rw[2])
            else:
                self.v.write(acc_rw[1], acc_rw[2])
        a = self.acc + self.inc                         # every cycle, window or not
        fire = a >= self.wrap
        self.acc = a - self.wrap if fire else a
        if self.win:
            self.win -= 1
            if not self.win and self.held is not None:
                self.v.write(*self.held)
                self.held = None
        elif fire:
            self.snap = (self.v.lrq, 1 if self.v.read(0x81) else 0)
            self.samples.append((k, self.v.step()))
            self.win = self.win_len
        self.done = k + 1
        return val

    def run_to(self, cycle):
        """Every ce before cycle `cycle` (cycles done .. cycle - 1), quickly when nothing is due."""
        while self.done < cycle:
            k = self.done
            if self.win or self.held is not None:
                self._ce(k)
                continue
            # cycles with no window: the accumulator alone, up to the next sample or `cycle`
            n = (self.wrap - self.acc + self.inc - 1) // self.inc     # ces until it passes wrap
            if k + n - 1 < cycle:
                self.acc += (n - 1) * self.inc
                self.done = k + n - 1
                self._ce(k + n - 1)
            else:
                self.acc += (cycle - k) * self.inc
                self.done = cycle

    def access(self, cycle, rw):
        """A bus access ('R', addr) or ('W', addr, data) at the end of cycle `cycle`: the read's
        value (bit 15 only) or None."""
        if not self.on:
            return 0xFFFF if rw[0] == 'R' else None
        self.run_to(cycle)
        return self._ce(cycle, rw)

    def state_words(self):
        """intv_voice.sv's words 20-22 (acc; {started, late, held, held_a, mode, win, snap_full,
        snap_lrq}; held data). started: the ce before cycle 0 has run (always, in cycle terms)."""
        h = self.held
        return [self.acc,
                (int(self.on) << 10) | (int(h is not None) << 8) | ((h[0] & 1 if h else 0) << 7) | (int(self.on) << 6)
                | (self.win << 2) | (self.snap[1] << 1) | self.snap[0],
                h[1] if h else 0]


OPS = {'RTS': 0b0000, 'LOADALL': 0b0001, 'LOAD_2': 0b0010, 'SETMSB_3': 0b0011, 'LOAD_4': 0b0100,
       'SETMSB_5': 0b0101, 'SETMSB_6': 0b0110, 'JMP': 0b0111, 'SETMODE': 0b1000, 'DELTA_9': 0b1001,
       'SETMSB_A': 0b1010, 'JSR': 0b1011, 'LOAD_C': 0b1100, 'DELTA_D': 0b1101, 'LOAD_E': 0b1110,
       'PAUSE': 0b1111}                         # IS notation


class Stream:
    """An SP0256 program written as bits in the chip's order (IS: fields LSB first, the opcode
    nibble reversed), for test streams through the FIFO: decles() gives the 10-bit words to push."""

    def __init__(self):
        self.bits = []

    def put(self, n, v):
        self.bits += [(v >> i) & 1 for i in range(n)]

    def op(self, name, imm=0, data=()):
        """One instruction: imm (4 bits), the opcode, then data: a list of values for the fields
        of FORMATS[opcode][mode] in order (the caller knows the mode), or (bits, value) pairs."""
        self.put(4, imm)
        self.put(4, rev(OPS[name], 4))
        for n, v in data:
            self.put(n, v)

    def setmode(self, mode, prefix=0):
        """SETMODE: MODE (IS notation, 0-3) and the repeat prefix (0-3, the repeat's bits 4-5)."""
        self.op('SETMODE', (mode & 1) << 3 | (mode & 2) << 1 | prefix)

    def jump(self, name, byte_addr, page=ROM_BASE << 3):
        """JMP or JSR to a byte address inside the current page (bit address page)."""
        b = byte_addr << 3
        assert b & ~0x7FFF == page and not b & 7
        self.op(name, rev(b >> 11 & 15, 4), [(8, rev(b >> 3 & 0xFF, 8))])

    def decles(self):
        b = self.bits + [0] * (-len(self.bits) % 10)
        return [sum(b[i + j] << j for j in range(10)) for i in range(0, len(b), 10)]


def fields(name, mode):
    """The data fields' widths of an opcode in a MODE (FORMATS), with zero repeat no data."""
    return [n for _, n, _, _ in FORMATS[OPS[name]][mode][2]]


def mame_out(v):
    """MAME's output value for a filter sample (sp0256.cpp HIGH_QUALITY: limit to 14 bits, << 2).
    The chip's DAC is a 7-bit PWM (G81 sheet 31): dac7() gives that."""
    return max(-8192, min(8191, v)) << 2


def dac7(v):
    """The 7-bit PWM DAC's code for a filter sample (G81 sheet 31; the bits taken are an
    assumption until a hardware recording: VOICE_NOTES 5 row 6)."""
    return max(-64, min(63, v >> 7))



class VoiceOut:
    """intv_voice.sv's output chain (VOICE_NOTES 8.5; not machine state): a sample held (clean:
    mame_out(); dac7: the 7-bit code at full scale, << 9), at each of the PSG's 48 kHz strobes a
    one-pole high-pass at about 150 Hz (x minus a low-pass of it, alpha 5/256) and two one-pole
    low-passes at about 5 kHz (alpha 1/2), in 1/256ths, then times the level (0, 1/2, 1, 3/2, 2)
    and saturated to 16 bits. strobe() gives the output as it stands at the strobe (the machine
    adds it to that strobe's PSG sample), then steps the filters."""

    def __init__(self, dac=False, level=4):
        self.dac, self.level = dac, level
        self.hs = self.hp = self.l1 = self.l2 = 0

    def sample(self, v):
        v = s16(v)
        self.hs = dac7(v) << 9 if self.dac else mame_out(v)

    def out(self):
        v = self.l2 >> 8
        g = (0, v >> 1, v, v + (v >> 1), v << 1)[self.level] if 0 <= self.level <= 4 else 0
        return max(-32768, min(32767, g))

    def strobe(self):
        o = self.out()
        x = self.hs << 8
        hpo = x - self.hp
        self.hp += ((x - self.hp) >> 8) * 5
        self.l2 += (self.l1 - self.l2) >> 1
        self.l1 += (hpo - self.l1) >> 1
        return o


# ----------------------------------------------------------------- references
def parse_log(path):
    """voice_t.log (tools/refs/mame_voice.sh): [(sample index, 'R'|'W', addr, data, state)], the
    index being floor(MAME's machine time x MAME_HZ): MAME's stream has made that sample (sound.cpp
    get_current_sample_index, update "include the current sample") before the access takes
    effect. state: MAME's (pc, halted, lrq, rpt, cnt, stack) when the run had STATE=1, else None."""
    ev = []
    for ln in open(path):
        t = ln.split()
        if len(t) < 4:
            continue
        sec, atto = t[0].split('.')
        st = None
        if len(t) >= 10:
            st = [int(x) for x in t[4:10]]
            st[3] = st[3] - (1 << 32) if st[3] >= 1 << 31 else st[3]
        ev.append(((int(sec) * 10**18 + int(atto)) * MAME_HZ // 10**18, t[1], int(t[2], 16), int(t[3], 16), st))
    return ev


def run_log(rom, ev, nsamp, k=1):
    """Play the bus accesses through the model on MAME's terms: an access at sample index n lands
    before sample n + k (k = 1: MAME's stream rule). At each read the value, and MAME's sequencer
    state when logged, must agree. Returns (samples, read mismatches, state
    mismatches, reads where MAME was between steps, reads where it was a sample ahead)."""
    v = Voice(rom)
    out = []
    bad = []
    sbad = []
    between = []
    ahead = []
    for e in ev:
        while len(out) < e[0] + k:
            out.append(mame_out(v.step()))
        if e[1] == 'W':
            v.write(e[2], e[3])
            continue
        got = v.read(e[2])
        if got != e[3]:
            bad.append((e, got))
        if e[4] is not None:
            mine = [v.pc, int(v.halted), v.lrq, v.rpt, v.cnt, v.stack]
            # MAME's stream is sometimes found stopped where a repeat count ran out (rpt 0) at a read
            # early in a frame, its counter left at a period boundary while the read's time is later
            # (VOICE_NOTES 6.3): there only the sequencer's position is compared
            pick = (0, 1, 2, 5) if e[4][3] == 0 else range(6)
            if [mine[i] for i in pick] != [e[4][i] for i in pick]:
                # a read in the sample before one of MAME's 50 Hz stream updates that falls on a
                # sample boundary (every 0.2 s at 9,285 Hz) can find the stream one sample ahead
                # (VOICE_NOTES 6.3): the model's state one sample later must then be MAME's
                w = copy.deepcopy(v)
                w.step()
                if [w.pc, int(w.halted), w.lrq, w.rpt, w.cnt, w.stack] != e[4]:
                    sbad.append((e, mine))
                else:
                    ahead.append(e)
            elif e[4][3] == 0:
                between.append(e)
    while len(out) < nsamp:
        out.append(mame_out(v.step()))
    return out[:nsamp], bad, sbad, between, ahead


def hook_start(ref, out, limit=4000):
    """MAME's sound hook (emu.register_sound_update) delivers the stream from its first mix after
    the script starts, not from sample 0: the offset of voice.bin's first sample in the model's
    sample numbering, found as the shift that lines up the first nonzero samples exactly."""
    f = next((i for i, x in enumerate(ref) if x), None)
    if f is None:
        return 0
    for off in range(limit):
        n = min(256, len(ref) - f)
        if f + off + n <= len(out) and out[f + off:f + off + n] == ref[f:f + n]:
            return off
    return None


def compare(rundir, rom, k=1):
    ev = parse_log(os.path.join(rundir, 'voice_t.log'))
    raw = open(os.path.join(rundir, 'voice.bin'), 'rb').read()
    ref = list(struct.unpack('<%dh' % (len(raw) // 2), raw))
    out, bad, sbad, between, ahead = run_log(rom, ev, len(ref) + 4000, k)
    off = hook_start(ref, out)
    if off is None:
        off = 0
        diff = list(range(len(ref)))
    else:
        out = out[off:off + len(ref)]
        diff = [i for i in range(len(ref)) if ref[i] != out[i]]
    return {'samples': len(ref), 'nonzero': sum(1 for x in ref if x), 'offset': off,
            'writes': sum(1 for e in ev if e[1] == 'W'), 'reads': sum(1 for e in ev if e[1] == 'R'),
            'states': sum(1 for e in ev if e[1] == 'R' and e[4] is not None), 'between': len(between), 'ahead': len(ahead),
            'diff': len(diff), 'first': diff[0] if diff else None, 'read_bad': len(bad),
            'first_read_bad': bad[0] if bad else None, 'state_bad': len(sbad),
            'first_state_bad': sbad[0] if sbad else None, 'out': out, 'ref': ref}


def selftest(rom):
    """Facts the model must keep (no reference needed)."""
    probs = []
    if len(QTBL) != 128 or QTBL[37] != 297 or QTBL[38] != 301 or QTBL[127] != 511:
        probs.append('QTBL against G81 sheets 6-7')
    if coef(0x05) != -41 or coef(0x80) != 0:
        probs.append('coef')
    if [(r, n) for r, n, _, _ in FORMATS[OPS['LOADALL']][1][2]][:2] != [(AM, 8), (PR, 8)] or \
            len(fields('LOADALL', 1)) != 16 or len(fields('LOADALL', 0)) != 14:
        probs.append('LOADALL: 8-bit A and P, 12 coefficients, interpolation in modes x1 (IS)')
    t = Stream()
    t.setmode(2, prefix=1)
    t.jump('JMP', FIFO_BYTE)
    v = Voice(rom)
    for d in t.decles():
        v.write(0x81, d)
    v.write(0x80, 0)                                   # $1000: the resident ROM's jump to $1800
    v.trace = []
    for i in range(400):
        v.step()
    ops = [(op, mode) for _, at, op, _, mode in v.trace if isinstance(at, tuple)]   # from the FIFO
    if ops[:2] != [(OPS['SETMODE'], 0), (OPS['JMP'], 2)]:
        probs.append('Stream: SETMODE 2 and JMP $1800 decode as written (%s)' % ops[:3])
    v = Voice(rom)
    if v.read(0x80) != 0x8000 or v.read(0x81) != 0:
        probs.append('reset: LRQ 1, FIFO not full')
    v.write(0x80, 6)
    if v.read(0x80) != 0:
        probs.append('ALD: LRQ 0 until the command is taken')
    v.write(0x80, 7)
    if v.ald != 6 << 4:
        probs.append('a command while busy is dropped')
    v.step()
    if v.read(0x80) != 0x8000 or v.halted:
        probs.append('the command is taken at the next sample')
    for i in range(70):
        v.write(0x81, i)
    if v.read(0x81) != 0x8000 or v.fhead != 64:
        probs.append('FIFO full at 64')
    v.write(0x81, 0x400)
    if v.read(0x81) != 0 or not v.halted:
        probs.append('bit 10 resets')
    # 6 = "Mattel Electronics Presents" plays and ends (halts) within 4 s
    v = Voice(rom)
    v.write(0x80, 6)
    n = nz = 0
    while n < 40000:
        nz += v.step() != 0
        n += 1
        if v.halted and n > 100:
            break
    if not (1000 < n < 40000) or nz < 1000:
        probs.append('command 6 plays and halts (%d samples, %d nonzero)' % (n, nz))
    print('SP0256_SELFTEST %s%s' % ('pass' if not probs else 'FAIL ', '; '.join(probs)))
    return 0 if not probs else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('cmd', choices=('selftest', 'compare', 'say', 'gen'))
    ap.add_argument('--check', action='store_true', help='gen: only check sp0256_fmt.svh is up to date')
    ap.add_argument('arg', nargs='*')
    ap.add_argument('--rom', help='the SP0256-012 ROM (default: ivoice.bin or IVOICE.BIN in INTV_BIOS_DIR)')
    ap.add_argument('--k', type=int, default=1, help='compare: the sample an access lands before')
    ap.add_argument('--wav', help='say/compare: write the model output (and ref) as WAV')
    a = ap.parse_args()
    if a.cmd == 'gen':
        t = gen_svh()
        if a.check:
            ok = os.path.exists(SVH) and open(SVH).read() == t
            print('SP0256_FMT %s' % ('up to date' if ok else 'STALE: run tools/sp0256.py gen'))
            return 0 if ok else 1
        open(SVH, 'w').write(t)
        print('wrote', os.path.normpath(SVH))
        return 0
    if not a.rom:
        bd = os.environ.get('INTV_BIOS_DIR', '')
        a.rom = next((os.path.join(bd, f) for f in ('ivoice.bin', 'IVOICE.BIN')
                      if os.path.exists(os.path.join(bd, f))), os.path.join(bd, 'ivoice.bin'))
    rom = open(a.rom, 'rb').read()
    if len(rom) != 2048:
        sys.exit('ivoice.bin: %d bytes, want 2048' % len(rom))
    if a.cmd == 'selftest':
        return selftest(rom)
    if a.cmd == 'say':                                  # say N: one resident phrase
        v = Voice(rom)
        v.write(0x80, int(a.arg[0]))
        out = []
        while len(out) < 60000:
            out.append(mame_out(v.step()))
            if v.halted and len(out) > 100:
                break
        print('phrase %s: %d samples, %d nonzero, peak %d' % (a.arg[0], len(out),
              sum(1 for x in out if x), max(abs(x) for x in out)))
        if a.wav:
            write_wav(a.wav, out)
        return 0
    rc = 0
    for d in a.arg:
        r = compare(d, rom, a.k)
        name = os.path.basename(os.path.normpath(d))
        ok = r['diff'] == 0 and r['read_bad'] == 0 and r['state_bad'] == 0 and r['nonzero'] > 0
        rc |= not ok
        print('%s: %d samples (%d nonzero, hook offset %d), %d writes, %d reads (%d with state, %d between steps, %d a sample ahead): '
              '%d samples differ%s, %d reads differ%s, %d states differ%s: VOICE_REF %s' % (
                  name, r['samples'], r['nonzero'], r['offset'], r['writes'], r['reads'], r['states'], r['between'], r['ahead'],
                  r['diff'], ' (first %d: ref %d model %d)' % (r['first'], r['ref'][r['first']], r['out'][r['first']])
                  if r['first'] is not None else '',
                  r['read_bad'], ' (first %s model %04X)' % (r['first_read_bad'][0][:4], r['first_read_bad'][1])
                  if r['first_read_bad'] else '',
                  r['state_bad'], ' (first %s: MAME %s model %s)' % (r['first_state_bad'][0][:4],
                                                                     r['first_state_bad'][0][4], r['first_state_bad'][1])
                  if r['first_state_bad'] else '', 'pass' if ok else 'FAIL'))
        if a.wav:
            write_wav(a.wav.replace('.wav', '_%s_model.wav' % name), r['out'])
            write_wav(a.wav.replace('.wav', '_%s_mame.wav' % name), r['ref'])
    return rc


def write_wav(path, s):
    with open(path, 'wb') as f:
        data = struct.pack('<%dh' % len(s), *s)
        f.write(b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVEfmt ' +
                struct.pack('<IHHIIHH', 16, 1, 1, SAMPLE_HZ, SAMPLE_HZ * 2, 2, 16) +
                b'data' + struct.pack('<I', len(data)) + data)


if __name__ == '__main__':
    sys.exit(main())
