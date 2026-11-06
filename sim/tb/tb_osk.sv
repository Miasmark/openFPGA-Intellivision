// Step-13 bench: the on-screen keypads, the on-screen ECS keyboard (1.0.4) and the game profiles
// (intv_input's keypads, keyboard and Auto mode, intv_profile, intv_osk_draw) against tools/osk.py,
// frame by frame (sim/tb/tb_osk.py).
//
// clk (clk_sys, 23.28 ns) and clk_74a (13.47 ns) as on the Pocket. A small raster gives the
// pixel clock (ce_pix every 12 clk), pf_x / pf_y over a 160 x 192 playfield inside a
// 180 x 200 frame, and the frame's start (the keypads' step), as intv_timing and pocket_video
// do for the core.
//
// +vec=FILE: one line a frame: key1 joy1 key2 joy2 mode swap crc ecs (hex; ecs bit 0 ecs_full,
// bit 1 the synthesizer setting). The bench drives frame f's words before frame f starts (line 150
// of frame f - 1), so the keypads and the keyboard step on them at the frame's start; it prints
// "S f" as frame f starts, "F f pad_r pad_l ecs_keys" at its line 100, and
// every overlay pixel of the frame that is not transparent as "P x y colour" (pocket_video's sampling: the colour
// intv_osk_draw holds at the ce_pix that ends the pixel). The CRC goes to intv_profile with
// ready set.
//
// SPDX-License-Identifier: MIT

`timescale 1ns / 1ps
`default_nettype none

module tb_osk;

    logic clk = 1'b0, clk_74a = 1'b0;
    always #11.64 clk = !clk;
    always #6.735 clk_74a = !clk_74a;

    // the raster
    localparam int H_TOTAL = 180, V_TOTAL = 200, PF_X0 = 10, PF_Y0 = 4;
    logic [3:0] sub = 4'd0;
    logic [8:0] hcnt = 9'd0, vline = 9'd0;
    wire  logic ce_pix = sub == 4'd11;
    always_ff @(posedge clk) begin
        sub <= ce_pix ? 4'd0 : sub + 4'd1;
        if (ce_pix) begin
            hcnt <= hcnt == 9'(H_TOTAL - 1) ? 9'd0 : hcnt + 9'd1;
            if (hcnt == 9'(H_TOTAL - 1))
                vline <= vline == 9'(V_TOTAL - 1) ? 9'd0 : vline + 9'd1;
        end
    end
    wire logic       in_pf = hcnt >= 9'(PF_X0) && hcnt < 9'(PF_X0 + 160) && vline >= 9'(PF_Y0) && vline < 9'(PF_Y0 + 192);
    wire logic [7:0] pf_x = 8'(hcnt - 9'(PF_X0)), pf_y = 8'(vline - 9'(PF_Y0));
    wire logic       frame = ce_pix && hcnt == 9'(H_TOTAL - 1) && vline == 9'(V_TOTAL - 1);  // the next clk starts the frame

    // the inputs (clk_74a)
    logic [31:0] key1 = 32'd0, joy1 = 32'h80808080, key2 = 32'd0, joy2 = 32'h80808080, crc = 32'd0;
    logic [1:0]  mode = 2'd0;
    logic        swap = 1'b0, efull = 1'b0, synth = 1'b0;

    wire logic [7:0]  pad_r, pad_l;
    wire logic [1:0]  osk_open;
    wire logic [7:0]  osk_cur, osk_held;
    wire logic        prof_ok;
    wire logic [1:0]  prof_mode;
    wire logic [5:0]  prof_sides;
    wire logic [71:0] labels;
    wire logic [1:0]  ovl;
    wire logic        kb_open;
    wire logic [5:0]  kb_cur, kb_held;
    wire logic [1:0]  kb_mods;
    wire logic [63:0] ecs_keys;
    /* verilator lint_off UNUSEDSIGNAL */
    wire logic        ecs_synth;
    wire logic [1:0]  ecs_ovr;
    /* verilator lint_on UNUSEDSIGNAL */

    intv_input #(.KBD_HEX(`OSK_KBD_HEX)) dut_in (
        .clk_74a(clk_74a), .clk(clk),
        .cont1_key(key1), .cont1_joy(joy1), .cont2_key(key2), .cont2_joy(joy2),
        .cont3_key(32'd0), .cont3_joy(32'd0), .cont3_trig(16'd0),
        .kp_mode(mode), .swap(swap), .ecs_ovr_74(2'd0), .synth_74(synth), .ecs_full(efull),
        .frame(frame), .prof_ok(prof_ok), .prof_mode(prof_mode), .prof_sides(prof_sides),
        .osk_open(osk_open), .osk_cur(osk_cur), .osk_held(osk_held),
        .kb_open(kb_open), .kb_cur(kb_cur), .kb_held(kb_held), .kb_mods(kb_mods),
        .pad_r(pad_r), .pad_l(pad_l), .ecs_keys(ecs_keys), .ecs_synth(ecs_synth), .ecs_ovr(ecs_ovr));

    intv_profile #(.CRC_HEX(`OSK_CRC_HEX), .PROF_HEX(`OSK_PROF_HEX)) dut_prof (
        .clk(clk), .crc(crc), .ready(1'b1),
        .ok(prof_ok), .mode(prof_mode), .sides(prof_sides), .labels(labels));

    intv_osk_draw #(.KBD_HEX(`OSK_KBD_HEX), .FONT_HEX(`OSK_FONT_HEX), .LABEL_HEX(`OSK_LABEL_HEX),
                    .LLEN_HEX(`OSK_LLEN_HEX)) dut_draw (
        .clk(clk), .ce_pix(ce_pix), .pf_x(pf_x), .pf_y(pf_y),
        .osk_open(osk_open), .osk_cur(osk_cur), .osk_held(osk_held),
        .kb_open(kb_open), .kb_cur(kb_cur), .kb_held(kb_held), .kb_mods(kb_mods),
        .prof_ok(prof_ok), .labels(labels), .ovl(ovl));

    // the overlay as pocket_video takes it
    integer fn = 0, out;
    always @(posedge clk)
        if (ce_pix && in_pf && ovl != 2'd0)
            $fdisplay(out, "P %0d %0d %0d", pf_x, pf_y, ovl);

    string vec;
    integer fd, n, f;
    logic [31:0] v [8];
    initial begin
        if (!$value$plusargs("vec=%s", vec)) begin
            $display("TB_OSK FAIL: no +vec");
            $finish;
        end
        fd = $fopen(vec, "r");
        out = $fopen("osk_out.txt", "w");
        f = 0;
        n = $fscanf(fd, "%h %h %h %h %h %h %h %h", v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]);
        while (n == 8) begin
            @(posedge clk_74a);
            #1;
            key1 = v[0]; joy1 = v[1]; key2 = v[2]; joy2 = v[3]; mode = v[4][1:0]; swap = v[5][0]; crc = v[6];
            synth = v[7][1];
            @(posedge clk);
            #1;
            efull = v[7][0];
            // frame f starts
            @(posedge clk iff frame);
            $fdisplay(out, "S %0d", f);
            @(posedge clk iff (vline == 9'd100 && ce_pix));
            $fdisplay(out, "F %0d %02x %02x %016x", f, pad_r, pad_l, ecs_keys);
            @(posedge clk iff (vline == 9'd150 && ce_pix));
            f = f + 1;
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h", v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]);
        end
        // the last frame's pixels
        @(posedge clk iff frame);
        $fclose(out);
        $display("TB_OSK done %0d frames", f);
        $finish;
    end

endmodule

`default_nettype wire
