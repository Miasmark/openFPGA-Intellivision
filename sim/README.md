# sim

Simulation (Verilator) and checks. Run outputs go to `sim/work*`, which git
ignores: traces, frames and audio from games are never committed.

- `check/`: repository checks. `hygiene.sh` runs before each commit.
- `tb/`: testbenches, one per build step (DESIGN.md section 9).
- `testroms/`: sources of our own test ROMs (MIT): opcodes, SDBD, interrupts,
  STIC and GRAM aliases, STIC modes and collisions, PSG.
- `regress/`: the regression set: game images referred to by path and CRC32
  only, and the save-state round-trip test (DESIGN.md 8.4).
