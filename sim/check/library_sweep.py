#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""library_sweep: every image of a game library through the system model (mode stic, the
core's behaviour: tools/intv_system.py), for the release's known-issues list.

  library_sweep.py run LIBDIR OUTDIR [--frames 600] [--part K/N] [--ecs-rom ECS.bin]
  library_sweep.py sheet OUTDIR          the contact sheet (sheet.png) and summary.csv

Each image is loaded as the core loads it (tools/mapper/cartfmt.py), with the ECS on Auto, and run
for --frames frames (600: 10 s) with scripted keys to get past title screens: key 1 at frame 150,
Enter at 300, the top side button at 420, the disc up at 480-540 (both hand controllers). It
records per image: the pictures at frames 150, 360 and the last; how many frames had the display
on; how many pictures differed from the one before; the CPU's undefined cases met (docs/CPU_NOTES);
and whether the model raised. One line of OUTDIR/rows/NAME.txt per image; `sheet` gathers them.

The flags (summary.csv "flags"): ERROR (the model raised), NODISPLAY (the display never on),
STILL (no picture changed after frame 150), UNDEFINED (an undefined CPU case: the console's
behaviour is used, but such a game is worth a look). None of these is a verdict: the owner's
play on the Pocket is. OUTDIR holds pictures of the user's games: keep it outside any repository.
"""
import argparse
import hashlib
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "mapper")]

PRESSES = "150-156:1,300-306:Enter,420-426:Upper,480-540:Up"
SHOTS = (150, 360)
VIEW = [(0, 0, 0), (0, 45, 255), (255, 61, 16), (201, 207, 171), (56, 107, 63), (0, 167, 86),
        (250, 234, 80), (255, 252, 255), (189, 172, 200), (36, 184, 255), (255, 180, 31),
        (84, 110, 0), (255, 78, 87), (164, 150, 255), (117, 204, 128), (181, 26, 88)]


def images(lib):
    return sorted(f for f in os.listdir(lib) if f.lower().endswith((".zip", ".int", ".bin", ".rom", ".itv")))


def run_one(path, frames, ecs_rom):
    import intv_system as isys
    ecs = ("auto", ecs_rom)                 # ECS on Auto (ecs_rom None: the BIOS folder's ECS.bin)
    bus, cpu, mclk = isys.system_for("stic", None, path, ecs=ecs)
    bus.presses = isys.parse_presses(PRESSES)
    want = set(SHOTS) | {frames}
    pics, st = {}, dict(on=0, changed=0, last=None)

    def grab(n, pic, info):
        st["on"] += 1 if info.get("enabled") else 0
        h = hashlib.sha1(bytes(pic)).hexdigest()
        if n > SHOTS[0] and h != st["last"]:
            st["changed"] += 1
        st["last"] = h
        if n in want:
            pics[n] = pic
    bus.vid.keep_frames = set()
    bus.vid.on_frame = grab
    und = set()
    while bus.vid.last_drawn < frames:
        cpu.step()
        if getattr(cpu, "_und", None):
            und.add(cpu._und)
            cpu._und = None
        bus.boundary(cpu.cycle)
    return pics, st, sorted(und)


def write_pic(path, pic):
    from PIL import Image
    import stic as sticm                    # a flat picture of W x H palette indices
    im = Image.new("RGB", (sticm.W, sticm.H))
    im.putdata([VIEW[v & 15] for v in pic])
    im.save(path)


def cmd_run(a):
    k, n = (int(x) for x in a.part.split("/"))
    lst = images(a.lib)
    mine = [f for i, f in enumerate(lst) if i % n == k - 1]
    os.makedirs(os.path.join(a.out, "rows"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "pics"), exist_ok=True)
    for f in mine:
        name = os.path.splitext(f)[0]
        row = os.path.join(a.out, "rows", name + ".txt")
        if os.path.exists(row):
            continue
        t0 = time.time()
        flags, note = [], ""
        try:
            pics, st, und = run_one(os.path.join(a.lib, f), a.frames, a.ecs_rom)
            for fr, pic in pics.items():
                write_pic(os.path.join(a.out, "pics", "%s_%d.png" % (name, fr)), pic)
            if st["on"] == 0:
                flags.append("NODISPLAY")
            if st["changed"] == 0:
                flags.append("STILL")
            if und:
                flags.append("UNDEFINED")
                note = "; ".join(und)
            on, ch = st["on"], st["changed"]
        except Exception as e:      # the model itself failed on this image
            flags.append("ERROR")
            note, on, ch = "%s: %s" % (type(e).__name__, e), 0, 0
        with open(row, "w") as fo:
            fo.write("%s\t%s\t%d\t%d\t%.0f\t%s\n" % (name, ",".join(flags) or "ok", on, ch,
                                                   time.time() - t0, note))
        print("%-60s %-24s %4ds" % (name[:60], ",".join(flags) or "ok", time.time() - t0), flush=True)
    return 0


def cmd_sheet(a):
    from PIL import Image, ImageDraw
    rows = []
    rd = os.path.join(a.out, "rows")
    for f in sorted(os.listdir(rd)):
        rows.append(open(os.path.join(rd, f)).read().rstrip("\n").split("\t"))
    with open(os.path.join(a.out, "summary.csv"), "w") as fo:
        fo.write("image,flags,display_on_frames,pictures_changed,seconds,note\n")
        for r in rows:
            fo.write(",".join('"%s"' % x.replace('"', "'") for x in r) + "\n")
    cols, tw, th = 8, 160, 192 + 24
    sheet = Image.new("RGB", (cols * tw, ((len(rows) + cols - 1) // cols) * th), (40, 40, 40))
    d = ImageDraw.Draw(sheet)
    for i, r in enumerate(rows):
        x, y = (i % cols) * tw, (i // cols) * th
        last = sorted((p for p in os.listdir(os.path.join(a.out, "pics")) if p.startswith(r[0] + "_")),
                      key=lambda p: int(p.rsplit("_", 1)[1].split(".")[0]))
        if last:
            sheet.paste(Image.open(os.path.join(a.out, "pics", last[-1])), (x, y))
        d.text((x + 2, y + 193), r[0][:26], fill=(255, 255, 255))
        d.text((x + 2, y + 204), r[1], fill=(255, 120, 120) if r[1] != "ok" else (150, 255, 150))
    sheet.save(os.path.join(a.out, "sheet.png"))
    bad = [r for r in rows if r[1] != "ok"]
    print("LIBRARY_SWEEP %d images, %d flagged" % (len(rows), len(bad)))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("lib")
    r.add_argument("out")
    r.add_argument("--frames", type=int, default=600)
    r.add_argument("--part", default="1/1")
    r.add_argument("--ecs-rom")
    s = sub.add_parser("sheet")
    s.add_argument("out")
    a = ap.parse_args()
    return cmd_run(a) if a.cmd == "run" else cmd_sheet(a)


if __name__ == "__main__":
    sys.exit(main())
