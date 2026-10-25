// Intellivision core: the cartridge side of the CPU bus (DESIGN.md 3 module
// 11, 5.2; tools/mapper/README.md).
//
// The loader (intv_loader.sv) fills a page table of 32 entries, one per
// 2K-word page of the CPU address space, from the CRC table's layout. Every
// cartridge access goes through it to an SRAM word:
//
//   entry [15:14] kind: 0 none, 1 ROM, 2 RAM 16-bit, 3 RAM 8-bit
//         [13]    ECS-style paged 4K range: page y is at offset + 2y
//         [12:9]  number of pages - 1
//         [8:0]   ROM: image offset in 2K-word units
//                 RAM: [8:6] size code, cells = 2048 >> code (mirrored in
//                 the page); [5:0] offset in the cart RAM area, 2K cells
//
//   ROM   SRAM word = offset x 2048 + (addr & $7FF), answered only below the
//         image length (words); a paged range answers only on its pages
//   RAM   SRAM word = RAM_BASE + offset x 2048 + (addr & $7FF & (cells - 1));
//         an 8-bit cell reads with the upper byte 0 and keeps only the low
//         byte of a write (MAME rom.h:52-53)
//   none  not answered: the bus reads $FFFF through its pull-ups (DESIGN 2.5)
//
// ECS-style page select: a write of $xA5y to $xFFF selects page y of the 4K
// range $x000 (jzIntv doc/tech/ecs.html), for every range, whatever the
// cartridge has there; machine reset selects page 0 everywhere. When the
// ECS is attached, the ECS module decides who drives $2000, $7000 and $E000
// (build step 9); this module is the cartridge alone, as the Python model.
//
// Bus port: a request (one clk) is answered by ack (one clk) with the data,
// hit (answered), the page's kind and its paged bit. A cartridge access
// costs about 6 clk_sys; the CPU bus cycle is 48 per microcycle.
//
// Save state (DESIGN.md 4.3; module id SS_ID, 21 words):
//   0      image CRC32
//   1      [16] table hit, [15:8] flags, [7:0] layout id
//   2      [16:0] image length in words
//   3..18  page table: word 3 + k = {entry 2k+1, entry 2k}
//   19, 20 page selects: 4 bits per 4K range, ranges 0-7, then 8-15
// The page table and the load results do not change at run time, but they
// are saved so that a restore is a plain reset with loaded values (DESIGN
// 4.3) and needs no table lookup. Cart RAM itself is in the SRAM, which
// ss_ctl reads and writes directly while the machine is frozen (DESIGN 4.3).
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_cart #(
    parameter logic [7:0]  SS_ID    = 8'h0B,
    parameter logic [16:0] RAM_BASE = 17'h18000
) (
    input  wire logic        clk,
    input  wire logic        mreset,          // machine reset: page selects to 0

    // load port (intv_loader)
    input  wire logic        ld_pt_we,
    input  wire logic [4:0]  ld_pt_idx,
    input  wire logic [15:0] ld_pt_data,
    input  wire logic        ld_res_we,       // results; also page selects to 0
    input  wire logic [31:0] ld_crc,
    input  wire logic [16:0] ld_words,
    input  wire logic [7:0]  ld_layout,
    input  wire logic [7:0]  ld_flags,
    input  wire logic        ld_hit,

    output logic [31:0]      crc,
    output logic [16:0]      words,
    output logic [7:0]       layout,
    output logic [7:0]       flags,
    output logic             hit,

    // CPU bus port
    input  wire logic        bus_req,
    input  wire logic        bus_we,
    input  wire logic [15:0] bus_addr,
    input  wire logic [15:0] bus_wdata,
    output logic             bus_ack,
    output logic [15:0]      bus_rdata,
    output logic             bus_hit,
    output logic [1:0]       bus_kind,
    output logic             bus_paged,

    // SRAM master (intv_media's arbiter)
    output logic             m_req,
    output logic             m_we,
    output logic [16:0]      m_addr,
    output logic [15:0]      m_wdata,
    output logic [1:0]       m_be,
    input  wire logic        m_ack,
    input  wire logic [15:0] m_rdata,

    // save state
    input  wire logic [15:0] ss_addr,         // [15:8] module id, [7:0] word
    input  wire logic        ss_we,
    input  wire logic [31:0] ss_wdata,
    output logic [31:0]      ss_rdata
);

    localparam logic [1:0] K_ROM = 2'd1, K_RAM16 = 2'd2, K_RAM8 = 2'd3;

    logic [15:0] pt  [32];
    wire  logic [3:0] ss_k = 4'(ss_addr[7:0] - 8'd3);   // page-table word pair
    logic [3:0]  sel [16];

    initial begin
        for (int i = 0; i < 32; i++) pt[i] = 16'd0;
        for (int i = 0; i < 16; i++) sel[i] = 4'd0;
        crc = 32'd0; words = 17'd0; layout = 8'd0; flags = 8'd0; hit = 1'b0;
        bus_ack = 1'b0; bus_rdata = 16'hFFFF; bus_hit = 1'b0; bus_kind = 2'd0; bus_paged = 1'b0;
        m_req = 1'b0; m_we = 1'b0; m_addr = 17'd0; m_wdata = 16'd0; m_be = 2'b11;
    end

    // ------------------------------------------------------------ decode
    // Combinational from the request; registered when the request is taken.
    wire logic [15:0] e      = pt[bus_addr[15:11]];
    wire logic [1:0]  e_kind = e[15:14];
    wire logic        e_pgd  = e[13];
    wire logic [3:0]  e_npm1 = e[12:9];
    wire logic [3:0]  y      = sel[bus_addr[15:12]];
    // ROM: the image word, in 2K units plus the offset in the page
    wire logic [9:0]  r_unit = {1'b0, e[8:0]} + (e_pgd ? {5'd0, y, 1'b0} : 10'd0);
    wire logic [20:0] r_idx  = {r_unit, bus_addr[10:0]};
    wire logic        r_ok   = (!e_pgd || y <= e_npm1) && r_idx < {4'd0, words};
    // RAM: the cell, mirrored inside the page
    wire logic [10:0] c_mask = 11'h7FF >> e[8:6];
    wire logic [16:0] c_idx  = {e[5:0], bus_addr[10:0] & c_mask};
    // page select write: $xA5y to $xFFF
    wire logic        sel_wr = bus_we && bus_addr[11:0] == 12'hFFF
                            && bus_wdata[15:4] == {bus_addr[15:12], 8'hA5};

    typedef enum logic [1:0] {B_IDLE, B_MEM, B_DONE} bstate_t;
    bstate_t    bst = B_IDLE;
    logic       q_ram8 = 1'b0;

    always_ff @(posedge clk) begin
        bus_ack <= 1'b0;
        case (bst)
            B_IDLE: if (bus_req) begin
                bus_kind  <= e_kind;
                bus_paged <= e_pgd;
                bus_rdata <= 16'hFFFF;
                bus_hit   <= 1'b0;
                q_ram8    <= e_kind == K_RAM8;
                m_we      <= bus_we;
                m_be      <= 2'b11;
                m_wdata   <= e_kind == K_RAM8 ? {8'h00, bus_wdata[7:0]} : bus_wdata;
                if (sel_wr)
                    sel[bus_addr[15:12]] <= bus_wdata[3:0];
                if (e_kind == K_ROM && !bus_we && r_ok) begin
                    m_addr <= r_idx[16:0];
                    m_req  <= 1'b1;
                    bst    <= B_MEM;
                end else if (e_kind == K_RAM16 || e_kind == K_RAM8) begin
                    m_addr <= RAM_BASE + c_idx;
                    m_req  <= 1'b1;
                    bst    <= B_MEM;
                end else begin
                    bst    <= B_DONE;           // not answered (or a ROM write)
                end
            end
            B_MEM: if (m_ack) begin
                m_req <= 1'b0;
                bus_hit <= 1'b1;
                if (!m_we)
                    bus_rdata <= q_ram8 ? {8'h00, m_rdata[7:0]} : m_rdata;
                bus_ack <= 1'b1;
                bst <= B_IDLE;
            end
            B_DONE: begin
                bus_ack <= 1'b1;
                bst <= B_IDLE;
            end
            default: bst <= B_IDLE;
        endcase

        // load results, state restore and machine reset (never during a
        // bus access: the machine is in reset or frozen then)
        if (ld_pt_we)
            pt[ld_pt_idx] <= ld_pt_data;
        if (ld_res_we) begin
            crc <= ld_crc; words <= ld_words; layout <= ld_layout; flags <= ld_flags; hit <= ld_hit;
        end
        if (mreset || ld_res_we)
            for (int i = 0; i < 16; i++) sel[i] <= 4'd0;
        if (ss_we && ss_addr[15:8] == SS_ID) begin
            case (ss_addr[7:0])
                8'd0: crc <= ss_wdata;
                8'd1: {hit, flags, layout} <= ss_wdata[16:0];
                8'd2: words <= ss_wdata[16:0];
                8'd19: for (int i = 0; i < 8; i++) sel[i] <= ss_wdata[4*i +: 4];
                8'd20: for (int i = 0; i < 8; i++) sel[8 + i] <= ss_wdata[4*i +: 4];
                default:
                    if (ss_addr[7:0] >= 8'd3 && ss_addr[7:0] <= 8'd18)
                        {pt[{ss_k, 1'b1}], pt[{ss_k, 1'b0}]} <= ss_wdata;
            endcase
        end
    end

    // --------------------------------------------------------- state read
    logic [31:0] ss_q;
    always_comb begin
        ss_q = 32'd0;
        case (ss_addr[7:0])
            8'd0:  ss_q = crc;
            8'd1:  ss_q = {15'd0, hit, flags, layout};
            8'd2:  ss_q = {15'd0, words};
            8'd19: for (int i = 0; i < 8; i++) ss_q[4*i +: 4] = sel[i];
            8'd20: for (int i = 0; i < 8; i++) ss_q[4*i +: 4] = sel[8 + i];
            default:
                if (ss_addr[7:0] >= 8'd3 && ss_addr[7:0] <= 8'd18)
                    ss_q = {pt[{ss_k, 1'b1}], pt[{ss_k, 1'b0}]};
        endcase
    end
    assign ss_rdata = ss_addr[15:8] == SS_ID ? ss_q : 32'd0;

endmodule

`default_nettype wire
