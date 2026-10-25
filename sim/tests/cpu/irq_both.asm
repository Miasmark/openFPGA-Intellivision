; INTR and INTRM requested together: INTR is taken first (S1 p.24-25), and
; only its request is cleared; the INTRM request stays and is taken after
; the first interruptible instruction of the handler. The test bus gives
; the same vector for both.
;! intr 14-
;! intrm 14-
;! expect isr#1: CYC=27 INTS=1 R0=0 [$0300]=x
;! expect isr#2: CYC=42 INTS=2 R0=1 [$0301]=isr+1
;! expect done: R0=2 INTS=2 R6=$0300
        ORG     $5000
start:  MVII    #$0300, R6      ; 0-8
        EIS                     ; 8-12
        NOP                     ; 12-18, both lines low since 14
x:      NOP
done:   NOP

        ORG     $6000
isr:    INCR    R0              ; 27-33; INTRM taken at 33, back here at 42
        PULR    R7
