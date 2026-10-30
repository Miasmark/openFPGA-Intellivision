// Step-10 bench, bus level (docs/VOICE_NOTES.md 8.7): intv_voice.sv on CPU
// cycles (a ce every 48 clk_sys, as the machine's) against
// tools/sp0256.py VoiceBus: the sample enable, the busy window (reads of the
// values at the sample, a held write), at 10 kHz or MAME's rate (INC, WRAP).
// sim/tb/tb_voice.py writes the command file and compares.
//
//   C k        k cycles without an access
//   W a d      a write at the end of the next cycle ("$0080 + a")
//   R a        a read at the end of the next cycle: "R <value, 4 hex>"
//   X          wait for the chip to be idle, save every state word, reset
//              the module (mreset), write the words back
// Output also "S <cycle> <sample, 4 hex>" for every sample made (the cycle
// whose end fired it) and at the end "L <late>".
//
// SPDX-License-Identifier: MIT

`timescale 1ns/1ps
`default_nettype none

module tb_voicebus #(
    parameter logic [31:0] INC  = 32'd88,
    parameter logic [31:0] WRAP = 32'd7875
);
    logic clk = 1'b0;
    always #5 clk = ~clk;

    logic        mreset = 1'b1, ce = 1'b0, wr = 1'b0;
    logic [15:0] a = 16'd0, wdata = 16'd0;
    wire  logic  hit, on, busy, late;
    wire  logic [15:0] q;
    wire  logic signed [15:0] out;
    wire  logic [10:0] rom_addr;
    logic [7:0]  rom_q = 8'd0;
    logic [7:0]  rom [2048];
    logic        ss_en = 1'b0, ss_we = 1'b0;
    logic [15:0] ss_addr = 16'd0;
    logic [31:0] ss_wdata = 32'd0;
    wire  logic [31:0] ss_rdata;

    intv_voice #(.SS_ID(8'h18), .INC(INC), .WRAP(WRAP)) dut (
        .clk, .mreset, .mode(1'b1), .ce, .run(1'b1), .a, .wr, .wdata, .hit, .q,
        .rom_addr, .rom_q, .dac7(1'b0), .level(3'd2), .audio_stb(1'b0), .out, .on, .busy, .late,
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata);

    always_ff @(posedge clk) rom_q <= rom[rom_addr];

    int fo, fc, cyc = 0, fire_cyc = 0;
    string line;
    localparam int NW = 24 + 64;
    logic [31:0] saved [NW];

    // the cycle a sample fired at, and the sample when it is made
    always @(posedge clk) begin
        if (dut.fire) fire_cyc = cyc;
        if (dut.c_done) $fdisplay(fo, "S %0d %04x", fire_cyc, dut.c_sample);
    end

    // one cycle: 47 quiet clk_sys, then the ce (with this cycle's access)
    task automatic cycle(input bit w, input bit r, input int aa, input int dd);
        repeat (47) @(negedge clk);
        ce = 1'b1;
        if (w || r) a = 16'h0080 | 16'(aa);
        wr = w; wdata = 16'(dd);
        #1;
        if (r) $fdisplay(fo, "R %04x", q);
        @(negedge clk);
        ce = 1'b0; wr = 1'b0;
        cyc++;
    endtask

    function automatic logic [15:0] sw_addr(input int i);
        return i < 24 ? {8'h18, 8'(i)} : {8'h19, 8'(i - 24)};
    endfunction

    task automatic save_restore();
        while (busy) @(negedge clk);
        @(negedge clk); ss_en = 1'b1;
        repeat (2) @(negedge clk);
        for (int i = 0; i < NW; i++) begin
            ss_addr = sw_addr(i);
            @(negedge clk); @(negedge clk);
            saved[i] = ss_rdata;
        end
        ss_en = 1'b0;
        @(negedge clk); mreset = 1'b1;
        @(negedge clk); mreset = 1'b0;
        // a load lands in a machine whose FIFO RAM holds what ran before (reset
        // does not clear it): fill it with other words, so a FIFO not restored shows
        for (int i = 0; i < 64; i++) dut.chip.fifo.mem[i] = 10'(i * 157 + 291);
        @(negedge clk); ss_en = 1'b1;
        @(negedge clk);
        for (int i = 0; i < NW; i++) begin
            ss_addr = sw_addr(i); ss_wdata = saved[i]; ss_we = 1'b1;
            @(negedge clk); ss_we = 1'b0;
            @(negedge clk);
        end
        ss_en = 1'b0;
        repeat (3) @(negedge clk);
    endtask

    initial begin
        string rf, cf, of, c;
        int aa, dd, k;
        if (!$value$plusargs("rom=%s", rf) || !$value$plusargs("cmd=%s", cf) || !$value$plusargs("out=%s", of))
            $fatal(1, "give +rom= +cmd= +out=");
        $readmemh(rf, rom);
        fo = $fopen(of, "w");
        fc = $fopen(cf, "r");
        repeat (4) @(negedge clk);
        mreset = 1'b0;
        cycle(1'b0, 1'b0, 0, 0);              // the ce that starts cycle 0 (not counted)
        cyc = 0;
        while (!$feof(fc)) begin
            if ($fgets(line, fc) == 0) break;
            c = line.substr(0, 0);
            if (c == "C") begin
                void'($sscanf(line, "C %d", k));
                for (int i = 0; i < k; i++) cycle(1'b0, 1'b0, 0, 0);
            end else if (c == "W") begin
                void'($sscanf(line, "W %d %h", aa, dd));
                cycle(1'b1, 1'b0, aa, dd);
            end else if (c == "R") begin
                void'($sscanf(line, "R %d", aa));
                cycle(1'b0, 1'b1, aa, 0);
            end else if (c == "X")
                save_restore();
        end
        repeat (400) @(negedge clk);
        $fdisplay(fo, "L %0d", late);
        $fclose(fo);
        $finish;
    end
endmodule

`default_nettype wire
