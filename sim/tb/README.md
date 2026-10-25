# tb

Verilator testbenches, one per build step (DESIGN.md section 9). Outputs go
to `sim/work*`.

| Bench | Step | Run |
|---|---|---|
| `tb_timing.sv` | 1: timing, video port, timing state port | `sim/tb/run_tb_timing.sh --all` |
| `tb_loader.sv` | 2: loader, CRC table, page table, system ROMs, cart state port | `python3 -I sim/tb/tb_loader.py --all` |

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
restore). Images are taken from the owner's library by path and extracted
only into `sim/work` for the run. `--all` then builds eight planted faults
(CRC over the padded length, little-endian words, page table read one entry
off, odd last byte, default map not cut, SRAM sampled early, selects kept on
machine reset, selects dropped on restore); each must fail.
