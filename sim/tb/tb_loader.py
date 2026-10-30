#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Step 2 bench driver (DESIGN.md 9): the loader RTL against the mapper model.

For each image of sim/regress/step2_set.csv (the owner's library by name,
two synthetic odd-length images built with tools/as1610.py, and forced:
images whose CRC tools/synth_image.py sets to a table CRC), it computes
every line sim/tb/tb_loader.sv prints from the Python model
(tools/intv_mapper.py Tables + tools/mapper/intvcart.py CartModel, replaying
the bench's exact sequence of bus writes, machine resets and state writes),
runs the Verilator bench through the APF bridge, and compares line by line.
Library images must also give the CRC, layout, flags and mapped-space CRC
recorded in sim/regress/mapper_library.csv.

  python3 -I sim/tb/tb_loader.py --all        build, the 33 images, the
                                              refused loads, the length and
                                              reload cases, then the planted
                                              faults
                                              (each must fail)
  python3 -I sim/tb/tb_loader.py [--only CRC,...] [--no-build]
  python3 -I sim/tb/tb_loader.py --plants-only --plant NAME,... [--only ...]

Environment: VERILATOR (default verilator), WORK (default sim/work/tb_loader),
INTV_LIBRARY (default ~/ROMLibrary/Intellivision), INTV_BIOS_DIR (default
~/pocket_projects/intellivision/bios: exec.bin, grom.bin, ECS.bin,
IVOICE.BIN). Images are extracted into WORK and deleted after the run; on
the owner's VM run this in a simulation slot (~/daria_work/bin/simslot).
The last line is "TB_LOADER_ALL pass" or "TB_LOADER_ALL FAIL (...)".
"""
import argparse
import csv
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'mapper'))
import as1610             # noqa: E402
import synth_image        # noqa: E402
import intv_mapper        # noqa: E402
import intvcart as m      # noqa: E402
import cartfmt as cf      # noqa: E402

CORE = os.path.join(ROOT, 'src', 'fpga', 'core')
RTL = ['intv_sram.sv', 'intv_cart.sv', 'intv_sysrom.sv', 'intv_loader.sv', 'intv_cfgparse.sv', 'intv_romparse.sv', 'intv_pagesel.sv', 'intv_media.sv',
       'apf_datatable.sv', 'apf_cfgfetch.sv']
OTHER = [os.path.join(CORE, 'core_bridge_cmd.v'),
         os.path.join(ROOT, 'src', 'fpga', 'apf', 'common.v'),
         os.path.join(ROOT, 'src', 'fpga', 'pocket_utils', 'data_loader.sv'),
         os.path.join(HERE, 'models', 'dcfifo.sv'),
         os.path.join(HERE, 'models', 'mf_datatable.sv'),
         os.path.join(HERE, 'models', 'sram_as6c2016.sv'),
         os.path.join(HERE, 'tb_loader.sv')]
SET = os.path.join(ROOT, 'sim', 'regress', 'step2_set.csv')
LIBCSV = os.path.join(ROOT, 'sim', 'regress', 'mapper_library.csv')
SYNTH_SRC = os.path.join(ROOT, 'sim', 'testroms', 'loader_odd.asm')

YS = (1, 2, 3, 15)
NSS = cf.SS_WORDS


def crc32(b, c=0):
    return zlib.crc32(b, c) & 0xFFFFFFFF


# ------------------------------------------------------------------------- images

def synthetic(nbytes):
    """loader_odd.asm plus a WORD table, cut to nbytes (odd)."""
    src = open(SYNTH_SRC, encoding='utf-8').read()
    code = len(as1610.assemble(src).image()) // 2
    total = -(-nbytes // 2)
    lines = []
    for i in range(total - code):
        v = (i * 0x3B5D + 0x1F2E) & 0xFFFF
        if (v >> 8) == (v & 0xFF):
            v ^= 0x0100
        lines.append('        WORD    $%04X\n' % v)
    prog = as1610.assemble(src + ''.join(lines))
    img = prog.image()
    assert len(img) == 2 * total, (len(img), total)
    return img[:nbytes]


def load_set(lib):
    out = []
    with open(SET, newline='') as f:
        for r in csv.DictReader(f):
            if r['image'].startswith('synthetic:'):
                data = synthetic(int(r['bytes']))
                src = r['image']
                if '%08X' % crc32(data) != r['crc32']:
                    sys.exit('%s: CRC %08X, set file says %s' % (src, crc32(data), r['crc32']))
            elif r['image'].startswith('forced:'):
                data = synth_image.forced(int(r['image'][7:], 16), int(r['bytes']))
                src = r['image']
                if '%08X' % crc32(data) != r['crc32']:
                    sys.exit('%s: CRC %08X, set file says %s' % (src, crc32(data), r['crc32']))
            else:
                src = os.path.join(lib, r['image'])
                data = m.load_image_bytes(src)
                if '%08X' % crc32(data) != r['crc32']:
                    sys.exit('%s: CRC %08X, set file says %s' % (src, crc32(data), r['crc32']))
            if len(data) != int(r['bytes']):
                sys.exit('%s: %d bytes, set file says %s' % (src, len(data), r['bytes']))
            out.append(dict(r, data=data, name=r['image'], crc='%08X' % crc32(data)))
    return out


# ------------------------------------------------------------------- expectations

def bench_sram(ld):
    """The bench's SRAM model starts with $DEAD ^ address in every word (sram_as6c2016.sv)."""
    sram = {a: 0xDEAD ^ (a & 0xFFFF) for a in range(cf.SRAM_WORDS)}
    sram.update(ld.sram)
    return sram


def blockcrc(cart, r):
    buf = bytearray()
    for a in range(r << 12, (r + 1) << 12):
        hit, attr, paged = cart.attr(a)
        v = cart.read(a)
        v = 0xFFFF if v is None else v
        buf += bytes((int(hit) | attr << 1 | paged << 5, v >> 8, v & 0xFF))
    return crc32(bytes(buf))


def fetch_expect(img):
    """(res, the CFG the loader gets) of apf_cfgfetch for a bench image: the CFG is found by the
    cartridge's name (build step 9b). res: 0 no cartridge (no fetch), 1 found with the table's
    size, 2 found with no size in the table (img['nodt']: the length found by reading), 3 none
    beside the cartridge (none, or another name: img['miss']), 4 the host refused the read (the
    table's size past the file: img['cfglenadj']), 5 a cartridge path without an extension
    (img['nodot']), 7 a command the host never answers (img['nohost'], a command number: 0.0.14's
    watchdog). Since 0.0.15 Ready to run (0x0140) goes out after the fetch, so a host that acks it
    late (img['rtrdelay']) or never (img['rtrhold']) no longer holds the fetch up."""
    cfg = img.get('cfg')
    if img.get('neg') == 'nocart':
        return 0, None
    if img.get('nohost') is not None:
        return 7, None
    if img.get('nodot'):
        return 5, None
    if cfg is None or img.get('miss') or len(cfg) == 0:
        return 3, None
    if img.get('cfglenadj'):
        return 4, None
    return (2 if img.get('nodt') else 1), cfg


def fetch_to(img):
    """apf_cfgfetch's to_cmd: the command that timed out (1 get filename, 2 open, 4 read)."""
    return {0x190: 1, 0x192: 2, 0x180: 4}.get(img.get('nohost'), 0)


def load_model(img, tab):
    """cartfmt.Loaded for a bench image, with the CFG the fetch gives the loader."""
    cfg = fetch_expect(img)[1]
    return cf.load(img['data'], cfg, tab, tab.pages, cfg_len=len(cfg) if cfg is not None else None)


def ecs_auto(ld):
    """Build step 9: the Auto rule's mode for a loaded image (tools/ecs.py auto_mode, from
    what intv_cart and the reset probe see: the ECS flag, the ROM word at $4800, the map of
    $4000-$47FF; no cartridge (0 words): on)."""
    import ecs as ecsm
    return ecsm.auto_mode(*ecsm.cart_inputs(cf.MapCart(ld)))


def expect(img, tab, bios):
    """Every line the bench prints for this image, and the model's summary.

    A refused load (img['neg']: no cartridge, or a data table length the
    strobes do not cover; or a format the loader refuses) maps nothing:
    layout 0. The length check (apf_datatable len_chk, err[4]): the host's
    0x0082 size is the file's size plus img['reqadj']; the data table's is
    plus img['lenadj'], or missing with img['notable'] (then the 0x0082 size
    is used); no cartridge sends no 0x0082 and a table size of 0.
    """
    data = img['data']
    if img.get('neg') == 'nocart':
        lenst = 0
    elif img.get('notable'):
        lenst = 3
    else:
        lenst = 1 if img.get('lenadj', 0) == img.get('reqadj', 0) else 2
    e4 = 16 if lenst == 2 else 0
    if img.get('neg'):
        ld = cf.Loaded()
        for i in range(cf.RAM_BLOCKS * 256):
            ld.sram[cf.RAM_BASE + i] = 0
        err = 1 | e4
        cslot = 0 if img['neg'] == 'nocart' else 1
    else:
        ld = load_model(img, tab)
        if ld.err == -1:
            err = 4 | e4                        # over 64K words: err[2]
        else:
            err = e4 | (32 if ld.err else 0)
        cslot = 1 if err & 0x2F else 2          # err[4] alone: still ok (the second card shows it)
    words = list(struct.unpack('>%dH' % ld.words, (data + b'\0')[:2 * ld.words])) if ld.words else []
    crc = '%08X' % ld.crc
    L = []
    L.append('status crc %s words %d layout %d flags %02X hit %d err %d lenst %d' % (
        crc, ld.words, ld.layout, ld.flags, int(ld.hit), err, lenst))
    fres, fcfg = fetch_expect(img)
    L.append('fetch res %d len %d to %d' % (fres, len(fcfg) if fcfg is not None else 0, fetch_to(img)))
    # the load's diagnostics (0.0.14): all complete seen; the cartridge's 0x0082 (none without a
    # cartridge); no 0x008A; the length handed on; core_bridge_cmd's target state: waiting for
    # Ready to run's ok (14) or a held command's (15) when the line is printed (+late answers
    # them only after it: the late line shows 0)
    # (0.0.15) setup_done (status_setup_done, Ready to run) up after the fetch; early: it was up
    # before all complete (img['acdelay']: the host started loading after setup_done's safety)
    tst = 14 if img.get('rtrhold') else 15 if img.get('nohost') is not None else 0
    L.append('diag ac 1 req %d upd 0 phase 2 tstate %d sd 1 early %d' % (
        0 if img.get('neg') == 'nocart' else 1, tst, 1 if img.get('acdelay') else 0))
    cfgslot = (2 << 2) if fcfg is not None else 0
    iv = not img.get('noivoice')
    slots = cslot | cfgslot | 2 << 4 | 2 << 6 | (2 << 8 if bios.get('ecs') else 0) | (2 << 10 if iv else 0)
    if img.get('late'):
        # the held command answered after the map: a read's bytes never reach the loader
        L.append('late slots %03X tstate 0' % slots)
    L.append('slots %03X' % slots)
    L.append('ecs auto %d' % ecs_auto(ld))
    # build step 10: the Intellivoice's Auto rule (intv_media voice_auto): the flag, with ivoice.bin
    L.append('voice auto %d' % int(bool(ld.flags & m.FLAG_VOICE) and iv))
    L.append('format cfgcrc %08X noss %d ferr %02X' % (ld.cfg_crc, int(ld.noss), max(ld.err, 0)))
    sram = bench_sram(ld)
    if cf.is_rom(data) and ld.err:
        L.append('image *')                     # a refused .rom: pad bytes may reach plane 1
    else:
        L.append('image %08X' % crc32(struct.pack('>%dH' % ld.words, *[sram[i] for i in range(ld.words)])))
    if bios.get('ecs'):
        L.append('ecs %08X' % crc32(bios['ecs']))
    ex = bios['exec']
    L.append('exec %08X' % crc32(b''.join(struct.pack('>H', ((ex[i] << 8) | ex[i + 1]) & 0x3FF)
                                          for i in range(0, 8192, 2))))
    L.append('grom %08X' % crc32(bios['grom']))
    L.append(('ivoice %08X' % crc32(bios['ivoice'])) if iv else 'ivoice *')
    mi = cf.MapCart(ld)
    mi.sram = sram
    for i, w in enumerate(mi.ss_words()):
        L.append('ss0 %d %08X' % (i, w))
    # A and the mapped-space CRC (the bench reads every page of a paged range)
    mi.reset()
    for r in range(16):
        L.append('A %d %08X' % (r, blockcrc(mi, r)))
    mc = 0
    for a in range(0x10000):
        hit, attr, paged = mi.attr(a)
        v = mi.read(a)
        mc = crc32(struct.pack('>H', v if (hit and attr & 3 == 1) else 0xFFFF), mc)
    for r in range(16):
        if ld.paged >> r & 1:
            pages, n = {}, 1
            for y in range(1, 16):
                mi.write((r << 12) + 0xFFF, (r << 12) + 0xA50 + y)
                blk, anyw = [], False
                for a in range(r << 12, (r + 1) << 12):
                    hit, attr, paged = mi.attr(a)
                    v = mi.read(a)
                    blk.append(v if v is not None else 0xFFFF)
                    anyw |= bool(attr & 3)
                pages[y] = blk
                if anyw:
                    n = y + 1
            for y in range(1, n):
                mc = crc32(struct.pack('>4096H', *pages[y]), mc)
            mi.write((r << 12) + 0xFFF, (r << 12) + 0xA50)
    L.append('mapped %08X' % mc)
    model_mapped = cf.MapCart(ld).mapped_space_crc() if not ld.err else mc
    # B
    for r in range(16):
        for y in YS:
            mi.write((r << 12) + 0xFFF, (r << 12) + 0xA50 + y)
            L.append('B %d %d %08X' % (r, y, blockcrc(mi, r)))
        mi.write((r << 12) + 0xFFF, (r << 12) + 0xA50)
    # K: the bank sweep (all bank registers at v; every 2K window whose first word is a
    # bank window, attr B, read), then the registers back at their start
    for v in range(0, 256, 8):
        for i in range(32):
            mi.write(0x40 + i, v)
        buf = bytearray()
        for w in range(32):
            if mi.attr(w << 11)[1] & 8:
                for a in range(w << 11, (w + 1) << 11):
                    hit, attr, paged = mi.attr(a)
                    x = mi.read(a)
                    x = 0xFFFF if x is None else x
                    buf += bytes((int(hit) | attr << 1 | paged << 5, x >> 8, x & 0xFF))
        L.append('K %d %08X' % (v, crc32(bytes(buf))))
    for i in range(32):
        mi.write(0x40 + i, cf.BANK0[i])
    # C, D
    for a in range(0x10000):
        mi.write(a, (a * 0x9E37 + 0x1234) & 0xFFFF)
    for r in range(16):
        L.append('C %d %08X' % (r, blockcrc(mi, r)))
    for r in range(16):
        mi.write((r << 12) + 0xFFF, (r << 12) + 0xA50 + ((r + 5) & 15))
    mi.reset()
    for i, w in enumerate(mi.ss_words()):
        L.append('ssd %d %08X' % (i, w))
    for r in range(16):
        L.append('D %d %08X' % (r, blockcrc(mi, r)))
    # E, Z, F
    for r in range(16):
        mi.write((r << 12) + 0xFFF, (r << 12) + 0xA50 + (r & 3))
    ss1 = mi.ss_words()
    for i, w in enumerate(ss1):
        L.append('ss1 %d %08X' % (i, w))
    for r in range(16):
        L.append('E %d %08X' % (r, blockcrc(mi, r)))
    # W: writes that must not select a page (another range's value at $xFFF; $xFFE, $xF7F)
    for r in range(16):
        mi.write((r << 12) + 0xFFF, (((r + 1) & 15) << 12) + 0xA50 + ((r + 7) & 15))
        mi.write((r << 12) + 0xFFE, (r << 12) + 0xA50 + ((r + 9) & 15))
        mi.write((r << 12) + 0xF7F, (r << 12) + 0xA50 + ((r + 11) & 15))
    ssw = mi.ss_words()
    for i in (5, 6):
        L.append('ssw %d %08X' % (i, ssw[i]))
    mi.ss_load([0] * NSS)
    for i, w in enumerate(mi.ss_words()):
        L.append('ssz %d %08X' % (i, w))
    for r in range(16):
        L.append('Z %d %08X' % (r, blockcrc(mi, r)))
    mi.ss_load(ss1)
    for i, w in enumerate(mi.ss_words()):
        L.append('ss2 %d %08X' % (i, w))
    for r in range(16):
        L.append('F %d %08X' % (r, blockcrc(mi, r)))
    # the hazard: no finish runs again, the selects and bank registers stay
    L.append('hazard busy 0 ready 1')
    ssf = mi.ss_words()
    for i in range(5, 15):
        L.append('ssh %d %08X' % (i, ssf[i]))
    # the reload: another cartridge (img['reload']) in the same session,
    # its own 0x0082 size, in the table or not (img['notable2']); its CFG is
    # fetched by its own name: the first CFG's file under it, unless
    # img['cfgclear2'] (none beside it)
    if img.get('reload'):
        rimg = dict(img['reload'])
        rcfg = fcfg if not img.get('cfgclear2') else None
        rres = fres if rcfg is not None else 3
        if fres == 7:
            rcfg, rres = None, 7                # a timed-out command: no more fetches this session
        rl = cf.load(rimg['data'], rcfg, tab, tab.pages, cfg_len=len(rcfg) if rcfg is not None else None)
        rsram = dict(sram)
        # the session's SRAM: the first image's words stay where the second does not write
        for a, v in mi.sram.items():
            rsram[a] = v
        for a, v in rl.sram.items():
            rsram[a] = v
        L.append('reload status crc %08X words %d layout %d flags %02X hit %d err 0 lenst %d' % (
            rl.crc, rl.words, rl.layout, rl.flags, int(rl.hit), 3 if img.get('notable2') else 1))
        L.append('reload fetch res %d len %d to 0' % (rres, len(rcfg) if rcfg is not None else 0))
        L.append('reload slots %03X' % (2 | cfgslot | 2 << 4 | 2 << 6 | (2 << 8 if bios.get('ecs') else 0) | 2 << 10))
        L.append('reload ecs auto %d' % ecs_auto(rl))
        L.append('reload image %08X' % crc32(struct.pack('>%dH' % rl.words, *[rsram[i] for i in range(rl.words)])))
        rm = cf.MapCart(rl)
        rm.sram = rsram
        rm.sel = list(mi.sel)
        rm.reset()
        for i, w in enumerate(rm.ss_words()):
            L.append('rss %d %08X' % (i, w))
        for r in range(16):
            L.append('R %d %08X' % (r, blockcrc(rm, r)))
    L.append('end')
    return L, dict(crc=crc, layout=ld.layout, flags=ld.flags, hit=ld.hit, mapped='%08X' % mc,
                   model_mapped='%08X' % model_mapped, err=ld.err)


# ---------------------------------------------------------------------- the bench

def build(work, rtl_dir, verilator, strict=True):
    obj = os.path.join(work, 'obj')
    os.makedirs(work, exist_ok=True)
    tables = os.path.join(CORE, 'tables')
    # --verilate-jobs 1: Verilator 5.040's multithreaded verilation (what -j N turns on besides --build-jobs)
    # crashed about one build in 16 with "internal fault" (2026-10-28: 5 of 80 with -j 2, 0 of 210 with one)
    cmd = [verilator, '--binary', '--timing', '--verilate-jobs', '1', '--build-jobs', '4', '-Wall', '-Wno-fatal', '-Wno-TIMESCALEMOD', '-Wno-PROCASSINIT',
           '--top-module', 'tb_loader', '-Mdir', obj, '-o', 'tb_loader',
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
    # our own RTL must build without a single warning (third-party files may warn)
    ours = [ln for ln in text.splitlines() if ln.startswith('%Warning') and
            any(('/' + f + ':') in ln for f in RTL)]
    if ours and strict:
        print('\n'.join(ours[:20]))
        return None
    return os.path.join(obj, 'tb_loader')


def pocket_paths(img, data, tag=''):
    """The cartridge's path on the SD card as the host gives it (0x0190), and the path of the
    CFG beside it as the host has it (img['cfgname'] another name, img['cartname'] /
    img['cartdir'] the cartridge's own)."""
    d = img.get('cartdir', '/Assets/intv/common/')
    name = img.get('cartname' + tag, img['crc'] + tag + ('.rom' if cf.is_rom(data) else '.bin'))
    stem = name.rsplit('.', 1)[0] if '.' in name else name
    return d + name, d + img.get('cfgname', stem + '.cfg')


def run_one(binary, img, path, bios_paths, work, k, timeout=1500, path2=None, cpath=None):
    out = os.path.join(work, 'out_%s.txt' % img['crc'])
    args = [binary, '+out=' + out, '+seed=%d' % (k + 1)]
    if cpath:
        args.append('+cfg=' + cpath)
    cart_p, cfg_p = pocket_paths(img, img['data'])
    args += ['+cartpath=' + cart_p, '+cfgpath=' + cfg_p]
    if img.get('nodt'):
        args.append('+dtupdate=0')
    if img.get('nohost') is not None:
        args.append('+nohost=%x' % img['nohost'])
    if img.get('rtrhold'):
        args.append('+rtrhold=1')
    if img.get('rtrdelay'):
        args.append('+rtrdelay=%d' % img['rtrdelay'])
    if img.get('acdelay'):
        args.append('+acdelay=%d' % img['acdelay'])
    if img.get('late'):
        args.append('+late=1')
    if img.get('cfglenadj'):
        args.append('+dtcfgadj=%d' % img['cfglenadj'])      # the table's size past the file
    if path2:
        args.append('+cart2=' + path2)
        cart2_p, cfg2_p = pocket_paths(img, img['reload']['data'], '_2')
        args += ['+cart2path=' + cart2_p, '+cfg2path=' + cfg2_p]
        if not img.get('cfgclear2'):
            args.append('+cfg2same=1')
    if img.get('notable2'):
        args.append('+notable2=1')
    if img.get('neg') != 'nocart':
        args.append('+cart=' + path)
    if img.get('lenadj'):
        args.append('+lenadj=%d' % img['lenadj'])
    if img.get('reqadj'):
        args.append('+reqadj=%d' % img['reqadj'])
    if img.get('notable'):
        args.append('+notable=1')
    args += [
            '+pad=%02X' % (0xA5, 0x00, 0xFF, 0x5A)[k % 4], '+dtfirst=%d' % img.get('dtfirst', k % 2),
            '+gap=%d' % (40 + 7 * (k % 5)), '+jitter=%d' % (1 + 13 * (k % 3))]
    for key in ('exec', 'grom', 'ecs', 'ivoice'):
        if bios_paths.get(key) and not (key == 'ivoice' and img.get('noivoice')):
            args.append('+%s=%s' % (key, bios_paths[key]))
    t0 = time.time()
    r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    lines = open(out).read().splitlines() if os.path.exists(out) else []
    if os.path.exists(out):
        os.remove(out)       # derived from a game image
    return r.stdout, lines, time.time() - t0


def compare(got, want):
    bad = []
    for i in range(max(len(got), len(want))):
        g = got[i] if i < len(got) else '<missing>'
        w = want[i] if i < len(want) else '<missing>'
        if g != w and not (w.endswith(' *') and g.split(' ')[0] == w.split(' ')[0]):
            bad.append('line %d: got "%s", want "%s"' % (i + 1, g, w))
    return bad


def run_set(binary, imgs, exp, bios_paths, work, tmp, quiet=False):
    """Run each image; returns the list of failing image names."""
    failed = []
    for k, img in enumerate(imgs):
        path = os.path.join(tmp, '%s.bin' % img['crc'])
        with open(path, 'wb') as f:
            f.write(img['data'])
        path2 = cpath = None
        if img.get('cfg') is not None:
            cpath = os.path.join(tmp, '%s.cfg' % img['crc'])
            with open(cpath, 'wb') as f:
                f.write(img['cfg'])
        if img.get('reload'):
            path2 = os.path.join(tmp, '%s_2.bin' % img['crc'])
            with open(path2, 'wb') as f:
                f.write(img['reload']['data'])
        try:
            so, got, dt = run_one(binary, img, path, bios_paths, work, k, path2=path2, cpath=cpath)
        finally:
            os.remove(path)
            for q in (path2, cpath):
                if q:
                    os.remove(q)
        bad = compare([g.upper() for g in got], [w.upper() for w in exp[img['crc']][0]])
        okrun = 'TB_LOADER run ok' in so
        if not okrun:
            bad.insert(0, 'bench: ' + ' | '.join(ln for ln in so.splitlines() if 'FAIL' in ln)[:300])
        tag = 'ok  ' if not bad else 'FAIL'
        if not quiet or bad:
            print('  %s %-8s %-60s %5.1fs%s' % (tag, img['crc'], img['name'][:60], dt,
                                                 '' if not bad else '  (%d lines differ)' % len(bad)))
        if bad:
            failed.append(img['crc'])
            if not quiet:
                for b in bad[:6]:
                    print('         ' + b)
    return failed


# Planted faults: one change each to a copy of the RTL; the bench must fail on it.
PLANTS = [
    ('crc_padded', 'intv_loader.sv', "crc_fin <= ~crc_at[len[1:0] - 2'd1];", "crc_fin <= ~crc;",
     'CRC over the padded (strobe) length'),
    ('byte_order', 'intv_loader.sv', "s_d = {2'b11, off[17:1], hb, ld_data};",
     "s_d = {2'b11, off[17:1], ld_data, hb};", 'little-endian words'),
    ('pt_off_by_one', 'intv_loader.sv', "assign lay_ra = {lid[4:0], r, b[3]};",
     "assign lay_ra = {lid[4:0], r, b[3]} + 10'd1;", 'layout entry read one entry off'),
    ('odd_low_byte', 'intv_loader.sv', "F_FIX: if (len[0] && {1'b0, len[31:1]} < 32'h10000 && !rom_mode) begin",
     "F_FIX: if (1'b0) begin", 'odd length: pad byte left in the last word'),
    ('default_uncut', 'intv_loader.sv',
     "if (lay_q[15:14] == 2'd1 && !(lid == 8'd1 && {1'b0, lay_q[8:0]} >= {4'd0, units})) begin",
     "if (lay_q[15:14] == 2'd1) begin", 'default map not cut at the image length'),
    ('sram_early', 'intv_media.sv', "intv_sram #(.RD_CYC(3)", "intv_sram #(.RD_CYC(2)",
     'SRAM sampled one clock early'),
    ('sel_no_reset', 'intv_cart.sv', ".rst(mreset || ld_res_we)", ".rst(ld_res_we)",
     'machine reset keeps the page selects'),
    ('ss_no_sel', 'intv_cart.sv', ".ss_we0(ss_hit && ss_addr[7:0] == 8'd5)", ".ss_we0(1'b0)",
     'state restore drops the selects of ranges 0-7'),
    ('no_size_check', 'intv_loader.sv',
     "&& (crc_q[15:0] == 16'd0 || {1'b0, crc_q[15:0]} == size256)) begin", ") begin",
     'a table hit whatever the image size'),
    ('len_xcheck_off', 'apf_datatable.sv',
     "len_chk  <= !req_seen ? 2'd0 : dt_q == req_len ? 2'd1 : 2'd2;", "len_chk  <= req_seen ? 2'd1 : 2'd0;",
     'the 0x0082 size not compared with the table'),
    ('no_fallback', 'apf_datatable.sv', "cart_len <= req_seen ? req_len : 32'd0;", "cart_len <= 32'd0;",
     'no cartridge entry in the table: the 0x0082 size not used'),
    ('req_any_slot', 'apf_datatable.sv', "if (wr_req && wr_id == SLOT_ID[15:0]) begin",
     "if (wr_req) begin", 'the 0x0082 size of any slot taken'),
    ('rerun', 'intv_loader.sv', "F_IDLE: if (len_valid && !len_d && pending) begin",
     "F_IDLE: if (len_valid && !len_d) begin", 'the finish runs again on every all complete'),
    ('pending_byte0', 'intv_loader.sv', "                        pending  <= 1'b1;\n                        seq_err  <= 1'b0;",
     "                        seq_err  <= 1'b0;", 'a reload\'s byte 0 does not arm the finish'),
    ('req_len_first', 'apf_datatable.sv', "            req_len  <= wr_size;",
     "            if (!req_seen) req_len <= wr_size;", 'only the first 0x0082 size kept'),
    # build step 8
    ('page_off_by_one', 'intv_cart.sv', "wire logic [3:0]  y_bus = paged[r_bus] ? pg_sel[4*r_bus +: 4] : 4'd0;",
     "wire logic [3:0]  y_bus = paged[r_bus] ? pg_sel[4*r_bus +: 4] + 4'd1 : 4'd0;", 'page off by one'),
    ('ram_width_read', 'intv_cart.sv', "bus_rdata <= qe[18] ? {8'h00, m_rdata[7:0]} : m_rdata;",
     "bus_rdata <= m_rdata;", '8-bit RAM read as 16 bits'),
    ('cfg_ram8_as16', 'intv_cfgparse.sv', "if (c == 8'h38) begin attr <= attr | 3'd4; st <= P_END; end",
     "if (c == 8'h38) begin st <= P_END; end", 'CFG RAM 8 taken as 16-bit'),
    ('cfg_memattr_ignored', 'intv_cfgparse.sv', "is_name(name, nlen, N_MEMATTR, 4'd7) ? S_MEM :",
     "1'b0 ? S_MEM :", 'the CFG section [memattr] ignored'),
    ('cfg_preload_ignored', 'intv_loader.sv',
     "q_data = (q_kind == 3'd1 || q_kind == 3'd2) && (q_pg ? rq[54:51] == ey : q_app);",
     "q_data = q_kind == 3'd1 && (q_pg ? rq[54:51] == ey : q_app);", 'the CFG section [preload] ignored'),
    ('bank_decode', 'intv_cart.sv', "if (fx_we && qa[15:5] == 11'd2)", "if (fx_we && qa[15:4] == 12'd4)",
     'bank registers $0050-$005F not decoded'),
    ('bank_index', 'intv_cart.sv', "wire logic [7:0]  bk    = bank[{qa[11], qa[15:12]}];",
     "wire logic [7:0]  bk    = bank[{1'b0, qa[15:12]}];", 'a bank window uses the lower 2K\'s register'),
    ('bank_ss', 'intv_cart.sv', "bank[{ss_addr[2:0] - 3'd7, 2'(i)}] <= ss_wdata[8*i +: 8];",
     "bank[{ss_addr[2:0] - 3'd6, 2'(i)}] <= ss_wdata[8*i +: 8];", 'bank registers restored one word off'),
    ('pool_no_fill', 'intv_loader.sv', "st <= asm_q[30:29] == A_POOL ? F_FILL :",
     "st <= asm_q[30:29] == A_POOL ? F_SCAN :", 'pool blocks not filled ($FFFF gaps)'),
    ('rom_tabcrc_off', 'intv_romparse.sv', "                    if ({got, in_c} != crc) begin\n                        err <= 8'h23;",
     "                    if (1'b0) begin\n                        err <= 8'h23;", '.rom table CRC not checked'),
    ('rom_no_clear', 'intv_loader.sv', "st <= (src == 2'd3 && !cov_q) ? F_COV_Z : F_COV_N;",
     "st <= F_COV_N;", '.rom: blocks no segment wrote not cleared'),
    ('rom_fine_off', 'intv_loader.sv', "if (!(rp_tq[6:4] <= b[2:0] && b[2:0] <= rp_tq[2:0]))",
     "if (!(rp_tq[6:4] <= b[2:0] && b[2:0] < rp_tq[2:0]))", '.rom fine range one block short'),
    ('cfg_lag', 'intv_loader.sv', "o = st == F_CF0 ? cfg_n - 25'd3 : st == F_CF1 ? cfg_n - 25'd2 : cfg_n - 25'd1;",
     "o = st == F_CF0 ? cfg_n - 25'd3 : st == F_CF1 ? cfg_n - 25'd2 : cfg_n;", 'the CFG\'s last byte dropped'),
    ('cfg_stale', 'intv_loader.sv', "cfg_on <= cnt[1] != 25'd0 && !(cinl && clen == 32'd0);",
     "cfg_on <= cnt[1] != 25'd0;", 'a CFG the data table no longer lists applied to a reload'),
    # cfg_refeed (intv_loader's "once per CFG stream" guard dropped: a CFG kept from the last load,
    # not streamed again, had its last bytes fed again at a reload) is retired with the CFG fetch
    # (autocfg): every new cartridge fetches its CFG afresh or has none, so no CFG is kept across a
    # reload and no image can show the fault (the autocfg full run: not caught). The guard stays.
    # the step-8 review
    ('sel_no_range_match', 'intv_pagesel.sv', "wdata[15:4] == {addr[15:12], 8'hA5}", "wdata[11:4] == 8'hA5",
     'a page select taken from another range\'s value'),
    ('unpaged_page0_only', 'intv_loader.sv', "wire  logic        q_app  = ey == 4'd0 || paged[er];",
     "wire  logic        q_app  = ey == 4'd0;", 'lines without PAGE only on page 0 of a paged range'),
    ('trim_off', 'intv_cart.sv', "wire logic        trim  = lo8 >= tab_q[37:30] && lo8 <= tab_q[29:22];",
     "wire logic        trim  = 1'b1;", 'a CFG block answers past its declared words'),
    ('bank_start_zero', 'intv_cart.sv', "            for (int i = 0; i < 32; i++) bank[i] <= {4'(i), i[4], 3'd0};",
     "            for (int i = 0; i < 32; i++) bank[i] <= 8'd0;", 'bank registers 0 after a load'),
    ('asm_one_pass', 'intv_loader.sv', "if (q_ov && q_data && q_pg == apass) begin",
     "if (q_ov && q_data && !apass) begin", 'a line without PAGE over the page\'s own words'),
    ('ram_per_page', 'intv_loader.sv', "if (y != 4'd0 && (!paged[r] || h_mode == H_RAM)) begin",
     "if (y != 4'd0 && !paged[r]) begin", 'cart RAM in a paged range not shared by its pages'),
    # build step 9: the ECS Auto rule (intv_media's probe, intv_cart's m4): the ECS flag ignored
    # (Game Factory), the $4800 word not checked against $03FF (ecsnohook: $1234 there), the hook
    # ignored (ecshook), the $500C header ignored (Atlantis), the off case ignored (a $4000-$47FF map:
    # cart4000; the ECS incompatible tag: ecsoffcfg, ecsoffrom), no cartridge not on (NEGNOCART), the
    # probe at $4801. intv_cart's m4 alone cannot be planted: the loader sets ECS_OFF for every page-0
    # entry of $4000-$47FF that m4 counts (R, W or B: intv_loader's CFG and .rom paths; the table path
    # has no B entries), so with m4 ignored every image keeps its mode (the fix9 run: not caught)
    # build step 10: the Intellivoice's Auto rule without its ROM check (the flagged title without
    # ivoice.bin), and with the flag ignored (the voice titles, the CFG and .rom cases)
    ('voice_auto_norom', 'intv_media.sv', "assign voice_auto = flags[1] && slot_st[11:10] == 2'd2;",
     "assign voice_auto = flags[1];", 'Auto: the voice on without ivoice.bin'),
    ('voice_auto_noflag', 'intv_media.sv', "assign voice_auto = flags[1] && slot_st[11:10] == 2'd2;",
     "assign voice_auto = slot_st[11:10] == 2'd2;", 'Auto: the voice flag ignored'),
    ('auto_flag', 'intv_media.sv', "ecs_auto <= (res_ecs || res_none) ? 2'd1", "ecs_auto <= (res_none) ? 2'd1",
     'Auto: the ECS flag ignored'),
    ('auto_4800_any', 'intv_media.sv', "code48 <= c_bus_hit && !c_bus_attr[1] && c_bus_rdata[15:10] == 6'd0;",
     "code48 <= c_bus_hit && !c_bus_attr[1];", 'Auto: any word at $4800 taken as code'),
    ('auto_hook_ignored', 'intv_media.sv', ": (code48 && hdr_ok) ? 2'd1", ": 1'b0 ? 2'd1",
     'Auto: the $4800 hook ignored'),
    ('auto_header_ignored', 'intv_media.sv', ": (code48 && hdr_ok) ? 2'd1", ": code48 ? 2'd1",
     'Auto: code at $4800 turns the ECS on whatever the header (the Imagic titles get its menu)'),
    ('auto_off_ignored', 'intv_media.sv', ": (c_m4 || res_off) ? 2'd0 : 2'd2;", ": 1'b0 ? 2'd0 : 2'd2;",
     'Auto: never off ($4000-$47FF mapped, the ECS incompatible tag)'),
    # the step-9 review: the ECS_OFF flag (the "ECS incompatible" tag of a .rom or a CFG: ecsoffrom,
    # ecsoffcfg) ignored, so those cartridges run with the ECS attached
    ('auto_ecs_off_ignored', 'intv_media.sv', ": (c_m4 || res_off) ? 2'd0 : 2'd2;", ": c_m4 ? 2'd0 : 2'd2;",
     'Auto: the ECS incompatible tag ignored'),
    ('auto_nocart_off', 'intv_media.sv', "res_none <= res_words == 17'd0;", "res_none <= 1'b0;",
     'Auto: no cartridge not on'),
    ('auto_probe_4801', 'intv_media.sv', "(pr_2nd ? 16'h500C : 16'h4800)", "(pr_2nd ? 16'h500C : 16'h4801)",
     'Auto: the probe at $4801'),
    # build step 9b: the CFG found by the cartridge's name (apf_cfgfetch): the extension not
    # replaced (the host is asked for NAME.bin), len_valid not held for the fetch, the length
    # found by reading one too long, "not found" taken as a refusal
    ('fetch_no_ext', 'apf_cfgfetch.sv', "b_d[31 - 8 * ext_p[1:0] -: 8] <= ext_b;",
     "b_d[31 - 8 * ext_p[1:0] -: 8] <= b_q[31 - 8 * ext_p[1:0] -: 8];", 'CFG fetch: the extension not replaced'),
    ('fetch_not_waited', 'apf_datatable.sv', "                    f_start <= 1'b1;\n                    st <= D_FWAIT;",
     "                    f_start <= 1'b1;\n                    st <= D_SET;", 'CFG fetch: the length given before the CFG came'),
    ('fetch_fb_len', 'apf_cfgfetch.sv', "                        len <= o;", "                        len <= o + 32'd1;",
     'CFG fetch: the length found by reading one too long'),
    ('fetch_notfound_err', 'apf_cfgfetch.sv', "                        if (code == 3'd3) begin\n                            res <= 3'd3;",
     "                        if (code == 3'd3) begin\n                            res <= 3'd4;", 'CFG fetch: not found taken as a refusal'),
    # the CFG slot's table entry taken for the cartridge's when the table has none for the
    # cartridge (the 0x0082 size must be used: NOTAB1); the full run of autocfg found it
    # (shrink) the scan's folder rule dropped (a '.' in a folder taken for the extension:
    # CFGDIRNODOT), and the struct RAM's port never given to the steps (they read the
    # bridge's address and their writes are lost)
    ('fetch_dir_dot', 'apf_cfgfetch.sv', "                            has_dot <= 1'b0;                 // a '.' in a folder",
     "                            has_dot <= has_dot;              // a '.' in a folder",
     "CFG fetch: a '.' in a folder taken for the extension"),
    # 0.0.14: the watchdog never fires (a held command hangs the load); a timeout that never
    # ends the fetch (len_valid stays low); a late read's bytes let through to the loader
    ('fetch_wd_never', 'apf_cfgfetch.sv', "if (wd[WD_BITS] && !(cph == 2'd2 && t_done)) begin",
     "if (1'b0 && wd[WD_BITS] && !(cph == 2'd2 && t_done)) begin", 'CFG fetch: the watchdog never fires'),
    ('fetch_to_nolv', 'apf_cfgfetch.sv', "                th   <= 32'(TO_HOLD);\n                st   <= S_TOHOLD;",
     "                th   <= 32'(TO_HOLD);\n                st   <= S_IDLE;", 'CFG fetch: a timeout never ends the fetch'),
    ('cfg_gate_open', 'apf_datatable.sv', "assign loader_wr = bridge_wr && !(bridge_addr[31:24] == 8'h01 && !cfg_wr_ok);",
     "assign loader_wr = bridge_wr;", 'a late CFG read\'s bytes reach the loader'),
    ('fetch_port_bridge', 'apf_cfgfetch.sv', "assign mem_own = b_we || (cph == 2'd0",
     "assign mem_own = 1'b0 && (cph == 2'd0", 'CFG fetch: the struct RAM port never given to the steps'),
    # 0.0.15: Ready to run at PLL lock again (0.0.14's wiring): the fetch's first command queues behind
    # it and the late ack (RTRDLY) runs the watchdog out
    ('rtr_at_lock', 'apf_datatable.sv', "    initial setup_done = 1'b0;", "    initial setup_done = 1'b1;",
     'Ready to run before the CFG fetch'),
    ('dt_cfg_as_cart', 'apf_datatable.sv', "end else if (!is_cfg && !got_cart && !rescan) begin",
     "end else if (!got_cart && !rescan) begin", 'the CFG entry taken for the cartridge without a cartridge entry'),
]
PLANT_IMAGES = ('C83EEA4C', '095638C0', 'synthetic:a', 'C2063C08', '00BE8BBA', 'REQ0', 'NOTAB1',
                'RELOAD0', 'RELOAD1', 'cfgmap', 'rombank', 'zoo2', 'zoo5', 'romfine', 'rom_tabcrc',
                'RELOAD2', 'RELOAD3', 'zoo6', 'zoo7', 'zoo8',
                'CE8FC699', 'NEGNOCART', 'ecshook', 'ecsnohook', 'ecsavail', 'cart4000', '13FF363C',
                'ecsoffcfg', 'ecsoffrom', 'CFGFB', 'CFGODD', 'CFGMISS', 'CFGDIRNODOT',
                'NOHOSTGF', 'NOHOSTRD', 'RTRHOLD', 'NOHOSTRL', 'RTRDLY', 'RTRDLYRL',
                'VOICECFG', 'VOICECMP', 'VOICEROM', 'NOIVOICE')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--all', action='store_true', help='set, then planted faults')
    ap.add_argument('--only', help='comma-separated CRCs or synthetic names')
    ap.add_argument('--no-build', action='store_true')
    ap.add_argument('--plants-only', action='store_true')
    ap.add_argument('--plant', help='comma-separated plant names (with --all or --plants-only)')
    ap.add_argument('--no-step8', action='store_true', help='leave out the step-8 format images')
    a = ap.parse_args()
    verilator = os.environ.get('VERILATOR', 'verilator')
    work = os.environ.get('WORK', os.path.join(ROOT, 'sim', 'work', 'tb_loader'))
    lib = os.environ.get('INTV_LIBRARY', os.path.expanduser('~/ROMLibrary/Intellivision'))
    bdir = os.environ.get('INTV_BIOS_DIR', os.path.expanduser('~/pocket_projects/intellivision/bios'))
    bios_paths = {'exec': os.path.join(bdir, 'exec.bin'), 'grom': os.path.join(bdir, 'grom.bin'),
                  'ecs': os.path.join(bdir, 'ECS.bin'), 'ivoice': os.path.join(bdir, 'IVOICE.BIN')}
    bios = {k: open(p, 'rb').read() for k, p in bios_paths.items()}
    sizes = {'exec': 8192, 'grom': 2048, 'ecs': 24576, 'ivoice': 2048}
    for k, n in sizes.items():
        if len(bios[k]) != n:
            sys.exit('%s: %d bytes, expected %d' % (bios_paths[k], len(bios[k]), n))
    os.makedirs(work, exist_ok=True)

    imgs = load_set(lib)
    syn = [i for i in imgs if i['name'] == 'synthetic:a']
    if syn:
        # refused loads (not part of the 25): the data table length 4 bytes too
        # long, 4 bytes too short (more than 3 pad bytes), and no cartridge
        for neg, adj in (('long', 4), ('short', -4), ('nocart', 0)):
            imgs.append(dict(syn[0], name='refused:' + neg, crc='NEG' + neg.upper(), neg=neg, lenadj=adj,
                             layout='0', flags='00'))
        # the length check, data table before and after the files: the
        # 0x0082 size 4 bytes too long (loaded with the table's length,
        # err[4]), and a table without the cartridge (the 0x0082 size used)
        for dt in (0, 1):
            imgs.append(dict(syn[0], name='length:0x0082 +4, dtfirst %d' % dt, crc='REQ%d' % dt,
                             reqadj=4, dtfirst=dt))
            imgs.append(dict(syn[0], name='length:no table entry, dtfirst %d' % dt, crc='NOTAB%d' % dt,
                             notable=True, dtfirst=dt))
    # build step 10: a title the CRC table flags for the Intellivoice, without ivoice.bin: Auto off
    fv = [i for i in imgs if i['name'] == 'forced:2B856EBC']
    if fv:
        imgs.append(dict(fv[0], name='voice: flagged title, no ivoice.bin', crc='NOIVOICE', noivoice=True))
    # user reloads in one session (no power-on reset between): synthetic:a,
    # then synthetic:b (another size, in the table, data table after the
    # files), or C2063C08 (paged layout 26, no table entry: its own 0x0082
    # size, data table first)
    byname = {i['name']: i for i in imgs}
    if syn and 'synthetic:b' in byname:
        imgs.append(dict(syn[0], name='reload:synthetic:a then synthetic:b', crc='RELOAD0',
                         reload=byname['synthetic:b'], dtfirst=0))
    cpg = [i for i in imgs if i['crc'] == 'C2063C08']
    if syn and cpg:
        imgs.append(dict(syn[0], name='reload:synthetic:a then C2063C08, no table entry', crc='RELOAD1',
                         reload=cpg[0], notable2=True, dtfirst=1))
    if not a.no_step8:
        sys.path.insert(0, os.path.join(ROOT, 'sim', 'testroms', 'step8'))
        import build_images
        for im in build_images.images():
            imgs.append(dict(im, crc=im['name'], image=im['name'], step8=True))
        # reloads with a CFG (step 8): none beside the second cartridge, or the same CFG file
        # under its name (the fetch finds it again)
        s8 = {i['name']: i for i in imgs if i.get('step8')}
        if 'zoo1' in s8 and 'synthetic:b' in byname:
            imgs.append(dict(s8['zoo1'], name='reload:zoo1 + CFG then synthetic:b, CFG cleared', crc='RELOAD2',
                             reload=byname['synthetic:b'], cfgclear2=True, dtfirst=0))
        if 'zoo5' in s8 and 'zoo3' in s8:
            imgs.append(dict(s8['zoo5'], name='reload:zoo5 + CFG then zoo3\'s image, CFG kept', crc='RELOAD3',
                             reload=dict(s8['zoo3'], cfg=None), dtfirst=1))
        # build step 9b: the CFG found by the cartridge's name (apf_cfgfetch): no size in the
        # table (its length found by reading), an odd length with no final line feed (by
        # reading: the last read below 4 bytes), the cartridge's name in capitals, a '.' in a
        # folder, a path without an extension (no CFG), a CFG under another name (not found),
        # and a .rom with a CFG beside it (fetched, ignored)
        # build step 10: the Intellivoice's Auto rule (voice auto): a CFG's voice = 1 and
        # voice_compat = 2, a .rom's compatibility tag (Intellivoice "requires")
        if 'zoo1' in s8:
            z = s8['zoo1']
            imgs.append(dict(z, name='voice: CFG voice = 1', crc='VOICECFG', cfg=z['cfg'] + b'\n[vars]\nvoice = 1\n'))
            imgs.append(dict(z, name='voice: CFG voice_compat = 2', crc='VOICECMP',
                             cfg=z['cfg'] + b'\n[vars]\nvoice_compat = 2\n'))
        if 'romfine' in s8:
            acc, fine = [0] * 16, [0x07] * 32
            acc[5] = 0x11
            rv = build_images.rom_file([(0x50, 0x50, [(0x5000 + i) ^ 0x5A5A for i in range(0x100)])], acc, fine,
                                       build_images.tag(0x06, [0x08, 0, 0]) + b'\x00')
            imgs.append(dict(s8['romfine'], name='voice: .rom tag (requires)', crc='VOICEROM', data=rv,
                             image='voicerom'))
        if 'zoo2' in s8:
            z = s8['zoo2']
            odd = z['cfg'].rstrip(b'\r\n')
            if len(odd) % 2 == 0:
                odd = b';x\n' + odd
            imgs.append(dict(z, name='cfg fetch: no size in the table', crc='CFGFB', nodt=True))
            imgs.append(dict(z, name='cfg fetch: odd length, no final line feed, no size in the table',
                             crc='CFGODD', cfg=odd, nodt=True))
            imgs.append(dict(z, name='cfg fetch: odd length, no final line feed', crc='CFGODDT', cfg=odd))
            imgs.append(dict(z, name='cfg fetch: ZOO2X.BIN, zoo2x.cfg', crc='CFGUPPER',
                             cartname='ZOO2X.BIN', cfgname='zoo2x.cfg'))
            imgs.append(dict(z, name='cfg fetch: a dot in a folder', crc='CFGDOTDIR', cartdir='/Assets/intv/v1.0/'))
            imgs.append(dict(z, name='cfg fetch: no extension', crc='CFGNODOT', cartname='zoo2x', nodot=True))
            # (shrink) a '.' in a folder and none in the name: still no extension
            imgs.append(dict(z, name='cfg fetch: a dot in a folder, no extension', crc='CFGDIRNODOT',
                             cartdir='/Assets/intv/v1.0/', cartname='zoo2x', nodot=True))
            imgs.append(dict(z, name='cfg fetch: the CFG under another name', crc='CFGMISS',
                             cfgname='other.cfg', miss=True))
            if 'rombank' in s8:
                imgs.append(dict(s8['rombank'], name='cfg fetch: a .rom with a CFG beside it', crc='ROMCFG',
                                 cfg=z['cfg']))
            # 0.0.14: a host that never answers (the owner's Pocket held a second cartridge at the
            # test pattern): the watchdog gives up, the cartridge maps without its CFG; a read
            # answered after the map (late) must not reach the loader; Ready to run never acked
            imgs.append(dict(z, name='cfg fetch: get filename never answered', crc='NOHOSTGF', nohost=0x190))
            imgs.append(dict(z, name='cfg fetch: open never answered', crc='NOHOSTOF', nohost=0x192))
            imgs.append(dict(z, name='cfg fetch: read answered after the timeout', crc='NOHOSTRD', nohost=0x180,
                             late=True))
            imgs.append(dict(z, name='cfg fetch: Ready to run never acked', crc='RTRHOLD', rtrhold=True))
            # 0.0.15: the owner's Pocket acks Ready to run only once it starts the core (0.0.14's photos:
            # later than the 0.9 s watchdog on a first load, never in a Core Settings reload): 600,000
            # clk_74a after all complete here (the watchdog: 2^18); with Ready to run after the fetch
            # the CFG still loads, also when the host starts loading after setup_done's safety (acdelay)
            imgs.append(dict(z, name='cfg fetch: Ready to run acked late', crc='RTRDLY', rtrdelay=600000))
            imgs.append(dict(z, name='cfg fetch: loading after the setup safety', crc='ACDELAY',
                             acdelay=(1 << 24) + 2000000))
            if 'zoo1' in s8 and 'synthetic:b' in byname:
                imgs.append(dict(s8['zoo1'], name='cfg fetch: get filename answered late, then a reload',
                                 crc='NOHOSTRL', nohost=0x190, late=True, reload=byname['synthetic:b'],
                                 cfgclear2=True, dtfirst=0))
                imgs.append(dict(s8['zoo1'], name='cfg fetch: Ready to run acked late, then a reload',
                                 crc='RTRDLYRL', rtrdelay=600000, reload=byname['synthetic:b'],
                                 cfgclear2=True, dtfirst=0))
        # build step 9: the ECS Auto rule's cartridges (sim/testroms/step9): the ECS flag and the
        # $4800 hook (ecssound), the hook alone (ecshook), attached (ecsavail), $4000 mapped (cart4000),
        # the ECS incompatible tags (ecsoffcfg, ecsoffrom: off)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'step9_build_images', os.path.join(ROOT, 'sim', 'testroms', 'step9', 'build_images.py'))
        b9 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(b9)
        for im in b9.images(os.path.join(work, 'step9_build')):
            imgs.append(dict(name=im['name'], data=im['data'], cfg=im['cfg'], want_err=0, crc=im['name'],
                             image=im['name'], step8=True))
    if a.only:
        keep = set(a.only.split(','))
        imgs = [i for i in imgs if i['crc'] in keep or i['name'] in keep]
    tab = intv_mapper.Tables(ROOT)
    libcsv = {r['crc32']: r for r in csv.DictReader(open(LIBCSV, newline=''))}

    rc_fail = []
    t0 = time.time()
    exp = {}
    for img in imgs:
        lines, s = expect(img, tab, bios)
        exp[img['crc']] = (lines, s)
        # forced: images share a CRC with a library image, not its content
        want = None if img.get('neg') or img['name'].startswith('forced:') or img.get('step8') \
            else libcsv.get(img['crc'])
        notes = []
        if s['mapped'] != s['model_mapped'] and not img.get('neg') and not s['err']:
            notes.append('mapped %s != model %s' % (s['mapped'], s['model_mapped']))
        if want:
            if (int(want['layout']), want['flags'], want['mapped_crc']) != (s['layout'], '%02X' % s['flags'],
                                                                           s['mapped']):
                notes.append('mapper_library.csv: layout %s flags %s mapped %s' %
                             (want['layout'], want['flags'], want['mapped_crc']))
        if img.get('step8'):
            if s['err'] != img['want_err'] and not img.get('cfglenadj'):
                notes.append('model err %s, the image wants %s' % (s['err'], img['want_err']))
        elif (int(img['layout']), img['flags']) != (s['layout'], '%02X' % s['flags']):
            notes.append('set file: layout %s flags %s' % (img['layout'], img['flags']))
        if notes:
            rc_fail.append('expect ' + img['crc'])
            print('  FAIL model %s: %s' % (img['crc'], '; '.join(notes)))
    print('expectations: %d images, %.1fs (model mapped CRC = mapper_library.csv for every library image)'
          % (len(imgs), time.time() - t0) if not rc_fail else 'expectations: FAIL')

    binary = os.path.join(work, 'obj', 'tb_loader')
    if not a.no_build:
        t1 = time.time()
        binary = build(work, CORE, verilator)
        if not binary:
            print('TB_LOADER_ALL FAIL (build)')
            return 1
        print('build: %.0fs' % (time.time() - t1))

    tmp = tempfile.mkdtemp(prefix='img_', dir=work)
    try:
        if not a.plants_only:
            failed = run_set(binary, imgs, exp, bios_paths, work, tmp)
            nneg = sum(1 for i in imgs if i.get('neg'))
            print('set: %d images and %d refused loads, %d pass, %d fail' %
                  (len(imgs) - nneg, nneg, len(imgs) - len(failed), len(failed)))
            rc_fail += failed
        if a.all or a.plants_only:
            pimgs = [i for i in imgs if (i['crc'] in PLANT_IMAGES or i['name'] in PLANT_IMAGES)
                     and (not i.get('neg') or i['crc'] == 'NEGNOCART')]   # no cartridge: the Auto plant
            for name, fn, frm, to, what in PLANTS:
                if a.plant and name not in a.plant.split(','):
                    continue
                d = os.path.join(work, 'plant_' + name)
                shutil.rmtree(d, ignore_errors=True)
                os.makedirs(os.path.join(d, 'rtl'))
                for f in RTL:
                    shutil.copy(os.path.join(CORE, f), os.path.join(d, 'rtl', f))
                p = os.path.join(d, 'rtl', fn)
                s = open(p).read()
                if s.count(frm) != 1:
                    print('PLANT %s: pattern not found once' % name)
                    rc_fail.append('plant ' + name)
                    continue
                open(p, 'w').write(s.replace(frm, to))
                b = build(d, os.path.join(d, 'rtl'), verilator, strict=False)
                if not b:
                    print('PLANT %s: build failed' % name)
                    rc_fail.append('plant ' + name)
                    continue
                caught = run_set(b, pimgs, exp, bios_paths, d, tmp, quiet=True)
                if caught:
                    print('PLANT %s (%s): caught by %s' % (name, what, ' '.join(caught)))
                else:
                    print('PLANT %s (%s): NOT caught' % (name, what))
                    rc_fail.append('plant ' + name)
                shutil.rmtree(os.path.join(d, 'obj'), ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if rc_fail:
        print('TB_LOADER_ALL FAIL (%s)' % ', '.join(rc_fail))
        return 1
    print('TB_LOADER_ALL pass')
    return 0


if __name__ == '__main__':
    sys.exit(main())
