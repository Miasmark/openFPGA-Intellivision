# regress

The regression set (DESIGN.md 8.3): about 25 images, one per hardware class,
listed by path in the owner's library and by CRC32. No image is committed.

`mapper_library.csv`: for each image of the owner's library (by file name and
CRC32), the mapper model's status, layout, flags and mapped-space CRC, written by
`python3 -I tools/intv_mapper.py check <library> --out sim/regress/mapper_library.csv`.
The RTL cart module must give the same mapped-space CRC (build steps 2 and 8).
