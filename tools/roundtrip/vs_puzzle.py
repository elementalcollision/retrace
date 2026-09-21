"""S4 round trip: our hardened layout of the recovered RTL next to Jane Street's puzzle.gds.

    .venv/bin/python -m tools.roundtrip.vs_puzzle RUN_DIR [--json OUT | --json -] [--svg OUT]

RUN_DIR is a LibreLane run of rtl_recovered/ made by tools/roundtrip/puzzle/harden.sh
(e.g. out/roundtrip/puzzle_run/upstreamlike). The comparison is printed as text; the same
numbers go to JSON (default out/roundtrip/vs_puzzle/<run>.json; `--json -` prints the JSON
instead of the text). `--svg` draws docs/figures/roundtrip_blocks.svg: two rows of seven
panels (puzzle, ours), one per recovered block plus the clock tree, at the same scale.

Sources, chosen so that each side is measured the same way wherever possible:
  puzzle  upstream/puzzle.gds through tools.retrace.extract (cone.design()): instances,
          connectivity; its blocks are tools.viz.puzzle.block_cells() (flops plus their
          logic cones cut at flops; 14 gates sit in two or more cones).
  ours    final/def (instance names carry the kept hierarchy, u_<block>/...; the 92 flops
          are top-level, `_NN_`, mapped to their register by the Q net name and to the
          puzzle's fNN through the `reg name; // fNN` comments of
          rtl_recovered/puzzle_recovered.v), cross-checked against the extraction of
          final/klayout_gds (same master, x, y, orientation for every instance).
  both    geometry (die boundary 235/4, pin labels and pin shapes, PDN straps and rails,
          wire paths, via cells) read from the two KLayout-streamed GDS files by the same
          code; routing = top-cell paths, minus the PDN (met1 0.48 followpin rails, met3
          0.33 DRCFILL patches, met4/met5 2.0 straps); vias = references to VIA_* cells,
          PDN when pdngen generated the cell (VIA_via<a>_<b>_...). Top-level polygons are
          not counted as wire: on both sides they are DEF RECT patches and pin squares, and
          on the puzzle also Jane Street's post-flow logo (0.3 um met2 squares); the
          INTERNAL_3/7 strip is a non-VIA reference. Both are listed under "not_counted".

What is and is not the same: the floorplan (die, rows, taps, endcaps, pins, PDN) is
identical. Placement is the one flow setting the round-trip config does not reproduce (Part
1 open question: the puzzle's placement mechanism is unknown), but it is not the only
difference in the layout. The cell count and mix differ too: logic 492 vs 604 in the
upstream-like run, a synthesis/RTL difference and not a placement one, and antenna diodes 0
vs 10 (flow-inserted; our run's antenna check found no violation). Routing, and which
registers share a CTS leaf buffer, differ as a consequence. The verdict of section
"placement" is computed from the run, so the counts there are the run's own.
Section "placement" says how far off placement is:
per-flop displacement against the puzzle's matching flop, per-block centroids, bounding
boxes and spread, the overlap of each block's footprint on a 10 x 10.88 um grid, and
Part 1's cluster-density statistic (bin density of logic+CTS+diode area in 10 x 10.88 um
bins, i.e. 10 um by four rows; Part 1 measured the puzzle's p10 at 0.91).

The flop correspondence (our register -> fNN through the `// fNN` comments of
rtl_recovered/puzzle_recovered.v) is taken as given here and not checked flop by flop: a
swapped pair of tags passes every check of this module. tools.roundtrip.loop checks it: its
step 4 proof asserts each of our flops equal to the puzzle's fNN from rtl_recovered/
blocks.json, so a wrong tag fails that proof (test/test_roundtrip.py runs it).

Leaf groups: which registers share a CTS leaf buffer is compared with what chance gives. If
our flops were dealt at random into leaves of our sizes, a puzzle pair that shares a leaf
would share one of ours with probability sum_leaves C(s, 2) / C(n, 2), so the expected number
of shared pairs is that times the puzzle's pair count (reported as expected_by_chance). The
same null model is also simulated (chance_shuffle): our registers shuffled into leaves of our
leaf sizes LEAF_SHUFFLES times with the fixed seed LEAF_SEED, reporting the mean, the 99th
percentile and the maximum count of shared puzzle pairs, and how many shuffles reach the
observed count.
"""

import argparse
import collections
import glob
import html
import itertools
import json
import math
import os
import random
import re
import statistics
import sys

import gdstk

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PUZZLE_GDS = "upstream/puzzle.gds"
LEF_PATH = "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"
TOP_RTL = "rtl_recovered/puzzle_recovered.v"
BLOCKS_JSON = "rtl_recovered/blocks.json"
FIGURE = "docs/figures/roundtrip_blocks.svg"
OUT_DIR = "out/roundtrip/vs_puzzle"
PREFIX = "sky130_fd_sc_hd__"
BLOCKS = ["counter", "array", "left_top", "left_bottom", "check", "outgen"]  # tools.viz.puzzle.ORDER
CLOCK = "clock tree"
CLASSES = ("logic", "flop", "clock", "diode", "tap", "endcap", "fill")
INPUT_PORTS = ("clk", "rst_n", "enable", "I")
FLOP = re.compile(r"(df|sdf|edf|dl[a-z]*tp|dlx)")
# sky130 GDS layers (drawing 20, pin 16, label 5, cut 44)
METAL = {67: "li1", 68: "met1", 69: "met2", 70: "met3", 71: "met4", 72: "met5"}
CUT = {67: "mcon (li1-met1)", 68: "via (met1-met2)", 69: "via2 (met2-met3)", 70: "via3 (met3-met4)",
       71: "via4 (met4-met5)"}
BOUNDARY = (235, 4)
PDN_VIA = re.compile(r"VIA_via\d_\d_")
# part 1's cluster-density bins (out/roundtrip/forensics/bin_density.py): 10 um wide from
# x = 0, four rows (10.88 um) high from the first row at y = 10.88 um
BIN_W, BIN_H, ROW0 = 10000, 10880, 10880
DENSE = 0.75  # "dense bin" threshold for the share-of-area statistic
LEAF_SHUFFLES, LEAF_SEED = 10000, 2026  # the leaf-group chance baseline (leaf_pair_chance)


def short(master):
    return master[len(PREFIX):] if master.startswith(PREFIX) else master


def classify(name, master):
    """Instance class; `name` None for a GDS reference (master only). Same rules as
    tools/roundtrip/puzzle/summarize.py: by DEF name where there is one, by master for
    the puzzle, where every decap_3 is an endcap and every clkbuf a CTS cell (both
    checked below: the endcaps against ours, the clkbufs against the cone analysis)."""
    base = short(master)
    if name is not None:
        if name.startswith("PHY_EDGE_ROW_"):
            return "endcap"
        if name.startswith("TAP_TAPCELL_ROW_"):
            return "tap"
        if name.startswith("FILLER_"):
            return "fill"
        if base.startswith("diode_"):
            return "diode"
        if name.startswith(("clkbuf_", "clkload", "clkinv_")) and base.startswith("clk"):
            return "clock"
    else:
        if base.startswith("decap_"):
            return "endcap"
        if base.startswith("tapvpwrvgnd"):
            return "tap"
        if base.startswith("fill_"):
            return "fill"
        if base.startswith("diode_"):
            return "diode"
        if base.startswith("clkbuf_"):
            return "clock"
    if FLOP.match(base):
        return "flop"
    return "logic"


def r2(v, nd=2):
    return None if v is None else round(v, nd)


# ---- GDS geometry, the same reader for both sides ---------------------------------------


