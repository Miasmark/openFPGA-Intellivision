#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Step-6 input bench driver (DESIGN.md 7, 9): intv_input.sv against the
model (tools/intv_input.py) and MAME's hand-controller tables.

  python3 -I sim/tb/tb_input.py --all     the gate: vectors, RTL run, then
                                          the planted faults (each must fail)
  python3 -I sim/tb/tb_input.py [--no-build]

Vector classes (one line each in sim/work/tb_input/vectors.txt):
  0  spec: each row of the agreed mapping (the owner's input notes, DESIGN
     7.2) written out by hand as the hand-controller inputs it must press,
     named as MAME's handctrl.cpp:19-54 names them; the expected bytes are
     MAME's read_ctrl() of those inputs (handctrl.cpp:123-168, its tables
     transcribed), not the model's; on both ports (Swap Controllers);
  1  every combination of the 16 Pocket buttons on player 1 (type 1) in
     each keypad mode (0-3), player 2 random;
  2  every combination on player 2 (docked digital, type 2), modes cycling;
  3  the left stick over its whole 256 x 256 range (docked analog, type 3),
     player 1 and player 2, modes cycling, random buttons on every 7th;
  4  the right stick over its whole range in Right stick mode (and every
     4th in Layer and Face-button ring, where it must do nothing), R3 on
     every 5th;
  5  the USB keyboard: every usage code in each of the six report bytes,
     then random reports of up to six keys, with player 1's buttons;
  6  slot types: every type 0-15 on cont1, cont2 and cont3 with random
     words (only 1-3 are controllers, only cont3 type 4 is a keyboard);
  7  random: everything random, both Swap settings;
  8  MAME's analog disc: the 24 off-centre cells of handctrl.cpp:137-144's
     5 x 5 grid, at each cell's centre, in every mode and on both ports;
     the expected byte is that table's entry;
  10 the ECS keyboard (step 9), written out by hand (ECS_SPEC, SYNTH_SPEC):
     every ECS key by its HID usage code in each report byte gives its
     switch (bit 8 row + column, tools/ecs.py KEYPOS: MAME ecs_ctrl.cpp's
     ROW.n and the wiki's table) and no keypad key; nothing without the
     ECS; Shift and Ctrl from either side of the modifier byte; the
     synthesizer's tracker rows give their notes; with the ECS only the
     numpad is the keypad (MAME's keypad names);
  11 every usage code in each byte with and without the ECS and the
     synthesizer, and 20,000 random reports with modifiers (expected: the
     model). Every vector also carries the ECS settings (Auto / On / Off,
     synthesizer), which must come out of the crossing unchanged.
  9  L + D-pad (the owner's Precision controls, 2026-10-26: in the Layer
     modes L turns the D-pad one notch, 22.5 degrees, clockwise; in
     Face-button ring L stays the top side action, no turn; the stick is
     never turned): every D-pad state (none, the 8, up+down, up+down+left)
     with every set of A/B/X/Y, with and without L and R, every mode, slot
     types 1-3 (type 3 with the left stick centred and, on every 4th, in
     each of its 16 directions), either player, both Swap settings; the
     expected bytes are MAME's read_ctrl() of the inputs l_oracle() writes
     out from the mapping, not the model's, and the model must agree.
For classes 1-7 the expected bytes are the model's, and the model with
this core's code table must equal MAME's read_ctrl() for every vector.

The crossing (sim/work/tb_input/tear.txt): 2,000 groups of 2-4 vectors
whose bit-by-bit mixtures give other bytes (keyboard usage codes such as
1E '1' and 21 '4', button sets, Keypad Mode 1 and 2, Swap, slot types,
everything random). tb_input.sv changes the inputs among a group's
vectors at random clk_74a edges, each bit at its own moment within the
clk_74a cycle, and at every clk edge both bytes must be one of the group's
vectors' bytes (the model's): no torn word may reach the pad bytes. The
plant bitwise_sync (the step-6 crossing before 0.0.5: two flip-flops per
bit) must fail there.

That model only skews the raw clk_74a inputs, so it cannot see a fault in
the handshake itself (the held copy is a register). Two more checks:
the bench's handshake rule (the copy must not change while a transfer is
in flight), and the skew build: a second build of intv_input.sv where the
clk side reads the copy and the request through views the bench drives,
each bit arriving 0.5 to 19.75 ns after it changes (tb_input.sv, -DTB_SKEW),
run over the crossing groups. The plants run on the skew build;
copy_while_in_flight (the copy retaken at every clk_74a edge) and
reg_then_bitwise (a registered copy crossed bit by bit) must fail. A load
decided on the request's first flip-flop is metastability, which no
simulation here shows: sim/check/fit_crossing_check.py checks the fit's
metastability report for two flip-flops on each flag instead.
"""
import argparse
import os
import random
import re
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import intv_input as m  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, 'sim', 'tb'))
import tbcommon  # noqa: E402

CORE = os.path.join(ROOT, 'src', 'fpga', 'core')
RTL = ['intv_input.sv']
TB = os.path.join(ROOT, 'sim', 'tb', 'tb_input.sv')

# MAME DISC_DG bit names (handctrl.cpp:39-54), N first, clockwise
DIRS = ['Up', 'Up-Up-Right', 'Up-Right', 'Right-Up-Right', 'Right', 'Right-Down-Right', 'Down-Right',
        'Down-Down-Right', 'Down', 'Down-Down-Left', 'Down-Left', 'Left-Down-Left', 'Left', 'Left-Up-Left',
        'Up-Left', 'Up-Up-Left']
MAME_DISC_BIT = {n: 15 - i for i, n in enumerate(DIRS)}
# MAME KEYPAD bit names (handctrl.cpp:21-35)
MAME_KEY_BIT = {'1': 15, '2': 14, '3': 13, '4': 12, '5': 11, '6': 10, '7': 9, '8': 8, '9': 7,
                'Clear': 6, '0': 5, 'Enter': 4, 'Upper': 3, 'Lower-Left': 2, 'Lower-Right': 1}

BTN = {'up': m.UP, 'down': m.DOWN, 'left': m.LEFT, 'right': m.RIGHT, 'A': m.A, 'B': m.B, 'X': m.X,
       'Y': m.Y, 'L': m.L1, 'R': m.R1, 'L2': m.L2, 'R2': m.R2, 'L3': m.L3, 'R3': m.R3,
       'Select': m.SELECT, 'Start': m.START}
DPAD8 = [('up',), ('up', 'right'), ('right',), ('down', 'right'), ('down',), ('down', 'left'), ('left',),
         ('up', 'left')]


def mame_read_ctrl(names):
    """MAME's read_ctrl() (digital disc) for a set of hand-controller inputs."""
    kp = disc = 0
    for n in names:
        if n in MAME_KEY_BIT:
            kp |= 1 << MAME_KEY_BIT[n]
        else:
            disc |= 1 << MAME_DISC_BIT[n]
    res = 0xFF
    for i in range(16):
        if kp >> i & 1:
            res &= m.MAME_KEYPAD_TABLE[i]
        if disc >> i & 1:
            res &= m.MAME_DISC_TABLE[i]
    return res


def keys(*names, t=1):
    v = t << 28
    for n in names:
        v |= 1 << BTN[n]
    return v


