#!/bin/bash
# mame_cart_dump.sh CART FRAMES OUT
# Build step 8 (docs/CARTFORMATS.md 7): run a cartridge image (an Intellicart
# .rom from our own sources) in the intv-only MAME with the real EXEC for
# FRAMES frames, then write OUT/space.txt: the 65,536 words MAME's CPU reads
# at every address of its program space ("AAAA VVVV" per line, Lua
# space:read_u16, no side effects counted). MAME loads a .rom's segments
# at their addresses and skips its enable tables (slot.cpp:225-290), so
# tools/refs/cart_ref_compare.py compares only the words our map answers
# through a plain (not banked) readable window. OUT holds words read with
# the user's EXEC: keep it outside any repository. Environment as for
# mame_trace.sh.
set -euo pipefail
cart=$(realpath "${1:?CART}"); frames=${2:?FRAMES}; out=${3:?OUT}
: "${MAME:?}" "${MAME_ROMPATH:?}" "${MAME_HASHPATH:?}"
mkdir -p "$out"; out=$(cd "$out" && pwd)
cat > "$out/dump.lua" <<LUA
local m = manager.machine
local sp = m.devices[":maincpu"].spaces["program"]
local n = 0
DUMPSUB = emu.add_machine_frame_notifier(function()
  n = n + 1
  if n >= $frames then
    local f = io.open("$out/space.txt", "w")
    for a = 0, 0xFFFF do f:write(string.format("%04X %04X\n", a, sp:read_u16(a))) end
    f:close()
    m:exit()
  end
end)
LUA
cd "$out"
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy timeout 300 "$MAME" intv \
  -rompath "$MAME_ROMPATH" -hashpath "$MAME_HASHPATH" -cart "$cart" \
  -autoboot_script "$out/dump.lua" -video none -sound none -nothrottle \
  -skip_gameinfo -nomouse -nojoystick -nvram_directory "$out/nvram" \
  -cfg_directory "$out/cfg" -snapshot_directory "$out/snap" \
  -seconds_to_run $(( frames / 30 + 5 )) > "$out/mame.log" 2>&1
echo "rc=$? lines=$(wc -l < "$out/space.txt")"
