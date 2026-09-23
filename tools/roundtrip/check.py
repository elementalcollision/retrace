"""S4 round trip, verification: RETRACE's own oracles on a LibreLane run's GDS.

    .venv/bin/python -m tools.roundtrip.check RUN_DIR [--gds klayout|magic|all|FILE ...]
                                              [--json OUT] [--work DIR] [--no-flat-cuts]

RUN_DIR is a LibreLane run directory (tools/roundtrip/run.sh makes
out/roundtrip/<design>_run/<tag>). Each GDS is checked against the run's own final
views, RUN_DIR/final/{def,nl}/: the DEF (COMPONENTS, PINS, NETS) and the post-route
netlist nl.v. These are the oracles the project ran on the warm-up
(docs/spec/VERIFICATION.md), with the run's DEF and nl.v as the golden files:

  X    extraction   extractor 1 (tools/retrace/extract.py) raises no diagnostic
  V1   placements   extracted (master, x, y, orient) multiset == DEF COMPONENTS
                    (test/test_warmup.py); also maps each GDS instance to its DEF name
  V2   pins         every master used: extracted pin names == LEF pins that have
                    geometry (VPB/VNB excluded), and every LEF li1/met1 port rectangle of
                    a signal pin lies on the extracted pin of that name and on no other
                    (test/test_pins.py)
  V3a  DEF nets     extracted partition of (DEF instance, pin) and ports == DEF NETS.
                    Single-pin nets on an OUTPUT pin (unconnected outputs, which DEF
                    omits) are allowed and counted (test/test_warmup.py)
  V3b  netlist      labelled-graph isomorphism (tools/retrace/netgraph.py) of the
                    extracted netlist (Extraction.to_verilog) with nl.v, physical cells
                    dropped by netgraph as in test/test_warmup.py. One normalisation,
                    applied to both graphs and counted: an unlabelled net whose only
                    connection is one OUTPUT pin is removed. OpenROAD writes a CTS dummy
                    load as `.A(net)` with X left out, while the layout has a real
                    X conductor. The number removed on our side must equal the number of
                    unconnected output pins in nl.v. As a companion check, the partition
                    by instance name must equal nl.v's, because OpenROAD writes the same
                    names into the DEF and nl.v.
  V4   extractor 2  KLayout LayoutToNetlist (tools/l2n) == extractor 1, net for net,
                    multi-member nets (test/test_crosscheck.py)
  V5   electrical   every DEF signal pin bound to a GDS label; one net per DEF supply,
                    touching only pins of its own name and every instance; one driver per
                    signal net; no floating logic input; unloaded outputs only CTS dummy
                    loads or tie cells (test/test_puzzle.py)
  CC   cellcheck    every sky130_fd_sc_hd master in the GDS identical, layer by layer on
                    a 1 nm grid, to the PDK's cell GDS (tools/retrace/cellcheck.py)
  XS   stream-outs  (two or more GDS) extractor 1's partitions over (master@origin,
                    pin) and labels are identical across the GDS files

Magic stream-out. Magic writes no VIA_* cells: every via is flat cut polygons in the
top cell. Until Freeze 2 extractor 1 took cuts only from VIA_* cells, so on a Magic GDS
it left every via open and raised no diagnostic, and this module added the missing rule
in a subclass. The rule now lives in extract.py (`Extraction(top_cuts=True)`, the
default): a cut shape drawn in the top cell joins the conductors below and above it,
just as the same shape inside a VIA_* cell would. The report counts those shapes and
how many the extractor bound (X fails on any left unbound). A GDS with none, such as
the KLayout stream-out, is extracted exactly as before. --no-flat-cuts extracts with
`top_cuts=False`, the old behaviour, which shows the failure.

--gds picks the GDS: klayout (final/klayout_gds), magic (final/mag_gds), all (every
stream-out present; the default) or a file path; it can be repeated. Emitted netlists
and report.json go to --work (default out/roundtrip/check/<run path under
out/roundtrip>). Exit status: 0 when every check passes on every GDS, 1 when any
check fails, 2 when a view is missing.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import gdstk
from shapely.geometry import Polygon, box

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.l2n import compare as l2n  # noqa: E402
from tools.retrace import cellcheck, mutate, netgraph  # noqa: E402
from tools.retrace.defparse import read_def  # noqa: E402
from tools.retrace.extract import TOP_CUT, Extraction  # noqa: E402
from tools.retrace.lef import read_lef  # noqa: E402
from tools.retrace.tech import SKY130_HD  # noqa: E402

TECH = SKY130_HD
PREFIX = TECH.prefix
SUPPLY = frozenset(TECH.supply_pins)
PIN_LAYERS = {"li1": 67, "met1": 68}  # LEF port layers that carry std-cell pins
OUT = ROOT / "out/roundtrip"
FLAT_CUT = TOP_CUT  # owner name extract.py gives a cut shape drawn in the top cell
STREAMOUTS = {"klayout": "klayout_gds", "magic": "mag_gds"}


def pdk_file(rel: str) -> Path:
    """sky130_fd_sc_hd file from the repo's pdk/ subset, else from $PDK_ROOT (open_pdks
    8afc8346; the repo subset is byte-identical to it)."""
    local = ROOT / "pdk/sky130_fd_sc_hd" / rel
    if local.exists():
        return local
    pdk_root = Path(os.environ.get("PDK_ROOT", os.path.expanduser("~/pdk-sky130")))
    return pdk_root / "sky130A/libs.ref/sky130_fd_sc_hd" / rel


LEF = pdk_file("lef/sky130_fd_sc_hd.lef")
PDK_GDS = pdk_file("gds/sky130_fd_sc_hd.gds")


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- run views ---------------------------------------------------------------

def views(run_dir: Path) -> dict:
    """The final views of a LibreLane run: {"def", "nl", "klayout", "magic", "gds"}, a
    Path or None each (None also when a directory holds more than one candidate)."""
    final = run_dir / "final"

    def one(sub, pattern):
        hits = sorted((final / sub).glob(pattern)) if (final / sub).is_dir() else []
        return hits[0] if len(hits) == 1 else None

    return {"def": one("def", "*.def"), "nl": one("nl", "*.nl.v"), "gds": one("gds", "*.gds"),
            **{k: one(d, "*.gds") for k, d in STREAMOUTS.items()}}


def def_header(path: Path) -> dict:
    """DESIGN name and the PINS section: {"design", "pins": {name: {direction, use}}}."""
    design, pins, section = None, {}, False
    with open(path) as f:
        for line in f:
            s = line.strip()
            if s.startswith("DESIGN "):
                design = s.split()[1]
            elif s.startswith("PINS "):
                section = True
            elif s.startswith("END PINS"):
                break
            elif section and s.startswith("- "):
                d = re.search(r"\+\s+DIRECTION\s+(\w+)", s)
                u = re.search(r"\+\s+USE\s+(\w+)", s)
                pins[s.split()[1]] = {"direction": d.group(1) if d else None, "use": u.group(1) if u else "SIGNAL"}
    return {"design": design, "pins": pins}


def signal_ports(pins: dict) -> dict:
    """{port bit name: INPUT|OUTPUT|INOUT} for the DEF's signal pins (not supplies)."""
    return {p: d["direction"] for p, d in pins.items() if d["use"] not in ("POWER", "GROUND")}


