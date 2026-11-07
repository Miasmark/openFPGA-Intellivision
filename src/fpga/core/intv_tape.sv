// Intellivision core: the ECS tape (docs/ECS_NOTES.md 6). TRIAL VERSION (two-slot Pocket trial):
// the store (intv_tape_store), its nonvolatile slot (intv_tape_nv, data slot 0x107), the clear
// at a load without a tape file (the JLP flash's rule) and a trial op that stamps the first 16
// bytes "ECS TAPE TRIAL " plus a count (byte 15) one higher than the tape's. The UART engine
// comes next.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_tape (
    input  wire logic        clk,
    input  wire logic        len_valid,       // clk_74a level: the load's "all complete"
    input  wire logic        erase,           // clk_sys pulse: blank the tape
    input  wire logic        trial,           // clk_sys pulse: the trial stamp

    // the nonvolatile slot (clk_74a bridge)
    input  wire logic        clk_74a,
    input  wire logic        bridge_rd,
    input  wire logic        bridge_wr,
    input  wire logic [31:0] bridge_addr,
    input  wire logic [31:0] bridge_wr_data,
    output logic [31:0]      bridge_rd_data
);

    logic [13:0] b_addr;
    logic        b_we;
    logic [7:0]  b_d, b_q;
    intv_tape_nv nv (
        .clk_74a, .bridge_rd, .bridge_wr, .bridge_addr, .bridge_wr_data, .bridge_rd_data,
        .clk, .nv_addr(b_addr), .nv_we(b_we), .nv_wdata(b_d), .nv_q(b_q));

    logic [13:0] a_addr = 14'd0;
    logic        a_we = 1'b0;
    logic [7:0]  a_d = 8'd0, a_q;
    intv_tape_store ram (
        .clk, .a_addr, .a_we, .a_d, .a_q, .b_addr, .b_we, .b_d, .b_q);

    // the clear: at the load's len_valid rise, unless the Pocket wrote a tape file in this load
    logic [2:0] lv_s = 3'd0;
    logic       nv_seen = 1'b0;
    always_ff @(posedge clk) begin
        lv_s <= {lv_s[1:0], len_valid};
        if (lv_s[2:1] == 2'b01) nv_seen <= 1'b0;
        else if (b_we) nv_seen <= 1'b1;
    end
    wire logic clr_req = (lv_s[2:1] == 2'b01 && !nv_seen) || erase;

    // port A: the clear (16,384 writes) and the trial stamp
    typedef enum logic [2:0] {T_IDLE, T_CLR, T_R0, T_R1, T_R2, T_W} tst_t;
    tst_t       st = T_IDLE;
    logic [7:0] cnt = 8'd0;
    logic       tr_pend = 1'b0;
    localparam logic [8 * 15 - 1:0] STAMP = "ECS TAPE TRIAL ";

    always_ff @(posedge clk) begin
        a_we <= 1'b0;
        if (trial) tr_pend <= 1'b1;
        case (st)
            T_IDLE: if (clr_req) begin
                a_addr <= 14'd0; a_d <= 8'd0; a_we <= 1'b1; st <= T_CLR;
            end else if (tr_pend) begin
                tr_pend <= 1'b0;
                a_addr <= 14'd15; st <= T_R0;
            end
            T_CLR: if (a_addr == 14'h3FFF) st <= T_IDLE;
                   else begin a_addr <= a_addr + 14'd1; a_we <= 1'b1; end
            T_R0: st <= T_R1;
            T_R1: st <= T_R2;
            T_R2: begin                               // a_q = byte 15
                cnt <= a_q + 8'd1;
                a_addr <= 14'd0; a_d <= STAMP[8 * 14 +: 8]; a_we <= 1'b1;
                st <= T_W;
            end
            T_W: if (a_addr == 14'd15) st <= T_IDLE;
                 else begin
                     a_addr <= a_addr + 14'd1;
                     a_d <= a_addr == 14'd14 ? cnt : STAMP[8 * (13 - 32'(a_addr)) +: 8];
                     a_we <= 1'b1;
                 end
            default: st <= T_IDLE;
        endcase
    end

endmodule

`default_nettype wire
