"""S4 round trip on the puzzle: synthesize the recovered RTL and compare it with the puzzle.

    python -m tools.roundtrip.puzzle_rt blocks  [--recipe warmup]   # each rec_<block> alone
    python -m tools.roundtrip.puzzle_rt control [--recipe warmup]   # the puzzle's own gates, resynthesized
    python -m tools.roundtrip.puzzle_rt equiv NAME [NAME ...]       # sequential equivalence, full runs
    python -m tools.roundtrip.puzzle_rt report                      # tables + summary.json

Everything is written under out/roundtrip/rt_synth/ (OUT). The full-design runs are plain
tools.roundtrip.synth runs into OUT/<NAME>/: warmup (the calibrated recipe), ll30 (LibreLane
3.0 defaults: flatten, AREA 0, sky130 cell exclusions), ll30_nosynthlist / ll30_nolists
(no no_synth.cells, i.e. no drive-strength restriction / no exclusions at all), all with
Yosys 0.62, plus warmup_y066, warmup_y069, ll30_y066 (other Yosys builds). OUT/run_full.sh
has the commands; OUT/run_native.sh reruns three of them with LibreLane's own synthesize.py.

Puzzle side (`puzzle_counts`): the logic instances of upstream/puzzle.gds (Extraction:
tap, decap, fill and diode cells are physical and already excluded; there are 10 diode_2)
minus the clock-tree cells that CTS adds (synth.cell_kinds() on the extracted connectivity:
the 32 clkbuf_*), i.e. what synthesis would have produced: 696 cells, 92 of them flops.
Area = sum of the liberty `area` of each master.

Cell kinds everywhere are synth.cell_kinds() (connectivity, not master name): the full runs
are synthesis results, classified pre_cts from their netlist_flat.json, so a clock-family
master that ABC used as logic (the clkinv_1 data inverters of ll30_nosynthlist and
ll30_nolists) counts as logic; the puzzle is a post-CTS layout, so its clock-tree cells are
found by what they drive.

Per block (`blocks`): the puzzle's cells per block are tools.viz.puzzle.block_cells() (flops
plus the logic cone cut at flops; 14 gates sit in two or more cones and are counted in each),
compared with rec_<block> synthesized alone (combinational, so gates only) and with the
rec_<block> instance of the hierarchical full run.

Control (`control`): the extracted puzzle netlist and each gold cone
(tools.analysis.cone.gold_module), turned into generic gates through the liberty functions
(flattened) and fed to the same recipe. It shows what the flow makes of the puzzle's own
structure once module boundaries are gone. Calibrated with two netlists whose origin is
known: upstream/warmup/01_netlist.v (a keep-hierarchy flow output; output under out/ only)
and our own keep-hierarchy result OUT/warmup/netlist.v.

Equivalence (`equiv`): the e2e miter (formal/recovered_miter.sv, as tools.analysis.e2e runs it)
with the recovered RTL on the "gold" side and the synthesized netlist on the "gate" side:
reset asserted in the first cycle, then O, success and all 92 flops (probed by register
name) equal forever; SymbiYosys abc pdr. Per-block runs get a combinational SAT miter.
"""

import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys

from tools.roundtrip import synth
from tools.roundtrip.synth import LIB, ROOT

OUT = os.path.join(ROOT, "out/roundtrip/rt_synth")
BLOCKS = ["counter", "array", "left_top", "left_bottom", "check", "outgen"]
RTL = [os.path.join(ROOT, "rtl_recovered/puzzle_recovered.v")] + [
    os.path.join(ROOT, f"rtl_recovered/{b}.v") for b in BLOCKS]
BIN = os.path.expanduser("~/ttsetup/oss-cad-suite/bin")
FLOP = ("df", "sdf", "edf", "dl")


def short(master):
    return master.split("__")[-1]


def is_flop(master):
    return short(master).startswith(FLOP)


def logic_of(module, pre_cts):
    """{master: n} of the logic cells of a Yosys JSON module, split by synth.cell_kinds()."""
    kinds = synth.cell_kinds(module, pre_cts)
    return dict(collections.Counter(c["type"] for n, c in module["cells"].items() if kinds[n] == "logic"))


