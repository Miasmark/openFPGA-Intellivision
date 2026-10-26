#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Step 7 bench driver (DESIGN.md 9: "Pocket save, load and sleep work on the regression
set"; docs/SAVESTATE.md): sim/tb/tb_savestate.sv, the core as core_top has it behind the
APF command handler, driven the way the Pocket drives it.

For each image of the regression set (SS_IMAGES: the EXEC with no cartridge, Astrosmash
in play with keys, B-17 Bomber in flight, Atlantis, Buzz Bombers, our sticmob and psgtest):
  R  a straight run: the reference, frame by frame (bus phases and CPU steps, PSG steps
     and samples, picture: the H, A and P lines, in machine frames);
  S  the same run with saves at several points (each asked for at a chosen moment: in the
     middle of an instruction, inside a BUSRQ, during a row fetch, while the PSG sounds),
     a menu pause of some frames, and a save inside a menu pause (sleep); every frame
     must equal R's, every save must answer ok, every blob must pass tools/savestate.py's
     checks, and its CPU and timing words must be what the machine held at the freeze;
  L  for each blob, a fresh core (the same cartridge, booted for a frame or so) loads it:
     ok, and every frame after the restore equals R's from the saved cycle on (one load
     is made inside a menu pause: wake from sleep);
  F  a core running this image loads another image's blob: err, and the run goes on as
     R, untouched;
  C  corrupt and wrong blobs (a payload byte flipped, the header CRC changed, a reserved
     byte set, the version changed, the unused module area set) each give err with the
     run untouched, then the good blob loads.
Planted faults (PLANTS, each a change to a copy of the RTL) must each make a check fail:
a module dropped from the stream, a word off by one, the CRC not checked, the resume
at the wrong position (one CPU cycle late: four pixel clocks; a slip that skips no CPU or
STIC enable in VBlank changes nothing in the machine), the cartridge not checked, the
system ROMs not checked, the cart RAM not restored or one word off, the menu ignored, a
bridge access's direction not latched (B's race), the PSG's envelope counter (0 at boot)
ignored on restore. A plant counts as caught only when a problem matches its own reason.

  python3 -I sim/tb/tb_savestate.py [--only nocart,psgtest] [--plants] [--no-build]
                                    [--jobs 2] [--plants-only]
Environment: VERILATOR, WORK (default sim/work/tb_savestate), INTV_LIBRARY, INTV_BIOS_DIR
(as tb_system.py), SIMSLOT (a command each simulation runs under, e.g.
~/daria_work/bin/simslot; with --jobs N at most N wait at once). Last line
"TB_SAVESTATE_ALL pass" or "TB_SAVESTATE_ALL FAIL (...)".
"""
import argparse
import concurrent.futures
import os
import re
import shutil
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'mapper'))
import as1610               # noqa: E402
import intv_system as isys  # noqa: E402
import intvcart as m        # noqa: E402
import savestate as ss      # noqa: E402

CORE = os.path.join(ROOT, 'src', 'fpga', 'core')
RTL = ['intv_ss_pkg.sv', 'cp1610.sv', 'intv_bus.sv', 'intv_stic.sv', 'intv_psg.sv', 'intv_ram.sv',
       'intv_machine.sv', 'intv_timing.sv', 'intv_sram.sv', 'intv_cart.sv', 'intv_sysrom.sv',
       'intv_loader.sv', 'intv_cfgparse.sv', 'intv_romparse.sv', 'intv_pagesel.sv', 'intv_media.sv', 'intv_ss_ctl.sv', 'intv_core.sv', 'core_bridge_cmd.v']
OTHER = [os.path.join(ROOT, 'src', 'fpga', 'apf', 'common.v'),
         os.path.join(HERE, 'models', 'sram_as6c2016.sv'),
         os.path.join(HERE, 'models', 'mf_datatable.sv'), os.path.join(HERE, 'tb_savestate.sv')]
TESTROMS = os.path.join(ROOT, 'sim', 'testroms')
FRAME = 14934

# (name, library file or None, EXEC-slot program or None, pads (R, L), frames,
#  keys (tb_system PLAY notation) or None,
#  saves: [(frame, kind)] (kind: midinst, busrq, rowfetch, sound, any),
#  menu pause (frame, raster frames), save inside a menu at frame)
SS_IMAGES = [
    ('nocart', None, None, (0xFF, 0xFF), 40, None,
     [(6, 'midinst'), (12, 'any'), (18, 'midinst'), (24, 'any')], (28, 20), 32),   # display off
    ('astrosmash', 'Astrosmash (USA, Europe).zip', None, (0xFF, 0xFF), 700,
     '200-206:1,300-400:Upper,400-480:Left,480-600:Right,600-700:Lower-Right',
     [(330, 'sound'), (420, 'busrq'), (500, 'rowfetch'), (560, 'midinst')], (600, 30), 640),
    ('b17bomber', 'B-17 Bomber (USA, Europe).zip', None, (0xFF, 0xFF), 1000,
     '200-206:1,500-506:Enter,600-630:Right,700-730:Down,800-806:0,900-960:Left',
     [(860, 'sound'), (890, 'busrq'), (910, 'rowfetch'), (930, 'midinst')], (945, 30), 965),
    ('atlantis', 'Atlantis (USA, Europe).zip', None, (0xFF, 0xFF), 360,
     '150-156:1,220-230:Up,280-320:Left',
     [(200, 'busrq'), (250, 'rowfetch'), (290, 'midinst'), (300, 'any')], (310, 20), 330),
    ('buzzbombers', 'Buzz Bombers (USA, Europe).zip', None, (0xFF, 0xFF), 360,
     '150-156:1,250-300:Left,300-330:Upper',
     [(200, 'sound'), (260, 'rowfetch'), (290, 'busrq'), (300, 'midinst')], (310, 20), 330),
    ('sticmob', None, 'sticmob.asm', (0xFF, 0xFF), 46, None,
     [(10, 'rowfetch'), (20, 'busrq'), (30, 'midinst'), (34, 'any')], (36, 10), 40),
    ('psgtest', None, 'psgtest.asm', (0x5A, 0xC3), 22, None,
     [(6, 'sound'), (11, 'sound'), (14, 'midinst'), (16, 'any')], (17, 10), 19),
    # build step 8: our cart8test.asm on an Intellicart .rom (bank windows, RAM) and on a
    # BIN + CFG (pages, RAM): non-default pages and bank registers, cart RAM in use
    ('cartbank', ('step8', 'rombank'), 'cart8test.asm', (0xFF, 0xFF), 40, None,
     [(6, 'midinst'), (12, 'any'), (18, 'midinst'), (24, 'any')], (28, 8), 32),
    ('cartcfg', ('step8', 'cfgmap'), 'cart8test.asm', (0xFF, 0xFF), 40, None,
     [(7, 'midinst'), (13, 'any'), (19, 'midinst'), (25, 'any')], (28, 8), 32),
    # cart RAM (RAM8 at $D000, 1,024 cells): a game started, its board in RAM
    ('chess', 'USCF Chess ~ Chess (USA, Europe).zip', None, (0xFF, 0xFF), 100,
     '40-46:1,60-66:Enter',
     [(55, 'any'), (65, 'busrq'), (75, 'midinst'), (78, 'any')], (82, 6), 86),
]
FRAMES_AFTER = 24          # an L run goes on this many frames after the restore
LOAD_AT = FRAME            # fresh cores load from machine cycle 1 frame on
DEEP_AFTER = 40            # D: s0 loaded into a core this many frames past its save point
PAUSE0_IMAGES = ('psgtest',)   # S0: the S run with Pause in Menu off
BURST_IMAGES = ('psgtest',)    # B: bridge reads while a save reads the state
SOUND_ZERO_CLKS = 171818       # 4 ms of clk_sys: the sound is 0 by then (intv_core.sv)


def cram_hash(cells):
    """FNV-1a over the cart RAM cells, as tb_savestate.sv's M lines."""
    h = 0x811C9DC5
    for c in cells:
        h = ((h ^ c) * 0x01000193) & 0xFFFFFFFF
    return h


