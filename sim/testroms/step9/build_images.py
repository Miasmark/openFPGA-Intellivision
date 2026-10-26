#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""The step-9 test cartridges (DESIGN.md 9 step 9, 17, 20), built from the committed
IntyBASIC sources in this directory with IntyBASIC and as1600 (run as programs: INTYBASIC,
AS1600, defaults the owner's builds, as sim/testroms/step8/build_images.py), never
committed themselves:

  ecssound   ecssound.bas: SOUND 5-9 and CONT3, so IntyBASIC boots through the $4800
             hook; its CFG says [vars] ecs = 1 (the ECS flag: Auto -> on)
  ecshook    the same image with the CFG's [vars] taken out: Auto finds the hook's
             word <= $03FF at $4800 (and the header at $500C that starts it straight) -> on
  ecsnohook  ecshook with $1234 (not an opcode) at $4800: -> attached
  ecsavail   ecsavail.bas: no ECS feature, no hook: Auto -> attached, ROMs paged out
  cart4000   cart4000.bas: maps $4000 and $47FF itself: Auto -> off

images(work) returns [dict(name, data, cfg, auto)], auto the mode tools/ecs.py must give.
Run as a script it lists them with the model's Auto mode.
"""
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'mapper'))
import ecs as ecsm  # noqa: E402


def _step8():
    """sim/testroms/step8/build_images.py (its toolchain paths), under its own name."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'step8_build_images', os.path.join(ROOT, 'sim', 'testroms', 'step8', 'build_images.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


b8 = _step8()


def intybasic(src, work):
    """(bin, cfg) of HERE/src through IntyBASIC, then as1600 (as step 8's helper)."""
    import subprocess
    base = os.path.join(work, os.path.splitext(src)[0])
    r = subprocess.run([b8.INTYBASIC, os.path.join(HERE, src), base + '.asm',
                        os.path.dirname(b8.INTYBASIC) + '/'], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0 or 'Compilation finished' not in r.stdout:
        sys.exit('IntyBASIC %s: %s' % (src, r.stdout[-800:]))
    r = subprocess.run([b8.AS1600, '-o', base + '.bin', base + '.asm'], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0 or 'ERRORS DETECTED 0' not in r.stdout:
        sys.exit('as1600 %s: %s' % (src, r.stdout[-800:]))
    return open(base + '.bin', 'rb').read(), open(base + '.cfg', 'rb').read()


def images(work=None):
    work = work or tempfile.mkdtemp(prefix='step9img_')
    os.makedirs(work, exist_ok=True)
    out = []
    d, c = intybasic('ecssound.bas', work)
    out.append(dict(name='ecssound', data=d, cfg=c, auto=ecsm.ON))
    nov = re.sub(rb'\[vars\][^\[]*', b'', c)
    if nov == c:
        sys.exit('ecssound.cfg has no [vars] section')
    out.append(dict(name='ecshook', data=d, cfg=nov, auto=ecsm.ON))
    # the same with a data word ($1234, not an opcode) at $4800: no hook, so attached
    out.append(dict(name='ecsnohook', data=b'\x12\x34' + d[2:], cfg=nov, auto=ecsm.ATTACHED))
    d, c = intybasic('ecsavail.bas', work)
    out.append(dict(name='ecsavail', data=d, cfg=c, auto=ecsm.ATTACHED))
    d, c = intybasic('cart4000.bas', work)
    out.append(dict(name='cart4000', data=d, cfg=c, auto=ecsm.OFF))
    return out


def write(work, img):
    """Write img's .bin and .cfg into work; (bin path, cfg path)."""
    b = os.path.join(work, img['name'] + '.bin')
    c = os.path.join(work, img['name'] + '.cfg')
    open(b, 'wb').write(img['data'])
    open(c, 'wb').write(img['cfg'])
    return b, c


def main():
    import intv_system as isys
    work = tempfile.mkdtemp(prefix='step9img_')
    bad = 0
    for img in images(work):
        b, c = write(work, img)
        cart = isys.load_cart(b, c)
        mode = ecsm.auto_mode(*ecsm.cart_inputs(cart[0]))
        ok = mode == img['auto']
        bad += not ok
        print('%-9s %5d bytes  CFG %s  Auto %s%s' % (img['name'], len(img['data']),
                                                    img['cfg'].decode().replace('\n', ' | ').strip(),
                                                    ecsm.MODE_NAMES[mode], '' if ok else ' FAIL'))
    print('STEP9_IMAGES %s' % ('pass' if not bad else 'FAIL'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
