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

# The CRC table is sorted, has no duplicate CRC and every layout id exists
crcs = [e >> 32 for e in tab.crc if (e >> 24) & 0xFF]
check(crcs == sorted(set(crcs)), 'CRC table sorted and unique')
check(all(((e >> 24) & 0xFF) < len(tab.pages) for e in tab.crc), 'layout ids in range')
check(tab.lookup(0x12345678, 0x1000)[3] is False, 'unknown CRC misses')

# The checked-in tables match what the generator makes from data/
r = subprocess.run([sys.executable, '-I', os.path.join(ROOT, 'tools', 'gen_crc_table.py'), '--check'],
                   capture_output=True, text=True)
check(r.returncode == 0, 'tables up to date (%s)' % r.stdout.strip().splitlines()[-1:])

print('selftest: %s' % ('pass' if not fails else '%d FAILED' % fails))
sys.exit(1 if fails else 0)
