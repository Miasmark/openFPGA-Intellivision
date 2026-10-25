// Intellivision core: a block RAM with a save-state port, for the
// scratchpad, System RAM and GRAM (DESIGN.md 3 modules 5 and 8; build step
// 3) and the STIC's row and line buffers (step 4).
//
// The bus side reads q one clock after addr (registered output; the bus
// fabric's address is stable for whole CPU cycles) and writes on we. The
// contents start at 0 (the FPGA's power-up state; RAM keeps its contents
// through a machine reset, as RAM chips do).
//
// Save state (DESIGN.md 4.3): one state word per RAM word, WORDS of them,
// numbered from module id SS_ID word 0 on through as many ids as needed
// (256 words per id). While ss_en is high (the machine frozen) the state
// port owns port A: ss_rdata gives the addressed word one clock after
// ss_addr (0 when not addressed), and ss_we writes it. ss_en must drop at
// least two clocks before the machine runs again.
//
// Port B (build step 4) is the STIC's: read only, q_b one clock after
// addr_b, every clock (also while ss_en is high). A reader must take q_b
// only when addr_b has not changed in the clock before, so that a freeze,
// a restore or a resume between the two clocks cannot hand it a stale word
// (intv_stic.sv keeps to this). A write and a port-B read of the same word
// in the same clock never happen in the machine.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_ram #(
    parameter int         AW    = 8,
    parameter int         DW    = 8,
    parameter int         WORDS = 256,        // used words (state words)
    parameter logic [7:0] SS_ID = 8'h06
) (
    input  wire logic          clk,
    input  wire logic [AW-1:0] addr,
    input  wire logic          we,
    input  wire logic [DW-1:0] d,
    output logic      [DW-1:0] q,
    input  wire logic [AW-1:0] addr_b,
    output logic      [DW-1:0] q_b,

    input  wire logic          ss_en,
    input  wire logic [15:0]   ss_addr,
    input  wire logic          ss_we,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [31:0]   ss_wdata,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic      [31:0]   ss_rdata
);

    logic [DW-1:0] mem [0:(1 << AW) - 1];
    initial begin
        for (int i = 0; i < (1 << AW); i++) mem[i] = '0;
        q = '0;
        q_b = '0;
    end

    wire logic [7:0]  ss_id  = ss_addr[15:8] - SS_ID;
    wire logic [15:0] ss_idx = {ss_id, ss_addr[7:0]};
    wire logic        ss_hit = ss_addr[15:8] >= SS_ID && ss_idx < 16'(WORDS);

    wire logic [AW-1:0] ra = ss_en ? AW'(ss_idx) : addr;
    wire logic          wa = ss_en ? ss_we && ss_hit : we;
    wire logic [DW-1:0] wd = ss_en ? ss_wdata[DW-1:0] : d;

    logic hit_q = 1'b0;
    always_ff @(posedge clk) begin
        if (wa)
            mem[ra] <= wd;
        q <= mem[ra];
        hit_q <= ss_en && ss_hit;
    end

    always_ff @(posedge clk)
        q_b <= mem[addr_b];

    assign ss_rdata = hit_q ? 32'(q) : 32'd0;

endmodule

`default_nettype wire
