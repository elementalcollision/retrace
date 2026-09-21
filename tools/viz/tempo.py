"""TEMPO's die, one panel per RTL module (PRD S1), from its own DEF and LEF.

TEMPO's netlist is flat and its gates are anonymous (`_12345_`), but the nets that
registers drive keep their hierarchical names (`u_top.u_core.rf[3][7]`, 2,898 of
35,543 nets). The module of every other cell is inferred from connectivity alone:

  1. seeds: a cell driving a net named `u_top.<module>....` belongs to <module>
     (the SRAM macro, `u_top.u_mem...`, to u_mem);
  2. every other logic cell takes the module of its nearest seed in the cell graph
     (cells joined by a net of at most FANOUT pins, so the clock, reset and other
     broadcast nets do not merge modules): a breadth-first search from all seeds at
     once, where a cell reached from several labelled neighbours takes the label most
     of them carry, ties broken by module name;
  3. clock-tree cells (driving `clknet_*` or the clock port) form their own panel.

Placement plays no part, so the clustering the panels show is independent evidence
that the labels are right. The labels are checked against the seeds: hide a fifth of
them (fixed random seed), label from the rest, and count how many hidden seeds get
their own module back (`holdout()`).

    python -m tools.viz.tempo docs/figures     # tempo_<module>.png panels (transparent), the
                                               # tempo_modules.png sheet and tempo_modules.json
"""

import collections
import os
import random
import re
import sys

from ..retrace.defparse import read_def
from ..tempo import lvs
from .layout import LIGHT, NEUTRAL, Die, png_panel, png_sheet

FANOUT = 12
MODULES = ["u_core", "u_tio", "u_ser", "u_crc", "u_sys", "u_host", "u_arb", "u_mem"]
RTL_NAME = {"u_core": "tempo_core", "u_tio": "tempo_tio", "u_ser": "tempo_ser_block", "u_crc": "tempo_crc_block",
            "u_sys": "tempo_sys", "u_host": "tempo_host", "u_arb": "tempo_arb", "u_mem": "tempo_mem"}
_HIER = re.compile(r"^u_top\.(u_[a-z0-9_]+)\.")
_ORIENT_SWAP = {"E", "W", "FE", "FW"}


def design():
    """(die, def data, lef, logic cell names, {cell: master})."""
    lef = lvs.load_lef()
    d = read_def(lvs.DEF)
    cells, master = {}, {}
    for name, (m, x, y, orient) in d["components"].items():
        w, h = lef[m]["size"]
        if orient in _ORIENT_SWAP:
            w, h = h, w
        cells[name] = (x / 1000, y / 1000, x / 1000 + w, y / 1000 + h)
        master[name] = m
    physical = tuple(lvs.IHP_SG13CMOS5L.prefix + p for p in lvs.IHP_SG13CMOS5L.physical_prefixes)
    logic = {n for n, m in master.items() if not m.startswith(physical)}
    macros = [("SRAM", cells[n]) for n, m in master.items() if m in lvs.IHP_SG13CMOS5L.macro_prefixes]
    width, height = _die_area(lvs.DEF)
    die = Die(width, height, {n: cells[n] for n in logic}, macros)
    return die, d, lef, logic, master


def _die_area(path):
    with open(path) as f:
        for line in f:
            if line.startswith("DIEAREA"):
                nums = [int(v) for v in re.findall(r"-?\d+", line)]
                return nums[2] / 1000, nums[3] / 1000
    raise ValueError("no DIEAREA")


def _graph(d, lef, logic, master):
    """Seeds, clock-tree cells, and the cell adjacency over nets of <= FANOUT pins."""
    seeds, clock = {}, set()
    adj = collections.defaultdict(set)
    for net, conns in d["nets"].items():
        insts = [i for i, _p in conns if i != "PIN" and i in logic]
        drivers = [i for i, p in conns if i != "PIN" and i in logic
                   and lef[master[i]]["pins"].get(p, {}).get("direction") == "OUTPUT"]
        name = net.replace("\\", "")
        if name.startswith("clknet_") or name in ("clk",):
            clock.update(drivers)
            continue
        m = _HIER.match(name)
        if m and m.group(1) in MODULES:
            for i in drivers:
                seeds.setdefault(i, m.group(1))
        if len(insts) <= FANOUT:
            for a in insts:
                adj[a].update(b for b in insts if b != a)
    for n, m in master.items():
        if m in lvs.IHP_SG13CMOS5L.macro_prefixes:
            seeds[n] = "u_mem"
    for n in clock:
        seeds.pop(n, None)
    return seeds, clock, adj