def supply_ports(pins: dict) -> set:
    return {p for p, d in pins.items() if d["use"] in ("POWER", "GROUND")}


def port_dirs(pins: dict) -> dict:
    """Extraction.to_verilog port directions, keyed by port base name (O[3] -> O)."""
    return {p.split("[")[0]: d.lower() for p, d in signal_ports(pins).items() if d}


# --- extraction ---------------------------------------------------------------

# Back-compat name only. The rule this subclass used to add after `Extraction._routing`
# (bind cut shapes drawn in the top cell) is now `Extraction`'s own, on by default;
# subclassing and adding the cuts again would bind each of them twice.
FlatCutExtraction = Extraction


def top_level_cuts(ex) -> int:
    """Cut shapes drawn directly in the top cell, polygons and paths (as polygons), counted
    here independently of the extractor so the report can show any it left unbound."""
    keys = {(c.layer, c.datatype) for c in ex.tech.cuts}
    shapes = list(ex.top.polygons) + [q for path in ex.top.paths for q in path.to_polygons()]
    return sum(1 for p in shapes if (p.layer, p.datatype) in keys)


def extract(gds: Path, lef: dict, top: str | None, flat_cuts: bool = True):
    """Extractor 1 on `gds`; `flat_cuts` is `Extraction`'s `top_cuts` (False: cut shapes
    drawn in the top cell are ignored, the pre-Freeze-2 behaviour)."""
    t0 = time.time()
    ex = Extraction(str(gds), lef, top, top_cuts=flat_cuts)
    return ex, time.time() - t0


def top_cells(gds: Path) -> list:
    return sorted(c.name for c in gdstk.read_gds(str(gds)).top_level())


def private_master_copies(gds: Path, lef: dict) -> dict:
    """{cell name: LEF master} for the cells of `gds` that the LEF does not know but that
    are named as a private per-mutant copy of a master it does know
    (tools/retrace/mutate.py: "<master>__PINSWAP_<n>", "<master>__TAMPER_<n>"). Extraction
    needs a LEF entry for every instantiated master; with these aliases (as
    mutate.lef_for_mutant does) such a GDS is extracted and its fault is left for V1
    (renamed master), V2 (pins against the original master's LEF) and CC (not a PDK cell)
    to report, instead of stopping the check with a KeyError."""
    out = {}
    for name in gdstk.read_rawcells(str(gds)):
        base = mutate.base_master_name(name)
        if name not in lef and base != name and base in lef:
            out[name] = base
    return out


