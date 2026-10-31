//
// Intellivision for Analogue Pocket - APF top level
//
// Instantiated by the real top level, apf_top. The port list and the APF
// plumbing (bridge, host commands, data table, tie-offs) come from
// Analogue's core template, by way of openFPGA-7800's core_top.v; the rest
// is this project's (MIT).
//
// Step 1 of DESIGN.md 9: the Pocket skeleton. PLL, the master timing with
// its clock enables (intv_timing), the video windows and the Pocket video
// port (pocket_video), a test pattern in the planned palette
// (test_pattern, intv_palette), silent audio, and the save-state commands
// answered "not supported" until step 7.
// Step 2: the data slots of DESIGN.md 5.6 through the data loader into
// intv_media (cartridge into the SRAM with its CRC32, CRC table and page
// table; EXEC, GROM and Intellivoice ROMs into block RAM; ECS ROM into the
// SRAM), with the cartridge length from the data table (apf_datatable).
// Step 3: the machine (intv_machine: CP1610, bus fabric, scratchpad,
// System RAM, GRAM, STIC and PSG register stubs) runs the EXEC from the
// first frame after the loader is ready.
// Step 4: the STIC (backgrounds, BUSRQ) draws the picture once the machine
// runs; the test pattern shows while it is held (loading, a required slot
// missing or refused). The step-3 status register at 0x60000000 is gone.
// Step 6: the PSG (intv_psg) gives the sound, 48 kHz, on both channels.
// intv_input turns the Pocket's controllers and USB keyboard into
// the two hand controllers on the PSG's ports; settings Keypad Mode (0x208)
// and Swap Controllers (0x20C).
// Step 7: save states (DESIGN.md 4; docs/SAVESTATE.md). The clk_sys side
// (intv_media, intv_timing, intv_machine and the save-state controller
// intv_ss_ctl) is in intv_core, which the bench sim/tb/tb_savestate.sv
// uses too. 0x00A0 / 0x00A4 save and load the 150 KiB blob at 0x50000000,
// 0x00B0 freezes the machine while the menu is open (setting Pause in
// Menu, 0x210), sleep is supported.
//

