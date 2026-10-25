// Intellivision core: controller for the Pocket's SRAM (DESIGN.md 5.1).
//
// The SRAM is an AS6C2016-55: 128K x 16, asynchronous, 55 ns. This core
// keeps the cartridge image, the cartridge RAM and the ECS ROM there
// (intv_media.sv). One CPU bus cycle is 1.12 us, so a plain one-access-at-
// a-time controller on clk_sys (23.3 ns) is ample; no SDRAM and no burst.
//
// Request port: hold req until ack. A request is taken only while the
// controller is idle (rdy); the address, data and byte enables are
// registered then, so the master may change them after ack.
//
//   read   cycle 0  address out, OE low (both bytes)
//          cycles 1 .. RD_CYC-1  wait
//          end of cycle RD_CYC-1  sample DQ, OE high, ack
//          the address is stable RD_CYC x 23.3 ns (3: 69.8 ns >= tAA 55)
//   write  cycle 0  address and data out, WE high (tAS = 0 is met with margin)
//          cycles 1 .. WR_CYC  WE low with the byte enables (3: 69.8 ns >=
//          tWP 45, tAW 50)
//          cycle WR_CYC + 1  WE high, data still driven (tDH, tWR = 0), ack
//
// Byte enables: be[1] the upper byte (UB), be[0] the lower byte (LB).
// OE and WE are never low together, and DQ is driven only in a write.
//
// Load-time and bus-cycle memory only: nothing here is machine state.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_sram #(
    parameter int RD_CYC = 3,
    parameter int WR_CYC = 3
) (
    input  wire logic        clk,
    input  wire logic        reset,

    input  wire logic        req,
    input  wire logic        we,
    input  wire logic [16:0] addr,
    input  wire logic [15:0] wdata,
    input  wire logic [1:0]  be,
    output logic             rdy,          // idle: a request is taken now
    output logic             ack,          // one clk: done (rdata valid for a read)
    output logic [15:0]      rdata,

    output logic [16:0]      sram_a,
    output logic [15:0]      sram_dq_out,
    output logic             sram_dq_oe,
    input  wire logic [15:0] sram_dq_in,
    output logic             sram_oe_n,
    output logic             sram_we_n,
    output logic             sram_ub_n,
    output logic             sram_lb_n
);

    typedef enum logic [2:0] {S_IDLE, S_RD, S_WS, S_WP, S_WH} state_t;
    state_t     st = S_IDLE;
    logic [2:0] cnt = 3'd0;

    initial begin
        sram_a = 17'd0; sram_dq_out = 16'd0; sram_dq_oe = 1'b0;
        sram_oe_n = 1'b1; sram_we_n = 1'b1; sram_ub_n = 1'b1; sram_lb_n = 1'b1;
        ack = 1'b0; rdata = 16'd0;
    end

    assign rdy = st == S_IDLE && !ack;

    always_ff @(posedge clk) begin
        ack <= 1'b0;
        if (reset) begin
            st <= S_IDLE;
            sram_oe_n <= 1'b1; sram_we_n <= 1'b1; sram_dq_oe <= 1'b0;
            sram_ub_n <= 1'b1; sram_lb_n <= 1'b1;
        end else case (st)
            S_IDLE: if (req && rdy) begin
                sram_a <= addr;
                if (we) begin
                    sram_dq_out <= wdata;
                    sram_dq_oe  <= 1'b1;
                    st <= S_WS;
                end else begin
                    sram_oe_n <= 1'b0;
                    sram_ub_n <= 1'b0;
                    sram_lb_n <= 1'b0;
                    cnt <= 3'(RD_CYC - 1);
                    st <= S_RD;
                end
                // byte enables of a write are applied with WE (S_WS)
                if (we) begin
                    sram_ub_n <= !be[1];
                    sram_lb_n <= !be[0];
                end
            end
            S_RD: if (cnt != 3'd0) cnt <= cnt - 3'd1;
                  else begin
                      rdata <= sram_dq_in;
                      sram_oe_n <= 1'b1;
                      sram_ub_n <= 1'b1;
                      sram_lb_n <= 1'b1;
                      ack <= 1'b1;
                      st <= S_IDLE;
                  end
            S_WS: begin
                sram_we_n <= 1'b0;
                cnt <= 3'(WR_CYC - 1);
                st <= S_WP;
            end
            S_WP: if (cnt != 3'd0) cnt <= cnt - 3'd1;
                  else begin
                      sram_we_n <= 1'b1;
                      st <= S_WH;
                  end
            S_WH: begin
                sram_dq_oe <= 1'b0;
                sram_ub_n <= 1'b1;
                sram_lb_n <= 1'b1;
                ack <= 1'b1;
                st <= S_IDLE;
            end
            default: st <= S_IDLE;
        endcase
    end

endmodule

`default_nettype wire