def blob_cram(path):
    cram = ss.unpack(open(path, 'rb').read())[2]
    return cram_hash(cram), sum(1 for c in cram if c)


def build(work, rtl_dir, verilator, strict=True):
    obj = os.path.join(work, 'obj')
    os.makedirs(work, exist_ok=True)
    tables = os.path.join(CORE, 'tables')
    cmd = [verilator, '--binary', '--timing', '-j', '4', '-Wall', '-Wno-fatal', '-Wno-TIMESCALEMOD',
           '-Wno-PROCASSINIT', '--top-module', 'tb_savestate', '-Mdir', obj, '-o', 'tb_savestate',
           '-DCRC_HEX="%s"' % os.path.join(tables, 'cart_crc.hex'),
           '-DLAYOUT_HEX="%s"' % os.path.join(tables, 'cart_layouts.hex')]
    cmd += [os.path.join(rtl_dir, f) for f in RTL] + OTHER
    log = os.path.join(work, 'build.log')
    for attempt in (1, 2):             # Verilator 5.040 can rarely fault on a build: once more
        with open(log, 'w') as f:
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
        if r.returncode == 0:
            break
    text = open(log).read()
    if r.returncode != 0:
        print(text[-3000:])
        return None
    ours = [ln for ln in text.splitlines() if ln.startswith('%Warning') and
            any(('/' + f + ':') in ln for f in RTL if f.startswith('intv_ss') or f == 'intv_core.sv')]
    if ours and strict:
        print('\n'.join(ours[:20]))
        return None
    return os.path.join(obj, 'tb_savestate')


# an image whose state the blob cannot hold (docs/CARTFORMATS.md 5): every save and load
# answers err, the run untouched
NOSS_IMAGES = [('cartnoss', ('step8', 'rombankw'), 'cart8test.asm', (0xFF, 0xFF), 16, None,
                [(5, 'midinst'), (9, 'any')], (12, 4), 14)]


def prepare(work, img, lib, bdir):
    """(exec path, cart path or None, keys file or None, cart CRC, cart words, EXEC CRC,
    GROM CRC, CFG path or None, CFG CRC)."""
    name, zipname, prog, pads, nframes, keys = img[:6]
    ex = os.path.join(bdir, 'exec.bin')
    if prog:
        ex = os.path.join(work, name + '_exec.bin')
        with open(os.path.join(TESTROMS, prog), encoding='utf-8') as f:
            pr = as1610.assemble(f.read(), romw=10)
        b = bytearray(8192)
        for a, w in pr.words.items():
            b[2 * (a - 0x1000)] = w >> 8
            b[2 * (a - 0x1000) + 1] = w & 0xFF
        with open(ex, 'wb') as f:
            f.write(b)
    cart, crc, words, cfgp, cfgcrc = None, 0, 0, None, 0
    if isinstance(zipname, tuple):             # a step-8 image from our sources
        sys.path.insert(0, os.path.join(ROOT, 'sim', 'testroms', 'step8'))
        import build_images
        import cartfmt
        im = [x for x in build_images.images() if x['name'] == zipname[1]][0]
        cart = os.path.join(work, name + ('.rom' if cartfmt.is_rom(im['data']) else '.bin'))
        with open(cart, 'wb') as f:
            f.write(im['data'])
        crc, words = ss.crc32(im['data']), (len(im['data']) + 1) // 2
        if im['cfg'] is not None:
            cfgp = os.path.join(work, name + '.cfg')
            with open(cfgp, 'wb') as f:
                f.write(im['cfg'])
            cfgcrc = ss.crc32(im['cfg'])
    elif zipname:
        data = m.load_image_bytes(os.path.join(lib, zipname))
        cart = os.path.join(work, name + '.bin')
        with open(cart, 'wb') as f:
            f.write(data)
        crc, words = ss.crc32(data), (len(data) + 1) // 2
    kf = None
    if keys:
        presses = isys.parse_presses(keys)
        kf = os.path.join(work, name + '.keys')
        out, last = [], None
        for k in range(nframes + 2):
            v = isys.press_pads(presses, k - 1)
            if v != last:
                out.append('%d %02X%02X\n' % (k, v, v))
                last = v
        with open(kf, 'w') as f:
            f.writelines(out)
    return (ex, cart, kf, crc, words, ss.crc32(open(ex, 'rb').read()),
            ss.crc32(open(os.path.join(bdir, 'grom.bin'), 'rb').read()), cfgp, cfgcrc)


