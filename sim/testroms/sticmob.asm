; Step-5 STIC test: MOBs and collisions. Our own program in the EXEC slot,
; for the system bench (sim/tb/tb_system.py, image "sticmob", BUSRQ on).
; It runs instead of the EXEC, from the reset vector $1000; INTRM vectors
; to $1004. Assembled with ROMW 10 (16-bit constants come in two decles;
; tables of MOB register words are BIDECLEs read with SDBD; direct
; addresses stay below $400).
;
; A list of scenes, one a frame. In VBlank of frame f the ISR
;   1. reads the eight collision registers $18-$1F (the bits frame f - 1
;      gathered) and compares bits 0-9 with the scene's expected words:
;      every difference adds 1 to the fail count ($0303; $0305 = the frame
;      of the last one) and sets the scene's bit in the failed-scene mask
;      ($030A: S0-S15 in bits 0-15, $030B: S16 on in bits 0-15);
;   2. clears $18-$1F, unless the scene says "keep" (stickiness);
;   3. sets up the next scene: display enable, Color Stack or
;      Foreground/Background mode, HDR, VDR, CBR and the 24 MOB registers;
;      after the last scene it starts again ($0306 counts the passes);
;   4. sets the border colour: green while the fail count is 0; yellow when
;      only S5, S7 and S10 have failed, the scenes where MAME's rules
;      differ (M4, M5, M1: the STIC behaves as MAME draws it); red when any
;      other scene has failed.
; The expected words follow the hardware rules of docs/STIC_NOTES.md 5
; (modes "stic"/"none" of tools/stic.py, S9 stic.txt): where MAME differs
; (M1, M4, M5) the scene says so. tb_system.py checks that the model's run
; ends with fail count 0 and at least one pass, and that the RTL equals the
; model in every picture, bus phase and collision bit. On the console
; (with a flash cartridge, later) the border colour gives the answer.
;
; Background: BACKTAB blank (GRAM card 0, background CSR0 = black) but
;   row 2 col 5, row 6 cols 0 and 1, row 0 col 15, row 1 col 15, row 8
;   col 19 and row 11 col 10: a solid GRAM card 1 (foreground blue);
;   row 4 col 10: Colored Squares, quadrants 7 / 1 / 2 / 7 (top left, top
;   right, bottom left, bottom right; colour 7 is never "on").
; GRAM cards: 0 blank, 1 solid, 2 row 6 only, 3 left pixel, 5 right pixel,
;   6 row 7 only, 7 left half, 8 right half, 9 a diagonal, 10 and 11 solid
;   (a YRES pair), 12 blank, 13 an L shape, 14 blank and 15 row 7 only (a
;   YRES pair: its last row only).
; Positions (no delays): a MOB at X covers playfield columns X - 8 ..;
;   at Y its top is picture line 2 (Y + 4); X = 8 c + 8, Y = 8 r + 8 is
;   card col c, row r. Collision area: columns 0-158, lines 24-215 (the
;   border extension bits move the left / top edge 8 columns / 16 lines in).
; SPDX-License-Identifier: MIT

        ROMW    10
        ORG     $1000
        B       main            ; $1000: reset vector
        NOP
        NOP

; $1004: interrupt vector. Runs in VBlank (the bus-copy window).
isr:    PSHR    R0
        PSHR    R1
        PSHR    R2
        PSHR    R3
        PSHR    R4
        PSHR    R5
        MVI     $0300, R0       ; frame count
        INCR    R0
        MVO     R0, $0300
; 1. the previous scene's collisions
        MVI     $0304, R4       ; its expected words (0: none yet)
        TSTR    R4
        BEQ     next
        MVII    #$18, R5
        MVII    #8, R2
cmp_l:  MVI@    R5, R0          ; $18 + i
        ANDI    #$3FF, R0
        MVI@    R4, R1
        CMPR    R1, R0
        BEQ     cmp_ok
        MVI     $0303, R3
        INCR    R3
        MVO     R3, $0303
        MVI     $0300, R3
        MVO     R3, $0305
        MVII    #1, R0          ; the scene's bit in the failed-scene mask
        MVII    #$030A, R1
        MVI     $0308, R3       ; the scene compared
        CMPI    #16, R3
        BLT     sb_lo
        SUBI    #16, R3
        INCR    R1
