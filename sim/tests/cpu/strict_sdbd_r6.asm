; Strict mode raises on SDBD + stack (R6) mode (S1 p.49).
;! options strict
;! raises SDBD with R6
        ORG     $5000
start:  MVII    #$0301, R6
        SDBD
        ADD@    R6, R0
done:   NOP
