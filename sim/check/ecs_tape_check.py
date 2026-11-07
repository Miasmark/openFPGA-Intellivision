#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""ecs_tape_check: the ECS cassette with a real game's save and load, in the system model
(tools/intv_system.py, mode stic; the tape is tools/ecs_tape.py). Too long for the RTL benches
(a 1,792-byte save is about 2,000 frames), so the RTL's side is tb_tape (the engine on scripts)
and tb_system's ecstape play run (ECS BASIC, short saves).

  ecs_tape_check.py OUTDIR [--wsmlb IMAGE]

  wsmlb  World Series Major League Baseball (the image, a zip from the user's library):
         run 1: RTN (2 players), 1 (the scoreboard menu), C (the cassette menu), SHIFT+K (Keep
         Game: "REWIND tape / Press RECORD / Press RETURN"), RTN: the save (its ECS RAM, one
         block, no BASIC name); run 2, a fresh game with run 1's tape: RTN, 1, C, SHIFT+O (Old
         Game), RTN: the load. The ECS RAM the block holds must be the same after the load as
         when the save started, and both runs must end on "Done".
It prints one line a case and ECS_TAPE pass / FAIL, and keeps a few pictures in OUTDIR (pictures
of the user's games: keep OUTDIR outside any repository).
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "mapper"),
                os.path.join(ROOT, "sim", "check")]
import ecs_tape  # noqa: E402
from ecs_osk_check import save  # noqa: E402

KEEP = "300-306:ecs:RTN,600-606:ecs:1,800-806:ecs:C,1100-1106:ecs:SHIFT+K,1400-1406:ecs:RTN"
OLD = "300-306:ecs:RTN,600-606:ecs:1,800-806:ecs:C,1100-1106:ecs:SHIFT+O,1400-1406:ecs:RTN"


def run(cart, presses, frames, out, name, tape=None):
    import intv_system as isys
    bus, cpu, _ = isys.system_for("stic", None, cart, ecs=("auto", None))
    bus.presses = isys.parse_presses(presses)
    tp = bus.ecs.tape
    if tape is not None:
        tp.load_file(tape)
    st = dict(motor=[], at_rec=None)
    mode = tp._mode

    def spy(m, c):
        st["motor"].append((bus.vid.last_drawn, m))
        if m == 0x39:
            st["at_rec"] = list(bus.ecs.ram)
        mode(m, c)
    tp._mode = spy
    last = {}

    def grab(n, pic, info):
        if n == frames - 1:
            last["pic"] = list(pic)
            save(os.path.join(out, "%s_%d.png" % (name, n)), pic)
    bus.vid.keep_frames = set()
    bus.vid.on_frame = grab
    while bus.vid.last_drawn < frames:
        cpu.step()
        bus.boundary(cpu.cycle)
    return tp, st, list(bus.ecs.ram), last.get("pic")


def wsmlb(cart, out):
    tp1, st1, _, pic1 = run(cart, KEEP, 4400, out, "wsmlb_keep")
    bl = ecs_tape.blocks(tp1.t)
    probs = []
    if len(bl) != 1 or st1["at_rec"] is None:
        return ["Keep Game: %d blocks on the tape, record %s" % (len(bl), "seen" if st1["at_rec"] else "not seen")]
    o, k, n, ln = bl[0]
    if ecs_tape.basic_name(ecs_tape.name_of(tp1.t, o, k, n)):
        probs.append("Keep Game: its block reads as a BASIC name")
    tp2, st2, ram2, pic2 = run(cart, OLD, 4400, out, "wsmlb_old", tape=tp1.file())
    lo, hi = 0x100, min(0x100 + n, 0x800)            # the block: ECS RAM from $4100
    a = st1["at_rec"]
    diff = [i for i in range(lo, hi) if a[i] != ram2[i]]
    if diff:
        probs.append("Old Game: %d of %d ECS RAM cells differ from the save, first $%04X" % (len(diff), hi - lo, 0x4000 + diff[0]))
    import stic as sticm                              # the bottom quarter: "Done" in both
    w, h = sticm.W, sticm.H
    if pic1 is None or pic2 is None or pic1[w * (3 * h // 4):] != pic2[w * (3 * h // 4):] \
            or len(set(pic1[w * (3 * h // 4):])) < 2:
        probs.append("Keep Game and Old Game do not both end on Done (the pictures' bottom quarter)")
    loads = [f for f, m in st2["motor"] if m == 0x1D]
    print("wsmlb  Keep Game: one block of %d bytes (%d frames); Old Game: motor on at %s, %d of %d cells "
          "back %s" % (n, next((f for f, m in st1["motor"] if m == 0), 0) - next((f for f, m in st1["motor"] if m == 0x39), 0),
                       loads[:1], hi - lo - len(diff), hi - lo, "pass" if not probs else "FAIL"), flush=True)
    return probs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("--wsmlb", help="World Series Major League Baseball image")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    probs = []
    if a.wsmlb:
        probs += wsmlb(a.wsmlb, a.out)
    for p in probs:
        print("  FAIL " + p)
    print("ECS_TAPE %s" % ("pass" if not probs else "FAIL"))
    return 0 if not probs else 1


if __name__ == "__main__":
    sys.exit(main())
