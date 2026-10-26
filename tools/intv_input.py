#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Input model (DESIGN.md 7, build step 6): the Pocket's controllers and
keyboard as two Intellivision hand controllers, the bytes the AY-3-8914's
ports read. src/fpga/core/intv_input.sv implements the same mapping; the
bench sim/tb/tb_input.py compares the two.

  python3 -I tools/intv_input.py        self-check (code tables against
                                        MAME's, the analog disc against
                                        MAME's analog grid)

Two layers:

1. virtual(): one Pocket controller (cont_key, cont_joy) in a keypad mode to
   one virtual hand controller, given as the two input ports of MAME's
   hand-controller device (devices/bus/intv_ctrl/handctrl.cpp:19-54):
   KEYPAD (bit 15 = key 1 ... bit 7 = key 9, 6 Clear, 5 key 0, 4 Enter,
   3 top side, 2 lower left, 1 lower right) and DISC_DG (bit 15 = N, then
   clockwise, bit 0 = N by NW). Several inputs set several bits.
2. code(): the virtual controller to the byte on the port, with this
   core's table (the codes of DESIGN.md 7.1, service manual and wiki: the
   lines each input pulls low) ORed together and inverted, as the
   hardware's wired-OR of active-low lines does. code_mame() is MAME's
   read_ctrl() for the digital disc (handctrl.cpp:123-168), transcribed
   with its tables, and must give the same byte for every input.

The mapping (the owner's input notes, "IN" in DESIGN.md, and DESIGN.md 7.2):

- Player 1 = cont1 (the Pocket's own buttons, or the first docked
  controller), player 2 = cont2. A slot is used only when its type
  (cont_key[31:28]) is 1 (Pocket), 2 (docked digital) or 3 (docked
  analog); the sticks only on type 3.
- Player 1's controller is the LEFT one ($01FF, PSG port B), player 2's the
  right one ($01FE, port A): many games read only the left controller.
  Swap Controllers exchanges them.
- The USB keyboard (cont3 type 4: six HID usage codes in cont3_joy[31:0]
  and cont3_trig[15:0]) is player 1's keypad: 1-9 and 0 on the number row
  and on the numpad, Backspace = Clear, Enter and numpad Enter = Enter.
  Everything ORs into player 1's controller, like a second set of fingers.
- Keypad mode Layer (0, default): D-pad = disc (8 directions); A = lower
  right, B = lower left, X = top side action. R held: D-pad = the keypad
  ring by position (up-left/up/up-right = 1/2/3, left/right = 4/6,
  down-left/down/down-right = 7/8/9; the disc is released), A/B/X = 1/2/3,
  Y = Enter. L held (and R not): A/B/X = 5/Clear/0. R beats L. Y alone,
  L+Y, Start and Select do nothing yet (Select is kept for the on-screen
  keypad, DESIGN.md 9 step 13).
- Keypad mode Face-button ring (1): D-pad = disc; the face buttons are a
  second D-pad on the ring, by position on the Pocket (X up = 2, B down = 8,
  Y left = 4, A right = 6; X+A = 3, X+Y = 1, B+A = 9, B+Y = 7); L = top side
  action, R = 5.
- Keypad mode Right stick (2): Layer, plus on a docked analog controller
  the right stick picks the ring key by direction (8 sectors) and its click
  (R3) is 5, the ring's centre (R3 = 5 is this core's addition).
- Opposite directions together (up+down, left+right, X+B, Y+A) cancel.
- Analog left stick (type 3, every mode): the disc in 16 directions, ORed
  with the D-pad's disc; inside a dead zone it does nothing.

