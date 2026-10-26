#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""psg_compare: the PSG model (tools/psg.py in tools/intv_system.py) against MAME.

DESIGN.md 9 step 6: "register logs match MAME". For one game this runs the
system model on MAME's terms (STIC mode "mame": MAME's frame timing and
clock, tools/intv_system.py system_for) with the same keys held as in the
MAME run (tools/refs/mame_psg.sh), twice:

  run A, the model with MAME's tone counter (tools/psg.py mame_tone: the
  count keeps its remainder when a smaller period is written) and on
  MAME's step grid (ClockedPsg.mame_grid: MAME's 223,721 Hz stream, a
  write applied at the start of the writing instruction, MAME's CPU time
  then). It must give
    1. the register-write log exactly: every CPU write to $01F0-$01FF
       with MAME's cycle count at the start of the writing instruction,
       the frame (MAME's screen frame), R7 after it, address and data
       (psg.log, MAME debugger watchpoint);
    2. MAME's AY-3-8914 output step by step: the three channels' DAC
       levels after every generator step against MAME's own stream at its
       own rate (ticks.bin, MAME's Lua sound hook; each float mapped back
       to its level through MAME's two tables, ay8910.cpp
       build_single_table), every step equal;
  run B, the model as the RTL runs it (tone counter restarts at 0; still
  MAME's grid and write time, so only the counter differs), reported, not
  gated:
    3. the share of steps equal to MAME's (a smaller period written while
       the count is past it ends the half cycle at once instead of
       keeping the remainder, so the tone's phase can differ from there on;
       the pitch is the same);
    4. the sound, which need not be sample-exact: run B's 48 kHz output
       (what intv_psg.sv gives the Pocket), and run A's for scale, against
       MAME's -wavwrite file (MAME resamples with its own filter and has
       slightly different envelope levels), per 2,048-sample window (43
       ms) with its mean removed:
       - pitch: the strongest frequency above 47 Hz of each window's
         spectrum (Hann window, 23.4 Hz bins); windows where model and MAME
         differ by more than one bin and 2 %; and the correlation of the
         two spectra from 47 Hz to 12 kHz (median, 10th percentile);
       - envelope: each window's RMS, both scaled to their loudest window;
         the correlation of the two RMS curves and the largest difference
         over loud windows (either above 2 % of its peak);
       - waveform: every 8th loud window's correlation at its best lag
         within 100 samples (MAME's file does not keep a fixed lag to
         emulated time: measured lags wander by up to 100 samples), median
         and 10th percentile.

  python3 tools/psg_compare.py compare MAMEDIR --cart IMG --frames N
        [--press F1-F2:KEY,...] [--bios-dir DIR] [--wav OUT.wav]
