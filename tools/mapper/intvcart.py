# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Intellivision cartridge layouts, the CRC map table and the mapper model.

Build step 0 of docs/DESIGN.md (sections 5.2 and 9). Our own code, written from:
  - MAME hash/intv.xml and hash/intvecs.xml (CC0-1.0, copied under data/mame-hash/):
    one dataarea per load address, ROM parts in file order.
  - MAME source (BSD-3-Clause), read for facts only:
      src/devices/bus/intv/slot.cpp:387-425  softlist dataarea names are load addresses, two
                                             bytes per word, high byte first in the file
      src/mame/mattel/intv_m.cpp:600-605     cart RAM windows: intv_ram at $D000-$D7FF,
                                             intv_gfact at $8800-$8FFF
      src/devices/bus/intv/rom.h:52-53, 65-66 cart RAM cells are 8 bits, index masked by size
      src/devices/bus/intv/ecs.cpp:200-245   WSMLB pages at $F000 selected by $FA50/$FA51
  - jzIntv doc/tech/ecs.html (read as a specification): writing $xA5y to $xFFF selects
    page y (of 16) of the 4K range $x000-$xFFF; all ranges start at page 0; the ECS ROM is
    $2000 page 1, $7000 page 0, $E000 page 1; ECS RAM is $4000-$47FF, upper byte reads 0.
  - wiki.intellivision.us Cart.mac (16K map: $5000-$6FFF, $D000-$DFFF, $F000-$FFFF) and
    Memory_Map (cartridge-safe ranges), for the default map of an unknown image.
  - wiki J / Jump pages: the J/JSR encoding used by the jump-target evidence check.

