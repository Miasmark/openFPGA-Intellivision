# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Cartridge formats of build step 8 (docs/DESIGN.md 5.3, 5.4, 9 step 8; docs/CARTFORMATS.md):
the BIN+CFG parser, the Intellicart .rom parser, the map table the loader builds from any
format, and the cartridge model that answers the CPU through that table.

Written as the RTL works (src/fpga/core/intv_cfgparse.sv, intv_romparse.sv, intv_loader.sv,
intv_cart.sv): the CFG and .rom parsers are byte-at-a-time state machines with the RTL's
states, limits and error codes, the table builder walks the 4,096 entries in the RTL's
order, and the model's reads and writes go through the table to a model of the SRAM.
Python and RTL must agree (sim/tb/tb_loader.py compares them on every bus address).

Specifications (read as specifications only; no jzIntv code is used):
  jzIntv doc/utilities/as1600.txt          CFG [vars] names and values, icart_attr flags
  jzIntv doc/programming/intellicart.txt   the CFG sections, Intellicart memory model, bank
                                           registers $0040-$005F: icart = (a & $7FF) + (v << 8)
  jzIntv doc/rom_fmt/id_tag.txt            .rom structure, metadata tags, compat tag $06
  Intellicart manual (research/datasheets-licences/text/IntellicartManual.booklet.txt):
                                           download format, access table nibbles (R 1, W 2,
                                           B 8), fine-address table [0lll 0hhh], CRC-16
                                           (poly $1021, init $FFFF, MSB first)
  as1600 outputs (tools run as programs):  the N (narrow) bit 4 in the access nibble, PAGE in hex
  jzIntv doc/tech/ecs.html                 ECS-style page selects: $xA5y written to $xFFF
  MAME src/devices/bus/intv/slot.cpp:225-290 (BSD-3, read for facts): MAME loads a .rom's
                                           segments and skips its tables

