#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Step-10 voice bench driver (DESIGN.md 9; docs/VOICE_NOTES.md 8.7): sp0256.sv against the model
tools/sp0256.py, sample by sample, read by read and state by state.

  python3 -I sim/tb/tb_voice.py --all          the gate: every run below, then the planted faults
  python3 -I sim/tb/tb_voice.py [--only NAMES] [--plant NAMES] [--plants-only] [--no-build]

Runs (each a command file for sim/tb/tb_voice.sv: N k samples, W a d writes, R a reads, X a save
of every state word, a reset, the FIFO RAM filled with other words (a reset does not clear it)
and a restore):
  ref:NAME    a MAME reference's bus log (tools/refs/mame_voice.sh: voice_t.log in INTV_VOICE_REFS,
              default ~/daria_work/intv/step10/refs), each access after the sample its MAME time falls
              in (the model's compare rule, sp0256.run_log), the whole run; a save-restore every
              50,000 samples. The model = MAME on these (VOICE_REF pass, sp0256.py compare), so
              RTL = model makes RTL = MAME.
  rnd:N       seed N: random bus traffic (commands into the resident ROM at any entry, FIFO
              programs written with sp0256.Stream from every opcode, MODE and repeat, raw random
              decles run from the FIFO, resets, pushes into a full FIFO, reads), save-restores at
              random points. A seed whose model step reads more than GUARD fields is skipped
              (a jump loop without data makes no sample, in the model as in the chip).
  bus:N       seed N, bus level: intv_voice.sv (sim/tb/tb_voicebus.sv) on CPU cycles against
              sp0256.VoiceBus at 10 kHz: random accesses, many of them in the cycles around a
              sample (the busy window: reads of the values at the sample, a held write),
              save-restores of every state word (the window's included). bus:0 is directed:
              a save-restore every few cycles across short phrases, so many land in the window.
  bmame:N     the same at MAME's rate (3,120,000 / 336 Hz).
Every line of the RTL's output must equal the model's: VOICE_RTL pass. At the bus level the reads
and the samples are compared as two sequences (the RTL makes a sample a few cycles after it
fires), and no sample may outlast the window (late 0).

Planted faults (PLANTS; --plants with --all): each, made in a copy of the RTL, must make a run
fail: "PLANT name: caught by RUNS". The ROM is the user's ivoice.bin (INTV_BIOS_DIR): the command
files and outputs are derived from it and stay in WORK.
"""
import argparse
import os
import random
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import sp0256 as sp  # noqa: E402

CORE = os.path.join(ROOT, 'src', 'fpga', 'core')
TB = os.path.join(ROOT, 'sim', 'tb', 'tb_voice.sv')
REFS = os.environ.get('INTV_VOICE_REFS', os.path.expanduser('~/daria_work/intv/step10/refs'))
REF_RUNS = ('b17_p', 'bombsqd_p', 'sspartan_p', 'tronss_p', 'wsmlb_p', 'voicetest')
RND_SEEDS = 24
BUS_SEEDS = 24
GUARD = 4000                       # getb calls in one model step
SR_EVERY = 50000                   # samples between save-restores in the reference runs


class GuardedVoice(sp.Voice):
    """The model with a bound on the fields one step reads (random programs may loop)."""

    def getb(self, n):
        self.calls += 1
        if self.calls > GUARD:
            raise RuntimeError('loop')
        return super().getb(n)

    def step(self):
        self.calls = 0
        return super().step()


def model_lines(rom, cmds, guard=False):
    v = (GuardedVoice if guard else sp.Voice)(rom)
    v.calls = 0
    out = []
    for c in cmds:
        t = c.split()
        if t[0] == 'N':
            for _ in range(int(t[1])):
                out.append('S %04x' % (v.step() & 0xFFFF))
        elif t[0] == 'W':
            v.write(0x80 + int(t[1]), int(t[2], 16))
        elif t[0] == 'R':
            a = int(t[1])
            out.append('R %d %04x %d %d %d %d %d %d' % (a, v.read(0x80 + a), v.pc, int(v.halted), v.lrq,
                                                        v.rpt, v.cnt, v.stack))
        elif t[0] == 'X':
            out.append('X')            # the RTL prints a hash of its words; only the line's presence is compared
    return out


def ref_cmds(name):
    ev = sp.parse_log(os.path.join(REFS, name, 'voice_t.log'))
    raw = os.path.getsize(os.path.join(REFS, name, 'voice.bin')) // 2
    cmds, made, nxt_sr = [], 0, SR_EVERY
    for e in ev:
        need = e[0] + 1
        while need > nxt_sr:
            if made < nxt_sr:
                cmds.append('N %d' % (nxt_sr - made))
                made = nxt_sr
            cmds.append('X')
            nxt_sr += SR_EVERY
        if need > made:
            cmds.append('N %d' % (need - made))
            made = need
        cmds.append('%s %d %04x' % (e[1], e[2] & 1, e[3]) if e[1] == 'W' else 'R %d' % (e[2] & 1))
    total = max(raw + 4000, made)
    cmds.append('N %d' % (total - made))
    return cmds


def rnd_program(r):
    """A random FIFO program (sp0256.Stream): SETMODEs and data instructions of every opcode with
    random fields, now and then a JSR into the resident ROM's phrase table or a SETPAGE + JMP."""
    s = sp.Stream()
    mode = 0
    for _ in range(r.randint(1, 12)):
        k = r.random()
        if k < 0.25:
            mode = r.randint(0, 3)
            s.setmode(mode, prefix=r.randint(0, 3) if r.random() < 0.3 else 0)
            continue
        if k < 0.30:
            s.jump('JSR', sp.ROM_BASE + 2 * r.randint(0, 40))
            continue
        name = r.choice(['LOADALL', 'LOAD_2', 'SETMSB_3', 'LOAD_4', 'SETMSB_5', 'SETMSB_6', 'DELTA_9',
                         'SETMSB_A', 'LOAD_C', 'DELTA_D', 'LOAD_E', 'PAUSE'])
        rep = r.choice([0, 1, 2, 3, r.randint(1, 15)])
        data = [(n, r.getrandbits(n)) for n in sp.fields(name, mode)] if rep else []
        s.op(name, rep, data)
    if r.random() < 0.5:
        s.op('RTS')
    return s.decles()


def rnd_cmds(seed):
    r = random.Random(seed)
    cmds = []
    for _ in range(r.randint(60, 120)):
        k = r.random()
        if k < 0.30:
            cmds.append('N %d' % r.randint(1, 4000))
        elif k < 0.45:
            cmds.append('W 0 %04x' % r.randint(0, 255 if r.random() < 0.3 else 60))
        elif k < 0.60:
            for d in rnd_program(r):
                cmds.append('W 1 %04x' % d)
            cmds.append('W 0 0000')
        elif k < 0.67:
            for _ in range(r.randint(1, 70)):
                cmds.append('W 1 %04x' % (r.getrandbits(10) | (r.getrandbits(5) << 11)))
            if r.random() < 0.5:
                cmds.append('W 0 0000')
        elif k < 0.70:
            cmds.append('W 1 %04x' % (0x400 | r.getrandbits(10)))         # reset
        elif k < 0.85:
            cmds.append('R %d' % r.randint(0, 1))
        else:
            cmds.append('X')
    cmds.append('N 2000')
    return cmds


def win_cmds():
    """bus:0, directed: a reset, a command into the idle chip at a random phase, then a
    save-restore every few cycles, each followed by reads (now and then a write): LRQ rises at
    the step that takes the command, so the reads in that window must give the value at the
    sample (snap_lrq 0, the live LRQ 1), and many saves land in it. A window not restored reads
    the live value."""
    r = random.Random(77)
    cmds = []
    for _ in range(300):
        cmds += ['W 1 0400', 'C %d' % r.randint(0, 120), 'W 0 %04x' % r.randint(1, 5)]
        for _ in range(r.randint(30, 50)):
            cmds += ['C %d' % r.randint(0, 3), 'X']
            for _ in range(r.randint(1, 2)):
                x = r.random()
                cmds.append('R %d' % r.randint(0, 1) if x < 0.85 else 'W 0 %04x' % r.randint(1, 5))
    cmds.append('C 4000')
    return cmds


def bus_cmds(seed):
    if seed == 0:
        return win_cmds()
    r = random.Random(1000 + seed)
    cmds = []
    for _ in range(r.randint(150, 300)):
        k = r.random()
        if k < 0.25:
            cmds.append('C %d' % r.randint(1, 3000))
        elif k < 0.45:                                   # a burst: every cycle for a while
            for _ in range(r.randint(5, 120)):
                x = r.random()
                if x < 0.5:
                    cmds.append('R %d' % r.randint(0, 1))
                elif x < 0.6:
                    cmds.append('W 0 %04x' % r.randint(0, 60))
                elif x < 0.85:
                    cmds.append('W 1 %04x' % r.getrandbits(10))
                else:
                    cmds.append('C 1')
        elif k < 0.60:
            for d in rnd_program(r):
                cmds.append('W 1 %04x' % d)
                cmds.append('C %d' % r.randint(8, 14))   # as a CPU loop pushes
            cmds.append('W 0 0000')
        elif k < 0.75:
            cmds.append('W 0 %04x' % r.randint(0, 60))
        elif k < 0.80:
            cmds.append('W 1 %04x' % (0x400 | r.getrandbits(10)))
        elif k < 0.95:
            cmds.append('R %d' % r.randint(0, 1))
        else:
            cmds.append('X')
    cmds.append('C 4000')
    return cmds


def bus_model(rom, cmds, mame):
    b = (sp.VoiceBus(rom, inc=sp.VoiceBus.MAME_INC, wrap=sp.VoiceBus.MAME_WRAP) if mame else sp.VoiceBus(rom))
    b.v.__class__ = GuardedVoice
    b.v.calls = 0
    cyc, reads = 0, []
    for c in cmds:
        t = c.split()
        if t[0] == 'C':
            cyc += int(t[1])
            b.run_to(cyc)
        elif t[0] == 'W':
            b.access(cyc, ('W', 0x80 + int(t[1]), int(t[2], 16)))
            cyc += 1
        elif t[0] == 'R':
            reads.append('R %04x' % b.access(cyc, ('R', 0x80 + int(t[1]))))
            cyc += 1
    b.run_to(cyc)                      # the bench runs no ce after its last command
    return reads, ['S %d %04x' % (k, x & 0xFFFF) for k, x in b.samples]


# ------------------------------------------------------------------ plants
# (name, file, [(from, to)], what): each must make a run fail
PLANTS = [
    ('loadall_amp6', 'sp0256_fmt.svh',
     [("6'b000101: fmt_hdr = {1'b1, 1'b0, 5'd16};", "6'b000101: fmt_hdr = {1'b1, 1'b0, 5'd15};")],
     'LOADALL in MODE 01 reads one field less'),
    ('fifo_jump_keep', 'sp0256.sv',
     [("if ($signed(ftail - fhead) < 16'sd0) ftail <= ftail + 16'd1;\n                        fbit <= 4'd0;",
       "fbit <= fbit;")], 'a jump into the FIFO keeps the half-read decle'),
    ('lrq_at_write', 'sp0256.sv', [("if (lrq) begin lrq <= 1'b0; ald <= wd[7:0]; end",
                                    "if (lrq) begin lrq <= 1'b1; ald <= wd[7:0]; end")],
     'LRQ not cleared by the command'),
    ('prefix_two', 'sp0256.sv', [("rep = {mode[5:4], gv[3:0]};\n                            mode <= mode & 6'h0F;",
                                  "rep = {mode[5:4], gv[3:0]};")], 'the repeat prefix kept'),
    ('sign_magnitude', 'sp0256.sv', [("? $signed({1'b0, qtbl(m)})", "? $signed({1'b0, qtbl(x[6:0])})")],
     'negative coefficients as sign and magnitude'),
    ('no_interp', 'sp0256.sv', [("rp = rpt - 8'sd1; di = interp;", "rp = rpt - 8'sd1; di = 1'b0;"),
                                ("di = interp; cn = 10'sd64;", "di = 1'b0; cn = 10'sd64;")],
     'no interpolation'),
    ('lfsr_tap', 'sp0256.sv', [("15'h4001", "15'h6001")], 'another LFSR tap'),
    ('fifo_full_63', 'sp0256.sv', [(">= 16'sd64", ">= 16'sd63")], 'the FIFO full at 63'),
    ('cmd_while_busy', 'sp0256.sv', [("if (lrq) begin lrq <= 1'b0; ald <= wd[7:0]; end",
                                      "begin lrq <= 1'b0; ald <= wd[7:0]; end")], 'a command taken while busy'),
    ('no_z_clear', 'sp0256.sv',
     [("rp = rpt - 8'sd1; di = interp;\n                            zv <= 6'd0;",
       "rp = rpt - 8'sd1; di = interp;")], 'the delay line kept at a pitch period start'),
    ('halted_decode', 'sp0256.sv', [("rv <= 16'd0;\n                        st <= S_EXC;",
                                     "rv <= 16'd0;\n                        st <= S_DEC;")],
     'the halted poll decodes the cleared registers'),
    # the register RAM (cleared by valid flags)
    ('r_unmasked', 'sp0256.sv', [("vmask[8 * k +: 8] = {8{rv[{a[1:0], 2'(k)}]}};", "vmask[8 * k +: 8] = 8'hFF;")],
     'cleared parameter registers keep their old values'),
    ('z_unmasked', 'sp0256.sv', [("vmask = {32{zv[3'(a - 4'd7)]}};", "vmask = {32{1'b1}};")],
     'a cleared delay line keeps its old values'),
    ('ss_ram_flags', 'sp0256.sv', [("if (ss_a < 4'd4) rv[{ss_a[1:0], 2'd0} +: 4] <= 4'hF;", "if (ss_a < 4'd4) ;")],
     'restored parameter registers read as cleared'),
    ('ss_word5', 'sp0256.sv', [("5'd5: {cnt, per, amp} <= ss_wdata[29:0];", "5'd5: ;")],
     'a state word not restored'),
    ('ss_fifo', 'sp0256.sv', [(".SS_ID(SS_ID + 8'd1)) fifo", ".SS_ID(SS_ID + 8'd2)) fifo")],
     'the FIFO not saved'),
    ('rom_range', 'sp0256.sv', [("inr <= ba[15:11] == 5'b00010;", "inr <= 1'b1;")],
     'bytes outside the resident ROM not 0'),
    ('mac_shift', 'sp0256.sv', [("h ? (mp >>> 8) : (mp >>> 9)", "h ? (mp >>> 8) : (mp >>> 8)")],
     'the B products shifted by 8'),
    # the bus level (intv_voice.sv): caught by the bus runs
    ('win_short', 'intv_voice.sv', [("parameter int          WIN   = 8", "parameter int          WIN   = 7")],
     'the busy window a cycle short'),
    ('snap_live', 'intv_voice.sv', [("{in_win ? snap_full : c_full, 15'd0} : {in_win ? snap_lrq : c_lrq, 15'd0}",
                                     "{c_full, 15'd0} : {c_lrq, 15'd0}")], 'reads in the window give the live values'),
    ('held_lost', 'intv_voice.sv', [("held <= 1'b1; held_a <= a[0]; held_d <= wdata;", "held_a <= a[0]; held_d <= wdata;")],
     'a write in the window dropped'),
    ('acc_stops', 'intv_voice.sv', [("if (ce && run && on)\n                acc <=", "if (ce && run && on && win == 4'd0)\n                acc <=")],
     'the sample enable stops in the window'),
    ('ss_window', 'intv_voice.sv', [("if (ss_w21) {started, late, held, held_a, mode_q, win, snap_full, snap_lrq} <= ss_wdata[10:0];",
                                     "if (ss_w21) {started, late, held, held_a, mode_q} <= ss_wdata[10:6];")],
     'the window not restored'),
]
PLANT_RUNS = ['ref:sspartan_p', 'ref:voicetest'] + ['rnd:%d' % i for i in range(1, 9)] + ['bus:%d' % i for i in range(0, 5)]


# ------------------------------------------------------------------ running
def verilator():
    return os.environ.get('VERILATOR', 'verilator')


def build(work, rtl, top='tb_voice', gen=()):
    obj = os.path.join(work, 'obj_' + top + ''.join('_' + g.split('=')[0] for g in gen))
    os.makedirs(work, exist_ok=True)
    srcs = [os.path.join(ROOT, 'sim', 'tb', top + '.sv'), os.path.join(rtl, 'sp0256.sv'), os.path.join(rtl, 'intv_ram.sv')]
    if top == 'tb_voicebus':
        srcs.append(os.path.join(rtl, 'intv_voice.sv'))
    cmd = [verilator(), '--binary', '--timing', '--verilate-jobs', '1', '--build-jobs', '2', '-Wall',
           '-Wno-fatal', '-Wno-TIMESCALEMOD', '-Wno-PROCASSINIT', '--top-module', top,
           '-I' + rtl, '-Mdir', obj, '-o', top] + ['-G' + g for g in gen] + srcs
    with open(os.path.join(work, 'build_%s.log' % top), 'a') as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    return os.path.join(obj, top) if r.returncode == 0 else None


def builds(work, rtl):
    """{kind: binary}: the chip bench and the bus bench at both rates."""
    return {'chip': build(work, rtl), 'bus': build(work, rtl, 'tb_voicebus'),
            'bmame': build(work, rtl, 'tb_voicebus', ("INC=32'd%d" % sp.VoiceBus.MAME_INC,
                                                      "WRAP=32'd%d" % sp.VoiceBus.MAME_WRAP))}


def rom_hex(rom, work):
    p = os.path.join(work, 'ivoice.hex')
    with open(p, 'w') as f:
        f.write('\n'.join('%02x' % b for b in rom) + '\n')
    return p


RUN_TIMEOUT = 7200     # seconds a run may take; the plant pass lowers it (PLANT_TIMEOUT)
PLANT_TIMEOUT = 300    # a planted chip that hangs (halted_decode) never ends its run: a FAIL


def run_sim(cmd):
    """The bench binary; False when it does not end within RUN_TIMEOUT (a hang)."""
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=RUN_TIMEOUT)
        return True
    except subprocess.TimeoutExpired:
        return False


def run_bus(binary, rom, romhex, work, name):
    kind, arg = name.split(':')
    cmds = bus_cmds(int(arg))
    try:
        wr_, ws_ = bus_model(rom, cmds, kind == 'bmame')
    except RuntimeError:
        return 'skip', 'the model loops (no data within %d fields)' % GUARD, 0
    tag = name.replace(':', '_')
    cf, of = os.path.join(work, tag + '.cmd'), os.path.join(work, tag + '.out')
    with open(cf, 'w') as f:
        f.write('\n'.join(cmds) + '\n')
    t0 = time.time()
    if not run_sim([binary, '+rom=' + romhex, '+cmd=' + cf, '+out=' + of]):
        for f_ in (cf, of):
            if os.path.exists(f_):
                os.remove(f_)
        return 'FAIL', 'no end within %d s (a hang)' % RUN_TIMEOUT, time.time() - t0
    got = open(of).read().split('\n') if os.path.exists(of) else []
    for f_ in (cf, of):
        os.remove(f_)
    gr = [g for g in got if g.startswith('R ')]
    gs = [g for g in got if g.startswith('S ')]
    gl = [g for g in got if g.startswith('L ')]
    dt = time.time() - t0
    if gl != ['L 0']:
        return 'FAIL', 'late %s' % gl, dt
    for what, g, w in (('read', gr, wr_), ('sample', gs, ws_)):
        if g != w:
            i = next((i for i in range(min(len(g), len(w))) if g[i] != w[i]), min(len(g), len(w)))
            return 'FAIL', '%s %d: RTL "%s", model "%s"' % (what, i + 1, g[i] if i < len(g) else '<missing>',
                                                             w[i] if i < len(w) else '<missing>'), dt
    return 'pass', '%d samples, %d reads, %d save-restores' % (len(ws_), len(wr_), cmds.count('X')), dt


def run_one(binary, rom, romhex, work, name):
    kind, arg = name.split(':')
    if kind in ('bus', 'bmame'):
        return run_bus(binary, rom, romhex, work, name)
    cmds = ref_cmds(arg) if kind == 'ref' else rnd_cmds(int(arg))
    try:
        want = model_lines(rom, cmds, guard=kind == 'rnd')
    except RuntimeError:
        return 'skip', 'the model loops (no data within %d fields)' % GUARD, 0
    tag = name.replace(':', '_')
    cf, of = os.path.join(work, tag + '.cmd'), os.path.join(work, tag + '.out')
    with open(cf, 'w') as f:
        f.write('\n'.join(cmds) + '\n')
    t0 = time.time()
    if not run_sim([binary, '+rom=' + romhex, '+cmd=' + cf, '+out=' + of]):
        for f_ in (cf, of):
            if os.path.exists(f_):
                os.remove(f_)              # derived from ivoice.bin
        return 'FAIL', 'no end within %d s (a hang)' % RUN_TIMEOUT, time.time() - t0
    got = open(of).read().split('\n') if os.path.exists(of) else []
    tail = [g for g in got if g.startswith('E ')]
    got = [g if not g.startswith('X') else 'X' for g in got if g and not g.startswith('E ')]
    for f_ in (cf, of):
        os.remove(f_)                  # derived from ivoice.bin
    nS = sum(1 for w in want if w[0] == 'S')
    if got == want:
        return 'pass', '%d samples, %d reads, %d save-restores%s' % (
            nS, sum(1 for w in want if w[0] == 'R'), sum(1 for w in want if w[0] == 'X'),
            ', longest step %s clk' % tail[0].split()[-1] if tail else ''), time.time() - t0
    for i, (g, w) in enumerate(zip(got + ['<missing>'] * len(want), want)):
        if g != w:
            return 'FAIL', 'line %d: RTL "%s", model "%s"' % (i + 1, g, w), time.time() - t0
    return 'FAIL', 'RTL output longer than the model\'s', time.time() - t0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--only', help='comma-separated runs (ref:NAME, rnd:N)')
    ap.add_argument('--plants', action='store_true', help='also the planted faults')
    ap.add_argument('--plants-only', action='store_true')
    ap.add_argument('--plant', help='comma-separated plant names')
    ap.add_argument('--no-build', action='store_true')
    a = ap.parse_args()
    work = os.environ.get('WORK', os.path.join(ROOT, 'sim', 'work', 'tb_voice'))
    bd = os.environ.get('INTV_BIOS_DIR', '')
    rp = next((os.path.join(bd, f) for f in ('ivoice.bin', 'IVOICE.BIN') if os.path.exists(os.path.join(bd, f))), None)
    if not rp:
        sys.exit('INTV_BIOS_DIR must hold ivoice.bin')
    rom = open(rp, 'rb').read()
    os.makedirs(work, exist_ok=True)
    romhex = rom_hex(rom, work)
    runs = a.only.split(',') if a.only else (['ref:' + n for n in REF_RUNS] + ['rnd:%d' % i for i in range(1, RND_SEEDS + 1)]
                                              + ['bus:%d' % i for i in range(0, BUS_SEEDS + 1)]
                                              + ['bmame:%d' % i for i in range(1, BUS_SEEDS // 2 + 1)])
    fails = []
    t0 = time.time()
    if not a.plants_only:
        bins = builds(work, CORE)
        if not all(bins.values()):
            print('TB_VOICE_ALL FAIL (build %s)' % [k for k, v in bins.items() if not v])
            return 1
        print('build: %ds' % (time.time() - t0), flush=True)
        for n in runs:
            k = n.split(':')[0]
            res, msg, dt = run_one(bins['chip' if k in ('ref', 'rnd') else k], rom, romhex, work, n)
            print('  %-4s %-16s %s  %.1fs' % ('ok' if res == 'pass' else res, n, msg, dt), flush=True)
            if res == 'FAIL':
                fails.append(n)
        print('set: %d runs, %d fail' % (len(runs), len(fails)))
    if a.plants or a.plants_only:
        names = a.plant.split(',') if a.plant else [p[0] for p in PLANTS]
        for name, fn, subs, what in [p for p in PLANTS if p[0] in names]:
            pw = os.path.join(work, 'plant_' + name)
            rtl = os.path.join(pw, 'rtl')
            shutil.rmtree(pw, ignore_errors=True)
            os.makedirs(rtl)
            for f in ('sp0256.sv', 'sp0256_fmt.svh', 'intv_ram.sv', 'intv_voice.sv'):
                shutil.copy(os.path.join(CORE, f), rtl)
            src = open(os.path.join(rtl, fn)).read()
            ok = True
            for x, y in subs:
                if src.count(x) != 1:
                    ok = False
                src = src.replace(x, y)
            if not ok:
                print('PLANT %s (%s): pattern not found once' % (name, what))
                fails.append('plant ' + name)
                continue
            open(os.path.join(rtl, fn), 'w').write(src)
            bins = builds(pw, rtl)
            if not all(bins.values()):
                print('PLANT %s (%s): build failed' % (name, what))
                fails.append('plant ' + name)
                continue
            caught = []
            global RUN_TIMEOUT
            RUN_TIMEOUT = PLANT_TIMEOUT
            for n in PLANT_RUNS:
                k = n.split(':')[0]
                res, _, _ = run_one(bins['chip' if k in ('ref', 'rnd') else k], rom, romhex, pw, n)
                if res == 'FAIL':
                    caught.append(n)
            print('PLANT %s (%s): %s' % (name, what, 'caught by ' + ' '.join(caught) if caught else 'NOT caught'),
                  flush=True)
            if not caught:
                fails.append('plant ' + name)
            shutil.rmtree(os.path.join(pw, 'obj'), ignore_errors=True)
    print('time: %ds' % (time.time() - t0))
    print('TB_VOICE_ALL %s' % ('pass' if not fails else 'FAIL (%s)' % ', '.join(fails)))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
