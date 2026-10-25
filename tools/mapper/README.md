# mapper

Cartridge mapper model and the CRC map table generator (build step 0,
DESIGN.md 5.2 and 9). Our own code (MIT), Python 3 standard library only.
Run every script with `python3 -I`.

| File | What it does |
|---|---|
| `../gen_crc_table.py` | builds the CRC table and the layout page tables from `data/` |
| `../intv_mapper.py` | the mapper model: what the core presents for an image; checks a library |
| `intvcart.py` | shared code: layouts, page entries, CRC32 combine, MAME list reader, the model |
| `import_name_list.py` | extracts the ECS/Intellivoice flags from jzIntv `name_list.c` (public domain) |
| `selftest.py` | self-test without game data; also checks the tables are up to date |

```
python3 -I tools/gen_crc_table.py            # regenerate (after editing data/)
python3 -I tools/gen_crc_table.py --check    # fail if a generated file is stale
python3 -I tools/mapper/selftest.py
python3 -I tools/intv_mapper.py map IMAGE    # IMAGE: .int/.bin, or a .zip holding one
python3 -I tools/intv_mapper.py read IMAGE 5000 16
python3 -I tools/intv_mapper.py evidence IMAGE "5000:2000" "5000:1000 D000:1000"
python3 -I tools/intv_mapper.py check DIR --out sim/regress/mapper_library.csv
```

Images are read in place and never copied. `dump` writes a file derived from
a game: keep it outside the repository.

## Inputs (`data/`)

| File | Source | Used for |
|---|---|---|
| `mame-hash/intv.xml`, `intvecs.xml` | MAME (CC0-1.0, copied verbatim) | load address and CRC of every ROM part; slot type (cart RAM, WSMLB paging); usage (ECS, Intellivoice) |
| `cart_extra.csv` | ours, hand-written from measurements | images MAME's lists do not give; each row says how it is placed |
| `jzintv_name_flags.csv` | jzIntv `name_list.c` (public domain), flagged rows only | ECS and Intellivoice flags, OR-ed into the table |

Rules the generator applies to MAME's lists, all from MAME's own loader
(`src/devices/bus/intv/slot.cpp:387-425`, `src/mame/mattel/intv_m.cpp:600-605`):

- A dataarea's name is its load address; the image is the ROM parts in list
  order, two bytes per word, high byte first. The image CRC32 is the parts'
  CRCs combined (`crc32_combine`), so no image is needed to build the table.
- A dataarea larger than its parts is $FF filler in MAME, which reads like
  unmapped space; only the parts are mapped (Checkers, Minehunter alt,
  Tag-Along Todd).
- `intv_ram`: 8-bit RAM at $D000-$D7FF, as many cells as the `ram` dataarea
  (1K cells are mirrored in the 2K window, as MAME masks the index,
  `rom.h:52-53`). `intv_gfact`: 8-bit RAM at $8800-$8FFF.
- `intv_wsmlb`: the $F000 dataarea holds two 4K-word pages
  (`ecs.cpp:200-245`).
- Skipped: the ECS itself (a system ROM with its own slot), the Intellivoice
  entry (no ROM), and `quest` (a dataarea named `0000`, which MAME does not
  load). The `kingotmf` entry (unsupported, "TODO: Investigate these files")
  is kept as MAME loads it, $D000-$F0FF.

## Output formats

**CRC table** `src/fpga/core/tables/cart_crc.{mif,hex}`: 256 entries x 64 bits,
sorted by CRC, zero entries after the last one (layout 0 = no entry). 246 used.

| Bits | Field |
|---|---|
| 63:32 | CRC32 of the image file (zlib CRC32, what the loader computes while streaming) |
| 31:24 | layout id |
| 23:16 | flags |
| 15:0 | image size in 256-word units, rounded up (0 = do not check) |

| Flag | Name | Set when |
|---|---|---|
| 0x01 | ECS | listed in `intvecs.xml`, usage says ECS, or `name_list.c` says ECS |
| 0x02 | VOICE | usage says Intellivoice, or `name_list.c` says Voice |
| 0x04 | RAM | the layout has cartridge RAM |
| 0x08 | PAGED | the layout has ECS-style pages |
| 0x10 | JLP | reserved: no table source marks JLP (CFG only, step 8/11) |
| 0x20 | ECS_OFF | not an ECS title, and cartridge ROM or RAM sits where the ECS maps its own: ROM $2000-$2FFF, $7000-$7FFF, $E000-$EFFF, RAM $4000-$47FF (jzIntv `doc/tech/ecs.html`; MAME `intv_m.cpp:616-622`) |
| 0x40 | ESTIMATED | the layout is ours (`cart_extra.csv`), or only `name_list.c` knows the CRC |

