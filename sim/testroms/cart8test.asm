; Step-8 cartridge test: our own program in the EXEC slot, for the system
; bench (sim/tb/tb_system.py, images "cartbank" and "cartcfg") and the save
; state bench (sim/tb/tb_savestate.py, image "cartbank"). The cartridges are
; built from our sources by sim/testroms/step8/build_images.py with as1600:
; rombank.rom (an Intellicart .rom: bank windows at $6000-$6FFF, 16-bit RAM
; $8000-$83FF, 8-bit RAM $8800-$88FF) and cfgmap.bin + cfgmap.cfg (BIN +
; CFG: pages at $2000, $E000 and $F000, 16-bit RAM $8000-$81FF, 8-bit RAM
; $9000-$9002, word-exact ranges with gaps). The same program runs on both;
; the bench compares every bus cycle with the model (tools/intv_system.py
; with tools/mapper/cartfmt.py), and the dumps compare the page selects and
; the Intellicart bank registers. DESIGN.md 9 step 8: it writes and reads
; back the Intellicart bank registers at $0040-$005F and the RAM they map.
;   1. a write then a read of 14 addresses: cart RAM 16- and 8-bit, the
;      8-bit RAM's block past its CFG range, ROM, a CFG gap, a bank
;      register (write only: reads $FFFF), a bank window
;   2. Intellicart bank registers: (register, value) writes, each followed
;      by reads of $6000, $6001, $67FF, $6800 and $6FFF: windows at the
;      loaded Intellicart memory ($1000, $3000), at the RAM of section 1
;      ($8000, and the 8-bit $8800 through a 16-bit window), past $FFFF
;      (wraps), a register of a window that is not a bank window
;   3. ECS-style page selects ($xA5y to $xFFF) at $F000, $2000 and $E000,
;      each followed by reads of $F000, $F010, $FF00, $2000, $2800, $E800
;   4. interrupts on: the ISR counts frames, points $6000 at the frame's
;      bank and flips the $F000 page; the loop writes and reads cart RAM and
;      reads both windows, all through the run (so the bench's save and
;      restore round trips land in every state)
; Results go to System RAM ($0210 on; a ring at $02C0-$02EF in the loop).
; Assembled with ROMW 10, as carttest.asm: an address above $3FF goes
; through a pointer register (MVII + MVI@ / MVO@).
; SPDX-License-Identifier: MIT

        ROMW    10
        ORG     $1000
        B       main            ; $1000: reset vector
        NOP
        NOP

; $1004: interrupt vector. The frame count, the $6000 bank, the $F000 page.
isr:    PSHR    R0
        PSHR    R1
        PSHR    R4
        MVI     $0200, R0       ; frame count
        INCR    R0
        MVO     R0, $0200
        MOVR    R0, R1
        ANDI    #$3F, R1
        ADDI    #$10, R1        ; bank $10 + (frame & $3F)
        MVO     R1, $0046
        MVII    #$6000, R4
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

; 1. write, then read back
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

; 2. bank registers: (register, value), then the windows
        MVII    #banks, R4
        MVII    #NBANK, R2
b_loop: MVI@    R4, R3          ; register $0040-$005F (one decle)
        SDBD
        MVI@    R4, R0          ; value
        MVO@    R0, R3
        PSHR    R4              ; the table pointer
        MVII    #wins, R4
        MVII    #NWIN, R1
b_rd:   SDBD
        MVI@    R4, R3          ; a window address
        MVI@    R3, R0
        MVO@    R0, R5
        DECR    R1
        BNEQ    b_rd
        PULR    R4
        DECR    R2
        BNEQ    b_loop

; 3. page selects: (address, value), then the paged ranges
        MVII    #sels, R4
        MVII    #NSEL, R2
s_loop: SDBD
        MVI@    R4, R3          ; address
        SDBD
        MVI@    R4, R0          ; value
        MVO@    R0, R3
        PSHR    R4
        MVII    #pgrd, R4
        MVII    #NPGRD, R1
s_rd:   SDBD
        MVI@    R4, R3
        MVI@    R3, R0
        MVO@    R0, R5
        DECR    R1
        BNEQ    s_rd
        PULR    R4
        DECR    R2
        BNEQ    s_loop

; 4. interrupts on; the loop
        CLRR    R0
        MVO     R0, $0200
        MVII    #$02C0, R5
        CLRR    R3
        EIS
loop:   MOVR    R3, R4
        ANDI    #$FF, R4
        ADDI    #$8000, R4      ; cart RAM $8000 + (pass & $FF)
        MOVR    R3, R0
        SWAP    R0
        XORR    R3, R0
        MVO@    R0, R4
        MVI@    R4, R1          ; read it back
        MVO@    R1, R5
        MVII    #$8800, R4      ; 8-bit RAM (rombank) / nothing (cfgmap)
        MVO@    R3, R4
        MVI@    R4, R1
        MVO@    R1, R5
        MVII    #$6010, R4      ; the window the ISR chose
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
addrs:  BIDECLE $8000, $8001, $83FF, $8800, $88FF, $9000, $9002, $9003
        BIDECLE $8100, $5000, $512C, $0046, $D150, $6000
NADDR   EQU     14
; (register: one decle, value: two decles)
banks:  DECLE   $46
        BIDECLE $0010           ; $6000-$67FF -> Intellicart $1000
        DECLE   $56
        BIDECLE $0030           ; $6800-$6FFF -> $3000
        DECLE   $46
        BIDECLE $FF11           ; upper byte ignored: $1100
        DECLE   $46
        BIDECLE $0080           ; -> $8000: the 16-bit RAM of section 1
        DECLE   $56
        BIDECLE $0088           ; -> $8800: the 8-bit RAM, through a 16-bit window
        DECLE   $46
        BIDECLE $00FC           ; -> $FC00-$03FF: wraps past $FFFF
        DECLE   $40
        BIDECLE $0050           ; $0000-$07FF: no bank window there
        DECLE   $46
        BIDECLE $0010
NBANK   EQU     8
wins:   BIDECLE $6000, $6001, $67FF, $6800, $6FFF
NWIN    EQU     5
sels:   BIDECLE $FFFF, $FA51    ; $F000 page 1
        BIDECLE $FFFF, $FA52    ; page 2
        BIDECLE $FFFF, $FA5F    ; page 15
        BIDECLE $2FFF, $2A51    ; $2000 page 1
        BIDECLE $2FFF, $2A53    ; page 3
        BIDECLE $EFFF, $EA51    ; $E000 page 1 (cfgmap: its upper 2K)
        BIDECLE $FFFF, $FA50    ; back to page 0
        BIDECLE $2FFF, $2A50
        BIDECLE $EFFF, $EA50
NSEL    EQU     9
pgrd:   BIDECLE $F000, $F010, $FF00, $2000, $2800, $E800
NPGRD   EQU     6