def is_physical(master: str) -> bool:
    return master[len(PREFIX):].startswith(TECH.physical_prefixes)


def direction(lef: dict, master: str, pin: str) -> str | None:
    return lef.get(master, {}).get("pins", {}).get(pin, {}).get("direction")


# --- V1 placements -------------------------------------------------------------

def check_v1(ex, comps: dict) -> tuple[dict, dict]:
    """Returns (result, {gds instance name: DEF name or None})."""
    key = lambda i: (i["master"], i["x"], i["y"], i["orient"])  # noqa: E731
    ours = collections.Counter(key(i) for i in ex.instances)
    theirs = collections.Counter(comps.values())
    only_gds, only_def = ours - theirs, theirs - ours
    by_key = collections.defaultdict(list)
    for name, k in comps.items():
        by_key[k].append(name)
    dup = {k: v for k, v in by_key.items() if len(v) > 1}
    ren = {i["name"]: (by_key[key(i)][0] if len(by_key.get(key(i), [])) == 1 else None) for i in ex.instances}
    physical = sum(1 for i in ex.instances if is_physical(i["master"]))
    res = {
        "pass": not only_gds and not only_def and not dup,
        "gds_instances": len(ex.instances), "def_components": len(comps),
        "matched": sum((ours & theirs).values()), "only_gds": sum(only_gds.values()),
        "only_def": sum(only_def.values()), "duplicate_def_keys": len(dup),
        "masters": len({i["master"] for i in ex.instances}),
        "logic": len(ex.instances) - physical, "physical": physical,
        "examples": {"only_gds": [list(k) for k in list(only_gds)[:5]], "only_def": [list(k) for k in list(only_def)[:5]]},
    }
    return res, ren


# --- V2 pins -------------------------------------------------------------------

def check_v2(ex, lef: dict) -> dict:
    masters = {c.name: c for c in ex.lib.cells if c.name.startswith(PREFIX)}
    set_bad, geo_bad, missing = [], [], []
    n_pins = n_rects = 0
    for name, cell in sorted(masters.items()):
        if name not in lef:
            missing.append(name)
            continue
        pins = ex._master_pins(cell)
        theirs = {p for p, d in lef[name]["pins"].items() if d["rects"] and p not in ("VPB", "VNB")}
        if set(pins) != theirs:
            set_bad.append([name, sorted(set(pins) ^ theirs)])
        n_pins += len(theirs)
        geo = {p: {lyr: [Polygon(q.points) for q in polys if q.layer == lyr] for lyr in PIN_LAYERS.values()}
               for p, polys in pins.items()}
        for pin, d in lef[name]["pins"].items():
            if pin in SUPPLY:
                continue
            for layer, x0, y0, x1, y1 in d["rects"]:
                if layer not in PIN_LAYERS:
                    continue
                n_rects += 1
                c = box(x0, y0, x1, y1).centroid
                owners = [p for p, g in geo.items() if any(q.buffer(1e-6).covers(c) for q in g[PIN_LAYERS[layer]])]
                if owners != [pin]:
                    geo_bad.append([name, pin, layer, [x0, y0, x1, y1], owners])
    return {"pass": not set_bad and not geo_bad and not missing and bool(masters),
            "masters": len(masters), "pins": n_pins, "lef_rects_checked": n_rects,
            "masters_not_in_lef": missing, "pin_set_mismatches": set_bad, "rects_off_pin": geo_bad[:10],
            "rects_off_pin_count": len(geo_bad)}


# --- V3a DEF nets ----------------------------------------------------------------

def gds_partition(ex, ren: dict) -> list:
    """Extracted nets as frozensets of (DEF instance, pin) and ("PIN", port), supply
    pins left out (the DEF's supplies are SPECIALNETS). An instance V1 could not match
    keeps its GDS name, marked, so it matches nothing."""
    nets = []
    for m in ex.nets:
        s = {(ren.get(i) or f"<unmatched {i}>", p) for i, p in m["pins"] if p not in SUPPLY}
        s |= {("PIN", p) for p in m["ports"]}
        if s:
            nets.append(frozenset(s))
    return nets


def _single_output(net, masters_by_def: dict, lef: dict) -> bool:
    (inst, pin), = net
    return inst != "PIN" and direction(lef, masters_by_def.get(inst), pin) == "OUTPUT"