def gds_geometry(path):
    lib = gdstk.read_gds(path)
    tops = lib.top_level()
    if len(tops) != 1:
        raise ValueError(f"{path}: expected one top cell, got {[c.name for c in tops]}")
    top = tops[0]
    g = {"top": top.name}
    b = [p.bounding_box() for p in top.polygons if (p.layer, p.datatype) == BOUNDARY]
    g["die_um"] = [round(v, 3) for v in (*b[0][0], *b[0][1])] if b else None
    g["labels"] = sorted((lb.text, METAL.get(lb.layer, str(lb.layer)), round(lb.origin[0], 3), round(lb.origin[1], 3))
                         for lb in top.labels)
    g["pin_shapes"] = sorted(tuple(round(v, 3) for v in (*p.bounding_box()[0], *p.bounding_box()[1])) + (METAL[p.layer],)
                             for p in top.polygons if p.datatype == 16 and p.layer in METAL and p.layer <= 70)
    straps, rails, drcfill = set(), set(), set()
    wl, nseg = collections.Counter(), collections.Counter()
    for p in top.paths:
        layer = p.layers[0]
        if p.datatypes[0] != 20 or layer not in METAL:
            continue
        w = round(float(p.widths().ravel()[0]), 3)
        sp = p.spine()
        key = (METAL[layer], w) + tuple(round(float(v), 3) for v in sp.ravel())
        if layer in (71, 72) and w == 2.0:
            straps.add(key)
        elif layer == 68 and w == 0.48:
            rails.add(key)
        elif layer == 70 and w == 0.33:
            drcfill.add(key)
        else:
            wl[METAL[layer]] += sum(math.dist(a, b) for a, b in zip(sp[:-1], sp[1:]))
            nseg[METAL[layer]] += 1
    g["pdn_straps"], g["pdn_rails"], g["pdn_drcfill"] = straps, rails, drcfill
    g["wirelength_um"] = {k: round(v, 2) for k, v in sorted(wl.items())}
    g["wire_paths"] = dict(sorted(nseg.items()))
    cut_of = {}
    for c in lib.cells:
        if c.name.startswith("VIA_"):
            cuts = {p.layer for p in c.polygons if p.datatype == 44}
            cut_of[c.name] = CUT[min(cuts)] if cuts else "?"
    vias = {"signal": collections.Counter(), "pdn": collections.Counter()}
    pdn_via_pos, other_refs = set(), collections.Counter()
    for r in top.references:
        n = r.cell.name
        if n.startswith("VIA_"):
            kind = "pdn" if PDN_VIA.match(n) else "signal"
            vias[kind][cut_of[n]] += 1
            if kind == "pdn":
                pdn_via_pos.add((n, round(r.origin[0], 3), round(r.origin[1], 3)))
        elif not n.startswith(PREFIX):
            other_refs[n] += 1
    g["vias"] = {k: dict(sorted(v.items())) for k, v in vias.items()}
    g["pdn_via_positions"] = pdn_via_pos
    g["other_references"] = dict(other_refs)
    # top-level metal polygons that are not PDN strap drawing: DEF RECT routing patches and
    # pin squares on both sides, plus whatever was added after the flow (Jane Street's logo)
    polys = collections.defaultdict(list)
    for p in top.polygons:
        (x0, y0), (x1, y1) = p.bounding_box()
        if p.datatype != 20 or p.layer not in METAL or max(x1 - x0, y1 - y0) > 100:
            continue
        polys[METAL[p.layer]].append((x0, y0, x1, y1))
    g["top_polygons"] = {
        l: {"count": len(v), "sizes_um": [[f"{w:g} x {h:g}", n] for (w, h), n in collections.Counter(
            (round(r[2] - r[0], 3), round(r[3] - r[1], 3)) for r in v).most_common(3)],
            "bbox_um": [round(min(r[0] for r in v), 2), round(min(r[1] for r in v), 2),
                        round(max(r[2] for r in v), 2), round(max(r[3] for r in v), 2)]}
        for l, v in sorted(polys.items())}
    return g


def routing_nets_per_layer(ex):
    """Signal nets with at least one routed path on each metal (extraction route shapes)."""
    root_net = {m["root"]: m for m in ex.nets}
    used = collections.defaultdict(set)
    for sid, (layer, _dt, _geom, owner) in enumerate(ex.shapes):
        if owner[0] != "route":
            continue
        m = root_net.get(ex.uf.find(sid))
        if m is None or m["supply"]:
            continue
        used[METAL.get(layer, str(layer))].add(m["name"])
    return {k: len(v) for k, v in sorted(used.items())}


# ---- DEF (ours) -------------------------------------------------------------------------

_KEYWORDS = {"TAPER", "TAPERRULE", "STYLE", "MASK", "RECT", "VIRTUAL"}


def def_extras(path):
    """DIEAREA, ROWs, PINS and the routed wirelength/vias per layer from the NETS section."""
    t = open(path).read()
    out = {}
    m = re.search(r"DIEAREA \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)", t)
    out["die_um"] = [int(v) / 1000 for v in m.groups()]
    out["rows"] = [(n, site, int(x), int(y), o, int(nx), int(sx)) for n, site, x, y, o, nx, _ny, sx, _sy in
                   re.findall(r"^ROW (\S+) (\S+) (-?\d+) (-?\d+) (\S+) DO (\d+) BY (\d+) STEP (\d+) (\d+)", t, re.M)]
    pins = re.search(r"^PINS \d+ ;(.*?)^END PINS", t, re.M | re.S).group(1)
    out["pins"] = {}
    for blk in re.split(r"\n\s+- ", "\n" + pins):
        pm = re.match(r"\s*(\S+) \+ NET", blk)
        if not pm:
            continue
        rects = re.findall(r"LAYER (\S+) \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)", blk)
        pl = re.search(r"(?:PLACED|FIXED) \( (-?\d+) (-?\d+) \) (\S+)", blk)
        out["pins"][pm.group(1)] = {"layers": sorted({r[0] for r in rects}), "shapes": len(rects),
                                    "placed_um": [int(pl.group(1)) / 1000, int(pl.group(2)) / 1000] if pl else None}
    nets = re.search(r"^NETS \d+ ;(.*?)^END NETS", t, re.M | re.S).group(1)
    wl, vias, after_via = collections.Counter(), collections.Counter(), 0
    for body in re.split(r"^\s*- ", nets, flags=re.M)[1:]:
        for stmt in re.split(r"\b(?:ROUTED|NEW)\b", body)[1:]:
            toks = stmt.replace(";", " ").split()
            layer, k, prev, seen_via = toks[0], 1, None, False
            while k < len(toks) and toks[k] != "+":
                tk = toks[k]
                if tk == "(":
                    j = toks.index(")", k)
                    x, y = toks[k + 1], toks[k + 2]
                    x = prev[0] if x == "*" else int(x)
                    y = prev[1] if y == "*" else int(y)
                    if prev is not None:
                        wl[layer] += abs(x - prev[0]) + abs(y - prev[1])
                        after_via += seen_via
                    prev, k = (x, y), j + 1
                elif tk == "RECT":
                    k = toks.index(")", k) + 1
                elif tk in ("TAPERRULE", "STYLE", "MASK"):
                    k += 2
                elif tk == "VIRTUAL":
                    k = toks.index(")", k) + 1
                elif tk == "TAPER":
                    k += 1
                else:
                    vias[tk] += 1
                    seen_via = True
                    k += 1
    out["wirelength_um"] = {k: round(v / 1000, 2) for k, v in sorted(wl.items()) if v}
    out["vias"] = dict(sorted(vias.items()))
    out["segments_after_a_via"] = after_via
    return out


# ---- the two designs --------------------------------------------------------------------


class Design:
    """Instances {name: (master, x, y, orient)} (DBU lower-left), signal pin -> net,
    port -> net, class per instance, block membership, GDS geometry."""

    def __init__(self, label, inst, pin_net, ports, named, geom):
        self.label = label
        self.inst = inst
        self.pin_net = pin_net
        self.ports = ports
        self.cls = {n: classify(n if named else None, v[0]) for n, v in inst.items()}
        self.nets = collections.defaultdict(list)
        for ip, n in pin_net.items():
            self.nets[n].append(ip)
        self.geom = geom
        self.blocks = {}  # {block: set of instance names}, filled by the loaders

    def of(self, *classes):
        return [n for n, c in self.cls.items() if c in classes]


def load_puzzle(lef):
    from tools.analysis import cone
    from tools.retrace.extract import SUPPLY_PINS
    from tools.viz.puzzle import block_cells

    ex, _lef, _inst, _pins, _direction, _driver, port_net = cone.design()
    inst = {i["name"]: (i["master"], i["x"], i["y"], i["orient"]) for i in ex.instances}
    pin_net = {ip: n for ip, n in ex.net_of.items() if ip[1] not in SUPPLY_PINS}
    ports = {p: n for p, n in port_net.items()}
    P = Design("puzzle", inst, pin_net, ports, named=False, geom=gds_geometry(PUZZLE_GDS))
    cells, _flops = block_cells()
    P.blocks = {b: set(cells[b]) for b in BLOCKS + [CLOCK]}
    blocks = json.load(open(BLOCKS_JSON))
    P.fid = {v["instance"]: k for k, v in blocks["flops"].items()}  # instance -> fNN
    P.ex = ex
    return P


def load_ours(run, lef):
    from tools.retrace.defparse import read_def
    from tools.retrace.extract import Extraction

    def_path = one(run, "final/def/*.def")
    gds_path = one(run, "final/klayout_gds/*.gds") or one(run, "final/gds/*.gds")
    if not def_path or not gds_path:
        raise SystemExit(f"{run}: no final/def/*.def or final/klayout_gds/*.gds (not a finished LibreLane run?)")
    d = read_def(def_path)
    inst = dict(d["components"])
    pin_net, ports = {}, {}
    for net, conns in d["nets"].items():
        for i, p in conns:
            if i == "PIN":
                ports[p] = net
            else:
                pin_net[(i, p)] = net
    O = Design("ours", inst, pin_net, ports, named=True, geom=gds_geometry(gds_path))
    O.def_path, O.gds_path = def_path, gds_path
    O.def_extras = def_extras(def_path)
    # flops -> register -> fNN -> block; gates by their u_<block>/ prefix; CTS cells
    regs = dict(re.findall(r"^\s*reg\s+(\w+);\s*//\s*(f\d\d)\b", open(TOP_RTL).read(), re.M))
    blocks = json.load(open(BLOCKS_JSON))
    O.fid, O.blocks = {}, {b: set() for b in BLOCKS + [CLOCK]}
    unmapped = []
    for n, c in O.cls.items():
        if c == "flop":
            q = pin_net.get((n, "Q"))
            if q in regs:
                O.fid[n] = regs[q]
                O.blocks[blocks["flops"][regs[q]]["block"]].add(n)
            else:
                unmapped.append(n)
        elif c == "logic":
            m = re.match(r"u_(\w+?)/", n)
            if m and m.group(1) in BLOCKS:
                O.blocks[m.group(1)].add(n)
            else:
                unmapped.append(n)
        elif c == "clock":
            O.blocks[CLOCK].add(n)
    O.unmapped = unmapped
    ex = Extraction(gds_path, lef)
    O.ex = ex
    O.gds_inst = collections.Counter((i["master"], i["x"], i["y"], i["orient"]) for i in ex.instances)
    return O


