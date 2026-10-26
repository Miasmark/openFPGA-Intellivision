; MVO R7, A (direct): the word written is the PC after the instruction's
; address word, i.e. the next instruction's address (MAME cp1610.cpp
; cp1610_mvo; S1 p.46-48: the data goes out after the address fetch). Found
; by build step 9's MAME gate (Mind Strike's $66B9). PSHR R7 and MVO@ R7
; write the PC after the opcode word (their next instruction).
;! expect w1: [$0200]=w1
;! expect w2: [$0201]=w2
;! expect w3: [$0202]=w3 R6=$0203
;! cycles w0 w1 = 11
        ORG     $5000
start:  MVII    #$0202, R6
w0:     MVO     R7, $0200       ; writes w1
w1:     MVII    #$0201, R1
        MVO@    R7, R1          ; writes w2
w2:     PSHR    R7              ; writes w3
w3:     B       done
done:   B       done