`default_nettype none

module core_top (

//
// physical connections
//

///////////////////////////////////////////////////
// clock inputs 74.25mhz. not phase aligned, so treat these domains as asynchronous

input   wire            clk_74a, // mainclk1
input   wire            clk_74b, // mainclk1 

///////////////////////////////////////////////////
// cartridge interface
// switches between 3.3v and 5v mechanically
// output enable for multibit translators controlled by pic32

// GBA AD[15:8]
inout   wire    [7:0]   cart_tran_bank2,
output  wire            cart_tran_bank2_dir,

// GBA AD[7:0]
inout   wire    [7:0]   cart_tran_bank3,
output  wire            cart_tran_bank3_dir,

// GBA A[23:16]
inout   wire    [7:0]   cart_tran_bank1,
output  wire            cart_tran_bank1_dir,

// GBA [7] PHI#
// GBA [6] WR#
// GBA [5] RD#
// GBA [4] CS1#/CS#
//     [3:0] unwired
inout   wire    [7:4]   cart_tran_bank0,
output  wire            cart_tran_bank0_dir,

// GBA CS2#/RES#
inout   wire            cart_tran_pin30,
output  wire            cart_tran_pin30_dir,
// when GBC cart is inserted, this signal when low or weak will pull GBC /RES low with a special circuit
// the goal is that when unconfigured, the FPGA weak pullups won't interfere.
// thus, if GBC cart is inserted, FPGA must drive this high in order to let the level translators
// and general IO drive this pin.
output  wire            cart_pin30_pwroff_reset,

// GBA IRQ/DRQ
inout   wire            cart_tran_pin31,
output  wire            cart_tran_pin31_dir,

// infrared
input   wire            port_ir_rx,
output  wire            port_ir_tx,
output  wire            port_ir_rx_disable, 

// GBA link port
inout   wire            port_tran_si,
output  wire            port_tran_si_dir,
inout   wire            port_tran_so,
output  wire            port_tran_so_dir,
inout   wire            port_tran_sck,
output  wire            port_tran_sck_dir,
inout   wire            port_tran_sd,
output  wire            port_tran_sd_dir,
 
///////////////////////////////////////////////////
// cellular psram 0 and 1, two chips (64mbit x2 dual die per chip)

output  wire    [21:16] cram0_a,
inout   wire    [15:0]  cram0_dq,
input   wire            cram0_wait,
output  wire            cram0_clk,
output  wire            cram0_adv_n,
output  wire            cram0_cre,
output  wire            cram0_ce0_n,
output  wire            cram0_ce1_n,
output  wire            cram0_oe_n,
output  wire            cram0_we_n,
output  wire            cram0_ub_n,
output  wire            cram0_lb_n,

output  wire    [21:16] cram1_a,
inout   wire    [15:0]  cram1_dq,
input   wire            cram1_wait,
output  wire            cram1_clk,
output  wire            cram1_adv_n,
output  wire            cram1_cre,
output  wire            cram1_ce0_n,
output  wire            cram1_ce1_n,
output  wire            cram1_oe_n,
output  wire            cram1_we_n,
output  wire            cram1_ub_n,
output  wire            cram1_lb_n,

///////////////////////////////////////////////////
// sdram, 512mbit 16bit

output  wire    [12:0]  dram_a,
output  wire    [1:0]   dram_ba,
inout   wire    [15:0]  dram_dq,
output  wire    [1:0]   dram_dqm,
output  wire            dram_clk,
output  wire            dram_cke,
output  wire            dram_ras_n,
output  wire            dram_cas_n,
output  wire            dram_we_n,

///////////////////////////////////////////////////
// sram, AS6C2016-55: 2 Mbit as 128K x 16, 55 ns

output  wire    [16:0]  sram_a,
inout   wire    [15:0]  sram_dq,
output  wire            sram_oe_n,
output  wire            sram_we_n,
output  wire            sram_ub_n,
output  wire            sram_lb_n,

///////////////////////////////////////////////////
// vblank driven by dock for sync in a certain mode

input   wire            vblank,

///////////////////////////////////////////////////
// i/o to 6515D breakout usb uart

output  wire            dbg_tx,
input   wire            dbg_rx,

///////////////////////////////////////////////////
// i/o pads near jtag connector user can solder to

output  wire            user1,
input   wire            user2,

///////////////////////////////////////////////////
// RFU internal i2c bus 

inout   wire            aux_sda,
output  wire            aux_scl,

///////////////////////////////////////////////////
// RFU, do not use
output  wire            vpll_feed,


//
// logical connections
//

///////////////////////////////////////////////////
// video, audio output to scaler
output  wire    [23:0]  video_rgb,
output  wire            video_rgb_clock,
output  wire            video_rgb_clock_90,
output  wire            video_de,
output  wire            video_skip,
output  wire            video_vs,
output  wire            video_hs,
    
output  wire            audio_mclk,
input   wire            audio_adc,
output  wire            audio_dac,
output  wire            audio_lrck,

///////////////////////////////////////////////////
// bridge bus connection
// synchronous to clk_74a
output  wire            bridge_endian_little,
input   wire    [31:0]  bridge_addr,
input   wire            bridge_rd,
output  reg     [31:0]  bridge_rd_data,
input   wire            bridge_wr,
input   wire    [31:0]  bridge_wr_data,

///////////////////////////////////////////////////
// controller data
// 
// key bitmap:
//   [0]    dpad_up
//   [1]    dpad_down
//   [2]    dpad_left
//   [3]    dpad_right
//   [4]    face_a
//   [5]    face_b
//   [6]    face_x
//   [7]    face_y
//   [8]    trig_l1
//   [9]    trig_r1
//   [10]   trig_l2
//   [11]   trig_r2
//   [12]   trig_l3
//   [13]   trig_r3
//   [14]   face_select
//   [15]   face_start
//   [31:28] type
// joy values - unsigned
//   [ 7: 0] lstick_x
//   [15: 8] lstick_y
//   [23:16] rstick_x
//   [31:24] rstick_y
// trigger values - unsigned
//   [ 7: 0] ltrig
//   [15: 8] rtrig
//
input   wire    [31:0]  cont1_key,
input   wire    [31:0]  cont2_key,
input   wire    [31:0]  cont3_key,
input   wire    [31:0]  cont4_key,
input   wire    [31:0]  cont1_joy,
input   wire    [31:0]  cont2_joy,
input   wire    [31:0]  cont3_joy,
input   wire    [31:0]  cont4_joy,
input   wire    [15:0]  cont1_trig,
input   wire    [15:0]  cont2_trig,
input   wire    [15:0]  cont3_trig,
input   wire    [15:0]  cont4_trig
    
);

// not using the IR port, so turn off both the LED, and
// disable the receive circuit to save power
assign port_ir_tx = 0;
assign port_ir_rx_disable = 1;

// bridge endianness
assign bridge_endian_little = 0;

// cart is unused, so set all level translators accordingly
// directions are 0:IN, 1:OUT
assign cart_tran_bank3 = 8'hzz;
assign cart_tran_bank3_dir = 1'b0;
assign cart_tran_bank2 = 8'hzz;
assign cart_tran_bank2_dir = 1'b0;
assign cart_tran_bank1 = 8'hzz;
assign cart_tran_bank1_dir = 1'b0;
assign cart_tran_bank0 = 4'hf;
assign cart_tran_bank0_dir = 1'b1;
assign cart_tran_pin30 = 1'b0;      // reset or cs2, we let the hw control it by itself
assign cart_tran_pin30_dir = 1'bz;
assign cart_pin30_pwroff_reset = 1'b0;  // hardware can control this
assign cart_tran_pin31 = 1'bz;      // input
assign cart_tran_pin31_dir = 1'b0;  // input

// link port is unused, set to input only to be safe
// each bit may be bidirectional in some applications
assign port_tran_so = 1'bz;
assign port_tran_so_dir = 1'b0;     // SO is output only
assign port_tran_si = 1'bz;
assign port_tran_si_dir = 1'b0;     // SI is input only
assign port_tran_sck = 1'bz;
assign port_tran_sck_dir = 1'b0;    // clock direction can change
assign port_tran_sd = 1'bz;
assign port_tran_sd_dir = 1'b0;     // SD is input and not used

// tie off the rest of the pins we are not using
assign cram0_a = 'h0;
assign cram0_dq = {16{1'bZ}};
assign cram0_clk = 0;
assign cram0_adv_n = 1;
assign cram0_cre = 0;
assign cram0_ce0_n = 1;
assign cram0_ce1_n = 1;
assign cram0_oe_n = 1;
assign cram0_we_n = 1;
assign cram0_ub_n = 1;
assign cram0_lb_n = 1;

assign cram1_a = 'h0;
assign cram1_dq = {16{1'bZ}};
assign cram1_clk = 0;
assign cram1_adv_n = 1;
assign cram1_cre = 0;
assign cram1_ce0_n = 1;
assign cram1_ce1_n = 1;
assign cram1_oe_n = 1;
assign cram1_we_n = 1;
assign cram1_ub_n = 1;
assign cram1_lb_n = 1;

// SDRAM: not used by this core (DESIGN.md 5.1: cartridge ROM and RAM go in
// the SRAM, which needs no SDRAM controller).
assign dram_a = 'h0;
assign dram_ba = 'h0;
assign dram_dq = {16{1'bZ}};
assign dram_dqm = 'h0;
assign dram_clk = 'h0;
assign dram_cke = 'h0;
assign dram_we_n = 'h1;
assign dram_ras_n = 'h1;
assign dram_cas_n = 'h1;

// SRAM: the cartridge's memory (DESIGN.md 5.1), driven by intv_media's
// controller below; DQ is driven only during its writes.
    wire    [15:0]  sram_dq_out;
    wire            sram_dq_oe;
assign sram_dq = sram_dq_oe ? sram_dq_out : {16{1'bZ}};

assign dbg_tx = 1'bZ;
assign user1 = 1'bZ;
assign aux_scl = 1'bZ;
assign vpll_feed = 1'bZ;


////////////////////////////////////////////////////////////////////////////////
// Clocks (DESIGN.md 2.3)
//
// One PLL from clk_74a, NTSC plan (pll/pll_core.v; docs/DEVELOPING.md,
// "Regenerate the PLL"): VCO 74.25 x (11 + 2449196227 / 2^32) =
// 859.0909 MHz, and
//   outclk_0  clk_sys     VCO / 20  = 42.954545 MHz = 12 x the 3.579545 MHz
//                         master; all machine logic, with clock enables
//   outclk_1  clk_mem     VCO / 10  = 85.909091 MHz, for the memories (not
//                         used yet)
//   outclk_2  clk_vid     VCO / 240 = 3.579545 MHz, the pixel clock
//   outclk_3  clk_vid_90  clk_vid at 90 degrees, the Pocket's sample clock
// All come from one VCO with their rising edges on the same VCO edge, so
// they are one synchronous group (core_constraints.sdc). PAL (4.0 MHz
// master, VCO 960 MHz: another integer M) needs a runtime retune; it is
// step 12 (DESIGN.md decision 5).
////////////////////////////////////////////////////////////////////////////////

    wire    clk_sys;
    wire    clk_mem;
    wire    clk_vid;
    wire    clk_vid_90;
    wire    pll_core_locked;
    wire    pll_core_locked_s;

pll_core pll (
    .refclk     ( clk_74a ),
    .rst        ( 1'b0 ),
    .outclk_0   ( clk_sys ),
    .outclk_1   ( clk_mem ),
    .outclk_2   ( clk_vid ),
    .outclk_3   ( clk_vid_90 ),
    .locked     ( pll_core_locked )
);

synch_3 s01(pll_core_locked, pll_core_locked_s, clk_74a);


////////////////////////////////////////////////////////////////////////////////
// Bridge
//
//   0x00000000  cartridge (data slot 0x100)        \
//   0x01000000  cartridge config (0x101)            |  through the data loader:
//   0x02000000  EXEC (0x102)                        |  bits 27:24 name the slot
//   0x03000000  GROM (0x103)                        |  (intv_media)
//   0x04000000  ECS ROM (0x104)                     |
//   0x05000000  Intellivoice ROM (0x105)           /
//   0x10000000  settings (interact.json)
//   0x20000000  JLP flash (0x106, nonvolatile; step 11)
//   0x50000000  save state blob (step 7; DESIGN.md 4.1)
//   0xF8000000  APF command interface
////////////////////////////////////////////////////////////////////////////////

localparam [15:0] SLOT_CART   = 16'h0100;
localparam [15:0] SLOT_CFG    = 16'h0101;
localparam [15:0] SLOT_EXEC   = 16'h0102;
localparam [15:0] SLOT_GROM   = 16'h0103;
localparam [15:0] SLOT_ECS    = 16'h0104;
localparam [15:0] SLOT_IVOICE = 16'h0105;
localparam [15:0] SLOT_JLP    = 16'h0106;

// Save state (DESIGN.md 4.1, 4.4): the blob's bridge address and its fixed
// size (tools/savestate.py, intv_ss_pkg), served by intv_ss_ctl.
localparam [31:0] SS_ADDR = 32'h50000000;
    wire    [31:0]  ss_bridge_rd_data;     // intv_ss_ctl, held from its last read
    wire    [31:0]  jlp_bridge_rd_data;    // intv_jlp_nv (the JLP flash slot), held likewise
    wire    [4:0]   jlp_sectors;           // clk_sys: the cartridge's JLP flash sectors
localparam [31:0] SS_SIZE = 32'd153600;

// Settings, written by the host from interact.json (clk_74a).
    reg             set_border = 1'b1;      // Border: 1 = show (slot 1), 0 = playfield only (slot 0)
    reg     [1:0]   set_kp_mode = 2'd0;     // Keypad Mode: 0 Layer, 1 Face-button ring, 2 Right stick
    reg             set_swap = 1'b0;        // Swap Controllers: 1 = player 1 on the right controller
    reg             set_pause = 1'b1;       // Pause in Menu: 1 = the machine freezes while the menu is open
    reg     [1:0]   set_ecs = 2'd0;         // ECS: 0 Auto, 1 On, 2 Off (taken at the next reset or load; step 9)
    reg             set_synth = 1'b0;       // ECS Keyboard: 0 computer keyboard, 1 music synthesizer
    reg     [1:0]   set_voice = 2'd0;       // Intellivoice: 0 Auto, 1 On, 2 Off (taken at the next reset or load; step 10)
    reg     [2:0]   set_vlevel = 3'd4;      // Voice level: 0 off, 1-4: x 1/2, 1, 3/2, 2 (2: speech peak near a PSG's)
    reg             set_vdac = 1'b0;        // Voice sound: 0 clean (14 bits), 1 the chip's 7-bit DAC
    reg     [2:0]   set_elevel = 3'd2;      // ECS level: PSG #2 only, 0 off, 1-4: x 1/2, 1, 3/2, 2 (2: as 0.0.9; the ECS has its own knob)
    reg     [7:0]   menu_reset_cnt = 8'd0;

always @(posedge clk_74a) begin
    if (menu_reset_cnt != 0)
        menu_reset_cnt <= menu_reset_cnt - 1'b1;

    if (bridge_wr && bridge_addr[31:24] == 8'h10) begin
        case (bridge_addr[11:0])
            12'h200: menu_reset_cnt <= 8'hFF;
            12'h204: set_border     <= bridge_wr_data[0];
            12'h208: set_kp_mode    <= bridge_wr_data[1:0];
            12'h20C: set_swap       <= bridge_wr_data[0];
            12'h210: set_pause      <= bridge_wr_data[0];
            12'h214: set_ecs        <= bridge_wr_data[1:0];
            12'h218: set_synth      <= bridge_wr_data[0];
            12'h21C: set_voice      <= bridge_wr_data[1:0];
            12'h220: set_vlevel     <= bridge_wr_data[2:0];
            12'h224: set_vdac       <= bridge_wr_data[0];
            12'h228: set_elevel     <= bridge_wr_data[2:0];
            default: ;
        endcase
    end
end

// JLP flash (step 11): the slot's words at 0x20000000 are intv_jlp_nv's (in
// intv_core); its size in the data table is the cartridge's sectors x 1,536
// bytes (apf_datatable), 0 without flash (no file then).

// for bridge write data, we just broadcast it to all bus devices
// for bridge read data, we have to mux it
always @(*) begin
    casex(bridge_addr)
    default: begin
        bridge_rd_data <= 0;
    end
    32'hF8xxxxxx: begin
        bridge_rd_data <= cmd_bridge_rd_data;
    end
    32'h50xxxxxx: begin
        bridge_rd_data <= ss_bridge_rd_data;    // the save-state blob (intv_ss_ctl)
    end
    32'h20xxxxxx: begin
        bridge_rd_data <= jlp_bridge_rd_data;   // the JLP flash slot (intv_jlp_nv)
    end
    32'h60xxxxxx: begin
        bridge_rd_data <= cfg_st_rd_data;       // the CFG fetch's path struct (apf_cfgfetch)
    end
    endcase
end


//
// host/target command handler
//
    wire            reset_n;                // driven by host commands, can be used as core-wide reset
    wire    [31:0]  cmd_bridge_rd_data;

// bridge host commands
// synchronous to clk_74a
    wire            status_boot_done = pll_core_locked_s;
    // setup done at PLL lock, as every core: Ready to run (0x0140) goes out on its rising edge
    // (core_bridge_cmd). The owner's Pocket (2026-10-31) stops with "Core not ready to run" when
    // 0x0140 comes later (0.0.15-0.0.17, 0.0.19), answers it on a first load, and leaves it
    // unanswered on a Core Settings reload (0.0.18's photo). So the CFG fetch waits until
    // core_bridge_cmd is done with it (rtr_ok, apf_datatable): answered, or given up after 5 s
    // (RTR_GIVEUP; rtr_gaveup, test pattern card 18).
    wire            status_setup_done = pll_core_locked_s;
    /* verilator lint_off UNUSEDSIGNAL */
    wire            dt_setup_done;          // apf_datatable's first-fetch flag (diagnostics only)
    /* verilator lint_on UNUSEDSIGNAL */
    // done with Ready to run: core_bridge_cmd's target state leaves WAITRESULT_RTR (14) the first time
    reg             rtr_wait = 1'b0, rtr_ok = 1'b0;
always @(posedge clk_74a) begin
    if (target_state == 4'd14) rtr_wait <= 1'b1;
    else if (rtr_wait) rtr_ok <= 1'b1;
end
    wire            status_running = reset_n; // we are running as soon as reset_n goes high

    wire            dataslot_requestread;
    wire    [15:0]  dataslot_requestread_id;
    wire            dataslot_requestread_ack = 1;
    wire            dataslot_requestread_ok = 1;

    wire            dataslot_requestwrite;
    wire    [15:0]  dataslot_requestwrite_id;
    wire    [31:0]  dataslot_requestwrite_size;
    wire            dataslot_requestwrite_ack = 1;
    wire            dataslot_requestwrite_ok = 1;

    wire            dataslot_update;
    wire    [15:0]  dataslot_update_id;
    wire    [31:0]  dataslot_update_size;

    wire            dataslot_allcomplete;

    wire     [31:0] rtc_epoch_seconds;
    wire     [31:0] rtc_date_bcd;
    wire     [31:0] rtc_time_bcd;
    wire            rtc_valid;

    wire            savestate_supported = 1'b1;
    wire    [31:0]  savestate_addr = SS_ADDR;
    wire    [31:0]  savestate_size = SS_SIZE;
    wire    [31:0]  savestate_maxloadsize = SS_SIZE;

    wire            savestate_start;
    wire            savestate_start_ack;
    wire            savestate_start_busy;
    wire            savestate_start_ok;
    wire            savestate_start_err;

    wire            savestate_load;
    wire            savestate_load_ack;
    wire            savestate_load_busy;
    wire            savestate_load_ok;
    wire            savestate_load_err;

    wire            osnotify_inmenu;

// bridge target commands
// synchronous to clk_74a
// The CFG beside the cartridge (apf_cfgfetch, in apf_datatable) is their only
// user: get filename, open file, data slot read. Its struct RAM (the path,
// flags and size) is at 0x60000000, for the request and the response alike.

    wire            target_dataslot_read;
    wire            target_dataslot_write = 1'b0;
    wire            target_dataslot_getfile;
    wire            target_dataslot_openfile;

    wire            target_dataslot_ack;
    wire            target_dataslot_done;
    wire    [2:0]   target_dataslot_err;

    wire    [15:0]  target_dataslot_id;
    wire    [31:0]  target_dataslot_slotoffset;
    wire    [31:0]  target_dataslot_bridgeaddr;
    wire    [31:0]  target_dataslot_length;

    wire    [31:0]  target_buffer_param_struct = 32'h6000_0000;
    wire    [31:0]  target_buffer_resp_struct  = 32'h6000_0000;
    wire    [31:0]  cfg_st_rd_data;             // the struct RAM, held from its last read
    wire    [2:0]   cfg_fetch_res;
    wire    [2:0]   cfg_fetch_to;               // the command that timed out (load diagnostics)
    wire            cfg_wr_ok;                  // a CFG read is outstanding
    wire            loader_bridge_wr;           // bridge_wr for the data loader (apf_datatable)
    wire            d_ac, d_req, d_upd;
    wire    [1:0]   d_phase;
    wire    [3:0]   target_state;
    wire            rtr_gaveup;             // core_bridge_cmd gave up waiting for Ready to run's ok

// bridge data slot access
// synchronous to clk_74a

    wire    [9:0]   datatable_addr;
    wire            datatable_wren;
    wire    [31:0]  datatable_data;
    wire    [31:0]  datatable_q;

core_bridge_cmd icb (

    .clk                ( clk_74a ),
    .reset_n            ( reset_n ),

    .bridge_endian_little   ( bridge_endian_little ),
    .bridge_addr            ( bridge_addr ),
    .bridge_rd              ( bridge_rd ),
    .bridge_rd_data         ( cmd_bridge_rd_data ),
    .bridge_wr              ( bridge_wr ),
    .bridge_wr_data         ( bridge_wr_data ),

    .status_boot_done       ( status_boot_done ),
    .status_setup_done      ( status_setup_done ),
    .status_running         ( status_running ),

    .dataslot_requestread       ( dataslot_requestread ),
    .dataslot_requestread_id    ( dataslot_requestread_id ),
    .dataslot_requestread_ack   ( dataslot_requestread_ack ),
    .dataslot_requestread_ok    ( dataslot_requestread_ok ),

    .dataslot_requestwrite      ( dataslot_requestwrite ),
    .dataslot_requestwrite_id   ( dataslot_requestwrite_id ),
    .dataslot_requestwrite_size ( dataslot_requestwrite_size ),
    .dataslot_requestwrite_ack  ( dataslot_requestwrite_ack ),
    .dataslot_requestwrite_ok   ( dataslot_requestwrite_ok ),

    .dataslot_update            ( dataslot_update ),
    .dataslot_update_id         ( dataslot_update_id ),
    .dataslot_update_size       ( dataslot_update_size ),

    .dataslot_allcomplete   ( dataslot_allcomplete ),

    .rtc_epoch_seconds      ( rtc_epoch_seconds ),
    .rtc_date_bcd           ( rtc_date_bcd ),
    .rtc_time_bcd           ( rtc_time_bcd ),
    .rtc_valid              ( rtc_valid ),

    .savestate_supported    ( savestate_supported ),
    .savestate_addr         ( savestate_addr ),
    .savestate_size         ( savestate_size ),
    .savestate_maxloadsize  ( savestate_maxloadsize ),

    .savestate_start        ( savestate_start ),
    .savestate_start_ack    ( savestate_start_ack ),
    .savestate_start_busy   ( savestate_start_busy ),
    .savestate_start_ok     ( savestate_start_ok ),
    .savestate_start_err    ( savestate_start_err ),

    .savestate_load         ( savestate_load ),
    .savestate_load_ack     ( savestate_load_ack ),
    .savestate_load_busy    ( savestate_load_busy ),
    .savestate_load_ok      ( savestate_load_ok ),
    .savestate_load_err     ( savestate_load_err ),

    .osnotify_inmenu        ( osnotify_inmenu ),

    .target_dataslot_read       ( target_dataslot_read ),
    .target_dataslot_write      ( target_dataslot_write ),
    .target_dataslot_getfile    ( target_dataslot_getfile ),
    .target_dataslot_openfile   ( target_dataslot_openfile ),

    .target_dataslot_ack        ( target_dataslot_ack ),
    .target_dataslot_done       ( target_dataslot_done ),
    .target_dataslot_err        ( target_dataslot_err ),

    .target_dataslot_id         ( target_dataslot_id ),
    .target_dataslot_slotoffset ( target_dataslot_slotoffset ),
    .target_dataslot_bridgeaddr ( target_dataslot_bridgeaddr ),
    .target_dataslot_length     ( target_dataslot_length ),

    .target_buffer_param_struct ( target_buffer_param_struct ),
    .target_buffer_resp_struct  ( target_buffer_resp_struct ),

    .datatable_addr         ( datatable_addr ),
    .datatable_wren         ( datatable_wren ),
    .datatable_data         ( datatable_data ),
    .datatable_q            ( datatable_q ),
    .target_state           ( target_state ),
    .rtr_gaveup             ( rtr_gaveup )

);

// Data table: word 2 * index + 1 is a slot's size. The Pocket reads it to
// decide how much of a nonvolatile slot to save: the JLP flash slot (index 6)
// is written 0 until step 11 stores flash; its size will then be the game's
// (DESIGN.md 13, item 17). The loader reads the cartridge's size from it,
// once the host has sent "all complete" (apf_datatable.sv).
    wire    [31:0]  cart_len;
    wire    [1:0]   cart_len_chk;
    wire            cart_len_valid;
    wire    [31:0]  cfg_len;
    wire            cfg_inlist;

apf_datatable #(
    .SLOT_ID    ( {16'd0, SLOT_CART} ),
    .CFG_ID     ( {16'd0, SLOT_CFG} ),
    .JLP_IDX    ( 6 )
) dtab (
    .clk        ( clk_74a ),
    .allcomplete( dataslot_allcomplete ),
    .wr_req     ( dataslot_requestwrite ),
    .wr_id      ( dataslot_requestwrite_id ),
    .wr_size    ( dataslot_requestwrite_size ),
    .upd        ( dataslot_update ),
    .upd_id     ( dataslot_update_id ),
    .dt_addr    ( datatable_addr ),
    .dt_wren    ( datatable_wren ),
    .dt_data    ( datatable_data ),
    .dt_q       ( datatable_q ),
    .cart_len   ( cart_len ),
    .len_chk    ( cart_len_chk ),
    .cfg_len    ( cfg_len ),
    .cfg_inlist ( cfg_inlist ),
    .len_valid  ( cart_len_valid ),
    .jlp_sectors( jlp_sectors ),
    .t_read         ( target_dataslot_read ),
    .t_getfile      ( target_dataslot_getfile ),
    .t_openfile     ( target_dataslot_openfile ),
    .t_id           ( target_dataslot_id ),
    .t_offset       ( target_dataslot_slotoffset ),
    .t_bridgeaddr   ( target_dataslot_bridgeaddr ),
    .t_length       ( target_dataslot_length ),
    .t_done         ( target_dataslot_done ),
    .t_err          ( target_dataslot_err ),
    .bridge_addr    ( bridge_addr ),
    .bridge_wr      ( bridge_wr ),
    .bridge_wr_data ( bridge_wr_data ),
    .bridge_rd      ( bridge_rd ),
    .st_rd_data     ( cfg_st_rd_data ),
    .fetch_res      ( cfg_fetch_res ),
    .fetch_code     ( ),
    .fetch_len      ( ),
    .fetch_to       ( cfg_fetch_to ),
    .cfg_wr_ok      ( cfg_wr_ok ),
    .d_ac           ( d_ac ),
    .d_req          ( d_req ),
    .d_upd          ( d_upd ),
    .d_phase        ( d_phase ),
    .setup_done     ( dt_setup_done ),
    .rtr_ok         ( rtr_ok ),
    .loader_wr      ( loader_bridge_wr )      // the CFG slot's writes only for a fetch read
);


////////////////////////////////////////////////////////////////////////////////
// Loading
//
// agg23's data loader (pocket_utils/, MIT) turns the bridge's 32-bit writes
// below 0x10000000 into bytes on clk_sys, one write strobe per byte;
// intv_media (in intv_core) takes them (DESIGN.md 5; the CFG slot goes to
// the loader's CFG parser, build step 8). Bridge accesses at 0x50000000 are the save
// state's (intv_ss_ctl), not the loader's.
////////////////////////////////////////////////////////////////////////////////

    wire            ioctl_wr;
    wire    [27:0]  ioctl_addr;
    wire    [7:0]   ioctl_dout;

data_loader #(
    .ADDRESS_MASK_UPPER_4       ( 4'h0 ),
    .ADDRESS_SIZE               ( 28 ),
    .WRITE_MEM_CLOCK_DELAY      ( 4 ),
    .WRITE_MEM_EN_CYCLE_LENGTH  ( 1 ),
    .OUTPUT_WORD_SIZE           ( 1 )
) loader (
    .clk_74a                ( clk_74a ),
    .clk_memory             ( clk_sys ),
    .bridge_wr              ( loader_bridge_wr ),
    .bridge_endian_little   ( bridge_endian_little ),
    .bridge_addr            ( bridge_addr ),
    .bridge_wr_data         ( bridge_wr_data ),
    .write_en               ( ioctl_wr ),
    .write_addr             ( ioctl_addr ),
    .write_data             ( ioctl_dout )
);

// Into clk_sys: PLL lock, the host's reset, the menu's Reset and the
// settings (they change rarely, only from the menu: two flip-flops a bit).
    reg     [2:0]   lock_s = 3'd0, rst_s = 3'd0, mrst_s = 3'd0;
    reg     [1:0]   border_s = 2'b11;
    // the voice's settings (they change rarely, from the menu: two flip-flops a bit; the
    // override is taken at a machine reset, the level and DAC choice any time)
    reg     [1:0]   voice_s0 = 2'd0, voice_s1 = 2'd0;
    reg     [2:0]   vlevel_s0 = 3'd4, vlevel_s1 = 3'd4;
    reg     [2:0]   elevel_s0 = 3'd2, elevel_s1 = 3'd2;     // the ECS level (any time)
    reg     [1:0]   vdac_s = 2'b00;
    reg             timing_reset = 1'b1;

always @(posedge clk_sys) begin
    lock_s   <= {lock_s[1:0], pll_core_locked};
    rst_s    <= {rst_s[1:0],  reset_n};
    mrst_s   <= {mrst_s[1:0], menu_reset_cnt != 0};
    border_s <= {border_s[0], set_border};
    voice_s0 <= set_voice;  voice_s1 <= voice_s0;
    vlevel_s0 <= set_vlevel; vlevel_s1 <= vlevel_s0;
    elevel_s0 <= set_elevel; elevel_s1 <= elevel_s0;
    vdac_s   <= {vdac_s[0], set_vdac};
    // The picture runs from PLL lock, through loading and resets, so the
    // Pocket always has a stable frame.
    timing_reset  <= ~lock_s[2];
end

////////////////////////////////////////////////////////////////////////////////
// Input (step 6): the Pocket's controllers and keyboard as the two hand
// controllers on the PSG's ports (DESIGN.md 7). intv_input takes the
// clk_74a words and the settings into clk_sys itself, as one word with a
// toggle handshake (constraints in core_constraints.sdc).
////////////////////////////////////////////////////////////////////////////////

    wire    [7:0]   pad_r, pad_l;
    wire    [63:0]  ecs_keys;
    wire            ecs_synth, ecs_full;
    wire    [1:0]   ecs_ovr;

intv_input input_map (
    .clk_74a    ( clk_74a ),
    .clk        ( clk_sys ),
    .cont1_key  ( cont1_key ),
    .cont1_joy  ( cont1_joy ),
    .cont2_key  ( cont2_key ),
    .cont2_joy  ( cont2_joy ),
    .cont3_key  ( cont3_key ),
    .cont3_joy  ( cont3_joy ),
    .cont3_trig ( cont3_trig ),
    .kp_mode    ( set_kp_mode ),
    .swap       ( set_swap ),
    .ecs_ovr_74 ( set_ecs ),
    .synth_74   ( set_synth ),
    .ecs_full   ( ecs_full ),
    .pad_r      ( pad_r ),
    .pad_l      ( pad_l ),
    .ecs_keys   ( ecs_keys ),
    .ecs_synth  ( ecs_synth ),
    .ecs_ovr    ( ecs_ovr )
);

////////////////////////////////////////////////////////////////////////////////
// The machine and its save states (steps 3-7): intv_core (media, timing,
// machine, intv_ss_ctl). The machine is held while the host holds the core
// in reset (loading), for the menu's Reset, and until the loader is ready
// (it finishes about 3 ms after the host's "all complete", which comes
// before its reset exit; intv_core adds that). The CPU then starts on the
// next frame (intv_bus). The save-state ports are clk_74a (core_bridge_cmd)
// and cross inside intv_ss_ctl.
////////////////////////////////////////////////////////////////////////////////

    wire            machine_reset;
    wire    [11:0]  slot_st;
    wire    [1:0]   cart_len_st;
    wire            ce_pix, live;
    wire    [8:0]   hcnt, vcnt, vline;
    wire    [3:0]   stic_colour;
    wire    [15:0]  psg_audio;

intv_core machine_side (
    .clk                ( clk_sys ),
    .timing_reset       ( timing_reset ),
    .hold_req           ( ~lock_s[2] | ~rst_s[2] | mrst_s[2] ),
    .ld_wr              ( ioctl_wr ),
    .ld_addr            ( ioctl_addr ),
    .ld_data            ( ioctl_dout ),
    .len_valid          ( cart_len_valid ),
    .cart_len           ( cart_len ),
    .len_chk            ( cart_len_chk ),
    .cfg_len            ( cfg_len ),
    .cfg_inlist         ( cfg_inlist ),
    .slot_st            ( slot_st ),
    .len_st             ( cart_len_st ),
    .machine_reset      ( machine_reset ),
    .pad_r              ( pad_r ),
    .pad_l              ( pad_l ),
    .ecs_override       ( ecs_ovr ),
    .ecs_keys           ( ecs_keys ),
    .ecs_synth          ( ecs_synth ),
    .ecs_full           ( ecs_full ),
    .voice_override     ( voice_s1 ),
    .voice_dac7         ( vdac_s[1] ),
    .voice_level        ( vlevel_s1 ),
    .ecs_level          ( elevel_s1 ),
    .voice_on           ( ),
    .ce_pix             ( ce_pix ),
    .hcnt               ( hcnt ),
    .vcnt               ( vcnt ),
    .vline              ( vline ),
    .live               ( live ),
    .colour             ( stic_colour ),
    .audio              ( psg_audio ),
    .clk_74a            ( clk_74a ),
    .bridge_addr        ( bridge_addr ),
    .bridge_rd          ( bridge_rd ),
    .bridge_wr          ( bridge_wr ),
    .bridge_wr_data     ( bridge_wr_data ),
    .ss_bridge_rd_data  ( ss_bridge_rd_data ),
    .jlp_bridge_rd_data ( jlp_bridge_rd_data ),
    .jlp_sectors        ( jlp_sectors ),
    .savestate_start        ( savestate_start ),
    .savestate_start_ack    ( savestate_start_ack ),
    .savestate_start_busy   ( savestate_start_busy ),
    .savestate_start_ok     ( savestate_start_ok ),
    .savestate_start_err    ( savestate_start_err ),
    .savestate_load         ( savestate_load ),
    .savestate_load_ack     ( savestate_load_ack ),
    .savestate_load_busy    ( savestate_load_busy ),
    .savestate_load_ok      ( savestate_load_ok ),
    .savestate_load_err     ( savestate_load_err ),
    .osnotify_inmenu    ( osnotify_inmenu ),
    .pause_en           ( set_pause ),
    .sram_a             ( sram_a ),
    .sram_dq_out        ( sram_dq_out ),
    .sram_dq_oe         ( sram_dq_oe ),
    .sram_dq_in         ( sram_dq ),
    .sram_oe_n          ( sram_oe_n ),
    .sram_we_n          ( sram_we_n ),
    .sram_ub_n          ( sram_ub_n ),
    .sram_lb_n          ( sram_lb_n )
);

    wire            in_pf;
    wire    [7:0]   pf_x, pf_y;
    wire    [3:0]   pat_colour, colour;

// Required slots: cartridge, EXEC, GROM (data.json)
// The CFG fetch's result (clk_74a, set once a load) into clk_sys for the
// CFG's second card
    reg     [2:0]   cfg_res_s1 = 3'd0, cfg_res_s2 = 3'd0;
// and the load's diagnostics (0.0.14; all held or slow-changing)
    reg     [13:0]  diag_s1 = 14'd0, diag_s2 = 14'd0;
always @(posedge clk_sys) begin
    cfg_res_s1 <= cfg_fetch_res;
    cfg_res_s2 <= cfg_res_s1;
    diag_s1 <= {cfg_fetch_to, target_state, d_ac, d_req, d_upd, d_phase, rtr_gaveup, 1'b0};
    diag_s2 <= diag_s1;
end

test_pattern pattern (
    .in_pf      ( in_pf ),
    .pf_x       ( pf_x ),
    .pf_y       ( pf_y ),
    .slot_st    ( slot_st ),
    .slot_req   ( 6'b001101 ),
    .len_st     ( cart_len_st ),
    .cfg_res    ( cfg_res_s2 ),
    .fetch_to   ( diag_s2[13:11] ),
    .tstate     ( diag_s2[10:7] ),
    .d_ac       ( diag_s2[6] ),
    .d_req      ( diag_s2[5] ),
    .d_upd      ( diag_s2[4] ),
    .d_phase    ( diag_s2[3:2] ),
    .rtr_gaveup ( diag_s2[1] ),
    .colour     ( pat_colour )
);

// The STIC's picture once the machine runs, else the test pattern (its
// slot indicators say what is missing). machine_reset changes only at
// loads and resets.
    assign colour = machine_reset ? pat_colour : stic_colour;

pocket_video video (
    .clk_sys    ( clk_sys ),
    .ce_pix     ( ce_pix ),
    .hcnt       ( hcnt ),
    .vline      ( vline ),
    .border_on  ( border_s[1] ),
    .blank      ( !live ),
    .in_pf      ( in_pf ),
    .pf_x       ( pf_x ),
    .pf_y       ( pf_y ),
    .colour     ( colour ),
    .clk_vid    ( clk_vid ),
    .video_rgb  ( video_rgb ),
    .video_de   ( video_de ),
    .video_skip ( video_skip ),
    .video_hs   ( video_hs ),
    .video_vs   ( video_vs )
);

assign video_rgb_clock    = clk_vid;
assign video_rgb_clock_90 = clk_vid_90;


////////////////////////////////////////////////////////////////////////////////
// Audio: the PSGs' 48 kHz sound (intv_psg: box filter from its 223.7 kHz
// steps, 0..32766, silence 0) on both channels. agg23's sound_i2s (MIT)
// takes it across to clk_74a and drives the Pocket's I2S DAC at 48 kHz.
////////////////////////////////////////////////////////////////////////////////

sound_i2s #(
    .CHANNEL_WIDTH  ( 16 ),
    .SIGNED_INPUT   ( 1 )
) sound (
    .clk_74a    ( clk_74a ),
    .clk_audio  ( clk_sys ),
    .audio_l    ( psg_audio ),
    .audio_r    ( psg_audio ),
    .audio_mclk ( audio_mclk ),
    .audio_lrck ( audio_lrck ),
    .audio_dac  ( audio_dac )
);

endmodule
