// Simulation model of the Pocket's SRAM, an AS6C2016-55 (128K x 16,
// asynchronous, 55 ns), with its timing checked in clk_sys half periods
// (11.64 ns): the controls are sampled on every falling clk_sys edge, half
// a cycle after the controller changes them on the rising edge.
//
//   read   data are valid once the address and OE have been stable for 3
//          samples (2.5 clk_sys = 58.2 ns >= tAA 55 ns); before that, and
//          for a byte whose UB/LB is high, the model returns garbage
//          ($BAD0 ^ address), so a controller that samples early fails
//   write  WE must be low for at least 2 samples (>= 1.5 clk_sys = 34.9 ns
//          measured this way, i.e. a pulse of 2 full clk_sys = 46.6 ns >=
//          tWP 45 ns), the address must not change while WE is low, DQ must
//          be driven throughout and still at the sample after WE rises
//          (data hold); the word is written with the byte enables seen
//          while WE was low
//   OE low while the controller drives DQ is a bus fight
// Each broken rule counts in `violations`. Memory starts as $DEAD ^ address,
// not 0, so anything the loader must clear or write shows.
//
// Our own behavioural model for Verilator; never synthesised.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module sram_as6c2016 (
    input  wire logic        clk,
    input  wire logic [16:0] a,
    input  wire logic [15:0] dq_w,            // controller's DQ output
    input  wire logic        dq_oe,           // controller drives DQ
    output logic      [15:0] dq_r,            // what the controller reads
    input  wire logic        oe_n,
    input  wire logic        we_n,
    input  wire logic        ub_n,
    input  wire logic        lb_n
);
    logic [15:0] mem [131072];
    int          violations = 0;
    int          writes = 0;

    initial for (int i = 0; i < 131072; i++) mem[i] = 16'hDEAD ^ i[15:0];

    // ---------------------------------------------------------------- read
    logic [16:0] ra = 17'd0;
    int          age = 0;
    always @(negedge clk) begin
        if (!oe_n && we_n) begin
            age <= (age != 0 && a == ra) ? age + 1 : 1;
            ra  <= a;
        end else
            age <= 0;
    end
    wire logic ok = age >= 3 && a == ra && !oe_n && we_n;
    always_comb begin
        dq_r = 16'hBAD0 ^ a[15:0];
        if (ok && !ub_n) dq_r[15:8] = mem[a][15:8];
        if (ok && !lb_n) dq_r[7:0]  = mem[a][7:0];
    end

    // --------------------------------------------------------------- write
    logic        w_on = 1'b0;
    int          w_n = 0;
    logic [16:0] w_a;
    logic [15:0] w_d;
    logic        w_ub, w_lb;
    always @(negedge clk) begin
        if (dq_oe && !oe_n) violations <= violations + 1;          // bus fight
        if (!we_n) begin
            if (!dq_oe) violations <= violations + 1;
            if (w_on && (a != w_a || dq_w != w_d)) violations <= violations + 1;
            if (!w_on) begin w_a <= a; w_d <= dq_w; end
            w_ub <= !ub_n;
            w_lb <= !lb_n;
            w_n  <= w_on ? w_n + 1 : 1;
            w_on <= 1'b1;
        end else if (w_on) begin
            w_on <= 1'b0;
            if (w_n < 2 || !dq_oe || dq_w != w_d || a != w_a)
                violations <= violations + 1;
            else begin
                if (w_ub) mem[w_a][15:8] <= w_d[15:8];
                if (w_lb) mem[w_a][7:0]  <= w_d[7:0];
                writes <= writes + 1;
            end
        end
    end
endmodule

`default_nettype wire
