// Intellivision core: drawing the on-screen keypads over the playfield (build step 13;
// tools/osk.py draw() is the model, pixel for pixel).
//
// Mostly transparent: each open keypad is a 3 x 4 grid of 12 x 20 cells (37 x 82 with its
// white outlines; player 1 at x 2, player 2 at x 121, both from line 108), each cell's glyph
// (our own 5 x 7 font, osk_font.hex, each row on two lines) white with a dark shadow one pixel
// right and one row down; the cursor cell's outline and glyph yellow, filled yellow with a dark
// glyph while its key is held. Above the grid (line 90; player 2's at line 70 while player 1's
// keypad is open too) the cursor key's label from the game's profile, white with a shadow:
// player 1's from the grid's left edge, player 2's ending at its right edge.
//
// The on-screen ECS keyboard (1.0.4; never open with a keypad): 5 rows of 20 lines, ten 15-pixel
// columns (151 x 102 with the outlines, x 4-154 and lines 88-189: inside the Hide window's 159
// columns). Rows 0-3 one key a column; row 4 ESC, SPACE, RTN over 2, 3 and 2 columns and the
// three arrows, outlined at each key's left edge only. Each key's text (osk_kbd.hex, our font)
// centred in it, as the keypad's glyphs: white with a shadow, the cursor key's outline and text
// yellow, filled yellow with a dark text while pressed. Above it (line 70) "Y:SHIFT" at its left
// edge and "X:CTL" ending at its right edge, each yellow while its button is held.
//
// The pixel (pf_x, pf_y) is stable for the 12 clk_sys between two ce_pix; the overlay colour
// ovl for it is worked out in four of them (ph 0: where the pixel is; 1: its character, the
// label pool read; 2: the glyph row; 3: the row above it, for the shadow) and holds until the
// next pixel's ph 3, so pocket_video takes it with that pixel at the ce_pix that ends it.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_osk_draw #(
    parameter KBD_HEX   = "core/tables/osk_kbd.hex",
    parameter FONT_HEX  = "core/tables/osk_font.hex",
    parameter LABEL_HEX = "core/tables/osk_label.hex",
    parameter LLEN_HEX  = "core/tables/osk_llen.hex"
) (
    input  wire logic        clk,
    input  wire logic        ce_pix,
    input  wire logic [7:0]  pf_x,
    input  wire logic [7:0]  pf_y,
    input  wire logic [1:0]  osk_open,      // intv_input: player 1 [0], player 2 [1]
    input  wire logic [7:0]  osk_cur,
    input  wire logic [7:0]  osk_held,
    input  wire logic        kb_open,       // intv_input: the ECS keyboard
    input  wire logic [5:0]  kb_cur,
    input  wire logic [5:0]  kb_held,
    input  wire logic [1:0]  kb_mods,
    input  wire logic        prof_ok,       // intv_profile
    input  wire logic [107:0] labels,
    output logic      [1:0]  ovl            // 0 none, 1 white, 2 dark, 3 yellow
);

    localparam logic [1:0] NONE = 2'd0, WHITE = 2'd1, DARK = 2'd2, YELLOW = 2'd3;
    localparam int GX0 = 2, GX1 = 121, GY = 108, GW = 37, GH = 82, LY = 90;

    logic [7:0] font_rom [512];
    logic [5:0] label_rom [8192];           // 512 labels of 16 (64 until 1.0.6)
    logic [3:0] llen_rom [512];
    /* verilator lint_off UNUSEDSIGNAL */
    logic [35:0] kbd_rom [64];              // a key's text: 5 characters at 29:0 (35:30 intv_input's)
    /* verilator lint_on UNUSEDSIGNAL */
    initial begin
        $readmemh(KBD_HEX, kbd_rom);
        $readmemh(FONT_HEX, font_rom);
        $readmemh(LABEL_HEX, label_rom);
        $readmemh(LLEN_HEX, llen_rom);
    end

    logic [3:0] ph;
    initial ph = 4'd15;
    always_ff @(posedge clk)
        ph <= ce_pix ? 4'd0 : (ph == 4'd15 ? ph : ph + 4'd1);

    // ------------------------------------------------------------------ ph 0: where
    // the cursor key's label of each player: pool index and length
    wire logic [3:0] cur0 = osk_cur[3:0], cur1 = osk_cur[7:4];
    wire logic [8:0] li0 = prof_ok && cur0 < 4'd12 ? labels[9 * cur0 +: 9] : 9'd0;
    wire logic [8:0] li1 = prof_ok && cur1 < 4'd12 ? labels[9 * cur1 +: 9] : 9'd0;
    wire logic [3:0] ln0 = llen_rom[li0], ln1 = llen_rom[li1];

    logic       w_grid, w_lab, w_pl;
    logic [6:0] w_dx;           // grid: x from the grid's left edge (0-36); label: from its start (0-111)
    logic [6:0] w_dy;           // grid: y from its top (0-81); label: from its first line (0-15)
    logic [8:0] w_li;
    always_comb begin
        logic [7:0] lx1;
        logic [7:0] ly1;
        w_grid = 1'b0; w_lab = 1'b0; w_pl = 1'b0; w_dx = 7'd0; w_dy = 7'd0; w_li = 9'd0;
        lx1 = 8'(GX1 + GW) - {1'b0, ln1, 3'd0};
        ly1 = osk_open[0] ? 8'(LY - 20) : 8'(LY);
        if (pf_y >= 8'(GY) && pf_y < 8'(GY + GH)) begin
            if (osk_open[0] && pf_x >= 8'(GX0) && pf_x < 8'(GX0 + GW)) begin
                w_grid = 1'b1; w_dx = 7'(pf_x - 8'(GX0)); w_dy = 7'(pf_y - 8'(GY));
            end else if (osk_open[1] && pf_x >= 8'(GX1) && pf_x < 8'(GX1 + GW)) begin
                w_grid = 1'b1; w_pl = 1'b1; w_dx = 7'(pf_x - 8'(GX1)); w_dy = 7'(pf_y - 8'(GY));
            end
        end
        if (osk_open[0] && li0 != 9'd0 && pf_y >= 8'(LY) && pf_y < 8'(LY + 16)
            && pf_x >= 8'(GX0) && pf_x < 8'(GX0) + {1'b0, ln0, 3'd0}) begin
            w_lab = 1'b1; w_dx = 7'(pf_x - 8'(GX0)); w_dy = 7'(pf_y - 8'(LY)); w_li = li0;
        end else if (osk_open[1] && li1 != 9'd0 && pf_y >= ly1 && pf_y < ly1 + 8'd16
                     && pf_x >= lx1 && pf_x < 8'(GX1 + GW)) begin
            w_lab = 1'b1; w_pl = 1'b1; w_dx = 7'(pf_x - lx1); w_dy = 7'(pf_y - ly1); w_li = li1;
        end
    end

    // the grid's cell, the pixel's offsets in it
    logic [1:0] g_c;
    logic [2:0] g_r;
    logic [3:0] g_ox;
    logic [4:0] g_oy;
    always_comb begin
        g_c = w_dx < 7'd12 ? 2'd0 : w_dx < 7'd24 ? 2'd1 : w_dx < 7'd36 ? 2'd2 : 2'd3;
        g_r = w_dy < 7'd20 ? 3'd0 : w_dy < 7'd40 ? 3'd1 : w_dy < 7'd60 ? 3'd2 : w_dy < 7'd80 ? 3'd3 : 3'd4;
        g_ox = 4'(w_dx - 7'(12 * g_c));
        g_oy = 5'(w_dy - 7'(20 * g_r));
    end

    // ------------------------------------------------------------------ ph 0: the ECS keyboard
    localparam int KX = 4, KY = 88, KW = 151, KH = 102, KLY = 70, KMR = KX + KW - 40;
    // row 4: a key's first column and width in columns (tools/osk.py KB_ROW4)
    function automatic logic [3:0] k4x(input logic [2:0] k);
        unique case (k)
            3'd0: k4x = 4'd0;  3'd1: k4x = 4'd2;  3'd2: k4x = 4'd5;
            3'd3: k4x = 4'd7;  3'd4: k4x = 4'd8;  default: k4x = 4'd9;
        endcase
    endfunction
    function automatic logic [1:0] k4w(input logic [2:0] k);
        k4w = k == 3'd1 ? 2'd3 : k == 3'd0 || k == 3'd2 ? 2'd2 : 2'd1;
    endfunction
    function automatic logic [2:0] k4of(input logic [3:0] u);     // the row-4 key over column u
        k4of = u < 4'd2 ? 3'd0 : u < 4'd5 ? 3'd1 : u < 4'd7 ? 3'd2 : u == 4'd7 ? 3'd3 : u == 4'd8 ? 3'd4 : 3'd5;
    endfunction
    // a cell's row, left edge and width (pixels from the keyboard's left edge)
    function automatic logic [2:0] krow(input logic [5:0] kc);
        krow = kc < 6'd10 ? 3'd0 : kc < 6'd20 ? 3'd1 : kc < 6'd30 ? 3'd2 : kc < 6'd40 ? 3'd3 : 3'd4;
    endfunction
    function automatic logic [7:0] kx0(input logic [5:0] kc);
        logic [2:0] r;
        r = krow(kc);
        kx0 = r < 3'd4 ? 8'(kc - 6'(r) * 6'd10) * 8'd15 : 8'(k4x(3'(kc - 6'd40))) * 8'd15;
    endfunction
    function automatic logic [5:0] kwid(input logic [5:0] kc);
        kwid = kc < 6'd40 ? 6'd15 : 6'(k4w(3'(kc - 6'd40))) * 6'd15;
    endfunction
    function automatic logic [2:0] klen(input logic [5:0] kc);  // its text's length
        klen = kc == 6'd41 ? 3'd5 : kc == 6'd40 || kc == 6'd42 ? 3'd3 : 3'd1;
    endfunction
    // "Y:SHIFT" and "X:CTL" (osk.py CHARS codes)
    function automatic logic [5:0] mod_char(input logic right, input logic [2:0] i);
        unique case ({right, i})
            4'h0: mod_char = 6'd35;  4'h1: mod_char = 6'd39;  4'h2: mod_char = 6'd29;      // Y : S
            4'h3: mod_char = 6'd18;  4'h4: mod_char = 6'd19;  4'h5: mod_char = 6'd16;      // H I F
            4'h6: mod_char = 6'd30;                                                         // T
            4'h8: mod_char = 6'd34;  4'h9: mod_char = 6'd39;  4'hA: mod_char = 6'd13;      // X : C
            4'hB: mod_char = 6'd30;  4'hC: mod_char = 6'd22;                                // T L
            default: mod_char = 6'd0;
        endcase
    endfunction

    logic       k_grid, k_mod, k_ing, k_bord, k_curb, k_cur, k_press, k_fill, k_yel;
    logic [5:0] k_ch;
    logic [2:0] k_gc;
    logic [3:0] k_gy;
    always_comb begin
        logic [7:0] dx, ks, cks, tx;
        /* verilator lint_off UNUSEDSIGNAL */
        logic [7:0] mx;                 // (5:0: the line's 8 characters)
        /* verilator lint_on UNUSEDSIGNAL */
        logic [6:0] dy, cy;
        logic [2:0] r, cr;
        logic [3:0] u;
        logic [4:0] oy;
        logic [5:0] kc, w, cw, off;
        logic [2:0] n, ti;
        logic       valid, right;
        dx = pf_x - 8'(KX);
        dy = 7'(pf_y - 8'(KY));
        k_grid = kb_open && pf_y >= 8'(KY) && pf_y < 8'(KY + KH) && pf_x >= 8'(KX) && pf_x < 8'(KX + KW);
        r = dy < 7'd20 ? 3'd0 : dy < 7'd40 ? 3'd1 : dy < 7'd60 ? 3'd2 : dy < 7'd80 ? 3'd3 : dy < 7'd100 ? 3'd4 : 3'd5;
        oy = 5'(dy - 7'(r) * 7'd20);
        u = dx < 8'd15 ? 4'd0 : dx < 8'd30 ? 4'd1 : dx < 8'd45 ? 4'd2 : dx < 8'd60 ? 4'd3 : dx < 8'd75 ? 4'd4
          : dx < 8'd90 ? 4'd5 : dx < 8'd105 ? 4'd6 : dx < 8'd120 ? 4'd7 : dx < 8'd135 ? 4'd8 : dx < 8'd150 ? 4'd9 : 4'd10;
        valid = r < 3'd5 && u < 4'd10;
        kc = r < 3'd4 ? 6'(r) * 6'd10 + {2'd0, u} : 6'd40 + {3'd0, k4of(u)};
        ks = kx0(kc);
        w = kwid(kc);
        n = klen(kc);
        off = (w + 6'd1 - {n, 3'd0}) >> 1;                  // the text centred in its key
        tx = dx - ks - {2'd0, off};
        ti = 3'(tx[7:3]);
        k_ing = valid && dx >= ks + {2'd0, off} && tx < {2'd0, n, 3'd0} && oy >= 5'd2 && oy < 5'd18;
        k_gc = tx[2:0];
        k_gy = 4'(oy - 5'd2);
        unique case (ti)
            3'd0:    k_ch = kbd_rom[kc][5:0];
            3'd1:    k_ch = kbd_rom[kc][11:6];
            3'd2:    k_ch = kbd_rom[kc][17:12];
            3'd3:    k_ch = kbd_rom[kc][23:18];
            3'd4:    k_ch = kbd_rom[kc][29:24];
            default: k_ch = 6'd0;
        endcase
        k_bord = (valid && dx == ks) || dx == 8'd150 || oy < 5'd2 || r == 3'd5;
        cr = krow(kb_cur);
        cks = kx0(kb_cur);
        cw = kwid(kb_cur);
        cy = 7'(cr) * 7'd20;
        k_curb = dx >= cks && dx <= cks + 8'(cw) && dy >= cy && dy <= cy + 7'd21
              && (dx == cks || dx == cks + 8'(cw) || dy < cy + 7'd2 || dy >= cy + 7'd20);
        k_cur = valid && kc == kb_cur;
        k_press = valid && kb_held != 6'd0 && kc == kb_held - 6'd1;
        k_fill = k_press && dx >= ks + 8'd1 && oy >= 5'd2;
        // the SHIFT / CTL line
        right = pf_x >= 8'(KMR);
        mx = pf_x - (right ? 8'(KMR) : 8'(KX));
        k_mod = kb_open && pf_y >= 8'(KLY) && pf_y < 8'(KLY + 16)
             && ((pf_x >= 8'(KX) && pf_x < 8'(KX + 56)) || (right && pf_x < 8'(KX + KW)));
        k_yel = right ? kb_mods[1] : kb_mods[0];
        if (k_mod && !k_grid) begin
            k_ing = 1'b1;
            k_gc = mx[2:0];
            k_gy = 4'(pf_y - 8'(KLY));
            k_ch = mod_char(right, mx[5:3]);
        end
    end

    // registered at the end of ph 0
    logic       q_kb, q_km, q_kfill, q_kyel;
    logic [5:0] q_kch;
    initial begin q_kb = 1'b0; q_km = 1'b0; q_kfill = 1'b0; q_kyel = 1'b0; q_kch = 6'd0; end
    logic       q_grid, q_lab;
    logic [3:0] q_cell, q_ox;
    logic [4:0] q_oy;
    logic       q_bord, q_curb, q_iscur, q_press;
    logic [2:0] q_gc;           // the pixel's column in its glyph (0-7)
    logic [3:0] q_gy;           // its line in the glyph (0-15)
    logic       q_ing;          // inside the glyph's 8 x 16 box
    initial begin
        q_grid = 1'b0; q_lab = 1'b0; q_cell = 4'd0; q_ox = 4'd0; q_oy = 5'd0; q_bord = 1'b0;
        q_curb = 1'b0; q_iscur = 1'b0; q_press = 1'b0; q_gc = 3'd0; q_gy = 4'd0; q_ing = 1'b0;
    end
    always_ff @(posedge clk) begin
        if (ph == 4'd0) begin
            logic [3:0] cur, held, cc;
            logic [1:0] rc;
            logic [6:0] bx, by;
            cur  = w_pl ? cur1 : cur0;
            held = w_pl ? osk_held[7:4] : osk_held[3:0];
            rc = cur >= 4'd9 ? 2'd3 : cur >= 4'd6 ? 2'd2 : cur >= 4'd3 ? 2'd1 : 2'd0;
            cc = cur - 4'(3 * rc);
            bx = w_dx - 7'(12 * cc);                        // from the cursor cell's corner
            by = w_dy - 7'(20 * rc);
            q_kb   <= k_grid;
            q_km   <= k_mod && !k_grid;
            q_kch  <= k_ch;
            q_kfill <= k_fill;
            q_kyel <= k_yel;
            q_grid <= w_grid && !k_grid;
            q_lab  <= w_lab && !w_grid && !k_grid;
            q_cell <= 4'(3 * g_r) + {2'd0, g_c};
            q_ox   <= g_ox;
            q_oy   <= g_oy;
            q_bord <= k_grid ? k_bord : g_ox == 4'd0 || g_oy < 5'd2;
            q_curb <= k_grid ? k_curb
                    : w_dx >= 7'(12 * cc) && w_dx <= 7'(12 * cc) + 7'd12
                   && w_dy >= 7'(20 * rc) && w_dy <= 7'(20 * rc) + 7'd21
                   && (bx == 7'd0 || bx == 7'd12 || by < 7'd2 || by >= 7'd20);
            q_iscur <= k_grid ? k_cur : g_r < 3'd4 && g_c < 2'd3 && 4'(3 * g_r) + {2'd0, g_c} == cur;
            q_press <= k_grid ? k_press
                     : g_r < 3'd4 && g_c < 2'd3 && held != 4'd0 && 4'(3 * g_r) + {2'd0, g_c} + 4'd1 == held;
            if (k_grid || k_mod) begin
                q_ing <= k_ing;
                q_gc  <= k_gc;
                q_gy  <= k_gy;
            end else if (w_grid) begin
                q_ing <= g_r < 3'd4 && g_c < 2'd3 && g_ox >= 4'd2 && g_ox < 4'd10 && g_oy >= 5'd2 && g_oy < 5'd18;
                q_gc  <= 3'(g_ox - 4'd2);
                q_gy  <= 4'(g_oy - 5'd2);
            end else begin
                q_ing <= 1'b1;
                q_gc  <= w_dx[2:0];
                q_gy  <= w_dy[3:0];
            end
        end
    end

    // ------------------------------------------------------------------ ph 1: the character
    // the label's character: the pool read with ph 0's address, so it is there in ph 1
    wire  logic [12:0] w_la = {w_li, 4'd0} + 13'd1 + 13'(w_dx[6:3]);
    logic [5:0] lab_q;
    always_ff @(posedge clk)
        lab_q <= label_rom[w_la];

    // the grid's glyphs: 1-9, C, 0, E (osk.py CHARS: ' ' 0, '0'-'9' 1-10, 'A' 11)
    function automatic logic [5:0] cell_char(input logic [3:0] c);
        unique case (c)
            4'd9:    cell_char = 6'd13;         // C
            4'd10:   cell_char = 6'd1;          // 0
            4'd11:   cell_char = 6'd15;         // E
            default: cell_char = 6'(c) + 6'd2;  // 1-9
        endcase
    endfunction

    logic [5:0] ch;
    assign ch = q_kb || q_km ? q_kch : q_grid ? cell_char(q_cell) : lab_q;

    // the font, one read a clk: ph 1 the glyph row, ph 2 the row above
    logic [7:0] font_q, f_row;
    initial begin lab_q = 6'd0; font_q = 8'd0; f_row = 8'd0; end
    wire  logic [2:0] grow = q_gy[3:1];
    always_ff @(posedge clk) begin
        font_q <= font_rom[{ch, ph == 4'd1 ? grow : grow - 3'd1}];
        if (ph == 4'd2)
            f_row <= font_q;
    end

    // ------------------------------------------------------------------ ph 3: the colour
    initial ovl = NONE;
    always_ff @(posedge clk) begin
        if (ph == 4'd3) begin
            logic on, sh;
            logic [1:0] gcol;
            on = q_ing && f_row[3'd7 - q_gc];
            sh = q_ing && q_gc != 3'd0 && q_gy >= 4'd2 && font_q[3'd7 - (q_gc - 3'd1)];
            gcol = q_press ? DARK : q_iscur ? YELLOW : WHITE;
            if (q_kb)
                ovl <= on ? gcol
                     : (sh && !q_press) ? DARK
                     : q_kfill ? YELLOW
                     : q_curb ? YELLOW
                     : q_bord ? WHITE : NONE;
            else if (q_km)
                ovl <= on ? (q_kyel ? YELLOW : WHITE) : sh ? DARK : NONE;
            else if (q_grid)
                ovl <= on ? gcol
                     : (sh && !q_press) ? DARK
                     : (q_press && q_ox >= 4'd1 && q_oy >= 5'd2) ? YELLOW
                     : q_curb ? YELLOW
                     : q_bord ? WHITE : NONE;
            else if (q_lab)
                ovl <= on ? WHITE : sh ? DARK : NONE;
            else
                ovl <= NONE;
        end
    end

endmodule

`default_nettype wire
