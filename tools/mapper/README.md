# mapper

Cartridge mapper model and the CRC map table generator (build step 0). The
generator reads MAME's CC0 hash files and our region proofs and writes the
table the loader uses; the model runs the table, the CFG parser and the
Intellicart `.rom` parser over the owner's images (by path, never committed).
