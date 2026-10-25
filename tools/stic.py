#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""stic: model of the STIC (AY-3-8900-1) for build step 4, backgrounds only.

The golden model for the step-4 STIC RTL (DESIGN.md 2.4, 3 row 6, 9 step 4).
It is driven by tools/intv_system.py (SystemBus owns the RAMs and the frame
timing; this module owns the STIC's registers and its view of the
graphics bus). MOBs and collisions are build step 5: the MOB registers are
stored and read back, but not drawn. docs/STIC_NOTES.md lists every fact,
its source and every place where the sources disagree.

Registers (CPU side, unchanged from the step-3 stub)
  Read masks per register class as MAME's stic_device::read returns them
  (MAME stic.cpp:1139-1201; DESIGN 13.7). A write to $20 (display enable)
  sets the handshake, the start of every frame clears it (MAME
  stic.cpp:1111-1116, 1270-1274). Reading $21 selects Color Stack mode,
  writing it Foreground/Background mode (wiki STIC "Display Background").
  Closed accesses read the address offset and drop writes (MAME
  intv_m.cpp:484-512); open = bus-copy window or handshake clear.

Background (rendered once per frame, for the frame's active display)
  BACKTAB words come from the 20-word row FIFO in System RAM, loaded by
  the row fetches (RA-3-9600 datasheet, GI 1980 catalog p.5-18; wiki STIC
  Bus Request). Color Stack mode: card bits 0-2 + 12 foreground, 3-10 GROM
  card (3-8 for GRAM), 11 GRAM, 13 advance; bit 12 set with bit 11 clear is
  a Colored Squares card (quadrant colours 0-6 direct, 7 = top of the
  stack, no advance). The stack restarts at entry 0 every frame and
  advances before the card that carries the bit (S9 stic.txt:334-436;
  MAME stic.cpp:668-734). Foreground/Background mode: bits 0-2 foreground,
  3-8 card (GROM 0-63 or GRAM 0-63), 11 GRAM, background bits 9-10 = 0-1,
  13 = 2, 12 = 3 (S9 stic.txt:441-471; MAME stic.cpp:736-775).
  Border colour fills the frame around the 159 x 96 playfield (the 20th
  column shows 7 pixels; GI 1980 catalog p.5-10). Horizontal / vertical
  delay ($30/$31, 0-7) move the card grid right / down; the uncovered
  strip shows the border colour; border extension ($32 bit 0 left, bit 1
  top) blocks an 8-pixel strip with the border colour (MAME
  stic.cpp:1102-1108; S9 stic.txt says the strip shows the background
  colour: STIC_NOTES D6). A frame whose display was not enabled shows the
  border colour only (MAME stic.cpp:1132-1135; STIC_NOTES D7).

Picture
  One frame is W x H = 189 x 240 palette indices (0-15), laid out as
  MAME's bitmap: 13 border pixels left, 160 - 1 playfield, 17 right; 12 x 2
  lines top, 96 x 2 playfield lines (each card row of 8 pixels is 16
  scanlines, each background pixel row two), 12 x 2 bottom (MAME stic.h:41-
  61). So a model frame and a MAME snapshot compare pixel for pixel; the
  RTL's raster placement is fixed in the RTL lane, not here.

Timing (cycles = CPU cycles from the frame start = SR1 / VBlank start)
  mode "stic" (the hardware model, DESIGN 2.4 and STIC_NOTES T1-T6):
    - INTRM and the bus-copy window: cycles 0-3789 (as step 3).
    - frame BUSRQ 3790-3831 (42 cycles; MAME stic.h:49) if the display
      is enabled at 3790.
    - row fetch r: BUSRQ from R = 3876 + 114 x VDR + 912 x r for 114 cycles
      (one scanline of warning, one of fetch; wiki STIC Bus Request), for
      every r with R + 114 <= 14934 (12 fetches, 13 with VDR = 0; GI 1980
      p.5-10: "SR2 is issued thirteen or fourteen times per picture frame
      depending on picture offset", the frame BUSRQ being the first). The
      fetch of row r is cycle R + 57 (MAME stic.h:51 FIRST_FETCH = 3933).
      The row loads only if the CPU acknowledged (BUSAK) by the fetch
      cycle; otherwise the FIFO keeps the previous row (wiki STIC Bus
      Request). The FIFO's address counter restarts at 0 on INTAK and
      steps by 20 per loaded row (RA-3-9600, GI 1980 p.5-18).
  mode "mame": MAME as it runs (STIC_NOTES T2): no BUSRQ is seen by the
    CPU (MAME's adjust_icount runs outside the CPU's timeslice); row r is
    copied from System RAM at the first instruction boundary at or after
    vblank + 3891 + 114 x VDR(at vblank) + 802 x r (MAME intv_m.cpp:670-676);
    the row counter restarts at every vblank; the frame is drawn at the
    vblank boundary (MAME intv_m.cpp:683).
  mode "none": the step-3 system (no BUSRQ). Rows are copied at the
    "stic" fetch cycles, as if every request were acknowledged at once.

Pictures in modes "stic" and "none" (the RTL, src/fpga/core/intv_stic.sv;
build step 4) differ from mode "mame" in what decides a frame's picture,
because the RTL draws line by line and cannot look ahead:
  - the display enable and the border colour are taken at the end of the
    VBlank window (after the CPU's accesses in cycles 0-3789), not at the
    frame's end: a $20 write after cycle 3,789 leaves that frame blank
    (STIC_NOTES D8), and a border colour written later in a blank frame
    shows from the next frame on;
  - picture rows 0-20 (raster lines 46-66, before the window ends) show the
    previous frame's border colour; the RTL switches its border colour at
    line 67 (picture row 21);
  - the other registers, GRAM and the colour-stack mode are read during the
    display, where they are closed to the CPU when the display is enabled,
    so they equal the values at the frame's end that draw() uses.
Picture n of the RTL is raster lines 46-261 of frame n - 1 and lines 0-23 of
frame n, pixel clocks 24-212 (pocket_video PF_X0 = 37 is picture x = 13).
The FIFO's address counter stops once it reaches the end of System RAM
(352 words; the model and the RTL both stop it at 360) and restarts at
INTAK in modes "stic" and "none", at every vblank in mode "mame".
"""

FRAME = 14934            # CPU cycles per frame (57 x 262; DESIGN 2.4)
VBLANK = 3790            # INTRM / bus-copy window (MAME stic.h:50)
LINE = 57                # CPU cycles per scanline (MAME stic.h:47)
CARD_ROWS, CARD_COLS = 12, 20
FRAME_BUSRQ = 42         # MAME stic.h:49 ("approximate")
SYSRAM_WORDS = 352
PREV_BORDER_ROWS = 21    # RTL picture rows 0-20 show the previous border (see above)
ROW0_REQ = 3876          # row 0 BUSRQ: FIRST_FETCH (MAME stic.h:51) - 1 line
ROW_PERIOD = 16 * LINE   # 912: one card row = 16 scanlines
ROW_HOLD = 2 * LINE      # 114: request line + fetch line (wiki)
MAME_ROW_BUSRQ = 110     # MAME stic.h:48
MAME_FIRST = 3933 - FRAME_BUSRQ   # MAME intv_m.cpp:673

# picture layout (MAME stic.h:41-61)
OV_L, OV_R, OV_T, OV_B = 13, 17, 12, 12
W = OV_L + CARD_COLS * 8 - 1 + OV_R          # 189
H = (OV_T + CARD_ROWS * 8 + OV_B) * 2        # 240

# Register classes: (fixed bits, kept bits) as MAME's read returns them.
STIC_REGS = 0x33
STIC_DER, STIC_GMR = 0x20, 0x21
CSR, BCR, HDR, VDR, CBR = 0x28, 0x2C, 0x30, 0x31, 0x32
STIC_DEF = [(0x3FFF, 0x0000)] * 0x40
for _i in range(8):
    STIC_DEF[0x00 + _i] = (0x3800, 0x07FF)     # MXR
    STIC_DEF[0x08 + _i] = (0x3000, 0x0FFF)     # MYR
    STIC_DEF[0x10 + _i] = (0x0000, 0x3FFF)     # MAR
    STIC_DEF[0x18 + _i] = (0x3C00, 0x03FF)     # MCR
for _i in (0x28, 0x29, 0x2A, 0x2B, 0x2C):       # CSR0-3, BCR
    STIC_DEF[_i] = (0x3FF0, 0x000F)
STIC_DEF[HDR] = STIC_DEF[VDR] = (0x3FF8, 0x0007)
STIC_DEF[CBR] = (0x3FFC, 0x0003)

MODES = ("none", "stic", "mame")


class Stic:
    """The STIC. `bus` is the SystemBus: it owns grom, gram, sysram and
    the frame timing (bus.timing, bus.tcycle)."""

    def __init__(self, bus, mode="none"):
        if mode not in MODES:
            raise ValueError("STIC mode %r" % (mode,))
        self.bus = bus
        self.mode = mode
        self.regs = [0] * STIC_REGS
        self.frames = []                # (picture number, picture) as drawn
        self.keep_frames = None         # None: all; set(): those numbers only
        self.on_frame = None            # callback(n, picture, info)
        self.fifo = [0] * CARD_COLS     # System RAM's row FIFO
        self.counter = 0                # its address counter (RA-3-9600)
        self.cur = None                 # the frame being displayed
        self.rows = [None] * (CARD_ROWS + 1)
        self.next_frame = bus.timing.first
        self.stats = []                 # per frame (see _finish)
        self.prev_bcr = 0               # modes stic/none: border of the frame before
        self.reset()

    def reset(self):
        """Machine reset (MAME stic.cpp:448-498: registers, mode, handshake).
        The frame timing and the System RAM FIFO go on."""
        self.regs[:] = [0] * STIC_REGS
        self.hs_frame = None            # frame in which $20 was written
        self.csmode = 0

    # -- handshake and access window ----------------------------------------
    def handshake(self, frame):
        return self.hs_frame is not None and self.hs_frame == frame

    def read(self, a, frame, open_):
        """CPU read of $0000-$003F (a = offset)."""
        if not open_:
            return a                    # MAME intv_m.cpp:484-490
        if a == STIC_GMR:
            self.csmode = 1
        if a >= STIC_REGS:
            return 0x3FFF
        fixed, keep = STIC_DEF[a]
        return fixed | (self.regs[a] & keep)

    def alias_mode_read(self, open_):
        """A read of $4021/$8021/$C021 (DESIGN 2.6)."""
        if open_:
            self.csmode = 1

    def write(self, n, value, frame, open_):
        if not open_:
            return
        if n == STIC_DER:
            self.hs_frame = frame
        elif n == STIC_GMR:
            self.csmode = 0
        if n < STIC_REGS:
            if 0x18 <= n < 0x20:
                value &= ~(1 << (n & 7))   # MAME stic.cpp:1258-1266
            self.regs[n] = value & STIC_DEF[n][1]

    # -- BUSRQ (mode "stic") -------------------------------------------------
    def schedule(self, vdr):
        """[(kind, request cycle, release cycle, fetch cycle or None)] for a
        frame with the display enabled, relative to the frame start."""
        s = [("frame", VBLANK, VBLANK + FRAME_BUSRQ, None)]
        r = 0
        while True:
            req = ROW0_REQ + 2 * LINE * vdr + ROW_PERIOD * r
            if req + ROW_HOLD > FRAME:
                break
            s.append(("row%d" % r, req, req + ROW_HOLD, req + LINE))
            r += 1
        return s

    def busrq(self, cycle):
        """BUSRQ* as the CPU sees it at `cycle` (model cycle)."""
        if self.mode != "stic":
            return False
        t = self.bus.tcycle(cycle)
        self.advance(t)
        cur = self.cur
        if cur is None or not cur["sched"]:
            return False
        rel = t - cur["start"]
        for i, (kind, req, end, fetch) in enumerate(cur["sched"]):
            if req <= rel < end:
                if i not in cur["ack"]:
                    cur["ack"][i] = rel
                    if fetch is not None:
                        self._row_fetch(int(kind[3:]), rel, rel <= fetch)
                return True
        return False

    def intak(self, t):
        if self.mode != "mame":
            self.counter = 0

    # -- event processing ----------------------------------------------------
    def advance(self, t, boundary=False):
        """Process everything up to timing cycle t. In mode "mame" events
        happen only at instruction boundaries (MAME timers run between CPU
        time slices), so only boundary calls process them."""
        if self.mode == "mame" and not boundary:
            return
        tm = self.bus.timing
        while True:
            cur = self.cur
            if cur is not None:
                if cur["defer"] and cur["start"] + VBLANK <= t:
                    self.window_end()
                self._advance_rows(t)
            k = self.next_frame
            st = tm.start(k)
            if st is None or st > t:
                break
            self._frame_start(k, st)

    def _advance_rows(self, t):
        cur = self.cur
        p = cur["pending"]
        if self.mode == "none":
            while p and cur["start"] + p[0][1] <= t:
                r, fetch = p.pop(0)
                self._row_fetch(r, fetch, True)
        elif self.mode == "stic":
            # requests nobody acknowledged before their release: missed rows
            while p and cur["start"] + p[0][2] <= t:
                i, r, end = p.pop(0)
                if i not in cur["ack"]:
                    self._row_fetch(r, None, False)
        else:
            while p and cur["vstart"] + p[0][1] <= t:
                r, _ = p.pop(0)
                self._row_fetch(r, t - cur["start"], True)

    def _frame_start(self, k, st):
        """Frame k starts at timing cycle st: draw frame k - 1, begin k."""
        if self.cur is not None:
            self._finish()
        self.next_frame = k + 1
        vdr = self.regs[VDR]
        cur = {"k": k, "start": st, "ack": {}, "pending": [], "fetches": [],
               "sched": [], "vdr": vdr, "defer": False}
        if self.mode == "mame":
            # MAME intv_m.cpp:662-676: row timers from the vblank time, the
            # delay as it is at the vblank, row counter back to 0
            cur["vstart"] = self.bus.timing.vstart(k)
            cur["pending"] = [(r, MAME_FIRST + 2 * LINE * vdr + (ROW_PERIOD - MAME_ROW_BUSRQ) * r)
                              for r in range(CARD_ROWS)]
            self.counter = 0
        else:
            # fixed at the end of VBlank, when the registers close
            cur["defer"] = True
        self.cur = cur
        self.rows = [None] * (CARD_ROWS + 1)

    def window_end(self):
        """End of the current frame's VBlank window: fix its BUSRQ schedule
        (only with the display enabled; a blanked frame fetches nothing)."""
        cur = self.cur
        cur["defer"] = False
        cur["en"] = self.handshake(cur["k"])    # modes stic/none: the picture's enable
        cur["bcr"] = self.regs[BCR] & 0xF       # and border colour
        if not cur["en"]:
            return
        vdr = self.regs[VDR]
        cur["vdr"] = vdr
        sched = self.schedule(vdr)
        if self.mode == "stic":
            cur["sched"] = sched
            cur["pending"] = [(i, int(s[0][3:]), s[2]) for i, s in enumerate(sched)
                              if s[0].startswith("row")]
        else:                           # "none": every row loads at its fetch cycle
            cur["pending"] = [(int(s[0][3:]), s[3]) for s in sched if s[0].startswith("row")]

    def _row_fetch(self, r, rel, ok):
        """Row fetch r of the current frame: load the FIFO from System RAM
        (BACKTAB) through the address counter, if acknowledged in time."""
        cur = self.cur
        words = None
        if ok:
            a = self.counter
            sysram = self.bus.sysram
            words = [sysram[a + j] & 0x3FFF if a + j < len(sysram) else 0x3FFF
                     for j in range(CARD_COLS)]
            self.fifo = words
            if a < SYSRAM_WORDS:        # the counter stops past System RAM
                self.counter = a + CARD_COLS
        if r < len(self.rows):
            self.rows[r] = list(self.fifo)
        cur["fetches"].append((r, rel, ok, a if ok else self.counter))

    # -- drawing -------------------------------------------------------------
    def _finish(self):
        """Draw the current frame k (its active display has just ended) as
        picture n = k + 1: the picture shown when frame k + 1 starts, as
        MAME draws it at its vblank k + 1 (MAME intv_m.cpp:683)."""
        cur = self.cur
        k = cur["k"]
        n = k + 1
        if cur["defer"]:
            self.window_end()
        if self.mode != "mame":
            self._advance_rows(1 << 62)
        enabled = self.handshake(k)
        border = None
        if self.mode != "mame":
            enabled, border = cur["en"], cur["bcr"]
        stolen = 0
        for i, (kind, req, end, fetch) in enumerate(cur["sched"]):
            a = cur["ack"].get(i)
            if a is not None:
                stolen += end - a
        self.stats.append({"n": n, "enabled": enabled, "vdr": cur["vdr"], "stolen": stolen,
                           "requests": len(cur["sched"]),
                           "loaded": sum(1 for f in cur["fetches"] if f[2])})
        prev_bcr = self.prev_bcr
        if self.mode != "mame":
            self.prev_bcr = border
        want = self.keep_frames is None or n in self.keep_frames
        if not (want or self.on_frame is not None):
            return
        rows = [r if r is not None else list(self.fifo) for r in self.rows]
        pic, fg, cards = self.draw(enabled, rows, border)
        if self.mode != "mame":
            n0 = PREV_BORDER_ROWS * W
            pic[:n0] = bytes([prev_bcr]) * n0
        if want:
            self.frames.append((n, pic))
        if self.on_frame is not None:
            info = {"n": n, "start": cur["start"], "enabled": enabled, "vdr": cur["vdr"],
                    "csmode": self.csmode, "fetches": cur["fetches"], "stolen": stolen,
                    "cards": cards, "fg": fg, "rows": rows}
            self.on_frame(n, pic, info)

    def draw(self, enabled, rows, border=None):
        """(picture, foreground mask, card fetch log) from the registers,
        GRAM/GROM now and the given 12 rows of BACKTAB words. border: the
        border colour (default: register $2C now)."""
        r = self.regs
        if border is None:
            border = r[BCR] & 0xF
        pic = bytearray([border]) * (W * H)
        fg = bytearray(W * H)
        cards = []
        if not enabled:
            return pic, fg, cards
        grom, gram = self.bus.grom, self.bus.gram
        hd, vd = r[HDR] & 7, r[VDR] & 7
        cs = 0                          # colour stack pointer, 0 every frame
        for row in range(CARD_ROWS):
            words = rows[row] if rows[row] is not None else [0] * CARD_COLS
            y0 = (OV_T + vd + row * 8) * 2
            for col in range(CARD_COLS):
                w = words[col] & 0x3FFF
                x0 = OV_L + hd + col * 8
                if self.csmode:
                    if w & 0x1800 == 0x1000:            # Colored Squares
                        q = (w & 7, (w >> 3) & 7, (w >> 6) & 7,
                             ((w >> 9) & 3) | ((w >> 11) & 4))
                        top = r[CSR + cs] & 0xF
                        for py in range(8):
                            for px in range(8):
                                c = q[(py >> 2) * 2 + (px >> 2)]
                                self._put(pic, fg, x0 + px, y0 + 2 * py,
                                          top if c == 7 else c, c != 7)
                        cards.append((row, col, "squares", None))
                        continue
                    if w & 0x2000:
                        cs = (cs + 1) & 3
                    fgc = (w & 7) | ((w >> 9) & 8)
                    bgc = r[CSR + cs] & 0xF
                    if w & 0x0800:
                        mem, base = gram, w & 0x01F8
                    else:
                        mem, base = grom, w & 0x07F8
                else:
                    fgc = w & 7
                    bgc = ((w >> 9) & 3) | ((w >> 11) & 4) | ((w >> 9) & 8)
                    mem, base = (gram if w & 0x0800 else grom), w & 0x01F8
                cards.append((row, col, "GRAM" if mem is gram else "GROM", base))
                for py in range(8):
                    bits = mem[base + py]
                    for px in range(8):
                        on = (bits >> (7 - px)) & 1
                        self._put(pic, fg, x0 + px, y0 + 2 * py, fgc if on else bgc, on)
        # borders (MAME stic.cpp:1102-1108): left, right, top, bottom
        lw = OV_L + (8 if r[CBR] & 1 else hd)
        th = (OV_T + (8 if r[CBR] & 2 else vd)) * 2
        for y in range(H):
            base = y * W
            if y < th or y >= (OV_T + CARD_ROWS * 8) * 2:
                pic[base:base + W] = bytes([border]) * W
                fg[base:base + W] = bytes(W)
                continue
            pic[base:base + lw] = bytes([border]) * lw
            fg[base:base + lw] = bytes(lw)
            x1 = OV_L + CARD_COLS * 8 - 1
            pic[base + x1:base + W] = bytes([border]) * (W - x1)
            fg[base + x1:base + W] = bytes(W - x1)
        return pic, fg, cards

    @staticmethod
    def _put(pic, fg, x, y, c, on):
        if 0 <= x < W and 0 <= y + 1 < H:
            i = y * W + x
            pic[i] = pic[i + W] = c
            fg[i] = fg[i + W] = on

    # -- helpers for the comparisons (step 5 draws MOBs) ---------------------
    def mob_boxes(self):
        """Rectangles (x0, y0, x1, y1) in picture coordinates that a MOB may
        cover, by MAME's rules (stic.cpp:777-851: X = 0 or neither VIS nor
        COL means no MOB). Used to mask MOBs out of a background compare."""
        r = self.regs
        out = []
        hd, vd = r[HDR] & 7, r[VDR] & 7
        for i in range(8):
            x, y = r[i], r[8 + i]
            if (x & 0xFF) == 0 or not (x & 0x300):
                continue
            # MYR: YSIZE $200 x4, YFULL $100 x2, YRES $80 two cards (lines)
            h = (4 if y & 0x200 else 1) * (2 if y & 0x100 else 1) * (2 if y & 0x80 else 1) * 8
            w = 16 if x & 0x400 else 8
            x0 = (x & 0xFF) - 8 + OV_L + hd
            y0 = ((y & 0x7F) - 8 + OV_T + vd) * 2
            out.append((max(x0, 0), max(y0, 0), min(x0 + w, W), min(y0 + h, H)))
        return out


# --------------------------------------------------------------- picture I/O
def write_pgm(path, pic):
    with open(path, "wb") as f:
        f.write(b"P5\n%d %d\n15\n" % (W, H))
        f.write(bytes(pic))


def read_pgm(path):
    """A binary PGM written by write_pgm (header "P5 W H MAX", one
    whitespace byte, then W x H bytes)."""
    data = open(path, "rb").read()
    toks, i = [], 0
    while len(toks) < 4:
        while data[i:i + 1].isspace():
            i += 1
        j = i
        while not data[j:j + 1].isspace():
            j += 1
        toks.append(data[i:j])
        i = j
    i += 1                              # the single whitespace byte
    if toks[0] != b"P5":
        raise ValueError("%s: not a binary PGM" % path)
    w, h, mx = int(toks[1]), int(toks[2]), int(toks[3])
    if (w, h) != (W, H) or mx > 255:
        raise ValueError("%s: %dx%d, want %dx%d" % (path, w, h, W, H))
    pix = data[i:]
    if len(pix) != W * H:
        raise ValueError("%s: %d pixel bytes, want %d" % (path, len(pix), W * H))
    return bytearray(pix)
