// Simulation stand-in for the APF template's mf_datatable (altsyncram,
// 256 x 32, BIDIR_DUAL_PORT, address and output registered on each port's
// clock: two clocks of read latency, new data on a read during a write).
// Our own behavioural model for Verilator; never synthesised.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module mf_datatable (
    input  wire logic [7:0]  address_a,
    input  wire logic [7:0]  address_b,
    input  wire logic        clock_a,
    input  wire logic        clock_b,
    input  wire logic [31:0] data_a,
    input  wire logic [31:0] data_b,
    input  wire logic        wren_a,
    input  wire logic        wren_b,
    output logic      [31:0] q_a,
    output logic      [31:0] q_b
);
    logic [31:0] mem [256];
    logic [31:0] ra = 32'd0, rb = 32'd0;
    initial for (int i = 0; i < 256; i++) mem[i] = 32'd0;

    always_ff @(posedge clock_a) begin
        if (wren_a) begin mem[address_a] <= data_a; ra <= data_a; end
        else ra <= mem[address_a];
        q_a <= ra;
    end
    always_ff @(posedge clock_b) begin
        if (wren_b) begin mem[address_b] <= data_b; rb <= data_b; end
        else rb <= mem[address_b];
        q_b <= rb;
    end
endmodule

`default_nettype wire
