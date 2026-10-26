// Step-6 bench: intv_input against vectors from sim/tb/tb_input.py.
//
// Two clocks, as on the Pocket: clk (clk_sys, 23.28 ns) and clk_74a (13.47
// ns on average, its period drawn anew each cycle between 12.5 and 14.5 ns,
// so its edges slide over every phase of clk). The inputs are clk_74a
// signals: they change only after a clk_74a edge and are settled before
// the next one.
//
// Part 1, +vec=FILE: each line is class key1 joy1 key2 joy2 key3 joy3 trig3
// mode swap ecs_ovr synth ecs pad_r pad_l keys_hi keys_lo, in hex (step 9:
// the ECS settings, ecs = the clk side's ecs_on, and the ECS keyboard's
// switches ecs_keys; ecs_ovr and ecs_synth must come out as they went in). The bench drives the inputs 1 ns after a
// clk_74a edge, waits 16 clocks (the crossing's handshake takes at most
// about 7 clk + 4 clk_74a periods, then the output register) and compares
// both bytes. It prints the first 20 mismatches and a count per class.
//
// Part 2, +tear=FILE (the crossing, DESIGN.md 7): groups of vectors, each
// a line "n" and then n lines of key1 .. swap pad_r pad_l. For each group
// the bench drives the first vector and lets it settle, then changes the
// inputs among the group's vectors at random clk_74a edges (held 1 to 24
// clk_74a cycles) for 64 changes. A change is not atomic: as the bits of a
// clk_74a bus leave their registers and cross the routing, each bit takes
// its new value at one of four moments 1.5, 4.5, 7.5 or 10.5 ns after the
// edge (drawn per bit and per change), all before the next clk_74a edge.
// At every clk edge both bytes must be the bytes of one of the group's
// vectors: a word torn between two vectors, as a bit-by-bit crossing gives
// when a clk edge falls between those moments, is a failure. At the end
// the last vector must be on the outputs. The bench also counts how often
// the outputs changed, to show the words do get across while they change.
//
// That input model cannot see a fault in the handshake itself: hold_74 is
// a register and changes all at once in a zero-delay simulation. Two more
// checks cover the handshake:
// - the handshake rule (both builds): at a clk_74a edge where a transfer
//   is in flight (req_74 != ack: the clk side has not loaded the copy
//   since the request), hold_74 must not change; the bench counts the
//   copies taken and the loads made;
// - the copy's routing (built with -DTB_SKEW, tb_input.py's skew build:
//   in intv_input.sv's always_ff @(posedge clk) blocks hold_74 and req_74
//   read hold_v and req_v instead, which this bench drives): each bit of
//   hold_74, and req_74, reaches the clk side after its own delay, one of
//   eight moments from 0.5 to 19.75 ns (twice the SDC's 10 ns bound, just
//   under one clk period), drawn again for every group. So a clk side that
//   loads the copy before every bit has arrived, or crosses a registered
//   copy bit by bit, shows torn bytes.
// What neither can show is metastability: a load decided on the request's
// first flip-flop (req_s[0]) passes here. sim/check/fit_crossing_check.py
// checks after a fit that the metastability report has req_74 and ack
// crossing through two flip-flops each, and the net delays.
//
// It prints TB_INPUT pass or TB_INPUT FAIL.
//
// SPDX-License-Identifier: MIT

`timescale 1ns/1ps
`default_nettype none

module tb_input;

    localparam int W = 6 * 32 + 16 + 2 + 1 + 3;

    logic        clk = 1'b0;
    logic        clk_74a = 1'b0;
    logic [W-1:0] bus = '0;          // {key1, joy1, key2, joy2, key3, joy3, trig3, mode, swap, ecs_ovr, synth}
    wire  [7:0]  pad_r, pad_l;
    logic        ecs_on = 1'b0;      // clk side: the ECS attached (step 9)
    wire  [63:0] ecs_keys;
    wire         ecs_synth;
    wire  [1:0]  ecs_ovr;

    always #11.64 clk = ~clk;

    // --------------------------------------------------------------- skew