Python 3.8+, standard library only. Run with python3 -I.
"""
import struct
import zlib

# ---------------------------------------------------------------------------------------
# SRAM map (intv_media.sv) and the map table
# ---------------------------------------------------------------------------------------
SRAM_WORDS = 0x20000
PLANE_WORDS = 0x10000           # plane 1: the image at file offsets, or a .rom's Intellicart space
RAM_BASE = 0x18000              # cart RAM area: 64 blocks of 256 cells (saved in the state)
RAM_BLOCKS = 64
POOL_BASE = 0x1E000             # assembled ROM blocks (partial or multi-range CFG blocks)
POOL_BLOCKS = 32

NENT = 4096                     # map table entries: {r = a[15:12], y = page, b = a[11:8]}
E_S, E_R, E_W, E_N, E_B = 1 << 21, 1 << 20, 1 << 19, 1 << 18, 1 << 17
E_BASE = 0x1FFFF
E_TLO, E_THI = 30, 22           # [37:30] first, [29:22] last word of the block that answers
TRIM_FULL = (0x00 << E_TLO) | (0xFF << E_THI)

# the Intellicart bank registers after a load: each 2K window onto its own address (as jzIntv
# starts them; intellicart.txt calls the start state undefined): $40+r = r << 4, $50+r = r << 4 | 8
BANK0 = [((i & 15) << 4) | (8 if i & 16 else 0) for i in range(32)]

FMT_NONE, FMT_RAW, FMT_CFG, FMT_ROM = 0, 1, 2, 3
FMT_NAMES = {FMT_NONE: 'none', FMT_RAW: 'raw', FMT_CFG: 'bin+cfg', FMT_ROM: 'rom'}
LAYOUT_CFG, LAYOUT_ROM = 0xFE, 0xFF

# flags (as tools/mapper/intvcart.py)
FLAG_ECS, FLAG_VOICE, FLAG_RAM, FLAG_PAGED = 0x01, 0x02, 0x04, 0x08
FLAG_JLP, FLAG_ECS_OFF, FLAG_ESTIMATED, FLAG_ECS_RISK = 0x10, 0x20, 0x40, 0x80

# refusal codes (the loader's fmt_err; err[5] set): 0 = none
ERR_CFG_SYNTAX = 0x10       # a line of a map section does not parse
ERR_CFG_MANY = 0x11         # more than MAXR ranges
ERR_CFG_RANGE = 0x12        # lo > hi, an address or file offset past $FFFF
ERR_CFG_PAGE = 0x13         # PAGE on a [preload] line, or a page past F
ERR_CFG_MIX = 0x14          # [bankswitch] and PAGE in one CFG (as1600 refuses it too)
ERR_CFG_LTO = 0x15          # lto_mapper = 1: the LTO Flash mapper is not documented (DESIGN 13 item 11)
ERR_CFG_SHORT = 0x16        # the data table's CFG length is longer than the bytes that came
ERR_RAM_FULL = 0x18         # more than RAM_BLOCKS blocks of cart RAM
ERR_POOL_FULL = 0x19        # more than POOL_BLOCKS assembled blocks
ERR_ROM_RANGE = 0x20        # a segment's end below its start
ERR_ROM_SEGCRC = 0x21       # a segment's CRC-16
ERR_ROM_SHORT = 0x22        # the file ends before the enable tables and their CRC
ERR_ROM_TABCRC = 0x23       # the enable tables' CRC-16
ERR_ROM_LTO = 0x24          # compat tag asks for the LTO mapper
ERR_ROM_BIG = 0x25          # the file is longer than the loader takes (1 MiB)
ERR_NAMES = {
    ERR_CFG_SYNTAX: 'CFG syntax', ERR_CFG_MANY: 'CFG: too many ranges', ERR_CFG_RANGE: 'CFG: range',
    ERR_CFG_PAGE: 'CFG: PAGE', ERR_CFG_MIX: 'CFG: bankswitch with PAGE', ERR_CFG_LTO: 'CFG: lto_mapper',
    ERR_CFG_SHORT: 'CFG: shorter than its data table length', ERR_RAM_FULL: 'cart RAM over 16K cells',
    ERR_POOL_FULL: 'too many partial blocks', ERR_ROM_RANGE: '.rom: segment range',
    ERR_ROM_SEGCRC: '.rom: segment CRC', ERR_ROM_SHORT: '.rom: truncated', ERR_ROM_TABCRC: '.rom: table CRC',
    ERR_ROM_LTO: '.rom: LTO mapper', ERR_ROM_BIG: '.rom: too long'}

MAXR = 32                   # CFG ranges ([mapping] [preload] [memattr] [bankswitch] lines)

# range kinds
RK_MAP, RK_PRE, RK_MEM, RK_BSW = 1, 2, 3, 4
AT_R, AT_W, AT_N = 1, 2, 4


def crc32(b, c=0):
    return zlib.crc32(bytes(b), c) & 0xFFFFFFFF


def crc16(data, c=0xFFFF):
    """Intellicart CRC-16: poly $1021, init $FFFF, MSB first, no final XOR."""
    for x in data:
        c ^= x << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c


# ---------------------------------------------------------------------------------------
# CFG parser: a byte-at-a-time state machine, as intv_cfgparse.sv
# ---------------------------------------------------------------------------------------
SEC_NONE, SEC_MAP, SEC_PRE, SEC_MEM, SEC_BSW, SEC_VARS, SEC_SKIP = 0, 1, 2, 3, 4, 5, 6
SECTIONS = {b'mapping': SEC_MAP, b'preload': SEC_PRE, b'memattr': SEC_MEM, b'bankswitch': SEC_BSW,
            b'vars': SEC_VARS}
NAME_MAX = 12

(P_BOL, P_SKIP, P_HDR, P_N0D, P_N0, P_DASH, P_N1S, P_N1D, P_N1, P_AFT1, P_N2S, P_N2D, P_N2,
 P_AFT2, P_PG, P_PGWS1, P_PGWS, P_PGD, P_KWS, P_KW, P_KWWS, P_WID, P_END, P_VNAME, P_VEQ,
 P_VVAL0, P_VVAL, P_VEND, P_DEAD) = range(29)

WS = (0x20, 0x09, 0x0D)
LF = 0x0A


def _hexval(c):
    if 0x30 <= c <= 0x39:
        return c - 0x30
    if 0x41 <= c <= 0x46 or 0x61 <= c <= 0x66:
        return (c | 0x20) - 0x61 + 10
    return None


def _lower(c):
    return c | 0x20 if 0x41 <= c <= 0x5A else c


def _namechar(c):
    return 0x30 <= c <= 0x39 or 0x41 <= c <= 0x5A or 0x61 <= c <= 0x7A or c == 0x5F


class CfgParser:
    """Feed bytes one at a time (feed), then end(); results in .ranges, the flags, .err.

    Grammar (docs/CARTFORMATS.md 2): lines end at LF; CR, tab and space are blanks; ';' starts
    a comment; '[name]' at the start of a line selects a section (names compared in lower
    case; text after ']' ignored). A NUL byte ends the text. In [mapping] and [preload]:
    `lo - hi = addr [PAGE p]`; in [memattr]: `lo - hi = RAM|WOM|ROM [8|16]`; in [bankswitch]:
    `lo - hi`. Numbers are hex, `$` optional, at most 20 bits. Any other text in those four
    sections refuses the CFG. In [vars]: `name = decimal` (names case sensitive); anything
    else there is ignored. Lines before the first section, in [macro] and in unknown sections
    are ignored.
    """

    def __init__(self):
        self.sec = SEC_NONE
        self.st = P_BOL
        self.err = 0
        self.ended = False          # a NUL byte: the text ends there
        self.ranges = []            # (kind, haspage, page, attr, lo, hi, src)
        self.ecs = self.ecs_off = self.voice = self.jlp = False
        self.jlp_mode = self.jlp_flash = None   # build step 11: the first instance counts
        self.has_page = self.has_bsw = False
        self.name = b''
        self.nover = False
        self.num = [0, 0, 0]
        self.ovf = False
        self.page = 0
        self.haspage = False
        self.kw = b''
        self.attr = 0
        self.val = 0
        self.k = 0

    def _fail(self, code):
        if not self.err:
            self.err = code
        self.st = P_DEAD

    def _commit(self):
        """A map line is complete: check it and store the range."""
        if self.ovf:
            return self._fail(ERR_CFG_RANGE)
        if len(self.ranges) == MAXR:
            return self._fail(ERR_CFG_MANY)
        a, b, c = self.num
        sec = self.sec
        if a > b or b > 0xFFFF:
            return self._fail(ERR_CFG_RANGE)
        if sec in (SEC_MAP, SEC_PRE):
            if c > 0xFFFF or c + (b - a) > 0xFFFF:
                return self._fail(ERR_CFG_RANGE)
            if sec == SEC_PRE and self.haspage:
                return self._fail(ERR_CFG_PAGE)
            kind = RK_MAP if sec == SEC_MAP else RK_PRE
            self.ranges.append((kind, self.haspage, self.page, 0, c, c + (b - a), a))
            self.has_page |= self.haspage
        elif sec == SEC_MEM:
            self.ranges.append((RK_MEM, False, 0, self.attr, a, b, 0))
        else:
            self.ranges.append((RK_BSW, False, 0, 0, a, b, 0))
            self.has_bsw = True
        if self.has_page and self.has_bsw:
            return self._fail(ERR_CFG_MIX)

    def _apply_var(self):
        n, v = self.name, self.val
        if self.nover:
            return
        if n == b'ecs':
            self.ecs |= v == 1
        elif n == b'ecs_compat':
            self.ecs |= v == 3
            self.ecs_off |= v == 0
        elif n == b'voice':
            self.voice |= v == 1
        elif n == b'voice_compat':
            self.voice |= v in (2, 3)
        elif n in (b'jlp', b'jlp_accel'):
            self.jlp |= v != 0
            if self.jlp_mode is None:
                self.jlp_mode = min(v, 3)
        elif n in (b'jlp_flash', b'jlpflash'):  # jlpflash: IntyBASIC's spelling (JLP_NOTES 1.1)
            if self.jlp_flash is None:
                self.jlp_flash = v
        elif n == b'lto_mapper' and v != 0:
            self._fail(ERR_CFG_LTO)

    def _digit(self, k, c):
        v = (self.num[k] << 4) | _hexval(c)
        if v > 0xFFFFF:
            self.ovf = True
        self.num[k] = v & 0xFFFFF

    def _end(self, c):
        """Blanks, then the line's end: ';' or LF commits the line."""
        if c in WS:
            self.st = P_END
        elif c == 0x3B or c == LF:
            self._commit()
            if self.st != P_DEAD:
                self.st = P_BOL if c == LF else P_SKIP
        else:
            self._fail(ERR_CFG_SYNTAX)

    def _after1(self, c):
        if c == 0x3D:                              # '='
            if self.sec in (SEC_MAP, SEC_PRE):
                self.st = P_N2S
            elif self.sec == SEC_MEM:
                self.kw = b''
                self.st = P_KWS
            else:
                self._fail(ERR_CFG_SYNTAX)
        elif self.sec == SEC_BSW:
            self._end(c)
        else:
            self._fail(ERR_CFG_SYNTAX)

    def _after2(self, c):
        if _lower(c) == 0x70:                      # 'p' of PAGE
            self.k = 0
            self.st = P_PG
        else:
            self._end(c)

    def _kwend(self):
        if self.kw not in (b'ram', b'wom', b'rom'):
            self._fail(ERR_CFG_SYNTAX)
            return False
        self.attr = {b'ram': AT_R | AT_W, b'wom': AT_W, b'rom': AT_R}[self.kw]
        return True

    def _vend(self, c):
        """In a [vars] value: ';' or LF applies it."""
        self._apply_var()
        if self.st != P_DEAD:
            self.st = P_BOL if c == LF else P_SKIP

    def feed(self, c):
        if self.ended:
            return
        if c == 0x00:
            self.ended = True
            return
        self._step(c)

    def end(self):
        """End of the text: a last line feed completes the last line."""
        self._step(LF)
        self.ended = True
        return self

    def _step(self, c):
        st = self.st
        ws, lf = c in WS, c == LF
        hx = _hexval(c)
        if st == P_DEAD:
            return
        if st == P_BOL:
            if ws or lf:
                return
            if c == 0x3B:
                self.st = P_SKIP
            elif c == 0x5B:                        # '['
                self.name, self.nover = b'', False
                self.st = P_HDR
            elif self.sec in (SEC_MAP, SEC_PRE, SEC_MEM, SEC_BSW):
                self.num, self.ovf, self.haspage, self.page, self.attr = [0, 0, 0], False, False, 0, 0
                if c == 0x24:
                    self.st = P_N0D
                elif hx is not None:
                    self.num[0] = hx
                    self.st = P_N0
                else:
                    self._fail(ERR_CFG_SYNTAX)
            elif self.sec == SEC_VARS and _namechar(c):
                self.name, self.nover, self.val = bytes([c]), False, 0
                self.st = P_VNAME
            else:
                self.st = P_SKIP
        elif st == P_SKIP:
            if lf:
                self.st = P_BOL
        elif st == P_HDR:
            if c == 0x5D:                          # ']'
                self.sec = SECTIONS.get(self.name, SEC_SKIP) if not self.nover else SEC_SKIP
                self.st = P_SKIP
            elif lf:
                self.sec = SEC_SKIP
                self.st = P_BOL
            elif len(self.name) < NAME_MAX:
                self.name += bytes([_lower(c)])
            else:
                self.nover = True
        elif st in (P_N0D, P_N1D, P_N2D):
            k = (P_N0D, P_N1D, P_N2D).index(st)
            if hx is None:
                self._fail(ERR_CFG_SYNTAX)
            else:
                self.num[k] = hx
                self.st = (P_N0, P_N1, P_N2)[k]
        elif st == P_N0:
            if hx is not None:
                self._digit(0, c)
            elif ws:
                self.st = P_DASH
            elif c == 0x2D:
                self.st = P_N1S
            else:
                self._fail(ERR_CFG_SYNTAX)
        elif st == P_DASH:
            if c == 0x2D:
                self.st = P_N1S
            elif not ws:
                self._fail(ERR_CFG_SYNTAX)
        elif st in (P_N1S, P_N2S):
            k = 1 if st == P_N1S else 2
            if ws:
                return
            if c == 0x24:
                self.st = P_N1D if k == 1 else P_N2D
            elif hx is not None:
                self.num[k] = hx
                self.st = P_N1 if k == 1 else P_N2
            else:
                self._fail(ERR_CFG_SYNTAX)
        elif st == P_N1:
            if hx is not None:
                self._digit(1, c)
            elif ws:
                self.st = P_AFT1
            else:
                self._after1(c)
        elif st == P_AFT1:
            if not ws:
                self._after1(c)
        elif st == P_N2:
            if hx is not None:
                self._digit(2, c)
            elif ws:
                self.st = P_AFT2
            else:
                self._after2(c)
        elif st == P_AFT2:
            if not ws:
                self._after2(c)
        elif st == P_PG:                           # "AGE" after the P
            if _lower(c) == b'age'[self.k]:
                self.k += 1
                if self.k == 3:
                    self.st = P_PGWS1
            else:
                self._fail(ERR_CFG_SYNTAX)
        elif st == P_PGWS1:                        # at least one blank after PAGE
            if ws:
                self.st = P_PGWS
            else:
                self._fail(ERR_CFG_SYNTAX)
        elif st == P_PGWS:
            if ws:
                return
            if hx is None:
                self._fail(ERR_CFG_SYNTAX)
            else:
                self.page, self.haspage = hx, True
                self.st = P_PGD
        elif st == P_PGD:
            if hx is not None:
                self.page = (self.page << 4) | hx
                if self.page > 15:
                    self._fail(ERR_CFG_PAGE)
            else:
                self._end(c)
        elif st == P_KWS:
            if ws:
                return
            if 0x41 <= (c & 0xDF) <= 0x5A:
                self.kw = bytes([_lower(c)])
                self.st = P_KW
            else:
                self._fail(ERR_CFG_SYNTAX)
        elif st == P_KW:
            if len(self.kw) < 3 and 0x41 <= (c & 0xDF) <= 0x5A:
                self.kw += bytes([_lower(c)])
            elif len(self.kw) == 3 and (ws or lf or c == 0x3B):
                if self._kwend():
                    if ws:
                        self.st = P_KWWS
                    else:
                        self._end(c)
            else:
                self._fail(ERR_CFG_SYNTAX)
        elif st == P_KWWS:
            if ws:
                return
            if c == 0x38:                          # '8'
                self.attr |= AT_N
                self.st = P_END
            elif c == 0x31:                        # '1' of 16
                self.st = P_WID
            elif lf or c == 0x3B:
                self._end(c)
            else:
                self._fail(ERR_CFG_SYNTAX)
        elif st == P_WID:
            if c == 0x36:
                self.st = P_END
            else:
                self._fail(ERR_CFG_SYNTAX)
        elif st == P_END:
            self._end(c)
        elif st == P_VNAME:
            if _namechar(c):
                if len(self.name) < NAME_MAX:
                    self.name += bytes([c])
                else:
                    self.nover = True
            elif ws:
                self.st = P_VEQ
            elif c == 0x3D:
                self.st = P_VVAL0
            else:
                self.st = P_BOL if lf else P_SKIP
        elif st == P_VEQ:
            if c == 0x3D:
                self.st = P_VVAL0
            elif not ws:
                self.st = P_BOL if lf else P_SKIP
        elif st == P_VVAL0:
            if 0x30 <= c <= 0x39:
                self.val = c - 0x30
                self.st = P_VVAL
            elif not ws:
                self.st = P_BOL if lf else P_SKIP
        elif st in (P_VVAL, P_VEND):
            if st == P_VVAL and 0x30 <= c <= 0x39:
                self.val = min(255, self.val * 10 + c - 0x30)
            elif ws:
                self.st = P_VEND
            elif lf or c == 0x3B:
                self._vend(c)
            else:
                self.st = P_SKIP


