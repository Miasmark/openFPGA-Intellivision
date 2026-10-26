// Intellivision core: the input module (DESIGN.md 3 module 10, 7; build
// step 6). The Pocket's controllers and USB keyboard as two hand
// controllers, the bytes the AY-3-8914's ports read: pad_r on port A
// ($01FE, the right controller), pad_l on port B ($01FF, the left one)
// (DESIGN.md 7.1; MAME intv.cpp:471-472).
//
// tools/intv_input.py is the model, with the mapping in full; in short:
// - player 1 = cont1, player 2 = cont2 (types 1-3 only; sticks on type 3);
//   player 1 is the left controller, player 2 the right; swap exchanges
//   them;
// - keypad mode 0 Layer: D-pad = disc, A/B/X = side actions lower right /
//   lower left / top; R: D-pad = ring keys by position, A/B/X/Y =
//   1/2/3/Enter; L (R not held): A/B/X = 5/Clear/0;
// - mode 1 Face-button ring: D-pad = disc, X/B/Y/A = ring 2/8/4/6 (pairs
//   for 1/3/7/9), L = top side action, R = 5;
// - mode 2 Right stick: Layer, plus the right stick = ring key (8 sectors),
//   R3 = 5; mode 3 works as Layer;
// - analog left stick: the disc in 16 directions; opposite directions
//   cancel;
// - USB keyboard (cont3 type 4): player 1's keypad (1-9, 0 on the number
//   row and the numpad, Backspace = Clear, Enter / numpad Enter = Enter).
// Every input pulls its lines low and the lines are wired-OR'd, as on the
// hardware (DESIGN.md 7.1): codes from the service manual and the wiki,
// equal to MAME handctrl.cpp:124-135 inverted.
//
// The Pocket's controller words and the two settings come from clk_74a
// (the APF pad controller's registers and the bridge's settings) and cross
// into clk (clk_sys) as one word with a toggle handshake (section
// "Crossing" below): a clk_74a register holds a copy of all of them, a
// request flag toggles, and clk loads the copy as a whole once the flag
// has passed its two synchroniser flip-flops; the load toggles an
// acknowledge flag back, and only when that has passed two clk_74a
// flip-flops is the copy taken again. So clk only ever sees words that
// were all present at one clk_74a edge, never a mixture of an old and a
// new word (a bit-by-bit crossing could, for one clk cycle, show a press
// nobody made: HID 1E '1' to 21 '4' read as 1F '2'). The latency from a
// change to the bytes is at most about 7 clk + 4 clk_74a periods (220 ns);
// the words change at most once a frame. core_constraints.sdc bounds the
// copy's and the request's paths into clk with set_net_delay (10 ns; its
// comment says why not set_max_skew or set_max_delay), which the
// asynchronous clock groups otherwise leave untimed;
// sim/check/fit_crossing_check.py checks those net delays and the two
// flip-flops of each flag after a fit. The module holds no
// machine state (inputs are sampled again after a restore, DESIGN.md 4.4),
// so it has no state port.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_input (
    input  wire logic        clk_74a,       // the words' and settings' clock
    input  wire logic        clk,           // clk_sys
    input  wire logic [31:0] cont1_key,
    input  wire logic [31:0] cont1_joy,
    input  wire logic [31:0] cont2_key,
    input  wire logic [31:0] cont2_joy,
    input  wire logic [31:0] cont3_key,
    input  wire logic [31:0] cont3_joy,
    input  wire logic [15:0] cont3_trig,
    input  wire logic [1:0]  kp_mode,       // 0 Layer, 1 Face-button ring, 2 Right stick
    input  wire logic        swap,          // 1: player 1 on the right controller
    output logic      [7:0]  pad_r,         // $01FE, PSG port A
    output logic      [7:0]  pad_l          // $01FF, PSG port B
);

    // -------------------------------------------------------------------
    // Codes: the lines each input pulls low (DESIGN.md 7.1)
    // -------------------------------------------------------------------
    localparam logic [7:0] K_CLEAR = 8'h88, K_ENTER = 8'h28;
    localparam logic [7:0] S_TOP = 8'hA0, S_LL = 8'h60, S_LR = 8'hC0;

    // key n (0-9)
    function automatic logic [7:0] key_code(input logic [3:0] n);
        unique case (n)
            4'd1: key_code = 8'h81;  4'd2: key_code = 8'h41;  4'd3: key_code = 8'h21;
            4'd4: key_code = 8'h82;  4'd5: key_code = 8'h42;  4'd6: key_code = 8'h22;
            4'd7: key_code = 8'h84;  4'd8: key_code = 8'h44;  4'd9: key_code = 8'h24;
            4'd0: key_code = 8'h48;
            default: key_code = 8'h00;
        endcase
    endfunction

    // disc direction d (0 = N, clockwise)
    function automatic logic [7:0] disc_code(input logic [3:0] d);
        unique case (d)
            4'd0:  disc_code = 8'h04;  4'd1:  disc_code = 8'h14;
            4'd2:  disc_code = 8'h16;  4'd3:  disc_code = 8'h06;
            4'd4:  disc_code = 8'h02;  4'd5:  disc_code = 8'h12;
            4'd6:  disc_code = 8'h13;  4'd7:  disc_code = 8'h03;
            4'd8:  disc_code = 8'h01;  4'd9:  disc_code = 8'h11;
            4'd10: disc_code = 8'h19;  4'd11: disc_code = 8'h09;
            4'd12: disc_code = 8'h08;  4'd13: disc_code = 8'h18;
            4'd14: disc_code = 8'h1C;  4'd15: disc_code = 8'h0C;
        endcase
    endfunction

    // The ring key at a position: up, down, left, right (opposites cancel)
    function automatic logic [7:0] ring_code(input logic u, input logic d, input logic l, input logic r);
        logic uu, dd, ll, rr;
        uu = u & ~d;  dd = d & ~u;  ll = l & ~r;  rr = r & ~l;
        unique case ({uu, dd, ll, rr})
            4'b1010: ring_code = key_code(4'd1);
            4'b1000: ring_code = key_code(4'd2);
            4'b1001: ring_code = key_code(4'd3);
            4'b0010: ring_code = key_code(4'd4);
            4'b0001: ring_code = key_code(4'd6);
            4'b0110: ring_code = key_code(4'd7);
            4'b0100: ring_code = key_code(4'd8);
            4'b0101: ring_code = key_code(4'd9);
            default: ring_code = 8'h00;
        endcase
    endfunction

    // The disc from a D-pad: 8 directions (opposites cancel)
    function automatic logic [7:0] dpad_code(input logic u, input logic d, input logic l, input logic r);
        logic uu, dd, ll, rr;
        uu = u & ~d;  dd = d & ~u;  ll = l & ~r;  rr = r & ~l;
        unique case ({uu, dd, ll, rr})
            4'b1000: dpad_code = disc_code(4'd0);
            4'b1001: dpad_code = disc_code(4'd2);
            4'b0001: dpad_code = disc_code(4'd4);
            4'b0101: dpad_code = disc_code(4'd6);
            4'b0100: dpad_code = disc_code(4'd8);
            4'b0110: dpad_code = disc_code(4'd10);
            4'b0010: dpad_code = disc_code(4'd12);
            4'b1010: dpad_code = disc_code(4'd14);
            default: dpad_code = 8'h00;
        endcase
    endfunction

    // -------------------------------------------------------------------
    // Sticks: unsigned bytes, centre 0x80, y down. a = |dx|, b = |dy|; the
    // angle from the vertical passes the sector boundaries where a * 256
    // >= b * round(256 tan(angle)) (tools/intv_input.py).
    // -------------------------------------------------------------------
    localparam int DZ_DISC = 40, DZ_RING = 64;

    // 16-direction disc code of a stick (0 in the dead zone)
    function automatic logic [7:0] stick16_code(input logic [7:0] x, input logic [7:0] y);
        logic signed [8:0] dx, dy;
        logic [7:0] a, b;
        logic [17:0] a256, b51, b171, b383, b1287;
        logic [2:0] k;
        logic [3:0] d;
        dx = $signed({1'b0, x}) - 9'sd128;
        dy = $signed({1'b0, y}) - 9'sd128;
        a = dx[8] ? 8'(-dx) : dx[7:0];
        b = dy[8] ? 8'(-dy) : dy[7:0];
        a256  = {2'b0, a, 8'd0};
        b51   = 18'(b) * 18'd51;
        b171  = 18'(b) * 18'd171;
        b383  = 18'(b) * 18'd383;
        b1287 = 18'(b) * 18'd1287;
        k = 3'(a256 >= b51) + 3'(a256 >= b171) + 3'(a256 >= b383) + 3'(a256 >= b1287);
        if (!dx[8])
            d = dy[8] ? 4'(k) : 4'(4'd8 - 4'(k));
        else
            d = !dy[8] ? 4'(4'd8 + 4'(k)) : 4'(5'd16 - 5'(k));
        if (17'(a) * 17'(a) + 17'(b) * 17'(b) < 17'(DZ_DISC * DZ_DISC))
            stick16_code = 8'h00;
        else
            stick16_code = disc_code(d);
    endfunction

    // Ring key of a stick in 8 sectors (0 in the dead zone)
    function automatic logic [7:0] stick8_code(input logic [7:0] x, input logic [7:0] y);
        logic signed [8:0] dx, dy;
        logic [7:0] a, b;
        logic [17:0] a256;
        logic [1:0] k;
        dx = $signed({1'b0, x}) - 9'sd128;
        dy = $signed({1'b0, y}) - 9'sd128;
        a = dx[8] ? 8'(-dx) : dx[7:0];
        b = dy[8] ? 8'(-dy) : dy[7:0];
        a256 = {2'b0, a, 8'd0};
        k = 2'(a256 >= 18'(b) * 18'd106) + 2'(a256 >= 18'(b) * 18'd618);
        if (17'(a) * 17'(a) + 17'(b) * 17'(b) < 17'(DZ_RING * DZ_RING))
            stick8_code = 8'h00;
        else
            // vertical unless k = 2, horizontal unless k = 0
            stick8_code = ring_code(k != 2'd2 && dy[8], k != 2'd2 && !dy[8],
                                    k != 2'd0 && dx[8], k != 2'd0 && !dx[8]);
    endfunction

    // -------------------------------------------------------------------
    // One Pocket controller slot -> the lines it pulls low
    // -------------------------------------------------------------------
    // (key bits 10-12, 14-15 and 27:16 are not used: L2, R2, L3, Select, Start)
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic logic [7:0] player(input logic [31:0] key, input logic [31:0] joy,
                                          input logic [1:0] mode);
        logic [3:0] t;
        logic up, dn, lt, rt, ba, bb, bx, by, l1, r1, r3, an;
        logic [7:0] p;
        t  = key[31:28];
        up = key[0];  dn = key[1];  lt = key[2];  rt = key[3];
        ba = key[4];  bb = key[5];  bx = key[6];  by = key[7];
        l1 = key[8];  r1 = key[9];  r3 = key[13];
        an = t == 4'd3;
        p = 8'h00;
        if (mode == 2'd1) begin                                 // Face-button ring
            p = dpad_code(up, dn, lt, rt) | ring_code(bx, bb, by, ba)
              | (l1 ? S_TOP : 8'h00) | (r1 ? key_code(4'd5) : 8'h00);
        end else begin                                          // Layer, Right stick
            if (r1)
                p = ring_code(up, dn, lt, rt)
                  | (ba ? key_code(4'd1) : 8'h00) | (bb ? key_code(4'd2) : 8'h00)
                  | (bx ? key_code(4'd3) : 8'h00) | (by ? K_ENTER : 8'h00);
            else if (l1)
                p = dpad_code(up, dn, lt, rt)
                  | (ba ? key_code(4'd5) : 8'h00) | (bb ? K_CLEAR : 8'h00)
                  | (bx ? key_code(4'd0) : 8'h00);
            else
                p = dpad_code(up, dn, lt, rt)
                  | (ba ? S_LR : 8'h00) | (bb ? S_LL : 8'h00) | (bx ? S_TOP : 8'h00);
            if (mode == 2'd2 && an)
                p = p | stick8_code(joy[23:16], joy[31:24]) | (r3 ? key_code(4'd5) : 8'h00);
        end
        if (an)
            p = p | stick16_code(joy[7:0], joy[15:8]);
        player = (t == 4'd1 || t == 4'd2 || t == 4'd3) ? p : 8'h00;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */

    // One HID usage code -> lines pulled low
    function automatic logic [7:0] hid_code(input logic [7:0] c);
        if (c >= 8'h1E && c <= 8'h26)           // 1-9
            hid_code = key_code(4'(c - 8'h1D));
        else if (c >= 8'h59 && c <= 8'h61)      // numpad 1-9
            hid_code = key_code(4'(c - 8'h58));
        else if (c == 8'h27 || c == 8'h62)      // 0, numpad 0
            hid_code = key_code(4'd0);
        else if (c == 8'h28 || c == 8'h58)      // Enter, numpad Enter
            hid_code = K_ENTER;
        else if (c == 8'h2A)                    // Backspace
            hid_code = K_CLEAR;
        else
            hid_code = 8'h00;
    endfunction

    // -------------------------------------------------------------------
    // Crossing: clk_74a -> clk as one word (toggle handshake)
    // -------------------------------------------------------------------
    localparam int W = 6 * 32 + 16 + 2 + 1;
    wire logic [W-1:0] in_74 = {cont1_key, cont1_joy, cont2_key, cont2_joy, cont3_key, cont3_joy,
                                cont3_trig, kp_mode, swap};

    // clk_74a side: the held copy, the request flag, the acknowledge's
    // synchroniser. The copy is taken only when the acknowledge equals the
    // request (clk has loaded the last copy), so it is stable from the
    // request's toggle until clk has loaded it.
    logic [W-1:0] hold_74;
    logic         req_74;
    logic [1:0]   ack_74;
    // clk side: the request's synchroniser, the acknowledge flag, the word
    logic [1:0]   req_s;
    logic         ack;
    logic [W-1:0] word;

    initial begin
        hold_74 = '0; req_74 = 1'b0; ack_74 = 2'b00;
        req_s = 2'b00; ack = 1'b0; word = '0;
    end

    always_ff @(posedge clk_74a) begin
        ack_74 <= {ack_74[0], ack};
        if (ack_74[1] == req_74) begin
            hold_74 <= in_74;
            req_74  <= !req_74;
        end
    end

    always_ff @(posedge clk) begin
        req_s <= {req_s[0], req_74};
        if (req_s[1] != ack) begin
            word <= hold_74;
            ack  <= req_s[1];
        end
    end

    // -------------------------------------------------------------------
    // Output
    // -------------------------------------------------------------------
    /* verilator lint_off UNUSEDSIGNAL */
    logic [31:0] k1, j1, k2, j2, k3, j3;    // (k3: the type alone; synthesis drops unused bits)
    /* verilator lint_on UNUSEDSIGNAL */
    logic [15:0] t3;
    logic [1:0]  md;
    logic        sw;
    assign {k1, j1, k2, j2, k3, j3, t3, md, sw} = word;

    logic [7:0] p1, p2, kb;
    always_comb begin
        kb = 8'h00;
        if (k3[31:28] == 4'd4)
            kb = hid_code(j3[7:0]) | hid_code(j3[15:8]) | hid_code(j3[23:16])
               | hid_code(j3[31:24]) | hid_code(t3[7:0]) | hid_code(t3[15:8]);
        p1 = player(k1, j1, md) | kb;
        p2 = player(k2, j2, md);
    end

    initial begin
        pad_r = 8'hFF;
        pad_l = 8'hFF;
    end
    always_ff @(posedge clk) begin
        pad_l <= ~(sw ? p2 : p1);
        pad_r <= ~(sw ? p1 : p2);
    end

endmodule

`default_nettype wire
