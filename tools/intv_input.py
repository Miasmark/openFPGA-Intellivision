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
- 1.0.9: players 3 and 4 are the ECS's hand controllers 3 (its PSG's port B,
  $00FF) and 4 (port A, $00FE; MAME devices/bus/intv_ctrl/ecs_ctrl.cpp:149-157,
  World Cup Football through the ECS ROM's $7134), from cont3 and cont4 (types
  1-3; cont3 type 4 is the USB keyboard, so then there is no player 3). The
  ECS's PSG reads them while the ECS is there, attached or on (the owner, 1.0.9:
  the patched Championship Tennis runs attached; tools/ecs.py), unlike the
  keyboard (fully on only); a seat without a controller reads $FF. Swap Controllers (v["swap"], 0-3: Player 1 / 2 / 3 / 4) is the seat of
  cont1 (the Pocket's own buttons): cont1 trades seats with the controller whose
  seat that is (Player 2 = the old swap: cont1 right, cont2 left). The
  on-screen keypads and the ECS keyboard belong to the controller (cont1's,
  cont2's), whatever its seat; cont3 and cont4 have none. All four players use
  the same keypad mode and, in Auto, the game's profile.
- The USB keyboard (cont3 type 4: six HID usage codes in cont3_joy[31:0]
  and cont3_trig[15:0]) is player 1's keypad: 1-9 and 0 on the number row
  and on the numpad, Backspace = Clear, Enter and numpad Enter = Enter.
  Everything ORs into player 1's controller, like a second set of fingers.
- With the ECS fully on (build step 9; v["ecs"] is the ECS mode, tools/ecs.py
  OFF 0, ON 1, ATTACHED 2; only ON counts here) the USB keyboard is the
  ECS keyboard key by key (ECS_HID; ecs_keys()), and only the numpad stays
  player 1's keypad (1-9, 0, numpad Enter, numpad . = Clear). With the
  "ECS Keyboard" setting on Synthesizer (v["synth"]) the two tracker rows
  play the music synthesizer (SYNTH_HID) instead. With the ECS attached
  (ROMs out: Auto's mode for most games) or off the keyboard is the keypad
  as above (0.0.8) and the ECS matrix reads no key (step 9 review: no ECS
  ROM code scans it then, and the games keep the number row).
- Keypad mode Layer (0, default): D-pad = disc (8 directions); A = lower
  right, B = lower left, X = top side action. R held: D-pad = the keypad
  ring by position (up-left/up/up-right = 1/2/3, left/right = 4/6,
  down-left/down/down-right = 7/8/9; the disc is released), and the face
  buttons the keypad's bottom row and centre: Y/B/A = Clear/0/Enter, X = 5
  (the owner's mapping of 2026-11-03: R is the number pad). L held (and R
  not) only turns the D-pad one notch (1/16 turn, 22.5 degrees) clockwise,
  the side buttons staying side actions: D-pad alone N, NE, E, SE,
  S, SW, W, NW; L + D-pad NNE, ENE, ESE, SSE, SSW, WSW, WNW, NNW, so the
  D-pad reaches all 16 disc directions (the owner's "Precision controls",
  2026-10-26; PGA Golf aims with all 16). The chords and the turned disc
  work together (L + up + A = disc NNE and lower right). R beats L. Y alone
  and L+Y do nothing; Select opens the on-screen keypad (build step 13,
  tools/osk.py: hands() takes the keypads and the profile); Start opens the
  on-screen ECS keyboard on player 1's controller while the ECS is fully on
  with the computer keyboard (1.0.4, tools/osk.py Keyboard: hands() masks the
  buttons it takes, ecs_keys() adds its keys).
- Keypad mode Auto (3, the default from step 13): the game profile's mode,
  and in its Layer modes the profile's buttons on A / B / X: each a side
  action or (1.0.8) a keypad key (the TutorVision titles: A Enter, B Clear,
  X lower right: a lower side key returns to their Main Menu); Layer without a profile. R + a face button stays the number pad
  (R+Y/B/A = Clear/0/Enter, R+X = 5) whatever the profile; the fixed modes
  (0-2) never use a profile.
- Keypad mode Face-button ring (1): D-pad = disc; the face buttons are a
  second D-pad on the ring, by position on the Pocket (X up = 2, B down = 8,
  Y left = 4, A right = 6; X+A = 3, X+Y = 1, B+A = 9, B+Y = 7); L = top side
  action, R = 5. L does not turn the D-pad here: it is the side action a
  game may need while moving, so L + D-pad stays one of the 8 directions
  plus the side action.
- Keypad mode Right stick (2): Layer, plus on a docked analog controller
  the right stick picks the ring key by direction (8 sectors) and its click
  (R3) is 5, the ring's centre (R3 = 5 is this core's addition).
- Opposite directions together (up+down, left+right, X+B, Y+A) cancel.
- Analog left stick (type 3, every mode): the disc in 16 directions, ORed
  with the D-pad's disc; inside a dead zone it does nothing. L never turns
  it (it has its 16 directions already).

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

# With the ECS fully on (mode ON, build step 9) the keypad keeps only the numpad: 1-9, 0, numpad Enter, and
# numpad . (Del) as Clear; the number row, Enter and Backspace belong to the ECS keyboard.
HID_ECS = {0x58: "E", 0x63: "C",
           0x59: 1, 0x5A: 2, 0x5B: 3, 0x5C: 4, 0x5D: 5, 0x5E: 6, 0x5F: 7, 0x60: 8, 0x61: 9, 0x62: 0}

# The ECS computer keyboard, key by key (build step 9): HID usage -> (row, column) of the ECS
# matrix (row = port A bit, column = port B bit; MAME ecs_ctrl.cpp ROW.n, the wiki's
# Entertainment_Computer_System table). Backspace is the ECS's left arrow too. Modifiers
# (cont3_key[15:8], the HID modifier byte; on a Dock, 2026-11-21): either Shift -> SHIFT (6, 7), either Ctrl -> CTL (5, 6).
ECS_HID = {
    0x28: (0, 6), 0x27: (0, 5), 0x29: (0, 4), 0x13: (0, 3), 0x33: (0, 2), 0x37: (0, 1), 0x50: (0, 0),
    0x2A: (0, 0),
    0x0F: (1, 7), 0x12: (1, 6), 0x25: (1, 5), 0x26: (1, 4), 0x0C: (1, 3), 0x0E: (1, 2), 0x10: (1, 1),
    0x36: (1, 0),
    0x0D: (2, 7), 0x18: (2, 6), 0x23: (2, 5), 0x24: (2, 4), 0x1C: (2, 3), 0x0B: (2, 2), 0x05: (2, 1),
    0x11: (2, 0),
    0x0A: (3, 7), 0x17: (3, 6), 0x21: (3, 5), 0x22: (3, 4), 0x15: (3, 3), 0x09: (3, 2), 0x06: (3, 1),
    0x19: (3, 0),
    0x07: (4, 7), 0x08: (4, 6), 0x1F: (4, 5), 0x20: (4, 4), 0x1A: (4, 3), 0x16: (4, 2), 0x1D: (4, 1),
    0x1B: (4, 0),
    0x04: (5, 7), 0x4F: (5, 5), 0x1E: (5, 4), 0x14: (5, 3), 0x52: (5, 2), 0x51: (5, 1), 0x2C: (5, 0),
}
ECS_SHIFT, ECS_CTL = (6, 7), (5, 6)
# 2026-11-21, the PC keys: the PC keys ECS_HID leaves out type their PC legend with ECS SHIFT down,
# whatever the PC's Shift (the ECS's shifted legends, measured on the owner's ECS: SHIFT+1 .. 0 =
# = " # $ + - / * ( ), SHIFT+LEFT / UP / DOWN / RIGHT = % ^ ? ' (its one quote)). HID usage ->
# (ECS key without the PC's Shift, with it); None: nothing (the ECS has no _ or ~). With Ctrl held
# they press nothing (as ECS_HID: Ctrl combinations unchanged).
PC_KEYS = {0x2E: ("1", "5"),            # =  +
           0x2D: ("6", None),           # -  _
           0x38: ("7", "DOWN"),         # /  ?
           0x34: ("RIGHT", "2"),        # '  "
           0x35: ("RIGHT", None)}       # `  ~
# Alt (either; HID modifier bits 2 and 6) + 5 = % (SHIFT+LEFT), Alt + 6 = ^ (SHIFT+UP); the plain 5 / 6
# are not pressed then (Ctrl held: the plain ones)
ALT_KEYS = {0x22: "LEFT", 0x23: "UP"}
KB_SEQ = 16384                          # intv_input.sv: each of SHIFT's two waits, in rounds of 8 clk_sys
# The music synthesizer on two tracker rows: Z S X D C V G B H N J M = C3 .. B3 (notes 12-23),
# Q 2 W 3 E R 5 T 6 Y 7 U I = C4 .. C5 (24-36); note n is matrix bit n (MAME ecs_ctrl.cpp SYNTH.n).
SYNTH_HID = {0x1D: 12, 0x16: 13, 0x1B: 14, 0x07: 15, 0x06: 16, 0x19: 17, 0x0A: 18, 0x05: 19,
             0x0B: 20, 0x11: 21, 0x0D: 22, 0x10: 23,
             0x14: 24, 0x1F: 25, 0x1A: 26, 0x20: 27, 0x08: 28, 0x15: 29, 0x22: 30, 0x17: 31,
             0x23: 32, 0x1C: 33, 0x24: 34, 0x18: 35, 0x0C: 36}

DZ_DISC, DZ_RING = 40, 64
SLOPES16 = (51, 171, 383, 1287)
SLOPES8 = (106, 618)

# ring key by (v, h): v = +1 up, -1 down; h = +1 right, -1 left
RING = {(1, -1): 1, (1, 0): 2, (1, 1): 3, (0, -1): 4, (0, 1): 6, (-1, -1): 7, (-1, 0): 8, (-1, 1): 9}
# disc direction (index into DISC_CODE) by (v, h), the D-pad's 8; L in the
# Layer modes adds TURN_L (one notch clockwise)
TURN_L = 1
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

    def dpad(self, v, h, turn=0):
        if (v, h) in DPAD_DIR:
            self.dir((DPAD_DIR[(v, h)] + turn) % 16)


def virtual(key, joy, mode, hand=None, sides=("lr", "ll", "top")):
    """One Pocket controller slot in keypad mode `mode` -> Hand; sides: what A, B, X press in
    the Layer modes (a game profile's in Auto, build step 13): a side action, a keypad key (1.0.8)
    or None (nothing)."""
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
            for btn, k in ((Y, "C"), (B, 0), (A, "E"), (X, 5)):    # the keypad's bottom row, X = 5
                if b[btn]:
                    h.key(k)
        else:
            h.dpad(*dp, turn=TURN_L if b[L1] else 0)
            for btn, k in ((A, sides[0]), (B, sides[1]), (X, sides[2])):   # L only turns the D-pad
                if b[btn] and k is not None:
                    h.key(k)
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


def hid_codes(joy3, trig3):
    return [(joy3 >> s) & 0xFF for s in (0, 8, 16, 24)] + [trig3 & 0xFF, trig3 >> 8 & 0xFF]


ECS_ON = 1                                  # tools/ecs.py ON: the mode that takes the keyboard


def keyboard(key3, joy3, trig3, hand, ecs=0):
    """The USB keyboard (cont3 type 4) into `hand`; ecs: the ECS mode (only the numpad is the
    keypad with the ECS fully on, ECS_ON)."""
    if key3 >> 28 != 4:
        return hand
    table = HID_ECS if ecs == ECS_ON else HID
    for code in hid_codes(joy3, trig3):
        if code in table:
            hand.key(table[code])
    return hand


def kpbit(name):
    import ecs as ecsm
    r, c = ecsm.KEYPOS[name]
    return 1 << (8 * r + c)


SHIFT_BIT, CTL_BIT = 1 << (8 * ECS_SHIFT[0] + ECS_SHIFT[1]), 1 << (8 * ECS_CTL[0] + ECS_CTL[1])


def pc_key(c, s, t, a):
    """One HID usage code with the PC's Shift, Ctrl and Alt of its key-down -> (matrix bit or 0,
    SHIFT down): the positional key (ECS_HID: SHIFT as the PC's Shift) or a PC key (PC_KEYS,
    ALT_KEYS: SHIFT down)."""
    if not t:
        if c in PC_KEYS:
            k = PC_KEYS[c][1 if s else 0]
            return (kpbit(k), True) if k else (0, False)
        if a and c in ALT_KEYS:
            return kpbit(ALT_KEYS[c]), True
    if c in ECS_HID:
        r, col = ECS_HID[c]
        return 1 << (8 * r + col), False
    return 0, False


class UsbKeys:
    """intv_input.sv's USB keyboard into the ECS matrix, round by round (a round: 8 clk_sys): each
    code keeps the {Shift, Ctrl, Alt} of its key-down while held (the codes of the last round's word
    with the computer keyboard); a key pressed (a new code with a switch) that needs SHIFT the other
    way from a key held drops that key, which stays dropped until let go (the newest key wins, as on
    a PC; the PC's Shift itself drops nothing); SHIFT (us) changes only after a wait of `seq` + 1
    rounds in which keys only leave (a drop starts one), and keys join after another such wait.
    step(v, ef) is one round of word v
    with ecs_full ef; settle(v, ef) runs rounds until nothing changes; keys() the matrix bits (CTL
    from the word: shown at once)."""

    def __init__(self, seq=KB_SEQ):
        self.seq = seq
        self.tab = {}                       # code -> ((s, t, a) at its key-down, dropped)
        self.ukp = self.ukd = 0
        self.us = False
        self.tm = 0
        self.ctl = False

    def state(self):
        return (tuple(sorted(self.tab.items())), self.ukp, self.ukd, self.us, self.tm, self.ctl)

    def step(self, v, ef):
        kbd = v["key3"] >> 28 == 4
        sy = v.get("synth") == 1
        ecw = kbd and not sy
        ecm = ecw and ef
        mods = (v["key3"] >> 8) & 0xFF
        now = (bool(mods & 0x22), bool(mods & 0x11), bool(mods & 0x44))
        sh = now[0]
        ep = ed = 0
        ent = {}                            # code -> (m, dropped, new, has a switch, SHIFT down)
        for c in hid_codes(v["joy3"], v["trig3"]):
            m, x = self.tab.get(c, (now, False))
            b, down = pc_key(c, *m)
            if ecw:
                ent.setdefault(c, (m, x, c not in self.tab, bool(b) and not x, down))
            if kbd and ef:
                if sy:
                    if c in SYNTH_HID:
                        ep |= 1 << SYNTH_HID[c]
                elif not x:
                    if down:
                        ed |= b
                    else:
                        ep |= b
        anynew = any(new and k for _, _, new, k, _ in ent.values())
        nt = any(new and k and (down or sh) for _, _, new, k, down in ent.values())
        self.tab = {c: (m, x or (anynew and k and (down or sh) != nt)) for c, (m, x, new, k, down) in ent.items()}
        mk = any(self.tab[c][1] != e[1] for c, e in ent.items())
        if not ecm:
            self.ukp, self.ukd, self.us, self.tm = ep, 0, False, 0
        else:
            ds = bool(ed) or sh
            ukp, ukd, us, tm = self.ukp & ep, self.ukd & ed, self.us, 0
            if mk:
                tm = self.seq
            elif self.tm:
                tm = self.tm - 1
                if self.tm == 1 and self.us != ds:
                    us, tm = ds, self.seq
            elif self.us != ds:
                tm = self.seq
            else:
                ukd, ukp = ed, ep
            self.ukp, self.ukd, self.us, self.tm = ukp, ukd, us, tm
        self.ctl = ecm and now[1]

    def advance(self, v, ef, n):
        """n rounds of word v (fast over the waits once nothing but the wait changes, and once nothing
        changes at all)."""
        while n > 0:
            before = self.state()
            self.step(v, ef)
            n -= 1
            if self.tm == 0 and self.state() == before:
                return
            if self.tm > 1 and n > 0 and self.state()[:4] == before[:4] and self.state()[5:] == before[5:]:
                k = min(self.tm - 1, n)
                self.tm -= k
                n -= k

    def settle(self, v, ef):
        """Rounds of word v until nothing changes (a wait's rounds change only tm: skipped)."""
        for _ in range(64):
            before = self.state()
            self.step(v, ef)
            self.tm = min(self.tm, 1)
            if self.state() == before:
                return self.keys()
        raise RuntimeError("UsbKeys: no settled state")

    def keys(self):
        return self.ukp | self.ukd | (SHIFT_BIT if self.us else 0) | (CTL_BIT if self.ctl else 0)


def ecs_keys(v, kb=None, usb=None):
    """The ECS keyboard's pressed switches (bit 8 row + column) from the USB keyboard, while
    the ECS is fully on (v["ecs"] == ECS_ON; attached or off: none), settled (UsbKeys: usb, the
    keyboard's state from the words before, or none held before); v["synth"] == 1: the
    synthesizer instead (tracker rows). kb: the on-screen ECS keyboard (tools/osk.py
    Keyboard), its keys with the computer keyboard."""
    usb = usb if usb is not None else UsbKeys()
    bits = usb.settle(v, v.get("ecs") == ECS_ON)
    if v.get("ecs") != ECS_ON:
        return 0
    if kb is not None and v.get("synth") != 1:
        bits |= kb.keys()
    return bits


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


AUTO = 3                                    # Keypad Mode 3: the game profile's (build step 13)


def hands(v, osk=None, prof=None, kb=None):
    """v: dict with key1 joy1 key2 joy2 key3 joy3 trig3 mode swap -> (p1, p2). osk: the two
    on-screen keypads (tools/osk.py Player, build step 13): the buttons they take are masked
    and their keys pressed; prof: the game's profile (tools/osk.py), used in mode Auto (3); kb:
    the on-screen ECS keyboard (tools/osk.py Keyboard): the buttons it takes on player 1's
    controller are masked."""
    sides = ("lr", "ll", "top")
    mode = v["mode"]
    if mode == AUTO:
        mode = prof["mode"] if prof else LAYER
        if prof:
            sides = prof["sides"]
    elif mode not in (FACE, RSTICK):
        mode = LAYER
    hs = []
    for n, (k, j) in enumerate(((v["key1"], v["joy1"]), (v["key2"], v["joy2"]))):
        if osk:
            k &= ~osk[n].buttons_mask() & 0xFFFFFFFF
        if kb is not None and n == 0:
            k &= ~kb.buttons_mask() & 0xFFFFFFFF
        h = virtual(k, j, mode, sides=sides)
        if osk and osk[n].key() is not None:
            h.key(osk[n].key())
        hs.append(h)
    keyboard(v["key3"], v["joy3"], v["trig3"], hs[0], v.get("ecs", 0))
    return hs[0], hs[1]


def seats(v):
    """1.0.9: the controller (0-3: cont1-cont4) in each seat (players 1-4): cont1 takes seat
    v["swap"] (Swap Controllers: Player 1 / 2 / 3 / 4) and trades it with that seat's
    controller."""
    s = list(range(4))
    n = v["swap"] & 3
    s[0], s[n] = s[n], s[0]
    return s


def players(v, osk=None, prof=None, kb=None):
    """1.0.9: the four players' hands (players 1-4), from the controllers' hands by seat."""
    c1, c2 = hands(v, osk, prof, kb)
    mode, sides = v["mode"], ("lr", "ll", "top")
    if mode == AUTO:
        mode = prof["mode"] if prof else LAYER
        if prof:
            sides = prof["sides"]
    elif mode not in (FACE, RSTICK):
        mode = LAYER
    c3 = virtual(v["key3"], v["joy3"], mode, sides=sides)          # type 4 (the keyboard): no hand
    c4 = virtual(v.get("key4", 0), v.get("joy4", 0x80808080), mode, sides=sides)
    ctl = (c1, c2, c3, c4)
    return [ctl[i] for i in seats(v)]


def ports4(v, mame=False, osk=None, prof=None, kb=None):
    """1.0.9: (pad_r, pad_l, ecs_a, ecs_b): $01FE (port A: player 2), $01FF (port B: player 1),
    the ECS's $00FE (port A: player 4) and $00FF (port B: player 3), in every ECS mode (the ECS's
    PSG reads the last two while it is there, attached or on: tools/ecs.py)."""
    p = players(v, osk, prof, kb)
    c = code_mame if mame else code
    return c(p[1]), c(p[0]), c(p[3]), c(p[2])


def ports(v, mame=False, osk=None, prof=None, kb=None):
    """(pad_r, pad_l): $01FE (port A, right) and $01FF (port B, left)."""
    return ports4(v, mame, osk, prof, kb)[:2]


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
    # L + D-pad in Layer mode: the D-pad's 8 turned one notch clockwise; with the plain 8, all 16
    plain, turned = set(), set()
    for (v, hh), d in DPAD_DIR.items():
        bits = {(1, 0): 1 << UP, (-1, 0): 1 << DOWN, (0, 1): 1 << RIGHT, (0, -1): 1 << LEFT}
        k = (1 << 28) | bits.get((v, 0), 0) | bits.get((0, hh), 0)
        plain.add(virtual(k, 0, LAYER).disc)
        t = virtual(k | 1 << L1, 0, LAYER).disc
        turned.add(t if t == 1 << (15 - (d + 1) % 16) else None)
    ok(None not in turned and len(plain | turned) == 16,
       "Layer: D-pad = 8 disc directions, L + D-pad = the other 8, each one notch clockwise")
    # The ECS keyboard: every matrix key of tools/ecs.py KEYPOS reachable, one HID code each
    # (Backspace doubles the left arrow), Shift and Ctrl from the modifier byte
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
    import ecs as ecsm
    pos = {}
    for c, rc in ECS_HID.items():
        pos.setdefault(rc, []).append(c)
    want = {rc for n, rc in ecsm.KEYPOS.items() if n not in ("SHIFT", "CTL")}
    ok(set(pos) == want and all(len(v) == 1 for rc, v in pos.items() if rc != (0, 0)) and len(pos[(0, 0)]) == 2,
       "ECS keyboard: the 47 matrix keys of tools/ecs.py KEYPOS, one HID code each (+ Backspace)")
    base = dict(key1=0, joy1=0x80808080, key2=0, joy2=0x80808080, joy3=0, trig3=0, mode=LAYER, swap=0)
    ok(ecs_keys(dict(base, key3=(4 << 28) | 0x0200, ecs=1)) == 1 << 55 and
       ecs_keys(dict(base, key3=(4 << 28) | 0x1000, ecs=1)) == 1 << 46,
       "ECS keyboard: Shift -> row 6 column 7, Ctrl -> row 5 column 6")
    ok(ecs_keys(dict(base, key3=4 << 28, joy3=0x1A, ecs=0)) == 0 and
       ecs_keys(dict(base, key3=4 << 28, joy3=0x1A, ecs=2)) == 0, "ECS keyboard: nothing with the ECS off or attached")
    ok(ports(dict(base, key3=4 << 28, joy3=0x1E, ecs=2)) == ports(dict(base, key3=4 << 28, joy3=0x1E, ecs=0)) != (0xFF, 0xFF),
       "ECS attached: the number row is the keypad, as with the ECS off")
    ok(sorted(SYNTH_HID.values()) == list(range(12, 37)), "synthesizer: 25 notes C3-C5")
    # 2026-11-21, the PC keys: only on codes ECS_HID leaves out; each with SHIFT down
    ok(not set(PC_KEYS) & set(ECS_HID) and set(ALT_KEYS) <= set(ECS_HID),
       "PC keys: = - / ' ` are not ECS_HID keys; Alt's 5 and 6 are")

    def kb(codes, mods=0, usb=None):
        cs = list(codes) + [0] * (6 - len(codes))
        return ecs_keys(dict(base, key3=(4 << 28) | mods << 8, joy3=cs[0] | cs[1] << 8 | cs[2] << 16 | cs[3] << 24,
                             trig3=cs[4] | cs[5] << 8, ecs=1), usb=usb)
    S = SHIFT_BIT
    ok(kb([0x2E]) == S | kpbit("1") and kb([0x2E], 0x02) == S | kpbit("5") and kb([0x2D]) == S | kpbit("6")
       and kb([0x2D], 0x20) == S and kb([0x38]) == S | kpbit("7") and kb([0x38], 0x02) == S | kpbit("DOWN")
       and kb([0x34]) == S | kpbit("RIGHT") and kb([0x34], 0x02) == S | kpbit("2") and kb([0x35]) == S | kpbit("RIGHT")
       and kb([0x35], 0x02) == S, "PC keys: = + - / ? ' \" `; Shift+- and Shift+` only the Shift")
    ok(kb([0x22], 0x04) == S | kpbit("LEFT") and kb([0x23], 0x40) == S | kpbit("UP") and kb([0x22]) == kpbit("5")
       and kb([0x22], 0x02) == S | kpbit("5") and kb([0x22], 0x05) == CTL_BIT | kpbit("5"),
       "Alt+5 = %, Alt+6 = ^; 5 alone 5, Shift+5 positional, Ctrl+Alt+5 positional")
    ok(kb([0x2E], 0x01) == CTL_BIT and kb([0x0B], 0x01) == CTL_BIT | kpbit("H"),
       "Ctrl: the PC keys press nothing, Ctrl+H = CTL+H")
    u = UsbKeys(seq=2)
    kb([0x38], 0x02, u)                                     # Shift+/ = ?
    ok(kb([0x38], 0, u) == S | kpbit("DOWN"), "a key keeps its key-down's Shift: ? stays ? when Shift goes first")
    ok(kb([], 0, u) == 0, "released: SHIFT goes up")
    u = UsbKeys(seq=2)
    kb([0x2D], 0, u)                                        # - held, 3 pressed: - dropped (no #)
    ok(kb([0x2D, 0x20], 0, u) == kpbit("3") and kb([0x2D, 0x20], 0, u) == kpbit("3") and kb([0x2D], 0, u) == 0,
       "- held, 3 pressed: - dropped for good, 3 without SHIFT")
    u = UsbKeys(seq=2)
    kb([0x04], 0, u)                                        # A held, = tapped: A dropped, not back
    ok(kb([0x04, 0x2E], 0, u) == S | kpbit("1") and kb([0x04], 0, u) == 0 and kb([0x04, 0x05], 0, u) == kpbit("B"),
       "A held, = tapped: A dropped (no second A), then B as usual")
    u = UsbKeys(seq=2)
    kb([0x04], 0, u)                                        # A held, Shift pressed: genuine ECS SHIFT+A
    ok(kb([0x04], 0x02, u) == S | kpbit("A") and kb([0x04, 0x2E], 0x02, u) == S | kpbit("A") | kpbit("5"),
       "A held, Shift pressed: SHIFT+A (no drop); then Shift+= with A: both, SHIFT down")
    # 1.0.8: a profile's keypad keys on the face buttons (the TutorVision titles), in Auto only
    tv = dict(mode=LAYER, sides=("E", "C", "lr"))

    def p1(btns, mode=AUTO, prof=tv):
        k = (1 << 28) | sum(1 << n for n in btns)
        return hands(dict(base, key1=k, key3=0, mode=mode), prof=prof)[0]
    want = Hand()
    ok(p1([A]).kp == 1 << KP_BIT["E"] and p1([B]).kp == 1 << KP_BIT["C"] and p1([X]).kp == 1 << KP_BIT["lr"]
       and p1([Y]).kp == 0, "Auto + TutorVision profile: A Enter, B Clear, X lower right, Y nothing")
    ok(all(p1([R1, b]).kp == 1 << KP_BIT[k] for b, k in ((Y, "C"), (B, 0), (A, "E"), (X, 5))),
       "Auto + TutorVision profile: R+Y/B/A/X = Clear/0/Enter/5 (the number pad unchanged)")
    h = p1([L1, UP, A])
    want.dir(TURN_L)
    ok(h.kp == 1 << KP_BIT["E"] and h.disc == want.disc, "Auto + TutorVision profile: L+up+A = disc NNE + Enter")
    ok(all(p1([A, B, X], mode=md).kp == p1([A, B, X], mode=md, prof=None).kp for md in (LAYER, FACE, RSTICK)),
       "the fixed modes ignore the profile")
    # 1.0.9: players 3 / 4 on the ECS's ports, Swap Controllers' seats
    pk = {n: (1 << 28) | (1 << b) for n, b in ((1, A), (2, B), (3, X), (4, UP))}
    w = {n: code(virtual(pk[n], 0, LAYER)) for n in pk}
    v4 = dict(base, key1=pk[1], key2=pk[2], key3=pk[3], key4=pk[4], ecs=1)
    ok(ports4(dict(v4, swap=0)) == (w[2], w[1], w[4], w[3]), "seat Player 1: P1 cont1, P2 cont2, P3 cont3, P4 cont4")
    ok(ports4(dict(v4, swap=1)) == (w[1], w[2], w[4], w[3]), "seat Player 2: cont1 and cont2 trade (the old swap)")
    ok(ports4(dict(v4, swap=2)) == (w[2], w[3], w[4], w[1]), "seat Player 3: cont1 on the ECS's port B, cont3 player 1")
    ok(ports4(dict(v4, swap=3)) == (w[2], w[4], w[1], w[3]), "seat Player 4: cont1 on the ECS's port A, cont4 player 1")
    ok(ports4(dict(v4, swap=2, ecs=2)) == ports4(dict(v4, swap=2, ecs=0)) == ports4(dict(v4, swap=2)),
       "players 3 / 4 in every ECS mode (the ECS reads them attached or on)")
    ok(ports4(dict(base, key1=pk[1], key3=0, ecs=2))[2:] == (0xFF, 0xFF),
       "attached, no controller 3 / 4: both ports $FF (as before 1.0.9)")
    ok(ports4(dict(v4, key3=4 << 28, joy3=0x59))[3] == 0xFF and ports4(dict(v4, key3=4 << 28, joy3=0x59))[1] != w[1],
       "the USB keyboard in slot 3: no player 3; its keypad (numpad 1, the ECS on) joins cont1's hand")
    return fails


if __name__ == "__main__":
    sys.exit(1 if self_check() else 0)
