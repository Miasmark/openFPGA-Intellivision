; Flags an instruction must leave alone or must not use (S1 p.53, p.55;
; wiki INCR/DECR, COMR, ADD, ADDI, ADD@, GSWD):
;  - DECR and COMR set S and Z only; C and O keep their old values (set
;    to 1 here beforehand with RSWD).
;  - ADD, ADDI, ADD@ and ADDR have no carry in: C=1 beforehand changes
;    nothing.
;  - GSWD R3 (GSWD works on R0-R3): SZOC0000SZOC0000.
;! expect t1: R0=0 SZOC=0111
;! expect t2: R0=$FFFF SZOC=1011
;! expect t3: R1=$FF00 SZOC=1011
;! expect t4: R0=2 SZOC=0000
;! expect t5: R0=0 SZOC=0101
;! expect t6: R0=$8000 SZOC=1010
;! expect t7: R0=3 SZOC=0000
;! expect t8: R3=$A0A0 SZOC=1010
        ORG     $5000
start:  MVII    #$0030, R4      ; bits 7-4 = 0011: O=1 C=1
        MVII    #1, R0
        RSWD    R4
        DECR    R0              ; $0000
t1:     MVII    #0, R0
        RSWD    R4
        DECR    R0              ; $FFFF
t2:     MVII    #$00FF, R1
        RSWD    R4
        COMR    R1              ; $FF00
t3:     MVII    #1, R0
        SETC
        ADDI    #1, R0          ; 1 + 1 = 2, C=0
t4:     MVII    #$FFFF, R0
        SETC
        ADD     val, R0         ; $FFFF + 1 = $0000, C=1, no overflow
t5:     MVII    #val, R5
        MVII    #$7FFF, R0
        SETC
        ADD@    R5, R0          ; $7FFF + 1 = $8000: S, overflow, no carry
t6:     MVII    #1, R0
        MVII    #2, R1
        SETC
        ADDR    R1, R0          ; 3
t7:     MVII    #$00A0, R4      ; S=1 Z=0 O=1 C=0
        RSWD    R4
        GSWD    R3
t8:     NOP
done:   NOP
val:    WORD    $0001