No jzIntv code is used. Python 3.8+, standard library only.
"""
import csv
import os
import re
import struct
import zipfile
import zlib
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------------------
# Table formats (the RTL loads these; see tools/mapper/README.md for the full description)
# ---------------------------------------------------------------------------------------

PAGE_WORDS = 0x800          # page-table granularity: 2K words
NPAGES = 0x10000 // PAGE_WORDS  # 32 entries per layout

# CRC table entry flags (bits 23:16 of an entry)
FLAG_ECS = 0x01        # enable the ECS on Auto (title needs or uses it)
FLAG_VOICE = 0x02      # enable the Intellivoice on Auto
FLAG_RAM = 0x04        # cartridge RAM present (the page table says where)
FLAG_PAGED = 0x08      # ECS-style paged ROM in the cartridge
FLAG_JLP = 0x10        # JLP (none of the table sources marks one; CFG only for now)
FLAG_ECS_OFF = 0x20    # hard ECS conflict: cart ROM at $7000-$7FFF (ECS ROM visible at reset)
                       # or cart ROM/RAM in ECS RAM $4000-$47FF
FLAG_ESTIMATED = 0x40  # layout is our own derivation, not MAME's region map
FLAG_ECS_RISK = 0x80   # paged ECS conflict: cart ROM/RAM at $2000-$2FFF or $E000-$EFFF, where the
                       # ECS ROM is page 1 (absent at reset, there once the ECS selects page 1)
FLAG_NAMES = {FLAG_ECS: 'ecs', FLAG_VOICE: 'voice', FLAG_RAM: 'ram', FLAG_PAGED: 'paged',
              FLAG_JLP: 'jlp', FLAG_ECS_OFF: 'ecs_off', FLAG_ESTIMATED: 'estimated', FLAG_ECS_RISK: 'ecs_risk'}

# Page entry (16 bits), one per 2K-word page of the CPU address space
KIND_NONE, KIND_ROM, KIND_RAM16, KIND_RAM8 = 0, 1, 2, 3
KIND_NAMES = {KIND_NONE: '-', KIND_ROM: 'ROM', KIND_RAM16: 'RAM16', KIND_RAM8: 'RAM8'}

LAYOUT_INVALID = 0     # entry 0: no layout (table padding)

# CRC table padding: CRC FFFFFFFF, layout 0, so the table is sorted end to end and both a
# linear scan (stop at layout 0) and a binary search work (tools/mapper/README.md)
CRC_PAD_ENTRY = 0xFFFFFFFF << 32
LAYOUT_DEFAULT = 1     # unknown CRC: our default map, cut at the image length

# Address ranges the ECS uses for itself (jzIntv doc/tech/ecs.html; MAME intv_m.cpp:616-622).
# The ECS ROM is $7000 page 0 (there at reset), $2000 and $E000 page 1 (there only after the
# ECS selects page 1); ECS RAM $4000-$47FF is always there.
ECS_HARD_ROM_RANGES = [(0x7000, 0x7FFF)]
ECS_RAM_RANGE = (0x4000, 0x47FF)
ECS_PAGED_ROM_RANGES = [(0x2000, 0x2FFF), (0xE000, 0xEFFF)]


def page_entry(kind, offset=0, paged=False, npages=1, ram_size_code=0):
    """Encode one page-table entry.

    [15:14] kind (0 none, 1 ROM, 2 RAM 16-bit, 3 RAM 8-bit)
    [13]    ECS-style paged 4K range: page y of the range is at offset + 2*y
    [12:9]  number of pages in the range - 1 (0 when not paged)
    [8:0]   ROM: image offset in 2K-word units (up to 1M words)
            RAM: [8:6] size code, cells = 2048 >> code (mirrored inside the 2K page);
                 [5:0] offset in the cartridge RAM area, 2K-cell units
    """
    if kind == KIND_NONE:
        return 0
    v = (kind << 14) | ((npages - 1) << 9)
    if paged:
        v |= 1 << 13
    if kind == KIND_ROM:
        assert 0 <= offset < 512
        v |= offset
    else:
        assert 0 <= offset < 64 and 0 <= ram_size_code < 8
        v |= (ram_size_code << 6) | offset
    return v


def decode_page_entry(v):
    kind = (v >> 14) & 3
    d = dict(kind=kind, paged=bool(v >> 13 & 1), npages=((v >> 9) & 15) + 1)
    if kind == KIND_ROM:
        d['offset'] = v & 0x1FF
    elif kind in (KIND_RAM8, KIND_RAM16):
        d['cells'] = 2048 >> ((v >> 6) & 7)
        d['offset'] = v & 0x3F
    return d


# ---------------------------------------------------------------------------------------
# CRC32 (same as zlib / the core's loader: reflected, poly 0xEDB88320, init and final ~0)
# ---------------------------------------------------------------------------------------

def crc32(data, crc=0):
    return zlib.crc32(data, crc) & 0xFFFFFFFF


def _gf2_times(mat, vec):
    s, i = 0, 0
    while vec:
        if vec & 1:
            s ^= mat[i]
        vec >>= 1
        i += 1
    return s


def _gf2_square(mat):
    return [_gf2_times(mat, mat[n]) for n in range(32)]


def crc32_combine(crc1, crc2, len2):
    """CRC32 of A||B from crc(A), crc(B) and len(B), without the data.

    Shifting crc(A) through len(B) zero bytes is a linear map on the 32-bit register;
    apply it by repeated squaring of the one-zero-bit operator, then xor crc(B).
    """
    if len2 <= 0:
        return crc1
    odd = [0xEDB88320] + [1 << (n - 1) for n in range(1, 32)]   # one zero bit
    even = _gf2_square(odd)       # two zero bits
    odd = _gf2_square(even)       # four zero bits
    while True:
        even = _gf2_square(odd)   # first pass: one zero byte
        if len2 & 1:
            crc1 = _gf2_times(even, crc1)
        len2 >>= 1
        if not len2:
            break
        odd = _gf2_square(even)
        if len2 & 1:
            crc1 = _gf2_times(odd, crc1)
        len2 >>= 1
        if not len2:
            break
    return (crc1 ^ crc2) & 0xFFFFFFFF


# ---------------------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------------------

class Layout:
    """Where the image's words appear in the CPU address space.

    segs: list of (addr, words, file_offset_words, page) in file order; page is the
          ECS-style page (0-15) of the 4K range at addr (0 for plain ROM).
    rams: list of (addr, cells, width) cartridge RAM windows (width 8 or 16).
    """

    def __init__(self, segs, rams=()):
        self.segs = [tuple(s) for s in segs]
        self.rams = [tuple(r) for r in rams]
        self.check()

    def key(self):
        return (tuple(self.segs), tuple(self.rams))

    def words(self):
        return sum(s[1] for s in self.segs)

    def check(self):
        seen = {}
        last = max((s[2] for s in self.segs), default=0)
        for addr, words, off, page in self.segs:
            # every segment starts on a page; only the last one in the file may end mid-page
            # (MAME fills the rest of its dataarea with $FF, which reads as unmapped)
            if addr % PAGE_WORDS or off % PAGE_WORDS or (words % PAGE_WORDS and off != last):
                raise ValueError('segment %04X+%X@%X not 2K-aligned' % (addr, words, off))
            if addr + words > 0x10000:
                raise ValueError('segment %04X+%X past $FFFF' % (addr, words))
            if page and (addr % 0x1000 or words % 0x1000 and words != 0x800):
                raise ValueError('paged segment %04X must sit in one 4K range' % addr)
            for p in range(addr // PAGE_WORDS, (addr + words + PAGE_WORDS - 1) // PAGE_WORDS):
                if (p, page) in seen:
                    raise ValueError('page %04X (page %d) mapped twice' % (p * PAGE_WORDS, page))
                seen[(p, page)] = 1
        for addr, cells, width in self.rams:
            if addr % PAGE_WORDS or cells > PAGE_WORDS * 4 or width not in (8, 16):
                raise ValueError('bad RAM window %04X' % addr)

    def text(self):
        out = []
        for addr, words, off, page in self.segs:
            out.append('%04X-%04X%s' % (addr, addr + words - 1, ('/p%d' % page) if page else ''))
        for addr, cells, width in self.rams:
            span = max(cells, PAGE_WORDS) if cells < PAGE_WORDS else cells
            out.append('RAM%d %04X-%04X%s' % (width, addr, addr + span - 1,
                                              (' (%d cells, mirrored)' % cells) if cells < PAGE_WORDS else ''))
        return ' '.join(out)

    def page_table(self):
        """32 page entries for this layout (see page_entry)."""
        tab = [0] * NPAGES
        bypage = {}
        for addr, words, off, page in self.segs:
            for k in range(-(-words // PAGE_WORDS)):
                p = addr // PAGE_WORDS + k
                bypage.setdefault(p, {})[page] = off // PAGE_WORDS + k
        for p, pages in bypage.items():
            n = max(pages) + 1
            if n == 1:
                tab[p] = page_entry(KIND_ROM, pages[0])
            else:
                # pages of one 4K range must be evenly spaced by 2 units (4K words) in the image
                base = pages[0]
                for y, o in pages.items():
                    if o != base + 2 * y:
                        raise ValueError('paged range at %04X not contiguous in image' % (p * PAGE_WORDS))
                tab[p] = page_entry(KIND_ROM, base, paged=True, npages=n)
        ram_off = 0
        for addr, cells, width in self.rams:
            kind = KIND_RAM8 if width == 8 else KIND_RAM16
            if cells >= PAGE_WORDS:
                for k in range(cells // PAGE_WORDS):
                    tab[addr // PAGE_WORDS + k] = page_entry(kind, ram_off, ram_size_code=0)
                    ram_off += 1
            else:
                code = (PAGE_WORDS // cells).bit_length() - 1
                assert PAGE_WORDS >> code == cells
                tab[addr // PAGE_WORDS] = page_entry(kind, ram_off, ram_size_code=code)
                ram_off += 1
        return tab


def segs_from_text(spec):
    """'5000:2000 D000:1000 F000:1000/p1' (address:words in file order) -> segs list."""
    segs, off = [], 0
    for tok in spec.split():
        m = re.fullmatch(r'([0-9A-Fa-f]{4}):([0-9A-Fa-f]+)(?:/p(\d+))?', tok)
        if not m:
            raise ValueError('bad segment %r' % tok)
        addr, words, page = int(m.group(1), 16), int(m.group(2), 16), int(m.group(3) or 0)
        segs.append((addr, words, off, page))
        off += words
    return segs


def rams_from_text(spec):
    """'D000:400:8' (address:cells:width) list -> rams list."""
    rams = []
    for tok in (spec or '').split():
        a, c, w = tok.split(':')
        rams.append((int(a, 16), int(c, 16), int(w)))
    return rams


# Default map for an image whose CRC is not in the table: Cart.mac's 16K map first
# ($5000-$6FFF, $D000-$DFFF, $F000-$FFFF; wiki Cart.mac), then the ranges the wiki's
# Memory_Map and MAME slot.cpp:27-42 call ROM-safe without the ECS, in the order MAME's
# multi-segment layouts use them: $9000-$BFFF, $C000-$CFFF (STIC alias $C000-$C03F is
# write-only, so ROM there is safe), $E000-$EFFF, $8000-$8FFF, $4800-$4FFF, $2000-$2FFF,
# $7000-$7FFF. The loader cuts the list at the image length.
DEFAULT_FILL = [0x5000, 0x5800, 0x6000, 0x6800, 0xD000, 0xD800, 0xF000, 0xF800,
                0x9000, 0x9800, 0xA000, 0xA800, 0xB000, 0xB800, 0xC000, 0xC800,
                0xE000, 0xE800, 0x8000, 0x8800, 0x4800, 0x2000, 0x2800, 0x7000, 0x7800]


def default_layout(image_words):
    """The default map cut at image_words (rounded up to whole pages)."""
    segs = []
    n = min(len(DEFAULT_FILL), -(-image_words // PAGE_WORDS))
    for k in range(n):
        segs.append((DEFAULT_FILL[k], PAGE_WORDS, k * PAGE_WORDS, 0))
    return Layout(merge_segs(segs))


def default_page_table():
    """Page table of layout 1: every default page, offsets in fill order."""
    tab = [0] * NPAGES
    for k, a in enumerate(DEFAULT_FILL):
        tab[a // PAGE_WORDS] = page_entry(KIND_ROM, k)
    return tab


def merge_segs(segs):
    out = []
    for s in segs:
        if out and out[-1][3] == s[3] == 0 and out[-1][0] + out[-1][1] == s[0] and out[-1][2] + out[-1][1] == s[2]:
            out[-1] = (out[-1][0], out[-1][1] + s[1], out[-1][2], 0)
        else:
            out.append(s)
    return out


def ecs_conflict(layout):
    """ECS conflict flags of a layout: FLAG_ECS_OFF, FLAG_ECS_RISK, both or 0.

    ECS_OFF (hard): cartridge ROM or RAM overlaps $7000-$7FFF (ECS ROM page 0, there at
    reset) or the ECS RAM $4000-$47FF. ECS_RISK (paged): it overlaps $2000-$2FFF or
    $E000-$EFFF, where the ECS ROM is page 1 and appears once the ECS selects that page.
    """
    spans = [(a, a + w - 1) for a, w, o, p in layout.segs if p == 0]
    spans += [(a, a + max(c, PAGE_WORDS) - 1) for a, c, w in layout.rams]

    def hit(ranges):
        return any(lo <= rhi and rlo <= hi for lo, hi in spans for rlo, rhi in ranges)

    flags = 0
    if hit(ECS_HARD_ROM_RANGES + [ECS_RAM_RANGE]):
        flags |= FLAG_ECS_OFF
    if hit(ECS_PAGED_ROM_RANGES):
        flags |= FLAG_ECS_RISK
    return flags


# ---------------------------------------------------------------------------------------
# MAME software lists
# ---------------------------------------------------------------------------------------

RAM_WINDOWS = {'intv_ram': 0xD000, 'intv_gfact': 0x8800}   # MAME intv_m.cpp:600-605


def read_softlist(path):
    """Parse a MAME software list; yield one dict per software with a ROM image."""
    root = ET.parse(path).getroot()
    listname = os.path.basename(path)
    for sw in root.findall('software'):
        info = {i.get('name'): i.get('value') for i in sw.findall('info')}
        parts = sw.findall('part')
        if len(parts) != 1:
            raise ValueError('%s: %d parts' % (sw.get('name'), len(parts)))
        part = parts[0]
        feat = {f.get('name'): f.get('value') for f in part.findall('feature')}
        areas = []
        for da in part.findall('dataarea'):
            roms = []
            for ro in da.findall('rom'):
                if ro.get('crc') is None:
                    continue
                roms.append(dict(size=int(ro.get('size'), 0), crc=int(ro.get('crc'), 16),
                                 offset=int(ro.get('offset', '0'), 0), name=ro.get('name')))
            roms.sort(key=lambda r: r['offset'])
            areas.append(dict(name=da.get('name'), size=int(da.get('size'), 0), roms=roms))
        yield dict(list=listname, name=sw.get('name'), desc=sw.findtext('description'),
                   cloneof=sw.get('cloneof', ''), supported=sw.get('supported', 'yes'),
                   usage=info.get('usage', ''), slot=feat.get('slot', 'intv_rom'), areas=areas)


def softlist_entry(sw):
    """Turn one software-list entry into (layout, image_crc, image_bytes, flags, problems).

    Returns None for entries with no ROM (the Intellivoice module) and for the ECS itself
    (its ROM is a system ROM, loaded through its own slot).
    """
    problems = []
    if sw['slot'] == 'intv_ecs':
        return None
    rom_areas = [a for a in sw['areas'] if a['name'] != 'ram' and a['roms']]
    if not rom_areas:
        return None
    segs, off, crc, nbytes = [], 0, 0, 0
    for a in rom_areas:
        try:
            addr = int(a['name'], 16)
        except ValueError:
            problems.append('dataarea %s is not an address' % a['name'])
            continue
        part_bytes = sum(r['size'] for r in a['roms'])
        pos = 0
        for r in a['roms']:
            if r['offset'] != pos:
                problems.append('dataarea %s: gap between parts' % a['name'])
            pos = r['offset'] + r['size']
            crc = crc32_combine(crc, r['crc'], r['size'])
            nbytes += r['size']
        if part_bytes > a['size'] or part_bytes % 2:
            problems.append('dataarea %s: parts do not fit it' % a['name'])
            continue
        # The image holds only the parts; a dataarea larger than its parts is $FF filler
        # in MAME (slot.cpp:124), which reads like unmapped space.
        words = part_bytes // 2
        if words % PAGE_WORDS and a is not rom_areas[-1]:
            problems.append('dataarea %s: %#x bytes, not whole 2K-word pages' % (a['name'], part_bytes))
            continue
        if addr not in (0x0400, 0x2000, 0x4000, 0x4800, 0x5000, 0x6000, 0x7000, 0x8000, 0x8800,
                        0x9000, 0xA000, 0xB000, 0xC000, 0xD000, 0xE000, 0xF000):
            # slot.cpp:387-388: MAME loads only these area names
            problems.append('dataarea %s is not one MAME loads' % a['name'])
            continue
        if sw['slot'] == 'intv_wsmlb' and addr == 0xF000 and words == 0x2000:
            # two 4K-word pages of $F000 (ecs.cpp:200-245; intvecs.xml part offsets 0, 0x2000)
            segs.append((addr, 0x1000, off, 0))
            segs.append((addr, 0x1000, off + 0x1000, 1))
        else:
            segs.append((addr, words, off, 0))
        off += words
    rams = []
    ram_area = [a for a in sw['areas'] if a['name'] == 'ram']
    if sw['slot'] in RAM_WINDOWS:
        cells = ram_area[0]['size'] if ram_area else 0x800
        rams.append((RAM_WINDOWS[sw['slot']], cells, 8))
    elif ram_area:
        problems.append('ram dataarea with slot %s' % sw['slot'])
    flags = 0
    if sw['list'] == 'intvecs.xml' or 'ECS' in sw['usage']:
        flags |= FLAG_ECS
    if 'Intellivoice' in sw['usage']:
        flags |= FLAG_VOICE
    if problems:
        return dict(layout=None, crc=crc, bytes=nbytes, flags=flags, problems=problems)
    lay = Layout(segs, rams)
    return dict(layout=lay, crc=crc, bytes=nbytes, flags=flags, problems=problems)


def layout_flags(layout, flags):
    if layout.rams:
        flags |= FLAG_RAM
    if any(p for a, w, o, p in layout.segs):
        flags |= FLAG_PAGED
    if not flags & FLAG_ECS:
        flags |= ecs_conflict(layout)
    return flags


# ---------------------------------------------------------------------------------------
# Data files under data/
# ---------------------------------------------------------------------------------------

def read_name_flags(path):
    """data/jzintv_name_flags.csv -> {crc: (ecs, voice)}."""
    out = {}
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            c = int(r['crc32'], 16)
            e, v = int(r['ecs']), int(r['voice'])
            pe, pv = out.get(c, (0, 0))
            out[c] = (pe | e, pv | v)
    return out


def read_extra(path):
    """data/cart_extra.csv: our own entries for images MAME's lists do not give."""
    rows = []
    with open(path, newline='') as f:
        for r in csv.DictReader(f, skipinitialspace=True):
            if not r['crc32'] or r['crc32'].startswith('#'):
                continue
            rows.append(r)
    return rows


