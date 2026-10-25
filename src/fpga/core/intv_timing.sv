// Intellivision core: master timing and clock enables.
//
// Everything in the machine runs on clk_sys = 12 x the master clock
// (DESIGN.md 2.3: NTSC 42.954545 MHz = 12 x 3.579545 MHz) with clock
// enables made here:
//   ce_pix  every 12 clk_sys   one pixel clock of the raster = one master
//                              clock (279.4 ns; Mattel service manual p.60)
//   ce_stic                    the same, for the machine (the STIC advance)
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
// pocket_video are counted in vline and need no wrap of their own.
// Every line/frame figure is a parameter, because PAL differs (DESIGN.md
// 2.4: probably 256 pixel clocks x 312 lines; not built until step 12).
//
// Raster and machine. The raster (sub, hcnt, vcnt and ce_pix) never stops:
// it drives the Pocket's video port, whose HS / VS / DE must stay periodic
// whatever the machine does, or the scaler loses sync. The machine has its
// own position, mpos, the raster position at which it takes its next
// clk_sys. While the machine runs it is aligned (mpos follows the raster
// and equals it on every clk_sys), live is 1 and ce_stic / ce_psg / ce_cpu
// fire with the raster. run = 0 freezes the machine (DESIGN.md 4.2): mpos
// holds, the machine enables stop, live is 0 and pocket_video blanks the
// picture, while the raster runs on. When run is 1 again, the machine waits
// until the raster comes round to mpos and then resumes on exactly that
// clk_sys, so it loses whole frames only and the raster never jumps. The
// freeze lands in VBlank (DESIGN.md 4.2), so the wait is at most one frame
// and resumes in VBlank too. While live, the raster's hcnt / vcnt are the
// machine's position, so the STIC and the CPU may use them under their
// enables; while not live they must not act on them.
//
// Save state (DESIGN.md 4.3): one state word, the machine's position mpos.
// A state write loads mpos only, never the raster: the machine is then out
// of line with the raster (live = 0) and resumes, as after a freeze, when
// the raster reaches the loaded position, so a restore keeps the video
// sync continuous too. ss_rdata is 0 unless this module is addressed, so
// ports can be OR-combined. The caller (ss_ctl, step 7) writes only while
// the machine is frozen. A word outside the frame (sub >= SUB_TOTAL,
// hcnt >= H_TOTAL or vcnt >= V_TOTAL, say from a corrupt or foreign state
// file) would never be reached and the machine would never resume, so such
// a write is ignored: mpos keeps its value.
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
    input  wire logic        reset,           // synchronous, raster and machine to 0
    input  wire logic        run,             // 0 = machine frozen

    // the raster, free-running
    output logic             ce_pix,
    output logic [8:0]       hcnt,            // 0 .. H_TOTAL-1
    output logic [8:0]       vcnt,            // 0 .. V_TOTAL-1, 0 = vblank start
    output logic [8:0]       vline,           // (vcnt - V_VS) mod V_TOTAL

    // the machine
    output logic             live,            // running and aligned to the raster
    output logic             ce_stic,
    output logic             ce_psg,
    output logic             ce_cpu,

    // state port
    input  wire logic [15:0] ss_addr,         // [15:8] module id, [7:0] word
    input  wire logic        ss_we,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [31:0] ss_wdata,        // [31:22] unused
    /* verilator lint_on UNUSEDSIGNAL */
    output logic [31:0]      ss_rdata
);

    logic [3:0]  sub = 4'd0;
    logic [21:0] mpos = 22'd0;                // {vcnt, hcnt, sub} of the machine

    initial begin
        hcnt = 9'd0;
        vcnt = 9'd0;
    end

    wire logic sub_end  = sub == 4'(SUB_TOTAL - 1);
    wire logic line_end = hcnt == 9'(H_TOTAL - 1);
    wire logic ss_hit   = ss_addr[15:8] == SS_ID && ss_addr[7:0] == 8'd0;
    wire logic ss_ok    = {1'b0, ss_wdata[3:0]} < 5'(SUB_TOTAL)
                       && ss_wdata[12:4] < 9'(H_TOTAL)
                       && ss_wdata[21:13] < 9'(V_TOTAL);

    // the raster's next position
    wire logic [3:0] sub_n  = sub_end ? 4'd0 : sub + 4'd1;
    wire logic [8:0] hcnt_n = !sub_end ? hcnt : line_end ? 9'd0 : hcnt + 9'd1;
    wire logic [8:0] vcnt_n = !(sub_end && line_end) ? vcnt
                            : vcnt == 9'(V_TOTAL - 1) ? 9'd0 : vcnt + 9'd1;

    assign live    = run && {vcnt, hcnt, sub} == mpos;
    assign ce_pix  = sub_end;
    assign ce_stic = live && sub_end;
    assign ce_psg  = ce_stic && hcnt[0];
    assign ce_cpu  = ce_stic && hcnt[1:0] == 2'd3;

    always_ff @(posedge clk) begin
        if (reset) begin
            sub  <= 4'd0;
            hcnt <= 9'd0;
            vcnt <= 9'd0;
        end else begin          // the raster never stops
            sub  <= sub_n;
            hcnt <= hcnt_n;
            vcnt <= vcnt_n;
        end
    end

    always_ff @(posedge clk) begin
        if (reset)
            mpos <= 22'd0;
        else if (ss_we && ss_hit && ss_ok)    // out-of-frame words ignored
            mpos <= ss_wdata[21:0];
        else if (live)
            mpos <= {vcnt_n, hcnt_n, sub_n};
    end

    assign vline = vcnt >= 9'(V_VS) ? vcnt - 9'(V_VS) : vcnt + 9'(V_TOTAL - V_VS);

    assign ss_rdata = ss_hit ? {10'd0, mpos} : 32'd0;

    // The CPU and PSG enables assume whole CPU cycles per line.
    initial begin
        if (H_TOTAL % 4 != 0)
            $error("intv_timing: H_TOTAL must be a multiple of 4");
        if (SUB_TOTAL > 16 || V_TOTAL > 511 || H_TOTAL > 511 || V_VS >= V_TOTAL)
            $error("intv_timing: parameter out of range");
    end

endmodule

`default_nettype wire
