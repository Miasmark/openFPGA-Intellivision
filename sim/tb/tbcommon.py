# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""What the bench drivers share (docs/SIM_SPEED.md).

vl_env(): the environment for a `verilator --binary` call. Verilator's generated makefile compiles
every C++ file through $(OBJCACHE); OBJCACHE is set to ccache when ccache is installed and the
caller has not set it (an empty OBJCACHE turns the cache off). ccache's own settings come from the
caller's environment: on the owner's VM the gate scripts set CCACHE_DIR=~/daria_work/ccache
(20 GB), away from the shared default cache.

VL_MAKEFLAGS: added to every bench build: the generated makefile's optimisation of the model's
code and of the Verilator runtime (OPT_FAST, OPT_GLOBAL; Verilator's default is -Os).

part_of(): --part K/N, a gate's long bench split into N processes."""
import os
import shutil
import sys

VL_MAKEFLAGS = ['-MAKEFLAGS', 'OPT_FAST=-O2', '-MAKEFLAGS', 'OPT_GLOBAL=-O2']


def vl_env():
    e = dict(os.environ)
    if 'OBJCACHE' not in e:
        e['OBJCACHE'] = 'ccache' if shutil.which('ccache') else ''
    return e


def part_of(items, part, cost):
    """--part K/N: the items (in their order) of part K when the items are dealt to N parts, each
    to the part with the least cost so far, the costliest first; every item is in exactly one part."""
    try:
        k, n = (int(x) for x in part.split('/'))
    except ValueError:
        k = n = 0
    if not 1 <= k <= n:
        sys.exit('--part %s: want K/N with 1 <= K <= N' % part)
    load, own = [0.0] * n, {}
    for i in sorted(range(len(items)), key=lambda i: (-cost(items[i]), i)):
        j = load.index(min(load))
        load[j] += cost(items[i])
        own[i] = j
    return [x for i, x in enumerate(items) if own[i] == k - 1]
