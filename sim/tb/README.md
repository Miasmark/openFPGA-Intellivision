# tb

Verilator testbenches, one per build step (DESIGN.md section 9). Outputs go
to `sim/work*`.

| Bench | Step | Run |
|---|---|---|
| `tb_timing.sv` | 1: timing, video port, timing state port | `sim/tb/run_tb_timing.sh --all` |
| `tb_loader.sv` | 2: loader, CRC table, page table, system ROMs, cart state port | `python3 -I sim/tb/tb_loader.py --all` |
| `tb_cpu.sv` | 3: the CP1610 RTL in lockstep with the Python model | `sim/tb/run_tb_cpu.sh --all` |
| `tb_system.sv` | 3: the machine (CPU, bus fabric, RAMs, STIC/PSG stubs) with timing and loader, against the system model | `python3 -I sim/tb/tb_system.py --all` |

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
cartridge (the 0x0082 size used). Images are taken from the owner's library
by path and extracted only into `sim/work` for the run; the `forced:` rows
come from `tools/synth_image.py` (a table CRC, no game data). `--all` then
builds 13 planted faults (CRC over the padded length, little-endian words,
page table read one entry off, odd last byte, default map not cut, SRAM
sampled early, selects kept on machine reset, selects dropped on restore, no
size check, no length cross-check, no fallback to the 0x0082 size, the
0x0082 size of any slot, the finish rerun on every "all complete"); each
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

`tb_system.py` runs `tb_system.sv`: `intv_machine` with the real
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
slots (3788-3791 and INTRM's last sample). Four runs per image: straight,
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
