; Step-3 cartridge write test: our own program in the EXEC slot, for the
; system bench (sim/tb/tb_system.py, images "cartram" and "cartpaged"). The
; cartridge is a synthetic image (tools/synth_image.py: a word pattern whose
; CRC32 is forced to a table entry, no game data): layout 25 (8-bit cart
; RAM at $8800-$8FFF) or layout 26 (paged ROM at $F000, two pages). The
; same program runs on both; the bench compares every bus cycle with the
; model (tools/intv_system.py with tools/mapper's CartModel), and the dumps
; compare the page selects. It checks that the bus fabric gives the
; cartridge every write (intv_bus.sv: the port is asked after each DW):
;   1. a write then a read of 13 addresses: cart RAM (16-bit values: the
;      8-bit RAM keeps the low byte, mirrored cells), ROM (a write changes
;      nothing), unmapped space, the Intellicart bank register range
;      $0040-$005F (nothing there before build step 8: reads $FFFF)
;   2. ECS-style page selects ($xA5y to $xFFF, tools/mapper/README.md):
;      page 1 of $F000 (WSMLB's second page on layout 26), page 2 (none
;      there), page 0 again, a select of a plain ROM range ($5000), and
;      writes to $xFFF that are not selects (wrong value, wrong range);
;      the ROM at $F000 and $5000 read after each
;   3. interrupts on; the ISR and the main loop write and read cart RAM and
;      flip the $F000 page, all through the run (so the round trips of the
;      bench save and restore it in every state)
; Results go to System RAM ($0210 on; a ring at $02C0-$02EF in the loop).
; Assembled with ROMW 10, as systest.asm: the EXEC ROM keeps 10 bits, so
; an address above $3FF goes through a pointer register (MVII + MVI@ /
; MVO@), never as the operand of a direct MVI / MVO.
; SPDX-License-Identifier: MIT

        ROMW    10
        ORG     $1000
        B       main            ; $1000: reset vector
        NOP
        NOP

; $1004: interrupt vector. A cart RAM cell per frame, and the $F000 page.
isr:    PSHR    R0
        PSHR    R1
        PSHR    R4
        MVI     $0200, R0       ; frame count
        INCR    R0
        MVO     R0, $0200
        MVII    #$8900, R4
        ADDR    R0, R4
        MVO@    R0, R4          ; cart RAM $8900 + frame
        MVII    #$8900, R4
        MVI@    R4, R1
        MVO     R1, $0201
        MOVR    R0, R1
        ANDI    #1, R1
        ADDI    #$FA50, R1      ; page = frame & 1
        MVII    #$FFFF, R4
        MVO@    R1, R4
        MVII    #$F010, R4
        MVI@    R4, R1
        MVO     R1, $0202
        PULR    R4
        PULR    R1
        PULR    R0
        PULR    R7

main:   MVII    #$0300, R6      ; stack
        MVII    #$0210, R5      ; results

; 1. write, then read back, 13 addresses
        MVII    #addrs, R4
        MVII    #NADDR, R2
        MVII    #$A55A, R0
w_loop: SDBD
        MVI@    R4, R3          ; address (two decles)
        MVO@    R0, R3
        ADDI    #$1111, R0
        DECR    R2
        BNEQ    w_loop
        MVII    #addrs, R4
        MVII    #NADDR, R2
r_loop: SDBD
        MVI@    R4, R3
        MVI@    R3, R1
        MVO@    R1, R5
        DECR    R2
        BNEQ    r_loop

; 2. page selects: (address, value) pairs, each followed by reads of
;    $F000, $FFFE and $5000
        MVII    #sels, R4
        MVII    #NSEL, R2
s_loop: SDBD
        MVI@    R4, R3          ; address
        SDBD
        MVI@    R4, R0          ; value
        MVO@    R0, R3
        MVII    #$F000, R3
        MVI@    R3, R1
        MVO@    R1, R5
        MVII    #$FFFE, R3
        MVI@    R3, R1
        MVO@    R1, R5
        MVII    #$5000, R3
        MVI@    R3, R1
        MVO@    R1, R5
        DECR    R2
        BNEQ    s_loop

; 3. interrupts on; the loop
        CLRR    R0
        MVO     R0, $0200
        MVII    #$02C0, R5
        CLRR    R3
        EIS
loop:   MOVR    R3, R4
        ANDI    #$3FF, R4
        ADDI    #$8800, R4      ; cart RAM $8800 + (pass & $3FF)
        MOVR    R3, R0
        SWAP    R0
        XORR    R3, R0
        MVO@    R0, R4
        SUBI    #1, R4
        MVI@    R4, R1          ; read it back
        MVO@    R1, R5
        MVII    #$8C00, R4      ; a cell section 1 wrote
        MVI@    R4, R1
        MVO@    R1, R5
        MVII    #$F7FF, R4      ; the page the ISR chose
        MVI@    R4, R1
        MVO@    R1, R5
        CMPI    #$02F0, R5
        BLT     l_ring
        MVII    #$02C0, R5
l_ring: INCR    R3
        MOVR    R3, R2
        ANDI    #$1F, R2
        ADDI    #5, R2
dly:    DECR    R2
        BNEQ    dly
        B       loop

; data: two decles each (low byte, high byte), for SDBD reads
addrs:  BIDECLE $8800, $8801, $8FFF, $8ABC, $8C00, $5000, $6FFF, $9000
        BIDECLE $C000, $0040, $005F, $F000, $D123
NADDR   EQU     13
sels:   BIDECLE $FFFF, $FA51    ; page 1 of $F000
        BIDECLE $FFFF, $FA52    ; page 2: not there on layout 26
        BIDECLE $5FFF, $5A53    ; a plain ROM range: stored, reads unchanged
        BIDECLE $EFFF, $DA51    ; not a select (wrong range nibble)
        BIDECLE $FFFF, $1234    ; not a select
        BIDECLE $FFFF, $FA50    ; page 0 again
        BIDECLE $FFFF, $FA51    ; page 1, left for the loop
NSEL    EQU     7
