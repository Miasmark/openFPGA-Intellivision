#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""ecs: model of the Entertainment Computer System (build step 9; DESIGN.md
2.6, 3 module 13, 7.3, 15-20; research/ecs-rom-use/REPORT.md).

The golden model for src/fpga/core/intv_ecs.sv. tools/intv_system.py owns
one Ecs and asks it first for every bus access (Ecs.owns: where the ECS
answers, the cartridge does not).

Address map (DESIGN 2.6):
  $00E0-$00E3  UART stub (see "UART" below)
  $00F0-$00FF  PSG #2, the AY-3-8917 (tools/psg.py variant "8917": one
               envelope-select bit, bit 4), registers in the Intellivision
               order like PSG #1; reads $FF00 | register (MAME ecs.cpp
               read_ay: no $01xx upper-byte zero here). $00FE / $00FF are its
               I/O ports A and B: the keyboard matrix.
  $2000-$2FFF  ECS ROM 1 (ECS.bin words 0-4095), answers on page 1
  $4000-$47FF  ECS RAM, 2,048 x 8; reads give the upper byte 0 (MAME
               ecs.h read_ram; IntyBASIC's ECS test compares $55 / $AA)
  $7000-$7FFF  ECS ROM 2 (words 4096-8191), answers on page 0
  $E000-$EFFF  ECS ROM 3 (words 8192-12287), answers on page 1
Pages (REPORT 2, 5.4; jzIntv doc/tech/ecs.html via REPORT): a write of $xA5y
to $xFFF sets the ECS's page latch of range x to y, for x = 2, 7, E; the
ROM answers only on its own page, so any other value (IntyBASIC's $F)
pages it out. The ECS's latches are its own (separate from the
cartridge's selects, intv_pagesel in intv_cart), with their own reset
values (MODE below).

Ownership: where the ECS answers -- a ROM range while its page is
selected, the RAM, PSG #2, the UART -- the cartridge neither answers nor
stores (MAME ecs.cpp read_rome0: the ECS ROM or the subslot, never both).
Writes there still reach the cartridge's page selects and bank registers
(those are decoded from every write).

Modes (DESIGN 20):
  OFF       nothing of the ECS answers (unplugged)
  ON        attached, the ROM pages as at power-on: all latches 0, so
            $7000 answers (the EXEC runs the ECS boot) and $2000 / $E000
            do not (MAME ecs.cpp device_reset; REPORT 1)
  ATTACHED  attached, ROMs paged out from reset: latches $2 = 0, $7 = $F,
            $E = 0, as if a $4800 hook had run; RAM, PSG #2, keyboard and
            UART answer
auto_mode() is DESIGN 20's Auto rule, in its order: the CRC table's ECS
flag -> ON; a ROM word <= $03FF at $4800 (code there: the EXEC's $4800 hook,
REPORT 2) -> ON; the cartridge maps $4000-$47FF on page 0 (the ECS RAM would
clash), or the loader's ECS_OFF flag is set -> OFF; else ATTACHED. ECS_OFF
(cartfmt FLAG_ECS_OFF, flags bit 5; tools/mapper/README.md) is a .rom's
compat tag "ECS incompatible" (11), a CFG's `ecs_compat = 0`, or a hard
conflict the mapper found (ROM or RAM at $7000-$7FFF or $4000-$47FF: Centipede,
Dig Dug, Congo Bongo, Defender, both Pac-Man, the IMI and MTE201 test carts;
DESIGN decision 10 keeps the ECS off for them) (step-9 review: the tag was
recorded as a rule in the lane notes but not applied). Added here: no cartridge at all (an empty
image) -> ON, a console with the ECS and no cartridge (ECS BASIC). Refined
here: code at $4800 turns the ECS on only when the ECS boot would start the
cartridge straight, i.e. the header word at $500C passes the ECS ROM's test
((the word byte-swapped) & $FD == 1, REPORT 2 step 5: IntyBASIC's $03C0
does); otherwise ATTACHED. Without it the four Imagic titles that boot
through $4800 (Atlantis, Beauty & the Beast, Demon Attack, Microsurgeon)
got the ECS title and menu first, as on a console with the ECS (their
$500C fails the test), and a hook cartridge whose header fails the test
would get the ECS title read from ROMs its hook had paged out (REPORT 2).
ATTACHED is "as if a $4800 hook had run": the hook still runs. The menu's override (Auto / On / Off)
picks Auto or a fixed mode. Without the ECS ROM slot the ROMs never answer.

Keyboard matrix (DESIGN 7.3; INPUT_NOTES "ECS keyboards"): port A ($FE)
lines are the rows 0-7, port B ($FF) the columns 0-7; register 8 ($F8,
the 8910's R7) bit 6 makes port A an output, bit 7 port B (each port all
input or all output). A pressed switch (row r, column c; bit 8 r + c of
`keys`) joins its row and column line. Computer keyboard (no diodes): the
lines form connected groups through the pressed switches; a group reads 1
if any line in it is driven 1, else 0 if any is driven 0, else 1 (the
pull-ups). An output port drives every one of its lines with its latch.
That one rule gives ghosting and the masking where 1 beats 0 (two keys in
one column vanish from a row scan), both scan directions. Note: the ECS
ROM's scan ($7293) drives one row 0 and the seven others 1, so on that scan
three corners of a rectangle mask each other instead of ghosting the
fourth (W, Q, 1: all three vanish; no 3 appears).
Music synthesizer (diodes, DESIGN 7.3): a column reads 0 if a pressed key
joins it to a row driven 0, else 1; rows read their own drive or 1 (the
diodes let no column pull a row). No ghosting, no masking.
A port reads its lines (the group values), whether input or output (MAME
ay8910.cpp:1403-1425 returns the external data either way).

UART ($00E0-$00E3; REPORT 5.5): a stub. The ECS ROM's tape code polls
$00E0 bit 1 (transmitter ready: $7E91, $7EAA, $7EB9, $7FF8) and bit 0
(received byte: $70B0), and requires bit 3 clear ($7FC9). Status reads
$0002, "ready, data discarded": a tape save (WSMLB, BASIC) streams its
bytes into nothing and finishes; a tape load waits for data that never
comes, like a real ECS with no tape. $00E1-$00E3 read 0; writes are
dropped. Upper byte 0 (the ROM compares the data register with $00AA,
$7EE7, so the ECS cannot read $FFxx there). MAME maps nothing there (reads
0, intv.cpp:364): a save waits for ever on MAME's "Press RETURN".

MAME mode (mame=True, comparisons with MAME's intvecs only): MAME's ECS
as it is (ecs.cpp, ecs_ctrl.cpp): pages decode only $xA50 / $xA51; $2000
and $7000 are the ECS's always ($FFFF when paged out), $E000 the ECS ROM
or the cartridge; PSG #2 an AY-3-8914 (two envelope-select bits); the
keyboard rows ANDed (no ghosting, no masking; port A reads $FF); the
UART unmapped (reads 0).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import psg as psgm  # noqa: E402

OFF, ON, ATTACHED = 0, 1, 2
MODE_NAMES = {OFF: "off", ON: "on", ATTACHED: "attached"}
# page latches ($2, $7, $E) at machine reset, per mode
RESET_PAGES = {OFF: (0, 0, 0), ON: (0, 0, 0), ATTACHED: (0, 0xF, 0)}
ROM_RANGES = (0x2, 0x7, 0xE)
ROM_PAGE = {0x2: 1, 0x7: 0, 0xE: 1}         # the page each ROM answers on
UART_STATUS = 0x0002
OVERRIDE_AUTO, OVERRIDE_ON, OVERRIDE_OFF = 0, 1, 2


def header_direct(w500c):
    """The ECS boot starts the cartridge straight (no ECS title): the word at
    $500C, byte-swapped, AND $FD equals 1 (REPORT 2 step 5)."""
    if w500c is None:
        return False
    return (((w500c >> 8) | (w500c << 8)) & 0xFD) == 1


def auto_mode(flags_ecs, w4800, maps4000, nocart=False, w500c=None, ecs_off=False):
    """DESIGN 20's Auto rule (refined: see the module docstring). flags_ecs:
    the CRC table's (or the CFG's / .rom tag's) ECS flag; w4800: the word a
    ROM read of $4800 gives at reset paging (None: not answered, or RAM);
    maps4000: the cartridge maps $4000-$47FF on page 0; nocart: no cartridge
    image (0 words); w500c: the word at $500C (None: not answered); ecs_off:
    the loader's ECS_OFF flag (the "ECS incompatible" tag or a hard conflict)."""
    if flags_ecs or nocart:
        return ON
    if w4800 is not None and w4800 <= 0x3FF and header_direct(w500c):
        return ON
    if maps4000 or ecs_off:
        return OFF
    return ATTACHED


def mode_for(override, auto):
    return {OVERRIDE_AUTO: auto, OVERRIDE_ON: ON, OVERRIDE_OFF: OFF}[override]


def cart_inputs(cart):
    """(flags_ecs, w4800, maps4000, nocart, w500c, ecs_off) of a cartfmt.MapCart as
    the loader and the reset probe see them (intv_cart: the map table's
    page-0 entries of $4000-$47FF; reads of $4800 and $500C, $4800 only from
    a ROM block)."""
    import cartfmt
    if cart is None or cart.ld.words == 0:
        return False, None, False, True, None, False
    ld = cart.ld
    maps = any(ld.table[(4 << 8) | b] & (cartfmt.E_R | cartfmt.E_W | cartfmt.E_B) for b in range(8))
    saved = list(cart.sel)
    cart.sel = [0] * 16
    hit, bits, _ = cart.attr(0x4800)
    w = cart.read(0x4800) if hit and not bits & 2 else None
    h = cart.read(0x500C)
    cart.sel = saved
    return bool(ld.flags & cartfmt.FLAG_ECS), w, maps, False, h, bool(ld.flags & cartfmt.FLAG_ECS_OFF)


def load_rom(path):
    """ECS.bin: 24,576 bytes, big-endian words ($2000, $7000, $E000 ROMs in
    turn; MAME ecs.cpp ROM_LOAD16_WORD_SWAP of ecs_rom.20/.70/.e0)."""
    b = open(path, "rb").read()
    if len(b) != 24576:
        raise ValueError("ECS ROM: %d bytes, want 24576" % len(b))
    return [b[i] << 8 | b[i + 1] for i in range(0, len(b), 2)]


# ---------------------------------------------------------------- matrix
def matrix_read(keys, synth, dir_a, dir_b, lat_a, lat_b):
    """(port A, port B) bytes read from the keyboard: keys = pressed
    switches (bit 8 row + col), dir_a / dir_b = the port is an output,
    lat_a / lat_b their latches."""
    drive = {}                                  # line -> driven value; rows 0-7, columns 8-15
    for i in range(8):
        if dir_a:
            drive[i] = lat_a >> i & 1
        if dir_b:
            drive[8 + i] = lat_b >> i & 1
    if synth:
        a = b = 0
        for i in range(8):
            a |= drive.get(i, 1) << i           # a row: its drive or the pull-up
            v = drive.get(8 + i, 1)
            if v:                               # an undriven or high column: a key on a low row pulls it
                for r in range(8):
                    if keys >> (8 * r + i) & 1 and drive.get(r, 1) == 0:
                        v = 0
            b |= v << i
        return a, b
    parent = list(range(16))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for r in range(8):
        for c in range(8):
            if keys >> (8 * r + c) & 1:
                parent[find(r)] = find(8 + c)
    val = {}
    for g in set(find(x) for x in range(16)):
        ds = [drive[x] for x in range(16) if find(x) == g and x in drive]
        val[g] = 1 if (1 in ds or not ds) else 0
    a = sum(val[find(i)] << i for i in range(8))
    b = sum(val[find(8 + i)] << i for i in range(8))
    return a, b


def matrix_read_mame(keys, dir_a, lat_a):
    """MAME ecs_ctrl.cpp intvecs_keybd_device / intvecs_synth_device: port B
    = AND of the rows whose port-A bit is driven 0 (port A an output);
    port A reads $FF."""
    v = 0xFF
    if dir_a:
        for r in range(7):                      # MAME scans rows 0-6
            if not lat_a >> r & 1:
                v &= ~(keys >> (8 * r)) & 0xFF
    return 0xFF, v


# ---------------------------------------------------------------- device
class Ecs:
    def __init__(self, rom=None, mode=ON, mame=False):
        self.rom = rom                          # 12,288 words or None (no ECS ROM slot)
        self.mode = mode
        self.mame = mame
        self.ram = [0] * 2048
        self.psg = psgm.ClockedPsg("8914" if mame else "8917")
        self.keys = 0                           # pressed switches now (bit 8 row + col)
        self.synth = False                      # the synthesizer is plugged in
        self.keys_at = None                     # f(frame) -> keys (scripted presses)
        self.reset()

    def reset(self):
        """Machine reset: page latches to the mode's values, PSG #2 and its
        port latches cleared (AY-3-8910 reset: every register 0). RAM keeps
        its contents."""
        self.page = dict(zip(ROM_RANGES, RESET_PAGES[self.mode]))
        self.psg.reset()
        self.lat = [0, 0]                       # port A ($FE), port B ($FF) latches

    @property
    def on(self):
        return self.mode != OFF

    # -- decode ------------------------------------------------------------
    def rom_word(self, a):
        """The ECS ROM's word at a if it answers there now, else None."""
        r = a >> 12
        if self.rom is None or r not in ROM_PAGE or self.page[r] != ROM_PAGE[r]:
            return None
        return self.rom[{0x2: 0, 0x7: 4096, 0xE: 8192}[r] + (a & 0xFFF)]

    def owns(self, a):
        """The ECS answers a (the cartridge does not)."""
        if not self.on:
            return False
        if 0x00E0 <= a <= 0x00E3:
            return not self.mame
        if 0x00F0 <= a <= 0x00FF or 0x4000 <= a <= 0x47FF:
            return True
        if self.mame and (a >> 12) in (0x2, 0x7):
            return True                         # MAME: never the cartridge there
        return self.rom_word(a) is not None

    def ports(self, frame=None):
        keys = self.keys if self.keys_at is None or frame is None else self.keys_at(frame)
        en = self.psg.regs[psgm.R_ENABLE]
        dir_a, dir_b = en >> 6 & 1, en >> 7 & 1
        if self.mame:
            return matrix_read_mame(keys, dir_a, self.lat[0])
        return matrix_read(keys, self.synth, dir_a, dir_b, self.lat[0], self.lat[1])

    def read(self, a, cycle, frame=None):
        """The word the ECS drives at a (owns(a) must be true)."""
        if 0x00E0 <= a <= 0x00E3:
            return UART_STATUS if a == 0x00E0 else 0
        if 0x00F0 <= a <= 0x00FF:
            n = a & 0xF
            if n >= 14:
                return 0xFF00 | self.ports(frame)[n - 14]
            self.psg.advance(cycle)
            return 0xFF00 | self.psg.regs[n]
        if 0x4000 <= a <= 0x47FF:
            return self.ram[a & 0x7FF]
        w = self.rom_word(a)
        return 0xFFFF if w is None else w       # MAME mode: $2000 / $7000 paged out

    def write(self, a, v, cycle):
        """Every CPU write (the ECS decodes its own)."""
        if not self.on:
            return
        v &= 0xFFFF
        if 0x00F0 <= a <= 0x00FF:
            n = a & 0xF
            if n >= 14:
                self.lat[n - 14] = v & 0xFF
            else:
                self.psg.bus_write(n, v & 0xFF, cycle)
        elif 0x4000 <= a <= 0x47FF:
            self.ram[a & 0x7FF] = v & 0xFF
        r = a >> 12
        if r in ROM_RANGES and a & 0xFFF == 0xFFF and v & 0xFFF0 == (r << 12 | 0x0A50):
            if not self.mame or v & 0xF <= 1:
                self.page[r] = v & 0xF

    # -- state (intv_ecs.sv's words) ---------------------------------------
    def state(self):
        """[ECS module word 0]: [3:0] page $2, [7:4] page $7, [11:8] page
        $E, [19:12] port A latch, [27:20] port B latch, [29:28] mode."""
        return [self.page[2] | self.page[7] << 4 | self.page[0xE] << 8 | self.lat[0] << 12 |
                self.lat[1] << 20 | self.mode << 28]

    def ram_words(self):
        """The ECS RAM as the state port holds it: 512 words of 4 bytes
        (byte k of word i = cell 4 i + k, bits 8 k + 7 .. 8 k)."""
        return [sum(self.ram[4 * i + k] << (8 * k) for k in range(4)) for i in range(512)]


# ---------------------------------------------------------------- self-test
# matrix positions (row = port A bit, column = port B bit; MAME ecs_ctrl.cpp ROW.n)
KEYPOS = {
    "RTN": (0, 6), "0": (0, 5), "ESC": (0, 4), "P": (0, 3), ";": (0, 2), ".": (0, 1), "LEFT": (0, 0),
    "L": (1, 7), "O": (1, 6), "8": (1, 5), "9": (1, 4), "I": (1, 3), "K": (1, 2), "M": (1, 1), ",": (1, 0),
    "J": (2, 7), "U": (2, 6), "6": (2, 5), "7": (2, 4), "Y": (2, 3), "H": (2, 2), "B": (2, 1), "N": (2, 0),
    "G": (3, 7), "T": (3, 6), "4": (3, 5), "5": (3, 4), "R": (3, 3), "F": (3, 2), "C": (3, 1), "V": (3, 0),
    "D": (4, 7), "E": (4, 6), "2": (4, 5), "3": (4, 4), "W": (4, 3), "S": (4, 2), "Z": (4, 1), "X": (4, 0),
    "A": (5, 7), "CTL": (5, 6), "RIGHT": (5, 5), "1": (5, 4), "Q": (5, 3), "UP": (5, 2), "DOWN": (5, 1),
    "SPACE": (5, 0), "SHIFT": (6, 7),
}


# characters typed with SHIFT (MAME ecs_ctrl.cpp PORT_CHAR pairs)
SHIFTED = {"=": "1", '"': "2", "#": "3", "$": "4", "+": "5", "-": "6", "/": "7", "*": "8", "(": "9",
           ")": "0", ":": ";", "%": "LEFT", "'": "RIGHT", "^": "UP", "?": "DOWN"}


def type_presses(start, text, hold=6, gap=6):
    """parse_presses text (tools/intv_system.py) that types `text` on the
    ECS keyboard from frame notifier `start`: each key held `hold` frames,
    `gap` frames apart; "\n" is RTN, "\x1b" ESC. -> (text, next frame)."""
    out, f = [], start
    for ch in text:
        if ch == "\n":
            keys = ["RTN"]
        elif ch == "\x1b":
            keys = ["ESC"]
        elif ch == " ":
            keys = ["SPACE"]
        elif ch in SHIFTED:
            keys = ["SHIFT", SHIFTED[ch]]
        else:
            keys = [ch.upper()]
        out.append("%d-%d:ecs:%s" % (f, f + hold, "+".join(keys)))
        f += hold + gap
    return ",".join(out), f


def keybits(*names):
    v = 0
    for n in names:
        r, c = KEYPOS[n]
        v |= 1 << (8 * r + c)
    return v


def rom_scan(keys, synth=False):
    """The ECS ROM's raw scan ($7293): port A out, port B in; for rows 6..0
    write ~(1 << row) to $FE and read $FF. -> {row: columns read 0}."""
    out = {}
    for r in range(7):
        _, b = matrix_read(keys, synth, 1, 0, ~(1 << r) & 0xFF, 0)
        out[r] = ~b & 0xFF
    return out


def selftest():
    errs = []

    def chk(cond, what):
        if not cond:
            errs.append(what)
    # one key: seen at its row and column, both scan directions
    for name, (r, c) in KEYPOS.items():
        s = rom_scan(keybits(name))
        chk(s == {i: (1 << c if i == r else 0) for i in range(7)}, "single key %s: %s" % (name, s))
        _, b = matrix_read_mame(keybits(name), 1, ~(1 << r) & 0xFF)
        chk(b == ~(1 << c) & 0xFF, "MAME single key %s" % name)
        # transposed: drive column c low, read rows
        a, _ = matrix_read(keybits(name), False, 0, 1, 0, ~(1 << c) & 0xFF)
        chk(a == ~(1 << r) & 0xFF, "transposed key %s" % name)
    # two keys in one column vanish from the row scan (1 beats 0), show transposed
    s = rom_scan(keybits("LEFT", ","))
    chk(all(v == 0 for v in s.values()), "LEFT + , masked: %s" % s)
    a, _ = matrix_read(keybits("LEFT", ","), False, 0, 1, 0, 0xFE)
    chk(a == 0xFC, "LEFT + , transposed: %02X" % a)
    # Shift cannot upper-case L, J, G, D, A on a row scan (they share its column)
    for k in "LJGDA":
        s = rom_scan(keybits("SHIFT", k))
        chk(all(v == 0 for v in s.values()), "SHIFT + %s masked" % k)
    s = rom_scan(keybits("SHIFT", "K"))
    chk(s[6] == 0x80 and s[1] == 0x04, "SHIFT + K: %s" % s)
    # W, Q, 1 (three corners of rows 4/5, columns 3/4): masked on the row scan
    s = rom_scan(keybits("W", "Q", "1"))
    chk(all(v == 0 for v in s.values()), "W Q 1 on the ROM's scan: %s" % s)
    # ...and ghost 3 when only one row is driven low and the other rows float
    # (port A output is all-or-nothing, so model it with port A as input and
    # one column driven: the transposed single-line case shows the ghost path)
    a, _ = matrix_read(keybits("W", "Q", "1"), False, 0, 1, 0, ~(1 << 3) & 0xFF)
    chk(a == 0xFF, "W Q 1 transposed column 3 (column 4 driven 1): masked %02X" % a)
    # all rows driven low at once (an "any key" scan): every pressed column reads 0
    _, b = matrix_read(keybits("W", "Q", "1"), False, 1, 0, 0x00, 0)
    chk(b == ~0x18 & 0xFF, "any-key scan: %02X" % b)
    # nothing driven: everything reads 1
    chk(matrix_read(keybits("W", "Q", "1"), False, 0, 0, 0, 0) == (0xFF, 0xFF), "undriven")
    # synthesizer (diodes): a chord in one column is not masked; no transposed path
    chord = (1 << 0) | (1 << 8) | (1 << 9)       # C2, Ab2, A2: rows 0, 1, 1
    for r in range(7):
        _, b = matrix_read(chord, True, 1, 0, ~(1 << r) & 0xFF, 0)
        want = ~(chord >> (8 * r)) & 0xFF
        chk(b == want, "synth row %d: %02X want %02X" % (r, b, want))
    a, _ = matrix_read(chord, True, 0, 1, 0, 0xFE)
    chk(a == 0xFF, "synth transposed: %02X" % a)
    # pages: ON = $7000 on page 0; ATTACHED = all out; IntyBASIC's $F out
    rom = list(range(12288))
    e = Ecs(rom, ON)
    chk(e.rom_word(0x7000) == 4096 and e.rom_word(0x2000) is None and e.rom_word(0xE000) is None, "ON reset")
    e.write(0x2FFF, 0x2A51, 0)
    e.write(0xEFFF, 0xEA51, 0)
    chk(e.rom_word(0x2001) == 1 and e.rom_word(0xE002) == 8194, "pages 1")
    e.write(0x7FFF, 0x7A5F, 0)
    chk(e.rom_word(0x7000) is None, "$7A5F pages out")
    e = Ecs(rom, ATTACHED)
    chk(all(e.rom_word(r << 12) is None for r in ROM_RANGES), "ATTACHED reset")
    chk(e.owns(0x4040) and e.owns(0x00F0) and e.owns(0x00E0) and not e.owns(0x7000), "ATTACHED owns")
    e.write(0x4040, 0x1255, 0)
    chk(e.read(0x4040, 0) == 0x55, "RAM 8-bit")
    e = Ecs(rom, OFF)
    chk(not any(e.owns(a) for a in (0x00E0, 0x00F0, 0x4040, 0x7000)), "OFF")
    m = Ecs(rom, ON, mame=True)
    m.write(0x7FFF, 0x7A5F, 0)
    chk(m.rom_word(0x7000) == 4096, "MAME ignores $7A5F")
    # Auto rule
    chk(auto_mode(True, None, True) == ON and auto_mode(False, 0x0004, False, w500c=0x03C0) == ON and
        auto_mode(False, 0x0004, False, w500c=0x00C0) == ATTACHED and
        auto_mode(False, 0x0004, False) == ATTACHED and
        auto_mode(False, 0x0400, True) == OFF and auto_mode(False, None, False) == ATTACHED and
        auto_mode(False, 0x0400, False) == ATTACHED and auto_mode(False, None, True, True) == ON and
        auto_mode(False, None, False, ecs_off=True) == OFF and
        auto_mode(False, 0x0004, False, w500c=0x03C0, ecs_off=True) == ON and
        auto_mode(True, None, False, ecs_off=True) == ON, "auto_mode")
    # PSG #2 envelope select: one bit
    p = psgm.Psg("8917")
    p.write(psgm.R_ENABLE, 0x3F)
    p.write(psgm.R_SHAPE, 0x0D)
    p.write(psgm.R_EFINE, 1)
    for _ in range(40):
        p.tick()
    chk([p.write(psgm.R_AVOL, v) or p.levels()[0] for v in (0x09, 0x19, 0x29, 0x39)] == [9, 15, 9, 15],
        "8917 volume select")
    return errs


def main():
    errs = selftest()
    for e in errs:
        print("FAIL", e)
    print("ECS_SELFTEST %s" % ("pass" if not errs else "FAIL (%d)" % len(errs)))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
