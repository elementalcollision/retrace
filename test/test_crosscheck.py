"""V4 (two independent extractors agree) and V6 (VCD replay in two simulators)."""

import functools
import os
import shutil
import subprocess

import pytest

from tools.l2n.compare import compare
from tools.retrace.extract import Extraction
from tools.retrace.lef import read_lef
from tools.retrace.vcdtb import read_vcd
from tools.retrace.vcdtb import testbench as make_testbench

LEF = "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"
LIB = "pdk/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
BIN = os.path.expanduser("~/ttsetup/oss-cad-suite/bin")
MODELS = ["pdk/sky130_fd_sc_hd/verilog/primitives.v", "pdk/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v"]


@functools.cache
def lef():
    return read_lef(LEF)


@pytest.mark.parametrize("gds", ["upstream/warmup/04_final.gds", "upstream/puzzle.gds"])
def test_v4_extractors_agree(gds):
    ours, theirs = compare(gds, Extraction(gds, lef()))
    # KLayout makes no subcircuit pin for an output that connects to nothing upward, so
    # single-member nets exist only on our side; they are compared by the V5 tests
    ours = {n for n in ours if len(n) > 1}
    theirs = {n for n in theirs if len(n) > 1}
    assert ours == theirs, (sorted(map(sorted, ours - theirs))[:3], sorted(map(sorted, theirs - ours))[:3])


@functools.cache
def puzzle_files():
    os.makedirs("out", exist_ok=True)
    ex = Extraction("upstream/puzzle.gds", lef())
    dirs = {p: "input" for p in ("clk", "rst_n", "enable", "I")} | {"O": "output", "success": "output"}
    with open("out/puzzle.v", "w") as f:
        f.write(ex.to_verilog(dirs, lef()))
    widths, events = read_vcd("upstream/example_inputs.vcd")
    with open("out/tb_puzzle.v", "w") as f:
        f.write(make_testbench(widths, events, "puzzle", ["clk", "rst_n", "enable", "I"], ["O", "success"], "clk"))
    return "out/puzzle.v", "out/tb_puzzle.v"


def _result(stdout):
    line = next(l for l in stdout.splitlines() if l.startswith("VCD-REPLAY"))
    return dict(kv.split("=") for kv in line.split()[1:])


@pytest.mark.skipif(not os.path.exists(f"{BIN}/iverilog"), reason="Icarus not installed")
def test_v6_vcd_replay_icarus_pdk_models():
    netlist, tb = puzzle_files()
    subprocess.run([f"{BIN}/iverilog", "-g2012", "-DFUNCTIONAL", "-DUNIT_DELAY=", "-o", "out/replay_icarus.vvp",
                    tb, netlist, *MODELS], check=True, capture_output=True)
    r = subprocess.run([f"{BIN}/vvp", "-n", "out/replay_icarus.vvp"], check=True, capture_output=True, text=True)
    res = _result(r.stdout)
    assert res == {"checked": "1248", "errors": "0"}, r.stdout[-2000:]


@pytest.mark.skipif(not os.path.exists(f"{BIN}/verilator"), reason="Verilator not installed")
def test_v6_vcd_replay_verilator_liberty_models():
    """Second simulator, and cell behaviour from the Liberty functions instead of the
    PDK Verilog models: Yosys flattens the netlist into plain logic first."""
    netlist, tb = puzzle_files()
    subprocess.run([f"{BIN}/yosys", "-q", "-p",
                    f"read_liberty -ignore_miss_func {LIB}; read_verilog {netlist}; hierarchy -top puzzle; "
                    "flatten; proc; opt_clean; write_verilog -noattr out/puzzle_libflat.v"], check=True)
    shutil.rmtree("out/vl", ignore_errors=True)
    env = dict(os.environ, PATH=BIN + os.pathsep + os.environ["PATH"])
    subprocess.run([f"{BIN}/verilator", "--binary", "--timing", "-Wno-fatal", "-Wno-lint", "-Wno-style",
                    "--top-module", "tb", "-Mdir", "out/vl", tb, "out/puzzle_libflat.v", "-o", "vtb"],
                   check=True, capture_output=True, env=env)
    r = subprocess.run(["out/vl/vtb"], check=True, capture_output=True, text=True)
    res = _result(r.stdout)
    assert res == {"checked": "1248", "errors": "0"}, r.stdout[-2000:]
