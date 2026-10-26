#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""MAME as a reference for the Intellicart .rom format (build step 8; docs/CARTFORMATS.md 7).

  python3 -I tools/refs/cart_ref_compare.py IMAGE.rom MAME_DUMP_DIR [...]

For each image (pairs of arguments), MAME_DUMP_DIR/space.txt is tools/refs/mame_cart_dump.sh's
dump of MAME's program space with that image. MAME loads a .rom's segments at their
Intellicart addresses and ignores the enable tables (MAME slot.cpp:225-290), so the check
is: at every address where our map (tools/mapper/cartfmt.py, the model the RTL equals)
answers through a plain readable window onto a block a segment wrote, MAME's CPU reads the
same word (the low byte in a narrow window: MAME has no N bit). Prints counts only (the dumps hold words read with the user's EXEC elsewhere).
Last line "CART_REF pass" or "CART_REF FAIL".
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'mapper'))
import cartfmt as cf  # noqa: E402
import intv_mapper    # noqa: E402


def main(argv):
    if len(argv) < 2 or len(argv) % 2:
        sys.exit(__doc__)
    tab = intv_mapper.Tables(ROOT)
    bad = 0
    for img, d in zip(argv[0::2], argv[1::2]):
        data = open(img, 'rb').read()
        ld = cf.load(data, None, tab, tab.pages)
        if ld.fmt != cf.FMT_ROM:
            print('%s: not a .rom the loader takes (%s)' % (os.path.basename(img), ld.summary()))
            bad += 1
            continue
        cover = cf.parse_rom(data).cover
        mame = {}
        for ln in open(os.path.join(d, 'space.txt')):
            a, v = ln.split()
            mame[int(a, 16)] = int(v, 16)
        cart = cf.MapCart(ld)
        n = diff = 0
        first = None
        for a in range(0x10000):
            e = ld.table[((a >> 12) << 8) | ((a >> 8) & 15)]
            if not e & cf.E_R or e & (cf.E_B | cf.E_W) or (a >> 8) not in cover:
                continue
            v = cart.read(a)
            if v is None:
                continue
            n += 1
            m = mame.get(a, -1)
            if e & cf.E_N:              # a narrow window: MAME knows no N bit, the low byte only
                m = m & 0xFF if m >= 0 else m
            if m != v:
                diff += 1
                if first is None:
                    first = '$%04X: MAME $%04X, ours $%04X' % (a, mame.get(a, -1), v)
        print('%-16s %5d words compared, %d differ%s' % (os.path.basename(img), n, diff,
                                                         '' if not first else ' (first ' + first + ')'))
        bad += diff > 0 or n == 0
    print('CART_REF %s' % ('pass' if not bad else 'FAIL'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
