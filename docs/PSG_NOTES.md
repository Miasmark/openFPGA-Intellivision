# PSG notes (build step 6: the AY-3-8914)

What the PSG model (`tools/psg.py`, owned by `tools/intv_system.py`) and the
RTL (`src/fpga/core/intv_psg.sv`) do, where each fact comes from, where
they differ from MAME and why, and how both were checked: against MAME
(section 4) and against each other (section 5).

Sources (DESIGN.md section 12 for the full list):

| Tag | Source |
|---|---|
| SM | Intellivision Service Manual, Model 2609: p.19 (U6 AY-3-8914), p.56 (AY-3-8914 features: three outputs with "4 bits of logarithmic digital to analog conversion", two 8-bit I/O ports), Fig 7-2 (outputs A, B, C tied together; research/service-manual/REPORT.md "Audio") |
| S9 | jzIntv documentation `doc/programming/psg.txt` (documentation only, no code): register map on the Intellivision, clocks, the 8914's two envelope-select bits |
| MAME | MAME (BSD-3) `src/devices/sound/ay8910.cpp`, `ay8910.h`, `src/mame/mattel/intv.cpp`, `src/emu/sound.cpp`, read for facts only; run as a black box |

## 1 What the PSG does

| Fact | Model and RTL | Source |
|---|---|---|
| Register order at $01F0-$01FF | n = 0-15 is AY-3-8910 register 0, 2, 4, 11, 1, 3, 5, 12, 7, 6, 13, 8, 9, 10, 14, 15 | MAME ay8910.cpp:1533; S9 psg.txt (same table) |
| Kept bits (reads) | FF FF FF FF 0F 0F 0F FF FF 1F 0F 3F 3F 3F; the generators use no other bits | MAME ay8910.cpp:1430-1450 ("tested and confirmed on hardware") |
| Ports | $01FE right, $01FF left hand controller, inputs; enable bits 6-7 ignored | DESIGN 7.1; MAME intv.cpp:471-472 |
| Reset | registers 0 (shape 0 written: envelope restarted), LFSR 1, counters 0 | MAME ay8910.cpp ay8910_reset_ym |
| Clock | master / 2 into the chip, / 8 before the generators: one step ("tick") every 16 master clocks = 4 CPU cycles, 223,721.6 Hz (NTSC) | DESIGN 2.3; S9 psg.txt; MAME ay8910.cpp device_start (stream at clock / 8) |
| Tone | 12-bit period P; count up from 0 until count + 1 >= P, then 0 and the output toggles: F = master / (32 P); P = 0 acts as 1 | MAME ay8910.cpp:84-91 (the chip "counts up from 0 until the counter becomes greater or equal to the period"; "period = 0 is the same as period = 1"); S9 psg.txt |
| Noise | 5-bit period N; a prescaler flip-flop toggles every N ticks (0 as 1), the LFSR shifts when it falls (master / (32 N)); 17 bits, input bit 0 ^ bit 3, output bit 0 | MAME ay8910.h noise_rng_tick, ay8910.cpp sound_stream_update; DESIGN decision 3 (taps unverified on the 8914: section 6) |
| Envelope | 16-bit period E; a step every 2 E ticks, E = 0 every tick ("period = 0 is half as period = 1"); step 15 down to 0, volume = step ^ attack; at the end hold (inverting attack if alternate) or wrap to 15 (inverting if alternate); shapes with bit 3 clear act as hold = 1, alternate = attack; every write of the shape register restarts at 15, even the same value; the period counter is not restarted | MAME ay8910.h envelope_t::set_shape, ay8910.cpp:84-107, sound_stream_update, ay8910_write_ym (a shape write always updates); S9 psg.txt (16 steps, 512 E master clocks a cycle) |
| Volume (8914) | bits 5-4: 00 fixed (bits 3-0), 01 envelope >> 2, 10 envelope >> 1, 11 envelope | S9 psg.txt; MAME ay8910.h tone_envelope with PSG_EXTENDED_ENVELOPE, ay8910.cpp `env_volume >> (3 - tone_envelope)`. The AY-3-8916/8917 (ECS, step 9) have one select bit: `ENV2 = 0` / variant "8917" |
| Mixer | channel on = (tone output or tone disabled) and (noise output or noise disabled); level = volume when on, else 0 | MAME ay8910.cpp sound_stream_update comment; S9 psg.txt |
| DAC | one 16-level curve for fixed and envelope volumes: MAME's AY-3-8910 resistances (Matthew Westcott's measurements, public domain) through MAME's build_single_table (1000 ohm load, "zero is off"), normalised as MAME's legacy output does, scaled to 0..10,922: 0 148 193 252 343 476 639 1040 1283 2101 2909 3863 5161 6539 8656 10922 | MAME ay8910.cpp ay8910_param, build_single_table; SM p.56 ("logarithmic") |
| Mix | A + B + C (the board ties the outputs together) | SM Fig 7-2; DESIGN 6.2 |

