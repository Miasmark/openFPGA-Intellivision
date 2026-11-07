// Intellivision core: the Entertainment Computer System (DESIGN.md 2.6, 3
// module 13, 7.3, 20; build step 9). The golden model is tools/ecs.py;
// every fact and source is listed there. In short:
//
//   $00E0-$00E3  the UART: answered here, its tape side is intv_tape (the
//                cassette as a file, 1.0.5; until then a stub that read
//                $0002, "ready, nothing received")
//   $00F0-$00FF  PSG #2, the AY-3-8917 (intv_psg with ENV2 = 0: one
//                envelope-select bit), reads $FF00 | register; $00FE /
//                $00FF are its ports A / B: the keyboard matrix
//   $4000-$47FF  ECS RAM 2,048 x 8, reads $00 | byte
//   $2000, $7000, $E000: the ECS ROMs, read by intv_cart from the SRAM
//                (ECS.bin at ECS_BASE) on their pages: page latch $2 = 1,
//                $7 = 0, $E = 1; any other value pages the ROM out. This
//                module keeps the latches (pg, to intv_cart): a write of
//                $xA5y to $xFFF, x = 2, 7, E, sets latch x to y.
// Where the ECS answers, the cartridge does not (intv_cart: ecs_on, pg).
//
// Modes (mode, taken at machine reset into the state): 0 off (nothing
// answers, PSG #2 held in reset), 1 on (latches 0 at reset: $7000 answers,
// the EXEC runs the ECS boot), 2 attached with the ROMs paged out (latch $7
// = $F at reset; RAM, PSG #2, keyboard and UART answer). intv_media's Auto
// rule and the menu pick it (DESIGN 20).
//
// Keyboard (DESIGN 7.3): keys[8 r + c] = a pressed switch joining row r
// (port A line r) and column c (port B line c), from intv_input. Register
// 8 ($F8) bit 6 makes port A an output (all its lines driven with its
// latch), bit 7 port B. Computer keyboard (synth = 0, no diodes): a line
// reads 0 if a line driven 0 reaches it through pressed switches and no
// line driven 1 does, else 1 (1 beats 0; the pull-ups): ghosting and the
// masking of keys that share a column on a row scan. The reach is found by
// a small engine that restarts every PASS clk_sys: one clock loads the
// driven lines, 16 more widen both sets one switch further in each
// direction (a path through the 16 lines has at most 15 switches), then
// the port values are registered. They are at most 2 x PASS = 34 clk_sys
// old, less than a CPU cycle (48 clk_sys): the latches and register 8
// change at a write at least two CPU cycles before any read, and a key
// change at the start of a cycle is seen by a read in it. Synthesizer
// (synth = 1, diodes): a column reads 0 if a pressed key joins it to a row
// driven 0; a row reads its own drive or 1. A port reads its lines whether
// input or output (MAME ay8910.cpp:1403-1425).
//
// Save state (DESIGN 4.3; tools/savestate.py):
//   SS_ID (1 word)        [3:0] latch $2, [7:4] latch $7, [11:8] latch $E,
//                         [19:12] port A latch, [27:20] port B latch,
//                         [29:28] mode
//   SS_PSG (21 words)     PSG #2 (intv_psg's words)
//   SS_RAM (512 words)    the RAM, four cells a word (cell 4 i + k in bits
//                         8 k + 7 .. 8 k of word i); its block RAM port
//                         belongs to the state port while ss_en (intv_ram)
// The matrix engine and the filter are not state (recomputed, DESIGN 4.4).
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_ecs #(
    parameter logic [7:0] SS_ID  = 8'h0E,
    parameter logic [7:0] SS_PSG = 8'h0F,
    parameter logic [7:0] SS_RAM = 8'h10,
    parameter int         PASS   = 17
) (
    input  wire logic        clk,
    input  wire logic        mreset,
    input  wire logic [1:0]  mode,            // at machine reset: 0 off, 1 on, 2 attached
    input  wire logic        ce,              // CPU cycle enable
    input  wire logic        run,             // 0 while the CPU is held after reset

    // CPU bus (intv_bus)
    input  wire logic [15:0] a,               // latched address
    input  wire logic        wr,              // ce of DW
    input  wire logic [15:0] wdata,
    output logic             hit,             // the ECS answers a (UART, PSG #2, RAM)
    output logic [15:0]      q,
    input  wire logic [15:0] uart_q,          // the UART ($00E0-$00E3): intv_tape, the cassette

    // to intv_cart: the ROM page latches and whether the ECS is attached
    output logic             on,
    output logic             full,            // mode on (not attached): intv_input's key routing
    output logic [11:0]      pg,              // {latch $E, latch $7, latch $2}

    // keyboard (intv_input)
    input  wire logic [63:0] keys,
    input  wire logic        synth,

    output logic [15:0]      audio,           // PSG #2, 48 kHz (0..32766)
    output logic             audio_stb,

    input  wire logic        ss_en,
    input  wire logic [15:0] ss_addr,
    input  wire logic        ss_we,
    input  wire logic [31:0] ss_wdata,
    output logic [31:0]      ss_rdata
);

    localparam logic [1:0] M_OFF = 2'd0, M_ON = 2'd1, M_ATT = 2'd2;

    // ------------------------------------------------------------ state
    logic [1:0] mode_q = M_OFF;
    logic [3:0] pg2 = 4'd0, pg7 = 4'd0, pgE = 4'd0;
    logic [7:0] lat_a = 8'd0, lat_b = 8'd0;

    assign on = mode_q != M_OFF;
    assign full = mode_q == M_ON;
    assign pg = {pgE, pg7, pg2};

    // -------------------------------------------------------------- decode
    wire logic sel_uart = a[15:2] == 14'h0038;            // $00E0-$00E3
    wire logic sel_psg  = a[15:4] == 12'h00F;             // $00F0-$00FF
    wire logic sel_ram  = a[15:11] == 5'b01000;           // $4000-$47FF
    assign hit = on && (sel_uart || sel_psg || sel_ram);

    wire logic ss_hit0 = ss_addr == {SS_ID, 8'd0};

    // page latch write: $xA5y to $xFFF, x = 2, 7, E
    wire logic pg_w = wr && a[11:0] == 12'hFFF && wdata[15:4] == {a[15:12], 8'hA5};

    always_ff @(posedge clk) begin
        if (mreset) begin
            mode_q <= mode;
            pg2 <= 4'd0;
            pg7 <= mode == M_ATT ? 4'hF : 4'd0;
            pgE <= 4'd0;
            lat_a <= 8'd0;
            lat_b <= 8'd0;
        end else if (ss_we && ss_hit0) begin
            {mode_q, lat_b, lat_a, pgE, pg7, pg2} <= ss_wdata[29:0];
        end else if (on) begin
            if (pg_w && a[15:12] == 4'h2) pg2 <= wdata[3:0];
            if (pg_w && a[15:12] == 4'h7) pg7 <= wdata[3:0];
            if (pg_w && a[15:12] == 4'hE) pgE <= wdata[3:0];
            if (wr && sel_psg && a[3:0] == 4'hE) lat_a <= wdata[7:0];
            if (wr && sel_psg && a[3:0] == 4'hF) lat_b <= wdata[7:0];
        end
    end

    // ---------------------------------------------------------- PSG #2
    logic [7:0]  psg_q;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [7:0]  ctrl;                              // [7:6] the port directions
    /* verilator lint_on UNUSEDSIGNAL */
    logic [7:0]  port_a = 8'hFF, port_b = 8'hFF;   // the lines as read
    logic [31:0] ssr_psg;

    intv_psg #(.SS_ID(SS_PSG), .ENV2(1'b0)) psg (
        .clk, .reset(mreset || !on), .ce, .run, .n(a[3:0]), .we(wr && sel_psg && on),
        .wdata(wdata[7:0]), .q(psg_q), .pad_r(port_a), .pad_l(port_b), .ctrl,
        .audio, .audio_stb,
        .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_psg));

    // ---------------------------------------------------------- keyboard
    wire logic dir_a = ctrl[6], dir_b = ctrl[7];
    logic [4:0]  step = 5'd0;
    logic [7:0]  r0 = 8'd0, c0 = 8'd0, r1 = 8'd0, c1 = 8'd0;   // lines reached from a driven 0 / 1
    logic [63:0] k = 64'd0;                                    // the switches of this pass

    function automatic logic [7:0] to_cols(input logic [7:0] r, input logic [63:0] sw);
        for (int c = 0; c < 8; c++) begin
            to_cols[c] = 1'b0;
            for (int i = 0; i < 8; i++) to_cols[c] = to_cols[c] | (r[i] & sw[8 * i + c]);
        end
    endfunction
    function automatic logic [7:0] to_rows(input logic [7:0] c, input logic [63:0] sw);
        for (int i = 0; i < 8; i++)
            to_rows[i] = |(c & sw[8 * i +: 8]);
    endfunction

    // synthesizer: a column is pulled low through a diode by a key on a row driven 0
    wire logic [7:0] syn_rows0 = dir_a ? ~lat_a : 8'd0;
    wire logic [7:0] syn_b = ~(to_cols(syn_rows0, keys) | (dir_b ? ~lat_b : 8'd0));
    wire logic [7:0] syn_a = dir_a ? lat_a : 8'hFF;

    always_ff @(posedge clk) begin
        step <= step == 5'(PASS - 1) ? 5'd0 : step + 5'd1;
        if (step == 5'd0) begin                                 // load the driven lines
            k  <= keys;
            r0 <= dir_a ? ~lat_a : 8'd0;
            r1 <= dir_a ?  lat_a : 8'd0;
            c0 <= dir_b ? ~lat_b : 8'd0;
            c1 <= dir_b ?  lat_b : 8'd0;
        end else begin
            r0 <= r0 | to_rows(c0, k);
            c0 <= c0 | to_cols(r0, k);
            r1 <= r1 | to_rows(c1, k);
            c1 <= c1 | to_cols(r1, k);
        end
        if (step == 5'(PASS - 1)) begin
            port_a <= synth ? syn_a : ~(r0 & ~r1);
            port_b <= synth ? syn_b : ~(c0 & ~c1);
        end
    end

    // ---------------------------------------------------------- RAM
    logic [31:0] ram [0:511];
    logic [31:0] ram_q = 32'd0;
    initial for (int i = 0; i < 512; i++) ram[i] = 32'd0;

    wire logic [15:0] ss_ri  = {ss_addr[15:8] - SS_RAM, ss_addr[7:0]};
    wire logic        ss_rhit = ss_addr[15:8] >= SS_RAM && ss_ri < 16'd512;
    wire logic [8:0]  ra   = ss_en ? ss_ri[8:0] : a[10:2];
    wire logic        rwe  = ss_en ? ss_we && ss_rhit : wr && sel_ram && on;
    wire logic [3:0]  rbe  = ss_en ? 4'hF : 4'b0001 << a[1:0];
    wire logic [31:0] rwd  = ss_en ? ss_wdata : {4{wdata[7:0]}};
    logic ss_rq = 1'b0;

    always_ff @(posedge clk) begin
        for (int b = 0; b < 4; b++)
            if (rwe && rbe[b]) ram[ra][8 * b +: 8] <= rwd[8 * b +: 8];
        ram_q <= ram[ra];
        ss_rq <= ss_en && ss_rhit;
    end

    // ---------------------------------------------------------- read data
    always_comb begin
        q = 16'hFFFF;
        if (sel_uart)     q = uart_q;
        else if (sel_psg) q = {8'hFF, psg_q};
        else if (sel_ram) q = {8'h00, ram_q[8 * a[1:0] +: 8]};
    end

    assign ss_rdata = ssr_psg
                    | (ss_hit0 ? {2'd0, mode_q, lat_b, lat_a, pgE, pg7, pg2} : 32'd0)
                    | (ss_rq ? ram_q : 32'd0);

endmodule

`default_nettype wire
