#!/bin/bash
# Build and run tb_timing (DESIGN.md 9, step 1) with Verilator.
#   sim/tb/run_tb_timing.sh [plusargs...]   one run, e.g. +border=0 +vidph=5
#   sim/tb/run_tb_timing.sh --all            the step-1 gate: border 0 and 1 at
#                                            clk_vid phases 0, 5 and 11, then
#                                            eight planted faults the bench
#                                            must catch
# VERILATOR (default: verilator on PATH) picks the binary; WORK (default
# sim/work/tb_timing) the build directory. On the owner's VM, run it in a
# simulation slot: ~/daria_work/bin/simslot sim/tb/run_tb_timing.sh --all
# SPDX-License-Identifier: MIT
set -e -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VERILATOR="${VERILATOR:-verilator}"
# the C++ through ccache when it is installed (OBJCACHE not set; empty: off) and at -O2 (sim/tb/tbcommon.py,
# docs/SIM_SPEED.md 2)
export OBJCACHE="${OBJCACHE-$(command -v ccache > /dev/null && echo ccache)}"
VL_MAKEFLAGS=(-MAKEFLAGS OPT_FAST=-O2 -MAKEFLAGS OPT_GLOBAL=-O2)
WORK="${WORK:-$ROOT/sim/work/tb_timing}"
CORE="$ROOT/src/fpga/core"
RTL=(intv_timing.sv intv_palette.sv test_pattern.sv pocket_video.sv)

# build DIR SRCDIR: the bench against the RTL in SRCDIR
build() {
	mkdir -p "$1"
	# --verilate-jobs 1: Verilator 5.040's multithreaded verilation (what -j N turns on besides --build-jobs) crashed
	# about one build in 16 with "internal fault" (2026-10-28: 5 of 80 with -j 2, 0 of 210 with one verilate job)
	"$VERILATOR" "${VL_MAKEFLAGS[@]}" --binary --timing --verilate-jobs 1 --build-jobs 2 -Wall -Wno-PROCASSINIT -Wno-UNUSEDSIGNAL -Wno-DECLFILENAME \
		-Wno-BLKSEQ -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \
		--top-module tb_timing -Mdir "$1/obj" -o tb_timing \
		"${RTL[@]/#/$2/}" "$ROOT/sim/tb/tb_timing.sv" > "$1/build.log" 2>&1 \
		|| { tail -40 "$1/build.log"; return 1; }
}
# run DIR plusargs...: 0 if the bench passes
run() {
	local d="$1"; shift
	"$d/obj/tb_timing" "$@" | tee "$d/run.log" | grep -v "^ *ok "
	grep -q "^TB_TIMING pass$" "$d/run.log"
}

build "$WORK" "$CORE"
if [ "$1" != "--all" ]; then
	run "$WORK" "$@"
	exit
fi

rc=0
for b in 0 1; do
	for p in 0 5 11; do
		run "$WORK" +border=$b +vidph=$p || rc=1
	done
done

# Planted faults: each is a one-line change to a copy of the RTL, and the
# bench must fail on it.
plant() {
	local name="$1" file="$2" from="$3" to="$4" d="$WORK/plant_$1"
	rm -rf "$d"; mkdir -p "$d/rtl"
	cp "${RTL[@]/#/$CORE/}" "$d/rtl/"
	grep -qF -- "$from" "$d/rtl/$file" || { echo "PLANT $name: pattern not found"; rc=1; return; }
	python3 -c 'import sys; p, a, b = sys.argv[1:]; s = open(p).read(); open(p, "w").write(s.replace(a, b, 1))' \
		"$d/rtl/$file" "$from" "$to"
	build "$d" "$d/rtl" || { echo "PLANT $name: build failed"; rc=1; return; }
	"$d/obj/tb_timing" +border=1 > "$d/run.log" 2>&1 || true
	if grep -q "^TB_TIMING FAIL" "$d/run.log" && ! grep -q "^TB_TIMING pass" "$d/run.log"; then
		echo "PLANT $name: caught: $(grep "^ *FAIL" "$d/run.log" | sed 's/^ *FAIL *//' | cut -c1-60 | paste -sd';')"
	else
		echo "PLANT $name: not caught"; rc=1
	fi
}
plant lines263 intv_timing.sv "parameter int         V_TOTAL   = 262" "parameter int         V_TOTAL   = 263"
plant blue intv_palette.sv "24'h002DFF" "24'h002DFE"
plant ss_sub intv_timing.sv "            mpos <= ss_wdata[21:0];" "            mpos <= {ss_wdata[21:4], 4'd0};"
# the raster gated by run (the step-1 commit's behaviour): sync stops in a freeze
plant raster_run intv_timing.sv "        end else begin          // the raster never stops" "        end else if (run) begin"
# the machine resumes at once instead of at its saved position
plant nophase intv_timing.sv "    assign live    = run && {vcnt, hcnt, sub} == mpos;" "    assign live    = run;"
# the picture not blanked while frozen
plant noblank pocket_video.sv "p_rgb <= blank ? 24'd0" "p_rgb <= 1'b0 ? 24'd0"
# an out-of-frame state word accepted: the machine would never resume
plant ss_nocheck intv_timing.sv "else if (ss_we && ss_hit && ss_ok)" "else if (ss_we && ss_hit)"
# live ignores sub: caught by the restore and by the skewed VBlank freeze
plant live_nosub intv_timing.sv "    assign live    = run && {vcnt, hcnt, sub} == mpos;" "    assign live    = run && {vcnt, hcnt} == mpos[21:4];"

echo "TB_TIMING_ALL $([ $rc = 0 ] && echo pass || echo FAIL)"
exit $rc
