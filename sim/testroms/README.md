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
  the end of the bus-copy window (slots 3788-3791) and of INTRM, and (p11,
  step 5) a write to $18 in the last slot of a frame whose display is off.
  `sim/tb/tb_system.py` runs it as the image "systest" and checks where the
  section-7 probes land (their delays were found with the model).
- `carttest.asm`: step 3, a program for the EXEC slot that writes and reads
  cartridge RAM, ROM, unmapped space and the $0040-$005F range, and sets
  ECS-style page selects, under interrupts. `tb_system.py` runs it with two
  synthetic cartridges (`tools/synth_image.py`: a word pattern whose CRC32
  is forced to a table entry, layout 25 with 8-bit RAM at $8800 and layout
  26 with paged ROM at $F000) as "cartram" and "cartpaged".
- `sticbus.asm`: step 4, the STIC test for backgrounds and BUSRQ (EXEC
  slot): every card kind, delays and border extension per frame, late
  display enables, a frame without INTAK, missed row fetches and the
  row-load deadline (see its header). `tb_system.py` runs it as
  "sticbus" (STICBUS_DEADLINE).
- `sticmob.asm`: step 5, the STIC test for MOBs and collisions (EXEC
  slot, ROMW 10). 22 scenes, one a frame, set up in VBlank from a table
  (flags, the 24 MOB registers, the 8 expected collision words): every
  size and flip, YRES with an odd card (M1), GROM cards 64-255 in both
  modes (M2), MOB order with PRIO (M3), the delay strip (M4), squares
  colour 7 (M5), X = 0, invisible MOBs, each border edge just inside and
  just outside (with delays and border extension), the edges of the
  background-collision area (bottom line, right column, left and top
  edges under border extension), YFLIP with YRES, the sweep's first line
  and last row, MOBs off the raster, sticky bits. The next frame's ISR
  reads $18-$1F, counts differences from the expected words (System RAM
  $0303), marks the scene in a failed-scene mask ($030A, $030B), and
  shows green, yellow (only S5, S7, S10 failed: M4, M5, M1 as MAME does
  them) or red in the border. Under MAME's rules (tools/stic.py
  `mob_rules`) it counts 5 fails a pass (M1, M4, M5), and so does MAME
  itself (`tools/refs/mame_exec_prog.sh`, docs/STIC_NOTES.md 6).
  `tb_system.py` runs it as "sticmob" (STICMOB_SELFCHECK).
- With ROMW 10 the EXEC ROM keeps 10 bits, so an address above $3FF must
  go through a pointer register; `tb_system.py` refuses a program with a
  word over 10 bits.
