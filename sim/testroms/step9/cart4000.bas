' Step-9 test cartridge (DESIGN.md 20): a cartridge that maps $4000-$47FF
' itself, so the core's Auto rule leaves the ECS off (its RAM would clash).
' Built with IntyBASIC and as1600 (run as programs) by
' sim/testroms/step9/build_images.py; our own program (MIT).
' Screen: CART 4000 (the cartridge's own words at $4000, written to first,
' and $47FF read back), ECS OFF (IntyBASIC's $4040/$4041 test finds no ECS:
' $4040 is not mapped) and a frame counter.
    CLS
    PRINT AT 0, "STEP 9  CART 4000"
    #p = $4000
    POKE #p, $5A            ' its ROM keeps $1234; with the ECS forced on, its RAM takes $5A
    #a = PEEK(#p)
    #p = $47FF
    #b = PEEK(#p)
    IF #a = $1234 AND #b = $5678 THEN PRINT AT 40, "CART 4000 PASS" ELSE PRINT AT 40, "CART 4000 FAIL"
    IF ECS.AVAILABLE THEN PRINT AT 60, "ECS OFF   FAIL" ELSE PRINT AT 60, "ECS OFF   PASS"
loop:
    WAIT
    c = c + 1
    PRINT AT 120, <5>c
    GOTO loop

endcode:
    ASM ORG $4000
    ASM DECLE $1234
    ASM ORG $47FF
    ASM DECLE $5678
    ASM ORG label_ENDCODE
