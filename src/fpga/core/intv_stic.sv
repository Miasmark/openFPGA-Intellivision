// Intellivision core: the STIC (AY-3-8900-1): backgrounds (build step 4),
// MOBs and collisions (build step 5; DESIGN.md 2.4, 3 module 6, 9).
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
//     STIC takes the frame's display enable (the handshake) and vertical
//     delay, after the CPU's accesses up to that slot (en_l, vdr_l). A $20
//     write later in the frame leaves it blank (STIC_NOTES D8, our choice).
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
//   - every border pixel shows the border colour register ($2C) as it is
//     when the pixel is registered: a write in CPU cycle t (written at the
//     ce that ends it) shows from pixel clock 4 t + 5 on (STIC_NOTES D17).
// The display registers (CSR, HDR, CBR, the border colour, the mode) are
// read live: they are closed to the CPU from the end of the VBlank window
// when the display is enabled, and the CPU may change the border colour
// at any time when it is not.
//
// MOBs (build step 5; STIC_NOTES 5, the hardware rules of modes "stic" and
// "none": M1-M5). Registers X $00-$07 (X 0-7, INTR 8, VISB 9, XSIZE 10),
// Y $08-$0F (Y 0-6, YRES 7, YSIZ2 8, YSIZ4 9, XFLIP 10, YFLIP 11), A
// $10-$17 (colour 0-2 + 12, card 3-10, GRAM 11, PRIO 13), collisions C
// $18-$1F. In picture lines (raster line - PF_LINE + 24) MOB m's top is
// 2 (Y + 4 + VDR); its pixel clock X + HDR + PF_X0 - 8; X = 0: no MOB.
// Pattern row = (line - top) >> (2 YSIZ4 + YSIZ2), 8 rows (16 with YRES:
// cards 2k and 2k + 1, bit 0 of the card ignored, M1), YFLIP reverses
// them; card bits 6-7 count only for a GROM card in Color Stack mode
// (M2); a pattern byte gives 8 pixels, 16 with XSIZE, XFLIP mirrors them.
// The MOB registers, GRAM and the mode are closed to the CPU from the end
// of the VBlank window (win_end) to the frame's end when the display is
// enabled (the only frames with MOBs), so every MOB read below sees what
// the model's draw() sees at the frame's end. Three users share the
// GROM / GRAM ports, by the raster position:
//   - the card engine, pixel clocks E0 .. E0 + 19 (as step 4);
//   - the line's MOBs, pixel clocks MF .. MF + 7 of line L (after the
//     playfield's last pixel): MOB m's pattern byte for line L + 1, made
//     into a 16-pixel mask (rm[m]) for the pixels of line L + 1;
//   - the collision sweep, every other clock: from win_end, for every
//     picture line 8 .. 403 that any MOB can cover (off the raster too),
//     the 8 masks of the MOBs with INTR (gm[m]), then 28 pairs of them:
//     MOB-MOB collisions anywhere in the object field (M7) and border
//     collisions (a pixel outside the collision area: picture lines
//     24 + 16 CBR[1] .. 215, pixel clocks PF_X0 + 8 CBR[0] .. PF_X0 + 158;
//     M8). It finishes about 7 lines after win_end.
// The pixel (one pixel ahead, as step 4): each MOB's bit from rm; the
// lowest-numbered MOB with VISB and a pixel there wins, and shows unless
// its PRIO is set and the background pixel is "on" (M3): a card's
// foreground pixel, a Colored Squares quadrant of colour 0-6 (M5); under
// the delay strips nothing is "on" (M4). Shown only where the playfield
// is. In the collision area an "on" pixel under a MOB with INTR sets its
// background bit. The bits gather in coll_p and are ORed into $18-$1F at
// the frame's end, as the model does (a MOB never sets its own bit).
//
// Clock enables: ce (the CPU cycle), ce_pix (the STIC's pixel clock; both
// only while the machine is live), live (every clk_sys the machine runs).
// Every block-RAM read port is read every clock from an address that is a
// function of the state and the position, and its word is used only when
// that address has been stable for a clock, so freezes, saves and restores
// may fall anywhere (intv_ram.sv). The sweep takes a GROM / GRAM word only
// at pixel clocks whose previous pixel clock was its own (g_ok).
//
// Save state (DESIGN.md 4.3; ss_rdata 0 unless addressed; write only while
// the machine is frozen):
//   SS_ID   words $00-$32 registers (the kept bits), $33 [0] csmode,
//           [1] handshake; $34 [0] en_l, [3:1] vdr_l; $35 [8:0] FIFO address counter, [9] fetch armed,
//           [10] copy running, [15:11] copy word, [16] copy phase;
//           $36 [1:0] colour-stack position, [3:2] its value at the card
//           row's start, [7:4] the colour of the next pixel;
//           $37 the sweep: [8:0] picture line, [11:9] MOB (pairs: the
//           first), [14:12] the pair's second MOB, [15] fetching (else
//           pairs), [16] word phase, [17] running;
//           $38-$3B sweep masks {gm[2i + 1], gm[2i]}; $3C-$3F line masks
//           {rm[2i + 1], rm[2i]}; $40-$42 collision bits gathered this
//           frame, 10 a MOB: {coll_p[2], [1], [0]}, {[5], [4], [3]}, {[7], [6]}
//   SS_ROW  row buffer, 20 words (14 bits)
//   SS_LINE line buffer, 64 words ({bank, card}: [17:16] "on" for a 1 / 0
//           pattern bit, [15:8] pattern byte, [7:4] foreground, [3:0]
//           background)
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
    parameter int         E0        = 8,      // pixel clock of the first card built
    parameter int         MF        = 196,    // pixel clock of the first MOB's line fetch
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
    wire logic [3:0] bcr = r[6'h2C][3:0];
    wire logic [1:0] cbr = r[6'h32][1:0];

    // -------------------------------------------------------- frame position
    wire logic [15:0] slot  = 16'(vcnt) * 16'(CPL) + 16'(hcnt[8:2]);
    wire logic        l_end = hcnt[8:2] == 7'(CPL - 1);
    wire logic [8:0]  nl    = !l_end ? vcnt : vcnt == 9'(V_TOTAL - 1) ? 9'd0 : vcnt + 9'd1;
    wire logic [15:0] slot_n = slot == 16'(FRAME - 1) ? 16'd0 : slot + 16'd1;

    // the frame's latches, taken at the end of the VBlank window
    logic       en_l = 1'b0;
    logic [2:0] vdr_l = 3'd0;
    wire logic       hs_eff  = hs || (wr_ok && n == 6'h20);
    wire logic [2:0] vdr_eff = wr_ok && n == 6'h31 ? wdata[2:0] : r[6'h31][2:0];
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
    wire logic [10:0] c_grom = csmode ? {w[10:3], py} : {2'b00, w[8:3], py};
    wire logic [7:0] pat = w[11] ? gram_q : grom_q;

    function automatic logic [3:0] sqc(input logic [2:0] c, input logic [3:0] top);
        sqc = c == 3'd7 ? top : {1'b0, c};
    endfunction

    logic [1:0] cs_new;
    logic [7:0] e_bits;
    logic [3:0] e_fg, e_bg;
    logic [1:0] e_on;                         // "on" for a pattern bit 1 / 0 (MOB priority, collisions)
    always_comb begin
        cs_new = cs_use;
        e_on   = 2'b10;
        if (!csmode) begin
            e_bits = pat;
            e_fg   = {1'b0, w[2:0]};
            e_bg   = {w[12], w[13], w[10], w[9]};
        end else if (squares) begin
            e_bits = 8'hF0;
            e_fg   = sqc(py[2] ? w[8:6] : w[2:0], csr[cs_use]);
            e_bg   = sqc(py[2] ? {w[13], w[10:9]} : w[5:3], csr[cs_use]);
            // colour 7 (the stack's colour) is never "on" (S9 stic.txt:433-434; M5)
            e_on   = {py[2] ? w[8:6] != 3'd7 : w[2:0] != 3'd7,
                      py[2] ? {w[13], w[10:9]} != 3'd7 : w[5:3] != 3'd7};
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
    logic [17:0] lb_q;
    logic [3:0]  pix = 4'd0;
    wire logic   pf_b = lb_q[5'd15 - {2'b0, xx[2:0]}];
    wire logic [3:0] pf_c = pf_b ? lb_q[7:4] : lb_q[3:0];
    assign colour = pix;

    // ------------------------------------------------------------- MOBs
    // the MOB unit: MOB um's pattern row for picture line uln, its GROM /
    // GRAM address and (a clock later) its 16-pixel mask
    localparam int PIC0 = PF_LINE - 24;       // raster line of picture line 0
    wire logic       rf_win = hcnt >= 9'(MF) && hcnt < 9'(MF + 8);
    wire logic       cd_win = hcnt >= 9'(E0) && hcnt < 9'(E0 + 20);
    wire logic       g_ok   = !(hcnt >= 9'(E0) && hcnt <= 9'(E0 + 20)) && !(hcnt >= 9'(MF) && hcnt <= 9'(MF + 8));
    wire logic [8:0] hm     = hcnt - 9'(MF);
    logic [2:0]  g_m = 3'd0, g_j = 3'd0;       // sweep: MOB (pairs: first, second)
    logic [8:0]  g_ly = 9'd0;                  // sweep: picture line
    logic        g_on = 1'b0, g_f = 1'b0, g_ph = 1'b0;
    logic [15:0] gm [8];                       // sweep masks (MOBs with INTR)
    logic [15:0] rm [8];                       // line masks
    logic [9:0]  coll_p [8];                   // collision bits gathered this frame
    initial for (int i = 0; i < 8; i++) begin
        gm[i] = 16'd0; rm[i] = 16'd0; coll_p[i] = 10'd0;
    end

    wire logic [2:0]  um  = rf_win ? hm[2:0] : g_m;
    wire logic signed [11:0] uln = rf_win ? 12'(vcnt) + 12'sd1 - 12'(PIC0) : 12'(g_ly);
    wire logic [13:0] u_x = r[{3'b000, um}];
    wire logic [13:0] u_y = r[{3'b001, um}];
    wire logic [13:0] u_a = r[{3'b010, um}];
    wire logic [7:0]  u_top = 8'(u_y[6:0]) + 8'd4 + 8'(vdr_l);          // in card pixel rows
    wire logic signed [11:0] u_dy = uln - 12'({u_top, 1'b0});
    wire logic [1:0]  u_s  = {u_y[9], u_y[8]};                          // YSIZ4, YSIZ2
    wire logic [10:0] u_rw = u_dy[10:0] >> u_s;
    wire logic        u_in = !u_dy[11] && u_rw < (u_y[7] ? 11'd16 : 11'd8);
    wire logic [3:0]  u_row = u_rw[3:0] ^ (u_y[11] ? {u_y[7], 3'b111} : 4'd0);
    logic [7:0] u_card;
    always_comb begin
        u_card = u_a[10:3];
        if (u_a[11] || !csmode)
            u_card[7:6] = 2'b00;                // M2; GRAM cards 0-63
        if (u_y[7])
            u_card[0] = 1'b0;                   // YRES: cards 2k, 2k + 1 (M1)
    end
    wire logic [10:0] u_addr = {u_card, 3'b000} + 11'(u_row);
    assign grom_addr = cd_win ? c_grom : u_addr;
    assign gram_addr = cd_win ? {w[8:3], py} : u_addr[8:0];
    wire logic [7:0]  u_pat = u_a[11] ? gram_q : grom_q;

    // pattern byte -> pixel k of the MOB (bit k), XSIZE xs, XFLIP xf
    function automatic logic [15:0] expand(input logic [7:0] p, input logic xs, input logic xf);
        for (int k = 0; k < 16; k++)
            if (xs)
                expand[k] = xf ? p[k / 2] : p[7 - k / 2];
            else
                expand[k] = k < 8 && (xf ? p[k % 8] : p[7 - k % 8]);
    endfunction
    wire logic [15:0] u_mask = u_x[7:0] != 8'd0 && u_in ? expand(u_pat, u_x[10], u_y[10]) : 16'd0;

    // the sweep's border test for MOB um on line g_ly: pixels outside the
    // collision area
    wire logic [9:0] u_xs = 10'(u_x[7:0]) + 10'(hd) + 10'(PF_X0 - 8);  // pixel clock of pixel 0
    wire logic [9:0] cx0  = 10'(PF_X0) + (cbr[0] ? 10'd8 : 10'd0);
    logic [15:0] u_inx;
    always_comb
        for (int k = 0; k < 16; k++)
            u_inx[k] = u_xs + 10'(k) >= cx0 && u_xs + 10'(k) <= 10'(PF_X0 + 158);
    wire logic g_rowin = g_ly >= (cbr[1] ? 9'd40 : 9'd24) && g_ly <= 9'd215;
    wire logic g_bord  = u_mask != 16'd0 && (!g_rowin || (u_mask & ~u_inx) != 16'd0);
    wire logic g_last  = g_ly == 9'd403;        // 2 (127 + 4 + 7) + 128 - 1

    // the sweep's pair test: MOBs g_m and g_j overlap on this line
    wire logic [15:0] p_mi = gm[g_m], p_mj = gm[g_j];
    wire logic [8:0]  p_d  = 9'(r[{3'b000, g_j}][7:0]) - 9'(r[{3'b000, g_m}][7:0]);
    wire logic [8:0]  p_ad = p_d[8] ? -p_d : p_d;
    wire logic [15:0] p_sh = (p_d[8] ? p_mi : p_mj) << p_ad[3:0];
    wire logic        p_hit = p_ad < 9'd16 && (p_sh & (p_d[8] ? p_mj : p_mi)) != 16'd0;

    // the pixel: MOB lanes
    logic [7:0] l_b;
    always_comb
        for (int i = 0; i < 8; i++) begin
            logic [10:0] k;
            k = 11'(nx) - 11'(r[i][7:0]) - 11'(hd) - 11'(PF_X0 - 8);
            l_b[i] = k < 11'd16 && rm[i][k[3:0]];
        end
    logic [7:0] l_vis, l_intr;
    always_comb
        for (int i = 0; i < 8; i++) begin
            l_vis[i]  = r[i][9];
            l_intr[i] = r[i][8];
        end
    wire logic [7:0] l_hit = l_b & l_vis;
    logic [2:0] l_w;                          // the lowest-numbered MOB shown here
    always_comb begin
        l_w = 3'd0;
        for (int i = 7; i >= 0; i--)
            if (l_hit[i]) l_w = 3'(i);
    end
    wire logic [13:0] l_a  = r[{3'b010, l_w}];
    // the background pixel is "on": a card pixel (not under the delays)
    wire logic fg_on = yy_l >= 0 && xp >= $signed({9'd0, hd}) && (pf_b ? lb_q[17] : lb_q[16]);
    wire logic mob_show = l_hit != 8'd0 && !(l_a[13] && fg_on);
    wire logic coll_area = en_l && vcnt >= (cbr[1] ? 9'(PF_LINE + 16) : 9'(PF_LINE))
                        && vcnt <= 9'(PF_LINE + 191)
                        && xp >= $signed({8'd0, cbr[0] ? 4'd8 : 4'd0}) && xp <= 12'sd158;
    wire logic [7:0] l_bg = coll_area && fg_on ? l_b & l_intr : 8'd0;

    // ---------------------------------------------------------- the RAMs
    logic [31:0] ssr_row, ssr_line;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [13:0] rb_qa;                       // port A reads: the state port's only
    logic [17:0] lb_qa;
    /* verilator lint_on UNUSEDSIGNAL */

    intv_ram #(.AW(5), .DW(14), .WORDS(20), .SS_ID(SS_ROW)) rowbuf (
        .clk, .addr(cp_j), .we(rb_we), .d(cp_w), .q(rb_qa),
        .addr_b(ec[4:0]), .q_b(w),
        .ss_en, .ss_addr, .ss_we, .ss_wdata, .ss_rdata(ssr_row));

    intv_ram #(.AW(6), .DW(18), .WORDS(64), .SS_ID(SS_LINE)) linebuf (
        .clk, .addr({tl[0], ec[4:0]}), .we(lb_we), .d({e_on, e_bits, e_fg, e_bg}), .q(lb_qa),
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
            {en_l, vdr_l} <= 4'd0;
            {cp_arm, cp_on, cp_ph} <= 3'd0;
            {cs, cs_row} <= 4'd0;
            pix <= 4'd0;
            {g_on, g_f, g_ph, g_m, g_j, g_ly} <= '0;
            for (int i = 0; i < 8; i++) begin
                gm[i] <= 16'd0; rm[i] <= 16'd0; coll_p[i] <= 10'd0;
            end
        end else if (ss_we && ss_hit) begin
            if (ss_w < 8'(NREG))
                r[ss_w[5:0]] <= ss_wdata[13:0] & keep(ss_w[5:0]);
            else unique case (ss_w)
                8'h33: {hs, csmode} <= ss_wdata[1:0];
                8'h34: {vdr_l, en_l} <= ss_wdata[3:0];
                8'h35: {cp_ph, cp_j, cp_on, cp_arm, cnt} <= ss_wdata[16:0];
                8'h36: {pix, cs_row, cs} <= ss_wdata[7:0];
                8'h37: {g_on, g_ph, g_f, g_j, g_m, g_ly} <= ss_wdata[17:0];
                8'h38, 8'h39, 8'h3A, 8'h3B: {gm[{ss_w[1:0], 1'b1}], gm[{ss_w[1:0], 1'b0}]} <= ss_wdata;
                8'h3C, 8'h3D, 8'h3E, 8'h3F: {rm[{ss_w[1:0], 1'b1}], rm[{ss_w[1:0], 1'b0}]} <= ss_wdata;
                8'h40: {coll_p[2], coll_p[1], coll_p[0]} <= ss_wdata[29:0];
                8'h41: {coll_p[5], coll_p[4], coll_p[3]} <= ss_wdata[29:0];
                8'h42: {coll_p[7], coll_p[6]} <= ss_wdata[19:0];
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
            end

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
                pix <= pf_line && pf_x ? (mob_show ? {l_a[12], l_a[2:0]} : pf_c) : bcr;

            // MOBs: the next line's masks
            if (ce_pix && rf_win)
                rm[hm[2:0]] <= u_mask;
            // background collisions
            if (ce_pix)
                for (int i = 0; i < 8; i++)
                    if (l_bg[i]) coll_p[i][8] <= 1'b1;
            // the collision sweep
            if (win_end && hs_eff) begin
                {g_on, g_f, g_ph} <= 3'b110;
                g_m  <= 3'd0;
                g_ly <= 9'd8;
            end else if (live && g_on) begin
                if (g_f) begin
                    if (!g_ph)
                        g_ph <= 1'b1;
                    else if (g_ok) begin
                        g_ph <= 1'b0;
                        gm[g_m] <= u_x[8] ? u_mask : 16'd0;
                        if (u_x[8] && g_bord)
                            coll_p[g_m][9] <= 1'b1;
                        if (g_m == 3'd7) begin
                            g_f <= 1'b0;
                            g_m <= 3'd0;
                            g_j <= 3'd1;
                        end else
                            g_m <= g_m + 3'd1;
                    end
                end else begin
                    if (p_hit) begin
                        coll_p[g_m][{1'b0, g_j}] <= 1'b1;
                        coll_p[g_j][{1'b0, g_m}] <= 1'b1;
                    end
                    if (g_j != 3'd7)
                        g_j <= g_j + 3'd1;
                    else if (g_m != 3'd6) begin
                        g_m <= g_m + 3'd1;
                        g_j <= g_m + 3'd2;
                    end else begin
                        g_f <= 1'b1;
                        g_m <= 3'd0;
                        g_ly <= g_ly + 9'd1;
                        if (g_last)
                            g_on <= 1'b0;
                    end
                end
            end
            // the frame's end: the gathered bits into $18-$1F (sticky)
            if (frame_end) begin
                for (int i = 0; i < 8; i++) begin
                    r[6'h18 + 6'(i)] <= r[6'h18 + 6'(i)] | (14'(coll_p[i]) & keep(6'h18 + 6'(i)));
                    coll_p[i] <= 10'd0;
                end
                g_on <= 1'b0;
            end
        end
    end

    always_comb begin
        ss_rdata = ssr_row | ssr_line;
        if (ss_hit) begin
            if (ss_w < 8'(NREG))
                ss_rdata = {18'd0, r[ss_w[5:0]]};
            else unique case (ss_w)
                8'h33: ss_rdata = {30'd0, hs, csmode};
                8'h34: ss_rdata = {28'd0, vdr_l, en_l};
                8'h35: ss_rdata = {15'd0, cp_ph, cp_j, cp_on, cp_arm, cnt};
                8'h36: ss_rdata = {24'd0, pix, cs_row, cs};
                8'h37: ss_rdata = {14'd0, g_on, g_ph, g_f, g_j, g_m, g_ly};
                8'h38, 8'h39, 8'h3A, 8'h3B: ss_rdata = {gm[{ss_w[1:0], 1'b1}], gm[{ss_w[1:0], 1'b0}]};
                8'h3C, 8'h3D, 8'h3E, 8'h3F: ss_rdata = {rm[{ss_w[1:0], 1'b1}], rm[{ss_w[1:0], 1'b0}]};
                8'h40: ss_rdata = {2'd0, coll_p[2], coll_p[1], coll_p[0]};
                8'h41: ss_rdata = {2'd0, coll_p[5], coll_p[4], coll_p[3]};
                8'h42: ss_rdata = {12'd0, coll_p[7], coll_p[6]};
                default: ;
            endcase
        end
    end

    /* verilator lint_off UNUSEDSIGNAL */
    wire logic [33:0] unused = {xx[11:8], ec[8:5], hm[8:3], u_x[13:11], u_x[9], u_y[13:12],
                                u_a[13:12], u_a[2:0], l_a[11:3]};
    /* verilator lint_on UNUSEDSIGNAL */

    initial begin
        if (H_TOTAL % 4 != 0 || PF_X0 < 14 || PF_X0 + 160 > H_TOTAL || E0 + 20 > H_TOTAL
            || MF < PF_X0 + 159 || MF + 9 > H_TOTAL || E0 < 1 || PF_LINE + 192 != V_TOTAL)
            $error("intv_stic: parameter out of range");
    end

endmodule

`default_nettype wire
