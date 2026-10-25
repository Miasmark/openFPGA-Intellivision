; Step-3 system test: our own program in the EXEC slot, for the system bench
; (sim/tb/tb_system.py, image "systest"). It runs instead of the EXEC, from
; the reset vector $1000; INTRM vectors to $1004. Assembled with ROMW 10, as
; the EXEC ROM is 10 bits wide: 16-bit constants and addresses come in two
; decles (SDBD). Not a test of the CPU (sim/tests/cpu does that) but of the
; bus around it (DESIGN.md 2.5, 2.6; tools/intv_system.py):
;   1. reads of 54 addresses: unmapped ones ($FFFF), the 8-bit devices
;      (upper byte 0), EXEC (10 bits), GROM ($FF00 | byte), STIC, GRAM
;   2. every STIC offset $00-$3F but $20 written, all read back (read
;      masks, the $33-$3F gap); writes through the $4000, $8000, $C000
;      aliases; a read of $8021 and a write of $0021 (the mode latch)
;   3. GRAM written through all eight 512-word windows ($3800, $3A00,
;      $3C00, $3E00, $7800, $B800, $F800, $7A00) and read through two
;   4. every PSG register written with $FF and $A5 and read back (masks,
;      hand controllers at $01FE / $01FF)
;   5. scratchpad and System RAM with 16-bit values; then a write of $20
;      (display enable) closes the STIC and GRAM for the rest of frame 0:
;      a STIC and a GRAM write and read there
;   6. interrupts on; the ISR counts frames, enables the display (sets the
;      STIC handshake) on odd frames only, and writes and reads STIC and
;      GRAM in VBlank. The main loop writes and reads STIC registers, GRAM
;      and the PSG all through the frame, with a delay that changes every
;      pass, so accesses land inside and outside VBlank with the handshake
;      set and clear.
; Results go to System RAM ($0210 on; a ring at $02C0-$02EF in the loop),
; so the dumps show them too; the bench compares every bus cycle anyway.
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
        MVI     $0200, R0       ; frame count
        INCR    R0
        MVO     R0, $0200
        MOVR    R0, R1
        ANDI    #1, R1
        BEQ     isr_nohs
        MVO     R0, $0020       ; display enable: handshake for this frame
isr_nohs:
        MVO     R0, $002C       ; border colour
        MVO     R0, $0018       ; MCR0: its own bit is never kept
        MVI     $0018, R1
        MVO     R1, $0201
        MVII    #$7840, R4      ; GRAM $040 through the $7800 window
        MVO@    R0, R4
        MVII    #$3A40, R4
        MVI@    R4, R1
        MVO     R1, $0202
        PULR    R4
        PULR    R1
        PULR    R0
        PULR    R7

main:   MVII    #$0300, R6      ; stack
        MVII    #$0210, R5      ; results

; 1. probes
        MVII    #probes, R4
        MVII    #NPROBE, R2
p_loop: SDBD
        MVI@    R4, R3          ; address (two decles)
        MVI@    R3, R1
        MVO@    R1, R5
        DECR    R2
        BNEQ    p_loop

; 2. STIC: every offset, then the aliases and the mode latch
        CLRR    R4
        MVII    #32, R2         ; $00-$1F
        MVII    #$3A5C, R0
s_w:    MVO@    R0, R4
        ADDI    #$0137, R0
        DECR    R2
        BNEQ    s_w
        INCR    R4              ; not $20: that would close the STIC
        MVII    #31, R2         ; $21-$3F
s_w2:   MVO@    R0, R4
        ADDI    #$0137, R0
        DECR    R2
        BNEQ    s_w2
        CLRR    R4
        MVII    #64, R2
s_r:    MVI@    R4, R1
        MVO@    R1, R5
        DECR    R2
        BNEQ    s_r
        MVII    #$4028, R4
        MVII    #$0005, R0
        MVO@    R0, R4
        MVII    #$8029, R4
        MVII    #$0006, R0
        MVO@    R0, R4
        MVII    #$C031, R4
        MVII    #$FFFB, R0
        MVO@    R0, R4
        MVI     $0028, R1
        MVO@    R1, R5
        MVI     $0029, R1
        MVO@    R1, R5
        MVI     $0031, R1
        MVO@    R1, R5
        MVII    #$8021, R4
        MVI@    R4, R1          ; reaches the mode latch, reads the cartridge
        MVO@    R1, R5
        MVO     R1, $0021

