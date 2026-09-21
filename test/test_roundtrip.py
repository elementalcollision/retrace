"""S4 round trip: our LibreLane hardening of rtl_recovered/, checked with RETRACE's own tools.

Nothing here runs LibreLane. The tests read an existing run: RETRACE_ROUNDTRIP_RUN (default
out/roundtrip/puzzle_run/upstreamlike, where `tools/roundtrip/puzzle/harden.sh upstreamlike`
writes it). tools/roundtrip/ci.sh hardens and then runs this file. A test skips when what it
needs is missing (the run, the upstream puzzle files in upstream/, which are not
redistributed, pdk/, oss-cad-suite, Docker); with RETRACE_ROUNDTRIP_REQUIRE=1 (ci.sh sets it)
it fails instead.

Default suite (each test a few seconds, about 30 s in all with a run present):
  run        the run was made by LibreLane 3.0.14 on open_pdks 8afc8346 from the current
             tools/roundtrip/puzzle/config.json; the flow's own sign-off: XOR, routing DRC,
             disconnected pins, PDN and antenna clean, and without fill the Magic/KLayout
             DRC and LVS findings are only the n-well ones fill would remove
  check      tools.roundtrip.check on the KLayout stream-out: X, V1-V5, CC
  loop       tools.roundtrip.loop, fast path: extraction == DEF; every flop clocked from
             port clk through clock buffers (a rewired CLK is caught); PDR proofs of the
             extracted netlist against rtl_recovered/ and against the puzzle's extracted
             netlist, with DEF flop probes; a one-gate mutant must fail; replays of
             upstream/example_inputs.vcd and answer/solution.vcd
  floorplan  tools.roundtrip.vs_puzzle: die, rows, taps, endcaps, signal pins, PDN identical
             to upstream/puzzle.gds; every register on the puzzle's flop master
  synthesis  the warm-up calibration: recipe `warmup` (Yosys 0.62 in the LibreLane 3.0.14
             image) reproduces upstream/warmup/01_netlist.v exactly (cells, names, nets);
             needs Docker with the image already pulled (a test never pulls 5 GB)
Slow (over ~30 s), run only when RETRACE_ROUNDTRIP_RUN is set or CI is true:
  check on both stream-outs (KLayout and Magic) plus XS; the whole tools.roundtrip.loop
  (simulation-only flop map, GDS mutant); sign-off of the fill-inserted `clean` run
  (RETRACE_ROUNDTRIP_CLEAN_RUN, default the sibling run named clean, "none" to skip): DRC
  and LVS clean.

vs_puzzle maps our registers to the puzzle's flops through the `// fNN` tags of
rtl_recovered/puzzle_recovered.v and does not check them; the step-4 proof here
(test_loop_equivalent_to_puzzle_layout) does, since it asserts each tagged register equal
to the puzzle's fNN.
"""

import functools
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "out/roundtrip/puzzle_run/upstreamlike"
RUN = Path(os.environ.get("RETRACE_ROUNDTRIP_RUN") or DEFAULT_RUN).resolve()
CLEAN_ENV = os.environ.get("RETRACE_ROUNDTRIP_CLEAN_RUN", "")  # "none": no clean run to check
CLEAN_RUN = Path(CLEAN_ENV if CLEAN_ENV not in ("", "none") else RUN.parent / "clean").resolve()
FULL = bool(os.environ.get("RETRACE_ROUNDTRIP_RUN")) or os.environ.get("CI", "").lower() in ("1", "true", "yes")
REQUIRE = os.environ.get("RETRACE_ROUNDTRIP_REQUIRE", "") not in ("", "0")
OUT = ROOT / "out/roundtrip/test"
BIN = Path(os.path.expanduser("~/ttsetup/oss-cad-suite/bin"))
CONFIG = ROOT / "tools/roundtrip/puzzle/config.json"
LIBRELANE_VERSION = "3.0.14"
OPEN_PDKS = "8afc8346a57fe1ab7934ba5a6056ea8b43078e71"
IMAGE = f"ghcr.io/librelane/librelane:{LIBRELANE_VERSION}"
ORACLES = ["X", "V1", "V2", "V3a", "V3b", "V4", "V5", "CC"]

slow = pytest.mark.skipif(not FULL, reason="over ~30 s: runs when RETRACE_ROUNDTRIP_RUN is set or CI is true")


def need(ok, why):
    """Skip (fail under RETRACE_ROUNDTRIP_REQUIRE=1) unless `ok`."""
    if ok:
        return
    if REQUIRE:
        pytest.fail(f"RETRACE_ROUNDTRIP_REQUIRE=1: {why}")
    pytest.skip(why)


def need_run(run=RUN):
    need((run / "final/def").is_dir() and (run / "final/klayout_gds").is_dir(),
         f"no finished round-trip run at {run} (tools/roundtrip/puzzle/harden.sh upstreamlike makes one)")


