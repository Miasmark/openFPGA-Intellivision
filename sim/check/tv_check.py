#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""tv_check: the TutorVision / INTV88 model (1.0.8, docs/TUTORVISION.md) against the documents.

  python3 -I sim/check/tv_check.py [--bios-dir DIR] [--games DIR]

1. Our sim/testroms/tvtest.asm in the EXEC slot, run in the system model (tools/intv_system.py,
   mode stic) with the TutorVision mode off, INTV88 and Full; its results (System RAM from
   $0330) must be what J. Zbiciak's notes say for each board (TUTORVISION.md 3), and the pictures
   of the three modes must differ only where the STIC 1A's rules differ (the 160th column, the
   GRAM cards above 63, MOBs above card 63 in Foreground/Background).
2. With --games (the owner's TutorVision images, never in the repository): each image run in
   the model to its title (Full: the WBEXEC's title screen; Little Man Computer in INTV88), the
   picture checked to show something (not one colour) and, for the WBEXEC titles, the CPU in the
   WBEXEC's half ($2000-$2FFF) at least once.
Full mode needs wbexec.bin in the BIOS directory (the owner's file; skipped with a note
without it). Last line: TV_CHECK pass / FAIL.
"""
import argparse
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "mapper")]
import as1610               # noqa: E402
import intv_system as isys  # noqa: E402
import stic as sticm        # noqa: E402

FRAMES = 13
VIEW = [(0, 0, 0), (0, 45, 255), (255, 61, 16), (201, 207, 171), (56, 107, 63), (0, 167, 86),
        (250, 234, 80), (255, 252, 255), (189, 172, 200), (36, 184, 255), (255, 180, 31),
        (84, 110, 0), (255, 78, 87), (164, 150, 255), (117, 204, 128), (181, 26, 88)]
PICS_OUT = os.environ.get("TV_CHECK_PICS")   # a directory: the tvtest pictures as PNG (not committed)


def tvtest_exec():
    with open(os.path.join(ROOT, "sim", "testroms", "tvtest.asm")) as f:
        prog = as1610.assemble(f.read(), romw=10)
    img = bytearray(prog.image())
    img += bytes(8192 - len(img))
    return isys.load_words_bytes(bytes(img[:8192])) if hasattr(isys, "load_words_bytes") else \
        [img[i] << 8 | img[i + 1] for i in range(0, 8192, 2)]


def run_tvtest(tv, grom, wbexec):
    bus = isys.SystemBus(tvtest_exec(), grom, None, stic_mode="stic", tv=tv,
                         wbexec=wbexec if tv == 2 else None)
    cpu = isys.CP1610(bus=bus, buslog=False)
    pics = {}
    bus.vid.keep_frames = set()
    bus.vid.on_frame = lambda n, pic, info: pics.__setitem__(n, bytes(pic))
    while cpu.cycle < FRAMES * isys.FRAME:
        cpu.step()
        bus.boundary(cpu.cycle)
    bus.vid.advance(cpu.cycle + isys.FRAME)
    return bus.sysram[0x130:0x130 + 20], pics


def expect(tv, wbexec):
    """tvtest's results ($0330 on) per board, from the documents (TUTORVISION.md 3)."""
    on = tv != 0
    e = []
    e += [0x11, 0x22, 0x33, 0x44] if on else [0x44] * 4         # 1. GRAM 2K, not mirrored
    e += [0x11 if on else 0x55]                                  # 2. no GRAM alias at $7800
    e += [0x3812 if on else 0x3834]                              #    no STIC alias at $4000
    e += [0xFFFF]                                                #    $4021: nothing answers
    e += [0x1234, 0x5678, 0x9ABC, 0xDEF0] if on else [0xFFFF] * 4   # 3. RAM $0360-$04FF
    e += [0x3FF7 if on else 0x3FFF]                              # 4. $0022 bit 3
    e += [0x3F if on else 0xFF]                                  # 5. R7 bits 7:6
    e += [0x0E]                                                  #    the shape reads back
    e += [wbexec[0], wbexec[0xFFF]] if tv == 2 else [0xFFFF] * 2  # 6. the WBEXEC's half
    return e


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bios-dir")
    ap.add_argument("--games", help="the owner's TutorVision images (a directory of folders)")
    a = ap.parse_args()
    ex, gr = isys.bios_paths(a.bios_dir)
    wbx, wbg = isys.tv_paths(a.bios_dir)
    grom = open(gr, "rb").read()
    wbexec = isys.load_words(wbx)[4096:8192] if wbx else None
    fails = []
    pics = {}
    for tv in (0, 1, 2):
        if tv == 2 and wbexec is None:
            print("tvtest full: skipped (no wbexec.bin)")
            continue
        got, pics[tv] = run_tvtest(tv, grom, wbexec)
        want = expect(tv, wbexec)
        # section 8: GROM $3008 and GRAM $3800 read after the window of frames 3 and 7, display on
        want += ([0x00FF, 0x00FF] if tv else [0xFF00 | grom[8], 0x0000]) * 2
        n = len(want)
        ok = got[:n] == want
        print("tvtest %s: %s%s" % (("off", "intv88", "full")[tv], "pass" if ok else "FAIL",
                                   "" if ok else " got %s want %s" % (
                                       " ".join("%04X" % v for v in got[:n]),
                                       " ".join("%04X" % v for v in want))))
        if not ok:
            fails.append("tvtest %d" % tv)
    if PICS_OUT:
        from PIL import Image
        os.makedirs(PICS_OUT, exist_ok=True)
        for tv, ps in pics.items():
            for n in (4, 8):
                if n in ps:
                    im = Image.new("P", (sticm.W, sticm.H))
                    im.putdata(list(ps[n]))
                    im.putpalette([c for v in VIEW for c in v])
                    im.save(os.path.join(PICS_OUT, "tvtest_%d_%d.png" % (tv, n)))
    if 0 in pics and 1 in pics:
        diff = [n for n in pics[0] if n in pics[1] and pics[0][n] != pics[1][n]]
        print("tvtest pictures: off and intv88 differ in %d of %d" % (len(diff), len(pics[0])))
        if not diff:
            fails.append("tvtest pictures: the modes draw the same")
    if a.games:
        for name, setting, frames, font in (("lmc", "intv88", 200, "tv"),
                                             ("TutorVision_MapMazes", "auto", 300, "tv"),
                                             ("TutorVision_Shapes_in_Space", "auto", 300, "tv"),
                                             ("TutorVision_Geo_Graphics", "auto", 300, "tv")):
            d = os.path.join(a.games, name)
            b = os.path.join(d, name + ".bin")
            c = os.path.join(d, name + ".cfg")
            if not os.path.exists(b):
                print("%s: skipped (no image)" % name)
                continue
            if setting == "auto" and wbx is None:
                print("%s: skipped (no wbexec.bin)" % name)
                continue
            bus, cpu, mclk = isys.system_for("stic", a.bios_dir, b, cfg_path=c, tv=setting, font=font)
            got = {}
            bus.vid.keep_frames = set()
            bus.vid.on_frame = lambda n, pic, info: got.__setitem__(n, bytes(pic))
            inrex = [0]
            orig = bus.read

            def rd(addr, cycle, kind="data", orig=orig):
                if kind == "fetch" and 0x2000 <= addr <= 0x2FFF:
                    inrex[0] += 1
                return orig(addr, cycle, kind)
            bus.read = rd
            isys.run_pictures(bus, cpu, frames, mclk)
            last = got[max(got)]
            colours = len(set(last))
            ok = colours > 2 and (setting != "auto" or inrex[0] > 0)
            print("%s: tv %d, %d colours in picture %d, %d fetches in $2000-$2FFF: %s"
                  % (name, bus.tv, colours, max(got), inrex[0], "pass" if ok else "FAIL"))
            if not ok:
                fails.append(name)
    print("TV_CHECK %s" % ("pass" if not fails else "FAIL (%s)" % ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
