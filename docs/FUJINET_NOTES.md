# FujiNet: scoping notes

Whether this core could talk to a FujiNet over the Pocket's link port or
cartridge slot, as the 7800 core (openFPGA-7800) is being made to.

**Status (2026-11-19): a note only. Nothing is built, and nothing will be
until the 7800 core's FujiNet support is shown to work on a Pocket.** The
7800 work it would follow: openFPGA-7800 `docs/FUJINET_POCKET_DEVICE.md`
(the device), `docs/FUJINET_TESTING.md` (the bring-up), and
`docs/FUJINET_GAME_LOADING.md` (booting games the FujiNet pushes). There,
on 2026-11-19, the link had been proven on a Pocket with fujinet-pc through
an FT232H, and game loading passed in simulation, its fits under way.

## 1. The short answer

Yes. FujiNet already has an Intellivision personality (fujinet-firmware
`build-platforms/platformio-fujiversal-intv.ini`, `pico/intellivision/`)
built the same way as its 7800 one: a cartridge that serves a mailbox in the
console's address space and speaks FujiBus to an ESP32-S3 running the
generic RS232 build. On the Pocket the core is the cartridge, as on the
7800, so the same FujiNet device, the same pins and the same protocol would
serve both cores; the console identity lives entirely in the core.

## 2. What carries over from the 7800 core unchanged

- **The device:** an ESP32-S3 with fujinet-firmware's RS232 build, on
  cartridge pins 5 (TX) and 31 (RX), or link port SO and SI, 115,200 baud
  8N1, 3.3 V, powered by itself (openFPGA-7800
  `docs/FUJINET_POCKET_DEVICE.md` applies as written). For bench work:
  fujinet-pc's RS232 build on a USB serial adapter.
- **The protocol:** FujiBus packets in SLIP frames, one request and one
  reply; the status codes are the same enum in both firmware ports
  (`fujibus.h`: OK, no link, timeout, bad frame, too big).
- **In the core:** openFPGA-7800's `fujinet_uart.sv`, and from
  `fujinet_mailbox.sv` the frame builder and parser, the two-port line
  watch and lock, the "no link" rule and the push receiver; the staging and
  replay of `fujinet_stage.sv`, `fujinet_rd.sv` and `fujinet_loader.sv` in
  spirit, with a different memory under them (section 3.4).
- **The game push:** NET_OPEN $4F, NET_WRITE $57 (512-byte blocks) and
  NET_CLOSE $43 to device $FF, each answered, while the program's
  MOUNT_IMAGE is outstanding.

## 3. What differs

### 3.1 The mailbox

Plain RAM cells at `$9C00-$9F3F` (fujinet-firmware
`pico/intellivision/firmware/include/fuji_mailbox.h`): 832 cells, each
read and written as a byte (the console's writes are 8 bits wide there).

| Cells | Contents |
|---|---|
| `$9C00-$9C02` | 'F', 'N', protocol 1 (the cartridge writes them; CONFIG waits for them at power-on) |
| `$9C03` / `$9C04` | SEQ (the console bumps it, wrapping, skipping 0) / ACKSEQ (the cartridge sets it to SEQ when the reply is in) |
| `$9C05-$9C09` | device, command, parameter count (0-8), payload length |
| `$9C0A-$9C0F` | status (diagnostic), error, reply length, reply command (ACK / NAK), link |
| `$9C10-$9C17`, `$9C20-$9C3F` | 8 parameter sizes (1, 2 or 4), 8 values of 4 cells, little endian |
| `$9C18-$9C1A` | boot state, percent, error (the push, outside the SEQ handshake) |
| `$9C1B` | BOOTSEL doorbell ($B5): reboots FujiNet's RP2040; nothing to do here |
| `$9C40-$9D3F` | request payload, 256 |
| `$9D40-$9F3F` | reply payload, 512 |

Re-poking the same SEQ is a no-op, so a retry never replays a command.
Simpler than the 7800's register file and TX stream: one dual-port block
RAM (832 x 8: one M10K) and the transaction engine, which reads the
request out of the cells and writes the reply into them.

The window sits at the top of JLP's `$8000-$9FFF`. FujiNet's own rule
(`pico/intellivision/README.md`, `firmware/src/fujinet.c`
`apply_boot_mapping()`): a JLP game gets the mailbox only if its `.cfg`
`[vars]` sets `fujinet = 1`; any other game keeps it unless its map
overlaps the cells. This core's JLP RAM is in SRAM (`$1C000`), so the
mailbox would be decoded ahead of it for `$9C00-$9F3F` while claimed.

### 3.2 How a program claims it

The 7800 has the "FUJI" signature at `$FF70`; the Intellivision has none.
FujiNet's convention is `fujinet = 1` in the `.cfg` `[vars]`.
`intv_cfgparse.sv` ignores variables it does not know, so a `fujinet` flag
beside `jlp` and the rest is a small change. A `.rom` or `.luigi` has no
`[vars]`: such a program would need the flag from the CRC table, or
another rule.

FujiNet's Intellivision CONFIG (Wi-Fi setup, host slots, browsing, boot) is
an IntyBASIC program that fujinet-firmware carries built:
`pico/intellivision/firmware/include/fujiconfigrom.h` (26,602 bytes, BIN
format, big-endian words), with its map in `firmware/src/fujiboot.c`
`fuji_config_map()`: $0000-$0FFF at $5000, $1000-$1E16 at $6000,
$1E17-$2CEA at $D000, $2CEB-$33F4 at $F000, and 8-bit RAM at $8000-$8FFF
and $9000-$9BFF. A script, as openFPGA-7800's `sim/fujinet/mk_config_a78.py`
does for the 7800, could write `CONFIG.bin` and a `CONFIG.cfg` with that
`[mapping]`, `[memattr]` and `fujinet = 1`, to load from the SD card.
CONFIG is GPL-3.0 (fujinet-config): the repository would not carry it.

### 3.3 Booting a game

The FujiNet pushes the `.cfg` first, as stream 1, then the ROM as stream 0
(`fujinet.c` `dbc_inbound_handler()`). On CLOSE the cartridge applies the
map and resets the console itself: no BOOTLOCK, no loader at `$0600`, no
jump, as the 7800 needs. FujiNet's cartridge refuses a bank-switched
`.rom`; this core handles bank switching and could take it.

This core already parses `.bin` + `.cfg`, `.rom` and `.luigi` in its loader
(`intv_loader.sv`, `intv_cfgparse.sv`, `intv_romparse.sv`,
`intv_luiparse.sv`). The swap would replay the pushed `.cfg` into the CFG
parser's buffer (where `apf_cfgfetch.sv` puts the SD card's) and the image
through the loader's byte stream, then reset the machine, as the 7800's
swap replays the staged file through its load path.

