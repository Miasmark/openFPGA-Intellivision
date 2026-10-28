; hw_intlate: where the VBlank interrupt is taken, to the cycle (docs/HW_TESTS.md 2;
; docs/CPU_NOTES.md open point 1: the sampling point of INTRM). Frames alternate in pairs:
;   lock frame (display on): the main code waits in `sloop` (B sloop, 9 cycles) while the STIC
;     fetches its rows; each row's bus request stops the CPU until a fixed cycle of the frame,
;     so after the last row the CPU's phase in the frame no longer depends on the past, and
;     the next interrupt comes at a known cycle of sloop;
;   probe frame (display off: no bus requests): its ISR (constant time) returns into probe k
;     (k = 0..5): 24 + k cycles of padding, a delay loop, then a train of TRAIN x INCR R0
;     (6 cycles each, interruptible) that the next VBlank interrupt cuts; the next ISR reads
;     the interrupted PC (the CPU pushes it at STACK) and keeps idx = PC - train.
; Each extra cycle of padding moves the train one cycle later against the frame, so over k
; = 0..5 idx steps down by one at one k: where it steps is where the CPU samples the request
; within an instruction (with the frame's length and the bus-request exit, which hw_steal
; measures). After the 6 probes the display stays on for SHOWF frames (the photo).
; SPDX-License-Identifier: MIT

TRAIN   EQU     60              ; INCRs in the train
DELAYN  EQU     959             ; delay loop passes (15 cycles each): the train around VBlank
SHOWF   EQU     120             ; frames shown between rounds of 6 probes

PHASE   EQU     VARS+0          ; 1: the next ISR is a probe frame's
WASP    EQU     VARS+1          ; 1: the frame just ended was a probe frame
KIDX    EQU     VARS+2          ; the probe 0..5
SHOW    EQU     VARS+3          ; frames still to show before the next round
RUNS    EQU     VARS+4          ; rounds done
LASTS   EQU     VARS+8          ; idx per k (6)
MINS    EQU     VARS+16         ; minimum per k (6)
MAXS    EQU     VARS+24         ; maximum per k (6)

isr:    PSHR    R5
        MVI     PHASE, R0
        TSTR    R0
        BNEQ    i_prb
; ---- a lock frame (also the frame after a probe)
        JSR     R5, stic_set
        MVO     R0, $0020       ; display on: its rows lock the phase
        MVI     WASP, R1
        TSTR    R1
        BEQ     i_next
        CLRR    R1
        MVO     R1, WASP
        MVI     STACK, R0       ; the PC the probe was interrupted at
        SUBI    #train, R0      ; idx
        MVI     KIDX, R2
        MOVR    R2, R4
        ADDI    #LASTS, R4
        MVO@    R0, R4
        MOVR    R2, R4
        ADDI    #MINS, R4
        MVI@    R4, R1
        CMPR    R1, R0
        BC      i_nmin
        DECR    R4
        MVO@    R0, R4
i_nmin: MOVR    R2, R4
        ADDI    #MAXS, R4
        MVI@    R4, R1
        CMPR    R0, R1
        BC      i_nmax
        DECR    R4
        MVO@    R0, R4
i_nmax: INCR    R2
        CMPI    #6, R2
        BLT     i_k
        CLRR    R2
        MVII    #SHOWF, R1
        MVO     R1, SHOW
        MVI     RUNS, R1
        INCR    R1
        MVO     R1, RUNS
i_k:    MVO     R2, KIDX
i_next: MVI     SHOW, R1        ; the next frame: shown, or a probe
        TSTR    R1
        BEQ     i_toprb
        DECR    R1
        MVO     R1, SHOW
        B       i_show
i_toprb:
        MVII    #1, R1
        MVO     R1, PHASE
i_show: JSR     R5, show
        MVII    #sloop, R0      ; back into sloop for the rows
        MVO     R0, STACK
        PULR    R5
        JR      R5