def parse_cfg(text):
    """Parse a CFG's bytes; returns the CfgParser with its results."""
    p = CfgParser()
    for c in bytes(text):
        p.feed(c)
    return p.end()


# ---------------------------------------------------------------------------------------
# .rom parser: a byte-at-a-time state machine, as intv_romparse.sv
# ---------------------------------------------------------------------------------------
(R_N, R_NC, R_LO, R_HI, R_DATA, R_CRC1, R_CRC2, R_TAB, R_TCRC1, R_TCRC2,
 R_TLEN, R_TLENX, R_TTYPE, R_TBODY, R_TC1, R_TC2, R_DONE) = range(17)


def is_rom(data):
    """The loader's test, after byte 2 (MAME slot.cpp:450 makes the same test)."""
    return len(data) >= 3 and data[0] == 0xA8 and data[1] != 0 and data[1] == (data[2] ^ 0xFF)


class RomParser:
    """Bytes from offset 3 on (feed(offset, byte)); words go to .writes (icart addr, word)."""

    def __init__(self, nseg):
        self.nseg = nseg
        self.st = R_LO
        self.seg = 0
        self.crc = 0xFFFF
        self.err = 0
        self.writes = []            # (icart address, word), in stream order
        self.cover = set()          # 256-word Intellicart blocks a segment wrote
        self.tab = bytearray()
        self.tab_end = None         # offset after the tables' CRC
        self.compat = None          # (body bytes, offset after its CRC)
        self.lto = False

    def feed(self, off, c):
        st = self.st
        if self.err and st != R_DONE:
            return
        if st == R_LO:
            self.lo = c
            self.crc = crc16([c])
            self.st = R_HI
        elif st == R_HI:
            self.hi = c
            self.crc = crc16([c], self.crc)
            if self.hi < self.lo:
                self.err = ERR_ROM_RANGE
                return
            self.n = (self.hi - self.lo + 1) * 512
            self.i = 0
            self.st = R_DATA
        elif st == R_DATA:
            self.crc = crc16([c], self.crc)
            if self.i & 1 == 0:
                self.hb = c
            else:
                a = (self.lo << 8) + (self.i >> 1)
                self.writes.append((a & 0xFFFF, (self.hb << 8) | c))
                self.cover.add((a >> 8) & 0xFF)
            self.i += 1
            if self.i == self.n:
                self.st = R_CRC1
        elif st == R_CRC1:
            self.got = c << 8
            self.st = R_CRC2
        elif st == R_CRC2:
            if (self.got | c) != self.crc:
                self.err = ERR_ROM_SEGCRC
                return
            self.seg += 1
            if self.seg == self.nseg:
                self.st = R_TAB
                self.crc = 0xFFFF
            else:
                self.st = R_LO
        elif st == R_TAB:
            self.tab.append(c)
            self.crc = crc16([c], self.crc)
            if len(self.tab) == 48:
                self.st = R_TCRC1
        elif st == R_TCRC1:
            self.got = c << 8
            self.st = R_TCRC2
        elif st == R_TCRC2:
            if (self.got | c) != self.crc:
                self.err = ERR_ROM_TABCRC
                return
            self.tab_end = off + 1
            self.st = R_TLEN
        elif st == R_TLEN:                       # a tag: its length's first byte (0: the NUL tag)
            if c == 0:
                self.st = R_DONE
                return
            self.crc = crc16([c])
            self.tlen = c & 0x3F
            self.tnb = c >> 6
            self.tk = 0
            self.st = R_TLENX if self.tnb else R_TTYPE
        elif st == R_TLENX:
            self.crc = crc16([c], self.crc)
            self.tlen |= c << (6 + 8 * self.tk)
            self.tk += 1
            if self.tk == self.tnb:
                self.st = R_TTYPE
        elif st == R_TTYPE:
            self.crc = crc16([c], self.crc)
            self.ttype = c
            self.tbody = []
            self.st = R_TBODY if self.tlen else R_TC1
        elif st == R_TBODY:
            self.crc = crc16([c], self.crc)
            if len(self.tbody) < 5:
                self.tbody.append(c)
            self.tlen -= 1
            if self.tlen == 0:
                self.st = R_TC1
        elif st == R_TC1:
            self.got = c << 8
            self.st = R_TC2
        elif st == R_TC2:
            if (self.got | c) == self.crc and self.ttype == 0x06 and len(self.tbody) >= 3 \
                    and self.compat is None:
                self.compat = (list(self.tbody), off + 1)
            self.st = R_TLEN
        # R_DONE: bytes after the NUL tag are ignored

    def result(self, length):
        """(err, access table, fine table, compat body or None) for a file of `length` bytes."""
        if self.err:
            return self.err, None, None, None
        if self.tab_end is None or self.tab_end > length:
            return ERR_ROM_SHORT, None, None, None
        compat = self.compat[0] if self.compat and self.compat[1] <= length else None
        if compat and len(compat) >= 4 and compat[3] & 0x20:
            return ERR_ROM_LTO, None, None, None
        return 0, bytes(self.tab[:16]), bytes(self.tab[16:48]), compat


