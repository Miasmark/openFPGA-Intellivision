# tools

Python tools, our own (MIT). Build step 0 of DESIGN.md section 9 needs no
simulator and comes first. Python 3, standard library only.

- `as1610.py`: CP1610 assembler for our own test ROMs, written from the
  CP-1600 manual (S1) and the wiki opcode pages. Raw image, `.cfg` and
  listing output.
- `cp1610.py`: CP1610 model: registers, flags, every opcode, SDBD,
  interrupts, bus requests and cycle counts, with a bus-phase log and a
  one-line-per-instruction trace. The golden model for the RTL CPU
  (lockstep), checked against MAME traces as a black box.
- `run_cpu_tests.py`: runs `sim/tests/cpu/*.asm` (expected results written
  by hand in `;!` comments) and sweeps over all 1024 opcodes (documented
  cycle counts, interruptibility, bus log, disassembler round trip).
- `lockstep.py`: runs the model against MAME instruction traces (from
  `tools/refs/mame_trace.sh`) of real games: compares state before each
  instruction, every bus access and the cycle counts, replaying only the
  reads from outside the CPU and the interrupt points. The step 0
  done-test; results in `docs/CPU_NOTES.md`. Needs the user's BIOS, game
  images and traces, which stay outside the repo.
- `mapper/`: cartridge mapper model and the CRC map table generator (to come).

Where the sources disagree and what the model does: `docs/CPU_NOTES.md`.

    python3 tools/run_cpu_tests.py            # all tests
    python3 tools/run_cpu_tests.py -k sdbd    # some
    python3 tools/as1610.py prog.asm -o sim/work/prog.bin --cfg sim/work/prog.cfg -l -
    python3 tools/cp1610.py prog.asm --steps 200   # trace a program
    python3 tools/lockstep.py                 # model vs MAME traces (3 games)

Packaging (`package.sh`) comes with build step 1.