### 3.4 Where a push is staged

Not in SRAM: its 128K words are all in use (CARTFORMATS.md: plane 1, the
ECS ROM, the save state's staging area, cart RAM, JLP RAM). The running
program, CONFIG, is in plane 1, so a push cannot land there either. The
Pocket's PSRAM is unused by this core: staging would go there, through a
PSRAM controller (the `psram.sv` the 7800 core uses, MIT) and the cram0
pins. That is the largest new piece.

### 3.5 Clock

clk_sys is 42.95 MHz here, 14.32 MHz on the 7800, and the core's worst
setup is +0.754 ns (TUTORVISION.md 5.4). The UART's divider is 373
(115,200 baud, 0.03 % off). The 7800's mailbox engine was timed at
14.32 MHz; here it should run on a clock enable at a third or a quarter of
clk_sys, with multicycle constraints, rather than take the core's margin.

## 4. Cost and risks

- **Area:** in the 7800 core the FujiNet logic is about 1,030 ALMs
  (openFPGA-7800 fit, 2026-11-19: mailbox engine 829 with the UART's 37,
  loader 122, stager 33, reader 7). Here, with the PSRAM controller and a
  simpler mailbox, about 1,100-1,400 [estimated]: from 81 % (15,052 ALMs)
  to about 87-89 %. One more M10K for the cells.
- **Timing** at 42.95 MHz is the main risk (3.5).
- **Save states:** the transaction state is not in the blob. Simplest:
  refuse save states while a program has the mailbox claimed.
- **`core.json`:** `link_port` false and `cartridge_adapter` -1 today; both
  must change (TX driven on the link port; the cartridge slot powered for
  a device there).
- **The Pocket's voltage switch:** a GB or GBC cartridge puts the rail at
  5 V; a FujiNet device in the slot needs a GBA-shaped corner (the 7800
  device notes).
- **Upstream status:** FujiNet's own Intellivision cartridge worked on its
  PiRTO II prototype; the current Minty-based firmware is marked not yet
  verified on hardware (`pico/intellivision/README.md`).

## 5. Order, once the 7800 has proven it

1. The mailbox, the UART and the port selection, and CONFIG from the SD
   card: Wi-Fi setup, browsing and the network devices. Most of the value
   for the least work.
2. The push receiver and staging in the PSRAM.
3. The swap through the loader.
4. An end-to-end bench: a FujiNet model on the link, CONFIG or a test
   program, a pushed game booting.
5. Fits, with the timing of 3.5 in mind.

## Sources

- fujinet-firmware (GPL-3.0; read as specification):
  `build-platforms/platformio-fujiversal-intv.ini`,
  `pico/intellivision/README.md`, `PROVENANCE.md`,
  `firmware/include/fuji_mailbox.h`, `fujibus.h`, `fujiconfigrom.h`,
  `firmware/src/fujinet.c`, `fujiboot.c`, `cartridge.c`.
- openFPGA-7800 (MIT, same author): the files and documents named above.
- This repository: DESIGN.md (section 5), CARTFORMATS.md, TUTORVISION.md
  (5.4), `intv_cfgparse.sv`, `dist/.../core.json`, `data.json`.
