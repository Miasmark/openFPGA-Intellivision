#
# Intellivision core constraints (loaded by apf/apf_constraints.sdc)
#
# One core PLL (ic|pll, core/pll/pll_core.v) makes, from one VCO:
#   counter 0  clk_sys     42.954545 MHz, the machine (12 x master)
#   counter 1  clk_mem     85.909091 MHz, memories (unused in step 1)
#   counter 2  clk_vid     3.579545 MHz, the pixel clock (clk_sys / 12)
#   counter 3  clk_vid_90  clk_vid at 90 degrees, the scaler's sample clock
# Their rising edges coincide, so they are one synchronous group and every
# crossing between them is timed: the pixel stream crosses from clk_sys to
# clk_vid (core/pocket_video.sv) with one clk_sys period of setup, the
# tightest edge pair. Everything else is asynchronous to them.
#
# derive_pll_clocks names the outputs
# ic|pll|altera_pll_i|cyclonev_pll|counter[n].output_counter|divclk
# (the fit's STA report). The wildcard takes counters 0, 2 and 3 now;
# counter 1 (clk_mem) is unused in step 1, so Quartus removes it, and the
# wildcard takes it too once it is used.

set core_clks {ic|pll|altera_pll_i|*|divclk}

set_clock_groups -asynchronous \
 -group { bridge_spiclk } \
 -group { clk_74a } \
 -group { clk_74b } \
 -group [get_clocks $core_clks]

# SRAM (AS6C2016-55; core/intv_sram.sv, build steps 2-3). The chip has no
# clock: the controller drives the address, OE, WE, UB/LB and the write data
# from clk_sys registers and samples DQ at the edge three clk_sys periods
# after the one that put the address out (RD_CYC = 3: 69.84 ns). Two checks
# make the read a timed path:
#  - every SRAM output reaches its pin at most 10 ns after the clk_sys edge
#    (output delay 23.28 - 10 = 13.28 ns; the step-3 fit gives about 8.6);
#  - DQ is valid tAA (55 ns) + 2 ns of board after the address is at the
#    pins, so at most 10 + 57 = 67 ns after the launching edge; it is
#    captured three edges later (multicycle setup 3, hold 2), in the I/O
#    input registers (FAST_INPUT_REGISTER on sram_dq in ap_core.qsf: the
#    capture register in the core fabric left only about 0.7 ns with a
#    65 ns bound).
# Writes have whole clk_sys periods between address/data and the WE edges
# (intv_sram.sv), so the 10 ns output bound covers them.
set sram_clk [get_clocks {ic|pll|altera_pll_i|cyclonev_pll|counter\[0\].output_counter|divclk}]
set sram_out [get_ports {sram_a[*] sram_dq[*] sram_oe_n sram_we_n sram_ub_n sram_lb_n}]
set_output_delay -clock $sram_clk -max 13.28 $sram_out
set_output_delay -clock $sram_clk -min 0.0 $sram_out
set_input_delay -clock $sram_clk -max 67.0 [get_ports {sram_dq[*]}]
set_input_delay -clock $sram_clk -min 0.0 [get_ports {sram_dq[*]}]
set_multicycle_path -from [get_ports {sram_dq[*]}] -setup -end 3
set_multicycle_path -from [get_ports {sram_dq[*]}] -hold -end 2

# Input (core/intv_input.sv, build step 6): the controller words and the
# Keypad Mode / Swap settings cross from clk_74a to clk_sys as one held word
# with a toggle handshake. hold_74 (clk_74a) is taken and req_74 toggles at
# the same clk_74a edge; req_74 passes two clk_sys flip-flops (req_s), and
# word loads hold_74 at the clk_sys edge after req_s[1] changes, at least
# two clk_sys periods (46.56 ns) after req_74 reached req_s[0]; hold_74 does
# not change again until the acknowledge has come back through two clk_74a
# flip-flops (ack_74). So the copy is stable for the load as long as no bit
# of it takes much longer from hold_74 to word than req_74 takes to req_s[0]:
# the scheme leaves about two clk_sys periods for that difference. No bound
# on skew is needed, only one on the paths' length, which the asynchronous
# clock groups above would leave untimed: set_net_delay still applies to
# cut paths and bounds every hold_74 -> word and req_74 -> req_s[0] net to
# 10 ns (the paths are register to register, so the net is nearly all of
# the path; 10 ns is under a quarter of the margin). set_max_skew and
# set_max_delay do not work here: Quartus Standard drops both on paths the
# clock groups cut ("No path is found satisfying assignment", tried on the
# 0.0.5 fit). The fit's Timing Analyzer lists the net delays in
# ap_core.sta.rpt (panels "Input crossing net delay", core/sta_reports.tcl).
# The single-bit synchronisers (req_74 -> req_s, ack -> ack_74) need nothing
# more; the metastability report (panel "Synchronizer chains") lists them as
# chains of two flip-flops. sim/check/fit_crossing_check.py checks both
# after a fit (DEVELOPING, Build).
set in_from [get_keepers {*intv_input:*|hold_74[*] *intv_input:*|req_74}]
set in_to   [get_keepers {*intv_input:*|word[*] *intv_input:*|req_s[0]}]
set_net_delay -from $in_from -to $in_to -max 10.0
