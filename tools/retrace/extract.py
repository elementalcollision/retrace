"""RETRACE extractor 1: GDS (sky130_fd_sc_hd, OpenLane-style) to a cell-level netlist.

Stages (docs/spec/APPROACH.md):
  S1 instances   every sky130_fd_sc_hd reference: master, DEF-style lower-left, orientation
  S2 pins        per master, the li1/met1 conductor (x/20 joined by mcon 67/44) under
                 each pin label (67/5, 68/5)
  S3 nets        union-find over conductor shapes: li1/met1..met5 routing (paths and
                 polygons, datatypes 20 and 16), via-cell pads, cell pins; a cut shape
                 L/44 in a via cell joins the layers L and L+1 that it touches
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

PREFIX = "sky130_fd_sc_hd__"
LI1, MET5 = 67, 72
LAYER_NAMES = {67: "li1", 68: "met1", 69: "met2", 70: "met3", 71: "met4", 72: "met5"}
CONDUCTOR_DT = (20, 16)
CUT_DT = 44
LABEL_DT = 5
# masters with no signal pins or no logic function
PHYSICAL = ("tapvpwrvgnd", "decap", "fill", "diode")
SUPPLY_PINS = ("VPWR", "VGND", "VPB", "VNB")
ORIENT = {(0, False): "N", (0, True): "FS", (180, False): "S", (180, True): "FN"}


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
    """Result of extracting one GDS top cell."""

    def __init__(self, gds_path, lef, top=None):
        self.lef = lef
        self.lib = gdstk.read_gds(gds_path)
        tops = self.lib.top_level()
        self.top = next(c for c in tops if c.name == top) if top else tops[0]
        self.instances = []  # dicts: name, master, x, y (DBU lower-left), orient, pins{pin: shape ids}
        self.ports = {}  # port name -> shape id
        self.supply_labels = collections.defaultdict(list)  # VPWR/VGND -> shape ids
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
        for ref in self.top.references:
            master = ref.cell.name
            if not master.startswith(PREFIX):
                continue
            rot = int(round(math.degrees(ref.rotation))) % 360
            orient = ORIENT.get((rot, bool(ref.x_reflection)))
            if orient is None or ref.magnification != 1:
                raise ValueError(f"unsupported transform on {master} at {ref.origin}")
            # DEF location = lower-left of the placed cell box (LEF SIZE, ORIGIN 0 0)
            w, h = (_dbu(v) for v in self.lef[master]["size"])
            ox, oy = _dbu(ref.origin[0]), _dbu(ref.origin[1])
            x = ox - w if orient in ("S", "FN") else ox
            y = oy - h if orient in ("S", "FS") else oy
            short = master[len(PREFIX):]
            inst = {"name": f"{short}_{x}_{y}", "master": master, "x": x, "y": y,
                    "orient": orient, "pins": collections.defaultdict(list)}
            for name, polys in self._master_pins(ref.cell).items():
                for q in polys:
                    q = gdstk.Polygon(q.points, q.layer, q.datatype)
                    q.transform(1, bool(ref.x_reflection), ref.rotation, ref.origin)
                    sid = self._add_shape(q.layer, q.datatype, _poly(q.points), ("pin", inst["name"], name))
                    inst["pins"][name].append(sid)
            self.instances.append(inst)

    def _master_pins(self, cell):
        """Pin geometry of a master, cached: {pin: [gdstk.Polygon in master coordinates]}.

        A pin is the whole conductor that its label sits on *inside the cell*: li1 and
        met1 polygons (drawing x/20 and pin x/16) joined by the cell's mcon cuts (67/44).
        Many sky130 pins are a met1 strap over two li1 islands (e.g. xor2_2 B, dfrtp_2
        RESET_B), and routers land on the strap. On li1 the x/16 shapes are only small
        markers inside the drawing, but the supply rails exist only as met1 x/16."""
        if cell.name in self._pin_cache:
            return self._pin_cache[cell.name]
        polys = [p for p in cell.polygons if p.layer in (LI1, LI1 + 1) and p.datatype in CONDUCTOR_DT]
        geoms = [_poly(p.points) for p in polys]
        uf = UnionFind()
        for _ in polys:
            uf.add()
        tree = shapely.STRtree(geoms)
        left, right = tree.query(geoms, predicate="intersects")
        for a, b in zip(left.tolist(), right.tolist()):
            if polys[a].layer == polys[b].layer and a != b:
                uf.union(a, b)
        for cut in cell.polygons:
            if (cut.layer, cut.datatype) != (LI1, CUT_DT):
                continue
            hits = tree.query(_poly(cut.points), predicate="intersects").tolist()
            for h in hits[1:]:
                uf.union(hits[0], h)
        names = collections.defaultdict(set)
        for lb in cell.labels:
            if lb.texttype != LABEL_DT or lb.layer not in (LI1, LI1 + 1):
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
            if len(labels) > 1 and not labels <= set(SUPPLY_PINS):
                self.diag["pin_component_multiple_labels"] += 1
                self.notes.append(f"{cell.name}: one conductor carries {sorted(labels)}")
            name = sorted(labels)[0]
            pins[name].extend(polys[i] for i in range(len(polys)) if uf.find(i) == root)
        self._pin_cache[cell.name] = dict(pins)
        return self._pin_cache[cell.name]

    # --- S3 ------------------------------------------------------------------
    def _routing(self):
        top = self.top
        for path in top.paths:
            for p in path.to_polygons():
                if LI1 <= p.layer <= MET5 and p.datatype in CONDUCTOR_DT:
                    self._add_shape(p.layer, p.datatype, _poly(p.points), ("route",))
        for p in top.polygons:
            if LI1 <= p.layer <= MET5 and p.datatype in CONDUCTOR_DT:
                self._add_shape(p.layer, p.datatype, _poly(p.points), ("poly",))
        self.cuts = []
        for ref in top.references:
            if not ref.cell.name.startswith("VIA"):
                continue
            for p in ref.get_polygons():
                if LI1 <= p.layer <= MET5 and p.datatype in CONDUCTOR_DT:
                    self._add_shape(p.layer, p.datatype, _poly(p.points), ("via", ref.cell.name))
                elif LI1 <= p.layer < MET5 and p.datatype == CUT_DT:
                    self.cuts.append((p.layer, _poly(p.points), ref.cell.name))
        for lb in top.labels:
            if lb.texttype == LABEL_DT and LI1 <= lb.layer <= MET5:
                self._pending_labels.append(lb)

    def _connect(self):
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
        for layer, cut, via in self.cuts:
            hits = []
            for lyr in (layer, layer + 1):
                if lyr not in self.trees:
                    continue
                tree, sids = self.trees[lyr]
                idx = tree.query(cut, predicate="intersects").tolist()
                if not idx:
                    self.diag[f"cut_open_{LAYER_NAMES[lyr]}_{via}"] += 1
                hits.extend(sids[i] for i in idx)
            for h in hits[1:]:
                self.uf.union(hits[0], h)

    def _bind_labels(self):
        for lb in self._pending_labels:
            if lb.layer not in self.trees:
                continue
            tree, sids = self.trees[lb.layer]
            idx = tree.query(Point(lb.origin), predicate="intersects").tolist()
            if not idx:
                self.diag["label_unbound"] += 1
                self.notes.append(f"label {lb.text!r} on {LAYER_NAMES[lb.layer]} at {lb.origin} touches nothing")
                continue
            sid = sids[idx[0]]
            if lb.text in SUPPLY_PINS:
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
            m["layers"].add(LAYER_NAMES[layer])
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
        return [i for i in self.instances if not i["master"][len(PREFIX):].startswith(PHYSICAL)]

    def summary(self):
        signal = [m for m in self.nets if not m["supply"] and any(p not in SUPPLY_PINS for _i, p in m["pins"])]
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
                if pin in SUPPLY_PINS:
                    continue
                net = self.net_of.get((inst["name"], pin))
                if net is None:
                    conns.append(f".{pin}()")
                    self.diag["pin_missing_geometry"] += 1
                    continue
                used.add(net)
                conns.append(f".{pin}({_vname(net)})")
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
