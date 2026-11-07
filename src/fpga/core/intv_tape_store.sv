// Intellivision core: the ECS tape store (intv_tape): 16,384 x 8 in block RAM, a true dual port
// in Quartus's single-clock template (as intv_jlp_store). Port A is the tape engine's, port B the
// nonvolatile slot's (intv_tape_nv). Each port reads its own write's data (new data).
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_tape_store (
    input  wire logic        clk,
    input  wire logic [13:0] a_addr,
    input  wire logic        a_we,
    input  wire logic [7:0]  a_d,
    output logic      [7:0]  a_q,
    input  wire logic [13:0] b_addr,
    input  wire logic        b_we,
    input  wire logic [7:0]  b_d,
    output logic      [7:0]  b_q
);

    logic [7:0] store [16384];
    initial for (int i = 0; i < 16384; i++) store[i] = 8'd0;

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
