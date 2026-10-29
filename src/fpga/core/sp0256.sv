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
// a sample): the sequencer reads one bit field at a time (two words from the
// resident ROM or the FIFO, two clocks each, intv_ram's port-B rule), and the
// filter makes its 12 products one a clock with one multiplier. A step takes
// about 30 clk_sys without the sequencer and up to about 130 with a LOADALL.
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
    logic [7:0]  r [16];
    logic [7:0]  dec [12];
    logic [11:0] amp = 12'd0;
    logic [7:0]  per = 8'd0;
    logic signed [9:0] cnt = 10'sd0;
    logic signed [7:0] rpt = -8'sd1;
    logic [14:0] rng = 15'd1;
    logic signed [15:0] z0 [6];
    logic signed [15:0] z1 [6];
    initial begin
        lrq = 1'b1;
        sample = 16'd0;
        for (int i = 0; i < 16; i++) r[i] = 8'd0;
        for (int i = 0; i < 12; i++) dec[i] = 8'd0;
        for (int i = 0; i < 6; i++) begin z0[i] = 16'sd0; z1[i] = 16'sd0; end
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
        S_IDLE, S_TOP, S_MIC, S_OPC, S_JLO, S_XFER, S_FLD, S_FAPP, S_FDONE, S_DEC, S_EXC, S_MAC,
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
    logic        h = 1'b0;
    logic [15:0] s = 16'd0;

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

    wire logic [15:0] ba = pc[18:3];                    // the ROM byte at the PC
    wire logic        mac_b = !h;                        // the B half of a stage

    // the multiplier: one product a clock (coefficient x delay word)
    wire logic signed [9:0]  mc = coef(dec[{j, h}]);
    wire logic signed [15:0] mz = h ? z0[j] : z1[j];
    wire logic signed [25:0] mp = mc * mz;
    /* verilator lint_off UNUSEDSIGNAL */
    wire logic signed [25:0] msh = h ? (mp >>> 8) : (mp >>> 9);
    /* verilator lint_on UNUSEDSIGNAL */
    wire logic [15:0] s_mac = s + msh[15:0];

    task automatic do_reset();
        fhead <= 16'd0; ftail <= 16'd0; fbit <= 4'd0;
        for (int i = 0; i < 16; i++) r[i] <= 8'd0;
        for (int i = 0; i < 12; i++) dec[i] <= 8'd0;
        for (int i = 0; i < 6; i++) begin z0[i] <= 16'sd0; z1[i] <= 16'sd0; end
        amp <= 12'd0; per <= 8'd0; cnt <= 10'sd0; rpt <= -8'sd1; rng <= 15'd1;
        interp <= 1'b0; halted <= 1'b1; lrq <= 1'b1; ald <= 8'd0;
        pc <= 19'd0; stack <= 19'd0; fsel <= 1'b0; mode <= 6'd0; page <= 4'd1;
    endtask

    // ------------------------------------------------------------ state port
    wire logic ss_hit = ss_addr[15:8] == SS_ID && ss_addr[7:0] < 8'd20;
    wire logic [4:0] ss_w = ss_addr[4:0];

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
        logic [18:0] t;
        done <= 1'b0;
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
                5'd6, 5'd7, 5'd8, 5'd9:
                    for (int k = 0; k < 4; k++) r[4 * (int'(ss_w) - 6) + k] <= ss_wdata[8 * k +: 8];
                5'd10, 5'd11, 5'd12:
                    for (int k = 0; k < 4; k++) dec[4 * (int'(ss_w) - 10) + k] <= ss_wdata[8 * k +: 8];
                5'd19: sample <= ss_wdata[15:0];
                default: if (ss_w >= 5'd13 && ss_w <= 5'd18)
                    {z1[3'(ss_w - 5'd13)], z0[3'(ss_w - 5'd13)]} <= ss_wdata;
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
                        for (int i = 0; i < 16; i++) r[i] <= 8'd0;
                        gn <= 4'd8; gret <= S_OPC; st <= G_A0;
                    end else if (halted) begin               // idle: the registers cleared, not decoded
                        rpt <= 8'sd1; lrq <= 1'b1; ald <= 8'd0;
                        for (int i = 0; i < 16; i++) r[i] <= 8'd0;
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
                                if (hdr[6]) for (int i = 0; i < 16; i++) r[i] <= 8'd0;
                                if (hdr[5]) begin r[12] <= 8'd0; r[13] <= 8'd0; end
                                nf <= hdr[4:0];
                                fi <= 5'd0;
                                st <= hdr[4:0] == 5'd0 ? S_FDONE : S_FLD;
                            end
                        end
                    endcase
                end
                S_JLO: begin
                    t = {page, rev4(imm), rev8(gv), 3'd0};
                    if (op == OP_JSR) stack <= (pc + 19'd7) & ~19'd7;
                    pc <= t;
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
                S_FLD: begin
                    fld = fmt_fld(op, mode[2:1], fi);
                    freg <= fld[12:9]; fshf <= fld[4:2]; fkind <= fld[1:0];
                    gn <= fld[8:5]; gret <= S_FAPP; st <= G_A0;
                end
                S_FAPP: begin
                    cur = r[freg];
                    v8 = gv << fshf;
                    case (fkind)
                        2'd1: r[freg] <= (cur & ((8'd1 << fshf) - 8'd1)) | v8;
                        2'd2: begin
                            sv = gv;
                            if (gv[3'(gn - 4'd1)]) sv = gv | ~((8'd1 << gn) - 8'd1);   // sign-extend
                            r[freg] <= cur + (sv << fshf);
                        end
                        default: r[freg] <= v8;
                    endcase
                    fi <= fi + 5'd1;
                    st <= fi + 5'd1 == nf ? S_FDONE : S_FLD;
                end
                S_FDONE: begin
                    if (op == OP_PAUSE) r[PR] <= 8'd64;
                    st <= S_DEC;
                end
                S_DEC: begin                                // regdec
                    amp <= {7'd0, r[AM][4:0]} << r[AM][7:5];
                    cnt <= 10'sd0;
                    per <= r[PR];
                    for (int i = 0; i < 12; i++) dec[i] <= r[2 + i];
                    interp <= r[IA] != 8'd0 || r[IP] != 8'd0;
                    st <= S_EXC;
                end
                // the filter step: the excitation, then the 12 products
                S_EXC: begin
                    di = 1'b0; cn = cnt; rp = rpt; rg = rng;
                    if (per != 8'd0) begin
                        if (cnt <= 10'sd0) begin
                            cn = cnt + $signed({2'd0, per}); x = $signed({1'b0, amp});
                            rp = rpt - 8'sd1; di = interp;
                            for (int i = 0; i < 6; i++) begin z0[i] <= 16'sd0; z1[i] <= 16'sd0; end
                        end else begin
                            x = 13'sd0; cn = cnt - 10'sd1;
                        end
                    end else begin
                        cn = cnt - 10'sd1;
                        if (cn <= 10'sd0) begin
                            di = interp; cn = 10'sd64; rp = rpt - 8'sd1;
                            for (int i = 0; i < 6; i++) begin z0[i] <= 16'sd0; z1[i] <= 16'sd0; end
                        end
                        rg = (rng >> 1) ^ (rng[0] ? 15'h4001 : 15'h0000);
                        x = rng[0] ? $signed({1'b0, amp}) : -$signed({1'b0, amp});
                    end
                    cnt <= cn; rpt <= rp; rng <= rg;
                    if (di) begin
                        ram = r[AM] + r[IA];
                        rpr = r[PR] + r[IP];
                        r[AM] <= ram; r[PR] <= rpr;
                        amp <= {7'd0, ram[4:0]} << ram[7:5];
                        per <= rpr;
                    end
                    if (rp <= 8'sd0)
                        st <= S_TOP;                         // made again with the next parameters
                    else begin
                        s <= 16'(x);
                        j <= 3'd0; h <= 1'b0;
                        st <= S_MAC;
                    end
                end
                S_MAC: begin
                    s <= s_mac;
                    if (!mac_b) begin
                        z1[j] <= z0[j];
                        z0[j] <= $signed(s_mac);
                    end
                    h <= !h;
                    if (h) begin
                        if (j == 3'd5) begin
                            sample <= s_mac;
                            done <= 1'b1;
                            busy <= 1'b0;
                            st <= S_IDLE;
                        end else
                            j <= j + 3'd1;
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
                5'd6, 5'd7, 5'd8, 5'd9:
                    for (int k = 0; k < 4; k++) ss_rdata[8 * k +: 8] = r[4 * (int'(ss_w) - 6) + k];
                5'd10, 5'd11, 5'd12:
                    for (int k = 0; k < 4; k++) ss_rdata[8 * k +: 8] = dec[4 * (int'(ss_w) - 10) + k];
                5'd19: ss_rdata = {16'd0, sample};
                default: if (ss_w >= 5'd13 && ss_w <= 5'd18)
                    ss_rdata = {z1[3'(ss_w - 5'd13)], z0[3'(ss_w - 5'd13)]};
            endcase
    end

endmodule

`default_nettype wire
