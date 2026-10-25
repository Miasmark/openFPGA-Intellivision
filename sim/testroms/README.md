# testroms

Sources of our own test ROMs (MIT), assembled by `tools/as1610.py`. Built images go
to `sim/work*` and are not committed.

- `loader_odd.asm`: synthetic odd-length cartridge images for the step-2
  loader bench (`sim/tb/tb_loader.py`).
- `systest.asm`: step 3, a program for the EXEC slot (ROMW 10, from
  `$1000`, ISR at `$1004`) that exercises the bus around the CPU: unmapped
  and fixed reads, every STIC offset and alias, the STIC handshake inside
  and outside VBlank, GRAM through all eight windows, every PSG register,
  RAM widths, the mode latch through its aliases, closed GRAM reads
  through non-zero windows, and (section 7) accesses timed to the cycle at
  the end of the bus-copy window (slots 3788-3791) and of INTRM.
  `sim/tb/tb_system.py` runs it as the image "systest" and checks where the
  section-7 probes land (their delays were found with the model).
- `carttest.asm`: step 3, a program for the EXEC slot that writes and reads
  cartridge RAM, ROM, unmapped space and the $0040-$005F range, and sets
  ECS-style page selects, under interrupts. `tb_system.py` runs it with two
  synthetic cartridges (`tools/synth_image.py`: a word pattern whose CRC32
  is forced to a table entry, layout 25 with 8-bit RAM at $8800 and layout
  26 with paged ROM at $F000) as "cartram" and "cartpaged".
- With ROMW 10 the EXEC ROM keeps 10 bits, so an address above $3FF must
  go through a pointer register; `tb_system.py` refuses a program with a
  word over 10 bits.