Stick geometry: unsigned bytes, 0x80 the centre, x grows to the right and y
downwards (the APF bus-communication page gives the byte layout; the y
direction is the common convention, to be confirmed on a docked
controller). Sectors are decided with integer slopes, identical in the RTL:
with a = |dx|, b = |dy|, the angle from the vertical axis passes 11.25,
33.75, 56.25, 78.75 degrees where a*256 >= b * 51, 171, 383, 1287 (tan of
the angle times 256, rounded); for 8 sectors 22.5 and 67.5 degrees, 106 and
618. Dead zones: dx*dx + dy*dy < 40*40 (disc) and < 64*64 (ring keys).
"""
import sys

# Pocket controller bits (APF bus-communication page; core_top.v's list)
UP, DOWN, LEFT, RIGHT, A, B, X, Y, L1, R1, L2, R2, L3, R3, SELECT, START = range(16)

LAYER, FACE, RSTICK = 0, 1, 2
MODES = {LAYER: "Layer", FACE: "Face-button ring", RSTICK: "Right stick"}

# MAME handctrl.cpp:19-54, the bits of the two ports
KP_BIT = {1: 15, 2: 14, 3: 13, 4: 12, 5: 11, 6: 10, 7: 9, 8: 8, 9: 7,
          "C": 6, 0: 5, "E": 4, "top": 3, "ll": 2, "lr": 1}

# This core's codes: the lines each input pulls low (DESIGN.md 7.1; service
# manual via research/service-manual/REPORT.md "Hand controllers"; MAME
# handctrl.cpp:124-135, inverted)
KEY_CODE = {1: 0x81, 2: 0x41, 3: 0x21, 4: 0x82, 5: 0x42, 6: 0x22, 7: 0x84, 8: 0x44, 9: 0x24,
            "C": 0x88, 0: 0x48, "E": 0x28, "top": 0xA0, "ll": 0x60, "lr": 0xC0}
DISC_CODE = [0x04, 0x14, 0x16, 0x06, 0x02, 0x12, 0x13, 0x03,       # N, clockwise
             0x01, 0x11, 0x19, 0x09, 0x08, 0x18, 0x1C, 0x0C]

# MAME handctrl.cpp:125-144, quoted as data (the active-low bytes)
MAME_KEYPAD_TABLE = [0xff, 0x3f, 0x9f, 0x5f, 0xd7, 0xb7, 0x77, 0xdb,
                     0xbb, 0x7b, 0xdd, 0xbd, 0x7d, 0xde, 0xbe, 0x7e]
MAME_DISC_TABLE = [0xf3, 0xe3, 0xe7, 0xf7, 0xf6, 0xe6, 0xee, 0xfe,
                   0xfc, 0xec, 0xed, 0xfd, 0xf9, 0xe9, 0xeb, 0xfb]
MAME_DISCYX_TABLE = [[0xe3, 0xf3, 0xfb, 0xeb, 0xe9],
                     [0xe7, 0xe3, 0xfb, 0xe9, 0xf9],
                     [0xf7, 0xf7, 0xff, 0xfd, 0xfd],
                     [0xf6, 0xe6, 0xfe, 0xec, 0xed],
                     [0xe6, 0xee, 0xfe, 0xfc, 0xec]]

# USB HID usage codes (keyboard page 0x07)
HID = {0x1E: 1, 0x1F: 2, 0x20: 3, 0x21: 4, 0x22: 5, 0x23: 6, 0x24: 7, 0x25: 8, 0x26: 9, 0x27: 0,
       0x28: "E", 0x2A: "C", 0x58: "E",
       0x59: 1, 0x5A: 2, 0x5B: 3, 0x5C: 4, 0x5D: 5, 0x5E: 6, 0x5F: 7, 0x60: 8, 0x61: 9, 0x62: 0}

DZ_DISC, DZ_RING = 40, 64
SLOPES16 = (51, 171, 383, 1287)
SLOPES8 = (106, 618)

# ring key by (v, h): v = +1 up, -1 down; h = +1 right, -1 left
RING = {(1, -1): 1, (1, 0): 2, (1, 1): 3, (0, -1): 4, (0, 1): 6, (-1, -1): 7, (-1, 0): 8, (-1, 1): 9}
# disc direction (index into DISC_CODE) by (v, h), the D-pad's 8
DPAD_DIR = {(1, 0): 0, (1, 1): 2, (0, 1): 4, (-1, 1): 6, (-1, 0): 8, (-1, -1): 10, (0, -1): 12, (1, -1): 14}


def bit(v, n):
    return (v >> n) & 1


def vh(up, down, left, right):
    return up - down, right - left


def stick16(x, y):
    """16-direction disc index (0 = N, clockwise) of a stick, or None."""
    dx, dy = x - 128, y - 128
    if dx * dx + dy * dy < DZ_DISC * DZ_DISC:
        return None
    a, b = abs(dx), abs(dy)
    k = sum(a * 256 >= b * t for t in SLOPES16)
    if dx >= 0:
        return k if dy < 0 else 8 - k
    return 8 + k if dy >= 0 else (16 - k) % 16


def stick8(x, y):
    """(v, h) of a stick in 8 sectors, or None in the dead zone."""
    dx, dy = x - 128, y - 128
    if dx * dx + dy * dy < DZ_RING * DZ_RING:
        return None
    a, b = abs(dx), abs(dy)
    k = sum(a * 256 >= b * t for t in SLOPES8)
    v = 0 if k == 2 else (1 if dy < 0 else -1)
    h = 0 if k == 0 else (1 if dx >= 0 else -1)
    return v, h


class Hand:
    """A virtual hand controller: MAME's KEYPAD and DISC_DG port bits."""

    def __init__(self):
        self.kp = 0
        self.disc = 0

    def key(self, k):
        self.kp |= 1 << KP_BIT[k]

    def dir(self, i):
        self.disc |= 1 << (15 - i)

    def ring(self, v, h):
        if (v, h) in RING:
            self.key(RING[(v, h)])

    def dpad(self, v, h):
        if (v, h) in DPAD_DIR:
            self.dir(DPAD_DIR[(v, h)])