; 3. GRAM through the eight windows: offset k through window k
        MVII    #windows, R4
        MVII    #8, R2
        MVII    #$1234, R0
g_w:    SDBD
        MVI@    R4, R3          ; window base + k
        MVO@    R0, R3
        ADDI    #$0111, R0
        DECR    R2
        BNEQ    g_w
        MVII    #$3800, R4
        MVII    #8, R2
g_r:    MVI@    R4, R1
        MVO@    R1, R5
        DECR    R2
        BNEQ    g_r
        MVII    #$3E00, R4
        MVII    #8, R2
g_r2:   MVI@    R4, R1
        MVO@    R1, R5
        DECR    R2
        BNEQ    g_r2

; 4. PSG: $FF, then $A5, into every register, each read back
        MVII    #$01F0, R4
        MVII    #16, R2
        MVII    #$00FF, R0
q_w:    MVO@    R0, R4
        DECR    R2
        BNEQ    q_w
        MVII    #$01F0, R4
        MVII    #16, R2
q_r:    MVI@    R4, R1
        MVO@    R1, R5
        DECR    R2
        BNEQ    q_r
        MVII    #$01F0, R4
        MVII    #16, R2
        MVII    #$FFA5, R0
q_w2:   MVO@    R0, R4
        DECR    R2
        BNEQ    q_w2
        MVII    #$01F0, R4
        MVII    #16, R2
q_r2:   MVI@    R4, R1
        MVO@    R1, R5
        DECR    R2
        BNEQ    q_r2

; 5. scratchpad and System RAM, 16-bit values
        MVII    #$0100, R4
        MVII    #$A55A, R0
        MVO@    R0, R4
        MVII    #$01EF, R4
        MVO@    R0, R4
        MVI     $0100, R1
        MVO@    R1, R5
        MVI     $01EF, R1
        MVO@    R1, R5
        MVII    #$035F, R4
        MVO@    R0, R4
        MVI     $035F, R1
        MVO@    R1, R5
        MVO     R0, $0020       ; display enable: closed until frame 1
        MVO     R0, $002A       ; dropped
        MVI     $002A, R1       ; reads $002A
        MVO@    R1, R5
        MVII    #$3805, R4
        MVO@    R0, R4          ; dropped
        MVI@    R4, R1          ; reads $0006 (R4 moved on)
        MVO@    R1, R5

; 6. interrupts on; the loop
        CLRR    R0
        MVO     R0, $0200
        MVII    #$02C0, R5
        CLRR    R3
        EIS
loop:   MVI     $0200, R0       ; frame count
        ADDR    R3, R0
        MVO     R0, $0029       ; CSR1
        MVI     $0029, R1       ; $0029 itself when closed
        MVO@    R1, R5
        MVO     R0, $0001       ; MXR1
        MVI     $0001, R1
        MVO@    R1, R5
        MVII    #$3820, R4      ; GRAM
        MVO@    R0, R4
        MVII    #$3820, R4
        MVI@    R4, R1
        MVO@    R1, R5
        MVO     R0, $01F3       ; PSG
        MVI     $01F3, R1
        MVO@    R1, R5
        MVI     $0021, R1       ; mode latch, if open
        CMPI    #$02F0, R5
        BLT     l_ring
        MVII    #$02C0, R5
l_ring: INCR    R3
        DIS
        MOVR    R3, R2          ; delay: 7 to 70 passes, changing
        ANDI    #$3F, R2
        ADDI    #7, R2
        EIS
dly:    DECR    R2
        BNEQ    dly
        B       loop

; data: two decles each (low byte, high byte), for SDBD reads
probes: BIDECLE $0040, $0060, $007F, $0080, $0081, $00E0, $00F0, $00FF
        BIDECLE $0360, $03FF, $0400, $04FF, $0500, $0700, $0FFF, $2000
        BIDECLE $2FFF, $4000, $4021, $4800, $5000, $6000, $7000, $7FFF
        BIDECLE $8000, $9000, $A000, $B000, $BFFF, $C000, $D000, $E000
        BIDECLE $F000, $FFFF, $1000, $1004, $1FFF, $3000, $3123, $37FF
        BIDECLE $3800, $3FFF, $01F0, $01FE, $01FF, $0100, $01EF, $0200
        BIDECLE $035F, $0000, $003F, $0033, $0020, $0021
NPROBE  EQU     54
windows: BIDECLE $3800, $3A01, $3C02, $3E03, $7804, $B805, $F806, $7A07
