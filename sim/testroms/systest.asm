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
;      aliases; the mode latch: FGBG by writes of $0021, $4021, $8021,
;      colour stack by reads of $8021, $4021, $C021 in between, so every
;      access changes it (the bench logs each change of the latch)
;   3. GRAM written through all eight 512-word windows ($3800, $3A00,
;      $3C00, $3E00, $7800, $B800, $F800, $7A00) and read through two
;   4. every PSG register written with $FF and $A5 and read back (masks,
;      hand controllers at $01FE / $01FF)
;   5. scratchpad and System RAM with 16-bit values; then a write of $20
;      (display enable) after frame 0's window: written for the step-3
;      rule (MAME's), under which it closed the STIC and GRAM for the rest
;      of frame 0. Since the console fit F (docs/TIMING_FIT.md; hw_frame2)
;      a late $20 write leaves a display-off frame open, so what follows
;      checks that instead: a STIC and a GRAM write and read there (kept),
;      reads of $0021 and $C021 (the mode latch goes to Color Stack), a
;      second $20 write, GRAM reads through the $3A00 and $3E00 windows.
;      Closed accesses (reads $0000) are in sections 6 and 7.
;   6. interrupts on; the ISR counts frames, enables the display (sets the
;      STIC handshake) on odd frames only, and writes and reads STIC and
;      GRAM in VBlank. The main loop writes and reads STIC registers, GRAM
;      and the PSG all through the frame, with a delay that changes every
;      pass, so accesses land inside and outside VBlank with the handshake
;      set and clear. In frame 7 the loop goes to section 7, then back.
;   7. the end of the bus-copy window (cycles 0-3,790: the console fit F,
;      docs/TIMING_FIT.md; one slot later than INTRM's end), one
;      probe a frame, each timed from the interrupt to the cycle (the
;      model and sim/tb/tb_system.py check where each lands): with the
;      handshake set, a STIC write in slot 3789 (open), GRAM read 3790
;      (open), STIC read 3791 (closed: $0000), GRAM write 3792 (dropped), GRAM
;      write 3790 (kept), STIC write 3791 (dropped), STIC read 3790 (open),
;      GRAM read 3791 through $3E00 (closed); then INTRM's end: with an
;      edge pending and I clear, EIS so that the next instruction ends in
;      slot 3789, after the line has dropped (the request is lost), and in
;      another frame in slot 3788 (taken: the INTAK is in slot 3789);
;      last (step 5), a write to $18 in the last slot of a frame whose
;      display is off, the cycle in which the STIC ORs the frame's
;      collision bits into $18-$1F: the write is kept (p11).
;      The delays were found with the model (scratch tuner; the comment
;      '; @dN' marks each delay block; retuned for F's CPU and window).
; Results go to System RAM ($0210 on; a ring at $02C0-$02EF in the loop),
; so the dumps show them too; the bench compares every bus cycle anyway.
; SPDX-License-Identifier: MIT

        ROMW    10
        ORG     $1000
        B       main            ; $1000: reset vector
        NOP
        NOP

; $1004: interrupt vector, through the word at $02FE (isr_main; section 7
; points it at isr7).
isr:    MVI     $02FE, R7
; Runs in VBlank (the bus-copy window).
isr_main:
        PSHR    R0
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
        MVII    #isr_main, R0
        MVO     R0, $02FE       ; the interrupt handler

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
        MVO     R1, $0021       ; FGBG (the reads above left colour stack)
        MVII    #$8021, R4
        MVI@    R4, R1          ; colour stack (alias read; the cartridge answers)
        MVO@    R1, R5
        MVII    #$4021, R4      ; (addresses over $3FF: pointer, not operand,
        MVO@    R1, R4          ; FGBG through the $4000 alias    ROMW 10)
        MVII    #$4021, R4
        MVI@    R4, R1          ; colour stack
        MVII    #$8021, R4
        MVO@    R1, R4          ; FGBG
        MVII    #$C021, R4
        MVI@    R4, R1          ; colour stack
        MVO     R1, $0021       ; FGBG

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
        MVO     R0, $0020       ; display enable after the window (F: stays open)
        MVO     R0, $002A       ; kept (F; MAME's rule: dropped)
        MVI     $002A, R1       ; reads $3FFA (F; MAME's rule: $002A)
        MVO@    R1, R5
        MVII    #$3805, R4
        MVO@    R0, R4          ; kept (F)
        MVI@    R4, R1          ; reads GRAM $3806 (R4 moved on; F: open)
        MVO@    R1, R5
        MVI     $0021, R1       ; open (F): the mode latch to Color Stack
        MVII    #$C021, R4      ; open, through the alias
        MVI@    R4, R1
        MVO     R0, $0020       ; a second $20 write (the handshake is set)
        MVII    #$3BC5, R4      ; GRAM read, $3A00 window (F: open)
        MVI@    R4, R1
        MVII    #$3FFF, R4      ; GRAM read, $3E00 window (F: open)
        MVI@    R4, R1

; 6. interrupts on; the loop
        CLRR    R0
        MVO     R0, $0200
        MVII    #$02C0, R5
        CLRR    R3
        EIS
loop:   MVI     $0200, R0       ; frame count
        CMPI    #S7F, R0
        BEQ     sect7
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

; 7. the end of the bus-copy window: one probe a frame
S7F     EQU     7               ; the frame count that starts section 7
sect7:  DIS
        MVII    #isr7, R0
        MVO     R0, $02FE
        MVII    #p1, R0
        MVO     R0, $02FD       ; the first probe
        EIS
w7:     B       w7              ; wait for the frame's interrupt
isr7:   DECR    R6              ; drop the return address
        MVO     R0, $0020       ; handshake: closed after the window
        MVI     $02FD, R7       ; the probe of this frame

p1:     MVII    #p2, R0
        MVO     R0, $02FD
        MVII    #$002B, R4      ; STIC write, slot 3789: open, kept
        MVII    #$0005, R0
        MVII    #244, R2     ; @d1
p1d:   DECR    R2
        BNEQ    p1d
        MVII    #0, R3          ; @d1
        MVII    #0, R3          ; @d1
        MVII    #0, R3          ; @d1
        MVO@    R0, R4
        B       w7
p2:     MVII    #p3, R0
        MVO     R0, $02FD
        MVII    #$3850, R4      ; GRAM read, slot 3790: open
        MVII    #245, R2     ; @d2
p2d:   DECR    R2
        BNEQ    p2d
        NOP                     ; @d2
        NOP                     ; @d2
        NOP                     ; @d2
        MVI@    R4, R1
        B       w7
p3:     MVII    #p4, R0
        MVO     R0, $02FD
        MVII    #$002A, R4      ; STIC read, slot 3791: closed ($0000)
        MVII    #245, R2     ; @d3
p3d:   DECR    R2
        BNEQ    p3d
        NOP                     ; @d3
        NOP                     ; @d3
        NOP                     ; @d3
        NOPP                    ; @d3
        MVI@    R4, R1
        B       w7
p4:     MVII    #p5, R0
        MVO     R0, $02FD
        MVII    #$3851, R4      ; GRAM write, slot 3792: dropped
        MVII    #$00A6, R0
        MVII    #244, R2     ; @d4
p4d:   DECR    R2
        BNEQ    p4d
        NOP                     ; @d4
        NOP                     ; @d4
        NOP                     ; @d4
        MVII    #0, R3          ; @d4
        MVO@    R0, R4
        B       w7
p5:     MVII    #p6, R0
        MVO     R0, $02FD
        MVII    #$3852, R4      ; GRAM write, slot 3790: kept
        MVII    #$005B, R0
        MVII    #244, R2     ; @d5
p5d:   DECR    R2
        BNEQ    p5d
        NOP                     ; @d5
        MVII    #0, R3          ; @d5
        MVII    #0, R3          ; @d5
        MVO@    R0, R4
        B       w7
p6:     MVII    #p7, R0
        MVO     R0, $02FD
        MVII    #$0030, R4      ; STIC write, slot 3791: dropped
        MVII    #$0003, R0
        MVII    #244, R2     ; @d6
p6d:   DECR    R2
        BNEQ    p6d
        NOPP                    ; @d6
        MVII    #0, R3          ; @d6
        MVII    #0, R3          ; @d6
        MVII    #0, R3          ; @d6
        MVO@    R0, R4
        B       w7
p7:     MVII    #p8, R0
        MVO     R0, $02FD
        MVII    #$002B, R4      ; STIC read, slot 3790: open (the value of p1)
        MVII    #245, R2     ; @d7
p7d:   DECR    R2
        BNEQ    p7d
        NOP                     ; @d7
        MVII    #0, R3          ; @d7
        MVII    #0, R3          ; @d7
        MVI@    R4, R1
        B       w7
p8:     MVII    #p9, R0
        MVO     R0, $02FD
        MVII    #$3E53, R4      ; GRAM read through $3E00, slot 3791: closed ($0000)
        MVII    #245, R2     ; @d8
p8d:   DECR    R2
        BNEQ    p8d
        NOP                     ; @d8
        NOP                     ; @d8
        NOPP                    ; @d8
        MVI@    R4, R1
        B       w7
; INTRM's end: I clear across the next frame's start (an edge pending),
; then EIS, then a NOP that ends after the line has dropped (p9: the
; request is lost) or in its last slot (p10: taken)
p9:     DIS
        MVII    #p10, R0
        MVO     R0, $02FD
        MVII    #1240, R2    ; @d9
p9d:   DECR    R2
        BNEQ    p9d
        NOP                     ; @d9
        NOP                     ; @d9
        NOP                     ; @d9
        MVII    #0, R3          ; @d9
        EIS
p9x:    NOP                     ; ends in slot 3789: not taken
        B       w7
p10:    DIS
        MVII    #p11, R0
        MVO     R0, $02FD
        MVII    #1240, R2    ; @d10
p10d:  DECR    R2
        BNEQ    p10d
        NOP                     ; @d10
        NOP                     ; @d10
        NOPP                    ; @d10
        EIS
p10x:   NOP                     ; ends in slot 3788: taken (INTAK in 3789)
        B       w7
; A collision register written in a frame's last slot (step 5): with I
; clear the next frame has no ISR, so its display stays off and the STIC
; is open all frame. $18 is set to $0006 there, then cleared through the
; $4000 alias in the frame's last slot (14933), the cycle in which the
; STIC ORs the frame's collision bits (none) into $18-$1F: the write is
; kept, and $18 reads $3C00 in the next frame's VBlank (STIC_NOTES 6).
p11:    DIS
        MVII    #p_end, R0
        MVO     R0, $02FD
        MVII    #$4018, R4      ; $18 through the $4000 alias
        MVII    #1300, R2    ; @d11
p11d:  DECR    R2
        BNEQ    p11d
        MVII    #$0006, R0
        MVO     R0, $0018       ; display off: open; $18 = $0006
        CLRR    R0
        MVII    #428, R2     ; @d12
p11e:  DECR    R2
        BNEQ    p11e
        NOP                     ; @d12
        NOP                     ; @d12
        MVII    #0, R3          ; @d12
        MVO@    R0, R4          ; slot 14933: $18 = 0
        MVI     $0018, R1       ; the next frame's VBlank: $3C00
        MVO     R1, $02F8
        EIS
        B       w7
p_end:  DIS
        MVII    #isr_main, R0
        MVO     R0, $02FE
        MVII    #S7F + 1, R0
        MVO     R0, $0200
        EIS
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
