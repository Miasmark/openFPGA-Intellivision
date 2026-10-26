#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""After a fit: the clock crossings' checks in ap_core.sta.rpt (DESIGN.md 7.2,
docs/SAVESTATE.md 1, core_constraints.sdc, core/sta_reports.tcl).

  python3 -I sim/check/fit_crossing_check.py [src/fpga/output_files/ap_core.sta.rpt]

- "Crossing net delay (slow model)" and "(fast model)": every set_net_delay
  summary row (four: the input module's and the save states' three) and
  every net row with no negative slack; the rows are exactly
  - hold_74[i] -> word[i], one per word register the fit kept (the message
    "Input crossing registers: word N, hold_74 N"), and req_74 -> req_s[0];
  - in intv_ss_ctl: b_we -> b_we_s, b_w[i] -> bp_w[i], b_d[i] -> bp_d[i],
    r_q[i] -> bridge_rd_data[i], one per kept destination bit (the message
    "Save-state crossing registers: ..."), b_t -> b_s[0], r_t -> r_s[0],
    and the eight result bits s_ack .. l_err -> st_a[7] .. st_a[0];
  so a renamed or pruned register cannot drop a path from the check unseen
  (a source may carry Quartus's ~DUPLICATE suffix).
- "Synchronizer chains" (the metastability report): req_74 crosses through
  req_s[0], req_s[1] and ack through ack_74[0], ack_74[1], two flip-flops
  each, in clk and clk_74a; in intv_ss_ctl b_t through b_s[0], b_s[1], r_t
  through r_s[0], r_s[1], and each result bit through st_a[k], st_b[k]. A
  load decided on the first flip-flop alone (which no simulation shows)
  leaves the second out of the chain.

Prints one line per check and FIT_CROSSING pass or FIT_CROSSING FAIL.
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
INST = 'intv_input:'
SS = 'intv_ss_ctl:'
SS_ST = ['s_ack', 's_busy', 's_ok', 's_err', 'l_ack', 'l_busy', 'l_ok', 'l_err']   # st_a[7] .. st_a[0]


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


def chain(lines, source, inst=INST):
    """The synchronisation registers of the metastability report's chain from `source`, or None."""
    for i, ln in enumerate(lines):
        if (ln.startswith('; Asynchronous Source') and i + 1 < len(lines)
                and inst in cells(lines[i + 1])[0]
                and re.sub(r'~DUPLICATE$', '', cells(lines[i + 1])[0]).endswith(source)):
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
    m = [re.search(r'Save-state crossing registers:(( \S+ \d+)+)', ln) for ln in lines]
    m = [x for x in m if x]
    kept = {}
    if m:
        t = m[0].group(1).split()
        kept = {t[i]: int(t[i + 1]) for i in range(0, len(t), 2)}
    pairs = [('b_we', 'b_we_s'), ('b_w', 'bp_w'), ('b_d', 'bp_d'), ('r_q', 'bridge_rd_data')]
    check(bool(kept) and all(kept.get(d, 0) > 0 for _, d in pairs) and kept.get('st_a') == 8,
          f'save-state registers kept: {kept or "?"} (message from core/sta_reports.tcl)')
    for model in ('slow', 'fast'):
        title = f'Crossing net delay ({model} model)'
        rows = net_panel(lines, title)
        if rows is None:
            check(False, f'{model} model: panel "{title}" missing')
            continue
        summ = [r for r in rows if r[0] == 'set_net_delay']
        nets = [r for r in rows if r[0] == '--']
        check(len(summ) == 4 and all(r[1] >= 0 for r in summ), f'{model} model: {len(summ)} set_net_delay '
              f'bounds (want 4), worst slack {min((r[1] for r in summ), default="?")} ns (10 ns bound)')
        neg = [r for r in nets if r[1] < 0]
        check(not neg, f'{model} model: {len(nets)} nets, {len(neg)} with negative slack')
        bits, req, other = set(), 0, []
        ss = {d: set() for _, d in pairs}
        ss_tog, ss_st = set(), set()
        for _, _, fr, to in nets:
            fr = re.sub(r'~DUPLICATE$', '', fr)
            a = re.fullmatch(r'.*' + INST + r'[^|]*\|hold_74\[(\d+)\]', fr)
            b = re.fullmatch(r'.*' + INST + r'[^|]*\|word\[(\d+)\]', to)
            fs = re.fullmatch(r'.*' + SS + r'[^|]*\|(\w+)(?:\[(\d+)\])?', fr)
            ts = re.fullmatch(r'.*' + SS + r'[^|]*\|(\w+)(?:\[(\d+)\])?', to)
            if a and b and a.group(1) == b.group(1):
                bits.add(int(a.group(1)))
            elif fr.endswith('|req_74') and to.endswith('|req_s[0]') and INST in fr:
                req += 1
            elif fs and ts and (fs.group(1), ts.group(1)) in pairs and fs.group(2) == ts.group(2):
                ss[ts.group(1)].add(ts.group(2))
            elif fs and ts and (fs.group(1), ts.group(1), ts.group(2)) in (('b_t', 'b_s', '0'), ('r_t', 'r_s', '0')):
                ss_tog.add(fs.group(1))
            elif (fs and ts and ts.group(1) == 'st_a' and fs.group(1) in SS_ST
                  and ts.group(2) == str(7 - SS_ST.index(fs.group(1)))):
                ss_st.add(fs.group(1))
            else:
                other.append((fr, to))
        n_ss = sum(len(v) for v in ss.values())
        check(len(bits) == nword and req == 1,
              f'{model} model: rows hold_74[i] -> word[i] for {len(bits)} of {nword} kept bits, '
              f'req_74 -> req_s[0] {req}')
        check(all(len(ss[d]) == kept.get(d, -1) for _, d in pairs) and ss_tog == {'b_t', 'r_t'}
              and len(ss_st) == 8,
              f'{model} model: save-state rows ' + ', '.join(f'{s_} -> {d} {len(ss[d])} of {kept.get(d, "?")}'
                                                            for s_, d in pairs)
              + f', toggles {sorted(ss_tog)}, result bits {len(ss_st)} of 8')
        check(not other and len(nets) == nword + 1 + n_ss + len(ss_tog) + len(ss_st),
              f'{model} model: other rows {len(other)} {other[:2]}')
    want = [(INST, '|req_74', ['req_s[0]', 'req_s[1]']), (INST, '|ack', ['ack_74[0]', 'ack_74[1]']),
            (SS, '|b_t', ['b_s[0]', 'b_s[1]']), (SS, '|r_t', ['r_s[0]', 'r_s[1]'])]
    want += [(SS, '|' + b, ['st_a[%d]' % (7 - k), 'st_b[%d]' % (7 - k)]) for k, b in enumerate(SS_ST)]
    for inst, src, regs in want:
        got = chain(lines, src, inst)
        names = [g.split('|')[-1] for g in got if inst in g] if got else None
        check(names is not None and names[:2] == regs,
              f'synchronizer chain from {inst}{src[1:]}: {names} (want {regs} first)')
    print('FIT_CROSSING ' + ('pass' if not fails else 'FAIL'))
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
