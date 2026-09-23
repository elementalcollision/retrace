"""Cut shapes drawn in the top cell (Freeze 2): tools/retrace/extract.py binds them itself.

Magic's stream-out and every Tiny Tapeout layout draw each via as bare cut polygons in the top
cell instead of a VIA_* cell reference. `Extraction(top_cuts=True)` (the default) joins the
conductors below and above such a cut exactly as it would inside a via cell; `top_cuts=False` is
the extractor before Freeze 2, which dropped them silently. Oracles, each able to fail:

  (a) no-op where there is nothing to bind: the puzzle and the warm-up have no top-level cut shape,
      and their extraction (summary, JSON, Verilog) is byte-identical with and without the rule;
      the puzzle's anonymous netlist hash still equals the one out/s3/FREEZE.json pins (TEMPO too,
      with TEMPO_ROOT=out/s3/tempo_snapshot; skipped otherwise: about 20 s and 4 GB)
  (b) positive, synthetic: the warm-up with every via-cell reference flattened into top-level cut
      shapes (half of them written as GDS paths) has the same (instance, pin, label) partition
  (c) negative control for (b): the same copy with top_cuts=False does not (its vias are open)
  (d) positive, real: a Tiny Tapeout layout already in the blind cache (the pilot ttsky25a/tt_um_BNN,
      an excluded design) extracts to the same partition raw and after thirdparty.prepare_layout,
      which moves the top-level cuts into a via cell; skipped when the cache file is absent
plus tools/roundtrip/check.py's use of the rule (bound once, not twice; --no-flat-cuts keeps the
old numbers) and tools/retrace/mutate.py's via-delete sites (a TOP cut is never one).
"""

import collections
import json
import os

import gdstk
import pytest

from tools.l2n.compare import partition_ours
from tools.retrace.extract import TOP_CUT, Extraction
from tools.retrace.lef import read_lef
from tools.retrace.tech import IHP_SG13CMOS5L, SKY130_HD

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEF = os.path.join(ROOT, "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef")
PUZZLE = os.path.join(ROOT, "upstream/puzzle.gds")
WARMUP = os.path.join(ROOT, "upstream/warmup/04_final.gds")
WARMUP_TOP = "adder_demo"
FREEZE = os.path.join(ROOT, "out/s3/FREEZE.json")
TEMPO_SNAPSHOT = os.path.join(ROOT, "out/s3/tempo_snapshot")
TEMPO_GDS = "runs/wokwi/final/gds/tt_um_elementalcollision_tempo.gds"
PILOT_ID, PILOT_TOP = "ttsky25a/tt_um_BNN", "tt_um_BNN"  # candidates.json "excluded", role pilot

# the keys summary() had before Freeze 2; the rule must not add one (not even a zero count)
SUMMARY_KEYS = {"top", "instances", "logic_instances", "ports", "nets", "signal_nets", "diagnostics"}


def need(*paths):
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        pytest.skip(f"missing: {[os.path.relpath(p, ROOT) for p in missing]}")


@pytest.fixture(scope="module")
def lef():
    need(LEF)
    return read_lef(LEF)


def top_cut_shapes(gds, top, tech=SKY130_HD):
    """{"polygon": n, "path": n}: cut shapes (tech.cuts) drawn directly in cell `top`."""
    keys = {(c.layer, c.datatype) for c in tech.cuts}
    cell = next(c for c in gdstk.read_gds(gds).top_level() if c.name == top)
    return {"polygon": sum(1 for p in cell.polygons if (p.layer, p.datatype) in keys),
            "path": sum(1 for pa in cell.paths for q in pa.to_polygons() if (q.layer, q.datatype) in keys)}


def partition(ex):
    """(master@GDS origin, pin) and label members of every net: the partition V4 and XS compare
    (tools/l2n/compare.py, tools/roundtrip/check.py stream_partition), independent of net ids."""
    return partition_ours(ex, set(ex.ports) | set(ex.supply_labels))


def outputs(ex, lef):
    return (json.dumps(ex.summary(), indent=1), json.dumps(ex.to_json(), indent=1), ex.to_verilog({}, lef))


def cuts_by_layer(ex, owner=None):
    return collections.Counter(f"{c.below}-{c.above}" for c, _g, v in ex._cuts if owner is None or v == owner)


# ---- (a) no-op where the layout has no top-level cut ------------------------------------------