def one(run, pattern):
    hits = sorted(glob.glob(os.path.join(run, pattern)))
    return hits[0] if hits else None


def rel(p):
    p = os.path.abspath(p)
    return os.path.relpath(p, ROOT) if p.startswith(ROOT + os.sep) else p


# ---- cones (the puzzle's block method, run on either design) -----------------------------


def cones(D, lef):
    """{block: cells in the logic cones behind its flops' D pins and its output ports},
    plus CLOCK: non-flop cells in no cone. Same walk as tools.analysis.cone.cone_sources."""
    blocks = json.load(open(BLOCKS_JSON))
    direction = lambda i, p: lef[D.inst[i][0]]["pins"][p]["direction"]
    driver = {}
    for (i, p), n in D.pin_net.items():
        if direction(i, p) == "OUTPUT":
            driver[n] = i
    stop = {D.ports[p] for p in INPUT_PORTS if p in D.ports}
    by_inst = collections.defaultdict(dict)
    for (i, p), n in D.pin_net.items():
        by_inst[i][p] = n

    def walk(net):
        seen, stack, cells = set(), [net], set()
        while stack:
            n = stack.pop()
            if n in seen or n in stop:
                continue
            seen.add(n)
            i = driver[n]
            if D.cls[i] == "flop":
                continue
            cells.add(i)
            stack.extend(nn for p, nn in by_inst[i].items() if direction(i, p) == "INPUT")
        return cells

    fl_block = {}
    for n, f in D.fid.items():
        fl_block[n] = blocks["flops"][f]["block"]
    out = {b: set() for b in BLOCKS}
    for n, b in fl_block.items():
        out[b].add(n)
        out[b] |= walk(by_inst[n]["D"])
    for port, b in blocks["outputs"].items():
        out[b] |= walk(D.ports[port])
    placed = set().union(*out.values())
    out[CLOCK] = {n for n in D.of("logic", "clock") if n not in placed}
    return out


# ---- sections ---------------------------------------------------------------------------


def floorplan(P, O, lef):
    res = {}
    res["die_um"] = {"puzzle_gds_boundary": P.geom["die_um"], "ours_def": O.def_extras["die_um"],
                     "ours_gds_boundary": O.geom["die_um"]}
    res["die_um"]["identical"] = P.geom["die_um"] == O.geom["die_um"] == O.def_extras["die_um"]
    # rows: ours from DEF ROW statements; the puzzle's inferred from its tap and endcap cells
    rows = O.def_extras["rows"]
    ys = sorted(r[3] for r in rows)
    ours_rows = {"count": len(rows), "x0_um": rows[0][2] / 1000, "y0_um": ys[0] / 1000,
                 "pitch_um": sorted({(b - a) / 1000 for a, b in zip(ys, ys[1:])}),
                 "sites": sorted({r[5] for r in rows}), "site_step_um": sorted({r[6] / 1000 for r in rows}),
                 "orient_first_rows": [r[4] for r in sorted(rows, key=lambda r: r[3])[:4]]}
    phys = [v for n, v in P.inst.items() if P.cls[n] in ("tap", "endcap")]
    pys = sorted({v[2] for v in phys})
    ends = [v for n, v in P.inst.items() if P.cls[n] == "endcap"]
    x0 = min(v[1] for v in ends)
    x1 = max(v[1] + round(lef[v[0]]["size"][0] * 1000) for v in ends)
    first = {}
    for v in sorted(ends, key=lambda v: (v[2], v[1])):
        first.setdefault(v[2], v[3])
    puz_rows = {"count": len(pys), "x0_um": x0 / 1000, "y0_um": pys[0] / 1000,
                "pitch_um": sorted({(b - a) / 1000 for a, b in zip(pys, pys[1:])}),
                "sites": [round((x1 - x0) / 460)], "site_step_um": [0.46],
                "orient_first_rows": [first[y] for y in pys[:4]]}
    res["rows"] = {"puzzle_inferred_from_taps_endcaps": puz_rows, "ours_def": ours_rows,
                   "identical": {k: puz_rows[k] == ours_rows[k] for k in puz_rows}}
    # taps and endcaps: (master, x, y, orient)
    for c in ("tap", "endcap"):
        a = collections.Counter(P.inst[n] for n in P.of(c))
        b = collections.Counter(O.inst[n] for n in O.of(c))
        res[c + "s"] = {"puzzle": sum(a.values()), "ours": sum(b.values()), "identical_master_x_y_orient": sum((a & b).values()),
                        "only_puzzle": sum((a - b).values()), "only_ours": sum((b - a).values())}
    # pins: GDS labels and pin shapes on both sides (same reader), DEF placement for ours
    lp = {(t, l): (x, y) for t, l, x, y in P.geom["labels"]}
    lo = {(t, l): (x, y) for t, l, x, y in O.geom["labels"]}
    sig = sorted(k for k in lp if k[0] not in ("VPWR", "VGND"))
    pins = []
    for k in sig:
        dp = O.def_extras["pins"].get(k[0], {})
        pins.append({"pin": k[0], "layer": k[1], "puzzle_label_um": lp[k], "ours_label_um": lo.get(k),
                     "ours_def_placed_um": dp.get("placed_um"), "ours_def_layers": dp.get("layers"),
                     "same": lo.get(k) == lp[k] and dp.get("placed_um") == list(lp[k]) and dp.get("layers") == [k[1]]})
    res["pins"] = {"signal": pins, "identical": sum(p["same"] for p in pins), "total": len(pins),
                   "pin_shapes_identical": P.geom["pin_shapes"] == O.geom["pin_shapes"],
                   "pin_shape_um": "0.6 x 0.6 um met3 at the die edge (both)" if P.geom["pin_shapes"] == O.geom["pin_shapes"] else None,
                   "power_labels_puzzle": [x for x in P.geom["labels"] if x[0] in ("VPWR", "VGND")],
                   "power_labels_ours": [x for x in O.geom["labels"] if x[0] in ("VPWR", "VGND")],
                   "power_labels_identical": [x for x in P.geom["labels"] if x[0] in ("VPWR", "VGND")]
                   == [x for x in O.geom["labels"] if x[0] in ("VPWR", "VGND")],
                   "ours_def_power_pin_shapes": {p: O.def_extras["pins"][p]["shapes"] for p in ("VPWR", "VGND")
                                                 if p in O.def_extras["pins"]}}
    # PDN
    pdn = {}
    for key, what in (("pdn_straps", "met4/met5 2 um straps"), ("pdn_rails", "met1 0.48 um followpin rails"),
                      ("pdn_drcfill", "met3 0.33 um DRCFILL patches"), ("pdn_via_positions", "via cells (name + position)")):
        a, b = P.geom[key], O.geom[key]
        pdn[key[4:]] = {"what": what, "puzzle": len(a), "ours": len(b), "identical": len(a & b)}
    pdn["straps_by_layer"] = dict(collections.Counter(k[0] for k in P.geom["pdn_straps"]))
    res["pdn"] = pdn
    return res


def area_of(masters, areas):
    return round(sum(areas[m] for m in masters), 2)


