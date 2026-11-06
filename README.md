# Intellivision for Analogue Pocket

A Mattel Intellivision core for the Analogue Pocket (openFPGA), written from scratch. It runs the
Master Component (NTSC Model 2609) with the Entertainment Computer System (ECS), the
Intellivoice and JLP cartridges, loads cartridge images directly, and has save states and sleep.
Its timing was measured against a real console.

1.0.3 is the first public release; the 0.0.x versions before it were test builds. Releases:
[github.com/Miasmark/openFPGA-Intellivision/releases](https://github.com/Miasmark/openFPGA-Intellivision/releases).

## Features

- **The console:** the CP1610, the STIC (backgrounds in all three modes, MOBs, collisions) and the
  PSG.
  - The timing of the STIC's bus requests and of the interrupts was fitted to ten measurement
    cartridges run on an original Model 2609 ([docs/TIMING_FIT.md](docs/TIMING_FIT.md),
    [docs/HW_TESTS.md](docs/HW_TESTS.md)).
  - The CPU's undefined instruction cases behave as that console's do.
- **Cartridges:**
  - raw `.int` / `.bin`, mapped by a CRC table of known games;
  - `.bin` + `.cfg` (jzIntv's format): `NAME.cfg` beside `NAME.bin` is loaded by itself;
  - Intellicart `.rom` (`.itv`);
  - cartridge RAM, page switching and Intellicart bank switching.
- **ECS:** its ROMs, RAM and second sound chip, and its computer keyboard and music synthesizer
  from a USB keyboard on the Dock (no diodes, as the real keyboard: keys mask and ghost).
- **Intellivoice:** the SP0256 speech chip with its own volume; clean or the chip's 7-bit DAC
  sound.
- **JLP:** 8,000 words of extra RAM, multiply / divide, CRC, random numbers and flash saves, kept in
  a `.sav` file per game.
- **Save states, sleep and a menu pause.**
- **Controls:** keypad modes for the Pocket's buttons, an on-screen keypad, game profiles, two
  players (a docked controller) and Swap Controllers.

## Setup

The core needs the console's own ROMs, which you supply. Copy them into `/Assets/intv/common/` on
the SD card:

| File | Contents | Needed |
|---|---|---|
| `exec.bin` | Executive ROM, 8,192 bytes | always |
| `grom.bin` | Graphics ROM, 2,048 bytes | always |
| `ecs.bin` | ECS ROM, 24,576 bytes | for ECS games |
| `ivoice.bin` | Intellivoice SP0256-012 ROM, 2,048 bytes | for Intellivoice games |

Cartridge images go in `/Assets/intv/common/` too. A `.bin` that needs a `.cfg` takes it from beside
it. While files load, or when a required one is missing, a test pattern shows one block per file:
green loaded, yellow another size, red required and missing, grey optional and missing.

## Controls

Keypad Mode (Core Settings) chooses how the Pocket's buttons play the hand controller.

**Auto (by game)** is the default: the game's profile picks the mode and, where it helps, which
button is which side action. Without a profile, Auto is Layer.

| Input | Layer (default) |
|---|---|
| D-pad | the disc, 8 directions |
| L + D-pad | the disc turned one notch clockwise: the 8 in-between directions, so all 16 |
| A / B / X | the side buttons: lower right / lower left / top |
| R + D-pad | the keypad's 1-9 by position (up-left = 1, up = 2, ... down-right = 9) |
| R + Y / B / A | the keypad's bottom row: Clear / 0 / Enter |
| R + X | 5 |
| Select | the on-screen keypad |

- **Face-button ring:** the face buttons are the keypad's ring (X = 2, B = 8, Y = 4, A = 6, pairs for
  the corners), R = 5 and L = the top side button. For games like TRON Deadly Discs.
- **Right stick (Dock):** Layer, plus a docked controller's right stick on the keypad ring, and R3 = 5.
- **Left stick:** on a docked analog controller, the left stick is the disc in all 16 directions, in
  every mode.

**On-screen keypad.**
- **Select** opens a 3 x 4 keypad over the game, drawn mostly see-through; the game keeps running.
- The **D-pad** moves the cursor, and **A** presses the key until you let go. **B** or Select closes it.
- With a game's profile, the cursor's key shows its function above the keypad (for example "BOMB
  BAY" in B-17 Bomber).
- A docked second controller opens player 2's keypad with its own Select.

**USB keyboard (Dock):**
- The number keys, Enter and Backspace (Clear) are player 1's keypad.
- With the ECS on, the keyboard is the ECS computer keyboard. Only the numpad stays the keypad.

## Settings

| Setting | Options |
|---|---|
| Border | Show (168 x 210) or Hide (the 160 x 192 picture only) |
| Keypad Mode | Auto (by game), Layer, Face-button ring, Right stick |
| Swap Controllers | player 1 on the left (default) or right controller |
| Pause in Menu | On / Off |
| ECS | Auto (by cartridge), On, Off (taken at the next reset or load) |
| ECS Keyboard | Computer keyboard, Music synthesizer (two rows: Z-M and Q-I) |
| Intellivoice | Auto (by cartridge), On, Off |
| Voice Level, ECS Level | the Intellivoice's and the ECS sound chip's volume |
| Voice Sound | Clean, Chip DAC (7-bit) |

## Known limits

- **Colours:** MAME's palette. A palette calibrated to the console is future work.
- **No PAL machine:** the PAL console's timing has not been measured.
- **No ECS cassette:** tape saves complete as with no tape plugged in, and nothing loads.
- **The ECS computer keyboard needs the Dock:** it comes only from a USB keyboard there; there is no
  on-screen ECS keyboard. Without the Dock, games that wait for typing stay on their first screen:
  ECS BASIC, Game Factory, Scooby Doo's Maze Chase and Super NFL Football (prototype).
- **The on-screen keypad** shows text labels, not overlay pictures.
- **Game profiles** exist for B-17 Bomber, Space Spartans, TRON Deadly Discs and AD&D Cloudy
  Mountain so far.
- **Library sweep:** a run of 188 library images through the core's model found one fault, now
  fixed: Super NFL Football (prototype) needs the ECS, which no game list recorded. Some games stay
  on their title screen until a key the test did not press.

## Clean room

This core is a clean-room design. It is written from the documents: General Instrument's CP-1600
manual and data catalogs, Mattel's service manuals, the Intellivision wiki and other technical
write-ups, and from measurements on a real console. MAME (BSD-3-Clause) is read for facts and
cited where a fact comes from it. jzIntv's documents are read as format specifications, and jzIntv
and MAME are run as black boxes to compare results. No code is taken from jzIntv, FreeIntv or any
other Intellivision FPGA core, and other Intellivision FPGA cores are not consulted.
[docs/SOURCES.md](docs/SOURCES.md) lists every source, its license and how it is used.

## No ROMs included

This repository and its releases contain no game images and no system ROMs.

## License

The project's own code is under the MIT License ([LICENSE](LICENSE)). Third-party parts keep their
own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and
[docs/SOURCES.md](docs/SOURCES.md).

## Developing

The design is [docs/DESIGN.md](docs/DESIGN.md). [docs/DEVELOPING.md](docs/DEVELOPING.md) says how to
build, simulate and package the core, and [docs/SIM_SPEED.md](docs/SIM_SPEED.md) how the benches run.

- `docs/`: the design, the notes for each part, the source list.
- `tools/`: Python models and tools (assembler, CPU, STIC, PSG, ECS, voice, JLP, cartridge formats).
- `sim/`: simulation benches, test programs and checks.
- `src/fpga/`: the core (Quartus project).
- `dist/`: the SD card layout of a release.

Before each commit: `sim/check/hygiene.sh --names <list>` (the names list is kept outside the
repository).
