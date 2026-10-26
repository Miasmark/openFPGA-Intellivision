# Cartridge formats (build step 8)

DESIGN.md 5.2-5.5 and 9 step 8, as built. What the core loads, how it maps
each format, what it refuses, and the tests. The Python model
`tools/mapper/cartfmt.py` is written the way the RTL works (the same state
machines, limits, order and error codes); the RTL is `intv_loader.sv` (with
`intv_cfgparse.sv` and `intv_romparse.sv`), `intv_cart.sv` and
`intv_pagesel.sv`. The benches hold the two equal on every bus address.

Specifications, read as specifications (no jzIntv code; MAME read for facts
only):

| Source | For |
|---|---|
| jzIntv `doc/programming/intellicart.txt` | the CFG sections `[mapping]` `[preload]` `[memattr]` `[bankswitch]` (BIN2ROM), the Intellicart memory model, the bank registers |
| jzIntv `doc/utilities/as1600.txt` | CFG `[vars]` names and values, `icart_attr` flags |
| jzIntv `doc/rom_fmt/id_tag.txt` | the .rom structure (`find_tags`), metadata tags, the compatibility tag $06 |
| Intellicart manual (research copy, `IntellicartManual.booklet.txt`) | CFG commands (whole-256-word rule, "superset" attributes), the download format, access table nibbles, fine-address table, CRC-16 |
| jzIntv `doc/tech/ecs.html` | ECS-style page selects: $xA5y written to $xFFF |
| as1600 outputs (the tool run as a program) | word-exact `[mapping]` lines, `PAGE` in hex, pages padded to 4K, the N bit 4 in the access nibble, compat tag bytes |
| MAME `src/devices/bus/intv/slot.cpp:225-290, 450` | MAME's .rom test (byte 0 $A8, byte 1 = ~byte 2) and loader (segments only, tables skipped); no BIN+CFG |

## 1 Data slots

| Slot | File | Use |
|---|---|---|
| 0x100 Cartridge | `.bin` `.int` `.itv` (raw) or `.rom` (Intellicart) | the image; a `.rom` is recognised by its first three bytes, whatever its name |
| 0x101 Cartridge CFG | `.cfg` | optional; used with a raw image only (ignored with a `.rom`) |

