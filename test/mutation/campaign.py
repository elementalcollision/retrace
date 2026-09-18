"""Layout-mutation campaign (docs/spec/VERIFICATION.md section 2, "the TEMPO move").

Plants one deterministic fault per mutant in a *copy* of the warm-up or puzzle GDS
(tools/retrace/mutate.py), runs every applicable check layer on that mutant, and records
which layer(s) noticed. The question it answers: if the extraction were wrong in a
particular way, would at least one of our check layers notice?

    .venv/bin/python test/mutation/campaign.py --list           # candidate counts, no mutation
    .venv/bin/python test/mutation/campaign.py                  # full campaign -> out/mut/results.json
    .venv/bin/python test/mutation/campaign.py --quick 6         # first 6 mutants only (debug)

Run as a plain script (not `-m test.mutation.campaign`): the stdlib also ships a `test`
package, and this project's `test/` has no `__init__.py` (pytest's own rootdir-relative
collection does not need one), so `-m test...` can resolve to the wrong `test` package
first. A direct script run sidesteps that; it only imports the top-level `tools` package,
which has no such collision.

CAUTION: the test/test_*.py fixtures are functools.cache'd on the FIXED original paths.
This module never calls them for a mutant path -- it calls the underlying library
functions (Extraction, read_def, netgraph.compare, tools.l2n.*) directly with the
mutant's own path, and every mutant is asserted to be byte-different from the original
before it is scored.
"""

import argparse
import functools
import json
import multiprocessing
import os
import random
import shutil
import subprocess
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from tools.l2n import compare as l2n_compare  # noqa: E402
from tools.retrace import mutate  # noqa: E402
from tools.retrace.cellcheck import compare as cellcheck_compare, masters as cellcheck_masters  # noqa: E402
from tools.retrace.defparse import read_def  # noqa: E402
from tools.retrace.extract import PHYSICAL, PREFIX, SUPPLY_PINS, Extraction  # noqa: E402
from tools.retrace.lef import read_lef  # noqa: E402
from tools.retrace.netgraph import compare as netgraph_compare  # noqa: E402

OUT = os.path.join(ROOT, "out", "mut")
LEF_PATH = os.path.join(ROOT, "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef")
LIB_PATH = os.path.join(ROOT, "pdk/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib")
PDK_GDS = os.path.join(ROOT, "pdk/sky130_fd_sc_hd/gds/sky130_fd_sc_hd.gds")
BIN = os.path.expanduser("~/ttsetup/oss-cad-suite/bin")
MODELS = [os.path.join(ROOT, "pdk/sky130_fd_sc_hd/verilog/primitives.v"),
          os.path.join(ROOT, "pdk/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v")]

WARMUP_GDS = os.path.join(ROOT, "upstream/warmup/04_final.gds")
WARMUP_DEF = os.path.join(ROOT, "upstream/warmup/03_post_place_and_route.def")
WARMUP_GOLD_V = os.path.join(ROOT, "upstream/warmup/01_netlist.v")
PUZZLE_GDS = os.path.join(ROOT, "upstream/puzzle.gds")
PUZZLE_TB = os.path.join(ROOT, "out/tb_puzzle.v")  # shared & read-only: built once from the VCD, netlist-agnostic

FORMAL_SBY = os.path.join(ROOT, "formal/warmup_equiv.sby")
FORMAL_MITER = os.path.join(ROOT, "formal/warmup_miter.sv")
SBY = os.path.join(BIN, "sby")

TOP_NAME = {"warmup": "adder_demo", "puzzle": "puzzle"}
GDS_OF = {"warmup": WARMUP_GDS, "puzzle": PUZZLE_GDS}
WARMUP_DIRS = {p: "input" for p in ("A", "B", "clk", "en", "rst_n")} | {"S": "output"}
PUZZLE_DIRS = {p: "input" for p in ("clk", "rst_n", "enable", "I")} | {"O": "output", "success": "output"}
PUZZLE_INPUTS = {"clk", "rst_n", "enable", "I"}
PUZZLE_OUTPUTS = {"success"} | {f"O[{i}]" for i in range(8)}

