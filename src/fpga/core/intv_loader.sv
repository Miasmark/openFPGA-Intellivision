// Intellivision core: the loader (DESIGN.md 3 module 12, 5.1, 5.2, 5.6;
// tools/mapper/README.md "The loader's CRC and length").
//
// Bytes come from agg23's data_loader on clk_sys, one strobe per byte, with
// the bridge address; bits 27:24 name the data slot (core_top.v):
//
//   0 cartridge   SRAM words 0 .. 64K-1 at file offsets: big-endian 16-bit
//                 words, byte 2n the high byte of word n (DESIGN 5.2); the
//                 CRC32 of the file while it streams
//   1 config      counted only (CFG parser: build step 8)
//   2 EXEC        intv_sysrom, 4,096 x 10 (big-endian words, 10 bits kept)
//   3 GROM        intv_sysrom, 2,048 x 8
//   4 ECS ROM     SRAM words ECS_BASE + n (big-endian words; step 9 maps it)
//   5 IVOICE      intv_sysrom, 2,048 x 8
//
// The bridge delivers whole 32-bit words, so a file whose length is not a
// multiple of 4 arrives with 1-3 pad bytes after its end. The loader never
// takes its length from the strobes: the CRC is over exactly the file length
// from the data table (apf_datatable.sv, slot 0x100), the image is
// words = ceil(length / 2), and an odd last byte is the high byte of the
// last word with the low byte 0. Since the length is known only after the
// bytes (the host completes the data table and sends "all complete"
// afterwards), the CRC register is kept after each of the last four bytes
// (crc_at[offset & 3]); the file's CRC is crc_at[(length - 1) & 3], and the
// pad bytes of the last bridge word are discarded with it. An odd length
// rewrites the low byte of the last word with 0 (pad bytes beyond the last
// word are never read: the cart answers only below words).
//
// When the length arrives (len_valid rises) after a cartridge stream that
// has not been finished yet (pending: set by power-on reset and by the
// cartridge's byte 0, cleared when the finish ends). The host clears "all
// complete" on any data slot request, read (0x0080) or write (0x0082), and
// sends it again afterwards; a read alone (for example of the JLP flash
// slot at step 11) must not rerun the finish while the machine runs, which
// would take the SRAM, clear the cartridge RAM and reset the page selects.
//   1. check: a cartridge streamed, in order, length 1 .. 64K words, and the
//      strobes cover exactly the length plus 0-3 pad bytes; else no
//      cartridge (layout 0: nothing answers) and err says why. err[4] says
//      that the data table's length and the host's 0x0082 size disagree
//      (apf_datatable len_chk 2; the load goes on with the table's length);
//      len_st keeps len_chk for the test pattern
//   2. CRC table (cart_crc.hex, 256 x 64, sorted end to end): binary search,
//      8 probes; a hit needs the CRC and a layout other than 0, and the size
//      field (256-word units, 0 = any) to agree, else the default map
//      (layout 1, flag ESTIMATED), as tools/intv_mapper.py Tables.model
//   3. page table: the layout's 32 entries (cart_layouts.hex) into intv_cart;
//      layout 1 is cut at the image length (ROM pages whose offset is past
//      it are empty), and then gets the ECS conflict flags of what is left
//   4. cartridge RAM area cleared to 0 (RAM_CELLS cells at RAM_BASE)
//   5. results into intv_cart; ready
//
// Load-time only: what a save state needs (the page table, layout, flags)
// is held and saved by intv_cart.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_loader #(
    parameter              CRC_HEX    = "core/tables/cart_crc.hex",
    parameter              LAYOUT_HEX = "core/tables/cart_layouts.hex",
    parameter logic [16:0] ECS_BASE   = 17'h10000,
    parameter logic [16:0] RAM_BASE   = 17'h18000,
    parameter int          RAM_CELLS  = 16384
) (
    input  wire logic        clk,
    input  wire logic        reset,           // power-on only

    // bytes from data_loader
    input  wire logic        ld_wr,
    input  wire logic [27:0] ld_addr,
    input  wire logic [7:0]  ld_data,

    // the cartridge's file length from the data table (clk_sys, held)
    input  wire logic        len_valid,
    input  wire logic [31:0] cart_len,
    input  wire logic [1:0]  len_chk,         // apf_datatable, held with cart_len

    // SRAM master (writes only)
    output logic             m_req,
    output logic [16:0]      m_addr,
    output logic [15:0]      m_wdata,
    output logic [1:0]       m_be,
    input  wire logic        m_ack,

    // system ROM writes (intv_sysrom)
    output logic             rom_we,
    output logic [1:0]       rom_wsel,
    output logic [11:0]      rom_waddr,
    output logic [9:0]       rom_wdata,

    // results (intv_cart)
    output logic             pt_we,
    output logic [4:0]       pt_idx,
    output logic [15:0]      pt_data,
    output logic             res_we,
    output logic [31:0]      res_crc,
    output logic [16:0]      res_words,
    output logic [7:0]       res_layout,
    output logic [7:0]       res_flags,
    output logic             res_hit,

    output logic             busy,            // owns the SRAM
    output logic             ready,           // cartridge mapped (or refused: err)
    output logic [4:0]       err,             // [0] no cartridge or length mismatch,
                                              // [1] bytes out of order, [2] over 64K
                                              // words, [3] SRAM write overrun,
                                              // [4] table length != 0x0082 size
    output logic [1:0]       len_st,          // len_chk of the last finish
    output logic [11:0]      slot_st          // per slot: 0 empty, 1 wrong, 2 ok
);

    localparam logic [7:0] FLAG_ECS = 8'h01, FLAG_ECS_OFF = 8'h20, FLAG_EST = 8'h40,
                           FLAG_ECS_RISK = 8'h80;

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
    assign m_req   = wq_n != 3'd0;
    assign {m_be, m_addr, m_wdata} = wq[wq_rd];
    wire logic   wq_full = wq_n == 3'd4;

    // ------------------------------------------------------------ stream
    wire logic [3:0]  slot = ld_addr[27:24];
    wire logic [23:0] off  = ld_addr[23:0];
    logic [7:0]  hb = 8'd0;                    // high byte of the word being built
    logic [31:0] crc = 32'hFFFFFFFF;
    logic [31:0] crc_at [4];
    logic [24:0] cnt [6];                      // per slot: last offset + 1
    logic        started = 1'b0, seq_err = 1'b0, big = 1'b0, ovr = 1'b0;
    logic        pending = 1'b1;               // a cartridge stream not finished yet
    wire logic [31:0] crc_in  = off == 24'd0 ? 32'hFFFFFFFF : crc;
    wire logic [31:0] crc_nxt = crc_byte(crc_in, ld_data);

    // ------------------------------------------------------------ finish
    typedef enum logic [3:0] {
        F_IDLE, F_CHECK, F_FIX, F_LK, F_LK_W, F_LK_C, F_LK_FW, F_LK_F,
        F_PT, F_PT_W, F_CLR, F_DRAIN, F_RES
    } fstate_t;
    fstate_t     st = F_IDLE;
    logic        len_d = 1'b0;
    logic [31:0] len = 32'd0;
    logic [16:0] words = 17'd0;
    logic [31:0] crc_fin = 32'd0;
    logic [8:0]  lo = 9'd0, hi = 9'd0;
    logic [7:0]  lid = 8'd0, flg = 8'd0;
    logic        hitf = 1'b0;
    logic [5:0]  p = 6'd0;
    logic [14:0] clr = 15'd0;
    logic [7:0]  conf = 8'd0;
    wire  logic [8:0]  mid   = 9'((10'(lo) + 10'(hi)) >> 1);
    wire  logic [5:0]  units = 6'((18'(words) + 18'd2047) >> 11);
    wire  logic [16:0] size256 = (words + 17'd255) >> 8;

    assign crc_ra = mid[7:0];
    assign lay_ra = {lid[4:0], p[4:0]};

    initial begin
        for (int i = 0; i < 6; i++) cnt[i] = 25'd0;
        for (int i = 0; i < 4; i++) begin crc_at[i] = 32'd0; wq[i] = 35'd0; end
        rom_we = 1'b0; rom_wsel = 2'd0; rom_waddr = 12'd0; rom_wdata = 10'd0;
        pt_we = 1'b0; pt_idx = 5'd0; pt_data = 16'd0;
        res_we = 1'b0; res_crc = 32'd0; res_words = 17'd0; res_layout = 8'd0;
        res_flags = 8'd0; res_hit = 1'b0; ready = 1'b0; err = 5'd0; len_st = 2'd0;
    end

    // streamed words (cartridge, ECS ROM) have priority; the finish steps
    // push only when the queue has room and no streamed word does
    logic        s_push, f_push;
    logic [34:0] s_d, f_d;
    always_comb begin
        s_push = 1'b0;
        s_d = 35'd0;
        if (ld_wr && off[0] && slot == 4'd0 && off[23:1] < 23'h10000) begin
            s_push = 1'b1;
            s_d = {2'b11, off[17:1], hb, ld_data};
        end else if (ld_wr && off[0] && slot == 4'd4 && off < 24'd24576) begin
            s_push = 1'b1;
            s_d = {2'b11, ECS_BASE + {3'd0, off[14:1]}, hb, ld_data};
        end
        f_push = 1'b0;
        f_d = 35'd0;
        if (st == F_FIX && len[0] && {1'b0, len[31:1]} < 32'h10000) begin
            // odd length: the last word's low byte is 0, not the pad byte
            f_push = !s_push && !wq_full;
            f_d = {2'b01, len[17:1], 16'h0000};
        end else if (st == F_CLR) begin
            f_push = !s_push && !wq_full;
            f_d = {2'b11, RAM_BASE + {2'd0, clr}, 16'h0000};
        end
        push   = s_push || f_push;
        push_d = s_push ? s_d : f_d;
    end
    wire logic push_ok = push && !(wq_full && !m_ack);

    always_ff @(posedge clk) begin
        rom_we <= 1'b0;
        pt_we  <= 1'b0;
        res_we <= 1'b0;
        len_d  <= len_valid;

        // ---- write queue
        if (push_ok) begin
            wq[wq_wr] <= push_d;
            wq_wr <= wq_wr + 2'd1;
        end else if (push)
            ovr <= 1'b1;                        // a streamed word found the queue full
        if (m_ack)
            wq_rd <= wq_rd + 2'd1;
        wq_n <= wq_n + {2'd0, push_ok} - {2'd0, m_ack};

        // ---- byte stream
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
                        started <= 1'b1;
                        pending <= 1'b1;
                        seq_err <= 1'b0;
                        big     <= 1'b0;
                        ovr     <= 1'b0;
                        ready   <= 1'b0;
                    end else if ({1'b0, off} != cnt[0]) begin
                        seq_err <= 1'b1;
                    end
                    if (off[23:1] >= 23'h10000)
                        big <= 1'b1;
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
                len <= cart_len;
                len_st <= len_chk;
                st  <= F_CHECK;
            end
            F_CHECK: begin
                words   <= 17'((len + 32'd1) >> 1);
                crc_fin <= ~crc_at[len[1:0] - 2'd1];
                lo <= 9'd0;
                hi <= 9'd256;
                if (!started || len == 32'd0 || {7'd0, cnt[0]} < len
                    || {7'd0, cnt[0]} - len > 32'd3 || seq_err || big || len > 32'h20000) begin
                    err  <= {len_st == 2'd2, ovr, big || len > 32'h20000, seq_err, !started
                             || len == 32'd0 || {7'd0, cnt[0]} < len || {7'd0, cnt[0]} - len > 32'd3};
                    words <= 17'd0;
                    crc_fin <= 32'd0;
                    lid  <= 8'd0;
                    flg  <= 8'd0;
                    hitf <= 1'b0;
                    p    <= 6'd0;
                    st   <= F_PT;
                end else begin
                    err <= {len_st == 2'd2, 4'd0};
                    st  <= F_FIX;
                end
            end
            F_FIX: if (!len[0] || {1'b0, len[31:1]} >= 32'h10000 || f_push)
                st <= F_LK;
            // binary search for the first entry whose CRC >= crc_fin
            F_LK: if (lo < hi)        st <= F_LK_W;
                  else if (lo[8])     st <= F_LK_F;     // past the end: miss
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
                    flg  <= crc_q[23:16];
                    hitf <= 1'b1;
                end else begin
                    lid  <= 8'd1;
                    flg  <= FLAG_EST;
                    hitf <= 1'b0;
                end
                p    <= 6'd0;
                conf <= 8'd0;
                st   <= F_PT;
            end
            // page table: entry p of the layout (lay_q is lay_rom[{lid, p}])
            F_PT: st <= F_PT_W;
            F_PT_W: begin
                pt_we  <= 1'b1;
                pt_idx <= p[4:0];
                if (lid >= 8'd32)
                    pt_data <= 16'd0;
                else if (lid == 8'd1 && lay_q[15:14] == 2'd1 && {1'b0, lay_q[8:0]} >= {4'd0, units})
                    pt_data <= 16'd0;                   // default map, past the image
                else begin
                    pt_data <= lay_q;
                    if (lay_q[15:14] != 2'd0) begin
                        if (p == 6'd8 || p == 6'd14 || p == 6'd15)
                            conf <= conf | FLAG_ECS_OFF;
                        if (p == 6'd4 || p == 6'd5 || p == 6'd28 || p == 6'd29)
                            conf <= conf | FLAG_ECS_RISK;
                    end
                end
                p <= p + 6'd1;
                if (p == 6'd31) begin
                    clr <= 15'd0;
                    st  <= F_CLR;
                end else
                    st <= F_PT;
            end
            F_CLR: if (f_push) begin
                if ({17'd0, clr} == RAM_CELLS - 1) st <= F_DRAIN;
                clr <= clr + 15'd1;
            end
            F_DRAIN: if (wq_n == 3'd0 && !push) st <= F_RES;
            F_RES: begin
                res_we     <= 1'b1;
                res_crc    <= crc_fin;
                res_words  <= words;
                res_layout <= lid;
                res_flags  <= (lid == 8'd1 && (flg & FLAG_ECS) == 8'd0) ? flg | conf : flg;
                res_hit    <= hitf;
                ready      <= 1'b1;
                pending    <= 1'b0;
                if (ovr) err[3] <= 1'b1;
                st <= F_IDLE;
            end
            default: st <= F_IDLE;
        endcase

        if (reset) begin
            st <= F_IDLE;
            started <= 1'b0;
            pending <= 1'b1;
            ready <= 1'b0;
            err <= 5'd0;
            wq_rd <= 2'd0; wq_wr <= 2'd0; wq_n <= 3'd0;
        end
    end

    assign busy = st != F_IDLE || wq_n != 3'd0;

    // slot status for the test pattern: the system ROMs by size (the owner's
    // files, DESIGN.md 5.6), the cartridge by the loader's verdict: wrong
    // only for err[3:0] (not mapped, or an SRAM overrun); err[4] alone (the
    // load went on with the table's length) leaves it ok, the cartridge's
    // second card shows the length check
    localparam logic [24:0] SIZE [6] = '{25'd0, 25'd0, 25'd8192, 25'd2048, 25'd24576, 25'd2048};
    always_comb begin
        for (int i = 0; i < 6; i++) begin
            if (cnt[i] == 25'd0)
                slot_st[2*i +: 2] = 2'd0;
            else if (i == 0)
                slot_st[1:0] = (ready && err[3:0] != 4'd0) ? 2'd1 : 2'd2;
            else if (SIZE[i] == 25'd0 || cnt[i] == SIZE[i])
                slot_st[2*i +: 2] = 2'd2;
            else
                slot_st[2*i +: 2] = 2'd1;
        end
    end

endmodule

`default_nettype wire
