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
| jzIntv 20200712, run as a program (a black box; its code is not read) | the reference for what a CFG or .rom maps word by word (section 7, `JZ_REF`); where we differ on purpose: 2.4 |

## 1 Data slots

| Slot | File | Use |
|---|---|---|
| 0x100 Cartridge | `.bin` `.int` (raw), `.rom` (Intellicart) or `.luigi` (LTO Flash, 1.0.7) | the image; a `.rom` is recognised by its first three bytes, a LUIGI by its first four, whatever its name (an `.itv` loads under another of these names: the slot lists four extensions at most, and 1.0.7 gave `.itv`'s place to `.luigi`) |
| 0x101 Cartridge CFG | `.cfg` | found by the core: NAME.cfg beside NAME.bin; used with a raw image only (ignored with a `.rom`) |

The Pocket reloads the core when a cartridge is loaded (parameters `0x109`)
and streams it. Since build step 9b the user does not pick the CFG: the CFG
slot is a deferload slot (parameters `0x8`, not in the menu) and the core
finds the CFG by the cartridge's name (`apf_cfgfetch.sv`, started by
`apf_datatable.sv` after "all complete" for a new cartridge). It asks the
host for the cartridge's path (target command 0x0190), puts `cfg` in place
of its extension, opens that file into the CFG slot (0x0192: not found means
no CFG) and reads it (0x0180) to the slot's bridge address, so the loader
gets it exactly as a streamed slot; only then does the loader get the
lengths (len_valid). Its length: the data table's size for the slot if the
host puts one there after the open, else found by reading in chunks
(256 bytes, then 128 down to 4, then 3, 2, 1 at the end). The core keeps
`NAME.cfg` and `NAME.CFG` alike (FAT ignores case). The test pattern's
CFG second card shows the result. The loader cuts the CFG at that length,
so the bridge's pad bytes are never parsed; a fetch that finds nothing
gives "no CFG" (size 0), so a CFG of an earlier cartridge in the session is
not used (tb_loader's reloads RELOAD2 and RELOAD3: none, and the same file
under the second cartridge's name). An "all complete" with no new
cartridge does not fetch again.

## 2 BIN + CFG

### 2.1 Grammar (`intv_cfgparse.sv`, `cartfmt.CfgParser`)

- Lines end at LF; CR, tab and space are blanks; `;` starts a comment; a NUL
  byte ends the text (the rest is ignored).
- `[name]` at the start of a line selects a section; names compared in lower
  case; text after `]` ignored. Lines before the first section, in
  `[macro]` and in unknown sections are skipped.
- Numbers are hex, `$` optional, at most 20 bits (more: refused). (jzIntv
  wants the `$`; we also take bare hex, see 2.4.)
- `[mapping]`: `lo - hi = addr [PAGE p]` (file words lo..hi at CPU address
  addr; `PAGE` any case, then a blank and one hex page 0-F).
- `[preload]`: `lo - hi = addr` (Intellicart memory only, not readable).
- `[memattr]`: `lo - hi = RAM|WOM|ROM [8|16]` (width 16 when not given, as
  the Intellicart manual's example; jzIntv wants the width, see 2.4).
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
256-word blocks (section 4); per block and page:

- Pages: a 4K range that a `[mapping]` line with `PAGE` touches is paged.
  There, as in jzIntv, the lines without `PAGE` (`[mapping]` without it,
  `[preload]`, `[memattr]`, `[bankswitch]`) count on every page, and a
  `PAGE p` line on page p only. A range no `PAGE` line touches has page 0
  alone (it answers whatever page is selected).
- the data ranges that touch it (`[mapping]` and `[preload]` lines, as
  above): one range covering the block whole points the block into the
  file (no copy); a block with parts of ranges, gaps or more than one range
  is assembled at load into a pool block ($1E000, 32 blocks): filled with
  $FFFF (what the bus reads when nothing answers), then the words of the
  lines without `PAGE`, then those of the page's own `PAGE` lines (each in
  file order: a later line wins where two overlap). A page with no `PAGE`
  line in the block shares one block with the other such pages.
- `[memattr]` adds R, W, N; `[bankswitch]` adds B and R (intellicart.txt:
  "also informs the Intellicart to respond to read accesses");
- a block with W and not B is RAM: it gets a block of the cart RAM area
  ($18000, 64 blocks), cleared, with page 0's data ranges copied in (RAM with
  preloaded data); the save state holds that area. In a paged range the same
  RAM block answers on every page.
