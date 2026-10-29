# Hardware measurement cartridges

Small programs of our own for the owner's console (NTSC Intellivision with the ECS) on a flash
cartridge (the owner's PiRTO II: BIN + CFG). Each one settles a timing or behaviour question the
documents leave open, shows its result as text, and holds still long enough for a photo. Sources:
`sim/testroms/hw/` (`hwlib.asm`, the shared header, take-over and text output; one `.asm` per
program). Build:

    python3 sim/testroms/hw/build_hw.py build OUTDIR          # NAME.bin + NAME.cfg (+ .lst)
    python3 sim/testroms/hw/build_hw.py run NAME --frames N --snaps a,b --png DIR [--mode stic|mame]
        [--tools OTHER_TREE] [--ecs on --keys r:c,...] [--intrm-shift D]

`run` boots the cartridge on the real EXEC in the Python model (`tools/intv_system.py`, the
user's exec.bin / grom.bin), writes the pictures and prints the program's variables; `--tools`
takes the model from another tree (the predictions below are those of the core from 0.0.13 on,
with the 2-cycle bus request exit of GI's figures; the values before 0.0.13 are kept for
comparison), `--intrm-shift` what-ifs the interrupt
sampling point. Every program starts like a normal cartridge (header at $5000, "code after the
title"), takes the EXEC's ISR vector ($0100) and never returns to the EXEC (the technique of
`sim/testroms/sticmob_cart.py`). Results are read off the screen.

The phase lock (hw_intlate, hw_rowcopy): with the display on, the main code waits in a one-
instruction loop (`sloop: B sloop`) while the STIC fetches its rows; each row's bus request
stops the CPU until a fixed cycle of the frame, so after the last row the CPU's phase no longer
depends on the past and the next VBlank interrupt is taken at a known cycle (in the model: frame
cycle +9 from sloop). An ISR of constant length then returns into the measurement by rewriting
the PC the interrupt saved (at STACK, $02F1: main's stack is empty). The EXEC's dispatcher runs
between the interrupt and our ISR; it is the console's own ROM, so its time is the same on both.

## 1. hw_steal: the cycles the STIC takes a frame

STIC_NOTES T1, T2, T4; CPU_NOTES (the bus request exit). Phases of 128 frames alternate, display
off (blank screen, no bus requests) and display on; the main loop counts its passes (52 cycles a
pass) over frames 8-127 of each phase; the ISR costs the same in both. Screen (display-on phases):
LAST / MIN / MAX of the OFF and ON counts, DIFF = OFF - ON, N = phases done.

Stolen cycles a frame = DIFF x 52 / 120.

| source | OFF | ON | DIFF | stolen / frame |
|---|---|---|---|---|
| **model, the core from 0.0.13 (2 NACT exit, G82 Fig 16)** | **33439** | **30120** | **3319** | **1,438** |
| model before 0.0.13 (no exit cycles) | 33439 (min 33438) | 30180 (min 30179) | 3259 | 1,412 |
| MAME (takes no cycles, STIC_NOTES T2) | - | - | ~0 | ~0 |

The two models differ by 60 passes (2 cycles x 13 requests a frame x 120 / 52): far over the
count's jitter of 1. OFF x 52 / 120 also gives the frame's cycles left after the ISR (14,490 in
the model, of 14,934).

## 2. hw_intlate: where the VBlank interrupt is taken

CPU_NOTES open point 1. Lock frame (display on) and probe frame (display off) alternate: the
probe frame's ISR returns into probe k (k = 0..5: 24 + k cycles of padding, a delay of 959
passes of 15 cycles, then 60 x INCR R0, 6 cycles each, interruptible); the next interrupt cuts
the train and its index (interrupted PC - train) is kept. After a round of 6 probes the display
stays on for 120 frames. Screen: per k, LAST / MIN / MAX of the index (hex); ROUND.

Each extra cycle of padding moves the train one cycle later, so the index steps down by one at
one k; the step's place and the index give the sampling point (with the frame length and the
bus request exit: hw_steal separates the exit). Model (`--intrm-shift D`: the CPU sees INTRM D
cycles later):

| model | k0 k1 k2 k3 k4 k5 |
|---|---|
| D = -3 | 1C 1C 1C 1C 1C 1C |
| **the core from 0.0.13 (D = 0 with the exit +2), = D = -2 before** | **1D 1C 1C 1C 1C 1C** |
| D = -1 | 1D 1D 1C 1C 1C 1C |
| before 0.0.13, D = 0 | 1D 1D 1D 1C 1C 1C |
| D = +1 | 1C 1B 1B 1B 1B 1B |
| D = +2 | 1C 1C 1B 1B 1B 1B |
| D = +3 | 1C 1C 1C 1B 1B 1B |

MAME takes no bus request cycles and runs on its own frame clock, so the phase lock does not
hold there: no MAME prediction.

## 3. hw_rowcopy: when each card row is copied

STIC_NOTES T5, T10. Every frame the same: the ISR (constant time) fills rows 0-10 with the OLD
pattern (white '-', the row number in column 0) and returns into the writer, which waits 15 x
(148 + STEP) cycles and writes the NEW pattern (red '#', the row number in yellow) over rows 0-10,
one word every 15 cycles (MVO@ then an interruptible NOP: a row request is answered within 15
cycles, so no row is missed; a run of MVO@ alone held requests past the 57-cycle deadline and
lost a row in the model). STEP (row 11) goes 0..23 (0x17), 90 frames each. The STIC copies a
row in one go while the CPU is stopped: the row being written when it is copied shows '#' up to
the writer's column. Model, the number of '#' in that row (columns 1-19, row 3 in all steps):

| step | 0-4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **the core from 0.0.13** | **19** | **18** | **17** | **16** | **15** | **14** | **13** | **12** | **11** | **10** | **9** | **8** | **8** | **7** | **6** | **5** | **4** | **3** | **2** | **1** |
| before 0.0.13 | 19 | 19 | 19 | 18 | 17 | 16 | 15 | 14 | 13 | 12 | 11 | 9 | 8 | 7 | 6 | 5 | 4 | 3 | 2 | 1 |
| MAME timers | 19 | 19 | 19 | 19 | 19 | 18 | 17 | 16 | 15 | 14 | 13 | 12 | 11 | 10 | 9 | 8 | 7 | 6 | 5 | 4 |

(Rows 0-2 OLD, rows 4-10 NEW in all.) A row that shows the row above it again (its number
repeated, the picture pushed down) is a missed row (T10): none in the model.

## 4. hw_cpuodd: undefined CPU cases

CPU_NOTES "Where the sources disagree". Run once at start-up with interrupts off; then shown
(hex). Model = the choice in CPU_NOTES; the alternatives:

| line | what | model | others |
|---|---|---|---|
| NEGR 0 | GSWD after NEGR of 0 (row 5) | 5050 (C = 1, S1 / wiki) | MAME 4040 (C never set) |
| SWAP 2 | SWAP R0, 2 of $1234 (row 6) | 3434 (wiki, MAME) | 1234 (S1: swap twice) |
| SDBD R6 | SDBD + MVI@ R6 over $11AA, $22BB: word, R6 moved down (row 8) | BBBB, 0001 (wiki) | MAME: two pre-decrements: AABB, 0002 |
| MVO SDBD | SDBD + MVO $ABCD to M1: M1, M1 + 1 (row 10) | ABCD, 0000 (D ignored) | MAME: illegal |
| MVO@ R4 | MVO@ R4, R4 at M2: word written, R4 after (row 15) | 0312, 0313 (old value) | MAME the same |
| SDBD DIR | SDBD + MVI M3, R0 (M3 = 1357, R0 -> 00A1, 00B2) (row 9) | 1357 (D ignored) | MAME: through R0 (A1A1 or B2A1) |
| J II=3 | a J with interrupt bits 11: taken, ISRs after (row 14) | J, 0000 (taken, I unchanged) | MAME: N (not taken) |

M1 = $0310, M2 = $0312 (shown on the last line).

## 5. hw_ecskeys: the ECS keyboard matrix

ECS_NOTES; TEST_0.0.9 B2. Needs the ECS. The main loop scans both ways through PSG #2 ($00F8
bit 6: port A out; bit 7: port B out): left grid A>B (row r driven low, columns read), right grid
B>A (column c driven low, rows read); '#' = the line reads 0. Key positions: tools/ecs.py KEYPOS
(row = port A bit, column = port B bit). Model (keys pressed by matrix position):

| keys | A>B | B>A |
|---|---|---|
| one key (1, 2) | row 1: col 2 | col 2: row 1 |
| a pair in one row (1, 2), (1, 5) | row 1: cols 2 and 5 | nothing (the other column, driven high, masks both) |
| three corners (1, 2), (3, 2), (1, 5) | nothing (masking: the keys join a line driven high) | nothing |
| MAME (rows ANDed, port A reads $FF) | every key at its place, no masking | nothing |

## On the RTL

All five run in tb_system (`--only hw_steal,hw_intlate,hw_rowcopy,hw_cpuodd,hw_ecskeys`; HW_IMAGES,
never in `--all`: 60 to 1,150 frames each) with the RTL equal to the model on every bus phase and
picture, straight and through the bench's save/restore round trips, at the core from 0.0.13
(2026-10-29): hw_steal 460 frames, hw_intlate 230, hw_rowcopy 1,150 (to step 12), hw_cpuodd 60,
hw_ecskeys 60 with ECS keys held (W; W+Q; W+Q+1; Shift+L) under Auto (attached). So the screens the
owner photographs are the model's predictions above, exactly.
