' Step-9 test cartridge (DESIGN.md 9 step 9, 17, 20): the ECS's second PSG
' (SOUND 5-9) and CONT3. Using them makes IntyBASIC boot through the EXEC's
' $4800 hook, which pages the ECS ROMs out with $2A5F, $7A5F and $EA5F
' (research/ecs-rom-use/REPORT.md 2). Built with IntyBASIC and as1600 (run as
' programs) by sim/testroms/step9/build_images.py; our own program (MIT).
' Screen: ROMS OUT (the three ROM ranges read $FFFF after the hook: page $F is
' not the ROMs' page; MAME decodes only pages 0 and 1, so there it says FAIL),
' ECS RAM (IntyBASIC's own $4040/$4041 test: ECS.AVAILABLE), a frame counter
' and CONT3 ($00FF complemented). Sound: a sweep on both PSGs, channel 6 on
' the envelope (volume 48).
    CLS
    PRINT AT 0, "STEP 9  ECS SOUND"
    #a = PEEK($7000)
    #b = PEEK($2000)
    #c = PEEK($E000)
    IF #a = $FFFF AND #b = $FFFF AND #c = $FFFF THEN PRINT AT 40, "ROMS OUT PASS" ELSE PRINT AT 40, "ROMS OUT FAIL"
    IF ECS.AVAILABLE THEN PRINT AT 60, "ECS RAM  PASS" ELSE PRINT AT 60, "ECS RAM  FAIL"
    SOUND 9, $1F, $38
    SOUND 8, $0300, 14
    f = 200
loop:
    WAIT
    c = c + 1
    IF (c AND 31) = 0 THEN f = f + 20 : IF f > 900 THEN f = 200
    SOUND 5, f, 12
    SOUND 6, f * 2, 48
    SOUND 7, f / 2, 8
    SOUND 0, f + 7, 10
    k = CONT3
    PRINT AT 100, <5>c
    PRINT AT 120, <3>k
    GOTO loop