def _compare_partitions(ours: list, theirs: list, masters_by_def: dict, lef: dict) -> dict:
    a, b = set(ours), set(theirs)
    missing = sorted(b - a, key=lambda n: sorted(map(str, n)))
    extra = sorted(a - b, key=lambda n: sorted(map(str, n)))
    extra_real = [n for n in extra if len(n) > 1 or not _single_output(n, masters_by_def, lef)]
    extra_single = [n for n in extra if n not in extra_real]
    single_masters = collections.Counter(
        f"{masters_by_def[i][len(PREFIX):]}.{p}" for n in extra_single for i, p in n)
    return {"pass": not missing and not extra_real and len(a) == len(ours),
            "golden_nets": len(b), "gds_nets": len(a), "matched": len(a & b),
            "missing": len(missing), "unexpected": len(extra_real),
            "unconnected_outputs": len(extra_single), "unconnected_output_pins": dict(single_masters),
            "duplicate_gds_nets": len(ours) - len(a),
            "examples": {"missing": [sorted(map(list, n)) for n in missing[:3]],
                         "unexpected": [sorted(map(list, n)) for n in extra_real[:3]]}}


def check_v3a(ex, ren: dict, golden: dict, lef: dict) -> dict:
    comps = golden["components"]
    masters_by_def = {n: c[0] for n, c in comps.items()}
    theirs_all = [frozenset(v) for v in golden["nets"].values()]
    res = _compare_partitions(gds_partition(ex, ren), [n for n in theirs_all if n], masters_by_def, lef)
    res["def_nets_listed"] = len(theirs_all)
    res["def_nets_without_connections"] = sum(1 for n in theirs_all if not n)
    return res


# --- V3b netlist -------------------------------------------------------------------

def drop_dangling_outputs(g, lef: dict) -> collections.Counter:
    """Remove unlabelled net nodes whose only edge is an OUTPUT pin; count them by
    master.pin."""
    gone = collections.Counter()
    for node, d in list(g.nodes(data=True)):
        if d["kind"] != "net" or d["label"] or g.degree(node) != 1:
            continue
        (cell,) = g.neighbors(node)
        pin = g.edges[cell, node]["pin"]
        master = g.nodes[cell]["label"]
        if direction(lef, master, pin) == "OUTPUT":
            g.remove_node(node)
            gone[f"{master[len(PREFIX):]}.{pin}"] += 1
    return gone


def unconnected_outputs(module: dict, lef: dict) -> collections.Counter:
    """Output pins of the netlist's logic cells that are left out or empty."""
    out = collections.Counter()
    for cell in module["cells"].values():
        master = cell["type"]
        if not master.startswith(PREFIX) or is_physical(master):
            continue
        for pin, d in lef.get(master, {}).get("pins", {}).items():
            if d["direction"] == "OUTPUT" and not cell["connections"].get(pin):
                out[f"{master[len(PREFIX):]}.{pin}"] += 1
    return out


def netlist_partition(module: dict) -> tuple[list, dict]:
    """nl.v nets by instance name: frozensets of (instance, pin) and ("PIN", port bit),
    supply pins left out, every cell kept (a diode's DIODE pin is a signal).
    Returns (partition, {instance: master})."""
    port_of = {}
    for name, port in module["ports"].items():
        bits, off = port["bits"], port.get("offset", 0)
        for k, bit in enumerate(bits):  # Yosys lists bits LSB first
            idx = off + (len(bits) - 1 - k if port.get("upto") else k)
            port_of[bit] = name if len(bits) == 1 else f"{name}[{idx}]"
    members = collections.defaultdict(set)
    for bit, name in port_of.items():
        members[bit].add(("PIN", name))
    masters = {}
    for iname, cell in module["cells"].items():
        masters[iname] = cell["type"]
        for pin, bits in cell["connections"].items():
            if pin in SUPPLY:
                continue
            for bit in bits:
                members[bit if isinstance(bit, int) else f"const_{bit}"].add((iname, pin))
    return [frozenset(s) for s in members.values()], masters


def check_v3b(ex, ren: dict, lef: dict, pins: dict, nl: Path, top: str, emitted: Path) -> dict:
    emitted.parent.mkdir(parents=True, exist_ok=True)
    emitted.write_text(ex.to_verilog(port_dirs(pins), lef))
    with contextlib.chdir(ROOT):  # netgraph reads the Liberty file by a repo-relative path
        ours_m = netgraph.yosys_json(str(emitted), top)
        theirs_m = netgraph.yosys_json(str(nl), top)
    ga, gb = netgraph.graph(ours_m), netgraph.graph(theirs_m)
    stats = lambda g: {k: sum(1 for _n, d in g.nodes(data=True) if d["kind"] == k)  # noqa: E731
                       for k in ("cell", "net", "const")} | {"edges": g.number_of_edges()}
    raw = {"ours": stats(ga), "nl": stats(gb)}
    t0 = time.time()
    raw_iso = raw["ours"] == raw["nl"] and netgraph.isomorphic(ga, gb)
    drop_a, drop_b = drop_dangling_outputs(ga, lef), drop_dangling_outputs(gb, lef)
    iso = netgraph.isomorphic(ga, gb)
    dt = time.time() - t0
    unconn = unconnected_outputs(theirs_m, lef)
    hist = lambda m: collections.Counter(c["type"] for c in m["cells"].values() if not is_physical(c["type"]))  # noqa: E731
    ha, hb = hist(ours_m), hist(theirs_m)
    # by name: nl.v's instance names are the DEF's
    part_nl, masters_nl = netlist_partition(theirs_m)
    names = _compare_partitions(gds_partition(ex, ren), part_nl, masters_nl, lef)
    ok = iso and drop_a == unconn + drop_b and names["pass"]
    return {"pass": ok, "isomorphic": iso, "raw_isomorphic": raw_iso, "raw_graphs": raw,
            "graphs": {"ours": stats(ga), "nl": stats(gb)}, "iso_seconds": round(dt, 2),
            "dangling_outputs_dropped": {"ours": dict(drop_a), "nl": dict(drop_b)},
            "nl_unconnected_outputs": dict(unconn),
            "logic_cells": {"ours": sum(ha.values()), "nl": sum(hb.values())},
            "histogram_diff": {k[len(PREFIX):]: ha[k] - hb[k] for k in sorted(set(ha) | set(hb)) if ha[k] != hb[k]},
            "by_name": names, "emitted": str(emitted), "nl_v": str(nl)}


