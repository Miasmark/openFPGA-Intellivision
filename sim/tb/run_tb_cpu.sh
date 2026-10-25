#!/bin/bash
# Build and run tb_cpu (DESIGN.md 9, step 3): the CP1610 RTL in lockstep
# with the Python model's bus-phase log, and the save/restore round trip.
#   sim/tb/run_tb_cpu.sh [+vec=FILE] [+saves=1] [+verbose=1]   one run
#                                    (default FILE: WORK/vec/tests.vec)
#   sim/tb/run_tb_cpu.sh --all       the step-3 CPU gate: the model's bus log
#                                    exported (tools/cpu_buslog.py), every
#                                    program in sim/tests/cpu, the opcode
#                                    sweep and the random programs, each
#                                    without and with save points, then the planted faults, each of
#                                    which the bench must catch
# VERILATOR (default: verilator on PATH) picks the binary; WORK (default
# sim/work/tb_cpu) the build directory. On the owner's VM, run it in a
# simulation slot: ~/daria_work/bin/simslot sim/tb/run_tb_cpu.sh --all
# SPDX-License-Identifier: MIT
set -e -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VERILATOR="${VERILATOR:-verilator}"
WORK="${WORK:-$ROOT/sim/work/tb_cpu}"
CORE="$ROOT/src/fpga/core"
RTL=(cp1610.sv)
VEC="$WORK/vec"

# build DIR SRCDIR: the bench against the RTL in SRCDIR
build() {
	mkdir -p "$1"
	"$VERILATOR" --binary --timing -j 2 -Wall -Wno-PROCASSINIT -Wno-UNUSEDSIGNAL -Wno-DECLFILENAME \
		-Wno-BLKSEQ -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND -Wno-TIMESCALEMOD \
		--top-module tb_cpu -Mdir "$1/obj" -o tb_cpu \
		"${RTL[@]/#/$2/}" "$ROOT/sim/tb/tb_cpu.sv" > "$1/build.log" 2>&1 \
		|| { tail -40 "$1/build.log"; return 1; }
}

python3 "$ROOT/tools/cpu_buslog.py" "$VEC" > "$WORK.export.log" 2>&1 || { cat "$WORK.export.log"; exit 1; }
build "$WORK" "$CORE"
if [ "$1" != "--all" ]; then
	case " $* " in
		*" +vec="*) args=("$@") ;;
		*) args=(+vec="$VEC/tests.vec" "$@") ;;
	esac
	"$WORK/obj/tb_cpu" "${args[@]}" | tee "$WORK/run.log"
	grep -q "^TB_CPU pass$" "$WORK/run.log"
	exit
fi

rc=0
for v in tests sweep fuzz; do
	for s in 0 1; do
		log="$WORK/run_${v}_s$s.log"
		"$WORK/obj/tb_cpu" +vec="$VEC/$v.vec" +saves=$s > "$log" 2>&1 || true
		echo "$v saves=$s: $(grep -E '^[0-9]+ cases|^TB_CPU' "$log" | paste -sd' ')"
		grep "FAIL" "$log" | head -5 || true
		grep -q "^TB_CPU pass$" "$log" || rc=1
	done
done

