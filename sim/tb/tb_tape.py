#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""tb_tape: the ECS cassette's engine (src/fpga/core/intv_tape.sv) = the model (tools/ecs_tape.py)
on scripted UART sequences (sim/tb/tb_tape.sv runs them).

  tb_tape.py [--all] [--no-build] [--plant NAMES] [--seed N]

The scripts, written here and run on both: the spec cases (two named saves, a save under the same
name, loads after a rewind and within 1 s, a load past the end, a save stopped short, a block too
long, a full tape dropping its oldest blocks, a tape file with a garbage tail, an erase, a reset
and a state load during a save, a state load during a load, the data byte that comes in while the
tape moves up), then random ones (saves of random length and names from a small set, loads,
rewinds, stops). Every read the RTL answers, every state word and the whole store at each dump
must equal the model's. --all also plants faults in the RTL, each of which must make the bench
fail. TB_TAPE_ALL pass / FAIL.
"""
import argparse
import os
import random
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, 'tools'), os.path.dirname(os.path.abspath(__file__))]
import ecs_tape as et  # noqa: E402
import tbcommon  # noqa: E402

CORE = os.path.join(ROOT, 'src', 'fpga', 'core')
TB = os.path.join(ROOT, 'sim', 'tb', 'tb_tape.sv')
RTL = ['intv_tape_store.sv', 'intv_tape.sv']
IDLE = 3000                 # the bench's rewind time (CPU cycles); the core's is et.REWIND_IDLE
ROOM = 12000                # CPU cycles after anything that sets the engine going (a move: 16,384
                            # bytes x 3 clocks / 8 clocks a cycle, and a whole-store dump)


class Script:
    """Operations for the bench, run on the model at once; exp: the log the RTL must write."""

    def __init__(self, name):
        self.name, self.ops, self.exp = name, [], []
        self.tp = et.Tape(idle=IDLE)
        self.c = 100                        # the next free CPU cycle
        self.nq = 0
        self.file = bytes(et.SIZE)

    def gap(self, g):
        self.c += g

    def w(self, a, v, g=4):
        self.c += g
        self.ops.append('W %d %x %x' % (self.c, a, v))
        self.tp.write(a, v, self.c)
        self.c += 1

    def r(self, a, g=4):
        self.c += g
        self.ops.append('R %d %x' % (self.c, a))
        v = self.tp.read(a, self.c)
        self.exp.append('Q %d %04x' % (self.nq, v))
        self.nq += 1
        self.c += 1
        return v

    def settle(self):
        self.ops.append('Z')
        self.c += ROOM

    def state(self):
        self.ops.append('S %d' % self.c)
        w = self.tp.state(self.c)
        self.exp.append('S %08x %08x' % tuple(w))
        return w

    def load_state(self, w):
        self.ops.append('L %d %x %x' % (self.c, w[0], w[1]))
        self.tp.load_state(w, self.c)
        self.c += 4
        self.settle()

    def media_file(self, data):
        """A load with a tape file: the Pocket's bytes, then the walk."""
        self.file = bytes(data[:et.SIZE]).ljust(et.SIZE, b'\0')
        self.ops.append('F %d' % et.SIZE)
        self.ops.append('K')
        self.tp.load_file(self.file)
        self.c += et.SIZE // 8 + 100
        self.settle()

    def clear(self):
        self.ops.append('C')
        self.tp.clear()
        self.settle()

    def reset(self, delay=0):
        self.ops.append('M %d' % delay)
        self.tp.reset()
        self.settle()

    def save_raw(self, seq):
        """A save of exactly these bytes (record on, the bytes, motor off)."""
        self.w(0xE2, 0x39, 200)
        for j, b in enumerate(seq):
            self.r(0xE0, 3)
            self.w(0xE1, b, 3)
            self.settle()
        self.w(0xE2, 0x00, 20)
        self.settle()

    def dump(self):
        self.ops.append('D')
        self.exp += ['D %d %02x' % (i, b) for i, b in enumerate(self.tp.file())]
        self.c += ROOM

    # -- as the ECS ROM does it
    def save(self, name, data, sync=9, stop_after=None, quick=False, hold_motor=False):
        body = (name.ljust(4).encode() if name else b'') + bytes(data)
        n = len(body)
        self.w(0xE2, 0x39, 200)
        seq = [0xAA] * sync + [0x00, (-n) & 0xFF, ((-n) >> 8) & 0xFF] + list(body)
        for j, b in enumerate(seq):
            if stop_after is not None and j == stop_after:
                break
            self.r(0xE0, 3)                 # the ROM waits for the transmitter
            self.w(0xE1, b, 3)
            if j == sync + (3 if quick else 2):
                self.settle()               # the tape moves up (INSERT); quick: one byte queues first
        if not hold_motor:
            self.w(0xE2, 0x00, 20)
            self.settle()

    def load(self, max_bytes=20000, pause=50):
        """Read bytes while there are any (as the ROM's loader, without its parsing)."""
        self.w(0xE2, 0x1D, pause)
        got = 0
        while got < max_bytes:
            if not self.r(0xE0, 5) & 1:
                break
            self.r(0xE1, 2)
            got += 1
        self.w(0xE2, 0x00, 10)
        return got

    def read_block(self):
        """One block (sync, $00, length, data), as the ROM reads it; the motor stays on."""
        self.w(0xE2, 0x1D, 30)
        ph, k, n, lo, got = 'sync', 0, 0, 0, 0
        for _ in range(et.SIZE + 10):
            if not self.r(0xE0, 3) & 1:
                break
            b = self.r(0xE1, 2)
            if ph == 'sync':
                k, ph = (k + 1, ph) if b == 0xAA else (0, 'lo') if b == 0 and k else (0, ph)
            elif ph == 'lo':
                lo, ph = b, 'hi'
            elif ph == 'hi':
                n, ph = (-(lo | b << 8)) & 0xFFFF, 'data'
                if n == 0:
                    break
            else:
                got += 1
                if got == n:
                    break
        self.w(0xE2, 0x00, 10)


