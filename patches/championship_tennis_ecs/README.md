# Championship Tennis: ECS patch (ECS page fix + four human players)

A patch for Championship Tennis (INTV, 1985) that

1. lets the game run with the Entertainment Computer System attached and on (without it the title
   is garbled and the game's own code at `$E000-$EFFF` is replaced by the ECS's ROM), and
2. lets four people play doubles, with hand controllers 3 and 4 on the ECS's two controller ports.
   The game has always had a four-player doubles setup, but nothing that read controllers 3 and 4.

One patch, applied to the original image, does both. (The first version of this folder held the
page fix alone; git keeps it.)

This folder holds only our own work: the patch's assembly source, the BPS patch (the changed words
and checksums, no game code), the memory map for the patched image, and the build script. You need
your own copy of the game.

| | |
|---|---|
| Source image | `Championship Tennis (Europe).int` (No-Intro), 32,768 bytes, CRC32 **4CC46A04** |
| Patched image | 32,768 bytes, CRC32 **D85F816E** |
| Patch | `championship_tennis_ecs.bps`, 652 bytes (its CRC32 BE52AFCF), 201 words changed |
| Memory map | `championship_tennis_ecs.cfg` (`$0000-$1FFF` at `$5000`, `$2000-$3FFF` at `$D000`) |

## What it changes

### 1. The ECS page fix

The ECS's ROM has three 4K pages; the third sits at `$E000-$EFFF` and is paged in by the ECS's boot
(`$EA51` written to `$EFFF`). Championship Tennis maps its own ROM at `$D000-$EFFF` and runs code at
`$EF10` while the EXEC draws its title (from the cartridge's title routine at `$5056`). With the ECS
on, that code is the ECS's, so the title shows garbage and later reads of the game's `$E000` data
get ECS ROM words.

The patch pages the ECS's `$E` ROM out again by writing `$EA50` to `$EFFF`, the bank-switching
documented in jzIntv's ECS notes (`doc/tech/ecs.html`) and used by World Series Major League
Baseball, before the title routine goes on: `$5056-$5058` (the title routine's first two
instructions) become `J $6FE0`, and a 15-word stub at `$6FE0` replays them around the write and
jumps back to `$5059`. Without an ECS the write lands on the cartridge's ROM and changes nothing.

### 2. Hand controllers 3 and 4

**Why not the ECS's own service.** The ECS ROM can read controllers 3 and 4 for a game: World Cup
Football hands its main loop to the ECS ROM (`$70C4`), whose loop runs the EXEC's hand-controller
decoder (`$152F`) a second time for the ECS's ports, with bit 5 of `$015E` set while the game's
handlers run. But that loop also acts on bits of `$015D`, `$015E` and `$015F` (its own flags), and
Championship Tennis uses those bytes as its own variables: its start table sets `$015D-$0160` to
2, 3, 6, 7, the object numbers of players 1-4 (`$015C` + player, used with the EXEC's object
routines). The game cannot run under that loop; this may be why its four-player code was left
unused.

**What the patch does instead** (the ECS ROM's `$7134` routine, redone from the game's side):

- The header's start address (`$5004`) points at a 26-word routine that probes the ECS RAM (writes
  1 to `$47CD` and reads it back, as World Cup Football does) and, with an ECS, sets this patch's
  ECS RAM bytes `$47D0-$47D6` to an idle controller state, then jumps to the game's start (`$5200`).
- The game's task routine (`$5072`, run once per pass of the EXEC's main loop, the same rate as the
  EXEC reads controllers 1 and 2) starts with a `J` to a 17-word hook: when the ECS RAM answers, it
  calls a 39-word routine (with an 18-word swap routine) that makes the ECS's two ports inputs
  (sound chip register `$00F8`, bits 6 and 7), swaps the EXEC's controller state (`$011F-$0124`)
  with the one kept for controllers 3 and 4 in ECS RAM, runs the EXEC's decoder for `$00FF`
  (controller 3, port B) and `$00FE` (controller 4, port A) with a marker byte (`$47D6` = `$5A`)
  set, and swaps back. The ports match MAME's `ecs_ctrl.cpp` (lines 149-157) and the ECS ROM's own
  `$7134`.
