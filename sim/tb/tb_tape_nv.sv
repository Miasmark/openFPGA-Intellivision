// tb_tape_nv: the ECS tape slot end to end at the bridge (intv_tape_nv on intv_tape's store; the
// walk and clear pulses as intv_core gives them at a load). Run by sim/tb/run_tb_tape_nv.sh
// (verilator --binary). The bridge side is the Pocket's: a word access every 100 clk_74a.
//   1  a load with a tape file: the Pocket writes 4,096 words (three blocks, then garbage), the
//      walk: the bridge reads the three blocks back and zeros after them (byte order: file byte
//      4i in bits 31:24)
//   2  a load without a file: the clear: all words 0
//   3  a file again, then the menu's erase (the clear): all words 0
//
// SPDX-License-Identifier: MIT

`timescale 1ns / 1ps
`default_nettype none

module tb_tape_nv;
    logic clk = 1'b0, clk74 = 1'b0;
    always #11.64 clk = !clk;            // clk_sys about 42.95 MHz
    always #6.73 clk74 = !clk74;         // clk_74a about 74.25 MHz

    logic        clr = 1'b0, walk = 1'b0, busy;
    logic        bridge_rd = 1'b0, bridge_wr = 1'b0;
    logic [31:0] bridge_addr = 32'd0, bridge_wr_data = 32'd0, bridge_rd_data;
    logic [13:0] nv_addr;
    logic        nv_we;
    logic [7:0]  nv_wdata, nv_q;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [15:0] q;
    logic [31:0] ss_rdata;
    /* verilator lint_on UNUSEDSIGNAL */

    intv_tape_nv slot (.clk_74a(clk74), .bridge_rd, .bridge_wr, .bridge_addr, .bridge_wr_data, .bridge_rd_data,
                       .clk, .nv_addr, .nv_we, .nv_wdata, .nv_q);
    intv_tape #(.SS_ID(8'h22)) tape (
        .clk, .mreset(1'b0), .ce(1'b0), .on(1'b1), .a(16'd0), .rd(1'b0), .wr(1'b0), .wdata(16'd0), .q,
        .fetch(1'b0), .hcnt(9'd0), .vcnt(9'd0), .instant(1'b0), .rom_ok(1'b0), .ovr_hit(), .ovr_q(),
        .clr, .walk, .busy, .nv_addr, .nv_we, .nv_wdata, .nv_q,
        .ss_addr(16'd0), .ss_we(1'b0), .ss_wdata(32'd0), .ss_rdata);

    int fails = 0;
    task automatic check(input bit ok, input string what);
        $display("  %s %s", ok ? "ok  " : "FAIL", what);
        if (!ok) fails++;
    endtask

    task automatic bwrite(input logic [31:0] a, input logic [31:0] d);
        @(posedge clk74); bridge_addr <= a; bridge_wr_data <= d; bridge_wr <= 1'b1;
        @(posedge clk74); bridge_wr <= 1'b0;
        repeat (100) @(posedge clk74);
    endtask
    task automatic bread(input logic [31:0] a, output logic [31:0] d);
        @(posedge clk74); bridge_addr <= a; bridge_rd <= 1'b1;
        @(posedge clk74); bridge_rd <= 1'b0;
        repeat (100) @(posedge clk74);
        d = bridge_rd_data;
    endtask

    // the file: three blocks (sync 9, $00, -N, N bytes) of 100, 37 and 3 bytes, then garbage
    logic [7:0] fb [16384];
    int tape_end;
    function automatic void make_file();
        int o = 0;
        int ns [3] = '{100, 37, 3};
        for (int b = 0; b < 3; b++) begin
            for (int k = 0; k < 9; k++) fb[o++] = 8'hAA;
            fb[o++] = 8'h00;
            fb[o++] = 8'(-ns[b]);
            fb[o++] = 8'((-ns[b]) >> 8);
            for (int i = 0; i < ns[b]; i++) fb[o++] = 8'(i * 7 + b);
        end
        tape_end = o;
        fb[o++] = 8'hAA; fb[o++] = 8'h00; fb[o++] = 8'h00; fb[o++] = 8'h80;     // a block cut at the top
        while (o < 16384) begin fb[o] = 8'(o * 13); o++; end
    endfunction

    task automatic load(input bit with_file);
        if (with_file) begin
            for (int i = 0; i < 4096; i++)
                bwrite(32'h30000000 + 32'(4 * i), {fb[4 * i], fb[4 * i + 1], fb[4 * i + 2], fb[4 * i + 3]});
            @(posedge clk); walk <= 1'b1; @(posedge clk); walk <= 1'b0;
        end else begin
            @(posedge clk); clr <= 1'b1; @(posedge clk); clr <= 1'b0;
        end
        repeat (5) @(posedge clk);
        while (busy) @(posedge clk);
    endtask

    task automatic readall(input bit want_file, output int ne);
        logic [31:0] d, w;
        ne = 0;
        for (int i = 0; i < 4096; i++) begin
            bread(32'h30000000 + 32'(4 * i), d);
            for (int k = 0; k < 4; k++)
                w[8 * (3 - k) +: 8] = want_file && 4 * i + k < tape_end ? fb[4 * i + k] : 8'h00;
            if (d != w) ne++;
        end
    endtask

    initial begin
        int ne;
        make_file();
        repeat (20) @(posedge clk);
        load(1);
        readall(1, ne);
        check(ne == 0, $sformatf("1 a load with a tape file: three blocks back, zeros after (%0d words differ; end %0d)", ne, tape_end));
        load(0);
        readall(0, ne);
        check(ne == 0, $sformatf("2 a load without a file: the tape is blank (%0d words not 0)", ne));
        load(1);
        @(posedge clk); clr <= 1'b1; @(posedge clk); clr <= 1'b0;
        repeat (5) @(posedge clk);
        while (busy) @(posedge clk);
        readall(0, ne);
        check(ne == 0, $sformatf("3 the erase: the tape is blank (%0d words not 0)", ne));
        $display("TB_TAPE_NV %s", fails == 0 ? "pass" : "FAIL");
        $finish;
    end
endmodule

`default_nettype wire
