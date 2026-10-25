#!/bin/bash
# jzintv_run.sh GAME_IMAGE INSTRUCTIONS OUTDIR [jzIntv flags...]
# Run jzIntv headless for INSTRUCTIONS CPU instructions (its debugger's
# "r" command counts instructions, in decimal), then save a screenshot
# (OUTDIR/shot0001.gif, 320x200) and quit. jzIntv reads GAME.cfg next to a
# raw image when one exists. Output comes from game data: OUTDIR must be
# outside any repository.
# Environment: JZINTV (binary), INTV_BIOS (folder with exec.bin, grom.bin
# and, for -s1, ECS.bin). Audio is off (-a0), speed unthrottled (-r0).
set -euo pipefail
img=${1:?IMAGE}; n=${2:?INSTRUCTIONS}; out=${3:?OUTDIR}; shift 3
: "${JZINTV:?}" "${INTV_BIOS:?}"
mkdir -p "$out"; cd "$out"; rm -f shot0001.gif
printf 'r %d\nvs\nq\n' "$n" > run.dbg
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy timeout 120 "$JZINTV" \
  -e "$INTV_BIOS/exec.bin" -g "$INTV_BIOS/grom.bin" -E "$INTV_BIOS/ECS.bin" \
  -a0 -r0 -d --script=run.dbg "$@" "$img" > jzintv.log 2>&1 || true
grep -q "Wrote screen shot" jzintv.log && echo "ok $out/shot0001.gif" || { tail -5 jzintv.log; exit 1; }
