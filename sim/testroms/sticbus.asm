; Step-4 STIC test: our own program in the EXEC slot, for the system bench
; (sim/tb/tb_system.py, image "sticbus", BUSRQ on). It runs instead of the
; EXEC, from the reset vector $1000; INTRM vectors to $1004. Assembled with
; ROMW 10 (16-bit constants come in two decles; direct addresses stay
; below $400, the rest through pointers). Not a picture to look at: it
; drives the STIC through what the games of the frame gate may not reach
; (docs/STIC_NOTES.md), and the bench compares every picture, row fetch and
; card row with the model (tools/stic.py, mode "stic"):
;   - BACKTAB and GRAM filled with pseudo-random words and bytes, so every
;     card kind shows: GROM and GRAM cards, colour-stack advance, Colored
;     Squares with all quadrant colours (also quadrants 1 and 2 apart),
;     Foreground/Background backgrounds;
;   - per frame f (the ISR, in VBlank): border colour f, HDR f, VDR f / 2,
;     CBR f / 8 (both border extensions), CSR0-3 from f, Color Stack mode
;     except when f & 6 = 6 (Foreground/Background), and one BACKTAB word
;     changed; the display enabled except when f & 3 = 3 (blank) and when
;     f & 7 = 5, where the main loop enables it after the VBlank window
;     (that frame stays blank: STIC_NOTES D8) and changes the border colour
;     late (it shows from the next frame on);
;   - when f = 12 the main loop disables interrupts for about 25,000
;     cycles and writes $20 every ~215 of them: the next frame is enabled
;     but has no INTAK, so the FIFO's address counter runs on past System
;     RAM ($3FFF words, the counter stopped at 360);
;   - the main loop runs blocks of 12 shifts (72 non-interruptible
;     cycles) between delays that change every pass: a row request that
;     comes early in a block is acknowledged after its fetch cycle, so that
;     row is missed and the row buffer shows the row before (STIC_NOTES
;     T10).
; SPDX-License-Identifier: MIT

        ROMW    10
        ORG     $1000
        B       main            ; $1000: reset vector
        NOP
        NOP

; $1004: interrupt vector. Runs in VBlank (the bus-copy window).
isr:    PSHR    R0
        PSHR    R1
        PSHR    R4
        MVI     $0300, R0       ; frame count f
        INCR    R0
        MVO     R0, $0300
        CLRR    R1
        MVO     R1, $0301       ; no late write by default
        MOVR    R0, R1
        ANDI    #3, R1
        CMPI    #3, R1
        BEQ     isr_blank       ; f & 3 = 3: blank (border changed late)
        MOVR    R0, R1
        ANDI    #7, R1
        CMPI    #5, R1
        BEQ     isr_late        ; f & 7 = 5: enabled late
        MVO     R0, $0020       ; display enable: handshake for this frame
        B       isr_regs
isr_blank:
        MVII    #1, R1
        MVO     R1, $0301
        B       isr_regs
isr_late:
        MVII    #2, R1
        MVO     R1, $0301
isr_regs:
        MVO     R0, $002C       ; border colour
        MVO     R0, $0030       ; HDR (3 bits kept)
        MOVR    R0, R1
        SLR     R1
        MVO     R1, $0031       ; VDR
        SLR     R1, 2
        MVO     R1, $0032       ; CBR
        MOVR    R0, R1
        MVO     R1, $0028       ; CSR0-3
        ADDI    #3, R1
        MVO     R1, $0029
        ADDI    #5, R1
        MVO     R1, $002A
        ADDI    #7, R1
        MVO     R1, $002B
        MOVR    R0, R1
        ANDI    #6, R1
        CMPI    #6, R1
        BEQ     isr_fgbg
        MVI     $0021, R1       ; Color Stack
        B       isr_bt
isr_fgbg:
        MVO     R1, $0021       ; Foreground/Background
isr_bt: MOVR    R0, R4          ; one BACKTAB word changed
        ANDI    #127, R4
        ADDI    #$0200, R4
        MVI@    R4, R1
        ADDI    #$0123, R1
        MVO@    R1, R4
        PULR    R4
        PULR    R1
        PULR    R0
        PULR    R7

main:   MVII    #$0310, R6      ; stack
        CLRR    R0
        MVO     R0, $0300
        MVO     R0, $0301
; BACKTAB: 240 words, R0 += $2E5B
        MVII    #$0200, R4
        MVII    #240, R2
        MVII    #$1357, R0
bt_l:   MVO@    R0, R4
        ADDI    #$2E5B, R0
        DECR    R2
        BNEQ    bt_l
; GRAM: 512 bytes, R0 += $5D, rotated
        MVII    #$3800, R4
        MVII    #512, R2
        MVII    #$0091, R0
gr_l:   MVO@    R0, R4
        ADDI    #$5D, R0
        SWAP    R0
        DECR    R2
        BNEQ    gr_l
        EIS

; the main loop: a delay that changes every pass, then 12 shifts
        CLRR    R3
loop:   MVI     $0301, R0
        TSTR    R0
        BEQ     no_late
        CLRR    R1              ; the late write: once, after the VBlank window
        MVO     R1, $0301
        MVII    #300, R2        ; about 4,000 cycles from the frame start
late_d: DECR    R2
        BNEQ    late_d
        CMPI    #2, R0
        BNEQ    late_b
        MVO     R0, $0020       ; display enable after the window
late_b: MVI     $0300, R1
        ADDI    #9, R1
        MVO     R1, $002C       ; border colour after the window
no_late:
        MVI     $0300, R0
        CMPI    #12, R0
        BNEQ    no_dis
        MVI     $0302, R1       ; frame 12, once: interrupts off past frame 13's VBlank
        TSTR    R1
        BNEQ    no_dis
        MVO     R0, $0302
        DIS                     ; about 25,000 cycles, writing $20 every ~215:
        MVII    #120, R2        ; some write lands in the next frame's VBlank
dis_l:  MVO     R0, $0020       ; and enables it, without its INTAK
        MVII    #12, R1
dis_d:  DECR    R1
        BNEQ    dis_d
        DECR    R2
        BNEQ    dis_l
        EIS
no_dis: ADDI    #7, R3
        MOVR    R3, R2
        ANDI    #63, R2
        INCR    R2
del:    DECR    R2
        BNEQ    del
        SLL     R0
        SLL     R0
        SLL     R0
        SLL     R0
        SLL     R0
        SLL     R0
        SLL     R0
        SLL     R0
        SLL     R0
        SLL     R0
        SLL     R0
        SLL     R0
        B       loop
