// Intellivision core: step-1 test pattern (DESIGN.md 9, step 1).
//
// Stands in for the STIC until step 4. Combinational: a colour for the
// pixel pocket_video asks about.
//   - Playfield lines 0-95: the 16 STIC colours as bars 10 pixels wide, in
//     colour number order (black, blue, red, tan, dark green, green, yellow,
//     white, grey, cyan, orange, brown, pink, light blue, yellow-green,
//     purple).
//   - Lines 96-175: a black and white checkerboard of cards, 8 pixels by
//     16 lines (one 8 x 8 card), to check the card grid and the scaling.
//   - Lines 176-191 (the last card row): one indicator two cards wide per
//     data slot, left to right cartridge, cartridge config, EXEC, GROM,
//     ECS ROM, Intellivoice ROM: green = loaded with the expected size,
//     yellow = loaded, other size (the cartridge: loaded with an error, or
//     refused), red = a required slot is empty, grey = an optional slot is
//     empty. The rest of the row is black. The cartridge's second card
//     shows, once it is loaded, where its length came from (len_st,
//     apf_datatable.sv len_chk): green = the data table, agreeing with the
//     host's 0x0082 size; orange = they disagree (the table's was used);
//     cyan = the table had no entry (the 0x0082 size was used); grey = the
//     table, with no 0x0082 size to check it against. The CFG's second card
//     shows how the core looked for NAME.cfg beside the cartridge
//     (apf_cfgfetch's res): green = found, its length from the data table;
//     cyan = found, its length found by reading; grey = no such file;
//     orange = the host refused a command; red = the cartridge's path has
//     no extension; purple = over 16 KiB; black = not looked for.
//   - The outermost pixel ring of the playfield is white, to check the
//     crop; the border outside it is blue.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module test_pattern (
    input  wire logic        in_pf,
    input  wire logic [7:0]  pf_x,      // 0..159
    input  wire logic [7:0]  pf_y,      // 0..191
    input  wire logic [11:0] slot_st,   // 2 bits a slot: 0 empty, 1 other size, 2 ok
    input  wire logic [5:0]  slot_req,  // slot is required
    input  wire logic [1:0]  len_st,    // cartridge length source (see above)
    input  wire logic [2:0]  cfg_res,   // the CFG fetch (see above)
    output logic      [3:0]  colour
);

    // pf_x / 10 for 0..159: (x * 205) >> 11 is exact for x < 1029
    /* verilator lint_off UNUSEDSIGNAL */
    wire logic [15:0] x205 = {8'd0, pf_x} * 16'd205;
    /* verilator lint_on UNUSEDSIGNAL */
    wire logic [3:0]  bar  = x205[14:11];
    wire logic [4:0]  cx   = pf_x[7:3];         // card column 0..19
    wire logic [3:0]  cy   = pf_y[7:4];         // card row 0..11
    wire logic [2:0]  ind  = 3'(cx[4:1]);       // indicator 0..5 (cards 0-11)

    logic [1:0] st;
    always_comb begin
        st = 2'd0;
        case (ind)
            3'd0: st = slot_st[1:0];
            3'd1: st = slot_st[3:2];
            3'd2: st = slot_st[5:4];
            3'd3: st = slot_st[7:6];
            3'd4: st = slot_st[9:8];
            3'd5: st = slot_st[11:10];
            default: st = 2'd0;
        endcase
    end

    always_comb begin
        if (!in_pf)
            colour = 4'd1;                                          // border: blue
        else if (pf_x == 8'd0 || pf_x == 8'd159 || pf_y == 8'd0 || pf_y == 8'd191)
            colour = 4'd7;                                          // edge: white
        else if (pf_y < 8'd96)
            colour = bar;                                           // colour bars
        else if (cy != 4'd11)
            colour = (cx[0] ^ cy[0]) ? 4'd7 : 4'd0;                 // card grid
        else if (cx >= 5'd12)
            colour = 4'd0;
        else if (cx == 5'd3)                                        // the CFG fetch
            colour = cfg_res == 3'd1 ? 4'd5 : cfg_res == 3'd2 ? 4'd9 : cfg_res == 3'd3 ? 4'd8
                   : cfg_res == 3'd4 ? 4'd10 : cfg_res == 3'd5 ? 4'd2 : cfg_res == 3'd6 ? 4'd15 : 4'd0;
        else if (cx == 5'd1 && st != 2'd0)                          // cartridge length
            colour = len_st == 2'd1 ? 4'd5 : len_st == 2'd2 ? 4'd10
                   : len_st == 2'd3 ? 4'd9 : 4'd8;
        else if (st == 2'd2)
            colour = 4'd5;                                          // ok: green
        else if (st == 2'd1)
            colour = 4'd6;                                          // other size: yellow
        else
            colour = slot_req[ind] ? 4'd2 : 4'd8;                   // empty: red / grey
    end

endmodule

`default_nettype wire
