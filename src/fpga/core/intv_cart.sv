// Intellivision core: the cartridge side of the CPU bus (DESIGN.md 3
// module 11, 5; build steps 2 and 8; docs/CARTFORMATS.md 4).
//
// Every cartridge access goes through a map table that the loader
// (intv_loader.sv) builds from the image's format (CRC-table layout, BIN +
// CFG, Intellicart .rom): 4,096 entries in block RAM, one per 256-word
// block of each of the 16 pages of each 4K range:
//
//   index  {r = addr[15:12], y, b = addr[11:8]}, y = sel[r] if range r is
//          paged (ECS-style pages, intv_pagesel), else 0
//   entry  [37:30] first, [29:22] last word of the block that answers (the
//          trim: a BIN + CFG's ranges declare only those words; every other
//          format the whole block, $00-$FF). A word outside it is not
//          answered and not written. Through a bank window, the trim of the
//          storage block's entry counts.
//          [21] S  the block has storage
//          [20] R  reads answered        [19] W  writes stored
//          [18] N  narrow: 8-bit cells (reads give the upper byte 0, a write
//                  keeps the low byte; MAME rom.h:52-53, jzIntv's N)
//          [17] B  Intellicart bank window: the access goes to Intellicart
//                  address ia = ((addr & $7FF) + (bank << 8)) & $FFFF,
//                  bank = the register of the 2K window (intellicart.txt),
//                  whose storage is the entry {ia[15:12], 0, ia[11:8]}'s
//          [16:0] the SRAM word of the block's first word: an access is at
//                  base + addr[7:0] (base + ia[7:0] through a bank window)
//
// A ROM-area word (SRAM below $10000) at or past `limit` (the image's
// length; $10000 for a .rom's Intellicart space) is not answered, as a read
// past an image's end was in step 2. Not answered: the bus reads $FFFF
// through its pull-ups (DESIGN 2.5).
//
// CPU writes, whatever their address: $xA5y to $xFFF selects a page
// (intv_pagesel); $0040-$005F loads Intellicart bank register addr[4:0]
// (the low byte; $0040+r for $r000-$r7FF, $0050+r for $r800-$rFFF). After
// a load each bank register points its 2K window at its own address
// ($0040+r = r << 4, $0050+r = r << 4 | 8: what jzIntv does; the
// Intellicart manual calls the start state undefined), and they keep their
// values over a machine reset (the Intellicart does not see the console's
// reset).
//
// The ECS (build step 9; intv_ecs.sv, tools/ecs.py): while it is attached
// (ecs_on) it owns $00E0-$00E3, $00F0-$00FF and $4000-$47FF, and each ROM
// range while its page latch (ecs_pg) selects it: $2000 on page 1, $7000
// on page 0, $E000 on page 1, with the ECS ROM slot loaded (ecs_rom_ok).
// There the cartridge neither answers nor stores (MAME ecs.cpp read_rome0:
// the ECS ROM or the cartridge, never both); a write still loads the page
// selects and bank registers. An ECS ROM read is answered from the SRAM at
// ECS_BASE ($2000: + $0000, $7000: + $1000, $E000: + $2000; ECS.bin as the
// loader stored it). m4 tells the ECS Auto rule (intv_media) that the image
// maps $4000-$47FF on page 0: an entry {4, 0, b < 8} with R, W or B, as
// the loader last wrote it.
//
// Bus port: a request (one clk) is answered by ack (one clk) with the data,
// hit (a read answered), the window's attributes {B, N, W, R} and the
// range's paged bit. The table is read on the request's clock (the bus's
// address is registered and stable), so an access takes 2 clk_sys more
// than step 7's (3 through a bank window) plus the SRAM's: about 8; the CPU
// bus cycle is 48 per microcycle.
//
// Save state (DESIGN.md 4.3; module id SS_ID, 16 words):
//   0      image CRC32                       \
//   1      [16] table hit, [15:8] flags,     |
//          [7:0] layout id                   | the load's results: read
//   2      [16:0] image length in words      | only (a restore leaves them:
//   3      CFG CRC32 (0: none)               | the header's CRCs say the
//   4      [18:17] format, [16] no state,    | load is the same)
//          [15:0] paged ranges               |
//   15     [16:0] limit                      /
//   5, 6   page selects, 4 bits per range (0-7, then 8-15)
//   7..14  Intellicart bank registers, four per word (word 7 + k:
//          registers 4k .. 4k+3, 4k in bits 7:0)
// The map table is not saved: the loader builds it from the same image and
// CFG, which the blob's header checks (CRC32s). Cart RAM is in the SRAM
// (the area at RAM_BASE), which ss_ctl reads and writes directly.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_cart #(
    parameter logic [7:0]  SS_ID    = 8'h0B,
    parameter logic [16:0] ECS_BASE = 17'h10000
) (
    input  wire logic        clk,
    input  wire logic        mreset,          // machine reset: page selects to pg_rst

    // load port (intv_loader)
    input  wire logic        ld_tab_we,
    input  wire logic [11:0] ld_tab_idx,
    input  wire logic [37:0] ld_tab_d,
    input  wire logic        ld_res_we,       // results; selects to 0, bank registers to their start
    input  wire logic [31:0] ld_crc,
    input  wire logic [16:0] ld_words,
    input  wire logic [7:0]  ld_layout,
    input  wire logic [7:0]  ld_flags,
    input  wire logic        ld_hit,
    input  wire logic [31:0] ld_cfg_crc,
    input  wire logic [1:0]  ld_fmt,
    input  wire logic        ld_noss,
    input  wire logic [15:0] ld_paged,
    input  wire logic [16:0] ld_limit,

    output logic [31:0]      crc,
    output logic [16:0]      words,
    output logic [7:0]       layout,
    output logic [7:0]       flags,
    output logic             hit,
    output logic [31:0]      cfg_crc,
    output logic [1:0]       fmt,
    output logic             noss,            // no save state for this image

    // page selects (for the ECS, build step 9)
    input  wire logic [63:0] pg_rst,
    output logic [63:0]      pg_sel,

    // the ECS (build step 9)
    input  wire logic        ecs_on,
    input  wire logic [11:0] ecs_pg,          // {latch $E, latch $7, latch $2}
    input  wire logic        ecs_rom_ok,
    output logic             m4,              // the image maps $4000-$47FF (page 0)

    // CPU bus port
    input  wire logic        bus_req,
    input  wire logic        bus_we,
    input  wire logic [15:0] bus_addr,
    input  wire logic [15:0] bus_wdata,
    output logic             bus_ack,
    output logic [15:0]      bus_rdata,
    output logic             bus_hit,
    output logic [3:0]       bus_attr,        // {B, N, W, R} of the window
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

    // ------------------------------------------------------------ table
    logic [37:0] tab [4096];
    logic [37:0] tab_q;
    logic [11:0] tab_ra;
    always_ff @(posedge clk) begin
        if (ld_tab_we)
            tab[ld_tab_idx] <= ld_tab_d;
        tab_q <= tab[tab_ra];
    end

    logic [15:0] paged = 16'd0;
    logic [7:0]  m4b = 8'd0;
    assign m4 = |m4b;
    logic [16:0] limit = 17'd0;
    logic [7:0]  bank [32];

    initial begin
        for (int i = 0; i < 32; i++) bank[i] = {4'(i), i[4], 3'd0};
        crc = 32'd0; words = 17'd0; layout = 8'd0; flags = 8'd0; hit = 1'b0; cfg_crc = 32'd0;
        fmt = 2'd0; noss = 1'b0;
        bus_ack = 1'b0; bus_rdata = 16'hFFFF; bus_hit = 1'b0; bus_attr = 4'd0; bus_paged = 1'b0;
        m_req = 1'b0; m_we = 1'b0; m_addr = 17'd0; m_wdata = 16'd0; m_be = 2'b11;
    end

    // -------------------------------------------------- page selects
    // A write's side effects (page select, bank register) land when its
    // access ends: the access itself is looked up with the values before it.
    wire logic ss_hit = ss_we && ss_addr[15:8] == SS_ID;
    logic      fx_we = 1'b0;
    intv_pagesel pagesel (
        .clk(clk), .rst(mreset || ld_res_we), .rst_val(ld_res_we ? 64'd0 : pg_rst),
        .we(fx_we), .addr(qa), .wdata(qwd),
        .ss_we0(ss_hit && ss_addr[7:0] == 8'd5), .ss_we1(ss_hit && ss_addr[7:0] == 8'd6),
        .ss_wdata(ss_wdata), .sel(pg_sel)
    );

    // ------------------------------------------------------- bus port
    typedef enum logic [2:0] {B_IDLE, B_T1, B_T2, B_MEM, B_DONE} bstate_t;
    bstate_t     bst = B_IDLE;
    logic [15:0] qa = 16'd0;                   // the access, held
    logic        qwe = 1'b0;
    logic [15:0] qwd = 16'd0;
    logic [21:0] qe = 22'd0;                   // the window's entry (B_T2; its trim is not used)
    logic [7:0]  qlo = 8'd0;                   // the word in the Intellicart block (B_T2)
    logic        qown = 1'b0;                  // the ECS owns the access
    logic        qrom = 1'b0;                  // ... and it is an ECS ROM read

    // the ECS's ranges for the address on the bus
    /* verilator lint_off UNUSEDSIGNAL */
    wire logic [15:0] ba = bus_addr;
    /* verilator lint_on UNUSEDSIGNAL */
    wire logic e_rom = ecs_on && ecs_rom_ok &&
                       ((ba[15:12] == 4'h2 && ecs_pg[3:0] == 4'd1) ||
                        (ba[15:12] == 4'h7 && ecs_pg[7:4] == 4'd0) ||
                        (ba[15:12] == 4'hE && ecs_pg[11:8] == 4'd1));
    wire logic e_own = e_rom || (ecs_on && (ba[15:2] == 14'h0038 || ba[15:4] == 12'h00F ||
                                            ba[15:11] == 5'b01000));

    wire logic [3:0]  r_bus = bus_addr[15:12];
    wire logic [3:0]  y_bus = paged[r_bus] ? pg_sel[4*r_bus +: 4] : 4'd0;
    wire logic [7:0]  bk    = bank[{qa[11], qa[15:12]}];
    wire logic [15:0] ia    = {5'd0, qa[10:0]} + {bk, 8'd0};

    // the access, from the window's entry w and the storage entry s
    // (s = w unless w is a bank window)
    /* verilator lint_off UNUSEDSIGNAL */
    wire logic [21:0] w_e   = bst == B_T2 ? qe : tab_q[21:0];  // its R, W, N
    /* verilator lint_on UNUSEDSIGNAL */
    wire logic [7:0]  lo8   = bst == B_T2 ? qlo : qa[7:0];
    wire logic [16:0] sa    = tab_q[16:0] + {9'd0, lo8};
    wire logic        lim   = !sa[16] && sa >= limit;
    wire logic        trim  = lo8 >= tab_q[37:30] && lo8 <= tab_q[29:22];
    wire logic        go    = tab_q[21] && !lim && trim && (qwe ? w_e[19] : w_e[20]);

    always_comb begin
        tab_ra = {r_bus, y_bus, bus_addr[11:8]};
        if (bst == B_T1)
            tab_ra = {ia[15:12], 4'd0, ia[11:8]};
    end

    always_ff @(posedge clk) begin
        bus_ack <= 1'b0;
        fx_we   <= 1'b0;
        case (bst)
            B_IDLE: if (bus_req) begin
                qa  <= bus_addr;
                qwe <= bus_we;
                qwd <= bus_wdata;
                qown <= e_own;
                qrom <= e_rom && !bus_we;
                bus_paged <= paged[r_bus];
                bst <= B_T1;
            end
            B_T1, B_T2: if (bst == B_T1 && qown) begin              // the ECS's
                bus_attr  <= {3'd0, qrom};
                bus_rdata <= 16'hFFFF;
                bus_hit   <= 1'b0;
                qe        <= 22'd0;
                m_we      <= 1'b0;
                m_be      <= 2'b11;
                m_addr    <= ECS_BASE + {3'd0, qa[15] ? 2'd2 : {1'b0, qa[14]}, qa[11:0]};
                if (qrom) begin
                    m_req <= 1'b1;
                    bst   <= B_MEM;
                end else
                    bst   <= B_DONE;
            end else begin                                      // the cartridge's
                if (bst == B_T1) begin                          // tab_q: the window's entry
                    qe  <= tab_q[21:0];
                    qlo <= ia[7:0];
                    bus_attr  <= {tab_q[17], tab_q[18], tab_q[19], tab_q[20]};
                    bus_rdata <= 16'hFFFF;
                    bus_hit   <= 1'b0;
                end
                m_we    <= qwe;
                m_be    <= 2'b11;
                m_wdata <= w_e[18] ? {8'h00, qwd[7:0]} : qwd;
                m_addr  <= sa;
                if (bst == B_T1 && tab_q[17])
                    bst <= B_T2;                                // tab_q next: the Intellicart block's
                else if (go) begin
                    m_req <= 1'b1;
                    bst   <= B_MEM;
                end else
                    bst   <= B_DONE;
            end
            B_MEM: if (m_ack) begin
                m_req <= 1'b0;
                if (!m_we) begin
                    bus_hit   <= 1'b1;
                    bus_rdata <= qe[18] ? {8'h00, m_rdata[7:0]} : m_rdata;
                end
                bus_ack <= 1'b1;
                fx_we   <= qwe;
                bst <= B_IDLE;
            end
            B_DONE: begin
                bus_ack <= 1'b1;
                fx_we   <= qwe;
                bst <= B_IDLE;
            end
            default: bst <= B_IDLE;
        endcase
        if (fx_we && qa[15:5] == 11'd2)                          // $0040-$005F
            bank[qa[4:0]] <= qwd[7:0];

        // load results, state restore (never during a bus access: the
        // machine is in reset or frozen then)
        if (ld_tab_we && ld_tab_idx[11:3] == 9'b0100_0000_0)       // {4, 0, b < 8}
            m4b[ld_tab_idx[2:0]] <= ld_tab_d[20] | ld_tab_d[19] | ld_tab_d[17];
        if (ld_res_we) begin
            crc <= ld_crc; words <= ld_words; layout <= ld_layout; flags <= ld_flags; hit <= ld_hit;
            cfg_crc <= ld_cfg_crc; fmt <= ld_fmt; noss <= ld_noss; paged <= ld_paged; limit <= ld_limit;
            for (int i = 0; i < 32; i++) bank[i] <= {4'(i), i[4], 3'd0};
        end
        if (ss_hit && ss_addr[7:0] >= 8'd7 && ss_addr[7:0] <= 8'd14)
            for (int i = 0; i < 4; i++)
                bank[{ss_addr[2:0] - 3'd7, 2'(i)}] <= ss_wdata[8*i +: 8];
    end

    // --------------------------------------------------------- state read
    logic [31:0] ss_q;
    wire  logic [2:0] ss_k = ss_addr[2:0] - 3'd7;            // bank word 0-7
    always_comb begin
        ss_q = 32'd0;
        case (ss_addr[7:0])
            8'd0:  ss_q = crc;
            8'd1:  ss_q = {15'd0, hit, flags, layout};
            8'd2:  ss_q = {15'd0, words};
            8'd3:  ss_q = cfg_crc;
            8'd4:  ss_q = {13'd0, fmt, noss, paged};
            8'd5:  ss_q = pg_sel[31:0];
            8'd6:  ss_q = pg_sel[63:32];
            8'd15: ss_q = {15'd0, limit};
            default:
                if (ss_addr[7:0] >= 8'd7 && ss_addr[7:0] <= 8'd14)
                    for (int i = 0; i < 4; i++) ss_q[8*i +: 8] = bank[{ss_k, 2'(i)}];
        endcase
    end
    assign ss_rdata = ss_addr[15:8] == SS_ID ? ss_q : 32'd0;

endmodule

`default_nettype wire
