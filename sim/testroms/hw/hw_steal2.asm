; hw_steal2: the shape of the STIC's bus requests in a frame (docs/HW_TESTS.md 7; docs/STIC_NOTES.md
; T1, T4; the bus request exit of docs/CPU_NOTES.md). hw_steal gives the cycles the requests take a
; frame; this program asks where they start and end, through counting loops of different
; lengths and boundary patterns. Rounds of 3 x 15 frames:
;   lock frame (display on): main waits in sloop, so the last row's request fixes the phase
;     and the next interrupt comes at a known cycle;
;   ON frame k (display on): the ISR (constant time) returns into probe k: a padding of 30-40
;     cycles, then counting loop k (INCR R0 and 0-2 more instructions, 15-37 cycles a pass;
;     some with an MVO, which a request cannot stop) until the next interrupt. Each request
;     stops the loop at its next interruptible boundary and lets it go at a fixed cycle, so
;     the passes depend on where each request starts against the loop: the request's length
;     before the CPU resumes (hold + exit), the frame request's start and end;
;   OFF frame k (display off: no requests): the same from the same cycle (the ON frame's last
;     row fixes the phase again): the frame length minus the interrupt path.
; The next ISR reads the interrupted main's R0 (the EXEC's dispatcher saves it at STACK+1),
; keeps it and clears it. The screen shows per probe the ON and OFF passes (hex); the display
; holds for SHOWF frames between rounds.
; SPDX-License-Identifier: MIT

K       EQU     15              ; probes (padding 30 .. 44 cycles)
SHOWF   EQU     150             ; frames shown between rounds

IDX     EQU     VARS+0          ; the frame being set up: 3k (lock), 3k+1 (ON k), 3k+2 (OFF k)
SHOWN   EQU     VARS+1          ; show frames left
RUNS    EQU     VARS+2          ; rounds done
TAB     EQU     VARS+16         ; loop passes per frame: TAB + 3k + 1 (ON k), + 3k + 2 (OFF k)

