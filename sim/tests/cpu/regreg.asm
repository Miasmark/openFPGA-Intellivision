; Register to register: MOVR TSTR JR ADDR SUBR CMPR ANDR XORR CLRR.
; S1 p.45 (status bits), p.50 fig 3.3.1, p.53; wiki MOVR, ADDR, SUBR, CMPR,
; Carry_Flag, Overflow_Flag.
;! expect a1: R0=$8000 SZOC=1010
;! expect a2: R2=0 SZOC=0101
;! expect a3: R4=0 SZOC=0111
;! expect a4: R0=2 SZOC=0001
;! expect a5: R0=$FFFE SZOC=1000
;! expect a6: R0=$7FFF SZOC=0011
;! expect a7: R0=0 SZOC=0111
;! expect a7b: R0=0 SZOC=0101
;! expect a8: R2=$8000 SZOC=1010
;! expect a9: R4=10 SZOC=1000
;! expect a10: SZOC=0001 R4=10 R5=20
;! expect a11: SZOC=0101
;! expect a12: R0=$000F SZOC=0001
;! expect a13: R0=$00F0 SZOC=0001
;! expect a14: SZOC=1001
;! expect a16: R6=$8000 SZOC=1001
;! expect a17: R3=$8000
;! expect a20: R1=a20 SZOC=0001
;! cycles a15 a16 = 7
;! cycles a16 a17 = 6
;! cycles a17 a19 = 15
        ORG     $5000
start:  MVII    #$7FFF, R0
        MVII    #1, R1
        ADDR    R1, R0          ; $7FFF + 1 = $8000: S, O
a1:     MVII    #$FFFF, R2
        ADDR    R1, R2          ; $FFFF + 1 = 0: Z, C
a2:     MVII    #$8000, R3
        MOVR    R3, R4          ; S (C kept)
        ADDR    R3, R4          ; $8000 + $8000 = 0: Z, O, C
a3:     MVII    #5, R0
        MVII    #3, R1
        SUBR    R1, R0          ; 5 - 3 = 2: C (no borrow)
a4:     MVII    #3, R0
        MVII    #5, R1
        SUBR    R1, R0          ; 3 - 5 = $FFFE: S, borrow (C=0)
a5:     MVII    #$8000, R0
        MVII    #1, R1
        SUBR    R1, R0          ; -32768 - 1 = $7FFF: O, C
a6:     CLRR    R0              ; Z; O C kept
a7:     SUBR    R0, R0          ; 0 - 0 = 0: Z, C
a7b:    MVII    #$7FFF, R2
        MVII    #$FFFF, R3
        SUBR    R3, R2          ; 32767 - (-1) = $8000: S, O, borrow
a8:     MVII    #10, R4
        MVII    #20, R5
        CMPR    R5, R4          ; 10 - 20: S, borrow; R4 kept
a9:     CMPR    R4, R5          ; 20 - 10: C
a10:    CMPR    R4, R4          ; Z, C
a11:    MVII    #$0F0F, R0
        MVII    #$00FF, R1
        ANDR    R1, R0          ; $000F; O C kept (0, 1)
a12:    XORR    R1, R0          ; $00F0
a13:    MVII    #$8000, R2
        TSTR    R2              ; S
a14:    NOP
a15:    MOVR    R2, R6          ; 7 cycles: destination R6
a16:    MOVR    R6, R3          ; 6 cycles
a17:    MVII    #a19, R0
        JR      R0              ; 7 cycles
a18:    DECLE   0               ; HLT, skipped
a19:    MOVR    R7, R1          ; R1 = address of the next instruction (S1 p.48)
a20:    NOP
done:   NOP
