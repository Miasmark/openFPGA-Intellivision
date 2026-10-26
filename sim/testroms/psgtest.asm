; Step-6 PSG test: our own program in the EXEC slot for the system bench
; (sim/tb/tb_system.py, image "psgtest"). It runs instead of the EXEC, from
; the reset vector $1000; INTRM vectors to $1004. Assembled with ROMW 10.
; It checks nothing itself: the bench compares the PSG's every step (the
; three channels' levels), its 48 kHz samples and its state words with
; tools/psg.py, and every bus cycle with the system model, so this program
; only has to make the PSG do everything once (tools/psg.py, intv_psg.sv):
;   - the ISR writes one frame's group of registers from a table (below),
;     then reads both hand controllers and the shape register back:
;     tones at periods 0, 1, $00D, $FFF and 5 (a smaller period written
;     while the count is far past it), unused bits set in every register
;     that has them, noise at periods 0, 31 and 5 on one or two channels,
;     tone and noise both off (the volume as a constant level), every one
;     of the 16 envelope shapes, envelope periods 0, 1, 2, $40 and $110,
;     the shape rewritten with the same value, all four volume selects
;     (fixed, envelope >> 2, >> 1, envelope), the port-direction bits 6-7
;     of the enable register set;
;   - from frame 11 a slow triangle (period $40: a step every 512 CPU
;     cycles, a cycle of 32 steps in about 1.1 frames) runs on channels
;     A-C for two frames, for the bench's round trips mid-envelope;
;   - the main loop writes channel C's period (fine every pass, coarse
;     every 8th) and the noise period (every 16th) after a delay that
;     changes every pass, so writes land in every phase of the PSG's
;     4-cycle step, and reads the period back.
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
        PSHR    R4
        MVI     $0200, R0       ; frame count
        INCR    R0
        MVO     R0, $0200
        MVI     $0201, R4       ; table pointer
i_loop: MVI@    R4, R1          ; register n, or an end mark
        CMPI    #$3FF, R1       ; end of this frame's group
        BEQ     i_done
        CMPI    #$3FE, R1       ; end of the table: stay on the mark
        BEQ     i_end
        MVI@    R4, R2          ; value
        ADDI    #$01F0, R1
        MVO@    R2, R1
        B       i_loop
i_end:  DECR    R4
i_done: MVO     R4, $0201
        MVI     $01FE, R0       ; right hand controller
        MVO     R0, $0202
        MVI     $01FF, R0       ; left hand controller
        MVO     R0, $0203
        MVI     $01FA, R0       ; envelope shape, read back (4 bits)
        MVO     R0, $0204
        PULR    R4
        PULR    R2
        PULR    R1
        PULR    R0
        PULR    R7

main:   MVII    #$0300, R6      ; stack
        MVII    #table, R0
        MVO     R0, $0201
        CLRR    R0
        MVO     R0, $0200
        CLRR    R3              ; delay
        CLRR    R5              ; value
        EIS
m_loop: INCR    R3
        ANDI    #15, R3
        MOVR    R3, R2
        INCR    R2
m_dly:  DECR    R2
        BNEQ    m_dly
        INCR    R5
        MVO     R5, $01F2       ; channel C period, low 8
        MOVR    R5, R0
        ANDI    #7, R0
        BNEQ    m_skip
        MOVR    R5, R0
        SLR     R0, 2
        SLR     R0, 1
        MVO     R0, $01F6       ; channel C period, high 4 (masked)
        MVI     $01F2, R1
        MVO     R1, $0205
        MOVR    R5, R0
        ANDI    #15, R0
        BNEQ    m_skip
        MOVR    R5, R0
        SLR     R0, 2
        MVO     R0, $01F9       ; noise period (masked to 5 bits)
m_skip: B       m_loop

; One group per interrupt: register n (0-13 = $01F0 + n), value; $3FF ends
; the group, $3FE the table. Registers: 0-2 tone A-C period low, 3
; envelope period low, 4-6 tone A-C period high, 7 envelope period high,
; 8 enable, 9 noise period, 10 envelope shape, 11-13 volume A-C.
table:
        DECLE   8, $3E, 0, $0D, 4, $F0, 11, $0F, 13, $00, $3FF          ; 1 tone A, period $00D
        DECLE   0, $01, 11, $09, 1, $FF, 5, $0F, 12, $0C, 8, $3C, $3FF  ; 2 A period 1, B $FFF
        DECLE   9, $00, 8, $2C, $3FF                                    ; 3 noise period 0 on B
        DECLE   9, $FF, 8, $24, 13, $C7, $3FF                           ; 4 noise 31 on A, B; C constant 7
        DECLE   3, $02, 7, $00, 10, $00, 11, $30, 8, $3C, $3FF          ; 5 envelope \___ period 2
        DECLE   10, $04, 12, $10, 11, $20, 13, $30, $3FF                ; 6 /___, selects 01 10 11
        DECLE   3, $00, 10, $08, $3FF                                   ; 7 period 0, \\\\
        DECLE   3, $01, 10, $0A, $3FF                                   ; 8 period 1, \/\/
        DECLE   10, $0B, $3FF                                           ; 9 \"""
        DECLE   10, $0C, 10, $0D, $3FF                                  ; 10 //// then /"""
        DECLE   3, $40, 7, $00, 10, $0E, 8, $38, $3FF                   ; 11 slow /\/\, all tones
        DECLE   $3FF                                                    ; 12 (it runs on)
        DECLE   10, $0F, 10, $09, 10, $09, $3FF                         ; 13 /___, \___ twice
        DECLE   0, $FF, 4, $0F, 11, $0F, $3FF                           ; 14 A period $FFF
        DECLE   0, $05, 4, $F0, $3FF                                    ; 15 A period 5: count past it
        DECLE   3, $10, 7, $01, 10, $0E, 9, $05, 8, $30, $3FF           ; 16 envelope $110, noise 5
        DECLE   8, $F8, 12, $3F, 13, $FF, $3FF                          ; 17 port bits; B, C envelope
        DECLE   11, $1F, 10, $0A, $3FF                                  ; 18 A envelope >> 2
        DECLE   $3FE