def spec_scripts():
    out = []
    s = Script('named')
    s.dump()
    s.save('AAA', b'program one')
    s.save('BBB', b'two')
    s.dump()
    s.save('AAA', b'program one, changed')        # replaces AAA, goes to the front
    s.dump()
    s.gap(IDLE + 10)
    s.read_block()                                # rewound: AAA
    s.read_block()                                # within 1 s: BBB
    s.load()                                      # past the end: no byte
    s.gap(IDLE + 10)
    s.load(30)                                    # rewound again
    s.state()
    out.append(s)

    s = Script('short')
    s.save('AAA', b'x' * 50)
    s.dump()
    s.save('CCC', b'y' * 100, stop_after=60)      # stopped short: taken out
    s.dump()
    s.save(None, b'z' * 20, stop_after=5)         # stopped in the sync: nothing
    s.save(None, b'z' * 20000)                    # too long: not recorded
    s.dump()
    s.save('Q', b'pend', quick=True)              # a data byte while the tape moves up
    s.dump()
    # junk inside the sync: the count starts again (k = 2 here)
    s.save_raw([0xAA, 0xAA, 0x55, 0xAA, 0xAA, 0x00, 0xFC, 0xFF] + list(b'JUNK'))
    s.dump()
    out.append(s)

    s = Script('full')
    for i in range(6):
        s.save('P%d' % i, bytes([i]) * 4000)
    s.dump()                                      # the oldest dropped, whole
    s.save('P4', b'again')
    s.dump()
    out.append(s)

    s = Script('media')
    one = bytes([0xAA] * 9 + [0, 0xFA, 0xFF]) + b'ROAD\x01\x02'
    s.media_file(one + bytes([0xAA, 0xAA, 0x00, 0x00, 0x80]) + b'\x55' * 300)   # a cut block, garbage
    s.dump()                                      # the tail zeroed
    s.reset()
    s.read_block()
    s.save('NEW', b'after the file')
    s.dump()
    s.clear()                                     # the menu's Erase
    s.dump()
    s.load()
    out.append(s)

    s = Script('state')
    s.save('AAA', b'0123456789' * 10)
    s.gap(IDLE + 10)
    s.w(0xE2, 0x1D, 20)
    for _ in range(15):
        s.r(0xE0, 3)
        s.r(0xE1, 2)
    w = s.state()                                 # a state in the middle of a load
    for _ in range(20):
        s.r(0xE1, 2)
    s.load_state(w)                               # back: the same bytes again
    for _ in range(20):
        s.r(0xE0, 3)
        s.r(0xE1, 2)
    s.w(0xE2, 0x00, 10)
    w2 = s.state()
    s.save('BBB', b'z' * 300, hold_motor=True, stop_after=100)   # a save in progress...
    s.load_state(w2)                              # ...abandoned by a state load
    s.dump()
    s.save('CCC', b'w' * 200, hold_motor=True, stop_after=150)
    s.reset()                                     # ...and by a reset
    s.dump()
    s.state()
    s.gap(500)
    s.state()                                     # the motor-off count
    s.gap(IDLE + 100)
    w3 = s.state()                                # off long enough to rewind...
    s.w(0xE2, 0x1D, 10)                           # (playing moves the head on)
    for _ in range(5):
        s.r(0xE1, 2)
    s.w(0xE2, 0x00, 10)
    s.load_state(w3)                              # ...and back to that count
    s.state()
    s.w(0xE2, 0x1D, 10)                           # the start rewinds
    s.r(0xE1, 2)
    s.w(0xE2, 0x00, 10)
    # a reset in the clock the read ahead finishes: the byte under the head is head 0's again
    s.gap(IDLE + 10)
    s.w(0xE2, 0x1D, 10)
    for _ in range(11):                           # the head on a byte that is not head 0's ($AA)
        s.r(0xE0, 3)
        s.r(0xE1, 2)
    s.reset(delay=2)
    s.r(0xE1, 20)
    s.r(0xE0, 3)
    out.append(s)
    return out