The Pocket reloads the core when either slot is loaded (parameters `0x109`),
and streams every slot that has a file. The loader reads the CFG slot's
length from the data table (as the cartridge's), so the bridge's pad bytes
are never parsed. A CFG slot the data table lists with size 0 means no CFG:
should the host ever reload a cartridge alone (no core reload), a CFG
streamed earlier is then not used; one still listed applies to the new
cartridge (tb_loader's reloads RELOAD2 and RELOAD3). The Pocket keeps the CFG slot's file selected until the
user changes it: a CFG chosen for one game stays with the next game loaded
unless it is cleared (owner check on hardware: how the menu clears an
optional slot).

## 2 BIN + CFG

### 2.1 Grammar (`intv_cfgparse.sv`, `cartfmt.CfgParser`)

- Lines end at LF; CR, tab and space are blanks; `;` starts a comment; a NUL
  byte ends the text (the rest is ignored).
- `[name]` at the start of a line selects a section; names compared in lower
  case; text after `]` ignored. Lines before the first section, in
  `[macro]` and in unknown sections are skipped.
- Numbers are hex, `$` optional, at most 20 bits (more: refused).
- `[mapping]`: `lo - hi = addr [PAGE p]` (file words lo..hi at CPU address
  addr; `PAGE` any case, then a blank and one hex page 0-F).
- `[preload]`: `lo - hi = addr` (Intellicart memory only, not readable).
- `[memattr]`: `lo - hi = RAM|WOM|ROM [8|16]` (width 16 when not given, as
  the Intellicart manual's example).
- `[bankswitch]`: `lo - hi`.
- `[vars]`: `name = decimal`; names case sensitive (as1600.txt). Used:
  `ecs` (1: ECS flag), `ecs_compat` (3: ECS, 0: ECS_OFF), `voice` (1),
  `voice_compat` (2, 3: VOICE), `jlp` / `jlp_accel` (not 0: JLP flag, for
  step 11), `lto_mapper` (not 0: refused). Everything else in `[vars]`,
  strings and malformed lines included, is ignored.
- Anything else in the four map sections refuses the CFG.

### 2.2 Mapping (word exact)

Each map line becomes a range (at most 32): `[mapping]` and `[preload]` give
CPU/Intellicart addresses lo..hi with the file offset of lo; `[memattr]` and
`[bankswitch]` give address ranges with attributes. The map table works in
256-word blocks (section 4); per block:

- the data ranges that touch it (a `[mapping]` line of the block's page, or
  a `[preload]` line on page 0): one range covering the block whole points
  the block into the file (no copy); a block with parts of ranges, gaps or
  more than one range is assembled at load into a pool block ($1E000, 32
  blocks): filled with $FFFF (what the bus reads when nothing answers), then
  each range's words copied in, in file order (a later line wins where two
  overlap);
- `[memattr]` adds R, W, N; `[bankswitch]` adds B and R (intellicart.txt:
  "also informs the Intellicart to respond to read accesses");
- a block with W and not B is RAM: it gets a block of the cart RAM area
  ($18000, 64 blocks), cleared, with any data ranges copied in (RAM with
  preloaded data); the save state holds that area.
- `[memattr]` ranges are word exact in the file but act on whole blocks: a
  3-word `RAM 8` line makes its 256-word block 8-bit RAM (the Intellicart
  itself works in 2K windows trimmed to 256-word blocks).
- Pages: a 4K range with any `PAGE` line is paged: a line without `PAGE` is
  page 0 there, visible only while page 0 is selected; ranges with no
  `PAGE` line answer on every page. `[memattr]` and `[bankswitch]` act on
  page 0.
- A mapping past the end of the file: those words are not answered.
- A CFG with no map lines (only `[vars]`): the CRC table's layout (or the
  default map) maps the image; the CFG's flags are added.
- Flags: the CFG's, plus the CRC table's ECS and VOICE when the image's CRC
  is in it, plus RAM, PAGED and the ECS conflict flags of the map
  (tools/mapper/README.md), as for the table's layouts.

### 2.3 Refused (the cartridge is not mapped; err[5], fmt_err)

| fmt_err | Cause |
|---|---|
| $10 | a line of `[mapping]` `[preload]` `[memattr]` `[bankswitch]` that does not parse |
| $11 | more than 32 ranges |
| $12 | lo > hi; a file offset or address past $FFFF; a number over 20 bits |
| $13 | `PAGE` on a `[preload]` line; a page past F |
| $14 | `[bankswitch]` and `PAGE` in one CFG (as1600 refuses them together too) |
| $15 | `lto_mapper` not 0: the LTO Flash mapper is not documented (DESIGN 13 item 11) |
| $16 | the data table's CFG length longer than the bytes that came, or 4 or more shorter |
| $18 | more than 64 blocks (16K cells) of cart RAM |
| $19 | more than 32 assembled blocks |

`[macro]`: the jzIntv documents give no syntax for it (the only example,
`examples/spacepat/dbgmac.cfg`, holds debugger watches `@W name addr`); the
patching use DESIGN 5.3 mentions comes from INTVPC-era files whose form is
not documented here. Skipped; a CFG that needs it maps without its patches.

## 3 Intellicart .rom

### 3.1 Structure (`intv_romparse.sv`, `cartfmt.RomParser`)

Bytes 0-2: $A8, n, ~n with n > 0 (the test MAME makes; a raw image that
starts so is taken for a .rom). Then n segments: lo, hi (256-word
Intellicart pages, hi >= lo), the words high byte first, CRC-16 (high byte
first) over lo, hi and the data. Then the tables: 16 bytes of access nibbles
(the 4K range's lower 2K in the low nibble; R 1, W 2, N 4 (jzIntv's narrow,
from as1600's output), B 8), 32 bytes of fine ranges `[0lll 0hhh]` (the
lower 2K windows first), CRC-16. Then metadata tags (id_tag.txt) until a NUL
tag or the end of the file: length (1-4 bytes), type, body, CRC-16; the
first compatibility tag ($06, at least 3 bytes) with a good CRC sets ECS
(requires), ECS_OFF (incompatible), VOICE (supports or requires) and JLP;
its LTOM bit refuses the image. Other tags, tags with a bad CRC and a
partial tag at the end are ignored. CRC-16: poly $1021, init $FFFF, MSB
first.

### 3.2 Mapping

Plane 1 of the SRAM is the Intellicart's 64K-word memory: each segment
word goes to its Intellicart address as it streams; every 256-word block no
segment wrote is cleared at the finish. Each 2K window takes its access
nibble, trimmed to its fine range; outside it nothing answers. A window
with W and not B is RAM: its blocks move to the cart RAM area (copied from
plane 1) so that the save state holds them; the window and any bank window
pointing at that Intellicart memory see the moved block. At most 64 such
blocks; more stay in plane 1 and the image has no save states.

### 3.3 Refused (fmt_err)

| fmt_err | Cause |
|---|---|
| $20 | a segment whose end is below its start |
| $21 | a segment's CRC-16 |
| $22 | the file ends before the tables and their CRC |
| $23 | the tables' CRC-16 |
| $24 | the compatibility tag asks for the LTO mapper |
| $25 | longer than 1 MiB |

## 4 The map table and the cartridge port (`intv_cart.sv`)

4,096 entries of 22 bits in block RAM, one per 256-word block of each of the
16 pages of each 4K range, index {r = addr[15:12], y, b = addr[11:8]} with
y = the range's page select if the range is paged, else 0:

| Bits | Field |
|---|---|
| 21 | S: the block has storage |
| 20 | R: reads answered |
| 19 | W: writes stored |
| 18 | N: 8-bit cells (reads give the upper byte 0, writes keep the low byte) |
| 17 | B: an Intellicart bank window |
| 16:0 | the SRAM word of the block's first word (an access is at base + addr[7:0]) |

The loader builds it from any format: a CRC-table layout (32 entries of 2K
words, tools/mapper/README.md) is expanded to it, so raw images map exactly
as in step 2 (all 188 library images give the same mapped-space CRC). A
bank window's access goes to Intellicart address ia = ((addr & $7FF) +
(bank << 8)) & $FFFF (intellicart.txt; the manual agrees; a historic note
in jzIntv's `doc/historic/intellicart/banksw.txt` says XOR, which the later
documents replace), whose storage is entry {ia[15:12], 0, ia[11:8]}'s. A word
in the image area (SRAM below $10000) at or past the image's length is not
answered ($10000 for a .rom).

