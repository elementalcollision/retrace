"""RETRACE x TEMPO: an LVS of TEMPO's sign-off GDS against its own DEF/netlist,
independent of LibreLane's Magic/Netgen flow (PRD G6, docs/TEMPO_LVS.md).

Extracts `tt_um_elementalcollision_tempo.gds` with `tools.retrace.extract`
under `tech.IHP_SG13CMOS5L`, then checks it six ways against TEMPO's own
files (all read-only, under $TEMPO_ROOT, default ~/Claude_Primary/Jane_Street_ASIC):

  (a) placements   GDS instances <-> DEF COMPONENTS, by (master, x, y, orient);
                    also builds the GDS-name -> DEF-name map every other check uses
  (b) net partition GDS-extracted (instance, pin) groups <-> DEF NETS, exact
  (c) net partition GDS-extracted (instance, pin) groups <-> nl.v connections, exact
  (d) pins          every master used, GDS-derived pin names <-> IHP LEF pin names
  (d2) pin geometry every LEF port rectangle lies on the extracted pin of the same name
  (e) sanity        one driver per signal net, no floating inputs, supplies separate
  (f) cellcheck     every std-cell master embedded in the GDS <-> the PDK's own cell GDS

Run standalone:  .venv/bin/python -m tools.tempo.lvs
"""

import os
import collections
import json
import re
import resource
import sys
import time

from ..retrace import cellcheck
from ..retrace.defparse import read_def
from ..retrace.extract import Extraction
from ..retrace.lef import read_lef
from ..retrace.tech import IHP_SG13CMOS5L

# the TEMPO checkout and the IHP PDK; override with environment variables
TEMPO_ROOT = os.environ.get("TEMPO_ROOT", os.path.expanduser("~/Claude_Primary/Jane_Street_ASIC"))
IHP_PDK = os.environ.get("IHP_PDK", os.path.expanduser("~/ttsetup/pdk/ihp-sg13cmos5l"))
GDS = f"{TEMPO_ROOT}/runs/wokwi/final/gds/tt_um_elementalcollision_tempo.gds"
DEF = f"{TEMPO_ROOT}/runs/wokwi/final/def/tt_um_elementalcollision_tempo.def"
NL_V = f"{TEMPO_ROOT}/runs/wokwi/final/nl/tt_um_elementalcollision_tempo.nl.v"
STDCELL_LEF = f"{IHP_PDK}/libs.ref/sg13cmos5l_stdcell/lef/sg13cmos5l_stdcell.lef"
STDCELL_GDS = f"{IHP_PDK}/libs.ref/sg13cmos5l_stdcell/gds/sg13cmos5l_stdcell.gds"
MACRO_LEF = f"{TEMPO_ROOT}/macro/RM_IHPSG13_1P_1024x32_c2_bm_bist/RM_IHPSG13_1P_1024x32_c2_bm_bist.lef"
TOP = "tt_um_elementalcollision_tempo"


def load_lef():
    lef = read_lef(STDCELL_LEF)
    lef.update(read_lef(MACRO_LEF))
    return lef


def extract_tempo(gds=GDS, lef=None, top=TOP):
    """Run extractor 1 on TEMPO's sign-off GDS with IHP_SG13CMOS5L. Returns
    (Extraction, elapsed_seconds, peak_rss_mb)."""
    lef = lef if lef is not None else load_lef()
    t0 = time.time()
    ex = Extraction(gds, lef, top, tech=IHP_SG13CMOS5L)
    dt = time.time() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mb = rss / 1e6 if sys.platform == "darwin" else rss / 1e3  # bytes on macOS, KiB on Linux
    return ex, dt, peak_mb


# --- (a) placements --------------------------------------------------------

