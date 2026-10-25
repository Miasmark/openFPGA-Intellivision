# regress

The regression set (DESIGN.md 8.3): about 25 images, one per hardware class,
listed by path in the owner's library and by CRC32. No image is committed.

The set must include MTE201 alt (`C83EEA4C`, 16,386 bytes) and Triple
Challenge (`095638C0`, 45,058 bytes). Their size is not a multiple of 4, so
they test the loader's length gate (the CRC is taken over the file length
from the data table, not over every 32-bit bridge strobe; see
`tools/mapper/README.md`). The library has no odd-length image, so the step
2 bench also needs a synthetic odd-length image from the assembler.

`mapper_library.csv`: for each image of the owner's library (by file name and
CRC32), the mapper model's status, layout, flags and mapped-space CRC, written by
`python3 -I tools/intv_mapper.py check <library> --out sim/regress/mapper_library.csv`.
The RTL cart module must give the same mapped-space CRC (build steps 2 and 8).

`step2_set.csv`: the build step 2 set (25 images): one per layout the
owner's library uses (21 layouts) plus the ECS and Intellivoice flag
classes, the 8-bit RAM carts (1K mirrored and 2K), a 16-bit prototype (Land
Battle), WSMLB's paged ROM, the ECS_OFF and ECS_RISK classes, MTE201 alt
(`C83EEA4C`) and Triple Challenge (`095638C0`), and two synthetic odd-length
images (4n+1 and 4n+3 bytes, default map) that `sim/tb/tb_loader.py` builds
from `sim/testroms/loader_odd.asm` with `tools/as1610.py`. Library images
are named by file and CRC32; `tb_loader.py` checks both.
