; ROMW 10: the assembler adds SDBD and two decles for an immediate over $3FF
; (S1 p.49 note), so the program runs the same from 10-bit ROM.
;! words a1 = $0001 $02B8 $0034 $0012
;! words a2 = $02B9 $03FF
;! words a3 = $0001 $02FA $00FF $00FF
;! expect done: R0=$1234 R1=$03FF R2=$FFFF
        ROMW    10
        ORG     $5000
start:  CLRR    R2
a1:     MVII    #$1234, R0
a2:     MVII    #$3FF, R1
a3:     ADDI    #-1, R2
done:   NOP
