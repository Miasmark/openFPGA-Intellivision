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
- `cart8test.asm`: step 8, a program for the EXEC slot that writes and reads
  back the Intellicart bank registers ($0040-$005F) and the windows they
  map (loaded Intellicart memory, RAM, a wrap past $FFFF), 16- and 8-bit
  cart RAM, a CFG gap, and page selects at $2000, $E000 and $F000, under
  interrupts that change the bank and the page every frame. `tb_system.py`
  runs it as "cartbank" (on `step8/rombank.rom`) and "cartcfg" (on
  `step8/cfgmap.bin` + `.cfg`), with a self-check against the images'
  words (CART8_SELFCHECK); `tb_savestate.py` saves and loads it.
- `step8/`: the step-8 cartridge format images (docs/CARTFORMATS.md 7):
  as1600 sources (`cfgmap.asm` BIN + CFG, `rombank.asm` and `rombankw.asm`
  Intellicart .rom; assembled with jzIntv's as1600, run as a program), the
  CFG zoo `cfg/zoo*.cfg` (each with a synthetic image), and
  `build_images.py`, which builds them and the refusal set (CFGs with one
  fault each, .rom files with a bad CRC, cut short, and the like) and
  lists the loader's verdict for each.
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
- `voicetest.py`: step 10, builds the Intellivoice test program for the EXEC slot (ROMW 10)
  with test streams written by `tools/sp0256.py` `Stream`: every data opcode in every MODE
  through the FIFO, jumps into and out of the FIFO, the resident commands 1-42, dropped
  commands and FIFO words, resets mid-speech, reads past the FIFO's head. Run in MAME with
  `tools/refs/mame_voice.sh` (`EXEC=`), compared by `tools/sp0256.py compare`
  (docs/VOICE_NOTES.md 7).
- `sticmob_cart.py`: builds sticmob.asm as a cartridge image (8 KiB words
  at $5000, raw big-endian, with a `[mapping]` file on request) that the
  real EXEC starts: a cartridge header and a title with start-up code
  replace the reset branch, the start-up code takes the EXEC's ISR vector
  ($0100 / $0101) over, and the ISR returns through the EXEC's dispatcher
  (`JR R5`); the scenes and checks are sticmob.asm's, unchanged. In MAME
  with the real EXEC (`tools/refs/mame_cart_prog.sh`) it counts 5 fails a
  pass (S5, S7, S10), the words of the model's MAME-rule run in every scene
  (docs/STIC_NOTES.md 6). The image is what a flash cartridge would take on
  the console; it is built, not committed.
  `tb_system.py` runs it as "sticmob" (STICMOB_SELFCHECK).
- `psgtest.asm`: step 6, the PSG test (EXEC slot, ROMW 10). The ISR
  writes one group of PSG registers a frame from a table (every register
  with its unused bits set, tones at periods 0, 1, $00D, $FFF and a small
  period written while the count is far past it, noise at periods 0, 31
  and 5, tone and noise both off, all 16 envelope shapes, envelope periods
  0, 1, 2, $40 and $110, a shape rewritten with the same value, all four
  volume selects, the port-direction bits) and reads the hand controllers
  and the shape back; the main loop writes channel C's and the noise
  period after a delay that changes every pass, so writes land in every
  phase of the PSG's 4-cycle step. It checks nothing itself: `tb_system.py`
  compares every PSG step and sample with `tools/psg.py` (image
  "psgtest", round trips rt9 and rt10 inside its slow envelope).
- With ROMW 10 the EXEC ROM keeps 10 bits, so an address above $3FF must
  go through a pointer register; `tb_system.py` refuses a program with a
  word over 10 bits.
- `ecstest.asm`: step 9, a program for the EXEC slot run with the ECS
  attached (`sim/tb/tb_system.py` images ecstest and ecssynth): ECS RAM
  widths, the UART stub, every ECS ROM page value, PSG #2's registers and
  sound (both envelope-select bits), PSG #1 at full volume (the mix
  saturates), and in every frame's ISR the keyboard matrix scanned four
  ways (rows, columns, both ports out, both in), stored for the bench's
  check against the matrix rule written out by hand (ECSKBD_WANT).
- `step9/`: step 9's IntyBASIC test cartridges and their builder
  (`build_images.py`): ecssound (SOUND 5-9 and CONT3: the $4800 hook, page
  value $F), ecshook (the same without the CFG's ECS flag), ecsavail (no
  ECS feature: the Auto rule's attached mode, IntyBASIC's ECS RAM test),
  cart4000 (a cartridge at $4000: the ECS off). Each prints PASS / FAIL.
- `hw/`: the hardware measurement cartridges for the owner's console on a flash cartridge
  (docs/HW_TESTS.md): `hwlib.asm` (the EXEC cartridge header, the ISR take-over, text output)
  and one program each: `hw_steal` (the cycles the STIC takes a frame), `hw_intlate` (where the
  VBlank interrupt is taken), `hw_rowcopy` (when each card row is copied), `hw_cpuodd` (the
  undefined CPU cases), `hw_ecskeys` (the ECS keyboard matrix, raw). `build_hw.py build OUTDIR`
  writes NAME.bin + NAME.cfg; `build_hw.py run NAME ...` runs one in the Python model and writes
  its pictures. Built, never committed.
