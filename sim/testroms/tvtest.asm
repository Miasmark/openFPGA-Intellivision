; 1.0.8 TutorVision / INTV88 test: our own program in the EXEC slot, for the system bench
; (sim/tb/tb_system.py, images tvtest_off, tvtest_88, tvtest_full; docs/TUTORVISION.md 5).
; It runs instead of the EXEC, from the reset vector $1000; INTRM vectors to $1004. Assembled
; with ROMW 10 (16-bit constants come in two decles; direct addresses stay below $400, the rest
; through pointers). Every access it makes differs between the 2609 and the INTV88 board's
; STIC 1A (J. Zbiciak's notes; tools/intv_system.py), so the same program checks the core in
; all three modes; the bench compares every bus cycle, picture, row fetch and state word with
; the model, and sim/check/tv_check.py checks the model's results against the documents:
;   1. GRAM size: $11, $22, $33, $44 written at $3800, $3A00, $3C00, $3E00 and read back (2609:
;      four windows on one 512-byte GRAM, all $44; INTV88: 2K, each its own)
;   2. the write aliases: GRAM through $7800, then $3800 read (2609 $55, INTV88 $11); the STIC's
;      MOB 0 X through $4000 after $0012 at $0000, then $0000 read (2609 $3834, INTV88 $3812);
;      a read of $4021 (the mode latch on the 2609, nothing on the STIC 1A: the bench logs it)
;   3. System RAM at $0360, $03FF, $0400, $04FF written and read (2609: unmapped, $FFFF)
;   4. $0022 read (2609 $3FFF, STIC 1A $3FF7)
;   5. the PSG: R7 = $FF read (STIC 1A: bits 7:6 read 0), the envelope shape read back; channel A
;      with volume mode 01 (2609: the envelope >> 2; STIC 1A: one envelope step, then silence)
;      and B with mode 10 sound on (the bench compares every step's levels and every sample)
;   6. $2000 and $2FFF read (the WBEXEC's second half in Full mode, else $FFFF)
;   7. the picture: all 2,048 GRAM bytes and BACKTAB filled; Color Stack cards with bits 10:9 set
;      (GRAM cards 64-255 on the STIC 1A), MOB 0 a GRAM card above 63, MOB 1 a GROM card above
;      63 in Foreground/Background frames, MOB 0 across the 160th column; frames 2-5 Color
;      Stack, 6-9 Foreground/Background
;   8. GROM and GRAM read after the VBlank window of a frame with the display on (2609: GROM
;      $FFxx, GRAM $0000; STIC 1A: both $00FF), frames 3 and 7
; Results go to System RAM from $0330 (R5; BACKTAB is $0200-$02EF), so the dumps show them too.
; SPDX-License-Identifier: MIT

        ROMW    10
        ORG     $1000
        B       main            ; $1000: reset vector
        NOP
        NOP

; $1004: interrupt vector. Runs in VBlank: counts frames, enables the display from frame 2,
; Color Stack before frame 6, Foreground/Background from there.
isr:    PSHR    R0
        PSHR    R1
        MVI     $0300, R0       ; frame count f
        INCR    R0
        MVO     R0, $0300
        CMPI    #2, R0
        BLT     isr_out
        MVO     R0, $0020       ; display enable
        MVII    #$0001, R1
        MVO     R1, $002C       ; border: blue
        MVII    #$0005, R1
        MVO     R1, $0028       ; CSR0-3
        MVII    #$0007, R1
        MVO     R1, $0029
        MVII    #$000A, R1
        MVO     R1, $002A
        MVII    #$000C, R1
        MVO     R1, $002B
        CMPI    #6, R0
        BGE     isr_fgbg
        MVI     $0021, R1       ; Color Stack
        B       isr_out
isr_fgbg:
        MVO     R1, $0021       ; Foreground/Background
isr_out:
        MVII    #1, R0
        MVO     R0, $0301       ; a frame started: the main loop's flag
        PULR    R1
        PULR    R0
        PULR    R7

main:   MVII    #$0320, R6      ; stack
        CLRR    R0
        MVO     R0, $0300
        MVO     R0, $0301
        MVII    #$0330, R5      ; results

; 1. GRAM size (the display is off: GRAM is open all frame)
        MVII    #$3800, R4
        MVII    #$11, R0
        MVO@    R0, R4
        MVII    #$3A00, R4
        MVII    #$22, R0
        MVO@    R0, R4
        MVII    #$3C00, R4
        MVII    #$33, R0
        MVO@    R0, R4
        MVII    #$3E00, R4
        MVII    #$44, R0
        MVO@    R0, R4
        MVII    #$3800, R4
        MVI@    R4, R0
        MVO@    R0, R5
        MVII    #$3A00, R4
        MVI@    R4, R0
        MVO@    R0, R5
        MVII    #$3C00, R4
        MVI@    R4, R0
        MVO@    R0, R5
        MVII    #$3E00, R4
        MVI@    R4, R0
        MVO@    R0, R5

; 2. the aliases
        MVII    #$7800, R4
        MVII    #$55, R0
        MVO@    R0, R4
        MVII    #$3800, R4
        MVI@    R4, R0
        MVO@    R0, R5
        MVII    #$0012, R0
        MVO     R0, $0000       ; MOB 0 X
        MVII    #$4000, R4
        MVII    #$0034, R0
        MVO@    R0, R4          ; through the alias
        MVI     $0000, R0
        MVO@    R0, R5
        MVII    #$4021, R4
        MVI@    R4, R0          ; the mode latch's alias read
        MVO@    R0, R5

; 3. System RAM $0360-$04FF
        MVII    #$0360, R4
        MVII    #$1234, R0
        MVO@    R0, R4
        MVII    #$03FF, R4
        MVII    #$5678, R0
        MVO@    R0, R4
        MVII    #$0400, R4
        MVII    #$9ABC, R0
        MVO@    R0, R4
        MVII    #$04FF, R4
        MVII    #$DEF0, R0
        MVO@    R0, R4
        MVII    #$0360, R4
        MVI@    R4, R0
        MVO@    R0, R5
        MVII    #$03FF, R4
        MVI@    R4, R0
        MVO@    R0, R5
        MVII    #$0400, R4
        MVI@    R4, R0
        MVO@    R0, R5
        MVII    #$04FF, R4
        MVI@    R4, R0
        MVO@    R0, R5

; 4. $0022
        MVI     $0022, R0
        MVO@    R0, R5

; 5. the PSG ($01F0 + n: n 8 = R7 enable, 10 = R13 shape, 11-13 = R8-R10 volumes)
        MVII    #$FF, R0
        MVO     R0, $01F8
        MVI     $01F8, R0
        MVO@    R0, R5
        MVII    #$0E, R0
        MVO     R0, $01FA       ; shape: continue, attack, alternate (a triangle)
        MVI     $01FA, R0
        MVO@    R0, R5
        MVII    #$40, R0        ; tone A, B periods
        MVO     R0, $01F0
        MVII    #$61, R0
        MVO     R0, $01F1
        CLRR    R0
        MVO     R0, $01F4
        MVO     R0, $01F5
        MVII    #$08, R0        ; envelope period $0008
        MVO     R0, $01F3
        CLRR    R0
        MVO     R0, $01F7
        MVII    #$3C, R0        ; R7: tone A and B on, noise off, C off
        MVO     R0, $01F8
        MVII    #$10, R0        ; A: volume mode 01
        MVO     R0, $01FB
        MVII    #$20, R0        ; B: volume mode 10
        MVO     R0, $01FC
        MVII    #$0E, R0        ; the shape again: the envelope restarts
        MVO     R0, $01FA

; 6. $2000, $2FFF
        MVII    #$2000, R4
        MVI@    R4, R0
        MVO@    R0, R5
        MVII    #$2FFF, R4
        MVI@    R4, R0
        MVO@    R0, R5

; 7. GRAM: 2,048 bytes ($3800-$3FFF), R0 += $3B, rotated
        MVII    #$3800, R4
        MVII    #2048, R2
        MVII    #$0055, R0
gr_l:   MVO@    R0, R4
        ADDI    #$3B, R0
        SWAP    R0
        DECR    R2
        BNEQ    gr_l
; BACKTAB: 240 words: GRAM cards with bits 10:9 (and so cards 64-255 on the STIC 1A), GROM
; cards, colour-stack advance; in Foreground/Background the same words give other cards
        MVII    #$0200, R4
        MVII    #240, R2
        MVII    #$0A07, R0
bt_l:   MVO@    R0, R4
        ADDI    #$2C5B, R0
        DECR    R2
        BNEQ    bt_l
; MOB 0: a GRAM card above 63 (card 200: bits 10:3 = $C8), across the 160th column; MOB 1: a
; GROM card above 63 (100) in the middle
        MVII    #$0300 + 164, R0        ; X 164: visible, interacts
        MVO     R0, $0000
        MVII    #$0048, R0              ; Y $48
        MVO     R0, $0008
        MVII    #$0800 + ($C8 << 3) + 6, R0     ; GRAM, card 200, colour 6
        MVO     R0, $0010
        MVII    #$0300 + 80, R0
        MVO     R0, $0001
        MVII    #$0030, R0
        MVO     R0, $0009
        MVII    #(100 << 3) + 2, R0     ; GROM card 100, colour 2
        MVO     R0, $0011
        EIS

; 8. the main loop: in frames 3 and 7, GROM and GRAM read after the window
loop:   MVI     $0301, R0
        TSTR    R0
        BEQ     loop
        CLRR    R0
        MVO     R0, $0301
        MVI     $0300, R0
        CMPI    #12, R0
        BGE     done
        CMPI    #3, R0
        BEQ     late
        CMPI    #7, R0
        BNEQ    loop
late:   MVII    #400, R2        ; past the window (about 4,800 cycles from the frame start)
late_d: DECR    R2
        BNEQ    late_d
        MVII    #$3000 + 8, R4
        MVI@    R4, R0
        MVO@    R0, R5
        MVII    #$3800, R4
        MVI@    R4, R0
        MVO@    R0, R5
        B       loop
done:   DIS
        B       done
