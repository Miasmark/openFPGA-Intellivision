# Console timing fit (2026-11-01)

The STIC's bus requests, the CPU's grant rule, the frame and the interrupt path, fitted to the
owner's Model 2609 (PiRTO II, CRT) on the hardware measurement cartridges of docs/HW_TESTS.md:
hw_steal (1), hw_intlate (2), hw_rowcopy (3), hw_steal2 (7), hw_frame / hw_frame2 (6, 9),
hw_grant / hw_grantx (10, 11). The fit runs the Python model as a simulator with what-if
options (a copy of the tools outside the repository) and searches its parameters against all
console screens together. The model (modes `stic` and `none`) and the RTL follow F since
2026-11-01 (branch timingF; "Changes to make" below, as done; mode `mame` unchanged).

## The fitted family F

Cycles from INTRM (the frame start the CPU sees). Today's core in brackets.

| What | F | Evidence |
|---|---|---|
| frame | 14,934 cycles, 57 x 262 [same] | hw_frame2 FRAME CYC 14934 (the length between two interrupt samplings, no interrupt sequence in it) |
| interrupt sequence | 9 cycles [same] | with the next two rows: hw_steal's OFF count (the main loop gets 14,487 cycles a frame: frame - interrupt path = 14,922 with the model's ISR instructions) |
| SDBD + MVI@ R4, R7 | 15 cycles [14] | hw_frame2 SDBD JUMP 15 |
| JSR, PULR R7 | 13, 12 cycles [12, 11] | the 2 cycles the interrupt path still needs after the jump; each ISR of ours and the EXEC's dispatcher have one JSR and one PULR R7. Not separable from an 11-cycle interrupt sequence (one fit point worse) |
| BUSRQ grant | only after an interruptible instruction (G82 p.11, 2.5.5) [same] | hw_grant's ON column: G82's pattern at every probe (after any instruction, the MAME fork's rule, is 3-6 passes off at the MVO loops) |
| row requests | 12, none with VDR = 0's 13th [13 with VDR = 0] | hw_intlate (the last request no longer runs into the next frame), hw_steal, hw_steal2 |
| row r request | from 3,926 + 912 r, 107 cycles, released at 4,033 + 912 r [3,876 + 912 r, 114, released 3,990 + 912 r] | hw_steal ON 30280, hw_steal2, hw_rowcopy, hw_intlate |
| exit | 2 NACTs after the release: the CPU resumes at 4,035 + 912 r [2 NACTs, 3,992 + 912 r] | only release + exit is visible (see below) |
| frame request | 3,792-3,891 (100 cycles), separate from row 0's [3,790-3,831, 42] | hw_steal2, hw_steal, hw_rowcopy |
| display enable latched | at the end of cycle 3,790 [3,789] | the frame request's place (one cycle; not separately seen) |
| register window | open in VBlank, and all frame while the frame's display is off; closed from the end of VBlank to the next frame start only in a frame whose display is on [closed whenever the handshake is set] | hw_frame2: mid-frame reads 0000 (display on), 3FF1 (display off), 3FF1 after a late $20 write; hw_frame's NO EDGE |
| closed STIC register read | $0000 [the address offset] | hw_frame2 ($2C read mid-frame, display on: 0000) |
| masked VBlank request | dropped when INTRM rises (DIS across a VBlank, EIS after: no interrupt) [same] | hw_frame2's W row |

Residuals of F: hw_steal 33431 / 30280 in every phase, hw_intlate 1C 1B 1B 1B 1B 1B, hw_rowcopy
all 24 steps, hw_frame2's V, W, U rows: exact. hw_steal2: 5 passes in 30 values (one each). hw_grant:
11 in its 27 non-zero values (at most 2 at one probe). hw_grantx: 3 counts off by one in 12, 3 of
12 interrupt points one instruction off. hw_grant's three 000s are not explained (HW_TESTS 11:
the same loops count normally in hw_grantx; hw_grant alone writes into its cartridge words).

## Not observable (choices to make, any value fits)

- The exit NACTs against the release: only their sum, the cycle the CPU resumes, is seen. Keep
  2 NACTs (S1 p.36, G82 Fig. 16) and the releases above.
- Where in a request the row is copied: the CPU is stopped from its grant to the release, so
  no CPU-side test sees it. The fit copies at 3,976 + 912 r (57 before the release; the row must
  load if the grant came by then, T10), in time for picture line 70 + 16 r.
