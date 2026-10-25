#!/bin/bash
# build_mame_intv.sh MAME_FORK BUILD_DIR [COMMIT]
# Build an Intellivision-only MAME (intv, intv2, intvsrs, intvoice, intvecs,
# intvkbd) from the owner's MAME fork, as a detached git worktree in
# BUILD_DIR. Heavy job: 8 make jobs at nice 10; detach it and poll the log.
# Qt is not installed on the VM, hence USE_QTDEBUG=0 (the console debugger
# and Lua still work; see mame_trace.sh). Took about 8 minutes on the VM.
set -euo pipefail
fork=${1:?MAME_FORK}; dir=${2:?BUILD_DIR}; rev=${3:-HEAD}
[ -d "$dir" ] || git -C "$fork" worktree add --detach "$dir" "$rev"
cd "$dir"
exec nice -n 10 make -j8 USE_QTDEBUG=0 TOOLS=0 SOURCES=src/mame/mattel/intv.cpp