class Run:
    def __init__(self, path):
        self.frames = {}          # (kind, k) -> line, the last one before any set, and after
        self.after = {}           # frames printed after "R set"
        self.set_cycle = None
        self.lines = []
        self.fails = []
        self.end = False
        for ln in open(path):
            ln = ln.rstrip('\n')
            t = ln.split()
            if not t:
                continue
            if t[0] in ('H', 'A', 'P'):
                key = (t[0], int(t[1]))
                if self.set_cycle is None:
                    self.frames[key] = ln
                else:
                    self.after[key] = ln
                continue
            self.lines.append(ln)
            if ln.startswith('R set cycle'):
                self.set_cycle = int(t[3])
            elif t[0] == 'FAIL':
                self.fails.append(ln)
            elif t[0] == 'END':
                self.end = True

    def tagged(self, tag):
        return [ln for ln in self.lines if ln.split()[0] == tag]


def compare_frames(ref, got, lo, hi, what, steps_only=False):
    """Frames lo .. hi-1 of got (a dict of lines) against ref.frames; problems.
    steps_only: of the A lines only the PSG's steps (hash and count), not its
    48 kHz samples: the output filter and its sample phase are not machine
    state (DESIGN.md 4.4), so after a load they need not match."""
    probs = []
    for k in range(lo, hi):
        for t in 'HAP':
            a, b = ref.frames.get((t, k)), got.get((t, k))
            if a is not None and b is not None and t == 'A' and steps_only:
                a, b = a.split()[:4], b.split()[:4]
            if a is None or b is None:
                probs.append('%s: frame %d %s line missing (%s)' % (what, k, t, 'ref' if a is None else 'run'))
            elif a != b:
                probs.append('%s: frame %d differs: %s | ref %s' % (what, k, b, a))
            if len(probs) > 3:
                return probs
    return probs


class Bench:
    def __init__(self, binary, work, bdir, lib, simslot, jobs):
        self.binary, self.work, self.bdir, self.lib = binary, work, bdir, lib
        self.simslot = simslot
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=jobs)
        self.prep = {}

    def sim(self, tag, img, ncyc, script_lines, extra=()):
        """Run the bench; returns (Run, log path)."""
        name = img[0]
        ex, cart, kf = self.prep[name][:3]
        sf = os.path.join(self.work, tag + '.script')
        with open(sf, 'w') as f:
            f.write(''.join(x + '\n' for x in script_lines))
        log = os.path.join(self.work, tag + '.log')
        cmd = [self.binary, '+exec=' + ex, '+grom=' + os.path.join(self.bdir, 'grom.bin'),
               '+cycles=%d' % ncyc, '+script=' + sf, '+log=' + log, '+pads=%02X%02X' % img[3]]
        if cart:
            cmd.append('+cart=' + cart)
        if self.prep[name][7]:
            cmd.append('+cfg=' + self.prep[name][7])
        if kf:
            cmd.append('+keys=' + kf)
        cmd += list(extra)
        if self.simslot:
            cmd = [self.simslot] + cmd
        t0 = time.time()
        with open(os.path.join(self.work, tag + '.out'), 'w') as out:
            r = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, cwd=self.work, timeout=14400)
        run = Run(log) if os.path.exists(log) else None
        if run is not None and r.returncode != 0:
            run.fails.append('FAIL exit code %d' % r.returncode)
        print('  ran %s: %.0fs' % (tag, time.time() - t0), flush=True)
        return run

    def blob_path(self, name, i, tag='s'):
        return os.path.join(self.work, '%s_%s%d.blob' % (name, tag, i))


def save_script(img, bench, tag='s'):
    name, _, _, _, nframes, _, saves, menu, menu_save = img
    lines, blobs = [], []
    events = [(f, 'save', kind) for f, kind in saves] + [(menu[0], 'menu', menu[1]),
                                                         (menu_save, 'msave', None)]
    for f, what, x in sorted(events):
        if what == 'save':
            p = bench.blob_path(name, len(blobs), tag)
            lines.append('save %d %s %s' % (f * FRAME, x, p))
            blobs.append((p, x))
        elif what == 'menu':
            lines += ['menu %d 1' % (f * FRAME), 'wait %d' % x, 'menu 0 0']
        else:                                  # sleep: menu open, save, menu closed later
            p = bench.blob_path(name, len(blobs), tag)
            lines += ['menu %d 1' % (f * FRAME), 'save 0 any %s' % p, 'wait 5', 'menu 0 0']
            blobs.append((p, 'menu'))
    return lines, blobs