def stick(deg, r=100):
    """Stick bytes at an angle (clockwise from up) and radius."""
    import math
    x = 128 + round(r * math.sin(math.radians(deg)))
    y = 128 - round(r * math.cos(math.radians(deg)))
    return max(0, min(255, x)), max(0, min(255, y))


def spec_rows():
    """(description, mode, cont1 key, cont1 joy, cont3 key, cont3 joy, cont3 trig, cont2 key, MAME inputs on
    player 1, MAME inputs on player 2)."""
    rows = []

    def r(desc, mode, k1, want, j1=0x80808080, k3=0, j3=0, t3=0, k2=0, want2=()):
        rows.append((desc, mode, k1, j1, k3, j3, t3, k2, tuple(want), tuple(want2)))

    ring_pos = {('up',): '2', ('up', 'right'): '3', ('right',): '6', ('down', 'right'): '9',
                ('down',): '8', ('down', 'left'): '7', ('left',): '4', ('up', 'left'): '1'}
    for mode in (0, 3):
        L = f'mode {mode}'
        for i, d in enumerate(DPAD8):
            r(f'{L}: D-pad {"+".join(d)} = disc {DIRS[2 * i]}', mode, keys(*d), [DIRS[2 * i]])
            r(f'{L}: R + D-pad {"+".join(d)} = key {ring_pos[d]}', mode, keys('R', *d), [ring_pos[d]])
            r(f'{L}: L + D-pad {"+".join(d)} = disc {DIRS[2 * i + 1]} (one notch clockwise)', mode,
              keys('L', *d), [DIRS[2 * i + 1]])
        r(f'{L}: up+down = nothing', mode, keys('up', 'down'), [])
        r(f'{L}: left+right = nothing', mode, keys('left', 'right'), [])
        r(f'{L}: up+down+left = disc Left', mode, keys('up', 'down', 'left'), ['Left'])
        r(f'{L}: R + up+down+left+right = nothing', mode, keys('R', 'up', 'down', 'left', 'right'), [])
        r(f'{L}: A = Lower-Right', mode, keys('A'), ['Lower-Right'])
        r(f'{L}: B = Lower-Left', mode, keys('B'), ['Lower-Left'])
        r(f'{L}: X = Upper', mode, keys('X'), ['Upper'])
        r(f'{L}: Y alone = nothing', mode, keys('Y'), [])
        r(f'{L}: A+B+X = three side actions', mode, keys('A', 'B', 'X'), ['Lower-Right', 'Lower-Left', 'Upper'])
        # R: the number pad (the owner's mapping of 2026-11-03): the keypad's bottom row on the lower
        # buttons, Y B A = Clear 0 Enter, and X = 5
        r(f'{L}: R+Y = Clear', mode, keys('R', 'Y'), ['Clear'])
        r(f'{L}: R+B = 0', mode, keys('R', 'B'), ['0'])
        r(f'{L}: R+A = Enter', mode, keys('R', 'A'), ['Enter'])
        r(f'{L}: R+X = 5', mode, keys('R', 'X'), ['5'])
        r(f'{L}: R+Y+B+A+X = Clear, 0, Enter, 5', mode, keys('R', 'Y', 'B', 'A', 'X'), ['Clear', '0', 'Enter', '5'])
        r(f'{L}: R alone = nothing', mode, keys('R'), [])
        # L: only the D-pad's 1/16 turn (2026-11-03): the side buttons stay side actions
        r(f'{L}: L+A = Lower-Right', mode, keys('L', 'A'), ['Lower-Right'])
        r(f'{L}: L+B = Lower-Left', mode, keys('L', 'B'), ['Lower-Left'])
        r(f'{L}: L+X = Upper', mode, keys('L', 'X'), ['Upper'])
        r(f'{L}: L+Y = nothing', mode, keys('L', 'Y'), [])
        r(f'{L}: L+R+A = Enter (R beats L)', mode, keys('L', 'R', 'A'), ['Enter'])
        r(f'{L}: R+up+A = keys 2 and Enter together', mode, keys('R', 'up', 'A'), ['2', 'Enter'])
        r(f'{L}: up+A = disc Up and Lower-Right together', mode, keys('up', 'A'), ['Up', 'Lower-Right'])
        # L + D-pad (the owner's Precision controls, 2026-10-26): the chords and the turned disc together
        r(f'{L}: L+up+A = disc Up-Up-Right and Lower-Right', mode, keys('L', 'up', 'A'), ['Up-Up-Right', 'Lower-Right'])
        r(f'{L}: L+right+B = disc Right-Down-Right and Lower-Left', mode, keys('L', 'right', 'B'),
          ['Right-Down-Right', 'Lower-Left'])
        r(f'{L}: L+down+X = disc Down-Down-Left and Upper', mode, keys('L', 'down', 'X'), ['Down-Down-Left', 'Upper'])
        r(f'{L}: L+left+Y = disc Left-Up-Left (Y nothing)', mode, keys('L', 'left', 'Y'), ['Left-Up-Left'])
        r(f'{L}: L+up+left+A+B+X = disc Up-Up-Left and the three side actions', mode,
          keys('L', 'up', 'left', 'A', 'B', 'X'), ['Up-Up-Left', 'Lower-Right', 'Lower-Left', 'Upper'])
        r(f'{L}: L+down+right+A = disc Down-Down-Right and Lower-Right', mode, keys('L', 'down', 'right', 'A'),
          ['Down-Down-Right', 'Lower-Right'])
        r(f'{L}: L+up+down = nothing', mode, keys('L', 'up', 'down'), [])
        r(f'{L}: L+up+down+left = disc Left-Up-Left', mode, keys('L', 'up', 'down', 'left'), ['Left-Up-Left'])
        r(f'{L}: L+left+right+X = Upper only', mode, keys('L', 'left', 'right', 'X'), ['Upper'])
        r(f'{L}: L+R+up = key 2 (R beats L, no turn)', mode, keys('L', 'R', 'up'), ['2'])
        r(f'{L}: L+R+up+right+B = keys 3 and 0', mode, keys('L', 'R', 'up', 'right', 'B'), ['3', '0'])
        r(f'{L}: L+Start+up = disc Up-Up-Right', mode, keys('L', 'Start', 'up'), ['Up-Up-Right'])
        r(f'{L}: Start, Select, L2, R2, L3, R3 = nothing', mode, keys('Start', 'Select', 'L2', 'R2', 'L3', 'R3'), [])
    L = 'Face-button ring'
    for desc, ks, want in [('X = 2', ('X',), ['2']), ('B = 8', ('B',), ['8']), ('Y = 4', ('Y',), ['4']),
                           ('A = 6', ('A',), ['6']), ('X+A = 3', ('X', 'A'), ['3']), ('X+Y = 1', ('X', 'Y'), ['1']),
                           ('B+A = 9', ('B', 'A'), ['9']), ('B+Y = 7', ('B', 'Y'), ['7']),
                           ('X+B = nothing', ('X', 'B'), []), ('Y+A = nothing', ('Y', 'A'), []),
                           ('X+B+A = 6', ('X', 'B', 'A'), ['6']),
                           ('L = Upper', ('L',), ['Upper']), ('R = 5', ('R',), ['5']),
                           ('L+up = Upper and disc Up (no turn)', ('L', 'up'), ['Upper', 'Up']),
                           ('L+down+right = Upper and disc Down-Right (no turn)', ('L', 'down', 'right'),
                            ['Upper', 'Down-Right']),
                           ('L+left+X = Upper, disc Left, 2', ('L', 'left', 'X'), ['Upper', 'Left', '2']),
                           ('R+X = 5 and 2', ('R', 'X'), ['5', '2']), ('up = disc Up', ('up',), ['Up']),
                           ('R+up = 5 and disc Up', ('R', 'up'), ['5', 'Up']),
                           ('down+left+B = disc Down-Left and 8', ('down', 'left', 'B'), ['Down-Left', '8']),
                           ('Start, Select = nothing', ('Start', 'Select'), [])]:
        r(f'{L}: {desc}', 1, keys(*ks), want)
    # Right stick mode (docked analog)
    rpos = ['2', '3', '6', '9', '8', '7', '4', '1']
    for i, k in enumerate(rpos):
        x, y = stick(45 * i, 110)
        r(f'Right stick: right stick at {45 * i} degrees = key {k}', 2, keys(t=3), [k], j1=(y << 24) | (x << 16) | 0x8080)
        r(f'Layer: right stick at {45 * i} degrees = nothing', 0, keys(t=3), [], j1=(y << 24) | (x << 16) | 0x8080)
        r(f'Face-button ring: right stick at {45 * i} degrees = nothing', 1, keys(t=3), [],
          j1=(y << 24) | (x << 16) | 0x8080)
    x, y = stick(90, 50)
    r('Right stick: right stick inside its dead zone = nothing', 2, keys(t=3), [], j1=(y << 24) | (x << 16) | 0x8080)
    r('Right stick: R3 = 5', 2, keys('R3', t=3), ['5'])
    r('Layer: R3 = nothing', 0, keys('R3', t=3), [])
    r('Right stick: R+A = Enter (Layer kept)', 2, keys('R', 'A', t=3), ['Enter'])
    for i, d in enumerate(DPAD8):
        r(f'Right stick: L + D-pad {"+".join(d)} = disc {DIRS[2 * i + 1]} (Layer kept)', 2, keys('L', *d, t=3),
          [DIRS[2 * i + 1]])
    r('Right stick: L+up+X = disc Up-Up-Right and Upper', 2, keys('L', 'up', 'X', t=2), ['Up-Up-Right', 'Upper'])
    r('Right stick on the Pocket (type 1): stick words ignored', 2, keys(t=1), [], j1=0x00FF00FF)
    # Left stick: 16 directions, all modes
    for mode in range(4):
        for i, d in enumerate(DIRS):
            x, y = stick(22.5 * i, 100)
            r(f'mode {mode}: left stick at {22.5 * i} degrees = disc {d}', mode, keys(t=3), [d], j1=0x80800000 | (y << 8) | x)
        x, y = stick(30, 35)
        r(f'mode {mode}: left stick inside its dead zone = nothing', mode, keys(t=3), [], j1=0x80800000 | (y << 8) | x)
    r('left stick on the Pocket (type 1) = nothing', 0, keys(t=1), [], j1=0x80800000)
    r('left stick on a docked digital pad (type 2) = nothing', 0, keys(t=2), [], j1=0x80800000)
    r('left stick N with D-pad right = two disc lines ORed', 0, keys('right', t=3), ['Up', 'Right'], j1=0x80800080 | (20 << 8))
    # L never turns the left stick (16 directions already)
    for mode in range(4):
        for i in (0, 3, 4, 9):
            x, y = stick(22.5 * i, 100)
            r(f'mode {mode}: L + left stick at {22.5 * i} degrees = disc {DIRS[i]} (no turn)'
              + (' and Upper' if mode == 1 else ''), mode, keys('L', t=3), [DIRS[i]] + (['Upper'] if mode == 1 else []),
              j1=0x80800000 | (y << 8) | x)
    x, y = stick(90, 100)
    r('Layer: L+up with the left stick at 90 degrees = discs Up-Up-Right and Right', 0, keys('L', 'up', t=3),
      ['Up-Up-Right', 'Right'], j1=0x80800000 | (y << 8) | x)
    r('Layer: L+A with the left stick at 90 degrees = disc Right and Lower-Right', 0, keys('L', 'A', t=3),
      ['Right', 'Lower-Right'], j1=0x80800000 | (y << 8) | x)
    # Keyboard
    kb = [(0x1E + i, str(i + 1)) for i in range(9)] + [(0x27, '0'), (0x28, 'Enter'), (0x2A, 'Clear'), (0x58, 'Enter')] \
        + [(0x59 + i, str(i + 1)) for i in range(9)] + [(0x62, '0')]
    for c, k in kb:
        for pos in range(6):
            j3, t3 = (c << (8 * pos), 0) if pos < 4 else (0, c << (8 * (pos - 4)))
            r(f'keyboard usage {c:02X} in byte {pos} = {k}', 0, 0, [k], k3=4 << 28, j3=j3, t3=t3)
    for c in (0x04, 0x29, 0x2B, 0x4C, 0x52, 0x63, 0x57, 0xE1):
        r(f'keyboard usage {c:02X} = nothing', 0, 0, [], k3=4 << 28, j3=c)
    r('keyboard 1 2 3 Enter Backspace 0 together', 0, 0, ['1', '2', '3', 'Enter', 'Clear', '0'],
      k3=4 << 28, j3=0x281F201E, t3=0x272A)
    r('keyboard 5 with player 1 A (Layer) = 5 and Lower-Right', 0, keys('A'), ['5', 'Lower-Right'], k3=4 << 28, j3=0x22)
    r('cont3 type 1 (a controller) is not a keyboard', 0, 0, [], k3=(1 << 28) | 0xFFFF, j3=0x1E1E1E1E, t3=0x1E1E)
    r('cont3 type 2 is not a keyboard', 0, 0, [], k3=2 << 28, j3=0x1E)
    # Slot types and player 2
    for t in (0, 4, 5, 6, 15):
        r(f'cont1 type {t} = nothing', 0, keys('A', 'up', 'R', t=t), [], j1=0)
    r('cont1 type 2 (docked digital) A = Lower-Right', 0, keys('A', t=2), ['Lower-Right'])
    r('player 2 type 2: B = Lower-Left on the other port', 0, 0, [], k2=keys('B', t=2), want2=['Lower-Left'])
    r('player 2 type 1, mode Face: X+A = 3', 1, 0, [], k2=keys('X', 'A', t=1), want2=['3'])
    r('player 2 type 2, Layer: L+left = disc Left-Up-Left', 0, 0, [], k2=keys('L', 'left', t=2),
      want2=['Left-Up-Left'])
    r('both players, Layer: L+up on player 1, up on player 2', 0, keys('L', 'up'), ['Up-Up-Right'],
      k2=keys('up', t=2), want2=['Up'])
    r('both players at once', 0, keys('up'), ['Up'], k2=keys('down', t=2), want2=['Down'])
    r('player 2 in Layer: R+Y = Clear, keyboard stays with player 1', 0, 0, ['7'], k3=4 << 28, j3=0x24,
      k2=keys('R', 'Y', t=2), want2=['Clear'])
    return rows