sb_lo:  TSTR    R3
        BEQ     sb_set
sb_sh:  SLL     R0
        DECR    R3
        BNEQ    sb_sh
sb_set: MVI@    R1, R3
        ANDR    R0, R3
        BNEQ    cmp_ok          ; already set
        MVI@    R1, R3
        XORR    R0, R3
        MVO@    R3, R1
cmp_ok: DECR    R2
        BNEQ    cmp_l
; 2. clear them, unless the scene keeps them
        MVI     $0307, R0
        ANDI    #$200, R0
        BNEQ    next
        CLRR    R0
        MVII    #$18, R5
        MVII    #8, R2
clr_l:  MVO@    R0, R5
        DECR    R2
        BNEQ    clr_l
; 3. the next scene
next:   MVI     $0301, R4
        CMPI    #s_end, R4
        BNEQ    scene
        MVII    #s_first, R4
        MVI     $0306, R0
        INCR    R0
        MVO     R0, $0306
        CLRR    R0
        MVO     R0, $0309       ; scene number 0
scene:  MVI@    R4, R0          ; flags: 0 FGBG, 1-3 HDR, 4-6 VDR, 7-8 CBR, 9 keep
        MVO     R0, $0307
        MVO     R0, $0020       ; display enable
        MOVR    R0, R1
        ANDI    #1, R1
        BEQ     mode_cs
        MVO     R1, $0021       ; Foreground/Background
        B       mode_ok
mode_cs:
        MVI     $0021, R1       ; Color Stack
mode_ok:
        MOVR    R0, R1
        SLR     R1
        MVO     R1, $0030       ; HDR (3 bits kept)
        SLR     R1, 2
        SLR     R1
        MVO     R1, $0031       ; VDR
        SLR     R1, 2
        SLR     R1
        MVO     R1, $0032       ; CBR
        CLRR    R5              ; X, Y, A registers $00-$17
        MVII    #24, R2
mob_l:  SDBD
        MVI@    R4, R0
        MVO@    R0, R5
        DECR    R2
        BNEQ    mob_l
        MVO     R4, $0304       ; this scene's expected words, for the next frame
        ADDI    #8, R4
        MVO     R4, $0301
        MVI     $0309, R0       ; and its number
        MVO     R0, $0308
        INCR    R0
        MVO     R0, $0309
; 4. the border colour
        MVII    #5, R1          ; green
        MVI     $0303, R0
        TSTR    R0
        BEQ     bord
        MVII    #2, R1          ; red: a scene other than S5, S7, S10
        MVI     $030B, R0
        TSTR    R0
        BNEQ    bord
        MVI     $030A, R0
        ANDI    #$FB5F, R0      ; all but S5, S7, S10 ($04A0)
        BNEQ    bord
        MVII    #6, R1          ; yellow: only MAME's M4, M5, M1
bord:   MVO     R1, $002C
        PULR    R5
        PULR    R4
        PULR    R3
        PULR    R2
        PULR    R1
        PULR    R0
        PULR    R7

main:   MVII    #$0310, R6      ; stack
        CLRR    R0
        MVO     R0, $0300
        MVO     R0, $0303
        MVO     R0, $0304
        MVO     R0, $0305
        MVO     R0, $0306
        MVO     R0, $0307
        MVO     R0, $0308
        MVO     R0, $0309
        MVO     R0, $030A
        MVO     R0, $030B
        MVO     R0, $002C       ; border black until the first frame
        MVII    #s_first, R0
        MVO     R0, $0301
        MVII    #1, R1          ; CSR1-3 (CSR0 black, below); no card advances the stack

        MVO     R1, $0029
        MVII    #2, R1
        MVO     R1, $002A
        MVII    #3, R1
        MVO     R1, $002B
        MVII    #$10, R0        ; CSR0: black; bit 4 is not kept (MAME keeps the word and
        MVO     R0, $0028       ; takes its bit 4 as "on" for squares colour 7: M5)
; GRAM cards 0-15
        MVII    #gram_d, R4
        MVII    #$3800, R5
        MVII    #128, R2
gram_l: MVI@    R4, R0
        MVO@    R0, R5
        DECR    R2
        BNEQ    gram_l