def map_to_def(ex, def_components):
    """Map every extracted GDS instance to its DEF instance name, by exact
    (master, x, y, orient) match (DBU). Physical-only cells (fill/decap/
    antenna) are included: DEF has them too, and check (a) must cover the
    full placement, not just logic. Returns (name_map, report):
      name_map: {gds_inst_name: def_inst_name}
      report: {"gds_total", "def_total", "matched", "only_gds": [...], "only_def": [...],
                "ambiguous": [gds_inst_name, ...]}  -- ambiguous: >1 DEF component
                shares that (master, x, y, orient) key (ties broken arbitrarily,
                still "matched" for count purposes, but flagged).
    """
    by_key = collections.defaultdict(list)
    for dname, (master, x, y, orient) in def_components.items():
        by_key[(master, x, y, orient)].append(dname)
    name_map, ambiguous = {}, []
    only_gds = []
    used = collections.Counter()
    for inst in ex.instances:
        key = (inst["master"], inst["x"], inst["y"], inst["orient"])
        cands = by_key.get(key)
        if not cands:
            only_gds.append(inst["name"])
            continue
        i = used[key]
        used[key] += 1
        if i >= len(cands):
            only_gds.append(inst["name"])
            continue
        if len(cands) > 1:
            ambiguous.append(inst["name"])
        name_map[inst["name"]] = cands[i]
    matched_def = set(name_map.values())
    only_def = [d for d in def_components if d not in matched_def]
    report = {
        "gds_total": len(ex.instances),
        "def_total": len(def_components),
        "matched": len(name_map),
        "only_gds": only_gds,
        "only_def": only_def,
        "ambiguous": ambiguous,
    }
    return name_map, report


# --- (b)/(c) net partitions -------------------------------------------------

def gds_partition(ex, name_map, lef, min_size=2):
    """{net_root: frozenset[(def_inst_name, pin), ...]} for every extracted net
    with at least `min_size` (instance, pin) connections, including top-level
    ports as ("PIN", port_name) -- matching DEF NETS' own convention. Bus-bit
    pin names are normalised `<n>` -> `[n]` (cosmetic GDS-label-vs-LEF-pin
    difference, verified on the SRAM macro, docs/TEMPO_LVS.md). Unmapped
    instances (see report["only_gds"]) are excluded. Nets below `min_size` are
    single-pin (a dangling/unloaded output, e.g. a CTS dummy load) and DEF's
    own NETS section does not list them either (docs/TEMPO_LVS.md); the caller
    reports their count separately rather than silently dropping a mismatch."""
    # Any net that a POWER/GROUND-use LEF pin touches -- a std cell's VDD/VSS pin,
    # an antenna diode's substrate-tap "VSS" pin, or the SRAM macro's VDD!/VSS!/
    # VDDARRAY! -- is global power, not a signal net, once union-find has merged
    # it with the physical strap. (`ex.supply_labels`/`net["supply"]` only catches
    # a *standalone top-level* VDD/VSS text label, which this GDS does not have --
    # TEMPO's power distribution is per-cell pins wired to the strap, with no bare
    # label of its own.) DEF's regular NETS section and nl.v's module body do not
    # enumerate power connectivity (that is DEF SPECIALNETS, which this check does
    # not read), so these nets have no DEF/nl.v counterpart by construction;
    # excluded here and counted, not silently dropped
    # (report["b_def_nets"]["gds_supply_pins_excluded"]).
    power_pin = lambda master, pin: lef.get(master, {}).get("pins", {}).get(pin, {}).get("use") in ("POWER", "GROUND")
    supply_root = set()
    for inst in ex.instances:
        for pin, sids in inst["pins"].items():
            if power_pin(inst["master"], pin):
                supply_root.add(ex.uf.find(sids[0]))
    parts = collections.defaultdict(set)
    excluded = 0
    for inst in ex.instances:
        dname = name_map.get(inst["name"])
        if dname is None:
            continue
        for pin, sids in inst["pins"].items():
            root = ex.uf.find(sids[0])
            if root in supply_root:
                excluded += 1
                continue
            parts[root].add((dname, _norm_bus(pin)))
    for name, sid in ex.ports.items():
        root = ex.uf.find(sid)
        if root in supply_root:
            continue
        parts[root].add(("PIN", name))
    result = {root: frozenset(pins) for root, pins in parts.items() if len(pins) >= min_size}
    gds_partition.last_excluded_supply_pins = excluded  # cheap out-of-band report field
    return result


def def_net_partition(def_data, min_size=2):
    """{net_name: frozenset[(inst, pin)]} from DEF NETS, PIN entries kept as
    ("PIN", portname)."""
    return {n: frozenset((i, p) for i, p in conns) for n, conns in def_data["nets"].items()
            if len(conns) >= min_size}


_BUS_BIT = re.compile(r"^(.*)\[(\d+)\]$")
_INST_RE = re.compile(r"(?m)^\s*(\\?[\w.$]+)\s+(\\?[^\s(]+?)\s*\((.*?)\);", re.S)
_PORT_RE = re.compile(r"\.(\w+)\s*\(([^()]*)\)")
_KEYWORDS = {"module", "input", "output", "inout", "wire", "assign", "endmodule", "parameter"}