def l_oracle(btns, mode, stick_dir):
    """Class 9's expectation, written from the agreed mapping without the model: the MAME inputs one
    controller presses for a set of button names (D-pad, A/B/X/Y, L, R), a keypad mode and the left
    stick's direction (an index into DIRS, or None)."""
    b = set(btns)
    v = ('up' in b) - ('down' in b)
    h = ('right' in b) - ('left' in b)
    pos = {(1, 0): 0, (1, 1): 1, (0, 1): 2, (-1, 1): 3, (-1, 0): 4, (-1, -1): 5, (0, -1): 6, (1, -1): 7}
    ring = {0: '2', 1: '3', 2: '6', 3: '9', 4: '8', 5: '7', 6: '4', 7: '1'}
    out = []
    if mode == 1:                               # Face-button ring: L = Upper, no turn
        if (v, h) in pos:
            out.append(DIRS[2 * pos[(v, h)]])
        fv = ('X' in b) - ('B' in b)
        fh = ('A' in b) - ('Y' in b)
        if (fv, fh) in pos:
            out.append(ring[pos[(fv, fh)]])
        out += ['Upper'] * ('L' in b) + ['5'] * ('R' in b)
    elif 'R' in b:                              # R beats L
        if (v, h) in pos:
            out.append(ring[pos[(v, h)]])
        out += [k for btn, k in (('Y', 'Clear'), ('B', '0'), ('A', 'Enter'), ('X', '5')) if btn in b]
    else:
        turn = 1 if 'L' in b else 0             # L: only the D-pad, one notch clockwise
        if (v, h) in pos:
            out.append(DIRS[2 * pos[(v, h)] + turn])
        out += [k for btn, k in (('A', 'Lower-Right'), ('B', 'Lower-Left'), ('X', 'Upper')) if btn in b]
    if stick_dir is not None:
        out.append(DIRS[stick_dir])             # the stick is never turned
    return out


