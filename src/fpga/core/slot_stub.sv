// Intellivision core: step-1 stand-in for the loaders (DESIGN.md 5).
//
// The data loader's bytes arrive with their bridge address; bits 27:24 name
// the data slot (data.json, core_top.v's bridge map):
//   0 cartridge, 1 cartridge config, 2 EXEC, 3 GROM, 4 ECS ROM,
//   5 Intellivoice ROM
// Until the loaders exist (step 2: cartridge and system ROMs; step 8: CFG;
// step 9: ECS; step 10: Intellivoice), this module only counts each slot's
// bytes and reports whether the count is the expected size, for the test
// pattern. The expected sizes are the owner's files (DESIGN.md 5.6):
// EXEC 8,192 bytes, GROM 2,048, ECS 24,576, Intellivoice 2,048; any
// non-empty cartridge or config counts as right.
// Load-time only: nothing here is machine state (DESIGN.md 4.4).
//
// SPDX-License-Identifier: MIT

`default_nettype none

module slot_stub (
    input  wire logic        clk,
    input  wire logic        wr,          // one pulse per byte
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire logic [27:0] addr,        // [27:24] the slot; the offset is not needed
    /* verilator lint_on UNUSEDSIGNAL */
    output logic      [11:0] slot_st      // 2 bits a slot: 0 empty, 1 other size, 2 ok
);

    localparam logic [23:0] SIZE [6] = '{24'd0, 24'd0, 24'd8192, 24'd2048, 24'd24576, 24'd2048};

    logic [23:0] count [6];

    initial begin
        for (int i = 0; i < 6; i++)
            count[i] = 24'd0;
    end

    always_ff @(posedge clk) begin
        if (wr && addr[27:24] < 4'd6 && count[addr[26:24]] != 24'hFFFFFF)
            count[addr[26:24]] <= count[addr[26:24]] + 24'd1;
    end

    always_comb begin
        for (int i = 0; i < 6; i++) begin
            if (count[i] == 24'd0)
                slot_st[2*i +: 2] = 2'd0;
            else if (SIZE[i] == 24'd0 || count[i] == SIZE[i])
                slot_st[2*i +: 2] = 2'd2;
            else
                slot_st[2*i +: 2] = 2'd1;
        end
    end

endmodule

`default_nettype wire
