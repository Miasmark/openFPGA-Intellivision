; Step-8 test image: an Intellicart .rom with a bank window that writes
; ($6000-$67FF "RWB"): its writes can reach any Intellicart address, which
; the save-state blob cannot hold, so the core refuses save states for it
; (docs/CARTFORMATS.md 5). Built by sim/testroms/step8/build_images.py with
; as1600. SPDX-License-Identifier: MIT

        ROMW    16

        ORG     $5000
        RPT     64
        DECLE   $ XOR $5A5A
        ENDR
        ORG     $6000, $2000, ""
        RPT     256
        DECLE   $ XOR $A5A5
        ENDR
        MEMATTR $6000, $67FF, "=RWB"
        CFGVAR  "jlp" = 1
