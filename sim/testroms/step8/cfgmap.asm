; Step-8 test image (DESIGN.md 9 step 8; docs/CARTFORMATS.md): BIN + CFG,
; assembled with as1600 (jzIntv's SDK-1600, run as a program) into
; cfgmap.bin + cfgmap.cfg by sim/testroms/step8/build_images.py. No code:
; every word is its own address XOR a per-range constant, so a word read at
; the wrong place shows. What the CFG exercises (the loader's map table):
;   - ranges that cover 256-word blocks whole (pointing into the file) and
;     ranges that end or start inside a block, with gaps (pool blocks)
;   - ECS-style pages in three 4K ranges: $2000 pages 1 and 3, $E000 page 1
;     (its upper 2K only), $F000 pages 0, 1, 2 and 15
;   - 16-bit RAM at $8000-$81FF and word-exact 8-bit RAM at $9000-$9002
;   - [vars]: voice = 1
; SPDX-License-Identifier: MIT

        ROMW    16

        ORG     $5000           ; $5000-$512B: block $50 whole, $51 in part
        RPT     300
        DECLE   $ XOR $1111
        ENDR
        ORG     $5140           ; a second range in block $51, after a gap
        RPT     20
        DECLE   $ XOR $2222
        ENDR
        ORG     $5800           ; $5800-$5FFF whole: eight full blocks
        RPT     2048
        DECLE   $ XOR $0F0F
        ENDR

        ORG     $D000           ; $D000-$D1FF whole
        RPT     512
        DECLE   $ XOR $4444
        ENDR
        ORG     $D2F0           ; starts inside block $D2, ends inside $D3
        RPT     40
        DECLE   $ XOR $5555
        ENDR

        ORG     $F000:0         ; page 0 of $F000
        RPT     64
        DECLE   $ XOR $6666
        ENDR
        ORG     $F000:1
        RPT     300
        DECLE   $ XOR $7777
        ENDR
        ORG     $F000:2
        RPT     8
        DECLE   $ XOR $8888
        ENDR
        ORG     $FF00:15        ; page 15, last block
        RPT     256
        DECLE   $ XOR $9999
        ENDR

        ORG     $2000:1
        RPT     100
        DECLE   $ XOR $AAAA
        ENDR
        ORG     $2800:3
        RPT     10
        DECLE   $ XOR $BBBB
        ENDR
        ORG     $E800:1
        RPT     2048
        DECLE   $ XOR $CCCC
        ENDR

        MEMATTR $8000, $81FF, "+RW"
        MEMATTR $9000, $9002, "+RWN"
        CFGVAR  "voice" = 1
