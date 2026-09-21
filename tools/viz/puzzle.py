"""The puzzle's die, one panel per recovered block (PRD S1).

A cell belongs to a block when it is one of the block's flops or lies in the proven
logic cone behind one (`tools.analysis.cone.cone_sources`, cut at flops): 696 of the
728 logic cells, 14 of them shared (13 by two cones, one by five) and drawn in each. The other 32 are
the clock tree. The flops were grouped from the flop-level SCCs together with their
placement (`cone.write_blocks`), but the gates are assigned by logic alone, so gates
that sit beside their block's flops are the layout's own evidence.

    python -m tools.viz.puzzle docs/figures/puzzle_blocks.svg
"""

import collections
import json
import sys

from ..analysis import cone
from .layout import Die, svg_panels

ORDER = ["counter", "array", "left_top", "left_bottom", "check", "outgen"]


def _rect(inst, lef):
    w, h = lef[inst["master"]]["size"]
    if inst["orient"] in ("E", "W", "FE", "FW"):
        w, h = h, w
    x, y = inst["x"] / 1000, inst["y"] / 1000
    return x, y, x + w, y + h


def block_cells():
    """{block: set of instance names}, plus "clock tree" for logic cells in no cone."""
    ex, lef, inst, pins, direction, driver, port_net = cone.design()
    blocks = json.load(open(cone.BLOCKS))
    cells = collections.defaultdict(set)
    for d in blocks["flops"].values():
        cells[d["block"]].add(d["instance"])
        cells[d["block"]] |= cone.cone_sources(d["D_net"])[0]
    for port, blk in blocks["outputs"].items():
        cells[blk] |= cone.cone_sources(port_net[port])[0]
    placed = set().union(*cells.values())
    cells["clock tree"] = set(inst) - placed
    flops = collections.Counter(d["block"] for d in blocks["flops"].values())
    return cells, flops


def figure():
    ex, lef, inst, *_ = cone.design()
    die = Die(200.0, 300.0, {i["name"]: _rect(i, lef) for i in ex.logic_instances()})
    cells, flops = block_cells()
    panels = []
    for k in ORDER:
        sub = f"{flops[k]} flops, {len(cells[k]) - flops[k]} gates"
        panels.append((k, sub, sorted(cells[k])))
    panels.append(("clock tree", f"{len(cells['clock tree'])} buffers", sorted(cells["clock tree"])))
    label = ("The puzzle's 200 by 300 um die drawn seven times, each panel highlighting one recovered "
             "block's cells: " + "; ".join(f"{t}, {s}" for t, s, _n in panels))
    return svg_panels(die, panels, cols=4, panel_w=150, label=label), panels


def main(argv=None):
    out = (argv or sys.argv[1:] or ["docs/figures/puzzle_blocks.svg"])[0]
    svg, panels = figure()
    with open(out, "w") as f:
        f.write(svg)
    for t, s, _n in panels:
        print(f"{t:12s} {s}")
    print(f"wrote {out} ({len(svg) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
