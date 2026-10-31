#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""ibjlp.py: a JLP cartridge built the way IntyBASIC games are (docs/JLP_NOTES.md 4, T12): our own
small IntyBASIC program, compiled with --jlp by the user's IntyBASIC and assembled by as1600 (both
run as tools; their output is ours, built, never committed). It uses JLP RAM for its variables, the
multiply / divide accelerators for * / %, and the flash through IntyBASIC's runtime (FLASH INIT,
ERASE, WRITE, READ with its System RAM wait loop), then shows the results. tb_system runs it RTL =
model; jzIntv runs it as a black box (tools/refs/jzintv_jlp_run.sh).

  ibjlp.py OUTDIR      -> OUTDIR/ibjlp.bin, ibjlp.cfg
Environment: INTYBASIC (the compiler), INTYBASIC_LIB (its library directory), AS1600.
"""
import os
import subprocess
import sys

SRC = r"""
	REM ibjlp: JLP RAM, the accelerators and the flash through IntyBASIC's runtime
	FLASH INIT SIZE 2
	DIM #row(96)
	#first = FLASH.FIRST
	#last = FLASH.LAST
	FOR c = 0 TO 95
		#row(c) = c * 37 + 5
	NEXT c
	FLASH ERASE #first
	FLASH WRITE #first + 1, VARPTR #row(0)
	FOR c = 0 TO 95
		#row(c) = 0
	NEXT c
	FLASH READ #first + 1, VARPTR #row(0)
	#sum = 0
	FOR c = 0 TO 95
		#sum = #sum + #row(c)
	NEXT c
	#a = 1234
	#b = 56
	#m = #a * #b
	#d = #a / #b
	#r = #a % #b
	#n = 0
	FOR c = 1 TO 50
		#n = #n + (#a / c) + (#b * c) % 7
	NEXT c
	PRINT AT 0, <>#first, " ", <>#last
	PRINT AT 20, <>#sum, " ", <>#row(95)
	PRINT AT 40, <>#m, " ", <>#d, " ", <>#r
	PRINT AT 60, <>#n
loop:	WAIT
	GOTO loop
"""


def build(out):
    ib = os.environ.get('INTYBASIC', '/home/miasmark/pocket_projects/intellivision/tools-ext/IntyBASIC/intybasic')
    lib = os.environ.get('INTYBASIC_LIB', os.path.dirname(ib))
    asm = os.environ.get('AS1600', '/home/miasmark/daria_work/intv/refs/jzintv/src-tree/jzintv-20200712-src/bin/as1600')
    os.makedirs(out, exist_ok=True)
    bas, src = os.path.join(out, 'ibjlp.bas'), os.path.join(out, 'ibjlp.asm')
    with open(bas, 'w') as f:
        f.write(SRC)
    subprocess.run([ib, '--jlp', '--title', 'IBJLP', bas, src, lib], check=True, cwd=out,
                   stdout=subprocess.DEVNULL)
    subprocess.run([asm, '-o', os.path.join(out, 'ibjlp'), '-l', os.path.join(out, 'ibjlp.lst'), src],
                   check=True, cwd=out, stdout=subprocess.DEVNULL)
    return os.path.join(out, 'ibjlp.bin'), os.path.join(out, 'ibjlp.cfg')


if __name__ == '__main__':
    print(*build(sys.argv[1]))
