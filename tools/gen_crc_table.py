#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Build the cartridge CRC map table and the layout page tables (docs/DESIGN.md 5.2).

Sources, in order of trust:
  1. MAME hash/intv.xml and intvecs.xml (CC0-1.0, copied under data/mame-hash/): each
     software's dataareas give the load addresses; the image CRC32 (what the core's loader
     computes over the file) is the parts' CRCs combined, so no image is needed.
  2. data/cart_extra.csv: our own entries for images MAME's lists do not give, each with
     the evidence that places it (marked 'estimated' in the table).
  3. data/jzintv_name_flags.csv (from jzIntv name_list.c, public domain): ECS and
     Intellivoice flags only. A CRC found only here gets the default layout.

Writes (all generated; do not edit by hand):
  data/cart_table.csv                    one row per CRC, readable
  data/layouts.json                      layout id -> segments, RAM, page table
  src/fpga/core/tables/cart_crc.mif|hex  CRC table for the RTL (256 x 64)
  src/fpga/core/tables/cart_layouts.mif|hex  page tables (layouts x 32 x 16)

Usage: python3 -I tools/gen_crc_table.py [--root REPO] [--check]
  --check  regenerate in memory and fail if any output file differs (for CI/hygiene).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mapper'))
import intvcart as m  # noqa: E402

CRC_DEPTH = 256


