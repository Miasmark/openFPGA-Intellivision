// Intellivision core: the Intellicart .rom parser (DESIGN.md 5.4; build
// step 8; docs/CARTFORMATS.md 3). A byte-at-a-time state machine, the same
// as tools/mapper/cartfmt.py RomParser. The loader starts it after byte 2,
// when bytes 0-2 are $A8, n, ~n (n > 0); it gets every byte from offset 3.
//
//   segments   lo, hi (256-word Intellicart pages, hi >= lo), the words
//              (high byte first), CRC-16 (high byte first) over lo, hi and
//              the data: each word goes out (w_v, w_a = the Intellicart
//              address, w_d) and its 256-word block is marked covered
//   tables     16 bytes of access nibbles (R 1, W 2, N 4, B 8; the upper
//              2K of a 4K range in the high nibble), 32 bytes of fine
//              ranges [0lll 0hhh] (lower 2K windows first), CRC-16; kept
//              in a 64 x 8 RAM the loader reads at the finish (t_ra, t_q)
//   tags       length (1-4 bytes), type, body, CRC-16, until a NUL tag
//              (jzIntv doc/rom_fmt/id_tag.txt); the first compat tag ($06,
//              at least 3 bytes) with a good CRC is kept with its end
//              offset
// CRC-16: poly $1021, init $FFFF, MSB first (Intellicart manual). A bad
// segment or table CRC, or a segment whose end is below its start, refuses
// the image (err). Whether the file is long enough is decided at the
// finish, when the length is known (the bridge's pad bytes are parsed like
// any others): the tables must end inside it (tab_end), and the compat tag
// counts only if it does too (cmp_end).
//
// Load-time only: nothing here is machine state.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_romparse (
    input  wire logic        clk,
    input  wire logic        start,           // byte 2 said .rom: n segments
    input  wire logic [7:0]  nseg,
    input  wire logic        in_v,            // bytes from offset 3
    input  wire logic [23:0] in_off,
    input  wire logic [7:0]  in_c,

    output logic             w_v,             // a segment word
    output logic [15:0]      w_a,
    output logic [15:0]      w_d,

    input  wire logic [5:0]  t_ra,            // tables: 0-15 access, 16-47 fine
    output logic [7:0]       t_q,

    output logic [7:0]       err,             // 0, or $20 range, $21 segment CRC, $23 table CRC
    output logic [24:0]      err_off,         // the offset of the byte that set err
    output logic             tab_done,
    output logic [24:0]      tab_end,         // offset after the tables' CRC
    output logic             cmp_ok,
    output logic [24:0]      cmp_end,
    output logic [39:0]      cmp_body         // bytes 0-4, byte 0 in [39:32]
);

    typedef enum logic [4:0] {
        R_IDLE, R_LO, R_HI, R_DATA, R_CRC1, R_CRC2, R_TAB, R_TCRC1, R_TCRC2,
        R_TLEN, R_TLENX, R_TTYPE, R_TBODY, R_TC1, R_TC2, R_DONE, R_ERR
    } rst_t;

    rst_t        st = R_IDLE;
    logic [7:0]  segs = 8'd0, seg = 8'd0, lo = 8'd0, hb = 8'd0, got = 8'd0, ttype = 8'd0;
    logic [15:0] crc = 16'hFFFF;
    logic [17:0] i = 18'd0, n = 18'd0;
    logic [5:0]  ti = 6'd0;
    logic [29:0] tlen = 30'd0;
    logic [1:0]  tnb = 2'd0, tk = 2'd0;
    logic [2:0]  bi = 3'd0;
    logic [39:0] body = 40'd0;

    logic [7:0]  tab [64];
    always_ff @(posedge clk) t_q <= tab[t_ra];

    initial begin
        w_v = 1'b0; w_a = 16'd0; w_d = 16'd0; err = 8'd0; err_off = 25'd0; tab_done = 1'b0; tab_end = 25'd0;
        cmp_ok = 1'b0; cmp_end = 25'd0; cmp_body = 40'd0;
    end

    function automatic logic [15:0] crc16(input logic [15:0] cin, input logic [7:0] d);
        logic [15:0] r;
        r = cin ^ {d, 8'd0};
        for (int b = 0; b < 8; b++)
            r = r[15] ? (r << 1) ^ 16'h1021 : r << 1;
        return r;
    endfunction
    wire logic [15:0] crc_c   = crc16(crc, in_c);         // CRC so far with this byte
    wire logic [15:0] crc_new = crc16(16'hFFFF, in_c);    // a new CRC from this byte
    wire logic [24:0] off1    = {1'b0, in_off} + 25'd1;

    always_ff @(posedge clk) begin
        w_v <= 1'b0;
        if (start) begin
            st <= R_LO; segs <= nseg; seg <= 8'd0; err <= 8'd0; tab_done <= 1'b0;
            cmp_ok <= 1'b0;
        end else if (in_v) begin
            unique case (st)
                R_LO: begin
                    lo <= in_c;
                    crc <= crc_new;
                    st <= R_HI;
                end
                R_HI: begin
                    crc <= crc_c;
                    if (in_c < lo) begin
                        err <= 8'h20;
                        err_off <= {1'b0, in_off};
                        st <= R_ERR;
                    end else begin
                        n <= 18'(9'(in_c - lo) + 9'd1) << 9;
                        i <= 18'd0;
                        st <= R_DATA;
                    end
                end
                R_DATA: begin
                    crc <= crc_c;
                    if (!i[0])
                        hb <= in_c;
                    else begin
                        w_v <= 1'b1;
                        w_a <= {lo, 8'd0} + i[16:1];
                        w_d <= {hb, in_c};
                    end
                    i <= i + 18'd1;
                    if (i + 18'd1 == n) st <= R_CRC1;
                end
                R_CRC1: begin got <= in_c; st <= R_CRC2; end
                R_CRC2:
                    if ({got, in_c} != crc) begin
                        err <= 8'h21;
                        err_off <= {1'b0, in_off};
                        st <= R_ERR;
                    end else if (seg + 8'd1 == segs) begin
                        seg <= seg + 8'd1;
                        crc <= 16'hFFFF;
                        ti  <= 6'd0;
                        st  <= R_TAB;
                    end else begin
                        seg <= seg + 8'd1;
                        st  <= R_LO;
                    end
                R_TAB: begin
                    tab[ti] <= in_c;
                    crc <= crc_c;
                    ti <= ti + 6'd1;
                    if (ti == 6'd47) st <= R_TCRC1;
                end
                R_TCRC1: begin got <= in_c; st <= R_TCRC2; end
                R_TCRC2:
                    if ({got, in_c} != crc) begin
                        err <= 8'h23;
                        err_off <= {1'b0, in_off};
                        st <= R_ERR;
                    end else begin
                        tab_done <= 1'b1;
                        tab_end  <= off1;
                        st <= R_TLEN;
                    end
                R_TLEN:
                    if (in_c == 8'd0)
                        st <= R_DONE;                       // the NUL tag
                    else begin
                        crc  <= crc_new;
                        tlen <= {24'd0, in_c[5:0]};
                        tnb  <= in_c[7:6];
                        tk   <= 2'd0;
                        st   <= in_c[7:6] != 2'd0 ? R_TLENX : R_TTYPE;
                    end
                R_TLENX: begin
                    crc <= crc_c;
                    case (tk)
                        2'd0: tlen[13:6]  <= in_c;
                        2'd1: tlen[21:14] <= in_c;
                        default: tlen[29:22] <= in_c;
                    endcase
                    tk <= tk + 2'd1;
                    if (tk + 2'd1 == tnb) st <= R_TTYPE;
                end
                R_TTYPE: begin
                    crc <= crc_c;
                    ttype <= in_c;
                    bi <= 3'd0;
                    body <= 40'd0;
                    st <= tlen != 30'd0 ? R_TBODY : R_TC1;
                end
                R_TBODY: begin
                    crc <= crc_c;
                    if (bi < 3'd5) begin
                        body[39 - 8*bi -: 8] <= in_c;
                        bi <= bi + 3'd1;
                    end
                    tlen <= tlen - 30'd1;
                    if (tlen == 30'd1) st <= R_TC1;
                end
                R_TC1: begin got <= in_c; st <= R_TC2; end
                R_TC2: begin
                    if ({got, in_c} == crc && ttype == 8'h06 && bi >= 3'd3 && !cmp_ok) begin
                        cmp_ok   <= 1'b1;
                        cmp_end  <= off1;
                        cmp_body <= body;
                    end
                    st <= R_TLEN;
                end
                default: ;                                  // R_IDLE, R_DONE, R_ERR
            endcase
        end
    end

endmodule

`default_nettype wire
