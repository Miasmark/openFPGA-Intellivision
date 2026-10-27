; Step-9 ECS test: our own program in the EXEC slot for the system bench
; (sim/tb/tb_system.py, images "ecstest" and "ecssynth"), run with the ECS
; attached (no cartridge: the Auto rule turns it on) and the ECS ROM slot
; loaded. Assembled with ROMW 10 (tools/as1610.py). It checks nothing
; itself: the bench compares every bus cycle (so every value read), the
; state words and the PSGs' output with tools/intv_system.py + tools/ecs.py,
; and checks the keyboard scans the ISR stores against the matrix rule
; written out by hand (tb_system.py ECSKBD_WANT).
;   main, once: the ECS RAM (every 64th cell written with $12xx, read back:
;   the upper byte reads 0; the first and last cells), the UART stub
;   ($00E0-$00E3 read, written), the ECS ROM pages ($7000 on page 0, out on
;   $7A5F and $7A51, back on $7A50; $2000 and $E000 on page 1, out on page
;   2; the cartridge's $FA51), PSG #2's registers (every one written with
;   its unused bits set and read back), then a tone on each channel: A on
;   the envelope (volume bit 4), B with bit 5 alone (fixed on the 8917, the
;   envelope >> 1 on an 8914), C fixed; noise on A; envelope triangle; and
;   PSG #1's three channels at full volume (the sum saturates).
;   ISR, frames 1-9: at $0200 + 32 k (k = the frame): the 8 rows scanned
;   (port A out with one line low, port B read: 8 words), the 8 columns
;   scanned (port B out, port A read: 8 words), both ports out ($EF / $F7
;   and $EF / $FF: A, B read), both in (A, B read).
; SPDX-License-Identifier: MIT

        ROMW    10
        ORG     $1000
        B       main            ; $1000: reset vector
        NOP
        NOP

; $1004: interrupt vector
isr:    PSHR    R0
        PSHR    R1
        PSHR    R2
        PSHR    R3
        PSHR    R4
        MVI     $0100, R0       ; frame count (scratchpad)
        INCR    R0
        MVO     R0, $0100
        CMPI    #10, R0
        BGE     i_done
        MOVR    R0, R3          ; R4 = $0200 + 32 k
        SLL     R3, 2
        SLL     R3, 2
        SLL     R3, 1
        ADDI    #$0200, R3
        MOVR    R3, R4
        MVII    #$78, R1        ; port A out, B in (tones on, noise off: $38)
        MVO     R1, $00F8
        MVII    #$FE, R2        ; row 0 low first
        MVII    #8, R3
i_rows: MVO     R2, $00FE
        MVI     $00FF, R1
        MVO@    R1, R4
        SLL     R2, 1
        INCR    R2
        ANDI    #$FF, R2
        DECR    R3
        BNEQ    i_rows
        MVII    #$B8, R1        ; port B out, A in
        MVO     R1, $00F8
        MVII    #$FE, R2
        MVII    #8, R3
i_cols: MVO     R2, $00FF
        MVI     $00FE, R1
        MVO@    R1, R4
        SLL     R2, 1
        INCR    R2
        ANDI    #$FF, R2
        DECR    R3
        BNEQ    i_cols
        MVII    #$F8, R1        ; both out
        MVO     R1, $00F8
        MVII    #$EF, R1
        MVO     R1, $00FE
        MVII    #$F7, R1
        MVO     R1, $00FF
        MVI     $00FE, R1
        MVO@    R1, R4
        MVI     $00FF, R1
        MVO@    R1, R4
        MVII    #$FF, R1
        MVO     R1, $00FF
        MVI     $00FE, R1
        MVO@    R1, R4
        MVI     $00FF, R1
        MVO@    R1, R4
        MVII    #$38, R1        ; both in
        MVO     R1, $00F8
        MVI     $00FE, R1
        MVO@    R1, R4
        MVI     $00FF, R1
        MVO@    R1, R4
i_done: PULR    R4
        PULR    R3
        PULR    R2
        PULR    R1
        PULR    R0
        PULR    R7

main:   MVII    #$0340, R6      ; stack: the top of System RAM
        CLRR    R0
        MVO     R0, $0100
        ; ---- ECS RAM: every 64th cell, $12xx written, read back
        MVII    #$4000, R4
        MVII    #$1200, R1
m_ram:  MVO@    R1, R4          ; R4 += 1
        ADDI    #63, R4
        INCR    R1
        CMPI    #$4800, R4
        BLT     m_ram
        MVII    #$4000, R4
m_rrd:  MVI@    R4, R1
        ADDI    #63, R4
        CMPI    #$4800, R4
        BLT     m_rrd
        MVII    #$47FF, R3      ; (ROMW 10: an address over $3FF goes through a pointer)
        MVI@    R3, R1
        MVII    #$A5C3, R1
        MVO@    R1, R3
        MVI@    R3, R1
        ; ---- the UART stub
        MVI     $00E0, R1
        MVI     $00E1, R1
        MVI     $00E2, R1
        MVI     $00E3, R1
        MVII    #$0003, R1
        MVO     R1, $00E0
        MVII    #$00AA, R1
        MVO     R1, $00E1
        MVO     R1, $00E2
        MVI     $00E0, R1
        ; ---- the ECS ROM pages: R2 the select address, R3 the read address
        MVII    #$7000, R3
        MVII    #$7FFF, R2
        MVI@    R3, R1          ; page 0 at reset (ON)
        MVII    #$7A5F, R1
        MVO@    R1, R2
        MVI@    R3, R1          ; out
        MVII    #$7A51, R1
        MVO@    R1, R2
        MVI@    R3, R1          ; out
        MVII    #$7A50, R1
        MVO@    R1, R2
        MVI@    R3, R1          ; back
        MVII    #$7A20, R1      ; not a select ($7A2x)
        MVO@    R1, R2
        MVI@    R3, R1
        MVII    #$2000, R3
        MVII    #$2FFF, R2
        MVI@    R3, R1          ; out at reset
        MVII    #$2A51, R1
        MVO@    R1, R2
        MVI@    R3, R1          ; in
        MVI@    R2, R1
        MVII    #$2A52, R1
        MVO@    R1, R2
        MVI@    R3, R1          ; out
        MVII    #$E000, R3
        MVII    #$EFFF, R2
        MVII    #$EA51, R1
        MVO@    R1, R2
        MVI@    R3, R1          ; in
        MVI@    R2, R1
        MVII    #$EA50, R1
        MVO@    R1, R2
        MVI@    R3, R1          ; out
        MVII    #$F000, R3
        MVII    #$FFFF, R2
        MVII    #$FA51, R1      ; the cartridge's page (none here)
        MVO@    R1, R2
        MVI@    R3, R1
        ; ---- PSG #2: every register with its unused bits set, read back
        MVII    #$00F0, R4
        MVII    #$FFFF, R1
        MVII    #14, R3
m_psg:  MVO@    R1, R4
        DECR    R3
        BNEQ    m_psg
        MVII    #$00F0, R4
        MVII    #14, R3
m_prd:  MVI@    R4, R1
        DECR    R3
        BNEQ    m_prd
        MVII    #psgtab, R5
        MVII    #$00F0, R4
        MVII    #14, R3
m_pset: MVI@    R5, R1
        MVO@    R1, R4
        DECR    R3
        BNEQ    m_pset
        ; ---- PSG #1 too, all three channels at full volume, so the mix of both
        ;      goes over 32,767 and saturates (intv_machine)
        MVII    #$40, R1
        MVO     R1, $01F0
        MVII    #$55, R1
        MVO     R1, $01F1
        MVII    #$66, R1
        MVO     R1, $01F2
        MVII    #$0F, R1
        MVO     R1, $01FB
        MVO     R1, $01FC
        MVO     R1, $01FD
        MVII    #$38, R1
        MVO     R1, $01F8
        EIS
m_loop: MVI     $00F9, R1       ; PSG #2 reads in the loop
        MVI     $00FD, R1
        INCR    R0
        B       m_loop

; PSG #2 registers $F0-$FD: periods A $07B, B $0C5, C $133; envelope $0030;
; enable $30 (tones on, noise on A until the ISR's first $38); noise 7; shape $0E (triangle);
; volumes A $10 (envelope), B $2C (bit 5 alone), C $09 (fixed)
psgtab: DECLE   $7B, $C5, $33, $30, $00, $00, $01, $00
        DECLE   $30, $07, $0E, $10, $2C, $09
