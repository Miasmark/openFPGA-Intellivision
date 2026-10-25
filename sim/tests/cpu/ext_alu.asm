; ADD SUB CMP AND XOR from memory in direct, indirect, post-increment, stack
; and immediate modes. S1 p.45 (status), p.55, p.57; wiki ADD, ADD@, SUB@,
; CMP, AND, XOR. CMP computes register minus memory and keeps the register.
;! expect x2: R0=$8000 SZOC=1010
;! expect x3: R0=0 SZOC=0111
;! expect x4: R2=$FFFE R4=v3+1 SZOC=1000
;! expect x5: R2=$FFFE SZOC=1001
;! expect x6: R3=$000F R6=$0300 SZOC=0001
;! expect x7: R3=$FFF0 SZOC=1001
;! expect x8: R3=0 SZOC=0101
;! expect x9: R3=$FFFF SZOC=1000
;! expect x10: R3=0 SZOC=0101
;! expect x11: R0=0 SZOC=0101
;! expect x12: R0=$1234 SZOC=0001
;! expect x13: R0=9 SZOC=0001
;! expect x14: R0=9 R5=v3+1 SZOC=0001
;! expect x15: R0=8 SZOC=0001
;! expect x16: R0=$8008 R6=$0300 SZOC=1010
;! expect done: SZOC=0101
;! cycles x1 x2 = 10
;! cycles x2 x3 = 16
;! cycles a5 x6 = 11
;! cycles x6 x7 = 8
        ORG     $5000
start:  MVII    #$0300, R6
        MVII    #$7FFF, R0
x1:     ADD     v1, R0          ; $8000: S O
x2:     MVII    #v2, R1
        ADD@    R1, R0          ; + $8000 = 0: Z O C
x3:     MVII    #5, R2
        MVII    #v3, R4
        SUB@    R4, R2          ; 5 - 7 = $FFFE: S, borrow
x4:     CMP     v3, R2          ; $FFFE - 7: S C; R2 kept
x5:     MVII    #$0F0F, R0
        PSHR    R0
        MVII    #$00FF, R3
a5:     AND@    R6, R3          ; stack read: 11 cycles
x6:     XORI    #$FFFF, R3
x7:     ANDI    #0, R3
x8:     SUBI    #1, R3          ; 0 - 1: S, borrow
x9:     ADDI    #1, R3          ; $FFFF + 1: Z C
x10:    MVII    #$1234, R0
        XOR     v4, R0
x11:    MVII    #$FFFF, R0
        AND     v4, R0
x12:    MVII    #$0010, R0
        SUB     v3, R0          ; 16 - 7 = 9: C
x13:    MVII    #v3, R5
        CMP@    R5, R0          ; 9 - 7: C
x14:    MVII    #v1, R2
        XOR@    R2, R0          ; 9 ^ 1 = 8
x15:    MVII    #$8000, R1
        PSHR    R1
        SUB@    R6, R0          ; 8 - $8000 = $8008: S O, borrow
x16:    CMPI    #$8008, R0
done:   NOP
v1:     WORD    1
v2:     WORD    $8000
v3:     WORD    7
v4:     WORD    $1234