isr:    PSHR    R5
        JSR     R5, stic_set
        MVI     SHOWN, R1
        TSTR    R1
        BNEQ    i_show
        MVI     IDX, R1         ; constant time from here to the return (rounds' frames)
        MOVR    R1, R4          ; the frame that ended: its passes
        ADDI    #TAB-1, R4
        MVI     STACK+1, R0
        MVO@    R0, R4
        CLRR    R0
        MVO     R0, STACK+1     ; main's R0 restarts at 0
        CMPI    #3*K, R1
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
        MVII    #m_show, R0     ; main draws it (longer than a frame)
        MVO     R0, STACK
        PULR    R5
        JR      R5
i_show: MVO     R0, $0020
        DECR    R1
        MVO     R1, SHOWN
        BNEQ    i_s2
        MVO     R1, IDX         ; the next frame starts a round
i_s2:   PULR    R5
        JR      R5

m_show: JSR     R5, show
sloop:  B       sloop
cL15:   INCR    R0
        B       cL15
cL21:   INCR    R0
        NOP
        B       cL21
cL22:   INCR    R0
        NOPP
        B       cL22
cL23:   INCR    R0
        MVII    #0, R1
        B       cL23
cL25:   INCR    R0
        MVI     VARS+15, R1
        B       cL25
cL26:   INCR    R0
        MVO     R1, VARS+14
        B       cL26
cL27:   INCR    R0
        NOP
        NOP
        B       cL27
cL32:   INCR    R0
        MVO     R1, VARS+14
        NOP
        B       cL32
cL37:   INCR    R0
        MVO     R1, VARS+14
        MVO     R1, VARS+14
        B       cL37

; probe k: its padding, then its loop
pk0:    NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cL15
pk1:    NOPP
        NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cL15
pk2:    NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cL21
pk3:    NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cL22
pk4:    NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cL23
pk5:    NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cL25
pk6:    NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cL26
pk7:    NOPP
        NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cL26
pk8:    NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cL27
pk9:    NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cL32
pk10:   NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cL37
pk11:   MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        B       cL37
pk12:   MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        B       cL21
pk13:   MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        B       cL25
pk14:   MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        MVII    #0, R1
        B       cL27

rtab:   DECLE   sloop, pk0, pk0, sloop, pk1, pk1
        DECLE   sloop, pk2, pk2, sloop, pk3, pk3
        DECLE   sloop, pk4, pk4, sloop, pk5, pk5
        DECLE   sloop, pk6, pk6, sloop, pk7, pk7
        DECLE   sloop, pk8, pk8, sloop, pk9, pk9
        DECLE   sloop, pk10, pk10, sloop, pk11, pk11
        DECLE   sloop, pk12, pk12, sloop, pk13, pk13
        DECLE   sloop, pk14, pk14
dtab:   DECLE   $0020, $0020, $0021, $0020, $0020, $0021
        DECLE   $0020, $0020, $0021, $0020, $0020, $0021
        DECLE   $0020, $0020, $0021, $0020, $0020, $0021
        DECLE   $0020, $0020, $0021, $0020, $0020, $0021
        DECLE   $0020, $0020, $0021, $0020, $0020, $0021
        DECLE   $0020, $0020, $0021, $0020, $0020, $0021
        DECLE   $0020, $0020, $0021, $0020, $0020, $0021
        DECLE   $0020, $0020, $0021

main:   JSR     R5, clrscr
        CLRR    R0
        MVII    #VARS, R4
        MVII    #16+3*K, R1
m_clr:  MVO@    R0, R4
        DECR    R1
        BNEQ    m_clr
        JSR     R5, labels
        EIS
        B       sloop

; puthex3: R0 (< $1000) as 3 hex digits at R4, colour R3. Uses R1, R2, R5's stack.
puthex3:
        PSHR    R5
        SLL     R0, 2
        SLL     R0, 2
        MVII    #3, R2
p3_lp:  MOVR    R0, R1
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
        BNEQ    p3_lp
        PULR    R7

; show: per k the ON and OFF passes; k 0-7 left, 8-14 right
show:   PSHR    R5
        CLRR    R2
sh_lp:  PSHR    R2
        MOVR    R2, R1          ; screen place: row 1 + (k & 7), column 0 or 10
        ANDI    #7, R1
        INCR    R1
        MOVR    R1, R0
        SLL     R0, 2
        ADDR    R1, R0
        SLL     R0, 2           ; row x 20
        ADDI    #BACKTAB, R0
        MOVR    R0, R4
        MOVR    R2, R1
        ANDI    #8, R1
        BEQ     sh_l
        ADDI    #10, R4
sh_l:   MOVR    R2, R0          ; ON: TAB + 3k + 1
        SLL     R0, 1
        ADDR    R2, R0
        ADDI    #TAB+1, R0
        MOVR    R0, R5
        MVI@    R5, R0
        PSHR    R5              ; OFF: the next word
        INCR    R4
        INCR    R4
        MVII    #YELLOW, R3
        JSR     R5, puthex3
        INCR    R4
        PULR    R5
        MVI@    R5, R0
        MVII    #WHITE, R3
        JSR     R5, puthex3
        PULR    R2
        INCR    R2
        CMPI    #K, R2
        BLT     sh_lp
        MVII    #WHITE, R3
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
        CLRR    R2              ; the probe numbers 0-E
lb_lp:  MOVR    R2, R1
        ANDI    #7, R1
        INCR    R1
        MOVR    R1, R0
        SLL     R0, 2
        ADDR    R1, R0
        SLL     R0, 2
        ADDI    #BACKTAB, R0
        MOVR    R0, R4
        MOVR    R2, R1
        ANDI    #8, R1
        BEQ     lb_l
        ADDI    #10, R4
lb_l:   MOVR    R2, R1
        ADDI    #hexcard, R1
        MOVR    R1, R5
        MVI@    R5, R1
        ADDR    R3, R1
        MVO@    R1, R4
        INCR    R2
        CMPI    #K, R2
        BLT     lb_lp
        MVII    #t10, R1
        MVII    #BACKTAB+10*20, R4
        JSR     R5, puts
        MVII    #t11, R1
        MVII    #BACKTAB+11*20, R4
        JSR     R5, puts
        PULR    R7
t0:     STRING  "HW STEAL2  K ON OFF"
        DECLE   0
t10:    STRING  "ON YELLOW  OFF WHITE"
        DECLE   0
t11:    STRING  "15 PROBES  N"
        DECLE   0
