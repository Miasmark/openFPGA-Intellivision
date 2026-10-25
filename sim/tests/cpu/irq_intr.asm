; INTR* is not masked by the I flag (S1 p.12: "INTR* is always honored").
; The Intellivision ties it high (wiki CP1610); the model supports it.
;! intr 10-
;! expect isr: CYC=23 I=0 [$0300]=x INTS=1
;! expect done: INTS=1
        ORG     $5000
start:  MVII    #$0300, R6      ; 0-8, I=0 after reset
        NOP                     ; 8-14, line low since 10: taken at 14, ISR at 23
x:      NOP
done:   NOP

        ORG     $6000
isr:    PULR    R7
