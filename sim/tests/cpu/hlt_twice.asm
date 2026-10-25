; HLT followed by HLT: S1 p.56 "HaLT after next instruction is executed".
; The next instruction is the second HLT, whatever it does, so the CPU
; halts after it (docs/CPU_NOTES.md row 7). A model that skipped HLTs as
; "the next instruction" would run on into the INCR and the unassembled
; word after it.
;! stop halt
;! expect end: R0=1 HALT=1 CYC=16 R7=$5004
        ORG     $5000
start:  MVII    #1, R0          ; 0-8
        HLT                     ; 8-12
        HLT                     ; 12-16, the halt takes effect after it
        INCR    R0              ; never
