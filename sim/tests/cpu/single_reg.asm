; Single-register instructions: INCR DECR COMR NEGR ADCR GSWD NOP SIN RSWD.
; S1 p.51 fig 3.3.3, p.53, p.56; wiki INCR, NEGR, ADCR, GSWD, RSWD, NOP, SIN.
; Flags start at 0 after reset (the model's choice; S1 p.21 says undefined).
;! expect t1: R0=0 SZOC=0100
;! expect t2: R0=$FFFF SZOC=1000
;! expect t3: R0=0 SZOC=0100
;! expect t4: R1=$8000 SZOC=1010
;! expect t4b: R2=0 SZOC=0110
;! expect t5: R2=0 SZOC=0101
;! expect t6: R3=$FFFB SZOC=1000
;! expect t7: R4=0 SZOC=0101
;! expect t8: R5=$8000 SZOC=1010
;! expect t9: R5=$8000 SZOC=1000
;! expect t10: R0=$8080 SZOC=1000
;! expect t11: SZOC=0101
;! expect t12: R2=$5050
;! expect t13: SZOC=0000 SIN=0
;! expect t14: SIN=2 SZOC=0000
;! expect t15: R0=$8080
;! expect done: R6=$FFFF R7=done SZOC=1000
;! cycles t1 t2 = 6
;! cycles t13 t14 = 24
;! cycles t14 t15 = 6
        ORG     $5000
start:  MVII    #$FFFF, R0
        INCR    R0              ; $FFFF + 1 = 0: Z; C and O untouched
t1:     DECR    R0              ; $FFFF: S
t2:     COMR    R0              ; 0: Z
t3:     MVII    #$8000, R1
        NEGR    R1              ; -$8000 = $8000: S, O
t4:     CLRR    R2              ; Z, S cleared; O C kept
t4b:    NEGR    R2              ; -0 = 0: Z and C (wiki NEGR: "Negating 0 sets the Carry")
t5:     MVII    #5, R3
        NEGR    R3              ; $FFFB: S only
t6:     SETC
        MVII    #$FFFF, R4
        ADCR    R4              ; $FFFF + 1: 0, C, Z
t7:     MVII    #$7FFF, R5
        SETC
        ADCR    R5              ; $7FFF + 1: $8000, S, O
t8:     CLRC
        ADCR    R5              ; + 0: S only
t9:     GSWD    R0              ; SZOC0000SZOC0000 = $8080
t10:    MVII    #$0050, R1      ; bits 7-4 = 0101
        RSWD    R1
t11:    GSWD    R2              ; $5050
t12:    MVII    #$FF0F, R3      ; bits 7-4 = 0000; other bits ignored
        RSWD    R3
t13:    NOP
        NOP     1
        SIN
        SIN     1
t14:    INCR    R7              ; skips the next word
        DECLE   0               ; HLT, never run
t15:    MVII    #0, R6
        DECR    R6              ; $FFFF: S
done:   NOP
