#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Steps 3-6 bench driver (DESIGN.md 9): the machine RTL against the system model.

"EXEC runs with no cartridge; bus log matches the Python model in lockstep",
plus the save/restore round trip of DESIGN 8.4; from step 4 also the STIC:
its pictures pixel by pixel, its row fetches (cycle, loaded or missed,
address counter, the 20 words) and its card reads (the card row's GROM /
GRAM card or squares), against tools/stic.py in mode "stic" (BUSRQ on, as
the core runs) or "none" (BUSRQ off; image astro_nobusrq); from step 5 the
MOBs in those pictures and every frame's collision bits (the K lines); from
step 6 the PSG: every step's levels and every 48 kHz sample, hashed per
frame (the A lines; samples in straight runs only), and its state words
(docs/PSG_NOTES.md 5; image psgtest, sim/testroms/psgtest.asm). For
each image (no
cartridge; Astrosmash from the owner's library; our sim/testroms/systest.asm
in the EXEC slot; our sim/testroms/carttest.asm with two synthetic
cartridges from tools/synth_image.py, whose CRCs are forced to table
entries with cart RAM and with paged ROM) it

  1. runs tools/intv_system.py (our CP1610 model on the step-3 system bus,
     the same device stubs and frame timing) for 10 frames (systest: 22),
     keeping its bus-phase log, the registers at every step start, every
     change of the STIC's handshake and mode latch, and the machine's
     state at the dump points; for systest, checks that section 7's probes
     land where the program says (the end of the bus-copy window);
  2. runs sim/tb/tb_system.sv (intv_machine with intv_timing, intv_media and
     the SRAM model; the system ROMs and the cartridge loaded through the
     loader's byte port) four times: straight, and with a round trip each
     (restore into a reset machine at a cartridge read or in VBlank; restore
     over a state 20,000 cycles later, which rewinds the run; restore into
     a reset machine outside VBlank; with the display on, restore into a
     reset machine in the middle of a row copy and over a later state from
     inside a BUSRQ, during the card engine's work; with MOBs (step 5),
     restore into a reset machine inside the collision sweep and over a
     later state inside a line's MOB fetch; before each restore every state
     word, and the cart RAM, is overwritten with junk);
  3. compares every run with the model: every bus phase other than NACT
     with its cycle, address and data; R0-R7, S Z O C, I and D at every step
     start; every change of the handshake and the mode latch with its
     cycle; at the dumps, scratchpad, System RAM, GRAM, the STIC and PSG
     registers, the handshake and mode latches, the page selects, the
     STIC's row buffer and FIFO counter; every picture, row fetch, card
     row and frame's collision bits. All runs must also leave every state
     word identical at both dumps. sticmob (sim/testroms/sticmob.asm, the
     step-5 STIC test) checks itself: the model's run must end with its
     fail count 0 after at least one pass (STICMOB_SELFCHECK).
  4. with --mame (or INTV_TRACE_ROOT set): the model against MAME's trace
     of the same image (tools/intv_system.py mame: every read and write and
     every interrupt point equal), so the stubs answer as MAME does.

  python3 -I sim/tb/tb_system.py --all     the step-3/4 gate: the above, then
                                           the planted faults (each must fail)
  python3 -I sim/tb/tb_system.py [--only nocart] [--no-build]
  python3 -I sim/tb/tb_system.py --play [--only astrosmash,b17bomber]
        the step-6 play bench (PLAY): each game started with a key press
        and played with scripted keys (+keys in the bench, press_pads in
        the model; PGA Golf with Pocket buttons through the input model,
        its aim RAM checked, PLAY_PEEKS); RTL = model mode "stic" over every frame as in the
        frame gate; with INTV_PLAY_ROOT (tools/refs/mame_play.sh OUTDIRs)
        also model mode "mame" = MAME's snapshots and PSG log for the same
        keys. Last line "TB_PLAY_ALL pass".
  python3 -I sim/tb/tb_system.py --screens [--only astrosmash,...]
        the frame gate (DESIGN 9 steps 4 and 5): the EXEC without a
        cartridge and with Astrosmash (its title screen), five games and
        the ten MOB games of step 5 (SCREENS), each run as far as the MAME
        snapshots the model was checked against (docs/STIC_NOTES.md 3,
        5.4); every picture, row fetch, card row and frame's collision bits
        of the RTL equal to the model's (mode "stic"), and the CPU bus and
        registers equal frame by frame (a hash per frame: every read of a
        collision register is in it)

Environment: VERILATOR (default verilator), WORK (default sim/work/tb_system),
INTV_LIBRARY (default ~/ROMLibrary/Intellivision), INTV_BIOS_DIR (default
~/pocket_projects/intellivision/bios: exec.bin, grom.bin), INTV_TRACE_ROOT
(MAME traces <root>/<image>/trace.log from tools/refs/mame_trace.sh; the
no-cartridge one with image "none"). Images are extracted into WORK and
deleted after the run; on the owner's VM run this in a simulation slot
(~/daria_work/bin/simslot). The last line is "TB_SYSTEM_ALL pass" or
"TB_SYSTEM_ALL FAIL (...)".
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'mapper'))
import as1610               # noqa: E402
import synth_image          # noqa: E402
import intv_system as isys  # noqa: E402
import stic                 # noqa: E402
import sp0256               # noqa: E402
import intvcart as m        # noqa: E402

CORE = os.path.join(ROOT, 'src', 'fpga', 'core')
RTL = ['intv_jlp_pkg.sv', 'cp1610.sv', 'intv_bus.sv', 'intv_stic.sv', 'intv_psg.sv', 'intv_ram.sv',
       'intv_machine.sv', 'intv_timing.sv', 'intv_sram.sv', 'intv_cart.sv', 'intv_sysrom.sv',
       'intv_loader.sv', 'intv_cfgparse.sv', 'intv_romparse.sv', 'intv_pagesel.sv', 'intv_media.sv',
       'intv_ecs.sv', 'sp0256.sv', 'intv_voice.sv', 'intv_jlp.sv']
INC = ['sp0256_fmt.svh']             # included by sp0256.sv (tools/sp0256.py gen)
OTHER = [os.path.join(HERE, 'models', 'sram_as6c2016.sv'), os.path.join(HERE, 'tb_system.sv')]

FRAME = isys.FRAME
# MOBs and collisions (build step 5): on in the model as in the RTL.
# False runs the model with backgrounds only (tools/stic.py Stic.mobs), as
# the step-4 RTL drew.
STIC_MOBS = True
NCYC = 10 * FRAME
DUMP1 = 5 * FRAME + 8000
# (name, cartridge: a file in the library or ('forced', CRC, bytes) from
# tools/synth_image.py, program for the EXEC slot instead of exec.bin,
# frames, hand controllers (right, left), STIC mode: 'stic' = BUSRQ on (the
# core), 'none' = off (+busrq=0))
IMAGES = [('nocart', None, None, 10, (0xFF, 0xFF), 'stic'),
          ('astrosmash', 'Astrosmash (USA, Europe).zip', None, 10, (0xFF, 0xFF), 'stic'),
          ('astro_nobusrq', 'Astrosmash (USA, Europe).zip', None, 10, (0xFF, 0xFF), 'none'),
          # systest's probe delays are tuned for the step-3 system (no BUSRQ;
          # it enables the display, so BUSRQ would move them)
          ('systest', None, 'systest.asm', 22, (0x5A, 0xC3), 'none'),
          # step 4: our STIC test (sim/testroms/sticbus.asm), BUSRQ on
          ('sticbus', None, 'sticbus.asm', 24, (0xFF, 0xFF), 'stic'),
          # step 5: our MOB test (sim/testroms/sticmob.asm), BUSRQ on
          ('sticmob', None, 'sticmob.asm', 46, (0xFF, 0xFF), 'stic'),
          # step 6: our PSG test (sim/testroms/psgtest.asm)
          ('psgtest', None, 'psgtest.asm', 22, (0x5A, 0xC3), 'stic'),
          ('cartram', ('forced', 0xCE8FC699, 49152), 'carttest.asm', 10, (0xFF, 0xFF), 'stic'),
          ('cartpaged', ('forced', 0xC2063C08, 49152), 'carttest.asm', 10, (0xFF, 0xFF), 'stic'),
          # step 8: our cart8test.asm on an Intellicart .rom and on a BIN + CFG, both built
          # from our sources (sim/testroms/step8/build_images.py, as1600)
          ('cartbank', ('step8', 'rombank'), 'cart8test.asm', 10, (0xFF, 0xFF), 'stic'),
          ('cartcfg', ('step8', 'cfgmap'), 'cart8test.asm', 10, (0xFF, 0xFF), 'stic'),
          # step 9: the ECS (ECS_OF: the menu override and the keys); our sim/testroms/ecstest.asm
          # in the EXEC slot with the keyboard and with the synthesizer, the real EXEC with the
          # ECS's boot, Astrosmash under the Auto rule, our step-9 cartridges
          # (sim/testroms/step9/build_images.py)
          ('ecstest', None, 'ecstest.asm', 12, (0xFF, 0xFF), 'stic'),
          ('ecssynth', None, 'ecstest.asm', 12, (0xFF, 0xFF), 'stic'),
          ('ecstest_off', None, 'ecstest.asm', 12, (0xFF, 0xFF), 'stic'),
          ('ecsboot', None, None, 10, (0xFF, 0xFF), 'stic'),
          ('ecsastro', 'Astrosmash (USA, Europe).zip', None, 10, (0xFF, 0xFF), 'stic'),
          ('ecssound', ('step9', 'ecssound'), None, 30, (0xFF, 0xFF), 'stic'),
          ('ecssound_l4', ('step9', 'ecssound'), None, 30, (0xFF, 0xFF), 'stic'),
          ('ecshook', ('step9', 'ecshook'), None, 30, (0xFF, 0xFF), 'stic'),
          ('ecsavail', ('step9', 'ecsavail'), None, 30, (0xFF, 0xFF), 'stic'),
          ('cart4000', ('step9', 'cart4000'), None, 30, (0xFF, 0xFF), 'stic'),
          ('cart4000_on', ('step9', 'cart4000'), None, 30, (0xFF, 0xFF), 'stic'),
          # the step-9 review: ecstest with the ECS on and no ECS ROM slot ($2000, $7000, $E000
          # read $FFFF on every page); library games under Auto with the ECS attached, the
          # hardware's default (Super NFL Football writes the ECS RAM from frame 14; Atlantis
          # boots through its $4800 hook; Body Slam, a Super Pro title, clears $00E0-$00FF, the
          # UART stub and PSG #2, in frame 4)
          ('ecsnorom', None, 'ecstest.asm', 12, (0xFF, 0xFF), 'stic'),
          ('nfl_auto', 'Super NFL Footbal (USA) (Proto).zip', None, 24, (0xFF, 0xFF), 'stic'),
          ('atlantis_auto', 'Atlantis (USA, Europe).zip', None, 10, (0xFF, 0xFF), 'stic'),
          ('bodyslam_auto', 'Body Slam! - Super Pro Wrestling (USA).zip', None, 10, (0xFF, 0xFF), 'stic'),
          # step 10: the Intellivoice (VOICE_OF): our sim/testroms/voicetest.py in the EXEC slot with the
          # voice on (clean sound at the default level; the 7-bit DAC sound at 3/2) and forced off
          ('voicetest', None, 'voicetest.py', 30, (0xFF, 0xFF), 'stic'),
          ('voicedac', None, 'voicetest.py', 16, (0xFF, 0xFF), 'stic'),
          ('voice_off', None, 'voicetest.py', 10, (0xFF, 0xFF), 'stic'),
          ('voicemix', None, 'voicemix.asm', 24, (0xFF, 0xFF), 'stic')]
# step 11: the JLP measurement cartridges (sim/testroms/jlp/build_jlp.py, docs/JLP_NOTES.md 4): each
# runs its table of JLP reads, writes and flash commands at start-up and keeps the results in
# System RAM ($0300 on), which the state dumps compare (RTL = model); the model = jzIntv on
# every data word (JLP_NOTES 4.1)
JLP_IMAGES = [(n, ('jlp', n), None, 40, (0xFF, 0xFF), 'stic')
              for n in ('jlpmap', 'jlpmul', 'jlpdiv', 'jlpfls', 'jlpena', 'jlpf1', 'jlpm1', 'jlpfz')]
IMAGES += JLP_IMAGES
# the hardware measurement cartridges (sim/testroms/hw/build_hw.py, docs/HW_TESTS.md): RTL = model on
# the owner's test programs before they go to his console. Long runs (hundreds of frames, to their
# results screens), so only by name (--only hw_steal,...), never in --all
HW_IMAGES = [('hw_steal', ('hw', 'hw_steal'), None, 460, (0xFF, 0xFF), 'stic'),
             ('hw_intlate', ('hw', 'hw_intlate'), None, 230, (0xFF, 0xFF), 'stic'),
             ('hw_rowcopy', ('hw', 'hw_rowcopy'), None, 1150, (0xFF, 0xFF), 'stic'),
             ('hw_cpuodd', ('hw', 'hw_cpuodd'), None, 60, (0xFF, 0xFF), 'stic'),
             ('hw_ecskeys', ('hw', 'hw_ecskeys'), None, 60, (0xFF, 0xFF), 'stic')]
# step 10: the Intellivoice of an image: the menu override ('on', 'off'), level, DAC sound. Images
# not listed run with it Off (the RTL's override 2; the model without one)
VOICE_OF = {'voicetest': dict(ovr='on', level=4, dac=False),
            'voicedac': dict(ovr='on', level=3, dac=True),
            'voice_off': dict(ovr='off', level=4, dac=False),
            'voicemix': dict(ovr='on', level=4, dac=False)}


def ivoice_rom():
    d = os.environ.get('INTV_BIOS_DIR', os.path.expanduser('~/pocket_projects/intellivision/bios'))
    for n in ('ivoice.bin', 'IVOICE.BIN'):
        if os.path.exists(os.path.join(d, n)):
            return os.path.join(d, n)
    return None


# a cartridge file's CFG (step 8): the model and the bench load it with the image
CFG_OF = {}
# step 9: the ECS of an image: the menu override ('auto', 'on', 'off'), the synthesizer,
# scripted ECS keys (intv_system.parse_presses "ecs:" / "synth:"), the Auto mode the image
# must get (tools/ecs.py; the RTL's L line too) and the BACKTAB lines its program prints
# PASS on (rows 2-4: the step-9 cartridges). Images not listed run without the ECS (the
# RTL with the override Off).
ECSTEST_KEYS = ('1-2:ecs:W,2-3:ecs:W+Q,3-4:ecs:W+Q+1,4-5:ecs:SHIFT+L,5-6:ecs:SHIFT+K,'
                '6-7:ecs:LEFT+N,7-8:ecs:Q+1')
ECSSYNTH_KEYS = '1-2:synth:0+8,2-3:synth:0+8+9,3-4:synth:36'
ECS_OF = {
    'ecstest': dict(ovr='auto', synth=False, presses=ECSTEST_KEYS, auto=1),
    'ecssynth': dict(ovr='auto', synth=True, presses=ECSSYNTH_KEYS, auto=1),
    'ecstest_off': dict(ovr='off', auto=1),     # the same program with the ECS forced off: nothing answers
    'ecsboot': dict(ovr='auto', auto=1),
    'ecsastro': dict(ovr='auto', auto=2),
    'ecssound': dict(ovr='auto', auto=1, passes=(2, 3)),
    'ecssound_l4': dict(ovr='auto', auto=1, passes=(2, 3), level=4),   # the ECS level at Loudest (x2)
    # voicemix (sim/testroms/voicemix.asm, the EXEC slot, no cartridge: Auto would be on): both PSGs
    # at full volume and the voice at Loudest, so the sum is clipped at 32,767 (intv_machine)
    'voicemix': dict(ovr='on', auto=1),
    # hw_ecskeys (attached under Auto): one key, a row pair, three corners, Shift + a key; its
    # results are on screen, not in ecstest's scan table (scans=False)
    'hw_ecskeys': dict(ovr='auto', auto=2, scans=False, presses='20-28:ecs:W,28-36:ecs:W+Q,36-44:ecs:W+Q+1,'
                                                    '44-52:ecs:SHIFT+L'),
    'ecshook': dict(ovr='auto', auto=1, passes=(2, 3)),
    'ecsavail': dict(ovr='auto', auto=2, passes=(2, 3, 4)),
    'cart4000': dict(ovr='auto', auto=0, passes=(2, 3)),
    'cart4000_on': dict(ovr='on', auto=0),      # forced on: the ECS RAM, not the cartridge, at $4000
    'ecsnorom': dict(ovr='on', auto=1, norom=True),     # no ECS ROM slot: the ROMs never answer
    'nfl_auto': dict(ovr='auto', auto=2),
    'atlantis_auto': dict(ovr='auto', auto=2),
    'bodyslam_auto': dict(ovr='auto', auto=2),
}
ECS_OVR = {'auto': 0, 'on': 1, 'off': 2}
# ecstest's ISR scans, written out from DESIGN 7.3's rule (not from tools/ecs.py): per key
# combination, the 22 words it stores: rows 0-7 scanned (port A out, one line low; port B
# read), columns 0-7 scanned (port B out; port A read), both ports out with A = $EF, B = $F7
# (A, B read), then A = $EF, B = $FF, then both in. Every read is $FF00 | the lines.
_N = [0xFF] * 8


def _scan(rows=None, cols=None, b1=(0xEF, 0xF7), b2=(0xEF, 0xFF)):
    r, c = list(_N), list(_N)
    for k, v in (rows or {}).items():
        r[k] = v
    for k, v in (cols or {}).items():
        c[k] = v
    return [0xFF00 | x for x in r + c + list(b1) + list(b2) + [0xFF, 0xFF]]


ECSKBD_WANT = {
    'none': _scan(),
    'W': _scan({4: 0xF7}, {3: 0xEF}, (0xEF, 0xF7), (0xFF, 0xFF)),
    'W+Q': _scan({}, {3: 0xCF}, (0xFF, 0xFF), (0xFF, 0xFF)),            # one column: masked
    'W+Q+1': _scan({}, {}, (0xFF, 0xFF), (0xFF, 0xFF)),                # three corners: no ghost
    'SHIFT+L': _scan({}, {7: 0xBD}),                                   # Shift can't upper-case L
    'SHIFT+K': _scan({1: 0xFB, 6: 0x7F}, {2: 0xFD, 7: 0xBF}),
    'LEFT+N': _scan({}, {0: 0xFA}),
    'Q+1': _scan({5: 0xE7}, {}, (0xEF, 0xFF), (0xEF, 0xFF)),           # one row: masked transposed
    # the synthesizer (diodes): columns pulled low by keys on a low row; no transposed path
    'synth:0+8': _scan({0: 0xFE, 1: 0xFE}),
    'synth:0+8+9': _scan({0: 0xFE, 1: 0xFC}),
    'synth:36': _scan({4: 0xEF}, {}, (0xEF, 0xE7), (0xEF, 0xEF)),
}


