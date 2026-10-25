#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""stic_frames: the STIC model's pictures against MAME's (build step 4).

  import --mame-src INTV_CPP --out DIR SNAP.png...
        turn MAME snapshots (RGB PNG, 189 x 240) into palette-index PGMs
        (DIR/<name>.pgm). The 16 colours are read from MAME's own source
        (intv.cpp, table intv_colors) at run time, so no MAME data is kept
        here; needs Pillow. A snapshot pixel that is none of the 16 colours
        is an error.
  run --cart IMG|none --pictures N[,N...] --out DIR [--mode mame|stic|none]
        run the system model (tools/intv_system.py with tools/stic.py) and
        write picture N as DIR/m<N>.pgm, the MOB boxes as DIR/m<N>.mask.pgm
        (1 = a MOB may cover the pixel) and the STIC's graphics bus accesses
        of that frame as DIR/m<N>.bus.txt.
  compare --cart IMG|none --ref DIR --snaps N[,N...] [--mode ...]
        run the model and compare DIR/f<N>.pgm (MAME's snapshot at its
        frame notifier N, imported as above) with model picture N - 1.
        Pixels inside the model's MOB boxes are not compared (MOBs are
        build step 5). Prints one line per picture and STIC_FRAMES pass /
        FAIL.

Picture N is the one the STIC model draws at the start of frame N, as MAME
draws the whole frame in its vblank-N interrupt (intv_m.cpp:683). MAME
runs its frame notifier (and so takes the snapshot) at the same vblank but
before the interrupt (screen.cpp:1680-1686), so snapshot N shows picture
N - 1. Pictures and snapshots
come from the user's game images: write them outside the repository.
The BIOS: --bios-dir or INTV_BIOS_DIR.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import intv_system as isys  # noqa: E402
import stic as sticm  # noqa: E402


def mame_palette(src):
    """The 16 RGB colours of MAME's intv_colors table, read from intv.cpp."""
    text = open(src).read()
    m = re.search(r"intv_colors\[\]\s*=\s*\{(.*?)\};", text, re.S)
    if not m:
        raise SystemExit("%s: no intv_colors table" % src)
    cols = re.findall(r"\{\s*0x([0-9a-fA-F]{2}),\s*0x([0-9a-fA-F]{2}),\s*0x([0-9a-fA-F]{2})\s*\}",
                      m.group(1))
    if len(cols) != 16:
        raise SystemExit("%s: %d colours, want 16" % (src, len(cols)))
    pal = [tuple(int(c, 16) for c in rgb) for rgb in cols]
    if len(set(pal)) != 16:
        raise SystemExit("%s: colours not distinct" % src)
    return pal