def cells_section(P, O, areas, lef):
    res = {"by_class": {}}
    for c in CLASSES:
        a, b = P.of(c), O.of(c)
        res["by_class"][c] = {"puzzle": len(a), "puzzle_area_um2": area_of((P.inst[n][0] for n in a), areas),
                              "ours": len(b), "ours_area_um2": area_of((O.inst[n][0] for n in b), areas)}
    res["total_instances"] = {"puzzle": len(P.inst), "ours": len(O.inst)}
    # logic per master (liberty area)
    hp = collections.Counter(short(P.inst[n][0]) for n in P.of("logic"))
    ho = collections.Counter(short(O.inst[n][0]) for n in O.of("logic"))
    rows = []
    for m in sorted(set(hp) | set(ho)):
        a = areas[PREFIX + m]
        rows.append({"master": m, "area_each_um2": round(a, 4), "puzzle": hp[m], "ours": ho[m], "delta": ho[m] - hp[m],
                     "delta_area_um2": round((ho[m] - hp[m]) * a, 2)})
    res["logic_masters"] = rows
    res["logic_masters_summary"] = {
        "masters_puzzle": len(hp), "masters_ours": len(ho), "masters_both": len(set(hp) & set(ho)),
        "cells_in_common_histogram": sum((hp & ho).values()),
        "l1_distance": sum(abs(hp[m] - ho[m]) for m in set(hp) | set(ho))}
    fam = lambda h, rx: sum(n for m, n in h.items() if re.match(rx, m))
    res["logic_detail"] = {k: {"puzzle": fam(hp, rx), "ours": fam(ho, rx)} for k, rx in (
        ("tie conb_1", r"conb_"), ("buf", r"buf_"), ("inv", r"(clk)?inv_"), ("xor/xnor", r"x(n)?or"),
        ("mux2", r"mux2"), ("nand/nor", r"n(and|or)"))}
    res["flops"] = {"puzzle": dict(collections.Counter(short(P.inst[n][0]) for n in P.of("flop"))),
                    "ours": dict(collections.Counter(short(O.inst[n][0]) for n in O.of("flop")))}
    same_master = sum(1 for n, f in O.fid.items() if short(O.inst[n][0]) == short(P.inst[_puz_flop(P, f)][0]))
    res["flops"]["same_master_per_register"] = same_master
    res["clock_tree"] = {"puzzle": clock_tree(P, lef), "ours": clock_tree(O, lef)}
    # which registers share a leaf buffer (CTS clusters flops by placement)
    gp, go = set(P.leaf_groups), set(O.leaf_groups)
    pairs = lambda gs: {frozenset(q) for g in gs for q in itertools.combinations(sorted(g), 2)}
    pp, po = pairs(gp), pairs(go)
    n_ours = sum(len(g) for g in O.leaf_groups)
    p_share = (sum(math.comb(len(g), 2) for g in O.leaf_groups) / math.comb(n_ours, 2)) if n_ours > 1 else 0.0
    chance = len(pp) * p_share
    res["clock_tree"]["leaf_groups"] = {
        "identical_groups": len(gp & go), "groups": len(gp),
        "flop_pairs_sharing_a_leaf_puzzle": len(pp), "of_which_share_a_leaf_in_ours": len(pp & po),
        "expected_by_chance": r2(chance, 1), "ratio_to_chance": r2(len(pp & po) / chance, 1) if chance else None,
        "chance_model": ("our flops dealt at random into leaves of our sizes: a puzzle pair shares one of our leaves "
                         f"with probability sum C(s,2) / C({n_ours},2) = {p_share:.4f}"),
        "chance_shuffle": leaf_pair_chance(pp, O.leaf_groups, len(pp & po))}
    # antenna diodes
    dio = {}
    for D in (P, O):
        nets = collections.Counter(D.pin_net.get((n, "DIODE")) for n in D.of("diode"))
        dio[D.label] = {"count": len(D.of("diode")), "nets": len(nets), "per_net": sorted(nets.values(), reverse=True),
                        "positions_um": sorted((D.inst[n][1] / 1000, D.inst[n][2] / 1000) for n in D.of("diode"))}
    res["diodes"] = dio
    fill = {D.label: dict(collections.Counter(short(D.inst[n][0]) for n in D.of("fill"))) for D in (P, O)}
    res["fill"] = fill
    return res


def leaf_pair_chance(pairs, groups, observed, n=LEAF_SHUFFLES, seed=LEAF_SEED):
    """The leaf-group null model, simulated: the registers of `groups` (our leaves) shuffled
    into leaves of the same sizes `n` times (random.Random(seed), so the result is fixed),
    counting each time how many of `pairs` (the puzzle's same-leaf register pairs) land in
    one leaf. Mean, 99th percentile (nearest rank), max, and the shuffles that reach
    `observed` (the count in our layout)."""
    regs = sorted(set().union(*groups))
    sizes = [len(g) for g in sorted(groups, key=lambda g: sorted(g))]
    pairs = sorted(tuple(sorted(p)) for p in pairs)
    rng = random.Random(seed)
    counts = []
    for _ in range(n):
        rng.shuffle(regs)
        leaf, k = {}, 0
        for li, s in enumerate(sizes):
            for r in regs[k:k + s]:
                leaf[r] = li
            k += s
        counts.append(sum(1 for a, b in pairs if a in leaf and leaf.get(a) == leaf.get(b)))
    counts.sort()
    return {"shuffles": n, "seed": seed, "mean": r2(statistics.mean(counts), 2),
            "p99": counts[math.ceil(0.99 * n) - 1], "max": counts[-1],
            "shuffles_at_or_above_observed": sum(c >= observed for c in counts),
            "what": ("our registers shuffled into leaves of our leaf sizes; count of the puzzle's same-leaf pairs "
                     "that share a leaf")}


def _puz_flop(P, f):
    return next(i for i, k in P.fid.items() if k == f)


def clock_tree(D, lef):
    """Root, leaves, dummy loads and flops per leaf, walking from the clk port."""
    out_pin = lambda i: next(p for p, v in lef[D.inst[i][0]]["pins"].items() if v["direction"] == "OUTPUT")
    sinks = lambda net: [ip for ip in D.nets.get(net, []) if lef[D.inst[ip[0]][0]]["pins"][ip[1]]["direction"] != "OUTPUT"]
    clk = D.ports["clk"]
    first = sinks(clk)
    roots = [i for i, _p in first if D.cls[i] == "clock"]
    res = {"clk_port_fanout": dict(collections.Counter(short(D.inst[i][0]) for i, _p in first))}
    if len(roots) != 1:
        res["error"] = f"{len(roots)} clock cells on the clk port net"
        return res
    root = roots[0]
    rnet = D.pin_net.get((root, out_pin(root)))
    level1 = sinks(rnet)
    res["root"] = {"master": short(D.inst[root][0]), "at_um": [D.inst[root][1] / 1000, D.inst[root][2] / 1000],
                   "fanout": dict(collections.Counter(short(D.inst[i][0]) for i, _p in level1))}
    leaves, dummies, flops_per_leaf, spans, loaded_leaves = [], [], [], [], 0
    D.leaf_groups = []  # the registers (fNN) under each leaf buffer
    for i, _p in level1:
        if D.cls[i] != "clock":
            continue
        net = D.pin_net.get((i, out_pin(i)))
        s = sinks(net) if net else []
        if not s:
            dummies.append(i)
            continue
        leaves.append(i)
        fl = [j for j, _q in s if D.cls[j] == "flop"]
        dl = [j for j, _q in s if D.cls[j] == "clock" and not sinks(D.pin_net.get((j, out_pin(j))))]
        loaded_leaves += bool(dl)
        dummies.extend(dl)
        flops_per_leaf.append(len(fl))
        D.leaf_groups.append(frozenset(D.fid.get(j, j) for j in fl))
        xs = [D.inst[j][1] / 1000 for j in fl] + [D.inst[i][1] / 1000]
        ys = [D.inst[j][2] / 1000 for j in fl] + [D.inst[i][2] / 1000]
        spans.append((max(xs) - min(xs)) + (max(ys) - min(ys)))
        other = [j for j, _q in s if D.cls[j] not in ("flop", "clock")]
        if other:
            res.setdefault("leaf_other_sinks", []).extend(other)
    res["leaves"] = {"count": len(leaves), "masters": dict(collections.Counter(short(D.inst[i][0]) for i in leaves)),
                     "flops_per_leaf": sorted(flops_per_leaf), "flops_total": sum(flops_per_leaf),
                     "mean_half_perimeter_um": r2(statistics.mean(spans)) if spans else None,
                     "leaves_with_a_dummy_load": loaded_leaves}
    res["dummy_loads"] = {"count": len(dummies), "masters": dict(collections.Counter(short(D.inst[i][0]) for i in dummies))}
    res["levels"] = 2 if leaves else 1
    res["clock_cells"] = len(D.of("clock"))
    return res


def rect_um(D, lef, n):
    m, x, y, o = D.inst[n]
    w, h = lef[m]["size"]
    if o in ("E", "W", "FE", "FW"):
        w, h = h, w
    return x / 1000, y / 1000, x / 1000 + w, y / 1000 + h


def blocks_section(P, O, areas, lef):
    cp, co = cones(P, lef), cones(O, lef)
    res = {"method": {
        "puzzle": "tools.viz.puzzle.block_cells(): flops + logic cones cut at flops; shared gates counted in each block",
        "ours": "kept hierarchy: gates named u_<block>/..., flops by register name -> fNN -> rtl_recovered/blocks.json"}}
    res["check_cone_walk_reproduces_block_cells_on_puzzle"] = all(cp[b] == P.blocks[b] for b in BLOCKS + [CLOCK])
    agree = {b: {"hierarchy": len(O.blocks[b]), "cone": len(co[b]), "both": len(O.blocks[b] & co[b])} for b in BLOCKS + [CLOCK]}
    res["ours_hierarchy_vs_cones"] = {"identical": all(O.blocks[b] == co[b] for b in BLOCKS + [CLOCK]), "per_block": agree}
    owners = collections.Counter(n for b in BLOCKS for n in P.blocks[b])
    rows = []
    for b in BLOCKS + [CLOCK]:
        row = {"block": b}
        for D in (P, O):
            names = D.blocks[b]
            fl = [n for n in names if D.cls[n] == "flop"]
            ga = [n for n in names if D.cls[n] != "flop"]
            row[D.label] = {"flops": len(fl), "gates": len(ga), "cells": len(names),
                            "gate_area_um2": area_of((D.inst[n][0] for n in ga), areas),
                            "flop_area_um2": area_of((D.inst[n][0] for n in fl), areas),
                            "area_um2": area_of((D.inst[n][0] for n in names), areas)}
        row["puzzle"]["shared_gates"] = sum(1 for n in P.blocks[b] if owners[n] > 1) if b != CLOCK else 0
        row["gate_delta"] = row["ours"]["gates"] - row["puzzle"]["gates"]
        row["gate_area_delta_um2"] = round(row["ours"]["gate_area_um2"] - row["puzzle"]["gate_area_um2"], 2)
        rows.append(row)
    res["per_block"] = rows
    res["puzzle_shared_gates"] = sum(1 for n, k in owners.items() if k > 1)
    res["unmapped_ours"] = O.unmapped
    return res


