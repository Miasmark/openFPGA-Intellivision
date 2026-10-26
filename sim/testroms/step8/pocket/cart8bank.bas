' Step-8 Pocket test cartridge, Intellicart .rom (DESIGN.md 9 step 8;
' docs/CARTFORMATS.md): bank windows at $6000 and $6800 over Intellicart memory
' loaded at $1000 and $3000, and 16- and 8-bit RAM. Built with IntyBASIC and as1600
' (run as programs) by sim/testroms/step8/build_images.py into cart8bank.rom. Our
' own program (MIT). Screen: two checks (PASS or FAIL), a counter kept in cart RAM,
' and the word the $6800 window shows, which walks with the counter: after a save
' state is loaded, both go on from where the state was saved.
    CLS
    PRINT AT 0, "STEP 8  INTELLICART"
    POKE $46, $10
    #a = PEEK($6000)
    POKE $56, $30
    #b = PEEK($6801)
    IF #a = $1357 AND #b = $2468 THEN PRINT AT 40, "BANKS PASS" ELSE PRINT AT 40, "BANKS FAIL"
    POKE $8000, $4321
    POKE $46, $80
    #a = PEEK($6000)
    POKE $8800, $1234
    #p = $8800
    #b = PEEK(#p)            ' through a variable: IntyBASIC would reuse the poked value
    IF #a = $4321 AND #b = $34 THEN PRINT AT 60, "RAM   PASS" ELSE PRINT AT 60, "RAM   FAIL"
    POKE $8001, 0
    PRINT AT 100, "COUNTER"
    PRINT AT 120, "WINDOW"
loop:
    WAIT
    #a = PEEK($8001) + 1
    POKE $8001, #a
    PRINT AT 108, <5>#a
    POKE $56, $30
    #b = PEEK($6800 + (#a AND 7))
    PRINT AT 127, <5>#b
    GOTO loop

endcode:
    ASM ORG $6000, $1000, ""
    ASM DECLE $1357
    ASM ORG $6000, $3000, ""
    ASM DECLE $1000, $2468, $3000, $4000, $5000, $6000, $7000, $8000
    ASM ORG label_ENDCODE
    ASM MEMATTR $6000, $6FFF, "=RB"
    ASM MEMATTR $8000, $83FF, "+RW"
    ASM MEMATTR $8800, $88FF, "+RWN"
