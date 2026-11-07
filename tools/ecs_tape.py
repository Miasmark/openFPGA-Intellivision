#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""ecs_tape: the ECS cassette as a file (docs/ECS_NOTES.md 6; the golden model of
src/fpga/core/intv_tape.sv), and a developer tool for tape files.

The tape (the owner's decisions of 2026-11-06): one GAME.ecs per game (the Pocket's nonvolatile
data slot 0x107, 16,384 bytes), jzIntv's .ecs byte stream. A block is what the ECS ROM's tape
engine writes to $E1 in one save:

    $AA x k        sync (k >= 1; the ECS ROM writes 9)
    $00
    -N             16 bits, low byte first
    N data bytes   (ECS BASIC: the name in the first 4, ASCII, space-padded)

so a jzIntv .ecs file is a one-block tape. The tape holds blocks back to back from byte 0, newest
first, then zeros. The UART at $00E0-$00E3, as the ECS ROM uses it (DESIGN_CASSETTE.md 1):

    $E0 read   status: bit 1 transmitter ready (always), bit 0 a byte under the head (playing,
               head < the tape's end); every other bit 0 (bit 3 set would hang the printer code)
    $E1 read   the byte under the head (upper byte 0); playing, the head moves on one
    $E1 write  recording: the save's next byte
    $E2 write  the mode: bit 4 the motor, bit 5 record ($1D play, $39 record, $00 off)
    $E0 write, $E3: ignored; reads of $E2 / $E3 give 0

Fast: a byte is ready whenever the ROM looks (it takes one a frame at most, about 2x a real
300-baud tape). The rules:

  - rewind: the head goes to 0 at a machine reset (a game load, the menu's Reset) and when the
    motor starts after REWIND_IDLE CPU cycles (60 frames, 1 s) or more with it off. The ROM's name
    search (CLOD) restarts the motor within a few frames between blocks, so it reads on.
  - a save: the sync is counted until $00, then the length; the block (k + 3 + N bytes) goes to
    the front: everything on the tape moves up by its length (what passes the tape's end is lost)
    and its bytes are written at 0 on. It is committed when the motor stops (or record goes off)
    with all N data bytes in: an older block of the same name (its first 4 data bytes, both N >= 4)
    is removed, the tape's end is found again (a block cut at the end is dropped) and the rest is
    zeroed. A save that stops short is taken out again (the tape moves back down). A block over
    16,384 bytes is not recorded.
  - the tape's end (tape_len): the first offset that does not start a whole block (sync, $00,
    length, all within the tape), found at a load with a tape file, after a save and an erase.
  - a load without a tape file, and the menu's "Erase ECS tape": all zeros.

Save state (intv_tape's words): the head, the mode, the motor-off count; not the tape (a state
load never undoes a save), and not a save in progress (a state load abandons one: it is taken out
as one stopped short).

  ecs_tape.py list FILE                 the blocks of a tape (.ecs) or .sav-less dump
  ecs_tape.py towav FILE.ecs OUT.wav    300-baud FSK (4,800 Hz 1, 2,400 Hz 0; 8 data bits LSB
                                        first, odd parity, 2 stop bits), for a real ECS
  ecs_tape.py fromwav IN.wav OUT.ecs    the reverse (a recording of a real ECS save)
  ecs_tape.py join OUT.ecs A.ecs ...    one tape of several (the first is the newest)
  ecs_tape.py selftest
"""

import math
import struct
import sys
import wave

SIZE = 16384                    # the tape: data slot 0x107's size
NAME_LEN = 4
FRAME = 14934                   # CPU cycles a frame (intv_system)
REWIND_IDLE = 60 * FRAME        # motor off this long: the next start rewinds
MODE_MOTOR, MODE_REC = 0x10, 0x20


def parse_block(t, o, limit):
    """The block at offset o: (k, N, length) if a whole block starts there and ends by limit, else
    None."""
    k = 0
    while o + k < limit and t[o + k] == 0xAA:
        k += 1
    if k == 0 or o + k + 3 > limit or t[o + k] != 0x00:
        return None
    n = (-(t[o + k + 1] | t[o + k + 2] << 8)) & 0xFFFF
    length = k + 3 + n
    if o + length > limit:
        return None
    return k, n, length


def blocks(t, limit=None):
    """[(offset, k, N, length)] from 0 to the tape's end."""
    limit = len(t) if limit is None else limit
    out, o = [], 0
    while True:
        b = parse_block(t, o, limit)
        if b is None:
            return out
        out.append((o,) + b)
        o += b[2]


def tape_end(t, limit=None):
    bl = blocks(t, limit)
    return bl[-1][0] + bl[-1][3] if bl else 0


def name_of(t, o, k, n):
    return bytes(t[o + k + 3:o + k + 3 + NAME_LEN]) if n >= NAME_LEN else None


class Tape:
    """The tape and the ECS UART's tape side (intv_tape.sv)."""

    def __init__(self, idle=REWIND_IDLE):
        self.t = bytearray(SIZE)
        self.tape_len = 0
        self.idle = idle                # the rewind's motor-off time (benches use less)
        self.reset()

    # -- media -------------------------------------------------------------
    def load_file(self, data):
        """A load with a tape file (the Pocket writes it before the load completes)."""
        self.t = bytearray(data[:SIZE].ljust(SIZE, b"\0"))
        self.tape_len = tape_end(self.t)
        self.t[self.tape_len:] = bytes(SIZE - self.tape_len)     # past the end: zeros

    def clear(self):
        """A load without a tape file, and the menu's Erase ECS tape."""
        self.t = bytearray(SIZE)
        self.tape_len = 0
        self.head = 0

    def file(self):
        """The slot's bytes (the Pocket saves them as GAME.ecs)."""
        return bytes(self.t)

    # -- machine -----------------------------------------------------------
    def reset(self):
        """Machine reset: rewound, motor off; a save in progress is taken out."""
        if getattr(self, "rec", None) is not None:
            self.abandon()
        self.head = 0
        self.mode = 0
        self.off_at = None              # the cycle the motor stopped (None: off since the reset)
        self.rec = None                 # a save in progress: dict(ph, k, n, got, length)

    @property
    def playing(self):
        return self.mode & MODE_MOTOR and not self.mode & MODE_REC

    @property
    def recording(self):
        return bool(self.mode & MODE_MOTOR and self.mode & MODE_REC)

    def read(self, a, cycle):
        if a == 0x00E0:
            return 0x0002 | (1 if self.playing and self.head < self.tape_len else 0)
        if a == 0x00E1:
            v = self.t[self.head] if self.head < SIZE else 0
            if self.playing and self.head < self.tape_len:
                self.head += 1
            return v
        return 0

    def write(self, a, v, cycle):
        if a == 0x00E1:
            if self.recording and self.rec is not None:
                self._rec_byte(v & 0xFF)
        elif a == 0x00E2:
            self._mode(v & 0xFF, cycle)

    def _mode(self, m, cycle):
        was_motor, was_rec = self.mode & MODE_MOTOR, self.recording
        self.mode = m
        motor = m & MODE_MOTOR
        if motor and not was_motor:
            if self.off_at is None or cycle - self.off_at >= self.idle:
                self.head = 0
        if not motor and was_motor:
            self.off_at = cycle
        if was_rec and not self.recording:
            self._finish()
        if self.recording and not was_rec:
            self.rec = dict(ph="sync", k=0, n=0, got=0, length=0, lo=0)

    # -- saving ------------------------------------------------------------
    def _rec_byte(self, b):
        r = self.rec
        if r["ph"] == "sync":
            if b == 0xAA:
                r["k"] += 1
            elif b == 0x00 and r["k"] > 0:
                r["ph"] = "lo"
            else:
                r["k"] = 0
        elif r["ph"] == "lo":
            r["lo"], r["ph"] = b, "hi"
        elif r["ph"] == "hi":
            r["n"] = (-(r["lo"] | b << 8)) & 0xFFFF
            r["length"] = r["k"] + 3 + r["n"]
            if r["length"] > SIZE:
                r["ph"] = "skip"                    # too long for the tape: not recorded
                return
            # the block goes to the front: the tape moves up by its length
            ln = r["length"]
            self.t[ln:] = self.t[:SIZE - ln]
            self.t[:r["k"]] = b"\xAA" * r["k"]
            self.t[r["k"]:r["k"] + 3] = bytes((0, r["lo"], b))
            r["ph"] = "data"
        elif r["ph"] == "data":
            if r["got"] < r["n"]:
                self.t[r["k"] + 3 + r["got"]] = b
                r["got"] += 1

    def _finish(self):
        r, self.rec = self.rec, None
        if r is None or r["ph"] in ("sync", "lo", "hi", "skip"):
            return
        ln = r["length"]
        if r["got"] < r["n"]:
            # stopped short: taken out again (the tape moves back down; what had passed the
            # tape's end is gone)
            self.t[:SIZE - ln] = self.t[ln:]
            self.t[SIZE - ln:] = bytes(ln)
        else:
            new = name_of(self.t, 0, r["k"], r["n"])
            o = ln
            while new is not None:
                b = parse_block(self.t, o, SIZE)
                if b is None:
                    break
                k, n, bl = b
                if name_of(self.t, o, k, n) == new:
                    self.t[o:SIZE - bl] = self.t[o + bl:]
                    self.t[SIZE - bl:] = bytes(bl)
                    break
                o += bl
        self.tape_len = tape_end(self.t)
        self.t[self.tape_len:] = bytes(SIZE - self.tape_len)

    def abandon(self):
        """A state load: a save in progress is taken out as one stopped short."""
        if self.rec is not None and self.rec["ph"] == "data":
            self.rec["got"] = -1
            self._finish()
        self.rec = None

    # -- save state (intv_tape's words) ------------------------------------
    def state(self, cycle):
        """[0] head (13:0), mode (23:16); [1] the motor-off count (CPU cycles, saturating at
        2^20 - 1; all ones when off since the reset)."""
        if self.mode & MODE_MOTOR:
            off = 0
        elif self.off_at is None:
            off = (1 << 20) - 1
        else:
            off = min(cycle - self.off_at, (1 << 20) - 1)
        return [self.head | self.mode << 16, off]

    def load_state(self, words, cycle):
        self.abandon()
        self.head = words[0] & 0x3FFF
        self.mode = words[0] >> 16 & 0xFF
        off = words[1] & 0xFFFFF
        self.off_at = None if off == (1 << 20) - 1 else cycle - off


# ---------------------------------------------------------------- the .wav side
RATE = 44100
BAUD, F1, F0 = 300, 4800, 2400


def to_wav(data, path, rate=RATE):
    """300-baud FSK: a start bit (0), 8 data bits LSB first, odd parity, 2 stop bits (1); 1 s of
    the 1 tone (idle) before and after."""
    bits = [1] * BAUD
    for b in data:
        d = [b >> i & 1 for i in range(8)]
        bits += [0] + d + [(sum(d) + 1) & 1, 1, 1]
    bits += [1] * BAUD
    spb = rate / BAUD
    out, ph = bytearray(), 0.0
    for i, bit in enumerate(bits):
        f = F1 if bit else F0
        for _ in range(int(round((i + 1) * spb)) - int(round(i * spb))):
            out += struct.pack("<h", int(12000 * math.sin(ph)))
            ph += 2 * math.pi * f / rate
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(out))


def from_wav(path, speed=1.0):
    """Bytes from a recording: the tone with more energy over two periods of the low tone, then
    the UART framing. Returns (bytes, framing / parity errors)."""
    with wave.open(path) as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    if sw != 2:
        raise SystemExit("16-bit .wav only")
    x = struct.unpack("<%dh" % (n * ch), raw)[::ch]
    f1, f0, baud = F1 * speed, F0 * speed, BAUD * speed
    L = int(sr / f0 * 2)

    def energy(f):
        pc, ps = [0.0], [0.0]
        for i, v in enumerate(x):
            pc.append(pc[-1] + v * math.cos(2 * math.pi * f * i / sr))
            ps.append(ps[-1] + v * math.sin(2 * math.pi * f * i / sr))
        return lambda a: (pc[a + L] - pc[a]) ** 2 + (ps[a + L] - ps[a]) ** 2

    e1, e0 = energy(f1), energy(f0)
    m = len(x) - L
    lv = [1 if e1(i) > e0(i) else 0 for i in range(m)]
    en = [e1(i) + e0(i) for i in range(0, m, 50)]
    thr = max(en) / 16 if en else 0                 # a tone present: within 12 dB of the loudest
    spb = sr / baud
    out, errs, i = bytearray(), 0, 0
    while i < m - int(12 * spb):
        if lv[i] == 0 and lv[i + int(spb / 2)] == 0 and e1(i) + e0(i) > thr:
            bits = [lv[int(i + spb * (k + 1.5))] for k in range(11)]
            d = sum(b << k for k, b in enumerate(bits[:8]))
            errs += not ((sum(bits[:8]) + bits[8]) % 2 == 1 and bits[9] == 1)
            out.append(d)
            i += int(spb * 10.5)
        else:
            i += 1
    return bytes(out), errs


# ---------------------------------------------------------------- self-test
def _save(tp, cyc, data, name=None, sync=9, stop_after=None):
    """Drive a save as the ECS ROM does: record on, sync, $00, -N, the data, motor off."""
    body = (name.ljust(NAME_LEN).encode() if name else b"") + data
    n = len(body)
    tp.write(0xE2, 0x39, cyc)
    seq = [0xAA] * sync + [0x00, (-n) & 0xFF, ((-n) >> 8) & 0xFF] + list(body)
    for j, b in enumerate(seq):
        if stop_after is not None and j == stop_after:
            break
        tp.write(0xE1, b, cyc)
    tp.write(0xE2, 0x00, cyc)
    return n


def _load(tp, cyc):
    """Read one block as the ROM does (wait for sync, $00, length, data). None at the end."""
    tp.write(0xE2, 0x1D, cyc)
    got, ph, k, n, lo = [], "sync", 0, 0, 0
    while True:
        if not tp.read(0xE0, cyc) & 1:
            tp.write(0xE2, 0x00, cyc)
            return None
        b = tp.read(0xE1, cyc)
        if ph == "sync":
            if b == 0xAA:
                k += 1
            elif b == 0 and k:
                ph = "lo"
            else:
                k = 0
        elif ph == "lo":
            lo, ph = b, "hi"
        elif ph == "hi":
            n, ph = (-(lo | b << 8)) & 0xFFFF, "data"
            if n == 0:
                break
        else:
            got.append(b)
            if len(got) == n:
                break
    tp.write(0xE2, 0x00, cyc)
    return bytes(got)


def selftest():
    fails = []

    def chk(c, what):
        print("  %s %s" % ("ok  " if c else "FAIL", what))
        if not c:
            fails.append(what)

    tp = Tape()
    cyc = 10 ** 7
    chk(tp.read(0xE0, cyc) == 2, "a blank tape: status $0002 (ready, no byte)")
    _save(tp, cyc, b"first program", "AAA")
    _save(tp, cyc + 10, b"second", "BBB")
    bl = blocks(tp.t)
    chk(len(bl) == 2 and name_of(tp.t, 0, bl[0][1], bl[0][2]) == b"BBB " and tp.tape_len == bl[1][0] + bl[1][3],
        "two saves: two blocks, newest first, the end after them")
    _save(tp, cyc + 20, b"first, changed", "AAA")
    bl = blocks(tp.t)
    names = [name_of(tp.t, o, k, n) for o, k, n, _ in bl]
    chk(names == [b"AAA ", b"BBB "] and all(v == 0 for v in tp.t[tp.tape_len:]),
        "a save under an existing name replaces it and goes to the front; the rest is zeros")
    cyc += REWIND_IDLE + 100
    d = _load(tp, cyc)
    chk(d == b"AAA first, changed", "a load after 1 s: rewound, the newest block")
    d = _load(tp, cyc + 1000)
    chk(d == b"BBB second", "the next load within 1 s reads on: the next block")
    chk(_load(tp, cyc + 2000) is None, "past the last block: no byte (the ROM waits, as at a tape's end)")
    # a save that stops short is taken out
    before = bytes(tp.t)
    _save(tp, cyc + 3000, b"x" * 100, "CCC", stop_after=60)
    chk(bytes(tp.t) == before, "a save stopped short: the tape as before")
    # a full tape drops the oldest
    tp2 = Tape()
    for i in range(6):
        _save(tp2, cyc, bytes([i]) * 4000, "P%d" % i)
    names = [name_of(tp2.t, o, k, n) for o, k, n, _ in blocks(tp2.t)]
    chk(names == [b"P5  ", b"P4  ", b"P3  ", b"P2  "] and tp2.tape_len == 4 * (12 + 4004),
        "a full tape: the oldest blocks are dropped, whole")
    # too long
    tp3 = Tape()
    _save(tp3, cyc, b"z" * SIZE, "BIG")
    chk(tp3.tape_len == 0 and not any(tp3.t), "a block over 16,384 bytes: not recorded")
    # a jzIntv file is a one-block tape
    one = bytes([0xAA] * 9 + [0, 0xFA, 0xFF]) + b"ROAD\x01\x02"
    tp4 = Tape()
    tp4.load_file(one)
    tp4.reset()
    chk(tp4.tape_len == len(one) and _load(tp4, cyc) == b"ROAD\x01\x02", "a jzIntv .ecs file loads as a one-block tape")
    # state
    tp4.reset()
    tp4.write(0xE2, 0x1D, cyc)
    for _ in range(5):
        tp4.read(0xE1, cyc)
    w = tp4.state(cyc + 7)
    tp5 = Tape()
    tp5.load_file(one)
    tp5.load_state(w, cyc + 7)
    chk(tp5.head == 5 and tp5.mode == 0x1D, "a state: the head and the mode come back")
    tp4.write(0xE2, 0x00, cyc + 10)
    w = tp4.state(cyc + 10 + 500)
    chk(w[1] == 500, "a state: the motor-off count")
    # wav round trip
    import tempfile
    import os
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "t.wav")
        data = one + b"\x00\x55\xFF"
        to_wav(data, p)
        back, errs = from_wav(p)
        chk(back == data and errs == 0, "the .wav round trip (%d bytes, %d errors)" % (len(back), errs))
    print("TAPE_SELFTEST %s" % ("pass" if not fails else "FAIL (%d)" % len(fails)))
    return 0 if not fails else 1


def main(argv):
    if len(argv) < 2 or argv[1] == "selftest":
        return selftest()
    cmd = argv[1]
    if cmd == "list":
        t = open(argv[2], "rb").read()
        for o, k, n, ln in blocks(t):
            nm = name_of(t, o, k, n)
            print("%5d  sync %d  %5d data bytes  name %r" % (o, k, n, nm))
        print("end of the tape at %d of %d" % (tape_end(t), len(t)))
        return 0
    if cmd == "towav":
        to_wav(open(argv[2], "rb").read(), argv[3])
        return 0
    if cmd == "fromwav":
        data, errs = from_wav(argv[2])
        open(argv[3], "wb").write(data)
        print("%d bytes, %d framing / parity errors" % (len(data), errs))
        return 0
    if cmd == "join":
        out = b"".join(open(p, "rb").read() for p in argv[3:])
        if len(out) > SIZE:
            raise SystemExit("over %d bytes" % SIZE)
        open(argv[2], "wb").write(out)
        return 0
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
