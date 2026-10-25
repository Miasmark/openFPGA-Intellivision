; Jumps to addresses above $7FFF (S1 p.52: word 2 = BB AAAAAA II gives
; address bits 15-10), run from there; and opcode words with bits 10-15
; set, which the CPU ignores (S1 p.46: "for future use"; only bits 0-9
; decode).
;! words wj = $0004 $03F0 $0100
;! words ws = $0004 $0180 $0200
;! expect e1: R0=1 R5=back
;! expect h1: I=1
;! expect h2: R1=$1234
;! expect h3: C=1
;! expect done: R0=2
        ORG     $5000
start:  MVII    #$0300, R6
wj:     J       $F100
ret1:   DIS
        DECLE   $FC02           ; EIS with bits 10-15 set
h1:     DECLE   $FEB9, $1234    ; MVII #$1234, R1 ($02B9) with bits 10-15 set
h2:     DECLE   $FC07           ; SETC with bits 10-15 set
h3:     NOP
done:   NOP

        ORG     $F100
f1:     MVII    #1, R0
ws:     JSR     R5, $8200
back:   J       ret1

        ORG     $8200
e1:     INCR    R0
        JR      R5
