#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""ecs_ref_compare: the system model against one MAME reference run of
tools/refs/mame_ecs_trace.sh (build step 9): every instruction, register,
flag and bus access of the trace (tools/intv_system.py mame_compare, with
the run's held keys and the ECS as MAME has it), and every snapshot the run
took against the model's picture (snapshot N = model picture N - 1,
tools/stic_frames.py), pixel for pixel.

  python3 -I tools/refs/ecs_ref_compare.py --run DIR --name NAME [--cart IMG] [--cfg CFG]
        [--presses TEXT|@FILE] [--ecs on|off] [--snaps N,N...] [--voice-replay] [--synth]
        [--timing computed|trace]
        --mame-src MAME_SOURCE_TREE

DIR holds trace.log and snap/<system>/*.png (in frame order: --snaps
names their frame notifiers). Prints ECS_REF pass / FAIL NAME. The run's
files come from game data and the owner's ROMs: keep DIR outside the
repository; nothing is written here.
"""
import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import intv_system as isys  # noqa: E402
import stic_frames as sf  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--cart")
    ap.add_argument("--cfg")
    ap.add_argument("--presses", default="")
    ap.add_argument("--ecs", choices=("on", "off", "auto"), default="on",
                    help="on: MAME's intvecs; auto: the model's Auto rule against MAME's plain intv "
                         "(an attached ECS with its ROMs paged out must look like none)")
    ap.add_argument("--snaps", default="")
    ap.add_argument("--voice-replay", action="store_true")
    ap.add_argument("--synth", action="store_true", help="the music synthesizer on the ECS port")
    ap.add_argument("--timing", choices=("trace", "computed"), default="computed",
                    help="frame timing (tools/intv_system.py mame): computed = MAME's 59.92 Hz, its "
                         "bus-copy window by instruction start (default; the trace's frame numbers are "
                         "checked against it)")
    ap.add_argument("--mame-src", required=True)
    ap.add_argument("--bios-dir")
    a = ap.parse_args()
    presses = a.presses
    if presses.startswith("@"):
        presses = open(presses[1:]).read().strip()
    snaps = sf.parse_list(a.snaps)
    pngs = sorted(glob.glob(os.path.join(a.run, "snap", "*", "*.png")))
    if len(pngs) != len(snaps):
        print("ECS_REF FAIL %s: %d snapshots, --snaps names %d" % (a.name, len(pngs), len(snaps)))
        return 1
    pal = sf.mame_palette(os.path.join(a.mame_src, "src", "mame", "mattel", "intv.cpp"))
    want = {n - 1: sf.import_snap(p, pal) for n, p in zip(snaps, pngs)}
    got = {}

    def on_bus(bus):
        if bus.ecs is not None:
            bus.ecs.synth = a.synth

        def grab(n, pic, info):
            if n in want:
                got[n] = pic
        bus.vid.keep_frames = set()
        bus.vid.on_frame = grab

    ok = isys.mame_compare(os.path.join(a.run, "trace.log"), a.bios_dir, a.cart, on_bus=on_bus,
                           ecs=(a.ecs, None) if a.ecs != "off" else None, presses=presses,
                           voice_replay=a.voice_replay, cfg_path=a.cfg, timing=a.timing)
    for n in sorted(want):
        if n not in got:
            print("snapshot %d: the model drew no picture %d" % (n + 1, n))
            ok = False
            continue
        bad = [i for i in range(len(want[n])) if want[n][i] != got[n][i]]
        print("snapshot %d / picture %d: %s%s" % (n + 1, n, "match" if not bad else "DIFFER, %d pixels" % len(bad),
                                                  "" if not bad else ", first x=%d y=%d" % (bad[0] % 189, bad[0] // 189)))
        ok = ok and not bad
    print("ECS_REF %s %s: trace and %d snapshots" % ("pass" if ok else "FAIL", a.name, len(want)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
