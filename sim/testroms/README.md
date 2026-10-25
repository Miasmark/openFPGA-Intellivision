# testroms

Sources of our own test ROMs (MIT), assembled by `tools/as1610.py`. Built images go
to `sim/work*` and are not committed.

- `loader_odd.asm`: synthetic odd-length cartridge images for the step-2
  loader bench (`sim/tb/tb_loader.py`).
- `systest.asm`: step 3, a program for the EXEC slot (ROMW 10, from
  `$1000`, ISR at `$1004`) that exercises the bus around the CPU: unmapped
  and fixed reads, every STIC offset and alias, the STIC handshake inside
  and outside VBlank, GRAM through all eight windows, every PSG register,
  RAM widths. `sim/tb/tb_system.py` runs it as the image "systest".