- Word exact: each block keeps the first and last word its ranges declare
  (the trim, section 4); the words of the block outside it are not answered
  and not written. `[memattr] $8040 - $8049 = RAM 16` (IntyBASIC `--cc3`
  writes this) answers at $8040-$8049 only, not in the STIC's alias at
  $8000-$803F nor at $804A-$80FF. Inside the trim, a gap between two ranges
  reads $FFFF from a ROM block and is a RAM cell in a RAM block.
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

### 2.4 Where we differ from jzIntv on purpose

jzIntv, run as a black box (`JZ_REF`, section 7), maps every CFG and .rom
of the test set as we do, word for word, outside these cases (each written
into `tools/refs/jz_cart_compare.py`, which checks that they still differ):

- A `PAGE` line and a line without `PAGE` on the same words: jzIntv answers
  with both (the bus ANDs them); we give the page's words (zoo7, $B000).
- `[memattr]` RAM in a paged range under a `PAGE` line: jzIntv answers with
  the RAM and the page's ROM together; we answer with the RAM alone, on
  every page, within its trim, and the page's words in that block are not
  seen (zoo7, $A800-$A9FF). A cartridge built this way would be unusual:
  one storage per block and page is what the map table holds.
- `[memattr] ROM` over words no line gives data: jzIntv reads $0000; we do
  not answer ($FFFF). A pool block's unfilled words in a `ROM 8` block:
  jzIntv $0000, we $00FF (zoo1).
