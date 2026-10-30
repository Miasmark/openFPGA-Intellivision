#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""build_jlp.py: the JLP measurement cartridges (docs/JLP_NOTES.md 4).

Each program is a table of writes, reads and flash commands run by jlp_run.asm (behind
sim/testroms/hw/hwlib.asm), with its own CFG ([mapping] of the code at $5000, [vars] for the
JLP mode and flash size, and for JLPENA a ROM under the JLP's addresses). The cartridge shows
its results as hex pages; the same results come from the model (tools/jlp.py in
tools/intv_system.py on the real EXEC) as NAME.txt, so a screen photo from the PiRTO II, or a
jzIntv run, compares word for word. Our own code, built, never committed.

  build_jlp.py build OUTDIR [NAME ...]     NAME.bin, NAME.cfg, NAME.txt (the model's results)
  build_jlp.py show NAME                   the model's results only
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
HW = os.path.join(os.path.dirname(HERE), "hw")
BASE = 0x5000
W, R, F, FILL, SUM = 1, 2, 3, 4, 5
ON, OFF = (W, 0x8033, 0x4A5A), (W, 0x8034, 0x6A7A)
WR, RD, ER = (0x802D, 0xC0DE), (0x802E, 0xDEC0), (0x802F, 0xBEEF)


def rd(*addrs):
    return [(R, a, 0) for a in addrs]


def flash(cmd, row=None, addr=None):
    t = []
    if addr is not None:
        t.append((W, 0x8025, addr))
    if row is not None:
        t.append((W, 0x8026, row))
    return t + [(F, cmd[0], cmd[1])]


def mpy(lo, cases):
    t = []
    for a, b in cases:
        t += [(W, lo, a), (W, lo + 1, b)] + rd(0x9F8E, 0x9F8F)
    return t


MPY_CASES = [(0x7FFF, 0x7FFF), (0x8000, 0x8000), (0xFFFF, 0xFFFF), (0x8000, 0xFFFF), (3, 0xFFFB)]
DIV_CASES = [(100, 7), (0xFF9C, 7), (100, 0xFFF9), (0xFF9C, 0xFFF9), (0x8000, 0xFFFF), (5, 0), (0, 0),
             (0xFFFF, 0)]


def p_map():
    """T1, T2, T7: what reads back where; the RAM's edges."""
    t = rd(0x8023, 0x8024, 0x8025, 0x8026, 0x802D, 0x802E, 0x802F, 0x8033, 0x8034, 0x803F, 0x8000,
           0x9F8C, 0x9F8D, 0x9FFC, 0x9FF0, 0x9FFF)
    t += rd(*range(0x9F90, 0x9F98))
    t += [(W, 0x9F90 + n, 0x1111 * (n + 1)) for n in range(8)] + rd(*range(0x9F90, 0x9F98)) + rd(0x9F8E)
    for a, v in ((0x803F, 0xA5C3), (0x8040, 0xA5C3), (0x9F7F, 0x5A3C), (0x9F80, 0x1234)):
        t += [(W, a, v)] + rd(a)
    return t + rd(0x8041, 0x9F7E)


def p_mul():
    """T3: the four multiplies, a recompute on one operand, operand read-back, a result write."""
    t = []
    for lo in (0x9F80, 0x9F82, 0x9F84, 0x9F86):
        t += mpy(lo, MPY_CASES)
    t += [(W, 0x9F86, 2)] + rd(0x9F8E, 0x9F8F)
    t += rd(*range(0x9F80, 0x9F88))
    return t + [(W, 0x9F8E, 0x1234)] + rd(0x9F8E)


def p_div():
    """T4, T5, T6: divides (signs, x / 0, overflow), the CRC, the random number."""
    t = mpy(0x9F8A, DIV_CASES) + mpy(0x9F88, DIV_CASES)
    t += rd(0x9FFD) + [(W, 0x9FFD, 0xFFFF)]
    for d in (0x0000, 0x0001, 0x1234):
        t += [(W, 0x9FFC, d)] + rd(0x9FFD)
    t += rd(0x9FFC) + rd(*[0x9FFE] * 8) + [(W, 0x9FFE, 0x1234)] + rd(0x9FFE, 0x9FFE)
    return t


def p_fls():
    """T10 (c)-(g), T11: flash rows and sectors, dropped commands, the busy reads."""
    t = rd(0x8023, 0x8024)
    t += flash(RD, 0, 0x9000) + [(SUM, 0x9000, 0)]                       # (c) an empty row
    t += [(FILL, 0x8040, 0x1000)] + flash(WR, 1, 0x8040)                 # (d) write row 1
    t += flash(RD, 1, 0x9100) + [(SUM, 0x9100, 0)]
    t += [(FILL, 0x8040, 0x2000)] + flash(WR, 1, 0x8040)                 # (e) row 1 again
    t += flash(RD, 1, 0x9200) + [(SUM, 0x9200, 0)]
    t += [(FILL, 0x8040, 0x3000)] + flash(WR, 8, 0x8040)                 # row 8: sector 1
    t += flash(ER, 3)                                                    # (f) erase sector 0
    t += flash(RD, 1, 0x9300) + [(SUM, 0x9300, 0)]
    t += flash(RD, 8, 0x9400) + [(SUM, 0x9400, 0)]
    t += flash(RD, 32, 0x9000)                                           # (g) rows 0-31 only
    t += flash(RD, 0, 0x9F40)                                            # 96 words past $9F7F
    t += flash((0x802F, 0xBEEE), 8)                                      # a wrong key
    return t + flash(RD, 8, 0x9500) + [(SUM, 0x9500, 0)]


def p_ena():
    """T8: the switch, in mode 2 (off at reset), with ROM under the JLP's addresses."""
    t = rd(0x8040, 0x9F80, 0x9FFE, 0x8023, 0x9F8E)
    t += [ON] + rd(0x8040) + [(W, 0x8040, 0x1234)] + rd(0x8040, 0x8023, 0x9F80)
    t += [OFF] + rd(0x8040, 0x8023, 0x9F80) + [(W, 0x8040, 0x5555)]
    t += [ON] + rd(0x8040)
    t += [(W, 0x8034, 0x6A7B)] + rd(0x8040) + [(W, 0x8034, 0x4A5A)] + rd(0x8040)
    t += [(W, 0x8033, 0x6A7A)] + rd(0x8040) + [OFF, (W, 0x8033, 0x4A5B)] + rd(0x8040)
    return t


def p_size():
    """T10 (a), (b): the flash range a CFG gives (the program is the same for each CFG)."""
    return rd(0x8023, 0x8024, 0x8040) + [(W, 0x8040, 0x4321)] + rd(0x8040)


ROMPAT = ((0x8040, 0x807F), (0x9F80, 0x9F8F))       # JLPENA: ROM under the JLP, word = addr ^ $5A5A
PROGS = {
    "jlpmap": (p_map, "jlp = 3\njlp_flash = 4\n", False),
    "jlpmul": (p_mul, "jlp = 1\n", False),
    "jlpdiv": (p_div, "jlp = 1\n", False),
    "jlpfls": (p_fls, "jlp = 3\njlp_flash = 4\n", False),
    "jlpena": (p_ena, "jlp_accel = 2\njlp_flash = 1\n", True),
    "jlpf1": (p_size, "jlp = 3\njlp_flash = 1\n", False),
    "jlpf16": (p_size, "jlp = 3\njlp_flash = 16\n", False),
    "jlpf0": (p_size, "jlp = 3\n", False),
    "jlpfib": (p_size, "jlp = 3\njlpflash = 16\n", False),
    "jlpm1": (p_size, "jlp = 1\n", False),
    "jlpfz": (p_size, "jlp = 3\njlp_flash = 0\n", False),
}


def tools_path():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    sys.path.insert(1, os.path.join(ROOT, "tools", "mapper"))


def table(name):
    t = PROGS[name][0]()
    n = sum(1 if op in (R,) else 2 if op in (F, SUM) else 0 for op, _, _ in t)
    if n > 64:
        raise SystemExit("%s: %d results (64 at most)" % (name, n))
    return t


POLL_SRC = """        ROMW    16
        ORG     $0340
        MVO@    R2, R1
pl:     INCR    R3
        MVI@    R1, R0
        CMPI    #$FFFF, R0
        BEQ     pl
        JR      R5
"""


def source(name):
    import as1610
    poll = as1610.assemble(POLL_SRC, romw=16)
    pw = [poll.words[0x0340 + i] for i in range(8)]
    lib = open(os.path.join(HW, "hwlib.asm"), encoding="utf-8").read()
    lib = lib.replace('STRING  "TITLE"', 'STRING  "%s"' % name.upper())
    run = open(os.path.join(HERE, "jlp_run.asm"), encoding="utf-8").read()
    rows = ["table:"] + ["        DECLE   %d, $%04X, $%04X" % e for e in table(name)] + ["        DECLE   0, 0, 0"]
    rows += ['ttl:    STRING  "%s"' % name.upper(), "        DECLE   0"]
    rows += ["pollsrc:", "        DECLE   " + ", ".join("$%04X" % w for w in pw)]
    return lib + run + "\n".join(rows) + "\n"


def build_one(name):
    import as1610
    prog = as1610.assemble(source(name), romw=16)
    top = max(prog.words)
    for a in prog.words:
        if not BASE <= a < BASE + 0x2000:
            raise SystemExit("%s: word at $%04X outside $5000-$6FFF" % (name, a))
    words = [prog.words.get(BASE + i, 0) for i in range(top - BASE + 1)]
    cfg = "[mapping]\n$0000 - $%04X = $5000\n" % (len(words) - 1)
    if PROGS[name][2]:
        for lo, hi in ROMPAT:
            cfg += "$%04X - $%04X = $%04X\n" % (len(words), len(words) + hi - lo, lo)
            words += [a ^ 0x5A5A for a in range(lo, hi + 1)]
    cfg += "[vars]\n" + PROGS[name][1]
    image = b"".join(bytes(((w >> 8) & 0xFF, w & 0xFF)) for w in words)
    return prog, image, cfg


def model_results(name, image, cfg, frames=40):
    """The results the model's machine leaves at $0300 (tools/intv_system.py, the real EXEC)."""
    import tempfile
    import intv_system as isys
    d = tempfile.mkdtemp(prefix="jlp_")
    bp, cp = os.path.join(d, name + ".bin"), os.path.join(d, name + ".cfg")
    open(bp, "wb").write(image)
    open(cp, "w").write(cfg)
    bus, cpu, mame = isys.system_for("stic", cart_path=bp, cfg_path=cp)
    if bus.jlp is None:
        raise SystemExit("%s: the model made no JLP from the CFG" % name)
    isys.run_pictures(bus, cpu, frames, mame_clock=mame)
    ram = bus.sysram
    n = ram[0x351 - 0x200]
    return [ram[0x100 + i] for i in range(n)], bus


def layout(name, res):
    """The screen's pages as text: index, then three results a row."""
    out = []
    for p in range(0, max(len(res), 1), 33):
        out.append("%s %04X" % (name.upper(), p // 33 + 1))
        for i in range(p, min(p + 33, len(res)), 3):
            out.append("%04X " % i + " ".join("%04X" % v for v in res[i:i + 3]))
        out.append("")
    return "\n".join(out)


def describe(name):
    """What each result is, one line each (for reading a photo)."""
    lines = []
    for op, a, v in table(name):
        if op == R:
            lines.append("read  $%04X" % a)
        elif op == F:
            lines += ["cmd   $%04X <- $%04X: reads until done" % (a, v), "cmd   $%04X: value read last" % a]
        elif op == SUM:
            lines += ["row   $%04X: first word" % a, "row   $%04X: sum of 96" % a]
    return lines


def cmd_build(a):
    tools_path()
    os.makedirs(a.out, exist_ok=True)
    for name in a.names or PROGS:
        prog, image, cfg = build_one(name)
        for w in prog.warnings:
            print("%s: warning: %s" % (name, w), file=sys.stderr)
        res, _ = model_results(name, image, cfg)
        open(os.path.join(a.out, name + ".bin"), "wb").write(image)
        open(os.path.join(a.out, name + ".cfg"), "w").write(cfg)
        txt = layout(name, res) + "\n" + "\n".join("%04X %04X  %s" % (i, res[i] if i < len(res) else 0, d)
                                                    for i, d in enumerate(describe(name)))
        open(os.path.join(a.out, name + ".txt"), "w").write(txt + "\n")
        print("%-7s %5d words, %2d results (model)" % (name, len(image) // 2, len(res)))
    return 0


def cmd_show(a):
    tools_path()
    prog, image, cfg = build_one(a.name)
    res, _ = model_results(a.name, image, cfg)
    print(layout(a.name, res))
    for i, d in enumerate(describe(a.name)):
        print("%04X %04X  %s" % (i, res[i] if i < len(res) else 0, d))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("out")
    b.add_argument("names", nargs="*")
    s = sub.add_parser("show")
    s.add_argument("name")
    a = ap.parse_args(argv)
    return cmd_build(a) if a.cmd == "build" else cmd_show(a)


if __name__ == "__main__":
    sys.exit(main())
