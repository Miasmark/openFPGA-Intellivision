; hw_cpuodd: the CPU cases the documents leave open (docs/HW_TESTS.md 4; docs/CPU_NOTES.md
; "Where the sources disagree", rows 5, 6, 8, 9, 10, 14, 15). Each runs once with interrupts
; off at start-up and leaves a word; then the display comes on and shows them (hex):
;   NEGR 0   GSWD after NEGR of 0 (row 5: C set or not; S1/wiki C = 1: $5050, MAME $4040)
;   SWAP 2   SWAP R0, 2 of $1234 (row 6)
;   SDBD R6  SDBD + MVI@ R6, R0 over the stack words $11AA (lower), $22BB (upper) (row 8):
;            the word read, and how far R6 moved down
;   MVO SDBD SDBD + MVO $ABCD to M1 (cleared, M1 + 1 cleared too) (row 10): M1, M1 + 1
;   MVO@ R4  MVO@ R4, R4 with R4 = M2 (row 15): the word written at M2, and R4 after
;   SDBD DIR SDBD + MVI M3, R0 with M3 = $1357, R0 = M4 (M4 holds $00A1, $00B2) (row 9)
;   J II=3   a J with its interrupt bits 11 (row 14): taken (J) or not (N), then whether
;            interrupts came on (they were off before it)
; The last two are the riskiest (an unknown decode); they run last.
; SPDX-License-Identifier: MIT

