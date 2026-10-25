; INTRM goes low while the CPU waits on a bus request: the request is seen
; at the end of the wait and taken at once (BUSRQ before interrupts, S1
; p.25), not one instruction later.
;! busrq 20-29
;! intrm 26-
;! expect isr: CYC=39 BUSAK=6 [$0300]=x INTS=1
;! expect done: INTS=1
        ORG     $5000
start:  MVII    #$0300, R6      ; 0-8
        EIS                     ; 8-12
        NOP                     ; 12-18
        NOP                     ; 18-24, bus wait 24-29, INTRM low at 26
x:      NOP
done:   NOP

        ORG     $6000
isr:    PULR    R7
