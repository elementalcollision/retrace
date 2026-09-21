"""RETRACE x TEMPO LVS (PRD G6, docs/TEMPO_LVS.md): the IHP-ported extractor
checks TEMPO's sign-off GDS against its own DEF/nl.v, independent of
LibreLane's Magic/Netgen flow.

Skips cleanly when TEMPO_ROOT (env var; default ~/Claude_Primary/Jane_Street_ASIC) is
absent -- this suite is meant to run on the machine that has both projects
checked out, but must not break `pytest -q` anywhere else. The extraction
(~20 s on an 18-core Mac, see docs/TEMPO_LVS.md) is cached once per session.
"""

import functools
import gc
import os
import tempfile

import pytest

from tools.retrace.defparse import read_def
from tools.tempo import faults, lvs

pytestmark = pytest.mark.skipif(not os.path.isdir(lvs.TEMPO_ROOT), reason=f"{lvs.TEMPO_ROOT} not present")


@functools.cache
def result():
    return lvs.run(verbose=False)


def test_extraction_runs_clean():
    """No unbound labels, open cuts, or missing pin geometry over the whole
    62,151-instance design (docs/TEMPO_LVS.md 'Performance')."""
    ex, report = result()
    assert ex.summary()["diagnostics"] == {}


def test_a_placements_match_def():
    """Every extracted instance maps 1:1 to a DEF COMPONENTS entry by
    (master, x, y, orient), and vice versa."""
    _ex, report = result()
    p = report["a_placements"]
    assert p["gds_total"] == p["def_total"] == p["matched"]
    assert p["only_gds"] == []
    assert p["only_def"] == []
    assert p["ambiguous"] == []


def test_b_net_partition_matches_def_nets():
    """The extracted (instance, pin) partition, minus global power and
    single-pin nets (neither of which DEF's regular NETS section lists --
    docs/TEMPO_LVS.md), agrees exactly with DEF NETS."""
    _ex, report = result()
    b = report["b_def_nets"]
    assert b["agree"], (b["only_a"], b["only_b"])
    assert b["only_a"] == 0 and b["only_b"] == 0


def test_c_net_partition_matches_nl_v():
    """Same partition, against the final netlist's connections per instance
    pin (nl.v uses DEF's own instance names)."""
    _ex, report = result()
    c = report["c_nl_v"]
    assert c["agree"], (c["only_a"], c["only_b"])
    assert c["nl_only"] == []


def test_d_pins_match_ihp_lef():
    """Every master used (51 std cells + the SRAM macro) has the extracted pin
    set the IHP LEF declares, for every instance."""
    _ex, report = result()
    bad = {m: v for m, v in report["d_pins_vs_lef"].items() if v["mismatched_instances"]}
    assert bad == {}


def test_d2_pin_geometry_matches_ihp_lef():
    """Every LEF port rectangle of every signal pin, for all 52 masters used, lies on
    the extracted conductor of the same pin and on no other pin's (closes the
    name-set blind spot of (d), docs/TEMPO_LVS.md 4c)."""
    _ex, report = result()
    d2 = report["d2_pin_geometry"]
    assert len(d2) == 52
    assert sum(v["rects_checked"] for v in d2.values()) > 500
    assert {m: v["bad"] for m, v in d2.items() if v["bad"]} == {}


@pytest.mark.parametrize("master,a,b", [
    ("RM_IHPSG13_1P_1024x32_c2_bm_bist", "A_DIN<15>", "A_BIST_DIN<15>"),
    ("sg13cmos5l_nand2_1", "A", "B"),
], ids=["sram-labels", "nand2-labels"])
def test_d2_negative_control_swapped_labels(master, a, b):
    """Swapping two pin labels leaves (d)'s name set unchanged but must fail (d2),
    flagging exactly the two pins, each found on the other's conductor."""
    ex, _report = result()
    lef = lvs.load_lef()
    cells = {c.name: c for c in ex.lib.cells}
    swapped = lvs.swapped_label_cell(cells[master], a, b)
    bad = lvs.check_pin_geometry_vs_lef(ex, lef, cells={**cells, master: swapped}, only=[master])[master]["bad"]
    norm = lvs._norm_bus
    assert {(x["pin"], tuple(x["owners"])) for x in bad} == {(norm(a), (norm(b),)), (norm(b), (norm(a),))}


