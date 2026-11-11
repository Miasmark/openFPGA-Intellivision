#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""LTO Flash LUIGI files (1.0.7), written from the format's specification only: "Locutus Universal
Intellivision Game Image (LUIGI) V1.0", J. Zbiciak, Left Turn Only, 6-Jul-2019 (the LTO Flash
download page; no code read). jzIntv's bin2luigi / rom2luigi / luigi2bin are run as black boxes to
make reference files from our own test images (docs/CARTFORMATS.md 8).

  python3 -I tools/mapper/luigi.py                 self-check (the spec's CRC test vectors, the
                                                   spec's encoding example, encode -> decode)
  python3 -I tools/mapper/luigi.py dump FILE       the header, blocks and tables of a .luigi

The format (spec "LUIGI File Format"): a header (version 0: 16 bytes, version 1: 32), then blocks
of {type, payload length (2 bytes, little endian), DOWCRC over those three bytes, CRC32/4 over the
payload (4 bytes, little endian), payload} until type $FF or the end of the file.

- Header: "LTO", version (0 or 1), feature flags (64 bits in version 0, 128 in version 1, little
  endian), version 1: an 8-byte source UID, reserved bytes, and a DOWCRC over the header's other
  bytes as its last byte (the spec: "CRC over entire header").
- Block $00: start of encryption (refused: the rest of the file is encrypted).
- Block $01: the tables, 1,280 bytes: the memory map (256 x 16 bits: per 256-word paragraph of the
  Intellivision map, bits 23:8 of the Locutus RAM word address), the permissions (256 x 8 bits:
  R 1, W 2, N(arrow) 4, B(ankswitched) 8) and the page-flip table (256 x 16 bits, index chapter * 16
  + page: R, W, N, PFE (page-flip enable) in bits 3:0, the page's Locutus address bits 23:12 in bits
  15:4).
- Block $02: a data hunk: a 24-bit Locutus word address, then packed words: start byte $01-$3F an
  8-bit block (N - 1 bytes, then one 16-bit word), $40-$BF a 10-bit block (N = s - $3F decles: N - 1
  packed in groups of four behind a byte of their top bits, bits 7:6 the first's, then one 16-bit
  word), $C0-$FD a 16-bit block (N = s - $BF words); $00, $FE, $FF reserved.
- Block $03: metadata (ignored); $FF: end of data.
- Feature flags: voice_compat 1:0, ecs_compat 3:2, intv2_compat 5:4, kc_compat 7:6, the compat
  fields' version 9:8, tv_compat 11:10, jlp_accel 17:16, jlp_flash (sectors) 31:22, lto_mapper 32,
  bit 63: the flags were set explicitly (0: the conversion tools' defaults). Compat fields: 00
  incompatible, 01 tolerates, 10 enhanced, 11 requires.
"""
import struct
import sys


# --------------------------------------------------------------------------------------- CRCs
def dowcrc(data, crc=0):
    """Koopman & Chakravarty's DOWCRC: poly $98, right shifting, init 0, not inverted."""
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (0x98 if crc & 1 else 0)
    return crc


def crc32_4(data, crc=0):
    """Castagnoli, Brauer, Hermann CRC32/4: poly $82F63B78, right shifting, init 0, not inverted."""
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
    return crc


# ------------------------------------------------------------------------------------ the file
class LuigiError(Exception):
    pass


def unpack_hunk(p):
    """A data hunk's payload -> (Locutus word address, [words])."""
    if len(p) < 3:
        raise LuigiError("hunk shorter than its address")
    addr = p[0] | p[1] << 8 | p[2] << 16
    out = []
    i = 3

    def take(n):
        nonlocal i
        if i + n > len(p):
            raise LuigiError("hunk ends inside a block")
        r = p[i:i + n]
        i += n
        return r

    while i < len(p):
        s = take(1)[0]
        if 0x01 <= s <= 0x3F:
            out += list(take(s - 1))
        elif 0x40 <= s <= 0xBF:
            n = s - 0x3F
            k = n - 1
            while k > 0:
                g = min(4, k)
                top = take(1)[0]
                lo = take(g)
                for j in range(g):
                    out.append((top >> (6 - 2 * j) & 3) << 8 | lo[j])
                k -= g
        elif 0xC0 <= s <= 0xFD:
            for _ in range(s - 0xBF):
                w = take(2)
                out.append(w[0] | w[1] << 8)
            continue
        else:
            raise LuigiError("reserved start byte $%02X" % s)
        w = take(2)
        out.append(w[0] | w[1] << 8)
    return addr, out


def pack_words(words):
    """Words -> packed blocks (a simple encoder: runs of 8-bit, then 10-bit, else 16-bit)."""
    out = bytearray()
    i = 0
    while i < len(words):
        # 8-bit block: up to 62 bytes then the closing word
        n8 = 0
        while i + n8 < len(words) - 1 and n8 < 62 and words[i + n8] < 0x100:
            n8 += 1
        n10 = 0
        while i + n10 < len(words) - 1 and n10 < 127 and words[i + n10] < 0x400:
            n10 += 1
        if n8 >= 4 and n8 >= n10:
            out.append(n8 + 1)
            out += bytes(words[i:i + n8])
            i += n8
        elif n10 >= 1:
            out.append(0x3F + n10 + 1)
            k = 0
            while k < n10:
                g = words[i + k:i + min(k + 4, n10)]
                out.append(sum((w >> 8 & 3) << (6 - 2 * j) for j, w in enumerate(g)))
                out += bytes(w & 0xFF for w in g)
                k += 4
            i += n10
        else:
            n = 1
            while i + n < len(words) and n < 62 and not (words[i + n] < 0x400 and i + n < len(words) - 1):
                n += 1
            out.append(0xBF + n)
            for w in words[i:i + n]:
                out += struct.pack("<H", w)
            i += n
            continue
        out += struct.pack("<H", words[i])
        i += 1
    return bytes(out)


def block(t, payload):
    hdr = bytes([t]) + struct.pack("<H", len(payload))
    return hdr + bytes([dowcrc(hdr)]) + struct.pack("<I", crc32_4(payload)) + payload


def header(flags, version=1, uid=0):
    if version == 0:
        h = b"LTO" + bytes([0]) + struct.pack("<Q", flags & (1 << 64) - 1) + bytes(3)
    else:
        h = b"LTO" + bytes([1]) + (flags & (1 << 128) - 1).to_bytes(16, "little") + struct.pack("<Q", uid) + bytes(3)
    return h + bytes([dowcrc(h)])


def encode(flags, mmap, perm, flip, hunks, version=1, meta=None, order=("meta", "tables", "hunks")):
    """flags: int; mmap / flip: 256 words; perm: 256 bytes; hunks: [(Locutus address, [words])]."""
    tab = b"".join(struct.pack("<H", x) for x in mmap) + bytes(perm) + b"".join(struct.pack("<H", x) for x in flip)
    parts = {"meta": block(3, meta) if meta else b"", "tables": block(1, tab),
             "hunks": b"".join(block(2, bytes([a & 0xFF, a >> 8 & 0xFF, a >> 16 & 0xFF]) + pack_words(w))
                               for a, w in hunks)}
    return header(flags, version) + b"".join(parts[k] for k in order) + bytes([0xFF])


class Luigi:
    """A decoded file: version, flags, mmap, perm, flip, hunks [(addr, words)], blocks [(type, len)]."""

    def __init__(self, data):
        if len(data) < 16 or data[:3] != b"LTO" or data[3] > 1:
            raise LuigiError("not a LUIGI file")
        self.version = data[3]
        hl = 16 if self.version == 0 else 32
        if len(data) < hl:
            raise LuigiError("file ends inside the header")
        if dowcrc(data[:hl - 1]) != data[hl - 1]:
            raise LuigiError("header DOWCRC")
        fb = data[4:12] if self.version == 0 else data[4:20]
        self.flags = int.from_bytes(fb, "little")
        self.mmap = self.perm = self.flip = None
        self.hunks = []
        self.blocks = []
        i = hl
        while i < len(data):
            t = data[i]
            if t == 0xFF:
                break
            if i + 8 > len(data):
                raise LuigiError("file ends inside a block header")
            ln = data[i + 1] | data[i + 2] << 8
            if dowcrc(data[i:i + 3]) != data[i + 3]:
                raise LuigiError("block header DOWCRC at %d" % i)
            pc = struct.unpack_from("<I", data, i + 4)[0]
            p = data[i + 8:i + 8 + ln]
            if len(p) != ln:
                raise LuigiError("file ends inside a block payload")
            if crc32_4(p) != pc:
                raise LuigiError("payload CRC32/4 at %d" % i)
            self.blocks.append((t, ln))
            if t == 0:
                raise LuigiError("encrypted")
            if t == 1:
                if ln != 1280:
                    raise LuigiError("tables block of %d bytes" % ln)
                self.mmap = list(struct.unpack_from("<256H", p, 0))
                self.perm = list(p[512:768])
                self.flip = list(struct.unpack_from("<256H", p, 768))
            elif t == 2:
                self.hunks.append(unpack_hunk(p))
            i += 8 + ln

    def field(self, lo, n=2):
        return self.flags >> lo & (1 << n) - 1


# ------------------------------------------------------------------------------- self-check
def self_check():
    fails = []

    def chk(c, what):
        if not c:
            fails.append(what)

    v1 = bytes(range(16))
    v2 = bytes([0x4A, 0x5A, 0x6A, 0x7A])
    v3 = bytes(8)
    v4 = bytes([0xFF] * 8)
    chk([dowcrc(v) for v in (v1, v2, v3, v4)] == [0x00, 0xB8, 0x00, 0x84], "DOWCRC test vectors")
    chk([crc32_4(v) for v in (v1, v2, v3, v4)] == [0x9BB99201, 0x02CB247E, 0x00000000, 0xC44FF94D],
        "CRC32/4 test vectors")
    # the spec's encoded example: its words from the listing
    words = [0x240, 0x100, 0x040, 0x240, 0x101, 0x2B8, 0x7A5F, 0x240, 0x7FFF, 0x004, 0x154, 0x042,
             0x2BC, 0x8040, 0x2B9, 0x1F4F, 0x004, 0x154, 0x046, 0x002, 0x1C0, 0x240, 0x12E, 0x240,
             0x102, 0x004, 0x154, 0x030, 0x001, 0x004, 0x154, 0x051, 0x56A8, 0x004, 0x150, 0x366,
             0x000, 0x220, 0x009]
    ex = bytes.fromhex("46 92 40 00 40 40 60 01 B8 5F 7A 41 80 40 FF 7F 44 12 04 54 42 BC 40 80"
                       " 41 80 B9 4F 1F 50 10 04 54 46 02 66 C0 40 2E 40 44 02 04 54 30 04 01 04 54"
                       " 51 A8 56 45 1C 04 50 66 00 80 20 09 00")
    a, w = unpack_hunk(bytes(3) + ex)
    chk(w == words, "the spec's encoded example decodes to its listing")
    chk(len(ex) == 62, "the spec's example is 62 bytes")
    # encode -> decode
    mm = [p for p in range(256)]
    pm = [3 if 0x50 <= p < 0x70 else 0 for p in range(256)]
    fl = [0] * 256
    data = list(range(0x3FF, 0, -7)) + [0xFFFF, 0x1234, 0x00, 0x55] * 20 + list(range(70))
    f = encode(0x3 << 2 | 1 << 63, mm, pm, fl, [(0x5000, data)])
    d = Luigi(f)
    chk(d.hunks == [(0x5000, data)] and d.mmap == mm and d.perm == pm and d.field(2) == 3, "encode -> decode")
    for bad in (5, 40, len(f) - 3):
        g = bytearray(f)
        g[bad] ^= 0x10
        try:
            Luigi(bytes(g))
            fails.append("a flipped bit at %d not caught" % bad)
        except LuigiError:
            pass
    print("LUIGI_SELFTEST %s%s" % ("pass" if not fails else "FAIL", "" if not fails else " (%s)" % "; ".join(fails)))
    return 1 if fails else 0


def dump(path):
    d = Luigi(open(path, "rb").read())
    print("version %d flags %032x (voice %d ecs %d jlp_accel %d jlp_flash %d lto_mapper %d explicit %d)"
          % (d.version, d.flags, d.field(0), d.field(2), d.field(16), d.field(22, 10), d.field(32, 1), d.field(63, 1)))
    print("blocks", d.blocks)
    for p in range(256):
        if d.perm[p]:
            print("  para $%02X00 -> locutus $%06X perm %X" % (p, d.mmap[p] << 8, d.perm[p]))
    for i in range(256):
        if d.flip[i]:
            print("  flip chap %X page %X -> locutus $%06X bits %X" % (i >> 4, i & 15, (d.flip[i] >> 4) << 12, d.flip[i] & 15))
    for a, w in d.hunks:
        print("  hunk $%06X: %d words" % (a, len(w)))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "dump":
        dump(sys.argv[2])
    else:
        sys.exit(self_check())
