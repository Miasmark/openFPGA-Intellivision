#!/usr/bin/env python3
"""jzintv_frames.py: jzIntv as a second timing reference (STIC_NOTES section 7).

jzIntv is run as a black box (build_jzintv.sh; its GPL-2 sources are never
read or copied). It takes the STIC's BUSRQ cycles from the CPU, which MAME
does not (STIC_NOTES T2), so its pictures show which of the model's two
timings, mode `stic` (hardware) or mode `mame`, a second emulator with
stolen cycles follows.

  capture IMAGE|none FRAMES OUT
      Run jzIntv from reset with movie recording on (debugger `vm`), for at
      least FRAMES frames; expand the movie with jzIntv's imvtoppm and store
      every frame as colour numbers: OUT/jz.frames.gz (160 x 200 bytes a
      frame) and OUT/jz.json (the RGB of each number). jzIntv runs our own
      mapper's memory map (tools/intv_mapper.py, written as a jzIntv .cfg),
      ECS and Intellivoice off, as the model. With `none` it gets a one-word
      cartridge at $D000, because it does not start with an empty slot.
  compare IMAGE|none OUT [--palette FILE]
      Model pictures in modes stic and mame against the captured frames, in
      jzIntv's 160 x 200 window (model picture x 13-172, lines 20-219;
      jzIntv frame k = model picture k). jzIntv's colours are mapped to the
      model's palette numbers by majority over all frames (saved as
      OUT/palette.json; --palette reuses a mapping). A display-off frame
      counts as equal when jzIntv shows black where the model shows the
      border colour (STIC_NOTES D7). Prints counts only.
  stolen IMAGE|none STEPS OUT
      jzIntv debugger step log (`s STEPS`, timestamps on) and the model's
      mode-stic event list over the same number of steps; prints the BUSRQ
      cycles the CPU loses per frame in each, and the instructions whose
      cycle count differs between them (while both run the same code).

Environment: JZINTV_BIN (folder with jzintv and imvtoppm), INTV_BIOS
(exec.bin, grom.bin), INTV_BIOS_DIR for the model (defaults to INTV_BIOS).
OUT is derived from game data: keep it outside the repository.
Run with python3 -I.
"""
import argparse
import collections
import gzip
import json
import os
import re
import shutil
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

W, H, X0, Y0 = 160, 200, 13, 20          # jzIntv's frame inside the model picture
FRAME = 14934
STEP = re.compile(r'^\s*(?:[0-9A-F]{4} ){7}([0-9A-F]{4}) (\S{8})  (.*?)\s+(\d+)\s*$')


def env(name):
    v = os.environ.get(name)
    if not v:
        raise SystemExit('%s is not set' % name)
    return v


def setup(image, run):
    """run/game.bin + game.cfg: the image under our mapper's map."""
    shutil.rmtree(run, ignore_errors=True)
    os.makedirs(run)
    if image == 'none':
        open(os.path.join(run, 'game.bin'), 'wb').write(b'\xff\xff')
        open(os.path.join(run, 'game.cfg'), 'w').write('[mapping]\n$0000 - $0000 = $D000\n')
        return
    os.symlink(os.path.abspath(image), os.path.join(run, 'game.bin'))
    out = subprocess.run([sys.executable, '-I', os.path.join(TOOLS, 'intv_mapper.py'), 'map', image],
                         capture_output=True, text=True, check=True).stdout
    flags = int(re.search(r'^flags\s+(\S+)', out, re.M).group(1), 16)
    if flags & ~0x62:                    # ecs_off, estimated, voice: nothing to map
        raise SystemExit('mapper flags %02X not handled' % flags)
    lines = ['[mapping]']
    for a0, a1, kind in re.findall(r'^\s+([0-9A-F]{4})-([0-9A-F]{4})\s+[0-9A-F]{4}\s+(\S+)', out, re.M):
        m = re.match(r'ROM@([0-9A-F]+)$', kind)
        if not m:
            raise SystemExit('page kind %s not handled' % kind)
        off = int(m.group(1), 16) * 0x800
        lines.append('$%04X - $%04X = $%s' % (off, off + int(a1, 16) - int(a0, 16), a0))
    open(os.path.join(run, 'game.cfg'), 'w').write('\n'.join(lines) + '\n')


def jzintv(run, script, log):
    bios = env('INTV_BIOS')
    open(os.path.join(run, 'run.dbg'), 'w').write(script)
    e = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy')
    with open(os.path.join(run, log), 'w') as f:
        subprocess.run(['timeout', '200', os.path.join(env('JZINTV_BIN'), 'jzintv'),
                        '-e', bios + '/exec.bin', '-g', bios + '/grom.bin', '-s0', '-v0', '-a0',
                        '-r0', '-d', '--script=run.dbg', 'game.bin'],
                       cwd=run, env=e, stdout=f, stderr=subprocess.STDOUT)
    return open(os.path.join(run, log), errors='replace').read()


