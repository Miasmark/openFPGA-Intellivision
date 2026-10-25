; SIN is interruptible (docs/CPU_NOTES.md "Where the sources disagree": the
; model's choice; cp1610.sv fin_ok). INTRM* goes low at 14, inside the first
; shift; the shifts hold it off (S1 p.53), so the first boundary that may
; take it is after the SIN that ends at 32: the INTAK follows the SIN and
; the ISR starts at 32 + 9 = 41 with the return address 'after'. If SIN
; were not interruptible, the NOP after it would run first (ISR at 47).
;! intrm 14-
;! expect isr: CYC=41 [$0300]=after INTS=1 SIN=1
;! expect done: INTS=1
        ORG     $5000
start:  MVII    #$0300, R6      ; 0-8
        EIS                     ; 8-12
        SLL     R0              ; 12-18, request seen at 18: not interruptible
        SLL     R0, 2           ; 18-26, not interruptible
        SIN                     ; 26-32: interruptible
after:  NOP
done:   NOP

        ORG     $6000
isr:    PULR    R7
