#!/usr/bin/env python3
"""Check the APF package files (dist/) against each other, against DESIGN.md
and against the RTL that answers them.

  sim/check/apf_json_check.py [--root DIR]

Adapted from openFPGA-2600's sim/check/apf_json_check.py (MIT, same author):
the table of Analogue's documented fields and limits (LIMITS) and its
checker are that file's; the checks after it are this core's.

Checks (each prints a line; the last line is APF_JSON pass or APF_JSON FAIL):
- every JSON file in dist/ parses; the core files carry "APF_VER_1";
- every field of every file is one Analogue's APF pages document, within the
  documented limits (lengths, counts, ranges, allowed values);
- core.json: platform "intv", names, the bitstream name tools/package.sh
  writes, and the release zip name (M_Intellivision_Pocket_<version>.zip);
- Platforms/intv.json: the fields of the platform Spiritualized's
  Intellivision core 1.0.2 installs (the platform is shared with it);
- data.json: DESIGN.md 5.6's slots in order (ids 0x100-0x106, file names,
  sizes), each loader slot's bridge address = its number in core_top.v and
  slot_stub.sv (bits 27:24), slot_stub's expected sizes, the required slots
  as core_top.v tells the test pattern, the JLP flash slot's data table
  entry, and the save-state address clear of every slot;
- interact.json: the Pocket's menu limits, every address decoded by
  core_top.v, defaults equal to core_top.v's power-up values;
- video.json: slots 0 and 1 are pocket_video.sv's playfield and border
  windows (from its parameters), the aspect ratios follow from the pixel
  clock (NTSC pixel aspect 12/7, PAL 59/32), and the scaler slot pocket_video
  sends is 0 or 1;
- input.json, info.txt.
"""
import argparse
import json
import os
import re
import sys

# Spiritualized's Intellivision 1.0.2 (2022-11-08 release zip,
# Platforms/intv.json): the platform this core shares.
SPIRIT_PLATFORM = {"category": "Console", "name": "Intellivision", "year": 1979,
                   "manufacturer": "Mattel Electronics"}

# DESIGN.md 5.6: (name, id, filename, size, required). Sizes are the owner's
# files, MAME's expected CRCs.
SLOTS = [
    ("Cartridge", 0x100, None, None, True),
    ("Cartridge CFG", 0x101, None, None, False),
    ("EXEC", 0x102, "exec.bin", 8192, True),
    ("GROM", 0x103, "grom.bin", 2048, True),
    ("ECS ROM", 0x104, "ecs.bin", 24576, False),
    ("Intellivoice", 0x105, "ivoice.bin", 2048, False),
    ("JLP flash", 0x106, None, None, False),
]

# Analogue's documented fields and limits, from the APF developer pages
# https://www.analogue.co/developer/docs/core-definition-files/<file>-json
# (core, data, input, interact, video, audio, variants) and
# https://www.analogue.co/developer/docs/platform-metadata, read 2026-10-24.
# Every field present in a file must have a row (an undocumented field
# fails), and every rule of its row must hold. Paths are dotted keys, []
# meaning each element of an array. Rules:
#   ("len", n)    string of at most n characters
#   ("count", n)  array of at most n elements
#   "u16", "u32"  integer or "0x" hex string, unsigned 16 / 32 bit
#   "s32"         integer or hex string, signed 32 bit
#   "int", "bool", "str", "obj", "arr"   the JSON type
#   ("eq", v), ("in", values), ("re", pattern)
PLATFORM_ID = ("re", r"[a-z0-9][a-z0-9_]{0,14}")   # platform-metadata: a-z 0-9 _, 15, no leading _
INPUT_KEYS = ("pad_btn_a", "pad_btn_b", "pad_btn_x", "pad_btn_y", "pad_trig_l", "pad_trig_r",
              "pad_btn_start", "pad_btn_select")
DISPLAY_MODES = ("0x10", "0x20", "0x21", "0x22", "0x23", "0x30", "0x31", "0x32", "0x40", "0x41", "0x42",
                 "0x51", "0x52", "0x61", "0x62", "0x63", "0x71", "0x72", "0x81", "0x82", "0xE0", "0xE1")
