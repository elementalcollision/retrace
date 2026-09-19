"""Route B (formal): find an input sequence on the EXTRACTED NETLIST that makes
`success` go high, and check whether it is unique, by SymbiYosys BMC/cover search.
Independent of route A (analytical): does not read or run tools/solve/starbattle*,
docs/SOLVE_ANALYTICAL.md or out/solve_a/, and does not use docs/INTENT.md's
interpretation of the design to constrain the search. The harness (formal/solve_top.sv)
only assumes the facts the task gives directly: one clock, an active-low reset on
rst_n, a free single-bit input I, and a hold-line enable driven high on every cycle
after a one-cycle reset (the "simplest first" policy).

    python -m tools.solve.formal_solve
    python -m tools.solve.formal_solve --skip-search   # reuse an existing found_bits.vh
    python -m tools.solve.formal_solve --depth 150 --jobs 4

Reproduces, in order:
  1. out/solve_b/puzzle.v      -- regenerate the extracted netlist (Extraction.to_verilog)
  2. formal/solve.sby          -- cover(success) / assert(!success), 4 engines in parallel,
                                   depth `--depth` (default 135), work dirs under
                                   out/solve_b/solve_<task>/
  3. out/solve_b/solve_found_bits.vh, out/solve_b/solve_found.json
                                -- the 121 I values on the 121 enabled cycles before the
                                   decision, read out of whichever task's trace VCD, plus
                                   the 11x11 grid (row-major, "row = bits 0-10, ...")
  4. formal/solve_uniq.sby     -- cover(success && differs) / assert(!(success && differs))
                                   to the same depth, using FOUND_I from step 3, work dirs
                                   under out/solve_b/solve_uniq_<task>/

Both .sby files declare `[tasks] cover_yices cover_bitwuzla bmc_abc bmc_yices`; this
module runs all four every time (cheap here: each one finishes in seconds) rather than
stopping at the first PASS, so the result is corroborated by 2 modes x up to 3 solvers.
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
from tools.retrace.vcdtb import read_vcd, value_at

GDS = "upstream/puzzle.gds"
LEF = "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"
LIB = "pdk/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
BIN = os.path.expanduser("~/ttsetup/oss-cad-suite/bin")
WORK = "out/solve_b"
DIRS = {p: "input" for p in ("clk", "rst_n", "enable", "I")} | {"O": "output", "success": "output"}
N_ENABLED = 121
TASKS = ["cover_yices", "cover_bitwuzla", "bmc_abc", "bmc_yices"]
# for each task, whether a PASS from SBY means "the property we care about holds" (True)
# or "unreached/no counterexample" carries the opposite sense for cover vs bmc tasks --
# see _interpret().
COVER_TASKS = {"cover_yices", "cover_bitwuzla"}


def gen_netlist(work=WORK):
    """Step 1: regenerate out/solve_b/puzzle.v from upstream/puzzle.gds."""
    os.makedirs(work, exist_ok=True)
    lef = read_lef(LEF)
    src = Extraction(GDS, lef, top="puzzle").to_verilog(DIRS, lef)
    path = f"{work}/puzzle.v"
    with open(path, "w") as f:
        f.write(src)
    return path


def run_sby(sby_file, tasks, prefix, jobs=4):
    """Run `sby --prefix <prefix> -j <jobs> -f <sby_file> <tasks...>` from the repo root.
    Returns (per_task {task: status_or_None}, full stdout+stderr)."""
    env = dict(os.environ, PATH=BIN + os.pathsep + os.environ["PATH"])
    for t in tasks:
        shutil.rmtree(f"{prefix}_{t}", ignore_errors=True)
    cmd = [f"{BIN}/sby", "--prefix", prefix, "-j", str(jobs), "-f", sby_file] + tasks
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    log = r.stdout + r.stderr
    per_task = {}
    for t in tasks:
        wd = f"{prefix}_{t}"
        m = re.search(rf"\[{re.escape(wd)}\] DONE \((\w+)", log)
        per_task[t] = m.group(1) if m else None
    return per_task, log


def _interpret(task, status):
    """Does this task's SBY status mean the property under test (success reachable /
    success&&differs reachable) is TRUE, FALSE, or unknown (engine error)?"""
    if status is None:
        return None
    if task in COVER_TASKS:
        # mode cover: PASS == the cover() statement WAS reached.
        return status == "PASS"
    # mode bmc: PASS == assert(!X) held for the whole bound == X never happened.
    # FAIL == a counterexample was found == X did happen.
    if status == "PASS":
        return False
    if status == "FAIL":
        return True
    return None  # ERROR/TIMEOUT/UNKNOWN


def find_trace_vcd(workdir):
    for cand in (f"{workdir}/engine_0/trace0.vcd", f"{workdir}/engine_0/trace.vcd"):
        if os.path.exists(cand):
            return cand
    eng = f"{workdir}/engine_0"
    if os.path.isdir(eng):
        for fn in sorted(os.listdir(eng)):
            if fn.endswith(".vcd"):
                return f"{eng}/{fn}"
    return None


def enabled_I_from_trace(vcd_path, n=N_ENABLED):
    """The value of `I` on each of the first `n` cycles where `enable` was high, in the
    order they were entered, read directly off the harness's own `I`/`enable`/`clk`
    signals in the SBY-produced VCD (formal/solve_top.sv and formal/solve_uniq_top.sv
    both expose these undisguised, since solve_top is itself the SBY top module)."""
    widths, events = read_vcd(vcd_path)
    clk_edges = sorted({t for t, v in events["clk"] if v == "1"})
    I_vals = [value_at(events["I"], e + 1) for e in clk_edges]
    en_vals = [value_at(events["enable"], e + 1) for e in clk_edges]
    enabled_I = [iv for iv, en in zip(I_vals, en_vals) if en == "1"]
    if len(enabled_I) < n:
        raise ValueError(f"{vcd_path}: only {len(enabled_I)} enabled cycles, need {n}")
    bits = "".join(enabled_I[:n])
    if set(bits) - {"0", "1"}:
        raise ValueError(f"{vcd_path}: non-boolean value in I trace: {bits!r}")
    return bits


def write_found_bits(bits, work=WORK):
    """Step 3b: out/solve_b/solve_found_bits.vh + solve_found.json.
    FOUND_I is declared [127:0] (121 real bits + 7 defined-zero padding bits), not
    [120:0]: `FOUND_I[cyc[6:0]]` in formal/solve_uniq_top.sv is a hardware mux selected
    by a 7-bit signal, and Yosys synthesizes all 128 decode branches whether or not
    cyc[6:0] can dynamically reach them. With a [120:0] array the unreachable codes
    121-127 read as Verilog's defined-but-unconstrained out-of-range value, 'x',
    structurally baked into the netlist -- tolerated by the SMT2 backend but rejected by
    `write_aiger` ("Design contains 'x' or 'z' bits"), which abc bmc3 depends on.
    """
    assert len(bits) == N_ENABLED and set(bits) <= {"0", "1"}, bits
    # literal is MSB-first text; want FOUND_I[k] == bits[k] for k=0..120 (LSB end) and
    # FOUND_I[127:121] == 0 (MSB end, the padding) -> pad text first, then bits reversed.
    lit = "0" * 7 + bits[::-1]
    assert len(lit) == 128
    with open(f"{work}/solve_found_bits.vh", "w") as f:
        f.write(
            "// Route B (formal) result: the 121 values of I on the 121 enabled cycles\n"
            "// before success is decided (see docs/SOLVE_FORMAL.md). Generated by\n"
            "// tools/solve/formal_solve.py -- do not hand-edit.\n"
            "// FOUND_I[k] is the value entered on the (k+1)-th enabled cycle after\n"
            "// reset, for k=0..120; bits 121..127 are defined padding (0) for the\n"
            "// unreachable codes of the 7-bit selector cyc[6:0] (see\n"
            "// formal/solve_uniq_top.sv).\n"
            f"localparam [127:0] FOUND_I = 128'b{lit};\n"
        )
    grid = [bits[r * 11:(r + 1) * 11] for r in range(11)]
    with open(f"{work}/solve_found.json", "w") as f:
        json.dump({"bits": bits, "ones": bits.count("1"), "grid": grid}, f, indent=2)
    return grid


def solve_search(depth=135, jobs=4, work=WORK):
    """Steps 1-3: generate the netlist, run formal/solve.sby, extract the bits."""
    gen_netlist(work)
    if depth != 135:
        _patch_depth("formal/solve.sby", depth)
    per_task, log = run_sby("formal/solve.sby", TASKS, f"{work}/solve", jobs=jobs)
    findings = {t: _interpret(t, s) for t, s in per_task.items()}
    print("solve.sby results:", per_task, "-> success reachable:", findings)
    winner = next((t for t, ok in findings.items() if ok), None)
    if winner is None:
        return {"found": False, "per_task": per_task, "log_tail": log[-4000:]}
    vcd = find_trace_vcd(f"{work}/solve_{winner}")
    bits = enabled_I_from_trace(vcd)
    grid = write_found_bits(bits, work)
    return {
        "found": True,
        "winner": winner,
        "vcd": vcd,
        "bits": bits,
        "ones": bits.count("1"),
        "grid": grid,
        "per_task": per_task,
        "findings": findings,
    }


def solve_uniqueness(depth=135, jobs=4, work=WORK):
    """Step 4: run formal/solve_uniq.sby against out/solve_b/solve_found_bits.vh."""
    if not os.path.exists(f"{work}/solve_found_bits.vh"):
        raise FileNotFoundError(f"{work}/solve_found_bits.vh missing -- run solve_search() first")
    if depth != 135:
        _patch_depth("formal/solve_uniq.sby", depth)
    per_task, log = run_sby("formal/solve_uniq.sby", TASKS, f"{work}/solve_uniq", jobs=jobs)
    findings = {t: _interpret(t, s) for t, s in per_task.items()}
    print("solve_uniq.sby results:", per_task, "-> another (differing) solution reachable:", findings)
    known = [v for v in findings.values() if v is not None]
    unique = bool(known) and not any(known)  # every engine agrees: unreachable
    disagreement = len(set(known)) > 1
    return {
        "per_task": per_task,
        "findings": findings,
        "unique_within_bound": unique,
        "disagreement": disagreement,
        "log_tail": log[-4000:],
    }


def _patch_depth(sby_path, depth):
    with open(sby_path) as f:
        src = f.read()
    src2 = re.sub(r"^depth \d+$", f"depth {depth}", src, flags=re.M)
    if src2 == src:
        raise ValueError(f"{sby_path}: no 'depth N' line to patch")
    with open(sby_path, "w") as f:
        f.write(src2)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--depth", type=int, default=135)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--work", default=WORK)
    ap.add_argument("--skip-search", action="store_true", help="reuse an existing solve_found_bits.vh")
    ap.add_argument("--skip-uniq", action="store_true")
    args = ap.parse_args(argv)

    result = {}
    if not args.skip_search:
        result["search"] = solve_search(args.depth, args.jobs, args.work)
        if not result["search"]["found"]:
            print("No task found `success` reachable within the bound.", file=sys.stderr)
            return 1
        print(f"Found by {result['search']['winner']}: {result['search']['bits']}")
        print(f"ones={result['search']['ones']}")
        for row in result["search"]["grid"]:
            print(row)
    if not args.skip_uniq:
        result["uniqueness"] = solve_uniqueness(args.depth, args.jobs, args.work)
        print("unique_within_bound:", result["uniqueness"]["unique_within_bound"])
        if result["uniqueness"]["disagreement"]:
            print("WARNING: engines disagreed on uniqueness -- see log_tail", file=sys.stderr)
    with open(f"{args.work}/solve_summary.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
