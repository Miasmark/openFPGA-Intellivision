// Intellivision core: the ECS cassette as a file (docs/ECS_NOTES.md 6; the golden model is
// tools/ecs_tape.py, whose docstring has the rules). The ECS's UART at $00E0-$00E3, its tape side
// as the ECS ROM's tape engine uses it, over a 16,384-byte tape in block RAM (intv_tape_store)
// that the Pocket keeps as GAME.ecs (data slot 0x107, intv_tape_nv on port B, from intv_core):
//
//   $E0 read   $0002 | a byte under the head (playing, head < the tape's end)
//   $E1 read   the byte under the head ($00xx); playing, the head moves on one
//   $E1 write  recording: the save's next byte
//   $E2 write  the mode: bit 4 the motor, bit 5 record
//
// The byte under the head is read ahead into hb (the CPU's read is combinational), again after
// every head move and every store write. Port A belongs to one engine (the state machine below):
//   CLEAR   all zeros (a load without a tape file, the menu's Erase ECS tape)
//   END     find the tape's end (whole blocks from 0) into tlen, zero the rest (after a load with
//           a tape file, a save, a stopped save)
//   FLOOR   record starts: where the save goes in (rins): the last block start at or before the
//           head (0 after a rewind; right after the previous block when a game writes one save
//           as several blocks back to back, as Game Factory does)
//   INSERT  a save's length is known: the tape from rins moves up by the block's length (from
//           the top down, what passes the end is lost), then its sync, $00 and length are written
//           at rins
//   COMMIT  record has stopped with every byte in: the head goes after the new block; if its
//           first 4 data bytes are an ECS BASIC name, another block with that name is removed
//           (the tape above it moves down, the top is zeroed); END
//   ABORT   record stopped short (or a reset or a state load during a save): the tape from rins
//           moves back down by the block's length, the top is zeroed; END
// A move is 3 clocks a byte (at most 16,384 bytes: 1.2 ms), so the engine is done long before
// the ECS ROM's next tape access (one a frame at most; the save's data bytes queue behind an
// INSERT in a 16-byte FIFO: at Tape speed Instant the ROM writes one every few hundred CPU cycles,
// faster than a move; the FIFO holds what one move lets in). The rewind: the head goes to 0 at a machine reset and when the motor starts
// after IDLE CPU cycles (1 s) or more with it off (offc counts them).
//
// Tape speed Instant (1.0.6; tools/intv_system.py _tape_patch is the model): the ECS ROM's tape
// routine ($7E70) is called once a frame while $015E bit 3 is set (by the ECS interrupt handler for
// ECS BASIC, by the game's own code for Game Factory and WSMLB) and moves one byte a call. With
// Instant, the opcode fetch that returns from such a call (the first fetch outside the routine,
// $7E1C-$7F77 and its helper $70B0-$70B9, after the fetch of $7E70) reads as B to the 3-word JSR
// just before it (ovr: $0220, then $0004 for the next read, for intv_bus) while the transfer is busy
// (busy_cp: bit 3 of the CPU's last write to $015E), the tape ready (more: recording, or playing
// with a byte under the head) and the frame's cycle (slot, at that fetch's DTB) below LIMIT: the
// routine is called again at once, up to about 40-60 bytes a frame, and every byte, timer, control
// word, flag and error path is the ROM's own. LIMIT keeps the caller inside its frame (a loop
// across the next frame's interrupt let it nest into the routine).
//
// Save state (SS_ID, 2 words): [0] head (14:0), mode (23:16); [1] the motor-off count (19:0, all
// ones: off since the reset), [20] inside a call of the routine, [21] the loop's branch answered
// (its displacement next), [22] the $015E bit 3 copy, [26:23] an opcode fetch between its BAR and
// DTB (pending; $7E70; inside the routine; a return from it). A load of word 0 abandons a save in progress (ABORT). The tape
// itself is not in the state.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_tape #(
    parameter logic [7:0] SS_ID = 8'h22,
    parameter int         IDLE  = 896040,       // 60 frames of 14,934 CPU cycles
    parameter int         CPL   = 57,           // CPU cycles a line (intv_bus's slot)
    parameter int         LIMIT = 12934         // Instant: the loop's last frame cycle + 1 (FRAME - 2000)
) (
    input  wire logic        clk,
    input  wire logic        mreset,
    input  wire logic        ce,                // CPU cycle enable
    input  wire logic        on,                // the ECS answers (mode on or attached)

    // CPU bus (intv_bus): $00E0-$00E3
    input  wire logic [15:0] a,
    input  wire logic        rd,                // ce of a read phase
    input  wire logic        wr,                // ce of DW
    input  wire logic        fetch,             // ce: an opcode fetch's BAR (its address on wdata)
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [8:0]  hcnt,              // the machine's position (intv_bus's slot)
    /* verilator lint_on UNUSEDSIGNAL */
    input  wire logic [8:0]  vcnt,
    input  wire logic        instant,           // Tape speed: Instant
    input  wire logic        rom_ok,            // the ECS ROM answers at $7000 (on, latch $7 = 0)
    output logic             ovr_hit,           // intv_bus: din is ovr_q (the loop's branch)
    output logic [15:0]      ovr_q,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [15:0] wdata,           // the low byte
    /* verilator lint_on UNUSEDSIGNAL */
    output logic [15:0]      q,

    // intv_core: the media
    input  wire logic        clr,               // pulse: blank the tape
    input  wire logic        walk,              // pulse: a tape file came in: find its end
    output logic             busy,

    // the nonvolatile slot (intv_tape_nv): the store's port B
    input  wire logic [13:0] nv_addr,
    input  wire logic        nv_we,
    input  wire logic [7:0]  nv_wdata,
    output logic [7:0]       nv_q,

    input  wire logic [15:0] ss_addr,
    input  wire logic        ss_we,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [31:0] ss_wdata,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic [31:0]      ss_rdata
);

    localparam logic [14:0] TSIZE = 15'd16384;

    // ------------------------------------------------------------ the store
    logic [13:0] a_addr = 14'd0;
    logic        a_we = 1'b0;
    logic [7:0]  a_d = 8'd0, a_q;
    intv_tape_store ram (
        .clk, .a_addr, .a_we, .a_d, .a_q, .b_addr(nv_addr), .b_we(nv_we), .b_d(nv_wdata), .b_q(nv_q));

    // ------------------------------------------------------------ state
    logic [14:0] head = 15'd0, tlen = 15'd0;
    logic [7:0]  mode = 8'd0;
    logic [19:0] offc = 20'hFFFFF;
    logic [7:0]  hb = 8'd0;
    logic        hb_ok = 1'b0;

    // a save in progress
    typedef enum logic [2:0] {R_NONE, R_SYNC, R_LO, R_HI, R_DATA, R_SKIP} rph_t;
    rph_t        rph = R_NONE;
    logic [14:0] rk = 15'd0;                    // sync bytes
    logic [7:0]  rlo = 8'd0, rhi = 8'd0;
    logic [15:0] rn = 16'd0, rgot = 16'd0;
    logic [14:0] rlen = 15'd0;                  // the block's length (<= 16,384)
    logic [31:0] rname = 32'd0;                 // the first 4 data bytes, byte 0 in 31:24
    logic [14:0] rins = 15'd0;                  // where the save goes in

    wire logic motor   = mode[4];
    wire logic playing = mode[4] && !mode[5];
    wire logic recording = mode[4] && mode[5];

    // ------------------------------------------------------------ the CPU
    wire logic sel  = on && a[15:2] == 14'h0038;
    wire logic dr   = playing && head < tlen && hb_ok && !busy;
    always_comb begin
        q = 16'h0000;
        if (a[1:0] == 2'd0) q = {14'd0, 1'b1, dr};
        else if (a[1:0] == 2'd1) q = {8'h00, head[14] ? 8'h00 : hb};
    end

    wire logic ss_hit0 = ss_addr == {SS_ID, 8'd0};
    wire logic ss_hit1 = ss_addr == {SS_ID, 8'd1};

    // ------------------------------------------------------------ Tape speed Instant
    logic        fpend = 1'b0;                  // an opcode fetch's BAR seen, its DTB not yet
    logic        f_ret = 1'b0, f_rtn = 1'b0;    // that fetch: a return from the routine; inside it
    logic        f_ent = 1'b0;                  // that fetch is $7E70
    logic        step = 1'b0, opnd = 1'b0, busy_cp = 1'b0;
    wire  logic [15:0] slot = 16'(vcnt) * 16'(CPL) + 16'(hcnt[8:2]);
    wire  logic  more = recording || (playing && head < tlen);
    wire  logic  in_rtn = (wdata >= 16'h7E1C && wdata <= 16'h7F77) || (wdata >= 16'h70B0 && wdata <= 16'h70B9);
    wire  logic  pt_now = f_ret && instant && rom_ok && busy_cp && more && slot < 16'(LIMIT);
    always_comb begin
        ovr_hit = 1'b0;
        ovr_q = 16'h0220;                       // B (back) to the JSR: $0220, $0004
        if (fpend && pt_now) ovr_hit = 1'b1;
        else if (opnd && !fpend) begin ovr_hit = 1'b1; ovr_q = 16'h0004; end
    end
    assign ss_rdata = ss_hit0 ? {8'd0, mode, 1'b0, head}
                    : ss_hit1 ? {5'd0, fpend, f_ent, f_rtn, f_ret, busy_cp, opnd, step, offc} : 32'd0;

    // ------------------------------------------------------------ the engine
    typedef enum logic [5:0] {
        E_IDLE, E_PF1, E_PF2,
        E_MV_RD, E_MV_W1, E_MV_W2,              // a move
        E_ZERO,                                 // zeros from zp to the top
        E_HDR,                                  // INSERT: the header at rins
        E_DATA,                                 // a queued data byte
        E_W_START, E_W_RD, E_W_K1, E_W_K2, E_W_L1, E_W_L2, E_W_H0, E_W_H1, E_W_H2,
        E_W_N0, E_W_N1, E_W_N2,                 // a walk: blocks from wo; the name compare
        E_DEL                                   // the matching block found: remove it
    } est_t;
    est_t        st = E_IDLE;
    typedef enum logic [2:0] {J_IDLE, J_HDR, J_ZEND, J_END, J_ABORTZ, J_DELZ} jret_t;
    jret_t       mret = J_IDLE;                 // after a move
    jret_t       zret = J_IDLE;                 // after a zero run
    logic [13:0] ms = 14'd0, md = 14'd0;        // move source, destination
    logic [14:0] mc = 15'd0;                    // bytes left to move
    logic        mup = 1'b0;                    // moving up: from the top down
    logic [14:0] zp = 15'd0;
    logic [14:0] wo = 15'd0, wk = 15'd0;        // walk: the block's offset, its sync count
    logic [16:0] wbl = 17'd0;                   // its length
    logic [15:0] wn = 16'd0;
    typedef enum logic [1:0] {W_END, W_SEARCH, W_FLOOR} wm_t;
    wm_t         wm = W_END;                    // the walk's job: END, a COMMIT's name search, FLOOR
    logic [1:0]  wj = 2'd0;
    logic [14:0] hj = 15'd0;                    // the header's byte
    logic [13:0] pf_a = 14'd0;
    // the save's data bytes wait here for port A (behind an INSERT): a 16-byte FIFO; dn counts
    // the bytes written to the tape
    logic [7:0]  fq [16];
    logic [3:0]  fw = 4'd0, fr = 4'd0;
    logic [4:0]  fc = 5'd0;                     // bytes in the FIFO
    logic [15:0] dn = 16'd0;
    wire  logic  pend = fc != 5'd0;
    // requests (taken by E_IDLE)
    logic        q_clr = 1'b0, q_walk = 1'b0, q_ins = 1'b0, q_com = 1'b0, q_abt = 1'b0, q_flr = 1'b0;
    assign busy = st != E_IDLE && st != E_PF1 && st != E_PF2;

    function automatic logic [15:0] neg16(input logic [7:0] lo, input logic [7:0] hi);
        return 16'(-{hi, lo});
    endfunction
    // an ECS BASIC name (ecs_tape.basic_name): the first character a letter or a digit, all four
    // $20-$5A; a game's data (Game Factory's 00 00 00 00, `;`;) never is one
    function automatic logic basic_name(input logic [31:0] nm);
        logic ok;
        ok = (nm[31:24] >= 8'h41 && nm[31:24] <= 8'h5A) || (nm[31:24] >= 8'h30 && nm[31:24] <= 8'h39);
        for (int j = 0; j < 4; j++)
            ok = ok && nm[8 * j +: 8] >= 8'h20 && nm[8 * j +: 8] <= 8'h5A;
        return ok;
    endfunction

    // the walk's block end: wo + wk + 3 + wn (17 bits: may pass the tape)
    wire logic [17:0] w_end = 18'(wo) + 18'(wk) + 18'd3 + 18'(wn);

    // the head moves (or is set) in this clock: a read ahead in flight is stale
    wire logic head_chg = mreset || (ss_we && ss_hit0) || clr
                       || (rd && sel && a[1:0] == 2'd1 && playing && head < tlen)
                       || (wr && sel && a[1:0] == 2'd2 && wdata[4] && !motor);

    always_ff @(posedge clk) begin
        logic f_push, f_pop, f_clr;                // the FIFO's moves this clock
        f_push = 1'b0; f_pop = 1'b0; f_clr = 1'b0;
        a_we <= 1'b0;
        if (a_we || nv_we) hb_ok <= 1'b0;

        // -------------------------------------------- the CPU side
        if (mreset) begin
            head <= 15'd0;
            mode <= 8'd0;
            offc <= 20'hFFFFF;
            hb_ok <= 1'b0;
            if (rph == R_DATA) q_abt <= 1'b1;   // a reset during a save: taken out
            rph <= R_NONE;
        end else if (ss_we && ss_hit0) begin
            head <= ss_wdata[14:0];
            mode <= ss_wdata[23:16];
            hb_ok <= 1'b0;
            if (rph == R_DATA) q_abt <= 1'b1;   // a state load during a save: taken out
            rph <= R_NONE;
        end else if (ss_we && ss_hit1) begin
            offc <= ss_wdata[19:0];
            {fpend, f_ent, f_rtn, f_ret, busy_cp, opnd, step} <= ss_wdata[26:20];
        end else begin
            if (ce && !motor && offc != 20'hFFFFF) offc <= offc + 20'd1;
            if (fetch) begin                    // an opcode fetch's BAR: its address on wdata
                fpend <= 1'b1;
                f_ret <= step && !in_rtn;
                f_rtn <= in_rtn;
                f_ent <= wdata == 16'h7E70;
            end else if (rd && fpend) begin     // its DTB: the model's fetch read
                fpend <= 1'b0;
                opnd  <= pt_now;
                step  <= f_ent || (f_rtn && step);
            end else if (rd && opnd)            // the branch's displacement
                opnd <= 1'b0;
            if (wr && a == 16'h015E) busy_cp <= wdata[3];
            if (rd && sel && a[1:0] == 2'd1 && playing && head < tlen) begin
                head <= head + 15'd1;
                hb_ok <= 1'b0;
            end
            if (wr && sel && a[1:0] == 2'd1 && recording) begin
                case (rph)
                    R_SYNC: if (wdata[7:0] == 8'hAA) rk <= rk == 15'h7FFF ? rk : rk + 15'd1;
                            else if (wdata[7:0] == 8'h00 && rk != 15'd0) rph <= R_LO;
                            else rk <= 15'd0;
                    R_LO:   begin rlo <= wdata[7:0]; rph <= R_HI; end
                    R_HI:   begin
                        rhi <= wdata[7:0];
                        rn  <= neg16(rlo, wdata[7:0]);
                        if (17'(rins) + 17'(rk) + 17'd3 + 17'(neg16(rlo, wdata[7:0])) > 17'(TSIZE))
                            rph <= R_SKIP;              // does not fit from rins: not recorded
                        else begin
                            rlen  <= 15'(17'(rk) + 17'd3 + 17'(neg16(rlo, wdata[7:0])));
                            q_ins <= 1'b1;
                            rph   <= R_DATA;
                        end
                    end
                    R_DATA: if (rgot < rn) begin
                        f_push = 1'b1;
                        if (rgot < 16'd4) rname[8 * (3 - 32'(rgot[1:0])) +: 8] <= wdata[7:0];
                        rgot <= rgot + 16'd1;
                    end
                    default: ;
                endcase
            end
            if (wr && sel && a[1:0] == 2'd2) begin
                mode <= wdata[7:0];
                if (wdata[4] && !motor) begin          // the motor starts
                    if (offc >= 20'(IDLE)) begin head <= 15'd0; hb_ok <= 1'b0; end
                    offc <= 20'd0;
                end
                if (!wdata[4] && motor) offc <= 20'd1;  // the motor stops (this cycle counts: the model's cycle - off_at)
                if (recording && !(wdata[4] && wdata[5])) begin   // record ends
                    if (rph == R_DATA) begin
                        if (rgot == rn) q_com <= 1'b1;
                        else q_abt <= 1'b1;
                    end
                    rph <= R_NONE;
                end
                if (wdata[4] && wdata[5] && !recording) begin     // record starts
                    rph <= R_SYNC; rk <= 15'd0; rgot <= 16'd0; rname <= 32'd0; dn <= 16'd0;
                    q_flr <= 1'b1;
                end
            end
            if (clr) begin head <= 15'd0; hb_ok <= 1'b0; end       // the tape blanked: rewound
        end
        if (clr)  q_clr  <= 1'b1;
        if (walk) q_walk <= 1'b1;

        // -------------------------------------------- the engine (port A)
        case (st)
            E_IDLE: begin
                if (q_clr) begin
                    q_clr <= 1'b0; q_walk <= 1'b0;
                    zp <= 15'd0; zret <= J_IDLE; tlen <= 15'd0;
                    st <= E_ZERO;
                end else if (q_walk) begin
                    q_walk <= 1'b0;
                    wo <= 15'd0; wm <= W_END; st <= E_W_START;
                end else if (q_flr) begin
                    q_flr <= 1'b0;
                    wo <= 15'd0; wm <= W_FLOOR; st <= E_W_START;
                end else if (q_ins) begin
                    q_ins <= 1'b0;
                    // up by rlen from rins, from the top down: t[i + rlen] = t[i]
                    ms <= 14'(TSIZE - rlen - 15'd1); md <= 14'h3FFF; mc <= TSIZE - rlen - rins; mup <= 1'b1;
                    mret <= J_HDR; hj <= 15'd0;
                    st <= TSIZE == rins + rlen ? E_HDR : E_MV_RD;
                end else if (pend) begin                // a data byte before an end of the save
                    st <= E_DATA;
                end else if (q_abt) begin
                    q_abt <= 1'b0; f_clr = 1'b1;
                    // down by rlen from rins: t[i] = t[i + rlen], then zeros from the top's rlen
                    ms <= 14'(rins + rlen); md <= 14'(rins); mc <= TSIZE - rins - rlen; mup <= 1'b0;
                    mret <= J_ABORTZ;
                    st <= TSIZE == rins + rlen ? E_ZERO : E_MV_RD;
                    zp <= TSIZE - rlen; zret <= J_END;
                end else if (q_com) begin
                    q_com <= 1'b0;
                    head <= rins + rlen; hb_ok <= 1'b0;     // the head after the new block
                    // a BASIC name: the search over every other block, else straight to END
                    wo <= 15'd0;
                    wm <= rn >= 16'd4 && basic_name(rname) ? W_SEARCH : W_END;
                    st <= E_W_START;
                end else if (!hb_ok && !head[14]) begin
                    a_addr <= head[13:0]; pf_a <= head[13:0];
                    st <= E_PF1;
                end
            end
            E_PF1: st <= E_PF2;
            E_PF2: begin
                if (pf_a == head[13:0] && !head[14] && !a_we && !nv_we && !head_chg) begin hb <= a_q; hb_ok <= 1'b1; end
                st <= E_IDLE;
            end
            E_DATA: begin
                f_pop = 1'b1;
                a_addr <= 14'(17'(rins) + 17'(rk) + 17'd3 + 17'(dn)); a_d <= fq[fr]; a_we <= 1'b1;
                dn <= dn + 16'd1;
                st <= E_IDLE;
            end

            // ---------------- a move (3 clocks a byte)
            E_MV_RD: begin a_addr <= ms; st <= E_MV_W1; end
            E_MV_W1: st <= E_MV_W2;
            E_MV_W2: begin
                a_addr <= md; a_d <= a_q; a_we <= 1'b1;
                ms <= mup ? ms - 14'd1 : ms + 14'd1;
                md <= mup ? md - 14'd1 : md + 14'd1;
                mc <= mc - 15'd1;
                if (mc == 15'd1)
                    case (mret)
                        J_HDR:    st <= E_HDR;
                        J_ABORTZ: st <= E_ZERO;
                        J_DELZ:   st <= E_ZERO;
                        default:  st <= E_IDLE;
                    endcase
                else st <= E_MV_RD;
            end

            // ---------------- zeros from zp to the top
            E_ZERO: begin
                a_addr <= zp[13:0]; a_d <= 8'd0; a_we <= !zp[14];
                if (zp[14] || zp == TSIZE - 15'd1) begin
                    if (zret == J_END) begin wo <= 15'd0; wm <= W_END; st <= E_W_START; end
                    else st <= E_IDLE;
                end else zp <= zp + 15'd1;
            end

            // ---------------- INSERT's header: sync x rk, $00, lo, hi
            E_HDR: begin
                a_addr <= 14'(rins + hj); a_we <= 1'b1;
                a_d <= hj < rk ? 8'hAA : hj == rk ? 8'h00 : hj == rk + 15'd1 ? rlo : rhi;
                if (hj == rk + 15'd2) st <= E_IDLE;
                else hj <= hj + 15'd1;
            end

            // ---------------- a walk: the block at wo
            E_W_START: begin wk <= 15'd0; st <= E_W_RD; end
            E_W_RD: if (16'(wo) + 16'(wk) >= 16'(TSIZE)) st <= E_W_K2;      // sync to the top: no block
                    else begin a_addr <= 14'(wo + wk); st <= E_W_K1; end
            E_W_K1: st <= E_W_K2;
            E_W_K2: begin
                if (16'(wo) + 16'(wk) < 16'(TSIZE) && a_q == 8'hAA) begin
                    wk <= wk + 15'd1; st <= E_W_RD;
                end else if (wk == 15'd0 || 16'(wo) + 16'(wk) + 16'd3 > 16'(TSIZE) || a_q != 8'h00)
                    st <= E_W_H0;                                       // no block here: the end
                else begin a_addr <= 14'(wo + wk + 15'd1); st <= E_W_L1; end
            end
            E_W_L1: st <= E_W_L2;
            E_W_L2: begin wn[7:0] <= a_q; a_addr <= 14'(wo + wk + 15'd2); st <= E_W_H1; end
            E_W_H1: st <= E_W_H2;
            E_W_H2: begin
                wn <= neg16(wn[7:0], a_q);
                st <= E_W_N0;
            end
            E_W_N0: begin
                // the block's end; wn is its data length
                wbl <= 17'(w_end - 18'(wo));
                if (w_end > 18'(TSIZE)) st <= E_W_H0;                   // cut at the top: the end
                else if (wm == W_FLOOR && w_end > 18'(head)) st <= E_W_H0;  // the block past the head
                else if (wm == W_SEARCH && wn >= 16'd4 && wo != rins) begin
                    wj <= 2'd0; a_addr <= 14'(wo + wk + 15'd3); st <= E_W_N1;
                end else begin wo <= 15'(w_end); st <= E_W_START; end
            end
            E_W_N1: st <= E_W_N2;
            E_W_N2: begin
                if (a_q != rname[8 * (3 - 32'(wj)) +: 8]) begin wo <= 15'(w_end); st <= E_W_START; end
                else if (wj == 2'd3) st <= E_DEL;
                else begin wj <= wj + 2'd1; a_addr <= 14'(wo + wk + 15'd4 + 15'(wj)); st <= E_W_N1; end
            end
            // the walk ends at wo: a search found nothing (END next), or END is done
            E_W_H0: begin
                if (wm == W_SEARCH) begin wo <= 15'd0; wm <= W_END; st <= E_W_START; end
                else if (wm == W_FLOOR) begin rins <= wo; st <= E_IDLE; end
                else begin tlen <= wo; zp <= wo; zret <= J_IDLE; st <= E_ZERO; end
            end
            // remove the block at wo (wbl bytes): down by wbl, zeros at the top, then END
            E_DEL: begin
                ms <= 14'(17'(wo) + wbl); md <= 14'(wo); mc <= 15'(17'(TSIZE) - 17'(wo) - wbl); mup <= 1'b0;
                mret <= J_DELZ; zp <= 15'(17'(TSIZE) - wbl); zret <= J_END;
                if (wo < rins) begin                    // the old copy was before the new block
                    rins <= 15'(17'(rins) - wbl);
                    head <= 15'(17'(rins) - wbl + 17'(rlen));
                end
                st <= 17'(wo) + wbl == 17'(TSIZE) ? E_ZERO : E_MV_RD;
            end
            default: st <= E_IDLE;
        endcase

        // the FIFO
        if (f_clr) begin
            fw <= 4'd0; fr <= 4'd0; fc <= 5'd0;
        end else begin
            if (f_push) begin fq[fw] <= wdata[7:0]; fw <= fw + 4'd1; end
            if (f_pop) fr <= fr + 4'd1;
            fc <= fc + 5'(f_push) - 5'(f_pop);
        end
    end

endmodule

`default_nettype wire
