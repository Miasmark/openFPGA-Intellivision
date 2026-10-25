#!/bin/bash
# Repository hygiene before a commit or a merge, over the changes from BASE
# (default: the repository's root commit) to HEAD. Adapted from
# openFPGA-7800's sim/check/hygiene.sh (MIT, same author).
#
# Checks:
#   - game data, never in git (DESIGN.md section 1):
#       * no file with a cartridge, BIOS or archive extension (.int, .bin,
#         .rom, .itv, .a26, .a78, .zip, .7z), no save state or nonvolatile
#         save (.sav, .ss, .sta), no image or frame dump (.png, .ppm, .pgm,
#         .bmp, .gif, .jpg), no audio dump (.wav), no waveform or trace
#         (.vcd, .fst, .ghw, .trace, .trc), nothing under sim/work;
#       * no file whose CRC32 is a known system ROM (EXEC, GROM, ECS,
#         SP0256-012; the list below, from MAME's ROM definitions);
#       * with --data DIR (or HYGIENE_DATA=DIR:DIR...): no file whose CRC32
#         equals a file in DIR (zip members too), and no file that contains
#         a run of 48 bytes or more of one, as raw bytes, as byte-swapped
#         16-bit words, or written out as hex numbers (a $readmemh, .mif or
#         .hex dump). Runs with too few distinct byte values (padding,
#         fills) are not counted.
#   - no binary file and no file over LIMIT bytes (default 262144) unless
#     --allow names it;
#   - no absolute path into the temporary directory (/tmp, /var/tmp,
#     /private/tmp), a scratch directory, or a home directory in an added
#     line. Only a path whose "tmp" continues a relative one (work, ./, ~,
#     $WORK, ${WORK} before it) is let through, and so is the directory
#     itself without a path into it;
#   - none of the assistant and model names in a list kept OUTSIDE the
#     repository: give it as --names FILE or HYGIENE_NAMES=FILE, one name per
#     line, matched case-insensitively, a name of 5 or more characters
#     anywhere (inside an identifier too), a shorter one as a word. A hit is
#     reported by its line number in the list, never by the name. Without
#     the list, or with a list that holds no name, the run fails: the check
#     did not happen.
# Commit messages are not files and are not checked here.
#
#   sim/check/hygiene.sh [--base REV] [--names FILE] [--data DIR]...
#                        [--allow PATH]... [--limit BYTES] [--repo DIR]
# --repo checks another checkout (default: the one this script is in).
# Exit status 0 when nothing is found, 1 otherwise, 2 on a usage error.
# SPDX-License-Identifier: MIT
set -e -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)"
BASE=
NAMES="${HYGIENE_NAMES:-}"
LIMIT=262144
ALLOW=()
DATA=()
IFS=: read -r -a DATA <<< "${HYGIENE_DATA:-}"
while [ $# -gt 0 ]; do
	case "$1" in
		--base) BASE="$2"; shift 2 ;;
		--names) NAMES="$2"; shift 2 ;;
		--data) DATA+=("$2"); shift 2 ;;
		--allow) ALLOW+=("$2"); shift 2 ;;
		--limit) LIMIT="$2"; shift 2 ;;
		--repo) REPO="$(git -C "$2" rev-parse --show-toplevel)" || exit 2; shift 2 ;;
		*) echo "hygiene.sh: unknown argument $1" >&2; exit 2 ;;
	esac
done
if [ -z "$BASE" ]; then
	BASE="$(git -C "$REPO" rev-list --max-parents=0 HEAD | tail -n 1)"
fi
git -C "$REPO" rev-parse --verify -q "$BASE^{commit}" > /dev/null || { echo "hygiene.sh: no commit $BASE" >&2; exit 2; }
DATALIST="$(printf '%s\n' "${DATA[@]}" | grep -v '^$' || true)"
# -I: the data directories hold files from outside (game images, BIOS).
python3 -I - "$REPO" "$BASE" "$NAMES" "$LIMIT" "$DATALIST" "${ALLOW[@]}" <<'PY'
import os, re, subprocess, sys, zipfile, zlib
repo, base, names, limit, datalist = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
allow = set(sys.argv[6:])
datadirs = [d for d in datalist.split("\n") if d]

def git(*a, binary=False):
    r = subprocess.run(["git", "-C", repo] + list(a), capture_output=True, check=True)
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")

