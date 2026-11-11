#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""jzIntv as a black-box reference for LUIGI (1.0.7; docs/CARTFORMATS.md 8).

  python3 -I tools/refs/jz_luigi_compare.py --cases          the cases: name, image, writes
  python3 -I tools/refs/jz_luigi_compare.py LUIDIR DUMPDIR   compare

jzIntv 20200712 does not load a .luigi itself. tools/refs/jz_luigi_ref.sh makes LUIDIR/<image>.luigi
from the step-8 images with jzIntv's bin2luigi / rom2luigi, turns each back into a BIN + CFG with
luigi2bin, and dumps jzIntv's space for every case of tools/refs/jz_cart_compare.py (the same
writes) into DUMPDIR/<case>. All three tools are run as programs (black boxes; their code is not
read). The model (tools/mapper/cartfmt.py, which the RTL equals: tb_loader) loads the .luigi,
makes the case's writes, and must read what jzIntv reads at every address outside the console's
own devices. Prints counts only. Last line "JZ_LUIGI pass" or "JZ_LUIGI FAIL".
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [HERE, os.path.join(ROOT, 'tools'), os.path.join(ROOT, 'tools', 'mapper')]
import cartfmt as cf          # noqa: E402
import intv_mapper            # noqa: E402
import jz_cart_compare as jc  # noqa: E402

# the cases of jz_cart_compare whose differences on purpose belong to the CFG format (a LUIGI
# maps whole paragraphs and has no PAGE / non-PAGE line overlap): checked without them
CASES = [(c, img, w) for c, img, w, keep in jc.CASES if not keep]
# where we differ from jzIntv-on-luigi2bin's-output on purpose: (case, lo, hi, reason); each must differ
NOREAD = ('a bankswitched paragraph without READ (permissions $8): Locutus answers no reads there (LUIGI '
          'spec); luigi2bin\'s [bankswitch] line makes it readable in jzIntv; on the original .rom jzIntv '
          'answers nothing there either, as we do (JZ_REF)')
BANKWIN = ('jzIntv answers 0 through a bank window moved onto other Intellicart memory in luigi2bin\'s BIN + '
           'CFG; on the original .rom it reads that memory, as we do (JZ_REF)')
KEEP = {'rombank_b': [(0x6000, 0x6FFF, BANKWIN)],
        'romfine_nonul_0': [(0xC000, 0xC7FF, NOREAD)],
        'romfine_nonul_b': [(0xC000, 0xC7FF, NOREAD), (0xD800, 0xDFFF, BANKWIN)]}


def main(argv):
    if argv[:1] == ['--cases']:
        for case, img, w in CASES:
            print(case, img, w or '-')
        return 0
    if len(argv) != 2:
        sys.exit(__doc__)
    luidir, dumps = argv
    tab = intv_mapper.Tables(ROOT)
    bad = 0
    for case, img, writes in CASES:
        lui = os.path.join(luidir, img + '.luigi')
        dump = os.path.join(dumps, case, 'dump.mem')
        if not os.path.exists(lui) or not os.path.exists(dump):
            print('%-18s no .luigi or no jzIntv dump' % case)
            bad += 1
            continue
        jz = struct.unpack('>65536H', open(dump, 'rb').read())
        ld = cf.load(open(lui, 'rb').read(), None, tab, tab.pages)
        cart = cf.MapCart(ld)
        for w in filter(None, writes.split(',')):
            a, v = w.split(':')
            cart.write(int(a, 16), int(v, 16))
        n = diff = 0
        first = None
        keep = KEEP.get(case, [])
        kept = [0] * len(keep)
        for a in range(0x10000):
            if jc.system(a):
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
        print('%-18s %5d words compared, %d differ%s%s%s' % (
            case, n, diff, ''.join('; $%04X-$%04X differ in %d (on purpose: %s)' % (keep[i][0], keep[i][1], c, keep[i][2])
                                   for i, c in enumerate(kept) if c),
            '' if ld.err == 0 else ' (refused: $%02X)' % ld.err, '' if not first else ' (first ' + first + ')'))
        stale = [i for i, c in enumerate(kept) if c == 0]
        for i in stale:
            print('  stale note: $%04X-$%04X does not differ' % keep[i][:2])
        bad += diff > 0 or n == 0 or ld.err != 0 or bool(stale)
    print('JZ_LUIGI %s' % ('pass' if not bad else 'FAIL'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
