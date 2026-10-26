#!/bin/bash
# jzintv_cart_dump.sh IMAGE CFG|- OUT [WRITES]
# Build step 8 (docs/CARTFORMATS.md 7): jzIntv (GPL, run as a program only, a
# black box: its documentation is our specification, its code is never read)
# as a reference for BIN + CFG and Intellicart .rom images made from our own
# sources. It starts jzIntv in its debugger with the user's EXEC and GROM,
# makes the CPU-bus writes WRITES ("AAAA:VVVV,..." in hex: page selects, bank
# registers, RAM) before any instruction runs, then dumps the 64K-word
# space: OUT/dump.mem (big-endian words; jzIntv's debugger command "d") and
# OUT/jz.log. tools/refs/jz_cart_compare.py compares the model with it.
# OUT holds the user's EXEC and GROM words: keep it outside any repository.
# Environment: JZINTV (default the owner's build), INTV_BIOS_DIR (exec.bin,
# grom.bin).
set -euo pipefail
img=$(realpath "${1:?IMAGE}"); cfg=${2:?CFG or -}; out=${3:?OUT}; writes=${4:-}
JZ=${JZINTV:-$HOME/daria_work/intv/refs/jzintv/src-tree/jzintv-20200712-src/bin/jzintv}
B=${INTV_BIOS_DIR:?}
rm -rf "$out"; mkdir -p "$out"; out=$(cd "$out" && pwd)
ext=${img##*.}
cp "$img" "$out/cart.$ext"
[ "$cfg" != - ] && cp "$cfg" "$out/cart.cfg"
: > "$out/d.dbg"
for w in ${writes//,/ }; do echo "e ${w%%:*} ${w#*:}" >> "$out/d.dbg"; done
printf 'd\nq\n' >> "$out/d.dbg"
cd "$out"
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy timeout 60 "$JZ" -e "$B/exec.bin" -g "$B/grom.bin" -a0 -r0 -d \
  --script=d.dbg "cart.$ext" > jz.log 2>&1 || true
[ -s dump.mem ] && [ "$(stat -c %s dump.mem)" = 131072 ] || { echo "no dump: $(grep -iE 'error' jz.log | head -2)"; exit 1; }
rm -f dump.cpu
echo "dump ok"