def step8_image(name, work):
    """(image path, CFG path or None) of a step-8 test image, written into work."""
    sys.path.insert(0, os.path.join(ROOT, 'sim', 'testroms', 'step8'))
    import build_images
    import cartfmt
    for im in build_images.images():
        if im['name'] == name:
            path = os.path.join(work, name + ('.rom' if cartfmt.is_rom(im['data']) else '.bin'))
            with open(path, 'wb') as f:
                f.write(im['data'])
            cpath = None
            if im['cfg'] is not None:
                cpath = os.path.join(work, name + '.cfg')
                with open(cpath, 'wb') as f:
                    f.write(im['cfg'])
            CFG_OF[path] = cpath
            return path, cpath
    sys.exit('no step-8 image %s' % name)


def step9_image(name, work):
    """The image path of a step-9 test cartridge (sim/testroms/step9), written into work
    with its CFG (CFG_OF)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'step9_build_images', os.path.join(TESTROMS, 'step9', 'build_images.py'))
    b9 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b9)
    if not hasattr(step9_image, 'cache'):
        step9_image.cache = {i['name']: i for i in b9.images(os.path.join(work, 'step9_build'))}
    path, cfg = b9.write(work, step9_image.cache[name])
    CFG_OF[path] = cfg
    return path


def hw_image(name, work):
    """The image path of a hardware measurement cartridge (sim/testroms/hw/build_hw.py), built
    into work with its CFG (CFG_OF)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('build_hw', os.path.join(TESTROMS, 'hw', 'build_hw.py'))
    bh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bh)
    _, image, cfg = bh.build_one(name)
    path, cpath = os.path.join(work, name + '.bin'), os.path.join(work, name + '.cfg')
    with open(path, 'wb') as f:
        f.write(image)
    with open(cpath, 'w') as f:
        f.write(cfg)
    CFG_OF[path] = cpath
    return path


def jlp_image(name, work):
    """The image path of a JLP measurement cartridge (sim/testroms/jlp/build_jlp.py), built
    into work with its CFG (CFG_OF)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('build_jlp', os.path.join(TESTROMS, 'jlp', 'build_jlp.py'))
    bj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bj)
    _, image, cfg = bj.build_one(name)
    path, cpath = os.path.join(work, name + '.bin'), os.path.join(work, name + '.cfg')
    with open(path, 'wb') as f:
        f.write(image)
    with open(cpath, 'w') as f:
        f.write(cfg)
    CFG_OF[path] = cpath
    return path


def ecs_selfcheck(name, e):
    """Step 9: the model's ECS mode is the image's Auto mode; ecstest / ecssynth stored the
    scans ECSKBD_WANT has for the keys held in each ISR's frame; the step-9 cartridges printed
    PASS on their result rows (BACKTAB) by the end."""
    import ecs as ecsm
    want = e.ecs
    probs = []
    dev = e.bus.ecs
    mode = want['auto'] if want['ovr'] == 'auto' else {'on': ecsm.ON, 'off': ecsm.OFF}[want['ovr']]
    if dev is None or dev.mode != mode or ecsm.auto_mode(*ecsm.cart_inputs(e.bus.cart)) != want['auto']:
        probs.append('mode %s (Auto %s), want %s' % (dev and ecsm.MODE_NAMES[dev.mode], ecsm.MODE_NAMES[want['auto']],
                                                     ecsm.MODE_NAMES[mode]))
    if want.get('norom'):
        # no ECS ROM slot: every read of $2000, $7000 and $E000 (ecstest reads each on several
        # pages) gives $FFFF, nothing answers there (step-9 review)
        for a in (0x2000, 0x7000, 0xE000):
            vals = [d for c, ph, ad, d in e.blog if ph == PHASE['DTB'] and ad == a]
            if not vals or any(v != 0xFFFF for v in vals):
                probs.append('no ECS ROM: $%04X read %s, want $FFFF' % (a, ' '.join('$%04X' % v for v in vals) or 'never'))
    ram = e.snaps[e.ncyc]['sysram']
    if want.get('presses') and want.get('scans', True):     # ecstest's / ecssynth's scan table
        presses = isys.parse_presses(want['presses'])
        names = {}
        for f1, f2, (_, bits) in presses:
            for k in range(f1 + 1, f2 + 1):
                txt = [x for x in want['presses'].split(',') if x.startswith('%d-%d:' % (f1, f2))][0]
                names[k] = txt.split(':', 1)[1].replace('ecs:', '')
        intak = [c for c, ph, a, d in e.blog if ph == PHASE['INTAK']]
        for k in range(1, 10):
            if k > len(intak):
                probs.append('ISR %d never ran' % k)
                break
            combo = names.get(intak[k - 1] // FRAME, 'none')
            got = ram[32 * k:32 * k + 22]
            if got != ECSKBD_WANT[combo]:
                probs.append('ISR %d (frame %d, keys %s): %s, want %s' % (
                    k, intak[k - 1] // FRAME, combo, ' '.join('%X' % x for x in got),
                    ' '.join('%X' % x for x in ECSKBD_WANT[combo])))
    for row in want.get('passes', ()):
        text = ''.join(chr(((w >> 3) & 0xFF) + 32) if not w & 0x800 and ((w >> 3) & 0xFF) < 95 else '.'
                       for w in ram[20 * row:20 * row + 20])
        if 'PASS' not in text:
            probs.append('row %d: %r' % (row, text))
    return probs


def cart8_selfcheck(e, cart_path):
    """cart8test.asm's results against the image itself (not the model): section 2's
    windows after $0046 = $10 read the Intellicart words at $1000/$1001 (rombank), after
    $0046 = $80 the RAM section 1 wrote at $8000; the 8-bit RAM keeps the low byte; past the
    CFG's 8-bit RAM ($9003, cfgmap) nothing answers. Section 3's last four writes must not
    select a page: their reads equal those after the selects went back to page 0."""
    import cartfmt
    ram = e.snaps[e.ncyc]['sysram']
    res = ram[0x10:]                       # $0210 on
    data = open(cart_path, 'rb').read()
    probs = []
    s1 = res[:14]
    v = [(0xA55A + k * 0x1111) & 0xFFFF for k in range(14)]
    if not cartfmt.is_rom(data):
        want = {0: v[0], 1: v[1], 2: 0xFFFF, 3: 0xFFFF, 5: v[5] & 0xFF, 6: v[6] & 0xFF, 7: 0xFFFF,
                8: v[8], 9: 0x5000 ^ 0x1111, 10: 0xFFFF, 11: 0xFFFF, 12: 0xD150 ^ 0x4444}
    else:
        want = {0: v[0], 1: v[1], 2: v[2], 3: v[3] & 0xFF, 4: v[4] & 0xFF, 5: 0xFFFF, 11: 0xFFFF}
    for k, w in want.items():
        if s1[k] != w:
            probs.append('section 1 word %d = $%04X, want $%04X' % (k, s1[k], w))
    s3 = res[14 + 8 * 5:14 + 8 * 5 + 13 * 6]
    for k in range(9, 13):
        if s3[6 * k:6 * k + 6] != s3[6 * 8:6 * 8 + 6]:
            probs.append('section 3 write %d selected a page' % (k + 1))
    if cartfmt.is_rom(data):
        p = cartfmt.parse_rom(data)
        icart = dict(p.writes)
        s2 = res[14:14 + 8 * 5]
        if (s2[0], s2[1]) != (icart.get(0x1000), icart.get(0x1001)):
            probs.append('bank $10: $6000/$6001 = $%04X/$%04X, image $1000/$1001 = %s' % (
                s2[0], s2[1], (icart.get(0x1000), icart.get(0x1001))))
        if s2[3 * 5] != v[0]:
            probs.append('bank $80: $6000 = $%04X, want the RAM word $A55A' % s2[3 * 5])
        if s2[4 * 5 + 3] != v[3] & 0xFF:
            probs.append('bank $88 ($6800): $%04X, want the 8-bit cell $%02X' % (s2[4 * 5 + 3], v[3] & 0xFF))
    return probs
# the step-4 frame gate: (name, library file or None, pictures)
SCREENS = [('nocart', None, 600),
           ('astrosmash', 'Astrosmash (USA, Europe).zip', 700),
           ('towerofdoom', 'Tower of Doom (USA).zip', 700),
           ('diner', 'Diner (USA).zip', 300),
           ('digdug', 'Dig Dug (USA).zip', 700),
           ('sewersam', 'Sewer Sam (USA).zip', 300),
           ('solarsailer', 'TRON Solar Sailer (USA, Europe).zip', 700),
           # step 5: the ten MOB games (docs/STIC_NOTES.md 5.4), as far as their MAME snapshots
           ('atlantis', 'Atlantis (USA, Europe).zip', 700),
           ('demonattack', 'Demon Attack (USA, Europe).zip', 700),
           ('mte201', 'MTE201 Intellivision Test Cartridge (USA).zip', 900),
           ('buzzbombers', 'Buzz Bombers (USA, Europe).zip', 700),
           ('centipede', 'Centipede (USA).zip', 700),
           ('defender', 'Defender (USA).zip', 700),
           ('dracula', 'Dracula (USA, Europe).zip', 700),
           ('dragonfire', 'Dragonfire (USA, Europe).zip', 700),
           ('icetrek', 'Ice Trek (USA, Europe).zip', 700),
           # step 8: our Pocket test cartridges (IntyBASIC; BIN + CFG with pages and RAM,
           # .rom with bank windows and RAM) with the real EXEC, through their checks
           ('cart8pages', ('step8', 'cart8pages'), 200),
           ('cart8bank', ('step8', 'cart8bank'), 200),
           ('tropicaltrouble', 'Tropical Trouble (USA, Europe).zip', 700)]
# the play bench (step 6, --play): each game started with a key press and
# played for a few seconds with the same scripted keys on both hand
# controllers (F1-F2:KEY held from MAME frame notifier F1 until F2; MAME's
# field names, intv_system.KEYCODE). The RTL against the model in mode
# "stic" over every frame; with INTV_PLAY_ROOT (tools/refs/mame_play.sh
# OUTDIRs, <root>/<name>) also the model in mode "mame" against MAME's
# snapshots (every 10th frame) and PSG log for the same keys. Astrosmash:
# 1 starts the game, then fire, left, right, diagonals; B-17 Bomber: 1, Enter
# for the map, the disc moves the bomber, 0 takes off, then the disc moves
# the bombsight and the side buttons fire.
PLAY = [('astrosmash', 'Astrosmash (USA, Europe).zip', 1200,
         '200-206:1,300-400:Upper,400-480:Left,480-600:Right,600-700:Lower-Right,'
         '700-760:Up-Left,800-900:Upper,900-960:Down-Right'),
        ('b17bomber', 'B-17 Bomber (USA, Europe).zip', 1300,
         '200-206:1,500-506:Enter,600-630:Right,700-730:Down,800-806:0,900-960:Left,'
         '1000-1040:Upper,1100-1160:Up,1200-1240:Lower-Right'),
        ('golf', 'PGA Golf ~ Golf (World).zip', 760,
         '120-125:Enter,180-185:1,240-245:Enter,400-405:1,'
         '500-510:pocket:right,560-570:pocket:L+right,620-630:pocket:up,680-690:pocket:L+up')]
# PGA Golf (the owner's Precision controls, 2026-10-26; research/golf/NOTES.md): the start sequence
# recorded in MAME (Enter, 1 player, Enter, club 1 = driver), then the Pocket's D-pad through the input
# model (intv_system "pocket:" presses: Layer mode, L turns the D-pad one notch clockwise), each held
# 10 frames: Right, L+Right, Up, L+Up must set the aim, RAM $015F (right = 0, counter-clockwise), to
# 0, 15, 4, 3 (the aim is stored about 12 frames after the press); read 40 frames after each press.
# No MAME reference run for it here: the measurement of the 16 aims in MAME is in that note.
# Build step 9, the ECS gate (--ecs-play): RTL = model frame by frame (as the play bench) over
# the runs checked against MAME's intvecs (tools/refs/ecs_ref_compare.py, the same keys:
# tools/refs/mame_ecs_trace.sh), plus Astrosmash under the Auto rule and our ecssound cartridge.
# (name, cartridge (library file, ('step9', name) or None), frames, keys, ECS_OF-style entry)
def _typed(start, text):
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import ecs as ecsm
    return ecsm.type_presses(start, text)[0]


ECS_PLAY = [
    ('ecsbasic', None, 1200, '300-306:Enter,420-426:1,500-506:Enter,' + _typed(800, '10 PRINT 2*3\nRUN\n'),
     dict(ovr='auto')),
    ('mindstrike', 'Mind Strike (USA, Europe).zip', 2000,
     '300-306:ecs:RTN,600-606:ecs:1,750-756:ecs:RTN,900-906:ecs:1,1000-1006:ecs:RTN,1300-1360:Right,'
     '1500-1560:Up,1700-1760:Left,1900-1906:Upper', dict(ovr='auto')),
    ('wsmlb', 'World Series Major League Baseball (USA).zip', 3200,
     '300-306:ecs:RTN,600-606:ecs:1,900-906:ecs:SPACE,1200-1206:Enter,1500-1506:ecs:E,1800-1806:1,'
     '2000-2006:Enter,2200-2260:Right,2400-2406:Upper,2600-2606:2,2800-2806:Enter,3000-3006:Lower-Right',
     dict(ovr='auto')),
    ('melody', 'Melody Blaster (USA, Europe).zip', 3200,
     '300-306:Enter,420-426:2,500-506:Enter,1500-1506:Enter,1800-1830:synth:0,1900-1930:synth:19,'
     '2000-2030:synth:24,2400-2406:1,2600-2606:Enter,2900-2930:synth:28,3000-3030:synth:36',
     dict(ovr='auto', synth=True)),
    ('mrbasic', "Mr. BASIC Meets Bits 'N Bytes (USA).zip", 2600,
     '300-306:Enter,420-426:2,500-506:Enter,1500-1506:Enter,1800-1806:3,1900-1906:Enter,' + _typed(2300, 'PRINT 5\n'),
     dict(ovr='auto')),
    ('astro_auto', 'Astrosmash (USA, Europe).zip', 700,
     '200-206:1,300-400:Upper,400-480:Left,480-600:Right,600-700:Lower-Right', dict(ovr='auto')),
    ('ecssound', ('step9', 'ecssound'), 600, '', dict(ovr='auto')),
    # ECS BASIC's CALL GRAB copies a MOB picture from the cartridge in the slot (the 1998 contest's
    # Bomb Run I, lines 140-180, with AD&D Cloudy Mountain; research/ecs-basic, owner 2026-10-27):
    # ECS forced on (Auto attaches it with its menu skipped), the ECS menu's 1, then the lines typed
    # without commas (the press list is comma-separated: DATA 0,7,0,0 / READ D,N,M,O give D=0, N=7,
    # M=0, O=0) and RUN; MOB 0 then shows GRAM card 62 = the cartridge's $53F5 picture (the boat).
    # MAME's intvecs agrees instruction by instruction and on 4 snapshots (ecs_ref_compare, 2026-10-29).
    ('grab', 'Advanced Dungeons & Dragons (USA, Europe).zip', 2056,
     '300-306:Enter,420-426:1,500-506:Enter,'
     + _typed(800, '140 D=0\n150 N=7\n160 M=0\n170 O=0\n180 CALL GRAB\n190 CO(0)=11\n200 XS(0)=1\n210 GOTO 210\nRUN\n'),
     dict(ovr='on')),
]

PLAY_PEEKS = {'golf': [(540, 0x015F, 0), (600, 0x015F, 15), (660, 0x015F, 4), (720, 0x015F, 3)]}
PLAY_SNAP_STEP = 10
PIC_W, PIC_H = 189, 240
PIC_BYTES = 4 + PIC_W * PIC_H // 2
KIND = {'GROM': 0, 'GRAM': 1, 'squares': 2}
FNV0, FNVP = 0x811C9DC5, 0x01000193
# systest section 7: (phase, address, frame slot) of each probe
SECT7 = [('DW', 0x002B, 3788), ('DTB', 0x3850, 3789), ('DTB', 0x002A, 3790), ('DW', 0x3851, 3791),
         ('DW', 0x3852, 3789), ('DW', 0x0030, 3790), ('DTB', 0x002B, 3789), ('DTB', 0x3E53, 3790),
         ('DW', 0x4018, FRAME - 1)]          # p11: $18 written in a display-off frame's last slot
SECT7_START = 7 * FRAME
TESTROMS = os.path.join(ROOT, 'sim', 'testroms')
PHASE = {'NACT': 0, 'ADAR': 1, 'IAB': 2, 'DTB': 3, 'BAR': 4, 'DW': 5, 'DWS': 6, 'INTAK': 7}
SS = {'cpu': 0x02, 'bus': 0x03, 'stic': 0x04, 'psg': 0x05, 'scr': 0x06, 'sys': 0x07,
      'gram': 0x09, 'cart': 0x0B, 'row': 0x0C, 'line': 0x0D, 'ecs': 0x0E, 'psg2': 0x0F, 'eram': 0x10,
      'voice': 0x18, 'jlp': 0x20}


# ------------------------------------------------------------------- model
class Exp:
    """The model's expectations for one image."""

    def __init__(self, blog, steps, snaps, bus, mlog, ncyc, pics=None, sinfo=None, mode='stic'):
        self.blog, self.steps, self.snaps, self.bus = blog, steps, snaps, bus
        self.mlog, self.ncyc = mlog, ncyc
        self.pics, self.sinfo, self.mode = pics or {}, sinfo or {}, mode
        self.name = None
        self.ecs = None                 # ECS_OF's entry (step 9)
        self.ecs_audio = {}             # PSG #2 and the mix by frame (E lines)
        self.voice = None               # VOICE_OF's entry (step 10)
        self.vsamples = []              # the model's voice samples [(cycle fired, sample)]


def stic_expect(info):
    """What the RTL's G / GW, C and K lines should say for one frame: row
    fetches [(r, ok, counter, words or None)], cards [(row, col, kind,
    base)] and the 8 collision words the frame gathers (tools/stic.py
    on_frame info)."""
    rows = info['rows']
    g = sorted((r, int(ok), addr, tuple(rows[r]) if ok else None)
               for r, rel, ok, addr in info['fetches'])
    c = [(row, col, KIND[k], base or 0) for row, col, k, base in info['cards']]
    return g, c, tuple(info['coll'])


def capture(bus):
    """Collect the model's pictures and STIC logs by picture number."""
    pics, sinfo = {}, {}

    def on_frame(n, pic, info):
        pics[n] = bytes(pic)
        sinfo[n] = stic_expect(info)
        bus.moblog[n] = list(info['mobs'])
        # BUSAK against the row's fetch cycle R + 57 (sticbus's deadline cases)
        for r, rel, ok, _ in info['fetches']:
            if rel is not None and r < 13:
                fc = stic.ROW0_REQ + 2 * stic.LINE * info['vdr'] + stic.ROW_PERIOD * r + stic.LINE
                bus.deadline.append((n, r, rel - fc, ok))
    bus.deadline = []
    bus.moblog = {}
    bus.vid.keep_frames = set()
    bus.vid.on_frame = on_frame
    return pics, sinfo


