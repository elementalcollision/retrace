"""Compare a synthesized netlist with a reference netlist: cell histograms and structure.

    python -m tools.roundtrip.compare OURS.v OURS_TOP REF.v REF_TOP

Both netlists are read through Yosys and flattened. Histograms are compared per cell
master over the logic cells only: physical cells (tap, decap, fill, diode) and clock-tree
cells are counted separately, because they come from floorplanning and CTS. Distance = sum
over masters of |count difference|.
Cells are split by connectivity, synth.cell_kinds(), not by master name: a clock-family
master (clkbuf, clkinv, clkdlybuf) is a clock-tree cell only where it drives a flop's clock
pin (or hangs off such a tree), and a netlist declared pre-CTS has no clock-tree cells at
all. OURS is taken as a synthesis result (pre-CTS; --ours-post-cts to change that) and REF
as a flow netlist after CTS (--ref-pre-cts to change that), the calibration's case:
upstream/warmup/01_netlist.v has its 3 CTS clkbuf_16. By master name a synthesis run
without no_synth.cells lost its clkinv_1 data inverters from the logic histogram (calib
sweep: 3 in keep_no_exclusions and 1 in keep_drc_exclude_only with Yosys 0.69, 1 in
keep_drc_exclude_only with 0.66), and collapse_clock_buffers bypassed them as if they were
clock buffers.

Structure: a labelled-graph isomorphism test (tools.retrace.netgraph) after deleting
physical cells and collapsing the clock tree (each clock-tree cell's input and output nets
are merged), so a post-CTS reference can be compared with a pre-CTS synthesis result.
Hierarchical netlists are flattened with "/" as the separator, the way OpenROAD names
instances of a hierarchical netlist (`add0/_32_`), so that a name-level comparison is
possible too (`names`: same instance names, masters and net names pin by pin). Per-instance
histograms are reported when cell names carry a hierarchy prefix.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

from tools.retrace import netgraph
from tools.roundtrip.synth import LIB, YOSYS, cell_kinds, histogram_of_module, summarize  # noqa: F401 (summarize: calib)


def load_module(verilog, top, yosys=YOSYS, lib=LIB, separator="/"):
    """Flattened Yosys JSON module. Hierarchical names use `separator` ("/" as OpenROAD)."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as t:
        js = t.name
    script = (
        f"read_liberty -lib {lib}; read_verilog {verilog}; hierarchy -top {top}; "
        f"flatten -noscopeinfo -separator {separator}; write_json {js}"
    )
    subprocess.run([yosys, "-q", "-p", script], check=True)
    with open(js) as f:
        mod = json.load(f)["modules"][top]
    os.unlink(js)
    return mod


def counts(module):
    c = {}
    for cell in module["cells"].values():
        c[cell["type"]] = c.get(cell["type"], 0) + 1
    return c


def distance(la, lb):
    """L1 distance between two logic histograms ({master: n} of logic cells only: the
    "by_kind" "logic" part of synth.histogram_of_module(), or a per_instance() entry), and
    the per-master differences."""
    diff = {m: la.get(m, 0) - lb.get(m, 0) for m in sorted(set(la) | set(lb))}
    diff = {m: d for m, d in diff.items() if d}
    return sum(abs(d) for d in diff.values()), diff


def instance_of(name):
    name = name.lstrip("\\")
    for sep in ("/", "."):
        if sep in name:
            return name.split(sep)[0]
    return ""


def per_instance(module, pre_cts):
    """{hierarchy instance: logic histogram}, cells split by synth.cell_kinds()."""
    kinds = cell_kinds(module, pre_cts)
    out = {}
    for name, cell in module["cells"].items():
        if kinds[name] != "logic":
            continue
        d = out.setdefault(instance_of(name), {})
        d[cell["type"]] = d.get(cell["type"], 0) + 1
    return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}


def collapse_clock_buffers(module, pre_cts):
    """Copy of a Yosys JSON module with physical cells dropped and clock-tree cells
    (synth.cell_kinds(); none when pre_cts) bypassed."""
    parent = {}
    kinds = cell_kinds(module, pre_cts)

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    port_bits = {b for p in module["ports"].values() for b in p["bits"] if isinstance(b, int)}
    cells = {}
    for name, cell in module["cells"].items():
        kind = kinds[name]
        if kind == "physical":
            continue
        if kind == "clock":
            ins = [b for p, bits in cell["connections"].items() if cell.get("port_directions", {}).get(p) == "input" for b in bits]
            outs = [b for p, bits in cell["connections"].items() if cell.get("port_directions", {}).get(p) == "output" for b in bits]
            if not ins or not outs:  # no directions in the JSON: sky130 clkbuf is A -> X
                ins, outs = cell["connections"].get("A", []), cell["connections"].get("X", [])
            (i,), (o,) = ins, outs
            ri, ro = find(i), find(o)
            if ri != ro:
                # keep a port bit as representative so port labels survive
                if ro in port_bits and ri not in port_bits:
                    ri, ro = ro, ri
                parent[ro] = ri
            continue
        cells[name] = cell
    remap = lambda bits: [find(b) if isinstance(b, int) else b for b in bits]
    new_cells = {
        n: dict(c, connections={p: remap(bits) for p, bits in c["connections"].items()}) for n, c in cells.items()
    }
    return {"ports": module["ports"], "cells": new_cells, "netnames": module.get("netnames", {})}