def virtual(key, joy, mode, hand=None):
    """One Pocket controller slot in keypad mode `mode` -> Hand."""
    h = hand or Hand()
    if key >> 28 not in (1, 2, 3):
        return h
    analog = key >> 28 == 3
    b = [bit(key, n) for n in range(16)]
    dp = vh(b[UP], b[DOWN], b[LEFT], b[RIGHT])
    if mode == FACE:
        h.dpad(*dp)
        h.ring(*vh(b[X], b[B], b[Y], b[A]))
        if b[L1]:
            h.key("top")
        if b[R1]:
            h.key(5)
    else:                                   # Layer; Right stick (modes 2, 3)
        if b[R1]:
            h.ring(*dp)
            for btn, k in ((A, 1), (B, 2), (X, 3), (Y, "E")):
                if b[btn]:
                    h.key(k)
        else:
            h.dpad(*dp)
            for btn, k, kl in ((A, "lr", 5), (B, "ll", "C"), (X, "top", 0)):
                if b[btn]:
                    h.key(kl if b[L1] else k)
        if mode == RSTICK and analog:
            r = stick8((joy >> 16) & 0xFF, (joy >> 24) & 0xFF)
            if r:
                h.ring(*r)
            if b[R3]:
                h.key(5)
    if analog:
        d = stick16(joy & 0xFF, (joy >> 8) & 0xFF)
        if d is not None:
            h.dir(d)
    return h


def keyboard(key3, joy3, trig3, hand):
    """The USB keyboard (cont3 type 4) into `hand`."""
    if key3 >> 28 != 4:
        return hand
    for code in [(joy3 >> s) & 0xFF for s in (0, 8, 16, 24)] + [trig3 & 0xFF, trig3 >> 8 & 0xFF]:
        if code in HID:
            hand.key(HID[code])
    return hand


def code(h):
    """The port byte: this core's code table, wired-OR, active low."""
    pulled = 0
    for k, n in KP_BIT.items():
        if bit(h.kp, n):
            pulled |= KEY_CODE[k]
    for i in range(16):
        if bit(h.disc, 15 - i):
            pulled |= DISC_CODE[i]
    return ~pulled & 0xFF


def code_mame(h):
    """MAME's read_ctrl() with the digital disc (handctrl.cpp:146-168)."""
    res = 0xFF
    for i in range(16):
        if bit(h.kp, i):
            res &= MAME_KEYPAD_TABLE[i]
    for i in range(16):
        if bit(h.disc, i):
            res &= MAME_DISC_TABLE[i]
    return res


def hands(v):
    """v: dict with key1 joy1 key2 joy2 key3 joy3 trig3 mode swap -> (p1, p2)."""
    mode = v["mode"] if v["mode"] in (FACE, RSTICK) else LAYER
    p1 = virtual(v["key1"], v["joy1"], mode)
    keyboard(v["key3"], v["joy3"], v["trig3"], p1)
    p2 = virtual(v["key2"], v["joy2"], mode)
    return p1, p2


def ports(v, mame=False):
    """(pad_r, pad_l): $01FE (port A, right) and $01FF (port B, left)."""
    p1, p2 = hands(v)
    c = code_mame if mame else code
    left, right = (p2, p1) if v["swap"] & 1 else (p1, p2)
    return c(right), c(left)


def self_check():
    fails = 0

    def ok(cond, what):
        nonlocal fails
        print(("  ok    " if cond else "  FAIL  ") + what)
        fails += not cond

    # Every single input: this core's code = MAME's table entry, inverted
    ok(all(KEY_CODE[k] == ~MAME_KEYPAD_TABLE[n] & 0xFF for k, n in KP_BIT.items()),
       "15 keypad/side codes = MAME keypad_table (handctrl.cpp:125-129), inverted")
    ok(all(DISC_CODE[i] == ~MAME_DISC_TABLE[15 - i] & 0xFF for i in range(16)),
       "16 disc codes = MAME disc_table (handctrl.cpp:131-135), inverted")
    ok(len(set(KEY_CODE.values()) | set(DISC_CODE)) == 31, "31 distinct codes")
    # The analog disc against MAME's 5x5 analog grid at each cell's centre
    # (MAME's stick is 0x00-0x9f, centre 0x50; ours 0x00-0xff, centre 0x80)
    bad = []
    for gy in range(5):
        for gx in range(5):
            mx, my = 16 + 32 * gx, 16 + 32 * gy
            x, y = 128 + (mx - 80) * 8 // 5, 128 + (my - 80) * 8 // 5
            h = Hand()
            d = stick16(x, y)
            if d is not None:
                h.dir(d)
            if code(h) != MAME_DISCYX_TABLE[gy][gx]:
                bad.append((gx, gy, hex(code(h))))
    ok(not bad, f"analog disc at the 25 cell centres = MAME discyx_table (handctrl.cpp:137-144) {bad}")
    # Integer sectors against the angle
    import math
    worst = 0
    for x in range(256):
        for y in range(256):
            d = stick16(x, y)
            if d is None:
                continue
            ang = math.degrees(math.atan2(x - 128, -(y - 128))) % 360
            err = min(abs(ang - 22.5 * d), 360 - abs(ang - 22.5 * d))
            worst = max(worst, err)
    ok(worst < 11.25 + 0.1, f"stick16: every stick position within {worst:.3f} degrees of its sector centre")
    return fails


if __name__ == "__main__":
    sys.exit(1 if self_check() else 0)
