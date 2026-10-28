// Step 3 bench (DESIGN.md 9): the CP1610 RTL in lockstep with the Python
// model's bus-phase log, and its save/restore round trip (DESIGN.md 8.4).
//
// Input: a case file from tools/cpu_buslog.py (+vec=FILE; format in that
// script): the test programs, the opcode sweep or the random programs. For each case the bench resets the CPU, loads the memory, gives
// the reset IAB and then runs the model's cycles one by one, checking in
// every cycle
//   - the phase code, and per phase the bus contents: BAR and INTAK the
//     address on dout; DTB and ADAR the latched address and the data the
//     memory returns; DW and DWS the latched address and dout; IAB the
//     vector; BUSAK and halted;
//   - that a step (instruction, interrupt, bus wait, halted cycle) starts
//     in exactly the cycles where a model step ends, with R0-R7, S Z O C,
//     I and D equal to the model's at that point;
//   - TCI in the model's cycle, the SIN pulse two cycles after the model's
//     hook;
// and at the end the final registers. The memory model is a plain 64K x 16
// RAM: it latches the address on BAR and INTAK (from dout) and on ADAR
// (from din, the word it returns), returns the latched word on DTB and
// ADAR, the reset vector on the first IAB and the interrupt vector on later
// ones, $FFFF otherwise (pull-ups), and writes on DW. The request lines
// follow the case's ranges: during model cycle c the bench drives the
// value for cycle c + 1, which the CPU samples at the ce that starts it.
//
// Round trip (+saves=1): at each save point of the case, with ce low, the
// bench reads the eight state words of the running CPU, loads them into
// the other instance, checks they read back the same, and goes on with
// that one. The other instance is reset before the load at even save
// points and left with its stale state (an earlier point of the run) at
// odd ones, so a flip-flop missing from the state port shows up either
// way. Save points fall mid-instruction, inside the interrupt sequence and
// bus-request waits (tools/cpu_buslog.py).
//
//   sim/tb/run_tb_cpu.sh      (builds with Verilator, runs, checks)
//
// The last line is "TB_CPU pass" or "TB_CPU FAIL (n)".
//
// SPDX-License-Identifier: MIT

`timescale 1ns / 1ps
`default_nettype none

