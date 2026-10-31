#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""On-screen keypad and per-game profiles (build step 13; the owner's decisions of 2026-10-31,
docs/KEYPAD_NOTES.md). src/fpga/core/intv_osk.sv and intv_osk_draw.sv implement the same; the
bench sim/tb/tb_osk.py compares them with this model.

  python3 -I tools/osk.py                 self-check
  python3 -I tools/osk.py gen [--check]   the RTL's tables (src/fpga/core/tables/osk_*.hex)

The keypad (one per player; player 1 = cont1, player 2 = cont2, controller types 1-3):

- Select opens it; Select or B closes it. The game keeps running.
- While it is open the D-pad moves a cursor over the 3 x 4 grid (1 2 3 / 4 5 6 / 7 8 9 /
  Clear 0 Enter), wrapping at the edges; a press of A presses the key under the cursor, held
  until A is let go (the key stays the one pressed even if the cursor moves). All of that
  controller's buttons are taken by the keypad while it is open (the analog sticks are not);
  buttons still held when it closes stay masked until they are let go, so the B that closes it
  does not also press the lower-left side action.
- Everything is decided once a frame (`step`, at the video frame's start in the RTL), from the
  controller word of that moment.
- It is drawn over the playfield, mostly transparent: cell outlines, glyphs with a dark shadow,
  and above the grid the cursor key's label from the game's profile. Player 1's grid is at the
  bottom left, player 2's at the bottom right (its label one row higher while player 1's keypad
  is open too, as the two labels could overlap). The cursor cell is yellow; while its key is held
  the cell is filled yellow and the glyph dark.

Profiles (PROFILES): by the cartridge's CRC-32, the keypad mode Auto chooses (Core Settings
Keypad Mode 3, the default from 0.0.22; 0-2 are the fixed modes), the side actions of A / B / X in
Auto's Layer mode, and the keypad's labels (function facts from the game's overlay, our own
words, at most 14 characters). Without a profile Auto is Layer with the usual side actions.

