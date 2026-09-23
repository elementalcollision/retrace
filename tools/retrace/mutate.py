"""RETRACE layout-mutation operators (docs/spec/VERIFICATION.md section 2, "the TEMPO move").

Each operator enumerates deterministic candidate *sites* from a real `Extraction` of the
base design (so sites are chosen on real signal nets, real paths, real vias — not random
coordinates), then *applies* one site to a freshly-loaded `gdstk.Library`, mutating it in
place and returning a precise, human-readable description (cell/path/via, coordinates,
layer). Never share a loaded Library between mutants: always start from `load(gds_path)`.

    from tools.retrace.mutate import OPERATORS, load
    sites = OPERATORS["via_delete"].enumerate(ex, lef)
    lib = load(design_path)
    desc = OPERATORS["via_delete"].apply(lib, ex.top.name, sites[0], lef, pdk_cells)
    lib.write_gds(out_path)

Site dicts are small and JSON-serialisable (`out/mut/results.json` stores them), and are
enough on their own (plus `lef`/`pdk_cells`) to re-apply a mutation deterministically —
sites never hold live gdstk objects.
"""

import collections
import math
import random
from dataclasses import dataclass
from typing import Callable

import gdstk
from shapely.geometry import Polygon

from .extract import CONDUCTOR_DT, LICON, ORIENT, PHYSICAL, POLY, PREFIX

# --- via families the campaign is allowed to touch (task spec) -------------------------
VIA_FAMILY = {
    "VIA_L1M1_PR_MR": 67,  # li1/met1 mcon
    "VIA_M1M2_PR": 68,     # met1/met2 via
    "VIA_M2M3_PR": 69,     # met2/met3 via2
    "VIA_M3M4_PR": 70,     # met3/met4 via3
}
LAYER_NAMES = {67: "li1", 68: "met1", 69: "met2", 70: "met3", 71: "met4", 72: "met5"}
FLIP_PAIRS = {"N": "FS", "FS": "N", "S": "FN", "FN": "S"}
# same LEF footprint width *and* height in this PDK (8afc8346), verified against
# pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef; and2_2/or2_2 (the task's suggested pair)
# differ in width (2.76 vs 2.30 um) in this PDK revision and are NOT used — see
# docs/MUTATION.md "Deviations from the brief".
MASTER_SWAP_PAIRS = [
    ("nand2_2", "nor2_2"),
    ("xor2_2", "xnor2_2"),
    ("and3_2", "or3_2"),
    ("nand3_2", "nor3_2"),
]
ART_LAYER, ART_DT = 69, 20  # met2 pixel-art squares


def _poly(points):
    g = Polygon(points)
    return g if g.is_valid else g.buffer(0)


def load(gds_path):
    """A fresh Library for one mutation. Never reuse across mutants: gdstk cells/refs
    can be shared, and mutating a shared master cell would corrupt other mutants."""
    return gdstk.read_gds(gds_path)


def load_pdk_cells(pdk_gds="pdk/sky130_fd_sc_hd/gds/sky130_fd_sc_hd.gds"):
    return {c.name: c for c in gdstk.read_gds(pdk_gds).cells}


PRIVATE_MARKERS = ("__PINSWAP_", "__TAMPER_")


def base_master_name(name):
    """pin_label_swap/cell_internal_tamper name their private copy
    "<original>__PINSWAP_<seq>" / "<original>__TAMPER_<seq>"; this recovers <original>."""
    for marker in PRIVATE_MARKERS:
        if marker in name:
            return name.split(marker)[0]
    return name


def lef_for_mutant(lef, lib):
    """LEF dict extended with a synthetic entry (same footprint as the original master)
    for every private per-mutant cell copy in `lib`, so Extraction -- which looks up
    every instantiated master's LEF size -- never crashes on a name the shared LEF has
    never heard of. V2 (pins vs LEF) then compares the *tampered* geometry against the
    *original* master's LEF pins, which is exactly the point of pin_label_swap and
    cell_internal_tamper."""
    ext = dict(lef)
    for cell in lib.cells:
        if cell.name not in ext:
            base = base_master_name(cell.name)
            if base in lef:
                ext[cell.name] = lef[base]
    return ext


def _top(lib, name):
    return next(c for c in lib.top_level() if c.name == name)


