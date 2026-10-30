// Intellivision core: the JLP's address decode (build step 11; docs/JLP_NOTES.md 2,
// 4.1; tools/jlp.py Jlp.owns / Jlp.stores), shared by intv_cart (where the
// cartridge's map neither answers nor stores) and intv_jlp (its registers).
//
//   $8023-$8026, $802D-$802F   flash registers     read: $8023, $8024, $802D-$802F
//   $8033, $8034               the switch          written whether on or off
//   $8040-$9F7F                RAM (in SRAM, through intv_cart)
//   $9F80-$9F97                multiply / divide, results, extended registers
//   $9FFC-$9FFF                CRC data, CRC, random, $9FFF
// While the JLP is switched off only the switch is its own.
//
// SPDX-License-Identifier: MIT

package intv_jlp_pkg;

    // RAM: $8040-$9F7F
    function automatic logic ram(input logic [15:0] a);
        return a >= 16'h8040 && a <= 16'h9F7F;
    endfunction

    // the registers that answer a read (on)
    function automatic logic reg_rd(input logic [15:0] a);
        return (a >= 16'h9F80 && a <= 16'h9F97) || a == 16'h9FFD || a == 16'h9FFE || a == 16'h9FFF ||
               a == 16'h8023 || a == 16'h8024 || (a >= 16'h802D && a <= 16'h802F);
    endfunction

    // the registers that take a write (on): the operands, results, extended registers,
    // CRC, flash registers
    function automatic logic reg_wr(input logic [15:0] a);
        return (a >= 16'h9F80 && a <= 16'h9F8B) || a == 16'h9F8E || a == 16'h9F8F ||
               (a >= 16'h9F90 && a <= 16'h9F97) || a == 16'h9FFC || a == 16'h9FFD ||
               a == 16'h8025 || a == 16'h8026 || (a >= 16'h802D && a <= 16'h802F);
    endfunction

    // the switch, $8033 / $8034: its own whether on or off
    function automatic logic sw(input logic [15:0] a);
        return a == 16'h8033 || a == 16'h8034;
    endfunction

    // the cartridge's map neither answers (read) nor stores (write) at a
    function automatic logic owns(input logic present, input logic on, input logic we,
                                  input logic [15:0] a);
        if (!present) return 1'b0;
        if (we && sw(a)) return 1'b1;
        if (!on) return 1'b0;
        return ram(a) || (we ? reg_wr(a) : reg_rd(a));
    endfunction

endpackage
