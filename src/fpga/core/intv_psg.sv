// Intellivision core: the PSG, AY-3-8914 (build step 6; DESIGN.md 3
// module 9, 6.2). The golden model is tools/psg.py; every fact and source
// is listed there and in docs/PSG_NOTES.md. In short:
//
// Registers at $01F0 + n in the Intellivision order (MAME ay8910.cpp:1533),
// kept bits as MAME's AY-3-8914 read masks (ay8910.cpp:1430-1450):
//   n     0    1    2    3    4    5    6    7    8    9    10   11   12   13
//   use   Af   Bf   Cf   Ef   Ac   Bc   Cc   Ec   en   nz   shp  Av   Bv   Cv
//   mask  FF   FF   FF   FF   0F   0F   0F   FF   FF   1F   0F   3F   3F   3F
// $01FE / $01FF read the right / left hand controllers (pad_r, pad_l);
// the ports are inputs, the direction bits 6-7 of the enable register are
// ignored (DESIGN 7.1). PSG #2 of the ECS (intv_ecs, step 9) reads its
// ports' lines through pad_r / pad_l too and takes the directions from
// ctrl (register 8). Machine reset clears everything (MAME
// ay8910_reset_ym: registers 0, LFSR 1, envelope restarted).
//
// Timing (DESIGN 2.3): the PSG divides its master / 2 clock by 8, so its
// generators take one step ("tick") every 4 CPU cycles. ce is the CPU
// cycle enable; run is 0 while the CPU is held after reset (intv_bus
// hold), and the PSG holds too, so that its first tick ends the CPU's first
// cycle (the model's cycle 0) and then every 4th: ticks end cycles 0, 4, 8,
// ... A write (we, at the ce that ends the DW cycle) lands after the tick
// of that ce: the tick uses the old registers, a shape write's envelope
// restart overrides that tick's envelope step.
//   tone      12-bit period P: the count runs 0 .. P-1 (P = 0 as 1) and the
//             output toggles at the end: F = master / (32 P)
//   noise     5-bit period N: a prescaler flip-flop toggles every N ticks
//             (0 as 1), the 17-bit LFSR (input bit0 ^ bit3, DESIGN
//             decision 3) shifts when it falls
//   envelope  16-bit period E: a step every 2 E ticks (E = 0: every tick);
//             step 15 down to 0, volume = step ^ attack; at the end of a
//             cycle hold or (alternate) invert, wrap to 15; a shape write
//             restarts at 15
//   mixer     channel on = (tone out | tone off) & (noise out | noise off)
//   volume    bits 5-4: 00 fixed bits 3-0, 01 envelope >> 2, 10 >> 1,
//             11 envelope (AY-3-8914; ENV2 = 0 is the AY-3-8916/8917 of
//             the ECS: bit 4 alone selects the envelope)
//   DAC       one 16-level curve (MAME ay8910.cpp ay8910_param, legacy
//             normalisation) scaled to 0..10922; the board ties the three
//             outputs together, so the mix is their sum (DESIGN 6.2)
//
// 48 kHz (DESIGN 6.2): every tick takes the mix of the three channels as
// they were up to it (before its step), x 256, through two one-pole low
// passes (y += (x - y) >> 1 each: -3 dB near 16.5 kHz at the 223.7 kHz
// step rate, against aliasing) and adds the second's output >> 8 to a box
// filter; a phase accumulator (+768,000 per tick, wrap 3,579,545: exactly
// 48 kHz from master / 16) ends each sample, the box's sum times 65536 /
// ticks (4 or 5) >> 16. audio is that sample, 0..32766 (silence 0), held;
// audio_stb marks a new one. The filter is not machine state (DESIGN
// 4.4).
//
// Save state (DESIGN 4.3; module id SS_ID, 21 words; ss_rdata 0 unless
// addressed; write only while the machine is frozen):
//   0-13  the registers (kept bits)
//   14-16 tone A-C: [11:0] count, [12] output
//   17    noise: [4:0] count, [5] prescaler
//   18    [16:0] LFSR
//   19    [16:0] envelope count
//   20    [3:0] envelope step, [4] attack, [5] holding, [7:6] tick phase
//         (the CPU cycle's number mod 4)
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_psg #(
    parameter logic [7:0] SS_ID = 8'h05,
    parameter bit         ENV2  = 1'b1        // two envelope-select bits (AY-3-8914)
) (
    input  wire logic        clk,
    input  wire logic        reset,
    input  wire logic        ce,              // CPU cycle enable
    input  wire logic        run,             // 0 while the CPU is held after reset
    input  wire logic [3:0]  n,               // address [3:0]
    input  wire logic        we,              // write strobe, decoded (at ce)
    input  wire logic [7:0]  wdata,
    output logic      [7:0]  q,
    input  wire logic [7:0]  pad_r,           // $01FE
    input  wire logic [7:0]  pad_l,           // $01FF
    output logic      [7:0]  ctrl,            // register 8 (port directions: the ECS, step 9)

    output logic      [15:0] audio,           // 48 kHz, 0..32766
    output logic             audio_stb,

    input  wire logic [15:0] ss_addr,
    input  wire logic        ss_we,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [31:0] ss_wdata,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic [31:0]      ss_rdata
);

    localparam logic [21:0] SR_STEP = 22'd768000, SR_WRAP = 22'd3579545;

    // ------------------------------------------------------------ state
    logic [7:0]  r [0:13];
    logic [11:0] tcnt [0:2];
    logic [2:0]  tout;
    logic [4:0]  ncnt;
    logic        npre;
    logic [16:0] rng;
    logic [16:0] ecnt;
    logic [3:0]  estep;
    logic        eatt, ehold;
    logic [1:0]  tph;
    // the 48 kHz filter (not saved)
    logic [22:0] lp1, lp2;
    logic [17:0] box;
    logic [2:0]  bcnt;
    logic [21:0] srph;

    initial begin
        for (int i = 0; i < 14; i++) r[i] = 8'd0;
        for (int i = 0; i < 3; i++) tcnt[i] = 12'd0;
        tout = 3'd0; ncnt = 5'd0; npre = 1'b0; rng = 17'd1;
        ecnt = 17'd0; estep = 4'd15; eatt = 1'b0; ehold = 1'b0; tph = 2'd3;
        lp1 = 23'd0; lp2 = 23'd0;
        box = 18'd0; bcnt = 3'd0; srph = 22'd0; audio = 16'd0; audio_stb = 1'b0;
    end

    function automatic logic [7:0] mask(input logic [3:0] k);
        unique case (k)
            4'd4, 4'd5, 4'd6, 4'd10: mask = 8'h0F;
            4'd9:                    mask = 8'h1F;
            4'd11, 4'd12, 4'd13:     mask = 8'h3F;
            default:                 mask = 8'hFF;
        endcase
    endfunction

    // MAME ay8910.cpp ay8910_param through build_single_table (zero is off),
    // normalised and scaled to 0..10922 (tools/psg.py DAC)
    function automatic logic [13:0] dac(input logic [3:0] l);
        unique case (l)
            4'd0:  dac = 14'd0;     4'd1:  dac = 14'd148;   4'd2:  dac = 14'd193;
            4'd3:  dac = 14'd252;   4'd4:  dac = 14'd343;   4'd5:  dac = 14'd476;
            4'd6:  dac = 14'd639;   4'd7:  dac = 14'd1040;  4'd8:  dac = 14'd1283;
            4'd9:  dac = 14'd2101;  4'd10: dac = 14'd2909;  4'd11: dac = 14'd3863;
            4'd12: dac = 14'd5161;  4'd13: dac = 14'd6539;  4'd14: dac = 14'd8656;
            default: dac = 14'd10922;
        endcase
    endfunction

    assign ctrl = r[8];

    always_comb begin
        unique case (n)
            4'd14:   q = pad_r;
            4'd15:   q = pad_l;
            default: q = r[n];
        endcase
    end

    // ------------------------------------------------------- the levels
    wire logic [3:0] ev = estep ^ {4{eatt}};
    logic [3:0] lv [0:2];
    always_comb begin
        for (int c = 0; c < 3; c++) begin
            logic [1:0] sel;
            logic [3:0] l;
            logic       on;
            sel = ENV2 ? r[11 + c][5:4] : {2{r[11 + c][4]}};
            unique case (sel)
                2'd0: l = r[11 + c][3:0];
                2'd1: l = ev >> 2;
                2'd2: l = ev >> 1;
                default: l = ev;
            endcase
            on = (tout[c] | r[8][c]) & (rng[0] | r[8][3 + c]);
            lv[c] = on ? l : 4'd0;
        end
    end
    wire logic [14:0] mix = 15'(dac(lv[0])) + 15'(dac(lv[1])) + 15'(dac(lv[2]));   // <= 32766

    // ------------------------------------------------------- the steps
    wire logic        tick = ce && run && tph == 2'd0;
    wire logic [3:0]  shape = r[10][3:0];
    wire logic        s_hold = shape[3] ? shape[0] : 1'b1;
    wire logic        s_alt  = shape[3] ? shape[1] : shape[2];
    wire logic [16:0] eper2  = {r[7], r[3], 1'b0};

    wire logic        ss_hit = ss_addr[15:8] == SS_ID && ss_addr[7:0] < 8'd21;
    wire logic [4:0]  ss_w   = ss_addr[4:0];
    wire logic [1:0]  ss_ch  = 2'(ss_w - 5'd14);     // tone words 14-16

    // the filter's next values
    wire logic signed [23:0] d1    = $signed({1'b0, mix, 8'd0}) - $signed({1'b0, lp1});
    wire logic        [22:0] lp1_n = 23'($signed({1'b0, lp1}) + (d1 >>> 1));
    wire logic signed [23:0] d2    = $signed({1'b0, lp1_n}) - $signed({1'b0, lp2});
    wire logic        [22:0] lp2_n = 23'($signed({1'b0, lp2}) + (d2 >>> 1));
    wire logic [17:0] box_n  = box + 18'(lp2_n[22:8]);
    wire logic [2:0]  bcnt_n = bcnt + 3'd1;
    wire logic [22:0] srph_n = 23'(srph) + 23'(SR_STEP);
    /* verilator lint_off UNUSEDSIGNAL */
    wire logic [32:0] prod   = 33'(box_n) * 33'(bcnt_n == 3'd5 ? 15'd13107 : 15'd16384);
    /* verilator lint_on UNUSEDSIGNAL */

    always_ff @(posedge clk) begin
        audio_stb <= 1'b0;
        if (reset) begin
            for (int i = 0; i < 14; i++) r[i] <= 8'd0;
            for (int i = 0; i < 3; i++) tcnt[i] <= 12'd0;
            tout <= 3'd0; ncnt <= 5'd0; npre <= 1'b0; rng <= 17'd1;
            ecnt <= 17'd0; estep <= 4'd15; eatt <= 1'b0; ehold <= 1'b0; tph <= 2'd3;
            lp1 <= 23'd0; lp2 <= 23'd0;
            box <= 18'd0; bcnt <= 3'd0; srph <= 22'd0; audio <= 16'd0;
        end else if (ss_we && ss_hit) begin
            if (ss_w < 5'd14)
                r[ss_w[3:0]] <= ss_wdata[7:0] & mask(ss_w[3:0]);
            else unique case (ss_w)
                5'd14, 5'd15, 5'd16: begin
                    tcnt[ss_ch] <= ss_wdata[11:0];
                    tout[ss_ch] <= ss_wdata[12];
                end
                5'd17: {npre, ncnt} <= ss_wdata[5:0];
                5'd18: rng <= ss_wdata[16:0];
                5'd19: ecnt <= ss_wdata[16:0];
                default: {tph, ehold, eatt, estep} <= ss_wdata[7:0];
            endcase
        end else begin
            if (ce && run)
                tph <= tph + 2'd1;
            if (tick) begin
                for (int c = 0; c < 3; c++) begin
                    if (13'(tcnt[c]) + 13'd1 >= {1'b0, r[4 + c][3:0], r[c]}) begin
                        tcnt[c] <= 12'd0;
                        tout[c] <= !tout[c];
                    end else
                        tcnt[c] <= tcnt[c] + 12'd1;
                end
                if (6'(ncnt) + 6'd1 >= {1'b0, r[9][4:0]}) begin
                    ncnt <= 5'd0;
                    npre <= !npre;
                    if (npre)
                        rng <= {rng[0] ^ rng[3], rng[16:1]};
                end else
                    ncnt <= ncnt + 5'd1;
                if (!ehold) begin
                    if (18'(ecnt) + 18'd1 >= {1'b0, eper2}) begin
                        ecnt <= 17'd0;
                        if (estep == 4'd0) begin
                            if (s_alt) eatt <= !eatt;
                            if (s_hold) ehold <= 1'b1;
                            else        estep <= 4'd15;
                        end else
                            estep <= estep - 4'd1;
                    end else
                        ecnt <= ecnt + 17'd1;
                end
                // the 48 kHz filter
                lp1 <= lp1_n;
                lp2 <= lp2_n;
                if (srph_n >= 23'(SR_WRAP)) begin
                    audio     <= prod[31:16];
                    audio_stb <= 1'b1;
                    box  <= 18'd0;
                    bcnt <= 3'd0;
                    srph <= 22'(srph_n - 23'(SR_WRAP));
                end else begin
                    box  <= box_n;
                    bcnt <= bcnt_n;
                    srph <= 22'(srph_n);
                end
            end
            if (we && n < 4'd14) begin
                r[n] <= wdata & mask(n);
                if (n == 4'd10) begin           // every shape write restarts the envelope
                    estep <= 4'd15;
                    ehold <= 1'b0;
                    eatt  <= wdata[2];
                end
            end
        end
    end

    always_comb begin
        ss_rdata = 32'd0;
        if (ss_hit) begin
            if (ss_w < 5'd14)
                ss_rdata = {24'd0, r[ss_w[3:0]]};
            else unique case (ss_w)
                5'd14, 5'd15, 5'd16:
                    ss_rdata = {19'd0, tout[ss_ch], tcnt[ss_ch]};
                5'd17: ss_rdata = {26'd0, npre, ncnt};
                5'd18: ss_rdata = {15'd0, rng};
                5'd19: ss_rdata = {15'd0, ecnt};
                default: ss_rdata = {24'd0, tph, ehold, eatt, estep};
            endcase
        end
    end

endmodule

`default_nettype wire