Writes, wherever they go: $xA5y to $xFFF selects page y of range x
(`intv_pagesel.sv`, all 16 ranges; machine reset: page 0); $0040-$005F loads
Intellicart bank register addr[4:0] (the low byte; $0040 + r for the lower 2K
of range r, $0050 + r for the upper). An access is looked up with the selects
and registers as they were before it; its own select or register write lands
after it. The bank registers are 0 after a load and keep their values over a
machine reset (the Intellicart does not see the console's reset; its manual
calls them undefined at start: programs set them first).

An access through the table costs 2 clk_sys more than step 7's (3 through a
bank window), plus the SRAM's: about 8 of the 96 clk_sys a CPU bus cycle
leaves.

SRAM map (`intv_media.sv`): $00000 plane 1 (the image at file offsets, or a
.rom's Intellicart memory), $10000 ECS ROM, $13000 the save state's staging
area, $18000 cart RAM (64 blocks), $1C000 free (JLP RAM, step 11), $1E000
the pool (32 blocks).

### 4.1 For step 9 (the ECS)

`intv_pagesel` is the one page-select register file of the machine: the ECS
module reads its outputs (`pg_sel`, through `intv_media`) for its ROMs at
$2000 (page 1), $7000 (page 0) and $E000 (page 1) instead of decoding the
writes again; `pg_rst` gives the reset pages (DESIGN 20: the ROMs paged out
from reset for games that do not need the ECS). Step 9 must also decide who
answers when the cartridge and an ECS ROM both map the same page (WSMLB maps
$E000 itself and hands it over with $EA50), and add the ECS's state.

## 5 Save states (blob version 2)

`tools/savestate.py` VERSION 2 (step 7's was 1; a version 1 blob is refused).
The header's word 12 holds the CFG's CRC32 (0 without a CFG): a state made
with the same image and another CFG is refused, as one of another image.
The cartridge's module (id $0B) has 16 words: the load's results (read only;
a restore leaves them), the page selects (2 words) and the 32 bank registers
(8 words). The map table is not saved: the loader builds it again from the
same image and CFG, which the header's CRCs tie to the state. Cart RAM of
every format is in the 16K-cell area the blob holds.

No save states (saves and loads answer err, the machine untouched) for an
image whose writable storage the blob cannot hold: a bank window that
writes (its writes reach any Intellicart address), or a .rom with more than
64 blocks of RAM windows.

## 6 Error reporting

`err[5]` (intv_loader / intv_media) is set when a format is refused, with
`fmt_err` (sections 2.3, 3.3); the cartridge's slot status shows it as
wrong (the test pattern's slot card), as the step-2 length checks do.

## 7 Tests

| Gate | What |
|---|---|
| `python3 -I sim/testroms/step8/build_images.py` | the step-8 images from our sources (as1600 `cfgmap.asm`, `rombank.asm`, `rombankw.asm`; the CFG zoo `cfg/zoo*.cfg` with synthetic images; hand-made .rom files; the refusal set), each with the error code the model must give |
| `sim/tb/tb_loader.py --all` | every library image of the step-2 set and every step-8 image through the APF bridge: CRC, format, CFG CRC, flags, error, the 16 state words, the mapped space at reset (each word with its answer and window attributes), each 4K range at pages 1, 2, 3, 15, a write to every address (cart RAM, selects, bank registers), a machine reset, the state round trip; Python = RTL line by line; planted faults (below) |
| `sim/tb/tb_system.py` images `cartbank`, `cartcfg` | `sim/testroms/cart8test.asm` in the EXEC slot on `rombank.rom` and on `cfgmap.bin + .cfg`: bank register writes and the windows they map (Intellicart memory, the RAM, a wrap past $FFFF, a register of no window), RAM 16/8 bit, page selects in three ranges, an ISR that changes bank and page every frame; RTL = model on every bus cycle with the round trips; a self-check against the image's own words (`CART8_SELFCHECK`) |
| `sim/tb/tb_savestate.py` images `cartbank`, `cartcfg`, `cartnoss` | saves and loads with cart RAM in use and non-default pages and bank registers; a blob of another CFG refused (C); an image with a writing bank window: every save and load answers err |
| `tools/refs/mame_cart_dump.sh` + `tools/refs/cart_ref_compare.py` | MAME as a reference for .rom: at every address our map answers through a plain readable window onto loaded memory, MAME's CPU reads the same word (low byte in a narrow window) |

Planted faults (tb_loader): page off by one, 8-bit RAM read as 16 bits, CFG
`RAM 8` taken as 16-bit, a CFG section ignored (`[memattr]`, `[preload]`),
the bank registers $0050-$005F not decoded, a bank window using the lower
2K's register, the bank registers restored one word off, pool blocks not
filled, the .rom table CRC not checked, a .rom's unwritten blocks not
cleared, a fine range one block short, the CFG's last byte dropped, plus
step 2's, a CFG the table no longer lists applied to a reload, a kept CFG's
last bytes fed twice. tb_savestate: the CFG's CRC not checked, the bank registers not
restored, an image without save states saved.