def centroid(D, lef, areas, names):
    """Area-weighted centroid of the cell centres, in um, unrounded."""
    rs = [rect_um(D, lef, n) for n in names]
    a = [areas[D.inst[n][0]] for n in names]
    A = sum(a)
    ctr = [((r[0] + r[2]) / 2, (r[1] + r[3]) / 2) for r in rs]
    return sum(ai * c[0] for ai, c in zip(a, ctr)) / A, sum(ai * c[1] for ai, c in zip(a, ctr)) / A


def centroid_offset(P, O, lef, areas, pn, on):
    """Distance between two centroids, from the unrounded values (then rounded)."""
    return r2(math.dist(centroid(P, lef, areas, pn), centroid(O, lef, areas, on)), 1)


def _stats(D, lef, areas, names):
    """Area-weighted centroid, rms and 90th-percentile radius of cell centres about it,
    bounding box of the cell rectangles, and cell area / bbox area."""
    rs = [rect_um(D, lef, n) for n in names]
    a = [areas[D.inst[n][0]] for n in names]
    A = sum(a)
    ctr = [((r[0] + r[2]) / 2, (r[1] + r[3]) / 2) for r in rs]
    cx, cy = centroid(D, lef, areas, names)
    dist = [math.dist(c, (cx, cy)) for c in ctr]
    rg = math.sqrt(sum(ai * d * d for ai, d in zip(a, dist)) / A)
    bb = (min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs))
    bba = (bb[2] - bb[0]) * (bb[3] - bb[1])
    return {"cells": len(names), "area_um2": round(A, 1), "centroid_um": [r2(cx, 1), r2(cy, 1)],
            "rms_radius_um": r2(rg, 1), "r90_um": r2(sorted(dist)[int(0.9 * (len(dist) - 1))], 1),
            "bbox_um": [r2(v, 1) for v in bb], "bbox_area_um2": round(bba), "fill_of_bbox": r2(A / bba)}


