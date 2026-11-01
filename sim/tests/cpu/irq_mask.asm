; The I flag masks INTRM, and a request that goes away before it is taken is
; dropped (wiki CP1610 Signal Pins: "If the signal transitions back to the
; high state prior to taking the interrupt, the CPU will ignore the
; interrupt"). JE is interruptible and enables at once (wiki Jump, CP1610).
; Pulse 1: cycles 20-30 while I=0, gone by 36. After EIS nothing happens.
; Pulse 2: from 80 while I=0, still low when JE ends at 99 (13 cycles: the jumps are one
; cycle longer than S1's 12 in the console fit F, docs/TIMING_FIT.md): taken there.
;! intrm 20-30 80-
;! expect e1: CYC=52 INTS=0 I=1
;! expect isr: CYC=108 [$0300]=next INTS=1 I=1
;! expect done: INTS=1
        ORG     $5000
start:  MVII    #$0300, R6      ; 0-8
        DIS                     ; 8-12
        NOP                     ; 12-18
        NOP                     ; 18-24 request latched
        NOP                     ; 24-30
        NOP                     ; 30-36 line high again: dropped
        NOP                     ; 36-42
        EIS                     ; 42-46
        NOP                     ; 46-52 no interrupt
e1:     NOP                     ; 52-58
        NOP                     ; 58-64
        NOP                     ; 64-70
        DIS                     ; 70-74
        NOP                     ; 74-80 request latched at 80, masked
        NOP                     ; 80-86
        JE      next            ; 86-99, enables: taken at 99
next:   NOP
done:   NOP

        ORG     $6000
isr:    PULR    R7
