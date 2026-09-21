"""Calibrate the round-trip synthesis recipe on the warm-up (ground truth: 01_netlist.v).

    python -m tools.roundtrip.calib [--out out/roundtrip/calib/sweep] [--only NAME ...]

Runs every attempt in ATTEMPTS on upstream/warmup/00_source.v (top adder_demo) and compares
the result with upstream/warmup/01_netlist.v through tools.roundtrip.compare. An attempt is
either a synth.py recipe plus overrides run with one Yosys build, or ("native") LibreLane's
own synthesize.py run inside a LibreLane image (tools.roundtrip.librelane_ref). Writes
<out>/<attempt>/{netlist.v,compare.json,...}, <out>/attempts.json and <out>/attempts.tsv
(one row per attempt: logic-cell histogram distance, per-instance distances, isomorphism
after clock-buffer collapse, name-level identity).

Yosys builds: y069 = oss-cad-suite 0.69 (local), y066 = LibreLane 3.1.0.dev3 image,
y062 = LibreLane 3.0.14 image.
"""

import argparse
import json
import os
import sys

from tools.roundtrip import compare, librelane_ref, synth

SRC = "upstream/warmup/00_source.v"
REF = "upstream/warmup/01_netlist.v"
TOP = "adder_demo"
YOSYS = {"y069": "oss", "y066": "ll31dev3", "y062": "ll3014"}
STRATEGIES = ["AREA 0", "AREA 1", "AREA 2", "AREA 3", "DELAY 0", "DELAY 1", "DELAY 2", "DELAY 3", "DELAY 4"]


def _attempts():
    A = []

    def add(name, recipe, sets=(), y="y069", native=None):
        A.append({"name": f"{len(A) + 1:02d}_{name}_{y}", "recipe": recipe, "set": list(sets),
                  "yosys": YOSYS[y], "native": native})

    for y in ("y069", "y066", "y062"):
        add("flatten_area0", "ll30", y=y)
        add("deferred_area0", "ll30_deferred", y=y)
        for s in STRATEGIES:
            add(f"keep_{s.replace(' ', '').lower()}", "ll30_keep", [f"strategy={s}"], y)
        add("keep_area0_nosort", "ll30_keep", ["no_sort=1"], y)
        add("keep_ll31script", "ll31_keep", y=y)
        add("keep_legacy_rf_rw", "ll30_keep", ["legacy_refactor=1", "legacy_rewrite=1"], y)
        add("keep_generic_abc_default", "ll30_keep", ["generic_abc=default"], y)
        add("keep_generic_abc_fast_as_script", "ll30_keep", ["generic_abc=fast_script"], y)
        add("keep_no_exclusions", "ll30_keep", ["exclude="], y)
        add("keep_drc_exclude_only", "ll30_keep", ["exclude=drc_exclude"], y)
    # sensitivity of the matching recipe to knobs the warm-up config might have set
    add("keep_clock5ns", "ll30_keep", ["clock_period=5"], "y062")
    add("keep_clock25ns", "ll30_keep", ["clock_period=25"], "y062")
    add("keep_load5fF", "ll30_keep", ["output_cap=5"], "y062")
    add("keep_abc_dff", "ll30_keep", ["abc_dff=1"], "y062")
    add("keep_no_tie_undefined", "ll30_keep", ["tie_undefined="], "y062")
    # LibreLane's own synthesize.py in its images (cross-checks the synth.py transcription)
    add("native_keep_area0", "ll30_keep", y="y062", native="ghcr.io/librelane/librelane:3.0.14")
    add("native_flatten_area0", "ll30", y="y062", native="ghcr.io/librelane/librelane:3.0.14")
    add("native_keep_area0", "ll31_keep", y="y066", native="ghcr.io/librelane/librelane:3.1.0.dev3")
    return A


ATTEMPTS = _attempts()


def run_attempt(att, out):
    d = os.path.join(out, att["name"])
    recipe = synth.with_overrides(synth.RECIPES[att["recipe"]], att["set"])
    row = {k: att[k] for k in ("name", "recipe", "set", "yosys", "native")}
    try:
        if att["native"]:
            librelane_ref.run([SRC], TOP, recipe, d, att["native"])
        else:
            synth.run([SRC], TOP, recipe, d, yosys=att["yosys"], name=att["recipe"])
    except Exception as e:  # record failures as attempts too
        row["error"] = str(e)
        return row
    res = compare.compare(os.path.join(d, "netlist.v"), TOP, REF, TOP)
    with open(os.path.join(d, "compare.json"), "w") as f:
        json.dump(res, f, indent=1)
    per = {}
    for inst in sorted(set(res["ours_per_instance"]) | set(res["ref_per_instance"])):
        per[inst] = compare.distance(res["ours_per_instance"].get(inst, {}), res["ref_per_instance"].get(inst, {}))[0]
    row.update(
        distance=res["distance"],
        per_instance_distance=per,
        diff=res["diff_ours_minus_ref"],
        logic_cells=res["ours"]["logic"]["count"],
        logic_area=res["ours"]["logic"]["area"],
        isomorphic=res["isomorphic"],
        names_identical=res["names"]["identical"],
    )
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="out/roundtrip/calib/sweep")
    ap.add_argument("--only", nargs="*", help="attempt names (default: all)")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    rows = []
    for att in ATTEMPTS:
        if a.only and att["name"] not in a.only:
            continue
        row = run_attempt(att, a.out)
        rows.append(row)
        print(
            f"{row['name']:42s} dist={row.get('distance', 'ERR')!s:>3} iso={row.get('isomorphic')!s:5} "
            f"names={row.get('names_identical')!s:5} per={row.get('per_instance_distance', row.get('error'))}",
            flush=True,
        )
    ref = compare.summarize(compare.counts(compare.load_module(REF, TOP)))
    with open(os.path.join(a.out, "attempts.json"), "w") as f:
        json.dump({"reference": REF, "reference_histogram": ref, "attempts": rows}, f, indent=1)
    cols = ["name", "recipe", "set", "yosys", "native", "distance", "add0", "cmp0", "sr_a", "sr_b",
            "logic_cells", "logic_area", "isomorphic", "names_identical"]
    with open(os.path.join(a.out, "attempts.tsv"), "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            p = r.get("per_instance_distance", {})
            vals = dict(r, set=";".join(r["set"]), native=r["native"] or "", distance=r.get("distance", "ERR"),
                        **{k: p.get(k, "") for k in ("add0", "cmp0", "sr_a", "sr_b")})
            f.write("\t".join(str(vals.get(c, "")) for c in cols) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
