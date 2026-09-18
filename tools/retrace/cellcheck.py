"""Compare the standard-cell masters embedded in a design GDS with a PDK's cell GDS.

The extractor trusts cell masters (a cell is its name plus its pins), so any
geometric difference between a design's copy of a master and the PDK's copy is
reported per layer. Polygons are compared as normalised vertex sets on a 1 nm
grid, independent of polygon order and starting vertex.

    python tools/retrace/cellcheck.py DESIGN.gds PDK.gds [PDK2.gds ...]
    python tools/retrace/cellcheck.py --json DESIGN.gds PDK.gds ...
"""

import argparse
import collections
import json
import sys

import gdstk

PREFIX = "sky130_fd_sc_hd__"


def _norm(poly):
    pts = [tuple(p) for p in (poly.points * 1000).round().astype(int).tolist()]
    # rotate to the lexicographically smallest start, keep winding-independent
    i = pts.index(min(pts))
    fwd = pts[i:] + pts[:i]
    rev = [fwd[0]] + fwd[1:][::-1]
    return tuple(min(fwd, rev))


def layer_shapes(cell):
    by_layer = collections.defaultdict(collections.Counter)
    for p in cell.get_polygons():
        by_layer[(p.layer, p.datatype)][_norm(p)] += 1
    return by_layer


def masters(path):
    return {c.name: c for c in gdstk.read_gds(path).cells if c.name.startswith(PREFIX)}


def compare(design, pdk):
    """Return {master: {(layer, datatype): (only_design, only_pdk)}} for differing masters."""
    diffs = {}
    for name, cell in sorted(design.items()):
        if name not in pdk:
            diffs[name] = "missing-in-pdk"
            continue
        a, b = layer_shapes(cell), layer_shapes(pdk[name])
        per = {}
        for key in sorted(set(a) | set(b)):
            only_a = sum((a[key] - b[key]).values())
            only_b = sum((b[key] - a[key]).values())
            if only_a or only_b:
                per[key] = (only_a, only_b)
        if per:
            diffs[name] = per
    return diffs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("design")
    ap.add_argument("pdk", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    design = masters(args.design)
    report = {}
    for path in args.pdk:
        d = compare(design, masters(path))
        report[path] = {
            m: (v if isinstance(v, str) else {f"{l}/{t}": list(n) for (l, t), n in v.items()})
            for m, v in d.items()
        }
    if args.json:
        json.dump({"design": args.design, "masters": len(design), "pdk": report}, sys.stdout, indent=1)
        print()
        return 0
    print(f"{args.design}: {len(design)} {PREFIX}* masters")
    for path, d in report.items():
        print(f"{path}: {len(design) - len(d)} identical, {len(d)} differ")
        for m, v in d.items():
            detail = v if isinstance(v, str) else ", ".join(f"{k} +{a}/-{b}" for k, (a, b) in v.items())
            print(f"  {m[len(PREFIX):]}: {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