# --- V4 second extractor ------------------------------------------------------------

def check_v4(gds: Path, ex) -> dict:
    t0 = time.time()
    ours, theirs = l2n.compare(str(gds), ex)
    dt = time.time() - t0
    a = {n for n in ours if len(n) > 1}
    b = {n for n in theirs if len(n) > 1}
    return {"pass": a == b and bool(a), "extractor1_nets": len(a), "klayout_nets": len(b),
            "only_extractor1": len(a - b), "only_klayout": len(b - a),
            "single_member": {"extractor1": len(ours) - len(a), "klayout": len(theirs) - len(b)},
            "seconds": round(dt, 1),
            "examples": {"only_extractor1": [sorted(map(list, n))[:6] for n in list(a - b)[:3]],
                         "only_klayout": [sorted(map(list, n))[:6] for n in list(b - a)[:3]]}}


# --- V5 electrical ---------------------------------------------------------------

def check_v5(ex, lef: dict, pins: dict) -> dict:
    ports = signal_ports(pins)
    inputs = {p for p, d in ports.items() if d == "INPUT"}
    outputs = {p for p, d in ports.items() if d == "OUTPUT"}
    supplies = supply_ports(pins)
    masters = {i["name"]: i["master"] for i in ex.instances}
    n_inst = len(ex.instances)
    res = {}

    bound = set(ex.ports)
    res["ports"] = {"pass": bound == set(ports), "bound": len(bound & set(ports)), "def_signal_pins": len(ports),
                    "unbound": sorted(set(ports) - bound), "unknown": sorted(bound - set(ports))}

    sup = [m for m in ex.nets if m["supply"]]
    labels = sorted(tuple(sorted(m["supply"])) for m in sup)
    per = {}
    for m in sup:
        pc = collections.Counter(p for _i, p in m["pins"])
        for name in m["supply"]:
            d = per.setdefault(name, {"nets": 0, "instances_reached": 0, "other_pins": collections.Counter()})
            d["nets"] += 1
            d["instances_reached"] = max(d["instances_reached"], pc.get(name, 0))  # by its best net
            d["other_pins"].update({p: c for p, c in pc.items() if p != name})
    unlabelled = sum(1 for m in ex.nets if not m["supply"] and m["pins"] and all(p in SUPPLY for _i, p in m["pins"]))
    ok = labels == sorted((s,) for s in supplies) and all(
        v["nets"] == 1 and v["instances_reached"] == n_inst and not v["other_pins"] for v in per.values())
    res["supplies"] = {"pass": ok and not unlabelled, "nets": dict(collections.Counter("/".join(x) for x in labels)),
                       "instances": n_inst,
                       "per_supply": per, "unlabelled_supply_only_nets": unlabelled}

    def signal_nets():
        for m in ex.nets:
            sig = [(i, p) for i, p in m["pins"] if p not in SUPPLY]
            if sig or m["ports"]:
                yield m, sig

    bad_drv, floating, unloaded, clock_loads, ties = [], [], [], 0, 0
    n_sig = 0
    clk_nets = {m["name"] for m in ex.nets if any(p == "CLK" for _i, p in m["pins"])}
    for m, sig in signal_nets():
        n_sig += 1
        drivers = [ip for ip in sig if direction(lef, masters[ip[0]], ip[1]) == "OUTPUT"]
        drivers += [("PORT", p) for p in m["ports"] if p in inputs]
        if len(drivers) != 1:
            bad_drv.append([m["name"], [list(d) for d in drivers[:4]], m["ports"]])
        if not drivers:
            floating += [list(ip) for ip in sig if not is_physical(masters[ip[0]])]
        loads = [ip for ip in sig if direction(lef, masters[ip[0]], ip[1]) == "INPUT"]
        loads += [p for p in m["ports"] if p in outputs]
        if loads:
            continue
        for inst, pin in sig:
            short = masters[inst][len(PREFIX):]
            if short.startswith("conb_"):
                ties += 1
            elif short.startswith(("clkbuf_", "clkinv_")) and ex.net_of.get((inst, "A")) in clk_nets:
                clock_loads += 1
            else:
                unloaded.append([inst, pin])
    res["drivers"] = {"pass": not bad_drv, "signal_nets": n_sig, "not_one_driver": len(bad_drv), "examples": bad_drv[:5]}
    res["floating_inputs"] = {"pass": not floating, "count": len(floating), "examples": floating[:10]}
    res["unloaded_outputs"] = {"pass": not unloaded, "cts_dummy_loads": clock_loads, "tie_outputs": ties,
                               "unexpected": unloaded[:10], "unexpected_count": len(unloaded)}
    res["pass"] = all(v["pass"] for v in res.values())
    return res


