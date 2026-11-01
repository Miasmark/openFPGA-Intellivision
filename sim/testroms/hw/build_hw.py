#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""build_hw.py: the hardware measurement cartridges (docs/HW_TESTS.md).

Each hw_*.asm in this directory is assembled behind hwlib.asm (the EXEC cartridge header,
the ISR take-over, text output; as1610 has no INCLUDE) into a raw cartridge image at $5000
and a CFG with one [mapping] line: NAME.bin + NAME.cfg, as a flash cartridge takes them
(the owner's PiRTO II: BIN + CFG, names of at most 32 bytes). Our own code, built, never
committed.

  build_hw.py build OUTDIR [NAME ...]
  build_hw.py run NAME [--frames N] [--snaps 30,60] [--mode stic] [--ecs on] [--tools DIR]
        [--keys ROW:COL,...] [--png DIR] [--vars N] [--intrm-shift D]
        run the cartridge on the real EXEC in the Python model (tools/intv_system.py; the
        user's exec.bin / grom.bin from INTV_BIOS_DIR), write the pictures asked for as PNG
        (a viewing palette, not a measured one) and print the program's variables
        ($0300 on). --tools takes the model from another tree (to compare model versions).
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
BASE = 0x5000
PROGS = ("hw_steal", "hw_intlate", "hw_rowcopy", "hw_cpuodd", "hw_ecskeys", "hw_frame", "hw_steal2", "hw_frame2")

# for looking at the model's pictures only (approximate colours; the STIC's real palette is
# a later capture, DESIGN 13)
VIEW = [(0, 0, 0), (0, 45, 255), (255, 61, 16), (201, 207, 171), (56, 107, 63), (0, 167, 86),
        (250, 234, 80), (255, 252, 255), (189, 172, 200), (36, 184, 255), (255, 180, 31),
        (84, 110, 0), (255, 78, 87), (164, 150, 255), (117, 204, 128), (181, 26, 88)]


def tools_path(d=None):
    sys.path.insert(0, os.path.join(d or ROOT, "tools"))
    sys.path.insert(1, os.path.join(d or ROOT, "tools", "mapper"))


def source(name):
    lib = open(os.path.join(HERE, "hwlib.asm"), encoding="utf-8").read()
    if lib.count('STRING  "TITLE"') != 1:
        raise SystemExit("hwlib.asm: no TITLE")
    lib = lib.replace('STRING  "TITLE"', 'STRING  "%s"' % name.upper().replace("_", " "))
    return lib + open(os.path.join(HERE, name + ".asm"), encoding="utf-8").read()


def build_one(name):
    import as1610
    prog = as1610.assemble(source(name), romw=16)
    top = max(prog.words)
    for a in prog.words:
        if not BASE <= a < BASE + 0x2000:
            raise SystemExit("%s: word at $%04X outside $5000-$6FFF" % (name, a))
    words = [prog.words.get(BASE + i, 0) for i in range(top - BASE + 1)]
    image = b"".join(bytes(((w >> 8) & 0xFF, w & 0xFF)) for w in words)
    cfg = "[mapping]\n$0000 - $%04X = $5000\n" % (len(words) - 1)
    return prog, image, cfg


def cmd_build(a):
    tools_path()
    os.makedirs(a.out, exist_ok=True)
    for name in a.names or PROGS:
        prog, image, cfg = build_one(name)
        for w in prog.warnings:
            print("%s: warning: %s" % (name, w), file=sys.stderr)
        open(os.path.join(a.out, name + ".bin"), "wb").write(image)
        open(os.path.join(a.out, name + ".cfg"), "w").write(cfg)
        open(os.path.join(a.out, name + ".lst"), "w").write(prog.listing_text())
        print("%-11s %5d words  isr $%04X  main $%04X" % (name, len(image) // 2, prog.symbols["isr"],
                                                         prog.symbols["main"]))
    return 0


def write_png(path, pic, sticm):
    from PIL import Image
    im = Image.new("RGB", (sticm.W, sticm.H))
    im.putdata([VIEW[p & 15] for p in pic])
    im.resize((sticm.W * 3, sticm.H * 2), Image.NEAREST).save(path)


def cmd_run(a):
    tools_path(a.tools)
    import intv_system as isys
    import stic as sticm
    import tempfile
    tools_path()                        # the assembler from this tree
    prog, image, cfg = build_one(a.name)
    d = tempfile.mkdtemp(prefix="hw_")
    bp, cp = os.path.join(d, a.name + ".bin"), os.path.join(d, a.name + ".cfg")
    open(bp, "wb").write(image)
    open(cp, "w").write(cfg)
    ecs = (a.ecs, None) if a.ecs else None
    bus, cpu, mame = isys.system_for(a.mode, cart_path=bp, cfg_path=cp, ecs=ecs)
    snaps = sorted(int(x) for x in a.snaps.split(",")) if a.snaps else []
    bus.vid.keep_frames = set(snaps)
    if a.intrm_shift:                   # the CPU sees INTRM d cycles later (d < 0: earlier)
        orig, d = bus.intrm, a.intrm_shift
        bus.intrm = lambda cycle: orig(cycle - d)
    if a.keys and bus.ecs is not None:
        k = 0
        for rc in a.keys.split(","):
            r, c = (int(x) for x in rc.split(":"))
            k |= 1 << (8 * r + c)
        bus.ecs.keys = k
    isys.run_pictures(bus, cpu, a.frames, mame_clock=mame)
    if a.png:
        os.makedirs(a.png, exist_ok=True)
        for n, pic in bus.vid.frames:
            p = os.path.join(a.png, "%s_%s_%d.png" % (a.name, a.tag or a.mode, n))
            write_png(p, pic, sticm)
            print("picture %d -> %s" % (n, p))
    ram = bus.sysram
    print("vars:", " ".join("%04X" % ram[0x300 - 0x200 + i] for i in range(a.vars)))
    print("cycles %d" % cpu.cycle)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("out")
    b.add_argument("names", nargs="*")
    r = sub.add_parser("run")
    r.add_argument("name")
    r.add_argument("--frames", type=int, default=60)
    r.add_argument("--snaps")
    r.add_argument("--mode", default="stic")
    r.add_argument("--ecs")
    r.add_argument("--tools")
    r.add_argument("--keys")
    r.add_argument("--png")
    r.add_argument("--tag")
    r.add_argument("--vars", type=int, default=16)
    r.add_argument("--intrm-shift", type=int, default=0,
                   help="what-if: the CPU sees INTRM this many cycles later (hw_intlate's table)")
    a = ap.parse_args(argv)
    return cmd_build(a) if a.cmd == "build" else cmd_run(a)


if __name__ == "__main__":
    sys.exit(main())
