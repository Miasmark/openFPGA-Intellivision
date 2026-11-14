# TutorVision / INTV88 (1.0.8, experimental)

The TutorVision mode as this core has it: what it changes, where each rule comes from, the
choices made where the documents stop, and how it is checked. **It is built from documents and
emulator comparison only and has never been checked against a unit.** With the mode off the core
is the 2609 core of 1.0.7, bit for bit (section 6).

The golden model is `tools/intv_system.py` (`SystemBus(tv=...)`), `tools/stic.py` and
`tools/psg.py`; the RTL is `intv_bus.sv`, `intv_stic.sv`, `intv_psg.sv`, `intv_machine.sv`,
`intv_sysrom.sv`, `intv_loader.sv`, `intv_cfgparse.sv`, `intv_media.sv`, `intv_core.sv`,
`intv_ss_ctl.sv`, `pocket_video.sv` and `test_pattern.sv`.

Sources:

- **[Z]** J. Zbiciak, "TutorVision / INTV88 Reverse Engineering Notes" (Mar/Apr 2017, updated
  Oct 2018; a public Google Doc). Board-level reverse engineering of Earl Ruffa's INTV88 board
  and Chuck Gill's TutorVision. The only primary source for the hardware rules; page numbers as
  cited below.
- **[JZD]** jzIntv 20200712's documents (`doc/rom_fmt/id_tag.txt`, `doc/utilities/as1600.txt`):
  the `tv_compat` CFG variable and the `.rom` tag's TUTOR field. jzIntv was also run as a black
  box (section 5.3); its source was never read.
- **[NDS]** the NINTV-DS README (file names and CRCs of `wbexec.bin` / `wbgrom.bin`; what its
  Full mode includes). README only.
- **[MAME]** MAME's `hash/intv.xml` (Map Mazes and Shapes in Space, `compatibility WBEXEC`);
  MAME has no TutorVision hardware.

The owner's research note (outside the repository) collects the history, the unit census and
the forum sources; nothing here relies on the forum extracts.

## 1 The two configurations

INTV88 boards were found inside ordinary INTV Super Pro (System III) consoles [Z p.24]. Every
INTV88 board has the STIC 1A, the 2K GRAM, the extra System RAM and the INTV 1986 GROM; only some
also have the TutorVision EXEC (the "WBEXEC", P587), the rest the stock EXEC (P586) [Z p.6,
p.24-25]. So the core has one mode with two settings:

| Setting | What it is | Files |
|---|---|---|
| INTV88 | a Super Pro with the INTV88 board and the stock EXEC: the STIC 1A's rules (section 3), with the user's `exec.bin` | none new |
| Full | the complete TutorVision: INTV88 plus the WBEXEC's second 4K words at $2000-$2FFF; the ECS is turned off (the WBEXEC sits where the ECS ROM's first range goes [Z p.4]) | `wbexec.bin` |

