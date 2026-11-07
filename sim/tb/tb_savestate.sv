// Step 7 bench (DESIGN.md 9; docs/SAVESTATE.md): save states as the Pocket
// drives them. The core's clk_sys side (intv_core: media, timing, machine,
// ss_ctl) with the SRAM model, behind the APF template's command handler
// (core_bridge_cmd, clk_74a) and core_top's bridge read multiplexer. The
// bench is the Pocket's host: it writes the command words at 0xF8000000
// and polls them for the result code, reads the blob from 0x50000000 after
// a save and writes it there before a load, one bridge access every 88
// clk_74a (the bridge's fastest, io_bridge_peripheral.v) with the read's
// word taken 84 clk_74a after its bridge_rd (the bridge sends it in the
// next access).
//
// Plusargs
//   +exec=F +grom=F +cart=F   system ROMs and cartridge (as tb_system.sv)
//   +cfg=F                    the cartridge's CFG (build step 8)
//   +pads=RRLL +keys=F        hand controllers (tb_system.sv: "k RRLL" from
//                             frame k on, k x 14,934 machine cycles)
//   +cycles=N                 end at machine cycle N
//   +pause=0                  setting "Pause in menu" off (default on)
//   +hold=1                   keep the host's reset on after the loader is
//                             ready (a wake: script "reset 0" releases it)
//   +script=F                 events, one per line, in order:
//       save C KIND FILE      at machine cycle C (then at the first clk
//                             where KIND holds, within 30 frames: any, midinst, busrq,
//                             rowfetch, sound; step 10: voice, a voice sample in the
//                             making; voicewin, its busy window open) ask for a save (0x00A0); on
//                             ok read the blob into FILE
//       saveb C FILE          a save as "save C any FILE", and while it
//                             reads the state two bridge reads at 0x50000000
//                             (the second overwrites the first: br_drops)
//       race C                at cycle C (or at once) six tries: a blob read,
//                             and a blob write strobed while ss_ctl's SRAM
//                             access for the read is under way (faster than
//                             the bridge sends them); the read must still be
//                             answered with its own word, the write must land
//       load C FILE EXPECT R  at cycle C write FILE over the bridge, ask for
//                             a load (0x00A4); EXPECT ok or err; on ok the
//                             bench's machine cycle becomes R (the saved
//                             cycle) when the core has written the state
//                             (C = -1: at once, also in reset)
//       loadr C FILE EXPECT R a load as above, with the host's reset
//                             released while ss_ctl checks the staged blob
//       reset V D             the host's reset := V, D clk_sys from now
//       menu C 1|0            at cycle C open (1) or close (0) the menu (0x00B0)
//       wait F                F raster frames
//   +log=F
// Machine cycles count CPU cycle enables from the first fetch, as in
// tb_system.sv: the machine's own time, which a freeze does not advance.
//
// Log lines
//   H k hb nb hs ns     frame k's bus phases and step starts (tb_system.sv +bushash)
//   A k ha na hq nq     frame k's PSG steps and 48 kHz samples (tb_system.sv)
//   P k hp np           frame k's picture: FNV-1a over the colour of every
//                       pixel clock the machine ran (np of them)
//   Q what c kind busak cp_on fetch lv vcnt
//                       a request reached ss_ctl (machine cycle c, what the
//                       machine was doing)
//   Z c mpos r0..r7 frames
//                       the machine froze at machine cycle c (its position
//                       and registers; raster frames since the request)
//   U c frames          the machine resumed (raster frames it was frozen)
//   M c hash nz         at each freeze: FNV-1a over the SRAM's cart RAM area
//                       ($18000-$1BFFF, 16,384 cells) and its nonzero cells
//   MA c hash nz        the same when a load's state is in
//   K c hash            at each freeze: FNV-1a over the 32 Intellicart bank
//                       registers (intv_cart bank[0..31], one byte each)
//   KA c hash           the same when a load's state is in
//   W f c0 c1           a "wait f": machine cycle at its start and end
//   D clks zero         the machine was not live for clks clk_sys; the
//                       sound was 0 from zero clk_sys on (-1: never)
//   S code ...          a host command's result (code as the host reads it)
//   SAVE ok|err c FILE  /  LOAD ok|err EXPECT e
//   MENU open c         before the host opens the menu; MENU 0 c after it closed it
//   R race d hit h      a race try: h = 1 if its write reached ss_ctl while the
//                       read's SRAM access was under way
//   RW hits wrong       after the race: tries that hit, words read wrong
//   E drops n           at the end: bridge accesses ss_ctl overwrote (br_drops)
//   END / FAIL text
// Checked on every clk: never live while frozen; the sound 0 once the
// machine has not been live for 4 ms (171,818 clk_sys); never ss_en while
// the machine runs; a load's state never written while the machine runs.
//
// SPDX-License-Identifier: MIT

`timescale 1ps / 1ps
`default_nettype none