def cmd_capture(a):
    run = os.path.join(a.out, 'run')
    setup(a.image, run)
    log = jzintv(run, 'vm\nr %d\nvm\nq\n' % (a.frames * 2600), 'jzintv.log')
    m = re.search(r'Total frames:\s+(\d+)', log)
    if not m or int(m.group(1)) < a.frames:
        raise SystemExit('movie too short or missing: %s/jzintv.log' % run)
    imv = [f for f in os.listdir(run) if f.endswith('.imv')][0]
    pdir = os.path.join(run, 'ppm')
    os.makedirs(pdir)
    subprocess.run([os.path.join(env('JZINTV_BIN'), 'imvtoppm'), os.path.join(run, imv),
                    os.path.join(pdir, 'f')], check=True, capture_output=True)
    colours, cmap, last = [], {}, (None, None)
    with gzip.open(os.path.join(a.out, 'jz.frames.gz'), 'wb', compresslevel=3) as gz:
        for k in range(a.frames):
            p = os.path.join(pdir, 'f_%05d.ppm' % k)
            ino = os.stat(p).st_ino      # imvtoppm hard-links repeated frames
            if ino != last[0]:
                d = open(p, 'rb').read()
                px = d[len(d) - W * H * 3:]
                out = bytearray(W * H)
                for i in range(W * H):
                    rgb = px[3 * i:3 * i + 3]
                    if rgb not in cmap:
                        cmap[rgb] = len(colours)
                        colours.append(rgb.hex())
                    out[i] = cmap[rgb]
                last = (ino, bytes(out))
            gz.write(last[1])
    json.dump({'colours': colours, 'frames': a.frames, 'recorded': int(m.group(1))},
              open(os.path.join(a.out, 'jz.json'), 'w'))
    shutil.rmtree(pdir)
    print('%d frames (%s recorded), %d colours' % (a.frames, m.group(1), len(colours)))


def model_pictures(image, n, mode):
    os.environ.setdefault('INTV_BIOS_DIR', env('INTV_BIOS'))
    import stic_frames
    import stic
    got = stic_frames.model_pictures(image, set(range(n)), mode)
    out = {}
    for k, (pic, _) in got.items():
        out[k] = b''.join(bytes(pic[(y + Y0) * stic.W + X0:(y + Y0) * stic.W + X0 + W]) for y in range(H))
    return out


def ndiff(a, b):
    return 0 if a == b else sum(1 for x, y in zip(a, b) if x != y)