def stats(logic):
    """count, flops, gates and liberty area of a {master: n} histogram of logic cells, as
    split by synth.cell_kinds() (logic_of(), puzzle_counts()): connectivity, not master
    name, so the clkinv_1 data inverters of ll30_nosynthlist / ll30_nolists count (619 /
    620 cells; by master name it was 609 / 611)."""
    areas = synth.cell_areas()
    fl = {m: n for m, n in logic.items() if is_flop(m)}
    area = sum(areas[m] * n for m, n in logic.items())
    farea = sum(areas[m] * n for m, n in fl.items())
    return {"cells": sum(logic.values()), "flops": sum(fl.values()), "gates": sum(logic.values()) - sum(fl.values()),
            "area": round(area, 4), "flop_area": round(farea, 4), "gate_area": round(area - farea, 4),
            "histogram": {short(m): n for m, n in sorted(logic.items())}}


# ---- puzzle ------------------------------------------------------------------------------


def puzzle_module(inst, pins):
    """The puzzle's logic instances (tools.analysis.cone.design(): `inst`, and `pins`
    {instance: {pin: net}} without supplies) as a Yosys-JSON-like module, nets numbered,
    for synth.cell_kinds()."""
    bit = {}
    return {"cells": {i: {"type": v["master"],
                          "connections": {p: [bit.setdefault(n, len(bit) + 2)] for p, n in sorted(pins.get(i, {}).items())}}
                      for i, v in inst.items()}}


def puzzle_counts():
    """{master: n} of the puzzle's pre-CTS logic: logic instances minus the clock-tree cells
    (synth.cell_kinds() on the extracted connectivity, the layout being post-CTS)."""
    from tools.analysis import cone

    ex, _lef, inst, pins, *_ = cone.design()
    kinds = synth.cell_kinds(puzzle_module(inst, pins), pre_cts=False)
    logic = collections.Counter(inst[n]["master"] for n, k in kinds.items() if k == "logic")
    dropped = collections.Counter(short(inst[n]["master"]) for n, k in kinds.items() if k != "logic")
    phys = collections.Counter(i["master"] for i in ex.instances if i["name"] not in inst)
    return dict(logic), dict(sorted(dropped.items())), {short(m): n for m, n in sorted(phys.items())}, len(ex.instances)


def puzzle_blocks():
    """{block: {master: n}} of the puzzle's gates per block (flops excluded), plus flop counts."""
    from tools.analysis import cone
    from tools.viz.puzzle import block_cells

    _ex, _lef, inst, *_ = cone.design()
    cells, flops = block_cells()
    out = {}
    for b in BLOCKS:
        c = collections.Counter(inst[i]["master"] for i in cells[b] if not is_flop(inst[i]["master"]))
        out[b] = dict(c)
    owners = collections.Counter(i for b in BLOCKS for i in cells[b])
    shared = {i: sorted(b for b in BLOCKS if i in cells[b]) for i, n in owners.items() if n > 1}
    return out, dict(flops), shared


# ---- per-block synthesis -----------------------------------------------------------------


def run_blocks(recipe_name, sets=()):
    recipe = synth.with_overrides(synth.RECIPES[recipe_name], sets)
    res = {}
    for b in BLOCKS:
        out = os.path.join(OUT, "blocks", recipe_name, b)
        h = synth.run([os.path.join(ROOT, f"rtl_recovered/{b}.v")], f"rec_{b}", recipe, out, name=recipe_name)
        ok, log = comb_equiv(os.path.join(ROOT, f"rtl_recovered/{b}.v"), os.path.join(out, "netlist.v"), f"rec_{b}")
        with open(os.path.join(out, "equiv.log"), "w") as f:
            f.write(log)
        res[b] = {"logic": h["logic"], "equivalent": ok}
        print(f"{b:12s} {h['logic']['count']:4d} cells {h['logic']['area']:9.2f} um^2  equivalent={ok}")
    return res