def parse_nl_verilog(path):
    """Structural Verilog (one `module`, no assigns/constants -- true of TEMPO's
    nl.v): {inst_name: (master, {port_name: net_or_'{concat,list}'})}. `inst_name`
    is DEF-style already (nl.v uses the same names as DEF, confirmed on TEMPO)."""
    text = open(path).read()
    insts = {}
    for m in _INST_RE.finditer(text):
        master, iname, body = m.group(1), m.group(2), m.group(3)
        if master in _KEYWORDS:
            continue
        conns = {}
        for pm in _PORT_RE.finditer(body):
            conns[pm.group(1)] = re.sub(r"\s+", "", pm.group(2))
        # Verilog escaped identifiers (\name, terminated by whitespace) carry
        # characters DEF/LEF simple names can't (e.g. hierarchical dots); DEF's
        # own name for the same instance has no leading backslash.
        insts[iname.lstrip("\\")] = (master, conns)
    return insts


def _expand_nl_pins(master, conns, lef):
    """Expand nl.v's per-bus-port connections (e.g. `.A_ADDR({net6600,...})`) into
    per-LEF-pin-bit connections (`A_ADDR[9]`), matching the GDS/LEF pin naming.
    Concatenation order is MSB..LSB (Yosys `write_verilog` convention), matching
    descending-index LEF pin declaration order, which IHP's LEF follows."""
    out = {}
    lef_pins = lef.get(master, {}).get("pins", {})
    bus_bits = collections.defaultdict(list)
    for p in lef_pins:
        m = _BUS_BIT.match(p)
        if m:
            bus_bits[m.group(1)].append(int(m.group(2)))
    for base in bus_bits:
        bus_bits[base].sort(reverse=True)
    for pin, expr in conns.items():
        if expr.startswith("{") and expr.endswith("}") and pin in bus_bits:
            nets = expr[1:-1].split(",")
            bits = bus_bits[pin]
            if len(nets) == len(bits):
                for bit, net in zip(bits, nets):
                    out[f"{pin}[{bit}]"] = net
                continue
        out[pin] = expr
    return out


def nlv_partition(nlv_insts, name_map, lef, ports, min_size=2):
    """{def_net_expr: frozenset[(inst, pin)]} built the same way as
    `def_net_partition`, but keyed by nl.v's own net token (so it is only ever
    compared to itself, never to DEF/GDS net names -- Q3/net-naming is not what
    this check is about). `ports` are the extractor's top-level port names:
    structural Verilog uses the port name itself as the net token for any cell
    tied straight to a port, with no separate "this is a chip pin" marker, so a
    synthetic ("PIN", name) member is added wherever the net token is a port
    name -- matching DEF NETS'/`gds_partition`'s convention."""
    parts = collections.defaultdict(set)
    reverse_map = {d: g for g, d in name_map.items()}
    for iname, (master, conns) in nlv_insts.items():
        if iname not in reverse_map:
            continue  # instance not extracted from GDS (see report["nl_only"])
        for pin, net in _expand_nl_pins(master, conns, lef).items():
            parts[net].add((iname, pin))
    for net in list(parts):
        if net in ports:
            parts[net].add(("PIN", net))
    return {net: frozenset(pins) for net, pins in parts.items() if len(pins) >= min_size}


def compare_partitions(a, b):
    """Two {key: frozenset[(inst,pin)]} partitions of the same universe of
    (inst,pin) pairs are the same partition iff their *sets of parts* match,
    independent of key/net naming. Returns a report; empty `only_a`/`only_b`
    means exact agreement."""
    sa, sb = set(a.values()), set(b.values())
    return {"parts_a": len(sa), "parts_b": len(sb), "only_a": len(sa - sb), "only_b": len(sb - sa),
            "agree": sa == sb}


# --- (d) pins vs LEF ---------------------------------------------------------

def _norm_bus(name):
    """GDS/extractor pin/label names for a bus bit use `<n>`; LEF/Verilog use
    `[n]`. Cosmetic only (verified equal geometry/count on the SRAM macro)."""
    return name.replace("<", "[").replace(">", "]")


