; hw_frame2: the frame length in CPU cycles from the VBlank interrupt alone, a timing check of the
; EXEC dispatcher's jump (SDBD + MVI@ R4, R7), and what reads of the STIC's border register
; return in and out of VBlank (docs/HW_TESTS.md 9; STIC_NOTES T11; CPU_NOTES row 1). hw_frame
; (section 6) polled the register window and saw no edge on the console; this one needs no
; register read for its timing. Like hw_intlate: a lock frame (display on, main in sloop: the
; rows fix the phase, so the next interrupt comes at a known cycle), then a probe frame (display
; off) whose ISR (constant time) returns into probe k (24 + k cycles of padding) and a fixed
; path, a delay loop and a train of 60 x INCR R0; the next interrupt cuts the train and the ISR
; keeps idx = interrupted PC - train. Over k = 0..5 the cut moves one cycle a probe, so the six
; indices give the cut's time against the train's start to the cycle: C = 6 x min + (the number
; of k one above the minimum).
;   V: the path is MVII + B; the train meets the next interrupt.
;   W: DIS, a delay past the next frame's VBlank (its interrupt is not taken: the request is
;      dropped when INTRM rises, CPU_NOTES), EIS, more delay: the train meets the interrupt one
;      frame later. C(W) - C(V) = the frame length minus a known path difference: FRAME CYC.
;      (The interrupt sequence is not in it: both cuts are the same kind of event.)
;   U: V's path with MVII + SDBD + MVI@ R4, R7 in front (the jump the EXEC's dispatcher uses to
;      reach our ISR): C(V) - C(U) - 8 = the cycles of SDBD + MVI@ R4, R7 (14 in the model).
; Then two diagnostic frames read $2C (border colour 1): in VBlank of a display-on frame, at
; cycle ~5,000 of it, in VBlank of a display-off frame, at ~5,000 of that one, and right after
; a $20 write there (hw_frame's late write). The model (MAME's rule): open in VBlank or while
; the handshake is clear, reading $3FF1; closed, the address offset $002C.
; SPDX-License-Identifier: MIT