@pytest.mark.parametrize("gds,top", [(WARMUP, WARMUP_TOP), (PUZZLE, "puzzle")], ids=["warmup", "puzzle"])
def test_no_top_level_cuts_is_a_byte_identical_no_op(lef, gds, top):
    need(gds)
    assert top_cut_shapes(gds, top) == {"polygon": 0, "path": 0}
    old = Extraction(gds, lef, top, top_cuts=False)
    new = Extraction(gds, lef, top)  # the default
    assert new.top_cuts and not old.top_cuts
    assert set(new.summary()) == SUMMARY_KEYS
    assert new.flat_cuts == {} and old.flat_cuts == {}
    assert not any(v == TOP_CUT for _l, _g, v in new.cuts)
    assert [(lyr, g.wkb, v) for lyr, g, v in new.cuts] == [(lyr, g.wkb, v) for lyr, g, v in old.cuts]
    for a, b in zip(outputs(old, lef), outputs(new, lef)):
        assert a == b


# Freeze 1 (commit 232cfe6) literals. FREEZE.json is rewritten by Freeze 2 FROM THIS CODE, so a test
# that only compares against the file on disk would become self-referential; these pin the values
# the extractor produced BEFORE Freeze 2, computed from HEAD's tools/ (git archive) on 2026-09-23.
FREEZE1_NETLIST_SHA256 = {
    "puzzle": "517f388c7ae6dc477f0c0e3c05aa14072ffc60af5d304a98bf51b9745d9df724",
    "tempo": "e0ef11c95a25d0cc0970c828a38d367f21cfe4430cba748b05f18fa78969fa87",
}
PRE_FREEZE2_WARMUP_SHA256 = {   # sha256 of Extraction(warm-up) outputs from the pre-Freeze-2 extractor
    "to_json": "02e9e26e8caef8e00de652a5b0a6aae7f1352c0c12330037948713d529f27829",
    "to_verilog": "9f95e2d7fb14b627bc13c93c6679d92e4f4cb10c45832a917eb4d9bf59b280c3",
}


def test_warmup_outputs_equal_the_pre_freeze2_extractor():
    """Both modes reproduce, byte for byte, what the extractor wrote before Freeze 2: a regression
    common to top_cuts=True and False would pass the True-vs-False comparison above but not this."""
    import hashlib

    need(WARMUP)
    lef = read_lef(LEF)
    h = lambda s: hashlib.sha256(s.encode()).hexdigest()
    for tc in (True, False):
        ex = Extraction(WARMUP, lef, top_cuts=tc)
        j = ex.to_json()
        j = j if isinstance(j, str) else json.dumps(j, sort_keys=True)
        assert h(j) == PRE_FREEZE2_WARMUP_SHA256["to_json"], tc
        assert h(ex.to_verilog()) == PRE_FREEZE2_WARMUP_SHA256["to_verilog"], tc


def _frozen_input(design):
    need(FREEZE)
    with open(FREEZE) as f:
        fr = json.load(f)
    pinned = (fr.get("inputs") or {}).get(design)
    if not pinned:
        pytest.skip(f"out/s3/FREEZE.json pins no input {design!r}")
    return pinned


def test_puzzle_netlist_hash_equals_freeze():
    """tools.s3.freeze.pin_design("puzzle") (the S3 loader over extract.py) reproduces the frozen
    anonymous-netlist hash."""
    need(PUZZLE)
    pinned = _frozen_input("puzzle")
    from tools.s3 import freeze

    got = freeze.pin_design("puzzle")
    assert got["files"] == pinned["files"]
    assert got["netlist_sha256"] == pinned["netlist_sha256"]
    assert got["netlist_sha256"] == FREEZE1_NETLIST_SHA256["puzzle"]


def _tempo_env_is_snapshot():
    env = os.environ.get("TEMPO_ROOT")
    return bool(env) and os.path.isdir(TEMPO_SNAPSHOT) and os.path.realpath(env) == os.path.realpath(TEMPO_SNAPSHOT)


@pytest.mark.skipif(not _tempo_env_is_snapshot(),
                    reason="TEMPO (~20 s, ~4 GB): run with TEMPO_ROOT=out/s3/tempo_snapshot and the snapshot present")
def test_tempo_netlist_hash_equals_freeze():
    """TEMPO (IHP, via tools/tempo/lvs.py's extraction) has no top-level cut shape, and
    pin_design("tempo") reproduces the frozen anonymous-netlist hash."""
    assert top_cut_shapes(os.path.join(TEMPO_SNAPSHOT, TEMPO_GDS), "tt_um_elementalcollision_tempo",
                          IHP_SG13CMOS5L) == {"polygon": 0, "path": 0}
    pinned = _frozen_input("tempo")
    from tools.s3 import freeze

    got = freeze.pin_design("tempo")
    assert got["files"] == pinned["files"]
    assert got["netlist_sha256"] == pinned["netlist_sha256"]
    assert got["netlist_sha256"] == FREEZE1_NETLIST_SHA256["tempo"]


