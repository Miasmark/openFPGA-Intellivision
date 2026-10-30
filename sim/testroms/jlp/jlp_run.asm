; jlp_run.asm: the JLP measurement cartridges' interpreter (sim/testroms/jlp/build_jlp.py;
; docs/JLP_NOTES.md 4). build_jlp.py puts hwlib.asm (sim/testroms/hw/) in front and a test
; table behind (`table`, `ttl`, `pollsrc`). With interrupts off the interpreter runs the
; table, three words an entry, and keeps each result word from VARS ($0300) on (64 at most):
;   0               the end
;   1  addr value   write value to addr
;   2  addr -       read addr: one result
;   3  cmd  key     a flash command: write key to cmd and read cmd until it is not $FFFF,
;                   from System RAM (POLL: the cartridge is silent while the JLP is busy);
;                   two results: the reads it took, the value read last
;   4  addr base    write base, base + 1, ... to the 96 words from addr
;   5  addr -       the 96 words from addr: two results, the first word and their sum
; Then the display comes on and shows the results as hex, three a row after the index of
; the first, 33 a page; the pages turn every 150 frames (about 2.5 s). The title row shows
; the program's name and the page number.
; SPDX-License-Identifier: MIT

POLL    EQU     $0340           ; the poll routine's copy in System RAM (8 words)
RP      EQU     $0350           ; the next result's address
NRES    EQU     $0351
NPG     EQU     $0352
PAGE    EQU     $0353
PT      EQU     $0354           ; frames on this page
SHOWN   EQU     $0355
BI      EQU     $0356           ; drawing: the result index
ROWP    EQU     $0357           ; drawing: the row's BACKTAB address
KC      EQU     $0358           ; drawing: results left on the row
PERPG   EQU     33

isr:    PSHR    R5
        JSR     R5, stic_set
        MVO     R0, $0020
        MVI     PT, R0
        INCR    R0
        CMPI    #150, R0
        BNEQ    is_s
        CLRR    R0
        MVI     PAGE, R1
        INCR    R1
        CMP     NPG, R1
        BNC     is_p
        CLRR    R1
is_p:   MVO     R1, PAGE
is_s:   MVO     R0, PT
        PULR    R5
        JR      R5

main:   DIS
        JSR     R5, clrscr
        MVII    #pollsrc, R4    ; the poll routine into System RAM
        MVII    #POLL, R5
        MVII    #8, R1
m_cp:   MVI@    R4, R0
        MVO@    R0, R5
        DECR    R1
        BNEQ    m_cp
        MVII    #VARS, R0
        MVO     R0, RP
        MVII    #table, R4
run:    MVI@    R4, R0          ; op
        TSTR    R0
        BEQ     done
        MVI@    R4, R1          ; addr
        MVI@    R4, R2          ; value
        CMPI    #1, R0
        BEQ     op_w
        CMPI    #2, R0
        BEQ     op_r
        CMPI    #3, R0
        BEQ     op_f
        CMPI    #4, R0
        BEQ     op_fl
; 5: the first word and the sum of 96
        MOVR    R1, R5
        CLRR    R2
        MVII    #96, R3
sm_lp:  MVI@    R5, R0
        ADDR    R0, R2
        DECR    R3
        BNEQ    sm_lp
        MVI@    R1, R0
        JSR     R5, keep
        MOVR    R2, R0
        JSR     R5, keep
        B       run
op_w:   MVO@    R2, R1
        B       run
op_r:   MVI@    R1, R0
        JSR     R5, keep
        B       run
op_f:   CLRR    R3
        JSR     R5, POLL        ; R1 command, R2 key; R3 counts the reads, R0 the last
        PSHR    R0
        MOVR    R3, R0
        JSR     R5, keep
        PULR    R0
        JSR     R5, keep
        B       run
op_fl:  MOVR    R1, R5
        MVII    #96, R3
fl_lp:  MVO@    R2, R5
        INCR    R2
        DECR    R3
        BNEQ    fl_lp
        B       run

; keep: R0 as the next result (none past 64). Uses R3.
keep:   MVI     RP, R3
        CMPI    #VARS+64, R3
        BC      kp_x
        MVO@    R0, R3
        INCR    R3
        MVO     R3, RP
kp_x:   JR      R5

done:   MVI     RP, R0
        SUBI    #VARS, R0
        MVO     R0, NRES
        CLRR    R1
pg_lp:  INCR    R1
        SUBI    #PERPG, R0
        BGT     pg_lp
        MVO     R1, NPG
        CLRR    R0
        MVO     R0, PAGE
        MVO     R0, PT
        MVII    #$FFFF, R0
        MVO     R0, SHOWN
        EIS
ml:     MVI     PAGE, R0
        CMP     SHOWN, R0
        BEQ     ml
        MVO     R0, SHOWN
        JSR     R5, draw
        B       ml

; draw: the page PAGE
draw:   PSHR    R5
        JSR     R5, clrscr
        MVII    #TAN, R3
        MVII    #ttl, R1
        MVII    #BACKTAB, R4
        JSR     R5, puts
        INCR    R4
        MVI     PAGE, R0
        INCR    R0
        JSR     R5, puthex
        CLRR    R2
        MVI     PAGE, R1
dr_m:   TSTR    R1
        BEQ     dr_b
        ADDI    #PERPG, R2
        DECR    R1
        B       dr_m
dr_b:   MVO     R2, BI
        MVII    #BACKTAB+20, R0
        MVO     R0, ROWP
dr_row: MVI     BI, R0
        CMP     NRES, R0
        BC      dr_end
        MVI     ROWP, R4
        MVII    #WHITE, R3
        JSR     R5, puthex
        MVII    #3, R1
        MVO     R1, KC
dr_k:   INCR    R4
        MVI     BI, R0
        CMP     NRES, R0
        BC      dr_nx
        ADDI    #VARS, R0
        MOVR    R0, R5
        MVI@    R5, R0
        MVII    #YELLOW, R3
        JSR     R5, puthex
        MVI     BI, R0
        INCR    R0
        MVO     R0, BI
        MVI     KC, R1
        DECR    R1
        MVO     R1, KC
        BNEQ    dr_k
dr_nx:  MVI     ROWP, R0
        ADDI    #20, R0
        MVO     R0, ROWP
        CMPI    #BACKTAB+240, R0
        BNEQ    dr_row
dr_end: PULR    R7
