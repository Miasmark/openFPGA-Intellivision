; Cases the documents leave undefined, run in the default (non-strict) mode:
; the model applies the choice in docs/CPU_NOTES.md and marks the event.
; All four were measured on the owner's Model 2609 (hw_cpuodd, 2026-10-31):
;  - SDBD + direct mode: the address is double byte data from the next two
;    words (their low bytes, low first), then one 16-bit read there
;  - SDBD + MVO: D ignored, one write (S1 p.49; MAME: illegal)
;  - jump with II=11 (wiki Jump: "unknown"): jumps, and enables interrupts
;    as JE
;  - MVO@ with the pointer as source (S1 p.55: "SSS = MMM = 4, 5, 6 or 7
;    not supported"): writes the incremented pointer
;! undefined u1b
;! undefined u2b
;! undefined u3
;! undefined u4b
;! expect u2: R0=$1234
;! expect u3: [$0201]=$1234
;! expect u4: I=1
;! expect done: [$0300]=$0301 R4=$0301
        ORG     $5000
start:  MVII    #$1234, R1
        MVO     R1, $0211
        SDBD
u1b:    DECLE   $0280, $0011, $0002     ; MVI <$0211>, R0: the address in two words
u2:     SDBD
u2b:    MVO     R0, $0201
u3:     DECLE   $0004, $0300 + ((u4 >> 10) << 2) + 3, u4 & $3FF
u4:     MVII    #$0300, R4
u4b:    MVO@    R4, R4
done:   NOP
