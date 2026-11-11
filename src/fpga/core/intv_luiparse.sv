// Intellivision core: the LTO Flash LUIGI parser (1.0.7; docs/CARTFORMATS.md 8). A
// byte-at-a-time state machine, the same as tools/mapper/cartfmt.py LuiParser, written from
// the format's specification ("Locutus Universal Intellivision Game Image (LUIGI) V1.0",
// J. Zbiciak, Left Turn Only, 6-Jul-2019; no code read). The loader starts it after byte 3,
// when bytes 0-3 are "LTO" and version 0 or 1; it gets every byte from offset 4.
//
//   header   flags (bytes 4-8 kept: flag bits 39:0), the UID and reserved bytes, the
//            header's DOWCRC as its last byte (byte 15 or 31)
//   blocks   type, payload length (little endian), DOWCRC over those three bytes, CRC32/4
//            over the payload (4 bytes, little endian), the payload; type $FF ends the file
//            $00 encryption: refused; $01 the tables (1,280 bytes, once, before any data):
//            kept in three RAMs (memory map 256 x 16, permissions 256 x 8, page flips
//            256 x 16) the loader reads at the finish; $02 a data hunk: a 24-bit Locutus
//            word address, then the packed words (8-bit, 10-bit and 16-bit blocks); $03
//            metadata and other types: skipped
//   words    a word below Locutus $10000 goes to plane 1 at its own address; with JLP,
//            $10000-$11FFF (Locutus' JLP RAM) is dropped; above, each Locutus 4K page takes
//            a free 4K page of plane 1 as its first word comes (highest first; free: no
//            mapped paragraph or page flip of the tables points there, no data below
//            $10000 wrote there; none with bankswitching). Out: w_v, w_sa (the plane-1
//            word), w_d, two clocks after the byte that made the word.
// DOWCRC: poly $98, right shifting, init 0. CRC32/4: poly $82F63B78, right shifting, init 0.
// The first error stops the parser (err, err_off: the offset of the byte that set it); the
// loader decides at the finish with the file length (the bridge's pad bytes are parsed like
// any others: what they set does not count).
//
// Load-time only: nothing here is machine state.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_luiparse (
    input  wire logic        clk,
    input  wire logic        start,           // byte 3 said LUIGI
    input  wire logic        ver,             // its version (0 or 1)
    input  wire logic        in_v,            // bytes from offset 4
    input  wire logic [23:0] in_off,
    input  wire logic [7:0]  in_c,

    output logic             w_v,             // a data word for plane 1
    output logic [15:0]      w_sa,
    output logic [15:0]      w_d,

    // the tables at the finish (one clock reads)
    input  wire logic [7:0]  t_p,             // memory map and permissions: paragraph
    output logic [15:0]      t_mmap,
    output logic [7:0]       t_perm,
    input  wire logic [7:0]  t_f,             // page flips: chapter * 16 + page
    output logic [15:0]      t_flip,
    input  wire logic [6:0]  t_pg,            // Locutus 4K page -> plane-1 page
    output logic [4:0]       t_alloc,         // {given, page}

    output logic [39:0]      flags,           // header flag bits 39:0
    output logic [7:0]       err,
    output logic [24:0]      err_off,
    output logic             hdr_open,        // still in the header
    output logic             in_blk,          // inside a block (header or payload)
    output logic [24:0]      blk_start,       // the offset of the current block's type byte
    output logic             tab_seen,
    output logic [15:0]      pfe,             // 4K ranges with page flipping
    output logic             bsw,             // a paragraph with B
    output logic             nonid            // a mapped paragraph not at its own Locutus address
);

    localparam logic [7:0] E_HDR = 8'h28, E_BHDR = 8'h29, E_PCRC = 8'h2A, E_ENC = 8'h2B, E_TAB = 8'h2C,
                           E_ORDER = 8'h2D, E_HUNK = 8'h2E, E_FULL = 8'h31, E_CLASH = 8'h32;

    typedef enum logic [3:0] {
        L_IDLE, L_HDR, L_BT, L_L0, L_L1, L_HC, L_P0, L_P1, L_P2, L_P3, L_PAY, L_DONE
    } lst_t;
    typedef enum logic [3:0] {
        H_A0, H_A1, H_A2, H_S, H_8, H_T, H_L, H_W0, H_W1, H_X0, H_X1
    } hst_t;

    function automatic logic [7:0] dow(input logic [7:0] cin, input logic [7:0] d);
        logic [7:0] r;
        r = cin ^ d;
        for (int i = 0; i < 8; i++)
            r = r[0] ? (r >> 1) ^ 8'h98 : r >> 1;
        return r;
    endfunction
    function automatic logic [31:0] c324(input logic [31:0] cin, input logic [7:0] d);
        logic [31:0] r;
        r = cin ^ {24'd0, d};
        for (int i = 0; i < 8; i++)
            r = r[0] ? (r >> 1) ^ 32'h82F63B78 : r >> 1;
        return r;
    endfunction
    // dow over "LTO" and the version byte
    function automatic logic [7:0] dow_hdr(input logic v);
        return dow(dow(dow(dow(8'd0, 8'h4C), 8'h54), 8'h4F), {7'd0, v});
    endfunction

    // ---- the tables
    logic [15:0] mmap_r [256];
    logic [7:0]  perm_r [256];
    logic [15:0] flip_r [256];
    logic [3:0]  alloc_r [128];
    logic [127:0] alloc_v = 128'd0;           // the Locutus page has its plane-1 page
    logic        mm_we, pm_we, fl_we, al_we;
    logic [7:0]  mm_a, pm_a, fl_a;
    logic [6:0]  al_a;
    logic [15:0] mm_d, fl_d;
    logic [7:0]  pm_d;
    logic [3:0]  al_d;
    logic [15:0] mm_q;
    logic [3:0]  al_q;
    logic        av_q;
    logic [7:0]  mm_ra;
    logic [6:0]  al_ra;
    always_ff @(posedge clk) begin
        if (mm_we) mmap_r[mm_a] <= mm_d;
        if (pm_we) perm_r[pm_a] <= pm_d;
        if (fl_we) flip_r[fl_a] <= fl_d;
        if (al_we) alloc_r[al_a] <= al_d;
        mm_q   <= mmap_r[mm_ra];
        t_perm <= perm_r[t_p];
        t_flip <= flip_r[t_f];
        al_q   <= alloc_r[al_ra];
        av_q   <= alloc_v[al_ra];
    end
    assign t_mmap  = mm_q;
    assign t_alloc = {av_q, al_q};

    lst_t        st = L_IDLE;
    hst_t        h = H_A0;
    logic        v1 = 1'b0;
    logic [7:0]  hcrc = 8'd0, bh = 8'd0, t = 8'd0, lo = 8'd0, top = 8'd0;
    logic [15:0] len = 16'd0, i = 16'd0;
    logic [31:0] pc = 32'd0, crc = 32'd0;
    logic [18:0] a = 19'd0;
    logic [6:0]  n = 7'd0;
    logic [2:0]  g = 3'd0, j = 3'd0;
    logic [15:0] used = 16'd0, loww = 16'd0, hiu = 16'd0;
    // the perm byte waiting for its paragraph's map entry (one clock)
    logic        pq_v = 1'b0;
    logic [7:0]  pq_p = 8'd0;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [7:0]  pq_c = 8'd0;                   // (R, W and B used)
    /* verilator lint_on UNUSEDSIGNAL */
    // a decoded word: stage 1 (w1), stage 2 waits for the alloc read (w2)
    logic        w1_v = 1'b0, w2_v = 1'b0;
    logic [18:0] w1_a = 19'd0, w2_a = 19'd0;
    logic [15:0] w1_d = 16'd0, w2_d = 16'd0;
    logic [24:0] w1_o = 25'd0, w2_o = 25'd0;

    initial begin
        w_v = 1'b0; w_sa = 16'd0; w_d = 16'd0; flags = 40'd0; err = 8'd0; err_off = 25'd0;
        blk_start = 25'd0; tab_seen = 1'b0; pfe = 16'd0; bsw = 1'b0; nonid = 1'b0;
    end
    assign hdr_open = st == L_HDR || st == L_IDLE;
    assign in_blk   = st != L_BT && st != L_DONE && st != L_HDR && st != L_IDLE;

    wire logic [7:0] hl1 = v1 ? 8'd31 : 8'd15;           // the header's last byte
    // a permissions byte reads its paragraph's map entry; a word its Locutus page's plane-1 page
    assign mm_ra = (in_v && st == L_PAY && t == 8'h01) ? i[7:0] : t_p;
    assign al_ra = w1_v ? w1_a[18:12] : t_pg;
    wire logic       jlp = flags[17:16] != 2'd0;
    // the highest free plane-1 page
    wire logic [15:0] free = ~(used | loww | hiu);
    logic [3:0] fpp;
    always_comb begin
        fpp = 4'd0;
        for (int k = 0; k < 16; k++)
            if (free[k]) fpp = 4'(k);
    end

    always_ff @(posedge clk) begin
        logic        emit;
        logic [15:0] ew;
        mm_we <= 1'b0; pm_we <= 1'b0; fl_we <= 1'b0; al_we <= 1'b0;
        w_v  <= 1'b0;
        emit = 1'b0;
        ew   = 16'd0;

        if (start) begin
            st <= L_HDR; v1 <= ver; hcrc <= dow_hdr(ver); flags <= 40'd0; err <= 8'd0; err_off <= 25'd0;
            blk_start <= 25'd0; tab_seen <= 1'b0; pfe <= 16'd0; bsw <= 1'b0; nonid <= 1'b0;
            used <= 16'd0; loww <= 16'd0; hiu <= 16'd0; pq_v <= 1'b0; w1_v <= 1'b0; w2_v <= 1'b0;
            alloc_v <= 128'd0;
        end

        // ---- a permissions byte: its paragraph's map entry was read the clock before
        pq_v <= 1'b0;
        if (pq_v) begin
            if (pq_c[1:0] != 2'd0 && mm_q[10:8] == 3'd0) used[mm_q[7:4]] <= 1'b1;   // (19-bit Locutus addresses)
            if (pq_c[3]) bsw <= 1'b1;
            if (pq_c[1:0] != 2'd0 && mm_q != {8'd0, pq_p}) nonid <= 1'b1;
        end

        // ---- the word pipeline: w1 -> read alloc -> w2 decides
        w2_v <= w1_v;
        w2_a <= w1_a; w2_d <= w1_d; w2_o <= w1_o;
        w1_v <= 1'b0;
        if (w2_v && err == 8'd0) begin
            if (w2_a < 19'h10000) begin
                if (hiu[w2_a[15:12]]) begin
                    err <= E_CLASH; err_off <= w2_o;
                end else begin
                    loww[w2_a[15:12]] <= 1'b1;
                    w_v <= 1'b1; w_sa <= w2_a[15:0]; w_d <= w2_d;
                end
            end else if (jlp && w2_a < 19'h12000) begin
                // Locutus' JLP RAM: the JLP's own
            end else if (av_q) begin
                w_v <= 1'b1; w_sa <= {al_q, w2_a[11:0]}; w_d <= w2_d;
            end else if (bsw || free == 16'd0) begin
                err <= E_FULL; err_off <= w2_o;
            end else begin
                al_we <= 1'b1; al_a <= w2_a[18:12]; al_d <= fpp;
                alloc_v[w2_a[18:12]] <= 1'b1;
                hiu[fpp] <= 1'b1;
                w_v <= 1'b1; w_sa <= {fpp, w2_a[11:0]}; w_d <= w2_d;
            end
        end

        if (in_v && err == 8'd0) begin
            case (st)
                L_HDR: begin
                    if (in_off < 24'd9) flags[8 * (in_off[2:0] - 3'd4) +: 8] <= in_c;
                    if (in_off[7:0] == hl1 && in_off[23:8] == 16'd0) begin
                        if (in_c != hcrc) begin err <= E_HDR; err_off <= {1'b0, in_off}; end
                        else st <= L_BT;
                    end else
                        hcrc <= dow(hcrc, in_c);
                end
                L_BT: begin
                    blk_start <= {1'b0, in_off};
                    if (in_c == 8'hFF) st <= L_DONE;
                    else begin t <= in_c; bh <= dow(8'd0, in_c); st <= L_L0; end
                end
                L_L0: begin len[7:0] <= in_c; bh <= dow(bh, in_c); st <= L_L1; end
                L_L1: begin len[15:8] <= in_c; bh <= dow(bh, in_c); st <= L_HC; end
                L_HC: begin
                    if (in_c != bh)                                          begin err <= E_BHDR;  err_off <= {1'b0, in_off}; end
                    else if (t == 8'h00)                                     begin err <= E_ENC;   err_off <= {1'b0, in_off}; end
                    else if (t == 8'h01 && (len != 16'd1280 || tab_seen))    begin err <= E_TAB;   err_off <= {1'b0, in_off}; end
                    else if (t == 8'h02 && !tab_seen)                        begin err <= E_ORDER; err_off <= {1'b0, in_off}; end
                    else st <= L_P0;
                end
                L_P0: begin pc[7:0]   <= in_c; st <= L_P1; end
                L_P1: begin pc[15:8]  <= in_c; st <= L_P2; end
                L_P2: begin pc[23:16] <= in_c; st <= L_P3; end
                L_P3: begin
                    crc <= 32'd0;
                    i   <= 16'd0;
                    h   <= H_A0;
                    if (len == 16'd0) begin
                        if ({in_c, pc[23:0]} != 32'd0) begin err <= E_PCRC; err_off <= {1'b0, in_off}; end
                        else if (t == 8'h02)           begin err <= E_HUNK; err_off <= {1'b0, in_off}; end
                        else st <= L_BT;
                    end else begin
                        pc[31:24] <= in_c;
                        st <= L_PAY;
                    end
                end
                L_PAY: begin
                    logic        herr;
                    logic [31:0] c2;
                    herr = 1'b0;
                    c2 = c324(crc, in_c);
                    crc <= c2;
                    // the tables
                    if (t == 8'h01) begin
                        if (i < 16'd512) begin
                            if (i[0]) begin mm_we <= 1'b1; mm_a <= i[8:1]; mm_d <= {in_c, lo}; end
                            else lo <= in_c;
                        end else if (i < 16'd768) begin
                            pm_we <= 1'b1; pm_a <= i[7:0]; pm_d <= in_c;
                            pq_v <= 1'b1; pq_p <= i[7:0]; pq_c <= in_c;
                        end else begin
                            logic [7:0] fk;
                            fk = 8'((i - 16'd768) >> 1);
                            if (i[0]) begin
                                fl_we <= 1'b1; fl_a <= fk; fl_d <= {in_c, lo};
                                if (lo[3]) pfe[fk[7:4]] <= 1'b1;
                                if (lo[1:0] != 2'd0 && in_c[2:0] == 3'd0) used[lo[7:4]] <= 1'b1;
                            end else
                                lo <= in_c;
                        end
                    end
                    // a data hunk
                    if (t == 8'h02) begin
                        case (h)
                            H_A0: begin a[7:0] <= in_c; h <= H_A1; end
                            H_A1: begin a[15:8] <= in_c; h <= H_A2; end
                            H_A2: begin a[18:16] <= in_c[2:0]; h <= H_S; end
                            H_S: begin
                                if (in_c >= 8'h01 && in_c <= 8'h3F) begin
                                    n <= 7'(in_c - 8'd1);
                                    h <= in_c == 8'h01 ? H_W0 : H_8;
                                end else if (in_c >= 8'h40 && in_c <= 8'hBF) begin
                                    n <= 7'(in_c - 8'h40);
                                    h <= in_c == 8'h40 ? H_W0 : H_T;
                                end else if (in_c >= 8'hC0 && in_c <= 8'hFD) begin
                                    n <= 7'(in_c - 8'hBF);
                                    h <= H_X0;
                                end else
                                    herr = 1'b1;
                            end
                            H_8: begin
                                emit = 1'b1; ew = {8'd0, in_c};
                                n <= n - 7'd1;
                                if (n == 7'd1) h <= H_W0;
                            end
                            H_T: begin
                                top <= in_c;
                                g <= n > 7'd4 ? 3'd4 : n[2:0];
                                j <= 3'd0;
                                h <= H_L;
                            end
                            H_L: begin
                                emit = 1'b1;
                                ew = {6'd0, j == 3'd0 ? top[7:6] : j == 3'd1 ? top[5:4] : j == 3'd2 ? top[3:2] : top[1:0], in_c};
                                j <= j + 3'd1;
                                n <= n - 7'd1;
                                if (j + 3'd1 == g) h <= n == 7'd1 ? H_W0 : H_T;
                            end
                            H_W0, H_X0: begin lo <= in_c; h <= h == H_W0 ? H_W1 : H_X1; end
                            H_W1: begin emit = 1'b1; ew = {in_c, lo}; h <= H_S; end
                            H_X1: begin
                                emit = 1'b1; ew = {in_c, lo};
                                n <= n - 7'd1;
                                h <= n == 7'd1 ? H_S : H_X0;
                            end
                            default: ;
                        endcase
                    end
                    if (emit) begin
                        w1_v <= 1'b1; w1_a <= a; w1_d <= ew; w1_o <= {1'b0, in_off};
                        a <= a + 19'd1;
                    end
                    i <= i + 16'd1;
                    if (herr) begin
                        err <= E_HUNK; err_off <= {1'b0, in_off};
                    end else if (i + 16'd1 == len) begin
                        if (c2 != pc) begin err <= E_PCRC; err_off <= {1'b0, in_off}; end
                        else if (t == 8'h02 && !(h == H_A2 || h == H_W1 || (h == H_X1 && n == 7'd1)))
                            begin err <= E_HUNK; err_off <= {1'b0, in_off}; end
                        else begin
                            if (t == 8'h01) tab_seen <= 1'b1;
                            st <= L_BT;
                        end
                    end
                end
                default: ;
            endcase
        end
    end

endmodule

`default_nettype wire
