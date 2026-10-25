// Intellivision core: the system ROMs in block RAM (DESIGN.md 3 module 8,
// 5.1, 5.6).
//
//   EXEC     4,096 x 10   from exec.bin (8,192 bytes, big-endian words,
//                         10 bits used); CPU $1000-$1FFF (build step 3)
//   GROM     2,048 x 8    from grom.bin; CPU and STIC $3000-$37FF (step 4)
//   IVOICE   2,048 x 8    from ivoice.bin, the SP0256-012 resident ROM, as
//                         the file holds it (step 10 decides the bit order)
//
// The ECS ROM (12,288 x 10) is in the SRAM instead (intv_media.sv).
// Written by the loader at load time; each has one read port with one clk
// of latency, GROM a second one for the STIC (vgrom_addr / vgrom_q, step
// 4). ROMs are not machine state (DESIGN.md 4.4).
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_sysrom (
    input  wire logic        clk,

    // loader writes
    input  wire logic        we,
    input  wire logic [1:0]  wsel,            // 0 EXEC, 1 GROM, 2 IVOICE
    input  wire logic [11:0] waddr,
    input  wire logic [9:0]  wdata,

    input  wire logic [11:0] exec_addr,
    output logic      [9:0]  exec_q,
    input  wire logic [10:0] grom_addr,
    output logic      [7:0]  grom_q,
    input  wire logic [10:0] vgrom_addr,
    output logic      [7:0]  vgrom_q,
    input  wire logic [10:0] ivoice_addr,
    output logic      [7:0]  ivoice_q
);

    logic [9:0] exec_mem   [4096];
    logic [7:0] grom_mem   [2048];
    logic [7:0] ivoice_mem [2048];

    always_ff @(posedge clk) begin
        if (we && wsel == 2'd0) exec_mem[waddr] <= wdata;
        exec_q <= exec_mem[exec_addr];
    end
    always_ff @(posedge clk) begin
        if (we && wsel == 2'd1) grom_mem[waddr[10:0]] <= wdata[7:0];
        grom_q <= grom_mem[grom_addr];
    end
    always_ff @(posedge clk)
        vgrom_q <= grom_mem[vgrom_addr];
    always_ff @(posedge clk) begin
        if (we && wsel == 2'd2) ivoice_mem[waddr[10:0]] <= wdata[7:0];
        ivoice_q <= ivoice_mem[ivoice_addr];
    end

endmodule

`default_nettype wire
