#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Intellivision mapper model: the memory map the core presents for a cartridge image.

It works the way the RTL loader and cart module will (docs/DESIGN.md 5.2, module 11/12):
CRC32 over exactly the file length (data table size, not the 32-bit bridge strobes)
-> look the CRC up in src/fpga/core/tables/cart_crc.hex -> layout id -> 32 page entries
from cart_layouts.hex -> every CPU read goes through the page table.
An unknown CRC gets layout 1 (the default map) cut at the image length.

Build step 8 (docs/CARTFORMATS.md): IMAGE may also be an Intellicart .rom, and map, read
and fmt take --cfg CFG (BIN + CFG); those go through tools/mapper/cartfmt.py, the model of
the step-8 loader (any format: the 4,096-entry map table, page selects, bank registers).

Commands (images are read in place, from a file or a .zip; nothing is copied):
  map IMAGE [--cfg CFG]     table entry, flags, page table, mapped-space CRC
  read IMAGE ADDR [COUNT]   words the cartridge answers at ADDR (---- = not answered)
       [--cfg CFG]
  fmt IMAGE [--cfg CFG]     the step-8 loader's verdict: format, refusal, map table blocks
  dump IMAGE OUT            the 64K-word space (big-endian, $FFFF where not answered)
                            plus extra pages, exactly the bytes the mapped-space CRC covers;
                            OUT is derived from a game: keep it out of the repository
  evidence IMAGE SPEC...    jump-target evidence for candidate layouts, e.g. "5000:2000 D000:1000"
  check DIR [--out CSV]     every image in DIR: table hit, region proof, mapped-space CRC

Run with python3 -I.
"""
import argparse
import csv
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'mapper'))
import intvcart as m  # noqa: E402

ROOT = os.path.dirname(HERE)


def read_hex(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('//'):
                out.append(int(line, 16))
    return out


class Tables:
    """The two RTL tables, as the loader will see them."""

    def __init__(self, root=ROOT):
        t = os.path.join(root, 'src', 'fpga', 'core', 'tables')
        self.crc = read_hex(os.path.join(t, 'cart_crc.hex'))
        lw = read_hex(os.path.join(t, 'cart_layouts.hex'))
        self.pages = [lw[i:i + m.NPAGES] for i in range(0, len(lw), m.NPAGES)]

    def find(self, crc, method='linear'):
        """Index of crc's entry in the CRC table, or None.

        The table is sorted end to end (padding is CRC FFFFFFFF with layout 0), so the RTL
        may scan it linearly (256 clocks, stop at layout 0) or binary-search it (8 probes).
        Both are modelled; they must agree.
        """
        if method == 'linear':
            for i, e in enumerate(self.crc):
                if (e >> 24) & 0xFF == m.LAYOUT_INVALID:
                    return None
                if e >> 32 == crc:
                    return i
            return None
        lo, hi = 0, len(self.crc)          # first index whose CRC >= crc
        while lo < hi:
            mid = (lo + hi) // 2
            if self.crc[mid] >> 32 < crc:
                lo = mid + 1
            else:
                hi = mid
        if lo < len(self.crc) and self.crc[lo] >> 32 == crc and (self.crc[lo] >> 24) & 0xFF != m.LAYOUT_INVALID:
            return lo
        return None

    def lookup(self, crc, words, method='linear'):
        """(layout id, flags, size check ok, hit) as the loader will compute them.

        words = ceil(file length / 2), the length taken from the data table.
        """
        i = self.find(crc, method)
        if i is None:
            return m.LAYOUT_DEFAULT, m.FLAG_ESTIMATED, True, False
        e = self.crc[i]
        size256 = e & 0xFFFF
        ok = size256 == 0 or size256 == -(-words // 256)
        return (e >> 24) & 0xFF, (e >> 16) & 0xFF, ok, True

    def model(self, words, crc):
        lid, flags, ok, hit = self.lookup(crc, len(words))
        if not ok:     # size disagrees: treat as unknown
            lid, flags, hit = m.LAYOUT_DEFAULT, m.FLAG_ESTIMATED, False
        cart = m.model_for(words, lid, self.pages)
        if lid == m.LAYOUT_DEFAULT and not flags & m.FLAG_ECS:
            flags |= m.ecs_conflict(m.default_layout(len(words)))
        return cart, lid, flags, hit


def flag_text(f):
    return '+'.join(n for b, n in m.FLAG_NAMES.items() if f & b) or '-'


def page_text(v):
    d = m.decode_page_entry(v)
    if d['kind'] == m.KIND_NONE:
        return '-'
    s = '%s@%X' % (m.KIND_NAMES[d['kind']], d['offset'])
    if d['kind'] in (m.KIND_RAM8, m.KIND_RAM16) and d['cells'] < m.PAGE_WORDS:
        s += '/%d' % d['cells']
    if d['paged']:
        s += ' x%d pages' % d['npages']
    return s


def load(path):
    """The image as the core's loader receives it (bridge strobes + data table length)."""
    data = m.load_image_bytes(path)
    crc, words = m.load_through_loader(data)
    if crc != m.crc32(data) or words != m.bytes_to_words(data):
        sys.exit('%s: loader model disagrees with the file (CRC %08X, file %08X)' % (path, crc, m.crc32(data)))
    return data, words, crc