def build(root):
    entries = {}     # crc -> dict(layout, flags, words, source, name)
    log = []
    for lst in ('intv.xml', 'intvecs.xml'):
        for sw in m.read_softlist(os.path.join(root, 'data', 'mame-hash', lst)):
            e = m.softlist_entry(sw)
            if e is None:
                continue
            if e['problems']:
                log.append('skipped MAME %s (%s): %s' % (sw['name'], sw['supported'], '; '.join(e['problems'])))
                continue
            if e['crc'] in entries:
                log.append('MAME %s has the same CRC as %s; kept the first' % (sw['name'], entries[e['crc']]['name']))
                continue
            entries[e['crc']] = dict(layout=e['layout'], flags=e['flags'], words=e['bytes'] // 2,
                                     source='mame:' + lst.split('.')[0], name=sw['name'],
                                     status='mame' if sw['supported'] == 'yes' else 'mame-unsupported:' + sw['supported'])
    for r in m.read_extra(os.path.join(root, 'data', 'cart_extra.csv')):
        crc = int(r['crc32'], 16)
        if crc in entries:
            sys.exit('cart_extra.csv: %08X is already in MAME\'s lists' % crc)
        lay = m.Layout(m.segs_from_text(r['segments']), m.rams_from_text(r['ram']))
        flags = m.FLAG_ESTIMATED
        flags |= m.FLAG_ECS if r['ecs'] == '1' else 0
        flags |= m.FLAG_VOICE if r['voice'] == '1' else 0
        entries[crc] = dict(layout=lay, flags=flags, words=(int(r['bytes']) + 1) // 2, source='extra',
                            name=r['ref'] or r['title'], status=r['status'])
    names = m.read_name_flags(os.path.join(root, 'data', 'jzintv_name_flags.csv'))
    for crc, (ecs, voice) in sorted(names.items()):
        add = (m.FLAG_ECS if ecs else 0) | (m.FLAG_VOICE if voice else 0)
        if crc in entries:
            if add & ~entries[crc]['flags']:
                log.append('%08X %s: name_list adds %s' % (crc, entries[crc]['name'],
                           '+'.join(n for b, n in m.FLAG_NAMES.items() if add & ~entries[crc]['flags'] & b)))
            entries[crc]['flags'] |= add
        else:
            entries[crc] = dict(layout=None, flags=add | m.FLAG_ESTIMATED, words=0, source='name_list',
                                name='', status='flags-only')
    if len(entries) > CRC_DEPTH:
        sys.exit('%d entries do not fit the %d-entry table' % (len(entries), CRC_DEPTH))

    # Layout ids: 0 invalid, 1 default, then each distinct layout in a stable order.
    keys = sorted({e['layout'].key() for e in entries.values() if e['layout']},
                  key=lambda k: (k[0][0][0], len(k[0]), k))
    lay_by_key = {}
    for e in entries.values():
        if e['layout']:
            lay_by_key.setdefault(e['layout'].key(), e['layout'])
    ids = {k: i + 2 for i, k in enumerate(keys)}
    if len(ids) + 2 > 256:
        sys.exit('too many layouts')
    tables = {m.LAYOUT_INVALID: [0] * m.NPAGES, m.LAYOUT_DEFAULT: m.default_page_table()}
    for k, i in ids.items():
        tables[i] = lay_by_key[k].page_table()

    rows = []
    for crc in sorted(entries):
        e = entries[crc]
        if e['layout']:
            lid = ids[e['layout'].key()]
            lay = e['layout']
        else:
            lid = m.LAYOUT_DEFAULT
            lay = None
        flags = m.layout_flags(lay, e['flags']) if lay else e['flags']
        size256 = -(-e['words'] // 256)
        rows.append(dict(crc=crc, layout=lid, flags=flags, size256=size256, e=e,
                         text=lay.text() if lay else 'default map (cut at image length)'))
    return rows, tables, ids, lay_by_key, log


def crc_word(r):
    return (r['crc'] << 32) | (r['layout'] << 24) | (r['flags'] << 16) | (r['size256'] & 0xFFFF)


def mif(width, depth, words, comment):
    out = ['-- %s' % c for c in comment]
    out += ['DEPTH = %d;' % depth, 'WIDTH = %d;' % width, 'ADDRESS_RADIX = HEX;', 'DATA_RADIX = HEX;',
            'CONTENT', 'BEGIN']
    digits = (width + 3) // 4
    adig = max(2, (depth - 1).bit_length() // 4 + 1)
    for a in range(depth):
        out.append('%0*X : %0*X;' % (adig, a, digits, words[a] if a < len(words) else 0))
    out.append('END;')
    return '\n'.join(out) + '\n'


def hexfile(width, depth, words, comment):
    out = ['// %s' % c for c in comment]
    digits = (width + 3) // 4
    for a in range(depth):
        out.append('%0*X' % (digits, words[a] if a < len(words) else 0))
    return '\n'.join(out) + '\n'


def outputs(root):
    rows, tables, ids, lay_by_key, log = build(root)
    files = {}
    head = ['Generated by tools/gen_crc_table.py from data/ (MAME CC0 lists, our cart_extra.csv,',
            'jzIntv name_list.c flags, public domain). Do not edit; see tools/mapper/README.md.']
    crcs = [crc_word(r) for r in rows]
    files['src/fpga/core/tables/cart_crc.mif'] = mif(64, CRC_DEPTH, crcs, head + [
        'Entry: [63:32] CRC32 of the image file, [31:24] layout id, [23:16] flags,',
        '[15:0] image size in 256-word units (0 = not checked). Sorted by CRC; %d entries,' % len(rows),
        'then zeros (layout 0 = no entry).'])
    files['src/fpga/core/tables/cart_crc.hex'] = hexfile(64, CRC_DEPTH, crcs, head + ['%d entries, sorted by CRC' % len(rows)])
    nlay = max(tables) + 1
    ldepth = 1
    while ldepth < nlay * m.NPAGES:
        ldepth *= 2
    lw = []
    for i in range(nlay):
        lw += tables[i]
    files['src/fpga/core/tables/cart_layouts.mif'] = mif(16, ldepth, lw, head + [
        'Address = layout id * 32 + page ($xx00 / $800). Entry: [15:14] kind (0 none, 1 ROM,',
        '2 RAM16, 3 RAM8), [13] ECS-style paged range, [12:9] pages - 1, [8:0] ROM: image',
        'offset in 2K-word units; RAM: [8:6] size code (cells = 2048 >> code), [5:0] RAM offset.',
        '%d layouts (0 = none, 1 = default map).' % nlay])
    files['src/fpga/core/tables/cart_layouts.hex'] = hexfile(16, ldepth, lw, head + ['%d layouts x 32 pages' % nlay])

    lj = {}
    for i in range(nlay):
        if i == m.LAYOUT_INVALID:
            d = dict(text='no layout')
        elif i == m.LAYOUT_DEFAULT:
            d = dict(text='default map: pages filled in this order, cut at the image length',
                     fill=['%04X' % a for a in m.DEFAULT_FILL])
        else:
            lay = lay_by_key[[k for k, v in ids.items() if v == i][0]]
            d = dict(text=lay.text(),
                     segments=[dict(addr='%04X' % a, words='%X' % w, file_offset='%X' % o, page=p)
                               for a, w, o, p in lay.segs],
                     ram=[dict(addr='%04X' % a, cells='%X' % c, width=w) for a, c, w in lay.rams])
        d['pages'] = ['%04X' % v for v in tables[i]]
        d['titles'] = sum(1 for r in rows if r['layout'] == i)
        lj[str(i)] = d
    files['data/layouts.json'] = json.dumps(dict(
        comment=' '.join(head), page_words='800', layouts=lj), indent=1, sort_keys=False) + '\n'

    lines = ['crc32,layout,flags,flag_names,size_words,source,status,name,map']
    for r in rows:
        e = r['e']
        fn = '+'.join(n for b, n in m.FLAG_NAMES.items() if r['flags'] & b)
        lines.append('%08X,%d,%02X,%s,%X,%s,%s,%s,%s' % (r['crc'], r['layout'], r['flags'], fn, e['words'],
                                                       e['source'], e['status'], e['name'], r['text']))
    files['data/cart_table.csv'] = '\n'.join(lines) + '\n'
    return files, rows, nlay, log


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    files, rows, nlay, log = outputs(a.root)
    for l in log:
        print('note:', l)
    bad = 0
    for rel, text in files.items():
        p = os.path.join(a.root, rel)
        if a.check:
            old = open(p).read() if os.path.exists(p) else None
            if old != text:
                print('differs:', rel)
                bad = 1
        else:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w') as f:
                f.write(text)
    src = {}
    for r in rows:
        src[r['e']['source']] = src.get(r['e']['source'], 0) + 1
    print('%d CRC entries (%s), %d layouts incl. none and default' %
          (len(rows), ', '.join('%s %d' % kv for kv in sorted(src.items())), nlay))
    if a.check:
        print('tables up to date' if not bad else 'tables out of date: run tools/gen_crc_table.py')
        sys.exit(bad)


if __name__ == '__main__':
    main()
