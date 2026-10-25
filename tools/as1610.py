#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""as1610: a small CP1610 assembler for our own test ROMs.

Written from the GI CP-1600 Microprocessor Users Manual, May 1975 (S1:
instruction formats p.46-52, instruction set tables p.53-58) and the
wiki.intellivision.us opcode pages (Branch, Jump, MVI@, SDBD, Double_Byte_Data).
No code from any other assembler was used. Mnemonics and operand order follow
the manual: source first, destination last ("MVI A, DDD", "MVO SSS, A",
"MOVR SSS, DDD", "ADDI I, DDD"). See docs/CPU_NOTES.md.

Source format
  label:  MNEMONIC operands   ; comment
  A label is an identifier followed by ':' or any identifier that starts in
  column 0 and is not a mnemonic or directive.

Directives
  ORG expr            set the location counter
  ROMW 10|16          ROM word width (default 16). With 10, immediates over
                      $3FF get an automatic SDBD and two decles, as in S1 p.49.
  name EQU expr       constant (also "name: EQU expr"); SET may redefine
  DECLE e, ...        one word per value (warns over the ROM width)
  WORD e, ...         one 16-bit word per value
  BIDECLE e, ...      two words per value: low byte, then high byte (for SDBD)
  STRING "text", ...  one word per character
  RES n               reserve n words (no data emitted)
  END                 stop reading

Symbols are case-sensitive; mnemonics, directives and registers are not.
Expressions: decimal, $hex, 0xhex, %binary, 0bbinary, 'c', symbols, '$' alone
(address of the current instruction, or of the current word in a data list),
unary - ~ +, * / << >> & ^ | + - (C precedence), parentheses. Division
truncates toward zero.

Use: as1610.py src.asm [-o out.bin] [--cfg out.cfg] [-l out.lst]
  .bin is the segments joined in address order as big-endian 16-bit words
  (the raw cartridge image format); .cfg gives each segment's [mapping] line.
