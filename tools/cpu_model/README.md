# cpu_model

Our own CP1610 model in Python (build step 0): registers, flags, every opcode,
SDBD, interrupts and cycle counts, with a bus log. It is the golden model for
the RTL CPU (lockstep) and is checked against MAME traces as a black box.