MAMEDIR is mame_psg.sh's OUTDIR for the same image, frames and presses.
The last line is "PSG_COMPARE <name> pass" or "... FAIL" (1 and 2). Nothing
derived from the game is written unless --wav names a file (run B's
sound; keep it outside the repository).
"""

import argparse
import array
import math
import os
import re
import sys
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import intv_system as isys  # noqa: E402

# DESIGN 7.1 (MAME handctrl.cpp:124-135): lines pulled low per key
KEYCODE = {"1": 0x81, "2": 0x41, "3": 0x21, "4": 0x82, "5": 0x42, "6": 0x22,
           "7": 0x84, "8": 0x44, "9": 0x24, "Clear": 0x88, "0": 0x48, "Enter": 0x28,
           "Upper": 0xA0, "Lower-Left": 0x60, "Lower-Right": 0xC0}
LOG_RE = re.compile(r"c=(\d+) f=(\d+) pc=([0-9A-F]+) W ([0-9A-F]+) ([0-9A-F]+)$")
WIN = 2048


def parse_presses(text):
    out = []
    for p in filter(None, (text or "").split(",")):
        fr, key = p.split(":", 1)
        f1, f2 = (int(x) for x in fr.split("-"))
        if key not in KEYCODE:
            raise SystemExit("unknown key %r" % key)
        out.append((f1, f2, KEYCODE[key]))
    return out


def model_run(cart, frames, presses, bios_dir=None, mame_tone=False):
    """Run the model on MAME's terms; return (register log, packed levels
    per step, 48 kHz samples)."""
    bus, cpu, _ = isys.system_for("mame", bios_dir, cart)
    bus.snd.mame_tone = mame_tone
    bus.snd.mame_grid = True
    log = []
    samples = array.array("i")
    ticks = array.array("H")
    bus.snd.on_sample = samples.append
    bus.snd.on_tick = lambda k, lv: ticks.append(lv)
    orig_w = bus.write
    tm = bus.timing

    def wr(addr, value, cycle):
        a = addr & 0xFFFF
        if 0x1F0 <= a <= 0x1FF:
            t = bus._t(cpu.cycle)
            log.append([t, tm.frame(t), None, a, value & 0xFFFF, t])
            if a <= 0x1FD:      # MAME's write time: the instruction's start
                bus.snd.bus_write(a & 0xF, value, t)
            return
        orig_w(addr, value, cycle)
    bus.write = wr
    cur = [None]

    def pads(k):
        v = 0xFF
        for f1, f2, code in presses:
            if f1 <= k < f2:
                v &= ~code & 0xFF
        return v
    end = None
    while True:
        ev = cpu.step()
        for x in log[-4:]:      # MAME's R7 at the watchpoint: after the instruction
            if x[2] is None:
                x[2] = cpu.r[7]
        isys.mame_quirks(bus, cpu, ev)
        if ev.text.startswith("SDBD"):
            continue
        bus.boundary(cpu.cycle)
        k = len(tm.starts)
        if k != cur[0]:
            cur[0] = k
            p = pads(k - 1)     # MAME's notifier n runs before the CPU sees frame n + 1
            bus.pad = (p, p)
            if k >= frames and end is None:
                end = cpu.cycle
                break
    bus.snd.advance(bus._t(end))
    return log, ticks, samples


def mame_tables():
    """MAME's AY-3-8914 output values per level: the fixed-volume table and
    the envelope table (MAME ay8910.cpp build_single_table, legacy output
    normalisation, ay8910_param, 1000 ohm load)."""
    import psg
    out = []
    for zero_off in (True, False):
        t = []
        for j, r in enumerate(psg._RES):
            rt, rw = 1 / psg._R_DOWN + 1 / psg._RL + 1 / r, 1 / r
            if not (zero_off and j == 0):
                rt += 1 / psg._R_UP
                rw += 1 / psg._R_UP
            t.append(rw / rt)
        lo, hi = min(t), max(t)
        out.append([((x - lo) / (hi - lo) - 0.25) * 0.5 for x in t])
    return out


def mame_ticks(mamedir):
    """MAME's stream as packed levels a | b << 4 | c << 8 per step."""
    tabs = mame_tables()
    lv = {}
    with open(os.path.join(mamedir, "ticks.ids")) as f:
        for line in f:
            k, x = line.split()
            x = float(x)
            best = min(((abs(v - x), j) for tab in tabs for j, v in enumerate(tab)))
            if best[0] > 1e-6:
                raise SystemExit("ticks.ids: %s is no level of MAME's tables" % x)
            lv[int(k)] = best[1]
    raw = open(os.path.join(mamedir, "ticks.bin"), "rb").read()
    lut = [lv.get(i, 0) for i in range(256)]
    return array.array("H", (lut[raw[i]] | lut[raw[i + 1]] << 4 | lut[raw[i + 2]] << 8
                             for i in range(0, len(raw) - 2, 3)))


def read_mame_log(path):
    out = []
    with open(path) as f:
        for line in f:
            m = LOG_RE.match(line.strip())
            if not m:
                raise SystemExit("%s: bad line %r" % (path, line))
            out.append((int(m.group(1)), int(m.group(2)), int(m.group(3), 16),
                        int(m.group(4), 16), int(m.group(5), 16)))
    return out


def read_wav(path):
    w = wave.open(path)
    if w.getsampwidth() != 2 or w.getframerate() != 48000:
        raise SystemExit("%s: want 16-bit 48 kHz" % path)
    nch = w.getnchannels()
    a = array.array("h", w.readframes(w.getnframes()))
    if sys.byteorder == "big":
        a.byteswap()
    return a[::nch] if nch > 1 else a