SETTING = ("persist", "writeonly", "defaultval", "value", "value_off", "mask", "group")
LIMITS = {
    "core.json": {
        "core": ["obj"], "core.magic": [("eq", "APF_VER_1")], "core.metadata": ["obj"],
        "core.metadata.platform_ids": ["arr", ("count", 4)],
        "core.metadata.platform_ids[]": ["str", PLATFORM_ID],
        "core.metadata.shortname": ["str", ("len", 31)],
        "core.metadata.description": ["str", ("len", 63)],
        "core.metadata.author": ["str", ("len", 31)],
        "core.metadata.url": ["str", ("len", 63)],
        "core.metadata.version": ["str", ("len", 31)],
        "core.metadata.date_release": ["str", ("len", 10), ("re", r"\d{4}-\d{2}-\d{2}")],
        "core.framework": ["obj"],
        "core.framework.target_product": [("eq", "Analogue Pocket")],
        "core.framework.version_required": ["str", ("re", r"\d+\.\d+")],
        "core.framework.sleep_supported": ["bool"],
        "core.framework.chip32_vm": ["str", ("len", 15)],
        "core.framework.dock": ["obj"],
        "core.framework.dock.supported": [("eq", True)],          # "Must be true"
        "core.framework.dock.analog_output": ["bool"],
        "core.framework.hardware": ["obj"],
        "core.framework.hardware.link_port": ["bool"],
        "core.framework.hardware.cartridge_adapter": ["s32"],
        "core.cores": ["arr", ("count", 8)], "core.cores[]": ["obj"],
        "core.cores[].name": ["str", ("len", 15)],
        "core.cores[].id": ["u32"],
        "core.cores[].filename": ["str", ("len", 15)],
    },
    "data.json": {
        "data": ["obj"], "data.magic": [("eq", "APF_VER_1")],
        "data.data_slots": ["arr", ("count", 32)], "data.data_slots[]": ["obj"],
        "data.data_slots[].name": ["str", ("len", 15)],
        "data.data_slots[].id": ["u16"],
        "data.data_slots[].required": ["bool"],
        "data.data_slots[].parameters": ["u32"],
        "data.data_slots[].nonvolatile": ["bool"],
        "data.data_slots[].deferload": ["bool"],
        "data.data_slots[].secondary": ["bool"],
        "data.data_slots[].filename": ["str", ("len", 31)],
        "data.data_slots[].extensions": ["arr", ("count", 4)],
        "data.data_slots[].extensions[]": ["str", ("len", 7)],
        "data.data_slots[].size_exact": ["u32"],
        "data.data_slots[].size_maximum": ["u32"],
        "data.data_slots[].address": ["u32"],
    },
    "input.json": {
        "input": ["obj"], "input.magic": [("eq", "APF_VER_1")],
        "input.controllers": ["arr", ("count", 4)], "input.controllers[]": ["obj"],
        "input.controllers[].type": [("eq", "default")],
        "input.controllers[].mappings": ["arr", ("count", 8)], "input.controllers[].mappings[]": ["obj"],
        "input.controllers[].mappings[].id": ["u16"],
        "input.controllers[].mappings[].name": ["str", ("len", 19)],
        "input.controllers[].mappings[].key": [("in", INPUT_KEYS)],
    },
    "interact.json": {
        "interact": ["obj"], "interact.magic": [("eq", "APF_VER_1")],
        "interact.variables": ["arr", ("count", 16)], "interact.variables[]": ["obj"],
        "interact.variables[].name": ["str", ("len", 23)],
        "interact.variables[].id": ["u16"],
        "interact.variables[].type": [("in", ("radio", "check", "slider_u32", "list", "number_u32", "action"))],
        "interact.variables[].enabled": ["bool"],
        "interact.variables[].address": ["u32"],
        "interact.variables[].group": ["u32"],
        "interact.variables[].persist": ["bool"],
        "interact.variables[].writeonly": ["bool"],
        "interact.variables[].defaultval": ["s32"],
        "interact.variables[].value": ["s32"],
        "interact.variables[].value_off": ["s32"],
        "interact.variables[].mask": ["u32"],
        "interact.variables[].graphical": ["obj"],
        "interact.variables[].graphical.signed": ["bool"],
        "interact.variables[].graphical.min": ["s32"],
        "interact.variables[].graphical.max": ["s32"],
        "interact.variables[].graphical.adjust_small": ["s32"],
        "interact.variables[].graphical.adjust_large": ["s32"],
        "interact.variables[].options": ["arr", ("count", 16)], "interact.variables[].options[]": ["obj"],
        "interact.variables[].options[].value": ["s32"],
        "interact.variables[].options[].name": ["str", ("len", 23)],
        # Not on the interact.json page; the 7800 core has shipped it empty
        "interact.messages": [("eq", [])],
    },
    "video.json": {
        "video": ["obj"], "video.magic": [("eq", "APF_VER_1")],
        "video.scaler_modes": ["arr", ("count", 8)], "video.scaler_modes[]": ["obj"],
        "video.scaler_modes[].width": ["int"], "video.scaler_modes[].height": ["int"],
        "video.scaler_modes[].aspect_w": ["int"], "video.scaler_modes[].aspect_h": ["int"],
        "video.scaler_modes[].dock_aspect_w": ["int"], "video.scaler_modes[].dock_aspect_h": ["int"],
        "video.scaler_modes[].rotation": [("in", (0, 90, 180, 270))],
        "video.scaler_modes[].mirror": [("in", (0, 1, 2, 3))],
        "video.display_modes": ["arr", ("count", 16)], "video.display_modes[]": ["obj"],
        "video.display_modes[].id": [("in", DISPLAY_MODES)],
        "video.defaults": ["obj"], "video.defaults.sharpness": [("in", (0, 1, 2, 3))],
    },
    "audio.json": {"audio": ["obj"], "audio.magic": [("eq", "APF_VER_1")]},
    "variants.json": {
        "variants": ["obj"], "variants.magic": [("eq", "APF_VER_1")],
        "variants.variant_list": ["arr", ("count", 8)], "variants.variant_list[]": ["obj"],
        "variants.variant_list[].name": ["str", ("len", 15)],
        "variants.variant_list[].id": ["u16"],
        "variants.variant_list[].core_select": ["obj"],
        "variants.variant_list[].core_select.core_id": ["u32"],
        "variants.variant_list[].data_override": ["arr", ("count", 8)],
        "variants.variant_list[].data_override[]": ["obj"],
        "variants.variant_list[].data_override[].data_id_to": ["u16"],
        "variants.variant_list[].data_override[].data_id_from": ["u16"],
        "variants.variant_list[].memory_writes": ["arr", ("count", 16)],
        "variants.variant_list[].memory_writes[]": ["obj"],
        "variants.variant_list[].memory_writes[].address": ["u32"],
        "variants.variant_list[].memory_writes[].data": ["u32"],
    },
    "platform": {
        "platform": ["obj"],
        "platform.category": ["str", ("len", 31)],
        "platform.name": ["str", ("len", 31)],
        "platform.manufacturer": ["str", ("len", 31)],
        "platform.year": ["int"],
    },
}

