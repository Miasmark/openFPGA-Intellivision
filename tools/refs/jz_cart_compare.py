#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""jzIntv as a black-box reference for BIN + CFG and Intellicart .rom (build step 8;
docs/CARTFORMATS.md 7).

  python3 -I tools/refs/jz_cart_compare.py --cases            the cases: name, CFG?, writes
  python3 -I tools/refs/jz_cart_compare.py IMGDIR DUMPDIR     compare

IMGDIR holds the step-8 images (sim/testroms/step8/build_images.py --out); DUMPDIR/<case>
holds tools/refs/jzintv_cart_dump.sh's dump of jzIntv's space after the case's writes. For
each case the model (tools/mapper/cartfmt.py, which the RTL equals: tb_loader) makes the same
writes after the load and must read what jzIntv reads at every address outside the console's
own devices, except in the ranges listed with the case: the differences we keep on purpose
(docs/CARTFORMATS.md 2.2, 3), each with its reason; each of those must differ (else the note
is stale). Prints counts only (the dumps hold the user's EXEC words elsewhere). Last line
"JZ_REF pass" or "JZ_REF FAIL".
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'mapper'))
import cartfmt as cf  # noqa: E402
import intv_mapper    # noqa: E402

# the console's own devices and their aliases (not the cartridge's): STIC, PSG, RAM, EXEC,
# GROM / GRAM and its aliases, the STIC aliases, the Intellicart bank registers
SYSTEM = [(0x0000, 0x007F), (0x0100, 0x035F), (0x1000, 0x1FFF), (0x3000, 0x3FFF), (0x4000, 0x403F),
          (0x7800, 0x7FFF), (0x8000, 0x803F), (0xB800, 0xBFFF), (0xC000, 0xC03F), (0xF800, 0xFFFF)]

# (case, image, writes "AAAA:VVVV,...", [(lo, hi, reason)] where we differ on purpose)
AND = 'jzIntv ANDs a PAGE line with a line without PAGE on the same words; we give the page\'s'
RAMPG = 'a PAGE line\'s words in a cart RAM block: the RAM answers on every page (only its trim)'
CASES = [
    ('cfgmap_0', 'cfgmap', '', []),
    ('cfgmap_1', 'cfgmap', '2FFF:2A51,EFFF:EA51,FFFF:FA51', []),
    ('cfgmap_2', 'cfgmap', '2FFF:2A53,FFFF:FA52', []),
    ('cfgmap_f', 'cfgmap', 'FFFF:FA5F,8001:1234,9001:5678', []),
    ('zoo5_0', 'zoo5', '', []),
    ('zoo6_0', 'zoo6', '', []),
    ('zoo6_1', 'zoo6', 'DFFF:DA51,CFFF:CA53', []),
    ('zoo6_2', 'zoo6', 'DFFF:DA52,CFFF:CA51', []),
    ('zoo7_0', 'zoo7', 'A800:1111,A901:2222', []),
    ('zoo7_1', 'zoo7', 'AFFF:AA51,BFFF:BA52', [(0xA908, 0xA9FF, RAMPG), (0xB000, 0xB03F, AND)]),
    ('zoo8_0', 'zoo8', '8041:1234', []),
    ('rombank_0', 'rombank', '', []),
    ('rombank_b', 'rombank', '0046:0010,0056:0030,0047:0080', []),
    ('romfine_nonul_0', 'romfine_nonul', '', []),
    ('romfine_nonul_b', 'romfine_nonul', '005D:00D0,004C:0098', []),
    ('cart8bank_0', 'cart8bank', '', []),
    ('cart8pages_0', 'cart8pages', '', []),
    ('cart8pages_f', 'cart8pages', 'FFFF:FA5F', []),
]


def image_files(imgdir, name):
    rom = os.path.join(imgdir, name + '.rom')
    if os.path.exists(rom):
        return rom, None
    cfg = os.path.join(imgdir, name + '.cfg')
    return os.path.join(imgdir, name + '.bin'), cfg if os.path.exists(cfg) else None


def system(a):
    return any(lo <= a <= hi for lo, hi in SYSTEM)


def main(argv):
    if argv[:1] == ['--cases']:
        for case, img, w, _ in CASES:
            print(case, img, w or '-')
        return 0
    if len(argv) != 2:
        sys.exit(__doc__)
    imgdir, dumps = argv
    tab = intv_mapper.Tables(ROOT)
    bad = 0
    for case, img, writes, keep in CASES:
        path, cfgp = image_files(imgdir, img)
        dump = os.path.join(dumps, case, 'dump.mem')
        if not os.path.exists(dump):
            print('%-18s no jzIntv dump' % case)
            bad += 1
            continue
        jz = struct.unpack('>65536H', open(dump, 'rb').read())
        ld = cf.load(open(path, 'rb').read(), open(cfgp, 'rb').read() if cfgp else None, tab, tab.pages)
        cart = cf.MapCart(ld)
        for w in filter(None, writes.split(',')):
            a, v = w.split(':')
            cart.write(int(a, 16), int(v, 16))
        n = diff = 0
        kept = [0] * len(keep)
        first = None
        for a in range(0x10000):
            if system(a):
                continue
            v = cart.read(a)
            v = 0xFFFF if v is None else v
            k = [i for i, (lo, hi, _) in enumerate(keep) if lo <= a <= hi]
            if k:
                kept[k[0]] += v != jz[a]
                continue
            n += 1
            if v != jz[a]:
                diff += 1
                if first is None:
                    first = '$%04X: jzIntv $%04X, ours $%04X' % (a, jz[a], v)
        stale = [i for i, c in enumerate(kept) if c == 0]
        print('%-18s %5d words compared, %d differ%s%s' % (
            case, n, diff, ''.join('; $%04X-$%04X differ in %d (on purpose: %s)' % (keep[i][0], keep[i][1], c,
                                                                                   keep[i][2])
                                   for i, c in enumerate(kept) if c),
            '' if not first else ' (first ' + first + ')'))
        for i in stale:
            print('  stale note: $%04X-$%04X does not differ' % keep[i][:2])
        bad += diff > 0 or n == 0 or bool(stale) or ld.err != 0
    print('JZ_REF %s' % ('pass' if not bad else 'FAIL'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
