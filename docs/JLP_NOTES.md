# JLP (build step 11): design notes

What a JLP cartridge is to the CPU, where each fact comes from, what is still unknown and how to
settle it, and what the core should do meanwhile. Written to be turned into a Python model
(`tools/jlp.py`, next to `tools/ecs.py` and `tools/sp0256.py`) and an RTL module (`intv_jlp.sv`,
DESIGN.md 3 module 15). Paper research only (2026-10-30): nothing was run.

Every fact is marked **[doc]** (a document says it), **[inf]** (inferred from code that uses the
JLP, or from two documents together), **[unk]** (no source; section 4 says how to settle it) or
**[choice]** (what the core does until a test says otherwise).

Sources (codes used below; all read for facts, no code taken):

| Code | Source |
|---|---|
| PV | *JLP Programmer's View*, the programming chapter of the JLP Developer's Guide (Left Turn Only, J. Zbiciak), 32 pp., PDF made 2017-04-09. Fetched from <https://manuals.plus/m/fa81eae08be3973e079ad17394c6803c3f14bd660f93dbd70851a902305bf131.pdf>; copy and text extract in `research/jlp/downloads/jlp_programmers_view/` (sha256 `fa81eae0…f131`). No licence stated: reference only. Cited by PDF page. The page ends "[... work in progress …]" (p.32). |
| JH | jzIntv 20200712 `src/jlp/jlp.c`, the leading comment only, lines 1-22 (DESIGN S9; read up to the first line of code, nothing after) |
| AS | jzIntv `doc/utilities/as1600.txt` (lines cited) |
| IT | jzIntv `doc/rom_fmt/id_tag.txt` (lines cited) |
| RN | jzIntv `ReleaseNotes_20200607.txt`, `ReleaseNotes_20200712.txt` |
| MM | jzIntv `doc/programming/memory_map.txt` |
| IB | IntyBASIC 1.5.1, `pocket_projects/intellivision/tools-ext/IntyBASIC/` (manual.txt, IntyBASIC.cpp, node.cpp, code.cpp, intybasic_prologue.asm, intybasic_epilogue.asm, samples/flash.bas); the client side, read in full where JLP appears |
| LTO | LTO Flash help, "ROM features" icons: <https://intvfunhouse.com/intvfunhouse/ltoflash/help/detailed_help/romfeatures.php> |
| REPO | the dev tree (`daria_work/intv/gate17/wt`, read only): DESIGN.md, CARTFORMATS.md, SAVESTATE.md, STIC_NOTES.md, the RTL and tools named where cited |
| OD | the owner's full DESIGN.md, `pocket_projects/intellivision/DESIGN.md` (row 11 of the build plan at line 491) |

