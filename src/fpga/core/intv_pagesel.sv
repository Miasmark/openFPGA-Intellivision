// Intellivision core: ECS-style page selects (DESIGN.md 5.5, 13 item 12;
// build step 8). A write of $xA5y to $xFFF selects page y of the 4K range
// $x000 (jzIntv doc/tech/ecs.html), for every one of the 16 ranges, whatever
// answers there. Kept general and on its own so that the ECS (build step 9)
// uses the same selects for its ROMs at $2000, $7000 and $E000: a device
// that pages decodes nothing itself, it reads sel.
//
// Machine reset loads rst_val (4 bits per range, range 0 in [3:0]); the
// cartridge alone uses all zeros. Step 9 may give the ECS's reset pages
// here (DESIGN 20: ECS ROMs paged out from reset).
//
// Save state: two 32-bit words, 4 bits per range (ranges 0-7, then 8-15),
// written through ss_we0 / ss_we1 by the owner's state port.
//
// SPDX-License-Identifier: MIT

`default_nettype none

module intv_pagesel (
    input  wire logic        clk,
    input  wire logic        rst,             // machine reset (and a new load)
    input  wire logic [63:0] rst_val,

    input  wire logic        we,              // a CPU write
    input  wire logic [15:0] addr,
    input  wire logic [15:0] wdata,

    input  wire logic        ss_we0,
    input  wire logic        ss_we1,
    input  wire logic [31:0] ss_wdata,

    output logic [63:0]      sel
);

    initial sel = 64'd0;

    wire logic hit = we && addr[11:0] == 12'hFFF && wdata[15:4] == {addr[15:12], 8'hA5};

    always_ff @(posedge clk) begin
        if (rst)
            sel <= rst_val;
        else if (ss_we0)
            sel[31:0] <= ss_wdata;
        else if (ss_we1)
            sel[63:32] <= ss_wdata;
        else if (hit)
            sel[4*addr[15:12] +: 4] <= wdata[3:0];
    end

endmodule

`default_nettype wire