def check_menu(run, pause, what):
    """Each menu window (MENU open .. MENU 0) of a run. Pause on: one freeze
    (Z) and one resume (U) in it, at the same machine cycle; the freeze within
    a frame of the menu opening; every wait ends at the freeze's cycle (the
    machine's time stands still); the raster frames frozen (U) about the
    waits'. Pause off: the machine runs through the menu (no freeze but a
    save's; each wait advances the machine by its frames). The sound and
    live are checked on every clk by the bench (FAIL lines)."""
    probs, win, n = [], None, 0
    for ln in run.lines:
        t = ln.split()
        if t[0] == 'MENU' and t[1] == 'open':
            win = {'c': int(t[2]), 'Z': [], 'U': [], 'W': [], 'SAVE': []}
        elif win is not None and t[0] in ('Z', 'U', 'W', 'SAVE'):
            win[t[0]].append(t)
        elif win is not None and t[0] == 'MENU' and t[1] == '0':
            n += 1
            fr = sum(int(w[1]) for w in win['W'])
            slack = 6 if win['SAVE'] else 2       # a save inside: the blob's read-out too
            tag = '%s: menu %d (open at cycle %d)' % (what, n, win['c'])
            if pause:
                if len(win['Z']) != 1 or len(win['U']) != 1:
                    probs.append('%s: %d freezes, %d resumes, want 1 each' % (tag, len(win['Z']), len(win['U'])))
                else:
                    zc, uc, uf = int(win['Z'][0][1]), int(win['U'][0][1]), int(win['U'][0][2])
                    if zc != uc:
                        probs.append('%s: frozen at cycle %d, resumed at %d' % (tag, zc, uc))
                    if not 0 <= zc - win['c'] <= FRAME + 64:
                        probs.append('%s: froze at cycle %d, %d after the menu opened' % (tag, zc, zc - win['c']))
                    for w in win['W']:
                        if int(w[3]) != zc:
                            probs.append('%s: a wait ended at cycle %s, frozen at %d' % (tag, w[3], zc))
                    if not fr - 1 <= uf <= fr + slack:
                        probs.append('%s: frozen %d raster frames, waits %d' % (tag, uf, fr))
            else:
                if len(win['Z']) != len(win['SAVE']) or len(win['U']) != len(win['SAVE']):
                    probs.append('%s: pause off, %d freezes for %d saves' % (tag, len(win['Z']), len(win['SAVE'])))
                for w in win['W']:
                    if int(w[3]) - int(w[2]) < (int(w[1]) - 1) * FRAME:
                        probs.append('%s: pause off, a wait of %s frames ran %d cycles' % (
                            tag, w[1], int(w[3]) - int(w[2])))
            win = None
    if n != 2:
        probs.append('%s: %d menu windows, want 2' % (what, n))
    return probs


def check_common(run, what, drops=0):
    """FAIL lines, END, the bridge accesses overwritten (E drops)."""
    probs = list(run.fails)
    if not run.end:
        probs.append('%s: no END' % what)
    e = run.tagged('E')
    got = int(e[0].split()[2]) if e else None
    if got is None or (got != 0 if drops == 0 else got < drops):
        probs.append('%s: bridge accesses overwritten: %s, want %s' % (what, got, drops or '0'))
    return probs


def check_save_run(img, ref, run, blobs, crc, words, ecrc, gcrc, cfgcrc=0, pause=True, what='S'):
    probs = check_common(run, what)
    nframes = img[4]
    probs += compare_frames(ref, run.frames, 0, nframes, what)
    probs += check_menu(run, pause, what)
    for ln in run.lines:              # a save asked for at its moment's end: never in it
        if ln.startswith('R kind '):
            probs.append('%s: %s' % (what, ln))
    saves = run.tagged('SAVE')
    if len(saves) != len(blobs) or any(s.split()[1] != 'ok' for s in saves):
        probs.append('S: saves %s' % saves)
        return probs, []
    # the Q (request seen) and Z (frozen) lines, one each per save; the menu
    # pause freezes too (a Z without a Q)
    # each save's request (Q) and the freeze it was taken in: the last Z
    # before its SAVE line (a menu pause may have frozen the machine first)
    qs, zs, ms, last_z, last_m = [], [], [], None, None
    for ln in run.lines:
        t = ln.split()
        if t[0] == 'Z':
            last_z = ln
        elif t[0] == 'M':
            last_m = ln
        elif t[0] == 'Q' and t[1] == 'save':
            qs.append(ln)
        elif t[0] == 'SAVE':
            zs.append(last_z)
            ms.append(last_m)
    info = []
    for (p, kind), s, q, z, mline in zip(blobs, saves, qs, zs, ms):
        qt = q.split()
        cond = {'busrq': qt[4] == '1', 'rowfetch': qt[6] == '1', 'midinst': qt[8] == '0',
                'sound': qt[10] != '0'}.get(kind, True)
        if not cond:
            probs.append('S: %s request seen outside its condition: %s' % (kind, q))
        if z is None:
            probs.append('S: no freeze for %s' % s)
            continue
        zt = z.split()
        zc, mpos = int(zt[1]), int(zt[2], 16)
        regs = [int(x, 16) for x in zt[3:11]]
        blob = open(p, 'rb').read()
        bad = ss.verify(blob, crc, words, exec_crc=ecrc, grom_crc=gcrc, cfg_crc=cfgcrc)
        if bad:
            probs.append('S: blob %s: %s' % (os.path.basename(p), bad[:3]))
            continue
        h, mods, cram = ss.unpack(blob)
        want_m = '%08x %d' % (cram_hash(cram), sum(1 for c in cram if c))
        if mline is None or ' '.join(mline.split()[2:4]) != want_m:
            probs.append('S: blob %s: cart RAM %s, the SRAM at the freeze %s' % (
                os.path.basename(p), want_m, mline))
        if ss.pack(mods, cram, h[ss.H_CART_CRC], h[ss.H_CART_WORDS], exec_crc=h[ss.H_EXEC_CRC],
                   grom_crc=h[ss.H_GROM_CRC], cfg_crc=h[ss.H_CFG_CRC]) != blob:
            probs.append('S: blob %s: pack(unpack) differs' % os.path.basename(p))
        cpu = mods[0x02]
        want = [(regs[1] << 16) | regs[0], (regs[3] << 16) | regs[2], (regs[5] << 16) | regs[4],
                (regs[7] << 16) | regs[6]]
        if cpu[:4] != want or mods[0x01][0] != mpos:
            probs.append('S: blob %s: CPU/timing words %s %08X, frozen machine %s %08X' % (
                os.path.basename(p), ['%08X' % x for x in cpu[:4]], mods[0x01][0],
                ['%08X' % x for x in want], mpos))
        vc, hc = mpos >> 13, (mpos >> 4) & 0x1FF
        if vc >= 60:
            probs.append('S: freeze outside VBlank: vcnt %d hcnt %d' % (vc, hc))
        info.append((p, zc, kind))
    return probs, info


