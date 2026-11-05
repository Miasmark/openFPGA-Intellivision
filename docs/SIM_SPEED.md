# Simulation speed

Where the benches' time goes, and what makes them and the release gates faster without changing a
verdict. Measured on the owner's VM (5 cores x 2 threads, 30 GiB), Verilator 5.040, g++ 15, at
0dcb29f (0.0.22), November 2026.

## 1. Profile (before)

One `tb_system --only nocart,systest` in one simulation slot, from an empty WORK (12 runs: nocart
4, systest 8): 343 s wall, 351 s CPU, peak RSS 398 MB. A cProfile of the same process for systest
alone (282 s) puts 275 s (97.7%) in waiting for the bench binary. Builds measured on their own with
the cache off (`CCACHE_DISABLE=1`), idle VM, 4 build jobs:

| Part | tb_system | tb_savestate | tb_loader |
|---|---|---|---|
| verilate (elaborate, convert) | 0.6 s | 0.7 s | 1.4 s |
| C++ compile (4 jobs; CPU) | 9.0 s (25 s) | 11.8 s (27 s) | 39.4 s (108 s) |
| link | 0.13 s | (in compile) | 0.14 s |
| whole build, cold | 9.9 s | 12.7 s | 41.2 s |
| a plant's build, cold | 9.6 s | 13.0 s | 42.8 s |
| Python model (expectations) | nocart 0.3 s, systest 0.8-1.9 s; `--all`'s 40 images 50 s | (Python blob checks: small) | 115 images 112 s |
| simulation | 1.4-1.6 s a frame: nocart 15-19 s a run, systest 31-35 s | about 1.5 s a frame; a plant's image runs R and S in full, then its loads | 6 s a run (859 runs in 0.0.22's gate: 5,380 s) |
| reading the run's log, comparing | systest: 3.4 s parse, 0.8 s compare, 0.4 s pictures for 8 runs (1.6%) | small | small |