"""

import argparse
import re
import sys

__all__ = ["assemble", "AsmError", "Program", "REGS"]

REGS = {"R%d" % i: i for i in range(8)}
REGS["SP"] = 6
REGS["PC"] = 7

# Internal control, implied (S1 p.51 fig 3.14; p.56)
IMPLIED = {"HLT": 0x000, "SDBD": 0x001, "EIS": 0x002, "DIS": 0x003,
           "TCI": 0x005, "CLRC": 0x006, "SETC": 0x007}
# Single register (S1 p.51 fig 3.3.3)
SINGLE = {"INCR": 0x008, "DECR": 0x010, "COMR": 0x018, "NEGR": 0x020,
          "ADCR": 0x028, "RSWD": 0x038}
# Register shift (S1 p.50 fig 3.3.2, p.53): 0001 ooo nrr
SHIFTS = {"SWAP": 0, "SLL": 1, "RLC": 2, "SLLC": 3, "SLR": 4, "SAR": 5,
          "RRC": 6, "SARC": 7}
# Register to register (S1 p.50 fig 3.3.1): 0 ooo sss ddd
REGREG = {"MOVR": 0x080, "ADDR": 0x0C0, "SUBR": 0x100, "CMPR": 0x140,
          "ANDR": 0x180, "XORR": 0x1C0}
# Conditional branches (S1 p.54): 1000 d e cccc; aliases from the same page
# and the wiki Branch page.
BRANCH = {"B": 0, "BC": 1, "BLGT": 1, "BOV": 2, "BPL": 3, "BZE": 4, "BEQ": 4,
          "BLT": 5, "BNGE": 5, "BLE": 6, "BNGT": 6, "BUSC": 7,
          "NOPP": 8, "BNC": 9, "BLLT": 9, "BNOV": 10, "BMI": 11,
          "BNZE": 12, "BNEQ": 12, "BGE": 13, "BNLT": 13, "BGT": 14,
          "BNLE": 14, "BESC": 15}
# External reference ops (S1 p.46 fig 3.2.1): 1 ooo mmm rrr
EXT_OP = {"MVO": 1, "MVI": 2, "ADD": 3, "SUB": 4, "CMP": 5, "AND": 6, "XOR": 7}
# Jumps (S1 p.52): 0x004, then BB AAAAAA II, then AAAAAAAAAA
JUMPS = {"J": (3, 0), "JE": (3, 1), "JD": (3, 2),
         "JSR": (None, 0), "JSRE": (None, 1), "JSRD": (None, 2)}

DIRECTIVES = {"ORG", "ROMW", "EQU", "SET", "DECLE", "WORD", "BIDECLE",
              "STRING", "RES", "END"}


def _mnemonics():
    m = set(IMPLIED) | set(SINGLE) | set(SHIFTS) | set(REGREG) | set(BRANCH)
    m |= set(JUMPS) | {"GSWD", "NOP", "SIN", "TSTR", "JR", "CLRR", "BEXT",
                       "PSHR", "PULR", "CALL"}
    for op in EXT_OP:
        m |= {op, op + "@", op + "I"}
    return m


MNEMONICS = _mnemonics()


class AsmError(Exception):
    def __init__(self, msg, line=None, text=None):
        self.line, self.text, self.msg = line, text, msg
        where = "line %d: " % line if line else ""
        super().__init__(where + msg)


class _Undefined(Exception):
    pass


# ---------------------------------------------------------------- expressions
_TOKEN = re.compile(r"""\s*(?:
    (?P<num>\$[0-9A-Fa-f]+|0[xX][0-9A-Fa-f]+|%[01]+|0[bB][01]+|[0-9]+)
  | (?P<chr>'(?:[^'\\]|\\.)')
  | (?P<id>[A-Za-z_.][A-Za-z0-9_.]*)
  | (?P<op><<|>>|[-+*/&|^~()$])
)""", re.X)


def _tokens(text):
    pos, out = 0, []
    text = text.rstrip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise AsmError("bad expression near '%s'" % text[pos:])
        pos = m.end()
        if m.group("num"):
            s = m.group("num")
            if s[0] == "$":
                v = int(s[1:], 16)
            elif s[:2] in ("0x", "0X"):
                v = int(s[2:], 16)
            elif s[0] == "%":
                v = int(s[1:], 2)
            elif s[:2] in ("0b", "0B"):
                v = int(s[2:], 2)
            else:
                v = int(s, 10)
            out.append(("n", v))
        elif m.group("chr"):
            c = m.group("chr")[1:-1]
            c = {"\\n": "\n", "\\t": "\t", "\\0": "\0"}.get(c, c[-1])
            out.append(("n", ord(c)))
        elif m.group("id"):
            out.append(("id", m.group("id")))
        else:
            out.append(("op", m.group("op")))
    return out


class _Expr:
    PREC = [("|",), ("^",), ("&",), ("<<", ">>"), ("+", "-"), ("*", "/")]

    def __init__(self, text, lookup, here):
        self.t = _tokens(text)
        self.i = 0
        self.lookup = lookup
        self.here = here

    def value(self):
        if not self.t:
            raise AsmError("missing expression")
        v = self._bin(0)
        if self.i != len(self.t):
            raise AsmError("unexpected '%s' in expression" % (self.t[self.i][1],))
        return v

    def _peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def _bin(self, level):
        if level == len(self.PREC):
            return self._unary()
        v = self._bin(level + 1)
        while True:
            k, o = self._peek()
            if k == "op" and o in self.PREC[level]:
                self.i += 1
                r = self._bin(level + 1)
                if o == "|": v |= r
                elif o == "^": v ^= r
                elif o == "&": v &= r
                elif o == "<<": v <<= r
                elif o == ">>": v >>= r
                elif o == "+": v += r
                elif o == "-": v -= r
                elif o == "*": v *= r
                elif o == "/":
                    if r == 0:
                        raise AsmError("division by zero")
                    v = int(v / r)
            else:
                return v

    def _unary(self):
        k, o = self._peek()
        if k == "op" and o in "-~+":
            self.i += 1
            v = self._unary()
            return -v if o == "-" else (~v if o == "~" else v)
        if k == "op" and o == "(":
            self.i += 1
            v = self._bin(0)
            if self._peek() != ("op", ")"):
                raise AsmError("missing ')'")
            self.i += 1
            return v
        if k == "op" and o == "$":
            self.i += 1
            return self.here
        if k == "n":
            self.i += 1
            return o
        if k == "id":
            self.i += 1
            return self.lookup(o)
        raise AsmError("bad expression")


# ------------------------------------------------------------------- program
class Program:
    """Result of assemble(): words by address, symbols, listing, segments."""

    def __init__(self):
        self.words = {}        # address -> 16-bit word
        self.symbols = {}      # name -> value
        self.listing = []      # (lineno, address or None, [words], text)
        self.warnings = []
        self.romw = 16

    def segments(self):
        """[(start, [words])] for runs of consecutive addresses."""
        segs = []
        for a in sorted(self.words):
            if segs and segs[-1][0] + len(segs[-1][1]) == a:
                segs[-1][1].append(self.words[a])
            else:
                segs.append((a, [self.words[a]]))
        return segs

    def image(self):
        """Raw image: segments joined in address order, big-endian words."""
        out = bytearray()
        for _, ws in self.segments():
            for w in ws:
                out += bytes(((w >> 8) & 0xFF, w & 0xFF))
        return bytes(out)

    def cfg(self):
        """jzIntv-style [mapping] section for the raw image (format from the
        as1600/bincfg documentation, written by us)."""
        lines, off = ["[mapping]"], 0
        for start, ws in self.segments():
            lines.append("$%04X - $%04X = $%04X" % (off, off + len(ws) - 1, start))
            off += len(ws)
        return "\n".join(lines) + "\n"

    def listing_text(self):
        out = []
        for lineno, addr, ws, text in self.listing:
            a = "%04X" % addr if addr is not None and ws else "    "
            first = " ".join("%04X" % w for w in ws[:3])
            out.append("%5d  %s  %-14s  %s" % (lineno, a, first, text))
            for k in range(3, len(ws), 3):
                out.append("%5s  %04X  %-14s" % ("", addr + k,
                           " ".join("%04X" % w for w in ws[k:k + 3])))
        return "\n".join(out) + "\n"


def _split_operands(s):
    ops, depth, cur, q = [], 0, "", None
    for c in s:
        if q:
            cur += c
            if c == q:
                q = None
            continue
        if c in "'\"":
            q = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == "," and depth == 0:
            ops.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip():
        ops.append(cur.strip())
    return ops


def _strip_comment(line):
    q = None
    for i, c in enumerate(line):
        if q:
            if c == q:
                q = None
        elif c in "'\"":
            # a lone quote char literal like ';' is handled by the pair rule
            q = c
        elif c == ";":
            return line[:i]
    return line


class _Assembler:
    def __init__(self, text, romw=16, defines=None):
        self.lines = text.splitlines()
        self.romw0 = romw
        self.defines = dict(defines or {})

    # Passes repeat with the previous pass's symbols until no symbol and no
    # instruction size changes; then a final pass reports undefined symbols
    # and overlaps. Forward references are allowed except in ORG, ROMW, RES.
    def run(self):
        prev, sizes = None, {}
        for _ in range(12):
            prog = self._pass(sizes, final=False, prev=prev)
            if prev is not None and prog.symbols == prev.symbols and self.unstable == 0:
                return self._pass(sizes, final=True, prev=prog)
            prev = prog
        raise AsmError("symbols do not settle (forward references keep changing sizes)")

    def _pass(self, sizes, final, prev):
        prog = Program()
        prog.romw = self.romw0
        self.prog = prog
        self.final = final
        self.unstable = 0
        known = dict(prev.symbols) if prev else {}
        known.update(self.defines)
        self.known = known
        pc = 0
        sdbd_next = False
        sets = {}
        for lineno, raw in enumerate(self.lines, 1):
            self.lineno = lineno
            line = _strip_comment(raw).rstrip()
            if not line.strip():
                prog.listing.append((lineno, None, [], raw))
                continue
            label, rest = self._label(line)
            parts = rest.split(None, 1)
            mnem = parts[0].upper() if parts else ""
            args = parts[1] if len(parts) > 1 else ""
            here = pc
            words = []
            try:
                if mnem in ("EQU", "SET"):
                    if not label:
                        raise AsmError("%s needs a label" % mnem)
                    if label.upper() in REGS:
                        raise AsmError("label '%s' is a register name" % label)
                    v = self._eval(args, here, allow_undef=True)
                    if v is None:
                        prog.listing.append((lineno, None, [], raw))
                        continue
                    if mnem == "EQU" and label in prog.symbols and label not in sets:
                        raise AsmError("symbol '%s' defined twice" % label)
                    if mnem == "SET":
                        sets[label] = True
                    prog.symbols[label] = v
                    known[label] = v
                    prog.listing.append((lineno, None, [], raw))
                    continue
                if label:
                    if label.upper() in REGS:
                        raise AsmError("label '%s' is a register name" % label)
                    if label in prog.symbols:
                        raise AsmError("symbol '%s' defined twice" % label)
                    prog.symbols[label] = pc
                    known[label] = pc
                if not mnem:
                    prog.listing.append((lineno, pc, [], raw))
                    continue
                if mnem == "END":
                    prog.listing.append((lineno, None, [], raw))
                    break
                if mnem == "ORG":
                    pc = self._eval(args, here) & 0xFFFF
                    prog.listing.append((lineno, None, [], raw))
                    continue
                if mnem == "ROMW":
                    w = self._eval(args, here)
                    if w not in (10, 16):
                        raise AsmError("ROMW must be 10 or 16")
                    prog.romw = w
                    prog.listing.append((lineno, None, [], raw))
                    continue
                if mnem == "RES":
                    n = self._eval(args, here)
                    prog.listing.append((lineno, pc, [], raw))
                    pc = (pc + n) & 0xFFFF
                    continue
                if mnem in ("DECLE", "WORD", "BIDECLE", "STRING"):
                    words = self._data(mnem, args, here)
                    sdbd_next = False
                elif mnem in MNEMONICS:
                    words, sdbd_next = self._insn(mnem, args, here, sdbd_next,
                                                  (lineno, sizes))
                else:
                    raise AsmError("unknown mnemonic '%s'" % parts[0])
            except AsmError as e:
                if e.line is None:
                    e = AsmError(e.msg, lineno, raw)
                raise e
            for k, w in enumerate(words):
                a = (pc + k) & 0xFFFF
                if final and a in prog.words:
                    raise AsmError("address $%04X written twice" % a, lineno, raw)
                prog.words[a] = w & 0xFFFF
            prog.listing.append((lineno, pc, words, raw))
            pc = (pc + len(words)) & 0xFFFF
        return prog

    def _label(self, line):
        m = re.match(r"\s*([A-Za-z_.][A-Za-z0-9_.]*):(.*)$", line)
        if m:
            return m.group(1), m.group(2)
        m = re.match(r"([A-Za-z_.][A-Za-z0-9_.]*)(\s.*)?$", line)
        if m and not line[0].isspace():
            word = m.group(1).upper()
            if word not in MNEMONICS and word not in DIRECTIVES:
                return m.group(1), m.group(2) or ""
        return None, line

    def _lookup(self, name):
        up = name.upper()
        if up in REGS:
            raise AsmError("register %s where a value is expected" % name)
        if name in self.known:
            return self.known[name]
        if self.final:
            raise AsmError("undefined symbol '%s'" % name)
        raise _Undefined(name)

    def _eval(self, text, here, allow_undef=False):
        try:
            return _Expr(text, self._lookup, here).value()
        except _Undefined:
            if allow_undef and not self.final:
                return None
            if self.final:
                raise
            raise AsmError("symbol used before it is defined in '%s'" % text.strip())

    def _reg(self, text, allowed=range(8), what="register"):
        r = REGS.get(text.strip().upper())
        if r is None:
            raise AsmError("expected a %s, got '%s'" % (what, text.strip()))
        if r not in allowed:
            raise AsmError("%s R%d not allowed here" % (what, r))
        return r

    def _warn(self, msg):
        if self.final:
            self.prog.warnings.append("line %d: %s" % (self.lineno, msg))

    def _data(self, mnem, args, here):
        out = []
        for a in _split_operands(args):
            if mnem == "STRING":
                if not (len(a) >= 2 and a[0] == a[-1] == '"'):
                    raise AsmError("STRING needs \"text\"")
                out += [ord(c) for c in a[1:-1]]
                continue
            v = self._eval(a, here + len(out), allow_undef=True)
            v = 0 if v is None else v
            if mnem == "BIDECLE":
                v &= 0xFFFF
                out += [v & 0xFF, v >> 8]
                continue
            if not -0x8000 <= v <= 0xFFFF:
                raise AsmError("value %d does not fit 16 bits" % v)
            v &= 0xFFFF
            if mnem == "DECLE" and v >> self.prog.romw:
                self._warn("DECLE $%04X wider than ROMW %d" % (v, self.prog.romw))
            out.append(v)
        return out

    def _imm(self, text, here, allow_undef=True):
        t = text.strip()
        if t.startswith("#"):
            t = t[1:]
        return self._eval(t, here, allow_undef=allow_undef)

    def _insn(self, mnem, args, here, sdbd_prefix, key):
        """Return (words, sdbd_next)."""
        ops = _split_operands(args)

        def nops(n):
            if len(ops) != n:
                raise AsmError("%s takes %d operand%s" % (mnem, n, "" if n == 1 else "s"))

        if mnem == "SDBD":
            nops(0)
            return [0x001], True
        if mnem in IMPLIED:
            nops(0)
            return [IMPLIED[mnem]], False
        if mnem in SINGLE:
            nops(1)
            return [SINGLE[mnem] | self._reg(ops[0])], False
        if mnem == "GSWD":
            nops(1)
            return [0x030 | self._reg(ops[0], range(4))], False
        if mnem in ("NOP", "SIN"):
            n = self._eval(ops[0], here) if ops else 0
            if len(ops) > 1 or n not in (0, 1):
                raise AsmError("%s takes an optional 0 or 1" % mnem)
            return [(0x034 if mnem == "NOP" else 0x036) | n], False
        if mnem in SHIFTS:
            if len(ops) not in (1, 2):
                raise AsmError("%s takes Rr[, 1|2]" % mnem)
            r = self._reg(ops[0], range(4), "shift register (R0-R3)")
            n = self._eval(ops[1], here) if len(ops) == 2 else 1
            if n not in (1, 2):
                raise AsmError("shift count must be 1 or 2")
            return [0x040 | SHIFTS[mnem] << 3 | (n - 1) << 2 | r], False
        if mnem in REGREG:
            nops(2)
            return [REGREG[mnem] | self._reg(ops[0]) << 3 | self._reg(ops[1])], False
        if mnem == "TSTR":
            nops(1)
            r = self._reg(ops[0])
            return [0x080 | r << 3 | r], False
        if mnem == "JR":
            nops(1)
            return [0x080 | self._reg(ops[0]) << 3 | 7], False
        if mnem == "CLRR":
            nops(1)
            r = self._reg(ops[0])
            return [0x1C0 | r << 3 | r], False
        if mnem in BRANCH or mnem == "BEXT":
            if mnem == "BEXT":
                nops(2)
                cond = self._eval(ops[1], here)
                if not 0 <= cond <= 15:
                    raise AsmError("BEXT condition must be 0-15")
                ext = 1
            else:
                if mnem == "NOPP" and not ops:
                    return [0x208, 0], False
                nops(1)
                cond, ext = BRANCH[mnem], 0
            target = self._eval(ops[0], here, allow_undef=True)
            if target is None:
                return [0x200 | ext << 4 | cond, 0], False
            target &= 0xFFFF
            # S1 p.47/p.54: forward adds the displacement to PC+2; backward
            # adds its one's complement, so target = PC+2 - disp - 1.
            if target >= here + 2:
                d, disp = 0, target - (here + 2)
            else:
                d, disp = 1, (here + 1) - target
            limit = (1 << self.prog.romw) - 1
            if disp > limit:
                raise AsmError("branch to $%04X out of range (displacement %d > %d for ROMW %d)"
                               % (target, disp, limit, self.prog.romw))
            return [0x200 | d << 5 | ext << 4 | cond, disp], False
        if mnem in JUMPS or mnem == "CALL":
            if mnem == "CALL":
                nops(1)
                bb, ii, tgt = 1, 0, ops[0]
            else:
                bb, ii = JUMPS[mnem]
                if bb is None:
                    nops(2)
                    bb = self._reg(ops[0], (4, 5, 6), "return register (R4-R6)") - 4
                    tgt = ops[1]
                else:
                    nops(1)
                    tgt = ops[0]
            a = self._eval(tgt, here, allow_undef=True)
            a = 0 if a is None else a & 0xFFFF
            # S1 p.52: word 2 = BB AAAAAA II (address bits 15-10 in bits 7-2),
            # word 3 = address bits 9-0.
            return [0x004, bb << 8 | (a >> 10) << 2 | ii, a & 0x3FF], False
        if mnem == "PSHR":
            nops(1)
            return [0x240 | 6 << 3 | self._reg(ops[0])], False
        if mnem == "PULR":
            nops(1)
            return [0x280 | 6 << 3 | self._reg(ops[0])], self._sdbd_check(sdbd_prefix)
        if mnem.endswith("@"):
            base, kind = mnem[:-1], "@"
        elif mnem.endswith("I") and mnem[:-1] in EXT_OP:
            base, kind = mnem[:-1], "I"
        else:
            base, kind = mnem, ""
        if base not in EXT_OP:
            raise AsmError("unknown mnemonic '%s'" % mnem)
        op = 0x200 | EXT_OP[base] << 6
        nops(2)
        if base == "MVO":
            # MVO SSS, A / MVO@ SSS, MMM / MVOI SSS, I
            if sdbd_prefix:
                self._warn("SDBD before a write: undocumented (S1 p.49)")
            s = self._reg(ops[0])
            if kind == "":
                a = self._eval(ops[1], here, allow_undef=True)
                return [op | s, 0 if a is None else a & 0xFFFF], False
            if kind == "@":
                m = self._reg(ops[1], range(1, 7), "address register (R1-R6)")
                return [op | m << 3 | s], False
            v = self._imm(ops[1], here)
            return [op | 7 << 3 | s, 0 if v is None else v & 0xFFFF], False
        # MVI A, DDD / MVI@ MMM, DDD / MVII I, DDD (and ADD.., SUB.., CMP.. etc)
        d = self._reg(ops[1])
        if kind == "":
            a = self._eval(ops[0], here, allow_undef=True)
            if sdbd_prefix:
                self._warn("SDBD before direct mode: undocumented (S1 p.49)")
            return [op | d, 0 if a is None else a & 0xFFFF], False
        if kind == "@":
            m = self._reg(ops[0], range(1, 7), "address register (R1-R6)")
            if sdbd_prefix and m == 6:
                self._warn("SDBD with R6 (stack): undocumented (S1 p.49)")
            return [op | m << 3 | d], False
        v = self._imm(ops[0], here)
        vv = 0 if v is None else v
        if not -0x8000 <= vv <= 0xFFFF:
            raise AsmError("immediate %d does not fit 16 bits" % vv)
        vv &= 0xFFFF
        lineno, sizes = key
        if sdbd_prefix:
            # S1 p.49: with an explicit SDBD the data always fills two bytes.
            return [op | 7 << 3 | d, vv & 0xFF, vv >> 8], False
        wide = vv >> self.prog.romw != 0
        if v is None:
            wide = sizes.get(lineno, False)
        if self.prog.romw == 10 and (wide or sizes.get(lineno, False)):
            # S1 p.49 note: the assembler adds SDBD when the constant does
            # not fit the ROM width. Once a line has grown it stays grown.
            if not sizes.get(lineno):
                sizes[lineno] = True
                self.unstable += 1
            return [0x001, op | 7 << 3 | d, vv & 0xFF, vv >> 8], False
        return [op | 7 << 3 | d, vv], False

    def _sdbd_check(self, sdbd_prefix):
        if sdbd_prefix:
            self._warn("SDBD with R6 (stack): undocumented (S1 p.49)")
        return False


def assemble(text, romw=16, defines=None):
    """Assemble source text; returns a Program. Raises AsmError."""
    return _Assembler(text, romw, defines).run()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src")
    ap.add_argument("-o", "--out", help="raw image (.bin), big-endian words")
    ap.add_argument("--cfg", help="[mapping] file for the raw image")
    ap.add_argument("-l", "--listing", help="listing file ('-' for stdout)")
    ap.add_argument("--romw", type=int, default=16, choices=(10, 16))
    a = ap.parse_args(argv)
    with open(a.src, encoding="utf-8") as f:
        text = f.read()
    try:
        prog = assemble(text, a.romw)
    except AsmError as e:
        print("%s: %s" % (a.src, e), file=sys.stderr)
        if e.text is not None:
            print("    " + e.text.strip(), file=sys.stderr)
        return 1
    for w in prog.warnings:
        print("%s: warning: %s" % (a.src, w), file=sys.stderr)
    if a.out:
        with open(a.out, "wb") as f:
            f.write(prog.image())
    if a.cfg:
        with open(a.cfg, "w", encoding="utf-8") as f:
            f.write(prog.cfg())
    if a.listing:
        if a.listing == "-":
            sys.stdout.write(prog.listing_text())
        else:
            with open(a.listing, "w", encoding="utf-8") as f:
                f.write(prog.listing_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