def corrupt_blobs(work, name, good):
    b = open(good, 'rb').read()
    out = []

    def put(tag, data):
        p = os.path.join(work, '%s_bad_%s.blob' % (name, tag))
        with open(p, 'wb') as f:
            f.write(data)
        out.append(p)
    x = bytearray(b)
    x[ss.MOD_BYTE + 4 * 1 + 3] ^= 0x01               # CPU R0 low byte
    put('payload', bytes(x))
    x = bytearray(b)
    struct.pack_into('>I', x, 4 * ss.H_CRC, ss.header(b)[ss.H_CRC] ^ 0x80000000)
    put('crcfield', bytes(x))
    x = bytearray(b)
    x[100000] = 0x5A                                 # beyond the live part
    put('reserved', bytes(x))
    x = bytearray(b)
    struct.pack_into('>I', x, 4 * ss.H_VERSION, 1)    # an older version's blob
    put('version', bytes(x))
    x = bytearray(b)                                 # another CFG for the same image
    struct.pack_into('>I', x, 4 * ss.H_CFG_CRC, ss.header(b)[ss.H_CFG_CRC] ^ 0x00000100)
    put('cfgcrc', bytes(x))
    x = bytearray(b)                                 # unused module area, CRC made right
    x[ss.MOD_BYTE + 4 * ss.MOD_WORDS + 8] = 0x01
    struct.pack_into('>I', x, 4 * ss.H_CRC, ss.crc32(x[ss.MOD_BYTE:ss.MOD_BYTE + ss.PAYLOAD_BYTES]))
    put('gap', bytes(x))
    for p in out:
        if not ss.verify(open(p, 'rb').read()):
            raise SystemExit('corrupt blob %s passes the model' % p)
    return out


