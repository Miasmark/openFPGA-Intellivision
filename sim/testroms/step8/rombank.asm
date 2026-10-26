; Step-8 test image (DESIGN.md 9 step 8; docs/CARTFORMATS.md 3): an
; Intellicart .rom, assembled with as1600 (run as a program) by
; sim/testroms/step8/build_images.py. No code; every word is its own
; Intellicart address XOR a per-range constant. It exercises:
;   - read-only windows ($5000, $D100-$D2FF through the fine-address table)
;   - Intellicart bank windows $6000-$67FF and $6800-$6FFF (read only,
;     "B"): banksel.asm in the EXEC slot (tb_system image "cartbank") points
;     them at the data loaded at $1000, $3000 and at the RAM below
;   - 16-bit RAM $8000-$83FF and 8-bit RAM $8800-$88FF (relocated by the
;     loader into the save state's cart RAM area)
;   - Intellicart memory loaded but not mapped ($1000, $3000: "preload")
;   - the metadata tags (as1600 CFGVAR): voice = 1
; SPDX-License-Identifier: MIT

        ROMW    16

        ORG     $5000
        RPT     256
        DECLE   $ XOR $1357
        ENDR

        ORG     $6000, $1000, ""        ; Intellicart memory $1000: no window
        RPT     512
        DECLE   $ XOR $2468
        ENDR
        ORG     $6000, $3000, ""        ; and $3000
        RPT     256
        DECLE   $ XOR $369C
        ENDR

        ORG     $D100
        RPT     512
        DECLE   $ XOR $4321
        ENDR

        MEMATTR $6000, $6FFF, "=RB"
        MEMATTR $8000, $83FF, "+RW"
        MEMATTR $8800, $88FF, "+RWN"
        CFGVAR  "voice" = 1
