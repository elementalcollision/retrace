"""RETRACE extractor 1: GDS (any `tech.Tech`) to a cell-level netlist.

Technology-independent since the TEMPO port (docs/TEMPO_LVS.md): everything that
used to be a sky130-specific constant (layer numbers, datatypes, the poly/licon
intra-cell join, physical-cell prefixes, supply names) now comes from a
`tools.retrace.tech.Tech` passed to `Extraction`. The default is
`tech.SKY130_HD`, which reproduces exactly what this file did before the
refactor (byte-identical `out/puzzle.v`, same 50/50 tests).

Stages (docs/spec/APPROACH.md):
  S1 instances   every std-cell/macro reference: master, DEF-style lower-left, orientation
  S2 pins        per master, the conductor under each pin label, joined per Tech
                 (e.g. sky130: li1/met1 via mcon, li1 islands via poly+licon;
                 IHP: Metal1 islands via GatPoly+Cont)
  S3 nets        union-find over conductor shapes: routing (paths and polygons),
                 via-cell pads, cell/macro pins; a Tech `Cut` joins the two
                 conductors it touches
  S4 netlist     structural Verilog + JSON, deterministic names

    python -m tools.retrace.extract GDS [--top NAME] [--verilog OUT.v] [--json OUT.json]
"""

import argparse
import collections
import json
import math
import sys

import gdstk
import shapely
from shapely.geometry import Point, Polygon

from .tech import SKY130_HD

ORIENT = {
    (0, False): "N", (90, False): "W", (180, False): "S", (270, False): "E",
    (0, True): "FS", (90, True): "FE", (180, True): "FN", (270, True): "FW",
}
# DEF PLACED (x, y) is the lower-left of the placed (already-oriented) LEF
# footprint; GDS gives the transformed origin of the cell's local (0, 0). The
# offset between them, in terms of the LEF SIZE (w, h), depends on orientation
# (derived from gdstk's mirror-then-rotate transform order and cross-checked
# against TEMPO's IHP macro, the first rotated instance this project has seen --
# the puzzle and warm-up only ever use N/S/FN/FS, which reproduce the pre-port
# formula exactly). 0 means "no offset on this axis", "w"/"h" subtract that LEF
# dimension.
_ORIENT_OFFSET = {
    "N": (0, 0), "S": ("w", "h"), "E": (0, "w"), "W": ("h", 0),
    "FN": ("w", 0), "FS": (0, "h"), "FE": (0, 0), "FW": ("h", "w"),
}

# Backward-compatible module-level aliases for tools/tests written against the
# pre-refactor, sky130-only extract.py (tools/retrace/mutate.py,
# tools/analysis/cone.py, test/*). All derived from `tech.SKY130_HD`, the
# default Tech, so they stay exactly what they were before this module gained
# a `Tech` parameter.
PREFIX = SKY130_HD.prefix
SUPPLY_PINS = SKY130_HD.supply_pins
PHYSICAL = SKY130_HD.physical_prefixes
CONDUCTOR_DT = SKY130_HD.conductors[0].datatypes
POLY = SKY130_HD.poly_layer
LICON = SKY130_HD.poly_cut


class UnionFind:
    def __init__(self):
        self.parent = []

    def add(self):
        self.parent.append(len(self.parent))
        return len(self.parent) - 1

    def find(self, a):
        p = self.parent
        while p[a] != a:
            p[a] = p[p[a]]
            a = p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _poly(points):
    g = Polygon(points)
    return g if g.is_valid else g.buffer(0)


def _dbu(v):
    return int(round(v * 1000))


