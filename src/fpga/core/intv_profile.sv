// Intellivision core: the game profiles (build step 13; tools/osk.py PROFILES). By the
// cartridge's CRC-32, the keypad mode that Keypad Mode Auto uses, the side actions of A / B / X
// in Auto's Layer modes, and the on-screen keypad's labels (an index into the label pool for
// each of the 12 cells).
//
// The CRC table (osk_crc.hex: 128 entries of valid, CRC-32, profile index; 64 until 1.0.6) is
// scanned round and round, one entry a clk; at the end of each round of 128 the result is taken,
// so ok follows a new cartridge within 258 clk of its CRC and ready. The profile's record (osk_prof.hex) is read
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
    output logic     [107:0] labels         // cell n's label index at [9n +: 9], 0 = none
);

    logic [39:0]  crc_rom [128];
    logic [115:0] prof_rom [128];
    initial begin
        $readmemh(CRC_HEX, crc_rom);
        $readmemh(PROF_HEX, prof_rom);
    end

    logic [6:0]   i, ie;                    // the entry read, the entry in e
    logic [39:0]  e;
    logic         f_acc, found;
    logic [6:0]   x_acc, idx;
    logic [115:0] rec;
    initial begin
        i = 7'd0; ie = 7'd0; e = 40'd0; f_acc = 1'b0; found = 1'b0; x_acc = 7'd0; idx = 7'd0; rec = 116'd0;
    end

    always_ff @(posedge clk) begin
        e  <= crc_rom[i];
        ie <= i;
        i  <= i + 7'd1;
        if (ie == 7'd127) begin
            found <= f_acc || (e[39] && e[38:7] == crc);
            idx   <= (e[39] && e[38:7] == crc) ? e[6:0] : x_acc;
            f_acc <= 1'b0;
        end else if (e[39] && e[38:7] == crc) begin
            f_acc <= 1'b1;
            x_acc <= e[6:0];
        end
        rec <= prof_rom[idx];
    end

    initial begin ok = 1'b0; mode = 2'd0; sides = 6'd0; labels = 108'd0; end
    always_ff @(posedge clk) begin
        ok     <= found && ready;
        mode   <= rec[115:114];
        sides  <= rec[113:108];
        labels <= rec[107:0];
    end

endmodule

`default_nettype wire