# Planted faults: each is a one-line change to a copy of the RTL, and the
# bench must fail on it (the plain lockstep or, for the state port, the
# round trip).
plant() {
	local name="$1" file="$2" from="$3" to="$4" vec="$5" saves="$6" d="$WORK/plant_$1"
	rm -rf "$d"; mkdir -p "$d/rtl"
	cp "${RTL[@]/#/$CORE/}" "$d/rtl/"
	grep -qF -- "$from" "$d/rtl/$file" || { echo "PLANT $name: pattern not found"; rc=1; return; }
	python3 -c 'import sys; p, a, b = sys.argv[1:]; s = open(p).read(); open(p, "w").write(s.replace(a, b, 1))' \
		"$d/rtl/$file" "$from" "$to"
	build "$d" "$d/rtl" || { echo "PLANT $name: build failed"; rc=1; return; }
	"$d/obj/tb_cpu" +vec="$VEC/$vec.vec" +saves=$saves > "$d/run.log" 2>&1 || true
	if grep -q "^TB_CPU FAIL" "$d/run.log" && ! grep -q "^TB_CPU pass" "$d/run.log"; then
		echo "PLANT $name: caught: $(grep "^FAIL" "$d/run.log" | head -3 | sed 's/^FAIL *//' | paste -sd';' | cut -c1-90)"
	else
		echo "PLANT $name: not caught"; rc=1
	fi
}
F=cp1610.sv
# a 10-cycle interrupt sequence (wiki Bus_Phases' count)
plant irq10 $F "cnt_n = 2'd2; st_n = S_INACT3;" "cnt_n = 2'd3; st_n = S_INACT3;" tests 0
# INTRM as a level, not an edge
plant irq_level $F "intrm_req_n  = intrm && (intrm_req || !intrm_prev);" "intrm_req_n  = intrm;" tests 0
# SDBD bytes in the wrong order
plant sdbd_swap $F "{din[7:0], lo} : tmp;" "{lo, din[7:0]} : tmp;" sweep 0
# a branch not taken with the trailing NACT (9 cycles)
plant nottaken_nact $F "fin = 1'b1; fin_ok = 1'b1;  // 7 cycles" "st_n = S_RNACT2;  // 7 cycles" sweep 0
# SWAP's S from bit 15
plant swap_s15 $F "3'd0: res = ir[2] ? {ra[7:0], ra[7:0]} : {ra[7:0], ra[15:8]};  // SWAP" "3'd0: begin res = ir[2] ? {ra[7:0], ra[7:0]} : {ra[7:0], ra[15:8]}; x_s7 = 1'b0; end" fuzz 0
# MVO interruptible
plant mvo_int $F "S_WNACT2: fin = 1'b1;               // MVO: not interruptible" "S_WNACT2: begin fin = 1'b1; fin_ok = 1'b1; end" tests 0
# BUSRQ not checked again after the wait (interrupt edge in the wait lost)
plant busak_nosample $F "                    smp = 1'b1;
                    st_n = S_FBAR;" "                    st_n = S_FBAR;" tests 0
# the jump's return address one too low
plant jsr_ret $F "if (tmp[9:8] != 2'd3) r_n[{1'b1, tmp[9:8]}] = r[7];" "if (tmp[9:8] != 2'd3) r_n[{1'b1, tmp[9:8]}] = r[7] - 16'd1;" sweep 0
# state port: the idle counter not restored (only the round trip sees it)
plant ss_cnt $F "st <= st_t'(ss_wdata[22:18]); cnt <= ss_wdata[24:23];" "st <= st_t'(ss_wdata[22:18]);" sweep 1
# state port: the INTRM line sample not restored
plant ss_intrm_prev $F "{intr_prev, intr_req, intrm_prev, intrm_req, intok} <= ss_wdata[10:6];" "{intr_prev, intr_req, intrm_req, intok} <= {ss_wdata[10:9], ss_wdata[7:6]};" tests 1
# state port: the SDBD low byte not saved
plant ss_lo $F "8'd5: ss_rdata = {3'd0, taken, hnow, dbd, jpt, cnt, 5'(st), lo, ir};" "8'd5: ss_rdata = {3'd0, taken, hnow, dbd, jpt, cnt, 5'(st), 8'd0, ir};" sweep 1
# NEGR of 0 leaves C clear (MAME's behaviour, CPU_NOTES row 5)
plant negr_c $F "x_we = 1'b1; x_sz = 1'b1; x_c = sum[17]; x_o = sum[16];" "x_we = 1'b1; x_sz = 1'b1; x_c = sum[17] & (f_m != 3'd4); x_o = sum[16];" tests 0
# state port: the sequence address/data word not restored
plant ss_tmp $F "8'd4: {tmp, ea} <= ss_wdata;" "8'd4: ea <= ss_wdata[15:0];" fuzz 1
# state port: halt pending not restored
plant ss_hpend $F "{hlt, hpend} <= ss_wdata[12:11];" "hlt <= ss_wdata[12];" tests 1

echo "TB_CPU_ALL $([ $rc = 0 ] && echo pass || echo FAIL)"
exit $rc