# Known system ROMs: CRC32 -> what it is. CRCs from MAME's ROM definitions
# (mattel/intv.cpp:551, 565; bus/intv/ecs.cpp:114-116; bus/intv/voice.cpp:87)
# and the size of the joined 24 KiB ECS file. Hashes only, no data.
KNOWN = {
    0xcbce86f7: "EXEC", 0xea552a22: "EXEC (Sears)", 0x683a4158: "GROM",
    0x0de7579d: "SP0256-012 (Intellivoice)", 0x5f9d05e5: "ECS ROM $2000",
    0x46bb1f48: "ECS ROM $7000", 0xc2ebcd90: "ECS ROM $E000",
    0xea790a06: "ECS ROM, 24 KiB joined",
}

# Absolute paths into the temporary directory, a scratch directory or a home
# directory (spelled in pieces, so that this file does not match itself).
T = "tmp/"
TMP_AT = re.compile(r"/(?:var/|private/)?" + T)
FILE_URL = re.compile(r"file:/{2}[^/\s\"'`]*$", re.I)
SCRATCH = "scratch" + "pad"
HOME_AT = re.compile(r"(?<![\w.~$})*%])/" + "ho" + r"me/[A-Za-z0-9_.-]+/")

def abs_tmp(text):
    text = text.replace("\\/", "/")
    for m in TMP_AT.finditer(text):
        i = m.start()
        if m.group(0) != "/" + T:
            return True                      # the var and private ones
        if FILE_URL.search(text[:i]):
            return True                      # a file URL, with a host or none
        j = i - 1
        while j >= 0 and text[j] == "/":
            j -= 1                           # a run of slashes: what is before it decides
        c = text[j] if j >= 0 else ""
        if c == "" or not re.match(r"[\w.~$})*%]", c):
            return True
        if re.search(r"(?:^|[\s\"'`=(:,\[{|>])-[A-Za-z]$", text[:i]):
            return True                      # an option glued to the path
    # a scratch directory as a path component (not "scratchpad RAM")
    return re.search(r"[/\\]" + SCRATCH + r"|" + SCRATCH + r"[/\\]", text, re.I) is not None

BAD_EXT = re.compile(r"\.(int|bin|rom|itv|a26|a78|zip|7z|sav|ss|sta|png|ppm|pgm|bmp|gif|jpe?g|wav|vcd|fst|ghw|trace|trc)$")

# Reference data for the content check: whole-file CRCs, and every W-byte
# window at a stride of S bytes. A copied run of W+S-1 bytes or more always
# holds one whole indexed window.
W, S, MIN_DISTINCT = 32, 16, 8

# Text and media files in a data directory (game lists, scans, manuals) are
# not ROM data: they are left out, and so is any file that is mostly
# printable text.
SKIP_EXT = (".txt", ".xml", ".json", ".md", ".cfg", ".nfo", ".pdf", ".pptx", ".docx",
            ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".mp4", ".mkv", ".avi")

def is_text(b):
    return sum(32 <= c < 127 or c in (9, 10, 13) for c in b) >= 0.9 * len(b)

def ref_blobs():
    for name, b in ref_files():
        if not name.lower().endswith(SKIP_EXT) and b and not is_text(b):
            yield name, b

def ref_files():
    for d in datadirs:
        for root, _, fs in os.walk(d):
            for f in sorted(fs):
                p = os.path.join(root, f)
                try:
                    if f.lower().endswith(".zip"):
                        with zipfile.ZipFile(p) as z:
                            for i in z.infolist():
                                if not i.is_dir() and i.file_size <= 4 << 20 \
                                        and not i.filename.lower().endswith(SKIP_EXT):
                                    yield f"{f}:{i.filename}", z.read(i)
                    elif os.path.getsize(p) <= 4 << 20 and not f.lower().endswith(SKIP_EXT):
                        yield f, open(p, "rb").read()
                except (OSError, zipfile.BadZipFile):
                    pass

def swap16(b):
    b = b[: len(b) & ~1]
    out = bytearray(len(b))
    out[0::2], out[1::2] = b[1::2], b[0::2]
    return bytes(out)

HEXTOK = re.compile(r"(?:0x|\$|\b)([0-9A-Fa-f]{1,4})\b")

def hex_forms(text):
    """A text dump as bytes: the hex numbers in it, as 16-bit big-endian
    words and (when all fit) as bytes. In "address : data" lines only the
    data counts."""
    vals = []
    for line in text.splitlines():
        line = line.split("//")[0].split("--")[0]
        if ":" in line:
            line = line.split(":", 1)[1]
        vals += [int(m, 16) for m in HEXTOK.findall(line)]
    if len(vals) < W // 2:
        return []
    forms = [b"".join(v.to_bytes(2, "big") for v in vals)]
    if max(vals) <= 0xFF:
        forms.append(bytes(vals))
    return forms

