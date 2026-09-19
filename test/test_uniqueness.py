"""Closes the scope of the formal uniqueness result (docs/SOLVE_FORMAL.md).

The formal search proves the solution unique among runs that hold `enable` high on every
cycle after reset. This lemma extends it to every input pattern: before the decision
(cnt_done = q_f08 = 0 and armed = q_f79 = 0), a cycle with enable = 0 leaves every flop
of the extracted netlist unchanged (the four no-reset `pos` flops are forced to 0), so a
run with enable gaps behaves exactly like the same run with the gaps removed, whatever I
does during the gaps. After the decision, success is latched (check block, V7-proven).
The proof is SAT on each block's gold cone, i.e. on the real netlist logic.
"""

import json
import os
import re
import subprocess

import pytest

from tools.analysis import cone

YOSYS = os.path.expanduser("~/ttsetup/oss-cad-suite/bin/yosys")
BLOCKS = ["counter", "array", "left_top", "left_bottom", "check", "outgen"]
needs_eda = pytest.mark.skipif(not os.path.exists(YOSYS), reason="oss-cad-suite not installed")


def _prove(block, fixed, proves):
    script = (f"read_liberty -ignore_miss_func {cone.LIB}; read_verilog rtl_recovered/gold/gold_{block}.v; "
              f"hierarchy -top gold_{block}; flatten; opt_clean; "
              f"sat {' '.join(f'-set {n} 0' for n in fixed)} {' '.join(f'-prove {a} {b}' for a, b in proves)} "
              f"-verify gold_{block}")
    return subprocess.run([YOSYS, "-q", "-p", script], capture_output=True, text=True).returncode == 0


@needs_eda
@pytest.mark.parametrize("block", BLOCKS)
def test_enable_low_before_decision_holds_state(block):
    cone.write_gold(block)
    with open(f"rtl_recovered/gold/gold_{block}.v") as f:
        inputs = set(re.findall(r"^\s*input (\w+);", f.read(), re.M))
    with open("rtl_recovered/blocks.json") as f:
        flops = {k: v for k, v in json.load(f)["flops"].items() if v["block"] == block}
    fixed = [n for n in ("enable", "q_f08", "q_f79") if n in inputs]
    proves = [(f"d_{k}", "0" if v["kind"] == "no_reset" else f"q_{k}") for k, v in flops.items()]
    assert _prove(block, fixed, proves)


@needs_eda
def test_negative_control_counter_moves_when_enabled():
    cone.write_gold("counter")
    assert not _prove("counter", ["q_f08"], [("d_f06", "q_f06")])
