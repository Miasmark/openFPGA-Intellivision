; hw_frame: the frame length in CPU cycles, and the cost of taking the VBlank interrupt
; (docs/HW_TESTS.md 6; docs/STIC_NOTES.md T11; docs/CPU_NOTES.md row 1). hw_steal's display-off
; count gives the frame length minus the interrupt path; this program measures the two apart.
; With the display off (no bus requests) and interrupts off, the main code finds each frame
; start by polling the STIC's register window: a $20 write late in a frame (after the VBlank
; window, so the display stays off) sets the handshake, which closes the registers to the CPU
; until the next frame starts (VBlank opens them again). A border register read ($2C, border
; colour 1) gives colour 1 in its low bits while open and something else while closed (the
; address offset in the model). Each frame: the edge, a payload, a fixed delay to about cycle
; 13,900, the $20 write, then 56-cycle poll passes until the next edge, counted. Over NFR =
; 224 frames the passes S give the frame length P = KFR + S / 4 (the count is off by less than
; one pass, so P rounds to the cycle). Three phases:
;   F: payload of 21 cycles, no interrupt;
;   I: the same payload with EIS ... DIS around an interruptible NOP: the VBlank interrupt,
;      pending since the frame start, is taken there (EXEC dispatcher, our ISR = JR R5);
;   X: the same payload, then an inline copy of the interrupt path's instruction sequence
;      (the EXEC dispatcher's instruction classes in its order, as the model traces it) entered
;      with MVII + PSHR + B in place of the interrupt.
; I - F = the interrupt path (interrupt + dispatcher + JR R5); X - F = the copy; their
; difference + 26 = the interrupt sequence itself (9 cycles: S1 p.35). Then the numbers show
; for SHOWF frames (display on). "NO EDGE": the window never closed after a late $20 write.
; SPDX-License-Identifier: MIT

NFR     EQU     224             ; frames measured per phase
DLY     EQU     910             ; delay passes of 15 cycles after the edge (the polls start late)
LIM     EQU     2000            ; poll passes without an edge: give up (NO EDGE)
SHOWF   EQU     300             ; frames the result is shown
KFR     EQU     13771           ; P = KFR + S / 4 (the cycles of a frame outside the counted passes)
KINT    EQU     26              ; MVII + PSHR + B: the copy's entry, in place of the interrupt

SF      EQU     VARS+0          ; poll passes, phase F
SI      EQU     VARS+1          ; phase I
SX      EQU     VARS+2          ; phase X
MASK    EQU     VARS+3          ; 0 at a phase's first edge (its passes not counted)
PAYLD   EQU     VARS+4          ; the phase's payload routine
SHOWN   EQU     VARS+5          ; show frames left (the ISR counts down)
RUNS    EQU     VARS+6
FAIL    EQU     VARS+7          ; 1: no edge

; the display ISR (show phase only): text set-up, display on, count down
isr:    PSHR    R5
        JSR     R5, stic_set
        MVO     R0, $0020
        MVI     SHOWN, R1
        DECR    R1
        MVO     R1, SHOWN
        PULR    R5
        JR      R5

; the ISR during phase I: nothing but the return (the dispatcher's own path is the measurement)
istub:  JR      R5

main:   JSR     R5, clrscr
        CLRR    R0
        MVII    #VARS, R4
        MVII    #16, R1
m_clr:  MVO@    R0, R4
        DECR    R1
        BNEQ    m_clr
        JSR     R5, labels
        MVII    #2, R0          ; two display frames first: our STIC set-up (border 1)
        JSR     R5, m_show
m_loop: DIS
        CLRR    R0
        MVO     R0, FAIL
        MVII    #p_none, R0     ; phase F
        MVO     R0, PAYLD
        JSR     R5, measure
        MVO     R3, SF
        MVII    #istub, R0      ; phase I
        MVO     R0, $0100
        SWAP    R0
        MVO     R0, $0101
        MVII    #p_int, R0
        MVO     R0, PAYLD
        JSR     R5, measure
        MVO     R3, SI
        MVII    #p_fake, R0     ; phase X
        MVO     R0, PAYLD
        JSR     R5, measure
        MVO     R3, SX
        MVI     RUNS, R0
        INCR    R0
        MVO     R0, RUNS
        JSR     R5, show
        MVII    #SHOWF, R0
        JSR     R5, m_show
        B       m_loop

; m_show: display on for R0 frames (our ISR), then interrupts off again
m_show: MVO     R0, SHOWN
        MVII    #isr, R0
        MVO     R0, $0100
        SWAP    R0
        MVO     R0, $0101
        EIS
m_wait: MVI     SHOWN, R0
        TSTR    R0
        BNEQ    m_wait
        DIS
        JR      R5

; measure: one phase of NFR frames, interrupts off; R3 = the counted poll passes
measure:
        PSHR    R5
        CLRR    R3
        CLRR    R0
        MVO     R0, MASK
        MVII    #NFR+1, R2
        MVO     R0, $0020       ; the handshake (a display-on frame at worst: no matter here)
        CLRR    R1
ms_cl:  INCR    R1              ; wait until the window is closed
        MVI     $002C, R0
        ANDI    #$F, R0
        CMPI    #1, R0
        BNEQ    ms_go
        CMPI    #LIM, R1
        BNC     ms_cl
        B       ftime
ms_go:  CLRR    R1
fpoll:  INCR    R1              ; 56 cycles a pass while closed
        MVI     $002C, R0
        ANDI    #$F, R0
        CMPI    #1, R0
        BEQ     fopen
        CMPI    #LIM, R1
        BNC     fpoll
        B       ftime
fopen:  MVI     MASK, R0        ; a frame start: add this frame's passes (not the first's)
        ANDR    R0, R1
        ADDR    R1, R3
        CLRR    R1
        MVII    #$FFFF, R0
        MVO     R0, MASK
        DECR    R2
        BEQ     fdone
        JSR     R5, pcall
        MVII    #DLY, R4
fdly:   DECR    R4
        BNEQ    fdly
        MVO     R0, $0020       ; late: the display stays off, the registers close
        B       fpoll
fdone:  PULR    R7
ftime:  MVII    #1, R0
        MVO     R0, FAIL
        PULR    R7

pcall:  MVI     PAYLD, R0
        MOVR    R0, R7
; payloads (21 cycles, then the copy for X)
p_none: CLRC
        NOP
        CLRC
        JR      R5
p_int:  EIS
        NOP                     ; the pending VBlank interrupt is taken after this
        DIS
        JR      R5
p_fake: CLRC
        NOP
        CLRC
        MVII    #pf_ret, R0     ; in place of the interrupt: push the return point, go
        PSHR    R0
        B       fk
pf_ret: JR      R5
; the interrupt path's instruction sequence (registers saved and restored as there)
fk:     PSHR    R0
        GSWD    R0
        PSHR    R0
        PSHR    R1
        PSHR    R2
        NOP
        PSHR    R3
        PSHR    R4
        PSHR    R5
        MOVR    R7, R5
fk_a:   ADDI    #fk_r-fk_a, R5
        MVII    #fk_v, R4
        SDBD
        MVI@    R4, R7
fk_r:   PULR    R5
        PULR    R4
        PULR    R3
        PULR    R2
        PULR    R1
        PULR    R0
        RSWD    R0
        PULR    R0
        PULR    R7
fk_v:   BIDECLE istub

; show: the results (drawn while the display is off; shown in the next show phase)
show:   PSHR    R5
        MVII    #WHITE, R3
        MVI     FAIL, R0
        TSTR    R0
        BEQ     sh_ok
        MVII    #t_fail, R1
        MVII    #BACKTAB+2*20, R4
        JSR     R5, puts
        PULR    R7
sh_ok:  MVI     SF, R0          ; FRAME = KFR + SF / 4, rounded
        ADDI    #2, R0
        SLR     R0, 2
        ADDI    #KFR, R0
        MVII    #BACKTAB+2*20+12, R4
        JSR     R5, putdec
        MVI     SF, R0          ; IRQ PATH = (SF - SI) / 4, rounded
        MVI     SI, R1
        SUBR    R1, R0
        ADDI    #2, R0
        SLR     R0, 2
        MVII    #BACKTAB+5*20+12, R4
        JSR     R5, putdec
        MVI     SF, R0          ; COPY = (SF - SX) / 4, rounded
        MVI     SX, R1
        SUBR    R1, R0
        ADDI    #2, R0
        SLR     R0, 2
        MVII    #BACKTAB+6*20+12, R4
        JSR     R5, putdec
        MVI     SF, R0          ; INT = IRQ PATH - COPY PATH + KINT
        MVI     SI, R1
        SUBR    R1, R0
        ADDI    #2, R0
        SLR     R0, 2
        MVI     SF, R1
        MVI     SX, R2
        SUBR    R2, R1
        ADDI    #2, R1
        SLR     R1, 2
        SUBR    R1, R0
        ADDI    #KINT, R0
        MVII    #YELLOW, R3
        MVII    #BACKTAB+8*20+12, R4
        JSR     R5, putdec
        MVII    #WHITE, R3
        MVI     SF, R0
        MVII    #BACKTAB+10*20+0, R4
        JSR     R5, puthex
        MVI     SI, R0
        MVII    #BACKTAB+10*20+5, R4
        JSR     R5, puthex
        MVI     SX, R0
        MVII    #BACKTAB+10*20+10, R4
        JSR     R5, puthex
        MVI     RUNS, R0
        MVII    #BACKTAB+11*20+15, R4
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
        MVII    #t5, R1
        MVII    #BACKTAB+5*20, R4
        JSR     R5, puts
        MVII    #t6, R1
        MVII    #BACKTAB+6*20, R4
        JSR     R5, puts
        MVII    #t8, R1
        MVII    #BACKTAB+8*20, R4
        JSR     R5, puts
        MVII    #t9, R1
        MVII    #BACKTAB+9*20, R4
        JSR     R5, puts
        MVII    #t11, R1
        MVII    #BACKTAB+11*20, R4
        JSR     R5, puts
        PULR    R7
t0:     STRING  "HW FRAME  FRAME+IRQ"
        DECLE   0
t2:     STRING  "FRAME CYC"
        DECLE   0
t5:     STRING  "IRQ PATH"
        DECLE   0
t6:     STRING  "COPY PATH"
        DECLE   0
t8:     STRING  "IRQ ENTRY"
        DECLE   0
t9:     STRING  "SF   SI   SX"
        DECLE   0
t11:    STRING  "224 FRAMES  N"
        DECLE   0
t_fail: STRING  "NO EDGE (WINDOW)"
        DECLE   0