def check_pins_vs_lef(ex, lef):
    by_master = collections.defaultdict(set)
    for inst in ex.instances:
        by_master[inst["master"]].add(frozenset(_norm_bus(p) for p in inst["pins"]))
    report = {}
    for master, pinsets in by_master.items():
        lef_pins = {_norm_bus(p) for p in lef.get(master, {}).get("pins", {})}
        bad = [sorted(ps) for ps in pinsets if ps != frozenset(lef_pins)]
        report[master] = {"instances": sum(1 for i in ex.instances if i["master"] == master),
                           "lef_pins": len(lef_pins), "mismatched_instances": len(bad),
                           "example_mismatch": bad[0] if bad else None}
    return report


def _pin_geometry(ex, cell, is_macro):
    """{normalised pin name: {gds layer: [shapely Polygon]}} in master coordinates,
    from the extractor's own per-master pin conductors (so this tests exactly what
    the extraction uses)."""
    from shapely.geometry import Polygon

    pins = ex._macro_pins(cell) if is_macro else ex._master_pins(cell)
    geo = collections.defaultdict(lambda: collections.defaultdict(list))
    for name, polys in pins.items():
        for q in polys:
            geo[_norm_bus(name)][q.layer].append(Polygon(q.points))
    return geo


def check_pin_geometry_vs_lef(ex, lef, cells=None, only=None):
    """(d2) Pin geometry against the LEF, per master: the centre of every LEF port
    rectangle of a signal pin must lie on the extracted conductor of the *same* pin,
    on the same layer, and on no other pin's. Closes the blind spot of (d), which
    compares only name sets and so passes two swapped labels (docs/TEMPO_LVS.md 4c).
    LEF `ORIGIN 0 0` / `FOREIGN 0 0` for every master used, so LEF and GDS master
    coordinates coincide. `cells` overrides the GDS cells looked up by name and `only`
    limits the masters checked (negative controls)."""
    import shapely
    from shapely.geometry import Point, box

    cells = cells or {c.name: c for c in ex.lib.cells}
    masters = sorted({i["master"] for i in ex.instances} if only is None else only)
    report = {}
    for master in masters:
        cell = cells.get(master)
        pins_lef = lef.get(master, {}).get("pins", {})
        if cell is None or not pins_lef:
            continue
        geo = _pin_geometry(ex, cell, master in ex.tech.macro_prefixes)
        index = {}  # gds layer -> (STRtree over that layer's pin polygons, pin name per polygon)
        for layer in {lyr for by_layer in geo.values() for lyr in by_layer}:
            polys = [(p, g) for p, by_layer in geo.items() for g in by_layer.get(layer, [])]
            index[layer] = (shapely.STRtree([g for _p, g in polys]), [p for p, _g in polys])
        checked, bad = 0, []
        for pin, d in pins_lef.items():
            if d.get("use") in ("POWER", "GROUND"):
                continue
            for layer_name, x0, y0, x1, y1 in d["rects"]:
                cond = ex.tech.conductor_named(layer_name)
                if cond is None:
                    continue
                c = box(x0, y0, x1, y1).centroid
                tree, names = index.get(cond.layer, (None, []))
                hits = tree.query(Point(c.x, c.y).buffer(1e-6), predicate="intersects").tolist() if tree else []
                owners = sorted({names[i] for i in hits})
                checked += 1
                if owners != [_norm_bus(pin)]:
                    bad.append({"pin": pin, "layer": layer_name, "rect": (x0, y0, x1, y1), "owners": owners})
        report[master] = {"rects_checked": checked, "bad": bad}
    return report


def swapped_label_cell(cell, a, b, suffix="__swapped"):
    """A copy of `cell` (new name, so no pin cache is reused) with the texts of labels
    `a` and `b` exchanged: the negative control for (d2)."""
    new = cell.copy(cell.name + suffix, deep_copy=True)
    for lb in new.labels:
        if lb.text in (a, b):
            lb.text = b if lb.text == a else a
    return new


# --- (e) V5 sanity -----------------------------------------------------------