def write_wav(path, samples):
    a = array.array("h", (max(-32768, min(32767, s)) for s in samples))
    if sys.byteorder == "big":
        a.byteswap()
    w = wave.open(path, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(48000)
    w.writeframes(a.tobytes())
    w.close()


def _dc(x):
    m = sum(x) / len(x)
    return [v - m for v in x]


def _corr(a, b):
    sab = sum(map(float.__mul__, a, b))
    saa = sum(map(float.__mul__, a, a))
    sbb = sum(map(float.__mul__, b, b))
    if saa <= 0 or sbb <= 0:
        return None
    return sab / math.sqrt(saa * sbb)


_FFT = {}


def _spectrum(x):
    """Magnitudes of a Hann-windowed radix-2 FFT of x (len a power of 2),
    bins 0 .. n/2 - 1."""
    n = len(x)
    if n not in _FFT:
        bits = n.bit_length() - 1
        rev = [int(format(i, "0%db" % bits)[::-1], 2) for i in range(n)]
        hann = [0.5 - 0.5 * math.cos(2 * math.pi * i / n) for i in range(n)]
        tw = [complex(math.cos(-2 * math.pi * k / n), math.sin(-2 * math.pi * k / n)) for k in range(n // 2)]
        _FFT[n] = (rev, hann, tw)
    rev, hann, tw = _FFT[n]
    a = [complex(x[rev[i]] * hann[rev[i]], 0) for i in range(n)]
    size = 2
    while size <= n:
        half, step = size // 2, n // size
        for st in range(0, n, size):
            for k in range(half):
                t = tw[k * step] * a[st + k + half]
                u = a[st + k]
                a[st + k] = u + t
                a[st + k + half] = u - t
        size *= 2
    return [abs(v) for v in a[:n // 2]]


def _peak(sp, lo=2):
    """The strongest bin from lo on (lo = 2: above about 47 Hz)."""
    return max(range(lo, len(sp)), key=sp.__getitem__)


def _best_corr(a, b, i, lag, span=100):
    x = _dc([float(v) for v in a[i:i + WIN]])
    best = None
    for d in range(lag - span, lag + span + 1):
        if i + d < 0 or i + d + WIN > len(b):
            continue
        c = _corr(x, _dc([float(v) for v in b[i + d:i + d + WIN]]))
        if c is not None and (best is None or c > best[0]):
            best = (c, d)
    return best


def compare_audio(model, mame):
    n = min(len(model), len(mame))
    wins = []
    for i in range(0, n - WIN, WIN):
        a = _dc([float(v) for v in model[i:i + WIN]])
        b = _dc([float(v) for v in mame[i:i + WIN]])
        ra = math.sqrt(sum(v * v for v in a) / WIN)
        rb = math.sqrt(sum(v * v for v in b) / WIN)
        wins.append([ra, rb, a, b])
    if not wins:
        return {"windows": 0}
    ma = max(w[0] for w in wins) or 1
    mb = max(w[1] for w in wins) or 1
    ea = [w[0] / ma for w in wins]
    eb = [w[1] / mb for w in wins]
    loud = [k for k in range(len(wins)) if ea[k] > 0.02 or eb[k] > 0.02]
    pitch_bad, spec = [], []
    for k in loud:
        sa, sb = _spectrum(wins[k][2]), _spectrum(wins[k][3])
        pa, pb = _peak(sa), _peak(sb)
        if abs(pa - pb) > max(1, 0.02 * max(pa, pb)):
            pitch_bad.append(k)
        c = _corr(_dc(sa[2:WIN // 4]), _dc(sb[2:WIN // 4]))      # 47 Hz - 12 kHz
        if c is not None:
            spec.append(c)
    spec.sort()
    cs, lag = [], 0
    for k in loud[::8]:
        r = _best_corr(model, mame, k * WIN, lag)
        if r is not None:
            cs.append(r[0])
            lag = r[1]
    cs.sort()
    return {
        "windows": len(wins), "loud": len(loud),
        "pitch_bad": len(pitch_bad), "pitch_bad_at": [k * WIN / 48000 for k in pitch_bad[:5]],
        "spec_median": spec[len(spec) // 2] if spec else None,
        "spec_p10": spec[len(spec) // 10] if spec else None,
        "env_corr": _corr(_dc(ea), _dc(eb)),
        "env_maxdiff": max((abs(ea[k] - eb[k]) for k in loud), default=0.0),
        "wave_n": len(cs),
        "wave_median": cs[len(cs) // 2] if cs else None,
        "wave_p10": cs[len(cs) // 10] if cs else None,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare")
    c.add_argument("mamedir")
    c.add_argument("--cart", required=True)
    c.add_argument("--frames", type=int, required=True)
    c.add_argument("--press", default="")
    c.add_argument("--bios-dir")
    c.add_argument("--wav")
    c.add_argument("--name")
    a = ap.parse_args()
    name = a.name or os.path.basename(a.mamedir.rstrip("/"))
    presses = parse_presses(a.press)
    want = read_mame_log(os.path.join(a.mamedir, "psg.log"))
    xticks = mame_ticks(a.mamedir)
    probs = []
    # run A: MAME's tone counter
    mlog, mticks, asamples = model_run(a.cart, a.frames, presses, a.bios_dir, mame_tone=True)
    n = min(len(mlog), len(want))
    first = next((i for i in range(n) if tuple(mlog[i][:5]) != want[i]), None)
    if first is not None:
        probs.append("write %d: model c=%d f=%d pc=%04X W %04X %04X, MAME c=%d f=%d pc=%04X W %04X %04X"
                     % ((first,) + tuple(mlog[first][:5]) + want[first]))
    elif len(mlog) != len(want):
        probs.append("model %d writes, MAME %d" % (len(mlog), len(want)))
    nt = min(len(mticks), len(xticks))
    bad = [k for k in range(nt) if mticks[k] != xticks[k]]
    if bad:
        probs.append("%d of %d PSG steps differ from MAME's (first: step %d)" % (len(bad), nt, bad[0]))
    regs = sorted({x[3] for x in mlog})
    print("%s: %d frames, %d register writes (%d addresses), %s; %d PSG steps, %d equal to MAME's"
          % (name, a.frames, len(mlog), len(regs),
             "log equal to MAME's" if first is None and len(mlog) == len(want) else "log differs",
             nt, nt - len(bad)))
    # run B: the RTL's tone counter
    _, bticks, samples = model_run(a.cart, a.frames, presses, a.bios_dir, mame_tone=False)
    nb = min(len(bticks), len(xticks))
    eq = sum(1 for k in range(nb) if bticks[k] == xticks[k])
    print("  RTL counter: %d of %d steps equal to MAME's (%.2f%%)" % (eq, nb, 100.0 * eq / max(nb, 1)))
    if a.wav:
        write_wav(a.wav, samples)
    mame = read_wav(os.path.join(a.mamedir, "audio.wav"))
    for lab, smp in (("RTL counter", samples), ("MAME counter", asamples)):
        au = compare_audio(smp, mame)
        if au.get("windows"):
            print("  48 kHz, %s: model %d samples, MAME %d; %d windows of %d, %d loud; strongest "
                  "frequency differs in %d %s; spectrum corr median %.4f, 10th pct %.4f; envelope "
                  "corr %.4f, max diff %.3f; waveform corr (%d windows) median %.4f, 10th pct %.4f"
                  % (lab, len(smp), len(mame), au["windows"], WIN, au["loud"], au["pitch_bad"],
                     ["%.2fs" % t for t in au["pitch_bad_at"]], au["spec_median"] or 0,
                     au["spec_p10"] or 0, au["env_corr"] or 0, au["env_maxdiff"], au["wave_n"],
                     au["wave_median"] or 0, au["wave_p10"] or 0))
    for p in probs:
        print("  FAIL", p)
    print("PSG_COMPARE %s %s" % (name, "pass" if not probs else "FAIL"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
