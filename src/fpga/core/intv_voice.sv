// Intellivision core: the Intellivoice on the bus (DESIGN.md 9 step 10;
// docs/VOICE_NOTES.md 8): the SPB640 at $0080-$0081 around sp0256.sv, its
// sample enable, and the module's output chain into the mix. The golden
// model is tools/sp0256.py (Voice for sp0256.sv, VoiceBus for this module).
//
// Mode (taken at machine reset): off leaves $0080-$0081 unmapped (reads
// $FFFF, writes dropped: a console without the module) and holds the chip
// in reset; on maps it. intv_core picks it (the menu's Auto / On / Off; Auto
// from the cartridge's flags: the CRC table, a CFG's voice var, a .rom's
// tag; off without ivoice.bin).
//
// Time: the sample enable is a phase accumulator on the CPU's cycle enable
// while the machine runs (ce && run, as the PSG's): +INC per cycle, a sample
// each time it passes WRAP. INC / WRAP = 88 / 7,875 gives exactly 10,000 Hz
// on NTSC clk_sys (472.5 / 11 MHz, a CPU cycle every 48 clk_sys: 10,000 x
// 528 / 472,500,000 = 88 / 7,875; VOICE_NOTES 8.2); 12,480,000 /
// 1,202,727,120 gives MAME's 3,120,000 / 336 Hz (benches). The resonator is
// not the console's, so the chip's 10 kHz need not follow the CPU clock;
// tying it to the cycle count makes the machine deterministic (save states,
// benches). The first ce after reset starts the CPU's cycle 0 and does not
// count (started; intv_psg's tph = 3 likewise): cycle numbers are the
// model's.
//
// The busy window: a sample fires at the ce that ends cycle c, after that
// ce's bus access (a write in it lands before the sample). sp0256.sv then
// makes the sample (at most about 160 clk_sys). Accesses at the ces that
// end cycles c + 1 .. c + WIN are in the window: a read gives the values
// $0080 / $0081 had when the sample fired, a write is held and lands right
// after the window's last ce (WIN = 8 cycles, 384 clk_sys: a sample is made
// well inside it, and two CPU writes are at least 9 cycles apart, so one
// write is held at most). A sample still unmade at the window's end (a
// pathological program) keeps the window open until it is made and counts
// in late (sticky; the benches check 0). tools/sp0256.py VoiceBus does the
// same on cycle numbers.
//
// The output chain (not machine state, DESIGN 4.4; VOICE_NOTES 8.5): the
// sample, clean (the filter's 14 bits, MAME's HIGH_QUALITY value) or as the
// chip's 7-bit PWM DAC gives it (dac7), held between samples, then at the
// PSG's 48 kHz strobe a one-pole high-pass at about 150 Hz (the coupling
// capacitors) and two one-pole low-passes at about 5 kHz (the LM324
// stages), times the level (0, 1/2, 1, 3/2, 2: 2 puts the speech's peak,
// 13,480 of 32,767 over the five titles, near one PSG's), into out (signed,
// added to the PSG mix by intv_machine).
//
// Save state: SS_ID words 0-19 are sp0256.sv's, 20-23 this module's:
//   20  acc[31:0]                       21  {started, late, held, held_a, mode_q, win[3:0], snap_full, snap_lrq}
//   22  held write data[15:0]           23  0
// The FIFO is SS_ID + 1 (64 words). A save only lands while the chip is
// idle (busy low: intv_ss_ctl's quiet point).
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_voice #(
    parameter logic [7:0]  SS_ID = 8'h18,
    parameter logic [31:0] INC   = 32'd88,
    parameter logic [31:0] WRAP  = 32'd7875,
    parameter int          WIN   = 8
) (
    input  wire logic        clk,
    input  wire logic        mreset,
    input  wire logic        mode,            // at machine reset: 0 off, 1 on
    input  wire logic        ce,
    input  wire logic        run,

    input  wire logic [15:0] a,
    input  wire logic        wr,              // ce of DW
    input  wire logic [15:0] wdata,
    output logic             hit,
    output logic [15:0]      q,

    output logic [10:0]      rom_addr,        // the resident ROM (intv_sysrom)
    input  wire logic [7:0]  rom_q,

    input  wire logic        dac7,            // the chip's 7-bit DAC sound instead of the clean one
    input  wire logic [2:0]  level,           // 0 off, 1-4: x 1/2, 1, 3/2, 2
    input  wire logic        audio_stb,       // the PSG's 48 kHz strobe
    output logic signed [15:0] out,
    output logic             on,
    output logic             busy,            // a sample in the making (intv_ss_ctl waits)
    output logic             late,            // a sample outlasted the window (sticky)

    input  wire logic        ss_en,
    input  wire logic [15:0] ss_addr,
    input  wire logic        ss_we,
    input  wire logic [31:0] ss_wdata,
    output logic [31:0]      ss_rdata
);

    logic        mode_q = 1'b0;
    logic [31:0] acc = 32'd0;
    logic [3:0]  win = 4'd0;              // ces left in the window
    logic        snap_lrq = 1'b1, snap_full = 1'b0;
    logic        held = 1'b0, held_a = 1'b0;
    logic [15:0] held_d = 16'd0;
    logic        fire_d = 1'b0, held_go = 1'b0;
    logic        started = 1'b0;          // the ce that starts cycle 0 has come
    initial late = 1'b0;

    assign on = mode_q;

    wire logic sel = a[15:1] == 15'h0040;                 // $0080-$0081
    assign hit = on && sel;

    // ------------------------------------------------------------ the chip
    logic        c_wr, c_wa, c_lrq, c_full, c_busy, c_done;
    logic [15:0] c_wd, c_sample;
    logic [31:0] ssr_chip;

    wire logic [32:0] acc_n = {1'b0, acc} + {1'b0, INC};
    wire logic        fire = ce && run && on && started && acc_n >= {1'b0, WRAP};

    // a write outside the window goes straight in (the chip is idle then); a held one after it
    always_comb begin
        c_wr = 1'b0; c_wa = a[0]; c_wd = wdata;
        if (held_go) begin
            c_wr = 1'b1; c_wa = held_a; c_wd = held_d;
        end else if (wr && hit && win == 4'd0 && !fire_d && !c_busy) begin
            c_wr = 1'b1;
        end
    end

    sp0256 #(.SS_ID(SS_ID)) chip (
        .clk, .reset(mreset || !on), .wr(c_wr), .wa(c_wa), .wd(c_wd), .lrq(c_lrq), .full(c_full),
        .step(fire_d), .busy(c_busy), .done(c_done), .sample(c_sample),
        .rom_addr, .rom_q,
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_chip));

    assign busy = c_busy || fire_d;

    wire logic ss_w20 = ss_addr == {SS_ID, 8'd20};
    wire logic ss_w21 = ss_addr == {SS_ID, 8'd21};
    wire logic ss_w22 = ss_addr == {SS_ID, 8'd22};

    always_ff @(posedge clk) begin
        fire_d <= 1'b0;
        held_go <= 1'b0;
        if (mreset) begin
            mode_q <= mode;
            started <= 1'b0;
            acc <= 32'd0;
            win <= 4'd0;
            held <= 1'b0;
            snap_lrq <= 1'b1;
            snap_full <= 1'b0;
        end else if (ss_we && (ss_w20 || ss_w21 || ss_w22)) begin
            if (ss_w20) acc <= ss_wdata;
            if (ss_w21) {started, late, held, held_a, mode_q, win, snap_full, snap_lrq} <= ss_wdata[10:0];
            if (ss_w22) held_d <= ss_wdata[15:0];
        end else begin
            if (ce && run && on && !started)
                started <= 1'b1;
            else if (ce && run && on)
                acc <= fire ? 32'(acc_n - {1'b0, WRAP}) : acc_n[31:0];
            if (fire_d) begin                                 // the values after the fire ce's access
                snap_lrq <= c_lrq;
                snap_full <= c_full;
            end
            if (fire) begin                                   // after this ce's access
                fire_d <= 1'b1;
                win <= 4'(WIN);
            end else if (ce && run && win != 4'd0) begin
                if (wr && hit) begin                          // held to the window's end
                    held <= 1'b1; held_a <= a[0]; held_d <= wdata;
                end
                if (win == 4'd1 && c_busy) late <= 1'b1;        // kept open until the sample is made
                else win <= win - 4'd1;
            end
            // the window's end: its held write, once the sample is made
            if (win == 4'd0 && held && !c_busy && !fire_d) begin
                held_go <= 1'b1;
                held <= 1'b0;
            end
            if (held_go) begin                                // applied: nothing held (the model's 0s)
                held_a <= 1'b0;
                held_d <= 16'd0;
            end
        end
    end

    // reads: in the window the values at the sample, else the chip's
    wire logic in_win = win != 4'd0 || fire_d;
    always_comb begin
        q = 16'hFFFF;
        if (sel)
            q = a[0] ? {in_win ? snap_full : c_full, 15'd0} : {in_win ? snap_lrq : c_lrq, 15'd0};
    end

    // ------------------------------------------------------------ output chain
    logic signed [15:0] hs = 16'sd0;                 // the held sample, clean or DAC
    logic signed [23:0] hp_lp = 24'sd0;               // a low-pass of x: within x's range
    logic signed [25:0] lp1 = 26'sd0, lp2 = 26'sd0;  // x - hp_lp: up to twice x's
    always_ff @(posedge clk) begin
        logic signed [15:0] c14;
        logic signed [23:0] x;
        logic signed [25:0] hpo;
        if (c_done) begin
            c14 = $signed(c_sample) > 16'sd8191 ? 16'sd8191 : $signed(c_sample) < -16'sd8192 ? -16'sd8192 : $signed(c_sample);
            if (dac7)                                // 7-bit code: v >> 7, -64 .. 63, at full scale
                hs <= $signed(c_sample) >>> 7 > 16'sd63 ? 16'sd63 <<< 9 : $signed(c_sample) >>> 7 < -16'sd64 ? -16'sd64 <<< 9
                    : ($signed(c_sample) >>> 7) <<< 9;
            else
                hs <= c14 <<< 2;                     // MAME's HIGH_QUALITY value
        end
        if (!on) begin
            hs <= 16'sd0; hp_lp <= 24'sd0; lp1 <= 26'sd0; lp2 <= 26'sd0;
        end else if (audio_stb) begin
            x = {hs, 8'd0};
            hp_lp <= hp_lp + (((x - hp_lp) >>> 8) * 5);    // the high-pass's own low-pass, about 150 Hz
            hpo = 26'(x) - 26'(hp_lp);
            lp1 <= lp1 + ((hpo - lp1) >>> 1);              // about 5 kHz, twice
            lp2 <= lp2 + ((lp1 - lp2) >>> 1);
        end
    end
    always_comb begin
        logic signed [17:0] v, g;
        v = 18'(lp2 >>> 8);
        case (level)
            3'd1: g = v >>> 1;
            3'd2: g = v;
            3'd3: g = v + (v >>> 1);
            3'd4: g = v <<< 1;
            default: g = 18'sd0;
        endcase
        out = g > 18'sd32767 ? 16'sh7FFF : g < -18'sd32768 ? 16'sh8000 : 16'(g);
    end

    assign ss_rdata = ssr_chip
                    | (ss_w20 ? acc : 32'd0)
                    | (ss_w21 ? {21'd0, started, late, held, held_a, mode_q, win, snap_full, snap_lrq} : 32'd0)
                    | (ss_w22 ? {16'd0, held_d} : 32'd0);

endmodule

`default_nettype wire