**Layouts** `src/fpga/core/tables/cart_layouts.{mif,hex}`: 32 page entries of
16 bits per layout, one per 2K-word page; address = layout id x 32 + (CPU
address >> 11). 29 layouts: 0 = none, 1 = default map, 2-28 from the table.
`data/layouts.json` lists the same with segments and title counts.

| Bits | Field |
|---|---|
| 15:14 | kind: 0 none, 1 ROM, 2 RAM 16-bit, 3 RAM 8-bit |
| 13 | ECS-style paged 4K range: page y is at offset + 2y |
| 12:9 | number of pages - 1 |
| 8:0 | ROM: offset in the image, 2K-word units (up to 1M words). RAM: [8:6] size code, cells = 2048 >> code, mirrored in the page; [5:0] offset in the cartridge RAM area, 2K-cell units |

A ROM read past the end of the image is not answered (the bus reads $FFFF).
The page table is coarse on purpose (2K words, as every MAME layout is); the
RTL may expand it into a finer table at load time for CFG and `.rom` files,
whose ranges can be 256-word aligned.

**Default map (layout 1).** An unknown CRC gets this map, cut at the image
length. Pages are filled in this order: Cart.mac's 16K map first ($5000-$6FFF,
$D000-$DFFF, $F000-$FFFF; wiki `Cart.mac`), then $9000-$BFFF, $C000-$CFFF,
$E000-$EFFF, $8000-$8FFF, $4800-$4FFF, $2000-$2FFF, $7000-$7FFF (ROM-safe
ranges per wiki `Memory_Map` and MAME `slot.cpp:27-42`). Unknown images are
more likely homebrew than Mattel originals (MAME has those), so the documented
homebrew map comes first. For the owner's 162 proven images the default map
gives the right layout for 129. No jzIntv heuristics are used.

## The mapper model

`CartModel` is the cartridge side of the bus, built from the image and the 32
page entries, exactly as the RTL will hold them. `intv_mapper.py` reads the
`.hex` files the RTL loads, looks the CRC up linearly as the loader may, and
answers reads through the page table.

- ECS-style paging: writing $xA5y to $xFFF selects page y of the 4K range
  $x000 (jzIntv `doc/tech/ecs.html`); all ranges reset to page 0. A paged
  range answers only on pages it has. A plain ROM range answers on every page:
  when the ECS is attached, the ECS module decides who drives $2000, $7000 and
  $E000 (build step 9). This model is the cartridge alone.
- 8-bit cart RAM returns the low byte with the upper byte 0 (MAME `rom.h:52-53`;
  ECS RAM per `ecs.html`).
- Not yet: the CFG parser, the Intellicart `.rom` parser and its bank
  registers at $0040-$005F (build step 8), JLP (step 11).

**Mapped-space CRC.** CRC32 over the 65,536-word space at reset paging,
big-endian, ROM words as read and $FFFF for RAM and unmapped addresses; then,
for each paged 4K range in address order, its pages 1..n-1 (4K words each).
The RTL check computes the same by reading the address space through the cart
module. `sim/regress/mapper_library.csv` records it for every image of the
owner's library.

## The owner's library (188 images, checked 2026-10-25)

`python3 -I tools/intv_mapper.py check ~/ROMLibrary/Intellivision` (by path):

| Status | Images | Meaning |
|---|---|---|
| proven | 162 | every MAME part CRC matches when the image is cut in list order, and the total size matches |
| derived-prefix | 6 | MAME's parts match the start of the image; the rest is not mapped |
| derived-sibling | 16 | no list has this exact image; >= 99 % equal word for word (every segment) to a proven image of the same size, whose map is used |
| derived-hsi | 2 | only MAME `intv.hsi` knows the CRC (map from its extrainfo, or the default 4K at $5000); jump targets agree |
| derived-jumps | 2 | no list entry and no sibling; the map with the best jump-target evidence |

Every image maps; for each, the page table was checked against the layout's
own segments word for word. The check fails on any mismatch (tested by
corrupting one page entry: 13 images failed).

What each of the 26 unproven images is missing:

