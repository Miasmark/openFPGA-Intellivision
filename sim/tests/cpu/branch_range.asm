; Branch displacement encoding and range. S1 p.47, p.54: forward adds the
; displacement to PC+2; backward adds its one's complement (PC+2-disp-1).
; All 16 bits of the displacement count (wiki Branch). Also a branch that
; wraps from $FFF8 to $0010, and the 9/7 cycle counts.
;! words br0 = $0200 $0000
;! words br1 = $0208 $0000
;! words self = $0220 $0001
;! words bpc1 = $0220 $0000
;! words farb = $0200 far-farb-2
;! words backb = $0220 backb+1-back
;! words wrapb = $0220 $FFE9
;! words t1 = $0201 $0000
;! expect done: R0=3 R1=1
;! cycles t1 t2 = 9
;! cycles t2 t3 = 7
        ORG     $5000
start:  CLRR    R0
br0:    B       br1             ; to the next instruction: displacement 0
br1:    NOPP                    ; never branches
        B       go
self:   B       self            ; to itself: backward, displacement 1
bpc1:   B       bpc1+1          ; to its own displacement word: backward 0
go:     SETC
t1:     BC      t2              ; taken: 9 cycles
t2:     BNC     fail            ; not taken: 7 cycles
t3:     INCR    R0
farb:   B       far             ; forward $1000 or so
back:   INCR    R0
        J       $FFF8
fail:   MVII    #$DEAD, R1
done:   NOP

        ORG     $6000
far:    INCR    R0
backb:  B       back            ; backward

        ORG     $FFF8
wrapb:  B       $0010           ; wraps: backward $FFE9, lands on $0010

        ORG     $0010
        MVII    #1, R1
        J       done
