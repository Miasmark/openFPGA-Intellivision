// Intellivision core: the STIC (AY-3-8900-1), backgrounds (build step 4;
// DESIGN.md 2.4, 3 module 6, 9). MOBs and collisions are step 5: their
// registers are stored and read back here, nothing more.
//
// Written from DESIGN.md, docs/STIC_NOTES.md and our Python model
// (tools/stic.py, modes "stic" and "none"), which sim/tb/tb_system.sv
// follows cycle by cycle and pixel by pixel. STIC_NOTES lists every fact,
// its source (the GI 1980 catalog, the service manual, the wiki archive,
// the jzIntv documentation; MAME stic.cpp / intv_m.cpp read for facts only,
// BSD-3, no code) and every place where the sources disagree.
//
// CPU side (unchanged from the step-3 stub intv_stic_regs): the registers
// read and write as MAME's stic_device::read / write do (MAME
// stic.cpp:1139-1309); a write to $20 sets the handshake for the frame and
// the frame's end clears it (stic.cpp:1111-1116, 1270-1274); open = vb ||
// !handshake (MAME intv_m.cpp:484-512); closed reads give the offset and
// closed writes are dropped; a register keeps only the bits it reads back
// (MXR $3800 | 11 bits, MYR $3000 | 12, MAR 14, MCR $3C00 | 10 without the
// MOB's own collision bit, CSR0-3 and BCR $3FF0 | 4, HDR / VDR $3FF8 | 3,
// CBR $3FFC | 2, the rest $3FFF); writing $21 selects Foreground/Background
// mode, reading $21 (or $4021 / $8021 / $C021) Color Stack mode. The
// VBlank window, INTRM and the frame's end come from intv_bus (vb,
// frame_end), which counts them from the same frame position.
//
// Frame (CPU cycles from the frame start, slot 0 = vcnt 0; 57 a line):
//   - end of the VBlank window: at the ce that ends slot VB_CYCLES - 1 the
//     STIC takes the frame's display enable (the handshake), vertical
//     delay and border colour, after the CPU's accesses up to that slot
//     (en_l, vdr_l, bcr_l). A $20 write later in the frame leaves it blank
//     (STIC_NOTES D8, our choice).
//   - BUSRQ (to the CPU, when busrq_en): 42 cycles from VB_CYCLES (MAME
//     stic.h:49), then for every card row r two whole lines from line
//     68 + 2 VDR + 16 r while they fit in the frame (12 rows, 13 when VDR
//     = 0; one line of warning and the fetch line: wiki STIC_Bus_Request,
//     MAME stic.h:51, GI 1980 p.5-10). The CPU samples its request lines
//     at the ce that ends a cycle, so busrq gives the value for the next
//     slot (as intv_bus does for INTRM).
//   - row fetch r, at the start of line 69 + 2 VDR + 16 r: if the CPU
//     acknowledged (busak during the fetch cycle) or BUSRQ is off
//     (busrq_en = 0, the step-3 system), the 20 BACKTAB words at the FIFO's
//     address counter are copied from System RAM (port B) into the row
//     buffer, two clk_sys a word, finished long before the CPU's next
//     cycle; then the counter steps by 20 (it stops once it has passed
//     System RAM: words past $035F read $3FFF). Otherwise the row buffer
//     keeps the previous row (wiki STIC_Bus_Request). INTAK clears the
//     counter (RA-3-9600, GI 1980 p.5-18).
// Picture (one 4-bit colour per pixel clock, `colour`, for pocket_video):
//   - lines PF_LINE .. PF_LINE + 191 hold 12 rows of 20 cards; the card
//     grid moves right by HDR pixels and down by 2 VDR lines; the strip
//     this uncovers, the 8-pixel left column (CBR bit 0), the top card row
//     (CBR bit 1) and the 160th column show the border colour; so does
//     everything outside the playfield and every line of a frame whose
//     display is not enabled (MAME stic.cpp:1102-1108, 1132-1135;
//     STIC_NOTES D6, D7, D13).
//   - one line ahead, at pixel clocks E0 .. E0 + 19 of line L, a card a
//     pixel clock, the STIC builds line L + 1 into a line buffer (two
//     banks of 20 entries: pattern byte, foreground and background
//     colour): BACKTAB word from the row buffer, its pattern byte for the
//     line from GROM (port vgrom) or GRAM (port B), the colours:
//       Color Stack: foreground bits 0-2 and 12; GROM card bits 3-10 or
//       GRAM card bits 3-8 (bit 11); bit 13 advances the stack before the
//       card; background = the stack entry ($28-$2B); the stack restarts at
//       0 every frame. A card with bit 12 set and bit 11 clear is Colored
//       Squares: quadrants bits 0-2, 3-5, 6-8 and 9-10 + 13, colour 7 =
//       the stack entry, no advance.
//       Foreground/Background: foreground bits 0-2, card bits 3-8 (GROM or
//       GRAM 0-63), background bits 9, 10, 13, 12.
//       (S9 stic.txt:334-471; wiki STIC; MAME stic.cpp:648-775.)
//   - the line buffer is read as the line is shown; bit 7 of the pattern
//     byte is the leftmost pixel, and each card pixel row is two lines.
//   - the border colour shown switches to bcr_l at line 67 (before that a
//     line shows the frame before's), so that every line from 67 on shows
//     the colour of the frame it belongs to.
// The display registers (CSR, HDR, CBR, the mode) are read live: they are
// closed to the CPU from the end of the VBlank window when the display is
// enabled, and unused when it is not.
//
// Clock enables: ce (the CPU cycle), ce_pix (the STIC's pixel clock; both
// only while the machine is live), live (every clk_sys the machine runs).
// Every block-RAM read port is read every clock from an address that is a
// function of the state and the position, and its word is used only when
// that address has been stable for a clock, so freezes, saves and restores
// may fall anywhere (intv_ram.sv).
//
// Save state (DESIGN.md 4.3; ss_rdata 0 unless addressed; write only while
// the machine is frozen):
//   SS_ID   words $00-$32 registers (the kept bits), $33 [0] csmode,
//           [1] handshake; $34 [0] en_l, [3:1] vdr_l, [7:4] bcr_l,
//           [11:8] bcr_d; $35 [8:0] FIFO address counter, [9] fetch armed,
//           [10] copy running, [15:11] copy word, [16] copy phase;
//           $36 [1:0] colour-stack position, [3:2] its value at the card
//           row's start, [7:4] the colour of the next pixel
//   SS_ROW  row buffer, 20 words (14 bits)
//   SS_LINE line buffer, 64 words ({bank, card}: [15:8] pattern byte,
//           [7:4] foreground, [3:0] background)
// The row and column positions are the machine's raster position (intv_timing).
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_stic #(
    parameter int         H_TOTAL   = 228,
    parameter int         V_TOTAL   = 262,
    parameter int         VB_CYCLES = 3790,
    parameter int         PF_X0     = 37,     // pixel clock of the playfield's first pixel
    parameter int         PF_LINE   = 70,     // first playfield line (vcnt)
    parameter int         REQ_LINE  = 68,     // row 0 BUSRQ line with VDR = 0
    parameter int         FRAME_RQ  = 42,     // frame BUSRQ cycles (MAME stic.h:49)
    parameter int         BD_LINE   = 67,     // the border colour switches here
    parameter int         E0        = 8,      // pixel clock of the first card built
    parameter logic [7:0] SS_ID     = 8'h04,
    parameter logic [7:0] SS_ROW    = 8'h0C,
    parameter logic [7:0] SS_LINE   = 8'h0D
) (
    input  wire logic        clk,
    input  wire logic        reset,           // machine reset
    input  wire logic        ce,              // CPU cycle
    input  wire logic        ce_pix,          // pixel clock (ce_stic)
    input  wire logic        live,            // the machine runs this clk
    input  wire logic [8:0]  hcnt,
    input  wire logic [8:0]  vcnt,

    // CPU side
    input  wire logic        vb,              // bus-copy window, this CPU cycle
    input  wire logic        frame_end,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [15:0] a,               // latched bus address
    input  wire logic [15:0] wdata,
    /* verilator lint_on UNUSEDSIGNAL */
    input  wire logic        rd,
    input  wire logic        we,
    output logic             open,
    output logic [15:0]      q,
    input  wire logic        intak,           // ce of an INTAK cycle
    input  wire logic        busrq_en,
    output logic             busrq,
    input  wire logic        busak,

    // graphics bus: System RAM, GRAM (their port B), GROM
    output logic [8:0]       sys_addr,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [15:0] sys_q,           // bits 14-15 are not on the graphics bus
    /* verilator lint_on UNUSEDSIGNAL */
    output logic [8:0]       gram_addr,
    input  wire logic [7:0]  gram_q,
    output logic [10:0]      grom_addr,
    input  wire logic [7:0]  grom_q,

    output logic [3:0]       colour,          // this pixel clock's colour

    input  wire logic        ss_en,
    input  wire logic [15:0] ss_addr,
    input  wire logic        ss_we,
    input  wire logic [31:0] ss_wdata,
    output logic [31:0]      ss_rdata
);

    localparam int NREG  = 'h33;
    localparam int CPL   = H_TOTAL / 4;
    localparam int FRAME = V_TOTAL * CPL;
    localparam int SYSW  = 352;              // System RAM words

    // ------------------------------------------------------------ registers
    logic [13:0] r [0:NREG-1];
    logic        hs = 1'b0, csmode = 1'b0;
    initial for (int i = 0; i < NREG; i++) r[i] = 14'd0;

    function automatic logic [13:0] keep(input logic [5:0] n);
        if (n < 6'h08)       keep = 14'h07FF;
        else if (n < 6'h10)  keep = 14'h0FFF;
        else if (n < 6'h18)  keep = 14'h3FFF;
        else if (n < 6'h20)  keep = 14'h03FF & ~(14'd1 << n[2:0]);
        else if (n >= 6'h28 && n <= 6'h2C) keep = 14'h000F;
        else if (n == 6'h30 || n == 6'h31)  keep = 14'h0007;
        else if (n == 6'h32) keep = 14'h0003;
        else                 keep = 14'h0000;
    endfunction

    function automatic logic [13:0] fixed(input logic [5:0] n);
        if (n < 6'h08)       fixed = 14'h3800;
        else if (n < 6'h10)  fixed = 14'h3000;
        else if (n < 6'h18)  fixed = 14'h0000;
        else if (n < 6'h20)  fixed = 14'h3C00;
        else if (n >= 6'h28 && n <= 6'h2C) fixed = 14'h3FF0;
        else if (n == 6'h30 || n == 6'h31)  fixed = 14'h3FF8;
        else if (n == 6'h32) fixed = 14'h3FFC;
        else                 fixed = 14'h3FFF;
    endfunction

    wire logic [5:0] n = a[5:0];
    assign open = vb || !hs;
    wire logic wr_ok = we && open;

    always_comb begin
        if (!open)
            q = {10'd0, n};
        else if (n < 6'(NREG))
            q = {2'b00, fixed(n) | (r[n] & keep(n))};
        else
            q = 16'h3FFF;
    end

    wire logic [3:0] csr [4];
    assign csr[0] = r[6'h28][3:0];
    assign csr[1] = r[6'h29][3:0];
    assign csr[2] = r[6'h2A][3:0];
    assign csr[3] = r[6'h2B][3:0];
    wire logic [2:0] hd  = r[6'h30][2:0];
    wire logic [1:0] cbr = r[6'h32][1:0];

    // -------------------------------------------------------- frame position
    wire logic [15:0] slot  = 16'(vcnt) * 16'(CPL) + 16'(hcnt[8:2]);
    wire logic        l_end = hcnt[8:2] == 7'(CPL - 1);
    wire logic [8:0]  nl    = !l_end ? vcnt : vcnt == 9'(V_TOTAL - 1) ? 9'd0 : vcnt + 9'd1;
    wire logic [15:0] slot_n = slot == 16'(FRAME - 1) ? 16'd0 : slot + 16'd1;

    // the frame's latches, taken at the end of the VBlank window
    logic       en_l = 1'b0;
    logic [2:0] vdr_l = 3'd0;
    logic [3:0] bcr_l = 4'd0, bcr_d = 4'd0;
    wire logic       hs_eff  = hs || (wr_ok && n == 6'h20);
    wire logic [2:0] vdr_eff = wr_ok && n == 6'h31 ? wdata[2:0] : r[6'h31][2:0];
    wire logic [3:0] bcr_eff = wr_ok && n == 6'h2C ? wdata[3:0] : r[6'h2C][3:0];
    wire logic       win_end = ce && slot == 16'(VB_CYCLES - 1);

    // ------------------------------------------------------------- BUSRQ
    // row requests, the fetch: line d = nl - REQ_LINE - 2 VDR from the row
    // 0 request; rows every 16 lines, request lines d % 16 = 0 and 1
    wire logic signed [10:0] d = 11'(nl) - 11'(REQ_LINE) - 11'({vdr_l, 1'b0});
    wire logic row_rq   = en_l && d >= 0 && d[3:1] == 3'd0;
    wire logic fetch_n  = en_l && d >= 0 && d[3:0] == 4'd1 && hcnt[8:2] == 7'(CPL - 1);
    wire logic frame_rq = slot_n >= 16'(VB_CYCLES) && slot_n < 16'(VB_CYCLES + FRAME_RQ)
                       && (slot_n == 16'(VB_CYCLES) ? hs_eff : en_l);
    assign busrq = busrq_en && (frame_rq || row_rq);

    // ------------------------------------------------- row fetch, row buffer
    logic [8:0] cnt = 9'd0;                   // FIFO address counter
    logic       cp_arm = 1'b0, cp_on = 1'b0, cp_ph = 1'b0;
    logic [4:0] cp_j = 5'd0;
    wire logic [9:0]  cp_a = 10'(cnt) + 10'(cp_j);
    assign sys_addr = cp_a[8:0];
    wire logic [13:0] cp_w = cp_a < 10'(SYSW) ? sys_q[13:0] : 14'h3FFF;
    wire logic        rb_we = live && cp_on && cp_ph && !reset && !ss_en;

    // ------------------------------------------------------ card engine
    // builds line T = vcnt + 1 at pixel clocks E0 .. E0 + 19 of line vcnt
    wire logic [8:0]  tl   = vcnt + 9'd1;
    wire logic signed [10:0] yy_t = 11'(tl) - 11'(PF_LINE) - 11'({vdr_l, 1'b0});
    wire logic eng_line = en_l && vcnt >= 9'(PF_LINE - 1) && vcnt < 9'(PF_LINE + 191) && yy_t >= 0;
    wire logic [8:0]  ec   = hcnt - 9'(E0);
    wire logic eng_card = eng_line && hcnt >= 9'(E0) && hcnt < 9'(E0 + 20);
    wire logic [2:0]  py   = yy_t[3:1];
    wire logic        rstart = yy_t[3:0] == 4'd0;
    logic [1:0] cs = 2'd0, cs_row = 2'd0;
    wire logic [1:0]  cs_use = ec[4:0] == 5'd0 && !rstart ? cs_row : cs;

    logic [13:0] w;                           // the card's BACKTAB word (row buffer port B)
    wire logic squares = csmode && w[12] && !w[11];
    assign grom_addr = csmode ? {w[10:3], py} : {2'b00, w[8:3], py};
    assign gram_addr = {w[8:3], py};
    wire logic [7:0] pat = w[11] ? gram_q : grom_q;

    function automatic logic [3:0] sqc(input logic [2:0] c, input logic [3:0] top);
        sqc = c == 3'd7 ? top : {1'b0, c};
    endfunction

    logic [1:0] cs_new;
    logic [7:0] e_bits;
    logic [3:0] e_fg, e_bg;
    always_comb begin
        cs_new = cs_use;
        if (!csmode) begin
            e_bits = pat;
            e_fg   = {1'b0, w[2:0]};
            e_bg   = {w[12], w[13], w[10], w[9]};
        end else if (squares) begin
            e_bits = 8'hF0;
            e_fg   = sqc(py[2] ? w[8:6] : w[2:0], csr[cs_use]);
            e_bg   = sqc(py[2] ? {w[13], w[10:9]} : w[5:3], csr[cs_use]);
        end else begin
            cs_new = cs_use + {1'b0, w[13]};
            e_bits = pat;
            e_fg   = {w[12], w[2:0]};
            e_bg   = csr[cs_new];
        end
    end
    wire logic lb_we = ce_pix && eng_card && !reset && !ss_en;

    // ----------------------------------------------------------- pixels
    // the colour of the next pixel clock (nx) of this line, registered at
    // ce_pix: pixel clock 0 of a line (nx = H_TOTAL) is always border
    wire logic [9:0]  nx   = 10'(hcnt) + 10'd1;
    wire logic signed [11:0] xp = 12'(nx) - 12'(PF_X0);
    wire logic signed [10:0] yy_l = 11'(vcnt) - 11'(PF_LINE) - 11'({vdr_l, 1'b0});
    wire logic pf_line = en_l && vcnt >= 9'(PF_LINE) && vcnt < 9'(PF_LINE + 192) && yy_l >= 0
                      && !(cbr[1] && vcnt < 9'(PF_LINE + 16));
    wire logic pf_x = xp >= $signed({8'd0, cbr[0] ? 4'd8 : {1'b0, hd}}) && xp < 12'sd159;
    wire logic [11:0] xx = xp - 12'(hd);
    logic [15:0] lb_q;
    logic [3:0]  pix = 4'd0;
    wire logic [3:0] pf_c = lb_q[4'd15 - {1'b0, xx[2:0]}] ? lb_q[7:4] : lb_q[3:0];
    assign colour = pix;

    // ---------------------------------------------------------- the RAMs
    logic [31:0] ssr_row, ssr_line;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [13:0] rb_qa;                       // port A reads: the state port's only
    logic [15:0] lb_qa;
    /* verilator lint_on UNUSEDSIGNAL */

    intv_ram #(.AW(5), .DW(14), .WORDS(20), .SS_ID(SS_ROW)) rowbuf (
        .clk, .addr(cp_j), .we(rb_we), .d(cp_w), .q(rb_qa),
        .addr_b(ec[4:0]), .q_b(w),
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_row));

    intv_ram #(.AW(6), .DW(16), .WORDS(64), .SS_ID(SS_LINE)) linebuf (
        .clk, .addr({tl[0], ec[4:0]}), .we(lb_we), .d({e_bits, e_fg, e_bg}), .q(lb_qa),
        .addr_b({vcnt[0], xx[7:3]}), .q_b(lb_q),
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_line));

    // ------------------------------------------------------- state machine
    wire logic       ss_hit = ss_addr[15:8] == SS_ID;
    wire logic [7:0] ss_w   = ss_addr[7:0];

    always_ff @(posedge clk) begin
        if (reset) begin
            for (int i = 0; i < NREG; i++) r[i] <= 14'd0;
            hs <= 1'b0;
            csmode <= 1'b0;
            {en_l, vdr_l, bcr_l, bcr_d} <= 12'd0;
            {cp_arm, cp_on, cp_ph} <= 3'd0;
            {cs, cs_row} <= 4'd0;
            pix <= 4'd0;
        end else if (ss_we && ss_hit) begin
            if (ss_w < 8'(NREG))
                r[ss_w[5:0]] <= ss_wdata[13:0] & keep(ss_w[5:0]);
            else unique case (ss_w)
                8'h33: {hs, csmode} <= ss_wdata[1:0];
                8'h34: {bcr_d, bcr_l, vdr_l, en_l} <= ss_wdata[11:0];
                8'h35: {cp_ph, cp_j, cp_on, cp_arm, cnt} <= ss_wdata[16:0];
                8'h36: {pix, cs_row, cs} <= ss_wdata[7:0];
                default: ;
            endcase
        end else begin
            // CPU side
            if (we && open) begin
                if (n < 6'(NREG))
                    r[n] <= wdata[13:0] & keep(n);
                if (n == 6'h20)
                    hs <= 1'b1;
                if (n == 6'h21)
                    csmode <= 1'b0;
            end
            if (rd && open && a[13:0] == 14'h0021)
                csmode <= 1'b1;
            if (frame_end)
                hs <= 1'b0;

            // the frame's latches
            if (win_end) begin
                en_l  <= hs_eff;
                vdr_l <= vdr_eff;
                bcr_l <= bcr_eff;
            end
            if (ce_pix && vcnt == 9'(BD_LINE - 1) && hcnt == 9'(H_TOTAL - 1))
                bcr_d <= bcr_l;

            // row fetch
            if (intak)
                cnt <= 9'd0;
            if (live) begin
                if (cp_arm) begin
                    cp_arm <= 1'b0;
                    if (!busrq_en || busak) begin
                        cp_on <= 1'b1;
                        cp_j  <= 5'd0;
                        cp_ph <= 1'b0;
                    end
                end else if (cp_on) begin
                    cp_ph <= !cp_ph;
                    if (cp_ph) begin
                        if (cp_j == 5'd19) begin
                            cp_on <= 1'b0;
                            if (cnt < 9'(SYSW))
                                cnt <= cnt + 9'd20;
                        end else
                            cp_j <= cp_j + 5'd1;
                    end
                end
                if (ce && fetch_n)
                    cp_arm <= 1'b1;
            end

            // card engine: the colour stack
            if (ce_pix && eng_card) begin
                cs <= cs_new;
                if (ec[4:0] == 5'd0 && rstart)
                    cs_row <= cs;
            end
            if (frame_end)
                {cs, cs_row} <= 4'd0;

            // pixels
            if (ce_pix)
                pix <= pf_line && pf_x ? pf_c : bcr_d;
        end
    end

    always_comb begin
        ss_rdata = ssr_row | ssr_line;
        if (ss_hit) begin
            if (ss_w < 8'(NREG))
                ss_rdata = {18'd0, r[ss_w[5:0]]};
            else unique case (ss_w)
                8'h33: ss_rdata = {30'd0, hs, csmode};
                8'h34: ss_rdata = {20'd0, bcr_d, bcr_l, vdr_l, en_l};
                8'h35: ss_rdata = {15'd0, cp_ph, cp_j, cp_on, cp_arm, cnt};
                8'h36: ss_rdata = {24'd0, pix, cs_row, cs};
                default: ;
            endcase
        end
    end

    /* verilator lint_off UNUSEDSIGNAL */
    wire logic [7:0] unused = {xx[11:8], ec[8:5]};
    /* verilator lint_on UNUSEDSIGNAL */

    initial begin
        if (H_TOTAL % 4 != 0 || PF_X0 < 14 || PF_X0 + 160 > H_TOTAL || E0 + 20 > H_TOTAL)
            $error("intv_stic: parameter out of range");
    end

endmodule

`default_nettype wire
