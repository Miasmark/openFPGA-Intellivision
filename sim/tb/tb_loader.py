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

CORE = os.path.join(ROOT, 'src', 'fpga', 'core')
RTL = ['intv_sram.sv', 'intv_cart.sv', 'intv_sysrom.sv', 'intv_loader.sv', 'intv_media.sv',
       'apf_datatable.sv']
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
NSS = 21


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

class Mirror:
    """The cartridge port as the bench drives it: CartModel plus the state words."""

    def __init__(self, words, pt, crc, lid, flags, hit):
        self.cart = m.CartModel(words, pt)
        self.words = words
        self.nwords = len(words)
        self.crc, self.lid, self.flags, self.hit = crc, lid, flags, hit

    def read(self, a):
        e = self.cart.pt[a >> 11]
        kind, paged = (e >> 14) & 3, (e >> 13) & 1
        v = None
        if kind == m.KIND_ROM:
            # CartModel reads the image list; a restored or cleared length cuts it
            d = m.decode_page_entry(e)
            unit = d['offset']
            ok = True
            if d['paged']:
                y = self.cart.sel[a >> 12]
                ok = y < d['npages']
                unit += 2 * y
            i = unit * m.PAGE_WORDS + (a % m.PAGE_WORDS)
            if ok and i < self.nwords:
                v = self.words[i]
        elif kind != m.KIND_NONE:
            v = self.cart.read(a)
        return (v is not None), kind, paged, (0xFFFF if v is None else v)

    def write(self, a, v):
        self.cart.write(a, v)

    def block(self, r):
        c = 0
        buf = bytearray()
        for a in range(r << 12, (r + 1) << 12):
            h, k, p, v = self.read(a)
            buf += bytes((h | k << 1 | p << 3, v >> 8, v & 0xFF))
        return crc32(bytes(buf), c)

    def ss(self):
        pt = self.cart.pt
        w = [int(self.crc, 16), (int(self.hit) << 16) | (self.flags << 8) | self.lid, self.nwords]
        w += [(pt[2 * k + 1] << 16) | pt[2 * k] for k in range(16)]
        sel = self.cart.sel
        w += [sum(sel[i] << (4 * i) for i in range(8)), sum(sel[8 + i] << (4 * i) for i in range(8))]
        return w

    def load_ss(self, w):
        self.crc = '%08X' % w[0]
        self.lid, self.flags, self.hit = w[1] & 0xFF, (w[1] >> 8) & 0xFF, bool(w[1] >> 16 & 1)
        self.nwords = w[2]
        for k in range(16):
            self.cart.pt[2 * k] = w[3 + k] & 0xFFFF
            self.cart.pt[2 * k + 1] = w[3 + k] >> 16
        for i in range(8):
            self.cart.sel[i] = (w[19] >> (4 * i)) & 15
            self.cart.sel[8 + i] = (w[20] >> (4 * i)) & 15


