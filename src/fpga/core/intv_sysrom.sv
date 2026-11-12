// Intellivision core: the system ROMs in block RAM (DESIGN.md 3 module 8,
// 5.1, 5.6).
//
//   EXEC     4,096 x 10   from exec.bin (8,192 bytes, big-endian words,
//                         10 bits used); CPU $1000-$1FFF (build step 3)
//   GROM     2,048 x 8    from grom.bin; CPU and STIC $3000-$37FF (step 4)
//   IVOICE   2,048 x 8    from ivoice.bin, the SP0256-012 resident ROM, as
//                         the file holds it (step 10 decides the bit order)
//   WBEXEC   4,096 x 10   (1.0.8) the second half of wbexec.bin (bytes 8,192-16,383): the
//                         TutorVision EXEC's $2000-$2FFF, read with the EXEC's address
//   WBGROM   2,048 x 8    (1.0.8) wbgrom.bin, the INTV88's GROM: with font set (taken at
//                         machine reset) both GROM ports read it instead of grom.bin
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
    input  wire logic [2:0]  wsel,            // 0 EXEC, 1 GROM, 2 IVOICE, 3 WBEXEC, 4 WBGROM
    input  wire logic [11:0] waddr,
    input  wire logic [9:0]  wdata,
    input  wire logic        font,            // 1.0.8: the GROM ports read WBGROM

    input  wire logic [11:0] exec_addr,
    output logic      [9:0]  exec_q,
    output logic      [9:0]  wbx_q,           // 1.0.8: WBEXEC at exec_addr
    input  wire logic [10:0] grom_addr,
    output logic      [7:0]  grom_q,
    input  wire logic [10:0] vgrom_addr,
    output logic      [7:0]  vgrom_q,
    input  wire logic [10:0] ivoice_addr,
    output logic      [7:0]  ivoice_q
);

    logic [9:0] exec_mem   [4096];
    logic [9:0] wbx_mem    [4096];
    logic [7:0] grom_mem   [2048];
    logic [7:0] wbg_mem    [2048];
    logic [7:0] ivoice_mem [2048];
    logic [7:0] g_q, vg_q, wg_q, vwg_q;

    always_ff @(posedge clk) begin
        if (we && wsel == 3'd0) exec_mem[waddr] <= wdata;
        exec_q <= exec_mem[exec_addr];
    end
    always_ff @(posedge clk) begin
        if (we && wsel == 3'd3) wbx_mem[waddr] <= wdata;
        wbx_q <= wbx_mem[exec_addr];
    end
    always_ff @(posedge clk) begin
        if (we && wsel == 3'd1) grom_mem[waddr[10:0]] <= wdata[7:0];
        g_q <= grom_mem[grom_addr];
    end
    always_ff @(posedge clk)
        vg_q <= grom_mem[vgrom_addr];
    always_ff @(posedge clk) begin
        if (we && wsel == 3'd4) wbg_mem[waddr[10:0]] <= wdata[7:0];
        wg_q <= wbg_mem[grom_addr];
    end
    always_ff @(posedge clk)
        vwg_q <= wbg_mem[vgrom_addr];
    assign grom_q  = font ? wg_q : g_q;
    assign vgrom_q = font ? vwg_q : vg_q;
    always_ff @(posedge clk) begin
        if (we && wsel == 3'd2) ivoice_mem[waddr[10:0]] <= wdata[7:0];
        ivoice_q <= ivoice_mem[ivoice_addr];
    end

endmodule

`default_nettype wire
