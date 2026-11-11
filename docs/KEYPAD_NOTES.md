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

**1.0.7: 63 more games** (`tools/osk_profiles.py`; the owner, 2026-11-11: "you have the overlay
scans already"). Their labels are typed from the owner's 97 overlay scans, matched to the games
by CRC (`research/test-assets/overlay_index.csv`, outside the repository): what each key's cell
of the overlay says, in our words and at most 14 characters. The scans are never in the
repository or a release; only the short labels are. All take Layer and the usual side actions:
no overlay asks for another mode (a mode or side remap is proposed to the owner, not guessed).
The scans with no profile, and why:

| Overlay | Why no profile |
|---|---|
| Beauty & the Beast, Buzz Bombers, The Jetsons' Ways With Words, Night Stalker, Scooby Doo's Maze Chase | a picture, no key functions |
| Bump 'n' Jump, BurgerTime, Kool-Aid Man, Lock 'N' Chase, Mission X, Vectron, Masters of the Universe | only digits (and Enter) on the keys |
| Championship Tennis, Motocross, SNAFU, U.S. Ski Team Skiing, World Cup Soccer, Las Vegas Roulette, Demon Attack, Pitfall! | only digits, game numbers, Clear and Enter |
| Major League Baseball | a field picture: which player is which key is not printed |

Second scans of a game (`auto-101`, `bump-100`, `buzz-100`, `hrac-100`, `mlbb-100`, `moto-100`,
`pinb-100`) and two duplicate files read the same as the first. 67 profiles, 70 CRCs, 349 labels.

`python3 -I tools/osk.py gen` writes the RTL's tables (`src/fpga/core/tables/osk_*.hex`):

| File | Holds |
|---|---|
| `osk_crc.hex` | 128 entries of valid, CRC, profile (64 until 1.0.6) |
| `osk_prof.hex` | mode, sides and 12 label indices (9 bits each; 6 until 1.0.6) per profile, 128 profiles |
| `osk_label.hex` | 512 labels of 16 bytes (length, then character codes; 64 until 1.0.6) |
| `osk_llen.hex` | the labels' lengths |
| `osk_font.hex` | 64 glyphs of 8 rows |

`intv_profile` scans the CRC table one entry a clk, round and round, and takes the result at the
end of each round of 128 (64 until 1.0.6). The label pool is 8,192 x 6 bits of block RAM. tb_osk's
spec frames step every cell of seven profiles (the first four, the one with the pool's last label,
the one in the CRC table's last entry, the one with the most 14-character labels); its random
frames choose among all 70 CRCs; the tables are the model's (`osk.py gen --check`).

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

## 5 The ECS keyboard (1.0.4)

The owner's decisions (2026-11-06): Start opens an on-screen ECS computer keyboard; with the
ECS off it does nothing; laid out like the real keyboard; SHIFT and CTL held by buttons.

| Input (player 1's controller) | Keyboard closed | Keyboard open |
|---|---|---|
| Start | opens it (the ECS on, the computer keyboard set) | closes it |
| B | lower left side action (Layer) | closes it |
| D-pad | the disc | moves the cursor, wrapping at the edges |
| A | lower right side action (Layer) | presses the cursor's key, held until A is let go |
| Y | Clear with R | SHIFT, while held |
| X | top side action | CTL, while held |
| other buttons | as the keypad mode says | nothing |
| analog sticks | as the keypad mode says | as the keypad mode says |

- **When:** only with the ECS fully on (mode on: ECS games under Auto, no cartridge, the
  menu's On) and the ECS Keyboard setting on Computer keyboard: the same condition under which
  a USB keyboard is the ECS keyboard. With the ECS off or attached (Auto's mode for most games:
  no ECS ROM code reads the keyboard) or the synthesizer set, Start does nothing, and if the ECS
  stops being on while the keyboard is open it closes.
- **Whose:** player 1's controller (cont1: the Pocket's own buttons, or the first docked
  controller). The ECS has one keyboard; a second controller's Start does nothing.
- **Layout:** five rows. Rows 0-3 have ten keys each: 1-0, Q-P, A-L ;, Z-M , . and the up
  arrow. Row 4 has ESC (two columns wide), SPACE (three), RTN (two) and the left, down and right
  arrows. With SHIFT and CTL on Y and X, all 48 keys of the ECS matrix (tools/ecs.py KEYPOS) are
  reachable. The cursor starts on RTN, the key most title screens wait for, and stays where it
  was between openings.
- **Moving:** up and down keep the column. In row 4, left and right go key by key and put the
  cursor on the key's first column (so up from SPACE lands on its first column).
- **Keys:** the key pressed is the one under the cursor when A went down, held until A is let
  go, as on the keypad. Its matrix switch goes into `ecs_keys` with the USB keyboard's; the ECS
  reads the matrix with the same no-diode rule (ECS_NOTES 4), so a USB key and an on-screen key
  together mask each other as two real keys would.
- **Never with a keypad:** Start opens the keyboard only while no keypad is open before or after
  this frame's step (so Select and Start together open the keypad), and Select opens no keypad,
  either player's, while the keyboard is open.
- **Masks:** while open it takes all 16 of player 1's buttons (the sticks still play); the
  buttons held when it closes stay masked until let go, as the keypad's.
- **Drawing** (`intv_osk_draw`): 151 x 102 (ten 15-pixel columns, five 20-line rows, with the
  outlines) at x 4 and line 88, inside the Hide window's 159 visible columns; the keypad's style:
  white outlines (in row 4 only at each key's left edge), each key's text centred in our font
  with a shadow, the cursor key yellow, filled yellow with a dark text while pressed. Above it,
  at line 70, "Y:SHIFT" at its left edge and "X:CTL" ending at its right edge, each yellow while
  its button is held.
- **Tables:** `osk_kbd.hex` (osk.py `kbd_hex`): each cell's matrix bit and up to five
  characters. The font gained `;` `,` and the four arrows.

Gates: `tb_osk` compares the keyboard frame by frame with the model (the pads, the ECS keys and
every pixel): spec frames for every key pressed, the moves and wraps, SHIFT and CTL, the closes
and masks, the ECS off, attached and the synthesizer, the keypad interlock both ways, a
non-controller; two random blocks, the second with Select absent and the ECS mostly on so the
keyboard stays open; 21 planted faults (`kb_*`, `keypad_over_kb`), each caught. A plant runs
its own frames (the keyboard's spec and second random block, or the keypad's spec and first
random block: about 6 minutes each instead of 12), and `--all --part K/N` splits the plants over
N jobs (part 1 also runs the frames): the 35 plants take about 3.5 slot-hours.
`sim/check/ecs_osk_check.py` runs the system model twice per case, once typing into the ECS
matrix directly and once with only Pocket buttons through the keyboard (Start, the cursor walked
in the gaps, A held over the same frames, Y for SHIFT): ECS BASIC (10 PRIN 2*3, RUN: 6.00; its print keyword is PRIN) and Super
NFL Football (RTN at its title, DEMO and RTN in its menu: the demonstration starts) give the same
picture in every frame.