def _bins(D, lef, names, weight=None, bw=BIN_W, bh=BIN_H):
    """{(bx, by): occupied area in DBU^2} on a grid of bw x bh from (0, ROW0), a cell split
    over the x bins it spans (bh is a whole number of rows, so a cell sits in one bin row)."""
    bins = collections.Counter()
    for n in names:
        m, x, y, _o = D.inst[n]
        w, h = lef[m]["size"]
        x1 = x + round(w * 1000)
        f = weight(n) if weight else 1.0
        for bx in range(x // bw, (x1 - 1) // bw + 1):
            ov = min(x1, (bx + 1) * bw) - max(x, bx * bw)
            bins[(bx, (y - ROW0) // bh)] += f * ov * round(h * 1000)
    return bins


def overlap(a, b):
    """Histogram intersection of two area maps, each normalised to 1: the share of a
    footprint that lands in the same grid cells in both layouts (1 = same place)."""
    ta, tb = sum(a.values()), sum(b.values())
    return round(sum(min(a[k] / ta, b[k] / tb) for k in set(a) & set(b)), 3)


def density(D, lef):
    """Part 1's statistic: cells other than taps, endcaps and fill (logic, flops, CTS,
    diodes) per 10 x 10.88 um bin; quantiles of the occupied bins sorted densest first."""
    names = [n for n, c in D.cls.items() if c not in ("tap", "endcap", "fill")]
    bins = _bins(D, lef, names)
    d = sorted((v / (BIN_W * BIN_H) for v in bins.values()), reverse=True)
    q = lambda f: round(d[min(len(d) - 1, int(len(d) * f))], 2)
    tot = sum(bins.values())
    return {"occupied_bins": len(d), "max": round(d[0], 2), "p10": q(0.1), "p25": q(0.25), "p50": q(0.5),
            f"area_share_in_bins_ge_{DENSE}": round(sum(v for v in bins.values() if v / (BIN_W * BIN_H) >= DENSE) / tot, 3)}


COARSE = (30000, 32640)  # a region-scale grid, 30 um x 12 rows, for footprint overlap and purity


def placement_section(P, O, areas, lef, fp_identical=None):
    n = lambda D, c: len(D.of(c))
    fp = {True: "The floorplan (die, rows, taps, endcaps, pins, PDN) is identical. ",
          False: "The floorplan (die, rows, taps, endcaps, pins, PDN) is NOT identical (see floorplan). ",
          None: ""}[fp_identical]
    res = {"verdict": (
        f"{fp}Placement is the one flow setting the round-trip config does not reproduce: our logic placement is "
        "OpenROAD's default global placement, and the mechanism behind the puzzle's placement is unknown (Part 1 open "
        "question). It is not the only difference in the layout. The cell count and mix differ too: logic "
        f"{n(O, 'logic')} vs {n(P, 'logic')} cells (ours vs puzzle), a synthesis/RTL difference and not a placement "
        f"one, and antenna diodes {n(O, 'diode')} vs {n(P, 'diode')} (flow-inserted). Routing, and which registers "
        "share a CTS leaf buffer, differ as a consequence.")}
    # matched flops: register fNN on both sides
    disp, per_block, same_pos, same_orient = [], collections.defaultdict(list), 0, 0
    blocks = json.load(open(BLOCKS_JSON))
    rows, pxy, oxy = [], {}, {}
    for n, f in sorted(O.fid.items(), key=lambda kv: kv[1]):
        pn = _puz_flop(P, f)
        a, b = P.inst[pn], O.inst[n]
        pxy[f], oxy[f] = a[1:3], b[1:3]
        dd = math.dist(a[1:3], b[1:3]) / 1000
        disp.append(dd)
        per_block[blocks["flops"][f]["block"]].append(dd)
        same_pos += a[1:3] == b[1:3]
        same_orient += a[1:4] == b[1:4]
        rows.append({"f": f, "puzzle": pn, "ours": n, "puzzle_um": [a[1] / 1000, a[2] / 1000],
                     "ours_um": [b[1] / 1000, b[2] / 1000], "displacement_um": round(dd, 2)})
    # what the displacement would be with no correspondence at all: every puzzle flop
    # against every other register's flop in our layout
    base = [math.dist(pxy[f], oxy[g]) / 1000 for f in pxy for g in oxy if f != g]
    res["flops_matched_by_register"] = {
        "count": len(disp), "same_position": same_pos, "same_position_and_orient": same_orient,
        "displacement_um": {"mean": r2(statistics.mean(disp), 1), "median": r2(statistics.median(disp), 1),
                            "min": r2(min(disp), 1), "max": r2(max(disp), 1),
                            "within_10um": sum(d <= 10 for d in disp), "within_25um": sum(d <= 25 for d in disp),
                            "over_50um": sum(d > 50 for d in disp)},
        "unmatched_baseline_um": {"mean": r2(statistics.mean(base), 1), "median": r2(statistics.median(base), 1),
                                  "what": "puzzle flop f vs our flop g for every f != g"},
        "mean_displacement_um_per_block": {b: r2(statistics.mean(v), 1) for b, v in per_block.items()},
        "per_flop": rows}
    # per block: bbox, centroid, spread, footprint overlap on the fine and the coarse grid
    blk = []
    for b in BLOCKS + [CLOCK]:
        sp, so = _stats(P, lef, areas, P.blocks[b]), _stats(O, lef, areas, O.blocks[b])
        blk.append({"block": b, "puzzle": sp, "ours": so,
                    "centroid_offset_um": centroid_offset(P, O, lef, areas, P.blocks[b], O.blocks[b]),
                    "footprint_overlap": overlap(_bins(P, lef, P.blocks[b]), _bins(O, lef, O.blocks[b])),
                    "footprint_overlap_coarse": overlap(_bins(P, lef, P.blocks[b], bw=COARSE[0], bh=COARSE[1]),
                                                        _bins(O, lef, O.blocks[b], bw=COARSE[0], bh=COARSE[1]))})
    res["per_block"] = blk
    lp, lo = P.of("logic", "flop", "clock"), O.of("logic", "flop", "clock")
    sp, so = _stats(P, lef, areas, lp), _stats(O, lef, areas, lo)
    res["all_logic"] = {"block": "all logic", "puzzle": sp, "ours": so,
                        "centroid_offset_um": centroid_offset(P, O, lef, areas, lp, lo),
                        "footprint_overlap": overlap(_bins(P, lef, lp), _bins(O, lef, lo)),
                        "footprint_overlap_coarse": overlap(_bins(P, lef, lp, bw=COARSE[0], bh=COARSE[1]),
                                                            _bins(O, lef, lo, bw=COARSE[0], bh=COARSE[1]))}
    res["grids"] = {"fine_um": [BIN_W / 1000, BIN_H / 1000], "coarse_um": [COARSE[0] / 1000, COARSE[1] / 1000],
                    "origin_um": [0, ROW0 / 1000]}
    res["density"] = {"puzzle": density(P, lef), "ours": density(O, lef),
                      "part1_default_gpl_p10": 0.55,
                      "note": ("Part 1's statistic: bins 10 um x 10.88 um (four rows) from (0, 10.88); cells other "
                               "than taps, endcaps and fill; p10 = density of the bin at the 10th percentile of the "
                               "occupied bins, densest first. Part 1's 0.55 (max 0.86) is its own default-GPL run of "
                               "the recovered RTL, out/roundtrip/forensics/ll_puzzle/runs/p1")}
    res["block_purity"] = {"fine": {D.label: purity(D, lef) for D in (P, O)},
                           "coarse": {D.label: purity(D, lef, *COARSE) for D in (P, O)}}
    return res


def purity(D, lef, bw=BIN_W, bh=BIN_H):
    """Area-weighted mean, over grid bins, of the largest single block's share of the bin's
    block-assigned area (a puzzle gate in k cones counts 1/k to each; the clock tree is
    left out): 1.0 = no two blocks ever share a bin."""
    k = collections.Counter(n for b in BLOCKS for n in D.blocks[b])
    per = {b: _bins(D, lef, D.blocks[b], weight=lambda n: 1 / k[n], bw=bw, bh=bh) for b in BLOCKS}
    keys = set().union(*per.values())
    T = sum(sum(per[b][q] for b in BLOCKS) for q in keys)
    return round(sum(max(per[b][q] for b in BLOCKS) for q in keys) / T, 3)


def routing_section(P, O):
    res = {"method": ("top-cell GDS paths (both sides, same reader), PDN paths removed; wirelength = sum of path "
                      "spine lengths; vias = VIA_* cell references by cut layer")}
    layers = ["met1", "met2", "met3", "met4", "met5"]
    wl = []
    for l in layers:
        a, b = P.geom["wirelength_um"].get(l, 0.0), O.geom["wirelength_um"].get(l, 0.0)
        wl.append({"layer": l, "puzzle_um": a, "ours_um": b, "ratio": r2(b / a) if a else None,
                   "puzzle_paths": P.geom["wire_paths"].get(l, 0), "ours_paths": O.geom["wire_paths"].get(l, 0)})
    res["signal_wirelength"] = wl
    tp, to = sum(P.geom["wirelength_um"].values()), sum(O.geom["wirelength_um"].values())
    res["signal_wirelength_total_um"] = {"puzzle": round(tp, 1), "ours": round(to, 1), "ratio": r2(to / tp)}
    vias = []
    for kind in ("signal", "pdn"):
        for cut in CUT.values():
            a, b = P.geom["vias"][kind].get(cut, 0), O.geom["vias"][kind].get(cut, 0)
            if a or b:
                vias.append({"kind": kind, "cut": cut, "puzzle": a, "ours": b})
    res["vias"] = vias
    res["signal_nets_per_layer_extraction"] = {"puzzle": routing_nets_per_layer(P.ex), "ours": routing_nets_per_layer(O.ex)}
    dx = O.def_extras
    def_signal_vias = sum(dx["vias"].values())
    gds_signal_vias = sum(O.geom["vias"]["signal"].values())
    res["ours_def_cross_check"] = {
        "def_wirelength_um": dx["wirelength_um"], "def_vias": dx["vias"],
        "def_total_wirelength_um": round(sum(dx["wirelength_um"].values()), 1),
        "gds_equals_def_wirelength": all(abs(dx["wirelength_um"].get(l, 0) - O.geom["wirelength_um"].get(l, 0)) < 0.05 for l in layers),
        "gds_equals_def_signal_vias": def_signal_vias == gds_signal_vias,
        "segments_after_a_via_in_a_statement": dx["segments_after_a_via"]}
    res["not_counted"] = {
        "what": ("top-level metal polygons (not in the wirelength: DEF RECT patches and pin squares on both sides; "
                 "on the puzzle also the post-flow additions) and references to non-VIA, non-std-cell cells"),
        "top_polygons": {"puzzle": P.geom["top_polygons"], "ours": O.geom["top_polygons"]},
        "other_references": {"puzzle": P.geom["other_references"], "ours": O.geom["other_references"]}}
    return res


def checks(P, O):
    def_inst = collections.Counter(O.inst.values())
    return {"ours_gds_extraction_equals_def_placement": def_inst == O.gds_inst,
            "ours_gds_instances": sum(O.gds_inst.values()), "ours_def_instances": sum(def_inst.values()),
            "puzzle_clkbufs_are_the_cone_clock_tree": set(P.of("clock")) == P.blocks[CLOCK],
            "ours_unmapped_logic_or_flops": len(O.unmapped)}


def compare(run):
    from tools.retrace.lef import read_lef
    from tools.roundtrip.synth import cell_areas

    lef = read_lef(LEF_PATH)
    # liberty `area`; the LEF footprint for the cells the liberty lacks (tapvpwrvgnd_1, fill_*)
    areas = dict(cell_areas())
    for m, v in lef.items():
        if v["size"]:
            areas.setdefault(m, v["size"][0] * v["size"][1])
    P = load_puzzle(lef)
    O = load_ours(run, lef)
    res = {"run_dir": rel(run), "reference": PUZZLE_GDS,
           "ours_views": {"def": rel(O.def_path), "gds": rel(O.gds_path)}}
    res["checks"] = checks(P, O)
    res["floorplan"] = floorplan(P, O, lef)
    res["cells"] = cells_section(P, O, areas, lef)
    res["blocks"] = blocks_section(P, O, areas, lef)
    res["placement"] = placement_section(P, O, areas, lef, floorplan_identical(res["floorplan"]))
    res["routing"] = routing_section(P, O)
    res["headline"] = headline(res)
    return res, P, O, lef


def floorplan_identical(f):
    """True when every floorplan item of floorplan() matches: die, rows, taps and endcaps
    (master/x/y/orient), signal pins, and the PDN straps, rails, DRC-fill patches and vias."""
    pdn = f["pdn"]
    return bool(f["die_um"]["identical"] and all(f["rows"]["identical"].values())
                and all(f[k]["identical_master_x_y_orient"] == f[k]["puzzle"] == f[k]["ours"] for k in ("taps", "endcaps"))
                and f["pins"]["identical"] == f["pins"]["total"]
                and all(v["identical"] == v["puzzle"] == v["ours"] for v in pdn.values()
                        if isinstance(v, dict) and "what" in v))


def headline(r):
    """A few sentences with the numbers that matter, computed from the result."""
    f, c, b, pl, rt = r["floorplan"], r["cells"], r["blocks"], r["placement"], r["routing"]
    pdn = f["pdn"]
    fp_same = floorplan_identical(f)
    bc = c["by_class"]
    ct = c["clock_tree"]
    shape = lambda t: (t["root"]["master"], t["root"]["fanout"], t["leaves"]["masters"], t["leaves"]["flops_per_leaf"],
                       t["dummy_loads"]["masters"], t["levels"])
    same_tree = shape(ct["puzzle"]) == shape(ct["ours"])
    fpl = ct["ours"]["leaves"]["flops_per_leaf"]
    fm, dn = pl["flops_matched_by_register"], pl["density"]
    al = pl["all_logic"]
    t = rt["signal_wirelength_total_um"]
    wl = {x["layer"]: x["ratio"] for x in rt["signal_wirelength"]}
    blk = ", ".join(f"{x['block']} {x['ours']['gates']}/{x['puzzle']['gates']}" for x in b["per_block"] if x["block"] != CLOCK)
    return [
        (f"Floorplan {'identical' if fp_same else 'NOT identical'}: die {f['die_um']['ours_def']}, "
         f"{f['rows']['ours_def']['count']} rows x {f['rows']['ours_def']['sites'][0]} sites, "
         f"{f['taps']['identical_master_x_y_orient']}/{f['taps']['puzzle']} taps and "
         f"{f['endcaps']['identical_master_x_y_orient']}/{f['endcaps']['puzzle']} endcaps at the same master/x/y/orient, "
         f"{f['pins']['identical']}/{f['pins']['total']} signal pins, {pdn['straps']['identical']}/{pdn['straps']['puzzle']} "
         f"PDN straps, {pdn['rails']['identical']}/{pdn['rails']['puzzle']} rails, "
         f"{pdn['via_positions']['identical']}/{pdn['via_positions']['puzzle']} PDN vias."),
        (f"Cells: logic {bc['logic']['ours']} vs {bc['logic']['puzzle']} ({bc['logic']['ours_area_um2']:.0f} vs "
         f"{bc['logic']['puzzle_area_um2']:.0f} um2), flops {bc['flop']['ours']} vs {bc['flop']['puzzle']} "
         f"({c['flops']['same_master_per_register']}/92 same master per register), clock buffers {bc['clock']['ours']} vs "
         f"{bc['clock']['puzzle']} ({'same tree shape' if same_tree else 'different tree shape'}: 1 root, "
         f"{ct['ours']['leaves']['count']} leaves of {min(fpl)}-{max(fpl)} flops, {ct['ours']['dummy_loads']['count']} dummy loads; "
         f"{ct['leaf_groups']['identical_groups']}/{ct['leaf_groups']['groups']} leaves drive the same registers, but "
         f"{ct['leaf_groups']['of_which_share_a_leaf_in_ours']} of the puzzle's "
         f"{ct['leaf_groups']['flop_pairs_sharing_a_leaf_puzzle']} same-leaf flop pairs share a leaf in ours, "
         f"against {ct['leaf_groups']['expected_by_chance']} expected by chance, {ct['leaf_groups']['ratio_to_chance']}x; "
         f"over {ct['leaf_groups']['chance_shuffle']['shuffles']} random leaf assignments the mean is "
         f"{ct['leaf_groups']['chance_shuffle']['mean']}, the 99th percentile {ct['leaf_groups']['chance_shuffle']['p99']} "
         f"and the max {ct['leaf_groups']['chance_shuffle']['max']}), "
         f"antenna diodes {bc['diode']['ours']} vs {bc['diode']['puzzle']}, fill {bc['fill']['ours']} vs {bc['fill']['puzzle']}."),
        f"Gates per block, ours/puzzle (puzzle counts include its 14 shared cone gates): {blk}.",
        (f"Placement NOT reproduced: {fm['same_position']}/{fm['count']} flops at the puzzle's position; a flop sits "
         f"{fm['displacement_um']['mean']} um (median {fm['displacement_um']['median']}) from its puzzle counterpart, "
         f"against {fm['unmatched_baseline_um']['mean']} um for unrelated flop pairs; block centroids move "
         + ", ".join(f"{x['block']} {x['centroid_offset_um']}" for x in pl["per_block"]) +
         f" um; {al['footprint_overlap']:.0%} of the logic area lands in the same 10 x 10.88 um bins "
         f"({al['footprint_overlap_coarse']:.0%} on a 30 x 32.64 um grid); bin density p10 {dn['ours']['p10']} vs "
         f"{dn['puzzle']['p10']}, area in bins >= {DENSE} dense {dn['ours'][f'area_share_in_bins_ge_{DENSE}']:.0%} vs "
         f"{dn['puzzle'][f'area_share_in_bins_ge_{DENSE}']:.0%}."),
        (f"Routing: signal wirelength {t['ours'] / 1000:.1f} mm vs {t['puzzle'] / 1000:.1f} mm ({t['ratio']}); by layer "
         + ", ".join(f"{k} {v}" for k, v in wl.items() if v is not None) + "; signal vias "
         + ", ".join(f"{v['cut'].split()[0]} {v['ours']}/{v['puzzle']}" for v in rt["vias"] if v["kind"] == "signal") + "."),
    ]


# ---- text -------------------------------------------------------------------------------


def show(r):
    w = print
    w(f"S4 round trip vs puzzle: ours = {r['run_dir']} ({r['ours_views']['def']}, {r['ours_views']['gds']}); "
      f"reference = {r['reference']}")
    w("")
    for line in r["headline"]:
        w("* " + line)
    c = r["checks"]
    w(f"\nchecks: our GDS extraction == DEF placement: {c['ours_gds_extraction_equals_def_placement']} "
      f"({c['ours_gds_instances']} instances); puzzle clkbufs == cone clock tree: "
      f"{c['puzzle_clkbufs_are_the_cone_clock_tree']}; unmapped ours: {c['ours_unmapped_logic_or_flops']}")
    f = r["floorplan"]
    w("\n== floorplan")
    w(f"die: puzzle {f['die_um']['puzzle_gds_boundary']}, ours DEF {f['die_um']['ours_def']} / GDS "
      f"{f['die_um']['ours_gds_boundary']}: identical {f['die_um']['identical']}")
    pr, orow = f["rows"]["puzzle_inferred_from_taps_endcaps"], f["rows"]["ours_def"]
    w(f"rows: puzzle {pr['count']} x {pr['sites'][0]} sites from ({pr['x0_um']}, {pr['y0_um']}) pitch {pr['pitch_um']} "
      f"orient {pr['orient_first_rows']}; ours {orow['count']} x {orow['sites']} from ({orow['x0_um']}, {orow['y0_um']}) "
      f"pitch {orow['pitch_um']} orient {orow['orient_first_rows']}; identical {all(f['rows']['identical'].values())}")
    for k in ("taps", "endcaps"):
        t = f[k]
        w(f"{k}: puzzle {t['puzzle']}, ours {t['ours']}, identical master/x/y/orient {t['identical_master_x_y_orient']} "
          f"(only puzzle {t['only_puzzle']}, only ours {t['only_ours']})")
    p = f["pins"]
    w(f"signal pins: {p['identical']}/{p['total']} identical (GDS label position+layer, DEF placement+layer); "
      f"pin shapes identical {p['pin_shapes_identical']}; power labels identical {p['power_labels_identical']}")
    for q in p["signal"]:
        if not q["same"]:
            w(f"   differs: {q}")
    for k, v in f["pdn"].items():
        if isinstance(v, dict) and "what" in v:
            w(f"PDN {v['what']}: puzzle {v['puzzle']}, ours {v['ours']}, identical {v['identical']}")
    cs = r["cells"]
    w("\n== cells by class (count, liberty area um2)")
    w(f"{'class':<8}{'puzzle':>8}{'area':>10}{'ours':>8}{'area':>10}{'delta':>8}")
    for k, v in cs["by_class"].items():
        w(f"{k:<8}{v['puzzle']:>8}{v['puzzle_area_um2']:>10.1f}{v['ours']:>8}{v['ours_area_um2']:>10.1f}"
          f"{v['ours'] - v['puzzle']:>+8}")
    w(f"{'total':<8}{cs['total_instances']['puzzle']:>8}{'':>10}{cs['total_instances']['ours']:>8}")
    s = cs["logic_masters_summary"]
    w(f"logic masters: puzzle {s['masters_puzzle']}, ours {s['masters_ours']}, in both {s['masters_both']}; "
      f"histogram intersection {s['cells_in_common_histogram']} cells, L1 distance {s['l1_distance']}")
    w("  " + ", ".join(f"{k} {v['puzzle']}->{v['ours']}" for k, v in cs["logic_detail"].items()))
    big = sorted(cs["logic_masters"], key=lambda x: -abs(x["delta"]))[:12]
    w("  largest per-master deltas (ours - puzzle): " + ", ".join(f"{x['master']} {x['delta']:+d}" for x in big))
    w("  every logic master, puzzle -> ours (liberty area each, um2):")
    ms = cs["logic_masters"]
    for k in range(0, len(ms), 5):
        w("    " + "".join(f"{x['master']:<10}{x['puzzle']:>3}->{x['ours']:<3}({x['area_each_um2']:>6.2f})  "
                           for x in ms[k:k + 5]).rstrip())
    w(f"flops: puzzle {cs['flops']['puzzle']}, ours {cs['flops']['ours']}; same master per register "
      f"{cs['flops']['same_master_per_register']}/92")
    for lbl in ("puzzle", "ours"):
        t = cs["clock_tree"][lbl]
        w(f"clock tree {lbl}: root {t['root']['master']} at {t['root']['at_um']} -> {t['root']['fanout']}; "
          f"{t['leaves']['count']} leaves {t['leaves']['masters']} with {t['leaves']['flops_per_leaf']} flops "
          f"(sum {t['leaves']['flops_total']}, mean leaf half-perimeter {t['leaves']['mean_half_perimeter_um']} um); "
          f"dummy loads {t['dummy_loads']['count']} {t['dummy_loads']['masters']} on "
          f"{t['leaves']['leaves_with_a_dummy_load']} leaves; levels {t['levels']}")
    lg = cs["clock_tree"]["leaf_groups"]
    w(f"  leaf groups: {lg['identical_groups']}/{lg['groups']} identical register sets; of the "
      f"{lg['flop_pairs_sharing_a_leaf_puzzle']} flop pairs sharing a leaf in the puzzle, "
      f"{lg['of_which_share_a_leaf_in_ours']} share one in ours, against {lg['expected_by_chance']} expected by "
      f"chance ({lg['ratio_to_chance']}x; {lg['chance_model']})")
    cs_ = lg["chance_shuffle"]
    w(f"  chance, simulated: {cs_['shuffles']} shuffles of our registers into leaves of our sizes (seed "
      f"{cs_['seed']}): mean {cs_['mean']}, 99th percentile {cs_['p99']}, max {cs_['max']}; "
      f"{cs_['shuffles_at_or_above_observed']} reach {lg['of_which_share_a_leaf_in_ours']}")
    for lbl in ("puzzle", "ours"):
        dd = cs["diodes"][lbl]
        w(f"antenna diodes {lbl}: {dd['count']} on {dd['nets']} nets {dd['per_net']}")
    w(f"fill: puzzle {cs['fill']['puzzle'] or 0}, ours {cs['fill']['ours'] or 0}")
    b = r["blocks"]
    w("\n== per recovered block (puzzle: cones incl. shared gates; ours: kept hierarchy)")
    w(f"cone walk reproduces block_cells() on the puzzle: {b['check_cone_walk_reproduces_block_cells_on_puzzle']}; "
      f"ours hierarchy == ours cones: {b['ours_hierarchy_vs_cones']['identical']}; puzzle gates in >1 cone: "
      f"{b['puzzle_shared_gates']}")
    w(f"{'block':<12}{'flops':>6}{'P gates':>9}{'(shared)':>9}{'P area':>9}{'O gates':>9}{'O area':>9}{'d gates':>9}{'d area':>9}")
    for x in b["per_block"]:
        pz, ou = x["puzzle"], x["ours"]
        w(f"{x['block']:<12}{pz['flops']:>6}{pz['gates']:>9}{pz['shared_gates']:>9}{pz['gate_area_um2']:>9.1f}"
          f"{ou['gates']:>9}{ou['gate_area_um2']:>9.1f}{x['gate_delta']:>+9}{x['gate_area_delta_um2']:>+9.1f}")
    pl = r["placement"]
    w("\n== placement (NOT reproduced)")
    w(pl["verdict"])
    fm = pl["flops_matched_by_register"]
    dm = fm["displacement_um"]
    w(f"flops matched by register: {fm['same_position']}/{fm['count']} at the puzzle's position; displacement mean "
      f"{dm['mean']} um, median {dm['median']}, min {dm['min']}, max {dm['max']}; <=10 um {dm['within_10um']}, "
      f"<=25 um {dm['within_25um']}, >50 um {dm['over_50um']}")
    ub = fm["unmatched_baseline_um"]
    w(f"  with no correspondence at all (puzzle flop f vs our flop g, f != g): mean {ub['mean']} um, "
      f"median {ub['median']}")
    w("  mean per block: " + ", ".join(f"{k} {v}" for k, v in fm["mean_displacement_um_per_block"].items()))
    g = pl["grids"]
    w(f"per block (centroid = area-weighted cell centres, um; r = rms / 90th-percentile distance from it; fill = "
      f"cell area / bbox; overlap = shared share of the footprint on the {g['fine_um'][0]:g} x {g['fine_um'][1]:g} "
      f"and {g['coarse_um'][0]:g} x {g['coarse_um'][1]:g} um grids)")
    w(f"{'block':<12}{'P centroid':>14}{'O centroid':>14}{'offset':>7}{'P r':>12}{'O r':>12}"
      f"{'P fill':>7}{'O fill':>7}{'overlap':>12}  P bbox / O bbox")
    for x in pl["per_block"] + [pl["all_logic"]]:
        pz, ou = x["puzzle"], x["ours"]
        w(f"{x['block']:<12}{str(tuple(pz['centroid_um'])):>14}{str(tuple(ou['centroid_um'])):>14}"
          f"{x['centroid_offset_um']:>7}{pz['rms_radius_um']:>6}/{pz['r90_um']:<5}{ou['rms_radius_um']:>6}/{ou['r90_um']:<5}"
          f"{pz['fill_of_bbox']:>7}{ou['fill_of_bbox']:>7}{x['footprint_overlap']:>6}/{x['footprint_overlap_coarse']:<5}"
          f"  {pz['bbox_um']} / {ou['bbox_um']}")
    dn = pl["density"]
    for lbl in ("puzzle", "ours"):
        d = dn[lbl]
        w(f"bin density {lbl}: occupied {d['occupied_bins']}, max {d['max']}, p10 {d['p10']}, p25 {d['p25']}, "
          f"p50 {d['p50']}; area share in bins >= {DENSE}: {d[f'area_share_in_bins_ge_{DENSE}']}")
    w(f"  (Part 1's default-GPL run of the recovered RTL gave p10 {dn['part1_default_gpl_p10']})")
    bp = pl["block_purity"]
    w(f"block purity (1 = no two blocks share a bin): fine grid puzzle {bp['fine']['puzzle']}, ours "
      f"{bp['fine']['ours']}; coarse grid puzzle {bp['coarse']['puzzle']}, ours {bp['coarse']['ours']}")
    rt = r["routing"]
    w("\n== routing (signal)")
    w(f"{'layer':<6}{'puzzle um':>11}{'ours um':>11}{'ratio':>7}{'P paths':>9}{'O paths':>9}")
    for x in rt["signal_wirelength"]:
        w(f"{x['layer']:<6}{x['puzzle_um']:>11.1f}{x['ours_um']:>11.1f}{str(x['ratio']):>7}{x['puzzle_paths']:>9}"
          f"{x['ours_paths']:>9}")
    t = rt["signal_wirelength_total_um"]
    w(f"{'total':<6}{t['puzzle']:>11.1f}{t['ours']:>11.1f}{str(t['ratio']):>7}")
    w("vias: " + "; ".join(f"{v['kind']} {v['cut']} {v['puzzle']}->{v['ours']}" for v in rt["vias"]))
    n = rt["signal_nets_per_layer_extraction"]
    w(f"signal nets routed on each layer: puzzle {n['puzzle']}, ours {n['ours']}")
    nc = rt["not_counted"]
    for lbl in ("puzzle", "ours"):
        w(f"not counted, {lbl}: top-level polygons " + "; ".join(
            f"{l} {v['count']} (most {v['sizes_um'][0][0]} um x{v['sizes_um'][0][1]}, in {v['bbox_um']})"
            for l, v in nc["top_polygons"][lbl].items()) + f"; other references {nc['other_references'][lbl] or 'none'}")
    x = rt["ours_def_cross_check"]
    w(f"ours cross-check against the DEF: wirelength equal {x['gds_equals_def_wirelength']} (DEF total "
      f"{x['def_total_wirelength_um']} um), signal vias equal {x['gds_equals_def_signal_vias']}")


# ---- figure -----------------------------------------------------------------------------


def figure(P, O, lef, panel_w=150, gap=18):
    """Two rows of seven panels (puzzle, ours) from tools.viz.layout.svg_panels, one per
    block plus the clock tree, same scale. Each row's shared cell path gets its own id so
    the figure can sit inline on a page next to docs/figures/puzzle_blocks.svg."""
    from tools.viz.layout import Die, svg_panels

    head = 26
    rows, labels = [], []
    names = {"puzzle": "puzzle", "ours": "ours"}
    heads = {"puzzle": "upstream/puzzle.gds: Jane Street's layout (blocks = logic cones)",
             "ours": "ours: rtl_recovered/ through LibreLane 3.0.14 Classic, upstream-like config (blocks = kept hierarchy)"}
    for D in (P, O):
        die = Die(200.0, 300.0, {n: rect_um(D, lef, n) for n in D.of("logic", "flop", "clock")})
        panels = []
        for b in BLOCKS + [CLOCK]:
            cells = D.blocks[b]
            fl = sum(1 for n in cells if D.cls[n] == "flop")
            sub = f"{len(cells)} buffers" if b == CLOCK else f"{fl} flops, {len(cells) - fl} gates"
            panels.append((f"{names[D.label]}: {b}", sub, sorted(cells)))
        svg = svg_panels(die, panels, cols=7, panel_w=panel_w, gap=gap)
        inner = svg[svg.index(">") + 1:svg.rindex("</svg>")]
        cid = f"rt-cells-{D.label}"
        inner = inner.replace('id="lo-cells"', f'id="{cid}"').replace('href="#lo-cells"', f'href="#{cid}"')
        m = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
        rows.append((D.label, inner, int(m.group(1)), int(m.group(2))))
        labels.append(f"{heads[D.label]}: " + "; ".join(f"{t.split(': ')[1]}, {s}" for t, s, _n in panels))
    W = max(r[2] for r in rows)
    H = sum(head + r[3] for r in rows) + gap
    label = ("The 200 by 300 um die drawn fourteen times at one scale: top row the puzzle, bottom row our "
             "round-trip layout; each panel highlights one recovered block or the clock tree. " + " | ".join(labels))
    parts = [f'<svg class="lo" viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(label)}" '
             f'xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;max-width:{W}px">']
    y = 0
    for (lbl, inner, _w, h) in rows:
        parts.append(f'<text x="0" y="{y + 15}" style="fill:var(--ink,#15181c);font:600 14px ui-monospace,Menlo,'
                     f'monospace">{html.escape(heads[lbl])}</text>')
        parts.append(f'<g transform="translate(0 {y + head})">{inner}</g>')
        y += head + h + gap
    parts.append("</svg>")
    return "".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run_dir")
    ap.add_argument("--json", help="JSON output path, or - to print JSON instead of text "
                                   "(default out/roundtrip/vs_puzzle/<run>.json)")
    ap.add_argument("--svg", nargs="?", const=FIGURE, help=f"draw the block figure (default path {FIGURE})")
    a = ap.parse_args(argv)
    run = os.path.abspath(a.run_dir)
    json_out = a.json if a.json == "-" or a.json is None else os.path.abspath(a.json)
    svg_out = os.path.join(ROOT, FIGURE) if a.svg == FIGURE else os.path.abspath(a.svg) if a.svg else None
    os.chdir(ROOT)  # tools.analysis.cone and the pdk paths are repo-relative
    sys.path.insert(0, ROOT)
    res, P, O, lef = compare(run)
    if json_out == "-":
        json.dump(res, sys.stdout, indent=1)
        print()
    else:
        show(res)
        if json_out is None:
            os.makedirs(OUT_DIR, exist_ok=True)
            json_out = os.path.join(OUT_DIR, os.path.basename(run.rstrip("/")) + ".json")
        with open(json_out, "w") as f:
            json.dump(res, f, indent=1)
            f.write("\n")
        print(f"\nJSON: {rel(json_out)}")
    if svg_out:
        svg = figure(P, O, lef)
        with open(svg_out, "w") as f:
            f.write(svg)
        print(f"SVG: {rel(svg_out)} ({len(svg.encode()) / 1024:.0f} KB)", file=sys.stderr if json_out == "-" else sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
