// Intellivision core: the core's side of the APF data table (clk_74a).
//
// The host writes the data table (slot id, size) pairs at 0xF8002000 before
// "data slot access all complete" (command 0x008F); core_bridge_cmd keeps it
// in a dual-port RAM (mf_datatable, two clocks of read latency) whose port A
// is ours. This module
//   - writes the JLP flash slot's size (index JLP_IDX) as 0 until step 11
//     stores flash (DESIGN.md 13 item 17), as core_top did in step 1;
//   - on each rising edge of dataslot_allcomplete, scans the table for the
//     cartridge slot id (0x100) and reads its size: the file's length in
//     bytes, which the loader needs (tools/mapper/README.md "The loader's
//     CRC and length"). cart_len is set one clk_74a before len_valid and
//     then held, so a clk_sys synchroniser on len_valid alone is enough.
//     A table without the slot gives length 0 (the loader: no cartridge).
//     len_valid falls with dataslot_allcomplete (a new slot request).
//
// SPDX-License-Identifier: MIT

`default_nettype none

module apf_datatable #(
    parameter logic [31:0] SLOT_ID = 32'h0000_0100,
    parameter int          JLP_IDX = 6,
    parameter int          ENTRIES = 16        // pairs scanned
) (
    input  wire logic        clk,             // clk_74a
    input  wire logic        allcomplete,

    output logic [9:0]       dt_addr,
    output logic             dt_wren,
    output logic [31:0]      dt_data,
    input  wire logic [31:0] dt_q,

    output logic [31:0]      cart_len,
    output logic             len_valid
);

    typedef enum logic [2:0] {D_IDLE, D_ID, D_IDW, D_SIZE, D_SIZEW, D_SET} dstate_t;
    dstate_t     st = D_IDLE;
    logic        ac_d = 1'b0;
    logic [4:0]  i = 5'd0;
    logic [1:0]  w = 2'd0;

    initial begin
        dt_addr = 10'(2 * JLP_IDX + 1); dt_wren = 1'b0; dt_data = 32'd0;
        cart_len = 32'd0; len_valid = 1'b0;
    end

    always_ff @(posedge clk) begin
        ac_d <= allcomplete;
        dt_wren <= 1'b0;
        if (!allcomplete)
            len_valid <= 1'b0;
        case (st)
            D_IDLE: begin
                // the JLP size word, rewritten while idle
                dt_addr <= 10'(2 * JLP_IDX + 1);
                dt_data <= 32'd0;
                dt_wren <= 1'b1;
                if (allcomplete && !ac_d) begin
                    i  <= 5'd0;
                    st <= D_ID;
                end
            end
            D_ID: begin                              // read the id of pair i
                dt_addr <= {4'd0, i, 1'b0};
                w  <= 2'd3;
                st <= D_IDW;
            end
            D_IDW: if (w != 2'd0) w <= w - 2'd1;
                   else if (dt_q == SLOT_ID) begin
                       dt_addr <= {4'd0, i, 1'b1};
                       w  <= 2'd3;
                       st <= D_SIZEW;
                   end else if (i == 5'(ENTRIES - 1)) begin
                       cart_len <= 32'd0;            // no cartridge slot in the table
                       st <= D_SET;
                   end else begin
                       i  <= i + 5'd1;
                       st <= D_ID;
                   end
            D_SIZEW: if (w != 2'd0) w <= w - 2'd1;
                     else begin
                         cart_len <= dt_q;
                         st <= D_SET;
                     end
            D_SET: begin
                len_valid <= allcomplete;
                st <= D_IDLE;
            end
            default: st <= D_IDLE;
        endcase
    end

endmodule

`default_nettype wire
