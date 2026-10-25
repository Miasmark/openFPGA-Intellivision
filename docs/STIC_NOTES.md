# STIC notes (build steps 4 and 5: backgrounds, MOBs and collisions)

What the STIC model (`tools/stic.py`, driven by `tools/intv_system.py`) does,
where each fact comes from, and every place where the sources disagree.
Sections 1-4 are the backgrounds (build step 4); section 5 is the MOBs and
their collisions (build step 5, model), section 6 their RTL.

Sources (DESIGN.md section 12 for the full list):

| Tag | Source |
|---|---|
| GI80 | GI Microelectronics Data Catalog 1980: AY-3-8900/8900-1 (p.5-10 to 5-12), RA-3-9600 (p.5-18), CP1600 (BUSRQ/BUSAK) |
| SM | Intellivision Service Manual, Model 2609 (via DESIGN.md) |
| WIKI | wiki.intellivision.us archive: STIC, STIC_Bus_Request, Bus_Copy, VBlank_Interval, VBlank_Period_1/2, VBlank_Interrupt |
| S9 | jzIntv documentation (doc/programming/stic.txt, interrupts.txt; documentation only, no code) |
| MAME | MAME (BSD-3) `src/mame/mattel/stic.cpp`, `stic.h`, `intv_m.cpp`, `intv.cpp`, `src/emu/screen.cpp`, `src/emu/diexec.h`, read for facts only |

MAME's STIC timing constants are "based on Joe Zbiciak's documentation"
(MAME stic.h:46), so MAME and S9 agreeing is one source, not two (DESIGN 2.4).

## 1 What the model does

**Registers.** Unchanged from the step-3 stub: MAME's read masks per register
class (MAME stic.cpp:1139-1201), a write to $20 sets the handshake for the
current frame, frame start clears it (MAME stic.cpp:1111-1116, 1270-1274),
reading $21 selects Color Stack mode and writing it Foreground/Background
(WIKI STIC; S9 stic.txt:339, 447), closed accesses read the offset and drop
writes (MAME intv_m.cpp:484-512), open = bus-copy window or handshake clear.
A MOB's own collision bit always reads 0 (MAME stic.cpp:1258-1266).

**Background.** BACKTAB words reach the STIC through System RAM's 20-word row
FIFO (GI80 p.5-18; WIKI STIC_Bus_Request). Bits 14-15 are not on the 14-bit
graphics bus (WIKI Bus_Copy; S9 stic.txt).

- Color Stack mode: foreground = bits 0-2 and bit 12 (as bit 3); card =
  bits 3-10 from GROM (bit 11 = 0) or bits 3-8 from GRAM (bit 11 = 1; bits
  9-10 ignored); bit 13 advances the stack *before* the card is drawn;
  background = the current stack entry ($28-$2B), stack back to entry 0
  every frame (S9 stic.txt:334-394; WIKI STIC; MAME stic.cpp:668-734).
- Colored Squares: a Color Stack card with bit 12 = 1 and bit 11 = 0;
  quadrants 0 (top left) bits 0-2, 1 (top right) bits 3-5, 2 (bottom left)
  bits 6-8, 3 (bottom right) bits 9-10 + bit 13 as bit 2; colours 0-6 are
  drawn as they are and count as foreground ("on") pixels; 7 shows the
  current stack entry and is "off"; the stack never advances on such a card
  (S9 stic.txt:396-436; WIKI STIC; MAME stic.cpp:660-698).
- Foreground/Background mode: foreground bits 0-2; card bits 3-8 (GROM
  0-63 or GRAM 0-63, bit 11); background bits 9-10 (0-1), 13 (2), 12 (3)
  (S9 stic.txt:441-471; WIKI STIC; MAME stic.cpp:736-775).
- Card pixels: GROM/GRAM byte per pixel row, bit 7 leftmost; each card
  pixel row is two scanlines (MAME stic.cpp:648-658, stic.h:37).
- Playfield 20 x 12 cards, 159 x 96 visible: the 20th column shows 7
  pixels (GI80 p.5-10; WIKI STIC; MAME stic.h:31-32).
- Border colour $2C around the playfield; horizontal/vertical delay $30/$31
  (0-7) move the card grid right/down and the uncovered strip shows the
  border colour; border extension $32 bit 0 (left) / bit 1 (top) covers an
  8-pixel strip with the border colour (S9 stic.txt:110-189; MAME
  stic.cpp:1102-1108). See D6.
- A frame whose display was not enabled shows only the border colour (MAME
  stic.cpp:1132-1135). See D7.

**Picture.** 189 x 240 palette indices in MAME's layout (13 border pixels
left, 159 playfield, 17 right; 24 lines top, 192 playfield, 24 bottom: MAME
stic.h:39-61, all "approximate" there), so model pictures and MAME snapshots
compare pixel for pixel. The RTL's raster placement is decided in the RTL
work, against GI80's 167 x 105 object grid (see D14).

**Timing**, in CPU cycles from the frame start (SR1 / VBlank start, cycle 0),
mode `stic` (the hardware model):

| Event | Cycles | Source |
|---|---|---|
| INTRM held, bus-copy window | 0-3,789 | MAME stic.h:50; step 3 (DESIGN 2.4) |
| frame BUSRQ (ends bus copy on hardware) | request 3,790-3,831 if the display is enabled at 3,790 | MAME stic.h:49 ("approximate"); GI80 p.5-10 (13 or 14 SR2 per frame) |
| row fetch r BUSRQ | request from R = 3,876 + 114 x VDR + 912 x r for 114 cycles, while R + 114 <= 14,934 (12 rows; 13 when VDR = 0) | WIKI STIC_Bus_Request (one scanline of warning, then the fetch line); MAME stic.h:51 (first fetch 3,933 = R + 57); GI80 p.5-10 |
| row r copied | at the CPU's BUSAK if that comes by R + 57 (the fetch line); else the FIFO keeps the previous row | WIKI STIC_Bus_Request; GI80 p.5-18 |
| FIFO address counter | 0 at INTAK, +20 per loaded row | GI80 p.5-18 |
| frame drawn | at the next frame start, with the registers, GRAM and colour-stack mode of that moment and the rows loaded during the frame; border pixels from $2C as it was at each pixel (D17), so the picture is complete at line 24 of the next frame | registers and GRAM are closed during the display when it is enabled, so this equals drawing line by line |

The CPU sees BUSRQ through `SystemBus.busrq`: it stops at its next
interruptible boundary and is held until the request ends (cp1610.py, S1
p.24). Stolen cycles per frame in mode `stic`, measured: see section 3.

In modes `stic` and `none` the FIFO counter restarts at INTAK (in mode
`none` it was never restarted before the RTL step) and stops once it has
passed System RAM (both the model and the RTL leave it at 360).

Mode `mame` is MAME as it runs (T2): no stolen cycles; row r copied at the
first instruction boundary at or after vblank + 3,891 + 114 x VDR + 802 x r
(MAME intv_m.cpp:670-676; VDR as it is at the vblank); the row counter back
to 0 at every vblank (intv_m.cpp:666); the frame drawn at the vblank
boundary (intv_m.cpp:683); MAME's 59.92 Hz frame and 894,886 Hz clock
(`MameTiming`, T11). Mode `none` (the default) is the step-3 system: no
BUSRQ, rows copied at the `stic` fetch cycles. `tb_system` uses `none`.

