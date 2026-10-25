#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Step 3 bench driver (DESIGN.md 9): the machine RTL against the system model.

"EXEC runs with no cartridge; bus log matches the Python model in lockstep",
plus the save/restore round trip of DESIGN 8.4. For each image (no
cartridge; Astrosmash from the owner's library; our sim/testroms/systest.asm
in the EXEC slot; our sim/testroms/carttest.asm with two synthetic
cartridges from tools/synth_image.py, whose CRCs are forced to table
entries with cart RAM and with paged ROM) it

  1. runs tools/intv_system.py (our CP1610 model on the step-3 system bus,
     the same device stubs and frame timing) for 10 frames (systest: 22),
     keeping its bus-phase log, the registers at every step start, every
     change of the STIC's handshake and mode latch, and the machine's
     state at the dump points; for systest, checks that section 7's probes
     land where the program says (the end of the bus-copy window);
  2. runs sim/tb/tb_system.sv (intv_machine with intv_timing, intv_media and
     the SRAM model; the system ROMs and the cartridge loaded through the
     loader's byte port) four times: straight, and with a round trip each
     (restore into a reset machine at a cartridge read or in VBlank; restore
     over a state 20,000 cycles later, which rewinds the run; restore into
     a reset machine outside VBlank; before each restore every state word,
     and the cart RAM, is overwritten with junk);
  3. compares every run with the model: every bus phase other than NACT
     with its cycle, address and data; R0-R7, S Z O C, I and D at every step
     start; every change of the handshake and the mode latch with its
     cycle; at the dumps, scratchpad, System RAM, GRAM, the STIC and PSG
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
import synth_image          # noqa: E402
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
# (name, cartridge: a file in the library or ('forced', CRC, bytes) from
# tools/synth_image.py, program for the EXEC slot instead of exec.bin,
# frames, hand controllers (right, left))
IMAGES = [('nocart', None, None, 10, (0xFF, 0xFF)),
          ('astrosmash', 'Astrosmash (USA, Europe).zip', None, 10, (0xFF, 0xFF)),
          ('systest', None, 'systest.asm', 22, (0x5A, 0xC3)),
          ('cartram', ('forced', 0xCE8FC699, 49152), 'carttest.asm', 10, (0xFF, 0xFF)),
          ('cartpaged', ('forced', 0xC2063C08, 49152), 'carttest.asm', 10, (0xFF, 0xFF))]
# systest section 7: (phase, address, frame slot) of each probe
SECT7 = [('DW', 0x002B, 3788), ('DTB', 0x3850, 3789), ('DTB', 0x002A, 3790), ('DW', 0x3851, 3791),
         ('DW', 0x3852, 3789), ('DW', 0x0030, 3790), ('DTB', 0x002B, 3789), ('DTB', 0x3E53, 3790)]
SECT7_START = 7 * FRAME
TESTROMS = os.path.join(ROOT, 'sim', 'testroms')
PHASE = {'NACT': 0, 'ADAR': 1, 'IAB': 2, 'DTB': 3, 'BAR': 4, 'DW': 5, 'DWS': 6, 'INTAK': 7}
SS = {'cpu': 0x02, 'bus': 0x03, 'stic': 0x04, 'psg': 0x05, 'scr': 0x06, 'sys': 0x07,
      'gram': 0x09, 'cart': 0x0B}


# ------------------------------------------------------------------- model
class Exp:
    """The model's expectations for one image."""

    def __init__(self, blog, steps, snaps, bus, mlog, ncyc):
        self.blog, self.steps, self.snaps, self.bus = blog, steps, snaps, bus
        self.mlog, self.ncyc = mlog, ncyc


def model_run(exec_path, grom_path, cart_path, ncyc=NCYC, pads=(0xFF, 0xFF)):
    """The model's expected log: bus phases, step starts, handshake and mode
    latch changes, state at the dumps."""
    cart = isys.load_cart(cart_path)
    bus = isys.SystemBus(isys.load_words(exec_path), open(grom_path, 'rb').read(),
                         cart[0] if cart else None)
    bus.pad = tuple(pads)
    cpu = isys.CP1610(bus=bus, buslog=True)
    snaps = {}
    want = [DUMP1, ncyc]
    orig_r, orig_w = bus.read, bus.write
    # {hs, csmode} during each cycle, as changes: the RTL changes them at the
    # ce that ends a read (DTB / ADAR) or DW cycle c, so the new value holds
    # from cycle c + 1; a frame start clears the handshake
    mlog = []
    mst = {'last': (0, 0), 'frame': 1}

    def mval(t):
        return (int(bus.handshake(t)), bus.csmode)

    def mpush(t, v):
        if v != mst['last']:
            mlog.append((t,) + v)
            mst['last'] = v

    def advance(c):
        while mst['frame'] * FRAME <= c:
            t = mst['frame'] * FRAME
            mpush(t, mval(t))
            mst['frame'] += 1

    def snap(cycle):
        while want and cycle >= want[0]:
            snaps[want[0]] = bus.state(want[0])
            want.pop(0)

    def rd(addr, cycle, kind='data'):
        snap(cycle)
        advance(cycle)
        v = orig_r(addr, cycle, kind)
        mpush(cycle + 1, mval(cycle + 1))
        return v

    def wr(addr, value, cycle):
        snap(cycle)
        advance(cycle)
        orig_w(addr, value, cycle)
        mpush(cycle + 1, mval(cycle + 1))

    bus.read, bus.write = rd, wr
    steps = []
    prev = (list(cpu.r), cpu.flags << 2 | cpu.I << 1 | cpu.D)
    while cpu.cycle < ncyc:
        ev = cpu.step()
        if ev.kind in ('insn', 'intr') and ev.cycle > 0:
            steps.append((ev.cycle, prev[0], prev[1]))
        prev = (list(ev.regs), ev.flags << 2 | ev.i << 1 | ev.d)
    snap(ncyc)
    advance(ncyc - 1)
    blog = [(c, PHASE[p], a or 0, d or 0) for (c, p, a, d) in cpu.buslog
            if c < ncyc and p != 'NACT']
    steps = [s for s in steps if s[0] < ncyc]
    mlog = [x for x in mlog if x[0] < ncyc]
    return Exp(blog, steps, snaps, bus, mlog, ncyc)


def check_sect7(exp, symbols):
    """systest section 7: each probe in its slot (frames from 7 on), and the
    two INTRM-end probes: p9x's NOP ends in slot 3789 and no INTAK follows,
    p10x's ends in 3788 and the INTAK is in slot 3789. Problems as strings."""
    probs = []
    blog = exp.blog
    for k, (ph, a, slot) in enumerate(SECT7, 1):
        hit = [b[0] for b in blog if b[1] == PHASE[ph] and b[2] == a and b[0] >= SECT7_START]
        if not hit or hit[0] % FRAME != slot:
            probs.append('systest probe %d (%s %04X): slot %s, want %d' % (
                k, ph, a, hit[0] % FRAME if hit else 'none', slot))
    for lab, slot, taken in (('p9x', 3784, False), ('p10x', 3783, True)):
        a = symbols[lab]
        i = [j for j, b in enumerate(blog) if b[1] == PHASE['BAR'] and b[2] == a and b[0] >= SECT7_START]
        if not i or blog[i[0]][0] % FRAME != slot:
            probs.append('systest %s: fetch in slot %s, want %d' % (
                lab, blog[i[0]][0] % FRAME if i else 'none', slot))
            continue
        nxt = [b for b in blog[i[0] + 1:] if b[1] in (PHASE['BAR'], PHASE['INTAK'])][0]
        if (nxt[1] == PHASE['INTAK']) != taken or (taken and nxt[0] % FRAME != slot + 6):
            probs.append('systest %s: next %s at slot %d' % (lab, fmt_b(nxt), nxt[0] % FRAME))
    return probs


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
    blog, steps, dumps, notes, fails, mlog = [], [], {}, [], [], []
    for ln in open(path):
        t = ln.split()
        if not t:
            continue
        if t[0] == 'B':
            blog.append((int(t[1]), int(t[2]), int(t[3], 16), int(t[4], 16)))
        elif t[0] == 'S':
            if int(t[1]) > 0:
                steps.append((int(t[1]), [int(x, 16) for x in t[2:10]], int(t[10], 16)))
        elif t[0] == 'M':
            mlog.append((int(t[1]), int(t[2]), int(t[3])))
        elif t[0] == 'W':
            dumps.setdefault(int(t[1]), {})[(int(t[2], 16), int(t[3]))] = int(t[4], 16)
        elif t[0] == 'R' and t[1] == 'rewind':
            c = int(t[2])
            notes.append(ln.strip())
            blog = [b for b in blog if b[0] < c]
            steps = [s for s in steps if s[0] < c]
            mlog = [x for x in mlog if x[0] < c]
        elif t[0] in ('R', 'L'):
            notes.append(ln.strip())
        elif t[0] == 'FAIL':
            fails.append(ln.strip())
    dedup, last = [], (0, 0)
    for x in mlog:                      # a restore logs the value again
        if x[1:] != last:
            dedup.append(x)
            last = x[1:]
    return blog, steps, dumps, notes, fails, dedup


def fmt_b(b):
    if b is None:
        return '(none)'
    inv = {v: k for k, v in PHASE.items()}
    return 'c=%d %s %04X %04X' % (b[0], inv[b[1]], b[2], b[3])


def compare(name, run, got, exp):
    """Problems of one run against the model (a list of strings)."""
    blog, steps, dumps, notes, fails, mlog = got
    eb, es, snaps = exp.blog, exp.steps, exp.snaps
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
    for i in range(max(len(mlog), len(exp.mlog))):
        g = mlog[i] if i < len(mlog) else None
        e = exp.mlog[i] if i < len(exp.mlog) else None
        if g != e:
            probs.append('handshake / mode latch change %d (cycle, hs, csmode): RTL %s, model %s' % (i, g, e))
            break
    for k, cyc in ((1, DUMP1), (2, exp.ncyc)):
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


def run_bench(binary, work, tag, exec_path, grom_path, cart_path, args, exp, pads, timeout=1200):
    log = os.path.join(work, 'run_%s.log' % tag)
    cmd = [binary, '+exec=' + exec_path, '+grom=' + grom_path, '+cycles=%d' % exp.ncyc,
           '+dump=%d' % DUMP1, '+log=' + log, '+pads=%02X%02X' % tuple(pads)] + args
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
    eb = exp.blog
    cart_dtb = [b[0] for b in eb if b[1] == PHASE['DTB'] and b[0] < DUMP1 and
                exp.bus.cart is not None and exp.bus.cart.read(b[2]) is not None]
    c1 = cart_dtb[-1] if cart_dtb else 5 * FRAME + 600
    return [('straight', []),
            ('rt1', ['+rt=1', '+rtcyc=%d' % c1, '+rtsub=17']),
            ('rt2', ['+rt=2', '+rtcyc=%d' % (5 * FRAME + 600), '+rtsub=30', '+rton=20000']),
            ('rt3', ['+rt=1', '+rtcyc=%d' % (5 * FRAME + 6000), '+rtsub=3'])]


def check_image(binary, work, name, exec_path, grom_path, cart_path, exp, pads, verbose=True,
                only_runs=None):
    probs = []
    results = {}
    for tag, args in rt_runs(exp):
        if only_runs and tag not in only_runs:
            continue
        t0 = time.time()
        got = run_bench(binary, work, '%s_%s' % (name, tag), exec_path, grom_path, cart_path, args, exp,
                        pads)
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
    # state port: one RAM whose restore writes are lost (reads still work);
    # rt1 writes junk after the reset, so the old contents cannot hide it
    ('ss_gram_wr_lost', 'intv_ram.sv', [("wire logic          wa = ss_en ? ss_we && ss_hit : we;",
                                         "wire logic          wa = ss_en ? ss_we && ss_hit && SS_ID != 8'h09 : we;")],
     'systest', ['rt1']),
    ('ss_scr_wr_lost', 'intv_ram.sv', [("wire logic          wa = ss_en ? ss_we && ss_hit : we;",
                                        "wire logic          wa = ss_en ? ss_we && ss_hit && SS_ID != 8'h06 : we;")],
     'systest', ['rt1']),
    ('ss_sys_wr_lost', 'intv_ram.sv', [("wire logic          wa = ss_en ? ss_we && ss_hit : we;",
                                        "wire logic          wa = ss_en ? ss_we && ss_hit && SS_ID != 8'h07 : we;")],
     'systest', ['rt1']),
    # the mode latch (the change log)
    ('csmode_no_alias', 'intv_stic_regs.sv', [("if (rd && open && a[13:0] == 14'h0021)",
                                               "if (rd && open && a == 16'h0021)")], 'systest', None),
    ('csmode_no_open', 'intv_stic_regs.sv', [("if (rd && open && a[13:0] == 14'h0021)",
                                              "if (rd && a[13:0] == 14'h0021)")], 'systest', None),
    ('csmode_wr_kept', 'intv_stic_regs.sv', [("                if (n == 6'h21)\n                    csmode <= 1'b0;\n",
                                              "")], 'systest', None),
    # the end of the bus-copy window and of INTRM (systest section 7)
    ('vb_end_p1', 'intv_bus.sv', [("assign vb        = slot < 16'(VB_CYCLES);",
                                   "assign vb        = slot < 16'(VB_CYCLES + 1);")], 'systest', None),
    ('vb_end_m1', 'intv_bus.sv', [("assign vb        = slot < 16'(VB_CYCLES);",
                                   "assign vb        = slot < 16'(VB_CYCLES - 1);")], 'systest', None),
    ('intrm_end_p1', 'intv_bus.sv', [("vb_next = last || slot < 16'(VB_CYCLES - 1);",
                                      "vb_next = last || slot < 16'(VB_CYCLES);")], 'systest', None),
    ('intrm_end_m1', 'intv_bus.sv', [("vb_next = last || slot < 16'(VB_CYCLES - 1);",
                                      "vb_next = last || slot < 16'(VB_CYCLES - 2);")], 'systest', None),
    # hand controllers swapped (systest drives two different pads)
    ('pads_swapped', 'intv_psg_regs.sv', [("4'd14:   q = pad_r;\n            4'd15:   q = pad_l;",
                                           "4'd14:   q = pad_l;\n            4'd15:   q = pad_r;")], 'systest', None),
    # a closed GRAM read gives 11 offset bits (systest reads through $3A00 / $3E00)
    ('gram_closed_11', 'intv_bus.sv', [("din &= stic_open ? {8'h00, gram_q} : {7'd0, a[8:0]};",
                                        "din &= stic_open ? {8'h00, gram_q} : {5'd0, a[10:0]};")],
     'systest', None),
    # the cartridge port not asked on a write (carttest: cart RAM, page selects)
    ('cart_write_no', 'intv_bus.sv', [("                end else if (phase == PH_DW) begin\n                    cart_req   <= 1'b1;",
                                       "                end else if (phase == PH_DW) begin\n                    cart_req   <= 1'b0;")],
     'cartram', None),
    ('cart_write_low', 'intv_bus.sv', [("                    cart_wdata <= dout;",
                                        "                    cart_wdata <= {8'h00, dout[7:0]};")], 'cartpaged', None),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--all', action='store_true', help='images, MAME, then planted faults')
    ap.add_argument('--only', help='comma-separated image names (nocart, astrosmash, systest, '
                                   'cartram, cartpaged)')
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
    pads = {}
    fails = []
    t0 = time.time()
    try:
        for name, zipname, prog, nframes, pad in imgs:
            cart = None
            if isinstance(zipname, tuple):        # synthetic, CRC forced to a table entry
                cart = os.path.join(work, name + '.bin')
                with open(cart, 'wb') as f:
                    f.write(synth_image.forced(zipname[1], zipname[2]))
            elif zipname:
                cart = os.path.join(work, name + '.bin')
                with open(cart, 'wb') as f:
                    f.write(m.load_image_bytes(os.path.join(lib, zipname)))
            carts[name] = cart
            pads[name] = pad
            ex = exec_path
            if prog:
                ex = os.path.join(work, name + '_exec.bin')
                with open(os.path.join(TESTROMS, prog), encoding='utf-8') as f:
                    pr = as1610.assemble(f.read(), romw=10)
                img = bytearray(8192)
                for a_, w in pr.words.items():
                    if not 0x1000 <= a_ < 0x2000:
                        sys.exit('%s: word outside $1000-$1FFF' % prog)
                    if w > 0x3FF:       # the EXEC ROM keeps 10 bits: an operand would be cut
                        sys.exit('%s: word $%04X at $%04X is over 10 bits' % (prog, w, a_))
                    img[2 * (a_ - 0x1000)] = w >> 8
                    img[2 * (a_ - 0x1000) + 1] = w & 0xFF
                with open(ex, 'wb') as f:
                    f.write(img)
            execs[name] = ex
            exps[name] = model_run(ex, grom_path, cart, nframes * FRAME, pad)
            e = exps[name]
            print('model %s: %d bus phases, %d step starts, %d latch changes in %d cycles' % (
                name, len(e.blog), len(e.steps), len(e.mlog), e.ncyc))
            if prog == 'systest.asm':
                p7 = check_sect7(e, pr.symbols)
                print('  systest section 7: %s' % ('every probe in its slot' if not p7 else '; '.join(p7)))
                fails += p7
            if cart and e.bus.cart is not None:
                cw = sum(1 for b in e.blog if b[1] == PHASE['DW'] and e.bus.cart.read(b[2]) is not None)
                sw = sum(1 for b in e.blog if b[1] == PHASE['DW'] and (b[2] & 0xFFF) == 0xFFF
                         and b[3] >> 4 == (b[2] >> 12) << 8 | 0xA5)
                print('  %s: %d writes to cartridge RAM/ROM, %d page selects' % (name, cw, sw))
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
            for name, _, _, _, _ in imgs:
                p = check_image(binary, work, name, execs[name], grom_path, carts[name], exps[name],
                                pads[name])
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
                pr = check_image(b, d, img, execs[img], grom_path, carts[img], exps[img], pads[img],
                                 verbose=False, only_runs=runs or ['straight'])
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
