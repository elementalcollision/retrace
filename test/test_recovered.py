"""V7: recovered RTL (rtl_recovered/) against the extracted puzzle netlist.

Per block, a SAT proof against the gold cone (tools/analysis/cone.py); end to end, an
unbounded SymbiYosys proof (tools/analysis/e2e.py) with a negative control; and a replay
of the sample VCD on the recovered top level.
"""

import os
import subprocess

import pytest

from tools.analysis import cone, e2e
from tools.retrace.vcdtb import read_vcd
from tools.retrace.vcdtb import testbench as make_testbench

BIN = os.path.expanduser("~/ttsetup/oss-cad-suite/bin")
BLOCKS = ["counter", "array", "left_top", "left_bottom", "check", "outgen"]
needs_eda = pytest.mark.skipif(not os.path.exists(f"{BIN}/yosys"), reason="oss-cad-suite not installed")


@needs_eda
@pytest.mark.parametrize("block", BLOCKS)
def test_v7_block_equivalent(block):
    ok, log = cone.check(block, f"rtl_recovered/{block}.v")
    assert ok, log[-2000:]


@needs_eda
def test_v7_harness_detects_wrong_output_bit(tmp_path):
    """The gold module itself passes; inverting one O bit fails (guards the O-bus fix)."""
    cone.write_gold("outgen")
    with open("rtl_recovered/gold/gold_outgen.v") as f:
        gold = f.read().replace("module gold_outgen", "module rec_outgen")
    good, bad = tmp_path / "good.v", tmp_path / "bad.v"
    good.write_text(gold)
    assert "assign O[3] = o_O3;" in gold
    bad.write_text(gold.replace("assign O[3] = o_O3;", "assign O[3] = ~o_O3;"))
    assert cone.check("outgen", str(good))[0]
    assert not cone.check("outgen", str(bad))[0]


@needs_eda
def test_v7_end_to_end_equivalent():
    ok, log = e2e.run("out/e2e/test")
    assert ok, log


@needs_eda
def test_v7_end_to_end_detects_wrong_message_byte(tmp_path):
    with open("rtl_recovered/outgen.v") as f:
        src = f.read()
    old = """(p==4'd8) ? "N" : 8'h00;
    end
  endfunction

  function [7:0] msg_two_not_touch;"""
    assert src.count(old) == 1
    bad = tmp_path / "outgen_bad.v"
    bad.write_text(src.replace(old, old.replace('"N"', '"M"')))
    ok, _log = e2e.run("out/e2e/test_neg", {"outgen": str(bad)})
    assert not ok


@needs_eda
def test_v6_vcd_replay_on_recovered_top():
    os.makedirs("out/e2e", exist_ok=True)
    widths, events = read_vcd("upstream/example_inputs.vcd")
    with open("out/e2e/tb_recovered.v", "w") as f:
        f.write(make_testbench(widths, events, "puzzle_recovered", ["clk", "rst_n", "enable", "I"],
                               ["O", "success"], "clk"))
    srcs = ["rtl_recovered/puzzle_recovered.v"] + [f"rtl_recovered/{b}.v" for b in BLOCKS]
    subprocess.run([f"{BIN}/iverilog", "-g2012", "-o", "out/e2e/tb_recovered.vvp", "out/e2e/tb_recovered.v", *srcs],
                   check=True, capture_output=True)
    r = subprocess.run([f"{BIN}/vvp", "-n", "out/e2e/tb_recovered.vvp"], check=True, capture_output=True, text=True)
    assert "VCD-REPLAY checked=1248 errors=0" in r.stdout, r.stdout[-2000:]
