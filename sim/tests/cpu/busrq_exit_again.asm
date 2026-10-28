; A bus request ends with 2 more NACT cycles, BUSAK* still low (S1 p.36,
; G82 Fig. 16); BUSRQ* is sampled again at their end, where the next step
; starts: asserted there, a second wait follows at once, with no fetch in
; between. Wait 24-29, 2 NACT 30-31, BUSRQ* seen at 32: wait 32-35, 2 NACT
; 36-37, then x at 38.
;! busrq 20-29 32-35
;! expect x: CYC=38 BUSAK=14
;! expect done: CYC=44
        ORG     $5000
start:  MVII    #$0300, R6      ; 0-8
        EIS                     ; 8-12
        NOP                     ; 12-18
        NOP                     ; 18-24
x:      NOP                     ; 38-44
done:   NOP
