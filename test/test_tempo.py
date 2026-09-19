"""RETRACE x TEMPO LVS (PRD G6, docs/TEMPO_LVS.md): the IHP-ported extractor
checks TEMPO's sign-off GDS against its own DEF/nl.v, independent of
LibreLane's Magic/Netgen flow.

Skips cleanly when TEMPO_ROOT (env var; default ~/Claude_Primary/Jane_Street_ASIC) is
absent -- this suite is meant to run on the machine that has both projects
checked out, but must not break `pytest -q` anywhere else. The extraction
(~20 s on an 18-core Mac, see docs/TEMPO_LVS.md) is cached once per session.
"""

import functools
import os

import pytest

from tools.tempo import lvs

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


def test_e_electrical_sanity():
    """Every signal net has exactly one driver (once power/ground-use LEF pins
    are excluded, docs/TEMPO_LVS.md), no signal net floats undriven, and no
    net mixes VDD and VSS."""
    _ex, report = result()
    e = report["e_sanity"]
    assert e["no_driver_count"] == 0, e["no_driver"]
    assert e["multi_driver_count"] == 0, e["multi_driver"]
    assert not e["supply_names_overlap"]


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
