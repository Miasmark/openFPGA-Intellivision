# Intellivision core for the Analogue Pocket: design

*Repository copy, 2026-10-25. The text is the research draft as reviewed, with the owner's local paths removed. Paths `docs/...` and `research/...` below point into the project's research folder, which stays outside this repository: it holds copyrighted manuals, user-supplied ROMs and data derived from games. This repository's own `docs/` holds this file and `SOURCES.md`.*

*Draft 1, 2026-10-24. Written from the five research lanes of 2026-10-24 (service manual, wiki, datasheets and licences, Pocket and save states, test assets). Nothing here has been built or simulated.*

*Reviewed 2026-10-24 (lane `research/review/`). Corrections are marked **(review)** in place; new findings and open questions are in section 13. Arithmetic behind the corrections: `research/review/scripts/review_checks.py`.*

Tags: **[from X]** = taken from source X (codes in section 12). **[measured]** = counted or computed on the VM by a lane script. **[estimated]** = a design estimate. "The owner" is the project owner.

---

## 1 Goal and constraints

**Goal.** A new Intellivision core for the Analogue Pocket (openFPGA). It runs the Master Component, plus ECS, Intellivoice and JLP. It loads cartridge images directly and supports save states and sleep from the first release [from PJ].

| Constraint | What it means for the design | Source |
|---|---|---|
| Licence | Own code under MIT, or the whole core GPL-3.0-or-later. Third-party parts listed as in openFPGA-7800. | PJ; 7800 README.md:538-545 |
| Clean room | Do not open Grabulosaure's Intv_MiSTer. No code from jzIntv (GPL-2) or FreeIntv. jzIntv documents may be read as format specifications. MAME (BSD-3) may be read and cited. | PJ |
| Primary references | Mattel service manual, GI datasheets. Cite page or sheet. Code printed in documents (EXEC listings) is reading only. | PJ |
| Save states designed in | Every module has a state port from its first version. Nothing that changes at run time is hidden from it. | PJ; section 4 |
| User-supplied system ROMs | EXEC, GROM, ECS ROM and SP0256-012 are loaded by the user. Never in the repo or a release. | PJ; owner rule "no game data in the repo" |
| No game data in the repo | Test images come from the owner's library or from our own assembler. Only hashes are committed. | owner rule; L-TA |
| No `.intv` conversion | Raw `.int`/`.bin`, `.bin`+`.cfg` and Intellicart `.rom` load directly. | PJ |

---

## 2 System architecture

### 2.1 The real machine (NTSC Model 2609)

| Ref | Part | Role | Source |
|---|---|---|---|
| U1 | CP-1610 | 16-bit CPU, multiplexed address/data bus | SM p.19, p.41-42 |
| U2 | RA-3-9600 | System RAM, 352 x 16 (BACKTAB), Bus Copy and video FIFO | SM p.50-51; MAME intv.h:93 |
| U3, U9 | RO-3-9504, RO-3-9502 | EXEC ROM, 4K x 10 together; U9 also supplies the reset and interrupt vectors on IAB | SM p.19, p.58 |
| U4 | AY-3-8900-1 | STIC, video | SM p.54 |
| U5 | RO-3-9503 | GROM, 2K x 8 | SM p.53; S2 p.468 |
| U6 | AY-3-8914 | PSG, also reads both hand controllers | SM p.19 |
| U7, U8 | GTE 3539 | GRAM, 2 x 256 x 8 | SM p.19 |
| U12 | GTE 3539 | Scratchpad RAM, 256 x 8 (240 mapped) | SM p.19; MAME intv.cpp:281 |
| U10 | AY-3-8915 | Colour encoder, makes 3.579545 MHz from a 7.15909 MHz crystal | SM p.32, p.60-61 |

### 2.2 Block diagram of the core

```
                Pocket APF bridge (74.25 MHz)
                 |            |               |
            data_loader   save-state ctl   cont1-4 / keyboard
                 |            |               |
   +-------------+------------+------+    input module (not saved)
   | cart loader: CRC32, CFG, .ROM   |         |
   | page table, bank regs           |         | virtual hand controllers
   +---------------+-----------------+         |
                   |  SRAM 128K x 16 (cart ROM/RAM, JLP RAM)
                   |
   CP1610 CPU <== CPU bus (phase codes BDIR/BC1/BC2, 16-bit DA) ==>
     |  ^             |        |         |         |        |        |
     |  | INTRM       EXEC     scratch   PSG #1    ECS:     Voice:   cart
     |  | BUSRQ       ROM      RAM 8-bit (ctrl     ROM,RAM  SPB640   mapper
     |  |                               ports)    PSG #2   SP0256   + JLP
     |  |
   bus fabric: System RAM 352x16 + Bus Copy + 20-word row buffer,
               GROM/GRAM decode state  <== graphics bus (14-bit) ==>  STIC
                                                                      |
                                       4-bit colour + blank   ->  palette LUT  ->  Pocket video
   PSG #1 + PSG #2 + speech  ->  mixer, 48 kHz  ->  I2S
```

The STIC sits on its own 14-bit graphics bus with System RAM, GROM and GRAM. The CPU reaches the STIC only through System RAM's Bus Copy mode [from SM p.50-51, p.55; L-SM]. The core keeps this split. It makes the GRAM/STIC access windows and the aliases fall out of the design, not out of special cases.

### 2.3 Clocks

| Clock | NTSC | PAL | Source |
|---|---|---|---|
| Crystal | 7.15909 MHz | not documented | SM p.32 |
| Master (NTSC: colour burst) | 3.579545 MHz | 4.000 MHz, not the PAL subcarrier (4.43 MHz), so the PAL machine probably does not use the AY-3-8915 as on NTSC [estimated] **(review)** | SM p.32; S2 p.461-464; S9 doc/programming/psg.txt:46-47, interrupts.txt:136 (PAL figures there are labelled "ESTIMATES") |
| CPU (master/4) | 894,886 Hz | 1.0 MHz | MAME intv.cpp:445; L-WIKI; S9 interrupts.txt:124, 140 |
| STIC pixel (master) | 279.4 ns per pixel | 250 ns [estimated] | SM p.60 (280 ns); MAME intv.cpp:452 |
| PSG (master/2; tone = master / (32 x period)) | 1.7898 MHz | 2.0 MHz | MAME intv.cpp:470, ecs.cpp:101; S9 psg.txt:46-80 (PAL value is stated there, not estimated) **(review)** |
| SP0256 | 3.12 MHz crystal; MAME runs the sample clock at 3.12 MHz / 336 = 9,286 Hz, not 10 kHz **(review)** | same (own crystal) | S8 pin descriptions XTAL IN/OUT "3.12MHz"; MAME voice.cpp:76, sp0256.cpp:34 (`CLOCK_DIVIDER (7*6*8)`) [measured: review_checks.py] |

The wiki gives 1.6 MHz for the SP0256. **(review)** Resolved: the SP0256 has a 1.56 MHz clock *output* pin (3.12 MHz / 2) that drives the external serial speech ROM [from S8, pin description "1.56MHz clock output used to drive an external serial speech ROM"]. The datasheet gives no sample rate, only a 5 kHz output bandwidth and a 7-bit PWM DAC filtered at 5 kHz [from S8; S6 "DAC Output" section]. The core's speech sample rate follows MAME (9,286 Hz) until a better source appears; see section 13.

**FPGA clock plan** [measured by `research/pocket-savestates/scripts/pll_plan.py`]:

| Output | NTSC | PAL | Use |
|---|---|---|---|
| VCO | 859.0909 MHz (M=11, K=0x91FBC4C3) | 960 MHz (M=12, K=0xEDE62434) | |
| /20 `clk_sys` | 42.954 MHz = 12 x master | 48.000 MHz | all machine logic, with clock enables |
| /10 | 85.9 MHz | 96 MHz | spare (memory) |
| /240 and /240 +90 deg | 3.579545 MHz | 4.000 MHz | Pocket video pixel clock |

Clock enables from `clk_sys`: pixel every 12, PSG every 24, CPU microcycle every 48 [estimated, from the ratios above]. **(build step 6)** The PSG divides its master / 2 clock by 8 before any generator, so `intv_psg` steps on every 4th CPU cycle enable instead of using the PSG enable: the same rate, locked to the CPU cycle count that the model uses. The SP0256 runs from a DDS clock enable, not a PLL output [from L-PSS].

### 2.4 Frame timing (NTSC)

| Figure | Value | Source |
|---|---|---|
| CPU cycles per line | 57 (228 pixel clocks) | MAME stic.h:47 |
| Lines per frame | 262; 192 of them active (96 card-pixel rows x 2) | 14,934 / 57; S9 doc/programming/interrupts.txt:121-122 **(review: stated there, not only estimated)** |
| CPU cycles per frame | 14,934 with display disabled; about 13,518 enabled with vertical delay 0, about 13,572 with vertical delay > 0 **(review)** | wiki STIC timing; S9 interrupts.txt:126-128 |
| Frame rate | 59.92 Hz | MAME intv.cpp:456 |
| VBlank, INTRM held | 3,790 to 3,791 cycles | MAME stic.h:50; wiki |
| First BACKTAB row fetch | cycle 3,933 | MAME stic.h:51 |
| BUSRQ per card row | 110 (MAME) or 114 (wiki) cycles | MAME stic.h:48; L-WIKI |
| BUSRQ once per frame **(review)** | 42 cycles just after VBlank ends, before the first row fetch (MAME: "approximate") | MAME stic.h:49 `FRAME_BUSRQ`; intv_m.cpp:668 |
| Extra row fetch **(review)** | one more row fetch (13 instead of 12) when vertical delay = 0 | MAME intv_m.cpp:680; S9 interrupts.txt:127-128 |
| Card grid | 20 x 12 cards of 8 x 8; 159 or 160 x 96 visible | S2 p.461-464; MAME stic.h:57-58 |

**(review)** MAME's STIC timing constants are not an independent source: stic.h:45 says they are "based on Joe Zbiciak's documentation". Where MAME and the wiki/jzIntv agree, that is one source, not two. They also disagree with each other on the total stolen per frame: MAME gives 12 x 110 + 42 = 1,362 cycles (vertical delay > 0) and 1,472 (delay 0), jzIntv 1,362 and 1,416 [measured: review_checks.py from MAME stic.h:48-49 and S9 interrupts.txt:127-128]. The delay > 0 figure agrees; the delay 0 figure does not (section 13).