def parse_rom(data):
    p = RomParser(data[1])
    for off in range(3, len(data)):
        p.feed(off, data[off])
    return p


JLP_MAX_SECTORS = 16                    # the core's flash store (JLP_NOTES 5.3)


def jlp_config(mode, flash):
    """(mode, sectors) of a cartridge (JLP_NOTES 1.1-1.3): mode 0-3 (jlp_accel), sectors of
    1.5 KiB: 4 when mode >= 2 and no size is given, none for modes 0 and 1, at most
    JLP_MAX_SECTORS."""
    mode = mode or 0
    if mode < 2:
        return mode, 0
    return mode, min(4 if flash is None else flash, JLP_MAX_SECTORS)


def rom_jlp(compat):
    """(mode, sectors) from a .rom compat tag: byte 3 bits 7-6, {byte 3 bits 1-0, byte 4} (a
    missing byte 4 reads 0, as intv_romparse keeps it: no flash)."""
    if compat is None or len(compat) < 4:
        return jlp_config(0, None)
    return jlp_config(compat[3] >> 6, (compat[3] & 3) << 8 | (compat[4] if len(compat) >= 5 else 0))


def rom_flags(compat):
    """Compat tag ($06) body -> flags (id_tag.txt: 00 don't care, 01 supports, 10 requires,
    11 incompatible)."""
    f = 0
    if compat is None:
        return f
    ecs, voice = compat[0] >> 6, (compat[0] >> 2) & 3
    if ecs == 2:
        f |= FLAG_ECS
    elif ecs == 3:
        f |= FLAG_ECS_OFF
    if voice in (1, 2):
        f |= FLAG_VOICE
    if len(compat) >= 4 and compat[3] >> 6:
        f |= FLAG_JLP
    return f


