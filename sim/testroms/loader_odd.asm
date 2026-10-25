; Synthetic cartridge image for the step-2 loader bench (sim/tb/tb_loader.py).
; Not a game and not in the CRC table, so the loader gives it the default map
; (layout 1) cut at its length. The bench assembles this file with
; tools/as1610.py, appends a table of WORD lines (a fixed pattern with
; different high and low bytes, so the byte order shows) to reach the size
; it wants, and drops the last byte: an odd length, 4n+1 or 4n+3 bytes,
; which the owner's library does not have (sim/regress/README.md).
        ORG     $5000
start:  MVII    #$0200, R4
        MVII    #$00F0, R0
fill:   MVO@    R0, R4
        DECR    R0
        BNEQ    fill
spin:   B       spin
table:
