#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Step 3 bench driver (DESIGN.md 9): the machine RTL against the system model.

"EXEC runs with no cartridge; bus log matches the Python model in lockstep",
plus the save/restore round trip of DESIGN 8.4. For each image (no
cartridge, then Astrosmash from the owner's library) it

  1. runs tools/intv_system.py (our CP1610 model on the step-3 system bus,
     the same device stubs and frame timing) for 10 frames, keeping its
     bus-phase log, the registers at every step start, and the machine's
     state at the dump points;
  2. runs sim/tb/tb_system.sv (intv_machine with intv_timing, intv_media and
     the SRAM model; the system ROMs and the cartridge loaded through the
     loader's byte port) four times: straight, and with a round trip each
     (restore into a reset machine at a cartridge read or in VBlank; restore
     over a state 20,000 cycles later, which rewinds the run; restore into
     a reset machine outside VBlank);
  3. compares every run with the model: every bus phase other than NACT
     with its cycle, address and data; R0-R7, S Z O C, I and D at every step
     start; at the dumps, scratchpad, System RAM, GRAM, the STIC and PSG
     registers, the handshake and mode latches and the page selects. All
     runs must also leave every state word identical at both dumps.
  4. with --mame (or INTV_TRACE_ROOT set): the model against MAME's trace
     of the same image (tools/intv_system.py mame: every read and write and
     every interrupt point equal), so the stubs answer as MAME does.

  python3 -I sim/tb/tb_system.py --all     the step-3 gate: the above, then
                                           the planted faults (each must fail)
  python3 -I sim/tb/tb_system.py [--only nocart] [--no-build]

Environment: VERILATOR (default verilator), WORK (default sim/work/tb_system),
INTV_LIBRARY (default ~/ROMLibrary/Intellivision), INTV_BIOS_DIR (default
~/pocket_projects/intellivision/bios: exec.bin, grom.bin), INTV_TRACE_ROOT
(MAME traces <root>/<image>/trace.log from tools/refs/mame_trace.sh; the
no-cartridge one with image "none"). Images are extracted into WORK and
deleted after the run; on the owner's VM run this in a simulation slot
(~/daria_work/bin/simslot). The last line is "TB_SYSTEM_ALL pass" or
"TB_SYSTEM_ALL FAIL (...)".
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'mapper'))
import as1610               # noqa: E402
import intv_system as isys  # noqa: E402
import intvcart as m        # noqa: E402

CORE = os.path.join(ROOT, 'src', 'fpga', 'core')
RTL = ['cp1610.sv', 'intv_bus.sv', 'intv_stic_regs.sv', 'intv_psg_regs.sv', 'intv_ram.sv',
       'intv_machine.sv', 'intv_timing.sv', 'intv_sram.sv', 'intv_cart.sv', 'intv_sysrom.sv',
       'intv_loader.sv', 'intv_media.sv']
OTHER = [os.path.join(HERE, 'models', 'sram_as6c2016.sv'), os.path.join(HERE, 'tb_system.sv')]

FRAME = isys.FRAME
NCYC = 10 * FRAME
DUMP1 = 5 * FRAME + 8000
# (name, cartridge in the library, program for the EXEC slot instead of exec.bin)
IMAGES = [('nocart', None, None), ('astrosmash', 'Astrosmash (USA, Europe).zip', None),
          ('systest', None, 'systest.asm')]
TESTROMS = os.path.join(ROOT, 'sim', 'testroms')
PHASE = {'NACT': 0, 'ADAR': 1, 'IAB': 2, 'DTB': 3, 'BAR': 4, 'DW': 5, 'DWS': 6, 'INTAK': 7}
SS = {'cpu': 0x02, 'bus': 0x03, 'stic': 0x04, 'psg': 0x05, 'scr': 0x06, 'sys': 0x07,
      'gram': 0x09, 'cart': 0x0B}


