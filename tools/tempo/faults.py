"""Planted faults for the TEMPO LVS (docs/TEMPO_LVS.md 4e): the negative controls that
show each check can fail, kept as tests so TEMPO's CI re-runs them on every sign-off.

Six faults, one per failure class, are planted far apart in a single copy of the
sign-off GDS, so the whole set costs one extra extraction:

  via_open    the only Via1 on a logic cell's output pin removed (the loads lose their driver)
  mirror      a logic cell mirrored in place (N -> FN), same footprint
  bridge      a Metal2 rectangle joining two driven signal nets across a gap
  sram_swap   the SRAM macro's A_DIN<15> / A_BIST_DIN<15> labels exchanged
  supply_short a Metal1 bar from rail to rail inside one fill_2 (VDD-VSS short)
  rail_open   every via stack removed from one VDD rail (power open)

Sites are chosen by rule from the base extraction, never by index, so a new sign-off
GDS gets equivalent sites. Each fault records the DEF instances it touches (its
neighbourhood), and the neighbourhoods are pairwise disjoint, so a test can require
every check to report its own fault and nothing else.
"""

import math

import gdstk
import shapely
from shapely.geometry import LineString, box
from shapely.ops import nearest_points

SRAM = "RM_IHPSG13_1P_1024x32_c2_bm_bist"
SRAM_SWAP = ("A_DIN<15>", "A_BIST_DIN<15>")
METAL1, METAL2 = 8, 10  # IHP GDS layers (tech.IHP_SG13CMOS5L)
# one horizontal band of the die (1289 x 711 um) per fault, in um, so the sites sit
# far apart; the SRAM macro covers x 912-1249, y 147-564
BANDS = {"via_open": (20, 140), "mirror": (150, 270), "bridge": (290, 410),
         "supply_short": (430, 550), "rail_open": (570, 690)}


class _Base:
    """Lookups over the base (unmutated) extraction."""

    def __init__(self, ex, lef, name_map):
        self.ex, self.lef, self.name_map = ex, lef, name_map
        self.nets = {m["root"]: m for m in ex.nets}
        self.by_name = {i["name"]: i for i in ex.instances}
        self.supply = set()
        for inst in ex.instances:
            pins = lef.get(inst["master"], {}).get("pins", {})
            for pin, sids in inst["pins"].items():
                if pins.get(pin, {}).get("use") in ("POWER", "GROUND"):
                    self.supply.add(ex.uf.find(sids[0]))

    def use(self, master, pin):
        return self.lef.get(master, {}).get("pins", {}).get(pin, {}).get("use")

    def direction(self, master, pin):
        return self.lef.get(master, {}).get("pins", {}).get(pin, {}).get("direction")

    def hits(self, layer, geom):
        tree, sids = self.ex.trees[layer]
        return [sids[i] for i in tree.query(geom, predicate="intersects").tolist()]

    def root(self, sid):
        return self.ex.uf.find(sid)

    def neighbourhood(self, roots, extra=()):
        """DEF names of every instance with a pin on one of `roots`, plus `extra`."""
        gds = {i for r in roots for i, _p in self.nets[r]["pins"]} | set(extra)
        return {self.name_map[g] for g in gds if g in self.name_map}

    def driven(self, root):
        return any(self.direction(self.by_name[i]["master"], p) == "OUTPUT"
                   for i, p in self.nets[root]["pins"])


def _in_band(y, band):
    return band[0] <= y <= band[1]


def _via_pads(base):
    """STRtree over the Metal1 pad of every via reference in the top cell, keyed by
    (via name, origin x, origin y) so `plant` can find the reference again."""
    local = {}
    geoms, keys = [], []
    for ref in base.ex.top.references:
        name = ref.cell.name
        if not name.startswith(base.ex.tech.via_prefix):
            continue
        if ref.rotation == 0 and not ref.x_reflection and ref.magnification == 1:
            if name not in local:
                local[name] = [p.points for p in ref.cell.polygons if (p.layer, p.datatype) == (METAL1, 0)]
            ox, oy = ref.origin
            polys = [pts + (ox, oy) for pts in local[name]]
        else:
            polys = [p.points for p in ref.get_polygons(layer=METAL1, datatype=0)]
        for pts in polys:
            geoms.append(shapely.Polygon(pts))
            keys.append((name, round(ref.origin[0], 4), round(ref.origin[1], 4)))
    return shapely.STRtree(geoms), geoms, keys


