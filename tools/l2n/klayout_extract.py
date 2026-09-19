"""RETRACE extractor 2 (independent): KLayout LayoutToNetlist, hierarchical.

Shares no code with tools/retrace/extract.py: this module builds its own connectivity
from KLayout's own region/L2N engine. The only thing it takes from
tools/retrace/tech.py is layer numbers/datatypes -- the `Tech` table that says which
GDS layers are which conductor, cut and label -- never any of extractor 1's
union-find/algorithm code.

Each std-cell (or macro) master becomes a circuit whose pins are the cell-internal
nets that connect upward, named from the cell's own labels. A macro
(`tech.macro_prefixes`, e.g. TEMPO's SRAM) is *not* special-cased: KLayout's
hierarchical netlist extraction already keeps every distinct referenced cell as its
own circuit and only surfaces that circuit's own top-level pins to its parent, so a
macro instance naturally appears to the top circuit as one subcircuit whose pins are
its own labelled nets -- its internal sub-hierarchy (e.g. the SRAM's ~50 sub-cells)
is extracted into its own nested circuits and never flattened into chip nets. This is
option 2 of the task brief ("keep it as a subcircuit whose pins come from its
top-level labels").

The result is reduced to {(instance key, pin)} partitions for comparison, where the
instance key is "master@x,y" with x, y the GDS reference origin in DBU (the
subcircuit displacement). Net names come from the top-level labels (ports,
supply pins).

    python -m tools.l2n.klayout_extract GDS --json OUT.json [--tech ihp_sg13cmos5l]
"""

import argparse
import json
import sys

import klayout.db as kdb

from ..retrace.tech import IHP_SG13CMOS5L
from ..retrace.tech import SKY130_HD

TECHS = {SKY130_HD.name: SKY130_HD, IHP_SG13CMOS5L.name: IHP_SG13CMOS5L}


def extract(gds, tech=SKY130_HD):
    layout = kdb.Layout()
    layout.read(gds)
    top = layout.top_cell()
    l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(layout, top, []))
    l2n.include_floating_subcircuits = True

    cond = {}
    for c in tech.conductors:
        region = None
        for dt in c.datatypes:
            r = l2n.make_layer(layout.layer(c.layer, dt), f"{c.name}_{dt}")
            region = r if region is None else region + r
        cond[c.name] = region
        l2n.register(region, c.name)
        txt = l2n.make_text_layer(layout.layer(c.layer, c.label_dt), f"{c.name}_lbl")
        l2n.connect(region, txt)

    # gate poly joins pin-conductor islands of one pin (poly_cut, e.g. licon/Cont);
    # diffusion is left out on purpose, so transistor source and drain never merge.
    # poly_resistor_cut (sky130 only, see tech.py) removes the marker shape first, so
    # a tie cell's output stays off the supply through the gate poly.
    if tech.poly_layer is not None:
        if tech.poly_resistor_cut is not None:
            poly = l2n.make_layer(layout.layer(*tech.poly_layer), "poly_all") - \
                l2n.make_layer(layout.layer(*tech.poly_resistor_cut), "poly_res")
            l2n.register(poly, "poly")  # difference is a fresh, not-yet-registered region
        else:
            poly = l2n.make_layer(layout.layer(*tech.poly_layer), "poly")  # already registered by make_layer
        pcut = l2n.make_layer(layout.layer(*tech.poly_cut), "poly_cut")
        l2n.connect(poly)
        l2n.connect(poly, pcut)
        # only the lowest pin conductor (extract.py: `layer_names[0]`, sky130 li1 /
        # IHP Metal1) -- never met1, so a std cell's local routing above li1 is not
        # dragged into the gate-poly join
        l2n.connect(pcut, cond[tech.pin_conductors[0]])

    for cut in tech.cuts:
        cl = l2n.make_layer(layout.layer(cut.layer, cut.datatype), f"cut_{cut.layer}_{cut.datatype}")
        l2n.connect(cond[cut.below])
        l2n.connect(cond[cut.below], cl)
        l2n.connect(cl, cond[cut.above])
    l2n.connect(cond[tech.conductors[-1].name])
    l2n.extract_netlist()
    return layout, top, l2n


def partitions(layout, top, l2n, tech=SKY130_HD):
    nl = l2n.netlist()
    tc = nl.circuit_by_name(top.name)
    dbu = layout.dbu
    masters = set(tech.macro_prefixes) | {tech.prefix}
    result = []
    for net in tc.each_net():
        members = []
        for sp in net.each_subcircuit_pin():
            sc = sp.subcircuit()
            master = sc.circuit_ref().name
            if not (master.startswith(tech.prefix) or master in tech.macro_prefixes):
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
    ap.add_argument("--tech", default=SKY130_HD.name, choices=sorted(TECHS))
    args = ap.parse_args(argv)
    tech = TECHS[args.tech]
    layout, top, l2n = extract(args.gds, tech)
    parts = partitions(layout, top, l2n, tech)
    with open(args.json, "w") as f:
        json.dump(parts, f, indent=1)
    print(f"{len(parts)} top-level nets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
