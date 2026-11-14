#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""bps: BPS patches (beat's binary patch format, version 1), written from the format's published
specification (byuu, "BPS file format": the header "BPS1", the variable-length numbers, the four
actions SourceRead / TargetRead / SourceCopy / TargetCopy, the CRC32 footer). No code from any
other implementation was used.

  bps.py make SOURCE TARGET OUT.bps [--meta TEXT]   a patch from SOURCE to TARGET
  bps.py apply SOURCE PATCH.bps OUT                 apply a patch (all CRC32s checked)
  bps.py info PATCH.bps                             sizes, CRC32s, actions

make() writes only SourceRead (bytes equal to the source at the same offset) and TargetRead (the
target's own bytes) actions, so the patch carries exactly the bytes that change and nothing of the
source. apply() decodes all four actions.
"""
import argparse
import sys
import zlib

MAGIC = b"BPS1"
SOURCE_READ, TARGET_READ, SOURCE_COPY, TARGET_COPY = range(4)
NAMES = ("SourceRead", "TargetRead", "SourceCopy", "TargetCopy")


class BpsError(Exception):
    pass


def encode_number(n):
    """The specification's variable-length number: 7 bits a byte, low first, the last byte's top
    bit set, and each further byte counting from one more than the previous range ends."""
    if n < 0:
        raise ValueError("negative number")
    out = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(0x80 | x)
            return bytes(out)
        out.append(x)
        n -= 1


def decode_number(buf, pos):
    """(number, next position)."""
    data, shift = 0, 1
    while True:
        if pos >= len(buf):
            raise BpsError("number runs past the end")
        x = buf[pos]
        pos += 1
        data += (x & 0x7F) * shift
        if x & 0x80:
            return data, pos
        shift <<= 7
        data += shift


def crc32(b):
    return zlib.crc32(b) & 0xFFFFFFFF


def make(source, target, metadata=b""):
    """A BPS patch from source to target (bytes) with SourceRead / TargetRead actions only."""
    out = bytearray(MAGIC)
    out += encode_number(len(source)) + encode_number(len(target)) + encode_number(len(metadata))
    out += metadata
    i, n = 0, len(target)
    while i < n:
        same = i < len(source) and source[i] == target[i]
        j = i
        while j < n and (j < len(source) and source[j] == target[j]) == same:
            j += 1
        out += encode_number(((j - i - 1) << 2) | (SOURCE_READ if same else TARGET_READ))
        if not same:
            out += target[i:j]
        i = j
    out += crc32(source).to_bytes(4, "little") + crc32(target).to_bytes(4, "little")
    out += crc32(bytes(out)).to_bytes(4, "little")
    return bytes(out)


def parse(patch):
    """(source size, target size, metadata, [(action, length, data or offset)], source CRC,
    target CRC); the patch's own CRC32 checked."""
    if len(patch) < len(MAGIC) + 3 + 12 or patch[:4] != MAGIC:
        raise BpsError("not a BPS1 patch")
    if crc32(patch[:-4]) != int.from_bytes(patch[-4:], "little"):
        raise BpsError("patch CRC32 mismatch")
    pos = 4
    ssize, pos = decode_number(patch, pos)
    tsize, pos = decode_number(patch, pos)
    msize, pos = decode_number(patch, pos)
    meta = patch[pos:pos + msize]
    pos += msize
    end = len(patch) - 12
    acts = []
    while pos < end:
        v, pos = decode_number(patch, pos)
        cmd, length = v & 3, (v >> 2) + 1
        if cmd == TARGET_READ:
            acts.append((cmd, length, patch[pos:pos + length]))
            pos += length
        elif cmd in (SOURCE_COPY, TARGET_COPY):
            off, pos = decode_number(patch, pos)
            acts.append((cmd, length, -(off >> 1) if off & 1 else off >> 1))
        else:
            acts.append((cmd, length, None))
    if pos != end:
        raise BpsError("actions run into the footer")
    scrc = int.from_bytes(patch[-12:-8], "little")
    tcrc = int.from_bytes(patch[-8:-4], "little")
    return ssize, tsize, meta, acts, scrc, tcrc


def apply(source, patch):
    """The target (bytes); the source, target and patch CRC32s and sizes checked."""
    ssize, tsize, _, acts, scrc, tcrc = parse(patch)
    if len(source) != ssize or crc32(source) != scrc:
        raise BpsError("source is not the one the patch was made for (size %d, CRC32 %08X; want "
                       "%d, %08X)" % (len(source), crc32(source), ssize, scrc))
    out = bytearray()
    srel = trel = 0
    for cmd, length, arg in acts:
        if cmd == SOURCE_READ:
            out += source[len(out):len(out) + length]
        elif cmd == TARGET_READ:
            out += arg
        elif cmd == SOURCE_COPY:
            srel += arg
            out += source[srel:srel + length]
            srel += length
        else:
            trel += arg
            for _ in range(length):         # byte by byte: a TargetCopy may overlap its own output
                out.append(out[trel])
                trel += 1
    if len(out) != tsize or crc32(bytes(out)) != tcrc:
        raise BpsError("target CRC32 mismatch")
    return bytes(out)


def selftest():
    for n in (0, 1, 127, 128, 129, 16511, 16512, 2 ** 32, 2 ** 40 + 5):
        v, p = decode_number(encode_number(n), 0)
        assert v == n and p == len(encode_number(n)), n
    src = bytes(range(256)) * 4
    tgt = bytearray(src)
    tgt[10:14] = b"ABCD"
    tgt[700] ^= 0xFF
    p = make(src, bytes(tgt), b"test")
    assert apply(src, p) == bytes(tgt)
    _, _, meta, acts, _, _ = parse(p)
    assert meta == b"test" and [a[0] for a in acts] == [0, 1, 0, 1, 0]
    # a hand-built patch with SourceCopy and TargetCopy (the decoder's other two actions)
    body = bytearray(MAGIC) + encode_number(4) + encode_number(8) + encode_number(0)
    body += encode_number(((2 - 1) << 2) | SOURCE_COPY) + encode_number((2 << 1) | 0)   # src[2:4]
    body += encode_number(((6 - 1) << 2) | TARGET_COPY) + encode_number(0)              # repeat
    s4, t8 = b"wxyz", b"yzyzyzyz"
    body += crc32(s4).to_bytes(4, "little") + crc32(t8).to_bytes(4, "little")
    body += crc32(bytes(body)).to_bytes(4, "little")
    assert apply(s4, bytes(body)) == t8
    try:
        apply(src[:-1], p)
        raise AssertionError("a wrong source was taken")
    except BpsError:
        pass
    print("BPS_SELFTEST pass")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("source")
    m.add_argument("target")
    m.add_argument("out")
    m.add_argument("--meta", default="")
    a_ = sub.add_parser("apply")
    a_.add_argument("source")
    a_.add_argument("patch")
    a_.add_argument("out")
    i = sub.add_parser("info")
    i.add_argument("patch")
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "selftest":
            selftest()
        elif a.cmd == "make":
            src, tgt = open(a.source, "rb").read(), open(a.target, "rb").read()
            open(a.out, "wb").write(make(src, tgt, a.meta.encode("utf-8")))
        elif a.cmd == "apply":
            src, p = open(a.source, "rb").read(), open(a.patch, "rb").read()
            open(a.out, "wb").write(apply(src, p))
        else:
            ssize, tsize, meta, acts, scrc, tcrc = parse(open(a.patch, "rb").read())
            print("source %d bytes CRC32 %08X, target %d bytes CRC32 %08X, metadata %r"
                  % (ssize, scrc, tsize, tcrc, meta.decode("utf-8", "replace")))
            off = 0
            for cmd, length, arg in acts:
                print("  %-10s %6d bytes at target offset $%05X" % (NAMES[cmd], length, off))
                off += length
    except BpsError as e:
        print("bps: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