def _pick_via_open(base, pads, taken):
    tree, geoms, keys = pads
    band = BANDS["via_open"]
    for inst in sorted(base.ex.instances, key=lambda i: (i["y"], i["x"])):
        if inst["macro"] or "tie" in inst["master"] or not _in_band(inst["y"] / 1000, band):
            continue
        for pin, sids in sorted(inst["pins"].items()):
            if base.direction(inst["master"], pin) != "OUTPUT":
                continue
            pin_geoms = [base.ex.shapes[s][2] for s in sids]
            pad_idx = sorted({j for g in pin_geoms for j in tree.query(g, predicate="intersects").tolist()})
            if len(pad_idx) != 1 or not keys[pad_idx[0]][0].startswith("VIA_Via1_"):
                continue
            root = base.root(sids[0])
            net = base.nets[root]
            if root in base.supply or len(net["pins"]) < 2 or net["ports"]:
                continue
            hood = base.neighbourhood([root])
            if hood & taken:
                continue
            name, x, y = keys[pad_idx[0]]
            return {"kind": "via_open", "via": name, "at": (x, y), "neighbourhood": hood,
                    "where": f"{name} at ({x}, {y}) um on output {inst['name']}.{pin}"}
    raise LookupError("no via_open site")


def _mirror_transform(ref, cx):
    """Mirror a placed reference about the vertical line x = cx (its own centre):
    rotation r -> pi - r, x_reflection toggled, origin x -> 2 cx - x."""
    ref.rotation = math.pi - ref.rotation
    ref.x_reflection = not ref.x_reflection
    ref.origin = (2 * cx - ref.origin[0], ref.origin[1])


def _pick_mirror(base, pads, taken):
    tree, _geoms, keys = pads
    band = BANDS["mirror"]
    for inst in sorted(base.ex.instances, key=lambda i: (i["y"], i["x"])):
        master = inst["master"]
        if (inst["macro"] or inst["orient"] != "N" or not _in_band(inst["y"] / 1000, band)
                or master.startswith(tuple(base.ex.tech.prefix + p for p in base.ex.tech.physical_prefixes))
                or "tie" in master):
            continue
        signal = [p for p in inst["pins"] if base.use(master, p) not in ("POWER", "GROUND")]
        if len(signal) < 3:
            continue
        roots = {base.root(inst["pins"][p][0]) for p in signal}
        if roots & base.supply:
            continue
        # the mirrored VDD/VSS geometry must not land on a signal via (that would
        # tie a signal net to a supply and blur the supply faults)
        w = base.lef[master]["size"][0]
        x0, y0 = inst["x"] / 1000, inst["y"] / 1000
        mirrored = [box(x0 + w - rx1, y0 + ry0, x0 + w - rx0, y0 + ry1)
                    for p in ("VDD", "VSS") for _l, rx0, ry0, rx1, ry1 in base.lef[master]["pins"][p]["rects"]]
        if any(keys[j][0].startswith("VIA_Via1_") for g in mirrored
               for j in tree.query(g, predicate="intersects").tolist()):
            continue
        hood = base.neighbourhood(roots, extra=[inst["name"]])
        if hood & taken:
            continue
        return {"kind": "mirror", "instance": inst["name"], "master": master,
                "origin": inst["gds_origin"], "cx": x0 + w / 2, "neighbourhood": hood,
                "def_name": base.name_map[inst["name"]],
                "where": f"{inst['name']} ({base.name_map[inst['name']]}) mirrored N -> FN in place"}
    raise LookupError("no mirror site")