def need_upstream(*files):
    files = files or ("upstream/puzzle.gds", "upstream/example_inputs.vcd")
    missing = [f for f in files if not (ROOT / f).exists()]
    need(not missing, f"upstream puzzle files missing: {missing} (git clone the puzzle repo into upstream/)")


def need_pdk():
    need((ROOT / "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef").exists()
         and (ROOT / "pdk/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib").exists(),
         "pdk/sky130_fd_sc_hd subset missing (README, Reproduce)")


def need_eda(*tools):
    missing = [t for t in (tools or ("yosys", "sby", "iverilog", "vvp")) if not (BIN / t).exists()]
    need(not missing, f"oss-cad-suite tools missing in {BIN}: {missing}")


@pytest.fixture(scope="module", autouse=True)
def _at_repo_root():
    """The RETRACE modules read repo-relative paths (formal/, rtl_recovered/, pdk/)."""
    old = os.getcwd()
    os.chdir(ROOT)
    yield
    os.chdir(old)


def _json(path):
    return json.loads(Path(path).read_text())


# ---- the run itself ---------------------------------------------------------------------


def test_run_made_by_pinned_flow_and_pdk():
    need_run()
    r = _json(RUN / "resolved.json")
    assert r["meta"]["librelane_version"] == LIBRELANE_VERSION
    assert r["meta"]["flow"] == "Classic"
    assert OPEN_PDKS in r["PDK_ROOT"], r["PDK_ROOT"]
    assert (r["PDK"], r["STD_CELL_LIBRARY"], r["DESIGN_NAME"]) == ("sky130A", "sky130_fd_sc_hd", "puzzle_recovered")


def test_run_used_the_current_config():
    """Every setting of tools/roundtrip/puzzle/config.json is what the run resolved (paths
    by file name; RUN_FILL_INSERTION may differ, harden.sh's clean variant turns it on)."""
    need_run()
    cfg, r = _json(CONFIG), _json(RUN / "resolved.json")
    differ = {}
    for k, v in cfg.items():
        if k.startswith("//") or k == "meta" or k == "RUN_FILL_INSERTION":
            continue
        got = r.get(k)
        if isinstance(v, str) and v.startswith("dir::"):
            v, got = Path(v[5:]).name, Path(str(got)).name
        elif isinstance(v, list) and v and isinstance(v[0], str) and v[0].startswith("dir::"):
            v, got = [Path(x[5:]).name for x in v], [Path(x).name for x in got or []]
        if v != got:
            differ[k] = (v, got)
    assert not differ, differ


def _signoff(run):
    from tools.roundtrip.puzzle import summarize

    return summarize.summarize(run, None)


def _check_signoff(run):
    s = _signoff(run)
    so = s["signoff"]
    clean = {k: so[k] for k in ("xor_difference", "magic_illegal_overlap", "route_drc_errors", "disconnected_pins",
                                "critical_disconnected_pins", "power_grid_violations")}
    clean["antenna_violating_nets"] = so["antenna_final"]["violating_nets"]
    assert all(v == 0 for v in clean.values()), clean
    fill = _json(run / "resolved.json").get("RUN_FILL_INSERTION")
    if fill:
        assert (so["magic_drc"], so["klayout_drc"], so["lvs_errors"]) == (0, 0, 0), so
        assert s["exit_status"] in (0, None), s["exit_status"]
    else:
        # without fill the n-well of every gap-separated cell group that touches no tap
        # floats (config.json //RUN_FILL_INSERTION): these rules and nothing else
        magic = {k.rsplit("(", 1)[-1].rstrip(")") for k in so.get("magic_drc_by_rule", {})}
        klay = set(so.get("klayout_drc_by_rule", {}))
        assert magic <= {"LU.3", "nwell.4", "nwell.2a", "nwell.1"}, so["magic_drc_by_rule"]
        assert klay <= {"nwell.2a", "nwell.1", "hvtp.1", "hvtp.2"}, so["klayout_drc_by_rule"]
        # every LVS net difference is an extra, floating n-well (<inst>/VPB) net
        assert so["lvs_detail"]["lvs_net_difference"] == so["lvs_layout_nets_without_match"] \
            == so["lvs_unmatched_well_nets_named_VPB"], so["lvs_detail"]
    return s


def test_run_signoff():
    need_run()
    need_pdk()
    _check_signoff(RUN)