def random_scripts(seed, n):
    rnd = random.Random(seed)
    out = []
    for k in range(n):
        s = Script('random%d' % k)
        for _ in range(rnd.randint(6, 14)):
            x = rnd.random()
            if x < 0.45:
                ln = rnd.choice([0, 1, 3, 4, 5, 40, 300, 2000, 5000])
                name = rnd.choice([None, 'A', 'B', 'CC', 'DDDD'])
                stop = rnd.choice([None] * 4 + [rnd.randint(0, 9 + 3 + ln + 4)])
                s.save(name, bytes(rnd.randrange(256) for _ in range(ln)), sync=rnd.choice([9, 9, 1, 3]),
                       stop_after=stop)
            elif x < 0.7:
                s.gap(rnd.choice([10, IDLE + 50]))
                s.read_block()
            elif x < 0.8:
                s.gap(rnd.choice([10, IDLE + 50]))
                s.load(rnd.randint(1, 200))
            elif x < 0.85:
                s.state()
            elif x < 0.9:
                s.reset()
            elif x < 0.93:
                s.clear()
            else:
                s.dump()
        s.dump()
        s.state()
        out.append(s)
    return out


def build(work, rtl_dir, verilator, strict=True):
    obj = os.path.join(work, 'obj')
    os.makedirs(work, exist_ok=True)
    cmd = [verilator, '--binary', '--timing', '--verilate-jobs', '1', '--build-jobs', '2', '-Wall', '-Wno-fatal',
           '-Wno-PROCASSINIT', '-Wno-TIMESCALEMOD', '-DTB_IDLE=%d' % IDLE, '--top-module', 'tb_tape', '-Mdir', obj, '-o', 'tb_tape']
    cmd += [os.path.join(rtl_dir, f) for f in RTL] + [TB]
    log = os.path.join(work, 'build.log')
    with open(log, 'w') as f:
        r = subprocess.run(cmd + tbcommon.VL_MAKEFLAGS, stdout=f, stderr=subprocess.STDOUT, env=tbcommon.vl_env())
    text = open(log).read()
    if r.returncode != 0:
        print(text[-3000:])
        return None
    ours = [ln for ln in text.splitlines() if ln.startswith('%Warning') and any(('/' + f + ':') in ln for f in RTL)]
    if ours and strict:
        print('\n'.join(ours[:20]))
        return None
    return os.path.join(obj, 'tb_tape')