**Bus accesses per frame** (`tools/stic_frames.py run`, file `m<N>.bus.txt`):
one ROW line per row fetch (when, loaded or missed, the System RAM words) and
one CARD line per card (GROM or GRAM address range, or squares). How often
the STIC reads a card's pattern byte (per scanline or per pixel row) is not
documented; the log lists each card's 8 bytes once (D15).

## 2 Where the sources disagree

### Timing

| # | Topic | Sources | Model |
|---|---|---|---|
| T1 | BUSRQ cycles per card row | MAME 110 (stic.h:48); WIKI 114 (DESIGN 2.4, L-WIKI); WIKI STIC_Bus_Request: requested one scanline ahead, released when the row is loaded (= 2 x 57) | request held 114 cycles; the CPU loses 114 minus its latency to the next interruptible boundary (MAME's 110 looks like 114 minus an average latency of 4) |
| T2 | Does the CPU lose the BUSRQ cycles at all in MAME? | MAME subtracts 12 x 110 + 42 (+ 110 when VDR = 0) with `adjust_icount` in the vblank interrupt (intv_m.cpp:668, 680), but `adjust_icount` acts only while the CPU is executing (diexec.h:159) and the vblank callback runs from a timer between time slices; MAME's traces show every instruction at its own cycle count and about 14,934.7 CPU cycles between vblanks (docs/CPU_NOTES.md "MAME lockstep"; step-4 traces: Beamrider 200 frames, no gap anywhere) | mode `mame` steals nothing (to follow MAME's traces); mode `stic` steals as the hardware should |
| T3 | Extra row fetch with VDR = 0 | MAME +110 cycles (intv_m.cpp:678-681); S9 14,934 - 13,518 = 1,416, i.e. +54 over VDR > 0 (interrupts.txt:126-128); GI80 p.5-10: SR2 "thirteen or fourteen times per picture frame depending on picture offset" | a 13th request when it fits before the frame end (VDR = 0 only): about +110, as MAME |
| T4 | Frame BUSRQ | MAME 42 cycles "just after end of vblank and before first row fetch (approximate)" (stic.h:49); no other source gives a figure; GI80's 13/14 SR2 per frame fits 12/13 row fetches plus one | 42-cycle request at 3,790 when the display is enabled |
| T5 | When rows are copied | MAME's row timers fire at vblank + 3,891 + 114 x VDR + 802 x r *real* time (intv_m.cpp:672-675): the stolen cycles are taken off a real-time delay, so row 11 lands at 12,713 instead of 3,933 + 11 x 912 = 13,965 | `stic`: 3,933 + 114 x VDR + 912 x r (the BUSAK cycle); `mame`: MAME's times. Visible only when a program writes BACKTAB during the display |
| T6 | VBlank windows | STIC registers ~2,000 (S9 interrupts.txt:64) or ~2,900 (WIKI VBlank_Period_1); GRAM/GROM 3,780-3,790 (S9 interrupts.txt:63, 130), ~3,796 (WIKI VBlank_Period_2), 3,790 (MAME stic.h:50); both open the whole frame while the display is not enabled (WIKI) | 3,790 for both, as step 3 (DESIGN 13.4 stays open: own test ROM) |
| T7 | INTRM length | 3,790 (MAME stic.h:50); "exactly 3,791" (WIKI VBlank_Interrupt) | 3,790 (step 3) |
| T8 | Bus copy start and end | System RAM enters bus copy on INTAK and leaves it at the first BUSAK (GI80 p.5-18; WIKI Bus_Copy); MAME: from the vblank for 3,790 cycles, whether or not the CPU takes the interrupt (intv_m.cpp:643-647, 665, 669) | the first 3,790 cycles of the frame (step 3's decision, kept; DESIGN 13.4) |
| T9 | FIFO address counter reset | at the decoded interrupt (INTAK) (GI80 p.5-18); MAME: at every vblank (intv_m.cpp:666) | `stic`: INTAK; `mame`: vblank. With interrupts off for a frame the hardware counter is not reset; past System RAM the model reads $3FFF (the real counter's width is unknown) |
| T10 | Rows when the CPU does not acknowledge | the FIFO replays the previous row, pushing the picture down (WIKI STIC_Bus_Request); a late BUSAK during the fetch line would load part of a row (GI80: SR3 copies a card only while BUSAK is low) | all or nothing at the fetch cycle (R + 57); a partial row is not modelled |
| T11 | Frame length | 14,934 = 57 x 262 cycles (S9; DESIGN 2.4); MAME: 59.92 Hz at 894,886 Hz = 14,934.68 cycles (intv.cpp:445, 456), so MAME's frames drift 0.68 cycles a frame against the hardware's | `stic`/`none`: 14,934 (RTL timing); `mame`: MAME's, frame k at the first boundary at or after floor(k x 14,934.68) |
| T12 | CPU clock | 3,579,545 / 4 = 894,886.25 Hz; MAME's device clock is the integer 894,886 Hz | MAME's figure inside `MameTiming` only |

### Display

| # | Topic | Sources | Model |
|---|---|---|---|
| D6 | Colour of the strip uncovered by a horizontal/vertical delay | S9: the object field outside the 20 x 12 cards "is filled in with the background color, as defined by the given display mode" (stic.txt:121-125, 150-154); MAME draws the border colour over it (stic.cpp:1104, 1106: the left/top border boxes are 13 + HDR / 12 + VDR wide) | border colour (MAME). Not covered by a MAME match that can tell them apart; settle with our own STIC test ROM on hardware |
| D7 | Picture when the display is not enabled | S9: "the display will blank" (interrupts.txt:74-76); MAME fills the frame with the border colour (stic.cpp:1132-1135) | border colour (MAME); hardware colour unknown (black is as likely) |
| D8 | When a write to $20 enables the display | S9 and WIKI: during VBlank period 1; MAME: any write while the STIC is open, including during the display of a frame that is not enabled (the handshake is clear, so the registers are open) | MAME (step 3). In mode `stic` the BUSRQ schedule is fixed at cycle 3,790, so a frame enabled later fetches no rows and shows the FIFO's last row |
| D9 | Mode select through $4021/$8021/$C021 | an access to any alias reaches the STIC (WIKI Bus_Copy; DESIGN 2.6); MAME maps the STIC at $0000-$003F only | aliases switch the mode (step 3); the EXEC with no cartridge writes them (D18) |
| D10 | GRAM at reset | MAME clears the first 64 bytes of GRAM on every reset (stic.cpp:487-491); RAM keeps its contents through a reset on hardware (no source says otherwise) | GRAM kept (power-on: zero) |
| D11 | 13th row fetch (VDR = 0) | GI80/S9 imply it; MAME fetches 12 rows | `stic`: loads System RAM $02F0-$0303 into the FIFO (counter at 240), never shown |
| D12 | Unmasked colour-stack value in Colored Squares | MAME uses the whole stored register value for colour 7 (stic.cpp:684: `m_stic_registers[]` holds the unmasked write); its palette maps it back to colour & 15 (intv.cpp:92-119) | 4-bit register value; same pixels |
| D13 | 160th pixel column | not displayed (GI80 p.5-10; WIKI STIC); MAME covers it with the right border | right border from x = 13 + 159 |
| D14 | Picture framing | GI80: object grid 167 x 105 (NTSC) of which 159 x 96 visible; MAME overscan 13/17/12/12 "approximate" (stic.h:39-44) | MAME's framing for the comparison; RTL to decide |
| D15 | Pattern reads | GI80 p.5-11: BAR/DTB on the graphics bus per card; how often per card row is not given; MAME reads all 8 bytes when it draws | bus log lists 8 bytes per card per frame |
| D16 | STIC state decay without interrupts | S9 interrupts.txt:181-183 (registers "lose their state after a few frames"); no mechanism given | not modelled (DESIGN 13.6) |
| D17 | When a border colour write shows | The STIC raises the VBlank interrupt "just as it begins to draw the solid border at the bottom of the screen" (WIKI VBlank_Interrupt), so the lower border and the top border lines are drawn inside the VBlank window, while $2C is open to the CPU; no source says the STIC latches the border colour once a frame. MAME draws the whole frame at its vblank with one value (stic.cpp:1102-1108; intv_m.cpp:683) | modes `stic`/`none` and the RTL: every border pixel shows $2C as it is when the pixel is drawn; a write in CPU cycle t shows from pixel clock 4 t + 5 of the frame (the register is written at the ce that ends the cycle, the pixel is registered one pixel clock ahead). So a change the interrupt routine makes early in VBlank already shows in the lower border of the picture before (Tower of Doom picture 10, Sewer Sam picture 11), where MAME shows it from the next picture. Until the step-4 review the RTL latched the colour at the window end and showed picture rows 0-20 (lines 46-66) in the frame before's colour; no source supported that band. Hardware test: our STIC test ROM writing $2C at known VBlank cycles (needs a flash cartridge); watching only, partly: a 240 fps video of the TV in the first second after RESET with Tower of Doom (border brown from picture 7, black from picture 10): with the live register the last brown picture's lowest border lines are already black, with MAME's rule the whole picture is brown (overscan may hide those lines) |
| D18 | The EXEC with no cartridge writes the STIC's write aliases | Model run, hardware map (EXEC read with `tools/cp1610.py`'s disassembler; the owner's file, not in the repository): at frame 2 the EXEC unpacks a GRAM-picture routine into System RAM $0210-$02E7 and from then on calls it every frame or two. Its list of cards comes from where the missing cartridge's header leads: it reads the list from $0000 on (the STIC's own registers, then the empty $0040-$00FF range), never meets an end mark, and stores 8 words a card upward from $3800: GRAM, GRAM's aliases $3A00-$3FFF, then $4000-$403F from frame 133, $8000-$803F from frame 347 and $C000-$C03F from frame 535. With the write aliases of DESIGN 2.6 (D9) these reach the STIC registers, $4020 / $8020 / $C020 (display enable) and $402C / $802C / $C02C (border) among them. MAME's map has no aliases and reads unmapped addresses as 0, so MAME stays black | modes `stic`/`none` and the RTL (hardware map), pictures predicted to 1,300: black; picture 137 (2.3 s) one frame of coloured cards; 349 (5.8 s) one such frame, then the whole screen colour 15 (MAME's palette: purple; a display-off frame shows the border colour, D7) until picture 724 (12.1 s), one more frame of cards, then black again. Hardware test: the owner's console with no cartridge and no ECS, watched for 25 s: a steady black screen means no aliases at $4000 / $8000 / $C000 (or that the EXEC reads differently there); single flashes mean the display-enable alias works; the screen turning a colour at about 6 s also answers D7 (a display-off frame shows the border colour). On the Pocket the cartridge is required, so 0.0.2 meets this only with a cartridge image that maps nothing at $5000 |

### Method notes (not source conflicts)

- MAME takes a snapshot in its frame notifier, which runs in `vblank_begin`
  *before* the vblank callbacks (MAME screen.cpp:1680-1686), and the STIC
  draws in the vblank interrupt (intv_m.cpp:683). So MAME's snapshot N shows
  the picture drawn at vblank N - 1: `stic_frames.py compare --snaps N`
  compares it with model picture N - 1 (checked: Beamrider snapshot 180
  equals picture 179 and no neighbour).
- A MAME timer at time T fires at the first CPU instruction boundary at or
  after floor(T) in CPU cycles (the scheduler gives the CPU whole cycles; the
  CPU runs until its count is used up). MAME executes SDBD and the next
  instruction as one step, so no timer fires between them. `MameTiming`
  follows both; checked against every frame number of the traces in
  section 3.
- MAME never sets C on NEGR (docs/CPU_NOTES.md row 5). In MAME-compatible
  runs (`mame` mode, `mame_compare`) the model follows MAME's flag after a
  NEGR, as it follows MAME's SETC and SARC ,2 cycle counts.
- MAME's memory map differs from the hardware's in ways a long trace
  meets: unmapped ranges ($0040-$00FF, $0360-$03FF, $0500-$0FFF,
  $3C00-$3FFF) read 0 instead of $FFFF, GRAM is mapped at $3800-$3BFF only,
  and there are no write aliases (MAME intv.cpp:278-303). The EXEC with no
  cartridge reads $0040 at frame 87; Diner reads $3C00 at frame 10. The
  system model keeps the hardware map (DESIGN 2.5, 2.6) and applies MAME's
  in MAME-compatible runs (`SystemBus.mame_map`).
- MAME draws MOBs and reports their collisions; games that read collision
  registers then run differently from a model without MOBs (Atlantis reads
  $001B = $3E00 at frame 8 of its trace). Such games waited for step 5;
  they match now (section 5).

## 3 Done-test (build step 4, model)

DESIGN 9 step 4: "EXEC title screen and 5 games' frame CRCs match MAME
(palette aside)". Pictures are compared pixel for pixel as palette indices
(`stic_frames.py compare`, mode `mame`), not as CRCs. Snapshots, frames
and traces come from the owner's BIOS and games and stay outside the
repository (`~/daria_work/intv/stic/{snaps,frames,traces}`), never
committed. Result 2026-10-25 (mode `mame`; re-run after D17, unchanged): **pass**.

| Screen | What it exercises | MAME snapshots compared (all match) | MAME trace compared (`mame --timing computed`) |
|---|---|---|---|
| EXEC, no cartridge | display never enabled: border colour only | 7 (60-600) | 301 frames, 579,141 steps, 1 interrupt |
| EXEC title screen (Astrosmash cartridge) | Color Stack, GROM text, border | 8 (60-700) | 301 frames, 573,939 steps, 298 interrupts |
| Tower of Doom | Foreground/Background, GRAM, stack advance and pastel foreground (picture 10) | 13 (9-13, 60-700) | 301 frames, 580,987 steps |
| Diner | vertical delay 0-7 with top border extension, Foreground/Background | 33 (20-50, 120, 300) | 301 frames, 619,299 steps (1 MAME NEGR carry) |
| Dig Dug | Color Stack with advance, top border extension, pastel GRAM foreground | 8 (4-700) | 301 frames, 516,642 steps |
| Sewer Sam | Colored Squares (colour 7 = stack); BACKTAB rewritten during the display (MAME's row timers decide the picture) | 13 (9-300) | 301 frames, 548,438 steps |
| TRON Solar Sailer | horizontal delay 0-7 with both border extensions | 13 (19-700, 648-651 without MOBs) | 652 frames, 1,299,869 steps |

Also matching (mode `mame`): Safecracker (FGBG, 8 snapshots, trace 301
frames), Beamrider (GRAM animation, 8, trace 301 frames), Blockade Runner
(Colored Squares, 11), Body Slam (vertical delay without extension, MOBs
masked, 18), Zzzz Spina the Bee (horizontal delay with left extension, MOBs
masked, 25); and at snapshots 60-700 B-17 Bomber, Backgammon, BurgerTime
(MOBs masked), Checkers, Crosswords, Dreadnaught Factor, Pitfall!, Reversi,
River Raid, Royal Dealer, Shark! Shark!, Space Armada, Thunder Castle
(MOBs masked), Utopia, Vectron. In all, 165 snapshots of the 12 listed in
the lane's done-test script, 53 of them with MOB boxes masked.

Not matching, as expected before step 5: Atlantis and Demon Attack (MOB
collisions read back: MAME sets collision bits the model does not have, and
the games then run differently; Atlantis reads $001B = $3E00 at frame 8),
and the MTE201 test cartridge (it tests MOBs and collisions).
**(build step 5)** With the MOBs in the model all of these match, every
snapshot above is compared without masks, and the masks are gone from
`stic_frames.py` (section 5.4).

**What this done-test proves for the RTL.** The pixel-exact match above
is the model's mode `mame`, which the RTL does not run. The RTL equals
the model's mode `stic` (the hardware model: BUSRQ on, 14,934-cycle
frames, the hardware memory map, the RTL's picture semantics of section
4): the frame gate (`tb_system.py --screens`, section 4) compares every
picture, row fetch, card row and bus cycle of the RTL with mode `stic`
on the same 7 screens, 600-700 pictures each. So the RTL meets "frames
match MAME" through the model: RTL = mode `stic`, and mode `mame` = MAME;
the two modes differ only where the hardware and MAME differ, and every
such difference on the required screens is listed and explained below.
There is no direct RTL-against-MAME gate; the owner accepts this reading
of DESIGN 9's done-test or asks for one.

**Hardware mode against MAME.** Mode `stic` against the same MAME
snapshots (2026-10-25, after D17; lane scripts outside the repository):

| Screen | Snapshots matching | The others, and why |
|---|---|---|
| EXEC, no cartridge | 5 of 7 (60-300) | 400 and 600: the whole picture is colour 15, MAME's 0. From frame 133 the EXEC's writes reach $4000-$403F, the STIC's write alias in the hardware map (D18, D9); MAME has no aliases there |
| EXEC title screen (Astrosmash) | 8 of 8 | |
| Tower of Doom | 11 of 13 | 9 (picture 8): its first $20 write comes after cycle 3,789, so the frame stays blank (D8; MAME draws it): 2,352 playfield pixels. 11 (picture 10): the next frame's interrupt routine changes the border colour at line 4, so the bottom 20 lines of the picture's lower border already show the new colour (D17; MAME draws the whole frame at its vblank): 3,655 pixels |
| Diner | 33 of 33 | |
| Dig Dug | 8 of 8 | |
| Sewer Sam | 2 of 13 (9, 10) | 12: the lower border band, as Tower of Doom's (D17, 567 pixels). 23-55: Sewer Sam rewrites BACKTAB during the display, so the row copy times decide the picture (T5: the model copies at the fetch cycle, MAME at its real-time row timers) and the stolen cycles (T2) move when it rewrites: 1,008-4,464 pixels in the cards at x = 13. 60-300: 7,488 pixels in every snapshot: the CPU loses about 1,470 cycles a frame to BUSRQ (T2), which MAME never takes, and the game's picture runs out of step with MAME's |
| TRON Solar Sailer | 2 of 13 (100, 624) | 19 and 648-700: 64-6,916 pixels. With BUSRQ off, 4 of these 11 match (648, 651, 652, 660) and the other 7 shrink to 4-800 pixels (row copy times, T5); the rest comes from the stolen cycles (T2), which move the game's timing |

The causes of the Sewer Sam and Solar Sailer differences were separated
with two diagnostic runs (not gates): with BUSRQ off (mode `none`, rows
still copied at the hardware fetch cycles) Sewer Sam matches at 9, 10, 55,
120 and 300 and differs by 240-2,594 pixels elsewhere (T5 only), and
Solar Sailer matches at 6 of 13 and differs by 4-800 pixels elsewhere. With
MAME's memory map forced into mode `stic` or `none`, Sewer Sam's results do
not change at all. Solar Sailer's change only a little: in mode `stic` the
same snapshots match (19 differs by 170 pixels instead of 124), and in mode
`none` 649 matches too (7 of 13), with 19 and 665 at 92 and 24 pixels
instead of 48 and 26. So the map does not cause the differences in these two
games; it only moves Solar Sailer's timing slightly. Which of the two
pictures a real console shows is the hardware question of T1-T5 (our own
STIC test ROM; not answerable without a flash cartridge).

Stolen cycles per frame in mode `stic`, 300 frames each:

| Game | VDR | Requests (frame + rows) | Mean (min-max) stolen | MAME intended | S9 |
|---|---|---|---|---|---|
| Astrosmash | 0 | 14 | 1,438.9 (1,382-1,440) | 1,472 | 1,416 |
| Tower of Doom | 0 | 14 | 1,433.5 (1,425-1,520) | 1,472 | 1,416 |
| Dig Dug | 0 | 14 | 1,407.2 (1,391-1,443) | 1,472 | 1,416 |
| Sewer Sam | 0 | 14 | 1,469.9 (1,420-1,495) | 1,472 | 1,416 |
| Diner | 0 | 14 | 1,460.5 (1,440-1,517) | 1,472 | 1,416 |
| Diner | 2-6 | 13 | 1,402.0 | 1,362 | 1,362 |
| Body Slam | 1-3 | 13 | 1,330.4 (1,287-1,362) | 1,362 | 1,362 |

The first enabled frame of each game has no requests: its $20 write came
after cycle 3,790 (D8).

**Sensitivity.** Each of 18 planted faults in a copy of `stic.py` must
make one of the comparisons above fail; 17 do: delays and border
extensions ignored (4), stack advance off, pastel foreground bit dropped,
squares colour 7, squares quadrant 3 bit 2, squares off, FGBG background
bits 3 and 2/3, GRAM card mask, pixel order, 160th column shown, border
colour, display-off frames drawn, MAME row timing 900 cycles late. Not
caught: quadrants 1 and 2 of a Colored Squares card swapped (no squares
card in Sewer Sam or Blockade Runner has different colours there). Other
coverage gaps: the colour of the strip a delay uncovers is the border
colour in every matched screen with a delay and no extension (Body Slam),
so D6 stays open; a frame enabled after cycle 3,790 in mode `stic` (D8)
is not compared.

Commands (lane scripts outside the repository drive these):

    tools/refs/mame_snap.sh / snaps.sh -> MAME PNG snapshots
    python3 tools/stic_frames.py import --mame-src <mame>/src/mame/mattel/intv.cpp --out FRAMES SNAP.png...
    python3 tools/stic_frames.py compare --cart GAME.int --ref FRAMES --snaps 60,120,...
    tools/refs/mame_trace.sh intv GAME.int 301 OUT
    python3 tools/intv_system.py mame OUT/trace.log --cart GAME.int --timing computed

## 4 The RTL (build step 4)

`src/fpga/core/intv_stic.sv` replaces the step-3 register stub
(`intv_stic_regs.sv`; its read masks, handshake, mode latch and closed
accesses are kept unchanged). It follows the model in modes `stic` (BUSRQ
on, as the core runs) and `none` (`busrq_en` = 0, benches only).

**Timing as built** (CPU cycles from the frame start, 57 a line; the frame
position is the raster's, `intv_timing`):

| What | When | Notes |
|---|---|---|
| frame latches: display enable, VDR | the ce that ends cycle 3,789, after that cycle's write | the model's `window_end` |
| frame BUSRQ | 3,790-3,831 when enabled | T4 |
| row r BUSRQ | lines 68 + 2 VDR + 16 r and the next, while they fit (12 rows, 13 with VDR = 0) | T1, T3 |
| row r copy | the start of line 69 + 2 VDR + 16 r, if BUSAK is low in that cycle (or BUSRQ is off): 20 words from System RAM's port B, two clk_sys a word, done 41 clk_sys after the cycle starts (the CPU's next write could come at 48) | T10: all or nothing |
| card engine | pixel clocks 8-27 of line L build line L + 1 into a two-bank line buffer, one card a pixel clock: row-buffer word, GROM / GRAM byte, colours, stack | |
| picture | line buffer shown from pixel clock 37 (playfield x 0) of lines 70-261; border elsewhere | D14 below |
| border pixels | register $2C live: a write in cycle t shows from pixel clock 4 t + 5 | D17 |

**Picture semantics.** The RTL draws line by line, so a frame's picture
cannot depend on what the CPU does after it is shown. Where MAME's
draw-at-vblank and the hardware can differ, the RTL (and the model in
modes `stic` / `none`) takes:

- the display enable at the end of the VBlank window: a $20 write after
  cycle 3,789 leaves that frame blank (D8; MAME draws it). This is the
  first enabled frame of most games (one picture);
- the border colour live, pixel by pixel (D17): a write in VBlank shows
  from that pixel on, in the lower border of the picture before (picture
  rows 216-239 are lines 0-23 of the next frame) and in its top border;
  in a blank frame the CPU may change it anywhere. The model therefore
  hands a picture out only at line 24 of the next frame;
- CSR, HDR, CBR, the mode and GRAM live: closed to the CPU from cycle
  3,790 when the display is enabled, unused when it is not.

Mode `mame` keeps MAME's semantics, so the MAME comparisons of section 3
are unchanged.

**Framing (D14).** RTL picture n (the model's numbering) is raster lines
46-261 of frame n - 1 and 0-23 of frame n, pixel clocks 24-212: MAME's
13/17 pixel and 24/24 line border around the 159 x 192 playfield, which
starts at pixel clock 37 and line 70 (the first fetch, 3,933, is line 69).
The Pocket shows the playfield (160 x 192, slot 0) or the playfield with 3
pixels left, 4 right and 9 lines above and below (167 x 210, slot 1;
`pocket_video`); the bottom border lines are the next frame's VBlank lines
0-8. The colours are MAME's palette (`intv_palette.sv`, BSD-3, credited
in THIRD_PARTY_NOTICES.md) until a capture of the owner's console.

**Pattern reads (D15).** The RTL reads a card's pattern byte once per
scanline (twice per card pixel row), from GROM's second port or GRAM's
port B; the bench logs the card rows at their first line, as the model's
card log gives them.

**State.** STIC id $04, 55 words (67 from step 5, section 6): the registers, {handshake, mode}, the
frame latches (enable, VDR), the fetch
state (FIFO counter, armed, copy running, word, phase), the colour-stack
position and its value at the card row's start, the next pixel's colour;
$0C the row buffer (20 words), $0D the line buffer (64). The row and
column positions are the raster's (`intv_timing`'s state). Every block-RAM
read port is read every clock from an address that depends only on the
state and the position, and its word is used only after the address has
been stable for a clock, so a freeze may fall in any clk_sys.

**Gates** (lane `stic-rtl`): see `sim/tb/README.md`; results in the lane's
NOTES.md.


## 5 MOBs and collisions (build step 5, model)

### 5.1 What the model does

**MOB registers** (S9 stic.txt:204-234; MAME stic.cpp:40-107, 1203-1309;
GI80 p.5-10). Read masks as in step 3 (MAME stic.cpp:1139-1180).

| Register | Bits |
|---|---|
| X, $00-$07 | 0-7 X coordinate, 8 INTR (interacts), 9 VISB (visible), 10 XSIZE (16 pixels wide) |
| Y, $08-$0F | 0-6 Y coordinate (in card pixel rows, 2 scanlines each), 7 YRES (two cards, 16 pattern rows), 8 YSIZ2, 9 YSIZ4, 10 XFLIP, 11 YFLIP |
| A, $10-$17 | 0-2 colour, 3-10 card (GROM 0-255; GRAM bits 3-8, 0-63), 11 GRAM, 12 colour bit 3, 13 PRIO (behind the background) |
| C, $18-$1F | 0-7 collision with MOB 0-7, 8 with the background, 9 with the border |

- Placement: the object field starts 8 pixels left of and 8 pixel rows (16
  scanlines) above the card grid and moves with the delays; a MOB whose X
  coordinate is 0 does not exist (not drawn, no collisions); Y = 0 is not
  special (S9 stic.txt:86-194; MAME stic.cpp:789, 798-799). In the
  picture of section 1: x = X - 8 + 13 + HDR, line = (Y - 8 + 12 + VDR) x 2.
- Size: 8 pixels wide, 16 with XSIZE, each pattern bit then 2 pixels. Each
  pattern row is 1 scanline, 2 with YSIZ2, 4 with YSIZ4, 8 with both; 8
  pattern rows, 16 with YRES (two cards). So the default MOB is 8 scanlines
  = 4 card pixels high and the largest 128 scanlines (S9 stic.txt:259-284,
  table; MAME stic.cpp:605-646 the same; GI80: "half height, y zoom, x zoom
  and 8 or 16 character lines high").
- XFLIP mirrors each line, YFLIP the line order (of both cards with YRES).
- Colour: bits 0-2 and 12, all 16 colours. VISB clear: not drawn, but it
  still interacts (S9 stic.txt:243-245; MAME stic.cpp:789, 834-837).
- Pixels outside the playfield are never shown (the border is drawn over
  them, MAME stic.cpp:1102-1108; the strip a delay uncovers too, D6).
- Priority: MOB 0 over MOB 1 over ... MOB 7. PRIO puts a MOB's visible
  pixels behind the background's "on" pixels (the card's foreground,
  Colored Squares colours 0-6) and in front of its "off" pixels. How the two
  orders combine differs (M3).

**Collisions** ("interaction", S9 stic.txt:239-245, 311-329; MAME
stic.cpp:539-603, 777-851, 1111-1131):

- a MOB's pixel on an "on" background pixel sets its bit 8; a MOB pixel
  outside the collision area sets bit 9. The area is the playfield's pixels
  13-171 (the 159 shown columns) and lines 24-215, its left edge 8 pixels
  and its top edge 16 lines further in with the border extension bits;
  the 160th column counts as border (MAME stic.cpp:801-804, 817-822; M8);
- two MOBs that both have INTR set and a pixel on the same spot set each
  other's bits 0-7, anywhere in the object field (MAME; M7); a MOB never
  sets its own bit, and a write never sets it either (step 3);
- INTR clear: the MOB sets no bit (and no other MOB's bit for it); VISB
  does not matter;
- the bits are sticky: the model ORs them in, only a CPU write clears them,
  and bits stay set when INTR is cleared later (S9 stic.txt:322-327).

**When the bits are set.** The hardware sets them while it draws the
frame; MAME sets them all at its vblank, when it draws the frame (stic.cpp:1111-1131). The model ORs them in when
it draws the frame (modes `stic` and `none`: at the frame's end; mode `mame`: at MAME's vblank boundary). With
the display enabled the registers are closed from cycle 3,790 to the frame's
end, so the CPU cannot tell the two apart; with the display not enabled
nothing is drawn and no bit is set (MAME screenrefresh does the same,
stic.cpp:1132-1135). The RTL may set them pixel by pixel.

**Two rule sets.** Mode `mame` follows MAME's stic.cpp line by line; modes
`stic` and `none` (the hardware model, the RTL's reference) follow S9 where
S9 (or the wiki) says otherwise, and MAME where they say nothing (M1-M5).
`Stic.mobs = False` turns MOBs off (backgrounds only, as step 4):
`sim/tb/tb_system.py` sets it (`STIC_MOBS`) until the step-5 RTL draws
MOBs. With MOBs off the model's pictures, STIC logs and machine state are
identical to step 4's (checked: modes `stic`/`none`/`mame` on 6 runs of
300-700 pictures, SHA-1 of every picture, row fetch, card log and the final
state).

### 5.2 Where the sources disagree

| # | Topic | Sources | Model |
|---|---|---|---|
| M1 | YRES card number | S9: the upper half always comes from an even card, the lower from the next odd card; bit 0 of the card number is ignored (stic.txt:274-279, 305-306). MAME reads card N and N + 1, so an odd N gives N, N + 1 (stic.cpp:618-636) | `mame`: MAME; `stic`/`none`: S9 |
| M2 | MOB GROM cards in Foreground/Background mode | S9: card bits 6-7 ignored in FGBG mode, so GROM 64-255 are not available to MOBs (stic.txt:298-303, 459-461); WIKI STIC: "both the BACKTAB and the MOBs are limited to GROM cards 0 through 63"; MAME: GROM 0-255 in both modes | `mame`: MAME; `stic`/`none`: S9 and WIKI |
| M3 | MOB order and PRIO together | S9: "MOBs are first ordered according to their number ... The PRIO bit does not affect MOB-to-MOB priority ordering" (stic.txt:247-252): the lowest-numbered MOB with a visible pixel there wins, then its PRIO decides against the background. MAME draws MOB 7 to MOB 0, each over the last, and skips a PRIO MOB's pixel over an "on" background pixel, so the higher-numbered MOB under it shows there (stic.cpp:786-851) | `mame`: MAME; `stic`/`none`: S9 |
| M4 | Background under a delay strip, for collisions | S9: the object field outside the cards is "filled in with the background color", i.e. no "on" pixels (stic.txt:121-125); MAME draws no cards there and its bitmap keeps what the frame before left (stic.cpp:668-775, 1102-1108): a card pixel of a frame with a smaller delay still counts as "on" | `mame`: MAME (the model keeps MAME's last "on" pixels); `stic`/`none`: no "on" pixels. Shown pixels are the border colour in both (D6) |
| M5 | Colour 7 of a Colored Squares card | S9: never "on" (stic.txt:433-434); MAME takes the colour-stack register as stored, 16 bits, and its bit 4 is MAME's "on" flag (stic.cpp:685-697; D12) | `mame`: "on" when bit 4 of the stored word is set; `stic`/`none`: never |
| M6 | When collision bits are set | S9: set by an interaction, sticky; when in the frame not said. MAME: all at the vblank | at the frame's end (section 5.1); the CPU cannot tell while the display is enabled |
| M7 | MOB to MOB collisions outside the playfield | MAME: anywhere in both MOBs' boxes, also over the border and under the delay strip (stic.cpp:539-579); S9 does not say | MAME, all modes. Hardware test: our STIC test ROM |
| M8 | The border for collisions | MAME: outside playfield columns 0-158 (picture x 13-171) and lines 24-215, edges moved in by the extension bits, not by the delays (stic.cpp:801-804, 817-822); S9: "interacts with the display borders" | MAME, all modes. Whether the 160th column and the delay strips count is a hardware question (test ROM) |
| M9 | Collisions of invisible MOBs | DESIGN 13.8 listed this as unknown; S9 stic.txt:243-245 says it: "The MOB does not need to be visible in order to interact with other MOBs, background cards or the screen border"; MAME the same | no disagreement: INTR alone decides |
| M10 | GROM card 255 with YRES | MAME reads GROM bytes 2,048-2,055, past its 2 KiB region (stic.cpp:629-631, undefined); with M1 the hardware reads cards 254 and 255 | `mame`: $FF for bytes past GROM (no game in the done-test does this); `stic`/`none`: M1 |

### 5.3 Bus accesses

MOB patterns come over the graphics bus: GI80 p.5-10: "The graphics
control BUS is used during 'STIC' time in the fetch of 'foreground' object
patterns and 'background' object patterns". So a MOB costs the CPU no
BUSRQ and no cycles: the BUSRQ schedule of section 1 (frame request, one
request per card row) is unchanged. When and how often the STIC reads a
MOB's pattern rows is not documented (as D15 for cards). The bus log
(`stic_frames.py run`, `m<N>.bus.txt`) adds one MOB line per MOB that is
drawn or interacts (its GROM/GRAM rows, its top left pixel) and a COLL line
with the bits the frame sets.

### 5.4 Done-test (build step 5, model)

DESIGN 9 step 5: "10 more games match; STIC test ROM passes". The task for
the model: mode `mame` matches MAME's frames, with no masks, on every screen
of steps 4 and 5, and MAME's traces of the MOB games, where the collision
reads must match for the trace to match. Snapshots, frames and traces stay
outside the repository. Result 2026-10-25 (mode `mame`): **pass**.

Snapshots, compared pixel for pixel with no masks (`stic_frames.py
compare`, mode `mame`; snapshot N against model picture N - 1):

| Screens | Snapshots | With MOBs drawn | Result |
|---|---|---|---|
| Step 4: the 26 games and the no-cartridge EXEC of section 3 (Beamrider, Body Slam, BurgerTime, River Raid, TRON Solar Sailer, Zzzz Spina the Bee and Thunder Castle were masked there) | 286 | 77 | all match |
| Atlantis | 8 (60-700) | 8 | all match |
| Demon Attack | 8 (60-700) | 8 | all match |
| MTE201 test cartridge | 110 (3-16, 142-180, 209-222, 240-400, 420-900) | 81 | all match |
| Buzz Bombers, Centipede, Defender, Dracula, Dragonfire, Ice Trek, Tropical Trouble | 35 each (20-700, every 20) | 35 each | all match |
| Also: Fathom, Nova Blast, International Demonstration Cartridge | 35 each | 29, 35, 3 | all match |

In all 762 snapshots of 39 cartridges and the EXEC, 486 of them with MOBs.
The step-5 games use, between them, every MOB feature: GROM and GRAM cards,
XSIZE, YSIZ2, YSIZ4, YRES, XFLIP, YFLIP, PRIO, pastel colours, MOBs that
only interact (INTR without VISB), and collisions with MOBs, the background
and the border (MTE201 alone has all of them; per game: lane notes).

MAME traces (`tools/refs/mame_trace.sh`, `intv_system.py mame --timing
computed`): every read and write equal, so every collision register read
returns MAME's value:

| Game | Frames | Steps | Collision register reads (with a bit set) | First set bit read |
|---|---|---|---|---|
| Atlantis | 301 | 575,793 | 2,392 (350) | frame 8 |
| Demon Attack | 301 | 577,031 | 2,392 (292) | frame 9 |
| MTE201 | 301 | 539,191 | 344 (186) | frame 15 |
| Buzz Bombers | 301 | 583,708 | 1,144 (96) | frame 23 |
| Centipede | 400 | 702,226 | 415 (82) | frame 314 |
| Defender | 450 | 827,003 | 168 (11) | frame 354 |
| Dracula | 301 | 566,010 | 2,288 (415) | frame 18 |
| Dragonfire | 301 | 582,835 | 2,360 (223) | frame 9 |
| Ice Trek | 301 | 572,399 | 2,128 (516) | frame 15 |
| Tropical Trouble | 301 | 572,383 | 2,336 (8) | frame 115 |

All pass (MAME_COMPARE pass). The 9 traces of section 3 (no cartridge,
Astrosmash, Tower of Doom, Diner, Dig Dug, Sewer Sam, Solar Sailer 652
frames, Safecracker, Beamrider) pass again with the MOBs on, with the same
step counts.

**Sensitivity.** Each of 23 planted faults in a copy of `stic.py` (mode `mame`)
must make one of the comparisons above fail; 20 do: MOB order 0 to 7, PRIO
ignored, XSIZE, XFLIP, YFLIP, YSIZ2, YSIZ4 or YRES ignored, GRAM card mask
5 bits, colour bit 3 dropped, X one pixel off, Y one scanline off, X = 0
drawn, invisible MOBs drawn, no background, border or MOB collisions, the
right border one column late, collisions only for visible MOBs (Atlantis
trace), collision bits overwritten instead of ORed (Centipede trace). Not
caught: the bottom border one line late, MAME's stale "on" pixels under a
delay strip ignored (M4) and MAME's colour-7 "on" bit ignored (M5): no game
in the set has a MOB there or such a colour-stack value. These need our own
STIC test ROM: since the step-5 review, sticmob run in MAME checks all
three against MAME itself (section 6, "Our STIC test ROM").

**Hardware rules against MAME.** A diagnostic (lane script, not a gate) redrew every
enabled picture of the 20 MOB games above, in their mode `mame` runs, with
the hardware rules from the same registers, rows and GRAM. No picture
changes in any of them (M3's PRIO MOBs appear in Centipede, Dracula,
Dragonfire, Fathom, River Raid, Thunder Castle and MTE201, but never over
another MOB on an "on" pixel). The collision bits change in MTE201 only,
at pictures 293-296: its eight MOBs use YRES with an odd card number (M1),
and under MAME's rule all eight collide with each other, the background and
the border, under S9's none. Run on MAME's timing with the hardware rules,
MTE201's snapshots 240-900 still all match MAME, so the test shows nothing
on screen for it there. Mode `stic` (hardware timing and rules) against the
same MAME snapshots, for comparison with section 3: Buzz Bombers 35 of 35
match, MTE201 105 of 110 (500-580: it fills BACKTAB during the display,
T2/T5), the others 0-18 of 35 (and 0 of 8): the stolen cycles (T2) change
when the games move their MOBs, as for Sewer Sam in section 3.

### 5.5 Hardware checks

The owner's console (no flash cartridge) can settle little here:

- the games here draw the same pictures under both rule sets (5.4), so
  watching them on the console cannot tell M1-M5 apart;
- MTE201 differs only in collision bits at pictures 293-296 and shows no
  difference on screen in the snapshots checked; and it is a factory test
  cartridge the owner may not have;
- what a console run of a game can show is the T2 question of section 3
  again (MOB games run with the hardware's stolen cycles): not new.

M1-M8 otherwise need our own STIC test ROM on hardware (a flash cartridge),
as D6, D8 and T1-T10 do. sticmob shows M1, M4 and M5 by its border colour
(section 6); ECS BASIC is no way round the flash cartridge as far as our
sources go (section 6).


## 6 MOBs and collisions in the RTL (build step 5)

`intv_stic.sv` follows the model's hardware rules (modes `stic` and
`none`; 5.1, M1-M5) pixel for pixel and bit for bit. How it is built:

**When the registers are read.** MOBs and collisions exist only in frames
whose display is enabled at the end of the VBlank window. From then
(cycle 3,790) to the frame's end the MOB registers, HDR / VDR / CBR, the
mode and GRAM are closed to the CPU, so whatever the RTL reads in that time
is what the model's `draw()` reads at the frame's end. Picture lines 8-23
(raster 54-69) and the lines below the raster can hold MOB pixels too, but
none of them is shown, so they matter only for collisions (below).

**Three users of the graphics bus** (GROM's second port, GRAM's port B),
by raster position:

- the card engine, pixel clocks 8-27 (as step 4);
- the line's MOBs, pixel clocks 196-203 of line L (after the playfield's
  last pixel, 195): MOB m's pattern byte for line L + 1, turned at once
  into a 16-pixel mask (`rm[m]`, XSIZE and XFLIP applied). Line L + 1's
  pixels take bit `nx - (X + HDR + 29)` of each mask;
- the collision sweep, at every other pixel clock (`g_ok`: neither this
  pixel clock nor the one before belongs to the other two). It starts at
  the end of the VBlank window and walks picture lines 8-403, the lines
  any MOB can cover (top 2 (Y + 4 + VDR) >= 8, bottom at most 2 (127 + 4 +
  7) + 128 - 1), on and off the raster: for each line the 8 masks of the
  MOBs with INTR (two clocks a MOB: address, then the word), each MOB's
  border test, then the 28 pairs one a clock (`(mask_j << d) & mask_i`,
  d = X_j - X_i, |d| < 16). About 45 clk_sys a line plus the waits: it ends
  some 7 lines after it starts, long before the frame's end.

So MOB-MOB collisions are taken over each MOB's whole box, also over the
border, under the delay strips and below or right of the raster (M7), and
border collisions over every pixel outside the collision area (picture
columns 13-171, lines 24-215, the left / top edge 8 columns / 16 lines in
with CBR; M8), with no raster time needed for lines that the raster never
draws.

**The pixel.** One pixel ahead, as in step 4: each MOB's bit for this
pixel; the lowest-numbered MOB with VISB and a bit set wins (M3) and shows
its colour (bits 0-2 and 12) unless its PRIO is set and the background
pixel is "on". "On" is the card's foreground pixel or, in a Colored
Squares card, a quadrant whose colour code is not 7 (M5: the line buffer
carries two more bits per card, "on" for a pattern bit 1 and for a 0);
nothing is "on" in the strips the delays uncover (M4). The MOB shows only
inside the playfield, as the cards do. Inside the collision area a MOB
with INTR on an "on" pixel sets its background bit.

**Collision bits.** Gathered in `coll_p` (10 bits a MOB) during the frame,
ORed into $18-$1F (without the MOB's own bit) and cleared at the frame's
end, exactly when the model ORs them in (5.1: the registers are closed
until then, so the CPU sees the same either way; a dump in the middle of a
frame shows the same registers as the model's too).

A CPU write to $18-$1F in the frame's last cycle (slot 14,933) falls in
the same clock as that OR. Our choice: the write is kept and the frame's
bits are ORed into the written word (the model's order: the write belongs
to the frame, its draw comes after it). The documents say only that the
bits stay set until the CPU writes the register (S9 stic.txt:322-327) and
nothing about a write at the very moment the STIC sets them, so the
choice is ours; it cannot be seen on hardware either way, because the two
cannot meet: a frame gathers bits only when its display is enabled, and
then the registers are closed from the end of the VBlank window to the
frame's end; in a frame whose display is off they are open all frame but
there are no bits, and the write simply wins. (Before the step-5 review
the RTL rewrote all eight registers at every frame's end, so such a
write in a display-off frame was lost; the bench's systest probe p11 now
writes $18 in exactly that slot, and the plant
`coll_frame_end_drops_write` brings the old behaviour back and is
caught.)

**Pattern addresses.** Card bits 3-10; bits 6-7 count only for a GROM card
in Color Stack mode (M2); with YRES bit 0 is dropped and rows 8-15 come
from the odd card (M1); the row is (line - top) >> (2 YSIZ4 + YSIZ2), XOR 7
(or 15 with YRES) with YFLIP. Under these rules no address passes the end
of GROM or GRAM (M10 does not arise).

**State.** Id $04 grows by 12 words to 67: $37 the sweep (line, MOB or pair,
fetch / pair phase, word phase, running), $38-$3B its 8 masks, $3C-$3F the
8 line masks, $40-$42 the gathered bits. The line buffer ($0D) is 18 bits
wide (the two "on" bits). The sweep takes a GROM / GRAM word only when the
port's address has been its own for a clock, so a freeze, save or restore
may fall in any clk_sys, inside the sweep or inside a line's MOB fetch
(the bench's rt6, rt7 and rt8).

**Our STIC test ROM** (`sim/testroms/sticmob.asm`, image `sticmob`): 22
scenes, one a frame, each with the collision words S9's rules give for
it, checked by the program itself in the next VBlank (the fail count in
System RAM $0303, a failed-scene mask in $030A / $030B, the border green,
yellow or red). It covers every size and flip, X = 0, invisible MOBs, the
order with PRIO (M3, on screen), YRES with an odd card (M1), GROM cards
64-255 in both modes (M2, on screen), the delay strip (M4), squares
colour 7 (M5, CSR0 written with bit 4 set), each border edge one pixel /
line inside and outside (also with delays and border extension), MOBs
below and right of the raster, and the bits' stickiness. Since the step-5
review it also covers (S18-S21) the background-collision area, which the
RTL tests apart from the sweep's border test: an "on" card pixel on the
bottom line 215 (with VDR 0 and with VDR 7, the cards moved down) is a
background collision and on line 216 only a border one; the same for
column 158 and the 160th column 159; under the extended left and top
borders (CBR 3) an "on" card pixel in column 7 or line 39 is only a border
collision, in column 8 or line 40 a background one. And YFLIP with YRES
(the 16 rows reversed, so the two cards swap halves), MOBs with INTR and
no VISB colliding, and the sweep's first line 8 (Y = 0, VDR = 0: two MOBs
that meet only there) and last row (Y = 127, VDR = 7, YRES + YSIZ4 +
YSIZ2: two MOBs that meet only in picture lines 396-403).

The review's plants for these edges are on the bench (128 plants), with
one exception: "the sweep ends at line 402" cannot be caught by any
program, because line 403 is the last of an 8-line pattern row (only
YRES + YSIZ4 + YSIZ2 with Y = 127 and VDR = 7 reaches it, and then lines
396-403 are one row): any pixel on 403 is on 396-402 as well, for the
pairs and for the border test. The plant `coll_sweep_to_395` (the last row
lost) stands for it and is caught.

The model in hardware rules passes it (0 fails, 2 passes in 46 frames);
with MAME's rules (`Stic.mob_rules = "mame"`, diagnostic) it counts 5 fails
a pass: M1 (2, S10), M4 (1, S5), M5 (2, S7). **MAME itself** gives the same:
`tools/refs/mame_exec_prog.sh` runs the program in MAME in place of the
EXEC (a rompath copy whose exec.bin is our image; MAME warns about the
checksum and runs it) and logs its RAM words every frame. Over 100 frames
MAME counts 23 fails, 5 in each of the 4 whole passes and 3 in the fifth,
all in S5, S7 and S10 (mask $04A0), and passes every other scene, among them the
bottom border lines 215 / 216 and the background-area edges of S18-S21. So
the three model faults that no game caught (5.4: the bottom border one line
late, M4, M5) now have a check against MAME too, through this program; and
the border's yellow ("only the scenes where MAME's rules differ failed")
is what a console that behaves like MAME would show.

So the ROM, run on a console, answers M1, M4 and M5 by the border colour
(green: S9's rules; yellow: MAME's; red: something else, the mask says
which scene) and shows M2 and M3 on screen (S13 and S1). It runs in the
EXEC slot, on the bench and in MAME; a cartridge build (a header and the
EXEC's start-up instead of our own ISR vector) is not made, and on the
owner's console it needs a flash cartridge. ECS BASIC as a way round
that: none of our sources (DESIGN 12: the wiki archive, S9, the service
manual) documents an ECS BASIC statement that writes an arbitrary address
(a POKE) or the MOB registers, so we cannot say that it can drive the STIC
from BASIC; until the owner's ECS BASIC manual shows otherwise, the flash
cartridge conclusion of DESIGN 13 stands.

**What the step-5 done-test proves for the RTL.** DESIGN 9 step 5: "10
more games match; STIC test ROM passes". As for step 4 (section 3) the
match is a chain of two gates that compare different things: the RTL
equals the model's mode `stic` (the frame gate, `tb_system.py --screens`:
every picture, row fetch, card row, frame's collision bits and bus cycle
of the 10 MOB games, 700-900 pictures each), and the model's mode `mame`
equals MAME (5.4: 762 snapshots, the traces with every collision read).
The two modes differ in timing (T2, T5: BUSRQ's stolen cycles, row copy
times) and in the MOB rules M1-M5. The rules were shown not to change any
picture of these games (5.4, "hardware rules against MAME"). The timing
was not: whether mode `stic`'s pictures are MAME's pictures in another
phase was only assumed until the step-5 review. A diagnostic (lane
script, not a gate) compared every mode-`stic` picture with the MAME
snapshots at frame offsets -3 to +3:

| Game | Snapshots | Equal at offset 0 | Equal only at another offset | Equal at none | Smallest difference over the offsets, pixels (median, max) |
|---|---|---|---|---|---|
| Atlantis | 8 | 0 | 0 | 8 | 276, 370 |
| Demon Attack | 8 | 0 | 0 | 8 | 220, 309 |
| MTE201 | 110 | 105 | 5 (+1) | 0 | 0, 0 |
| Buzz Bombers | 35 | 35 | 0 | 0 | 0, 0 |
| Centipede | 35 | 15 | 1 (+1) | 19 (from 340) | 106, 731 |
| Defender | 35 | 14 | 0 | 21 (from 300) | 602, 1,083 |
| Dracula | 35 | 1 | 0 | 34 | 4,474, 4,586 |
| Dragonfire | 35 | 18 | 1 (+1) | 16 | 0, 34 |
| Ice Trek | 35 | 0 | 2 (-1, +2) | 33 | 14,832, 14,867 |
| Tropical Trouble | 35 | 3 | 1 (-2) | 31 | 143, 235 |

So it is not a phase: in 8 of the 10 games the hardware timing leads the
game itself somewhere else (other object positions, other screens: Ice
Trek's pictures differ almost everywhere), as Sewer Sam's did in section
3. Only MTE201 and Buzz Bombers draw MAME's pictures. That is what the
stolen cycles do to a game that runs its logic against the frame (T2),
and which of the two a console draws is the open hardware question T1-T5.
The reading "RTL = mode `stic`, mode `mame` = MAME" therefore means: the
RTL draws exactly what our model of the hardware draws, and our model
under MAME's timing and rules draws exactly what MAME draws; it does not
mean that the RTL's pictures look like a MAME video of the same game. The
owner accepts this reading of DESIGN 9's done-test or asks for a direct
RTL-against-MAME gate (which would need the RTL to run MAME's timing).

**Gates** (lane `mob-rtl`; results in its NOTES.md; the step-5 review
fixes in lane `mob-fix`): see `sim/tb/README.md`.
