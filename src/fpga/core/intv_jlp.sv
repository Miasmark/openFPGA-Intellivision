// Intellivision core: the JLP cartridge board's features (build step 11;
// docs/JLP_NOTES.md). The golden model is tools/jlp.py (Jlp), settled against
// jzIntv as a black box (JLP_NOTES 4.1); every fact and choice is listed there.
// Its RAM ($8040-$9F7F, 8,000 words in SRAM at $1C000) is intv_cart's
// (intv_jlp_pkg's decode); everything else is here:
//
//   $8023 / $8024  JF.first ($00E0) / JF.last (JF.first + 8 x sectors - 1);
//                  0 / 0 without flash
//   $8025 / $8026  JF.addr / JF.row (write only)
//   $802D-$802F    flash commands (keys $C0DE write, $DEC0 read, $BEEF
//                  erase); read 0 when idle
//   $8033 / $8034  the switch: $4A5A on, $6A7A off (taken on or off)
//   $9F80-$9F8B    multiply / divide operands (read back); a write recomputes
//                  its pair's function into $9F8E / $9F8F (x / 0: unchanged)
//   $9F8C / $9F8D  read 0                  $9F8E / $9F8F  results (writable)
//   $9F90-$9F97    eight read / write registers
//   $9FFC          CRC data: crc := crc16(crc ^ d) (16 right shifts, poly $AD52)
//   $9FFD          the CRC (write: seed)   $9FFE  random   $9FFF  reads 0
// While switched off only the switch answers. mode (jlp_accel) and sect come
// from the loader: mode 0 no JLP, 1 on at reset without flash, 2 off at reset
// with flash, 3 on with flash; the switch takes the mode's value at every
// machine reset.
//
// Random: a read of $9FFE gives the state, then state := crc16(state, the
// read's cycle number mod 2^16) (deterministic: save states, benches). Cycle
// numbers are the model's: the first ce after reset starts cycle 0 and does
// not count (started; intv_voice likewise).
//
// Flash: the store is a block RAM of 16 sectors x 8 rows x 96 words
// (12,288 x 16), the nonvolatile slot's data (outside the save state). It
// holds each word inverted, so its power-on zeros read as erased ($FFFF). A command is checked at its write: the row in JF.first..JF.last,
// the 96 RAM words in $8040-$9F7F (read, write), and for a write the row
// empty (empt, one bit a row, kept as rows are written, erased and loaded);
// one that fails is dropped (nothing, not busy). One that passes makes the
// JLP busy for BUSY CPU cycles (busy: the cartridge port answers and stores
// nothing, intv_cart, so the CPU waits in System RAM, as the JLP guide's
// routine does) while the engine copies 96 words between the store and the
// RAM in SRAM (the jm_* port; the SRAM is the cartridge port's otherwise) or
// erases a sector (768 words). The engine is done in about 1,000 clk_sys,
// long before BUSY (about 4,800). When a cartridge load starts (fl_clr) the
// engine erases the whole store (12,288 clk_sys), so a game without a .sav
// starts erased and never sees another's rows; the Pocket writes the new
// game's .sav after that (intv_jlp_nv).
//
// Save state (module id SS_ID, 28 words; tools/jlp.py Jlp.state, words 0-26):
//   0  {busy cycles left[15:0], on}       1-12  the operands
//   13-14  the results    15 CRC    16 random    17 JF.addr    18 JF.row
//   19-26  the extended registers         27 {started, cycle[15:0]}
// Only at the quiet point (intv_ss_ctl): no bus access, CRC or divide in
// progress; the engine idle (eng_busy).
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_jlp #(
    parameter logic [7:0] SS_ID = 8'h20,
    parameter int         BUSY  = 100
) (
    input  wire logic        clk,
    input  wire logic        mreset,
    input  wire logic        fl_clr,          // a cartridge load starts: the store erased (one clk)
    input  wire logic [1:0]  mode,
    input  wire logic [4:0]  sect,
    input  wire logic        ce,
    input  wire logic        run,

    // CPU bus (intv_bus: the latched address, read and write ces)
    input  wire logic [15:0] a,
    input  wire logic        rd,
    input  wire logic        wr,
    input  wire logic [15:0] wdata,
    output logic             hit,
    output logic [15:0]      q,

    output logic             on,              // switched on (intv_cart: RAM and holes)
    output logic             busy,            // a flash command runs (intv_cart: silent)
    output logic             eng_busy,        // the engine works (intv_ss_ctl: not quiet)

    // the flash engine's SRAM port (intv_media)
    output logic             jm_req,
    output logic             jm_we,
    output logic [16:0]      jm_addr,
    output logic [15:0]      jm_wdata,
    input  wire logic        jm_ack,
    input  wire logic [15:0] jm_rdata,

    // the flash store's second port (the nonvolatile slot; a write marks its row)
    input  wire logic [13:0] nv_addr,
    input  wire logic        nv_we,
    input  wire logic [15:0] nv_wdata,
    output logic [15:0]      nv_q,

    // save state
    input  wire logic [15:0] ss_addr,
    input  wire logic        ss_we,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [31:0] ss_wdata,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic [31:0]      ss_rdata
);

    localparam logic [15:0] FIRST = 16'h00E0;
    localparam logic [15:0] POLY  = 16'hAD52;
    localparam logic [16:0] JLP_BASE = 17'h1C000;

    // ------------------------------------------------------------ state
    logic        on_q = 1'b0;
    logic [15:0] ops [12];
    logic [15:0] res0 = 16'd0, res1 = 16'd0;
    logic [15:0] ext [8];
    logic [15:0] crc = 16'hFFFF, rnd = 16'hFFFF;
    logic [15:0] jf_addr = 16'd0, jf_row = 16'd0;
    logic [15:0] left = 16'd0;                // busy CPU cycles left
    logic [15:0] cyc = 16'd0;
    logic        started = 1'b0;
    logic [127:0] empt = '1;                  // the store's rows that hold only $FFFF
    initial begin
        for (int i = 0; i < 12; i++) ops[i] = 16'd0;
        for (int i = 0; i < 8; i++) ext[i] = 16'd0;
    end

    assign on = on_q && mode != 2'd0;
    assign busy = left != 16'd0;

    // ------------------------------------------------------------ decode
    wire logic sel_rd = on && intv_jlp_pkg::reg_rd(a);
    wire logic [15:0] last = FIRST + {8'd0, sect, 3'd0} - 16'd1;
    wire logic has_fl = sect != 5'd0;

    always_comb begin
        q = 16'hFFFF;
        if (a >= 16'h9F80 && a <= 16'h9F8B) q = ops[4'(a - 16'h9F80)];
        else if (a == 16'h9F8E) q = res0;
        else if (a == 16'h9F8F) q = res1;
        else if (a >= 16'h9F90 && a <= 16'h9F97) q = ext[a[2:0]];
        else if (a == 16'h9FFD) q = crc;
        else if (a == 16'h9FFE) q = rnd;
        else if (a == 16'h8023) q = has_fl ? FIRST : 16'd0;
        else if (a == 16'h8024) q = has_fl ? last : 16'd0;
        else q = 16'd0;                       // $9F8C, $9F8D, $9FFF, the command registers
    end
    assign hit = sel_rd && !busy;

    // ------------------------------------------------------------ multiply / divide
    // a write to operand i recomputes function i >> 1 with its pair (the new value here)
    logic [3:0]  op_i;
    logic [15:0] op_a, op_b;
    always_comb begin
        op_i = 4'(a - 16'h9F80);
        op_a = op_i[0] ? ops[{op_i[3:1], 1'b0}] : wdata;
        op_b = op_i[0] ? wdata : ops[{op_i[3:1], 1'b1}];
    end
    wire logic [2:0]  fn  = op_i[3:1];
    wire logic signed [16:0] mx = fn == 3'd0 || fn == 3'd1 ? {op_a[15], op_a} : {1'b0, op_a};
    wire logic signed [16:0] my = fn == 3'd0 || fn == 3'd2 ? {op_b[15], op_b} : {1'b0, op_b};
    /* verilator lint_off UNUSEDSIGNAL */
    wire logic signed [33:0] mp = mx * my;
    /* verilator lint_on UNUSEDSIGNAL */

    // the divider: 17-bit magnitudes, 17 steps, signs after (DIVSS: the quotient
    // negative when the signs differ, the remainder with the dividend's sign)
    logic        dv_go = 1'b0, dv_sq = 1'b0, dv_sr = 1'b0;
    logic [4:0]  dv_n = 5'd0;
    logic [16:0] dv_q = 17'd0, dv_r = 17'd0, dv_d = 17'd0;
    wire  logic [17:0] dv_t = {dv_r, dv_q[16]} - {1'b0, dv_d};

    // ------------------------------------------------------------ CRC / random
    logic        cr_go = 1'b0, cr_rnd = 1'b0;
    logic [4:0]  cr_n = 5'd0;
    logic [15:0] cr_v = 16'd0;

    // ------------------------------------------------------------ flash
    logic [15:0] store [12288];
    logic [15:0] st_q;
    logic [13:0] st_a = 14'd0;
    logic        st_we = 1'b0;
    logic [15:0] st_d = 16'd0;
    // A true dual-port block RAM in Quartus's template: each port reads its own write's data
    // (new data) in the write's clock. Old data on a port that writes is not a mode the M10K
    // has in true dual port, and 0.0.21's first fit failed on it (Error 276003: the store left
    // as registers). Nothing reads a port in a clock it writes: the engine reads st_q one
    // clock after an address with no write (E_RD_A -> E_RD_W), the slot nv_q in N_R1 / N_R3.
    always_ff @(posedge clk) begin
        if (st_we) begin
            store[st_a] <= st_d;
            st_q <= st_d;
        end else
            st_q <= store[st_a];
    end
    logic [15:0] nv_qi;
    always_ff @(posedge clk) begin
        if (nv_we) begin
            store[nv_addr] <= ~nv_wdata;
            nv_qi <= ~nv_wdata;
        end else
            nv_qi <= store[nv_addr];
    end
    assign nv_q = ~nv_qi;

    /* verilator lint_off UNUSEDSIGNAL */
    wire logic [15:0] row_r  = jf_row - FIRST;               // the row in the store
    /* verilator lint_on UNUSEDSIGNAL */
    wire logic        row_ok = has_fl && jf_row >= FIRST && jf_row <= last;
    wire logic        ram_ok = jf_addr >= 16'h8040 && jf_addr <= 16'h9F7F - 16'd95;
    wire logic [6:0]  row7   = row_r[6:0];
    wire logic [1:0]  cmd    = a == 16'h802D && wdata == 16'hC0DE ? 2'd1 :
                               a == 16'h802E && wdata == 16'hDEC0 ? 2'd2 :
                               a == 16'h802F && wdata == 16'hBEEF ? 2'd3 : 2'd0;
    wire logic        cmd_ok = cmd == 2'd3 ? row_ok :
                               cmd != 2'd0 && row_ok && ram_ok && (cmd == 2'd2 || empt[row7]);

    typedef enum logic [2:0] {E_IDLE, E_RD_S, E_RD_A, E_RD_W, E_WR_R, E_WR_S, E_ER, E_CLR} est_t;
    est_t        est = E_IDLE;
    logic [9:0]  ei = 10'd0;                  // the word
    logic [13:0] eb = 14'd0;                  // the store's first word
    logic [12:0] er = 13'd0;                  // the RAM's first word (from $8040)
    logic [6:0]  erow = 7'd0;
    logic        e_ne = 1'b0;                 // a word not $FFFF written
    logic        nv_mark = 1'b0;
    logic [6:0]  nv_row = 7'd0;
    assign eng_busy = est != E_IDLE;

    // ------------------------------------------------------------ the module
    wire logic ss_hit = ss_addr[15:8] == SS_ID && ss_addr[7:0] < 8'd28;
    wire logic [4:0] ss_w = ss_addr[4:0];

    always_ff @(posedge clk) begin
        logic [15:0] c;
        logic [16:0] dq, dr;
        st_we <= 1'b0;
        // the nonvolatile slot writes the store: a word not $FFFF marks its row
        nv_mark <= nv_we && nv_wdata != 16'hFFFF;
        nv_row  <= 7'(nv_addr / 14'd96);
        if (nv_mark) empt[nv_row] <= 1'b0;
        if (mreset) begin
            on_q <= mode != 2'd2;
            for (int i = 0; i < 12; i++) ops[i] <= 16'd0;
            for (int i = 0; i < 8; i++) ext[i] <= 16'd0;
            res0 <= 16'd0; res1 <= 16'd0;
            crc <= 16'hFFFF; rnd <= 16'hFFFF;
            jf_addr <= 16'd0; jf_row <= 16'd0;
            left <= 16'd0;
            cyc <= 16'd0; started <= 1'b0;
            dv_go <= 1'b0; cr_go <= 1'b0;
        end else if (ss_we && ss_hit) begin
            case (ss_w)
                5'd0:  {left, on_q} <= ss_wdata[16:0];
                5'd13: res0 <= ss_wdata[15:0];
                5'd14: res1 <= ss_wdata[15:0];
                5'd15: crc <= ss_wdata[15:0];
                5'd16: rnd <= ss_wdata[15:0];
                5'd17: jf_addr <= ss_wdata[15:0];
                5'd18: jf_row <= ss_wdata[15:0];
                5'd27: {started, cyc} <= ss_wdata[16:0];
                default:
                    if (ss_w >= 5'd1 && ss_w <= 5'd12) ops[4'(ss_w - 5'd1)] <= ss_wdata[15:0];
                    else if (ss_w >= 5'd19 && ss_w <= 5'd26) ext[3'(ss_w - 5'd19)] <= ss_wdata[15:0];
            endcase
        end else begin
            // cycles
            if (ce && run && !started) started <= 1'b1;
            else if (ce && run) cyc <= cyc + 16'd1;
            if (ce && run && busy) left <= left - 16'd1;
            // the switch, then the registers (none while busy)
            if (wr && !busy && mode != 2'd0) begin
                if (a == 16'h8033 && wdata == 16'h4A5A) on_q <= 1'b1;
                if (a == 16'h8034 && wdata == 16'h6A7A) on_q <= 1'b0;
            end
            if (wr && !busy && on && intv_jlp_pkg::reg_wr(a)) begin
                if (a >= 16'h9F80 && a <= 16'h9F8B) begin
                    ops[op_i] <= wdata;
                    if (fn < 3'd4) begin
                        res0 <= mp[15:0];
                        res1 <= mp[31:16];
                    end else if (op_b != 16'd0) begin       // x / 0: the results stay
                        dv_go <= 1'b1;
                        dv_n  <= 5'd17;
                        dv_sq <= fn == 3'd4 && (op_a[15] ^ op_b[15]);
                        dv_sr <= fn == 3'd4 && op_a[15];
                        dv_q  <= fn == 3'd4 && op_a[15] ? 17'(-{op_a[15], op_a}) : {1'b0, op_a};
                        dv_d  <= fn == 3'd4 && op_b[15] ? 17'(-{op_b[15], op_b}) : {1'b0, op_b};
                        dv_r  <= 17'd0;
                    end
                end
                if (a == 16'h9F8E) res0 <= wdata;
                if (a == 16'h9F8F) res1 <= wdata;
                if (a >= 16'h9F90 && a <= 16'h9F97) ext[a[2:0]] <= wdata;
                if (a == 16'h9FFC) begin cr_go <= 1'b1; cr_rnd <= 1'b0; cr_n <= 5'd16; cr_v <= crc ^ wdata; end
                if (a == 16'h9FFD) crc <= wdata;
                if (a == 16'h8025) jf_addr <= wdata;
                if (a == 16'h8026) jf_row <= wdata;
                if (cmd != 2'd0 && cmd_ok) begin
                    left <= 16'(BUSY - 1);
                    eb   <= 14'(row_r[6:0]) * 14'd96;
                    er   <= 13'(jf_addr - 16'h8040);
                    erow <= row7;
                    ei   <= 10'd0;
                    e_ne <= 1'b0;
                    est  <= cmd == 2'd1 ? E_WR_R : cmd == 2'd2 ? E_RD_S : E_ER;
                    if (cmd == 2'd3) begin
                        eb <= {row_r[6:3], 3'd0} * 14'd96;
                        ei <= 10'd0;
                    end
                end
            end
            if (rd && !busy && on && a == 16'h9FFE) begin
                cr_go <= 1'b1; cr_rnd <= 1'b1; cr_n <= 5'd16; cr_v <= rnd ^ cyc;
            end
            // the CRC engine: 16 right shifts
            if (cr_go) begin
                c = (cr_v >> 1) ^ (cr_v[0] ? POLY : 16'd0);
                cr_v <= c;
                cr_n <= cr_n - 5'd1;
                if (cr_n == 5'd1) begin
                    cr_go <= 1'b0;
                    if (cr_rnd) rnd <= c; else crc <= c;
                end
            end
            // the divider: one quotient bit a clock; the results at the last
            if (dv_go) begin
                dq = {dv_q[15:0], !dv_t[17]};
                dr = dv_t[17] ? {dv_r[15:0], dv_q[16]} : dv_t[16:0];
                dv_q <= dq;
                dv_r <= dr;
                dv_n <= dv_n - 5'd1;
                if (dv_n == 5'd1) begin
                    dv_go <= 1'b0;
                    res0 <= dv_sq ? 16'(-dq) : dq[15:0];
                    res1 <= dv_sr ? 16'(-dr) : dr[15:0];
                end
            end
        end

        // the flash engine (runs on through a state load: the quiet point waits for it)
        case (est)
            E_IDLE: if (fl_clr) begin
                empt <= '1;
                st_a <= 14'd0; st_d <= 16'h0000; st_we <= 1'b1;
                est <= E_CLR;
            end
            E_RD_S: begin                                   // store word -> RAM
                st_a <= eb + 14'(ei);
                est  <= E_RD_A;
            end
            E_RD_A: est <= E_RD_W;                          // st_q: the word, next clock
            E_RD_W: if (!jm_req) begin
                jm_req <= 1'b1; jm_we <= 1'b1;
                jm_addr <= JLP_BASE + {4'd0, er + 13'(ei)};
                jm_wdata <= ~st_q;
            end else if (jm_ack) begin
                jm_req <= 1'b0;
                if (ei == 10'd95) est <= E_IDLE;
                else begin ei <= ei + 10'd1; est <= E_RD_S; end
            end
            E_WR_R: if (!jm_req) begin                      // RAM word -> store
                jm_req <= 1'b1; jm_we <= 1'b0;
                jm_addr <= JLP_BASE + {4'd0, er + 13'(ei)};
            end else if (jm_ack) begin
                jm_req <= 1'b0;
                st_a <= eb + 14'(ei); st_d <= ~jm_rdata; st_we <= 1'b1;
                if (jm_rdata != 16'hFFFF) e_ne <= 1'b1;
                est <= E_WR_S;
            end
            E_WR_S: begin
                if (ei == 10'd95) begin
                    if (e_ne) empt[erow] <= 1'b0;
                    est <= E_IDLE;
                end else begin
                    ei <= ei + 10'd1;
                    est <= E_WR_R;
                end
            end
            E_ER: begin                                     // 768 words of $FFFF
                st_a <= eb + 14'(ei); st_d <= 16'h0000; st_we <= 1'b1;
                if (ei == 10'd767) begin
                    empt[{erow[6:3], 3'd0} +: 8] <= 8'hFF;
                    est <= E_IDLE;
                end else
                    ei <= ei + 10'd1;
            end
            E_CLR: begin                                    // the whole store erased
                st_a <= st_a + 14'd1; st_d <= 16'h0000; st_we <= 1'b1;
                if (st_a == 14'd12287) begin
                    st_we <= 1'b0;
                    est <= E_IDLE;
                end
            end
            default: est <= E_IDLE;
        endcase
    end

    initial begin jm_req = 1'b0; jm_we = 1'b0; jm_addr = 17'd0; jm_wdata = 16'd0; end

    // ------------------------------------------------------------ state read
    always_comb begin
        ss_rdata = 32'd0;
        if (ss_hit)
            case (ss_w)
                5'd0:  ss_rdata = {15'd0, left, on_q};
                5'd13: ss_rdata = {16'd0, res0};
                5'd14: ss_rdata = {16'd0, res1};
                5'd15: ss_rdata = {16'd0, crc};
                5'd16: ss_rdata = {16'd0, rnd};
                5'd17: ss_rdata = {16'd0, jf_addr};
                5'd18: ss_rdata = {16'd0, jf_row};
                5'd27: ss_rdata = {15'd0, started, cyc};
                default:
                    if (ss_w >= 5'd1 && ss_w <= 5'd12) ss_rdata = {16'd0, ops[4'(ss_w - 5'd1)]};
                    else if (ss_w >= 5'd19 && ss_w <= 5'd26) ss_rdata = {16'd0, ext[3'(ss_w - 5'd19)]};
            endcase
    end

endmodule

`default_nettype wire