; BACKTAB: GRAM card 0 everywhere, then the three special cards
        MVII    #$0800, R0
        MVII    #$0200, R4
        MVII    #240, R2
bt_l:   MVO@    R0, R4
        DECR    R2
        BNEQ    bt_l
        MVII    #$0809, R0      ; GRAM card 1, foreground 1
        MVO     R0, $022D       ; row 2 col 5
        MVO     R0, $0278       ; row 6 col 0
        MVO     R0, $0279       ; row 6 col 1
        MVO     R0, $020F       ; row 0 col 15
        MVO     R0, $0223       ; row 1 col 15
        MVO     R0, $02B3       ; row 8 col 19
        MVO     R0, $02E6       ; row 11 col 10
        MVII    #$368F, R0      ; squares 7 / 1 / 2 / 7
        MVO     R0, $025A       ; row 4 col 10
        EIS
loop:   B       loop

gram_d: DECLE   $00, $00, $00, $00, $00, $00, $00, $00      ; 0 blank
        DECLE   $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF      ; 1 solid
        DECLE   $00, $00, $00, $00, $00, $00, $FF, $00      ; 2 row 6
        DECLE   $80, $80, $80, $80, $80, $80, $80, $80      ; 3 left pixel
        DECLE   $00, $00, $00, $00, $00, $00, $00, $00      ; 4
        DECLE   $01, $01, $01, $01, $01, $01, $01, $01      ; 5 right pixel
        DECLE   $00, $00, $00, $00, $00, $00, $00, $FF      ; 6 row 7
        DECLE   $F0, $F0, $F0, $F0, $F0, $F0, $F0, $F0      ; 7 left half
        DECLE   $0F, $0F, $0F, $0F, $0F, $0F, $0F, $0F      ; 8 right half
        DECLE   $C0, $60, $30, $18, $0C, $06, $03, $81      ; 9 diagonal
        DECLE   $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF      ; 10 solid (YRES pair)
        DECLE   $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF      ; 11 solid
        DECLE   $00, $00, $00, $00, $00, $00, $00, $00      ; 12 blank (M1: MAME's lower half of 11)
        DECLE   $FF, $80, $80, $80, $00, $00, $00, $00      ; 13 L shape
        DECLE   $00, $00, $00, $00, $00, $00, $00, $00      ; 14 blank (YRES pair 14, 15)
        DECLE   $00, $00, $00, $00, $00, $00, $00, $FF      ; 15 row 7

; Register bits. X: INTR $100, VISB $200, XSIZE $400. Y: YRES $80, YSIZ2
; $100, YSIZ4 $200, XFLIP $400, YFLIP $800. A: colour 0-2 + $1000, card
; << 3, GRAM $800, PRIO $2000. Expected: MOBs 0-7 bits 0-7, background
; $100, border $200.
IV      EQU     $300            ; INTR + VISB
G1      EQU     $808            ; GRAM card 1 (solid)
G2      EQU     $810
G3      EQU     $818
G5      EQU     $828
G6      EQU     $830
G7      EQU     $838
G8      EQU     $840
G9      EQU     $848
G10     EQU     $850
G11     EQU     $858
G13     EQU     $868
G14     EQU     $870

; Each scene: flags, X0-X7, Y0-Y7, A0-A7, expected C0-C7.
s_first:
; S0: nothing
        DECLE   0
        BIDECLE 0, 0, 0, 0, 0, 0, 0, 0
        BIDECLE 0, 0, 0, 0, 0, 0, 0, 0
        BIDECLE 0, 0, 0, 0, 0, 0, 0, 0
        DECLE   0, 0, 0, 0, 0, 0, 0, 0
; S1: two MOBs on the solid card, overlapping; MOB 0 has PRIO, so where
; both are over the card's "on" pixels the card shows (MOB 0 decides
; first, M3; MAME would show MOB 1 there)
        DECLE   0
        BIDECLE 48 + IV, 52 + IV, 0, 0, 0, 0, 0, 0
        BIDECLE 24, 24, 0, 0, 0, 0, 0, 0
        BIDECLE $2000 + G1 + 2, $1000 + G1 + 3, 0, 0, 0, 0, 0, 0
        DECLE   $102, $101, 0, 0, 0, 0, 0, 0
