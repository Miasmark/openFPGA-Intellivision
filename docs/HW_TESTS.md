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
| A, SI-A, IR-A (12-cycle interrupt) | 14934 | 224 | 238 | 12 | 122C 0EAC 0E74 |
| A' (the dispatcher's SDBD + MVI@ R4, R7 three cycles longer) | 14934 | 224 | 241 | 9 | 122C 0EAC 0E68 |
| B, SI-B, IR-B (frame 14,931) | 14931 | 221 | 238 | 9 | 1220 0EAC 0E68 |

So the console's FRAME CYC settles A against B at once (14,934 or 14,931), and IRQ ENTRY / COPY
PATH tell a longer interrupt sequence (A) from a slower instruction in the dispatcher (A').

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

No variant tried matches all three console results (the search, about 3,000 model runs: hold
lengths, frame request starts, lengths and merging, exit NACTs, the 12-row case, a request held a
fixed time from BUSAK, BUSRQ taken after non-interruptible instructions; the last two contradict
the console's stable hw_intlate or G82's "only after the completion of an interruptable
instruction"). hw_frame settles A / A' / B; hw_steal2 then shows the requests' shape directly.

## On the RTL

All five run in tb_system (`--only hw_steal,hw_intlate,hw_rowcopy,hw_cpuodd,hw_ecskeys`; HW_IMAGES,
never in `--all`: 60 to 1,150 frames each) with the RTL equal to the model on every bus phase and
picture, straight and through the bench's save/restore round trips, at the core from 0.0.13
(2026-10-29): hw_steal 460 frames, hw_intlate 230, hw_rowcopy 1,150 (to step 12), hw_cpuodd 60,
hw_ecskeys 60 with ECS keys held (W; W+Q; W+Q+1; Shift+L) under Auto (attached). So the screens the
owner photographs are the model's predictions above, exactly.
