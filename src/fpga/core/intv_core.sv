// Intellivision core: everything on clk_sys between the Pocket's glue
// (core_top.v) and the machine, so that core_top and the save-state bench
// (sim/tb/tb_savestate.sv) use the same wiring (build step 7).
//
//   intv_media    cartridge, CRC and page table, system ROMs, the SRAM
//   intv_timing   raster, the machine's position and clock enables
//   intv_machine  CP1610, bus fabric, RAMs, STIC, PSG
//   intv_ss_ctl   save, load and menu pause (0x00A0, 0x00A4, 0x00B0) and
//                 the blob at bridge address 0x50000000 (DESIGN.md 4)
//
// The state bus: ss_ctl's ss_addr / ss_we / ss_wdata go to every module's
// state port, their ss_rdata are ORed (each is 0 unless addressed); the
// module ids are intv_ss_pkg's (tools/savestate.py). ss_ctl reaches the
// SRAM (its blob buffer and the cart RAM) through intv_media's aux port.
//
// The machine is held in reset while hold_req is high (the host's reset,
// the menu's Reset, PLL lock) and until the loader is ready; the CPU
// starts on the frame after (intv_bus). While the machine is frozen or
// waits for the raster to come round to its position (live = 0), the
// picture is blanked by pocket_video and the sound decays to silence
// (0) in about 4 ms instead of holding the PSG's last sample.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_core #(
    parameter             CRC_HEX    = "core/tables/cart_crc.hex",
    parameter             LAYOUT_HEX = "core/tables/cart_layouts.hex"
) (
    input  wire logic        clk,             // clk_sys
    input  wire logic        timing_reset,    // power-on: raster and loader
    input  wire logic        hold_req,        // machine reset request

    // data_loader bytes and the data table (intv_media)
    input  wire logic        ld_wr,
    input  wire logic [27:0] ld_addr,
    input  wire logic [7:0]  ld_data,
    input  wire logic        len_valid,
    input  wire logic [31:0] cart_len,
    input  wire logic [1:0]  len_chk,
    input  wire logic [31:0] cfg_len,
    input  wire logic        cfg_inlist,
    output logic [11:0]      slot_st,
    output logic [1:0]       len_st,
    output logic             machine_reset,

    input  wire logic [7:0]  pad_r,
    input  wire logic [7:0]  pad_l,

    // the ECS (build step 9): the menu's override (0 Auto, 1 On, 2 Off; taken
    // at the next machine reset), the keyboard from intv_input
    input  wire logic [1:0]  ecs_override,
    input  wire logic [63:0] ecs_keys,
    input  wire logic        ecs_synth,
    output logic             ecs_full,        // the ECS fully on, mode on (intv_input's key routing)
    // the Intellivoice (build step 10): the menu's override (0 Auto, 1 On, 2 Off; taken at the next
    // machine reset), its sound (7-bit DAC or clean) and level
    input  wire logic [1:0]  voice_override,
    input  wire logic        voice_dac7,
    input  wire logic [2:0]  voice_level,
    output logic             voice_on,
    // the ECS's own volume (the module has its own knob): PSG #2 only, 0 off, 1-4: x 1/2, 1, 3/2, 2
    input  wire logic [2:0]  ecs_level,

    // raster and picture
    output logic             ce_pix,
    output logic [8:0]       hcnt,
    output logic [8:0]       vcnt,
    output logic [8:0]       vline,
    output logic             live,
    output logic [3:0]       colour,
    output logic [15:0]      audio,

    // APF save states (clk_74a)
    input  wire logic        clk_74a,
    input  wire logic [31:0] bridge_addr,
    input  wire logic        bridge_rd,
    input  wire logic        bridge_wr,
    input  wire logic [31:0] bridge_wr_data,
    output logic      [31:0] ss_bridge_rd_data,
    input  wire logic        savestate_start,
    output logic             savestate_start_ack,
    output logic             savestate_start_busy,
    output logic             savestate_start_ok,
    output logic             savestate_start_err,
    input  wire logic        savestate_load,
    output logic             savestate_load_ack,
    output logic             savestate_load_busy,
    output logic             savestate_load_ok,
    output logic             savestate_load_err,
    input  wire logic        osnotify_inmenu,
    input  wire logic        pause_en,        // "Pause in menu"

    // SRAM pins
    output logic [16:0]      sram_a,
    output logic [15:0]      sram_dq_out,
    output logic             sram_dq_oe,
    input  wire logic [15:0] sram_dq_in,
    output logic             sram_oe_n,
    output logic             sram_we_n,
    output logic             sram_ub_n,
    output logic             sram_lb_n
);

    import intv_ss_pkg::*;

    logic        run, frozen, ss_en, ss_we;
    logic [15:0] ss_addr;
    logic [31:0] ss_wdata, ssr_media, ssr_timing, ssr_machine;
    wire  logic [31:0] ss_rdata = ssr_media | ssr_timing | ssr_machine;

    logic        cart_ready, cart_busy, cart_hit;
    logic [5:0]  cart_err;
    logic [7:0]  cart_fmt_err;
    logic [31:0] cart_crc, cart_cfg_crc;
    logic        cart_noss;
    logic [63:0] pg_sel;
    logic        ecs_on, ecs_rom_ok;
    logic [11:0] ecs_pg;
    logic [1:0]  ecs_auto, ecs_mode;
    // the mode intv_ecs takes at machine reset: the menu's override or the Auto rule
    assign ecs_mode = ecs_override == 2'd1 ? 2'd1 : ecs_override == 2'd2 ? 2'd0 : ecs_auto;
    logic [16:0] cart_words;
    logic [7:0]  cart_layout, cart_flags;
    // the Intellivoice at machine reset: On, or Auto and the cartridge's flags say so (the CRC
    // table, a CFG's voice var, a .rom's tag: intv_loader FLAG_VOICE); never without ivoice.bin
    // (data slot 5 loaded with its 2,048 bytes)
    logic        voice_mode, voice_busy;
    /* verilator lint_off UNUSEDSIGNAL */
    logic        voice_late;
    /* verilator lint_on UNUSEDSIGNAL */
    logic [10:0] ivoice_addr;
    wire  logic  ivoice_ok = slot_st[11:10] == 2'd2;
    logic        voice_auto;                     // intv_media: the flag and the ROM
    assign voice_mode = voice_override == 2'd1 ? ivoice_ok : voice_override == 2'd0 && voice_auto;
    logic        cbus_ack, cbus_hit, cbus_paged, cbus_req, cbus_we;
    logic [15:0] cbus_addr, cbus_wdata, cbus_rdata;
    logic [3:0]  cbus_attr;
    logic        aux_req, aux_we, aux_ack;
    // the JLP (build step 11)
    logic [1:0]  jlp_mode;
    logic [4:0]  jlp_sect;
    logic        jlp_on, jlp_busy, jlp_eng_busy, jm_req, jm_we, jm_ack;
    logic [16:0] jm_addr;
    logic [15:0] jm_wdata, jm_rdata;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [15:0] jlp_nv_q;                 // the nonvolatile slot (next pass)
    /* verilator lint_on UNUSEDSIGNAL */
    logic [16:0] aux_addr;
    logic [15:0] aux_wdata, aux_rdata;
    logic [11:0] exec_addr;
    logic [10:0] grom_addr, vgrom_addr;
    logic [9:0]  exec_q;
    logic [7:0]  grom_q, vgrom_q;
    logic [7:0]  ivoice_q;
    /* verilator lint_off UNUSEDSIGNAL */
    logic        m_audio_stb;
    logic [2:0]  m_phase;
    logic [15:0] m_dout, m_din, m_addr;
    /* verilator lint_on UNUSEDSIGNAL */

    // CRC32 (zlib) of the EXEC and GROM slots as they load (slots 2 and 3,
    // byte offsets from 0; the loader's byte strobes): with the cartridge's,
    // they tie a saved state to the ROMs it ran with (intv_ss_ctl)
    function automatic logic [31:0] crc_byte(input logic [31:0] c, input logic [7:0] d);
        logic [31:0] x;
        x = c ^ {24'd0, d};
        for (int k = 0; k < 8; k++)
            x = x[0] ? (x >> 1) ^ 32'hEDB88320 : x >> 1;
        return x;
    endfunction
    logic [31:0] ex_c = 32'hFFFFFFFF, gr_c = 32'hFFFFFFFF, es_c = 32'hFFFFFFFF;
    always_ff @(posedge clk)
        if (ld_wr) begin
            if (ld_addr[27:24] == 4'd4)
                es_c <= crc_byte(ld_addr[23:0] == 24'd0 ? 32'hFFFFFFFF : es_c, ld_data);
            if (ld_addr[27:24] == 4'd2)
                ex_c <= crc_byte(ld_addr[23:0] == 24'd0 ? 32'hFFFFFFFF : ex_c, ld_data);
            if (ld_addr[27:24] == 4'd3)
                gr_c <= crc_byte(ld_addr[23:0] == 24'd0 ? 32'hFFFFFFFF : gr_c, ld_data);
        end

    initial machine_reset = 1'b1;
    always_ff @(posedge clk)
        machine_reset <= hold_req | ~cart_ready;

    intv_media #(.CRC_HEX(CRC_HEX), .LAYOUT_HEX(LAYOUT_HEX), .SS_ID(SS_CART)) media (
        .clk(clk), .reset(timing_reset), .mreset(machine_reset),
        .ld_wr(ld_wr), .ld_addr(ld_addr), .ld_data(ld_data),
        .len_valid(len_valid), .cart_len(cart_len), .len_chk(len_chk),
        .cfg_len(cfg_len), .cfg_inlist(cfg_inlist),
        .bus_req(cbus_req), .bus_we(cbus_we), .bus_addr(cbus_addr), .bus_wdata(cbus_wdata),
        .bus_ack(cbus_ack), .bus_rdata(cbus_rdata), .bus_hit(cbus_hit), .bus_attr(cbus_attr),
        .bus_paged(cbus_paged), .pg_rst(64'd0), .pg_sel(pg_sel),
        .ecs_on(ecs_on), .ecs_pg(ecs_pg), .ecs_auto(ecs_auto), .ecs_rom_ok(ecs_rom_ok), .voice_auto(voice_auto),
        .jlp_mode(jlp_mode), .jlp_sect(jlp_sect), .jlp_on(jlp_on), .jlp_busy(jlp_busy),
        .jm_req(jm_req), .jm_we(jm_we), .jm_addr(jm_addr), .jm_wdata(jm_wdata), .jm_ack(jm_ack), .jm_rdata(jm_rdata),
        .aux_req(aux_req), .aux_we(aux_we), .aux_addr(aux_addr), .aux_wdata(aux_wdata),
        .aux_be(2'b11), .aux_ack(aux_ack), .aux_rdata(aux_rdata),
        .exec_addr(exec_addr), .exec_q(exec_q), .grom_addr(grom_addr), .grom_q(grom_q),
        .vgrom_addr(vgrom_addr), .vgrom_q(vgrom_q), .ivoice_addr(ivoice_addr), .ivoice_q(ivoice_q),
        .ready(cart_ready), .busy(cart_busy), .err(cart_err), .fmt_err(cart_fmt_err), .len_st(len_st),
        .slot_st(slot_st),
        .crc(cart_crc), .words(cart_words), .layout(cart_layout), .flags(cart_flags), .hit(cart_hit),
        .cfg_crc(cart_cfg_crc), .noss(cart_noss),
        .ss_addr(ss_addr), .ss_we(ss_we), .ss_wdata(ss_wdata), .ss_rdata(ssr_media),
        .sram_a(sram_a), .sram_dq_out(sram_dq_out), .sram_dq_oe(sram_dq_oe),
        .sram_dq_in(sram_dq_in), .sram_oe_n(sram_oe_n), .sram_we_n(sram_we_n),
        .sram_ub_n(sram_ub_n), .sram_lb_n(sram_lb_n));

    logic ce_stic, ce_psg, ce_cpu;
    /* verilator lint_off UNUSEDSIGNAL */
    logic unused_ce_psg;
    /* verilator lint_on UNUSEDSIGNAL */
    assign unused_ce_psg = ce_psg;

    intv_timing #(.SS_ID(SS_TIMING)) timing (
        .clk(clk), .reset(timing_reset), .run(run),
        .ce_pix(ce_pix), .hcnt(hcnt), .vcnt(vcnt), .vline(vline),
        .live(live), .ce_stic(ce_stic), .ce_psg(ce_psg), .ce_cpu(ce_cpu),
        .ss_addr(ss_addr), .ss_we(ss_we), .ss_wdata(ss_wdata), .ss_rdata(ssr_timing));

    logic        m_fetch, m_hold, m_halted;
    logic [15:0] psg_audio;

    intv_machine #(
        .SS_CPU(SS_CPU), .SS_BUS(SS_BUS), .SS_STIC(SS_STIC), .SS_PSG(SS_PSG),
        .SS_SCR(SS_SCRATCH), .SS_SYS(SS_SYSRAM), .SS_GRAM(SS_GRAM), .SS_ROW(SS_ROW),
        .SS_LINE(SS_LINE), .SS_ECS(SS_ECS), .SS_PSG2(SS_PSG2), .SS_ERAM(SS_ECSRAM), .SS_VOICE(SS_VOICE),
        .SS_JLP(SS_JLP)
    ) machine (
        .clk(clk), .mreset(machine_reset), .ce(ce_cpu), .ce_pix(ce_stic), .live(live),
        .hcnt(hcnt), .vcnt(vcnt),
        .cfg_hlt_imm(1'b0), .cfg_sdbd_r6_mame(1'b0), .busrq_en(1'b1),
        .pad_r(pad_r), .pad_l(pad_l),
        .ecs_mode(ecs_mode), .ecs_keys(ecs_keys), .ecs_synth(ecs_synth), .ecs_on(ecs_on), .ecs_full(ecs_full), .ecs_pg(ecs_pg),
        .voice_mode(voice_mode), .voice_dac7(voice_dac7), .voice_level(voice_level), .voice_on(voice_on), .ecs_level(ecs_level),
        .voice_busy(voice_busy), .voice_late(voice_late), .ivoice_addr(ivoice_addr), .ivoice_q(ivoice_q),
        .jlp_mode(jlp_mode), .jlp_sect(jlp_sect), .jlp_on(jlp_on), .jlp_busy(jlp_busy), .jlp_eng_busy(jlp_eng_busy),
        .jm_req(jm_req), .jm_we(jm_we), .jm_addr(jm_addr), .jm_wdata(jm_wdata), .jm_ack(jm_ack), .jm_rdata(jm_rdata),
        .jlp_nv_addr(14'd0), .jlp_nv_we(1'b0), .jlp_nv_wdata(16'd0), .jlp_nv_q(jlp_nv_q),
        .cart_req(cbus_req), .cart_we(cbus_we), .cart_addr(cbus_addr), .cart_wdata(cbus_wdata),
        .cart_ack(cbus_ack), .cart_rdata(cbus_rdata), .cart_hit(cbus_hit),
        .exec_addr(exec_addr), .exec_q(exec_q), .grom_addr(grom_addr), .grom_q(grom_q),
        .vgrom_addr(vgrom_addr), .vgrom_q(vgrom_q),
        .colour(colour), .audio(psg_audio), .audio_stb(m_audio_stb),
        .phase(m_phase), .dout(m_dout), .din(m_din), .addr(m_addr),
        .fetch(m_fetch), .hold(m_hold), .halted(m_halted),
        .ss_en(ss_en), .ss_addr(ss_addr), .ss_we(ss_we), .ss_wdata(ss_wdata),
        .ss_rdata(ssr_machine));

    intv_ss_ctl ssc (
        .clk_74a(clk_74a), .bridge_addr(bridge_addr), .bridge_rd(bridge_rd),
        .bridge_wr(bridge_wr), .bridge_wr_data(bridge_wr_data),
        .bridge_rd_data(ss_bridge_rd_data),
        .savestate_start(savestate_start), .savestate_start_ack(savestate_start_ack),
        .savestate_start_busy(savestate_start_busy), .savestate_start_ok(savestate_start_ok),
        .savestate_start_err(savestate_start_err),
        .savestate_load(savestate_load), .savestate_load_ack(savestate_load_ack),
        .savestate_load_busy(savestate_load_busy), .savestate_load_ok(savestate_load_ok),
        .savestate_load_err(savestate_load_err),
        .osnotify_inmenu(osnotify_inmenu), .pause_en(pause_en),
        .clk(clk), .mreset(machine_reset), .cart_ready(cart_ready), .live(live), .vcnt(vcnt),
        .ce_cpu(ce_cpu),
        .cpu_fetch(m_fetch), .cpu_halted(m_halted), .cpu_hold(m_hold),
        .cart_crc(cart_crc), .cart_words(cart_words), .cfg_crc(cart_cfg_crc), .cart_noss(cart_noss),
        .exec_crc(~ex_c), .grom_crc(~gr_c),
        .ecs_flag(ecs_on), .ecs_crc(ecs_on ? ~es_c : 32'd0), .voice_flag(voice_on), .voice_busy(voice_busy || jlp_eng_busy),
        .run(run), .frozen(frozen), .ss_en(ss_en), .ss_addr(ss_addr), .ss_we(ss_we),
        .ss_wdata(ss_wdata), .ss_rdata(ss_rdata),
        .aux_req(aux_req), .aux_we(aux_we), .aux_addr(aux_addr), .aux_wdata(aux_wdata),
        .aux_ack(aux_ack), .aux_rdata(aux_rdata));

    // sound: the machine's while it runs; otherwise toward 0 by 1/16 (and 1)
    // every 1,024 clk_sys (42 kHz), from full scale in about 4 ms (signed:
    // the voice can make it negative, step 10)
    logic [9:0] dk = 10'd0;
    initial audio = 16'd0;
    always_ff @(posedge clk) begin
        dk <= dk + 10'd1;
        if (live)
            audio <= psg_audio;
        else if (dk == 10'd0 && audio != 16'd0)
            audio <= audio[15] ? audio - 16'($signed(audio) >>> 4) + 16'd1 : audio - (audio >> 4) - 16'd1;
    end

    /* verilator lint_off UNUSEDSIGNAL */
    wire unused = cart_busy | cart_hit | (|cart_err) | (|cart_fmt_err) | (|cart_layout) | (|cart_flags)
                | (|cbus_attr) | cbus_paged | (|pg_sel) | frozen | ecs_rom_ok;
    /* verilator lint_on UNUSEDSIGNAL */

endmodule

`default_nettype wire
