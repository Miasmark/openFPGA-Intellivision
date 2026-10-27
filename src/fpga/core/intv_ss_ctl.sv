// Intellivision core: the save-state controller, ss_ctl (DESIGN.md 3 module
// 16, 4; build step 7; docs/SAVESTATE.md).
//
// The Pocket's commands reach it through core_bridge_cmd (clk_74a):
//   0x00A0  save   savestate_start held until ack; then busy, and ok or err
//                  held until the next request (DESIGN 4.1, 13 item 16)
//   0x00A4  load   the same with savestate_load; the host has written the
//                  blob over the bridge before it sends the command
//   0x00B0  menu   osnotify_inmenu: with pause_en (setting "Pause in menu")
//                  the machine is frozen while the menu is open
// Sleep is a save and, on wake, a load (APF core.json sleep_supported).
// The host polls 0x00A0 / 0x00A4 for the result code: 0 idle, 1 busy, 2 ok,
// 3 error (core_bridge_cmd.v; the 7800 core's template). The status bits
// change one at a time, 4 clk_sys apart, in an order that never shows the
// host a wrong code across the crossing: busy rises, then ok / err clear,
// then ack; at the end ok or err rises, then busy drops.
//
// The blob: tools/savestate.py's layout (intv_ss_pkg), 153,600 bytes at
// bridge address 0x50000000, 32-bit words, big-endian. Its live part, bytes
// 0 - 40,959 (header, module words, cart RAM), is kept in the SRAM at
// STAGE (2 SRAM words per blob word, the upper half first): a save writes
// it there and the host reads it from there; for a load the host writes it
// there, and only after its header and payload CRC have been checked is
// any of it written into the machine. Bytes from 40,960 on read 0; a write
// of anything else there marks the blob bad (cleared by a write to word 0
// and after every load). The bridge's accesses cross to clk_sys one at a
// time (a toggle each way; the bridge leaves at least 88 clk_74a, 1.18 us,
// between them: io_bridge_peripheral.v) and are served from the SRAM
// through intv_media's aux port within about 25 clk_sys. A read's word is
// on bridge_rd_data from then until the next read, as the bridge expects
// (it sends the word of the last bridge_rd in the next read: the template's
// core_bridge_cmd.v and agg23's data_unloader.sv work the same way).
//
// Freezing (DESIGN 4.2, intv_timing.sv): run = 0 stops the machine's clock
// enables; the raster runs on, so the Pocket's video keeps its sync, and
// the machine resumes when the raster comes round to its position (mpos).
// The freeze lands at a quiet point: the machine live and out of reset, in
// VBlank (its vcnt < V_QUIET, before the frame's first BUSRQ), and the CPU
// at an instruction boundary (inside an opcode fetch's BAR cycle, not on
// its last clk: no bus access in flight) or halted or held. A save or load
// that finds none within TIMEOUT_FRAMES frames (counted while the machine
// is out of reset; at most 255 frames in all) ends with err, the machine
// untouched. The state is read or written from 32 clk_sys after the
// freeze, with ss_en high (the block RAMs' ports belong to the state port
// then; intv_ram.sv); ss_en drops at least 4 clk_sys before run rises.
//
//   save   freeze; every module word (ss_word_addr order) and the cart RAM
//          into the blob with the payload CRC, then the header; ok; resume
//          (unless the menu holds the freeze). About 5 ms.
//   load   freeze; check the header (magic, version, size, length, the
//          cartridge's CRC and length, the CFG's CRC (version 2, step 8),
//          the EXEC's and GROM's CRCs, flags (bit 0: the ECS attached;
//          version 3, step 9), the ECS ROM's CRC,
//          word counts, reserved words 0) and the payload (CRC32, the
//          unused module area 0, nothing written beyond the live part): a
//          foreign or corrupt blob ends with err and the machine resumes
//          untouched. Else every module
//          word and the cart RAM are written (the timing word's mpos: the
//          machine resumes at the saved position), then ok.
//
// (build step 8) An image whose writable storage the blob cannot hold
// (cart_noss: an Intellicart bank window that writes, or more cart RAM than
// the 16K cells; docs/CARTFORMATS.md 5) refuses saves and loads with err,
// the machine untouched.
//
// Wake (sleep_supported): the order of the Pocket's 0x00A4 and its reset
// exit on wake is not documented. A load asked for while the machine is
// held in reset (the host's reset; the cartridge loaded) is checked at once
// and answered ok or err without a freeze; an ok one is staged (pend) and
// applied, checked once more, at the first quiet point after the reset
// exit, with no status change. A load or save that starts while a staged
// one waits replaces or follows it (DESIGN 4.2).
//
// Bridge accesses at 0x50xxxxxx are served one at a time: while a save or
// load reads or writes the state (O_SNAP .. O_APPLYW) one access is held
// (bp) and served after it. The host sends none then (it polls the result
// first); a second one while one is held overwrites it and counts in
// br_drops (sticky, for the bench: sim/tb/tb_savestate.sv checks it).
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_ss_ctl #(
    parameter int          V_QUIET        = 60,   // freeze while the machine's vcnt < this
    parameter int          TIMEOUT_FRAMES = 3,    // DESIGN 4.2
    parameter logic [16:0] STAGE          = 17'h13000,
    parameter logic [16:0] CRAM           = 17'h18000
) (
    // ---------------------------------------------- clk_74a: APF
    input  wire logic        clk_74a,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [31:0] bridge_addr,         // [1:0] unused: word accesses
    /* verilator lint_on UNUSEDSIGNAL */
    input  wire logic        bridge_rd,
    input  wire logic        bridge_wr,
    input  wire logic [31:0] bridge_wr_data,
    output logic      [31:0] bridge_rd_data,

    input  wire logic        savestate_start,
    output logic             savestate_start_ack,
    output logic             savestate_start_busy,
    output logic             savestate_start_ok,
    output logic             savestate_start_err,
    input  wire logic        savestate_load,
    output logic             savestate_load_ack,
    output logic             savestate_load_busy,
    output logic             savestate_load_ok,
    output logic             savestate_load_err,
    input  wire logic        osnotify_inmenu,
    input  wire logic        pause_en,

    // ---------------------------------------------- clk_sys: the machine
    input  wire logic        clk,
    input  wire logic        mreset,
    input  wire logic        cart_ready,         // the loader is done (cartridge CRC valid)
    input  wire logic        live,
    input  wire logic [8:0]  vcnt,
    input  wire logic        ce_cpu,
    input  wire logic        cpu_fetch,
    input  wire logic        cpu_halted,
    input  wire logic        cpu_hold,
    input  wire logic [31:0] cart_crc,
    input  wire logic [16:0] cart_words,
    input  wire logic [31:0] cfg_crc,            // the CFG's CRC32, 0: none (step 8)
    input  wire logic        cart_noss,          // the image's state cannot be saved (step 8)
    input  wire logic [31:0] exec_crc,           // the system ROM slots' CRC32s (intv_core)
    input  wire logic [31:0] grom_crc,
    input  wire logic        ecs_flag,           // the ECS attached (step 9: header flags bit 0)
    input  wire logic [31:0] ecs_crc,            // its ROM slot's CRC32 (0 when not attached)

    output logic             run,
    output logic             frozen,
    output logic             ss_en,
    output logic [15:0]      ss_addr,
    output logic             ss_we,
    output logic [31:0]      ss_wdata,
    input  wire logic [31:0] ss_rdata,

    output logic             aux_req,
    output logic             aux_we,
    output logic [16:0]      aux_addr,
    output logic [15:0]      aux_wdata,
    input  wire logic        aux_ack,
    input  wire logic [15:0] aux_rdata
);

    import intv_ss_pkg::*;

    localparam int W_MOD0 = SS_MOD_BYTE / 4;              // 16: first module word
    localparam int W_GAP0 = W_MOD0 + SS_MOD_WORDS;        // unused module area
    localparam int W_CRAM = SS_CRAM_BYTE / 4;             // 2048
    localparam int W_END  = SS_LIVE_END / 4;              // 10240

    // ============================================== clk_74a side
    logic        b_t = 1'b0;                              // request toggle
    logic        b_we = 1'b0;
    logic [21:0] b_w = 22'd0;                             // blob word
    logic [31:0] b_d = 32'd0;
    logic        rd_q = 1'b0, wr_q = 1'b0;
    logic [2:0]  r_s = 3'd0;                              // response toggle, synchronised
    logic        r_t = 1'b0;                              // clk_sys
    logic [31:0] r_q = 32'd0;                             // clk_sys, stable before r_t moves
    initial bridge_rd_data = 32'd0;

    wire logic b_hit = bridge_addr[31:24] == 8'h50;

    always_ff @(posedge clk_74a) begin
        rd_q <= bridge_rd;
        wr_q <= bridge_wr;
        if (b_hit && ((bridge_rd && !rd_q) || (bridge_wr && !wr_q))) begin
            b_we <= bridge_wr;
            b_w  <= bridge_addr[23:2];
            b_d  <= bridge_wr_data;
            b_t  <= !b_t;
        end
        r_s <= {r_s[1:0], r_t};
        if (r_s[2] != r_s[1])
            bridge_rd_data <= r_q;
    end

    // status to clk_74a: levels, each through two flip-flops
    logic s_ack = 1'b0, s_busy = 1'b0, s_ok = 1'b0, s_err = 1'b0;
    logic l_ack = 1'b0, l_busy = 1'b0, l_ok = 1'b0, l_err = 1'b0;
    logic [7:0] st_a = 8'd0, st_b = 8'd0;
    always_ff @(posedge clk_74a) begin
        st_a <= {s_ack, s_busy, s_ok, s_err, l_ack, l_busy, l_ok, l_err};
        st_b <= st_a;
    end
    assign {savestate_start_ack, savestate_start_busy, savestate_start_ok, savestate_start_err,
            savestate_load_ack, savestate_load_busy, savestate_load_ok, savestate_load_err} = st_b;

    // ============================================== clk_sys side
    logic [2:0] st_s = 3'd0, ld_s = 3'd0, mn_s = 3'd0, pz_s = 3'd0, b_s = 3'd0;
    always_ff @(posedge clk) begin
        st_s <= {st_s[1:0], savestate_start};
        ld_s <= {ld_s[1:0], savestate_load};
        mn_s <= {mn_s[1:0], osnotify_inmenu};
        pz_s <= {pz_s[1:0], pause_en};
        b_s  <= {b_s[1:0], b_t};
    end
    wire logic start_lv = st_s[2], load_lv = ld_s[2];
    wire logic menu_hold = mn_s[2] && pz_s[2];

    // the bridge request, taken when its toggle has crossed (its words
    // were set with the toggle and have been stable since)
    logic        bp = 1'b0;                               // pending
    logic        bp_we = 1'b0;
    logic [21:0] bp_w = 22'd0;
    logic [31:0] bp_d = 32'd0;
    logic        bp_take;                                 // the FSM takes it (one clk)
    logic        cur_we = 1'b0;                           // the access being served
    /* verilator lint_off UNUSEDSIGNAL */
    logic [3:0]  br_drops = 4'd0;                         // accesses overwritten (sticky, saturating; the bench)
    /* verilator lint_on UNUSEDSIGNAL */

    // b_we is sampled on every clk first: a plain register, so its crossing
    // is one net that core_constraints.sdc bounds (loaded into bp_we with
    // an enable, the fit made it a LUT input, which set_net_delay misses);
    // b_we_s holds the access's direction from the clk after b_s[0] took
    // the toggle on, one clk before bp_we loads it
    logic        b_we_s = 1'b0;
    always_ff @(posedge clk)
        b_we_s <= b_we;

    always_ff @(posedge clk) begin
        if (b_s[2] != b_s[1]) begin
            bp <= 1'b1;
            bp_we <= b_we_s;
            bp_w <= b_w;
            bp_d <= b_d;
            if (bp && !bp_take && br_drops != 4'hF)
                br_drops <= br_drops + 4'd1;
        end else if (bp_take)
            bp <= 1'b0;
        if (bp_take)
            cur_we <= bp_we;
    end

    // ---------------------------------------------- SRAM: one blob word
    // m_go starts two accesses through the aux port: m_a (bits 31-16) and
    // m_a + 1 (bits 15-0); m_done pulses when both are done, m_q the word read
    typedef enum logic [1:0] {M_IDLE, M_HI, M_LO} mst_t;
    mst_t        mst = M_IDLE;
    logic        m_go, m_we;
    logic [16:0] m_a;
    logic [31:0] m_d;
    logic [15:0] m_lo = 16'd0;
    logic [31:0] m_q = 32'd0;
    logic        m_done = 1'b0;
    initial begin
        aux_req = 1'b0; aux_we = 1'b0; aux_addr = 17'd0; aux_wdata = 16'd0;
    end

    always_ff @(posedge clk) begin
        m_done <= 1'b0;
        case (mst)
            M_IDLE: if (m_go) begin
                aux_req   <= 1'b1;
                aux_we    <= m_we;
                aux_addr  <= m_a;
                aux_wdata <= m_d[31:16];
                m_lo      <= m_d[15:0];
                mst       <= M_HI;
            end
            M_HI: if (aux_ack) begin
                m_q[31:16] <= aux_rdata;
                aux_addr   <= aux_addr + 17'd1;
                aux_wdata  <= m_lo;
                mst        <= M_LO;
            end
            M_LO: if (aux_ack) begin
                m_q[15:0] <= aux_rdata;
                aux_req   <= 1'b0;
                aux_we    <= 1'b0;
                m_done    <= 1'b1;
                mst       <= M_IDLE;
            end
            default: mst <= M_IDLE;
        endcase
    end

    // ---------------------------------------------- CRC-32 (zlib), a word
    // big-endian: byte 31-24 first, each byte bit 0 first
    function automatic logic [31:0] crc_word(input logic [31:0] c, input logic [31:0] v);
        logic [31:0] x;
        x = c;
        for (int b = 3; b >= 0; b--) begin
            x = x ^ {24'd0, v[8*b +: 8]};
            for (int k = 0; k < 8; k++)
                x = x[0] ? (x >> 1) ^ 32'hEDB88320 : x >> 1;
        end
        return x;
    endfunction

    // ---------------------------------------------- freeze
    logic op = 1'b0;                                      // a save or load holds the freeze
    wire logic want = op || menu_hold;
    wire logic quiet = live && !mreset && vcnt < 9'(V_QUIET) && !ce_cpu
                    && (cpu_fetch || cpu_halted || cpu_hold);
    typedef enum logic [1:0] {F_RUN, F_SETTLE, F_FROZEN, F_RESUME} fst_t;
    fst_t       fst = F_RUN;
    logic [5:0] fcnt = 6'd0;
    initial begin
        run = 1'b1;
        frozen = 1'b0;
        ss_en = 1'b0;
        ss_addr = 16'd0;
        ss_we = 1'b0;
        ss_wdata = 32'd0;
    end

    always_ff @(posedge clk) begin
        case (fst)
            F_RUN: if (want && quiet) begin
                run  <= 1'b0;
                fcnt <= 6'd32;            // let a cartridge access or bridge write end
                fst  <= F_SETTLE;
            end
            F_SETTLE: if (fcnt != 6'd0) fcnt <= fcnt - 6'd1;
                      else begin
                          frozen <= 1'b1;
                          fst <= F_FROZEN;
                      end
            F_FROZEN: if (!want && !ss_en) begin
                frozen <= 1'b0;
                fcnt <= 6'd4;
                fst <= F_RESUME;
            end
            F_RESUME: if (want) begin
                frozen <= 1'b1;
                fst <= F_FROZEN;
            end else if (fcnt != 6'd0)
                fcnt <= fcnt - 6'd1;
            else begin
                run <= 1'b1;
                fst <= F_RUN;
            end
            default: fst <= F_RUN;
        endcase
    end

    // ---------------------------------------------- the operation
    typedef enum logic [4:0] {
        O_IDLE, O_HS1, O_HS2, O_WAITF, O_BR, O_BRW,
        O_SNAP, O_SNAPR, O_SNAPW, O_HDR,
        O_VHDR, O_VPAY, O_VCHK, O_APPLY, O_APPLYW,
        O_FIN_OK, O_FIN_ERR, O_FIN2
    } ost_t;
    ost_t        ost = O_IDLE, ret = O_IDLE;
    logic        is_load = 1'b0;
    logic        staged = 1'b0;                           // a load checked in reset, not applied
    logic        pend = 1'b0;                             // a staged load waits for the reset exit
    logic        silent = 1'b0;                           // applying it: no status change
    /* verilator lint_off UNUSEDSIGNAL */
    logic        ld_applied = 1'b0;                       // a load's state is in (one clk; the bench)
    /* verilator lint_on UNUSEDSIGNAL */
    logic [2:0]  dly = 3'd0;
    logic [13:0] w = 14'd0;                               // blob word
    logic [1:0]  ph = 2'd0;
    logic [31:0] crc = 32'hFFFFFFFF, hdr_crc = 32'd0, v = 32'd0;
    logic        bad = 1'b0, resv_bad = 1'b0;
    logic [2:0]  tmo = 3'd0;
    logic [7:0]  tmo_all = 8'd0;
    logic [8:0]  vcnt_q = 9'd0;

    wire logic        in_mod  = w >= 14'(W_MOD0) && w < 14'(W_GAP0);
    wire logic        in_gap  = w >= 14'(W_GAP0) && w < 14'(W_CRAM);
    wire logic        in_cram = w >= 14'(W_CRAM);
    wire logic [10:0] mi      = 11'(w - 14'(W_MOD0));
    wire logic [16:0] stg_a   = STAGE + {2'd0, w, 1'b0};
    wire logic [16:0] cram_a  = CRAM + {2'd0, w - 14'(W_CRAM), 1'b0};
    wire logic        w_last  = w == 14'(W_END - 1);
    wire logic        m_idle  = mst == M_IDLE;

    // the header this core expects (word SS_H_CRC: c)
    function automatic logic [31:0] hdr_exp(input logic [3:0] i, input logic [31:0] c,
                                            input logic [31:0] ccrc, input logic [16:0] cwords,
                                            input logic [31:0] ecrc, input logic [31:0] gcrc);
        case (i)
            4'(SS_H_MAGIC):      hdr_exp = SS_MAGIC;
            4'(SS_H_VERSION):    hdr_exp = SS_VERSION;
            4'(SS_H_SIZE):       hdr_exp = 32'(SS_BLOB_BYTES);
            4'(SS_H_LENGTH):     hdr_exp = 32'(SS_PAYLOAD);
            4'(SS_H_CART_CRC):   hdr_exp = ccrc;
            4'(SS_H_CART_WORDS): hdr_exp = {15'd0, cwords};
            4'(SS_H_FLAGS):      hdr_exp = {31'd0, ecs_flag};
            4'(SS_H_CRC):        hdr_exp = c;
            4'(SS_H_MOD_WORDS):  hdr_exp = 32'(SS_MOD_WORDS);
            4'(SS_H_CRAM_CELLS): hdr_exp = 32'(SS_CRAM_CELLS);
            4'(SS_H_EXEC_CRC):   hdr_exp = ecrc;
            4'(SS_H_GROM_CRC):   hdr_exp = gcrc;
            4'(SS_H_CFG_CRC):    hdr_exp = cfg_crc;
            4'(SS_H_ECS_CRC):    hdr_exp = ecs_crc;
            default:             hdr_exp = 32'd0;
        endcase
    endfunction

    // the bridge's word: in the live part from the SRAM, else 0
    wire logic bp_live = bp_w < 22'(W_END);

    // the SRAM requests of each state (m_go in a state's phase 0; the
    // state moves to phase 1 or 2 in the same clk and waits for m_done)
    always_comb begin
        m_go = 1'b0;
        m_we = 1'b0;
        m_a  = stg_a;
        m_d  = v;
        bp_take = 1'b0;
        case (ost)
            O_BR: if (m_idle) begin
                bp_take = 1'b1;
                if (bp_live) begin
                    m_go = 1'b1;
                    m_we = bp_we;
                    m_a  = STAGE + {bp_w[15:0], 1'b0};
                    m_d  = bp_d;
                end
            end
            O_SNAP:  if (ph == 2'd0 && dly == 3'd0 && in_cram) begin
                m_go = 1'b1;                              // two cart RAM cells
                m_a  = cram_a;
            end
            O_SNAPW, O_HDR: if (ph == 2'd0) begin
                m_go = 1'b1;
                m_we = 1'b1;
            end
            O_VHDR, O_APPLY: if (ph == 2'd0)
                m_go = 1'b1;
            O_VPAY:  if (ph == 2'd0 && !bad)
                m_go = 1'b1;
            O_APPLYW: if (ph == 2'd0 && in_cram) begin
                m_go = 1'b1;
                m_we = 1'b1;
                m_a  = cram_a;
            end
            default: ;
        endcase
    end

    always_ff @(posedge clk) begin
        ss_we <= 1'b0;
        ld_applied <= 1'b0;
        vcnt_q <= vcnt;
        if (!start_lv) s_ack <= 1'b0;
        if (!load_lv) l_ack <= 1'b0;
        if (dly != 3'd0) dly <= dly - 3'd1;

        case (ost)
            O_IDLE: begin
                if (bp) begin
                    ret <= O_IDLE;
                    ost <= O_BR;
                end else if (pend && !mreset) begin       // apply the staged load
                    is_load <= 1'b1;
                    silent <= 1'b1;
                    op <= 1'b1;
                    tmo <= 3'd0;
                    tmo_all <= 8'd0;
                    ost <= O_WAITF;
                end else if ((start_lv && !s_ack) || (load_lv && !l_ack)) begin
                    is_load <= !(start_lv && !s_ack);
                    if (start_lv && !s_ack) s_busy <= 1'b1; else l_busy <= 1'b1;
                    dly <= 3'd4;
                    ost <= O_HS1;
                end
            end
            O_HS1: if (dly == 3'd0) begin
                s_ok <= 1'b0; s_err <= 1'b0; l_ok <= 1'b0; l_err <= 1'b0;
                dly <= 3'd4;
                ost <= O_HS2;
            end
            O_HS2: if (dly == 3'd0) begin
                if (is_load) l_ack <= 1'b1; else s_ack <= 1'b1;
                if (is_load) pend <= 1'b0;                // a new load replaces a staged one
                staged <= 1'b0;
                op <= 1'b1;
                tmo <= 3'd0;
                tmo_all <= 8'd0;
                ost <= O_WAITF;
            end

            O_WAITF: begin
                if (vcnt == 9'd0 && vcnt_q != 9'd0) begin  // a raster frame
                    if (!mreset) tmo <= tmo + 3'd1;
                    tmo_all <= tmo_all + 8'd1;
                end
                if (cart_noss && cart_ready)
                    ost <= O_FIN_ERR;                     // docs/CARTFORMATS.md 5: no state
                else if (frozen && !(is_load && mreset)) begin
                    ss_en <= 1'b1;
                    w <= is_load ? 14'd0 : 14'(W_MOD0);
                    ph <= 2'd0;
                    crc <= 32'hFFFFFFFF;
                    bad <= 1'b0;
                    dly <= 3'd2;
                    ost <= is_load ? O_VHDR : O_SNAP;
                end else if (silent && mreset) begin      // reset again: wait for its exit
                    op <= 1'b0;
                    silent <= 1'b0;
                    ost <= O_IDLE;
                end else if (is_load && mreset && cart_ready) begin
                    staged <= 1'b1;                       // check it now, apply it later
                    w <= 14'd0;
                    ph <= 2'd0;
                    crc <= 32'hFFFFFFFF;
                    bad <= 1'b0;
                    dly <= 3'd2;
                    ost <= O_VHDR;
                end else if (tmo == 3'(TIMEOUT_FRAMES + 1) || tmo_all == 8'd255)
                    ost <= O_FIN_ERR;
                else if (bp) begin
                    ret <= O_WAITF;
                    ost <= O_BR;
                end
            end

            // a bridge access: a write into the SRAM (or the check of a word
            // beyond the live part), a read from it
            O_BR: if (m_idle) begin
                if (bp_we && bp_w == 22'd0) resv_bad <= 1'b0;
                if (bp_live)
                    ost <= O_BRW;
                else begin
                    if (bp_we && bp_d != 32'd0) resv_bad <= 1'b1;
                    if (!bp_we) begin r_q <= 32'd0; r_t <= !r_t; end
                    ost <= ret;
                end
            end
            O_BRW: if (m_done) begin
                if (!cur_we) begin r_q <= m_q; r_t <= !r_t; end
                ost <= ret;
            end

            // ---------------- save: module words, gap, cart RAM, then header
            O_SNAP: if (dly == 3'd0) begin
                case (ph)
                    2'd0: if (in_mod) begin
                              ss_addr <= intv_ss_pkg::ss_word_addr(mi);
                              dly <= 3'd2;
                              ph <= 2'd1;
                          end else if (in_gap) begin
                              v <= 32'd0;
                              ost <= O_SNAPR;
                          end else
                              ph <= 2'd2;                 // cart RAM: m_go now
                    2'd1: begin
                              v <= ss_rdata;
                              ost <= O_SNAPR;
                          end
                    default: if (m_done) begin
                              v <= m_q;
                              ost <= O_SNAPR;
                          end
                endcase
            end
            O_SNAPR: begin
                crc <= crc_word(crc, v);
                ph <= 2'd0;
                ost <= O_SNAPW;
            end
            O_SNAPW: begin
                if (ph == 2'd0) ph <= 2'd1;               // write v at w: m_go now
                else if (m_done) begin
                    ph <= 2'd0;
                    if (w_last) begin
                        w <= 14'd0;
                        v <= hdr_exp(4'd0, ~crc, cart_crc, cart_words, exec_crc, grom_crc);
                        ost <= O_HDR;
                    end else begin
                        w <= w + 14'd1;
                        ost <= O_SNAP;
                    end
                end
            end
            O_HDR: begin
                if (ph == 2'd0) ph <= 2'd1;               // write v at w: m_go now
                else if (m_done) begin
                    ph <= 2'd0;
                    if (w == 14'(SS_HDR_WORDS - 1))
                        ost <= O_FIN_OK;
                    else begin
                        w <= w + 14'd1;
                        v <= hdr_exp(4'(w + 14'd1), ~crc, cart_crc, cart_words, exec_crc, grom_crc);
                    end
                end
            end

            // ---------------- load: header, payload CRC, then apply
            O_VHDR: begin
                if (ph == 2'd0) ph <= 2'd1;               // read w: m_go now
                else if (m_done) begin
                    ph <= 2'd0;
                    if (w == 14'(SS_H_CRC))
                        hdr_crc <= m_q;
                    else if (m_q != hdr_exp(4'(w), 32'd0, cart_crc, cart_words, exec_crc, grom_crc))
                        bad <= 1'b1;
                    if (w == 14'(SS_HDR_WORDS - 1))
                        ost <= O_VPAY;
                    w <= w + 14'd1;
                end
            end
            O_VPAY: begin
                if (bad)
                    ost <= O_FIN_ERR;                     // foreign: no need to read on
                else if (ph == 2'd0) ph <= 2'd1;          // read w: m_go now
                else if (m_done) begin
                    ph <= 2'd0;
                    crc <= crc_word(crc, m_q);
                    if (in_gap && m_q != 32'd0) bad <= 1'b1;
                    if (w_last) begin
                        w <= 14'(W_MOD0);
                        ost <= O_VCHK;
                    end else
                        w <= w + 14'd1;
                end
            end
            O_VCHK: begin
                if (bad || resv_bad || ~crc != hdr_crc)
                    ost <= O_FIN_ERR;
                else if (staged)
                    ost <= O_FIN_OK;                      // applied after the reset exit
                else
                    ost <= O_APPLY;
            end
            O_APPLY: begin
                if (ph == 2'd0) ph <= 2'd1;               // read w: m_go now
                else if (m_done) begin
                    v <= m_q;
                    ph <= 2'd0;
                    ost <= O_APPLYW;
                end
            end
            O_APPLYW: begin
                case (ph)
                    2'd0: if (in_mod) begin
                              ss_addr  <= intv_ss_pkg::ss_word_addr(mi);
                              ss_wdata <= v;
                              ss_we    <= 1'b1;
                              ph       <= 2'd2;
                          end else if (in_gap)
                              ph <= 2'd2;
                          else
                              ph <= 2'd1;                 // cart RAM: m_go now
                    2'd1: if (m_done) ph <= 2'd2;
                    default: begin
                        ph <= 2'd0;
                        if (w_last)
                            ost <= O_FIN_OK;
                        else begin
                            w <= w + 14'd1;
                            ost <= O_APPLY;
                        end
                    end
                endcase
            end

            // ---------------- the end
            O_FIN_OK, O_FIN_ERR: begin
                ss_en <= 1'b0;
                if (is_load) begin
                    resv_bad <= 1'b0;
                    if (ost == O_FIN_OK && !staged) ld_applied <= 1'b1;
                    if (staged) pend <= ost == O_FIN_OK;
                    if (silent) pend <= 1'b0;
                    if (!silent) begin
                        if (ost == O_FIN_OK) l_ok <= 1'b1; else l_err <= 1'b1;
                    end
                end else begin
                    if (ost == O_FIN_OK) s_ok <= 1'b1; else s_err <= 1'b1;
                end
                dly <= 3'd4;
                ost <= O_FIN2;
            end
            O_FIN2: if (dly == 3'd0) begin
                s_busy <= 1'b0;
                l_busy <= 1'b0;
                op <= 1'b0;
                staged <= 1'b0;
                silent <= 1'b0;
                ost <= O_IDLE;
            end
            default: ost <= O_IDLE;
        endcase
    end

endmodule

`default_nettype wire