class Extraction:
    """Result of extracting one GDS top cell under a given `Tech`."""

    def __init__(self, gds_path, lef, top=None, tech=SKY130_HD):
        self.tech = tech
        self.lef = lef
        self.lib = gdstk.read_gds(gds_path)
        tops = self.lib.top_level()
        self.top = next(c for c in tops if c.name == top) if top else tops[0]
        self.instances = []  # dicts: name, master, x, y (DBU lower-left), orient, pins{pin: shape ids}
        self.ports = {}  # port name -> shape id
        self.supply_labels = collections.defaultdict(list)  # supply name -> shape ids
        self.shapes = []  # (layer, datatype, geometry, owner)
        self.uf = UnionFind()
        self.diag = collections.Counter()
        self.notes = []
        self._pin_cache = {}
        self._run()

    # --- S1/S2 ---------------------------------------------------------------
    def _add_shape(self, layer, datatype, geom, owner):
        self.shapes.append((layer, datatype, geom, owner))
        return self.uf.add()

    def _instances_and_pins(self):
        tech = self.tech
        for ref in self.top.references:
            master = ref.cell.name
            is_std = master.startswith(tech.prefix)
            is_macro = master in tech.macro_prefixes
            if not (is_std or is_macro):
                continue
            rot = int(round(math.degrees(ref.rotation))) % 360
            orient = ORIENT.get((rot, bool(ref.x_reflection)))
            if orient is None or ref.magnification != 1:
                raise ValueError(f"unsupported transform on {master} at {ref.origin}")
            # DEF location = lower-left of the placed cell box (LEF SIZE, ORIGIN 0 0)
            w, h = (_dbu(v) for v in self.lef[master]["size"])
            ox, oy = _dbu(ref.origin[0]), _dbu(ref.origin[1])
            dx, dy = _ORIENT_OFFSET[orient]
            x = ox - (w if dx == "w" else h if dx == "h" else 0)
            y = oy - (w if dy == "w" else h if dy == "h" else 0)
            short = master[len(tech.prefix):] if is_std else master
            inst = {"name": f"{short}_{x}_{y}", "master": master, "x": x, "y": y, "orient": orient,
                    "gds_origin": (ox, oy), "macro": is_macro, "pins": collections.defaultdict(list)}
            if is_std:
                master_pins = self._master_pins(ref.cell)
            else:
                master_pins = self._macro_pins(ref.cell)
            for name, polys in master_pins.items():
                for q in polys:
                    q = gdstk.Polygon(q.points, q.layer, q.datatype)
                    q.transform(1, bool(ref.x_reflection), ref.rotation, ref.origin)
                    sid = self._add_shape(q.layer, q.datatype, _poly(q.points), ("pin", inst["name"], name))
                    inst["pins"][name].append(sid)
            self.instances.append(inst)

    def _join_master_islands(self, cell, layer_names, use_poly):
        """Shared core of `_master_pins`/`_macro_pins`: union-find conductor shapes
        of `cell` restricted to `layer_names` (Tech conductor names), optionally
        joined through the Tech's gate-poly + contact, then group by pin label.
        Returns {pin_name: [gdstk.Polygon in master/macro-cell coordinates]}."""
        tech = self.tech
        layers = {tech.conductor_named(n).layer: tech.conductor_named(n) for n in layer_names}
        polys = [p for p in cell.polygons if p.layer in layers and p.datatype in layers[p.layer].datatypes]
        geoms = [_poly(p.points) for p in polys]
        poly_layer = poly_start = None
        if use_poly and tech.poly_layer is not None:
            poly_layer, poly_dt = tech.poly_layer
            cuts = shapely.union_all(
                [_poly(p.points) for p in cell.polygons if tech.poly_resistor_cut and (p.layer, p.datatype) == tech.poly_resistor_cut]
            ) if tech.poly_resistor_cut else None
            poly_start = len(polys)
            for p in cell.polygons:
                if (p.layer, p.datatype) != (poly_layer, poly_dt):
                    continue
                g = _poly(p.points).difference(cuts) if cuts is not None else _poly(p.points)
                for part in getattr(g, "geoms", [g]):
                    if not part.is_empty:
                        polys.append(gdstk.Polygon(list(part.exterior.coords)[:-1], poly_layer, poly_dt))
                        geoms.append(part)
        uf = UnionFind()
        for _ in polys:
            uf.add()
        if not polys:
            return {}
        tree = shapely.STRtree(geoms)
        left, right = tree.query(geoms, predicate="intersects")
        for a, b in zip(left.tolist(), right.tolist()):
            if polys[a].layer == polys[b].layer and a != b:
                uf.union(a, b)
        # cuts that join two of `layer_names` to each other inside the cell (sky130:
        # mcon joins li1-met1); irrelevant (empty) for a single-layer pin_conductors
        for cut in tech.cuts:
            if cut.below not in layer_names or cut.above not in layer_names:
                continue
            below_l, above_l = tech.conductor_named(cut.below).layer, tech.conductor_named(cut.above).layer
            for c in cell.polygons:
                if (c.layer, c.datatype) != (cut.layer, cut.datatype):
                    continue
                hits = [h for h in tree.query(_poly(c.points), predicate="intersects").tolist()
                        if polys[h].layer in (below_l, above_l)]
                if {polys[h].layer for h in hits} >= {below_l, above_l}:
                    for h in hits[1:]:
                        uf.union(hits[0], h)
        # gate poly + contact joins poly to the lowest of `layer_names`
        if use_poly and tech.poly_layer is not None and tech.poly_cut is not None:
            lowest = tech.conductor_named(layer_names[0]).layer
            cut_l, cut_dt = tech.poly_cut
            for c in cell.polygons:
                if (c.layer, c.datatype) != (cut_l, cut_dt):
                    continue
                hits = [h for h in tree.query(_poly(c.points), predicate="intersects").tolist()
                        if polys[h].layer in (poly_layer, lowest)]
                if {polys[h].layer for h in hits} >= {poly_layer, lowest}:
                    for h in hits[1:]:
                        uf.union(hits[0], h)
        names = collections.defaultdict(set)
        for lb in cell.labels:
            c = layers.get(lb.layer)
            if c is None or lb.texttype != c.label_dt:
                continue
            idx = [i for i in tree.query(Point(lb.origin), predicate="intersects").tolist()
                   if polys[i].layer == lb.layer]
            if not idx:
                self.diag["pin_label_without_polygon"] += 1
                self.notes.append(f"{cell.name}: label {lb.text} covers no polygon")
                continue
            names[uf.find(idx[0])].add(lb.text)
        pins = collections.defaultdict(list)
        for root, labels in names.items():
            if len(labels) > 1 and not labels <= set(tech.supply_pins):
                self.diag["pin_component_multiple_labels"] += 1
                self.notes.append(f"{cell.name}: one conductor carries {sorted(labels)}")
            name = sorted(labels)[0]
            pins[name].extend(polys[i] for i in range(len(polys))
                               if uf.find(i) == root and (poly_layer is None or polys[i].layer != poly_layer))
        return dict(pins)

    def _master_pins(self, cell):
        """Pin geometry of a std-cell master, cached: {pin: [gdstk.Polygon in master
        coordinates]}. A pin is the whole conductor its label sits on *inside the
        cell*, per `Tech.pin_conductors`/`poly_layer`/`poly_cut`. See docs/STATUS.md
        (sky130) and docs/TEMPO_LVS.md (IHP) for the geometry findings behind this."""
        if cell.name in self._pin_cache:
            return self._pin_cache[cell.name]
        pins = self._join_master_islands(cell, self.tech.pin_conductors, use_poly=True)
        self._pin_cache[cell.name] = pins
        return pins

    def _macro_pins(self, cell):
        """Pin geometry of a macro instance (e.g. the TEMPO SRAM), cached by cell
        name: the macro's own top-level pin shapes/labels, across every conductor
        layer they may appear on. The macro's internal hierarchy is never flattened
        into chip nets (docs/TEMPO_LVS.md)."""
        key = ("macro", cell.name)
        if key in self._pin_cache:
            return self._pin_cache[key]
        all_layers = tuple(c.name for c in self.tech.conductors)
        pins = self._join_master_islands(cell, all_layers, use_poly=False)
        self._pin_cache[key] = pins
        return pins

    # --- S3 ------------------------------------------------------------------
    def _routing(self):
        tech = self.tech
        top = self.top
        cond_layers = tech.conductor_layers()
        for path in top.paths:
            for p in path.to_polygons():
                if tech.is_conductor_shape(p.layer, p.datatype):
                    self._add_shape(p.layer, p.datatype, _poly(p.points), ("route",))
        for p in top.polygons:
            if tech.is_conductor_shape(p.layer, p.datatype):
                self._add_shape(p.layer, p.datatype, _poly(p.points), ("poly",))
        cut_keys = {(c.layer, c.datatype): c for c in tech.cuts}
        self._cuts = []  # (Cut, geom, via_name); used internally by _connect()
        self.cuts = []  # (below_layer:int, geom, via_name); back-compat with
        #                 tools/retrace/mutate.py, which assumes (as sky130's own
        #                 numbering happens to allow) that the layer above a cut is
        #                 below_layer + 1. Only meaningful for SKY130_HD.
        for ref in top.references:
            if not ref.cell.name.startswith(tech.via_prefix):
                continue
            for p in ref.get_polygons():
                if tech.is_conductor_shape(p.layer, p.datatype):
                    self._add_shape(p.layer, p.datatype, _poly(p.points), ("via", ref.cell.name))
                elif (p.layer, p.datatype) in cut_keys:
                    cut = cut_keys[(p.layer, p.datatype)]
                    geom = _poly(p.points)
                    self._cuts.append((cut, geom, ref.cell.name))
                    self.cuts.append((tech.conductor_named(cut.below).layer, geom, ref.cell.name))
        max_label_dt = {c.label_dt for c in tech.conductors}
        for lb in top.labels:
            if lb.layer in cond_layers and lb.texttype in max_label_dt:
                self._pending_labels.append(lb)

    def _connect(self):
        tech = self.tech
        by_layer = collections.defaultdict(list)
        for sid, (layer, _dt, _g, _o) in enumerate(self.shapes):
            by_layer[layer].append(sid)
        self.trees = {}
        for layer, sids in by_layer.items():
            geoms = [self.shapes[s][2] for s in sids]
            tree = shapely.STRtree(geoms)
            self.trees[layer] = (tree, sids)
            left, right = tree.query(geoms, predicate="intersects")
            for a, b in zip(left.tolist(), right.tolist()):
                if a != b:
                    self.uf.union(sids[a], sids[b])
        for cut, geom, via in self._cuts:
            below_l, above_l = tech.conductor_named(cut.below).layer, tech.conductor_named(cut.above).layer
            hits = []
            for lyr in (below_l, above_l):
                if lyr not in self.trees:
                    continue
                tree, sids = self.trees[lyr]
                idx = tree.query(geom, predicate="intersects").tolist()
                if not idx:
                    self.diag[f"cut_open_{tech.conductor(lyr).name}_{via}"] += 1
                hits.extend(sids[i] for i in idx)
            for h in hits[1:]:
                self.uf.union(hits[0], h)

    def _bind_labels(self):
        tech = self.tech
        for lb in self._pending_labels:
            if lb.layer not in self.trees:
                continue
            tree, sids = self.trees[lb.layer]
            idx = tree.query(Point(lb.origin), predicate="intersects").tolist()
            if not idx:
                self.diag["label_unbound"] += 1
                self.notes.append(f"label {lb.text!r} on {tech.conductor(lb.layer).name} at {lb.origin} touches nothing")
                continue
            sid = sids[idx[0]]
            if lb.text in tech.supply_pins:
                self.supply_labels[lb.text].append(sid)
            else:
                if lb.text in self.ports and self.uf.find(self.ports[lb.text]) != self.uf.find(sid):
                    self.diag["port_label_conflict"] += 1
                self.ports[lb.text] = sid

    def _run(self):
        self._pending_labels = []
        self._instances_and_pins()
        self._routing()
        self._connect()
        self._bind_labels()
        self._join_pin_polygons()
        self._build_nets()

    # --- S4 ------------------------------------------------------------------
    def _join_pin_polygons(self):
        """All polygons of one pin label are one electrical node inside the cell."""
        for inst in self.instances:
            for pin, sids in inst["pins"].items():
                for s in sids[1:]:
                    self.uf.union(sids[0], s)

    def _build_nets(self):
        members2 = collections.defaultdict(lambda: {"pins": [], "ports": [], "supply": set(), "shapes": 0,
                                                    "layers": set(), "owners": collections.Counter()})
        for sid, (layer, _dt, _g, owner) in enumerate(self.shapes):
            m = members2[self.uf.find(sid)]
            m["shapes"] += 1
            m["layers"].add(self.tech.conductor(layer).name)
            m["owners"][owner[0]] += 1
        for inst in self.instances:
            for pin, sids in inst["pins"].items():
                members2[self.uf.find(sids[0])]["pins"].append((inst["name"], pin))
        for name, sid in self.ports.items():
            members2[self.uf.find(sid)]["ports"].append(name)
        for name, sids in self.supply_labels.items():
            for s in sids:
                members2[self.uf.find(s)]["supply"].add(name)
        self.nets = []
        for root, m in members2.items():
            m["pins"].sort()
            m["ports"].sort()
            m["root"] = root
            self.nets.append(m)
        # deterministic order: ports first by name, then by first pin
        self.nets.sort(key=lambda m: (0, m["ports"]) if m["ports"] else (1, m["pins"][:1], m["shapes"]))
        counter = 0
        for m in self.nets:
            if m["ports"]:
                m["name"] = m["ports"][0]
            elif m["supply"]:
                m["name"] = "/".join(sorted(m["supply"]))
            else:
                m["name"] = f"n{counter}"
                counter += 1
        self.net_of = {}
        for m in self.nets:
            for ip in m["pins"]:
                self.net_of[ip] = m["name"]

    # --- reports -------------------------------------------------------------
    def logic_instances(self):
        tech = self.tech
        return [i for i in self.instances
                if i.get("macro") or not i["master"][len(tech.prefix):].startswith(tech.physical_prefixes)]

    def summary(self):
        signal = [m for m in self.nets if not m["supply"] and any(p not in self.tech.supply_pins for _i, p in m["pins"])]
        return {
            "top": self.top.name,
            "instances": len(self.instances),
            "logic_instances": len(self.logic_instances()),
            "ports": sorted(self.ports),
            "nets": len(self.nets),
            "signal_nets": len(signal),
            "diagnostics": dict(self.diag),
        }

    def to_json(self):
        return {
            "summary": self.summary(),
            "instances": [{k: v for k, v in i.items() if k != "pins"} for i in self.instances],
            "nets": [{"name": m["name"], "pins": m["pins"], "ports": m["ports"], "supply": sorted(m["supply"]),
                      "shapes": m["shapes"], "layers": sorted(m["layers"])} for m in self.nets],
            "notes": self.notes,
        }

    def to_verilog(self, port_dirs=None, lef=None):
        """Structural Verilog of the logic instances (physical-only cells omitted)."""
        port_dirs = port_dirs or {}
        buses = collections.defaultdict(list)
        scalars = []
        for p in sorted(self.ports):
            if "[" in p:
                base, idx = p[:-1].split("[")
                buses[base].append(int(idx))
            else:
                scalars.append(p)
        decl = []
        for p in scalars:
            decl.append(f"  {port_dirs.get(p, 'inout')} {p};")
        for b, idxs in sorted(buses.items()):
            decl.append(f"  {port_dirs.get(b, 'inout')} [{max(idxs)}:{min(idxs)}] {b};")
        header = ", ".join(scalars + sorted(buses))
        lines = [f"// generated by tools/retrace/extract.py from {self.top.name}; do not edit",
                 f"module {self.top.name} ({header});", *decl]
        used = set()
        body = []
        for inst in sorted(self.logic_instances(), key=lambda i: i["name"]):
            conns = []
            pins = lef[inst["master"]]["pins"] if lef else {p: {"use": "SIGNAL"} for p in inst["pins"]}
            for pin in sorted(pins):
                if pin in self.tech.supply_pins:
                    continue
                net = self.net_of.get((inst["name"], pin))
                if net is None:
                    conns.append(f".{pin}()")
                    self.diag["pin_missing_geometry"] += 1
                    continue
                used.add(net)
                # a bus port bit is written as a bit-select (O[3]), never escaped
                ref = net if net in self.ports else _vname(net)
                conns.append(f".{pin}({ref})")
            body.append(f"  {inst['master']} {inst['name']} ({', '.join(conns)});")
        for net in sorted(used):
            if net not in self.ports:
                lines.append(f"  wire {_vname(net)};")
        lines += body
        lines.append("endmodule")
        return "\n".join(lines) + "\n"


def _vname(net):
    return net if net.replace("_", "").isalnum() else "\\" + net + " "


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("gds")
    ap.add_argument("--top")
    ap.add_argument("--lef", default="pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef")
    ap.add_argument("--verilog")
    ap.add_argument("--json")
    ap.add_argument("--inputs", default="", help="comma-separated input port base names")
    ap.add_argument("--outputs", default="", help="comma-separated output port base names")
    args = ap.parse_args(argv)
    from .lef import read_lef

    lef = read_lef(args.lef)
    ex = Extraction(args.gds, lef, args.top)
    dirs = {p: "input" for p in args.inputs.split(",") if p} | {p: "output" for p in args.outputs.split(",") if p}
    if args.verilog:
        with open(args.verilog, "w") as f:
            f.write(ex.to_verilog(dirs, lef))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(ex.to_json(), f, indent=1)
    json.dump(ex.summary(), sys.stdout, indent=1)
    print()
    for n in ex.notes[:20]:
        print("note:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
