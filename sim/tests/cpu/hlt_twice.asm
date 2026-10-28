; HLT followed by HLT: G82 p.33 "Halt after next interruptable instruction
; is executed" (S1 p.56 said "after next instruction"). HLT is not
; interruptible, so the second HLT runs on and the CPU halts after the
; INCR, the first interruptible instruction (docs/CPU_NOTES.md row 7). A
; model that halted after the second HLT (S1's wording) would leave R0 = 1.
;! stop halt
;! expect end: R0=2 HALT=1 CYC=22 R7=$5005
        ORG     $5000
start:  MVII    #1, R0          ; 0-8
        HLT                     ; 8-12
        HLT                     ; 12-16, not interruptible: runs on
        INCR    R0              ; 16-22, the halt takes effect after it
        INCR    R0              ; never
