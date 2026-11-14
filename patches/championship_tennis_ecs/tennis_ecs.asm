; SPDX-License-Identifier: MIT
; Copyright (c) 2026 Miasmark and contributors
;
; Championship Tennis (INTV 1985): four human players with the ECS. Our own patch words only.
; Applies to the original image (CRC32 4CC46A04) and includes the ECS page fix (step 1 below;
; earlier versions of this folder held the page fix alone), so one patch does both.
;
; The game already has a four-player doubles setup (players placed in four court positions) and
; plays it with players 3 and 4 computer-steered, because nothing reads hand controllers 3 and 4.
; The ECS ROM has a service for that (World Cup Football uses it): its own main loop ($70C4) runs
; the EXEC's hand-controller decoder ($152F) a second time for the ECS's ports $00FF / $00FE. That
; loop also acts on bits of $015D-$015F, which this game uses as its own variables (its start
; table sets them to 2, 3, 6, 7), so the game cannot hand its main loop to the ECS. Instead this
; patch does the same work from the game's own once-per-pass task:
;  1. pages the ECS's $E ROM out before the title routine needs the cartridge's $EF10 (as before);
;  2. at the game's start, probes the ECS RAM ($47CD, as World Cup Football does) and, with an
;     ECS, sets this patch's ECS RAM bytes ($47D0-$47D6) to an idle controller state;
;  3. each pass of the game's task ($5072, once per EXEC main-loop pass), when the ECS RAM is
;     there: makes the ECS's two ports inputs, swaps the EXEC's controller state ($011F-$0124) with
;     the one kept for controllers 3/4 in ECS RAM, runs the EXEC's decoder for $00FF (controller 3)
;     and $00FE (controller 4) with a marker byte set, and swaps back (what the ECS's $7134 does);
;  4. the game's "held disc" re-check ($E0DC: after a point it re-sends each human player's held
;     disc direction, reading the EXEC's state byte at $011E + controller) reads controllers 3/4's
;     state from ECS RAM instead of $0121/$0122 (the EXEC's bytes for something else, which made
;     players 3 and 4 run off at every point);
;  5. in front of the game's five hand-controller handlers (disc, keypad, three side buttons),
;     adds 2 to the controller number R1 while the marker is set, so controllers 3 and 4 claim
;     and steer players 3 and 4 (the game's own table at $0175 + controller; $0178 / $0179 are
;     unused otherwise: README).
; Without an ECS, steps 2-4 change nothing: the probe fails and the marker never reads $5A.
; See README.md.

        ROMW    10

; -- 1. the ECS page fix (the first version of this patch, unchanged) -----------------------------
TITLE   EQU     $5056           ; the title routine: PSHR R5 / MVII #$0007, R3 / MVII #$023D, R4
TBACK   EQU     $5059
PSTUB   EQU     $6FE0           ; end padding of the $5000 segment

        ORG     TITLE
        J       PSTUB

        ORG     PSTUB
        PSHR    R5              ; the two instructions J replaced
        MVII    #$EA50, R3      ; page the ECS ROM's $E000-$EFFF out (page 0)
        MVII    #$EFFF, R4
        MVO@    R3, R4
        MVII    #$0007, R3
        J       TBACK

; -- 2.-4. controllers 3 and 4 --------------------------------------------------------------------
START   EQU     $5200           ; the game's start routine (header bidecle at $5004)
TASK    EQU     $5072           ; the game's task: PSHR R5 / MVI $017E, R0 / TSTR R0 ...
TASKBK  EQU     $5075
DECODE  EQU     $152F           ; EXEC: decode the port value in R2 with the state table at R1
CSTATE  EQU     $011F           ; EXEC: the hand-controller state, 6 bytes ($011F-$0124)
PROBE   EQU     $47CD           ; ECS RAM: the probe byte (World Cup Football's)
SAVE    EQU     $47D0           ; ECS RAM: controllers 3/4's state, 6 bytes
MARK    EQU     $47D6           ; ECS RAM: MAGIC while the decoder runs for controllers 3/4
MAGIC   EQU     $005A
PSGEN   EQU     $00F8           ; the ECS sound chip's enable register (bits 6/7: port directions)
PORT3   EQU     $00FF           ; ECS port B: hand controller 3
PORT4   EQU     $00FE           ; ECS port A: hand controller 4

        ORG     $5004
        BIDECLE S_START

        ORG     TASK
        J       T_HOOK

        ORG     $E0DF           ; MVII #$011E, R1 / ADDR R3, R1 (R3 = controller 1-4)
        J       HELD

        ORG     $52D0           ; the hand-controller handler table (copied to RAM by the game)
        BIDECLE H_DISC, H_KEY, H_TOP, H_LEFT, H_RIGHT

        ORG     $EF5A           ; end padding of the $E000 segment
S_START MVII    #$0001, R0      ; ECS RAM there?
        MVO     R0, PROBE
        CMP     PROBE, R0
        BNEQ    S_GO
        MVII    #SAVE, R4       ; controllers 3/4's state as the EXEC keeps an idle controller's:
        MVII    #$0040, R0      ; $40 in the first two bytes (with 0 the first idle pass would
        MVO@    R0, R4          ; dispatch a release, which claims a player)
        MVO@    R0, R4
        CLRR    R0
        MVII    #5, R1
S_CLR   MVO@    R0, R4
        DECR    R1
        BNEQ    S_CLR
S_GO    J       START

T_HOOK  PSHR    R5              ; the task's first instruction
        MVII    #$0001, R0
        MVO     R0, PROBE
        CMP     PROBE, R0
        BNEQ    T_BACK
        JSR     R5, POLL
T_BACK  MVI     $017E, R0       ; the task's second instruction
        J       TASKBK

POLL    PSHR    R5
        MVI     PSGEN, R0       ; both ECS ports inputs
        ANDI    #$003F, R0
        MVO     R0, PSGEN
        JSR     R5, XSTATE
        MVII    #MAGIC, R0
        MVO     R0, MARK
        MVII    #CSTATE, R1     ; controller 3: the EXEC's slot for controller 1
        MVI     PORT3, R2
        ANDI    #$00FF, R2
        JSR     R5, DECODE
        MVII    #CSTATE+1, R1   ; controller 4: the EXEC's slot for controller 2
        MVI     PORT4, R2
        ANDI    #$00FF, R2
        JSR     R5, DECODE
        CLRR    R0
        MVO     R0, MARK
        JSR     R5, XSTATE
        PULR    R7

XSTATE  MVII    #CSTATE, R2     ; exchange $011F-$0124 with SAVE
        MVII    #SAVE, R3
        MVII    #6, R1
SW_L    MVI@    R2, R4
        MVI@    R3, R0
        MVO@    R0, R2
        MVO@    R4, R3
        INCR    R2
        INCR    R3
        DECR    R1
        BNEQ    SW_L
        JR      R5

H_DISC  PSHR    R5
        JSR     R5, FIXR1
        PULR    R5
        J       $D000
H_KEY   PSHR    R5
        JSR     R5, FIXR1
        PULR    R5
        J       $6489
H_TOP   PSHR    R5
        JSR     R5, FIXR1
        PULR    R5
        J       $DD2B
H_LEFT  PSHR    R5
        JSR     R5, FIXR1
        PULR    R5
        J       $DD30
H_RIGHT PSHR    R5
        JSR     R5, FIXR1
        PULR    R5
        J       $DD35

FIXR1   PSHR    R0              ; controller 0/1 -> 2/3 while the marker is set
        MVI     MARK, R0
        CMPI    #MAGIC, R0
        BNEQ    F_DONE
        ADDI    #$0002, R1
F_DONE  PULR    R0
        JR      R5

; -- 4. the held-disc re-check, in the $5000 segment's end padding after the page-fix stub ---------
        ORG     $6FF0
HELD    MVII    #$011E, R1      ; controllers 1/2: the EXEC's state byte ($011F/$0120)
        CMPI    #3, R3
        BLT     H_GO
        MVII    #SAVE-3, R1     ; controllers 3/4: theirs, kept in ECS RAM ($47D0/$47D1)
H_GO    ADDR    R3, R1
        J       $E0E2

