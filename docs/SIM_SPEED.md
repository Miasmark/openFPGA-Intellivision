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
| Python model (expectations) | nocart 0.3 s, systest 0.8-1.9 s; `--all`'s 37 images 50 s | (Python blob checks: small) | 115 images 112 s |
| simulation | 1.4-1.6 s a frame: nocart 15-19 s a run, systest 31-35 s | about 1.5 s a frame; a plant's image runs R and S in full, then its loads | 6 s a run (859 runs in 0.0.22's gate: 5,380 s) |
| reading the run's log, comparing | systest: 3.4 s parse, 0.8 s compare, 0.4 s pictures for 8 runs (1.6%) | small | small |

Inside the simulation (gprof of the tb_system binary, nocart): 85% in the model's evaluation
(Verilator's `nba_sequent`, `nba_comb` and `act_sequent` functions of the design) and about 8% in
the timing scheduler (`always #5` clock: coroutine resume, triggers). There is nothing left to win
in Python: the time is the RTL model's.

The 0.0.22 gate (gate22, 3-4 November: 15 h 20 min from the start to the last bench, a Quartus fit and three
simulation slots) by bench, in
its slots (times include waits for a slot behind the other benches):

| Bench | Wall | What |
|---|---|---|
| tb_savestate --plants --jobs 2 | 15 h 11 min | 17 images (R, S, loads: 84,192 s of runs), then 22 plants (21,400 s of runs) |
| tb_system --only (10 hardware-test images) | 7 h 11 min | 3,140 frames, each image 4-8 runs; 7.4 GB peak RSS (every image's model kept) |
| tb_system --ecs-play | 6 h 1 min | 8 runs of 900-4,300 s |
| tb_voice --all --plants | 6 h 3 min (5,841 s of its own) | 67 runs, 23 plants x 3 builds and up to 15 runs |
| tb_system --all --mame | 4 h 45 min | 37 images: 221 runs, 8,793 s; 185 plants: a build and (mostly) one run each |
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