def run_image_set(bench, imgs, other_blob, tagp=''):
    """Every run of every image; returns problems (strings)."""
    probs = []
    refs, saves = {}, {}
    futs = {}
    for img in imgs:
        name, nframes = img[0], img[4]
        lines, blobs = save_script(img, bench)
        futs[(name, 'R')] = bench.pool.submit(bench.sim, tagp + name + '_R', img, nframes * FRAME, [])
        futs[(name, 'S')] = bench.pool.submit(bench.sim, tagp + name + '_S', img, nframes * FRAME, lines)
        saves[name] = blobs
        if name in PAUSE0_IMAGES:              # the same with Pause in Menu off
            l0, b0 = save_script(img, bench, tag='p')
            futs[(name, 'S0')] = (b0, bench.pool.submit(bench.sim, tagp + name + '_S0', img,
                                                        nframes * FRAME, l0, ['+pause=0']))
    for img in imgs:
        name = img[0]
        ref, srun = futs[(name, 'R')].result(), futs[(name, 'S')].result()
        if ref is None or srun is None or not ref.end or ref.fails:
            probs.append('%s: R or S did not run (%s)' % (name, ref.fails[:2] if ref else 'no log'))
            continue
        refs[name] = ref
        p, info = check_save_run(img, ref, srun, saves[name], *bench.prep[name][3:7],
                                 cfgcrc=bench.prep[name][8])
        p += check_common(ref, 'R')
        want = 'L ready crc %08x words %d' % bench.prep[name][3:5]
        for tag, r in (('R', ref), ('S', srun)):
            if want not in r.lines:
                p.append('%s: loader result %s, want %s' % (tag, [x for x in r.lines if x.startswith('L ready')], want))
        if (name, 'S0') in futs:
            b0, f0 = futs[(name, 'S0')]
            r0 = f0.result()
            if r0 is None:
                p.append('S0: no log')
            else:
                p += check_save_run(img, ref, r0, b0, *bench.prep[name][3:7], cfgcrc=bench.prep[name][8],
                                    pause=False, what='S0')[0]
        probs += ['%s %s' % (name, x) for x in p]
        saves[name] = info
        print('%s: R %d frames, S %d saves%s %s' % (name, img[4], len(info),
                                                    ', S0' if (name, 'S0') in futs else '',
                                                    'pass' if not p else 'FAIL'), flush=True)
    # loads: (img, tag, saved cycle or None, end cycle, the blob it must apply or None, future)
    lf = []
    for img in imgs:
        name, nframes = img[0], img[4]
        if name not in refs or not saves.get(name):
            continue

        def sub(tag, end, sc, extra=()):
            return bench.pool.submit(bench.sim, '%s%s_%s' % (tagp, name, tag), img, end, sc, extra)
        for i, (p, zc, kind) in enumerate(saves[name]):
            end = min(nframes, zc // FRAME + FRAMES_AFTER) * FRAME
            if i == len(saves[name]) - 1:      # wake: the load inside a menu pause
                sc = ['menu %d 1' % LOAD_AT, 'load 0 %s ok %d' % (p, zc), 'wait 8', 'menu 0 0']
            else:
                sc = ['load %d %s ok %d' % (LOAD_AT, p, zc)]
            lf.append((img, 'L%d' % i, zc, end, p, sub('L%d' % i, end, sc)))
        p0, zc0, _ = saves[name][0]
        end0 = min(nframes, zc0 // FRAME + FRAMES_AFTER) * FRAME
        # D: s0 into a core that has run past its save point
        deep = min(nframes - 2, zc0 // FRAME + DEEP_AFTER)
        lf.append((img, 'D', zc0, end0, p0, sub('D', end0, ['load %d %s ok %d' % (deep * FRAME, p0, zc0)])))
        # wake with the host's reset held: the load asked for in reset, reset
        # released after its answer (W1) or while ss_ctl checks it (W2)
        lf.append((img, 'W1', zc0, end0, p0, sub('W1', end0, ['load -1 %s ok %d' % (p0, zc0), 'reset 0 0'],
                                                ['+hold=1'])))
        lf.append((img, 'W2', zc0, end0, p0, sub('W2', end0, ['loadr -1 %s ok %d' % (p0, zc0)], ['+hold=1'])))
        # foreign: another image's blob into this one
        ob = other_blob(name, saves)
        if ob:
            end = 20 * FRAME
            lf.append((img, 'F', None, end, None, sub('F', end, ['load %d %s err -1' % (LOAD_AT, ob)])))
        # corrupt ones, then the good one
        bads = corrupt_blobs(bench.work, tagp + name, p0)
        sc = ['load %d %s err -1' % (LOAD_AT, b) for b in bads] + ['load 0 %s ok %d' % (p0, zc0)]
        end = min(nframes, zc0 // FRAME + 12) * FRAME
        lf.append((img, 'C', zc0, end, p0, sub('C', end, sc)))
        # B: two blob reads while a save reads the state: the second overwrites
        # the first (one drop counted), the save and the run untouched; then
        # the race: a write arriving while a read is served
        if name in BURST_IMAGES:
            pb = bench.blob_path(name, 0, 'b')
            fb = saves[name][0][1] // FRAME
            lf.append((img, 'B', None, nframes * FRAME, pb,
                       sub('B', nframes * FRAME, ['saveb %d %s' % (fb * FRAME, pb), 'race 0'])))
    for img, tag, zc, end, blob, fut in lf:
        name = img[0]
        run = fut.result()
        q = []
        if run is None:
            q = ['no log']
        else:
            q += check_common(run, tag, drops=1 if tag == 'B' else 0)
            loads = run.tagged('LOAD')
            applied = run.tagged('MA')
            ref = refs[name]
            if tag[0] in 'LDW' and loads != ['LOAD ok EXPECT ok']:
                q.append('loads %s' % loads)
            if tag == 'W1':                    # answered while the reset was still on
                rl = [i for i, x in enumerate(run.lines) if x.startswith('R reset 0')]
                ol = [i for i, x in enumerate(run.lines) if x.startswith('LOAD ok')]
                if not rl or not ol or rl[0] < ol[0]:
                    q.append('reset not held through the load (%s %s)' % (rl, ol))
            if tag == 'W2' and 'R reset released, staged 1' not in run.lines:
                q.append('reset not released while the load was checked')
            if tag == 'B':
                sv = run.tagged('SAVE')
                if len(sv) != 1 or sv[0].split()[1] != 'ok' or not any(
                        x.startswith('R burst') and x.endswith('ss_en 1') for x in run.lines):
                    q.append('burst save %s' % sv)
                elif ss.verify(open(blob, 'rb').read(), *bench.prep[name][3:5],
                               exec_crc=bench.prep[name][5], grom_crc=bench.prep[name][6],
                               cfg_crc=bench.prep[name][8]):
                    q.append('burst save: blob does not verify')
                rw = run.tagged('RW')
                if len(rw) != 1 or int(rw[0].split()[1]) < 1 or int(rw[0].split()[2]) != 0:
                    q.append('race: %s (want at least one write taken in during a read, none wrong)' % rw)
                q += compare_frames(ref, run.frames, 0, end // FRAME, tag)
            elif zc is None:                   # F: untouched all the way
                if run.set_cycle is not None or applied:
                    q.append('state set by a refused load')
                q += compare_frames(ref, run.frames, 0, end // FRAME, tag)
            else:
                if run.set_cycle != zc:
                    q.append('set cycle %s, want %d' % (run.set_cycle, zc))
                want_m = '%08x %d' % blob_cram(blob)
                if len(applied) != 1 or ' '.join(applied[0].split()[2:4]) != want_m:
                    q.append('cart RAM after the load %s, blob %s' % (applied, want_m))
                # before the load: the fresh core's own frames are R's too
                pre = sorted(k for t, k in run.frames if t == 'H' and k < img[4])
                q += compare_frames(ref, run.frames, 0, (pre[-1] + 1) if pre else 0, tag + ' before')
                q += compare_frames(ref, run.after, zc // FRAME + 1, end // FRAME, tag + ' after',
                                    steps_only=True)
            if tag == 'C':
                if [x.split()[1] for x in loads] != ['err'] * 6 + ['ok']:
                    q.append('loads %s' % loads)
            if tag == 'F' and loads != ['LOAD err EXPECT err']:
                q.append('loads %s' % loads)
        print('%s %s: %s' % (name, tag, 'pass' if not q else 'FAIL ' + '; '.join(q[:3])), flush=True)
        probs += ['%s %s: %s' % (name, tag, x) for x in q]
    return probs, saves


# ------------------------------------------------------------------ plants
# (name, file, [(from, to)], image, the image whose state is the foreign one,
#  the reason: a regular expression one of the run's problems must match, so a
#  plant counts as caught only for its own fault, not for any failure)
AFTER = r' (L\d|D|W\d|C) after: frame \d+ differs'
CHK = "else if (m_q != hdr_exp(4'(w), 32'd0, cart_crc, cart_words, exec_crc, grom_crc))"
PLANTS = [
    ('ss_drop_stic', 'intv_ss_ctl.sv',
     [("                              v <= ss_rdata;\n",
       "                              v <= ss_addr[15:8] == 8'h04 ? 32'd0 : ss_rdata;\n")], 'sticmob', 'psgtest',
     AFTER),
    ('ss_word_off_by_one', 'intv_ss_ctl.sv',
     [("                              ss_addr  <= intv_ss_pkg::ss_word_addr(mi);\n",
       "                              ss_addr  <= intv_ss_pkg::ss_word_addr(mi + 11'd1);\n")], 'sticmob', 'psgtest',
     AFTER),
    ('ss_crc_unchecked', 'intv_ss_ctl.sv',
     [("if (bad || resv_bad || ~crc != hdr_crc)", "if (bad || resv_bad)")], 'sticmob', 'psgtest',
     r' C: FAIL load \S+_bad_\w+\.blob: code \d+, expected err'),
    ('ss_resume_wrong_pos', 'intv_ss_ctl.sv',
     [("                              ss_wdata <= v;\n",
       "                              ss_wdata <= mi == 11'd0 ? v + 32'd64 : v;\n")], 'sticmob', 'psgtest',
     AFTER),
    ('ss_cart_unchecked', 'intv_ss_ctl.sv',
     [(CHK, "else if (w != 14'(SS_H_CART_CRC) && w != 14'(SS_H_CART_WORDS)\n"
            "                             && m_q != hdr_exp(4'(w), 32'd0, cart_crc, cart_words, exec_crc, grom_crc))")],
     'nocart', 'astrosmash', r' F: FAIL load \S+plant_foreign_astrosmash\.blob: code \d+, expected err'),
    ('ss_rom_unchecked', 'intv_ss_ctl.sv',
     [(CHK, "else if (w != 14'(SS_H_EXEC_CRC) && w != 14'(SS_H_GROM_CRC)\n"
            "                             && m_q != hdr_exp(4'(w), 32'd0, cart_crc, cart_words, exec_crc, grom_crc))")],
     'sticmob', 'psgtest', r' F: FAIL load \S+plant_foreign_psgtest\.blob: code \d+, expected err'),
    # the cart RAM: its restore skipped; its cells taken one blob word off (save and load)
    ('ss_cram_not_restored', 'intv_ss_ctl.sv',
     [("                              ph <= 2'd1;                 // cart RAM: m_go now\n",
       "                              ph <= 2'd2;                 // cart RAM: m_go now\n")], 'chess', 'psgtest',
     r' (L\d|D|W\d|C): cart RAM after the load '),
    ('ss_cram_offset', 'intv_ss_ctl.sv',
     [("cram_a  = CRAM + {2'd0, w - 14'(W_CRAM), 1'b0};",
       "cram_a  = CRAM + 17'd2 + {2'd0, w - 14'(W_CRAM), 1'b0};")], 'chess', 'psgtest',
     r'(S: blob \S+: cart RAM |: cart RAM after the load )'),
    # the menu ignored: the machine runs on while the menu is open
    ('ss_menu_ignored', 'intv_ss_ctl.sv',
     [("    wire logic menu_hold = mn_s[2] && pz_s[2];\n",
       "    wire logic menu_hold = 1'b0 && mn_s[2] && pz_s[2];\n")], 'psgtest', 'astrosmash',
     r'S: menu \d+ \(open at cycle \d+\): (\d+ freezes|frozen at|froze at|a wait ended|frozen \d+ raster)'),
    # a bridge access's direction not latched: a write arriving while a read
    # is served takes the read's answer away (the B run's race)
    ('ss_brw_dir', 'intv_ss_ctl.sv',
     [("                if (!cur_we) begin r_q <= m_q; r_t <= !r_t; end\n",
       "                if (!bp_we) begin r_q <= m_q; r_t <= !r_t; end\n")], 'psgtest', 'astrosmash',
     r' B: FAIL race \d+: the read answered '),
    # a state word that boots to 0 ignored on restore (the PSG's envelope
    # counter): only the loads whose saved value is not 0 can show it
    ('ss_psg_ecnt_ignored', 'intv_psg.sv',
     [("                5'd19: ecnt <= ss_wdata[16:0];\n", "                5'd19: ;\n")], 'psgtest', 'astrosmash',
     AFTER),
    # build step 8: the CFG's CRC not checked (C: a blob of another CFG taken); the bank
    # registers not restored (a load runs on with the fresh core's); an image without save
    # states saved all the same
    ('ss_cfg_unchecked', 'intv_ss_ctl.sv',
     [(CHK, "else if (w != 14'(SS_H_CFG_CRC)\n"
            "                             && m_q != hdr_exp(4'(w), 32'd0, cart_crc, cart_words, exec_crc, grom_crc))")],
     'cartcfg', 'psgtest', r' C: (FAIL load \S+_bad_cfgcrc\.blob|loads )'),
    ('ss_bank_not_restored', 'intv_cart.sv',
     [("                bank[{ss_addr[2:0] - 3'd7, 2'(i)}] <= ss_wdata[8*i +: 8];",
       "                bank[{ss_addr[2:0] - 3'd7, 2'(i)}] <= bank[{ss_addr[2:0] - 3'd7, 2'(i)}];")],
     'cartbank', 'psgtest', AFTER),
    ('ss_noss_ignored', 'intv_ss_ctl.sv',
     [("                if (cart_noss && cart_ready)", "                if (1'b0 && cart_noss && cart_ready)")],
     'cartnoss', 'psgtest', r'NOSS: '),
]
PLANT_FOREIGN = {'psgtest': 6, 'astrosmash': 20}     # the foreign states: a save at this frame


def run_noss(bench, img, foreign):
    """An image without save states: R, then the S script (every save must answer err and
    leave the run as R), then a foreign blob's load (err, untouched)."""
    name, nframes = img[0], img[4]
    lines, blobs = save_script(img, bench)
    ref = bench.sim(name + '_R', img, nframes * FRAME, [])
    srun = bench.sim(name + '_S', img, nframes * FRAME, lines)
    probs = []
    if ref is None or srun is None or not ref.end:
        return ['NOSS: R or S did not run']
    sv = srun.tagged('SAVE')
    if len(sv) != len(blobs) or any(x.split()[1] != 'err' for x in sv):
        probs.append('NOSS: saves %s, want err each' % sv)
    probs += ['NOSS: ' + x for x in compare_frames(ref, srun.frames, 0, nframes, 'S')]
    if foreign:
        f = bench.sim(name + '_F', img, nframes * FRAME, ['load %d %s err -1' % (LOAD_AT, foreign)])
        if f is None or f.tagged('LOAD') != ['LOAD err EXPECT err']:
            probs.append('NOSS: foreign load %s' % (f.tagged('LOAD') if f else 'no log'))
        elif f.set_cycle is not None or f.tagged('MA'):
            probs.append('NOSS: state set by a refused load')
        else:
            probs += ['NOSS: ' + x for x in compare_frames(ref, f.frames, 0, nframes, 'F')]
    print('%s: R %d frames, %d saves refused%s %s' % (name, nframes, len(blobs),
                                                    ', a foreign load refused' if foreign else '',
                                                    'pass' if not probs else 'FAIL'), flush=True)
    return ['%s %s' % (name, x) for x in probs]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--only', help='comma-separated image names')
    ap.add_argument('--no-build', action='store_true')
    ap.add_argument('--plants', action='store_true', help='also the planted faults')
    ap.add_argument('--plants-only', action='store_true')
    ap.add_argument('--plant', help='comma-separated plant names')
    ap.add_argument('--jobs', type=int, default=2)
    a = ap.parse_args()
    verilator = os.environ.get('VERILATOR', 'verilator')
    work = os.environ.get('WORK', os.path.join(ROOT, 'sim', 'work', 'tb_savestate'))
    lib = os.environ.get('INTV_LIBRARY', os.path.expanduser('~/ROMLibrary/Intellivision'))
    bdir = os.environ.get('INTV_BIOS_DIR', os.path.expanduser('~/pocket_projects/intellivision/bios'))
    simslot = os.environ.get('SIMSLOT')
    os.makedirs(work, exist_ok=True)
    imgs = SS_IMAGES
    if a.only:
        imgs = [i for i in imgs if i[0] in a.only.split(',')]
    fails = []
    t0 = time.time()
    binary = os.path.join(work, 'obj', 'tb_savestate')
    if not a.no_build:
        binary = build(work, CORE, verilator)
        if not binary:
            print('TB_SAVESTATE_ALL FAIL (build)')
            return 1
        print('build: %.0fs' % (time.time() - t0), flush=True)
    bench = Bench(binary, work, bdir, lib, simslot, a.jobs)
    allimgs = {i[0]: i for i in SS_IMAGES + NOSS_IMAGES}
    noss = [i for i in NOSS_IMAGES if not a.only or i[0] in a.only.split(',')]
    try:
        for img in SS_IMAGES + NOSS_IMAGES:
            if img in imgs or img in noss or (a.plants or a.plants_only):
                bench.prep[img[0]] = prepare(work, img, lib, bdir)
        order = [i[0] for i in imgs]

        def other_blob(name, saves):
            # the next image's first blob (its S run is in this set)
            cands = [n for n in order[order.index(name) + 1:] + order[:order.index(name)]
                     if saves.get(n) and isinstance(saves[n][0], tuple) and len(saves[n][0]) == 3]
            return saves[cands[0]][0][0] if cands else None

        saves = {}
        if not a.plants_only:
            p, saves = run_image_set(bench, imgs, other_blob)
            fails += p
            for img in noss:
                fb = next((v[0][0] for v in saves.values() if v and isinstance(v[0], tuple)), None)
                fails += run_noss(bench, img, fb)
        if a.plants or a.plants_only or a.plant:
            # the foreign states for the plants, saved by the unplanted RTL
            fbs = {}
            for fname, fr in PLANT_FOREIGN.items():
                fbs[fname] = os.path.join(work, 'plant_foreign_%s.blob' % fname)
                r = bench.sim('plant_foreign_' + fname, allimgs[fname], (fr + 3) * FRAME,
                              ['save %d any %s' % (fr * FRAME, fbs[fname])])
                if r is None or not r.end or r.fails or not os.path.exists(fbs[fname]):
                    fails.append('plants: no foreign state of ' + fname)
            sel = a.plant.split(',') if a.plant else None
            for pname, f, edits, iname, fname, why in PLANTS:
                if sel and pname not in sel:
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
                pb = Bench(b, d, bdir, lib, simslot, a.jobs)
                pb.prep = bench.prep
                img = allimgs[iname]
                if img in NOSS_IMAGES:
                    pr = run_noss(pb, img, fbs[fname])
                else:
                    pr, _ = run_image_set(pb, [img], lambda n, s_, fb=fbs[fname]: fb, tagp='')
                own = [x for x in pr if re.search(why, x)]
                if own:
                    print('PLANT %s: caught: %s' % (pname, own[0][:150]), flush=True)
                elif pr:
                    print('PLANT %s: not caught for its own reason (/%s/); first problem: %s'
                          % (pname, why, pr[0][:150]), flush=True)
                    fails.append('plant ' + pname)
                else:
                    print('PLANT %s: not caught' % pname, flush=True)
                    fails.append('plant ' + pname)
    finally:
        bench.pool.shutdown(wait=True)
        for name, pr in bench.prep.items():
            cart = pr[1]
            if cart and os.path.exists(cart):
                os.remove(cart)
    print('time: %.0fs' % (time.time() - t0))
    print('TB_SAVESTATE_ALL %s' % ('pass' if not fails else 'FAIL (%s)' % ', '.join(fails[:6])))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