The font (the INTV88's GROM, `wbgrom.bin`) is a separate option, on or off in either setting and
with the mode off too.

## 2 Settings, files and the Auto rule

### 2.1 Menu (Core Settings, taken at the next Reset or load)

| Item | Options | Address |
|---|---|---|
| TutorVision | Auto (by cartridge), Off, INTV88, Full (WBEXEC), INTV88 12-request, Full 12-request (section 3.6) | 0x10000234 |
| Font | Original; TutorVision | 0x1000023C |

1.0.9: the bus-request option is folded into the TutorVision list (its item at 0x10000238 gave
its place in the menu to Tape: next load). The list's values 0-3 are 1.0.8's (Auto, Off, INTV88,
Full), so a saved TutorVision setting means what it did; 4 and 5 are INTV88 and Full with the
12-request timing (`core_top.v`: tv_setting 2 / 3 and tv_bq_set). The core no longer decodes
0x10000238, so a 1.0.8 setting of "STIC 1A (12 a frame)" left in the Pocket's saved settings is
dropped: the timing is back off (its default) until 4 or 5 is chosen. Auto has no 12-request
variant (no known program depends on the timing).

The mode is latched at machine reset (`intv_core.sv`), like the ECS and Intellivoice modes:

- **Off**: off. **INTV88**: INTV88.
- **Full**: Full when `wbexec.bin` is loaded (slot 0x108 status ok), else INTV88.
- **Auto**: as Full for a cartridge the Auto rule marks (section 2.3), else off.
- The 12-request timing (4, 5) applies only while the mode is on.
- **Font**: the TutorVision GROM when the option is on and `wbgrom.bin` is loaded; else
  `grom.bin`. It applies with the mode off too (both GROM ports: the CPU's and the STIC's).

### 2.2 Files (yours to supply, in `/Assets/intv/common/`)

| Slot | File | Size | CRC32 [NDS]; the owner's measured | Use |
|---|---|---|---|---|
| 0x108 TutorVis. EXEC | `wbexec.bin` | 16,384 bytes | 7558A4CF | bytes 8,192-16,383 (its words $1000-$1FFF = CPU $2000-$2FFF) into the WBEXEC ROM; its first 8 KiB are the stock EXEC (the owner's file: equal to `exec.bin`), and the core keeps running the EXEC slot's file there |
| 0x109 TutorVis. GROM | `wbgrom.bin` | 2,048 bytes | 82736456 | the INTV 1986 GROM, in its own block RAM |

Both are optional. Loader slots 6 and 7 (`intv_loader.sv`, addresses 0x06000000 / 0x07000000).
The test pattern shows them on card 19 of the bottom row: pixels 152-155 the EXEC, 156-158 the
GROM; green loaded, yellow another size, grey missing, and red for a missing `wbexec.bin` only
when the menu says Full.

### 2.3 The Auto rule

The loader's verdict (`res_tv`, `tools/mapper/cartfmt.py tv_of`): off (incompatible) wins, then on:

| Source | Field | On | Off |
|---|---|---|---|
| BIN + CFG | `[vars] tv_compat` [JZD as1600.txt:1044] | 2 supports, 3 requires | 0 incompatible |
| `.rom` | compat tag byte 1 bits 3:2, TUTOR [JZD id_tag.txt:604] | 01 supports, 10 requires | 11 incompatible |
| LUIGI | header flags 11:10 | 10 enhanced, 11 requires | 00 incompatible |
| CRC table | entry bit 15 (`TV_FLAG`): MAME's `compatibility WBEXEC`, or `data/cart_extra.csv`'s `tv` column | flagged | |

`tv_compat = 1` (tolerates, jzIntv's default) leaves the mode off. The table flags the four
TutorVision images the owner has (cart_extra.csv rows and MAME):

| Image | CRC32 | Size | Needs |
|---|---|---|---|
| Map Mazes | 59F5FA32 | 32 KiB ($5000 + $9000) | Full |
| Shapes in Space | 714ECD51 | 32 KiB | Full |
| Geo Graphics (the owner's dump; CFG with `tv_compat=2`) | 10BBDB07 | 32 KiB | Full |
| Little Man Computer (homebrew; JLP flash, CFG) | F57B1FCE | 77,868 bytes | INTV88 (2K GRAM; its readme names jzIntv -G2) |

With Auto, the three World Book titles get Full (with `wbexec.bin`) and Little Man Computer
does too: Full is a superset of INTV88, and LMC runs on it (it never touches $2000-$2FFF).

### 2.4 Controls (1.0.8)

In Map Mazes, Shapes in Space and Geo Graphics the keypad's Enter is needed most of the time, and
"any LOWER SIDE KEY" returns to the Main Menu (their help screen). Under Keypad Mode Auto their
game profiles put the keypad's Enter on A and Clear on B, and the lower right side action on X:
X returns to the Main Menu (a lower side key); Y and R's number pad as everywhere (KEYPAD_NOTES.md 3). A fixed Keypad Mode ignores the profiles. Little Man
Computer has no profile.

## 3 The rules the mode changes

Each rule holds from machine reset while the mode is on. "2609" is the core's behaviour with the
mode off (DESIGN.md 2.6, STIC_NOTES.md).

### 3.1 GRAM: 2K, 256 cards

- 2K x 8 at $3800-$3FFF, not mirrored [Z p.18-20]. The 2609's 512 bytes repeat four times over
  $3800-$3FFF. One 2K block RAM serves both (`intv_machine.sv`); the 2609 uses bytes 0-511.
- Color Stack BACKTAB: bits 10:9 join the GRAM card number (cards 0-255, bits 10:3), as for GROM
  cards [Z p.20].
- MOBs: the card number is never masked; in Foreground/Background mode MOBs see all of GRAM and
  GROM ("STIC1A only applies the restriction to BACKTAB cards. MOBs always see the full GRAM and
  full GROM" [Z p.17]).
- Foreground/Background BACKTAB stays cards 0-63 (bits 8:3).
- GRAM starts at zero at power-on and reset, as in mode off. A stock game that leaves junk in bits
  10:9 (Worm Whomper, Space Patrol: "displays corrupted graphics" [Z p.23, Misc Observations])
  therefore picks blank cards 64-255 here, so those objects go invisible or flicker (the owner's
  test of 1.0.8: Worm Whomper's worms invisible; Space Patrol's rocks flicker and its UFOs are
  invisible). On the board those cards hold the RAM's power-on contents, so it draws
  random-looking garbage instead. Power-on RAM is not reproducible, and zero keeps save states and
  the benches repeatable.

### 3.2 System RAM $0360-$04FF

416 more 16-bit words [Z p.6-7; NDS], in the same block RAM as the 2609's 352 (System RAM is
1K x 16; word = address - $0200). Nothing else answers there: the cartridge port's $0400-$04FF
reads are overridden (`intv_bus.sv sel_tvr`). The STIC still fetches BACKTAB from $0200-$02EF.

### 3.3 No aliases

The STIC 1A does not answer the GRAM write aliases $7800, $B800, $F800 or the STIC register
aliases $4000, $8000, $C000 [Z p.17]. Reads of $4021 / $8021 / $C021 no longer reach the mode
latch (the documents do not say; this core takes "no aliases" to cover them: open question 2).

### 3.4 The display and its reads

- The 160th playfield column is shown (cards and MOBs) [Z p.15; IntvPrime FAQ]. The Hide (playfield
  only) window shows it too (`pocket_video.sv`: not blacked out with the mode on). The collision
  area stays the 2609's: a MOB pixel in the 160th column touches the border, never the background
  (open question 3).
- $0022 reads $3FF7: bit 3 reads 0 [Z p.14].
- With the display on, GROM and GRAM read $00FF outside the STIC's register window [Z p.15]; the
  2609 core gives $FFxx (GROM: the upper byte pulled up) and $0000 (GRAM), measured on the
  owner's console. STIC registers outside the window read $0000 as on the 2609 core: [Z]'s
  "random values" are not modelled.

### 3.5 Full: the WBEXEC

The WBEXEC is 8K words at $1000-$2FFF: the first 4K the stock EXEC, the second 4K the TutorVision
extensions, not bank-switched [Z p.4]. Full maps the second half at $2000-$2FFF (`intv_sysrom.sv`
WBEXEC ROM, 4,096 x 10) and turns the ECS off: the menu's ECS item is overridden while Full is in
effect. The cartridge port still sees the bus there but its reads are overridden.

### 3.6 The bus-request option (TutorVision's "12-request" choices; until 1.0.8 INTV88 Bus Timing)

[Z p.15-16]: the INTV88 leaves the CPU slightly more bus time; Zbiciak's guess, from experiments
in jzIntv, is that the STIC 1A issues only the 12 card-row requests (no short request at the
frame start, no 14th) and that each is about one CPU cycle shorter. The measured tables are not
available as text. With the option on the core does exactly that guess (`intv_stic.sv bq`,
`tools/stic.py schedule`): no frame-start request, each row request one cycle shorter. Off by
default: no known program depends on it.

### 3.7 PSG

Inside the STIC 1A, "mostly an AY-3-8914 clone" [Z p.18]:

- The envelope shape register reads back: already so on the 2609 core (MAME's mask, 4 bits).
- Volume modes 01 and 10 (bits 5:4) "take volume from envelope for one envelope step and then go
  to silence": the envelope's level until its first step after the last shape write, then 0
  (`efirst`, state word 20 bit 8). The 2609 core gives the envelope >> 2 and >> 1.
- R7 bits 7:6 read 0.

### 3.8 Not modelled

- The interrupt logic's bug (IntyBASIC 1.2.9 programs dispatched twice; the stripes in Map
  Mazes) [Z p.8-9, p.15]: modelling a fault from a theory is not done.
- STIC registers' "random" closed reads (3.4); the cartridge port's raw INTAK and BC lines; the
  dead cartridge RESET pin [Z p.3, p.11, p.23].
- The controllers (74HCTLS257 muxes, no series resistors [Z p.21]): the same to software.
- The palette and the audio output stage (same ladder [Z p.21]; the audio stage "TBD").
- jzIntv's 128-tile GRAM (`-G1`): no hardware has it.

## 4 Save states

The TutorVision state is a segment of its own after version 6's live part (blob bytes
56,960-64,767, 1,952 words: GRAM cards 64-255 as ids $24-$29, System RAM $0360-$04FF as $2A-$2B;
`tools/savestate.py TV_LAYOUT`), present only with header flags bit 2 (the mode on; bit 3 Full).
The format version stays 6 and the blob 153,600 bytes; a TutorVision state's header length is
64,704 (else 56,896); header word 15 holds the WBEXEC slot's CRC32 in Full mode (else 0); the
GROM CRC word is the active GROM's (`wbgrom.bin`'s with the font on).

A state loads only into a core in the same configuration; each mismatch is refused (Load State
gives the Pocket's error, the running game is untouched):

| The state, the core | Refused by |
|---|---|
| a TutorVision state into a core with the mode off, or the reverse | header length and flags bit 2 |
| INTV88 into Full, or the reverse | flags bit 3 |
| Full, with another `wbexec.bin` | header word 15 |
| the other font | the GROM CRC (word 11) |

1.0.7 states (and 1.0.8 states with the mode off) are 1.0.7's format exactly: they load with the
mode off, and are refused with it on.

## 5 Verification

### 5.1 Our test program, model against the documents

`sim/testroms/tvtest.asm` runs in the EXEC slot and touches every rule of section 3 (its header
lists its eight sections); its results land in System RAM from $0330. `sim/check/tv_check.py`
runs it in the model with the mode off, INTV88 and Full and checks every result against what
[Z] says for each board (the expectations are written from the documents, not from the model),
and that the pictures of the modes differ; with `--games DIR` it also runs the four owner images
to their titles (the three WBEXEC titles must run code in $2000-$2FFF). TV_CHECK pass.

### 5.2 RTL against the model

- `sim/tb/tb_system.py`: images `tvtest_off`, `tvtest_88`, `tvtest_full`, `tvtest_bq` (the bus
  option), `tvtest_font`, and the owner's `tv_lmc` (INTV88) and `tv_mmaze` (Auto: Full); every bus
  cycle, picture, card fetch, sample and state word equal to the model, through the bench's
  save/restore round trips. 14 plants (`tv_*`) for the rules of section 3.
- `sim/tb/tb_loader.py`: the Auto rule's sources (CFG `tv_compat` 2 and 0, a `.rom` TUTOR tag,
  a forced CRC of Map Mazes), the slots 6 and 7 (status, the WBEXEC ROM's and the font's
  contents); 3 plants.
- `sim/tb/tb_savestate.py`: `tv88` (INTV88, the font) and `tvfull` (Full): saves, loads, wake,
  corrupt blobs; the blob's TutorVision segment against the machine's; T (into a core with the
  mode off) and G (the other font) refused; 3 plants.
- `sim/tb/run_tb_timing.sh --all`: the 160th column in the Hide window, the test pattern's card 19;
  2 plants.

### 5.3 jzIntv 20200712 as a black box

Our `tvtest.asm` image as jzIntv's EXEC (`-e`), its debugger dumping the results (`m 330`) and
taking screenshots (`vs`); `--help` gives `-G#` / `--gramsize`: "2: 256 tiles (INTV88)".

- `-G0`: every result equals our mode off, but for the GRAM and GROM reads outside the window
  (jzIntv gives the address's low byte, our 2609 core the console's measured values).
- `-G2`: the 2K GRAM results equal ours; jzIntv 20200712 models nothing else of section 3 (the
  aliases, the RAM, $0022, R7: all as its 2609).
- Pictures: in a Color Stack frame and a Foreground/Background frame, jzIntv `-G0` equals our
  mode off and `-G2` our INTV88 in every playfield pixel (160 x 96, the colours matched one to
  one): GRAM cards 64-255 in Color Stack, MOBs above card 63 in FG/BG, the 160th column.

So for the GRAM rules two independent implementations agree; the rest rests on [Z] alone.

### 5.4 Cost (trial fit, seed 1, commit d3ddbbf)

15,052 ALMs (81 %; 1.0.7's trial: 14,775, so +277), 172 RAM blocks (143, +29: the GRAM and
System RAM blocks doubled, the WBEXEC 4K x 10, the font's GROM with two ports, the save-state
shadow 4,096 -> 5,952 words), 25 DSP. Timing as 1.0.7: `clk_sys` worst setup +0.754 ns, worst hold
+0.039 ns, no negative slack anywhere; FIT_CROSSING pass. Test build 2 (commit 00c5a1d, the
TutorVision titles' button profiles, 122-bit profile records): 15,029 ALMs, 173 RAM blocks,
`clk_sys` worst setup +0.757 ns, worst hold +0.044 ns; FIT_CROSSING pass.

## 6 Mode off

Every 1.0.7 gate runs with the mode off (the benches pass `+tv=1`); the state layout, the menu's
other items and every state word are unchanged (the PSG's new bit reads 0 with the mode off).
The only change visible with the mode off is the Font option, which is off by default.

## 7 Open questions

1. Everything here is from [Z] (one source, first-hand) plus jzIntv for the GRAM; a unit running
   tvtest from an LTO Flash is the only route to measured truth (note: cartridge RESET does not
   work on INTV88 [Z p.23]).
2. Does a read of $x021 at the $4000 / $8000 / $C000 aliases still select Color Stack mode?
3. The STIC 1A's collision border with the 160th column.
4. The bus-request pattern (3.6) and what the INTV88 does at vertical delays above 0.
5. How the WBEXEC boots a non-TutorVision cartridge, and how it recognises a TutorVision one.
6. What FW Diagnostics and the detection ROMs test to call a unit a STIC 1A.
