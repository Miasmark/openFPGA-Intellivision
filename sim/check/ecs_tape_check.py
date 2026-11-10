#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""ecs_tape_check: the ECS cassette with ECS BASIC and real games' saves and loads, in the system
model (tools/intv_system.py, mode stic; the tape is tools/ecs_tape.py), at Tape speed Normal and
Instant (1.0.6; intv_system._tape_patch). Too long for the RTL benches (a 1,792-byte save is about
2,000 frames at Normal), so the RTL's side is tb_tape (the engine on scripts) and tb_system's
ecstape play runs (ECS BASIC, short saves, both speeds).

  ecs_tape_check.py OUTDIR [--basic] [--wsmlb IMAGE] [--gf IMAGE]

Every case runs at Normal and at Instant. Instant lets the ECS ROM's own tape routine run again at
once inside the frame, so its effects must be the same; only the frames differ. Compared exactly:
the tape (every byte), the head and the motor / record mode, the whole ECS RAM (the routine's
control block $4070-$4084 included; ECS BASIC's program and WSMLB's game live there), $015E /
$015F (the routine's busy, mode and error flags) and, for Game Factory, its cartridge RAM. The
other RAM (frame counters, the cursor, the stack's leftovers) runs on frames, so it is listed,
not compared.

  basic  no cartridge, ECS on: the ECS menu (1: ECS BASIC); 10 PRIN 1, CSAV AAA (SET and GO: the
         hand controller's Enter), NEW, 10 PRIN 22, CSAV BBB, NEW, CLOD AAA past BBB, RUN, CLOD
         BBB, RUN (tb_system's ecstape plan), then CVER BBB (verify), then CLOD ZZZ (no such
         name: every block read, then the routine waits at the tape's end)
  wsmlb  World Series Major League Baseball: run 1: RTN (2 players), 1 (the scoreboard menu), C
         (the cassette menu), SHIFT+K (Keep Game), RTN: the save (its ECS RAM, one block, no BASIC
         name); run 2, a fresh game with run 1's tape: RTN, 1, C, SHIFT+O (Old Game), RTN: the
         load. The ECS RAM the block holds must be the same after the load as when the save
         started, and both runs must end on "Done".
  gf     Game Factory (prototype): RTN (the title), 4 (LOAD/STORE GAME), RTN, 2 (STORE), RTN,
         then RTN at each of its two prompts: one save of two blocks back to back (ECS RAM
         $4085-$47C8, then cartridge RAM $8800-$8B0C; docs/ECS_NOTES.md 5); then a fresh game
         with that tape: RTN, 4, RTN, 1 (LOAD), RTN, RTN, RTN: both blocks back, in order.
It prints one line a case and ECS_TAPE pass / FAIL, and keeps a few pictures in OUTDIR (pictures
of the user's games: keep OUTDIR outside any repository).
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "mapper"),
                os.path.join(ROOT, "sim", "check"), os.path.join(ROOT, "sim", "tb")]
import ecs_tape  # noqa: E402
from ecs_osk_check import save  # noqa: E402

KEEP = "300-306:ecs:RTN,600-606:ecs:1,800-806:ecs:C,1100-1106:ecs:SHIFT+K,1400-1406:ecs:RTN"
OLD = "300-306:ecs:RTN,600-606:ecs:1,800-806:ecs:C,1100-1106:ecs:SHIFT+O,1400-1406:ecs:RTN"
GF_MENU = "300-306:ecs:RTN,700-706:ecs:4,800-806:ecs:RTN,"
GF_STORE = GF_MENU + "1000-1006:ecs:2,1100-1106:ecs:RTN,1300-1306:ecs:RTN,1500-1506:ecs:RTN"
GF_LOAD = GF_MENU + "1000-1006:ecs:1,1100-1106:ecs:RTN,1300-1306:ecs:RTN,1500-1506:ecs:RTN"
GF_RAM = range(0x8800, 0x8B0D)                      # Game Factory's cartridge RAM block


class Run:
    """One model run: the tape's E2 writes, the RAM at the first record start, the end state."""

    def __init__(self, cart, presses, frames, out, name, instant, tape=None, cart_ram=()):
        import intv_system as isys
        bus, cpu, _ = isys.system_for("stic", None, cart, ecs=("auto", None))
        bus.ecs.instant = instant
        bus.presses = isys.parse_presses(presses)
        tp = bus.ecs.tape
        if tape is not None:
            tp.load_file(tape)
        self.motor, self.at_rec = [], None
        mode = tp._mode

        def spy(m, c):
            self.motor.append((bus.vid.last_drawn, m))
            if m == 0x39 and self.at_rec is None:
                self.at_rec = (list(bus.ecs.ram), [bus.cart.read(a) for a in cart_ram])
            mode(m, c)
        tp._mode = spy
        self.pic = None

        def grab(n, pic, info):
            if n == frames - 1:
                self.pic = list(pic)
                save(os.path.join(out, "%s_%s_%d.png" % (name, "instant" if instant else "normal", n)), pic)
        bus.vid.keep_frames = set()
        bus.vid.on_frame = grab
        while bus.vid.last_drawn < frames:
            cpu.step()
            bus.boundary(cpu.cycle)
        self.tape, self.head, self.mode = tp.file(), tp.head, tp.mode
        self.eram = list(bus.ecs.ram)
        self.flags = list(bus.scratch[0x5E:0x60])
        self.cart_ram = [bus.cart.read(a) for a in cart_ram]
        self.other = list(bus.scratch) + list(bus.sysram)

    def busy_frames(self):
        """Frames from each motor start to its stop."""
        out, on = [], None
        for f, m in self.motor:
            if m & 0x10 and on is None:
                on = f
            elif not m & 0x10 and on is not None:
                out.append(f - on)
                on = None
        return out


def same(n, i, what):
    """The exact comparisons of a Normal and an Instant run."""
    probs = []
    if n.tape != i.tape:
        k = next(x for x in range(len(n.tape)) if n.tape[x] != i.tape[x])
        probs.append("%s: the tapes differ (first at byte %d)" % (what, k))
    if (n.head, n.mode) != (i.head, i.mode):
        probs.append("%s: head / mode Normal %s, Instant %s" % (what, (n.head, n.mode), (i.head, i.mode)))
    d = [x for x in range(len(n.eram)) if n.eram[x] != i.eram[x]]
    if d:
        probs.append("%s: %d ECS RAM cells differ, first $%04X" % (what, len(d), 0x4000 + d[0]))
    if n.flags != i.flags:
        probs.append("%s: $015E / $015F Normal %s, Instant %s" % (what, n.flags, i.flags))
    if n.cart_ram != i.cart_ram:
        probs.append("%s: the cartridge RAM differs" % what)
    return probs


def other_diff(n, i):
    d = [x for x in range(len(n.other)) if n.other[x] != i.other[x]]
    return ["$%04X" % (0x100 + x if x < 256 else 0x200 + x - 256) for x in d]


def report(name, n, i, probs, extra=""):
    print("%-6s Normal %s frames, Instant %s; frame-driven RAM that differs: %s%s %s" % (
        name, n.busy_frames(), i.busy_frames(), other_diff(n, i)[:12] or "none", extra,
        "pass" if not probs else "FAIL"), flush=True)
    for p in probs:
        print("  FAIL " + p)
    return probs


def basic(out):
    import tb_system as tbs
    import ecs as ecsm
    presses, t = tbs._tape_basic()
    more = []

    def typ(text, after):
        nonlocal t
        p, end = ecsm.type_presses(t, text)
        more.append(p)
        t = end + after

    def key(after):
        nonlocal t
        more.append("%d-%d:Enter" % (t, t + 6))
        t += 6 + after
    typ("CVER BBB\n", 100)
    key(100)
    key(300)
    typ("CLOD ZZZ\n", 100)
    key(100)
    key(400)                          # every block read; the routine then waits at the tape's end
    presses = presses + "," + ",".join(more)
    n = Run(None, presses, t, out, "basic", False)
    i = Run(None, presses, t, out, "basic", True)
    probs = same(n, i, "basic")
    if n.mode != 0x1D or n.head != ecs_tape.tape_end(n.tape) or (n.flags[0] & 8) == 0:
        probs.append("basic: CLOD ZZZ should end waiting at the tape's end (motor on, busy): mode %02X, "
                     "head %d of %d, $015E %02X" % (n.mode, n.head, ecs_tape.tape_end(n.tape), n.flags[0]))
    if n.flags[1] & 0x10:
        probs.append("basic: CVER BBB set the error flag")
    return report("basic", n, i, probs)


def wsmlb(cart, out):
    probs = []
    keep = [Run(cart, KEEP, 4400, out, "wsmlb_keep", x) for x in (False, True)]
    probs += same(keep[0], keep[1], "Keep Game")
    tape = keep[0].tape
    bl = ecs_tape.blocks(tape)
    if len(bl) != 1 or keep[0].at_rec is None:
        return report("wsmlb", keep[0], keep[1], probs + ["Keep Game: %d blocks" % len(bl)])
    o, k, n, ln = bl[0]
    if ecs_tape.basic_name(ecs_tape.name_of(tape, o, k, n)):
        probs.append("Keep Game: its block reads as a BASIC name")
    old = [Run(cart, OLD, 4400, out, "wsmlb_old", x, tape=tape) for x in (False, True)]
    probs += same(old[0], old[1], "Old Game")
    lo, hi = 0x100, min(0x100 + n, 0x800)            # the block: ECS RAM from $4100
    a = keep[0].at_rec[0]
    for r, what in ((old[0], "Normal"), (old[1], "Instant")):
        diff = [x for x in range(lo, hi) if a[x] != r.eram[x]]
        if diff:
            probs.append("Old Game (%s): %d of %d ECS RAM cells differ from the save, first $%04X"
                         % (what, len(diff), hi - lo, 0x4000 + diff[0]))
    import stic as sticm                              # the bottom quarter: "Done" in both
    w, h = sticm.W, sticm.H
    for r, what in ((keep[1], "Keep Game"), (old[0], "Old Game Normal"), (old[1], "Old Game Instant")):
        if r.pic is None or r.pic[w * (3 * h // 4):] != keep[0].pic[w * (3 * h // 4):]:
            probs.append("%s does not end on Done" % what)
    report("wsmlb", keep[0], keep[1], [], " (Keep Game)")
    return report("wsmlb", old[0], old[1], probs, " (Old Game)")


def gf(cart, out):
    probs = []
    store = [Run(cart, GF_STORE, 4700, out, "gf_store", x, cart_ram=GF_RAM) for x in (False, True)]
    probs += same(store[0], store[1], "STORE")
    tape = store[0].tape
    bl = ecs_tape.blocks(tape)
    if [b[2] for b in bl] != [0x47C8 - 0x4085, 0x8B0C - 0x8800] or store[0].at_rec is None:
        return report("gf", store[0], store[1], probs + ["STORE: blocks %s, want 1,859 then 780 bytes"
                                                          % [b[2] for b in bl]])
    load = [Run(cart, GF_LOAD, 4500, out, "gf_load", x, tape=tape, cart_ram=GF_RAM) for x in (False, True)]
    probs += same(load[0], load[1], "LOAD")
    eram, cram = store[0].at_rec
    for r, what in ((load[0], "Normal"), (load[1], "Instant")):
        d = [x for x in range(0x85, 0x7C8) if eram[x] != r.eram[x]]
        if d:
            probs.append("LOAD (%s): %d ECS RAM cells differ from the store, first $%04X" % (what, len(d), 0x4000 + d[0]))
        if [v & 0xFF for v in cram] != [v & 0xFF for v in r.cart_ram]:
            probs.append("LOAD (%s): the cartridge RAM differs from the store" % what)
    report("gf", store[0], store[1], [], " (STORE)")
    return report("gf", load[0], load[1], probs, " (LOAD)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("--basic", action="store_true")
    ap.add_argument("--wsmlb", help="World Series Major League Baseball image")
    ap.add_argument("--gf", help="Game Factory (prototype) image")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    probs = []
    if a.basic:
        probs += basic(a.out)
    if a.wsmlb:
        probs += wsmlb(a.wsmlb, a.out)
    if a.gf:
        probs += gf(a.gf, a.out)
    print("ECS_TAPE %s" % ("pass" if not probs else "FAIL"))
    return 0 if not probs else 1


if __name__ == "__main__":
    sys.exit(main())
