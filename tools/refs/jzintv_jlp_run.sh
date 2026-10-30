#!/bin/bash
# jzintv_jlp_run.sh BIN CFG OUT [CYCLES_HEX]
# Build step 11 (docs/JLP_NOTES.md 4): a JLP measurement cartridge (sim/testroms/jlp) on
# jzIntv (GPL, run as a program only, a black box: its documentation is our specification, its
# code is never read). It runs CYCLES_HEX CPU cycles (default $100000, about 70 frames) in the
# debugger, then dumps the 64K-word space: OUT/dump.mem (big-endian words), OUT/jz.log, and
# the JLP flash file OUT/jlp.sav (--jlp-savegame). build_jlp.py compare reads the results.
# OUT holds the user's EXEC and GROM words: keep it outside any repository.
# Environment: JZINTV (default the owner's build), INTV_BIOS_DIR (exec.bin, grom.bin).
set -euo pipefail
bin=$(realpath "${1:?BIN}"); cfg=$(realpath "${2:?CFG}"); out=${3:?OUT}; cyc=${4:-100000}
JZ=${JZINTV:-$HOME/daria_work/intv/refs/jzintv/src-tree/jzintv-20200712-src/bin/jzintv}
B=${INTV_BIOS_DIR:?}
mkdir -p "$out"; out=$(cd "$out" && pwd)
cp "$bin" "$out/cart.bin"; cp "$cfg" "$out/cart.cfg"
rm -f "$out/dump.mem" "$out/dump.cpu"
printf 'r %s\nd\nq\n' "$cyc" > "$out/d.dbg"
cd "$out"
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy timeout 120 "$JZ" -e "$B/exec.bin" -g "$B/grom.bin" -a0 -r0 -d \
  --jlp-savegame="$out/jlp.sav" --script=d.dbg cart.bin > jz.log 2>&1 || true
[ -s dump.mem ] && [ "$(stat -c %s dump.mem)" = 131072 ] || { echo "no dump: $(grep -iE 'error|unknown' jz.log | head -2)"; exit 1; }
rm -f dump.cpu
echo "dump ok"
