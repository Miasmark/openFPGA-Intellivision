#!/bin/bash
# tb_tape_nv: the ECS tape slot end to end at the bridge (sim/tb/tb_tape_nv.sv). WORK (default
# sim/work/tb_tape_nv): the build. Prints TB_TAPE_NV pass / FAIL.
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=${WORK:-$ROOT/sim/work/tb_tape_nv}
CORE=$ROOT/src/fpga/core
mkdir -p "$WORK"
${VERILATOR:-verilator} --binary --timing --verilate-jobs 1 --build-jobs 2 -Wall -Wno-fatal -Wno-PROCASSINIT \
    -Wno-TIMESCALEMOD --top-module tb_tape_nv -Mdir "$WORK/obj" -o tb_tape_nv \
    "$ROOT/sim/tb/tb_tape_nv.sv" "$CORE/intv_tape_store.sv" "$CORE/intv_tape_nv.sv" "$CORE/intv_tape.sv" \
    > "$WORK/build.log" 2>&1 || { tail -20 "$WORK/build.log"; echo "TB_TAPE_NV FAIL (build)"; exit 1; }
"$WORK/obj/tb_tape_nv" | grep -v '^- '
