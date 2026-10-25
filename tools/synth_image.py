#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""synth_image: synthetic cartridge images whose CRC32 is a chosen value.

The benches need images that hit given entries of the committed CRC table
(src/fpga/core/tables/cart_crc.hex) without any game data: a fixed word
pattern, then 4 bytes chosen so that the CRC32 of the whole file is the
table's CRC. CRC32 is affine over GF(2) in the appended bytes, so the 4
bytes come from a 32 x 32 linear system (no table inversion needed).

  pattern(nbytes, seed)        a word pattern, high byte != low byte, so a
                               byte-order mistake shows
  force_crc(data, target)      the 4 bytes to append for CRC32 = target
  forced(target, nbytes, seed) pattern(nbytes - 4) + the 4 bytes
  python3 -I tools/synth_image.py CRC NBYTES OUT [--seed N]

Used by sim/tb/tb_loader.py (forced: rows of sim/regress/step2_set.csv: a
size mismatch and correct-size hits on layouts the library does not use)
and sim/tb/tb_system.py (the cartridge images of the cart-write test).
"""
import argparse
import sys
import zlib


def crc32(b, c=0):
    return zlib.crc32(b, c) & 0xFFFFFFFF


def pattern(nbytes, seed=0):
    out = bytearray()
    i = 0
    while len(out) < nbytes:
        v = (i * 0x3B5D + 0x1F2E + seed * 0x0101) & 0xFFFF
        if (v >> 8) == (v & 0xFF):
            v ^= 0x0100
        out += bytes((v >> 8, v & 0xFF))
        i += 1
    return bytes(out[:nbytes])


def force_crc(data, target):
    """4 bytes x with crc32(data + x) == target."""
    base = crc32(data + b'\0\0\0\0')
    cols = []
    for bit in range(32):
        x = (1 << bit).to_bytes(4, 'little')
        cols.append(crc32(data + x) ^ base)
    # solve sum(c_i * cols[i]) = target ^ base over GF(2)
    want = target ^ base
    basis = {}                      # pivot bit -> (vector, combination of input bits)
    for i, c in enumerate(cols):
        comb = 1 << i
        v = c
        for p in sorted(basis, reverse=True):
            if v >> p & 1:
                bv, bc = basis[p]
                v ^= bv
                comb ^= bc
        if v:
            basis[v.bit_length() - 1] = (v, comb)
    if len(basis) != 32:
        raise ValueError('CRC map not invertible')
    comb = 0
    v = want
    for p in sorted(basis, reverse=True):
        if v >> p & 1:
            bv, bc = basis[p]
            v ^= bv
            comb ^= bc
    assert v == 0
    x = comb.to_bytes(4, 'little')
    assert crc32(data + x) == target
    return x


def forced(target, nbytes, seed=0):
    if nbytes < 4:
        raise ValueError('need at least 4 bytes')
    head = pattern(nbytes - 4, seed)
    return head + force_crc(head, target)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('crc')
    ap.add_argument('nbytes', type=int)
    ap.add_argument('out')
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    data = forced(int(a.crc, 16), a.nbytes, a.seed)
    with open(a.out, 'wb') as f:
        f.write(data)
    print('%s: %d bytes, CRC32 %08X' % (a.out, len(data), crc32(data)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
