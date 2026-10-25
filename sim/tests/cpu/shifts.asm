; Shifts and rotates on R0-R3, one or two positions. S1 p.50 fig 3.3.2,
; p.53 ("Shift Right instructions set the S flip-flop with Bit 7 of the
; result"; "SWAP: S equals Bit 7"; two-position forms use C as bit 16/17 and
; OV as bit 16/17); wiki SWAP, SLL, RLC, SLLC, SLR, SAR, RRC, SARC.
; Double SWAP follows the wiki (low byte into both halves); S1 p.53 says
; "swap them back to original form" (docs/CPU_NOTES.md).
;! expect s1: R0=$0180 SZOC=1000
;! expect s2: R1=$3434 SZOC=0000
;! expect s3: R2=$FFFF SZOC=1000
;! expect s4: R0=$8002 SZOC=1000
;! expect s5: R0=$0008 SZOC=0000
;! expect s6: R1=$0000 SZOC=0100
;! expect s7: R0=$0001 SZOC=0001
;! expect s8: R1=$0003 SZOC=0010
;! expect s9: R2=$8000 SZOC=1011
;! expect s10: R2=$0004 SZOC=0010
;! expect s11: R0=$4001 SZOC=0010
;! expect s12: R0=$00C0 SZOC=1010
;! expect s13: R1=$C040 SZOC=0010
;! expect s14: R1=$F010 SZOC=0010
;! expect s15: R2=$8001 SZOC=0000
;! expect s16: R2=$8000 SZOC=0011
;! expect s17: R0=$C002 SZOC=0011
;! expect s18: R0=$0001 SZOC=0010
;! expect s19: R1=$0000 SZOC=0110
;! expect s20: R1=$0080 SZOC=0010
;! expect s21: R2=$8000 SZOC=1010
;! cycles c1 c2 = 6
;! cycles c2 c3 = 8
;! cycles c3 c4 = 6
;! cycles c4 c5 = 8
;! cycles c5 c6 = 8
;! cycles c6 done = 6
        ORG     $5000
start:  MVII    #$8001, R0
        SWAP    R0              ; $0180, S from bit 7
s1:     MVII    #$1234, R1
        SWAP    R1, 2           ; $3434
s2:     MVII    #$00FF, R2
        SWAP    R2, 2           ; $FFFF, S from bit 7
s3:     MVII    #$C001, R0
        SLL     R0              ; $8002, S from bit 15
s4:     SLL     R0, 2           ; $0008
s5:     MVII    #$4000, R1
        SLL     R1, 2           ; 0: Z
s6:     MVII    #$0010, R3      ; C=1
        RSWD    R3
        MVII    #$8000, R0
        RLC     R0              ; C into bit 0, bit 15 into C: $0001, C
s7:     MVII    #$0030, R3      ; O=1 C=1
        RSWD    R3
        MVII    #$4000, R1
        RLC     R1, 2           ; bit 1 = old C, bit 0 = old O; C = bit 15, O = bit 14
s8:     MVII    #$C000, R2
        SLLC    R2              ; C = bit 15; O kept
s9:     MVII    #$4001, R2
        SLLC    R2, 2           ; C = bit 15 (0), O = bit 14 (1)
s10:    MVII    #$8003, R0
        SLR     R0              ; $4001, S from bit 7 (0); C O kept
s11:    MVII    #$0300, R0
        SLR     R0, 2           ; $00C0, S from bit 7 (1)
s12:    MVII    #$8080, R1
        SAR     R1              ; $C040, sign copied, S from bit 7 (0)
s13:    SAR     R1, 2           ; $F010
s14:    MVII    #$0010, R3      ; C=1 O=0
        RSWD    R3
        MVII    #$0002, R2
        RRC     R2              ; old C into bit 15: $8001; C = bit 0 (0)
s15:    MVII    #$0020, R3      ; O=1 C=0
        RSWD    R3
        MVII    #$0003, R2
        RRC     R2, 2           ; bit 15 = old O, bit 14 = old C: $8000; C = bit 0, O = bit 1
s16:    MVII    #$8005, R0
        SARC    R0              ; C = bit 0; $C002; O kept
s17:    MVII    #$0006, R0
        SARC    R0, 2           ; C = bit 0 (0), O = bit 1 (1); $0001
s18:    MVII    #$0001, R1
        SLR     R1              ; 0: Z
s19:    MVII    #$0040, R1
        SLL     R1              ; $0080: S from bit 15 (0), not bit 7
s20:    MVII    #$4000, R2
        RLC     R2              ; $8000: S from bit 15
s21:    NOP
c1:     SLL     R3
c2:     SLL     R3, 2
c3:     SWAP    R3
c4:     SWAP    R3, 2
c5:     RRC     R3, 2
c6:     NOP
done:   NOP
