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
system ROMs not checked.

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
       'intv_loader.sv', 'intv_media.sv', 'intv_ss_ctl.sv', 'intv_core.sv', 'core_bridge_cmd.v']
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
     [(200, 'busrq'), (260, 'rowfetch'), (290, 'sound'), (300, 'midinst')], (310, 20), 330),
    ('sticmob', None, 'sticmob.asm', (0xFF, 0xFF), 46, None,
     [(10, 'rowfetch'), (20, 'busrq'), (30, 'midinst'), (34, 'any')], (36, 10), 40),
    ('psgtest', None, 'psgtest.asm', (0x5A, 0xC3), 22, None,
     [(6, 'sound'), (11, 'sound'), (14, 'midinst'), (16, 'any')], (17, 10), 19),
]
FRAMES_AFTER = 24          # an L run goes on this many frames after the restore
LOAD_AT = FRAME            # fresh cores load from machine cycle 1 frame on


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


def prepare(work, img, lib, bdir):
    """(exec path, cart path or None, keys file or None, cart CRC, cart words, EXEC CRC,
    GROM CRC)."""
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
    cart, crc, words = None, 0, 0
    if zipname:
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
            ss.crc32(open(os.path.join(bdir, 'grom.bin'), 'rb').read()))


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

    def blob_path(self, name, i):
        return os.path.join(self.work, '%s_s%d.blob' % (name, i))


def save_script(img, bench):
    name, _, _, _, nframes, _, saves, menu, menu_save = img
    lines, blobs = [], []
    events = [(f, 'save', kind) for f, kind in saves] + [(menu[0], 'menu', menu[1]),
                                                         (menu_save, 'msave', None)]
    for f, what, x in sorted(events):
        if what == 'save':
            p = bench.blob_path(name, len(blobs))
            lines.append('save %d %s %s' % (f * FRAME, x, p))
            blobs.append((p, x))
        elif what == 'menu':
            lines += ['menu %d 1' % (f * FRAME), 'wait %d' % x, 'menu 0 0']
        else:                                  # sleep: menu open, save, menu closed later
            p = bench.blob_path(name, len(blobs))
            lines += ['menu %d 1' % (f * FRAME), 'save 0 any %s' % p, 'wait 5', 'menu 0 0']
            blobs.append((p, 'menu'))
    return lines, blobs


