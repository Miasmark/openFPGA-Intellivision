; Shifts work on R0-R3 only (S1 p.50: "Shifts can only be performed on
; Registers R0 - R3").
;! asm-error shift register
        ORG     $5000
start:  SLL     R4