@slow
def test_clean_run_signoff_is_clean():
    """The same layout with fill inserted (harden.sh clean): Magic DRC, KLayout DRC and
    Netgen LVS all 0, and the logic identical to RUN's (DEF components other than fill)."""
    need_pdk()
    if CLEAN_ENV == "none" or (not CLEAN_ENV and not (CLEAN_RUN / "final").is_dir()):
        pytest.skip(f"no clean run to check ({CLEAN_ENV or CLEAN_RUN})")
    need_run(CLEAN_RUN)
    assert _json(CLEAN_RUN / "resolved.json")["RUN_FILL_INSERTION"] is True
    _check_signoff(CLEAN_RUN)
    from tools.retrace.defparse import read_def

    ours = read_def(str(next((RUN / "final/def").glob("*.def"))))
    clean = read_def(str(next((CLEAN_RUN / "final/def").glob("*.def"))))
    unfilled = {k: v for k, v in clean["components"].items() if not k.startswith("FILLER_")}
    assert unfilled == ours["components"]
    assert clean["nets"] == ours["nets"]


# ---- tools.roundtrip.check: RETRACE's oracles against the run's own DEF and nl.v ---------


@pytest.fixture(scope="module")
def check_report():
    need_run()
    need_pdk()
    from tools.roundtrip import check

    return check.run(RUN, ["all"] if FULL else ["klayout"], work=OUT / "check" / RUN.name)


@pytest.mark.parametrize("oracle", ORACLES)
def test_check(check_report, oracle):
    bad = {}
    for g, r in check_report["gds"].items():
        res = r.get(oracle) or r["X"]  # X failed: no other result
        if not res.get("pass"):
            bad[g] = res
    assert not bad, json.dumps(bad, default=list)[:3000]


def test_check_counts(check_report):
    for r in check_report["gds"].values():
        v1, v3a, v3b, v5 = r["V1"], r["V3a"], r["V3b"], r["V5"]
        assert v1["matched"] == v1["gds_instances"] == v1["def_components"]
        assert v3a["matched"] == v3a["golden_nets"] and not v3a["missing"] and not v3a["unexpected"]
        assert v3b["isomorphic"] and v3b["by_name"]["matched"] == v3b["by_name"]["golden_nets"]
        assert v5["ports"]["bound"] == v5["ports"]["def_signal_pins"] == 13


@slow
def test_check_both_streamouts_agree(check_report):
    assert set(check_report["gds"]) == {"klayout", "magic"}
    assert check_report["XS"]["pass"], check_report["XS"]


# ---- tools.roundtrip.loop, fast path: the extracted layout is the recovered RTL ----------


@pytest.fixture(scope="module")
def lp():
    need_run()
    need_upstream()
    need_pdk()
    need_eda()
    from tools.retrace.defparse import read_def
    from tools.retrace.lef import read_lef
    from tools.roundtrip import loop

    work = OUT / "loop" / RUN.name
    work.mkdir(parents=True, exist_ok=True)
    lef = read_lef(loop.LEF)
    v = loop.run_views(str(RUN))
    netlist = str(work / "rt_extracted.v")
    ex, src = loop.extract(v["gds"], lef, netlist)
    d = read_def(v["def"])
    flops = loop.flop_instances(ex, d)
    return SimpleNamespace(loop=loop, lef=lef, ex=ex, src=src, d=d, flops=flops, drivers=loop.q_nets(ex, flops),
                           work=work, top=ex.top.name, netlist=netlist)


def test_loop_extraction_matches_def(lp):
    cross = lp.loop.def_vs_extraction(lp.ex, lp.d)
    assert cross["ok"], cross
    assert not lp.ex.summary()["diagnostics"]
    assert len(lp.drivers) == 92


def test_loop_every_flop_clocked_from_clk(lp):
    cp = lp.loop.clock_paths(lp.ex, lp.lef, lp.flops)
    assert cp["ok"] and cp["reach_clk"] == 92, cp["bad"]


def test_loop_clock_check_catches_a_rewired_clk(lp):
    """The single-clock proofs pass with a flop's CLK on the wrong net; this check must not."""
    port_net = {p: m["name"] for m in lp.ex.nets for p in m["ports"]}
    for wrong in (port_net["I"], lp.ex.net_of[(lp.flops["f03"], "Q")]):
        net_of = dict(lp.ex.net_of)
        net_of[(lp.flops["f02"], "CLK")] = wrong
        cp = lp.loop.clock_paths(lp.ex, lp.lef, lp.flops, net_of)
        assert not cp["ok"] and set(cp["bad"]) == {"f02"}, cp["bad"]


def test_loop_equivalent_to_rtl(lp):
    r = lp.loop.prove_against_rtl(str(lp.work / "prove_rtl"), lp.src, lp.top, lp.drivers)
    assert r["status"] == "PASS", r


def test_loop_one_gate_mutant_is_not_equivalent(lp):
    src, info = lp.loop.netlist_mutant(lp.ex, lp.lef, lp.flops, lp.src)
    r = lp.loop.prove_against_rtl(str(lp.work / "prove_rtl_mut"), src, lp.top, lp.drivers)
    assert r["status"] == "FAIL", (info["description"], r)


