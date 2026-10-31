#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Step-13 bench driver: the on-screen keypads, Auto mode and the game profiles (intv_input's
keypads, intv_profile, intv_osk_draw; sim/tb/tb_osk.sv) against tools/osk.py and
tools/intv_input.py, frame by frame: both pad bytes, and every overlay pixel of every frame.

  python3 -I sim/tb/tb_osk.py --all       the gate: the frames, then the planted faults
  python3 -I sim/tb/tb_osk.py [--no-build] [--frames N]

Frames (one vector each: both controllers' words, Keypad Mode, Swap, the cartridge's CRC):
  spec    written out by hand: opening and closing (Select, B, Select again, a slot that is not
          a controller), the cursor in every direction with wrapping, A pressed, held while the
          cursor moves, let go; the close's masked buttons until they are let go; both players'
          keypads at once (player 2's label one row up); every profile's cells, so every label
          is drawn; Auto with and without a profile (its mode, its A / B / X), the fixed modes,
          Swap;
  random  random button words (Select, A, B and the D-pad more often), slot types, modes,
          Swap, the CRC now and then.
For every frame the model steps both keypads (tools/osk.py Player), gives the pad bytes
(intv_input.ports with the keypads and the profile) and draws the overlay (osk.draw); the bench
must give the same bytes and exactly the same pixels.
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


def frame(k1=T1, k2=0, mode=0, swap=0, crc=NOPROF, j1=CENTRE, j2=CENTRE):
    return dict(key1=k1, joy1=j1, key2=k2, joy2=j2, mode=mode, swap=swap, crc=crc)


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
    return fr


def random_frames(n, rnd):
    fr = []
    crc = NOPROF
    mode, swap = 3, 0
    for _ in range(n):
        if rnd.random() < 0.03:
            crc = rnd.choice(CRCS + [NOPROF, 0])
        if rnd.random() < 0.05:
            mode, swap = rnd.randrange(4), rnd.randrange(2)
        ks = []
        for _p in range(2):
            t = rnd.choice([1, 1, 2, 3, 3, 0]) if rnd.random() < 0.02 else 1
            b = 0
            for bit, pr in ((osk.SELECT, 0.08), (osk.A, 0.3), (osk.B, 0.08), (osk.UP, 0.15),
                            (osk.DOWN, 0.15), (osk.LEFT, 0.15), (osk.RIGHT, 0.15), (osk.X, 0.1),
                            (osk.L1, 0.05), (osk.R1, 0.05), (osk.Y, 0.05)):
                if rnd.random() < pr:
                    b |= 1 << bit
            ks.append((t << 28) | b)
        fr.append(frame(k1=ks[0], k2=ks[1], mode=mode, swap=swap, crc=crc,
                        j1=rnd.choice([CENTRE, rnd.getrandbits(32)]), j2=CENTRE))
    return fr


def expect(frames):
    """The model, frame by frame: (pad_r, pad_l, pixels)."""
    pl = [osk.Player(), osk.Player()]
    out = []
    for f in frames:
        pl[0].step(f['key1'])
        pl[1].step(f['key2'])
        prof = osk.profile_for(f['crc'])
        v = dict(f, key3=0, joy3=0, trig3=0, ecs=0)
        r, l = im.ports(v, osk=pl, prof=prof)
        px = {(x, y): c for (x, y), c in osk.draw(pl, prof).items()}
        out.append((r, l, px))
    return out


def build(work, rtl_dir, verilator, strict=True):
    obj = os.path.join(work, 'obj')
    os.makedirs(work, exist_ok=True)
    tables = os.path.join(rtl_dir, 'tables')
    defs = ['-DOSK_%s_HEX="%s"' % (k.upper(), os.path.join(tables, 'osk_%s.hex' % k))
            for k in ('crc', 'prof', 'font', 'label', 'llen')]
    cmd = [verilator, '--binary', '--timing', '--verilate-jobs', '1', '--build-jobs', '2', '-Wall', '-Wno-fatal',
           '-Wno-TIMESCALEMOD', '-Wno-PROCASSINIT', '--top-module', 'tb_osk', '-Mdir', obj, '-o', 'tb_osk'] + defs
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
    return os.path.join(obj, 'tb_osk')


def run(binary, frames, work):
    vec = os.path.join(work, 'vectors.txt')
    with open(vec, 'w') as f:
        for fr in frames:
            f.write('%08x %08x %08x %08x %x %x %08x\n' % (fr['key1'], fr['joy1'], fr['key2'], fr['joy2'],
                                                          fr['mode'], fr['swap'], fr['crc']))
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
            cur = [None, None, {}]
            got.append(cur)
        elif cur is None:
            continue
        elif p[0] == 'F':
            cur[0], cur[1] = int(p[2], 16), int(p[3], 16)
        elif p[0] == 'P':
            cur[2][(int(p[1]), int(p[2]))] = int(p[3])
    return got


def compare(frames, want, got, quiet=False):
    bad = 0
    if got is None or len(got) != len(want):
        if not quiet:
            print('frames: %s of %d' % ('no output' if got is None else len(got), len(want)))
        return 1
    for i, ((r, l, px), (gr, gl, gpx)) in enumerate(zip(want, got)):
        msg = []
        if (r, l) != (gr, gl):
            msg.append('pads want %02x %02x got %s %s' % (r, l, gr, gl))
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
    frames = spec_frames() + random_frames(a.frames, random.Random(13))
    want = expect(frames)
    ok = True
    if not a.plant:
        binary = os.path.join(work, 'obj', 'tb_osk') if a.no_build else build(work, CORE, verilator)
        if binary is None:
            print('TB_OSK FAIL: build')
            return 1
        bad = compare(frames, want, run(binary, frames, work))
        print('TB_OSK frames: %d (%d spec, %d random), %d differ' % (len(frames), len(spec_frames()), a.frames, bad))
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
