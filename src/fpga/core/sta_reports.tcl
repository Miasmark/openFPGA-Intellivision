# Extra reports of the fit's Timing Analyzer (TIMING_ANALYZER_REPORT_SCRIPT
# in ap_core.qsf), run after its default reports, for the input crossing
# (core_constraints.sdc, intv_input.sv), as panels in ap_core.sta.rpt and as
# messages:
# - "Input crossing net delay (slow model)" and "(fast model)": the
#   set_net_delay bound on every hold_74 -> word and req_74 -> req_s[0] net;
# - the number of word and hold_74 registers the fit kept (a message), so a
#   check can tell that every kept bit has its row;
# - "Synchronizer chains": the metastability report, where req_74 -> req_s
#   and ack -> ack_74 must each be a chain of two flip-flops.
# sim/check/fit_crossing_check.py checks all three after a build.
#
# SPDX-License-Identifier: MIT

foreach model {slow fast} {
    set_operating_conditions -model $model
    update_timing_netlist
    report_net_delay -panel_name "Input crossing net delay ($model model)" -stdout
}
set n_word [get_collection_size [get_keepers {*intv_input:*|word[*]}]]
set n_hold [get_collection_size [get_keepers {*intv_input:*|hold_74[*]}]]
post_message -type info "Input crossing registers: word $n_word, hold_74 $n_hold"
report_metastability -panel_name "Synchronizer chains" -stdout
