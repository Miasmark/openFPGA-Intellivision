; Internal control instructions, 4 cycles each, not interruptible.
; S1 p.51 fig 3.14, p.56; wiki EIS, DIS, TCI, CLRC, SETC, SDBD.
;! cycles b0 a1 = 4
;! cycles a1 a2 = 4
;! cycles a2 a3 = 4
;! cycles a3 a4 = 4
;! cycles a4 a5 = 4
;! cycles a5 a6 = 4
;! cycles a6 done = 6
;! expect b0: SZOC=1111 I=0 D=0
;! expect a1: I=1
;! expect a2: I=0
;! expect a3: SZOC=1111
;! expect a4: SZOC=1110
;! expect a5: TCI=1 SZOC=1110
;! expect a6: D=1
;! expect done: D=0 I=0 SZOC=1110 CYC=44
        ORG     $5000
start:  MVII    #$00F0, R0      ; 8: S Z O C from bits 7-4
        RSWD    R0              ; 6
b0:     EIS
a1:     DIS
a2:     SETC
a3:     CLRC
a4:     TCI
a5:     SDBD
a6:     NOP                     ; D only lasts for the next instruction
done:   NOP