def _net_lookup(ex):
    return {m["root"]: m for m in ex.nets}


def _is_signal_root(by_root, root):
    m = by_root.get(root)
    return bool(m) and not m["supply"]


def _def_xy(ref, lef, master):
    """Same derivation as Extraction._instances_and_pins: GDS reference -> DEF-style
    (lower-left x, y, orient) in DBU (nm), so sites never depend on GDS reference order."""
    rot = int(round(math.degrees(ref.rotation))) % 360
    orient = ORIENT[(rot, bool(ref.x_reflection))]
    w, h = lef[master]["size"]
    wd, hd = round(w * 1000), round(h * 1000)
    ox, oy = round(ref.origin[0] * 1000), round(ref.origin[1] * 1000)
    x = ox - wd if orient in ("S", "FN") else ox
    y = oy - hd if orient in ("S", "FS") else oy
    return x, y, orient


def _find_ref(top, lef, master, x, y, orient):
    for ref in top.references:
        if ref.cell.name != master:
            continue
        if _def_xy(ref, lef, master) == (x, y, orient):
            return ref
    raise LookupError(f"no reference found for {master} at DEF ({x},{y}) {orient}")


def _um(x):
    return x / 1000.0


# ============================================================ via_delete (open) ========

def sites_via_delete(ex, lef):
    """One candidate per via instance of the 4 required families whose cut lands on a
    signal net (never a VPWR/VGND via). Deleting it opens that net."""
    by_root = _net_lookup(ex)
    idx_by_name = collections.Counter()
    cands = []
    for layer, geom, via_name in ex.cuts:
        i = idx_by_name[via_name]
        idx_by_name[via_name] += 1
        if via_name not in VIA_FAMILY:
            continue
        root = None
        for lyr in (layer, layer + 1):
            tree, sids = ex.trees.get(lyr, (None, None))
            if tree is None:
                continue
            hit = tree.query(geom, predicate="intersects").tolist()
            if hit:
                root = ex.uf.find(sids[hit[0]])
                break
        if root is None or not _is_signal_root(by_root, root):
            continue
        c = geom.centroid
        cands.append({"via": via_name, "index": i, "x": round(c.x, 4), "y": round(c.y, 4),
                      "layer": LAYER_NAMES[layer], "net": by_root[root]["name"]})
    cands.sort(key=lambda s: (s["via"], s["x"], s["y"]))
    return cands


def apply_via_delete(lib, top_name, site, lef, pdk_cells):
    top = _top(lib, top_name)
    refs = [r for r in top.references if r.cell.name == site["via"]]
    target = refs[site["index"]]
    top.remove(target)
    return (f"removed {site['via']} instance #{site['index']} at "
            f"({site['x']:.3f}, {site['y']:.3f}) um, cut on {site['layer']}, "
            f"net {site['net']!r} -- opens that via")


# ============================================================ path_shift_nearmiss ======

def sites_path_shift_nearmiss(ex, lef):
    """Simple 2-point paths on a signal net that actually meet >=1 other shape (so
    shifting one end can plausibly separate a real touch, not just an already-dangling
    stub)."""
    by_root = _net_lookup(ex)
    cands = []
    for i, path in enumerate(ex.top.paths):
        if len(path.spine()) != 2:
            continue
        polys = path.to_polygons()
        if len(polys) != 1:
            continue
        poly = polys[0]
        geom = _poly(poly.points)
        tree, sids = ex.trees[poly.layer]
        hit = tree.query(geom, predicate="intersects").tolist()
        if len(hit) < 2:
            continue
        root = ex.uf.find(sids[hit[0]])
        if not _is_signal_root(by_root, root):
            continue
        cands.append({"path_index": i, "layer": LAYER_NAMES[poly.layer], "net": by_root[root]["name"]})
    cands.sort(key=lambda s: (s["layer"], s["path_index"]))
    return cands