# --- cellcheck ----------------------------------------------------------------------

def check_cellcheck(gds: Path, pdk_gds: Path) -> dict:
    design = cellcheck.masters(str(gds))
    diffs = cellcheck.compare(design, cellcheck.masters(str(pdk_gds)))
    detail = {m: (v if isinstance(v, str) else {f"{ly}/{dt}": list(n) for (ly, dt), n in v.items()}) for m, v in diffs.items()}
    return {"pass": bool(design) and not diffs, "masters": len(design), "identical": len(design) - len(diffs),
            "differ": detail, "pdk_gds": str(pdk_gds), "pdk_gds_sha256": sha(pdk_gds)[:16]}


# --- XS stream-outs agree -------------------------------------------------------------

def stream_partition(ex) -> set:
    labels = set(ex.ports) | set(ex.supply_labels)
    return l2n.partition_ours(ex, labels)


def check_streamouts(parts: dict) -> dict:
    names = list(parts)
    ref = parts[names[0]]
    res = {"pass": True, "reference": names[0], "nets": {n: len(p) for n, p in parts.items()}, "diff": {}}
    for n in names[1:]:
        d = {"only_" + names[0]: len(ref - parts[n]), "only_" + n: len(parts[n] - ref)}
        res["diff"][n] = d
        res["pass"] &= not any(d.values())
    return res


# --- driver ----------------------------------------------------------------------

ORDER = ["X", "V1", "V2", "V3a", "V3b", "V4", "V5", "CC"]


def check_gds(label: str, gds: Path, v: dict, lef: dict, golden: dict, hdr: dict, work: Path,
              flat_cuts: bool = True, pdk_gds: Path = PDK_GDS) -> tuple[dict, object]:
    top = hdr["design"]
    r = {"gds": str(gds), "sha256": sha(gds)[:16]}
    aliases = private_master_copies(gds, lef)
    if aliases:
        lef = dict(lef) | {name: lef[base] for name, base in aliases.items()}
    try:
        ex, dt = extract(gds, lef, top, flat_cuts)
    except Exception as e:  # e.g. a master the LEF does not know, or no top cell `top`
        msg = f"{type(e).__name__}: {e}"
        if isinstance(e, StopIteration):  # extract.py's next() over the top cells
            msg = f"no top cell named {top!r} (the DEF's DESIGN) in this GDS; its top cells: {top_cells(gds)}"
        r["X"] = {"pass": False, "error": msg, "private_master_copies": aliases}
        r["pass"] = False
        return r, None
    v1, ren = check_v1(ex, golden["components"])
    r["V1"] = v1
    r["V2"] = check_v2(ex, lef)
    r["V3a"] = check_v3a(ex, ren, golden, lef)
    r["V3b"] = check_v3b(ex, ren, lef, hdr["pins"], v["nl"], top, work / f"{label}.v")
    r["V4"] = check_v4(gds, ex)
    r["V5"] = check_v5(ex, lef, hdr["pins"])
    r["CC"] = check_cellcheck(gds, pdk_gds)
    # after to_verilog (V3b), which records pin_missing_geometry
    s = ex.summary()
    n_cuts = top_level_cuts(ex)
    ignored = n_cuts - sum(getattr(ex, "flat_cuts", {}).values())
    r["X"] = {"pass": not ex.diag and not ignored, "diagnostics": dict(ex.diag), "notes": ex.notes[:5], "seconds": round(dt, 2),
              "instances": s["instances"], "logic_instances": s["logic_instances"], "nets": s["nets"],
              "signal_nets": s["signal_nets"],
              "extractor": type(ex).__name__ + ("(top_cuts=True)" if ex.top_cuts else "(top_cuts=False)"),
              "top_level_cut_polygons": n_cuts, "top_level_cut_polygons_ignored": ignored,
              "flat_cuts_bound": dict(getattr(ex, "flat_cuts", {})), "private_master_copies": aliases}
    r["pass"] = all(r[k]["pass"] for k in ORDER)
    return r, ex