# ---------------------------------------------------------------------------------------
# The map table builder (intv_loader.sv's finish), and the loaded cartridge
# ---------------------------------------------------------------------------------------
def ent(s=0, r=0, w=0, n=0, b=0, base=0, tlo=0x00, thi=0xFF):
    return (E_S if s else 0) | (E_R if r else 0) | (E_W if w else 0) | (E_N if n else 0) | \
        (E_B if b else 0) | (base & E_BASE) | (tlo << E_TLO) | (thi << E_THI)


def dec(e):
    return dict(s=bool(e & E_S), r=bool(e & E_R), w=bool(e & E_W), n=bool(e & E_N), b=bool(e & E_B),
                base=e & E_BASE, tlo=(e >> E_TLO) & 0xFF, thi=(e >> E_THI) & 0xFF)


def trim_ok(e, lo8):
    """The word lo8 of a storage block lies in the entry's trim (CFG blocks: the words its
    ranges declare, from the first to the last; every other format: the whole block)."""
    return (e >> E_TLO) & 0xFF <= lo8 <= (e >> E_THI) & 0xFF


def ent_text(e):
    if not e:
        return '-'
    d = dec(e)
    a = ''.join(k.upper() for k in 'rwnb' if d[k])
    t = '' if (d['tlo'], d['thi']) == (0, 0xFF) else '[%02X-%02X]' % (d['tlo'], d['thi'])
    return '%s@%05X%s' % (a or '-', d['base'], t) if d['s'] else a + '@none'


class Loaded:
    """What the loader leaves behind: SRAM contents, map table, paged mask, results."""

    def __init__(self):
        self.sram = {}                  # word address -> value (absent: never written, reads 0)
        self.table = [0] * NENT
        self.paged = 0
        self.limit = 0
        self.fmt = FMT_NONE
        self.crc = 0
        self.words = 0
        self.layout = 0
        self.flags = 0
        self.hit = False
        self.cfg_crc = 0
        self.jlp_mode, self.jlp_sectors = 0, 0  # build step 11
        self.noss = False
        self.err = 0                    # fmt_err (0: mapped)
        self.asm = []                   # (entry index, dest base, kind) assembled blocks
        self.notes = []

    def sram_rd(self, a):
        return self.sram.get(a & 0x1FFFF, 0)

    def summary(self):
        return dict(fmt=FMT_NAMES[self.fmt], crc='%08X' % self.crc, words=self.words, layout=self.layout,
                    flags='%02X' % self.flags, hit=int(self.hit), cfg_crc='%08X' % self.cfg_crc,
                    paged='%04X' % self.paged, noss=int(self.noss), err=self.err)


def _conflicts(table, flags):
    """ECS conflict flags of a CFG or .rom map (tools/mapper/README.md: ECS_OFF, ECS_RISK)."""
    if flags & FLAG_ECS:
        return 0
    f = 0
    for r in range(16):
        for b in range(16):
            e = table[(r << 8) | b]
            if not e & (E_R | E_W | E_B):
                continue
            a = (r << 12) | (b << 8)
            if r == 7 or 0x4000 <= a <= 0x47FF:
                f |= FLAG_ECS_OFF
            if r in (2, 14):
                f |= FLAG_ECS_RISK
    return f