def apply_path_shift_nearmiss(lib, top_name, site, lef, pdk_cells):
    top = _top(lib, top_name)
    path = top.paths[site["path_index"]]
    spine = path.spine()
    ends, layer, dt = path.ends[0], path.layers[0], path.datatypes[0]
    w = float(path.widths()[0][0])
    (x0, y0), (x1, y1) = spine[0], spine[1]
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1.0
    ux, uy = -dy / length, dx / length
    rng = random.Random(site["seed"])
    shift = rng.uniform(0.005, 0.020) * rng.choice((-1, 1))  # 5-20 nm
    new_spine = [(x0 + ux * shift, y0 + uy * shift), (x1, y1)]
    top.remove(path)
    top.add(gdstk.FlexPath(new_spine, w, ends=ends, layer=layer, datatype=dt))
    return (f"shifted end 0 of path #{site['path_index']} on {site['layer']} "
            f"(net {site['net']!r}) by {shift * 1000:+.1f} nm perpendicular to the spine "
            f"-- near-miss open")


# ============================================================ path_widen_short =========

def sites_path_widen_short(ex, lef):
    """Simple paths on a signal net with a nearby (<=400 nm) shape on the same layer
    belonging to a *different* signal net: widening bridges the gap."""
    by_root = _net_lookup(ex)
    cands = []
    for i, path in enumerate(ex.top.paths):
        polys = path.to_polygons()
        if len(polys) != 1:
            continue
        poly = polys[0]
        if poly.datatype not in CONDUCTOR_DT:
            continue
        geom = _poly(poly.points)
        tree, sids = ex.trees[poly.layer]
        hit = tree.query(geom, predicate="intersects").tolist()
        if not hit:
            continue
        root = ex.uf.find(sids[hit[0]])
        if not _is_signal_root(by_root, root):
            continue
        near = tree.query(geom.buffer(0.4), predicate="intersects").tolist()
        best = None
        for h in near:
            r2 = ex.uf.find(sids[h])
            if r2 == root or not _is_signal_root(by_root, r2):
                continue
            d = geom.distance(ex.shapes[sids[h]][2])
            if d <= 0.001:
                continue
            if best is None or d < best[0]:
                best = (d, r2)
        if best is None:
            continue
        d, r2 = best
        w = float(path.widths()[0][0])
        cands.append({"path_index": i, "layer": LAYER_NAMES[poly.layer], "net": by_root[root]["name"],
                      "target_net": by_root[r2]["name"], "old_width": round(w, 4),
                      "new_width": round(w + 2 * (d + 0.02), 4), "gap": round(d, 4)})
    cands.sort(key=lambda s: (s["layer"], s["path_index"]))
    return cands


def apply_path_widen_short(lib, top_name, site, lef, pdk_cells):
    top = _top(lib, top_name)
    path = top.paths[site["path_index"]]
    spine, ends, layer, dt = path.spine(), path.ends[0], path.layers[0], path.datatypes[0]
    top.remove(path)
    top.add(gdstk.FlexPath(spine, site["new_width"], ends=ends, layer=layer, datatype=dt))
    return (f"widened path #{site['path_index']} on {site['layer']} (net {site['net']!r}) "
            f"from {site['old_width'] * 1000:.0f} nm to {site['new_width'] * 1000:.0f} nm "
            f"to bridge a {site['gap'] * 1000:.0f} nm gap to net {site['target_net']!r} (short)")


# ============================================================ cell_flip ================

def sites_cell_flip(ex, lef):
    cands = []
    for inst in ex.instances:
        short = inst["master"][len(PREFIX):]
        if short.startswith(PHYSICAL):
            continue
        cands.append({"master": inst["master"], "x": inst["x"], "y": inst["y"], "orient": inst["orient"]})
    cands.sort(key=lambda s: (s["master"], s["x"], s["y"]))
    return cands


def apply_cell_flip(lib, top_name, site, lef, pdk_cells):
    top = _top(lib, top_name)
    ref = _find_ref(top, lef, site["master"], site["x"], site["y"], site["orient"])
    w, h = lef[site["master"]]["size"]
    wd, hd = round(w * 1000), round(h * 1000)
    new_orient = FLIP_PAIRS[site["orient"]]
    ox = site["x"] + wd if new_orient in ("S", "FN") else site["x"]
    oy = site["y"] + hd if new_orient in ("S", "FS") else site["y"]
    ref.origin = (_um(ox), _um(oy))
    ref.rotation = math.radians(0 if new_orient in ("N", "FS") else 180)
    ref.x_reflection = new_orient in ("FS", "FN")
    short = site["master"][len(PREFIX):]
    return (f"flipped {short} at DEF ({_um(site['x']):.3f},{_um(site['y']):.3f}) "
            f"{site['orient']} -> {new_orient} (same DEF lower-left)")


