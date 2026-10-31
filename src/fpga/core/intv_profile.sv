// Intellivision core: the game profiles (build step 13; tools/osk.py PROFILES). By the
// cartridge's CRC-32, the keypad mode that Keypad Mode Auto uses, the side actions of A / B / X
// in Auto's Layer modes, and the on-screen keypad's labels (an index into the label pool for
// each of the 12 cells).
//
// The CRC table (osk_crc.hex: 64 entries of valid, CRC-32, profile index) is scanned round and
// round, one entry a clk; at the end of each round of 64 the result is taken, so ok follows a
// new cartridge within 130 clk of its CRC and ready. The profile's record (osk_prof.hex) is read
// from the index found. Nothing here is machine state: it follows the cartridge.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_profile #(
    parameter CRC_HEX  = "core/tables/osk_crc.hex",
    parameter PROF_HEX = "core/tables/osk_prof.hex"
) (
    input  wire logic        clk,
    input  wire logic [31:0] crc,           // the cartridge's CRC-32 (intv_media)
    input  wire logic        ready,         // the cartridge is loaded
    output logic             ok,            // a profile for it
    output logic      [1:0]  mode,          // Auto's keypad mode
    output logic      [5:0]  sides,         // A [1:0], B [3:2], X [5:4]: 0 lr, 1 ll, 2 top
    output logic      [71:0] labels         // cell n's label index at [6n +: 6], 0 = none
);

    logic [39:0] crc_rom [64];
    logic [79:0] prof_rom [64];
    initial begin
        $readmemh(CRC_HEX, crc_rom);
        $readmemh(PROF_HEX, prof_rom);
    end

    logic [5:0]  i, ie;                     // the entry read, the entry in e
    /* verilator lint_off UNUSEDSIGNAL */
    logic [39:0] e;                         // (bit 6: the index's top bit, always 0)
    /* verilator lint_on UNUSEDSIGNAL */
    logic        f_acc, found;
    logic [5:0]  x_acc, idx;
    logic [79:0] rec;
    initial begin
        i = 6'd0; ie = 6'd0; e = 40'd0; f_acc = 1'b0; found = 1'b0; x_acc = 6'd0; idx = 6'd0; rec = 80'd0;
    end

    always_ff @(posedge clk) begin
        e  <= crc_rom[i];
        ie <= i;
        i  <= i + 6'd1;
        if (ie == 6'd63) begin
            found <= f_acc || (e[39] && e[38:7] == crc);
            idx   <= (e[39] && e[38:7] == crc) ? e[5:0] : x_acc;
            f_acc <= 1'b0;
        end else if (e[39] && e[38:7] == crc) begin
            f_acc <= 1'b1;
            x_acc <= e[5:0];
        end
        rec <= prof_rom[idx];
    end

    initial begin ok = 1'b0; mode = 2'd0; sides = 6'd0; labels = 72'd0; end
    always_ff @(posedge clk) begin
        ok     <= found && ready;
        mode   <= rec[79:78];
        sides  <= rec[77:72];
        labels <= rec[71:0];
    end

endmodule

`default_nettype wire
