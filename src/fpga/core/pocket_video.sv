// Intellivision core: video windows and the Pocket's video interface.
//
// The picture source (the test pattern now, the STIC from step 4) gives a
// 4-bit STIC colour per pixel clock; this module decides which pixels the
// Pocket gets, turns colours into RGB (intv_palette) and drives the APF
// video port.
//
// Windows (DESIGN.md 6.1; the scaler modes are dist/Cores/
// Miasmark.Intellivision/video.json, slots 0 and 1). Counted in pixel
// clocks (hcnt) and Pocket lines (vline, see intv_timing):
//   playfield  160 x 192  hcnt PF_X0 ..+159, vline PF_Y0 ..+191
//              (20 x 12 cards of 8 x 8 pixels, each card-pixel row on two
//              lines: MAME stic.h:30-37, Y_SCALE 2)
//   border     167 x 210  3 pixels left, 4 right, 9 lines above and below
// The window sizes are DESIGN 6.1's; where the playfield sits in the line
// and frame is an estimate until the STIC timing is simulated (step 4).
// With V_VS = 30 in intv_timing the playfield is frame lines 70-261 (the
// first BACKTAB row fetch is at CPU cycle 3,933 = line 69: MAME stic.h:51).
//
// Pocket protocol (as in openFPGA-7800's core_top.v): video_vs is a
// one-pixel pulse at the start of the frame, video_hs a one-pixel pulse
// two pixels into every line (so never on the VS pixel), video_de marks
// the active pixels, and the first pixel after a line's active pixels
// carries the scaler slot in rgb[23:13].
//
// While the machine is frozen (blank = 1, intv_timing's live = 0) the
// active pixels are black: the windows, the slot word and HS / VS / DE run
// on unchanged with the free-running raster, so the scaler keeps its sync.
//
// Clocks: the pixel stream is built on clk_sys at ce_pix and holds for
// the 12 clk_sys of a pixel. clk_vid (= clk_sys / 12, the same PLL VCO,
// rising edges on clk_sys's) samples it once per pixel into the output
// registers; video_rgb_clock_90 is clk_vid shifted 90 degrees (core_top).
//
// SPDX-License-Identifier: MIT

`default_nettype none

module pocket_video #(
    parameter int PF_X0 = 37,   // first playfield pixel clock in the line
    parameter int PF_Y0 = 40,   // first playfield line (vline)
    parameter int PF_W  = 160,
    parameter int PF_H  = 192,
    parameter int BD_L  = 3,    // border pixels left / right of the playfield
    parameter int BD_R  = 4,
    parameter int BD_T  = 9,    // border lines above / below
    parameter int BD_B  = 9,
    parameter int HS_X  = 2     // hcnt of the HS pulse
) (
    input  wire logic        clk_sys,
    input  wire logic        ce_pix,
    input  wire logic [8:0]  hcnt,
    input  wire logic [8:0]  vline,
    input  wire logic        border_on,   // 1: border window (slot 1), 0: playfield (slot 0)
    input  wire logic        blank,       // 1: active pixels black (machine frozen)

    // to the picture source, for the current pixel
    output logic             in_pf,
    output logic [7:0]       pf_x,        // 0..159 inside the playfield
    output logic [7:0]       pf_y,        // 0..191 inside the playfield
    // from the picture source, for the same pixel (combinational)
    input  wire logic [3:0]  colour,
    // the on-screen keypads over the playfield (intv_osk_draw, build step 13), for the same
    // pixel: 0 none, 1 white, 2 dark, 3 yellow
    input  wire logic [1:0]  ovl,

    input  wire logic        clk_vid,
    output logic [23:0]      video_rgb,
    output logic             video_de,
    output logic             video_skip,
    output logic             video_hs,
    output logic             video_vs
);

    localparam int BX0 = PF_X0 - BD_L;
    localparam int BX1 = PF_X0 + PF_W + BD_R;     // exclusive
    localparam int BY0 = PF_Y0 - BD_T;
    localparam int BY1 = PF_Y0 + PF_H + BD_B;     // exclusive

    wire logic in_pf_x = hcnt >= 9'(PF_X0) && hcnt < 9'(PF_X0 + PF_W);
    wire logic in_pf_y = vline >= 9'(PF_Y0) && vline < 9'(PF_Y0 + PF_H);
    wire logic in_bd   = hcnt >= 9'(BX0) && hcnt < 9'(BX1) && vline >= 9'(BY0) && vline < 9'(BY1);

    assign in_pf = in_pf_x && in_pf_y;
    assign pf_x  = 8'(hcnt - 9'(PF_X0));
    assign pf_y  = 8'(vline - 9'(PF_Y0));

    wire logic de_now = border_on ? in_bd : in_pf;

    logic [23:0] pal_rgb;
    intv_palette palette (
        .idx    ( colour ),
        .rgb    ( pal_rgb )
    );

    // Pixel stream, clk_sys, one value per pixel clock
    logic [23:0] p_rgb = 24'd0;
    logic        p_de = 1'b0, p_hs = 1'b0, p_vs = 1'b0;

    always_ff @(posedge clk_sys) begin
        if (ce_pix) begin
            p_de  <= de_now;
            p_hs  <= hcnt == 9'(HS_X);
            p_vs  <= hcnt == 9'd0 && vline == 9'd0;
            if (de_now)
                p_rgb <= blank ? 24'd0
                       : !in_pf || ovl == 2'd0 ? pal_rgb
                       : ovl == 2'd1 ? 24'hFFFFFF : ovl == 2'd2 ? 24'h000000 : 24'hFFD800;
            else if (p_de)
                p_rgb <= {8'd0, 2'd0, border_on, 13'd0};   // scaler slot 0 or 1
            else
                p_rgb <= 24'd0;
        end
    end

    // Output registers, clk_vid
    logic [23:0] o_rgb = 24'd0;
    logic        o_de = 1'b0, o_hs = 1'b0, o_vs = 1'b0;

    always_ff @(posedge clk_vid) begin
        o_rgb <= p_rgb;
        o_de  <= p_de;
        o_hs  <= p_hs;
        o_vs  <= p_vs;
    end

    assign video_rgb  = o_rgb;
    assign video_de   = o_de;
    assign video_skip = 1'b0;
    assign video_hs   = o_hs;
    assign video_vs   = o_vs;

    initial begin
        if (BX0 < HS_X + 1 || BY0 < 1)
            $error("pocket_video: the border window must start after HS / VS");
    end

endmodule

`default_nettype wire