def vec_line(cls, v, r, l, keys=0):
    return '%x %08x %08x %08x %08x %08x %08x %04x %x %x %x %x %x %02x %02x %08x %08x' % (
        cls, v['key1'], v['joy1'], v['key2'], v['joy2'], v['key3'], v['joy3'], v['trig3'], v['mode'], v['swap'],
        v.get('ovr', 0), v.get('synth', 0), v.get('ecs', 0), r, l, keys >> 32, keys & 0xFFFFFFFF)


def tear_line(v, r, l):
    return '%08x %08x %08x %08x %08x %08x %04x %x %x %02x %02x' % (
        v['key1'], v['joy1'], v['key2'], v['joy2'], v['key3'], v['joy3'], v['trig3'], v['mode'], v['swap'], r, l)


def vec(key1=0, joy1=0x80808080, key2=0, joy2=0x80808080, key3=0, joy3=0, trig3=0, mode=0, swap=0, ovr=0,
        synth=0, ecs=0):
    return dict(key1=key1, joy1=joy1, key2=key2, joy2=joy2, key3=key3, joy3=joy3, trig3=trig3, mode=mode, swap=swap,
                ovr=ovr, synth=synth, ecs=ecs)


def generate(path):
    rng = random.Random(6)
    lines = []
    problems = []
    counts = {}

    def add(cls, v, want=None, want_keys=None):
        r, l = m.ports(v)
        mr, ml = m.ports(v, mame=True)
        k = m.ecs_keys(v)
        if (r, l) != (mr, ml):
            problems.append(f'class {cls}: model {r:02X} {l:02X} != MAME read_ctrl {mr:02X} {ml:02X} for {v}')
        if want is not None and want != (r, l):
            problems.append(f'class {cls}: model {r:02X} {l:02X} != expected {want[0]:02X} {want[1]:02X} for {v}')
        if want_keys is not None and want_keys != k:
            problems.append(f'class {cls}: model ECS keys {k:016X} != expected {want_keys:016X} for {v}')
        e = want if want is not None else (r, l)
        lines.append(vec_line(cls, v, *e, keys=want_keys if want_keys is not None else k))
        counts[cls] = counts.get(cls, 0) + 1

    def rkey(t=None):
        return ((rng.choice((1, 2, 3)) if t is None else t) << 28) | rng.getrandbits(16)

    # 0 spec
    for desc, mode, k1, j1, k3, j3, t3, k2, w1, w2 in spec_rows():
        for swap in (0, 1):
            v = vec(key1=k1, joy1=j1, key2=k2, key3=k3, joy3=j3, trig3=t3, mode=mode, swap=swap)
            a, b = mame_read_ctrl(w1), mame_read_ctrl(w2)
            want = (a, b) if swap else (b, a)          # (pad_r, pad_l): player 1 left unless swapped
            before = len(problems)
            add(0, v, want)
            if len(problems) > before:
                problems[-1] = f'spec "{desc}" swap {swap}: ' + problems[-1]
    # 1 every button combination, player 1 type 1
    for mode in range(4):
        for b in range(1 << 16):
            add(1, vec(key1=(1 << 28) | b, key2=rkey() if b % 3 == 0 else 0, mode=mode, swap=b & 1))
    # 2 player 2 type 2
    for b in range(1 << 16):
        add(2, vec(key2=(2 << 28) | b, mode=b % 4, swap=(b >> 3) & 1))
    # 3 left stick, whole range
    for i in range(1 << 16):
        x, y = i & 0xFF, i >> 8
        k = (3 << 28) | (rng.getrandbits(16) if i % 7 == 0 else 0)
        joy = (rng.getrandbits(16) << 16) | (y << 8) | x
        if i & 1:
            add(3, vec(key2=k, joy2=joy, mode=(i >> 1) % 4, swap=(i >> 9) & 1))
        else:
            add(3, vec(key1=k, joy1=joy, mode=(i >> 1) % 4, swap=(i >> 9) & 1))
    # 4 right stick, whole range
    for i in range(1 << 16):
        x, y = i & 0xFF, i >> 8
        mode = 2 if i % 4 else (i >> 2) % 2
        k = (3 << 28) | ((1 << m.R3) if i % 5 == 0 else 0)
        add(4, vec(key1=k, joy1=(y << 24) | (x << 16) | 0x8080, mode=mode, swap=(i >> 8) & 1))
    # 5 keyboard
    for c in range(256):
        for pos in range(6):
            j3, t3 = (c << (8 * pos), 0) if pos < 4 else (0, c << (8 * (pos - 4)))
            add(5, vec(key3=4 << 28, joy3=j3, trig3=t3, swap=c & 1))
    mapped = list(m.HID)
    for i in range(20000):
        n = rng.randint(1, 6)
        cs = [rng.choice(mapped) if rng.random() < 0.7 else rng.getrandbits(8) for _ in range(n)] + [0] * (6 - n)
        rng.shuffle(cs)
        add(5, vec(key1=rkey() if i % 2 else 0, joy1=rng.getrandbits(32), key3=(4 << 28) | rng.getrandbits(16),
                   joy3=cs[0] | cs[1] << 8 | cs[2] << 16 | cs[3] << 24, trig3=cs[4] | cs[5] << 8,
                   mode=i % 4, swap=(i >> 2) & 1))
    # 6 slot types
    for i in range(16 * 3 * 200):
        t, slot = (i // 200) % 16, i // 3200
        v = vec(key1=rkey(), joy1=rng.getrandbits(32), key2=rkey(), joy2=rng.getrandbits(32),
                key3=(rng.choice((0, 1, 2, 3, 5)) << 28) | rng.getrandbits(16), joy3=rng.getrandbits(32),
                trig3=rng.getrandbits(16), mode=i % 4, swap=(i >> 2) & 1)
        v[('key1', 'key2', 'key3')[slot]] = (t << 28) | rng.getrandbits(28)
        add(6, v)
    # 7 random
    for i in range(50000):
        add(7, vec(key1=rng.getrandbits(32), joy1=rng.getrandbits(32), key2=rng.getrandbits(32),
                   joy2=rng.getrandbits(32), key3=rng.getrandbits(32), joy3=rng.getrandbits(32),
                   trig3=rng.getrandbits(16), mode=rng.getrandbits(2), swap=rng.getrandbits(1)))
    # 8 MAME's analog grid
    for gy in range(5):
        for gx in range(5):
            if (gx, gy) == (2, 2):
                continue
            x, y = 128 + (16 + 32 * gx - 80) * 8 // 5, 128 + (16 + 32 * gy - 80) * 8 // 5
            for mode in range(4):
                for swap in (0, 1):
                    want = m.MAME_DISCYX_TABLE[gy][gx]
                    add(8, vec(key1=3 << 28, joy1=0x80800000 | (y << 8) | x, mode=mode, swap=swap),
                        (want, 0xFF) if swap else (0xFF, want))
    # 9 L + D-pad: each D-pad state (none, the 8, up+down, up+down+left) with every set of A/B/X/Y,
    # with and without L and R, in every mode, on slot types 1, 2 and 3 (type 3 with the left stick
    # centred and in each of its 16 directions), on either player, both Swap settings; the expected bytes
    # from l_oracle (the mapping written out), and the model must agree
    dstates = [()] + DPAD8 + [('up', 'down'), ('up', 'down', 'left')]
    n9 = 0
    for mode in range(4):
        for ds in dstates:
            for fb in range(16):
                face = [nm for i, nm in enumerate(('A', 'B', 'X', 'Y')) if fb >> i & 1]
                for lr in range(4):
                    sh = ['L'] * (lr & 1) + ['R'] * (lr >> 1)
                    btns = list(ds) + face + sh
                    for t, sd in [(1, None), (2, None)] + [(3, None)] + [(3, i) for i in range(16)]:
                        if t == 3 and sd is not None and (fb + lr + n9) % 4:
                            n9 += 1
                            continue
                        n9 += 1
                        joy = 0x80808080
                        if sd is not None:
                            x, y = stick(22.5 * sd, 100)
                            joy = 0x80800000 | (y << 8) | x
                        k = keys(*btns, t=t)
                        mm = 'Layer' if mode != 1 else 'Face'
                        want = mame_read_ctrl(l_oracle(btns, mode, sd))
                        p2 = n9 & 1
                        swap = (n9 >> 1) & 1
                        v = vec(key1=0 if p2 else k, joy1=0x80808080 if p2 else joy, key2=k if p2 else 0,
                                joy2=joy if p2 else 0x80808080, mode=mode, swap=swap)
                        left = swap ^ p2 == 0           # player 1 left unless swapped
                        e = (0xFF, want) if left else (want, 0xFF)
                        before = len(problems)
                        add(9, v, e)
                        if len(problems) > before:
                            problems[-1] = f'L+D-pad {mm} {"+".join(btns)} type {t} stick {sd}: ' + problems[-1]
    # 10 the ECS keyboard (step 9), written out by hand: each key of the ECS keyboard by its HID
    # usage code (ECS_SPEC) gives its switch of the matrix (MAME ecs_ctrl.cpp ROW.n, the wiki's table:
    # tools/ecs.py KEYPOS); Shift and Ctrl from either side of the modifier byte; the synthesizer's two
    # tracker rows give their notes; nothing without the ECS; the keypad keeps only the numpad with it.
    # ecs is the ECS mode (tools/ecs.py: 0 off, 1 on, 2 attached): only mode on (1) takes the keyboard
    # (step 9 review); attached is the 0.0.8 keypad with no matrix key, like off
    import ecs as ecsm
    kb = 4 << 28
    for name, code in ECS_SPEC.items():
        r_, c_ = ecsm.KEYPOS[name]
        for pos in range(6):
            j3, t3 = (code << (8 * pos), 0) if pos < 4 else (0, code << (8 * (pos - 4)))
            add(10, vec(key3=kb, joy3=j3, trig3=t3, ecs=1, ovr=pos % 3), (0xFF, 0xFF), 1 << (8 * r_ + c_))
            add(10, vec(key3=kb, joy3=j3, trig3=t3, ecs=0, swap=pos & 1), None, 0)
            add(10, vec(key3=kb, joy3=j3, trig3=t3, ecs=2, swap=pos & 1, synth=pos & 1), None, 0)
    for mod, name in ((0x02, 'SHIFT'), (0x20, 'SHIFT'), (0x01, 'CTL'), (0x10, 'CTL')):
        r_, c_ = ecsm.KEYPOS[name]
        add(10, vec(key3=kb | mod, ecs=1), (0xFF, 0xFF), 1 << (8 * r_ + c_))
        add(10, vec(key3=kb | mod, ecs=1, synth=1), (0xFF, 0xFF), 0)
        add(10, vec(key3=kb | mod, ecs=2), (0xFF, 0xFF), 0)
    for code, note in SYNTH_SPEC:
        add(10, vec(key3=kb, joy3=code, ecs=1, synth=1), (0xFF, 0xFF), 1 << note)
        add(10, vec(key3=kb, trig3=code << 8, ecs=1, synth=1, ovr=2), (0xFF, 0xFF), 1 << note)
        add(10, vec(key3=kb, joy3=code, ecs=2, synth=1), None, 0)
    # with the ECS the numpad stays the keypad (numpad . = Clear) and the number row, Enter and
    # Backspace do not; written out with MAME's keypad names
    for code, key in ((0x59, '1'), (0x61, '9'), (0x62, '0'), (0x58, 'Enter'), (0x63, 'Clear')):
        w = mame_read_ctrl([key])
        add(10, vec(key3=kb, joy3=code, ecs=1), (0xFF, w), 0)
        add(10, vec(key3=kb, joy3=code, ecs=1, swap=1), (w, 0xFF), 0)
    for code in (0x1E, 0x27, 0x28, 0x2A):
        add(10, vec(key3=kb, joy3=code, ecs=1), (0xFF, 0xFF), None)
    # with the ECS attached (Auto's mode for most games) the number row, Enter and Backspace are the
    # keypad as in 0.0.8 (and with the ECS off), written out with MAME's keypad names; no matrix key
    for code, key in ((0x1E, '1'), (0x26, '9'), (0x27, '0'), (0x28, 'Enter'), (0x2A, 'Clear'), (0x59, '1'),
                      (0x58, 'Enter')):
        w = mame_read_ctrl([key])
        for e in (0, 2):
            add(10, vec(key3=kb, joy3=code, ecs=e), (0xFF, w), 0)
            add(10, vec(key3=kb, trig3=code << 8, ecs=e, swap=1, synth=1), (w, 0xFF), 0)
    add(10, vec(key3=kb, joy3=0x63, ecs=2), (0xFF, 0xFF), 0)      # numpad . is Clear only with the ECS on
    # 11 every usage code in each report byte, with and without the ECS and the synthesizer; random
    # reports of up to six keys with modifiers (expected: the model)
    for c in range(256):
        for pos in range(6):
            j3, t3 = (c << (8 * pos), 0) if pos < 4 else (0, c << (8 * (pos - 4)))
            for e in (1, 2):
                add(11, vec(key3=kb | rng.getrandbits(8), joy3=j3, trig3=t3, ecs=e, synth=(c + pos) & 1,
                            swap=c & 1, ovr=pos % 3))
    for i in range(20000):
        n = rng.randint(1, 6)
        cs = [rng.choice(list(m.ECS_HID) + list(m.SYNTH_HID) + list(m.HID_ECS)) if rng.random() < 0.8
              else rng.getrandbits(8) for _ in range(n)] + [0] * (6 - n)
        rng.shuffle(cs)
        add(11, vec(key1=rkey() if i % 2 else 0, joy1=rng.getrandbits(32), key3=kb | rng.getrandbits(16),
                    joy3=cs[0] | cs[1] << 8 | cs[2] << 16 | cs[3] << 24, trig3=cs[4] | cs[5] << 8,
                    mode=i % 4, swap=(i >> 2) & 1, ecs=(i >> 3) % 3, synth=(i >> 4) & 1, ovr=i % 3))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return counts, problems


# The ECS keyboard by USB HID usage code (step 9), written out from the HID usage tables (keyboard
# page 0x07: a-z = 0x04-0x1D, 1-9 = 0x1E-0x26, 0 = 0x27, Enter 0x28, Esc 0x29, Backspace 0x2A,
# Space 0x2C, ; 0x33, , 0x36, . 0x37, Right 0x4F, Left 0x50, Down 0x51, Up 0x52): the ECS key each
# PC key is (tools/ecs.py KEYPOS names). Backspace is the ECS left arrow too (BS below).
ECS_SPEC = dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ', range(0x04, 0x1E)))
ECS_SPEC.update(zip('123456789', range(0x1E, 0x27)))
ECS_SPEC.update({'0': 0x27, 'RTN': 0x28, 'ESC': 0x29, 'SPACE': 0x2C, ';': 0x33, ',': 0x36, '.': 0x37,
                 'RIGHT': 0x4F, 'LEFT': 0x50, 'DOWN': 0x51, 'UP': 0x52})
# the synthesizer's tracker rows: (HID usage, note; 0 = C2): Z S X D C V G B H N J M = C3-B3,
# Q 2 W 3 E R 5 T 6 Y 7 U I = C4-C5
SYNTH_SPEC = list(zip((0x1D, 0x16, 0x1B, 0x07, 0x06, 0x19, 0x0A, 0x05, 0x0B, 0x11, 0x0D, 0x10), range(12, 24)))
SYNTH_SPEC += list(zip((0x14, 0x1F, 0x1A, 0x20, 0x08, 0x15, 0x22, 0x17, 0x23, 0x1C, 0x24, 0x18, 0x0C), range(24, 37)))


def generate_tear(path, groups=2000):
    """Groups of vectors for the crossing check: 'n' then n vector lines."""
    rng = random.Random(66)
    hid_keys = sorted(m.HID)
    out = []
    kinds = {}

    def vline(v):
        r, l = m.ports(v)
        return tear_line(v, r, l), (r, l)

    def btn(t=None):
        return ((rng.choice((1, 2, 3)) if t is None else t) << 28) | rng.getrandbits(16)

    g = 0
    while g < groups:
        kind = g % 6
        n = rng.randint(2, 4)
        vs = []
        if kind == 0:       # keyboard: usage codes in one or two report bytes
            pos = rng.sample(range(6), rng.randint(1, 2))
            for _ in range(n):
                cs = [0] * 6
                for p_ in pos:
                    cs[p_] = rng.choice(hid_keys)
                vs.append(vec(key3=4 << 28, joy3=cs[0] | cs[1] << 8 | cs[2] << 16 | cs[3] << 24,
                              trig3=cs[4] | cs[5] << 8))
            if g % 12 == 0:  # the review's example: 1E '1' and 21 '4'
                vs = [vec(key3=4 << 28, joy3=0x1E), vec(key3=4 << 28, joy3=0x21)]
        elif kind == 1:     # buttons on both players
            for _ in range(n):
                vs.append(vec(key1=btn(), key2=btn(), mode=rng.getrandbits(2), swap=g & 1))
        elif kind == 2:     # the settings: Keypad Mode 1 and 2, Swap
            k1, k2 = btn(1) | (1 << m.R1), btn(2)
            j1 = rng.getrandbits(32)
            vs = [vec(key1=k1, joy1=j1, key2=k2, mode=md, swap=sw) for md, sw in ((1, 0), (2, 1), (1, 1), (2, 0))][:n]
        elif kind == 3:     # sticks (docked analog)
            for _ in range(n):
                vs.append(vec(key1=btn(3), joy1=rng.getrandbits(32), key2=btn(3), joy2=rng.getrandbits(32),
                              mode=2, swap=g & 1))
        elif kind == 4:     # slot types change under the same buttons
            b = rng.getrandbits(16)
            for _ in range(n):
                vs.append(vec(key1=(rng.randrange(16) << 28) | b, key3=(rng.choice((0, 1, 4)) << 28),
                              joy3=0x1E1F2021, mode=rng.getrandbits(2)))
        else:               # everything random
            for _ in range(n):
                vs.append(vec(key1=rng.getrandbits(32), joy1=rng.getrandbits(32), key2=rng.getrandbits(32),
                              joy2=rng.getrandbits(32), key3=rng.getrandbits(32), joy3=rng.getrandbits(32),
                              trig3=rng.getrandbits(16), mode=rng.getrandbits(2), swap=rng.getrandbits(1)))
        lines = [vline(v) for v in vs]
        if len(set(e for _, e in lines)) < 2:
            continue
        out.append('%x' % len(lines))
        out += [ln for ln, _ in lines]
        kinds[kind] = kinds.get(kind, 0) + 1
        g += 1
    with open(path, 'w') as f:
        f.write('\n'.join(out) + '\n')
    return kinds


SKEW_DECL = ("    localparam int W = 6 * 32 + 16 + 2 + 1 + 3;\n",
             "    localparam int W = 6 * 32 + 16 + 2 + 1 + 3;\n"
             "    logic [W-1:0] hold_v;      // tb_input skew build: the clk side's view of hold_74\n"
             "    logic         req_v;       // and of req_74, driven by tb_input.sv\n")
CLK_BLOCK = re.compile(r'(    always_ff @\(posedge clk\) begin\n)(.*?)(\n    end\n)', re.S)


def skew_view(src):
    """The skew build's intv_input.sv: in the always_ff @(posedge clk) blocks, hold_74 and req_74 become the
    views hold_v and req_v. Returns (text, number of references replaced)."""
    n = 0

    def sub(mo):
        nonlocal n
        body, k1 = re.subn(r'\bhold_74\b', 'hold_v', mo.group(2))
        body, k2 = re.subn(r'\breq_74\b', 'req_v', body)
        n += k1 + k2
        return mo.group(1) + body + mo.group(3)
    if src.count(SKEW_DECL[0]) != 1:
        return src, -1
    src = src.replace(SKEW_DECL[0], SKEW_DECL[1])
    return CLK_BLOCK.sub(sub, src), n


def build(work, rtl_dir, verilator, strict=True, defines=()):
    obj = os.path.join(work, 'obj')
    os.makedirs(work, exist_ok=True)
    # --verilate-jobs 1: Verilator 5.040's multithreaded verilation (what -j N turns on besides --build-jobs)
    # crashed about one build in 16 with "internal fault" (2026-10-28: 5 of 80 with -j 2, 0 of 210 with one)
    cmd = [verilator, '--binary', '--timing', '--verilate-jobs', '1', '--build-jobs', '2', '-Wall', '-Wno-fatal', '-Wno-TIMESCALEMOD',
           '-Wno-PROCASSINIT', '--top-module', 'tb_input', '-Mdir', obj, '-o', 'tb_input']
    cmd += ['-D' + d for d in defines]
    cmd += [os.path.join(rtl_dir, f) for f in RTL] + [TB]
    log = os.path.join(work, 'build.log')
    with open(log, 'w') as f:
        r = subprocess.run(cmd + tbcommon.VL_MAKEFLAGS, stdout=f, stderr=subprocess.STDOUT, env=tbcommon.vl_env())
    text = open(log).read()
    if r.returncode != 0:
        print(text[-4000:])
        return None
    ours = [ln for ln in text.splitlines() if ln.startswith('%Warning') and any(('/' + f + ':') in ln for f in RTL)]
    if ours and strict:
        print('\n'.join(ours[:20]))
        return None
    return os.path.join(obj, 'tb_input')


def run(binary, vectors, tear, log):
    args = [binary] + (['+vec=' + vectors] if vectors else []) + ['+tear=' + tear]
    with open(log, 'w') as f:
        subprocess.run(args, stdout=f, stderr=subprocess.STDOUT)
    text = open(log).read()
    return 'TB_INPUT pass' in text.splitlines(), text


# Planted faults: (name, file, from, to), or (name, file, [(from, to), ...], None); each must make the
# bench fail.
PLANTS = [
    ('swap_ignored', 'intv_input.sv', 'pad_l <= ~(sw ? p2 : p1);', 'pad_l <= ~p1;'),
    ('disc_ssw', 'intv_input.sv', "4'd9:  disc_code = 8'h11;", "4'd9:  disc_code = 8'h19;"),
    ('deadzone_le', 'intv_input.sv', '< 17\'(DZ_DISC * DZ_DISC)', '<= 17\'(DZ_DISC * DZ_DISC)'),
    ('slope_171', 'intv_input.sv', "b171  = 18'(b) * 18'd171;", "b171  = 18'(b) * 18'd180;"),
    ('y_flipped', 'intv_input.sv', "d = dy[8] ? 4'(k) : 4'(4'd8 - 4'(k));", "d = !dy[8] ? 4'(k) : 4'(4'd8 - 4'(k));"),
    ('l_beats_r', 'intv_input.sv', '            if (r1)                                             // R: the number pad\n',
     '            if (r1 && !l1)                                      // R: the number pad\n'),
    # the owner's mapping of 2026-11-03: R + A = Enter (not 1 as until 0.0.21), L leaves A/B/X alone
    ('r_keys_old', 'intv_input.sv', "(ba ? K_ENTER : 8'h00)", "(ba ? key_code(4'd1) : 8'h00)"),
    ('l_chord_back', 'intv_input.sv', "(ba ? side_code(sides[1:0]) : 8'h00)",
     "(ba ? (l1 ? key_code(4'd5) : side_code(sides[1:0])) : 8'h00)"),
    ('ring_nocancel', 'intv_input.sv', "uu = u & ~d;  dd = d & ~u;  ll = l & ~r;  rr = r & ~l;\n        unique case ({uu, dd, ll, rr})\n            4'b1010: ring_code",
     "uu = u;  dd = d & ~u;  ll = l & ~r;  rr = r & ~l;\n        unique case ({uu, dd, ll, rr})\n            4'b1010: ring_code"),
    ('face_lr_swapped', 'intv_input.sv', 'ring_code(bx, bb, by, ba)', 'ring_code(bx, bb, ba, by)'),
    ('backspace', 'intv_input.sv', "c == 8'h2A", "c == 8'h2B"),
    ('kbd_any_type', 'intv_input.sv', "k3[31:28] == 4'd4", "k3[31:28] != 4'd0"),
    ('kbd_5_bytes', 'intv_input.sv', "default: hc = t3[15:8];", "default: hc = 8'h00;"),
    ('type_any', 'intv_input.sv', "(t == 4'd1 || t == 4'd2 || t == 4'd3) ? p", "(t != 4'd0) ? p"),
    ('no_r3', 'intv_input.sv', "| (r3 ? key_code(4'd5) : 8'h00)", "| (1'b0 ? key_code(4'd5) : 8'h00)"),
    ('rstick_any_mode', 'intv_input.sv', "if (mode == 2'd2 && an)", 'if (an)'),
    # L + D-pad (Precision controls): the turn the wrong way (counter-clockwise); no turn (as before
    # 0.0.7); L turning the D-pad in Face-button ring too; an L chord (A/B/X) dropping the disc, or undoing
    # the turn; L turning the left stick as well; the turn by two notches
    ('turn_ccw', 'intv_input.sv', "disc_code(k + {3'b000, turn})", "disc_code(k - {3'b000, turn})"),
    ('turn_none', 'intv_input.sv', "p = dpad_code(up, dn, lt, rt, l1)", "p = dpad_code(up, dn, lt, rt, 1'b0)"),
    ('turn_in_face', 'intv_input.sv', "p = dpad_code(up, dn, lt, rt, 1'b0) | ring_code(bx, bb, by, ba)",
     "p = dpad_code(up, dn, lt, rt, l1) | ring_code(bx, bb, by, ba)"),
    ('chord_drops_disc', 'intv_input.sv', "p = dpad_code(up, dn, lt, rt, l1)",
     "p = ((ba | bb | bx) ? 8'h00 : dpad_code(up, dn, lt, rt, l1))"),
    ('chord_unturns', 'intv_input.sv', "p = dpad_code(up, dn, lt, rt, l1)",
     "p = dpad_code(up, dn, lt, rt, l1 & !(ba | bb | bx))"),
    ('turn_two', 'intv_input.sv', "disc_code(k + {3'b000, turn})", "disc_code(k + {2'b00, turn, 1'b0})"),
    ('turn_stick', 'intv_input.sv',
     [("function automatic logic [7:0] stick16_code(input logic [7:0] x, input logic [7:0] y);",
       "function automatic logic [7:0] stick16_code(input logic [7:0] x, input logic [7:0] y, input logic turn);"),
      ("stick16_code = disc_code(d);", "stick16_code = disc_code(d + 4'(turn));"),
      ("p = p | stick16_code(joy[7:0], joy[15:8]);",
       "p = p | stick16_code(joy[7:0], joy[15:8], mode != 2'd1 && l1 && !r1);")], None),
    ('stick_on_pocket', 'intv_input.sv', "an = t == 4'd3;", "an = t[1];"),
    # step 9, the ECS keyboard: Shift on the wrong switch; Backspace not the left arrow; the number row
    # still the keypad with the ECS; the synthesizer an octave off; right Ctrl ignored; the keys sent
    # without the ECS; the ECS setting's bits swapped
    ('ecs_shift_pos', 'intv_input.sv', "? 64'd1 << 55 : 64'd0)", "? 64'd1 << 54 : 64'd0)"),
    ('ecs_bs_none', 'intv_input.sv', "8'h50: p = 7'd0;   8'h2A: p = 7'd0;", "8'h50: p = 7'd0;"),
    ('ecs_numrow_keypad', 'intv_input.sv', "ecs_full ? hid_code_ecs(hc) : hid_code(hc)",
     "ecs_full ? (ph == 3'd0 ? hid_code(hc) : hid_code_ecs(hc)) : hid_code(hc)"),
    ('synth_octave', 'intv_input.sv', "8'h1D: n = 7'd12;", "8'h1D: n = 7'd24;"),
    ('ecs_rctrl', 'intv_input.sv', "&& (k3[0] | k3[4]) ?", "&& (k3[0]) ?"),
    ('ecs_always', 'intv_input.sv', "(kbd && ecs_full && !sp[6]", "(kbd && !sp[6]"),
    # the step-9 review: with the ECS attached (or off) the keyboard is the 0.0.8 keypad; a core that
    # gives it the ECS's numpad-only mapping there loses the number row, Enter and Backspace
    ('attached_numpad_only', 'intv_input.sv', "ecs_full ? hid_code_ecs(hc) : hid_code(hc)", "hid_code_ecs(hc)"),
    ('ecs_mods_always', 'intv_input.sv', "(kbd && ecs_full && !sy && (k3[1] | k3[5])", "(kbd && !sy && (k3[1] | k3[5])"),
    # the decode round: a word loaded at any step (the outputs mix two words: the tear check)
    ('round_any_load', 'intv_input.sv', "if (req_s[1] != ack && ph == 3'd7) begin", "if (req_s[1] != ack) begin"),
    ('ovr_swapped', 'intv_input.sv', "    assign ecs_ovr   = eo;", "    assign ecs_ovr   = {eo[0], eo[1]};"),
    # the crossing as it was before 0.0.5: every bit through two clk flip-flops on its own
    ('bitwise_sync', 'intv_input.sv',
     [("    logic [W-1:0] word;\n", "    logic [W-1:0] word, w_s;\n    initial w_s = '0;\n"),
      ("        if (req_s[1] != ack && ph == 3'd7) begin\n            word <= hold_74;\n            ack  <= req_s[1];\n        end\n",
       "        w_s  <= in_74;\n        word <= w_s;\n        ack  <= req_s[1];\n")], None),
    # handshake faults the input skew alone cannot show (the step-6 review of 0.0.5): the copy retaken at
    # every clk_74a edge, so it can change while clk loads it; a registered copy crossed bit by bit
    ('copy_while_in_flight', 'intv_input.sv',
     "        if (ack_74[1] == req_74) begin\n            hold_74 <= in_74;\n            req_74  <= !req_74;\n        end\n",
     "        hold_74 <= in_74;\n        req_74  <= !req_74;\n"),
    ('reg_then_bitwise', 'intv_input.sv',
     [("    logic [W-1:0] word;\n", "    logic [W-1:0] word, w_s;\n    initial w_s = '0;\n"),
      ("        if (ack_74[1] == req_74) begin\n            hold_74 <= in_74;\n            req_74  <= !req_74;\n        end\n",
       "        hold_74 <= in_74;\n"),
      ("        if (req_s[1] != ack && ph == 3'd7) begin\n            word <= hold_74;\n            ack  <= req_s[1];\n        end\n",
       "        w_s  <= hold_74;\n        word <= w_s;\n")], None),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--all', action='store_true', help='vectors, RTL, then the planted faults')
    ap.add_argument('--no-build', action='store_true')
    ap.add_argument('--plant', help='comma-separated plant names (with --all)')
    a = ap.parse_args()
    verilator = os.environ.get('VERILATOR', 'verilator')
    work = os.environ.get('WORK', os.path.join(ROOT, 'sim', 'work', 'tb_input'))
    fails = []

    print('-- model self-check (tools/intv_input.py)')
    if m.self_check():
        fails.append('model self-check')
    print('-- vectors')
    vectors = os.path.join(work, 'vectors.txt')
    counts, problems = generate(vectors)
    for p in problems[:20]:
        print('  FAIL  ' + p)
    if problems:
        fails.append(f'{len(problems)} model problems')
    print(('  ok    ' if not problems else '  FAIL  ') +
          f'{sum(counts.values())} vectors {dict(sorted(counts.items()))}: model = MAME read_ctrl on every one, '
          f'spec rows and MAME analog cells as expected')

    tear = os.path.join(work, 'tear.txt')
    kinds = generate_tear(tear)
    print(f'  ok    {sum(kinds.values())} crossing groups {dict(sorted(kinds.items()))}')

    print('-- RTL')
    binary = os.path.join(work, 'obj', 'tb_input')
    if not a.no_build:
        binary = build(work, CORE, verilator)
    if not binary:
        fails.append('build')
    else:
        ok, text = run(binary, vectors, tear, os.path.join(work, 'run.log'))
        print('\n'.join(ln for ln in text.splitlines() if ln.strip() and not ln.startswith('- ')))
        if not ok:
            fails.append('RTL')

        print('-- RTL, skew build')
        d = os.path.join(work, 'skew')
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(os.path.join(d, 'rtl'))
        s, n = skew_view(open(os.path.join(CORE, 'intv_input.sv')).read())
        if n < 2:
            print(f'  FAIL  skew view: {n} references of hold_74 / req_74 in the clk blocks')
            fails.append('skew view')
        else:
            open(os.path.join(d, 'rtl', 'intv_input.sv'), 'w').write(s)
            b = build(d, os.path.join(d, 'rtl'), verilator, strict=False, defines=['TB_SKEW'])
            if not b:
                fails.append('skew build')
            else:
                ok, text = run(b, None, tear, os.path.join(d, 'run.log'))
                print('\n'.join(ln for ln in text.splitlines() if ln.strip() and not ln.startswith('- ')))
                if not ok:
                    fails.append('RTL skew')

    if a.all and not fails:
        print('-- planted faults')
        names = a.plant.split(',') if a.plant else None
        for name, fn, frm, to in PLANTS:
            if names and name not in names:
                continue
            d = os.path.join(work, 'plant_' + name)
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(os.path.join(d, 'rtl'))
            for f in RTL:
                shutil.copy(os.path.join(CORE, f), os.path.join(d, 'rtl', f))
            p = os.path.join(d, 'rtl', fn)
            s = open(p).read()
            subs = frm if isinstance(frm, list) else [(frm, to)]
            bad = [x for x, _ in subs if s.count(x) != 1]
            if bad:
                print(f'  FAIL  PLANT {name}: pattern found {s.count(bad[0])} times')
                fails.append('plant ' + name)
                continue
            for x, y in subs:
                s = s.replace(x, y)
            s, n = skew_view(s)
            if n < 0:
                print(f'  FAIL  PLANT {name}: no place for the skew views')
                fails.append('plant ' + name)
                continue
            open(p, 'w').write(s)
            b = build(d, os.path.join(d, 'rtl'), verilator, strict=False, defines=['TB_SKEW'])
            if not b:
                print(f'  FAIL  PLANT {name}: build failed')
                fails.append('plant ' + name)
                continue
            ok, text = run(b, vectors, tear, os.path.join(d, 'run.log'))
            first = next((ln.strip()[6:90] for ln in text.splitlines() if ln.strip().startswith('FAIL')), '')
            if ok:
                print(f'  FAIL  PLANT {name}: not caught')
                fails.append('plant ' + name)
            else:
                print(f'  ok    PLANT {name}: caught: {first}')
            shutil.rmtree(os.path.join(d, 'obj'), ignore_errors=True)

    print('TB_INPUT_ALL ' + ('pass' if not fails else 'FAIL (%s)' % ', '.join(fails)))
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
