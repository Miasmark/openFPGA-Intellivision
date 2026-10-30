// Intellivision core: the machine as build step 6 has it (DESIGN.md 9):
// the CP1610, the bus fabric, scratchpad, System RAM and GRAM, the STIC
// (backgrounds, MOBs and collisions, BUSRQ, the picture) and the PSG
// (sound and the hand controllers), around the cartridge port and the
// system ROMs of intv_media. The EXEC and the games run, and the bus, the
// picture and the PSG's output match tools/intv_system.py cycle by cycle
// (sim/tb/tb_system.sv).
//
//   cp1610          CPU (one bus phase per ce)
//   intv_bus        address latch, decode, data-in, IAB vectors, INTRM and
//                   the bus-copy window from the frame position, the reset
//                   hold that starts the CPU on a frame, the cartridge port
//   intv_stic       STIC: registers and handshake, row fetches from System
//                   RAM (BUSRQ), cards and MOBs from GROM / GRAM,
//                   collisions, the picture
//   intv_psg        PSG (AY-3-8914): tone, noise, envelope, the 48 kHz
//                   sound (audio, audio_stb) and the hand controllers
//   intv_ram x 3    scratchpad 256 x 8 ($0100-$01EF), System RAM 352 x 16
//                   ($0200-$035F), GRAM 512 x 8 ($3800-$3FFF)
//   intv_ecs        the ECS (build step 9): UART stub, PSG #2 and the
//                   keyboard, ECS RAM, the ROM page latches (its ROMs are
//                   read through the cartridge port: ecs_on, ecs_pg to
//                   intv_media); ecs_mode is taken at machine reset. The
//                   sound is PSG #1 + PSG #2, at most 32,767.
//   intv_jlp        the JLP (build step 11): registers, multiply / divide,
//                   CRC, random, the flash store and its engine; its RAM is
//                   intv_cart's (jlp_on), the engine an SRAM master (jm_*)
//   intv_voice      the Intellivoice (build step 10): the SPB640 at
//                   $0080-$0081 and the SP0256 (sp0256.sv), its ROM read
//                   from intv_sysrom (ivoice_addr / ivoice_q); voice_mode
//                   is taken at machine reset. Its output (signed) is added
//                   to the PSGs' and the sum saturated to 16 bits signed.
//
// ce is the CPU cycle enable from intv_timing (ce_cpu: only while the
// machine is live), ce_pix its pixel clock (ce_stic), live high on every
// clk_sys the machine runs, hcnt / vcnt its position. mreset is the
// machine reset; the CPU starts at the frame after it ends (intv_bus).
// busrq_en = 1 is the hardware (the STIC holds the CPU for its row
// fetches); 0 is the step-3 system without BUSRQ (benches only).
//
// Save state (DESIGN.md 4.3; the ids are intv_ss_pkg's, from
// tools/savestate.py, passed in by intv_core; the defaults here are the
// same, checked by `savestate.py gen --check`): all ports are OR-combined
// into ss_rdata. Write only while
// the machine is frozen and mreset is low. ss_en hands the block RAMs' port
// to the state port (their words read one clock after ss_addr; the others
// at once); it must drop two clocks before the machine runs again.
//   SS_CPU  ($02)        cp1610, 8 words
//   SS_BUS  ($03)        intv_bus, 2 words
//   SS_STIC ($04)        intv_stic, 67 words
//   SS_PSG  ($05)        intv_psg, 21 words
//   SS_SCR  ($06)        scratchpad, 256 words
//   SS_SYS  ($07, $08)   System RAM, 352 words
//   SS_GRAM ($09, $0A)   GRAM, 512 words
//   SS_ROW  ($0C)        the STIC's row buffer, 20 words
//   SS_LINE ($0D)        the STIC's line buffer, 64 words (18 bits)
//   SS_ECS  ($0E)        intv_ecs, 1 word
//   SS_PSG2 ($0F)        PSG #2, 21 words
//   SS_ERAM ($10, $11)   ECS RAM, 512 words
//   SS_VOICE ($18)       intv_voice, 24 words; its FIFO ($19), 64 words
//   SS_JLP  ($20)        intv_jlp, 28 words (build step 11; its RAM is in SRAM)
// The timing ($01) and the cartridge ($0B) have their own modules.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_machine #(
    parameter int         H_TOTAL   = 228,
    parameter int         V_TOTAL   = 262,
    parameter int         VB_CYCLES = 3790,
    parameter logic [7:0] SS_CPU  = 8'h02,
    parameter logic [7:0] SS_BUS  = 8'h03,
    parameter logic [7:0] SS_STIC = 8'h04,
    parameter logic [7:0] SS_PSG  = 8'h05,
    parameter logic [7:0] SS_SCR  = 8'h06,
    parameter logic [7:0] SS_SYS  = 8'h07,
    parameter logic [7:0] SS_GRAM = 8'h09,
    parameter logic [7:0] SS_ROW  = 8'h0C,
    parameter logic [7:0] SS_LINE = 8'h0D,
    parameter logic [7:0] SS_ECS  = 8'h0E,
    parameter logic [7:0] SS_PSG2 = 8'h0F,
    parameter logic [7:0] SS_ERAM = 8'h10,
    parameter logic [7:0] SS_VOICE = 8'h18,
    parameter logic [7:0] SS_JLP  = 8'h20
) (
    input  wire logic        clk,
    input  wire logic        mreset,
    input  wire logic        ce,
    input  wire logic        ce_pix,
    input  wire logic        live,
    input  wire logic [8:0]  hcnt,
    input  wire logic [8:0]  vcnt,
    input  wire logic        cfg_hlt_imm,
    input  wire logic        cfg_sdbd_r6_mame,
    input  wire logic        busrq_en,
    input  wire logic [7:0]  pad_r,           // hand controllers ($FF: none)
    input  wire logic [7:0]  pad_l,
    input  wire logic [1:0]  ecs_mode,        // 0 off, 1 on, 2 attached (taken at reset)
    input  wire logic [63:0] ecs_keys,        // the ECS keyboard's pressed switches
    input  wire logic        ecs_synth,       // the synthesizer instead of the keyboard
    output logic             ecs_on,          // to intv_media: the ECS ROMs
    output logic             ecs_full,        // the ECS fully on (mode on): intv_input's key routing
    output logic [11:0]      ecs_pg,
    input  wire logic        voice_mode,      // the Intellivoice: 0 off, 1 on (taken at reset)
    input  wire logic        voice_dac7,      // its 7-bit DAC sound instead of the clean one
    input  wire logic [2:0]  voice_level,     // 0 off, 1-4: x 1/2, 1, 3/2, 2
    input  wire logic [2:0]  ecs_level,       // PSG #2 only: 0 off, 1-4: x 1/2, 1, 3/2, 2 (2: as before)
    output logic             voice_on,
    output logic             voice_busy,      // a voice sample in the making (intv_ss_ctl waits)
    output logic             voice_late,      // a sample outlasted its window (sticky; benches)
    output logic [10:0]      ivoice_addr,     // the SP0256-012 ROM (intv_sysrom)
    input  wire logic [7:0]  ivoice_q,

    // the JLP (build step 11): mode and flash sectors from the loader; its RAM is
    // intv_cart's (jlp_on), its flash engine an SRAM master (jm_*)
    input  wire logic [1:0]  jlp_mode,
    input  wire logic [4:0]  jlp_sect,
    output logic             jlp_on,
    output logic             jlp_busy,
    output logic             jlp_eng_busy,    // the flash engine works (intv_ss_ctl waits)
    output logic             jm_req,
    output logic             jm_we,
    output logic [16:0]      jm_addr,
    output logic [15:0]      jm_wdata,
    input  wire logic        jm_ack,
    input  wire logic [15:0] jm_rdata,
    input  wire logic [13:0] jlp_nv_addr,     // the flash store's slot port
    input  wire logic        jlp_nv_we,
    input  wire logic [15:0] jlp_nv_wdata,
    output logic [15:0]      jlp_nv_q,

    // cartridge port and system ROMs (intv_media)
    output logic             cart_req,
    output logic             cart_we,
    output logic [15:0]      cart_addr,
    output logic [15:0]      cart_wdata,
    input  wire logic        cart_ack,
    input  wire logic [15:0] cart_rdata,
    input  wire logic        cart_hit,
    output logic [11:0]      exec_addr,
    input  wire logic [9:0]  exec_q,
    output logic [10:0]      grom_addr,
    input  wire logic [7:0]  grom_q,
    output logic [10:0]      vgrom_addr,      // the STIC's GROM port
    input  wire logic [7:0]  vgrom_q,

    output logic [3:0]       colour,          // the picture, this pixel clock
    output logic [15:0]      audio,           // the PSGs and the voice, 48 kHz, signed (PSGs alone 0..32767)
    output logic             audio_stb,

    // what the bus does (bench, later the STIC)
    output logic [2:0]       phase,
    output logic [15:0]      dout,
    output logic [15:0]      din,
    output logic [15:0]      addr,            // latched address
    output logic             fetch,
    output logic             hold,            // CPU held (reset)
    output logic             halted,

    // state port
    input  wire logic        ss_en,
    input  wire logic [15:0] ss_addr,
    input  wire logic        ss_we,
    input  wire logic [31:0] ss_wdata,
    output logic [31:0]      ss_rdata
);

    /* verilator lint_off UNUSEDSIGNAL */
    logic        wr, tci, pcit;           // not used until later steps
    logic [3:0]  ebca;
    /* verilator lint_on UNUSEDSIGNAL */
    logic        busrq, busak;
    logic [8:0]  v_sys_addr, v_gram_addr;
    logic [15:0] v_sys_q;
    logic [7:0]  v_gram_q;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [7:0]  scr_qb;                  // the scratchpad's port B is not used
    /* verilator lint_on UNUSEDSIGNAL */
    logic        intrm, rd, vb, frame_end;
    logic        scr_we, psg_we, sys_we, gram_we, stic_we;
    logic        stic_open;
    logic [15:0] stic_q, sys_q;
    logic [7:0]  scr_q, psg_q, gram_q;
    logic [31:0] ssr_cpu, ssr_bus, ssr_stic, ssr_psg, ssr_scr, ssr_sys, ssr_gram, ssr_ecs, ssr_voice, ssr_jlp;
    logic        ecs_hit, v_hit, j_hit;
    logic [15:0] ecs_q, v_q, j_q, audio1, audio2;
    logic signed [15:0] v_out;
    logic        audio1_stb;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [7:0]  psg1_ctrl;
    logic        audio2_stb;              // the same steps as PSG #1's (both reset together)
    /* verilator lint_on UNUSEDSIGNAL */

    cp1610 #(.SS_ID(SS_CPU)) cpu (
        .clk, .reset(hold && !ss_en), .ce, .cfg_hlt_imm, .cfg_sdbd_r6_mame,
        .phase, .dout, .din, .intrm, .intr(1'b0), .busrq, .busak,
        .ebca, .ebci(1'b0), .tci, .pcit, .halted, .fetch,
        .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_cpu));

    intv_bus #(.H_TOTAL(H_TOTAL), .V_TOTAL(V_TOTAL), .VB_CYCLES(VB_CYCLES),
               .SS_ID(SS_BUS)) bus (
        .clk, .mreset, .ce, .hcnt, .vcnt, .hold, .frame_end,
        .phase, .dout, .din, .intrm,
        .a(addr), .rd, .wr, .vb, .scr_we, .psg_we, .sys_we, .gram_we, .stic_we,
        .stic_open, .stic_q, .scr_q, .psg_q, .sys_q, .exec_q, .grom_q, .gram_q,
        .cart_req, .cart_we, .cart_wdata, .cart_ack, .cart_rdata,
        .cart_hit_in(cart_hit), .ecs_hit(ecs_hit || v_hit || j_hit),
        .ecs_q((ecs_hit ? ecs_q : 16'hFFFF) & (v_hit ? v_q : 16'hFFFF) & (j_hit ? j_q : 16'hFFFF)),
        .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_bus));

    assign cart_addr = addr;
    assign exec_addr = addr[11:0];
    assign grom_addr = addr[10:0];

    intv_stic #(.H_TOTAL(H_TOTAL), .V_TOTAL(V_TOTAL), .VB_CYCLES(VB_CYCLES),
                .SS_ID(SS_STIC), .SS_ROW(SS_ROW), .SS_LINE(SS_LINE)) stic (
        .clk, .reset(mreset), .ce, .ce_pix, .live, .hcnt, .vcnt,
        .vb, .frame_end, .a(addr), .wdata(dout), .rd, .we(stic_we),
        .open(stic_open), .q(stic_q), .intak(ce && phase == 3'd7),
        .busrq_en, .busrq, .busak,
        .sys_addr(v_sys_addr), .sys_q(v_sys_q), .gram_addr(v_gram_addr), .gram_q(v_gram_q),
        .grom_addr(vgrom_addr), .grom_q(vgrom_q), .colour,
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_stic));

    intv_psg #(.SS_ID(SS_PSG)) psg (
        .clk, .reset(mreset), .ce, .run(!hold), .n(addr[3:0]), .we(psg_we), .wdata(dout[7:0]),
        .q(psg_q), .pad_r, .pad_l, .ctrl(psg1_ctrl), .audio(audio1), .audio_stb(audio1_stb),
        .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_psg));

    intv_ecs #(.SS_ID(SS_ECS), .SS_PSG(SS_PSG2), .SS_RAM(SS_ERAM)) ecs (
        .clk, .mreset, .mode(ecs_mode), .ce, .run(!hold),
        .a(addr), .wr, .wdata(dout), .hit(ecs_hit), .q(ecs_q),
        .on(ecs_on), .full(ecs_full), .pg(ecs_pg), .keys(ecs_keys), .synth(ecs_synth),
        .audio(audio2), .audio_stb(audio2_stb),
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_ecs));

    intv_voice #(.SS_ID(SS_VOICE)) voice (
        .clk, .mreset, .mode(voice_mode), .ce, .run(!hold),
        .a(addr), .wr, .wdata(dout), .hit(v_hit), .q(v_q),
        .rom_addr(ivoice_addr), .rom_q(ivoice_q),
        .dac7(voice_dac7), .level(voice_level), .audio_stb(audio1_stb), .out(v_out),
        .on(voice_on), .busy(voice_busy), .late(voice_late),
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_voice));

    intv_jlp #(.SS_ID(SS_JLP)) jlp (
        .clk, .mreset, .mode(jlp_mode), .sect(jlp_sect), .ce, .run(!hold),
        .a(addr), .rd, .wr, .wdata(dout), .hit(j_hit), .q(j_q),
        .on(jlp_on), .busy(jlp_busy), .eng_busy(jlp_eng_busy),
        .jm_req, .jm_we, .jm_addr, .jm_wdata, .jm_ack, .jm_rdata,
        .nv_addr(jlp_nv_addr), .nv_we(jlp_nv_we), .nv_wdata(jlp_nv_wdata), .nv_q(jlp_nv_q),
        .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_jlp));

    // the two PSGs' samples come together (same reset, same steps); PSG #2 is
    // silent (0) unless the ECS is attached. PSG #2 first at the ECS's own level
    // (the menu's ECS Level: the module has its own knob; 2 = x1, the sound of
    // 0.0.9-0.0.15). While the ECS is attached or on the sum is scaled to 3/4
    // (floor), so the loudest six-channel music measured (WSMLB: PSG #1 + PSG #2
    // up to 43,278) stays under 32,767 at the default level (ECS_NOTES 3); the
    // saturation stays for the rest (up to 73,722 at x2)
    logic [17:0] a2s;
    always_comb
        case (ecs_level)
            3'd0:    a2s = 18'd0;
            3'd1:    a2s = 18'(audio2[15:1]);
            3'd3:    a2s = 18'(audio2) + 18'(audio2[15:1]);
            3'd4:    a2s = {1'b0, audio2, 1'b0};
            default: a2s = 18'(audio2);
        endcase
    wire logic [18:0] mix = 19'(audio1) + 19'(a2s);
    /* verilator lint_off UNUSEDSIGNAL */
    wire logic [20:0] mix3 = 21'(mix) + {1'b0, mix, 1'b0};      // 3 x mix; [1:0] dropped (floor)
    /* verilator lint_on UNUSEDSIGNAL */
    wire logic [18:0] mixs = ecs_on ? mix3[20:2] : mix;
    wire logic [15:0] psgs = mixs[18:15] != 4'd0 ? 16'h7FFF : mixs[15:0];
    // the voice (0 when off) on top, saturated to 16 bits signed
    wire logic signed [17:0] vsum = $signed({2'b00, psgs}) + 18'(v_out);
    assign audio     = vsum > 18'sd32767 ? 16'h7FFF : vsum < -18'sd32768 ? 16'h8000 : vsum[15:0];
    assign audio_stb = audio1_stb;

    intv_ram #(.AW(8), .DW(8), .WORDS(256), .SS_ID(SS_SCR)) scratch (
        .clk, .addr(addr[7:0]), .we(scr_we), .d(dout[7:0]), .q(scr_q),
        .addr_b(8'd0), .q_b(scr_qb),
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_scr));

    intv_ram #(.AW(9), .DW(16), .WORDS(352), .SS_ID(SS_SYS)) sysram (
        .clk, .addr(addr[8:0]), .we(sys_we), .d(dout), .q(sys_q),
        .addr_b(v_sys_addr), .q_b(v_sys_q),
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_sys));

    intv_ram #(.AW(9), .DW(8), .WORDS(512), .SS_ID(SS_GRAM)) gram (
        .clk, .addr(addr[8:0]), .we(gram_we), .d(dout[7:0]), .q(gram_q),
        .addr_b(v_gram_addr), .q_b(v_gram_q),
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_gram));

    assign ss_rdata = ssr_cpu | ssr_bus | ssr_stic | ssr_psg | ssr_scr | ssr_sys | ssr_gram | ssr_ecs | ssr_voice | ssr_jlp;

endmodule

`default_nettype wire
