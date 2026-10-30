; Step-10 mix test: our own program in the EXEC slot for the system bench
; (sim/tb/tb_system.py, image "voicemix", the ECS and the Intellivoice on). It
; runs instead of the EXEC, from the reset vector $1000; interrupts stay off.
; Assembled with ROMW 10. It checks nothing itself: the bench compares the
; machine's mixed sound (the E lines' mix hash with the voice on top) with the
; model, so this program only has to drive the sum past 32,767:
;   - PSG #1 ($01F0) and the ECS's PSG #2 ($00F0) each play three square tones
;     at full fixed volume (enable $38: tones A-C on, noise off; volume $0F);
;     with the ECS on their sum, scaled to 3/4, already passes 32,767 at the
;     peaks, and the voice (Loudest) on top of it reaches the final clip
;     (intv_machine: vsum saturated to 16 bits);
;   - the Intellivoice is reset, then speaks the resident phrases 6-42 in
;     turn (1-5 are the resident pauses), each when LRQ says the last one was
;     taken, forever.
; SPDX-License-Identifier: MIT

        ROMW    10
        ORG     $1000
        B       main            ; $1000: reset vector
        NOP
        NOP
isr:    B       isr             ; $1004: interrupts stay off

main:   MVII    #$01F0, R4      ; PSG #1, then PSG #2 at $00F0
        CALL    psg
        MVII    #$00F0, R4
        CALL    psg

        MVII    #$200, R0
        ADDR    R0, R0          ; $400: bit 10
        MVO     R0, $0081       ; reset the FIFO and the SP0256
        MVII    #6, R1          ; resident phrases 6-42 (1-5: pauses), forever
say:    MVI     $0080, R0       ; bit 15: LRQ
        TSTR    R0
        BPL     say
        MVO     R1, $0080
        INCR    R1
        CMPI    #43, R1
        BNEQ    say
        MVII    #6, R1
        B       say

; psg: R4 = the PSG's register 0; three tones (periods $080, $0B4, $0F0) at full
; fixed volume. R5 holds the return address (CALL)
psg:    MVII    #ptab, R3
        MVII    #14, R2         ; registers 0-13
p1:     MVI@    R3, R0
        MVO@    R0, R4
        INCR    R3
        DECR    R2
        BNEQ    p1
        JR      R5

; registers 0-13: tone A-C period low, envelope low, tone A-C period high,
; envelope high, enable, noise period, envelope shape, volume A-C
ptab:   DECLE   $80, $B4, $F0, $00, $00, $00, $00, $00
        DECLE   $38, $00, $00, $0F, $0F, $0F
