#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""run_cache.py: a bench's result reused only on byte-identical inputs (docs/SIM_SPEED.md 5).

  RUN_CACHE=DIR python3 -I sim/check/run_cache.py CMD [ARG...]

runs CMD (a bench: python3 -u -I sim/tb/tb_system.py --all, sim/tb/run_tb_cpu.sh --all, ...,
possibly behind ~/daria_work/bin/simslot) from the current directory, which must be inside the
repository's work tree. Without RUN_CACHE it only runs CMD (opt-in: the gate scripts set it).

With RUN_CACHE, it first hashes everything that can change the result (the key):
  - the git trees of src/fpga, sim and tools at HEAD; when `git status` shows any change or
    untracked file under them, nothing is reused or stored (the trees would not say what ran);
  - CMD and its arguments, the directory it runs in, relative to the work tree's top;
  - the environment variables the benches read (ENV below) and, for those that name files or
    folders (and their defaults when unset: the BIOS folder, the ROM library, the MAME traces, the
    voice references, IntyBASIC, as1600), the contents of every file in them;
  - Verilator (`$VERILATOR --version`), the C++ compiler (`g++ --version`) and Python's version.
If DIR/<key>/ holds a stored result, its output is printed after one first line
"RUN_CACHE reused ..." and run_cache exits 0. Otherwise CMD runs, its output (stdout and stderr
together) goes to stdout as it comes, run_cache exits with CMD's exit code, and the output is
stored under the key only when CMD exited 0: a FAIL is never stored, so never reused.
"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser('~')
TREES = ('src/fpga', 'sim', 'tools')
# variables the benches read: (name, default path when unset or None, is a path)
ENV = [('VERILATOR', None, False),
       ('INTV_BIOS_DIR', HOME + '/pocket_projects/intellivision/bios', True),
       ('INTV_LIBRARY', HOME + '/ROMLibrary/Intellivision', True),
       ('INTV_TRACE_ROOT', None, True),
       ('INTV_PLAY_ROOT', None, True),
       ('INTV_GAME_DIR', None, True),
       ('INTV_VOICE_REFS', HOME + '/daria_work/intv/step10/refs', True),
       ('INTYBASIC', HOME + '/pocket_projects/intellivision/tools-ext/IntyBASIC/intybasic', True),
       ('INTYBASIC_LIB', None, True),
       ('AS1600', HOME + '/daria_work/intv/refs/jzintv/src-tree/jzintv-20200712-src/bin/as1600', True),
       ('TB_SYSTEM_TIMEOUT', None, False)]


def sh(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout


def file_hash(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def path_hash(p):
    """A file's content, or a folder's files (relative names and contents; links followed)."""
    if os.path.isfile(p):
        return file_hash(p)
    if not os.path.isdir(p):
        return 'missing'
    h = hashlib.sha256()
    for d, dirs, files in os.walk(p, followlinks=True):
        dirs.sort()
        for f in sorted(files):
            q = os.path.join(d, f)
            if os.path.isfile(q):
                h.update(('%s %s\n' % (os.path.relpath(q, p), file_hash(q))).encode())
    return h.hexdigest()


def key_of(argv):
    """(key, inputs) or (None, why not)."""
    top = sh(['git', 'rev-parse', '--show-toplevel']).strip()
    if not top or not os.path.isdir(top):
        return None, 'not in a git work tree'
    dirty = sh(['git', 'status', '--porcelain', '--untracked-files=all', '--'] + list(TREES), cwd=top)
    if dirty.strip():
        return None, 'changes under %s: %s' % (', '.join(TREES), dirty.split('\n')[0].strip())
    inp = {'trees': {t: sh(['git', 'rev-parse', 'HEAD:' + t], cwd=top).strip() for t in TREES},
           'argv': argv, 'cwd': os.path.relpath(os.getcwd(), top), 'env': {}, 'paths': {}}
    for name, default, is_path in ENV:
        v = os.environ.get(name)
        inp['env'][name] = v
        if is_path and (v or default):
            inp['paths'][name] = path_hash(os.path.expanduser(v or default))
    inp['verilator'] = sh([os.environ.get('VERILATOR', 'verilator'), '--version']).strip()
    inp['cxx'] = sh(['g++', '--version']).split('\n')[0]
    inp['python'] = sys.version
    key = hashlib.sha256(json.dumps(inp, sort_keys=True).encode()).hexdigest()
    return key, inp


def main():
    argv = sys.argv[1:]
    if argv[:1] == ['--']:
        argv = argv[1:]
    if not argv:
        sys.exit(__doc__)
    store = os.environ.get('RUN_CACHE')
    if not store:
        os.execvp(argv[0], argv)
    key, inp = key_of(argv)
    if key is None:
        print('RUN_CACHE not used: %s' % inp, flush=True)
    else:
        d = os.path.join(store, key)
        if os.path.isfile(os.path.join(d, 'output.log')) and os.path.isfile(os.path.join(d, 'meta.json')):
            meta = json.load(open(os.path.join(d, 'meta.json')))
            if meta.get('rc') == 0:
                print('RUN_CACHE reused %s: exit 0 on %s after %ds (docs/SIM_SPEED.md 5)' % (
                    key[:16], meta['date'], meta['wall']), flush=True)
                with open(os.path.join(d, 'output.log'), 'rb') as f:
                    shutil.copyfileobj(f, sys.stdout.buffer)
                sys.stdout.flush()
                return 0
    os.makedirs(store, exist_ok=True)
    tmp = os.path.join(store, '.run.%d' % os.getpid())
    t0 = time.time()
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    with open(tmp, 'wb') as f:
        for b in iter(lambda: p.stdout.read1(1 << 16), b''):
            sys.stdout.buffer.write(b)
            sys.stdout.flush()
            f.write(b)
    rc = p.wait()
    if rc == 0 and key is not None:
        d = os.path.join(store, key)
        nd = d + '.new.%d' % os.getpid()
        os.makedirs(nd)
        os.replace(tmp, os.path.join(nd, 'output.log'))
        with open(os.path.join(nd, 'meta.json'), 'w') as f:
            json.dump(dict(inp, rc=rc, wall=int(time.time() - t0),
                           date=datetime.datetime.now().isoformat(timespec='seconds')), f, indent=1)
        try:
            os.rename(nd, d)
        except OSError:                 # stored meanwhile by another run with the same key
            shutil.rmtree(nd, ignore_errors=True)
    else:
        os.remove(tmp)
    return rc


if __name__ == '__main__':
    sys.exit(main())
