# Save states

Build step 7 (DESIGN.md 4 and 9): the Pocket's save states, sleep and a
menu pause. This page is how the core does it as built; DESIGN.md 4 is the
plan it follows. The RTL is `src/fpga/core/intv_ss_ctl.sv` (the controller,
ss_ctl), wired in `intv_core.sv`; the module ids and the blob layout are
written down once, in `tools/savestate.py`, which generates
`src/fpga/core/intv_ss_pkg.sv` and the tables below.

## 1 The Pocket's side

| Command | What the core does |
|---|---|
| 0x00A0 save (bit 0 of the parameter: start; else a query) | freeze, write the blob into its buffer, answer ok; the host then reads 153,600 bytes from 0x50000000 |
| 0x00A4 load | the host has already written the blob to 0x50000000; freeze, check it, write it into the machine (or refuse it), answer ok or err |
| 0x00B0 menu open / closed | with **Pause in Menu** on (the default), the machine is frozen while the menu is open |
| sleep (`sleep_supported: true` in core.json) | a save before sleep and a load on wake: the same two commands (a load while the host holds the core in reset is staged: below) |

The template's `core_bridge_cmd.v` decodes the commands and gives the
result code the host polls for: 0 idle, 1 busy, 2 ok, 3 error. ok and err
stay up until the next save or load starts (template comments; DESIGN.md
13 item 16). ss_ctl changes its status bits one at a time, 4 clk_sys
apart, in an order that never lets the host read a wrong code through the
clock crossing: busy rises, then ok and err clear, then ack; at the end ok
or err rises, then busy drops.

The bridge's reads are one word behind: a read sends the word of the
previous `bridge_rd` (Analogue's `io_bridge_peripheral.v`: "reads are
buffered by 1 word"). The template's command registers and agg23's
`data_unloader.sv` (MIT) answer that way, and so does ss_ctl: on each
`bridge_rd` at 0x50xxxxxx it fetches the word and holds it on
`bridge_rd_data` until the next read. Accesses come at most every 88
clk_74a (1.18 us); ss_ctl serves one in about 25 clk_sys (0.6 us) through
two toggle crossings and the SRAM. It takes one access at a time and
latches its direction when it starts to serve it, so an access arriving
meanwhile cannot change it. While a save or load reads or writes the
state (about 5 ms) accesses are deferred: one is held and served after
it. The host sends none then (it polls the result first); a second one
while one is held would overwrite it, and ss_ctl counts that (`br_drops`,
sticky; the bench requires 0 in every run but the one that provokes it).

The crossings are constrained like the input module's (DESIGN.md 7.2):
`core_constraints.sdc` bounds every net of a bridge access (`b_we` ->
`b_we_s`; `b_w`, `b_d`, `b_t` -> `bp_*`, `b_s[0]`), of a read's word (`r_q`, `r_t` ->
`bridge_rd_data`, `r_s[0]`) and of the result bits (`s_*`, `l_*` ->
`st_a`) to 10 ns, against at least two destination clocks (or, for the
result bits, 4 clk_sys between changes) of margin, and
`sim/check/fit_crossing_check.py` checks each kept bit's row and the
two-flip-flop chains after every fit.

Wake. Analogue's documents say only that sleep uses 0x00A0 and 0x00A4,
not in what order the Pocket sends the load and releases the core's reset
on wake. ss_ctl accepts both. A load asked for while the machine is held
in reset (the cartridge loaded: its CRC is known) is checked at once,
without a freeze, and answered ok or err; an ok one is staged and applied
at the first quiet point after the reset exit (checked once more, with no
status change, so a blob changed in between is not applied). A load asked
for after the reset exit is the ordinary one. agg23's Pocket cores (fpga-tamagotchi,
MIT: `savestate_controller.sv`, `savestate_machine.sv`) were read for the
protocol: the host writes the blob before it sends 0x00A4, and reads it
after the save answers ok. Their code was not used.

## 2 Freezing

`intv_timing` has the machine's own position (mpos) beside the raster: with
`run` low the machine's clock enables stop and the raster runs on, so the
Pocket's video keeps its sync (the picture is black while frozen) and the
machine resumes on exactly its clk_sys when the raster comes round to it.
ss_ctl lowers `run` at a quiet point (DESIGN.md 4.2):

- the machine live and out of reset;
- in VBlank: the machine's line `vcnt` < 60 (the STIC's VBlank is 66.5
  lines; no row fetch and no BUSRQ there);
