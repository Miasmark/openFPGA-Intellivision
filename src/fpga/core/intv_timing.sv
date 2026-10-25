// Intellivision core: master timing and clock enables.
//
// Everything in the machine runs on clk_sys = 12 x the master clock
// (DESIGN.md 2.3: NTSC 42.954545 MHz = 12 x 3.579545 MHz) with clock
// enables made here:
//   ce_pix  every 12 clk_sys   one STIC pixel = one master clock
//                              (279.4 ns; Mattel service manual p.60)
//   ce_psg  every 24 clk_sys   PSG clock, master / 2 (MAME intv.cpp:470)
//   ce_cpu  every 48 clk_sys   one CP1610 microcycle, master / 4
//                              (MAME intv.cpp:445)
// The line is 57 CPU cycles = 228 pixel clocks and the frame 262 lines
// (DESIGN.md 2.4; MAME stic.h:47; jzIntv doc/programming/interrupts.txt,
// read as specification), so 14,934 CPU cycles and 59.92 Hz per frame.
// Because the line length is a multiple of 4 pixels, the CPU and PSG
// enables keep a fixed phase to the pixel counter: the STIC drives the
// CPU's clocks on the real board, so they are locked to the picture.
//
// vcnt counts frame lines from the start of vertical blanking (the STIC's
// frame, where the CPU's interrupt begins: jzIntv interrupts.txt, MAME
// stic.h:50). The Pocket's frame starts at line V_VS instead, so vline is
// vcnt moved by V_VS, wrapping at the frame end: the video windows in
// pocket_video_timing are counted in vline and need no wrap of their own.
// Every line/frame figure is a parameter, because PAL differs (DESIGN.md
// 2.4: probably 256 pixel clocks x 312 lines; not built until step 12).
//
// Save state (DESIGN.md 4.3): one state word holds every counter. While
// run is low nothing advances (the freeze of DESIGN.md 4.2), and a state
// write loads the counters. ss_rdata is 0 unless this module is addressed,
// so ports can be OR-combined.
//   word 0: [3:0] sub (clk_sys within the pixel), [12:4] hcnt, [21:13] vcnt
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_timing #(
    parameter int         SUB_TOTAL = 12,     // clk_sys per pixel clock
    parameter int         H_TOTAL   = 228,    // pixel clocks per line
    parameter int         V_TOTAL   = 262,    // lines per frame
    parameter int         V_VS      = 30,     // vcnt of the Pocket's first line
    parameter logic [7:0] SS_ID     = 8'h01   // save-state module id
) (
    input  wire logic        clk,             // clk_sys
    input  wire logic        reset,           // synchronous, counters to 0
    input  wire logic        run,             // 0 = frozen

    output logic             ce_pix,
    output logic             ce_psg,
    output logic             ce_cpu,
    output logic [8:0]       hcnt,            // 0 .. H_TOTAL-1
    output logic [8:0]       vcnt,            // 0 .. V_TOTAL-1, 0 = vblank start
    output logic [8:0]       vline,           // (vcnt - V_VS) mod V_TOTAL

    // state port
    input  wire logic [15:0] ss_addr,         // [15:8] module id, [7:0] word
    input  wire logic        ss_we,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [31:0] ss_wdata,        // [31:22] unused
    /* verilator lint_on UNUSEDSIGNAL */
    output logic [31:0]      ss_rdata
);

    logic [3:0] sub = 4'd0;

    initial begin
        hcnt = 9'd0;
        vcnt = 9'd0;
    end

    wire logic sub_end  = sub == 4'(SUB_TOTAL - 1);
    wire logic line_end = hcnt == 9'(H_TOTAL - 1);
    wire logic ss_hit   = ss_addr[15:8] == SS_ID && ss_addr[7:0] == 8'd0;

    assign ce_pix = run && sub_end;
    assign ce_psg = ce_pix && hcnt[0];
    assign ce_cpu = ce_pix && hcnt[1:0] == 2'd3;

    always_ff @(posedge clk) begin
        if (reset) begin
            sub  <= 4'd0;
            hcnt <= 9'd0;
            vcnt <= 9'd0;
        end else if (ss_we && ss_hit) begin
            sub  <= ss_wdata[3:0];
            hcnt <= ss_wdata[12:4];
            vcnt <= ss_wdata[21:13];
        end else if (run) begin
            sub <= sub_end ? 4'd0 : sub + 4'd1;
            if (sub_end) begin
                hcnt <= line_end ? 9'd0 : hcnt + 9'd1;
                if (line_end)
                    vcnt <= vcnt == 9'(V_TOTAL - 1) ? 9'd0 : vcnt + 9'd1;
            end
        end
    end

    assign vline = vcnt >= 9'(V_VS) ? vcnt - 9'(V_VS) : vcnt + 9'(V_TOTAL - V_VS);

    assign ss_rdata = ss_hit ? {10'd0, vcnt, hcnt, sub} : 32'd0;

    // The CPU and PSG enables assume whole CPU cycles per line.
    initial begin
        if (H_TOTAL % 4 != 0)
            $error("intv_timing: H_TOTAL must be a multiple of 4");
        if (SUB_TOTAL > 16 || V_TOTAL > 511 || H_TOTAL > 511 || V_VS >= V_TOTAL)
            $error("intv_timing: parameter out of range");
    end

endmodule

`default_nettype wire