The font is our own: 5 x 7 glyphs in 8 x 8 cells, each row drawn on two lines (as the STIC's
card pixels).
"""
import sys

# ---------------------------------------------------------------------- font (our own glyphs)
CHARS = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ./:-&'!?()"
_G = {
    ' ': [".....", ".....", ".....", ".....", ".....", ".....", "....."],
    '0': [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
    '1': ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    '2': [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
    '3': ["#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."],
    '4': ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    '5': ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
    '6': ["..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."],
    '7': ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    '8': [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    '9': [".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."],
    'A': [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    'B': ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    'C': [".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."],
    'D': ["###..", "#..#.", "#...#", "#...#", "#...#", "#..#.", "###.."],
    'E': ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    'F': ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
    'G': [".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"],
    'H': ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    'I': [".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."],
    'J': ["..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."],
    'K': ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    'L': ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    'M': ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
    'N': ["#...#", "#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#"],
    'O': [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    'P': ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    'Q': [".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"],
    'R': ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    'S': [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    'T': ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    'U': ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    'V': ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    'W': ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."],
    'X': ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
    'Y': ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    'Z': ["#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"],
    '.': [".....", ".....", ".....", ".....", ".....", ".##..", ".##.."],
    '/': [".....", "....#", "...#.", "..#..", ".#...", "#....", "....."],
    ':': [".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."],
    '-': [".....", ".....", ".....", "#####", ".....", ".....", "....."],
    '&': [".##..", "#..#.", "#.#..", ".#...", "#.#.#", "#..#.", ".##.#"],
    "'": ["..#..", "..#..", ".#...", ".....", ".....", ".....", "....."],
    '!': ["..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."],
    '?': [".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."],
    '(': ["...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."],
    ')': [".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."],
}
assert set(_G) == set(CHARS) and len(CHARS) <= 64


def _rows(c):
    """The 8 rows of a glyph, bit 7 = the leftmost pixel; the 5 x 7 glyph at columns 1-5, rows
    0-6."""
    return [sum(1 << (6 - i) for i, p in enumerate(r) if p == '#') for r in _G[c]] + [0]


FONT = [_rows(c) for c in CHARS] + [[0] * 8] * (64 - len(CHARS))


def ccode(c):
    return CHARS.index(c)


# ---------------------------------------------------------------------- the grid
KEYS = [1, 2, 3, 4, 5, 6, 7, 8, 9, "C", 0, "E"]          # cell index -> hand-controller key
GLYPH = "123456789C0E"
NCELL = 12
CW, CH = 12, 20                     # a cell: 12 pixels by 20 lines (8 x 16 glyph at +2, +2)
GW, GH = 3 * CW + 1, 4 * CH + 2     # the grid with its outlines: 37 x 82
PF_W, PF_H = 160, 192
GX = (2, PF_W - 2 - GW)             # player 1 bottom left, player 2 bottom right
GY = PF_H - 2 - GH
LY = GY - CH + 2                    # the label's first line (16 lines, ends 4 above the grid)
LABEL_MAX = 14
NONE, WHITE, DARK, YELLOW = 0, 1, 2, 3

# Pocket controller bits (tools/intv_input.py)
UP, DOWN, LEFT, RIGHT, A, B, X, Y, L1, R1, L2, R2, L3, R3, SELECT, START = range(16)


class Player:
    """One player's keypad (state changes only in step(), once a frame)."""

    def __init__(self):
        self.open = 0
        self.cur = 4                # the cursor's cell (key 5)
        self.prev = 0               # the buttons at the last step
        self.held = 0               # the pressed cell + 1 (0: none)
        self.mask = 0               # buttons masked after a close until let go

    def step(self, key):
        """The controller word at this frame's start."""
        if key >> 28 not in (1, 2, 3):
            self.open = self.held = self.mask = self.prev = 0
            return
        b = key & 0xFFFF
        rise = b & ~self.prev
        self.mask &= b
        if not self.open:
            if rise >> SELECT & 1:
                self.open = 1
                self.held = 0
        elif rise >> SELECT & 1 or rise >> B & 1:
            self.open = 0
            self.held = 0
            self.mask = b
        else:
            r, c = divmod(self.cur, 3)
            if rise >> UP & 1:
                r = (r + 3) % 4
            if rise >> DOWN & 1:
                r = (r + 1) % 4
            if rise >> LEFT & 1:
                c = (c + 2) % 3
            if rise >> RIGHT & 1:
                c = (c + 1) % 3
            if not b >> A & 1:
                self.held = 0
            elif rise >> A & 1:
                self.held = self.cur + 1    # the cell under the cursor before this frame's move
            self.cur = 3 * r + c
        self.prev = b

    def buttons_mask(self):
        """The buttons the game does not see (all 16 while open)."""
        return 0xFFFF if self.open else self.mask

    def key(self):
        """The hand-controller key the keypad presses, or None."""
        return KEYS[self.held - 1] if self.open and self.held else None


# ---------------------------------------------------------------------- profiles
# crc: the cartridge's CRC-32 (the loader's, as tools/gen_crc_table.py); mode: Auto's keypad
# mode (0 Layer, 1 Face-button ring, 2 Right stick); sides: the side actions of A, B, X in
# Auto's Layer mode ("lr" lower right, "ll" lower left, "top"); labels: key -> text. From the
# overlays' function facts (the owner's scans, research/test-assets/overlay_index.csv), in our
# own words.
SIDES = ("lr", "ll", "top")
PROFILES = [
    dict(name="B-17 Bomber", crcs=[0x8AD19AB3], mode=0, sides=("top", "ll", "lr"),
         labels={1: "PILOT", 2: "12:00 GUN", 3: "BOMB BAY", 4: "GAUGES", 6: "PREVIEW",
                 7: "9:00 GUN", 9: "3:00 GUN", "C": "MAP", 0: "6:00 GUN", "E": "SCORE"}),
    dict(name="Space Spartans", crcs=[0x3784DC52], mode=0, sides=SIDES,
         labels={1: "BATTLE COMP.", 2: "IMPULSE DRIVE", 3: "SHIELDS", 4: "TRACKING COMP.",
                 5: "HYPER DRIVE", 6: "ALL SYSTEMS", 7: "ON/OFF", 8: "STATUS",
                 9: "REPAIR ON/OFF", "C": "ENERGY LEVEL", 0: "NO. OF ALIENS", "E": "CHANGE VIEW"}),
    dict(name="TRON Deadly Discs", crcs=[0xCA447BBD], mode=1, sides=SIDES,
         labels={1: "THROW UP-LEFT", 2: "THROW UP", 3: "THROW UP-RIGHT", 4: "THROW LEFT",
                 5: "BLOCK", 6: "THROW RIGHT", 7: "THROW DN-LEFT", 8: "THROW DOWN",
                 9: "THROW DN-RIGHT"}),
    dict(name="AD&D Cloudy Mountain", crcs=[0xF8B1F2B7, 0x11C3BCFA], mode=0, sides=SIDES,
         labels={1: "SHOOT UP-LEFT", 2: "SHOOT UP", 3: "SHOOT UP-RIGHT", 4: "SHOOT LEFT",
                 6: "SHOOT RIGHT", 7: "SHOOT DN-LEFT", 8: "SHOOT DOWN", 9: "SHOOT DN-RIGHT",
                 "C": "PICK UP", 0: "COUNT ARROWS", "E": "EXIT"}),
]
MAX_PROFILES = 64                   # the CRC table's entries (osk_crc.hex)
MAX_LABELS = 64                     # the label pool (osk_label.hex: 16 bytes each, 0 = none)


