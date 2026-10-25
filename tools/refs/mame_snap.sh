#!/bin/bash
# mame_snap.sh SYSTEM GAME_IMAGE FRAME OUTDIR
# Run the intv-only MAME headless to the end of frame FRAME and save one
# PNG snapshot in OUTDIR/snap/. Frames come from game data: OUTDIR must be
# outside any repository. Environment as for mame_trace.sh.
set -euo pipefail
sys=${1:?SYSTEM}; img=${2:?IMAGE}; frame=${3:?FRAME}; out=${4:?OUTDIR}
: "${MAME:?}" "${MAME_ROMPATH:?}" "${MAME_HASHPATH:?}"
mkdir -p "$out"; out=$(cd "$out" && pwd)
cat > "$out/snap.lua" <<LUA
local m = manager.machine
local n = 0
FRAMESUB = emu.add_machine_frame_notifier(function()
  n = n + 1
  if n == $frame then m.video:snapshot(); m:exit() end
end)
LUA
cd "$out"
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy timeout 300 "$MAME" "$sys" \
  -rompath "$MAME_ROMPATH" -hashpath "$MAME_HASHPATH" -cart "$img" \
  -autoboot_script "$out/snap.lua" -video none -sound none -nothrottle \
  -skip_gameinfo -nomouse -nojoystick -nvram_directory "$out/nvram" \
  -cfg_directory "$out/cfg" -snapshot_directory "$out/snap" \
  -seconds_to_run $(( frame / 30 + 5 )) > "$out/mame.log" 2>&1
echo "rc=$? $(find "$out/snap" -name '*.png' | head -1)"
