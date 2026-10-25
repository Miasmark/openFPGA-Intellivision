# Developing the Intellivision core

How to build, simulate, check and package the core. The plan is
[DESIGN.md](DESIGN.md); section 9 is the build order.

## Layout

| Path | What |
|---|---|
| `src/fpga/ap_core.qpf`, `ap_core.qsf` | Quartus project: Analogue's template settings and pins (as openFPGA-7800 has them), then this core's seed and file lists |
| `src/fpga/apf/` | Analogue's APF framework, unmodified |
| `src/fpga/core/core_top.v` | APF top level: bridge map, settings, data table, host commands, loader, clocks, wiring |
| `src/fpga/core/core_bridge_cmd.v` | Analogue's host/target command handler, unmodified |
| `src/fpga/core/pll/` | the PLL, generated (below) |
| `src/fpga/core/intv_timing.sv` | master timing: the clock enables, pixel / line / frame counters, state port |
| `src/fpga/core/pocket_video.sv` | video windows (scaler modes) and the Pocket's video port |
| `src/fpga/core/intv_palette.sv` | the 16 STIC colours (MAME's values, BSD-3 notice in THIRD_PARTY_NOTICES.md) |
| `src/fpga/core/test_pattern.sv`, `slot_stub.sv` | step 1 stand-ins for the STIC and the loaders |
| `src/fpga/pocket_utils/` | agg23's data loader and I2S output (MIT), unmodified |
| `dist/` | the SD card layout: `Cores/Miasmark.Intellivision/`, `Platforms/intv.json`, `Assets/intv/common/` |
| `sim/tb/` | Verilator benches, one per build step |
| `sim/check/` | repository checks: `hygiene.sh`, `apf_json_check.py` |
| `tools/` | `package.sh`, `reverse_bits.py`; the Python models of step 0 |

## Clocks

One PLL from the 74.25 MHz `clk_74a` (DESIGN.md 2.3, NTSC):

| Output | Divider | Frequency | Use |
|---|---|---|---|
| `clk_sys` | 20 | 42.954545 MHz = 12 x 3.579545 MHz | all machine logic, with clock enables |
| `clk_mem` | 10 | 85.909091 MHz | memories (from step 2) |
| `clk_vid` | 240 | 3.579545 MHz | the pixel clock |
| `clk_vid_90` | 240, 90 degrees | 3.579545 MHz | the scaler's sample clock |

VCO = 74.25 x (11 + 2449196227 / 2^32) = 859.0909091 MHz. All four share
the VCO and their rising edges, so `core_constraints.sdc` puts them in one
synchronous group. `intv_timing` makes the enables from `clk_sys`: pixel
every 12, PSG every 24, CPU microcycle every 48, locked to the pixel counter
(228 pixel clocks = 57 CPU cycles a line, 262 lines, 59.92275 Hz).

PAL (4.000 MHz master, VCO 960 MHz, integer M = 12 instead of 11) needs a
runtime retune of M and K; it is step 12 (DESIGN.md decision 5).

### Regenerate the PLL

`src/fpga/core/pll/pll_core.v` is the tool's output with a header comment
added above it; don't edit the parameters by hand. From the repository
root (the output directory is outside git). ip-generate runs Java, which the
image only lets root start, so the container runs as root and gives the
files back to you at the end:

```sh
mkdir -p sim/work/pll
docker run --rm -e OWNER="$(id -u):$(id -g)" -v "$PWD/sim/work/pll:/out" raetro/quartus:21.1 bash -c 'cd /out &&
 ip-generate --remove-qsys-generate-warning --project-directory=/out --output-directory=/out/pll_core \
  --file-set=QUARTUS_SYNTH --component-name=altera_pll --output-name=pll_core \
  --system-info=DEVICE_FAMILY="Cyclone V" --system-info=DEVICE=5CEBA4F23C8 --system-info=DEVICE_SPEEDGRADE=8_H6 \
  --component-parameter=gui_device_speed_grade=8 --component-parameter=gui_pll_mode="Fractional-N PLL" \
  --component-parameter=gui_reference_clock_frequency=74.25 --component-parameter=gui_operation_mode=direct \
  --component-parameter=gui_fractional_cout=32 --component-parameter=gui_dsm_out_sel=1st_order \
  --component-parameter=gui_en_reconf=false --component-parameter=gui_number_of_clocks=4 \
  --component-parameter=gui_output_clock_frequency0=42.954545 --component-parameter=gui_output_clock_frequency1=85.909091 \
  --component-parameter=gui_output_clock_frequency2=3.579545 --component-parameter=gui_output_clock_frequency3=3.579545 \
  --component-parameter=gui_ps_units3=degrees --component-parameter=gui_phase_shift_deg3=90.0 \
  --component-parameter=gui_en_adv_params=true \
  --component-parameter=gui_multiply_factor=11 --component-parameter=gui_frac_multiply_factor=2449196227 \
  --component-parameter=gui_divide_factor_n=1 --component-parameter=gui_divide_factor_c0=20 \
  --component-parameter=gui_divide_factor_c1=10 --component-parameter=gui_divide_factor_c2=240 \
  --component-parameter=gui_divide_factor_c3=240 \
  --component-parameter=gui_pll_auto_reset=Off; rc=$?; chown -R "$OWNER" /out; exit $rc'
```

Then compare `sim/work/pll/pll_core/pll_core.v` with the tree's file below its header
comment; they must be identical. `pll_core.qip` is kept by hand (the
instance assignments openFPGA-7800 uses, without its reconfiguration files).
On the owner's VM, run any Quartus tool under the shared Quartus lock
(openFPGA-7800's docs/ENVIRONMENT.md: one Quartus job at a time).

## Build

```sh
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/build" -w /build/src/fpga \
  raetro/quartus:21.1 quartus_sh --flow compile ap_core
tools/package.sh          # release/M_Intellivision_Pocket_<version>.zip
```

`apf/build_id.mif` is written by the pre-flow script on every build and is
not tracked. After every build check `src/fpga/output_files/ap_core.sta.summary`:
every setup and hold slack must be positive. A clock name you don't
recognise there means `core_constraints.sdc` no longer matches the PLL's
clock names (`ic|pll|altera_pll_i|cyclonev_pll|counter[n].output_counter|divclk`).

The first fit of step 1 (seed 1): 656 ALMs of 18,480, 3 M10K, 1 DSP;
worst setup +3.537 ns (`clk_74a`), `clk_sys` +12.999 ns, `clk_vid`
+15.690 ns (the `clk_sys` -> `clk_vid` crossing), worst hold +0.139 ns
(`clk_74a`, fast 0 C model).
With the free-running raster (seed 1): 705 ALMs, 3 M10K, 1 DSP; worst
setup +2.840 ns (`clk_74a`), `clk_sys` +13.264 ns, `clk_vid` +15.011 ns,
worst hold +0.120 ns (`clk_74a`, fast 0 C model).

## Simulation

```sh
VERILATOR=/opt/verilator-5.040/bin/verilator ~/daria_work/bin/simslot sim/tb/run_tb_timing.sh --all
```

`tb_timing` (step 1) runs `intv_timing`, `test_pattern` and `pocket_video`
with `clk_sys` and `clk_vid` as the PLL makes them. It checks, per frame:
228 x 262 pixel clocks, 14,934 CPU and 29,868 PSG enables at fixed pixel
phases, 59.92275 Hz between the Pocket's VS pulses, 262 HS pulses, HS to HS
always 228 pixel clocks and DE always at the same distance after HS, the
active window of each scaler mode (160 x 192, 167 x 210), the slot index
after each line, the test pattern's pixels, and the state port. The machine
is frozen 40 lines from mid-frame and 300 lines from VBlank, restored to
another position, and a saved word is restored into a second instance whose
raster is at another phase: the raster (and so HS / VS / DE) runs on
unchanged throughout, the picture is black while the machine is frozen,
the machine resumes on exactly its saved clk_sys and loses whole frames
only, and the restored copy replays the same machine enables for a frame.
`--all` runs both scaler modes at three `clk_vid` phases and then six
planted faults (263 lines, a wrong palette entry, a state word that loses
a counter, the raster stopped by the freeze, the machine resuming at once
instead of at its position, no blanking while frozen), each of which must
fail.

## Checks

```sh
python3 sim/check/apf_json_check.py
sim/check/hygiene.sh --names <list outside the repo> --data <BIOS folder> --data <ROM folder>
```

`apf_json_check.py` holds every `dist/` file to Analogue's documented
limits and to the RTL that answers it (slot addresses and ids, the data
table, menu addresses and defaults, scaler modes against `pocket_video`'s
windows and the pixel aspect). Run both before each commit.

## Pocket (APF) notes

- **Data slots** (DESIGN.md 5.6): bridge addresses `0x0N000000`, N = the
  slot's number (bits 27:24 reach `slot_stub` through the loader). EXEC,
  GROM, ECS and Intellivoice ROMs load at start from `/Assets/intv/common/`
  (parameters `0x88`); cartridge and CFG are reloadable with a core reload
  (`0x109`); JLP flash is one nonvolatile file per game (`0x84`), reported
  as 0 bytes until step 11.
- **Save states**: the blob address is `0x50000000` (DESIGN.md 4.1); the
  core answers "not supported" until step 7.
- **Menu**: Reset (`0x200`) and Border (`0x204`: show = scaler slot 1,
  167 x 210; hide = slot 0, 160 x 192).
- **Power-up values** go on internal declarations, never on output ports
  (openFPGA-7800's DEVELOPING.md explains why).
