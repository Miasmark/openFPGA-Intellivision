// Simulation stand-in for Intel's dcfifo, as agg23's data_loader uses it
// (lpm_showahead "OFF": q changes on the rdclk edge that takes rdreq;
// rdempty from the write pointer through two rdclk flip-flops). Our own
// behavioural model for Verilator; never synthesised.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module dcfifo #(
    parameter clocks_are_synchronized = "FALSE",
    parameter intended_device_family = "Cyclone V",
    parameter int lpm_numwords = 4,
    parameter lpm_showahead = "OFF",
    parameter lpm_type = "dcfifo",
    parameter int lpm_width = 8,
    parameter int lpm_widthu = 2,
    parameter overflow_checking = "OFF",
    parameter int rdsync_delaypipe = 5,
    parameter underflow_checking = "OFF",
    parameter use_eab = "OFF",
    parameter int wrsync_delaypipe = 5
) (
    input  wire logic [lpm_width-1:0] data,
    input  wire logic                 rdclk,
    input  wire logic                 rdreq,
    input  wire logic                 wrclk,
    input  wire logic                 wrreq,
    output logic      [lpm_width-1:0] q,
    output logic                      rdempty
);
    logic [lpm_width-1:0] mem [lpm_numwords];
    logic [lpm_widthu:0]  wp = '0, rp = '0, wp_s1 = '0, wp_s2 = '0;
    int                   overflows = 0;

    always_ff @(posedge wrclk) if (wrreq) begin
        if (wp - rp >= (lpm_widthu+1)'(lpm_numwords)) overflows <= overflows + 1;
        mem[wp[lpm_widthu-1:0]] <= data;
        wp <= wp + 1'b1;
    end
    always_ff @(posedge rdclk) begin
        wp_s1 <= wp;
        wp_s2 <= wp_s1;
        if (rdreq && !rdempty) begin
            q  <= mem[rp[lpm_widthu-1:0]];
            rp <= rp + 1'b1;
        end
    end
    assign rdempty = wp_s2 == rp;
endmodule

`default_nettype wire