def test_e_electrical_sanity():
    """Every signal net has exactly one driver (once power/ground-use LEF pins
    are excluded, docs/TEMPO_LVS.md), no signal net floats undriven, every POWER
    pin is on one net and every GROUND pin on another, never the same one."""
    _ex, report = result()
    e = report["e_sanity"]
    assert e["no_driver_count"] == 0, e["no_driver"]
    assert e["multi_driver_count"] == 0, e["multi_driver"]
    assert (e["power_nets"], e["ground_nets"], e["supply_shorts"]) == (1, 1, 0)
    assert e["supply_stray_instances"] == []
    assert e["supplies_ok"]


def test_f_cellcheck_masters_match_pdk():
    """Every sg13cmos5l_* master embedded in TEMPO's GDS is geometrically
    identical to the PDK's own stdcell GDS."""
    _ex, report = result()
    f = report["f_cellcheck"]
    assert f["differ"] == {}
    assert f["identical"] == f["masters"]


def test_v4_extractors_agree():
    """V4: extractor 2 (KLayout L2N, tools/l2n/klayout_extract.py, its own
    connectivity engine, tech.py for layer numbers only) agrees net-for-net with
    extractor 1 on TEMPO's sign-off GDS under `tech.IHP_SG13CMOS5L`, exactly like
    it does on the warm-up (86/86) and the puzzle (719/719) -- see docs/TEMPO_LVS.md
    V4 section for the counts and the single-pin-net exclusion this mirrors from
    `test/test_crosscheck.py::test_v4_extractors_agree`."""
    from tools.l2n.compare import compare

    ex, _report = result()
    ours, theirs = compare(lvs.GDS, ex)
    # same convention as the sky130 V4 test: KLayout makes no subcircuit pin for an
    # output that connects to nothing upward, so single-member nets (TEMPO's own
    # unloaded clkload* CTS dummy-load outputs, docs/TEMPO_LVS.md) exist only on our
    # side; checks (b)/(c)/(e) above already cover those.
    ours = {n for n in ours if len(n) > 1}
    theirs = {n for n in theirs if len(n) > 1}
    assert ours == theirs, (sorted(map(sorted, ours - theirs))[:3], sorted(map(sorted, theirs - ours))[:3])


@pytest.mark.skipif(not (os.path.exists("upstream/puzzle.gds") and os.path.isdir("pdk/sky130_fd_sc_hd")),
                    reason="puzzle files or sky130 PDK subset not present (e.g. on TEMPO's CI runner)")
def test_sky130_extractor_output_is_unaffected():
    """The IHP port must not change a single byte of the puzzle's sky130
    extraction (docs/STATUS.md); this is also covered by the rest of the
    suite defaulting to `tech.SKY130_HD`, asserted here as a direct guard."""
    from tools.retrace.extract import Extraction
    from tools.retrace.lef import read_lef
    from tools.retrace.tech import SKY130_HD

    lef = read_lef("pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef")
    ex_default = Extraction("upstream/puzzle.gds", lef)
    ex_explicit = Extraction("upstream/puzzle.gds", lef, tech=SKY130_HD)
    assert ex_default.to_verilog({}, lef) == ex_explicit.to_verilog({}, lef)


# --- planted faults (docs/TEMPO_LVS.md 4e) --------------------------------------
# Six faults in one copy of the sign-off GDS (tools/tempo/faults.py), far apart, each
# with the DEF instances it touches. Every check must report its own fault there and
# nothing anywhere else. Costs one extra extraction.

SIGNAL_FAULTS = ("via_open", "mirror", "bridge", "sram_swap")


@functools.cache
def planted():
    ex, _report = result()
    lef = lvs.load_lef()
    name_map, _ = lvs.map_to_def(ex, read_def(lvs.DEF)["components"])
    chosen = faults.choose(ex, lef, name_map)
    with tempfile.TemporaryDirectory() as tmp:
        gds = os.path.join(tmp, "tempo_faults.gds")
        faults.plant(chosen, lvs.GDS, gds, lvs.TOP)
        mutant, report = lvs.run(gds=gds, verbose=False)
    del mutant  # keep only the report: one extraction in memory, not two
    gc.collect()
    return chosen, report, name_map


def _hood(chosen, *kinds):
    return set().union(*(chosen[k]["neighbourhood"] for k in kinds))


def test_planted_fault_sites_are_disjoint():
    """The fixture itself: six faults, and no two touch the same instance."""
    chosen, _report, _map = planted()
    assert set(chosen) == {"via_open", "mirror", "bridge", "sram_swap", "supply_short", "rail_open"}
    kinds = [k for k in chosen if chosen[k].get("neighbourhood")]
    for i, a in enumerate(kinds):
        for b in kinds[i + 1:]:
            assert not chosen[a]["neighbourhood"] & chosen[b]["neighbourhood"], (a, b)