`ifdef TB_SKEW
    // The clk side's view of hold_74 and req_74 (dut.hold_v, dut.req_v):
    // bit i arrives msk_k[i]'s moment after it changes, req_74 at moment
    // rk. Delays are fixed per group, so changes arrive in order.
    localparam int NM = 8;
    real          dly [NM];
    logic [W-1:0] msk [NM];
    int           rk;

    task automatic draw_skew();
        logic [W-1:0] r0, r1, r2;
        r0 = rbits();
        r1 = rbits();
        r2 = rbits();
        for (int k = 0; k < NM; k++)
            msk[k] = ({W{k[0]}} ~^ r0) & ({W{k[1]}} ~^ r1) & ({W{k[2]}} ~^ r2);
        rk = $urandom % NM;
    endtask

    task automatic carry_hold(input int k);
        forever begin
            @(dut.hold_74);
            begin
                automatic logic [W-1:0] b = dut.hold_74;
                automatic logic [W-1:0] mk = msk[k];
                automatic real d = dly[k];
                fork
                    begin
                        #(d);
                        dut.hold_v = (dut.hold_v & ~mk) | (b & mk);
                    end
                join_none
            end
        end
    endtask

    task automatic carry_req();
        forever begin
            @(dut.req_74);
            begin
                automatic logic v = dut.req_74;
                automatic real d = dly[rk];
                fork
                    begin
                        #(d);
                        dut.req_v = v;
                    end
                join_none
            end
        end
    endtask

    initial begin
        for (int k = 0; k < NM; k++)
            dly[k] = 0.5 + 2.75 * k;
        draw_skew();
        dut.hold_v = dut.hold_74;
        dut.req_v = dut.req_74;
        for (int k = 0; k < NM; k++) begin
            automatic int kk = k;
            fork
                carry_hold(kk);
            join_none
        end
        fork
            carry_req();
        join_none
    end
`endif

    // ------------------------------------------------- the handshake rule
    // hold_74 must not change at a clk_74a edge while a transfer is in
    // flight (req_74 != ack, both before the edge). A copy is a request
    // toggle; a load is an acknowledge toggle.
    int ncopy = 0, nload = 0, nflight = 0;
    always @(posedge clk_74a) begin
        automatic logic inflight = dut.req_74 != dut.ack;
        automatic logic r = dut.req_74;
        automatic logic [W-1:0] h = dut.hold_74;
        #0.1;
        if (dut.req_74 != r)
            ncopy++;
        if (inflight && dut.hold_74 !== h) begin
            if (nflight < 10)
                $display("  FAIL  handshake at %0t: hold_74 changed while a transfer was in flight", $time);
            nflight++;
        end
    end
    always @(posedge clk) begin
        automatic logic a = dut.ack;
        #0.1;
        if (dut.ack != a)
            nload++;
    end

    // clk_74a: period 12.5 .. 14.5 ns, high for half of it
    real p74;
    initial begin
        forever begin
            p74 = 12.5 + 2.0 * ($urandom % 1001) / 1000.0;
            clk_74a = 1'b1;
            #(p74 / 2.0);
            clk_74a = 1'b0;
            #(p74 / 2.0);
        end
    end

    intv_input dut (
        .clk_74a    ( clk_74a ),
        .clk        ( clk ),
        .cont1_key  ( bus[213:182] ),
        .cont1_joy  ( bus[181:150] ),
        .cont2_key  ( bus[149:118] ),
        .cont2_joy  ( bus[117:86] ),
        .cont3_key  ( bus[85:54] ),
        .cont3_joy  ( bus[53:22] ),
        .cont3_trig ( bus[21:6] ),
        .kp_mode    ( bus[5:4] ),
        .swap       ( bus[3] ),
        .ecs_ovr_74 ( bus[2:1] ),
        .synth_74   ( bus[0] ),
        .ecs_on     ( ecs_on ),
        .pad_r      ( pad_r ),
        .pad_l      ( pad_l ),
        .ecs_keys   ( ecs_keys ),
        .ecs_synth  ( ecs_synth ),
        .ecs_ovr    ( ecs_ovr )
    );

    function automatic logic [W-1:0] pack(input logic [31:0] f [17]);
        pack = {f[1], f[2], f[3], f[4], f[5], f[6], f[7][15:0], f[8][1:0], f[9][0], f[10][1:0], f[11][0]};
    endfunction

    // W random bits
    function automatic logic [W-1:0] rbits();
        logic [W-1:0] v;
        for (int i = 0; i < W; i += 32)
            v[i +: 32] = $urandom;
        rbits = v;
    endfunction

    // One clk_74a change from a to b, each bit at one of four moments
    task automatic skewed(input logic [W-1:0] a, input logic [W-1:0] b);
        logic [W-1:0] r1, r2, d;
        r1 = rbits();
        r2 = rbits();
        d = a ^ b;
        #1.5  bus = a ^ (d & ~r1 & ~r2);
        #3.0  bus = a ^ (d & ~r1);
        #3.0  bus = a ^ (d & ~(r1 & r2));
        #3.0  bus = b;
    endtask

    int fd, n, cls, nvec, nbad, ngrp, nchk, nchg, ntear;
    int cnt [16], bad [16];
    logic [31:0] f [17];
    logic [W-1:0] gv [16];
    logic [15:0]  ge [16];
    logic [15:0]  prev;
    int gn, cur, nxt, hold;
    bit ok1, done;
    string path;

    initial begin
        nvec = 0;
        nbad = 0;
        ngrp = 0;
        #1;     // before the first clock edge
        // Power-up value: no button pressed reads $FF on both ports
        if (pad_r !== 8'hFF || pad_l !== 8'hFF) begin
            $display("  FAIL  power-up pad_r %h pad_l %h, want FF FF", pad_r, pad_l);
            nbad++;
        end
        for (int i = 0; i < 16; i++) begin cnt[i] = 0; bad[i] = 0; end

        // ---------------------------------------------------- part 1
        if ($value$plusargs("vec=%s", path)) begin
            fd = $fopen(path, "r");
            if (fd == 0) begin
                $display("TB_INPUT FAIL (cannot open %s)", path);
                $finish;
            end
            while (!$feof(fd)) begin
                n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                            f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8], f[9], f[10], f[11],
                            f[12], f[13], f[14], f[15], f[16]);
                if (n != 17) begin
                    if (n > 0) begin
                        $display("  FAIL  vector %0d: %0d fields", nvec, n);
                        nbad++;
                    end
                    break;
                end
                cls = f[0];
                @(posedge clk_74a);
                #1 bus = pack(f);
                ecs_on = f[12][0];
                repeat (16) @(posedge clk);
                #1;
                cnt[cls & 15]++;
                if (pad_r !== f[13][7:0] || pad_l !== f[14][7:0] || ecs_keys !== {f[15], f[16]}
                    || ecs_ovr !== f[10][1:0] || ecs_synth !== f[11][0]) begin
                    bad[cls & 15]++;
                    if (nbad < 20)
                        $display("  FAIL  class %0d vector %0d: k1 %h j1 %h k2 %h j2 %h k3 %h j3 %h t3 %h mode %0d swap %0d ovr %0d synth %0d ecs %0d: pad_r %h pad_l %h keys %h ovr %0d synth %0d, want %h %h %h%h",
                                 cls, nvec, f[1], f[2], f[3], f[4], f[5], f[6], f[7][15:0], f[8][1:0], f[9][0],
                                 f[10][1:0], f[11][0], f[12][0],
                                 pad_r, pad_l, ecs_keys, ecs_ovr, ecs_synth, f[13][7:0], f[14][7:0], f[15], f[16]);
                    nbad++;
                end
                nvec++;
            end
            $fclose(fd);
            for (int i = 0; i < 16; i++)
                if (cnt[i] != 0)
                    $display("  %s class %0d: %0d vectors, %0d wrong", bad[i] == 0 ? "ok  " : "FAIL", i, cnt[i], bad[i]);
            $display("%0d vectors, %0d wrong", nvec, nbad);
        end

        // ---------------------------------------------------- part 2
        if ($value$plusargs("tear=%s", path)) begin
            fd = $fopen(path, "r");
            if (fd == 0) begin
                $display("TB_INPUT FAIL (cannot open %s)", path);
                $finish;
            end
            ngrp = 0; nchk = 0; nchg = 0; ntear = 0;
            while (!$feof(fd)) begin
                n = $fscanf(fd, "%h\n", gn);
                if (n != 1)
                    break;
                if (gn < 2 || gn > 16) begin
                    $display("  FAIL  group %0d: %0d vectors", ngrp, gn);
                    nbad++;
                    break;
                end
                ecs_on = 1'b0;
                for (int i = 0; i < gn; i++) begin
                    f[0] = 0;
                    n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h\n",
                                f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8], f[9], f[13], f[14]);
                    f[10] = $urandom % 3;               // the ECS settings: they change nothing on the pads
                    f[11] = $urandom % 2;
                    gv[i] = pack(f);
                    ge[i] = {f[13][7:0], f[14][7:0]};
                end
                // settle on the first vector