def comb_equiv(rtl, netlist, top):
    """SAT miter: rtl's `top` against the synthesized `top` (renamed syn_<top>)."""
    work = os.path.dirname(netlist)
    syn = os.path.join(work, "netlist_syn.v")
    with open(netlist) as f:
        src = f.read()
    with open(syn, "w") as f:
        f.write(rename_modules(src, "syn_"))
    script = (f"read_liberty -ignore_miss_func {LIB}; read_verilog {syn}; read_verilog -sv {rtl}; "
              f"hierarchy -check; proc; flatten; opt_clean; "
              f"miter -equiv -flatten -make_assert {top} syn_{top} miter; hierarchy -top miter; "
              f"sat -verify -prove-asserts miter")
    r = subprocess.run([f"{BIN}/yosys", "-p", script], capture_output=True, text=True)
    return r.returncode == 0 and "SUCCESS!" in r.stdout, (r.stdout + r.stderr)[-4000:]


def rename_modules(src, prefix):
    names = re.findall(r"^module\s+(\w+)", src, re.M)
    if not names:
        return src
    rx = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b")
    return rx.sub(lambda m: prefix + m[1], src)


# ---- control: the puzzle's own gates through the same flow ------------------------------


def generic(verilog_text, top, dst):
    """Write `top` as generic gates (liberty functions, flattened) to dst."""
    src = dst + ".cells.v"
    with open(src, "w") as f:
        f.write(verilog_text)
    phys = " ".join(f"{top}/t:sky130_fd_sc_hd__{p}*" for p in synth.PHYSICAL)
    script = (f"read_liberty -ignore_miss_func {LIB}; read_verilog {src}; delete {phys}; "
              f"hierarchy -top {top}; proc; flatten; opt_clean; write_verilog -noattr {dst}")
    subprocess.run([f"{BIN}/yosys", "-q", "-p", script], check=True)


def run_control(recipe_name, sets=()):
    from tools.analysis import cone, e2e
    from tools.retrace.extract import Extraction
    from tools.retrace.lef import read_lef

    recipe = synth.with_overrides(synth.RECIPES[recipe_name], sets)
    base = os.path.join(OUT, "control", recipe_name)
    os.makedirs(base, exist_ok=True)
    res = {}
    lef = read_lef(e2e.LEF)
    full = Extraction(e2e.GDS, lef, top="puzzle").to_verilog(e2e.DIRS, lef)
    jobs = [("puzzle", "puzzle", full)] + [(b, f"gold_{b}", cone.gold_module(b)[0]) for b in BLOCKS]
    # calibration of this control: the warm-up's own flow output (keep hierarchy, 76 logic
    # cells, reproduced exactly by recipe warmup), flattened and resynthesized the same way
    with open(os.path.join(ROOT, "upstream/warmup/01_netlist.v")) as f:
        jobs.append(("warmup_ref", "adder_demo", f.read()))
    # and our own keep-hierarchy result for the recovered RTL (full run OUT/warmup), the same way
    ours = os.path.join(OUT, "warmup", "netlist.v")
    if os.path.exists(ours):
        with open(ours) as f:
            jobs.append(("rt_keep", "puzzle_recovered", f.read()))
    for name, top, text in jobs:
        g = os.path.join(base, f"{name}_generic.v")
        generic(text, top, g)
        out = os.path.join(base, name)
        h = synth.run([g], top, recipe, out, name=recipe_name)
        res[name] = {"logic": h["logic"], "cells": {short(m): n for m, n in h["cells"].items()}}
        print(f"{name:12s} {h['logic']['count']:4d} cells {h['logic']['area']:9.2f} um^2")
    with open(os.path.join(base, "control.json"), "w") as f:
        json.dump(res, f, indent=1)
    return res


# ---- sequential equivalence of a full run ------------------------------------------------


def reg_drivers():
    """{fNN: register name} from rtl_recovered/puzzle_recovered.v (as tools.analysis.e2e)."""
    with open(RTL[0]) as f:
        src = f.read()
    d = {m.group(2): m.group(1) for m in re.finditer(r"^\s*reg\s+(\w+)\s*;\s*//\s*(f\d\d)\b", src, re.M)}
    assert len(d) == 92, len(d)
    return src, d


