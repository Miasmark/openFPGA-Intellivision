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
| **console (2026-10-31; Model 2609, PiRTO II; LAST = MIN = MAX over 5 phases)** | **33431** | **30280** | **3151** | **1,365** |

The console's OFF count needs 14,487 cycles a frame for the main loop (14,486 or 14,488 give
other counts): 3 fewer than the model (a frame 3 cycles shorter, or an interrupt path 3 cycles
longer: section 6 separates them). Its ON count is 120 x 757 / 3: the CPU loses 1,365.7 cycles
a frame on average, in a pattern that repeats every 3 frames. The model's per-candidate
predictions are in section 8.

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
cycles later), the core from 0.0.13 (corrected 2026-10-31: the table here before gave D
relative to the model before 0.0.13, whose D equals today's D - 2):

| model | k0 k1 k2 k3 k4 k5 |
|---|---|
| D = -3 | 1C 1C 1C 1C 1B 1B |
| D = -2 | 1C 1C 1C 1C 1C 1B |
| D = -1 | 1C 1C 1C 1C 1C 1C |
| **the core from 0.0.13 (D = 0, the 2-NACT exit)** | **1D 1C 1C 1C 1C 1C** |
| D = +1 | 1D 1D 1C 1C 1C 1C |
| D = +2 (= the model before 0.0.13, no exit cycles) | 1D 1D 1D 1C 1C 1C |
| D = +3 | 1C 1B 1B 1B 1B 1B |
| D = +4 | 1C 1C 1B 1B 1B 1B |
| **console (2026-10-31; LAST = MIN = MAX, 6 rounds)** | **1C 1B 1B 1B 1B 1B** |

The console's row is D = +3 of today's model: the CPU resumes from the frame's last row request
and takes the interrupt 3 cycles later against the next VBlank than in the model (with the frame
3 cycles shorter, or the interrupt path 3 cycles longer, as hw_steal's OFF count needs: the CPU
resumes from the last row 5 cycles after the next INTRM, not 2). Section 8 has the candidates.

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
| **console (2026-10-31; read at steps 3, 6, 8, 16, 18, 20, 23)** | **19** | **19** | **18** | **17** | **16** | **15** | **14** | **13** | **12** | **11** | **10** | **9** | **8** | **7** | **6** | **5** | **4** | **3** | **2** | **1** |

The console's count is min(19, 24 - step) at every step read, with no plateau: one column (15
cycles) later than the model at steps 5-15, the same from 16 on.

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

## 6. hw_frame: the frame length and the interrupt's cost

STIC_NOTES T11; CPU_NOTES row 1 (the interrupt sequence, 9 cycles: S1 p.35). hw_steal's OFF
count gives the frame length minus the interrupt path; this program measures the two apart.
Interrupts off, display off (no bus requests). The main code finds each frame start by polling
the STIC's register window: a $20 write late in the frame (after the VBlank window, so the
display stays off) sets the handshake, which closes the registers until the next frame starts.
A read of the border register ($2C, colour 1) shows colour 1 in its low bits while open and
anything else while closed (the model: the address offset, $2C). Each frame: the edge, a
21-cycle payload, a fixed delay to about cycle 13,900, the late $20 write, then 56-cycle poll
passes, counted, until the next edge. Over 224 frames the passes S give the frame length P =
13,771 + S / 4 (the count is off by less than one pass, so P rounds to the cycle). Three phases
of 224 frames (11 s, a blank screen), then the numbers for 300 frames (5 s):

- F: the payload alone;
- I: the payload with EIS ... DIS around an interruptible NOP, so the VBlank interrupt (pending
  since the frame start) is taken there: the EXEC's dispatcher and our ISR (JR R5);
- X: the payload, then an inline sequence of the same instructions as the dispatcher's interrupt
  path (as the model traces it), entered by MVII + PSHR + B instead of the interrupt.

