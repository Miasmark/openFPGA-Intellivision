#!/bin/bash
# mame_exec_prog.sh PROG_BIN FRAMES OUT [WORDS]
# Run one of our own test programs (sim/testroms, assembled for the EXEC
# slot: 8 KiB, the layout of exec.bin, as sim/tb/tb_system.py writes it to
# WORK/<image>_exec.bin) in the intv-only MAME in place of the EXEC, with
# no cartridge, for FRAMES frames. OUT/rompath is a copy of MAME_ROMPATH
# (links) whose intv/exec.bin is PROG_BIN; MAME reports its wrong checksum
# and runs it. Every frame OUT/words.log gets the program's System RAM
# words at the addresses WORDS (comma-separated hex, default sticmob.asm's:
# 300 frame, 303 fails, 305 last fail frame, 306 passes, 30A/30B failed-
# scene mask). The rompath holds the user's BIOS files: OUT must be
# outside any repository. Environment as for mame_trace.sh.
set -euo pipefail
prog=$(realpath "${1:?PROG_BIN}"); frames=${2:?FRAMES}; out=${3:?OUT}
words=${4:-300,303,305,306,30A,30B}
: "${MAME:?}" "${MAME_ROMPATH:?}" "${MAME_HASHPATH:?}"
mkdir -p "$out/rompath/intv"; out=$(cd "$out" && pwd)
for f in "$MAME_ROMPATH"/intv/*; do
  [ "$(basename "$f")" = exec.bin ] || ln -sfn "$(realpath "$f")" "$out/rompath/intv/"
done
cp -f "$prog" "$out/rompath/intv/exec.bin"
for d in intvoice intvecs intv_ecs intv_voice stic; do ln -sfn intv "$out/rompath/$d"; done
lw=$(echo "$words" | sed 's/\([0-9A-Fa-f]\+\)/0x\1/g')
cat > "$out/words.lua" <<LUA
local m = manager.machine
local sp = m.devices[":maincpu"].spaces["program"]
local f = io.open("$out/words.log", "w")
local at = {$lw}
local n = 0
FRAMESUB = emu.add_machine_frame_notifier(function()
  n = n + 1
  local s = string.format("frame %d:", n)
  for _, a in ipairs(at) do s = s .. string.format(" %04X=%04X", a, sp:read_u16(a)) end
  f:write(s .. "\n")
  if n >= $frames then f:close(); m:exit() end
end)
LUA
cd "$out"
rc=0
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy timeout 300 "$MAME" intv \
  -rompath "$out/rompath" -hashpath "$MAME_HASHPATH" \
  -autoboot_script "$out/words.lua" -video none -sound none -nothrottle \
  -skip_gameinfo -nomouse -nojoystick -nvram_directory "$out/nvram" \
  -cfg_directory "$out/cfg" -snapshot_directory "$out/snap" \
  -seconds_to_run $(( frames / 30 + 5 )) > "$out/mame.log" 2>&1 || rc=$?
echo "rc=$rc $(tail -1 "$out/words.log")"
