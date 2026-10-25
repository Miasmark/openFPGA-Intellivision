; Branches that wrap past $FFFF: the CPU adds mod 2^16 (S1 p.47, p.54), so
; with 10-bit ROM a branch from $FFFE to $0003 is forward 3, and one from
; $0010 to $FFF0 is backward $21. The assembler takes the direction whose
; displacement fits.
;! words w1 = $0200 $0003
;! words w2 = $0220 $0021
;! expect done: R0=2
        ROMW    10
        ORG     $5000
start:  CLRR    R0
        J       w1
done:   NOP

        ORG     $FFFE
w1:     B       $0003
        ORG     $0003
        INCR    R0
        J       w2
        ORG     $0010
w2:     B       $FFF0
        ORG     $FFF0
        INCR    R0
        J       done
