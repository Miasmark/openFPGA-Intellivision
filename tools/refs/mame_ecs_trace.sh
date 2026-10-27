#!/bin/bash
# mame_ecs_trace.sh SYSTEM GAME_IMAGE FRAMES OUTDIR [PRESSES] [-- MAME ARGS...]
# The ECS references (build step 9): mame_trace.sh's per-instruction trace
# (OUTDIR/trace.log, same format: tools/intv_system.py mame reads it) of
# the intv-only MAME, with keys held as the model holds them
# (tools/intv_system.py parse_presses, "F1-F2:KEY,..."): hand-controller
# keys by MAME field name on both controllers (as mame_psg.sh), "ecs:K1+K2"
# ECS keyboard keys (tools/ecs.py KEYPOS: row r = MAME port ROW.r, column c
# = bit c; ecs_ctrl.cpp) and "synth:N1+N2" synthesizer keys (note n = port
# SYNTH.(n / 8) bit n % 8, C6 = SYNTH.6 bit 7), each set at frame notifier
# F1 and released at F2. SNAPS (environment, optional): frame notifiers at
# which to save a snapshot (OUTDIR/snap/<system>/NNNN.png in order).
# GAME_IMAGE "none" runs with an empty slot; "sl:NAME" loads softlist entry
# NAME (MAME_ROMPATH_EXTRA is added to the ROM path: WSMLB's four pieces).
# MAME ARGS go to MAME (e.g. -ecs:ctrl_port synth). Traces come from game
# data and the owner's ROMs: OUTDIR must be outside any repository.
#
# Environment: MAME, MAME_ROMPATH, MAME_HASHPATH (as mame_trace.sh).
# MAME debugger commands used (from Lua): trace, tracelog, wpset, g,
# traceflush (MAME docs, docs/source/debugger/; MAME is BSD-3).
set -euo pipefail
sys=${1:?SYSTEM}; img=${2:?IMAGE}; frames=${3:?FRAMES}; out=${4:?OUTDIR}; presses=${5-}
shift 4; [ $# -gt 0 ] && [ "$1" != "--" ] && shift; [ "${1-}" = "--" ] && shift
: "${MAME:?}" "${MAME_ROMPATH:?}" "${MAME_HASHPATH:?}"
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$out"; out=$(cd "$out" && pwd)
rm -f "$out/trace.log"
if [ -n "${SNAPS:-}" ] && [ -e "$out/snap" ]; then echo "$out/snap exists: use a new OUTDIR" >&2; exit 2; fi
lp=$(python3 -I - "$here/.." "$presses" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import intv_system as s
out = []
for f1, f2, code in s.parse_presses(sys.argv[2]):
    if isinstance(code, tuple) and code[0] == "ecs":
        bits, synth = code[1], False
        # synth presses are written "synth:" in the text; the bits are the same matrix
        for b in range(64):
            if bits >> b & 1:
                out.append('{%d,%d,"M",%d,%d}' % (f1, f2, b // 8, 1 << (b % 8)))
    elif isinstance(code, tuple):
        raise SystemExit("pocket: presses are not supported here")
    else:
        name = [k for k, v in s.KEYCODE.items() if v == code][0]
        out.append('{%d,%d,"H","%s"}' % (f1, f2, name))
print(",".join(out))
PY
)
synth=0
case " $* " in *" synth "*) synth=1 ;; esac
cat > "$out/trace.lua" <<LUA
-- step 9: per-instruction trace with bus accesses and held keys, stop after $frames frames
local m = manager.machine
local d = m.debugger
d:command([[trace $out/trace.log,maincpu,noloop,{tracelog "c=%d f=%d y=%d R=%04X %04X %04X %04X %04X %04X %04X %04X F=%02X ",totalcycles,frame,beamy,r0,r1,r2,r3,r4,r5,r6,r7,curflags}]])
d:command([[wpset 0,10000,r,1,{tracelog "  R %04X %04X\\n",wpaddr,wpdata; g}]])
d:command([[wpset 0,10000,w,1,{tracelog "  W %04X %04X\\n",wpaddr,wpdata; g}]])
d:command("g")
local press = {$lp}
local snaps = {}
for v in string.gmatch("${SNAPS:-}", "%d+") do snaps[tonumber(v)] = true end
local digital = false
for _, p in ipairs(press) do
  if p[3] == "H" and not ({["0"]=1,["1"]=1,["2"]=1,["3"]=1,["4"]=1,["5"]=1,["6"]=1,["7"]=1,["8"]=1,["9"]=1,
           Clear=1, Enter=1, Upper=1, ["Lower-Left"]=1, ["Lower-Right"]=1})[p[4]] then digital = true end
end
local pads = {}
for _, c in ipairs({":iopt_right_ctrl:handctrl:", ":iopt_left_ctrl:handctrl:"}) do
  if digital then m.ioport.ports[c .. "OPTIONS"].fields["Controller Disc Emulation"].user_value = 0 end
  pads[#pads + 1] = {m.ioport.ports[c .. "KEYPAD"], m.ioport.ports[c .. "DISC_DG"]}
end
local mtag = ($synth == 1) and ":ecs:ctrl_port:synth:SYNTH." or ":ecs:ctrl_port:keybd:ROW."
local held = {}
local n = 0
FRAMESUB = emu.add_machine_frame_notifier(function()
  n = n + 1
  for _, p in ipairs(press) do
    if n == p[1] or n == p[2] then
      local on = (n == p[1]) and 1 or 0
      if p[3] == "H" then
        for _, pp in ipairs(pads) do
          local f = pp[1].fields[p[4]] or pp[2].fields[p[4]]
          f:set_value(on)
        end
      else
        local port = m.ioport.ports[mtag .. p[4]]
        local f = port and port:field(p[5])
        if f then f:set_value(on) else print("NOFIELD " .. mtag .. p[4] .. " " .. p[5]) end
      end
    end
  end
  if snaps[n] then m.video:snapshot() end
  if n >= $frames then d:command("traceflush"); m:exit() end
end)
LUA
case "$img" in
  none) cart=() ;;
  sl:*) cart=(-cart "${img#sl:}") ;;
  *)    cart=(-cart "$img") ;;
esac
rp=$MAME_ROMPATH; [ -n "${MAME_ROMPATH_EXTRA:-}" ] && rp="$rp;$MAME_ROMPATH_EXTRA"
cd "$out"
rc=0
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy timeout "${MAME_TIMEOUT:-3600}" "$MAME" "$sys" \
  -rompath "$rp" -hashpath "$MAME_HASHPATH" "${cart[@]}" "$@" \
  -debug -debugger none -autoboot_script "$out/trace.lua" -video none -sound none -nothrottle \
  -skip_gameinfo -nomouse -nojoystick -nvram_directory "$out/nvram" \
  -cfg_directory "$out/cfg" -snapshot_directory "$out/snap" \
  -seconds_to_run $(( frames / 30 + 10 )) > "$out/mame.log" 2>&1 || rc=$?
echo "rc=$rc lines=$(wc -l < "$out/trace.log") snaps=$(find "$out/snap" -name '*.png' 2>/dev/null | wc -l)"
