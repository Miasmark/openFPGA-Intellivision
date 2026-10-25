#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""sticmob_cart.py: build sticmob.asm as a cartridge image at $5000.

sticmob.asm is written for the EXEC slot (reset vector $1000, our own ISR
at $1004). This script makes a cartridge of the same program, unchanged
in its scenes, tables and checks, that the real EXEC starts:

  - the prologue (ORG $1000, the reset branch) becomes ORG $5000, a
    cartridge header for the EXEC and a title string followed by start-up
    code (the "code after the title" technique of S9 interrupts.txt,
    "INITIALIZATION", written by us);
  - the start-up code points the EXEC's ISR vector ($0100 / $0101, S9
    interrupts.txt "ISR VECTOR") at an initialisation routine and waits;
    that routine, called by the EXEC's dispatcher in VBlank, disables
    interrupts, points the vector at sticmob's ISR and jumps to sticmob's
    main, which never returns to the EXEC;
  - sticmob's ISR ends with JR R5 instead of PULR R7: the EXEC's
    dispatcher has saved the registers and calls the ISR with R5 = its
    return code ($1014, S9 interrupts.txt), which restores them.

The header layout (pointers, flags word, colour stack and border words)
is the EXEC's cartridge interface; that the EXEC starts this image is
checked by running it on the real EXEC in MAME (tools/refs/
mame_cart_prog.sh, docs/STIC_NOTES.md 6). The image is the raw cartridge
format: 8,192 big-endian words for $5000-$6FFF (MAME's intv loads an
image it has no hash entry for as one such block at $5000), padded with
zero; --cfg also writes the [mapping] file.

Use: sticmob_cart.py OUT.bin [--cfg OUT.cfg] [-l OUT.lst]
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import as1610  # noqa: E402

BASE, SIZE = 0x5000, 0x2000

OLD_PROLOGUE = """        ORG     $1000
        B       main            ; $1000: reset vector
        NOP
        NOP
"""

CART_PROLOGUE = """        ORG     $5000
; (cartridge build, sim/testroms/sticmob_cart.py) the EXEC's cartridge
; header: nothing for the EXEC to draw or run; start-up code after the title.
        BIDECLE c_zero          ; $5000 MOB picture list: empty
        BIDECLE c_zero          ; $5002 process table: empty
        BIDECLE c_start         ; $5004 program start
        BIDECLE c_zero          ; $5006 background picture list: empty
        BIDECLE c_ones          ; $5008 GRAM picture list: empty
        BIDECLE c_title         ; $500A title and year
        DECLE   $03C0           ; $500C flags: run the code after the title
c_zero: DECLE   0               ; $500D border extension
        DECLE   0               ; $500E Color Stack mode
c_ones: DECLE   1, 1, 1, 1      ; colour stack
        DECLE   1               ; border
c_title:
        DECLE   126             ; year - 1900
        STRING  "STICMOB"
        DECLE   0
; start-up code after the title: hook the ISR vector, wait for VBlank
c_start:
        MVII    #c_init, R0
        MVO     R0, $0100
        SWAP    R0
        MVO     R0, $0101
        EIS
c_spin: B       c_spin
; called by the EXEC's dispatcher: take the machine over for good
c_init: DIS
        MVII    #$0310, R6
        MVII    #isr, R0
        MVO     R0, $0100
        SWAP    R0
        MVO     R0, $0101
        B       main
"""

OLD_RETURN = """        PULR    R7

main:"""

CART_RETURN = """        JR      R5              ; (cartridge build) to the EXEC's return code

main:"""


def cart_source(text):
    for old in (OLD_PROLOGUE, OLD_RETURN):
        if text.count(old) != 1:
            raise SystemExit("sticmob.asm changed: the cartridge build's "
                             "substitution no longer applies:\n" + old)
    return text.replace(OLD_PROLOGUE, CART_PROLOGUE).replace(OLD_RETURN, CART_RETURN)


def build(src_path):
    with open(src_path, encoding="utf-8") as f:
        prog = as1610.assemble(cart_source(f.read()), romw=10)
    for a in prog.words:
        if not BASE <= a < BASE + SIZE:
            raise SystemExit("word at $%04X outside $5000-$6FFF" % a)
    words = [prog.words.get(BASE + i, 0) for i in range(SIZE)]
    return prog, b"".join(bytes(((w >> 8) & 0xFF, w & 0xFF)) for w in words)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("--src", default=os.path.join(HERE, "sticmob.asm"))
    ap.add_argument("--cfg")
    ap.add_argument("-l", "--listing")
    a = ap.parse_args(argv)
    prog, image = build(a.src)
    for w in prog.warnings:
        print("warning: %s" % w, file=sys.stderr)
    with open(a.out, "wb") as f:
        f.write(image)
    if a.cfg:
        with open(a.cfg, "w", encoding="utf-8") as f:
            f.write("[mapping]\n$0000 - $1FFF = $5000\n")
    if a.listing:
        with open(a.listing, "w", encoding="utf-8") as f:
            f.write(prog.listing_text())
    used = max(prog.words) - BASE + 1
    print("%s: %d words used of $5000-$6FFF, isr $%04X, main $%04X" % (
        a.out, used, prog.symbols["isr"], prog.symbols["main"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
