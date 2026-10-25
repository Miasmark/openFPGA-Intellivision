; SDBD builds its operand from the low byte of each of the two words it
; reads (S1 p.49 fig 3.2.6, 3.2.7; wiki Double_Byte_Data); bits 8-15 of
; the words are dropped. 10-bit ROM words ($03xx) and GROM reads ($FFxx,
; DB8-15 pulled up) carry ones there.
;! expect w1: R0=$10CD
;! expect w2: R1=$5634 R4=tbl+2
;! expect w3: R2=$7878 R3=tbl+2
        ORG     $5000
start:  SDBD
        DECLE   $02B8, $03CD, $FF10     ; MVII #$10CD, R0 from $03CD $FF10
w1:     MVII    #tbl, R4
        SDBD
        MVI@    R4, R1          ; $FF34, $0356 -> $5634
w2:     MVII    #tbl+2, R3
        SDBD
        MVI@    R3, R2          ; $0378 twice -> $7878
w3:     NOP
done:   NOP
tbl:    WORD    $FF34, $0356, $0378
