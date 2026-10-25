# sim

Simulation (Verilator) and checks. Run outputs go to `sim/work*`, which git
ignores: traces, frames and audio from games are never committed.

- `check/`: repository checks. `hygiene.sh` runs before each commit.
- `tb/`: testbenches, one per build step (DESIGN.md section 9).
- `tests/cpu/`: CPU tests for the Python model, one program per instruction
  class, with hand-written expected results; run by `tools/run_cpu_tests.py`.
- `testroms/`: sources of our own test ROMs (MIT) for the whole core:
  STIC and GRAM aliases, STIC modes and collisions, PSG.
- `regress/`: the regression set: game images referred to by path and CRC32
  only, and the save-state round-trip test (DESIGN.md 8.4).