**The machine's tick.** Ticks end CPU cycles 0, 4, 8, ... counted from the
first fetch (the system model's cycle 0). `intv_psg.sv` counts CPU cycle
enables in `tph` and is held, with the CPU, while `intv_bus` holds the CPU
after reset (`run = !hold`), so its first tick ends cycle 0. A register
write lands at the clock enable that ends its DW cycle, after that
enable's tick: the tick uses the old registers, and a shape write's
restart overrides the tick's envelope step (the model: `ClockedPsg`
processes all ticks up to and including the write's cycle, then writes).

**48 kHz for the Pocket** (DESIGN 6.2). Every tick takes the mix of the
levels before its step (so a write in the tick's own cycle is heard from
the next tick on), x 256, through two one-pole low passes (`y += (x - y)
>> 1`, at 223.7 kHz: -3 dB near 16.5 kHz, -12 dB at 48 kHz), adds the
result >> 8 to a box filter, and a phase accumulator (+768,000 a tick,
wrap 3,579,545: exactly 48 kHz from master / 16) ends each sample: the
box's sum x 65536 / ticks (4 or 5) >> 16, 0..32,766, silence 0.
`core_top` sends it to both channels of agg23's `sound_i2s` (MIT), which
crosses to `clk_74a`. The filter is not machine state (DESIGN 4.4): after
a state load it continues from its own state, which is at most one sample
off. The two low passes were measured against MAME's resampled output on
Astrosmash's first 1.5 M ticks (MAME's own step stream through each
filter, scored as in section 4): spectrum correlation median 0.915 with the
box alone, 0.942 with one stage, 0.949 with two, 0.947 with three, 0.954
with a 6th-order Butterworth at 18 kHz (float). What remains is MAME's
resampler and its file's wandering lag, not aliasing.

## 2 State (save-state words, module id $05, 21 words)