def test_loop_equivalent_to_puzzle_layout(lp):
    r = lp.loop.prove_against_puzzle(str(lp.work / "prove_puzzle"), lp.src, lp.top, lp.drivers)
    assert r["status"] == "PASS", r


def test_loop_replay_example_vcd(lp):
    r = lp.loop.replay(str(lp.work), "example", lp.netlist, lp.top, lp.loop.EXAMPLE_VCD)
    assert (r["checked"], r["errors"]) == (lp.loop.EXAMPLE_CHECKS, 0), r


def test_loop_replay_solution_prints_the_message(lp):
    need_upstream("answer/solution.vcd")
    r = lp.loop.replay(str(lp.work), "solution", lp.netlist, lp.top, lp.loop.SOLUTION_VCD)
    assert r["checked"] > 0 and r["errors"] == 0, r
    assert r["success_stays_high"] and r["message"] == lp.loop.EXPECTED_MESSAGE, r


@slow
def test_loop_full():
    """Everything tools.roundtrip.loop checks, including the flop map found by simulation
    alone (no DEF) and the GDS-level mutant."""
    need_run()
    need_upstream()
    need_pdk()
    need_eda()
    from tools.roundtrip import loop

    res = loop.run(str(RUN), str(OUT / "loop_full" / RUN.name))
    assert res["ok"], {k: v for k, v in res["checks"].items() if not v}


# ---- tools.roundtrip.vs_puzzle: the floorplan is the puzzle's --------------------------


@functools.cache
def _vs_puzzle(run):
    from tools.roundtrip import vs_puzzle

    return vs_puzzle.compare(str(run))[0]


@pytest.fixture(scope="module")
def vs():
    need_run()
    need_upstream("upstream/puzzle.gds")
    need_pdk()
    return _vs_puzzle(RUN)


def test_vs_puzzle_our_gds_is_our_def(vs):
    c = vs["checks"]
    assert c["ours_gds_extraction_equals_def_placement"], c
    assert c["ours_unmapped_logic_or_flops"] == 0


def test_floorplan_die_and_rows_identical(vs):
    f = vs["floorplan"]
    assert f["die_um"]["identical"], f["die_um"]
    assert all(f["rows"]["identical"].values()), f["rows"]


@pytest.mark.parametrize("kind,count", [("taps", 676), ("endcaps", 204)])
def test_floorplan_taps_and_endcaps_identical(vs, kind, count):
    t = vs["floorplan"][kind]
    assert t["identical_master_x_y_orient"] == t["puzzle"] == t["ours"] == count, t


def test_floorplan_pins_identical(vs):
    p = vs["floorplan"]["pins"]
    assert p["identical"] == p["total"] == 13, [q for q in p["signal"] if not q["same"]]
    assert p["pin_shapes_identical"] and p["power_labels_identical"]


@pytest.mark.parametrize("key,count", [("straps", 30), ("rails", 103), ("drcfill", 618), ("via_positions", 1962)])
def test_floorplan_pdn_identical(vs, key, count):
    v = vs["floorplan"]["pdn"][key]
    assert v["identical"] == v["puzzle"] == v["ours"] == count, v


def test_every_register_on_the_puzzles_flop_master(vs):
    assert vs["cells"]["flops"]["same_master_per_register"] == 92


# ---- synthesis calibration (warm-up) ----------------------------------------------------


def _docker_image_present():
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def test_synthesis_calibration_reproduces_warmup():
    """Recipe `warmup` (LibreLane 3.0.x synthesis, SYNTH_HIERARCHY_MODE keep, AREA 0) with the
    Yosys 0.62 of the LibreLane 3.0.14 image gives Jane Street's synthesized warm-up netlist:
    the same logic cells, instance names and pin nets (tools/roundtrip/synth.py)."""
    need_upstream("upstream/warmup/00_source.v", "upstream/warmup/01_netlist.v")
    need_pdk()
    need_eda("yosys")
    need(_docker_image_present(), f"Docker with {IMAGE} pulled is needed (the test does not pull it)")
    from tools.roundtrip import compare, synth

    out = OUT / "calib_warmup"
    shutil.rmtree(out, ignore_errors=True)
    hist = synth.run(["upstream/warmup/00_source.v"], "adder_demo", synth.RECIPES["warmup"], str(out), name="warmup")
    assert hist["meta"]["yosys"].startswith("Yosys 0.62"), hist["meta"]["yosys"]
    res = compare.compare(str(out / "netlist.v"), "adder_demo", "upstream/warmup/01_netlist.v", "adder_demo")
    assert res["distance"] == 0, res["diff_ours_minus_ref"]
    assert res["isomorphic"], res["graph_stats"]
    n = res["names"]
    assert n["identical"], (n["n_mismatches"], n["mismatches"][:5], n["extra_in_ours"][:5])