def profile_for(crc):
    for p in PROFILES:
        if crc in p["crcs"]:
            return p
    return None


def label_pool():
    """The distinct labels, index 1 up (0: no label)."""
    pool = []
    for p in PROFILES:
        for k in KEYS:
            t = p["labels"].get(k)
            if t and t not in pool:
                pool.append(t)
    return pool


def label(p, cell):
    return p["labels"].get(KEYS[cell], "") if p else ""


# ---------------------------------------------------------------------- drawing
def draw(players, prof):
    """The overlay over the playfield: {(x, y): colour} for x 0-159, y 0-191 (lines), colours
    WHITE, DARK, YELLOW (absent: transparent). players: the two Player objects."""
    px = {}

    def glyph(x0, y0, ch, colour):
        rows = FONT[ccode(ch)]
        for y in range(16):
            for x in range(8):
                on = rows[y >> 1] >> (7 - x) & 1
                # the shadow: the glyph one pixel left and one row (two lines) up
                sh = x > 0 and y >= 2 and rows[(y >> 1) - 1] >> (8 - x) & 1
                if on:
                    px[(x0 + x, y0 + y)] = colour
                elif sh and colour != DARK:
                    px[(x0 + x, y0 + y)] = DARK

    for n, pl in enumerate(players):
        if not pl.open:
            continue
        gx = GX[n]
        # outlines: white, the cursor cell's yellow over them
        for y in range(GH):
            for x in range(GW):
                if x % CW == 0 or y % CH < 2:
                    px[(gx + x, GY + y)] = WHITE
        r, c = divmod(pl.cur, 3)
        for y in range(CH + 2):
            for x in range(CW + 1):
                if x in (0, CW) or y < 2 or y >= CH:
                    px[(gx + c * CW + x, GY + r * CH + y)] = YELLOW
        for cell in range(NCELL):
            r, c = divmod(cell, 3)
            x0, y0 = gx + c * CW, GY + r * CH
            pressed = pl.held == cell + 1
            if pressed:
                for y in range(2, CH):
                    for x in range(1, CW):
                        px[(x0 + x, y0 + y)] = YELLOW
            glyph(x0 + 2, y0 + 2, GLYPH[cell], DARK if pressed else YELLOW if cell == pl.cur else WHITE)
        t = label(prof, pl.cur)
        lx = gx if n == 0 else gx + GW - 8 * len(t)
        ly = LY - CH if n == 1 and players[0].open else LY      # above player 1's when both are open
        for i, ch in enumerate(t):
            glyph(lx + 8 * i, ly, ch, WHITE)
    return px


# ---------------------------------------------------------------------- the RTL's tables
def crc_hex():
    """osk_crc.hex: 64 entries of 40 bits: valid, CRC-32, profile index (7 bits)."""
    ent = []
    for i, p in enumerate(PROFILES):
        for c in p["crcs"]:
            ent.append((1 << 39) | (c << 7) | i)
    assert len(ent) <= MAX_PROFILES
    return ent + [0] * (MAX_PROFILES - len(ent))


def prof_hex():
    """osk_prof.hex: 64 records of 80 bits: mode (2), sides (A, B, X: 2 bits each, 0 lr, 1 ll,
    2 top), 12 label indices (6 bits each, cell 0 at the low end; 0 = none)."""
    pool = label_pool()
    assert len(pool) < MAX_LABELS
    recs = []
    for p in PROFILES:
        v = 0
        for cell in range(NCELL):
            t = label(p, cell)
            v |= (pool.index(t) + 1 if t else 0) << (6 * cell)
        sides = sum(SIDES.index(s) << (2 * i) for i, s in enumerate(p["sides"]))
        recs.append((p["mode"] << 78) | (sides << 72) | v)
    return recs + [0] * (MAX_PROFILES - len(recs))


