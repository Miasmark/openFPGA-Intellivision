// Intellivision core: the loader (DESIGN.md 3 module 12, 5; build steps 2
// and 8; tools/mapper/README.md "The loader's CRC and length";
// docs/CARTFORMATS.md).
//
// Bytes come from agg23's data_loader on clk_sys, one strobe per byte (at
// least 4 clk_sys apart), with the bridge address; bits 27:24 name the data
// slot (core_top.v):
//
//   0 cartridge   raw .bin / .int: SRAM words 0 .. 64K-1 at file offsets
//                 (big-endian 16-bit words, byte 2n the high byte of word
//                 n); Intellicart .rom (bytes 0-2 $A8, n, ~n with n > 0,
//                 the test MAME makes, slot.cpp:450): from byte 3 on,
//                 intv_romparse, its segment words at their Intellicart
//                 addresses in plane 1. The CRC32 of the file either way.
//   1 CFG         intv_cfgparse, three bytes behind the stream (the last
//                 ones at the finish, cut at the data table's length)
//   2 EXEC        intv_sysrom, 4,096 x 10 (big-endian words, 10 bits kept)
//   3 GROM        intv_sysrom, 2,048 x 8
//   4 ECS ROM     SRAM words ECS_BASE + n (big-endian words; step 9 maps it)
//   5 IVOICE      intv_sysrom, 2,048 x 8
//
// The bridge delivers whole 32-bit words, so a file whose length is not a
// multiple of 4 arrives with 1-3 pad bytes after its end. The loader never
// takes a length from the strobes: the cartridge's CRC is over exactly the
// file length from the data table (apf_datatable.sv, slot 0x100), the image
// is words = ceil(length / 2), and an odd last byte is the high byte of the
// last word with the low byte 0. The CRC register is kept after each of the
// last four bytes (crc_at[offset & 3]); the file's CRC is crc_at[(length -
// 1) & 3]. The .rom parser sees the pad bytes too: the finish decides with
// the length (romparse's tab_end, cmp_end, err_off).
//
// The finish runs when the length arrives (len_valid rises) after a
// cartridge stream that has not been finished yet (pending: set by power-on
// reset and by the cartridge's byte 0 and the CFG's byte 0, cleared when
// the finish ends). The host clears "all complete" on any data slot
// request and sends it again afterwards; a read alone must not rerun the
// finish while the machine runs.
//   1. check: a cartridge streamed, in order, the strobes cover exactly the
//      length plus 0-3 pad bytes, a raw image at most 64K words, a .rom at
//      most 1 MiB; else no cartridge (layout 0) and err says why. err[4]:
//      the data table's length and the host's 0x0082 size disagree.
//   2. the CFG's last bytes and its end; the CFG's length: the data table's
//      (slot 0x101), or the bytes that came if the table has none
//   3. CRC table (cart_crc.hex, 256 x 64): binary search, 8 probes, as
//      step 2 (raw and BIN + CFG; a .rom is not looked up)
//   4. the format's verdict: a .rom's errors, the CFG's, or the source of
//      the map: the CFG's ranges (if it has any), the .rom's tables, the
//      layout (cart_layouts.hex; layout 1 cut at the image length)
//   5. the cart RAM area cleared (RAM_CELLS at RAM_BASE); for a .rom, every
//      256-word block of plane 1 no segment wrote cleared too
//   6. the map table: 4,096 entries into intv_cart (docs/CARTFORMATS.md 4),
//      from the layout, the CFG's ranges (word exact: a block one range
//      covers whole points into the file; a block with parts of ranges or
//      gaps is assembled into a pool block; RAM blocks get the cart RAM
//      area) or the .rom's tables (W blocks get the cart RAM area, copied
//      from plane 1, so that the save state holds them)
//   7. assembly: pool blocks filled with $FFFF, then every range's words
//      copied in (a later line wins); RAM blocks with data copied
//   8. results into intv_cart; ready. A refused image maps nothing
//      (layout 0, the table all zero), err[5] and fmt_err say why.
//
// Load-time only: what a save state needs is held and saved by intv_cart.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_loader #(
    parameter              CRC_HEX    = "core/tables/cart_crc.hex",
    parameter              LAYOUT_HEX = "core/tables/cart_layouts.hex",
    parameter logic [16:0] ECS_BASE   = 17'h10000,
    parameter logic [16:0] RAM_BASE   = 17'h18000,
    parameter int          RAM_CELLS  = 16384,
    parameter logic [16:0] POOL_BASE  = 17'h1E000
) (
    input  wire logic        clk,
    input  wire logic        reset,           // power-on only

    // bytes from data_loader
    input  wire logic        ld_wr,
    input  wire logic [27:0] ld_addr,
    input  wire logic [7:0]  ld_data,

    // the cartridge's and the CFG's lengths from the data table (clk_sys, held)
    input  wire logic        len_valid,
    input  wire logic [31:0] cart_len,
    input  wire logic [1:0]  len_chk,         // apf_datatable, held with cart_len
    input  wire logic [31:0] cfg_len,
    input  wire logic        cfg_inlist,      // the table has the CFG slot

    // SRAM master
    output logic             m_req,
    output logic             m_we,
    output logic [16:0]      m_addr,
    output logic [15:0]      m_wdata,
    output logic [1:0]       m_be,
    input  wire logic        m_ack,
    input  wire logic [15:0] m_rdata,

    // system ROM writes (intv_sysrom)
    output logic             rom_we,
    output logic [1:0]       rom_wsel,
    output logic [11:0]      rom_waddr,
    output logic [9:0]       rom_wdata,

    // results (intv_cart)
    output logic             tab_we,
    output logic [11:0]      tab_idx,
    output logic [21:0]      tab_d,
    output logic             res_we,
    output logic [31:0]      res_crc,
    output logic [16:0]      res_words,
    output logic [7:0]       res_layout,
    output logic [7:0]       res_flags,
    output logic             res_hit,
    output logic [31:0]      res_cfg_crc,
    output logic [1:0]       res_fmt,
    output logic             res_noss,
    output logic [15:0]      res_paged,
    output logic [16:0]      res_limit,

    output logic             busy,            // owns the SRAM
    output logic             ready,           // cartridge mapped (or refused: err)
    output logic [5:0]       err,             // [0] no cartridge or length mismatch,
                                              // [1] bytes out of order, [2] too long,
                                              // [3] SRAM write overrun, [4] table
                                              // length != 0x0082 size, [5] format
                                              // refused (fmt_err)
    output logic [7:0]       fmt_err,         // docs/CARTFORMATS.md 6
    output logic [1:0]       len_st,          // len_chk of the last finish
    output logic [11:0]      slot_st          // per slot: 0 empty, 1 wrong, 2 ok
);

    localparam logic [7:0] FLAG_ECS = 8'h01, FLAG_VOICE = 8'h02, FLAG_RAM = 8'h04, FLAG_PAGED = 8'h08,
                           FLAG_JLP = 8'h10, FLAG_ECS_OFF = 8'h20, FLAG_EST = 8'h40,
                           FLAG_ECS_RISK = 8'h80;
    localparam logic [7:0] E_CFG_SHORT = 8'h16, E_RAM_FULL = 8'h18, E_POOL_FULL = 8'h19,
                           E_ROM_SHORT = 8'h22, E_ROM_LTO = 8'h24, E_ROM_BIG = 8'h25;
    localparam logic [1:0] FMT_NONE = 2'd0, FMT_RAW = 2'd1, FMT_CFG = 2'd2, FMT_ROM = 2'd3;
    localparam logic [1:0] A_RAM = 2'd0, A_POOL = 2'd1, A_ROM = 2'd2;

    // ------------------------------------------------------------ tables
    logic [63:0] crc_rom [256];
    logic [15:0] lay_rom [1024];
    initial begin
        $readmemh(CRC_HEX, crc_rom);
        $readmemh(LAYOUT_HEX, lay_rom);
    end
    logic [7:0]  crc_ra;
    logic [9:0]  lay_ra;
    logic [63:0] crc_q;
    logic [15:0] lay_q;
    always_ff @(posedge clk) begin
        crc_q <= crc_rom[crc_ra];
        lay_q <= lay_rom[lay_ra];
    end

    // -------------------------------------------------------- CRC32 byte
    function automatic logic [31:0] crc_byte(input logic [31:0] c, input logic [7:0] d);
        logic [31:0] r;
        r = c ^ {24'd0, d};
        for (int i = 0; i < 8; i++)
            r = r[0] ? (r >> 1) ^ 32'hEDB88320 : r >> 1;
        return r;
    endfunction

    // ---------------------------------------------- SRAM write queue (4)
    logic [34:0] wq [4];                       // {be, addr, data}
    logic [1:0]  wq_rd = 2'd0, wq_wr = 2'd0;
    logic [2:0]  wq_n = 3'd0;
    logic        push;
    logic [34:0] push_d;
    wire  logic  wq_full = wq_n == 3'd4;
    // a load-time read (assembly copies): only with the queue empty
    logic        rd_req = 1'b0;
    logic [16:0] rd_addr = 17'd0;
    assign m_req = rd_req || wq_n != 3'd0;
    assign m_we  = !rd_req;
    assign {m_be, m_addr, m_wdata} = rd_req ? {2'b11, rd_addr, 16'd0} : wq[wq_rd];
    wire  logic  q_ack = m_ack && !rd_req;

    // ------------------------------------------------------------ stream
    wire logic [3:0]  slot = ld_addr[27:24];
    wire logic [23:0] off  = ld_addr[23:0];
    logic [7:0]  hb = 8'd0;                    // high byte of the word being built
    logic [7:0]  b1 = 8'd0, b0 = 8'd0;         // the cartridge's bytes 0 and 1
    logic [31:0] crc = 32'hFFFFFFFF;
    logic [31:0] crc_at [4];
    logic [24:0] cnt [6];                      // per slot: last offset + 1
    logic        started = 1'b0, seq_err = 1'b0, big = 1'b0, ovr = 1'b0;
    logic        rom_mode = 1'b0;              // byte 2 said .rom
    logic        pending = 1'b1;               // a stream not finished yet
    wire logic [31:0] crc_in  = off == 24'd0 ? 32'hFFFFFFFF : crc;
    wire logic [31:0] crc_nxt = crc_byte(crc_in, ld_data);
    wire logic        cart_b  = ld_wr && slot == 4'd0;
    wire logic        rom_det = cart_b && off == 24'd2 && b0 == 8'hA8 && b1 != 8'd0 && b1 == ~ld_data;

    // .rom parser
    logic        rp_wv;
    logic [15:0] rp_wa, rp_wd;
    logic [5:0]  rp_tra = 6'd0;
    logic [7:0]  rp_tq, rp_err;
    logic [24:0] rp_err_off, rp_tab_end, rp_cmp_end;
    logic        rp_tab_done, rp_cmp_ok;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [39:0] rp_cmp;                       // compat tag bytes 0-4 (bytes 0 and 3 used)
    /* verilator lint_on UNUSEDSIGNAL */
    intv_romparse romparse (
        .clk(clk), .start(rom_det), .nseg(b1),
        .in_v(cart_b && rom_mode && off >= 24'd3), .in_off(off), .in_c(ld_data),
        .w_v(rp_wv), .w_a(rp_wa), .w_d(rp_wd),
        .t_ra(rp_tra), .t_q(rp_tq),
        .err(rp_err), .err_off(rp_err_off), .tab_done(rp_tab_done), .tab_end(rp_tab_end),
        .cmp_ok(rp_cmp_ok), .cmp_end(rp_cmp_end), .cmp_body(rp_cmp)
    );

    // the .rom's covered 256-word blocks (swept back to 0 at every finish)
    logic        cov [256];
    logic [7:0]  cov_a;
    logic        cov_we, cov_wd, cov_q;
    initial for (int i = 0; i < 256; i++) cov[i] = 1'b0;
    always_ff @(posedge clk) begin
        if (cov_we) cov[cov_a] <= cov_wd;
        cov_q <= cov[cov_a];
    end

    // CFG: three bytes behind, its CRC32 over what the parser takes
    logic [23:0] lag = 24'd0;                  // bytes off-3 .. off-1, oldest in [23:16]
    logic        cp_in_v, cp_end;
    logic [7:0]  cp_in_c;
    logic        cfg_clr;
    logic [31:0] cfg_crc = 32'hFFFFFFFF;
    logic        cp_we;
    logic [4:0]  cp_idx;
    logic [58:0] cp_d;
    logic [5:0]  nrng;
    logic [7:0]  cp_err;
    logic        cp_ecs, cp_ecs_off, cp_voice, cp_jlp;
    intv_cfgparse cfgparse (
        .clk(clk), .clr(cfg_clr), .in_v(cp_in_v), .in_c(cp_in_c), .in_end(cp_end),
        .rng_we(cp_we), .rng_idx(cp_idx), .rng_d(cp_d), .nrng(nrng), .err(cp_err),
        .f_ecs(cp_ecs), .f_ecs_off(cp_ecs_off), .f_voice(cp_voice), .f_jlp(cp_jlp)
    );
    logic [58:0] rng [32];
    logic [4:0]  rng_ra;
    logic [58:0] rq;
    always_ff @(posedge clk) begin
        if (cp_we) rng[cp_idx] <= cp_d;
        rq <= rng[rng_ra];
    end

    // assembly list: {kind, entry index, base}
    logic [30:0] asml [128];
    logic [6:0]  asm_wa, asm_ra;
    logic        asm_we;
    logic [30:0] asm_wd, asm_q;
    always_ff @(posedge clk) begin
        if (asm_we) asml[asm_wa] <= asm_wd;
        asm_q <= asml[asm_ra];
    end

    // ------------------------------------------------------------ finish
    typedef enum logic [5:0] {
        F_IDLE, F_CHECK, F_FIX, F_CF0, F_CF1, F_CF2, F_CFE, F_CFW, F_LK, F_LK_W, F_LK_C,
        F_LK_FW, F_LK_F, F_SRC, F_CLR, F_COV, F_COV_W, F_COV_D, F_COV_Z, F_COV_N, F_BUILD,
        F_RAW_W, F_RAW_C, F_C_RD, F_C_EV, F_C_DEC, F_R_A, F_R_AW, F_R_F, F_R_FW, F_R_C,
        F_ZERO, F_ASM, F_ASM_W, F_ASM_D, F_FILL, F_SCAN, F_SCAN_EV, F_CP_RQ, F_CP_RD,
        F_CP_WR, F_CP_NX, F_DRAIN, F_RES
    } fstate_t;
    fstate_t     st = F_IDLE;
    logic        len_d = 1'b0;
    logic [31:0] len = 32'd0, clen = 32'd0;
    logic        cinl = 1'b0;
    logic [16:0] words = 17'd0;
    logic [31:0] crc_fin = 32'd0;
    logic [8:0]  lo = 9'd0, hi = 9'd0;
    logic [7:0]  lid = 8'd0, tflg = 8'd0;
    logic        hitf = 1'b0, cfg_on = 1'b0, refused = 1'b0;
    logic [1:0]  fmt = FMT_NONE;
    logic [1:0]  src = 2'd0;                   // map source: 0 refused, 1 raw, 2 CFG, 3 .rom
    logic [14:0] clr = 15'd0;
    logic [12:0] idx = 13'd0;                  // [12]: done
    logic [7:0]  conf = 8'd0;
    logic [15:0] paged = 16'd0;
    logic        noss = 1'b0, anyw = 1'b0;
    logic [6:0]  ram_next = 7'd0, nasm = 7'd0, ai = 7'd0;
    logic [5:0]  pool_next = 6'd0;
    logic [5:0]  ri = 6'd0;                    // range index
    logic [8:0]  wcnt = 9'd0;                  // words of a fill or copy
    logic [7:0]  blk = 8'd0;
    // the entry being built
    logic        e_r = 1'b0, e_w = 1'b0, e_n = 1'b0, e_b = 1'b0, ffull = 1'b0;
    logic [1:0]  e_cnt = 2'd0;
    logic [16:0] fbase = 17'd0;
    logic [7:0]  acc = 8'd0;
    // the assembly item / copy run
    logic [1:0]  a_kind = 2'd0;
    logic [11:0] a_idx = 12'd0;
    logic [16:0] a_base = 17'd0;
    logic [15:0] c_a = 16'd0, c_hi = 16'd0, c_lo = 16'd0;
    logic [16:0] c_src = 17'd0;
    logic [15:0] rd_q = 16'd0;

    wire  logic [8:0]  mid   = 9'((10'(lo) + 10'(hi)) >> 1);
    wire  logic [5:0]  units = 6'((18'(words) + 18'd2047) >> 11);
    wire  logic [16:0] size256 = (words + 17'd255) >> 8;
    wire  logic [3:0]  r = idx[11:8], y = idx[7:4], b = idx[3:0];
    wire  logic [15:0] b0w = {r, b, 8'h00}, b1w = {r, b, 8'hFF};

    assign crc_ra = mid[7:0];
    assign lay_ra = {lid[4:0], r, b[3]};
    assign rng_ra = ri[4:0];

    // the range rq against the block being built (or assembled: a_idx)
    wire  logic [3:0]  ar = a_idx[11:8], ay = a_idx[7:4], ab = a_idx[3:0];
    wire  logic [3:0]  ey = st == F_SCAN_EV ? ay : y;
    wire  logic [15:0] eb0 = st == F_SCAN_EV ? {ar, ab, 8'h00} : b0w;
    wire  logic [15:0] eb1 = st == F_SCAN_EV ? {ar, ab, 8'hFF} : b1w;
    wire  logic [2:0]  q_kind = rq[58:56];
    wire  logic [15:0] q_lo = rq[47:32], q_hi = rq[31:16], q_src = rq[15:0];
    wire  logic        q_ov   = q_lo <= eb1 && q_hi >= eb0;
    wire  logic        q_full = q_lo <= eb0 && q_hi >= eb1;
    wire  logic        q_data = (q_kind == 3'd1 && rq[54:51] == ey) || (q_kind == 3'd2 && ey == 4'd0);

    // the raw layout's entry for (r, y, b)
    logic [21:0] raw_e;
    always_comb begin
        logic [9:0] unit;
        logic [10:0] cmask;
        raw_e = 22'd0;
        unit  = 10'(lay_q[8:0]) + (lay_q[13] ? {5'd0, y, 1'b0} : 10'd0);
        cmask = 11'h7FF >> lay_q[8:6];
        if (lay_q[15:14] == 2'd1 && !(lid == 8'd1 && {1'b0, lay_q[8:0]} >= {4'd0, units})) begin
            if (lay_q[13] ? y <= lay_q[12:9] : y == 4'd0)
                raw_e = {5'b11000, 17'({unit, b[2:0], 8'h00})};
        end else if (lay_q[15:14] >= 2'd2 && y == 4'd0)
            raw_e = {3'b111, lay_q[15:14] == 2'd3, 1'b0,
                     RAM_BASE + {lay_q[5:0], 11'd0} + {6'd0, {b[2:0], 8'h00} & cmask}};
    end

    initial begin
        for (int i = 0; i < 6; i++) cnt[i] = 25'd0;
        for (int i = 0; i < 4; i++) begin crc_at[i] = 32'd0; wq[i] = 35'd0; end
        rom_we = 1'b0; rom_wsel = 2'd0; rom_waddr = 12'd0; rom_wdata = 10'd0;
        tab_we = 1'b0; tab_idx = 12'd0; tab_d = 22'd0;
        res_we = 1'b0; res_crc = 32'd0; res_words = 17'd0; res_layout = 8'd0; res_flags = 8'd0;
        res_hit = 1'b0; res_cfg_crc = 32'd0; res_fmt = 2'd0; res_noss = 1'b0; res_paged = 16'd0;
        res_limit = 17'd0; ready = 1'b0; err = 6'd0; fmt_err = 8'd0; len_st = 2'd0;
    end

    // streamed words (cartridge, .rom segments, ECS ROM) have priority; the
    // finish pushes only when the queue has room and no streamed word does
    logic        s_push, f_push, f_want;
    logic [34:0] s_d, f_d;
    always_comb begin
        s_push = 1'b0;
        s_d = 35'd0;
        if (cart_b && off[0] && !rom_mode && off[23:1] < 23'h10000) begin
            s_push = 1'b1;
            s_d = {2'b11, off[17:1], hb, ld_data};
        end else if (rp_wv && rom_mode) begin
            s_push = 1'b1;
            s_d = {2'b11, 1'b0, rp_wa, rp_wd};
        end else if (ld_wr && off[0] && slot == 4'd4 && off < 24'd24576) begin
            s_push = 1'b1;
            s_d = {2'b11, ECS_BASE + {3'd0, off[14:1]}, hb, ld_data};
        end
        f_want = 1'b0;
        f_d = 35'd0;
        case (st)
            F_FIX: if (len[0] && {1'b0, len[31:1]} < 32'h10000 && !rom_mode) begin
                // odd length: the last word's low byte is 0, not the pad byte
                f_want = 1'b1;
                f_d = {2'b01, len[17:1], 16'h0000};
            end
            F_CLR:   begin f_want = 1'b1; f_d = {2'b11, RAM_BASE + {2'd0, clr}, 16'h0000}; end
            F_COV_Z: begin f_want = 1'b1; f_d = {2'b11, 1'b0, blk, wcnt[7:0], 16'h0000}; end
            F_FILL:  begin f_want = 1'b1; f_d = {2'b11, a_base + {9'd0, wcnt[7:0]}, 16'hFFFF}; end
            F_CP_WR: begin f_want = 1'b1; f_d = {2'b11, a_base + 17'(c_a - {ar, ab, 8'h00}), rd_q}; end
            default: ;
        endcase
        f_push = f_want && !s_push && !wq_full;
        push   = s_push || f_push;
        push_d = s_push ? s_d : f_d;
    end
    wire logic push_ok = push && !(wq_full && !q_ack);

    // the CFG's lagged bytes at the finish
    wire logic [24:0] cfg_n = cnt[1];
    // CFG flags
    wire logic [7:0]  vflags = (cp_ecs ? FLAG_ECS : 8'd0) | (cp_ecs_off ? FLAG_ECS_OFF : 8'd0) |
                               (cp_voice ? FLAG_VOICE : 8'd0) | (cp_jlp ? FLAG_JLP : 8'd0);
    // .rom compat tag flags (id_tag.txt: 00 don't care, 01 supports, 10 requires, 11 incompatible)
    wire logic        cmp_in = rp_cmp_ok && {7'd0, rp_cmp_end} <= len;
    wire logic [7:0]  rflags = !cmp_in ? 8'd0 :
                               (rp_cmp[39:38] == 2'b10 ? FLAG_ECS : 8'd0) |
                               (rp_cmp[39:38] == 2'b11 ? FLAG_ECS_OFF : 8'd0) |
                               (rp_cmp[35:34] == 2'b01 || rp_cmp[35:34] == 2'b10 ? FLAG_VOICE : 8'd0) |
                               (rp_cmp[15:14] != 2'b00 ? FLAG_JLP : 8'd0);

    always_ff @(posedge clk) begin
        rom_we  <= 1'b0;
        tab_we  <= 1'b0;
        res_we  <= 1'b0;
        cov_we  <= 1'b0;
        asm_we  <= 1'b0;
        cp_in_v <= 1'b0;
        cp_end  <= 1'b0;
        cfg_clr <= 1'b0;
        len_d   <= len_valid;

        // ---- write queue
        if (push_ok) begin
            wq[wq_wr] <= push_d;
            wq_wr <= wq_wr + 2'd1;
        end else if (s_push)
            ovr <= 1'b1;                        // a streamed word found the queue full
        if (q_ack)
            wq_rd <= wq_rd + 2'd1;
        wq_n <= wq_n + {2'd0, push_ok} - {2'd0, q_ack};

        // ---- byte stream
        if (rp_wv && rom_mode) begin
            cov_a  <= rp_wa[15:8];
            cov_wd <= 1'b1;
            cov_we <= 1'b1;
        end
        if (ld_wr) begin
            if (slot < 4'd6)
                cnt[slot[2:0]] <= {1'b0, off} + 25'd1;
            if (!off[0])
                hb <= ld_data;
            case (slot)
                4'd0: begin
                    crc <= crc_nxt;
                    crc_at[off[1:0]] <= crc_nxt;
                    if (off == 24'd0) begin
                        started  <= 1'b1;
                        pending  <= 1'b1;
                        seq_err  <= 1'b0;
                        big      <= 1'b0;
                        ovr      <= 1'b0;
                        ready    <= 1'b0;
                        rom_mode <= 1'b0;
                        b0       <= ld_data;
                    end else if ({1'b0, off} != cnt[0]) begin
                        seq_err <= 1'b1;
                    end
                    if (off == 24'd1)
                        b1 <= ld_data;
                    if (rom_det)
                        rom_mode <= 1'b1;
                    if (rom_mode ? off >= 24'h100000 : off[23:1] >= 23'h10000)
                        big <= 1'b1;
                end
                4'd1: begin
                    lag <= {lag[15:0], ld_data};
                    if (off == 24'd0) begin
                        cfg_clr <= 1'b1;
                        cfg_crc <= 32'hFFFFFFFF;
                        if (!rom_mode) pending <= 1'b1;   // a new CFG remaps a raw image
                    end else if (off >= 24'd3) begin
                        cp_in_v <= 1'b1;
                        cp_in_c <= lag[23:16];
                        cfg_crc <= crc_byte(cfg_crc, lag[23:16]);
                    end
                end
                4'd2: if (off[0] && off < 24'd8192) begin
                    rom_we <= 1'b1; rom_wsel <= 2'd0;
                    rom_waddr <= off[12:1]; rom_wdata <= {hb[1:0], ld_data};
                end
                4'd3: if (off < 24'd2048) begin
                    rom_we <= 1'b1; rom_wsel <= 2'd1;
                    rom_waddr <= {1'b0, off[10:0]}; rom_wdata <= {2'd0, ld_data};
                end
                4'd5: if (off < 24'd2048) begin
                    rom_we <= 1'b1; rom_wsel <= 2'd2;
                    rom_waddr <= {1'b0, off[10:0]}; rom_wdata <= {2'd0, ld_data};
                end
                default: ;
            endcase
        end

        // ---- finish
        case (st)
            F_IDLE: if (len_valid && !len_d && pending) begin
                len    <= cart_len;
                len_st <= len_chk;
                cinl   <= cfg_inlist;
                clen   <= cfg_inlist ? cfg_len : {7'd0, cnt[1]};
                st     <= F_CHECK;
            end
            F_CHECK: begin
                words   <= 17'((len + 32'd1) >> 1);
                crc_fin <= ~crc_at[len[1:0] - 2'd1];
                lo <= 9'd0;
                hi <= 9'd256;
                fmt_err <= 8'd0;
                noss <= 1'b0; anyw <= 1'b0; paged <= 16'd0; conf <= 8'd0; ram_next <= 7'd0; pool_next <= 6'd0;
                nasm <= 7'd0; hitf <= 1'b0; lid <= 8'd0; tflg <= 8'd0;
                cfg_on <= cnt[1] != 25'd0;
                if (!started || len == 32'd0 || {7'd0, cnt[0]} < len || {7'd0, cnt[0]} - len > 32'd3
                    || seq_err || big || (!rom_mode && len > 32'h20000)) begin
                    err <= {1'b0, len_st == 2'd2, ovr, big || (!rom_mode && len > 32'h20000), seq_err,
                            !started || len == 32'd0 || {7'd0, cnt[0]} < len || {7'd0, cnt[0]} - len > 32'd3};
                    words   <= 17'd0;
                    crc_fin <= 32'd0;
                    refused <= 1'b1;
                    fmt <= FMT_NONE;
                    st  <= F_CF0;
                end else begin
                    err <= {1'b0, len_st == 2'd2, 4'd0};
                    refused <= 1'b0;
                    st  <= F_FIX;
                end
            end
            F_FIX: if (!len[0] || {1'b0, len[31:1]} >= 32'h10000 || rom_mode || f_push)
                st <= F_CF0;
            // the CFG's last (up to three) bytes, cut at its length, then its end
            F_CF0, F_CF1, F_CF2: begin
                if (cfg_n != 25'd0) begin
                    logic [24:0] o;
                    o = st == F_CF0 ? cfg_n - 25'd3 : st == F_CF1 ? cfg_n - 25'd2 : cfg_n - 25'd1;
                    if (!o[24] && {7'd0, o} < clen && {7'd0, o} < {7'd0, cfg_n}) begin
                        cp_in_v <= 1'b1;
                        cp_in_c <= st == F_CF0 ? lag[23:16] : st == F_CF1 ? lag[15:8] : lag[7:0];
                        cfg_crc <= crc_byte(cfg_crc, st == F_CF0 ? lag[23:16] : st == F_CF1 ? lag[15:8] : lag[7:0]);
                    end
                end
                st <= st == F_CF0 ? F_CF1 : st == F_CF1 ? F_CF2 : F_CFE;
            end
            F_CFE: begin
                if (cfg_n != 25'd0) cp_end <= 1'b1;
                st <= F_CFW;
            end
            F_CFW: st <= refused ? F_SRC : rom_mode ? F_SRC : F_LK;
            // binary search for the first entry whose CRC >= crc_fin
            F_LK: if (lo < hi)        st <= F_LK_W;
                  else if (lo[8])     st <= F_LK_F;
                  else                st <= F_LK_FW;
            F_LK_W: st <= F_LK_C;
            F_LK_C: begin
                if (crc_q[63:32] < crc_fin) lo <= mid + 9'd1;
                else                        hi <= mid;
                st <= F_LK;
            end
            F_LK_FW: st <= F_LK_F;
            F_LK_F: begin
                if (!lo[8] && crc_q[63:32] == crc_fin && crc_q[31:24] != 8'd0
                    && (crc_q[15:0] == 16'd0 || {1'b0, crc_q[15:0]} == size256)) begin
                    lid  <= crc_q[31:24];
                    tflg <= crc_q[23:16];
                    hitf <= 1'b1;
                end else begin
                    lid  <= 8'd1;
                    tflg <= FLAG_EST;
                    hitf <= 1'b0;
                end
                st <= F_SRC;
            end
            // the format's verdict and the map's source
            F_SRC: begin
                src <= 2'd0;
                if (refused) begin
                    src <= 2'd0;
                end else if (rom_mode) begin
                    fmt <= FMT_ROM;
                    lid <= 8'hFF;
                    if (len > 32'h100000)
                        fmt_err <= E_ROM_BIG;
                    else if (rp_err != 8'd0 && {7'd0, rp_err_off} < len)
                        fmt_err <= rp_err;
                    else if (!rp_tab_done || {7'd0, rp_tab_end} > len)
                        fmt_err <= E_ROM_SHORT;
                    else if (cmp_in && rp_cmp[13])
                        fmt_err <= E_ROM_LTO;
                    else
                        src <= 2'd3;
                end else if (cfg_on && cinl && ({7'd0, cnt[1]} < clen || {7'd0, cnt[1]} - clen > 32'd3)) begin
                    fmt_err <= E_CFG_SHORT;
                end else if (cfg_on && cp_err != 8'd0) begin
                    fmt_err <= cp_err;
                end else begin
                    fmt <= cfg_on ? FMT_CFG : FMT_RAW;
                    if (cfg_on && nrng != 6'd0) begin
                        src <= 2'd2;
                        lid <= 8'hFE;
                    end else
                        src <= 2'd1;
                end
                clr <= 15'd0;
                st  <= F_CLR;
            end
            F_CLR: if (f_push) begin
                if ({17'd0, clr} == RAM_CELLS - 1) begin
                    blk <= 8'd0;
                    st  <= F_COV;
                end
                clr <= clr + 15'd1;
            end
            // plane 1's blocks no .rom segment wrote: cleared (a .rom only);
            // every covered bit back to 0
            F_COV:   begin cov_a <= blk; st <= F_COV_W; end
            F_COV_W: st <= F_COV_D;
            F_COV_D: begin
                wcnt <= 9'd0;
                st <= (src == 2'd3 && !cov_q) ? F_COV_Z : F_COV_N;
            end
            F_COV_Z: if (f_push) begin
                wcnt <= wcnt + 9'd1;
                if (wcnt == 9'd255) st <= F_COV_N;
            end
            F_COV_N: begin
                cov_a <= blk; cov_wd <= 1'b0; cov_we <= 1'b1;
                blk <= blk + 8'd1;
                if (blk == 8'hFF) begin
                    idx <= 13'd0;
                    st  <= F_BUILD;
                end else
                    st <= F_COV;
            end
            // ---- the map table
            F_BUILD: begin
                if (idx[12]) begin
                    ai <= 7'd0;
                    st <= F_ASM;
                end else case (src)
                    2'd0: st <= F_ZERO;
                    2'd1: st <= F_RAW_W;              // lay_ra is {lid, r, b[3]}
                    2'd2: begin
                        e_r <= 1'b0; e_w <= 1'b0; e_n <= 1'b0; e_b <= 1'b0; e_cnt <= 2'd0;
                        ffull <= 1'b0; fbase <= 17'd0; ri <= 6'd0;
                        st <= F_C_RD;
                    end
                    default: begin
                        if (y != 4'd0) begin
                            tab_we <= 1'b1; tab_idx <= idx[11:0]; tab_d <= 22'd0;
                            idx <= idx + 13'd1;
                        end else begin
                            rp_tra <= {2'd0, r};
                            st <= F_R_A;
                        end
                    end
                endcase
            end
            F_ZERO: begin
                tab_we <= 1'b1; tab_idx <= idx[11:0]; tab_d <= 22'd0;
                idx <= idx + 13'd1;
                st <= F_BUILD;
            end
            F_RAW_W: st <= F_RAW_C;
            F_RAW_C: begin
                tab_we <= 1'b1; tab_idx <= idx[11:0]; tab_d <= raw_e;
                if (lay_q[15:14] == 2'd1 && lay_q[13] && !(lid == 8'd1 && {1'b0, lay_q[8:0]} >= {4'd0, units}))
                    paged[r] <= 1'b1;
                if (y == 4'd0 && raw_e[20:19] != 2'd0) begin
                    if (r == 4'd7 || (r == 4'd4 && !b[3])) conf <= conf | FLAG_ECS_OFF;
                    if (r == 4'd2 || r == 4'd14)          conf <= conf | FLAG_ECS_RISK;
                end
                idx <= idx + 13'd1;
                st <= F_BUILD;
            end
            // CFG: every range against the block (two clocks a range)
            F_C_RD: begin
                if (ri == nrng) st <= F_C_DEC;
                else st <= F_C_EV;
            end
            F_C_EV: begin
                if (q_ov && q_data) begin
                    if (q_kind == 3'd1) e_r <= 1'b1;
                    if (e_cnt == 2'd0) begin
                        fbase <= 17'(q_src) + 17'(b0w) - 17'(q_lo);
                        ffull <= q_full;
                    end
                    if (e_cnt != 2'd2) e_cnt <= e_cnt + 2'd1;
                    if (q_kind == 3'd1 && rq[55]) paged[r] <= 1'b1;
                end
                if (q_ov && q_kind == 3'd3 && y == 4'd0) begin
                    if (rq[48]) e_r <= 1'b1;
                    if (rq[49]) e_w <= 1'b1;
                    if (rq[50]) e_n <= 1'b1;
                end
                if (q_ov && q_kind == 3'd4 && y == 4'd0) begin
                    e_b <= 1'b1;
                    e_r <= 1'b1;
                end
                ri <= ri + 6'd1;
                st <= F_C_RD;
            end
            F_C_DEC: begin
                logic s;
                logic [16:0] base;
                s = 1'b0;
                base = 17'd0;
                if (e_w && !e_b) begin
                    s = 1'b1;
                    base = RAM_BASE + {3'd0, ram_next[5:0], 8'd0};
                end else if (e_cnt == 2'd1 && ffull) begin
                    s = 1'b1;
                    base = fbase;
                end else if (e_cnt != 2'd0) begin
                    s = 1'b1;
                    base = POOL_BASE + {4'd0, pool_next[4:0], 8'd0};
                end
                if (e_w && !e_b && ram_next == 7'd64)
                    fmt_err <= E_RAM_FULL;
                else if (!(e_w && !e_b) && !(e_cnt == 2'd1 && ffull) && e_cnt != 2'd0 && pool_next == 6'd32)
                    fmt_err <= E_POOL_FULL;
                if ((e_w && !e_b && ram_next == 7'd64) ||
                    (!(e_w && !e_b) && !(e_cnt == 2'd1 && ffull) && e_cnt != 2'd0 && pool_next == 6'd32)) begin
                    src <= 2'd0;                    // refused: the table all zero
                    idx <= 13'd0;
                    nasm <= 7'd0;
                    st  <= F_BUILD;
                end else begin
                    if (e_w && !e_b) begin
                        ram_next <= ram_next + 7'd1;
                        if (e_cnt != 2'd0) begin
                            asm_we <= 1'b1; asm_wa <= nasm; asm_wd <= {A_RAM, idx[11:0], base};
                            nasm <= nasm + 7'd1;
                        end
                    end else if (!(e_cnt == 2'd1 && ffull) && e_cnt != 2'd0) begin
                        pool_next <= pool_next + 6'd1;
                        asm_we <= 1'b1; asm_wa <= nasm; asm_wd <= {A_POOL, idx[11:0], base};
                        nasm <= nasm + 7'd1;
                    end
                    if (e_w && e_b) noss <= 1'b1;
                    if (e_w) anyw <= 1'b1;
                    tab_we  <= 1'b1;
                    tab_idx <= idx[11:0];
                    tab_d   <= {s, (e_b || s) && e_r, e_w, e_n, e_b, base};
                    if (y == 4'd0 && (((e_b || s) && e_r) || e_w || e_b)) begin
                        if (r == 4'd7 || (r == 4'd4 && !b[3])) conf <= conf | FLAG_ECS_OFF;
                        if (r == 4'd2 || r == 4'd14)          conf <= conf | FLAG_ECS_RISK;
                    end
                    idx <= idx + 13'd1;
                    st  <= F_BUILD;
                end
            end
            // .rom: the access byte of range r, then the fine byte of its window
            F_R_A:  st <= F_R_AW;
            F_R_AW: begin acc <= rp_tq; rp_tra <= {b[3], !b[3], r}; st <= F_R_F; end
            F_R_F:  st <= F_R_FW;
            F_R_FW: st <= F_R_C;
            F_R_C: begin
                logic [3:0] nib;
                logic [16:0] base;
                nib = b[3] ? acc[7:4] : acc[3:0];
                if (!(rp_tq[6:4] <= b[2:0] && b[2:0] <= rp_tq[2:0]))
                    nib = 4'd0;
                base = {1'b0, r, b, 8'h00};
                if (nib[1] && !nib[3]) begin
                    if (ram_next != 7'd64) begin
                        base = RAM_BASE + {3'd0, ram_next[5:0], 8'd0};
                        ram_next <= ram_next + 7'd1;
                        asm_we <= 1'b1; asm_wa <= nasm; asm_wd <= {A_ROM, idx[11:0], base};
                        nasm <= nasm + 7'd1;
                    end else
                        noss <= 1'b1;
                end
                if (nib[1] && nib[3]) noss <= 1'b1;
                if (nib[1]) anyw <= 1'b1;
                tab_we  <= 1'b1;
                tab_idx <= idx[11:0];
                tab_d   <= {1'b1, nib[0], nib[1], nib[2], nib[3], base};
                if (nib[0] || nib[1] || nib[3]) begin
                    if (r == 4'd7 || (r == 4'd4 && !b[3])) conf <= conf | FLAG_ECS_OFF;
                    if (r == 4'd2 || r == 4'd14)          conf <= conf | FLAG_ECS_RISK;
                end
                idx <= idx + 13'd1;
                st  <= F_BUILD;
            end
            // ---- assembly: pool blocks filled, then the ranges' words copied;
            // .rom RAM blocks copied from plane 1
            F_ASM: begin
                if (ai == nasm) st <= F_DRAIN;
                else begin asm_ra <= ai; st <= F_ASM_W; end
            end
            F_ASM_W: st <= F_ASM_D;
            F_ASM_D: begin
                a_kind <= asm_q[30:29];
                a_idx  <= asm_q[28:17];
                a_base <= asm_q[16:0];
                wcnt   <= 9'd0;
                ri     <= 6'd0;
                c_lo   <= {asm_q[28:25], asm_q[20:17], 8'h00};
                c_a    <= {asm_q[28:25], asm_q[20:17], 8'h00};
                c_hi   <= {asm_q[28:25], asm_q[20:17], 8'hFF};
                c_src  <= {1'b0, asm_q[28:25], asm_q[20:17], 8'h00};
                st <= asm_q[30:29] == A_POOL ? F_FILL : asm_q[30:29] == A_ROM ? F_CP_RQ : F_SCAN;
            end
            F_FILL: if (f_push) begin
                wcnt <= wcnt + 9'd1;
                if (wcnt == 9'd255) st <= F_SCAN;
            end
            F_SCAN: begin
                if (ri == nrng) begin ai <= ai + 7'd1; st <= F_ASM; end
                else st <= F_SCAN_EV;
            end
            F_SCAN_EV: begin
                if (q_ov && q_data) begin
                    c_lo  <= q_lo;
                    c_src <= {1'b0, q_src};
                    c_a   <= q_lo > eb0 ? q_lo : eb0;
                    c_hi  <= q_hi < eb1 ? q_hi : eb1;
                    st <= F_CP_RQ;
                end else begin
                    ri <= ri + 6'd1;
                    st <= F_SCAN;
                end
            end
            F_CP_RQ: begin
                logic [16:0] sa;
                sa = c_src + {1'b0, c_a - c_lo};
                if (sa >= words && a_kind != A_ROM)
                    st <= F_CP_NX;                      // past the image: the fill stays
                else if (wq_n == 3'd0 && !push) begin
                    rd_req  <= 1'b1;
                    rd_addr <= sa;
                    st <= F_CP_RD;
                end
            end
            F_CP_RD: if (m_ack) begin
                rd_req <= 1'b0;
                rd_q   <= m_rdata;
                st <= F_CP_WR;
            end
            F_CP_WR: if (f_push) st <= F_CP_NX;
            F_CP_NX: begin
                if (c_a == c_hi) begin
                    if (a_kind == A_ROM) begin ai <= ai + 7'd1; st <= F_ASM; end
                    else begin ri <= ri + 6'd1; st <= F_SCAN; end
                end else begin
                    c_a <= c_a + 16'd1;
                    st <= F_CP_RQ;
                end
            end
            F_DRAIN: if (wq_n == 3'd0 && !push) st <= F_RES;
            F_RES: begin
                logic [7:0] f;
                f = 8'd0;
                case (src)
                    2'd1: f = ((lid == 8'd1 && (tflg & FLAG_ECS) == 8'd0) ? tflg | conf : tflg)
                              | (cfg_on ? vflags : 8'd0);
                    2'd2: begin
                        f = vflags | (hitf ? tflg & (FLAG_ECS | FLAG_VOICE) : 8'd0)
                            | (anyw ? FLAG_RAM : 8'd0) | (paged != 16'd0 ? FLAG_PAGED : 8'd0);
                        if ((f & FLAG_ECS) == 8'd0) f = f | conf;
                    end
                    2'd3: begin
                        f = rflags | (anyw ? FLAG_RAM : 8'd0);
                        if ((f & FLAG_ECS) == 8'd0) f = f | conf;
                    end
                    default: f = 8'd0;
                endcase
                res_we      <= 1'b1;
                res_crc     <= crc_fin;
                res_words   <= words;
                res_layout  <= src == 2'd0 ? 8'd0 : lid;
                res_flags   <= f;
                res_hit     <= (src == 2'd1 || src == 2'd2) && hitf;
                res_cfg_crc <= (src != 2'd0 && fmt == FMT_CFG) ? ~cfg_crc : 32'd0;
                res_fmt     <= src == 2'd0 ? FMT_NONE : fmt;
                res_noss    <= src != 2'd0 && noss;
                res_paged   <= src == 2'd0 ? 16'd0 : paged;
                res_limit   <= src == 2'd0 ? 17'd0 : src == 2'd3 ? 17'h10000 : words;
                if (fmt_err != 8'd0) err[5] <= 1'b1;
                if (ovr) err[3] <= 1'b1;
                ready   <= 1'b1;
                pending <= 1'b0;
                st <= F_IDLE;
            end
            default: st <= F_IDLE;
        endcase

        if (reset) begin
            st <= F_IDLE;
            started <= 1'b0;
            pending <= 1'b1;
            ready <= 1'b0;
            err <= 6'd0;
            rd_req <= 1'b0;
            wq_rd <= 2'd0; wq_wr <= 2'd0; wq_n <= 3'd0;
        end
    end

    assign busy = st != F_IDLE || wq_n != 3'd0;

    // slot status for the test pattern: the system ROMs by size (the owner's
    // files, DESIGN.md 5.6), the cartridge by the loader's verdict: wrong
    // for err[3:0] (not mapped, or an SRAM overrun) and err[5] (a format
    // refused); err[4] alone (the load went on with the table's length)
    // leaves it ok, the cartridge's second card shows the length check. The
    // CFG slot: ok when it streamed (its verdict is in err[5] / fmt_err).
    localparam logic [24:0] SIZE [6] = '{25'd0, 25'd0, 25'd8192, 25'd2048, 25'd24576, 25'd2048};
    always_comb begin
        for (int i = 0; i < 6; i++) begin
            if (cnt[i] == 25'd0)
                slot_st[2*i +: 2] = 2'd0;
            else if (i == 0)
                slot_st[1:0] = (ready && (err[3:0] != 4'd0 || err[5])) ? 2'd1 : 2'd2;
            else if (SIZE[i] == 25'd0 || cnt[i] == SIZE[i])
                slot_st[2*i +: 2] = 2'd2;
            else
                slot_st[2*i +: 2] = 2'd1;
        end
    end

endmodule

`default_nettype wire
