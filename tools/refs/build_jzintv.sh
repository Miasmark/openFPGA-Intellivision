#!/bin/bash
# build_jzintv.sh SRC_ZIP WORK_DIR
# Build the jzIntv emulator binary and its movie expander imvtoppm (used by
# jzintv_frames.py) from the official source zip, to run as a black-box
# reference only. Its sources are GPL-2 and are never read or
# copied for this project (clean room, DESIGN.md section 1); only its
# Makefile flags were looked at to build it.
# Official download: http://spatula-city.org/~im14u2c/intv/dl/jzintv-20200712-src.zip
# (sha256 b36b3b274d0fc05cb227818d4957f96620d23d8d6b7596c24f07675ced7129f3).
# glibc on the VM no longer has <termio.h>; a one-line shim header that
# includes <termios.h> is put first on the include path. Readline is off.
set -euo pipefail
zip=${1:?SRC_ZIP}; work=${2:?WORK_DIR}
mkdir -p "$work/src-tree" "$work/shim"
work=$(cd "$work" && pwd)
[ -d "$work/src-tree/jzintv-20200712-src" ] || unzip -q "$zip" -d "$work/src-tree"
printf '/* build shim: glibc dropped termio.h */\n#include <termios.h>\n#include <sys/ioctl.h>\n' > "$work/shim/termio.h"
cd "$work/src-tree/jzintv-20200712-src/src"
nice -n 10 make -f Makefile.linux_sdl2 -j4 GNU_READLINE=0 \
  CC="gcc -std=gnu99 -I$work/shim" CXX="g++ -std=c++14 -I$work/shim" ../bin/jzintv ../bin/imvtoppm
ls -l ../bin/jzintv ../bin/imvtoppm
