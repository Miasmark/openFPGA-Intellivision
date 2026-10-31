// Intellivision core: the Intellivoice's SPB640 speech buffer and SP0256-012
// speech processor (DESIGN.md 9 step 10; docs/VOICE_NOTES.md). The golden
// model is tools/sp0256.py (Voice): this module makes the same samples, step
// for step, and keeps the same state; every fact and source is listed there
// and in the notes.
//
// One sample per step pulse (the 10 kHz enable is intv_voice's): the
// sequencer runs while the repeat count is out (micro), then one filter step
// (filt); a step that the count runs out in is made again with the next
// parameters, as the model's step(). Time is plentiful (about 4,300 clk_sys
// a sample, and intv_voice's window gives 384): the sequencer reads one bit
// field at a time (two words from the resident ROM or the FIFO, two clocks
// each, intv_ram's port-B rule; the field formats are a block ROM), and the
// filter makes its 12 products two a stage with one multiplier. A step takes
// about 45 clk_sys without the sequencer and at most 232 in the benches.
//
// The 16 parameter registers, the 12 decoded ones and the delay line live in
// a 16 x 32 block RAM laid out as state words 6-18 (word w at w - 6), one
// read port (registered address, so data two clocks after the state that sets
// it) and one write port with byte enables (a write lands a clock after the
// state that asks for it). Clearing them is a valid flag per register byte
// (rv), per decoded word (dv) and per delay stage (zv): a cleared byte reads 0.
//
// Bus (between steps only: intv_voice holds an access that comes during one)
//   wr, wa = 0   the command (ALD): taken when lrq, then lrq := 0
//   wr, wa = 1   wd[10]: reset the SPB640 and the SP0256; else push wd[9:0]
//                into the FIFO unless it holds 64 decles
//   lrq, full    the read values' bit 15 ($0080, $0081)
//
// The resident ROM (2 KiB, ivoice.bin at byte $1000) is intv_sysrom's, read
// through rom_addr / rom_q (registered, one clock); bytes outside $1000-$17FF
// read 0 (the model's mem). The FIFO is a 64 x 10 block RAM (intv_ram, state
// id SS_ID + 1): the bus pushes through port A, the sequencer reads port B.
//
// Save state (tools/savestate.py; only while idle: intv_ss_ctl's quiet point
// waits for it): SS_ID words 0-19 below, the FIFO's 64 words at SS_ID + 1.
//   0  {page[3:0], mode[5:0], fsel, halted, ald[7:0], lrq}
//   1  pc[18:0] (bit address)          2  stack[18:0]
//   3  {fhead[15:0], ftail[15:0]}      4  {interp, rng[14:0], fbit[3:0], rpt[7:0]}
//   5  {cnt[9:0], per[7:0], amp[11:0]}
//   6-9    the 16 parameter registers, four a word (register 4 i + k in bits 8 k + 7 .. 8 k)
//   10-12  the 12 decoded coefficient registers (B0 F0 B1 ... F5), four a word
//   13-18  {z1[j], z0[j]}, j = 0..5     19  the last sample
//
// SPDX-License-Identifier: MIT

