; hw_grantx: what happens in hw_grant's probes 5 and 9, which read 000 on the console
; (docs/HW_TESTS.md 11). hw_grant's frames (lock, ON, OFF) with six of its loops: 4 (MVO MVII) x2,
; 5 (MVO SDBD MVII) x2, 8 (MVO MVO) x2 B, 9 (MVO MVO) x2 NOP B, A (MVO MVO) x3 NOP NOP, and the
; control INCR NOP NOP B. The ISR keeps, per frame, the interrupted main's R0 (the loop passes)
; and the interrupted PC (where the VBlank interrupt cut the loop), and at the end of a round
; the screen shows both for the ON and OFF frame of each probe, with each loop's address.
; SPDX-License-Identifier: MIT

K       EQU     6              ; probes (padding 30 .. 44 cycles)
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
        ADDI    #3*K-1, R4      ; and the interrupted PC (MVO@ R4 stepped R4)
        MVI     STACK, R0
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
cl0:    INCR    R0
        MVO     R1, VARS+14
        MVII    #0, R1
        MVO     R1, VARS+14
        MVII    #0, R1
        B       cl0
cl1:    INCR    R0
        MVO     R1, VARS+14
        SDBD
        MVII    #$1234, R1
        MVO     R1, VARS+14
        SDBD
        MVII    #$1234, R1
        B       cl1
cl2:    INCR    R0
        MVO     R1, VARS+14
        MVO     R1, VARS+14
        MVO     R1, VARS+14
        MVO     R1, VARS+14
        B       cl2
cl3:    INCR    R0
        MVO     R1, VARS+14
        MVO     R1, VARS+14
        MVO     R1, VARS+14
        MVO     R1, VARS+14
        NOP
        B       cl3
cl4:    INCR    R0
        MVO     R1, VARS+14
        MVO     R1, VARS+14
        MVO     R1, VARS+14
        MVO     R1, VARS+14
        MVO     R1, VARS+14
        MVO     R1, VARS+14
        NOP
        NOP
        B       cl4
cl5:    INCR    R0
        NOP
        NOP
        B       cl5

; probe k: its padding, then its loop
pk0:    NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cl0
pk1:    NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cl1
pk2:    NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cl2
pk3:    NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cl3
pk4:    NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cl4
pk5:    NOPP
        NOPP
        MVII    #0, R1
        MVII    #0, R1
        B       cl5

rtab:   DECLE   sloop, pk0, pk0, sloop, pk1, pk1
        DECLE   sloop, pk2, pk2, sloop, pk3, pk3
        DECLE   sloop, pk4, pk4, sloop, pk5, pk5
dtab:   DECLE   $0020, $0020, $0021, $0020, $0020, $0021
        DECLE   $0020, $0020, $0021, $0020, $0020, $0021
        DECLE   $0020, $0020, $0021, $0020, $0020, $0021

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
        MOVR    R2, R1          ; screen row 1 + k
        INCR    R1
        MOVR    R1, R0
        SLL     R0, 2
        ADDR    R1, R0
        SLL     R0, 2
        ADDI    #BACKTAB+2, R0
        MOVR    R0, R4
        MOVR    R2, R0          ; ON: TAB + 3k + 1
        SLL     R0, 1
        ADDR    R2, R0
        ADDI    #TAB+1, R0
        MOVR    R0, R5
        PSHR    R5
        MVI@    R5, R0
        MVII    #YELLOW, R3
        JSR     R5, puthex3
        INCR    R4
        PULR    R5
        PSHR    R5
        ADDI    #3*K, R5        ; its PC
        MVI@    R5, R0
        JSR     R5, puthex
        INCR    R4
        PULR    R5
        INCR    R5              ; OFF
        PSHR    R5
        MVI@    R5, R0
        MVII    #WHITE, R3
        JSR     R5, puthex3
        INCR    R4
        PULR    R5
        ADDI    #3*K, R5
        MVI@    R5, R0
        JSR     R5, puthex
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
        CLRR    R2              ; probe numbers
lb_lp:  MOVR    R2, R1
        INCR    R1
        MOVR    R1, R0
        SLL     R0, 2
        ADDR    R1, R0
        SLL     R0, 2
        ADDI    #BACKTAB, R0
        MOVR    R0, R4
        MOVR    R2, R1
        ADDI    #pnum, R1
        MOVR    R1, R5
        MVI@    R5, R1
        ADDI    #hexcard, R1
        MOVR    R1, R5
        MVI@    R5, R1
        ADDR    R3, R1
        MVO@    R1, R4
        INCR    R2
        CMPI    #K, R2
        BLT     lb_lp
        MVII    #t8, R1
        MVII    #BACKTAB+8*20, R4
        JSR     R5, puts
        MVII    #cl0, R0        ; the loops' addresses
        MVII    #BACKTAB+9*20, R4
        JSR     R5, puthex
        INCR    R4
        MVII    #cl1, R0
        JSR     R5, puthex
        INCR    R4
        MVII    #cl2, R0
        JSR     R5, puthex
        MVII    #cl3, R0
        MVII    #BACKTAB+10*20, R4
        JSR     R5, puthex
        INCR    R4
        MVII    #cl4, R0
        JSR     R5, puthex
        INCR    R4
        MVII    #cl5, R0
        JSR     R5, puthex
        MVII    #t11, R1
        MVII    #BACKTAB+11*20, R4
        JSR     R5, puts
        PULR    R7
pnum:   DECLE   4, 5, 8, 9, 10, 0
t0:     STRING  "HW GRANTX ON PC OFF"
        DECLE   0
t8:     STRING  "LOOPS 4 5 8 / 9 A 0"
        DECLE   0
t11:    STRING  "6 PROBES    N"
        DECLE   0