refcrc, windows = {}, {}
nref = 0
for name, b in ref_blobs():
    nref += 1
    refcrc.setdefault(zlib.crc32(b), name)
    for off in range(0, len(b) - W + 1, S):
        w = b[off:off + W]
        if len(set(w)) >= MIN_DISTINCT:
            windows.setdefault(w, name)

def data_hit(blob):
    c = zlib.crc32(blob)
    if c in KNOWN:
        return f"system ROM ({KNOWN[c]})"
    if c in refcrc:
        return "same CRC32 as a data file"
    if not windows:
        return None
    forms = [blob, swap16(blob)]
    try:
        forms += hex_forms(blob.decode("ascii"))
    except UnicodeDecodeError:
        pass
    for b in forms:
        for off in range(0, len(b) - W + 1):
            if b[off:off + W] in windows:
                return f"holds a run of a data file (offset {off} of one form)"
    return None

bad = []
head = git("rev-parse", "--short", "HEAD").strip()
changed = [l.split("\t") for l in git("diff", "--name-status", "--no-renames", base, "HEAD").splitlines() if l]
files = [p[-1] for p in changed if not p[0].startswith("D")]
numstat = {l.split("\t")[2]: l.split("\t")[:2] for l in git("diff", "--numstat", "--no-renames", base, "HEAD").splitlines() if l}
for f in files:
    if f in allow:
        continue
    if BAD_EXT.search(f.lower()):
        bad.append(f"game-data, image, dump or trace extension: {f}")
    if f.startswith("sim/work"):
        bad.append(f"under sim/work: {f}")
    try:
        blob = git("cat-file", "blob", f"HEAD:{f}", binary=True)
    except subprocess.CalledProcessError:
        blob = b""
    if numstat.get(f, ["", ""])[0] == "-":
        bad.append(f"binary file: {f} ({len(blob)} bytes)")
    elif len(blob) > limit:
        bad.append(f"over {limit} bytes: {f} ({len(blob)} bytes)")
    hit = data_hit(blob) if blob else None
    if hit:
        bad.append(f"game data: {f}: {hit}")

# added lines
diff = git("diff", "-U0", "--no-color", "--no-renames", base, "HEAD")
cur, added = None, []
for l in diff.splitlines():
    if l.startswith("+++ "):
        cur = l[6:] if l.startswith("+++ b/") else None
    elif l.startswith("+") and cur and cur not in allow:
        added.append((cur, l[1:]))
for f, t in added:
    if abs_tmp(t):
        bad.append(f"absolute path into /tmp or a scratch directory: {f}: {t.strip()[:120]}")
    if HOME_AT.search(t.replace("\\/", "/")):
        bad.append(f"absolute path into a home directory: {f}: {t.strip()[:120]}")

if not names:
    bad.append("assistant and model names: no list given (--names FILE or HYGIENE_NAMES): not checked")
else:
    rp = os.path.realpath(names)
    if rp.startswith(os.path.realpath(repo) + os.sep):
        bad.append("the name list is inside the repository")
    elif not os.path.exists(rp):
        bad.append("the name list does not exist")
    else:
        words = [(n, w.strip()) for n, w in enumerate(open(rp, errors="replace"), 1)
                 if w.strip() and not w.strip().startswith("#")]
        if not words:
            # an empty or truncated list checks nothing: that is no pass
            bad.append("the name list holds no names (empty, or comment lines only): not checked")
        pats = [(n, re.compile(re.escape(w), re.I) if len(w) >= 5 else
                 re.compile(r"(?<![A-Za-z0-9])" + re.escape(w) + r"(?![A-Za-z0-9])", re.I)) for n, w in words]
        for f, t in added:
            for n, p in pats:
                if p.search(t):
                    bad.append(f"listed name (list line {n}) in an added line: {f}")
        for f in files:
            for n, p in pats:
                if p.search(f):
                    bad.append(f"listed name (list line {n}) in a file name: {f}")
        print(f"  names: {len(words)} checked over {len(added)} added lines")

if datadirs:
    print(f"  game data: {nref} data files, {len(windows)} windows, {len(KNOWN)} known system ROM CRCs")
else:
    print(f"  game data: {len(KNOWN)} known system ROM CRCs only (no --data: no content scan)")
print(f"hygiene {base[:7]}..{head}: {len(files)} files changed, {len(added)} lines added")
for b in bad:
    print("  FAIL: " + b)
print("HYGIENE " + ("pass" if not bad else f"FAIL ({len(bad)} finding(s))"))
sys.exit(0 if not bad else 1)
PY
