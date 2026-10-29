; hw_steal: the CPU cycles the STIC takes in a frame (docs/HW_TESTS.md 1; docs/STIC_NOTES.md
; T1, T2, T4; the bus request exit of docs/CPU_NOTES.md). Phases of 128 frames alternate:
; display off (no bus requests: a blank screen) and display on. In each phase the main loop
; counts its passes (52 cycles a pass: MVI, INCR, MVO, MVI, TSTR, BEQ) from the ISR of frame 8
; to that of frame 128 (120 frames; the first 8 leave time for the screen update); the ISR
; costs the same in both phases. OFF - ON passes x 52 / 120 = the cycles a frame the STIC
; takes from the CPU. The screen (seen in the display-on phases) shows the last count of
; each phase and their minimum and maximum over the run.
; SPDX-License-Identifier: MIT

MODE    EQU     VARS+0          ; 1: this phase has the display on
FCNT    EQU     VARS+1          ; ISRs in this phase
CNT     EQU     VARS+2          ; the main loop's passes (wraps)
SNAP0   EQU     VARS+3          ; CNT at the phase's frame 8
NEWRES  EQU     VARS+4          ; 1: a phase ended
RES_OFF EQU     VARS+5
RES_ON  EQU     VARS+6
MIN_OFF EQU     VARS+7
MAX_OFF EQU     VARS+8
MIN_ON  EQU     VARS+9
MAX_ON  EQU     VARS+10
RUNS    EQU     VARS+11         ; phases ended

isr:    PSHR    R5
        JSR     R5, stic_set
        MVI     MODE, R0        ; the same cycles in both phases:
        TSTR    R0
        BEQ     i_off
        MVO     R0, $0020       ;   on: display enable (7 + 11 + 9)
        B       i_c
i_off:  MVO     R0, $0021       ;   off: Color Stack mode again (9 + 11 + 7)
        NOPP
i_c:    MVI     FCNT, R1
        INCR    R1
        MVO     R1, FCNT
        CMPI    #8, R1
        BNEQ    i_n8
        MVI     CNT, R2
        MVO     R2, SNAP0
i_n8:   CMPI    #128, R1
        BNEQ    i_ret
        MVI     CNT, R2         ; the phase's count: frames 8-127
        MVI     SNAP0, R1
        SUBR    R1, R2
        TSTR    R0
        BEQ     i_eoff
        MVO     R2, RES_ON
        B       i_e
i_eoff: MVO     R2, RES_OFF
i_e:    XORI    #1, R0
        MVO     R0, MODE
        CLRR    R1
        MVO     R1, FCNT
        MVII    #1, R1
        MVO     R1, NEWRES
        MVI     RUNS, R1
        INCR    R1
        MVO     R1, RUNS
i_ret:  PULR    R5
        JR      R5

main:   JSR     R5, clrscr
        CLRR    R0
        MVII    #VARS, R4
        MVII    #16, R1
m_clr:  MVO@    R0, R4
        DECR    R1
        BNEQ    m_clr
        MVII    #$FFFF, R0
        MVO     R0, MIN_OFF
        MVO     R0, MIN_ON
        JSR     R5, labels
        EIS
m_loop: MVI     CNT, R0         ; 52 cycles a pass
        INCR    R0
        MVO     R0, CNT
        MVI     NEWRES, R1
        TSTR    R1
        BEQ     m_loop
        CLRR    R1
        MVO     R1, NEWRES
        JSR     R5, show
        B       m_loop

; min / max of a result: R0 the result, R4 the address of its MIN (MAX follows)
minmax: TSTR    R0
        BEQ     mm_end          ; no result yet
        MVI@    R4, R1
        CMPR    R1, R0
        BC      mm_nmin         ; R0 >= MIN
        DECR    R4
        MVO@    R0, R4
mm_nmin:
        MVI@    R4, R1
        CMPR    R0, R1
        BC      mm_end          ; MAX >= R0
        DECR    R4
        MVO@    R0, R4
mm_end: JR      R5

show:   PSHR    R5
        MVI     RES_OFF, R0
        MVII    #MIN_OFF, R4
        JSR     R5, minmax
        MVI     RES_ON, R0
        MVII    #MIN_ON, R4
        JSR     R5, minmax
        MVII    #WHITE, R3
        MVI     RES_OFF, R0
        MVII    #BACKTAB+3*20+7, R4
        JSR     R5, putdec
        MVI     MIN_OFF, R0
        MVII    #BACKTAB+4*20+7, R4
        JSR     R5, putdec
        MVI     MAX_OFF, R0
        MVII    #BACKTAB+5*20+7, R4
        JSR     R5, putdec
        MVI     RES_ON, R0
        MVII    #BACKTAB+7*20+7, R4
        JSR     R5, putdec
        MVI     MIN_ON, R0
        MVII    #BACKTAB+8*20+7, R4
        JSR     R5, putdec
        MVI     MAX_ON, R0
        MVII    #BACKTAB+9*20+7, R4
        JSR     R5, putdec
        MVII    #YELLOW, R3
        MVI     RES_OFF, R0
        MVI     RES_ON, R1
        SUBR    R1, R0
        MVII    #BACKTAB+10*20+5, R4
        JSR     R5, putdec
        MVII    #WHITE, R3
        MVI     RUNS, R0
        MVII    #BACKTAB+10*20+14, R4
        JSR     R5, putdec
        PULR    R7

labels: PSHR    R5
        MVII    #TAN, R3
        MVII    #t0, R1
        MVII    #BACKTAB+0*20, R4
        JSR     R5, puts
        MVII    #WHITE, R3
        MVII    #t2, R1
        MVII    #BACKTAB+2*20, R4
        JSR     R5, puts
        MVII    #t3, R1
        MVII    #BACKTAB+3*20+1, R4
        JSR     R5, puts
        MVII    #t4, R1
        MVII    #BACKTAB+4*20+1, R4
        JSR     R5, puts
        MVII    #t5, R1
        MVII    #BACKTAB+5*20+1, R4
        JSR     R5, puts
        MVII    #t6, R1
        MVII    #BACKTAB+6*20, R4
        JSR     R5, puts
        MVII    #t3, R1
        MVII    #BACKTAB+7*20+1, R4
        JSR     R5, puts
        MVII    #t4, R1
        MVII    #BACKTAB+8*20+1, R4
        JSR     R5, puts
        MVII    #t5, R1
        MVII    #BACKTAB+9*20+1, R4
        JSR     R5, puts
        MVII    #t10, R1
        MVII    #BACKTAB+10*20, R4
        JSR     R5, puts
        MVII    #t11, R1
        MVII    #BACKTAB+11*20, R4
        JSR     R5, puts
        PULR    R7
t0:     STRING  "HW STEAL  STIC STEAL"
        DECLE   0
t2:     STRING  "DISPLAY OFF"
        DECLE   0
t3:     STRING  "LAST"
        DECLE   0
t4:     STRING  "MIN"
        DECLE   0
t5:     STRING  "MAX"
        DECLE   0
t6:     STRING  "DISPLAY ON"
        DECLE   0
t10:    STRING  "DIFF       N"
        DECLE   0
t11:    STRING  "52 CYC  120 FRAMES"
        DECLE   0
