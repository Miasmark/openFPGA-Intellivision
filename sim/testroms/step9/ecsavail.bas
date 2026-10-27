' Step-9 test cartridge (DESIGN.md 20): no ECS feature, so no $4800 hook; the
' core's Auto rule then attaches the ECS with its ROMs paged out from reset.
' Built with IntyBASIC and as1600 (run as programs) by
' sim/testroms/step9/build_images.py; our own program (MIT).
' Screen: ECS RAM (IntyBASIC's $4040/$4041 test finds the ECS: ECS.AVAILABLE),
' NO MENU ($7000 reads $FFFF: the ECS ROM is out, so the EXEC booted this
' cartridge straight), 8 BIT (a word written to ECS RAM reads back as its low
' byte) and a frame counter.
    CLS
    PRINT AT 0, "STEP 9  ECS AUTO"
    IF ECS.AVAILABLE THEN PRINT AT 40, "ECS RAM  PASS" ELSE PRINT AT 40, "ECS RAM  FAIL"
    #a = PEEK($7000)
    IF #a = $FFFF THEN PRINT AT 60, "NO MENU  PASS" ELSE PRINT AT 60, "NO MENU  FAIL"
    #p = $4100
    POKE #p, $1234
    #b = PEEK(#p)
    IF #b = $34 THEN PRINT AT 80, "8 BIT    PASS" ELSE PRINT AT 80, "8 BIT    FAIL"
loop:
    WAIT
    c = c + 1
    PRINT AT 120, <5>c
    GOTO loop