`default_nettype none

module sp0256 #(
    parameter logic [7:0] SS_ID = 8'h18
) (
    input  wire logic        clk,
    input  wire logic        reset,           // held: the power-up state (voice off, machine reset)

    input  wire logic        wr,
    input  wire logic        wa,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [15:0] wd,              // bits 9-0 (decle), 10 (reset), 7-0 (command)
    /* verilator lint_on UNUSEDSIGNAL */
    output logic             lrq,
    output logic             full,

    input  wire logic        step,            // make one sample (only while !busy)
    output logic             busy,
    output logic             done,            // one clk with the new sample
    output logic [15:0]      sample,          // the filter's output, 16-bit signed

    output logic [10:0]      rom_addr,
    input  wire logic [7:0]  rom_q,

    input  wire logic        ss_en,
    input  wire logic [15:0] ss_addr,
    input  wire logic        ss_we,
    input  wire logic [31:0] ss_wdata,
    output logic [31:0]      ss_rdata
);

`include "sp0256_fmt.svh"

    localparam int AM = 0, PR = 1, IA = 14, IP = 15;
    localparam logic [3:0] OP_RTS = 4'b0000, OP_SETMODE = 4'b1000, OP_JMP = 4'b0111, OP_JSR = 4'b1011,
                           OP_PAUSE = 4'b1111;

    // ------------------------------------------------------------ state
    logic [18:0] pc = 19'd0, stack = 19'd0;
    logic [3:0]  page = 4'd1;
    logic [5:0]  mode = 6'd0;
    logic        halted = 1'b1, fsel = 1'b0, interp = 1'b0;
    logic [7:0]  ald = 8'd0;
    logic [15:0] fhead = 16'd0, ftail = 16'd0;
    logic [3:0]  fbit = 4'd0;
    logic [15:0] rv = 16'd0;               // r[i] holds a value (else it reads 0)
    logic [2:0]  dv = 3'd0;                // decoded word 4 + i
    logic [5:0]  zv = 6'd0;                // delay stage {z1[j], z0[j]}
    logic [11:0] amp = 12'd0;
    logic [7:0]  per = 8'd0;
    logic signed [9:0] cnt = 10'sd0;
    logic signed [7:0] rpt = -8'sd1;
    logic [14:0] rng = 15'd1;
    initial begin
        lrq = 1'b1;
        sample = 16'd0;
    end

    assign full = $signed(fhead - ftail) >= 16'sd64;

    // ------------------------------------------------------------ FIFO
    logic [5:0]  fifo_rb;
    logic [9:0]  fifo_qb;
    logic        push;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [9:0]  fifo_qa;
    /* verilator lint_on UNUSEDSIGNAL */
    logic [31:0] ssr_fifo;
    intv_ram #(.AW(6), .DW(10), .WORDS(64), .SS_ID(SS_ID + 8'd1)) fifo (
        .clk, .addr(fhead[5:0]), .we(push), .d(wd[9:0]), .q(fifo_qa),
        .addr_b(fifo_rb), .q_b(fifo_qb),
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_fifo));

    // ------------------------------------------------------------ the engine
    typedef enum logic [4:0] {
        S_IDLE, S_TOP, S_MIC, S_OPC, S_JLO, S_XFER, S_FLW, S_FLD, S_FAPP, S_FDONE,
        S_DEC, S_D1, S_D2, S_D3, S_D4, S_D5, S_EXC, S_X1, S_X2, S_EXN,
        S_M0, S_M1, S_M2, S_M3, S_MB, S_MF,
        G_A0, G_W0, G_A1, G_W1, G_C
    } st_t;
    st_t         st = S_IDLE, gret = S_IDLE;
    logic [3:0]  gn = 4'd0;                // getb: bits
    logic [7:0]  gv = 8'd0;                // getb: the value
    logic [9:0]  w0 = 10'd0;               // getb: the first word (FIFO decle or ROM byte)
    logic        inr = 1'b0;               // the ROM byte asked for is in $1000-$17FF
    logic [3:0]  imm = 4'd0, op = 4'd0;
    logic [4:0]  fi = 5'd0, nf = 5'd0;
    logic [3:0]  freg = 4'd0;
    logic [2:0]  fshf = 3'd0;
    logic [1:0]  fkind = 2'd0;
    logic [2:0]  j = 3'd0;
    logic [15:0] s = 16'd0;
    logic [31:0] t = 32'd0;                // a word read before (r words 0 / 1-2, a delay stage)
    logic [15:0] db = 16'd0;               // the stage's two decoded registers {F, B}
    logic [12:0] fq = 13'd0;               // the field format ROM's word ({op, mode, fi}, a clock late)

    // ------------------------------------------------------------ the register RAM
    (* ramstyle = "M10K, no_rw_check" *) logic [3:0][7:0] rmem [16];
    logic [3:0]  mra = 4'd0, mqa = 4'd0;   // the engine's read address; mq's address
    logic [31:0] mq;
    logic        mwe = 1'b0;               // the write asked for (lands next clock)
    logic [3:0]  mwa = 4'd0, mbe = 4'd0;
    logic [31:0] mwd = 32'd0;

    function automatic logic [3:0] rev4(input logic [3:0] x);
        return {x[0], x[1], x[2], x[3]};
    endfunction
    function automatic logic [7:0] rev8(input logic [7:0] x);
        for (int i = 0; i < 8; i++) rev8[i] = x[7 - i];
    endfunction
    function automatic logic signed [9:0] coef(input logic [7:0] x);
        logic [6:0] m;
        m = 7'(-x);
        return x[7] ? $signed({1'b0, qtbl(m)}) : -$signed({1'b0, qtbl(x[6:0])});
    endfunction

    // a word's valid lanes: r bytes, decoded words, delay stages
    function automatic logic [31:0] vmask(input logic [3:0] a);
        vmask = 32'd0;
        if (a < 4'd4) for (int k = 0; k < 4; k++) vmask[8 * k +: 8] = {8{rv[{a[1:0], 2'(k)}]}};
        else if (a < 4'd7) vmask = {32{dv[2'(a - 4'd4)]}};
        else if (a < 4'd13) vmask = {32{zv[3'(a - 4'd7)]}};
    endfunction

    wire logic [15:0] ba = pc[18:3];                    // the ROM byte at the PC
    wire logic        h = st == S_MF;                    // the F half of a stage
    wire logic [31:0] mqm = mq & vmask(mqa);             // the word read, cleared lanes 0

    // the multiplier: one product a clock (coefficient x delay word)
    wire logic signed [9:0]  mc = coef(h ? db[15:8] : db[7:0]);
    wire logic signed [15:0] mz = h ? t[15:0] : t[31:16];
    wire logic signed [25:0] mp = mc * mz;
    /* verilator lint_off UNUSEDSIGNAL */
    wire logic signed [25:0] msh = h ? (mp >>> 8) : (mp >>> 9);
    /* verilator lint_on UNUSEDSIGNAL */
    wire logic [15:0] s_mac = s + msh[15:0];

    task automatic do_reset();
        fhead <= 16'd0; ftail <= 16'd0; fbit <= 4'd0;
        rv <= 16'd0; dv <= 3'd0; zv <= 6'd0;
        amp <= 12'd0; per <= 8'd0; cnt <= 10'sd0; rpt <= -8'sd1; rng <= 15'd1;
        interp <= 1'b0; halted <= 1'b1; lrq <= 1'b1; ald <= 8'd0;
        pc <= 19'd0; stack <= 19'd0; fsel <= 1'b0; mode <= 6'd0; page <= 4'd1;
    endtask

    // ------------------------------------------------------------ state port
    wire logic ss_hit = ss_addr[15:8] == SS_ID && ss_addr[7:0] < 8'd20;
    wire logic [4:0] ss_w = ss_addr[4:0];
    wire logic       ss_m = ss_w >= 5'd6 && ss_w <= 5'd18;    // a word of the register RAM
    wire logic [3:0] ss_a = 4'(ss_w - 5'd6);

    always_ff @(posedge clk) begin
        if (mwe) begin
            if (mbe[0]) rmem[mwa][0] <= mwd[7:0];
            if (mbe[1]) rmem[mwa][1] <= mwd[15:8];
            if (mbe[2]) rmem[mwa][2] <= mwd[23:16];
            if (mbe[3]) rmem[mwa][3] <= mwd[31:24];
        end
        mq <= rmem[ss_en ? ss_a : mra];
        mqa <= ss_en ? ss_a : mra;
    end
    initial begin
        for (int i = 0; i < 16; i++) rmem[i] = '0;
        mq = 32'd0;
    end

    always_comb begin
        push = 1'b0;
        if (wr && st == S_IDLE && !reset && wa && !wd[10] && !full) push = 1'b1;
    end

    always_ff @(posedge clk) begin
        logic [19:0] d20;
        logic [15:0] d16;
        logic [7:0]  v8, sv, cur;
        logic [4:0]  nfb;
        logic [6:0]  hdr;
        logic [12:0] fld;
        logic [5:0]  rep;
        logic signed [9:0] cn;
        logic signed [7:0] rp;
        logic signed [12:0] x;
        logic [14:0] rg;
        logic        di;
        logic [7:0]  ram, rpr;
        logic [18:0] ta;
        done <= 1'b0;
        mwe <= 1'b0;
        if (reset) begin
            do_reset();
            st <= S_IDLE;
            busy <= 1'b0;
        end else if (ss_we && ss_hit) begin
            case (ss_w)
                5'd0: {page, mode, fsel, halted, ald, lrq} <= ss_wdata[20:0];
                5'd1: pc <= ss_wdata[18:0];
                5'd2: stack <= ss_wdata[18:0];
                5'd3: {fhead, ftail} <= ss_wdata;
                5'd4: {interp, rng, fbit, rpt} <= ss_wdata[27:0];
                5'd5: {cnt, per, amp} <= ss_wdata[29:0];
                5'd19: sample <= ss_wdata[15:0];
                default: if (ss_m) begin
                    mwe <= 1'b1; mwa <= ss_a; mbe <= 4'hF; mwd <= ss_wdata;
                    if (ss_a < 4'd4) rv[{ss_a[1:0], 2'd0} +: 4] <= 4'hF;
                    else if (ss_a < 4'd7) dv[2'(ss_a - 4'd4)] <= 1'b1;
                    else zv[3'(ss_a - 4'd7)] <= 1'b1;
                end
            endcase
        end else begin
            case (st)
                S_IDLE: begin
                    busy <= 1'b0;
                    if (wr) begin
                        if (!wa) begin
                            if (lrq) begin lrq <= 1'b0; ald <= wd[7:0]; end
                        end else if (wd[10])
                            do_reset();
                        else if (!full)
                            fhead <= fhead + 16'd1;
                    end else if (step) begin
                        busy <= 1'b1;
                        st <= S_TOP;
                    end
                end
                S_TOP: st <= rpt <= 8'sd0 ? S_MIC : S_EXC;
                // the sequencer: one instruction a pass
                S_MIC: begin
                    if (halted && !lrq) begin                // a command is waiting: take it
                        pc <= 19'h08000 | {7'd0, ald, 4'd0};          // byte $1000 + 2 x command
                        fsel <= 1'b0; halted <= 1'b0; lrq <= 1'b1; ald <= 8'd0;
                        rv <= 16'd0;
                        gn <= 4'd8; gret <= S_OPC; st <= G_A0;
                    end else if (halted) begin               // idle: the registers cleared, not decoded
                        rpt <= 8'sd1; lrq <= 1'b1; ald <= 8'd0;
                        rv <= 16'd0;
                        st <= S_EXC;
                    end else begin
                        gn <= 4'd8; gret <= S_OPC; st <= G_A0;
                    end
                end
                S_OPC: begin
                    imm <= gv[3:0];
                    op <= rev4(gv[7:4]);
                    case (rev4(gv[7:4]))
                        OP_RTS: begin
                            if (gv[3:0] != 4'd0) begin       // SETPAGE
                                page <= rev4(gv[3:0]);
                                mode <= mode & 6'h0F;
                                st <= S_MIC;
                            end else begin                    // RTS: an empty stack halts
                                if (stack != 19'd0) pc <= stack;
                                else begin halted <= 1'b1; pc <= 19'd0; end
                                stack <= 19'd0;
                                mode <= mode & 6'h0F;
                                st <= S_XFER;
                            end
                        end
                        OP_JMP, OP_JSR: begin gn <= 4'd8; gret <= S_JLO; st <= G_A0; end
                        OP_SETMODE: begin
                            mode <= {gv[1:0], 1'b0, gv[2], gv[3], 1'b0};
                            st <= S_MIC;
                        end
                        default: begin
                            rep = {mode[5:4], gv[3:0]};
                            mode <= mode & 6'h0F;
                            if (rep == 6'd0)
                                st <= S_MIC;
                            else begin
                                rpt <= $signed({2'd0, rep}) + 8'sd1;
                                hdr = fmt_hdr(rev4(gv[7:4]), mode[2:1]);
                                if (hdr[6]) rv <= 16'd0;
                                if (hdr[5]) begin rv[12] <= 1'b0; rv[13] <= 1'b0; end
                                nf <= hdr[4:0];
                                fi <= 5'd0;
                                st <= hdr[4:0] == 5'd0 ? S_FDONE : S_FLW;
                            end
                        end
                    endcase
                end
                S_JLO: begin
                    ta = {page, rev4(imm), rev8(gv), 3'd0};
                    if (op == OP_JSR) stack <= (pc + 19'd7) & ~19'd7;
                    pc <= ta;
                    mode <= mode & 6'h0F;
                    st <= S_XFER;
                end
                S_XFER: begin
                    fsel <= pc == 19'h0C000;
                    if (pc == 19'h0C000 && fbit != 4'd0) begin  // a jump into the FIFO drops a partial decle
                        if ($signed(ftail - fhead) < 16'sd0) ftail <= ftail + 16'd1;
                        fbit <= 4'd0;
                    end
                    st <= S_MIC;
                end
                S_FLW: st <= S_FLD;                         // the format ROM's word for fi
                S_FLD: begin
                    fld = fq;
                    freg <= fld[12:9]; fshf <= fld[4:2]; fkind <= fld[1:0];
                    mra <= {2'd0, fld[12:11]};              // r[freg]'s word, read during getb
                    gn <= fld[8:5]; gret <= S_FAPP; st <= G_A0;
                end
                S_FAPP: begin
                    cur = mqm[8 * freg[1:0] +: 8];
                    v8 = gv << fshf;
                    case (fkind)
                        2'd1: v8 = (cur & ((8'd1 << fshf) - 8'd1)) | v8;
                        2'd2: begin
                            sv = gv;
                            if (gv[3'(gn - 4'd1)]) sv = gv | ~((8'd1 << gn) - 8'd1);   // sign-extend
                            v8 = cur + (sv << fshf);
                        end
                        default: ;
                    endcase
                    mwe <= 1'b1; mwa <= {2'd0, freg[3:2]}; mbe <= 4'(1 << freg[1:0]); mwd <= {4{v8}};
                    rv[freg] <= 1'b1;
                    fi <= fi + 5'd1;
                    st <= fi + 5'd1 == nf ? S_FDONE : S_FLW;
                end
                S_FDONE: begin
                    if (op == OP_PAUSE) begin
                        mwe <= 1'b1; mwa <= 4'd0; mbe <= 4'b0010; mwd <= {4{8'd64}};
                        rv[PR] <= 1'b1;
                    end
                    st <= S_DEC;
                end
                // regdec: r words 0-3 read in turn; decoded word 4 + i = {r[4 i + 5:4 i + 2]}
                S_DEC: begin mra <= 4'd0; st <= S_D1; end
                S_D1: begin mra <= 4'd1; st <= S_D2; end
                S_D2: begin
                    amp <= {7'd0, mqm[4:0]} << mqm[7:5];
                    cnt <= 10'sd0;
                    per <= mqm[15:8];
                    t <= mqm; mra <= 4'd2; st <= S_D3;
                end
                S_D3, S_D4, S_D5: begin
                    mwe <= 1'b1; mbe <= 4'hF; mwd <= {mqm[15:0], t[31:16]};
                    mwa <= st == S_D3 ? 4'd4 : st == S_D4 ? 4'd5 : 4'd6;
                    dv <= dv | (st == S_D3 ? 3'b001 : st == S_D4 ? 3'b010 : 3'b100);
                    t <= mqm; mra <= 4'd3;
                    if (st == S_D5) interp <= mqm[31:16] != 16'd0;     // IA, IP
                    st <= st == S_D3 ? S_D4 : st == S_D4 ? S_D5 : S_EXC;
                end
                // the filter step: AM, PR (word 0) and IA, IP (word 3) read, the excitation,
                // then the 12 products
                S_EXC: begin mra <= 4'd0; st <= S_X1; end
                S_X1: begin mra <= 4'd3; st <= S_X2; end
                S_X2: begin t <= mqm; st <= S_EXN; end
                S_EXN: begin
                    di = 1'b0; cn = cnt; rp = rpt; rg = rng;
                    if (per != 8'd0) begin
                        if (cnt <= 10'sd0) begin
                            cn = cnt + $signed({2'd0, per}); x = $signed({1'b0, amp});
                            rp = rpt - 8'sd1; di = interp;
                            zv <= 6'd0;
                        end else begin
                            x = 13'sd0; cn = cnt - 10'sd1;
                        end
                    end else begin
                        cn = cnt - 10'sd1;
                        if (cn <= 10'sd0) begin
                            di = interp; cn = 10'sd64; rp = rpt - 8'sd1;
                            zv <= 6'd0;
                        end
                        rg = (rng >> 1) ^ (rng[0] ? 15'h4001 : 15'h0000);
                        x = rng[0] ? $signed({1'b0, amp}) : -$signed({1'b0, amp});
                    end
                    cnt <= cn; rpt <= rp; rng <= rg;
                    if (di) begin
                        ram = t[8 * AM +: 8] + mqm[8 * (IA - 12) +: 8];
                        rpr = t[8 * PR +: 8] + mqm[8 * (IP - 12) +: 8];
                        mwe <= 1'b1; mwa <= 4'd0; mbe <= 4'b0011; mwd <= {16'd0, rpr, ram};
                        rv[AM] <= 1'b1; rv[PR] <= 1'b1;
                        amp <= {7'd0, ram[4:0]} << ram[7:5];
                        per <= rpr;
                    end
                    if (rp <= 8'sd0)
                        st <= S_TOP;                         // made again with the next parameters
                    else begin
                        s <= 16'(x);
                        j <= 3'd0;
                        st <= S_M0;
                    end
                end
                // a stage: its decoded word and its delay words read, then B x z1, F x z0
                S_M0: begin mra <= 4'd4 + {2'd0, j[2:1]}; st <= S_M1; end
                S_M1: begin mra <= 4'd7 + {1'd0, j}; st <= S_M2; end
                S_M2: begin db <= j[0] ? mqm[31:16] : mqm[15:0]; st <= S_M3; end
                S_M3: begin t <= mqm; st <= S_MB; end
                S_MB: begin s <= s_mac; st <= S_MF; end
                S_MF: begin
                    s <= s_mac;
                    mwe <= 1'b1; mwa <= 4'd7 + {1'd0, j}; mbe <= 4'hF; mwd <= {t[15:0], s_mac};
                    zv[j] <= 1'b1;
                    if (j == 3'd5) begin
                        sample <= s_mac;
                        done <= 1'b1;
                        busy <= 1'b0;
                        st <= S_IDLE;
                    end else begin
                        j <= j + 3'd1;
                        st <= S_M0;
                    end
                end
                // getb: gn bits at the PC (ROM) or the FIFO's tail, LSB first
                G_A0: st <= G_W0;
                G_W0: st <= G_A1;
                G_A1: begin
                    w0 <= fsel ? fifo_qb : {2'd0, inr ? rom_q : 8'd0};
                    st <= G_W1;
                end
                G_W1: st <= G_C;
                G_C: begin
                    if (fsel) begin
                        d20 = {fifo_qb, w0};
                        v8 = 8'(d20 >> fbit) & ((8'd1 << gn) - 8'd1);
                        nfb = {1'b0, fbit} + {1'b0, gn};
                        if (nfb >= 5'd10) begin ftail <= ftail + 16'd1; fbit <= 4'(nfb - 5'd10); end
                        else fbit <= nfb[3:0];
                    end else begin
                        d16 = {inr ? rom_q : 8'd0, w0[7:0]};
                        v8 = 8'(d16 >> pc[2:0]) & ((8'd1 << gn) - 8'd1);
                        pc <= pc + 19'(gn);
                    end
                    gv <= v8;
                    st <= gret;
                end
                default: st <= S_IDLE;
            endcase
        end
    end

    // the field format ROM, {op, mode, fi} (fi < 16: LOADALL has 16 fields)
    (* romstyle = "M10K" *) logic [12:0] fmt_rom [1024];
    initial for (int i = 0; i < 1024; i++) fmt_rom[i] = fmt_fld(4'(i >> 6), 2'(i >> 4), 5'(i & 15));
    always_ff @(posedge clk) fq <= fmt_rom[{op, mode[2:1], fi[3:0]}];

    // the read addresses for getb: word 0 in G_A0/G_W0, word 1 in G_A1/G_W1 (held a clock
    // before q is taken, intv_ram's port-B rule; intv_sysrom's port the same way)
    always_ff @(posedge clk) begin
        logic [15:0] a1;
        a1 = ba + 16'd1;
        case (st)
            G_A0: begin
                fifo_rb <= ftail[5:0];
                rom_addr <= ba[10:0];
                inr <= ba[15:11] == 5'b00010;
            end
            G_A1: begin
                fifo_rb <= ftail[5:0] + 6'd1;
                rom_addr <= a1[10:0];
                inr <= a1[15:11] == 5'b00010;
            end
            default: ;
        endcase
    end
    initial begin fifo_rb = 6'd0; rom_addr = 11'd0; end

    // ------------------------------------------------------------ state read
    always_comb begin
        ss_rdata = ssr_fifo;
        if (ss_hit)
            case (ss_w)
                5'd0: ss_rdata = {11'd0, page, mode, fsel, halted, ald, lrq};
                5'd1: ss_rdata = {13'd0, pc};
                5'd2: ss_rdata = {13'd0, stack};
                5'd3: ss_rdata = {fhead, ftail};
                5'd4: ss_rdata = {4'd0, interp, rng, fbit, rpt};
                5'd5: ss_rdata = {2'd0, cnt, per, amp};
                5'd19: ss_rdata = {16'd0, sample};
                default: if (ss_m) ss_rdata = mqm;          // a clock after the address
            endcase
    end

endmodule

`default_nettype wire