; S2: X = 0 is no MOB, whatever its other bits
        DECLE   0
        BIDECLE 0 + IV, 48 + IV, 0, 0, 0, 0, 0, 0
        BIDECLE 24, 24, 0, 0, 0, 0, 0, 0
        BIDECLE G1 + 2, G1 + 3, 0, 0, 0, 0, 0, 0
        DECLE   0, $100, 0, 0, 0, 0, 0, 0
; S3: an invisible MOB still interacts (M9); a MOB without INTR sets
; nothing, for itself or for a MOB over it, on the solid card at row 6
; col 0 or over the left border
        DECLE   0
        BIDECLE 48 + $100, 0, 100 + $200, 104 + IV, 8 + $200, 2 + $200, 0, 0
        BIDECLE 24, 0, 60, 60, 56, 40, 0, 0
        BIDECLE G1 + 2, 0, G1 + 4, G1 + 5, G1 + 6, G1 + 7, 0, 0
        DECLE   $100, 0, 0, 0, 0, 0, 0, 0
; S4: the border, just inside / just outside each edge: left (column -1),
; right (column 159, the 160th, counts as border; M8), top (line 23 / 24),
; bottom (line 215 / 216)
        DECLE   0
        BIDECLE 8 + IV, 7 + IV, 159 + IV, 160 + IV, 60 + IV, 80 + IV, 100 + IV, 120 + IV
        BIDECLE 40, 40, 40, 40, 4, 5, 100, 101
        BIDECLE G3 + 7, G3 + 7, G5 + 7, G5 + 7, G6 + 7, G2 + 7, G6 + 7, G2 + 7
        DECLE   0, $200, 0, $200, $200, 0, 0, $200
