#!/bin/bash
# mame_voice.sh SYSTEM GAME_IMAGE FRAMES OUTDIR [PRESSES]
# Build step 10: run the intv-only MAME with the Intellivoice on one cartridge image for FRAMES
# frames and record (SYSTEM intvoice: the Intellivoice expansion with the game in its slot, the
# SP0256 at $0080-$0081 (MAME intv.cpp:308) as sound device :voice:sp0256_speech; intvecs: the ECS
# with the SP0256 built in at $0080-$0081 (intv.cpp:363) as :speech, set SPEECH=:speech)
#   OUTDIR/voice.log   one line per CPU access to $0080-$0081, in order:
#                      "c=<total cycles> f=<frame> pc=<R7> W|R <addr> <data>" (MAME debugger
#                      watchpoints, logged with logerror into error.log, then filtered)
#   OUTDIR/voice_t.log the same accesses with MAME's machine time ("<s>.<attoseconds> W|R addr data",
#                      Lua memory taps): the time MAME's sound stream sees (the cycle count above is
#                      not: the two drift apart by a few samples across frames)
#   OUTDIR/voice.bin   the SP0256's own output stream at its own rate (3.12 MHz / 312 = 10 kHz,
#                      MAME sp0256.cpp CLOCK_DIVIDER), taken with the Lua sound hook
#                      (emu.register_sound_update): one little-endian int16 per sample, the
#                      float MAME carries times 32768 (sp0256.cpp puts int16 values / 32768)
#   OUTDIR/voice.info  sample count, frames, MAME time at the end
# PRESSES as in mame_ecs_trace.sh (tools/intv_system.py parse_presses: hand-controller keys and "ecs:" keys). GAME_IMAGE "sl:NAME" loads a softlist entry (WSMLB: sl:wsmlbase), "none"
# no cartridge. EXEC=PROG.bin (environment, optional) runs one of our programs in the EXEC slot, as
# mame_exec_prog.sh does (OUTDIR/rompath: links to MAME_ROMPATH's files, exec.bin replaced; MAME
# reports the wrong checksum and runs it): sim/testroms/voicetest.py's program.
# STATE=1 (environment, optional) adds the SP0256's state to every line of voice_t.log.
# tools/sp0256.py compare plays voice.log through the model and compares it with voice.bin.
# Everything here is derived from game data: OUTDIR must be outside any repository.
# Environment: MAME, MAME_ROMPATH, MAME_HASHPATH as for mame_trace.sh. MAME is BSD-3; the
# debugger commands (wpset, logerror, g) and the Lua API are MAME's documented interfaces.
set -euo pipefail
sys=${1:?SYSTEM}; img=${2:?IMAGE}; frames=${3:?FRAMES}; out=${4:?OUTDIR}; presses=${5:-}
here=$(cd "$(dirname "$0")" && pwd)
lp=$(python3 -I - "$here/.." "$presses" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import intv_system as s
out = []
for f1, f2, code in s.parse_presses(sys.argv[2]):
    if isinstance(code, tuple) and code[0] == "ecs":
        for b in range(64):
            if code[1] >> b & 1:
                out.append('{%d,%d,"M",%d,%d}' % (f1, f2, b // 8, 1 << (b % 8)))
    elif isinstance(code, tuple):
        raise SystemExit("pocket: presses are not supported here")
    else:
        out.append('{%d,%d,"H","%s"}' % (f1, f2, [k for k, v in s.KEYCODE.items() if v == code][0]))
print(",".join(out))
PY
)
: "${MAME:?}" "${MAME_ROMPATH:?}" "${MAME_HASHPATH:?}"
mkdir -p "$out"; out=$(cd "$out" && pwd)
rm -f "$out/voice.log" "$out/voice_t.log" "$out/error.log" "$out/voice.bin" "$out/voice.info"
cat > "$out/voice.lua" <<LUA
-- voice lane: log every CPU access to the SPB640, record the SP0256 stream, stop after $frames frames
local m = manager.machine
local d = m.debugger
d:command([[wpset 80,2,w,1,{logerror "VOXW c=%d f=%d pc=%04X W %04X %04X\\n",totalcycles,frame,r7,wpaddr,wpdata; g}]])
d:command([[wpset 80,2,r,1,{logerror "VOXR c=%d f=%d pc=%04X R %04X %04X\\n",totalcycles,frame,r7,wpaddr,wpdata; g}]])
d:command("g")
-- the machine time of every access (scheduler time = the executing CPU's local time, the time
-- MAME's sound stream update uses: sound.cpp get_current_sample_index), via Lua memory taps
local vt = io.open("$out/voice_t.log", "w")
local sp = m.devices[":maincpu"].spaces["program"]
-- STATE=1: append the SP0256's own state at each access (MAME save-state items, read through the
-- documented Lua item API): pc (bit address), halted, lrq, filter repeat count and period counter.
-- A read tap runs after the handler, which has brought the stream up to the access time first.
local st = {}
if ${STATE:-0} ~= 0 then
  local its = m.devices["${SPEECH:-:voice:sp0256_speech}"].items
  for _, k in ipairs({"m_pc", "m_halted", "m_lrq", "m_filt.rpt", "m_filt.cnt", "m_stack"}) do
    st[#st + 1] = emu.item(its["0/" .. k])
  end
end
local function stamp(kind, offset, data)
  local t = m.time
  local s = ""
  for _, it in ipairs(st) do s = s .. " " .. tostring(it:read(0)) end
  vt:write(string.format("%d.%018d %s %04X %04X%s\n", t.seconds, t.attoseconds, kind, offset, data, s))
end
WTAP = sp:install_write_tap(0x80, 0x81, "voxw", function(offset, data, mask) stamp("W", offset, data) end)
RTAP = sp:install_read_tap(0x80, 0x81, "voxr", function(offset, data, mask) stamp("R", offset, data); return data end)
local press = {$lp}
local pads = {}
local digital = false
for _, p in ipairs(press) do
  if p[3] == "H" and not ({["0"]=1,["1"]=1,["2"]=1,["3"]=1,["4"]=1,["5"]=1,["6"]=1,["7"]=1,["8"]=1,["9"]=1,
           Clear=1, Enter=1, Upper=1, ["Lower-Left"]=1, ["Lower-Right"]=1})[p[4]] then digital = true end
end
for _, c in ipairs({":iopt_right_ctrl:handctrl:", ":iopt_left_ctrl:handctrl:"}) do
  local o = m.ioport.ports[c .. "OPTIONS"]
  if digital and o then o.fields["Controller Disc Emulation"].user_value = 0 end
  local k = m.ioport.ports[c .. "KEYPAD"]
  if k then pads[#pads + 1] = {k, m.ioport.ports[c .. "DISC_DG"]} end
end
local tf = io.open("$out/voice.bin", "wb")
local nsamp = 0
m.sounds["${SPEECH:-:voice:sp0256_speech}"].hook = true
SOUNDSUB = emu.register_sound_update(function(t)
  local ch = t["${SPEECH:-:voice:sp0256_speech}"]
  if not ch then return end
  local a = ch[1]
  local buf = {}
  for i = 1, #a do
    local v = math.floor(a[i] * 32768 + 0.5)
    if v < 0 then v = v + 65536 end
    buf[#buf + 1] = string.char(v & 0xFF, (v >> 8) & 0xFF)
    if #buf >= 4096 then tf:write(table.concat(buf)); buf = {} end
  end
  tf:write(table.concat(buf))
  nsamp = nsamp + #a
end)
local n = 0
FRAMESUB = emu.add_machine_frame_notifier(function()
  n = n + 1
  for _, p in ipairs(press) do
    if n == p[1] or n == p[2] then
      local on = (n == p[1]) and 1 or 0
      if p[3] == "H" then
        for _, pp in ipairs(pads) do
          local f = pp[1].fields[p[4]] or (pp[2] and pp[2].fields[p[4]])
          if f then f:set_value(on) end
        end
      else                              -- ECS keyboard (row, column bit), as mame_ecs_trace.sh
        local port = m.ioport.ports[":ecs:ctrl_port:keybd:ROW." .. p[4]]
        local f = port and port:field(p[5])
        if f then f:set_value(on) else print("NOFIELD ROW." .. p[4] .. " " .. p[5]) end
      end
    end
  end
  if n >= $frames then
    tf:close(); vt:close()
    local inf = io.open("$out/voice.info", "w")
    inf:write(string.format("samples %d\nframes %d\ntime %.9f\n", nsamp, n, m.time:as_double()))
    inf:close()
    m:exit()
  end
end)
LUA
cart=(-cart "$img")
[ "$img" = none ] && cart=()
case "$img" in sl:*) cart=(-cart "${img#sl:}") ;; esac
base=$MAME_ROMPATH
if [ -n "${EXEC:-}" ]; then
  prog=$(realpath "$EXEC")
  mkdir -p "$out/rompath/intv"
  for f in "$MAME_ROMPATH"/intv/*; do
    [ "$(basename "$f")" = exec.bin ] || ln -sfn "$(realpath "$f")" "$out/rompath/intv/"
  done
  cp -f "$prog" "$out/rompath/intv/exec.bin"
  for d in intvoice intvecs; do ln -sfn intv "$out/rompath/$d"; done
  base=$out/rompath
fi
rp="$base${MAME_ROMPATH_EXTRA:+;$MAME_ROMPATH_EXTRA}"
cd "$out"
rc=0
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy timeout 1800 "$MAME" "$sys" \
  -rompath "$rp" -hashpath "$MAME_HASHPATH" "${cart[@]}" \
  -debug -debugger none -log -autoboot_script "$out/voice.lua" -video none -sound none \
  -nothrottle -skip_gameinfo -nomouse -nojoystick -nvram_directory "$out/nvram" \
  -cfg_directory "$out/cfg" -seconds_to_run $(( frames / 30 + 10 )) > "$out/mame.log" 2>&1 || rc=$?
grep -E '^VOX[WR] ' "$out/error.log" | cut -c6- > "$out/voice.log" || true
echo "rc=$rc accesses=$(wc -l < "$out/voice.log") writes=$(grep -c ' W ' "$out/voice.log" || true) samples=$(( $(stat -c %s "$out/voice.bin" 2>/dev/null || echo 0) / 2 ))"
