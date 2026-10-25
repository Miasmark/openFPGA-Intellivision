// Intellivision core: the CPU bus fabric (DESIGN.md 2.5, 2.6, 3 module 4;
// build step 3).
//
// Written from DESIGN.md and our Python system model (tools/intv_system.py),
// which the bench (sim/tb/tb_system.sv) follows cycle by cycle.
//
// Bus. The CPU gives a phase code and dout and takes din (no tristate,
// DESIGN 2.5). Every device sees the same latched address, as the chips
// latch it: on BAR and INTAK from dout, on ADAR from the bus, which is the
// word the addressed device returns (din). On INTAK the cartridge port sees
// a BAR (DESIGN 2.5); here every device latches on INTAK alike, which is
// the same for the devices step 3 has. Devices drive the bus only in the
// read phases (DTB and ADAR); every word they drive is ANDed, and a device
// that is not addressed gives $FFFF, so a read nobody answers is $FFFF (the
// pull-ups, DESIGN 2.5). Writes happen at the ce that ends DW (the model's
// write cycle). IAB reads the vectors: $1000 the first time after reset,
// then $1004 (DESIGN 2.1: U9 supplies them; MAME intv_m.cpp:550-561).
//
// Address decode (DESIGN 2.6; reads unless marked):
//   $0000-$003F             STIC registers (intv_stic); writes also from
//                           the aliases $4000, $8000, $C000 ($x000-$x03F);
//                           a read of $x021 reaches the mode latch
//   $0100-$01EF             scratchpad, 8-bit: the upper byte reads 0
//   $01F0-$01FF             PSG registers and hand controllers, upper byte 0
//   $0200-$035F             System RAM, 16-bit
//   $1000-$1FFF             EXEC ROM, 10-bit: the upper 6 bits read 0
//   $3000-$37FF             GROM: $FF00 | byte
//   $3800-$3FFF             GRAM, 512 x 8, mirrored; writes also from
//                           $7800, $B800, $F800 (+ $7FF)
//   the cartridge port      everywhere its page table maps (intv_cart)
// STIC registers and GRAM are open to the CPU in the bus-copy window
// (VBlank) or while the STIC handshake is clear; otherwise a read gives
// the address offset and a write is dropped (MAME intv_m.cpp:484-512).
//
// Frame timing. vcnt / hcnt are the machine's position (intv_timing; they
// are only used under ce, i.e. while the machine is live). A frame is
// V_TOTAL x H_TOTAL / 4 CPU cycles, slot 0 the first CPU cycle of VBlank
// (vcnt 0). INTRM is held during the first VB_CYCLES slots (DESIGN 2.4:
// 3,790; MAME stic.h:50), and that is the bus-copy window too (MAME
// intv_m.cpp:660-666). The CPU samples its request lines at the ce that
// starts a cycle (cp1610.sv), so intrm gives the value for the slot after
// the one ending; vb is the window of the slot now running. Both come from
// the position alone, so they need no state.
//
// Reset and the frame: mreset holds the machine. When it ends, the CPU
// stays held (hold) until the ce that ends slot FRAME-2, so its reset IAB
// is the frame's last slot and its first fetch (the model's cycle 0) slot
// 0. The model and the bench count on this alignment.
//
// The cartridge port (intv_cart via intv_media) is asked at the clock after
// every address latch (a read) and after DW (a write); it answers in about
// 6 clk_sys, long before the read phase (two CPU cycles of 48 clk_sys
// later at least). Its answer is held here (cart_q, cart_hit), in the state.
//
// Save state (DESIGN.md 4.3; module id SS_ID, 2 words; ss_rdata is 0
// unless addressed, so ports OR-combine; write only while the machine is
// frozen, with mreset low). The cartridge request in flight (cart_req,
// c_rd and intv_media's SRAM read, about 6 clk_sys after a BAR, ADAR,
// INTAK or DW ce) is not in the state: ss_ctl (step 7) must freeze only at
// the quiet point of DESIGN 4.2 (an instruction boundary, where no request
// is in flight), or wait at least 16 clk_sys after the last ce before it
// reads the state (sim/tb/tb_system.sv freeze() waits 16). A save read
// sooner could store a stale cart_q.
//   0  [15:0] latched address, [16] next IAB is the reset vector,
//      [17] cart_hit, [18] hold
//   1  [15:0] cart_q
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_bus #(
    parameter int         H_TOTAL   = 228,      // pixel clocks per line
    parameter int         V_TOTAL   = 262,      // lines per frame
    parameter int         VB_CYCLES = 3790,     // INTRM / bus-copy window
    parameter logic [7:0] SS_ID     = 8'h03
) (
    input  wire logic        clk,
    input  wire logic        mreset,          // machine reset (synchronous)
    input  wire logic        ce,              // CPU cycle (ce_cpu)
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [8:0]  hcnt,            // [1:0] unused: CPU cycle = 4 pixels
    input  wire logic [31:0] ss_wdata,        // [31:19] unused
    /* verilator lint_on UNUSEDSIGNAL */
    input  wire logic [8:0]  vcnt,
    output logic             hold,            // CPU held in reset
    output logic             frame_end,       // ce that ends the frame's last slot

    // CPU
    input  wire logic [2:0]  phase,
    input  wire logic [15:0] dout,
    output logic [15:0]      din,
    output logic             intrm,

    // to the devices
    output logic [15:0]      a,               // latched address
    output logic             rd,              // ce of a read phase (DTB, ADAR)
    output logic             wr,              // ce of DW
    output logic             vb,              // bus-copy window, this slot
    output logic             scr_we, psg_we, sys_we, gram_we, stic_we,

    // from the devices
    input  wire logic        stic_open,       // STIC registers and GRAM open
    input  wire logic [15:0] stic_q,          // $0000-$003F
    input  wire logic [7:0]  scr_q,
    input  wire logic [7:0]  psg_q,
    input  wire logic [15:0] sys_q,
    input  wire logic [9:0]  exec_q,
    input  wire logic [7:0]  grom_q,
    input  wire logic [7:0]  gram_q,

    // cartridge port (intv_media)
    output logic             cart_req,
    output logic             cart_we,
    output logic [15:0]      cart_wdata,
    input  wire logic        cart_ack,
    input  wire logic [15:0] cart_rdata,
    input  wire logic        cart_hit_in,

    // state port
    input  wire logic [15:0] ss_addr,
    input  wire logic        ss_we,
    output logic [31:0]      ss_rdata
);

    localparam logic [2:0] PH_ADAR = 3'd1, PH_IAB = 3'd2, PH_DTB = 3'd3,
                           PH_BAR = 3'd4, PH_DW = 3'd5, PH_INTAK = 3'd7;
    localparam int CPL   = H_TOTAL / 4;           // CPU cycles per line
    localparam int FRAME = V_TOTAL * CPL;

    logic        iab_rst = 1'b1;
    logic        cart_hit = 1'b0;
    logic [15:0] cart_q = 16'hFFFF;
    logic        c_rd = 1'b0;
    initial begin
        a = 16'd0; hold = 1'b1;
        cart_req = 1'b0; cart_we = 1'b0; cart_wdata = 16'd0;
    end

    // ---------------------------------------------------------- frame slot
    wire logic [15:0] slot = 16'(vcnt) * 16'(CPL) + 16'(hcnt[8:2]);
    wire logic        last = slot == 16'(FRAME - 1);
    wire logic        vb_next = last || slot < 16'(VB_CYCLES - 1);
    assign intrm     = vb_next;
    assign vb        = slot < 16'(VB_CYCLES);
    assign frame_end = ce && last;

    // -------------------------------------------------------------- decode
    wire logic sel_stic = a[15:6] == 10'd0;
    wire logic sel_scr  = a[15:8] == 8'h01 && a[7:4] != 4'hF;
    wire logic sel_psg  = a[15:4] == 12'h01F;
    wire logic sel_sys  = a[15:9] == 7'b0000001 && a[8:0] < 9'h160;
    wire logic sel_exec = a[15:12] == 4'h1;
    wire logic sel_grom = a[15:11] == 5'b00110;
    wire logic sel_gram = a[15:11] == 5'b00111;

    wire logic rphase = phase == PH_DTB || phase == PH_ADAR;
    assign rd = ce && rphase;
    assign wr = ce && phase == PH_DW;

    assign scr_we  = wr && sel_scr;
    assign psg_we  = wr && sel_psg;
    assign sys_we  = wr && sel_sys;
    assign gram_we = wr && a[13:11] == 3'b111 && stic_open;
    assign stic_we = wr && a[13:6] == 8'd0;

    // ------------------------------------------------------------ data in
    always_comb begin
        din = 16'hFFFF;
        if (phase == PH_IAB)
            din = iab_rst ? 16'h1000 : 16'h1004;
        else if (rphase) begin
            if (sel_stic) din &= stic_q;
            if (sel_scr)  din &= {8'h00, scr_q};
            if (sel_psg)  din &= {8'h00, psg_q};
            if (sel_sys)  din &= sys_q;
            if (sel_exec) din &= {6'd0, exec_q};
            if (sel_grom) din &= {8'hFF, grom_q};
            if (sel_gram) din &= stic_open ? {8'h00, gram_q} : {7'd0, a[8:0]};
            if (cart_hit) din &= cart_q;
        end
    end

    // ----------------------------------------------------------- registers
    wire logic ss_hit = ss_addr[15:8] == SS_ID;
    wire logic [7:0] ss_w = ss_addr[7:0];

    always_ff @(posedge clk) begin
        cart_req <= 1'b0;
        if (cart_ack && c_rd) begin
            cart_q   <= cart_rdata;
            cart_hit <= cart_hit_in;
        end
        if (mreset) begin
            hold     <= 1'b1;
            a        <= 16'd0;
            iab_rst  <= 1'b1;
            cart_q   <= 16'hFFFF;
            cart_hit <= 1'b0;
        end else if (ss_we && ss_hit) begin
            if (ss_w == 8'd0) begin
                a <= ss_wdata[15:0];
                {hold, cart_hit, iab_rst} <= ss_wdata[18:16];
            end else if (ss_w == 8'd1)
                cart_q <= ss_wdata[15:0];
        end else if (ce) begin
            if (hold && slot == 16'(FRAME - 2))
                hold <= 1'b0;
            if (!hold) begin
                unique case (phase)
                    PH_BAR, PH_INTAK: a <= dout;
                    PH_ADAR:          a <= din;
                    PH_IAB:           iab_rst <= 1'b0;
                    default: ;
                endcase
                if (phase == PH_BAR || phase == PH_INTAK || phase == PH_ADAR) begin
                    cart_req <= 1'b1;
                    cart_we  <= 1'b0;
                    c_rd     <= 1'b1;
                end else if (phase == PH_DW) begin
                    cart_req   <= 1'b1;
                    cart_we    <= 1'b1;
                    cart_wdata <= dout;
                    c_rd       <= 1'b0;
                end
            end
        end
    end

    always_comb begin
        ss_rdata = 32'd0;
        if (ss_hit)
            unique case (ss_w)
                8'd0: ss_rdata = {13'd0, hold, cart_hit, iab_rst, a};
                8'd1: ss_rdata = {16'd0, cart_q};
                default: ;
            endcase
    end

    initial begin
        if (H_TOTAL % 4 != 0 || VB_CYCLES < 2 || VB_CYCLES >= V_TOTAL * (H_TOTAL / 4))
            $error("intv_bus: parameter out of range");
    end

endmodule

`default_nettype wire
