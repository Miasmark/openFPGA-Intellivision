// Steps 2 and 8 bench (DESIGN.md 9): the loader, the CRC table lookup, the
// CFG and .rom parsers, the map table and the system ROMs, driven through the APF bridge as core_top sees
// it, against the Python mapper model (tools/intv_mapper.py).
//
//   python3 -I sim/tb/tb_loader.py ...   (builds with Verilator, prepares
//                                         images and expectations, runs
//                                         this bench per image, compares)
//
// The host side follows the Pocket's protocol on clk_74a: reset enter
// (0x0010), for each slot a data slot request write (0x0082) and its bytes
// as big-endian 32-bit bridge writes (the last one padded with +pad), the
// data table (id, size pairs at 0xF8002000; before the files with
// +dtfirst=1, else after them), all complete (0x008F), reset exit
// (0x0011). The real core_bridge_cmd, agg23's data_loader and our
// apf_datatable carry it to intv_media on clk_sys, whose SRAM is the
// AS6C2016 model with its timing checks.
//
// Then, through the cartridge bus port (as the CPU will reach it), the
// auxiliary SRAM port, the system ROM read ports and the state port:
//   status   CRC, words, layout, flags, hit, err, slot status; format,
//            CFG CRC, no-state flag, format error (step 8)
//   image    CRC of the stored image words; ECS ROM words; EXEC, GROM and
//            Intellivoice ROMs
//   ss0      the 16 state words after the load
//   A        machine reset, the 64K space (16 blocks of 4K)
//   mapped   the mapped-space CRC of tools/mapper/README.md (each paged range's
//            pages read to find its last mapped page)
//   B        each 4K range at pages 1, 2, 3 and 15 ($xA5y to $xFFF)
//   C        a write to every address (pattern P), then the space
//   D        page selects (r + 5) & 15, machine reset: state words ssd, the
//            space
//   E        page selects r & 3, state words ss1, the space
//   Z        all state words written 0: state words ssz (all 0), the space
//            (nothing may answer)
//   F        ss1 written back: state words ss2 and the space (= E)
// Each block is printed as a CRC32 over 3 bytes per word: {hit | attr << 1
// | paged << 5} (attr = the window's {B, N, W, R}), data high, data low
// (data $FFFF when not answered). The C phase's writes reach the page
// selects and the Intellicart bank registers ($0040-$005F) too. The
// Python side computes every line from the model and compares.
//
//   hazard   after all that, the host reads a slot (0x0080) and sends "all
//            complete" (0x008F) again without a cartridge stream: the
//            loader must not run its finish again (busy stays low, the page
//            selects stay): "hazard busy B ready R" and the select words
//   reload   (+cfgclear2=1: the data table lists the CFG slot with size 0
//            for the reload, as with no CFG chosen; without it, a CFG of the
//            first load stays listed and applies to the second cartridge)
//            with +cart2=, a user reload of another cartridge in the same
//            session (no power-on reset): reset enter, its 0x0082 with its
//            own size, its bytes, the data table with its length (or no
//            entry with +notable2=1), all complete, reset exit; the loader
//            must map it: "reload status", "reload slots", "reload image",
//            the state words rss and, after a machine reset, the space R
//
// +cart= +exec= +grom= +ecs= +ivoice= (files; a missing one is not loaded),
// +lenadj=N adds N to the cartridge's size in the data table (a refused
// load: the loader must map nothing and set err), +reqadj=N adds N to the
// size the host gives with 0x0082 for the cartridge (the table's length is
// used, err[4] set), +notable=1 leaves the cartridge out of the data table
// (the 0x0082 size is used), +out= (result file), +gap=N (bridge clocks
// between writes, default 75, +jitter=N adds 0..N-1), +pad=HH (pad byte),
// +dtfirst=0/1, +seed=N, +cart2= and +notable2=1 (reload); +cfg= (the CFG
// slot), +cfglenadj=N (added to the CFG's size in the data table),
// +cfgnotable=1 (no CFG entry in the table).
//
// SPDX-License-Identifier: MIT

`timescale 1ns / 1ps
`default_nettype none

