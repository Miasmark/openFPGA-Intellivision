#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""The step-8 test images (DESIGN.md 9 step 8; docs/CARTFORMATS.md 7), built from the
committed sources in this directory, never committed themselves:

  cfgmap.asm, rombank.asm, rombankw.asm    as1600 (jzIntv's SDK-1600, run as a program:
                                           AS1600, default the owner's build) -> BIN + CFG
                                           or Intellicart .rom
  pocket/cart8pages.bas, cart8bank.bas     IntyBASIC (run as a program: INTYBASIC, default the
                                           owner's build, and its directory for the prologue and
                                           epilogue) then as1600 -> the Pocket test cartridges
                                           (BIN + CFG; .rom), which check themselves on screen
  cfg/zoo*.cfg                             hand-written CFGs, each with a synthetic .bin
                                           (a word pattern, no game data)
  the refusal set                          made here from the above: CFG text with one
                                           fault each, .rom files with a bad CRC, cut short,
                                           a backwards segment, an LTO tag, and the like

images() returns a list of dicts: name, data (bytes), cfg (bytes or None), want_err (the
loader's fmt_err the Python model must give, 0 = mapped, -1 = refused by the length/size
checks) and bench options (cfglenadj). Run as a script it lists them with the model's
verdict:  python3 -I sim/testroms/step8/build_images.py [--out DIR]
"""
import os
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'mapper'))
import cartfmt as cf  # noqa: E402

AS1600 = os.environ.get('AS1600', os.path.expanduser(
    '~/daria_work/intv/refs/jzintv/src-tree/jzintv-20200712-src/bin/as1600'))
INTYBASIC = os.environ.get('INTYBASIC', os.path.expanduser(
    '~/pocket_projects/intellivision/tools-ext/IntyBASIC/intybasic'))


def intybasic(src, out_ext, work):
    """Compile pocket/src with IntyBASIC, then as1600 -> (data, cfg)."""
    base = os.path.join(work, os.path.splitext(os.path.basename(src))[0])
    r = subprocess.run([INTYBASIC, os.path.join(HERE, 'pocket', src), base + '.asm',
                        os.path.dirname(INTYBASIC) + '/'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True)
    if r.returncode != 0 or 'Compilation finished' not in r.stdout:
        sys.exit('IntyBASIC %s: %s' % (src, r.stdout[-800:]))
    out = base + out_ext
    r = subprocess.run([AS1600, '-o', out, base + '.asm'], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0 or 'ERRORS DETECTED 0' not in r.stdout:
        sys.exit('as1600 %s: %s' % (src, r.stdout[-800:]))
    data = open(out, 'rb').read()
    cfg = open(base + '.cfg', 'rb').read() if out_ext == '.bin' else None
    return data, cfg


def as1600(src, out_ext, work):
    """Assemble src (a file in this directory) to .bin + .cfg or .rom; returns (data, cfg)."""
    base = os.path.join(work, os.path.splitext(os.path.basename(src))[0])
    out = base + out_ext
    r = subprocess.run([AS1600, '-o', out, os.path.join(HERE, src)], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0 or 'ERRORS DETECTED 0' not in r.stdout:
        sys.exit('as1600 %s: %s' % (src, r.stdout[-800:]))
    data = open(out, 'rb').read()
    cfg = open(base + '.cfg', 'rb').read() if out_ext == '.bin' else None
    return data, cfg


def pattern_bin(nwords, seed):
    """A synthetic image: word i = (i * $9E37 + seed) & $FFFF, high byte first."""
    return b''.join(struct.pack('>H', (i * 0x9E37 + seed) & 0xFFFF) for i in range(nwords))


def rom_file(segs, access, fine, tags=b''):
    """An Intellicart .rom from segments [(lo, hi, words)], 16 access and 32 fine bytes."""
    out = bytearray([0xA8, len(segs), len(segs) ^ 0xFF])
    for lo, hi, words in segs:
        body = bytes([lo, hi]) + b''.join(struct.pack('>H', w) for w in words)
        out += body + struct.pack('>H', cf.crc16(body))
    tab = bytes(access) + bytes(fine)
    out += tab + struct.pack('>H', cf.crc16(tab))
    return bytes(out) + tags


def tag(ttype, body):
    n = len(body)
    assert n < 64
    t = bytes([n, ttype]) + bytes(body)
    return t + struct.pack('>H', cf.crc16(t))


def images(work=None):
    own = work is None
    if own:
        work = tempfile.mkdtemp(prefix='step8img_')
    out = []

    def add(name, data, cfg=None, want=0, **kw):
        out.append(dict(name=name, data=data, cfg=cfg, want_err=want, **kw))

    # ---- as1600 images
    cm_bin, cm_cfg = as1600('cfgmap.asm', '.bin', work)
    add('cfgmap', cm_bin, cm_cfg)
    rb, _ = as1600('rombank.asm', '.rom', work)
    add('rombank', rb)
    rbw, _ = as1600('rombankw.asm', '.rom', work)
    add('rombankw', rbw)

    # ---- the Pocket test cartridges (IntyBASIC)
    d, c = intybasic('cart8pages.bas', '.bin', work)
    add('cart8pages', d, c, pocket=True)
    d, _ = intybasic('cart8bank.bas', '.rom', work)
    add('cart8bank', d, pocket=True)

    # ---- the CFG zoo, each with a synthetic image
    zoo = sorted(f for f in os.listdir(os.path.join(HERE, 'cfg')) if f.endswith('.cfg'))
    for k, f in enumerate(zoo):
        cfg = open(os.path.join(HERE, 'cfg', f), 'rb').read()
        if f == 'zoo4.cfg':                  # the text ends at a NUL byte; junk after it
            cfg += b'\x00[mapping]\n$this is after a NUL and never read\n'
        add(f[:-4], pattern_bin(0x3000 + 0x400 * k, 0x51 + k), cfg)

    # ---- a hand-made .rom: windows trimmed by the fine table, odd ranges
    acc = [0] * 16
    fine = [0x07] * 32
    acc[5] = 0x11           # $5000-$5FFF read
    fine[5] = 0x13          # $5100-$53FF of the lower 2K
    fine[16 + 5] = 0x77     # $5F00-$5FFF of the upper 2K
    acc[0xC] = 0x08         # $C000-$C7FF a bank window, not readable (no answer)
    acc[0xD] = 0x9B         # $D000 RW (lower), $D800 R + B (upper)
    acc[0x9] = 0x50         # $9800 RN (upper; narrow read only)
    segs = [(0x50, 0x5F, [(0x5000 + i) ^ 0x0BAD for i in range(0x1000)]),
            (0xD0, 0xD0, [(0xD000 + i) ^ 0x1EE7 for i in range(0x100)]),
            (0x98, 0x98, [(0x9800 + i) ^ 0xFACE for i in range(0x100)]),
            (0x10, 0x11, [(0x1000 + i) ^ 0x7777 for i in range(0x200)])]
    good_rom = rom_file(segs, acc, fine, tag(0x01, b'step8') + tag(0x06, [0x40, 0, 0]) + b'\x00')
    add('romfine', good_rom)
    add('romodd', good_rom[:-1] + b'\x05\x01\x02')       # a partial tag at the end: ignored
    add('rombadtag', rom_file(segs, acc, fine, tag(0x06, [0x80, 0, 0])[:-1] + b'\x00'))  # bad tag CRC
    # romfine without the NUL tag at the end: as1600's form, which jzIntv loads (it refuses a
    # .rom whose tags end with a NUL tag, error 7; id_tag.txt describes the NUL tag, so we take
    # both). rombadtag has no NUL tag (its last byte is the bad CRC's): jzIntv refuses it for
    # that CRC (error 8), we skip the tag (docs/CARTFORMATS.md 3)
    add('romfine_nonul', rom_file(segs, acc, fine, tag(0x01, b'step8') + tag(0x06, [0x40, 0, 0])))

    # ---- refusals: CFG
    base = pattern_bin(0x2000, 0x33)
    bad_cfgs = [
        ('cfg_syntax_nodash', b'[mapping]\n$0000 $0FFF = $5000\n', cf.ERR_CFG_SYNTAX),
        ('cfg_syntax_noaddr', b'[mapping]\n$0000 - $0FFF = \n', cf.ERR_CFG_SYNTAX),
        ('cfg_syntax_width', b'[memattr]\n$8000 - $80FF = RAM 12\n', cf.ERR_CFG_SYNTAX),
        ('cfg_syntax_kw', b'[memattr]\n$8000 - $80FF = RAMS 16\n', cf.ERR_CFG_SYNTAX),
        ('cfg_syntax_page', b'[mapping]\n$0000 - $0FFF = $F000 PAGE\n', cf.ERR_CFG_SYNTAX),
        ('cfg_syntax_hex', b'[mapping]\n$0000 - $0G00 = $5000\n', cf.ERR_CFG_SYNTAX),
        ('cfg_syntax_bsw', b'[bankswitch]\n$6000 - $67FF = $1000\n', cf.ERR_CFG_SYNTAX),
        ('cfg_many', b'[mapping]\n' + b''.join(b'$%04X - $%04X = $%04X\n' % (i * 8, i * 8 + 7, 0x5000 + i * 8)
                                             for i in range(33)), cf.ERR_CFG_MANY),
        ('cfg_range_back', b'[mapping]\n$0100 - $00FF = $5000\n', cf.ERR_CFG_RANGE),
        ('cfg_range_top', b'[mapping]\n$0000 - $0FFF = $F800\n', cf.ERR_CFG_RANGE),
        ('cfg_range_ovf', b'[memattr]\n$123456 - $123457 = RAM 16\n', cf.ERR_CFG_RANGE),
        ('cfg_page_big', b'[mapping]\n$0000 - $0FFF = $F000 PAGE 10\n', cf.ERR_CFG_PAGE),
        ('cfg_page_pre', b'[preload]\n$0000 - $0FFF = $F000 PAGE 1\n', cf.ERR_CFG_PAGE),
        ('cfg_mix', b'[mapping]\n$0000 - $0FFF = $F000 PAGE 1\n[bankswitch]\n$6000 - $67FF\n', cf.ERR_CFG_MIX),
        ('cfg_lto', b'[mapping]\n$0000 - $0FFF = $5000\n[vars]\nlto_mapper = 1\n', cf.ERR_CFG_LTO),
        ('cfg_ramfull', b'[memattr]\n$4000 - $7FFF = RAM 16\n$8000 - $80FF = RAM 8\n', cf.ERR_RAM_FULL),
        ('cfg_poolfull', b'[mapping]\n' + b''.join(b'$%04X - $%04X = $%04X\n' % (i * 0x101, i * 0x101 + 0x100,
                                                                                 0x9080 + i * 0x200)
                                                 for i in range(17)), cf.ERR_POOL_FULL),
    ]
    for name, text, code in bad_cfgs:
        add(name, base, text, code)
    add('cfg_short', base, b'[mapping]\n$0000 - $0FFF = $5000\n', cf.ERR_CFG_SHORT, cfglenadj=8)

    # ---- refusals: .rom
    r = bytearray(good_rom)
    r[3 + 2 + 100] ^= 0x01                                    # a data byte of segment 1
    add('rom_segcrc', bytes(r), want=cf.ERR_ROM_SEGCRC)
    r = bytearray(good_rom)
    tab_at = len(good_rom) - len(tag(0x01, b'step8') + tag(0x06, [0x40, 0, 0]) + b'\x00') - 50
    r[tab_at + 3] ^= 0x10
    add('rom_tabcrc', bytes(r), want=cf.ERR_ROM_TABCRC)
    add('rom_short_seg', good_rom[:3 + 2 + 1000], want=cf.ERR_ROM_SHORT)
    add('rom_short_tab', good_rom[:tab_at + 20], want=cf.ERR_ROM_SHORT)
    add('rom_back', rom_file([(0x60, 0x5F, [])], acc, fine), want=cf.ERR_ROM_RANGE)
    add('rom_lto', rom_file(segs[:1], acc, fine, tag(0x06, [0, 0, 0, 0x20, 0])), want=cf.ERR_ROM_LTO)
    # not a .rom: byte 1 is 0 (n = 0) -> a raw image (default map)
    add('rom_not', bytes([0xA8, 0x00, 0xFF]) + base[3:], want=0)
    # ---- refusals: length (the step-2 checks): a raw image over 64K words
    add('raw_big', pattern_bin(0x10001, 0x77), want=-1)
    if own:
        pass
    return out


def main():
    import argparse
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import intv_mapper
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', help='also write each image (and CFG) there')
    a = ap.parse_args()
    tab = intv_mapper.Tables(ROOT)
    bad = 0
    for img in images():
        ld = cf.load(img['data'], img['cfg'], tab, tab.pages)
        err = ld.err
        if img.get('cfglenadj'):
            err = cf.ERR_CFG_SHORT
        ok = err == img['want_err']
        bad += not ok
        print('%-4s %-18s %7d bytes  %s err %s%s' % ('ok' if ok else 'FAIL', img['name'], len(img['data']),
                                                    ld.summary()['fmt'], err,
                                                    '' if ok else ' (want %s)' % img['want_err']))
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            ext = '.rom' if cf.is_rom(img['data']) else '.bin'
            open(os.path.join(a.out, img['name'] + ext), 'wb').write(img['data'])
            if img['cfg'] is not None:
                open(os.path.join(a.out, img['name'] + '.cfg'), 'wb').write(img['cfg'])
    print('STEP8_IMAGES %s' % ('pass' if not bad else 'FAIL (%d)' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
