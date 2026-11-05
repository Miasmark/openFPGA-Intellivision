# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""What the bench drivers share (docs/SIM_SPEED.md).

vl_env(): the environment for a `verilator --binary` call. Verilator's generated makefile compiles
every C++ file through $(OBJCACHE); OBJCACHE is set to ccache when ccache is installed and the
caller has not set it (an empty OBJCACHE turns the cache off). ccache's own settings come from the
caller's environment: on the owner's VM the gate scripts set CCACHE_DIR=~/daria_work/ccache
(20 GB), away from the shared default cache.

VL_MAKEFLAGS: added to every bench build: the generated makefile's optimisation of the model's
code and of the Verilator runtime (OPT_FAST, OPT_GLOBAL; Verilator's default is -Os)."""
import os
import shutil

VL_MAKEFLAGS = ['-MAKEFLAGS', 'OPT_FAST=-O2', '-MAKEFLAGS', 'OPT_GLOBAL=-O2']


def vl_env():
    e = dict(os.environ)
    if 'OBJCACHE' not in e:
        e['OBJCACHE'] = 'ccache' if shutil.which('ccache') else ''
    return e

