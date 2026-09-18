"""V7 top level: end-to-end sequential equivalence of the recovered RTL and the extracted netlist.

Regenerates everything the proof needs into a fresh work directory, so the result depends
only on the GDS and the files in rtl_recovered/:
  puzzle_probe.v            the extracted netlist (Extraction.to_verilog), module renamed,
                            plus one output probe_fNN per flop driven by its Q net
                            (rtl_recovered/blocks.json)
  puzzle_recovered_probe.v  rtl_recovered/puzzle_recovered.v, module renamed, plus the
                            same probes driven by the register tagged `// fNN`
  the six block files       rtl_recovered/<block>.v, optionally replaced (negative tests)
  recovered_miter.sv        formal/recovered_miter.sv: reset asserted in the first cycle,
                            then O, success and all 92 flops asserted equal
The probes only add ports; the proof passes only if every assertion holds, so O and
success equality is proven whatever the probes say. SymbiYosys abc pdr.

    python -m tools.analysis.e2e [--work out/e2e/main] [--replace BLOCK=FILE ...] [--gds OTHER.gds]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

from tools.retrace.extract import Extraction
from tools.retrace.lef import read_lef

GDS = "upstream/puzzle.gds"
LEF = "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"
LIB = "pdk/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
BLOCKS = ["counter", "array", "left_top", "left_bottom", "check", "outgen"]
BIN = os.path.expanduser("~/ttsetup/oss-cad-suite/bin")
DIRS = {p: "input" for p in ("clk", "rst_n", "enable", "I")} | {"O": "output", "success": "output"}


def _add_probes(src, old_module, new_module, drivers):
    """Rename the module and add `output probe_fNN; assign probe_fNN = <driver>;`."""
    ids = sorted(drivers)
    head = re.compile(r"^module\s+" + old_module + r"\s*\(", re.M)
    if not head.search(src):
        raise ValueError(f"module {old_module} not found")
    src = head.sub(f"module {new_module} (" + "".join(f"probe_{k}, " for k in ids), src, count=1)
    decl = "".join(f"  output probe_{k};\n  assign probe_{k} = {drivers[k]};\n" for k in ids)
    i = src.rindex("endmodule")
    return src[:i] + decl + src[i:]


def gold_probe(gds=GDS):
    lef = read_lef(LEF)
    src = Extraction(gds, lef, top="puzzle").to_verilog(DIRS, lef)
    with open("rtl_recovered/blocks.json") as f:
        flops = json.load(f)["flops"]
    drivers = {k: v["Q_net"] for k, v in flops.items()}
    return _add_probes(src, "puzzle", "puzzle_probe", drivers)


def gate_probe():
    with open("rtl_recovered/puzzle_recovered.v") as f:
        src = f.read()
    drivers = {m.group(2): m.group(1) for m in re.finditer(r"^\s*reg\s+(\w+)\s*;\s*//\s*(f\d\d)\b", src, re.M)}
    if len(drivers) != 92:
        raise ValueError(f"expected 92 `reg name; // fNN` declarations, found {len(drivers)}")
    return _add_probes(src, "puzzle_recovered", "puzzle_recovered_probe", drivers)


def run(work, replace=None, gds=GDS):
    """Build the work directory and run SymbiYosys. Returns (passed, tail of the log).
    `gds` other than the puzzle is a regression use: is that layout still the design
    rtl_recovered/ describes? (flop ids and Q nets come from rtl_recovered/blocks.json)"""
    replace = replace or {}
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    with open(f"{work}/puzzle_probe.v", "w") as f:
        f.write(gold_probe(gds))
    with open(f"{work}/puzzle_recovered_probe.v", "w") as f:
        f.write(gate_probe())
    for b in BLOCKS:
        shutil.copy(replace.get(b, f"rtl_recovered/{b}.v"), f"{work}/{b}.v")
    shutil.copy("formal/recovered_miter.sv", work)
    shutil.copy(LIB, work)
    lib = os.path.basename(LIB)
    blocks = " ".join(f"{b}.v" for b in BLOCKS)
    sby = f"""[options]
mode prove

[engines]
abc pdr

[script]
read_liberty -ignore_miss_func {lib}
read_verilog puzzle_probe.v
read_verilog puzzle_recovered_probe.v {blocks}
read_verilog -formal recovered_miter.sv
delete */t:sky130_fd_sc_hd__tapvpwrvgnd_1 */t:sky130_fd_sc_hd__decap_* */t:sky130_fd_sc_hd__fill_* */t:sky130_fd_sc_hd__diode_*
hierarchy -check -top recovered_miter
flatten
prep -top recovered_miter

[files]
{lib}
puzzle_probe.v
puzzle_recovered_probe.v
{chr(10).join(f"{b}.v" for b in BLOCKS)}
recovered_miter.sv
"""
    with open(f"{work}/e2e.sby", "w") as f:
        f.write(sby)
    env = dict(os.environ, PATH=BIN + os.pathsep + os.environ["PATH"])
    r = subprocess.run([f"{BIN}/sby", "-f", "e2e.sby"], cwd=work, env=env, capture_output=True, text=True)
    return "DONE (PASS" in r.stdout, r.stdout[-3000:]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", default="out/e2e/main")
    ap.add_argument("--replace", action="append", default=[], help="BLOCK=FILE")
    ap.add_argument("--gds", default=GDS)
    args = ap.parse_args(argv)
    ok, log = run(args.work, dict(r.split("=", 1) for r in args.replace), args.gds)
    print(log if not ok else "")
    print("V7 end-to-end", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
