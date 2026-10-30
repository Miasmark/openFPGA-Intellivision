# The Intellivoice (build step 10)

The Intellivoice as this core will have it: the module, the SPB640 speech buffer, the SP0256-012
speech processor, where each fact comes from, where the sources disagree, how the model is held
to MAME, and the plan for the RTL. The golden model is `tools/sp0256.py`; the RTL comes in the
next pass (section 8).

Sources (codes as in DESIGN.md 12, all read for facts, no code taken):

| Code | Source |
|---|---|
| G81 | GI, SP-0256 Design Objective Specification, rev. C, Nov 1981 (DESIGN S6): sheets 6-7 the coefficient table, sheet 12 the excitation registers, the "DAC Output" and "LRQ" passages |
| IS | J. Zbiciak and F. Palazzolo, SP0256 Instruction Set, rev. 23-Sep-2000 (DESIGN S7, reverse engineered): opcodes, data formats by MODE, bit order |
| AL2 | Radio Shack / GI SP0256-AL2 technical data, 1984 (DESIGN S8): p.1 features, Table 5-6 allophone durations |
| S2 | GI 1982 Microelectronics Data Catalog: the SPR016/032/128 speech ROM pages ("1.56MHz clock input from SP0256") |
| SM | Mattel Intellivoice Service Manual, Model 3330 (DESIGN 14; `research/intellivoice-manual/REPORT.md`): p.3 technical description, schematic, parts list, troubleshooting |
| wiki | wiki.intellivision.us: Intellivoice, SPB640, SP0256-012, SP0256_Resident_ROM, SP0256_Page_Prefix, SP0256_Program_Counter |
| M | MAME (the owner's fork, DESIGN 12, BSD-3): `devices/sound/sp0256.cpp` (cited as sp0256:line), `bus/intv/voice.cpp`, `mame/mattel/intv.cpp`, `emu/sound.cpp` |
| meas | measured here with the model or MAME runs (section 6); the BIOS and game data stay outside the repository |

## 1 The module

- A cartridge-slot module that passes the cartridge bus through unchanged; the game plugs into
  it (SM p.3). Chips: U1 74LS12, U2 **SPB640** speech buffer, U3 **SP0256-012** (the SP0256 with
  Mattel's 2 KiB resident ROM), U4 LM324, U5 LM358, Y1 **3.12 MHz** ceramic resonator (SM parts
  list; troubleshooting: 3.12 MHz at TP9/TP10).
- Bus map (M intv.cpp:308 for the Intellivoice, :363 for MAME's ECS machine, which has the
  SP0256 built in; wiki Intellivoice):

| Access | Meaning |
|---|---|
| read `$0080` | bit 15 = LRQ: 1 when the SP0256 will take a new command (the last one was picked up); other bits 0 (sp0256:1189) |
| read `$0081` | bit 15 = 1 when the FIFO holds 64 decles (full); other bits 0 |
| write `$0080` | ALD: the low 8 bits are a command. Ignored while LRQ = 0; else LRQ := 0 and the command waits (sp0256:1153-1176) |
| write `$0081` | bit 10 set: reset the FIFO and the SP0256 (sp0256:1211-1222); else push the 10 low bits into the FIFO, dropped when it is full (sp0256:1224-1242) |

- **SPB640**: a "10 BIT x 64 FIFO" with an address trap and enable, and a serial link to the
  SP0256 (C1-C3, the ROM clock, SER IN/OUT) (SM schematic). For the CPU it is the two words
  above.
- **The FIFO path**: command 0 runs the resident ROM's entry at `$1000`, which ends in a jump to
  byte `$1800`, the SPB640 (wiki SP0256_Resident_ROM: "Execute from SPB640 Speech FIFO"; M
  FIFO_ADDR). While the program counter is `$1800` the sequencer reads its bits from the FIFO,
  10 per decle, LSB first (sp0256:738-760). The PC does not move while it does; a jump or return
  to `$1800` drops the rest of a decle that was half read (sp0256:986-1001).
- **LRQ**: G81 "LRQ": the rising edge of ALD makes LRQ go low, "where it will remain until the
  internal IBF flag is reset by a RET instruction". M: the command is taken when the sequencer
  is halted (an RTS with an empty stack) and its repeat count has run out (sp0256:817-826), which
  sets LRQ again. So a command written during a phrase waits for the phrase's end, and a second
  command written meanwhile is lost: games poll LRQ before each write (meas: every title).
- **Commands** (wiki SP0256_Resident_ROM): 0 the FIFO, 1-5 pauses, 6 "Mattel Electronics
  Presents", 7-36 numbers, 37-42 "-teen", "-ty", "Press", "Enter", "Or", "And". The test
  program (section 7) plays all 42.

## 2 The SP0256

### 2.1 Micro-sequencer

Registers (IS "Registers", M): a 16-bit bit-address PC (with a page prefix: 19 bits in M), a
one-deep stack, a 4-bit PAGE, the 2-bit MODE and 2-bit repeat prefix, and the filter's 16
parameter registers (amplitude A, pitch P, B0/F0 ... B5/F5, interpolation AI and PI).

- **Bit order** (IS p.2): every field is read LSB first from the byte stream; the opcode nibble
  and the branch fields come out bit-reversed with respect to IS's notation, which writes them
  MSB first. The resident ROM is read as dumped, byte by byte LSB first: M's header says it flips
  every byte at start-up, but that call is commented out (sp0256:13-20, :113).
- **Instruction**: 4 bits immediate, then 4 bits opcode (IS notation below), then data.

| IS opcode | Name | What it does (IS; M micro, sp0256:799-1148) |
|---|---|---|
| 0000, imm 0 | RTS | PC := stack, stack := 0; an empty stack halts (PC := 0) |
| 0000, imm != 0 | SETPAGE | PAGE := imm reversed; the page is bits 15-18 of JMP/JSR targets |
| 0111 | JMP | then 8 bits: target = PAGE \| rev(imm) << 11 \| rev(byte) << 3 (a byte address) |
| 1011 | JSR | as JMP; stack := (PC + 7) & ~7 (the next byte) |
| 1000 | SETMODE | imm bits 2-3 = MODE (IS "MM"), bits 0-1 = repeat prefix (the repeat's bits 4-5) |
| others | data | repeat := imm \| prefix; if 0, no data and no effect (IS p.3, sp0256:1012); else the filter runs repeat periods with the new parameters (`rpt = repeat + 1`, the first excitation counts one) |

  MODE is sticky; the repeat prefix lasts one instruction: M clears it after every opcode but
  SETMODE (sp0256:972). The data formats per opcode and MODE are IS's tables; the model writes
  them once (`FORMATS`) and they equal M's table field for field (meas: `fmtcmp`, section 6.5):
  value loads, MSB-field replaces (SETMSB_*: the low bits are kept), and delta updates (DELTA_*:
  sign-extended, added at the field's position). Fields narrower than their register are MSB
  justified; a B coefficient without its sign bit sits one bit lower. Clear-all (the LOAD_*
  family and PAUSE) zeroes the 16 registers first; the SETMSB_* family zeroes B5/F5 in MODE 00
  and 10. PAUSE also sets P := 64, which makes 64-sample silent periods (sp0256:1133-1137).
- **Resident ROM**: 2 KiB at byte `$1000` (M voice.cpp:87, CRC 0de7579d); everything above it
  reads 0 (an RTS: a stray jump halts).

### 2.2 Filter and excitation

Per sample (G81 sheet 12; M lpc12 update, sp0256:197-312):

- **Excitation.** P > 0: an impulse of height `amp` every P samples, zero between. P = 0: noise,
  ±amp from a 15-bit LFSR (`rng = rng >> 1 ^ (bit ? $4001 : 0)`, seed 1 at reset, sp0256:243),
  with the repeat counted in periods of 64 samples (G81: "64 times R samples"). The repeat count
  drops by one at each period start; when it runs out there, that step's sample is not made: the
  sequencer runs and the sample is made again with the new parameters (sp0256:264).
- **Amplitude**: `amp = (A & 31) << (A >> 5)` (G81: "5 bits of mantissa and 3 bits of exponent";
  sp0256:256).
- **Interpolation**: at each period start, A += AI and P += PI (8-bit wrap), amp and P are
  decoded again (G81 sheet 12; IS LOADALL notes "Wraparound may occur"). Only when AI or PI was
  non-zero at the last load (M `interp`).
- **Coefficients**: an 8-bit register x is multiplied as `-T(x)` through G81's table T(X) x 512
  (sheets 6-7, 128 entries, the same numbers as M's qtbl). A negative register is taken as two's
  complement (M `qtbl[0x7F & -x]`): section 5 row 3.
- **Six 2-pole stages** in series, 16-bit information lines (G81 sheet 6): `s += B·z1 >> 9;
  s += F·z0 >> 8; z1 := z0; z0 := s`, wrapping at 16 bits (M keeps `samp` in 16 bits). The delay
  line is cleared at every impulse and every noise period start (sp0256:219-238; M only).
- **Output**: M HIGH_QUALITY: the sample clipped to -8192..8191, x 4 (sp0256:182-192, :304). The
  chip drives "an internal 7 bit pulse width modulation" DAC (G81 "DAC Output"): section 5 row 5.
- **Idle**: a halted sequencer sets the repeat to 1 and clears the registers but does not decode
  them (sp0256:832-843): it polls for a command once a period (64 samples with P = 0) and its
  output is silence (A = 0 after the next period start).

## 3 Sample rate, output filter, mix level

- **Rate: 10 kHz on the chip.** 3.12 MHz (SM Y1) / 312. Evidence: AL2 p.1 "flat frequency
  response ranging from 0 to 5 kHz" (Nyquist at 10 kHz); G81 "DAC Output": PWM noise "at or above
  10KHz", low-passed "to 5KHz"; the ROM clock is half the resonator, 1.56 MHz (S2 SPR016:
  "1.56MHz clock input from SP0256"); and the resident ROM's five pauses (commands 1-5) last
  10,011, 5,006, 2,016, 976 and 456 samples (meas): 1.0 s, 0.5 s, 0.2 s, 0.1 s and 0.05 s at
  10 kHz, the AL2's pause scheme (PA1-PA5, AL2 Table 6). MAME runs it at 9,285 Hz (row 1).
  **Measured** (the owner's real-console recordings, 2026-10-29; YouTube e7XtAR26F6k B-17
  Bomber, DhR_elQIojM TRON Solar Sailer twice, M6hnDS-zVAU Bomb Squad twice; the analysis and
  the files in the planning folder's research/voice-rec/): the chip's exact sample stream for
  each title phrase (the model = MAME's samples) played at every rate from 9,000 to 10,600 Hz,
  its 5 ms log envelope correlated with the recording's at the best offset: every take peaks
  between 9,950 and 10,500 Hz (B-17 0.622 at 10,000-10,050; TRON 0.729 at 10,100; Bomb Squad
  0.738 at 10,050), and MAME's rate scores far lower (B-17 0.33, TRON 0.49, Bomb Squad 0.55).
  The rate is settled: 10 kHz.
- **Power-on pop** (meas, the TRON recording): one transient at power-on (17.5 times the median
  5 ms step, decaying in about 20 ms) before the first phrase only: the module's analog output
  (its coupling capacitors) settling. The core's output starts at 0 and has none, on purpose.
- **Analog chain** (SM p.3 and schematic): PWM → C3 high-pass (~150 Hz) → two LM324 active
  low-passes (above 5 kHz) → C8 low-pass ("hash") → volume R22 (200K thumbwheel) → U5A buffer with
  C14 low-pass (above 5 kHz) → C9 + R25 high-pass (150 Hz; 430 Ω) → J1 pin 6, EXT AUDIO, into the
  console's sound, "heard through the TV set" (SM troubleshooting). Values: C3-C8, C14 4,700 pF;
  R11/R16 16K, R12 3.9K, R13/R15/R18/R20 8.2K, R14 6.34K, R17 12K, R19 3.83K (SM parts list).
- **Level**: the thumbwheel sets voice loudness only; game sounds keep the TV's volume (SM p.2-3).
  So there is no fixed ratio to the PSG; MAME says the same ("relative volumes to use are
  subjective", voice.cpp:77) and puts the voice on its own speaker at 1.0 against the PSG's 0.33
  (voice.cpp:74-78, intv.cpp:473). The core gives it a menu level (section 8.5).

## 4 MAME's timing, as the references see it

- Stream rule (M sound.cpp:582-608): a register access at machine time t first brings the stream
  up to sample `floor(t x rate)` inclusive, then acts. So an access lands before the next sample.
- MAME's rate is 3,120,000 / 336 = 9,285 Hz (integer division, sp0256:34, :75).
- The sequencer runs lazily inside the stream update (sp0256:1262-1330), with the same order as
  the model's `step()`: a repeat that runs out runs the sequencer before the sample is made.
- Measured (section 6): with the 9,285 Hz rate every access lands exactly where this rule puts it
  (a reset too), and MAME's sound hook delivers the stream from sample 0. Early in this lane the
  model was compared at 10,000 Hz, which needed a 93-sample offset and a 2-sample "reset lag"; both
  were artefacts of the wrong rate and are gone.

## 5 Where the sources disagree

| # | What | Sources | The model | The core |
|---|---|---|---|---|
| 1 | Sample rate | 10 kHz: SM Y1 3.12 MHz, AL2 p.1, G81 DAC passage, the resident pauses (section 3); **measured 10 kHz** on five real-console takes of three titles (section 3). M: 3.12 MHz / 336 = 9,285 Hz (sp0256:34) | rate-free; compared with M at 9,285 Hz | 10 kHz (section 8.2): speech 7.7 % higher and shorter than MAME's, as on the console. Settled |
| 2 | Clock | wiki SP0256-012 "1.6Mhz"; SM Y1 3.12 MHz; S2: the ROM clock is 1.56 MHz | — | the wiki's figure is the ROM clock, rounded |
| 3 | Negative coefficients | G81: sign and magnitude; M: two's complement (`qtbl[0x7F & -x]`, sp0256:361) | M | M. Settled by the data: decoding the games' streams as sign and magnitude makes every title's filter blow up (meas, `variants.py`: TRON 20,603 of 200,000 samples at the clip level, SNR -27 dB against M; B-17 likewise) |
| 4 | SETMSB_3 pitch field | IS's format has none (its title says "Load Pitch"); M reads 8 bits of P as for SETMSB_5 | M | M. Moot for the library: no title's stream and no resident phrase uses SETMSB_3 (meas, coverage). DESIGN 10's risk row is closed by this |
| 5 | DELTA_9 B4 in MODE 0x | IS "B4 6 MSBs" (4 bits at bit 2); M 7 MSBs (bit 1), as IS gives for DELTA_D | M | M; **closed as inaudible**: B-17, TRON and WSMLB use DELTA_9 in MODE 00; IS's reading changes their samples by 12-24 dB SNR (meas), but against the owner's recordings (section 3) the two readings differ by only 0.3-0.6 dB in the 3-4.8 kHz band and 0.1 dB in level in the frames concerned (B-17: 70 frames, 0.56 dB; TRON's title: 17 frames, 0.34 dB), far below the recordings' colouring (about 9-12 dB); neither fits better. B4 is the fifth formant's bandwidth |
| 6 | Output resolution | G81: 7-bit PWM; M HIGH_QUALITY: 14 bits (sp0256:184-186); M's "original" path keeps 8 bits (`limit(samp >> 4)`, sp0256:187-189, :307) | M (14 bits) | open (section 9); default 14 bits |
| 7 | MODE across a halt | IS: MODE holds "until ... SETMODE or the sequencer halts"; M keeps it until SETMODE or reset | M | M; moot: every phrase in the references sets MODE before its first data opcode (meas) |
| 8 | Where the voice goes | M: its own speaker, "mono_voice" (voice.cpp:74); SM: R25 to J1 pin 6 (EXT AUDIO), heard through the TV | — | mixed into the machine's sound (section 8.5) |
| 9 | ROM bit order | M's header: the ROM is bit-flipped at start; M's code: the flip is commented out (sp0256:113) | as dumped, LSB first | as dumped |
| 10 | FIFO read past its head | M: the sequencer reads the slot's old word (no stall); SM, wiki: nothing | M | M; no title does it (meas: 0 such reads in every reference), the test program does (section 7) |
| 11 | Repeat count 0 | IS: the instruction does not execute and has no data ("may be in error"); M's header lists it as unimplemented but its code does what IS says (sp0256:1012) | M = IS | M |

Behaviours only MAME describes, copied by the model because the references are MAME's: the delay
line cleared at each period start; the step dropped and remade when the repeat runs out; the halted
poll with the old decoded parameters; the noise seed 1.

## 6 The model and the references

### 6.1 `tools/sp0256.py`

`Voice(rom)`: the SPB640 and SP0256 as the bus sees them: `read(addr)`, `write(addr, data)`,
`step()` (one sample, before the DAC), `reset()`, an optional instruction trace. `mame_out()` is
MAME's output word. `Stream` writes SP0256 programs bit by bit (for test streams), `fields()`
gives an opcode's data widths. CLI: `selftest`, `say N [--wav F]`, `compare DIR...`. It needs the
user's `ivoice.bin` (`--rom`, or `IVOICE.BIN`/`ivoice.bin` in `INTV_BIOS_DIR`).

### 6.2 References: `tools/refs/mame_voice.sh`

Runs MAME (`intvoice`: the Intellivoice with the game in its slot; `intvecs` with
`SPEECH=:speech`: the ECS machine) for N frames with scripted keys, and writes, outside the
repository: `voice_t.log` (every access to `$0080-$0081` with MAME's machine time, Lua memory
taps; with `STATE=1` also the SP0256's PC, halted, LRQ, repeat, period counter and stack, read
through MAME's save-state items), `voice.bin` (the SP0256's stream, Lua sound hook, int16 at
9,285 Hz) and `voice.log` (debugger watchpoints; misses some writes, kept only for the frame and
PC of each access). `EXEC=prog.bin` runs one of our programs in the EXEC slot.

### 6.3 The compare and its tolerances

`sp0256.py compare DIR` plays `voice_t.log` through the model (each access before sample
`floor(t x 9,285) + 1`), and requires: every sample of `voice.bin` equal to `mame_out` of the
model's, from sample 0 (the hook's start is found by matching the first sound and must be 0 in
every run so far); every read value equal; every logged state equal, with two documented
exceptions where MAME's state is not the state at the access's time:

- **Between steps**: at a few reads (games only, all early in a frame), MAME's stream is found
  stopped where a repeat count ran out (repeat 0, period counter just reloaded) while the read's
  time is later. There PC, halted, LRQ and stack must still agree; the counters are not compared.
  The next read always agrees in full. Cause not found (not the stream rule, nor the 50 Hz update).
- **A sample ahead**: a read in the last sample before one of MAME's 50 Hz stream updates that
  falls exactly on a sample boundary (every 0.2 s at 9,285 Hz: sound.h:398) can find the stream
  one sample further; the model's state one sample later must then equal MAME's.

No other tolerance: samples and read values are exact.

### 6.4 Results (meas, 2026-10-29; `logs/compare_final.log` in the lane)

| Run | Frames, keys | Samples (non-zero) | Writes / reads | Commands, FIFO decles | Result |
|---|---|---|---|---|---|
| B-17 Bomber | 3,600, keys | 557,843 (38,387) | 428 / 4,301 | 6, 2, 0; 424 | 0 samples, 0 reads, 0 states differ (83 between steps) |
| Bomb Squad | 3,600, keys | 557,843 (26,232) | 238 / 7,627 | 6, 2, 0; 234 | 0 / 0 / 0 (165 between steps) |
| Space Spartans | 3,600, keys | 557,843 (46,942) | 719 / 4,198 | 6, 2, 4, 0 x3; 712 | 0 / 0 / 0 (78) |
| TRON Solar Sailer | 3,600, keys | 557,843 (66,289) | 793 / 3,754 | 6, 2 x3, 11, 12, 14 x2, 16, 0 x3; 780 | 0 / 0 / 0 (61) |
| WSMLB (`intvecs`, ECS) | 3,600, ECS keys | 557,843 (32,468) | 446 / 4,265 | 6, 2 x2, 0; 441 | 0 / 0 / 0 (101) |
| voicetest (section 7) | 3,000 | 464,808 (229,043) | 484 / 965,976 | 0 x3, 1-42, 63 x42 dropped; 394 | 0 / 0 / 0 (8 a sample ahead) |

The game runs reach their title speech and, for Space Spartans and TRON, some speech in play; the
key scripts are in the lane's `scripts/refs2.sh` and `refs3.sh`. Opcodes the games use: DELTA_9,
DELTA_D, LOAD_4, LOAD_C, PAUSE (MODE 00 and 01) from the FIFO; the resident phrases add LOAD_E,
SETMSB_5, SETMSB_A. The test program covers all twelve data opcodes in all four MODEs.

### 6.5 Found on the way

- LOADALL's amplitude is 8 bits (IS and M agree); the first model had 6. Found by the test
  program, and since checked for every opcode and MODE against M's table (`fmtcmp`).

## 7 The test program: `sim/testroms/voicetest.py`

Builds our own program for the EXEC slot (ROMW 10) with two test streams written with
`sp0256.Stream` (random data, fixed seed). It resets the voice, pushes 64 decles blind, writes
command 0, keeps the FIFO fed; the stream holds every data opcode in every MODE, a zero repeat, a
repeat prefix, SETPAGE, a JMP into the FIFO from a half-read decle, a JSR from the FIFO to a
resident entry and the return to the FIFO. Then it queues commands 1-42, each followed by a
command that LRQ must drop; then resets, pushes 70 decles blind (6 dropped), resets in the middle
of that speech, and starts a 20-decle stream that runs past the FIFO's head. Run in MAME
(`EXEC=`) it is the `voicetest` row above. It checks nothing itself and is the RTL bench's main
stimulus (section 8.7).

## 8 RTL (as built, pass 2: core 0.0.16)

### 8.1 Modules

| Module | Holds | Notes |
|---|---|---|
| `intv_voice.sv` | the bus at `$0080-$0081`, the sample enable, the busy window (8.2), the output chain (8.5) | in `intv_machine`; answers only while on (8.6) |
| `sp0256.sv` | the SPB640 (LRQ, ALD, the 64 x 10 FIFO in an `intv_ram` block RAM, head / tail / bit pointer) and the SP0256 (PC, stack, PAGE, MODE + prefix, halted, the 16 parameter registers, the decoded copy, amp, period, repeat, LFSR, interpolation, the 12-word delay line) | one FSM: the sequencer reads one bit field at a time (two words, two clocks each), the filter makes its 12 products one a clock with one multiplier |
| `sp0256_fmt.svh` | the instruction formats (`fmt_hdr`, `fmt_fld`) and the coefficient table `qtbl` | generated: `tools/sp0256.py gen` (`gen --check` in the gates), from `sp0256.FORMATS` and `QTBL` |

The resident ROM (2 KiB, `ivoice.bin`, data slot 0x105) stays where step 2 put it, in
`intv_sysrom` (M10K), read through `ivoice_addr` / `ivoice_q` (one clock); bytes outside
`$1000-$17FF` read 0, as the model's memory. The planned split into `sp0256_seq` / `sp0256_lpc`
was not needed: the sequencer and the filter never run at the same time, so one FSM with one
multiplier is smaller.

### 8.2 Clocking: the sample enable and the busy window

The enable is a phase accumulator on the CPU's cycle enable while the machine runs (`ce && run`,
as the PSG's): +INC per cycle, a sample each time it passes WRAP. INC / WRAP = 88 / 7,875 is
exactly 10,000 Hz on NTSC clk_sys (472.5 / 11 MHz, a cycle every 48 clocks: 10,000 x 528 /
472,500,000 = 88 / 7,875), so the rate is the clk_sys accumulator of the first plan, gated by the
cycle enable. Counting CPU cycles rather than free clk_sys makes the machine deterministic: the
enable stops with the machine (menu pause, save, load), its phase is one state word, and the
model (`tools/sp0256.py VoiceBus`) works in cycle numbers. 12,480,000 / 1,202,727,120 gives
MAME's 3,120,000 / 336 Hz on MAME's CPU clock (parameters only: the benches).

A sample fires at the ce that ends cycle c, after that cycle's bus access, and `sp0256.sv`
makes it in at most 181 clk_sys (measured over the six references; usually about 30). Accesses at
the ces that end cycles c + 1 .. c + 8 are in the busy window: a read gives the values `$0080` /
`$0081` had when the sample fired; a write is held and lands after the window's last ce (8
cycles = 384 clk_sys, so the sample is always made by then; two CPU writes are at least 9
cycles apart, so at most one is held). A sample still unmade at the window's end would keep the
window open and set `late` (sticky; every bench checks 0). The chip sees bus accesses only
between samples, in the order they come, as the model's.

### 8.3 Resources (expected; the fit is the owner's)

One 18 x 18 DSP (the filter's products), about 600-900 ALMs (the FSM, 16 + 12 parameter bytes,
12 x 16 delay words, the output chain's three accumulators), one M10K for the FIFO (64 x 10;
it may land in MLAB). No new M10K for the ROM (`intv_sysrom` had it since step 2).

### 8.4 Save state: ids $18 and $19

`$18`, 24 words: `sp0256.sv`'s words 0-19 (listed in its header: the sequencer and SPB640
registers, the FIFO pointers, the parameter registers, the decoded coefficient copy kept apart, the
excitation, the delay line, the last sample) and `intv_voice.sv`'s 20-22 (the accumulator; late,
the held write's flag and address, mode, the window count, the snapshot; the held write's data);
word 23 is 0. `$19`, 64 words: the FIFO (`intv_ram`). The format is version 4
(`tools/savestate.py`; states of 0.0.15 and earlier, version 3, are refused). Header flags bit 1
is set while the voice is on, and a state with it refuses to load into a core with the voice off
(and the other way), as the ECS's bit 0. A save lands only while the chip is idle:
`intv_ss_ctl`'s quiet point waits for `voice_busy` low (at most 181 clk_sys). The output chain
is not machine state (DESIGN 4.4).

### 8.5 The output chain and the level

The sample (16-bit signed) is clamped to 14 bits and shifted left 2 (MAME's HIGH_QUALITY value,
the default "Clean"), or, with "Voice Sound: Chip DAC (7-bit)", taken as the PWM DAC's code
(v >> 7, clamped to -64 .. 63) at full scale (<< 9). It is held between samples; at each of the
PSG's 48 kHz strobes a one-pole high-pass at about 150 Hz (x minus a low-pass of x, alpha 5/256:
the coupling capacitors) and two one-pole low-passes at about 5 kHz (alpha 1/2 each at 48 kHz:
the LM324 stages), in 1/256ths, then times the level, added to the PSG sum (PSG #1, or the ECS's
3/4 sum; 0 to 32,767) and saturated to signed 16 bits. The model is `sp0256.VoiceOut`.

ECS level (menu "ECS Level", 0x228; the owner: the ECS and the Intellivoice have separate volume
knobs): PSG #2 alone, before the ECS's 3/4 sum, times Off, Half, Normal, Loud, Loudest = x0, x1/2,
x1, x3/2, x2 (floor); default Normal (x1: the sound of 0.0.9-0.0.15). The sum is widened to 19
bits and saturated at 32,767 as before (`intv_machine` a2s / psgs; the benches' `mix_sample`).
`tb_system` image `ecssound_l4` (Loudest) and plant `ecs_level_ignored`; image `voicemix`
(`sim/testroms/voicemix.asm`: both PSGs' three tones at full volume and the voice at Loudest
saying the resident phrases 6-42) drives the final sum past 32,767, plant `voice_mix_unsat`.

Level (menu "Voice Level", 0x220): Off, Half, Normal, Loud, Loudest = x0, x1/2, x1, x3/2, x2;
default Loudest (x2). How it was chosen: the speech's peak over the five titles' MAME references
is 13,480 (of 32,767, in the clean scale), one PSG's measured peak is 25,967 (WSMLB): x2 puts the
speech's peak (about 27,000, a little less after the filters) at the PSG's, as the owner asked
(speech about as loud as the game's sound); no console recording has been measured yet (section
9, item 3), and the softer steps are there for games whose music is quiet. The saturation keeps a loud phrase over loud music from
wrapping.

### 8.6 Menu and detection

Three items in `interact.json` (11 items, 2,380 bytes minified; `apf_json_check` checks each
against `core_top`'s register and power-up value):

| Item | Address | Values (default first) |
|---|---|---|
| Intellivoice | 0x1000021C | Auto (by cartridge), On, Off |
| Voice Level | 0x10000220 | Loudest (as the PSG) = 4; Off, Half, Normal, Loud |
| Voice Sound | 0x10000224 | Clean, Chip DAC (7-bit) |

Auto is `intv_media`'s `voice_auto`: the loader's flag bit 1 (the CRC table's voice flag, a
CFG's `voice = 1` or `voice_compat = 2 / 3`, a .rom's compatibility tag saying "supports" or
"requires") with the ROM slot (5) loaded whole. On needs the ROM too: without `ivoice.bin` the
voice is off whatever the menu says. Off (or no ROM) leaves `$0080-$0081` unmapped (reads `$FFFF`,
writes dropped: a console without the module) and holds the chip in reset. The mode is taken at
machine reset, as the ECS's. The expansion bus `$0700-$0CFF` stays unmapped (DESIGN 13 item 15).

### 8.7 Benches (sim/tb/tb_voice.py; the others' voice cases)

- `tb_voice` (chip: `tb_voice.sv`; bus: `tb_voicebus.sv`): RTL = model sample by sample, read by
  read (with the sequencer's state at each read) and through save / reset / restore every 50,000
  samples, on the six MAME references at 9,285 Hz (`ref:`), 24 random streams (`rnd:`), and on
  the bus level 24 random programs at 10 kHz (`bus:`) and 12 at MAME's rate (`bmame:`), comparing
  read values, sample cycles and values, and `late` = 0. `bus:0` is directed: a reset, a command
  into the idle chip at a random phase, then a save-restore every few cycles with reads after
  each, so many saves land in the busy window of the step that raises LRQ (snap 0, live 1:
  `ss_window`). Between the save and the restore both benches fill the FIFO RAM with other
  words (a reset does not clear it; a load lands in a machine that ran something else), so a
  FIFO not saved shows (`ss_fifo`). A run that does not end in time (a hung chip:
  `halted_decode`) is a FAIL. Plants (20, each must be caught):
  `loadall_amp6`, `fifo_jump_keep`, `lrq_at_write`, `prefix_two`, `sign_magnitude`,
  `no_interp`, `lfsr_tap`, `fifo_full_63`, `cmd_while_busy`, `no_z_clear`, `halted_decode`,
  `ss_word5`, `ss_fifo`, `rom_range`, `mac_shift`, `win_short`, `snap_live`, `held_lost`,
  `acc_stops`, `ss_window`.
- `tb_system`: `voicetest` (voice on, clean, default level), `voicedac` (the DAC sound at x3/2)
  and `voice_off` through the RTL CPU and bus against `intv_system.py` with the voice: every bus
  phase, every voice sample (its cycle and value: V lines), the mixed sound's hash with the voice
  (`voice_mix`), `intv_voice`'s state words in the dumps, the round trips. Plants
  `voice_mapped_off`, `voice_level2_lost`, `voice_mix_unsigned`, `voice_dac_bits`. (voicetest
  makes no PSG sound, so the mix's saturation is not reached by these images: voicemix reaches it.)
- `tb_savestate`: `voicetest` (On) and B-17 Bomber (Auto, the CRC table's flag) with saves asked
  for just before a sample (two cycles ahead: the request takes about three to reach
  intv_ss_ctl) at five frames, and in the busy window; the voice's samples (A lines) equal after
  every load; V: a voice state into a core with the voice off is refused. Every run fails on a
  freeze that begins inside a voice sample (FRZBUSY), and at least one voice save must have
  waited for a sample with every other quiet term true (VWAIT; the CPU's fetch points fall at a
  different phase of the sample at each frame, and one of the five lands inside it). Plants
  `ss_voice_unchecked`, `ss_voice_acc_lost`, `ss_voice_busy_ignored` (caught by FRZBUSY: the
  freeze inside a sample, whose making is not in the state).
- `tb_loader`: `voice auto` for every image (the table's voice titles, a forced voice CRC), a CFG
  with `voice = 1` and with `voice_compat = 2`, a .rom with the "requires" tag, a voice title
  without `ivoice.bin` (Auto off).

## 9 Open questions for the owner

1. **Rate**: settled at 10 kHz by the owner's recordings (section 3). MAME's 9,285 Hz stays a
   bench parameter only.
2. **DAC** (built: Clean by default, "Chip DAC (7-bit)" in the menu): the chip has a 7-bit PWM;
   MAME outputs 14 bits. The same recording would show the 7-bit hiss between words.
3. **Level** (built: x2 by default, 8.5): the default voice level against game sounds (the module's thumbwheel); the
   recording at a known thumbwheel position gives a starting point. The ECS's second PSG has its
   own level now (8.5), default x1.
4. **DELTA_9 B4** (row 5): closed as inaudible; MAME's reading kept.
5. With the flash cart, a cartridge build of `voicetest` played on the console with the
   Intellivoice would measure the rate, the FIFO's behaviour past its head (row 10) and the
   resident pauses directly.
