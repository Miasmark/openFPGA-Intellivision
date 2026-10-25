# tools

Python tools, our own (MIT). Build step 0 of DESIGN.md section 9 needs no
simulator and comes first.

- `asm/`: CP1610 assembler for our own test ROMs.
- `cpu_model/`: CP1610 golden model, run in lockstep with the RTL CPU.
- `mapper/`: cartridge mapper model and the CRC map table generator.

Packaging (`package.sh`) comes with build step 1.
