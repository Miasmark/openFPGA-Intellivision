// Step 1 bench (DESIGN.md 9): the master timing, the clock enables, the
// video windows and the Pocket video port, and intv_timing's state port.
//
// The raster must never stop: the run freezes the machine (DESIGN.md 4.2)
// twice, 40 lines from mid-frame and 300 lines from VBlank (the second
// 5 clk_sys into a pixel, so at a nonzero sub), then a state restore
// refuses three out-of-frame words and loads another machine position, and
// a saved word is restored
// into a second instance whose raster is at another phase. Through all of
// it HS, VS and DE must stay exact (228 pixel clocks per line, 262 lines,
// 59.92 Hz), the picture is black in frames where the machine is frozen,
// the machine resumes exactly on its saved clk_sys and loses whole frames
// only (or, after a restore, runs as the saved machine did).
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
    logic        ce_pix, live, ce_stic, ce_psg, ce_cpu;
    logic [8:0]  hcnt, vcnt, vline;
    logic [15:0] ss_addr = 16'h0100;
    logic        ss_we = 1'b0;
    logic [31:0] ss_wdata = 32'd0, ss_rdata;

    intv_timing dut (
        .clk(clk_sys), .reset(reset), .run(run),
        .ce_pix(ce_pix), .hcnt(hcnt), .vcnt(vcnt), .vline(vline),
        .live(live), .ce_stic(ce_stic), .ce_psg(ce_psg), .ce_cpu(ce_cpu),
        .ss_addr(ss_addr), .ss_we(ss_we), .ss_wdata(ss_wdata), .ss_rdata(ss_rdata)
    );
    // the raster position, as the state word packs it
    wire logic [21:0] rpos = {vcnt, hcnt, dut.sub};

    logic        in_pf;
    logic [7:0]  pf_x, pf_y;
    logic [3:0]  colour;
    // slots: cart ok, cfg empty, EXEC ok, GROM other size, ECS empty, IVOICE ok
    localparam logic [11:0] SLOT_ST = {2'd2, 2'd0, 2'd1, 2'd2, 2'd0, 2'd2};

    test_pattern pattern (
        .in_pf(in_pf), .pf_x(pf_x), .pf_y(pf_y),
        .slot_st(SLOT_ST), .slot_req(6'b001101), .len_st(2'd2), .cfg_res(3'd2),
        // the load diagnostics (0.0.14): open file timed out, waiting for Ready to run's ok,
        // all complete seen, no 0x0082, a 0x008A, waiting for the fetch
        .fetch_to(3'b010), .tstate(4'd14), .d_ac(1'b1), .d_req(1'b0), .d_upd(1'b1), .d_phase(2'd1),
        .colour(colour)
    );

    logic [23:0] video_rgb;
    logic        video_de, video_skip, video_hs, video_vs;

    pocket_video video (
        .clk_sys(clk_sys), .ce_pix(ce_pix), .hcnt(hcnt), .vline(vline),
        .border_on(border[0]), .blank(!live),
        .in_pf(in_pf), .pf_x(pf_x), .pf_y(pf_y), .colour(colour),
        .clk_vid(clk_vid),
        .video_rgb(video_rgb), .video_de(video_de), .video_skip(video_skip),
        .video_hs(video_hs), .video_vs(video_vs)
    );

    // A second timing instance for the state round trip (out of reset
    // 100,003 clk_sys later, so its raster is at another phase, and never
    // run before the restore), and a PAL-sized one (DESIGN.md 2.4: 256 x 312
    // estimated) to exercise the parameters.
    logic        b_reset = 1'b1, b_run = 1'b0;
    logic        b_ce_pix, b_live, b_ce_stic, b_ce_psg, b_ce_cpu;
    logic [8:0]  b_hcnt, b_vcnt, b_vline;
    logic [15:0] b_ss_addr = 16'h0100;
    logic        b_ss_we = 1'b0;
    logic [31:0] b_ss_wdata = 32'd0, b_ss_rdata;

    intv_timing dut_b (
        .clk(clk_sys), .reset(b_reset), .run(b_run),
        .ce_pix(b_ce_pix), .hcnt(b_hcnt), .vcnt(b_vcnt), .vline(b_vline),
        .live(b_live), .ce_stic(b_ce_stic), .ce_psg(b_ce_psg), .ce_cpu(b_ce_cpu),
        .ss_addr(b_ss_addr), .ss_we(b_ss_we), .ss_wdata(b_ss_wdata), .ss_rdata(b_ss_rdata)
    );
    wire logic [21:0] b_rpos = {b_vcnt, b_hcnt, dut_b.sub};
    initial begin
        repeat (37 + 100003) @(posedge clk_sys);
        b_reset = 1'b0;
    end

    logic        p_ce_pix, p_live, p_ce_stic, p_ce_psg, p_ce_cpu;
    logic [8:0]  p_hcnt, p_vcnt, p_vline;
    logic [31:0] p_ss_rdata;

    intv_timing #(.H_TOTAL(256), .V_TOTAL(312), .V_VS(30)) dut_pal (
        .clk(clk_sys), .reset(reset), .run(1'b1),
        .ce_pix(p_ce_pix), .hcnt(p_hcnt), .vcnt(p_vcnt), .vline(p_vline),
        .live(p_live), .ce_stic(p_ce_stic), .ce_psg(p_ce_psg), .ce_cpu(p_ce_cpu),
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
    // Per frame of the raster (vcnt wrapping to 0): pixel clocks, lines,
    // clk_sys; machine enables for the frames the machine ran throughout.
    longint sys_cyc = 0, tot_pix = 0, tot_stic = 0;
    int n_pix = 0, n_psg = 0, n_cpu = 0, n_line = 0, max_h = 0, max_v = 0;
    int f_pix[$], f_psg[$], f_cpu[$], f_line[$], f_cyc[$];
    longint frame_start_cyc = -1;
    bit counting = 0, all_live = 1;
    int bad_phase = 0, frozen_ce = 0;
    int p_n_cpu = 0, p_frames[$];
    bit p_counting = 0;
    // machine-enable streams of the round trip: {ce_cpu, ce_psg, vcnt, hcnt}
    bit cap_a = 0, cap_b = 0;
    int q_a[$], q_b[$];
    localparam int CAP_N = 228 * 262 + 500;

    always @(posedge clk_sys) begin
        sys_cyc++;
        if (!reset) begin
            if (int'(hcnt) > max_h) max_h = int'(hcnt);
            if (int'(vcnt) > max_v) max_v = int'(vcnt);
            tot_pix += int'(ce_pix); tot_stic += int'(ce_stic);
            // machine enables only while live, on pixel enables, CPU and PSG
            // at fixed pixel phases
            if (ce_stic && !(ce_pix && live)) bad_phase++;
            if (ce_cpu && !(ce_stic && hcnt[1:0] == 2'd3)) bad_phase++;
            if (ce_psg && !(ce_stic && hcnt[0])) bad_phase++;
            if (!run && (live || ce_stic || ce_psg || ce_cpu)) frozen_ce++;
            all_live &= live;
            if (ce_pix && hcnt == 9'd227 && vcnt == 9'd261) begin
                // the last pixel of a frame: close the count
                if (counting) begin
                    f_pix.push_back(n_pix + 1); f_line.push_back(n_line + 1);
                    f_cyc.push_back(int'(sys_cyc - frame_start_cyc));
                    if (all_live) begin
                        f_psg.push_back(n_psg + int'(ce_psg)); f_cpu.push_back(n_cpu + int'(ce_cpu));
                    end
                end
                counting = 1; n_pix = 0; n_psg = 0; n_cpu = 0; n_line = 0; all_live = 1;
                frame_start_cyc = sys_cyc;
            end else if (counting) begin
                n_pix += int'(ce_pix); n_psg += int'(ce_psg); n_cpu += int'(ce_cpu);
                if (ce_pix && hcnt == 9'd227) n_line++;
            end
            if (cap_a && ce_stic && q_a.size() < CAP_N) q_a.push_back({ce_cpu, ce_psg, 3'd0, vcnt, hcnt});
            if (cap_b && b_ce_stic && q_b.size() < CAP_N) q_b.push_back({b_ce_cpu, b_ce_psg, 3'd0, b_vcnt, b_hcnt});
            // vline is vcnt moved by 30, wrapping
            if (int'(vline) != (int'(vcnt) + 262 - 30) % 262) bad_phase++;
            // PAL-sized instance: CPU cycles per frame
            if (p_ce_stic && p_hcnt == 9'd255 && p_vcnt == 9'd311) begin
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
    // HS to HS always one line, DE always the same distance after HS
    longint vid_n = 0, last_hs = -1;
    int     hs_gaps = 0, hs_gap_bad = 0, de_off = -1, de_off_bad = 0;
    // frames in which the machine was frozen throughout: black
    bit     live_q = 1, f_any_live = 0;
    int     frozen_frames = 0, frozen_lit = 0, f_lit = 0;
    always @(negedge clk_sys) live_q <= live;

    always @(posedge clk_vid) begin
        if (!reset) begin
            vid_cyc_n++;
            vid_n++;
            if (video_skip) skip_seen++;
            if (video_vs && video_hs) vs_hs_clash++;
            if (video_de && (video_vs || video_hs)) de_on_sync++;
            if (video_vs) begin
                if (started) begin
                    frame_hs.push_back(hs_in_frame);
                    frame_lines.push_back(de_lines);
                    vid_cyc.push_back(vid_cyc_n);
                    if (!f_any_live) begin
                        frozen_frames++;
                        frozen_lit += f_lit;
                    end
                end
                t_vs.push_back($realtime);
                started = 1; hs_in_frame = 0; de_lines = 0; vid_cyc_n = 0; cap_y = 0;
                f_any_live = 0; f_lit = 0;
            end
            f_any_live |= live_q;
            if (video_hs) begin
                if (last_hs >= 0) begin
                    hs_gaps++;
                    if (vid_n - last_hs != 228) hs_gap_bad++;
                end
                last_hs = vid_n;
            end
            if (video_de && !prev_de && last_hs >= 0) begin
                if (de_off < 0) de_off = int'(vid_n - last_hs);
                else if (de_off != int'(vid_n - last_hs)) de_off_bad++;
            end
            if (video_hs && started) hs_in_frame++;
            if (video_de) begin
                if (cap_y < 240 && de_px < 200) lines_rgb[cap_y][de_px] = video_rgb;
                if (video_rgb != 24'd0) f_lit++;
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

    // wait (at negedges) until the raster reaches line v, pixel h
    task automatic wait_pos(input int v, input int h);
        int n = 0;
        do begin
            @(negedge clk_sys);
            n++;
        end while (!(vcnt == 9'(v) && hcnt == 9'(h)) && n < 2 * 12 * 228 * 262);
    endtask

    // Freeze the machine for nlines lines, then run: the state word holds,
    // no machine enable, the machine resumes on exactly the saved position
    // and has lost exactly `lost` whole frames.
    task automatic freeze_for(input int nlines, input int lost, input string what,
                              input int skew = 0);
        longint d0, d1;
        logic [31:0] w;
        bit still = 1, no_ce = 1;
        int n = 0;
        // skew clk_sys more before the freeze: the saved position then has
        // a nonzero sub
        repeat (skew) @(negedge clk_sys);
        d0 = tot_pix - tot_stic;
        run = 1'b0;
        @(negedge clk_sys);
        w = ss_rdata;
        repeat (nlines * 228 * 12) begin
            @(negedge clk_sys);
            still &= ss_rdata == w;
            no_ce &= !live && !ce_stic && !ce_psg && !ce_cpu;
        end
        check(still && no_ce, $sformatf("%s: frozen %0d lines at state word %08x (line %0d): word held, no machine enable",
              what, nlines, w, w[21:13]));
        run = 1'b1;
        while (!live && n < 2 * 12 * 228 * 262) begin
            @(negedge clk_sys);
            n++;
        end
        check(live && {10'd0, rpos} == w, $sformatf("%s: resumes when the raster reaches the saved position (%06x, saved %08x)",
              what, rpos, w));
        repeat (5000) @(negedge clk_sys);
        d1 = tot_pix - tot_stic;
        check(d1 - d0 == longint'(lost) * 228 * 262, $sformatf("%s: machine lost %0d pixel clocks (%0d whole frames: %0d)",
              what, d1 - d0, lost, lost * 228 * 262));
    endtask

    initial begin
        void'($value$plusargs("vidph=%d", vidph));
        void'($value$plusargs("border=%d", border));
        void'($value$plusargs("frames=%d", frames));
        $display("tb_timing: vidph %0d, border %0d, %0d frames", vidph, border, frames);
        repeat (37) @(posedge clk_sys);
        reset = 1'b0;

        // Two frames running, then the machine frozen and restored while the
        // raster runs on.
        while (t_vs.size() < 3) @(posedge clk_vid);
        $display("-- freezes and restores (the raster runs on)");
        wait_pos(150, 100);
        freeze_for(40, 1, "mid-frame");
        repeat (12 * 228 * 100) @(negedge clk_sys);
        wait_pos(10, 33);
        freeze_for(300, 2, "VBlank", 5);

        // Restore: frozen in VBlank, another machine position loaded.
        begin
            logic [31:0] w4 = {10'd0, 9'd5, 9'd77, 4'd4};
            bit still = 1, no_ce = 1;
            int n = 0;
            wait_pos(20, 50);
            run = 1'b0;
            repeat (12 * 228 * 10) @(negedge clk_sys);
            // out-of-frame words are refused: the held word stays
            begin
                logic [31:0] w0 = ss_rdata;
                logic [31:0] bad [3] = '{{10'd0, 9'd5, 9'd77, 4'd12},
                                         {10'd0, 9'd5, 9'd228, 4'd4},
                                         {10'd0, 9'd262, 9'd77, 4'd4}};
                bit kept = 1;
                foreach (bad[i]) begin
                    ss_wdata = bad[i];
                    ss_we = 1'b1;
                    @(negedge clk_sys);
                    ss_we = 1'b0;
                    kept &= ss_rdata == w0;
                end
                check(kept, $sformatf("restore: out-of-frame words (sub 12, pixel 228, line 262) refused, word stays %08x", w0));
            end
            ss_wdata = w4;
            ss_we = 1'b1;
            @(negedge clk_sys);
            ss_we = 1'b0;
            check(ss_rdata == w4, $sformatf("restore: loaded word reads back %08x", ss_rdata));
            repeat (12 * 228 * 10) begin
                @(negedge clk_sys);
                still &= ss_rdata == w4;
                no_ce &= !live && !ce_stic && !ce_psg && !ce_cpu;
            end
            check(still && no_ce, "restore: word held, no machine enable while frozen");
            run = 1'b1;
            while (!live && n < 2 * 12 * 228 * 262) begin
                @(negedge clk_sys);
                n++;
            end
            check(live && rpos == w4[21:0], $sformatf("restore: resumes when the raster reaches the loaded position (%06x)", rpos));
        end

        // Round trip: freeze, save, restore into dut_b (raster at another
        // phase), run both: the same machine-enable stream from the restore.
        $display("-- state round trip into a second instance (DESIGN.md 4.3)");
        repeat (12 * 228 * 50) @(negedge clk_sys);
        wait_pos(12, 200);
        run = 1'b0;
        @(negedge clk_sys);
        saved = ss_rdata;
        b_ss_wdata = saved;
        b_ss_we = 1'b1;
        @(negedge clk_sys);
        b_ss_we = 1'b0;
        check(b_ss_rdata == saved, $sformatf("restored word reads back %08x", b_ss_rdata));
        check(b_rpos != rpos, $sformatf("second raster at another position (%06x, first %06x)", b_rpos, rpos));
        cap_a = 1;
        cap_b = 1;
        run = 1'b1;
        b_run = 1'b1;
        while (q_a.size() < CAP_N || q_b.size() < CAP_N) @(negedge clk_sys);
        mism = 0;
        foreach (q_a[i]) if (q_a[i] != q_b[i]) mism++;
        check(mism == 0 && q_a[0][17:0] == {saved[21:13], saved[12:4]},
              $sformatf("restored copy replays the machine from line %0d pixel %0d for a frame (%0d of %0d enables differ)",
              saved[21:13], saved[12:4], mism, CAP_N));
        // Word 1 and other module ids read 0 (ports are OR-combined)
        ss_addr = 16'h0101;
        #1;
        check(ss_rdata == 0, "word 1 reads 0");
        ss_addr = 16'h0200;
        #1;
        check(ss_rdata == 0, "another module id reads 0");
        ss_addr = 16'h0100;

        // frames more, running throughout (the picture check uses the last)
        begin
            int v0 = t_vs.size();
            while (t_vs.size() < v0 + frames + 1) @(posedge clk_vid);
        end
        @(posedge clk_sys);

        $display("-- clk_sys side (STIC frame)");
        check(max_h == 227 && max_v == 261, $sformatf("hcnt 0..%0d, vcnt 0..%0d (228 x 262)", max_h, max_v));
        check(all_eq(f_pix, 228 * 262), $sformatf("pixel clocks per frame, every frame %s (59,736)", ql(f_pix)));
        check(all_eq(f_line, 262), $sformatf("lines per frame %s", ql(f_line)));
        check(all_eq(f_cyc, 12 * 228 * 262), $sformatf("clk_sys per frame %s (716,832)", ql(f_cyc)));
        check(f_cpu.size() >= frames && all_eq(f_cpu, 57 * 262),
              $sformatf("CPU cycles per frame, frames running throughout %s (14,934)", ql(f_cpu)));
        check(all_eq(f_psg, 114 * 262), $sformatf("PSG clocks per frame, same frames %s (29,868)", ql(f_psg)));
        check(f_pix.size() > f_cpu.size(), $sformatf("%0d frames had the machine frozen for a while", f_pix.size() - f_cpu.size()));
        check(bad_phase == 0, $sformatf("machine enables only while live, CPU / PSG on pixel phases 3 / odd, vline = vcnt - 30 mod 262 (%0d bad)", bad_phase));
        check(frozen_ce == 0, $sformatf("no machine enable while run = 0 (%0d)", frozen_ce));
        check(all_eq(p_frames, 64 * 312), $sformatf("PAL-sized instance (256 x 312): CPU cycles per frame %s (19,968)", ql(p_frames)));

        $display("-- Pocket side (clk_vid)");
        begin
            real period = (t_vs[t_vs.size() - 1] - t_vs[1]) / real'(t_vs.size() - 2);
            real hz = 1.0e9 / period;
            check(hz > 59.92 && hz < 59.925, $sformatf("frame rate %.5f Hz (59.92275 from the PLL's clk_sys)", hz));
        end
        check(all_eq(vid_cyc, 228 * 262), $sformatf("pixel clocks VS to VS %s", ql(vid_cyc)));
        check(hs_gaps > 262 * 10 && hs_gap_bad == 0, $sformatf("HS to HS 228 pixel clocks, %0d lines (%0d not)", hs_gaps, hs_gap_bad));
        check(de_off > 0 && de_off_bad == 0, $sformatf("DE starts %0d pixel clocks after HS on every line (%0d not)", de_off, de_off_bad));
        check(frozen_frames >= 1 && frozen_lit == 0, $sformatf("frames with the machine frozen throughout: %0d, black (%0d lit pixels)",
              frozen_frames, frozen_lit));
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
            // GROM other size (yellow), ECS empty (grey), IVOICE ok; the
            // cartridge's second card its length source (len_st 2: orange),
            // the CFG's second card the CFG fetch (cfg_res 2: cyan)
            begin
                int want [6] = '{5, 8, 5, 6, 8, 5};
                for (int s = 0; s < 6; s++) begin
                    ok &= lines_rgb[oy + 184][ox + s * 16 + 3] == pal(want[s]);
                    if (s > 1) ok &= lines_rgb[oy + 184][ox + s * 16 + 12] == pal(want[s]);
                end
                ok &= lines_rgb[oy + 184][ox + 28] == pal(9);
                ok &= lines_rgb[oy + 184][ox + 12] == pal(10);
            end
            check(ok, "slot indicators: green+orange / grey+cyan / green / yellow / grey / green");
            // the load diagnostics, cards 12-17, then black: red (open timed out), yellow
            // (Ready to run), green (all complete), black (no 0x0082), green (0x008A), cyan
            begin
                int want [7] = '{2, 6, 5, 0, 5, 9, 0};
                ok = 1;
                for (int c = 0; c < 7; c++) ok &= lines_rgb[oy + 184][ox + (12 + c) * 8 + 3] == pal(want[c]);
            end
            check(ok, "load diagnostics: red / yellow / green / black / green / cyan, then black");
        end

        $display("TB_TIMING %s", fails == 0 ? "pass" : $sformatf("FAIL (%0d)", fails));
        $finish;
    end

    initial begin
        #(600.0e6);   // 600 ms of simulated time
        $display("TB_TIMING FAIL (timeout)");
        $finish;
    end

endmodule

`default_nettype wire
