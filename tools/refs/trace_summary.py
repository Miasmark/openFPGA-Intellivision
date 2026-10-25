#!/usr/bin/env python3
"""trace_summary.py TRACE.LOG [...]

Check and summarise a trace written by tools/refs/mame_trace.sh. Prints
counts only (no game bytes), so the output may be quoted in notes:
instructions and cycles per frame, interrupts taken, the PC ranges that
ran, and bus reads and writes per address region. Exit 1 if the trace is
malformed (a line that does not parse, or no instruction lines).

Address regions follow DESIGN.md section 2.6 (memory map).
"""
import hashlib
import re
import sys
from collections import Counter

INSN = re.compile(r'^c=(\d+) f=(\d+) y=(\d+) R=((?:[0-9A-F]{4} ){8})F=([0-9A-F]{2}) ([0-9A-F]{4}): (.*)$')
ACC = re.compile(r'^  ([RW]) ([0-9A-F]{4}) ([0-9A-F]{4})$')
IRQ = re.compile(r'^\s*\(interrupted at ([0-9A-F]+), IRQ (\d+)\)$')

REGIONS = [  # (first, last, name)
    (0x0000, 0x003F, 'STIC regs'), (0x0040, 0x007F, 'STIC/icart 0040'),
    (0x0080, 0x0081, 'Intellivoice'), (0x0082, 0x00EF, 'unmapped 00xx'),
    (0x00F0, 0x00FF, 'ECS PSG'), (0x0100, 0x01EF, 'scratchpad'),
    (0x01F0, 0x01FF, 'PSG'), (0x0200, 0x035F, 'system RAM'),
    (0x0360, 0x0FFF, '0360-0FFF'), (0x1000, 0x1FFF, 'EXEC'),
    (0x2000, 0x2FFF, '2000 cart/ECS'), (0x3000, 0x37FF, 'GROM'),
    (0x3800, 0x3FFF, 'GRAM'), (0x4000, 0x403F, 'STIC alias 4000'),
    (0x4040, 0x4FFF, '4040-4FFF'), (0x5000, 0x6FFF, 'cart 5000-6FFF'),
    (0x7000, 0x7FFF, '7000-7FFF'), (0x8000, 0x803F, 'STIC alias 8000'),
    (0x8040, 0xBFFF, 'cart 8040-BFFF'), (0xC000, 0xC03F, 'STIC alias C000'),
    (0xC040, 0xFFFF, 'cart C040-FFFF'),
]


def region(a):
    for lo, hi, name in REGIONS:
        if lo <= a <= hi:
            return name
    return '?'


def summarise(path):
    h = hashlib.sha256()
    insns = 0
    per_frame = Counter()
    first_c = {}
    last_c = {}
    irqs = []
    pcs = Counter()
    reads = Counter()
    writes = Counter()
    bad = 0
    last_pc = None
    with open(path, 'rb') as f:
        for raw in f:
            h.update(raw)
            line = raw.decode('ascii', 'replace').rstrip('\n')
            if not line.strip():
                continue
            m = INSN.match(line)
            if m:
                insns += 1
                c, fr = int(m.group(1)), int(m.group(2))
                per_frame[fr] += 1
                first_c.setdefault(fr, c)
                last_c[fr] = c
                last_pc = int(m.group(6), 16)
                pcs[region(last_pc)] += 1
                continue
            m = ACC.match(line)
            if m:
                a = int(m.group(2), 16)
                (reads if m.group(1) == 'R' else writes)[region(a)] += 1
                continue
            m = IRQ.match(line)
            if m:
                irqs.append((insns, int(m.group(1), 16), int(m.group(2))))
                continue
            bad += 1
            if bad <= 5:
                print('  unparsed:', line[:80])
    print(f'{path}')
    print(f'  sha256 {h.hexdigest()}')
    print(f'  instructions {insns}, unparsed lines {bad}, interrupts {len(irqs)}')
    print('  frame: instructions, first..last total cycle')
    for fr in sorted(per_frame):
        print(f'    {fr:3d}: {per_frame[fr]:6d}  {first_c[fr]}..{last_c[fr]}')
    print('  interrupts (instruction index, return PC region):',
          ', '.join(f'{i}:{region(pc)}' for i, pc, _ in irqs))
    print('  instructions by PC region:', dict(pcs.most_common()))
    print('  reads by region (fetches included):', dict(reads.most_common()))
    print('  writes by region:', dict(writes.most_common()))
    return 0 if insns and not bad else 1


if __name__ == '__main__':
    rc = 0
    for p in sys.argv[1:]:
        rc |= summarise(p)
    sys.exit(rc)