SEED = 20260918  # the day this campaign was built; every site selection derives from it
TARGET_PER_OP = {"warmup": 6, "puzzle": 7}


# ============================================================ site selection ==========

@functools.lru_cache(maxsize=1)
def _lef():
    return read_lef(LEF_PATH)


@functools.lru_cache(maxsize=1)
def _pdk_cells():
    return mutate.load_pdk_cells(PDK_GDS)


@functools.lru_cache(maxsize=2)
def _orig_extraction(design):
    return Extraction(GDS_OF[design], _lef(), TOP_NAME[design])


def discover(design):
    ex = _orig_extraction(design)
    lef = _lef()
    return ex, {name: op.enumerate(ex, lef) for name, op in sorted(mutate.OPERATORS.items())}


def select_sites(design):
    """Deterministic: same SEED + design -> same mutants, every run."""
    _, cands = discover(design)
    rng = random.Random(f"{SEED}:{design}")
    chosen, avail = {}, {}
    for name in sorted(mutate.OPERATORS):
        pool = cands[name]
        avail[name] = len(pool)
        k = min(TARGET_PER_OP[design], len(pool))
        picks = rng.sample(pool, k) if pool else []
        out = []
        for s in picks:
            s = dict(s)
            s["seed"] = rng.randint(0, 2**31 - 1)
            out.append(s)
        chosen[name] = out
    return chosen, avail


def build_mutants():
    mutants, avail_report = [], {}
    for design in ("warmup", "puzzle"):
        chosen, avail = select_sites(design)
        avail_report[design] = avail
        for op_name in sorted(chosen):
            for i, site in enumerate(chosen[op_name]):
                mutants.append({"id": f"{design}_{op_name}_{i:02d}", "design": design,
                                "operator": op_name, "site": site})
    return mutants, avail_report


# ============================================================ check layers ============

def check_diagnostics(mgds, ex, lef, mdir, design):
    diag = dict(ex.diag)
    return (not diag), (f"{diag}" if diag else "")


def check_cellcheck(mgds, ex, lef, mdir, design):
    d = cellcheck_compare(cellcheck_masters(mgds), cellcheck_masters(PDK_GDS))
    return (not d), ("; ".join(sorted(d)[:5]) if d else "")


V2_LAYER = {"li1": 67, "met1": 68}


def check_v2_pins(mgds, ex, lef, mdir, design):
    from shapely.geometry import Polygon, box
    bad = []
    cells = {c.name: c for c in ex.lib.cells if c.name.startswith(PREFIX)}
    for name, cell in sorted(cells.items()):
        if name not in lef:
            bad.append(f"{name}: not a known LEF macro")
            continue
        pins = ex._master_pins(cell)
        ours = set(pins)
        theirs = {p for p, d in lef[name]["pins"].items() if d["rects"] and p not in ("VPB", "VNB")}
        if ours != theirs:
            bad.append(f"{name}: pin set differs {sorted(ours ^ theirs)}")
            continue
        # the finer check: every LEF pin rectangle must land on the *correspondingly
        # named* extracted pin conductor -- this is what actually catches a label swap
        # (the pin-name set alone is unchanged by a swap)
        geo = {p: {lyr: [Polygon(q.points) for q in polys if q.layer == lyr] for lyr in V2_LAYER.values()}
               for p, polys in pins.items()}
        for pin, d in lef[name]["pins"].items():
            if pin in SUPPLY_PINS:
                continue
            for layer, x0, y0, x1, y1 in d["rects"]:
                if layer not in V2_LAYER:
                    continue
                c = box(x0, y0, x1, y1).centroid
                owners = [p for p, g in geo.items() if any(q.buffer(1e-6).covers(c) for q in g[V2_LAYER[layer]])]
                if owners != [pin]:
                    bad.append(f"{name}.{pin} ({layer}): expected owner {pin!r}, got {owners}")
    return (not bad), ("; ".join(bad[:5]) if bad else "")


