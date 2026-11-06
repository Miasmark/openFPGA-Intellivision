#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Step-13 bench driver: the on-screen keypads, the on-screen ECS keyboard (1.0.4), Auto mode and
the game profiles (intv_input's keypads and keyboard, intv_profile, intv_osk_draw;
sim/tb/tb_osk.sv) against tools/osk.py and tools/intv_input.py, frame by frame: both pad bytes,
the ECS matrix's pressed keys, and every overlay pixel of every frame.

  python3 -I sim/tb/tb_osk.py --all       the gate: the frames, then the planted faults
  python3 -I sim/tb/tb_osk.py [--no-build] [--frames N]

Frames (one vector each: both controllers' words, Keypad Mode, Swap, the cartridge's CRC, the
ECS fully on and the synthesizer setting):
  spec    written out by hand: opening and closing (Select, B, Select again, a slot that is not
          a controller), the cursor in every direction with wrapping, A pressed, held while the
          cursor moves, let go; the close's masked buttons until they are let go; both players'
          keypads at once (player 2's label one row up); every profile's cells, so every label
          is drawn; Auto with and without a profile (its mode, its A / B / X), the fixed modes,
          Swap; the ECS keyboard: Start with the ECS on, every direction with the wraps and
          row 4's key-by-key moves, every key pressed (with Y and X: SHIFT and CTL), held while
          the cursor moves, B and Start closing it and the masks after, Start with the ECS off,
          attached or the synthesizer set, Start with a keypad open or opening in that frame,
          Select while it is open, the ECS turned off and a non-controller while it is open;
  random  random button words (Select, Start, A, B and the D-pad more often), slot types, modes,
          Swap, the ECS state, the CRC now and then.
For every frame the model steps both keypads and the keyboard (tools/osk.py step_all), gives the
pad bytes (intv_input.ports with the keypads, the keyboard and the profile), the ECS keys
(intv_input.ecs_keys with the keyboard) and draws the overlay (osk.draw); the bench must give the
same bytes, the same keys and exactly the same pixels.
"""
import argparse
import os
import random
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import intv_input as im  # noqa: E402
import osk  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, 'sim', 'tb'))
import tbcommon  # noqa: E402

CORE = os.path.join(ROOT, 'src', 'fpga', 'core')
RTL = ['intv_input.sv', 'intv_profile.sv', 'intv_osk_draw.sv']
TB = os.path.join(ROOT, 'sim', 'tb', 'tb_osk.sv')
T1, T2, T3 = 1 << 28, 2 << 28, 3 << 28
CENTRE = 0x80808080
CRCS = [c for p in osk.PROFILES for c in p['crcs']]
NOPROF = 0x12345678


def btn(*names):
    m = {'up': osk.UP, 'down': osk.DOWN, 'left': osk.LEFT, 'right': osk.RIGHT, 'A': osk.A, 'B': osk.B,
         'X': osk.X, 'Y': osk.Y, 'L': osk.L1, 'R': osk.R1, 'sel': osk.SELECT, 'start': osk.START}
    return sum(1 << m[n] for n in names)


def frame(k1=T1, k2=0, mode=0, swap=0, crc=NOPROF, j1=CENTRE, j2=CENTRE, ecs=0):
    """ecs: bit 0 the ECS fully on, bit 1 the synthesizer setting"""
    return dict(key1=k1, joy1=j1, key2=k2, joy2=j2, mode=mode, swap=swap, crc=crc, ecs=ecs)


def spec_frames():
    fr = []

    def tap(*names, base=T1, n=0, **kw):
        """press then release (two frames) on player n + 1"""
        for b in (btn(*names), 0):
            fr.append(frame(**{('k1' if n == 0 else 'k2'): base | b, **kw}))

    fr.append(frame())
    tap('sel')                                              # open
    for d in ('up', 'up', 'up', 'up', 'left', 'left', 'left', 'right', 'down', 'right', 'down'):
        tap(d)                                              # every direction, wrapping
    fr += [frame(k1=T1 | btn('A'))] * 3                     # A held: the key held
    fr += [frame(k1=T1 | btn('A', 'right'))]                # the cursor moves, the key stays
    fr += [frame(k1=T1 | btn('A'))] * 2
    fr += [frame(k1=T1)]
    fr += [frame(k1=T1 | btn('X', 'Y', 'L', 'R', 'start'))] * 2     # masked while open
    fr += [frame(k1=T1)]
    fr += [frame(k1=T1 | btn('B', 'A'))]                    # close with B: A and B masked
    fr += [frame(k1=T1 | btn('B'))] * 2
    fr += [frame(k1=T1)]
    fr += [frame(k1=T1 | btn('B'))]                         # now B is the side action again
    fr += [frame(k1=T1)]
    tap('sel')
    tap('sel')                                              # Select closes
    tap('sel')
    fr += [frame(k1=0)] * 2                                 # no controller: closed
    fr += [frame(k1=T1)]
    # both players, every profile, every cell (labels), Auto
    for crc in CRCS + [NOPROF]:
        fr.append(frame(k1=T1 | btn('sel'), k2=T2 | btn('sel'), mode=3, crc=crc))
        fr.append(frame(k1=T1, k2=T2, mode=3, crc=crc))
        for i in range(12):
            for b in (btn('right'), 0):
                fr.append(frame(k1=T1 | b, k2=T2 | b, mode=3, crc=crc))
            if i % 3 == 2:
                for b in (btn('down'), 0):
                    fr.append(frame(k1=T1 | b, k2=T2 | b, mode=3, crc=crc))
        for b in (btn('B'), 0):                             # player 1 closes: player 2's label drops
            fr.append(frame(k1=T1 | b, k2=T2, mode=3, crc=crc))
        for b in (btn('B'), 0):
            fr.append(frame(k1=T1, k2=T2 | b, mode=3, crc=crc))
        for b in ('A', 'B', 'X'):                           # Auto's side actions
            fr.append(frame(k1=T1 | btn(b), k2=T3 | btn(b), mode=3, crc=crc))
            fr.append(frame(k1=T1, k2=T3, mode=3, crc=crc))
        for m in (0, 1, 2):
            fr.append(frame(k1=T1 | btn('A', 'X'), k2=T2 | btn('B'), mode=m, crc=crc, swap=m & 1))
    # player 2 alone, with Swap
    fr.append(frame(k1=T1, k2=T2 | btn('sel'), swap=1, crc=CRCS[0]))
    fr += [frame(k1=T1, k2=T2 | btn('A'), swap=1, crc=CRCS[0])] * 2
    fr.append(frame(k1=T1, k2=T2, swap=1, crc=CRCS[0]))
    fr += kb_spec_frames()
    return fr


def kb_spec_frames():
    """The ECS keyboard, written out by hand (ECS fully on unless said)."""
    fr = []
    E = 1

    def tap(*names, k2=T2, ecs=E):
        for b in (btn(*names), 0):
            fr.append(frame(k1=T1 | b, k2=k2, ecs=ecs))

    fr.append(frame(k1=T1, k2=T2 | btn('B'), ecs=0))        # player 2's keypad (above) closes
    fr.append(frame(k1=T1, k2=T2, ecs=0))
    tap('start', ecs=0)                                     # ECS off: nothing
    tap('start', ecs=E | 2)                                 # the synthesizer: nothing
    tap('start')                                            # open (cursor on RTN)
    fr += [frame(k1=T1 | btn('A'), ecs=E)] * 3              # RTN held
    fr.append(frame(k1=T1, ecs=E))
    for d in ['left'] * 7 + ['right'] * 7 + ['up', 'up', 'left'] + ['down'] * 6 + ['up'] * 6:
        tap(d)                                              # row 4 key by key, the column kept
    # every cell, pressing each: a snake over rows 0-3, then row 4
    for r in range(5):
        for _ in range(10 if r < 4 else 6):
            fr.append(frame(k1=T1 | btn('A'), ecs=E))
            fr.append(frame(k1=T1, ecs=E))
            tap('right')
        tap('down')
    fr += [frame(k1=T1 | btn('Y'), ecs=E)] * 2               # SHIFT alone, then with a key
    fr += [frame(k1=T1 | btn('Y', 'A'), ecs=E)] * 2
    fr += [frame(k1=T1 | btn('X', 'A'), ecs=E)] * 2          # CTL
    fr += [frame(k1=T1 | btn('X', 'Y', 'A', 'right'), ecs=E)]   # held while the cursor moves
    fr += [frame(k1=T1 | btn('X', 'Y', 'A'), ecs=E)]
    fr.append(frame(k1=T1, ecs=E))
    fr += [frame(k1=T1 | btn('L', 'R', 'sel'), ecs=E)] * 2   # taken while open; Select opens no keypad
    fr.append(frame(k1=T1, k2=T2 | btn('sel'), ecs=E))      # nor player 2's
    fr.append(frame(k1=T1, k2=T2, ecs=E))
    fr += [frame(k1=T1 | btn('B', 'A', 'Y'), ecs=E)]         # close with B: masked until let go
    fr += [frame(k1=T1 | btn('B', 'Y'), ecs=E)] * 2
    fr.append(frame(k1=T1, ecs=E))
    fr.append(frame(k1=T1 | btn('B'), ecs=E))
    fr.append(frame(k1=T1, ecs=E))
    tap('start')
    tap('start')                                            # Start closes
    tap('sel')                                              # a keypad open: Start does nothing
    tap('start')
    tap('B')
    fr.append(frame(k1=T1 | btn('sel', 'start'), ecs=E))     # both at once: the keypad
    fr.append(frame(k1=T1, ecs=E))
    tap('B')
    tap('sel', k2=T2)                                       # player 1's keypad open...
    fr.append(frame(k1=T1 | btn('B', 'start'), k2=T2, ecs=E))   # ...closing as Start rises: no
    fr.append(frame(k1=T1, k2=T2, ecs=E))
    fr.append(frame(k1=T1 | btn('start'), k2=T2 | btn('sel'), ecs=E))   # player 2's opening: no
    fr.append(frame(k1=T1, k2=T2, ecs=E))
    fr.append(frame(k1=T1, k2=T2 | btn('B'), ecs=E))
    fr.append(frame(k1=T1, k2=T2, ecs=E))
    tap('start')
    fr += [frame(k1=T1 | btn('A', 'up'), ecs=E)] * 2
    fr.append(frame(k1=T1 | btn('A'), ecs=0))               # the ECS goes: it closes
    fr.append(frame(k1=T1, ecs=0))
    fr.append(frame(k1=T1, ecs=E))
    tap('start')
    fr.append(frame(k1=T1 | btn('A', 'Y'), ecs=E | 2))       # the synthesizer set: it closes
    fr.append(frame(k1=T1, ecs=E))
    tap('start')
    fr.append(frame(k1=T1 | btn('A'), ecs=E))
    fr += [frame(k1=0, ecs=E)] * 2                          # not a controller: closed
    fr.append(frame(k1=T3, ecs=E))
    tap('start')
    fr.append(frame(k1=T3 | btn('down', 'left'), ecs=E, j1=0x0000FF00))   # analog: the stick still plays
    fr.append(frame(k1=T3, ecs=E))
    tap('B')
    return fr


def random_frames(n, rnd, sel=0.06, start=0.06, b_pr=0.08, ecs_set=(0, 1, 1, 1, 3, 2)):
    """sel, start, b_pr: how often Select, Start and B are pressed; ecs_set: the ECS states drawn
    (the second block: Select and B rare, the ECS on: the keyboard open longer)"""
    fr = []
    crc = NOPROF
    mode, swap, ecs = 3, 0, 1
    for _ in range(n):
        if rnd.random() < 0.03:
            crc = rnd.choice(CRCS + [NOPROF, 0])
        if rnd.random() < 0.05:
            mode, swap = rnd.randrange(4), rnd.randrange(2)
        ks = []
        if rnd.random() < 0.04:
            ecs = rnd.choice(ecs_set)
        for _p in range(2):
            t = rnd.choice([1, 1, 2, 3, 3, 0]) if rnd.random() < 0.02 else 1
            b = 0
            for bit, pr in ((osk.SELECT, sel), (osk.START, start), (osk.A, 0.3), (osk.B, b_pr), (osk.UP, 0.15),
                            (osk.DOWN, 0.15), (osk.LEFT, 0.15), (osk.RIGHT, 0.15), (osk.X, 0.1),
                            (osk.L1, 0.05), (osk.R1, 0.05), (osk.Y, 0.1)):
                if rnd.random() < pr:
                    b |= 1 << bit
            ks.append((t << 28) | b)
        fr.append(frame(k1=ks[0], k2=ks[1], mode=mode, swap=swap, crc=crc, ecs=ecs,
                        j1=rnd.choice([CENTRE, rnd.getrandbits(32)]), j2=CENTRE))
    return fr


def expect(frames):
    """The model, frame by frame: (pad_r, pad_l, ECS keys, pixels)."""
    pl = [osk.Player(), osk.Player()]
    kb = osk.Keyboard()
    out = []
    for f in frames:
        on, synth = f['ecs'] & 1, f['ecs'] >> 1 & 1
        osk.step_all(pl, kb, f['key1'], f['key2'], on and not synth)
        prof = osk.profile_for(f['crc'])
        v = dict(f, key3=0, joy3=0, trig3=0, ecs=im.ECS_ON if on else 0, synth=synth)
        r, l = im.ports(v, osk=pl, prof=prof, kb=kb)
        px = {(x, y): c for (x, y), c in osk.draw(pl, prof, kb).items()}
        out.append((r, l, im.ecs_keys(v, kb), px))
    return out


def build(work, rtl_dir, verilator, strict=True):
    obj = os.path.join(work, 'obj')
    os.makedirs(work, exist_ok=True)
    tables = os.path.join(rtl_dir, 'tables')
    defs = ['-DOSK_%s_HEX="%s"' % (k.upper(), os.path.join(tables, 'osk_%s.hex' % k))
            for k in ('crc', 'prof', 'font', 'label', 'llen', 'kbd')]
    cmd = [verilator, '--binary', '--timing', '--verilate-jobs', '1', '--build-jobs', '2', '-Wall', '-Wno-fatal',
           '-Wno-TIMESCALEMOD', '-Wno-PROCASSINIT', '--top-module', 'tb_osk', '-Mdir', obj, '-o', 'tb_osk'] + defs
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
    return os.path.join(obj, 'tb_osk')


def run(binary, frames, work):
    vec = os.path.join(work, 'vectors.txt')
    with open(vec, 'w') as f:
        for fr in frames:
            f.write('%08x %08x %08x %08x %x %x %08x %x\n' % (fr['key1'], fr['joy1'], fr['key2'], fr['joy2'],
                                                             fr['mode'], fr['swap'], fr['crc'], fr['ecs']))
    with open(os.path.join(work, 'run.log'), 'w') as f:
        subprocess.run([binary, '+vec=' + vec], stdout=f, stderr=subprocess.STDOUT, cwd=work)
    got = []
    cur = None
    out = os.path.join(work, 'osk_out.txt')
    if not os.path.exists(out):
        return None
    for ln in open(out):
        p = ln.split()
        if p[0] == 'S':
            cur = [None, None, None, {}]
            got.append(cur)
        elif cur is None:
            continue
        elif p[0] == 'F':
            cur[0], cur[1], cur[2] = int(p[2], 16), int(p[3], 16), int(p[4], 16)
        elif p[0] == 'P':
            cur[3][(int(p[1]), int(p[2]))] = int(p[3])
    return got


def compare(frames, want, got, quiet=False):
    bad = 0
    if got is None or len(got) != len(want):
        if not quiet:
            print('frames: %s of %d' % ('no output' if got is None else len(got), len(want)))
        return 1
    for i, ((r, l, ek, px), (gr, gl, gek, gpx)) in enumerate(zip(want, got)):
        msg = []
        if (r, l) != (gr, gl):
            msg.append('pads want %02x %02x got %s %s' % (r, l, gr, gl))
        if ek != gek:
            msg.append('ECS keys want %016x got %s' % (ek, gek if gek is None else '%016x' % gek))
        if px != gpx:
            dx = sorted(set(px) ^ set(gpx) | {k for k in px if k in gpx and px[k] != gpx[k]})
            msg.append('%d pixels differ, first %s: want %s got %s' % (len(dx), dx[0], px.get(dx[0], 0),
                                                                        gpx.get(dx[0], 0)))
        if msg:
            bad += 1
            if not quiet and bad <= 10:
                print('frame %d (%s): %s' % (i, ' '.join('%s=%x' % kv for kv in frames[i].items()), '; '.join(msg)))
    return bad


PLANTS = [
    ('osk_no_wrap', 'intv_input.sv', "if (rise[0]) r = r == 2'd0 ? 2'd3 : r - 2'd1;",
     "if (rise[0]) r = r == 2'd0 ? 2'd0 : r - 2'd1;"),
    ('osk_a_level', 'intv_input.sv', "else if (rise[4]) o_held[n] <= o_cur[n] + 4'd1;",
     "else o_held[n] <= o_cur[n] + 4'd1;"),
    ('osk_close_unmasked', 'intv_input.sv', "o_open[n] <= 1'b0; o_held[n] <= 4'd0; o_mask[n] <= b;",
     "o_open[n] <= 1'b0; o_held[n] <= 4'd0; o_mask[n] <= 16'd0;"),
    ('osk_buttons_leak', 'intv_input.sv', "k1[15:0] & ~(o_open[0] ? 16'hFFFF : o_mask[0])", "k1[15:0] & ~o_mask[0]"),
    ('osk_p2_key_lost', 'intv_input.sv', "| (o_open[1] && o_held[1] != 4'd0 ? cell_code(o_held[1] - 4'd1) : 8'h00);", ";"),
    ('auto_sides_ignored', 'intv_input.sv', "wire logic [5:0] psd  = auto && prof_ok ? prof_sides : 6'b10_01_00;",
     "wire logic [5:0] psd  = 6'b10_01_00;"),
    ('auto_mode_ignored', 'intv_input.sv', "wire logic [1:0] pmd  = auto ? (prof_ok ? prof_mode : 2'd0) : md;",
     "wire logic [1:0] pmd  = auto ? 2'd0 : md;"),
    ('prof_first_entry_lost', 'intv_profile.sv', "end else if (e[39] && e[38:7] == crc) begin",
     "end else if (e[39] && e[38:7] == crc && ie != 6'd0) begin"),
    ('draw_no_shadow', 'intv_osk_draw.sv', ": (sh && !q_press) ? DARK", ": 1'b0 ? DARK"),
    ('draw_p2_label_row', 'intv_osk_draw.sv', "ly1 = osk_open[0] ? 8'(LY - 20) : 8'(LY);", "ly1 = 8'(LY);"),
    ('draw_cursor_box', 'intv_osk_draw.sv', "|| by < 7'd2 || by >= 7'd20);", "|| by < 7'd2 || by >= 7'd21);"),
    ('draw_shadow_row', 'intv_osk_draw.sv', "ph == 4'd1 ? grow : grow - 3'd1", "grow"),
    ('draw_press_fill', 'intv_osk_draw.sv', "(q_press && q_ox >= 4'd1 && q_oy >= 5'd2)", "(q_press && q_ox >= 4'd1 && q_oy >= 5'd1)"),
    ('draw_label_char', 'intv_osk_draw.sv', "{w_li, 4'd0} + 10'd1 + 10'(w_dx[6:3])", "{w_li, 4'd0} + 10'(w_dx[6:3])"),
    # the ECS keyboard (1.0.4)
    ('kb_no_wrap', 'intv_input.sv', "if (rise[0]) r = r == 3'd0 ? 3'd4 : r - 3'd1;",
     "if (rise[0]) r = r == 3'd0 ? 3'd0 : r - 3'd1;"),
    ('kb_row4_by_column', 'intv_input.sv', "end else if (rise[2] || rise[3]) begin              // row 4",
     "end else if (1'b0) begin              // row 4"),
    ('kb_row4_no_wrap', 'intv_input.sv', "if (rise[3]) k = k == 3'd5 ? 3'd0 : k + 3'd1;",
     "if (rise[3]) k = k == 3'd5 ? 3'd5 : k + 3'd1;"),
    ('kb_without_ecs', 'intv_input.sv', "if (rise[15] && ecs_ok && !kp_was && !kp_now) begin",
     "if (rise[15] && !kp_was && !kp_now) begin"),
    ('kb_with_synth', 'intv_input.sv', "wire logic ecs_ok = ecs_full && !sy;", "wire logic ecs_ok = ecs_full;"),
    ('kb_over_keypad', 'intv_input.sv', "if (rise[15] && ecs_ok && !kp_was && !kp_now) begin",
     "if (rise[15] && ecs_ok && !kp_now) begin"),
    ('kb_with_opening_keypad', 'intv_input.sv', "if (rise[15] && ecs_ok && !kp_was && !kp_now) begin",
     "if (rise[15] && ecs_ok && !kp_was) begin"),
    ('keypad_over_kb', 'intv_input.sv', "if (rise[14] && !kb_on) begin", "if (rise[14]) begin"),
    ('kb_stays_without_ecs', 'intv_input.sv', "end else if (!ecs_ok || rise[15] || rise[5]) begin",
     "end else if (rise[15] || rise[5]) begin"),
    ('kb_buttons_leak', 'intv_input.sv', "(kb_on ? 16'hFFFF : kb_mask)", "kb_mask"),
    ('kb_close_unmasked', 'intv_input.sv', "on = 1'b0; kb_hd <= 6'd0; kb_mask <= b;",
     "on = 1'b0; kb_hd <= 6'd0; kb_mask <= 16'd0;"),
    ('kb_a_level', 'intv_input.sv', "else if (rise[4]) kb_hd <= kb_cell(kb_r, kb_c) + 6'd1;",
     "else kb_hd <= kb_cell(kb_r, kb_c) + 6'd1;"),
    ('kb_shift_lost', 'intv_input.sv', "| (kb_md[0] ? 64'd1 << 55 : 64'd0)", "| 64'd0"),
    ('kb_ctl_bit', 'intv_input.sv', "| (kb_md[1] ? 64'd1 << 46 : 64'd0);", "| (kb_md[1] ? 64'd1 << 45 : 64'd0);"),
    ('kb_key_bit', 'intv_input.sv', "64'd1 << kbd_rom[kb_hd - 6'd1][35:30]", "64'd1 << kbd_rom[kb_hd][35:30]"),
    ('kb_draw_row4_edges', 'intv_osk_draw.sv', "k_bord = (valid && dx == ks)", "k_bord = (valid && dx == 8'(u) * 8'd15)"),
    ('kb_draw_text_centre', 'intv_osk_draw.sv', "off = (w + 6'd1 - {n, 3'd0}) >> 1;", "off = 6'd4;"),
    ('kb_draw_cursor_box', 'intv_osk_draw.sv', "dy < cy + 7'd2 || dy >= cy + 7'd20);", "dy < cy + 7'd2 || dy >= cy + 7'd21);"),
    ('kb_draw_fill', 'intv_osk_draw.sv', "k_fill = k_press && dx >= ks + 8'd1 && oy >= 5'd2;",
     "k_fill = k_press && dx >= ks + 8'd1 && oy >= 5'd1;"),
    ('kb_draw_mod_colour', 'intv_osk_draw.sv', "k_yel = right ? kb_mods[1] : kb_mods[0];", "k_yel = kb_mods[0];"),
    ('kb_draw_mod_text', 'intv_osk_draw.sv', "4'h4: mod_char = 6'd19;", "4'h4: mod_char = 6'd18;"),
]


def run_plant(name, fname, a, b, verilator, work, frames, want):
    d = os.path.join(work, 'plant_' + name)
    shutil.rmtree(d, ignore_errors=True)
    rtl = os.path.join(d, 'rtl')
    os.makedirs(rtl)
    for f in RTL:
        shutil.copy(os.path.join(CORE, f), rtl)
    shutil.copytree(os.path.join(CORE, 'tables'), os.path.join(rtl, 'tables'))
    src = open(os.path.join(rtl, fname)).read()
    if src.count(a) != 1:
        return 'pattern not found'
    open(os.path.join(rtl, fname), 'w').write(src.replace(a, b))
    binary = build(d, rtl, verilator, strict=False)
    if binary is None:
        return 'build failed'
    bad = compare(frames, want, run(binary, frames, d), quiet=True)
    return 'caught (%d frames)' % bad if bad else 'NOT caught'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--no-build', action='store_true')
    ap.add_argument('--frames', type=int, default=400, help='random frames')
    ap.add_argument('--plant', help='comma-separated plant names (implies the plants only)')
    a = ap.parse_args()
    verilator = os.environ.get('VERILATOR', 'verilator')
    work = os.environ.get('WORK', os.path.join(ROOT, 'sim', 'work', 'tb_osk'))
    os.makedirs(work, exist_ok=True)
    if osk.gen(check=True):
        return 1
    frames = spec_frames() + random_frames(a.frames, random.Random(13)) \
        + random_frames(a.frames, random.Random(14), sel=0.0, start=0.04, b_pr=0.01,
                        ecs_set=(1, 1, 1, 1, 1, 1, 1, 1, 0, 3))
    want = expect(frames)
    ok = True
    if not a.plant:
        binary = os.path.join(work, 'obj', 'tb_osk') if a.no_build else build(work, CORE, verilator)
        if binary is None:
            print('TB_OSK FAIL: build')
            return 1
        bad = compare(frames, want, run(binary, frames, work))
        print('TB_OSK frames: %d (%d spec, %d random), %d differ' % (len(frames), len(spec_frames()), 2 * a.frames, bad))
        ok = bad == 0
    if a.all or a.plant:
        sel = a.plant.split(',') if a.plant else None
        for name, fname, x, y in PLANTS:
            if sel and name not in sel:
                continue
            r = run_plant(name, fname, x, y, verilator, work, frames, want)
            print('PLANT %s: %s' % (name, r))
            ok = ok and r.startswith('caught')
    print('TB_OSK%s %s' % ('_ALL' if a.all else '', 'pass' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