- The game's hand-controller handler table (`$52D0`, copied to RAM by the game) points at five
  8-word stubs, one per handler (disc `$D000`, keypad `$6489`, side buttons `$DD2B`, `$DD30`,
  `$DD35`), and an 11-word common part: each adds 2 to the controller number (R1) while the
  marker is set, then enters the game's handler. The handlers' own `INCR R1` makes that 3 or 4,
  and they map controller to player through the game's table at `$0175` + controller. The game's
  code already treats that table as four entries (its player-to-controller search at `$5B9D` walks
  it from `$0176` up); in the original, nothing but the start-up clear ever writes `$0178`/`$0179`.
- One fix in the game's own four-player code: between points it re-sends each human player's
  held disc direction (`$E0DC-$E0F3`), reading the EXEC's state byte at `$011E` + controller. For
  controllers 3 and 4 that is `$0121`/`$0122`, which the EXEC uses for something else, so players 3
  and 4 were sent off running (direction 0) at every point. `$E0DF` now jumps to a 14-word stub at
  `$6FF0` that reads controllers 3 and 4's state from ECS RAM (`$47D0`/`$47D1`) instead.

Positioning and the match then run on the game's own code: the controller that moves first while
"PLAYER 3 POSITION ?" shows claims player 3, likewise player 4, and placing all four starts the match
in mode 0 (`$0198 = 0`), the four-human mode the game always had.

**Without an ECS** the probe fails, so nothing is polled, and the marker read at `$47D6` (no memory
there) never gives `$5A`: the game runs as the original. The source is `tennis_ecs.asm`
(tools/as1610.py).

### Where the new code lives

Most zero runs in this image are tables, not free space; the new code uses two padding runs that no
game code reads:

- `$6FE0-$6FEE`, the page fix's stub, and `$6FF0-$6FFD`, the held-disc stub. The original reads
  `$6FC5-$6FC9` (the end of the last record, at the first court in singles) and nothing at
  `$6FCA-$6FFF`.
- `$EF5A-$EFF0`, the controller code (151 words) in the zero padding at the end of the `$E000`
  segment, right after the last routine (the title code at `$EF10-$EF59`).

Access logs (model, every bus access): the original read nothing at `$6FCA-$6FFF` in six runs
(three courts, singles and doubles, page fix above), and in a jzIntv run of the original with
memory attributes logged, its last code in the `$E000` segment ends at `$EF59`. Over a long
original two-player singles game in the model (60,000 frames, ECS off: 17 games, a 5-7 set and the
start of the next), nothing at all touched `$6FCA-$6FFF` or `$EF5A-$EFFF`, and `$0178`/`$0179`
were only cleared at start-up. In the
patched game's full four-player match (below) the only accesses to `$EF5A-$EFFF` and
`$6FE0-$6FFF` were the patch's own code, and `$0178`/`$0179` were written only by the disc
handler's claim (`$D038`) and read only by the handlers (`$D030`, `$DD50`) and the
player-to-controller search (`$5BA0`).

## Playing with four people

- Controllers 1 and 2 are the console's, 3 and 4 the ECS's (port B = 3, port A = 4). On the Pocket
  core this needs the ECS's controller ports wired to Dock controllers 3 and 4 (planned for 1.0.9);
  until then the patched game plays as before with two. In jzIntv (`-s1`) they are `PD1L_` and
  `PD1R_`.
- After the location, "PLAYER n POSITION ?" asks for each player in turn: move with that player's
  controller into one of the boxes and press Enter. The first controller to move claims the player.
- Teams are whoever stands on the same side of the net, as in the original's two-player doubles:
  any arrangement works (players 1 and 3 against 2 and 4, or 1 and 2 against 3 and 4, ...), and
  the game alternates the serve between the teams (1, 4, 3, 2 for the first, 1, 3, 2, 4 for the
  second). To reach a box on the other side, walk around the **left** net post (along the left
  edge of the court): the net blocks the middle and the right-hand side.
