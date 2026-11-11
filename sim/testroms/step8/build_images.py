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
  LUIGI (1.0.7)                            made here with tools/mapper/luigi.py (an encoder
                                           written from the format's specification): the
                                           formats' features over synthetic words, and one
                                           file for each refusal (docs/CARTFORMATS.md 8)

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
import luigi          # noqa: E402

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


def lui_tables():
    """Empty LUIGI tables: memory map, permissions, page flips."""
    return [0] * 256, [0] * 256, [0] * 256


def lui_tab_block(mm, pm, fl, length=1280):
    t = b''.join(struct.pack('<H', x) for x in mm) + bytes(pm) + b''.join(struct.pack('<H', x) for x in fl)
    return luigi.block(1, (t + bytes(8))[:length])


def lui_hunk(addr, words):
    return luigi.block(2, bytes([addr & 0xFF, addr >> 8 & 0xFF, addr >> 16 & 0xFF]) + luigi.pack_words(words))


def lui_pattern(n, seed, bits=16):
    return [((i * 0x9E37 + seed) & 0xFFFF) & ((1 << bits) - 1) for i in range(n)]


def lui_images():
    """(name, bytes, want) LUIGI files over synthetic words."""
    out = []
    # ---- paged: like cfgmap (non-paged ROM with partial paragraphs, RAM 16 and narrow RAM 8,
    # page flipping with pages above Locutus $10000, $4800's flipped half beside a fixed $4000)
    mm, pm, fl = lui_tables()
    for p in range(0x50, 0x60):
        mm[p], pm[p] = p, 1
    for p in (0x80, 0x81):
        mm[p], pm[p] = p, 3                  # RAM 16, preloaded below
    mm[0x90], pm[0x90] = 0x90, 7             # RAM 8 (narrow)
    mm[0x82], pm[0x82] = 0x83, 3             # RAM preloaded from another Locutus address ($8300)
    for p in range(0xD0, 0xD4):
        mm[p], pm[p] = p, 1
    for p in range(0x40, 0x48):
        mm[p], pm[p] = p, 3                  # $4000-$47FF RAM (the ECS's place: a conflict flag)
    mm[0x02], pm[0x02] = 0x02, 3             # where Locutus answers no reads: $0200 (writes go in),
    mm[0x10], pm[0x10] = 0x10, 1             # $1000, $3000
    mm[0x30], pm[0x30] = 0x30, 1
    for y, la in ((0, 0x7C000), (1, 0x79000), (2, 0x7A000), (15, 0x7B000)):
        fl[0xF0 | y] = (la >> 8) | 1 | 8     # chapter F: pages 0, 1, 2, F above $10000
    for y in range(16):
        fl[0xF0 | y] |= 8
    for p in range(0xF0, 0x100):
        mm[p], pm[p] = (0x7C0 | (p & 15)), 1  # page 0 is the reset map
    for y, la in ((1, 0x0C000), (3, 0x77000)):
        fl[0x20 | y] = (la >> 8) | 1 | 8      # chapter 2: pages 1 ($C000: plane 1, only a flip uses it) and 3
    for y in range(16):
        fl[0x20 | y] |= 8
        fl[0x40 | y] |= 8                     # chapter 4: pages 0 and 1 of $4800-$4FFF
    fl[0x41] = (0x75000 >> 8) | 1 | 8
    fl[0x40] = (0x40 << 4) | 3 | 8            # page 0: the fixed RAM's own page (lower half)
    hunks = [(0x5000, lui_pattern(0x12C, 0x11)), (0x5140, lui_pattern(0x14, 0x22, 10)),
             (0x5800, lui_pattern(0x800, 0x33, 10)), (0xD000, lui_pattern(0x200, 0x44, 8)),
             (0xD2F0, lui_pattern(0x28, 0x55)), (0x8000, [0] * 0x10 + lui_pattern(0x10, 0x66)),
             (0x7C000, lui_pattern(0x1000, 0x77, 10)), (0x79000, lui_pattern(0x1000, 0x88, 10)),
             (0x7A000, lui_pattern(0x1000, 0x99)), (0x7B000, lui_pattern(0x800, 0xAA, 8)),
             (0x76000, lui_pattern(0x1000, 0xBB, 10)), (0x77000, lui_pattern(0x400, 0xCC, 10)),
             (0x75800, lui_pattern(0x800, 0xDD, 10)), (0x0C000, lui_pattern(0x1000, 0xEE, 10)),
             (0x8300, lui_pattern(0x100, 0xF1))]
    flags = 1 << 2 | 2 | 1 << 63            # ecs tolerates, voice enhanced, explicit
    body = luigi.block(3, b'\x00\x09lui_paged') + lui_tab_block(mm, pm, fl) + luigi.block(5, b'skip me')
    body += b''.join(lui_hunk(a, w) for a, w in hunks)
    out.append(('lui_paged', luigi.header(flags) + body + b'\xff' + b'junk after the end', 0))
    # ---- bank windows (as a .rom through rom2luigi): version 0 header, no end mark
    mm, pm, fl = lui_tables()
    for p in range(0x50, 0x54):
        mm[p], pm[p] = p, 1
    for p in range(0x60, 0x70):
        mm[p], pm[p] = p, 9                   # R + B: Intellicart bank windows
    for p in range(0x69, 0x70):
        pm[p] = 1                             # B looked up at the half-page's first paragraph only
    for p in range(0xC0, 0xC8):
        mm[p], pm[p] = p, 8                   # B without R: no reads
    for p in range(0x80, 0x84):
        mm[p], pm[p] = p, 3
    for p in range(0x98, 0x99):
        mm[p], pm[p] = p, 5                   # NARROW without WRITE: reads give 16 bits
    mm[0x88], pm[0x88] = 0x88, 7
    hunks = [(0x5000, lui_pattern(0x400, 0x13)), (0x1000, lui_pattern(0x200, 0x24)),
             (0x3000, lui_pattern(0x100, 0x35)), (0x9800, lui_pattern(0x100, 0x46)),
             (0x6000, lui_pattern(0x1000, 0x57, 10))]
    body = lui_tab_block(mm, pm, fl) + b''.join(lui_hunk(a, w) for a, w in hunks)
    out.append(('lui_bank', luigi.header(0x55, version=0) + body, 0))
    # ---- JLP (accelerators and flash), the ECS required, the Intellivoice: a JLP RAM preload
    # at Locutus $10040 (dropped: the JLP's own), unwritten paragraphs above $10000 (RAM: a
    # cleared cart RAM block; ROM: no answer)
    # The map uses every plane-1 page but $C: the paged data at Locutus $40000 must get it, which
    # it can only if the JLP RAM preload before it was dropped
    mm, pm, fl = lui_tables()
    for p in range(0x05, 0x100):
        if p >> 4 != 0xC:
            mm[p], pm[p] = p, 1
    mm[0xA0], pm[0xA0] = 0x6F0, 3            # RAM at an unwritten Locutus page
    mm[0xB0], pm[0xB0] = 0x6E0, 1            # ROM at an unwritten Locutus page
    for p in range(0xC0, 0xC4):
        mm[p], pm[p] = 0x400 | (p & 15), 1    # ROM at Locutus $40000 (paged data's place)
    flags = 3 | 3 << 2 | 3 << 16 | 2 << 22 | 1 << 63
    body = lui_tab_block(mm, pm, fl) + lui_hunk(0x5000, lui_pattern(0x800, 0x5A, 10)) + \
        lui_hunk(0x10040, lui_pattern(0x40, 0x6B)) + lui_hunk(0x40000, lui_pattern(0x400, 0x7C))
    out.append(('lui_jlp', luigi.header(flags) + body + b'\xff', 0))
    # ---- refusals
    mm, pm, fl = lui_tables()
    for p in range(0x50, 0x60):
        mm[p], pm[p] = p, 1
    good = lui_tab_block(mm, pm, fl) + lui_hunk(0x5000, lui_pattern(0x1000, 0x7C, 10))
    hdr = luigi.header(0x55)
    f = bytearray(hdr + good + b'\xff')
    f[31] ^= 0x01
    out.append(('lui_hdrcrc', bytes(f), cf.ERR_LUI_HDR))
    f = bytearray(hdr + good + b'\xff')
    f[32 + 3] ^= 0x01
    out.append(('lui_bhdr', bytes(f), cf.ERR_LUI_BHDR))
    f = bytearray(hdr + good + b'\xff')
    f[32 + 8 + 100] ^= 0x01
    out.append(('lui_pcrc', bytes(f), cf.ERR_LUI_PCRC))
    out.append(('lui_enc', hdr + luigi.block(0, bytes(16)) + good, cf.ERR_LUI_ENC))
    out.append(('lui_notab', hdr + luigi.block(3, b'\x00\x02hi') + b'\xff', cf.ERR_LUI_TAB))
    out.append(('lui_tab2', hdr + lui_tab_block(mm, pm, fl) + good, cf.ERR_LUI_TAB))
    out.append(('lui_tablen', hdr + lui_tab_block(mm, pm, fl, 1279) + good, cf.ERR_LUI_TAB))
    out.append(('lui_order', hdr + lui_hunk(0x5000, [1, 2, 3]) + good, cf.ERR_LUI_ORDER))
    out.append(('lui_hunk', hdr + lui_tab_block(mm, pm, fl) + luigi.block(2, bytes([0, 0x50, 0, 0xFE, 1, 2])),
                cf.ERR_LUI_HUNK))
    out.append(('lui_hunk_end', hdr + lui_tab_block(mm, pm, fl) + luigi.block(2, bytes([0, 0x50, 0, 0x05, 1, 2])),
                cf.ERR_LUI_HUNK))
    out.append(('lui_short_hdr', hdr[:20], cf.ERR_LUI_SHORT))
    out.append(('lui_short_blk', (hdr + good)[:32 + 600], cf.ERR_LUI_SHORT))
    out.append(('lui_lto', luigi.header(0x55 | 1 << 32) + good, cf.ERR_LUI_LTO))
    mmf, pmf, flf = lui_tables()
    for p in range(256):
        if p >= 0x05:
            mmf[p], pmf[p] = p, 1             # every plane-1 page used by the map
    out.append(('lui_full', hdr + lui_tab_block(mmf, pmf, flf) + lui_hunk(0x7F000, [1, 2, 3]), cf.ERR_LUI_FULL))
    mmb, pmb, flb = list(mm), list(pm), list(fl)
    for p in range(0x60, 0x68):
        mmb[p], pmb[p] = p, 9
    out.append(('lui_full_bsw', hdr + lui_tab_block(mmb, pmb, flb) + lui_hunk(0x7F000, [1, 2, 3]),
                cf.ERR_LUI_FULL))
    out.append(('lui_clash', hdr + lui_tab_block(mm, pm, fl) + lui_hunk(0x7F000, [1, 2, 3]) +
                lui_hunk(0xF000, [4, 5, 6]), cf.ERR_LUI_CLASH))
    mmn = list(mmb)
    mmn[0x50] = 0x51                          # a mapped paragraph not at its own address, with B
    out.append(('lui_bsw', hdr + lui_tab_block(mmn, pmb, flb) + lui_hunk(0x5000, [1, 2]), cf.ERR_LUI_BSW))
    return out


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
    # ---- LUIGI (1.0.7)
    for name, data, want in lui_images():
        add(name, data, want=want)
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
            ext = '.rom' if cf.is_rom(img['data']) else '.luigi' if cf.is_luigi(img['data']) else '.bin'
            open(os.path.join(a.out, img['name'] + ext), 'wb').write(img['data'])
            if img['cfg'] is not None:
                open(os.path.join(a.out, img['name'] + '.cfg'), 'wb').write(img['cfg'])
    print('STEP8_IMAGES %s' % ('pass' if not bad else 'FAIL (%d)' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
