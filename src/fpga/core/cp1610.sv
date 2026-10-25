// Intellivision core: the CP1610 CPU (DESIGN.md 2.5, module 3).
//
// Written from the documents and our Python model (tools/cp1610.py), which
// it follows cycle by cycle; every behaviour and every choice where the
// sources disagree is in docs/CPU_NOTES.md:
//   S1   GI CP-1600 Microprocessor Users Manual, May 1975: pins p.12-14,
//        state flow p.21-25, timing diagrams p.27-37 (interrupt sequence
//        p.35), formats p.44-52, instruction set and cycles p.53-58.
//   wiki wiki.intellivision.us CP1610, Bus_Phases, Double_Byte_Data and the
//        opcode pages.
// MAME's cp1610.cpp (BSD-3) was read only to cross-check facts; no code.
//
// Bus. One bus phase per CPU cycle; ce is the CPU cycle enable (clk_sys / 48
// in the core). No tristate (DESIGN.md 2.5): the phase code, a 16-bit
// data-out and a combined data-in. phase is {BDIR, BC2, BC1}:
//   NACT 000  ADAR 001  IAB 010  DTB 011  BAR 100  DW 101  DWS 110  INTAK 111
// (DESIGN.md 2.5; S1 p.12 names the pins BDIR, BC1, BC2: keep the order in
// mind when wiring real pin names). phase and dout come from flip-flops only
// and are valid for the whole cycle; din is sampled at the ce that ends a
// DTB, ADAR or IAB cycle. dout carries the address in BAR and INTAK (the
// stack pointer) and the data in DW and DWS; it is 0 in the other phases.
// Devices latch the address in BAR and INTAK from dout, and in ADAR from
// the bus, which is din then (the word the device itself returns).
// Sequences (wiki Bus_Phases; S1 p.29-35):
//   fetch, indirect or immediate read  BAR NACT DTB NACT
//   write                              BAR NACT DW DWS NACT
//   direct read                        BAR NACT ADAR NACT DTB NACT
//   direct write                       BAR NACT ADAR NACT DW DWS NACT
//   SDBD read                          BAR NACT DTB BAR NACT DTB
//   interrupt                          INTAK NACT DW DWS NACT IAB NACT NACT NACT
// After reset the CPU gives one IAB cycle and loads the PC from din (S1
// p.21; the Intellivision's EXEC answers $1000), then fetches. The model
// does not count that cycle: its cycle 0 is the first fetch's BAR.
//
// Request lines (active high here; the pins INTRM*, INTR*, BUSRQ*, BUSAK*
// are active low). They are sampled at the ce that ends the last cycle of
// an instruction, of a bus-request wait cycle, never elsewhere; the model's
// "line at cycle c" is the value sampled at the ce that starts cycle c.
// INTRM and INTR are edge requests: a rising edge of the (active-high)
// line sets a request, a low line clears it (wiki CP1610 Signal Pins).
// After an interruptible instruction: BUSRQ first (busak and NACT for as
// long as busrq stays high), then INTR, then INTRM if I is set (S1
// p.24-25). INTR is taken before INTRM and clears only its own request.
// No check between the interrupt sequence and the handler's first
// instruction. The interrupt vector comes from din in the IAB cycle.
//
// Choices taken from the model (docs/CPU_NOTES.md "Where the sources
// disagree"): 9-cycle interrupt; SIN interruptible; SETC 4 cycles; SARC
// Rr,2 8 cycles; NEGR 0 sets C; SWAP Rr,2 copies the low byte to both
// halves; branch not taken 7 cycles (no trailing NACT); the 3 extra cycles
// of a stack read before the read; SDBD with direct mode or before MVO
// ignored; jump with II=11 jumps with I unchanged; MVO@ with the pointer as
// source writes the old value. Two options are inputs (tie them in the
// core; the bench runs both ways):
//   cfg_hlt_imm       0: HLT halts after the next instruction (S1 p.56)
//                     1: HLT halts at once (wiki HLT)
//   cfg_sdbd_r6_mame  0: SDBD + R6 reads the word under R6 twice, one
//                        decrement, 10 cycles (wiki Undocumented_SDBD_Behavior)
//                     1: two decrements, two words, 13 cycles (MAME)
// A halted CPU gives NACT until reset (nothing in the core resumes it).
// TCI pulses in the fetch's last cycle (model: cycle + 3); the SIN pulse
// (pcit) comes in the first cycle after the fetch (model hook: cycle + 2,
// inside the fetch, where the opcode is not yet known). EBCA is ir[3:0];
// EBCI is sampled at the end of the fetch of a BEXT.
//
// Save state (DESIGN.md 4.3, 4.4): eight 32-bit words, every flip-flop that
// changes at run time, so a save in any cycle, also mid-instruction or in
// the interrupt sequence, restores exactly (sim/tb/tb_cpu.sv checks it).
// ss_rdata is 0 unless this module is addressed, so ports OR-combine. The
// caller writes only while ce is low. reset beats a state write, which
// beats ce.
//   word 0 {R1, R0}   word 1 {R3, R2}   word 2 {R5, R4}   word 3 {R7, R6}
//   word 4 {tmp, ea}  (data and address of the sequence in progress)
//   word 5 [9:0] ir, [17:10] lo (SDBD low byte), [22:18] st (cycle state),
//          [24:23] cnt (idle cycles left - 1), [25] jpt (jump word 3),
//          [26] dbd (this instruction follows SDBD), [27] hnow (halt after
//          this instruction), [28] taken (branch)
//   word 6 [3:0] S Z O C, [4] I, [5] D, [6] reserved (reads 0; whether
//          the instruction ending may be interrupted is decided in its
//          last cycle and needs no flip-flop), [7] intrm request, [8] intrm line last sample,
//          [9] intr request, [10] intr line last sample, [11] halt
//          pending, [12] halted
//   word 7 reads 0 (reserved)
// A word 5 whose st field is not a state (31) leaves the CPU halted.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module cp1610 #(
    parameter logic [7:0] SS_ID = 8'h02     // save-state module id
) (
    input  wire logic        clk,
    input  wire logic        reset,          // synchronous
    input  wire logic        ce,             // one CPU cycle (microcycle)
    input  wire logic        cfg_hlt_imm,
    input  wire logic        cfg_sdbd_r6_mame,

    output logic [2:0]       phase,          // {BDIR, BC2, BC1}
    output logic [15:0]      dout,
    input  wire logic [15:0] din,

    input  wire logic        intrm,          // 1 = INTRM* low
    input  wire logic        intr,           // 1 = INTR* low
    input  wire logic        busrq,          // 1 = BUSRQ* low
    output logic             busak,          // 1 = BUSAK* low
    output logic [3:0]       ebca,
    input  wire logic        ebci,
    output logic             tci,
    output logic             pcit,           // SIN pulse
    output logic             halted,
    output logic             fetch,          // this cycle is an opcode fetch's BAR

    input  wire logic [15:0] ss_addr,        // [15:8] module id, [7:0] word
    input  wire logic        ss_we,
    input  wire logic [31:0] ss_wdata,
    output logic [31:0]      ss_rdata
);

    localparam logic [2:0] PH_NACT = 3'd0, PH_ADAR = 3'd1, PH_IAB = 3'd2,
                           PH_DTB = 3'd3, PH_BAR = 3'd4, PH_DW = 3'd5,
                           PH_DWS = 3'd6, PH_INTAK = 3'd7;

    typedef enum logic [4:0] {
        S_RST,                                  // IAB: reset vector
        S_FBAR, S_FNACT, S_FDTB, S_FNACT2,      // opcode fetch
        S_RBAR, S_RNACT, S_RDTB, S_RNACT2,      // operand read
        S_R2BAR, S_R2NACT, S_R2DTB,             // SDBD second read
        S_WBAR, S_WNACT, S_WDW, S_WDWS, S_WNACT2, // write
        S_ABAR, S_ANACT, S_AADAR, S_ANACT2,     // direct address
        S_IDLE,                                 // NACT, cnt more after this
        S_IINTAK, S_INACT1, S_IDW, S_IDWS, S_INACT2, S_IIAB, S_INACT3, // interrupt
        S_BUSAK,                                // bus request wait
        S_HALT
    } st_t;

    // ---------------------------------------------------------------- state
    logic [15:0] r [0:7];
    logic        fS, fZ, fO, fC, fI, fD;
    logic        intrm_req, intrm_prev, intr_req, intr_prev;
    logic        hpend, hlt;
    st_t         st;
    logic [1:0]  cnt;
    logic [9:0]  ir;
    logic [7:0]  lo;
    logic [15:0] ea, tmp;
    logic        jpt, dbd, hnow, taken;

    // next values
    logic [15:0] r_n [0:7];
    logic        fS_n, fZ_n, fO_n, fC_n, fI_n, fD_n;
    logic        intok_n;                // the instruction ending is interruptible
    logic        intrm_req_n, intrm_prev_n, intr_req_n, intr_prev_n;
    logic        hpend_n, hlt_n;
    st_t         st_n;
    logic [1:0]  cnt_n;
    logic [9:0]  ir_n;
    logic [7:0]  lo_n;
    logic [15:0] ea_n, tmp_n;
    logic        jpt_n, dbd_n, hnow_n, taken_n;

    // ------------------------------------------------------------- decode
    wire logic [2:0] f_o  = ir[8:6];          // ext/regreg operation
    wire logic [2:0] f_m  = ir[5:3];          // ext mode, regreg source, single op
    wire logic [2:0] f_r  = ir[2:0];
    wire logic cls_jump   = ir == 10'h004;
    wire logic cls_impl   = ir[9:3] == 7'd0 && !cls_jump;
    wire logic cls_single = ir[9:6] == 4'd0 && ir[5:3] != 3'd0;
    wire logic cls_shift  = ir[9:6] == 4'd1;
    wire logic cls_regreg = !ir[9] && ir[8:7] != 2'd0;
    wire logic cls_branch = ir[9:6] == 4'b1000;
    wire logic cls_ext    = ir[9] && ir[8:6] != 3'd0;
    wire logic cls_mvo    = cls_ext && ir[8:6] == 3'd1;
    wire logic cls_rd     = cls_ext && ir[8:6] != 3'd1;
    wire logic dbl        = cls_rd && dbd && f_m != 3'd0;   // SDBD read (two locations)

    // ---------------------------------------------------------- bus outputs
    always_comb begin
        phase = PH_NACT;
        dout  = 16'd0;
        unique case (st)
            S_RST:                       phase = PH_IAB;
            S_FBAR:                begin phase = PH_BAR; dout = r[7]; end
            S_RBAR, S_R2BAR, S_WBAR, S_ABAR:
                                   begin phase = PH_BAR; dout = ea; end
            S_FDTB, S_RDTB, S_R2DTB:     phase = PH_DTB;
            S_AADAR:                     phase = PH_ADAR;
            S_WDW:                 begin phase = PH_DW;  dout = tmp; end
            S_WDWS:                begin phase = PH_DWS; dout = tmp; end
            S_IINTAK:              begin phase = PH_INTAK; dout = r[6]; end
            S_IDW:                 begin phase = PH_DW;  dout = r[7]; end
            S_IDWS:                begin phase = PH_DWS; dout = r[7]; end
            S_IIAB:                      phase = PH_IAB;
            default:                     phase = PH_NACT;
        endcase
    end
    assign busak  = st == S_BUSAK;
    assign halted = hlt;
    assign fetch  = st == S_FBAR;
    assign ebca   = ir[3:0];
    assign tci    = st == S_FNACT2 && ir == 10'h005;
    assign pcit   = st == S_IDLE && cnt == 2'd1 && cls_single && f_m == 3'd6 && f_r[2:1] == 2'b11;

    // ------------------------------------------------------------------ ALU
    // a + b + cin with C = carry out and O = two's complement overflow
    // (S1 p.45); subtraction is a + ~b + 1.
    function automatic logic [17:0] add16(input logic [15:0] a, input logic [15:0] b,
                                          input logic cin);
        logic [16:0] s;
        logic        ov;
        s  = {1'b0, a} + {1'b0, b} + {16'd0, cin};
        ov = (a[15] ^ s[15]) & (b[15] ^ s[15]);
        return {s[16], ov, s[15:0]};          // {C, O, result}
    endfunction

    // SDBD read data: low bytes of the two words, low first (S1 p.49)
    wire logic [15:0] opnd = st == S_R2DTB ? {din[7:0], lo} : tmp;

    // Execute datapath, used in the last cycle of single-register, shift,
    // register-register and read instructions: one adder, one result, one
    // register write (to ridx), flags from the result.
    wire logic [2:0]  ridx = cls_shift ? {1'b0, ir[1:0]} : f_r;   // shifts: R0-R3
    wire logic [15:0] ra   = r[ridx];
    wire logic [15:0] rb   = cls_regreg ? r[f_m] : opnd;
    logic [15:0] ax, ay, res;
    logic        acin, x_we, x_sz, x_s7, x_c, x_o, x_nib;
    logic [17:0] sum;
    always_comb begin
        ax = ra; ay = 16'd0; acin = 1'b0;
        if (cls_single) begin
            unique case (f_m)
                3'd1: acin = 1'b1;                               // INCR
                3'd2: ay = 16'hFFFF;                             // DECR
                3'd4: begin ax = 16'd0; ay = ~ra; acin = 1'b1; end // NEGR
                3'd5: acin = fC;                                 // ADCR
                default: ;
            endcase
        end else if (f_o == 3'd3) begin
            ay = rb;                                             // ADD
        end else begin
            ay = ~rb; acin = 1'b1;                               // SUB, CMP
        end
        sum = add16(ax, ay, acin);

        res = sum[15:0];
        x_we = 1'b0; x_sz = 1'b0; x_s7 = 1'b0; x_c = fC; x_o = fO; x_nib = 1'b0;
        if (cls_single) begin
            unique case (f_m)
                3'd1, 3'd2: begin x_we = 1'b1; x_sz = 1'b1; end  // INCR DECR
                3'd3: begin res = ~ra; x_we = 1'b1; x_sz = 1'b1; end // COMR
                3'd4, 3'd5: begin                                // NEGR ADCR
                    x_we = 1'b1; x_sz = 1'b1; x_c = sum[17]; x_o = sum[16];
                end
                3'd6: begin                                      // GSWD (R0-R3), NOP, SIN
                    res = {fS, fZ, fO, fC, 4'd0, fS, fZ, fO, fC, 4'd0};
                    x_we = !f_r[2];
                end
                default: x_nib = 1'b1;                           // RSWD
            endcase
        end else if (cls_shift) begin
            // S1 p.50, p.53; wiki SWAP .. SARC. Right shifts and SWAP take
            // S from bit 7.
            x_we = 1'b1; x_sz = 1'b1; x_s7 = 1'b1;
            unique case (ir[5:3])
                3'd0: res = ir[2] ? {ra[7:0], ra[7:0]} : {ra[7:0], ra[15:8]};  // SWAP
                3'd1: begin res = ir[2] ? {ra[13:0], 2'b00} : {ra[14:0], 1'b0}; x_s7 = 1'b0; end
                3'd2: begin                                      // RLC
                    res = ir[2] ? {ra[13:0], fC, fO} : {ra[14:0], fC};
                    x_c = ra[15]; if (ir[2]) x_o = ra[14];
                    x_s7 = 1'b0;
                end
                3'd3: begin                                      // SLLC
                    res = ir[2] ? {ra[13:0], 2'b00} : {ra[14:0], 1'b0};
                    x_c = ra[15]; if (ir[2]) x_o = ra[14];
                    x_s7 = 1'b0;
                end
                3'd4: res = ir[2] ? {2'b00, ra[15:2]} : {1'b0, ra[15:1]};          // SLR
                3'd5: res = ir[2] ? {ra[15], ra[15], ra[15:2]} : {ra[15], ra[15:1]}; // SAR
                3'd6: begin                                      // RRC
                    res = ir[2] ? {fO, fC, ra[15:2]} : {fC, ra[15:1]};
                    x_c = ra[0]; if (ir[2]) x_o = ra[1];
                end
                default: begin                                   // SARC
                    res = ir[2] ? {ra[15], ra[15], ra[15:2]} : {ra[15], ra[15:1]};
                    x_c = ra[0]; if (ir[2]) x_o = ra[1];
                end
            endcase
        end else begin                                           // regreg and reads
            x_sz = 1'b1;
            unique case (f_o)
                3'd2: begin                                      // MOVR; MVI keeps the flags
                    res = rb; x_we = 1'b1; x_sz = cls_regreg;
                end
                3'd3, 3'd4: begin x_we = 1'b1; x_c = sum[17]; x_o = sum[16]; end
                3'd5: begin x_c = sum[17]; x_o = sum[16]; end   // CMP
                3'd6: begin res = ra & rb; x_we = 1'b1; end
                default: begin res = ra ^ rb; x_we = 1'b1; end
            endcase
        end
    end

    // address of the second SDBD read
    logic [15:0] ea2;
    always_comb begin
        if (f_m < 3'd4)
            ea2 = ea;                                   // same word twice
        else if (f_m == 3'd6)
            ea2 = cfg_sdbd_r6_mame ? ea - 16'd1 : ea;   // CPU_NOTES row 8
        else
            ea2 = ea + 16'd1;                           // R4, R5, R7
    end

    // branch condition (S1 p.47, p.54)
    logic cond_t;
    always_comb begin
        unique case (ir[2:0])
            3'd0: cond_t = 1'b1;
            3'd1: cond_t = fC;
            3'd2: cond_t = fO;
            3'd3: cond_t = !fS;
            3'd4: cond_t = fZ;
            3'd5: cond_t = fS ^ fO;
            3'd6: cond_t = fZ | (fS ^ fO);
            default: cond_t = fS ^ fC;
        endcase
    end

    // ------------------------------------------------------------ next state
    always_comb begin
        logic        fin, fin_ok;         // the step ends with this cycle
        logic        ex_rd, ex_idle;      // operations done at the end
        logic        hlt_now;
        logic        smp;                 // sample the request lines

        for (int k = 0; k < 8; k++) r_n[k] = r[k];
        fS_n = fS; fZ_n = fZ; fO_n = fO; fC_n = fC; fI_n = fI; fD_n = fD;
        intok_n = 1'b0;
        intrm_req_n = intrm_req; intrm_prev_n = intrm_prev;
        intr_req_n = intr_req; intr_prev_n = intr_prev;
        hpend_n = hpend; hlt_n = hlt;
        st_n = st; cnt_n = cnt; ir_n = ir; lo_n = lo; ea_n = ea; tmp_n = tmp;
        jpt_n = jpt; dbd_n = dbd; hnow_n = hnow; taken_n = taken;
        fin = 1'b0; fin_ok = 1'b0; ex_rd = 1'b0; ex_idle = 1'b0;
        hlt_now = 1'b0; smp = 1'b0;

        unique case (st)
            S_RST: begin
                r_n[7] = din;                   // reset vector (S1 p.21)
                st_n = S_FBAR;
            end
            S_FBAR:  st_n = S_FNACT;
            S_FNACT: st_n = S_FDTB;
            S_FDTB: begin
                ir_n = din[9:0];                // bits 15-10 "future use" (S1 p.46)
                r_n[7] = r[7] + 16'd1;
                dbd_n = fD;                     // D lasts one instruction
                fD_n = 1'b0;
                hnow_n = hpend;                 // HLT before: halt after this one
                st_n = S_FNACT2;
            end
            S_FNACT2: begin                     // decode
                if (cls_impl) begin
                    unique case (ir[2:0])
                        3'd0: if (cfg_hlt_imm) hlt_now = 1'b1; else hpend_n = 1'b1;
                        3'd1: fD_n = 1'b1;      // SDBD
                        3'd2: fI_n = 1'b1;      // EIS
                        3'd3: fI_n = 1'b0;      // DIS
                        3'd6: fC_n = 1'b0;      // CLRC
                        3'd7: fC_n = 1'b1;      // SETC
                        default: ;              // TCI (pulse only)
                    endcase
                    fin = 1'b1;
                end else if (cls_jump) begin
                    ea_n = r[7]; r_n[7] = r[7] + 16'd1; jpt_n = 1'b0;
                    st_n = S_RBAR;
                end else if (cls_single) begin
                    cnt_n = 2'd1; st_n = S_IDLE;
                end else if (cls_shift) begin
                    cnt_n = ir[2] ? 2'd3 : 2'd1; st_n = S_IDLE;
                end else if (cls_regreg) begin  // MOVR to R6/R7: one more (S1 p.53)
                    cnt_n = (f_o == 3'd2 && f_r[2:1] == 2'b11) ? 2'd2 : 2'd1;
                    st_n = S_IDLE;
                end else if (cls_branch) begin
                    taken_n = ir[4] ? ebci : (cond_t ^ ir[3]);
                    ea_n = r[7]; r_n[7] = r[7] + 16'd1;
                    st_n = S_RBAR;
                end else if (cls_mvo) begin
                    tmp_n = r[f_r];             // old value, also when f_r is the pointer
                    if (f_m == 3'd0) begin
                        ea_n = r[7]; r_n[7] = r[7] + 16'd1; st_n = S_ABAR;
                    end else begin
                        ea_n = r[f_m];
                        if (f_m[2]) r_n[f_m] = r[f_m] + 16'd1;
                        st_n = S_WBAR;
                    end
                end else begin                  // reads (cls_rd)
                    if (f_m == 3'd0) begin      // direct; SDBD ignored
                        ea_n = r[7]; r_n[7] = r[7] + 16'd1; st_n = S_ABAR;
                    end else if (f_m == 3'd6 && (!dbd || cfg_sdbd_r6_mame)) begin
                        cnt_n = 2'd2; st_n = S_IDLE;   // 3 cycles before the read
                    end else if (f_m == 3'd6) begin    // SDBD + R6, wiki
                        ea_n = r[6] - 16'd1; r_n[6] = r[6] - 16'd1; st_n = S_RBAR;
                    end else begin
                        ea_n = r[f_m];
                        if (f_m[2]) r_n[f_m] = r[f_m] + (dbd ? 16'd2 : 16'd1);
                        st_n = S_RBAR;
                    end
                end
            end

            S_IDLE: begin
                if (cnt != 2'd0) begin
                    cnt_n = cnt - 2'd1;
                end else if (cls_rd) begin      // stack read: pre-decrement
                    ea_n = r[6] - 16'd1;
                    r_n[6] = r[6] - (dbd ? 16'd2 : 16'd1);
                    st_n = S_RBAR;
                end else begin
                    ex_idle = 1'b1;
                end
            end

            S_RBAR:  st_n = S_RNACT;
            S_RNACT: st_n = S_RDTB;
            S_RDTB: begin
                tmp_n = din;
                if (cls_jump && jpt) begin      // S1 p.52: BB AAAAAA II, AAAAAAAAAA
                    if (tmp[9:8] != 2'd3) r_n[{1'b1, tmp[9:8]}] = r[7];
                    r_n[7] = {tmp[7:2], din[9:0]};
                    if (tmp[1:0] == 2'd1) fI_n = 1'b1;
                    if (tmp[1:0] == 2'd2) fI_n = 1'b0;
                    st_n = S_RNACT2;
                end else if (cls_branch && !taken) begin
                    fin = 1'b1; fin_ok = 1'b1;  // 7 cycles, no trailing NACT
                end else if (dbl) begin
                    lo_n = din[7:0]; ea_n = ea2; st_n = S_R2BAR;
                end else begin
                    st_n = S_RNACT2;
                end
            end
            S_RNACT2: begin
                if (cls_jump && !jpt) begin
                    jpt_n = 1'b1; ea_n = r[7]; r_n[7] = r[7] + 16'd1; st_n = S_RBAR;
                end else if (cls_jump) begin
                    fin = 1'b1; fin_ok = 1'b1;
                end else if (cls_branch) begin
                    cnt_n = 2'd0; st_n = S_IDLE;
                end else begin
                    ex_rd = 1'b1;
                end
            end
            S_R2BAR:  st_n = S_R2NACT;
            S_R2NACT: st_n = S_R2DTB;
            S_R2DTB:  ex_rd = 1'b1;

            S_ABAR:   st_n = S_ANACT;
            S_ANACT:  st_n = S_AADAR;
            S_AADAR: begin ea_n = din; st_n = S_ANACT2; end
            S_ANACT2: st_n = cls_mvo ? S_WDW : S_RDTB;

            S_WBAR:   st_n = S_WNACT;
            S_WNACT:  st_n = S_WDW;
            S_WDW:    st_n = S_WDWS;
            S_WDWS:   st_n = S_WNACT2;
            S_WNACT2: fin = 1'b1;               // MVO: not interruptible

            S_IINTAK: st_n = S_INACT1;
            S_INACT1: st_n = S_IDW;
            S_IDW:    st_n = S_IDWS;
            S_IDWS:   st_n = S_INACT2;
            S_INACT2: st_n = S_IIAB;
            S_IIAB: begin
                r_n[6] = r[6] + 16'd1;
                r_n[7] = din;
                if (intr_req) intr_req_n = 1'b0; else intrm_req_n = 1'b0;
                cnt_n = 2'd2; st_n = S_INACT3;
            end
            S_INACT3: begin
                if (cnt != 2'd0) cnt_n = cnt - 2'd1;
                else st_n = S_FBAR;
            end

            S_BUSAK: begin
                if (!busrq) begin
                    smp = 1'b1;
                    st_n = S_FBAR;              // or INTAK, below
                end
            end
            S_HALT: ;
            default: begin hlt_n = 1'b1; st_n = S_HALT; end
        endcase

        // ---- operations at the end of an instruction
        if (ex_idle) begin
            fin = 1'b1;
            fin_ok = !cls_shift;                // S1 p.53: shifts not interruptible
            if (cls_branch)                     // taken: PC + disp or + ~disp
                r_n[7] = r[7] + (tmp ^ {16{ir[5]}});
        end
        if (ex_rd) begin
            fin = 1'b1; fin_ok = 1'b1;
        end
        if ((ex_idle && !cls_branch) || ex_rd) begin
            if (x_we) r_n[ridx] = res;
            if (x_sz) begin
                fS_n = x_s7 ? res[7] : res[15];
                fZ_n = res == 16'd0;
            end
            fC_n = x_c; fO_n = x_o;
            if (x_nib) {fS_n, fZ_n, fO_n, fC_n} = ra[7:4];
        end

        // ---- end of an instruction: halt, sample, next step
        if (fin) begin
            // S1 p.56: HLT halts after the next instruction (CPU_NOTES row 7)
            if (hnow) begin hpend_n = 1'b0; hlt_n = 1'b1; end
            if (hlt_now) hlt_n = 1'b1;
            smp = 1'b1;
            intok_n = fin_ok && !hlt_n;
        end

        if (smp) begin                          // edge latches (wiki CP1610 Signal Pins)
            intrm_req_n  = intrm && (intrm_req || !intrm_prev);
            intrm_prev_n = intrm;
            intr_req_n   = intr && (intr_req || !intr_prev);
            intr_prev_n  = intr;
        end

        if (fin) begin
            if (hlt_n)
                st_n = S_HALT;
            else if (intok_n && busrq)
                st_n = S_BUSAK;
            else if (intok_n && (intr_req_n || (intrm_req_n && fI_n)))
                st_n = S_IINTAK;
            else
                st_n = S_FBAR;
        end else if (st == S_BUSAK && !busrq && (intr_req_n || (intrm_req_n && fI_n))) begin
            st_n = S_IINTAK;
        end
    end

    // ---------------------------------------------------------- registers
    wire logic ss_mod = ss_addr[15:8] == SS_ID;
    wire logic [7:0] ss_w = ss_addr[7:0];

    always_ff @(posedge clk) begin
        if (reset) begin
            // S1 p.21: registers undefined after MSYNC, interrupts disabled;
            // cleared here, as in the model.
            for (int k = 0; k < 8; k++) r[k] <= 16'd0;
            {fS, fZ, fO, fC, fI, fD} <= 6'd0;
            {intrm_req, intrm_prev, intr_req, intr_prev} <= 4'd0;
            hpend <= 1'b0; hlt <= 1'b0;
            st <= S_RST; cnt <= 2'd0; ir <= 10'd0; lo <= 8'd0;
            ea <= 16'd0; tmp <= 16'd0;
            {jpt, dbd, hnow, taken} <= 4'd0;
        end else if (ss_we && ss_mod) begin
            unique case (ss_w)
                8'd0: {r[1], r[0]} <= ss_wdata;
                8'd1: {r[3], r[2]} <= ss_wdata;
                8'd2: {r[5], r[4]} <= ss_wdata;
                8'd3: {r[7], r[6]} <= ss_wdata;
                8'd4: {tmp, ea} <= ss_wdata;
                8'd5: begin
                    ir <= ss_wdata[9:0]; lo <= ss_wdata[17:10];
                    st <= st_t'(ss_wdata[22:18]); cnt <= ss_wdata[24:23];
                    {taken, hnow, dbd, jpt} <= ss_wdata[28:25];
                end
                8'd6: begin
                    {fS, fZ, fO, fC} <= ss_wdata[3:0];
                    {fD, fI} <= ss_wdata[5:4];
                    {intr_prev, intr_req, intrm_prev, intrm_req} <= ss_wdata[10:7];
                    {hlt, hpend} <= ss_wdata[12:11];
                end
                default: ;
            endcase
        end else if (ce) begin
            for (int k = 0; k < 8; k++) r[k] <= r_n[k];
            {fS, fZ, fO, fC, fI, fD} <= {fS_n, fZ_n, fO_n, fC_n, fI_n, fD_n};
            {intrm_req, intrm_prev, intr_req, intr_prev}
                <= {intrm_req_n, intrm_prev_n, intr_req_n, intr_prev_n};
            hpend <= hpend_n; hlt <= hlt_n;
            st <= st_n; cnt <= cnt_n; ir <= ir_n; lo <= lo_n;
            ea <= ea_n; tmp <= tmp_n;
            {jpt, dbd, hnow, taken} <= {jpt_n, dbd_n, hnow_n, taken_n};
        end
    end

    always_comb begin
        ss_rdata = 32'd0;
        if (ss_mod) begin
            unique case (ss_w)
                8'd0: ss_rdata = {r[1], r[0]};
                8'd1: ss_rdata = {r[3], r[2]};
                8'd2: ss_rdata = {r[5], r[4]};
                8'd3: ss_rdata = {r[7], r[6]};
                8'd4: ss_rdata = {tmp, ea};
                8'd5: ss_rdata = {3'd0, taken, hnow, dbd, jpt, cnt, 5'(st), lo, ir};
                8'd6: ss_rdata = {19'd0, hlt, hpend, intr_prev, intr_req,
                                  intrm_prev, intrm_req, 1'b0, fD, fI, fS, fZ, fO, fC};
                default: ss_rdata = 32'd0;
            endcase
        end
    end

endmodule

`default_nettype wire