# ---- (b)/(c) the warm-up with its vias flattened into top-level cut shapes ----------------------


def flatten_vias(src, top, dst, tech=SKY130_HD):
    """Copy of `src` with every via-cell reference of `top` replaced by its polygons drawn in `top`
    (the via cells themselves dropped). Every other cut shape is written as a GDS PATH (a flush
    2-point path covering the same rectangle), so both top-level forms are exercised. Returns
    the number of cut shapes written as paths."""
    lib = gdstk.read_gds(src)
    cell = next(c for c in lib.top_level() if c.name == top)
    keys = {(c.layer, c.datatype) for c in tech.cuts}
    refs = [r for r in cell.references if r.cell.name.startswith(tech.via_prefix)]
    as_path = n_cut = 0
    for r in refs:
        for p in r.get_polygons():
            if (p.layer, p.datatype) in keys:
                n_cut += 1
                (x0, y0), (x1, y1) = p.bounding_box()
                if n_cut % 2 and len(p.points) == 4 and abs(p.area() - (x1 - x0) * (y1 - y0)) < 1e-9:
                    ym = (y0 + y1) / 2
                    cell.add(gdstk.FlexPath([(x0, ym), (x1, ym)], y1 - y0, ends="flush",
                                            layer=p.layer, datatype=p.datatype, simple_path=True))
                    as_path += 1
                    continue
            cell.add(p)
    cell.remove(*refs)
    via_cells = {r.cell.name for r in refs}
    lib.remove(*[c for c in lib.cells if c.name in via_cells and c is not cell])
    lib.write_gds(dst)
    return as_path


def _rects(geoms):
    return collections.Counter(tuple(round(v, 4) for v in g.bounds) for g in geoms)


@pytest.fixture(scope="module")
def warmup_flat(lef, tmp_path_factory):
    need(WARMUP)
    orig = Extraction(WARMUP, lef, WARMUP_TOP)
    flat = str(tmp_path_factory.mktemp("topcuts") / "warmup_flat.gds")
    as_path = flatten_vias(WARMUP, WARMUP_TOP, flat)
    return orig, flat, as_path


def test_flattened_copy_is_the_same_geometry(warmup_flat):
    """Precondition for (b)/(c): no via-cell reference is left, every via-cell cut is now a
    top-level cut shape of the same rectangle, and some of them are paths."""
    orig, flat, as_path = warmup_flat
    cell = next(c for c in gdstk.read_gds(flat).top_level() if c.name == WARMUP_TOP)
    assert [c.name for c in gdstk.read_gds(flat).top_level()] == [WARMUP_TOP]
    assert not any(r.cell.name.startswith(SKY130_HD.via_prefix) for r in cell.references)
    n = top_cut_shapes(flat, WARMUP_TOP)
    assert n["path"] == as_path > 0 and n["polygon"] > 0
    assert n["polygon"] + n["path"] == len(orig.cuts) > 0
    keys = {(c.layer, c.datatype) for c in SKY130_HD.cuts}
    from shapely.geometry import Polygon

    shapes = [q for q in cell.polygons if (q.layer, q.datatype) in keys]
    shapes += [q for pa in cell.paths for q in pa.to_polygons() if (q.layer, q.datatype) in keys]
    assert _rects(Polygon(q.points) for q in shapes) == _rects(g for _c, g, _v in orig._cuts)


def test_flattened_vias_extract_to_the_same_partition(lef, warmup_flat):
    """(b) the top-level cuts, polygons and paths, join exactly what the via cells joined."""
    orig, flat, _as_path = warmup_flat
    ex = Extraction(flat, lef, WARMUP_TOP)
    assert partition(ex) == partition(orig)
    assert ex.summary() == orig.summary()
    assert sum(ex.flat_cuts.values()) == len(orig.cuts)
    assert ex.flat_cuts == cuts_by_layer(orig)
    assert cuts_by_layer(ex, TOP_CUT) == cuts_by_layer(orig) and cuts_by_layer(ex) == cuts_by_layer(orig)
    assert all(v == TOP_CUT for _l, _g, v in ex.cuts)


def test_flattened_vias_without_the_rule_are_open(lef, warmup_flat):
    """(c) negative control: with top_cuts=False the same copy loses every via (nets open)."""
    orig, flat, _as_path = warmup_flat
    ex = Extraction(flat, lef, WARMUP_TOP, top_cuts=False)
    assert ex.flat_cuts == {} and ex.cuts == []
    assert partition(ex) != partition(orig)
    assert ex.summary()["nets"] > orig.summary()["nets"]
    assert ex.summary()["signal_nets"] > orig.summary()["signal_nets"]