def run_script(binary, work, s):
    ops = os.path.join(work, s.name + '.ops')
    hexf = os.path.join(work, s.name + '.hex')
    log = os.path.join(work, s.name + '.log')
    open(ops, 'w').write('\n'.join(s.ops) + '\n')
    open(hexf, 'w').write('\n'.join('%02x' % b for b in s.file) + '\n')
    subprocess.run([binary, '+ops=' + ops, '+log=' + log, '+file=' + hexf],
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    got = open(log).read().splitlines() if os.path.exists(log) else []
    if not got or not got[-1].startswith('END'):
        return 'no END line'
    if got[-1] != 'END late 0':
        return 'the script ran late (%s): leave the engine more room' % got[-1]
    got = got[:-1]
    for i, (g, e) in enumerate(zip(got, s.exp)):
        if g != e:
            return 'line %d: RTL "%s", model "%s"' % (i, g, e)
    if len(got) != len(s.exp):
        return '%d lines, model %d' % (len(got), len(s.exp))
    return None


def run_all(binary, work, scripts):
    probs = []
    for s in scripts:
        p = run_script(binary, work, s)
        if p:
            probs.append('%s: %s' % (s.name, p))
    return probs


# planted faults: (name, file, from, to); each must make the bench fail
PLANTS = [
    ('rewind_every_start', 'intv_tape.sv', "if (offc >= 20'(IDLE)) begin head <= 15'd0;",
     "if (1'b1) begin head <= 15'd0;"),
    ('no_rewind', 'intv_tape.sv', "if (offc >= 20'(IDLE)) begin head <= 15'd0;", "if (1'b0) begin head <= 15'd0;"),
    ('dr_always', 'intv_tape.sv', "wire logic dr   = playing && head < tlen && hb_ok && !busy;",
     "wire logic dr   = playing && hb_ok && !busy;"),
    ('head_stuck', 'intv_tape.sv', "                head <= head + 15'd1;\n                hb_ok <= 1'b0;",
     "                hb_ok <= 1'b0;"),
    ('data_upper_byte', 'intv_tape.sv', "else if (a[1:0] == 2'd1) q = {8'h00, head[14] ? 8'h00 : hb};",
     "else if (a[1:0] == 2'd1) q = {8'hFF, head[14] ? 8'h00 : hb};"),
    ('status_bit3', 'intv_tape.sv', "if (a[1:0] == 2'd0) q = {14'd0, 1'b1, dr};", "if (a[1:0] == 2'd0) q = {12'd0, 4'b1010 | {3'b0, dr}};"),
    ('name_off_by_one', 'intv_tape.sv', "a_addr <= 14'(wo + wk + 15'd3); st <= E_W_N1;",
     "a_addr <= 14'(wo + wk + 15'd2); st <= E_W_N1;"),
    ('no_replace', 'intv_tape.sv', "else if (wj == 2'd3) st <= E_DEL;", "else if (wj == 2'd3) begin wo <= 15'(w_end); st <= E_W_START; end"),
    ('oldest_first', 'intv_tape.sv', "ms <= 14'(TSIZE - rlen - 15'd1); md <= 14'h3FFF; mc <= TSIZE - rlen; mup <= 1'b1;",
     "ms <= 14'(TSIZE - rlen - 15'd1); md <= 14'h3FFF; mc <= 15'd0; mup <= 1'b1;"),
    ('cut_block_kept', 'intv_tape.sv', "if (w_end > 18'(TSIZE)) st <= E_W_H0;", "if (1'b0) st <= E_W_H0;"),
    ('no_short_abort', 'intv_tape.sv', "                        else q_abt <= 1'b1;\n", "                        else q_com <= 1'b1;\n"),
    ('no_tail_zero', 'intv_tape.sv', "else begin tlen <= wo; zp <= wo; zret <= J_IDLE; st <= E_ZERO; end",
     "else begin tlen <= wo; zp <= TSIZE; zret <= J_IDLE; st <= E_ZERO; end"),
    ('clr_ignored', 'intv_tape.sv', "        if (clr)  q_clr  <= 1'b1;", "        if (1'b0) q_clr  <= 1'b1;"),
    ('walk_ignored', 'intv_tape.sv', "        if (walk) q_walk <= 1'b1;", "        if (1'b0) q_walk <= 1'b1;"),
    ('too_long_recorded', 'intv_tape.sv', "> 17'(TSIZE))\n                            rph <= R_SKIP;", "> 17'(TSIZE) + 17'd70000)\n                            rph <= R_SKIP;"),
    ('pend_lost', 'intv_tape.sv', "                end else if (pend) begin\n                    st <= E_DATA;",
     "                end else if (pend) begin\n                    pend <= 1'b0;"),
    ('ss_head_lost', 'intv_tape.sv', "            head <= ss_wdata[14:0];\n", "            head <= 15'd0;\n"),
    ('ss_offc_lost', 'intv_tape.sv', "            offc <= ss_wdata[19:0];", "            offc <= 20'd0;"),
    ('ss_save_kept', 'intv_tape.sv', "            if (rph == R_DATA) q_abt <= 1'b1;   // a state load during a save: taken out\n",
     "\n"),
    ('reset_save_kept', 'intv_tape.sv', "            if (rph == R_DATA) q_abt <= 1'b1;   // a reset during a save: taken out\n",
     "\n"),
    ('offc_off_by_one', 'intv_tape.sv', "if (!wdata[4] && motor) offc <= 20'd1;", "if (!wdata[4] && motor) offc <= 20'd0;"),
    ('sync_count_reset', 'intv_tape.sv', "                            else rk <= 15'd0;\n", "\n"),
    ('stale_read_ahead', 'intv_tape.sv', "&& !a_we && !nv_we && !head_chg) begin hb <= a_q;", "&& !a_we && !nv_we) begin hb <= a_q;"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--all', action='store_true', help='the scripts, then the planted faults')
    ap.add_argument('--no-build', action='store_true')
    ap.add_argument('--plant', help='comma-separated plant names (with --all)')
    ap.add_argument('--seed', type=int, default=2026_11_06)
    ap.add_argument('--random', type=int, default=12)
    a = ap.parse_args()
    verilator = os.environ.get('VERILATOR', 'verilator')
    work = os.environ.get('WORK', os.path.join(ROOT, 'sim', 'work', 'tb_tape'))
    os.makedirs(work, exist_ok=True)
    fails = []

    print('-- model self-test (tools/ecs_tape.py)')
    if et.selftest():
        fails.append('model self-test')
    src = open(os.path.join(CORE, 'intv_tape.sv')).read()
    m = re.search(r"parameter int\s+IDLE\s*=\s*(\d+)", src)
    ok = m is not None and int(m.group(1)) == et.REWIND_IDLE
    print('  %s intv_tape IDLE = the model\'s REWIND_IDLE (%d CPU cycles, 60 frames)' % ('ok  ' if ok else 'FAIL', et.REWIND_IDLE))
    if not ok:
        fails.append('IDLE')

    scripts = spec_scripts() + random_scripts(a.seed, a.random)
    print('-- %d scripts (%d spec, %d random), %d expected lines' % (
        len(scripts), len(scripts) - a.random, a.random, sum(len(s.exp) for s in scripts)))
    binary = os.path.join(work, 'obj', 'tb_tape')
    if not a.no_build:
        binary = build(work, CORE, verilator)
    if not binary:
        fails.append('build')
    else:
        probs = run_all(binary, work, scripts)
        for p in probs[:10]:
            print('  FAIL  ' + p)
        print('  %s RTL = model on every script' % ('ok  ' if not probs else 'FAIL'))
        if probs:
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
            if s.count(frm) != 1:
                print('  FAIL  PLANT %s: pattern not found (%d)' % (name, s.count(frm)))
                fails.append('plant ' + name)
                continue
            open(p, 'w').write(s.replace(frm, to))
            b = build(d, os.path.join(d, 'rtl'), verilator, strict=False)
            if not b:
                print('  FAIL  PLANT %s: build failed' % name)
                fails.append('plant ' + name)
                continue
            probs = []
            for sc in scripts:                    # the first script that fails is enough
                pr = run_script(b, d, sc)
                if pr:
                    probs.append('%s: %s' % (sc.name, pr))
                    break
            if probs:
                print('  ok    PLANT %s: caught: %s' % (name, probs[0][:90]))
            else:
                print('  FAIL  PLANT %s: not caught' % name)
                fails.append('plant ' + name)
            shutil.rmtree(os.path.join(d, 'obj'), ignore_errors=True)

    print('TB_TAPE_ALL ' + ('pass' if not fails else 'FAIL (%s)' % ', '.join(fails)))
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
