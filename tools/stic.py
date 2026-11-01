#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""stic: model of the STIC (AY-3-8900-1): backgrounds (build step 4), MOBs
and collisions (build step 5).

The golden model for the STIC RTL (DESIGN.md 2.4, 3 row 6, 9 steps 4-5).
It is driven by tools/intv_system.py (SystemBus owns the RAMs and the frame
timing; this module owns the STIC's registers and its view of the
graphics bus). docs/STIC_NOTES.md lists every fact, its source and every
place where the sources disagree.

MOBs (build step 5; STIC_NOTES 5)
  Eight MOBs from the X, Y and A registers ($00-$17; bits: S9 stic.txt:
  204-234, MAME stic.cpp:40-107): X coordinate 0-255 (0 = no MOB at all),
  INTR, VISB, XSIZE (16 pixels wide); Y coordinate 0-127 in card pixel
  rows (2 scanlines), YRES (two cards, 16 rows), YSIZ2 / YSIZ4 (each
  pattern row 2 / 4 / 8 scanlines; 1 when both clear), XFLIP, YFLIP; card
  bits 3-10 from GROM, 3-8 from GRAM (bit 11), colour bits 0-2 + 12, PRIO
  (behind the background's "on" pixels). The object field starts 8 pixels
  left of and 8 pixel rows above the card grid and moves with the delays
  (S9 stic.txt:86-194). Collision ("interaction") bits ($18-$1F): MOB n,
  bit 8 background (an "on" card pixel, squares colours 0-6), bit 9 border;
  both MOBs need INTR, a MOB never sets its own bit, the bits stay set
  until the CPU writes the register (S9 stic.txt:239-245, 311-329).
  The STIC computes them while it draws the frame; the CPU can only read
  them in the next VBlank (the registers are closed during the display when
  it is enabled), so the model ORs them in when it draws the frame (MAME
  stic.cpp:1111-1131 does the same at its vblank). MOB patterns come over
  the graphics bus during STIC time (GI80 p.5-10: "the fetch of
  'foreground' object patterns"): no BUSRQ, no CPU cycles.
  Two rule sets: mode "mame" follows MAME's stic.cpp exactly (MOBs drawn 7
  to 0, each over the last, a PRIO MOB skipped over an "on" pixel; YRES
  reads cards N and N + 1; GROM cards 0-255 in both modes; colour 7 of a
  Colored Squares card is "on" when bit 4 of the stored colour-stack word
  is set; the background under a delay strip is the last frame's), modes
  "stic" and "none" follow S9 where it says otherwise (STIC_NOTES 5, M1-M4):
  the lowest-numbered visible MOB pixel wins and only then its PRIO bit
  decides against the background, YRES ignores the card's bit 0, GROM
  cards 64-255 are not reachable in Foreground/Background mode, a delay
  strip has no "on" pixels.

Registers (CPU side, unchanged from the step-3 stub)
  Read masks per register class as MAME's stic_device::read returns them
  (MAME stic.cpp:1139-1201; DESIGN 13.7). A write to $20 (display enable)
  sets the handshake, the start of every frame clears it (MAME
  stic.cpp:1111-1116, 1270-1274). Reading $21 selects Color Stack mode,
  writing it Foreground/Background mode (wiki STIC "Display Background").
  Mode "mame": closed accesses read the address offset and drop writes
  (MAME intv_m.cpp:484-512); open = bus-copy window or handshake clear.
  Modes "stic" and "none" (the console, docs/TIMING_FIT.md): closed reads
  give $0000; open = the window (cycles 0-3,790) or the frame's display
  off (tools/intv_system.py SystemBus.stic_open).

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

Timing (cycles = CPU cycles from the frame start = SR1 / VBlank start = INTRM)
  mode "stic" (the hardware model: the console fit F of docs/TIMING_FIT.md,
  2026-11-01, on the hardware measurement cartridges of docs/HW_TESTS.md;
  STIC_NOTES T1-T6 has the documents' figures it replaced):
    - INTRM: cycles 0-3,789; the register window: cycles 0-3,790 (WINDOW),
      the display enable (the handshake) latched at its end.
    - frame BUSRQ 3,792-3,891 (100 cycles) if the display is enabled.
    - row fetch r (r = 0-11, any VDR; no 13th: TIMING_FIT F, against GI
      1980 p.5-10's "thirteen or fourteen times"): BUSRQ from R = 3,926 +
      114 x VDR + 912 x r for 107 cycles (released at R + 107; the CPU
      resumes 2 NACTs later). The row is copied at the fetch cycle R + 50
      (3,976 + 912 r: the CPU is stopped from its grant to the release, so
      only the deadline is seen): it loads only if the CPU acknowledged
      (BUSAK) by then; otherwise the FIFO keeps the previous row (wiki STIC
      Bus Request). The FIFO's address counter restarts at 0 on INTAK and
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
  - the display enable is taken at the end of the VBlank window (after
    the CPU's accesses in cycles 0-3,790), not at the frame's end: a $20
    write after cycle 3,790 leaves that frame blank (STIC_NOTES D8);
  - every border pixel shows register $2C as it is when the pixel is
    drawn (STIC_NOTES D17): a write in CPU cycle t (timing cycles) shows
    from pixel position 4 t + 5 on (pixel clocks from the frame start, 228
    a line; BCR_PIX), so a write in VBlank changes the border in the
    middle of a picture. A picture is therefore complete only at line 24
    of the next frame, when the model hands it out (pending);
  - the other registers, GRAM and the colour-stack mode are read during the
    display, where they are closed to the CPU when the display is enabled,
    so they equal the values at the frame's end that draw() uses.
Picture n of the RTL is raster lines 46-261 of frame n - 1 and lines 0-23 of
frame n, pixel clocks 24-212 (pocket_video PF_X0 = 37 is picture x = 13).
The FIFO's address counter stops once it reaches the end of System RAM
(352 words; the model and the RTL both stop it at 360) and restarts at
INTAK in modes "stic" and "none", at every vblank in mode "mame".
"""

import bisect

FRAME = 14934            # CPU cycles per frame (57 x 262; DESIGN 2.4)
VBLANK = 3790            # INTRM (all modes); mode "mame": the bus-copy window too (MAME stic.h:50)
WINDOW = 3791            # modes stic/none: the register window, cycles 0-3,790; the display
                         # enable is latched at its end (docs/TIMING_FIT.md, family F)
LINE = 57                # CPU cycles per scanline (MAME stic.h:47)
CARD_ROWS, CARD_COLS = 12, 20
FRAME_BUSRQ_AT = 3792    # mode stic: the request after VBlank, 3,792-3,891 (TIMING_FIT F)
FRAME_BUSRQ = 100
MAME_FRAME_BUSRQ = 42    # MAME stic.h:49 ("approximate")
SYSRAM_WORDS = 352
BCR_PIX = 5              # a $2C write in cycle t shows from pixel clock 4 t + 5 (see above)
HPIX = 4 * LINE          # 228 pixel clocks a line
PIC_LINE0, PIC_X0 = 46, 24   # picture (0, 0) = raster line 46, pixel clock 24
BORDER = 16              # draw(): marks a border pixel, filled in later
ROW0_REQ = 3926          # row 0 BUSRQ (VDR 0; TIMING_FIT F)
ROW_PERIOD = 16 * LINE   # 912: one card row = 16 scanlines
ROW_HOLD = 107           # held 107 cycles, released at 4,033 + 912 r (TIMING_FIT F)
FETCH_OFF = 50           # the row is copied at request + 50 (3,976 + 912 r), if granted by then
ROW_REQS = CARD_ROWS     # 12 row requests whatever the vertical delay (no 13th; TIMING_FIT F)
MAME_ROW_BUSRQ = 110     # MAME stic.h:48
MAME_FIRST = 3933 - MAME_FRAME_BUSRQ   # MAME intv_m.cpp:673

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

# MOB register bits (S9 stic.txt:204-234; MAME stic.cpp:40-107)
MXR, MYR, MAR, MCR = 0x00, 0x08, 0x10, 0x18
MX_X, MX_INTR, MX_VISB, MX_XSIZE = 0x00FF, 0x0100, 0x0200, 0x0400
MY_Y, MY_YRES, MY_YSIZ2, MY_YSIZ4, MY_XFLIP, MY_YFLIP = 0x007F, 0x0080, 0x0100, 0x0200, 0x0400, 0x0800
MA_FG20, MA_CARD, MA_GRAM, MA_FG3, MA_PRIO = 0x0007, 0x07F8, 0x0800, 0x1000, 0x2000
MC_BKGD, MC_BRDR = 0x0100, 0x0200
# collision area: pixels outside it touch the border (MAME stic.cpp:801-804;
# picture coordinates, inclusive; the left / top edge moves 8 pixels / 8 card
# rows in with a border extension bit)
COL_X1 = OV_L + CARD_COLS * 8 - 2                   # 171: the 159th playfield column
COL_Y1 = (OV_T + CARD_ROWS * 8) * 2 - 1             # 215


def _row_table(double, flip):
    """Pattern byte -> pixel mask of one MOB line (bit x = pixel x from the
    left), for XSIZE (double) and XFLIP (flip)."""
    w = 16 if double else 8
    out = []
    for b in range(256):
        m = 0
        for k in range(w):
            if (b >> (7 - k // (2 if double else 1))) & 1:
                m |= 1 << ((w - 1 - k) if flip else k)
        out.append(m)
    return out


ROWBITS = {(d, f): _row_table(d, f) for d in (0, 1) for f in (0, 1)}
# pattern byte -> 8 bytes of 0/1 (bit 7 first), for drawing cards
BYTEPIX = [bytes((b >> (7 - k)) & 1 for k in range(8)) for b in range(256)]
# A picture's last pixel (line 23 of the next frame, pixel clock 212) is
# position 4 x start + 285 x 228 + 212; writes from cycle start + PIC_DONE
# on show only after it.
PIC_DONE = -(-((PIC_LINE0 + H - 1) * HPIX + PIC_X0 + W - 1 - BCR_PIX + 1) // 4)


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
        self.bcr_log = [(-1, 0)]        # modes stic/none: ($2C pixel position, colour)
        self.pending = []               # pictures waiting for their last border line
        self.last_drawn = bus.timing.first   # the last picture handed out
        self.mobs = True                # False: backgrounds only (build step 4)
        self.mob_rules = None           # "mame" / "hw": MOB rules (default: by mode)
        self.raw = [0] * STIC_REGS      # mode "mame": the words as written (MAME keeps them)
        self.mame_fg = None             # mode "mame": "on" pixels left in MAME's bitmap
        self.reset()

    def reset(self):
        """Machine reset (MAME stic.cpp:448-498: registers, mode, handshake).
        The frame timing and the System RAM FIFO go on (and MAME's bitmap)."""
        self.regs[:] = [0] * STIC_REGS
        self.raw[:] = [0] * STIC_REGS
        self.hs_frame = None            # frame in which $20 was written
        self.csmode = 0

    # -- handshake and access window ----------------------------------------
    def handshake(self, frame):
        return self.hs_frame is not None and self.hs_frame == frame

    def read(self, a, frame, open_):
        """CPU read of $0000-$003F (a = offset)."""
        if not open_:
            # MAME intv_m.cpp:484-490: the offset; the console reads $0000 (hw_frame2,
            # docs/TIMING_FIT.md)
            return a if self.mode == "mame" else 0
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

    def write(self, n, value, frame, open_, t=None):
        """CPU write of register n in timing cycle t (t: modes stic/none)."""
        if not open_:
            return
        if n == BCR and self.mode != "mame":
            self.bcr_log.append((4 * t + BCR_PIX, value & 0xF))
        if n == STIC_DER:
            self.hs_frame = frame
        elif n == STIC_GMR:
            self.csmode = 0
        if n < STIC_REGS:
            if MCR <= n < MCR + 8:
                value &= ~(1 << (n & 7))   # MAME stic.cpp:1258-1266; S9 stic.txt:319-327
            self.raw[n] = value
            self.regs[n] = value & STIC_DEF[n][1]

    # -- BUSRQ (mode "stic") -------------------------------------------------
    def schedule(self, vdr):
        """[(kind, request cycle, release cycle, fetch cycle or None)] for a
        frame with the display enabled, relative to the frame start
        (docs/TIMING_FIT.md, family F)."""
        s = [("frame", FRAME_BUSRQ_AT, FRAME_BUSRQ_AT + FRAME_BUSRQ, None)]
        for r in range(ROW_REQS):
            req = ROW0_REQ + 2 * LINE * vdr + ROW_PERIOD * r
            s.append(("row%d" % r, req, req + ROW_HOLD, req + FETCH_OFF))
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
        while self.pending and self.pending[0][0] <= t:
            self._hand_out(*self.pending.pop(0)[1:])
        while True:
            cur = self.cur
            if cur is not None:
                if cur["defer"] and cur["start"] + WINDOW <= t:
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
            enabled, border = cur["en"], BORDER
        stolen = 0
        for i, (kind, req, end, fetch) in enumerate(cur["sched"]):
            a = cur["ack"].get(i)
            if a is not None:
                stolen += end - a
        self.stats.append({"n": n, "enabled": enabled, "vdr": cur["vdr"], "stolen": stolen,
                           "requests": len(cur["sched"]),
                           "loaded": sum(1 for f in cur["fetches"] if f[2])})
        want = self.keep_frames is None or n in self.keep_frames
        # MOB collisions need the frame drawn; MAME's bitmap carries "on"
        # pixels from frame to frame (under a delay strip), so mode mame
        # draws every enabled frame
        collide = self.mobs and enabled and (
            self.mame_rules() or any(self.regs[MXR + i] & MX_X and self.regs[MXR + i] & MX_INTR
                                       for i in range(8)))
        if not (want or self.on_frame is not None or collide):
            if self.mode == "mame":
                self.mame_fg = None
                self.last_drawn = n
            else:
                self.pending.append((cur["start"] + PIC_DONE, n, None, None, None))
            return
        rows = [r if r is not None else list(self.fifo) for r in self.rows]
        pic, fg, cards, mobs = self.draw(enabled, rows, border)
        if mobs is not None:
            for i, bits in enumerate(mobs["coll"]):
                if bits:                # sticky until the CPU writes (S9 stic.txt:322-327)
                    self.regs[MCR + i] = (self.regs[MCR + i] | bits) & STIC_DEF[MCR + i][1]
                    self.raw[MCR + i] |= bits
        if not (want or self.on_frame is not None):
            if self.mode == "mame":
                self.last_drawn = n
            else:
                self.pending.append((cur["start"] + PIC_DONE, n, None, None, None))
            return
        info = {"n": n, "start": cur["start"], "enabled": enabled, "vdr": cur["vdr"],
                "csmode": self.csmode, "fetches": cur["fetches"], "stolen": stolen,
                "cards": cards, "fg": fg, "rows": rows,
                "stats": dict(self.stats[-1]),
                "mobs": mobs["log"] if mobs is not None else [],
                "coll": mobs["coll"] if mobs is not None else [0] * 8}
        if self.mode == "mame":
            self._hand_out(n, pic, info, want)
        else:
            # border pixels wait for $2C up to the picture's last line
            self.pending.append((cur["start"] + PIC_DONE, n, pic, info, want))

    def _hand_out(self, n, pic, info, want):
        """Picture n is complete: fill its border pixels (modes stic/none)
        and hand it out."""
        self.last_drawn = n
        if pic is None:
            return
        if self.mode != "mame":
            self._fill_border(pic, info["start"])
        if want:
            self.frames.append((n, pic))
        if self.on_frame is not None:
            self.on_frame(n, pic, info)

    def _fill_border(self, pic, start):
        """Replace the BORDER marks of a picture whose frame started at
        timing cycle `start` with $2C as it was at each pixel."""
        log = self.bcr_log
        base = 4 * start + PIC_LINE0 * HPIX + PIC_X0
        # drop changes no picture still needs (keep the one in force)
        i = bisect.bisect_right(log, (base, 99)) - 1
        if i > 0:
            del log[:i]
        mark = bytes([BORDER])
        j = 0
        for y in range(H):
            p0 = base + y * HPIX
            while j + 1 < len(log) and log[j + 1][0] <= p0:
                j += 1
            row = pic[y * W:(y + 1) * W]
            if mark not in row:
                continue
            if j + 1 >= len(log) or log[j + 1][0] > p0 + W - 1:
                pic[y * W:(y + 1) * W] = row.replace(mark, bytes([log[j][1]]))
                continue
            jj = j
            for x in range(W):
                while jj + 1 < len(log) and log[jj + 1][0] <= p0 + x:
                    jj += 1
                if row[x] == BORDER:
                    pic[y * W + x] = log[jj][1]

    def draw(self, enabled, rows, border=None):
        """(picture, foreground mask, card fetch log, MOB result) from the
        registers, GRAM/GROM now and the given 12 rows of BACKTAB words.
        border: the border colour (default: register $2C now). The MOB
        result (None without MOBs) is {"coll": 8 collision words to OR into
        $18-$1F, "log": [(MOB, memory, first address, last address, x, y)]}."""
        r = self.regs
        mame = self.mame_rules()
        if border is None:
            border = r[BCR] & 0xF
        pic = bytearray([border]) * (W * H)
        cards = []
        if not enabled:
            if mame:
                self.mame_fg = None     # MAME fills the bitmap (stic.cpp:1132-1135)
            return pic, bytearray(W * H), cards, None
        # mode mame: what MAME's bitmap holds where this frame draws no card
        fg = bytearray(self.mame_fg) if (mame and self.mame_fg is not None) else bytearray(W * H)
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
                        # colour 7 is "off"; MAME: "on" if bit 4 of the stored word is (D12)
                        top_on = (self.raw[CSR + cs] >> 4) & 1 if mame else 0
                        for half in (0, 1):
                            a, b = q[2 * half], q[2 * half + 1]
                            line = bytes([top if a == 7 else a] * 4 + [top if b == 7 else b] * 4)
                            on = bytes([top_on if a == 7 else 1] * 4 + [top_on if b == 7 else 1] * 4)
                            for py in range(8 * half, 8 * half + 8):
                                i = (y0 + py) * W + x0
                                pic[i:i + 8] = line
                                fg[i:i + 8] = on
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
                tr = bytes([bgc, fgc]) + bytes(254)
                for py in range(8):
                    bits = BYTEPIX[mem[base + py] & 0xFF]
                    line = bits.translate(tr)
                    i = (y0 + 2 * py) * W + x0
                    pic[i:i + 8] = line
                    pic[i + W:i + W + 8] = line
                    fg[i:i + 8] = bits
                    fg[i + W:i + W + 8] = bits
        mobs = self._draw_mobs(pic, fg) if self.mobs else None
        # borders (MAME stic.cpp:1102-1108): left, right, top, bottom
        lw = OV_L + (8 if r[CBR] & 1 else hd)
        th = (OV_T + (8 if r[CBR] & 2 else vd)) * 2
        x1 = OV_L + CARD_COLS * 8 - 1
        full, zero = bytes([border]) * W, bytes(W)
        for y in range(H):
            base = y * W
            if y < th or y >= (OV_T + CARD_ROWS * 8) * 2:
                pic[base:base + W] = full
                fg[base:base + W] = zero
                continue
            pic[base:base + lw] = full[:lw]
            fg[base:base + lw] = zero[:lw]
            pic[base + x1:base + W] = full[:W - x1]
            fg[base + x1:base + W] = zero[:W - x1]
        if mame:
            self.mame_fg = bytes(fg)
        return pic, fg, cards, mobs

    # -- MOBs (build step 5) -------------------------------------------------
    def mame_rules(self):
        """True: MOBs and collisions by MAME's rules (mode mame), else by
        the hardware's (modes stic and none; STIC_NOTES 5.2). mob_rules
        overrides it for diagnostics."""
        if self.mob_rules is not None:
            return self.mob_rules == "mame"
        return self.mode == "mame"

    def mob_shape(self, i):
        """MOB i as (x, y, lines, log entry) in picture coordinates: x, y of
        its top left pixel (picture line), lines = one pixel mask per
        scanline (bit k = pixel x + k). None: X coordinate 0 (S9
        stic.txt:187-189; MAME stic.cpp:789)."""
        r = self.regs
        xr, yr, ar = r[MXR + i], r[MYR + i], r[MAR + i]
        if not xr & MX_X:
            return None
        hd, vd = r[HDR] & 7, r[VDR] & 7
        x = (xr & MX_X) - 8 + OV_L + hd
        y = ((yr & MY_Y) - 8 + OV_T + vd) * 2
        size = (4 if yr & MY_YSIZ4 else 1) * (2 if yr & MY_YSIZ2 else 1)  # scanlines a pattern row
        nrows = 16 if yr & MY_YRES else 8
        card = (ar & MA_CARD) >> 3
        gram_ = ar & MA_GRAM
        if self.mame_rules():
            if gram_:
                card &= 0x3F            # MAME stic.cpp:622
        else:
            if gram_ or not self.csmode:
                card &= 0x3F            # S9 stic.txt:298-303; WIKI STIC (M2)
            if yr & MY_YRES:
                card &= ~1              # S9 stic.txt:274-279, 305-306 (M1)
        base = card * 8
        mem = self.bus.gram if gram_ else self.bus.grom
        pats = []
        for k in range(nrows):
            a = base + k
            if gram_:
                pats.append(mem[a] & 0xFF if a < 0x200 else 0xFF)   # MAME stic.cpp:629-635
            else:
                pats.append(mem[a] & 0xFF if a < len(mem) else 0xFF)
        tab = ROWBITS[(1 if xr & MX_XSIZE else 0, 1 if yr & MY_XFLIP else 0)]
        lines = []
        for p in pats:
            lines.extend([tab[p]] * size)
        if yr & MY_YFLIP:
            lines.reverse()
        off = 0x3800 if gram_ else 0x3000
        log = (i, "GRAM" if gram_ else "GROM", off + base, off + base + nrows - 1, x, y)
        return x, y, lines, log

    def _draw_mobs(self, pic, fg):
        """Draw the MOBs into a picture whose cards are drawn (fg: their "on"
        pixels) and return their collision bits (see draw())."""
        r = self.regs
        mame = self.mame_rules()
        x0 = OV_L + (8 if r[CBR] & 1 else 0)
        y0 = (OV_T + (8 if r[CBR] & 2 else 0)) * 2
        shapes = [self.mob_shape(i) for i in range(8)]
        coll = [0] * 8
        log = []
        claimed = None if mame else bytearray(W * H)
        # MAME draws 7 to 0, each MOB over the last (stic.cpp:786-851); the
        # hardware rules take the lowest-numbered visible pixel (M3)
        order = range(7, -1, -1) if mame else range(8)
        for i in order:
            s = shapes[i]
            xr = r[MXR + i]
            vis, intr = xr & MX_VISB, xr & MX_INTR
            if s is None or not (vis or intr):
                continue
            x, y, lines, ent = s
            log.append(ent)
            prio = r[MAR + i] & MA_PRIO
            colour = (r[MAR + i] & MA_FG20) | ((r[MAR + i] & MA_FG3) >> 9)
            bord = back = False
            for dy, m in enumerate(lines):
                if not m:
                    continue
                py = y + dy
                k = 0
                while m:
                    if m & 1:
                        px = x + k
                        if px < x0 or px > COL_X1 or py < y0 or py > COL_Y1:
                            bord = True
                        else:
                            idx = py * W + px
                            on = fg[idx]
                            if on:
                                back = True
                            if vis:
                                if mame:
                                    if not (on and prio):
                                        pic[idx] = colour
                                elif not claimed[idx]:
                                    claimed[idx] = 1
                                    if not (on and prio):
                                        pic[idx] = colour
                    m >>= 1
                    k += 1
            if intr:
                coll[i] |= (MC_BKGD if back else 0) | (MC_BRDR if bord else 0)
        log.sort()
        # MOB to MOB: both need INTR, anywhere in the object field (MAME
        # stic.cpp:539-603; S9 stic.txt:239-241)
        act = [i for i in range(8) if shapes[i] is not None and r[MXR + i] & MX_INTR]
        for a in range(len(act)):
            i = act[a]
            xi, yi, li, _ = shapes[i]
            for b in range(a + 1, len(act)):
                j = act[b]
                xj, yj, lj, _ = shapes[j]
                lo, hi = max(yi, yj), min(yi + len(li), yj + len(lj))
                xm = min(xi, xj)
                for py in range(lo, hi):
                    if (li[py - yi] << (xi - xm)) & (lj[py - yj] << (xj - xm)):
                        coll[i] |= 1 << j
                        coll[j] |= 1 << i
                        break
        return {"coll": coll, "log": log}


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
