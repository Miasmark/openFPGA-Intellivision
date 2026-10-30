#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""jlp: model of the JLP cartridge board's features (build step 11;
docs/JLP_NOTES.md, from the JLP Developer's Guide, "JLP Programmer's View").

The golden model for the core's JLP. tools/intv_system.py owns one Jlp
(when the cartridge asks for one) and asks it first for every bus access
(Jlp.owns: where the JLP answers, the cartridge's map does not).

Address map (features on; JLP_NOTES 2.1):
  $8023 / $8024  JF.first / JF.last (read)             flash, modes 2 and 3
  $8025 / $8026  JF.addr / JF.row (write)
  $802D-$802F    the write / read / erase commands (keys $C0DE, $DEC0, $BEEF)
  $8033 / $8034  $4A5A to $8033 switches RAM and accelerators on, $6A7A to
                 $8034 off (taken whether on or off)
  $8040-$9F7F    8,000 words of 16-bit RAM
  $9F80-$9F8B    multiply / divide operand pairs (MPYSS, MPYSU, MPYUS, MPYUU,
                 DIVSS, DIVUU), read back as written
  $9F8E / $9F8F  results: product bits 15-0 / 31-16; quotient / remainder
  $9FFC          CRC data (write only); $9FFD the CRC (read, write = seed)
  $9FFE          random number (read)
Everything else in $8000-$9FFF is not the JLP's (the map answers there).

Choices where the guide is silent (JLP_NOTES 2.2-2.6; each settled by a
black-box test, JLP_NOTES 4, and changed here if the test says otherwise):
  - x / 0: quotient $FFFF, remainder = the dividend; DIVSS truncates toward
    zero, the remainder takes the dividend's sign; $8000 / $FFFF gives
    $8000 remainder 0.
  - the switch follows the mode at every machine reset (on for 1 and 3).
  - while off, nothing but the switch answers (flash registers included).
  - CRC 0 and random $FFFF at reset; a random read returns the state, then
    state := crc16(state, the cycle's low 16 bits) (deterministic).
  - JF.first = 0, JF.last = 8 x sectors - 1; flash words erased = $FFFF.
  - a command that is accepted makes the JLP busy for BUSY CPU cycles: the
    whole cartridge port reads $FFFF and drops writes (Jlp.blocks); the
    command registers then read 0 (the guide's wait loop, ADD@ R1, PC).
    A dropped command (row or RAM range, a write to a row not empty, a
    wrong key) changes nothing and is not busy.
"""
import sys

RAM_LO, RAM_HI = 0x8040, 0x9F7F
MD_LO = 0x9F80
RES_LO, RES_HI = 0x9F8E, 0x9F8F
CRC_DATA, CRC_REG, RND = 0x9FFC, 0x9FFD, 0x9FFE
JF_FIRST, JF_LAST, JF_ADDR, JF_ROW = 0x8023, 0x8024, 0x8025, 0x8026
JF_WR, JF_RD, JF_ER = 0x802D, 0x802E, 0x802F
KEYS = {JF_WR: 0xC0DE, JF_RD: 0xDEC0, JF_ER: 0xBEEF}
SW_ON, SW_OFF = 0x8033, 0x8034
KEY_ON, KEY_OFF = 0x4A5A, 0x6A7A
ROW, SECTOR = 96, 8                       # words a row, rows a sector
BUSY = 100                               # CPU cycles a flash command keeps the port busy
POLY = 0xAD52


def crc16(crc, d):
    """One write to $9FFC: the guide's Perl (PV p.18), right-shifting."""
    crc ^= d & 0xFFFF
    for _ in range(16):
        crc = (crc >> 1) ^ (POLY if crc & 1 else 0)
    return crc


def s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def muldiv(fn, a, b):
    """(result $9F8E, result $9F8F) of function fn (0-5) on operands a, b."""
    if fn < 4:
        x = s16(a) if fn in (0, 1) else a & 0xFFFF
        y = s16(b) if fn in (0, 2) else b & 0xFFFF
        p = (x * y) & 0xFFFFFFFF
        return p & 0xFFFF, p >> 16
    if fn == 4:
        x, y = s16(a), s16(b)
        if y == 0:
            return 0xFFFF, a & 0xFFFF
        q = abs(x) // abs(y)
        if (x < 0) != (y < 0):
            q = -q
        return q & 0xFFFF, (x - q * y) & 0xFFFF
    x, y = a & 0xFFFF, b & 0xFFFF
    if y == 0:
        return 0xFFFF, x
    return x // y, x % y


class Jlp:
    def __init__(self, mode=1, sectors=0, flash=None):
        """mode: jlp_accel 1 (on at reset, no flash), 2 (off at reset, flash),
        3 (on, flash); sectors: jlp_flash (1.5 KiB each, modes 2 and 3);
        flash: the nonvolatile store's words (sectors x 768), else erased."""
        assert mode in (1, 2, 3)
        self.mode = mode
        self.sectors = sectors if mode in (2, 3) else 0
        n = self.sectors * SECTOR * ROW
        self.flash = list(flash) if flash is not None else [0xFFFF] * n
        assert len(self.flash) == n
        self.ram = [0] * (RAM_HI - RAM_LO + 1)    # power-on contents (the RTL's SRAM is cleared)
        self.reset()

    def reset(self):
        """Machine reset: the switch from the mode, the accelerators and the
        flash registers cleared. RAM and flash keep their contents."""
        self.on = self.mode != 2
        self.ops = [0] * 12
        self.res = [0, 0]
        self.crc = 0
        self.rnd = 0xFFFF
        self.jf_addr = 0
        self.jf_row = 0
        self.busy_until = -1

    # -- decode ------------------------------------------------------------
    def busy(self, cycle):
        return cycle < self.busy_until

    def blocks(self, cycle):
        """A flash command is running: the cartridge port answers nothing."""
        return self.busy(cycle)

    def owns(self, a):
        """The JLP answers a read of a (the cartridge's map does not)."""
        if not self.on:
            return False
        if RAM_LO <= a <= RAM_HI or MD_LO <= a <= MD_LO + 11 or a in (RES_LO, RES_HI, CRC_REG, RND):
            return True
        return self.sectors > 0 and a in (JF_FIRST, JF_LAST, JF_WR, JF_RD, JF_ER)

    def stores(self, a):
        """A write to a is the JLP's (the cartridge's map does not store it)."""
        if a in (SW_ON, SW_OFF):
            return True
        if not self.on:
            return False
        if RAM_LO <= a <= RAM_HI or MD_LO <= a <= MD_LO + 11 or a in (CRC_DATA, CRC_REG):
            return True
        return self.sectors > 0 and a in (JF_ADDR, JF_ROW, JF_WR, JF_RD, JF_ER)

    def read(self, a, cycle):
        """The word the JLP drives at a (owns(a) must be true)."""
        if RAM_LO <= a <= RAM_HI:
            return self.ram[a - RAM_LO]
        if MD_LO <= a <= MD_LO + 11:
            return self.ops[a - MD_LO]
        if a in (RES_LO, RES_HI):
            return self.res[a - RES_LO]
        if a == CRC_REG:
            return self.crc
        if a == RND:
            v = self.rnd
            self.rnd = crc16(self.rnd, cycle)
            return v
        if a == JF_FIRST:
            return 0
        if a == JF_LAST:
            return self.sectors * SECTOR - 1
        return 0                                # the command registers when idle

    def write(self, a, v, cycle):
        """Every CPU write (the JLP decodes its own; none while busy)."""
        if self.busy(cycle):
            return
        v &= 0xFFFF
        if a == SW_ON and v == KEY_ON:
            self.on = True
        elif a == SW_OFF and v == KEY_OFF:
            self.on = False
        if not self.stores(a) or a in (SW_ON, SW_OFF):
            return
        if RAM_LO <= a <= RAM_HI:
            self.ram[a - RAM_LO] = v
        elif MD_LO <= a <= MD_LO + 11:
            i = a - MD_LO
            self.ops[i] = v
            fn = i >> 1
            self.res = list(muldiv(fn, self.ops[2 * fn], self.ops[2 * fn + 1]))
        elif a == CRC_DATA:
            self.crc = crc16(self.crc, v)
        elif a == CRC_REG:
            self.crc = v
        elif a == JF_ADDR:
            self.jf_addr = v
        elif a == JF_ROW:
            self.jf_row = v
        elif a in KEYS and v == KEYS[a]:
            self.command(a, cycle)

    def command(self, a, cycle):
        row, addr = self.jf_row, self.jf_addr
        if row >= self.sectors * SECTOR:
            return
        if a == JF_ER:
            s = row // SECTOR * SECTOR * ROW
            self.flash[s:s + SECTOR * ROW] = [0xFFFF] * (SECTOR * ROW)
        else:
            if addr < RAM_LO or addr + ROW - 1 > RAM_HI:
                return
            f, r = row * ROW, addr - RAM_LO
            if a == JF_RD:
                self.ram[r:r + ROW] = self.flash[f:f + ROW]
            else:
                if any(w != 0xFFFF for w in self.flash[f:f + ROW]):
                    return
                self.flash[f:f + ROW] = self.ram[r:r + ROW]
        self.busy_until = cycle + BUSY

    # -- state ------------------------------------------------------------
    def state(self, cycle):
        """The JLP module's words: [0] {busy cycles left[15:0], on}, [1-12]
        the operands, [13-14] the results, [15] the CRC, [16] the random
        state, [17] JF.addr, [18] JF.row. RAM is its own region; flash is
        not in the state (the nonvolatile slot)."""
        left = max(0, self.busy_until - cycle)
        return ([left << 1 | int(self.on)] + self.ops + self.res +
                [self.crc, self.rnd, self.jf_addr, self.jf_row])

    def load_state(self, words, cycle):
        self.on = bool(words[0] & 1)
        self.busy_until = cycle + (words[0] >> 1 & 0xFFFF)
        self.ops = list(words[1:13])
        self.res = list(words[13:15])
        self.crc, self.rnd, self.jf_addr, self.jf_row = words[15:19]


# ---------------------------------------------------------------- self-test
def selftest():
    bad = []

    def chk(cond, what):
        if not cond:
            bad.append(what)

    # CRC vectors (JLP_NOTES 2.4) and the guide's $5AA4 warning
    chk(crc16(0x0000, 0x0001) == 0xEFCA, "crc16(0, 1)")
    chk(crc16(0xFFFF, 0x0000) == 0x5AB9, "crc16($FFFF, 0)")
    chk(crc16(0x1234, 0x5678) == 0x2A3F, "crc16($1234, $5678)")
    chk(crc16(0x0001, 0x5AA4) == 0x0001, "$5AA4 fixes seed 1")
    # multiply / divide
    chk(muldiv(0, 0xFFFF, 0xFFFF) == (1, 0), "MPYSS -1 x -1")
    chk(muldiv(3, 0xFFFF, 0xFFFF) == (1, 0xFFFE), "MPYUU $FFFF^2")
    chk(muldiv(1, 0xFFFF, 0xFFFF) == (1, 0xFFFF), "MPYSU -1 x 65535")
    chk(muldiv(2, 0x0002, 0xFFFD) == (0xFFFA, 0xFFFF), "MPYUS 2 x -3")
    chk(muldiv(5, 100, 7) == (14, 2), "DIVUU 100 / 7")
    chk(muldiv(4, s16(-7) & 0xFFFF, 2) == (0xFFFD, 0xFFFF), "DIVSS -7 / 2")
    chk(muldiv(4, 0x8000, 0xFFFF) == (0x8000, 0), "DIVSS $8000 / -1")
    chk(muldiv(5, 1234, 0) == (0xFFFF, 1234), "DIVUU / 0")
    # the board
    j = Jlp(mode=3, sectors=2)
    j.write(0x9F8B, 7, 0)                       # DIVUU.den, then num
    j.write(0x9F8A, 100, 1)
    chk((j.read(RES_LO, 2), j.read(RES_HI, 2)) == (14, 2), "DIVUU through the registers")
    j.write(0x9F87, 3, 3)                       # MPYUU op2 alone: op1 still 0
    chk(j.res == [0, 0], "MPYUU with op1 0")
    chk(j.read(0x9F8A, 4) == 100, "operands read back")
    j.write(CRC_REG, 0x1234, 5)
    j.write(CRC_DATA, 0x5678, 6)
    chk(j.read(CRC_REG, 7) == 0x2A3F, "CRC through the registers")
    r1, r2 = j.read(RND, 8), j.read(RND, 9)
    chk(r1 == 0xFFFF and r2 == crc16(0xFFFF, 8) and r1 != r2, "random")
    # flash: write a row, read it back elsewhere, refuse a second write, erase
    for i in range(ROW):
        j.write(RAM_LO + i, 0x1000 + i, 10)
    j.write(JF_ADDR, RAM_LO, 11)
    j.write(JF_ROW, 9, 12)
    j.write(JF_WR, 0xC0DE, 20)
    chk(j.flash[9 * ROW:10 * ROW] == [0x1000 + i for i in range(ROW)], "flash write")
    chk(j.blocks(20 + BUSY - 1) and not j.blocks(20 + BUSY), "busy window")
    chk(j.read(JF_WR, 20 + BUSY) == 0, "command register reads 0 when idle")
    j.write(JF_ADDR, 0x9000, 200)
    j.write(JF_RD, 0xDEC0, 201)
    chk(j.ram[0x9000 - RAM_LO:0x9000 - RAM_LO + ROW] == j.flash[9 * ROW:10 * ROW], "flash read")
    j.write(JF_ADDR, RAM_LO + 1, 400)
    j.write(JF_WR, 0xC0DE, 401)               # row 9 not empty: dropped
    chk(j.flash[9 * ROW] == 0x1000 and not j.busy(402), "write to a full row dropped")
    j.write(JF_ADDR, 0x9F40, 500)              # 0x9F40 + 95 > $9F7F: dropped
    j.write(JF_RD, 0xDEC0, 501)
    chk(not j.busy(502), "RAM range checked")
    j.write(JF_ROW, 16, 600)                   # two sectors: rows 0-15
    j.write(JF_ER, 0xBEEF, 601)
    chk(not j.busy(602), "row range checked")
    j.write(JF_ROW, 12, 700)
    j.write(JF_ER, 0xBEEF, 701)
    chk(j.flash[8 * ROW:16 * ROW] == [0xFFFF] * (SECTOR * ROW), "erase a sector")
    chk(j.read(JF_LAST, 900) == 15, "JF.last")
    # the switch
    j.write(SW_OFF, 0x6A7A, 1000)
    chk(not j.owns(RAM_LO) and not j.stores(0x9F80), "switched off")
    j.write(SW_ON, 0x6A7A, 1001)               # wrong key for $8033
    chk(not j.on, "wrong key ignored")
    j.write(SW_ON, 0x4A5A, 1002)
    chk(j.owns(RAM_LO), "switched on")
    j2 = Jlp(mode=2, sectors=1)
    chk(not j2.on, "mode 2 off at reset")
    j2.write(SW_ON, KEY_ON, 0)
    j2.reset()
    chk(not j2.on, "the switch back to the mode at reset")
    j3 = Jlp(mode=1)
    chk(not j3.owns(JF_FIRST) and not j3.stores(JF_WR), "mode 1: no flash registers")
    # state round trip
    st = j.state(1100)
    j4 = Jlp(mode=3, sectors=2)
    j4.load_state(st, 5000)
    chk(j4.state(5000) == st, "state round trip")
    for b in bad:
        print("FAIL", b)
    print("JLP_SELFTEST %s" % ("pass" if not bad else "FAIL (%d)" % len(bad)))
    return not bad


if __name__ == "__main__":
    sys.exit(0 if selftest() else 1)