def ecs_device(cart, ecs):
    """The model's ECS for an ECS_OF entry (None: no ECS, the RTL's override Off)."""
    if not ecs:
        return None
    dev = isys.make_ecs(cart[0] if cart else None, (ecs['ovr'], '' if ecs.get('norom') else None))
    dev.synth = bool(ecs.get('synth'))
    return dev


def model_run(exec_path, grom_path, cart_path, ncyc=NCYC, pads=(0xFF, 0xFF), mode='stic', ecs=None, voice=None):
    """The model's expected log: bus phases, step starts, handshake and mode
    latch changes, state at the dumps, pictures and STIC logs. ecs: an
    ECS_OF entry (step 9); voice: a VOICE_OF entry (step 10)."""
    cart = isys.load_cart(cart_path, CFG_OF.get(cart_path))
    vdev = None
    if voice:
        vdev = sp0256.VoiceBus(open(ivoice_rom(), 'rb').read(), on=voice['ovr'] == 'on')
    bus = isys.SystemBus(isys.load_words(exec_path), open(grom_path, 'rb').read(),
                         cart[0] if cart else None, stic_mode=mode, ecs=ecs_device(cart, ecs), voice=vdev,
                         jlp=isys.make_jlp(cart[0] if cart else None))
    bus.vid.mobs = STIC_MOBS
    bus.pad = tuple(pads)
    if ecs and ecs.get('presses'):
        bus.presses = isys.parse_presses(ecs['presses'])
    cpu = isys.CP1610(bus=bus, buslog=True)
    pics, sinfo = capture(bus)
    snaps = {}
    want = [DUMP1, ncyc]
    orig_r, orig_w = bus.read, bus.write
    # {hs, csmode} during each cycle, as changes: the RTL changes them at the
    # ce that ends a read (DTB / ADAR) or DW cycle c, so the new value holds
    # from cycle c + 1; a frame start clears the handshake
    mlog = []
    mst = {'last': (0, 0), 'frame': 1}

    def mval(t):
        return (int(bus.handshake(t)), bus.csmode)

    def mpush(t, v):
        if v != mst['last']:
            mlog.append((t,) + v)
            mst['last'] = v

    def advance(c):
        while mst['frame'] * FRAME <= c:
            t = mst['frame'] * FRAME
            mpush(t, mval(t))
            mst['frame'] += 1

    def snap(cycle):
        while want and cycle >= want[0]:
            snaps[want[0]] = bus.state(want[0])
            want.pop(0)

    def rd(addr, cycle, kind='data'):
        snap(cycle)
        advance(cycle)
        v = orig_r(addr, cycle, kind)
        mpush(cycle + 1, mval(cycle + 1))
        return v

    def wr(addr, value, cycle):
        snap(cycle)
        advance(cycle)
        orig_w(addr, value, cycle)
        mpush(cycle + 1, mval(cycle + 1))

    bus.read, bus.write = rd, wr
    audio = psg_hooks(bus)
    ecs_audio = psg2_hooks(bus, (ecs or {}).get('level', 2))
    steps = []
    prev = (list(cpu.r), cpu.flags << 2 | cpu.I << 1 | cpu.D)
    while cpu.cycle < ncyc:
        ev = cpu.step()
        bus.boundary(cpu.cycle)
        if ev.kind in ('insn', 'intr') and ev.cycle > 0:
            steps.append((ev.cycle, prev[0], prev[1]))
        prev = (list(ev.regs), ev.flags << 2 | ev.i << 1 | ev.d)
    snap(ncyc)
    bus.snd.advance(ncyc - 1)
    if bus.ecs is not None and bus.ecs.on:
        bus.ecs.psg.advance(ncyc - 1)
    bus.vid.advance(ncyc + FRAME)     # draw the last frame
    if vdev is not None and vdev.on:
        vdev.run_to(ncyc)
    advance(ncyc - 1)
    blog = [(c, PHASE[p], a or 0, d or 0) for (c, p, a, d) in cpu.buslog
            if c < ncyc and p != 'NACT']
    steps = [s for s in steps if s[0] < ncyc]
    mlog = [x for x in mlog if x[0] < ncyc]
    exp = Exp(blog, steps, snaps, bus, mlog, ncyc, pics, sinfo, mode)
    exp.audio = audio
    exp.ecs = ecs
    exp.ecs_audio = ecs_audio.done()
    exp.mix_raw = ecs_audio
    exp.voice = voice
    exp.vsamples = [x for x in vdev.samples if x[0] < ncyc] if vdev is not None else []
    return exp


def psg_hooks(bus):
    """The PSG's per-frame fingerprint as the bench's A lines give it:
    {k: [ha, na, hq, nq, steps with a level]} over the steps that end
    cycles of frame k (each step's levels before it, A | B << 4 | C << 8)
    and the 48 kHz samples they end (tools/psg.py: steps end cycles 0, 4,
    8, ...)."""
    audio = {}
    snd = bus.snd

    def cur():
        k = 4 * (snd.ticks - 1) // FRAME
        a = audio.get(k)
        if a is None:
            a = audio[k] = [FNV0, 0, FNV0, 0, 0]
        return a

    def on_level(lv):
        a = cur()
        a[0] = fnv(a[0], lv)
        a[1] += 1
        a[4] += lv != 0

    def on_sample(v):
        a = cur()
        a[2] = fnv(a[2], v)
        a[3] += 1
    snd.on_level = on_level
    snd.on_sample = on_sample
    return audio


class psg2_hooks:
    """PSG #2's per-frame fingerprint and the mixed sound, as the bench's E
    lines give them: {k: [ha, na, hq, nq, hm]}: PSG #2's steps' levels and
    48 kHz samples as psg_hooks has PSG #1's (it steps only while the ECS is
    attached), and hm over every sample of the machine's sound, mix_sample():
    min(32767, PSG #1 + PSG #2), the sum scaled to 3/4 (floor) while the ECS
    is attached or on, a step at cycle c counting in frame (c + 1) // FRAME
    (intv_machine gives the sample the clk after the step's ce). Both PSGs
    step at the same cycles (tools/psg.py); done() collects them once the
    run has advanced both."""

    def __init__(self, bus, level=2):
        self.bus = bus
        self.level = level              # the ECS level (ECS_OF's 'level', default 2)
        self.a2 = {}
        self.s1, self.s2 = [], {}
        prev1 = bus.snd.on_sample

        def s1(v):
            if prev1:
                prev1(v)
            self.s1.append((bus.snd.ticks, v, bus.ecs is not None and bus.ecs.on))
        bus.snd.on_sample = s1
        if bus.ecs is not None:
            p2 = bus.ecs.psg

            def cur():
                k = 4 * (p2.ticks - 1) // FRAME
                a = self.a2.get(k)
                if a is None:
                    a = self.a2[k] = [FNV0, 0, FNV0, 0]
                return a

            def on_level(lv):
                a = cur()
                a[0] = fnv(a[0], lv)
                a[1] += 1

            def on_sample(v):
                a = cur()
                a[2] = fnv(a[2], v)
                a[3] += 1
                self.s2[p2.ticks] = v
            p2.on_level = on_level
            p2.on_sample = on_sample

    def done(self):
        out = {}
        for t, v1, on in self.s1:
            k = (4 * (t - 1) + 1) // FRAME
            e = out.setdefault(k, list(self.a2.get(k, [FNV0, 0, FNV0, 0])) + [FNV0])
            e[4] = fnv(e[4], mix_sample(v1, self.s2.get(t, 0), on, self.level))
        for k, a in self.a2.items():
            out.setdefault(k, list(a) + [FNV0])
        return out


def ecs_scale(v2, level=2):
    """PSG #2 at the ECS level (intv_machine.sv a2s; the menu's ECS Level, the module's own
    knob): 0 off, 1-4: x 1/2, 1, 3/2, 2 (floor), 2 the default."""
    return (0, v2 >> 1, v2, v2 + (v2 >> 1), v2 << 1)[level] if 0 <= level <= 4 else v2


def mix_sample(v1, v2, ecs_on, level=2):
    """The machine's sound sample (intv_machine.sv): PSG #1 + PSG #2 at the ECS level, scaled
    to 3/4 (floor) while the ECS is attached or on (ECS_NOTES 3), at most 32,767."""
    m = v1 + ecs_scale(v2, level)
    if ecs_on:
        m = (3 * m) >> 2
    return min(32767, m)


def fnv(h, *xs):
    for x in xs:
        h = ((h ^ (x & 0xFFFFFFFF)) * FNVP) & 0xFFFFFFFF
    return h


def model_stream(exec_path, grom_path, cart_path, npics, mode='stic', presses=None, peeks=None, ecs=None):
    """A long model run for the frame gate: per frame k the hash of the
    bus phases and of the step starts as the bench's H lines give them,
    and pictures 1..npics with their STIC logs; with presses, the scripted
    keys of the play bench (intv_system.press_pads). peeks: [(frame,
    address)] of scratchpad or System RAM, read at the first step start in
    that frame (cycle >= frame * FRAME); their values are returned in
    model_stream.peeked (a dict)."""
    cart = isys.load_cart(cart_path, CFG_OF.get(cart_path))
    bus = isys.SystemBus(isys.load_words(exec_path), open(grom_path, 'rb').read(),
                         cart[0] if cart else None, stic_mode=mode, ecs=ecs_device(cart, ecs),
                         jlp=isys.make_jlp(cart[0] if cart else None))
    bus.vid.mobs = STIC_MOBS
    if presses:
        bus.presses = presses
    cpu = isys.CP1610(bus=bus, buslog=True)
    pics, sinfo = capture(bus)
    audio = psg_hooks(bus)
    ecs_audio = psg2_hooks(bus, (ecs or {}).get('level', 2))
    ncyc = (npics + 1) * FRAME
    hashes = {}
    acc = {'k': 0, 'hb': FNV0, 'nb': 0, 'hs': FNV0, 'ns': 0}

    def close(upto):            # frames that ended before cycle `upto`
        while (acc['k'] + 1) * FRAME <= upto:
            hashes[acc['k']] = (acc['hb'], acc['nb'], acc['hs'], acc['ns'])
            acc.update(k=acc['k'] + 1, hb=FNV0, nb=0, hs=FNV0, ns=0)

    prev = (list(cpu.r), cpu.flags << 2 | cpu.I << 1 | cpu.D)
    todo = sorted(peeks or [])
    model_stream.peeked = {}
    while cpu.cycle < ncyc:
        while todo and cpu.cycle >= todo[0][0] * FRAME:
            f, a = todo.pop(0)
            model_stream.peeked[(f, a)] = (bus.scratch[a & 0xFF] if 0x100 <= a <= 0x1EF
                                           else bus.sysram[a - 0x200])
        ev = cpu.step()
        bus.boundary(cpu.cycle)
        if ev.kind in ('insn', 'intr') and 0 < ev.cycle < ncyc:
            close(ev.cycle)
            acc['hs'] = fnv(acc['hs'], ev.cycle, *prev[0], prev[1])
            acc['ns'] += 1
        prev = (list(ev.regs), ev.flags << 2 | ev.i << 1 | ev.d)
        for (c, p, a, d) in cpu.buslog:
            if p != 'NACT' and c < ncyc:
                close(c)
                acc['hb'] = fnv(acc['hb'], c, PHASE[p], a or 0, d or 0)
                acc['nb'] += 1
        cpu.buslog.clear()
    close(ncyc)
    bus.vid.advance(ncyc + FRAME)
    bus.snd.advance(ncyc - 1)
    if bus.ecs is not None and bus.ecs.on:
        bus.ecs.psg.advance(ncyc - 1)
    model_stream.ecs_audio = ecs_audio.done()
    model_stream.bus = bus
    return hashes, pics, sinfo, audio


def check_sect7(exp, symbols):
    """systest section 7: each probe in its slot (frames from 7 on), and the
    two INTRM-end probes: p9x's NOP ends in slot 3789 and no INTAK follows,
    p10x's ends in 3788 and the INTAK is in slot 3789. Problems as strings."""
    probs = []
    blog = exp.blog
    for k, (ph, a, slot) in enumerate(SECT7, 1):
        hit = [b[0] for b in blog if b[1] == PHASE[ph] and b[2] == a and b[0] >= SECT7_START]
        if not hit or hit[0] % FRAME != slot:
            probs.append('systest probe %d (%s %04X): slot %s, want %d' % (
                k, ph, a, hit[0] % FRAME if hit else 'none', slot))
    for lab, slot, taken in (('p9x', 3784, False), ('p10x', 3783, True)):
        a = symbols[lab]
        i = [j for j, b in enumerate(blog) if b[1] == PHASE['BAR'] and b[2] == a and b[0] >= SECT7_START]
        if not i or blog[i[0]][0] % FRAME != slot:
            probs.append('systest %s: fetch in slot %s, want %d' % (
                lab, blog[i[0]][0] % FRAME if i else 'none', slot))
            continue
        nxt = [b for b in blog[i[0] + 1:] if b[1] in (PHASE['BAR'], PHASE['INTAK'])][0]
        if (nxt[1] == PHASE['INTAK']) != taken or (taken and nxt[0] % FRAME != slot + 6):
            probs.append('systest %s: next %s at slot %d' % (lab, fmt_b(nxt), nxt[0] % FRAME))
    return probs


# ------------------------------------------------------------------- bench
def build(work, rtl_dir, verilator, strict=True):
    obj = os.path.join(work, 'obj')
    os.makedirs(work, exist_ok=True)
    tables = os.path.join(CORE, 'tables')
    # --verilate-jobs 1: Verilator 5.040's multithreaded verilation (what -j N turns on besides --build-jobs)
    # crashed about one build in 16 with "internal fault" (2026-10-28: 5 of 80 with -j 2, 0 of 210 with one)
    cmd = [verilator, '--binary', '--timing', '--verilate-jobs', '1', '--build-jobs', '4', '-Wall', '-Wno-fatal', '-Wno-TIMESCALEMOD',
           '-Wno-PROCASSINIT', '--top-module', 'tb_system', '-I' + rtl_dir, '-Mdir', obj, '-o', 'tb_system',
           '-DCRC_HEX="%s"' % os.path.join(tables, 'cart_crc.hex'),
           '-DLAYOUT_HEX="%s"' % os.path.join(tables, 'cart_layouts.hex')]
    cmd += [os.path.join(rtl_dir, f) for f in RTL] + OTHER
    log = os.path.join(work, 'build.log')
    with open(log, 'w') as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    text = open(log).read()
    if r.returncode != 0:
        print(text[-4000:])
        return None
    ours = [ln for ln in text.splitlines() if ln.startswith('%Warning') and
            any(('/' + f + ':') in ln for f in RTL)]
    if ours and strict:
        print('\n'.join(ours[:20]))
        return None
    return os.path.join(obj, 'tb_system')


class Got(tuple):
    """parse_log's result: (blog, steps, dumps, notes, fails, mlog) and the
    STIC's logs as attributes."""


