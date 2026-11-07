// Intellivision core: the ECS tape slot (data slot 0x107, nonvolatile, at bridge address
// 0x30000000; docs/ECS_NOTES.md 6). The Pocket writes the game's .ecs there when it loads one,
// and reads it back (the data table's size, apf_datatable: 16,384 bytes while the ECS is on) when
// it saves. The file is jzIntv's .ecs byte stream (tools/ecs_tape.py): byte k of the file is
// store byte k (intv_tape_store, port B); bridge word i (bytes 4i .. 4i + 3) holds file byte 4i in
// bits 31:24 (big-endian on the bridge, as the other slots).
//
// The crossing is intv_jlp_nv's: one access at a time, a toggle each way (the bridge leaves at
// least 88 clk_74a between them); a read answers on bridge_rd_data from then until the next read,
// which is the word the bridge takes with that next read.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_tape_nv (
    // clk_74a: the bridge
    input  wire logic        clk_74a,
    input  wire logic        bridge_rd,
    input  wire logic        bridge_wr,
    input  wire logic [31:0] bridge_addr,
    input  wire logic [31:0] bridge_wr_data,
    output logic [31:0]      bridge_rd_data,

    // clk_sys: the store's port B
    input  wire logic        clk,
    output logic [13:0]      nv_addr,
    output logic             nv_we,
    output logic [7:0]       nv_wdata,
    input  wire logic [7:0]  nv_q
);

    // ============================================== clk_74a side
    logic        b_t = 1'b0, b_we = 1'b0, rd_q = 1'b0, wr_q = 1'b0;
    logic [11:0] b_w = 12'd0;
    logic [31:0] b_d = 32'd0;
    logic [2:0]  r_s = 3'd0;
    logic        r_t = 1'b0;                  // clk_sys
    logic [31:0] r_q = 32'd0;                 // clk_sys, stable before r_t moves
    initial bridge_rd_data = 32'd0;

    /* verilator lint_off UNUSEDSIGNAL */
    wire logic [31:0] ba = bridge_addr;
    /* verilator lint_on UNUSEDSIGNAL */
    wire logic b_hit = ba[31:24] == 8'h30 && ba[23:14] == 10'd0;    // 4,096 words: 16,384 bytes

    always_ff @(posedge clk_74a) begin
        rd_q <= bridge_rd;
        wr_q <= bridge_wr;
        if (b_hit && ((bridge_rd && !rd_q) || (bridge_wr && !wr_q))) begin
            b_we <= bridge_wr;
            b_w  <= ba[13:2];
            b_d  <= bridge_wr_data;
            b_t  <= !b_t;
        end
        r_s <= {r_s[1:0], r_t};
        if (r_s[2] != r_s[1])
            bridge_rd_data <= r_q;
    end

    // ============================================== clk_sys side
    logic [2:0] b_s = 3'd0;
    logic       b_we_s = 1'b0;
    always_ff @(posedge clk) begin
        b_s <= {b_s[1:0], b_t};
        b_we_s <= b_we;
    end

    // a word is four bytes, file order: bits 31:24 first
    logic [1:0]  n = 2'd0;                    // the byte in the word
    logic        busy = 1'b0, rd = 1'b0;
    logic [1:0]  wt = 2'd0;                   // a read's wait for nv_q
    logic [31:0] w = 32'd0;
    initial begin nv_addr = 14'd0; nv_we = 1'b0; nv_wdata = 8'd0; end

    always_ff @(posedge clk) begin
        nv_we <= 1'b0;
        if (!busy) begin
            if (b_s[2] != b_s[1]) begin       // b_w, b_d stable since the toggle
                busy <= 1'b1;
                rd   <= !b_we_s;
                n    <= 2'd0;
                w    <= b_d;
                nv_addr <= {b_w, 2'd0};
                wt   <= 2'd0;
                if (b_we_s) begin
                    nv_we <= 1'b1;
                    nv_wdata <= b_d[31:24];
                end
            end
        end else if (!rd) begin               // writes: one byte a clock
            if (n == 2'd3) busy <= 1'b0;
            else begin
                n <= n + 2'd1;
                nv_addr <= nv_addr + 14'd1;
                nv_we <= 1'b1;
                nv_wdata <= w[8 * (2 - 32'(n)) +: 8];
            end
        end else if (wt != 2'd2) wt <= wt + 2'd1;  // nv_q of nv_addr, two clocks after
        else begin
            w <= {w[23:0], nv_q};
            wt <= 2'd0;
            if (n == 2'd3) begin
                r_q <= {w[23:0], nv_q};
                r_t <= !r_t;
                busy <= 1'b0;
            end else begin
                n <= n + 2'd1;
                nv_addr <= nv_addr + 14'd1;
            end
        end
    end

endmodule

`default_nettype wire
