; SDBD (Set Double Byte Data): the next instruction reads two words and
; builds a 16-bit operand from their low bytes, low byte first. S1 p.46-49
; (fig 3.2.6, 3.2.7), p.57; wiki SDBD, Double_Byte_Data, MVI@.
;  - immediate (R7): the two words after the opcode, PC + 3
;  - R4/R5: two consecutive locations, pointer + 2
;  - R1-R3: the same location twice
;  - D lasts for one instruction only, whatever it is
;  - SDBD 4 cycles (not interruptible) + 10 for the instruction
;  - R6 (not supported, S1 p.49): the model's default follows the wiki
;    (one pre-decrement, the same location read twice, 10 cycles)
;! expect d1: D=1
;! expect d3: R0=$ABCD R1=$1234 R4=tbl+2
;! expect d4: R3=$3434 R2=tbl
;! expect d5: R0=$9001 R5=tbl+4 SZOC=1000
;! expect d6: R0=0 SZOC=0101
;! expect d7: R0=0 SZOC=1000
;! expect d8: R1=$0FF0 SZOC=0000
;! expect d9: R1=0 SZOC=0100
;! expect d10: R2=0 D=0
;! expect d11: D=0
;! expect d12: R0=$5656 R6=stk+1
;! undefined p1b
;! cycles start d1 = 4
;! cycles d1 d2 = 10
;! cycles d2 d2b = 8
;! cycles d2b d3 = 14
;! cycles p1 d12 = 14
        ORG     $5000
start:  SDBD
d1:     MVII    #$ABCD, R0      ; words: $02B8 $00CD $00AB
d2:     MVII    #tbl, R4
d2b:    SDBD
        MVI@    R4, R1          ; $34 from $FF34, $12 from $FF12
d3:     MVII    #tbl, R2
        SDBD
        MVI@    R2, R3          ; same word twice: $3434
d4:     MVII    #tbl+2, R5
        MVII    #$1000, R0
        SDBD
        ADD@    R5, R0          ; $1000 + $8001
d5:     SDBD
        SUBI    #$9001, R0
d6:     SDBD
        CMPI    #1, R0          ; 0 - 1: S, borrow
d7:     MVII    #$FFFF, R1
        SDBD
        ANDI    #$0FF0, R1
d8:     SDBD
        XORI    #$0FF0, R1
d9:     SDBD
        MOVR    R1, R2          ; D has no effect here and is cleared
d10:    SDBD
        NOP                     ; consumes D
d11:    MVII    #stk+2, R6
p1:     SDBD
p1b:    PULR    R0
d12:    NOP
done:   NOP
tbl:    WORD    $FF34, $FF12, $0001, $0080
stk:    WORD    $0012, $0056
