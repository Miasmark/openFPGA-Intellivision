#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""ecs_osk_check: typing on the on-screen ECS keyboard (tools/osk.py Keyboard, 1.0.4) gives the
game exactly what typing on the ECS keyboard does, in the system model (tools/intv_system.py,
mode stic).

  ecs_osk_check.py OUTDIR [--snfl IMAGE] [--frames-basic N] [--frames-snfl N]

Each case runs twice: once with the keys pressed straight into the ECS matrix ("ecs:" presses,
tools/ecs.py type_presses, each key held 6 frames and 20 apart), once with only Pocket buttons
("pocket:" presses): Start opens the keyboard, D-pad presses walk the cursor to each key in the
gap (the shortest walk, found on the model), A is held over exactly the frames the first run
held the key, Y with it for a shifted character. Every picture of the two runs must be the same.
  basic   no cartridge, ECS on: the ECS menu (1: ECS BASIC), then 10 PRIN 2*3 / RUN: 6.00 (the
          print keyword is PRIN; PRINT reads as PRIN T..., T unset: 0.00, as in MAME)
  snfl    Super NFL Football (prototype), ECS on Auto (the table's flag): RTN at its title, then
          DEMO and RTN in its menu (the demonstration starts)
It prints one line a case and ECS_OSK pass / FAIL, and keeps the pictures at a few frames of the
keyboard run in OUTDIR (pictures of the user's games: keep OUTDIR outside any repository).
"""
import argparse
import collections
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "mapper")]
import ecs as ecsm  # noqa: E402
import osk  # noqa: E402

HOLD, GAP = 6, 20
VIEW = [(0, 0, 0), (0, 45, 255), (255, 61, 16), (201, 207, 171), (56, 107, 63), (0, 167, 86),
        (250, 234, 80), (255, 252, 255), (189, 172, 200), (36, 184, 255), (255, 180, 31),
        (84, 110, 0), (255, 78, 87), (164, 150, 255), (117, 204, 128), (181, 26, 88)]


def walk(src, dst):
    """The shortest list of D-pad buttons that takes the keyboard's cursor from (r, c) src to a
    position on cell dst (breadth first over the model's own moves)."""
    T = 1 << 28
    seen, q = {src: []}, collections.deque([src])
    while q:
        rc = q.popleft()
        if osk.kb_cell(*rc) == dst:
            return rc, seen[rc]
        for d in (osk.UP, osk.DOWN, osk.LEFT, osk.RIGHT):
            kb = osk.Keyboard()
            kb.open, (kb.r, kb.c) = 1, rc
            kb.step(T | 1 << d, True, False)
            if (kb.r, kb.c) not in seen:
                seen[(kb.r, kb.c)] = seen[rc] + [d]
                q.append((kb.r, kb.c))
    raise SystemExit("no walk to cell %d" % dst)


def osk_presses(ecs_text, open_at):
    """ecs_text: type_presses' text ("F1-F2:ecs:K1+K2,..."). -> the same keys as Pocket presses:
    Start at open_at, then per key the walk in the gap before it and A (+ Y) over F1-F2."""
    names = {osk.UP: "up", osk.DOWN: "down", osk.LEFT: "left", osk.RIGHT: "right"}
    out = ["%d-%d:pocket:start" % (open_at, open_at + 1)]
    rc, t = osk.KB_START, open_at + 2
    for p in ecs_text.split(","):
        fr, keys = p.split(":ecs:")
        f1, f2 = (int(x) for x in fr.split("-"))
        keys = keys.split("+")
        key = [k for k in keys if k != "SHIFT"][0]
        rc, moves = walk(rc, osk.KB_CELLS.index(key))
        if t + 2 * len(moves) > f1:
            raise SystemExit("no room to walk to %s before frame %d" % (key, f1))
        for d in moves:
            out.append("%d-%d:pocket:%s" % (t, t + 1, names[d]))
            t += 2
        out.append("%d-%d:pocket:%s" % (f1, f2, "A+Y" if "SHIFT" in keys else "A"))
        t = f2
    return ",".join(out)


def run(cart, ovr, presses, frames, keep=()):
    import intv_system as isys
    bus, cpu, _ = isys.system_for("stic", None, cart, ecs=(ovr, None))
    bus.presses = isys.parse_presses(presses)
    hashes, pics = [], {}

    def grab(n, pic, info):
        hashes.append(hashlib.sha1(bytes(pic)).hexdigest())
        if n in keep:
            pics[n] = list(pic)
    bus.vid.keep_frames = set()
    bus.vid.on_frame = grab
    while bus.vid.last_drawn < frames:
        cpu.step()
        bus.boundary(cpu.cycle)
    return hashes, pics


def save(path, pic):
    from PIL import Image
    import stic as sticm
    im = Image.new("RGB", (sticm.W, sticm.H))
    im.putdata([VIEW[v & 15] for v in pic])
    im.save(path)


def case(name, cart, ovr, lead, text_at, text, frames, out, open_at):
    typed, end = ecsm.type_presses(text_at, text, HOLD, GAP)
    if end + 60 > frames:
        raise SystemExit("%s: %d frames are too few (typing ends at %d)" % (name, frames, end))
    direct = ",".join(filter(None, (lead, typed)))
    onscreen = ",".join(filter(None, (lead, osk_presses(typed, open_at))))
    keep = (text_at, (text_at + end) // 2, end, frames)
    h1, _ = run(cart, ovr, direct, frames)
    h2, pics = run(cart, ovr, onscreen, frames, keep)
    for n, pic in pics.items():
        save(os.path.join(out, "%s_%d.png" % (name, n)), pic)
    diff = [i for i, (a, b) in enumerate(zip(h1, h2)) if a != b]
    ok = len(h1) == len(h2) and not diff
    changed = len(set(h1[text_at:]))
    print("%-6s %d frames, %d distinct pictures after the typing starts: %s" % (
        name, len(h1), changed, "the same" if ok else "%d differ, first %s" % (len(diff), diff[:1])), flush=True)
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("--snfl", help="Super NFL Football (prototype) image")
    ap.add_argument("--frames-basic", type=int, default=1500)
    ap.add_argument("--frames-snfl", type=int, default=1300)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    ok = case("basic", None, "on", "300-306:Enter,420-426:1,500-506:Enter", 800, "10 PRIN 2*3\nRUN\n",
              a.frames_basic, a.out, 600)
    if a.snfl:
        ok &= case("snfl", a.snfl, "auto", "", 400, "\nDEMO\n", a.frames_snfl, a.out, 300)
    print("ECS_OSK %s" % ("pass" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
