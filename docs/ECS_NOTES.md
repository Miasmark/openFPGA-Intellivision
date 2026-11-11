# The ECS (build step 9)

The Entertainment Computer System as this core has it: what each part does, where each fact
comes from, the choices made where the documents stop, and how it is checked. The golden model
is `tools/ecs.py` (inside `tools/intv_system.py`); the RTL is `src/fpga/core/intv_ecs.sv` with
the ECS's parts of `intv_cart.sv`, `intv_media.sv`, `intv_input.sv` and `intv_psg.sv`.

Sources: DESIGN.md 2.6, 3 (module 13), 7.3, 15-20 (the owner's full copy); the owner's
research `research/ecs-rom-use/REPORT.md` (MAME measurements of what the games use);
`INPUT_NOTES.md` and the AtariAge "Reading the ECS Keyboards" thread (the matrix, the masking);
MAME 0.28x `bus/intv/ecs.cpp`, `bus/intv_ctrl/ecs_ctrl.cpp`, `sound/ay8910.cpp`,
`mame/mattel/intv.cpp` (BSD-3, read and cited, no code taken); the owner's ECS.bin, read with our
disassembler (nothing of it is in this repository).

## 1 Address map

| Address | Part | Reads | Writes |
|---|---|---|---|
| $00E0-$00E3 | UART stub (section 5) | $00E0 = $0002, the others 0 | dropped |
| $00F0-$00FF | PSG #2, AY-3-8917 (`intv_psg`, `ENV2 = 0`) | $FF00 \| register (MAME `read_ay`) | registers; $00FE / $00FF the port latches |
| $2000-$2FFF | ECS ROM 1 (ECS.bin words 0-4095) | on page 1 | page select at $2FFF |
| $4000-$47FF | ECS RAM, 2,048 x 8 | $00 \| byte | low byte; $4000-$403F also the STIC aliases |
| $7000-$7FFF | ECS ROM 2 (words 4096-8191) | on page 0 | page select at $7FFF |
| $E000-$EFFF | ECS ROM 3 (words 8192-12287) | on page 1 | page select at $EFFF |

**Pages.** A write of `$xA5y` to `$xFFF` sets the ECS's latch of range x (2, 7, E) to y. A ROM
answers only on its own page (REPORT 2, 5.4), so any other value pages it out, IntyBASIC's `$F`
included; MAME decodes only `$xA50` / `$xA51` (its ecs.cpp TODO says so). The ECS's latches are its
own: the cartridge's selects (`intv_pagesel` in `intv_cart`) see the same writes but keep their
own reset value (0), so a paged cartridge is never disturbed by the ECS's reset values.

**Who answers.** Where the ECS answers (a ROM range on its page, the RAM, PSG #2, the UART) the
cartridge neither answers nor stores. A write there still reaches the cartridge's page selects and
Intellicart bank registers (decoded from every write). This is MAME's `read_rome0` (the ECS ROM or
the cartridge, never both), and it is what WSMLB needs: the ECS boot maps the `$E000` ECS ROM with
`$EA51`; WSMLB's `$F026` writes `$EA50`, which pages the ECS ROM out, and from then on its own `$E000`
ROM answers. WSMLB's `$FA50` / `$FA51` are its own `$F000` pages (step 8), untouched by the ECS.

**The ROM in the SRAM.** The loader stores the ECS ROM slot at SRAM `$10000` (ECS.bin in order:
`$2000`, `$7000`, `$E000`; MAME's ROM_LOAD16_WORD_SWAP of ecs_rom.20/.70/.e0). `intv_cart` reads it
for an ECS ROM access instead of its map table. Without the ECS ROM slot the ROMs never answer.

## 2 Modes and the Auto rule

| Mode | At machine reset | Used for |
|---|---|---|
| off | nothing answers; PSG #2 held in reset | the menu's Off; Auto for a cartridge that maps $4000-$47FF or is tagged ECS incompatible |
| on | latches $2 = 0, $7 = 0, $E = 0: $7000 answers, the EXEC runs the ECS boot | ECS games; no cartridge; the menu's On |
| attached | latch $7 = $F: every ROM paged out; RAM, PSG #2, keyboard, UART answer | every other cartridge under Auto |

Auto (DESIGN 20, in its order): the ECS flag (CRC table, CFG `[vars] ecs = 1`, .rom tag) -> on;
a ROM word <= `$03FF` at `$4800` at reset paging (code there: the EXEC's `$4800` hook, REPORT 2) ->
on; the image maps `$4000-$47FF` on page 0, or the loader's flags say ECS_OFF -> off; else attached.
Added here: no cartridge (an empty image) -> on, as a console with the ECS and no cartridge (ECS
BASIC). A RAM cell at `$4800` is not code. The menu item "ECS" (Auto / On / Off) is taken at the next
machine reset (Reset or a load).

**ECS_OFF** (flags bit 5; tools/mapper/README.md) is set by a .rom's compat tag "ECS incompatible"
(`$06`, ECS bits 11), a CFG's `[vars] ecs_compat = 0`, or a hard conflict the mapper or the loader
finds (ROM or RAM at `$7000-$7FFF` or `$4000-$47FF`; in the library Centipede, Dig Dug, Congo Bongo,
Defender, both Pac-Man, the IMI and MTE201 test carts). The step-9 lane notes had recorded the tag
as a rule; the first cut of the code did not apply it (step-9 review). Applying the whole flag keeps
DESIGN decision 10 ("ECS forced off for titles with ROM at `$7000`"); with the ECS attached those
eight would have run as well (`$7000` is paged out), so nothing is lost by the rule, and nothing of
the ECS is in their way. Test images: `sim/testroms/step9` ecsoffcfg (ecsavail with
`ecs_compat = 0`) and ecsoffrom (a .rom tagged incompatible), both off; tb_loader's plant
auto_ecs_off_ignored.

**Refined here (DESIGN 20's second row; recorded there as the rule in force on 2026-10-26, the owner
may override it):** code at `$4800`
turns the ECS on only when the ECS boot would then start the cartridge straight, i.e. its header
word at `$500C`, byte-swapped and ANDed with `$FD`, is 1 (the ECS ROM's own test, REPORT 2 step 5;
IntyBASIC's hook cartridges have `$03C0` there and pass); otherwise the ECS is attached with its ROMs
out, which is "as if a `$4800` hook had run" and still runs the hook. Over the owner's library the
literal rule turned the ECS on for the four Imagic titles that boot through `$4800` (Atlantis, Beauty
& the Beast, Demon Attack, Microsurgeon): their `$500C` fails the test, so they would have shown the
ECS title and menu first (as on a console with the ECS), which is what the rule is there to avoid;
and a hook cartridge whose header fails the test would get an ECS title read from ROMs its hook had
just paged out (REPORT 2). With the refinement and ECS_OFF: 9 library images on (all by the ECS
flag), 171 attached, 8 off (the ECS_OFF titles above).

In the RTL, `intv_media` reads `$4800` and `$500C` through the cartridge port after every load,
before `ready` rises (the machine is still in reset, the selects at 0), and `intv_cart` keeps `m4`: an
entry `{r = 4, page 0, block < 8}` with R, W or B as the loader last wrote it. `ecs_auto` goes to
`intv_core`, which applies the menu's override.

With the ECS attached under Auto a game boots straight (the EXEC finds `$FFFF` at `$7000`, no ECS
title), and IntyBASIC's ECS test at `$4040/$4041` finds the ECS RAM (ECS.AVAILABLE).

## 3 PSG #2

The AY-3-8917 (Console5 TechWiki parts list; DESIGN 15.1): `intv_psg` with one envelope-select
bit (volume bit 4 selects the envelope, bit 5 is stored and read back but does nothing). MAME
emulates it as an AY-3-8914 (two bits); the difference shows only for a volume with bit 5 set and
bit 4 clear. Read masks are the 8914's (MAME's; ay8910.cpp notes that the 8916/8917's unused bits
"mirror one of the i/o ports, needs further testing": not modelled). Register 8 bits 6 and 7 are
the port directions (A = $00FE, B = $00FF). Both PSGs step together.

**The mix.** The sound is PSG #1 + PSG #2; while the ECS is attached or on the sum is scaled to 3/4
(floor; `intv_machine.sv`), and then held at 32,767 at most. With the ECS off it is PSG #1 alone,
unscaled, as in 0.0.8. Why (step-9 review): with the plain sum, World Series Major League Baseball
(the model over its 3,200-frame MAME reference keys) peaks at PSG #1 25,967, PSG #2 25,967, sum
43,278, and 464 samples went over 32,767 and were hard-clipped (the review counted 477 at the
ceiling, in 14 frames): a short distortion in loud six-channel
music. Scaled to 3/4 the peak is 32,458: no sample clips (`tools/ecs_mix_check.py`, run in the step-9
gates: ECS_MIX pass). Melody Blaster peaked at 32,764 unscaled. The cost is 2.5 dB less volume for
the games that run with the ECS attached; a soft limiter was the other choice and needs more logic.
The 3/4 sum can still reach 49,149 in theory (both PSGs at full volume on all channels), so the
saturation stays. tb_system's E lines hash the mix (the model in `mix_sample`); plants
ecs_mix_unscaled and ecs_mix_scaled_off.

**ECS Level** (build step 10; the owner: the ECS module has its own volume knob, as the Intellivoice
has): the menu's ECS Level (0x228) scales PSG #2 alone before the 3/4 sum: Off, Half, Normal, Loud,
Loudest = x0, x1/2, x1, x3/2, x2 (floor), default Normal, so the default sound is the one above. At
Loudest the sum can reach 73,722 before the saturation. Image ecssound_l4, plant ecs_level_ignored;
plant ecs_mix_wraps (the PSG sum's saturation dropped) targets the step-10 `psgs` line.

## 4 Keyboards

The matrix (MAME ecs_ctrl.cpp ROW.n, the wiki's table): port A's lines are rows 0-7, port B's
columns 0-7; a key joins a row to a column. Shift is row 6 column 7, alone in its row.

**Computer keyboard (no diodes), DESIGN 7.3.** An output port drives every one of its lines with
its latch (one line 0 and seven 1s for a row scan). The lines form groups through the pressed
keys; a group reads 1 if any line in it is driven 1, else 0 if any is driven 0, else 1 (the
pull-ups). So two keys in one column vanish from a row scan (1 beats 0, intvnut's post 2), Shift
cannot upper-case L, J, G, D or A, and three corners of a rectangle (W, Q, 1: rows 4/5, columns
3/4) mask each other: on the ECS ROM's scan (`$7293`: rows 6..0, one low) no ghost 3 appears and
all three vanish. A ghost needs undriven lines, which the AY's all-or-nothing ports never leave on
a scan. MAME ANDs the rows (no masking, no ghost). DESIGN 15 item 5's "W, Q and 1 should ghost a 3"
assumed undriven rows; the owner's hardware test decides (section 7).

**Music synthesizer (diodes).** A column reads 0 when a pressed key joins it to a row driven 0;
rows read their own drive (or 1). No ghost, no masking, no transposed path.

**A port reads its lines** whether input or output (MAME ay8910.cpp:1403-1425 returns the outside
value either way).

**The RTL** (`intv_ecs.sv`) finds the groups with a small engine instead of a combinational
closure: every 17 clk_sys it loads the driven lines and widens the "reached from a 0" and "reached
from a 1" sets one key further in each direction for 16 clocks, then registers the ports. The
values are at most 34 clk_sys old, less than a CPU cycle (48): latches change at a write at least
two CPU cycles before any read.

**The USB keyboard** (`intv_input.sv`, `tools/intv_input.py`; INPUT_NOTES plan item 2): while the
ECS is fully on (mode on: ECS games under Auto, no cartridge, the menu's On) it is the ECS keyboard
key by key (letters, digits, Enter = RTN, Esc, Space, `;` `,` `.`, the arrows, Backspace = left
arrow; either Shift = SHIFT, either Ctrl = CTL from the HID modifier byte), and only the numpad
stays player 1's keypad (numpad `.` = Clear). With the ECS attached (Auto's mode for most games:
no ECS ROM code runs to scan the keyboard) or off, the keyboard is player 1's keypad as in 0.0.8
(number row and numpad, Enter, Backspace = Clear) and the matrix reads no key. The first cut sent
the keyboard to the matrix whenever the ECS was attached, so under Auto almost every game lost the
number row, Enter and Backspace (step-9 review); `intv_ecs` now tells `intv_input` the mode on
(`full`). The six HID codes of a report are decoded one per clk_sys in a round of 8 clocks into two
accumulating registers (keypad lines, matrix switches), one decoder instead of twelve (about 640
ALMs; DESIGN 4.5); a new word from the clock crossing is taken only between rounds, so the outputs
always come from one whole word. With the setting
"ECS Keyboard" on Music synthesizer, two tracker rows play it: Z S X D C V G B H N J M = C3-B3,
Q 2 W 3 E R 5 T 6 Y 7 U I = C4-C5.

**The on-screen ECS keyboard** (1.0.4, docs/KEYPAD_NOTES.md 5): Start on player 1's controller
opens it under the same condition (mode on, the computer keyboard); its key, SHIFT (Y) and CTL
(X) go into the same matrix bits as the USB keyboard's, ORed with them, so the matrix rule above
applies to both together. `sim/check/ecs_osk_check.py` shows typing through it gives a game the
same frames as typing into the matrix (ECS BASIC, Super NFL Football).

ECS hand controllers 3/4 are not provided (no game reads them,
REPORT 5.6); their port bytes read as the matrix gives.

## 5 The UART and the cassette (1.0.5)

The ECS ROM's tape and printer code polls `$00E0`: bit 1 = ready to send (`$7E91`, `$7EAA`,
`$7EB9`, `$7FF8`), bit 0 = a byte received (`$70B0`), bit 3 must be 0 (`$7FC9`); it compares a
received byte with `$00AA` (`$7EE7`), so the UART cannot drive `$FF` into the upper byte. Until
1.0.5 the UART was a stub (status `$0002`, "ready, data discarded": saves went nowhere, loads waited
for ever). MAME maps nothing there (reads 0), so its saves wait for ever: MAME has no tape to
compare with.

**The tape engine in the ECS ROM** (`$7E1C-$7F61`, read in a local disassembly, never committed;
the design study `DESIGN_CASSETTE.md` outside the repository) runs once a frame from the ECS
interrupt; every tape user calls it: ECS BASIC's CSAV / CLOD / CVER, World Series Major League
Baseball, Game Factory, Super NFL Football, The Jetsons' Ways with Words, Melody Blaster (loads
only). No game touches `$E0` / `$E1` itself; games write `$E2` for their own motor prompts.
`$E2` = `$1D` plays (motor on), `$39` records, `$00` stops the motor. A save writes `$AA` sync
bytes (9, one every 8 frames), `$00`, the length as -N (low byte first), then the N data bytes, one
a frame at most, each when bit 1 is set. A load waits for bit 0, counts the sync, reads `$00`, the
length and the data. ECS BASIC keeps a program's name (4 characters, space-padded) in its first 4
data bytes; CLOD loads block after block until the name matches (a blank name takes the first).
That byte stream is jzIntv's `.ecs` file exactly (five files from the owner: `AA x 9, 00, -N`,
then N bytes; N = the file's length - 12).

**The cassette as a file** (the owner's decisions of 2026-11-06: one `GAME.ecs` per game, every
save kept by name, fast, an Erase action). `tools/ecs_tape.py` is the golden model and has the
rules; `intv_tape.sv` (in `intv_machine`, beside `intv_ecs`, which answers `$E0-$E3` with its
`q`) the RTL; `intv_tape_nv.sv` (in `intv_core`) the nonvolatile slot. In short:

- The tape is data slot 0x107 "ECS tape" (`.ecs`, nonvolatile, 16,384 bytes at bridge
  `0x30000000`); its size in the data table is 16,384 while the ECS is fully on (mode on: ECS
  games under Auto, or ECS = On), else 0, so other games get no tape file. A load with a tape file
  finds its end (whole blocks from 0) and zeroes the rest; a load without one, and the menu's
  **Erase ECS tape** action, blank the tape (the JLP flash's rule, `intv_core`).
- `$E0` reads `$0002`, plus bit 0 while playing with a byte under the head; `$E1` reads the byte
  (`$00xx`) and, playing, moves the head on: the ROM takes one a frame, about twice a real 300-baud
  tape. Bits 3-5 (errors) are never set.
- A save is a block of the tape, and goes in at the head: after a rewind that is the front, so the
  newest save comes first; right after another save (the motor off for a moment, no rewind) it is
  just after that block, so a game that writes one save as several blocks keeps them in their
  order. Game Factory does (owner's 1.0.5 test, 2026-11-07: its game came back scrambled while
  each block went to the front): its save is two engine calls back to back, ECS RAM `$4085-$47C8`
  (1,859 bytes) then cartridge RAM `$8800-$8B0C` (780 bytes), and its load reads them in that
  order. When the length comes in, the tape from there moves up by the block's length (what
  passes the end is lost: the oldest blocks) and the block is written there. When the motor stops
  with every byte in, the head goes after the new block, and if its first 4 data bytes are an ECS
  BASIC name (a letter or digit, then `$20-$5A`) another block with that name is removed; a
  game's data (Game Factory's `00 00 00 00`, `` `;`; ``) never replaces anything. The tape's end
  is found again (a block cut at the end is dropped) and the rest is zeroed. A save that stops
  short (or is cut by a reset or a state load) is taken out again. A block that does not fit from
  where it goes in is not recorded. (The head inside a block: the save goes in at that block's
  start.)
- The head goes to 0 at a machine reset and when the motor starts after 1 s (60 frames) or more
  with it off: CLOD's SET / GO prompts rewind, its search from block to block does not.
- **Tape speed** (1.0.6; Core Settings, default Normal; the owner's go of 2026-11-10 after the
  options in `TAPE_SPEED.md`, outside the repository). Normal: the ROM's routine (`$7E70`) is
  called once a frame while `$015E` bit 3 is set (by the ECS interrupt handler `$7261` for ECS
  BASIC; by the game's own code for Game Factory, `$5295`, and WSMLB, `$5552`) and moves one byte a
  call, plus its timers (an 80-frame wait and a 73-frame lead-in before a save's data, a 40-frame
  tail after): a 1,341-byte BASIC program loads in 1,342 frames and saves in 1,525. Instant: the
  opcode fetch that returns from such a call (the first fetch outside the routine, `$7E1C-$7F77`
  and its status helper `$70B0-$70B9`, after the fetch of `$7E70`) reads as a branch back to the
  3-word JSR just before it (`$0220`, `$0004`) while the transfer is busy, the tape ready
  (recording, or a byte under the head) and the frame's cycle below 12,934: the routine is called
  again at once, so whichever code calls it, it is called as it would be in the next frames.
  Every byte, timer, control-block word (`$4070-$4084`), flag and error path is still the ROM's
  own (verify, a name that does not match, the wait at the tape's end); only the frames differ.
  The cycle limit keeps the caller inside its frame: a loop across the next frame's interrupt let
  it nest into the routine (the first model run read a byte too many), and the display and the
  game's frame timing  timing stay as they are. About 40-60 bytes a frame: a BASIC save in 5 frames (227 at Normal),
  a load in 3 (44). The core's side (`intv_tape`): a copy of `$015E` bit 3 from the CPU's writes,
  whether a call of the routine is running, and the answer for the returning fetch and its next
  read, which `intv_bus` takes instead of the devices'; a 16-byte FIFO takes the save's bytes while the tape moves up (at Instant one comes
  every 230 CPU cycles or so, faster than a move). Those three bits are in the tape's state words,
  so a state may be made at any time, inside the loop too. A real ECS has no such speed; Normal
  is the console's pace.
- The printer's output is still discarded.
- Save state: module `tape` ($22, 2 words: the head and mode, the motor-off count; blob version 6).
  The tape itself is media, not state: a state load never undoes a save.
- `tools/ecs_tape.py` is also the developer's tool: `list` (a tape's blocks), `towav` / `fromwav`
  (300-baud FSK: 4,800 Hz 1, 2,400 Hz 0, 8 data bits LSB first, odd parity, 2 stop bits, for a real
  ECS and recorder), `join` (several `.ecs` files into one tape).

## 6 Save state (blob version 3; the tape's module since version 6)

Module `ecs` ($0E, 1 word: the three page latches, the port latches, the mode), `psg2` ($0F, 21
words as `psg`), `ecsram` ($10-$11, 512 words, four cells a word); header word 13 the ECS ROM's
CRC32 while the ECS is attached, flags bit 0 "ECS attached". A state saved with the ECS refuses to
load with it off, or with another ECS ROM (docs/SAVESTATE.md). Since 1.0.5 (blob version 6) the
module `tape` ($22, 2 words): the head and the mode, the motor-off count; not the tape.

## 7 Checks

- `tools/ecs.py` selftest (ECS_SELFTEST): the matrix rule's cases, pages, modes, the 8917's select.
- The cassette (1.0.5): `tools/ecs_tape.py` selftest (TAPE_SELFTEST: saves by name, newest first,
  the rewind, a stopped save, a full tape, a block too long, a jzIntv file, the state, the .wav
  round trip); `sim/tb/tb_tape.py` (RTL = model on 5 spec and 12 random UART scripts: every read,
  state word and store dump; planted faults); `sim/tb/run_tb_tape_nv.sh` (the slot at the bridge:
  a file with its tail zeroed, the clear, the erase); `sim/tb/tb_system.py --ecs-play` ecstape (ECS
  BASIC CSAV AAA, CSAV BBB, CLOD AAA past BBB and RUN 1.00, CLOD BBB and RUN 22.00: RTL = model
  frame by frame); tb_system's state dumps compare the tape's words; `sim/check/ecs_tape_check.py`
  (model only, too long for the RTL): World Series Major League Baseball's Keep Game (RTN, 1, C,
  SHIFT+K, RTN: one 1,792-byte block of its ECS RAM `$4100-$47FF`, 1,988 frames) and, in a fresh
  game with that tape, Old Game (RTN, 1, C, SHIFT+O, RTN: 1,805 frames): every byte back, both end
  on "Done". Game Factory's two-block save is covered by its rule in tb_tape's session script.
- Tape speed (1.0.6): `sim/check/ecs_tape_check.py --basic --wsmlb --gf` runs every case at Normal
  and at Instant and compares the tape, head, mode, ECS RAM (with the routine's control block),
  `$015E / $015F` and Game Factory's cartridge RAM exactly (ECS BASIC with CVER and a CLOD waiting
  at the tape's end; WSMLB; Game Factory driven through its menu: 4, STORE / LOAD); `tb_system
  --ecs-play` ecstape_fast (ECS BASIC at Instant, RTL = model frame by frame) and its planted
  faults (`--ecs-play --plants-only`, a short script: CSAV A, CLOD Z); `tb_savestate` ecstape (saves
  inside the loop, plant ss_tape_loop_lost); `tb_tape` the FIFO at Instant's pace (plant fifo_one).
- `tools/refs/ecs_ref_compare.py`: the model (MAME mode: MAME's ECS) against MAME intvecs traces
  and snapshots (`tools/refs/mame_ecs_trace.sh`): ECS BASIC typing, Mind Strike to its board,
  WSMLB to the field and pitching (its `$EA50` and `$FA50`/`$FA51`), Melody Blaster on the
  synthesizer, Mr. BASIC, our ecssound; Astrosmash under Auto against plain intv.
- `sim/tb/tb_system.py`: RTL = model cycle by cycle (images ecstest, ecssynth: our
  `sim/testroms/ecstest.asm`; ecsboot; ecsastro; the step-9 cartridges) with round trips, the
  keyboard scans against ECSKBD_WANT (the rule written out by hand); `--ecs-play` frame by frame
  over the MAME runs' keys.
- `sim/tb/tb_input.py` classes 10-11 (the key mapping, in modes off, on and attached);
  `sim/tb/tb_loader.py` the Auto rule on every image (ecsoffcfg, ecsoffrom: the incompatible tag);
  `sim/tb/tb_savestate.py` ecsbasic, ecssound, ecsavail, Atlantis (attached) and Super NFL Football
  (on) under Auto, the E runs (a state with the ECS into a core with it off) and the X runs (into a
  core whose ECS ROM differs by one byte): refused.
- `sim/tb/tb_system.py` also: ecsnorom (the ECS on with no ECS ROM slot: `$2000`, `$7000`, `$E000`
  read `$FFFF`), and library games under Auto: Super NFL Football with the ECS on (the CRC table's
  ECS flag since 0.0.24; see below), and with the ECS attached, the hardware default: Atlantis
  (its `$4800` hook), Body Slam (a Super Pro title: clears `$00E0-$00FF`); every image's `L ecs
  full` line (the key routing's mode).
- Super NFL Football (prototype, no list has it; owner, 2026-11-05: "supposed to be an ECS game
  ... starts up but goes black"): it is an ECS title. It calls the ECS ROM at `$7BE0` from frame 15
  and is driven from the ECS keyboard (RTN leaves the title; its menu takes typed words, e.g.
  `demo`). Attached (the ROMs paged out, as if a `$4800` hook had run) and off, the call reads
  empty space and the CPU runs away with the display off; with the ECS on, the ECS boot starts it
  straight (its `$500C` header passes) and it plays. jzIntv (black box, our map as a .cfg) does the
  same: `-s0` stops at `$7BE0`, `-s1` reaches the title. `data/cart_extra.csv` now sets its ECS
  flag, so Auto turns the ECS on.
- `tools/ecs_mix_check.py` on WSMLB: no sample of the mix at the ceiling.
- ECS BASIC's `CALL GRAB` (owner, 2026-10-27: it copies a MOB picture from the cartridge in the
  slot, so the cartridge stays mapped under ECS BASIC): `--ecs-play` run `grab`, ECS on with AD&D
  Cloudy Mountain, Bomb Run I's lines 140-180 (the 1998 ECS BASIC contest) typed and run. MOB 0
  then shows GRAM card 62, the cartridge's picture at `$53F5`; the model equals MAME intvecs over
  the 4.0M instructions and 4 snapshots of the same keys (`tools/refs/ecs_ref_compare.py`), and the
  RTL equals the model frame by frame.

**What MAME cannot show and the documents decide:** the `$F` page value (ecssound's ROMS OUT line;
REPORT 2), the masking and the ghost (DESIGN 7.3), the 8917's single envelope bit, the UART.