def cmd_compare(a):
    meta = json.load(open(os.path.join(a.out, 'jz.json')))
    raw = gzip.open(os.path.join(a.out, 'jz.frames.gz')).read()
    jzr = [raw[i:i + W * H] for i in range(0, len(raw), W * H)]
    n = len(jzr)
    md = {m: model_pictures(a.image, n, m) for m in ('stic', 'mame')}
    if a.palette:
        pal = json.load(open(a.palette))
    else:
        votes = collections.defaultdict(collections.Counter)
        for k in range(2, n, 3):
            if k in md['stic']:
                f, p = jzr[k], md['stic'][k]
                for i in range(0, W * H, 3):
                    votes[meta['colours'][f[i]]][p[i]] += 1
        pal = {c: v.most_common(1)[0][0] for c, v in votes.items()}
        if len(set(pal.values())) != len(pal):
            raise SystemExit('two jzIntv colours vote for one palette number: give --palette')
        json.dump(pal, open(os.path.join(a.out, 'palette.json'), 'w'), indent=1)
    t = bytes(pal.get(c, 255) for c in meta['colours']).ljust(256, b'\xff')
    jz = [f.translate(t) for f in jzr]
    ks = [k for k in range(2, n) if k in md['stic'] and k in md['mame']]
    c = collections.Counter()
    first = {}
    ds, dm = [], []
    for k in ks:
        f, s, m = jz[k], md['stic'][k], md['mame'][k]
        for ref in (s, m):
            if f != ref and len(set(ref)) == 1 and all(x == 0 for x, y in zip(f, ref) if x != y):
                f = ref                  # display off: black here, border colour in the model (D7)
                c['d7'] += 1
                break
        es, em, esm = f == s, f == m, s == m
        c['jz=stic'] += es
        c['jz=mame'] += em
        c['stic=mame'] += esm
        for key, ok in (('jz/stic', es), ('jz/mame', em), ('stic/mame', esm)):
            if not ok:
                first.setdefault(key, k)
        if not esm:
            c['split'] += 1
            c['split jz=stic'] += es
            c['split jz=mame'] += em
            a1, a2 = ndiff(f, s), ndiff(f, m)
            ds.append(a1)
            dm.append(a2)
            c['nearer stic' if a1 < a2 else 'nearer mame' if a2 < a1 else 'tie'] += 1
        for mode, ref in (('stic', md['stic']), ('mame', md['mame'])):
            c['near1 ' + mode] += any(jz[k] == ref.get(k + o) for o in (-1, 0, 1))
    med = lambda v: sorted(v)[len(v) // 2] if v else 0
    print('pictures %d-%d: jz = stic %d, jz = mame %d, stic = mame %d (display-off pictures taken as '
          'equal, D7: %d); equal at k-1, k or k+1: stic %d, mame %d' % (
              ks[0], ks[-1], c['jz=stic'], c['jz=mame'], c['stic=mame'], c['d7'], c['near1 stic'], c['near1 mame']))
    print('first difference: %s' % (', '.join('%s %d' % kv for kv in sorted(first.items(), key=lambda x: x[1])) or 'none'))
    print('where stic != mame (%d pictures): jz = stic %d, jz = mame %d; nearer stic %d, nearer mame %d, '
          'tie %d; median pixels from stic %d, from mame %d' % (
              c['split'], c['split jz=stic'], c['split jz=mame'], c['nearer stic'], c['nearer mame'],
              c['tie'], med(ds), med(dm)))


def cmd_stolen(a):
    run = os.path.join(a.out, 'trace')
    setup(a.image, run)
    jzintv(run, 's %d\nq\n' % a.steps, 'step.log')
    j = []
    for ln in open(os.path.join(run, 'step.log'), errors='replace'):
        m = STEP.match(ln)
        if m:
            j.append((int(m.group(1), 16), int(m.group(4)), m.group(2), m.group(3).strip()))
    # jzIntv: a frame starts where the interrupt line ('q') is first seen;
    # a BUSRQ stall is a step printed twice, the second time with 'B'.
    qa = [j[i][1] for i in range(1, len(j)) if j[i][2][-1] in 'qQ' and j[i - 1][2][-1] not in 'qQ']
    ph = collections.Counter(x % FRAME for x in qa).most_common(1)[0][0]
    jst, jn = collections.Counter(), collections.Counter()
    for i in range(1, len(j)):
        if j[i][2][-1] == 'B' and j[i - 1][0] == j[i][0] and j[i - 1][3] == j[i][3]:
            f = (j[i - 1][1] - ph) // FRAME
            jst[f] += j[i][1] - j[i - 1][1]
            jn[f] += 1
    os.environ.setdefault('INTV_BIOS_DIR', env('INTV_BIOS'))
    import intv_system as isys
    bus, cpu, _ = isys.system_for('stic', None, None if a.image == 'none' else a.image)
    mst, mn = collections.Counter(), collections.Counter()
    mev = []
    for _ in range(a.steps):
        ev = cpu.step()
        bus.boundary(cpu.cycle)
        if ev.kind == 'busak':
            mst[ev.cycle // FRAME] += ev.cycles
            mn[ev.cycle // FRAME] += 1
        elif ev.kind == 'insn':
            mev.append((ev.pc, ev.cycles))
    def stat(c, n):
        fs = sorted(f for f in c if f - 1 in c and f + 1 in c)[2:-1]
        if not fs:
            return 'no frames with BUSRQ'
        v = [c[f] for f in fs]
        r = [n[f] for f in fs]
        return '%d frames, %.1f cycles a frame (%d-%d), %.1f requests' % (
            len(fs), statistics.mean(v), min(v), max(v), statistics.mean(r))
    print('jzIntv: first interrupt line at cycle %d of its count (frame phase); BUSRQ lost: %s' % (ph, stat(jst, jn)))
    print('model mode stic: BUSRQ lost: %s' % stat(mst, mn))
    # instruction cycle counts while both run the same code, outside stalls and interrupts
    diff = collections.Counter()
    same = 0
    jc = {}
    for x, y in zip(j, j[1:]):
        if not any(ch in x[2] + y[2] for ch in 'qQbB'):
            jc.setdefault(x[0], collections.Counter())[y[1] - x[1]] += 1
    mc = {}
    for pc, cyc in mev:
        mc.setdefault(pc, collections.Counter())[cyc] += 1
    text = {x[0]: x[3] for x in j}
    for pc in jc:
        if pc in mc:
            if set(jc[pc]) == set(mc[pc]):
                same += 1
            else:
                key = re.sub(r'#?\$[0-9A-F]+', 'n', text[pc])
                diff[(key, tuple(sorted(jc[pc])), tuple(sorted(mc[pc])))] += 1
    print('instruction addresses with the same cycle counts: %d; different:' % same)
    for (key, jv, mv), cnt in sorted(diff.items()):
        print('  %-20s jzIntv %s, model %s (%d addresses)' % (key, jv, mv, cnt))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('capture')
    p.add_argument('image'); p.add_argument('frames', type=int); p.add_argument('out')
    p = sub.add_parser('compare')
    p.add_argument('image'); p.add_argument('out'); p.add_argument('--palette')
    p = sub.add_parser('stolen')
    p.add_argument('image'); p.add_argument('steps', type=int); p.add_argument('out')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    {'capture': cmd_capture, 'compare': cmd_compare, 'stolen': cmd_stolen}[a.cmd](a)


if __name__ == '__main__':
    main()