def load8(a, tab):
    """cartfmt's Loaded and MapCart for a.image (and a.cfg)."""
    import cartfmt
    data = m.load_image_bytes(a.image)
    cfg = open(a.cfg, 'rb').read() if getattr(a, 'cfg', None) else None
    ld = cartfmt.load(data, cfg, tab, tab.pages)
    return cartfmt, ld, cartfmt.MapCart(ld)


def cmd_fmt(a, tab):
    cf, ld, cart = load8(a, tab)
    print('image      %s%s' % (a.image, (' + ' + a.cfg) if a.cfg else ''))
    for k, v in ld.summary().items():
        print('%-10s %s' % (k, v))
    if ld.err:
        print('refused    %s' % cf.ERR_NAMES.get(ld.err, 'length / size checks'))
        return
    for n in ld.notes:
        print('note       %s' % n)
    for r in range(16):
        for y in range(16):
            row = [ld.table[(r << 8) | (y << 4) | b] for b in range(16)]
            if any(row):
                print('  $%X000 page %2d: %s' % (r, y, ' '.join(cf.ent_text(e) for e in row)))
    print('assembled  %d blocks' % len(ld.asm))
    print('mapped     %08X (mapped-space CRC)' % cart.mapped_space_crc())


def cmd_map(a, tab):
    if a.cfg or m.load_image_bytes(a.image)[:1] == b'\xa8':
        return cmd_fmt(a, tab)
    data, words, crc = load(a.image)
    cart, lid, flags, hit = tab.model(words, crc)
    print('image      %s' % a.image)
    print('size       %d bytes, %X words' % (len(data), len(words)))
    print('crc32      %08X (%s)' % (crc, 'in table' if hit else 'unknown: default map'))
    print('layout     %d' % lid)
    print('flags      %02X %s' % (flags, flag_text(flags)))
    for p in range(m.NPAGES):
        if cart.pt[p]:
            print('  %04X-%04X  %04X  %s' % (p * m.PAGE_WORDS, p * m.PAGE_WORDS + m.PAGE_WORDS - 1, cart.pt[p],
                                             page_text(cart.pt[p])))
    print('mapped     %08X (mapped-space CRC)' % cart.mapped_space_crc())


def cmd_read(a, tab):
    _, _, cart = load8(a, tab)
    addr = int(a.addr, 16)
    n = int(a.count, 0)
    for row in range(addr, addr + n, 8):
        vals = [cart.read(x) for x in range(row, min(row + 8, addr + n))]
        print('%04X: %s' % (row, ' '.join('----' if v is None else '%04X' % v for v in vals)))


