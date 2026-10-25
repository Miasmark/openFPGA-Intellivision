; Non-interruptible instructions hold an interrupt off: shifts, MVO and SDBD
; (wiki CP1610 table; S1 p.53 "Shifts are not interruptable", p.56-57).
; INTRM* goes low at 20; the first interruptible boundary is after the MVII
; that ends at 57, so the ISR starts at 57 + 9 = 66.
;! intrm 20-
;! expect isr: CYC=66 [$0300]=after R1=$1234 INTS=1
;! expect done: INTS=1
        ORG     $5000
start:  MVII    #$0300, R6      ; 0-8
        EIS                     ; 8-12
        NOP                     ; 12-18
        SLL     R0              ; 18-24, request seen at 24
        SLL     R0, 2           ; 24-32
        MVO     R0, $0200       ; 32-43
        SDBD                    ; 43-47
        MVII    #$1234, R1      ; 47-57: interruptible
after:  NOP
done:   NOP

        ORG     $6000
isr:    PULR    R7