module tb_loader;

    // clk_74a 74.25 MHz; clk_sys 12 x 3.579545 MHz (asynchronous to it)
    localparam real HALF_74 = 1.0e9 / 74.25e6 / 2.0;
    localparam real HALF_SYS = 1.0e9 / (12.0 * 315.0e6 / 88.0) / 2.0;
    logic clk_74a = 1'b0, clk_sys = 1'b0;
    initial forever #(HALF_74) clk_74a = ~clk_74a;
    initial begin #3.7; forever #(HALF_SYS) clk_sys = ~clk_sys; end

    int fails = 0;
    int outf;
    task automatic check(input bit ok, input string what);
        if (!ok) begin
            $display("  FAIL  %s", what);
            fails++;
        end
    endtask

    // ------------------------------------------------------------- bridge
    logic [31:0] bridge_addr = 32'd0, bridge_wr_data = 32'd0;
    logic        bridge_rd = 1'b0, bridge_wr = 1'b0;
    wire  logic [31:0] cmd_bridge_rd_data;
    wire  logic  reset_n;
    wire  logic  dataslot_allcomplete;
    wire  logic        dataslot_requestwrite;
    wire  logic [15:0] dataslot_requestwrite_id;
    wire  logic [31:0] dataslot_requestwrite_size;
    wire  logic [9:0]  datatable_addr;
    wire  logic        datatable_wren;
    wire  logic [31:0] datatable_data, datatable_q;
    /* verilator lint_off PINCONNECTEMPTY */
    core_bridge_cmd icb (
        .clk(clk_74a), .reset_n(reset_n),
        .bridge_endian_little(1'b0), .bridge_addr(bridge_addr), .bridge_rd(bridge_rd),
        .bridge_rd_data(cmd_bridge_rd_data), .bridge_wr(bridge_wr), .bridge_wr_data(bridge_wr_data),
        .status_boot_done(1'b1), .status_setup_done(1'b1), .status_running(reset_n),
        .dataslot_requestread(), .dataslot_requestread_id(),
        .dataslot_requestread_ack(1'b1), .dataslot_requestread_ok(1'b1),
        .dataslot_requestwrite(dataslot_requestwrite), .dataslot_requestwrite_id(dataslot_requestwrite_id),
        .dataslot_requestwrite_size(dataslot_requestwrite_size),
        .dataslot_requestwrite_ack(1'b1), .dataslot_requestwrite_ok(1'b1),
        .dataslot_update(), .dataslot_update_id(), .dataslot_update_size(),
        .dataslot_allcomplete(dataslot_allcomplete),
        .rtc_epoch_seconds(), .rtc_date_bcd(), .rtc_time_bcd(), .rtc_valid(),
        .savestate_supported(1'b0), .savestate_addr(32'h5000_0000), .savestate_size(32'd0),
        .savestate_maxloadsize(32'd0),
        .savestate_start(), .savestate_start_ack(1'b0), .savestate_start_busy(1'b0),
        .savestate_start_ok(1'b0), .savestate_start_err(1'b0),
        .savestate_load(), .savestate_load_ack(1'b0), .savestate_load_busy(1'b0),
        .savestate_load_ok(1'b0), .savestate_load_err(1'b0),
        .osnotify_inmenu(),
        .target_dataslot_read(1'b0), .target_dataslot_write(1'b0),
        .target_dataslot_getfile(1'b0), .target_dataslot_openfile(1'b0),
        .target_dataslot_ack(), .target_dataslot_done(), .target_dataslot_err(),
        .target_dataslot_id(16'd0), .target_dataslot_slotoffset(32'd0),
        .target_dataslot_bridgeaddr(32'd0), .target_dataslot_length(32'd0),
        .target_buffer_param_struct(), .target_buffer_resp_struct(),
        .datatable_addr(datatable_addr), .datatable_wren(datatable_wren),
        .datatable_data(datatable_data), .datatable_q(datatable_q)
    );
    /* verilator lint_on PINCONNECTEMPTY */

    wire logic        ioctl_wr;
    wire logic [27:0] ioctl_addr;
    wire logic [7:0]  ioctl_dout;
    data_loader #(
        .ADDRESS_MASK_UPPER_4(4'h0), .ADDRESS_SIZE(28), .WRITE_MEM_CLOCK_DELAY(4),
        .WRITE_MEM_EN_CYCLE_LENGTH(1), .OUTPUT_WORD_SIZE(1)
    ) loader (
        .clk_74a(clk_74a), .clk_memory(clk_sys),
        .bridge_wr(bridge_wr), .bridge_endian_little(1'b0),
        .bridge_addr(bridge_addr), .bridge_wr_data(bridge_wr_data),
        .write_en(ioctl_wr), .write_addr(ioctl_addr), .write_data(ioctl_dout)
    );

    wire logic [31:0] cart_len, cfg_len;
    wire logic [1:0]  len_chk;
    wire logic        len_valid, cfg_inlist;
    apf_datatable dtab (
        .clk(clk_74a), .allcomplete(dataslot_allcomplete),
        .wr_req(dataslot_requestwrite), .wr_id(dataslot_requestwrite_id),
        .wr_size(dataslot_requestwrite_size),
        .dt_addr(datatable_addr), .dt_wren(datatable_wren), .dt_data(datatable_data),
        .dt_q(datatable_q), .cart_len(cart_len), .len_chk(len_chk), .cfg_len(cfg_len),
        .cfg_inlist(cfg_inlist), .len_valid(len_valid)
    );

    // ---------------------------------------------------------------- DUT
    logic        reset = 1'b1, mreset = 1'b0;
    logic        bus_req = 1'b0, bus_we = 1'b0;
    logic [15:0] bus_addr = 16'd0, bus_wdata = 16'd0;
    wire  logic  bus_ack, bus_hit, bus_paged;
    wire  logic [15:0] bus_rdata;
    wire  logic [3:0]  bus_attr;
    wire  logic [63:0] pg_sel;
    logic        aux_req = 1'b0;
    logic [16:0] aux_addr = 17'd0;
    wire  logic  aux_ack;
    wire  logic [15:0] aux_rdata;
    logic [11:0] exec_addr = 12'd0;
    logic [10:0] grom_addr = 11'd0, ivoice_addr = 11'd0;
    wire  logic [9:0]  exec_q;
    wire  logic [7:0]  grom_q, vgrom_q, ivoice_q;
    wire  logic        ready, busy, hit, noss;
    wire  logic [5:0]  err;
    wire  logic [7:0]  fmt_err;
    wire  logic [31:0] cfg_crc;
    wire  logic [1:0]  len_st;
    wire  logic [11:0] slot_st;
    wire  logic [31:0] crc;
    wire  logic [16:0] words;
    wire  logic [7:0]  layout, flags;
    logic [15:0] ss_addr = 16'd0;
    logic        ss_we = 1'b0;
    logic [31:0] ss_wdata = 32'd0;
    wire  logic [31:0] ss_rdata;
    wire  logic [16:0] sram_a;
    wire  logic [15:0] sram_dq_out, sram_dq_in;
    wire  logic        sram_dq_oe, sram_oe_n, sram_we_n, sram_ub_n, sram_lb_n;

    intv_media #(
        .CRC_HEX(`CRC_HEX), .LAYOUT_HEX(`LAYOUT_HEX)
    ) dut (
        .clk(clk_sys), .reset(reset), .mreset(mreset),
        .ld_wr(ioctl_wr), .ld_addr(ioctl_addr), .ld_data(ioctl_dout),
        .len_valid(len_valid), .cart_len(cart_len), .len_chk(len_chk),
        .cfg_len(cfg_len), .cfg_inlist(cfg_inlist),
        .bus_req(bus_req), .bus_we(bus_we), .bus_addr(bus_addr), .bus_wdata(bus_wdata),
        .bus_ack(bus_ack), .bus_rdata(bus_rdata), .bus_hit(bus_hit),
        .bus_attr(bus_attr), .bus_paged(bus_paged), .pg_rst(64'd0), .pg_sel(pg_sel),
        .aux_req(aux_req), .aux_we(1'b0), .aux_addr(aux_addr), .aux_wdata(16'd0), .aux_be(2'b11),
        .aux_ack(aux_ack), .aux_rdata(aux_rdata),
        .exec_addr(exec_addr), .exec_q(exec_q), .grom_addr(grom_addr), .grom_q(grom_q),
        .vgrom_addr(grom_addr), .vgrom_q(vgrom_q),
        .ivoice_addr(ivoice_addr), .ivoice_q(ivoice_q),
        .ready(ready), .busy(busy), .err(err), .fmt_err(fmt_err), .len_st(len_st), .slot_st(slot_st),
        .crc(crc), .words(words), .layout(layout), .flags(flags), .hit(hit),
        .cfg_crc(cfg_crc), .noss(noss),
        .ss_addr(ss_addr), .ss_we(ss_we), .ss_wdata(ss_wdata), .ss_rdata(ss_rdata),
        .sram_a(sram_a), .sram_dq_out(sram_dq_out), .sram_dq_oe(sram_dq_oe),
        .sram_dq_in(sram_dq_in), .sram_oe_n(sram_oe_n), .sram_we_n(sram_we_n),
        .sram_ub_n(sram_ub_n), .sram_lb_n(sram_lb_n)
    );

    sram_as6c2016 sram (
        .clk(clk_sys), .a(sram_a), .dq_w(sram_dq_out), .dq_oe(sram_dq_oe), .dq_r(sram_dq_in),
        .oe_n(sram_oe_n), .we_n(sram_we_n), .ub_n(sram_ub_n), .lb_n(sram_lb_n)
    );

    // ------------------------------------------------------------- CRC32
    function automatic logic [31:0] crc_byte(input logic [31:0] c, input logic [7:0] d);
        logic [31:0] r;
        r = c ^ {24'd0, d};
        for (int i = 0; i < 8; i++)
            r = r[0] ? (r >> 1) ^ 32'hEDB88320 : r >> 1;
        return r;
    endfunction
    function automatic logic [31:0] crc_word(input logic [31:0] c, input logic [15:0] w);
        return crc_byte(crc_byte(c, w[15:8]), w[7:0]);
    endfunction

    // --------------------------------------------------------- host side
    int gap = 75, jitter = 0, seed = 1, dtfirst = 0, lenadj = 0, reqadj = 0, notable = 0;
    int cfglenadj = 0, cfgnotable = 0;
    logic [7:0] pad = 8'hA5;

    task automatic bwrite(input logic [31:0] a, input logic [31:0] d);
        @(negedge clk_74a);
        bridge_addr = a; bridge_wr_data = d; bridge_wr = 1'b1;
        @(negedge clk_74a);
        bridge_wr = 1'b0;
        repeat (gap + (jitter > 0 ? $urandom_range(jitter - 1, 0) : 0)) @(negedge clk_74a);
    endtask
    task automatic bread(input logic [31:0] a, output logic [31:0] d);
        @(negedge clk_74a);
        bridge_addr = a; bridge_rd = 1'b1;
        @(negedge clk_74a);
        bridge_rd = 1'b0;
        repeat (4) @(negedge clk_74a);
        d = cmd_bridge_rd_data;
    endtask
    task automatic host_cmd(input logic [15:0] cmd, input logic [31:0] p20, input logic [31:0] p24);
        logic [31:0] st;
        int n;
        bwrite(32'hF800_0020, p20);
        bwrite(32'hF800_0024, p24);
        bwrite(32'hF800_0000, {16'h434D, cmd});
        n = 0;
        do begin
            bread(32'hF800_0000, st);
            n++;
        end while (st[31:16] != 16'h4F4B && n < 1000);
        check(n < 1000, $sformatf("host command %04X answered", cmd));
    endtask

    // files
    localparam int FMAX = 262144;             // bytes per slot file in this bench
    byte unsigned fdata [6][FMAX];
    int           fsize [6];
    logic         floaded [6];
    string        fname [6];
    localparam logic [31:0] SLOT_ADDR [6] = '{32'h0000_0000, 32'h0100_0000, 32'h0200_0000,
                                               32'h0300_0000, 32'h0400_0000, 32'h0500_0000};
    task automatic read_file(input int s, input string plus);
        int fd, c;
        floaded[s] = 1'b0;
        fsize[s] = 0;
        if (!$value$plusargs({plus, "=%s"}, fname[s])) return;
        fd = $fopen(fname[s], "rb");
        if (fd == 0) begin check(0, {"open ", fname[s]}); return; end
        while ((c = $fgetc(fd)) != -1 && fsize[s] < FMAX) begin
            fdata[s][fsize[s]] = byte'(c);
            fsize[s]++;
        end
        check(c == -1, {"file fits the bench: ", fname[s]});
        $fclose(fd);
        floaded[s] = 1'b1;
    endtask
    task automatic send_slot(input int s);
        int n;
        logic [31:0] w;
        n = fsize[s];
        host_cmd(16'h0082, 32'h100 + s, n + (s == 0 ? reqadj : 0));
        for (int i = 0; i < n; i += 4) begin
            w = 32'd0;
            for (int k = 0; k < 4; k++)
                w[31 - 8*k -: 8] = (i + k < n) ? fdata[s][i + k] : pad;
            bwrite(SLOT_ADDR[s] + i, w);
        end
    endtask
    task automatic send_table();
        // data.json order: 0x100 .. 0x106; size 0 for a slot not loaded
        for (int s = 0; s < 7; s++) begin
            bwrite(32'hF800_2000 + 8 * s, ((s == 0 && notable != 0) || (s == 1 && cfgnotable != 0)) ? 32'h1FF
                                                                                               : 32'h100 + s);
            bwrite(32'hF800_2004 + 8 * s, (s < 6 && floaded[s]) ? fsize[s] + (s == 0 ? lenadj : 0)
                                                                + (s == 1 ? cfglenadj : 0) : 0);
        end
    endtask

    // ---------------------------------------------------- core-side ports
    task automatic cart_op(input logic we, input logic [15:0] a, input logic [15:0] d,
                           output logic [23:0] r);
        int n;
        @(negedge clk_sys);
        bus_req = 1'b1; bus_we = we; bus_addr = a; bus_wdata = d;
        @(negedge clk_sys);
        bus_req = 1'b0;
        n = 0;
        while (!bus_ack && n < 100) begin @(negedge clk_sys); n++; end
        if (n >= 100) begin check(0, $sformatf("cart port answers at %04X", a)); r = 24'd0; return; end
        r = {2'd0, bus_paged, bus_attr, bus_hit, bus_rdata};
    endtask
    task automatic cart_wr(input logic [15:0] a, input logic [15:0] d);
        logic [23:0] r;
        cart_op(1'b1, a, d, r);
    endtask
    task automatic aux_rd(input logic [16:0] a, output logic [15:0] d);
        int n;
        @(negedge clk_sys);
        aux_req = 1'b1; aux_addr = a;
        n = 0;
        do begin @(negedge clk_sys); n++; end while (!aux_ack && n < 100);
        aux_req = 1'b0;
        d = aux_rdata;
        check(n < 100, "aux port answers");
    endtask
    task automatic ss_rd(input int i, output logic [31:0] d);
        @(negedge clk_sys);
        ss_addr = {8'h0B, 8'(i)};
        @(negedge clk_sys);
        d = ss_rdata;
    endtask
    task automatic ss_wr(input int i, input logic [31:0] d);
        @(negedge clk_sys);
        ss_addr = {8'h0B, 8'(i)}; ss_wdata = d; ss_we = 1'b1;
        @(negedge clk_sys);
        ss_we = 1'b0;
    endtask
    task automatic machine_reset();
        @(negedge clk_sys); mreset = 1'b1;
        @(negedge clk_sys); mreset = 1'b0;
    endtask

    // block r (4K words) through the cart port -> CRC; also the mapped-space
    // words (ROM as read, $FFFF for RAM and not answered) into mcrc
    logic [31:0] mcrc;
    task automatic block(input int r, output logic [31:0] c, input bit mapped_rom_only, input bit mapped_any);
        logic [23:0] q;
        logic [15:0] v;
        c = 32'hFFFFFFFF;
        for (int i = 0; i < 4096; i++) begin
            cart_op(1'b0, 16'(r * 4096 + i), 16'd0, q);
            c = crc_byte(c, {2'd0, q[21:16]});
            c = crc_word(c, q[15:0]);
            if (mapped_rom_only) begin
                v = (q[16] && q[18:17] == 2'd1) ? q[15:0] : 16'hFFFF;
                mcrc = crc_word(mcrc, v);
            end else if (mapped_any) begin
                v = q[16] ? q[15:0] : 16'hFFFF;
                mcrc = crc_word(mcrc, v);
            end
        end
        c = ~c;
    endtask
    task automatic wait_ready();
        int to;
        to = 0;
        while (!(ready && !busy) && to < 2000000) begin @(negedge clk_sys); to++; end
        check(to < 2000000, "loader ready");
        repeat (10) @(negedge clk_sys);
    endtask
    task automatic image_crc(input string tag);
        logic [31:0] c;
        logic [15:0] v;
        c = 32'hFFFFFFFF;
        for (int i = 0; i < int'(words); i++) begin aux_rd(17'(i), v); c = crc_word(c, v); end
        $fdisplay(outf, "%s %08X", tag, ~c);
    endtask
    task automatic space(input string tag);
        logic [31:0] c;
        for (int r = 0; r < 16; r++) begin
            block(r, c, 1'b0, 1'b0);
            $fdisplay(outf, "%s %0d %08X", tag, r, c);
        end
    endtask

    // busy during the hazard step
    bit hz_mon = 1'b0, busy_seen = 1'b0;
    always @(negedge clk_sys) if (hz_mon && busy) busy_seen = 1'b1;

    // ------------------------------------------------------------ the run
    localparam int NSS = 16;
    logic [31:0] ss1 [NSS], ssq;
    logic [15:0] pgw [16][4096];
    bit          pgany [16];
    localparam int YS [4] = '{1, 2, 3, 15};
    initial begin : run
        string outn;
        logic [31:0] c, w32;
        logic [15:0] v;
        int n;
        int vgrom_bad = 0;
        if (!$value$plusargs("out=%s", outn)) outn = "tb_loader.out";
        void'($value$plusargs("gap=%d", gap));
        void'($value$plusargs("jitter=%d", jitter));
        void'($value$plusargs("pad=%h", pad));
        void'($value$plusargs("dtfirst=%d", dtfirst));
        void'($value$plusargs("lenadj=%d", lenadj));
        void'($value$plusargs("reqadj=%d", reqadj));
        void'($value$plusargs("notable=%d", notable));
        void'($value$plusargs("cfglenadj=%d", cfglenadj));
        void'($value$plusargs("cfgnotable=%d", cfgnotable));
        if ($value$plusargs("seed=%d", seed)) void'($urandom(seed));
        outf = $fopen(outn, "w");
        read_file(0, "cart");
        read_file(1, "cfg");
        read_file(2, "exec");
        read_file(3, "grom");
        read_file(4, "ecs");
        read_file(5, "ivoice");
        if ($test$plusargs("debug"))
            for (int s = 0; s < 6; s++)
                $display("slot %0d loaded %0d size %0d first %02X", s, floaded[s], fsize[s],
                         fsize[s] > 0 ? fdata[s][0] : 8'h00);

        repeat (20) @(negedge clk_sys);
        reset = 1'b0;
        repeat (50) @(negedge clk_74a);

        // ---- the host loads the slots
        host_cmd(16'h0010, 32'd0, 32'd0);
        if (dtfirst != 0) send_table();
        for (int s = 0; s < 6; s++) if (floaded[s]) send_slot(s);
        if (dtfirst == 0) send_table();
        host_cmd(16'h008F, 32'd0, 32'd0);
        host_cmd(16'h0011, 32'd0, 32'd0);
        wait_ready();

        // ---- status
        if ($test$plusargs("debug"))
            for (int s = 0; s < 6; s++) $display("loader cnt %0d = %0d", s, dut.loader.cnt[s]);
        $fdisplay(outf, "status crc %08X words %0d layout %0d flags %02X hit %0d err %0d lenst %0d",
                  crc, words, layout, flags, hit, err, len_st);
        $fdisplay(outf, "slots %03X", slot_st);
        $fdisplay(outf, "format cfgcrc %08X noss %0d ferr %02X", cfg_crc, noss, fmt_err);
        image_crc("image");
        if (floaded[4]) begin
            c = 32'hFFFFFFFF;
            for (int i = 0; i < 12288; i++) begin aux_rd(17'h10000 + 17'(i), v); c = crc_word(c, v); end
            $fdisplay(outf, "ecs %08X", ~c);
        end
        c = 32'hFFFFFFFF;
        for (int i = 0; i < 4096; i++) begin
            @(negedge clk_sys); exec_addr = 12'(i); @(negedge clk_sys); @(negedge clk_sys);
            c = crc_word(c, {6'd0, exec_q});
        end
        $fdisplay(outf, "exec %08X", ~c);
        c = 32'hFFFFFFFF;
        for (int i = 0; i < 2048; i++) begin
            @(negedge clk_sys); grom_addr = 11'(i); ivoice_addr = 11'(i); @(negedge clk_sys); @(negedge clk_sys);
            c = crc_byte(c, grom_q);
            if (vgrom_q !== grom_q) vgrom_bad++;     // the STIC's GROM port (step 4)
        end
        check(vgrom_bad == 0, $sformatf("STIC GROM port differs in %0d bytes", vgrom_bad));
        $fdisplay(outf, "grom %08X", ~c);
        c = 32'hFFFFFFFF;
        for (int i = 0; i < 2048; i++) begin
            @(negedge clk_sys); ivoice_addr = 11'(i); @(negedge clk_sys); @(negedge clk_sys);
            c = crc_byte(c, ivoice_q);
        end
        $fdisplay(outf, "ivoice %08X", ~c);
        for (int i = 0; i < NSS; i++) begin ss_rd(i, ssq); $fdisplay(outf, "ss0 %0d %08X", i, ssq); end

        // ---- A: the space at reset paging, and the mapped-space CRC
        machine_reset();
        mcrc = 32'hFFFFFFFF;
        for (int r = 0; r < 16; r++) begin
            block(r, c, 1'b1, 1'b0);
            $fdisplay(outf, "A %0d %08X", r, c);
        end
        ss_rd(4, ssq);                             // [15:0]: the paged ranges
        for (int r = 0; r < 16; r++) begin
            if (ssq[r]) begin
                int n;
                logic [23:0] q;
                n = 1;
                for (int y = 1; y < 16; y++) begin
                    cart_wr(16'(r * 4096 + 4095), 16'(r * 4096 + 32'hA50 + y));
                    pgany[y] = 1'b0;
                    for (int i = 0; i < 4096; i++) begin
                        cart_op(1'b0, 16'(r * 4096 + i), 16'd0, q);
                        pgw[y][i] = q[16] ? q[15:0] : 16'hFFFF;
                        if (q[18:17] != 2'd0) pgany[y] = 1'b1;
                    end
                    if (pgany[y]) n = y + 1;
                end
                for (int y = 1; y < n; y++)
                    for (int i = 0; i < 4096; i++) mcrc = crc_word(mcrc, pgw[y][i]);
                cart_wr(16'(r * 4096 + 4095), 16'(r * 4096 + 32'hA50));
            end
        end
        $fdisplay(outf, "mapped %08X", ~mcrc);

        // ---- B: pages 1, 2, 3, 15 of every range
        for (int r = 0; r < 16; r++) begin
            for (int k = 0; k < 4; k++) begin
                cart_wr(16'(r * 4096 + 4095), 16'(r * 4096 + 32'hA50 + YS[k]));
                block(r, c, 1'b0, 1'b0);
                $fdisplay(outf, "B %0d %0d %08X", r, YS[k], c);
            end
            cart_wr(16'(r * 4096 + 4095), 16'(r * 4096 + 32'hA50));
        end

        // ---- C: write everywhere, D: after a machine reset
        for (int a = 0; a < 65536; a++)
            cart_wr(16'(a), 16'(a * 32'h9E37 + 32'h1234));
        space("C");
        for (int r = 0; r < 16; r++)
            cart_wr(16'(r * 4096 + 4095), 16'(r * 4096 + 32'hA50 + ((r + 5) & 15)));
        machine_reset();
        for (int i = 0; i < NSS; i++) begin ss_rd(i, ssq); $fdisplay(outf, "ssd %0d %08X", i, ssq); end
        space("D");

        // ---- E, Z, F: the state round trip
        for (int r = 0; r < 16; r++)
            cart_wr(16'(r * 4096 + 4095), 16'(r * 4096 + 32'hA50 + (r & 3)));
        for (int i = 0; i < NSS; i++) begin ss_rd(i, ss1[i]); $fdisplay(outf, "ss1 %0d %08X", i, ss1[i]); end
        space("E");
        // ---- W: writes that must not select a page: another range's $xA5y at
        // $xFFF, the range's own at $xFFE and $xF7F (the selects must stay)
        for (int r = 0; r < 16; r++) begin
            cart_wr(16'(r * 4096 + 4095), 16'(((r + 1) & 15) * 4096 + 32'hA50 + ((r + 7) & 15)));
            cart_wr(16'(r * 4096 + 4094), 16'(r * 4096 + 32'hA50 + ((r + 9) & 15)));
            cart_wr(16'(r * 4096 + 3967), 16'(r * 4096 + 32'hA50 + ((r + 11) & 15)));
        end
        for (int i = 5; i < 7; i++) begin ss_rd(i, ssq); $fdisplay(outf, "ssw %0d %08X", i, ssq); end
        for (int i = 0; i < NSS; i++) ss_wr(i, 32'd0);
        for (int i = 0; i < NSS; i++) begin ss_rd(i, ssq); $fdisplay(outf, "ssz %0d %08X", i, ssq); end
        space("Z");
        for (int i = 0; i < NSS; i++) ss_wr(i, ss1[i]);
        for (int i = 0; i < NSS; i++) begin ss_rd(i, ssq); $fdisplay(outf, "ss2 %0d %08X", i, ssq); end
        space("F");

        // ---- hazard: a slot read and "all complete" again, no cartridge
        begin
            busy_seen = 1'b0;
            hz_mon = 1'b1;
            host_cmd(16'h0080, 32'h106, 32'd0);
            host_cmd(16'h008F, 32'd0, 32'd0);
            repeat (2000) @(negedge clk_sys);
            hz_mon = 1'b0;
            check(len_valid, "len_valid again after the second all complete");
            $fdisplay(outf, "hazard busy %0d ready %0d", busy_seen, ready);
            for (int i = 5; i < 15; i++) begin ss_rd(i, ssq); $fdisplay(outf, "ssh %0d %08X", i, ssq); end
        end

        // ---- reload: another cartridge, same session
        if ($test$plusargs("cart2=")) begin
            read_file(0, "cart2");
            reqadj = 0;
            lenadj = 0;
            notable = 0;
            void'($value$plusargs("notable2=%d", notable));
            if ($test$plusargs("cfgclear2")) floaded[1] = 1'b0;   // the table lists no CFG now
            host_cmd(16'h0010, 32'd0, 32'd0);
            if (dtfirst != 0) send_table();
            send_slot(0);
            if (dtfirst == 0) send_table();
            host_cmd(16'h008F, 32'd0, 32'd0);
            host_cmd(16'h0011, 32'd0, 32'd0);
            wait_ready();
            $fdisplay(outf, "reload status crc %08X words %0d layout %0d flags %02X hit %0d err %0d lenst %0d",
                      crc, words, layout, flags, hit, err, len_st);
            $fdisplay(outf, "reload slots %03X", slot_st);
            image_crc("reload image");
            for (int i = 0; i < NSS; i++) begin ss_rd(i, ssq); $fdisplay(outf, "rss %0d %08X", i, ssq); end
            machine_reset();
            space("R");
        end

        // ---- bench health
        check(sram.violations == 0, $sformatf("SRAM timing: %0d violations", sram.violations));
        check(loader.dcfifo_component.overflows == 0, "data_loader FIFO never overflows");
        $fdisplay(outf, "end");
        $fclose(outf);
        $display("sram writes %0d, violations %0d", sram.writes, sram.violations);
        if (fails == 0) $display("TB_LOADER run ok");
        else $display("TB_LOADER run FAIL (%0d)", fails);
        $finish;
    end

    initial begin
        #(4.0e9);
        $display("TB_LOADER run FAIL (timeout)");
        $finish;
    end

endmodule

`default_nettype wire
