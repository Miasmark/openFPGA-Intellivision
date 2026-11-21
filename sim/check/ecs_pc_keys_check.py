#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""ecs_pc_keys_check: typing on a USB keyboard by its PC legends (2026-11-21: = + - / ? ' " ` and
Alt+5 / Alt+6 on the keys the positional map leaves free, tools/intv_input.py PC_KEYS, ALT_KEYS)
gives ECS BASIC what typing the same characters on the ECS keyboard does, in the system model
(tools/intv_system.py, mode stic) with the owner's ECS ROM.

  ecs_pc_keys_check.py [--frames N] [--show]      (INTV_BIOS_DIR: exec.bin, grom.bin, ECS.bin)

The program below is typed twice: once straight into the ECS matrix (tools/ecs.py type_presses,
the ECS's own SHIFT combinations), once as USB keyboard reports frame by frame (PC keys, the
PC's Shift held over the shifted characters and let go first on every other one, some keys rolled
over the next) through the input model's USB keyboard (UsbKeys, the RTL's rounds: 29,868 a frame,
each report changing at a random point of its frame; the matrix is taken at each frame's start,
where the ECS ROM's scan runs). Both runs must end on the same screen (BACKTAB as text), and the
screen must show the RUN's output. It prints the screen and ECS_PC_KEYS pass / FAIL.
"""
import argparse
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "mapper")]
import ecs as ecsm  # noqa: E402
import intv_input as inm  # noqa: E402

# ECS BASIC's print keyword is PRIN (PRINT reads as PRIN T: tools/../ecs_osk_check.py)
PROGRAM = '10 A=5-1\n20 B=A*2+1\n30 PRIN A\n40 PRIN B\n50 PRIN 10/4\n60 PRIN "HI"\n70 C=8/2-1\n80 PRIN C\nRUN\n'
WANT = ["4.00", "9.00", "2.50", "HI", "3.00"]
ROUNDS = 14934 * 16 // 8                # rounds of 8 clk_sys a frame
LEAD = "300-306:Enter,420-426:1,500-506:Enter"     # the ECS menu: 1, ECS BASIC
START, STEP, HOLD = 800, 16, 7

# US PC keyboard: character -> (HID usage, modifiers: S Shift, A Alt)
PC = {" ": (0x2C, ""), "\n": (0x28, ""), ",": (0x36, ""), ".": (0x37, ""), ";": (0x33, ""), ":": (0x33, "S"),
      "=": (0x2E, ""), "+": (0x2E, "S"), "-": (0x2D, ""), "/": (0x38, ""), "?": (0x38, "S"), "'": (0x34, ""),
      '"': (0x34, "S"), "*": (0x25, "S"), "(": (0x26, "S"), ")": (0x27, "S"), "%": (0x22, "A"), "^": (0x23, "A")}
for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    PC[ch] = (0x04 + i, "")
for i, ch in enumerate("1234567890"):
    PC[ch] = (0x1E + i, "")


def usb_reports(text, start):
    """text typed on the PC keyboard -> {frame: (codes, modifier byte)}, frames start .. end; each key
    held HOLD frames, STEP apart; a key after '=' or '-' goes down before that one is let go (rolled
    over); the Shift of every other shifted character is let go before its key."""
    keys = {}                               # frame -> set of codes; mods -> frame -> byte
    mods = {}
    f = start
    nsh = 0
    for i, ch in enumerate(text):
        code, m = PC[ch]
        down, up = f, f + HOLD
        if i > 0 and text[i - 1] in "=-" and ch not in "\n":
            down = f - STEP + HOLD - 3          # rolled over the '=' or '-' before (held until f - STEP + HOLD)
        for k in range(down, up):
            keys.setdefault(k, []).append(code)
        if m:
            bit = 0x02 if m == "S" else 0x04
            nsh += 1
            m_up = up - 2 if nsh % 2 else up + 2   # every other one: the modifier let go first
            for k in range(down - 2, m_up):
                mods[k] = mods.get(k, 0) | bit
        f += STEP
    return {k: (keys.get(k, []), mods.get(k, 0)) for k in range(start - 4, f + 4)}, f


def usb_presses(reports, seed=1):
    """The ECS matrix frame by frame from the reports through UsbKeys -> parse_presses-style list."""
    rng = random.Random(seed)
    u = inm.UsbKeys()
    base = dict(key1=0, joy1=0x80808080, key2=0, joy2=0x80808080, mode=0, swap=0, ecs=inm.ECS_ON)

    def v_of(codes, mb):
        cs = (list(codes) + [0] * 6)[:6]
        return dict(base, key3=(4 << 28) | mb << 8, joy3=cs[0] | cs[1] << 8 | cs[2] << 16 | cs[3] << 24,
                    trig3=cs[4] | cs[5] << 8)
    out, prev = [], v_of([], 0)
    first, last = min(reports), max(reports)
    seen = []
    for k in range(first, last + 1):
        # frame k: the matrix at its start (the ECS ROM's scan), then the report of frame k comes at a
        # random point of it
        bits = u.keys()
        seen.append((k, bits))
        cur = v_of(*reports[k])
        ph = rng.randrange(ROUNDS)
        u.advance(prev, True, ph)
        u.advance(cur, True, ROUNDS - ph)
        prev = cur
    run = None
    for k, bits in seen:
        if run and run[2] == bits and run[1] == k:
            run[1] = k + 1
        else:
            if run and run[2]:
                out.append((run[0], run[1], ("ecs", run[2])))
            run = [k, k + 1, bits]
    if run and run[2]:
        out.append((run[0], run[1], ("ecs", run[2])))
    return out


def screen(bus):
    rows = []
    for r in range(12):
        s = ""
        for c in range(20):
            w = bus.sysram[20 * r + c]
            card = (w >> 3) & 0xFF
            s += chr(card + 0x20) if not (w & 0x800) and 0 <= card < 0x5F else "~"
        rows.append(s)
    return rows


def run(presses, frames):
    import intv_system as isys
    bus, cpu, _ = isys.system_for("stic", None, None, ecs=("on", None))
    p = isys.parse_presses(LEAD)
    p.extend(presses)
    bus.presses = p
    bus.vid.keep_frames = set()
    while bus.vid.last_drawn < frames:
        cpu.step()
        bus.boundary(cpu.cycle)
    return screen(bus)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--frames", type=int, default=0, help="frames to run (default: the typing's end + 300)")
    ap.add_argument("--show", action="store_true", help="print both screens")
    a = ap.parse_args()
    import intv_system as isys
    reports, end = usb_reports(PROGRAM, START)
    frames = a.frames or end + 300
    typed, end2 = ecsm.type_presses(START, PROGRAM, HOLD, STEP - HOLD)
    s1 = run(list(isys.parse_presses(typed)), frames)
    s2 = run(usb_presses(reports), frames)
    for name, s in (("ECS keys", s1), ("USB keys", s2)) if a.show else (("USB keys", s2),):
        print("-- %s" % name)
        print("\n".join("   |%s|" % r for r in s))
    text = "\n".join(s2)
    ok = s1 == s2 and all(w in text for w in WANT)
    print("  %s screens %s, output %s" % ("ok  " if ok else "FAIL", "the same" if s1 == s2 else "differ",
                                         " ".join(WANT) + (" shown" if all(w in text for w in WANT) else " missing")))
    print("ECS_PC_KEYS %s" % ("pass" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
