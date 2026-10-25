// Intellivision core: the machine as build step 4 has it (DESIGN.md 9):
// the CP1610, the bus fabric, scratchpad, System RAM and GRAM, the STIC
// (backgrounds, BUSRQ, the picture) and the PSG register stub, around the
// cartridge port and the system ROMs of intv_media. No sound yet: the EXEC
// and the games run, and the bus and the picture match tools/intv_system.py
// cycle by cycle (sim/tb/tb_system.sv).
//
//   cp1610          CPU (one bus phase per ce)
//   intv_bus        address latch, decode, data-in, IAB vectors, INTRM and
//                   the bus-copy window from the frame position, the reset
//                   hold that starts the CPU on a frame, the cartridge port
//   intv_stic       STIC: registers and handshake, row fetches from System
//                   RAM (BUSRQ), cards from GROM / GRAM, the picture
//   intv_psg_regs   PSG registers and hand controllers (stub)
//   intv_ram x 3    scratchpad 256 x 8 ($0100-$01EF), System RAM 352 x 16
//                   ($0200-$035F), GRAM 512 x 8 ($3800-$3FFF)
//
// ce is the CPU cycle enable from intv_timing (ce_cpu: only while the
// machine is live), ce_pix its pixel clock (ce_stic), live high on every
// clk_sys the machine runs, hcnt / vcnt its position. mreset is the
// machine reset; the CPU starts at the frame after it ends (intv_bus).
// busrq_en = 1 is the hardware (the STIC holds the CPU for its row
// fetches); 0 is the step-3 system without BUSRQ (benches only).
//
// Save state (DESIGN.md 4.3; the ids are provisional until the step 7
// package file): all ports are OR-combined into ss_rdata. Write only while
// the machine is frozen and mreset is low. ss_en hands the block RAMs' port
// to the state port (their words read one clock after ss_addr; the others
// at once); it must drop two clocks before the machine runs again.
//   SS_CPU  ($02)        cp1610, 8 words
//   SS_BUS  ($03)        intv_bus, 2 words
//   SS_STIC ($04)        intv_stic, 55 words
//   SS_PSG  ($05)        intv_psg_regs, 14 words
//   SS_SCR  ($06)        scratchpad, 256 words
//   SS_SYS  ($07, $08)   System RAM, 352 words
//   SS_GRAM ($09, $0A)   GRAM, 512 words
//   SS_ROW  ($0C)        the STIC's row buffer, 20 words
//   SS_LINE ($0D)        the STIC's line buffer, 64 words
// The timing ($01) and the cartridge ($0B) have their own modules.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_machine #(
    parameter int         H_TOTAL   = 228,
    parameter int         V_TOTAL   = 262,
    parameter int         VB_CYCLES = 3790,
    parameter logic [7:0] SS_CPU  = 8'h02,
    parameter logic [7:0] SS_BUS  = 8'h03,
    parameter logic [7:0] SS_STIC = 8'h04,
    parameter logic [7:0] SS_PSG  = 8'h05,
    parameter logic [7:0] SS_SCR  = 8'h06,
    parameter logic [7:0] SS_SYS  = 8'h07,
    parameter logic [7:0] SS_GRAM = 8'h09,
    parameter logic [7:0] SS_ROW  = 8'h0C,
    parameter logic [7:0] SS_LINE = 8'h0D
) (
    input  wire logic        clk,
    input  wire logic        mreset,
    input  wire logic        ce,
    input  wire logic        ce_pix,
    input  wire logic        live,
    input  wire logic [8:0]  hcnt,
    input  wire logic [8:0]  vcnt,
    input  wire logic        cfg_hlt_imm,
    input  wire logic        cfg_sdbd_r6_mame,
    input  wire logic        busrq_en,
    input  wire logic [7:0]  pad_r,           // hand controllers ($FF: none)
    input  wire logic [7:0]  pad_l,

    // cartridge port and system ROMs (intv_media)
    output logic             cart_req,
    output logic             cart_we,
    output logic [15:0]      cart_addr,
    output logic [15:0]      cart_wdata,
    input  wire logic        cart_ack,
    input  wire logic [15:0] cart_rdata,
    input  wire logic        cart_hit,
    output logic [11:0]      exec_addr,
    input  wire logic [9:0]  exec_q,
    output logic [10:0]      grom_addr,
    input  wire logic [7:0]  grom_q,
    output logic [10:0]      vgrom_addr,      // the STIC's GROM port
    input  wire logic [7:0]  vgrom_q,

    output logic [3:0]       colour,          // the picture, this pixel clock

    // what the bus does (bench, later the STIC)
    output logic [2:0]       phase,
    output logic [15:0]      dout,
    output logic [15:0]      din,
    output logic [15:0]      addr,            // latched address
    output logic             fetch,
    output logic             hold,            // CPU held (reset)
    output logic             halted,

    // state port
    input  wire logic        ss_en,
    input  wire logic [15:0] ss_addr,
    input  wire logic        ss_we,
    input  wire logic [31:0] ss_wdata,
    output logic [31:0]      ss_rdata
);

    /* verilator lint_off UNUSEDSIGNAL */
    logic        wr, tci, pcit;           // not used until later steps
    logic [3:0]  ebca;
    /* verilator lint_on UNUSEDSIGNAL */
    logic        busrq, busak;
    logic [8:0]  v_sys_addr, v_gram_addr;
    logic [15:0] v_sys_q;
    logic [7:0]  v_gram_q;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [7:0]  scr_qb;                  // the scratchpad's port B is not used
    /* verilator lint_on UNUSEDSIGNAL */
    logic        intrm, rd, vb, frame_end;
    logic        scr_we, psg_we, sys_we, gram_we, stic_we;
    logic        stic_open;
    logic [15:0] stic_q, sys_q;
    logic [7:0]  scr_q, psg_q, gram_q;
    logic [31:0] ssr_cpu, ssr_bus, ssr_stic, ssr_psg, ssr_scr, ssr_sys, ssr_gram;

    cp1610 #(.SS_ID(SS_CPU)) cpu (
        .clk, .reset(hold && !ss_en), .ce, .cfg_hlt_imm, .cfg_sdbd_r6_mame,
        .phase, .dout, .din, .intrm, .intr(1'b0), .busrq, .busak,
        .ebca, .ebci(1'b0), .tci, .pcit, .halted, .fetch,
        .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_cpu));

    intv_bus #(.H_TOTAL(H_TOTAL), .V_TOTAL(V_TOTAL), .VB_CYCLES(VB_CYCLES),
               .SS_ID(SS_BUS)) bus (
        .clk, .mreset, .ce, .hcnt, .vcnt, .hold, .frame_end,
        .phase, .dout, .din, .intrm,
        .a(addr), .rd, .wr, .vb, .scr_we, .psg_we, .sys_we, .gram_we, .stic_we,
        .stic_open, .stic_q, .scr_q, .psg_q, .sys_q, .exec_q, .grom_q, .gram_q,
        .cart_req, .cart_we, .cart_wdata, .cart_ack, .cart_rdata,
        .cart_hit_in(cart_hit),
        .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_bus));

    assign cart_addr = addr;
    assign exec_addr = addr[11:0];
    assign grom_addr = addr[10:0];

    intv_stic #(.H_TOTAL(H_TOTAL), .V_TOTAL(V_TOTAL), .VB_CYCLES(VB_CYCLES),
                .SS_ID(SS_STIC), .SS_ROW(SS_ROW), .SS_LINE(SS_LINE)) stic (
        .clk, .reset(mreset), .ce, .ce_pix, .live, .hcnt, .vcnt,
        .vb, .frame_end, .a(addr), .wdata(dout), .rd, .we(stic_we),
        .open(stic_open), .q(stic_q), .intak(ce && phase == 3'd7),
        .busrq_en, .busrq, .busak,
        .sys_addr(v_sys_addr), .sys_q(v_sys_q), .gram_addr(v_gram_addr), .gram_q(v_gram_q),
        .grom_addr(vgrom_addr), .grom_q(vgrom_q), .colour,
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_stic));

    intv_psg_regs #(.SS_ID(SS_PSG)) psg (
        .clk, .reset(mreset), .n(addr[3:0]), .we(psg_we), .wdata(dout[7:0]),
        .q(psg_q), .pad_r, .pad_l,
        .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_psg));

    intv_ram #(.AW(8), .DW(8), .WORDS(256), .SS_ID(SS_SCR)) scratch (
        .clk, .addr(addr[7:0]), .we(scr_we), .d(dout[7:0]), .q(scr_q),
        .addr_b(8'd0), .q_b(scr_qb),
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_scr));

    intv_ram #(.AW(9), .DW(16), .WORDS(352), .SS_ID(SS_SYS)) sysram (
        .clk, .addr(addr[8:0]), .we(sys_we), .d(dout), .q(sys_q),
        .addr_b(v_sys_addr), .q_b(v_sys_q),
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_sys));

    intv_ram #(.AW(9), .DW(8), .WORDS(512), .SS_ID(SS_GRAM)) gram (
        .clk, .addr(addr[8:0]), .we(gram_we), .d(dout[7:0]), .q(gram_q),
        .addr_b(v_gram_addr), .q_b(v_gram_q),
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_gram));

    assign ss_rdata = ssr_cpu | ssr_bus | ssr_stic | ssr_psg | ssr_scr | ssr_sys | ssr_gram;

endmodule

`default_nettype wire