def check_v4(mgds, ex, lef, mdir, design):
    ours, theirs = l2n_compare.compare(mgds, ex)
    ours = {n for n in ours if len(n) > 1}
    theirs = {n for n in theirs if len(n) > 1}
    ok = ours == theirs
    return ok, ("" if ok else f"only-ours={len(ours - theirs)} only-klayout={len(theirs - ours)}")


def check_v1(mgds, ex, lef, mdir, design):
    golden = read_def(WARMUP_DEF)
    ours = sorted((i["master"], i["x"], i["y"], i["orient"]) for i in ex.instances)
    theirs = sorted(golden["components"].values())
    ok = ours == theirs
    return ok, ("" if ok else f"placement multiset differs: {len(ours)} vs {len(theirs)}")


def check_v3a(mgds, ex, lef, mdir, design):
    golden = read_def(WARMUP_DEF)
    by_pos = {v: k for k, v in golden["components"].items()}
    def_name_of = {i["name"]: by_pos.get((i["master"], i["x"], i["y"], i["orient"])) for i in ex.instances}
    ours = set()
    for m in ex.nets:
        s = {(def_name_of[i], p) for i, p in m["pins"] if p not in SUPPLY_PINS}
        s |= {("PIN", p) for p in m["ports"]}
        if s:
            ours.add(frozenset(s))
    theirs = {frozenset(pins) for pins in golden["nets"].values()}
    missing = theirs - ours
    extra_real = [n for n in (ours - theirs) if len(n) > 1]
    ok = not missing and not extra_real
    return ok, ("" if ok else f"missing={len(missing)} extra={len(extra_real)}")


def check_v3b(mgds, ex, lef, mdir, design):
    v_path = os.path.join(mdir, "adder_demo.v")
    with open(v_path, "w") as f:
        f.write(ex.to_verilog(WARMUP_DIRS, lef))
    same, ours, theirs = netgraph_compare(v_path, "adder_demo", WARMUP_GOLD_V, "adder_demo")
    ok = same and ours == theirs
    return ok, ("" if ok else f"isomorphic={same} ours={ours} theirs={theirs}")


def check_v3c(mgds, ex, lef, mdir, design):
    v_path = os.path.join(mdir, "adder_demo.v")
    if not os.path.exists(v_path):
        with open(v_path, "w") as f:
            f.write(ex.to_verilog(WARMUP_DIRS, lef))
    with open(FORMAL_SBY) as f:
        content = f.read()
    # out/mut/<id>/ is 3 levels below the repo root; formal/ is 1
    content = (content.replace("../pdk/", "../../../pdk/")
                       .replace("../upstream/", "../../../upstream/")
                       .replace("../out/adder_demo.v", "adder_demo.v"))
    with open(os.path.join(mdir, "warmup_equiv.sby"), "w") as f:
        f.write(content)
    shutil.copy(FORMAL_MITER, os.path.join(mdir, "warmup_miter.sv"))
    shutil.rmtree(os.path.join(mdir, "warmup_equiv"), ignore_errors=True)
    env = dict(os.environ, PATH=BIN + os.pathsep + os.environ["PATH"])
    r = subprocess.run([SBY, "-f", "warmup_equiv.sby"], cwd=mdir, env=env, capture_output=True, text=True, timeout=180)
    ok = "DONE (PASS" in r.stdout
    return ok, ("" if ok else r.stdout[-600:])


