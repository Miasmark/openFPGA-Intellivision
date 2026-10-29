// Step-10 bench (DESIGN.md 9; docs/VOICE_NOTES.md 8.7): sp0256.sv against
// the model tools/sp0256.py, driven by a command file that
// sim/tb/tb_voice.py writes (from the MAME references' bus logs, the test
// program and random streams) and compares line by line with the model's.
//
//   N k        make k samples: each line "S <sample, 4 hex>"
//   W a d      a bus write (a: 0 = $0080, 1 = $0081; d hex)
//   R a        a read: "R a <value> <pc> <halted> <lrq> <rpt> <cnt> <stack>"
//   X          save every state word through the state port, reset the
//              module (the power-up state), write the words back: the run
//              must go on as if nothing happened ("X <words hashed>")
//
// +rom=FILE (2,048 bytes as hex lines, ivoice.bin) +cmd=FILE +out=FILE
//
// SPDX-License-Identifier: MIT

`timescale 1ns/1ps
`default_nettype none

module tb_voice;
    logic clk = 1'b0;
    always #5 clk = ~clk;

    logic        reset = 1'b1, wr = 1'b0, wa = 1'b0, step = 1'b0;
    logic [15:0] wd = 16'd0;
    wire  logic  lrq, full, busy, done;
    wire  logic [15:0] sample;
    wire  logic [10:0] rom_addr;
    logic [7:0]  rom_q = 8'd0;
    logic [7:0]  rom [2048];
    logic        ss_en = 1'b0, ss_we = 1'b0;
    logic [15:0] ss_addr = 16'd0;
    logic [31:0] ss_wdata = 32'd0;
    wire  logic [31:0] ss_rdata;

    sp0256 #(.SS_ID(8'h18)) dut (
        .clk, .reset, .wr, .wa, .wd, .lrq, .full, .step, .busy, .done, .sample,
        .rom_addr, .rom_q, .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata);

    always_ff @(posedge clk) rom_q <= rom[rom_addr];

    int fo, fc, samples = 0, longest = 0;
    string line;
    localparam int NW = 20 + 64;
    logic [31:0] saved [NW];

    function automatic logic [15:0] sw_addr(input int i);
        return i < 20 ? {8'h18, 8'(i)} : {8'h19, 8'(i - 20)};
    endfunction

    task automatic one_sample();
        int n;
        @(negedge clk); step = 1'b1;
        @(negedge clk); step = 1'b0;
        n = 1;
        while (!done) begin @(negedge clk); n++; end
        if (n > longest) longest = n;
        $fdisplay(fo, "S %04x", sample);
        samples++;
    endtask

    task automatic save_restore();
        logic [31:0] h;
        @(negedge clk); ss_en = 1'b1;
        repeat (2) @(negedge clk);
        for (int i = 0; i < NW; i++) begin
            ss_addr = sw_addr(i);
            @(negedge clk); @(negedge clk);
            saved[i] = ss_rdata;
        end
        ss_en = 1'b0;
        @(negedge clk); reset = 1'b1;
        @(negedge clk); reset = 1'b0;
        @(negedge clk); ss_en = 1'b1;
        @(negedge clk);
        for (int i = 0; i < NW; i++) begin
            ss_addr = sw_addr(i); ss_wdata = saved[i]; ss_we = 1'b1;
            @(negedge clk); ss_we = 1'b0;
            @(negedge clk);
        end
        ss_en = 1'b0;
        repeat (3) @(negedge clk);
        h = 32'h811C9DC5;
        for (int i = 0; i < NW; i++) h = (h ^ saved[i]) * 32'h01000193;
        $fdisplay(fo, "X %08x", h);
    endtask

    initial begin
        string rf, cf, of, c;
        int a, d, k;
        if (!$value$plusargs("rom=%s", rf) || !$value$plusargs("cmd=%s", cf) || !$value$plusargs("out=%s", of))
            $fatal(1, "give +rom= +cmd= +out=");
        $readmemh(rf, rom);
        fo = $fopen(of, "w");
        fc = $fopen(cf, "r");
        repeat (4) @(negedge clk);
        reset = 1'b0;
        repeat (2) @(negedge clk);
        while (!$feof(fc)) begin
            if ($fgets(line, fc) == 0) break;
            c = line.substr(0, 0);
            if (c == "N") begin
                void'($sscanf(line, "N %d", k));
                for (int i = 0; i < k; i++) one_sample();
            end else if (c == "W") begin
                void'($sscanf(line, "W %d %h", a, d));
                @(negedge clk); wr = 1'b1; wa = a[0]; wd = 16'(d);
                @(negedge clk); wr = 1'b0;
            end else if (c == "R") begin
                void'($sscanf(line, "R %d", a));
                @(negedge clk);
                $fdisplay(fo, "R %0d %04x %0d %0d %0d %0d %0d %0d", a,
                          a[0] ? {full, 15'd0} : {lrq, 15'd0},
                          dut.pc, dut.halted, dut.lrq, dut.rpt, dut.cnt, dut.stack);
            end else if (c == "X")
                save_restore();
        end
        $fdisplay(fo, "E samples %0d longest %0d", samples, longest);
        $fclose(fo);
        $finish;
    end
endmodule

`default_nettype wire
