"""Warm-up oracles (docs/spec/VERIFICATION.md V1, V3a, V3b, V3c).

The warm-up ships every forward-flow stage, so the extractor output is compared with
the placed-and-routed DEF: placements exactly (V1) and the net partition over
(instance, pin) exactly (V3a). Instances are matched by (master, x, y, orient), never by
name, since the GDS carries no instance names.
"""

import functools
import os
import shutil
import subprocess

import pytest

from tools.retrace.defparse import read_def
from tools.retrace.extract import SUPPLY_PINS, Extraction
from tools.retrace.lef import read_lef
from tools.retrace.netgraph import compare

GDS = "upstream/warmup/04_final.gds"
DEF = "upstream/warmup/03_post_place_and_route.def"
LEF = "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"


@functools.cache
def extraction():
    return Extraction(GDS, read_lef(LEF))


@functools.cache
def golden():
    return read_def(DEF)


def _def_name_of():
    by_pos = {v: k for k, v in golden()["components"].items()}
    return {i["name"]: by_pos.get((i["master"], i["x"], i["y"], i["orient"])) for i in extraction().instances}


def test_v1_placements_match_def():
    ours = sorted((i["master"], i["x"], i["y"], i["orient"]) for i in extraction().instances)
    theirs = sorted(golden()["components"].values())
    assert ours == theirs


def test_no_extraction_diagnostics():
    assert dict(extraction().diag) == {}, extraction().notes[:10]


def _our_partition():
    ren = _def_name_of()
    nets = []
    for m in extraction().nets:
        s = {(ren[i], p) for i, p in m["pins"] if p not in SUPPLY_PINS}
        s |= {("PIN", p) for p in m["ports"]}
        if s:
            nets.append(frozenset(s))
    return nets


def _def_partition():
    return [frozenset(pins) for pins in golden()["nets"].values()]


def test_v3a_net_partition_matches_def():
    ours, theirs = set(_our_partition()), set(_def_partition())
    missing = sorted(theirs - ours, key=lambda n: sorted(n))
    extra = sorted(ours - theirs, key=lambda n: sorted(n))
    # nets that exist only in the layout are single unconnected output pins (DEF omits them)
    extra_real = [n for n in extra if len(n) > 1]
    detail = "\n".join(
        [f"missing DEF net: {sorted(n)}" for n in missing[:5]]
        + [f"unexpected net: {sorted(n)}" for n in extra_real[:5]]
    )
    assert not missing and not extra_real, detail


@pytest.mark.parametrize("port", ["A", "B", "S", "clk", "en", "rst_n"])
def test_ports_bound(port):
    assert port in extraction().ports


# --- V3b / V3c: against the synthesized netlist 01_netlist.v -----------------------

OUT_V = "out/adder_demo.v"
SBY = os.path.expanduser("~/ttsetup/oss-cad-suite/bin/sby")


@functools.cache
def emitted_netlist():
    os.makedirs("out", exist_ok=True)
    ex = extraction()
    dirs = {p: "input" for p in ("A", "B", "clk", "en", "rst_n")} | {"S": "output"}
    with open(OUT_V, "w") as f:
        f.write(ex.to_verilog(dirs, read_lef(LEF)))
    return OUT_V


def test_v3b_isomorphic_to_synth_netlist():
    same, ours, theirs = compare(emitted_netlist(), "adder_demo", "upstream/warmup/01_netlist.v", "adder_demo")
    assert ours == theirs
    assert same


@pytest.mark.skipif(not os.path.exists(SBY), reason="SymbiYosys not installed")
def test_v3c_sequentially_equivalent_pdr():
    emitted_netlist()
    shutil.rmtree("formal/warmup_equiv", ignore_errors=True)
    env = dict(os.environ, PATH=os.path.dirname(SBY) + os.pathsep + os.environ["PATH"])
    r = subprocess.run([SBY, "-f", "warmup_equiv.sby"], cwd="formal", env=env, capture_output=True, text=True)
    assert "DONE (PASS" in r.stdout, r.stdout[-2000:]