def seq_equiv(name, timeout=3000):
    from tools.analysis.e2e import _add_probes

    run_dir = os.path.join(OUT, name)
    work = os.path.join(OUT, "equiv", name)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    rtl_src, drivers = reg_drivers()
    with open(os.path.join(work, "rtl_probe.v"), "w") as f:
        f.write(_add_probes(rtl_src, "puzzle_recovered", "rtl_probe", drivers))
    for b in BLOCKS:
        shutil.copy(os.path.join(ROOT, f"rtl_recovered/{b}.v"), work)
    with open(os.path.join(run_dir, "netlist.v")) as f:
        syn = rename_modules(f.read(), "syn_")
    m = re.search(r"^module\s+syn_puzzle_recovered\s*\(.*?^endmodule\n?", syn, re.M | re.S)
    top = m[0]
    syn_drivers, aliased = {}, {}
    nxt = dict(re.findall(r"^\s*(\w+)\s*<=\s*(next_\w+)\s*;", rtl_src, re.M))
    for k, r in drivers.items():
        if re.search(r"^\s*(wire|output|reg)\b[^;]*\b" + r + r"\s*;", top, re.M):
            syn_drivers[k] = r
            continue
        # the register's net was merged into another name (flattened runs: success_latch is
        # the `success` port); take the Q net of the flop whose D is the register's next_ net
        q = None
        for cell in re.findall(r"sky130_fd_sc_hd__d\w+\s+\S+\s*\((.*?)\);", top, re.S):
            if re.search(r"\.D\(" + re.escape(nxt.get(r, "?")) + r"\)", cell):
                q = re.search(r"\.Q\(([^)]*)\)", cell)[1].strip()
        if q is None:
            raise SystemExit(f"{name}: register {r} ({k}) not found in the synthesized top")
        syn_drivers[k], aliased[r] = q, q
    with open(os.path.join(work, "syn_probe.v"), "w") as f:
        f.write(syn[:m.start()] + _add_probes(top, "syn_puzzle_recovered", "syn_probe", syn_drivers) + syn[m.end():])
    with open(os.path.join(ROOT, "formal/recovered_miter.sv")) as f:
        miter = f.read()
    assert "puzzle_probe gold (" in miter and "puzzle_recovered_probe gate (" in miter
    miter = miter.replace("puzzle_probe gold (", "rtl_probe gold (").replace("puzzle_recovered_probe gate (", "syn_probe gate (")
    miter = ("// copy of formal/recovered_miter.sv made by tools/roundtrip/puzzle_rt.py: gold = recovered RTL\n"
             f"// (rtl_recovered/), gate = synthesized netlist out/roundtrip/rt_synth/{name}/netlist.v\n" + miter)
    with open(os.path.join(work, "miter.sv"), "w") as f:
        f.write(miter)
    shutil.copy(LIB, work)
    lib = os.path.basename(LIB)
    blocks = " ".join(f"{b}.v" for b in BLOCKS)
    nl = "\n"
    sby = f"""[options]
mode prove

[engines]
abc pdr

[script]
read_liberty -ignore_miss_func {lib}
read_verilog syn_probe.v
read_verilog rtl_probe.v {blocks}
read_verilog -formal miter.sv
hierarchy -check -top recovered_miter
flatten
prep -top recovered_miter

[files]
{lib}
syn_probe.v
rtl_probe.v
{nl.join(f"{b}.v" for b in BLOCKS)}
miter.sv
"""
    with open(os.path.join(work, "equiv.sby"), "w") as f:
        f.write(sby)
    env = dict(os.environ, PATH=BIN + os.pathsep + os.environ["PATH"])
    r = subprocess.run([f"{BIN}/sby", "-f", "equiv.sby"], cwd=work, env=env, capture_output=True, text=True,
                       timeout=timeout)
    ok = "DONE (PASS" in r.stdout
    with open(os.path.join(work, "result.json"), "w") as f:
        json.dump({"netlist": os.path.relpath(os.path.join(run_dir, "netlist.v"), ROOT), "pass": ok,
                   "probes_aliased": aliased,
                   "summary": [l for l in r.stdout.splitlines() if "summary" in l or "DONE" in l][-12:]}, f, indent=1)
    return ok, r.stdout[-2500:]


# ---- report ------------------------------------------------------------------------------