def _pick_bridge(base, taken):
    band = BANDS["bridge"]
    tree, sids = base.ex.trees[METAL2]
    routes = [s for s in sids if base.ex.shapes[s][3][0] == "route"
              and _in_band(base.ex.shapes[s][2].centroid.y, band)]
    routes.sort(key=lambda s: (round(base.ex.shapes[s][2].centroid.y, 3), round(base.ex.shapes[s][2].centroid.x, 3)))
    for a in routes:
        ga = base.ex.shapes[a][2]
        ra = base.root(a)
        if ra in base.supply or not base.driven(ra):
            continue
        for j in tree.query(ga.buffer(0.3)).tolist():
            b = sids[j]
            gb = base.ex.shapes[b][2]
            rb = base.root(b)
            if rb == ra or rb in base.supply or not base.driven(rb):
                continue
            gap = ga.distance(gb)
            if not 0.05 < gap < 0.3:
                continue
            pa, pb = nearest_points(ga, gb)
            bridge = LineString([pa, pb]).buffer(0.08, cap_style="square")
            if {base.root(s) for s in base.hits(METAL2, bridge)} != {ra, rb}:
                continue
            hood = base.neighbourhood([ra, rb])
            if hood & taken:
                continue
            return {"kind": "bridge", "polygon": list(bridge.exterior.coords), "neighbourhood": hood,
                    "where": f"Metal2 bridge at ({pa.x:.3f}, {pa.y:.3f}) um across a {gap:.3f} um gap"}
    raise LookupError("no bridge site")


def _pick_sram_swap(base, taken):
    inst = next(i for i in base.ex.instances if i["master"] == SRAM)
    roots = {base.root(inst["pins"][p][0]) for p in SRAM_SWAP}
    hood = base.neighbourhood(roots, extra=[inst["name"]])
    if hood & taken:
        raise LookupError("sram_swap neighbourhood overlaps another fault")
    return {"kind": "sram_swap", "neighbourhood": hood,
            "where": f"{SRAM} labels {SRAM_SWAP[0]} and {SRAM_SWAP[1]} exchanged"}


def _pick_supply_short(base):
    """A Metal1 bar, 0.36 um wide, from rail to rail through the middle of a filler
    cell (no signal geometry inside), preferring the fault's band."""
    band = BANDS["supply_short"]
    fillers = [i for i in base.ex.instances
               if i["master"].startswith(base.ex.tech.prefix + "fill_") and i["orient"] in ("N", "FS")]
    fillers.sort(key=lambda i: (not _in_band(i["y"] / 1000, band), i["y"], i["x"]))
    for inst in fillers:
        w, h = base.lef[inst["master"]]["size"]
        x, y = inst["x"] / 1000, inst["y"] / 1000
        bar = box(x + w / 2 - 0.18, y + 0.05, x + w / 2 + 0.18, y + h - 0.05)
        roots = {base.root(s) for s in base.hits(METAL1, bar)}
        if len(roots) == 2 and roots <= base.supply:
            return {"kind": "supply_short", "rect": bar.bounds, "instance": inst["name"],
                    "where": f"Metal1 bar rail to rail inside {inst['name']}"}
    raise LookupError("no supply_short site")


def _pick_rail_open(base, pads, power_root):
    tree, _geoms, keys = pads
    band = BANDS["rail_open"]
    rails = []
    for s, (layer, _dt, g, owner) in enumerate(base.ex.shapes):
        if layer == METAL1 and owner[0] == "route" and _in_band(g.centroid.y, band):
            x0, y0, x1, y1 = g.bounds
            if x1 - x0 > 50 and base.root(s) == power_root:
                rails.append((s, g))
    rails.sort(key=lambda sg: (round(sg[1].centroid.y, 3), -sg[1].length))
    for s, g in rails:
        vias = [keys[j] for j in tree.query(g, predicate="intersects").tolist()]
        stray = set()
        for h in base.hits(METAL1, g):
            owner = base.ex.shapes[h][3]
            if owner[0] == "pin" and base.use(base.by_name[owner[1]]["master"], owner[2]) == "POWER":
                stray.add(owner[1])
        if vias and stray:
            x0, y0, x1, y1 = g.bounds
            return {"kind": "rail_open", "vias": vias, "stray": stray,
                    "neighbourhood": {base.name_map[i] for i in stray if i in base.name_map},
                    "where": f"{len(vias)} via stacks removed from the VDD rail at y = {(y0 + y1) / 2:.3f} um "
                             f"({len(stray)} instances on it)"}
    raise LookupError("no rail_open site")


