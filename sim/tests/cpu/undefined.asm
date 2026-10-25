; Cases the documents leave undefined, run in the default (non-strict) mode:
; the model applies the choice in docs/CPU_NOTES.md and marks the event.
;  - SDBD + direct mode: D ignored, one 16-bit read (S1 p.49: not supported)
;  - SDBD + MVO: D ignored, one write (S1 p.49; MAME: illegal)
;  - jump with II=11 (wiki Jump: "unknown"): jumps, I unchanged
;  - MVO@ with the pointer as source (S1 p.55: "SSS = MMM = 4, 5, 6 or 7
;    not supported"): writes the old value, then increments
;! undefined u1b
;! undefined u2b
;! undefined u3
;! undefined u4b
;! expect u2: R0=$BEEF
;! expect u3: [$0201]=$BEEF
;! expect u4: I=0
;! expect done: [$0300]=$0300 R4=$0301
        ORG     $5000
start:  SDBD
u1b:    MVI     val, R0
u2:     SDBD
u2b:    MVO     R0, $0201
u3:     DECLE   $0004, $0300 + ((u4 >> 10) << 2) + 3, u4 & $3FF
u4:     MVII    #$0300, R4
u4b:    MVO@    R4, R4
done:   NOP
val:    WORD    $BEEF
