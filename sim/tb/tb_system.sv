// Step 3-6 bench (DESIGN.md 9): the machine (intv_machine: CP1610, bus
// fabric, RAMs, the STIC, the PSG) with the real timing
// (intv_timing) and cartridge side (intv_media and our SRAM model), running
// the EXEC with or without a cartridge. The bench writes what the bus does,
// what the STIC fetches and the pictures it draws; sim/tb/tb_system.py
// compares them with tools/intv_system.py cycle by cycle and pixel by pixel.
//
// Plusargs
//   +exec=F +grom=F     the system ROM files (loaded through intv_media's
//                       byte port as the data slots 2 and 3 would)
//   +cart=F             a cartridge image (slot 0); without it, no cartridge
//   +cycles=N           run N CPU cycles from the first fetch (model cycle 0)
//   +pads=RRLL          the hand controllers' bytes at $01FE (right) and
//                       $01FF (left), hex (default FFFF: nothing pressed)
//   +keys=F             scripted hand controllers (tb_system.py --play):
//                       lines "k RRLL", both bytes from frame k on (model
//                       cycle k x FRAME) until the next line; +pads before
//                       the first
//   +ecs=N              the ECS (build step 9): the menu's override, 0 Auto
//                       (intv_media's rule), 1 On, 2 Off (the default: the
//                       benches of steps 3-8 run without the ECS)
//   +ecsrom=F           ECS.bin, loaded as the ECS ROM slot (4)
//   +ekeys=F            scripted ECS keyboard: lines "k K", the pressed
//                       switches K (hex, bit 8 row + column) from frame k on
//   +synth=1            the music synthesizer instead of the keyboard
//   +voice=N            the Intellivoice (step 10) as the menu's: 0 Auto, 1 On,
//                       2 Off (default); +ivoice=F its ROM (slot 5); +vlevel=N
//                       (0-4, default 4) +vdac=1 (the chip's 7-bit DAC sound)
//   +elevel=N           the ECS level (PSG #2 only: 0-4, default 2, the menu's)
//   +log=F              the output (below)
//   +busrq=0            BUSRQ off (the step-3 system; model mode "none")
//   +pic=F              write every picture to F (binary, see below)
//   +bushash=1          instead of B and S lines, one H line a frame with
//                       a hash of them (long runs; no round trips)
//   +dump=C             also freeze after cycle C-1 and dump every state
//                       word (then run on)
//   +rt=M +rtcyc=C +rtsub=K [+rton=R]
//                       save/restore round trip (DESIGN 8.4): after cycle
//                       C-1 and K more clk_sys, freeze the machine (timing
//                       run = 0) and read every state word of every module.
//                       M=1: reset the machine; M=2: run on for R more
//                       cycles, freeze again. Either way then write junk
//                       straight into the RAM arrays and through the state
//                       port into every word (a reset keeps RAM contents, so
//                       without it a RAM that loses its restore writes would
//                       not show). Then write the saved words back, read them back
//                       (must be equal) and run on; with M=2 the run goes
//                       back to cycle C ("R rewind C"). The raster runs
//                       through it all: the machine resumes when the raster
//                       comes round to its saved position. With a
//                       cartridge, the 16K cart RAM cells in the SRAM go
//                       the same way through intv_media's aux port (what
//                       ss_ctl does at step 7, DESIGN 4.3).
//
// Log lines (cycles are model cycles: 0 = the first fetch, after the reset
// IAB; the bench counts CPU ce's)
//   B c ph a d          a bus phase other than NACT: BAR, INTAK a = dout;
//                       DTB, ADAR a = latched address, d = din; DW, DWS a =
//                       latched address, d = dout; IAB d = din
//   S c r0 .. r7 f      a step starts (opcode fetch or INTAK): registers and
//                       {S,Z,O,C,I,D} in that cycle
//   G c r ok a          row fetch r decided in cycle c (the fetch cycle):
//                       ok = loaded, a = the FIFO address counter
//   GW c w0 .. w19      the row just loaded (BACKTAB words)
//   C c r col k base    the card engine at the first line of card row r:
//                       k 0 GROM, 1 GRAM (base = card address), 2 squares
//   K c b0 .. b7        the frame's end (cycle c): the collision bits the
//                       frame gathered for MOBs 0-7 (hex; ORed into
//                       $18-$1F now)
//   A k ha na hq nq     the end of frame k: the PSG's steps in it (na, FNV-1a
//                       ha over each step's three levels before it, A | B
//                       << 4 | C << 8: the filter's input) and its 48 kHz
//                       samples (nq, hash hq); a rewind (+rt=2) restores
//                       the sums of the mark, and the last line of a frame
//                       counts
//   E k ha nb hq nq hm  the end of frame k: PSG #2 (the ECS) as the A line
//                       has PSG #1, and hm: FNV-1a over every 48 kHz sample
//                       of the machine's mixed sound (PSG #1 + #2, at most
//                       32,767; intv_machine audio at audio_stb), a step
//                       at cycle c counting in frame (c + 1) / FRAME
//   H k hb nb hs ns     +bushash: frame k's B lines (hb, count nb) and S
//                       lines (hs, ns), FNV-1a over 32-bit words: B c ph a
//                       d, S c r0 .. r7 f; S lines of cycle 0 are left out
//   M c hs cs           the STIC's handshake or mode latch (csmode) changed:
//                       their values during cycle c (also once after a
//                       restore; the reader drops repeats)
//   L ...               load results;  R ...  round-trip notes ("R mark":
//                       the state is saved here; lines from here to "R
//                       rewind" belong to the run that is rewound)
//   W k id w value      every state word at a dump (k = 1: +dump, 2: the
//                       end, frozen after cycle N-1)
//   END / FAIL text
// Pictures (+pic): picture n (the model's numbering: frame n - 1's display)
// is 189 x 240 STIC colours, raster lines 46-261 of frame n - 1 and 0-23
// of frame n, pixel clocks 24-212 (tools/stic.py); each record is the
// 32-bit number n, then 5,670 32-bit words of eight 4-bit pixels (pixel
// 8i + j in bits 4j+3:4j), all as $fwrite %u writes them. After a rewind
// (+rt=2) the frames from the rewind on are written again; the last record
// of a number counts.
//
// SPDX-License-Identifier: MIT

