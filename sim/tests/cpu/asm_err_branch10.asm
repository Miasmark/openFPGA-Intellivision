; A displacement of $400 does not fit 10-bit ROM (S1 p.54).
;! asm-error out of range
        ROMW    10
        ORG     $5000
start:  B       start+2+$400
