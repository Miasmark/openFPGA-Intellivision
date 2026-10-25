// Intellivision core: the STIC's CPU-side registers, a stub without a
// picture (build step 3; the STIC proper is step 4, DESIGN.md 3 module 6).
//
// Enough for the EXEC to run: the registers read and write as MAME's
// stic_device::read / write do (MAME stic.cpp:1139-1309, read for facts
// only), and the handshake that closes the STIC to the CPU outside VBlank
// once the display is enabled (MAME intv_m.cpp:484-512, stic.cpp:1111-1116,
// 1270-1274; DESIGN 13.4):
//   - a write to register $20 (display enable) sets the handshake; the
//     start of each frame clears it (frame_end, the ce that ends a frame);
//   - open = vb || !handshake: STIC registers and GRAM (intv_bus) are open
//     to the CPU; when closed a read gives the address offset, a write is
//     dropped;
//   - a register keeps only the bits it reads back; the others read fixed
//     (DESIGN 13.7): MXR $3800 | 11 bits, MYR $3000 | 12, MAR 14 bits, MCR
//     $3C00 | 10 bits (a MOB's own collision bit is never stored), CSR0-3
//     and BCR $3FF0 | 4, HDR and VDR $3FF8 | 3, CBR $3FFC | 2, everything
//     else ($20-$27, $2D-$2F, $33-$3F) $3FFF;
//   - a write to $21 selects FGBG mode and a read of $21 (or $4021, $8021,
//     $C021, DESIGN 2.6) colour-stack mode, as the mode latch (csmode).
// Writes come from $0000-$003F and the aliases $4000, $8000, $C000 (intv_bus
// decodes them); reads only from $0000-$003F. The read word is 16 bits with
// bits 14-15 0, as MAME gives them.
//
// Save state (DESIGN.md 4.3; module id SS_ID, 52 words; ss_rdata 0 unless
// addressed): word n < $33 register n (the kept bits); word $33 [0] csmode,
// [1] handshake.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_stic_regs #(
    parameter logic [7:0] SS_ID = 8'h04
) (
    input  wire logic        clk,
    input  wire logic        reset,
    input  wire logic        vb,              // bus-copy window, this CPU cycle
    input  wire logic        frame_end,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [15:0] a,               // latched bus address
    /* verilator lint_on UNUSEDSIGNAL */
    input  wire logic        rd,              // read strobe (any address)
    input  wire logic        we,              // write strobe, decoded
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [15:0] wdata,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic             open,
    output logic [15:0]      q,

    input  wire logic [15:0] ss_addr,
    input  wire logic        ss_we,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [31:0] ss_wdata,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic [31:0]      ss_rdata
);

    localparam int NREG = 'h33;

    logic [13:0] r [0:NREG-1];
    logic        hs = 1'b0, csmode = 1'b0;
    initial for (int i = 0; i < NREG; i++) r[i] = 14'd0;

    function automatic logic [13:0] keep(input logic [5:0] n);
        if (n < 6'h08)       keep = 14'h07FF;
        else if (n < 6'h10)  keep = 14'h0FFF;
        else if (n < 6'h18)  keep = 14'h3FFF;
        else if (n < 6'h20)  keep = 14'h03FF & ~(14'd1 << n[2:0]);
        else if (n >= 6'h28 && n <= 6'h2C) keep = 14'h000F;
        else if (n == 6'h30 || n == 6'h31)  keep = 14'h0007;
        else if (n == 6'h32) keep = 14'h0003;
        else                 keep = 14'h0000;
    endfunction

    function automatic logic [13:0] fixed(input logic [5:0] n);
        if (n < 6'h08)       fixed = 14'h3800;
        else if (n < 6'h10)  fixed = 14'h3000;
        else if (n < 6'h18)  fixed = 14'h0000;
        else if (n < 6'h20)  fixed = 14'h3C00;
        else if (n >= 6'h28 && n <= 6'h2C) fixed = 14'h3FF0;
        else if (n == 6'h30 || n == 6'h31)  fixed = 14'h3FF8;
        else if (n == 6'h32) fixed = 14'h3FFC;
        else                 fixed = 14'h3FFF;
    endfunction

    wire logic [5:0] n = a[5:0];
    assign open = vb || !hs;

    always_comb begin
        if (!open)
            q = {10'd0, n};
        else if (n < 6'(NREG))
            q = {2'b00, fixed(n) | (r[n] & keep(n))};
        else
            q = 16'h3FFF;
    end

    wire logic       ss_hit = ss_addr[15:8] == SS_ID;
    wire logic [7:0] ss_w   = ss_addr[7:0];

    always_ff @(posedge clk) begin
        if (reset) begin
            for (int i = 0; i < NREG; i++) r[i] <= 14'd0;
            hs <= 1'b0;
            csmode <= 1'b0;
        end else if (ss_we && ss_hit) begin
            if (ss_w < 8'(NREG))
                r[ss_w[5:0]] <= ss_wdata[13:0] & keep(ss_w[5:0]);
            else if (ss_w == 8'(NREG))
                {hs, csmode} <= ss_wdata[1:0];
        end else begin
            if (we && open) begin
                if (n < 6'(NREG))
                    r[n] <= wdata[13:0] & keep(n);
                if (n == 6'h20)
                    hs <= 1'b1;
                if (n == 6'h21)
                    csmode <= 1'b0;
            end
            if (rd && open && a[13:0] == 14'h0021)
                csmode <= 1'b1;
            if (frame_end)
                hs <= 1'b0;
        end
    end

    always_comb begin
        ss_rdata = 32'd0;
        if (ss_hit) begin
            if (ss_w < 8'(NREG))
                ss_rdata = {18'd0, r[ss_w[5:0]]};
            else if (ss_w == 8'(NREG))
                ss_rdata = {30'd0, hs, csmode};
        end
    end

endmodule

`default_nettype wire
