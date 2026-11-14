# Championship Tennis: ECS page fix

A patch that lets Championship Tennis (INTV, 1985) run with the Entertainment Computer System
attached and on. Without it the game's title is garbled and its own code at `$E000-$EFFF` is
replaced by the ECS's ROM, because the ECS keeps its third ROM page at the same addresses.

This folder holds only our own work: the patch's assembly source, the BPS patch (the changed words
and checksums, no game code), the memory map for the patched image, and the build script. You need
your own copy of the game.

| | |
|---|---|
| Source image | `Championship Tennis (Europe).int` (No-Intro), 32,768 bytes, CRC32 **4CC46A04** |
| Patched image | 32,768 bytes, CRC32 **C4A99DFD** |
| Patch | `championship_tennis_ecs.bps`, 188 bytes (its CRC32 EB52D0CD), 18 words changed |
| Memory map | `championship_tennis_ecs.cfg` (`$0000-$1FFF` at `$5000`, `$2000-$3FFF` at `$D000`) |

## What it changes

The ECS's ROM has three 4K pages; the third sits at `$E000-$EFFF` and is paged in by the ECS's boot
(`$EA51` written to `$EFFF`). Championship Tennis maps its own ROM at `$D000-$EFFF` and runs code at
`$EF10` while the EXEC draws its title (from the cartridge's title routine at `$5056`). With the ECS
on, that code is the ECS's, so the title shows garbage and later reads of the game's `$E000` data
get ECS ROM words.

The patch pages the ECS's `$E` ROM out again by writing `$EA50` to `$EFFF`, the bank-switching
documented in jzIntv's ECS notes (`doc/tech/ecs.html`) and used by World Series Major League
Baseball, before the title routine goes on:

- `$5056-$5058` (the title routine's first two instructions) become `J $6FE0`;
- a 15-word stub at `$6FE0` (end padding of the `$5000` segment) replays those two instructions
  around the write and jumps back to `$5059`.

Without an ECS the write lands on the cartridge's ROM and changes nothing, so the patched game runs
everywhere the original does. The source is `tennis_ecs.asm` (tools/as1610.py).

**Where the stub lives.** Most zero runs in this image are parts of tables, not free space. The
model (tools/intv_system.py, every bus access logged) ran the original game with the ECS off through
its title, location choice, player positioning and play, at all three courts, in singles and in
doubles (six runs, 2,300-3,000 frames each): it read zero runs at `$6025`, `$68AB`, `$6D42`, `$6D91`,
`$6DF1`, `$6E0A`, `$6E46`, `$6F7E` and `$D8D0` (tables), and `$6FC5-$6FC9` (the end of the last
record before the padding, at the first court in singles), but nothing at `$6FCA-$6FFF`. The stub
sits at `$6FE0-$6FEE`, 22 words past that.

**Checked** (model, patched image): ECS on: the ECS's title and menu, Cartridge, the game's own title
drawn correctly, then singles play with scoring, and the computer doubles (two players placed, the
third left waiting, keypad 0); the stub's `$EA50` write at the title, and no access to `$6FCA-$6FFF`
but the stub's own (the original's `$6FC5-$6FC9` reads stay as they were). ECS off: doubles as the original. ECS Auto with the `.cfg`: the ECS attached, the
game starts directly. jzIntv (black box, ECS off): the same title, positioning and computer doubles.

## Using it

With any BPS patcher (Floating IPS, beat, Rom Patcher JS, ...): apply `championship_tennis_ecs.bps`
to `Championship Tennis (Europe).int`, name the result `Championship Tennis (ECS).bin`, and put
`championship_tennis_ecs.cfg` beside it as `Championship Tennis (ECS).cfg`. The patcher checks the
source's CRC32. On the Pocket core (1.0.7 or later) load the `.bin`: its `.cfg` loads by itself.

Or, with Python and this repository: `python3 patches/championship_tennis_ecs/build.py IMAGE OUTDIR`
(IMAGE: the No-Intro zip, its `.int`, or a `.bin` of the same bytes). It checks the CRC32 and the
words it replaces, and writes the patched `.bin`, its `.cfg` and the `.bps` into OUTDIR. Keep OUTDIR
out of any repository: the patched image is game data.

## The `.cfg`

The patched image's CRC32 is in no game list, so the `.cfg` gives its map. It sets
`ecs_compat = 1` (tolerates the ECS): the core's ECS setting Auto then leaves the ECS attached
without its menu, as for the original; with ECS set to On (or a real ECS) the game now works as
well. The game does not use the ECS, so turning it on gives nothing more yet.

## Not in this patch

The game has a doubles setup for four players, but nothing that reads hand controllers 3 and 4. A
four-human patch would need new code (the ECS's own controller service, as World Cup Football
uses), and is a separate, experimental piece of work.
