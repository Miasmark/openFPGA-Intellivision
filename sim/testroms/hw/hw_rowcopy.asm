; hw_rowcopy: when the STIC copies each card row from BACKTAB (docs/HW_TESTS.md 3;
; docs/STIC_NOTES.md T5, T10). Every frame is the same, so the picture stands still:
;   the ISR (constant time, display on) fills rows 0-10 with the OLD pattern (white '-', the
;   row number in column 0) and returns into the writer;
;   the writer waits a delay, then writes the NEW pattern (red '#') over rows 0-10, top to
;   bottom, one word every 15 cycles (MVO@ + NOP); then it waits in sloop (B sloop) through
;   the rows, whose bus requests fix the phase of the next frame's interrupt.
; The STIC copies a row in one go while the CPU is stopped, so each row shows what the writer
; had written by then: the rows above the writer show '#' to the end, the row being written
; shows '#' up to the column the writer had reached (one column = 15 cycles), the rows below
; show '-'. The delay grows by 15 cycles a step (24 steps of HOLDF frames, the step in row 11),
; so the mixed row's edge moves one column left a step (the writer later); the step where it
; moves to the next row and the columns give the copy cycle of that row to 15 cycles. Rows 0-10 only (row 11 is the status line).
; SPDX-License-Identifier: MIT

STEPN   EQU     24              ; delay steps of 15 cycles (one column)
HOLDF   EQU     90              ; frames per step
DLOOP   EQU     148             ; delay loop passes (15 cycles each) at step 0

STEP    EQU     VARS+0
HOLD    EQU     VARS+1
OLDW    EQU     ('-'-32)*8+WHITE
NEWW    EQU     ('#'-32)*8+RED

isr:    PSHR    R5
        JSR     R5, stic_set
        MVO     R0, $0020       ; display on
        MVII    #BACKTAB, R4    ; OLD over rows 0-10 (constant time)
        MVII    #(('0'-32)*8+WHITE), R2
        MVII    #11, R1
        MVII    #OLDW, R0
i_row:  MVO@    R2, R4          ; the row number (0-9, then ':')
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        MVO@    R0, R4
        ADDI    #8, R2
        DECR    R1
        BNEQ    i_row
        MVII    #writer, R0
        MVO     R0, STACK       ; return into the writer
        PULR    R5
        JR      R5

; the writer: a delay of 15 x (DLOOP + STEP) cycles, then NEW, one word every 15 cycles
; (MVO@ and an interruptible NOP: a row request is answered within 15 cycles, well inside the
; 57-cycle deadline of STIC_NOTES T10, so no row is missed)
writer: MVI     STEP, R1        ; constant time: DLOOP + STEP passes of 15 cycles
        ADDI    #DLOOP, R1
w_go:   DECR    R1
        BNEQ    w_go
        MVII    #BACKTAB, R4
        MVII    #(('0'-32)*8+YELLOW), R2
        MVII    #11, R1
        MVII    #NEWW, R0
w_row:  MVO@    R2, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        MVO@    R0, R4
        NOP
        ADDI    #8, R2
        DECR    R1
        BNEQ    w_row
        MVI     HOLD, R0        ; the step: STEPN steps of HOLDF frames
        DECR    R0
        BNEQ    w_hold
        MVI     STEP, R1
        INCR    R1
        CMPI    #STEPN, R1
        BLT     w_st
        CLRR    R1
w_st:   MVO     R1, STEP
        MVII    #HOLDF, R0
w_hold: MVO     R0, HOLD
        MVII    #TAN, R3        ; row 11: STEP xx
        MVII    #t11, R1
        MVII    #BACKTAB+11*20, R4
        JSR     R5, puts
        MVI     STEP, R0
        MVII    #WHITE, R3
        MVII    #BACKTAB+11*20+5, R4
        JSR     R5, puthex
sloop:  B       sloop

main:   JSR     R5, clrscr
        CLRR    R0
        MVO     R0, STEP
        MVII    #HOLDF, R0
        MVO     R0, HOLD
        EIS
        B       sloop
t11:    STRING  "STEP       ROWCOPY"
        DECLE   0