- BIN + CFG banking: jzIntv's BIN+CFG loader ignores `[bankswitch]` and
  `[preload]` (zoo2's windows read $0000 there after bank writes); we follow
  intellicart.txt's BIN2ROM text for them.
- Syntax: jzIntv refuses numbers without `$` (`0800-0FFF=6000`) and `RAM`
  without a width (zoo1); we take both.
- .rom: jzIntv refuses a file whose tags end with a NUL tag (its error 7;
  id_tag.txt describes the NUL tag, so we take it: `romfine`; as1600 never
  writes one, `romfine_nonul` is that form) and a file with a tag whose CRC
  is bad (its error 8; we skip that tag: `rombadtag`).

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

4,096 entries of 38 bits in block RAM, one per 256-word block of each of the
16 pages of each 4K range, index {r = addr[15:12], y, b = addr[11:8]} with
y = the range's page select if the range is paged, else 0:

| Bits | Field |
|---|---|
| 37:30, 29:22 | the trim: first and last word of the block that answer (a CFG block: what its ranges declare; any other format: $00-$FF). Through a bank window, the storage block's trim |
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
after it. After a load each bank register points its 2K window at its own
address ($0040 + r = r << 4, $0050 + r = r << 4 | 8: a window reads the
Intellicart memory at its own address until the program sets it), as
jzIntv starts them (the Intellicart manual calls the start state undefined;
step 8's first build started them at 0); they keep their values over a
machine reset (the Intellicart does not see the console's reset).

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
WSMLB in step 8 (no ECS): its two $F000 pages map as the CRC table says
(tb_loader: every word at pages 0 and 1, mapped-space CRC 44A70D1A as
`sim/regress/mapper_library.csv`); booted with the real EXEC in the model
for 300 frames it writes $EA50 to $EFFF once and selects no $F000 page (it
waits for the ECS), so its $FA50/$FA51 flips are step 9's to see.

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
| `sim/tb/tb_loader.py --all` | every library image of the step-2 set and every step-8 image through the APF bridge: CRC, format, CFG CRC, flags, error, the 16 state words, the mapped space at reset (each word with its answer and window attributes), each 4K range at pages 1, 2, 3, 15, the bank sweep (K: all 32 bank registers at each 2K of the Intellicart memory in turn, every bank window read; it reaches a `[preload]` no CPU address maps at the start values), a write to every address (cart RAM, selects, bank registers), a machine reset, the state round trip; Python = RTL line by line; planted faults (below) |
| `sim/tb/tb_system.py` images `cartbank`, `cartcfg` | `sim/testroms/cart8test.asm` in the EXEC slot on `rombank.rom` and on `cfgmap.bin + .cfg`: bank register writes and the windows they map (Intellicart memory, the RAM, a wrap past $FFFF, a register of no window), RAM 16/8 bit, page selects in three ranges, an ISR that changes bank and page every frame; RTL = model on every bus cycle with the round trips; a self-check against the image's own words (`CART8_SELFCHECK`) |
| `sim/tb/tb_savestate.py` images `cartbank`, `cartcfg`, `cartnoss` | saves and loads with cart RAM in use and non-default pages and bank registers; a blob of another CFG refused (C); an image with a writing bank window: every save and load answers err |
| `tools/refs/mame_cart_dump.sh` + `tools/refs/cart_ref_compare.py` | MAME as a reference for .rom: at every address our map answers through a plain readable window onto loaded memory, MAME's CPU reads the same word (low byte in a narrow window) |
| `tools/refs/jzintv_cart_dump.sh` + `tools/refs/jz_cart_compare.py` (`JZ_REF`) | jzIntv as a black-box reference for BIN + CFG and .rom: for 18 cases (images, then page selects, bank register and RAM writes made through jzIntv's debugger) the model reads what jzIntv reads at every address outside the console's devices, except the differences of 2.4, each of which must still differ |

Planted faults (tb_loader): page off by one, 8-bit RAM read as 16 bits, CFG
`RAM 8` taken as 16-bit, a CFG section ignored (`[memattr]`, `[preload]`),
the bank registers $0050-$005F not decoded, a bank window using the lower
2K's register, the bank registers restored one word off, pool blocks not
filled, the .rom table CRC not checked, a .rom's unwritten blocks not
cleared, a fine range one block short, the CFG's last byte dropped, plus
step 2's, a CFG the table no longer lists applied to a reload, a kept CFG's
last bytes fed twice; after the step-8 review: a page select taken from
another range's value (`sel_no_range_match`: the bench's phase W writes
another range's $xA5y to $xFFF, and the range's own to $xFFE and $xF7F;
cart8test does the same), lines without `PAGE` on page 0 only, no trim, the
bank registers 0 after a load, a line without `PAGE` over a page's own
words, cart RAM in a paged range not shared by its pages. tb_savestate: the CFG's CRC not checked, the bank registers not
restored, an image without save states saved.

## 8 LTO Flash LUIGI (1.0.7)

The LTO Flash multicart's own format, used for many newer homebrews. Written from its
specification only: "Locutus Universal Intellivision Game Image (LUIGI) V1.0", J. Zbiciak, Left
Turn Only, 6-Jul-2019 (the LTO Flash download page). Model: `tools/mapper/luigi.py` (the format,
an encoder and a decoder, the spec's CRC test vectors and encoding example), `cartfmt.LuiParser`
and `build_lui`; RTL: `intv_luiparse.sv` and the loader's LUIGI states.

### 8.1 Structure

A file whose bytes 0-3 are "LTO" and version 0 or 1, whatever its name. Header: 16 bytes
(version 0) or 32 (version 1): feature flags (64 or 128 bits, little endian), in version 1 a
source UID, reserved bytes, and a DOWCRC over the rest as the last byte. Then blocks: type,
payload length (2 bytes), DOWCRC over those three bytes, CRC32/4 over the payload (4 bytes),
the payload. Block $01: the tables (1,280 bytes: the memory map, 256 x 16 bits, Locutus
address bits 23:8 per 256-word paragraph of the Intellivision map; the permissions, 256 x 8:
READ 1, WRITE 2, NARROW 4, BANKSW 8; the page flips, 256 x 16 per chapter (4K range) and page:
READ, WRITE, NARROW, PFE (page-flip enable) and the page's Locutus address bits 23:12). Block
$02: a data hunk (a 24-bit Locutus word address, then 8-bit, 10-bit and 16-bit packed blocks of
words). Block $03: metadata (skipped), other types skipped, $FF the end (what follows is
ignored; a file may also just end after a block). DOWCRC: poly $98, right shifting, init 0.
CRC32/4: poly $82F63B78, right shifting, init 0. The flags the core uses: voice_compat (bits
1:0), ecs_compat (3:2), jlp_accel (17:16), jlp_flash (31:22: 1.5 KiB sectors), lto_mapper (32).

### 8.2 Mapping

Locutus has a 512K-word RAM that the memory map points paragraphs into (19-bit addresses: the
upper bits of the map and of the page flips are ignored); the core has plane 1 (64K words):

- Data below Locutus $10000 goes to plane 1 at its own address: that is the Intellicart's
  memory, which bank windows reach (LUIGI keeps Intellicart memory at Locutus $00000-$0FFFF).
- Data above (jzIntv's tools put paged ROM at the top of Locutus RAM): each Locutus 4K page takes
  a free 4K page of plane 1 as its first word comes, the highest first. Free: no mapped paragraph
  or readable / writable page flip of the tables points there, no data below $10000 wrote there.
  With bankswitching, no page is free (any Intellicart address can be reached).
- With JLP, data at Locutus $10000-$11FFF (Locutus' JLP RAM) is dropped: the core's JLP has its
  own RAM.
- Every plane-1 word no data word wrote reads 0, as jzIntv reads a LUIGI's unwritten words (a
  64K-bit map of the written words, cleared at the finish).

The map table (section 4) from the tables, per 256-word paragraph: page 0 from the memory map and
permissions (the state at reset: Locutus copies its initial tables at every reset, and the
Mattel scheme selects page 0), pages 1-15 of a range with page flipping (any PFE in its
chapter) from the page flips, except $4000-$47FF, which a flip leaves alone (the spec: the ECS
RAM). READ, WRITE and BANKSW (the half-page's first paragraph's, as Locutus looks it up) as the
entry's R, W, B; NARROW only with WRITE (the spec: ignored without WRITE, and a read gives all
16 bits; the core's N makes reads of 8-bit RAM give 0 in the upper byte: the one difference,
for 8-bit RAM preloaded with upper bytes). No reads at $0000-$04FF, $1000-$1FFF, $3000-$3FFF
(the spec: Locutus ignores them). A WRITE paragraph without B is RAM: a block of the cart RAM area
(saved in the state), copied from its Locutus address (or cleared, if no data came there); a
paragraph pointing above $10000 where no data came: RAM as above, ROM not answered. Bank
registers, page selects, save states and the "no save states" rules as for a .rom (section 3.2,
5). The format is reported as `.rom` with layout $FD.

Flags: ecs_compat 11 (requires) ECS, 00 (incompatible) ECS_OFF; voice_compat 10 (enhanced) or 11
(requires) VOICE; jlp_accel non-zero JLP, its mode and jlp_flash's sectors (at most 16, the
core's flash store); plus RAM, PAGED and the ECS conflicts of the map.

Where Locutus differs and the core does not follow: Locutus reloads its bankswitch state at a
console reset (the core keeps the Intellicart's behaviour, as for a .rom: the registers keep
their values); a bankswitched image whose map points a paragraph elsewhere than its own address
is refused (below).

### 8.3 Refused (fmt_err)

| fmt_err | Cause |
|---|---|
| $28 | the header's DOWCRC |
| $29 | a block header's DOWCRC |
| $2A | a block payload's CRC32/4 |
| $2B | an encrypted file (block $00) |
| $2C | the tables block missing, twice, or not 1,280 bytes |
| $2D | a data hunk before the tables |
| $2E | a data hunk's packing (a reserved start byte, a block that runs past the payload) |
| $2F | the file ends inside the header or a block |
| $30 | lto_mapper (the LTO Flash mapper is not documented) |
| $31 | data above Locutus $10000 with no free 4K page of plane 1, or with bankswitching |
| $32 | data below $10000 on a plane-1 page already given to data above it |
| $33 | bankswitching with a mapped paragraph not at its own Locutus address |
| $25 | longer than 1 MiB |

### 8.4 Tests

- `python3 -I tools/mapper/luigi.py`: the spec's test vectors for both CRCs (and IEEE CRC32's),
  the spec's encoding example decoded to its listing, encode -> decode, flipped bits caught
  (LUIGI_SELFTEST).
- `sim/testroms/step8/build_images.py`: `lui_paged` (page flips with pages above $10000, partial
  paragraphs, RAM 16 and 8, $4800's flipped half, metadata and an unknown block, junk after the
  end mark), `lui_bank` (version 0, bank windows, B without R, NARROW without WRITE, preloads, no
  end mark), `lui_jlp` (flags, a JLP RAM preload dropped, unwritten pages above $10000) and one
  file per refusal. `tb_loader` runs them all: RTL = model on every bus address, plus planted
  faults.
- `tools/refs/jz_luigi_ref.sh` (`JZ_LUIGI`): jzIntv's bin2luigi / rom2luigi make LUIGI files from
  the step-8 images, luigi2bin turns them back into BIN + CFG, jzIntv dumps its space for every
  JZ_REF case's writes; the model on the LUIGI must read the same (all three tools and jzIntv run
  as programs; their code is not read). Where we differ on purpose (`jz_luigi_compare.py`
  KEEP, each must still differ): a bankswitched paragraph without READ answers nothing (the
  spec; luigi2bin's `[bankswitch]` line makes it readable), and a bank window moved onto other
  Intellicart memory (jzIntv reads 0 there through luigi2bin's BIN + CFG; on the original .rom it
  reads the memory, as we do).
