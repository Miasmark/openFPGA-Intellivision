# tools

Python tools, our own (MIT). Build step 0 of DESIGN.md section 9 needs no
simulator and comes first. Python 3, standard library only (`stic_frames.py import` also needs Pillow).

- `as1610.py`: CP1610 assembler for our own test ROMs, written from the
  CP-1600 manual (S1) and the wiki opcode pages. Raw image, `.cfg` and
  listing output.
- `cp1610.py`: CP1610 model: registers, flags, every opcode, SDBD,
  interrupts, bus requests and cycle counts, with a bus-phase log and a
  one-line-per-instruction trace. The golden model for the RTL CPU
  (lockstep), checked against MAME traces as a black box.
- `run_cpu_tests.py`: runs `sim/tests/cpu/*.asm` (expected results written
  by hand in `;!` comments) and sweeps over all 1024 opcodes (documented
  cycle counts, interruptibility, bus log, disassembler round trip). A test
  fails if any expectation or cycles label is never reached (in a
  `;! raises` test, any expectation before the raise point), if it halts
  without `;! stop halt`, or if it fetches an instruction from a word that
  was neither assembled nor written.
- `lockstep.py`: runs the model against MAME instruction traces (from
  `tools/refs/mame_trace.sh`) of real games: compares state before each
  instruction, every bus access and the cycle counts, replaying only the
  reads from outside the CPU and the interrupt points. The step 0
  done-test; results in `docs/CPU_NOTES.md`. Cycle differences other
  than the two documented ones (SETC, SARC Rr,2) fail it, and so does
  any extra lump of cycles at an interrupt (`--max-lump`, default 0).
  Needs the user's BIOS, game images and traces, which stay outside the
  repo.
- `intv_system.py`: the Intellivision as build steps 3-4 have it around
  the CPU model: memory map, pull-ups, EXEC (10 bits), GROM, GRAM with its
  windows, scratchpad and System RAM, the STIC (`stic.py`) and the PSG
  (`psg.py`), the frame timing (INTRM and the
  bus-copy window, the STIC handshake, BUSRQ) and the cartridge (the
  mapper model). The golden model of `sim/tb/tb_system.py`.
  `intv_system.py mame TRACE [--cart IMG] [--timing computed]` compares it
  with a MAME trace, nothing replayed: every read and write and every
  interrupt point must agree. It runs on MAME's terms: MAME's clock, its
  NEGR carry and its memory map (no GRAM alias above $3BFF, unmapped
  ranges read 0), and with `--timing computed` MAME's 59.92 Hz frames
  computed rather than read from the trace.
- `intv_input.py`: the input model (DESIGN.md 7.2, build step 6): the
  Pocket's controllers and USB keyboard as two hand controllers, the bytes
  on the PSG's ports; its code table is checked against MAME's
  hand-controller tables (`handctrl.cpp`), and every byte against MAME's
  `read_ctrl()` transcribed. The golden model of `sim/tb/tb_input.py`.
- `stic.py`: the STIC model (build steps 4 and 5): registers, Color
  Stack / Colored Squares / Foreground-Background cards from GROM and
  GRAM, border colour, delays and border extension, the display enable,
  the row FIFO fetches and BUSRQ, the 8 MOBs (sizes, flips, priority,
  GROM/GRAM cards) and their collision bits, one 189 x 240 palette-index
  picture per frame plus a log of its graphics-bus reads. MOB rules: MAME's
  in mode `mame`, the hardware's (S9) in `stic` and `none`; `Stic.mobs =
  False` draws backgrounds only (the step-4 RTL bench). Modes `none` (step 3,
  default), `stic` (the hardware, BUSRQ on) and `mame` (MAME as it runs).
  In modes `stic` and `none` a picture is what the RTL (`intv_stic.sv`)
  draws: display enable from the end of the VBlank window, border pixels
  from register $2C as it is when each pixel is drawn (so a picture is
  handed out at line 24 of the next frame). Facts, sources and
  disagreements: `docs/STIC_NOTES.md`.
- `psg.py`: the PSG model (build step 6): the AY-3-8914's registers,
  tone, noise and envelope generators, the 2-bit envelope select, mixer,
  DAC curve and the 48 kHz filter the core gives the Pocket, clocked from
  the system model's CPU cycles (`ClockedPsg`); `psg.py selftest` checks
  periods, the LFSR's length and all 16 envelope shapes. Facts, sources
  and the differences from MAME: `docs/PSG_NOTES.md`.
- `psg_compare.py`: the PSG model against MAME (`tools/refs/mame_psg.sh`'s
  register-write log, step stream and 48 kHz file): the register log and,
  with MAME's tone counter and step grid, every PSG step must be equal;
  with the core's counter, how close the steps and the 48 kHz sound are
  (pitch, spectrum, envelope, waveform). Results in `docs/PSG_NOTES.md` 4.
- `stic_frames.py`: the model's pictures against MAME's snapshots:
  `import` (MAME PNG to palette-index PGM, the palette read from MAME's
  own source; needs Pillow), `run` (pictures, bus logs with MOB lines and
  collision bits) and `compare` (snapshot N against picture N - 1, every
  pixel); `--press F1-F2:KEY,...` holds scripted keys on both hand
  controllers as `tools/refs/mame_psg.sh` does in MAME
  (`intv_system.parse_presses` / `press_pads`, also used by
  `psg_compare.py --press` and the play bench).
- `cpu_buslog.py`: exports the model's bus-phase log, step ends and
  final registers for the RTL lockstep bench (`sim/tb/tb_cpu.sv`, build
  step 3): every program in `sim/tests/cpu`, a sweep over all 1024
  opcodes (after SDBD and both branch outcomes too) and random programs,
  each with save points for the round trip. Run by
  `sim/tb/run_tb_cpu.sh`.
- `mapper/`: cartridge mapper model and the CRC map table generator.
  Entry points: `gen_crc_table.py` (builds `data/cart_table.csv`, `data/layouts.json`
  and `src/fpga/core/tables/cart_*.mif|hex`) and `intv_mapper.py` (the model and
  the library check). See `mapper/README.md`.
- `refs/`: scripts that build and drive MAME and jzIntv as black-box
  references (traces, snapshots). Their outputs are never committed.

Where the sources disagree and what the model does: `docs/CPU_NOTES.md`
(CPU), `docs/STIC_NOTES.md` (STIC).

    python3 tools/run_cpu_tests.py            # all tests
    python3 tools/run_cpu_tests.py -k sdbd    # some
    python3 tools/as1610.py prog.asm -o sim/work/prog.bin --cfg sim/work/prog.cfg -l -
    python3 tools/cp1610.py prog.asm --steps 200   # trace a program
    python3 tools/lockstep.py                 # model vs MAME traces (3 games)
    python3 tools/intv_system.py mame T.log --cart G.int   # system model vs MAME
    python3 tools/stic_frames.py compare --cart G.int --ref FRAMES --snaps 60,120   # STIC vs MAME

Packaging (build step 1): `package.sh` assembles the SD card zip from
`dist/` and a Quartus bitstream (`release/M_Intellivision_Pocket_<version>.zip`);
`reverse_bits.py` makes the bit-reversed `.rbf_r` the Pocket loads.
