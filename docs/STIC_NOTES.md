# STIC notes (build step 4: backgrounds)

What the STIC model (`tools/stic.py`, driven by `tools/intv_system.py`) does,
where each fact comes from, and every place where the sources disagree.
MOBs and collisions are build step 5; their registers are stored and read
back here, nothing more.

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
  $001B = $3E00 at frame 8 of its trace). Such games wait for step 5.

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
| TRON Solar Sailer | 2 of 13 (100, 624) | 19 and 648-700: 64-6,916 pixels. With BUSRQ off they shrink to 4-800 pixels at 6 of these snapshots (row copy times, T5); the rest comes from the stolen cycles (T2), which move the game's timing |

The causes of the Sewer Sam and Solar Sailer differences were separated
with two diagnostic runs (not gates): with BUSRQ off (mode `none`, rows
still copied at the hardware fetch cycles) Sewer Sam matches at 9, 10, 55,
120 and 300 and differs by 240-2,594 pixels elsewhere (T5 only), and
Solar Sailer matches at 6 of 13 and differs by 4-800 pixels elsewhere; with
MAME's memory map forced into mode `stic` or `none` the results do not
change, so the map plays no part in these two games. Which of the two
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

**State.** STIC id $04, 55 words: the registers, {handshake, mode}, the
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

