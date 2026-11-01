; Taking an interrupt. INTRM* goes low at cycle 100 and stays low. The CPU
; takes it at the end of the first interruptible instruction after that,
; with interrupts enabled (wiki CP1610 Interruptibility; S1 p.12-13). The
; sequence is INTAK NACT DW DWS NACT IAB NACT NACT NACT: 9 cycles (S1 p.35
; timing diagram). The PC is pushed at R6, R6 increments, the vector comes
; from IAB (here: label isr), and the I flag stays set. The request is an
; edge: the line is still low when the ISR runs, but there is no second
; interrupt (wiki CP1610 Signal Pins).
;! intrm 100-
;! expect n14: CYC=96
;! expect isr: CYC=111 R6=$0301 [$0300]=n15 I=1 INTS=1
; PULR R7 is 12 cycles, not S1's 11: the console fit F (docs/TIMING_FIT.md), so done
; is at 159.
;! expect done: CYC=159 INTS=1 R6=$0300
;! cycles n14 isr = 15
        ORG     $5000
start:  MVII    #$0300, R6      ; 0-8
        EIS                     ; 8-12
n0:     NOP                     ; 12-18
n1:     NOP                     ; 18-24
n2:     NOP                     ; 24-30
n3:     NOP                     ; 30-36
n4:     NOP                     ; 36-42
n5:     NOP                     ; 42-48
n6:     NOP                     ; 48-54
n7:     NOP                     ; 54-60
n8:     NOP                     ; 60-66
n9:     NOP                     ; 66-72
n10:    NOP                     ; 72-78
n11:    NOP                     ; 78-84
n12:    NOP                     ; 84-90
n13:    NOP                     ; 90-96
n14:    NOP                     ; 96-102
n15:    NOP                     ; 102-108
n16:    NOP                     ; 108-114
n17:    NOP                     ; 114-120
n18:    NOP                     ; 120-126
n19:    NOP                     ; 126-132
done:   NOP

        ORG     $6000
isr:    NOP
        PULR    R7              ; return (12 cycles, TIMING_FIT F)