def run(run_dir: Path, which=("all",), work: Path | None = None, flat_cuts: bool = True,
        lef_path: Path = LEF, pdk_gds: Path = PDK_GDS) -> dict:
    run_dir = Path(run_dir).resolve()
    v = views(run_dir)
    if not v["def"] or not v["nl"]:
        raise FileNotFoundError(f"{run_dir}/final: need exactly one def/*.def and one nl/*.nl.v")
    targets = {}
    for w in which:
        if w == "all":
            targets |= {k: v[k] for k in STREAMOUTS if v[k]}
        elif w in STREAMOUTS:
            if not v[w]:
                raise FileNotFoundError(f"{run_dir}/final/{STREAMOUTS[w]}: no single GDS")
            targets[w] = v[w]
        else:
            p = Path(w).resolve()
            if not p.exists():
                raise FileNotFoundError(p)
            targets[p.stem.replace(".", "_")] = p
    if not targets:
        raise FileNotFoundError(f"{run_dir}/final: no GDS stream-out")
    if work is None:
        try:
            work = OUT / "check" / run_dir.relative_to(OUT)
        except ValueError:
            work = OUT / "check" / run_dir.name
    work = Path(work).resolve()
    lef = read_lef(str(lef_path))
    golden = read_def(str(v["def"]))
    hdr = def_header(v["def"])
    primary = sha(v["gds"]) if v["gds"] else None
    report = {"run_dir": str(run_dir), "design": hdr["design"], "def": str(v["def"]), "nl_v": str(v["nl"]),
              "def_components": len(golden["components"]), "def_nets": len(golden["nets"]),
              "def_pins": len(hdr["pins"]), "flat_cuts": flat_cuts, "lef": str(lef_path),
              "primary_gds": str(v["gds"]) if v["gds"] else None,
              "primary_gds_same_as": [k for k in STREAMOUTS if v[k] and primary and sha(v[k]) == primary],
              "gds": {}}
    parts = {}
    for label, gds in targets.items():
        r, ex = check_gds(label, gds, v, lef, golden, hdr, work, flat_cuts, pdk_gds)
        report["gds"][label] = r
        if ex is not None:
            parts[label] = stream_partition(ex)
    if len(targets) > 1:
        report["XS"] = check_streamouts(parts) if len(parts) == len(targets) else {
            "pass": False, "error": "extraction failed on a GDS"}
    report["pass"] = all(r["pass"] for r in report["gds"].values()) and report.get("XS", {"pass": True})["pass"]
    report["work"] = str(work)
    return report


def _pf(ok):
    return "PASS" if ok else "FAIL"


def _brief(counts: dict, k: int = 4) -> str:
    """'total (a n, b m, ...)', largest first, at most k entries shown."""
    if not counts:
        return "0"
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    body = ", ".join(f"{n} {c}" for n, c in top[:k]) + (f", +{len(top) - k} more" if len(top) > k else "")
    return f"{sum(counts.values())} ({body})"


