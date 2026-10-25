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
# (the fit's STA report); the wildcard takes all four.

set core_clks {ic|pll|altera_pll_i|*|divclk}

set_clock_groups -asynchronous \
 -group { bridge_spiclk } \
 -group { clk_74a } \
 -group { clk_74b } \
 -group [get_clocks $core_clks]
