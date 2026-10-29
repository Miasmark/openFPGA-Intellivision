; BUSRQ asserted during the interrupt sequence: the first handler
; instruction runs before the request is served. The interrupt sequence
; ends non-interruptibly, like MAME; S1 does not say (docs/CPU_NOTES.md,
; estimated).
; Each served request ends with 2 more NACT cycles, BUSAK* still low: the
; cycle whose TS1 sees BUSRQ* high and the next (S1 p.36, G82 Fig. 16).
;! intrm 14-
;! busrq 20-40
;! expect isr: CYC=27 BUSAK=0 INTS=1
;! expect i2: CYC=43 BUSAK=10
;! expect done: INTS=1 R0=1
        ORG     $5000
start:  MVII    #$0300, R6      ; 0-8
        EIS                     ; 8-12
        NOP                     ; 12-18, interrupt 18-27
x:      NOP
done:   NOP

        ORG     $6000
isr:    INCR    R0              ; 27-33, then bus wait 33-40
i2:     PULR    R7