def choose(ex, lef, name_map):
    """Pick the six sites on the base extraction. Returns {kind: fault record}."""
    base = _Base(ex, lef, name_map)
    pads = _via_pads(base)
    faults, taken = {}, set()
    for kind, pick in (("sram_swap", lambda: _pick_sram_swap(base, taken)),
                       ("via_open", lambda: _pick_via_open(base, pads, taken)),
                       ("mirror", lambda: _pick_mirror(base, pads, taken)),
                       ("bridge", lambda: _pick_bridge(base, taken))):
        faults[kind] = pick()
        taken |= faults[kind]["neighbourhood"]
    faults["supply_short"] = _pick_supply_short(base)
    power = {r for r in base.supply
             if any(base.use(base.by_name[i]["master"], p) == "POWER" for i, p in base.nets[r]["pins"])}
    if len(power) != 1:
        raise ValueError(f"base design has {len(power)} power nets, expected 1")
    faults["rail_open"] = _pick_rail_open(base, pads, next(iter(power)))
    return faults


def plant(faults, src_gds, out_gds, top_name):
    """Write a copy of `src_gds` with every fault in `faults` planted."""
    lib = gdstk.read_gds(src_gds)
    top = next(c for c in lib.top_level() if c.name == top_name)
    cells = {c.name: c for c in lib.cells}

    def via_ref(name, at):
        for ref in top.references:
            if ref.cell.name == name and abs(ref.origin[0] - at[0]) < 1e-3 and abs(ref.origin[1] - at[1]) < 1e-3:
                return ref
        raise LookupError(f"no {name} at {at}")

    top.remove(via_ref(faults["via_open"]["via"], faults["via_open"]["at"]))
    for name, x, y in faults["rail_open"]["vias"]:
        top.remove(via_ref(name, (x, y)))
    m = faults["mirror"]
    ox, oy = (v / 1000 for v in m["origin"])
    ref = next(r for r in top.references if r.cell.name == m["master"]
               and abs(r.origin[0] - ox) < 1e-3 and abs(r.origin[1] - oy) < 1e-3)
    _mirror_transform(ref, m["cx"])
    top.add(gdstk.Polygon(faults["bridge"]["polygon"], layer=METAL2, datatype=0))
    x0, y0, x1, y1 = faults["supply_short"]["rect"]
    top.add(gdstk.rectangle((x0, y0), (x1, y1), layer=METAL1, datatype=0))
    a, b = SRAM_SWAP
    for lb in cells[SRAM].labels:
        if lb.text in (a, b):
            lb.text = b if lb.text == a else a
    lib.write_gds(out_gds)


def main(argv=None):
    """Write the planted copy for inspection: python -m tools.tempo.faults OUT.gds"""
    import sys

    from ..retrace.defparse import read_def
    from . import lvs

    out = (argv or sys.argv[1:] or ["out/tempo/tempo_faults.gds"])[0]
    lef = lvs.load_lef()
    ex, _dt, _mb = lvs.extract_tempo(lef=lef)
    name_map, _ = lvs.map_to_def(ex, read_def(lvs.DEF)["components"])
    chosen = choose(ex, lef, name_map)
    plant(chosen, lvs.GDS, out, lvs.TOP)
    for kind, f in chosen.items():
        print(f"{kind:13s} {f['where']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
