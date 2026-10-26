' Step-8 Pocket test cartridge, BIN + CFG (DESIGN.md 9 step 8; docs/CARTFORMATS.md):
' ECS-style pages at $F000 and 16- and 8-bit cart RAM declared in the CFG. Built
' with IntyBASIC and as1600 (run as programs) by sim/testroms/step8/build_images.py
' into cart8pages.bin + cart8pages.cfg. Our own program (MIT).
' Screen: two checks (PASS or FAIL), a counter kept in cart RAM and the page shown
' at $F000, which flips between 1 and 2 every 64 frames: after a save state is
' loaded, both go on from where the state was saved.
    CLS
    PRINT AT 0, "STEP 8  BIN+CFG"
    POKE $FFFF, $FA51
    #a = PEEK($F000)
    POKE $FFFF, $FA52
    #b = PEEK($F000)
    POKE $FFFF, $FA5F
    #c = PEEK($F000)
    IF #a = $1111 AND #b = $2222 AND #c = $FFF0 THEN PRINT AT 40, "PAGES PASS" ELSE PRINT AT 40, "PAGES FAIL"
    POKE $8000, $1234
    POKE $9000, $1234
    #p = $8000
    #a = PEEK(#p)            ' through a variable: IntyBASIC would reuse a poked value
    #p = $9000
    #b = PEEK(#p)
    IF #a = $1234 AND #b = $34 THEN PRINT AT 60, "RAM   PASS" ELSE PRINT AT 60, "RAM   FAIL"
    POKE $8001, 0
    POKE $9001, 1
    POKE $FFFF, $FA51
    PRINT AT 100, "COUNTER"
    PRINT AT 120, "PAGE"
loop:
    WAIT
    #a = PEEK($8001) + 1
    POKE $8001, #a
    PRINT AT 108, <5>#a
    IF (#a AND 63) = 0 THEN #p = PEEK($9001) XOR 3 : POKE $9001, #p : POKE $FFFF, $FA50 + #p
    #b = PEEK($F000)
    IF #b = $1111 THEN PRINT AT 125, "1"
    IF #b = $2222 THEN PRINT AT 125, "2"
    GOTO loop

endcode:
    ASM ORG $F000:1
    ASM DECLE $1111
    ASM ORG $F000:2
    ASM DECLE $2222
    ASM ORG $F000:15
    ASM DECLE $FFF0
    ASM ORG label_ENDCODE
    ASM MEMATTR $8000, $80FF, "+RW"
    ASM MEMATTR $9000, $90FF, "+RWN"