`timescale 1ns / 1ps
`default_nettype none

module tb_system;

    localparam logic [2:0] PH_NACT = 3'd0, PH_INTAK = 3'd7;

    logic clk = 1'b0;
    always #5 clk = ~clk;

    // ------------------------------------------------------------ the DUT
    logic        reset = 1'b1;            // power-on (timing, media)
    logic        run = 1'b1;
    logic        mres_tb = 1'b1;
    logic        ld_wr = 1'b0;
    logic [27:0] ld_addr = 28'd0;
    logic [7:0]  ld_data = 8'd0;
    logic        len_valid = 1'b0;
    logic [31:0] cart_len = 32'd0, cfg_len = 32'd0;
    logic        cfg_inlist = 1'b0;
    logic        ss_en = 1'b0;
    logic [7:0]  pad_r = 8'hFF, pad_l = 8'hFF;
    logic [1:0]  ecs_ovr = 2'd2;
    logic        synth = 1'b0;
    logic        aux_req = 1'b0, aux_we = 1'b0;
    logic [16:0] aux_addr = 17'd0;
    logic [15:0] aux_wdata = 16'd0;
    logic [15:0] ss_addr = 16'd0;
    logic        ss_we = 1'b0;
    logic [31:0] ss_wdata = 32'd0;

    wire logic        ce_pix, live, ce_stic, ce_psg, ce_cpu;
    wire logic [8:0]  hcnt, vcnt, vline;
    wire logic [31:0] ssr_t, ssr_m, ssr_c;

    intv_timing timing (
        .clk, .reset, .run, .ce_pix, .hcnt, .vcnt, .vline, .live, .ce_stic,
        .ce_psg, .ce_cpu, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_t));

    wire logic        ready, busy, hit, noss;
    wire logic [5:0]  err;
    wire logic [7:0]  fmt_err;
    wire logic [31:0] cfg_crc;
    wire logic [63:0] pg_sel;
    wire logic [11:0] slot_st;
    wire logic [31:0] crc;
    wire logic [16:0] words;
    wire logic [7:0]  layout, flags;
    wire logic        c_req, c_we, c_ack, c_hit, c_paged;
    wire logic [15:0] c_addr, c_wdata, c_rdata;
    wire logic [3:0]  c_attr;
    wire logic        aux_ack;
    wire logic [15:0] aux_rdata;
    wire logic [11:0] exec_addr;
    wire logic [10:0] grom_addr, vgrom_addr;
    wire logic [9:0]  exec_q;
    wire logic [7:0]  grom_q, vgrom_q, ivoice_q;
    wire logic [16:0] sram_a;
    wire logic [15:0] sram_dq_out, sram_dq_in;
    wire logic        sram_dq_oe, sram_oe_n, sram_we_n, sram_ub_n, sram_lb_n;
    wire logic        mreset = mres_tb || !ready;
    wire logic        ecs_on, ecs_rom_ok;
    wire logic        efull;            // intv_ecs: mode on (intv_input's key routing, step-9 review)
    wire logic [11:0] ecs_pg;
    wire logic [1:0]  ecs_auto;
    wire logic [1:0]  ecs_mode = ecs_ovr == 2'd1 ? 2'd1 : ecs_ovr == 2'd2 ? 2'd0 : ecs_auto;
    // the Intellivoice (step 10): intv_core's rule (On, or Auto and the cartridge's flag; never
    // without its ROM slot)
    logic [1:0]       voice_ovr = 2'd2;
    logic             vdac = 1'b0;
    logic [2:0]       vlevel = 3'd4;
    logic [2:0]       elevel = 3'd2;
    wire logic [10:0] iv_addr;
    wire logic        voice_auto;
    wire logic        voice_mode = voice_ovr == 2'd1 ? slot_st[11:10] == 2'd2 : voice_ovr == 2'd0 && voice_auto;
    wire logic        voice_on, voice_busy, voice_late;
    // the JLP (build step 11): the loader's mode and sectors, its RAM in the SRAM model
    wire logic [1:0]  jlp_mode;
    wire logic [4:0]  jlp_sect;
    wire logic        jlp_on, jlp_busy, jlp_eng_busy, jm_req, jm_we, jm_ack;
    wire logic [16:0] jm_addr;
    wire logic [15:0] jm_wdata, jm_rdata;
    /* verilator lint_off UNUSEDSIGNAL */
    wire logic [15:0] jlp_nv_q;
    /* verilator lint_on UNUSEDSIGNAL */

    intv_media #(.CRC_HEX(`CRC_HEX), .LAYOUT_HEX(`LAYOUT_HEX)) media (
        .clk, .reset, .mreset,
        .ld_wr, .ld_addr, .ld_data, .len_valid, .cart_len, .len_chk(2'd0), .cfg_len, .cfg_inlist,
        .bus_req(c_req), .bus_we(c_we), .bus_addr(c_addr), .bus_wdata(c_wdata),
        .bus_ack(c_ack), .bus_rdata(c_rdata), .bus_hit(c_hit), .bus_attr(c_attr),
        .bus_paged(c_paged), .pg_rst(64'd0), .pg_sel,
        .ecs_on, .ecs_pg, .ecs_auto, .ecs_rom_ok, .voice_auto,
        .jlp_mode, .jlp_sect, .jlp_on, .jlp_busy, .jm_req, .jm_we, .jm_addr, .jm_wdata, .jm_ack, .jm_rdata,
        .aux_req, .aux_we, .aux_addr, .aux_wdata, .aux_be(2'b11),
        .aux_ack, .aux_rdata,
        .exec_addr, .exec_q, .grom_addr, .grom_q, .vgrom_addr, .vgrom_q,
        .ivoice_addr(iv_addr), .ivoice_q,
        .ready, .busy, .err, .fmt_err, .len_st(), .slot_st, .crc, .words, .layout, .flags, .hit,
        .cfg_crc, .noss,
        .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_c),
        .sram_a, .sram_dq_out, .sram_dq_oe, .sram_dq_in, .sram_oe_n, .sram_we_n,
        .sram_ub_n, .sram_lb_n);

    sram_as6c2016 sram (
        .clk, .a(sram_a), .dq_w(sram_dq_out), .dq_oe(sram_dq_oe), .dq_r(sram_dq_in),
        .oe_n(sram_oe_n), .we_n(sram_we_n), .ub_n(sram_ub_n), .lb_n(sram_lb_n));

    wire logic [2:0]  phase;
    wire logic [15:0] dout, din, addr;
    wire logic        fetch, hold, halted;
    wire logic [3:0]  colour;
    logic             busrq_en = 1'b1;

    // +keys: the hand controllers' bytes by model cycle (cyc, below)
    int          nkeys = 0;
    longint      key_c[256];
    logic [15:0] key_v[256];
    logic [15:0] kpads;
    longint      cyc = -1;                // model cycle of the CPU cycle now running

    always_comb begin
        kpads = {pad_r, pad_l};
        for (int i = 0; i < nkeys; i++)
            if (cyc >= key_c[i]) kpads = key_v[i];
    end

    // +ekeys: the ECS keyboard's switches by model cycle
    int          nek = 0;
    longint      ek_c[512];
    logic [63:0] ek_v[512];
    logic [63:0] ekeys;
    always_comb begin
        ekeys = 64'd0;
        for (int i = 0; i < nek; i++)
            if (cyc >= ek_c[i]) ekeys = ek_v[i];
    end

    intv_machine dut (
        .clk, .mreset, .ce(ce_cpu), .ce_pix(ce_stic), .live, .hcnt, .vcnt,
        .cfg_hlt_imm(1'b0), .cfg_sdbd_r6_mame(1'b0), .busrq_en,
        .pad_r(kpads[15:8]), .pad_l(kpads[7:0]),
        .ecs_mode, .ecs_keys(ekeys), .ecs_synth(synth), .ecs_on, .ecs_full(efull), .ecs_pg,
        .cart_req(c_req), .cart_we(c_we), .cart_addr(c_addr), .cart_wdata(c_wdata),
        .cart_ack(c_ack), .cart_rdata(c_rdata), .cart_hit(c_hit),
        .voice_mode, .voice_dac7(vdac), .voice_level(vlevel), .ecs_level(elevel), .voice_on, .voice_busy, .voice_late,
        .ivoice_addr(iv_addr), .ivoice_q,
        .jlp_mode, .jlp_sect, .jlp_on, .jlp_busy, .jlp_eng_busy,
        .jm_req, .jm_we, .jm_addr, .jm_wdata, .jm_ack, .jm_rdata,
        .jlp_nv_addr(14'd0), .jlp_nv_we(1'b0), .jlp_nv_wdata(16'd0), .jlp_nv_q,
        .exec_addr, .exec_q, .grom_addr, .grom_q, .vgrom_addr, .vgrom_q, .colour,
        .phase, .dout, .din, .addr, .fetch, .hold, .halted,
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_m));

    wire logic [31:0] ss_rdata = ssr_t | ssr_m | ssr_c;

    // ------------------------------------------------------------ logging
    string exec_f, grom_f, cart_f, cfg_f, log_f;
    longint ncyc = 1000, rtcyc = -1, rton = 20000, dumpc = -1;
    int rt = 0, rtsub = 0;
    int  fd;
    int  nfail = 0;

    task automatic fail(input string s);
        nfail++;
        $fdisplay(fd, "FAIL %s", s);
        $display("FAIL %s", s);
    endtask

    logic   rw_req = 1'b0;
    longint rw_val = 0;
    logic [1:0] ml = 2'b00;               // last logged {hs, csmode}
    logic   ml_force = 1'b0;
    int     bushash = 0;
    logic [31:0] hb = 32'h811C9DC5, hs_ = 32'h811C9DC5;
    int     nb = 0, ns = 0;
    logic [31:0] ha = 32'h811C9DC5, hq = 32'h811C9DC5, ha_s, hq_s;
    int     na = 0, nq = 0, na_s, nq_s;
    logic [31:0] ha2 = 32'h811C9DC5, hq2 = 32'h811C9DC5, hm = 32'h811C9DC5, ha2_s, hq2_s, hm_s;
    int     na2 = 0, nq2 = 0, na2_s, nq2_s;
    localparam longint FRAME = 14934;

    function automatic logic [31:0] fnv(input logic [31:0] h, input logic [31:0] x);
        fnv = (h ^ x) * 32'h01000193;
    endfunction

    always @(posedge clk) begin
        logic [15:0] ba, bd;
        if (rw_req)
            cyc <= rw_val;
        else if (ce_cpu && !hold) begin
            if (cyc >= 0 && ({dut.stic.hs, dut.stic.csmode} != ml || ml_force)) begin
                $fdisplay(fd, "M %0d %0d %0d", cyc, dut.stic.hs, dut.stic.csmode);
                ml <= {dut.stic.hs, dut.stic.csmode};
                ml_force <= 1'b0;
            end
            ba = (phase == 3'd4 || phase == PH_INTAK) ? dout : (phase == 3'd2 ? 16'd0 : addr);
            bd = (phase == 3'd4 || phase == PH_INTAK) ? 16'd0 : (phase == 3'd5 || phase == 3'd6) ? dout : din;
            if (cyc >= 0 && phase != PH_NACT) begin
                if (bushash != 0) begin
                    hb = fnv(fnv(fnv(fnv(hb, 32'(cyc)), 32'(phase)), 32'(ba)), 32'(bd));
                    nb++;
                end else
                    $fdisplay(fd, "B %0d %0d %04x %04x", cyc, phase, ba, bd);
            end
            if (cyc >= 0 && (fetch || phase == PH_INTAK)) begin
                if (bushash != 0) begin
                    if (cyc > 0) begin
                        hs_ = fnv(hs_, 32'(cyc));
                        for (int i = 0; i < 8; i++) hs_ = fnv(hs_, 32'(dut.cpu.r[i]));
                        hs_ = fnv(hs_, 32'({dut.cpu.fS, dut.cpu.fZ, dut.cpu.fO, dut.cpu.fC,
                                            dut.cpu.fI, dut.cpu.fD}));
                        ns++;
                    end
                end else
                    $fdisplay(fd, "S %0d %04x %04x %04x %04x %04x %04x %04x %04x %02x", cyc,
                              dut.cpu.r[0], dut.cpu.r[1], dut.cpu.r[2], dut.cpu.r[3],
                              dut.cpu.r[4], dut.cpu.r[5], dut.cpu.r[6], dut.cpu.r[7],
                              {dut.cpu.fS, dut.cpu.fZ, dut.cpu.fO, dut.cpu.fC, dut.cpu.fI, dut.cpu.fD});
            end
            if (bushash != 0 && cyc >= 0 && (cyc + 1) % FRAME == 0) begin
                $fdisplay(fd, "H %0d %08x %0d %08x %0d", cyc / FRAME, hb, nb, hs_, ns);
                hb = 32'h811C9DC5; hs_ = 32'h811C9DC5; nb = 0; ns = 0;
            end
            // the PSG: a step ends this cycle (and maybe a 48 kHz sample)
            if (cyc >= 0 && dut.psg.tick) begin
                ha = fnv(ha, {20'd0, dut.psg.lv[2], dut.psg.lv[1], dut.psg.lv[0]});
                na++;
                if (dut.psg.srph_n >= 23'd3579545) begin
                    hq = fnv(hq, 32'(dut.psg.prod[31:16]));
                    nq++;
                end
            end
            // PSG #2 (it steps only while the ECS is attached) and the mixed sound
            if (cyc >= 0 && dut.ecs.psg.tick) begin
                ha2 = fnv(ha2, {20'd0, dut.ecs.psg.lv[2], dut.ecs.psg.lv[1], dut.ecs.psg.lv[0]});
                na2++;
                if (dut.ecs.psg.srph_n >= 23'd3579545) begin
                    hq2 = fnv(hq2, 32'(dut.ecs.psg.prod[31:16]));
                    nq2++;
                end
            end
            if (cyc >= 0 && (cyc + 1) % FRAME == 0) begin
                $fdisplay(fd, "A %0d %08x %0d %08x %0d", cyc / FRAME, ha, na, hq, nq);
                ha = 32'h811C9DC5; hq = 32'h811C9DC5; na = 0; nq = 0;
                $fdisplay(fd, "E %0d %08x %0d %08x %0d %08x", cyc / FRAME, ha2, na2, hq2, nq2, hm);
                ha2 = 32'h811C9DC5; hq2 = 32'h811C9DC5; hm = 32'h811C9DC5; na2 = 0; nq2 = 0;
            end
            cyc <= cyc + 1;
        end
    end

    // the machine's mixed sound: every sample as intv_machine gives it (audio
    // at audio_stb, the clk after the step's ce: a step that ends a frame's
    // last cycle counts in the next frame's E line)
    always @(posedge clk)
        if (dut.audio_stb && cyc > 0 && !ss_en)
            hm = fnv(hm, 32'(dut.audio));

    // the Intellivoice's samples (step 10): "V <cycle it fired at> <strobe> <sample>", strobe:
    // the number of 48 kHz strobes (audio_stb) before the first that sees it
    longint v_fire = 0, nstb = 0;
    always @(posedge clk) begin
        if (dut.voice.fire) v_fire = cyc;
        if (dut.voice.c_done)
            $fdisplay(fd, "V %0d %0d %04x", v_fire, nstb + (dut.audio_stb ? 1 : 0), dut.voice.c_sample);
        if (dut.audio_stb) nstb++;
    end

    // ------------------------------------------------- the STIC's side
    // row fetches (decided the clk after the fetch cycle's ce) and the card
    // engine at the first line of each card row
    always @(posedge clk) begin
        if (dut.stic.live && !mreset && !ss_en && cyc >= 0) begin
            if (dut.stic.cp_arm)
                $fdisplay(fd, "G %0d %0d %0d %0d", cyc, (32'(vcnt) - 69 - 2 * 32'(dut.stic.vdr_l)) / 16,
                          (!busrq_en || dut.stic.busak) ? 1 : 0, dut.stic.cnt);
            if (dut.stic.cp_on && dut.stic.cp_ph && dut.stic.cp_j == 5'd19) begin
                $fwrite(fd, "GW %0d", cyc);
                for (int i = 0; i < 19; i++) $fwrite(fd, " %04x", dut.stic.rowbuf.mem[i]);
                $fwrite(fd, " %04x\n", dut.stic.cp_w);
            end
            if (dut.stic.frame_end)
                $fdisplay(fd, "K %0d %03x %03x %03x %03x %03x %03x %03x %03x", cyc,
                          dut.stic.coll_p[0], dut.stic.coll_p[1], dut.stic.coll_p[2], dut.stic.coll_p[3],
                          dut.stic.coll_p[4], dut.stic.coll_p[5], dut.stic.coll_p[6], dut.stic.coll_p[7]);
            if (ce_stic && dut.stic.eng_card && dut.stic.rstart)
                $fdisplay(fd, "C %0d %0d %0d %0d %0d", cyc, dut.stic.yy_t[8:4], dut.stic.ec[4:0],
                          dut.stic.squares ? 2 : dut.stic.w[11] ? 1 : 0,
                          dut.stic.squares ? 14'd0 : (dut.stic.csmode && !dut.stic.w[11])
                          ? dut.stic.w & 14'h07F8 : dut.stic.w & 14'h01F8);
        end
    end

    // pictures: two buffers, picture of frame k in buf[k & 1]
    string  pic_f;
    int     pfd = 0;
    logic [3:0] pbuf [2][45360];
    always @(posedge clk) begin
        longint k;
        int y, x;
        if (pfd != 0 && ce_stic && live && cyc >= 0) begin
            k = cyc / FRAME;
            x = 32'(hcnt) - 24;
            if (vcnt == 9'd24 && hcnt == 9'd0 && k >= 1) begin
                $fwrite(pfd, "%u", 32'(k));
                for (int i = 0; i < 5670; i++) begin
                    logic [31:0] wv;
                    for (int j = 0; j < 8; j++) wv[4*j +: 4] = pbuf[(k - 1) & 1][8 * i + j];
                    $fwrite(pfd, "%u", wv);
                end
            end
            if (x >= 0 && x < 189) begin
                if (vcnt >= 9'd46 && vcnt < 9'd262) begin
                    y = 32'(vcnt) - 46;
                    pbuf[k & 1][y * 189 + x] = colour;
                end else if (vcnt < 9'd24 && k >= 1) begin
                    y = 216 + 32'(vcnt);
                    pbuf[(k - 1) & 1][y * 189 + x] = colour;
                end
            end
        end
    end

    // ------------------------------------------------------------ loading
    task automatic load_file(input string path, input logic [3:0] slot, output int n);
        int f, c;
        n = 0;
        f = $fopen(path, "rb");
        if (f == 0) begin
            fail($sformatf("cannot open %s", path));
            return;
        end
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

    // --------------------------------------------------------- state port
    // module id, word count (the order is the write order)
    localparam int NMOD = 20;
    int unsigned mod_id [NMOD] = '{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 24, 25, 32};
    int unsigned mod_n  [NMOD] = '{1, 8, 2, 67, 21, 256, 256, 96, 256, 256, 16, 20, 64, 1, 21, 256, 256, 24, 64, 28};
    logic [31:0] saved [NMOD][256];
    // the JLP's flash store and its row bits (build step 11): not machine state (a state load
    // keeps the flash, JLP_NOTES 5.2), so the core never rolls it back; a "later state" round
    // trip (mode 2) goes back in time past flash commands the model never undid, so the
    // bench rolls the store back itself there
    logic [15:0]  fl_saved [12288];
    logic [127:0] fe_saved;
    logic [3:0]  pbuf_saved [2][45360];

    task automatic ss_read(input int id, input int w, output logic [31:0] v);
        @(negedge clk);
        ss_addr = {8'(id), 8'(w)};
        @(negedge clk);
        @(negedge clk);
        v = ss_rdata;
    endtask

    task automatic ss_write(input int id, input int w, input logic [31:0] v);
        @(negedge clk);
        ss_addr = {8'(id), 8'(w)}; ss_wdata = v; ss_we = 1'b1;
        @(negedge clk);
        ss_we = 1'b0;
    endtask

    // cart RAM (16K cells at $18000 in the SRAM) and the JLP RAM after it ($1C000, 8K;
    // build step 11) through the aux port
    localparam int CRAM = 16384 + 8192;
    logic [15:0] cram_saved [CRAM];
    bit          has_cart = 1'b0;

    task automatic aux_op(input logic we, input logic [16:0] a, input logic [15:0] d,
                          output logic [15:0] q);
        int n;
        @(negedge clk);
        aux_req = 1'b1; aux_we = we; aux_addr = a; aux_wdata = d;
        n = 0;
        do begin @(negedge clk); n++; end while (!aux_ack && n < 100);
        aux_req = 1'b0; aux_we = 1'b0;
        q = aux_rdata;
        if (n >= 100) fail($sformatf("aux port answers at %05x", a));
    endtask

    task automatic cram_all(input int what);  // 0 save, 1 junk, 2 restore and check
        logic [15:0] q;
        for (int i = 0; i < CRAM; i++) begin
            if (what == 0)
                aux_op(1'b0, 17'h18000 + 17'(i), 16'd0, cram_saved[i]);
            else if (what == 1)
                aux_op(1'b1, 17'h18000 + 17'(i), ~cram_saved[i] ^ 16'(i * 32'h9E37), q);
            else
                aux_op(1'b1, 17'h18000 + 17'(i), cram_saved[i], q);
        end
        if (what == 2)
            for (int i = 0; i < CRAM; i++) begin
                aux_op(1'b0, 17'h18000 + 17'(i), 16'd0, q);
                if (q !== cram_saved[i])
                    fail($sformatf("restore: cart RAM cell %0d reads %04x, saved %04x", i, q,
                                   cram_saved[i]));
            end
    endtask

    task automatic freeze();
        @(negedge clk);
        run = 1'b0;
        repeat (16) @(negedge clk);       // let a cartridge access finish
        while (voice_busy || jlp_eng_busy) @(negedge clk); // and a voice sample, the JLP's flash
                                           // engine (intv_ss_ctl's quiet point)
        if (live) fail("machine still live after run = 0");
        ss_en = 1'b1;
    endtask

    task automatic save_all();
        for (int b = 0; b < 2; b++)               // the bench's own picture capture (rewind)
            for (int i = 0; i < 45360; i++) pbuf_saved[b][i] = pbuf[b][i];
        ha_s = ha; hq_s = hq; na_s = na; nq_s = nq;   // and its PSG sums
        ha2_s = ha2; hq2_s = hq2; hm_s = hm; na2_s = na2; nq2_s = nq2;
        for (int m = 0; m < NMOD; m++)
            for (int w = 0; w < mod_n[m]; w++)
                ss_read(mod_id[m], w, saved[m][w]);
        if (has_cart) cram_all(0);
        for (int i = 0; i < 12288; i++) fl_saved[i] = dut.jlp.store[i];
        fe_saved = dut.jlp.empt;
    endtask

    task automatic dump_all(input int k);
        logic [31:0] v;
        for (int m = 0; m < NMOD; m++)
            for (int w = 0; w < mod_n[m]; w++) begin
                ss_read(mod_id[m], w, v);
                $fdisplay(fd, "W %0d %02x %0d %08x", k, mod_id[m], w, v);
            end
    endtask

    task automatic resume();
        longint t0;
        ss_en = 1'b0;
        repeat (4) @(negedge clk);
        run = 1'b1;
        t0 = $time;
        while (!live) @(negedge clk);
        $fdisplay(fd, "R resumed after %0d clk_sys", ($time - t0) / 10);
    endtask

    task automatic wait_cycle(input longint c);
        while (cyc < c) @(negedge clk);
        if (cyc != c) fail($sformatf("wait for cycle %0d: at %0d", c, cyc));
    endtask

    task automatic restore_all(input int mode);
        logic [31:0] v;
        if (mode == 1) begin                      // into a reset machine
            ss_en = 1'b0;
            @(negedge clk);
            mres_tb = 1'b1;
            repeat (8) @(negedge clk);
            mres_tb = 1'b0;
            repeat (4) @(negedge clk);
            ss_en = 1'b1;
        end else begin                            // a later state
            resume();
            wait_cycle(rtcyc + rton);
            freeze();
            $fdisplay(fd, "R frozen again at cycle %0d", cyc);
            for (int i = 0; i < 12288; i++) dut.jlp.store[i] = fl_saved[i];
            dut.jlp.empt = fe_saved;
        end
        // junk, so that nothing left from before can pass: straight into
        // the three RAM arrays (what another game would have left there; a
        // RAM that dropped every state-port write would otherwise keep the
        // right contents through the reset), then through the state port
        // into every word, and into the cart RAM
        for (int i = 0; i < 256; i++) dut.scratch.mem[i] = 8'(~saved[5][i] ^ 32'(i * 37));
        for (int i = 0; i < 512; i++)
            dut.sysram.mem[i] = 16'(~(i < 256 ? saved[6][i] : saved[7][i - 256]) ^ 32'(i * 4097));
        for (int i = 0; i < 512; i++)
            dut.gram.mem[i] = 8'(~(i < 256 ? saved[8][i] : saved[9][i - 256]) ^ 32'(i * 41));
        for (int i = 0; i < 32; i++)
            dut.stic.rowbuf.mem[i] = 14'(~(i < 20 ? saved[11][i] : 0) ^ 32'(i * 911));
        for (int i = 0; i < 64; i++)
            dut.stic.linebuf.mem[i] = 18'(~saved[12][i] ^ 32'(i * 40503));
        for (int m = 0; m < NMOD; m++)
            for (int w = 0; w < mod_n[m]; w++)
                ss_write(mod_id[m], w, ~saved[m][w] ^ (32'h9E3779B9 * (w + 1)));
        if (has_cart) cram_all(1);
        for (int m = 0; m < NMOD; m++)
            for (int w = 0; w < mod_n[m]; w++)
                ss_write(mod_id[m], w, saved[m][w]);
        for (int m = 0; m < NMOD; m++)
            for (int w = 0; w < mod_n[m]; w++) begin
                ss_read(mod_id[m], w, v);
                if (v !== saved[m][w])
                    fail($sformatf("restore: word %02x.%0d reads %08x, saved %08x",
                                   mod_id[m], w, v, saved[m][w]));
            end
        if (has_cart) cram_all(2);
        ml_force = 1'b1;
    endtask

    // ------------------------------------------------------------ the run

    initial begin
        int n, to;
        if (!$value$plusargs("log=%s", log_f)) log_f = "tb_system.log";
        fd = $fopen(log_f, "w");
        void'($value$plusargs("cycles=%d", ncyc));
        void'($value$plusargs("rt=%d", rt));
        void'($value$plusargs("rtcyc=%d", rtcyc));
        void'($value$plusargs("rtsub=%d", rtsub));
        void'($value$plusargs("rton=%d", rton));
        void'($value$plusargs("dump=%d", dumpc));
        void'($value$plusargs("bushash=%d", bushash));
        begin
            int b;
            if ($value$plusargs("busrq=%d", b)) busrq_en = b != 0;
        end
        if ($value$plusargs("pic=%s", pic_f)) begin
            pfd = $fopen(pic_f, "wb");
            if (pfd == 0) fail($sformatf("cannot open %s", pic_f));
        end
        if (bushash != 0 && rt != 0) fail("+bushash with a round trip");
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
                $fdisplay(fd, "L keys %0d", nkeys);
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
                $fdisplay(fd, "L ekeys %0d", nek);
            end
        end
        begin
            int e;
            if ($value$plusargs("ecs=%d", e)) ecs_ovr = 2'(e);
            if ($value$plusargs("synth=%d", e)) synth = e != 0;
            if ($value$plusargs("voice=%d", e)) voice_ovr = 2'(e);
            if ($value$plusargs("vlevel=%d", e)) vlevel = 3'(e);
            if ($value$plusargs("vdac=%d", e)) vdac = e != 0;
            if ($value$plusargs("elevel=%d", e)) elevel = 3'(e);
        end
        if (!$value$plusargs("exec=%s", exec_f) || !$value$plusargs("grom=%s", grom_f))
            fail("give +exec= and +grom=");
        repeat (8) @(negedge clk);
        reset = 1'b0;
        repeat (8) @(negedge clk);

        load_file(exec_f, 4'd2, n);
        $fdisplay(fd, "L exec %0d", n);
        load_file(grom_f, 4'd3, n);
        $fdisplay(fd, "L grom %0d", n);
        begin
            string ecs_f;
            if ($value$plusargs("ecsrom=%s", ecs_f)) begin
                load_file(ecs_f, 4'd4, n);
                $fdisplay(fd, "L ecsrom %0d", n);
            end
            if ($value$plusargs("ivoice=%s", ecs_f)) begin
                load_file(ecs_f, 4'd5, n);
                $fdisplay(fd, "L ivoice %0d", n);
            end
        end
        n = 0;
        if ($value$plusargs("cart=%s", cart_f)) begin
            load_file(cart_f, 4'd0, n);
            has_cart = 1'b1;
        end
        $fdisplay(fd, "L cart %0d", n);
        cart_len = n;
        if ($value$plusargs("cfg=%s", cfg_f)) begin
            load_file(cfg_f, 4'd1, n);
            cfg_len = n; cfg_inlist = 1'b1;
            $fdisplay(fd, "L cfg %0d", n);
        end
        @(negedge clk);
        len_valid = 1'b1;
        to = 0;
        while (!(ready && !busy) && to < 4000000) begin @(negedge clk); to++; end
        if (to >= 4000000) fail("loader not ready");
        $fdisplay(fd, "L ready err %0d crc %08x words %0d layout %0d flags %02x hit %0d",
                  err, crc, words, layout, flags, hit);
        $fdisplay(fd, "L ecs auto %0d rom %0d mode %0d", ecs_auto, ecs_rom_ok, ecs_mode);
        $fdisplay(fd, "L voice mode %0d", voice_mode);
        repeat (10) @(negedge clk);
        mres_tb = 1'b0;

        // the round trip and the first dump, in the order of their cycles
        for (int pass = 0; pass < 2; pass++) begin
            if (rt != 0 && rtcyc >= 0 && (pass == 0) == (dumpc < 0 || rtcyc < dumpc)) begin
                wait_cycle(rtcyc);
                repeat (rtsub) @(negedge clk);
                freeze();
                $fdisplay(fd, "R freeze at cycle %0d +%0d clk, timing word %08x", cyc, rtsub + 1,
                          timing.mpos);
                $fdisplay(fd, "R stic: row copy %0d word %0d, CPU in BUSAK %0d, hcnt %0d, card engine %0d",
                          dut.stic.cp_on, dut.stic.cp_j, dut.stic.busak, hcnt, dut.stic.eng_card);
                $fdisplay(fd, "R mobs: sweep %0d line %0d %s %0d/%0d phase %0d, masks of the next line %0d",
                          dut.stic.g_on, dut.stic.g_ly, dut.stic.g_f ? "fetch" : "pair", dut.stic.g_m,
                          dut.stic.g_j, dut.stic.g_ph,
                          (dut.stic.rm[0] | dut.stic.rm[1] | dut.stic.rm[2] | dut.stic.rm[3] |
                           dut.stic.rm[4] | dut.stic.rm[5] | dut.stic.rm[6] | dut.stic.rm[7]) != 16'd0);
                save_all();
                $fdisplay(fd, "R mark");
                restore_all(rt);
                if (rt == 2) begin
                    @(negedge clk);
                    rw_val = rtcyc; rw_req = 1'b1;
                    repeat (2) @(negedge clk);
                    rw_req = 1'b0;
                    for (int b = 0; b < 2; b++)
                        for (int i = 0; i < 45360; i++) pbuf[b][i] = pbuf_saved[b][i];
                    ha = ha_s; hq = hq_s; na = na_s; nq = nq_s;
                    ha2 = ha2_s; hq2 = hq2_s; hm = hm_s; na2 = na2_s; nq2 = nq2_s;
                    $fdisplay(fd, "R rewind %0d", rtcyc);
                end
                resume();
            end
            if (pass == 0 && dumpc >= 0) begin
                wait_cycle(dumpc);
                freeze();
                dump_all(1);
                resume();
            end
        end

        // just after the ce that ended cycle ncyc - 1
        wait_cycle(ncyc);
        freeze();
        $fdisplay(fd, "L ecs full %0d", efull);
        $fdisplay(fd, "L voice on %0d late %0d", voice_on, voice_late);
        dump_all(2);
        ss_en = 1'b0;
        if (halted) $fdisplay(fd, "R CPU halted");
        $fdisplay(fd, nfail == 0 ? "END" : "END with failures");
        $fclose(fd);
        if (pfd != 0) $fclose(pfd);
        $finish;
    end

endmodule

`default_nettype wire
