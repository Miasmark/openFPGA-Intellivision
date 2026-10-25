#!/bin/bash
# Assemble the SD card layout from a finished Quartus build:
#   dist/ + output_files/ap_core.rbf -> release/M_Intellivision_Pocket_<version>.zip
# Environment (optional): RBF=FILE packages another bitstream (a dry run can
# pass any file); OUT_DIR=DIR writes the zip there instead of release/.
# Adapted from openFPGA-2600's tools/package.sh (MIT, same author).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RBF="${RBF:-$ROOT/src/fpga/output_files/ap_core.rbf}"
CORE="$ROOT/dist/Cores/Miasmark.Intellivision"
VERSION=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['core']['metadata']['version'])" "$CORE/core.json")

[ -f "$RBF" ] || { echo "missing $RBF - build first"; exit 1; }
python3 "$ROOT/tools/reverse_bits.py" "$RBF" "$CORE/intv.rbf_r"

OUT_DIR="${OUT_DIR:-$ROOT/release}"
mkdir -p "$OUT_DIR"
OUT="$(cd "$OUT_DIR" && pwd)/M_Intellivision_Pocket_${VERSION}.zip"
rm -f "$OUT"
# License texts and notices travel with the bitstream.
LIC="$CORE/licenses"
rm -rf "$LIC"
mkdir -p "$LIC"
cp "$ROOT/LICENSE" "$ROOT/THIRD_PARTY_NOTICES.md" "$LIC/"
cp "$ROOT/src/fpga/pocket_utils/LICENSE" "$LIC/analogue-pocket-utils-LICENSE.txt"
# A notice that lives only in source headers, copied word for word:
# Analogue's APF license.
awk '{ sub(/\r$/, "") } /^$/ { print; next } /^\/\/ *$/ || !/^\/\// { exit } { sub(/^\/\/ ?/, ""); print }' \
	"$ROOT/src/fpga/apf/apf_top.v" > "$LIC/Analogue-APF-Software-License.txt"
if command -v zip >/dev/null; then
	(cd "$ROOT/dist" && zip -r "$OUT" Cores Platforms Assets -x '*.keep')
else
	(cd "$ROOT/dist" && python3 - "$OUT" <<'PY'
import os, sys, zipfile
with zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED) as z:
    for top in ("Cores", "Platforms", "Assets"):
        for d, _, files in os.walk(top):
            z.write(d)
            for f in files:
                if f != ".keep":
                    z.write(os.path.join(d, f))
PY
	)
fi
echo "$OUT"
