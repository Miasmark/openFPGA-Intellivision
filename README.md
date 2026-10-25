# Intellivision for Analogue Pocket

A new Mattel Intellivision core for the Analogue Pocket (openFPGA), written
from scratch. It is to run the Master Component (NTSC Model 2609) with the
Entertainment Computer System (ECS), the Intellivoice and JLP cartridges, load
cartridge images directly (raw `.int`/`.bin`, `.bin` + `.cfg`, Intellicart
`.rom`), and support save states and sleep from its first release.

**Status: in development.** Build step 1 (the Pocket skeleton) is done: the
core shows a test pattern at 59.92 Hz and loads the data slots. The plan is
[docs/DESIGN.md](docs/DESIGN.md); section 9 gives the build order.
[docs/DEVELOPING.md](docs/DEVELOPING.md) says how to build, simulate and
package it.

## Clean room

This core is a clean-room design. It is written from the documents: General
Instrument's CP-1600 manual and data catalogs, Mattel's service manuals, the
Intellivision wiki and other technical write-ups. MAME (BSD-3-Clause) is read
for facts and cited where a fact comes from it. jzIntv's documents are read as
format specifications, and jzIntv and MAME are run as black boxes to compare
results. No code is taken from jzIntv, FreeIntv or any other Intellivision
FPGA core, and other Intellivision FPGA cores are not consulted.
[docs/SOURCES.md](docs/SOURCES.md) lists every source, its license and how it
is used.

## No ROMs included

This repository and its releases contain no game images and no system ROMs.
The core needs the console's own ROMs, supplied by the user:

| File | Contents | Required |
|---|---|---|
| `exec.bin` | Executive ROM, 8,192 bytes | yes |
| `grom.bin` | Graphics ROM, 2,048 bytes | yes |
| `ecs.bin` | ECS ROM, 24,576 bytes | for ECS titles |
| `ivoice.bin` | Intellivoice SP0256-012 ROM, 2,048 bytes | for Intellivoice titles |

They go in `/Assets/intv/common/` on the SD card (DESIGN.md section 5.6).

## License

The project's own code is under the MIT License ([LICENSE](LICENSE)).
Third-party parts keep their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [docs/SOURCES.md](docs/SOURCES.md).

## Repository layout

- `docs/`: the design, the source list and the developer notes.
- `tools/`: Python tools (assembler, CPU and mapper models, table
  generators); see `tools/README.md`.
- `sim/`: simulation, test ROM sources and checks; see `sim/README.md`.
- `src/fpga/`: the core (Quartus project).
- `dist/`: the SD card layout of a release.

Before each commit: `sim/check/hygiene.sh --names <list>` (the names list is
kept outside the repository).