def load_run(name):
    """(all cells {master: n}, stats()) of the full run OUT/<name>: logic split pre-CTS by
    synth.cell_kinds() on its netlist_flat.json (a synthesis result: no CTS has run)."""
    with open(os.path.join(OUT, name, "histogram.json")) as f:
        h = json.load(f)
    counts = {m: n for m, n in h["cells"].items()}
    with open(os.path.join(OUT, name, "netlist_flat.json")) as f:
        mod = json.load(f)["modules"][h["meta"]["top"]]
    logic = logic_of(mod, pre_cts=True)
    if "by_kind" in h:  # histograms written by synth.run() since cell_kinds(): must agree
        assert logic == h["by_kind"]["logic"], (name, "histogram.json by_kind disagrees with netlist_flat.json")
    s = stats(logic)
    s["classified_by"] = "synth.cell_kinds(pre_cts=True) on netlist_flat.json"
    s["recipe"] = h["meta"]["recipe_name"]
    s["recipe_knobs"] = {k: v for k, v in h["meta"]["recipe"].items()
                         if v != getattr(synth.LL30, k) and k != "yosys"}
    s["yosys"] = h["meta"]["yosys"].split("(")[0].strip()
    eq = os.path.join(OUT, "equiv", name, "result.json")
    s["seq_equivalent"] = json.load(open(eq))["pass"] if os.path.exists(eq) else None
    return counts, s


def per_instance(name):
    from tools.roundtrip.compare import load_module, per_instance as pi

    mod = load_module(os.path.join(OUT, name, "netlist.v"), "puzzle_recovered")
    return {k: v for k, v in pi(mod, pre_cts=True).items()}


def by_function(hist):
    """Histogram with the drive-strength suffix dropped (nand2_2 and nand2_1 -> nand2)."""
    out = collections.Counter()
    for m, n in hist.items():
        out[re.sub(r"_\d+$", "", m)] += n
    return dict(out)


def puzzle_block_gate_names():
    from tools.analysis import cone
    from tools.viz.puzzle import block_cells

    _ex, _lef, inst, *_ = cone.design()
    cells, _flops = block_cells()
    return {b: {i for i in cells[b] if not is_flop(inst[i]["master"])} for b in BLOCKS}


def diff(a, b):
    ms = sorted(set(a) | set(b))
    return {m: a.get(m, 0) - b.get(m, 0) for m in ms if a.get(m, 0) != b.get(m, 0)}