def propagate(seeds, adj, cells):
    """Nearest-seed labels by multi-source BFS: {cell: module}."""
    label = dict(seeds)
    frontier = sorted(seeds)
    while frontier:
        votes = collections.defaultdict(collections.Counter)
        for a in frontier:
            for b in adj.get(a, ()):
                if b not in label and b in cells:
                    votes[b][label[a]] += 1
        nxt = []
        for b, v in votes.items():
            best = max(v.values())
            label[b] = min(k for k, c in v.items() if c == best)
            nxt.append(b)
        frontier = sorted(nxt)
    return label


def holdout(seeds, adj, cells, frac=0.2, rng_seed=20260921):
    """Hide `frac` of the seeds, label from the rest; {module: (right, hidden)}."""
    names = sorted(seeds)
    hidden = set(random.Random(rng_seed).sample(names, round(frac * len(names))))
    label = propagate({n: seeds[n] for n in names if n not in hidden}, adj, cells)
    score = collections.defaultdict(lambda: [0, 0])
    for n in hidden:
        score[seeds[n]][1] += 1
        score[seeds[n]][0] += label.get(n) == seeds[n]
    return {m: tuple(v) for m, v in score.items()}


def modules():
    die, d, lef, logic, master = design()
    seeds, clock, adj = _graph(d, lef, logic, master)
    cells = logic - clock
    label = propagate(seeds, adj, cells)
    groups = collections.defaultdict(set)
    for n, m in label.items():
        groups[m].add(n)
    groups["clock tree"] = clock
    unassigned = cells - set(label)
    return die, groups, seeds, adj, cells, unassigned


def main(argv=None):
    import json

    outdir = (argv or sys.argv[1:] or ["docs/figures"])[0]
    os.makedirs(outdir, exist_ok=True)
    die, groups, seeds, adj, cells, unassigned = modules()
    score = holdout(seeds, adj, cells)
    right = sum(r for r, _h in score.values())
    hidden = sum(h for _r, h in score.values())
    print(f"logic cells {len(die.cells)}; seeds {len(seeds)}; clock tree {len(groups['clock tree'])}; "
          f"unassigned {len(unassigned)}")
    print(f"holdout: {right}/{hidden} hidden seeds get their own module back ({right / hidden:.1%})")
    panels, manifest = [], {"holdout": [right, hidden], "cells": len(die.cells), "seeds": len(seeds),
                            "unassigned": len(unassigned), "panels": []}
    for m in MODULES + ["clock tree"]:
        names = groups.get(m, set())
        r, h = score.get(m, (0, 0))
        check = f", holdout {r}/{h}" if h else ""
        print(f"  {m:10s} {len(names):6d} cells, {sum(1 for n in names if n in seeds):5d} seeds{check}")
        slug = m.replace(" ", "_")
        png_panel(die, names, os.path.join(outdir, f"tempo_{slug}.png"), width_px=480, colours=NEUTRAL)
        sub = f"{RTL_NAME.get(m, 'CTS buffers')}, {len(names):,} cells"
        panels.append((m, sub, names, ()))
        manifest["panels"].append({"title": m, "subtitle": sub, "file": f"tempo_{slug}.png",
                                   "cells": len(names), "holdout": [r, h]})
    with open(os.path.join(outdir, "tempo_modules.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    png_sheet(die, panels, os.path.join(outdir, "tempo_modules.png"), cols=3, panel_w=520, colours=LIGHT,
              heading="TEMPO (tt_um_elementalcollision_tempo), IHP sg13cmos5l: cells by RTL module")
    print(f"wrote {outdir}/tempo_*.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
