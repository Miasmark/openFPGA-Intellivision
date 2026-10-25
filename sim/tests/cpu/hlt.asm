; HLT: S1 p.56 "HaLT after next instruction is executed. Resume on control
; start." The Intellivision ties STPST* high, so the CPU stays halted; an
; interrupt does not wake it (wiki HLT). The wiki says it stops at once:
; see hlt_immediate.asm and docs/CPU_NOTES.md.
;! stop halt
;! intrm 30-
;! expect end: R0=2 R1=0 HALT=1 INTS=0
        ORG     $5000
start:  MVII    #$0300, R6      ; 0-8
        EIS                     ; 8-12
        MVII    #1, R0          ; 12-20
        HLT                     ; 20-24
        INCR    R0              ; 24-30, still runs
        INCR    R0              ; never
done:   NOP

        ORG     $6000
isr:    MVII    #$DEAD, R1
