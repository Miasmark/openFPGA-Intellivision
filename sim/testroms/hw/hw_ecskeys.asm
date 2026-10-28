; hw_ecskeys: the ECS keyboard matrix, raw, live (docs/HW_TESTS.md 5; docs/ECS_NOTES.md; the
; 0.0.9 test sheet B2). Needs the ECS. The main loop scans the keyboard through the ECS's
; sound chip (PSG #2, $00F0-$00FF; $00F8 = its R7: bit 6 port A an output, bit 7 port B):
;   left grid  A>B: port A drives row r low (the others high), port B is read: columns 0-7
;   right grid B>A: port B drives column c low, port A is read: rows 0-7
; '#' = the line reads 0, '.' = 1. Hold keys and photograph: the ECS ROM scans A>B; a key that
; shares its column with another held key can vanish from a row (masking), and three keys at
; the corners of a rectangle can show the fourth (ghosting). The key positions (row = port A
; bit, column = port B bit) are in tools/ecs.py KEYPOS.
; SPDX-License-Identifier: MIT

DOT     EQU     ('.'-32)*8+WHITE
HASH    EQU     ('#'-32)*8+YELLOW

isr:    PSHR    R5
        JSR     R5, stic_set
        MVO     R0, $0020
        PULR    R5
        JR      R5

main:   JSR     R5, clrscr
        JSR     R5, labels
        MVII    #$3F, R0        ; PSG #2 silent: tones and noise off, volumes 0
        MVO     R0, $00F8
        CLRR    R0
        MVO     R0, $00FB
        MVO     R0, $00FC
        MVO     R0, $00FD
        EIS
m_scan: MVII    #$7F, R0        ; A>B: port A out
        MVO     R0, $00F8
        CLRR    R2              ; row
        MVII    #BACKTAB+2*20+2, R4
ab_row: MVII    #1, R1          ; ~(1 << row) to port A
        MOVR    R2, R3
        TSTR    R3
        BEQ     ab_sh0
ab_sh:  SLL     R1, 1
        DECR    R3
        BNEQ    ab_sh
ab_sh0: COMR    R1
        ANDI    #$FF, R1
        MVO     R1, $00FE
        NOP
        NOP
        MVI     $00FF, R0       ; columns
        JSR     R5, putbits
        ADDI    #12, R4         ; next row: 20 - 8
        INCR    R2
        CMPI    #8, R2
        BLT     ab_row
        MVII    #$BF, R0        ; B>A: port B out
        MVO     R0, $00F8
        CLRR    R2              ; column
        MVII    #BACKTAB+2*20+11, R4
ba_col: MVII    #1, R1
        MOVR    R2, R3
        TSTR    R3
        BEQ     ba_sh0
ba_sh:  SLL     R1, 1
        DECR    R3
        BNEQ    ba_sh
ba_sh0: COMR    R1
        ANDI    #$FF, R1
        MVO     R1, $00FF
        NOP
        NOP
        MVI     $00FE, R0       ; rows
        JSR     R5, putbits
        ADDI    #12, R4
        INCR    R2
        CMPI    #8, R2
        BLT     ba_col
        B       m_scan

; putbits: R0's bits 0-7 as 8 cells at R4 ('#' for 0); R4 advances 8. Uses R0, R1, R3.
putbits:
        MVII    #8, R3
pb_lp:  MOVR    R0, R1
        ANDI    #1, R1
        BEQ     pb_h
        MVII    #DOT, R1
        B       pb_put
pb_h:   MVII    #HASH, R1
pb_put: MVO@    R1, R4
        SLR     R0, 1
        DECR    R3
        BNEQ    pb_lp
        JR      R5

labels: PSHR    R5
        MVII    #TAN, R3
        MVII    #t0, R1
        MVII    #BACKTAB+0*20, R4
        JSR     R5, puts
        MVII    #WHITE, R3
        MVII    #t1, R1
        MVII    #BACKTAB+1*20, R4
        JSR     R5, puts
        CLRR    R2              ; the row numbers 0-7 in column 0
        MVII    #BACKTAB+2*20, R4
lb_lp:  MOVR    R2, R0
        SLL     R0, 2
        SLL     R0, 1
        ADDI    #('0'-32)*8+TAN, R0
        MVO@    R0, R4
        ADDI    #19, R4
        INCR    R2
        CMPI    #8, R2
        BLT     lb_lp
        MVII    #t10, R1
        MVII    #BACKTAB+10*20, R4
        JSR     R5, puts
        MVII    #t11, R1
        MVII    #BACKTAB+11*20, R4
        JSR     R5, puts
        PULR    R7
t0:     STRING  "HW ECSKEYS   MATRIX"
        DECLE   0
t1:     STRING  "  A>B COL  B>A ROW"
        DECLE   0
t10:    STRING  "  01234567 01234567"
        DECLE   0
t11:    STRING  "# = LINE READS 0"
        DECLE   0
