# Extra reports of the fit's Timing Analyzer (TIMING_ANALYZER_REPORT_SCRIPT
# in ap_core.qsf), run after its default reports: the input crossing's net
# delays (core_constraints.sdc, intv_input.sv) for the slow and the fast
# model, as panels in ap_core.sta.rpt and as messages.
#
# SPDX-License-Identifier: MIT

foreach model {slow fast} {
    set_operating_conditions -model $model
    update_timing_netlist
    report_net_delay -panel_name "Input crossing net delay ($model model)" -stdout
}