def build_raw(ld, layout_entries, lid):
    """Map table from a CRC-table layout (32 entries of 16 bits; intvcart.page_entry)."""
    units = -(-ld.words // 2048)
    for r in range(16):
        for y in range(16):
            for b in range(16):
                le = layout_entries[(r << 1) | (b >> 3)]
                kind = le >> 14
                e = 0
                if kind == 1:
                    off = le & 0x1FF
                    if lid == 1 and off >= units:
                        kind = 0            # default map: cut at the image length
                    elif le >> 13 & 1:
                        if y < ((le >> 9) & 15) + 1:
                            e = ent(s=1, r=1, base=(off + 2 * y) * 2048 + (b & 7) * 256)
                    elif y == 0:
                        e = ent(s=1, r=1, base=off * 2048 + (b & 7) * 256)
                elif kind in (2, 3) and y == 0:
                    cells = 2048 >> ((le >> 6) & 7)
                    assert cells >= 256
                    e = ent(s=1, r=1, w=1, n=kind == 3,
                            base=RAM_BASE + (le & 0x3F) * 2048 + ((b & 7) * 256) % cells)
                ld.table[(r << 8) | (y << 4) | b] = e
                if kind == 1 and le >> 13 & 1:
                    ld.paged |= 1 << r
    ld.limit = ld.words


def cfg_paged(rng):
    """The paged 4K ranges: every range a [mapping] line with PAGE touches (the loader's first
    pass over the ranges)."""
    m = 0
    for (kind, hp, pg, at, lo, hi, src) in rng:
        if kind == RK_MAP and hp:
            for r in range(lo >> 12, (hi >> 12) + 1):
                m |= 1 << r
    return m


def cfg_data(rng_entry, y, pr):
    """A [mapping] or [preload] line gives data to page y of its range: a PAGE line on its own
    page; any other line on page 0, and on every page of a paged range (pr: as jzIntv, a line
    without PAGE stays mapped whatever page is selected)."""
    kind, hp, pg = rng_entry[0], rng_entry[1], rng_entry[2]
    if kind == RK_MAP and hp:
        return pg == y
    return kind in (RK_MAP, RK_PRE) and (y == 0 or pr)


H_NONE, H_RAM, H_UNPAGED = 0, 1, 2


def build_cfg(ld, cfg):
    """Map table from a CFG's ranges (word-exact; docs/CARTFORMATS.md 2).

    The walk is r, then b, then y (the RTL's order), so that a block's pages follow each other:
    - in a range no PAGE line touches, only page 0 is built (the others are never looked up)
    - in a paged range, lines without PAGE ([mapping] without PAGE, [preload], [memattr]) count
      on every page; a page's own PAGE lines are copied over them where both have words
    - a block with [memattr] RAM or WOM is one block of cart RAM on every page (built at page 0,
      the same entry on the others: the RAM answers there whatever page is selected; it starts
      with the words page 0 maps there)
    - a page with no PAGE line in the block gets the entry of the block without them (built
      once: one pool block, not one per page)
    Each entry keeps the first and last word of the block its ranges declare (the trim): words
    of the block outside it are not answered and not written (a [memattr] range of a few words
    does not make its whole 256-word block answer, as at $8000-$803F, the STIC's alias).
    """
    rng = cfg.ranges
    ld.paged = cfg_paged(rng)
    ram_next = pool_next = 0
    for r in range(16):
        pr = ld.paged >> r & 1
        for b in range(16):
            hmode, hent = H_NONE, 0
            b0 = (r << 12) | (b << 8)
            b1 = b0 + 255
            for y in range(16):
                idx = (r << 8) | (y << 4) | b
                if y and not pr:
                    ld.table[idx] = 0
                    continue
                if y and hmode == H_RAM:
                    ld.table[idx] = hent
                    continue
                app = y == 0 or pr
                R = W = N = B = 0
                cnt = pc = 0
                fbase, ffull = 0, False
                tlo, thi = 0xFF, 0x00
                for q in rng:
                    (kind, hp, pg, at, lo, hi, src) = q
                    if not (lo <= b1 and hi >= b0):
                        continue
                    full = lo <= b0 and hi >= b1
                    data = cfg_data(q, y, pr)
                    if data:
                        if kind == RK_MAP:
                            R = 1
                        cnt += 1
                        if cnt == 1:
                            fbase, ffull = (src + b0 - lo) & E_BASE, full
                        if kind == RK_MAP and hp:
                            pc = 1
                    elif kind == RK_MEM and app:
                        R |= at & AT_R
                        W |= (at & AT_W) >> 1
                        N |= (at & AT_N) >> 2
                    elif kind == RK_BSW and app:
                        B = R = 1
                    if data or (kind in (RK_MEM, RK_BSW) and app):
                        tlo = min(tlo, 0 if lo <= b0 else lo & 0xFF)
                        thi = max(thi, 0xFF if hi >= b1 else hi & 0xFF)
                if y and not pc and hmode == H_UNPAGED:
                    ld.table[idx] = hent
                    continue
                S = 0
                base = 0
                if W and not B:
                    if ram_next == RAM_BLOCKS:
                        ld.err = ERR_RAM_FULL
                        return
                    base = RAM_BASE + ram_next * 256
                    ram_next += 1
                    S = 1
                    if cnt:
                        ld.asm.append((idx, base, 'ram'))
                elif cnt == 1 and ffull:
                    base, S = fbase, 1
                elif cnt:
                    if pool_next == POOL_BLOCKS:
                        ld.err = ERR_POOL_FULL
                        return
                    base = POOL_BASE + pool_next * 256
                    pool_next += 1
                    S = 1
                    ld.asm.append((idx, base, 'pool'))
                if not B and not S:
                    R = 0
                if W and B:
                    ld.noss = True
                e = ent(S, R, W, N, B, base, tlo, thi)
                ld.table[idx] = e
                if y == 0:
                    hmode = H_RAM if (W and not B) else H_UNPAGED if not pc else H_NONE
                    hent = e
                elif not pc:
                    hmode, hent = H_UNPAGED, e
    ld.limit = ld.words
    # assembly: pool blocks filled with $FFFF, then the words of the lines without PAGE, then
    # the page's own PAGE lines (each pass in line order: a later line wins)
    for idx, base, kind in ld.asm:
        r, y, b = idx >> 8, (idx >> 4) & 15, idx & 15
        b0 = (r << 12) | (b << 8)
        pr = ld.paged >> r & 1
        if kind == 'pool':
            for i in range(256):
                ld.sram[base + i] = 0xFFFF
        for pas in (0, 1):
            for q in rng:
                (rk, hp, pg, at, lo, hi, src) = q
                if not cfg_data(q, y, pr) or int(rk == RK_MAP and hp) != pas:
                    continue
                for a in range(max(lo, b0), min(hi, b0 + 255) + 1):
                    s = src + (a - lo)
                    if s < ld.limit:
                        ld.sram[base + (a - b0)] = ld.sram_rd(s)


def build_rom(ld, access, fine):
    """Map table from a .rom's enable tables (Intellicart manual; jzIntv's N bit)."""
    ram_next = 0
    for r in range(16):
        for b in range(16):
            nib = (access[r] >> (4 if b >> 3 else 0)) & 15
            fb = fine[(16 if b >> 3 else 0) + r]
            lo, hi = (fb >> 4) & 7, fb & 7
            j = b & 7
            if not lo <= j <= hi:
                nib = 0
            R, W, N, B = nib & 1, (nib >> 1) & 1, (nib >> 2) & 1, (nib >> 3) & 1
            base = (r << 12) | (b << 8)
            idx = (r << 8) | b
            if W and not B:
                if ram_next < RAM_BLOCKS:
                    nb = RAM_BASE + ram_next * 256
                    ram_next += 1
                    ld.asm.append((idx, nb, 'rom'))
                    base = nb
                else:
                    ld.noss = True
            if W and B:
                ld.noss = True
            ld.table[idx] = ent(1, R, W, N, B, base)
    ld.limit = PLANE_WORDS
    for idx, base, kind in ld.asm:
        src = ((idx >> 8) << 12) | ((idx & 15) << 8)
        for i in range(256):
            ld.sram[base + i] = ld.sram_rd(src + i)


def load(image, cfg=None, tables=None, layout_pages=None, cfg_len=None):
    """The loader: an image's bytes (and a CFG's bytes, or None) -> Loaded.

    tables: intv_mapper.Tables (CRC table lookup); layout_pages: its .pages. cfg_len: the
    CFG's length in the data table (None: the CFG's own length); 0: no CFG (a stale one is
    not used); longer than the CFG, or more than 3 bytes shorter, refuses the CFG
    (ERR_CFG_SHORT); shorter cuts it.
    """
    ld = Loaded()
    data = bytes(image)
    ld.crc = crc32(data)
    ld.words = (len(data) + 1) // 2
    for i in range(RAM_BLOCKS * 256):           # the RAM area is cleared at every load
        ld.sram[RAM_BASE + i] = 0
    rom = is_rom(data)
    if not data or (ld.words > 0x10000 and not rom):
        ld.err = -1                             # no cartridge / too long: the loader's err[2:0]
        ld.words, ld.crc = 0, 0
        return ld
    if rom:
        if len(data) > 0x100000:
            ld.err = ERR_ROM_BIG
            return _refused(ld)
        p = parse_rom(data)
        # the stream wrote word 0 ($A8nn) before byte 2 decided the format
        ld.sram[0] = (data[0] << 8) | data[1]
        for a, w in p.writes:
            ld.sram[a] = w
        err, access, fine, compat = p.result(len(data))
        if err:
            ld.err = err
            return _refused(ld)
        for blk in range(256):
            if blk not in p.cover:
                for i in range(256):
                    ld.sram[(blk << 8) | i] = 0
        ld.fmt = FMT_ROM
        ld.layout = LAYOUT_ROM
        if cfg:
            ld.notes.append('CFG ignored: the image is a .rom')
        build_rom(ld, access, fine)
        ld.flags = rom_flags(compat)
        ld.jlp_mode, ld.jlp_sectors = rom_jlp(compat)
    else:
        words = struct.unpack('>%dH' % ld.words, data + (b'\0' if len(data) & 1 else b''))
        for i, w in enumerate(words):
            ld.sram[i] = w
        lid, flags, ok, hit = tables.lookup(ld.crc, ld.words)
        if not ok:
            lid, flags, hit = 1, FLAG_ESTIMATED, False
        if cfg is not None and cfg_len == 0:
            cfg = None                          # the data table lists no CFG: none is used
        if cfg is not None and cfg_len is not None:
            if cfg_len > len(cfg) or len(cfg) - cfg_len > 3:
                ld.err = ERR_CFG_SHORT
                return _refused(ld)
            cfg = cfg[:cfg_len]
        c = parse_cfg(cfg) if cfg else None
        if c is not None and c.err:
            ld.err = c.err
            return _refused(ld)
        vflags = 0
        if c is not None:
            ld.cfg_crc = crc32(cfg)
            ld.jlp_mode, ld.jlp_sectors = jlp_config(c.jlp_mode, c.jlp_flash)
            vflags = (FLAG_ECS if c.ecs else 0) | (FLAG_ECS_OFF if c.ecs_off else 0) | \
                (FLAG_VOICE if c.voice else 0) | (FLAG_JLP if c.jlp else 0)
        ld.fmt = FMT_RAW if c is None else FMT_CFG
        if c is not None and c.ranges:
            ld.layout = LAYOUT_CFG
            ld.hit = hit
            build_cfg(ld, c)
            if ld.err:
                return _refused(ld)
            ld.flags = vflags | (flags & (FLAG_ECS | FLAG_VOICE) if hit else 0)
        else:
            ld.layout, ld.hit = lid, hit
            build_raw(ld, layout_pages[lid] if lid < len(layout_pages) else [0] * 32, lid)
            ld.flags = flags
            if lid == 1 and not flags & FLAG_ECS:
                ld.flags |= _raw_default_conflicts(ld.table)
            ld.flags |= vflags
            return ld
    # RAM / PAGED flags and the ECS conflicts of a CFG or .rom map
    if any(e & E_W for e in ld.table):
        ld.flags |= FLAG_RAM
    if ld.paged:
        ld.flags |= FLAG_PAGED
    ld.flags |= _conflicts(ld.table, ld.flags)
    return ld


def _raw_default_conflicts(table):
    """The loader's conflict flags for the default map (2K pages 8, 14, 15: ECS_OFF; 4, 5, 28, 29:
    ECS_RISK), from the cut layout."""
    f = 0
    for p in range(32):
        r, h = p >> 1, p & 1
        if table[(r << 8) | (h << 3)] & (E_R | E_W):
            if p in (8, 14, 15):
                f |= FLAG_ECS_OFF
            if p in (4, 5, 28, 29):
                f |= FLAG_ECS_RISK
    return f


def _refused(ld):
    """A refused image maps nothing (layout 0); the SRAM keeps what the stream wrote."""
    ld.table = [0] * NENT
    ld.paged = 0
    ld.layout, ld.flags, ld.hit = 0, 0, False
    ld.fmt = FMT_NONE
    ld.cfg_crc = 0
    ld.noss = False
    ld.limit = 0
    ld.asm = []
    return ld


# ---------------------------------------------------------------------------------------
# The cartridge on the bus (intv_cart.sv)
# ---------------------------------------------------------------------------------------
class MapCart:
    """The cartridge port: page selects, Intellicart bank registers, the map table, SRAM.

    read(a) -> word or None (not answered: the bus reads $FFFF); write(a, v); reset() is the
    machine reset (page selects to 0; the bank registers keep their values: the Intellicart
    does not see the console's reset; after a load they are BANK0). Same interface as intvcart.CartModel (sel, reset,
    read, write, mapped_space_crc).
    """

    def __init__(self, ld):
        self.ld = ld
        self.table = ld.table
        self.sram = dict(ld.sram)
        self.sel = [0] * 16
        self.bank = list(BANK0)

    def reset(self):
        self.sel = [0] * 16

    def _lookup(self, a):
        """(entry, SRAM address or None: no storage, or a word outside the storage block's trim)."""
        r = a >> 12
        y = self.sel[r] if self.ld.paged >> r & 1 else 0
        e = self.table[(r << 8) | (y << 4) | ((a >> 8) & 15)]
        if e & E_B:
            ia = ((a & 0x7FF) + (self.bank[((a >> 11) & 1) << 4 | r] << 8)) & 0xFFFF
            e2 = self.table[((ia >> 12) << 8) | ((ia >> 8) & 15)]
            if not e2 & E_S or not trim_ok(e2, ia & 0xFF):
                return e, None
            return e, ((e2 & E_BASE) + (ia & 0xFF)) & 0x1FFFF
        if not e & E_S or not trim_ok(e, a & 0xFF):
            return e, None
        return e, ((e & E_BASE) + (a & 0xFF)) & 0x1FFFF

    def _limited(self, sa):
        return sa < PLANE_WORDS and sa >= self.ld.limit

    def read(self, a):
        a &= 0xFFFF
        e, sa = self._lookup(a)
        if not e & E_R or sa is None or self._limited(sa):
            return None
        v = self.sram.get(sa, 0)
        return v & 0xFF if e & E_N else v

    def attr(self, a):
        """(answered, R W N B bits, paged) as intv_cart's bus outputs give them for a read."""
        a &= 0xFFFF
        e, sa = self._lookup(a)
        hit = bool(e & E_R) and sa is not None and not self._limited(sa)
        bits = (1 if e & E_R else 0) | (2 if e & E_W else 0) | (4 if e & E_N else 0) | (8 if e & E_B else 0)
        return hit, bits, (self.ld.paged >> (a >> 12)) & 1

    def write(self, a, v, store=True):
        """The access is looked up with the selects and bank registers before this write;
        its page select or bank register load lands after it (intv_cart.sv). store=False:
        the ECS owns the address (build step 9): nothing is stored, the selects and bank
        registers still see the write."""
        a &= 0xFFFF
        v &= 0xFFFF
        e, sa = self._lookup(a)
        if store and e & E_W and sa is not None and not self._limited(sa):
            self.sram[sa] = v & 0xFF if e & E_N else v
        if a & 0xFFF == 0xFFF and (v & 0xFFF0) == ((a & 0xF000) | 0x0A50):
            self.sel[a >> 12] = v & 0xF
        if 0x40 <= a <= 0x5F:
            self.bank[a & 0x1F] = v & 0xFF

    def ram_cells(self):
        """The cart RAM area as the save state holds it (16K cells)."""
        return [self.sram.get(RAM_BASE + i, 0) for i in range(RAM_BLOCKS * 256)]

    def rom_space(self):
        out = []
        for a in range(0x10000):
            e, sa = self._lookup(a)
            v = self.read(a) if (e & E_R and not e & E_W) else None
            out.append(0xFFFF if v is None else v)
        return out

    def npages(self, r):
        """1 + the highest page of range r that maps anything."""
        n = 1
        for y in range(16):
            if any(self.table[(r << 8) | (y << 4) | b] & (E_R | E_W) for b in range(16)):
                n = y + 1
        return n

    def mapped_space_crc(self):
        """The 64K-word space at reset paging and the load's bank registers (ROM words as read,
        $FFFF for RAM and unmapped), then for each paged 4K range its pages 1 .. n-1 (tools/mapper/README.md)."""
        saved, sbank = list(self.sel), list(self.bank)
        self.reset()
        self.bank = list(BANK0)
        crc = crc32(struct.pack('>65536H', *self.rom_space()))
        for r in range(16):
            if self.ld.paged >> r & 1:
                for y in range(1, self.npages(r)):
                    self.sel[r] = y
                    blk = [self.read((r << 12) + i) for i in range(0x1000)]
                    crc = crc32(struct.pack('>4096H', *[0xFFFF if v is None else v for v in blk]), crc)
                self.sel[r] = 0
        self.sel, self.bank = saved, sbank
        return crc

    # save state words (intv_cart.sv, module id $0B; tools/savestate.py)
    def ss_words(self):
        ld = self.ld
        w = [ld.crc, (int(ld.hit) << 16) | (ld.flags << 8) | ld.layout, ld.words, ld.cfg_crc,
             (ld.jlp_sectors << 21) | (ld.jlp_mode << 19) | (ld.fmt << 17) | (int(ld.noss) << 16) | ld.paged]
        w += [sum(self.sel[i] << (4 * i) for i in range(8)), sum(self.sel[8 + i] << (4 * i) for i in range(8))]
        w += [sum(self.bank[4 * k + i] << (8 * i) for i in range(4)) for k in range(8)]
        w.append(ld.limit)
        return w

    def ss_load(self, w):
        """A restore writes the selects and bank registers; the other words are the load's."""
        for i in range(8):
            self.sel[i] = (w[5] >> (4 * i)) & 15
            self.sel[8 + i] = (w[6] >> (4 * i)) & 15
        for k in range(8):
            for i in range(4):
                self.bank[4 * k + i] = (w[7 + k] >> (8 * i)) & 0xFF


SS_WORDS = 16