# ============================================================ master_swap ==============

def sites_master_swap(ex, lef):
    by_master = collections.defaultdict(list)
    for inst in ex.instances:
        by_master[inst["master"][len(PREFIX):]].append(inst)
    cands = []
    for a, b in MASTER_SWAP_PAIRS:
        for src, dst in ((a, b), (b, a)):
            for inst in by_master.get(src, []):
                cands.append({"master": inst["master"], "x": inst["x"], "y": inst["y"],
                              "orient": inst["orient"], "new_master": PREFIX + dst})
    cands.sort(key=lambda s: (s["master"], s["new_master"], s["x"], s["y"]))
    return cands


def _pin_geometry_diff(lef, old, new):
    """Pins of masters `old`/`new` whose LEF port rectangles differ, in the cell's own
    frame (the swap keeps the reference's origin and orientation, so equal LEF rects
    land on equal layout), or that only one master has. [] means identical pin geometry;
    None means either master has no LEF entry, so nothing was compared."""
    if old not in lef or new not in lef:
        return None
    po, pn = lef[old]["pins"], lef[new]["pins"]
    diff = []
    for pin in sorted(set(po) | set(pn)):
        if pin not in pn:
            diff.append(f"{pin} (only on {old[len(PREFIX):]})")
        elif pin not in po:
            diff.append(f"{pin} (only on {new[len(PREFIX):]})")
        elif sorted(po[pin]["rects"]) != sorted(pn[pin]["rects"]):
            diff.append(pin)
    return diff


def apply_master_swap(lib, top_name, site, lef, pdk_cells):
    top = _top(lib, top_name)
    ref = _find_ref(top, lef, site["master"], site["x"], site["y"], site["orient"])
    new_name = site["new_master"]
    existing = next((c for c in lib.cells if c.name == new_name), None)
    if existing is None:
        existing = pdk_cells[new_name].copy(new_name)
        lib.add(existing)
    ref.cell = existing
    a, b = site["master"][len(PREFIX):], new_name[len(PREFIX):]
    # The routing is untouched, so whether a connection survives depends on where the new
    # master's pins lie: a pin whose geometry changed may still overlap the old contact and
    # then joins the net to a DIFFERENT pin (nand2_2 A over nor2_2 B, for one). The string
    # reports per swap whether LEF pin geometry is identical (docs/ROUNDTRIP.md section 7).
    # Even identical pin geometry does not rule out routing touching the new master's
    # internal (non-pin) shapes, so the string never claims identical connectivity.
    diff = _pin_geometry_diff(lef, site["master"], new_name)
    if diff is None:
        pins = "pin geometry not compared (no LEF entry)"
    elif not diff:
        pins = "identical pin geometry"
    else:
        pins = "pin geometry differs: " + ", ".join(diff)
    return (f"swapped master {a} -> {b} at DEF ({_um(site['x']):.3f},{_um(site['y']):.3f}) "
            f"{site['orient']} -- same footprint width/height, behavioural change, {pins}")


# ============================================================ pin_label_swap ===========

def sites_pin_label_swap(ex, lef):
    cands = []
    for inst in ex.instances:
        master = inst["master"]
        short = master[len(PREFIX):]
        if short.startswith(PHYSICAL):
            continue
        inputs = sorted(p for p, d in lef[master]["pins"].items() if d["direction"] == "INPUT" and d["rects"])
        if len(inputs) < 2:
            continue
        cands.append({"master": master, "x": inst["x"], "y": inst["y"], "orient": inst["orient"],
                      "pin_a": inputs[0], "pin_b": inputs[1]})
    cands.sort(key=lambda s: (s["master"], s["x"], s["y"]))
    return cands


