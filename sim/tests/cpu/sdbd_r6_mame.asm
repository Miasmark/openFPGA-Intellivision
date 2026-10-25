; SDBD with R6, the MAME variant (sdbd_r6=mame): two pre-decrements, low
; byte from the top of the stack, high byte from the word below; 4 + 13
; cycles (MAME cp1610.cpp cp1610_sdbd_mviat_d). Not the model's default.
;! options sdbd_r6=mame
;! expect d12: R0=$1256 R6=stk
;! cycles p1 d12 = 17
        ORG     $5000
start:  MVII    #stk+2, R6
p1:     SDBD
        PULR    R0
d12:    NOP
done:   NOP
stk:    WORD    $0012, $0056
