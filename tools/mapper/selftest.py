#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Self-test of the mapper model and the generated tables. Needs no game data.

Usage: python3 -I tools/mapper/selftest.py
"""
import os
import random
import subprocess
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import intvcart as m  # noqa: E402
import intv_mapper as im  # noqa: E402

rng = random.Random(1600)
fails = 0


def check(cond, what):
    global fails
    if not cond:
        fails += 1
        print('FAIL', what)


# CRC32 combine agrees with zlib over the whole concatenation
for n1, n2 in [(0, 7), (7, 0), (1, 1), (0x2000, 0x4000), (5, 0x3002)]:
    a = bytes(rng.randrange(256) for _ in range(n1))
    b = bytes(rng.randrange(256) for _ in range(n2))
    check(m.crc32_combine(zlib.crc32(a), zlib.crc32(b), n2) == zlib.crc32(a + b), 'crc32_combine %d+%d' % (n1, n2))

# Page entries decode to what was encoded
for kind, off, paged, n, code in [(m.KIND_ROM, 0, False, 1, 0), (m.KIND_ROM, 511, True, 16, 0),
                                  (m.KIND_RAM8, 3, False, 1, 1), (m.KIND_RAM16, 63, False, 1, 0)]:
    d = m.decode_page_entry(m.page_entry(kind, off, paged, n, code))
    check(d['kind'] == kind and d['offset'] == off and d['paged'] == paged and d['npages'] == n,
          'page entry %s' % ((kind, off, paged, n, code),))

words = [rng.randrange(0x10000) for _ in range(0x3000)]

# A WSMLB-like layout: $5000-$6FFF, $D000-$DFFF, then two pages of $F000
lay = m.Layout([(0x5000, 0x1000, 0, 0), (0xF000, 0x1000, 0x1000, 0), (0xF000, 0x1000, 0x2000, 1)])
cart = m.CartModel(words, lay.page_table())
check(cart.read(0x5000) == words[0] and cart.read(0x5FFF) == words[0xFFF], 'plain ROM')
check(cart.read(0x6000) is None and cart.read(0x4FFF) is None, 'unmapped reads')
check(cart.read(0xF123) == words[0x1123], 'page 0 at reset')
cart.write(0xFFFF, 0xFA51)
check(cart.read(0xF123) == words[0x2123], 'page 1 after $FA51 to $FFFF')
cart.write(0xFFFF, 0xFA52)
check(cart.read(0xF123) is None, 'page 2 has no ROM')
cart.write(0xEFFF, 0xFA50)            # wrong range nibble: ignored
check(cart.sel[15] == 2, 'write to $EFFF does not select $F000 pages')
cart.write(0xFFFF, 0xFA50)
check(cart.read(0xF123) == words[0x1123], 'back to page 0')

# 8-bit cart RAM with 1K cells at $D000 (mirrored), upper byte reads 0
lay = m.Layout([(0x5000, 0x1000, 0, 0)], [(0xD000, 0x400, 8)])
cart = m.CartModel(words, lay.page_table())
cart.write(0xD010, 0x12AB)
check(cart.read(0xD010) == 0xAB and cart.read(0xD410) == 0xAB, 'RAM8 value, upper byte, mirror')
check(cart.read(0xD800) is None, 'RAM window ends at $D7FF')

# Default map: Cart.mac 16K order, cut at the image length
tab = im.Tables(ROOT)
for n, expect in [(0x1000, '5000-5FFF'), (0x1800, '5000-67FF'), (0x3000, '5000-6FFF D000-DFFF'),
                  (0x4000, '5000-6FFF D000-DFFF F000-FFFF')]:
    check(m.default_layout(n).text() == expect, 'default layout %X words' % n)
    img = words[:n] if n <= len(words) else words + [0] * (n - len(words))
    c = m.model_for(img, m.LAYOUT_DEFAULT, tab.pages)
    ok = all(c.read(a) == (img[o + i] if o + i < n else None)
             for a0, w, o, p in m.default_layout(n).segs for i, a in enumerate(range(a0, a0 + w)))
    check(ok, 'default page table %X words' % n)

# The CRC table is sorted end to end (padding CRC FFFFFFFF, layout 0), has no duplicate
# CRC and every layout id exists
crcs = [e >> 32 for e in tab.crc if (e >> 24) & 0xFF]
used = len(crcs)
check(crcs == sorted(set(crcs)) and 0xFFFFFFFF not in crcs, 'CRC table entries sorted and unique')
check(len(tab.crc) == 256 and all(e == m.CRC_PAD_ENTRY for e in tab.crc[used:]), 'padding is CRC FFFFFFFF, layout 0')
check([e >> 32 for e in tab.crc] == sorted(e >> 32 for e in tab.crc), 'whole table sorted (binary search valid)')
check(all(((e >> 24) & 0xFF) < len(tab.pages) for e in tab.crc), 'layout ids in range')
check(tab.lookup(0x12345678, 0x1000)[3] is False, 'unknown CRC misses')
# Linear scan and binary search agree on every entry, on misses between entries and on FFFFFFFF
probes = crcs + [c + 1 for c in crcs] + [0, 0xFFFFFFFF] + [rng.randrange(1 << 32) for _ in range(500)]
check(all(tab.find(c) == tab.find(c, 'binary') for c in probes), 'linear and binary lookup agree')
check(all(tab.find(c, 'binary') == i for i, c in enumerate(crcs)), 'binary search finds every entry')
check(tab.find(0xFFFFFFFF, 'binary') is None and tab.find(0xFFFFFFFF) is None, 'padding is never a hit')
# Negative: the old zero padding breaks the binary search (why the padding is FFFFFFFF)
zt = im.Tables.__new__(im.Tables)
zt.crc, zt.pages = tab.crc[:used] + [0] * (256 - used), tab.pages
check(any(zt.find(c, 'binary') is None for c in crcs), 'zero padding would break binary search (negative)')

# The loader: CRC over exactly the data-table length, words = ceil(len/2), whatever the
# bridge pads the last 32-bit word with. Lengths 4n, 4n+1, 4n+2 (MTE201 alt, Triple
# Challenge), 4n+3.
for n in (0x4000, 0x4001, 0x4002, 0xB002, 0x4003):
    data = bytes(rng.randrange(256) for _ in range(n))
    strobes = m.bridge_strobes(data, 0x00)
    check(len(strobes) % 4 == 0 and len(strobes) >= n, 'bridge strobes whole words (%d bytes)' % n)
    table = m.datatable({0x100: n, 0x101: 0, 0x102: 0x2000})
    check(m.datatable_size(table) == n, 'data table size of slot 0x100')
    for pad in (0x00, 0xFF, 0xA5):
        crc, w = m.loader_load(m.bridge_strobes(data, pad), m.datatable_size(table))
        check(crc == zlib.crc32(data) and w == m.bytes_to_words(data) and len(w) == -(-n // 2),
              'loader CRC/words over the file length only (%d bytes, pad %02X)' % (n, pad))
    if n % 4:
        # Negative: a CRC over every strobe (counting the pad) is not the file's CRC
        check(zlib.crc32(strobes) != zlib.crc32(data), 'strobe-count CRC differs for %d bytes (negative)' % n)
    # Lookup with an entry for this image, as the generator writes it (size = ceil(len/2) words)
    t2 = im.Tables.__new__(im.Tables)
    ent = (zlib.crc32(data) << 32) | (5 << 24) | (-(-(-(-n // 2)) // 256))
    t2.crc, t2.pages = [ent] + [m.CRC_PAD_ENTRY] * 255, tab.pages
    crc, w = m.load_through_loader(data)
    for meth in ('linear', 'binary'):
        lid, fl, ok, hit = t2.lookup(crc, len(w), meth)
        check(hit and ok and lid == 5, 'synthetic %d-byte image hits its entry (%s)' % (n, meth))
        if n % 4:
            check(not t2.lookup(zlib.crc32(strobes), len(strobes) // 2, meth)[3],
                  'strobe-count CRC misses the entry (%d bytes, negative, %s)' % (n, meth))

# ECS conflict classes: hard ($7000, ECS RAM) and paged ($2000, $E000)
for segs, rams, expect in [([(0x5000, 0x2000, 0, 0)], [], 0),
                           ([(0x5000, 0x3000, 0, 0)], [], m.FLAG_ECS_OFF),                 # $5000-$7FFF
                           ([(0x4000, 0x800, 0, 0)], [], m.FLAG_ECS_OFF),                  # ECS RAM range
                           ([(0x5000, 0x1000, 0, 0)], [(0x4000, 0x400, 8)], m.FLAG_ECS_OFF),
                           ([(0x5000, 0x2000, 0, 0), (0xD000, 0x2000, 0x2000, 0)], [], m.FLAG_ECS_RISK),
                           ([(0x2000, 0x1000, 0, 0)], [], m.FLAG_ECS_RISK),
                           ([(0x5000, 0x1000, 0, 0)], [(0xE000, 0x800, 16)], m.FLAG_ECS_RISK),
                           ([(0x6000, 0x2000, 0, 0), (0xE000, 0x1000, 0x2000, 0)], [], m.FLAG_ECS_OFF | m.FLAG_ECS_RISK),
                           ([(0x4800, 0x800, 0, 0), (0x8000, 0x1000, 0x800, 0)], [], 0)]:
    lay = m.Layout(segs, rams)
    check(m.ecs_conflict(lay) == expect, 'ECS class %s' % lay.text())
    check(m.layout_flags(lay, m.FLAG_ECS) & (m.FLAG_ECS_OFF | m.FLAG_ECS_RISK) == 0, 'ECS title: no conflict flag')

# The checked-in tables match what the generator makes from data/
r = subprocess.run([sys.executable, '-I', os.path.join(ROOT, 'tools', 'gen_crc_table.py'), '--check'],
                   capture_output=True, text=True)
check(r.returncode == 0, 'tables up to date (%s)' % r.stdout.strip().splitlines()[-1:])

print('selftest: %s' % ('pass' if not fails else '%d FAILED' % fails))
sys.exit(1 if fails else 0)
