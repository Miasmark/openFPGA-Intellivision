# CP1610 notes

What the Python CPU model (`tools/cp1610.py`) and assembler
(`tools/as1610.py`) do, which document each behaviour comes from, and every
place where the sources disagree or say nothing. Build step 0 of DESIGN.md
section 9. The RTL CPU (step 3) follows the same choices and runs in
lockstep with the model.

## Sources

| Code | Document | Used for |
|---|---|---|
| S1 | GI CP-1600 Microprocessor Users Manual, May 1975 | pins p.12-14; state flow p.21-25; timing diagrams p.27-37 (interrupt sequence p.35); formats p.44-52; instruction set and cycles p.53-58 |
| wiki | wiki.intellivision.us: CP1610, Bus_Phases, Branch, Jump, Double_Byte_Data, Undocumented_SDBD_Behavior, Interrupt_Enable_Flag, VBlank_Interrupt, the opcode pages | cycles, interruptibility, flags, bus phase sequences |
| S9 | jzIntv documents `doc/jzintv/cp_1610.txt` (read as specification text, no code) | SDBD and HLT remarks |
| MAME | `src/devices/cpu/cp1610/cp1610.cpp` (BSD-3) | cross-check of facts only; no code taken |

The page numbers are PDF pages of the bitsavers scan. The S1 text layer is
OCR; tables were checked against the page images where the OCR was unclear.

## The model

- **State:** R0-R7 (R6 stack pointer, R7 program counter), S Z O C, I
  (interrupt enable), D (double byte data), the "last instruction was
  interruptible" latch, the INTRM and INTR edge latches, halt state. All of
  it is in `CP1610.state()`, which the save-state work will reuse.
- **Reset:** the PC comes from the bus in an IAB phase (S1 p.21); on the
  Intellivision that is $1000. Registers and flags are undefined on the chip
  (S1 p.21); the model clears them. I is clear (S1 p.21). The
  initialisation sequence is not counted: cycle 0 is the first fetch.
- **Opcode width:** bits 15-10 of an opcode are "Future Use" (S1 p.46); the
  model decodes the low 10 bits of the opcode and of the jump's address
  words. Immediate data, direct addresses and branch displacements use all
  16 bits (S1 p.48-49, p.54; wiki Branch: "All 16 bits are significant").
- **Flags:** C is the carry out of the ALU; subtraction and compare are
  a + ~b + 1, so C means "no borrow" (S1 p.45; wiki Carry_Flag). OV is two's
  complement overflow (wiki Overflow_Flag truth tables). Right shifts, SWAP
  and their two-position forms take S from bit 7 of the result (S1 p.53;
  wiki CP1610); everything else from bit 15. GSWD gives SZOC0000SZOC0000,
  RSWD takes bits 7-4 (S1 p.56).

### Cycles and bus phases

Each instruction is built from the documented bus sequences (wiki
Bus_Phases; S1 p.29-35). The sum gives the documented count (S1 p.53-58,
wiki opcode pages). `run_cpu_tests.py` checks every one of the 1024 opcodes
against a separate table of the documented counts, and that the bus log
accounts for every cycle.

| Sequence | Phases | Cycles |
|---|---|---|
| fetch, indirect or immediate read | BAR NACT DTB NACT | 4 |
| write | BAR NACT DW DWS NACT | 5 |
| direct read | BAR NACT ADAR NACT DTB NACT | 6 |
| direct write | BAR NACT ADAR NACT DW DWS NACT | 7 |
| SDBD read (two locations) | BAR NACT DTB BAR NACT DTB | 6 |
| interrupt (S1 p.35) | INTAK NACT DW DWS NACT IAB NACT NACT NACT | 9 |

