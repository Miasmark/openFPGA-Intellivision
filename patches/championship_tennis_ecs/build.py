#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""build: Championship Tennis for four human players with the ECS (includes the ECS page fix), as a
BPS patch, from your own image.

  build.py IMAGE OUTDIR

IMAGE is the cartridge image you own: the No-Intro zip, its .int, or a .bin of the same 32,768 bytes
(CRC32 4CC46A04). OUTDIR gets:
  "Championship Tennis (ECS).bin"   the patched image (your game data: keep it out of any repository)
  "Championship Tennis (ECS).cfg"   its memory map (a copy of the .cfg in this folder)
  championship_tennis_ecs.bps       the patch (the same as the one in this folder)
The patch words come from tennis_ecs.asm (tools/as1610.py). The words they replace are checked
first, so the patch can only go on the image it was written for.
"""
import os
import sys
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(ROOT, "tools")]
import as1610  # noqa: E402
import bps  # noqa: E402

SOURCE_CRC, SOURCE_SIZE = 0x4CC46A04, 32768
SEGMENTS = ((0x5000, 0x2000, 0x0000), (0xD000, 0x2000, 0x4000))   # address, words, file byte offset
# what the patch overwrites: the title routine's first two instructions (PSHR R5, MVII #$0007, R3),
# the header's start address ($5200), the task's first two instructions at $5072 (PSHR R5, MVI
# $017E, R0), the held-disc re-check's MVII #$011E, R1 / ADDR R3, R1 at $E0DF, the five hand-controller handler addresses at $52D0 ($D000,
# $6489, $DD2B, $DD30, $DD35, low byte then high byte), and zero padding for the new code; anything
# else means another image or another version
REPLACED = {0x5056: 0x0275, 0x5057: 0x02BB, 0x5058: 0x0007, 0x5004: 0x0000, 0x5005: 0x0052,
            0xE0DF: 0x02B9, 0xE0E0: 0x011E, 0xE0E1: 0x00D9,
            0x5072: 0x0275, 0x5073: 0x0280, 0x5074: 0x017E}
REPLACED.update(zip(range(0x52D0, 0x52DA), (0x00, 0xD0, 0x89, 0x64, 0x2B, 0xDD, 0x30, 0xDD, 0x35, 0xDD)))
NAME = "Championship Tennis (ECS)"


def offset(addr):
    for base, n, off in SEGMENTS:
        if base <= addr < base + n:
            return off + 2 * (addr - base)
    raise ValueError("$%04X is not in the cartridge's map" % addr)


def load(path):
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith((".int", ".bin", ".rom"))]
            if len(names) != 1:
                raise SystemExit("%s: want exactly one image inside, found %r" % (path, names))
            return z.read(names[0])
    with open(path, "rb") as f:
        return f.read()


def build(src):
    if len(src) != SOURCE_SIZE or zlib.crc32(src) & 0xFFFFFFFF != SOURCE_CRC:
        raise SystemExit("not the image this patch is for: %d bytes, CRC32 %08X (want %d, %08X)"
                         % (len(src), zlib.crc32(src) & 0xFFFFFFFF, SOURCE_SIZE, SOURCE_CRC))
    with open(os.path.join(HERE, "tennis_ecs.asm"), encoding="utf-8") as f:
        prog = as1610.assemble(f.read())
    out = bytearray(src)
    for addr, word in sorted(prog.words.items()):
        o = offset(addr)
        old = src[o] << 8 | src[o + 1]
        want = REPLACED.get(addr, 0x0000)
        if old != want:
            raise SystemExit("$%04X holds %04X, want %04X: another version of the game?" % (addr, old, want))
        out[o], out[o + 1] = word >> 8, word & 0xFF
    return bytes(out), len(prog.words)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    src = load(argv[0])
    tgt, n = build(src)
    os.makedirs(argv[1], exist_ok=True)
    meta = ("Championship Tennis (INTV 1985) four players with the ECS: %d words; "
            "openFPGA-Intellivision patches/championship_tennis_ecs" % n).encode("utf-8")
    patch = bps.make(src, tgt, meta)
    assert bps.apply(src, patch) == tgt
    with open(os.path.join(argv[1], NAME + ".bin"), "wb") as f:
        f.write(tgt)
    with open(os.path.join(HERE, "championship_tennis_ecs.cfg"), encoding="utf-8") as f:
        cfg = f.read()
    with open(os.path.join(argv[1], NAME + ".cfg"), "w", encoding="utf-8") as f:
        f.write(cfg)
    with open(os.path.join(argv[1], "championship_tennis_ecs.bps"), "wb") as f:
        f.write(patch)
    print("source CRC32 %08X, target CRC32 %08X, %d words changed, patch %d bytes (its CRC32 %08X)"
          % (SOURCE_CRC, zlib.crc32(tgt) & 0xFFFFFFFF, n, len(patch), int.from_bytes(patch[-4:], "little")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
