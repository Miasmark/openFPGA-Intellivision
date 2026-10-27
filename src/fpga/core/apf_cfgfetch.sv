// Intellivision core: the cartridge's CFG found by its name (clk_74a).
//
// The owner keeps NAME.cfg beside NAME.bin and wants it used without a
// second pick (2026-10-27). The CFG slot (0x101) is a deferload slot in
// data.json: the Pocket never streams it. apf_datatable starts this module
// after "all complete" for a new cartridge, and holds len_valid until it is
// done. With the target commands of core_bridge_cmd (APF "Host/Target
// commands"):
//   1. 0x0190 "Get filename of data slot" for the cartridge (0x100): the
//      host writes its full path ("/Assets/intv/common/NAME.bin", NUL
//      ended, 256 bytes) into the struct RAM below;
//   2. the path's extension, after its last '.', becomes "cfg" (FAT does
//      not mind the case); no '.' or no room for "cfg" and its NUL: no CFG;
//   3. 0x0192 "Open new file into data slot" for the CFG slot with that
//      struct (flags and size words 0: open, do not create): result 0 (or
//      1) opened, 3 not found (no CFG: the cartridge maps as without one),
//      any other: an error (no CFG);
//   4. the CFG's length: the data table's size for 0x101 (apf_datatable
//      rescans it, sz_req / sz), if the host put it there. If it is 0, the
//      length is found by reading: 0x0180 "Data slot read" in chunks of 256
//      bytes while they succeed, then on a failure the next smaller length
//      of 128, 64, ..., 4, 3, 2, 1 at the same offset; a success below 4
//      ends it, and so does a failure at 1. A read that fails is taken to
//      write nothing (the host checks the range first); successful reads
//      run in order and never overlap, so the loader sees one CFG stream;
//      Each chunk goes to the CFG slot's bridge address plus its offset;
//      the chunks are word aligned until the last (a read below 4 bytes).
//   5. with a known length, one 0x0180 read of the whole file (at most
//      MAX_LEN, data.json's size_maximum) to the CFG slot's bridge address,
//      so agg23's data_loader hands its bytes to intv_media as if the host
//      had streamed the slot; then a short wait for that pipeline to drain
//      into clk_sys before done.
// Each target command: the request is raised with its parameters held,
// core_bridge_cmd clears target_dataslot_done when it starts the command
// and sets it with the result code at the end; the request falls then.
//
// The struct RAM (66 words, 256-byte path, flags word, size word) is served
// at the bridge address ST_ADDR (0x6000_0000; 0x00-0x05 are the slots, 0x20
// the JLP flash, 0x50 the save state). The bridge is big-endian (core_top
// keeps bridge_endian_little 0): byte k of the path is in word k / 4, bits
// [31 - 8 * (k % 4) -: 8].
//
// res says how it went (test pattern and benches): 0 not run, 1 found
// (the table's length), 2 found (length by reading), 3 no CFG beside the
// cartridge, 4 the host refused (getfile, openfile or read), 5 the path
// has no extension to replace, 6 the CFG is over MAX_LEN bytes.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module apf_cfgfetch #(
    parameter logic [15:0] CART_ID = 16'h0100,
    parameter logic [15:0] CFG_ID  = 16'h0101,
    parameter logic [31:0] CFG_ADDR = 32'h0100_0000,  // the CFG slot's bridge address
    parameter logic [31:0] ST_ADDR  = 32'h6000_0000,  // the struct RAM
    parameter int          MAX_LEN = 16384,
    parameter int          DRAIN   = 2048              // clk_74a after the last read
) (
    input  wire logic        clk,                 // clk_74a
    input  wire logic        start,               // a pulse
    output logic             done,                // until the next start
    output logic [2:0]       res,
    output logic [31:0]      len,                 // the CFG's length when res is 1 or 2
    output logic [2:0]       code,                // the last command's result code
    // the data table's size for CFG_ID (apf_datatable rescans on sz_req)
    output logic             sz_req,
    input  wire logic        sz_ack,
    input  wire logic [31:0] sz,
    // core_bridge_cmd's target command ports
    output logic             t_read,
    output logic             t_getfile,
    output logic             t_openfile,
    output logic [15:0]      t_id,
    output logic [31:0]      t_offset,
    output logic [31:0]      t_bridgeaddr,
    output logic [31:0]      t_length,
    input  wire logic        t_done,
    input  wire logic [2:0]  t_err,
    // the struct RAM on the bridge (bits 31:24 select it, 8:2 the word)
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [31:0] bridge_addr,
    /* verilator lint_on UNUSEDSIGNAL */
    input  wire logic        bridge_wr,
    input  wire logic [31:0] bridge_wr_data,
    input  wire logic        bridge_rd,
    output logic [31:0]      st_rd_data           // held from the last read
);

    // ------------------------------------------------------- struct RAM
    logic [31:0] mem [128];
    wire  logic  a_hit = bridge_addr[31:24] == ST_ADDR[31:24];
    logic [31:0] a_q;
    logic        rd_d = 1'b0;
    always_ff @(posedge clk) begin
        if (bridge_wr && a_hit) mem[bridge_addr[8:2]] <= bridge_wr_data;
        a_q <= mem[bridge_addr[8:2]];
    end
    always_ff @(posedge clk) begin
        rd_d <= bridge_rd && a_hit;
        if (rd_d) st_rd_data <= a_q;
    end
    logic [6:0]  b_addr = 7'd0;
    logic        b_we = 1'b0;
    logic [31:0] b_d = 32'd0, b_q;
    always_ff @(posedge clk) begin
        if (b_we) mem[b_addr] <= b_d;
        b_q <= mem[b_addr];
    end

    // ------------------------------------------------------------ steps
    typedef enum logic [4:0] {
        S_IDLE, S_CLR0, S_CLR1, S_GETF, S_SCAN, S_SCANW, S_SCANB, S_EDITR, S_EDITW, S_EDITM,
        S_OPEN, S_SIZE, S_READ, S_CHUNK, S_DRAIN, S_END
    } st_t;
    st_t         st = S_IDLE;
    st_t         after = S_IDLE;                  // the step a command returns to
    logic [1:0]  cph = 2'd0;                      // command phase: 0 raise, 1 wait start, 2 wait end
    logic [2:0]  cmd = 3'd0;                      // 1 getfile, 2 openfile, 4 read
    logic [8:0]  pos = 9'd0;                      // byte position
    logic [8:0]  dot = 9'd0;
    logic        has_dot = 1'b0;
    logic [2:0]  k = 3'd0;                        // the 'cfg' + NUL byte being written
    logic [31:0] off = 32'd0, cl = 32'd0;         // chunk offset and length
    logic [15:0] dr = 16'd0;

    initial begin
        done = 1'b0; res = 3'd0; len = 32'd0; code = 3'd0; sz_req = 1'b0;
        t_read = 1'b0; t_getfile = 1'b0; t_openfile = 1'b0;
        t_id = 16'd0; t_offset = 32'd0; t_bridgeaddr = 32'd0; t_length = 32'd0;
    end

    // the next smaller chunk length after a failure (0: none)
    function automatic logic [31:0] smaller(input logic [31:0] n);
        return n > 32'd4 ? n >> 1 : n - 32'd1;
    endfunction

    // the byte of the edit: 'c', 'f', 'g', NUL
    wire logic [7:0] ext_b = k == 3'd0 ? 8'h63 : k == 3'd1 ? 8'h66 : k == 3'd2 ? 8'h67 : 8'h00;
    wire logic [8:0] ext_p = dot + 9'd1 + {6'd0, k};

    always_ff @(posedge clk) begin
        b_we <= 1'b0;
        if (start) begin
            done   <= 1'b0;
            res    <= 3'd0;
            len    <= 32'd0;
            code   <= 3'd0;
            sz_req <= 1'b0;
            {t_read, t_getfile, t_openfile} <= 3'b000;
            cph    <= 2'd0;
            st     <= S_CLR0;
        end else if (cph != 2'd0 || cmd != 3'd0) begin
            // ---- one target command (cmd), then back to after
            case (cph)
                2'd0: begin
                    {t_read, t_openfile, t_getfile} <= cmd;
                    cph <= 2'd1;
                end
                2'd1: if (!t_done) cph <= 2'd2;          // the bridge took it
                default: if (t_done) begin
                    {t_read, t_openfile, t_getfile} <= 3'b000;
                    code <= t_err;
                    cmd  <= 3'd0;
                    cph  <= 2'd0;
                    st   <= after;
                end
            endcase
        end else begin
            case (st)
                S_IDLE: ;
                // the flags and size words of the open struct: 0
                S_CLR0: begin b_addr <= 7'd64; b_d <= 32'd0; b_we <= 1'b1; st <= S_CLR1; end
                S_CLR1: begin b_addr <= 7'd65; b_d <= 32'd0; b_we <= 1'b1; st <= S_GETF; end
                S_GETF: begin
                    t_id <= CART_ID;
                    cmd  <= 3'b001;
                    after <= S_SCAN;
                    pos  <= 9'd0;
                    has_dot <= 1'b0;
                end
                // ---- the path: its NUL and its last '.'
                S_SCAN: if (code != 3'd0) begin
                            res <= 3'd4;
                            st  <= S_END;
                        end else begin
                            b_addr <= pos[8:2];
                            st <= S_SCANW;
                        end
                S_SCANW: st <= S_SCANB;
                S_SCANB: begin
                    logic [7:0] c;
                    c = b_q[31 - 8 * pos[1:0] -: 8];
                    if (c == 8'h00 || pos == 9'd256) begin
                        // room for "cfg" and its NUL within the 256 bytes
                        if (!has_dot || dot > 9'd251) begin
                            res <= 3'd5;
                            st  <= S_END;
                        end else begin
                            k  <= 3'd0;
                            st <= S_EDITR;
                        end
                    end else begin
                        if (c == 8'h2E) begin
                            dot <= pos;
                            has_dot <= 1'b1;
                        end else if (c == 8'h2F) begin
                            has_dot <= 1'b0;                 // a '.' in a folder name is not the extension's
                        end
                        pos <= pos + 9'd1;
                        if (pos[1:0] == 2'd3) st <= S_SCAN;  // next word
                    end
                end
                // ---- "cfg" and NUL after the dot, a byte at a time (read, modify, write)
                S_EDITR: begin b_addr <= ext_p[8:2]; st <= S_EDITW; end
                S_EDITW: st <= S_EDITM;
                S_EDITM: begin
                    b_d <= b_q;
                    b_d[31 - 8 * ext_p[1:0] -: 8] <= ext_b;
                    b_we <= 1'b1;
                    if (k == 3'd3) st <= S_OPEN;
                    else begin k <= k + 3'd1; st <= S_EDITR; end
                end
                S_OPEN: begin
                    t_id  <= CFG_ID;
                    cmd   <= 3'b010;
                    after <= S_SIZE;
                end
                S_SIZE: begin
                    if (!sz_req) begin
                        if (code == 3'd3) begin
                            res <= 3'd3;
                            st  <= S_END;
                        end else if (code > 3'd1) begin
                            res <= 3'd4;
                            st  <= S_END;
                        end else
                            sz_req <= 1'b1;
                    end else if (sz_ack) begin
                        sz_req <= 1'b0;
                        t_id <= CFG_ID;
                        t_bridgeaddr <= CFG_ADDR;
                        t_offset <= 32'd0;
                        if (sz > 32'(MAX_LEN)) begin
                            res <= 3'd6;
                            st  <= S_END;
                        end else if (sz != 32'd0) begin
                            len <= sz;
                            t_length <= sz;
                            cmd   <= 3'b100;
                            after <= S_READ;
                        end else begin
                            // the table has no size: find it by reading
                            off <= 32'd0;
                            cl  <= 32'd256;
                            t_length <= 32'd256;
                            cmd   <= 3'b100;
                            after <= S_CHUNK;
                        end
                    end
                end
                S_READ: begin
                    res <= code == 3'd0 ? 3'd1 : 3'd4;
                    dr  <= 16'(DRAIN);
                    st  <= code == 3'd0 ? S_DRAIN : S_END;
                end
                S_CHUNK: begin
                    logic [31:0] o, n;
                    o = code == 3'd0 ? off + cl : off;      // the offset after this read
                    n = code == 3'd0 ? cl : smaller(cl);    // the next length
                    off <= o;
                    if (o >= 32'(MAX_LEN) && code == 3'd0 && cl >= 32'd4) begin
                        res <= 3'd6;
                        st  <= S_END;
                    end else if ((code == 3'd0 && cl < 32'd4) || n == 32'd0) begin
                        // the end: a short read succeeded, or one byte failed
                        len <= o;
                        res <= o == 32'd0 ? 3'd3 : 3'd2;    // an empty file: no CFG
                        dr  <= 16'(DRAIN);
                        st  <= S_DRAIN;
                    end else begin
                        cl <= n;
                        t_offset <= o;
                        t_bridgeaddr <= CFG_ADDR + o;       // the slot's bytes at their own offsets
                        t_length <= n;
                        cmd   <= 3'b100;
                        after <= S_CHUNK;
                    end
                end
                S_DRAIN: if (dr == 16'd0) st <= S_END; else dr <= dr - 16'd1;
                S_END: begin
                    done <= 1'b1;
                    st   <= S_IDLE;
                end
                default: st <= S_IDLE;
            endcase
        end
    end

endmodule

`default_nettype wire