R_NEG   EQU     VARS+0
R_SWAP  EQU     VARS+1
R_SDR6  EQU     VARS+2
R_SDR6D EQU     VARS+3
R_MVO1  EQU     VARS+4
R_MVO2  EQU     VARS+5
R_MVOP  EQU     VARS+6
R_MVOR4 EQU     VARS+7
R_SDDIR EQU     VARS+8
R_JTAK  EQU     VARS+9
R_JINT  EQU     VARS+10
TICKS   EQU     VARS+11         ; ISRs seen (the J case's interrupt check)
M1      EQU     VARS+16         ; 2 words
M2      EQU     VARS+18
M4      EQU     VARS+20         ; 2 words: $00A1, $00B2

isr:    PSHR    R5
        JSR     R5, stic_set
        MVO     R0, $0020
        MVI     TICKS, R0
        INCR    R0
        MVO     R0, TICKS
        PULR    R5
        JR      R5

main:   DIS
        JSR     R5, clrscr
        CLRR    R0
        MVII    #VARS, R4
        MVII    #24, R1
m_clr:  MVO@    R0, R4
        DECR    R1
        BNEQ    m_clr
; NEGR of 0
        CLRR    R0
        NEGR    R0
        GSWD    R1
        MVO     R1, R_NEG
; SWAP R0, 2
        MVII    #$1234, R0
        SWAP    R0, 2
        MVO     R0, R_SWAP
; SDBD + MVI@ R6
        MVII    #STACK, R6
        MVII    #$11AA, R0
        PSHR    R0
        MVII    #$22BB, R0
        PSHR    R0
        MOVR    R6, R2          ; R6 before
        CLRR    R0
        SDBD
        MVI@    R6, R0
        MVO     R0, R_SDR6
        SUBR    R6, R2          ; how far R6 moved down
        MVO     R2, R_SDR6D
        MVII    #STACK, R6
; SDBD + MVO direct
        MVII    #$ABCD, R0
        SDBD
        MVO     R0, M1
        MVI     M1, R0
        MVO     R0, R_MVO1
        MVI     M1+1, R0
        MVO     R0, R_MVO2
; MVO@ R4, R4
        MVII    #M2, R4
        MVO@    R4, R4
        MVO     R4, R_MVOR4
        MVI     M2, R0
        MVO     R0, R_MVOP
; SDBD + MVI direct (M3 = $1357 in ROM; R0 points at M4)
        MVII    #$00A1, R0
        MVO     R0, M4
        MVII    #$00B2, R0
        MVO     R0, M4+1
        MVII    #M4, R0
        SDBD
        MVI     M3, R0
        MVO     R0, R_SDDIR
; J with II = 3: taken -> jtak, else falls through to jnot
        MVII    #$004E, R0      ; 'N'
        MVO     R0, R_JTAK
        DIS
        DECLE   $0004, (3 << 8) | ((jtak >> 10) << 2) | 3, jtak & $3FF
jnot:   B       jdone
jtak:   MVII    #$004A, R0      ; 'J'
        MVO     R0, R_JTAK
jdone:  CLRR    R0              ; interrupts: off before the J; see if any ISR runs now
        MVO     R0, TICKS
        MVII    #3000, R1       ; about 3 frames of waiting
jw:     NOP
        DECR    R1
        BNEQ    jw
        MVI     TICKS, R0
        MVO     R0, R_JINT
        JSR     R5, labels
        EIS
mloop:  B       mloop

M3:     DECLE   $1357

labels: PSHR    R5
        MVII    #TAN, R3
        MVII    #t0, R1
        MVII    #BACKTAB+0*20, R4
        JSR     R5, puts
        MVII    #WHITE, R3
        MVII    #tl, R1         ; the names, rows 2-8
        MVII    #BACKTAB+2*20, R4
        MVII    #7, R2
lb_row: PSHR    R2
        PSHR    R4
        JSR     R5, puts
        PULR    R4
        ADDI    #20, R4
        PULR    R2
        DECR    R2
        BNEQ    lb_row
        MVII    #YELLOW, R3
        MVI     R_NEG, R0
        MVII    #BACKTAB+2*20+10, R4
        JSR     R5, puthex
        MVI     R_SWAP, R0
        MVII    #BACKTAB+3*20+10, R4
        JSR     R5, puthex
        MVI     R_SDR6, R0
        MVII    #BACKTAB+4*20+10, R4
        JSR     R5, puthex
        MVI     R_SDR6D, R0
        MVII    #BACKTAB+4*20+15, R4
        JSR     R5, puthex
        MVI     R_MVO1, R0
        MVII    #BACKTAB+5*20+10, R4
        JSR     R5, puthex
        MVI     R_MVO2, R0
        MVII    #BACKTAB+5*20+15, R4
        JSR     R5, puthex
        MVI     R_MVOP, R0
        MVII    #BACKTAB+6*20+10, R4
        JSR     R5, puthex
        MVI     R_MVOR4, R0
        MVII    #BACKTAB+6*20+15, R4
        JSR     R5, puthex
        MVI     R_SDDIR, R0
        MVII    #BACKTAB+7*20+10, R4
        JSR     R5, puthex
        MVI     R_JTAK, R0
        SUBI    #32, R0
        SLL     R0, 2
        SLL     R0, 1
        ADDI    #YELLOW, R0
        MVO     R0, BACKTAB+8*20+10
        MVI     R_JINT, R0
        MVII    #BACKTAB+8*20+15, R4
        JSR     R5, puthex
        MVII    #WHITE, R3
        MVII    #t10, R1
        MVII    #BACKTAB+10*20, R4
        JSR     R5, puts
        MVII    #M1, R0         ; the addresses used
        MVII    #BACKTAB+11*20+3, R4
        JSR     R5, puthex
        MVII    #M2, R0
        MVII    #BACKTAB+11*20+10, R4
        JSR     R5, puthex
        PULR    R7
t0:     STRING  "HW CPUODD  UNDEFINED"
        DECLE   0
tl:     STRING  "NEGR 0"
        DECLE   0
        STRING  "SWAP 2"
        DECLE   0
        STRING  "SDBD R6"
        DECLE   0
        STRING  "MVO SDBD"
        DECLE   0
        STRING  "MVO@ R4"
        DECLE   0
        STRING  "SDBD DIR"
        DECLE   0
        STRING  "J II=3"
        DECLE   0
t10:    STRING  "M1   M2"
        DECLE   0