**(build step 4)** MAME never applies those stolen cycles: its `adjust_icount` runs in the vblank callback, outside the CPU's time slice, so MAME's CPU gets the whole frame (about 14,934.7 cycles at 59.92 Hz). The STIC model (`tools/stic.py`) has a `stic` mode that steals them as the hardware should (BUSRQ held 114 cycles per row from one scanline before the fetch; the CPU stops at its next interruptible boundary) and a `mame` mode that follows MAME. Timing, the measured stolen cycles and every source disagreement: docs/STIC_NOTES.md. The RTL (`intv_stic.sv`) follows the `stic` mode; as built: STIC_NOTES section 4. Step 4's "frames match MAME" holds for the RTL through the model (RTL = mode `stic` by the frame gate, mode `mame` = MAME); where the two modes differ on the required screens, and why (D8, D17, D18, T2, T5): STIC_NOTES section 3. **(build step 5)** MOBs take no BUSRQ: the STIC reads their patterns over the graphics bus (GI80 p.5-10); MOBs and collisions in the model: STIC_NOTES section 5. The RTL draws them and gathers the collision bits by the model's hardware rules (RTL = model mode `stic` on the frame gate's 17 screens and our STIC test ROM `sim/testroms/sticmob.asm`): STIC_NOTES section 6.

PAL frame timing is not documented anywhere the lanes looked [from L-WIKI, L-PSS]. An estimate is 312 lines, 50.08 Hz [estimated]. **(review)** 50.08 Hz at 312 lines only works with a 64 us line, which is 256 pixel clocks or **64 CPU cycles per line** at 4 MHz (312 x 64 = 19,968 cycles per frame, close to jzIntv's "~20000") [measured: review_checks.py; S9 interrupts.txt:133-147]. With NTSC's 57 cycles per line, 312 lines would give 56.2 Hz. jzIntv itself marks its PAL "57 cycles per scanline" and bus-copy figures as "very possibly BOGUS" [from S9 interrupts.txt:149-150]. So the timing generator, the row-fetch timing and the Pocket video timing must be parameters per region, not fixed at 228/57.

### 2.5 CPU bus model

The CP1610 runs one bus phase per microcycle. The phase is coded on BDIR, BC1, BC2: NACT, BAR, IAB, DWS, ADAR, DTB, DW, INTAK [from S2 p.441-446; wiki Bus_Phases].

- The core carries the phase code as a 3-bit signal plus a 16-bit data-out and a combined data-in. No tristate. **(review)** The real bus has pull-ups: a read that no device answers returns $FFFF [from wiki Memory_Map:14; wiki Bus_Phases ("NACT ... float to all ones")]. So data-in is an AND of active-low contributions (each idle device drives $FFFF), or an OR with a default of $FFFF when no device selects. A plain OR with idle-zero would return $0000 and break peripheral detection (ECS, Intellivoice, cart RAM probes); jzIntv's ECS notes also say unimplemented memory "should always read as $FFFF" [from S9 doc/tech/ecs.html].
- Each peripheral latches its address on BAR or ADAR, as the chips do. Aliases and partial decodes then match the hardware.
- Costs per access: fetch or read 4 cycles, write 5, direct read 6, direct write 7 [from wiki Bus_Phases; L-WIKI].
- No wait states: BDRDY and STPST are tied to +5 V on the board [from SM Fig 7-2, traced; L-SM]. ~~The core keeps a BDRDY input anyway, tied high, so the save-state freeze can use it.~~ **(build step 3)** The core has no BDRDY input: the freeze stops the machine's clock enable (`ce_cpu` from `intv_timing` is low while `run` is low), so the CPU never waits inside a bus cycle; it simply gets no more microcycles until the machine runs again (`cp1610.sv`, docs/CPU_NOTES.md "RTL (build step 3)").
- On INTAK, glue logic shows the cartridge port BAR instead. Only System RAM sees the raw INTAK [from SM Fig 7-2, traced; wiki].
- 8-bit devices: reads in the $01xx range drive DB8-15 to 0 [from SM Fig 7-2, U14/U15].
- ~~**Open:** the manual's phase table (SM p.52, p.59) disagrees with the wiki and MAME on the IAB/ADAR and DW/DWS rows.~~ **(review) Resolved, no disagreement.** The SM p.52 table is headed **BDIR, BC1, BC2** (crop `research/service-manual/img/crops/z_p52tab.png`, viewed), while the wiki and jzIntv tables are headed BDIR, BC2, BC1. Read with its own column order, the SM gives the same codes: in BDIR/BC2/BC1 order NACT 000, ADAR 001, IAB 010, DTB 011, BAR 100, DW 101, DWS 110, INTAK 111. GI's own 1982 catalog uses both column orders: the RO-3-9504 page is headed "BDIR BC1 BC2" and the RO-3-9508 page "BDIR BC2 BC1", with the same encodings [from S2, catalog text lines 2783-2807 and 2938-2948 in `research/datasheets-licences/text/1982_GI_Microelectronics_Data_Catalog.txt`]. The RTL must name its pins BC1/BC2 carefully, but the phase decode is settled.

### 2.6 Memory map (Master Component plus expansions)

| Range | Device | Width / access | Source |
|---|---|---|---|
| $0000-$003F | STIC registers (write-only aliases at $4000, $8000, $C000) | 14-bit | MAME intv.cpp:280; wiki Memory_Map:28 |
| $0040-$005F | Intellicart bank registers, write-only (one per 2K range: $0040-$004F for $x000-$x7FF, $0050-$005F for $x800-$xFFF) | 8-bit value, upper byte ignored | S9 doc/programming/intellicart.txt:228-255 |
| $0040-$007F | **(review)** STIC-responsive, read only, during VBlank period 2 (on the console itself, independent of any Intellicart) | | wiki Memory_Map:22 |
| $0080-$0081 | Intellivoice (SPB640). **(review)** $0080: write = SP0256 address load (8 bits), read bit 15 = LRQ. $0081: write = push 10 bits into the 64-decle FIFO, bit 10 set = reset FIFO and SP0256; read bit 15 = FIFO full | 16-bit | wiki Intellivoice; MAME sp0256.cpp:1189-1245 |
| $00E0-$00E3 | **(review, was missing)** ECS UART: cassette and printer ($E0 status, $E1 data, $E2 control, bit 4 = cassette motor relay) | 8-bit | S9 doc/tech/ecs.html |
| $00F0-$00FF | ECS PSG (AY-3-8917) | 8-bit | IN; wiki Entertainment_Computer_System |
| $0100-$01EF | Scratchpad RAM | 8-bit, 240 B | MAME intv.cpp:281 |
| $01F0-$01FF | PSG; $01FE right controller, $01FF left | 8-bit | MAME intv.cpp:282; wiki Memory_Map:7 |
| $0200-$035F | System RAM (BACKTAB is the first 240 words) | 16-bit, 352 words | MAME intv.cpp:283, intv.h:93 |
| $0360-$03FF | RAM-9600A "garbage" (wiki: "Intellivision II only?") **(review)** | | wiki Memory_Map:23 |
| $0400-$04FF | **(review, was missing)** cart on Model 2609 (MAME maps `read_rom04`); extra EXEC ROM on Intellivision II only | | MAME intv.cpp:284; wiki Memory_Map:24, 53 |
| $0500-$0FFF | **(review, was missing)** cart-safe, except $0700-$0CFF, where the Intellivoice maps its peripheral expansion bus | | wiki Memory_Map:54-56; S9 intellicart.txt:91-92 |
| $1000-$1FFF | EXEC ROM | 10-bit | MAME intv.cpp:285 |
| $2000-$2FFF | cart, or ECS ROM | | MAME ecs.cpp:114 |
| $3000-$37FF | GROM | 8-bit | SM p.53; S2 p.468 |
| $3800-$39FF | GRAM; aliases up to $3FFF (read/write); write-only aliases at $7800-$7FFF, $B800-$BFFF, $F800-$FFFF **(review: exact ranges)** | 8-bit | SM p.53; MAME intv.cpp:288-289; wiki Memory_Map:25-45 |
| $4000-$47FF | cart, or ECS RAM (2 KiB) | 8-bit | MAME ecs.cpp:56; wiki Memory_Map:58 |
| $4800-$6FFF | cart (EXEC checks $4800, header at $5000) | | wiki; L-WIKI |
| $7000-$7FFF | cart, or ECS ROM | | MAME ecs.cpp:115; wiki Memory_Map:63-65 |
| $8000-$DFFF | cart. **(review)** JLP, when enabled: flash save-game registers $8023-$802F, 16-bit RAM $8040-$9F7F (8,000 words), multiply/divide $9F80-$9F8F, extended registers $9F90-$9F97, CRC-16 $9FFC/$9FFD, random $9FFE | 16-bit | S9 src/jlp/jlp.c header lines 6-19 (spec only) |
| $E000-$EFFF | cart, or ECS ROM | | MAME ecs.cpp:116; wiki Memory_Map:71 |
| $F000-$FFFF | cart (WSMLB paged ROM) | | MAME ecs.cpp:200-245 |

GROM has three decode modes: CPU mode after SR1, STIC mode after BUSAK, and a 512-word window after BAR+DWS [from SM p.53]. The GRAM aliases follow from the third mode [from S2 p.468]. MAME maps only $3A00-$3BFF as an alias; the wiki pages disagree with each other [from L-WIKI]. The core decodes as the GROM chip does and tests the aliases with our own test ROM (section 8).

**(review)** Unmapped reads return $FFFF (section 2.5). The STIC aliases at $4000/$8000/$C000 are write-only, except $4021/$8021/$C021, where a *read* during VBlank period 1 still switches the STIC to colour-stack mode [from wiki Memory_Map:19, 29, 35, 41]. So a cartridge ROM read at $x021 must also reach the STIC mode latch. The same applies to cart ROM at $x800-$xFFF in the GRAM write-alias ranges: reads go to the cart, writes also reach GRAM.

---

## 3 Module list

Sizes are ALMs on the 5CEBA4 (18,480 ALMs, 308 M10K) [from L-PSS]. All sizes are [estimated] unless marked.

| # | Module | Function | Interfaces | State to save | References | Size | Test approach |
|---|---|---|---|---|---|---|---|
| 1 | `core_top` / APF glue | Pocket template, bridge, slots | APF bus, video, audio, controllers | none | 7800 core_top.v, core_bridge_cmd.v:431-478 | 500-700 | builds and boots on Pocket |
| 2 | `clocks`, `timing` | PLL, clock enables, reset, region | PLL; enables out | frame/line/cycle counters | section 2.3 | 100 (+580-650 if runtime PAL retune) | sim counts 228 x 262 per frame |
| 3 | `cp1610` | CPU: 8 registers, flags, all opcodes, SDBD, interrupts, bus phases | CPU bus; INTRM, BUSRQ, BUSAK, MSYNC | R0-R7, S/Z/O/C, I, D (SDBD), interruptible latch, pending INTRM/BUSRQ, microcycle position | S1; S2 p.441-446; wiki opcode pages; MAME cp1610.cpp (cross-check) | 900-1,500 | lockstep with Python model; own opcode test ROM; MAME trace compare |
| 4 | `bus_fabric` | address decode, Bus Copy mode, GROM decode mode, $01xx upper-byte zero | CPU bus; graphics bus | Bus Copy flag, GROM mode, latched addresses | SM p.50-53, p.58 | 150-300 | alias test ROM; sim |
| 5 | `sysram` | 352 x 16 RAM plus 20 x 14-bit row buffer and address counter | CPU bus; graphics bus | RAM, row buffer, pointer | SM p.50-51; MAME intv.h:93 | 1 M10K + 100 | sim |
| 6 | `stic` | registers $00-$32, colour stack / FGBG / squares, 8 MOBs, collisions, border, delays, SR1/SR2/SR3 | graphics bus; colour out; INTRM; BUSRQ | all 51 registers, mode, display-enable latch, colour-stack index, collision latches, MOB line state | SM p.54; S2 p.461-464; wiki STIC pages; MAME stic.cpp:416-445 | 1,800-3,000 | frame CRCs vs MAME; own STIC test ROM |
| 7 | `colour` | AY-3-8915 model: 16 colours to RGB | 4-bit + blank in, RGB out | none | SM p.60-61; S2 p.476 | LUT | compare with owner capture |
| 8 | ROMs and RAMs | EXEC 4K x 10, GROM 2K x 8, GRAM 512 x 8, scratchpad 256 x 8 | CPU bus, graphics bus | GRAM, scratchpad (ROMs not saved) | section 2.6 | about 8 M10K | readback after load |
| 9 | `psg8914` (x2) | 3 tones, noise, envelope, 2 input ports (ECS: bidirectional). **(review)** The AY-3-8914 volume registers have *two* envelope-select bits (00 fixed, 01 envelope >> 2, 10 envelope >> 1, 11 full envelope); the ECS AY-3-8917 and later AY-3-8916 have one bit, like the AY-3-8912. Build the variant as a parameter. Register order differs from the 8912 ($01F0-$01FF table) | CPU bus; ports; audio out | 14 registers, tone/noise/envelope counters, LFSR, envelope phase, output flip-flops | S4 p.7-100 to 7-105; S2 p.299-306; MAME ay8910.cpp:1533 | 250-400 each | register-write logs vs MAME; owner noise recording |
| 10 | `input` | virtual hand controllers from Pocket inputs; ECS keyboard matrix | cont1-4, keyboard; PSG ports | none | IN; MAME handctrl.cpp:124-135 | 300-500 | unit sim per mode; hand test |
| 11 | `cart` | page table, Intellicart bank registers, ECS-style paging, cart RAM 8/16-bit | CPU bus; SRAM | bank registers, page selects; RAM pages in SRAM | L-TA; S9 id_tag.txt, as1600.txt | 300-600 **(build step 8: 552 with `intv_pagesel` 49; map table in block RAM)** | all 188 images mapped in sim (CRC of mapped space) |
| 12 | `cart_loader` | CRC32 of the image, map table lookup, CFG parser, .ROM parser | APF data_loader; SRAM; page table | none (load time) | sections 5.2-5.4 | 400-800 **(build step 8: 1,993 with `intv_cfgparse` 507 and `intv_romparse` 210; section 4.5)** | Python reference for each format |
| 13 | `ecs` | ECS ROM (12K x 10, paged), 2 KiB RAM, PSG #2, ports 3/4, keyboards | CPU bus | page registers, RAM, PSG #2 state | MAME ecs.cpp; wiki ECS; AA | 200-400 + PSG | ECS BASIC boots; keyboard tests |
| 14 | `ivoice` | SPB640 FIFO (**(review)** 64 decles of 10 bits; writes when full are dropped [from MAME sp0256.cpp:1235-1242]) and SP0256 (microsequencer, 12-pole LPC filter) | CPU bus $0080-$0081; audio | FIFO, PC, stack, mode, page, coefficients, filter delay line, repeat and pitch counters, LRQ/SBY | S6 sheets 18-22; S7; S8; MAME sp0256.cpp | 500-1,000 + 1-2 DSP | per-opcode tests; resident phrases vs MAME audio |
| 15 | `jlp` | RAM, multiply/divide, CRC, random numbers, flash | CPU bus; SRAM; flash slot | registers; RAM in SRAM | S9 jlp.c header (spec only); JLP Developer's Guide wanted | 300-600 | homebrew that uses JLP |
| 16 | `ss_ctl` | save/load protocol, freeze, state bus | APF bridge; all `ss` ports | none | section 4 | 450-850 (all taps) **(build step 7: measured 749 for the controller and about 2,470 with all taps; section 4.5)** | round-trip test (section 8) |
| 17 | `audio_out` | mix, filter, 48 kHz I2S | PSGs, speech | none (filters) | agg23 sound_i2s.sv (MIT) | 200 | sim spectrum; listen |
| 18 | `osd_keypad` (later) | on-screen 3 x 4 keypad, overlay slot | video path; input | none | IN | 300-600 | hand test |

**Total** about 7,000-11,500 ALMs (38-62 %) and 50-70 M10K [from L-PSS]. For scale: the 7800 core 2.2.4 uses 14,639 ALMs and 216 M10K [from L-PSS]. Fit is not expected to be a problem.

---

## 4 Save-state architecture

### 4.1 Pocket protocol

| Command | Meaning | Source |
|---|---|---|
| 0x00A0 | save state: bit 0 of the parameter starts; without it, a query. Reply gives supported, blob address, size | APF host-target-commands; 7800 core_bridge_cmd.v:402-423 |
| 0x00A4 | load state: same; reply gives maximum load size | APF host-target-commands |
| 0x00B0 | menu opened / closed | APF host-target-commands |
| Result codes | **(review)** 0 = nothing in progress (idle), 1 busy, 2 ok (done), 3 error. Code 0 is *not* "ok"; the core must hold `ok` high until the next start so the host can read 2 | 7800 core_bridge_cmd.v:408-411, 430-433 (template comments: "assert continuously when done, and clear when new process is started", lines 65-69) |
| `sleep_supported` | in core.json; sleep reuses 00A0/00A4 | APF core-json |

The template's `core_bridge_cmd.v` already decodes all three commands. The 7800 ties them off [from 7800 core_bridge_cmd.v:431-478, core_top.v:515-530].

Behaviour seen in agg23's cores (not in the docs) [from L-PSS: AGG NES core_top.v:390-394, Tamagotchi core_top.sv:428-431, save_state_controller.sv]:

- On load, the Pocket writes the blob over the bridge **before** it sends 0x00A4. Loading starts on the first write.
- On save, the core raises `ok` when the first word is ready. Then it gives one word per new bridge read address. Repeated reads of one address must return the same word.
- Both put the blob at bridge address 0x40000000. The 7800 uses 0x40000000 for FA2 flash [from 7800 data.json], so this core picks its own free address (proposed 0x50000000) [estimated].

**(build step 7)** As built: `intv_ss_ctl.sv`, the blob at 0x50000000, and every detail of the protocol, the freeze, the checks on load and the bench in docs/SAVESTATE.md. The bridge's reads are one word behind (Analogue's `io_bridge_peripheral.v`), so the core holds each read's word until the next read, as the template's command registers do; it serves any read or write order.

### 4.2 Freezing the machine

1. On 0x00A0 or 0x00B0 (menu open), `ss_ctl` asks for a freeze.
2. The freeze waits for a quiet point: the CPU at an interruptible instruction boundary, and the frame counter inside VBlank before the first row fetch (NTSC cycles 0 to about 3,790 of 14,934) [from L-PSS; MAME stic.h:50].
3. Then one clock enable stops the whole machine. Nothing is half-done on the bus.
4. If no quiet point comes within 3 frames, reply "error" [estimated].
5. **(build step 7)** A load asked for while the host holds the core in reset (a wake whose load comes before the reset exit) is checked at once and staged; it is applied at the first quiet point after the reset exit (docs/SAVESTATE.md 1).

Because the freeze always lands in the same frame phase, the STIC row buffer and the BUSRQ machinery are idle. This makes the saved state smaller and the restore simpler. The STIC registers and the row buffer are still saved, so a later change of freeze point stays possible.

### 4.3 How each module exposes state

- Each module has one `ss` port: `ss_addr` (module id + word index), `ss_wdata`, `ss_we`, `ss_rdata`. All ports are OR-combined into one 32-bit state bus, as in agg23's Tamagotchi core (MIT) [from L-PSS: `rtl/savestates/ss_addresses.sv`, `bus_connector`].
- Restore works as a reset with loaded values: while `ss_load` is high, every register takes its value from the state bus [from L-PSS: Tamagotchi `rtl/stopwatch.sv:54-56`]. **(build step 3)** As built, the machine is frozen (clock enable stopped, section 2.5) and each state word is written on its own (`ss_we` with `ss_addr`); a write beats the clock enable, and machine reset beats a write.
- ~~Block RAMs are read and written through their second port. They cost no logic.~~ **(build step 3)** Block RAMs (scratchpad, System RAM, GRAM: `intv_ram.sv`) are read and written through their bus-side port A: `ss_en`, high only while the machine is frozen, hands that port from the CPU bus to the state port (one clock of read latency) and must drop two clocks before the machine runs again. Port B stays free for the STIC's reads (build step 4). The switch costs a few multiplexers per RAM, no RAM. **(build step 4)** Port B is read only and belongs to the STIC (System RAM rows, GRAM patterns); the STIC's row buffer (20 words, id $0C) and line buffer (64 words, id $0D) are `intv_ram`s too, and GROM has a second read port for it. Every port-B word is used only after its address has been stable for a clock, so a freeze may land in any clk_sys (docs/STIC_NOTES.md 4).
- The freeze must wait until no cartridge access is in flight: `intv_bus` asks the cartridge port the clock after each address latch and holds the answer in its state, but the request and the SRAM read take about 6 clk_sys and are not in the state. The quiet point of section 4.2 (an instruction boundary) has none in flight; a freeze anywhere else must wait at least 16 clk_sys after the last CPU microcycle before reading state (the step-3 bench does this).
- Cart RAM and JLP RAM live in SRAM. `ss_ctl` reads them directly while the machine is frozen.
- One package file lists every module id and word count. A Python script checks that the RTL package and the blob layout agree. **(build step 7)** `tools/savestate.py` holds the ids, counts and layout and generates `intv_ss_pkg.sv` and the table in docs/SAVESTATE.md; `gen --check` fails if either, or a module's id default, differs.
- **Rule:** a module is not finished until its `ss` port covers every flip-flop that changes at run time, or the flip-flop is listed in docs/SAVESTATE.md 5 as quiescent at the quiet point (section 4.2), with the reason it holds nothing the machine needs again there. The round-trip test (section 8.4) enforces this. **(build step 7)** Amended after the step-7 review: the cartridge port's per-access registers (intv_bus, intv_cart) and the block RAMs' read registers are such flip-flops; a change of the freeze point must re-check that list.

### 4.4 Blob layout (fixed size)

| Part | Bytes | Source of the figure |
|---|---|---|
| Header: magic, version, region, cart CRC32, flags, part table | 64 | [estimated] |
| Timing counters | 32 | [estimated] |
| CP1610 | 32 | MAME cp1610.cpp:3341-3349 (save items) |
| Bus fabric | 16 | [estimated] |
| STIC registers (0x33 x 16-bit) and internal state | 512 | MAME stic.h:91; stic.cpp:416-445 |
| GRAM | 512 | SM p.19 |
| Scratchpad | 256 | MAME intv.h:95 |
| System RAM 352 x 16 + row buffer | 768 | MAME intv.h:93 |
| PSG #1, PSG #2 | 128 | [estimated] |
| ECS page registers, ECS RAM | 2,048 + 64 | MAME ecs.cpp:56 |
| Intellivoice (FIFO + SP0256) | 512 | MAME sp0256.cpp:116-144 |
| Cart and JLP registers | 128 | [estimated] |
| JLP RAM | 16,384 | L-PSS |
| Cart RAM window (all 64K words of the cart plane, RAM pages only written back) | 131,072 | L-PSS |
| **Total, padded** | **153,600 (0x25800, 150 KiB)** | L-PSS |

The header holds the cart CRC32. A load with the wrong cartridge is refused with code 3. **(build step 8)** Version 2: the header also holds the CFG's CRC32; the cartridge module holds the page selects and the Intellicart bank registers, not the map table (docs/SAVESTATE.md 3, CARTFORMATS.md 5). **(build step 7)** Version 1 of the blob keeps the fixed 153,600 bytes but uses only what the core has so far: a 64-byte header (with the payload CRC32 and the EXEC's and GROM's CRC32s too, so that a state made with other system ROMs is refused), the 1,324 module words, and the 16K cells of the SRAM's cart RAM area; the rest is zero and reserved for the ECS, the Intellivoice and JLP (docs/SAVESTATE.md 3). The input module, audio filters and all ROMs are not saved. Inputs are re-sampled after a restore [from L-PSS].

### 4.5 Expected cost

The NES study measured about 570 ALMs for its save-state engine, controller and 22 register taps [measured, from L-PSS: fitstudy/nes/reports/pr1_parity]. The SNES study measured +4,754 ALUTs for state muxes added after the fact [from L-PSS]. Designing the taps in from the start is what keeps this core near the NES figure: 450-850 ALMs [estimated].

**(build step 7) Measured** (seed-1 fits, 0.0.5 against 0.0.6 with the step-7 review fixes; ALMs per module from the fit report's entity table): the save states cost about 2,470 ALMs (4,020 -> 6,488, 22 % -> 35 % of the device), three times the estimate. Most of it is not the controller but the state read-back of flip-flop state, which the earlier fits pruned because core_top tied the state ports off:

| Module | 0.0.5 | 0.0.6 | Cost | What it is |
|---|---|---|---|---|
| `intv_ss_ctl` | - | 749 | 749 | the controller: command handshakes, freeze, the blob's CRC32 and header checks, bridge crossings, SRAM sequencing |
| `intv_stic` | 1,160 | 1,827 | 667 | 67 state words of flip-flops (registers, row fetch, card engine, MOB sweep) through a 32-bit read multiplexer and the restore writes: about 10 ALMs a word |
| `intv_cart` | 276 | 800 | 524 | the 32 x 16 page table in flip-flops (read by the bus combinationally, so a block RAM would add a clock to every cartridge access) and its state read and write: about 25 ALMs a word |
| `cp1610` | 621 | 769 | 148 | 8 state words (R0-R7 are 16 bits; sequence state, flags, request lines) |
| `intv_psg` | 330 | 417 | 87 | 21 narrow state words: about 4 ALMs a word |
| `intv_core` (own logic) | - | about 186 | 186 | the OR of the state buses, the EXEC and GROM CRC32s, the sound decay |
| block RAMs (`intv_ram` x 5) | 0 | 52 | 52 | port A handed to the state port while frozen (`ss_en`) |
| `core_bridge_cmd` | 181 | 227 | 46 | the save, load and menu commands no longer tied off |
| others (`intv_bus`, `intv_timing`, `intv_media`, loader, input) | | | about 40 | |

The rule of thumb for later steps: state kept in block RAM or SRAM costs almost nothing (a port multiplexer); state in flip-flops costs about 4 ALMs per 8-16-bit word and 10-25 per 32-bit or table word.

**(build step 8) Measured** (seed 1, 0.0.7 against 0.0.8): 6,449 -> 7,913 ALMs (+1,464; 43 % of the device), 26 -> 50 RAM blocks. `intv_cart` fell from about 800 to 552 (with `intv_pagesel` 49): the page table became a 4,096 x 38 map table in block RAM (24 M10K with the loader's range list, assembly list and covered-block bits; 16 of the 38 bits are the trim the step-8 review added, section 5.3), as the step-7 note proposed, at 2-3 clk_sys more per cartridge access. The loader grew to 1,993 (`intv_cfgparse` 507, `intv_romparse` 210, the table builder with the review's page rules and trims, the copy and clear passes, the CFG's CRC32): load-time logic only, about twice section 3's 400-800 for module 12. It could be trimmed (one CRC32 engine for both slots, a narrower range compare) if a later step runs short; the budget below still fits.

Budget for steps 9-11, updated from these figures [estimated]: ECS (step 9) state taps about 150 ALMs (PSG #2 as PSG #1, 87; page selects and ports about 40; ECS RAM in block RAM through `ss_en`, about 10); Intellivoice (step 10) about 300-450 if the SP0256's filter coefficients and delay line stay in flip-flops (about 30 words), about 60 if they are kept in a block RAM (the plan); JLP (step 11) about 150 for its registers (its RAM is in SRAM, which `ss_ctl` reads directly). With the modules themselves (section 3: ECS 200-400 plus PSG #2 about 420, Intellivoice 500-1,000, JLP 300-600) the core would end at about 8,300-10,100 ALMs (45-55 %), inside section 3's 7,000-11,500. **(build step 8)** From 0.0.8's 7,913 the same additions give about 9,450-10,650 (51-58 %), still inside it. If it ever runs short, moving `intv_cart`'s page table into a block RAM saves about 450 ALMs, at the cost of a clock on every cartridge access and a re-run of the bus and screen gates; it was considered in step 7 and not done, because it is not needed and is not a small change to the cartridge port's timing. **(build step 8)** Done in step 8 (above), as a 4,096-entry map table for the new formats.

---

## 5 Cartridges and loading

### 5.1 Where ROM lives

| Contents | Place | Why | Source |
|---|---|---|---|
| EXEC (4,096 words, 10 bits used) | M10K, 1K x 10 mode | fits exactly | [measured] L-PSS |
| GROM (2 KiB) | M10K | graphics bus needs it every row | |
| SP0256-012 (2 KiB) | M10K | | MAME voice.cpp:87 |
| ECS ROM (12,288 words, 10 bits used) | SRAM plane 2, or 12 M10K | M10K is plentiful; choose at fit time | [measured] L-PSS |
| Cartridge ROM and RAM | Pocket SRAM, 128K x 16, 55 ns | one CPU bus cycle is 1.12 us, so no contention problem; avoids SDRAM and its GPL-3 controller | apf_top.v:173-176; L-PSS |
| Large page-flipped homebrew | PSRAM | only if a title needs more than SRAM | L-PSS |

SRAM layout [estimated]: plane 1 (64K words) is the cartridge address space as loaded. Plane 2 holds the staging copy of a raw image, JLP RAM and paged ROM banks.

The largest image in the owner's library is 48 KiB [measured, L-PSS]. Twelve images need full 16-bit words, seven of them prototypes, so cartridge ROM is never masked to 10 bits [measured, L-TA].

### 5.2 Raw `.int` / `.bin` with CRC auto-map

A raw image is the ROM segments joined end to end as big-endian 16-bit words, with no addresses [measured, L-TA]. The map must come from a table.

1. The loader writes the file to SRAM at file offsets and computes CRC32 while it streams.
2. After the last byte, the CRC is looked up in a ROM table (about 200 entries x 8 bytes; **(review)** that is 12,800 bits, so two M10K, not one [measured: review_checks.py]).
3. The table entry gives a layout id and flags: ECS, Intellivoice, cart RAM, paged, JLP, "ECS must stay off".
4. The layout fills the page table. Page table entries point at file offsets, so nothing is copied.

**Where the table comes from.** Our own Python script builds it from:

- MAME `hash/intv.xml` and `intvecs.xml` (CC0-1.0, verified). These carry per-segment CRCs with load addresses [from L-DSL].
- The region-CRC proofs in `research/test-assets/rom_classes.csv`: 162 of the owner's 188 images have proven layouts [measured, L-TA].
- jzIntv `name_list.c` (public domain, verified) for the ECS and Voice flags only. It has no memory maps [from L-DSL].

Correction to the owner's project list (PJ): the PD and CC0 CRC lists do not give memory maps on their own; `intv.xml` does [from L-DSL]. Prefer the region proofs over `intv.hsi`, which gives wrong segment counts for Scooby Doo and Thin Ice (Beta) [from L-TA].

**Layout families in the owner's library** [measured, L-TA]:

| Family | Images |
|---|---|
| 8K words at $5000 | 57 |
| 4K words at $5000 | 54 |
| Multi-segment | 39 |
| Not in MAME's lists | 26 |
| Imagic, 8K at $4800 | 4 |
| 12K at $5000-$7FFF | 4 |
| Other | 4 |

**Unknown CRC.** Fall back to our own rule, written from the wiki's cartridge-safe ranges and the Cart.mac 16K and 42K maps [from wiki Memory_Map, Cart.mac]. Not from jzIntv's heuristics. The menu shows "unknown cartridge, default map" and the user can supply a `.cfg`.

### 5.3 BIN + CFG

- A second, optional data slot takes the `.cfg` file.
- The CFG text goes to a small buffer. A small RTL parser reads the `[mapping]`, `[memattr]` and `[vars]` sections [from L-DSL: S9 doc/utilities/as1600.txt, src/bincfg/bincfg.h, as specification].
- **(review)** Also needed: `[preload]` and `[bankswitch]`, which bincfg lists with `[mapping]` and `[memattr]` as the sections that configure the memory map, and `[macro]`, which some CFGs use to poke (patch) ROM words [from S9 src/bincfg/bincfg.h:13-29]. Span attributes include R, W, narrow (8-bit), Intellicart-bankswitched, ECS-style PAGE, and poke [from bincfg.h:43-50]. `[vars]` that change hardware: `ecs`/`ecs_compat`, `voice`/`voice_compat`, `intv2`, `kc_compat`, `tv_compat`, `lto_mapper`, `jlp`/`jlp_accel`, `jlp_flash` [from S9 as1600.txt:1040-1051]. `[keys]`/`[joystick]` and metadata can be skipped.
- **(review)** A `.bin` may be up to 1 MiB (`BC_MAXBIN`) [from S9 bincfg.h:34-38]; anything over the 128K-word SRAM needs the PSRAM path (section 5.1).
- Unknown sections are skipped.
- A CFG wins over the CRC table.
- **(build step 8)** As built (`intv_cfgparse.sv`, `intv_loader.sv`; model `tools/mapper/cartfmt.py`; docs/CARTFORMATS.md 2): `[mapping]`, `[preload]`, `[memattr]` (RAM/WOM/ROM, 8/16), `[bankswitch]` and `[vars]` (`ecs`, `ecs_compat`, `voice`, `voice_compat`, `jlp`, `jlp_accel`; `lto_mapper` refused), word exact through a 4,096-entry map table of 256-word blocks (whole blocks point into the file, partial or shared ones are assembled at load into a pool, RAM gets the cart RAM area; each block keeps the first and last word its ranges declare, so a few words of `[memattr]` RAM do not make the whole block answer); in a paged 4K range the lines without `PAGE` count on every page, as in jzIntv (run as a black box: CARTFORMATS 2.4 lists where we differ on purpose); `[macro]` has no specification in the jzIntv documents and is skipped. A CFG with no map lines adds its flags to the CRC table's map. Malformed CFGs are refused with a code (CARTFORMATS 2.3). The 1 MiB `.bin` is not supported: the image is at most 64K words (SRAM plane 1), as in step 2.

### 5.4 Intellicart `.rom`

- Header byte 0xA8, segment count and its complement, then segments (page range, data, CRC-16), then the 50-byte enable tables [from L-DSL: S9 doc/rom_fmt/id_tag.txt].
- The parser writes each segment to plane 1 at its address while it streams.
- The tables fill the page table's readable/writable bits.
- Intellicart bank registers are write-only at $0040-$005F; `addr = (a & $7FF) + (v << 8)` [from L-WIKI]. They are saved.
- **(build step 8)** As built (`intv_romparse.sv`; docs/CARTFORMATS.md 3): segments to plane 1 at their Intellicart addresses (unwritten blocks cleared), CRC-16s checked (poly $1021, init $FFFF, from the Intellicart manual), the access nibbles (R, W, B and jzIntv's N) trimmed by the fine table, the tags walked for the compat tag $06 (ECS / Intellivoice / JLP flags; LTO refused). The bank registers add (intellicart.txt and the Intellicart manual; `doc/historic/intellicart/banksw.txt` says XOR, superseded), start with each 2K window at its own address after a load (as jzIntv; the manual calls the start state undefined) and keep their values over a machine reset (the Intellicart does not see it). RAM windows move to the cart RAM area so the save state holds them; a bank window that writes, or more than 64 blocks of RAM windows, means no save states for that image.

### 5.5 Expansions

| Expansion | Enable | Notes | Source |
|---|---|---|---|
| ECS | menu Auto / On / Off; Auto uses the table flag | keep off for titles with ROM at $7000 or $E000 (Centipede, Dig Dug, IMI and MTE201 test carts, and others) | L-TA; wiki Memory_Map |
| ECS paging | write $xA5y to $xFFF selects page y of the 4K block at $x000 | build the general 16 x 16 case; MAME has only pages 0-1 (its own TODO). **(build step 8)** `intv_pagesel.sv`: all 16 ranges, 16 pages each, for the cartridge's map table (any format) and, from step 9, the ECS's ROMs (`pg_sel`, `pg_rst`; docs/CARTFORMATS.md 4.1) | wiki; MAME ecs.cpp:8-14, 200-245 |
| Intellivoice | menu Auto / On / Off | six titles use it in the owner's library | L-TA |
| Cart RAM | from table or CFG | 8-bit cells in some carts (USCF Chess, Triple Challenge, Land Battle, Game Factory) | MAME slot.cpp:331-340, rom.h:52-53; L-TA |
| JLP | from CFG `[vars]` or table | RAM, accelerators, flash on its own nonvolatile slot. **(review)** `jlp_accel` 0-3: 1 = accelerators on at reset, no flash; 2 = accelerators *off* at reset with flash; 3 = on with flash. The accelerator on/off state is run-time state and goes in the save state. Flash size is per game, `jlp_flash` x 1.5 KiB sectors (default 4 when flash is enabled), so the flash slot size is not fixed | L-DSL; L-PSS; S9 as1600.txt:1124-1133; id_tag.txt:638-670 |
| LTO mapper **(review, was missing)** | CFG `lto_mapper` or .ROM tag flag LTOM | LTO Flash's own mapper. Not specified in the 2020 jzIntv docs; titles that need it will not run until it is documented (section 13) | S9 as1600.txt:1048; id_tag.txt:657 |

### 5.6 Data slots (proposed, `data.json`)

| id | Name | Files | Notes |
|---|---|---|---|
| 0x100 | Cartridge | .int .bin .rom .itv | required |
| 0x101 | Cartridge config | .cfg | optional; **(build step 8)** used with a raw image (ignored with a .rom), its length from the data table (docs/CARTFORMATS.md 1) |
| 0x102 | EXEC | exec.bin (8,192 bytes) | required |
| 0x103 | GROM | grom.bin (2,048 bytes) | required |
| 0x104 | ECS ROM | ecs.bin (24,576 bytes) | optional |
| 0x105 | Intellivoice ROM | ivoice.bin (2,048 bytes) | optional |
| 0x106 | JLP flash | .sav | nonvolatile |

File sizes are the owner's files [measured]. They match MAME's expected CRCs: EXEC cbce86f7, GROM 683a4158, Intellivoice 0de7579d, and the three ECS parts [from L-TA].

---

## 6 Video and audio on the Pocket

### 6.1 Video

- The STIC produces a 4-bit colour and a blank flag per pixel clock [from SM p.60-61].
- A 16-entry LUT turns it into RGB888. The Pocket pixel clock is master (3.579545 MHz NTSC), from the PLL /240 output, with a +90 deg copy [from L-PSS].
- Each line is 228 pixel clocks on NTSC (**(review)** about 256 on PAL [estimated], section 2.4). Each STIC row of 8 card pixels is shown as 2 lines [from MAME stic.h:37, Y_SCALE].
- Scaler modes [estimated, L-PSS]: NTSC 160 x 192 (playfield only, 10:7) and 167 x 210 (with border, 15:11); PAL 160 x 192 (20:13) and 168 x 208 (67:45). The slot index goes in rgb[23:13], as in the 7800 [from 7800 core_top.v:995]. The final crop is fixed after the STIC timing is in simulation.
- **(build step 4)** The STIC (`intv_stic.sv`) gives a colour for every pixel clock: the playfield from pixel clock 37 of lines 70-261 (the 160th column is border, as on the console), the border colour everywhere else. The step-1 windows of `pocket_video` stay: the playfield window shows the 159 card pixels plus that border column; the border window adds 3 pixels left, 4 right and 9 lines above and below (the 9 below are the next frame's lines 0-8). The test pattern shows while the machine is held (loading, a required slot missing). Picture semantics and framing against MAME's: docs/STIC_NOTES.md 4.

**Palette.**

- The AY-3-8915 table gives 16 colours as levels at four subcarrier phases. Blank = 3, sync = 0, white = 13, burst = 1 1 5 5 [from SM p.60-61; S2 p.476].
- Luma is reliable. The luma codes for colours 0-15 are 3 7 6 8 7 8 12 13 9 10 9 6 8 9 9 6, and all 16 pass a self-check with Grass Green +I = 6 [measured, L-DSL].
- Hue is not settled. Two independent decodes give hues about 30 deg off or worse against the expected colours [measured, `research/service-manual/palette_estimate.txt`; L-DSL].
- MAME's palette is BSD-3 and may be used with its notice [from PJ]. The FreeIntv palette is not used.

### 6.2 Audio

| Source | Rate | Treatment | Source |
|---|---|---|---|
| PSG #1 (3 channels tied together on the board) | master/2, tone divider /16 | sum, box filter to 48 kHz | SM Fig 7-2 (A/B/C tied); S4 p.7-101 |
| PSG #2 (ECS) | same | same | MAME ecs.cpp:101 |
| SP0256 | about 9.29 kHz (3.12 MHz / 336) **(review: was 10 kHz)** | upsample to 48 kHz | MAME sp0256.cpp:34; S8 gives only 5 kHz bandwidth |

- Output: 48 kHz I2S through agg23's MIT `sound_i2s.sv` [from L-PSS].
- Volume curve: the AY 16-level DAC curve from the datasheet, cross-checked with MAME's table [from S4; MAME ay8910.cpp].
- Speech level against the PSG is unknown (no Intellivoice schematic) [from L-PSS].
- **Noise LFSR:** use bit0 ^ bit3 (maximal, period 131,071), as MAME does for the AY-3-8910 and YM2149 [from MAME ay8910.h:263-272]. The wiki's formula is bit0 ^ bit2 with period 114,681, which is not maximal [measured, L-WIKI, L-DSL]. GI datasheets say only "pseudo random" [from S4 p.7-101; S2 p.302]. Nothing verifies the taps on the 8914 die itself. This stays a decision until there is a hardware recording (section 11).
- **(build step 6)** As built (`intv_psg.sv`, model `tools/psg.py`; facts, sources and the differences from MAME in docs/PSG_NOTES.md): the generators step once every 4 CPU cycles (master / 16), counted from the CPU's first cycle, and a write lands at the end of its DW cycle. The 48 kHz output is two one-pole low passes at the step rate (-3 dB near 16.5 kHz), the box filter and an exact 48 kHz phase accumulator; the DAC is MAME's AY-3-8910 curve for fixed and envelope volumes alike; no DC: silence is 0. Register logs equal MAME's for eight games, and with MAME's tone counter and step grid every PSG step equals MAME's own stream; the core's tone counter restarts at 0 when a smaller period is written, as MAME's notes describe the chip, where MAME keeps the remainder (PSG_NOTES P1).

---

## 7 Input (summary of INPUT_NOTES.md)

### 7.1 Hardware facts

- Disc (16 directions), 12 keys (1-9, Clear, 0, Enter), 3 distinct side actions (the two top buttons are wired together) [from IN].
- Right controller on PSG port A ($01FE), left on port B ($01FF). Lines are active-low [from SM; MAME intv.cpp:471-472].
- **(review)** The Master Component's AY-3-8914 I/O ports are reported to be input-only ("modified at some point", per David Chandler's documentation as quoted in AA); the ECS AY-3-8917 ports are bidirectional [from AA; wiki Entertainment_Computer_System]. The core should ignore the R7 port-direction bits on PSG #1.
- **(review, was missing)** ECS hand controllers 3 and 4 plug into the ECS and are read through the ECS PSG: one on port A ($00FE), one on port B ($00FF) [from MAME devices/bus/intv_ctrl/ecs_ctrl.cpp:149-157]. These are the same lines the ECS keyboard scans (rows on $00FE, columns on $00FF), so a game that sets $00F8 bit 6 to drive port A sees controller 3's pulled-low bits mixed into the matrix. The input module must merge controllers 3/4 into the ECS matrix model, not replace it. Known user: World Cup Soccer (four players with ECS) [from S9 doc/tech/ecs.html].
- Codes (bits pulled low) [from MAME handctrl.cpp:124-135; wiki, all agree]:

| Input | Codes |
|---|---|
| Keys 1-9 | $81 $41 $21 $82 $42 $22 $84 $44 $24 |
| Clear, 0, Enter | $88 $48 $28 |
| Side: top, lower left, lower right | $A0 $60 $C0 |
| Disc N, clockwise | $04 $14 $16 $06 $02 $12 $13 $03 $01 $11 $19 $09 $08 $18 $1C $0C |

- Several presses merge by OR of these bits. Some games rely on it (Pinball uses keys as flippers together with the disc), so the core merges, it does not pick one [from IN; L-TA].

### 7.2 Mapping on the Pocket

One input module builds a virtual hand controller per player. Every source feeds it. It holds no machine state, so it is outside the save state [from IN].

| Mode | Layout | Source |
|---|---|---|
| Layer (default) | D-pad = disc (16 directions from an analog stick when docked); L + D-pad = the 8 in-between disc directions (each D-pad direction turned 22.5 degrees clockwise); A/B/X = side actions; R + A/B/X = 1/2/3, R + Y = Enter; R + D-pad = ring keys by position; L + A/B/X = 5/Clear/0 | IN |
| Face-button ring | D-pad = disc; X=2, B=8, Y=4, A=6, pairs for diagonals; L = side action, R = 5 (TRON Deadly Discs; also AD&D) | IN; L-TA |
| Right stick | docked analog: right stick picks the ring key | IN |
| Swap controllers | menu item | IN |
| USB keyboard (slot 3) | number keys = keypad, Backspace = Clear, Enter = Enter; ECS keys one to one; music keyboard on Z-M and Q-I rows | IN; APF bus-communication doc |
| Later: on-screen keypad | Select opens a 3 x 4 grid drawn in the video path; optional user-supplied overlay scan in its own slot | IN |

Check `cont3_key[31:28] == 4` before reading the keyboard [from L-PSS, APF docs]. Per-game profiles (for example B-17 Bomber, Space Spartans) come from our own CRC-keyed table with function facts only, no artwork [from IN].

**(build step 6) As built** (`src/fpga/core/intv_input.sv`, model `tools/intv_input.py`, bench `sim/tb/tb_input.py`):

- Player 1 = cont1, player 2 = cont2; a slot counts only with type 1 (Pocket), 2 (docked digital) or 3 (docked analog), and the sticks only on type 3. Player 1 is the **left** controller ($01FF, port B) and player 2 the right ($01FE, port A), because many games read only the left one; the Swap Controllers item (0x1000020C) exchanges them. The USB keyboard (cont3 type 4, six usage codes in `cont3_joy` and `cont3_trig`) is player 1's keypad: 1-9 and 0 on the number row and the numpad, Backspace = Clear, Enter and numpad Enter = Enter. ECS keys and the music rows come with step 9.
- Keypad Mode item (0x10000208): 0 Layer (default), 1 Face-button ring, 2 Right stick; 3 works as Layer. Details beyond the table: R beats L when both are held; R releases the D-pad's disc (the D-pad is the ring), L does not; Y alone, L + Y, Start, Select, L2/R2/L3 press nothing yet (Select is kept for the on-screen keypad); Face-button ring's L is the top side action. Right stick mode is Layer plus the right stick (8 sectors) and R3 = 5, the ring's centre (R3 is this core's addition).
- **L + D-pad (0.0.7; the owner's Precision controls, IN 2026-10-26):** in the Layer modes (0, 2, 3) L turns the D-pad's disc one notch (1/16 turn, 22.5 degrees) clockwise: the D-pad alone gives N, NE, E, SE, S, SW, W, NW, L + D-pad NNE, ENE, ESE, SSE, SSW, WSW, WNW, NNW, so all 16 disc directions are reachable on the Pocket. The L chords work at the same time (L + up + A = disc NNE and key 5). R still beats L (R + L + D-pad = the ring key, not turned). In Face-button ring L stays the top side action and does not turn the D-pad (a game in that mode may need the side action while moving; turning there would change the direction whenever it fires). The analog left stick is never turned (16 directions already). PGA Golf's aim (research/golf/NOTES.md: the disc sets RAM $015F to one of 16 directions, the EXEC ignores presses under 6 frames) is the play bench's check: from the recorded start, Right, L + Right, Up, L + Up (Pocket buttons through the input model) give $015F = 0, 15, 4, 3, with the RTL equal to the model frame by frame.
- Opposite directions together (D-pad up + down, X + B in the ring) cancel. Everything else is wired-OR: each input pulls its code's lines low, so presses combine as on the hardware, the stick's disc with the D-pad's too.
- Merged with the PSG (branch step6): the module's bytes are intv_machine's `pad_r` / `pad_l`, which the PSG's ports $01FE / $01FF read. The play bench (`sim/tb/tb_system.py --play`; PGA Golf added in 0.0.7, above) starts Astrosmash and B-17 Bomber with a key press and runs them 20-22 s from power-on with scripted keys (keypad, side buttons, disc): the RTL equals the model (mode `stic`) in every picture, bus phase and PSG step, and the model (mode `mame`) equals MAME, given the same keys at the same frames, in every 10th frame's snapshot and the whole PSG register log (MAME's own BUSRQ timing differs from the core's, STIC_NOTES T2, so MAME is compared with mode `mame`).
- Analog left stick: 16 directions by integer slopes (sector boundaries at 11.25 + 22.5 n degrees), dead zone radius 40 of 128; right stick: 8 sectors, dead zone 64. Stick y is taken as growing downwards (to be confirmed on a docked analog controller). At the centres of MAME's 5 x 5 analog grid the disc equals MAME's table (handctrl.cpp:137-144).
- The controller words and the Keypad Mode / Swap settings (all clk_74a) cross into clk_sys as one word with a toggle handshake: a clk_74a copy of all of them, a request flag through two clk_sys flip-flops, the whole copy loaded at once, an acknowledge back through two clk_74a flip-flops before the next copy (0.0.5; the step-6 review: a bit-by-bit crossing could show, for one clk_sys cycle, a press nobody made). About 220 ns of latency; `core_constraints.sdc` bounds the copy's and the request's paths with set_net_delay (10 ns; its comment says why set_max_skew and set_max_delay are not used), and `sim/check/fit_crossing_check.py` checks the fit's net delays and that each flag crosses through two flip-flops. `tb_input` checks the handshake rule and the crossing with skewed inputs and a skewed copy (sim/tb/README). The module keeps no machine state and has no state port (4.4).
- Interact menu limits learned on the owner's Pocket (2026-10-25, openFPGA-2600): at most 15 options a list (the documents say 16), and interact.json at most 8,740 bytes (10,213 failed), kept minified; `sim/check/apf_json_check.py` enforces both.

### 7.3 ECS keyboard matrix model

- ECS PSG at $00F0-$00FF. Port $FE = rows, $FF = columns. Register $F8 bits 6/7 set each port's direction. Each port is all-input or all-output, with pull-ups [from IN; AA].
- **Alphanumeric keyboard** (no diodes): build the connected groups of row and column lines through the pressed switches. A group reads 1 if any driven line in it is 1; else 0 if any is driven 0; else 1 (pull-up). One rule gives ghosting and the "two keys in a column vanish" masking, for both scan directions [from IN; AA].
- **Synthesizer keyboard** (49 keys, with diodes): a directional model, no ghosting [from IN].
- Limit: USB HID gives 6 keys at once plus modifiers. Whether any ECS music title needs more is unchecked [from IN].

Implementation [estimated]: 8 x 8 switch matrix, group closure computed combinationally per read (at most 8 iterations of row/column propagation). Small.

---

## 8 Verification plan

No simulation runs until sim slots are free. This section is the plan.

### 8.1 References used as black boxes

| Reference | Use | Limits | Source |
|---|---|---|---|
| MAME intv (BSD-3) | instruction traces, mapper behaviour, PSG register logs, speech, title-screen frames | the owner's build is Atari-only and has no intv driver; needs a separate intv-only build. VBlank "not accurate"; NTSC only; simplified ECS paging | L-TA; MAME intv.cpp:445-457; mame.lst:26792-26798 |
| jzIntv | traces, frames, audio, PAL | run as a program only; its source is not read for code; outputs treated like game data (only hashes committed) | L-TA |
| Python CP1610 model (ours) | golden model for the RTL CPU in lockstep, with bus log | written from S1, S2 and the wiki | L-TA |
| Python mapper model (ours) | runs the CRC table and parsers on all 188 images before any RTL | | L-TA |

### 8.2 Test ROMs (our own, MIT)

No public CP1610 test suite was found [from L-TA]. We write our own with our own Python assembler:

- every opcode, addressing mode and flag, with cycle counts from the wiki opcode pages;
- SDBD corner cases (with R6, direct mode, same register as pointer and operand);
- non-interruptible instructions, interrupt cost;
- GRAM and STIC aliases and access windows;
- STIC modes, MOB sizes, flips, priority and collision persistence;
- PSG noise period (count the LFSR period from a register readback where possible).

### 8.3 Owner's library

- A regression set of about 25 images, one per hardware class (layout family, ECS, Intellivoice, cart RAM, paging, keypad class, 16-bit prototypes) [from L-TA].
- Smoke tests: the owner's MTE201 and IMI factory test cartridges, local only [from L-TA].

### 8.4 Save-state round trip (no reference needed)

Run N frames, save, restore, run M more. Compare frame CRCs and the PSG register-write log against a straight N+M run [from L-TA]. Run it at every build step and on every regression title. Also do restore into a freshly reset machine, and restore across a region mismatch (must fail cleanly).

### 8.5 Owner hardware tests (if hardware exists)

| Test | Settles |
|---|---|
| Composite capture of the 16 colours | palette hue |
| Recording of PSG white noise | noise taps |
| PAL console timing (scope on SR1, line count) | PAL frame timing |
| ECS keyboard ghosting test program | matrix model |
| Pocket: save, load, sleep, wake on several titles | firmware behaviour of 00A0/00A4 |
| Pocket (build step 2/3 test build): the cartridge's second indicator card after the first load, and after a user reload of a cartridge of another size (green: data table length = 0x0082 size; orange: they differ; cyan: no table entry, 0x0082 size used; grey: no 0x0082 size seen) | whether the host writes slot 0x100's size into the data table and rewrites it on reload (`apf_datatable.sv`; no reference core reads a file size back from the table) |

### 8.6 Overlay index

`research/test-assets/overlay_index.csv` maps all 97 overlay scans to titles and ROM CRCs [measured, L-TA]. Uses:

- choose test titles per input class: keypad-only-for-setup (41 cards), few keys in play (16), keypad-heavy (28) [estimated boundaries, L-TA];
- write the per-game profile table (B-17, Space Spartans, TRON Deadly Discs, AD&D) from card function facts;
- test the on-screen keypad's optional overlay slot locally with the owner's scans (never shipped).

---

## 9 Build order with done-tests

Each step adds its module's `ss` port and passes the round-trip test (8.4) before the next step starts.

| Step | Build | Done when |
|---|---|---|
| 0 | Python assembler, CP1610 model, mapper model, CRC table generator | model passes our opcode tests; agrees with a MAME trace on 3 games for 10 frames; mapper places all 162 proven images correctly |
| 1 | Pocket skeleton from the 7800 template: PLL, timing generator, test pattern, slots | Pocket shows a stable pattern at 59.92 Hz; sim counts 228 x 262 |
| 2 | Loader: SRAM, CRC32, table lookup, BIOS slots | CRC and page table match the Python model for the 25-image set |
| 3 | CP1610, bus fabric, EXEC, scratchpad, System RAM | EXEC runs with no cartridge; bus log matches the Python model in lockstep |
| 4 | STIC backgrounds (three modes), SR1/INTRM, BUSRQ, GROM/GRAM | EXEC title screen and 5 games' frame CRCs match MAME (palette aside) |
| 5 | MOBs and collisions | 10 more games match; STIC test ROM passes |
| 6 | PSG #1 and input module | register logs match MAME; games playable on the Pocket |
| 7 | `ss_ctl` hooked to 0x00A0/0x00A4/0x00B0, sleep | Pocket save, load and sleep work on the regression set **(build step 7: in simulation, `sim/tb/tb_savestate.py`; on the Pocket, the owner's test sheet)** |
| 8 | Cartridge formats: CFG, Intellicart .rom, cart RAM, paging | Python and RTL agree for each format; WSMLB pages; a `carttest`-style program (`sim/testroms/carttest.asm`, step 3) writes and reads back the Intellicart bank registers at $0040-$005F and the RAM they map (step 3 only pins that nothing answers there yet) **(build step 8: tb_loader over the step-2 set and the step-8 images built from our sources, tb_system `cartbank`/`cartcfg` with `sim/testroms/cart8test.asm`, tb_savestate `cartbank`/`cartcfg`/`cartnoss`, MAME as the .rom reference; docs/CARTFORMATS.md 7)** |
| 9 | ECS: ROM paging, RAM, PSG #2, keyboards, ports 3/4 | ECS BASIC and Mind Strike run; keyboard ghosting test **(built: docs/ECS_NOTES.md; 0.0.9)** |
| 10 | Intellivoice | resident phrases and B-17 speech sound right; per-opcode tests pass |
| 11 | JLP and flash slot | a JLP homebrew runs and keeps its flash |
| 12 | PAL | depends on PAL timing data (section 10) |
| 13 | On-screen keypad, profiles, overlay slot | owner hand test |

---

## 10 Risks

| Risk | Effect | Mitigation | Source |
|---|---|---|---|
| STIC timing windows disagree (2,900 vs 2,000; INTRM 3,791 vs 1,600; BUSRQ 114 vs 110) | games that race the STIC break | own test ROM; jzIntv black box; owner hardware | L-WIKI |
| CPU corner cases: interrupt cost (7, 9 or 10), SDBD with R6, branch-not-taken 7 cycles | timing-sensitive titles drift | read S1 bus timing; test ROMs | L-WIKI; MAME cp1610.cpp:3320, 1543 |
| ~~Bus phase table column swap in SM~~ **(review) resolved**: the SM table is headed BDIR/BC1/BC2 and agrees with the wiki (section 2.5) | none left; name BC1/BC2 pins carefully | | SM p.52 crop; S2 |
| Noise taps unverified on the 8914 | wrong noise sound | default bit0^bit3, recording later | L-DSL |
| Palette hue undecided | wrong colours | MAME palette first, capture later | L-SM; L-DSL |
| PAL timing undocumented | no PAL support | defer to step 12; ask the owner for hardware | L-WIKI; L-PSS |
| SP0256 SETMSB_3 differs (MAME loads 8-bit pitch; GI spec does not) | speech desync | walk the IVOICE ROM and game streams with a script | L-DSL |
| 26 images without proven layout; 6 only estimated | some games will not map | user .cfg; owner checks; menu message | L-TA |
| Pocket save-state behaviour undocumented (timing, size limit, size changing per game) | save or sleep fails | fixed 150 KiB blob; test on the Pocket early (step 7) | L-PSS |
| Clean-room slip (reading Intv_MiSTer, copying jzIntv code) | licence problem | keep a reference list per module with page or sheet; review notes before commit | PJ |
| No sim slots now | schedule | Python models first (step 0) need no slots | task |

---

## 11 Decisions for the owner

*Status 2026-10-25 (bootstrap): every decision below takes its recommended default; 13 is answered.*

| # | Decision | Recommended default |
|---|---|---|
| 1 | Licence | MIT for all own code. With cart ROM in SRAM, no GPL-3 SDRAM controller is needed. Switch to GPL-3.0-or-later only if a GPL part is added. |
| 2 | Ask Grabulosaure for a licence? | No. The clean rebuild does not need it. |
| 3 | PSG noise taps | bit0 ^ bit3 until a hardware recording says otherwise. |
| 4 | Palette | MAME's palette (BSD-3, credited) for first light; replace with a calibrated one if the owner can capture hardware. |
| 5 | PAL | One bitstream with runtime PLL retune (580-650 ALMs; fit has room), built last, after PAL timing is known. |
| 6 | Save blob size | Fixed 150 KiB for all games. |
| 7 | JLP flash | Its own nonvolatile slot, outside the save state. A state load does not roll back flash. |
| 8 | Auto-resume at launch (a nonvolatile `savestate.ss`, as in Tamagotchi) | Not at first; sleep and Memories only. |
| 9 | Unmapped images | Own CRC table from MAME CC0 data and our region proofs; others by user .cfg or owner check. No jzIntv heuristics. |
| 10 | ECS and Intellivoice | Auto from the table, with On/Off overrides in the menu. ECS forced off for titles with ROM at $7000/$E000. |
| 11 | Intv-only MAME build | Yes, in a separate worktree or build directory, when a build slot is free. |
| 12 | jzIntv as a black box | Yes: download and build under `research/.../downloads/`, run the binary only. |
| 13 | Hardware tests | **Answered (owner, 2026-10-24):** an NTSC console with the ECS and Intellivoice, no flash cart. So hardware checks use original cartridges and ECS BASIC only (no custom test ROMs); palette and audio captures from the console's RF output; PAL stays without hardware. A flash cart (e.g. LTO Flash) would allow our own test ROMs on hardware later. |
| 14 | Default input mode | Layer mode, with per-game profiles for B-17 and ring-type games. |
| 15 | The `wcbb-000` card | Treat as World Championship Baseball unless the owner knows otherwise. |

---

## 12 Sources

The lanes' reports and supporting files are under `research/<lane>/` in the project's research folder, which is not part of this repository.

| Code | Source | Licence / status | Where |
|---|---|---|---|
| SM | Mattel Intellivision Service Manual, Model 2609 (68 PDF pages; "SM p.N" = PDF page) | (c) Mattel; reference only | `docs/Intellivision_Service_Manual_Model_2609.pdf`; crops in `research/service-manual/img/` |
| S1 | GI CP-1600 Microprocessor Users Manual, May 1975 | (c) GI | bitsavers.mirrorservice.org/components/gi/CP1600/; `research/datasheets-licences/downloads/bitsavers_gi/` |
| S2 | GI 1982 Microelectronics Data Catalog (CP1610 p.441-446, STIC p.461-464, RO-3-9502 p.465-467, GROM p.468, PSG p.299-306, AY-3-8915 p.476, SP0256 p.286-290) | (c) GI | bitsavers …/gi/_dataBooks/ |
| S4 | GI 1978 "Programmable TV Games" (AY-3-8914 layout p.7-100 to 7-105) | (c) GI | spatula-city.org/~im14u2c/intv/gi_micro_programmable_tv_games/ |
| S6 | GI SP-0256 Design Objective Spec, Rev C, Nov 1981 | (c) GI | bitsavers …/gi/speech/ |
| S7 | Zbiciak/Palazzolo SP0256 Instruction Set | no licence stated; spec only | bitsavers …/gi/speech/ |
| S8 | SP0256A-AL2 datasheet, 1984 | (c) GI | bitsavers |
| S9 | jzIntv 20200712 docs: as1600.txt, bincfg.h, id_tag.txt, jlp.c header; name_list.c; **(review)** also doc/programming/interrupts.txt, psg.txt, stic.txt, intellicart.txt and doc/tech/ecs.html (all read as specification text, no code) | GPL-2+ (specs only); name_list.c public domain | `research/datasheets-licences/downloads/jzintv_src/` |
| wiki | wiki.intellivision.us archive, 225 pages | no licence; reference only | `wiki_intellivision_us/raw/<Page>.wiki` |
| AA | "Reading the ECS Keyboards", AtariAge | reference only | `docs/Reading_the_ECS_Keyboards_AtariAge.txt` |
| MAME | MAME fork at commit 3c6120b6: mattel/intv.cpp, intv.h, stic.h, stic.cpp; devices/cpu/cp1610; devices/sound/ay8910; devices/sound/sp0256; bus/intv/ecs.cpp, voice.cpp, slot.cpp, rom.h; hash/intv.xml, intvecs.xml, intv.hsi | BSD-3; hash files CC0-1.0 | MAME source tree, `src/...` (the owner's fork; upstream github.com/mamedev/mame) |
| APF | Analogue developer docs: host-target-commands, core-definition-files (core.json, data.json), bus communication | Analogue docs | analogue.co/developer/docs |
| AGG | agg23 openFPGA NES, SNES, Tamagotchi, Game & Watch, analogue-pocket-utils | Tamagotchi and sound_i2s MIT | `research/pocket-savestates/downloads/` |
| 7800 | openFPGA-7800: core_top.v, core_bridge_cmd.v, dist/Cores/Miasmark.7800/*.json, README.md | MIT + listed GPL-3 parts | github.com/Miasmark/openFPGA-7800 |
| PJ | Project list, section "Intellivision" | owner | owner's project list (not published) |
| IN | Input design notes, 2026-10-24 | owner | `INPUT_NOTES.md` |
| L-SM | Lane: service manual | | `research/service-manual/` (palette_estimate.txt, scripts/) |
| L-WIKI | Lane: wiki | | `research/wiki/scripts/lfsr_check.py` |
| L-DSL | Lane: datasheets and licences | | `research/datasheets-licences/` (scripts/lfsr_compare.py, crc_coverage.py, xml_mapping_coverage.py) |
| L-PSS | Lane: Pocket and save states | | `research/pocket-savestates/scripts/pll_plan.py` |
| L-TA | Lane: test assets | | `research/test-assets/` (overlay_index.csv, rom_classes.csv, rom_scan.csv, rom_classify_mame.csv, scripts/) |
| L-REV | Lane: review of this document, 2026-10-24 | | `research/review/scripts/review_checks.py` |

---

## 13 Open points from review

*Added by the review lane, 2026-10-24. Each item says what is missing or uncertain, why it matters and how to settle it. Items 1-8 affect the RTL directly; 9-15 are scope and format questions; 16-22 are about save states and the Pocket.*

### Timing

1. **PAL line length.** The design's PAL numbers (312 lines, 50.08 Hz) only work with 64 CPU cycles (256 pixel clocks) per line, not 57 [measured: review_checks.py]. jzIntv's PAL table is labelled estimates, and its "57 cycles per scanline" is flagged "very possibly BOGUS" [from S9 interrupts.txt:133-150]. The PAL VBlank windows (jzIntv: bus copy "?? 8840-8850 cycles") are unknown. *Settle:* owner PAL hardware (scope on SR1 and HSYNC), or a PAL service manual. Until then, make every line/frame constant a region parameter.
2. **PAL video path.** 4.000 MHz is not the PAL colour subcarrier (4.43 MHz), so the PAL console must use a different colour encoder from the AY-3-8915 [estimated from S9 psg.txt:46-47]. Which chip that is, and the PAL STIC part number, are unknown, so the PAL palette has no source. *Settle:* PAL board photos or a PAL schematic.
3. **Row-fetch cycle stealing with vertical delay 0.** MAME: 13 x 110 + 42 = 1,472 cycles per frame; jzIntv: 14,934 - 13,518 = 1,416 [measured: review_checks.py, from MAME stic.h:48-49, intv_m.cpp:668-680 and S9 interrupts.txt:127-128]. The vertical delay > 0 figures agree (1,362). Per-row cost (110 MAME, 114 wiki) and the 42-cycle frame BUSRQ are both "approximate" in MAME. *Settle:* own cycle-count test ROM on hardware, or jzIntv as a black box (decision 12). **(build step 4)** The model's `stic` mode steals about 1,410-1,470 cycles a frame with VDR = 0 and 1,330-1,400 with VDR > 0 (14 or 13 requests); MAME's traces show none (docs/STIC_NOTES.md T1-T3).
4. **VBlank windows.** STIC registers: ~2,000 cycles [S9 interrupts.txt:63-64] or ~2,900 [wiki VBlank_Period_1]. GRAM/GROM: 3,780-3,790 [S9 interrupts.txt:63, 130; MAME stic.h:50] or ~3,796 [wiki VBlank_Period_2]. When the display is not enabled (no write to $0020 in period 1), both windows stay open for the whole frame [from wiki VBlank_Period_1, VBlank_Period_2]. Outside the windows, writes are dropped and reads return "garbage" [from S9 interrupts.txt:66-68]; the core needs a defined garbage value (proposal: whatever the GROM-mode bus gives, else $FFFF), checked by test ROM.
5. **BUSRQ is taken only at the next interruptible instruction.** If the CPU ignores BUSRQ (long non-interruptible runs), the System RAM replays the same 20-card row for the next 16 lines, pushing the picture down a row [from wiki STIC_Bus_Request]. The `sysram` row buffer and the STIC must model this, and the CPU must model BUSRQ latency exactly. It also means the save-state freeze point is not always row-fetch-free if the freeze window is ever moved outside VBlank.
6. **STIC state decay.** jzIntv notes that STIC registers "lose their state after a few frames if interrupts are not taken regularly" [from S9 interrupts.txt:181-183]. Mechanism unknown; decide whether to model it (probably not at first; list it as a known difference).
7. **STIC register read-back values.** MAME returns fixed 1 bits in unused positions (for example X registers read $3800 | x, colour-stack registers $3FF0 | c, $0020/$0021 read $3FFF) [from MAME stic.cpp `stic_device::read`]. Bits 14-15 come back as 0 in MAME, but the bus has pull-ups (section 2.5). Some games read collision and position registers back. *Settle:* own STIC test ROM; until then follow MAME's masks.
8. **Collision rules checklist** for the STIC module: both MOBs need INTR set; a MOB never collides with itself; all 10 bits are sticky until the CPU clears them and stay set if INTR is cleared later; the CPU may set bits by writing; MOB-to-border and MOB-to-background (in coloured-squares mode colours 0-6 count as "on", colour 7 as "off") [from S9 doc/programming/stic.txt:239-245, 311-326, 433-434]. Whether collisions are computed for MOBs with VISB = 0 is not stated in the sources read; test ROM. **(build step 5)** S9 does state it: "The MOB does not need to be visible in order to interact with other MOBs, background cards or the screen border" (stic.txt:243-245), and MAME agrees. The STIC model (`tools/stic.py`) has all of these rules; where S9 and MAME disagree on MOBs (YRES card pairs, GROM cards in FGBG mode, MOB order against PRIO, the background under a delay strip, Colored Squares colour 7) mode `mame` follows MAME and modes `stic`/`none` follow S9: docs/STIC_NOTES.md 5 (M1-M10). The RTL follows modes `stic`/`none`; our STIC test ROM (`sim/testroms/sticmob.asm`) checks every rule here and tells M1, M4 and M5 apart by its border colour (STIC_NOTES 6).

### Scope and formats

9. **Machine variants.** The design targets Model 2609. Intellivision II has a different EXEC (extra ROM at $0400-$04FF and a cartridge check that breaks some titles), and the $0360-$03FF "garbage" may be INTV II only [from wiki Memory_Map:23-24, 53]. Decision for the owner: 2609 only (proposed), with the CFG `intv2` variable ignored.
10. **Keyboard Component** (6502, TMS9927 CRT controller, 16K x 10 shared RAM, tape drive) [from wiki Keyboard_Component]: not in the design; propose an explicit non-goal, with `kc_compat` ignored. Same for TutorVision/INTV88 (`tv_compat`) and PlayCable.
11. **LTO Flash mapper and CC3.** `lto_mapper` exists in the CFG and .ROM tag formats [from S9 as1600.txt:1048; id_tag.txt:640-657], but the 2020 jzIntv docs do not specify it, and a web search found no technical description (only LTO Flash user pages at intvfunhouse.com). CC3 (Cuttle Cart 3) adds serial ports (jzIntv examples/cc3serial) that no game needs. *Settle:* fetch the LTO Flash manual or newer jzIntv docs into `research/<lane>/downloads/`, then decide.
12. **ECS-style page flipping.** MAME implements only what ECS and WSMLB need (its own TODO, ecs.cpp:8-14); the spec is "write $xA5y to $xFFF, 16 pages per 4K range" [from S9 doc/tech/ecs.html]. Whether newer homebrew uses 2K-granular flipping (as some later documents may describe) was not confirmed. The page selects of all 16 ranges go in the save state. Note the $7000 ECS ROM is switched *off* by selecting page 1 ($7A51), not by a separate enable [from S9 doc/jzintv/debugger.txt:302-303].
13. **ECS UART** ($00E0-$00E3, cassette and printer) was missing from the map. ECS BASIC uses it for CSAV/CLOD and printing [from S9 doc/tech/ecs.html]. Propose: model status as "never ready" (or ready, data discarded) so ECS BASIC does not hang; real tape support is a non-goal. Its few registers go in the save state.
14. **Intellicart `.rom` tag area.** After the enable tables, id_tag.txt defines tagged metadata, including the compatibility byte (ECS, Intellivoice, INTV II, Keyboard Component: "supports / requires / incompatible") and the JLP/LTO feature bytes [from S9 id_tag.txt:593-670]. The .ROM parser should read these tags so that a .ROM needs no table entry.
15. **Intellivoice FIFO timing.** MAME (from jzIntv) gives 64 decles of 10 bits; a full FIFO drops writes; bit 10 on $0081 resets [from MAME sp0256.cpp:1211-1245]. How fast the SP0256 drains the FIFO and how LRQ behaves after an address load on real hardware is not in S6/S8 as read; the Intellivoice has no schematic in hand. Also, the expansion bus at $0700-$0CFF [from S9 intellicart.txt:91-92] is undocumented: it should be left unmapped (reads $FFFF) when the Intellivoice is on, so a cart there is not shadowed.

### Save states and the Pocket

16. **Result code 0** is idle, not "ok" (corrected in 4.1). `ss_ctl` must hold `ok` (or `err`) high until the next start or load request, because the host polls 0x00A0/0x00A4 and reads 2 for done [from 7800 core_bridge_cmd.v:65-69, 408-411].
17. **JLP flash slot size varies per game** (`jlp_flash` x 1.5 KiB sectors, default 4) [from S9 as1600.txt:1051, 1131-1133]. A Pocket nonvolatile slot is declared in data.json with a size; decide on one maximum size and whether a smaller game's file is padded. Also unknown: whether the Pocket flushes a nonvolatile slot on sleep, and what happens to a flash write in progress at the freeze. Proposal: freeze waits until no JLP flash command is in progress.
18. **JLP accelerator enable** is run-time state (`jlp_accel` 2 starts disabled and the game enables it) [from S9 as1600.txt:1124-1129]. It is in the blob under "Cart and JLP registers", but must be listed explicitly in the package file.
19. **Freeze point and Bus Copy.** The freeze lands in VBlank, often inside the CPU's interrupt routine with System RAM in Bus Copy mode. The Bus Copy flag, the GROM decode mode, the display-enable latch and the pending-INTRM state must all be in the blob (they are listed in sections 3 and 4.3; the round-trip test should freeze inside the ISR on purpose).
20. **Load size with a different region.** The header carries the region; a PAL state loaded on NTSC must fail with code 3 (already in 8.4). With PAL in a runtime-retuned PLL (decision 5), the region in the header must be checked *before* any machine state is written.
21. **Blob arithmetic checks out**: the listed parts sum to 152,528 bytes, padded to 153,600 [measured: review_checks.py]. JLP RAM is 8,000 words (16,000 bytes) inside its 16,384-byte slot [from S9 jlp.c header]; the Intellivoice FIFO is 640 bits.
22. **Resource estimate.** Only one arithmetic error found: the CRC table needs two M10K, not one (5.2). The M10K total (about 25 for ROMs, RAMs and tables) stays well under the 50-70 estimate. The ALM ranges remain [estimated] and cannot be checked without a fit.

### Single-source facts to re-verify

- AY-3-8914 I/O ports input-only: only AA's quote of David Chandler's documentation. Check against the SM schematic (does anything ever drive the hand-controller lines from the PSG side?).
- AY-3-8914 two-bit envelope select and 8916/8917 one bit: only jzIntv psg.txt:84-101. Check against S4 (1978 "Programmable TV Games") AY-3-8914 pages.
- PSG noise taps (already in section 10).
- MAME STIC constants are derived from jzIntv documents (stic.h:45), so "MAME and wiki agree" counts as one source.

## 14 Addendum: Intellivoice Service Manual (owner, 2026-10-24)
See research/intellivoice-manual/REPORT.md (docs/Intellivoice_Service_Manual.pdf, Model 3330). It confirms the
3.12 MHz resonator (Y1) and the chip set (74LS12, SPB640, SP0256, LM324, LM358), shows the module passes the
cartridge bus through unchanged, and gives the full analog chain (PWM -> ~150 Hz high-pass -> two 5 kHz active
low-pass stages -> volume -> buffer low-pass -> final high-pass) with component values, so the core's speech
filter can follow the real circuit. Voice volume is separate from game sound on the real unit: give it its own
mix level in the menu.

## 15 ECS: what to look for on the owner's unit (no service manual found, 2026-10-24)
Gaps the documents leave, which the owner's ECS can close:
1. Which peripherals: alphanumeric keyboard, Music Synthesizer (49-key), ECS hand controllers 3/4, cassette/printer
   cable. Sets which input models need hardware checks.
2. Board markings (only if the unit is opened anyway): the PSG (AY-3-8917 or 8916), the ROMs and RAM chips, the UART
   chip, and whether there is any crystal (the design assumes the PSG runs from the console's clock, MAME ecs.cpp:101).
3. Stacking order with the Intellivoice (which plugs into which) and whether both together behave normally.
4. ECS BASIC with no tape: what CSAV/CLOD do (error message, hang, or wait). Decides the UART model ($00E0-$00E3).
5. Keyboard behaviour in ECS BASIC: hold Shift with L, J, G, D, A (the documented scan bug); press three keys at the
   corners of a matrix rectangle and note any ghost character: W, Q and 1 together should ghost a 3 (rows 4/5,
   columns 3/4 of the wiki matrix table) **(build step 9: under 7.3's rule the ECS ROM's scan drives every row, so
   no ghost can appear: W, Q and 1 mask each other and all vanish; the 0.0.9 test sheet asks which the console
   shows; docs/ECS_NOTES.md 4)**;
   key repeat delay and rate.
6. Conflicting cartridges: does Centipede or Dig Dug (ROM at $7000/$E000) run with the ECS attached? Sets the
   "ECS must stay off" rule.
7. Music Synthesizer with Melody Blaster: whether any chord or key loses notes (diode matrix, many keys at once).
8. Controllers 3/4 on the ECS: which ECS game uses them (four-player titles), and that they read like ports 1/2.

### 15.1 Answers and new facts (owner, 2026-10-24)
- **Owner's ECS setup:** the ECS with the alphanumeric (computer) keyboard. No Music Synthesizer, no ECS hand
  controllers 3/4, and none of the conflicting carts (Centipede, Dig Dug). **ECS cartridges (correction, owner
  2026-10-24):** Mr. BASIC Meets Bits 'N Bytes and World Series Major League Baseball, possibly one more. So on
  hardware: ECS BASIC and the keyboard (items 4 and 5), Mr. BASIC (keyboard input in a game), and WSMLB, which is
  the title that uses ECS paging at $F000 (MAME ecs.cpp:200-245) and the Intellivoice: a strong check of paging,
  ECS RAM and speech together (its manual requires both the ECS and the Intellivoice, per the owner). The owner's
  copy is fragile (board separating from the shell). Items 6-8 rely on documents and MAME.
- **Stacking:** the owner puts the ECS on the console and the Intellivoice on the ECS; expected not to matter (the
  Intellivoice passes the bus through, Intellivoice manual p.3).
- **Console5 TechWiki parts list** (docs/ECS_Console5_TechWiki.mht/.txt, oldid 5911, 2021): U2 **AY-3-8917** (sound
  and controller input; confirms the PSG part), U3 **TMM2016P-2** (2K x 8 static RAM: matches the 2 KiB 8-bit ECS RAM
  at $4000-$47FF), U41 ROM (unmarked on the page), U42 4182-0033 (Mattel number, probably ROM), U52 4812-0128 (Mattel
  number, page guesses UART), U1 LM358P (op amp: likely the cassette interface). A separate power-supply PCB
  (C5 3300 uF): the ECS has its own regulation. No crystal is listed, which agrees with the PSG running from the
  console clock (still unconfirmed).
