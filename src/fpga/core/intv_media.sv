// Intellivision core: cartridge and system ROM storage (build step 2;
// DESIGN.md 5.1, 5.2, 5.6).
//
//   intv_loader   the data slots' bytes into SRAM and block RAM, CRC32, the
//                 CRC table lookup and the page table
//   intv_cart     page table, page selects, the CPU bus's cartridge port,
//                 and the save-state port of what the loader leaves behind
//   intv_sysrom   EXEC, GROM and Intellivoice ROMs in block RAM
//   intv_sram     the controller for the Pocket's SRAM
//
// SRAM map (128K x 16 words):
//   $00000-$0FFFF  plane 1: the cartridge image at file offsets (64K words)
//   $10000-$12FFF  ECS ROM, 12K words, as ecs.bin holds it (step 9 maps it)
//   $13000-$17FFF  free (JLP RAM, step 11)
//   $18000-$1BFFF  cartridge RAM, 16K cells (cleared at load)
//   $1C000-$1FFFF  free
//
// Three SRAM masters, fixed priority: the loader (only while loading, when
// the machine is held in reset), the cartridge port, and an auxiliary port
// (the ECS module from step 9; the bench reads the stored image with it).
// Each holds its request until ack.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_media #(
    parameter             CRC_HEX    = "core/tables/cart_crc.hex",
    parameter             LAYOUT_HEX = "core/tables/cart_layouts.hex",
    parameter logic [7:0] SS_ID      = 8'h0B
) (
    input  wire logic        clk,
    input  wire logic        reset,           // power-on
    input  wire logic        mreset,          // machine reset (page selects)

    // data_loader bytes and the data table's cartridge length
    input  wire logic        ld_wr,
    input  wire logic [27:0] ld_addr,
    input  wire logic [7:0]  ld_data,
    input  wire logic        len_valid,       // clk_74a (apf_datatable)
    input  wire logic [31:0] cart_len,        // held while len_valid is high
    input  wire logic [1:0]  len_chk,         // apf_datatable, held like cart_len

    // CPU bus: cartridge
    input  wire logic        bus_req,
    input  wire logic        bus_we,
    input  wire logic [15:0] bus_addr,
    input  wire logic [15:0] bus_wdata,
    output logic             bus_ack,
    output logic [15:0]      bus_rdata,
    output logic             bus_hit,
    output logic [1:0]       bus_kind,
    output logic             bus_paged,

    // auxiliary SRAM port
    input  wire logic        aux_req,
    input  wire logic        aux_we,
    input  wire logic [16:0] aux_addr,
    input  wire logic [15:0] aux_wdata,
    input  wire logic [1:0]  aux_be,
    output logic             aux_ack,
    output logic [15:0]      aux_rdata,

    // system ROMs
    input  wire logic [11:0] exec_addr,
    output logic      [9:0]  exec_q,
    input  wire logic [10:0] grom_addr,
    output logic      [7:0]  grom_q,
    input  wire logic [10:0] vgrom_addr,      // the STIC's GROM port (step 4)
    output logic      [7:0]  vgrom_q,
    input  wire logic [10:0] ivoice_addr,
    output logic      [7:0]  ivoice_q,

    // status
    output logic             ready,
    output logic             busy,
    output logic [4:0]       err,
    output logic [1:0]       len_st,          // len_chk of the last load (test pattern)
    output logic [11:0]      slot_st,
    output logic [31:0]      crc,
    output logic [16:0]      words,
    output logic [7:0]       layout,
    output logic [7:0]       flags,
    output logic             hit,

    // save state
    input  wire logic [15:0] ss_addr,
    input  wire logic        ss_we,
    input  wire logic [31:0] ss_wdata,
    output logic [31:0]      ss_rdata,

    // SRAM pins (the tristate is at the top level)
    output logic [16:0]      sram_a,
    output logic [15:0]      sram_dq_out,
    output logic             sram_dq_oe,
    input  wire logic [15:0] sram_dq_in,
    output logic             sram_oe_n,
    output logic             sram_we_n,
    output logic             sram_ub_n,
    output logic             sram_lb_n
);

    localparam logic [16:0] RAM_BASE = 17'h18000;

    // len_valid crosses from clk_74a; cart_len and len_chk are held from one
    // clk_74a before it rises (apf_datatable), so they are stable when seen here
    logic [2:0] lv_s = 3'd0;
    always_ff @(posedge clk) lv_s <= {lv_s[1:0], len_valid};

    // -------------------------------------------------------------- loader
    logic        l_req, l_ack;
    logic [16:0] l_addr;
    logic [15:0] l_wdata;
    logic [1:0]  l_be;
    logic        rom_we;
    logic [1:0]  rom_wsel;
    logic [11:0] rom_waddr;
    logic [9:0]  rom_wdata;
    logic        pt_we, res_we, res_hit;
    logic [4:0]  pt_idx;
    logic [15:0] pt_data;
    logic [31:0] res_crc;
    logic [16:0] res_words;
    logic [7:0]  res_layout, res_flags;

    intv_loader #(
        .CRC_HEX(CRC_HEX), .LAYOUT_HEX(LAYOUT_HEX),
        .ECS_BASE(17'h10000), .RAM_BASE(RAM_BASE), .RAM_CELLS(16384)
    ) loader (
        .clk(clk), .reset(reset),
        .ld_wr(ld_wr), .ld_addr(ld_addr), .ld_data(ld_data),
        .len_valid(lv_s[2]), .cart_len(cart_len), .len_chk(len_chk),
        .m_req(l_req), .m_addr(l_addr), .m_wdata(l_wdata), .m_be(l_be), .m_ack(l_ack),
        .rom_we(rom_we), .rom_wsel(rom_wsel), .rom_waddr(rom_waddr), .rom_wdata(rom_wdata),
        .pt_we(pt_we), .pt_idx(pt_idx), .pt_data(pt_data),
        .res_we(res_we), .res_crc(res_crc), .res_words(res_words),
        .res_layout(res_layout), .res_flags(res_flags), .res_hit(res_hit),
        .busy(busy), .ready(ready), .err(err), .len_st(len_st), .slot_st(slot_st)
    );

    // ---------------------------------------------------------- cartridge
    logic        c_req, c_we, c_ack;
    logic [16:0] c_addr;
    logic [15:0] c_wdata;
    logic [1:0]  c_be;

    intv_cart #(.SS_ID(SS_ID), .RAM_BASE(RAM_BASE)) cart (
        .clk(clk), .mreset(mreset),
        .ld_pt_we(pt_we), .ld_pt_idx(pt_idx), .ld_pt_data(pt_data),
        .ld_res_we(res_we), .ld_crc(res_crc), .ld_words(res_words),
        .ld_layout(res_layout), .ld_flags(res_flags), .ld_hit(res_hit),
        .crc(crc), .words(words), .layout(layout), .flags(flags), .hit(hit),
        .bus_req(bus_req), .bus_we(bus_we), .bus_addr(bus_addr), .bus_wdata(bus_wdata),
        .bus_ack(bus_ack), .bus_rdata(bus_rdata), .bus_hit(bus_hit),
        .bus_kind(bus_kind), .bus_paged(bus_paged),
        .m_req(c_req), .m_we(c_we), .m_addr(c_addr), .m_wdata(c_wdata), .m_be(c_be),
        .m_ack(c_ack), .m_rdata(aux_rdata),
        .ss_addr(ss_addr), .ss_we(ss_we), .ss_wdata(ss_wdata), .ss_rdata(ss_rdata)
    );

    // -------------------------------------------------------- system ROMs
    intv_sysrom sysrom (
        .clk(clk),
        .we(rom_we), .wsel(rom_wsel), .waddr(rom_waddr), .wdata(rom_wdata),
        .exec_addr(exec_addr), .exec_q(exec_q),
        .grom_addr(grom_addr), .grom_q(grom_q),
        .vgrom_addr(vgrom_addr), .vgrom_q(vgrom_q),
        .ivoice_addr(ivoice_addr), .ivoice_q(ivoice_q)
    );

    // ----------------------------------------------------- SRAM, arbiter
    logic        s_rdy, s_ack;
    logic [1:0]  pick, gnt = 2'd0;
    logic        s_req, s_we;
    logic [16:0] s_addr;
    logic [15:0] s_wdata, s_rdata;
    logic [1:0]  s_be;

    always_comb begin
        pick = l_req ? 2'd0 : c_req ? 2'd1 : 2'd2;
        s_req = l_req || c_req || aux_req;
        case (pick)
            2'd0:    {s_we, s_addr, s_wdata, s_be} = {1'b1, l_addr, l_wdata, l_be};
            2'd1:    {s_we, s_addr, s_wdata, s_be} = {c_we, c_addr, c_wdata, c_be};
            default: {s_we, s_addr, s_wdata, s_be} = {aux_we, aux_addr, aux_wdata, aux_be};
        endcase
    end
    always_ff @(posedge clk)
        if (s_req && s_rdy) gnt <= pick;

    assign l_ack   = s_ack && gnt == 2'd0;
    assign c_ack   = s_ack && gnt == 2'd1;
    assign aux_ack = s_ack && gnt == 2'd2;
    assign aux_rdata = s_rdata;               // read data is shared by all masters

    intv_sram #(.RD_CYC(3), .WR_CYC(3)) sram (
        .clk(clk), .reset(reset),
        .req(s_req), .we(s_we), .addr(s_addr), .wdata(s_wdata), .be(s_be),
        .rdy(s_rdy), .ack(s_ack), .rdata(s_rdata),
        .sram_a(sram_a), .sram_dq_out(sram_dq_out), .sram_dq_oe(sram_dq_oe),
        .sram_dq_in(sram_dq_in), .sram_oe_n(sram_oe_n), .sram_we_n(sram_we_n),
        .sram_ub_n(sram_ub_n), .sram_lb_n(sram_lb_n)
    );

endmodule

`default_nettype wire