# ---------------------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------------------

def load_image_bytes(path):
    """Raw .int/.bin bytes from a file, or from the single image inside a .zip."""
    if path.lower().endswith('.zip'):
        with zipfile.ZipFile(path) as zf:
            members = [i for i in zf.infolist() if not i.is_dir()]
            imgs = [i for i in members if i.filename.lower().endswith(('.int', '.bin', '.itv'))] or members
            if len(imgs) != 1:
                raise ValueError('%s: expected one image, found %d' % (path, len(imgs)))
            if imgs[0].file_size > 2 * 1024 * 1024:
                raise ValueError('%s: image too large' % path)
            return zf.read(imgs[0])
    with open(path, 'rb') as f:
        return f.read(2 * 1024 * 1024 + 1)


# ---------------------------------------------------------------------------------------
# The core's cart loader, as the RTL will be (DESIGN 5.2, module 12)
# ---------------------------------------------------------------------------------------
#
# The APF bridge delivers a file in whole 32-bit words, and data_loader (OUTPUT_WORD_SIZE=1)
# emits every byte of every word, so a file whose length is not a multiple of 4 arrives with
# 1-3 pad bytes after its end. The loader therefore never counts strobes: it takes the file
# length from the data table entry the host writes for the cartridge slot (id 0x100, the
# size is the word after the id: word 2*index+1), CRCs exactly that many bytes, and the
# image is ceil(length/2) words (an odd last byte is the high byte, the low byte 0).