- Keypad 0 while player 3 waits still gives the computer doubles, Clear the singles, as before.
- Serving (as in the original): a lower side button tosses the ball and a second press hits it; the
  top button lobs (in the model, top-button serves were always faults).

## Checked

Model (tools/intv_system.py, with the ECS's hand controllers 3 and 4 added on this branch:
`pN:KEY` presses, port B = controller 3, port A = controller 4):

- **Four humans, ECS on, a full match.** All four placed with their own controllers
  (`$0176-$0179` = 1-4, `$0180` = 5, mode `$0198` = 0), then a best-of-five match played to its
  end by a script that only serves (toss with a lower side button, hit 25 frames later; to lose a
  game the server lobs two faults): sets 6-0, 0-6, 6-0, 6-0, "MATCH" after 44,000 frames. Serve
  order 1, 4, 3, 2 in all 24 games, across sides and sets; points, games and sets counted for the
  right team each time (the team of players 1 and 3, then players 2 and 4 in the second set), with
  "FAULT", "2ND SERVE", "GAME", "SET PT", "SET", "MATCH PT", "MATCH" as in two-player play. No
  hand-controller call for controllers 3 or 4 outside their own input once the held-disc fix was in.
- **Four humans, other teams, a full match.** Players 1 and 2 placed on the near side, 3 and 4
  walked around the left net post to the far boxes: serve order 1, 3, 2, 4 in all 32 games, sets
  2-6, 6-2, 2-6, 2-6 (the scripted serves did not always do what the script meant), "MATCH" when
  the team of players 3 and 4 won its third set. In jzIntv, too, player 3 crossed around the left post to the far side.
- **Four humans, ECS Auto with the `.cfg`** (ECS attached, no ECS menu): placed, mode 0, first
  game played.
- **Two players, unchanged**: singles and computer doubles (keypad 0), with the ECS off, on and
  on Auto, played by the same serving script against the original (ECS off) and the
  page-fixed-only image (ECS on): the same screens and the same kind of play (positioning,
  points, faults and games counted as usual). Which serves go in, and so the scores and the frames
  of later points, differ, because the game's play depends on CPU timing: the page fix alone (a few
  cycles at the title) already changes singles against the original exactly as the whole patch
  does (ECS off, page-fixed and patched runs score the same points on the same frames). With the
  ECS on, the per-pass work for controllers 3 and 4 shifts the timing a little more.

jzIntv (black box, its own ECS emulation, `-s1`; four hand controllers bound to keys, driven under
Xvfb): ECS on: the ECS menu, the game's title, all four players placed with controllers 1-4, points,
games and the side change; two-player singles. ECS off: the computer doubles with scoring. (jzIntv
needs `$3000-$3FFF = $E000 PAGE 0` in its own `.cfg` for the cartridge's `$E000` segment with the
ECS on; the core's `.cfg` here does not use it.)

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
without its menu, which is all the four-player code needs (the ECS RAM and controller ports answer
with the ROMs paged out); with ECS set to On (or a real ECS) the game works as well, through the
ECS's menu. With ECS Off it plays as the original, two players.

## Open points

- **The core.** Controllers 3 and 4 need the ECS's controller ports on the Pocket (Dock
  controllers 3/4), planned for 1.0.9; nothing in this patch can be tried with four people on the
  Pocket before that. With one or two controllers the patched game plays as before, ECS on or off.
- **Hardware.** Checked in our model and in jzIntv only. The ECS RAM probe, port directions and
  marker byte follow the ECS ROM and MAME, but no real ECS has run it.
- **Game rules nobody shipped.** The four-player mode is the game's own, unfinished-looking code:
  one bug is fixed here (the held disc).
  Rallies with four people returning the ball were tried only briefly (jzIntv); the full match used
  serves only.
- **Timing.** The patch adds work to every main-loop pass (with the ECS, two more passes through the
  EXEC's decoder), so the game's timing-dependent details differ slightly from the original.