| Instructions | Make-up | Cycles |
|---|---|---|
| HLT SDBD EIS DIS TCI CLRC SETC | fetch | 4 |
| INCR DECR COMR NEGR ADCR GSWD NOP SIN RSWD, ADDR SUBR CMPR ANDR XORR | fetch + 2 NACT | 6 |
| MOVR (TSTR, JR) to R6 or R7 | fetch + 3 NACT | 7 |
| shifts, SWAP | fetch + 2 NACT (one position) or 4 NACT (two) | 6 / 8 |
| J JE JD JSR JSRE JSRD | 3 fetches | 12 |
| branch taken | fetch + read + NACT | 9 |
| branch not taken | fetch + BAR NACT DTB (estimated: no trailing NACT) | 7 |
| MVO | fetch + direct write | 11 |
| MVO@, PSHR, MVOI | fetch + write | 9 |
| MVI ADD SUB CMP AND XOR direct | fetch + direct read | 10 |
| ... indirect R1-R5, immediate | fetch + read | 8 |
| ... stack (R6) | fetch + 3 NACT + read | 11 |
| ... after SDBD (R1-R5, R7) | fetch + SDBD read | 10 |

Where the three extra cycles of a stack read sit inside the instruction is
not documented; the model puts them before the read (estimated).

### Interruptibility, interrupts, bus requests

- Not interruptible: HLT SDBD EIS DIS TCI CLRC SETC, all shifts and SWAP,
  MVO, MVO@, PSHR, MVOI (wiki CP1610 table; S1 p.53, p.56). After a
  non-interruptible instruction the CPU checks neither BUSRQ nor
  interrupts (wiki CP1610 Interruptibility).
- After an interruptible instruction: BUSRQ first, then INTR, then INTRM if
  I is set (S1 p.24-25). During a bus request the bus shows NACT with BUSAK
  for exactly as long as BUSRQ stays low (S1 p.24); entry or exit overhead is
  not documented and the model adds none (estimated).
- INTRM and INTR are edge requests: a high-to-low transition latches a
  request, which is dropped if the line goes high before it is taken (wiki
  CP1610 Signal Pins). The model samples the lines at every instruction
  boundary. Taking an interrupt does not change I (no source says it does);
  the edge latch is why the EXEC's handler is not re-entered while the STIC
  holds SR1 low for about 3,790 cycles (wiki VBlank_Interrupt).
- The interrupt pushes the PC at R6 (then R6 + 1) and loads the vector from
  IAB (S1 p.24-25). The vector is $1004 on the Intellivision.
- INTR before INTRM: when both are pending, taking INTR clears only the
  INTR request; the INTRM request is taken after the handler's first
  interruptible instruction (irq_both.asm).
- An INTRM edge that arrives during a bus-request wait is sampled at the
  end of the wait and taken at once (busrq_intrm_edge.asm).
- No BUSRQ or interrupt check between the interrupt sequence and the first
  instruction of the handler: that instruction always runs first, even
  with BUSRQ held during the sequence. S1 does not say; this matches MAME
  (estimated, busrq_in_intr.asm).

## Where the sources disagree

| # | Topic | S1 | wiki | Others | Model | Test |
|---|---|---|---|---|---|---|
| 1 | Cost of taking an interrupt | 9 cycles: INTAK NACT DW DWS NACT IAB NACT NACT NACT, counted on the p.35 timing diagram | 7 (Interrupt_Enable_Flag); 10 (Bus_Phases, "unsure about the NACTs at the end") | MAME 9 | **9** | interrupts.asm, phase sweep |
| 2 | SIN interruptible? | yes: "The interrupt will be acknowledged at the end of the SIN instruction" (p.13) | CP1610 table: yes; SIN page: no | MAME: yes | **yes** | sweep |
| 3 | SETC cycles | 4 (p.56) | 4 | MAME 6 (cp1610.cpp:153); the lockstep sees MAME charge 6 for every SETC in the game traces | **4** | implied.asm |
| 4 | SARC Rr, 2 cycles | 8 ("add 2 cycles if shift is 2 bits", p.53) | 8 | MAME 6 (cp1610.cpp:567; every other two-position shift there is 8); the lockstep sees 6 for every SARC Rr,2 | **8** | sweep |
| 5 | NEGR of 0: carry | status S Z C OV (p.53, OCR damaged) | "Negating 0 ... sets the Carry Flag" (NEGR) | MAME never sets C (it truncates to 16 bits before the carry test) | **C=1** | single_reg.asm |
| 6 | SWAP Rr, 2 | "swap bytes ..., then swap them back to original form" (p.53) | low byte copied to both halves (SWAP) | MAME as the wiki ("not officially supported by GI"); S9 "swaps bytes in word once or twice" | **wiki** | shifts.asm |
| 7 | HLT | "HaLT after next instruction is executed. Resume on control start", 4 cycles (p.56) | halts, cycles "Infinity", ignores interrupts until reset or STPST (HLT) | S9: "Halts the CPU (until next interrupt?)"; MAME: 4 cycles, does not halt (TBD) | **S1**: the instruction after HLT runs, whatever it is (a second HLT included), then the CPU halts; option `hlt='immediate'` | hlt.asm, hlt_twice.asm, hlt_immediate.asm |
| 8 | SDBD with R6 | not supported (p.49, p.57) | 10 cycles "regardless of which register" (MVI@, ADD@...); "two stack reads from top of stack, ... decrements stack pointer once" (Undocumented_SDBD_Behavior, from memory) | S9: "not allowed, although I suspect it works as expected (two accesses through R6)"; MAME: two pre-decrements, 13 cycles + SDBD | **wiki** (one decrement, same word twice, 10); option `sdbd_r6='mame'`; strict raises | sdbd.asm, sdbd_r6_mame.asm, strict_sdbd_r6.asm |
| 9 | SDBD with direct mode | not supported (p.49) | "modifies the behavior of Direct Mode", details unknown (Double_Byte_Data, Undocumented_SDBD_Behavior) | MAME decodes it as indirect through R0 | **D ignored**, one direct read; marked undefined; strict raises | undefined.asm, strict_sdbd_direct.asm |
| 10 | SDBD before MVO | double byte data is described for reads (p.46-49) | CP1610 table lists D as an input of MVO@ and MVOI | S9: "bringing in (or out) two 8-bit words"; MAME: illegal | **D ignored**, one write; marked undefined | undefined.asm |
| 11 | Branch not taken | 7/9 (p.54) | 7/9 | MAME 7/9 | **7**; the dropped NACT is estimated | branch_range.asm, phase sweep |
| 12 | INTRM: level or edge | "low active ... honor an interrupt at the completion of any interruptable instruction" (p.12) | high-to-low transition, dropped if released first (CP1610 Signal Pins) | MAME: pending on assert, cleared on release or when taken | **edge latch** | interrupts.asm, irq_mask.asm |
| 13 | Branch reach in 10-bit ROM | "+1025 to -1024" (p.54) | 2K words either way (Branch) | | **the encoding rule**: forward PC+2+d, backward PC+1-d, d up to 2^ROMW-1, so PC+1025 and PC-1022 | branch_romw10.asm |
| 14 | Jump with II=11 | only II = 00, 01, 10 defined (p.52) | "unknown opcode (behavior unknown!!)" (Jump) | S9 "Invalid opcode"; MAME: logs it and does not jump | **jumps, I unchanged**; marked undefined; strict raises | undefined.asm, strict_jump_ii3.asm |
| 15 | MVO@ with the pointer as source | "SSS = MMM = 4, 5, 6 or 7 not supported" (p.55) | | MAME writes the old value | **old value, then increment**; marked undefined | undefined.asm |

**Errors on single wiki pages** (the CP1610 table and S1 agree with each
other, and with MAME's decoder):

- RLC shows the format `0101:1srr`, which is SLLC's; RLC is `0101:0srr`
  ($0050-$0057).
- RRC shows `0111:1srr`, which is SARC's; RRC is `0111:0srr` ($0070-$0077).
- SIN shows `0011:010x`, which is NOP's; SIN is `0011:011x` ($0036-$0037).
- ADD@ gives the range $02C0-$02C7 (ADD direct); ADD@ is $02C8-$02EF.
- The CP1610 table gives the immediate forms as $xx0-$xxF (MVOI $0270-$027F,
  MVII $02B0-$02BF, ...). The immediate forms are $xx8-$xxF; $xx0-$xx7 are
  the stack (R6) forms (PSHR $0270-$0277, PULR $02B0-$02B7).

## Undefined cases

The default (non-strict) model applies the choice in the table above and
marks the event (`Event.undefined`; a `?` in the trace). With `strict=True`
it raises `UndefinedBehaviour` instead, which is how a test or the MAME
trace comparison finds out that a program depends on one of them.

Not marked, but also unverified: an instruction whose pointer register is
also its destination (`MVI@ R4, R4`, `ADD@ R5, R5`). The model increments
the pointer first and then writes the result, so for MVI@ the data wins and
ADD@ adds to the incremented pointer (the same order as MAME). The wiki
calls the SDBD form of this "an interesting blend of old and new register
values" (Undocumented_SDBD_Behavior), without details.

## Open points

1. **Sampling point of INTRM/BUSRQ.** S1 says the lines are synchronised at
   every TS1 (p.24-25) but not how late in the last instruction a request
   can arrive and still be taken. The model samples at the boundary cycle.
   This sets the exact cycle of the first ISR instruction and of the BUSRQ
   response, which matter for STIC timing (DESIGN.md section 13, items 3-5).
   The RTL (step 3) fixes the convention, not the hardware fact: it samples
   at the ce that starts the boundary cycle (see "RTL" below). Whether the
   real chip needs the request a cycle earlier or later is still open and
   moves the STIC's figures by a constant; settle with STIC test ROMs.
2. **Phase position inside branches and stack reads** (estimated, see
   above). Only the totals are documented.
3. **MAME trace comparison**: done, see "MAME lockstep" below. NEGR,
   ADCR, arithmetic overflow, SIN, TCI, HLT and SDBD with R6 do not occur
   in the traced code, so rows 5-10 and 14-15 of the table are still
   unchecked against MAME; only our own test ROMs cover them.
4. **HLT** is never used by games; the choice only matters for test ROMs.

## MAME lockstep (step 0 done-test)

`tools/lockstep.py` runs the model against MAME instruction traces made by
`tools/refs/mame_trace.sh` (MAME 0.289, the owner's fork at 3c6120b6, built
for `intv` only). The model owns the CPU and the memory a bare CPU system
has: EXEC, GROM, the cartridge segments, scratchpad RAM and System RAM. Reads
of everything else (STIC, PSG and controllers, GRAM, Intellivoice, unmapped
probes) are replayed from the trace, and INTRM is raised at the boundary
where the trace shows MAME's "(interrupted at ...)". Before each instruction
it compares PC, R0-R7 and S Z O C; during it, every read and write in
order, with address and data; after it, the cycle count. MAME shows SDBD
and the instruction it prefixes as one step, so the tool merges the two
model steps.

Result, 2026-10-25, on Astrosmash, Tower of Doom and B-17 Bomber (plain
`intv`, so no Intellivoice), from reset:

| Run | Steps (3 games) | Interrupts | State and bus | Cycles |
|---|---|---|---|---|
| 10 frames (refs lane traces) | 56,678 | 14 | all agree | differ only on SETC and SARC Rr,2 |
| 120 frames | 688,237 | 344 | all agree | differ only on SETC and SARC Rr,2 |

- No model bug was found, so no new opcode test was needed. Negative
  checks: a model that pushes the wrong return address on an interrupt, or
  that sets S from bit 15 after SWAP, is caught at the first use; a model
  that never sets O passes, because no ADD/SUB in the traced code
  overflows (O is only raised there by RLC, RRC and SARC).
- **Interrupts**: every interrupt in the traces is taken at a boundary
  the model also treats as interruptible, with I set, and the push writes
  the same return address to the same stack word. Across each interrupt
  MAME's cycle count grows by exactly instruction + 9, which agrees with
  row 1.
- **SDBD**: the 795 SDBD-prefixed instructions of the 10-frame run (MVII,
  ADDI, ANDI, MVI@ through R4 and R5, ADD@ through R5) agree in data and
  cycles: MAME's merged step costs SDBD 4 + the documented SDBD form.
- **Cycles**: the only differences are rows 3 and 4 (SETC: model 4, MAME
  6; SARC Rr,2: model 8, MAME 6). The model keeps the documented values.
  The lockstep enforces this: those two (mnemonic, model, MAME) triples
  are its allowlist (`KNOWN_CYCLE_DIFF`), and any other cycle difference,
  or an interrupt step whose MAME delta is not exactly instruction +
  interrupt, is a divergence and makes the run `LOCKSTEP FAIL`. (A lump
  of extra cycles at an interrupt is accepted only up to `--max-lump N`,
  default 0, for later traces where STIC stealing may show up.) Checked by
  planting a model that charges 9 instead of 8 cycles for indirect and
  immediate reads, one with a 10-cycle interrupt, one with an 8-cycle
  interrupt and one with a 5-cycle SETC: each fails, on both the 10- and
  the 120-frame traces.
- **STIC cycle stealing does not show in MAME's cycle counter.** Every
  instruction's cycle delta equals its documented count (rows 3-4 aside),
  also across interrupts, and a frame is about 14,934 cycles
  (3,579,545 / 4 / 59.92), so the CPU gets the whole frame. MAME's
  interrupt handler subtracts the STIC's BUSRQ cycles with `adjust_icount`
  (intv_m.cpp:668, 680), but the counter does not show them; most likely
  the handler runs outside the CPU's timeslice, which was not checked
  further. So MAME's cycle counts are not a reference for BUSRQ timing in
  step 4.
- **GROM reads give $FFxx** in MAME (`0xFF00 | byte`, stic.cpp:1319): the
  GROM drives DB0-7 only and the pulled-up bus gives ones above (DESIGN
  2.5). The lockstep's memory does the same; the first run, with the
  upper byte at 0, diverged at the EXEC's first GROM read ($36DF at $1F40).
  EXEC reads give $0xxx (10-bit words, upper bits 0) in MAME; whether the
  real EXEC ROMs drive DB10-15 low or leave them high is open for step 3.

Run it (the BIOS, images and traces are outside the repo; the paths go in
INTV_BIOS_DIR, INTV_GAME_DIR and INTV_TRACE_ROOT, or the matching options):

    python3 tools/lockstep.py                  # the three games
    python3 tools/lockstep.py --context 20 b17bomb

## RTL (build step 3)

`src/fpga/core/cp1610.sv` is the CPU in SystemVerilog, written from the
documents above and this model, with the same choices (every row of the
disagreement table, the undefined cases and both options). It runs one
bus phase per `ce` (one CPU cycle). No tristate: a 3-bit phase code
{BDIR, BC2, BC1} (DESIGN.md 2.5), `dout` and a combined `din`.

- **Sequencer.** One state per bus cycle (fetch, operand read, SDBD
  second read, write, direct address, idle, the nine interrupt cycles,
  bus wait, halt), so `phase` and `dout` come from flip-flops only. The
  instruction's effect lands at its last cycle, pointer updates at the
  decode (the model's order: pointer first, then the result, so
  `MVI@ R4, R4` gives the data and `ADD@ R5, R5` adds to the incremented
  pointer). Cycle counts are the model's.
- **Reset.** One IAB cycle loads the PC (S1 p.21), then the first fetch.
  The model does not count that cycle; its cycle 0 is the fetch's BAR.
- **Request lines** (active high in the core) are sampled at the `ce`
  that ends the last cycle of an instruction or of a bus-wait cycle,
  never elsewhere (not after the interrupt sequence, not while halted),
  exactly where the model calls `_sample_irq`. The model's "line at
  cycle c" is the RTL's sample at the `ce` that starts cycle c. A device
  that changes a line with its own registered output at the `ce` ending
  cycle c-1 is therefore seen at the `ce` ending cycle c (one cycle
  later in model terms); step 4 must account for that constant when it
  places SR1 and BUSRQ.
- **Pins.** TCI pulses in the fetch's last cycle (the model's
  cycle + 3). The SIN pulse (`pcit`) comes in the first cycle after the
  fetch; the model's hook is at cycle + 2, inside the fetch, where the
  opcode is not yet known (the bench checks RTL = model + 2). BEXT's
  `ebci` is sampled at the end of the fetch with `ebca` = the condition
  number (the model asks at cycle + 4). BDRDY is not modelled: the freeze
  stops `ce` instead.
- **Halt.** NACT until reset; the core has no STPST.
- **State port** (DESIGN.md 4.3): eight 32-bit words, the 32 bytes of
  DESIGN.md 4.4: R0-R7, the sequence's address and data, opcode, SDBD
  low byte, cycle state and idle counter, the jump/SDBD/halt/branch
  latches, S Z O C I D, the interruptible latch, both edge latches with
  their last samples, halt pending and halted. Layout in the file header.
  Every flip-flop that changes at run time is in it, so a save in any
  cycle restores exactly; `ss_ctl` (step 7) still saves only at a
  quiet point (DESIGN.md 4.2), and the `fetch` output marks an
  instruction's first cycle for that.
- **Execute datapath.** One adder and one result mux serve the
  single-register, shift, register-register and read instructions; the
  flags come from the result itself, not from the register file after
  the write (a first version did that: 1,914 ALMs and a 18.7 ns path
  into Z).
- **Size.** Quartus 21.1 Lite, 5CEBA4F23C8, the CPU alone as top level
  (bus and control ports as virtual pins, 42.95 MHz clk_sys constraint,
  seed 1, in a scratch project outside the repo): 747 ALMs (4 %), 202
  registers, no RAM, no DSP; worst setup slack +9.531 ns (slow 85 C),
  worst hold +0.169 ns (fast 0 C). DESIGN.md section 3 estimated
  900-1,500 ALMs.

