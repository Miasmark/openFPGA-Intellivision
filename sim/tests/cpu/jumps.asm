; Jumps: J JE JD JSR JSRE JSRD (and CALL = JSR R5). S1 p.52, p.56: word 2 =
; BB AAAAAA II, word 3 = AAAAAAAAAA; the return address (PC+3) goes to
; R(4+BB); II = 01 enables, 10 disables interrupts. 12 cycles, interruptible.
;! words j1 = $0004 $0160 $0000
;! words q1 = $0004 $0061 $0100
;! words q2 = $0004 $0262 $0200
;! words q3b = $0004 $0361 $0300
;! words q4 = $0004 $0366 $0000
;! words jx = $0004 $03FC $03FF
;! words jy = $0004 $0000 $0000
;! words jz = $0004 $0160 $0000
;! expect s0: R5=q1 I=0
;! expect q2: R4=q2 I=1
;! expect q3: R6=q3 I=0
;! expect s3: I=1
;! expect s4: I=0
;! expect done: R5=done I=0 R6=$0300
;! cycles j1 s0 = 12
;! cycles s0 q1 = 7
        ORG     $5000
start:  MVII    #$0300, R6
j1:     JSR     R5, $6000
q1:     JSRE    R4, $6100
q2:     JSRD    R6, $6200       ; return address in R6, nothing pushed
q3:     MVII    #$0300, R6
q3b:    JE      $6300
q4:     JD      $6400
q5:     CALL    $6500
done:   NOP

jx:     J       $FFFF           ; encodings only, never run
jy:     JSR     R4, $0000
jz:     JSR     R5, $6000

        ORG     $6000
s0:     JR      R5
        ORG     $6100
        JR      R4
        ORG     $6200
        JR      R6
        ORG     $6300
s3:     J       q4
        ORG     $6400
s4:     J       q5
        ORG     $6500
        JR      R5