def cmd_dump(a, tab):
    data, words, crc = load(a.image)
    cart, lid, flags, hit = tab.model(words, crc)
    cart.reset()
    out = struct.pack('>65536H', *cart.rom_space())
    for r in range(16):
        e = m.decode_page_entry(cart.pt[(r << 12) // m.PAGE_WORDS])
        if e['kind'] == m.KIND_ROM and e['paged']:
            for y in range(1, e['npages']):
                cart.sel[r] = y
                out += struct.pack('>4096H', *[0xFFFF if v is None else v
                                               for v in (cart.read((r << 12) + i) for i in range(0x1000))])
            cart.sel[r] = 0
    with open(a.out, 'wb') as f:
        f.write(out)
    print('%d bytes, crc32 %08X' % (len(out), m.crc32(out)))


def cmd_evidence(a, tab):
    data, words, crc = load(a.image)
    print('%08X %X words; J/JSR targets at $4000 and up:' % (crc, len(words)))
    for spec in a.spec:
        lay = m.Layout(m.segs_from_text(spec))
        r = m.jump_evidence(words, lay)
        print('  %-48s rom %4d  filler %4d  outside %4d  (of %d)' % (spec, r['rom'], r['fill'], r['unmapped'], r['n']))


def softlists(root):
    out = {}
    for lst in ('intv.xml', 'intvecs.xml'):
        for sw in m.read_softlist(os.path.join(root, 'data', 'mame-hash', lst)):
            out[sw['name']] = sw
    return out


def region_proof(data, sw):
    """Cut the image in the software's part order; every part CRC and the total must match."""
    off = 0
    for a in sw['areas']:
        if a['name'] == 'ram':
            continue
        for r in a['roms']:
            if m.crc32(data[off:off + r['size']]) != r['crc']:
                return False, off
            off += r['size']
    return off == len(data), off


def expected_space(words, lay):
    """The 64K-word space straight from the layout's segments (no page table), page 0."""
    sp = [None] * 0x10000
    for addr, n, off, page in lay.segs:
        if page:
            continue
        for i in range(n):
            if off + i < len(words):
                sp[addr + i] = words[off + i]
    return sp


def cmd_check(a, tab):
    sl = softlists(ROOT)
    rows = list(csv.DictReader(open(os.path.join(ROOT, 'data', 'cart_table.csv'))))
    bycrc = {int(r['crc32'], 16): r for r in rows}
    extra = {int(r['crc32'], 16): r for r in m.read_extra(os.path.join(ROOT, 'data', 'cart_extra.csv'))}
    files = sorted(f for f in os.listdir(a.dir) if f.lower().endswith(('.zip', '.int', '.bin')))
    imgs = {}
    for f in files:
        data = m.load_image_bytes(os.path.join(a.dir, f))
        imgs[f] = data
    crc_of = {}
    loaded = {}
    for f, d in imgs.items():
        crc_of[f], loaded[f] = m.load_through_loader(d)   # CRC as the core computes it
    words_by_name = {}
    for f, d in imgs.items():
        r = bycrc.get(crc_of[f])
        if r and r['source'].startswith('mame'):
            words_by_name[r['name']] = m.bytes_to_words(d)
    out = []
    fails = 0
    count = {}
    for f in files:
        data = imgs[f]
        crc = crc_of[f]
        words = loaded[f]
        cart, lid, flags, hit = tab.model(words, crc)
        row = bycrc.get(crc)
        status, proof = 'unknown', ''
        loader_bad = crc != m.crc32(data) or words != m.bytes_to_words(data)
        if tab.lookup(crc, len(words), 'binary') != tab.lookup(crc, len(words)):
            loader_bad = True
        if row and row['source'].startswith('mame'):
            ok, n = region_proof(data, sl[row['name']])
            status = 'proven' if ok else 'FAILED'
            proof = 'every MAME part CRC and the total size match' if ok else 'part mismatch at byte %X' % n
        elif row and row['source'] == 'extra':
            x = extra[crc]
            status = 'derived-' + x['status']
            ref = x['ref']
            if x['status'] == 'prefix':
                ok, n = region_proof(data[:sum(r['size'] for ar in sl[ref]['areas'] for r in ar['roms'])], sl[ref])
                proof = ('MAME %s parts match the first %X bytes; %X bytes beyond' % (ref, n, len(data) - n)) if ok \
                    else 'prefix proof FAILED'
                if not ok:
                    status = 'FAILED'
            elif x['status'] == 'sibling':
                sib = words_by_name.get(ref)
                if sib is None:
                    proof = 'sibling %s not in this directory' % ref
                else:
                    lay = m.Layout(m.segs_from_text(x['segments']))
                    segp = []
                    for addr, n, off, page in lay.segs:
                        eq = sum(1 for i in range(off, off + n) if i < len(sib) and i < len(words) and words[i] == sib[i])
                        segp.append(eq / n)
                    proof = 'equal to %s: %s' % (ref, ' '.join('%.1f%%' % (100 * p) for p in segp))
                    if len(sib) != len(words) or min(segp) < 0.99:
                        status = 'FAILED'
            else:
                proof = x['evidence']
        elif row:
            status = 'flags-only'
        # independent check of the page-table encoding against the layout's own segments
        if row and row['source'] != 'name_list':
            if row['source'] == 'extra':
                x = extra[crc]
                lay = m.Layout(m.segs_from_text(x['segments']), m.rams_from_text(x['ram']))
            else:
                lay = m.softlist_entry(sl[row['name']])['layout']
            exp = expected_space(words, lay)
            cart.reset()
            got = [cart.read(ad) if m.decode_page_entry(cart.pt[ad // m.PAGE_WORDS])['kind'] == m.KIND_ROM else None
                   for ad in range(0x10000)]
            if exp != got:
                status = 'FAILED'
                proof += '; page table disagrees with the layout'
        if loader_bad:
            status = 'FAILED'
            proof += '; loader CRC/words differ from the file, or the two table searches disagree'
        if row and row['source'] != 'name_list' and not hit:
            status = 'FAILED'
            proof += '; CRC is in the table but the lookup missed'
        if status == 'FAILED':
            fails += 1
        count[status] = count.get(status, 0) + 1
        mapped = cart.mapped_space_crc()
        lay_text = row['map'] if row else 'default map'
        missing = ''
        if status != 'proven':
            missing = {
                'derived-prefix': 'image has more data than MAME\'s regions; whether the extra is on the cart',
                'derived-sibling': 'no list entry for this exact image; map taken from a near-identical proven image',
                'derived-hsi': 'only MAME intv.hsi (name/extrainfo) knows this CRC; no region CRCs',
                'derived-jumps': 'no list entry and no sibling; map chosen by jump-target evidence only',
                'unknown': 'not in any table: default map',
                'flags-only': 'only jzIntv flags; default map',
            }.get(status, 'check failed')
        out.append(dict(file=f, crc32='%08X' % crc, words='%X' % len(words), status=status, layout=lid,
                        flags='%02X' % flags, flag_names=flag_text(flags), map=lay_text,
                        mapped_crc='%08X' % mapped, proof=proof, missing=missing))
    if a.out:
        with open(a.out, 'w', newline='') as fo:
            w = csv.DictWriter(fo, fieldnames=list(out[0].keys()))
            w.writeheader()
            w.writerows(out)
    for r in out:
        if r['status'] != 'proven' or a.verbose:
            print('%-8s %s %-44s %s | %s' % (r['crc32'], r['status'], r['file'][:44], r['map'], r['proof']))
    print('%d images: %s' % (len(out), ', '.join('%s %d' % kv for kv in sorted(count.items()))))
    if fails:
        sys.exit('%d FAILED' % fails)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', default=ROOT, help='repository root (tables are read from it)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('map'); p.add_argument('image'); p.add_argument('--cfg')
    p = sub.add_parser('read'); p.add_argument('image'); p.add_argument('addr'); p.add_argument('count', nargs='?', default='16')
    p.add_argument('--cfg')
    p = sub.add_parser('fmt'); p.add_argument('image'); p.add_argument('--cfg')
    p = sub.add_parser('dump'); p.add_argument('image'); p.add_argument('out')
    p = sub.add_parser('evidence'); p.add_argument('image'); p.add_argument('spec', nargs='+')
    p = sub.add_parser('check'); p.add_argument('dir'); p.add_argument('--out'); p.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args()
    tab = Tables(a.root)
    dict(map=cmd_map, read=cmd_read, fmt=cmd_fmt, dump=cmd_dump, evidence=cmd_evidence,
         check=cmd_check)[a.cmd](a, tab)


if __name__ == '__main__':
    main()
