// Intellivision core: the PSG's registers, a stub without sound (build
// step 3; the PSG proper is step 6, DESIGN.md 3 module 9).
//
// AY-3-8914 at $01F0-$01FF (DESIGN 2.6), enough for the EXEC: 14 registers
// that read back as MAME's ay8914_device does (MAME ay8910.cpp:1533 maps
// register $01F0 + n to AY-3-8910 register MAP[n]; ay8910.cpp:1445-1450
// gives the read masks per AY-3-8910 register, from hardware tests):
//   n     0    1    2    3    4    5    6    7    8    9    10   11   12   13
//   mask  FF   FF   FF   FF   0F   0F   0F   FF   FF   1F   0F   3F   3F   3F
// $01FE and $01FF read the right and left hand controllers (pad_r, pad_l;
// $FF with nothing pressed). Machine reset clears the registers (MAME
// ay8910_reset_ym). The bus fabric puts the byte on DB0-7 (upper byte 0).
//
// Save state (DESIGN.md 4.3; module id SS_ID, 14 words; ss_rdata 0 unless
// addressed): word n = register n (the kept bits).
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_psg_regs #(
    parameter logic [7:0] SS_ID = 8'h05
) (
    input  wire logic        clk,
    input  wire logic        reset,
    input  wire logic [3:0]  n,               // address [3:0]
    input  wire logic        we,              // write strobe, decoded
    input  wire logic [7:0]  wdata,
    output logic      [7:0]  q,
    input  wire logic [7:0]  pad_r,           // $01FE
    input  wire logic [7:0]  pad_l,           // $01FF

    input  wire logic [15:0] ss_addr,
    input  wire logic        ss_we,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [31:0] ss_wdata,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic [31:0]      ss_rdata
);

    logic [7:0] r [0:13];
    initial for (int i = 0; i < 14; i++) r[i] = 8'd0;

    function automatic logic [7:0] mask(input logic [3:0] k);
        unique case (k)
            4'd4, 4'd5, 4'd6, 4'd10: mask = 8'h0F;
            4'd9:                    mask = 8'h1F;
            4'd11, 4'd12, 4'd13:     mask = 8'h3F;
            default:                 mask = 8'hFF;
        endcase
    endfunction

    always_comb begin
        unique case (n)
            4'd14:   q = pad_r;
            4'd15:   q = pad_l;
            default: q = r[n];
        endcase
    end

    wire logic       ss_hit = ss_addr[15:8] == SS_ID && ss_addr[7:0] < 8'd14;
    wire logic [3:0] ss_w   = ss_addr[3:0];

    always_ff @(posedge clk) begin
        if (reset) begin
            for (int i = 0; i < 14; i++) r[i] <= 8'd0;
        end else if (ss_we && ss_hit)
            r[ss_w] <= ss_wdata[7:0] & mask(ss_w);
        else if (we && n < 4'd14)
            r[n] <= wdata & mask(n);
    end

    assign ss_rdata = ss_hit ? {24'd0, r[ss_w]} : 32'd0;

endmodule

`default_nettype wire
