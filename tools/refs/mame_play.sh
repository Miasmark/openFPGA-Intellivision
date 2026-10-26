#!/bin/bash
# mame_play.sh GAME_IMAGE FRAMES PRESSES STEP OUTDIR
# The MAME side of the scripted-input bench (sim/tb/tb_system.py --play):
# one MAME run (tools/refs/mame_psg.sh) of the cartridge for FRAMES frames
# with PRESSES held on both hand controllers ("F1-F2:KEY,..."), recording
# the PSG writes, MAME's AY-3-8914 stream and audio, and a snapshot at every
# STEP-th frame notifier. The snapshots are imported as OUTDIR/frames/fN.pgm
# (MAME's palette read from its intv.cpp, tools/stic_frames.py import), the
# reference tools/stic_frames.py compare --press and tools/psg_compare.py
# --press check the model (mode mame) against. OUTDIR must be new and
# outside any repository (everything in it is derived from the game).
# Environment: MAME, MAME_ROMPATH, MAME_HASHPATH as for mame_trace.sh, and
# MAME_SRC (MAME's source tree, for src/mame/mattel/intv.cpp).
set -euo pipefail
img=${1:?IMAGE}; frames=${2:?FRAMES}; presses=${3:?PRESSES}; step=${4:?STEP}; out=${5:?OUTDIR}
: "${MAME_SRC:?}"
here=$(cd "$(dirname "$0")" && pwd)
[ -e "$out" ] && { echo "$out exists: use a new OUTDIR" >&2; exit 2; }
mkdir -p "$out"; out=$(cd "$out" && pwd)
snaps=$(seq -s, "$step" "$step" "$frames")
SNAPS=$snaps "$here/mame_psg.sh" intv "$img" "$frames" "$out" "$presses"
mapfile -t pngs < <(find "$out/snap" -name '*.png' | sort)
IFS=, read -ra want <<< "$snaps"
if [ "${#pngs[@]}" -ne "${#want[@]}" ]; then
  echo "MAME_PLAY FAIL: ${#pngs[@]} snapshots, want ${#want[@]}" >&2; exit 1
fi
mkdir -p "$out/png"
for i in "${!want[@]}"; do mv "${pngs[$i]}" "$out/png/f${want[$i]}.png"; done
python3 -I "$here/../stic_frames.py" import --mame-src "$MAME_SRC/src/mame/mattel/intv.cpp" \
  --out "$out/frames" "$out/png"/f*.png
echo "MAME_PLAY done: ${#want[@]} snapshots, $(wc -l < "$out/psg.log") PSG writes"
