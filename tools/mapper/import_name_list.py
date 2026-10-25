#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Extract the ECS and Intellivoice flags from jzIntv's src/name/name_list.c.

name_list.c is placed in the public domain by its author, Joseph Zbiciak (its header
and footer say so); the rest of jzIntv is GPL and is not used. Its table rows are
{ crc32, year, ecs, voice, name, short_name }. We keep only the CRC32 and the two flags,
and only rows with a flag set: that is all the CRC table uses (docs/DESIGN.md 5.2).

Usage: python3 -I tools/mapper/import_name_list.py <name_list.c> data/jzintv_name_flags.csv
"""
import re
import sys


def main(src, dst):
    text = open(src, encoding='latin-1').read()
    if 'public domain' not in text[:600] or 'public domain' not in text[-400:]:
        sys.exit('%s: public-domain header or footer not found; not importing' % src)
    rows = {}
    for m in re.finditer(r'\{\s*0x([0-9A-Fa-f]{8}),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),', text):
        crc, ecs, voice = int(m.group(1), 16), int(m.group(3)), int(m.group(4))
        if ecs not in (0, 1) or voice not in (0, 1):
            sys.exit('unexpected flag value in row %08X' % crc)
        if ecs or voice:
            pe, pv = rows.get(crc, (0, 0))
            rows[crc] = (pe | ecs, pv | voice)
    with open(dst, 'w', newline='') as f:
        f.write('crc32,ecs,voice\n')
        for crc in sorted(rows):
            f.write('%08X,%d,%d\n' % (crc, rows[crc][0], rows[crc][1]))
    print('%d rows with a flag written to %s' % (len(rows), dst))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