module tb_savestate;

    // clk_sys 42.954545 MHz, clk_74a 74.25 MHz
    // (clk_74a runs only while the host talks to the core, and stops low:
    // nothing on it acts otherwise, and the simulation runs faster)
    logic clk = 1'b0, clk74 = 1'b0, clk74_on = 1'b0;
    always #11640 clk = ~clk;
    initial forever begin
        #6734;
        if (clk74_on || clk74) clk74 = ~clk74;
    end

    task automatic host_on();
        clk74_on = 1'b1;
        repeat (16) @(negedge clk74);
    endtask
    task automatic host_off();
        repeat (16) @(negedge clk74);
        clk74_on = 1'b0;
    endtask

    localparam longint FRAME = 14934;

    // ------------------------------------------------------------ the host side
    logic [31:0] bridge_addr = 32'd0, bridge_wr_data = 32'd0;
    logic        bridge_rd = 1'b0, bridge_wr = 1'b0;
    wire  logic [31:0] cmd_rd_data, ss_rd_data, jlp_rd_data;
    logic [31:0] bridge_rd_data;
    logic        pause_en = 1'b1;

    // core_top's multiplexer
    always_comb begin
        if (bridge_addr[31:24] == 8'hF8)      bridge_rd_data = cmd_rd_data;
        else if (bridge_addr[31:24] == 8'h50) bridge_rd_data = ss_rd_data;
        else if (bridge_addr[31:24] == 8'h20) bridge_rd_data = jlp_rd_data;   // the JLP flash slot
        else                                  bridge_rd_data = 32'd0;
    end

    wire logic        savestate_start, savestate_load, osnotify_inmenu;
    wire logic        s_ack, s_busy, s_ok, s_err, l_ack, l_busy, l_ok, l_err;
    /* verilator lint_off UNUSEDSIGNAL */
    wire logic        reset_n, d_rr, d_rw, d_up, d_all, rtc_valid;
    wire logic [15:0] d_rr_id, d_rw_id, d_up_id;
    wire logic [31:0] d_rw_size, d_up_size, rtc_e, rtc_d, rtc_t;
    wire logic        t_ack, t_done;
    wire logic [2:0]  t_err;
    wire logic [31:0] dt_q;
    /* verilator lint_on UNUSEDSIGNAL */

    core_bridge_cmd icb (
        .clk(clk74), .reset_n(reset_n), .bridge_endian_little(1'b0),
        .bridge_addr(bridge_addr), .bridge_rd(bridge_rd), .bridge_rd_data(cmd_rd_data),
        .bridge_wr(bridge_wr), .bridge_wr_data(bridge_wr_data),
        .status_boot_done(1'b1), .status_setup_done(1'b1), .status_running(1'b1),
        .dataslot_requestread(d_rr), .dataslot_requestread_id(d_rr_id),
        .dataslot_requestread_ack(1'b1), .dataslot_requestread_ok(1'b1),
        .dataslot_requestwrite(d_rw), .dataslot_requestwrite_id(d_rw_id),
        .dataslot_requestwrite_size(d_rw_size),
        .dataslot_requestwrite_ack(1'b1), .dataslot_requestwrite_ok(1'b1),
        .dataslot_update(d_up), .dataslot_update_id(d_up_id), .dataslot_update_size(d_up_size),
        .dataslot_allcomplete(d_all),
        .rtc_epoch_seconds(rtc_e), .rtc_date_bcd(rtc_d), .rtc_time_bcd(rtc_t), .rtc_valid(rtc_valid),
        .savestate_supported(1'b1), .savestate_addr(32'h50000000),
        .savestate_size(32'd153600), .savestate_maxloadsize(32'd153600),
        .savestate_start(savestate_start), .savestate_start_ack(s_ack),
        .savestate_start_busy(s_busy), .savestate_start_ok(s_ok), .savestate_start_err(s_err),
        .savestate_load(savestate_load), .savestate_load_ack(l_ack),
        .savestate_load_busy(l_busy), .savestate_load_ok(l_ok), .savestate_load_err(l_err),
        .osnotify_inmenu(osnotify_inmenu),
        .target_dataslot_read(1'b0), .target_dataslot_write(1'b0),
        .target_dataslot_getfile(1'b0), .target_dataslot_openfile(1'b0),
        .target_dataslot_ack(t_ack), .target_dataslot_done(t_done), .target_dataslot_err(t_err),
        .target_dataslot_id(16'd0), .target_dataslot_slotoffset(32'd0),
        .target_dataslot_bridgeaddr(32'd0), .target_dataslot_length(32'd0),
        .target_buffer_param_struct(32'd0), .target_buffer_resp_struct(32'd0),
        .datatable_addr(10'd0), .datatable_wren(1'b0), .datatable_data(32'd0),
        .datatable_q(dt_q));

    // ------------------------------------------------------------ the core
    logic        treset = 1'b1, hold_req = 1'b1;
    logic        ld_wr = 1'b0;
    logic [27:0] ld_addr = 28'd0;
    logic [7:0]  ld_data = 8'd0;
    logic        len_valid = 1'b0;
    logic [31:0] cart_len = 32'd0, cfg_len = 32'd0;
    logic        cfg_inlist = 1'b0;
    logic [7:0]  pad_r = 8'hFF, pad_l = 8'hFF;
    logic [1:0]  ecs_ovr = 2'd2;          // +ecs (step 9): the menu's ECS override; Off by default
    logic [1:0]  voice_ovr = 2'd2;        // +voice (step 10): the menu's Intellivoice; Off by default
    logic        synth = 1'b0;
    /* verilator lint_off UNUSEDSIGNAL */
    wire logic        ecs_full;
    wire logic [11:0] slot_st;
    wire logic [1:0]  len_st;
    wire logic        ce_pix;
    wire logic [8:0]  hcnt, vline;
    wire logic [15:0] audio;
    wire logic        voice_on;
    /* verilator lint_on UNUSEDSIGNAL */
    wire logic        mreset, live;
    wire logic [8:0]  vcnt;
    wire logic [3:0]  colour;
    wire logic [16:0] sram_a;
    wire logic [15:0] sram_dq_out, sram_dq_in;
    wire logic        sram_dq_oe, sram_oe_n, sram_we_n, sram_ub_n, sram_lb_n;

    // +keys: the hand controllers' bytes by machine cycle
    int          nkeys = 0;
    longint      key_c[256];
    logic [15:0] key_v[256];
    logic [15:0] kpads;
    longint      cyc = -1;

    always_comb begin
        kpads = {pad_r, pad_l};
        for (int i = 0; i < nkeys; i++)
            if (cyc >= key_c[i]) kpads = key_v[i];
    end

    // +ekeys: the ECS keyboard's switches by machine cycle (step 9)
    int          nek = 0;
    longint      ek_c[512];
    logic [63:0] ek_v[512];
    logic [63:0] ekeys;
    always_comb begin
        ekeys = 64'd0;
        for (int i = 0; i < nek; i++)
            if (cyc >= ek_c[i]) ekeys = ek_v[i];
    end

    intv_core #(.CRC_HEX(`CRC_HEX), .LAYOUT_HEX(`LAYOUT_HEX)) core (
        .clk(clk), .timing_reset(treset), .hold_req(hold_req),
        .ld_wr(ld_wr), .ld_addr(ld_addr), .ld_data(ld_data), .len_valid(len_valid),
        .cart_len(cart_len), .len_chk(2'd0), .cfg_len(cfg_len), .cfg_inlist(cfg_inlist),
        .slot_st(slot_st), .len_st(len_st),
        .machine_reset(mreset), .cart_crc_o(), .cart_ready_o(), .pad_r(kpads[15:8]), .pad_l(kpads[7:0]),
        .ecs_override(ecs_ovr), .ecs_keys(ekeys), .ecs_synth(synth), .ecs_full(ecs_full),
        .voice_override(voice_ovr), .voice_dac7(1'b0), .voice_level(3'd4), .voice_on(voice_on), .ecs_level(3'd2),
        .ce_pix(ce_pix), .hcnt(hcnt), .vcnt(vcnt), .vline(vline), .live(live), .colour(colour),
        .audio(audio),
        .clk_74a(clk74), .bridge_addr(bridge_addr), .bridge_rd(bridge_rd), .bridge_wr(bridge_wr),
        .bridge_wr_data(bridge_wr_data), .ss_bridge_rd_data(ss_rd_data),
        .jlp_bridge_rd_data(jlp_rd_data), .jlp_sectors(),
        .tape_bridge_rd_data(), .tape_erase(1'b0),
        .savestate_start(savestate_start), .savestate_start_ack(s_ack),
        .savestate_start_busy(s_busy), .savestate_start_ok(s_ok), .savestate_start_err(s_err),
        .savestate_load(savestate_load), .savestate_load_ack(l_ack),
        .savestate_load_busy(l_busy), .savestate_load_ok(l_ok), .savestate_load_err(l_err),
        .osnotify_inmenu(osnotify_inmenu), .pause_en(pause_en),
        .sram_a(sram_a), .sram_dq_out(sram_dq_out), .sram_dq_oe(sram_dq_oe), .sram_dq_in(sram_dq_in),
        .sram_oe_n(sram_oe_n), .sram_we_n(sram_we_n), .sram_ub_n(sram_ub_n), .sram_lb_n(sram_lb_n));

    sram_as6c2016 sram (
        .clk, .a(sram_a), .dq_w(sram_dq_out), .dq_oe(sram_dq_oe), .dq_r(sram_dq_in),
        .oe_n(sram_oe_n), .we_n(sram_we_n), .ub_n(sram_ub_n), .lb_n(sram_lb_n));

    // ------------------------------------------------------------ logging
    int fd;
    int nfail = 0;
    task automatic fail(input string s);
        nfail++;
        $fdisplay(fd, "FAIL %s", s);
        $display("FAIL %s", s);
    endtask

    function automatic logic [31:0] fnv(input logic [31:0] h, input logic [31:0] x);
        fnv = (h ^ x) * 32'h01000193;
    endfunction

    wire logic ce_cpu = core.timing.ce_cpu;
    wire logic ce_stic = core.timing.ce_stic;
    wire logic hold = core.machine.hold;
    wire logic [2:0]  phase = core.machine.phase;
    wire logic [15:0] dout = core.machine.dout, din = core.machine.din, addr = core.machine.addr;

    logic [31:0] hb = 32'h811C9DC5, hs_ = 32'h811C9DC5, ha = 32'h811C9DC5, hq = 32'h811C9DC5;
    logic [31:0] hp = 32'h811C9DC5, hv = 32'h811C9DC5;   // hv, nv: the voice's samples (step 10)
    int          nb = 0, ns = 0, na = 0, nq = 0, np = 0, nv = 0;
    logic        set_req = 1'b0;          // the load's state is in: cycle := set_val
    longint      set_val = 0;

    always @(posedge clk) begin
        logic [15:0] ba, bd;
        if (set_req) begin
            cyc <= set_val;
            $fdisplay(fd, "R set cycle %0d", set_val);
            hb = 32'h811C9DC5; hs_ = 32'h811C9DC5; ha = 32'h811C9DC5; hq = 32'h811C9DC5;
            hp = 32'h811C9DC5; nb = 0; ns = 0; na = 0; nq = 0; np = 0; hv = 32'h811C9DC5; nv = 0;
        end else begin
            if (cyc >= 0 && core.machine.voice.c_done) begin
                hv = fnv(hv, 32'(core.machine.voice.c_sample));
                nv++;
            end
            if (ce_stic && live && cyc >= 0) begin
                hp = fnv(hp, {28'd0, colour});
                np++;
            end
            if (ce_cpu && !hold) begin
                ba = (phase == 3'd4 || phase == 3'd7) ? dout : (phase == 3'd2 ? 16'd0 : addr);
                bd = (phase == 3'd4 || phase == 3'd7) ? 16'd0 : (phase == 3'd5 || phase == 3'd6) ? dout : din;
                if (cyc >= 0 && phase != 3'd0) begin
                    hb = fnv(fnv(fnv(fnv(hb, 32'(cyc)), 32'(phase)), 32'(ba)), 32'(bd));
                    nb++;
                end
                if (cyc > 0 && (core.machine.fetch || phase == 3'd7)) begin
                    hs_ = fnv(hs_, 32'(cyc));
                    for (int i = 0; i < 8; i++) hs_ = fnv(hs_, 32'(core.machine.cpu.r[i]));
                    hs_ = fnv(hs_, 32'({core.machine.cpu.fS, core.machine.cpu.fZ, core.machine.cpu.fO,
                                        core.machine.cpu.fC, core.machine.cpu.fI, core.machine.cpu.fD}));
                    ns++;
                end
                if (cyc >= 0 && core.machine.psg.tick) begin
                    ha = fnv(ha, {20'd0, core.machine.psg.lv[2], core.machine.psg.lv[1], core.machine.psg.lv[0]});
                    na++;
                    if (core.machine.psg.srph_n >= 23'd3579545) begin
                        hq = fnv(hq, 32'(core.machine.psg.prod[31:16]));
                        nq++;
                    end
                end
                if (cyc >= 0 && (cyc + 1) % FRAME == 0) begin
                    $fdisplay(fd, "H %0d %08x %0d %08x %0d", cyc / FRAME, hb, nb, hs_, ns);
                    $fdisplay(fd, "A %0d %08x %0d %08x %0d %08x %0d", cyc / FRAME, ha, na, hq, nq, hv, nv);
                    $fdisplay(fd, "P %0d %08x %0d", cyc / FRAME, hp, np);
                    hb = 32'h811C9DC5; hs_ = 32'h811C9DC5; ha = 32'h811C9DC5; hq = 32'h811C9DC5;
                    hp = 32'h811C9DC5; nb = 0; ns = 0; na = 0; nq = 0; np = 0; hv = 32'h811C9DC5; nv = 0;
                end
                cyc <= cyc + 1;
            end
        end
    end

    // raster frames, and what ss_ctl sees
    longint rframes = 0;
    longint req_rf = 0, frz_rf = 0;
    logic   frz_q = 1'b0, st_q = 1'b0, ld_q = 1'b0, run_q = 1'b1, vwait_q = 1'b0;
    longint rcyc_next = -1;
    always @(posedge clk) begin
        if (core.timing.vcnt == 9'd0 && core.timing.hcnt == 9'd0 && core.timing.sub == 4'd0)
            rframes <= rframes + 1;
        st_q <= core.ssc.start_lv;
        ld_q <= core.ssc.load_lv;
        if ((core.ssc.start_lv && !st_q) || (core.ssc.load_lv && !ld_q)) begin
            req_rf <= rframes;
            $fdisplay(fd, "Q %0s %0d busak %0d cp_on %0d fetch %0d lv %0d vcnt %0d vbusy %0d",
                      (core.ssc.start_lv && !st_q) ? "save" : "load", cyc, core.machine.busak,
                      core.machine.stic.cp_on, core.machine.fetch,
                      core.machine.psg.lv[0] | core.machine.psg.lv[1] | core.machine.psg.lv[2], vcnt,
                      core.machine.voice_busy);
        end
        // the freeze must not begin inside a voice sample (its making is not in the state);
        // VWAIT: a request held back by the voice alone (every other quiet term true)
        run_q <= core.ssc.run;
        if (core.ssc.run && core.ssc.want && core.machine.voice_busy && !vwait_q && core.ssc.live
            && !core.ssc.mreset && core.ssc.vcnt < 9'(core.ssc.V_QUIET) && !core.ssc.ce_cpu
            && (core.ssc.cpu_fetch || core.ssc.cpu_halted || core.ssc.cpu_hold)) begin
            vwait_q <= 1'b1;
            $fdisplay(fd, "VWAIT %0d", cyc);
        end
        if (!core.ssc.want) vwait_q <= 1'b0;
        if (run_q && !core.ssc.run && core.machine.voice_busy)
            $fdisplay(fd, "FRZBUSY %0d", cyc);
        frz_q <= core.ssc.frozen;
        if (core.ssc.frozen && !frz_q) begin
            cram_hash("M");
            bank_hash("K");
            frz_rf <= rframes;
            $fdisplay(fd, "Z %0d %06x %04x %04x %04x %04x %04x %04x %04x %04x %0d", cyc, core.timing.mpos,
                      core.machine.cpu.r[0], core.machine.cpu.r[1], core.machine.cpu.r[2],
                      core.machine.cpu.r[3], core.machine.cpu.r[4], core.machine.cpu.r[5],
                      core.machine.cpu.r[6], core.machine.cpu.r[7], rframes - req_rf);
        end
        if (!core.ssc.frozen && frz_q)
            $fdisplay(fd, "U %0d %0d", cyc, rframes - frz_rf);
        // a load's state is in (the machine still frozen): ld_applied, at
        // once for a load out of reset, after the reset exit for one staged
        set_req <= 1'b0;
        if (core.ssc.ld_applied) begin
            cram_hash("MA");
            bank_hash("KA");
            jram_hash("JA");
            if (rcyc_next >= 0) begin
                set_val <= rcyc_next;
                set_req <= 1'b1;
                rcyc_next = -1;
            end
            if (core.ssc.run) fail("load done while the machine runs");
        end
        if (core.ssc.ss_en && core.ssc.run)
            fail("ss_en while the machine runs");
        if (core.ssc.frozen && live)
            fail("live while frozen");
        // the sound while the machine is not live
        if (!live) begin
            nl_clk <= nl_clk + 1;
            if (audio == 16'd0 && nl_zero < 0) nl_zero <= nl_clk;
            if (audio != 16'd0) nl_zero <= -1;
            if (nl_clk >= 64'd171818 && audio != 16'd0 && !nl_fail) begin
                nl_fail <= 1'b1;
                fail($sformatf("sound %04x after 4 ms not live (cycle %0d)", audio, cyc));
            end
        end else begin
            if (nl_clk >= 64'd100000)
                $fdisplay(fd, "D %0d %0d", nl_clk, nl_zero);
            nl_clk <= 0;
            nl_zero <= -1;
            nl_fail <= 1'b0;
        end
    end

    longint nl_clk = 0, nl_zero = -1;
    logic   nl_fail = 1'b0;

    task automatic cram_hash(input string tag);
        logic [31:0] h;
        int nz;
        h = 32'h811C9DC5;
        nz = 0;
        for (int i = 0; i < 16384; i++) begin
            h = fnv(h, {16'd0, sram.mem[17'h18000 + 17'(i)]});
            if (sram.mem[17'h18000 + 17'(i)] != 16'd0) nz++;
        end
        $fdisplay(fd, "%s %0d %08x %0d", tag, cyc, h, nz);
    endtask

    // the JLP RAM region (version 5): its 8,000 cells in the SRAM at JLP_BASE, hashed as the
    // blob's (tb_savestate.py checks the JA line after every load against the blob's cells)
    task automatic jram_hash(input string tag);
        logic [31:0] h;
        h = 32'h811C9DC5;
        for (int i = 0; i < 8000; i++) h = fnv(h, {16'd0, sram.mem[17'h1C000 + 17'(i)]});
        $fdisplay(fd, "%s %0d %08x", tag, cyc, h);
    endtask

    task automatic bank_hash(input string tag);
        logic [31:0] h;
        h = 32'h811C9DC5;
        for (int i = 0; i < 32; i++) h = fnv(h, {24'd0, core.media.cart.bank[i]});
        $fdisplay(fd, "%s %0d %08x", tag, cyc, h);
    endtask

    // ------------------------------------------------------------ bridge
    task automatic br_wr(input logic [31:0] a, input logic [31:0] d);
        @(negedge clk74);
        bridge_addr = a;
        bridge_wr_data = d;
        @(negedge clk74);
        bridge_wr = 1'b1;
        @(negedge clk74);
        bridge_wr = 1'b0;
        repeat (85) @(negedge clk74);
    endtask

    task automatic br_rd(input logic [31:0] a, output logic [31:0] d);
        @(negedge clk74);
        bridge_addr = a;
        @(negedge clk74);
        bridge_rd = 1'b1;
        @(negedge clk74);
        bridge_rd = 1'b0;
        repeat (84) @(negedge clk74);
        d = bridge_rd_data;
        @(negedge clk74);
    endtask

    // a host command: parameter word, command, poll for "OK" + code
    task automatic host_cmd(input logic [15:0] cmd, input logic [31:0] par, output logic [15:0] code);
        logic [31:0] v;
        int n;
        br_wr(32'hF8000020, par);
        br_wr(32'hF8000000, {16'h434D, cmd});
        n = 0;
        do begin
            br_rd(32'hF8000000, v);
            n++;
        end while (v[31:16] != 16'h4F4B && n < 1000);
        if (n >= 1000) fail($sformatf("command %04x: no OK (%08x)", cmd, v));
        code = v[15:0];
    endtask

    // the result of a save or load: poll the command without bit 0
    task automatic host_result(input logic [15:0] cmd, output logic [15:0] code, output int polls);
        polls = 0;
        do begin
            host_cmd(cmd, 32'd0, code);
            polls++;
            repeat (2000) @(negedge clk74);
        end while ((code == 16'd1 || code == 16'd0) && polls < 3000);
    endtask

    // (fails if the machine stops counting for 300 raster frames)
    task automatic wait_cyc(input longint c);
        longint last, idle;
        last = cyc;
        idle = 0;
        while (cyc < c && idle < 300 * 262 * 228 * 12) begin
            @(negedge clk);
            if (cyc != last) begin last = cyc; idle = 0; end else idle++;
        end
        if (cyc < c) fail($sformatf("cycle %0d never reached (%0d)", c, cyc));
    endtask

    task automatic wait_frames(input longint f);
        longint r0;
        r0 = rframes;
        while (rframes < r0 + f) @(negedge clk);
    endtask

    // the moments a save is asked for, at the start of a stretch that lasts
    // well beyond the ~10 clk_sys the request takes to reach ss_ctl. sound:
    // the clk after a PSG tick, when the levels the tick set are in (they hold
    // until the next tick, 4 CPU cycles on); at the tick itself they are the
    // old ones, and a tone's square wave can take a nonzero level to 0 there
    logic ce_fired = 1'b0, cp_q = 1'b0, tick_fired = 1'b0;
    always @(posedge clk) begin
        ce_fired <= ce_cpu;
        cp_q <= core.machine.stic.cp_on;
        tick_fired <= core.machine.psg.tick;
    end
    function automatic bit kind_ok(input string kind);
        case (kind)
            "midinst":  return ce_fired && !core.machine.fetch && !hold && phase != 3'd4;
            "busrq":    return core.machine.busak;
            "rowfetch": return core.machine.stic.cp_on && !cp_q;
            // in VBlank (the quiet point's vcnt < V_QUIET, with a margin), two cycles before the
            // voice's next sample: the request takes about three cycles to reach intv_ss_ctl, so
            // it is there while the sample is made, and a quiet point that does not wait for the
            // voice freezes inside it (ss_voice_busy_ignored; VWAIT below shows the wait)
            "voice":    return core.machine.voice.on && core.machine.voice.started && core.ssc.vcnt < 9'd50
                               && 33'(core.machine.voice.acc) + 33'(2 * core.machine.voice.INC) >= 33'(core.machine.voice.WRAP)
                               && 33'(core.machine.voice.acc) + 33'(core.machine.voice.INC) < 33'(core.machine.voice.WRAP);
            "voicewin": return core.machine.voice.win != 4'd0;
            "sound":    return tick_fired && (core.machine.psg.lv[0] != 4'd0
                               || core.machine.psg.lv[1] != 4'd0 || core.machine.psg.lv[2] != 4'd0);
            default:    return 1'b1;
        endcase
    endfunction

    logic [7:0] blob [153600];

    // the JLP's flash store (build step 11) is not machine state: a state load keeps the flash
    // (JLP_NOTES 5.2). A blob is written with the store as it was at the save's freeze
    // (FILE.flash, $writememh) and a load puts that store back first, so a load into a core
    // whose flash moved on (a fresh core, D's) compares with the straight run
    logic [15:0]  fl_snap [12288];
    logic [127:0] fe_snap;
    logic [127:0] fe_arr [1];
    bit           fl_took;

    task automatic do_save(input longint c, input string kind, input string fname, input bit burst = 1'b0);
        logic [15:0] code;
        logic [31:0] v;
        int polls, f, n;
        wait_cyc(c);
        fl_took = 1'b0;
        fork begin
            int k;
            k = 0;
            while (!core.ssc.ss_en && k < 40 * 14934 * 48) begin @(negedge clk); k++; end
            for (int i = 0; i < 12288; i++) fl_snap[i] = core.machine.jlp.flash.store[i];
            fe_snap = core.machine.jlp.empt;
            fl_took = 1'b1;
        end join_none
        host_on();
        br_wr(32'hF8000020, 32'd1);
        // the command word set up, then its write strobe at the moment
        @(negedge clk74);
        bridge_addr = 32'hF8000000;
        bridge_wr_data = {16'h434D, 16'h00A0};
        n = 0;
        while (!kind_ok(kind) && n < 30 * 14934 * 48) begin @(negedge clk); n++; end
        if (!kind_ok(kind)) $fdisplay(fd, "R kind %s not found by cycle %0d", kind, cyc);
        @(negedge clk74);
        bridge_wr = 1'b1;
        @(negedge clk74);
        bridge_wr = 1'b0;
        repeat (85) @(negedge clk74);
        n = 0;
        do begin br_rd(32'hF8000000, v); n++; end while (v[31:16] != 16'h4F4B && n < 1000);
        $fdisplay(fd, "S %0d save start (kind %s)", v[15:0], kind);
        if (burst) begin                      // two blob reads while the state is read
            n = 0;
            while (!core.ssc.ss_en && n < 40 * 14934 * 12) begin @(negedge clk); n++; end
            br_rd(32'h50000000, v);
            br_rd(32'h50000004, v);
            $fdisplay(fd, "R burst at cycle %0d, ss_en %0d", cyc, core.ssc.ss_en);
        end
        host_result(16'h00A0, code, polls);
        $fdisplay(fd, "S %0d save after %0d polls", code, polls);
        if (code != 16'd2) begin
            $fdisplay(fd, "SAVE err %0d", cyc);
            host_off();
            return;
        end
        for (int i = 0; i < 38400; i++) begin
            br_rd(32'h50000000 + 32'(4 * i), v);
            {blob[4*i], blob[4*i+1], blob[4*i+2], blob[4*i+3]} = v;
        end
        host_off();
        f = $fopen(fname, "wb");
        if (f == 0) begin fail($sformatf("cannot write %s", fname)); return; end
        for (int i = 0; i < 153600; i++) $fwrite(f, "%c", blob[i]);
        $fclose(f);
        if (!fl_took) fail($sformatf("%s: the flash store was not taken at the freeze", fname));
        $writememh({fname, ".flash"}, fl_snap);
        fe_arr[0] = fe_snap;
        $writememh({fname, ".empt"}, fe_arr);
        $fdisplay(fd, "SAVE ok %0d %s", cyc, fname);
    endtask

    // race: ss_ctl latches an access's direction when it takes it (cur_we),
    // so a write that arrives while a read is being served neither drops
    // the read's answer nor answers itself. Word RACE_W is read; the write
    // to RACE_W + 1 is strobed d = 0..5 clk_sys after the read's SRAM access
    // starts (it reaches ss_ctl about 5 clk_sys later; the read's two SRAM
    // accesses take about 10). race_hits counts the writes taken in while a
    // read was in flight (the case that needs the latch).
    localparam int RACE_W = 40;
    int   race_hits = 0;
    logic race_on = 1'b0;
    always @(posedge clk)
        if (race_on && core.ssc.b_s[2] != core.ssc.b_s[1] && int'(core.ssc.mst) != 0 && !core.ssc.cur_we)
            race_hits <= race_hits + 1;

    task automatic do_race(input longint c);
        logic [31:0] v, want_r, want_w;
        int n, h0, wrong;
        wait_cyc(c);
        host_on();
        race_on = 1'b1;
        wrong = 0;
        for (int d = 0; d < 6; d++) begin
            want_r = 32'hA5C30000 | 32'(d);
            want_w = 32'h3C5A0000 | 32'(d);
            br_wr(32'h50000000 + 32'(4 * RACE_W), want_r);
            br_wr(32'h50000000 + 32'(4 * (RACE_W + 1)), ~want_w);
            br_rd(32'h50000000 + 32'(4 * (RACE_W + 1)), v);   // the bridge's word: ~want_w
            h0 = race_hits;
            @(negedge clk74);
            bridge_addr = 32'h50000000 + 32'(4 * RACE_W);
            @(negedge clk74);
            bridge_rd = 1'b1;
            @(negedge clk74);
            bridge_rd = 1'b0;
            n = 0;
            while (int'(core.ssc.mst) == 0 && n < 4000) begin @(negedge clk); n++; end
            repeat (d) @(negedge clk);
            @(negedge clk74);
            bridge_addr = 32'h50000000 + 32'(4 * (RACE_W + 1));
            bridge_wr_data = want_w;
            bridge_wr = 1'b1;
            @(negedge clk74);
            bridge_wr = 1'b0;
            repeat (85) @(negedge clk74);
            v = bridge_rd_data;
            if (v != want_r) begin
                wrong++;
                fail($sformatf("race %0d: the read answered %08x, want %08x", d, v, want_r));
            end
            br_rd(32'h50000000 + 32'(4 * (RACE_W + 1)), v);
            if (v != want_w) begin
                wrong++;
                fail($sformatf("race %0d: the written word reads %08x, want %08x", d, v, want_w));
            end
            $fdisplay(fd, "R race %0d hit %0d", d, race_hits - h0);
        end
        race_on = 1'b0;
        $fdisplay(fd, "RW %0d %0d", race_hits, wrong);
        host_off();
    endtask

    task automatic do_load(input longint c, input string fname, input string expect_s, input longint r,
                           input bit rel_reset = 1'b0);
        logic [15:0] code;
        int polls, f, ch;
        if (c >= 0) wait_cyc(c);
        f = $fopen(fname, "rb");
        if (f == 0) begin fail($sformatf("cannot read %s", fname)); return; end
        for (int i = 0; i < 153600; i++) begin
            ch = $fgetc(f);
            blob[i] = ch < 0 ? 8'd0 : 8'(ch);
        end
        $fclose(f);
        f = $fopen({fname, ".flash"}, "r");
        if (f != 0) $fclose(f);
        if (f != 0 && expect_s == "ok") begin       // (a load meant to be refused keeps the flash)
            logic [127:0] fe [1];
            $readmemh({fname, ".flash"}, fl_snap);
            $readmemh({fname, ".empt"}, fe);
            for (int i = 0; i < 12288; i++) core.machine.jlp.flash.store[i] = fl_snap[i];
            core.machine.jlp.empt = fe[0];
        end
        host_on();
        for (int i = 0; i < 38400; i++)
            br_wr(32'h50000000 + 32'(4 * i), {blob[4*i], blob[4*i+1], blob[4*i+2], blob[4*i+3]});
        rcyc_next = r;
        host_cmd(16'h00A4, 32'd1, code);
        $fdisplay(fd, "S %0d load start", code);
        if (rel_reset)
            fork begin
                int k;
                k = 0;
                while (!core.ssc.staged && k < 4000000) begin @(negedge clk); k++; end
                $fdisplay(fd, "R reset released, staged %0d", core.ssc.staged);
                hold_req = 1'b0;
            end join_none
        host_result(16'h00A4, code, polls);
        $fdisplay(fd, "S %0d load after %0d polls", code, polls);
        if (code != 16'd2) rcyc_next = -1;    // else the state's arrival takes it
        host_off();
        if (code == 16'd2)      $fdisplay(fd, "LOAD ok EXPECT %s", expect_s);
        else if (code == 16'd3) $fdisplay(fd, "LOAD err EXPECT %s", expect_s);
        else                    $fdisplay(fd, "LOAD other EXPECT %s", expect_s);
        if ((code == 16'd2) != (expect_s == "ok") || (code != 16'd2 && code != 16'd3))
            fail($sformatf("load %s: code %0d, expected %s", fname, code, expect_s));
    endtask

    task automatic do_menu(input longint c, input int open);
        logic [15:0] code;
        wait_cyc(c);
        if (open != 0) $fdisplay(fd, "MENU open %0d", cyc);
        host_on();
        host_cmd(16'h00B0, 32'(open), code);
        host_off();
        if (open == 0) $fdisplay(fd, "MENU 0 %0d", cyc);
    endtask

    // ------------------------------------------------------------ loading
    task automatic load_file(input string path, input logic [3:0] slot, output int n);
        int f, c;
        n = 0;
        f = $fopen(path, "rb");
        if (f == 0) begin fail($sformatf("cannot open %s", path)); return; end
        while (1) begin
            c = $fgetc(f);
            if (c < 0) break;
            @(negedge clk);
            ld_wr = 1'b1; ld_addr = {slot, 24'(n)}; ld_data = 8'(c);
            @(negedge clk);
            ld_wr = 1'b0;
            repeat (4) @(negedge clk);
            n++;
        end
        $fclose(f);
    endtask

    // ------------------------------------------------------------ the run
    string exec_f, grom_f, cart_f, cfg_f, log_f, script_f;
    int    hold_on = 0;
    logic  rst_v = 1'b0;                      // the script's "reset V D" (one at a time)
    int    rst_d = 0;
    longint ncyc = 10 * FRAME;

    initial begin
        int n, to, sf, p;
        if (!$value$plusargs("log=%s", log_f)) log_f = "tb_savestate.log";
        fd = $fopen(log_f, "w");
        void'($value$plusargs("cycles=%d", ncyc));
        if ($value$plusargs("pause=%d", p)) pause_en = p != 0;
        if (!$value$plusargs("hold=%d", hold_on)) hold_on = 0;
        begin
            logic [15:0] pads;
            string keys_f;
            if ($value$plusargs("pads=%h", pads)) {pad_r, pad_l} = pads;
            if ($value$plusargs("keys=%s", keys_f)) begin
                int     kf;
                longint k;
                logic [15:0] v;
                kf = $fopen(keys_f, "r");
                if (kf == 0) fail($sformatf("cannot open %s", keys_f));
                while (kf != 0 && nkeys < 256 && $fscanf(kf, "%d %h", k, v) == 2) begin
                    key_c[nkeys] = k * FRAME;
                    key_v[nkeys] = v;
                    nkeys++;
                end
                if (kf != 0) $fclose(kf);
            end
            if ($value$plusargs("ekeys=%s", keys_f)) begin
                int     kf;
                longint k;
                logic [63:0] v;
                kf = $fopen(keys_f, "r");
                if (kf == 0) fail($sformatf("cannot open %s", keys_f));
                while (kf != 0 && nek < 512 && $fscanf(kf, "%d %h", k, v) == 2) begin
                    ek_c[nek] = k * FRAME;
                    ek_v[nek] = v;
                    nek++;
                end
                if (kf != 0) $fclose(kf);
            end
            if ($value$plusargs("ecs=%d", p)) ecs_ovr = 2'(p);
            if ($value$plusargs("synth=%d", p)) synth = p != 0;
            if ($value$plusargs("voice=%d", p)) voice_ovr = 2'(p);
        end
        if (!$value$plusargs("exec=%s", exec_f) || !$value$plusargs("grom=%s", grom_f))
            fail("give +exec= and +grom=");
        repeat (8) @(negedge clk);
        treset = 1'b0;
        repeat (8) @(negedge clk);
        load_file(exec_f, 4'd2, n);
        load_file(grom_f, 4'd3, n);
        begin
            string ecs_f;
            if ($value$plusargs("ecsrom=%s", ecs_f)) load_file(ecs_f, 4'd4, n);
            if ($value$plusargs("ivoice=%s", ecs_f)) load_file(ecs_f, 4'd5, n);
        end
        n = 0;
        if ($value$plusargs("cart=%s", cart_f)) load_file(cart_f, 4'd0, n);
        $fdisplay(fd, "L cart %0d", n);
        cart_len = n;
        if ($value$plusargs("cfg=%s", cfg_f)) begin    // build step 8: the CFG slot
            load_file(cfg_f, 4'd1, n);
            cfg_len = n; cfg_inlist = 1'b1;
        end
        // the JLP flash slot (build step 11): +jlpsav=F written at 0x20000000 as the Pocket does
        // when it loads a game's .sav: with the other slots, before "all complete" (the data
        // table's len_valid). (Until 2026-11-03 the bench wrote it after the load had finished;
        // the owner's 0.0.21 test 4 showed the Pocket's order, where the load's erase lost it.)
        begin
            string jf;
            int    f, ch;
            logic [7:0] bb [4];
            if ($value$plusargs("jlpsav=%s", jf)) begin
                f = $fopen(jf, "rb");
                if (f == 0) fail($sformatf("cannot read %s", jf));
                host_on();
                for (int i = 0; f != 0 && i < 6144; i++) begin
                    for (int k = 0; k < 4; k++) begin ch = $fgetc(f); bb[k] = ch < 0 ? 8'hFF : 8'(ch); end
                    if (ch < 0 && i > 0) break;
                    br_wr(32'h20000000 + 32'(4 * i), {bb[0], bb[1], bb[2], bb[3]});
                end
                host_off();
                if (f != 0) $fclose(f);
                $fdisplay(fd, "R jlp slot written from %s", jf);
            end
        end
        @(negedge clk);
        len_valid = 1'b1;
        repeat (64) @(negedge clk);           // the loader takes len_valid (synchronised) first
        to = 0;
        while (!(core.media.ready && !core.media.busy) && to < 4000000) begin @(negedge clk); to++; end
        if (to >= 4000000) fail("loader not ready");
        repeat (8) @(negedge clk);            // the results reach intv_cart's registers
        $fdisplay(fd, "L ready crc %08x words %0d", core.media.crc, core.media.words);
        $fdisplay(fd, "L ecs mode %0d", core.ecs_mode);
        $fdisplay(fd, "L voice mode %0d", core.voice_mode);
        repeat (10) @(negedge clk);
        if (hold_on == 0) hold_req = 1'b0;

        if ($value$plusargs("script=%s", script_f)) begin
            string cmd, a1, a2;
            longint c, r;
            int k;
            sf = $fopen(script_f, "r");
            if (sf == 0) fail($sformatf("cannot open %s", script_f));
            while (sf != 0 && $fscanf(sf, "%s", cmd) == 1) begin
                case (cmd)
                    "save": begin
                        k = $fscanf(sf, "%d %s %s", c, a1, a2);
                        do_save(c, a1, a2);
                    end
                    "saveb": begin
                        k = $fscanf(sf, "%d %s", c, a2);
                        do_save(c, "any", a2, 1'b1);
                    end
                    "race": begin
                        k = $fscanf(sf, "%d", c);
                        do_race(c);
                    end
                    "load", "loadr": begin
                        k = $fscanf(sf, "%d %s %s %d", c, a1, a2, r);
                        do_load(c, a1, a2, r, cmd == "loadr");
                    end
                    "reset": begin
                        k = $fscanf(sf, "%d %d", r, c);
                        rst_v = r != 0;
                        rst_d = 32'(c);
                        fork
                            begin
                                repeat (rst_d) @(negedge clk);
                                hold_req = rst_v;
                                $fdisplay(fd, "R reset %0d at cycle %0d", rst_v, cyc);
                            end
                        join_none
                    end
                    "menu": begin
                        k = $fscanf(sf, "%d %d", c, r);
                        do_menu(c, int'(r));
                    end
                    "wait": begin
                        longint c0;
                        k = $fscanf(sf, "%d", r);
                        c0 = cyc;
                        wait_frames(r);
                        $fdisplay(fd, "W %0d %0d %0d", r, c0, cyc);
                    end
                    default: fail($sformatf("script: %s", cmd));
                endcase
            end
            if (sf != 0) $fclose(sf);
        end

        wait_cyc(ncyc);
        // the JLP flash slot read back as the Pocket saves it (+jlpout=F, +jlpbytes=N), and the
        // JLP cartridges' results ($0300 on, $0351 counts them: sim/testroms/jlp)
        begin
            string jf;
            int    f, nb;
            logic [31:0] v;
            if ($value$plusargs("jlpout=%s", jf) && $value$plusargs("jlpbytes=%d", nb)) begin
                f = $fopen(jf, "wb");
                host_on();
                for (int i = 0; i < nb / 4; i++) begin
                    br_rd(32'h20000000 + 32'(4 * i), v);
                    $fwrite(f, "%c%c%c%c", v[31:24], v[23:16], v[15:8], v[7:0]);
                end
                host_off();
                $fclose(f);
                for (int k = 0; k < int'(core.machine.sysram.mem[16'h151]) && k < 64; k++)
                    $fdisplay(fd, "J %0d %04x", k, core.machine.sysram.mem[16'h100 + k]);
            end
        end
        $fdisplay(fd, "E drops %0d", core.ssc.br_drops);
        if (nfail == 0) $fdisplay(fd, "END");
        else $fdisplay(fd, "END with failures");
        $fclose(fd);
        $finish;
    end

endmodule

`default_nettype wire