| Image | Map | Missing |
|---|---|---|
| Advanced Dungeons & Dragons | $5000-$67FF | MAME `add` covers 6K words; the last 2K words of the image (79 % one value) are not in any list. The image is 99.9 % equal to `adventur`, which maps all 8K |
| Demonstration Cartridge - Blue | $5000-$67FF | as above (`demoblue`; last 2K words 83 % one value) |
| Royal Dealer | $5000-$67FF | as above (`rdealer`; 80 % one value) |
| Lock 'N' Chase | $5000-$67FF | MAME `lnc` covers 6K words; the last 2K words are all zero. Nothing really missing |
| MTE201 Test Cartridge | $5000-$5FFF $7000-$7FFF | both MAME `mte201` regions match; only a trailing $0000 word is extra. Nothing really missing |
| Triple Challenge | $5000-$6FFF $9000-$AFFF, RAM $D000 | MAME `trchalng` covers the first 0x8000 bytes; 0x3002 more bytes (88 % one value) are not in any list. If they were mapped at $B000, 24 more jump targets would land; unproven |
| BattleTanks, Biplanes, Racing Cars | $5000-$5FFF | sibling `traction` (99.2 %) |
| Buzz Bombers (Alt 1) | $5000-$6FFF | sibling `buzbombr` (99.5 %) |
| Crosswords, Word Hunt, Word Rockets | $5000-$6FFF | sibling `lfun2` (99.7-99.8 %) |
| Factor Fun, Math Master | $5000-$6FFF | sibling `lfun1` (99.7-99.8 %) |
| Memory Fun | $5000-$6FFF | sibling `lfun2` (99.8 %) |
| Magic Carousel (Alt 1) | $5000-$6FFF $D000-$EFFF | sibling `magic` (99.8 %, 100 %) |
| Number Jumble (Alt 1) | $5000-$6FFF $D000-$DFFF $F000-$FFFF | sibling `jumble` (100 %, 99.7 %, 100 %) |
| Party Line - Space Cadet (Alt 1) | $5000-$6FFF | sibling `spacecad` (99.8 %) |
| Thin Ice | $5000-$6FFF | sibling `thinicep` (99.7 %) |
| Vectron (Alt 1) | $5000-$6FFF $D000-$DFFF | sibling `vectron` (99.4 %, 100 %) |
| World Championship Baseball | $5000-$6FFF $D000-$DFFF | sibling `allstar` (All-Star Major League Baseball beta; 99.8 %, 100 %) |
| Deadly Dogs (Beta) | $5000-$5FFF | only `intv.hsi` (no extrainfo = MAME's default 4K at $5000, `slot.cpp:308`); jump targets 61 in ROM / 23 outside, against 2 / 82 at $6000 |
| Mr. BASIC Meets Bits 'N Bytes | $5000-$6FFF $D000-$DFFF, ECS | only `intv.hsi` extrainfo (and `name_list.c` for ECS); no MAME region matches this dump; jump targets 249 / 56, best of five maps |
| Party Line - Blow Out (Proto) | $5000-$5FFF $D000-$DFFF | no source at all; jump targets 95 / 15, against 15 / 95 for $5000-$6FFF |
| Super NFL Football (Proto) | $5000-$6FFF $9000-$AFFF $D000-$DFFF $F000-$FFFF | no source at all; Tower of Doom's map; jump targets 918 in ROM / 7 on filler / 71 outside, against 895 / 30 / 71 for the default order |

To prove these: an owner check on hardware or in MAME/jzIntv as black boxes
(does it boot and play past the title), or a `.cfg` from the owner.

**Jump-target evidence** (`intv_mapper.py evidence`, `intvcart.jump_evidence`):
every J/JSR pattern ($0004 + two words, encoding from the wiki `Jump` page) is
decoded and its target at $4000 and up is classed as cartridge ROM, filler
(a 2K block >= 90 % one value) or outside the candidate map. Ten-bit data often
looks like a jump, so this is a statistic: on the 162 proven images the true
map scores best (fewest outside + filler) against every other proven map of
the same size in 144 cases, ties in 5 and loses in 13, mostly to a larger map.

**Corrections to the test-assets lane (2026-10-24):**

- MTE201: both MAME regions match; the lane's "second region differs" is wrong.
- Crosswords, Word Hunt, Word Rockets and World Championship Baseball are
  siblings of proven images, not size-only estimates.
- Party Line - Blow Out is most likely $5000-$5FFF + $D000-$DFFF, not
  $5000-$6FFF.
- Congo Bongo, Defender and both Pac-Man images have ROM at $7000-$7FFF
  ($5000-$7FFF), so they need the ECS off too; the lane's list missed them.
- Flags: `name_list.c` adds Intellivoice to `sshuttle` (Space Shuttle); MAME
  marks Number Jumble ECS where `name_list.c` does not. Both are OR-ed.