def bit_names(module):
    names = {}
    for name, net in module.get("netnames", {}).items():
        for b in net["bits"]:
            if isinstance(b, int):
                names.setdefault(b, set()).add(name)
    return names


def names(ours, ref, ours_pre_cts=True, ref_pre_cts=False):
    """Name-level identity after clock-buffer collapse.

    Every logic cell of `ref` must exist in `ours` under the same instance name with the same
    master, and on every signal pin the two nets must share at least one name (a net has
    several names in a flattened Yosys module: the top-level wire and the submodule port
    wires; a reference clock-tree net is represented by its root, the clock port).
    """
    o, r = collapse_clock_buffers(ours, ours_pre_cts), collapse_clock_buffers(ref, ref_pre_cts)
    on, rn = bit_names(ours), bit_names(ref)
    oc, rc = o["cells"], r["cells"]
    bad = []
    for name, cell in sorted(rc.items()):
        mine = oc.get(name)
        if mine is None:
            bad.append({"cell": name, "problem": "missing in ours"})
            continue
        if mine["type"] != cell["type"]:
            bad.append({"cell": name, "problem": f"type {mine['type']} vs {cell['type']}"})
            continue
        for pin, bits in cell["connections"].items():
            if pin in netgraph.SUPPLY:
                continue
            for rb, ob in zip(bits, mine["connections"].get(pin, [])):
                if isinstance(rb, str) or isinstance(ob, str):
                    ok = rb == ob
                else:
                    ok = bool(rn.get(rb, set()) & on.get(ob, set()))
                if not ok:
                    bad.append({"cell": name, "pin": pin, "ref": sorted(rn.get(rb, [rb])) if not isinstance(rb, str) else rb,
                                "ours": sorted(on.get(ob, [ob])) if not isinstance(ob, str) else ob})
    extra = sorted(set(oc) - set(rc))
    return {"ref_cells": len(rc), "ours_cells": len(oc), "extra_in_ours": extra, "mismatches": bad,
            "identical": not bad and not extra}


def structure(ours, ref, ours_pre_cts=True, ref_pre_cts=False):
    ga = netgraph.graph(collapse_clock_buffers(ours, ours_pre_cts))
    gb = netgraph.graph(collapse_clock_buffers(ref, ref_pre_cts))
    stats = lambda g: {k: sum(1 for _n, d in g.nodes(data=True) if d["kind"] == k) for k in ("cell", "net", "const")}
    return netgraph.isomorphic(ga, gb), stats(ga), stats(gb)


def compare(ours_v, ours_top, ref_v, ref_top, iso=True, ours_pre_cts=True, ref_pre_cts=False):
    """ours_pre_cts / ref_pre_cts: whether each netlist is a synthesis result, before CTS
    (synth.cell_kinds()); by default ours is and the reference is not."""
    ours, ref = load_module(ours_v, ours_top), load_module(ref_v, ref_top)
    ho, hr = histogram_of_module(ours, pre_cts=ours_pre_cts), histogram_of_module(ref, pre_cts=ref_pre_cts)
    dist, diff = distance(ho["by_kind"]["logic"], hr["by_kind"]["logic"])
    res = {
        "distance": dist,
        "diff_ours_minus_ref": diff,
        "ours": ho,
        "ref": hr,
        "ours_per_instance": per_instance(ours, ours_pre_cts),
        "ref_per_instance": per_instance(ref, ref_pre_cts),
    }
    if iso:
        same, so, sr = structure(ours, ref, ours_pre_cts, ref_pre_cts)
        res["isomorphic"] = same
        res["graph_stats"] = {"ours": so, "ref": sr}
        nm = names(ours, ref, ours_pre_cts, ref_pre_cts)
        res["names"] = dict(nm, mismatches=nm["mismatches"][:50], extra_in_ours=nm["extra_in_ours"][:50],
                            n_mismatches=len(nm["mismatches"]), n_extra=len(nm["extra_in_ours"]))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ours")
    ap.add_argument("ours_top")
    ap.add_argument("ref")
    ap.add_argument("ref_top")
    ap.add_argument("--no-iso", action="store_true")
    ap.add_argument("--ours-post-cts", action="store_true",
                    help="OURS is a netlist after CTS (default: a synthesis result, no clock-tree cells)")
    ap.add_argument("--ref-pre-cts", action="store_true",
                    help="REF is a synthesis result, before CTS (default: after CTS)")
    ap.add_argument("--json", help="write the full result here")
    a = ap.parse_args(argv)
    res = compare(a.ours, a.ours_top, a.ref, a.ref_top, iso=not a.no_iso,
                  ours_pre_cts=not a.ours_post_cts, ref_pre_cts=a.ref_pre_cts)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(res, f, indent=1)
    print(f"logic-cell histogram distance: {res['distance']}  (ours - ref: {res['diff_ours_minus_ref']})")
    print(f"logic cells ours {res['ours']['logic']} ref {res['ref']['logic']}")
    if "isomorphic" in res:
        print(f"isomorphic after clock-buffer collapse: {res['isomorphic']}  {res['graph_stats']}")
        n = res["names"]
        print(f"same instance names, masters and pin nets (names) as ref: {n['identical']}  "
              f"(ref cells {n['ref_cells']}, ours {n['ours_cells']}, mismatches {n['n_mismatches']}, extra {n['n_extra']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