def check_save_run(img, ref, run, blobs, crc, words, ecrc, gcrc):
    probs = list(run.fails)
    if not run.end:
        probs.append('S: no END')
    nframes = img[4]
    probs += compare_frames(ref, run.frames, 0, nframes, 'S')
    saves = run.tagged('SAVE')
    if len(saves) != len(blobs) or any(s.split()[1] != 'ok' for s in saves):
        probs.append('S: saves %s' % saves)
        return probs, []
    # the Q (request seen) and Z (frozen) lines, one each per save; the menu
    # pause freezes too (a Z without a Q)
    # each save's request (Q) and the freeze it was taken in: the last Z
    # before its SAVE line (a menu pause may have frozen the machine first)
    qs, zs, last_z = [], [], None
    for ln in run.lines:
        t = ln.split()
        if t[0] == 'Z':
            last_z = ln
        elif t[0] == 'Q' and t[1] == 'save':
            qs.append(ln)
        elif t[0] == 'SAVE':
            zs.append(last_z)
    info = []
    for (p, kind), s, q, z in zip(blobs, saves, qs, zs):
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
        bad = ss.verify(blob, crc, words, exec_crc=ecrc, grom_crc=gcrc)
        if bad:
            probs.append('S: blob %s: %s' % (os.path.basename(p), bad[:3]))
            continue
        h, mods, cram = ss.unpack(blob)
        if ss.pack(mods, cram, h[ss.H_CART_CRC], h[ss.H_CART_WORDS], exec_crc=h[ss.H_EXEC_CRC],
                   grom_crc=h[ss.H_GROM_CRC]) != blob:
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
    struct.pack_into('>I', x, 4 * ss.H_VERSION, 2)
    put('version', bytes(x))
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
    for img in imgs:
        name = img[0]
        ref, srun = futs[(name, 'R')].result(), futs[(name, 'S')].result()
        if ref is None or srun is None or not ref.end or ref.fails:
            probs.append('%s: R or S did not run (%s)' % (name, ref.fails[:2] if ref else 'no log'))
            continue
        refs[name] = ref
        p, info = check_save_run(img, ref, srun, saves[name], *bench.prep[name][3:])
        probs += ['%s %s' % (name, x) for x in p]
        saves[name] = info
        print('%s: R %d frames, S %d saves %s' % (name, img[4], len(info), 'pass' if not p else 'FAIL'),
              flush=True)
    # loads
    lf = []
    for img in imgs:
        name, nframes = img[0], img[4]
        if name not in refs or not saves.get(name):
            continue
        for i, (p, zc, kind) in enumerate(saves[name]):
            end = min(nframes, zc // FRAME + FRAMES_AFTER) * FRAME
            if i == len(saves[name]) - 1:      # wake: the load inside a menu pause
                sc = ['menu %d 1' % LOAD_AT, 'load 0 %s ok %d' % (p, zc), 'wait 8', 'menu 0 0']
            else:
                sc = ['load %d %s ok %d' % (LOAD_AT, p, zc)]
            lf.append((img, 'L%d' % i, zc, end,
                       bench.pool.submit(bench.sim, '%s%s_L%d' % (tagp, name, i), img, end, sc)))
        # foreign: another image's blob into this one
        ob = other_blob(name, saves)
        if ob:
            end = 20 * FRAME
            lf.append((img, 'F', None, end, bench.pool.submit(
                bench.sim, '%s%s_F' % (tagp, name), img, end, ['load %d %s err -1' % (LOAD_AT, ob)])))
        # corrupt ones, then the good one
        p, zc, _ = saves[name][0]
        bads = corrupt_blobs(bench.work, tagp + name, p)
        sc = ['load %d %s err -1' % (LOAD_AT, b) for b in bads] + ['load 0 %s ok %d' % (p, zc)]
        end = min(nframes, zc // FRAME + 12) * FRAME
        lf.append((img, 'C', zc, end, bench.pool.submit(bench.sim, '%s%s_C' % (tagp, name), img, end, sc)))
    for img, tag, zc, end, fut in lf:
        name = img[0]
        run = fut.result()
        q = []
        if run is None:
            q = ['no log']
        else:
            q += run.fails
            if not run.end:
                q.append('no END')
            loads = run.tagged('LOAD')
            if tag.startswith('L') and loads != ['LOAD ok EXPECT ok']:
                q.append('loads %s' % loads)
            ref = refs[name]
            if zc is None:                     # F: untouched all the way
                if run.set_cycle is not None:
                    q.append('state set by a refused load')
                q += compare_frames(ref, run.frames, 0, end // FRAME, tag)
            else:
                if run.set_cycle != zc:
                    q.append('set cycle %s, want %d' % (run.set_cycle, zc))
                # before the load: the fresh core's own frames are R's too
                pre = sorted(k for t, k in run.frames if t == 'H' and k < img[4])
                q += compare_frames(ref, run.frames, 0, (pre[-1] + 1) if pre else 0, tag + ' before')
                q += compare_frames(ref, run.after, zc // FRAME + 1, end // FRAME, tag + ' after',
                                    steps_only=True)
            if tag == 'C':
                if [x.split()[1] for x in loads] != ['err'] * 5 + ['ok']:
                    q.append('loads %s' % loads)
            if tag == 'F' and loads != ['LOAD err EXPECT err']:
                q.append('loads %s' % loads)
        print('%s %s: %s' % (name, tag, 'pass' if not q else 'FAIL ' + '; '.join(q[:3])), flush=True)
        probs += ['%s %s: %s' % (name, tag, x) for x in q]
    return probs, saves


# ------------------------------------------------------------------ plants
# (name, file, [(from, to)], image, the image whose state is the foreign one)
CHK = "else if (m_q != hdr_exp(4'(w), 32'd0, cart_crc, cart_words, exec_crc, grom_crc))"
PLANTS = [
    ('ss_drop_stic', 'intv_ss_ctl.sv',
     [("                              v <= ss_rdata;\n",
       "                              v <= ss_addr[15:8] == 8'h04 ? 32'd0 : ss_rdata;\n")], 'sticmob', 'psgtest'),
    ('ss_word_off_by_one', 'intv_ss_ctl.sv',
     [("                              ss_addr  <= intv_ss_pkg::ss_word_addr(mi);\n",
       "                              ss_addr  <= intv_ss_pkg::ss_word_addr(mi + 11'd1);\n")], 'sticmob', 'psgtest'),
    ('ss_crc_unchecked', 'intv_ss_ctl.sv',
     [("if (bad || resv_bad || ~crc != hdr_crc)", "if (bad || resv_bad)")], 'sticmob', 'psgtest'),
    ('ss_resume_wrong_pos', 'intv_ss_ctl.sv',
     [("                              ss_wdata <= v;\n",
       "                              ss_wdata <= mi == 11'd0 ? v + 32'd64 : v;\n")], 'sticmob', 'psgtest'),
    ('ss_cart_unchecked', 'intv_ss_ctl.sv',
     [(CHK, "else if (w != 14'(SS_H_CART_CRC) && w != 14'(SS_H_CART_WORDS)\n"
            "                             && m_q != hdr_exp(4'(w), 32'd0, cart_crc, cart_words, exec_crc, grom_crc))")],
     'nocart', 'astrosmash'),
    ('ss_rom_unchecked', 'intv_ss_ctl.sv',
     [(CHK, "else if (w != 14'(SS_H_EXEC_CRC) && w != 14'(SS_H_GROM_CRC)\n"
            "                             && m_q != hdr_exp(4'(w), 32'd0, cart_crc, cart_words, exec_crc, grom_crc))")],
     'sticmob', 'psgtest'),
]
PLANT_FOREIGN = {'psgtest': 6, 'astrosmash': 20}     # the foreign states: a save at this frame


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
    allimgs = {i[0]: i for i in SS_IMAGES}
    try:
        for img in SS_IMAGES:
            if img in imgs or (a.plants or a.plants_only):
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
            for pname, f, edits, iname, fname in PLANTS:
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
                pr, _ = run_image_set(pb, [img], lambda n, s_, fb=fbs[fname]: fb, tagp='')
                if pr:
                    print('PLANT %s: caught: %s' % (pname, pr[0][:150]), flush=True)
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