Looked at and not usable: the Scribd copy of the whole Developer's Guide (only the wrapper page
comes through); AtariAge threads 264236 "JLP Accelerator support", 353861 "JLP Acceleration vs RAM
vs FLASH" (HTTP 403 to the fetcher); the LUIGI format PDF on ltoflash.leftturnonly.info (connection
refused). A search-engine summary attributed the sentence "CPU accesses to addresses $8000 - $9FFF
behave as if JLP Accelerators do not exist" (when the accelerators are off) to the LUIGI document;
not seen first hand, so it counts as **[inf]** below. MAME (the owner's fork) has no JLP at all
(no `jlp` in `bus/intv`, `mame/mattel`, `hash/intv.xml`). The owner's library has no JLP title
(no CFG in `ROMLibrary` names `jlp`; tools/mapper/README.md flag 0x10: "no table source marks
JLP").

## 1 How a cartridge asks for JLP

### 1.1 CFG `[vars]`

| Variable | Values | Meaning | Source |
|---|---|---|---|
| `jlp_accel` | 0-3 | 0 JLP disabled; 1 accelerators on at reset, no flash; 2 accelerators **off** at reset, flash present; 3 on at reset, flash present | AS:1049, 1124-1129 **[doc]** |
| `jlp` | 0-3 | synonym for `jlp_accel` | AS:1050 **[doc]** |
| `jlp_flash` | sectors of 1.5 KiB | flash capacity. With `jlp_accel` >= 2 it "should be non-zero. If missing, it will take on a minimum value of 4. If set to 0, jlp_flash support will be disabled." Default 0, or 4 if `jlp_accel` >= 2 | AS:1051, 1131-1133, 1168-1169 **[doc]** |
| `jlpflash` (sic) | sectors | what IntyBASIC actually writes for `FLASH INIT SIZE n` (default 16) next to `jlp = 3`. Not in as1600.txt; whether jzIntv reads it is **[unk]** (test T10b) | IB IntyBASIC.cpp:4203-4220, manual.txt:1358-1375 **[doc]** |

"Accelerators" in these tables means the whole JLP feature set that $8033/$8034 switch (RAM
included, section 2.2): AS and IT call mode 1 "accelerators enabled", and IntyBASIC's `--jlp`
(which needs the RAM) emits `jlp = 1` (IB IntyBASIC.cpp:4204-4206) **[inf]**.

`jlp = 3` is also as1600.txt's own example (AS:995, 1003).

### 1.2 Intellicart `.rom` tag

Tag $06 (Game Attribute / Compatibility, 3-5 bytes; IT:593). Bytes 3 and 4 (IT:639-672) **[doc]**:

| Byte | Bits 7-6 | Bit 5 | Bits 4-2 | Bits 1-0 |
|---|---|---|---|---|
| 3 | JLP Accel (same 4 codes as `jlp_accel`: 00 none, 01 on/no flash, 10 off/flash, 11 on/flash; IT:664-667) | LTOM | reserved | JLP Flash [9:8] |
| 4 | JLP Flash [7:0] | | | |

"Byte 4 need not be present if JLP Accel is set to 00 or 01" (IT:653). "The JLP Flash field must
be non-zero for JLP Accel modes 10 and 11 ... in units of 1.5K sectors. It specifies the minimum
required for the cartridge; however, the unit may provide more" (IT:669-672). as1600 writes
`jlp` and `jlp_flash` into this tag (IT:971-972). Note IT:640-642: games that *require* these
features "will not run correctly on an Intellicart or CC3".

### 1.3 What the core parses now (build step 8)

- CFG: `intv_cfgparse.sv:118-119, 190-191` and `cartfmt.py:212-213`: `jlp` or `jlp_accel` not 0
  sets one flag, `FLAG_JLP` = $10 (`intv_loader.sv:136, 410`). The value is not kept and
  `jlp_flash` is not read. Values saturate at 255 (`intv_cfgparse.sv:361`), enough for the
  flash sizes the Pocket slot allows (section 5.3).
- .rom: `intv_romparse.sv` keeps the first good tag $06, bytes 0-4 (`cmp_body[39:0]`, byte 3 in
  [15:8], byte 4 in [7:0]); `intv_loader.sv:417` sets `FLAG_JLP` when byte 3 bits 7-6 are not 0
  (`cartfmt.py:634-635` the same). LTOM refuses the image (CARTFORMATS 3.1). A short tag (3
  bytes) leaves bytes 3-4 zero: no JLP, which is right (IT:639 "if present").
- Test inputs already in the tree: `sim/testroms/step8/cfg/zoo1.cfg:23` (`JLP = 3`, upper case:
  names are case sensitive, so this one must *not* count), `zoo2.cfg:15` (`jlp_accel = 1`),
  `rombankw.asm:18` (`CFGVAR "jlp" = 1`).
- **Step 11 needs** [choice]: keep the mode (2 bits) and the sector count (10 bits) instead of the
  flag: CFG `jlp`/`jlp_accel` (when repeated, the first one counts: AS:1056-1058 "typically ...
  the first instance takes precedence"), `jlp_flash`, and `jlpflash` as a synonym (IntyBASIC's games get
  the size they asked for; harmless if jzIntv ignores it, since programs read the range at run
  time, section 2.6); .rom byte 3 bits 7-6 and {byte 3 bits 1-0, byte 4}. Default sectors: 4
  when mode >= 2 and no size given; mode >= 2 with size 0 means no flash (AS:1132-1133). Clamp
  to the slot's maximum (section 5.3).

## 2 The JLP as the CPU sees it

### 2.1 Address map (mode 1-3, features on)

| Address | What | Source |
|---|---|---|
| $8000-$803F | "JLP Flash command registers" (only $8023-$8026, $802D-$802F, $8033, $8034 are defined) | PV p.1, p.8, p.20 **[doc]** |
| $8040-$9F7F | 8,000 words of 16-bit RAM | PV p.2; JH:8 **[doc]** |
| $9F80-$9F8F | multiply / divide | PV p.8-9; JH:12-18 **[doc]** |
| $9F90-$9F97 | "Extended registers" | JH:19 only **[doc, no semantics]** |
| $9FFC, $9FFD | CRC-16 | PV p.11; JH:11 **[doc]** |
| $9FFE | random number | PV p.18; JH:10 **[doc]** |
| other $9F80-$9FFF | "JLP accelerator features" (range named, contents not) | PV p.2 **[doc]**; values read there **[unk]** (T1) |

Facts around the map:

- $8000-$803F is also the STIC's write alias (MM:132; REPO DESIGN 2.6, `intv_bus.sv:20-22`):
  every JLP register write also reaches a STIC register. The JLP's addresses alias STIC $23-$26,
  $2D-$2F, $33, $34, which the STIC does not use (it has $00-$21, $28-$2C, $30-$32: STIC_NOTES
  lines 39, 54-56) **[inf]**. Reads there are the cartridge's (only $x021 also reaches the STIC's
  mode latch, DESIGN 2.6). Nothing to do in the bus fabric.
- For 4K-word MCUs the RAM is only $9000-$9F7F (PV p.2). The core models the 8K part **[choice]**.
- JLP RAM "fully supports the GI bus protocol. All CP-1600 code will execute correctly from JLP
  RAM" (PV p.2): instruction fetches from it are ordinary cartridge reads **[doc]**.
- Paged ROM: the JLP uses ECS-style pages: "Reset selects page 0 in all segments", "a write to
  $xFFF with a value of the form $xA5y selects page y in segment $x000-$xFFF", 4K segments, a
  paged ROM answers only on its page (PV p.4-5) **[doc]**. This is what `intv_pagesel` does since
  step 8; it also settles DESIGN 13 q12 for JLP-style carts (4K, not 2K). IntyBASIC's 42K map with
  `--jlp` puts ROM at $2000-$2FFF and $7000-$7FFF on page $F (IB prologue:878-883), so it pages
  the ECS ROMs out by selecting $F, as PV p.7's example does **[inf]**.
- PV p.1-2: the JLP leaves $4000-$47FF to the ECS RAM, $2000 page 1, $7000 page 0, $E000 page 1 to
  the ECS ROMs **[doc]** (the step-9 ECS rules need no change).

### 2.2 Enable / disable ("special page-switch")

- Write **$6A7A to $8034**: "switch JLP RAM and accelerator features off". Write **$4A5A to
  $8033**: back on (PV p.8) **[doc]**.
- While off, ROM the cartridge maps in $8000-$9FFF answers instead ("you can access ROM in this
  address space if your program maps any ROM in this address range"; for old software with ROM in
  $8000-$9FFF and for the Keyboard Component's RAM at $8000-$BFFF; PV p.7-8) **[doc]**.
- While off, nothing of the JLP answers in $8000-$9FFF **[inf]** (the second-hand LUIGI sentence
  above). Whether the flash registers ($8023-$802F) also go away is **[unk]** (T8): mode 2 is
  "off at reset, flash present", and every flash command copies to or from JLP RAM (PV p.2),
  so flash is only usable after the program switches the RAM on, whichever way it is.
- The two control writes must work while off (or nothing could switch it back on) **[inf]**.
  Other values written to $8033/$8034, and $6A7A to $8033 or $4A5A to $8034, do nothing **[inf]**;
  whether the control addresses read back anything **[unk]** (T8).
- At reset: on for modes 1 and 3, off for mode 2 (AS:1127-1129) **[doc]**. Whether a console
  reset (the Reset button) puts the switch back to that value or keeps it: **[unk]**. jzIntv
  20200607 "Restore JLP accelerator enable state across reset" (RN 20200607:79) reads either way
  (T9). **[choice]**: set it from the mode at every machine reset, as at power-on; switch only if
  T9 says otherwise.
- With JLP on and a CFG that also declares RAM or ROM in $8040-$9F7F: PV p.4 calls `[memattr]
  $8040 - $9F7F = RAM 16` alongside JLP a conflict ("The two will conflict, eventually resulting
  in trouble"). **[choice]**: while the JLP is on, it answers its own addresses and the map table
  does not; while off, the map table does. IntyBASIC declares its JLP RAM with attributes "-RWBN"
  (`ORG $8040, $8040, "-RWBN"`, IB IntyBASIC.cpp:4420), i.e. no CFG entry.

### 2.3 Multiply / divide ($9F80-$9F8F)

PV p.8-9 (table) and JH:12-18 agree **[doc]**:

| Name | Operand 1 | Operand 2 | Operation | $9F8F | $9F8E |
|---|---|---|---|---|---|
| MPYSS | $9F80 | $9F81 | s16 x s16 -> s32 | product bits 31-16 | product bits 15-0 |
| MPYSU | $9F82 | $9F83 | s16 x u16 -> s32 | high | low |
| MPYUS | $9F84 | $9F85 | u16 x s16 -> s32 | high | low |
| MPYUU | $9F86 | $9F87 | u16 x u16 -> u32 | high | low |
| DIVSS | $9F88 | $9F89 | s16 / s16 | remainder | quotient |
| DIVUU | $9F8A | $9F8B | u16 / u16 | remainder | quotient |

Operand 1 is the multiplicand or the dividend (numerator), operand 2 the multiplier or the divisor
(PV p.10 "DIVUU.num $9F8A", "DIVUU.den $9F8B") **[doc]**.

- **Quotient in $9F8E, remainder in $9F8F**: PV's table, JH:17-18, and IntyBASIC (A/B reads
  $9F8E, A%B reads $9F8F: IB node.cpp:1057-1061, 1096-1100, 1585-1593, 1622-1630) **[doc]**.
  PV's own decimal example (p.10) labels them the other way round (`DIVUU.quo EQU $9F8F`,
  `DIVUU.rem EQU $9F8E`); with those labels the example would print quotients, so the example's
  labels are the slip **[inf]**. T4 confirms.
- "JLP computes a new result when *either* input operand changes. Furthermore, it holds the input
  operands and results indefinitely" (PV p.8) **[doc]**. So: twelve operand registers (each
  function keeps its own pair, "each command takes its input from a different pair of
  locations"), two result registers shared by all six; a write to any operand register recomputes
  that function with the other held operand and overwrites $9F8E/$9F8F **[inf]**. PV p.10-11
  writes the denominator once and then only the numerator, four times. Whether a write of the
  same value counts as a change does not matter (same result).
- Timing: the result is read by the very next instruction (`MVO R1,$9F81` then `MVI $9F8E,R2`, PV
  p.9-10; IB node.cpp:986-990). In the core that is at least three bus cycles (the MVI's two
  fetches come first), a few hundred clk_sys **[inf]**: an iterative 16-step divider fits easily.
- Not documented, **[unk]** (T3, T4): division by zero (both); DIVSS $8000 / $FFFF; rounding of
  signed division (truncation toward zero with the remainder taking the dividend's sign, as the
  PIC24H the JLP uses, PV p.8, would do, is the likely rule **[inf]**); whether the operand
  registers and results read back as written / whether writes to $9F8E/$9F8F do anything; what
  $9F8C/$9F8D hold. **[choice]** until T4: x / 0 gives quotient $FFFF and remainder = dividend
  (what a restoring divider gives); DIVSS $8000 / $FFFF gives quotient $8000, remainder 0;
  operand registers read back their last value; $9F8C/$9F8D and writes to $9F8E/$9F8F as
  unassigned. Note for x / 0: IntyBASIC without `--jlp` returns the dividend for A/0 (its
  software divide skips on a zero divisor, IB node.cpp:1598-1608), so a game may behave
  differently with and without JLP if it ever divides by zero.
- Atomicity: one shared result pair, so code must not use the unit from both the ISR and the main
  loop unprotected (PV p.9-10). Nothing for the core, except that the state (section 5) must hold
  all fourteen registers.

### 2.4 CRC-16 ($9FFC, $9FFD)

- "$9FFC: Write only. Write data to checksum to this location. $9FFD: Read-write. Write this
  location to initialize the checksum. Read this location to get the current checksum" (PV p.11)
  **[doc]**. Right-shifting, polynomial $AD52 (PV p.11; JH:11) **[doc]**.
- Exact function (PV p.18, Perl): a write of `d` to $9FFC does
  `crc ^= d; repeat 16: crc = (crc >> 1) ^ ($AD52 if crc & 1 else 0)` **[doc]**. PV p.16-17's
  table version agrees: its table entry i is the 8-step CRC of i XORed with i << 8 (checked here
  for entries 0-15 and 248-255 with a 10-line script; all equal) **[inf, checked]**.
- Vectors from that function (for the model's unit test): crc16($0000, $0001) = $EFCA;
  crc16($FFFF, $0000) = $5AB9; crc16($1234, $5678) = $2A3F. With data 0 the sequence from any
  non-zero seed has period 65,535 and 0 stays 0; data $5AA4 makes seed $0001 a fixed point,
  which is PV p.15's warning "Do not use $5AA4 as the fixed value" **[inf, checked]**.
- **[unk]** (T5): what a read of $9FFC returns; the CRC register's value at reset. **[choice]**:
  $9FFC reads as unassigned, CRC = 0 at reset.

### 2.5 Random number ($9FFE)

- Read only. "JLP will return the current random number state as a 16-bit number. JLP will also
  scramble the random number with a CRC after the read, so that two consecutive reads return
  different numbers." The state mixes in what the MCU sees on the bus, at least 40x the CPU's
  clock, so it is non-deterministic (PV p.18-19) **[doc]**.
- **[choice]**: the core must be deterministic (save-state round trips, model-vs-RTL gates), so:
  16-bit state; a read returns it, then state := crc16(state, T), T = the low 16 bits of a CPU
  cycle counter (free-running from machine reset, in the state). Human input timing still
  varies T between runs, which is where the real JLP gets most of its entropy (PV p.18 "JLP will
  observe every user input"). State at reset: 0 is a fixed point of crc16(·, 0), so seed it
  non-zero ($FFFF), or rely on T. A write to $9FFE: **[unk]** (T6), treated as unassigned.

### 2.6 Flash save-game ($8023-$802F)

Geometry (PV p.19-20) **[doc]**: a **row** is 96 16-bit words (192 bytes), the unit of read and
write; a **sector** is 8 rows (768 words, 1,536 bytes = the "1.5K" of AS/IT), the unit of erase.
Capacity is always whole sectors; the first row number is a multiple of 8, the last is one less
than a multiple of 8.

| Address | Name | Access | Meaning |
|---|---|---|---|
| $8023 | JF.first | read | first valid row number |
| $8024 | JF.last | read | last valid row number |
| $8025 | JF.addr | write | JLP RAM address to copy to or from |
| $8026 | JF.row | write | flash row to operate on |
| $802D | JF.wrcmd | write $C0DE | copy 96 words of JLP RAM at JF.addr to row JF.row |
| $802E | JF.rdcmd | write $DEC0 | copy row JF.row to 96 words of JLP RAM at JF.addr |
| $802F | JF.ercmd | write $BEEF | erase the sector that holds row JF.row (all 8 rows) |

(PV p.20; the same constants in IB epilogue:2876-2890) **[doc]**

Command rules (PV p.24-25) **[doc]**:

- Read: "JLP drops the command if: the row number is out of range ... One or more RAM addresses
  fall outside the JLP RAM range." "Empty rows of flash read as $FFFF." Real time: "a few
  Intellivision CPU instruction cycles".
- Write: dropped if "the requested row of flash is not empty", the row is out of range, or a RAM
  address is outside JLP RAM. Up to 1.8 ms.
- Erase: the whole sector holding JF.row; dropped if the row is out of range. Up to 28 ms.
- In range: JF.first <= row <= JF.last; RAM in range: $8040 <= addr and addr + 95 <= $9F7F
  **[inf]** from the wording.
- "Not empty" = some word of the row is not $FFFF **[inf]** (T10e).
- A key other than the one listed is ignored **[inf]** ("Must write the value", PV p.20).
- JF.first, JF.last: on a real JLP they depend on the program's size and the MCU (PV p.20); in an
  emulator the value is the implementer's. IntyBASIC reads them at run time (FLASH.FIRST,
  FLASH.LAST: IB node.cpp:577-580) and the guide's reference code takes its base from JF.first
  (PV p.28), so programs do not assume a value **[inf]**. **[choice]**: JF.first = whatever jzIntv
  gives (T10a; jzIntv's save file is then the same rows), else 0; JF.last = JF.first + 8 x
  sectors - 1. With no flash (mode 1, or size 0): **[unk]** (T10a, T14); choice: $8023-$802F
  read as unassigned and writes do nothing.
- Reads of the write-only registers and of the command registers: **[unk]**, but see the next
  point for the command registers.

**Busy and the wait loop.** "JLP flash operations can take up to 28ms to complete. During the JLP
flash operation, JLP's MCU stalls execution, and JLP ceases responding to the Intellivision" (PV
p.20) **[doc]**. Hence the program issues the command and waits from System RAM, with the stack and
an ISR in System RAM, and must not touch JLP RAM or ROM meanwhile (PV p.20-21) **[doc]**. The
reference routine, copied into System RAM by JF.INIT (PV p.22; identical in IB epilogue:2893-2911):

```
JF.SYSRAM+0:  MVO@ R0, R1    ; R1 = command register, R0 = key: start
JF.SYSRAM+1:  ADD@ R1, PC    ; read the command register, add it to PC
JF.SYSRAM+2:  JR   R5        ; return
JF.SYSRAM+3:  MVO@ R2, R2    ; ISR: R2 = $20, the STIC handshake
JF.SYSRAM+4:  JR   R5
```

When `ADD@ R1, PC` executes, PC already points at +2: a read of $FFFF (nobody answers, the bus's
pull-ups, DESIGN 2.5) adds -1 and loops on the ADD; a read of 0 falls through to the return. So
**after the command completes, a read of the command register must give 0**, and while busy it
must give $FFFF **[inf]** (any other value would jump elsewhere). The core's choice must keep this
loop working. The ISR keeps the display enabled during the wait (`MVO@ R2,R2` writes to $0020) and
returns through the EXEC's dispatcher, which runs from the EXEC ROM; JF.CMD swaps the vector at
$0100/$0101 around the call (PV p.23-24) **[doc]**. The IntyBASIC manual still warns that the
screen goes black and music stops for a few milliseconds (IB manual.txt:1408-1410) **[doc]**
(why, with the handshake kept, is not explained: IntyBASIC's own ISR, which updates the picture
and music, is not running).

**[choice]** for the core: a flash command makes the JLP busy for exactly as long as the core's
copy engine works (96 SRAM reads or writes, or a 768-word erase of the flash store: a few hundred
to a few thousand clk_sys, well under a frame). While busy the whole cartridge port answers
nothing ($FFFF, as on the real board, where the MCU also serves the ROM) and drops writes; after
it, $802D-$802F read 0. A modelled delay (1.8 ms / 28 ms) is possible later if a game is found to
depend on it; T11 measures jzIntv and the PiRTO.

**How data persists.** Flash is a nonvolatile store outside the machine (DESIGN risk 7): only the
three commands change it.

**Wear and versioning** (PV p.25-31) are the program's business: the guide's FL_LOAD / FL_SAVE
write round robin over 32 rows from JF.first with a two-word version, erasing a sector when the
next row is a sector's first. Nothing for the core, but it explains save-state hazard 5.2.

## 3 What software uses

IntyBASIC is the main source of JLP programs (LTO lists Christmas Carol vs. the Ghost of Christmas
Presents as using flash if possible and The Lost Caves of Kroz as requiring it: LTO page).

| Feature | IntyBASIC (`--jlp`) | Evidence |
|---|---|---|
| RAM $8040-$9F7F | yes: 16-bit variables and arrays (7,962 words free), cleared at start ($1F40 words from $8040) | IB manual.txt:313-316, 1976; prologue:1576-1580; IntyBASIC.cpp:4142-4150, 4418-4421, 4484-4485 |
| MPYUU, low word only | yes: A*B for variables, and for constants >= 128 or slow ones; reads $9F8E only | IB node.cpp:986-990, 1261-1265, 1556-1559 |
| DIVUU | yes: A/B reads $9F8E, A%B reads $9F8F; constant divisors too | IB node.cpp:1057-1061, 1096-1100, 1292-1296, 1313-1317, 1585-1593, 1622-1630 |
| MPYSS/SU/US, DIVSS, $9F8F after a multiply | no | (no other $9F8x addresses in IB) |
| CRC-16, random $9FFE, extended registers | no (RANDOM is IntyBASIC's own generator, IB epilogue:529-580) | grep of IB sources |
| enable/disable $8033/$8034 | no; it emits `jlp = 1`, or `jlp = 3` with FLASH (IB IntyBASIC.cpp:4203-4206; fixed in 1.4.2, manual.txt:45) | |
| flash | FLASH INIT / READ / WRITE / ERASE (JF.INIT, JF.CMD from the guide), FLASH.FIRST/LAST | IB manual.txt:1358-1410, 1804-1808; epilogue:2871-2962; samples/flash.bas |
| ECS-style pages | page $F at $2000 and $7000 in map 2 | IB prologue:870-883 |

Also: IntyBASIC does not cache reads of $9F8E/$9F8F (IB code.cpp:560), so any register can be read
right after the write; the compiler's test line is `jzintv --jlp` (manual.txt:431) and flash wants
`--jlp-savegame=file` (manual.txt:1406). Assembly programs (SDK-1600 `cart.mac`) get the RAM through
the CARTRAM macro (PV p.3).

So the minimum that runs IntyBASIC JLP games: RAM, MPYUU, DIVUU, the flash interface, the mode bits,
and the page selects that already exist. The signed functions, CRC, random number and the
enable switch are documented and cheap, and are what the guide's own examples and jzIntv's JLP
test use (T0): build them too. The extended registers wait for a source.

## 4 Black-box test plan

Two references, both black boxes: jzIntv 20200712 (the binary built at
`daria_work/intv/refs/jzintv/src-tree/jzintv-20200712-src/bin/jzintv`, with `--jlp` and
`--jlp-savegame=FILE`; as1600 next to it), and the owner's PiRTO II with Minty firmware (Minty
adds JLP from 2.4, sector erase and reset fixes in 2.5, OD:491; its code is not read and it is
itself an emulation of the JLP, so a third implementation, not ground truth). Where the three
disagree, PV decides (OD:491).

Programs are ours (BIN+CFG, CFG `[vars] jlp = 3`, `jlp_flash = 4` unless said; 8-character file
names for the PiRTO as in `hwtests/out_owner/pirto83`), print hex results on the screen, and run
from ROM except where flash commands need System RAM. On jzIntv the screen or a debugger memory
dump is read; on the PiRTO a phone photo. Not run yet (no emulator slots while the release gate
runs).

| Test | Program | Observe | Settles |
|---|---|---|---|
| T0 | jzIntv's own "JLP Feature Test" (`src/jlp/jlp_test.asm`) and `jlp_rand_stats.asm`, assembled locally with as1600, never committed, code not read (OD:491) | its screens on jzIntv; later the core in simulation must show the same | overall agreement |
| T1 JLPMAP | read every word of $8000-$803F and $9F80-$9FFF after reset, mode 3 | the table of values | unassigned addresses ($FFFF? 0?), read-back of $8025/$8026/$802D-$802F/$8033/$8034, $9F8C/$9F8D, $9FFC |
| T2 JLPRAM | write/read $803F, $8040, $9F7F, $9F80 with $A5C3, $FFFF, $0000; then reset (Reset button) and read $8040-$804F again | RAM bounds; whether RAM survives a console reset; its power-on content (first run after power-up / emulator start) | 2.1, reset |
| T3 JLPMUL | each MPY with ($7FFF,$7FFF), ($8000,$8000), ($FFFF,$FFFF), ($8000,$FFFF), (3,-5); then write only operand 1 again with a new value; read $9F80-$9F87 back; write $1234 to $9F8E and read it | $9F8E/$9F8F; recompute on one operand; operand read-back; result writes | 2.3 |
| T4 JLPDIV | DIVUU and DIVSS: (100,7), (-100,7), (100,-7), (-100,-7), ($8000,$FFFF), (5,0), (0,0), ($FFFF,0) | quotient/remainder placement and signs, x/0, overflow | 2.3 [unk] |
| T5 JLPCRC | read $9FFD after reset; write seed $FFFF to $9FFD, data $0000, $0001, $1234 to $9FFC, read $9FFD after each; read $9FFC | match the Perl function (2.4 vectors); reset value; $9FFC read | 2.4 |
| T6 JLPRND | read $9FFE 8 times in a row, and once per frame for 60 frames; run twice from power-up with no input; write to $9FFE | values change per read; whether jzIntv is deterministic run to run; write effect | 2.5 |
| T7 JLPEXT | read $9F90-$9F97 after reset; write $1111 x n, read back; check nothing else changes (screen, $9F8E) | what the "extended registers" are | 2.1 [unk] |
| T8 JLPENA | with a CFG that also maps ROM over $8000-$9FFF (a known pattern): $6A7A -> $8034, read $8023, $8040, $9F8E, $9FFE, the ROM pattern; write RAM; $4A5A -> $8033 and re-read (did the RAM keep its data?); also wrong keys ($6A7B -> $8034, $4A5A -> $8034); modes 1 and 2 | scope of the switch (RAM, accel, flash registers); ROM underneath; RAM kept while off | 2.2 |
| T9 JLPRST | mode 2: read $8040 (off?), switch on, press Reset, read again; mode 3: switch off, Reset, read | enable after a console reset | 2.2 reset |
| T10 JLPFLS | (a) JF.first/JF.last for `jlp_flash` = 1, 4, 16, and absent with mode 3; mode 1 / `jlp_flash = 0`; (b) `jlpflash = 16` (IntyBASIC's spelling); (c) read an empty row; (d) write a row with a counter pattern, read back to another RAM address; (e) write the same row again with other data (dropped?), then a row of $FFFF words (counts as empty after?); (f) erase through the 3rd row of a sector (all 8 erased? neighbours kept?); (g) out-of-range row and RAM address $9F40 (96 words pass $9F7F); (h) quit and restart: persistence; hexdump the `--jlp-savegame` file | (a)-(g) the command rules of 2.6; (h) jzIntv's save file: size per sector, byte order, erased value, header or none, where row JF.first sits | 2.6, 5.3 |
| T11 JLPBSY | own wait loop in System RAM: issue erase / write / read, then count loop passes until $802F (resp. $802D, $802E) reads non-$FFFF; record the count and the value; also read a ROM word in the loop | busy length; the value read when done (0?); ROM gone while busy | 2.6 busy |
| T12 | IntyBASIC `samples/flash.bas` compiled with `--jlp`, run on jzIntv, PiRTO, then the core | end to end, and a Pocket sleep / quit with the .sav kept | step 11 gate |

T10 and T11 on the PiRTO also answer whether Minty keeps flash across power cycles (its own
storage) and how long it stalls; on the Pocket the same programs (in simulation, then hardware)
answer 5.3's open points.

### 4.1 Results on jzIntv (2026-10-30)

The eleven programs of `sim/testroms/jlp` (`build_jlp.py build`; T1-T10 above, T9 and the
reset parts of T2 need the Reset button and wait for the PiRTO), each run on jzIntv 20200712 as a
black box (`tools/refs/jzintv_jlp_run.sh`, `build_jlp.py compare`). jzIntv's author designed the
JLP, so where the guide is silent its behaviour is the best evidence short of the board. Found,
and taken into `tools/jlp.py`:

| Point | jzIntv | Was (choice in section 2) |
|---|---|---|
| x / 0 (DIVUU, DIVSS) | both results keep their values (the write that makes the divisor 0 does not recompute) | quotient $FFFF, remainder the dividend |
| DIVSS signs, $8000 / $FFFF, quotient / remainder places | truncation toward zero, remainder with the dividend's sign; $8000 r 0; quotient $9F8E, remainder $9F8F | the same (confirmed) |
| $9F8C, $9F8D, $9FFF | read 0 | unassigned ($FFFF) |
| $9F8E, $9F8F | writable: a write is read back (until the next operand write) | unassigned writes |
| $9F90-$9F97 ("extended registers") | eight words, 0 at reset, read back as written, nothing else changes | unknown |
| $9FFC, $9FF0, $8025, $8026, $8033, $8034, $803F, $8000 | $FFFF (nobody answers) | the same |
| $802D-$802F when idle | 0 | the same (the wait loop's rule) |
| CRC at reset | $FFFF | 0 |
| JF.first | $00E0; JF.last = $E0 + 8 x sectors - 1 ($E7 for 1 sector, $FF for 4, $15F for 16) | 0 |
| no flash (`jlp = 1`, `jlp_flash = 0`) | $8023 / $8024 read 0 | not answered |
| `jlp_flash` absent with `jlp = 3` | 4 sectors | the same |
| `jlpflash` (IntyBASIC) | taken as the size (16 sectors) | the same (choice) |
| flash rules | an empty row reads $FFFF; a write to a row not empty is dropped; erase clears the whole sector of JF.row, not the next; rows outside JF.first-JF.last, RAM past $9F7F and a wrong key are dropped | the same (confirmed) |
| switched off | RAM, accelerators and the flash registers all go; the map's ROM answers; the RAM keeps its data; writes to the ROM do nothing; wrong keys and swapped keys do nothing | the same (confirmed) |

jzIntv's flash file (`--jlp-savegame`, T10h): no header; the rows in order from JF.first, 192
bytes a row, each word **little-endian** (row 8 of JLPFLS's \$3000 pattern starts `00 30 01 30`
at byte \$600), erased words \$FFFF; 1,536 bytes a sector (6,144 for 4 sectors, 24,576 for 16); not
written when the cartridge has no flash. The core's slot 0x106 takes the same layout, so a save
moves between jzIntv and the Pocket unchanged.

Known differences, kept on purpose (`build_jlp.py compare` lists them apart):

- **Busy time.** jzIntv stalls about as the guide says (polls of the wait loop, about 31 cycles
  each: a read about 11-30, a write about 400-580, an erase about 840) and stalls on dropped reads
  too. The core is busy only while its copy engine works (BUSY, a few hundred cycles). A program
  can only wait for the command register, so a shorter wait is harmless.
- **Random numbers.** jzIntv's differ run to run; the core's are deterministic (save states,
  benches).
- **Mode 2 at reset.** as1600.txt (AS:1127-1129) says off; jzIntv starts it on. The core
  follows the document until the PiRTO II with Minty, the third implementation, is measured
  (JLPENA's first five results).

## 5 Save states, nonvolatile data, cost

### 5.1 In the save state (module id $20, reserved: SAVESTATE.md 3, `intv_ss_pkg.sv:28`)

| Item | Words |
|---|---|
| mode (2 bits), enable (1), busy flag and engine counters if a freeze can see them | 1-2 |
| MPY/DIV operand registers ($9F80-$9F8B) | 12 |
| results $9F8E, $9F8F | 2 |
| CRC register | 1 |
| random state, cycle counter low word | 2 |
| JF.addr, JF.row | 2 |
| extended registers (if they turn out to be storage) | 0-8 |
| **Total** | about 20-30 words, inside DESIGN 4.4's 128 bytes |

- JLP RAM: 8,000 words in SRAM $1C000-$1DF3F (`intv_media.sv:19`, CARTFORMATS 4), read by
  `ss_ctl` while frozen (DESIGN 4.3); 16,000 of the blob's reserved 16,384 bytes (DESIGN 4.4,
  13 q21). The blob version goes up (SAVESTATE.md 4 already expects this).
- The enable switch is run-time state and is in the list (answers DESIGN 13 q18).
- Freeze: never while a flash command runs; with the copy-engine busy model that wait is at most a
  few thousand clk_sys (DESIGN 13 q17's proposal).
- JF.first/last, the sector count and the mode come from the load, not the state, but the state
  header's CFG CRC32 already ties a state to its CFG (DESIGN 4.4, version 2).

### 5.2 Flash is outside the state

DESIGN risk 7: a state load does not roll back flash. Consequence to document for users: a game
that keeps its idea of flash in RAM (the guide's FL_INFO "next row" and version, PV p.27-30) can,
after loading an older state, try to write a row it already wrote after that state was made; the
JLP drops writes to non-empty rows (PV p.24), so that save is silently lost, and the next FL_SAVE
that reaches a sector start erases newer rows. Loading the game normally (FL_LOAD rescans) is safe.
Same on any emulator with states and a separate flash file **[inf]**; nothing in the core can
fix it without putting flash in the state, which DESIGN rejects.

### 5.3 The nonvolatile slot (0x106)

- Now: `data.json` slot 0x106 "JLP flash", nonvolatile, parameters 0x84, `size_maximum` 0x10000,
  bridge address 0x20000000; `apf_datatable` reports its size as 0 (`core_top.v:389, 443-444,
  640-657`; `apf_datatable.sv:7, 140, 172-173`; `apf_json_check.py:405-412`).
- Size **[choice]**: sectors x 1,536 bytes, written to the data table so the Pocket saves exactly
  that (DESIGN 13 q17). 0x10000 allows 42 sectors (64,512 bytes); larger requests are clamped
  (IT's field reaches 1,023 sectors; no known title needs more than IntyBASIC's 16).
- Layout **[choice]**: rows in order from JF.first, 192 bytes each, words big-endian (as the
  bridge and the other slots). If T10h shows jzIntv's file is the same rows with no header,
  match its byte order and erased value so files move between the two.
- Erased state: a game's first run has no file. **[unk]** whether the Pocket hands the core a
  zero-filled file, none at all, or the previous game's data (Pocket test). The core must start
  from all-$FFFF (erased) when nothing is loaded **[choice]**: clear the store to $FFFF at
  load, before the bridge writes the file. If the Pocket always delivers a zero-filled file of
  the reported size, store words inverted (file = NOT flash) so zeros mean erased; that breaks
  file compatibility with jzIntv, so decide after T10h and the Pocket test.
- When the Pocket writes the file back (quit, sleep, both?) and whether the core must say "dirty":
  **[unk]**, DESIGN 13 q17; the 7800 core's nonvolatile handling is the model to copy.
- Where the store lives: the SRAM is full (plane 1 64K, ECS ROM 12K, state staging 20K, cart RAM
  16K, JLP RAM 8K, pool 8K: `intv_media.sv:10-23`). Options: (a) block RAM: 4 sectors = 3,072
  words = 6 M10K, 16 sectors = 24, 42 sectors = 32,256 words = 64 M10K (512 x 20 mode); (b) the
  Pocket's PSRAM, unused so far (SAVESTATE.md 4), for a controller of about 200-400 ALMs and no
  M10K; (c) a slice of the cartridge RAM area when the image declares none (JLP games normally
  do not), but that area is in the save state, so it would need an exclusion. **[choice]**
  pending the owner: (a) with a 16-sector cap (24 M10K; the device has 308, the core uses 54),
  raising it later through (b) if a title needs more.

### 5.4 Cost estimate [estimated]

| Part | ALMs | M10K / DSP |
|---|---|---|
| decode ($8000-$803F, $9F80-$9FFF), enable, mode, read mux | 40-60 | |
| multiplier: 17 x 17 signed (sign-extend by mode), one DSP | 20-30 | 1 DSP |
| divider: 16-step restoring, signed by pre/post negation | 60-90 | |
| CRC: 16 steps unrolled (or 1 step per clk_sys, about 20) | 40-80 | |
| random state and cycle counter | 30-40 | |
| flash engine (row copy, erase, range checks, busy) | 80-120 | |
| JLP RAM port into `intv_media`'s SRAM arbiter | 20-40 | |
| state taps, about 25 words (step-7 rule: read-back costs as much as the flip-flops) | 120-180 | |
| **Total** | **about 410-640** | flash store 6-64 M10K (or 0 with PSRAM, +200-400 ALMs) |

DESIGN 3 (module 15) estimated 300-600 and DESIGN 4.5 about 150 for the taps; this is the same
order. Timing: the divider and CRC are multi-cycle inside the 96 clk_sys of a bus cycle, so no new
critical path is expected.

## 6 The JLP test ROM

No built JLP test ROM (.rom/.bin/.int) exists in the downloads. The jzIntv 20200712 distribution
has the **source** of jzIntv's "JLP Feature Test" and a random-number statistics program:

- `research/datasheets-licences/downloads/jzintv_src/x/jzintv-20200712-src/src/jlp/jlp_test.asm`
- `research/datasheets-licences/downloads/jzintv_src/x/jzintv-20200712-src/src/jlp/jlp_rand_stats.asm`

(identical copies under `daria_work/intv/refs/jzintv/src-tree/jzintv-20200712-src/src/jlp/`).
Not opened here (jzIntv source outside the jlp.c header); OD:491 already plans to assemble both
locally with as1600 and run them as black boxes (T0), never committing them. The distribution's
`rom/` holds only a README.

Also present and not opened (jzIntv example code, GPL-2; whether reading them is allowed is the
owner's call): `examples/library/jlp_accel.asm`, `examples/library/jlp_savegame.asm`,
`examples/jlpserial/jlpserial.asm`, `examples/jlpserial/jlp_loopback.asm`. The last two suggest
the JLP serial port that LTO lists for JLP hardware version 4 (LTO page); the extended registers
at $9F90-$9F97 may belong to it **[unk]**.

## 7 Open points, in order of importance

1. Flash store location and the nonvolatile file's erased value and layout (5.3), and the Pocket's
   behaviour with a missing file and on sleep (Pocket test).
2. Division by zero, signed division rounding and overflow (T4).
3. Scope of the enable switch and its value after a console reset (T8, T9).
4. JF.first and the save-file format, for jzIntv compatibility (T10a, T10h).
5. Busy behaviour seen by the CPU: value of the command registers when idle, ROM while busy (T11).
6. The extended registers $9F90-$9F97 (T7, or a document).
7. Unassigned addresses in $8000-$803F and $9F80-$9FFF, operand read-back (T1, T3).
