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
// The CFG (+cfg=) is not streamed: the CFG slot is a deferload slot and
// apf_cfgfetch (in apf_datatable) asks for it by name with target commands
// (+cfgpush=1 streams it as before build step 9b, for no current case). The
// host serves them while it waits (serve_target, as the Pocket polls
// 0xF8001000): 0x0190 gives the cartridge's path (+cartpath=; after a
// reload +cart2path=) in the struct at the given bridge address, big-endian
// bytes, NUL ended; 0x0192 reads the struct's path and opens the CFG when
// it names +cfgpath= (+cfg2path= for the reload's cartridge, which has a CFG
// only with +cfg2same=1, the same file), compared without case as FAT does,
// else answers 3 (not found); opened, it writes the CFG's size into the data
// table (+dtupdate=0: not; +dtcfgadj=N: the size plus N); 0x0180 writes the
// CFG's bytes [offset, offset + length) to the bridge address as 32-bit
// words (the last padded), or answers 2 when that runs past the file.
// "fetch res R len N" (apf_cfgfetch's res, the length used) follows the
// status.
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
//   K        the bank sweep: all 32 Intellicart bank registers set to v
//            (v = 0, 8, ... 248: each 2K of the Intellicart memory in turn),
//            then every 2K window whose first word is a bank window (attr B)
//            read: "K v CRC" (CRC of nothing = 0); the registers then go back
//            to their start. It reaches Intellicart memory no CPU address
//            maps at the start values (a CFG's [preload], fix 8)
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
//            selects stay; no CFG is fetched again): "hazard busy B ready R"
//            and the select words
//   reload   with +cart2=, a user reload of another cartridge in the same
//            session (no power-on reset): reset enter, its 0x0082 with its
//            own size, its bytes, the data table with its length (or no
//            entry with +notable2=1), all complete, reset exit; the loader
//            must map it, with the CFG fetched for its own name (+cart2path=;
//            +cfg2same=1: the first CFG's file under that name, else none):
//            "reload status", "reload fetch", "reload slots", "reload image",
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
    // Ready to run given up after 2^20 clk_74a (the Pocket's build: 5 s), past RTRDLY's 600,000
    core_bridge_cmd #(.RTR_GIVEUP(1 << 20)) icb (
        .clk(clk_74a), .reset_n(reset_n),
        .bridge_endian_little(1'b0), .bridge_addr(bridge_addr), .bridge_rd(bridge_rd),
        .bridge_rd_data(cmd_bridge_rd_data), .bridge_wr(bridge_wr), .bridge_wr_data(bridge_wr_data),
        .status_boot_done(1'b1), .status_setup_done(1'b1), .status_running(reset_n),
        .dataslot_requestread(), .dataslot_requestread_id(),
        .dataslot_requestread_ack(1'b1), .dataslot_requestread_ok(1'b1),
        .dataslot_requestwrite(dataslot_requestwrite), .dataslot_requestwrite_id(dataslot_requestwrite_id),
        .dataslot_requestwrite_size(dataslot_requestwrite_size),
        .dataslot_requestwrite_ack(1'b1), .dataslot_requestwrite_ok(1'b1),
        .dataslot_update(dataslot_update), .dataslot_update_id(dataslot_update_id), .dataslot_update_size(),
        .dataslot_allcomplete(dataslot_allcomplete),
        .rtc_epoch_seconds(), .rtc_date_bcd(), .rtc_time_bcd(), .rtc_valid(),
        .savestate_supported(1'b0), .savestate_addr(32'h5000_0000), .savestate_size(32'd0),
        .savestate_maxloadsize(32'd0),
        .savestate_start(), .savestate_start_ack(1'b0), .savestate_start_busy(1'b0),
        .savestate_start_ok(1'b0), .savestate_start_err(1'b0),
        .savestate_load(), .savestate_load_ack(1'b0), .savestate_load_busy(1'b0),
        .savestate_load_ok(1'b0), .savestate_load_err(1'b0),
        .osnotify_inmenu(),
        .target_dataslot_read(t_read), .target_dataslot_write(1'b0),
        .target_dataslot_getfile(t_getfile), .target_dataslot_openfile(t_openfile),
        .target_dataslot_ack(), .target_dataslot_done(t_done), .target_dataslot_err(t_err),
        .target_dataslot_id(t_id), .target_dataslot_slotoffset(t_offset),
        .target_dataslot_bridgeaddr(t_bridgeaddr), .target_dataslot_length(t_length),
        .target_buffer_param_struct(32'h6000_0000), .target_buffer_resp_struct(32'h6000_0000),
        .datatable_addr(datatable_addr), .datatable_wren(datatable_wren),
        .datatable_data(datatable_data), .datatable_q(datatable_q),
        .target_state(tstate)
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
        .bridge_wr(loader_wr), .bridge_endian_little(1'b0),
        .bridge_addr(bridge_addr), .bridge_wr_data(bridge_wr_data),
        .write_en(ioctl_wr), .write_addr(ioctl_addr), .write_data(ioctl_dout)
    );

    wire logic [31:0] cart_len, cfg_len;
    wire logic [1:0]  len_chk;
    wire logic        len_valid, cfg_inlist;
    wire logic        t_read, t_getfile, t_openfile, t_done;
    wire logic [2:0]  t_err, fetch_res, fetch_to;
    wire logic        dataslot_update, loader_wr, d_ac, d_req, d_upd;
    wire logic [15:0] dataslot_update_id;
    wire logic [1:0]  d_phase;
    wire logic [3:0]  tstate;
    wire logic        dt_setup_done;          // apf_datatable's first-fetch flag (diagnostics; status_setup_done
                                              // is configuration again, 2026-10-31, as core_top's)
    // Ready to run acked (core_top's rtr_ok): the target state leaves WAITRESULT_RTR the first time
    logic             rtr_wait = 1'b0, rtr_ok = 1'b0;
    always_ff @(posedge clk_74a) begin
        if (tstate == 4'd14) rtr_wait <= 1'b1;
        else if (rtr_wait) rtr_ok <= 1'b1;
    end
    /* verilator lint_off UNUSEDSIGNAL */
    wire logic        cfg_wr_ok;
    /* verilator lint_on UNUSEDSIGNAL */
    wire logic [15:0] t_id;
    wire logic [31:0] t_offset, t_bridgeaddr, t_length, st_rd_data, fetch_len;
    /* verilator lint_off UNUSEDSIGNAL */
    wire logic [2:0]  fetch_code;
    /* verilator lint_on UNUSEDSIGNAL */
    // the fetch's watchdog: 2^18 clk_74a (3.5 ms; the Pocket's build: 2^26), past the bench's
    // longest answer and inside wait_ready's limit; the hold after a timeout 1,000 (the Pocket's: 4 s);
    // setup_done's safety 2^24 clk_74a (the Pocket's: 3 s), past the longest load from configuration
    apf_datatable #(.WD_BITS(18), .TO_HOLD(1000), .SAFE(1 << 24)) dtab (
        .clk(clk_74a), .allcomplete(dataslot_allcomplete),
        .wr_req(dataslot_requestwrite), .wr_id(dataslot_requestwrite_id),
        .wr_size(dataslot_requestwrite_size),
        .dt_addr(datatable_addr), .dt_wren(datatable_wren), .dt_data(datatable_data),
        .dt_q(datatable_q), .cart_len(cart_len), .len_chk(len_chk), .cfg_len(cfg_len),
        .cfg_inlist(cfg_inlist), .len_valid(len_valid),
        .t_read(t_read), .t_getfile(t_getfile), .t_openfile(t_openfile), .t_id(t_id),
        .t_offset(t_offset), .t_bridgeaddr(t_bridgeaddr), .t_length(t_length),
        .t_done(t_done), .t_err(t_err),
        .bridge_addr(bridge_addr), .bridge_wr(bridge_wr), .bridge_wr_data(bridge_wr_data),
        .bridge_rd(bridge_rd), .st_rd_data(st_rd_data),
        .fetch_res(fetch_res), .fetch_code(fetch_code), .fetch_len(fetch_len),
        .upd(dataslot_update), .upd_id(dataslot_update_id),
        .fetch_to(fetch_to), .cfg_wr_ok(cfg_wr_ok), .loader_wr(loader_wr),
        .d_ac(d_ac), .d_req(d_req), .d_upd(d_upd), .d_phase(d_phase), .setup_done(dt_setup_done), .rtr_ok(rtr_ok)
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
    wire  logic [1:0]  ecs_auto;              // step 9: the Auto rule's mode
    wire  logic        voice_auto;            // step 10: the Intellivoice's Auto rule
    /* verilator lint_off UNUSEDSIGNAL */
    wire  logic        ecs_rom_ok;
    /* verilator lint_on UNUSEDSIGNAL */
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
        .ecs_on(1'b0), .ecs_pg(12'd0), .ecs_auto(ecs_auto), .ecs_rom_ok(ecs_rom_ok), .voice_auto(voice_auto),
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
    int cfgpush = 0, dtupdate = 1, dtcfgadj = 0, cfg2same = 0;
    // 0.0.14: the host never answers target command +nohost=K (hex; 0: any) or never acks Ready to
    // run (+rtrhold=1); with +late=1 it answers them once the first load has mapped
    int nohost = -1, rtrhold = 0, late = 0;
    // 0.0.15: +rtrdelay=N: the host acks Ready to run only N clk_74a after it sent all complete (the
    // owner's Pocket: more than the 0.9 s watchdog on a first load, never during a Core Settings
    // reload, 0.0.14's photos); +acdelay=N: the host starts loading only N clk_74a after configuration
    // (setup_done's safety must raise it first)
    int rtrdelay = 0, acdelay = 0;
    longint cyc74 = 0, ac_cyc = -1;
    bit early = 1'b0;                          // setup_done was up when all complete was sent
    always @(posedge clk_74a) cyc74 <= cyc74 + 1;
    bit hold = 1'b1;
    string cartpath = "", cfgpath = "", cart2path = "", cfg2path = "";
    bit    reloaded = 1'b0, cfg_open = 1'b0;
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
        d = a[31:24] == 8'h60 ? st_rd_data : cmd_bridge_rd_data;    // core_top's read mux
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
        // data.json order: 0x100 .. 0x106; size 0 for a slot not loaded (and
        // for the deferload CFG slot, unless it is streamed: +cfgpush)
        for (int s = 0; s < 7; s++) begin
            bwrite(32'hF800_2000 + 8 * s, ((s == 0 && notable != 0) || (s == 1 && cfgnotable != 0)) ? 32'h1FF
                                                                                               : 32'h100 + s);
            bwrite(32'hF800_2004 + 8 * s, (s < 6 && floaded[s] && (s != 1 || cfgpush != 0))
                                          ? fsize[s] + (s == 0 ? lenadj : 0) + (s == 1 ? cfglenadj : 0) : 0);
        end
    endtask

    // ---------------------------------------------- target commands (host)
    function automatic string lower(input string x);
        string r;
        r = x;
        for (int i = 0; i < r.len(); i++)
            if (r.getc(i) >= 8'h41 && r.getc(i) <= 8'h5A) r.putc(i, r.getc(i) + 8'd32);
        return r;
    endfunction
    int ntarget = 0;
    task automatic serve_target();
        logic [31:0] t0, p20, p24, p28, p2c, w;
        logic [2:0]  code;
        string       path, want;
        bread(32'hF800_1000, t0);
        if (t0[31:16] != 16'h636D) return;
        if (hold && ((nohost >= 0 && (nohost == 0 || t0[15:0] == 16'(nohost)) && t0[15:0] != 16'h0140)
                     || (rtrhold != 0 && t0[15:0] == 16'h0140)))
            return;                                                // not answered (yet)
        if (rtrdelay > 0 && t0[15:0] == 16'h0140 && (ac_cyc < 0 || cyc74 - ac_cyc < longint'(rtrdelay)))
            return;                                                // the Pocket acks it late
        ntarget++;
        bwrite(32'hF800_1000, {16'h6275, t0[15:0]});               // busy
        bread(32'hF800_1020, p20);
        bread(32'hF800_1024, p24);
        bread(32'hF800_1028, p28);
        bread(32'hF800_102C, p2c);
        code = 3'd1;                                               // slot not defined
        case (t0[15:0])
            16'h0190: if (p20 == 32'h100) begin
                path = reloaded ? cart2path : cartpath;
                for (int i = 0; i < 64; i++) begin
                    w = 32'd0;
                    for (int k = 0; k < 4; k++)
                        w[31 - 8*k -: 8] = (4*i + k < path.len()) ? path.getc(4*i + k) : 8'h00;
                    bwrite(p24 + 4*i, w);
                end
                code = 3'd0;
            end
            16'h0192: if (p20 == 32'h101) begin
                path = "";
                for (int i = 0; i < 64; i++) begin
                    bread(p24 + 4*i, w);
                    for (int k = 0; k < 4; k++)
                        if (path.len() == 4*i + k && w[31 - 8*k -: 8] != 8'h00)
                            path = $sformatf("%s%c", path, w[31 - 8*k -: 8]);
                end
                bread(p24 + 32'h100, w);
                check(w == 32'd0, "open: flags 0");
                want = reloaded ? (cfg2same != 0 ? cfg2path : "") : cfgpath;
                if (floaded[1] && want != "" && lower(path) == lower(want)) begin
                    cfg_open = 1'b1;
                    code = 3'd0;
                    if (dtupdate != 0) begin
                        bwrite(32'hF800_2008, 32'h101);
                        bwrite(32'hF800_200C, fsize[1] + dtcfgadj);
                    end
                end else begin
                    cfg_open = 1'b0;
                    code = 3'd3;                                   // file not found
                end
            end
            16'h0180: if (p20 == 32'h101 && cfg_open) begin
                if (p24 + p2c > fsize[1] || p2c == 32'd0)
                    code = 3'd2;                                   // out of range
                else begin
                    for (int i = 0; i < int'(p2c); i += 4) begin
                        w = 32'd0;
                        for (int k = 0; k < 4; k++)
                            w[31 - 8*k -: 8] = (i + k < int'(p2c)) ? fdata[1][int'(p24) + i + k] : pad;
                        bwrite(p28 + i, w);
                    end
                    code = 3'd0;
                end
            end
            default: ;
        endcase
        bwrite(32'hF800_1000, {16'h6F6B, 13'd0, code});            // done
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
        // the host serves the core's target commands while it waits
        while (!(ready && !busy) && to < 40000) begin
            serve_target();
            repeat (100) @(negedge clk_sys);
            to++;
        end
        check(to < 40000, "loader ready");
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
        void'($value$plusargs("cfgpush=%d", cfgpush));
        void'($value$plusargs("dtupdate=%d", dtupdate));
        void'($value$plusargs("dtcfgadj=%d", dtcfgadj));
        void'($value$plusargs("cfg2same=%d", cfg2same));
        void'($value$plusargs("nohost=%h", nohost));
        void'($value$plusargs("rtrhold=%d", rtrhold));
        void'($value$plusargs("rtrdelay=%d", rtrdelay));
        void'($value$plusargs("acdelay=%d", acdelay));
        void'($value$plusargs("late=%d", late));
        void'($value$plusargs("cartpath=%s", cartpath));
        void'($value$plusargs("cfgpath=%s", cfgpath));
        void'($value$plusargs("cart2path=%s", cart2path));
        void'($value$plusargs("cfg2path=%s", cfg2path));
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
        if (acdelay > 0) begin
            while (cyc74 < longint'(acdelay)) begin serve_target(); repeat (1000) @(negedge clk_74a); end
        end
        host_cmd(16'h0010, 32'd0, 32'd0);
        if (dtfirst != 0) send_table();
        for (int s = 0; s < 6; s++) if (floaded[s] && (s != 1 || cfgpush != 0)) send_slot(s);
        if (dtfirst == 0) send_table();
        early = dt_setup_done;
        host_cmd(16'h008F, 32'd0, 32'd0);
        ac_cyc = cyc74;
        host_cmd(16'h0011, 32'd0, 32'd0);
        wait_ready();
        // the host serves the core's commands until its request channel is idle (Ready to run acked),
        // or a bound: held commands (+nohost, +rtrhold) stay pending
        begin
            longint t0c;
            t0c = cyc74;
            while (tstate != 4'd0 && cyc74 - t0c < longint'(rtrdelay) + 200000) begin
                serve_target(); repeat (1000) @(negedge clk_74a);
            end
        end

        // ---- status
        if ($test$plusargs("debug"))
            for (int s = 0; s < 6; s++) $display("loader cnt %0d = %0d", s, dut.loader.cnt[s]);
        $fdisplay(outf, "status crc %08X words %0d layout %0d flags %02X hit %0d err %0d lenst %0d",
                  crc, words, layout, flags, hit, err, len_st);
        $fdisplay(outf, "fetch res %0d len %0d to %0d", fetch_res, fetch_res == 3'd1 || fetch_res == 3'd2 ? fetch_len : 0,
                  fetch_to);
        $fdisplay(outf, "diag ac %0d req %0d upd %0d phase %0d tstate %0d sd %0d early %0d", d_ac, d_req, d_upd,
                  d_phase, tstate, dt_setup_done, early);
        // a command held past the watchdog, answered now (+late): a read's bytes must not reach
        // the loader (the CFG slot stays empty), and the next commands must still work
        if (late != 0) begin
            hold = 1'b0;
            for (int i = 0; i < 40; i++) begin serve_target(); repeat (100) @(negedge clk_sys); end
            $fdisplay(outf, "late slots %03X tstate %0d", slot_st, tstate);
        end
        $fdisplay(outf, "slots %03X", slot_st);
        $fdisplay(outf, "ecs auto %0d", ecs_auto);
        $fdisplay(outf, "voice auto %0d", voice_auto);
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

        // ---- K: the bank sweep (every 2K of the Intellicart memory through
        // the bank windows), then the bank registers back at their start
        for (int k = 0; k < 32; k++) begin
            logic [23:0] q;
            for (int i = 0; i < 32; i++) cart_wr(16'(32'h40 + i), 16'(k * 8));
            c = 32'hFFFFFFFF;
            for (int w = 0; w < 32; w++) begin
                cart_op(1'b0, 16'(w * 2048), 16'd0, q);
                if (q[20])
                    for (int i = 0; i < 2048; i++) begin
                        cart_op(1'b0, 16'(w * 2048 + i), 16'd0, q);
                        c = crc_byte(c, {2'd0, q[21:16]});
                        c = crc_word(c, q[15:0]);
                    end
            end
            $fdisplay(outf, "K %0d %08X", k * 8, ~c);
        end
        for (int i = 0; i < 32; i++) cart_wr(16'(32'h40 + i), 16'({i[3:0], i[4], 3'd0}));

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
            for (int i = 0; i < 20; i++) begin serve_target(); repeat (100) @(negedge clk_sys); end
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
            reloaded = 1'b1;                                      // its path and its CFG (+cfg2same)
            host_cmd(16'h0010, 32'd0, 32'd0);
            if (dtfirst != 0) send_table();
            send_slot(0);
            if (dtfirst == 0) send_table();
            host_cmd(16'h008F, 32'd0, 32'd0);
            host_cmd(16'h0011, 32'd0, 32'd0);
            wait_ready();
            $fdisplay(outf, "reload status crc %08X words %0d layout %0d flags %02X hit %0d err %0d lenst %0d",
                      crc, words, layout, flags, hit, err, len_st);
            $fdisplay(outf, "reload fetch res %0d len %0d to %0d", fetch_res,
                      fetch_res == 3'd1 || fetch_res == 3'd2 ? fetch_len : 0, fetch_to);
            $fdisplay(outf, "reload slots %03X", slot_st);
            $fdisplay(outf, "reload ecs auto %0d", ecs_auto);
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