def parse_log(path, pic_path=None):
    blog, steps, dumps, notes, fails, mlog = [], [], {}, [], [], []
    gl, gw, cl, hl, kl, al, el = [], {}, [], {}, [], {}, {}
    vl = []
    mark = (0, 0, 0)
    for ln in open(path):
        t = ln.split()
        if not t:
            continue
        if t[0] == 'G':
            gl.append((int(t[1]), int(t[2]), int(t[3]), int(t[4])))
        elif t[0] == 'GW':
            gw[int(t[1])] = tuple(int(x, 16) for x in t[2:22])
        elif t[0] == 'C':
            cl.append((int(t[1]), int(t[2]), int(t[3]), int(t[4]), int(t[5])))
        elif t[0] == 'K':
            kl.append((int(t[1]), tuple(int(x, 16) for x in t[2:10])))
        elif t[0] == 'H':
            hl[int(t[1])] = (int(t[2], 16), int(t[3]), int(t[4], 16), int(t[5]))
        elif t[0] == 'A':
            al[int(t[1])] = [int(t[2], 16), int(t[3]), int(t[4], 16), int(t[5])]
        elif t[0] == 'E':
            el[int(t[1])] = [int(t[2], 16), int(t[3]), int(t[4], 16), int(t[5]), int(t[6], 16)]
        elif t[0] == 'V':
            vl.append((int(t[1]), int(t[2]), int(t[3], 16)))
        elif t[0] == 'B':
            blog.append((int(t[1]), int(t[2]), int(t[3], 16), int(t[4], 16)))
        elif t[0] == 'S':
            if int(t[1]) > 0:
                steps.append((int(t[1]), [int(x, 16) for x in t[2:10]], int(t[10], 16)))
        elif t[0] == 'M':
            mlog.append((int(t[1]), int(t[2]), int(t[3])))
        elif t[0] == 'W':
            dumps.setdefault(int(t[1]), {})[(int(t[2], 16), int(t[3]))] = int(t[4], 16)
        elif t[0] == 'R' and t[1] == 'mark':
            mark = (len(gl), len(cl), len(kl))
            notes.append(ln.strip())
        elif t[0] == 'R' and t[1] == 'rewind':
            c = int(t[2])
            notes.append(ln.strip())
            blog = [b for b in blog if b[0] < c]
            steps = [s for s in steps if s[0] < c]
            mlog = [x for x in mlog if x[0] < c]
            vl = [x for x in vl if x[0] < c]
            # the STIC's lines are cut at the save (a freeze inside a cycle
            # may come after some of that cycle's lines)
            gl, cl, kl = gl[:mark[0]], cl[:mark[1]], kl[:mark[2]]
            gw = {k: v for k, v in gw.items() if k < c or k in [g[0] for g in gl]}
        elif t[0] in ('R', 'L'):
            notes.append(ln.strip())
        elif t[0] == 'FAIL':
            fails.append(ln.strip())
    dedup, last = [], (0, 0)
    for x in mlog:                      # a restore logs the value again
        if x[1:] != last:
            dedup.append(x)
            last = x[1:]
    got = Got((blog, steps, dumps, notes, fails, dedup))
    got.fetches, got.cards = {}, {}
    for c, r, ok, a in gl:
        got.fetches.setdefault(c // FRAME, []).append((r, ok, a, gw.get(c) if ok else None))
    for c, r, col, k, base in cl:
        got.cards.setdefault(c // FRAME, []).append((r, col, k, base))
    got.colls = {c // FRAME: b for c, b in kl}
    got.hashes = hl
    got.audio = al
    got.ecs_audio = el
    got.voice = vl
    got.pics = read_pics(pic_path) if pic_path else {}
    return got


def compare_audio(got, exp, frames, samples):
    """The PSG's per-frame fingerprint (A lines) against the model: the
    steps' levels in every run, the 48 kHz samples only with `samples` (the
    filter is not in the state, DESIGN 4.4, so a round trip may move them)."""
    for k in frames:
        g, e = got.audio.get(k), exp.audio.get(k)
        if g is None or e is None:
            if g != e:
                return ['frame %d PSG: RTL %s, model %s' % (k, g, e)]
            continue
        if g[:2] != e[:2] or (samples and g[2:4] != e[2:4]):
            return ['frame %d PSG (step hash, steps, 48 kHz hash, samples): RTL %s, model %s' % (
                k, ' '.join('%X' % x for x in g[:4]), ' '.join('%X' % x for x in e[:4]))]
    return []


def compare_ecs_audio(got, exp, frames, samples, ea=None):
    """PSG #2 and the mixed sound (E lines, step 9) against the model: PSG #2's steps in
    every run, its samples and the mix's with `samples` (straight runs)."""
    for k in frames:
        g = got.ecs_audio.get(k)
        e = (ea or exp.ecs_audio).get(k, [FNV0, 0, FNV0, 0, FNV0])
        if g is None:
            return ['frame %d PSG #2: no E line' % k]
        if g[:2] != e[:2] or (samples and (g[2:4] != e[2:4] or g[4] != e[4])):
            return ['frame %d PSG #2 / mix (step hash, steps, 48 kHz hash, samples, mix hash): RTL %s, '
                    'model %s' % (k, ' '.join('%X' % x for x in g), ' '.join('%X' % x for x in e))]
    return []


def voice_mix(got, exp):
    """Step 10: the E lines' mix hashes with the voice on top: the model's samples through
    sp0256.VoiceOut, each seen from the 48 kHz strobe the RTL's V line names (when the sample
    is made inside a CPU cycle is the RTL's, not machine state), the sum saturated to 16 bits
    (intv_machine). PSG #1's samples are the strobes, in order."""
    out = {k: list(v) for k, v in exp.ecs_audio.items()}
    vo = sp0256.VoiceOut(exp.voice['dac'], exp.voice['level'])
    vis, vals = [x[1] for x in got.voice], [x[1] for x in exp.vsamples]
    hm, j = {}, 0
    for i, (t, v1, on) in enumerate(exp.mix_raw.s1):
        while j < len(vis) and j < len(vals) and vis[j] <= i:
            vo.sample(vals[j])
            j += 1
        m = max(-32768, min(32767, mix_sample(v1, exp.mix_raw.s2.get(t, 0), on, exp.mix_raw.level) + vo.strobe()))
        k = (4 * (t - 1) + 1) // FRAME
        hm[k] = fnv(hm.get(k, FNV0), m & 0xFFFF)
    for k, h in hm.items():
        out.setdefault(k, [FNV0, 0, FNV0, 0, FNV0])[4] = h
    return out


def compare_voice(got, exp, run):
    """Step 10: the voice's samples (V lines: the cycle each fired at, its value) against the
    model's, up to a few cycles before the end (the last may be made during the freeze); the
    mode and late (L lines)."""
    probs = []
    on = bool(exp.voice) and exp.voice['ovr'] == 'on'
    want = 'L voice mode %d' % on
    if want not in got[3]:
        probs.append('RTL voice: %s, want "%s"' % ([x for x in got[3] if x.startswith('L voice')], want))
    want = 'L voice on %d late 0' % on
    if want not in got[3]:
        probs.append('RTL voice: %s, want "%s"' % ([x for x in got[3] if x.startswith('L voice on')], want))
    lim = exp.ncyc - 8
    g = [(f, v) for f, _, v in got.voice if f < lim]
    e = [(f, v & 0xFFFF) for f, v in exp.vsamples if f < lim]
    if g != e:
        i = next((j for j in range(max(len(g), len(e))) if (g[j] if j < len(g) else None) != (e[j] if j < len(e) else None)), 0)
        probs.append('voice sample %d of %d / %d (cycle, value): RTL %s, model %s' % (
            i, len(g), len(e), g[i] if i < len(g) else None, e[i] if i < len(e) else None))
    return probs


def audio_summary(exp):
    """How much the PSG did in the model's run: steps, steps with a
    channel on, frames with sound."""
    a = exp.audio
    return 'PSG %d steps (%d with a channel on), %d samples, %d frames with sound' % (
        sum(v[1] for v in a.values()), sum(v[4] for v in a.values()),
        sum(v[3] for v in a.values()), sum(1 for v in a.values() if v[4]))


def read_pics(path):
    """Pictures from the bench's +pic file: {n: bytes of 189 x 240 colours};
    the last record of a number counts (rewinds write some again)."""
    import struct
    pics = {}
    if not os.path.exists(path):
        return pics
    data = open(path, 'rb').read()
    for i in range(0, len(data) - PIC_BYTES + 1, PIC_BYTES):
        n = struct.unpack_from('<I', data, i)[0]
        px = bytearray(PIC_W * PIC_H)
        raw = data[i + 4:i + PIC_BYTES]
        for j, b in enumerate(raw):
            px[2 * j] = b & 15
            px[2 * j + 1] = b >> 4
        pics[n] = bytes(px)
    return pics


def compare_stic(got, exp, frames, check_hash=False):
    """The STIC's pictures, row fetches and card rows (and with check_hash
    the per-frame bus hashes) against the model. frames: the frame numbers
    k (picture k + 1) to compare."""
    probs = []
    shown = 0
    for k in frames:
        n = k + 1
        e = exp.pics.get(n)
        g = got.pics.get(n)
        if e is None or g is None:
            probs.append('picture %d: %s' % (n, 'not drawn by the model' if e is None else 'missing from the RTL'))
            break
        if g != e:
            i = next(j for j in range(len(e)) if g[j] != e[j])
            nd = sum(1 for j in range(len(e)) if g[j] != e[j])
            probs.append('picture %d: %d pixels differ, first x=%d y=%d RTL %d model %d' % (
                n, nd, i % PIC_W, i // PIC_W, g[i], e[i]))
            break
        if len(set(e[24 * PIC_W:216 * PIC_W])) > 1:
            shown += 1
    for k in frames:
        ef, ec, ek = exp.sinfo.get(k + 1, ([], [], None))
        gf, gc = got.fetches.get(k, []), got.cards.get(k, [])
        if ek is not None and got.colls.get(k) != ek:
            probs.append('frame %d collisions (MOBs 0-7): RTL %s, model %s' % (
                k, ' '.join('%03X' % b for b in got.colls[k]) if k in got.colls else None,
                ' '.join('%03X' % b for b in ek)))
            break
        if gf != ef:
            i = next((j for j in range(max(len(gf), len(ef)))
                      if (gf[j] if j < len(gf) else None) != (ef[j] if j < len(ef) else None)), 0)
            probs.append('frame %d row fetch %d (row, loaded, counter, words): RTL %s, model %s' % (
                k, i, gf[i] if i < len(gf) else None, ef[i] if i < len(ef) else None))
            break
        if gc != ec:
            i = next((j for j in range(max(len(gc), len(ec)))
                      if (gc[j] if j < len(gc) else None) != (ec[j] if j < len(ec) else None)), 0)
            probs.append('frame %d card %d (row, col, GROM/GRAM/squares, base): RTL %s, model %s' % (
                k, i, gc[i] if i < len(gc) else None, ec[i] if i < len(ec) else None))
            break
    if check_hash:
        for k in frames:
            if got.hashes.get(k) != exp.hashes.get(k):
                probs.append('frame %d bus hash (B hash, n, S hash, n): RTL %s, model %s' % (
                    k, got.hashes.get(k), exp.hashes.get(k)))
                break
    got.shown = shown
    return probs


def fmt_b(b):
    if b is None:
        return '(none)'
    inv = {v: k for k, v in PHASE.items()}
    return 'c=%d %s %04X %04X' % (b[0], inv[b[1]], b[2], b[3])


def compare(name, run, got, exp):
    """Problems of one run against the model (a list of strings)."""
    blog, steps, dumps, notes, fails, mlog = got[:6]
    eb, es, snaps = exp.blog, exp.steps, exp.snaps
    probs = list(fails)
    n = max(len(blog), len(eb))
    for i in range(n):
        g = blog[i] if i < len(blog) else None
        e = eb[i] if i < len(eb) else None
        if g != e:
            ctx = ' | '.join(fmt_b(x) for x in eb[max(0, i - 3):i])
            probs.append('bus entry %d: RTL %s, model %s (before: %s)' % (i, fmt_b(g), fmt_b(e), ctx))
            break
    for i in range(max(len(steps), len(es))):
        g = steps[i] if i < len(steps) else None
        e = es[i] if i < len(es) else None
        if g != e:
            probs.append('step %d: RTL %s, model %s' % (i, g, e))
            break
    for i in range(max(len(mlog), len(exp.mlog))):
        g = mlog[i] if i < len(mlog) else None
        e = exp.mlog[i] if i < len(exp.mlog) else None
        if g != e:
            probs.append('handshake / mode latch change %d (cycle, hs, csmode): RTL %s, model %s' % (i, g, e))
            break
    for k, cyc in ((1, DUMP1), (2, exp.ncyc)):
        d = dumps.get(k)
        if d is None:
            probs.append('dump %d missing' % k)
            continue
        st = snaps[cyc]
        checks = []
        checks += [('scratch %02X' % i, d[(SS['scr'], i)], st['scratch'][i]) for i in range(256)]
        checks += [('sysram %03X' % i, d[(SS['sys'] + i // 256, i % 256)], st['sysram'][i])
                   for i in range(352)]
        checks += [('gram %03X' % i, d[(SS['gram'] + i // 256, i % 256)], st['gram'][i])
                   for i in range(512)]
        checks += [('stic %02X' % i, d[(SS['stic'], i)], st['stic'][i]) for i in range(0x33)]
        checks.append(('stic hs/csmode', d[(SS['stic'], 0x33)], st['handshake'] << 1 | st['csmode']))
        checks += [('psg %d' % i, d[(SS['psg'], i)], st['psg'][i]) for i in range(14)]
        checks += [('psg %d' % (14 + i), d[(SS['psg'], 14 + i)], st['psgx'][i]) for i in range(7)]
        sel = st['sel']
        checks.append(('page selects 0-7', d[(SS['cart'], 5)],
                       sum(sel[i] << 4 * i for i in range(8))))
        checks.append(('page selects 8-15', d[(SS['cart'], 6)],
                       sum(sel[8 + i] << 4 * i for i in range(8))))
        bank = st['bank']
        checks += [('bank registers %d-%d' % (4 * k, 4 * k + 3), d[(SS['cart'], 7 + k)],
                    sum(bank[4 * k + i] << 8 * i for i in range(4))) for k in range(8)]
        checks.append(('bus: reset vector flag, hold', d[(SS['bus'], 0)] >> 16 & 5, 0))
        checks += [('row buffer %d' % i, d[(SS['row'], i)], st['fifo'][i]) for i in range(20)]
        checks.append(('FIFO counter', d[(SS['stic'], 0x35)] & 0x1FF, st['counter']))
        # step 9: the ECS (its page and port latches, mode; PSG #2; its RAM)
        checks.append(('ECS latches and mode', d[(SS['ecs'], 0)], st['ecs'][0]))
        checks += [('psg2 %d' % i, d[(SS['psg2'], i)], st['psg2'][i]) for i in range(14)]
        checks += [('psg2 %d' % (14 + i), d[(SS['psg2'], 14 + i)], st['psg2x'][i]) for i in range(7)]
        checks += [('ECS RAM %03X' % (4 * i), d[(SS['eram'] + i // 256, i % 256)], st['ecsram'][i])
                   for i in range(512)]
        # step 10: intv_voice's own words (the sample enable, the window, the held write)
        checks += [('voice word %d' % (20 + i), d[(SS['voice'], 20 + i)], st['voice'][i]) for i in range(3)]
        # step 11: the JLP's words (tools/jlp.py Jlp.state, and the cycle count)
        if st.get('jlp') is not None:
            checks += [('jlp word %d' % i, d[(SS['jlp'], i)], st['jlp'][i]) for i in range(28)]
        bad = [c for c in checks if c[1] != c[2]]
        if bad:
            probs.append('dump %d (cycle %d): %d words differ from the model, first: %s' % (
                k, cyc, len(bad), '; '.join('%s RTL %X model %X' % b for b in bad[:4])))
    probs += compare_stic(got, exp, range(exp.ncyc // FRAME - 1))
    probs += compare_audio(got, exp, range(exp.ncyc // FRAME), run == 'straight')
    on = bool(exp.voice) and exp.voice['ovr'] == 'on'
    probs += compare_ecs_audio(got, exp, range(exp.ncyc // FRAME), run == 'straight',
                               voice_mix(got, exp) if on and run == 'straight' else None)
    probs += compare_voice(got, exp, run)
    mode = 0
    if exp.ecs:
        mode = exp.ecs['auto'] if exp.ecs['ovr'] == 'auto' else {'on': 1, 'off': 0}[exp.ecs['ovr']]
        want = 'L ecs auto %d rom %d mode %d' % (exp.ecs['auto'], 0 if exp.ecs.get('norom') else 1, mode)
        if want not in got[3]:
            probs.append('RTL ECS: %s, want "%s"' % ([x for x in got[3] if x.startswith('L ecs')], want))
    # the key routing's mode (step-9 review): intv_input gets the keyboard into the matrix only
    # with the ECS fully on (mode 1), never attached
    want = 'L ecs full %d' % (mode == 1)
    if want not in got[3]:
        probs.append('RTL ECS: %s, want "%s"' % ([x for x in got[3] if x.startswith('L ecs full')], want))
    return probs


def run_bench(binary, work, tag, exec_path, grom_path, cart_path, args, exp, pads, timeout=1200):
    log = os.path.join(work, 'run_%s.log' % tag)
    pic = os.path.join(work, 'run_%s.pic' % tag)
    cmd = [binary, '+exec=' + exec_path, '+grom=' + grom_path, '+cycles=%d' % exp.ncyc,
           '+dump=%d' % DUMP1, '+log=' + log, '+pads=%02X%02X' % tuple(pads), '+pic=' + pic,
           '+busrq=%d' % (exp.mode != 'none')] + args
    if cart_path:
        cmd.append('+cart=' + cart_path)
        if CFG_OF.get(cart_path):
            cmd.append('+cfg=' + CFG_OF[cart_path])
    cmd += ecs_args(work, tag, exp.ecs, exp.ncyc // FRAME)
    if exp.voice:
        cmd += ['+voice=%d' % {'auto': 0, 'on': 1, 'off': 2}[exp.voice['ovr']], '+ivoice=' + ivoice_rom(),
                '+vlevel=%d' % exp.voice['level'], '+vdac=%d' % exp.voice['dac']]
    with open(os.path.join(work, 'stdout_%s.txt' % tag), 'w') as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout, cwd=work)
    if r.returncode != 0 or not os.path.exists(log):
        return None
    got = parse_log(log, pic)
    os.remove(pic)
    return got


def ecs_bios():
    d = os.environ.get('INTV_BIOS_DIR', os.path.expanduser('~/pocket_projects/intellivision/bios'))
    for n in ('ECS.bin', 'ecs.bin'):
        if os.path.exists(os.path.join(d, n)):
            return os.path.join(d, n)
    return None


def ekey_lines(presses, nframes):
    """The bench's +ekeys file: "k K" where frame k's ECS keyboard switches (press_keys of
    notifier k - 1) change."""
    out, last = [], 0
    for k in range(nframes + 2):
        v = isys.press_keys(presses, k - 1)
        if v != last:
            out.append('%d %016X\n' % (k, v))
            last = v
    return out


def ecs_args(work, tag, ecs, nframes):
    """The bench's ECS plusargs for an ECS_OF entry: the override (none: Off), the ECS
    ROM slot, the synthesizer, the keys."""
    if not ecs:
        return ['+ecs=2']
    args = ['+ecs=%d' % ECS_OVR[ecs['ovr']]]
    rom = None if ecs.get('norom') else ecs_bios()
    if rom:
        args.append('+ecsrom=' + rom)
    if ecs.get('synth'):
        args.append('+synth=1')
    if ecs.get('level', 2) != 2:
        args.append('+elevel=%d' % ecs['level'])
    if ecs.get('presses'):
        kf = os.path.join(work, 'ekeys_%s.txt' % tag)
        with open(kf, 'w') as f:
            f.writelines(ekey_lines(isys.parse_presses(ecs['presses']), nframes))
        args.append('+ekeys=' + kf)
    return args


def rt_runs(exp):
    """The round-trip runs: (tag, plusargs). The first freezes inside a
    cartridge read (between the address and the data, so the held answer
    must come back): the last one of the run, if the image has one, else
    in VBlank of frame 5."""
    eb = exp.blog
    cart_dtb = [b[0] for b in eb if b[1] == PHASE['DTB'] and b[0] < DUMP1 and
                exp.bus.cart is not None and exp.bus.cart.read(b[2]) is not None]
    c1 = cart_dtb[-1] if cart_dtb else 5 * FRAME + 600
    runs = [('straight', []),
            ('rt1', ['+rt=1', '+rtcyc=%d' % c1, '+rtsub=17']),
            ('rt2', ['+rt=2', '+rtcyc=%d' % (5 * FRAME + 600), '+rtsub=30', '+rton=20000']),
            ('rt3', ['+rt=1', '+rtcyc=%d' % (5 * FRAME + 6000), '+rtsub=3'])]
    # with the display on: the fetch cycles of loaded rows in frames 3 on
    # (row r of frame k at k FRAME + 3933 + 114 VDR + 912 r)
    fl = []
    for n, (g, *_) in sorted(exp.sinfo.items()):
        k = n - 1
        st = [s for s in exp.bus.vid.stats if s['n'] == n]
        if k >= 3 and st and st[0]['enabled'] and (k + 2) * FRAME < exp.ncyc:
            fl += [(k, r, k * FRAME + 3933 + 114 * st[0]['vdr'] + 912 * r) for r, ok, _, _ in g if ok]
    if fl:
        rt4 = [f for f in fl if f[1] == 3][0][2]
        rt5 = [f for f in fl if f[1] == 6][-1][2]
        # reset restore 17 clk_sys into the row copy (word 8 of 20); a later
        # state, restored from 3 cycles into the fetch line plus 30 clk_sys:
        # the CPU in BUSAK, the card engine building the row's first line
        runs += [('rt4', ['+rt=1', '+rtcyc=%d' % rt4, '+rtsub=17']),
                 ('rt5', ['+rt=2', '+rtcyc=%d' % (rt5 + 3), '+rtsub=30', '+rton=20000'])]
    # with MOBs (build step 5), frames 3 on with the display on and a MOB
    # drawn or interacting: rt6 = reset restore inside the collision sweep
    # (it runs from the end of the VBlank window, cycle 3,790, for about 7
    # lines: here 3 lines and 20 cycles in, plus 17 clk_sys); rt7 = rewind
    # restore inside a line's MOB fetch (pixel clocks 196-203 = cycles 49
    # and 50 of the line; here 1 + 5 clk_sys into cycle 50) on a line
    # inside a MOB, so the masks it builds are used on the next line
    mk = []
    for n, ml in sorted(exp.bus.moblog.items()):
        k = n - 1
        st = [x for x in exp.bus.vid.stats if x['n'] == n]
        if k >= 3 and ml and st and st[0]['enabled'] and (k + 2) * FRAME < exp.ncyc:
            mk.append((k, ml))
    if mk:
        k = mk[0][0]
        runs.append(('rt6', ['+rt=1', '+rtcyc=%d' % (k * FRAME + stic.VBLANK + 3 * stic.LINE + 20),
                             '+rtsub=17']))
        for k, ml in reversed(mk):
            tops = [e[5] + stic.PIC_LINE0 for e in ml if 70 <= e[5] + stic.PIC_LINE0 <= 254]
            if tops:
                runs.append(('rt7', ['+rt=2', '+rtcyc=%d' % (k * FRAME + stic.LINE * (tops[0] + 1) + 50),
                                     '+rtsub=5', '+rton=20000']))
                break
    # sticmob: rt8 = reset restore at the start of the sweep's pairs for
    # picture line 169 of frame 34 (scene S11 of 22, second pass), the one
    # line where MOBs 4 and 5 overlap: the sweep's masks of that line must
    # come back
    # psgtest: round trips in the middle of the slow triangle envelope
    # (its group 11, steps every 512 cycles; tools/psg.py): rt9 restores
    # into a reset machine, rt10 over a state 20,000 cycles later, each at
    # a clk_sys inside a CPU cycle and a step's 4-cycle phase other than 0
    if exp.name == 'psgtest':
        k = [n for n in sorted(exp.audio) if n >= 11][0]
        runs += [('rt9', ['+rt=1', '+rtcyc=%d' % (k * FRAME + 7002), '+rtsub=29']),
                 ('rt10', ['+rt=2', '+rtcyc=%d' % (k * FRAME + 12002), '+rtsub=7', '+rton=20000'])]
    if exp.name == 'sticmob':
        t = 34 * FRAME * 48 + sweep_clock(169)
        runs.append(('rt8', ['+rt=1', '+rtcyc=%d' % (t // 48), '+rtsub=%d' % (t % 48)]))
    return runs


def sweep_clock(line, e0=8, mf=196):
    """clk_sys from the frame start (12 a pixel clock, 48 a CPU cycle) at
    which intv_stic.sv's collision sweep starts the pairs of picture line
    `line`: it starts the clock after the ce that ends the VBlank window,
    takes two clocks a MOB (the second only where g_ok), then one a pair."""
    c = stic.VBLANK * 48
    ly, m, ph, pairs = 8, 0, 0, 0
    while True:
        h = (c // 12) % (4 * stic.LINE)
        ok = not (e0 <= h <= e0 + 20) and not (mf <= h <= mf + 8)
        if pairs:
            if ly == line:
                return c
            pairs -= 1
            if pairs == 0:
                ly += 1
        elif ph == 0:
            ph = 1
        elif ok:
            ph = 0
            m += 1
            if m == 8:
                m, pairs = 0, 28
        c += 1


def check_image(binary, work, name, exec_path, grom_path, cart_path, exp, pads, verbose=True,
                only_runs=None):
    probs = []
    results = {}
    for tag, args in rt_runs(exp):
        if only_runs and tag not in only_runs:
            continue
        t0 = time.time()
        got = run_bench(binary, work, '%s_%s' % (name, tag), exec_path, grom_path, cart_path, args, exp,
                        pads)
        if got is None:
            probs.append('%s %s: the bench did not finish' % (name, tag))
            continue
        p = compare(name, tag, got, exp)
        results[tag] = got
        if verbose:
            rt = [x for x in got[3] if x.startswith('R ')]
            print('  %s %s: %d bus phases, %d step starts, %d pictures (%d with the display on), '
                  '%d row fetches, %.1fs%s%s' % (
                name, tag, len(got[0]), len(got[1]), len(got.pics), getattr(got, 'shown', 0),
                sum(len(v) for v in got.fetches.values()), time.time() - t0,
                ('; ' + '; '.join(x[2:] for x in rt)) if rt else '',
                ('\n    FAIL ' + '\n    FAIL '.join(p)) if p else ''))
        probs += ['%s %s: %s' % (name, tag, x) for x in p]
    ref = results.get('straight')
    for tag, got in results.items():
        if ref is None or tag == 'straight':
            continue
        for k in (1, 2):
            a, b = ref[2].get(k, {}), got[2].get(k, {})
            diff = [w for w in a if a[w] != b.get(w)]
            if diff:
                probs.append('%s %s: dump %d differs from the straight run in %d words, first %s' % (
                    name, tag, k, len(diff), ', '.join('%02X.%d %08X/%08X' % (w[0], w[1], a[w], b.get(w, -1))
                                                       for w in diff[:4])))
    return probs


# ------------------------------------------------------------- frame gate
def screen_cart(work, name, zipname, lib):
    if not zipname:
        return None
    if isinstance(zipname, tuple):            # a step-8 image from our sources
        return step8_image(zipname[1], work)[0]
    cart = os.path.join(work, 'screen_%s.bin' % name)
    with open(cart, 'wb') as f:
        f.write(m.load_image_bytes(os.path.join(lib, zipname)))
    return cart


def key_lines(presses, nframes):
    """The bench's +keys file for a play run: "k RRLL" where frame k's
    hand-controller byte (press_pads of notifier k - 1) changes."""
    out, last = [], None
    for k in range(nframes + 2):
        v = isys.press_pads(presses, k - 1)
        if v != last:
            out.append('%d %02X%02X\n' % (k, v, v))
            last = v
    return out


def check_screen(binary, work, name, cart, exec_path, grom_path, npics, verbose=True, presses=None,
                 peeks=None, ecs=None):
    """One image of the frame gate: the bench (+bushash, +pic) runs while
    the model runs; then every picture, row fetch, card row and per-frame
    bus hash must be equal. With presses (the play bench) both hold the
    same scripted keys. peeks: [(frame, address, want)]: the model's RAM
    word there (model_stream peeks) must be want. Returns problems."""
    ncyc = (npics + 1) * FRAME
    log = os.path.join(work, 'screen_%s.log' % name)
    pic = os.path.join(work, 'screen_%s.pic' % name)
    cmd = [binary, '+exec=' + exec_path, '+grom=' + grom_path, '+cycles=%d' % ncyc,
           '+dump=%d' % DUMP1, '+log=' + log, '+pic=' + pic, '+bushash=1', '+busrq=1']
    if cart:
        cmd.append('+cart=' + cart)
        if CFG_OF.get(cart):
            cmd.append('+cfg=' + CFG_OF[cart])
    if presses:
        kf = os.path.join(work, 'screen_%s.keys' % name)
        with open(kf, 'w') as f:
            f.writelines(key_lines(presses, npics))
        cmd.append('+keys=' + kf)
    if ecs:                             # step 9: the ECS keys come with the same presses
        e2 = dict(ecs, presses=None)
        cmd += ecs_args(work, 'screen_' + name, e2, npics)
        if presses and any(isinstance(c, tuple) and c[0] == 'ecs' for _, _, c in presses):
            ef = os.path.join(work, 'screen_%s.ekeys' % name)
            with open(ef, 'w') as f:
                f.writelines(ekey_lines(presses, npics))
            cmd.append('+ekeys=' + ef)
    else:
        cmd.append('+ecs=2')
    t0 = time.time()
    out = open(os.path.join(work, 'screen_%s.out' % name), 'w')
    proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, cwd=work)
    try:
        hashes, pics, sinfo, audio = model_stream(exec_path, grom_path, cart, npics, presses=presses,
                                                  peeks=[(f, a) for f, a, _ in peeks or []], ecs=ecs)
        peeked = model_stream.peeked
        t1 = time.time() - t0
        r = proc.wait(timeout=7200)
    finally:
        if proc.poll() is None:
            proc.kill()
        out.close()
    if r != 0 or not os.path.exists(log):
        return ['%s: the bench did not finish' % name]
    got = parse_log(log, pic)
    os.remove(pic)
    exp = Exp([], [], {}, None, [], ncyc, pics, sinfo)
    exp.hashes = hashes
    exp.audio = audio
    exp.ecs_audio = model_stream.ecs_audio
    probs = list(got[4]) + compare_stic(got, exp, range(npics), check_hash=True)
    for f, a, want in peeks or []:
        val = peeked.get((f, a))
        if verbose:
            print('  %s: model $%04X at frame %d = %s, want %d' % (name, a, f, val, want))
        if val != want:
            probs.append('%s: model $%04X at frame %d = %s, want %d' % (name, a, f, val, want))
    if presses:
        nk = [x for x in got[3] if x.startswith('L keys')]
        want = 'L keys %d' % len(key_lines(presses, npics))
        if nk != [want]:
            probs.append('%s: bench read %s, want %s' % (name, nk, want))
    probs += compare_audio(got, exp, range(npics + 1), True)
    probs += compare_ecs_audio(got, exp, range(npics + 1), True)
    if verbose:
        en = sum(1 for n in range(1, npics + 1) if exp.sinfo.get(n, ([], []))[1])
        print('  %s: %d pictures (%d with the display on, %d of them not blank), %d row fetches '
              '(%d missed), %d card rows, %d frames of bus hashes; %s; model %.0fs, bench %.0fs%s' % (
                  name, len(got.pics), en, got.shown,
                  sum(len(v) for v in got.fetches.values()),
                  sum(1 for v in got.fetches.values() for f in v if not f[1]),
                  sum(len(v) for v in got.cards.values()) // 20, len(got.hashes),
                  audio_summary(exp), t1,
                  time.time() - t0, ('\n    FAIL ' + '\n    FAIL '.join(probs)) if probs else ''))
    return probs


# ------------------------------------------------------------------ plants
# Each is one change to a copy of the RTL; the bench must fail on it.
PLANTS = [
    # behaviour (the plain lockstep)
    ('pullup_zero', 'intv_bus.sv', [("            if (cart_hit) din &= cart_q;\n",
     "            if (cart_hit) din &= cart_q;\n            if (!(sel_stic || sel_scr || sel_psg || sel_sys"
     " || sel_exec || sel_grom || sel_gram || cart_hit)) din = 16'h0000;\n")], 'nocart', None),
    ('grom_upper_0', 'intv_bus.sv', [("din &= {8'hFF, grom_q};", "din &= {8'h00, grom_q};")], 'nocart', None),
    ('exec_upper_1', 'intv_bus.sv', [("din &= {6'd0, exec_q};", "din &= {6'h3F, exec_q};")], 'nocart', None),
    ('scratch_upper_1', 'intv_bus.sv', [("din &= {8'h00, scr_q};", "din &= {8'hFF, scr_q};")], 'systest', None),
    ('intrm_line_late', 'intv_bus.sv', [("    assign intrm     = vb_next;",
     "    assign intrm     = slot >= 16'(CPL - 1) && slot < 16'(VB_CYCLES + CPL - 1);")], 'astrosmash', None),
    ('start_line_early', 'intv_bus.sv', [("if (hold && slot == 16'(FRAME - 2))",
                                          "if (hold && slot == 16'(FRAME - 2 - CPL))")], 'astrosmash', None),
    ('iab_always_1004', 'intv_bus.sv', [("din = iab_rst ? 16'h1000 : 16'h1004;", "din = 16'h1004;")],
     'nocart', None),
    ('stic_mxr_mask', 'intv_stic.sv', [("if (n < 6'h08)       fixed = 14'h3800;",
                                             "if (n < 6'h08)       fixed = 14'h3000;")], 'nocart', None),
    ('stic_always_open', 'intv_stic.sv', [("assign open = vb || !hs;", "assign open = 1'b1;")],
     'systest', None),
    ('stic_no_aliases', 'intv_bus.sv', [("assign stic_we = wr && a[13:6] == 8'd0;",
                                         "assign stic_we = wr && a[15:6] == 10'd0;")], 'systest', None),
    ('gram_no_mirror', 'intv_bus.sv', [("assign gram_we = wr && a[13:11] == 3'b111 && stic_open;",
     "assign gram_we = wr && a[15:11] == 5'b00111 && a[10:9] == 2'b00 && stic_open;")], 'systest', None),
    ('psg_mask', 'intv_psg.sv', [("4'd9:                    mask = 8'h1F;",
                                       "4'd9:                    mask = 8'hFF;")], 'systest', None),
    # state port: a flip-flop left out of the port (neither saved nor restored),
    # shown by the run after the restore
    ('ss_ram_lost', 'intv_ram.sv', [("wire logic          wa = ss_en ? ss_we && ss_hit : we;",
                                     "wire logic          wa = ss_en ? 1'b0 : we;"),
                                    ("assign ss_rdata = hit_q ? 32'(q) : 32'd0;", "assign ss_rdata = 32'd0;")],
     'systest', ['rt2']),
    ('ss_psg_lost', 'intv_psg.sv', [("                r[ss_w[3:0]] <= ss_wdata[7:0] & mask(ss_w[3:0]);", "                ;"),
                                    ("ss_rdata = {24'd0, r[ss_w[3:0]]};", "ss_rdata = 32'd0;")],
     'systest', ['rt1']),
    ('ss_cart_q_lost', 'intv_bus.sv', [("            end else if (ss_w == 8'd1)\n                cart_q <= ss_wdata[15:0];",
                                        "            end else if (ss_w == 8'd1)\n                ;"),
                                       ("8'd1: ss_rdata = {16'd0, cart_q};", "8'd1: ss_rdata = 32'd0;")],
     'astrosmash', ['rt1']),
    ('ss_iab_lost', 'intv_bus.sv', [("{hold, cart_hit, iab_rst} <= ss_wdata[18:16];",
                                     "{hold, cart_hit} <= ss_wdata[18:17];"),
                                    ("8'd0: ss_rdata = {13'd0, hold, cart_hit, iab_rst, a};",
                                     "8'd0: ss_rdata = {13'd0, hold, cart_hit, 1'b0, a};")], 'astrosmash', ['rt1']),
    ('ss_handshake_lost', 'intv_stic.sv', [("{hs, csmode} <= ss_wdata[1:0];", "csmode <= ss_wdata[0];"),
                                                ("ss_rdata = {30'd0, hs, csmode};", "ss_rdata = {31'd0, csmode};")],
     'systest', ['rt3']),
    ('ss_addr_lost', 'intv_bus.sv', [("                a <= ss_wdata[15:0];\n", ""),
                                     ("8'd0: ss_rdata = {13'd0, hold, cart_hit, iab_rst, a};",
                                      "8'd0: ss_rdata = {13'd0, hold, cart_hit, iab_rst, 16'd0};")],
     'astrosmash', ['rt1']),
    # state port: one RAM whose restore writes are lost (reads still work);
    # rt1 writes junk after the reset, so the old contents cannot hide it
    ('ss_gram_wr_lost', 'intv_ram.sv', [("wire logic          wa = ss_en ? ss_we && ss_hit : we;",
                                         "wire logic          wa = ss_en ? ss_we && ss_hit && SS_ID != 8'h09 : we;")],
     'systest', ['rt1']),
    ('ss_scr_wr_lost', 'intv_ram.sv', [("wire logic          wa = ss_en ? ss_we && ss_hit : we;",
                                        "wire logic          wa = ss_en ? ss_we && ss_hit && SS_ID != 8'h06 : we;")],
     'systest', ['rt1']),
    ('ss_sys_wr_lost', 'intv_ram.sv', [("wire logic          wa = ss_en ? ss_we && ss_hit : we;",
                                        "wire logic          wa = ss_en ? ss_we && ss_hit && SS_ID != 8'h07 : we;")],
     'systest', ['rt1']),
    # the mode latch (the change log)
    ('csmode_no_alias', 'intv_stic.sv', [("if (rd && open && a[13:0] == 14'h0021)",
                                               "if (rd && open && a == 16'h0021)")], 'systest', None),
    ('csmode_no_open', 'intv_stic.sv', [("if (rd && open && a[13:0] == 14'h0021)",
                                              "if (rd && a[13:0] == 14'h0021)")], 'systest', None),
    ('csmode_wr_kept', 'intv_stic.sv', [("                if (n == 6'h21)\n                    csmode <= 1'b0;\n",
                                              "")], 'systest', None),
    # the end of the bus-copy window and of INTRM (systest section 7)
    ('vb_end_p1', 'intv_bus.sv', [("assign vb        = slot < 16'(VB_CYCLES);",
                                   "assign vb        = slot < 16'(VB_CYCLES + 1);")], 'systest', None),
    ('vb_end_m1', 'intv_bus.sv', [("assign vb        = slot < 16'(VB_CYCLES);",
                                   "assign vb        = slot < 16'(VB_CYCLES - 1);")], 'systest', None),
    ('intrm_end_p1', 'intv_bus.sv', [("vb_next = last || slot < 16'(VB_CYCLES - 1);",
                                      "vb_next = last || slot < 16'(VB_CYCLES);")], 'systest', None),
    ('intrm_end_m1', 'intv_bus.sv', [("vb_next = last || slot < 16'(VB_CYCLES - 1);",
                                      "vb_next = last || slot < 16'(VB_CYCLES - 2);")], 'systest', None),
    # hand controllers swapped (systest drives two different pads)
    ('pads_swapped', 'intv_psg.sv', [("4'd14:   q = pad_r;\n            4'd15:   q = pad_l;",
                                           "4'd14:   q = pad_l;\n            4'd15:   q = pad_r;")], 'systest', None),
    # the PSG (build step 6): its steps' levels and 48 kHz samples (psgtest)
    ('psg_lfsr_tap_2', 'intv_psg.sv', [("rng <= {rng[0] ^ rng[3], rng[16:1]};",
                                        "rng <= {rng[0] ^ rng[2], rng[16:1]};")], 'psgtest', None),
    ('psg_tone_period_p1', 'intv_psg.sv', [("13'(tcnt[c]) + 13'd1 >= {1'b0, r[4 + c][3:0], r[c]}",
                                            "13'(tcnt[c]) >= {1'b0, r[4 + c][3:0], r[c]}")], 'psgtest', None),
    ('psg_env_period_x1', 'intv_psg.sv', [("wire logic [16:0] eper2  = {r[7], r[3], 1'b0};",
                                           "wire logic [16:0] eper2  = {1'b0, r[7], r[3]};")], 'psgtest', None),
    ('psg_env_select_swapped', 'intv_psg.sv', [("2'd1: l = ev >> 2;\n                2'd2: l = ev >> 1;",
                                                "2'd1: l = ev >> 1;\n                2'd2: l = ev >> 2;")],
     'psgtest', None),
    ('psg_shape_no_restart', 'intv_psg.sv', [("                    estep <= 4'd15;\n                    ehold <= 1'b0;\n"
                                              "                    eatt  <= wdata[2];",
                                              "                    eatt  <= wdata[2];")], 'psgtest', None),
    ('psg_env_no_alternate', 'intv_psg.sv', [("if (s_alt) eatt <= !eatt;", ";")], 'psgtest', None),
    ('psg_tone_off_is_off', 'intv_psg.sv', [("on = (tout[c] | r[8][c]) & (rng[0] | r[8][3 + c]);",
                                             "on = tout[c] & (rng[0] | r[8][3 + c]);")], 'psgtest', None),
    ('psg_step_phase', 'intv_psg.sv', [("ehold <= 1'b0; tph <= 2'd3;", "ehold <= 1'b0; tph <= 2'd2;")],
     'psgtest', None),
    ('psg_write_after_step', 'intv_psg.sv', [("            if (we && n < 4'd14) begin",
                                              "            if (we && n < 4'd14 && !tick) begin")], 'psgtest', None),
    ('psg_filter_recip', 'intv_psg.sv', [("15'd13107", "15'd13108")], 'psgtest', None),
    ('psg_lowpass_single', 'intv_psg.sv', [("box + 18'(lp2_n[22:8]);", "box + 18'(lp1_n[22:8]);")],
     'psgtest', None),
    ('psg_dac_level', 'intv_psg.sv', [("4'd13: dac = 14'd6539;", "4'd13: dac = 14'd6540;")], 'psgtest', None),
    # the noise prescaler's phase: the LFSR shifts when the prescaler falls, not when it rises
    ('psg_noise_prescaler_rise', 'intv_psg.sv', [("                    if (npre)\n",
                                                  "                    if (!npre)\n")], 'psgtest', None),
    # Continue = 0 (shapes 0-7): hold after the first cycle, whatever Hold says
    ('psg_shape_cont0_hold', 'intv_psg.sv', [("s_hold = shape[3] ? shape[0] : 1'b1;", "s_hold = shape[0];")],
     'psgtest', None),
    # the mixer's noise-enable bits 3-5 (here the tone bits 0-2 read for noise too)
    ('psg_mixer_noise_bits', 'intv_psg.sv', [("(rng[0] | r[8][3 + c])", "(rng[0] | r[8][c])")], 'psgtest', None),
    # the port-direction bits 6-7 of the enable register obeyed: an output port reads its
    # (never written) latch instead of the hand controller (psgtest frame 17 sets both)
    ('psg_port_dir_obeyed', 'intv_psg.sv', [("4'd14:   q = pad_r;\n            4'd15:   q = pad_l;",
                                             "4'd14:   q = r[8][6] ? 8'hFF : pad_r;\n"
                                             "            4'd15:   q = r[8][7] ? 8'hFF : pad_l;")], 'psgtest', None),
    # the PSG's state words left out of the port (rt9: reset restore in the
    # slow envelope, at a step phase other than the reset's)
    ('ss_psg_tone_lost', 'intv_psg.sv', [("tcnt[ss_ch] <= ss_wdata[11:0];\n                    tout[ss_ch] <= ss_wdata[12];", ""),
                                         ("ss_rdata = {19'd0, tout[ss_ch], tcnt[ss_ch]};", "ss_rdata = 32'd0;")],
     'psgtest', ['rt9']),
    ('ss_psg_noise_lost', 'intv_psg.sv', [("5'd17: {npre, ncnt} <= ss_wdata[5:0];", "5'd17: ;"),
                                          ("5'd17: ss_rdata = {26'd0, npre, ncnt};", "5'd17: ss_rdata = 32'd0;")],
     'psgtest', ['rt9']),
    ('ss_psg_lfsr_lost', 'intv_psg.sv', [("5'd18: rng <= ss_wdata[16:0];", "5'd18: ;"),
                                         ("5'd18: ss_rdata = {15'd0, rng};", "5'd18: ss_rdata = 32'd0;")],
     'psgtest', ['rt9']),
    ('ss_psg_env_count_lost', 'intv_psg.sv', [("5'd19: ecnt <= ss_wdata[16:0];", "5'd19: ;"),
                                              ("5'd19: ss_rdata = {15'd0, ecnt};", "5'd19: ss_rdata = 32'd0;")],
     'psgtest', ['rt9']),
    ('ss_psg_env_step_lost', 'intv_psg.sv', [("default: {tph, ehold, eatt, estep} <= ss_wdata[7:0];",
                                              "default: {tph, ehold, eatt} <= ss_wdata[7:4];"),
                                             ("default: ss_rdata = {24'd0, tph, ehold, eatt, estep};",
                                              "default: ss_rdata = {24'd0, tph, ehold, eatt, 4'd0};")],
     'psgtest', ['rt9']),
    ('ss_psg_phase_lost', 'intv_psg.sv', [("default: {tph, ehold, eatt, estep} <= ss_wdata[7:0];",
                                           "default: {ehold, eatt, estep} <= ss_wdata[5:0];"),
                                          ("default: ss_rdata = {24'd0, tph, ehold, eatt, estep};",
                                           "default: ss_rdata = {24'd0, 2'd0, ehold, eatt, estep};")],
     'psgtest', ['rt9']),
    # a closed GRAM read gives 11 offset bits (systest reads through $3A00 / $3E00)
    ('gram_closed_11', 'intv_bus.sv', [("din &= stic_open ? {8'h00, gram_q} : {7'd0, a[8:0]};",
                                        "din &= stic_open ? {8'h00, gram_q} : {5'd0, a[10:0]};")],
     'systest', None),
    # the STIC (build step 4): pictures, row fetches, card rows, BUSRQ. An
    # image ('screen', name, pictures) runs the frame gate's image that far.
    ('stack_no_advance', 'intv_stic.sv', [("cs_new = cs_use + {1'b0, w[13]};", "cs_new = cs_use;")],
     'sticbus', None),
    ('stack_no_restart', 'intv_stic.sv', [("            if (frame_end)\n                {cs, cs_row} <= 4'd0;\n", "")],
     'sticbus', None),
    ('stack_row_start', 'intv_stic.sv', [("ec[4:0] == 5'd0 && !rstart ? cs_row : cs", "cs")],
     'sticbus', None),
    ('vdr_minus1', 'intv_stic.sv', [("vdr_l <= vdr_eff;", "vdr_l <= vdr_eff - {2'd0, vdr_eff != 3'd0};")],
     ('screen', 'diner', 30), None),
    ('hdr_minus1', 'intv_stic.sv', [("wire logic [2:0] hd  = r[6'h30][2:0];",
                                     "wire logic [2:0] hd  = r[6'h30][2:0] - {2'd0, r[6'h30][2:0] != 3'd0};")],
     'sticbus', None),
    ('top_ext_off', 'intv_stic.sv', [("&& !(cbr[1] && vcnt < 9'(PF_LINE + 16))", "")], ('screen', 'diner', 30), None),
    ('row_busrq_3lines', 'intv_stic.sv', [("wire logic row_rq   = en_l && d >= 0 && d[3:1] == 3'd0;",
                                           "wire logic row_rq   = en_l && d >= 0 && d[3:0] <= 4'd2;")],
     'astrosmash', None),
    ('frame_busrq_43', 'intv_stic.sv', [("parameter int         FRAME_RQ  = 42,", "parameter int         FRAME_RQ  = 43,")],
     'astrosmash', None),
    ('pattern_select_swapped', 'intv_stic.sv', [("wire logic [7:0] pat = w[11] ? gram_q : grom_q;",
                                                 "wire logic [7:0] pat = w[11] ? grom_q : gram_q;")],
     ('screen', 'towerofdoom', 15), None),
    ('fgbg_grom_256', 'intv_stic.sv', [("wire logic [10:0] c_grom = csmode ? {w[10:3], py} : {2'b00, w[8:3], py};",
                                        "wire logic [10:0] c_grom = {w[10:3], py};")], ('screen', 'towerofdoom', 15), None),
    ('squares_off', 'intv_stic.sv', [("wire logic squares = csmode && w[12] && !w[11];",
                                      "wire logic squares = 1'b0;")], ('screen', 'sewersam', 15), None),
    ('fifo_no_intak_clear', 'intv_stic.sv', [("            if (intak)\n                cnt <= 9'd0;\n", "")],
     'astrosmash', None),
    ('fetch_late_line', 'intv_stic.sv', [("d[3:0] == 4'd1 && hcnt[8:2] == 7'(CPL - 1);",
                                          "d[3:0] == 4'd2 && hcnt[8:2] == 7'(CPL - 1);")], 'astro_nobusrq', None),
    ('enable_live', 'intv_stic.sv', [("wire logic pf_line = en_l &&", "wire logic pf_line = hs &&")],
     'sticbus', None),
    # the border colour: a cycle late, or latched per frame at the window end (D17)
    ('border_cycle_late', 'intv_stic.sv', [("    wire logic [3:0] bcr = r[6'h2C][3:0];",
                                            "    logic [3:0] bcr = 4'd0;\n    always_ff @(posedge clk) if (ce) bcr <= r[6'h2C][3:0];")],
     'sticbus', None),
    ('border_frame_latch', 'intv_stic.sv', [("    wire logic       win_end = ce && slot == 16'(VB_CYCLES - 1);",
                                             "    wire logic       win_end = ce && slot == 16'(VB_CYCLES - 1);\n"
                                             "    logic [3:0] bcr_fl = 4'd0;\n"
                                             "    always_ff @(posedge clk) if (win_end) bcr_fl <= r[6'h2C][3:0];"),
                                            ("pix <= pf_line && pf_x ? (mob_show ? {l_a[12], l_a[2:0]} : pf_c) : bcr;",
                                             "pix <= pf_line && pf_x ? (mob_show ? {l_a[12], l_a[2:0]} : pf_c) : bcr_fl;")],
     'astrosmash', None),
    ('missed_row_loads', 'intv_stic.sv', [("if (!busrq_en || busak) begin", "if (1'b1) begin")], 'sticbus', None),
    ('counter_no_stop', 'intv_stic.sv', [("if (cnt < 9'(SYSW))", "if (1'b1)")], 'sticbus', None),
    ('squares_q12_swapped', 'intv_stic.sv', [("e_fg   = sqc(py[2] ? w[8:6] : w[2:0], csr[cs_use]);",
                                              "e_fg   = sqc(py[2] ? w[5:3] : w[2:0], csr[cs_use]);"),
                                             ("e_bg   = sqc(py[2] ? {w[13], w[10:9]} : w[5:3], csr[cs_use]);",
                                              "e_bg   = sqc(py[2] ? {w[13], w[10:9]} : w[8:6], csr[cs_use]);")],
     'sticbus', None),
    ('ss_rowbuf_wr_lost', 'intv_ram.sv', [("wire logic          wa = ss_en ? ss_we && ss_hit : we;",
                                           "wire logic          wa = ss_en ? ss_we && ss_hit && SS_ID != 8'h0C : we;")],
     'astrosmash', ['rt4']),
    ('ss_linebuf_wr_lost', 'intv_ram.sv', [("wire logic          wa = ss_en ? ss_we && ss_hit : we;",
                                            "wire logic          wa = ss_en ? ss_we && ss_hit && SS_ID != 8'h0D : we;")],
     'astrosmash', ['rt5']),
    ('ss_copy_lost', 'intv_stic.sv', [("8'h35: {cp_ph, cp_j, cp_on, cp_arm, cnt} <= ss_wdata[16:0];",
                                       "8'h35: cnt <= ss_wdata[8:0];")], 'astrosmash', ['rt4']),
    ('ss_latches_lost', 'intv_stic.sv', [("8'h34: {vdr_l, en_l} <= ss_wdata[3:0];", "8'h34: ;")],
     'astrosmash', ['rt4']),
    ('ss_pix_lost', 'intv_stic.sv', [("8'h36: {pix, cs_row, cs} <= ss_wdata[7:0];", "8'h36: {cs_row, cs} <= ss_wdata[3:0];")],
     'astrosmash', ['rt3']),
    # the cartridge port not asked on a write (carttest: cart RAM, page selects)
    ('cart_write_no', 'intv_bus.sv', [("                end else if (phase == PH_DW) begin\n                    cart_req   <= 1'b1;",
                                       "                end else if (phase == PH_DW) begin\n                    cart_req   <= 1'b0;")],
     'cartram', None),
    ('cart_write_low', 'intv_bus.sv', [("                    cart_wdata <= dout;",
                                        "                    cart_wdata <= {8'h00, dout[7:0]};")], 'cartpaged', None),
    # the step-4 review's plants (2026-10-25), kept for their coverage
    ('pastel_fg_dropped', 'intv_stic.sv', [("e_fg   = {w[12], w[2:0]};", "e_fg   = {1'b0, w[2:0]};")], 'sticbus', None),
    ('fgbg_bg_12_13_swapped', 'intv_stic.sv', [("e_bg   = {w[12], w[13], w[10], w[9]};",
                                                "e_bg   = {w[13], w[12], w[10], w[9]};")], 'sticbus', None),
    ('squares_c7_direct', 'intv_stic.sv', [("sqc = c == 3'd7 ? top : {1'b0, c};", "sqc = {1'b0, c};")], 'sticbus', None),
    ('squares_q3_bit2', 'intv_stic.sv', [("e_bg   = sqc(py[2] ? {w[13], w[10:9]} : w[5:3], csr[cs_use]);",
                                          "e_bg   = sqc(py[2] ? {1'b0, w[10:9]} : w[5:3], csr[cs_use]);")], 'sticbus', None),
    ('column_160_shown', 'intv_stic.sv', [("&& xp < 12'sd159;", "&& xp < 12'sd160;")], 'sticbus', None),
    ('left_ext_off', 'intv_stic.sv', [("cbr[0] ? 4'd8 : {1'b0, hd}", "{1'b0, hd}")], 'sticbus', None),
    ('pixel_order_reversed', 'intv_stic.sv', [("lb_q[5'd15 - {2'b0, xx[2:0]}]", "lb_q[5'd8 + {2'b0, xx[2:0]}]")],
     'sticbus', None),
    ('frame_busrq_always', 'intv_stic.sv', [("&& (slot_n == 16'(VB_CYCLES) ? hs_eff : en_l);", ";")], 'nocart', None),
    ('row13_dropped', 'intv_stic.sv', [("wire logic row_rq   = en_l && d >= 0 && d[3:1] == 3'd0;",
                                        "wire logic row_rq   = en_l && d >= 0 && d < 11'sd192 && d[3:1] == 3'd0;"),
                                       ("wire logic fetch_n  = en_l && d >= 0 &&",
                                        "wire logic fetch_n  = en_l && d >= 0 && d < 11'sd192 &&")], 'astrosmash', None),
    ('cs_grom_64', 'intv_stic.sv', [("wire logic [10:0] c_grom = csmode ? {w[10:3], py} : {2'b00, w[8:3], py};",
                                     "wire logic [10:0] c_grom = {2'b00, w[8:3], py};")], 'astrosmash', None),
    ('squares_advance', 'intv_stic.sv', [("            e_bits = 8'hF0;\n",
                                          "            e_bits = 8'hF0;\n            cs_new = cs_use + {1'b0, w[13]};\n")],
     'sticbus', None),
    ('top_ext_moved_by_vdr', 'intv_stic.sv', [("!(cbr[1] && vcnt < 9'(PF_LINE + 16))",
                                               "!(cbr[1] && vcnt < 9'(PF_LINE + 16) + {5'd0, vdr_l, 1'b0})")],
     'sticbus', None),
    ('counter_steps_missed', 'intv_stic.sv', [("                        cp_ph <= 1'b0;\n                    end\n",
                                               "                        cp_ph <= 1'b0;\n                    end else if (cnt < 9'(SYSW))\n"
                                               "                        cnt <= cnt + 9'd20;\n")], 'sticbus', None),
    # the row-load deadline: BUSAK checked one cycle early, one late (sticbus dlb), two late
    ('fetch_deadline_m1', 'intv_stic.sv', [("d[3:0] == 4'd1 && hcnt[8:2] == 7'(CPL - 1);",
                                            "d[3:0] == 4'd0 && hcnt[8:2] == 7'(CPL - 2);")], 'sticbus', None),
    ('fetch_deadline_p1', 'intv_stic.sv', [("d[3:0] == 4'd1 && hcnt[8:2] == 7'(CPL - 1);",
                                            "d[3:0] == 4'd1 && hcnt[8:2] == 7'd0;")], 'sticbus', None),
    ('fetch_deadline_p2', 'intv_stic.sv', [("d[3:0] == 4'd1 && hcnt[8:2] == 7'(CPL - 1);",
                                            "d[3:0] == 4'd1 && hcnt[8:2] == 7'd1;")], 'sticbus', None),
    ('ss_cs_lost', 'intv_stic.sv', [("8'h36: {pix, cs_row, cs} <= ss_wdata[7:0];", "8'h36: pix <= ss_wdata[7:4];")],
     'sticbus', ['rt4', 'rt5']),
    ('ss_cs_row_lost', 'intv_stic.sv', [("8'h36: {pix, cs_row, cs} <= ss_wdata[7:0];",
                                         "8'h36: {pix, cs} <= {ss_wdata[7:4], ss_wdata[1:0]};")],
     'sticbus', ['rt4', 'rt5']),
    # MOBs and collisions (build step 5): sizes, flips, priority, the
    # hardware rules M1-M5, collision pairs, border, background, sweep, and
    # the bits' life (gathered, ORed in at the frame's end, cleared)
    ('mob_xflip_off', 'intv_stic.sv', [("expand(u_pat, u_x[10], u_y[10])", "expand(u_pat, u_x[10], 1'b0)")],
     'sticmob', None),
    ('mob_yflip_off', 'intv_stic.sv', [("u_rw[3:0] ^ (u_y[11] ? {u_y[7], 3'b111} : 4'd0)", "u_rw[3:0]")],
     'sticmob', None),
    ('mob_xsize_off', 'intv_stic.sv', [("expand(u_pat, u_x[10], u_y[10])", "expand(u_pat, 1'b0, u_y[10])")],
     'sticmob', None),
    ('mob_ysiz2_off', 'intv_stic.sv', [("wire logic [1:0]  u_s  = {u_y[9], u_y[8]};",
                                        "wire logic [1:0]  u_s  = {u_y[9], 1'b0};")], 'sticmob', None),
    ('mob_ysiz4_off', 'intv_stic.sv', [("wire logic [1:0]  u_s  = {u_y[9], u_y[8]};",
                                        "wire logic [1:0]  u_s  = {1'b0, u_y[8]};")], 'sticmob', None),
    ('mob_yres_off', 'intv_stic.sv', [("u_rw < (u_y[7] ? 11'd16 : 11'd8)", "u_rw < 11'd8")], 'sticmob', None),
    ('mob_y_line_late', 'intv_stic.sv', [("wire logic signed [11:0] u_dy = uln - 12'({u_top, 1'b0});",
                                          "wire logic signed [11:0] u_dy = uln - 12'({u_top, 1'b1});")],
     'sticmob', None),
    ('mob_x_pixel_late', 'intv_stic.sv', [("k = 11'(nx) - 11'(r[i][7:0]) - 11'(hd) - 11'(PF_X0 - 8);",
                                           "k = 11'(nx) - 11'(r[i][7:0]) - 11'(hd) - 11'(PF_X0 - 7);")],
     'sticmob', None),
    ('mob_x0_drawn', 'intv_stic.sv', [("u_x[7:0] != 8'd0 && u_in ?", "u_in ?")], 'sticmob', None),
    ('mob_order_reversed', 'intv_stic.sv', [("for (int i = 7; i >= 0; i--)\n            if (l_hit[i]) l_w = 3'(i);",
                                             "for (int i = 0; i < 8; i++)\n            if (l_hit[i]) l_w = 3'(i);")],
     'sticmob', None),
    ('mob_prio_ignored', 'intv_stic.sv', [("wire logic mob_show = l_hit != 8'd0 && !(l_a[13] && fg_on);",
                                           "wire logic mob_show = l_hit != 8'd0;")], 'sticmob', None),
    ('mob_pastel_dropped', 'intv_stic.sv', [("(mob_show ? {l_a[12], l_a[2:0]} : pf_c)",
                                             "(mob_show ? {1'b0, l_a[2:0]} : pf_c)")], 'sticmob', None),
    ('mob_invisible_drawn', 'intv_stic.sv', [("wire logic [7:0] l_hit = l_b & l_vis;",
                                              "wire logic [7:0] l_hit = l_b;")], 'sticmob', None),
    ('mob_m1_card_bit0', 'intv_stic.sv', [("        if (u_y[7])\n            u_card[0] = 1'b0;", "")],
     'sticmob', None),
    ('mob_m2_fgbg_grom_256', 'intv_stic.sv', [("if (u_a[11] || !csmode)", "if (u_a[11])")], 'sticmob', None),
    ('mob_gram_card_7bit', 'intv_stic.sv', [("if (u_a[11] || !csmode)\n            u_card[7:6] = 2'b00;",
                                             "if (u_a[11] || !csmode)\n            u_card[7] = 1'b0;")],
     'sticmob', None),
    # M4 broken as MAME has it: the strip a delay uncovers takes the card
    # under it as if there were no delay
    ('coll_m4_strip_on', 'intv_stic.sv', [("wire logic fg_on = yy_l >= 0 && xp >= $signed({9'd0, hd}) &&",
                                           "wire logic fg_on = yy_l >= 0 &&"),
                                          (".addr_b({vcnt[0], xx[7:3]}), .q_b(lb_q),",
                                           ".addr_b({vcnt[0], xp < $signed({9'd0, hd}) ? xp[7:3] : xx[7:3]}), .q_b(lb_q),")],
     'sticmob', None),
    ('coll_bg_no_intr', 'intv_stic.sv', [("wire logic [7:0] l_bg = coll_area && fg_on ? l_b & l_intr : 8'd0;",
                                          "wire logic [7:0] l_bg = coll_area && fg_on ? l_b : 8'd0;")], 'sticmob', None),
    ('coll_m5_squares_c7_on', 'intv_stic.sv', [("            e_on   = {py[2] ? w[8:6] != 3'd7 : w[2:0] != 3'd7,\n"
                                                "                      py[2] ? {w[13], w[10:9]} != 3'd7 : w[5:3] != 3'd7};\n",
                                                "            e_on   = 2'b11;\n")], 'sticmob', None),
    ('coll_bg_off', 'intv_stic.sv', [("if (l_bg[i]) coll_p[i][8] <= 1'b1;", "if (1'b0) coll_p[i][8] <= l_bg[i];")],
     'sticmob', None),
    ('coll_bg_needs_visb', 'intv_stic.sv', [("wire logic [7:0] l_bg = coll_area && fg_on ? l_b & l_intr : 8'd0;",
                                             "wire logic [7:0] l_bg = coll_area && fg_on ? l_b & l_intr & l_vis : 8'd0;")],
     'sticmob', None),
    ('coll_pair_one_way', 'intv_stic.sv', [("                        coll_p[g_j][{1'b0, g_m}] <= 1'b1;\n", "")],
     'sticmob', None),
    ('coll_pair_shift_swapped', 'intv_stic.sv', [("wire logic [15:0] p_sh = (p_d[8] ? p_mi : p_mj) << p_ad[3:0];",
                                                  "wire logic [15:0] p_sh = (p_d[8] ? p_mj : p_mi) << p_ad[3:0];")],
     'sticmob', None),
    ('coll_pair_15', 'intv_stic.sv', [("p_ad < 9'd16 &&", "p_ad < 9'd15 &&")], 'sticmob', None),
    ('coll_sweep_raster_only', 'intv_stic.sv', [("wire logic g_last  = g_ly == 9'd403;",
                                                 "wire logic g_last  = g_ly == 9'd215;")], 'sticmob', None),
    ('coll_border_bottom_p1', 'intv_stic.sv', [("&& g_ly <= 9'd215;", "&& g_ly <= 9'd216;")], 'sticmob', None),
    ('coll_border_top_m1', 'intv_stic.sv', [("g_ly >= (cbr[1] ? 9'd40 : 9'd24)", "g_ly >= (cbr[1] ? 9'd40 : 9'd23)")],
     'sticmob', None),
    ('coll_border_col160_inside', 'intv_stic.sv', [("u_xs + 10'(k) <= 10'(PF_X0 + 158);",
                                                    "u_xs + 10'(k) <= 10'(PF_X0 + 159);")], 'sticmob', None),
    ('coll_border_left_ext_off', 'intv_stic.sv', [("(cbr[0] ? 10'd8 : 10'd0)", "10'd0")], 'sticmob', None),
    ('coll_border_needs_intr_off', 'intv_stic.sv', [("if (u_x[8] && g_bord)", "if (g_bord)")], 'sticmob', None),
    ('coll_no_clear', 'intv_stic.sv', [("                    coll_p[i] <= 10'd0;\n", "")], 'sticmob', None),
    ('coll_not_sticky', 'intv_stic.sv', [("r[6'h18 + 6'(i)] <= (c_wr[i] ? wdata[13:0] : r[6'h18 + 6'(i)]) & keep(6'h18 + 6'(i))",
                                          "r[6'h18 + 6'(i)] <= (c_wr[i] ? wdata[13:0] : 14'd0) & keep(6'h18 + 6'(i))")],
     'sticmob', None),
    # the frame's end overwrites a CPU write to $18-$1F in the same cycle
    # (step-5 review; systest p11)
    ('coll_frame_end_drops_write', 'intv_stic.sv', [("r[6'h18 + 6'(i)] <= (c_wr[i] ? wdata[13:0] : r[6'h18 + 6'(i)]) & keep(6'h18 + 6'(i))",
                                                     "r[6'h18 + 6'(i)] <= r[6'h18 + 6'(i)] & keep(6'h18 + 6'(i))")],
     'systest', None),
    ('coll_cpu_write_kept', 'intv_stic.sv', [("            if (we && open) begin\n                if (n < 6'(NREG))\n",
                                              "            if (we && open) begin\n                if (n < 6'(NREG) && !(n >= 6'h18 && n < 6'h20 && wdata[9:0] == 10'd0))\n")],
     'sticmob', None),
    # the step-5 review's plants (sticmob scenes S18-S21 catch the first
    # seven; the review's 'sweep ends at 402' is equivalent: line 403 is
    # the last of an 8-line pattern row whose other lines 396-402 the
    # sweep still covers, so it is replaced by 'ends at 395')
    ('coll_bg_bottom_m1', 'intv_stic.sv', [
        ("&& vcnt <= 9'(PF_LINE + 191)",
         "&& vcnt <= 9'(PF_LINE + 190)")],
     'sticmob', None),
    ('coll_bg_right_m1', 'intv_stic.sv', [("&& xp <= 12'sd158;", "&& xp <= 12'sd157;")], 'sticmob', None),
    ('coll_bg_left_ext_off', 'intv_stic.sv', [
        ("xp >= $signed({8'd0, cbr[0] ? 4'd8 : 4'd0})",
         "xp >= $signed({8'd0, 4'd0})")],
     'sticmob', None),
    ('coll_bg_top_ext_off', 'intv_stic.sv', [
        ("vcnt >= (cbr[1] ? 9'(PF_LINE + 16) : 9'(PF_LINE))",
         "vcnt >= 9'(PF_LINE)")],
     'sticmob', None),
    ('mob_yflip_yres_halves', 'intv_stic.sv', [("{u_y[7], 3'b111}", "4'b0111")], 'sticmob', None),
    ('coll_sweep_from_9', 'intv_stic.sv', [("g_ly <= 9'd8;", "g_ly <= 9'd9;")], 'sticmob', None),
    ('coll_sweep_to_395', 'intv_stic.sv', [("g_ly == 9'd403;", "g_ly == 9'd395;")], 'sticmob', None),
    ('coll_pair_needs_visb', 'intv_stic.sv', [
        ("gm[g_m] <= u_x[8] ? u_mask : 16'd0;",
         "gm[g_m] <= u_x[8] && u_x[9] ? u_mask : 16'd0;")],
     'sticmob', None),
    ('coll_sweep_no_gok', 'intv_stic.sv', [
        ("                    else if (g_ok) begin\n                        g_ph <= 1'b0;",
         "                    else begin\n                        g_ph <= 1'b0;")],
     'sticmob', None),
    ('coll_pair_no_intr', 'intv_stic.sv', [
        ("gm[g_m] <= u_x[8] ? u_mask : 16'd0;",
         'gm[g_m] <= u_mask;')],
     'sticmob', None),
    ('mob_xflip_xsize_off', 'intv_stic.sv', [
        ('expand[k] = xf ? p[k / 2] : p[7 - k / 2];',
         'expand[k] = p[7 - k / 2];')],
     'sticmob', None),
    ('mob_vdr_ignored', 'intv_stic.sv', [("8'd4 + 8'(vdr_l);", "8'd4;")], 'sticmob', None),
    ('mob_hdr_ignored_draw', 'intv_stic.sv', [
        ("k = 11'(nx) - 11'(r[i][7:0]) - 11'(hd) - 11'(PF_X0 - 8);",
         "k = 11'(nx) - 11'(r[i][7:0]) - 11'(PF_X0 - 8);")],
     'sticmob', None),
    ('coll_border_left_by_hdr', 'intv_stic.sv', [
        ("(cbr[0] ? 10'd8 : 10'd0);",
         "(cbr[0] ? 10'd8 : 10'(hd));")],
     'sticmob', None),
    ('coll_border_hdr_ignored', 'intv_stic.sv', [
        ("wire logic [9:0] u_xs = 10'(u_x[7:0]) + 10'(hd) + 10'(PF_X0 - 8);",
         "wire logic [9:0] u_xs = 10'(u_x[7:0]) + 10'(PF_X0 - 8);")],
     'sticmob', None),
    ('mob_m3_prio_then_order', 'intv_stic.sv', [
        ("    wire logic [13:0] l_a  = r[{3'b010, l_w}];",
         "    logic [2:0] l_w2;\n    wire logic [13:0] l_a  = r[{3'b010, l_w2}];"),
        ("wire logic mob_show = l_hit != 8'd0 && !(l_a[13] && fg_on);",
         "logic [7:0] l_pr;\n    always_comb for (int i = 0; i < 8; i++) l_pr[i] = r[6'h10 + 6'(i)][13];\n    wire logic [7:0] l_hm = l_hit & ~(fg_on ? l_pr : 8'd0);\n    always_comb begin l_w2 = 3'd0; for (int i = 7; i >= 0; i--) if (l_hm[i]) l_w2 = 3'(i); end\n    wire logic mob_show = l_hm != 8'd0;")],
     'sticmob', None),
    # state port: the new words (the sweep, its masks, the line masks, the
    # gathered bits) left out of the restore
    ('ss_sweep_lost', 'intv_stic.sv', [("8'h37: {g_on, g_ph, g_f, g_j, g_m, g_ly} <= ss_wdata[17:0];", "8'h37: ;")],
     'sticmob', ['rt6', 'rt8']),
    ('ss_sweep_masks_lost', 'intv_stic.sv', [("8'h38, 8'h39, 8'h3A, 8'h3B: {gm[{ss_w[1:0], 1'b1}], gm[{ss_w[1:0], 1'b0}]} <= ss_wdata;",
                                              "8'h38, 8'h39, 8'h3A, 8'h3B: ;")], 'sticmob', ['rt8']),
    ('ss_line_masks_lost', 'intv_stic.sv', [("8'h3C, 8'h3D, 8'h3E, 8'h3F: {rm[{ss_w[1:0], 1'b1}], rm[{ss_w[1:0], 1'b0}]} <= ss_wdata;",
                                             "8'h3C, 8'h3D, 8'h3E, 8'h3F: ;")], 'sticmob', ['rt7']),
    ('ss_coll_lost', 'intv_stic.sv', [("8'h40: {coll_p[2], coll_p[1], coll_p[0]} <= ss_wdata[29:0];", "8'h40: ;")],
     'sticmob', ['rt6', 'rt7']),
    # build step 9, the ECS: a page decode that takes any page but 1 for $7000 (IntyBASIC's $F would
    # leave it in), the RAM read 16 bits wide, a byte write landing in all four cells of a word, the
    # keyboard groups not widened through the columns (no masking: MAME's AND), PSG #2 with the
    # 8914's two envelope bits, the UART's status 0 (MAME's), the ECS not owning its RAM (a
    # cartridge at $4000 answering too: cart4000 with the ECS forced on), the mixed sound not
    # saturated (wraps), the ECS's latches written while it is off
    ('ecs_page_any', 'intv_cart.sv', [("(ba[15:12] == 4'h7 && ecs_pg[7:4] == 4'd0)",
                                       "(ba[15:12] == 4'h7 && ecs_pg[7:4] != 4'd1)")], 'ecstest', None),
    ('ecs_ram_16', 'intv_ecs.sv', [("else if (sel_ram) q = {8'h00, ram_q[8 * a[1:0] +: 8]};",
                                    "else if (sel_ram) q = {ram_q[8 * a[1:0] +: 8], ram_q[8 * a[1:0] +: 8]};")],
     'ecstest', None),
    ('ecs_ram_word_write', 'intv_ecs.sv', [("4'b0001 << a[1:0];", "4'hF;")], 'ecstest', None),
    ('ecs_no_masking', 'intv_ecs.sv', [("            r0 <= r0 | to_rows(c0, k);\n", "            r0 <= r0;\n"),
                                       ("            r1 <= r1 | to_rows(c1, k);\n", "            r1 <= r1;\n")],
     'ecstest', None),
    ('ecs_env2', 'intv_ecs.sv', [(".ENV2(1'b0)", ".ENV2(1'b1)")], 'ecstest', None),
    ('ecs_uart_0', 'intv_ecs.sv', [("a[1:0] == 2'd0 ? 16'h0002 : 16'h0000", "16'h0000")], 'ecstest', None),
    ('ecs_ram_not_owned', 'intv_cart.sv', [("ba[15:11] == 5'b01000));", "1'b0));")], 'cart4000_on', None),
    # step 10: the Intellivoice: mapped while off (reads $0000 / $8000, not the pull-ups), the level's
    # x2 lost, the voice added to the mix as unsigned (its negative half wraps), the DAC sound's bits
    # (voicetest makes no PSG sound, so the mix's saturation is not reached here: VOICE_NOTES 8.7)
    ('voice_mapped_off', 'intv_voice.sv', [("assign hit = on && sel;", "assign hit = sel;")], 'voice_off', None),
    ('voice_level2_lost', 'intv_voice.sv', [("3'd4: g = v <<< 1;", "3'd4: g = v;")], 'voicetest', None),
    ('voice_mix_unsigned', 'intv_machine.sv', [("wire logic signed [17:0] vsum = $signed({2'b00, psgs}) + 18'(v_out);",
                                               "wire logic signed [17:0] vsum = $signed({2'b00, psgs}) + $signed({2'b00, v_out});")],
     'voicedac', None),
    ('voice_dac_bits', 'intv_voice.sv', [("($signed(c_sample) >>> 7) <<< 9", "($signed(c_sample) >>> 6) <<< 8")], 'voicedac', None),
    # the PSG sum's saturation dropped: voicemix (both PSGs at full volume, the ECS on) takes the
    # 3/4 sum past 32,767 (ecstest, its image until step 10, never reaches it)
    ('ecs_mix_wraps', 'intv_machine.sv', [("wire logic [15:0] psgs = mixs[18:15] != 4'd0 ? 16'h7FFF : mixs[15:0];",
                                          "wire logic [15:0] psgs = mixs[15:0];")], 'voicemix', None),
    # the ECS level (the module's own knob): ignored, PSG #2 always x1 (ecssound_l4: Loudest)
    ('ecs_level_ignored', 'intv_machine.sv', [("        case (ecs_level)", "        case (3'd2)")], 'ecssound_l4', None),
    # step 11: the JLP (each caught by one of its cartridges, RTL = model through System RAM and the
    # JLP's state words): x / 0 recomputing, the CRC's reset value, JF.first, a write to a row not
    # empty taken, a short busy window, the RAM window one word off (the CPU's accesses alone, so the
    # flash engine's copy shows it), the switch not hiding the registers, a result word not restored
    # (round trip rt1, after the result's write), the random update's cycle number
    ('jlp_div0_updates', 'intv_jlp.sv', [("end else if (op_b != 16'd0) begin", "end else begin")], 'jlpdiv', None),
    ('jlp_crc_reset0', 'intv_jlp.sv', [("crc <= 16'hFFFF; rnd <= 16'hFFFF;", "crc <= 16'h0000; rnd <= 16'hFFFF;")],
     'jlpdiv', None),
    ('jlp_first_off', 'intv_jlp.sv', [("localparam logic [15:0] FIRST = 16'h00E0;", "localparam logic [15:0] FIRST = 16'h00E1;")],
     'jlpfls', None),
    ('jlp_full_row_written', 'intv_jlp.sv', [("(cmd == 2'd2 || empt[row7])", "(cmd == 2'd2 || 1'b1)")], 'jlpfls', None),
    ('jlp_busy_short', 'intv_jlp.sv', [("left <= 16'(BUSY - 1);", "left <= 16'd2;")], 'jlpfls', None),
    ('jlp_ram_off_by_one', 'intv_cart.sv', [("m_addr    <= JLP_BASE + {4'd0, j_off[12:0]};",
                                             "m_addr    <= JLP_BASE + {4'd0, j_off[12:0]} + 17'd1;")], 'jlpfls', None),
    ('jlp_off_answers', 'intv_jlp.sv', [("wire logic sel_rd = on && intv_jlp_pkg::reg_rd(a);",
                                         "wire logic sel_rd = intv_jlp_pkg::reg_rd(a);")], 'jlpena', None),
    ('jlp_ss_result_lost', 'intv_jlp.sv', [("5'd13: res0 <= ss_wdata[15:0];", "5'd13: ;")], 'jlpmul', ['rt1']),
    ('jlp_rnd_cycle', 'intv_jlp.sv', [("cr_v <= rnd ^ cyc;", "cr_v <= rnd ^ (cyc + 16'd1);")], 'jlpdiv', None),
    # the final saturation (the voice on top of the PSGs' sum) dropped: voicemix drives it past 32,767
    ('voice_mix_unsat', 'intv_machine.sv', [("assign audio     = vsum > 18'sd32767 ? 16'h7FFF : vsum < -18'sd32768 ? 16'h8000 : vsum[15:0];",
                                            "assign audio     = vsum[15:0];")], 'voicemix', None),
    # the step-9 review: the sum not scaled to 3/4 with the ECS attached (ecsastro: Auto, attached)
    # or on (ecstest), or scaled with the ECS off too (psgtest: PSG #1 alone at full volume)
    ('ecs_mix_unscaled', 'intv_machine.sv', [("ecs_on ? mix3[20:2] : mix;", "mix;")], 'ecstest', None),
    ('ecs_mix_scaled_off', 'intv_machine.sv', [("ecs_on ? mix3[20:2] : mix;", "mix3[20:2];")], 'psgtest', None),
    ('ecs_latch_when_off', 'intv_ecs.sv', [("        end else if (on) begin\n", "        end else begin\n")],
     'ecstest_off', None),
    # the step-9 review: the ECS ROMs answering with no ECS ROM slot (uninitialised SRAM at
    # $10000-$12FFF); intv_ecs reporting attached as fully on (the keyboard would leave the keypad)
    ('ecs_rom_ok_ignored', 'intv_cart.sv', [("wire logic e_rom = ecs_on && ecs_rom_ok &&", "wire logic e_rom = ecs_on &&")],
     'ecsnorom', None),
    ('ecs_full_attached', 'intv_ecs.sv', [("assign full = mode_q == M_ON;", "assign full = mode_q != M_OFF;")],
     'ecsastro', None),
    ('ecs_answers_when_off', 'intv_ecs.sv', [("assign hit = on && (sel_uart", "assign hit = (sel_uart")],
     'ecstest_off', None),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--all', action='store_true', help='images, MAME, then planted faults')
    ap.add_argument('--only', help='comma-separated image names (nocart, astrosmash, systest, '
                                   'psgtest, cartram, cartpaged, ...)')
    ap.add_argument('--no-build', action='store_true')
    ap.add_argument('--plants-only', action='store_true')
    ap.add_argument('--plant', help='comma-separated plant names')
    ap.add_argument('--mame', action='store_true', help='also compare the model with MAME traces')
    ap.add_argument('--screens', action='store_true', help='the step-4 frame gate (SCREENS)')
    ap.add_argument('--play', action='store_true', help='the step-6 play bench (PLAY)')
    ap.add_argument('--ecs-play', action='store_true', help='the step-9 ECS runs (ECS_PLAY)')
    a = ap.parse_args()
    verilator = os.environ.get('VERILATOR', 'verilator')
    work = os.environ.get('WORK', os.path.join(ROOT, 'sim', 'work', 'tb_system'))
    lib = os.environ.get('INTV_LIBRARY', os.path.expanduser('~/ROMLibrary/Intellivision'))
    bdir = os.environ.get('INTV_BIOS_DIR', os.path.expanduser('~/pocket_projects/intellivision/bios'))
    troot = os.environ.get('INTV_TRACE_ROOT')
    exec_path, grom_path = os.path.join(bdir, 'exec.bin'), os.path.join(bdir, 'grom.bin')
    os.makedirs(work, exist_ok=True)
    os.environ['INTV_BIOS_DIR'] = bdir

    if a.screens:
        return screens_main(a, verilator, work, lib, exec_path, grom_path)
    if a.play:
        return play_main(a, verilator, work, lib, exec_path, grom_path)
    if a.ecs_play:
        return ecs_play_main(a, verilator, work, lib, exec_path, grom_path)

    imgs = IMAGES
    if a.only:
        imgs = [i for i in IMAGES + HW_IMAGES if i[0] in a.only.split(',')]
    carts = {}
    execs = {}
    exps = {}
    pads = {}
    fails = []
    t0 = time.time()
    try:
        for name, zipname, prog, nframes, pad, smode in imgs:
            cart = None
            if isinstance(zipname, tuple) and zipname[0] == 'step8':
                cart, _ = step8_image(zipname[1], work)
            elif isinstance(zipname, tuple) and zipname[0] == 'step9':
                cart = step9_image(zipname[1], work)
            elif isinstance(zipname, tuple) and zipname[0] == 'hw':
                cart = hw_image(zipname[1], work)
            elif isinstance(zipname, tuple) and zipname[0] == 'jlp':
                cart = jlp_image(zipname[1], work)
            elif isinstance(zipname, tuple):        # synthetic, CRC forced to a table entry
                cart = os.path.join(work, name + '.bin')
                with open(cart, 'wb') as f:
                    f.write(synth_image.forced(zipname[1], zipname[2]))
            elif zipname:
                cart = os.path.join(work, name + '.bin')
                with open(cart, 'wb') as f:
                    f.write(m.load_image_bytes(os.path.join(lib, zipname)))
            carts[name] = cart
            pads[name] = pad
            ex = exec_path
            if prog == 'voicetest.py':
                ex = os.path.join(work, name + '_exec.bin')
                subprocess.run([sys.executable, '-I', os.path.join(TESTROMS, prog), ex], check=True)
            elif prog:
                ex = os.path.join(work, name + '_exec.bin')
                with open(os.path.join(TESTROMS, prog), encoding='utf-8') as f:
                    pr = as1610.assemble(f.read(), romw=10)
                img = bytearray(8192)
                for a_, w in pr.words.items():
                    if not 0x1000 <= a_ < 0x2000:
                        sys.exit('%s: word outside $1000-$1FFF' % prog)
                    if w > 0x3FF:       # the EXEC ROM keeps 10 bits: an operand would be cut
                        sys.exit('%s: word $%04X at $%04X is over 10 bits' % (prog, w, a_))
                    img[2 * (a_ - 0x1000)] = w >> 8
                    img[2 * (a_ - 0x1000) + 1] = w & 0xFF
                with open(ex, 'wb') as f:
                    f.write(img)
            execs[name] = ex
            exps[name] = model_run(ex, grom_path, cart, nframes * FRAME, pad, smode, ECS_OF.get(name),
                                   VOICE_OF.get(name))
            exps[name].name = name
            e = exps[name]
            if name in ECS_OF:
                p9 = ecs_selfcheck(name, e)
                print('  %s ECS self-check: %s' % (name, 'pass' if not p9 else 'FAIL: ' + '; '.join(p9)))
                if p9:
                    fails.append('ECS_SELFCHECK ' + name)
            print('model %s (STIC mode %s): %d bus phases, %d step starts, %d latch changes in %d cycles; '
                  '%d pictures with the display on, %d rows loaded, %d missed' % (
                      name, smode, len(e.blog), len(e.steps), len(e.mlog), e.ncyc,
                      sum(1 for x in e.bus.vid.stats if x['enabled']),
                      sum(1 for g, *_ in e.sinfo.values() for f in g if f[1]),
                      sum(1 for g, *_ in e.sinfo.values() for f in g if not f[1])))
            if prog == 'sticbus.asm':
                # the row-load deadline: BUSAK exactly at R + 57 loads, at R + 58 misses
                dl = [(d, ok) for _, _, d, ok in e.bus.deadline]
                miss = [x for x in ((0, True), (1, False)) if x not in dl]
                print('  sticbus deadline: BUSAK at R + 57 (loaded) %d, at R + 58 (missed) %d%s' % (
                    dl.count((0, True)), dl.count((1, False)),
                    '' if not miss else ' FAIL: missing %s' % miss))
                if miss or any((d <= 0) != ok for d, ok in dl):
                    fails.append('STICBUS_DEADLINE')
            if prog == 'sticmob.asm':
                # the STIC test checks itself (sysram $0303 fails, $0306 passes)
                ram = e.snaps[e.ncyc]['sysram']
                ok = ram[0x103] == 0 and ram[0x106] >= 1
                print('  sticmob self-check: %d passes, %d fails%s' % (
                    ram[0x106], ram[0x103], '' if ok else ' (last in frame %d) FAIL' % ram[0x105]))
                if not ok:
                    fails.append('STICMOB_SELFCHECK')
            if prog == 'cart8test.asm':
                p8 = cart8_selfcheck(e, cart)
                print('  cart8test self-check: %s' % ('the image\'s words, the RAM and the windows as written'
                                                      if not p8 else 'FAIL: ' + '; '.join(p8)))
                if p8:
                    fails.append('CART8_SELFCHECK ' + name)
            if name in VOICE_OF:
                nz = sum(1 for _, v in e.vsamples if v)
                print('  %s voice (%s): %d samples, %d not 0' % (name, VOICE_OF[name]['ovr'], len(e.vsamples), nz))
                if (VOICE_OF[name]['ovr'] == 'on') != (nz > 1000):
                    fails.append('VOICE_MODEL ' + name)
            if prog == 'systest.asm':
                p7 = check_sect7(e, pr.symbols)
                print('  systest section 7: %s' % ('every probe in its slot' if not p7 else '; '.join(p7)))
                fails += p7
            if cart and e.bus.cart is not None:
                cw = sum(1 for b in e.blog if b[1] == PHASE['DW'] and e.bus.cart.read(b[2]) is not None)
                sw = sum(1 for b in e.blog if b[1] == PHASE['DW'] and (b[2] & 0xFFF) == 0xFFF
                         and b[3] >> 4 == (b[2] >> 12) << 8 | 0xA5)
                print('  %s: %d writes to cartridge RAM/ROM, %d page selects' % (name, cw, sw))
            if (a.all or a.mame) and troot and not prog and name in ('nocart', 'astrosmash'):
                tr = os.path.join(troot, 'none' if name == 'nocart' else name, 'trace.log')
                if os.path.exists(tr):
                    sys.stdout.write('  MAME %s: ' % name)
                    if not isys.mame_compare(tr, bdir, cart):
                        fails.append('MAME ' + name)
                else:
                    print('  MAME %s: no trace at %s' % (name, tr))
                    fails.append('MAME trace ' + name)
        print('expectations: %.1fs' % (time.time() - t0))

        binary = os.path.join(work, 'obj', 'tb_system')
        if not a.no_build:
            t1 = time.time()
            binary = build(work, CORE, verilator)
            if not binary:
                print('TB_SYSTEM_ALL FAIL (build)')
                return 1
            print('build: %.1fs' % (time.time() - t1))
        if not a.plants_only:
            for name, _, _, _, _, _ in imgs:
                p = check_image(binary, work, name, execs[name], grom_path, carts[name], exps[name],
                                pads[name])
                if p:
                    fails += p
                    print('TB_SYSTEM %s FAIL' % name)
                else:
                    print('TB_SYSTEM %s pass' % name)

        if a.all or a.plants_only or a.plant:
            sel = a.plant.split(',') if a.plant else None
            for pname, f, edits, img, runs in PLANTS:
                if sel and pname not in sel:
                    continue
                if not isinstance(img, tuple) and img not in exps:
                    continue
                d = os.path.join(work, 'plant_' + pname)
                shutil.rmtree(d, ignore_errors=True)
                os.makedirs(os.path.join(d, 'rtl'))
                for x in RTL + INC:
                    shutil.copy(os.path.join(CORE, x), os.path.join(d, 'rtl', x))
                p = os.path.join(d, 'rtl', f)
                s = open(p).read()
                if not all(frm in s for frm, _ in edits):
                    print('PLANT %s: pattern not found' % pname)
                    fails.append('plant ' + pname)
                    continue
                for frm, to in edits:
                    s = s.replace(frm, to, 1)
                open(p, 'w').write(s)
                b = build(d, os.path.join(d, 'rtl'), verilator, strict=False)
                if not b:
                    print('PLANT %s: build failed' % pname)
                    fails.append('plant ' + pname)
                    continue
                if isinstance(img, tuple):        # ('screen', name, pictures)
                    sc = [x for x in SCREENS if x[0] == img[1]][0]
                    c = screen_cart(d, sc[0], sc[1], lib)
                    try:
                        pr = check_screen(b, d, sc[0], c, exec_path, grom_path, img[2], verbose=False)
                    finally:
                        if c:
                            os.remove(c)
                else:
                    pr = check_image(b, d, img, execs[img], grom_path, carts[img], exps[img], pads[img],
                                     verbose=False, only_runs=runs or ['straight'])
                if pr:
                    print('PLANT %s: caught: %s' % (pname, pr[0][:150]))
                else:
                    print('PLANT %s: not caught' % pname)
                    fails.append('plant ' + pname)
    finally:
        for c in carts.values():
            if c and os.path.exists(c):
                os.remove(c)
    print('TB_SYSTEM_ALL %s' % ('pass' if not fails else 'FAIL (%s)' % ', '.join(fails[:6])))
    return 1 if fails else 0


def screens_main(a, verilator, work, lib, exec_path, grom_path):
    """The step-4 frame gate (--screens)."""
    sel = SCREENS
    if a.only:
        sel = [x for x in SCREENS if x[0] in a.only.split(',')]
    binary = os.path.join(work, 'obj', 'tb_system')
    if not a.no_build:
        t1 = time.time()
        binary = build(work, CORE, verilator)
        if not binary:
            print('TB_SCREENS FAIL (build)')
            return 1
        print('build: %.1fs' % (time.time() - t1))
    fails = []
    for name, zipname, npics in sel:
        cart = screen_cart(work, name, zipname, lib)
        try:
            p = check_screen(binary, work, name, cart, exec_path, grom_path, npics)
        finally:
            if cart:
                os.remove(cart)
        print('TB_SCREEN %s %s' % (name, 'FAIL' if p else 'pass'))
        fails += ['%s: %s' % (name, x) for x in p]
    print('TB_SCREENS %s' % ('pass' if not fails else 'FAIL (%s)' % ', '.join(fails[:4])))
    return 1 if fails else 0


def ecs_play_main(a, verilator, work, lib, exec_path, grom_path):
    """The step-9 ECS runs (--ecs-play, ECS_PLAY): RTL = model (mode stic) frame by frame, PSG #2
    and the mixed sound included (E lines); the model's ECS mode must be the Auto rule's."""
    import ecs as ecsm
    sel = ECS_PLAY
    if a.only:
        sel = [x for x in ECS_PLAY if x[0] in a.only.split(',')]
    binary = os.path.join(work, 'obj', 'tb_system')
    if not a.no_build:
        t1 = time.time()
        binary = build(work, CORE, verilator)
        if not binary:
            print('TB_ECS_PLAY FAIL (build)')
            return 1
        print('build: %.1fs' % (time.time() - t1))
    fails = []
    for name, cart_spec, nframes, ptext, ecs in sel:
        presses = isys.parse_presses(ptext)
        if isinstance(cart_spec, tuple):
            cart = step9_image(cart_spec[1], work)
        else:
            cart = screen_cart(work, name, cart_spec, lib)
        try:
            print('%s: keys %s' % (name, ptext[:200]))
            p = check_screen(binary, work, name, cart, exec_path, grom_path, nframes, presses=presses, ecs=ecs)
            dev = model_stream.bus.ecs
            print('  %s: model ECS mode %s' % (name, ecsm.MODE_NAMES[dev.mode] if dev else None))
        finally:
            if cart and not isinstance(cart_spec, tuple):
                os.remove(cart)
        print('TB_ECS_PLAY %s %s' % (name, 'FAIL' if p else 'pass'), flush=True)
        fails += ['%s: %s' % (name, x) for x in p]
    print('TB_ECS_PLAY_ALL %s' % ('pass' if not fails else 'FAIL (%s)' % ', '.join(fails[:4])))
    return 1 if fails else 0


def play_main(a, verilator, work, lib, exec_path, grom_path):
    """The step-6 play bench (--play, PLAY)."""
    sel = PLAY
    if a.only:
        sel = [x for x in PLAY if x[0] in a.only.split(',')]
    proot = os.environ.get('INTV_PLAY_ROOT')
    binary = os.path.join(work, 'obj', 'tb_system')
    if not a.no_build:
        t1 = time.time()
        binary = build(work, CORE, verilator)
        if not binary:
            print('TB_PLAY FAIL (build)')
            return 1
        print('build: %.1fs' % (time.time() - t1))
    fails = []
    for name, zipname, nframes, ptext in sel:
        presses = isys.parse_presses(ptext)
        cart = screen_cart(work, name, zipname, lib)
        try:
            print('%s: keys %s' % (name, ptext))
            p = check_screen(binary, work, name, cart, exec_path, grom_path, nframes, presses=presses,
                             peeks=PLAY_PEEKS.get(name))
            print('TB_PLAY %s RTL = model (mode stic) %s' % (name, 'FAIL' if p else 'pass'))
            if proot and any(isinstance(x[2], tuple) for x in presses):
                print('  MAME side: none for Pocket presses (research/golf/NOTES.md has the MAME measurement)')
            elif proot:
                ref = os.path.join(proot, name)
                snaps = ','.join(str(n) for n in range(PLAY_SNAP_STEP, nframes + 1, PLAY_SNAP_STEP))
                for what, cmd in (
                        ('frames', [sys.executable, '-I', os.path.join(ROOT, 'tools', 'stic_frames.py'),
                                    'compare', '--mode', 'mame', '--cart', cart, '--ref',
                                    os.path.join(ref, 'frames'), '--snaps', snaps, '--press', ptext]),
                        ('PSG', [sys.executable, '-I', os.path.join(ROOT, 'tools', 'psg_compare.py'),
                                 'compare', ref, '--cart', cart, '--frames', str(nframes),
                                 '--press', ptext, '--name', name])):
                    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       universal_newlines=True)
                    lines = r.stdout.strip().splitlines()
                    keep = [x for x in lines if 'DIFFER' in x or 'pass' in x or 'FAIL' in x
                            or 'log equal' in x or 'steps equal' in x]
                    for x in keep[-6:]:
                        print('    ' + x)
                    ok = r.returncode == 0 and lines and ' pass' in lines[-1]
                    print('TB_PLAY %s MAME %s = model (mode mame) %s' % (name, what, 'pass' if ok else 'FAIL'))
                    if not ok:
                        p = p + ['MAME %s' % what]
            else:
                print('  MAME side skipped (INTV_PLAY_ROOT not set)')
        finally:
            if cart:
                os.remove(cart)
        print('TB_PLAY %s %s' % (name, 'FAIL' if p else 'pass'))
        fails += ['%s: %s' % (name, x) for x in p]
    print('TB_PLAY_ALL %s' % ('pass' if not fails else 'FAIL (%s)' % ', '.join(fails[:4])))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
