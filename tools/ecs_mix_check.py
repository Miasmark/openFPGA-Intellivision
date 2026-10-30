#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""ecs_mix_check: the machine's sound with the ECS, peaks and clipping
(build step 9, the step-9 review; docs/ECS_NOTES.md 3).

Runs the system model (tools/intv_system.py, the RTL's timing, the ECS by
the menu override, Auto by default) for some frames with scripted keys and
takes every 48 kHz sample of PSG #1 and of PSG #2. It prints their peaks,
the peak of their sum, and how many samples of the mix intv_machine.sv
makes (the sum scaled to 3/4, floor, while the ECS is attached or on; at
most 32,767) reach the ceiling. ECS_MIX pass when none does, and, with
--want-sum N, when the sum's peak is at least N (so the run did reach the
loud passage the check is about).

  python3 -I tools/ecs_mix_check.py --cart IMG [--cfg CFG] [--frames 3200]
          [--presses TEXT|@FILE] [--ecs auto|on|off] [--want-sum N]

The cartridge and the BIOS (INTV_BIOS_DIR) are game data and the owner's
ROMs: they stay outside the repository; nothing is written.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import intv_system as isys  # noqa: E402

CEIL = 32767


def mix(v1, v2, ecs_on, level=2):
    """intv_machine.sv's sample: (PSG #1 + PSG #2 at the ECS level: 0 off, 1-4: x 1/2, 1, 3/2,
    2; 2 the default) * 3 / 4 (floor) while the ECS is attached or on, else the sum; at most
    32,767."""
    m = v1 + (0, v2 >> 1, v2, v2 + (v2 >> 1), v2 << 1)[level]
    if ecs_on:
        m = (3 * m) >> 2
    return min(CEIL, m)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cart", required=True)
    ap.add_argument("--cfg")
    ap.add_argument("--frames", type=int, default=3200)
    ap.add_argument("--presses", default="")
    ap.add_argument("--ecs", choices=("auto", "on", "off"), default="auto")
    ap.add_argument("--want-sum", type=int, default=0)
    ap.add_argument("--bios-dir")
    a = ap.parse_args()
    presses = a.presses
    if presses.startswith("@"):
        presses = open(presses[1:]).read().strip()
    bus, cpu, mclk = isys.system_for("stic", a.bios_dir, a.cart, ecs=(a.ecs, None), cfg_path=a.cfg)
    if presses:
        bus.presses = isys.parse_presses(presses)
    s1, s2 = [], {}
    bus.snd.on_sample = lambda v: s1.append((bus.snd.ticks, v))
    if bus.ecs is not None:
        p2 = bus.ecs.psg

        def on2(v):
            s2[p2.ticks] = v
        p2.on_sample = on2
    bus.vid.keep_frames = set()
    isys.run_pictures(bus, cpu, a.frames, mclk)
    on = bus.ecs is not None and bus.ecs.on
    if on:
        bus.ecs.psg.advance(bus._t(cpu.cycle) - 1)
    pk1 = max((v for _, v in s1), default=0)
    pk2 = max(s2.values(), default=0)
    sums = [v + s2.get(t, 0) for t, v in s1]
    pks = max(sums, default=0)
    clip = sum(1 for t, v in s1 if mix(v, s2.get(t, 0), on) >= CEIL)
    clip_raw = sum(1 for x in sums if x > CEIL)
    print("ECS %s; %d frames, %d samples: peaks PSG #1 %d, PSG #2 %d, sum %d (unscaled: %d samples over "
          "32,767); the mix%s: peak %d, %d samples at 32,767" % (
              "on" if on else "off", a.frames, len(s1), pk1, pk2, pks, clip_raw,
              " (3/4)" if on else "", max((mix(v, s2.get(t, 0), on) for t, v in s1), default=0), clip))
    ok = clip == 0 and pks >= a.want_sum
    if pks < a.want_sum:
        print("the sum's peak %d is under --want-sum %d: the run missed the loud passage" % (pks, a.want_sum))
    print("ECS_MIX %s" % ("pass" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
