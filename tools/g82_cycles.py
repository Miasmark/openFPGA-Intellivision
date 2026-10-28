#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Microcycles per instruction as General Instrument's CP1600/CP1610 Microprocessor
Data Manual (1982; G82 in docs/CPU_NOTES.md) gives them: the summary listing on p.45
and the double byte data listings on p.52-53. Our own transcription of those facts,
kept apart from tools/cp1610.py and from run_cpu_tests.py's doc_cycles (S1 and the
wiki), so the opcode sweep can hold the model against a third source.

  g82_cycles(op, taken=False, sdbd=False)   cycles of opcode op (10 bits); taken
                                            for a branch whose condition holds;
                                            sdbd for an instruction after SDBD
                                            (the instruction's own cycles: G82
                                            gives the pair, SDBD's 4 included)
"""


def g82_cycles(op, taken=False, sdbd=False):
    if op == 0x004:
        return 12                     # J, JE, JD, JSR, JSRE, JSRD
    if op < 0x008:
        return 4                      # HLT SDBD EIS DIS TCI CLRC SETC
    if op < 0x040:
        return 6                      # INCR ... RSWD (single register)
    if op < 0x080:
        return 6 + (2 if op & 4 else 0)   # shifts: "add two cycles for 2-position shift"
    if op < 0x200:
        o, s, d = op >> 6, (op >> 3) & 7, op & 7
        if o == 2:                    # MOVR, TSTR (MOVR to itself), JR (MOVR to PC): 6/7
            return 7 if d >= 6 else 6
        return 6                      # ADDR SUBR CMPR ANDR XORR CLRR
    if op < 0x240:
        if op & 0x1F == 0x00:
            return 9                  # B: 9*
        if op & 0x1F == 0x08:
            return 7                  # NOPP: 7*
        return 9 if taken else 7      # "add 2 cycles if test condition is true"
    o, m = (op >> 6) & 7, (op >> 3) & 7
    if sdbd and m != 0 and o != 1:
        return 14 - 4                 # p.52-53: SDBD + MVII/ADDI.., SDBD + MVI@/ADD@..: 14
    if o == 1:                        # MVO: Dir 11, Imm 9, Indir 9, Stack (PSHR) 9
        return 11 if m == 0 else 9
    if m == 0:
        return 10                     # MVI, ADD, SUB, CMP, AND, XOR: Dir 10
    if m == 6:
        return 11                     # Stack (PULR = MVI@ R6)
    return 8                          # Imm (R7), Indir (R1-R5)