def show(rep: dict) -> None:
    print(f"run     {rep['run_dir']}")
    print(f"golden  {rep['def']}: {rep['def_components']} components, {rep['def_nets']} nets, {rep['def_pins']} pins")
    print(f"        {rep['nl_v']}")
    if rep["primary_gds"]:
        same = ", ".join(rep["primary_gds_same_as"]) or "neither stream-out"
        print(f"        final/gds is byte-identical to: {same}")
    for label, r in rep["gds"].items():
        x = r["X"]
        print(f"\n[{label}] {r['gds']}")
        if "error" in x:
            print(f"  X    FAIL  extraction raised {x['error']}\n  =>   FAIL")
            continue
        cuts = f"{x['top_level_cut_polygons']} top-level cut polygons"
        if x["flat_cuts_bound"]:
            cuts += " bound as vias (" + ", ".join(f"{k} {n}" for k, n in x["flat_cuts_bound"].items()) + ")"
        if x["top_level_cut_polygons_ignored"]:
            cuts += f"; {x['top_level_cut_polygons_ignored']} IGNORED (vias left open)"
        print(f"  X    {_pf(x['pass'])}  {x['extractor']} {x['seconds']} s: {x['instances']} instances "
              f"({x['logic_instances']} logic), {x['nets']} nets; diagnostics {x['diagnostics'] or 'none'}; {cuts}")
        if x.get("private_master_copies"):
            print(f"             private master copies read with their original master's LEF: "
                  f"{x['private_master_copies']}")
        a = r["V1"]
        print(f"  V1   {_pf(a['pass'])}  {a['matched']}/{a['gds_instances']} GDS instances = DEF COMPONENTS "
              f"({a['def_components']}) by (master, x, y, orient); only GDS {a['only_gds']}, only DEF {a['only_def']}; "
              f"{a['masters']} masters, {a['logic']} logic + {a['physical']} physical")
        a = r["V2"]
        print(f"  V2   {_pf(a['pass'])}  {a['masters']} masters: pin sets = LEF ({a['pins']} pins, "
              f"{len(a['pin_set_mismatches'])} mismatches); {a['lef_rects_checked']} LEF li1/met1 rects, "
              f"{a['rects_off_pin_count']} not on their own pin only")
        a = r["V3a"]
        print(f"  V3a  {_pf(a['pass'])}  {a['matched']}/{a['golden_nets']} DEF nets matched exactly; missing {a['missing']}, "
              f"unexpected {a['unexpected']}; unconnected output pins {_brief(a['unconnected_output_pins'])}")
        a = r["V3b"]
        g = a["graphs"]
        print(f"  V3b  {_pf(a['pass'])}  isomorphic to nl.v: {a['isomorphic']} ({g['ours']['cell']} cells, "
              f"{g['ours']['net']} nets, {g['ours']['edges']} pin edges vs {g['nl']['cell']}/{g['nl']['net']}/"
              f"{g['nl']['edges']}; {a['iso_seconds']} s); raw graphs isomorphic: {a['raw_isomorphic']}")
        print(f"             dangling outputs dropped: ours {_brief(a['dangling_outputs_dropped']['ours'])}, "
              f"nl.v {_brief(a['dangling_outputs_dropped']['nl'])}; nl.v unconnected outputs "
              f"{_brief(a['nl_unconnected_outputs'])}")
        n = a["by_name"]
        print(f"             by name: {n['matched']}/{n['golden_nets']} nl.v nets matched; missing {n['missing']}, "
              f"unexpected {n['unexpected']}, unconnected outputs {n['unconnected_outputs']}"
              + (f"; histogram diff {a['histogram_diff']}" if a["histogram_diff"] else ""))
        a = r["V4"]
        print(f"  V4   {_pf(a['pass'])}  KLayout L2N {a['klayout_nets']} nets vs extractor 1 {a['extractor1_nets']} "
              f"(multi-member); only KLayout {a['only_klayout']}, only extractor 1 {a['only_extractor1']}; "
              f"single-member {a['single_member']['extractor1']}/{a['single_member']['klayout']}; {a['seconds']} s")
        a = r["V5"]
        p, s = a["ports"], a["supplies"]
        per = ", ".join(f"{k} on {v['nets']} net(s), best reaches {v['instances_reached']}/{s['instances']} instances"
                        + (f" +{_brief(v['other_pins'])}" if v["other_pins"] else "") for k, v in sorted(s["per_supply"].items()))
        print(f"  V5   {_pf(a['pass'])}  ports {p['bound']}/{p['def_signal_pins']} bound; {per}; "
              f"{s['unlabelled_supply_only_nets']} unlabelled supply islands")
        print(f"             {a['drivers']['signal_nets']} signal nets, {a['drivers']['not_one_driver']} without exactly "
              f"one driver; {a['floating_inputs']['count']} floating logic inputs; unloaded outputs: "
              f"{a['unloaded_outputs']['cts_dummy_loads']} CTS dummy loads, {a['unloaded_outputs']['tie_outputs']} tie, "
              f"{a['unloaded_outputs']['unexpected_count']} unexpected")
        a = r["CC"]
        print(f"  CC   {_pf(a['pass'])}  {a['identical']}/{a['masters']} masters identical to {a['pdk_gds']} "
              f"(sha256 {a['pdk_gds_sha256']}...)" + (f"; differ: {sorted(a['differ'])}" if a["differ"] else ""))
        print(f"  =>   {_pf(r['pass'])}")
    if "XS" in rep:
        a = rep["XS"]
        print(f"\nXS   {_pf(a['pass'])}  " + (a["error"] if "error" in a else
              f"extractor-1 partitions across stream-outs: {a['nets']}; diff {a['diff']}"))
    print(f"\n{_pf(rep['pass'])}  (work: {rep['work']})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--gds", action="append", help="klayout, magic, all (default) or a GDS path; repeatable")
    ap.add_argument("--json", type=Path, help="report JSON (default WORK/report.json)")
    ap.add_argument("--work", type=Path, help="scratch directory (default out/roundtrip/check/<run>)")
    ap.add_argument("--no-flat-cuts", action="store_true",
                    help="extractor 1 with top_cuts=False: top-level cut shapes ignored, as before Freeze 2")
    ap.add_argument("--lef", type=Path, default=LEF)
    ap.add_argument("--pdk-gds", type=Path, default=PDK_GDS)
    args = ap.parse_args(argv)
    try:
        rep = run(args.run_dir, args.gds or ["all"], args.work, not args.no_flat_cuts, args.lef, args.pdk_gds)
    except FileNotFoundError as e:
        print(f"check: {e}", file=sys.stderr)
        return 2
    show(rep)
    out = args.json or Path(rep["work"]) / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=1, default=list) + "\n")
    print(f"report  {out}")
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
