#!/bin/bash
# mame_psg.sh SYSTEM GAME_IMAGE FRAMES OUTDIR [PRESSES]
# Run the intv-only MAME on one cartridge image (or "none") for FRAMES
# frames and record the PSG (AY-3-8914 at $01F0-$01FF). PRESSES (default
# none) holds keys on both hand controllers: "F1-F2:KEY,..." presses KEY
# (MAME's field name: 0-9, Clear, Enter, Upper, Lower-Left, Lower-Right) at
# frame notifier F1 and releases it at F2 (tools/psg_compare.py --press
# does the same in the model). Output:
#   OUTDIR/psg.log    one line per CPU write to $01F0-$01FF, in order:
#                     "c=<total cycles> f=<frame> pc=<R7> W <addr> <data>"
#                     (MAME debugger watchpoint, logged with its logerror
#                     command into MAME's error.log, then filtered)
#   OUTDIR/ticks.bin  the AY-3-8914's own three output streams at its
#                     internal rate (clock / 8 = 223.7 kHz, one value per
#                     generator step: MAME ay8910.cpp device_start), taken
#                     with MAME's Lua sound hook (emu.register_sound_update,
#                     device "hook" property): 3 bytes per step, each an id
#                     of the float MAME output on that channel;
#                     OUTDIR/ticks.ids lists "id float" per line
#   OUTDIR/audio.wav  MAME's sound output, 48 kHz (-wavwrite)
# tools/psg_compare.py compares both with tools/psg.py. Everything here is
# derived from game data: OUTDIR must be outside any repository.
#
# Environment: MAME, MAME_ROMPATH, MAME_HASHPATH as for mame_trace.sh.
# MAME debugger commands used (issued from Lua, since "-debugger none" does
# not run a -debugscript): wpset, logerror, g (MAME docs,
# docs/source/debugger/; MAME is BSD-3).
set -euo pipefail
sys=${1:?SYSTEM}; img=${2:?IMAGE}; frames=${3:?FRAMES}; out=${4:?OUTDIR}; presses=${5:-}
lp=""
IFS=',' read -ra pp <<< "$presses"
for p in "${pp[@]}"; do
  [ -n "$p" ] || continue
  f1=${p%%-*}; r=${p#*-}; f2=${r%%:*}; key=${r#*:}
  lp="$lp{$f1,$f2,\"$key\"},"
done
: "${MAME:?}" "${MAME_ROMPATH:?}" "${MAME_HASHPATH:?}"
mkdir -p "$out"; out=$(cd "$out" && pwd)
rm -f "$out/psg.log" "$out/error.log" "$out/audio.wav"
cat > "$out/psg.lua" <<LUA
-- psg lane: log every CPU write to the PSG, stop after $frames frames
local m = manager.machine
local d = m.debugger
d:command([[wpset 1f0,10,w,1,{logerror "PSGW c=%d f=%d pc=%04X W %04X %04X\\n",totalcycles,frame,r7,wpaddr,wpdata; g}]])
d:command("g")
local press = {$lp}
local pads = {}
for _, t in ipairs({":iopt_right_ctrl:handctrl:KEYPAD", ":iopt_left_ctrl:handctrl:KEYPAD"}) do
  pads[#pads + 1] = m.ioport.ports[t]
end
local ids, nid = {}, 0
local tf = io.open("$out/ticks.bin", "wb")
local idf = io.open("$out/ticks.ids", "w")
m.sounds[":ay8914"].hook = true
SOUNDSUB = emu.register_sound_update(function(t)
  local ch = t[":ay8914"]
  if not ch then return end
  local a, b, c = ch[1], ch[2], ch[3]
  local out = {}
  for i = 1, #a do
    local s = ""
    for _, x in ipairs({a[i], b[i], c[i]}) do
      local k = ids[x]
      if not k then k = nid; ids[x] = k; nid = nid + 1; idf:write(string.format("%d %.9g\n", k, x)) end
      out[#out + 1] = k
    end
  end
  for i = 1, #out, 4096 do
    tf:write(string.char(table.unpack(out, i, math.min(i + 4095, #out))))
  end
end)
local n = 0
FRAMESUB = emu.add_machine_frame_notifier(function()
  n = n + 1
  for _, p in ipairs(press) do
    if n == p[1] or n == p[2] then
      for _, port in ipairs(pads) do port.fields[p[3]]:set_value(n == p[1] and 1 or 0) end
    end
  end
  if n >= $frames then tf:close(); idf:close(); print(string.format("PSGEND frames=%d time=%.6f", n, m.time:as_double())); m:exit() end
end)
LUA
cart=(-cart "$img")
[ "$img" = none ] && cart=()
cd "$out"
rc=0
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy timeout 900 "$MAME" "$sys" \
  -rompath "$MAME_ROMPATH" -hashpath "$MAME_HASHPATH" "${cart[@]}" \
  -debug -debugger none -log -autoboot_script "$out/psg.lua" -video none -sound none \
  -samplerate 48000 -wavwrite "$out/audio.wav" -nothrottle \
  -skip_gameinfo -nomouse -nojoystick -nvram_directory "$out/nvram" \
  -cfg_directory "$out/cfg" -snapshot_directory "$out/snap" \
  -seconds_to_run $(( frames / 30 + 5 )) > "$out/mame.log" 2>&1 || rc=$?
grep '^PSGW ' "$out/error.log" | cut -c6- > "$out/psg.log" || true
echo "rc=$rc writes=$(wc -l < "$out/psg.log") wav=$(stat -c %s "$out/audio.wav" 2>/dev/null || echo none)"
