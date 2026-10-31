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
//   1/2/3/Enter; L (R not held): A/B/X = 5/Clear/0 and the D-pad turned
//   one notch (22.5 deg) clockwise, the 8 in-between disc directions
//   (NNE, ENE, ... NNW), so the D-pad reaches all 16;
// - mode 1 Face-button ring: D-pad = disc, X/B/Y/A = ring 2/8/4/6 (pairs
//   for 1/3/7/9), L = top side action (no turn: L is a button there),
//   R = 5;
// - mode 2 Right stick: Layer, plus the right stick = ring key (8 sectors),
//   R3 = 5;
// - mode 3 Auto (build step 13): the game profile's mode (intv_profile;
//   Layer without one), and in its Layer modes the profile's side actions
//   on A / B / X (prof_sides) instead of lower right / lower left / top;
// - the on-screen keypads (build step 13, tools/osk.py): Select opens a
//   player's keypad, Select or B closes it; while open the D-pad moves the
//   cursor over the 3 x 4 grid (wrapping) and a press of A presses the
//   cursor's key until A is let go; all 16 buttons of that controller are
//   the keypad's while it is open (the sticks are not), and buttons held
//   when it closes stay masked until let go. It steps once a frame (frame,
//   the video frame's start) on the word of that moment; its state goes to
//   intv_osk_draw (osk_open, osk_cur, osk_held). It is not machine state.
// - analog left stick: the disc in 16 directions, never turned by L;
//   opposite directions cancel;
// - USB keyboard (cont3 type 4): player 1's keypad (1-9, 0 on the number
//   row and the numpad, Backspace = Clear, Enter / numpad Enter = Enter).
// - with the ECS fully on (ecs_full: mode on, build step 9): the USB
//   keyboard is the ECS keyboard key by key (ecs_keys: bit 8 row + column
//   of the ECS matrix; Shift and Ctrl from the HID modifier byte
//   cont3_key[7:0]); only the numpad stays the keypad (numpad . = Clear).
//   Setting synth: the music synthesizer on two tracker rows (Z-M = C3-B3,
//   Q-I = C4-C5) instead. With the ECS attached (ROMs out, Auto's default)
//   or off the keyboard is the keypad as in 0.0.8 and the matrix reads no
//   key: no ECS ROM code scans it then, and the games keep the number row,
//   Enter and Backspace (step 9 review). The ECS settings (ecs_ovr_74:
//   Auto / On / Off, synth_74) cross with the controller words (ecs_ovr,
//   ecs_synth).
// - the six HID codes are decoded one per clk in a round of 8 clk (0-5:
//   one code each into kb_acc / ek_acc, 6: the outputs registered, 7: the
//   next word may load), one decoder instead of six (the step-9 review:
//   twelve 64-bit decoders cost about 640 ALMs). The word is loaded only at
//   step 7, so every output comes from one whole word (the crossing's
//   promise below holds). Latency: at most 2 rounds (16 clk) more.
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
    input  wire logic [1:0]  kp_mode,       // 0 Layer, 1 Face-button ring, 2 Right stick, 3 Auto (the game's profile)
    input  wire logic        swap,          // 1: player 1 on the right controller
    input  wire logic [1:0]  ecs_ovr_74,    // setting ECS: 0 Auto, 1 On, 2 Off
    input  wire logic        synth_74,      // setting ECS Keyboard: 1 Synthesizer
    input  wire logic        ecs_full,      // clk: the ECS is fully on (mode on, not attached)
    input  wire logic        frame,         // clk: the video frame's start (one clk): the keypads step
    input  wire logic        prof_ok,       // clk: the cartridge has a profile (intv_profile)
    input  wire logic [1:0]  prof_mode,     //   its keypad mode for Auto
    input  wire logic [5:0]  prof_sides,    //   its side actions of A [1:0], B [3:2], X [5:4]: 0 lr, 1 ll, 2 top
    output logic      [1:0]  osk_open,      // clk: the keypads, player 1 [0], player 2 [1]
    output logic      [7:0]  osk_cur,       //   cursor cells 0-11 (player 1 [3:0])
    output logic      [7:0]  osk_held,      //   the pressed cell + 1, 0 none
    output logic      [7:0]  pad_r,         // $01FE, PSG port A
    output logic      [7:0]  pad_l,         // $01FF, PSG port B
    output logic      [63:0] ecs_keys,      // clk: the ECS matrix's pressed switches
    output logic             ecs_synth,
    output logic      [1:0]  ecs_ovr
);

    // -------------------------------------------------------------------
    // Codes: the lines each input pulls low (DESIGN.md 7.1)
    // -------------------------------------------------------------------
    localparam logic [7:0] K_CLEAR = 8'h88, K_ENTER = 8'h28;
    localparam logic [7:0] S_TOP = 8'hA0, S_LL = 8'h60, S_LR = 8'hC0;

    // a side action: 0 lower right, 1 lower left, 2 top
    function automatic logic [7:0] side_code(input logic [1:0] s);
        side_code = s == 2'd0 ? S_LR : s == 2'd1 ? S_LL : S_TOP;
    endfunction

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

    // The disc from a D-pad: 8 directions (opposites cancel); turn = 1 turns
    // each one notch (22.5 deg) clockwise, to the 8 in-between directions
    // (L in Layer mode: N -> NNE, E -> ESE, S -> SSW, W -> WNW)
    function automatic logic [7:0] dpad_code(input logic u, input logic d, input logic l, input logic r,
                                             input logic turn);
        logic uu, dd, ll, rr, on;
        logic [3:0] k;
        uu = u & ~d;  dd = d & ~u;  ll = l & ~r;  rr = r & ~l;
        on = 1'b1;
        unique case ({uu, dd, ll, rr})
            4'b1000: k = 4'd0;
            4'b1001: k = 4'd2;
            4'b0001: k = 4'd4;
            4'b0101: k = 4'd6;
            4'b0100: k = 4'd8;
            4'b0110: k = 4'd10;
            4'b0010: k = 4'd12;
            4'b1010: k = 4'd14;
            default: begin k = 4'd0; on = 1'b0; end
        endcase
        dpad_code = on ? disc_code(k + {3'b000, turn}) : 8'h00;
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
                                          input logic [1:0] mode, input logic [5:0] sides);
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
            p = dpad_code(up, dn, lt, rt, 1'b0) | ring_code(bx, bb, by, ba)
              | (l1 ? S_TOP : 8'h00) | (r1 ? key_code(4'd5) : 8'h00);
        end else begin                                          // Layer, Right stick
            if (r1)
                p = ring_code(up, dn, lt, rt)
                  | (ba ? key_code(4'd1) : 8'h00) | (bb ? key_code(4'd2) : 8'h00)
                  | (bx ? key_code(4'd3) : 8'h00) | (by ? K_ENTER : 8'h00);
            else if (l1)
                p = dpad_code(up, dn, lt, rt, 1'b1)
                  | (ba ? key_code(4'd5) : 8'h00) | (bb ? K_CLEAR : 8'h00)
                  | (bx ? key_code(4'd0) : 8'h00);
            else
                p = dpad_code(up, dn, lt, rt, 1'b0)
                  | (ba ? side_code(sides[1:0]) : 8'h00) | (bb ? side_code(sides[3:2]) : 8'h00)
                  | (bx ? side_code(sides[5:4]) : 8'h00);
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

    // With the ECS: the numpad only (numpad . = Clear)
    function automatic logic [7:0] hid_code_ecs(input logic [7:0] c);
        if (c >= 8'h59 && c <= 8'h61)           // numpad 1-9
            hid_code_ecs = key_code(4'(c - 8'h58));
        else if (c == 8'h62)                    // numpad 0
            hid_code_ecs = key_code(4'd0);
        else if (c == 8'h58)                    // numpad Enter
            hid_code_ecs = K_ENTER;
        else if (c == 8'h63)                    // numpad . (Del)
            hid_code_ecs = K_CLEAR;
        else
            hid_code_ecs = 8'h00;
    endfunction

    // One HID usage code -> the ECS matrix switch it closes (bit 8 row + column;
    // bit 6 set: none)
    function automatic logic [6:0] ecs_hid(input logic [7:0] c);
        logic [6:0] p;
        p = 7'h7F;
        unique case (c)
            8'h28: p = 7'd6;   8'h27: p = 7'd5;   8'h29: p = 7'd4;   8'h13: p = 7'd3;
            8'h33: p = 7'd2;   8'h37: p = 7'd1;   8'h50: p = 7'd0;   8'h2A: p = 7'd0;
            8'h0F: p = 7'd15;  8'h12: p = 7'd14;  8'h25: p = 7'd13;  8'h26: p = 7'd12;
            8'h0C: p = 7'd11;  8'h0E: p = 7'd10;  8'h10: p = 7'd9;   8'h36: p = 7'd8;
            8'h0D: p = 7'd23;  8'h18: p = 7'd22;  8'h23: p = 7'd21;  8'h24: p = 7'd20;
            8'h1C: p = 7'd19;  8'h0B: p = 7'd18;  8'h05: p = 7'd17;  8'h11: p = 7'd16;
            8'h0A: p = 7'd31;  8'h17: p = 7'd30;  8'h21: p = 7'd29;  8'h22: p = 7'd28;
            8'h15: p = 7'd27;  8'h09: p = 7'd26;  8'h06: p = 7'd25;  8'h19: p = 7'd24;
            8'h07: p = 7'd39;  8'h08: p = 7'd38;  8'h1F: p = 7'd37;  8'h20: p = 7'd36;
            8'h1A: p = 7'd35;  8'h16: p = 7'd34;  8'h1D: p = 7'd33;  8'h1B: p = 7'd32;
            8'h04: p = 7'd47;  8'h4F: p = 7'd45;  8'h1E: p = 7'd44;  8'h14: p = 7'd43;
            8'h52: p = 7'd42;  8'h51: p = 7'd41;  8'h2C: p = 7'd40;
            default: ;
        endcase
        ecs_hid = p;
    endfunction

    // One HID usage code -> the synthesizer key (note n = matrix bit n; bit 6
    // set: none)
    function automatic logic [6:0] syn_hid(input logic [7:0] c);
        logic [6:0] n;
        n = 7'h7F;
        unique case (c)
            8'h1D: n = 7'd12;  8'h16: n = 7'd13;  8'h1B: n = 7'd14;  8'h07: n = 7'd15;
            8'h06: n = 7'd16;  8'h19: n = 7'd17;  8'h0A: n = 7'd18;  8'h05: n = 7'd19;
            8'h0B: n = 7'd20;  8'h11: n = 7'd21;  8'h0D: n = 7'd22;  8'h10: n = 7'd23;
            8'h14: n = 7'd24;  8'h1F: n = 7'd25;  8'h1A: n = 7'd26;  8'h20: n = 7'd27;
            8'h08: n = 7'd28;  8'h15: n = 7'd29;  8'h22: n = 7'd30;  8'h17: n = 7'd31;
            8'h23: n = 7'd32;  8'h1C: n = 7'd33;  8'h24: n = 7'd34;  8'h18: n = 7'd35;
            8'h0C: n = 7'd36;
            default: ;
        endcase
        syn_hid = n;
    endfunction

    // -------------------------------------------------------------------
    // Crossing: clk_74a -> clk as one word (toggle handshake)
    // -------------------------------------------------------------------
    localparam int W = 6 * 32 + 16 + 2 + 1 + 3;
    wire logic [W-1:0] in_74 = {cont1_key, cont1_joy, cont2_key, cont2_joy, cont3_key, cont3_joy,
                                cont3_trig, kp_mode, swap, ecs_ovr_74, synth_74};

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

    logic [2:0] ph;             // the decode round (Output below)
    initial ph = 3'd0;

    always_ff @(posedge clk) begin
        req_s <= {req_s[0], req_74};
        if (req_s[1] != ack && ph == 3'd7) begin
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
    logic [1:0]  eo;
    logic        sy;
    assign {k1, j1, k2, j2, k3, j3, t3, md, sw, eo, sy} = word;
    assign ecs_synth = sy;
    assign ecs_ovr   = eo;

    // The round: step ph < 6 decodes code ph into the accumulators; step 6
    // registers the outputs from them and the word; step 7 lets a new word in
    logic [7:0]  hc, kc, kb_acc;
    logic [6:0]  sp;
    logic [63:0] ek_acc;
    wire  logic  kbd = k3[31:28] == 4'd4;
    always_comb begin
        unique case (ph)
            3'd0:    hc = j3[7:0];
            3'd1:    hc = j3[15:8];
            3'd2:    hc = j3[23:16];
            3'd3:    hc = j3[31:24];
            3'd4:    hc = t3[7:0];
            default: hc = t3[15:8];
        endcase
        kc = !kbd ? 8'h00 : ecs_full ? hid_code_ecs(hc) : hid_code(hc);
        sp = sy ? syn_hid(hc) : ecs_hid(hc);
    end

    // -------------------------------------------------------------------
    // The on-screen keypads (tools/osk.py Player)
    // -------------------------------------------------------------------
    // a cell's key: 1-9, Clear, 0, Enter
    function automatic logic [7:0] cell_code(input logic [3:0] c);
        unique case (c)
            4'd9:    cell_code = K_CLEAR;
            4'd10:   cell_code = key_code(4'd0);
            4'd11:   cell_code = K_ENTER;
            default: cell_code = key_code(c + 4'd1);
        endcase
    endfunction

    logic [15:0] o_prev [2], o_mask [2];
    logic [3:0]  o_cur [2], o_held [2];
    logic        o_open [2];
    initial for (int n = 0; n < 2; n++) begin
        o_prev[n] = 16'd0; o_mask[n] = 16'd0; o_cur[n] = 4'd4; o_held[n] = 4'd0; o_open[n] = 1'b0;
    end

    always_ff @(posedge clk) begin
        if (frame) begin
            for (int n = 0; n < 2; n++) begin : step
                /* verilator lint_off UNUSEDSIGNAL */
                logic [31:0] k;
                logic [15:0] b, rise;
                /* verilator lint_on UNUSEDSIGNAL */
                logic [1:0]  r, c;
                k = n == 0 ? k1 : k2;
                b = k[15:0];
                rise = b & ~o_prev[n];
                r = o_cur[n] >= 4'd9 ? 2'd3 : o_cur[n] >= 4'd6 ? 2'd2 : o_cur[n] >= 4'd3 ? 2'd1 : 2'd0;
                c = 2'(o_cur[n] - 4'(3 * r));
                if (!(k[31:28] == 4'd1 || k[31:28] == 4'd2 || k[31:28] == 4'd3)) begin
                    o_open[n] <= 1'b0; o_held[n] <= 4'd0; o_mask[n] <= 16'd0; o_prev[n] <= 16'd0;
                end else begin
                    o_prev[n] <= b;
                    if (!o_open[n]) begin
                        o_mask[n] <= o_mask[n] & b;
                        if (rise[14]) begin
                            o_open[n] <= 1'b1; o_held[n] <= 4'd0;
                        end
                    end else if (rise[14] || rise[5]) begin            // Select, B
                        o_open[n] <= 1'b0; o_held[n] <= 4'd0; o_mask[n] <= b;
                    end else begin
                        o_mask[n] <= o_mask[n] & b;
                        if (rise[0]) r = r == 2'd0 ? 2'd3 : r - 2'd1;          // up
                        if (rise[1]) r = r == 2'd3 ? 2'd0 : r + 2'd1;          // down
                        if (rise[2]) c = c == 2'd0 ? 2'd2 : c - 2'd1;          // left
                        if (rise[3]) c = c == 2'd2 ? 2'd0 : c + 2'd1;          // right
                        if (!b[4]) o_held[n] <= 4'd0;
                        else if (rise[4]) o_held[n] <= o_cur[n] + 4'd1;
                        o_cur[n] <= 4'(3 * r) + {2'd0, c};
                    end
                end
            end
        end
    end

    always_comb begin
        osk_open = {o_open[1], o_open[0]};
        osk_cur  = {o_cur[1], o_cur[0]};
        osk_held = {o_held[1], o_held[0]};
    end

    // Auto (3): the profile's mode and sides; the fixed modes: the usual sides
    wire logic       auto = md == 2'd3;
    wire logic [1:0] pmd  = auto ? (prof_ok ? prof_mode : 2'd0) : md;
    wire logic [5:0] psd  = auto && prof_ok ? prof_sides : 6'b10_01_00;

    logic [7:0]  p1, p2;
    always_comb begin
        p1 = player({k1[31:16], k1[15:0] & ~(o_open[0] ? 16'hFFFF : o_mask[0])}, j1, pmd, psd) | kb_acc
           | (o_open[0] && o_held[0] != 4'd0 ? cell_code(o_held[0] - 4'd1) : 8'h00);
        p2 = player({k2[31:16], k2[15:0] & ~(o_open[1] ? 16'hFFFF : o_mask[1])}, j2, pmd, psd)
           | (o_open[1] && o_held[1] != 4'd0 ? cell_code(o_held[1] - 4'd1) : 8'h00);
    end

    initial begin
        pad_r = 8'hFF;
        pad_l = 8'hFF;
        ecs_keys = 64'd0;
        kb_acc = 8'h00;
        ek_acc = 64'd0;
    end
    always_ff @(posedge clk) begin
        ph <= ph + 3'd1;
        if (ph < 3'd6) begin
            kb_acc <= (ph == 3'd0 ? 8'h00 : kb_acc) | kc;
            ek_acc <= (ph == 3'd0 ? 64'd0 : ek_acc)
                    | (kbd && ecs_full && !sp[6] ? 64'd1 << sp[5:0] : 64'd0);
        end
        if (ph == 3'd6) begin
            pad_l <= ~(sw ? p2 : p1);
            pad_r <= ~(sw ? p1 : p2);
            ecs_keys <= ek_acc
                      | (kbd && ecs_full && !sy && (k3[1] | k3[5]) ? 64'd1 << 55 : 64'd0)   // Shift: row 6, column 7
                      | (kbd && ecs_full && !sy && (k3[0] | k3[4]) ? 64'd1 << 46 : 64'd0);  // Ctrl: row 5, column 6
        end
    end

endmodule

`default_nettype wire
