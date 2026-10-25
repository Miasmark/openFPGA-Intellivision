// Step 3 bench (DESIGN.md 9): the machine (intv_machine: CP1610, bus
// fabric, RAMs, STIC and PSG register stubs) with the real timing
// (intv_timing) and cartridge side (intv_media and our SRAM model), running
// the EXEC with or without a cartridge. The bench writes what the bus does;
// sim/tb/tb_system.py compares it with tools/intv_system.py cycle by cycle.
//
// Plusargs
//   +exec=F +grom=F     the system ROM files (loaded through intv_media's
//                       byte port as the data slots 2 and 3 would)
//   +cart=F             a cartridge image (slot 0); without it, no cartridge
//   +cycles=N           run N CPU cycles from the first fetch (model cycle 0)
//   +pads=RRLL          the hand controllers' bytes at $01FE (right) and
//                       $01FF (left), hex (default FFFF: nothing pressed)
//   +log=F              the output (below)
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
//   M c hs cs           the STIC's handshake or mode latch (csmode) changed:
//                       their values during cycle c (also once after a
//                       restore; the reader drops repeats)
//   L ...               load results;  R ...  round-trip notes
//   W k id w value      every state word at a dump (k = 1: +dump, 2: the
//                       end, frozen after cycle N-1)
//   END / FAIL text
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
    logic [31:0] cart_len = 32'd0;
    logic        ss_en = 1'b0;
    logic [7:0]  pad_r = 8'hFF, pad_l = 8'hFF;
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

    wire logic        ready, busy, hit;
    wire logic [4:0]  err;
    wire logic [11:0] slot_st;
    wire logic [31:0] crc;
    wire logic [16:0] words;
    wire logic [7:0]  layout, flags;
    wire logic        c_req, c_we, c_ack, c_hit, c_paged;
    wire logic [15:0] c_addr, c_wdata, c_rdata;
    wire logic [1:0]  c_kind;
    wire logic        aux_ack;
    wire logic [15:0] aux_rdata;
    wire logic [11:0] exec_addr;
    wire logic [10:0] grom_addr;
    wire logic [9:0]  exec_q;
    wire logic [7:0]  grom_q, ivoice_q;
    wire logic [16:0] sram_a;
    wire logic [15:0] sram_dq_out, sram_dq_in;
    wire logic        sram_dq_oe, sram_oe_n, sram_we_n, sram_ub_n, sram_lb_n;
    wire logic        mreset = mres_tb || !ready;

    intv_media #(.CRC_HEX(`CRC_HEX), .LAYOUT_HEX(`LAYOUT_HEX)) media (
        .clk, .reset, .mreset,
        .ld_wr, .ld_addr, .ld_data, .len_valid, .cart_len, .len_chk(2'd0),
        .bus_req(c_req), .bus_we(c_we), .bus_addr(c_addr), .bus_wdata(c_wdata),
        .bus_ack(c_ack), .bus_rdata(c_rdata), .bus_hit(c_hit), .bus_kind(c_kind),
        .bus_paged(c_paged),
        .aux_req, .aux_we, .aux_addr, .aux_wdata, .aux_be(2'b11),
        .aux_ack, .aux_rdata,
        .exec_addr, .exec_q, .grom_addr, .grom_q, .ivoice_addr(11'd0), .ivoice_q,
        .ready, .busy, .err, .len_st(), .slot_st, .crc, .words, .layout, .flags, .hit,
        .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_c),
        .sram_a, .sram_dq_out, .sram_dq_oe, .sram_dq_in, .sram_oe_n, .sram_we_n,
        .sram_ub_n, .sram_lb_n);

    sram_as6c2016 sram (
        .clk, .a(sram_a), .dq_w(sram_dq_out), .dq_oe(sram_dq_oe), .dq_r(sram_dq_in),
        .oe_n(sram_oe_n), .we_n(sram_we_n), .ub_n(sram_ub_n), .lb_n(sram_lb_n));

    wire logic [2:0]  phase;
    wire logic [15:0] dout, din, addr;
    wire logic        fetch, hold, halted;

    intv_machine dut (
        .clk, .mreset, .ce(ce_cpu), .hcnt, .vcnt,
        .cfg_hlt_imm(1'b0), .cfg_sdbd_r6_mame(1'b0), .pad_r, .pad_l,
        .cart_req(c_req), .cart_we(c_we), .cart_addr(c_addr), .cart_wdata(c_wdata),
        .cart_ack(c_ack), .cart_rdata(c_rdata), .cart_hit(c_hit),
        .exec_addr, .exec_q, .grom_addr, .grom_q,
        .phase, .dout, .din, .addr, .fetch, .hold, .halted,
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_m));

    wire logic [31:0] ss_rdata = ssr_t | ssr_m | ssr_c;

    // ------------------------------------------------------------ logging
    string exec_f, grom_f, cart_f, log_f;
    longint ncyc = 1000, rtcyc = -1, rton = 20000, dumpc = -1;
    int rt = 0, rtsub = 0;
    int  fd;
    int  nfail = 0;
    longint cyc = -1;                     // model cycle of the CPU cycle now running

    task automatic fail(input string s);
        nfail++;
        $fdisplay(fd, "FAIL %s", s);
        $display("FAIL %s", s);
    endtask

    logic   rw_req = 1'b0;
    longint rw_val = 0;
    logic [1:0] ml = 2'b00;               // last logged {hs, csmode}
    logic   ml_force = 1'b0;
    always @(posedge clk) begin
        if (rw_req)
            cyc <= rw_val;
        else if (ce_cpu && !hold) begin
            if (cyc >= 0 && ({dut.stic.hs, dut.stic.csmode} != ml || ml_force)) begin
                $fdisplay(fd, "M %0d %0d %0d", cyc, dut.stic.hs, dut.stic.csmode);
                ml <= {dut.stic.hs, dut.stic.csmode};
                ml_force <= 1'b0;
            end
            if (cyc >= 0 && phase != PH_NACT)
                $fdisplay(fd, "B %0d %0d %04x %04x", cyc, phase,
                          (phase == 3'd4 || phase == PH_INTAK) ? dout : (phase == 3'd2 ? 16'd0 : addr),
                          (phase == 3'd4 || phase == PH_INTAK) ? 16'd0
                          : (phase == 3'd5 || phase == 3'd6) ? dout : din);
            if (cyc >= 0 && (fetch || phase == PH_INTAK))
                $fdisplay(fd, "S %0d %04x %04x %04x %04x %04x %04x %04x %04x %02x", cyc,
                          dut.cpu.r[0], dut.cpu.r[1], dut.cpu.r[2], dut.cpu.r[3],
                          dut.cpu.r[4], dut.cpu.r[5], dut.cpu.r[6], dut.cpu.r[7],
                          {dut.cpu.fS, dut.cpu.fZ, dut.cpu.fO, dut.cpu.fC, dut.cpu.fI, dut.cpu.fD});
            cyc <= cyc + 1;
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
    localparam int NMOD = 11;
    int unsigned mod_id [NMOD] = '{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11};
    int unsigned mod_n  [NMOD] = '{1, 8, 2, 52, 14, 256, 256, 96, 256, 256, 21};
    logic [31:0] saved [NMOD][256];

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

    // cart RAM (16K cells at $18000 in the SRAM) through the aux port
    localparam int CRAM = 16384;
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
        if (live) fail("machine still live after run = 0");
        ss_en = 1'b1;
    endtask

    task automatic save_all();
        for (int m = 0; m < NMOD; m++)
            for (int w = 0; w < mod_n[m]; w++)
                ss_read(mod_id[m], w, saved[m][w]);
        if (has_cart) cram_all(0);
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
        begin
            logic [15:0] pads;
            if ($value$plusargs("pads=%h", pads)) {pad_r, pad_l} = pads;
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
        n = 0;
        if ($value$plusargs("cart=%s", cart_f)) begin
            load_file(cart_f, 4'd0, n);
            has_cart = 1'b1;
        end
        $fdisplay(fd, "L cart %0d", n);
        @(negedge clk);
        cart_len = n; len_valid = 1'b1;
        to = 0;
        while (!(ready && !busy) && to < 4000000) begin @(negedge clk); to++; end
        if (to >= 4000000) fail("loader not ready");
        $fdisplay(fd, "L ready err %0d crc %08x words %0d layout %0d flags %02x hit %0d",
                  err, crc, words, layout, flags, hit);
        repeat (10) @(negedge clk);
        mres_tb = 1'b0;

        if (rt != 0 && rtcyc >= 0) begin
            wait_cycle(rtcyc);
            repeat (rtsub) @(negedge clk);
            freeze();
            $fdisplay(fd, "R freeze at cycle %0d +%0d clk, timing word %08x", cyc, rtsub + 1,
                      timing.mpos);
            save_all();
            restore_all(rt);
            if (rt == 2) begin
                @(negedge clk);
                rw_val = rtcyc; rw_req = 1'b1;
                repeat (2) @(negedge clk);
                rw_req = 1'b0;
                $fdisplay(fd, "R rewind %0d", rtcyc);
            end
            resume();
        end

        if (dumpc >= 0) begin
            wait_cycle(dumpc);
            freeze();
            dump_all(1);
            resume();
        end

        // just after the ce that ended cycle ncyc - 1
        wait_cycle(ncyc);
        freeze();
        dump_all(2);
        ss_en = 1'b0;
        if (halted) $fdisplay(fd, "R CPU halted");
        $fdisplay(fd, nfail == 0 ? "END" : "END with failures");
        $fclose(fd);
        $finish;
    end

endmodule

`default_nettype wire