- the CPU at an instruction boundary: inside the BAR cycle of an opcode
  fetch, not on the clock that ends it (nothing is on the bus then), or
  halted, or held after reset.

It reads or writes the state 32 clk_sys after the freeze, with `ss_en` high
(the block RAMs' ports belong to the state port then), and drops `ss_en` at
least 8 clk_sys before `run` rises. A save or load that finds no quiet point
within 3 frames (counted while the machine is out of reset; 255 frames in
all) ends with err and leaves the machine untouched. While the machine is
not live the sound decays to 0 in about 4 ms (`intv_core.sv`), instead of
holding the PSG's last sample.

A request may come at any moment: in the middle of an instruction, while
the CPU is held by a BUSRQ, during a row fetch, while the PSG sounds; the
bench asks at each of these (section 5) and the freeze still lands at the
quiet point. The modules' state ports would allow a freeze in any clk_sys
(the step 3-6 round trips do that), so the quiet point is a margin, not a
need. The machine's time is its position on the raster, so the timing
word must come back exactly: a resume one CPU cycle late (a planted
fault) changes the whole run. (A slip of a few clk_sys inside VBlank that
skips no CPU or STIC clock enable would change nothing in the machine.)

## 3 The blob

153,600 bytes (DESIGN.md decision 6), 32-bit words, big-endian (the
bridge's byte order). The live part (version 1: bytes 0-40,959) is kept in
the SRAM at $13000-$17FFF, two SRAM words per blob word: a save writes it
there and the host reads it from there; for a load the host writes it
there. The rest reads 0. Bytes 64 on are the payload; the header holds its
length and CRC32 (zlib's CRC-32, as the cartridge CRC).

<!-- BEGIN GENERATED by tools/savestate.py gen: do not edit -->

Header (bytes 0-63, 32-bit words, big-endian):

| Word | Byte | Field | Value |
|---|---|---|---|
| 0 | 0 | magic | $494E5456 "INTV" |
| 1 | 4 | version | format version (1) |
| 2 | 8 | size | blob size in bytes (153600) |
| 3 | 12 | length | payload bytes from byte 64 (40896) |
| 4 | 16 | cart_crc | the cartridge image's CRC32 (as the loader computes it; 0 with no cartridge) |
| 5 | 20 | cart_words | the cartridge image length in 16-bit words |
| 6 | 24 | flags | bit 0 ECS attached, bit 1 Intellivoice attached, bit 8 PAL (all 0 in this core) |
| 7 | 28 | crc | CRC32 of the payload (bytes 64 .. 64 + length - 1) |
| 8 | 32 | mod_words | module state words (1324) |
| 9 | 36 | cram_cells | cart RAM cells (16384) |
| 10 | 40 | exec_crc | the EXEC slot's CRC32 (the bytes the loader took) |
| 11 | 44 | grom_crc | the GROM slot's CRC32 |
| 12-15 | 48-63 | reserved | 0 |

Modules (state words in id order; one 32-bit word per state word):

| Id | Module | Words | Blob bytes | RTL | Holds |
|---|---|---|---|---|---|
| $01 | timing | 1 | 64-67 | intv_timing.sv | machine position mpos {vcnt, hcnt, sub} |
| $02 | cpu | 8 | 68-99 | cp1610.sv | R0-R7, sequence state, flags, request lines |
| $03 | bus | 2 | 100-107 | intv_bus.sv | latched address, hold, IAB, cartridge answer |
| $04 | stic | 67 | 108-375 | intv_stic.sv | registers, handshake, row fetch, card engine, MOB sweep |
| $05 | psg | 21 | 376-459 | intv_psg.sv | registers, tone/noise/envelope counters, LFSR |
| $06 | scratch | 256 | 460-1483 | intv_ram.sv | scratchpad RAM 256 x 8 |
| $07-$08 | sysram | 352 | 1484-2891 | intv_ram.sv | System RAM 352 x 16 (ids $07-$08) |
| $09-$0A | gram | 512 | 2892-4939 | intv_ram.sv | GRAM 512 x 8 (ids $09-$0A) |
| $0B | cart | 21 | 4940-5023 | intv_cart.sv | image CRC, length, page table, page selects |
| $0C | row | 20 | 5024-5103 | intv_ram.sv | the STIC's row buffer 20 x 14 |
| $0D | line | 64 | 5104-5359 | intv_ram.sv | the STIC's line buffer 64 x 18 |
| | (unused, zero) | | 5360-8191 | | |

Then:

| Blob bytes | Part |
|---|---|
| 8192-40959 | cart RAM: 16384 cells of the SRAM area $18000-$1BFFF, cell 2k in bits 31-16 of a word |
| 40960-153599 | reserved for later steps, zero |

Ids kept for later steps:

| Id | For |
|---|---|
| $0E | ECS page registers, UART (step 9) |
| $0F | PSG #2 (ECS, step 9) |
| $10 | ECS RAM, ids $10-$17 (step 9) |
| $18 | Intellivoice FIFO and SP0256 (step 10) |
| $20 | JLP registers (step 11) |

Module words: 1324 (5296 bytes); payload 40896 bytes (bytes 64-40959); blob 153600 bytes.

<!-- END GENERATED -->

## 4 Loading: what is checked

Nothing is written into the machine until all of this holds; otherwise the
answer is err and the machine resumes where it was, untouched:

1. header words: magic, version, size, payload length, flags (ECS,
   Intellivoice, PAL: all 0 in this core), module word count, cart RAM
   cells, and the reserved words 0;
2. the cartridge and the system ROMs: the header's cartridge CRC32 and
   length equal the loaded cartridge's, and its EXEC and GROM CRC32s those
   of the files in the EXEC and GROM slots (`intv_core.sv` takes them from
   the loader's bytes): a state of another game, of no cartridge, or made
   with another EXEC (our test programs run from the EXEC slot) is refused;
3. the payload CRC32 over bytes 64-40,959;
4. the unused module area (bytes 5,360-8,191) is 0, and nothing but 0 was
   written beyond byte 40,959.

Then every module word goes through the state bus in id order, the cart RAM
cells into the SRAM's cart RAM area, and the machine resumes at the saved
position (the timing word). `python3 -I tools/savestate.py verify BLOB
--cart-crc X --cart-words N` makes the same checks on a file.

## 5 Not in the state

- the input module (the Pocket's controllers are read again after a load);
- the system ROMs and the cartridge image (the header's CRC ties the state
  to the image);
- the PSG's 48 kHz output filter and its sample phase (`intv_psg.sv`,
  DESIGN.md 4.4): after a load the PSG's steps are exactly as they were,
  but the 48 kHz samples are taken at another phase of its 223.7 kHz steps,
  so their values differ by the filter's rounding; this is not audible;
- the audio decay and the raster (the raster never stops).

Quiescent at the quiet point. These flip-flops change at run time but are
not in the stream, because at the quiet point they hold nothing the
machine needs again: each is rewritten before it is next used. A change of
the freeze point (section 2) must keep each reason true or put the
flip-flop in the stream.

| Module | Flip-flops | Why they need not be saved |
|---|---|---|
| intv_bus | `cart_req` (a one-clk pulse), `c_rd`, `cart_we`, `cart_wdata` | a cartridge request's direction and write data: set with each request (BAR, INTAK, ADAR, DW) and used only while it is in flight. At the quiet point none is (the CPU is inside an opcode fetch's BAR cycle, its request answered long since; the 32 clk_sys settle covers one just issued), and the answer the CPU will read is in the stream (`cart_hit` in word 0 and `cart_q` in word 1 of id $03) |
| intv_cart | `bst`, `m_req`, `m_we`, `m_be`, `m_addr`, `m_wdata`, `q_ram8` | the cartridge port's access machine and its SRAM request: idle (`bst` B_IDLE, `m_req` 0) whenever no access is in flight, as at the quiet point; the rest is set from the next request |
| intv_cart | `bus_rdata`, `bus_hit`, `bus_kind`, `bus_paged` | the last access's answer: intv_bus copies it into its own state the clock it is acknowledged, and nothing reads it after that |
| intv_ram | `q`, `q_b` | the read registers of every block RAM (scratchpad, System RAM, GRAM, row and line buffers): loaded from the address on every clk_sys, and used only after the address has been stable for a clock (DESIGN.md 4.3) |
| intv_ss_ctl | everything | the controller itself: idle at a resume |

## 6 Verification

`sim/tb/tb_savestate.sv` is the core's clk_sys side (`intv_core`) with the
SRAM model behind the template's `core_bridge_cmd` and core_top's bridge
multiplexer; the bench is the Pocket's host (commands at 0xF8000000, the
blob at 0x50000000, one bridge access every 88 clk_74a, a read's word taken
84 clk_74a after its `bridge_rd`). `sim/tb/tb_savestate.py` runs, for each
image of the regression set (the EXEC with no cartridge, Astrosmash in play
with keys, B-17 Bomber in flight, Atlantis, Buzz Bombers, our sticmob and
psgtest):

- R, a straight run, and S, the same run with saves asked for in the middle
  of an instruction, inside a BUSRQ, during a row fetch and while the PSG
  sounds, a menu pause, and a save inside a menu pause (sleep). Each save is
  asked for at the start of its moment (the sound's: the clk after a PSG
  tick that left a level not 0, held until the next tick, 4 CPU cycles on)
  and must reach the core inside it, within 30 frames. S must equal
  R in every machine frame (bus phases and CPU steps, PSG steps and
  samples, picture); every blob must pass `tools/savestate.py verify`, and
  its CPU and timing words must be what the machine held at the freeze;
- L, each blob loaded into a fresh core (one inside a menu pause: wake):
  every frame after the restore equals R's from the saved point on (the
  48 kHz samples aside, section 5);
- F, a blob of another image loaded: err, and the run goes on as R;
- C, five bad blobs (a payload byte, the header CRC, a reserved byte, the
  version, the unused module area with its CRC made right): err each, the
  run untouched, then the good blob loads.

More runs and checks:

- cart RAM: USCF Chess (RAM8 at $D000, 1,024 cells) is in the set, saved
  after a game has started (its board in the cart RAM). At every freeze
  the bench takes an FNV-1a hash of the SRAM model's cart RAM area
  ($18000-$1BFFF), and each saved blob's cart RAM must equal it; after
  every load the area must equal the blob's;
- D: the first state loaded into a core that has run 40 frames past its
  save point (so a word left out of the stream cannot hide behind a fresh
  core's boot value);
- the menu: in each menu window of S the machine's cycle counter stands
  still from the freeze (within a frame of the menu opening) to the resume,
  the freeze spans the wait's raster frames, and every wait ends at the
  frozen cycle; on every clk of every run the machine is never live while
  frozen and the sound is 0 once the machine has not been live for 4 ms
  (the decay takes at most 3.3 ms). psgtest's S0 runs S with Pause in Menu
  off: the machine runs through the menu, frame for frame as R;
- wake with the host's reset held: W1 asks for the load in reset and
  releases the reset after the answer, W2 releases it while the staged
  blob is checked; both must restore the state exactly as L does;
- B (psgtest): two blob reads while a save reads the state; the second
  overwrites the first, `br_drops` counts it, the save and the run are
  unharmed. Every other run must end with no access overwritten. Then the
  race: six times a blob read, and a blob write strobed while ss_ctl's
  SRAM access for the read is under way (faster than the bridge sends
  them); the read must be answered with its own word and the write must
  land, and at least one write must reach ss_ctl inside the read's access
  (the case the direction latch is for).

Planted faults, each of which must make a check fail: a module (the STIC)
dropped from the saved stream, a word restored one place off, the payload
CRC not checked, the machine resumed one CPU cycle late, the cartridge not
checked, the system ROMs not checked, the cart RAM not restored, the cart
RAM's cells taken one blob word off (on save and load), the menu ignored
(the machine runs on while it is open), a bridge access's direction not
latched (B's race), the PSG's envelope counter ignored on restore (a word
that boots to 0: only loads whose saved value is not 0 show it). Each
plant has its own reason, a pattern one of the run's problems must match,
so a plant is not counted as caught by an unrelated failure.

## 7 Open points for the Pocket

- The host's exact behaviour (order and timing of the blob's reads and
  writes, whether sleep opens the menu first, whether the wake's load comes
  before or after the reset exit) is not documented; the core serves any
  order (section 1). To check on hardware: save and load from the menu,
  sleep and wake, a state of another game. If wake fails (the game starts
  from its title instead of where it slept, or a black screen), the order
  is what to report.
- The live part of the blob is kept in SRAM $13000-$17FFF; JLP RAM (step 11)
  was planned there. When ECS, Intellivoice and JLP state join the blob
  (steps 9-11) the version goes up and the buffer moves (the SRAM has
  $1C000-$1FFFF free, PSRAM is unused).
- No auto-resume at launch (DESIGN.md decision 8): sleep and Memories only.
