# Intellivision for Analogue Pocket

A new Mattel Intellivision core for the Analogue Pocket (openFPGA), written
from scratch. It is to run the Master Component (NTSC Model 2609) with the
Entertainment Computer System (ECS), the Intellivoice and JLP cartridges, load
cartridge images directly (raw `.int`/`.bin`, `.bin` + `.cfg`, Intellicart
`.rom`), and support save states and sleep from its first release.

**Status: in development.** Build steps 1-9 are done (8: cartridge formats, 9: the ECS); step 10,
the Intellivoice, is built in 0.0.16 and waits for its hardware test. The core loads and
maps the cartridge and the system ROMs, runs the EXEC and games on the
CP1610 with the STIC's picture (backgrounds, MOBs, collisions) and the
PSG's sound, takes the Pocket's controllers and keyboard as the hand
controllers, and saves and loads states (Memories, sleep, a menu pause;
[docs/SAVESTATE.md](docs/SAVESTATE.md)). Cartridge formats beyond the CRC
table, the ECS and the Intellivoice are in; JLP comes next. The plan is
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
Cartridges go there too, and a `.bin` that needs a `.cfg` takes it from
beside it: `NAME.cfg` next to `NAME.bin` is loaded automatically.

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
