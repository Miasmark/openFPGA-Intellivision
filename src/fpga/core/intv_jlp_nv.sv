// Intellivision core: the JLP flash slot (data slot 0x106, nonvolatile, at
// bridge address 0x20000000; build step 11; docs/JLP_NOTES.md 5.3). The
// Pocket writes the cartridge's .sav there when it loads one, and reads it
// back (the data table's size, apf_datatable: sectors x 1,536 bytes) when it
// saves. The file is jzIntv's (JLP_NOTES 4.1): the rows from JF.first, 96
// words each, every word little-endian, erased $FFFF, no header; the store's
// word k (intv_jlp, nv port) is the file's bytes 2k (low) and 2k + 1 (high),
// so bridge word i (bytes 4i .. 4i + 3, big-endian on the bridge) holds
// store words 2i and 2i + 1.
//
// The bridge's accesses cross to clk_sys one at a time (a toggle each way,
// as intv_ss_ctl's: the bridge leaves at least 88 clk_74a between them); a
// read answers on bridge_rd_data from then until the next read, which is
// the word the bridge takes with that next read (the 7800 core's lesson:
// answering the current address shifts every word by one).
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_jlp_nv (
    // clk_74a: the bridge
    input  wire logic        clk_74a,
    input  wire logic        bridge_rd,
    input  wire logic        bridge_wr,
    input  wire logic [31:0] bridge_addr,
    input  wire logic [31:0] bridge_wr_data,
    output logic [31:0]      bridge_rd_data,

    // clk_sys: the flash store's port (intv_jlp)
    input  wire logic        clk,
    output logic [13:0]      nv_addr,
    output logic             nv_we,
    output logic [15:0]      nv_wdata,
    input  wire logic [15:0] nv_q
);

    // ============================================== clk_74a side
    logic        b_t = 1'b0, b_we = 1'b0, rd_q = 1'b0, wr_q = 1'b0;
    logic [12:0] b_w = 13'd0;
    logic [31:0] b_d = 32'd0;
    logic [2:0]  r_s = 3'd0;
    logic        r_t = 1'b0;                  // clk_sys
    logic [31:0] r_q = 32'd0;                 // clk_sys, stable before r_t moves
    initial bridge_rd_data = 32'd0;

    /* verilator lint_off UNUSEDSIGNAL */
    wire logic [31:0] ba = bridge_addr;
    /* verilator lint_on UNUSEDSIGNAL */
    wire logic b_hit = ba[31:24] == 8'h20 && ba[23:15] == 9'd0;     // 6,144 words: 24,576 bytes

    always_ff @(posedge clk_74a) begin
        rd_q <= bridge_rd;
        wr_q <= bridge_wr;
        if (b_hit && ((bridge_rd && !rd_q) || (bridge_wr && !wr_q))) begin
            b_we <= bridge_wr;
            b_w  <= ba[14:2];
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

    typedef enum logic [2:0] {N_IDLE, N_W1, N_R0, N_R1, N_R2, N_R3} nst_t;
    nst_t        nst = N_IDLE;
    logic [15:0] dlo = 16'd0;             // a write's second word
    logic [15:0] w0 = 16'd0;
    initial begin nv_addr = 14'd0; nv_we = 1'b0; nv_wdata = 16'd0; end

    always_ff @(posedge clk) begin
        nv_we <= 1'b0;
        case (nst)
            N_IDLE: if (b_s[2] != b_s[1]) begin   // b_w, b_d stable since the toggle
                dlo <= b_d[15:0];
                nv_addr <= {b_w, 1'b0};
                if (b_we_s) begin
                    nv_we <= 1'b1;
                    nv_wdata <= {b_d[23:16], b_d[31:24]};
                    nst <= N_W1;
                end else
                    nst <= N_R0;
            end
            N_W1: begin
                nv_we <= 1'b1;
                nv_addr <= nv_addr + 14'd1;
                nv_wdata <= {dlo[7:0], dlo[15:8]};
                nst <= N_IDLE;
            end
            N_R0: nst <= N_R1;                    // nv_q: word 2i, next clk
            N_R1: begin
                w0 <= nv_q;
                nv_addr <= nv_addr + 14'd1;
                nst <= N_R2;
            end
            N_R2: nst <= N_R3;
            N_R3: begin
                r_q <= {w0[7:0], w0[15:8], nv_q[7:0], nv_q[15:8]};
                r_t <= !r_t;
                nst <= N_IDLE;
            end
            default: nst <= N_IDLE;
        endcase
    end

endmodule

`default_nettype wire