; ---- a probe frame: constant time, display off
i_prb:  CLRR    R1
        MVO     R1, PHASE
        MVII    #1, R1
        MVO     R1, WASP
        MVI     KIDX, R4
        ADDI    #ptab, R4
        MVI@    R4, R0
        MVO     R0, STACK       ; return into probe k
        PULR    R5
        JR      R5

ptab:   DECLE   pk0, pk1, pk2, pk3, pk4, pk5

sloop:  B       sloop

; probe k: 24 + k cycles of padding, the delay, the train
pk0:    NOP
        NOP
        NOP
        NOP
        B       pcom
pk1:    NOPP
        NOP
        NOP
        NOP
        B       pcom
pk2:    NOPP
        NOPP
        NOP
        NOP
        B       pcom
pk3:    NOPP
        NOPP
        NOPP
        NOP
        B       pcom
pk4:    NOPP
        NOPP
        NOPP
        NOPP
        B       pcom
pk5:    NOPP
        NOPP
        NOPP
        MVII    #0, R1
        B       pcom
pcom:   MVII    #DELAYN, R1
pdl:    DECR    R1
        BNEQ    pdl
train:  INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
        INCR    R0
tspin:  B       tspin           ; past the train: idx = TRAIN or more

main:   JSR     R5, clrscr
        CLRR    R0
        MVII    #VARS, R4
        MVII    #32, R1
m_clr:  MVO@    R0, R4
        DECR    R1
        BNEQ    m_clr
        MVII    #$FFFF, R0
        MVII    #MINS, R4
        MVII    #6, R1
m_min:  MVO@    R0, R4
        DECR    R1
        BNEQ    m_min
        MVII    #8, R0          ; a few frames to settle before the first probe
        MVO     R0, SHOW
        JSR     R5, labels
        EIS
        B       sloop

show:   PSHR    R5
        MVII    #WHITE, R3
        CLRR    R2
sh_lp:  MOVR    R2, R1          ; row 3 + k: LAST MIN MAX in hex
        SLL     R1, 2
        ADDR    R2, R1          ; 5k
        SLL     R1, 2           ; 20k
        ADDI    #BACKTAB+3*20+4, R1
        MOVR    R1, R4
        MOVR    R2, R5
        ADDI    #LASTS, R5
        MVI@    R5, R0
        PSHR    R2
        JSR     R5, puthex
        PULR    R2
        INCR    R4
        MOVR    R2, R5
        ADDI    #MINS, R5
        MVI@    R5, R0
        PSHR    R2
        JSR     R5, puthex
        PULR    R2
        INCR    R4
        MOVR    R2, R5
        ADDI    #MAXS, R5
        MVI@    R5, R0
        PSHR    R2
        JSR     R5, puthex
        PULR    R2
        INCR    R2
        CMPI    #6, R2
        BLT     sh_lp
        MVI     RUNS, R0
        MVII    #BACKTAB+10*20+6, R4
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
        CLRR    R2
lb_lp:  MOVR    R2, R1
        SLL     R1, 2
        ADDR    R2, R1
        SLL     R1, 2
        ADDI    #BACKTAB+3*20, R1
        MOVR    R1, R4
        MOVR    R2, R0
        SLL     R0, 2
        SLL     R0, 1
        ADDI    #('0'-32)*8+YELLOW, R0
        MVII    #('K'-32)*8+YELLOW, R1
        MVO@    R1, R4
        MVO@    R0, R4
        INCR    R2
        CMPI    #6, R2
        BLT     lb_lp
        MVII    #t10, R1
        MVII    #BACKTAB+10*20, R4
        JSR     R5, puts
        MVII    #t11, R1
        MVII    #BACKTAB+11*20, R4
        JSR     R5, puts
        PULR    R7
t0:     STRING  "HW INTLATE   INTRM"
        DECLE   0
t2:     STRING  "K   LAST MIN  MAX"
        DECLE   0
t10:    STRING  "ROUND"
        DECLE   0
t11:    STRING  "IDX = INCR CUT (HEX)"
        DECLE   0
