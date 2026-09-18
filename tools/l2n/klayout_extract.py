"""RETRACE extractor 2 (independent): KLayout LayoutToNetlist, hierarchical.

Shares no code with tools/retrace/extract.py. KLayout builds connectivity from its own
layer rules; each std-cell master becomes a circuit whose pins are the cell-internal nets
that connect upward, named from the cell's own labels. The result is reduced to
{(instance key, pin)} partitions for comparison, where the instance key is
"master@x,y" with x, y the GDS reference origin in DBU (the subcircuit displacement).
Net names come from the top-level labels (ports, VPWR/VGND).

    python -m tools.l2n.klayout_extract GDS --json OUT.json
"""

import argparse
import json
import sys

import klayout.db as kdb

# (layer, datatype) sets merged into one conductor per metal level
CONDUCTORS = {
    "li1": [(67, 20), (67, 16)],
    "met1": [(68, 20), (68, 16)],
    "met2": [(69, 20), (69, 16)],
    "met3": [(70, 20), (70, 16)],
    "met4": [(71, 20), (71, 16)],
    "met5": [(72, 20), (72, 16)],
}
CUTS = [("mcon", (67, 44), "li1", "met1"), ("via", (68, 44), "met1", "met2"), ("via2", (69, 44), "met2", "met3"),
        ("via3", (70, 44), "met3", "met4"), ("via4", (71, 44), "met4", "met5")]
LABELS = {"li1": (67, 5), "met1": (68, 5), "met2": (69, 5), "met3": (70, 5), "met4": (71, 5), "met5": (72, 5)}
PREFIX = "sky130_fd_sc_hd__"


def extract(gds):
    layout = kdb.Layout()
    layout.read(gds)
    top = layout.top_cell()
    l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(layout, top, []))
    l2n.include_floating_subcircuits = True
    cond = {}
    for name, lds in CONDUCTORS.items():
        region = None
        for layer, dt in lds:
            r = l2n.make_layer(layout.layer(layer, dt), f"{name}_{dt}")
            region = r if region is None else region + r
        cond[name] = region
        l2n.register(region, name)
    for name, ld in LABELS.items():
        txt = l2n.make_text_layer(layout.layer(*ld), f"{name}_lbl")
        l2n.connect(cond[name], txt)
    # gate poly joins li1 islands of one pin (licon); diffusion is left out on purpose,
    # so transistor source and drain never merge
    # minus the poly-resistor marker (66/15, conb_1), so tie outputs stay off the supplies
    poly = l2n.make_layer(layout.layer(66, 20), "poly_all") - l2n.make_layer(layout.layer(66, 15), "poly_res")
    l2n.register(poly, "poly")
    licon = l2n.make_layer(layout.layer(66, 44), "licon")
    l2n.connect(poly)
    l2n.connect(poly, licon)
    l2n.connect(licon, cond["li1"])
    for name, ld, lo, hi in CUTS:
        cut = l2n.make_layer(layout.layer(*ld), name)
        l2n.connect(cond[lo])
        l2n.connect(cond[lo], cut)
        l2n.connect(cut, cond[hi])
    l2n.connect(cond["met5"])
    l2n.extract_netlist()
    return layout, top, l2n


def partitions(layout, top, l2n):
    nl = l2n.netlist()
    tc = nl.circuit_by_name(top.name)
    dbu = layout.dbu
    result = []
    for net in tc.each_net():
        members = []
        for sp in net.each_subcircuit_pin():
            sc = sp.subcircuit()
            master = sc.circuit_ref().name
            if not master.startswith(PREFIX):
                continue
            d = sc.trans.disp  # the GDS reference origin, in um
            key = f"{master}@{round(d.x / dbu)},{round(d.y / dbu)}"
            members.append((key, sp.pin().name()))
        ports = sorted(p.pin().name() for p in net.each_pin() if p.pin().name())
        result.append({"name": net.name, "members": sorted(members), "ports": ports})
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("gds")
    ap.add_argument("--json", required=True)
    args = ap.parse_args(argv)
    layout, top, l2n = extract(args.gds)
    parts = partitions(layout, top, l2n)
    with open(args.json, "w") as f:
        json.dump(parts, f, indent=1)
    print(f"{len(parts)} top-level nets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
