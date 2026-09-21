#!/usr/bin/env python3
"""N-well census of a sky130_fd_sc_hd layout: why a no-fill layout fails DRC/LVS.

    .venv/bin/python tools/roundtrip/puzzle/wells.py GDS [GDS...] [--json OUT]

sky130_fd_sc_hd cells are tapless: only the tap cell (tapvpwrvgnd_1) ties the
n-well to VPWR through an N+ tap.  Abutting cells merge their n-wells into
one strip per row pair, so a continuous row reaches a tap every ~13 um; a gap
between two cells (no fill cell in it) splits the strip.  This script flattens
the layout with KLayout, merges n-well (64/20) into islands and reports, for
each GDS:

  islands           merged n-well regions
  untapped          islands with no N+ tap (tap 65/44 & nsdm 93/44 & licon
                    66/44) inside: Magic nwell.4; each one is a floating
                    VPB node, i.e. one extra layout net in LVS
  narrow_gaps       n-well spacings < 1.27 um (nwell.2a), from gaps of 1-2
                    sites between cells
  pdiff_far_from_ntap_LU3  P+ diffusion (diff & psdm inside n-well) farther
                    than 15 um from an N+ tap of its own n-well island (so all
                    P+ in an untapped island), merged regions (Magic LU.3)

These are geometric counts from our own layer arithmetic, not a DRC deck; the
Magic/KLayout DRC and netgen LVS numbers LibreLane records are the sign-off
results.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import klayout.db as kdb

NWELL, DIFF, TAP, NSDM, PSDM, LICON = (64, 20), (65, 20), (65, 44), (93, 44), (94, 20), (66, 44)


def region(layout: kdb.Layout, top: kdb.Cell, ld: tuple[int, int]) -> kdb.Region:
    li = layout.find_layer(*ld)
    if li is None:
        return kdb.Region()
    return kdb.Region(top.begin_shapes_rec(li))


def census(gds: Path) -> dict:
    layout = kdb.Layout()
    layout.read(str(gds))
    top = layout.top_cells()
    top = max(top, key=lambda c: c.bbox().area())
    um = layout.dbu
    nwell = region(layout, top, NWELL).merged()
    ntap = (region(layout, top, TAP) & region(layout, top, NSDM)).interacting(region(layout, top, LICON)) & nwell
    islands = list(nwell.each())
    tapped = nwell.interacting(ntap)
    untapped = nwell.not_interacting(ntap)
    pdiff = (region(layout, top, DIFF) & region(layout, top, PSDM) & nwell).merged()
    # LU.3 is about the tap in the same well: all P+ in an untapped island is
    # out of reach; in a tapped island, P+ farther than 15 um from its taps.
    far = pdiff.interacting(untapped)
    d15 = int(round(15.0 / um))
    for poly in tapped.each():
        isl = kdb.Region(poly)
        far += (pdiff & isl) - ((ntap & isl).sized(d15) & isl)
    gaps = nwell.space_check(int(round(1.27 / um)))
    narrow = nwell.width_check(int(round(0.84 / um)))
    return {
        "gds": str(gds),
        "top": top.name,
        "islands": len(islands),
        "tapped": tapped.count(),
        "untapped": untapped.count(),
        "untapped_area_um2": round(untapped.area() * um * um, 1),
        "tapped_area_um2": round(tapped.area() * um * um, 1),
        "ntaps": ntap.merged().count(),
        "narrow_gaps_nwell_2a": gaps.count(),
        "narrow_nwell_1": narrow.count(),
        "pdiff_regions": pdiff.count(),
        "pdiff_in_untapped_islands": pdiff.interacting(untapped).count(),
        "pdiff_far_from_ntap_LU3": far.merged().count(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("gds", nargs="+", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    rows = [census(g) for g in a.gds]
    for r in rows:
        print(json.dumps(r))
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1) + "\n")


if __name__ == "__main__":
    main()
