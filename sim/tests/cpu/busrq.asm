; BUSRQ*: after an interruptible instruction the CPU stops (BUSAK*, NACT)
; until BUSRQ* goes high again, whatever the I flag (S1 p.14, p.24; wiki
; CP1610). Non-interruptible instructions hold it off, so a short request
; during a run of shifts is missed altogether (wiki STIC_Bus_Request).
;! busrq 20-39 60-70
;! expect b1: CYC=40 BUSAK=16
;! expect b2: CYC=82 BUSAK=16
        ORG     $5000
start:  NOP                     ; 0-6
        NOP                     ; 6-12
        NOP                     ; 12-18
        NOP                     ; 18-24, then waits 24-39
b1:     NOP                     ; 40-46
        SLL     R0              ; 46-52
        SLL     R0              ; 52-58
        SLL     R0              ; 58-64
        SLL     R0              ; 64-70
        SLL     R0              ; 70-76
        NOP                     ; 76-82, request gone at 71
b2:     NOP
done:   NOP
