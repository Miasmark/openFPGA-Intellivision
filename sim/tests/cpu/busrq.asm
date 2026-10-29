; BUSRQ*: after an interruptible instruction the CPU stops (BUSAK*, NACT)
; until BUSRQ* goes high again, whatever the I flag (S1 p.14, p.24; wiki
; CP1610). Non-interruptible instructions hold it off, so a short request
; during a run of shifts is missed altogether (wiki STIC_Bus_Request).
; Each served request ends with 2 more NACT cycles, BUSAK* still low: the
; cycle whose TS1 sees BUSRQ* high and the next (S1 p.36, G82 Fig. 16).
;! busrq 20-39 60-70
;! expect b1: CYC=42 BUSAK=18
;! expect b2: CYC=84 BUSAK=18
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
