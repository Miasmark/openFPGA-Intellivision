#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""The save-state blob (docs/DESIGN.md 4; docs/SAVESTATE.md): the one place where the
module ids, their word counts and the blob layout are written down.

Everything else is generated from LAYOUT below or checked against it:
  src/fpga/core/intv_ss_pkg.sv   the RTL package (ids, sizes, the blob word -> state
                                 address function used by intv_ss_ctl.sv)
  docs/SAVESTATE.md              the table between the GENERATED markers
  the SS_ID defaults of the RTL modules and intv_machine's parameters (checked only)

The blob (format version 5, build step 11; 4 was step 10's, 3 step 9's, 2 step 8's, 1 step 7's) is 153,600 bytes (DESIGN decision 6),
32-bit words stored big-endian (the Pocket's bridge byte order):
  bytes 0-63        header, 16 words (HEADER below)
  bytes 64-8191     the modules' state words in id order (1,853 used; the rest zero)
  bytes 8192-40959  cart RAM, the 16K cells of the SRAM's cart RAM area, two per word
                    (cell 2k in bits 31-16)
  bytes 40960-56959 JLP RAM, its 8,000 words ($8040-$9F7F, the SRAM at $1C000), two per word
                    (version 5; zero without a JLP)
  bytes 56960-      reserved: zero
The payload is bytes 64 .. 64 + length - 1 (length in the header); its CRC32 (zlib's
CRC-32, the same as the cartridge CRC) is in the header. A blob is refused unless the
magic, version, size, length, cartridge CRC and length, the CFG's CRC, flags, word
counts and the EXEC and GROM CRCs match this core, its cartridge (and CFG) and its system
ROMs, the ECS flag and ECS ROM CRC (version 3: the ECS attached or not, and with which ROM),
the Intellivoice flag (version 4: on or off), the JLP RAM's cell count (version 5),
the reserved header words and the reserved area are
zero, and the payload CRC is right.

Usage:
  python3 -I tools/savestate.py gen [--check]   write (or check) the package and the doc table
  python3 -I tools/savestate.py verify BLOB [--cart-crc X] [--cart-words N] [--cfg-crc X]
  python3 -I tools/savestate.py show BLOB
  python3 -I tools/savestate.py selftest
"""
import argparse
import os
import struct
import sys
import zlib

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
PKG = os.path.join(ROOT, 'src', 'fpga', 'core', 'intv_ss_pkg.sv')
DOC = os.path.join(ROOT, 'docs', 'SAVESTATE.md')

# ------------------------------------------------------------------ the layout
# (id, name, words, RTL file, its SS_ID parameter, what the words hold).
# A module with more than 256 words takes the next ids too (256 words per id).
LAYOUT = [
    (0x01, 'timing', 1, 'intv_timing.sv', 'SS_ID',
     'machine position mpos {vcnt, hcnt, sub}'),
    (0x02, 'cpu', 8, 'cp1610.sv', 'SS_ID',
     'R0-R7, sequence state, flags, request lines'),
    (0x03, 'bus', 2, 'intv_bus.sv', 'SS_ID',
     'latched address, hold, IAB, cartridge answer'),
    (0x04, 'stic', 67, 'intv_stic.sv', 'SS_ID',
     'registers, handshake, row fetch, card engine, MOB sweep'),
    (0x05, 'psg', 21, 'intv_psg.sv', 'SS_ID',
     'registers, tone/noise/envelope counters, LFSR'),
    (0x06, 'scratch', 256, 'intv_ram.sv', None,
     'scratchpad RAM 256 x 8'),
    (0x07, 'sysram', 352, 'intv_ram.sv', None,
     'System RAM 352 x 16 (ids $07-$08)'),
    (0x09, 'gram', 512, 'intv_ram.sv', None,
     'GRAM 512 x 8 (ids $09-$0A)'),
    (0x0B, 'cart', 16, 'intv_cart.sv', 'SS_ID',
     'load results (read only), page selects, Intellicart bank registers'),
    (0x0C, 'row', 20, 'intv_ram.sv', None,
     "the STIC's row buffer 20 x 14"),
    (0x0D, 'line', 64, 'intv_ram.sv', None,
     "the STIC's line buffer 64 x 18"),
    (0x0E, 'ecs', 1, 'intv_ecs.sv', 'SS_ID',
     'ECS page latches $2/$7/$E, port latches, mode (step 9)'),
    (0x0F, 'psg2', 21, 'intv_psg.sv', None,
     'PSG #2 (ECS, AY-3-8917): as psg'),
    (0x10, 'ecsram', 512, 'intv_ecs.sv', None,
     'ECS RAM 2,048 x 8, four cells a word (ids $10-$11)'),
    (0x18, 'voice', 24, 'intv_voice.sv', 'SS_ID',
     'Intellivoice: SP0256 sequencer, parameters, decoded copy, filter, the sample enable and busy window (step 10)'),
    (0x19, 'voicefifo', 64, 'intv_ram.sv', None,
     "the SPB640's FIFO 64 x 10 (step 10)"),
    (0x20, 'jlp', 28, 'intv_jlp.sv', 'SS_ID',
     'JLP: switch and busy count, multiply / divide operands and results, CRC, random, flash registers, '
     'extended registers, the cycle count (step 11; its RAM is the JLP RAM region)'),
]
# Ids kept for later build steps.
RESERVED_IDS = []
# intv_machine's id parameters (the rest are in core_top / intv_core)
MACHINE_PARAMS = {'SS_CPU': 0x02, 'SS_BUS': 0x03, 'SS_STIC': 0x04, 'SS_PSG': 0x05, 'SS_SCR': 0x06,
                  'SS_SYS': 0x07, 'SS_GRAM': 0x09, 'SS_ROW': 0x0C, 'SS_LINE': 0x0D,
                  'SS_ECS': 0x0E, 'SS_PSG2': 0x0F, 'SS_ERAM': 0x10, 'SS_VOICE': 0x18, 'SS_JLP': 0x20}

VERSION = 5
MAGIC = 0x494E5456                 # "INTV"
BLOB_BYTES = 153600                # DESIGN 4.4, decision 6
HDR_WORDS = 16
MOD_BYTE = 64                      # first module word
MOD_AREA_END = 8192                # module words up to here
CRAM_BYTE = 8192
CRAM_CELLS = 16384                 # the SRAM's cart RAM area (intv_media.sv)
JRAM_BYTE = CRAM_BYTE + 2 * CRAM_CELLS       # 40960: the end of what versions 1-4 use
JRAM_CELLS = 8000                  # the JLP RAM ($8040-$9F7F; SRAM $1C000, intv_cart.sv)
LIVE_END = JRAM_BYTE + 2 * JRAM_CELLS        # 56960
PAYLOAD_BYTES = LIVE_END - MOD_BYTE          # 40896
MOD_WORDS = sum(n for _, _, n, *_ in LAYOUT)  # 1941

# header words
(H_MAGIC, H_VERSION, H_SIZE, H_LENGTH, H_CART_CRC, H_CART_WORDS, H_FLAGS, H_CRC, H_NMOD, H_NCRAM,
 H_EXEC_CRC, H_GROM_CRC, H_CFG_CRC, H_ECS_CRC, H_NJRAM) = range(15)
HEADER = [
    (H_MAGIC, 'magic', '$494E5456 "INTV"'),
    (H_VERSION, 'version', 'format version (%d)' % VERSION),
    (H_SIZE, 'size', 'blob size in bytes (%d)' % BLOB_BYTES),
    (H_LENGTH, 'length', 'payload bytes from byte 64 (%d)' % PAYLOAD_BYTES),
    (H_CART_CRC, 'cart_crc', "the cartridge image's CRC32 (as the loader computes it; 0 with no cartridge)"),
    (H_CART_WORDS, 'cart_words', 'the cartridge image length in 16-bit words'),
    (H_FLAGS, 'flags', 'bit 0 ECS attached (version 3), bit 1 Intellivoice on (version 4), bit 8 PAL (0 in this core)'),
    (H_CRC, 'crc', 'CRC32 of the payload (bytes 64 .. 64 + length - 1)'),
    (H_NMOD, 'mod_words', 'module state words (%d)' % MOD_WORDS),
    (H_NCRAM, 'cram_cells', 'cart RAM cells (%d)' % CRAM_CELLS),
    (H_EXEC_CRC, 'exec_crc', "the EXEC slot's CRC32 (the bytes the loader took)"),
    (H_GROM_CRC, 'grom_crc', "the GROM slot's CRC32"),
    (H_CFG_CRC, 'cfg_crc', "the CFG's CRC32 when the map came with one (0: none; version 2)"),
    (H_ECS_CRC, 'ecs_crc', "the ECS ROM slot's CRC32 while the ECS is attached, else 0 (version 3)"),
    (H_NJRAM, 'jram_cells', 'JLP RAM cells (%d; version 5)' % JRAM_CELLS),
]
H_LAST = H_NJRAM
FLAG_ECS, FLAG_VOICE, FLAG_PAL = 1, 2, 0x100

assert 4 * HDR_WORDS == MOD_BYTE
assert MOD_BYTE + 4 * MOD_WORDS <= MOD_AREA_END
assert LIVE_END <= BLOB_BYTES


def module_offsets():
    """[(id, name, words, first blob word index)] in blob order."""
    out, w = [], MOD_BYTE // 4
    for mid, name, n, *_ in LAYOUT:
        out.append((mid, name, n, w))
        w += n
    return out


def state_addr(i):
    """The state-bus address ({id, word}) of module word i (0 .. MOD_WORDS-1)."""
    for mid, _, n, w0 in module_offsets():
        k = i - (w0 - MOD_BYTE // 4)
        if 0 <= k < n:
            return ((mid + (k >> 8)) << 8) | (k & 0xFF)
    raise IndexError(i)


def crc32(b):
    return zlib.crc32(bytes(b)) & 0xFFFFFFFF


# ------------------------------------------------------------- pack / unpack
def pack(mods, cram, cart_crc=0, cart_words=0, flags=0, crc_override=None, exec_crc=0, grom_crc=0,
         cfg_crc=0, version=VERSION, ecs_crc=0, jram=None):
    """mods: {id: [words]} (every LAYOUT module, exact length); cram: CRAM_CELLS cells; jram:
    JRAM_CELLS cells (None: zero)."""
    b = bytearray(BLOB_BYTES)
    for mid, name, n, w0 in module_offsets():
        ws = mods[mid]
        if len(ws) != n:
            raise ValueError('%s: %d words, want %d' % (name, len(ws), n))
        for k, v in enumerate(ws):
            struct.pack_into('>I', b, 4 * (w0 + k), v & 0xFFFFFFFF)
    if len(cram) != CRAM_CELLS:
        raise ValueError('cart RAM: %d cells' % len(cram))
    for c, v in enumerate(cram):
        struct.pack_into('>H', b, CRAM_BYTE + 2 * c, v & 0xFFFF)
    if jram is not None:
        if len(jram) != JRAM_CELLS:
            raise ValueError('JLP RAM: %d cells' % len(jram))
        for c, v in enumerate(jram):
            struct.pack_into('>H', b, JRAM_BYTE + 2 * c, v & 0xFFFF)
    h = [0] * HDR_WORDS
    h[H_MAGIC], h[H_VERSION], h[H_SIZE], h[H_LENGTH] = MAGIC, version, BLOB_BYTES, PAYLOAD_BYTES
    h[H_CART_CRC], h[H_CART_WORDS], h[H_FLAGS] = cart_crc, cart_words, flags
    h[H_NMOD], h[H_NCRAM] = MOD_WORDS, CRAM_CELLS
    h[H_EXEC_CRC], h[H_GROM_CRC] = exec_crc, grom_crc
    if version >= 2:
        h[H_CFG_CRC] = cfg_crc
    if version >= 3:
        h[H_ECS_CRC] = ecs_crc
    if version >= 5:
        h[H_NJRAM] = JRAM_CELLS
    h[H_CRC] = crc32(b[MOD_BYTE:MOD_BYTE + PAYLOAD_BYTES]) if crc_override is None else crc_override
    for i, v in enumerate(h):
        struct.pack_into('>I', b, 4 * i, v & 0xFFFFFFFF)
    return bytes(b)


def header(blob):
    return list(struct.unpack_from('>%dI' % HDR_WORDS, blob, 0))


def unpack(blob):
    """(header words, {id: [words]}, cram cells)."""
    mods = {}
    for mid, _, n, w0 in module_offsets():
        mods[mid] = list(struct.unpack_from('>%dI' % n, blob, 4 * w0))
    cram = list(struct.unpack_from('>%dH' % CRAM_CELLS, blob, CRAM_BYTE))
    return header(blob), mods, cram


def jram_of(blob):
    """The JLP RAM cells of a blob (version 5)."""
    return list(struct.unpack_from('>%dH' % JRAM_CELLS, blob, JRAM_BYTE))


def verify(blob, cart_crc=None, cart_words=None, flags=0, exec_crc=None, grom_crc=None, cfg_crc=None,
           ecs_crc=0):
    """The core's load checks, in its order; [] if the blob would be taken."""
    if len(blob) != BLOB_BYTES:
        return ['size %d bytes, want %d' % (len(blob), BLOB_BYTES)]
    h = header(blob)
    want = {H_MAGIC: MAGIC, H_VERSION: VERSION, H_SIZE: BLOB_BYTES, H_LENGTH: PAYLOAD_BYTES,
            H_FLAGS: flags, H_NMOD: MOD_WORDS, H_NCRAM: CRAM_CELLS, H_NJRAM: JRAM_CELLS}
    if cart_crc is not None:
        want[H_CART_CRC] = cart_crc
    if cart_words is not None:
        want[H_CART_WORDS] = cart_words
    if exec_crc is not None:
        want[H_EXEC_CRC] = exec_crc
    if grom_crc is not None:
        want[H_GROM_CRC] = grom_crc
    if cfg_crc is not None:
        want[H_CFG_CRC] = cfg_crc
    want[H_ECS_CRC] = ecs_crc
    bad = []
    names = {i: n for i, n, _ in HEADER}
    for i in range(HDR_WORDS):
        exp = want.get(i, 0 if i > H_LAST else None)
        if exp is not None and h[i] != exp:
            bad.append('header %s = $%08X, want $%08X' % (names.get(i, 'word %d' % i), h[i], exp))
    for lo, hi in ((MOD_BYTE + 4 * MOD_WORDS, MOD_AREA_END), (LIVE_END, BLOB_BYTES)):
        if any(blob[lo:hi]):
            bad.append('reserved bytes %d-%d not zero' % (lo, hi - 1))
    c = crc32(blob[MOD_BYTE:MOD_BYTE + PAYLOAD_BYTES])
    if c != h[H_CRC]:
        bad.append('payload CRC $%08X, header says $%08X' % (c, h[H_CRC]))
    return bad


# ------------------------------------------------------------- generation
def gen_pkg():
    L = []
    L.append('// Intellivision core: the save-state module ids and the blob layout (DESIGN.md 4;')
    L.append('// docs/SAVESTATE.md). GENERATED by tools/savestate.py from its LAYOUT: do not edit;')
    L.append('// run `python3 -I tools/savestate.py gen` and commit both.')
    L.append('//')
    L.append('// SPDX-License-Identifier: MIT')
    L.append('')
    L.append('package intv_ss_pkg;')
    L.append('')
    L.append('    /* verilator lint_off UNUSEDPARAM */')
    L.append('    // module ids (state bus address [15:8]; a module of more than 256 words')
    L.append('    // takes the next ids too)')
    for mid, name, n, *_ in LAYOUT:
        L.append("    localparam logic [7:0] SS_%-8s = 8'h%02X;   // %d word%s" % (name.upper(), mid, n,
                                                                         '' if n == 1 else 's'))
    for mid, what in RESERVED_IDS:
        L.append("    // 8'h%02X reserved: %s" % (mid, what))
    L.append('')
    L.append('    // the blob (format version %d), byte offsets' % VERSION)
    L.append("    localparam logic [31:0] SS_MAGIC      = 32'h%08X;" % MAGIC)
    L.append("    localparam logic [31:0] SS_VERSION    = 32'd%d;" % VERSION)
    L.append("    localparam int          SS_BLOB_BYTES = %d;" % BLOB_BYTES)
    L.append("    localparam int          SS_HDR_WORDS  = %d;" % HDR_WORDS)
    L.append("    localparam int          SS_MOD_BYTE   = %d;" % MOD_BYTE)
    L.append("    localparam int          SS_MOD_WORDS  = %d;" % MOD_WORDS)
    L.append("    localparam int          SS_MOD_END    = %d;     // module area end" % MOD_AREA_END)
    L.append("    localparam int          SS_CRAM_BYTE  = %d;" % CRAM_BYTE)
    L.append("    localparam int          SS_CRAM_CELLS = %d;" % CRAM_CELLS)
    L.append("    localparam int          SS_JRAM_BYTE  = %d;" % JRAM_BYTE)
    L.append("    localparam int          SS_JRAM_CELLS = %d;" % JRAM_CELLS)
    L.append("    localparam int          SS_LIVE_END   = %d;    // version %d uses bytes below" % (LIVE_END, VERSION))
    L.append("    localparam int          SS_PAYLOAD    = %d;    // payload bytes from SS_MOD_BYTE" % PAYLOAD_BYTES)
    L.append('')
    L.append('    // header words')
    for i, name, what in HEADER:
        L.append('    localparam int          SS_H_%-10s = %d;   // %s' % (name.upper(), i, what))
    L.append("    localparam logic [31:0] SS_FLAG_ECS = 32'h%X, SS_FLAG_VOICE = 32'h%X, SS_FLAG_PAL = 32'h%X;"
             % (FLAG_ECS, FLAG_VOICE, FLAG_PAL))
    L.append('    /* verilator lint_on UNUSEDPARAM */')
    L.append('')
    L.append('    // the state-bus address {id, word} of module word i (0 .. SS_MOD_WORDS-1),')
    L.append('    // blob byte SS_MOD_BYTE + 4 i')
    L.append('    function automatic logic [15:0] ss_word_addr(input logic [10:0] i);')
    L.append('        logic [10:0] k;')
    first = True
    for mid, name, n, w0 in module_offsets():
        base = w0 - MOD_BYTE // 4
        kw = 'if' if first else 'end else if'
        L.append("        %s (i < 11'd%d) begin" % (kw, base + n))
        L.append("            k = i - 11'd%d;" % base)
        if n > 256:
            L.append("            ss_word_addr = {8'h%02X + {5'd0, k[10:8]}, k[7:0]};" % mid)
        else:
            L.append("            ss_word_addr = {8'h%02X, k[7:0]};" % mid)
        first = False
    L.append('        end else begin')
    L.append("            k = 11'd0;")
    L.append("            ss_word_addr = 16'h0000;")
    L.append('        end')
    L.append('    endfunction')
    L.append('')
    L.append('endpackage')
    return '\n'.join(L) + '\n'


BEGIN = '<!-- BEGIN GENERATED by tools/savestate.py gen: do not edit -->'
END = '<!-- END GENERATED -->'


def gen_table():
    L = [BEGIN, '', 'Header (bytes 0-63, 32-bit words, big-endian):', '',
         '| Word | Byte | Field | Value |', '|---|---|---|---|']
    for i, name, what in HEADER:
        L.append('| %d | %d | %s | %s |' % (i, 4 * i, name, what))
    L.append('| %d-%d | %d-%d | reserved | 0 |' % (H_LAST + 1, HDR_WORDS - 1, 4 * (H_LAST + 1), 4 * HDR_WORDS - 1))
    L += ['', 'Modules (state words in id order; one 32-bit word per state word):', '',
          '| Id | Module | Words | Blob bytes | RTL | Holds |', '|---|---|---|---|---|---|']
    for (mid, name, n, w0), (_, _, _, f, _, what) in zip(module_offsets(), LAYOUT):
        ids = '$%02X' % mid if n <= 256 else '$%02X-$%02X' % (mid, mid + (n - 1) // 256)
        L.append('| %s | %s | %d | %d-%d | %s | %s |' % (ids, name, n, 4 * w0, 4 * (w0 + n) - 1, f, what))
    L.append('| | (unused, zero) | | %d-%d | | |' % (MOD_BYTE + 4 * MOD_WORDS, MOD_AREA_END - 1))
    L += ['', 'Then:', '',
          '| Blob bytes | Part |', '|---|---|',
          '| %d-%d | cart RAM: %d cells of the SRAM area $18000-$1BFFF, cell 2k in bits 31-16 of a word |'
          % (CRAM_BYTE, JRAM_BYTE - 1, CRAM_CELLS),
          '| %d-%d | JLP RAM: %d cells ($8040-$9F7F, the SRAM at $1C000), as the cart RAM |'
          % (JRAM_BYTE, LIVE_END - 1, JRAM_CELLS),
          '| %d-%d | reserved for later steps, zero |' % (LIVE_END, BLOB_BYTES - 1),
          '', 'Ids kept for later steps:', '', '| Id | For |', '|---|---|']
    for mid, what in RESERVED_IDS:
        L.append('| $%02X | %s |' % (mid, what))
    L += ['', 'Module words: %d (%d bytes); payload %d bytes (bytes %d-%d); blob %d bytes.'
          % (MOD_WORDS, 4 * MOD_WORDS, PAYLOAD_BYTES, MOD_BYTE, LIVE_END - 1, BLOB_BYTES), '', END]
    return '\n'.join(L)


def rtl_checks():
    """The literal SS_ID defaults and intv_machine's parameters against LAYOUT."""
    import re
    bad = []
    core = os.path.join(ROOT, 'src', 'fpga', 'core')
    for mid, name, n, f, par, _ in LAYOUT:
        if not par:
            continue
        s = open(os.path.join(core, f)).read()
        m = re.search(r"parameter\s+logic\s*\[7:0\]\s+%s\s*=\s*8'h([0-9A-Fa-f]+)" % par, s)
        if not m or int(m.group(1), 16) != mid:
            bad.append('%s: %s default is not $%02X' % (f, par, mid))
    s = open(os.path.join(core, 'intv_machine.sv')).read()
    for par, mid in MACHINE_PARAMS.items():
        m = re.search(r"parameter\s+logic\s*\[7:0\]\s+%s\s*=\s*8'h([0-9A-Fa-f]+)" % par, s)
        if not m or int(m.group(1), 16) != mid:
            bad.append('intv_machine.sv: %s default is not $%02X' % (par, mid))
    names = {name: mid for mid, name, *_ in LAYOUT}
    if names.get('psg') != MACHINE_PARAMS['SS_PSG'] or names.get('sysram') != MACHINE_PARAMS['SS_SYS']:
        bad.append('MACHINE_PARAMS disagree with LAYOUT')
    return bad


def cmd_gen(a):
    pkg = gen_pkg()
    doc = open(DOC).read() if os.path.exists(DOC) else ''
    if BEGIN not in doc or END not in doc:
        print('%s: no GENERATED markers' % DOC)
        return 1
    pre, rest = doc.split(BEGIN, 1)
    _, post = rest.split(END, 1)
    newdoc = pre + gen_table() + post
    bad = rtl_checks()
    for b in bad:
        print('RTL: ' + b)
    if a.check:
        old = open(PKG).read() if os.path.exists(PKG) else ''
        ok = old == pkg and doc == newdoc and not bad
        if old != pkg:
            print('%s differs from tools/savestate.py' % os.path.relpath(PKG, ROOT))
        if doc != newdoc:
            print('%s table differs from tools/savestate.py' % os.path.relpath(DOC, ROOT))
        print('SS_LAYOUT %s' % ('up to date' if ok else 'FAIL'))
        return 0 if ok else 1
    open(PKG, 'w').write(pkg)
    open(DOC, 'w').write(newdoc)
    print('wrote %s, %s' % (os.path.relpath(PKG, ROOT), os.path.relpath(DOC, ROOT)))
    return 1 if bad else 0


def cmd_show(a):
    blob = open(a.blob, 'rb').read()
    h, mods, cram = unpack(blob)
    for i, name, _ in HEADER:
        print('%-10s $%08X' % (name, h[i]))
    for mid, name, n, _ in module_offsets():
        ws = mods[mid]
        print('$%02X %-8s %4d words, first %s' % (mid, name, n, ' '.join('%08X' % x for x in ws[:4])))
    print('cart RAM: %d of %d cells not zero' % (sum(1 for c in cram if c), len(cram)))
    return 0


def cmd_verify(a):
    blob = open(a.blob, 'rb').read()
    hx = lambda x: None if x is None else int(x, 16)  # noqa: E731
    bad = verify(blob, hx(a.cart_crc), a.cart_words, flags=a.flags, exec_crc=hx(a.exec_crc),
                 grom_crc=hx(a.grom_crc), cfg_crc=hx(a.cfg_crc), ecs_crc=hx(a.ecs_crc))
    for b in bad:
        print('  ' + b)
    print('SS_VERIFY %s' % ('pass' if not bad else 'FAIL'))
    return 0 if not bad else 1


def selftest():
    import random
    rnd = random.Random(7)
    mods = {mid: [rnd.getrandbits(32) for _ in range(n)] for mid, _, n, *_ in LAYOUT}
    cram = [rnd.getrandbits(16) for _ in range(CRAM_CELLS)]
    b = pack(mods, cram, 0x12345678, 4096, exec_crc=0xCAFEF00D, grom_crc=0x0BADBEEF, cfg_crc=0x5EEDC0DE)
    fails = []
    if len(b) != BLOB_BYTES:
        fails.append('size')
    if verify(b, 0x12345678, 4096, exec_crc=0xCAFEF00D, grom_crc=0x0BADBEEF, cfg_crc=0x5EEDC0DE):
        fails.append('good blob refused')
    h, m2, c2 = unpack(b)
    if m2 != mods or c2 != cram:
        fails.append('unpack differs')
    if pack(m2, c2, h[H_CART_CRC], h[H_CART_WORDS], exec_crc=h[H_EXEC_CRC], grom_crc=h[H_GROM_CRC],
            cfg_crc=h[H_CFG_CRC]) != b:
        fails.append('pack(unpack) differs')
    # each refusal on its own
    cases = []
    for i in range(HDR_WORDS):
        if i == H_CRC:
            continue
        x = bytearray(b)
        struct.pack_into('>I', x, 4 * i, header(b)[i] ^ 0x00010000)
        cases.append(('header word %d' % i, bytes(x)))
    for off in (MOD_BYTE, MOD_BYTE + 4 * MOD_WORDS - 1, CRAM_BYTE, LIVE_END - 1):
        x = bytearray(b)
        x[off] ^= 0x01
        cases.append(('payload byte %d' % off, bytes(x)))
    for off in (MOD_BYTE + 4 * MOD_WORDS, MOD_AREA_END - 1, LIVE_END, BLOB_BYTES - 1):
        x = bytearray(b)
        x[off] = 0x80
        cases.append(('reserved byte %d' % off, bytes(x)))
    cases.append(('short', b[:-4]))
    # an older (version 1) blob of the same machine: refused
    cases.append(('version 1 blob', pack(mods, cram, 0x12345678, 4096, exec_crc=0xCAFEF00D,
                                         grom_crc=0x0BADBEEF, version=1)))
    cases.append(('version 2 blob', pack(mods, cram, 0x12345678, 4096, exec_crc=0xCAFEF00D,
                                         grom_crc=0x0BADBEEF, cfg_crc=0x5EEDC0DE, version=2)))
    cases.append(('ECS attached', pack(mods, cram, 0x12345678, 4096, flags=FLAG_ECS, exec_crc=0xCAFEF00D,
                                       grom_crc=0x0BADBEEF, cfg_crc=0x5EEDC0DE, ecs_crc=0x0EC5C0DE)))
    for what, x in cases:
        if not verify(x, 0x12345678, 4096, exec_crc=0xCAFEF00D, grom_crc=0x0BADBEEF, cfg_crc=0x5EEDC0DE):
            fails.append('not refused: ' + what)
    if not verify(b, 0x12345678, 4096, cfg_crc=0x5EEDC0DF):
        fails.append('foreign CFG CRC taken')
    if not verify(b, 0x12345679, 4096):
        fails.append('foreign cart CRC taken')
    if not verify(b, 0x12345678, 4096, exec_crc=0xCAFEF00E) or not verify(b, 0x12345678, 4096, grom_crc=1):
        fails.append('foreign system ROM taken')
    if verify(b, 0x12345678, 4096, exec_crc=0xCAFEF00D, grom_crc=0x0BADBEEF, cfg_crc=0x5EEDC0DE):
        fails.append('own system ROM CRCs refused')
    be = pack(mods, cram, 0x12345678, 4096, flags=FLAG_ECS, exec_crc=0xCAFEF00D, grom_crc=0x0BADBEEF,
              cfg_crc=0x5EEDC0DE, ecs_crc=0x0EC5C0DE)
    if verify(be, 0x12345678, 4096, flags=FLAG_ECS, ecs_crc=0x0EC5C0DE):
        fails.append('own ECS blob refused')
    if not verify(be, 0x12345678, 4096, flags=FLAG_ECS, ecs_crc=0x0EC5C0DF):
        fails.append('foreign ECS ROM taken')
    if not verify(be, 0x12345678, 4096, flags=0, ecs_crc=0x0EC5C0DE):
        fails.append('ECS blob taken without the ECS')
    # the state addresses: every word once, in id order
    addrs = [state_addr(i) for i in range(MOD_WORDS)]
    if len(set(addrs)) != MOD_WORDS or addrs != sorted(addrs):
        fails.append('state addresses')
    if addrs[0] != 0x0100 or state_addr(1 + 8 + 2 + 67 + 21 + 256 + 256) != 0x0800 \
            or state_addr(1 + 8 + 2 + 67 + 21 + 256 + 352 + 512) != 0x0B00:
        fails.append('state address spot checks')
    for f in fails:
        print('  FAIL ' + f)
    print('SS_SELFTEST %s (%d refusal cases)' % ('pass' if not fails else 'FAIL', len(cases) + 1))
    return 0 if not fails else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    g = sub.add_parser('gen')
    g.add_argument('--check', action='store_true')
    s = sub.add_parser('show')
    s.add_argument('blob')
    v = sub.add_parser('verify')
    v.add_argument('blob')
    v.add_argument('--cart-crc')
    v.add_argument('--cart-words', type=int)
    v.add_argument('--exec-crc')
    v.add_argument('--grom-crc')
    v.add_argument('--cfg-crc')
    v.add_argument('--flags', type=int, default=0)
    v.add_argument('--ecs-crc', default='0')
    sub.add_parser('selftest')
    a = ap.parse_args()
    return {'gen': cmd_gen, 'show': cmd_show, 'verify': cmd_verify,
            'selftest': lambda _: selftest()}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