def report(runs):
    pc, dropped, phys, total = puzzle_counts()
    ps = stats(pc)
    ps["classified_by"] = "synth.cell_kinds(pre_cts=False) on the extracted puzzle.gds connectivity"
    ps["dropped_clock_cells"] = dropped
    ps["physical_cells"] = phys
    ps["gds_instances"] = total
    ps["drive_strengths"] = dict(collections.Counter(re.sub(r"^.*_", "_", m) for m in ps["histogram"]
                                                     for _ in range(ps["histogram"][m])))
    summary = {"puzzle": ps, "runs": {}, "blocks": {}}
    print(f"puzzle pre-CTS logic: {ps['cells']} cells ({ps['flops']} flops, {ps['gates']} gates), "
          f"{ps['area']} um^2; dropped clock cells {dropped}; physical {phys}")
    for name in runs:
        counts, s = load_run(name)
        s["diff_vs_puzzle"] = diff(s["histogram"], ps["histogram"])
        s["l1_vs_puzzle"] = sum(abs(v) for v in s["diff_vs_puzzle"].values())
        s["l1_function_vs_puzzle"] = sum(abs(v) for v in diff(by_function(s["histogram"]),
                                                               by_function(ps["histogram"])).values())
        s["drive_strengths"] = dict(collections.Counter(re.sub(r"^.*_", "_", m) for m in s["histogram"]
                                                        for _ in range(s["histogram"][m])))
        s["cells_ratio_to_puzzle"] = round(s["cells"] / ps["cells"], 4)
        s["area_ratio_to_puzzle"] = round(s["area"] / ps["area"], 4)
        summary["runs"][name] = s
        print(f"{name:18s} {s['cells']:4d} cells ({s['flops']} flops, {s['gates']} gates) {s['area']:9.2f} um^2 "
              f"= {s['cells'] / ps['cells']:.3f}x cells, {s['area'] / ps['area']:.3f}x area; L1 {s['l1_vs_puzzle']} "
              f"(function-only {s['l1_function_vs_puzzle']}); seq-equiv {s['seq_equivalent']}")
    # per block
    pb, pflops, shared = puzzle_blocks()
    pcells = puzzle_block_gate_names()
    areas = synth.cell_areas()
    hier = per_instance("warmup") if "warmup" in runs else {}
    ctl_path = os.path.join(OUT, "control", "warmup", "control.json")
    ctl = json.load(open(ctl_path)) if os.path.exists(ctl_path) else {}
    for b in BLOCKS:
        row = {"puzzle_flops": pflops.get(b, 0), "puzzle_gates": sum(pb[b].values()),
               "puzzle_gates_shared_split": round(sum(1 / len(shared[i]) if i in shared else 1
                                                      for i in pcells[b]), 2),
               "puzzle_gate_area": round(sum(areas[m] * n for m, n in pb[b].items()), 4),
               "puzzle_histogram": {short(m): n for m, n in sorted(pb[b].items())}}
        p = os.path.join(OUT, "blocks", "warmup", b, "histogram.json")
        if os.path.exists(p):
            h = json.load(open(p))
            row["alone_gates"] = h["logic"]["count"]
            row["alone_gate_area"] = h["logic"]["area"]
            row["alone_histogram"] = {short(m): n for m, n in h["cells"].items()}
            eqlog = os.path.join(OUT, "blocks", "warmup", b, "equiv.log")
            row["alone_equivalent"] = os.path.exists(eqlog) and "SUCCESS!" in open(eqlog).read()
        inst = hier.get(f"u_{b}")
        if inst:
            row["hier_gates"] = sum(inst.values())
            row["hier_gate_area"] = round(sum(areas[m] * n for m, n in inst.items()), 4)
        if b in ctl:
            row["control_gates"] = ctl[b]["logic"]["count"]
            row["control_gate_area"] = ctl[b]["logic"]["area"]
        summary["blocks"][b] = row
    if ctl:
        summary["control"] = {k: v["logic"] for k, v in ctl.items()}
    summary["shared_gates"] = shared
    if hier:
        top_cells = hier.get("", {})
        summary["warmup_top_level_cells"] = {short(m): n for m, n in top_cells.items()}
    print(f"\n{'block':12s} {'flops':>5s} {'puz gates':>9s} {'puz area':>9s} {'rec alone':>9s} {'area':>9s} "
          f"{'in hier':>7s} {'ctl':>5s} {'ratio':>6s}")
    for b, r in summary["blocks"].items():
        ratio = r["puzzle_gates"] / r["alone_gates"] if r.get("alone_gates") else float("nan")
        print(f"{b:12s} {r['puzzle_flops']:5d} {r['puzzle_gates']:9d} {r['puzzle_gate_area']:9.2f} "
              f"{r.get('alone_gates', -1):9d} {r.get('alone_gate_area', -1):9.2f} {r.get('hier_gates', -1):7d} "
              f"{r.get('control_gates', -1):5d} {ratio:6.2f}")
    with open(os.path.join(OUT, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("blocks", "control"):
        p = sub.add_parser(c)
        p.add_argument("--recipe", default="warmup")
        p.add_argument("--set", action="append", default=[])
    e = sub.add_parser("equiv")
    e.add_argument("names", nargs="+")
    r = sub.add_parser("report")
    r.add_argument("runs", nargs="*", default=["warmup", "ll30", "ll30_nosynthlist", "ll30_nolists",
                                               "warmup_y066", "warmup_y069", "ll30_y066"])
    a = ap.parse_args(argv)
    if a.cmd == "blocks":
        run_blocks(a.recipe, a.set)
    elif a.cmd == "control":
        run_control(a.recipe, a.set)
    elif a.cmd == "equiv":
        bad = 0
        for n in a.names:
            ok, log = seq_equiv(n)
            print(f"{n}: sequential equivalence {'PASS' if ok else 'FAIL'}")
            if not ok:
                print(log)
                bad += 1
        return 1 if bad else 0
    else:
        report(a.runs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