def check_v5(mgds, ex, lef, mdir, design):
    problems = []
    masters_map = {i["name"]: i["master"] for i in ex.instances}

    def direction(inst, pin):
        m = masters_map[inst]
        return lef.get(m, {}).get("pins", {}).get(pin, {}).get("direction") if m in lef else None

    def is_logic(name):
        m = masters_map[name]
        short = m[len(PREFIX):] if m.startswith(PREFIX) else m
        return not short.startswith(PHYSICAL)

    def signal_nets():
        for m in ex.nets:
            pins = [(i, p) for i, p in m["pins"] if p not in SUPPLY_PINS]
            if pins or m["ports"]:
                yield m, pins

    if set(ex.ports) != PUZZLE_INPUTS | PUZZLE_OUTPUTS:
        problems.append(f"ports={sorted(ex.ports)}")
    sup = [m for m in ex.nets if m["supply"]]
    n_inst = len(ex.instances)
    if sorted(tuple(sorted(m["supply"])) for m in sup) != [("VGND",), ("VPWR",)]:
        problems.append("supply nets malformed")
    for m in sup:
        (name,) = tuple(m["supply"]) if len(m["supply"]) == 1 else (None,)
        pins = Counter(p for _i, p in m["pins"])
        if name is None or set(pins) - {name} or pins.get(name, 0) != n_inst:
            problems.append(f"supply net {m['name']} reaches {pins} of {n_inst}")
    for m, pins in signal_nets():
        drivers = [ip for ip in pins if direction(*ip) == "OUTPUT"]
        drivers += [("PORT", p) for p in m["ports"] if p in PUZZLE_INPUTS]
        if len(drivers) != 1:
            problems.append(f"net {m['name']} has {len(drivers)} drivers")
        if not drivers:
            problems += [f"floating {ip}" for ip in pins if is_logic(ip[0])]
    unexpected = []
    for m, pins in signal_nets():
        loads = [ip for ip in pins if direction(*ip) == "INPUT"] + [p for p in m["ports"] if p in PUZZLE_OUTPUTS]
        if loads:
            continue
        for inst, pin in pins:
            master = masters_map[inst]
            short = master[len(PREFIX):] if master.startswith(PREFIX) else master
            if short.startswith("conb_"):
                continue
            if short.startswith("clkbuf_"):
                net_a = ex.net_of.get((inst, "A"))
                if any(p == "CLK" for m2 in ex.nets if m2["name"] == net_a for _i, p in m2["pins"]):
                    continue
            unexpected.append((inst, pin))
    if unexpected:
        problems.append(f"unexpected unloaded outputs: {unexpected[:3]}")
    ok = not problems
    return ok, ("; ".join(str(p) for p in problems[:5]) if problems else "")


def _vcd_result(stdout):
    line = next((l for l in stdout.splitlines() if l.startswith("VCD-REPLAY")), None)
    return dict(kv.split("=") for kv in line.split()[1:]) if line else None