def test_planted_a_reports_the_mirrored_cell_only():
    chosen, report, _map = planted()
    a = report["a_placements"]
    assert a["only_gds"] == [chosen["mirror"]["instance"]]
    assert a["only_def"] == [chosen["mirror"]["def_name"]]


@pytest.mark.parametrize("check", ["b_def_nets", "c_nl_v"])
def test_planted_bc_report_each_signal_fault_and_nothing_else(check):
    """Every instance in a mismatched net belongs to a planted signal fault, and each
    fault shows up. In (c) the mirrored cell has no GDS match, so nl.v's side drops it
    too and it is reported as `nl_only` instead of as a partition difference."""
    chosen, report, _map = planted()
    r = report[check]
    where = set(r["mismatched_instances"])
    assert not r["agree"]
    assert where <= _hood(chosen, *SIGNAL_FAULTS), sorted(where - _hood(chosen, *SIGNAL_FAULTS))[:5]
    shown = SIGNAL_FAULTS if check == "b_def_nets" else ("via_open", "bridge", "sram_swap")
    for kind in shown:
        assert where & chosen[kind]["neighbourhood"], kind
    if check == "c_nl_v":
        assert r["nl_only"] == [chosen["mirror"]["def_name"]]


def test_planted_d2_flags_the_swapped_sram_pins():
    _chosen, report, _map = planted()
    bad = {m: v["bad"] for m, v in report["d2_pin_geometry"].items() if v["bad"]}
    assert set(bad) == {faults.SRAM}
    a, b = (lvs._norm_bus(p) for p in faults.SRAM_SWAP)
    assert {(x["pin"], tuple(x["owners"])) for x in bad[faults.SRAM]} == {(a, (b,)), (b, (a,))}


def test_planted_e_open_leaves_loads_undriven_and_bridge_doubles_drivers():
    chosen, report, name_map = planted()
    e = report["e_sanity"]
    undriven = {name_map[i] for i in e["no_driver_instances"]}
    doubled = {name_map[i] for i in e["multi_driver_instances"]}
    assert undriven & chosen["via_open"]["neighbourhood"]
    assert undriven <= _hood(chosen, "via_open", "mirror")
    assert doubled & chosen["bridge"]["neighbourhood"]
    assert doubled <= _hood(chosen, "bridge", "mirror")


def test_planted_e_supply_short_and_rail_open():
    """The short leaves one net holding both POWER and GROUND pins; the isolated rail
    becomes a second POWER net, and the instances on it are exactly the rail's."""
    chosen, report, _map = planted()
    e = report["e_sanity"]
    assert not e["supplies_ok"]
    assert e["supply_shorts"] == 1
    assert (e["power_nets"], e["ground_nets"]) == (2, 1)
    assert set(e["supply_stray_instances"]) == chosen["rail_open"]["stray"]


def test_planted_supply_short_is_located_at_the_bar():
    """locate_supply_short: the shortest VDD-to-GROUND path runs through the planted bar,
    and its non-pin shapes (`at`) lie within the bar."""
    chosen, report, _map = planted()
    (site,) = report["e_sanity"]["supply_short_at"]
    x0, y0, x1, y1 = site[0]["at"]
    b0, c0, b1, c1 = chosen["supply_short"]["rect"]
    assert b0 - 1e-3 <= x0 and x1 <= b1 + 1e-3 and c0 - 1e-3 <= y0 and y1 <= c1 + 1e-3, (site[0], chosen["supply_short"])


def test_planted_lvs_where_rings_every_fault():
    """tools.viz.lvs_where turns the report into rings on the die: every planted fault is
    inside one, and the checks named on the rings are the ones that flagged it."""
    from tools.viz import lvs_where
    from tools.viz.tempo import design

    chosen, report, name_map = planted()
    die, d, _lef, _logic, _master = design()
    flags, shorts = lvs_where.findings(report, die, d)
    marks = lvs_where.marks(flags, shorts, die)

    def ringed(box, check):
        x0, y0, x1, y1 = box
        return any(check in label and m[0] <= x0 + 1e-3 and x1 - 1e-3 <= m[2] and m[1] <= y0 + 1e-3 and y1 - 1e-3 <= m[3]
                   for label, m in marks)

    assert ringed(chosen["supply_short"]["rect"], "VDD-VSS short")
    assert ringed(die.cells[chosen["mirror"]["def_name"]], "(a)")
    assert any(ringed(die.cells[n], "off-grid supply") for n in chosen["rail_open"]["neighbourhood"] if n in die.cells)
    for kind in ("via_open", "bridge", "sram_swap"):
        assert any(ringed(die.cells[n], "(b)") for n in chosen[kind]["neighbourhood"] if n in die.cells), kind
