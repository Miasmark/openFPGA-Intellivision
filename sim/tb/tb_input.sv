// Step-6 bench: intv_input against vectors from sim/tb/tb_input.py.
//
// Each line of +vec=FILE: class key1 joy1 key2 joy2 key3 joy3 trig3 mode
// swap pad_r pad_l, in hex. The bench drives the inputs, waits 4 clocks
// (2 synchroniser stages and the output register) and compares both bytes.
// It prints the first 20 mismatches, a count per class and TB_INPUT pass or
// TB_INPUT FAIL.
//
// SPDX-License-Identifier: MIT

`timescale 1ns/1ps
`default_nettype none

module tb_input;

    logic        clk = 1'b0;
    logic [31:0] key1, joy1, key2, joy2, key3, joy3;
    logic [15:0] trig3;
    logic [1:0]  mode;
    logic        swap;
    wire  [7:0]  pad_r, pad_l;

    always #5 clk = ~clk;

    intv_input dut (
        .clk        ( clk ),
        .cont1_key  ( key1 ),
        .cont1_joy  ( joy1 ),
        .cont2_key  ( key2 ),
        .cont2_joy  ( joy2 ),
        .cont3_key  ( key3 ),
        .cont3_joy  ( joy3 ),
        .cont3_trig ( trig3 ),
        .kp_mode    ( mode ),
        .swap       ( swap ),
        .pad_r      ( pad_r ),
        .pad_l      ( pad_l )
    );

    int fd, n, cls, nvec, nbad;
    int cnt [16], bad [16];
    logic [31:0] f [12];
    string path;

    initial begin
        if (!$value$plusargs("vec=%s", path)) begin
            $display("TB_INPUT FAIL (no +vec=FILE)");
            $finish;
        end
        fd = $fopen(path, "r");
        if (fd == 0) begin
            $display("TB_INPUT FAIL (cannot open %s)", path);
            $finish;
        end
        nvec = 0;
        nbad = 0;
        #1;     // before the first clock edge
        // Power-up value: no button pressed reads $FF on both ports
        if (pad_r !== 8'hFF || pad_l !== 8'hFF) begin
            $display("  FAIL  power-up pad_r %h pad_l %h, want FF FF", pad_r, pad_l);
            nbad++;
        end
        for (int i = 0; i < 16; i++) begin cnt[i] = 0; bad[i] = 0; end
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h\n",
                        f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8], f[9], f[10], f[11]);
            if (n != 12) begin
                if (n > 0) begin
                    $display("  FAIL  vector %0d: %0d fields", nvec, n);
                    nbad++;
                end
                break;
            end
            cls = f[0];
            {key1, joy1, key2, joy2, key3, joy3} = {f[1], f[2], f[3], f[4], f[5], f[6]};
            trig3 = f[7][15:0];
            mode  = f[8][1:0];
            swap  = f[9][0];
            repeat (4) @(posedge clk);
            #1;
            cnt[cls & 15]++;
            if (pad_r !== f[10][7:0] || pad_l !== f[11][7:0]) begin
                bad[cls & 15]++;
                if (nbad < 20)
                    $display("  FAIL  class %0d vector %0d: k1 %h j1 %h k2 %h j2 %h k3 %h j3 %h t3 %h mode %0d swap %0d: pad_r %h pad_l %h, want %h %h",
                             cls, nvec, key1, joy1, key2, joy2, key3, joy3, trig3, mode, swap,
                             pad_r, pad_l, f[10][7:0], f[11][7:0]);
                nbad++;
            end
            nvec++;
        end
        $fclose(fd);
        for (int i = 0; i < 16; i++)
            if (cnt[i] != 0)
                $display("  %s class %0d: %0d vectors, %0d wrong", bad[i] == 0 ? "ok  " : "FAIL", i, cnt[i], bad[i]);
        $display("%0d vectors, %0d wrong", nvec, nbad);
        $display("TB_INPUT %s", (nbad == 0 && nvec > 0) ? "pass" : "FAIL");
        $finish;
    end

endmodule

`default_nettype wire
