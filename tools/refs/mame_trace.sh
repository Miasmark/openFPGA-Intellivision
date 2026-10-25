#!/bin/bash
# mame_trace.sh SYSTEM GAME_IMAGE FRAMES OUTDIR
# GAME_IMAGE "none" runs the system with an empty cartridge slot.
# Run the intv-only MAME on one cartridge image for FRAMES frames and write
# OUTDIR/trace.log: one line per CP1610 instruction (total cycles, frame,
# beam line, R0-R7, S/Z/O/C flags, PC and disassembly), each followed by
# the bus accesses that instruction made ("  R addr data" / "  W addr data",
# instruction fetches included), and MAME's "(interrupted at ...)" lines
# where INTRM is taken. tools/refs/trace_summary.py checks and summarises it.
# Traces are derived from game data: OUTDIR must be outside any repository.
#
# Environment: MAME (binary), MAME_ROMPATH (from setup_mame_rompath.sh),
# MAME_HASHPATH (MAME's hash/, for intv.hsi: MAME maps a raw .int by it).
# MAME debugger commands used (issued from Lua): trace, tracelog, wpset (MAME docs,
# docs/source/debugger/; MAME is BSD-3).
set -euo pipefail
sys=${1:?SYSTEM}; img=${2:?IMAGE}; frames=${3:?FRAMES}; out=${4:?OUTDIR}
: "${MAME:?}" "${MAME_ROMPATH:?}" "${MAME_HASHPATH:?}"
mkdir -p "$out"; out=$(cd "$out" && pwd)
rm -f "$out/trace.log"
# The commands go through Lua: with "-debugger none" MAME does not run a
# -debugscript, but manager.machine.debugger:command() works.
cat > "$out/trace.lua" <<LUA
-- refs lane: per-instruction trace with bus accesses, stop after $frames frames
local m = manager.machine
local d = m.debugger
d:command([[trace $out/trace.log,maincpu,noloop,{tracelog "c=%d f=%d y=%d R=%04X %04X %04X %04X %04X %04X %04X %04X F=%02X ",totalcycles,frame,beamy,r0,r1,r2,r3,r4,r5,r6,r7,curflags}]])
d:command([[wpset 0,10000,r,1,{tracelog "  R %04X %04X\\n",wpaddr,wpdata; g}]])
d:command([[wpset 0,10000,w,1,{tracelog "  W %04X %04X\\n",wpaddr,wpdata; g}]])
d:command("g")
local n = 0
FRAMESUB = emu.add_machine_frame_notifier(function()
  n = n + 1
  if n >= $frames then d:command("traceflush"); m:exit() end
end)
LUA
cart=(-cart "$img")
[ "$img" = none ] && cart=()
cd "$out"
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy timeout 600 "$MAME" "$sys" \
  -rompath "$MAME_ROMPATH" -hashpath "$MAME_HASHPATH" "${cart[@]}" \
  -debug -debugger none -autoboot_script "$out/trace.lua" -video none -sound none -nothrottle \
  -skip_gameinfo -nomouse -nojoystick -nvram_directory "$out/nvram" \
  -cfg_directory "$out/cfg" -snapshot_directory "$out/snap" \
  -seconds_to_run $(( frames / 30 + 5 )) > "$out/mame.log" 2>&1
echo "rc=$? lines=$(wc -l < "$out/trace.log")"
