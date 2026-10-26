# tb

Verilator testbenches, one per build step (DESIGN.md section 9). Outputs go
to `sim/work*`.

| Bench | Step | Run |
|---|---|---|
| `tb_timing.sv` | 1: timing, video port, timing state port | `sim/tb/run_tb_timing.sh --all` |
| `tb_loader.sv` | 2: loader, CRC table, page table, system ROMs, cart state port | `python3 -I sim/tb/tb_loader.py --all` |
| `tb_cpu.sv` | 3: the CP1610 RTL in lockstep with the Python model | `sim/tb/run_tb_cpu.sh --all` |
| `tb_system.sv` | 3-6: the machine (CPU, bus fabric, RAMs, STIC, PSG) with timing and loader, against the system model | `python3 -I sim/tb/tb_system.py --all`; the frame gate (steps 4-6) `--screens` |
| `tb_input.sv` | 6: the input module against the input model and MAME's hand-controller tables | `python3 -I sim/tb/tb_input.py --all` |

`tb_loader.py` builds `tb_loader.sv` with the real `core_bridge_cmd.v`,
agg23's `data_loader.sv`, `apf_datatable.sv` and `intv_media.sv`, plus our
own simulation models in `models/` (Intel's `dcfifo` and the template's
`mf_datatable`, which Verilator cannot take from Quartus, and the Pocket's
AS6C2016 SRAM with its read and write timing checked). For every image of
`sim/regress/step2_set.csv` it computes each line the bench prints from the
mapper model and compares: CRC, words, layout, flags, slot status, the stored
image, ECS/EXEC/GROM/Intellivoice ROMs, the full mapped space at reset paging
and at pages 1, 2, 3 and 15 of every 4K range, after a write to every
address, after a machine reset, and the state round trip (save, clear,
restore), and last a slot read (0x0080) and "all complete" again with no
cartridge stream, which must not run the loader's finish again. The host
gives the cartridge's size with 0x0082 too; `apf_datatable` checks the data
table's length against it, and four extra cases on the 4n+1 synthetic image
cover it with the data table before and after the files: a 0x0082 size 4
bytes long (loaded with the table's length, err[4]) and a table without the
cartridge (the 0x0082 size used). Two reload cases load that image and
then, in the same session (no power-on reset), another cartridge with its
own 0x0082 size: synthetic:b (in the table) and C2063C08 (paged, no table
entry); the second must be mapped with its own length. Images are taken from the owner's library
by path and extracted only into `sim/work` for the run; the `forced:` rows
come from `tools/synth_image.py` (a table CRC, no game data). `--all` then
builds 15 planted faults (CRC over the padded length, little-endian words,
page table read one entry off, odd last byte, default map not cut, SRAM
sampled early, selects kept on machine reset, selects dropped on restore, no
size check, no length cross-check, no fallback to the 0x0082 size, the
0x0082 size of any slot, the finish rerun on every "all complete", a
reload's byte 0 not arming the finish, only the first 0x0082 size kept); each
must fail.

`tb_cpu.sv` checks the CP1610 RTL (`src/fpga/core/cp1610.sv`) in
lockstep with the Python model, cycle by cycle: bus phase, address and
data, BUSAK, halt, TCI/SIN, the cycle every step ends in with R0-R7,
S Z O C, I and D there, and the final registers. Cases from
`tools/cpu_buslog.py`: the 36 programs of `sim/tests/cpu` (the three
asm-error tests have none), 1,420 opcode-sweep cases and 300 random
programs, each run once straight and once with save points (state
saved mid-instruction, in the interrupt sequence and in bus waits,
restored into the other CPU instance, fresh or stale, and run on).
`run_tb_cpu.sh --all` also builds planted faults and fails unless the
bench catches each one.

`tb_system.py` runs `tb_system.sv` (step 4 additions below): `intv_machine` with the real
`intv_timing`, `intv_media` and the SRAM model, the system ROMs and the
cartridge loaded through the loader's byte port, for 10 frames
(149,340 CPU cycles; systest 22). Images: no cartridge, Astrosmash (from
the owner's library), `sim/testroms/systest.asm` in the EXEC slot (two
different hand-controller bytes), and `sim/testroms/carttest.asm` in the
EXEC slot with two synthetic cartridges (`tools/synth_image.py`, CRCs
forced to the table's 8-bit cart RAM layout 25 and paged layout 26). For
each, the system model (`tools/intv_system.py`) gives every bus phase other
than NACT with its cycle, address and data, R0-R7, S Z O C, I and D at
every step start, every change of the STIC handshake and mode latch with
its cycle, and the RAMs, STIC and PSG registers, latches and page selects
at two dumps (cycle 82,670 and the end); every run must match all of it.
For systest it also checks that the section-7 probes land in their frame
slots (3788-3791, INTRM's last sample and, from step 5, a write to $18 in
a display-off frame's last slot, 14,933, where the STIC ORs in the frame's
collision bits). Four runs per image: straight,
and three save/restore round trips (DESIGN 8.4): into a reset machine at
the last cartridge read (or in VBlank), over the state 20,000 cycles later
(the run rewinds), and into a reset machine outside VBlank; before every
restore all state words, and the 16K cart RAM cells through intv_media's
aux port, are overwritten with junk. The freeze lands mid-cycle, the
raster runs on and the machine resumes when it comes round. Every state
word must also read back as written and be identical across the runs at
both dumps. With `INTV_TRACE_ROOT` set, the system model is first
compared with MAME's traces (no cartridge: image `none`; Astrosmash).
`--all` then builds 32 planted faults, each of which must fail: bus
behaviour (pull-ups, GROM / EXEC / scratchpad upper bits, INTRM a line
late, CPU started a line early, IAB vector, STIC read mask, STIC always
open, STIC aliases, GRAM windows, PSG mask, the mode latch's alias read,
open check and write, the window's end one cycle either way, INTRM's end
one cycle either way, hand controllers swapped, closed GRAM reads with 11
offset bits, cartridge writes not asked or cut to 8 bits) and the state
port (RAM, PSG, held cartridge word, IAB vector flag, handshake, latched
address, and restore writes lost in GRAM, scratchpad or System RAM alone).

Step 4 (the STIC, `intv_stic.sv`). The model runs in STIC mode `stic`
(BUSRQ on, as the core runs it) for every image except `systest` (its
probe delays were tuned without BUSRQ) and `astro_nobusrq` (Astrosmash
again with `+busrq=0`, model mode `none`). Every run is also compared on
the STIC's side: every picture (189 x 240 colours, `+pic`, the model's
picture numbering), every row fetch (its cycle's frame, row, loaded or
missed, the FIFO address counter, the 20 words loaded) and every card row
(card, GROM / GRAM / squares, card address at the row's first line); the
dumps add the row buffer and the FIFO counter. Two more round trips where
the display is on: a restore into a reset machine 17 clk_sys into a row
copy (word 8 of 20, the CPU in BUSAK), and a rewind restore 3 cycles into
a fetch line (the CPU in BUSAK, the card engine building the row's first
line); the bench saves and restores its own picture capture with the
state. Image `sticbus` runs our `sim/testroms/sticbus.asm` (24 frames,
BUSRQ on): pseudo-random BACKTAB and GRAM (every card kind), delays,
border extensions, Color Stack and FGBG frames, blank frames with a late
border colour (it shows from that pixel on: STIC_NOTES D17), a display
enabled after the window (blank, STIC_NOTES D8), a frame without INTAK
(the FIFO counter past System RAM), shift blocks that make the CPU miss
row fetches, and the row-load deadline exactly: BUSAK at R + 57 (the row
loads) and at R + 58 (missed); the bench fails (STICBUS_DEADLINE) unless
the model shows both. `--all` adds 41 STIC plants (colour-stack advance,
restart and row start, vertical and horizontal delay one short, top
border extension, BUSRQ three lines a row, frame BUSRQ 43 cycles, GRAM /
GROM select swapped, FGBG GROM with 256 cards, squares off, squares
quadrants 1 and 2 swapped, FIFO counter not cleared by INTAK or not
stopped, missed rows loaded anyway, fetch a line late, display enable
read live, border colour a CPU cycle late or latched per frame; the
step-4 review's: pastel foreground dropped, FGBG background bits 12/13
swapped, squares colour 7 shown direct, squares quadrant 3 bit 2 dropped,
160th column shown, left extension ignored, pixel order reversed, frame
BUSRQ always on, 13th row fetch dropped, Color Stack GROM limited to 64
cards, stack advance on squares cards, top extension moved by VDR,
counter stepping on missed rows, row-load deadline a cycle early, a cycle
late or two late; state port: row buffer, line buffer, copy state, the
frame's latches, the next pixel, the colour-stack position or its row
start lost), some of them on the frame gate's games (`('screen', name,
pictures)`).

`--screens` is the frame gate (DESIGN 9 steps 4 and 5; SCREENS): the EXEC
without a cartridge (600 pictures) and with Astrosmash (its title screen,
700), Tower of Doom (700), Diner (300), Dig Dug (700), Sewer Sam (300)
and TRON Solar Sailer (700), as far as the MAME snapshots the model was
checked against (docs/STIC_NOTES.md 3). The bench runs with `+bushash=1`
(one hash a frame of its B and S lines instead of the lines) while the
model runs beside it; every picture, row fetch, card row and per-frame
bus hash must be equal.

Step 5 (MOBs and collisions, `intv_stic.sv`; docs/STIC_NOTES.md 6). The
model runs with its MOBs on (`STIC_MOBS = True`; `False` gives step 4's
backgrounds only). Pictures now include the MOBs, and the bench writes a K
line at every frame's end with the collision bits the frame gathered
(ORed into $18-$1F then), compared with the model's per frame; the CPU's
reads of $18-$1F are in the bus lines (or the per-frame hash). Two more
round trips on every image with MOBs: rt6 restores into a reset machine
inside the collision sweep (3 lines after the VBlank window), rt7 rewinds
to a state taken inside a line's MOB fetch (pixel clocks 196-203) on a
line covered by a MOB; for sticmob, rt8 restores into a reset machine at
the start of the sweep's pairs for the one line where two of its MOBs
overlap (`sweep_clock` gives the clk_sys); the R lines say where they
landed. Image
`sticmob` runs `sim/testroms/sticmob.asm` (46 frames: 22 scenes, two
passes), which checks its own collision reads against the hardware rules
(STICMOB_SELFCHECK: the model's run must end with 0 fails). `--all` adds
37 MOB plants (flips, sizes, YRES, position, X = 0, order, PRIO, pastel,
invisible drawn, M1, M2, M4, M5, background, INTR, border edges, pairs, the
sweep's range, the bits' clear and stickiness, the CPU's clear; state
port: sweep, sweep masks, line masks, gathered bits), and from the step-5
review 17 more: the background-collision area's edges (bottom line, right
column, left and top edges with border extension), YFLIP with YRES, the
sweep's first line and last row, pairs needing VISB or ignoring INTR, the
sweep ignoring its port turn, XFLIP with XSIZE, VDR or HDR ignored for
MOBs, the border test moved or not moved by HDR, MAME's PRIO-first order,
and the frame's end dropping a CPU write to $18-$1F (systest p11): 128
plants in all. `--screens` adds
the ten MOB games of docs/STIC_NOTES.md 5.4 (700 pictures each, MTE201
900).

Step 6 (the PSG, `intv_psg.sv`; docs/PSG_NOTES.md 5). The model's PSG
(`tools/psg.py`) steps with the system model's cycle count. The bench
writes an A line at every frame's end: a hash of every PSG step's three
levels in the frame (before the step: the 48 kHz filter's input) and a
hash of the 48 kHz samples the frame's steps ended; the driver compares
them with the model, steps in every run, samples in straight runs (the
filter is not state, so a round trip may move them), and frame by frame
in the frame gate. The dumps add the PSG's seven new state words (tone
counts and outputs, noise count and prescaler, LFSR, envelope count, step,
attack, holding, tick phase); the state port grows to 21 words. Image
`psgtest` runs `sim/testroms/psgtest.asm` (22 frames, two different
hand-controller bytes) with two more round trips in the middle of a slow
envelope: rt9 into a reset machine, rt10 over a later state. `--all` adds
18 PSG plants (LFSR tap, tone compare, envelope period, volume selects,
shape restart, alternate, tone-off bit, tick phase, write before the
step, filter reciprocal, one low pass, a DAC level; state port: tone,
noise, LFSR, envelope count, envelope step, tick phase) and keeps the
step-3 PSG ones (mask, registers lost, ports swapped) on `intv_psg.sv`.

The play bench (`tb_system.py --play`, step 6): Astrosmash (1,200
frames) and B-17 Bomber (1,300), each started with a key press and played
with scripted keys on both hand controllers (`PLAY`: keypad, side buttons
and disc directions, held from one MAME frame notifier to another). The
bench reads the keys as `+keys` (the bytes by frame, changing at the
frame's first cycle) and the model (`intv_system.press_pads`) applies the
same bytes by frame; every picture, row fetch, card row, collision bit,
per-frame bus hash and PSG hash must be equal, mode `stic`. With
`INTV_PLAY_ROOT` (one `tools/refs/mame_play.sh` OUTDIR per game) the
model in mode `mame` must also equal MAME given the same keys: every
10th frame's snapshot pixel for pixel (`stic_frames.py compare --press`)
and the PSG register log and step stream (`psg_compare.py --press`). The
last line is `TB_PLAY_ALL pass`.

`tb_input.py` writes about 541,000 vectors (`sim/work/tb_input/vectors.txt`)
and runs `tb_input.sv` (`intv_input.sv` alone) over them: the agreed
mapping written out row by row as the hand-controller inputs each Pocket
input must press, with MAME's `read_ctrl()` of those inputs as the expected
bytes; every combination of the 16 Pocket buttons in each keypad mode
(player 1 on the Pocket, player 2 docked); both sticks over their whole
range; every keyboard usage code in each report byte and random reports;
every slot type on each slot; random vectors; and the centres of MAME's
analog grid, expected as its table says. Both Swap settings throughout.
For all but the spec rows and the grid the expected bytes are the model's,
and the model must equal MAME's `read_ctrl()` on every vector. `--all`
then builds 15 planted faults (Swap ignored, a disc code, the dead zone's
edge, a sector slope, stick y flipped, L beating R, no cancel on the ring,
the face buttons' left and right swapped, Backspace, the keyboard on any
slot type, the keyboard's sixth byte, any slot type a controller, no R3,
the right stick in every mode, sticks on the Pocket); each must fail.
