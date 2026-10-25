; Strict mode raises on a jump with II=11 (wiki Jump: behaviour unknown).
;! options strict
;! raises II=11
        ORG     $5000
start:  DECLE   $0004, $0303 + ((done >> 10) << 2), done & $3FF
done:   NOP
