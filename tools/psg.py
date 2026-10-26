#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""psg: model of the Intellivision's PSG, the AY-3-8914 (build step 6).

The golden model for src/fpga/core/intv_psg.sv (DESIGN.md 2.3, 3 row 9,
6.2, 9 step 6). tools/intv_system.py owns one and clocks it from the CPU
cycle count. Facts and sources (docs/PSG_NOTES.md has the full list and
the comparison with MAME):

Registers ($01F0 + n; MAME ay8910.cpp:1533 maps them to AY-3-8910
registers; S9 doc/programming/psg.txt gives the same table)
   n  8910  use                          kept bits
   0  R0    channel A period, low 8      FF
   1  R2    channel B period, low 8      FF
   2  R4    channel C period, low 8      FF
   3  R11   envelope period, low 8       FF
   4  R1    channel A period, high 4     0F
   5  R3    channel B period, high 4     0F
   6  R5    channel C period, high 4     0F
   7  R12   envelope period, high 8      FF
   8  R7    enable: bits 0-2 tone A-C off, 3-5 noise A-C off; 6-7 port
            direction, ignored (the 8914's ports are inputs, DESIGN 7.1)
   9  R6    noise period                 1F
  10  R13   envelope shape               0F
  11  R8    channel A volume             3F
  12  R9    channel B volume             3F
  13  R10   channel C volume             3F
  14  R14   port A: right hand controller (read only here)
  15  R15   port B: left hand controller
The kept bits are MAME's read masks for the AY-3-8914, tested on hardware
(MAME ay8910.cpp:1430-1450); the generators use no other bits.

Volume (AY-3-8914 only; S9 psg.txt "AY-3-8912 vs. AY-3-8914 notes"; MAME
ay8910.cpp mix: env_volume >> (3 - tone_envelope), ay8910.h tone_envelope
with PSG_EXTENDED_ENVELOPE): bits 5-4 = 00 fixed volume bits 3-0, 01 the
envelope >> 2, 10 the envelope >> 1, 11 the envelope. The AY-3-8916/8917
(ECS, step 9) have one select bit (bit 4: the envelope): variant "8917".

Clocking (DESIGN 2.3): the PSG runs at master / 2 and divides by 8 before
everything else, so its generators step once every 16 master clocks = 4
CPU cycles (one "tick", 223,721.6 Hz NTSC). A tone toggles every P ticks
(F = master / (32 P), S9 psg.txt; MAME ay8910.cpp sound_stream_update at
clock / 8), the noise prescaler every N ticks and the LFSR every second
toggle (master / (32 N)), the envelope takes a step every 2 E ticks (16
steps in 512 E master clocks, S9 psg.txt; MAME m_step = 2 for the AY
type). A period of 0 counts as 1 for tones and noise (MAME max(1, period);
the noise compare "count >= 0"); an envelope period of 0 steps on every
tick (MAME "++count >= 0"). Counters count up and restart at 0 when they
reach the period (">=", so a smaller period written while a count is past
it ends that half cycle on the next tick; MAME keeps the remainder there,
a difference of one half cycle at most, docs/PSG_NOTES.md).

  The machine's tick: the PSG ticks at the end of CPU cycles 0, 4, 8, ...
  from the first fetch (model cycle 0); intv_psg.sv counts the same CPU
  cycle enables and is held in reset with the CPU until then. A register
  write in cycle c (its DW phase) takes effect after the tick that ends
  cycle c, as every register in the RTL changes on the clock enable that
  ends its write cycle.

Noise: 17-bit LFSR, shifted right, input bit0 ^ bit3, output bit 0, 1
after reset (MAME ay8910.h noise_rng_tick; DESIGN decision 3).

Envelope: a 4-bit step counting down from 15 after every write of the
shape register (even the same value), volume = step ^ attack (attack 0 or
15 from shape bit 2); shapes with bit 3 clear act as hold = 1, alternate
= attack; at the end of a cycle, hold stops it (after inverting attack if
alternate), else alternate inverts attack and the step wraps to 15 (MAME
ay8910.h envelope_t::set_shape, ay8910.cpp sound_stream_update). The
write does not restart the envelope's period counter (MAME neither).

Mixer (S9 psg.txt; MAME ay8910.cpp): a channel is on while (tone output
or tone disabled) and (noise output or noise disabled); its level is its
volume when on, 0 when off.

DAC: one 16-level curve for fixed and envelope volumes, MAME's AY-3-8910
table (ay8910.cpp ay8910_param: resistances from Matthew Westcott's
measurements, public domain; build_single_table with a 1000 ohm load and
"zero is off", normalised as MAME's legacy output does) scaled to 0-10,922
so that three channels at full volume fit in 15 bits. The board ties the
three outputs together (DESIGN 6.2: SM Fig 7-2): the mix is their sum.

48 kHz (DESIGN 6.2; what intv_psg.sv gives the Pocket): every tick takes
the mix of the levels before its step, x 256, through two one-pole low
passes (y += (x - y) >> 1 each, at 223.7 kHz: -3 dB near 16.5 kHz, about
-12 dB at 48 kHz, against the aliasing of short periods and noise) and
adds the result >> 8 to a box filter; a phase accumulator in ticks
(+768,000 per tick, -3,579,545 per sample: 48 kHz from master / 16
exactly) ends a sample, which is the box's sum times 65536 / ticks in it
(4 or 5), >> 16. The filter is not machine state (DESIGN 4.4) and restarts
with the PSG.

State (the RTL's save-state words, docs/PSG_NOTES.md): the 14 registers,
three tone counters and outputs, the noise counter, prescaler and LFSR,
the envelope counter, step, attack and holding flag, the tick phase.
"""

import argparse
import sys

# Intellivision register n -> AY-3-8910 register (MAME ay8910.cpp:1533)
MAP8910 = (0, 2, 4, 11, 1, 3, 5, 12, 7, 6, 13, 8, 9, 10, 14, 15)
_MASK8910 = (0xFF, 0x0F, 0xFF, 0x0F, 0xFF, 0x0F, 0x1F, 0xFF,
             0x3F, 0x3F, 0x3F, 0xFF, 0xFF, 0x0F, 0xFF, 0xFF)
MASK = tuple(_MASK8910[MAP8910[n]] for n in range(14))

R_AFINE, R_BFINE, R_CFINE, R_EFINE = 0, 1, 2, 3
R_ACOARSE, R_BCOARSE, R_CCOARSE, R_ECOARSE = 4, 5, 6, 7
R_ENABLE, R_NOISE, R_SHAPE, R_AVOL, R_BVOL, R_CVOL = 8, 9, 10, 11, 12, 13

TICK_CYCLES = 4                 # CPU cycles per PSG tick (master / 16)
MASTER_HZ = 3579545             # NTSC (DESIGN 2.3)
TICK_HZ = MASTER_HZ / 16
SR_HZ = 48000
SR_STEP, SR_WRAP = 768000, MASTER_HZ     # 48000 / (MASTER_HZ / 16) = 768000 / MASTER_HZ

# MAME ay8910.cpp ay8910_param (r_up, r_down, 16 resistances), 1000 ohm load
_R_UP, _R_DOWN, _RL = 800000, 8000000, 1000
_RES = (15950, 15350, 15090, 14760, 14275, 13620, 12890, 11370,
        10600, 8590, 7190, 5985, 4820, 3945, 3017, 2345)
LEVEL_MAX = 10922


def _dac_table():
    t = []
    for j, r in enumerate(_RES):
        rt, rw = 1 / _R_DOWN + 1 / _RL + 1 / r, 1 / r
        if j:                   # zero is off
            rt += 1 / _R_UP
            rw += 1 / _R_UP
        t.append(rw / rt)
    lo, hi = min(t), max(t)
    return tuple(int((x - lo) / (hi - lo) * LEVEL_MAX + 0.5) for x in t)


DAC = _dac_table()   # (0, 148, 193, 252, 343, 476, 639, 1040, 1283, 2101, 2909, 3863, 5161, 6539, 8656, 10922)
RECIP = {4: 16384, 5: 13107}


class Psg:
    """One AY-3-8914 (variant "8914") or AY-3-8916/8917 ("8917")."""

    def __init__(self, variant="8914"):
        if variant not in ("8914", "8917"):
            raise ValueError("variant 8914 or 8917")
        self.variant = variant
        self.on_tick = None     # called with (tick number, levels after it) after every tick
        self.on_level = None    # called with the levels before each tick (the RTL's filter input)
        self.on_sample = None   # called with each 48 kHz sample
        self.mame_tone = False  # MAME's tone counter (remainder kept), checks only
        self.reset()

    # ---------------------------------------------------------------- state
    def reset(self):
        self.regs = [0] * 14
        self.tcount = [0, 0, 0]
        self.tout = [0, 0, 0]
        self.ncount = 0
        self.nprescale = 0
        self.rng = 1
        self.ecount = 0
        self.estep = 15         # shape 0 written at reset (MAME ay8910_reset_ym)
        self.eattack = 0
        self.eholding = 0
        self.ticks = 0          # ticks since reset
        self.box, self.boxn, self.srphase = 0, 0, 0
        self.lp1 = self.lp2 = 0

    def state(self, phase=0):
        """The RTL's 21 state words (intv_psg.sv); phase = the number of the
        CPU cycle now running mod 4."""
        w = [self.tcount[c] | self.tout[c] << 12 for c in range(3)]
        w.append(self.ncount | self.nprescale << 5)
        w.append(self.rng)
        w.append(self.ecount)
        w.append(self.estep | (self.eattack & 1) << 4 | self.eholding << 5 | (phase & 3) << 6)
        return list(self.regs) + w

    # ------------------------------------------------------------ registers
    def write(self, n, value):
        if not 0 <= n < 14:
            return
        self.regs[n] = value & MASK[n]
        if n == R_SHAPE:        # every write restarts the envelope
            self.estep = 15
            self.eholding = 0
            self.eattack = 15 if self.regs[R_SHAPE] & 4 else 0

    def read(self, n, pads=(0xFF, 0xFF)):
        n &= 15
        return pads[n - 14] if n >= 14 else self.regs[n]

    def _shape(self):
        s = self.regs[R_SHAPE]
        if s & 8:
            return s & 1, (s >> 1) & 1
        return 1, (s >> 2) & 1  # continue = 0: hold, alternate = attack

    # ----------------------------------------------------------- generators
    def tick(self):
        r = self.regs
        a0, b0, c0 = self.levels()      # the output up to this step (the filter's input)
        for c in range(3):
            p = r[c] | r[R_ACOARSE + c] << 8
            if self.mame_tone:  # MAME: keep the remainder (MAME check only)
                p = max(1, p)
                self.tcount[c] += 1
                while self.tcount[c] >= p:
                    self.tout[c] ^= 1
                    self.tcount[c] -= p
            elif self.tcount[c] + 1 >= p:
                self.tcount[c] = 0
                self.tout[c] ^= 1
            else:
                self.tcount[c] += 1
        if self.ncount + 1 >= r[R_NOISE]:
            self.ncount = 0
            self.nprescale ^= 1
            if not self.nprescale:
                b = (self.rng ^ (self.rng >> 3)) & 1
                self.rng = self.rng >> 1 | b << 16
        else:
            self.ncount += 1
        if not self.eholding:
            ep = r[R_EFINE] | r[R_ECOARSE] << 8
            if self.ecount + 1 >= 2 * ep:
                self.ecount = 0
                if self.estep == 0:
                    hold, alt = self._shape()
                    if hold:
                        if alt:
                            self.eattack ^= 15
                        self.eholding = 1
                    else:
                        if alt:
                            self.eattack ^= 15
                        self.estep = 15
                else:
                    self.estep -= 1
            else:
                self.ecount += 1
        self.ticks += 1
        if self.on_tick is not None:
            a, b, c = self.levels()
            self.on_tick(self.ticks, a | b << 4 | c << 8)
        if self.on_level is not None:
            self.on_level(a0 | b0 << 4 | c0 << 8)
        v = (DAC[a0] + DAC[b0] + DAC[c0]) << 8
        self.lp1 += (v - self.lp1) >> 1
        self.lp2 += (self.lp1 - self.lp2) >> 1
        self.box += self.lp2 >> 8
        self.boxn += 1
        self.srphase += SR_STEP
        if self.srphase >= SR_WRAP:
            self.srphase -= SR_WRAP
            s = (self.box * RECIP[self.boxn]) >> 16
            self.box, self.boxn = 0, 0
            if self.on_sample is not None:
                self.on_sample(s)

    def levels(self):
        """The three channels' 4-bit DAC inputs now."""
        r = self.regs
        ev = self.estep ^ self.eattack
        noise = self.rng & 1
        out = []
        for c in range(3):
            v = r[R_AVOL + c]
            on = (self.tout[c] | (r[R_ENABLE] >> c & 1)) & (noise | (r[R_ENABLE] >> (3 + c) & 1))
            sel = (v >> 4) & 3
            if self.variant == "8917":
                sel = 3 if sel & 1 else 0
            lv = (ev >> (3 - sel)) if sel else (v & 15)
            out.append(lv if on else 0)
        return out

    def mix(self):
        a, b, c = self.levels()
        return DAC[a] + DAC[b] + DAC[c]


class ClockedPsg(Psg):
    """A Psg clocked by the CPU cycle count (see the module docstring:
    ticks at the end of cycles 0, 4, 8, ...; a write in cycle c lands after
    the tick that ends cycle c).

    mame_grid (MAME checks only, tools/psg_compare.py): step on MAME's own
    grid instead. MAME runs the AY-3-8914 stream at int(1,789,772 / 8) =
    223,721 Hz (MAME intv.cpp:470 XTAL / 2 as an integer clock,
    ay8910.cpp device_start clock / 8), not at 4 CPU cycles (223,721.5
    Hz), and a write at time T first brings the stream up to and including
    sample floor(T x rate) (MAME sound.cpp sound_stream::update, "include
    the current sample"). T is the cycle count in MAME's attoseconds."""

    MAME_RATE = 1789772 // 8
    MAME_CYCLE_AS = 10 ** 18 // 894886

    def __init__(self, variant="8914"):
        self.mame_grid = False
        super().__init__(variant)
        self.wlog = None        # list: (cycle, n, value) of every write, if set

    def reset(self):
        super().reset()
        self.done = -1          # last cycle whose end has been processed

    def advance(self, cycle):
        """Process the ends of all cycles up to and including `cycle`."""
        if self.mame_grid:
            last = cycle * self.MAME_CYCLE_AS * self.MAME_RATE // 10 ** 18
            while self.ticks <= last:
                self.tick()
            return
        if cycle <= self.done:
            return
        # ticks at cycles t = 0, 4, 8, ... with done < t <= cycle
        t = (self.done // TICK_CYCLES + 1) * TICK_CYCLES
        while t <= cycle:
            self.tick()
            t += TICK_CYCLES
        self.done = cycle

    def bus_write(self, n, value, cycle):
        self.advance(cycle)
        if self.wlog is not None:
            self.wlog.append((cycle, n, value & 0xFFFF))
        self.write(n, value)


# --------------------------------------------------------------- self-test
def selftest():
    """Facts that need no reference: periods, LFSR period, envelope shapes."""
    errs = []
    p = Psg()
    # LFSR bit0 ^ bit3 is maximal: 2^17 - 1
    r, n = 1, 0
    while True:
        r = r >> 1 | ((r ^ (r >> 3)) & 1) << 16
        n += 1
        if r == 1:
            break
    if n != 131071:
        errs.append("LFSR period %d" % n)
    # tone period P: output toggles every P ticks
    for per in (0, 1, 2, 5, 0x123):
        p.reset()
        p.write(R_AFINE, per & 0xFF)
        p.write(R_ACOARSE, per >> 8)
        edges = []
        for k in range(4 * max(per, 1) + 2):
            o = p.tout[0]
            p.tick()
            if p.tout[0] != o:
                edges.append(k)
        d = {b - a for a, b in zip(edges, edges[1:])}
        if d != {max(per, 1)}:
            errs.append("tone period %d: toggles every %s ticks" % (per, sorted(d)))
    # envelope: the 16 shapes over 3 cycles, period 1 (2 ticks a step)
    want = {}
    dec, inc = list(range(15, -1, -1)), list(range(16))
    for s in range(16):
        if s & 8 == 0:
            want[s] = (dec if s & 4 == 0 else inc) + [0] * 32
        else:
            hold, alt, att = s & 1, s & 2, s & 4
            first = inc if att else dec
            second = (dec if att else inc) if alt else first
            if hold:
                last = first[-1] if not alt else (15 - first[-1])
                want[s] = first + [last] * 32
            else:
                want[s] = first + second + first
    for s in range(16):
        p.reset()
        p.write(R_EFINE, 1)
        p.write(R_SHAPE, s)
        seq = []
        for k in range(96):
            if k % 2 == 0:
                seq.append(p.estep ^ p.eattack)
            p.tick()
        if seq != want[s]:
            errs.append("shape %d: %s" % (s, seq))
    # volume select (8914): 01 = env >> 2, 10 = >> 1, 11 = env
    p.reset()
    p.write(R_ENABLE, 0x3F)     # tone and noise off: channel always on
    p.write(R_SHAPE, 0x0D)      # attack, hold: rises to 15 and stays
    p.write(R_EFINE, 1)
    for _ in range(40):
        p.tick()
    for sel, want_l in ((1, 3), (2, 7), (3, 15), (0, 9)):
        p.write(R_AVOL, sel << 4 | 9)
        if p.levels()[0] != want_l:
            errs.append("volume select %d: level %d" % (sel, p.levels()[0]))
    return errs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("selftest", "table"))
    a = ap.parse_args()
    if a.cmd == "table":
        print(" ".join(str(x) for x in DAC))
        return 0
    errs = selftest()
    for e in errs:
        print("FAIL", e)
    print("PSG_SELFTEST %s" % ("pass" if not errs else "FAIL (%d)" % len(errs)))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
