#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Miasmark and contributors
"""Write an openFPGA instance JSON for each cartridge + CFG pair in a folder, so the
Pocket loads both with one pick in the Cartridge slot (data.json: the Cartridge
slot 0x100 has the instance bit; DESIGN.md 5.6).

  python3 tools/make_instances.py FOLDER [--dry-run]

For every NAME.bin or NAME.int in FOLDER with a NAME.cfg beside it, writes
NAME.json naming both files (slots 0x100 and 0x101). Copy the folder, .json files
included, to /Assets/intv/Miasmark.Intellivision/ (or a subfolder of it) on the SD
card and pick NAME.json. An existing NAME.json is kept unless it is one of ours.
Cartridges without a .cfg need no instance: pick them directly.
"""
import argparse
import json
import os
import sys

SLOT_CART, SLOT_CFG = 0x100, 0x101
MAX_NAME = 255                  # openFPGA's limit for a filename in an instance


def instance(cart, cfg):
    """The fields and their form as in instance files known to load on the Pocket (jotego's
    jtbin, pocket/raw/Assets/*/jotego.*/*.json: integer slot ids, an empty data_path); each
    file is looked up in its own slot's folder (both slots here are core-specific)."""
    return {"instance": {
        "magic": "APF_VER_1",
        "data_path": "",
        "data_slots": [
            {"id": SLOT_CART, "filename": cart},
            {"id": SLOT_CFG, "filename": cfg},
        ],
    }}


def ours(path):
    """True when path is an instance this tool wrote (same two slots, nothing else)."""
    try:
        d = json.load(open(path))["instance"]
        return [int(str(s["id"]), 0) for s in d["data_slots"]] == [SLOT_CART, SLOT_CFG] and \
            set(d) <= {"magic", "data_path", "data_slots"}
    except (OSError, ValueError, KeyError, TypeError):
        return False


def pairs(folder):
    names = os.listdir(folder)
    lower = {n.lower(): n for n in names}
    for n in sorted(names):
        base, ext = os.path.splitext(n)
        if ext.lower() not in (".bin", ".int"):
            continue
        cfg = lower.get(base.lower() + ".cfg")
        if cfg:
            yield base, n, cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    made = kept = 0
    for base, cart, cfg in pairs(a.folder):
        out = os.path.join(a.folder, base + ".json")
        if max(len(cart), len(cfg)) > MAX_NAME:
            print("skip %s: filename longer than %d" % (cart, MAX_NAME))
            continue
        if os.path.exists(out) and not ours(out):
            print("keep %s: not written by this tool" % out)
            kept += 1
            continue
        if not a.dry_run:
            with open(out, "w") as f:
                json.dump(instance(cart, cfg), f, indent=2)
                f.write("\n")
        print("%s %s: %s + %s" % ("would write" if a.dry_run else "wrote", base + ".json", cart, cfg))
        made += 1
    print("%d instance file(s)%s, %d kept" % (made, " (dry run)" if a.dry_run else "", kept))
    return 0


if __name__ == "__main__":
    sys.exit(main())
