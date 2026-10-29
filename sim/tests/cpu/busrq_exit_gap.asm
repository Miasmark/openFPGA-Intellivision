; The 2 NACT cycles after a bus request (30-31 here) do not look at the
; request lines: a BUSRQ* pulse inside them is not seen. The lines are sampled
; at their end (32), where an INTRM* edge that came during them is taken at
; once (BUSRQ first, then interrupts: S1 p.25). 9 cycles of interrupt
; sequence: the handler at 41.
;! busrq 20-29 31-31
;! intrm 31-
;! expect isr: CYC=41 BUSAK=8 [$0300]=x INTS=1
;! expect done: INTS=1
        ORG     $5000
start:  MVII    #$0300, R6      ; 0-8
        EIS                     ; 8-12
        NOP                     ; 12-18
        NOP                     ; 18-24
x:      NOP
done:   NOP

        ORG     $6000
isr:    PULR    R7