# ------------------------------------------------------------------- model
def model_run(exec_path, grom_path, cart_path):
    """The model's expected log: bus phases, step starts, state at the dumps."""
    cart = isys.load_cart(cart_path)
    bus = isys.SystemBus(isys.load_words(exec_path), open(grom_path, 'rb').read(),
                         cart[0] if cart else None)
    cpu = isys.CP1610(bus=bus, buslog=True)
    snaps = {}
    want = [DUMP1, NCYC]
    orig_r, orig_w = bus.read, bus.write

    def snap(cycle):
        while want and cycle >= want[0]:
            snaps[want[0]] = bus.state(want[0])
            want.pop(0)

    def rd(addr, cycle, kind='data'):
        snap(cycle)
        return orig_r(addr, cycle, kind)

    def wr(addr, value, cycle):
        snap(cycle)
        orig_w(addr, value, cycle)

    bus.read, bus.write = rd, wr
    steps = []
    prev = (list(cpu.r), cpu.flags << 2 | cpu.I << 1 | cpu.D)
    while cpu.cycle < NCYC:
        ev = cpu.step()
        if ev.kind in ('insn', 'intr') and ev.cycle > 0:
            steps.append((ev.cycle, prev[0], prev[1]))
        prev = (list(ev.regs), ev.flags << 2 | ev.i << 1 | ev.d)
    snap(NCYC)
    blog = [(c, PHASE[p], a or 0, d or 0) for (c, p, a, d) in cpu.buslog
            if c < NCYC and p != 'NACT']
    steps = [s for s in steps if s[0] < NCYC]
    return blog, steps, snaps, bus


# ------------------------------------------------------------------- bench
def build(work, rtl_dir, verilator, strict=True):
    obj = os.path.join(work, 'obj')
    os.makedirs(work, exist_ok=True)
    tables = os.path.join(CORE, 'tables')
    cmd = [verilator, '--binary', '--timing', '-j', '4', '-Wall', '-Wno-fatal', '-Wno-TIMESCALEMOD',
           '-Wno-PROCASSINIT', '--top-module', 'tb_system', '-Mdir', obj, '-o', 'tb_system',
           '-DCRC_HEX="%s"' % os.path.join(tables, 'cart_crc.hex'),
           '-DLAYOUT_HEX="%s"' % os.path.join(tables, 'cart_layouts.hex')]
    cmd += [os.path.join(rtl_dir, f) for f in RTL] + OTHER
    log = os.path.join(work, 'build.log')
    with open(log, 'w') as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    text = open(log).read()
    if r.returncode != 0:
        print(text[-4000:])
        return None
    ours = [ln for ln in text.splitlines() if ln.startswith('%Warning') and
            any(('/' + f + ':') in ln for f in RTL)]
    if ours and strict:
        print('\n'.join(ours[:20]))
        return None
    return os.path.join(obj, 'tb_system')


def parse_log(path):
    blog, steps, dumps, notes, fails = [], [], {}, [], []
    for ln in open(path):
        t = ln.split()
        if not t:
            continue
        if t[0] == 'B':
            blog.append((int(t[1]), int(t[2]), int(t[3], 16), int(t[4], 16)))
        elif t[0] == 'S':
            if int(t[1]) > 0:
                steps.append((int(t[1]), [int(x, 16) for x in t[2:10]], int(t[10], 16)))
        elif t[0] == 'W':
            dumps.setdefault(int(t[1]), {})[(int(t[2], 16), int(t[3]))] = int(t[4], 16)
        elif t[0] == 'R' and t[1] == 'rewind':
            c = int(t[2])
            notes.append(ln.strip())
            blog = [b for b in blog if b[0] < c]
            steps = [s for s in steps if s[0] < c]
        elif t[0] in ('R', 'L'):
            notes.append(ln.strip())
        elif t[0] == 'FAIL':
            fails.append(ln.strip())
    return blog, steps, dumps, notes, fails


def fmt_b(b):
    if b is None:
        return '(none)'
    inv = {v: k for k, v in PHASE.items()}
    return 'c=%d %s %04X %04X' % (b[0], inv[b[1]], b[2], b[3])