# ---- tools/roundtrip/check.py and tools/retrace/mutate.py over the same copy -------------------


def test_roundtrip_check_binds_each_top_cut_once(lef, warmup_flat):
    """check.extract builds Extraction(top_cuts=flat_cuts); FlatCutExtraction no longer adds the
    cuts a second time; --no-flat-cuts (flat_cuts=False) still reports every one ignored."""
    from tools.roundtrip import check

    orig, flat, _as_path = warmup_flat
    assert check.FLAT_CUT == TOP_CUT
    n = sum(top_cut_shapes(flat, WARMUP_TOP).values())
    for ex in (check.extract(flat, lef, WARMUP_TOP, True)[0], check.FlatCutExtraction(flat, lef, WARMUP_TOP)):
        assert check.top_level_cuts(ex) == n
        assert sum(ex.flat_cuts.values()) == n == sum(1 for _c, _g, v in ex._cuts if v == check.FLAT_CUT)
        assert check.top_level_cuts(ex) - sum(ex.flat_cuts.values()) == 0  # check_gds's "ignored"
        assert check.stream_partition(ex) == check.stream_partition(orig)
    ex, _dt = check.extract(flat, lef, WARMUP_TOP, False)
    assert not ex.top_cuts and ex.flat_cuts == {}
    assert check.top_level_cuts(ex) - sum(getattr(ex, "flat_cuts", {}).values()) == n


def test_mutate_via_delete_never_selects_a_top_cut(lef, warmup_flat):
    """tools/retrace/mutate.py's via-delete sites come from VIA_FAMILY names only: a layout whose
    vias are all top-level cuts offers none, and the warm-up's own sites are the same either way."""
    from tools.retrace import mutate

    orig, flat, _as_path = warmup_flat
    assert TOP_CUT not in mutate.VIA_FAMILY
    ex = Extraction(flat, lef, WARMUP_TOP)
    assert len(ex.cuts) == len(orig.cuts) and mutate.sites_via_delete(ex, lef) == []
    assert mutate.sites_via_delete(orig, lef)
    assert mutate.sites_via_delete(Extraction(WARMUP, lef, WARMUP_TOP, top_cuts=False), lef) \
        == mutate.sites_via_delete(orig, lef)


# ---- (d) a real Tiny Tapeout layout: raw vs thirdparty.prepare_layout ----------------------------


@pytest.fixture(scope="module")
def pilot_layout():
    from tools.s3 import thirdparty

    path = os.path.join(thirdparty.CACHE, "layout", PILOT_ID.replace("/", "__") + ".gds")
    if not os.path.exists(path):
        pytest.skip(f"{path} not cached (python -m tools.s3.thirdparty pilot fetches it)")
    with open(os.path.join(ROOT, "out/s3/blind/candidates.json")) as f:
        rec = next(r for r in json.load(f)["excluded"] if r["id"] == PILOT_ID)
    assert rec["role"] == "pilot"  # an excluded design, never a blind candidate
    with open(path, "rb") as f:
        assert thirdparty._git_blob_sha(f.read()) == rec["files"]["layout"]["git_blob"]
    return path


def test_tiny_tapeout_raw_equals_prepare_layout(lef, pilot_layout, tmp_path):
    """(d) the raw TT layout (every via a top-level cut) and prepare_layout's copy (cuts moved into
    one via cell) give the same partition; without the rule the raw layout does not."""
    from tools.s3 import thirdparty

    raw = str(tmp_path / os.path.basename(pilot_layout))
    with open(pilot_layout, "rb") as f, open(raw, "wb") as g:
        g.write(f.read())
    prep, moved = thirdparty.prepare_layout(raw, PILOT_TOP)
    assert prep != raw and moved > 0
    assert top_cut_shapes(raw, PILOT_TOP) == {"polygon": moved, "path": 0}
    assert top_cut_shapes(prep, PILOT_TOP) == {"polygon": 0, "path": 0}
    ex_raw, ex_prep = Extraction(raw, lef, PILOT_TOP), Extraction(prep, lef, PILOT_TOP)
    assert sum(ex_raw.flat_cuts.values()) == moved and ex_prep.flat_cuts == {}
    assert ex_raw.flat_cuts == cuts_by_layer(ex_prep)
    assert partition(ex_raw) == partition(ex_prep)
    assert ex_raw.summary()["nets"] == ex_prep.summary()["nets"]
    assert ex_raw.summary()["ports"] == ex_prep.summary()["ports"]
    old = Extraction(raw, lef, PILOT_TOP, top_cuts=False)
    assert partition(old) != partition(ex_prep)