def check_v6_icarus(mgds, ex, lef, mdir, design):
    v_path = os.path.join(mdir, "puzzle.v")
    with open(v_path, "w") as f:
        f.write(ex.to_verilog(PUZZLE_DIRS, lef))
    vvp = os.path.join(mdir, "replay_icarus.vvp")
    r = subprocess.run([f"{BIN}/iverilog", "-g2012", "-DFUNCTIONAL", "-DUNIT_DELAY=", "-o", vvp,
                        PUZZLE_TB, v_path, *MODELS], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return False, f"compile failed: {r.stderr[-500:]}"
    # a short between two actively-driven nets can make a zero-delay simulator spin
    # forever on delta-cycle contention instead of erroring; a hang is itself a kill
    try:
        r = subprocess.run([f"{BIN}/vvp", "-n", vvp], capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        return False, "vvp did not terminate in 25s (likely delta-cycle contention from a short)"
    res = _vcd_result(r.stdout)
    if res is None:
        return False, (r.stdout[-500:] + r.stderr[-300:])
    ok = res == {"checked": "1248", "errors": "0"}
    return ok, ("" if ok else str(res))


def check_v6_verilator(mgds, ex, lef, mdir, design):
    v_path = os.path.join(mdir, "puzzle.v")
    if not os.path.exists(v_path):
        with open(v_path, "w") as f:
            f.write(ex.to_verilog(PUZZLE_DIRS, lef))
    flat = os.path.join(mdir, "puzzle_libflat.v")
    r = subprocess.run([f"{BIN}/yosys", "-q", "-p",
                        f"read_liberty -ignore_miss_func {LIB_PATH}; read_verilog {v_path}; hierarchy -top puzzle; "
                        f"flatten; proc; opt_clean; write_verilog -noattr {flat}"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return False, f"yosys failed: {r.stderr[-500:]}"
    vldir = os.path.join(mdir, "vl")
    shutil.rmtree(vldir, ignore_errors=True)
    env = dict(os.environ, PATH=BIN + os.pathsep + os.environ["PATH"])
    r = subprocess.run([f"{BIN}/verilator", "--binary", "--timing", "-Wno-fatal", "-Wno-lint", "-Wno-style",
                        "--top-module", "tb", "-Mdir", vldir, PUZZLE_TB, flat, "-o", "vtb"],
                       capture_output=True, text=True, env=env, timeout=90)
    if r.returncode != 0:
        return False, f"verilator build failed: {r.stderr[-500:]}"
    try:
        r = subprocess.run([os.path.join(vldir, "vtb")], capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        return False, "vtb did not terminate in 25s (likely delta-cycle contention from a short)"
    res = _vcd_result(r.stdout)
    if res is None:
        return False, r.stdout[-500:]
    ok = res == {"checked": "1248", "errors": "0"}
    return ok, ("" if ok else str(res))


LAYERS_BY_DESIGN = {
    "warmup": [("diagnostics", check_diagnostics), ("cellcheck", check_cellcheck),
               ("V1_placements", check_v1), ("V2_pins", check_v2_pins),
               ("V3a_partition", check_v3a), ("V3b_isomorphism", check_v3b),
               ("V3c_formal", check_v3c), ("V4_extractors_agree", check_v4)],
    "puzzle": [("diagnostics", check_diagnostics), ("cellcheck", check_cellcheck),
               ("V2_pins", check_v2_pins), ("V4_extractors_agree", check_v4),
               ("V5_sanity", check_v5), ("V6_icarus", check_v6_icarus)],
}


# ============================================================ equivalence =============

def _instance_multiset(ex):
    return sorted((i["master"], i["x"], i["y"], i["orient"]) for i in ex.instances)


def _partition(ex):
    key = {i["name"]: f"{i['master']}@{i['x']},{i['y']}" for i in ex.instances}
    out = set()
    for m in ex.nets:
        s = frozenset((key[i], p) for i, p in m["pins"] if p not in SUPPLY_PINS)
        s |= frozenset(("PORT", p) for p in m["ports"])
        if s:
            out.add(s)
    return out


def is_electrically_equivalent(ex_orig, ex_mut):
    """Same instances (incl. orientation and master) and same net partition => the mutant
    has zero electrical effect (e.g. a redundant via, deleted pixel art)."""
    return _instance_multiset(ex_orig) == _instance_multiset(ex_mut) and _partition(ex_orig) == _partition(ex_mut)


# ============================================================ per-mutant worker ========

def _run_check(fn, name, mgds, ex, lef, mdir, design):
    try:
        ok, detail = fn(mgds, ex, lef, mdir, design)
    except Exception as e:  # a crashing check also counts as "noticed something's wrong"
        ok, detail = False, f"{type(e).__name__}: {e}"
    return name, {"pass": bool(ok), "detail": detail}


def run_mutant(spec, sample_verilator=False):
    mid, design, op_name, site = spec["id"], spec["design"], spec["operator"], spec["site"]
    t0 = time.time()
    lef = _lef()
    base_gds = GDS_OF[design]
    mdir = os.path.join(OUT, mid)
    os.makedirs(mdir, exist_ok=True)
    mgds = os.path.join(mdir, f"{design}.gds")

    try:
        lib = mutate.load(base_gds)
        description = mutate.OPERATORS[op_name].apply(lib, TOP_NAME[design], site, lef, _pdk_cells())
        lib.write_gds(mgds)
        with open(mgds, "rb") as f1, open(base_gds, "rb") as f2:
            if f1.read() == f2.read():
                raise AssertionError("mutant GDS is byte-identical to the original -- operator did nothing")
        lef = mutate.lef_for_mutant(lef, lib)  # private per-mutant cell copies need a LEF entry too
        # explicit top=: some operators (master_swap, pin_label_swap, cell_internal_tamper)
        # can leave a standard-cell master with zero remaining references, which makes it
        # a second gdstk "top level" cell -- Extraction()'s default (tops[0]) can then pick
        # the wrong one
        ex = Extraction(mgds, lef, TOP_NAME[design])
    except Exception as e:
        return {"id": mid, "design": design, "operator": op_name, "site": site, "description": None,
                "error": f"{type(e).__name__}: {e}", "classification": "error", "layers": {},
                "seconds": round(time.time() - t0, 2)}

    layers = {}
    for name, fn in LAYERS_BY_DESIGN[design]:
        name, result = _run_check(fn, name, mgds, ex, lef, mdir, design)
        layers[name] = result
    if design == "puzzle" and sample_verilator:
        name, result = _run_check(check_v6_verilator, "V6_verilator", mgds, ex, lef, mdir, design)
        layers[name] = result

    if any(not v["pass"] for v in layers.values()):
        classification = "killed"
    elif is_electrically_equivalent(_orig_extraction(design), ex):
        classification = "equivalent"
    else:
        classification = "survived"

    return {"id": mid, "design": design, "operator": op_name, "site": site, "description": description,
            "error": None, "classification": classification, "layers": layers,
            "seconds": round(time.time() - t0, 2)}


# ============================================================ reporting ===============

def summarize(results):
    by_op = {}
    layer_totals, layer_kills = Counter(), Counter()
    for r in results:
        key = f"{r['design']}/{r['operator']}"
        e = by_op.setdefault(key, Counter())
        e["planted"] += 1
        if r["classification"] == "error":
            e["error"] += 1
            continue
        e[r["classification"]] += 1
        for layer, res in r["layers"].items():
            layer_totals[layer] += 1
            if not res["pass"]:
                layer_kills[layer] += 1
                e[f"killed_by:{layer}"] += 1
    return {
        "by_operator": {k: dict(v) for k, v in sorted(by_op.items())},
        "layer_kill_rate": {l: {"applicable": layer_totals[l], "killed": layer_kills[l],
                                "rate": round(layer_kills[l] / layer_totals[l], 3) if layer_totals[l] else None}
                            for l in sorted(layer_totals)},
        "totals": dict(Counter(r["classification"] for r in results)),
        "errors": [r["id"] for r in results if r["classification"] == "error"],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="print candidate/selected site counts and exit")
    ap.add_argument("--quick", type=int, default=0, help="only run the first N mutants (debug)")
    ap.add_argument("--workers", type=int, default=min(18, os.cpu_count() or 4))
    ap.add_argument("--verilator-every", type=int, default=6, help="sample V6_verilator every Nth puzzle mutant")
    args = ap.parse_args(argv)

    mutants, avail = build_mutants()
    if args.list:
        for design, counts in avail.items():
            print(design)
            for op, n in sorted(counts.items()):
                k = min(TARGET_PER_OP[design], n)
                print(f"  {op:24s} candidates={n:5d} selected={k}")
        print(f"total mutants: {len(mutants)}")
        return 0

    if args.quick:
        mutants = mutants[:args.quick]

    jobs, puzzle_idx = [], 0
    for spec in mutants:
        sample = False
        if spec["design"] == "puzzle":
            sample = (puzzle_idx % args.verilator_every == 0)
            puzzle_idx += 1
        jobs.append((spec, sample))

    os.makedirs(OUT, exist_ok=True)
    print(f"running {len(jobs)} mutants with {args.workers} workers...", flush=True)
    t0 = time.time()
    results = []
    with multiprocessing.Pool(args.workers) as pool:
        for i, r in enumerate(pool.starmap(run_mutant, jobs, chunksize=1)):
            results.append(r)
            print(f"[{i + 1}/{len(jobs)}] {r['id']:32s} {r['classification']:10s} {r['seconds']:6.1f}s", flush=True)
    total = time.time() - t0
    print(f"done in {total:.1f}s", flush=True)

    summary = summarize(results)
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump({"seed": SEED, "target_per_operator": TARGET_PER_OP, "candidates": avail,
                   "generated_seconds": round(total, 1), "mutants": results, "summary": summary}, f, indent=1)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
