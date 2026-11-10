// tb_tape: the ECS cassette's engine (intv_tape, its store) against the model (tools/ecs_tape.py),
// driven by sim/tb/tb_tape.py. The bench runs a script of operations (+ops=FILE, one a line) and
// writes what the RTL answers (+log=FILE); the driver runs the same script on the model and
// compares line by line.
//
//   W c a v     at CPU cycle c, a CPU write of v to a                    (nothing logged)
//   R c a       at CPU cycle c, a CPU read of a                          -> Q n value
//   F n         the Pocket's file: bytes 0..n-1 of +file=HEX into the store's port B
//   K / C       the media's walk pulse / clear pulse (one clock)
//   M d         a machine reset (one clock), d clocks after the operation before
//   S c         the state words before CPU cycle c                      -> S w0 w1
//   L c w0 w1   a state load before CPU cycle c (word 0, then word 1)
//   Z           wait until the engine is idle
//   D           the whole store through port B                          -> D i byte (16,384 lines)
// A CPU cycle is CE clocks (one ce; cyc counts them). A cycle already past is a FAIL (the driver
// leaves room for the engine). IDLE (the rewind's motor-off time) is TB_IDLE.
//
// SPDX-License-Identifier: MIT

`timescale 1ns / 1ps
`default_nettype none

module tb_tape;
    localparam int CE = 8;
    logic clk = 1'b0;
    always #5 clk = !clk;

    logic        mreset = 1'b0, ce = 1'b0, rd = 1'b0, wr = 1'b0, clr = 1'b0, walk = 1'b0;
    logic [15:0] a = 16'd0, wdata = 16'd0, q;
    logic        busy;
    logic [13:0] nv_addr = 14'd0;
    logic        nv_we = 1'b0;
    logic [7:0]  nv_wdata = 8'd0, nv_q;
    logic [15:0] ss_addr = 16'd0;
    logic        ss_we = 1'b0;
    logic [31:0] ss_wdata = 32'd0, ss_rdata;

`ifndef TB_IDLE
`define TB_IDLE 3000
`endif
    intv_tape #(.SS_ID(8'h22), .IDLE(`TB_IDLE)) dut (
        .clk, .mreset, .ce, .on(1'b1), .a, .rd, .wr, .wdata, .q, .clr, .walk, .busy,
        .fetch(1'b0), .hcnt(9'd0), .vcnt(9'd0), .instant(1'b0), .rom_ok(1'b0), .ovr_hit(), .ovr_q(),
        .nv_addr, .nv_we, .nv_wdata, .nv_q, .ss_addr, .ss_we, .ss_wdata, .ss_rdata);

    // ce: one clock in CE; cyc: the CPU cycles done
    int phase = 0;
    longint cyc = 0;
    always @(posedge clk) begin
        phase <= phase == CE - 1 ? 0 : phase + 1;
        if (ce) cyc <= cyc + 1;
    end
    assign ce = phase == CE - 1;

    logic [7:0] file_b [16384];
    int fo, fd, n = 0;

    int late = 0;
    // to the clock whose ce is CPU cycle c (cyc == c while it lasts)
    task automatic at_cycle(input longint c);
        @(negedge clk);
        if (cyc > c) begin
            late++;
            $fdisplay(fo, "LATE %0d at %0d", c, cyc);
        end
        while (!(cyc == c && phase == CE - 1) && cyc <= c) @(negedge clk);
    endtask
    // before CPU cycle c's clock (cyc == c, not its ce clock)
    task automatic before_cycle(input longint c);
        @(negedge clk);
        if (cyc > c) begin late++; $fdisplay(fo, "LATE %0d at %0d", c, cyc); end
        while (cyc < c) @(negedge clk);
        while (phase == CE - 1) @(negedge clk);
    endtask

    initial begin
        string ops, log, fname, kind;
        longint g;
        int v, w0, w1, cnt;
        if (!$value$plusargs("ops=%s", ops) || !$value$plusargs("log=%s", log)) begin
            $display("TB_TAPE FAIL: +ops= and +log= needed");
            $finish;
        end
        if ($value$plusargs("file=%s", fname)) $readmemh(fname, file_b);
        fd = $fopen(ops, "r");
        fo = $fopen(log, "w");
        repeat (10) @(negedge clk);
        mreset = 1'b1; @(negedge clk); mreset = 1'b0;
        repeat (4) @(negedge clk);
        while ($fscanf(fd, "%s", kind) == 1) begin
            case (kind)
                "W": begin
                    void'($fscanf(fd, "%d %h %h", g, w0, v));
                    at_cycle(g);
                    a = 16'(w0); wdata = 16'(v); wr = 1'b1;     // this clock is the ce clock
                    @(negedge clk); wr = 1'b0;
                end
                "R": begin
                    void'($fscanf(fd, "%d %h", g, w0));
                    at_cycle(g);
                    a = 16'(w0); rd = 1'b1;
                    #1 $fdisplay(fo, "Q %0d %04x", n, q);
                    @(negedge clk); rd = 1'b0;
                    n++;
                end
                "F": begin
                    void'($fscanf(fd, "%d", cnt));
                    for (int i = 0; i < cnt; i++) begin
                        nv_addr = 14'(i); nv_wdata = file_b[i]; nv_we = 1'b1;
                        @(negedge clk);
                    end
                    nv_we = 1'b0;
                end
                "K": begin walk = 1'b1; @(negedge clk); walk = 1'b0; end
                "C": begin clr = 1'b1; @(negedge clk); clr = 1'b0; end
                "M": begin
                    void'($fscanf(fd, "%d", cnt));
                    repeat (cnt) @(negedge clk);
                    mreset = 1'b1; @(negedge clk); mreset = 1'b0;
                end
                "S": begin
                    void'($fscanf(fd, "%d", g));
                    before_cycle(g);
                    ss_addr = 16'h2200; #1 w0 = int'(ss_rdata);
                    ss_addr = 16'h2201; #1 w1 = int'(ss_rdata);
                    $fdisplay(fo, "S %08x %08x", w0, w1);
                    ss_addr = 16'h0000;
                end
                "L": begin
                    void'($fscanf(fd, "%d %h %h", g, w0, w1));
                    before_cycle(g);
                    ss_addr = 16'h2200; ss_wdata = 32'(w0); ss_we = 1'b1; @(negedge clk);
                    ss_addr = 16'h2201; ss_wdata = 32'(w1); @(negedge clk);
                    ss_we = 1'b0; ss_addr = 16'h0000;
                end
                "Z": begin
                    repeat (4) @(negedge clk);
                    while (busy) @(negedge clk);
                    repeat (8) @(negedge clk);       // the read ahead
                end
                "D": begin
                    repeat (4) @(negedge clk);
                    while (busy) @(negedge clk);
                    for (int i = 0; i < 16384; i++) begin
                        nv_addr = 14'(i); repeat (3) @(negedge clk);
                        $fdisplay(fo, "D %0d %02x", i, nv_q);
                    end
                end
                default: begin
                    $display("TB_TAPE FAIL: unknown op %s", kind);
                    $finish;
                end
            endcase
        end
        $fdisplay(fo, "END late %0d", late);
        $fclose(fo);
        $display("TB_TAPE done");
        $finish;
    end
endmodule

`default_nettype wire