def apply_pin_label_swap(lib, top_name, site, lef, pdk_cells, seq="0"):
    top = _top(lib, top_name)
    ref = _find_ref(top, lef, site["master"], site["x"], site["y"], site["orient"])
    src = ref.cell
    new_name = f"{src.name}__PINSWAP_{seq}"
    private = src.copy(new_name)
    a, b = site["pin_a"], site["pin_b"]
    na = nb = 0
    for lb in private.labels:
        if lb.text == a:
            lb.text, na = b, na + 1
        elif lb.text == b:
            lb.text, nb = a, nb + 1
    if not na or not nb:  # a pin can be several li1 islands, each labelled the same text
        raise RuntimeError(f"expected labels {a} and {b} on {src.name}, found {na}/{nb}")
    lib.add(private)
    ref.cell = private
    short = site["master"][len(PREFIX):]
    return (f"private copy of {short} at DEF ({_um(site['x']):.3f},{_um(site['y']):.3f}) "
            f"({new_name}) with pin labels {a}<->{b} swapped -- no physical change, "
            f"mislabels the input")


# ============================================================ path_endtype =============

def sites_path_endtype(ex, lef):
    by_root = _net_lookup(ex)
    cands = []
    for i, path in enumerate(ex.top.paths):
        polys = path.to_polygons()
        if len(polys) != 1:
            continue
        poly = polys[0]
        geom = _poly(poly.points)
        tree, sids = ex.trees[poly.layer]
        hit = tree.query(geom, predicate="intersects").tolist()
        if not hit:
            continue
        root = ex.uf.find(sids[hit[0]])
        if not _is_signal_root(by_root, root):
            continue
        cands.append({"path_index": i, "layer": LAYER_NAMES[poly.layer], "net": by_root[root]["name"],
                      "old_end": path.ends[0]})
    cands.sort(key=lambda s: (s["layer"], s["path_index"]))
    return cands


def apply_path_endtype(lib, top_name, site, lef, pdk_cells):
    top = _top(lib, top_name)
    path = top.paths[site["path_index"]]
    new_end = "flush" if site["old_end"] == "extended" else "extended"
    path.set_ends(new_end)
    return f"path #{site['path_index']} on {site['layer']} (net {site['net']!r}) end type {site['old_end']} -> {new_end}"


# ============================================================ cell_internal_tamper =====

def sites_cell_internal_tamper(ex, lef):
    cands = []
    for inst in ex.instances:
        short = inst["master"][len(PREFIX):]
        if short.startswith(PHYSICAL):
            continue
        cands.append({"master": inst["master"], "x": inst["x"], "y": inst["y"], "orient": inst["orient"]})
    cands.sort(key=lambda s: (s["master"], s["x"], s["y"]))
    return cands


def apply_cell_internal_tamper(lib, top_name, site, lef, pdk_cells, seq="0"):
    top = _top(lib, top_name)
    ref = _find_ref(top, lef, site["master"], site["x"], site["y"], site["orient"])
    src = ref.cell
    new_name = f"{src.name}__TAMPER_{seq}"
    private = src.copy(new_name)
    targets = sorted((p for p in private.polygons if (p.layer, p.datatype) in (POLY, LICON)),
                      key=lambda p: (p.layer, p.datatype, tuple(p.points[0])))
    if not targets:
        raise RuntimeError(f"no poly/licon shapes on {src.name}")
    victim = targets[0]
    private.remove(victim)
    lib.add(private)
    ref.cell = private
    kind = "poly gate" if (victim.layer, victim.datatype) == POLY else "licon contact"
    short = site["master"][len(PREFIX):]
    return (f"private copy of {short} at DEF ({_um(site['x']):.3f},{_um(site['y']):.3f}) "
            f"({new_name}) with one {kind} shape deleted -- transistor-level tamper")


# ============================================================ art_delete ===============

def sites_art_delete(ex, lef):
    cands = []
    for idx, p in enumerate(ex.top.polygons):
        if p.layer != ART_LAYER or p.datatype != ART_DT:
            continue
        pts = p.points
        w, h = pts[:, 0].max() - pts[:, 0].min(), pts[:, 1].max() - pts[:, 1].min()
        if not (0.25 < w < 0.35 and 0.25 < h < 0.35):
            continue  # only the ~0.3 um pixel-art squares (STATUS.md finding 5), not routing
        cands.append({"index": idx, "x": round(float(pts[:, 0].mean()), 4), "y": round(float(pts[:, 1].mean()), 4)})
    cands.sort(key=lambda s: (s["x"], s["y"]))
    return cands


def apply_art_delete(lib, top_name, site, lef, pdk_cells):
    top = _top(lib, top_name)
    top.remove(top.polygons[site["index"]])
    return f"deleted met2 pixel-art square #{site['index']} at ({site['x']:.3f},{site['y']:.3f}) um"


