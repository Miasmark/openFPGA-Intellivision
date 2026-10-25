; With 10-bit ROM (ROMW 10) a displacement must fit 10 bits: the farthest
; branches are forward to PC+2+$3FF and backward to PC+1-$3FF (S1 p.54).
;! words fwd = $0200 $03FF
;! words bwd = $0220 $03FF
;! expect done: R0=2
        ROMW    10
        ORG     $5000
start:  CLRR    R0
fwd:    B       fwd+2+$3FF      ; $5402
        ORG     $5402
        INCR    R0
        J       bwd
        ORG     $5600
bwd:    B       bwd+1-$3FF      ; $5202
        ORG     $5202
        INCR    R0
        J       done
        ORG     $5700
done:   NOP