Screen: FRAME CYC = P; IRQ PATH = (S_F - S_I) / 4, the cycles an interrupt costs the main code;
COPY PATH = (S_F - S_X) / 4; IRQ ENTRY = IRQ PATH - COPY PATH + 26 (MVII + PSHR + B), the
interrupt sequence itself; S_F S_I S_X in hex (each can differ by 1 with the boot's phase); N.
"NO EDGE (WINDOW)": the registers never closed after the late $20 write (the handshake does not
close them with the display off), so this method cannot time the frame. Should a late $20
write switch the display on at once (MAME draws such a frame, STIC_NOTES D8), the poll region
would see row requests and FRAME would read noticeably low.

| candidate (section 8) | FRAME CYC | IRQ PATH | COPY PATH | IRQ ENTRY | S_F S_I S_X |
|---|---|---|---|---|---|
| **today's core (0.0.13 on)** | **14934** | **221** | **238** | **9** | 122C 0EB8 0E74 |
| A, SI-A, IR-A, M-A (12-cycle interrupt) | 14934 | 224 | 238 | 12 | 122C 0EAC 0E74 |
| M (the MAME fork's timing as it is) | 14934 | 221 | 238 | 9 | |
| A' (the dispatcher's SDBD + MVI@ R4, R7 three cycles longer) | 14934 | 224 | 241 | 9 | 122C 0EAC 0E68 |
| B, SI-B, IR-B (frame 14,931) | 14931 | 221 | 238 | 9 | 1220 0EAC 0E68 |

So the console's FRAME CYC settles A against B at once (14,934 or 14,931), and IRQ ENTRY / COPY
PATH tell a longer interrupt sequence (A) from a slower instruction in the dispatcher (A').

**Console (2026-10-31): "NO EDGE (WINDOW)".** Within the poll limit (2,000 passes, about 7.5
frames) the program never saw the sequence it waits for: a read of $2C whose low four bits are
not 1 (closed), then one whose low bits are 1 (open). It enters the polls right after a
display-on frame's ISR (its own $20 write may fall in VBlank too), so with the model's rules it
sees "closed" at the end of that VBlank and "open" at the next frame start. Two ways the
console can fail this, and this program cannot tell them apart: (a) $2C never reads back with
the border colour in its low bits (a read of the colour registers does not return what MAME's
rule, $3FF0 | colour, says: the model and MAME are wrong about the read value); or (b) $2C reads
1 in its low bits at all times, in and out of VBlank, even in a display-on frame (the register
window does not gate reads of $2C as modelled). Either way the model's rule for this read is
wrong somewhere. hw_frame2 (section 9) prints the raw values of such reads, and times the frame
without any register read.

## 7. hw_steal2: the shape of the bus requests

STIC_NOTES T1, T4; CPU_NOTES (the bus request exit). hw_steal gives the cycles the requests take
a frame; this program asks where they start and end. Rounds of 3 x 15 frames: a lock frame
(display on, main in `sloop`: the last row's request fixes the phase, so the interrupt comes at a
known cycle), then ON frame k (display on) and OFF frame k (display off: no requests), both
entered at the same cycle: the ISR (constant time) returns into probe k, a padding of 30-40
cycles and then counting loop k (INCR R0 and up to two more instructions, 15 to 37 cycles a
pass, some with an MVO that a request cannot stop), until the next interrupt. Each request stops
the loop at its next interruptible boundary and lets it go at a fixed cycle, so the ON passes
depend on where each request starts against each loop (the length before the CPU resumes, i.e.
hold + exit, and the frame request's start and end); the OFF passes only on the frame length
minus the interrupt path. The next ISR reads the interrupted main's R0 (the EXEC's dispatcher
saves it at STACK + 1) and clears it. Screen (2.5 s after each 0.75 s round): per probe k
(0-E) the ON (yellow) and OFF (white) passes in hex; N = rounds.

Probes: k = loop (cycles a pass) + padding: 0 = 15 + 30, 1 = 15 + 37, 2 = 21 + 30 (INCR NOP B),
3 = 22 + 30 (INCR NOPP B), 4 = 23 + 30 (INCR MVII B), 5 = 25 + 30 (INCR MVI B), 6 = 26 + 30
(INCR MVO B), 7 = 26 + 37, 8 = 27 + 30 (INCR NOP NOP B), 9 = 32 + 30 (INCR MVO NOP B), A = 37 + 30
(INCR MVO MVO B), B = 37 + 40, C = 21 + 40, D = 25 + 40, E = 27 + 40.

ON passes (hex), k = 0 .. E:

| candidate (section 8) | ON k = 0 1 2 3 4 5 6 7 8 9 A B C D E |
|---|---|
| **today's core (0.0.13 on)** | **35D 35C 264 249 22F 203 1F2 1F2 1DE 193 161 161 264 203 1DD** |
| A | 35D 35C 264 249 22F 203 1F2 1F2 1DE 193 161 160 264 203 1DD |
| A' | 35D 35C 264 249 22F 203 1F2 1F2 1DE 193 161 160 264 203 1DD |
| B (12 rows: the 13th no longer fits) | 364 363 26A 24E 234 208 1F6 1F6 1E2 197 164 164 269 208 1E1 |
| SI-A | 35F 35F 26A 24F 235 208 1F6 1F6 1E0 198 160 15F 26A 207 1E0 |
| SI-B | 360 35F 26A 24F 235 208 1F7 1F6 1E0 198 160 15F 26A 208 1E0 |
| IR-A | 35D 35D 264 249 232 203 1F2 1F2 1DE 193 161 161 264 203 1DD |
| IR-B | 35D 35C 265 249 232 203 1F2 1F2 1DE 193 162 161 264 203 1DD |
| M (the MAME fork as it is) | 360 360 26B 24D 235 205 1F4 1F4 1E0 195 15F 15F 26A 205 1E0 |
| **M-A, hold 110 (exact on all three)** | **361 361 26B 24E 235 206 1F5 1F5 1E1 195 160 15F 26B 205 1E1** |
| M-A, hold 109 (exact on all three) | 361 361 26B 24E 235 209 1F5 1F5 1E1 198 15F 15F 26B 209 1E1 |
| M-A' (hold 110, the dispatcher +3) | as M-A, hold 110 |
| M-B (closest: ON 30279) | 361 360 26B 24E 235 206 1F5 1F4 1E1 195 160 15F 26A 206 1E1 |
| X-A, X-B (section 8: the best fit of all four tests) | 365 365 26B 250 235 209 1F5 1F4 1E4 197 163 163 26A 209 1E3 |
| Y-B (section 8: the best fit of this table alone) | 365 365 26B 24F 235 209 1F5 1F4 1E4 198 163 163 26A 209 1E3 |
| **console (2026-10-31; N = 11 rounds, stable)** | **365 365 26A 24F 235 209 1F5 1F4 1E4 198 163 163 26A 209 1E3** |

Console OFF: 3BE 3BE 2AD 28E 271 23F 229 228 215 1C1 184 184 2AC 23F 214 (X-A / X-B: 3BF at k = 0,
the rest equal; Y-B: all equal).

OFF passes: 3BF 3BE 2AD 28E 271 23F 229 229 215 1C2 185 185 2AC 23F 214 (today's core, A, A');
B, SI and IR have 3BE at k = 0, SI and IR 1C1 at k = 9, B 184 at k = A and B. The exit NACTs cannot be told apart by any CPU-side count
(only release + exit, the moment the CPU resumes, is visible): SI-B with exits of 0, 1 or 2
cycles (hold 102, 101, 100) gives the same screen, and so on.

## 8. Candidates for the console's timing (2026-10-31)

From the console's hw_steal, hw_intlate and hw_rowcopy results: model variants (the what-if
copy of the tools, run on these programs), cycles from INTRM (the frame start). Today's core:
frame 14,934, interrupt 9 cycles, frame BUSRQ 3,790-3,831, row r BUSRQ from 3,876 + 912 r for
114 cycles, then 2 NACTs (the CPU resumes at 3,992 + 912 r), 13 rows with VDR = 0.

- **A**: the interrupt sequence 12 cycles (3 more NACTs; no source: S1 p.35 and MAME give 9,
  the wiki 7 or 10). **A'**: 9 cycles, but the dispatcher's SDBD + MVI@ R4, R7 three cycles
  longer. **B**: the frame 14,931 cycles (3 short of 57 x 262). Each alone gives hw_steal's OFF.
- **SI-A / SI-B** (hw_steal and hw_intlate exact, hw_rowcopy one column early): A or B, the CPU
  resuming from row r at 3,995 + 912 r (A) / 3,992 + 912 r (B) (row 12 past the next INTRM),
  row r's request 102 cycles before that (e.g. held 100 + 2 NACTs, instead of 114 + 2), and the
  frame BUSRQ from 3,790 held until row 0 is released (one request of about 200 cycles).
- **IR-A / IR-B** (hw_intlate and hw_rowcopy exact, hw_steal ON 30179 / 30180): A or B with the
  CPU resuming at 3,995 + 912 r / 3,992 + 912 r, the requests 115 cycles before that, frame
  BUSRQ 3,790-3,831.

| candidate | hw_steal OFF / ON | hw_intlate | hw_rowcopy | hw_frame | hw_steal2 |
|---|---|---|---|---|---|
| **console** | **33431 / 30280** | **1C 1B 1B 1B 1B 1B** | **min(19, 24 - step)** | ? | ? |
| today's core | 33439 / 30120 | 1D 1C 1C 1C 1C 1C | 23 - step at 5-15, 8 8 at 15-16 | 14934, 9 | section 7 |
| A / A' | 33431 / 30120 | 1C 1C 1C 1C 1B 1B | as today | 14934, 12 / 9 | |
| B | 33431 / 30360 | 1C 1C 1C 1C 1B 1B | as today | 14931, 9 | |
| SI-A / SI-B | 33431 / 30280 | 1C 1B 1B 1B 1B 1B | 22 / 23 - step, row 4 at step 23 | 14934, 12 / 14931, 9 | |
| IR-A / IR-B | 33432 / 30179, 30180 | 1C 1B 1B 1B 1B 1B | min(19, 24 - step) | 14934, 12 / 14931, 9 | |
| M (the MAME fork, f82e8a54) | 33438 / 30270 | 1C 1C 1B 1B 1B 1B | min(19, 24 - step) | 14934, 9 | |
| **M-A** | **33431 / 30280** | **1C 1B 1B 1B 1B 1B** | **min(19, 24 - step)** | 14934, 12 | |
| M-B (best found) | 33431 / 30279 | 1C 1B 1B 1B 1B 1B | min(19, 24 - step) | 14931, 9 | |

**Family M** (from the MAME fork's commit f82e8a54 of 2026-10-31, fitted there to the same three
console results): the CPU grants BUSRQ at the end of every instruction, interruptible or not
(against G82's pin description and 2.5.5: "only after the completion of an interruptable
instruction"; the console's hw_rowcopy, a writer of non-interruptible MVO@s, shows no plateau);
12 row fetches and no 13th with VDR = 0 (against T3); the request at the end of VBlank held
about 100 cycles (T4 had 42); row r requested at the fetch line, 3,933 + 912 r, for 110 cycles,
then 2 NACTs. In our model this gives the fork's numbers (1,373 a frame, 1C 1C 1B..., all 24
rowcopy steps). **M-A**: the same with a 12-cycle interrupt (or A'), row r released at 4,041 +
912 r (requested at 3,931 for 110 or 3,932 for 109 cycles) and the frame request held 88-96 (88-94
with 110): **hw_steal, hw_intlate and hw_rowcopy all exact** (H 108 with frame request 96 and
request 3,933, and H 107 / 98 / 3,934, too). M-B (frame 14,931): hw_intlate and hw_rowcopy exact
with rows released at 4,038 + 912 r, but ON 30279 at best (30299, 30279, 30270 around it). The
counts' last digit also depends on the phase the console powered up in (the first OFF phase:
33432 in the model; M-A's ON phases 30280, 30279, 30280 over a long run), so a difference of one
in a single phase does not decide.

**Fitted to hw_steal2 as well (2026-10-31).** The console's hw_steal2 screen (section 7) is
matched by none of the candidates above (M-A, hold 109, is closest: 3-4 passes short in the
loops without MVO). A local search over the model's parameters (interrupt / frame family,
BUSRQ grant rule, rows, the rows' release point and request lead, the frame request's start and
length, INTRM sampling) against all four console results finds:

- **Y-B**: B (frame 14,931, 9-cycle interrupt), BUSRQ granted only after interruptible
  instructions (G82, as today's core), 12 rows, row r released at 4,029 + 912 r (requested at
  3,922 + 912 r, 107 cycles, then 2 NACTs), the frame request 3,800-3,900, INTRM seen one cycle
  early: hw_steal2 within one pass at one probe (k = 2), hw_rowcopy exact, but hw_steal ON
  30299 and hw_intlate 1B 1B 1B 1B 1B 1B.
- **X-A / X-B**: the same rows and frame request (A: released 4,032 + 912 r, requested 3,924 +
  912 r for 108; frame request 3,802-3,902), and a grant rule between the two: BUSRQ granted after
  any instruction except when the next one is not interruptible either (so after an MVO that
  an interruptible instruction follows, not between two MVOs): hw_steal (33431 / 30280),
  hw_intlate and hw_rowcopy exact, hw_steal2 off by one pass at k = 2, 3 and 9 and one OFF pass
  at k = 0.

The probes where the grant rules part: k = A, B (two MVOs in a row: the console loses as few
cycles as with G82's rule) and hw_steal's loop (an MVO before an MVI: the console loses as many as
with a grant after the MVO). No rule tried gives both exactly; a cartridge that varies what
follows the MVO (MVI, NOP, B, another MVO) would settle it.

Before family M, no variant tried matched all three (about 3,000 model runs: hold lengths, frame
request starts, lengths and merging, exit NACTs, a 12-row case with the requests one line ahead,
a request held a fixed time from BUSAK, BUSRQ after non-interruptible instructions with the rows
one line ahead). hw_frame settles A / A' / B; hw_steal2 then tells the families and the holds apart.

**The final fit, F (2026-11-01), against all six console results** (hw_steal, hw_intlate,
hw_rowcopy, hw_steal2, hw_frame2, hw_grant). Cycles from INTRM (the CPU's VBlank request):

- the frame 14,934 cycles (57 x 262), the interrupt sequence 9 cycles;
- SDBD + MVI@ R4, R7 one cycle longer (15: hw_frame2), and two more cycles on the interrupt path
  (the steal OFF count): modelled as JSR 13 and PULR R7 12 (the EXEC's dispatcher and our ISRs
  have one of each; an 11-cycle interrupt sequence fits the same tests one point worse);
- BUSRQ granted only after interruptible instructions (G82; hw_grant), as today's core;
- 12 row requests, none at VDR = 0's 13th place: row r requested at 3,926 + 912 r for 107 cycles,
  released at 4,033 + 912 r, the CPU resuming 2 NACTs later (4,035 + 912 r; the exit NACTs and
  the release cannot be told apart, only their sum);
- the request at the end of VBlank 3,792-3,892 (100 cycles), separate from row 0's;
- the display enable latched at 3,791 (the end of the register window).

Refitted with hw_grantx (counts and PCs) included, F stays the best point found. Residuals:
hw_steal 33431 / 30280 (in every phase of a 1,000-frame run, the first included),
hw_intlate 1C 1B 1B 1B 1B 1B, hw_rowcopy all 24 steps, hw_frame2's V, W, U rows (14934, 15): all
exact. hw_steal2: 5 passes in 30 (ON k = 2 +1, 8 -1, A -1, B -1; OFF k = 7 +1). hw_grant: 11 in 27
(ON k = 0 -1, 1 +1, 2 +2, 3 -1, 6 -1, 7 -1, A +1, D -1; OFF A +2), its three 000s not explained
(section 11). hw_grantx: 3 counts off by one in 12, 3 cut positions one instruction off in 12.
Read-back: a closed STIC register reads $0000; the registers close only in a frame with the
display on (section 9). The changes this implies, with their evidence: docs/TIMING_FIT.md.

## 9. hw_frame2: the frame length from the VBlank interrupt alone; what $2C reads return

STIC_NOTES T11; CPU_NOTES row 1. Replaces hw_frame's register-window timing (section 6: no edge
on the console). As hw_intlate: a lock frame (display on, main in `sloop`) then a probe frame
(display off) whose ISR (constant time) returns into probe k (24 + k cycles of padding, k =
0..5), a path, a delay loop and a train of 60 x INCR R0; the next VBlank interrupt cuts the
train, and the next ISR keeps idx = interrupted PC - train (hex). Over k = 0..5 the cut moves
one cycle a probe, so a row's six indices give the cut against the train's start to the cycle:
C = 6 x min + (the number of k one above it). Rows:

- V: the path MVII + B; the train meets the next frame's interrupt;
- W: DIS, a delay past the next frame's VBlank (that frame's interrupt is not taken: its request
  is dropped when INTRM rises, CPU_NOTES), EIS, more delay: the train meets the interrupt one
  frame later. Both ends are the same kind of event (the interrupt's sampling), so the interrupt
  sequence is in neither: FRAME CYC = C(W) - C(V) + 14,933 is the frame length;
- U: V with MVII + SDBD + MVI@ R4, R7 in front (the jump the EXEC's dispatcher makes to our ISR):
  SDBD JUMP = C(V) - C(U) - 8, the cycles of SDBD + MVI@ R4, R7 (14 in the model).

Then two diagnostic frames read $2C (border colour 1, set by every ISR): in VBlank and at cycle
~5,000 of a display-on frame, in VBlank and at ~5,000 of a display-off frame, and right after a
$20 write at that point (hw_frame's late write). Shown raw (4 hex digits). The model (MAME's
rule): $3FF1 while the registers are open (VBlank, or the handshake clear), $002C (the address
offset) while closed.

Screen (about 1.5 s to the first, then every 3.1 s): V, W, U rows of six indices, FRAME CYC,
SDBD JUMP, the five $2C reads, N.

| candidate | V | W | U | FRAME CYC | SDBD JUMP |
|---|---|---|---|---|---|
| **today's core** | **1D 1D 1D 1D 1C 1C** | **1D 1D 1D 1D 1D 1C** | **19 19 19 19 19 19** | **14934** | **14** |
| A (12-cycle interrupt) | 1D 1C 1C 1C 1C 1C | 1D 1D 1C 1C 1C 1C | 19 19 19 18 18 18 | 14934 | 14 |
| A' (dispatcher's jump +3) | 1D 1C 1C 1C 1C 1C | 1D 1D 1C 1C 1C 1C | 18 18 18 18 18 18 | 14934 | 17 |
| B (frame 14,931) | 1D 1C 1C 1C 1C 1C | 1C 1C 1C 1C 1C 1B | 19 19 19 18 18 18 | 14931 | 14 |
| M-A (section 8) | 1C 1C 1C 1C 1B 1B | 1C 1C 1C 1C 1C 1B | 18 18 18 18 18 18 | 14934 | 14 |
| M-B | 1C 1C 1C 1C 1B 1B | 1C 1C 1B 1B 1B 1B | 18 18 18 18 18 18 | 14931 | 14 |
| X-A (section 8) | 1C 1C 1C 1C 1B 1B | 1C 1C 1C 1C 1C 1B | 18 18 18 18 18 18 | 14934 | 14 |
| X-B (section 8) | 1C 1C 1C 1C 1B 1B | 1C 1C 1B 1B 1B 1B | 18 18 18 18 18 18 | 14931 | 14 |
| Y-B (section 8) | 1C 1C 1C 1B 1B 1B | 1C 1B 1B 1B 1B 1B | 18 18 18 18 18 17 | 14931 | 14 |

| **console (2026-11-01; N = 13 and 14, identical)** | **1C 1C 1C 1B 1B 1B** | **1C 1C 1C 1C 1B 1B** | **18 18 18 18 17 17** | **14934** | **15** (decimal) |
| F (section 8: the final fit) | 1C 1C 1C 1B 1B 1B | 1C 1C 1C 1C 1B 1B | 18 18 18 18 17 17 | 14934 | 15 |

$2C reads in the model (all candidates): VBLANK ON 3FF1, MID ON 002C, VBLANK OFF 3FF1, MID OFF
3FF1, AFTER LATE $20 002C. **Console: 3FF1, 0000, 3FF1, 3FF1, 3FF1.** So (1) a closed STIC read
returns $0000, not the address offset (MAME's rule, and ours, are wrong); (2) a $20 write after
VBlank, with the display off, does not close the registers: they are closed only in a frame
whose display is on (the handshake written during VBlank), from the end of VBlank to the next
frame start. That is why hw_frame (section 6) saw no edge: it waited for a close the late write
never makes. (3) W's indices are sane: the VBlank request masked by DIS was dropped when INTRM
rose, not kept for the EIS (CPU_NOTES' edge rule holds). FRAME CYC 14934 settles the frame
length (57 x 262, A not B), and SDBD JUMP 15 (the field is decimal: putdec) makes SDBD + MVI@
R4, R7 one cycle longer than the model's 14. hw_steal's console OFF count fixes the frame length minus the
interrupt sequence at 14,922 cycles (the main loop gets 14,487 of each frame; the ISR path's
instructions take 435 in the model), so FRAME CYC and SDBD JUMP give the interrupt sequence: 14,934 and 14 say 12 cycles (A), 14,934 and
17 the dispatcher's jump (A'), 14,931 and 14 a 9-cycle interrupt in a shorter frame (B). If the
console keeps a masked interrupt request latched (taken at the EIS), W's indices come out far
off (the cut inside the delay loop: FFxx) and FRAME CYC is meaningless: that answers CPU_NOTES'
edge-latch question instead.

## 10. hw_grant: after which instructions the CPU lends the bus

CPU_NOTES (interruptibility; G82 p.11 and 2.5.5: the bus is granted "only after the completion
of an interruptable instruction"). The question of section 8: the console's hw_steal2 and
hw_steal fit no single grant rule of the model. Three rules: **G82** (only after an
interruptible instruction: today's core); **any** (after every instruction: the MAME fork);
**look-ahead** (after every instruction except when the next is not interruptible either:
X-A / X-B). Same frames as hw_steal2 (section 7): a lock frame, then ON frame k and OFF frame k
entered at the same cycle, a padding of 30 cycles and loop k until the next interrupt; the
loops vary what follows a non-interruptible MVO (or MVOI):

| k | loop (MVO, MVOI not interruptible) | k | loop |
|---|---|---|---|
| 0 | INCR NOP NOP B (control) | 8 | INCR (MVO MVO) x2 B |
| 1 | INCR MVO MVI NOP NOP B | 9 | INCR (MVO MVO) x2 NOP B |
| 2 | INCR (MVO NOP) x2 B | A | INCR (MVO MVO) x3 NOP NOP B |
| 3 | INCR MVO B NOP B | B | INCR MVO MVO MVI NOP NOP B |
| 4 | INCR (MVO MVII) x2 B | C | INCR (MVO MVOI MVI) x2 B |
| 5 | INCR (MVO SDBD MVII) x2 B | D | INCR (MVO MVOI) x3 B |
| 6 | INCR (MVO MVOI) x2 B | E | INCR NOP x5 B (control) |
| 7 | INCR MVO MVO B | | |

(MVOI writes to its own operand word in the cartridge, which is never run.) Screen (2.5 s after
each 0.75 s round): per probe the ON (yellow) and OFF (white) passes in hex; N = rounds.

ON passes, k = 0 .. E:

| candidate | ON |
|---|---|
| **today's core (G82 rule)** | **1DE 111 108 13B 0F5 0C9 0F0 161 0E0 0CF 090 0E0 0B0 0B0 11E** |
| X-A / X-B (look-ahead rule) | 1E4 10F 10A 13E 0F6 0C9 0F1 163 0E1 0D0 090 0DD 0AF 0B2 122 |
| Y-B (G82 rule) | 1E4 111 10B 141 0F7 0CA 0F1 163 0E1 0D0 090 0E1 0B1 0B2 122 |
| M-A (grant after any instruction) | 1E1 10F 109 13D 0F5 0C8 0ED 160 0DC 0C8 08C 0DD 0AE 0AE 121 |
| X-B's structure with the "any" rule | 1E4 10F 10A 13E 0F6 0C8 0ED 160 0DD 0CA 08C 0DD 0AE 0AE 122 |
| F (section 8: the final fit) | 1E3 112 10A 141 0F7 0CA 0F1 162 0E1 0D0 091 0E1 0B1 0B1 122 |
| **console (2026-11-01; N = 18 and 19, identical)** | **1E4 111 108 142 0F7 0CA 0F2 163 0E1 000 090 0E1 0B1 0B2 122** |

Console OFF: 215 12C 126 15F 110 000 106 184 0F4 000 098 0F4 0C0 0C0 140. The ON column is G82's
(Y-B's within one or two at k = 2, 3, 6; X and M-A are off at k = 1, B, C): the bus is lent only
after interruptible instructions, as G82 says and today's core does. Probe 9 (ON and OFF) and
probe 5's OFF frame read 000, which no rule of the model gives (it predicts 0D0 / 0DD / 0DD):
the loop's count was 0 when the next interrupt came, or the ISR read it from elsewhere; section 11
looks at it.

On one structure (X-B's) the rules differ by 41 passes in all (G82 against any), 14 (G82
against look-ahead) and 27 (any against look-ahead), up to 6 at one probe: k = 6-A and D tell
"any" from the other two, k = 1-5, B and C tell G82 from the other two (the same on M-A's and
today's structures: 43-50, 14-22, 22-30). The controls (k = 0, E) only move with the frame's
structure. OFF passes are within one of 215 12C 126 15F 110 0DE 106 185 0F4 0DE 09B 0F4 0C0 0C0
140 for all.

## 11. hw_grantx: where the interrupt cuts hw_grant's probes 5 and 9

hw_grant's frames with six of its loops: 4 (MVO MVII) x2, 5 (MVO SDBD MVII) x2, 8 (MVO MVO) x2 B,
9 (MVO MVO) x2 NOP B, A (MVO MVO) x3 NOP NOP, 0 (control). The ISR keeps, per frame, the loop's
count (the interrupted R0, as in hw_grant) and the interrupted PC; the screen shows both for the
ON and OFF frame of each probe (hex: count, PC; ON yellow, OFF white) and the six loops'
addresses (50F2, 50FD, 510C / 5117, 5123, 5134: a PC inside a loop's range means the interrupt cut
it as intended; a PC at the probe's entry or padding, 5139-5173, or a count of 000, means the
interrupt came right after the ISR returned or the loop never ran).

| candidate | 4 ON / OFF | 5 | 8 | 9 | A | 0 |
|---|---|---|---|---|---|---|
| **today's core** | **0F5 50F7 / 10F 50FB** | **0C9 5104 / 0DD 510A** | **0E0 510C / 0F4 510C** | **0CF 5121 / 0DD 5121** | **090 5131 / 09B 5131** | **1DD 5135 / 214 5136** |
| F (section 8) | 0F7 50F7 / 10F 50F7 | 0C9 510A / 0DD 510A | 0E1 510C / 0F3 510C | 0D0 5121 / 0DD 5118 | 091 5131 / 09A 5131 | 1E2 5135 / 214 5135 |
| **console (2026-11-01; N = 14)** | **0F7 50FB / 10F 50F7** | **0C9 510A / 0DD 510A** | **0E1 510C / 0F4 510C** | **0D0 5121 / 0DD 5121** | **090 5131 / 09A 5132** | **1E3 5135 / 214 5135** |

No zeros: the loops of hw_grant's probes 5 and 9 count normally here, at F's counts (F's
residuals: counts 8 OFF -1, A ON +1, 0 ON -1; the cut lands one instruction off at 4 ON, 9 OFF
and A OFF). So the three 000s on hw_grant are not a property of those loops or of the grant
rule; they come from something only hw_grant does. What differs: hw_grant has three loops with
MVOI (k = 6, C, D) that write into seven of the cartridge's own words ($5129, $512D, $516E,
$5174, $517D, $5181, $5185, each MVOI's operand, never run); hw_grantx has none. Mapped as RAM
those writes change only data words, so either the PiRTO II reacts to writes into the cartridge
in some other way, or (with the same effect on the table) an extra interrupt right after an ISR
swallowed those frames: a count of 0 means the loop never ran before the interrupt. hw_grant's
27 non-zero values agree with F to within 2 passes (section 8), and the loops shared with
hw_grantx agree with it there, so they are kept. A hw_grant with the MVOI stores replaced by
MVO@ to System RAM (the same 9-cycle non-interruptible store) would show whether the cartridge
writes cause the zeros.

## On the RTL

All ten run in tb_system (`--only hw_steal,hw_intlate,hw_rowcopy,hw_cpuodd,hw_ecskeys,hw_frame,hw_steal2,hw_frame2,hw_grant,hw_grantx`; HW_IMAGES,
never in `--all`: 60 to 1,150 frames each) with the RTL equal to the model on every bus phase and
picture, straight and through the bench's save/restore round trips, at the core from 0.0.13
(2026-10-29): hw_steal 460 frames, hw_intlate 230, hw_rowcopy 1,150 (to step 12), hw_cpuodd 60,
hw_ecskeys 60 with ECS keys held (W; W+Q; W+Q+1; Shift+L) under Auto (attached); hw_frame (720
frames, to its first result screen) and hw_steal2 (130 frames, the first round shown) likewise on
2026-10-31 (`--only hw_frame,hw_steal2`), hw_frame2 (120 frames, the first round shown) and
hw_grant (130 frames) and hw_grantx (80 frames). So the screens the owner photographs are the
model's predictions above, exactly.