- The split of the interrupt path's last 2 cycles between JSR, PULR R7 and the interrupt
  sequence; whether J (not only JSR), other MVI@ to R7, MVII to R7 are also one cycle longer.
- GRAM's closed reads (only $2C was read); presumably $0000 as well.
- The INTRM sampling point against the STIC's events: folded into the positions above (all
  relative to INTRM).

## Changes to make

Done on branch timingF (2026-11-01) as listed, with these details: the STIC's positions are
folded one cycle later against INTRM (INTRM stays 0-3,789; the register window is 0-3,790);
the fetch is at request + 50 (`FETCH_OFF`); the CPU's extra cycle is a NACT at the end of the
whole jump family ($004), PULR R7 (with or without SDBD) and SDBD + MVI@ R4 or R5, R7, in the
model's timing `f` (timing `doc` keeps the documents' counts for the MAME comparisons); closed
GRAM reads give $0000 as the STIC's; the RTL's card engine builds a line at pixel clocks
176-195 of the line before (after the row copy, now at the line's slot 43); no new save state
(the STIC's `en_l` is the window's latch, the CPU's `jpt` marks a read's extra cycle).
On the model, hw_frame (section 6 of HW_TESTS) does not show the console's "NO EDGE": its first
poll loop (`ms_cl`) waits for the registers to close after a $20 write in VBlank of a frame with
interrupts off, and in F that frame's display is on, so they close at 3,791 and the program goes
on (with a late $20 write leaving the registers open, its later polls then see "open" at once
and count one pass a frame: FAIL 0, S_F = S_I = 224). The console never saw them close. One
reading that fits every result so far (a hypothesis, not in F): the $20 handshake enables the
display only in a frame whose VBlank interrupt was taken (GI80 p.5-18: the bus copy starts at
INTAK); hw_frame's measured frames have no INTAK, hw_frame2's display-on frames do. A test: a
display-on frame entered with interrupts off ($20 in VBlank, no ISR), then a mid-frame $2C read.

**Model** (tools/):
- stic.py: rows 12 with any VDR (`schedule`: no 13th request); ROW0_REQ 3,926, ROW_HOLD 107
  (release 4,033 + 912 r), the fetch at request + 50; FRAME_BUSRQ 100 from 3,792 (a separate
  request, not merged with row 0); VBLANK 3,791 (the register window cycles 0-3,790, the
  display enable latched at its end).
- cp1610.py: SDBD + MVI@ R4, R7 15 cycles, JSR 13, PULR R7 12 (or INTERRUPT_CYCLES 11 instead
  of the last two); the grant rule and BUSRQ_EXIT stay.
- intv_system.py: the register window open = in VBlank or the frame's display off (not the
  handshake); closed STIC reads $0000 (and, unmeasured, GRAM).

**RTL** (src/fpga/core/): the same in intv_stic.sv (request schedule: 12 rows, 3,926 / 107, the
frame request 3,792 / 100, the latch at 3,790; the window gate on the frame's display state; the
closed read value) and cp1610.sv (the three cycle counts). The STIC's picture timing (row copy
before line 70 + 16 r) is unchanged.

**The MAME fork** (Miasmark/mame-Atari8bit7800, atari-0.289 at 0a6a1bf1) to match F:
- src/devices/cpu/cp1610/cp1610.cpp:3371-3386 (`take_requests`): lend the bus only after an
  interruptible instruction (move the BUSRQ block below the `m_mask_interrupts` test at 3389).
- cp1610.cpp:1100 (`cp1610_pulr`): 12 cycles when d = 7; cp1610.cpp:1539 (`cp1610_sdbd_mviat_i`):
  15 when d = 7; cp1610.cpp:2163 (jumps): 13 (at least for JSR).
- src/mame/mattel/stic.h:49 ROW_BUSRQ 110 -> 107; stic.h:52 FIRST_FETCH 3933 -> 3926 (the row
  request's start; intv_m.cpp:667 and 678 schedule from it); FRAME_BUSRQ (stic.h:50) stays 100
  but starts 2 cycles after VBLANK_END: intv_m.cpp:665 (`bus_request` in `interrupt_complete`).
- intv_m.cpp:486, 494, 502, 510: gate STIC and GRAM accesses on the frame's display state
  latched in `interrupt_complete` (662) and cleared in `interrupt` (715), not on the handshake;
  intv_m.cpp:489 and 505: a closed read returns 0, not `offset`.
- Already as F: 12 rows (intv_m.cpp:677), the 2 exit cycles (cp1610.cpp:3379), the frame of
  14,934 cycles (intv.cpp:458).
