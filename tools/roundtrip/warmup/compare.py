#!/usr/bin/env python3
"""Compare the standard-cell content of two GDS layouts (S4 round trip).

Counts the references the top cell makes to sky130_fd_sc_hd masters
(gdstk, repetitions expanded), groups them into classes (tap, decap, fill,
diode, tie, clock buffer, buffer/delay, flop, logic), and reports die size,
placed-cell extent and cell area from the LEF SIZE of each master.

    .venv/bin/python tools/roundtrip/warmup/compare.py REF.gds OURS.gds \
        [--lef pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef] [--json out.json]

The first GDS is the reference (the upstream warm-up or puzzle), the second
is our LibreLane result.  Nothing is written unless --json is given.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import gdstk

REPO = Path(__file__).resolve().parents[3]
DEFAULT_LEF = REPO / "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"
PREFIX = "sky130_fd_sc_hd__"

CLASSES = (
    ("tap", re.compile(r"tapvpwrvgnd_|tap_")),
    ("decap", re.compile(r"decap_")),
    ("fill", re.compile(r"fill_")),
    ("diode", re.compile(r"diode_")),
    ("tie", re.compile(r"conb_")),
    ("clkbuf", re.compile(r"clkbuf_|clkinv|clkdlybuf")),
    ("buf/dly", re.compile(r"buf_|dlygate|dlymetal|dlyb")),
    ("flop", re.compile(r"df|dl[a-z]*tp|sdf|edf")),
)


def classify(master: str) -> str:
    base = master[len(PREFIX):]
    for name, rx in CLASSES:
        if rx.match(base):
            return name
    return "logic"


def drive(master: str) -> str:
    m = re.search(r"_(\d+)$", master)
    return m.group(1) if m else "?"


def lef_sizes(lef: Path) -> dict[str, tuple[float, float]]:
    sizes: dict[str, tuple[float, float]] = {}
    macro = None
    for line in lef.read_text().splitlines():
        t = line.split()
        if not t:
            continue
        if t[0] == "MACRO":
            macro = t[1]
        elif t[0] == "SIZE" and macro:
            sizes[macro] = (float(t[1]), float(t[3]))
        elif t[0] == "END" and len(t) > 1 and t[1] == macro:
            macro = None
    return sizes


def survey(path: Path) -> dict:
    lib = gdstk.read_gds(str(path))
    tops = lib.top_level()
    if len(tops) != 1:
        sys.exit(f"{path}: expected one top cell, found {[c.name for c in tops]}")
    top = tops[0]
    cells: Counter[str] = Counter()
    other: Counter[str] = Counter()
    boxes = []
    for ref in top.references:
        name = ref.cell.name if isinstance(ref.cell, gdstk.Cell) else ref.cell
        n = ref.repetition.size if ref.repetition.size else 1
        if name.startswith(PREFIX):
            cells[name] += n
            bb = ref.bounding_box()
            if bb is not None:
                boxes.append(bb)
        else:
            other[name] += n
    (x0, y0), (x1, y1) = top.bounding_box()
    if boxes:
        px0 = min(b[0][0] for b in boxes)
        py0 = min(b[0][1] for b in boxes)
        px1 = max(b[1][0] for b in boxes)
        py1 = max(b[1][1] for b in boxes)
    else:
        px0 = py0 = px1 = py1 = 0.0
    return {
        "path": str(path),
        "top": top.name,
        "die": [round(v, 3) for v in (x0, y0, x1, y1)],
        "placed_extent": [round(v, 3) for v in (px0, py0, px1, py1)],
        "cells": dict(sorted(cells.items())),
        "non_cell_refs": dict(sorted(other.items())),
    }


def summarise(s: dict, sizes: dict) -> dict:
    by_class: Counter[str] = Counter()
    area_class: Counter[str] = Counter()
    drives: Counter[str] = Counter()
    missing = []
    for m, n in s["cells"].items():
        c = classify(m)
        by_class[c] += n
        if m in sizes:
            w, h = sizes[m]
            area_class[c] += n * w * h
        else:
            missing.append(m)
        if c in ("logic", "flop"):
            drives[drive(m)] += n
    return {
        "count_by_class": dict(by_class),
        "area_by_class_um2": {k: round(v, 3) for k, v in area_class.items()},
        "logic_and_flop_drive_strengths": dict(sorted(drives.items())),
        "instances": sum(s["cells"].values()),
        "masters_without_lef_size": missing,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ref", type=Path, help="reference GDS (upstream)")
    ap.add_argument("ours", type=Path, help="our LibreLane GDS")
    ap.add_argument("--lef", type=Path, default=DEFAULT_LEF)
    ap.add_argument("--json", type=Path, help="write the comparison as JSON")
    a = ap.parse_args()

    sizes = lef_sizes(a.lef)
    ref, ours = survey(a.ref), survey(a.ours)
    rs, os_ = summarise(ref, sizes), summarise(ours, sizes)

    print(f"REF : {ref['path']}  top={ref['top']}  die={ref['die']}  placed={ref['placed_extent']}")
    print(f"OURS: {ours['path']}  top={ours['top']}  die={ours['die']}  placed={ours['placed_extent']}")
    print()
    masters = sorted(set(ref["cells"]) | set(ours["cells"]), key=lambda m: (classify(m), m))
    print(f"{'master':<34}{'class':<9}{'ref':>6}{'ours':>6}{'delta':>7}")
    for m in masters:
        r, o = ref["cells"].get(m, 0), ours["cells"].get(m, 0)
        flag = "" if r == o else ("  only-ours" if r == 0 else ("  only-ref" if o == 0 else ""))
        print(f"{m[len(PREFIX):]:<34}{classify(m):<9}{r:>6}{o:>6}{o - r:>+7}{flag}")
    print(f"{'TOTAL':<43}{rs['instances']:>6}{os_['instances']:>6}{os_['instances'] - rs['instances']:>+7}")
    print()
    classes = [c for c, _ in CLASSES] + ["logic"]
    print(f"{'class':<10}{'ref n':>7}{'ours n':>8}{'ref um2':>11}{'ours um2':>11}")
    for c in classes:
        rn, on = rs["count_by_class"].get(c, 0), os_["count_by_class"].get(c, 0)
        ra, oa = rs["area_by_class_um2"].get(c, 0.0), os_["area_by_class_um2"].get(c, 0.0)
        if rn or on:
            print(f"{c:<10}{rn:>7}{on:>8}{ra:>11.2f}{oa:>11.2f}")
    print()
    print("logic+flop drive strengths  ref:", rs["logic_and_flop_drive_strengths"],
          " ours:", os_["logic_and_flop_drive_strengths"])
    print("non-cell refs (vias etc.)   ref:", sum(ref["non_cell_refs"].values()),
          " ours:", sum(ours["non_cell_refs"].values()))
    for s, sm in ((ref, rs), (ours, os_)):
        if sm["masters_without_lef_size"]:
            print("no LEF SIZE for", sm["masters_without_lef_size"], "in", s["path"])
    if a.json:
        a.json.write_text(json.dumps({"ref": {**ref, **rs}, "ours": {**ours, **os_}}, indent=1))


if __name__ == "__main__":
    main()