def compare(name, run, got, exp):
    """Problems of one run against the model (a list of strings)."""
    blog, steps, dumps, notes, fails = got
    eb, es, snaps, _ = exp
    probs = list(fails)
    n = max(len(blog), len(eb))
    for i in range(n):
        g = blog[i] if i < len(blog) else None
        e = eb[i] if i < len(eb) else None
        if g != e:
            ctx = ' | '.join(fmt_b(x) for x in eb[max(0, i - 3):i])
            probs.append('bus entry %d: RTL %s, model %s (before: %s)' % (i, fmt_b(g), fmt_b(e), ctx))
            break
    for i in range(max(len(steps), len(es))):
        g = steps[i] if i < len(steps) else None
        e = es[i] if i < len(es) else None
        if g != e:
            probs.append('step %d: RTL %s, model %s' % (i, g, e))
            break
    for k, cyc in ((1, DUMP1), (2, NCYC)):
        d = dumps.get(k)
        if d is None:
            probs.append('dump %d missing' % k)
            continue
        st = snaps[cyc]
        checks = []
        checks += [('scratch %02X' % i, d[(SS['scr'], i)], st['scratch'][i]) for i in range(256)]
        checks += [('sysram %03X' % i, d[(SS['sys'] + i // 256, i % 256)], st['sysram'][i])
                   for i in range(352)]
        checks += [('gram %03X' % i, d[(SS['gram'] + i // 256, i % 256)], st['gram'][i])
                   for i in range(512)]
        checks += [('stic %02X' % i, d[(SS['stic'], i)], st['stic'][i]) for i in range(0x33)]
        checks.append(('stic hs/csmode', d[(SS['stic'], 0x33)], st['handshake'] << 1 | st['csmode']))
        checks += [('psg %d' % i, d[(SS['psg'], i)], st['psg'][i]) for i in range(14)]
        sel = st['sel']
        checks.append(('page selects 0-7', d[(SS['cart'], 19)],
                       sum(sel[i] << 4 * i for i in range(8))))
        checks.append(('page selects 8-15', d[(SS['cart'], 20)],
                       sum(sel[8 + i] << 4 * i for i in range(8))))
        checks.append(('bus: reset vector flag, hold', d[(SS['bus'], 0)] >> 16 & 5, 0))
        bad = [c for c in checks if c[1] != c[2]]
        if bad:
            probs.append('dump %d (cycle %d): %d words differ from the model, first: %s' % (
                k, cyc, len(bad), '; '.join('%s RTL %X model %X' % b for b in bad[:4])))
    return probs


def run_bench(binary, work, tag, exec_path, grom_path, cart_path, args, timeout=1200):
    log = os.path.join(work, 'run_%s.log' % tag)
    cmd = [binary, '+exec=' + exec_path, '+grom=' + grom_path, '+cycles=%d' % NCYC,
           '+dump=%d' % DUMP1, '+log=' + log] + args
    if cart_path:
        cmd.append('+cart=' + cart_path)
    with open(os.path.join(work, 'stdout_%s.txt' % tag), 'w') as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout, cwd=work)
    if r.returncode != 0 or not os.path.exists(log):
        return None
    return parse_log(log)


def rt_runs(exp):
    """The round-trip runs: (tag, plusargs). The first freezes inside a
    cartridge read (between the address and the data, so the held answer
    must come back): the last one of the run, if the image has one, else
    in VBlank of frame 5."""
    eb = exp[0]
    cart_dtb = [b[0] for b in eb if b[1] == PHASE['DTB'] and b[0] < DUMP1 and
                exp[3].cart is not None and exp[3].cart.read(b[2]) is not None]
    c1 = cart_dtb[-1] if cart_dtb else 5 * FRAME + 600
    return [('straight', []),
            ('rt1', ['+rt=1', '+rtcyc=%d' % c1, '+rtsub=17']),
            ('rt2', ['+rt=2', '+rtcyc=%d' % (5 * FRAME + 600), '+rtsub=30', '+rton=20000']),
            ('rt3', ['+rt=1', '+rtcyc=%d' % (5 * FRAME + 6000), '+rtsub=3'])]


def check_image(binary, work, name, exec_path, grom_path, cart_path, exp, verbose=True,
                only_runs=None):
    probs = []
    results = {}
    for tag, args in rt_runs(exp):
        if only_runs and tag not in only_runs:
            continue
        t0 = time.time()
        got = run_bench(binary, work, '%s_%s' % (name, tag), exec_path, grom_path, cart_path, args)
        if got is None:
            probs.append('%s %s: the bench did not finish' % (name, tag))
            continue
        p = compare(name, tag, got, exp)
        results[tag] = got
        if verbose:
            rt = [x for x in got[3] if x.startswith('R ')]
            print('  %s %s: %d bus phases, %d step starts, %.1fs%s%s' % (
                name, tag, len(got[0]), len(got[1]), time.time() - t0,
                ('; ' + '; '.join(x[2:] for x in rt)) if rt else '',
                ('\n    FAIL ' + '\n    FAIL '.join(p)) if p else ''))
        probs += ['%s %s: %s' % (name, tag, x) for x in p]
    ref = results.get('straight')
    for tag, got in results.items():
        if ref is None or tag == 'straight':
            continue
        for k in (1, 2):
            a, b = ref[2].get(k, {}), got[2].get(k, {})
            diff = [w for w in a if a[w] != b.get(w)]
            if diff:
                probs.append('%s %s: dump %d differs from the straight run in %d words, first %s' % (
                    name, tag, k, len(diff), ', '.join('%02X.%d %08X/%08X' % (w[0], w[1], a[w], b.get(w, -1))
                                                       for w in diff[:4])))
    return probs


# ------------------------------------------------------------------ plants
# Each is one change to a copy of the RTL; the bench must fail on it.
PLANTS = [
    # behaviour (the plain lockstep)
    ('pullup_zero', 'intv_bus.sv', [("            if (cart_hit) din &= cart_q;\n",
     "            if (cart_hit) din &= cart_q;\n            if (!(sel_stic || sel_scr || sel_psg || sel_sys"
     " || sel_exec || sel_grom || sel_gram || cart_hit)) din = 16'h0000;\n")], 'nocart', None),
    ('grom_upper_0', 'intv_bus.sv', [("din &= {8'hFF, grom_q};", "din &= {8'h00, grom_q};")], 'nocart', None),
    ('exec_upper_1', 'intv_bus.sv', [("din &= {6'd0, exec_q};", "din &= {6'h3F, exec_q};")], 'nocart', None),
    ('scratch_upper_1', 'intv_bus.sv', [("din &= {8'h00, scr_q};", "din &= {8'hFF, scr_q};")], 'systest', None),
    ('intrm_line_late', 'intv_bus.sv', [("    assign intrm     = vb_next;",
     "    assign intrm     = slot >= 16'(CPL - 1) && slot < 16'(VB_CYCLES + CPL - 1);")], 'astrosmash', None),
    ('start_line_early', 'intv_bus.sv', [("if (hold && slot == 16'(FRAME - 2))",
                                          "if (hold && slot == 16'(FRAME - 2 - CPL))")], 'astrosmash', None),
    ('iab_always_1004', 'intv_bus.sv', [("din = iab_rst ? 16'h1000 : 16'h1004;", "din = 16'h1004;")],
     'nocart', None),
    ('stic_mxr_mask', 'intv_stic_regs.sv', [("if (n < 6'h08)       fixed = 14'h3800;",
                                             "if (n < 6'h08)       fixed = 14'h3000;")], 'nocart', None),
    ('stic_always_open', 'intv_stic_regs.sv', [("assign open = vb || !hs;", "assign open = 1'b1;")],
     'systest', None),
    ('stic_no_aliases', 'intv_bus.sv', [("assign stic_we = wr && a[13:6] == 8'd0;",
                                         "assign stic_we = wr && a[15:6] == 10'd0;")], 'systest', None),
    ('gram_no_mirror', 'intv_bus.sv', [("assign gram_we = wr && a[13:11] == 3'b111 && stic_open;",
     "assign gram_we = wr && a[15:11] == 5'b00111 && a[10:9] == 2'b00 && stic_open;")], 'systest', None),
    ('psg_mask', 'intv_psg_regs.sv', [("4'd9:                    mask = 8'h1F;",
                                       "4'd9:                    mask = 8'hFF;")], 'systest', None),
    # state port: a flip-flop left out of the port (neither saved nor restored),
    # shown by the run after the restore
    ('ss_ram_lost', 'intv_ram.sv', [("wire logic          wa = ss_en ? ss_we && ss_hit : we;",
                                     "wire logic          wa = ss_en ? 1'b0 : we;"),
                                    ("assign ss_rdata = hit_q ? 32'(q) : 32'd0;", "assign ss_rdata = 32'd0;")],
     'systest', ['rt2']),
    ('ss_psg_lost', 'intv_psg_regs.sv', [("            r[ss_w] <= ss_wdata[7:0] & mask(ss_w);", "            ;"),
                                         ("assign ss_rdata = ss_hit ? {24'd0, r[ss_w]} : 32'd0;",
                                          "assign ss_rdata = 32'd0;")], 'systest', ['rt1']),
    ('ss_cart_q_lost', 'intv_bus.sv', [("            end else if (ss_w == 8'd1)\n                cart_q <= ss_wdata[15:0];",
                                        "            end else if (ss_w == 8'd1)\n                ;"),
                                       ("8'd1: ss_rdata = {16'd0, cart_q};", "8'd1: ss_rdata = 32'd0;")],
     'astrosmash', ['rt1']),
    ('ss_iab_lost', 'intv_bus.sv', [("{hold, cart_hit, iab_rst} <= ss_wdata[18:16];",
                                     "{hold, cart_hit} <= ss_wdata[18:17];"),
                                    ("8'd0: ss_rdata = {13'd0, hold, cart_hit, iab_rst, a};",
                                     "8'd0: ss_rdata = {13'd0, hold, cart_hit, 1'b0, a};")], 'astrosmash', ['rt1']),
    ('ss_handshake_lost', 'intv_stic_regs.sv', [("{hs, csmode} <= ss_wdata[1:0];", "csmode <= ss_wdata[0];"),
                                                ("ss_rdata = {30'd0, hs, csmode};", "ss_rdata = {31'd0, csmode};")],
     'systest', ['rt3']),
    ('ss_addr_lost', 'intv_bus.sv', [("                a <= ss_wdata[15:0];\n", ""),
                                     ("8'd0: ss_rdata = {13'd0, hold, cart_hit, iab_rst, a};",
                                      "8'd0: ss_rdata = {13'd0, hold, cart_hit, iab_rst, 16'd0};")],
     'astrosmash', ['rt1']),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--all', action='store_true', help='images, MAME, then planted faults')
    ap.add_argument('--only', help='comma-separated image names (nocart, astrosmash)')
    ap.add_argument('--no-build', action='store_true')
    ap.add_argument('--plants-only', action='store_true')
    ap.add_argument('--plant', help='comma-separated plant names')
    ap.add_argument('--mame', action='store_true', help='also compare the model with MAME traces')
    a = ap.parse_args()
    verilator = os.environ.get('VERILATOR', 'verilator')
    work = os.environ.get('WORK', os.path.join(ROOT, 'sim', 'work', 'tb_system'))
    lib = os.environ.get('INTV_LIBRARY', os.path.expanduser('~/ROMLibrary/Intellivision'))
    bdir = os.environ.get('INTV_BIOS_DIR', os.path.expanduser('~/pocket_projects/intellivision/bios'))
    troot = os.environ.get('INTV_TRACE_ROOT')
    exec_path, grom_path = os.path.join(bdir, 'exec.bin'), os.path.join(bdir, 'grom.bin')
    os.makedirs(work, exist_ok=True)
    os.environ['INTV_BIOS_DIR'] = bdir

    imgs = IMAGES
    if a.only:
        imgs = [i for i in imgs if i[0] in a.only.split(',')]
    carts = {}
    execs = {}
    exps = {}
    fails = []
    t0 = time.time()
    try:
        for name, zipname, prog in imgs:
            cart = None
            if zipname:
                cart = os.path.join(work, name + '.bin')
                with open(cart, 'wb') as f:
                    f.write(m.load_image_bytes(os.path.join(lib, zipname)))
            carts[name] = cart
            ex = exec_path
            if prog:
                ex = os.path.join(work, name + '_exec.bin')
                with open(os.path.join(TESTROMS, prog), encoding='utf-8') as f:
                    pr = as1610.assemble(f.read(), romw=10)
                img = bytearray(8192)
                for a_, w in pr.words.items():
                    if not 0x1000 <= a_ < 0x2000:
                        sys.exit('%s: word outside $1000-$1FFF' % prog)
                    img[2 * (a_ - 0x1000)] = w >> 8
                    img[2 * (a_ - 0x1000) + 1] = w & 0xFF
                with open(ex, 'wb') as f:
                    f.write(img)
            execs[name] = ex
            exps[name] = model_run(ex, grom_path, cart)
            eb, es, _, bus = exps[name]
            print('model %s: %d bus phases, %d step starts in %d cycles' % (name, len(eb), len(es), NCYC))
            if (a.all or a.mame) and troot and not prog:
                tr = os.path.join(troot, 'none' if name == 'nocart' else name, 'trace.log')
                if os.path.exists(tr):
                    sys.stdout.write('  MAME %s: ' % name)
                    if not isys.mame_compare(tr, bdir, cart):
                        fails.append('MAME ' + name)
                else:
                    print('  MAME %s: no trace at %s' % (name, tr))
                    fails.append('MAME trace ' + name)
        print('expectations: %.1fs' % (time.time() - t0))

        binary = os.path.join(work, 'obj', 'tb_system')
        if not a.no_build:
            t1 = time.time()
            binary = build(work, CORE, verilator)
            if not binary:
                print('TB_SYSTEM_ALL FAIL (build)')
                return 1
            print('build: %.1fs' % (time.time() - t1))
        if not a.plants_only:
            for name, _, _ in imgs:
                p = check_image(binary, work, name, execs[name], grom_path, carts[name], exps[name])
                if p:
                    fails += p
                    print('TB_SYSTEM %s FAIL' % name)
                else:
                    print('TB_SYSTEM %s pass' % name)

        if a.all or a.plants_only or a.plant:
            sel = a.plant.split(',') if a.plant else None
            for pname, f, edits, img, runs in PLANTS:
                if sel and pname not in sel:
                    continue
                if img not in exps:
                    continue
                d = os.path.join(work, 'plant_' + pname)
                shutil.rmtree(d, ignore_errors=True)
                os.makedirs(os.path.join(d, 'rtl'))
                for x in RTL:
                    shutil.copy(os.path.join(CORE, x), os.path.join(d, 'rtl', x))
                p = os.path.join(d, 'rtl', f)
                s = open(p).read()
                if not all(frm in s for frm, _ in edits):
                    print('PLANT %s: pattern not found' % pname)
                    fails.append('plant ' + pname)
                    continue
                for frm, to in edits:
                    s = s.replace(frm, to, 1)
                open(p, 'w').write(s)
                b = build(d, os.path.join(d, 'rtl'), verilator, strict=False)
                if not b:
                    print('PLANT %s: build failed' % pname)
                    fails.append('plant ' + pname)
                    continue
                pr = check_image(b, d, img, execs[img], grom_path, carts[img], exps[img], verbose=False,
                                 only_runs=runs or ['straight'])
                if pr:
                    print('PLANT %s: caught: %s' % (pname, pr[0][:150]))
                else:
                    print('PLANT %s: not caught' % pname)
                    fails.append('plant ' + pname)
    finally:
        for c in carts.values():
            if c and os.path.exists(c):
                os.remove(c)
    print('TB_SYSTEM_ALL %s' % ('pass' if not fails else 'FAIL (%s)' % ', '.join(fails[:6])))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
