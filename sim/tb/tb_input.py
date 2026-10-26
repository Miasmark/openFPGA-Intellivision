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
     the expected byte is that table's entry.
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
"""
import argparse
import os
import random
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import intv_input as m  # noqa: E402

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
            r(f'{L}: L + D-pad {"+".join(d)} = disc {DIRS[2 * i]}', mode, keys('L', *d), [DIRS[2 * i]])
        r(f'{L}: up+down = nothing', mode, keys('up', 'down'), [])
        r(f'{L}: left+right = nothing', mode, keys('left', 'right'), [])
        r(f'{L}: up+down+left = disc Left', mode, keys('up', 'down', 'left'), ['Left'])
        r(f'{L}: R + up+down+left+right = nothing', mode, keys('R', 'up', 'down', 'left', 'right'), [])
        r(f'{L}: A = Lower-Right', mode, keys('A'), ['Lower-Right'])
        r(f'{L}: B = Lower-Left', mode, keys('B'), ['Lower-Left'])
        r(f'{L}: X = Upper', mode, keys('X'), ['Upper'])
        r(f'{L}: Y alone = nothing', mode, keys('Y'), [])
        r(f'{L}: A+B+X = three side actions', mode, keys('A', 'B', 'X'), ['Lower-Right', 'Lower-Left', 'Upper'])
        r(f'{L}: R+A = 1', mode, keys('R', 'A'), ['1'])
        r(f'{L}: R+B = 2', mode, keys('R', 'B'), ['2'])
        r(f'{L}: R+X = 3', mode, keys('R', 'X'), ['3'])
        r(f'{L}: R+Y = Enter', mode, keys('R', 'Y'), ['Enter'])
        r(f'{L}: R alone = nothing', mode, keys('R'), [])
        r(f'{L}: L+A = 5', mode, keys('L', 'A'), ['5'])
        r(f'{L}: L+B = Clear', mode, keys('L', 'B'), ['Clear'])
        r(f'{L}: L+X = 0', mode, keys('L', 'X'), ['0'])
        r(f'{L}: L+Y = nothing', mode, keys('L', 'Y'), [])
        r(f'{L}: L+R+A = 1 (R beats L)', mode, keys('L', 'R', 'A'), ['1'])
        r(f'{L}: R+up+A = keys 2 and 1 together', mode, keys('R', 'up', 'A'), ['2', '1'])
        r(f'{L}: up+A = disc Up and Lower-Right together', mode, keys('up', 'A'), ['Up', 'Lower-Right'])
        r(f'{L}: Start, Select, L2, R2, L3, R3 = nothing', mode, keys('Start', 'Select', 'L2', 'R2', 'L3', 'R3'), [])
    L = 'Face-button ring'
    for desc, ks, want in [('X = 2', ('X',), ['2']), ('B = 8', ('B',), ['8']), ('Y = 4', ('Y',), ['4']),
                           ('A = 6', ('A',), ['6']), ('X+A = 3', ('X', 'A'), ['3']), ('X+Y = 1', ('X', 'Y'), ['1']),
                           ('B+A = 9', ('B', 'A'), ['9']), ('B+Y = 7', ('B', 'Y'), ['7']),
                           ('X+B = nothing', ('X', 'B'), []), ('Y+A = nothing', ('Y', 'A'), []),
                           ('X+B+A = 6', ('X', 'B', 'A'), ['6']),
                           ('L = Upper', ('L',), ['Upper']), ('R = 5', ('R',), ['5']),
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
    r('Right stick: R+A = 1 (Layer kept)', 2, keys('R', 'A', t=3), ['1'])
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
    r('both players at once', 0, keys('up'), ['Up'], k2=keys('down', t=2), want2=['Down'])
    r('player 2 in Layer: R+Y = Enter, keyboard stays with player 1', 0, 0, ['7'], k3=4 << 28, j3=0x24,
      k2=keys('R', 'Y', t=2), want2=['Enter'])
    return rows


def vec_line(cls, v, r, l):
    return '%x %08x %08x %08x %08x %08x %08x %04x %x %x %02x %02x' % (
        cls, v['key1'], v['joy1'], v['key2'], v['joy2'], v['key3'], v['joy3'], v['trig3'], v['mode'], v['swap'], r, l)


def vec(key1=0, joy1=0x80808080, key2=0, joy2=0x80808080, key3=0, joy3=0, trig3=0, mode=0, swap=0):
    return dict(key1=key1, joy1=joy1, key2=key2, joy2=joy2, key3=key3, joy3=joy3, trig3=trig3, mode=mode, swap=swap)


def generate(path):
    rng = random.Random(6)
    lines = []
    problems = []
    counts = {}

    def add(cls, v, want=None):
        r, l = m.ports(v)
        mr, ml = m.ports(v, mame=True)
        if (r, l) != (mr, ml):
            problems.append(f'class {cls}: model {r:02X} {l:02X} != MAME read_ctrl {mr:02X} {ml:02X} for {v}')
        if want is not None and want != (r, l):
            problems.append(f'class {cls}: model {r:02X} {l:02X} != expected {want[0]:02X} {want[1]:02X} for {v}')
        e = want if want is not None else (r, l)
        lines.append(vec_line(cls, v, *e))
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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return counts, problems


def generate_tear(path, groups=2000):
    """Groups of vectors for the crossing check: 'n' then n vector lines."""
    rng = random.Random(66)
    hid_keys = sorted(m.HID)
    out = []
    kinds = {}

    def vline(v):
        r, l = m.ports(v)
        return vec_line(0, v, r, l).split(' ', 1)[1], (r, l)

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


def build(work, rtl_dir, verilator, strict=True):
    obj = os.path.join(work, 'obj')
    os.makedirs(work, exist_ok=True)
    cmd = [verilator, '--binary', '--timing', '-j', '2', '-Wall', '-Wno-fatal', '-Wno-TIMESCALEMOD',
           '-Wno-PROCASSINIT', '--top-module', 'tb_input', '-Mdir', obj, '-o', 'tb_input']
    cmd += [os.path.join(rtl_dir, f) for f in RTL] + [TB]
    log = os.path.join(work, 'build.log')
    with open(log, 'w') as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
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
    with open(log, 'w') as f:
        subprocess.run([binary, '+vec=' + vectors, '+tear=' + tear], stdout=f, stderr=subprocess.STDOUT)
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
    ('l_beats_r', 'intv_input.sv', '            if (r1)\n', '            if (r1 && !l1)\n'),
    ('ring_nocancel', 'intv_input.sv', "uu = u & ~d;  dd = d & ~u;  ll = l & ~r;  rr = r & ~l;\n        unique case ({uu, dd, ll, rr})\n            4'b1010: ring_code",
     "uu = u;  dd = d & ~u;  ll = l & ~r;  rr = r & ~l;\n        unique case ({uu, dd, ll, rr})\n            4'b1010: ring_code"),
    ('face_lr_swapped', 'intv_input.sv', 'ring_code(bx, bb, by, ba)', 'ring_code(bx, bb, ba, by)'),
    ('backspace', 'intv_input.sv', "c == 8'h2A", "c == 8'h2B"),
    ('kbd_any_type', 'intv_input.sv', "k3[31:28] == 4'd4", "k3[31:28] != 4'd0"),
    ('kbd_5_bytes', 'intv_input.sv', ' | hid_code(t3[15:8]);', ';'),
    ('type_any', 'intv_input.sv', "(t == 4'd1 || t == 4'd2 || t == 4'd3) ? p", "(t != 4'd0) ? p"),
    ('no_r3', 'intv_input.sv', "| (r3 ? key_code(4'd5) : 8'h00)", ''),
    ('rstick_any_mode', 'intv_input.sv', "if (mode == 2'd2 && an)", 'if (an)'),
    ('stick_on_pocket', 'intv_input.sv', "an = t == 4'd3;", "an = t[1];"),
    # the crossing as it was before 0.0.5: every bit through two clk flip-flops on its own
    ('bitwise_sync', 'intv_input.sv',
     [("    logic [W-1:0] word;\n", "    logic [W-1:0] word, w_s;\n    initial w_s = '0;\n"),
      ("        if (req_s[1] != ack) begin\n            word <= hold_74;\n            ack  <= req_s[1];\n        end\n",
       "        w_s  <= in_74;\n        word <= w_s;\n        ack  <= req_s[1];\n")], None),
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
            open(p, 'w').write(s)
            b = build(d, os.path.join(d, 'rtl'), verilator, strict=False)
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