def label_hex():
    """osk_label.hex: 64 labels x 16 bytes (byte 0: length, then the character codes)."""
    pool = label_pool()
    out = [0] * (16 * MAX_LABELS)
    for i, t in enumerate(pool):
        assert 0 < len(t) <= LABEL_MAX, t
        b = 16 * (i + 1)
        out[b] = len(t)
        for j, ch in enumerate(t):
            out[b + 1 + j] = ccode(ch)
    return out


def llen_hex():
    """osk_llen.hex: the 64 labels' lengths (the drawing places player 2's label by it)."""
    lab = label_hex()
    return [lab[16 * i] for i in range(MAX_LABELS)]


def font_hex():
    """osk_font.hex: 64 glyphs x 8 rows."""
    return [r for g in FONT for r in g]


def tables():
    return {"osk_crc.hex": ["%010x" % e for e in crc_hex()],
            "osk_prof.hex": ["%020x" % e for e in prof_hex()],
            "osk_label.hex": ["%02x" % e for e in label_hex()],
            "osk_llen.hex": ["%x" % e for e in llen_hex()],
            "osk_font.hex": ["%02x" % e for e in font_hex()]}


def gen(check=False):
    import os
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "fpga", "core", "tables")
    bad = 0
    for name, lines in tables().items():
        p = os.path.join(d, name)
        text = "\n".join(lines) + "\n"
        if check:
            if not os.path.exists(p) or open(p).read() != text:
                print("OSK_TABLES %s out of date" % name)
                bad = 1
        else:
            open(p, "w").write(text)
    if check and not bad:
        print("OSK_TABLES up to date")
    return bad


# ---------------------------------------------------------------------- self-check
def self_check():
    fails = []

    def chk(c, what):
        if not c:
            fails.append(what)

    for p in PROFILES:
        for t in p["labels"].values():
            chk(0 < len(t) <= LABEL_MAX and all(ch in CHARS for ch in t), "label %r" % t)
        chk(p["mode"] in (0, 1, 2) and all(s in SIDES for s in p["sides"]), p["name"])
    crcs = [c for p in PROFILES for c in p["crcs"]]
    chk(len(crcs) == len(set(crcs)), "a CRC in two profiles")
    # the state machine
    T = 1 << 28
    pl = Player()
    seq = [(0, None, 0), (1 << SELECT, None, 1), (0, None, 1), (1 << RIGHT, None, 1), (0, None, 1),
           (1 << A, 6, 1), (1 << A | 1 << DOWN, 6, 1), (1 << A, 6, 1), (0, None, 1), (1 << A, 9, 1),
           (1 << B | 1 << A, None, 0), (1 << B, None, 0), (0, None, 0)]
    for i, (b, want, op) in enumerate(seq):
        pl.step(T | b)
        chk(pl.key() == want and pl.open == op, "step %d: key %r open %d" % (i, pl.key(), pl.open))
    chk(pl.buttons_mask() == 0, "mask cleared after release")
    pl.step(T | 1 << SELECT)
    pl.step(T | 1 << SELECT | 1 << B)
    chk(not pl.open and pl.buttons_mask() == (1 << SELECT | 1 << B), "close mask")
    pl.step(T | 1 << B)
    chk(pl.buttons_mask() == 1 << B, "mask follows release")
    for _ in range(4):
        pl.step(T | 1 << SELECT)
        pl.step(T)
    chk(not pl.open, "Select toggles")
    pl.step(T | 1 << SELECT)
    pl.step(0)
    chk(not pl.open, "a non-controller closes it")
    # drawing: the grid inside the playfield, the label's width
    ps = [Player(), Player()]
    for q in ps:
        q.step(T | 1 << SELECT)
    px = draw(ps, PROFILES[1])
    chk(all(0 <= x < PF_W and 0 <= y < PF_H for x, y in px), "drawn outside the playfield")
    chk(len(FONT) == 64 and all(r & 0x81 == 0 for g in FONT for r in g), "glyph columns 1-5 only")
    if fails:
        print("OSK_SELFTEST FAIL:", "; ".join(fails))
        return 1
    print("OSK_SELFTEST pass (%d profiles, %d CRCs, %d labels)" % (len(PROFILES), len(crcs), len(label_pool())))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "gen":
        sys.exit(gen("--check" in sys.argv))
    sys.exit(self_check())