def import_snap(png, pal):
    from PIL import Image
    im = Image.open(png).convert("RGB")
    if im.size != (sticm.W, sticm.H):
        raise SystemExit("%s: %dx%d, want %dx%d" % ((png,) + im.size + (sticm.W, sticm.H)))
    inv = {rgb: i for i, rgb in enumerate(pal)}
    out = bytearray()
    get = getattr(im, "get_flattened_data", None) or im.getdata
    for i, rgb in enumerate(get()):
        if rgb not in inv:
            raise SystemExit("%s: pixel %d,%d colour %s not in MAME's palette"
                             % (png, i % sticm.W, i // sticm.W, rgb))
        out.append(inv[rgb])
    return out


def parse_list(s):
    return sorted({int(x) for x in s.split(",") if x})


def model_pictures(cart, pictures, mode, bios_dir=None, want_info=False):
    """{n: (picture, mask, info)} from the system model."""
    bus, cpu, mclk = isys.system_for(mode, bios_dir, None if cart == "none" else cart)
    out = {}

    def grab(n, pic, info):
        if n in pictures:
            mask = bytearray(sticm.W * sticm.H)
            for x0, y0, x1, y1 in bus.vid.mob_boxes():
                for y in range(y0, y1):
                    mask[y * sticm.W + x0:y * sticm.W + x1] = b"\x01" * (x1 - x0)
            info = dict(info)
            info["stats"] = dict(bus.vid.stats[-1])
            out[n] = (pic, mask, info)
    bus.vid.keep_frames = set()
    bus.vid.on_frame = grab
    isys.run_pictures(bus, cpu, max(pictures), mclk)
    return out


def bus_log(info):
    """The STIC's graphics bus accesses of one frame, as text."""
    lines = ["# picture %d: display %s, VDR %d, colour stack mode %d, BUSRQ stolen %d" % (
        info["n"], "on" if info["enabled"] else "off", info["vdr"], info["csmode"],
        info["stolen"]),
        "# ROW r cycle: when row r was copied into the FIFO, in cycles from the frame",
        "#   start (mode stic: the CPU's BUSAK; mame: MAME's timer boundary; none: the",
        "#   fetch cycle). CARD row col: the pattern the card's 8 pixel rows read."]
    for r, rel, ok, addr in info["fetches"]:
        lines.append("ROW %d cycle %s %s sysram $%04X-$%04X" % (
            r, "-" if rel is None else "%d" % rel, "load" if ok else "missed",
            0x200 + addr, 0x200 + addr + 19))
    for row, col, mem, base in info["cards"]:
        if mem == "squares":
            lines.append("CARD %d %d squares" % (row, col))
        else:
            off = 0x3000 if mem == "GROM" else 0x3800
            lines.append("CARD %d %d %s $%04X-$%04X" % (row, col, mem, off + base, off + base + 7))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    im = sub.add_parser("import")
    im.add_argument("--mame-src", required=True)
    im.add_argument("--out", required=True)
    im.add_argument("snaps", nargs="+")
    for name in ("run", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--cart", required=True)
        if name == "run":
            p.add_argument("--pictures", required=True)
        p.add_argument("--mode", choices=sticm.MODES, default="mame")
        p.add_argument("--bios-dir")
        if name == "run":
            p.add_argument("--out", required=True)
        else:
            p.add_argument("--ref", required=True)
            p.add_argument("--snaps", required=True)
            p.add_argument("--save", help="write the model's pictures here too")
    a = ap.parse_args()

    if a.cmd == "import":
        pal = mame_palette(a.mame_src)
        os.makedirs(a.out, exist_ok=True)
        for png in a.snaps:
            name = os.path.splitext(os.path.basename(png))[0]
            sticm.write_pgm(os.path.join(a.out, name + ".pgm"), import_snap(png, pal))
        print("imported %d snapshots" % len(a.snaps))
        return 0

    if a.cmd == "run":
        pics = parse_list(a.pictures)
    else:
        snaps = parse_list(a.snaps)
        pics = [n - 1 for n in snaps]
    got = model_pictures(a.cart, set(pics), a.mode, a.bios_dir)
    if a.cmd == "run":
        os.makedirs(a.out, exist_ok=True)
        for n in pics:
            pic, mask, info = got[n]
            sticm.write_pgm(os.path.join(a.out, "m%d.pgm" % n), pic)
            sticm.write_pgm(os.path.join(a.out, "m%d.mask.pgm" % n), mask)
            with open(os.path.join(a.out, "m%d.bus.txt" % n), "w") as f:
                f.write(bus_log(info))
        print("wrote %d pictures" % len(pics))
        return 0

    ok = True
    for sn in snaps:
        n = sn - 1
        pic, mask, info = got[n]
        if a.save:
            os.makedirs(a.save, exist_ok=True)
            sticm.write_pgm(os.path.join(a.save, "m%d.pgm" % n), pic)
            with open(os.path.join(a.save, "m%d.bus.txt" % n), "w") as f:
                f.write(bus_log(info))
        ref = sticm.read_pgm(os.path.join(a.ref, "f%d.pgm" % sn))
        bad = [i for i in range(len(pic)) if not mask[i] and pic[i] != ref[i]]
        masked = sum(mask)
        st = info["stats"]
        line = "snapshot %d / picture %d: %s, %d pixels differ, %d masked (MOB boxes), display %s, VDR %d, " \
               "csmode %d, stolen %d" % (sn, n, "match" if not bad else "DIFFER", len(bad), masked,
                                         "on" if st["enabled"] else "off", st["vdr"],
                                         info["csmode"], st["stolen"])
        if bad:
            ok = False
            x, y = bad[0] % sticm.W, bad[0] // sticm.W
            line += "; first at x=%d y=%d model %d MAME %d" % (x, y, pic[bad[0]], ref[bad[0]])
        print(line)
    print("STIC_FRAMES %s: %s, %d snapshots, mode %s" % (
        "pass" if ok else "FAIL", os.path.basename(a.cart), len(snaps), a.mode))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
