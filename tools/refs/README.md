# tools/refs: reference emulators as black boxes

Scripts that build and drive the two reference emulators of DESIGN.md
section 8.1. They hold no emulator code. Everything they produce from a
game or a system ROM (traces, snapshots, rompaths) goes to a folder
outside this repository and is never committed (DESIGN.md section 1).

| Script | What it does |
|---|---|
| `build_mame_intv.sh FORK DIR [REV]` | Intellivision-only MAME from the owner's fork, as a git worktree; `SOURCES=src/mame/mattel/intv.cpp`, `-j8`, nice 10 |
| `setup_mame_rompath.sh BIOS OUT` | MAME rompath from the user's BIOS files under MAME's names, CRC-checked |
| `mame_trace.sh SYS IMAGE FRAMES OUT` | per-instruction CPU trace with every bus read and write and the interrupts, from reset; IMAGE `none` for an empty cartridge slot |
| `trace_summary.py TRACE...` | parses a trace; prints counts and a sha256 only |
| `mame_snap.sh SYS IMAGE FRAME OUT` | one PNG snapshot at the end of a frame |
| `build_jzintv.sh ZIP DIR` | jzIntv from its official source zip (run only; GPL-2 source never read) |
| `jzintv_run.sh IMAGE N OUT [flags]` | jzIntv headless for N instructions, then one screenshot |

## Environment

```
MAME=<build>/mame  MAME_ROMPATH=<rompath>  MAME_HASHPATH=<build>/hash
JZINTV=<jzintv tree>/bin/jzintv  INTV_BIOS=<folder with exec.bin, grom.bin, ECS.bin>
```

Both run headless with `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy` (the
scripts set it).

## Trace format (`mame_trace.sh`)

One line per instruction, before it runs, then its bus accesses:

```
c=<total cycles> f=<frame> y=<beam line> R=<R0> ... <R7> F=<flags> <PC>: <disassembly>
  R <addr> <data>        read, instruction fetches included
  W <addr> <data>        write
   (interrupted at <PC>, IRQ 1)   INTRM taken; the push of the return PC follows
```

- `F` is MAME's `CURFLAGS`: S = $80, Z = $40, O = $20, C = $10 (MAME
  cp1610.cpp:23-26). The interrupt-enable and SDBD state are not exported.
- The interrupt vector fetch (IAB) is not a bus read in MAME, so it does
  not appear as an `R` line.
- MAME charges the STIC's BUSRQ cycles in one lump when INTRM is raised
  (intv_m.cpp:668, 680), so `c` jumps there. A lockstep model should compare
  the instruction stream, registers, flags and bus data, inject INTRM at
  the instruction index where the trace shows it, and not compare cycle
  counts across a frame.
- MAME maps a raw `.int` by `hash/intv.hsi`; an image without an entry
  there is loaded as 8K words at $5000.
- The debugger commands are sent from Lua (`manager.machine.debugger`):
  with `-debugger none`, MAME does not run a `-debugscript`.
