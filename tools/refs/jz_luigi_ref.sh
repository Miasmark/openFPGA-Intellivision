#!/bin/bash
# jz_luigi_ref.sh REPO IMGDIR OUT
# 1.0.7 (docs/CARTFORMATS.md 8): jzIntv's LUIGI tools as black boxes (run as programs only;
# their code is never read). For every case image of tools/refs/jz_luigi_compare.py: bin2luigi
# (BIN + CFG) or rom2luigi (.rom) makes OUT/luigi/<image>.luigi; luigi2bin turns it back into a
# BIN + CFG; tools/refs/jzintv_cart_dump.sh dumps jzIntv's space for each case's writes into
# OUT/dumps/<case>. Then the compare. OUT holds the user's EXEC words (in the dumps): keep it
# outside any repository. Environment: JZBIN (the jzIntv bin directory, default the owner's
# build), INTV_BIOS_DIR.
set -uo pipefail
R=$(realpath "${1:?REPO}"); I=$(realpath "${2:?IMGDIR}"); O=${3:?OUT}
JZBIN=${JZBIN:-$HOME/daria_work/intv/refs/jzintv/src-tree/jzintv-20200712-src/bin}
mkdir -p "$O/luigi" "$O/l2b" "$O/dumps"; O=$(realpath "$O")
for img in $(python3 -I "$R/tools/refs/jz_luigi_compare.py" --cases | awk '{print $2}' | sort -u); do
  if [ -f "$I/$img.rom" ]; then
    cp "$I/$img.rom" "$O/l2b/$img.rom"
    (cd "$O/l2b" && "$JZBIN/rom2luigi" "$img.rom" "$O/luigi/$img.luigi" > /dev/null 2>&1)
  else
    cp "$I/$img.bin" "$O/l2b/$img.bin"; [ -f "$I/$img.cfg" ] && cp "$I/$img.cfg" "$O/l2b/$img.cfg"
    (cd "$O/l2b" && "$JZBIN/bin2luigi" "$img.bin" "$O/luigi/$img.luigi" > /dev/null 2>&1)
  fi
  mkdir -p "$O/l2b/$img.back" && cp "$O/luigi/$img.luigi" "$O/l2b/$img.back/x.luigi"
  (cd "$O/l2b/$img.back" && "$JZBIN/luigi2bin" x.luigi > /dev/null 2>&1)
done
python3 -I "$R/tools/refs/jz_luigi_compare.py" --cases | while read -r case img w; do
  [ "$w" = - ] && w=
  bash "$R/tools/refs/jzintv_cart_dump.sh" "$O/l2b/$img.back/x.bin" "$O/l2b/$img.back/x.cfg" "$O/dumps/$case" "$w" > /dev/null 2>&1 \
    || echo "$case: no dump"
done
python3 -I "$R/tools/refs/jz_luigi_compare.py" "$O/luigi" "$O/dumps"