; S5: delays HDR 5, VDR 3: the collision area does not move (M8); the
; strip the delay uncovers has no "on" pixels (M4: MOB 4 over the strip
; beside the solid card at row 6 col 0 sets nothing; MOB 5 on the card does.
; MAME's bitmap keeps S4's card pixels there, so MAME sets MOB 4's bit)
        DECLE   (5 << 1) + (3 << 4)
        BIDECLE 2 + IV, 3 + IV, 60 + IV, 80 + IV, 4 + IV, 13 + IV, 0, 0
        BIDECLE 40, 40, 1, 2, 56, 56, 0, 0
        BIDECLE G3 + 7, G3 + 7, G6 + 7, G2 + 7, G3 + 6, G3 + 6, 0, 0
        DECLE   $200, 0, $200, 0, 0, $100, 0, 0
; S6: border extension (CBR 3): the left edge at column 8, the top at line 40
        DECLE   $180
        BIDECLE 16 + IV, 15 + IV, 60 + IV, 80 + IV, 0, 0, 0, 0
        BIDECLE 40, 40, 12, 13, 0, 0, 0, 0
        BIDECLE G3 + 7, G3 + 7, G6 + 7, G2 + 7, 0, 0, 0, 0
        DECLE   0, $200, $200, 0, 0, 0, 0, 0
; S7: Colored Squares: quadrants of colour 1 and 2 are "on", colour 7 is not
; (M5; with CSR0's bit 4 set MAME counts colour 7 as "on")
        DECLE   0
        BIDECLE 88 + IV, 88 + IV, 88 + IV, 88 + IV, 0, 0, 0, 0
        BIDECLE 40, 40, 44, 44, 0, 0, 0, 0
        BIDECLE G7 + 1, G8 + 2, G7 + 3, G8 + 4, 0, 0, 0, 0
        DECLE   0, $100, $100, 0, 0, 0, 0, 0
; S8: off the raster (VDR 7): MOBs below the picture (lines 276-403) and
; right of the line still collide with each other and with the border (M7)
        DECLE   7 << 4
        BIDECLE 50 + IV, 55 + IV, 250 + IV, 252 + IV, 100 + IV, 108 + IV, 30 + IV, 37 + IV
        BIDECLE 120, 120, 40, 40, 60, 60, 127 + $380, 127 + $380
        BIDECLE G1 + 2, G1 + 3, G1 + 4, G1 + 5, G1 + 6, G1 + 7, G10 + 6, G10 + 7
        DECLE   $202, $201, $208, $204, 0, 0, $280, $240
; S9: XSIZE (16 pixels: MOBs 4 and 5 touch in one column), YSIZ2 (16 lines)
        DECLE   0
        BIDECLE 0, 0, 0, 0, 100 + IV + $400, 115 + IV, 30 + IV, 30 + IV
        BIDECLE 0, 0, 0, 0, 60, 60, 80 + $100, 87
        BIDECLE 0, 0, 0, 0, G1 + 6, G1 + 7, G1 + 2, G1 + 3
        DECLE   0, 0, 0, 0, $020, $010, $080, $040
; S10: YSIZ4 (32 lines), YRES (16 lines), YRES with an odd card: S9 reads
; cards 10 and 11 (M1; MAME reads 11 and the blank 12, no collision)
        DECLE   0
        BIDECLE 30 + IV, 30 + IV, 100 + IV, 100 + IV, 150 + IV, 150 + IV, 0, 0
        BIDECLE 60 + $200, 75, 60 + $80, 66, 60 + $80, 66, 0, 0
        BIDECLE G1 + 2, G1 + 3, G10 + 2, G1 + 3, G11 + 4, G1 + 5, 0, 0
        DECLE   $002, $001, $008, $004, $020, $010, 0, 0
; S11: YSIZ2 + YSIZ4 (64 lines), XFLIP (the left pixel moves to the right
; end), YFLIP (row 6 moves to row 1)
        DECLE   0
        BIDECLE 30 + IV, 30 + IV, 100 + IV, 107 + IV, 140 + IV, 140 + IV, 0, 0
        BIDECLE 20 + $300, 51, 60 + $400, 60, 80 + $800, 77, 0, 0
        BIDECLE G1 + 2, G1 + 3, G3 + 2, G3 + 3, G2 + 4, G6 + 5, 0, 0
        DECLE   $002, $001, $008, $004, $020, $010, 0, 0
; S12: XSIZE + XFLIP; and to look at (no INTR): GROM cards 65 and 200 in
; Color Stack mode, a pastel colour, the diagonal and the L with every flip
        DECLE   0
        BIDECLE 100 + IV + $400, 115 + IV, 40 + $200, 60 + $200, 80 + $200 + $400, 120 + $200, 0, 0
        BIDECLE 60 + $400, 60, 90, 90, 90 + $100 + $400 + $800, 90 + $800, 0, 0
        BIDECLE G3 + 6, G3 + 3, (65 << 3) + 3, (200 << 3) + $1000 + 4, G9 + 5, G13 + 6, 0, 0
        DECLE   $002, $001, 0, 0, 0, 0, 0, 0
; S13: Foreground/Background mode: the solid card still "on"; GROM card 70
; shows as card 6 (M2: card bits 6-7 ignored; MAME shows card 70)
        DECLE   1
        BIDECLE 48 + IV, 40 + $200, 60 + $200, 0, 0, 0, 0, 0
        BIDECLE 24, 90, 90, 0, 0, 0, 0, 0
        BIDECLE G1 + 2, (70 << 3) + 3, (6 << 3) + 3, 0, 0, 0, 0, 0
        DECLE   $100, 0, 0, 0, 0, 0, 0, 0
; S14: as S1 without PRIO, and the bits are kept ("keep")
        DECLE   $200
        BIDECLE 48 + IV, 52 + IV, 0, 0, 0, 0, 0, 0
        BIDECLE 24, 24, 0, 0, 0, 0, 0, 0
        BIDECLE G1 + 2, G1 + 3, 0, 0, 0, 0, 0, 0
        DECLE   $102, $101, 0, 0, 0, 0, 0, 0
; S15: INTR cleared, X = 0: nothing new, the kept bits are still there
        DECLE   0
        BIDECLE 48 + $200, 0, 0, 0, 0, 0, 0, 0
        BIDECLE 24, 24, 0, 0, 0, 0, 0, 0
        BIDECLE G1 + 2, G1 + 3, 0, 0, 0, 0, 0, 0
        DECLE   $102, $101, 0, 0, 0, 0, 0, 0
; S16: nothing (S15's bits were cleared)
        DECLE   0
        BIDECLE 0, 0, 0, 0, 0, 0, 0, 0
        BIDECLE 0, 0, 0, 0, 0, 0, 0, 0
        BIDECLE 0, 0, 0, 0, 0, 0, 0, 0
        DECLE   0, 0, 0, 0, 0, 0, 0, 0
; S17: eight MOBs in a staircase (X + 1, Y + 1 each): MOBs i and j overlap
; when |i - j| <= 3; the lowest number shows on top; MOB 3 has PRIO, MOB 5
; a pastel colour
        DECLE   0
        BIDECLE 130 + IV, 131 + IV, 132 + IV, 133 + IV, 134 + IV, 135 + IV, 136 + IV, 137 + IV
        BIDECLE 90, 91, 92, 93, 94, 95, 96, 97
        BIDECLE G1 + 0, G1 + 1, G1 + 2, $2000 + G1 + 3, G1 + 4, $1000 + G1 + 5, G1 + 6, G1 + 7
        DECLE   $00E, $01D, $03B, $077, $0EE, $0DC, $0B8, $070
; S18: the edges of the background-collision area (no delays): the bottom
; line 215 is in it, 216 is not (MOBs 0, 1 on the solid card at row 11 col
; 10); column 158 is in it, the 160th column 159 is not (MOBs 2, 3 on the
; solid card at row 8 col 19). Outside the area an "on" card pixel is only
; a border collision.
        DECLE   0
        BIDECLE 88 + IV, 88 + IV, 159 + IV, 160 + IV, 0, 0, 0, 0
        BIDECLE 100, 101, 72, 76, 0, 0, 0, 0
        BIDECLE G6 + 1, G2 + 2, G5 + 3, G5 + 4, 0, 0, 0, 0
        DECLE   $100, $200, $100, $200, 0, 0, 0, 0
; S19: border extension (CBR 3) over "on" card pixels: column 7 (MOB 0, the
; solid card at row 6 col 0, hidden under the extended left border) is a
; border collision only, column 8 (MOB 1, row 6 col 1) a background one;
; line 39 (MOB 2, row 0 col 15, hidden under the extended top border) a
; border collision only, line 40 (MOB 3, row 1 col 15) a background one
        DECLE   $180
        BIDECLE 8 + IV, 16 + IV, 128 + IV, 128 + IV, 0, 0, 0, 0
        BIDECLE 56, 56, 12, 13, 0, 0, 0, 0
        BIDECLE G5 + 1, G3 + 2, G6 + 3, G2 + 4, 0, 0, 0, 0
        DECLE   $200, $100, $200, $100, 0, 0, 0, 0
; S20: YRES with YFLIP reverses all 16 rows, so the two cards swap halves:
; MOB 0 (cards 6 and 7) has its full row (card 6 row 7) on its line 8,
; where MOB 1's only line (card 2 row 6) meets it right of its left half
; (flipping each card in place would leave card 7's left half there: no
; collision). MOBs 2 and 3 have INTR without VISB and collide. MOBs 4 and
; 5 (Y = 0, VDR = 0: from the sweep's first line, 8) overlap only on that
; line (the L's top row), and touch the border
        DECLE   0
        BIDECLE 60 + IV, 64 + IV, 100 + $100, 104 + $100, 40 + IV, 44 + IV, 0, 0
        BIDECLE 20 + $880, 21, 60, 60, 0, 0, 0, 0
        BIDECLE G6 + 1, G2 + 2, G1 + 3, G1 + 4, G13 + 5, G13 + 6, 0, 0
        DECLE   $002, $001, $008, $004, $220, $210, 0, 0
; S21: VDR 7: the bottom line 215 with the cards moved down (MOBs 0, 1 on
; row 11 col 10, now lines 214-229: only 215 counts as background); MOBs 6
; and 7 (Y = 127, YRES + YSIZ4 + YSIZ2: picture lines 276-403, the sweep's
; last) overlap only in their last row, lines 396-403 (MOB 7: cards 14 and
; 15, the last row only)
        DECLE   7 << 4
        BIDECLE 88 + IV, 88 + IV, 0, 0, 0, 0, 50 + IV, 54 + IV
        BIDECLE 93, 94, 0, 0, 0, 0, 127 + $380, 127 + $380
        BIDECLE G6 + 1, G2 + 2, 0, 0, 0, 0, G10 + 6, G14 + 7
        DECLE   $100, $200, 0, 0, 0, 0, $280, $240
s_end:
