# tb

Verilator testbenches, one per build step (DESIGN.md section 9). Outputs go
to `sim/work*`.

- `tb_timing.sv` (step 1): master timing, clock enables, Pocket video
  port, the timing state port. `run_tb_timing.sh --all`.
- `tb_cpu.sv` (step 3): the CP1610 RTL (`src/fpga/core/cp1610.sv`) in
  lockstep with the Python model, cycle by cycle: bus phase, address and
  data, BUSAK, halt, TCI/SIN, the cycle every step ends in with R0-R7,
  S Z O C, I and D there, and the final registers. Cases from
  `tools/cpu_buslog.py`: the 35 programs of `sim/tests/cpu` (the three
  asm-error tests have none), 1,420 opcode-sweep cases and 300 random
  programs, each run once straight and once with save points (state
  saved mid-instruction, in the interrupt sequence and in bus waits,
  restored into the other CPU instance, fresh or stale, and run on).
  `run_tb_cpu.sh --all` also builds planted faults and fails unless the
  bench catches each one.
