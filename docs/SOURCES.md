# Sources

Every source this core is written from, its license and how it is used.
Codes match DESIGN.md section 12 and the tags in the design and in code
comments (`[from X]`). Code comments cite a source with page, sheet or file
and line.

## Rules

- **Own code** (RTL, Python tools, test ROMs, scripts) is written by this
  project from the documents below and is under the MIT License.
- **Documents** (manuals, datasheets, the wiki) are read for facts. Code
  printed in them (for example EXEC listings) is read only, never copied.
- **MAME** (BSD-3-Clause) may be read for facts and cited, and is run as a
  black box to compare traces, register logs, audio and frames. Its palette
  may be used with its notice (DESIGN.md decision 4); anything taken from
  MAME is credited where it is used and in the release notices.
- **jzIntv** (GPL-2.0-or-later): its documents are read as format and
  hardware specifications; its source code is not read for code and nothing
  is copied from it. The program is run as a black box only. `name_list.c`
  is public domain and gives the ECS and Intellivoice flags of the CRC table.
- **Not used:** the Intv_MiSTer core (not opened), FreeIntv (no code, no
  palette), and jzIntv's source code.
- **No game data:** system ROMs and game images are user-supplied and never
  in the repository or a release. Outputs of runs on games (traces, frames,
  audio) stay out too; only hashes are committed.

## Hardware documents

| Code | Source | License / status | How used |
|---|---|---|---|
| SM | Mattel Intellivision Service Manual, Model 2609 ("SM p.N" = PDF page) | (c) Mattel; reference only | board, bus phases, memory decode, GROM modes, System RAM Bus Copy, colour encoder levels |
| S1 | General Instrument CP-1600 Microprocessor Users Manual, May 1975 (bitsavers.org, components/gi/CP1600) | (c) GI; reference only | CPU instruction set, flags, bus timing; the Python CPU model and the RTL CPU |
| S2 | GI 1982 Microelectronics Data Catalog (CP1610 p.441-446, STIC p.461-464, RO-3-9502 p.465-467, GROM p.468, PSG p.299-306, AY-3-8915 p.476, SP0256 p.286-290) | (c) GI; reference only | chip behaviour and pin functions |
| S4 | GI 1978 "Programmable TV Games" (AY-3-8914 p.7-100 to 7-105) | (c) GI; reference only | PSG registers and envelope |
| S6 | GI SP-0256 Design Objective Spec, Rev C, Nov 1981 | (c) GI; reference only | speech processor, DAC output |
| S7 | SP0256 Instruction Set (Zbiciak, Palazzolo) | no license stated; specification only | SP0256 microsequencer opcodes |
| S8 | GI SP0256A-AL2 datasheet, 1984 | (c) GI; reference only | clocks, pins, output bandwidth |
| IVSM | Mattel Intellivoice Service Manual, Model 3330 | (c) Mattel; reference only | Intellivoice chip set and analog filter chain |
| C5 | Console5 TechWiki, ECS page (2021) | wiki text; reference only | ECS parts list |
| wiki | wiki.intellivision.us (archive) | no license stated; reference only | memory map, bus phases, opcode cycle counts, STIC timing, ECS keyboard matrix, controller codes |
| AA | "Reading the ECS Keyboards", AtariAge forum | reference only | ECS keyboard matrix and ghosting |

## Emulators and data files

| Code | Source | License / status | How used |
|---|---|---|---|
| MAME | MAME: mattel/intv.cpp, intv.h, stic.h, stic.cpp; devices/cpu/cp1610; devices/sound/ay8910, sp0256; bus/intv/ecs.cpp, voice.cpp, slot.cpp, rom.h (github.com/mamedev/mame) | BSD-3-Clause | read and cited for facts; run as a black box (an intv-only build) for comparison; palette with its notice |
| MAME hash | MAME hash/intv.xml, intvecs.xml | CC0-1.0 | per-segment CRCs and load addresses for the CRC map table, read by our own generator |
| MAME hsi | MAME hash/intv.hsi | BSD-3-Clause | cross-check only (known errors; DESIGN.md 5.2) |
| S9 | jzIntv 20200712 documents: as1600.txt, bincfg.h, id_tag.txt, jlp.c header, interrupts.txt, psg.txt, stic.txt, intellicart.txt, ecs.html, jzintv/cp_1610.txt (CPU remarks, see CPU_NOTES.md) | GPL-2.0-or-later; read as specifications only | CFG, Intellicart `.rom` and JLP formats; timing figures (MAME's STIC constants derive from these, so the two count as one source) |
| S9-names | jzIntv `name_list.c` | public domain | ECS and Intellivoice flags per CRC |
| jzIntv | the jzIntv program | GPL-2.0-or-later | run as a black box only (traces, frames, audio, PAL); outputs treated as game data |

## Pocket side

| Code | Source | License / status | How used |
|---|---|---|---|
| APF | Analogue developer documentation and the openFPGA core template | Analogue's terms | core template, bridge, host commands (save states 0x00A0/0x00A4, 0x00B0), core definition files |
| AGG | agg23's analogue-pocket-utils (`data_loader`, `sound_i2s`) and his openFPGA cores (NES, SNES, Tamagotchi, Game & Watch) | utils and Tamagotchi: MIT | utils used with their notice; save-state behaviour learned from his cores, state-bus pattern from Tamagotchi (MIT) |
| 7800 | openFPGA-7800 (github.com/Miasmark/openFPGA-7800), same author | MIT for own files, listed GPL-3.0 parts | Pocket wrapper conventions, packaging, `sim/check/hygiene.sh` (adapted). No GPL part of it is used here |

## Project notes

| Code | Source | How used |
|---|---|---|
| PJ | the owner's project list, Intellivision section | goals and constraints |
| IN | input design notes (owner, 2026-10-24) | controller mapping (DESIGN.md section 7) |
| L-* | research lanes of 2026-10-24 (service manual, wiki, datasheets and licences, Pocket and save states, test assets, review) | the measurements tagged [measured] in DESIGN.md; kept in the research folder outside this repository |
