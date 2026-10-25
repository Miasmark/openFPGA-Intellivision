// Step 1 bench (DESIGN.md 9): the master timing, the clock enables, the
// video windows and the Pocket video port, and intv_timing's state port.
//
//   sim/tb/run_tb_timing.sh      (builds with Verilator, runs, checks)
//
// Clocks as the PLL makes them (core/pll/pll_core.v): clk_sys 42.954545 MHz
// and clk_vid = clk_sys / 12, rising edges together. +vidph=N (0-11) moves
// clk_vid's edge N clk_sys cycles against the reset, which on the board is
// arbitrary; +border=0/1 picks the scaler mode (slot 0: 160 x 192, slot 1:
// 167 x 210). Every check prints a line; the last line is
// "TB_TIMING pass" or "TB_TIMING FAIL (n)".
//
// SPDX-License-Identifier: MIT

`timescale 1ns / 1fs
`default_nettype none

module tb_timing;

    // clk_sys = 12 x 3.579545454 MHz: half period 11.640211 ns
    localparam real HALF = 1.0e9 / (12.0 * 315.0e6 / 88.0) / 2.0;

    logic clk_sys = 1'b0, clk_vid = 1'b0;
    int   vidph = 0, border = 1, frames = 3;
    int   fails = 0;

    task automatic check(input bit ok, input string what);
        $display("  %s  %s", ok ? "ok  " : "FAIL", what);
        if (!ok) fails++;
    endtask

    // ---------------------------------------------------------------- DUT
    logic        reset = 1'b1, run = 1'b1;
    logic        ce_pix, ce_psg, ce_cpu;
    logic [8:0]  hcnt, vcnt, vline;
    logic [15:0] ss_addr = 16'h0100;
    logic        ss_we = 1'b0;
    logic [31:0] ss_wdata = 32'd0, ss_rdata;

    intv_timing dut (
        .clk(clk_sys), .reset(reset), .run(run),
        .ce_pix(ce_pix), .ce_psg(ce_psg), .ce_cpu(ce_cpu),
        .hcnt(hcnt), .vcnt(vcnt), .vline(vline),
        .ss_addr(ss_addr), .ss_we(ss_we), .ss_wdata(ss_wdata), .ss_rdata(ss_rdata)
    );

    logic        in_pf;
    logic [7:0]  pf_x, pf_y;
    logic [3:0]  colour;
    // slots: cart ok, cfg empty, EXEC ok, GROM other size, ECS empty, IVOICE ok
    localparam logic [11:0] SLOT_ST = {2'd2, 2'd0, 2'd1, 2'd2, 2'd0, 2'd2};

    test_pattern pattern (
        .in_pf(in_pf), .pf_x(pf_x), .pf_y(pf_y),
        .slot_st(SLOT_ST), .slot_req(6'b001101), .colour(colour)
    );

    logic [23:0] video_rgb;
    logic        video_de, video_skip, video_hs, video_vs;

    pocket_video video (
        .clk_sys(clk_sys), .ce_pix(ce_pix), .hcnt(hcnt), .vline(vline),
        .border_on(border[0]),
        .in_pf(in_pf), .pf_x(pf_x), .pf_y(pf_y), .colour(colour),
        .clk_vid(clk_vid),
        .video_rgb(video_rgb), .video_de(video_de), .video_skip(video_skip),
        .video_hs(video_hs), .video_vs(video_vs)
    );

    // A second timing instance for the state round trip, and a PAL-sized one
    // (DESIGN.md 2.4: 256 x 312 estimated) to exercise the parameters.
    logic        b_reset = 1'b1, b_run = 1'b0;
    logic        b_ce_pix, b_ce_psg, b_ce_cpu;
    logic [8:0]  b_hcnt, b_vcnt, b_vline;
    logic [15:0] b_ss_addr = 16'h0100;
    logic        b_ss_we = 1'b0;
    logic [31:0] b_ss_wdata = 32'd0, b_ss_rdata;

    intv_timing dut_b (
        .clk(clk_sys), .reset(b_reset), .run(b_run),
        .ce_pix(b_ce_pix), .ce_psg(b_ce_psg), .ce_cpu(b_ce_cpu),
        .hcnt(b_hcnt), .vcnt(b_vcnt), .vline(b_vline),
        .ss_addr(b_ss_addr), .ss_we(b_ss_we), .ss_wdata(b_ss_wdata), .ss_rdata(b_ss_rdata)
    );

    logic        p_ce_pix, p_ce_psg, p_ce_cpu;
    logic [8:0]  p_hcnt, p_vcnt, p_vline;
    logic [31:0] p_ss_rdata;

    intv_timing #(.H_TOTAL(256), .V_TOTAL(312), .V_VS(30)) dut_pal (
        .clk(clk_sys), .reset(reset), .run(1'b1),
        .ce_pix(p_ce_pix), .ce_psg(p_ce_psg), .ce_cpu(p_ce_cpu),
        .hcnt(p_hcnt), .vcnt(p_vcnt), .vline(p_vline),
        .ss_addr(16'h0000), .ss_we(1'b0), .ss_wdata(32'd0), .ss_rdata(p_ss_rdata)
    );

    // ------------------------------------------------------------- clocks
    int ph = 0;
    initial begin
        forever begin
            #HALF;
            clk_sys = 1'b1;
            if (ph == vidph) clk_vid = 1'b1;
            if (ph == (vidph + 6) % 12) clk_vid = 1'b0;
            ph = (ph + 1) % 12;
            #HALF;
            clk_sys = 1'b0;
        end
    end

    // ----------------------------------------- counts in the clk_sys domain
    // Per frame of the STIC (vcnt wrapping to 0): enables, lines, clk_sys.
    longint sys_cyc = 0;
    int n_pix = 0, n_psg = 0, n_cpu = 0, n_line = 0, max_h = 0, max_v = 0;
    int f_pix[$], f_psg[$], f_cpu[$], f_line[$], f_cyc[$];
    longint frame_start_cyc = -1;
    bit counting = 0;
    int bad_phase = 0, line_cyc = 0, bad_line_len = 0, last_line_start = -1;
    int p_n_cpu = 0, p_frames[$];
    bit p_counting = 0;

    always @(posedge clk_sys) begin
        sys_cyc++;
        if (!reset) begin
            if (int'(hcnt) > max_h) max_h = int'(hcnt);
            if (int'(vcnt) > max_v) max_v = int'(vcnt);
            // CPU and PSG enables only on pixel enables, at fixed pixel phases
            if (ce_cpu && !(ce_pix && hcnt[1:0] == 2'd3)) bad_phase++;
            if (ce_psg && !(ce_pix && hcnt[0])) bad_phase++;
            if (ce_pix && hcnt == 9'd227 && vcnt == 9'd261) begin
                // the last pixel of a frame: close the count
                if (counting) begin
                    f_pix.push_back(n_pix + 1); f_psg.push_back(n_psg + int'(ce_psg));
                    f_cpu.push_back(n_cpu + int'(ce_cpu)); f_line.push_back(n_line + 1);
                    f_cyc.push_back(int'(sys_cyc - frame_start_cyc));
                end
                counting = 1; n_pix = 0; n_psg = 0; n_cpu = 0; n_line = 0;
                frame_start_cyc = sys_cyc;
            end else if (counting) begin
                n_pix += int'(ce_pix); n_psg += int'(ce_psg); n_cpu += int'(ce_cpu);
                if (ce_pix && hcnt == 9'd227) n_line++;
            end
            // vline is vcnt moved by 30, wrapping
            if (int'(vline) != (int'(vcnt) + 262 - 30) % 262) bad_phase++;
            // PAL-sized instance: CPU cycles per frame
            if (p_ce_pix && p_hcnt == 9'd255 && p_vcnt == 9'd311) begin
                if (p_counting) p_frames.push_back(p_n_cpu + int'(p_ce_cpu));
                p_counting = 1; p_n_cpu = 0;
            end else if (p_counting)
                p_n_cpu += int'(p_ce_cpu);
        end
    end

    // ------------------------------------------- the Pocket's side, clk_vid
    real    t_vs[$];
    int     vs_n = 0, hs_in_frame = 0, de_lines = 0, de_px = 0;
    int     line_px[$], frame_hs[$], frame_lines[$], vid_cyc[$];
    int     vid_cyc_n = 0;
    int     vs_hs_clash = 0, de_on_sync = 0, slot_bad = 0, slot_seen = 0, skip_seen = 0;
    bit     prev_de = 0, started = 0;
    logic [23:0] lines_rgb [0:239][0:199];   // captured active pixels of the last frame
    int     cap_y = 0;

    always @(posedge clk_vid) begin
        if (!reset) begin
            vid_cyc_n++;
            if (video_skip) skip_seen++;
            if (video_vs && video_hs) vs_hs_clash++;
            if (video_de && (video_vs || video_hs)) de_on_sync++;
            if (video_vs) begin
                if (started) begin
                    frame_hs.push_back(hs_in_frame);
                    frame_lines.push_back(de_lines);
                    vid_cyc.push_back(vid_cyc_n);
                end
                t_vs.push_back($realtime);
                started = 1; hs_in_frame = 0; de_lines = 0; vid_cyc_n = 0; cap_y = 0;
            end
            if (video_hs && started) hs_in_frame++;
            if (video_de) begin
                if (cap_y < 240 && de_px < 200) lines_rgb[cap_y][de_px] = video_rgb;
                de_px++;
            end
            if (!video_de && prev_de) begin
                // first pixel after the line's active pixels: the scaler slot
                slot_seen++;
                if (video_rgb != {8'd0, 3'(border), 13'd0}) slot_bad++;
                if (started) begin
                    line_px.push_back(de_px);
                    de_lines++;
                    cap_y++;
                end
                de_px = 0;
            end
            prev_de = video_de;
        end
    end

    // ------------------------------------------------------------- script
    function automatic string ql(int q[$]);
        string r = "";
        foreach (q[i]) r = {r, (i ? " " : ""), $sformatf("%0d", q[i])};
        return {"[", r, "]"};
    endfunction

    function automatic bit all_eq(int q[$], int v);
        foreach (q[i]) if (q[i] != v) return 0;
        return q.size() > 0;
    endfunction

    // Expected RGB of the test pattern (intv_palette, MAME's values)
    function automatic logic [23:0] pal(int i);
        logic [23:0] t [16] = '{24'h000000, 24'h002DFF, 24'hFF3D10, 24'hC9CFAB, 24'h386B3F, 24'h00A756,
                                24'hFAEA50, 24'hFFFCFF, 24'hBDACC8, 24'h24B8FF, 24'hFFB41F, 24'h546E00,
                                24'hFF4E57, 24'hA496FF, 24'h75CC80, 24'hB51A58};
        return t[i];
    endfunction

    logic [31:0] saved;
    int          mism;

    initial begin
        void'($value$plusargs("vidph=%d", vidph));
        void'($value$plusargs("border=%d", border));
        void'($value$plusargs("frames=%d", frames));
        $display("tb_timing: vidph %0d, border %0d, %0d frames", vidph, border, frames);
        repeat (37) @(posedge clk_sys);
        reset = 1'b0;
        b_reset = 1'b0;

        // Let the Pocket side see frames + 1 VS pulses.
        while (t_vs.size() < frames + 2) @(posedge clk_vid);
        @(posedge clk_sys);

        $display("-- clk_sys side (STIC frame)");
        check(max_h == 227 && max_v == 261, $sformatf("hcnt 0..%0d, vcnt 0..%0d (228 x 262)", max_h, max_v));
        check(all_eq(f_pix, 228 * 262), $sformatf("pixel clocks per frame %s (59,736)", ql(f_pix)));
        check(all_eq(f_cpu, 57 * 262), $sformatf("CPU cycles per frame %s (14,934)", ql(f_cpu)));
        check(all_eq(f_psg, 114 * 262), $sformatf("PSG clocks per frame %s (29,868)", ql(f_psg)));
        check(all_eq(f_line, 262), $sformatf("lines per frame %s", ql(f_line)));
        check(all_eq(f_cyc, 12 * 228 * 262), $sformatf("clk_sys per frame %s (716,832)", ql(f_cyc)));
        check(bad_phase == 0, $sformatf("CPU / PSG enables on pixel phases 3 / odd, vline = vcnt - 30 mod 262 (%0d bad)", bad_phase));
        check(all_eq(p_frames, 64 * 312), $sformatf("PAL-sized instance (256 x 312): CPU cycles per frame %s (19,968)", ql(p_frames)));

        $display("-- Pocket side (clk_vid)");
        begin
            real period = (t_vs[t_vs.size() - 1] - t_vs[1]) / real'(t_vs.size() - 2);
            real hz = 1.0e9 / period;
            check(hz > 59.92 && hz < 59.925, $sformatf("frame rate %.5f Hz (59.92275 from the PLL's clk_sys)", hz));
        end
        check(all_eq(vid_cyc, 228 * 262), $sformatf("pixel clocks VS to VS %s", ql(vid_cyc)));
        check(all_eq(frame_hs, 262), $sformatf("HS pulses per frame %s", ql(frame_hs)));
        check(all_eq(frame_lines, border ? 210 : 192), $sformatf("active lines per frame %s (%0d)", ql(frame_lines), border ? 210 : 192));
        check(all_eq(line_px, border ? 167 : 160), $sformatf("active pixels per line: %0d lines, all %0d: %0d",
              line_px.size(), border ? 167 : 160, all_eq(line_px, border ? 167 : 160)));
        check(vs_hs_clash == 0 && de_on_sync == 0, $sformatf("HS never on the VS pixel, DE never on HS / VS (%0d, %0d)", vs_hs_clash, de_on_sync));
        check(slot_seen > 0 && slot_bad == 0, $sformatf("scaler slot %0d in rgb[23:13] after every line (%0d lines, %0d bad)", border, slot_seen, slot_bad));
        check(skip_seen == 0, "video_skip never set");

        $display("-- picture (last frame)");
        begin
            int ox = border ? 3 : 0, oy = border ? 9 : 0;
            bit ok = 1;
            // border: blue all round
            if (border) begin
                ok &= lines_rgb[0][0] == pal(1) && lines_rgb[209][166] == pal(1) && lines_rgb[100][1] == pal(1)
                      && lines_rgb[100][164] == pal(1);
                check(ok, "border window: blue border (corners, left and right sides)");
            end
            ok = 1;
            for (int y = 0; y < 192; y++) begin
                ok &= lines_rgb[oy + y][ox] == pal(7) && lines_rgb[oy + y][ox + 159] == pal(7);
            end
            for (int x = 0; x < 160; x++)
                ok &= lines_rgb[oy][ox + x] == pal(7) && lines_rgb[oy + 191][ox + x] == pal(7);
            check(ok, "playfield edge ring white (crop marks)");
            ok = 1;
            for (int y = 1; y < 96; y++)
                for (int x = 1; x < 159; x++)
                    ok &= lines_rgb[oy + y][ox + x] == pal(x / 10);
            check(ok, "colour bars: 16 bars of 10 pixels in colour order, lines 1-95");
            ok = 1;
            for (int y = 96; y < 176; y++)
                for (int x = 1; x < 159; x++)
                    ok &= lines_rgb[oy + y][ox + x] == ((((x / 8) ^ (y / 16)) & 1) ? pal(7) : pal(0));
            check(ok, "card checkerboard 8 x 16, lines 96-175");
            ok = 1;
            // indicators: cart ok (green), cfg empty optional (grey), EXEC ok,
            // GROM other size (yellow), ECS empty (grey), IVOICE ok
            begin
                int want [6] = '{5, 8, 5, 6, 8, 5};
                for (int s = 0; s < 6; s++)
                    ok &= lines_rgb[oy + 184][ox + s * 16 + 8] == pal(want[s]);
                ok &= lines_rgb[oy + 184][ox + 120] == pal(0);
            end
            check(ok, "slot indicators: green / grey / green / yellow / grey / green, then black");
        end

        $display("-- state port (DESIGN.md 4.3)");
        // Freeze, read the state word, check nothing moves while frozen.
        @(posedge clk_sys);
        run = 1'b0;
        @(posedge clk_sys);
        saved = ss_rdata;
        begin
            bit still = 1, no_ce = 1;
            repeat (1000) begin
                @(posedge clk_sys);
                still &= ss_rdata == saved;
                no_ce &= !ce_pix && !ce_psg && !ce_cpu;
            end
            check(still && no_ce, $sformatf("frozen (run = 0): state word %08x held 1000 clk_sys, no enables", saved));
        end
        // Restore into the second instance (reset at another time, never run)
        b_ss_wdata = saved;
        b_ss_we = 1'b1;
        @(posedge clk_sys);
        b_ss_we = 1'b0;
        @(negedge clk_sys);
        check(b_ss_rdata == saved, $sformatf("restored word reads back %08x", b_ss_rdata));
        // Both run from the same edge: identical from then on
        @(negedge clk_sys);
        run = 1'b1;
        b_run = 1'b1;
        mism = 0;
        repeat (12 * 228 * 262 + 1000) begin
            @(negedge clk_sys);
            if ({ce_pix, ce_psg, ce_cpu, hcnt, vcnt, vline} != {b_ce_pix, b_ce_psg, b_ce_cpu, b_hcnt, b_vcnt, b_vline})
                mism++;
        end
        check(mism == 0, $sformatf("restored copy runs in lockstep for a frame (%0d mismatching cycles)", mism));
        // Word 1 and other module ids read 0 (ports are OR-combined)
        ss_addr = 16'h0101;
        #1;
        check(ss_rdata == 0, "word 1 reads 0");
        ss_addr = 16'h0200;
        #1;
        check(ss_rdata == 0, "another module id reads 0");

        $display("TB_TIMING %s", fails == 0 ? "pass" : $sformatf("FAIL (%0d)", fails));
        $finish;
    end

    initial begin
        #(200.0e6);   // 200 ms of simulated time
        $display("TB_TIMING FAIL (timeout)");
        $finish;
    end

endmodule

`default_nettype wire
