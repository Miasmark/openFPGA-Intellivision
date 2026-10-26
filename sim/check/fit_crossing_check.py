#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""After a fit: the input crossing's checks in ap_core.sta.rpt (DESIGN.md 7.2,
core_constraints.sdc, core/sta_reports.tcl).

  python3 -I sim/check/fit_crossing_check.py [src/fpga/output_files/ap_core.sta.rpt]

- "Input crossing net delay (slow model)" and "(fast model)": the
  set_net_delay summary row and every net row with no negative slack; the
  rows are exactly hold_74[i] -> word[i], one per word register the fit
  kept (the message "Input crossing registers: word N, hold_74 N"), and
  req_74 -> req_s[0]. So a renamed or pruned register cannot drop a path
  from the check unseen.
- "Synchronizer chains" (the metastability report): req_74 crosses through
  req_s[0], req_s[1] and ack through ack_74[0], ack_74[1], two flip-flops
  each, in clk and clk_74a. A load decided on req_s[0] alone (which no
  simulation shows) leaves req_s[1] out of the chain.

Prints one line per check and FIT_CROSSING pass or FIT_CROSSING FAIL.
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
INST = 'intv_input:'


def cells(line):
    return [c.strip() for c in line.strip().strip(';').split(';')]


def net_panel(lines, title):
    """Rows (name, slack, from, to) of a report_net_delay panel, or None."""
    for i, ln in enumerate(lines):
        if ln.startswith('; ' + title) and ln.rstrip().endswith(';'):
            break
    else:
        return None
    rows = []
    j = i + 1
    while j < len(lines) and not lines[j].startswith('; Name'):
        j += 1
    j += 2      # header and the line below it
    while j < len(lines) and lines[j].startswith(';'):
        c = cells(lines[j])
        rows.append((c[0], float(c[1]), c[4], c[5]))
        j += 1
    return rows


def chain(lines, source):
    """The synchronisation registers of the metastability report's chain from `source`, or None."""
    for i, ln in enumerate(lines):
        if (ln.startswith('; Asynchronous Source') and i + 1 < len(lines)
                and INST in cells(lines[i + 1])[0] and cells(lines[i + 1])[0].endswith(source)):
            j = i + 2
            if not lines[j].startswith('; Synchronization Registers'):
                continue
            regs = []
            j += 1
            while j < len(lines) and lines[j].startswith(';  '):
                regs.append(cells(lines[j])[0])
                j += 1
            return regs
    return None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'src', 'fpga', 'output_files', 'ap_core.sta.rpt')
    lines = open(path).read().splitlines()
    fails = []

    def check(ok, what):
        print(('  ok    ' if ok else '  FAIL  ') + what)
        if not ok:
            fails.append(what)

    m = [re.search(r'Input crossing registers: word (\d+), hold_74 (\d+)', ln) for ln in lines]
    m = [x for x in m if x]
    nword = int(m[0].group(1)) if m else -1
    check(bool(m) and nword > 0 and int(m[0].group(2)) == nword,
          f'registers kept: word {nword}, hold_74 {m[0].group(2) if m else "?"} (message from core/sta_reports.tcl)')
    for model in ('slow', 'fast'):
        rows = net_panel(lines, f'Input crossing net delay ({model} model)')
        if rows is None:
            check(False, f'{model} model: panel "Input crossing net delay ({model} model)" missing')
            continue
        summ = [r for r in rows if r[0] == 'set_net_delay']
        nets = [r for r in rows if r[0] == '--']
        check(len(summ) == 1 and summ[0][1] >= 0, f'{model} model: set_net_delay worst slack '
              f'{summ[0][1] if summ else "?"} ns (10 ns bound)')
        neg = [r for r in nets if r[1] < 0]
        check(not neg, f'{model} model: {len(nets)} nets, {len(neg)} with negative slack')
        bits, req, other = set(), 0, []
        for _, _, fr, to in nets:
            a = re.fullmatch(r'.*' + INST + r'[^|]*\|hold_74\[(\d+)\]', fr)
            b = re.fullmatch(r'.*' + INST + r'[^|]*\|word\[(\d+)\]', to)
            if a and b and a.group(1) == b.group(1):
                bits.add(int(a.group(1)))
            elif fr.endswith('|req_74') and to.endswith('|req_s[0]') and INST in fr:
                req += 1
            else:
                other.append((fr, to))
        check(len(bits) == nword and len(nets) == nword + 1 and req == 1 and not other,
              f'{model} model: rows hold_74[i] -> word[i] for {len(bits)} of {nword} kept bits, '
              f'req_74 -> req_s[0] {req}, other rows {len(other)}')
    for src, regs in (('|req_74', ['req_s[0]', 'req_s[1]']), ('|ack', ['ack_74[0]', 'ack_74[1]'])):
        got = chain(lines, src)
        names = [g.split('|')[-1] for g in got if INST in g] if got else None
        check(names == regs, f'synchronizer chain from {src[1:]}: {names} (want {regs})')
    print('FIT_CROSSING ' + ('pass' if not fails else 'FAIL'))
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