Inside the simulation (gprof of the tb_system binary, nocart): 85% in the model's evaluation
(Verilator's `nba_sequent`, `nba_comb` and `act_sequent` functions of the design) and about 8% in
the timing scheduler (`always #5` clock: coroutine resume, triggers). There is nothing left to win
in Python: the time is the RTL model's.

The 0.0.22 gate (gate22, 3-4 November: 15 h 20 min from the start to the last bench, a Quartus fit
and three simulation slots) by bench (times include waits for a slot behind the other benches):

| Bench | Wall | What |
|---|---|---|
| tb_savestate --plants --jobs 2 | 15 h 11 min | 17 images (213 runs: R, S, loads; 82,833 s), then 22 plants (257 runs, 22,772 s) |
| tb_system --only (10 hardware-test images) | 7 h 11 min | 3,140 frames, each image 4-8 runs; 7.4 GB peak RSS (every image's model kept) |
| tb_system --ecs-play | 6 h 1 min | 8 runs of 900-4,300 s |
| tb_voice --all --plants | 6 h 3 min (5,841 s of its own) | 67 runs, 23 plants x 3 builds and up to 15 runs |
| tb_system --all --mame | 4 h 45 min | 40 images: 221 runs, 8,793 s; 185 plants: a build and (mostly) one run each |
| tb_loader --all | 4 h 34 min | 115 images, 56 plants x (a 41 s build, up to 43 runs) |
| tb_system --screens (4 parts) | 4 h 13 min | 19 runs of 260-1,170 s |
| tb_cpu, tb_timing, tb_input, tb_osk | 3 h 44 min | |
| tb_system --play | 1 h 15 min | 3 runs |

## 2. The C++ build: ccache and -O2

ccache was already in use: Verilator 5.040's generated makefile compiles through `$(OBJCACHE)`,
which its installation set to `ccache`. But the cache was the user's default one
(`~/.cache/ccache`, 5 GB), shared with the other cores' builds, full (99.9%) and cleaned out 4,762
times, so a plant's objects rarely lived until the next gate. Now (sim/tb/tbcommon.py):

- every bench build sets `OBJCACHE=ccache` itself when ccache is installed (`OBJCACHE=` turns it
  off); the gate scripts point `CCACHE_DIR` at `~/daria_work/ccache`, 20 GB, compressed
  (`CCACHE_DIR=~/daria_work/ccache ccache -M 20G`; ccache.conf there keeps the limit);
- the model's code and Verilator's runtime are compiled at `-O2` (`-MAKEFLAGS OPT_FAST=-O2
  -MAKEFLAGS OPT_GLOBAL=-O2`; Verilator's default is `-Os`).

What the cache gives (a fresh dedicated cache, the build after the unplanted one):

| Build | tb_system | tb_savestate | tb_loader |
|---|---|---|---|
| unplanted, empty cache | 10.9 s, 0 of 17 hits | 14.5 s, 0 of 16 | 41.6 s, 0 of 15 |
| a plant, first time | 3.7 s, 14 of 17 | 13.7 s, 3 of 16 | 43.2 s, 3 of 15 |
| the same plant again (another folder) | 4.0 s, 14 of 17 | 4.4 s, 13 of 16 | 2.5 s, 15 of 15 |
| unplanted again (another folder) | 1.6 s, 17 of 17 | 1.8 s, 16 of 16 | 2.5 s, 15 of 15 |

Verilator splits the model into files by what they depend on, so a plant recompiles only the files
with the planted module's code (tb_loader's and tb_savestate's plants touch most of theirs) and the
runtime's three files always hit. The files that call `$stop`/`$fatal` carry the source path, the
plant's folder, so they miss in another folder (tb_system's 3 of 17). A plant whose RTL did not
change since the last gate rebuilds from the cache: the gain is in the next gate and in reruns, not
in the first build of a changed module.

`-O2` against `-Os`, the same 18 runs (nocart, systest, psgtest) concurrently: 444 s of runs
against 534 s (83%; every run 15-19% faster). Every run's log and picture file (36 files) is
byte-identical to `-Os`'s; only the binary's own `walltime` report line differs. `-O3`: systest's
8 runs 222 s against `-O2`'s 230 s (4%, within the noise of a shared VM), its 16 files identical
too; not taken. A cold build at `-O2` takes 13.0 s against 9.9 s (tb_system).

## 3. Plants stop at their first difference

A planted fault only has to make one run fail to count as caught, so each plant runner now stops at
its first failing run:

| Bench | Stops | What a plant still runs |
|---|---|---|
| tb_system | `check_image(first_fail=True)`: after the first run with a problem | most plants have one run anyway; 27 have 2-3 |
| tb_savestate | `run_image_set(stop=...)`: once a problem matches the plant's own reason (`why`); the runs not started are cancelled, the ones running finish | R and S of its image, then its loads in order up to the first that fails for its reason |
| tb_loader | `run_set(first_fail=True)`: at the first failing image | the plant images (43) in order up to the first that fails |
| tb_voice | the plant's run loop at the first failing run | `PLANT_RUNS` in order up to the first that fails |
| tb_input, tb_osk, tb_cpu, tb_timing | (one run a plant: nothing to stop) | |

The verdicts cannot change: a plant that is not caught (or, in tb_savestate, caught for another
reason only) has no failing run, so it never stops and runs everything as before. Runs are checked
in a fixed order and tb_system's comparison between runs comes after them, so the problems a stopped
plant reports are the first ones of the full set: tb_system's and tb_savestate's PLANT lines are
the same, word for word. tb_loader's and tb_voice's "caught by" now name only the first image or
run (they used to list every one that failed).

## 4. Memory: one image's model at a time

tb_system kept every image's model (the expectations: bus log, steps, pictures, row fetches, sound)
for the whole process, and check_image kept every run's parsed log until the comparison between
runs: `--only` with the ten hardware-test cartridges peaked at 7.4 GB. Now, with several images or
any plants, tb_system.py is a parent that runs each image (model, then its runs), and each run of
consecutive plants on one image, in a child process (`--child images|plants`); the parent passes
the child's lines through (a plants child's model lines are dropped: the image's own child printed
them), collects its fails in the single process's order and prints the same last line. check_image
keeps only each run's dumps for the comparison between runs. A single image without plants runs in
the process itself, as before.

| | before | after |
|---|---|---|
| `--only hw_cpuodd,hw_ecskeys,hw_grantx` (200 frames), peak RSS | 1,109 MB | 322 MB |
| the same, wall (one slot each, side by side; after = -O2 too) | 31 min 50 s | 26 min 51 s |
| `--all --mame`, peak RSS of any process | 1,784 MB with the 40 models alone, before the first run | 401 MB |

One image's model alone (the model only, one process, peak RSS): hw_rowcopy (1,150 frames) 3,397 MB,
hw_frame (720) 2,142 MB, hw_steal (460) 1,394 MB, hw_intlate (230) 687 MB, hw_steal2, hw_grant
(130) 400 MB, hw_frame2 (120) 370 MB, hw_grantx (80) 253 MB, hw_cpuodd, hw_ecskeys (60) 200 MB. So a
process now peaks at its largest image (about 3 MB a frame), not at the sum (9.4 GB for the ten).
The lines are the same but for their order (each image's model lines now come just before its
runs) and the timings; the three images' lines, times taken out, are identical.

## 5. Results reused only on byte-identical inputs

`sim/check/run_cache.py CMD...` runs a bench and, opt-in (`RUN_CACHE=DIR`, set by the gate scripts
only), reuses a stored pass when every input that can change the result is byte-identical. The
rule:

- the key hashes the git trees of `src/fpga`, `sim` and `tools` at HEAD; the bench's command line
  and the folder it runs in; the environment variables the benches read (`VERILATOR`,
  `INTV_BIOS_DIR`, `INTV_LIBRARY`, `INTV_TRACE_ROOT`, `INTV_PLAY_ROOT`, `INTV_GAME_DIR`,
  `INTV_VOICE_REFS`, `INTYBASIC`, `INTYBASIC_LIB`, `AS1600`, `TB_SYSTEM_TIMEOUT`) and the content of
  every file in the paths they name (or their defaults when unset): the BIOS files, every cartridge
  image of the library, the MAME traces and play references, the voice references, IntyBASIC and
  as1600; Verilator's `--version`, g++'s and Python's versions;
- any change or untracked file under `src/fpga`, `sim` or `tools` (`git status`) turns it off: the
  trees would not say what ran;
- a result is stored only when the bench exited 0, so a FAIL is never reused, and is reused only
  under exactly its key: anything else reruns;
- a reused result prints the stored output after one first line, `RUN_CACHE reused KEY: exit 0
  on DATE after N s`, and exits 0; the gate's checks then read the same lines as from a run.

What it does not see: anything a bench reads that is not in the list (a new environment variable
or an outside tool would have to be added to `ENV`), the machine (the benches' results do not
depend on it: `-Os`, `-O2` and `-O3` gave identical files) and the WORK folder (only the log is
reused, never WORK's files: the gate's checks read only the logs). It pays when a gate is run again
on the same trees (a gate script fixed, a part rerun, a release head whose `sim/` and `tools/` did
not change); a change to the RTL reruns everything.

## 6. Gate scheduling

The 0.0.22 gate ran three chains of benches one after another in the three simulation slots, and
tb_savestate (15 h) set its length. The next gate's scripts (`~/daria_work/intv/gate23/scripts`,
not run yet) keep the same checks but make jobs of them and deal them, longest first, to three
workers (`sched23.sh`); a worker takes the next job when its last one ends, each simulation goes
through simslot, and the fit runs beside them (1 Quartus + 3 simulations):

