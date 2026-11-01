// Intellivision core: the JLP flash store (build step 11; intv_jlp): 12,288 x 16 in block RAM,
// a true dual port in Quartus's single-clock template. Port A is the copy engine's, port B the
// nonvolatile slot's (intv_jlp_nv). Each port reads its own write's data in the write's clock
// (new data); old data on a writing port is not a true-dual-port M10K mode.
//
// Its own module: written inline in intv_jlp, Quartus 21.1 left it as registers ("uninferred
// due to asynchronous read logic", 0.0.21's first gate fit), while this module alone infers
// block RAM.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_jlp_store (
    input  wire logic        clk,
    input  wire logic [13:0] a_addr,
    input  wire logic        a_we,
    input  wire logic [15:0] a_d,
    output logic      [15:0] a_q,
    input  wire logic [13:0] b_addr,
    input  wire logic        b_we,
    input  wire logic [15:0] b_d,
    output logic      [15:0] b_q
);

    logic [15:0] store [12288];

    always_ff @(posedge clk) begin
        if (a_we) begin
            store[a_addr] <= a_d;
            a_q <= a_d;
        end else
            a_q <= store[a_addr];
    end

    always_ff @(posedge clk) begin
        if (b_we) begin
            store[b_addr] <= b_d;
            b_q <= b_d;
        end else
            b_q <= store[b_addr];
    end

endmodule

`default_nettype wire
