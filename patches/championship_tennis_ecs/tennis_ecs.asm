; SPDX-License-Identifier: MIT
; Copyright (c) 2026 Miasmark and contributors
;
; Championship Tennis (INTV 1985) with the ECS: our own patch words, nothing of the game's.
; The ECS's third ROM page sits at $E000-$EFFF and hides the cartridge's own $E000-$EFFF once the
; ECS boot pages it in ($EA51 to $EFFF). The cartridge's title routine ($5056, after the title
; string at $5048) calls its code at $EF10, so with the ECS on the EXEC ran ECS ROM code there.
; This patch pages the ECS's $E ROM out ($EA50 to $EFFF, the documented way: jzIntv doc/tech/
; ecs.html; World Series Major League Baseball does the same) before the title routine goes on.
; Without an ECS the write lands on the cartridge's ROM and does nothing.
; See README.md and docs: ~/daria_work/intv/wcf/TENNIS.md (outside the repository).

        ROMW    10              ; the cartridge is 10-bit ROM: 16-bit constants get SDBD

TITLE   EQU     $5056           ; the title routine: PSHR R5 / MVII #$0007, R3 / MVII #$023D, R4
BACK    EQU     $5059           ; its third instruction
STUB    EQU     $6FE0           ; end padding of the $5000 segment (unused: README)

        ORG     TITLE
        J       STUB            ; 3 words over PSHR R5 and MVII #$0007, R3

        ORG     STUB
        PSHR    R5              ; the first displaced instruction
        MVII    #$EA50, R3      ; $E page 0: the ECS's $E ROM out, the cartridge's back
        MVII    #$EFFF, R4      ; the $E range's page register
        MVO@    R3, R4
        MVII    #$0007, R3      ; the second displaced instruction
        J       BACK