VN      EQU     946             ; V and U: delay passes (15 cycles) before the train
WN1     EQU     1360            ; W: passes before EIS (past the next frame's VBlank)
WN2     EQU     580             ; W: passes after EIS
KP      EQU     14933           ; FRAME CYC = C(W) - C(V) + KP
KU      EQU     8              ; SDBD JUMP = C(V) - C(U) - KU
DGN     EQU     330             ; diagnostic delay passes (about cycle 5,000)
NF      EQU     39              ; frames set up in a round
SHOWF   EQU     150             ; frames shown between rounds

IDX     EQU     VARS+0          ; the frame being set up
SHOWN   EQU     VARS+1          ; show frames left
RUNS    EQU     VARS+2          ; rounds done
VBR     EQU     VARS+3          ; $2C as the last ISR read it (VBlank)
DG      EQU     VARS+4          ; 5 diagnostic reads: VB on, mid on, VB off, mid off, after $20
SCRA    EQU     VARS+10         ; show: screen address
TAB     EQU     VARS+16         ; idx of frame i at TAB + i

isr:    PSHR    R5
        JSR     R5, stic_set
        MVI     $002C, R3       ; the border register in VBlank
        MVO     R3, VBR
        MVI     SHOWN, R1
        TSTR    R1
        BNEQ    i_show
        MVI     IDX, R1         ; constant time from here to the return (rounds' frames)
        MOVR    R1, R4          ; the frame that ended: its train index
        ADDI    #TAB-1, R4
        MVI     STACK, R0
        SUBI    #train, R0
        MVO@    R0, R4
        CMPI    #NF, R1
        BGE     i_end
        MOVR    R1, R4          ; this frame: display on ($20) or off ($21)
        ADDI    #dtab, R4
        MVI@    R4, R2
        MVO@    R0, R2
        MOVR    R1, R4          ; and where main goes
        ADDI    #rtab, R4
        MVI@    R4, R0
        MVO     R0, STACK
        INCR    R1
        MVO     R1, IDX
        PULR    R5
        JR      R5
i_end:  MVO     R0, $0020       ; the round is over: show it
        MVII    #SHOWF, R1
        MVO     R1, SHOWN
        MVI     RUNS, R1
        INCR    R1
        MVO     R1, RUNS
        MVII    #m_show, R0     ; main draws it
        MVO     R0, STACK
        PULR    R5
        JR      R5
i_show: MVII    #1, R0
        MVO     R0, $0020
        DECR    R1
        MVO     R1, SHOWN
        BNEQ    i_s2
        MVO     R1, IDX         ; the next frame starts a round
i_s2:   PULR    R5
        JR      R5

m_show: JSR     R5, show
sloop:  B       sloop

; the diagnostic frames: D1 display on, D2 display off
diag1:  MVI     VBR, R0
        MVO     R0, DG+0
        MVII    #DGN, R1
dg1:    DECR    R1
        BNEQ    dg1
        MVI     $002C, R0
        MVO     R0, DG+1
        B       sloop
diag2:  MVI     VBR, R0
        MVO     R0, DG+2
        MVII    #DGN, R1
dg2:    DECR    R1
        BNEQ    dg2
        MVI     $002C, R0
        MVO     R0, DG+3
        MVO     R0, $0020       ; late: the display stays off
        MVI     $002C, R0
        MVO     R0, DG+4
        B       sloop

; probes: 24 + k cycles of padding, then the path
pv0:    MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        MVII    #VN, R1
        B       dloop
pv1:    NOP
        NOP
        NOP
        NOPP
        MVII    #VN, R1
        B       dloop
pv2:    NOP
        NOP
        NOPP
        NOPP
        MVII    #VN, R1
        B       dloop
pv3:    NOP
        NOPP
        NOPP
        NOPP
        MVII    #VN, R1
        B       dloop
pv4:    NOPP
        NOPP
        NOPP
        NOPP
        MVII    #VN, R1
        B       dloop
pv5:    NOPP
        NOPP
        NOPP
        MVII    #0, R1
        MVII    #VN, R1
        B       dloop
pw0:    MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        DIS
        MVII    #WN1, R1
        B       wdl
pw1:    NOP
        NOP
        NOP
        NOPP
        DIS
        MVII    #WN1, R1
        B       wdl
pw2:    NOP
        NOP
        NOPP
        NOPP
        DIS
        MVII    #WN1, R1
        B       wdl
pw3:    NOP
        NOPP
        NOPP
        NOPP
        DIS
        MVII    #WN1, R1
        B       wdl
pw4:    NOPP
        NOPP
        NOPP
        NOPP
        DIS
        MVII    #WN1, R1
        B       wdl
pw5:    NOPP
        NOPP
        NOPP
        MVII    #0, R1
        DIS
        MVII    #WN1, R1
        B       wdl
pu0:    MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        MVII    #uvec, R4
        SDBD
        MVI@    R4, R7
pu1:    NOP
        NOP
        NOP
        NOPP
        MVII    #uvec, R4
        SDBD
        MVI@    R4, R7
pu2:    NOP
        NOP
        NOPP
        NOPP
        MVII    #uvec, R4
        SDBD
        MVI@    R4, R7
pu3:    NOP
        NOPP
        NOPP
        NOPP
        MVII    #uvec, R4
        SDBD
        MVI@    R4, R7
pu4:    NOPP
        NOPP
        NOPP
        NOPP
        MVII    #uvec, R4
        SDBD
        MVI@    R4, R7
pu5:    NOPP
        NOPP
        NOPP
        MVII    #0, R1
        MVII    #uvec, R4
        SDBD
        MVI@    R4, R7
ucont:  MVII    #VN, R1
        B       dloop
wdl:    DECR    R1              ; W: the skipped frame's VBlank passes with interrupts off
        BNEQ    wdl
        EIS
        MVII    #WN2, R1
        B       dloop
dloop:  DECR    R1
        BNEQ    dloop
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
tspin:  B       tspin           ; past the train: idx = 60 or more
uvec:   BIDECLE ucont

rtab:   DECLE   sloop, diag1, diag2, sloop, pv0, sloop
        DECLE   pv1, sloop, pv2, sloop, pv3, sloop
        DECLE   pv4, sloop, pv5, sloop, pw0, sloop
        DECLE   pw1, sloop, pw2, sloop, pw3, sloop
        DECLE   pw4, sloop, pw5, sloop, pu0, sloop
        DECLE   pu1, sloop, pu2, sloop, pu3, sloop
        DECLE   pu4, sloop, pu5
dtab:   DECLE   $0020, $0020, $0021, $0020, $0021, $0020
        DECLE   $0021, $0020, $0021, $0020, $0021, $0020
        DECLE   $0021, $0020, $0021, $0020, $0021, $0020
        DECLE   $0021, $0020, $0021, $0020, $0021, $0020
        DECLE   $0021, $0020, $0021, $0020, $0021, $0020
        DECLE   $0021, $0020, $0021, $0020, $0021, $0020
        DECLE   $0021, $0020, $0021

main:   JSR     R5, clrscr
        CLRR    R0
        MVII    #VARS, R4
        MVII    #16+NF, R1
m_clr:  MVO@    R0, R4
        DECR    R1
        BNEQ    m_clr
        JSR     R5, labels
        EIS
        B       sloop

; putnh: R0's low R2 hex digits at R4 (R4 advances), colour R3. Uses R1, R2; R0 is lost.
putnh:  PSHR    R5
        MOVR    R2, R1          ; shift the wanted digits to the top
        SUBI    #4, R1
        NEGR    R1
        BEQ     pn_go
pn_sh:  SLL     R0, 2
        SLL     R0, 2
        DECR    R1
        BNEQ    pn_sh
pn_go:  MOVR    R0, R1
        SWAP    R1
        SLR     R1, 2
        SLR     R1, 2
        ANDI    #$F, R1
        ADDI    #hexcard, R1
        MOVR    R1, R5
        MVI@    R5, R1
        ADDR    R3, R1
        MVO@    R1, R4
        SLL     R0, 2
        SLL     R0, 2
        DECR    R2
        BNEQ    pn_go
        PULR    R7

; cvalue: R4 = the first of six indices; R0 = 6 x min + (the count one above it). Uses R1-R2.
cvalue: PSHR    R5
        MOVR    R4, R5
        ADDI    #10, R5         ; probe 5: the last of the six (TAB stride 2: lock frames between)
        MVI@    R5, R1          ; m = idx(5)
        CLRR    R0
        MVII    #6, R2
cv_lp:  MVI@    R4, R5          ; idx(k) (R4 steps by 2: lock frames between)
        INCR    R4
        CMPR    R1, R5
        BEQ     cv_n
        INCR    R0
cv_n:   DECR    R2
        BNEQ    cv_lp
        MOVR    R1, R2          ; + 6 x m
        SLL     R2, 1
        ADDR    R1, R2
        SLL     R2, 1
        ADDR    R2, R0
        PULR    R7

show:   PSHR    R5
        MVII    #WHITE, R3
        MVII    #BACKTAB+1*20+2, R0
        MVO     R0, SCRA
        MVII    #TAB+4, R4      ; V: frames 4, 6, .. 14
        JSR     R5, row6x
        MVII    #BACKTAB+2*20+2, R0
        MVO     R0, SCRA
        MVII    #TAB+16, R4     ; W: frames 16 .. 26
        JSR     R5, row6x
        MVII    #BACKTAB+3*20+2, R0
        MVO     R0, SCRA
        MVII    #TAB+28, R4     ; U: frames 28 .. 38
        JSR     R5, row6x
        MVII    #TAB+16, R4     ; FRAME CYC = C(W) - C(V) + KP
        JSR     R5, cvalue
        PSHR    R0
        MVII    #TAB+4, R4
        JSR     R5, cvalue
        PULR    R1
        SUBR    R0, R1
        ADDI    #KP, R1
        MOVR    R1, R0
        MVII    #YELLOW, R3
        MVII    #BACKTAB+5*20+14, R4
        JSR     R5, putdec
        MVII    #TAB+4, R4      ; SDBD JUMP = C(V) - C(U) - KU
        JSR     R5, cvalue
        PSHR    R0
        MVII    #TAB+28, R4
        JSR     R5, cvalue
        PULR    R1
        SUBR    R0, R1
        SUBI    #KU, R1
        MOVR    R1, R0
        MVII    #BACKTAB+6*20+14, R4
        JSR     R5, putdec
        MVII    #WHITE, R3
        MVI     DG+0, R0
        MVII    #BACKTAB+8*20+6, R4
        MVII    #4, R2
        JSR     R5, putnh
        MVI     DG+1, R0
        MVII    #BACKTAB+8*20+15, R4
        MVII    #4, R2
        JSR     R5, putnh
        MVI     DG+2, R0
        MVII    #BACKTAB+9*20+6, R4
        MVII    #4, R2
        JSR     R5, putnh
        MVI     DG+3, R0
        MVII    #BACKTAB+9*20+15, R4
        MVII    #4, R2
        JSR     R5, putnh
        MVI     DG+4, R0
        MVII    #BACKTAB+10*20+15, R4
        MVII    #4, R2
        JSR     R5, putnh
        MVI     RUNS, R0
        MVII    #BACKTAB+11*20+15, R4
        JSR     R5, putdec
        PULR    R7

; row6x: R4 = TAB address of probe 0 (stride 2), the screen address in SCRA; six 2-digit indices
row6x:  PSHR    R5
        MVII    #6, R2
rx_lp:  MVI@    R4, R0          ; idx (R4 + 1)
        INCR    R4              ; stride 2: lock frames between
        PSHR    R4
        PSHR    R2
        MVI     SCRA, R4
        MVII    #2, R2
        JSR     R5, putnh
        INCR    R4
        MVO     R4, SCRA
        PULR    R2
        PULR    R4
        DECR    R2
        BNEQ    rx_lp
        PULR    R7

labels: PSHR    R5
        MVII    #TAN, R3
        MVII    #t0, R1
        MVII    #BACKTAB+0*20, R4
        JSR     R5, puts
        MVII    #WHITE, R3
        MVII    #t1, R1
        MVII    #BACKTAB+1*20, R4
        JSR     R5, puts
        MVII    #t2, R1
        MVII    #BACKTAB+2*20, R4
        JSR     R5, puts
        MVII    #t3, R1
        MVII    #BACKTAB+3*20, R4
        JSR     R5, puts
        MVII    #t5, R1
        MVII    #BACKTAB+5*20, R4
        JSR     R5, puts
        MVII    #t6, R1
        MVII    #BACKTAB+6*20, R4
        JSR     R5, puts
        MVII    #t7, R1
        MVII    #BACKTAB+7*20, R4
        JSR     R5, puts
        MVII    #t8, R1
        MVII    #BACKTAB+8*20, R4
        JSR     R5, puts
        MVII    #t9, R1
        MVII    #BACKTAB+9*20, R4
        JSR     R5, puts
        MVII    #t10, R1
        MVII    #BACKTAB+10*20, R4
        JSR     R5, puts
        MVII    #t11, R1
        MVII    #BACKTAB+11*20, R4
        JSR     R5, puts
        PULR    R7
t0:     STRING  "HW FRAME2 FRAME+REG"
        DECLE   0
t1:     STRING  "V"
        DECLE   0
t2:     STRING  "W"
        DECLE   0
t3:     STRING  "U"
        DECLE   0
t5:     STRING  "FRAME CYC"
        DECLE   0
t6:     STRING  "SDBD JUMP"
        DECLE   0
t7:     STRING  "$2C   VBLANK   MID"
        DECLE   0
t8:     STRING  "ON"
        DECLE   0
t9:     STRING  "OFF"
        DECLE   0
t10:    STRING  "AFTER LATE $20"
        DECLE   0
t11:    STRING  "N"
        DECLE   0
