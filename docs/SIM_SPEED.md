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