- tb_system `--all --mame`, the ten hardware-test cartridges and `--ecs-play` in three parts each
  (`--part K/3`), tb_loader `--all` in two, tb_savestate's plants in two (`--plants-only --part
  K/2`) beside its image set (`--jobs 2`: its foreign loads cross the images, so the set stays one
  process);
- tb_cpu, tb_timing, tb_input, tb_osk, the PSG compares, the model's frames and traces, the four
  screens parts, the play bench, the ECS references and the Python gates as one job each;
- every bench through run_cache.py (section 5);
- `finish23.sh` merges each split bench's parts into 0.0.22's log name with one verdict line and the
  largest exit code (`merge23.sh`; any part's failure, missing verdict or missing EXIT fails the
  whole), and `checkgates23.sh` runs 0.0.22's checks on them, plus: every image and plant in one
  part (the counts from the bench's own lists), every job started and ended, the reused logs listed.

`--part K/N` deals the items to N parts, the costliest first, each to the part with the least
cost so far (frames; for tb_system's plants, frames times runs plus a build); every item is in
exactly one part and each part keeps the list's order (checked for N = 1-4 on every list).

## 7. Before and after

Measured on 5 November at 1bd64e5 (the benches of this branch; `src/fpga` = 0dcb29f's) while the
VM's other session ran up to four simulations of its own (load 4-9 on 10 threads): timings are
noisy, and a "before" taken side by side is the fairer comparison.

| Bench | Before | After |
|---|---|---|
| tb_system `--all --mame` | 4 h 45 min (gate22) | 4 h 16 min in one process (images 2 h 20 min, plants 1 h 56 min); in 3 parts about 1 h 26 min each |
| tb_savestate `--plants --jobs 2` | 15 h 11 min (gate22; 54,672 s of its own) | 4 h 19 min (15,535 s); plants 257 runs before, 148 after |
| 4 savestate plants side by side (`--jobs 1`) | 50 min 39 s, 52 runs | 15 min 52 s, 15 runs |
| tb_loader `--all` | 4 h 34 min (gate22) | 1 h 31 min |
| 6 loader plants side by side | 30 min 55 s | 13 min 43 s |
| tb_voice `--all --plants` | 5,841 s (gate22, its own time) | 937 s |
| 4 voice plants side by side | 3 min 23 s | 2 min 9 s |
| tb_input `--all` (partly side by side) | 52 min 14 s | 45 min 41 s |
| tb_osk `--all` (partly side by side) | 1 h 34 min 46 s | 1 h 14 min 35 s |
| tb_cpu, tb_timing `--all` (side by side) | 1 min 52 s, 1 min 30 s | 2 min 23 s, 1 min 23 s (the -O2 build, cold in the new cache, costs more than the short runs save) |
| tb_system, 3 hardware-test cartridges (side by side) | 31 min 50 s, 1,109 MB | 26 min 51 s, 322 MB |

Peak RSS: tb_system `--all --mame` 401 MB (its largest process; before, the models alone took
1,784 MB), tb_savestate 503 MB, tb_loader 855 MB, tb_voice 401 MB.

A whole gate (0.0.22's checks, gate23's jobs on 3 slots, longest first; minutes in one slot:
measured above, or 0.0.22's run times x 0.83 for the hardware-test cartridges, `--ecs-play`, the
screens and the play bench, which only -O2 speeds up): 33.3 slot-hours of simulation, so about
11 h on 3 slots, against 0.0.22's 15 h 20 min. What is left is the RTL model's own speed: the
hardware-test cartridges (5.9 slot-hours), tb_savestate's image set (5.8), `--ecs-play` (5.0),
tb_system `--all` (4.3) and the screens (3.5) are all simulation.

The same verdicts (every bench above, at 1bd64e5, against 0.0.22's gate logs; tb_system's systest
lines and its 23 systest plants against their rerun at 0dcb29f, where csmode_no_open is caught):
tb_system `--all --mame` 540 lines (every model and self-check line, both MAME compares, every
run's counts, the 40 image verdicts, all 185 PLANT lines word for word, the last line) identical;
tb_savestate 65 lines (every image's R/S line, the JLP slot, all 22 PLANT lines) identical but for
the WORK folder in two messages (one of them cut at 150 characters, so at another place); tb_loader
the set's 118 lines identical, and for each of the 56 plants the verdict, the first catching image
and that image's FAIL line; tb_voice the set's 69 lines, and each of the 23 plants' verdict and first
catching run (0.0.22's list's first); tb_input 76 lines and tb_osk 17 lines identical (also against
0dcb29f run side by side, as tb_cpu's 31 and tb_timing's 57 lines, whose 0.0.22 log kept only
the tails); the three hardware-test cartridges' lines identical but for times and order;
0.0.22's screens_d run as `--part 1/2` and `2/2` and merged by merge23.sh: the same lines.

## 8. Not done

- Faster models: the profile leaves the design's evaluation (85%); `-O3` gave 4%, inside the
  noise. A C++ clock instead of `always #5` would save at most the scheduler's 8% and changes every
  bench.
- A fourth simulation while no Quartus job runs (the owner's limit allows it; simslot keeps 3, as
  this work was asked to): 33 slot-hours on 4 slots would be about 8.3 h.
- Splitting tb_savestate's image set: its foreign loads take the next image's blob, so parts would
  run other tests; it keeps `--jobs 2` instead.
- Leaner model data: one image still holds its whole model (hw_rowcopy 3.4 GB); a 3-part split of
  the hardware-test cartridges can hold up to about 7 GB at once.
- ccache across folders for the files that carry the plant's source path (`$stop`): building from
  relative paths would make them hit, for about 2 s a tb_system plant.
