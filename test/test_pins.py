"""V2: pin geometry of every master used, against the PDK LEF.

For each signal pin, every LEF port rectangle on li1/met1 must lie on our extracted pin
conductor of the same name, and on no other pin's. This is what catches pins made of
several islands (a met1 strap, or two li1 islands on one gate poly).
"""

import functools

import pytest
from shapely.geometry import Polygon, box

from tools.retrace.extract import PREFIX, SUPPLY_PINS, Extraction
from tools.retrace.lef import read_lef

LEF = "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"
DESIGNS = ["upstream/warmup/04_final.gds", "upstream/puzzle.gds"]
LAYER = {"li1": 67, "met1": 68}


@functools.cache
def lef():
    return read_lef(LEF)


@functools.cache
def extraction(gds):
    return Extraction(gds, lef())


def _masters(gds):
    ex = extraction(gds)
    return sorted({c.name: c for c in ex.lib.cells if c.name.startswith(PREFIX)}.items())


@pytest.mark.parametrize("gds", DESIGNS)
def test_v2_pin_sets_match_lef(gds):
    ex = extraction(gds)
    bad = []
    for name, cell in _masters(gds):
        # VPB/VNB are the n-well and substrate body pins: no li1/met1 geometry, no logic
        ours = set(ex._master_pins(cell))
        theirs = {p for p, d in lef()[name]["pins"].items() if d["rects"] and p not in ("VPB", "VNB")}
        if ours != theirs:
            bad.append((name, sorted(ours ^ theirs)))
    assert not bad, bad


@pytest.mark.parametrize("gds", DESIGNS)
def test_v2_lef_rects_on_extracted_pin(gds):
    ex = extraction(gds)
    bad = []
    for name, cell in _masters(gds):
        pins = ex._master_pins(cell)
        geo = {p: {lyr: [Polygon(q.points) for q in polys if q.layer == lyr] for lyr in LAYER.values()}
               for p, polys in pins.items()}
        for pin, d in lef()[name]["pins"].items():
            if pin in SUPPLY_PINS:
                continue
            for layer, x0, y0, x1, y1 in d["rects"]:
                if layer not in LAYER:
                    continue
                c = box(x0, y0, x1, y1).centroid
                owners = [p for p, g in geo.items() if any(q.buffer(1e-6).covers(c) for q in g[LAYER[layer]])]
                if owners != [pin]:
                    bad.append((name, pin, layer, (x0, y0, x1, y1), owners))
    assert not bad, bad[:10]
