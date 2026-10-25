; Two-position rotates through C and O (S1 p.50 fig 3.3.2, p.53; wiki RLC,
; RRC). RLC Rr,2: bit 1 = old C, bit 0 = old O; C = old bit 15, O = old
; bit 14. RRC Rr,2: C = old bit 0, O = old bit 1. The flags are set with
; RSWD (bits 7-4 = S Z O C) so that C and O differ.
;! expect q1: R0=$0006 SZOC=0010
;! expect q2: R1=$0000 SZOC=0101
;! expect q3: R2=$0000 SZOC=0110
        ORG     $5000
start:  MVII    #$0010, R4      ; C=1, O=0
        RSWD    R4
        MVII    #$4001, R0
        RLC     R0, 2           ; $0004 | C<<1 | O = $0006; C=0 O=1
q1:     MVII    #0, R4          ; C=0, O=0
        RSWD    R4
        MVII    #$0001, R1
        RRC     R1, 2           ; $0000; C=1 O=0
q2:     RSWD    R4
        MVII    #$0002, R2
        RRC     R2, 2           ; $0000; C=0 O=1
q3:     NOP
done:   NOP
