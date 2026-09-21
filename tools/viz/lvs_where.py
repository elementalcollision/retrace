"""Where the TEMPO LVS found something, drawn on the die (PRD S1).

Reads the full report that `python -m tools.tempo.lvs --json REPORT.json` writes and
highlights every instance a check named: (a) placements, (b)/(c) mismatched nets, (e)
undriven or multiply driven nets and supply pins off the main supply net, and the place
where a supply short joins the supplies. Instances named by the same checks are grouped by
distance, and each group is ringed and labelled with those checks. A clean report draws
nothing but the die. Run by TEMPO's CI when the LVS fails.

    python -m tools.viz.lvs_where REPORT.json OUT.png [HEADING]
    python -m tools.viz.lvs_where --panel REPORT.json OUT.png    # transparent, no text but the
                                                                 # labels: for a page with its own
                                                                 # light and dark themes
"""

import collections
import json
import sys

from ..tempo import lvs
from .layout import LIGHT, NEUTRAL, png_panel, png_sheet
from .tempo import design

NEAR = 25.0  # um: flagged instances closer than this share a ring


def _groups(rects, near=NEAR):
    """Cluster rectangles whose gap is under `near` (union-find over a coarse grid)."""
    parent = list(range(len(rects)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    grid = collections.defaultdict(list)
    for k, (x0, y0, x1, y1) in enumerate(rects):
        for gx in range(int(x0 // near), int(x1 // near) + 1):
            for gy in range(int(y0 // near), int(y1 // near) + 1):
                grid[(gx, gy)].append(k)
    for (gx, gy), ks in grid.items():
        near_ks = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in grid.get((gx + dx, gy + dy), ())]
        for a in ks:
            for b in near_ks:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb
    out = collections.defaultdict(list)
    for k in range(len(rects)):
        out[find(k)].append(k)
    return list(out.values())


def findings(report, die, d):
    """{DEF instance name: set of check labels}, plus [(label, box)] supply short sites."""
    gds_to_def = {}
    for name, (m, x, y, _o) in d["components"].items():
        short = m[len(lvs.IHP_SG13CMOS5L.prefix):] if m.startswith(lvs.IHP_SG13CMOS5L.prefix) else m
        gds_to_def[f"{short}_{x}_{y}"] = name
    flags = collections.defaultdict(set)
    a = report.get("a_placements", {})
    for n in a.get("only_def", []):
        flags[n].add("(a)")
    for n in a.get("only_gds", []):
        flags[gds_to_def.get(n, n)].add("(a)")
    for key, tag in (("b_def_nets", "(b)"), ("c_nl_v", "(c)")):
        for n in report.get(key, {}).get("mismatched_instances", []):
            flags[n].add(tag)
    e = report.get("e_sanity", {})
    for key, tag in (("no_driver_instances", "(e) undriven"), ("multi_driver_instances", "(e) 2 drivers"),
                     ("supply_stray_instances", "(e) off-grid supply")):
        for n in e.get(key, []):
            flags[gds_to_def.get(n, n)].add(tag)
    shorts = [("(e) VDD-VSS short", tuple(p["at"])) for site in e.get("supply_short_at", []) for p in site[:1]]
    return {n: t for n, t in flags.items() if n in die.cells}, shorts


def marks(flags, shorts, die):
    """One ring per group: instances flagged by the same checks, clustered by distance."""
    by_tags = collections.defaultdict(list)
    for n in sorted(flags):
        by_tags[tuple(sorted(flags[n]))].append(n)
    out = []
    for tags, names in sorted(by_tags.items()):
        rects = [die.cells[n] for n in names]
        for group in _groups(rects):
            xs0, ys0, xs1, ys1 = zip(*(rects[k] for k in group))
            out.append((" ".join(tags), (min(xs0), min(ys0), max(xs1), max(ys1))))
    return out + shorts


def main(argv=None):
    argv = list(argv or sys.argv[1:])
    panel = "--panel" in argv
    argv = [a for a in argv if a != "--panel"]
    report_path, out = argv[0], argv[1]
    heading = argv[2] if len(argv) > 2 else f"TEMPO LVS findings: {report_path}"
    report = json.load(open(report_path))
    die, d, _lef, _logic, _master = design()
    flags, shorts = findings(report, die, d)
    ms = marks(flags, shorts, die)
    d2 = {m: [b["pin"] for b in v["bad"]] for m, v in report.get("d2_pin_geometry", {}).items() if v["bad"]}
    sub = f"{len(flags)} logic cells flagged, in {len(ms)} places"
    if d2:
        sub += "; (d2) misplaced pins in master " + "; ".join(f"{m}: {', '.join(p)}" for m, p in d2.items())
    if panel:
        png_panel(die, set(flags), out, width_px=1040, colours={**NEUTRAL, "hi": NEUTRAL["flag"]}, marks=ms)
    else:
        png_sheet(die, [("Where the LVS found something", sub, set(flags), ms)], out, cols=1, panel_w=1200,
                  colours={**LIGHT, "hi": LIGHT["flag"]}, heading=heading)
    for label, box in ms:
        print(f"{label:40s} at x {box[0]:.1f}-{box[2]:.1f}, y {box[1]:.1f}-{box[3]:.1f} um")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
