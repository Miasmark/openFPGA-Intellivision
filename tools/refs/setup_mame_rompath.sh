#!/bin/bash
# setup_mame_rompath.sh BIOS_DIR OUT_DIR
# Make a MAME rompath for the intv, intvoice and intvecs systems from the
# user's own BIOS files. Nothing here is committed: OUT_DIR must be outside
# any repository. File names and CRCs are MAME's (src/mame/mattel/intv.cpp
# ROM_START(intv), stic.cpp, devices/bus/intv/ecs.cpp ROM_START(ecs),
# devices/bus/intv/voice.cpp ROM_START(intellivoice); MAME is BSD-3).
# The user's ECS.bin is the three 4K-word parts joined ($2000, $7000, $E000);
# it is split into MAME's three files.
set -euo pipefail
bios=${1:?BIOS_DIR}; out=${2:?OUT_DIR}
mkdir -p "$out/intv"
cp -f "$bios/exec.bin" "$out/intv/exec.bin"
# The GROM belongs to the stic device (src/mame/mattel/stic.cpp ROM_START).
cp -f "$bios/grom.bin" "$out/intv/ro-3-9503-003.u21"
[ -f "$bios/IVOICE.BIN" ] && cp -f "$bios/IVOICE.BIN" "$out/intv/sp0256-012.bin"
if [ -f "$bios/ECS.bin" ]; then
  dd if="$bios/ECS.bin" of="$out/intv/ecs_rom.20" bs=8192 skip=0 count=1 status=none
  dd if="$bios/ECS.bin" of="$out/intv/ecs_rom.70" bs=8192 skip=1 count=1 status=none
  dd if="$bios/ECS.bin" of="$out/intv/ecs_rom.e0" bs=8192 skip=2 count=1 status=none
fi
# MAME looks in the system's folder, its parent's, and each device's folder.
for d in intvoice intvecs intv_ecs intv_voice stic; do ln -sfn intv "$out/$d"; done
python3 -I - "$out/intv" <<'PY'
import sys, zlib, os
want = {'exec.bin':0xcbce86f7, 'ro-3-9503-003.u21':0x683a4158, 'sp0256-012.bin':0x0de7579d,
        'ecs_rom.20':0x5f9d05e5, 'ecs_rom.70':0x46bb1f48, 'ecs_rom.e0':0xc2ebcd90}
bad = 0
for n, c in want.items():
    p = os.path.join(sys.argv[1], n)
    if not os.path.exists(p): print('missing', n); continue
    got = zlib.crc32(open(p,'rb').read())
    print('%-15s %08x %s' % (n, got, 'ok' if got == c else 'MISMATCH'))
    bad += got != c
sys.exit(1 if bad else 0)
PY
