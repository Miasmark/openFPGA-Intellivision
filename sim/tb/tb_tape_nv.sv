// tb_tape_nv: the ECS tape slot end to end at the bridge (intv_tape: intv_tape_nv, the store, the
// clear at a load without a file, the erase). Run by sim/tb/run_tb_tape_nv.sh (verilator
// --binary). The bridge side is the Pocket's: a word access every 100 clk_74a.
//   1  a load with a file: the Pocket writes 4,096 words, then len_valid rises: the tape keeps
//      them; read back through the bridge: the same words (byte order: file byte 4i in 31:24)
//   2  a load without a file: len_valid falls and rises with no write: the tape reads all 0
//   3  a file again, then the erase pulse: all 0
//   4  (+trial) the trial stamp: bytes 0-14 "ECS TAPE TRIAL ", byte 15 one more than before
//
// SPDX-License-Identifier: MIT

`timescale 1ns / 1ps
`default_nettype none

module tb_tape_nv;
    logic clk = 1'b0, clk74 = 1'b0;
    always #11.64 clk = !clk;            // clk_sys about 42.95 MHz
    always #6.73 clk74 = !clk74;         // clk_74a about 74.25 MHz

    logic        len_valid = 1'b0, erase = 1'b0, trial = 1'b0;
    logic        bridge_rd = 1'b0, bridge_wr = 1'b0;
    logic [31:0] bridge_addr = 32'd0, bridge_wr_data = 32'd0, bridge_rd_data;

    intv_tape dut (.clk, .len_valid, .erase, .trial, .clk_74a(clk74), .bridge_rd, .bridge_wr,
                   .bridge_addr, .bridge_wr_data, .bridge_rd_data);

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
    // the bridge takes a read's data with the next read: read i, then the value is word i
    // on bridge_rd_data once the answer has crossed (100 clk_74a later)
    task automatic bread(input logic [31:0] a, output logic [31:0] d);
        @(posedge clk74); bridge_addr <= a; bridge_rd <= 1'b1;
        @(posedge clk74); bridge_rd <= 1'b0;
        repeat (100) @(posedge clk74);
        d = bridge_rd_data;
    endtask

    function automatic logic [31:0] pat(input int i);
        return {8'(4 * i + 1), 8'(4 * i + 2) ^ 8'h5A, 8'(i >> 2), 8'(i * 7 + 3)};
    endfunction

    task automatic load(input bit with_file);
        len_valid <= 1'b0;
        repeat (50) @(posedge clk74);
        if (with_file)
            for (int i = 0; i < 4096; i++) bwrite(32'h30000000 + 32'(4 * i), pat(i));
        len_valid <= 1'b1;
        repeat (20000) @(posedge clk);       // the clear (16,384 clocks) has time
    endtask

    task automatic readall(output int ne_pat, output int ne_zero);
        logic [31:0] d;
        ne_pat = 0; ne_zero = 0;
        for (int i = 0; i < 4096; i++) begin
            bread(32'h30000000 + 32'(4 * i), d);
            if (d != pat(i)) ne_pat++;
            if (d != 32'd0) ne_zero++;
        end
    endtask

    initial begin
        int np, nz;
        logic [31:0] d0, d1, d2, d3;
        repeat (20) @(posedge clk);
        load(1);
        readall(np, nz);
        check(np == 0, $sformatf("1 a load with a file: 4,096 words read back as written (%0d differ)", np));
        load(0);
        readall(np, nz);
        check(nz == 0, $sformatf("2 a load without a file: the tape is blank (%0d words not 0)", nz));
        load(1);
        @(posedge clk); erase <= 1'b1; @(posedge clk); erase <= 1'b0;
        repeat (20000) @(posedge clk);
        readall(np, nz);
        check(nz == 0, $sformatf("3 the erase: the tape is blank (%0d words not 0)", nz));
        // 4: the trial stamp twice on a blank tape: count 2
        repeat (2) begin
            @(posedge clk); trial <= 1'b1; @(posedge clk); trial <= 1'b0;
            repeat (100) @(posedge clk);
        end
        bread(32'h30000000, d0); bread(32'h30000004, d1); bread(32'h30000008, d2); bread(32'h3000000C, d3);
        check({d0, d1, d2, d3} == {"ECS TAPE TRIAL ", 8'd2},
              $sformatf("4 the trial stamp: %h %h %h %h", d0, d1, d2, d3));
        $display("TB_TAPE_NV %s", fails == 0 ? "pass" : "FAIL");
        $finish;
    end
endmodule

`default_nettype wire
