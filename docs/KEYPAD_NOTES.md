# On-screen keypad and game profiles (build step 13)

The owner's decisions (2026-10-31) on the step-13 proposal:

1. The game keeps running while a keypad is open (no pause).
2. Text labels first, with the keypad drawn mostly transparent. Overlay images are not built.
3. Select on the second controller opens player 2's keypad.
4. Per-game profiles may remap A / B / X.

`tools/osk.py` is the model (the keypad's state machine, the profiles, the font, the drawing,
and the RTL's tables). `sim/tb/tb_osk.py` compares the RTL with it.

## 1 The keypad

| Input (that controller) | Keypad closed | Keypad open |
|---|---|---|
| Select | opens it | closes it |
| B | lower left side action (Layer) | closes it |
| D-pad | the disc | moves the cursor, wrapping at the edges |
| A | lower right side action (Layer) | presses the cursor's key, held until A is let go |
| other buttons | as the keypad mode says | nothing |
| analog sticks | as the keypad mode says | as the keypad mode says |

- Player 1's keypad belongs to cont1, player 2's to cont2. Only controller types 1-3 have one;
  any other type closes it. Its key goes into that player's hand controller, wherever Swap puts
  it.
- The key pressed is the one under the cursor when A went down. Moving the cursor while A is
  held does not change it.
- Buttons still held when the keypad closes stay masked until they are let go, so the B that
  closes it does not also press the lower-left side action.
- Everything is decided once a frame (intv_input's `frame`, the video frame's start) from the
  controller word of that moment. The keypads are not machine state: a save state neither keeps
  nor restores them.

## 2 Drawing

- Each keypad is a 3 x 4 grid (1 2 3 / 4 5 6 / 7 8 9 / C 0 E) of 12 x 20 cells (37 x 82 with the
  outlines) at the bottom of the playfield: player 1's at x 2, player 2's at x 121, both from
  line 108.
- It is mostly transparent: white cell outlines, and glyphs from our own 5 x 7 font (each row on
  two lines, as the STIC's card pixels) in white with a black shadow one pixel right and one row
  down. Nothing else covers the game.
- The cursor cell's outline and glyph are yellow. While its key is held the cell is filled
  yellow and the glyph is black.
- Above the grid (from line 90) is the cursor key's label from the game's profile, in white with
  a shadow: player 1's from the grid's left edge, player 2's ending at its grid's right edge.
  While both keypads are open, player 2's label is one row higher (line 70), because the two
  labels could overlap.
- `intv_osk_draw` works out each pixel in 4 of the pixel's 12 clk_sys (where it is, its
  character, the glyph row, the row above for the shadow). `pocket_video` takes the result with
  the STIC's colour for the same pixel.

## 3 Profiles

`tools/osk.py PROFILES` lists each game with:

- its cartridge CRC-32s;
- the keypad mode for Keypad Mode **Auto**: the new default, setting value 3, which used to work
  as Layer;
- the side actions of A / B / X in Auto's Layer mode;
- the labels: function facts from the game's overlay, in our own words, at most 14 characters.

Without a profile, Auto is Layer with the usual side actions. The fixed modes (Layer, Face-button
ring, Right stick) ignore the profile's mode and sides, but the labels are still shown.

| Game | Auto's mode | A / B / X | Labels |
|---|---|---|---|
| B-17 Bomber | Layer | top / lower left / lower right (A bombs and fires) | 10 keys (crew positions, guns, views) |
| Space Spartans | Layer | as usual | all 12 |
| TRON Deadly Discs | Face-button ring | as usual | throws in 8 directions, 5 = block |
| AD&D Cloudy Mountain (two CRCs) | Layer | as usual | 8 arrow directions, Clear / 0 / Enter |

`python3 -I tools/osk.py gen` writes the RTL's tables (`src/fpga/core/tables/osk_*.hex`):

| File | Holds |
|---|---|
| `osk_crc.hex` | 64 entries of valid, CRC, profile |
| `osk_prof.hex` | mode, sides and 12 label indices per profile |
| `osk_label.hex` | 64 labels of 16 bytes (length, then character codes) |
| `osk_llen.hex` | the labels' lengths |
| `osk_font.hex` | 64 glyphs of 8 rows |

`intv_profile` scans the CRC table one entry a clk, round and round, and takes the result at the
end of each round of 64.

## 4 Gates

- `tools/osk.py`: self-check (OSK_SELFTEST) and `gen --check` (OSK_TABLES).
- `sim/tb/tb_osk.py --all`: about 540 frames are run through the RTL (intv_input, intv_profile,
  intv_osk_draw on a small raster):
  - written-out frames for every rule above, every profile's every cell, Auto's modes and side
    actions, the fixed modes, Swap;
  - random frames.

  Both pad bytes and every overlay pixel of every frame must equal the model's. Fourteen planted
  faults (cursor wrap, A held by level, the close's mask, buttons leaking while open, player 2's
  key, Auto's sides and mode, the profile scan's first entry, the shadow, player 2's label row,
  the cursor's outline, the shadow's row, the pressed fill, the label's character address) must
  each fail.
- `tb_input`: unchanged. Its keypads never step (`frame` = 0), and mode 3 without a profile is
  Layer, as before.
- `apf_json_check`: Keypad Mode's options and its power-up value Auto (core_top's
  `set_kp_mode`).