### Lockstep bench

`sim/tb/tb_cpu.sv`, run by `sim/tb/run_tb_cpu.sh --all` (Verilator 5.040),
compares the RTL with the model's bus-phase log exported by
`tools/cpu_buslog.py`, in every cycle: the phase; the address on BAR and
INTAK; the latched address and the data on DTB, ADAR, DW and DWS; the
vector on IAB; BUSAK and halt; TCI and SIN. A step (instruction,
interrupt, bus wait, halted cycle) must start in exactly the cycles where
a model step ends, with R0-R7, S Z O C, I and D equal there, and the final
state must agree. Case sets:

| Set | Cases | What |
|---|---|---|
| tests | 35 | every program in `sim/tests/cpu` with its own start, stop, request lines, BEXT conditions and options (the 3 asm-error tests have no program; the 3 strict tests run non-strict, so the RTL's default choice is the one compared) |
| sweep | 1,420 | every opcode once, after SDBD for each double-byte read, each branch taken and not taken, registers as in `run_cpu_tests.py`'s cycle sweep, at least 40 cycles each |
| fuzz | 300 | random programs: all 64K words from a hash both sides compute, random registers, flags, I, start address, INTRM/INTR/BUSRQ windows, BEXT conditions, and both HLT and SDBD+R6 options; about 600 cycles each |

Each set runs twice: straight, and with save points (state read through
the state port mid-instruction, inside the interrupt sequence, inside bus
waits, between HLT and the halt, and at random cycles; loaded into the
other CPU instance, alternately reset first and left stale; read back;
run on). Planted faults that the script builds and the bench must catch:
10-cycle interrupt, INTRM as a level, SDBD bytes swapped, branch not
taken with the trailing NACT, SWAP's S from bit 15, MVO interruptible, no
line sample after a bus wait, JSR return address one low, NEGR 0 without
C, and the state port missing the idle counter, the INTRM line sample,
the SDBD low byte, the sequence data word or halt pending.

## Assembler

`tools/as1610.py`, our own, syntax from S1 (operand order source first:
`MVI A, DDD`, `MVO SSS, A`, `ADDI I, DDD`, `MVOI SSS, I`). Immediates may be
written with or without `#`. `ROMW 10` makes the assembler add SDBD and two
decles to an immediate over $3FF, as S1 p.49 describes; an explicit SDBD
always gives two decles. Branches pick the direction from the target and
check the displacement against the ROM width; the CPU adds mod 2^16, so
when the direction that does not wrap past $FFFF is too far for the ROM
width, the wrapping one is used if it fits (`ORG $FFFE / B $0003` with
`ROMW 10` is forward 3; branch_wrap.asm). Labels may not be register
names (R0-R7, SP, PC); a label without a colon must start in column 0 and
not be a mnemonic. Output: a raw image (segments joined, big-endian words,
like a `.int`), a `[mapping]` `.cfg` for it, and a listing.

## Trace format

One line per instruction, interrupt (`INT`), bus wait (`BUS`) or halted
cycle (`HLT`):

```
     cycle PC   words           instruction             R0   R1   R2   R3   R4   R5   R6   R7   SZOC ID  cyc
       102 5012 INT             INTERRUPT -> $6000      0000 0000 0000 0000 0000 0000 0301 6000 ---- I-   9
```

`cycle` is the cycle at which the step starts, registers and flags are the
values after it, `ID` shows I and D, `cyc` the cycles taken. With
`buslog=True` the model also records `(cycle, phase, address, data)` for
every bus cycle, for the RTL lockstep test.