CART_SLOT_ID = 0x100


def bridge_strobes(data, pad=0xA5):
    """The byte strobes data_loader gives for a file: the file, padded to whole 32-bit words.

    The pad value is whatever the bridge word held; any value must give the same result.
    """
    return bytes(data) + bytes([pad & 0xFF]) * (-len(data) % 4)


def datatable(sizes):
    """The data table the host writes: {slot id: size in bytes} -> words id0, size0, id1, ..."""
    out = []
    for sid, size in sizes.items():
        out += [sid, size]
    return out


def datatable_size(table, slot_id=CART_SLOT_ID):
    """Size of a slot from the data table: the word after the slot id (word 2*index+1)."""
    for i in range(0, len(table) - 1, 2):
        if table[i] == slot_id:
            return table[i + 1]
    raise KeyError('slot %X not in the data table' % slot_id)


def loader_load(strobes, length):
    """What the loader keeps from the strobes: (CRC32, image words).

    Byte n of the stream is used only while n < length; strobes after that are bridge
    padding and change neither the CRC nor the image.
    """
    crc = 0xFFFFFFFF
    words = [0] * (-(-length // 2))
    for n, b in enumerate(strobes):
        if n >= length:
            break
        crc = _crc_byte(crc, b)
        if n & 1:
            words[n >> 1] |= b
        else:
            words[n >> 1] = b << 8
    return crc ^ 0xFFFFFFFF, words


def _crc_table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
        t.append(c)
    return t


_CRC_T = _crc_table()


def _crc_byte(crc, b):
    """One byte of the loader's CRC32 register (reflected, poly EDB88320, init ~0)."""
    return _CRC_T[(crc ^ b) & 0xFF] ^ (crc >> 8)


def load_through_loader(data, pad=0xA5):
    """A file as the core receives it: bridge strobes + data table length -> (CRC32, words)."""
    table = datatable({CART_SLOT_ID: len(data)})
    return loader_load(bridge_strobes(data, pad), datatable_size(table))


def bytes_to_words(data):
    """Big-endian 16-bit words; an odd trailing byte becomes the high byte of a last word."""
    if len(data) % 2:
        data = data + b'\x00'
    return list(struct.unpack('>%dH' % (len(data) // 2), data))


# ---------------------------------------------------------------------------------------
# The mapper model
# ---------------------------------------------------------------------------------------

class CartModel:
    """What the cartridge side of the core presents on the CPU bus.

    Built from the image words and a 32-entry page table, exactly as the RTL will be:
    every read goes through the page table, so the model checks the table as well as
    the layout. Reads that the cartridge does not answer return None (the bus then
    reads $FFFF through the pull-ups, DESIGN 2.5).
    """

    def __init__(self, words, page_table, ram_cells=0x4000):
        self.words = words
        self.pt = list(page_table)
        self.sel = [0] * 16                 # ECS-style page select per 4K range, 0 at reset
        self.ram = [0] * ram_cells

    def reset(self):
        self.sel = [0] * 16

    def _decode(self, addr):
        e = decode_page_entry(self.pt[addr // PAGE_WORDS])
        return e

    def read(self, addr):
        addr &= 0xFFFF
        e = self._decode(addr)
        k = e['kind']
        if k == KIND_NONE:
            return None
        if k == KIND_ROM:
            unit = e['offset']
            if e['paged']:
                y = self.sel[addr >> 12]
                if y >= e['npages']:
                    return None             # no ROM on this page
                unit += 2 * y
            i = unit * PAGE_WORDS + (addr % PAGE_WORDS)
            return self.words[i] if i < len(self.words) else None
        cells = e['cells']
        i = e['offset'] * PAGE_WORDS + (addr % PAGE_WORDS) % cells
        v = self.ram[i]
        return v & 0xFF if k == KIND_RAM8 else v

    def write(self, addr, value):
        addr &= 0xFFFF
        value &= 0xFFFF
        # ECS-style page select: $xA5y written to $xFFF (jzIntv doc/tech/ecs.html)
        if addr & 0xFFF == 0xFFF and (value & 0xFFF0) == ((addr & 0xF000) | 0x0A50):
            self.sel[addr >> 12] = value & 0xF
        e = self._decode(addr)
        if e['kind'] in (KIND_RAM8, KIND_RAM16):
            i = e['offset'] * PAGE_WORDS + (addr % PAGE_WORDS) % e['cells']
            self.ram[i] = value & 0xFF if e['kind'] == KIND_RAM8 else value

    def rom_space(self):
        """65,536 words as read at the current page selects; RAM and unmapped read $FFFF."""
        out = []
        for a in range(0x10000):
            e = decode_page_entry(self.pt[a // PAGE_WORDS])
            v = self.read(a) if e['kind'] == KIND_ROM else None
            out.append(0xFFFF if v is None else v)
        return out

    def mapped_space_crc(self):
        """CRC32 of the mapped space, as the RTL check will compute it.

        The 64K-word space at reset paging (page 0 everywhere), big-endian, ROM words as
        read and $FFFF for RAM and unmapped addresses; then, for each paged 4K range in
        address order, pages 1..n-1 of that range (4K words each).
        """
        saved = list(self.sel)
        self.reset()
        data = struct.pack('>65536H', *self.rom_space())
        crc = crc32(data)
        for r in range(16):
            e = decode_page_entry(self.pt[(r << 12) // PAGE_WORDS])
            if e['kind'] == KIND_ROM and e['paged']:
                for y in range(1, e['npages']):
                    self.sel[r] = y
                    blk = [self.read((r << 12) + i) for i in range(0x1000)]
                    crc = crc32(struct.pack('>4096H', *[0xFFFF if v is None else v for v in blk]), crc)
                self.sel[r] = 0
        self.sel = saved
        return crc


def model_for(words, layout_id, page_tables):
    """CartModel for layout_id; layout 1 (default) is cut at the image length."""
    pt = list(page_tables[layout_id])
    if layout_id == LAYOUT_DEFAULT:
        units = -(-len(words) // PAGE_WORDS)
        for p in range(NPAGES):
            e = decode_page_entry(pt[p])
            if e['kind'] == KIND_ROM and e['offset'] >= units:
                pt[p] = 0
    return CartModel(words, pt)


# ---------------------------------------------------------------------------------------
# Jump-target evidence (a check on a candidate layout, never used by the core)
# ---------------------------------------------------------------------------------------

def jump_candidates(words):
    """Every J/JSR pattern in the image: list of (file_index, target).

    Encoding from the wiki Jump page: $0004, then 0000 00rr aaaa aaff, then
    0000 00aa aaaa aaaa; target = (a[7:2] << 10) | third[9:0]; ff = 11 is not valid.
    Ten-bit data often looks like a jump, so this is a statistic, not a proof.
    """
    out = []
    for i in range(len(words) - 2):
        if words[i] != 0x0004:
            continue
        w2, w3 = words[i + 1], words[i + 2]
        if w2 & 0xFC00 or w3 & 0xFC00 or (w2 & 3) == 3:
            continue
        out.append((i, ((w2 >> 2) & 0x3F) << 10 | w3))
    return out


def jump_evidence(words, layout):
    """How well a candidate layout explains the image's jump targets.

    Only targets at $4000 and up count (below are the console's own EXEC, GROM, GRAM and
    RAM). Each such target is 'rom' (lands on cartridge ROM that is not filler), 'fill'
    (lands in a 2K block that is >= 90 % one value) or 'unmapped'. A right layout has
    few 'unmapped' and 'fill' hits compared with other candidates.
    Returns dict(n, rom, fill, unmapped).
    """
    pt = layout.page_table()
    model = CartModel(words, pt)
    fillblk = set()
    for k in range(0, len(words), PAGE_WORDS):
        blk = words[k:k + PAGE_WORDS]
        top = max(blk.count(v) for v in set(blk))
        if top >= 0.9 * len(blk):
            fillblk.add(k // PAGE_WORDS)
    res = dict(n=0, rom=0, fill=0, unmapped=0)
    for i, t in jump_candidates(words):
        if t < 0x4000:
            continue
        res['n'] += 1
        e = decode_page_entry(pt[t // PAGE_WORDS])
        if e['kind'] != KIND_ROM or model.read(t) is None:
            res['unmapped'] += 1
        elif e['offset'] in fillblk:
            res['fill'] += 1
        else:
            res['rom'] += 1
    return res
