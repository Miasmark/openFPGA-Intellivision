; hwlib.asm: the shared part of the hardware measurement cartridges (sim/testroms/hw/,
; docs/HW_TESTS.md). build_hw.py puts it in front of each program's own source (as1610
; has no INCLUDE): the cartridge header at $5000 that the EXEC starts (as
; sim/testroms/sticmob_cart.py: header, title, start-up code after the title), the take-over
; of the EXEC's ISR vector ($0100 / $0101), and text output on the background (Color Stack
; mode, GROM characters: card = ASCII - 32). Each program defines `isr` (called by the
; EXEC's dispatcher in VBlank with R5 = its return code: end with JR R5, keep R5) and `main`
; (never returns). TITLE is substituted by build_hw.py.
;
; System RAM use: BACKTAB $0200-$02EF (20 x 12), the stack from STACK ($02F1: the CPU's
; interrupt pushes the interrupted PC at STACK, so an ISR finds it there while main's stack
; is empty), program variables from VARS ($0300).
; SPDX-License-Identifier: MIT

        ROMW    16
STACK   EQU     $02F1
VARS    EQU     $0300
BACKTAB EQU     $0200
WHITE   EQU     7
YELLOW  EQU     6
RED     EQU     2
GREEN   EQU     5
TAN     EQU     3

        ORG     $5000
; the EXEC's cartridge header: nothing for the EXEC to draw or run; start-up code after
; the title
        BIDECLE c_zero          ; $5000 MOB picture list: empty
        BIDECLE c_zero          ; $5002 process table: empty
        BIDECLE c_start         ; $5004 program start
        BIDECLE c_zero          ; $5006 background picture list: empty
        BIDECLE c_ones          ; $5008 GRAM picture list: empty
        BIDECLE c_title         ; $500A title and year
        DECLE   $03C0           ; $500C flags: run the code after the title
c_zero: DECLE   0               ; $500D border extension
        DECLE   0               ; $500E Color Stack mode
c_ones: DECLE   1, 1, 1, 1      ; colour stack
        DECLE   1               ; border
c_title:
        DECLE   126             ; year - 1900
        STRING  "TITLE"
        DECLE   0
; start-up code after the title: hook the ISR vector, wait for VBlank
c_start:
        MVII    #c_init, R0
        MVO     R0, $0100
        SWAP    R0
        MVO     R0, $0101
        EIS
c_spin: B       c_spin
; called by the EXEC's dispatcher in VBlank: take the machine over for good
c_init: DIS
        MVII    #STACK, R6
        MVII    #isr, R0
        MVO     R0, $0100
        SWAP    R0
        MVO     R0, $0101
        B       main

; ------------------------------------------------------------------ text
; clrscr: BACKTAB all blank (card 0, colour 0). Uses R0, R1, R4.
clrscr: MVII    #BACKTAB, R4
        MVII    #240, R1
        CLRR    R0
cs_lp:  MVO@    R0, R4
        DECR    R1
        BNEQ    cs_lp
        JR      R5

; puts: the 0-ended STRING at R1 to BACKTAB at R4 (R4 advances), colour R3; R1 ends past
; the string's 0 (the next string of a table). Uses R0.
puts:   PSHR    R5
        MOVR    R1, R5
ps_lp:  MVI@    R5, R0
        TSTR    R0
        BEQ     ps_end
        SUBI    #32, R0
        SLL     R0, 2
        SLL     R0, 1
        ADDR    R3, R0
        MVO@    R0, R4
        B       ps_lp
ps_end: MOVR    R5, R1
        PULR    R7

; puthex: R0 as 4 hex digits at R4 (R4 advances), colour R3; constant time (a table, no
; data-dependent branch). Uses R1, R2; R0 is kept.
puthex: PSHR    R5
        PSHR    R0
        MVII    #4, R2
ph_lp:  MOVR    R0, R1
        SWAP    R1
        SLR     R1, 2
        SLR     R1, 2
        ANDI    #$F, R1
        ADDI    #hexcard, R1
        MOVR    R1, R5
        MVI@    R5, R1
        ADDR    R3, R1
        MVO@    R1, R4
        SLL     R0, 2
        SLL     R0, 2
        DECR    R2
        BNEQ    ph_lp
        PULR    R0
        PULR    R7
hexcard:
        DECLE   ('0'-32)*8, ('1'-32)*8, ('2'-32)*8, ('3'-32)*8
        DECLE   ('4'-32)*8, ('5'-32)*8, ('6'-32)*8, ('7'-32)*8
        DECLE   ('8'-32)*8, ('9'-32)*8, ('A'-32)*8, ('B'-32)*8
        DECLE   ('C'-32)*8, ('D'-32)*8, ('E'-32)*8, ('F'-32)*8

; putdec: R0 (unsigned) as 5 decimal digits at R4 (R4 advances), colour R3. Uses R1, R2;
; R0 is kept.
putdec: PSHR    R5
        PSHR    R0
        MVII    #p10, R5
pd_nxt: MVI@    R5, R1
        TSTR    R1
        BEQ     pd_end
        MVII    #('0'-32)*8, R2
pd_sub: CMPR    R1, R0
        BNC     pd_put
        SUBR    R1, R0
        ADDI    #8, R2
        B       pd_sub
pd_put: ADDR    R3, R2
        MVO@    R2, R4
        B       pd_nxt
pd_end: PULR    R0
        PULR    R7
p10:    DECLE   10000, 1000, 100, 10, 1, 0

; stic_set: the STIC set up for text (call in VBlank): Color Stack mode, colour stack 0
; black, border blue, no delays. Uses R0.
stic_set:
        CLRR    R0
        MVO     R0, $0021       ; Color Stack mode
        MVO     R0, $0028       ; colour stack 0: black
        MVO     R0, $0030       ; HDR
        MVO     R0, $0031       ; VDR
        MVO     R0, $0032       ; CBR
        MVII    #1, R0
        MVO     R0, $002C       ; border: blue
        JR      R5