# ============================================================ via_insert_short =========

def sites_via_insert_short(ex, lef):
    """A point where a signal shape on layer L and a *different* signal net's shape on
    layer L+1 actually overlap in XY (a routing crossing with no via today): inserting a
    via there shorts the two nets."""
    by_root = _net_lookup(ex)
    cands = []
    for via_name, layer in sorted(VIA_FAMILY.items(), key=lambda kv: kv[1]):
        if layer not in ex.trees or (layer + 1) not in ex.trees:
            continue
        treeA, sidsA = ex.trees[layer]
        treeB, sidsB = ex.trees[layer + 1]
        geomsB = [ex.shapes[s][2] for s in sidsB]
        if not geomsB:
            continue
        left, right = treeA.query(geomsB, predicate="intersects")
        seen = set()
        for bi, ai in zip(left.tolist(), right.tolist()):
            sidA, sidB = sidsA[ai], sidsB[bi]
            rootA, rootB = ex.uf.find(sidA), ex.uf.find(sidB)
            if rootA == rootB:
                continue
            if not (_is_signal_root(by_root, rootA) and _is_signal_root(by_root, rootB)):
                continue
            key = (via_name, min(sidA, sidB), max(sidA, sidB))
            if key in seen:
                continue
            seen.add(key)
            overlap = ex.shapes[sidA][2].intersection(ex.shapes[sidB][2])
            if overlap.is_empty:
                continue
            c = overlap.centroid
            cands.append({"via": via_name, "x": round(c.x, 4), "y": round(c.y, 4),
                          "net_a": by_root[rootA]["name"], "net_b": by_root[rootB]["name"]})
    cands.sort(key=lambda s: (s["via"], s["x"], s["y"]))
    return cands


def apply_via_insert_short(lib, top_name, site, lef, pdk_cells):
    top = _top(lib, top_name)
    via_cell = next(c for c in lib.cells if c.name == site["via"])
    top.add(gdstk.Reference(via_cell, origin=(site["x"], site["y"])))
    return (f"inserted {site['via']} at ({site['x']:.3f},{site['y']:.3f}) um where "
            f"net {site['net_a']!r} crosses net {site['net_b']!r} -- shorts them")


# ============================================================ registry ================

@dataclass
class Operator:
    name: str
    kind: str  # "open" | "short" | "near-miss" | "orientation" | "behavioural" | "mislabel" | "path-end" | "transistor" | "cosmetic"
    enumerate: Callable
    apply: Callable
    description: str


OPERATORS = {
    "via_delete": Operator("via_delete", "open", sites_via_delete, apply_via_delete,
                            "remove one via instance on a signal net"),
    "path_shift_nearmiss": Operator("path_shift_nearmiss", "near-miss", sites_path_shift_nearmiss,
                                     apply_path_shift_nearmiss,
                                     "move one routing path end 5-20 nm so it stops touching"),
    "path_widen_short": Operator("path_widen_short", "short", sites_path_widen_short, apply_path_widen_short,
                                  "widen a path until it touches a different signal net"),
    "cell_flip": Operator("cell_flip", "orientation", sites_cell_flip, apply_cell_flip,
                           "change one standard-cell instance orientation in place"),
    "master_swap": Operator("master_swap", "behavioural", sites_master_swap, apply_master_swap,
                             "replace one instance's master with a same-footprint different master"),
    "pin_label_swap": Operator("pin_label_swap", "mislabel", sites_pin_label_swap, apply_pin_label_swap,
                                "swap two input pin labels in a private copy of one master"),
    "path_endtype": Operator("path_endtype", "path-end", sites_path_endtype, apply_path_endtype,
                              "change a path's end type (extended <-> flush)"),
    "cell_internal_tamper": Operator("cell_internal_tamper", "transistor", sites_cell_internal_tamper,
                                      apply_cell_internal_tamper,
                                      "delete one poly/licon shape in a private copy of one master"),
    "art_delete": Operator("art_delete", "cosmetic", sites_art_delete, apply_art_delete,
                            "delete one met2 pixel-art square"),
    "via_insert_short": Operator("via_insert_short", "short", sites_via_insert_short, apply_via_insert_short,
                                  "add a via where two different signal nets cross on adjacent layers"),
}
