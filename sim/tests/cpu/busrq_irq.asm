; Bus requests are served before interrupts (S1 p.25: "the CPU will honor
; Bus Requests before it will honor Interrupt Requests").
;! busrq 20-29
;! intrm 20-
;! expect isr: CYC=39 BUSAK=6 [$0300]=x INTS=1
;! expect done: INTS=1
        ORG     $5000
start:  MVII    #$0300, R6      ; 0-8
        EIS                     ; 8-12
        NOP                     ; 12-18
        NOP                     ; 18-24, bus wait 24-29, interrupt 30-38
x:      NOP
done:   NOP

        ORG     $6000
isr:    PULR    R7