module tb_cpu;

    localparam logic [7:0] SS_ID = 8'h02;
    localparam logic [2:0] PH_ADAR = 3'd1, PH_IAB = 3'd2,
                           PH_DTB = 3'd3, PH_BAR = 3'd4, PH_DW = 3'd5,
                           PH_DWS = 3'd6, PH_INTAK = 3'd7;

    logic        clk = 1'b0;
    logic        ce = 1'b0;
    logic        act = 1'b0;                  // 0: cpu_a runs, 1: cpu_b
    logic        reset_a = 1'b0, reset_b = 1'b0;
    logic        cfg_hlt_imm = 1'b0, cfg_mame = 1'b0;
    logic [15:0] din;
    logic        intrm = 1'b0, intr = 1'b0, busrq = 1'b0;
    logic [15:0] ss_addr = 16'd0;
    logic [31:0] ss_wdata = 32'd0;
    logic        ss_we_a = 1'b0, ss_we_b = 1'b0;

    logic [2:0]  ph_a, ph_b;
    logic [15:0] do_a, do_b;
    logic        busak_a, busak_b, tci_a, tci_b, pcit_a, pcit_b;
    logic        hlt_a, hlt_b, fetch_a, fetch_b;
    logic [3:0]  ebca_a, ebca_b;
    logic [31:0] ssr_a, ssr_b;
    logic [15:0] bext_mask = 16'd0;

    cp1610 #(.SS_ID(SS_ID)) cpu_a (
        .clk, .reset(reset_a), .ce(ce && !act), .cfg_hlt_imm, .cfg_sdbd_r6_mame(cfg_mame),
        .phase(ph_a), .dout(do_a), .din, .intrm, .intr, .busrq, .busak(busak_a),
        .ebca(ebca_a), .ebci(bext_mask[ebca_a]), .tci(tci_a), .pcit(pcit_a),
        .halted(hlt_a), .fetch(fetch_a),
        .ss_addr, .ss_we(ss_we_a), .ss_wdata, .ss_rdata(ssr_a));
    cp1610 #(.SS_ID(SS_ID)) cpu_b (
        .clk, .reset(reset_b), .ce(ce && act), .cfg_hlt_imm, .cfg_sdbd_r6_mame(cfg_mame),
        .phase(ph_b), .dout(do_b), .din, .intrm, .intr, .busrq, .busak(busak_b),
        .ebca(ebca_b), .ebci(bext_mask[ebca_b]), .tci(tci_b), .pcit(pcit_b),
        .halted(hlt_b), .fetch(fetch_b),
        .ss_addr, .ss_we(ss_we_b), .ss_wdata, .ss_rdata(ssr_b));

    wire logic [2:0]  ph    = act ? ph_b : ph_a;
    wire logic [15:0] dout  = act ? do_b : do_a;
    wire logic        busak = act ? busak_b : busak_a;
    wire logic        tci   = act ? tci_b : tci_a;
    wire logic        pcit  = act ? pcit_b : pcit_a;
    wire logic        hlt   = act ? hlt_b : hlt_a;
    wire logic        fch   = act ? fetch_b : fetch_a;
    // a bus-request wait cycle (not one of the 2 NACT after it): a wait that
    // follows those 2 at once keeps busak high, so the step boundary is seen
    // here, not on busak's edge
    wire logic        waiting = act ? (cpu_b.st == cpu_b.S_BUSAK && cpu_b.cnt == 2'd0)
                                    : (cpu_a.st == cpu_a.S_BUSAK && cpu_a.cnt == 2'd0);

    // registers of the running CPU, from its state port words 0-3 and 6
    function automatic logic [15:0] reg_of(input int k);
        return act ? cpu_b.r[k] : cpu_a.r[k];
    endfunction
    function automatic logic [5:0] flags_of();   // {S,Z,O,C,I,D}
        return act ? {cpu_b.fS, cpu_b.fZ, cpu_b.fO, cpu_b.fC, cpu_b.fI, cpu_b.fD}
                   : {cpu_a.fS, cpu_a.fZ, cpu_a.fO, cpu_a.fC, cpu_a.fI, cpu_a.fD};
    endfunction

    // ------------------------------------------------------------ memory
    logic [15:0] mem [0:65535];
    logic [15:0] latch = 16'd0;
    int          iabs = 0;
    logic [15:0] vec_reset, vec_intr;

    always_comb begin
        unique case (ph)
            PH_DTB, PH_ADAR: din = mem[latch];
            PH_IAB:          din = iabs == 0 ? vec_reset : vec_intr;
            default:         din = 16'hFFFF;
        endcase
    end

    // one CPU cycle: the clock edge with ce, then the memory's own update
    // from the values the cycle had before the edge
    task automatic cpu_cycle();
        logic [2:0]  p;
        logic [15:0] o, i, l;
        p = ph; o = dout; i = din; l = latch;
        ce = 1'b1;
        #5 clk = 1'b1;
        #5 clk = 1'b0;
        ce = 1'b0;
        unique case (p)
            PH_BAR, PH_INTAK: latch = o;
            PH_ADAR:          latch = i;
            PH_DW:            mem[l] = o;
            PH_IAB:           iabs++;
            default: ;
        endcase
    endtask

    // -------------------------------------------------------------- case data
    typedef struct { logic [2:0] ph; logic [15:0] a, d; logic [1:0] fl; } cyc_t;
    typedef struct { int c; logic [15:0] r [8]; logic [3:0] f; logic i, d; } ev_t;
    cyc_t  cyc [$];
    ev_t   evs [$];
    int    tcis [$], sins [$], saves [$];
    int    rk [$], rlo [$], rhi [$];
    logic [15:0] init_r [8];
    logic [3:0]  init_f;
    logic        init_i, has_init, has_fill;
    int unsigned fill_seed;

    // memory of a random-program case (tools/cpu_buslog.py fill_word)
    function automatic logic [15:0] fill_word(input int unsigned seed, input int unsigned a);
        int unsigned x;
        x = a * 32'd2654435761 + seed;
        x = x ^ (x >> 15);
        x = x * 32'd2246822519;
        x = x ^ (x >> 13);
        return x[15:0];
    endfunction
    ev_t   fin;
    logic  fin_h;
    int    ncyc;

    int    fails = 0, case_fails = 0, ncases = 0, nchecks = 0, nswaps = 0;
    string cname;
    int    do_saves = 0;
    int    verbose = 0;
    int    mw_a [$];
    logic [15:0] mw_d [$];

    task automatic fail(input string what);
        if (case_fails < 8)
            $display("  FAIL %s: %s", cname, what);
        case_fails++;
    endtask

    function automatic logic line_at(input int kind, input int c);
        for (int k = 0; k < rk.size(); k++)
            if (rk[k] == kind && c >= rlo[k] && (rhi[k] < 0 || c <= rhi[k]))
                return 1'b1;
        return 1'b0;
    endfunction

    task automatic tick();                  // a clock edge without ce
        #5 clk = 1'b1;
        #5 clk = 1'b0;
    endtask

    // ---- save the running CPU, restore into the other one, switch
    task automatic swap(input int c);
        logic [31:0] w [8];
        ce = 1'b0;
        for (int k = 0; k < 8; k++) begin
            ss_addr = {SS_ID, 8'(k)};
            #1;
            w[k] = act ? ssr_b : ssr_a;
        end
        if (nswaps % 2 == 0) begin               // fresh: reset first
            if (act) reset_a = 1'b1; else reset_b = 1'b1;
            tick();
            reset_a = 1'b0; reset_b = 1'b0;
        end
        for (int k = 0; k < 8; k++) begin
            ss_addr = {SS_ID, 8'(k)};
            ss_wdata = w[k];
            if (act) ss_we_a = 1'b1; else ss_we_b = 1'b1;
            tick();
            ss_we_a = 1'b0; ss_we_b = 1'b0;
        end
        act = !act;
        for (int k = 0; k < 8; k++) begin
            ss_addr = {SS_ID, 8'(k)};
            #1;
            if ((act ? ssr_b : ssr_a) !== w[k])
                fail($sformatf("cycle %0d: state word %0d reads %08x after restore, saved %08x",
                               c, k, act ? ssr_b : ssr_a, w[k]));
        end
        // a word of another module id must read 0
        ss_addr = {SS_ID + 8'd1, 8'd0};
        #1;
        if (ssr_a !== 32'd0 || ssr_b !== 32'd0) fail("state port answers another module id");
        nswaps++;
    endtask

    // ---- load INIT registers and flags through the state port (read-modify-write)
    task automatic load_init();
        logic [31:0] w6;
        ce = 1'b0;
        for (int k = 0; k < 4; k++) begin
            ss_addr = {SS_ID, 8'(k)};
            ss_wdata = {init_r[2 * k + 1], init_r[2 * k]};
            ss_we_a = 1'b1;
            tick();
            ss_we_a = 1'b0;
        end
        ss_addr = {SS_ID, 8'd6};
        #1;
        w6 = ssr_a;
        w6[4:0] = {init_i, init_f};
        ss_wdata = w6;
        ss_we_a = 1'b1;
        tick();
        ss_we_a = 1'b0;
    endtask

    task automatic check_regs(input string where, input ev_t e);
        logic [5:0] f;
        f = flags_of();
        for (int k = 0; k < 8; k++)
            if (reg_of(k) !== e.r[k])
                fail($sformatf("%s: R%0d=%04x, model %04x", where, k, reg_of(k), e.r[k]));
        if (f[5:2] !== e.f)
            fail($sformatf("%s: SZOC=%04b, model %04b", where, f[5:2], e.f));
        if (f[1] !== e.i || f[0] !== e.d)
            fail($sformatf("%s: I D=%b %b, model %b %b", where, f[1], f[0], e.i, e.d));
        nchecks++;
    endtask

    // ---- run one case
    task automatic run_case();
        int ei, ti, pi, si;
        logic prev_wait;
        case_fails = 0;
        nswaps = 0;
        act = 1'b0;
        for (int a = 0; a < 65536; a++) mem[a] = has_fill ? fill_word(fill_seed, a) : 16'd0;
        // memory words were read into the queue mw before this call
        foreach (mw_a[k]) mem[mw_a[k]] = mw_d[k];
        intrm = 1'b0; intr = 1'b0; busrq = 1'b0;
        ce = 1'b0;
        reset_a = 1'b1; reset_b = 1'b1;
        tick();
        reset_a = 1'b0; reset_b = 1'b0;
        iabs = 0;
        latch = 16'd0;
        // the reset IAB cycle (not in the model's count)
        intrm = line_at(0, 0); intr = line_at(1, 0); busrq = line_at(2, 0);
        #1;
        if (ph !== PH_IAB) fail($sformatf("reset: phase %0d, want IAB", ph));
        cpu_cycle();
        if (has_init) load_init();
        ei = 0; ti = 0; pi = 0; si = 0;
        prev_wait = 1'b0;
        for (int c = 0; c <= ncyc; c++) begin
            logic step_start;
            if (do_saves && si < saves.size() && saves[si] == c) begin
                swap(c);
                si++;
            end
            intrm = line_at(0, c + 1); intr = line_at(1, c + 1); busrq = line_at(2, c + 1);
            #1;
            // a step starts here?
            step_start = fch || ph == PH_INTAK || (waiting && !prev_wait) || hlt;
            if (c > 0 && step_start) begin
                if (ei >= evs.size() || evs[ei].c != c)
                    fail($sformatf("cycle %0d: a step starts, model's next step end is %0d",
                                   c, ei < evs.size() ? evs[ei].c : -1));
                else begin
                    check_regs($sformatf("step end %0d", c), evs[ei]);
                    ei++;
                end
            end else if (ei < evs.size() && evs[ei].c == c && c > 0)
                fail($sformatf("cycle %0d: model step ends, RTL in mid step", c));
            if (c == ncyc) break;
            // bus phase and contents
            begin
                cyc_t m;
                m = cyc[c];
                nchecks++;
                if (ph !== m.ph)
                    fail($sformatf("cycle %0d: phase %0d, model %0d", c, ph, m.ph));
                else begin
                    unique case (ph)
                        PH_BAR, PH_INTAK:
                            if (dout !== m.a) fail($sformatf("cycle %0d: phase %0d address %04x, model %04x", c, ph, dout, m.a));
                        PH_DTB, PH_ADAR:
                            if (latch !== m.a || din !== m.d)
                                fail($sformatf("cycle %0d: phase %0d at %04x data %04x, model %04x %04x", c, ph, latch, din, m.a, m.d));
                        PH_DW, PH_DWS:
                            if (latch !== m.a || dout !== m.d)
                                fail($sformatf("cycle %0d: phase %0d at %04x data %04x, model %04x %04x", c, ph, latch, dout, m.a, m.d));
                        PH_IAB:
                            if (din !== m.d) fail($sformatf("cycle %0d: IAB %04x, model %04x", c, din, m.d));
                        default: ;
                    endcase
                end
                if (busak !== m.fl[0]) fail($sformatf("cycle %0d: busak %b, model %b", c, busak, m.fl[0]));
                if (hlt !== m.fl[1]) fail($sformatf("cycle %0d: halted %b, model %b", c, hlt, m.fl[1]));
            end
            if (tci) begin
                if (ti < tcis.size() && tcis[ti] == c) ti++;
                else fail($sformatf("cycle %0d: TCI pulse not in the model", c));
            end
            if (pcit) begin
                if (pi < sins.size() && sins[pi] + 2 == c) pi++;
                else fail($sformatf("cycle %0d: SIN pulse not in the model", c));
            end
            prev_wait = waiting;
            cpu_cycle();
        end
        if (ei != evs.size()) fail($sformatf("%0d model steps not seen", evs.size() - ei));
        if (ti != tcis.size() || pi != sins.size())
            fail($sformatf("TCI %0d of %0d, SIN %0d of %0d", ti, tcis.size(), pi, sins.size()));
        check_regs("end", fin);
        if (hlt !== fin_h) fail($sformatf("end: halted %b, model %b", hlt, fin_h));
        if (do_saves && si != saves.size()) fail("save points not all used");
        ncases++;
        if (case_fails) begin
            fails++;
            $display("FAIL %s (%0d)", cname, case_fails);
        end else if (verbose)
            $display("ok   %s (%0d cycles, %0d steps, %0d swaps)", cname, ncyc, evs.size(), nswaps);
    endtask

    initial begin
        string fn, tok;
        int fd, n, x0, x1, x2, x3, x4, x5;
        int r [10];
        logic any = 1'b0;
        if (!$value$plusargs("vec=%s", fn)) begin
            $display("TB_CPU FAIL (no +vec=FILE)");
            $finish;
        end
        void'($value$plusargs("saves=%d", do_saves));
        void'($value$plusargs("verbose=%d", verbose));
        fd = $fopen(fn, "r");
        if (fd == 0) begin
            $display("TB_CPU FAIL (cannot open %s)", fn);
            $finish;
        end
        while (1) begin
            n = $fscanf(fd, "%s", tok);
            if (n != 1) break;
            if (tok == "CASE") begin
                n = $fscanf(fd, "%s", cname);
                cyc.delete(); evs.delete(); tcis.delete(); sins.delete(); saves.delete();
                rk.delete(); rlo.delete(); rhi.delete(); mw_a.delete(); mw_d.delete();
                has_init = 1'b0; has_fill = 1'b0;
            end else if (tok == "FILL") begin
                n = $fscanf(fd, "%h", fill_seed);
                has_fill = 1'b1;
            end else if (tok == "OPT") begin
                n = $fscanf(fd, "%h %h %h %h %h", x0, x1, x2, x3, x4);
                cfg_hlt_imm = x0[0]; cfg_mame = x1[0]; bext_mask = x2[15:0];
                vec_reset = x3[15:0]; vec_intr = x4[15:0];
            end else if (tok == "INIT") begin
                n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h",
                            r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9]);
                for (int k = 0; k < 8; k++) init_r[k] = r[k][15:0];
                init_f = r[8][3:0]; init_i = r[9][0];
                has_init = 1'b1;
            end else if (tok == "R") begin
                logic [31:0] hi;
                n = $fscanf(fd, "%h %h %h", x0, x1, hi);
                rk.push_back(x0); rlo.push_back(x1);
                rhi.push_back(hi == 32'hFFFFFFFF ? -1 : int'(hi));
            end else if (tok == "M") begin
                n = $fscanf(fd, "%h %h", x0, x1);
                mw_a.push_back(x0); mw_d.push_back(x1[15:0]);
            end else if (tok == "C") begin
                cyc_t m;
                n = $fscanf(fd, "%h %h %h %h", x0, x1, x2, x3);
                m.ph = x0[2:0]; m.a = x1[15:0]; m.d = x2[15:0]; m.fl = x3[1:0];
                cyc.push_back(m);
            end else if (tok == "E" || tok == "END") begin
                ev_t e;
                n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h",
                            e.c, r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], x0, x1, x2);
                for (int k = 0; k < 8; k++) e.r[k] = r[k][15:0];
                e.f = x0[3:0]; e.i = x1[0]; e.d = x2[0];
                if (tok == "E") evs.push_back(e);
                else begin
                    n = $fscanf(fd, "%h", x5);
                    fin = e; fin_h = x5[0]; ncyc = e.c;
                    if (cyc.size() != ncyc) begin
                        $display("  FAIL %s: %0d cycle records for %0d cycles", cname, cyc.size(), ncyc);
                        fails++;
                    end else
                        run_case();
                    any = 1'b1;
                end
            end else if (tok == "T") begin
                n = $fscanf(fd, "%h", x0); tcis.push_back(x0);
            end else if (tok == "P") begin
                n = $fscanf(fd, "%h", x0); sins.push_back(x0);
            end else if (tok == "S") begin
                n = $fscanf(fd, "%h", x0); saves.push_back(x0);
            end else begin
                $display("  FAIL bad record '%s'", tok);
                fails++;
                break;
            end
        end
        $fclose(fd);
        if (!any) fails++;
        $display("%0d cases, %0d checks, saves=%0d", ncases, nchecks, do_saves);
        if (fails == 0) $display("TB_CPU pass");
        else $display("TB_CPU FAIL (%0d)", fails);
        $finish;
    end

endmodule

`default_nettype wire
