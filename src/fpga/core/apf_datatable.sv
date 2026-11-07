// Intellivision core: the core's side of the APF data table (clk_74a).
//
// The host writes the data table (slot id, size) pairs at 0xF8002000 before
// "data slot access all complete" (command 0x008F); core_bridge_cmd keeps it
// in a dual-port RAM (mf_datatable, two clocks of read latency) whose port A
// is ours. This module
//   - writes the JLP flash slot's size (index JLP_IDX): the cartridge's sectors x
//     1,536 bytes (build step 11; 0 without flash, so the Pocket writes no file).
//     The sector count comes from clk_sys and changes only at a load: two
//     flip-flops, then taken when two clocks agree
//     stores flash (DESIGN.md 13 item 17), as core_top did in step 1;
//   - on each rising edge of dataslot_allcomplete, scans the table for the
//     cartridge slot id (0x100) and reads its size: the file's length in
//     bytes, which the loader needs (tools/mapper/README.md "The loader's
//     CRC and length"). cart_len is set one clk_74a before len_valid and
//     then held, so a clk_sys synchroniser on len_valid alone is enough.
//     len_valid falls with dataslot_allcomplete (a new slot request).
//   - (build step 8) in the same scan, the CFG slot's size (CFG_ID, 0x101):
//     cfg_len and cfg_inlist (0 when the table has no such entry), set with
//     cart_len; the loader cuts the CFG text at it (the bridge pads files to
//     32-bit words). With FETCH (the core's own setting since 2026-10-27)
//     the CFG slot is a deferload slot the host never streams: after the
//     scan, for a new cartridge (a 0x0082 for it since the last fetch, or
//     the first load after power-on), apf_cfgfetch finds NAME.cfg beside the
//     cartridge and reads it in; cfg_len and cfg_inlist then come from it
//     (cfg_inlist 1 with cfg_len 0: no CFG), and len_valid waits for it. An
//     "all complete" without a new cartridge (a slot read, say) keeps the
//     last fetch's result and does not fetch again: a CFG streamed again
//     would remap the running cartridge. The fetch asks for the table's
//     size of the CFG slot after opening it (sz_req): the scan runs again
//     for that one entry;
//   - latches the size the host gives with "data slot request write"
//     (0x0082, core_bridge_cmd's dataslot_requestwrite_size) for the
//     cartridge slot, and checks the table's length against it. No core in
//     the research corpus reads a file size back from the data table, so
//     until a Pocket shows both agree (step-1/2 hardware checklist: the
//     length after the first load and after a user reload of a cartridge of
//     another size), the core keeps both and says which it used (len_chk,
//     shown on the test pattern):
//       0  the table's length; no 0x0082 for the slot was seen
//       1  the table's length; the 0x0082 size agrees
//       2  the table's length; the 0x0082 size disagrees (the loader sets
//          err[4] and the test pattern shows it)
//       3  the table has no entry for the slot: the 0x0082 size is used
//     A table without the slot and no 0x0082 for it gives length 0 (the
//     loader: no cartridge). The 0x0082 size is kept until the next one for
//     the slot, so a session that does not reload the cartridge checks
//     against the last load's size.
//   - (2026-10-31, the owner's tests of 0.0.15-0.0.19) status_setup_done and
//     Ready to run (0x0140) go out at PLL lock (core_top; any later and the
//     Pocket stops with "Core not ready to run"), and the fetch below waits
//     until core_bridge_cmd is done with 0x0140 (rtr_ok): answered, as on a
//     first load, or given up after 5 s (core_bridge_cmd RTR_GIVEUP: on a Core
//     Settings reload the Pocket leaves it unanswered), so the fetch's own
//     commands never queue behind it. setup_done is diagnostics now:
//   - setup_done: rises when the
//     first load since configuration has reached len_valid (D_SET), the CFG
//     fetch finished whatever its result, so the core reports APF "setup"
//     ("Pocket loads assets, core may request dataslot reads") while it
//     fetches and sends Ready to run (0x0140, core_bridge_cmd queues it on
//     setup_done's rising edge) after. The owner's 0.0.14 photos (2026-10-28)
//     showed why: with setup_done at PLL lock, 0x0140 went out first and the
//     Pocket acks it only once it starts the core, so the fetch's 0x0190,
//     queued behind it in core_bridge_cmd, timed out on every load. Safety:
//     with no "all complete" SAFE clocks (3 s) after configuration, setup_done
//     rises anyway, in case a host flow waits for Ready to run before loading.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module apf_datatable #(
    parameter logic [31:0] SLOT_ID = 32'h0000_0100,
    parameter logic [31:0] CFG_ID  = 32'h0000_0101,
    parameter int          JLP_IDX = 6,
    parameter int          TAPE_IDX = 7,     // the ECS tape slot (0x107): 16,384 bytes while tape_on
    parameter int          ENTRIES = 16,       // pairs scanned
    parameter bit          FETCH   = 1'b1,     // the CFG found by name (apf_cfgfetch)
    parameter int          WD_BITS = 26,       // apf_cfgfetch's time limit per command (2^WD_BITS clk_74a)
    parameter int          TO_HOLD = 300000000, // apf_cfgfetch's hold after a timeout (clk_74a: 4 s)
    parameter int          SAFE    = 222750000  // setup_done without an "all complete" (clk_74a: 3 s)
) (
    input  wire logic        clk,             // clk_74a
    input  wire logic        allcomplete,
    input  wire logic        wr_req,          // dataslot_requestwrite (0x0082)
    input  wire logic [15:0] wr_id,
    input  wire logic [31:0] wr_size,
    input  wire logic        upd,             // dataslot_update (0x008A)
    input  wire logic [15:0] upd_id,

    output logic [9:0]       dt_addr,
    output logic             dt_wren,
    output logic [31:0]      dt_data,
    input  wire logic [31:0] dt_q,

    output logic [31:0]      cart_len,
    output logic [1:0]       len_chk,         // see above; set with cart_len
    output logic [31:0]      cfg_len,
    output logic             cfg_inlist,
    output logic             len_valid,
    input  wire logic [4:0]  jlp_sectors,     // clk_sys: the JLP flash slot's size (x 1,536 bytes)
    input  wire logic        tape_on,         // clk_sys: the game has an ECS tape (its slot's size 16,384, else 0)

    // apf_cfgfetch (FETCH): core_bridge_cmd's target commands, its struct
    // RAM on the bridge, and how the fetch went (apf_cfgfetch's res)
    output logic             t_read,
    output logic             t_getfile,
    output logic             t_openfile,
    output logic [15:0]      t_id,
    output logic [31:0]      t_offset,
    output logic [31:0]      t_bridgeaddr,
    output logic [31:0]      t_length,
    input  wire logic        t_done,
    input  wire logic [2:0]  t_err,
    input  wire logic [31:0] bridge_addr,
    input  wire logic        bridge_wr,
    input  wire logic [31:0] bridge_wr_data,
    input  wire logic        bridge_rd,
    output logic [31:0]      st_rd_data,
    output logic [2:0]       fetch_res,
    output logic [2:0]       fetch_code,
    output logic [31:0]      fetch_len,
    // the load's diagnostics (test pattern, 0.0.14): which command timed out
    // (apf_cfgfetch's to_cmd); all complete seen since power-on; a 0x0082 and
    // a 0x008A for the cartridge slot seen since power-on; where the last
    // load is: 0 idle or scanning, 1 waiting for the fetch, 2 len_valid set
    output logic [2:0]       fetch_to,
    output logic             cfg_wr_ok,       // the CFG slot's bridge writes may reach the loader
    output logic             loader_wr,       // bridge_wr for the data loader: the CFG slot's only while cfg_wr_ok
    output logic             d_ac,
    output logic             d_req,
    output logic             d_upd,
    output logic [1:0]       d_phase,
    output logic             setup_done,      // the first load's fetch done (diagnostics; see above)
    input  wire logic        rtr_ok           // core_bridge_cmd is done with Ready to run (answered or given up)
);

    typedef enum logic [3:0] {D_IDLE, D_ID, D_IDW, D_SIZEW, D_NEXT, D_DECIDE, D_FETCH, D_FWAIT, D_SET} dstate_t;
    dstate_t     st = D_IDLE;
    logic        cart_new = 1'b1;              // a cartridge streamed since the last fetch
    logic        rescan = 1'b0;                // the scan serves the fetch's size request
    logic        f_start = 1'b0, f_done, f_sz_req;
    logic        sz_ack = 1'b0;
    logic [31:0] sz = 32'd0;
    logic [31:0] f_len;
    logic        ac_d = 1'b0;
    logic [4:0]  i = 5'd0;
    logic [1:0]  w = 2'd0;
    logic        req_seen = 1'b0;
    logic [31:0] req_len = 32'd0;
    logic        is_cfg = 1'b0, got_cart = 1'b0;

    initial begin
        dt_addr = 10'(2 * JLP_IDX + 1); dt_wren = 1'b0; dt_data = 32'd0;
        cart_len = 32'd0; len_chk = 2'd0; len_valid = 1'b0; cfg_len = 32'd0; cfg_inlist = 1'b0;
    end

    logic reached = 1'b0;                      // len_valid set for the current load
    logic [$clog2(SAFE + 1) - 1:0] safe_n = '0;
    initial setup_done = 1'b0;
    initial begin d_ac = 1'b0; d_upd = 1'b0; end
    assign d_req   = req_seen;
    assign d_phase = st == D_FWAIT ? 2'd1 : reached ? 2'd2 : 2'd0;

    logic [4:0] js_a = 5'd0, js_s = 5'd0, js_b = 5'd0;
    logic [2:0] tp_s = 3'd0;
    logic       tw = 1'b0;                     // idle size writes alternate: JLP, tape
    always_ff @(posedge clk) begin
        js_a <= jlp_sectors;
        js_s <= js_a;
        if (js_s == js_a) js_b <= js_s;
        tp_s <= {tp_s[1:0], tape_on};
    end

    always_ff @(posedge clk) begin
        ac_d <= allcomplete;
        if (allcomplete) d_ac <= 1'b1;
        // the safety: no "all complete" SAFE clocks after configuration (a host flow that would
        // wait for Ready to run before loading): setup done all the same
        if (!setup_done && !d_ac) begin
            if (32'(safe_n) == 32'(SAFE)) setup_done <= 1'b1;
            else safe_n <= safe_n + 1'b1;
        end
        if (upd && upd_id == SLOT_ID[15:0]) d_upd <= 1'b1;
        dt_wren <= 1'b0;
        f_start <= 1'b0;
        if (wr_req && wr_id == SLOT_ID[15:0]) begin
            req_seen <= 1'b1;
            req_len  <= wr_size;
            cart_new <= 1'b1;
        end
        if (!allcomplete)
            len_valid <= 1'b0;
        case (st)
            D_IDLE: begin
                // the JLP and tape size words, rewritten while idle (one a clock, in turn)
                tw <= !tw;
                dt_addr <= tw ? 10'(2 * TAPE_IDX + 1) : 10'(2 * JLP_IDX + 1);
                dt_data <= tw ? (tp_s[2] ? 32'd16384 : 32'd0) : 32'(js_b) * 32'd1536;
                dt_wren <= 1'b1;
                if (allcomplete && !ac_d) begin
                    reached <= 1'b0;
                    i  <= 5'd0;
                    got_cart <= 1'b0;
                    rescan <= 1'b0;
                    if (!FETCH) begin
                        cfg_len <= 32'd0;
                        cfg_inlist <= 1'b0;
                    end
                    st <= D_ID;
                end
            end
            D_ID: begin                              // read the id of pair i
                dt_addr <= {4'd0, i, 1'b0};
                w  <= 2'd3;
                st <= D_IDW;
            end
            D_IDW: if (w != 2'd0) w <= w - 2'd1;
                   else if (dt_q == SLOT_ID || dt_q == CFG_ID) begin
                       is_cfg  <= dt_q == CFG_ID;
                       dt_addr <= {4'd0, i, 1'b1};
                       w  <= 2'd3;
                       st <= D_SIZEW;
                   end else
                       st <= D_NEXT;
            D_SIZEW: if (w != 2'd0) w <= w - 2'd1;
                     else begin
                         if (is_cfg && rescan) begin
                             sz     <= dt_q;              // the fetch's size request
                             sz_ack <= 1'b1;
                             st     <= D_FWAIT;
                         end else if (is_cfg && !FETCH) begin
                             cfg_len    <= dt_q;
                             cfg_inlist <= 1'b1;
                         end else if (!is_cfg && !got_cart && !rescan) begin
                             got_cart <= 1'b1;
                             cart_len <= dt_q;
                             len_chk  <= !req_seen ? 2'd0 : dt_q == req_len ? 2'd1 : 2'd2;
                         end
                         if (!(is_cfg && rescan)) st <= D_NEXT;
                     end
            D_NEXT: if (i == 5'(ENTRIES - 1) && rescan) begin
                        sz     <= 32'd0;               // the table has no CFG entry
                        sz_ack <= 1'b1;
                        st     <= D_FWAIT;
                    end else if (i == 5'(ENTRIES - 1)) begin
                        if (!got_cart) begin
                            // no cartridge slot in the table: the 0x0082 size, if any
                            cart_len <= req_seen ? req_len : 32'd0;
                            len_chk  <= req_seen ? 2'd3 : 2'd0;
                        end
                        st <= D_DECIDE;
                    end else begin
                        i  <= i + 5'd1;
                        st <= D_ID;
                    end
            // the CFG beside the cartridge (apf_cfgfetch), once per cartridge;
            // none without a cartridge (length 0: nothing to name it after)
            D_DECIDE: st <= FETCH && cart_new ? D_FETCH : D_SET;
            D_FETCH: begin
                if (cart_len == 32'd0) begin
                    cart_new <= 1'b0;
                    st <= D_SET;
                end else if (rtr_ok) begin             // after core_bridge_cmd is done with 0x0140
                    cart_new <= 1'b0;
                    f_start <= 1'b1;
                    st <= D_FWAIT;
                end
            end
            D_FWAIT: begin
                sz_ack <= 1'b0;
                if (f_sz_req && !sz_ack && !rescan) begin
                    rescan <= 1'b1;                   // the CFG entry's size, once
                    i  <= 5'd0;
                    st <= D_ID;
                end else if (!f_sz_req)
                    rescan <= 1'b0;
                if (f_done && !f_start) begin
                    cfg_inlist <= 1'b1;
                    cfg_len    <= fetch_res == 3'd1 || fetch_res == 3'd2 ? f_len : 32'd0;
                    st <= D_SET;
                end
            end
            D_SET: begin
                len_valid <= allcomplete;
                reached <= 1'b1;
                setup_done <= 1'b1;
                st <= D_IDLE;
            end
            default: st <= D_IDLE;
        endcase
    end

    apf_cfgfetch #(
        .CART_ID(SLOT_ID[15:0]), .CFG_ID(CFG_ID[15:0]), .WD_BITS(WD_BITS), .TO_HOLD(TO_HOLD)
    ) fetch (
        .clk(clk), .start(f_start), .done(f_done), .res(fetch_res), .len(f_len), .code(fetch_code),
        .to_cmd(fetch_to), .cfg_wr_ok(cfg_wr_ok),
        .sz_req(f_sz_req), .sz_ack(sz_ack), .sz(sz),
        .t_read(t_read), .t_getfile(t_getfile), .t_openfile(t_openfile), .t_id(t_id),
        .t_offset(t_offset), .t_bridgeaddr(t_bridgeaddr), .t_length(t_length),
        .t_done(t_done), .t_err(t_err),
        .bridge_addr(bridge_addr), .bridge_wr(bridge_wr), .bridge_wr_data(bridge_wr_data),
        .bridge_rd(bridge_rd), .st_rd_data(st_rd_data)
    );
    assign fetch_len = f_len;
    // The CFG slot is a deferload slot: the host writes its bytes to the bridge only for
    // apf_cfgfetch's reads. A read that timed out may still be answered later; its bytes must
    // not reach a cartridge already mapped, so the CFG slot's addresses reach the data loader
    // only while a read is outstanding.
    assign loader_wr = bridge_wr && !(bridge_addr[31:24] == 8'h01 && !cfg_wr_ok);

endmodule

`default_nettype wire
