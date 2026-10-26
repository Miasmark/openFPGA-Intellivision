# Extra reports of the fit's Timing Analyzer (TIMING_ANALYZER_REPORT_SCRIPT
# in ap_core.qsf), run after its default reports, for the clock crossings
# with a net-delay bound (core_constraints.sdc: intv_input.sv, build step 6;
# intv_ss_ctl.sv, build step 7), as panels in ap_core.sta.rpt and as
# messages:
# - "Crossing net delay (slow model)" and "(fast model)": every set_net_delay
#   bound and its nets: hold_74 -> word and req_74 -> req_s[0] (input);
#   b_we / b_w / b_d -> b_we_s / bp_w / bp_d and b_t -> b_s[0] (a bridge
#   access), r_q -> bridge_rd_data and r_t -> r_s[0] (a read's word),
#   s_* / l_* -> st_a (the result bits) (save states);
# - the number of registers on each side the fit kept (messages), so a
#   check can tell that every kept bit has its row;
# - "Synchronizer chains": the metastability report, where each toggle and
#   result bit must cross through a chain of two flip-flops.
# sim/check/fit_crossing_check.py checks all of it after a build.
#
# SPDX-License-Identifier: MIT

foreach model {slow fast} {
    set_operating_conditions -model $model
    update_timing_netlist
    report_net_delay -panel_name "Crossing net delay ($model model)" -stdout
}
proc n_kept {pat} { return [get_collection_size [get_keepers $pat]] }
set n_word [n_kept {*intv_input:*|word[*]}]
set n_hold [n_kept {*intv_input:*|hold_74[*]}]
post_message -type info "Input crossing registers: word $n_word, hold_74 $n_hold"
set m "Save-state crossing registers:"
foreach r {b_we_s bp_w[*] bp_d[*] b_we b_w[*] b_d[*] bridge_rd_data[*] r_q[*] st_a[*]} {
    append m " [string map {{[*]} {}} $r] [n_kept *intv_ss_ctl:*|$r]"
}
post_message -type info $m
report_metastability -panel_name "Synchronizer chains" -stdout