def check_sanity(ex, lef):
    pin_dir = {}
    for master, m in lef.items():
        for p, info in m["pins"].items():
            pin_dir[(master, _norm_bus(p))] = info["direction"]
    master_of = {i["name"]: i["master"] for i in ex.instances}
    no_driver, multi_driver, floating_input = [], [], []
    for net in ex.nets:
        if net["supply"]:
            continue
        drivers = 0
        has_input = False
        for inst_name, pin in net["pins"]:
            master = master_of.get(inst_name)
            d = pin_dir.get((master, _norm_bus(pin)))
            if d in ("OUTPUT",):
                drivers += 1
            elif d in ("INPUT",):
                has_input = True
        if net["ports"]:
            continue  # top-level port: driven/loaded off-chip, not a defect here
        if drivers == 0 and has_input:
            no_driver.append(net["name"])
        elif drivers > 1:
            multi_driver.append(net["name"])
    supply_overlap = set(ex.supply_labels.get("VDD", [])) & set(ex.supply_labels.get("VSS", []))
    return {
        "signal_nets": sum(1 for n in ex.nets if not n["supply"]),
        "no_driver": no_driver[:50], "no_driver_count": len(no_driver),
        "multi_driver": multi_driver[:50], "multi_driver_count": len(multi_driver),
        "supply_names_overlap": bool(supply_overlap),
    }


# --- (f) cellcheck ------------------------------------------------------------

def check_cellcheck(gds=GDS, pdk_gds=STDCELL_GDS, prefix=IHP_SG13CMOS5L.prefix):
    design = cellcheck.masters(gds, prefix)
    diffs = cellcheck.compare(design, cellcheck.masters(pdk_gds, prefix))
    return {"masters": len(design), "identical": len(design) - len(diffs), "differ": diffs}


# --- driver ------------------------------------------------------------------

def run(verbose=True):
    report = {}
    lef = load_lef()
    ex, dt, peak_mb = extract_tempo(lef=lef)
    report["extraction"] = {"seconds": dt, "peak_rss_mb": peak_mb, **ex.summary()}
    if verbose:
        print(f"extraction: {dt:.1f}s, {peak_mb:.0f} MB peak, {ex.summary()}")

    def_data = read_def(DEF)
    name_map, place_report = map_to_def(ex, def_data["components"])
    report["a_placements"] = place_report
    if verbose:
        print("(a) placements:", {k: (v if not isinstance(v, list) else len(v)) for k, v in place_report.items()})

    gp = gds_partition(ex, name_map, lef)
    supply_pins_excluded = gds_partition.last_excluded_supply_pins
    gp_all = gds_partition(ex, name_map, lef, min_size=1)
    gp_singletons = len(gp_all) - len(gp)
    dp = def_net_partition(def_data)
    report["b_def_nets"] = compare_partitions(gp, dp)
    report["b_def_nets"]["gds_singleton_nets_excluded"] = gp_singletons
    report["b_def_nets"]["gds_supply_pins_excluded"] = supply_pins_excluded
    if verbose:
        print("(b) vs DEF NETS:", report["b_def_nets"])

    nlv_insts = parse_nl_verilog(NL_V)
    np_ = nlv_partition(nlv_insts, name_map, lef, set(ex.ports))
    report["c_nl_v"] = compare_partitions(gp, np_)
    report["c_nl_v"]["nl_instances"] = len(nlv_insts)
    report["c_nl_v"]["nl_only"] = sorted(set(nlv_insts) - set(name_map.values()))[:20]
    if verbose:
        print("(c) vs nl.v:", report["c_nl_v"])

    report["d_pins_vs_lef"] = check_pins_vs_lef(ex, lef)
    d_bad = {m: v for m, v in report["d_pins_vs_lef"].items() if v["mismatched_instances"]}
    if verbose:
        print(f"(d) pins vs LEF: {len(report['d_pins_vs_lef'])} masters, {len(d_bad)} with mismatches")

    report["d2_pin_geometry"] = check_pin_geometry_vs_lef(ex, lef)
    d2 = report["d2_pin_geometry"]
    if verbose:
        print(f"(d2) pin geometry vs LEF: {len(d2)} masters, {sum(v['rects_checked'] for v in d2.values())} "
              f"rects, {sum(len(v['bad']) for v in d2.values())} misplaced")

    report["e_sanity"] = check_sanity(ex, lef)
    if verbose:
        print("(e) sanity:", {k: v for k, v in report["e_sanity"].items() if not isinstance(v, list)})

    report["f_cellcheck"] = check_cellcheck()
    if verbose:
        print(f"(f) cellcheck: {report['f_cellcheck']['identical']}/{report['f_cellcheck']['masters']} identical")

    return ex, report


def main():
    _ex, report = run()
    print(json.dumps(
        {k: v for k, v in report.items() if k not in ("d_pins_vs_lef", "d2_pin_geometry")},
        indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
