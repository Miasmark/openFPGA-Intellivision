// Intellivision core: the 16 STIC colours as RGB888.
//
// First-light palette (DESIGN.md 6.1 and decision 4): MAME's intv_colors[]
// table, src/mame/mattel/intv.cpp:72-90 at MAME commit 3c6120b6
// (license BSD-3-Clause, copyright-holders Nathan Woods, Frank Palazzolo;
// the notice is in THIRD_PARTY_NOTICES.md). Only the sixteen values are
// taken. The colour order is the STIC's colour numbering (service manual
// p.60-61). A palette calibrated from a capture of the owner's console
// will replace it.
//
// SPDX-License-Identifier: MIT (this file's code); the values: BSD-3-Clause, MAME

`default_nettype none

module intv_palette (
    input  wire logic [3:0]  idx,
    output logic      [23:0] rgb
);

    always_comb begin
        case (idx)
            4'd0:  rgb = 24'h000000;   // black
            4'd1:  rgb = 24'h002DFF;   // blue
            4'd2:  rgb = 24'hFF3D10;   // red
            4'd3:  rgb = 24'hC9CFAB;   // tan
            4'd4:  rgb = 24'h386B3F;   // dark green
            4'd5:  rgb = 24'h00A756;   // green
            4'd6:  rgb = 24'hFAEA50;   // yellow
            4'd7:  rgb = 24'hFFFCFF;   // white
            4'd8:  rgb = 24'hBDACC8;   // grey
            4'd9:  rgb = 24'h24B8FF;   // cyan
            4'd10: rgb = 24'hFFB41F;   // orange
            4'd11: rgb = 24'h546E00;   // brown
            4'd12: rgb = 24'hFF4E57;   // pink
            4'd13: rgb = 24'hA496FF;   // light blue
            4'd14: rgb = 24'h75CC80;   // yellow-green
            default: rgb = 24'hB51A58; // purple
        endcase
    end

endmodule

`default_nettype wire
