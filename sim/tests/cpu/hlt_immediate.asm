; HLT with the wiki's reading (hlt=immediate): nothing after HLT runs.
;! options hlt=immediate
;! stop halt
;! expect end: R0=1 HALT=1
        ORG     $5000
start:  MVII    #1, R0
        HLT
        INCR    R0
done:   NOP
