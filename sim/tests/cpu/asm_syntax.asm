; Assembler syntax: EQU (also forward), expressions and their precedence,
; number forms, character and string data, BIDECLE, RES, '$', register
; aliases SP and PC, labels without a colon in column 0.
;! words w1 = 33 $FFFF 65 10 31 5 3
;! words w2 = 7 9 17 255 3 $77 $34 $12
;! words s1 = $48 $69 $3B
;! words r1x = $00B7
;! words lab2 = $0034 lab2
;! words after = $0034
;! expect done: CYC=6
        ORG     $4800
k1      EQU     $10
k2:     EQU     k1*2+1
w1:     WORD    k2, -1, 'A', %1010, 0x1F, $ - w1, 0b11
w2:     WORD    1+2*3, (1+2)*3, 1<<4|1, ~0 & $FF, 7/2, later
        BIDECLE $1234
s1:     STRING  "Hi;"           ; a ';' inside quotes is not a comment
r1x:    MOVR    SP, PC
lab2    NOP
        DECLE   lab2
later   EQU     $77
        RES     2
after:  NOP

        ORG     $5000
start:  NOP
done:   NOP
