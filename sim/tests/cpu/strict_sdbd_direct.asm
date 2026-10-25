; Strict mode raises on SDBD + direct mode (S1 p.49: modes 0 and 6 are not
; supported for double byte data).
;! options strict
;! raises SDBD with direct mode
        ORG     $5000
start:  SDBD
        MVI     $0200, R0
done:   NOP