def expect(img, tab, bios):
    """Every line the bench prints for this image, and the model's summary.

    A refused load (img['neg']: no cartridge, or a data table length the
    strobes do not cover) maps nothing: layout 0, no words, CRC 0, err 1.
    The length check (apf_datatable len_chk, err[4]): the host's 0x0082 size
    is the file's size plus img['reqadj']; the data table's is plus
    img['lenadj'], or missing with img['notable'] (then the 0x0082 size is
    used); no cartridge sends no 0x0082 and a table size of 0.
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
        words, crc_v = [], 0
        cart, lid, flags, hit = m.CartModel([], [0] * m.NPAGES), 0, 0, False
        err, cslot = 1 | e4, (0 if img['neg'] == 'nocart' else 1)
    else:
        crc_v, words = m.load_through_loader(data)
        assert crc_v == crc32(data) and words == m.bytes_to_words(data)
        for meth in ('linear', 'binary'):
            assert tab.lookup(crc_v, len(words), meth) == tab.lookup(crc_v, len(words), 'linear')
        cart, lid, flags, hit = tab.model(words, crc_v)
        err = e4
        cslot = 1 if err & 15 else 2      # err[4] alone: still ok (the second card shows it)
    crc = '%08X' % crc_v
    L = []
    L.append('status crc %s words %d layout %d flags %02X hit %d err %d lenst %d' % (
        crc, len(words), lid, flags, int(hit), err, lenst))
    L.append('slots %03X' % (cslot | 2 << 4 | 2 << 6 | (2 << 8 if bios.get('ecs') else 0) | 2 << 10))
    L.append('image %08X' % crc32(struct.pack('>%dH' % len(words), *words)))
    if bios.get('ecs'):
        L.append('ecs %08X' % crc32(bios['ecs']))
    ex = bios['exec']
    L.append('exec %08X' % crc32(b''.join(struct.pack('>H', ((ex[i] << 8) | ex[i + 1]) & 0x3FF)
                                          for i in range(0, 8192, 2))))
    L.append('grom %08X' % crc32(bios['grom']))
    L.append('ivoice %08X' % crc32(bios['ivoice']))
    mi = Mirror(words, cart.pt, crc, lid, flags, hit)
    for i, w in enumerate(mi.ss()):
        L.append('ss0 %d %08X' % (i, w))
    # A and the mapped-space CRC
    mi.cart.reset()
    for r in range(16):
        L.append('A %d %08X' % (r, mi.block(r)))
    mc = 0
    for a in range(0x10000):
        h, k, p, v = mi.read(a)
        mc = crc32(struct.pack('>H', v if (h and k == m.KIND_ROM) else 0xFFFF), mc)
    for r in range(16):
        d = m.decode_page_entry(mi.cart.pt[2 * r])
        if d['kind'] == m.KIND_ROM and d['paged']:
            for y in range(1, d['npages']):
                mi.write((r << 12) + 0xFFF, (r << 12) + 0xA50 + y)
                mc = crc32(b''.join(struct.pack('>H', mi.read(a)[3])
                                    for a in range(r << 12, (r + 1) << 12)), mc)
            mi.write((r << 12) + 0xFFF, (r << 12) + 0xA50)
    L.append('mapped %08X' % mc)
    model_mapped = cart.mapped_space_crc()
    # B
    for r in range(16):
        for y in YS:
            mi.write((r << 12) + 0xFFF, (r << 12) + 0xA50 + y)
            L.append('B %d %d %08X' % (r, y, mi.block(r)))
        mi.write((r << 12) + 0xFFF, (r << 12) + 0xA50)
    # C, D
    for a in range(0x10000):
        mi.write(a, (a * 0x9E37 + 0x1234) & 0xFFFF)
    for r in range(16):
        L.append('C %d %08X' % (r, mi.block(r)))
    for r in range(16):
        mi.write((r << 12) + 0xFFF, (r << 12) + 0xA50 + ((r + 5) & 15))
    mi.cart.reset()
    for i, w in enumerate(mi.ss()):
        L.append('ssd %d %08X' % (i, w))
    for r in range(16):
        L.append('D %d %08X' % (r, mi.block(r)))
    # E, Z, F
    for r in range(16):
        mi.write((r << 12) + 0xFFF, (r << 12) + 0xA50 + (r & 3))
    ss1 = mi.ss()
    for i, w in enumerate(ss1):
        L.append('ss1 %d %08X' % (i, w))
    eb = [mi.block(r) for r in range(16)]
    for r in range(16):
        L.append('E %d %08X' % (r, eb[r]))
    mi.load_ss([0] * NSS)
    for i, w in enumerate(mi.ss()):
        L.append('ssz %d %08X' % (i, w))
    for r in range(16):
        L.append('Z %d %08X' % (r, mi.block(r)))
    mi.load_ss(ss1)
    for i, w in enumerate(mi.ss()):
        L.append('ss2 %d %08X' % (i, w))
    for r in range(16):
        L.append('F %d %08X' % (r, mi.block(r)))
    # the hazard: no finish runs again, the selects stay
    L.append('hazard busy 0 ready 1')
    ssf = mi.ss()
    for i in (19, 20):
        L.append('ssh %d %08X' % (i, ssf[i]))
    # the reload: another cartridge (img['reload']) in the same session,
    # its own 0x0082 size, in the table or not (img['notable2'])
    if img.get('reload'):
        rdata = img['reload']['data']
        rcrc, rwords = m.load_through_loader(rdata)
        rcart, rlid, rflags, rhit = tab.model(rwords, rcrc)
        L.append('reload status crc %08X words %d layout %d flags %02X hit %d err 0 lenst %d' % (
            rcrc, len(rwords), rlid, rflags, int(rhit), 3 if img.get('notable2') else 1))
        L.append('reload slots %03X' % (2 | 2 << 4 | 2 << 6 | (2 << 8 if bios.get('ecs') else 0) | 2 << 10))
        L.append('reload image %08X' % crc32(struct.pack('>%dH' % len(rwords), *rwords)))
        rm = Mirror(rwords, rcart.pt, '%08X' % rcrc, rlid, rflags, rhit)
        for i, w in enumerate(rm.ss()):
            L.append('rss %d %08X' % (i, w))
        rm.cart.reset()
        for r in range(16):
            L.append('R %d %08X' % (r, rm.block(r)))
    L.append('end')
    return L, dict(crc=crc, layout=lid, flags=flags, hit=hit, mapped='%08X' % mc,
                   model_mapped='%08X' % model_mapped)


# ---------------------------------------------------------------------- the bench

def build(work, rtl_dir, verilator, strict=True):
    obj = os.path.join(work, 'obj')
    os.makedirs(work, exist_ok=True)
    tables = os.path.join(CORE, 'tables')
    cmd = [verilator, '--binary', '--timing', '-j', '4', '-Wall', '-Wno-fatal', '-Wno-TIMESCALEMOD', '-Wno-PROCASSINIT',
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


def run_one(binary, img, path, bios_paths, work, k, timeout=1500, path2=None):
    out = os.path.join(work, 'out_%s.txt' % img['crc'])
    args = [binary, '+out=' + out, '+seed=%d' % (k + 1)]
    if path2:
        args.append('+cart2=' + path2)
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
        if bios_paths.get(key):
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
        if g != w:
            bad.append('line %d: got "%s", want "%s"' % (i + 1, g, w))
    return bad


def run_set(binary, imgs, exp, bios_paths, work, tmp, quiet=False):
    """Run each image; returns the list of failing image names."""
    failed = []
    for k, img in enumerate(imgs):
        path = os.path.join(tmp, '%s.bin' % img['crc'])
        with open(path, 'wb') as f:
            f.write(img['data'])
        path2 = None
        if img.get('reload'):
            path2 = os.path.join(tmp, '%s_2.bin' % img['crc'])
            with open(path2, 'wb') as f:
                f.write(img['reload']['data'])
        try:
            so, got, dt = run_one(binary, img, path, bios_paths, work, k, path2=path2)
        finally:
            os.remove(path)
            if path2:
                os.remove(path2)
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
    ('pt_off_by_one', 'intv_loader.sv', "assign lay_ra = {lid[4:0], p[4:0]};",
     "assign lay_ra = {lid[4:0], p[4:0] + 5'd1};", 'page table read one entry off'),
    ('odd_low_byte', 'intv_loader.sv', "if (st == F_FIX && len[0] &&", "if (st == F_FIX && 1'b0 &&",
     'odd length: pad byte left in the last word'),
    ('default_uncut', 'intv_loader.sv', "else if (lid == 8'd1 && lay_q[15:14] == 2'd1",
     "else if (1'b0 && lay_q[15:14] == 2'd1", 'default map not cut at the image length'),
    ('sram_early', 'intv_media.sv', "intv_sram #(.RD_CYC(3)", "intv_sram #(.RD_CYC(2)",
     'SRAM sampled one clock early'),
    ('sel_no_reset', 'intv_cart.sv', "if (mreset || ld_res_we)", "if (ld_res_we)",
     'machine reset keeps the page selects'),
    ('ss_no_sel', 'intv_cart.sv', "8'd19: for (int i = 0; i < 8; i++) sel[i] <= ss_wdata[4*i +: 4];",
     "8'd19: ;", 'state restore drops the selects of ranges 0-7'),
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
    ('pending_byte0', 'intv_loader.sv', "                        pending <= 1'b1;\n                        seq_err <= 1'b0;",
     "                        seq_err <= 1'b0;", 'a reload\'s byte 0 does not arm the finish'),
    ('req_len_first', 'apf_datatable.sv', "            req_len  <= wr_size;",
     "            if (!req_seen) req_len <= wr_size;", 'only the first 0x0082 size kept'),
]
PLANT_IMAGES = ('C83EEA4C', '095638C0', 'synthetic:a', 'C2063C08', '00BE8BBA', 'REQ0', 'NOTAB1',
                'RELOAD0', 'RELOAD1')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--all', action='store_true', help='set, then planted faults')
    ap.add_argument('--only', help='comma-separated CRCs or synthetic names')
    ap.add_argument('--no-build', action='store_true')
    ap.add_argument('--plants-only', action='store_true')
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
        want = None if img.get('neg') or img['name'].startswith('forced:') else libcsv.get(img['crc'])
        notes = []
        if s['mapped'] != s['model_mapped'] and not img.get('neg'):
            notes.append('mapped %s != model %s' % (s['mapped'], s['model_mapped']))
        if want:
            if (int(want['layout']), want['flags'], want['mapped_crc']) != (s['layout'], '%02X' % s['flags'],
                                                                           s['mapped']):
                notes.append('mapper_library.csv: layout %s flags %s mapped %s' %
                             (want['layout'], want['flags'], want['mapped_crc']))
        if (int(img['layout']), img['flags']) != (s['layout'], '%02X' % s['flags']):
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
                     and not i.get('neg')]
            for name, fn, frm, to, what in PLANTS:
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
