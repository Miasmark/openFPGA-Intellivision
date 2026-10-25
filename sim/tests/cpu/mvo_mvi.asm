; Moves in and out in every mode: direct, indirect R1-R3, post-increment
; R4/R5, stack R6 (push post-increments, pull pre-decrements), immediate R7.
; S1 p.46-48 (fig 3.2.1-3.2.5), p.55, p.57; wiki MVO, MVO@, MVOI, MVI, MVI@,
; MVII. Cycles: MVO 11, MVO@/PSHR/MVOI 9, MVI 10, MVI@/MVII 8, PULR 11.
; Moves leave the flags alone.
;! expect m2: [$0200]=$1111 SZOC=1111
;! expect m4: [$0201]=$2222 R1=$0201
;! expect m5: [$0202]=$2222 [$0203]=$1111 R4=$0204
;! expect m6: [$0210]=$1111 R5=$0211
;! expect m7: [$0300]=$1111 [$0301]=$2222 R6=$0302
;! expect m8: R3=$2222 R6=$0301
;! expect m9: R1=$1111
;! expect m10: R5=$2222 R4=$0203
;! expect m11: R0=$2222 R2=$0201
;! expect m12: [m11+1]=$1111
;! expect m13: R0=$1111
;! expect m14: R0=0 R6=$02FF
;! expect done: SZOC=1111
;! cycles m1 m2 = 11
;! cycles m3 m4 = 9
;! cycles m6 m7 = 18
;! cycles m7 m8 = 11
;! cycles m8 m9 = 10
;! cycles m9 m10 = 16
;! cycles m11 m12 = 9
;! cycles m12 m13 = 10
;! cycles m14 m15 = 8
        ORG     $5000
start:  MVII    #$00F0, R0
        RSWD    R0
        MVII    #$0300, R6
        MVII    #$1111, R0
m1:     MVO     R0, $0200
m2:     MVII    #$0201, R1
        MVII    #$2222, R2
m3:     MVO@    R2, R1          ; R1 does not change
m4:     MVII    #$0202, R4
        MVO@    R2, R4          ; R4 increments
        MVO@    R0, R4
m5:     MVII    #$0210, R5
        MVO@    R0, R5
m6:     PSHR    R0
        PSHR    R2
m7:     PULR    R3
m8:     MVI     $0200, R1
m9:     MVII    #$0202, R4
        MVI@    R4, R5
m10:    MVII    #$0201, R2
        MVI@    R2, R0
m11:    MVOI    R1, 0           ; writes R1 over its own immediate word
m12:    MVI     m11+1, R0
m13:    MVII    #$0300, R6
        PULR    R0              ; pre-decrement: reads $02FF
m14:    MVII    #m15, R7        ; immediate into the PC is a jump
        DECLE   0
m15:    NOP
done:   NOP
