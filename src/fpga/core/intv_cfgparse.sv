// Intellivision core: the BIN+CFG text parser (DESIGN.md 5.3; build step 8;
// docs/CARTFORMATS.md 2). A byte-at-a-time state machine, the same as
// tools/mapper/cartfmt.py CfgParser (states, limits, error codes): the
// loader feeds it the CFG slot's bytes (three bytes behind the stream, so
// the bridge's pad bytes after the file's end are never parsed; the last
// ones at the finish, when the data table gives the length), then end.
//
// Grammar: lines end at LF; CR, tab and space are blanks; ';' starts a
// comment; '[name]' at the start of a line selects a section (lower-case
// compare; text after ']' ignored); a NUL byte ends the text.
//   [mapping]    lo - hi = addr [PAGE p]   file words lo..hi at addr
//   [preload]    lo - hi = addr            Intellicart memory only
//   [memattr]    lo - hi = RAM|WOM|ROM [8|16]
//   [bankswitch] lo - hi                   Intellicart bank windows
//   [vars]       name = decimal            ecs, ecs_compat, voice,
//                voice_compat, jlp, jlp_accel, jlp_flash, jlpflash (sic:
//                IntyBASIC's), lto_mapper (others and other values ignored;
//                values saturate at 255). jlp / jlp_accel and jlp_flash /
//                jlpflash: the first one counts (f_jlp_mode, f_jlp_flash with
//                their "given" bits; build step 11, docs/JLP_NOTES.md 1.1)
// Numbers are hex, '$' optional, at most 20 bits. Anything else in the four
// map sections refuses the CFG (err); lines before the first section, in
// [macro] and in unknown sections are ignored. At most 32 ranges.
//
// Each complete map line becomes a range (rng_we, rng_idx, rng_d):
//   [58:56] kind (1 mapping, 2 preload, 3 memattr, 4 bankswitch)
//   [55] PAGE given, [54:51] page, [50:48] attr (memattr: R 1, W 2, N 4)
//   [47:32] lo, [31:16] hi (CPU / Intellicart addresses), [15:0] src
//   (mapping, preload: the file offset of lo)
//
// Load-time only: nothing here is machine state.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_cfgparse (
    input  wire logic        clk,
    input  wire logic        clr,             // a new CFG stream (its byte 0)
    input  wire logic        in_v,
    input  wire logic [7:0]  in_c,
    input  wire logic        in_end,          // end of text: a last LF

    output logic             rng_we,
    output logic [4:0]       rng_idx,
    output logic [58:0]      rng_d,
    output logic [5:0]       nrng,
    output logic [7:0]       err,
    output logic             f_ecs,
    output logic             f_ecs_off,
    output logic             f_voice,
    output logic             f_jlp,
    output logic [1:0]       f_jlp_mode,      // min(value, 3) of the first jlp / jlp_accel
    output logic             f_jlp_mset,
    output logic [7:0]       f_jlp_flash,     // the first jlp_flash / jlpflash
    output logic             f_jlp_fset
);

    localparam logic [7:0] E_SYNTAX = 8'h10, E_MANY = 8'h11, E_RANGE = 8'h12, E_PAGE = 8'h13,
                           E_MIX = 8'h14, E_LTO = 8'h15;
    localparam logic [2:0] S_NONE = 3'd0, S_MAP = 3'd1, S_PRE = 3'd2, S_MEM = 3'd3, S_BSW = 3'd4,
                           S_VARS = 3'd5, S_SKIP = 3'd6;

    typedef enum logic [4:0] {
        P_BOL, P_SKIP, P_HDR, P_N0D, P_N0, P_DASH, P_N1S, P_N1D, P_N1, P_AFT1, P_N2S, P_N2D,
        P_N2, P_AFT2, P_PG, P_PGWS1, P_PGWS, P_PGD, P_KWS, P_KW, P_KWWS, P_WID, P_END,
        P_VNAME, P_VEQ, P_VVAL0, P_VVAL, P_VEND, P_DEAD
    } pst_t;

    pst_t        st = P_BOL;
    logic [2:0]  sec = S_NONE;
    logic        ended = 1'b0;
    logic [95:0] name = 96'd0;                // up to 12 characters, first in [95:88]
    logic [3:0]  nlen = 4'd0;
    logic        nover = 1'b0;
    logic [19:0] num0 = 20'd0, num1 = 20'd0, num2 = 20'd0;
    logic        ovf = 1'b0;
    logic [3:0]  page = 4'd0;
    logic [4:0]  pagex = 5'd0;               // page digits so far (> 15: refused)
    logic        haspage = 1'b0;
    logic [2:0]  attr = 3'd0;
    logic [1:0]  k = 2'd0;
    logic [7:0]  val = 8'd0;
    logic        has_page = 1'b0, has_bsw = 1'b0;

    initial begin
        rng_we = 1'b0; rng_idx = 5'd0; rng_d = 59'd0; nrng = 6'd0; err = 8'd0;
        f_ecs = 1'b0; f_ecs_off = 1'b0; f_voice = 1'b0; f_jlp = 1'b0;
        f_jlp_mode = 2'd0; f_jlp_mset = 1'b0; f_jlp_flash = 8'd0; f_jlp_fset = 1'b0;
    end

    // ------------------------------------------------------- characters
    wire logic        go = (in_v && !ended) || in_end;
    wire logic [7:0]  c  = in_end ? 8'h0A : in_c;
    wire logic        ws = c == 8'h20 || c == 8'h09 || c == 8'h0D;
    wire logic        lf = c == 8'h0A;
    wire logic        semi = c == 8'h3B;
    wire logic [7:0]  lc = (c >= 8'h41 && c <= 8'h5A) ? c | 8'h20 : c;
    wire logic        isdig = c >= 8'h30 && c <= 8'h39;
    wire logic        ishex = isdig || (lc >= 8'h61 && lc <= 8'h66);
    wire logic [3:0]  hx = isdig ? c[3:0] : 4'(lc - 8'h57);
    wire logic        alpha = lc >= 8'h61 && lc <= 8'h7A;
    wire logic        namec = isdig || alpha || c == 8'h5F;
    wire logic [7:0]  ddig = c - 8'h30;

    // the name register, as the characters came (lower case for sections)
    function automatic logic [95:0] put(input logic [95:0] n, input logic [3:0] i, input logic [7:0] ch);
        logic [95:0] r;
        r = n;
        r[95 - 8*i -: 8] = ch;
        return r;
    endfunction
    function automatic logic is_name(input logic [95:0] n, input logic [3:0] len, input logic [95:0] s,
                                     input logic [3:0] slen);
        return len == slen && n == s;
    endfunction
    localparam logic [95:0] N_MAPPING  = {"mapping", 40'd0};
    localparam logic [95:0] N_PRELOAD  = {"preload", 40'd0};
    localparam logic [95:0] N_MEMATTR  = {"memattr", 40'd0};
    localparam logic [95:0] N_BANKSW   = {"bankswitch", 16'd0};
    localparam logic [95:0] N_VARS     = {"vars", 64'd0};
    localparam logic [95:0] N_ECS      = {"ecs", 72'd0};
    localparam logic [95:0] N_ECSC     = {"ecs_compat", 16'd0};
    localparam logic [95:0] N_VOICE    = {"voice", 56'd0};
    localparam logic [95:0] N_VOICEC   = {"voice_compat"};
    localparam logic [95:0] N_JLP      = {"jlp", 72'd0};
    localparam logic [95:0] N_JLPA     = {"jlp_accel", 24'd0};
    localparam logic [95:0] N_JLPF     = {"jlp_flash", 24'd0};
    localparam logic [95:0] N_JLPF2    = {"jlpflash", 32'd0};
    localparam logic [95:0] N_LTO      = {"lto_mapper", 16'd0};

    // the line's range, checked (a commit)
    wire logic [20:0] span   = 21'(num1) - 21'(num0);           // hi - lo (num1 >= num0)
    wire logic [20:0] tgt_hi = 21'(num2) + span;
    wire logic        is_map = sec == S_MAP || sec == S_PRE;

    logic [7:0]  c_err;
    always_comb begin
        c_err = 8'd0;
        if (ovf)                                   c_err = E_RANGE;
        else if (nrng == 6'd32)                    c_err = E_MANY;
        else if (num0 > num1 || num1 > 20'hFFFF)   c_err = E_RANGE;
        else if (is_map && (num2 > 20'hFFFF || tgt_hi > 21'hFFFF)) c_err = E_RANGE;
        else if (sec == S_PRE && haspage)          c_err = E_PAGE;
        else if ((has_page || (sec == S_MAP && haspage)) && (has_bsw || sec == S_BSW))
                                                   c_err = E_MIX;
    end
    wire logic [58:0] c_d =
        sec == S_MAP ? {3'd1, haspage, page, 3'd0, num2[15:0], tgt_hi[15:0], num0[15:0]} :
        sec == S_PRE ? {3'd2, 1'b0, 4'd0, 3'd0, num2[15:0], tgt_hi[15:0], num0[15:0]} :
        sec == S_MEM ? {3'd3, 1'b0, 4'd0, attr, num0[15:0], num1[15:0], 16'd0} :
                       {3'd4, 1'b0, 4'd0, 3'd0, num0[15:0], num1[15:0], 16'd0};

    // ------------------------------------------------------------ steps
    task automatic fail(input logic [7:0] code);
        if (err == 8'd0) err <= code;
        st <= P_DEAD;
    endtask

    // blanks, then ';' or LF ends (commits) a map line
    task automatic line_end;
        if (ws)
            st <= P_END;
        else if (semi || lf) begin
            if (c_err != 8'd0)
                fail(c_err);
            else begin
                rng_we  <= 1'b1;
                rng_idx <= nrng[4:0];
                rng_d   <= c_d;
                nrng    <= nrng + 6'd1;
                if (sec == S_MAP && haspage) has_page <= 1'b1;
                if (sec == S_BSW) has_bsw <= 1'b1;
                st <= lf ? P_BOL : P_SKIP;
            end
        end else
            fail(E_SYNTAX);
    endtask

    task automatic after1;
        if (c == 8'h3D) begin
            if (is_map)              st <= P_N2S;
            else if (sec == S_MEM)   st <= P_KWS;
            else                     fail(E_SYNTAX);
        end else if (sec == S_BSW)
            line_end();
        else
            fail(E_SYNTAX);
    endtask

    task automatic var_end;
        if (!nover) begin
            if (is_name(name, nlen, N_ECS, 4'd3) && val == 8'd1)       f_ecs <= 1'b1;
            if (is_name(name, nlen, N_ECSC, 4'd10)) begin
                if (val == 8'd3) f_ecs <= 1'b1;
                if (val == 8'd0) f_ecs_off <= 1'b1;
            end
            if (is_name(name, nlen, N_VOICE, 4'd5) && val == 8'd1)     f_voice <= 1'b1;
            if (is_name(name, nlen, N_VOICEC, 4'd12) && (val == 8'd2 || val == 8'd3)) f_voice <= 1'b1;
            if ((is_name(name, nlen, N_JLP, 4'd3) || is_name(name, nlen, N_JLPA, 4'd9)) && val != 8'd0)
                f_jlp <= 1'b1;
            if ((is_name(name, nlen, N_JLP, 4'd3) || is_name(name, nlen, N_JLPA, 4'd9)) && !f_jlp_mset) begin
                f_jlp_mset <= 1'b1;
                f_jlp_mode <= val > 8'd3 ? 2'd3 : val[1:0];
            end
            if ((is_name(name, nlen, N_JLPF, 4'd9) || is_name(name, nlen, N_JLPF2, 4'd8)) && !f_jlp_fset) begin
                f_jlp_fset  <= 1'b1;
                f_jlp_flash <= val;
            end
        end
        if (!nover && is_name(name, nlen, N_LTO, 4'd10) && val != 8'd0)
            fail(E_LTO);
        else
            st <= lf ? P_BOL : P_SKIP;
    endtask

    wire logic [11:0] dec_next = 12'(val) * 12'd10 + 12'(ddig);

    always_ff @(posedge clk) begin
        rng_we <= 1'b0;
        if (clr) begin
            st <= P_BOL; sec <= S_NONE; ended <= 1'b0; err <= 8'd0; nrng <= 6'd0;
            f_ecs <= 1'b0; f_ecs_off <= 1'b0; f_voice <= 1'b0; f_jlp <= 1'b0;
            f_jlp_mode <= 2'd0; f_jlp_mset <= 1'b0; f_jlp_flash <= 8'd0; f_jlp_fset <= 1'b0;
            has_page <= 1'b0; has_bsw <= 1'b0;
        end else if (in_v && !ended && c == 8'h00 && !in_end) begin
            ended <= 1'b1;
        end else if (go) begin
            if (in_end) ended <= 1'b1;
            unique case (st)
                P_BOL: if (!(ws || lf)) begin
                    if (semi)
                        st <= P_SKIP;
                    else if (c == 8'h5B) begin
                        nlen <= 4'd0; nover <= 1'b0; name <= 96'd0;
                        st <= P_HDR;
                    end else if (sec == S_MAP || sec == S_PRE || sec == S_MEM || sec == S_BSW) begin
                        num0 <= 20'd0; num1 <= 20'd0; num2 <= 20'd0; ovf <= 1'b0;
                        haspage <= 1'b0; page <= 4'd0; attr <= 3'd0;
                        if (c == 8'h24)
                            st <= P_N0D;
                        else if (ishex) begin
                            num0 <= {16'd0, hx};
                            st <= P_N0;
                        end else
                            fail(E_SYNTAX);
                    end else if (sec == S_VARS && namec) begin
                        name <= put(96'd0, 4'd0, c); nlen <= 4'd1; nover <= 1'b0; val <= 8'd0;
                        st <= P_VNAME;
                    end else
                        st <= P_SKIP;
                end
                P_SKIP: if (lf) st <= P_BOL;
                P_HDR:
                    if (c == 8'h5D) begin
                        sec <= nover ? S_SKIP :
                               is_name(name, nlen, N_MAPPING, 4'd7) ? S_MAP :
                               is_name(name, nlen, N_PRELOAD, 4'd7) ? S_PRE :
                               is_name(name, nlen, N_MEMATTR, 4'd7) ? S_MEM :
                               is_name(name, nlen, N_BANKSW, 4'd10) ? S_BSW :
                               is_name(name, nlen, N_VARS, 4'd4) ? S_VARS : S_SKIP;
                        st <= P_SKIP;
                    end else if (lf) begin
                        sec <= S_SKIP;
                        st  <= P_BOL;
                    end else if (nlen < 4'd12) begin
                        name <= put(name, nlen, lc);
                        nlen <= nlen + 4'd1;
                    end else
                        nover <= 1'b1;
                P_N0D: if (ishex) begin num0 <= {16'd0, hx}; st <= P_N0; end else fail(E_SYNTAX);
                P_N1D: if (ishex) begin num1 <= {16'd0, hx}; st <= P_N1; end else fail(E_SYNTAX);
                P_N2D: if (ishex) begin num2 <= {16'd0, hx}; st <= P_N2; end else fail(E_SYNTAX);
                P_N0:
                    if (ishex) begin
                        if (num0[19:16] != 4'd0) ovf <= 1'b1;
                        num0 <= {num0[15:0], hx};
                    end else if (ws)            st <= P_DASH;
                    else if (c == 8'h2D)        st <= P_N1S;
                    else                        fail(E_SYNTAX);
                P_DASH:
                    if (c == 8'h2D)             st <= P_N1S;
                    else if (!ws)               fail(E_SYNTAX);
                P_N1S, P_N2S: if (!ws) begin
                    if (c == 8'h24)
                        st <= st == P_N1S ? P_N1D : P_N2D;
                    else if (ishex) begin
                        if (st == P_N1S) begin num1 <= {16'd0, hx}; st <= P_N1; end
                        else             begin num2 <= {16'd0, hx}; st <= P_N2; end
                    end else
                        fail(E_SYNTAX);
                end
                P_N1:
                    if (ishex) begin
                        if (num1[19:16] != 4'd0) ovf <= 1'b1;
                        num1 <= {num1[15:0], hx};
                    end else if (ws)            st <= P_AFT1;
                    else                        after1();
                P_AFT1: if (!ws) after1();
                P_N2:
                    if (ishex) begin
                        if (num2[19:16] != 4'd0) ovf <= 1'b1;
                        num2 <= {num2[15:0], hx};
                    end else if (ws)            st <= P_AFT2;
                    else if (lc == 8'h70) begin k <= 2'd0; st <= P_PG; end
                    else                        line_end();
                P_AFT2: if (!ws) begin
                    if (lc == 8'h70) begin k <= 2'd0; st <= P_PG; end
                    else             line_end();
                end
                P_PG:
                    if (lc == (k == 2'd0 ? 8'h61 : k == 2'd1 ? 8'h67 : 8'h65)) begin
                        k <= k + 2'd1;
                        if (k == 2'd2) st <= P_PGWS1;
                    end else
                        fail(E_SYNTAX);
                P_PGWS1: if (ws) st <= P_PGWS; else fail(E_SYNTAX);
                P_PGWS: if (!ws) begin
                    if (ishex) begin
                        page <= hx; pagex <= {1'b0, hx}; haspage <= 1'b1;
                        st <= P_PGD;
                    end else
                        fail(E_SYNTAX);
                end
                P_PGD:
                    if (ishex) begin
                        if (pagex != 5'd0) fail(E_PAGE);   // a second digit after a non-zero one
                        else begin page <= hx; pagex <= {1'b0, hx}; end
                    end else
                        line_end();
                P_KWS: if (!ws) begin
                    if (alpha) begin
                        name <= put(96'd0, 4'd0, lc); nlen <= 4'd1;
                        st <= P_KW;
                    end else
                        fail(E_SYNTAX);
                end
                P_KW:
                    if (nlen < 4'd3 && alpha) begin
                        name <= put(name, nlen, lc);
                        nlen <= nlen + 4'd1;
                    end else if (nlen == 4'd3 && (ws || lf || semi)) begin
                        if (name[95:72] == "ram")      attr <= 3'd3;
                        else if (name[95:72] == "wom") attr <= 3'd2;
                        else if (name[95:72] == "rom") attr <= 3'd1;
                        if (name[95:72] != "ram" && name[95:72] != "wom" && name[95:72] != "rom")
                            fail(E_SYNTAX);
                        else if (ws)
                            st <= P_KWWS;
                        else
                            line_end();
                    end else
                        fail(E_SYNTAX);
                P_KWWS: if (!ws) begin
                    if (c == 8'h38) begin attr <= attr | 3'd4; st <= P_END; end
                    else if (c == 8'h31) st <= P_WID;
                    else if (lf || semi) line_end();
                    else fail(E_SYNTAX);
                end
                P_WID: if (c == 8'h36) st <= P_END; else fail(E_SYNTAX);
                P_END: line_end();
                P_VNAME:
                    if (namec) begin
                        if (nlen < 4'd12) begin
                            name <= put(name, nlen, c);
                            nlen <= nlen + 4'd1;
                        end else
                            nover <= 1'b1;
                    end else if (ws)            st <= P_VEQ;
                    else if (c == 8'h3D)        st <= P_VVAL0;
                    else                        st <= lf ? P_BOL : P_SKIP;
                P_VEQ:
                    if (c == 8'h3D)             st <= P_VVAL0;
                    else if (!ws)               st <= lf ? P_BOL : P_SKIP;
                P_VVAL0:
                    if (isdig) begin val <= ddig; st <= P_VVAL; end
                    else if (!ws)               st <= lf ? P_BOL : P_SKIP;
                P_VVAL, P_VEND:
                    if (st == P_VVAL && isdig)
                        val <= dec_next > 12'd255 ? 8'd255 : dec_next[7:0];
                    else if (ws)                st <= P_VEND;
                    else if (lf || semi)        var_end();
                    else                        st <= P_SKIP;
                default: ;                      // P_DEAD
            endcase
        end
    end

endmodule

`default_nettype wire
