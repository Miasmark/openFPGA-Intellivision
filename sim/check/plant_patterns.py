#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""plant_patterns: every bench's planted faults still find their lines in the RTL (1.0.9).

  python3 -I sim/check/plant_patterns.py        prints PLANT_PATTERNS pass / FAIL

Each planted fault patches a line of the RTL by text; when the RTL changes, a pattern can stop
matching and the bench then reports "pattern not found" only when that plant runs, which in the
gate is hours later (gate30: 21 such plants after the TutorVision changes). This check reads the
plant tables of every bench without running anything and checks, in a second or two, that each
pattern is in its file: exactly once for the Python benches (they refuse a pattern found more
than once), at least once for the shell benches (grep -F, the first copy replaced). Run it after
every RTL change, before any bench; the Python gates run it too.

The tables: tb_system.py PLANTS and ECS_PLAY_PLANTS, tb_loader.py, tb_savestate.py, tb_input.py,
tb_osk.py, tb_tape.py, tb_voice.py PLANTS; run_tb_cpu.sh and run_tb_timing.sh "plant" lines.
An entry is (name, file, from, to, ...) or (name, file, [(from, to), ...], ...). A list of pairs
is checked as the benches apply it: each pattern in the file as it stands after the pairs
before it (a pair may patch a line an earlier pair wrote).
"""
import importlib.util
import os
import re
import shlex
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TB = os.path.join(ROOT, 'sim', 'tb')
SEARCH = [os.path.join(ROOT, 'src', 'fpga', 'core'), os.path.join(ROOT, 'src', 'fpga'), TB]
TABLES = [('tb_system', ('PLANTS', 'ECS_PLAY_PLANTS')), ('tb_loader', ('PLANTS',)),
          ('tb_savestate', ('PLANTS',)), ('tb_input', ('PLANTS',)), ('tb_osk', ('PLANTS',)),
          ('tb_tape', ('PLANTS',)), ('tb_voice', ('PLANTS',))]
SHELL = ['run_tb_cpu.sh', 'run_tb_timing.sh']


def find(name):
    for d in SEARCH:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    for d, _, fs in os.walk(os.path.join(ROOT, 'src', 'fpga')):
        if name in fs:
            return os.path.join(d, name)
    return None


def load(mod):
    sys.path[:0] = [TB, os.path.join(ROOT, 'tools'), os.path.join(ROOT, 'tools', 'mapper')]
    spec = importlib.util.spec_from_file_location(mod, os.path.join(TB, mod + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def entries(table):
    """(name, file, [(from, to)]) from a plant table's tuples."""
    for e in table:
        name = e[0]
        fn = next(x for x in e[1:] if isinstance(x, str) and re.search(r'\.(sv|svh|v|vh)$', x))
        i = e.index(fn)
        rest = e[i + 1:]
        if rest and isinstance(rest[0], list):
            pairs = [tuple(p) for p in rest[0]]
        else:
            pairs = [(rest[0], rest[1])]
        yield name, fn, pairs


def check_python(fails, counts):
    for mod, names in TABLES:
        m = load(mod)
        for tn in names:
            table = getattr(m, tn, None)
            if table is None:
                fails.append('%s.%s: no such table' % (mod, tn))
                continue
            n = 0
            for name, fn, pairs in entries(table):
                n += 1
                p = find(fn)
                if p is None:
                    fails.append('%s %s: file %s not found' % (mod, name, fn))
                    continue
                src = open(p).read()
                for k, (frm, to) in enumerate(pairs):
                    c = src.count(frm)
                    if c != 1:
                        fails.append('%s %s: pattern %d of %d in %s found %d times: %r'
                                     % (mod, name, k + 1, len(pairs), fn, c, frm[:70]))
                        break
                    src = src.replace(frm, to, 1)
            counts['%s.%s' % (mod, tn)] = n


def check_shell(fails, counts):
    for sh in SHELL:
        text = open(os.path.join(TB, sh)).read()
        var = dict(re.findall(r'^([A-Z_]+)=(\S+)$', text, re.M))
        n = 0
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if not line.startswith('plant '):
                continue
            j, words = i, None
            while words is None:            # a quoted pattern may run over several lines
                try:
                    words = shlex.split('\n'.join(lines[i:j + 1]))
                except ValueError:
                    j += 1
            name, fn, frm = words[1], words[2], words[3]
            fn = re.sub(r'\$\{?([A-Z_]+)\}?', lambda mo: var.get(mo.group(1), mo.group(0)), fn)
            n += 1
            p = find(fn)
            if p is None:
                fails.append('%s %s: file %s not found' % (sh, name, fn))
                continue
            if frm not in open(p).read():
                fails.append('%s %s: pattern not in %s: %r' % (sh, name, fn, frm[:70]))
        counts[sh] = n


def main():
    fails, counts = [], {}
    check_python(fails, counts)
    check_shell(fails, counts)
    for f in fails:
        print('  FAIL  ' + f)
    print('  %d plants: %s' % (sum(counts.values()), ', '.join('%s %d' % kv for kv in counts.items())))
    print('PLANT_PATTERNS %s' % ('pass' if not fails else 'FAIL (%d)' % len(fails)))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