`ifdef TB_SKEW
                draw_skew();
`endif
                @(posedge clk_74a);
                #1 bus = gv[0];
                repeat (16) @(posedge clk);
                cur = 0;
                prev = {pad_r, pad_l};
                // 64 changes at random clk_74a edges, checked at every clk edge
                done = 1'b0;
                fork
                    begin
                        for (int c = 0; c < 64; c++) begin
                            hold = 1 + $urandom % 24;
                            repeat (hold) @(posedge clk_74a);
                            nxt = (cur + 1 + $urandom % (gn - 1)) % gn;
                            skewed(gv[cur], gv[nxt]);
                            cur = nxt;
                        end
                        repeat (2) @(posedge clk_74a);
                        done = 1'b1;
                    end
                    begin
                        while (!done) begin
                            @(posedge clk);
                            #0.5;
                            nchk++;
                            if ({pad_r, pad_l} != prev) nchg++;
                            prev = {pad_r, pad_l};
                            ok1 = 1'b0;
                            for (int i = 0; i < gn; i++)
                                if ({pad_r, pad_l} === ge[i]) ok1 = 1'b1;
                            if (!ok1) begin
                                if (ntear < 20)
                                    $display("  FAIL  tear group %0d at %0t: pad_r %h pad_l %h is no vector's (inputs now %h)",
                                             ngrp, $time, pad_r, pad_l, bus);
                                ntear++;
                            end
                        end
                    end
                join
                repeat (16) @(posedge clk);
                #1;
                if ({pad_r, pad_l} !== ge[cur]) begin
                    if (ntear < 20)
                        $display("  FAIL  tear group %0d: settled on pad_r %h pad_l %h, want %h %h",
                                 ngrp, pad_r, pad_l, ge[cur][15:8], ge[cur][7:0]);
                    ntear++;
                end
                ngrp++;
            end
            $fclose(fd);
            $display("  %s tear: %0d groups, %0d clk edges checked, %0d output changes, %0d torn or wrong",
                     (ntear == 0 && ngrp > 0) ? "ok  " : "FAIL", ngrp, nchk, nchg, ntear);
            if (ngrp == 0 || nchg < ngrp)
                ntear++;
            nbad += ntear;
        end

        // the handshake rule over the whole run
        $display("  %s handshake: %0d copies, %0d loads, %0d copies changed in flight",
                 (nflight == 0 && nload > 0) ? "ok  " : "FAIL", ncopy, nload, nflight);
        if (nflight != 0 || nload == 0)
            nbad++;
`ifdef TB_SKEW
        $display("  skew: the copy's bits and the request reach clk 0.5 to 19.75 ns after they change");
`endif

        $display("TB_INPUT %s", (nbad == 0 && nvec + ngrp > 0) ? "pass" : "FAIL");
        $finish;
    end

endmodule

`default_nettype wire
