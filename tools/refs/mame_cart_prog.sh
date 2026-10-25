#!/bin/bash
# mame_cart_prog.sh CART_BIN FRAMES OUT [WORDS] [SNAPS]
# Run one of our own test programs built as a cartridge (e.g. the image of
# sim/testroms/sticmob_cart.py) in the intv-only MAME with the real EXEC,
# for FRAMES frames. Every frame OUT/words.log gets the System RAM words at
# the addresses WORDS (comma-separated hex, default sticmob.asm's: 300
# frame, 303 fails, 305 last fail frame, 306 passes, 30A/30B failed-scene
# mask) and the word at $0100/$0101 (the EXEC's ISR vector, to see when
# the program takes over); OUT/coll.log gets every CPU read of the
# collision registers $18-$1F with the frame and the word at $0308
# (sticmob's scene being compared); at the frames SNAPS (comma-separated, default
# none) a PNG goes to OUT/snap/. OUT holds frames of the user's BIOS: it
# must be outside any repository. Environment as for mame_trace.sh.
set -euo pipefail
cart=$(realpath "${1:?CART_BIN}"); frames=${2:?FRAMES}; out=${3:?OUT}
words=${4:-300,303,305,306,30A,30B}; snaps=${5:-}
: "${MAME:?}" "${MAME_ROMPATH:?}" "${MAME_HASHPATH:?}"
mkdir -p "$out"; out=$(cd "$out" && pwd)
lw=$(echo "$words" | sed 's/\([0-9A-Fa-f]\+\)/0x\1/g')
cat > "$out/words.lua" <<LUA
local m = manager.machine
local sp = m.devices[":maincpu"].spaces["program"]
local f = io.open("$out/words.log", "w")
local at = {$lw}
local snap = {}
for _, s in ipairs({$snaps}) do snap[s] = true end
local n = 0
local c = io.open("$out/coll.log", "w")
COLLTAP = sp:install_read_tap(0x18, 0x1F, "coll", function(offset, data, mask)
  c:write(string.format("frame %d scene %d %02X %04X\n", n + 1, sp:read_u16(0x308), offset, data))
end)
FRAMESUB = emu.add_machine_frame_notifier(function()
  n = n + 1
  local s = string.format("frame %d: vec=%04X", n,
    (sp:read_u16(0x100) & 0xFF) | ((sp:read_u16(0x101) & 0xFF) << 8))
  for _, a in ipairs(at) do s = s .. string.format(" %04X=%04X", a, sp:read_u16(a)) end
  f:write(s .. "\n")
  if snap[n] then m.video:snapshot() end
  if n >= $frames then f:close(); c:close(); m:exit() end
end)
LUA
cd "$out"
rc=0
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy timeout 300 "$MAME" intv \
  -rompath "$MAME_ROMPATH" -hashpath "$MAME_HASHPATH" -cart "$cart" \
  -autoboot_script "$out/words.lua" -video none -sound none -nothrottle \
  -skip_gameinfo -nomouse -nojoystick -nvram_directory "$out/nvram" \
  -cfg_directory "$out/cfg" -snapshot_directory "$out/snap" \
  -seconds_to_run $(( frames / 30 + 5 )) > "$out/mame.log" 2>&1 || rc=$?
echo "rc=$rc $(tail -1 "$out/words.log")"