fails = []


def num(v):
    """An "integer / hex string" field's value, or None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and re.fullmatch(r"0[xX][0-9A-Fa-f]+", v):
        return int(v, 16)
    return None


def rule_ok(rule, v):
    if rule == "obj":
        return isinstance(v, dict)
    if rule == "arr":
        return isinstance(v, list)
    if rule == "str":
        return isinstance(v, str)
    if rule == "bool":
        return isinstance(v, bool)
    if rule == "int":
        return isinstance(v, int) and not isinstance(v, bool)
    if rule in ("u16", "u32", "s32"):
        n = num(v)
        lo, hi = {"u16": (0, 0xFFFF), "u32": (0, 0xFFFFFFFF), "s32": (-2**31, 2**31 - 1)}[rule]
        if rule == "s32" and isinstance(v, str) and n is not None and n <= 0xFFFFFFFF:
            return True     # a hex string is the 32-bit pattern
        return n is not None and lo <= n <= hi
    kind, arg = rule
    if kind == "len":
        return isinstance(v, str) and len(v) <= arg
    if kind == "count":
        return isinstance(v, list) and len(v) <= arg
    if kind == "eq":
        return v == arg and type(v) is type(arg)
    if kind == "in":
        return any(v == x and type(v) is type(x) for x in arg)
    if kind == "re":
        return isinstance(v, str) and re.fullmatch(arg, v) is not None
    raise ValueError(rule)


def check_limits(fname, obj, table):
    """Every field of obj against table; one check line per (field, rule)
    that has values, so a long array still prints one line."""
    seen = {}

    def walk(v, path, where):
        if path:
            seen.setdefault(path, []).append((where, v))
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{path}.{k}" if path else k, f"{where}.{k}" if where else k)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, path + "[]", f"{where}[{i}]")
    walk(obj, "", "")
    n_ok = n_vals = 0
    for path, vals in seen.items():
        rules = table.get(path)
        if rules is None:
            check(False, f"{fname}: {path} is not a documented field")
            continue
        for r in rules:
            for w, v in vals:
                n_vals += 1
                if rule_ok(r, v):
                    n_ok += 1
                else:
                    what = r if isinstance(r, str) else f"{r[0]} {r[1]!r}"
                    check(False, f"{fname}: {w} = {v!r} breaks the documented limit {what}")
    lens = sorted({f"{p.rsplit('.', 1)[-1]} {r[1]}" for p in seen for r in table.get(p, []) if r[0] == "len"})
    check(n_ok == n_vals and all(p in table for p in seen),
          f"{fname}: {sum(p in table for p in seen)}/{len(seen)} fields documented, "
          f"{n_ok}/{n_vals} rule checks within limits"
          + (f" (lengths: {', '.join(lens)})" if lens else ""))


def check(ok, what):
    print(("  ok    " if ok else "  FAIL  ") + what)
    if not ok:
        fails.append(what)
    return ok


def load(path):
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return json.loads(raw.decode("utf-8")), raw
    except Exception as e:  # noqa: BLE001
        check(False, f"{path}: does not parse ({e})")
        return None, raw


def param(text, name):
    m = re.search(r"parameter\s+int\s+" + name + r"\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    dist = os.path.join(root, "dist")
    cname = "Miasmark.Intellivision"
    core_dir = os.path.join(dist, "Cores", cname)
    rtl = os.path.join(root, "src/fpga/core")
    core_top = open(os.path.join(rtl, "core_top.v")).read()
    video = open(os.path.join(rtl, "pocket_video.sv")).read()
    stub = open(os.path.join(rtl, "slot_stub.sv")).read()
    package = open(os.path.join(root, "tools/package.sh")).read()

    print("-- JSON files")
    js = {}
    for d, _, files in os.walk(dist):
        for f in sorted(files):
            if f.endswith(".json"):
                p = os.path.join(d, f)
                obj, raw = load(p)
                rel = os.path.relpath(p, dist)
                check(obj is not None, f"{rel} parses")
                js[rel] = (obj, raw)
    for n in ("core", "data", "input", "interact", "video", "audio", "variants"):
        rel = f"Cores/{cname}/{n}.json"
        obj = js.get(rel, (None,))[0]
        check(obj is not None and obj.get(n, {}).get("magic") == "APF_VER_1", f"{rel}: {n}.magic APF_VER_1")
    if fails:
        print("APF_JSON FAIL")
        return 1

    print("-- Analogue's documented fields and limits (LIMITS)")
    for rel, (obj, _) in sorted(js.items()):
        base = os.path.basename(rel)
        table = LIMITS["platform"] if rel.startswith("Platforms/") else LIMITS.get(base)
        if check(table is not None, f"{rel}: a file the APF pages document"):
            check_limits(rel, obj, table)

    print("-- core.json")
    core = js[f"Cores/{cname}/core.json"][0]["core"]
    md = core["metadata"]
    check(md["platform_ids"] == ["intv"], "platform_ids [\"intv\"] (Spiritualized's Intellivision core's platform)")
    check(f"{md['author']}.{md['shortname']}" == cname, f"author.shortname = {cname}")
    check(bool(re.fullmatch(r"\d+\.\d+\.\d+", md["version"])), f"version {md['version']}")
    check(core["framework"]["sleep_supported"] is False, "sleep_supported false (save states come in step 7)")
    rbf = core["cores"][0]["filename"]
    check(rbf == "intv.rbf_r", "bitstream intv.rbf_r")
    check(f'"$CORE/{rbf}"' in package and cname in package, f"tools/package.sh writes {rbf} into Cores/{cname}")
    check("M_Intellivision_Pocket_${VERSION}.zip" in package, "tools/package.sh names the zip M_Intellivision_Pocket_<version>.zip")

    print("-- platform")
    pl = js.get("Platforms/intv.json", ({},))[0].get("platform")
    check(pl == SPIRIT_PLATFORM, f"Platforms/intv.json fields = Spiritualized Intellivision 1.0.2's {SPIRIT_PLATFORM}")
    others = [p for p in os.listdir(os.path.join(dist, "Platforms")) if p.endswith(".json") and p != "intv.json"]
    check(not others, f"no other platform files ({others})")
    check(sorted(os.listdir(os.path.join(dist, "Cores"))) == [cname], f"dist/Cores holds {cname} only")
    check(os.path.exists(os.path.join(dist, "Assets/intv/common/.keep")), "dist/Assets/intv/common/.keep")

    print("-- data.json")
    slots = js[f"Cores/{cname}/data.json"][0]["data"]["data_slots"]
    check([s["name"] for s in slots] == [s[0] for s in SLOTS], f"slot names and order {[s['name'] for s in slots]}")
    ids = [int(s["id"], 16) for s in slots]
    check(ids == [s[1] for s in SLOTS], "slot ids 0x100-0x106 (DESIGN.md 5.6)")
    m = dict(re.findall(r"localparam \[15:0\] (SLOT_\w+)\s*=\s*16'h([0-9A-Fa-f]+);", core_top))
    want = dict(zip(("SLOT_CART", "SLOT_CFG", "SLOT_EXEC", "SLOT_GROM", "SLOT_ECS", "SLOT_IVOICE", "SLOT_JLP"), ids))
    check({k: int(v, 16) for k, v in m.items()} == want, "core_top.v SLOT_* = data.json ids")
    sizes = re.search(r"SIZE \[6\] = '\{([^}]*)\}", stub)
    stub_sizes = [int(x.split("'d")[1]) for x in sizes.group(1).split(",")] if sizes else []
    req = re.search(r"\.slot_req\s*\(\s*6'b([01]{6})\s*\)", core_top)
    req = [req.group(1)[5 - i] == "1" for i in range(6)] if req else []
    loader_mask = re.search(r"\.ADDRESS_MASK_UPPER_4\s*\(\s*4'h([0-9A-Fa-f])\s*\)", core_top)
    for i, (s, (name, sid, fn, size, required)) in enumerate(zip(slots, SLOTS)):
        addr = int(s["address"], 16)
        check(s.get("required", False) is required, f"{name}: required {required}")
        if fn:
            check(s.get("filename") == fn and int(s["parameters"], 16) == 0x88
                  and int(s["size_maximum"], 16) == size,
                  f"{name}: {fn}, {size} bytes, loaded at start, not reloadable, in /Assets/intv/common/ (0x88)")
        if i < 6:
            check(loader_mask and addr >> 28 == int(loader_mask.group(1), 16) and addr == i << 24,
                  f"{name}: address {s['address']} reaches the data loader as slot {i} (bits 27:24)")
            check(i < len(stub_sizes) and stub_sizes[i] == (size or 0), f"{name}: slot_stub expects {size or 'any size'}")
            check(i < len(req) and req[i] == required, f"{name}: core_top tells the test pattern required = {required}")
    cart, cfg = slots[0], slots[1]
    check(int(cart["parameters"], 16) == 0x109 and int(cfg["parameters"], 16) == 0x109,
          "cartridge and config: reloadable, full core reload (0x109)")
    check(cart["extensions"] == ["int", "bin", "rom", "itv"] and cfg["extensions"] == ["cfg"],
          "extensions: cartridge int/bin/rom/itv, config cfg (DESIGN.md 5.6)")
    jlp = slots[6]
    check(jlp.get("nonvolatile") is True and int(jlp["parameters"], 16) == 0x84 and "filename" not in jlp,
          "JLP flash: nonvolatile, one file per game (0x84)")
    check(int(jlp["address"], 16) == 0x20000000, "JLP flash at 0x20000000 (core_top's bridge map; reads 0 until step 11)")
    dt = re.findall(r"datatable_addr <= 10'd(\d+) \* 2 \+ 1;\s*\n\s*datatable_data <= 32'd(\d+);", core_top)
    check(dt == [("6", "0")], f"core_top reports JLP flash (slot index 6) as 0 bytes until step 11: {dt}")
    ss = re.search(r"localparam \[31:0\] SS_ADDR = 32'h([0-9A-Fa-f]+);", core_top)
    ss = int(ss.group(1), 16) if ss else None
    check(ss == 0x50000000 and all(int(s["address"], 16) >> 24 != ss >> 24 for s in slots),
          "save-state blob at 0x50000000 (DESIGN.md 4.1), clear of every slot")
    check(re.search(r"wire\s+savestate_supported\s*=\s*1'b0;", core_top) is not None,
          "save states answered 'not supported' until step 7")

    print("-- interact.json")
    var = js[f"Cores/{cname}/interact.json"][0]["interact"]["variables"]
    reload = sum(1 for s in slots if int(s["parameters"], 16) & 1)
    check(len(var) <= 16 and len(var) + reload <= 20, f"{len(var)} entries + {reload} reloadable slots (limits 16, 20)")
    check(len({v["id"] for v in var}) == len(var), "entry ids unique")
    blk = core_top.split("bridge_addr[31:24] == 8'h10", 1)[1].split("endcase", 1)[0]
    decoded = {int(x, 16) for x in re.findall(r"12'h([0-9A-Fa-f]{3}):", blk)}
    for v in var:
        addr = int(v["address"], 16)
        check(addr >> 24 == 0x10 and (addr & 0xFFF) in decoded and (addr & 0x00FFF000) == 0,
              f"{v['name']}: {v['address']} decoded by core_top")
        if v["type"] == "action":
            check(all(k not in v for k in ("writeonly", "persist", "defaultval")), f"{v['name']}: action, no setting fields")
        else:
            check(v.get("writeonly") is True and v.get("persist") is True, f"{v['name']}: writeonly, persist")
        if v["type"] == "list":
            mask = int(v["mask"], 16)
            opts = v["options"]
            check(all(o["value"] & mask == 0 for o in opts) and len({o["value"] for o in opts}) == len(opts)
                  and v["defaultval"] in [o["value"] for o in opts],
                  f"{v['name']}: options inside mask {v['mask']}, unique, default among them")
    border = [v for v in var if v["name"] == "Border"]
    pw = re.search(r"reg\s+set_border\s*=\s*1'b([01]);", core_top)
    check(len(border) == 1 and pw and border[0]["defaultval"] == int(pw.group(1))
          and re.search(r"12'h204:\s*set_border\s*<=\s*bridge_wr_data\[0\];", core_top) is not None
          and int(border[0]["address"], 16) & 0xFFF == 0x204,
          "Border: core_top's set_border at 0x204, power-up value = the menu default")
    check(re.search(r"12'h200:\s*menu_reset_cnt", core_top) is not None and
          any(v["name"] == "Reset" and int(v["address"], 16) & 0xFFF == 0x200 for v in var), "Reset action at 0x200")
    total_opts = sum(len(v.get("options", [])) for v in var)
    check(total_opts <= 51, f"{total_opts} list options in all (51 proven on hardware by the 7800 core)")

    print("-- video.json")
    vj = js[f"Cores/{cname}/video.json"][0]["video"]
    modes = [(s["width"], s["height"], s["aspect_w"], s["aspect_h"]) for s in vj["scaler_modes"]]
    check(modes == [(160, 192, 10, 7), (167, 210, 15, 11), (160, 192, 20, 13), (168, 208, 67, 45)],
          f"scaler modes = DESIGN.md 6.1's: {modes}")
    pw_, ph_ = param(video, "PF_W"), param(video, "PF_H")
    bw = pw_ + param(video, "BD_L") + param(video, "BD_R")
    bh = ph_ + param(video, "BD_T") + param(video, "BD_B")
    check(modes[0][:2] == (pw_, ph_), f"slot 0 = pocket_video's playfield window {pw_} x {ph_}")
    check(modes[1][:2] == (bw, bh), f"slot 1 = pocket_video's border window {bw} x {bh}")
    check("{8'd0, 2'd0, border_on, 13'd0}" in video, "pocket_video sends slot 0 or 1 (border_on) in rgb[23:13]")
    # Pixel aspect: NTSC square pixels at 135/11 MHz on 480 lines, so a 240p
    # line of 315/88 MHz pixels is (135/11) / (315/88) / 2 = 12/7; PAL
    # 14.75 MHz on 576 lines and 4 MHz pixels: 59/32.
    for i, par in ((0, 12 / 7), (1, 12 / 7), (2, 59 / 32), (3, 59 / 32)):
        w, h, aw, ah = modes[i]
        dar = w * par / h
        check(abs(aw / ah / dar - 1) < 0.005, f"slot {i}: {aw}:{ah} = {aw / ah:.4f}, picture {w}x{h} at pixel aspect {par:.4f} = {dar:.4f}")
    check([d["id"] for d in vj.get("display_modes", [])] == ["0x10", "0x20", "0x30", "0x40"],
          "display_modes 0x10-0x40, as the 7800 core's")

    print("-- input.json, info.txt")
    mp = js[f"Cores/{cname}/input.json"][0]["input"]["controllers"][0]["mappings"]
    check(len({x["id"] for x in mp}) == len(mp) and len({x["key"] for x in mp}) == len(mp) and all(x["name"] for x in mp),
          "input.json: unique ids and keys, every button named")
    info = open(os.path.join(core_dir, "info.txt")).read()
    check(all(w in info for w in ("exec.bin", "grom.bin", "ecs.bin", "ivoice.bin", "/Assets/intv/common/")),
          "info.txt names the system ROM files and their folder")

    print("APF_JSON " + ("pass" if not fails else f"FAIL ({len(fails)})"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