| Word | Bits |
|---|---|
| 0-13 | the registers (kept bits) |
| 14-16 | tone A-C: [11:0] count, [12] output |
| 17 | noise: [4:0] count, [5] prescaler |
| 18 | [16:0] LFSR |
| 19 | [16:0] envelope period count |
| 20 | [3:0] envelope step, [4] attack, [5] holding, [7:6] tick phase (the running CPU cycle's number mod 4) |

`tools/psg.py` `Psg.state(phase)` gives the same words (14-20 also as
`intv_system.SystemBus.state()['psgx']`). Hold and alternate are not
state: they follow from the shape register.

## 3 Differences from MAME

| # | MAME | Here | Effect |
|---|---|---|---|
| P1 | Tone counter keeps the remainder when a period smaller than the count is written (`count -= period` in a loop: one or more toggles at once) | restarts at 0 with one toggle, as MAME's own notes describe the chip (ay8910.cpp:84-91) | the tone's phase from such a write on; pitch unchanged. Games that sweep periods downward every frame (Atlantis, Night Stalker, Buzz Bombers) differ in up to 60 % of steps; see section 4 |
| P2 | The stream runs at int(1,789,772 / 8) = 223,721 Hz (the integer clock of XTAL / 2) on its own grid | a tick every 4 CPU cycles (223,721.5 Hz), locked to the CPU | MAME's steps slide against CPU cycles by half a step a second |
| P3 | A write takes effect at the CPU's time at the start of the writing instruction (MAME's CP1610 writes before it subtracts the instruction's cycles), after the stream sample that time falls in (sound.cpp sound_stream::update "include the current sample") | at the end of the DW cycle, after the tick of that cycle | a write lands 1-2 ticks later than in MAME |
| P4 | Envelope volumes use a second table (`build_single_table` without "zero is off") | one curve for both | envelope levels 1-14 a little louder in MAME |
| P5 | Output: 3 streams, each `((x - min) / (max - min) - 0.25) * 0.5`, x 0.33 into the speaker, MAME's resampler to 48 kHz | 0..32,766, silence 0, section 1 | level and DC only |

The comparison tool (section 4) has P1, P2 and P3 as switches
(`Psg.mame_tone`, `ClockedPsg.mame_grid` with writes at the instruction's
start) to show that nothing else differs.

## 4 Against MAME (DESIGN 9 step 6: "register logs match MAME")

`tools/refs/mame_psg.sh` runs the intv-only MAME headless on a cartridge
for N frames with keys held at chosen frames and records every CPU write
to $01F0-$01FF (debugger watchpoint), the AY-3-8914's own three output
streams at its step rate (Lua sound hook) and MAME's 48 kHz output
(`-wavwrite`). `tools/psg_compare.py` runs the system model on MAME's terms
(STIC mode "mame") with the same keys and compares (its docstring has the
details):

- **run A** (MAME's tone counter, MAME's grid and write time): the
  register-write log, every write's cycle, frame, R7, address and data,
  must be equal, and so must every one of MAME's PSG steps (all three
  channels' levels);
- **run B** (the RTL's counter): the share of steps equal to MAME's, and
  the 48 kHz output against MAME's file per 43 ms window: strongest
  frequency, spectrum correlation (47 Hz-12 kHz), RMS envelope correlation,
  waveform correlation at the best lag (MAME's file wanders by up to 100
  samples against emulated time, so no fixed lag works).

Keys are held on both controllers ("1" at frames 200-205, "Enter" at
500-505, "Upper" at 800-805 for the games that wait at their title;
MAME's frame notifier n runs before the CPU sees frame n + 1, so the model
holds the key from its frame n + 1). Results, 2026-10-25, MAME `3c6120b6`
(the owner's fork), runs and audio kept outside the repository:

| Game | Frames, keys | Writes | Log | Run A steps equal | Run B steps equal | 48 kHz (run B): strongest frequency differs / loud windows | spectrum corr median (10th pct) | envelope corr | waveform corr median |
|---|---|---|---|---|---|---|---|---|---|
| Buzz Bombers | 1800, none | 1897 | equal | 6,720,579 of 6,720,579 | 79.70 % | 18 / 295 | 0.9935 (0.9466) | 0.9989 | 0.9367 |
| Atlantis | 1800, none | 1032 | equal | 6,720,579 of 6,720,579 | 39.66 % | 30 / 702 | 0.9631 (0.8362) | 0.8614 | 0.5708 |
| Demon Attack | 1800, none | 33 | equal | 6,720,579 of 6,720,579 | 100.00 % | silent | - | - | - |
| Shark! Shark! | 1200, 1, Enter, Upper | 92 | equal | 4,478,895 of 4,478,895 | 100.00 % | 1 / 14 | 0.9998 (0.9996) | 0.9999 | 0.9947 |
| B-17 Bomber | 1200, 1, Enter, Upper | 2320 | equal | 4,478,895 of 4,478,895 | 100.00 % | 1 / 293 | 0.9997 (0.9966) | 0.9735 | 0.9855 |
| Dig Dug | 1200, 1, Enter, Upper | 486 | equal | 4,478,895 of 4,478,895 | 85.98 % | 1 / 202 | 0.9999 (0.9836) | 0.9996 | 0.9664 |
| Astrosmash | 1200, 1, Enter, Upper | 410 | equal | 4,478,895 of 4,478,895 | 100.00 % | 49 / 321 | 0.9518 (0.9399) | 0.9993 | 0.9021 |
| Night Stalker | 1200, 1, Enter, Upper | 1588 | equal | 4,478,895 of 4,478,895 | 75.22 % | 33 / 175 | 0.9955 (0.7518) | 0.9686 | 0.4165 |

All eight: the register-write log equal to MAME's, write by write, and
every PSG step of run A equal to MAME's stream (P1-P3 switched to MAME's
way). Run B differs from MAME only through P1, in the games that lower a
tone's period while it counts (Atlantis, Night Stalker, Buzz Bombers, Dig
Dug); there the waveform correlation drops (phase), the strongest
frequency stays mostly the same. For scale, run A's 48 kHz output against
the same files: spectrum correlation median 0.990-1.000 and waveform
correlation median 0.957-0.9996, except Astrosmash (0.952 and 0.902 in
both runs: its sound is mostly high and noisy, where MAME's resampler and
the core's filter differ most, section 1). The window at 0.00 s always
counts as different (MAME's output starts from its DC level).
Demon Attack writes the PSG only at start-up (33 writes, silence), Shark!
Shark! a short jingle. BurgerTime writes nothing but the EXEC's start-up
in MAME, with or without keys (31 writes in 1,500 frames); it is not in
the set. B-17 Bomber runs on plain intv (no Intellivoice), so only its
PSG music.

## 5 RTL against the model (`sim/tb/tb_system.py`)

The bench logs, per frame, a hash of every tick's three levels (before its
step: the filter's input) and of every 48 kHz sample (A lines), and
dumps all 21 state words; the driver compares them with the model:

- every image of the step-3/4/5 gate, plus **psgtest**
  (`sim/testroms/psgtest.asm`, EXEC slot): every register with unused bits
  set, tones at periods 0, 1, $00D, $FFF and 5 written while the count is
  far past it, noise at periods 0, 31 and 5, tone and noise both off, all
  16 shapes, envelope periods 0, 1, 2, $40 and $110, the same shape
  rewritten, all four volume selects, the port-direction bits, and writes
  of channel C's and the noise period in every phase of the 4-cycle tick;
- straight runs: steps and samples equal in every frame; round trips: the
  steps equal in every frame (the samples may move, the filter is not
  state), and every state word at both dumps equal to the straight run's.
  psgtest adds rt9 (restore into a reset machine) and rt10 (restore over a
  state 20,000 cycles later) in the middle of a slow triangle envelope,
  inside a CPU cycle, at a tick phase other than the reset's;
- the frame gate (`--screens`) compares the A lines of its game images
  too, frame by frame: Atlantis and Buzz Bombers (700 pictures each, both
  with demo sound) and the EXEC without a cartridge (600) were run for
  this step;
- planted faults (each must fail): LFSR tap, tone compare, envelope
  period x 1, volume selects swapped, shape write without restart, no
  alternate, tone-off bit, tick phase, write before the tick, filter
  reciprocal, one low pass, one DAC level, register mask, ports swapped,
  and each group of state words left out of the port.

## 6 Open

- Noise taps (DESIGN decision 3) and the tone counter rule (P1) on the
  8914 itself: a recording of the owner's console (DESIGN 8.5, decision
  13: RF audio) would settle both; Atlantis is the game to record for P1.
- The DAC curve is MAME's AY-3-8910 measurement, not the 8914's; SM p.56
  says only "logarithmic". A recording of a fixed-volume sweep would give
  the 8914's.
- The board's audio stage (Q3, SM Fig 7-2) has no values in the scan; the
  core's 16.5 kHz low pass is a choice, not the console's response.
