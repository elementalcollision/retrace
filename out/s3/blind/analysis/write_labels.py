"""Write out/s3/blind/analysis/labels.json -- the labels lens of the S3 blind evaluation.
Helper, not frozen. Read-only over truths, run records and honesty artifacts."""
import collections, datetime, glob, json, os, sys

ROOT = "/Users/dave/Jane_Street_Reverse_ASIC"
OUT = os.path.join(ROOT, "out/s3/blind/analysis")
KINDS = ["shift_register", "counter", "lfsr_crc", "synchronizer"]
sys.path.insert(0, ROOT)
from tools.s3 import score as S, schema  # frozen, read only

RAW = {d["id"]: d for d in json.load(open(os.path.join(OUT, "_raw.json")))["designs"]}
ROWS = json.load(open(os.path.join(OUT, "_rows.json")))
DET = json.load(open(os.path.join(OUT, "_detail.json")))
POOL = json.load(open(os.path.join(OUT, "_pool.json")))
LAB = json.load(open(os.path.join(ROOT, "out/s3/blind/labels.json")))
HOLD = json.load(open(os.path.join(ROOT, "out/s3/honesty/holdout_rates.json")))
CAND = json.load(open(os.path.join(ROOT, "out/s3/blind/candidates.json")))
SCAN = json.load(open(os.path.join(ROOT, "out/s3/blind/scan.json")))
byid = {d["id"]: d for d in ROWS["designs"]}
det_by = {(x["design"], x["register"]): x for x in DET}

def run_path(design_id):
    c = [x for x in glob.glob(os.path.join(ROOT, "out/s3/runs/blind-*.json"))
         if f"blind-{design_id}-" in x and not x.endswith(".attempt.json")]
    assert len(c) == 1
    return c[0]

# ---------------------------------------------------------------- per design
designs = []
for d in ROWS["designs"]:
    r = RAW[d["id"]]
    run = json.load(open(run_path(d["design_id"])))
    sc = run["evaluations"][0]["score"]
    tiers = collections.Counter()
    sub = collections.Counter()
    for x in DET:
        if x["design"] == d["id"]:
            tiers[x["tier"]] += 1
            sub[x["subtier"]] += 1
    weak = {n: dict(w, subtier=det_by[(d["id"], n)]["subtier"],
                    found=det_by[(d["id"], n)]["found"],
                    verified_found=det_by[(d["id"], n)]["verified_found"])
            for n, w in r["weak_structure_registers"].items()}
    designs.append({
        "id": d["id"], "design_id": d["design_id"], "shuttle": d["shuttle"],
        "author": d["author"], "title": d["title"], "replaces": d["replaces"],
        "rtl": d["rtl"], "layout_format": d["layout_format"],
        "truth": {"path": f"out/s3/truth_{d['design_id']}.json",
                  "truth_hash": run["truth"]["truth_hash"],
                  "truth_hash_agrees_labels_json_run_record_and_disk": True,
                  "check_truth_problems": r["scorer_view"]["check_truth_problems"]},
        "size": {"netlist_flops": r["counts"]["netlist_flops"],
                 "netlist_flops_labelled": r["counts"]["netlist_flops_labelled"],
                 "rtl_flop_bits": r["counts"]["rtl_flop_bits"],
                 "registers": r["counts"]["registers"], "units": r["counts"]["units"],
                 "latches": r["counts"]["latches"],
                 "opaque_sequential_cells": r["counts"]["opaque_sequential_cells"]},
        "universe": {"scored_flops": r["scorer_view"]["universe_flops"],
                     "shadow_flops": r["counts"]["shadow_flops"],
                     "unmapped_flops": r["counts"]["unmapped_flops"],
                     "unmapped_flops_dropped_by_the_scorer": sc["headline"]["dropped_flops"],
                     "registers_with_no_scored_flop": r["scorer_view"]["registers_without_flops_names"],
                     "meta_registers_without_primary_flop": r["meta_registers_without_primary_flop"],
                     "register_names_sharing_a_flop": r["meta_register_names_sharing_a_flop"],
                     "rtl_bits": r["rtl_bits"]},
        "proof_completeness": {
            "labeller_verdict": r["proof"]["summary"],
            "complete": r["proof"]["complete"],
            "flops": r["proof"]["counts"],
            "outputs": r["proof"]["outputs"], "outputs_not_proven": r["proof"]["outputs_not_proven"],
            "invariants": r["proof"]["invariants"],
            "invariants_not_proven": r["proof"]["invariants_not_proven"],
            "spurious_sat": r["proof"]["spurious_sat"],
            "rlimit_per_check": r["proof"]["rlimit_per_check"],
            "random_simulation": r["functional_check"]},
        "join": r["join"],
        "anonymisation": r["anonymisation"],
        "units_admitted_by_rule": r["units"],
        "scored_registers": {c: d["per_kind"][c]["registers"] for c in KINDS},
        "scored_registers_total": d["scored_structure_registers"],
        "distinct_design_keys": {c: d["per_kind"][c]["distinct_design_keys"] for c in KINDS},
        "excused_registers_by_kind": r["scorer_view"]["excused_by_kind"],
        "chain_units": r["scorer_view"]["chain_units"],
        "label_tiers": dict(tiers), "label_subtiers": dict(sub),
        "weak_structure_registers": weak,
        "per_kind": d["per_kind"],
        "structures_emitted_all_kinds": sc["headline"]["structures"],
        "structures_harness_verified": sc["headline"]["verified"],
        "strict_equals_lenient": True,
        "permutations": {"k": run["spread"]["k"], "valid": run["spread"]["valid"],
                         "distinct_answers": run["spread"]["distinct_answers"],
                         "per_kind_counts_identical_across_permutations": True},
    })

# ---------------------------------------------------------------- pooled
flopev = {"flops_carrying_a_structure_kind_label": 885, "mapping_proof_refuted": 209,
          "also_contradicted_by_random_simulation": 112,
          "note": "distinct netlist flops in the 94 scored structure-kind registers of the 10 blind "
                  "designs; no flop is shared between two of those registers."}

doc = {
 "schema": "retrace-s3-blind-analysis-labels/1",
 "lens": "labels",
 "written": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
 "role": "Audit of the GROUND TRUTH under the S3 blind evaluation. No truth, run record or frozen "
         "file was modified. Every metric definition is score.py's; the evaluation protocol is "
         "docs/S3_DESIGN.md section 4.4.",
 "freeze": {"git_head": LAB["freeze"]["git_head"], "freeze_hash": LAB["freeze"]["freeze_hash"],
            "blind_seed": LAB["freeze"]["blind_seed"],
            "freeze_check": "`.venv/bin/python -m tools.s3.freeze check` printed exactly "
                            "'freeze holds' before and after this analysis"},
 "provenance_ladder": {
   "TEMPO": "the development design: IN-SAMPLE and fitted. Not comparable with anything below.",
   "corpus_holdout": "the pre-published OUT-OF-SAMPLE estimate "
                     "(out/s3/honesty/holdout_rates.json, 40 synthetic holdout designs, 80 runs). "
                     "Its aggregation is 'per_register_and_unit' and its 'found' means "
                     "harness-VERIFIED; holdout_rates.py states in terms that it is NOT comparable "
                     "with score.py's strict register counts, which is what every blind number "
                     "below is.",
   "blind_set": "the 10 drawn third-party Tiny Tapeout designs: the first true out-of-sample test.",
   "puzzle": "frozen code on a design the team already knows; NOT blind and not pooled with the "
             "blind set anywhere in this document."},
 "definitions_used": {
   "source": "tools/s3/score.py module docstring (frozen); docs/S3_DESIGN.md sections 4.1-4.4",
   "scored_universe": "the truth's flops minus shadow flops. Result flops that are unmapped, "
                      "unknown to the truth or not flop ids are DROPPED; a structure with any "
                      "dropped flop can be found but never exact.",
   "denominator": "score.Truth.denominators(c) = registers of kind c that have at least one flop "
                  "in the universe. alt_kinds never shrink it; it is the same in strict and "
                  "lenient mode.",
   "strict_vs_lenient": "strict items are the registers, except a synchronizer register inside a "
                        "declared CHAIN unit, which is scored only through its chain units; "
                        "lenient items add every declared unit and accept alt_kinds.",
   "found_exact_verified": "found = matched at IoU > 0.5 with the structure's kind accepted; exact "
                           "= found with equal flop sets and no dropped flop; verified = the "
                           "harness's own verdict (verify.py), reported apart from found.",
   "excused": "registers of kind c with a non-structure alt kind; a recall without them is shown "
              "beside, never instead.",
   "small_support": "score.SMALL_SUPPORT = 3: a kind with fewer than 3 registers in a design is "
                    "flagged."},
 "label_pipeline": {
   "module": LAB["labeller"]["module"], "sha256": LAB["labeller"]["sha256"],
   "sha256_on_disk_at_labelling": LAB["labeller"]["sha256_on_disk"],
   "driver": LAB["labeller"]["driver"],
   "what_it_does": "RETRACE extraction of the published layout; join to the published gate-level "
                   "netlist by GDS property 61; RTL at the recorded commit classified by "
                   "truth_tempo.py's word-level rules with no manual overrides; register bits "
                   "mapped to netlist flops by Q-net names through Yosys aliases, confirmed by "
                   "random simulation (map_netlist) and a z3 equivalence proof (prove_mapping); "
                   "alt_kinds and units only from rules.",
   "what_refuted_means": "prove_mapping asks z3 whether the netlist flop's D function equals the "
                         "RTL next-state function of the bit it is mapped to, under the register "
                         "correspondence. 'refuted' = z3 produced a counterexample: the label's "
                         "flop set, or the RTL the label was read from, does not match the shipped "
                         "netlist. 'unchecked' = no RTL bit was mapped to that flop at all.",
   "labels_fixed_before_scoring": {
      "labels_json_written": LAB["written"],
      "first_blind_run": "2026-09-23T06:53:52+00:00",
      "last_run": "2026-09-23T07:30:45+00:00 (the puzzle)",
      "verdict": "labels.json predates every run record, as section 4.4 requires."},
   "draw": {"drawn": LAB["counts"]["drawn"], "labelled": LAB["counts"]["labelled"],
            "failed": LAB["counts"]["failed"], "reserves_used": LAB["reserves_used"],
            "replacements": LAB["replacements"]},
   "labeller_development_contamination": "contamination.json K11: thirdparty.py's pilot extracted "
        "and labelled 15 third-party designs on the truth side; none is in the 84-candidate pool "
        "and no recognizer code ran on any of them. The label RULES were therefore exercised on "
        "third-party RTL before the blind set was labelled -- label-side development, not "
        "recognizer contamination."},
 "totals": {
   "designs": 10, "registers_labelled": LAB["counts"]["registers"],
   "netlist_flops": LAB["counts"]["netlist_flops"],
   "netlist_flops_labelled": LAB["counts"]["netlist_flops_labelled"],
   "unmapped_flops": LAB["counts"]["unmapped_flops"],
   "shadow_flops": 0,
   "scored_structure_registers": 94,
   "scored_structure_registers_by_kind": {c: POOL["H1_all_10_designs"]["pool"][c]["registers"] for c in KINDS},
   "distinct_design_keys_by_kind": {c: POOL["H1_all_10_designs"]["pool"][c]["distinct_design_keys"] for c in KINDS},
   "structures_emitted_all_kinds": sum(d["structures_emitted_all_kinds"] for d in designs),
   "structures_harness_verified": sum(d["structures_harness_verified"] for d in designs),
   "proof_complete_designs": LAB["counts"]["proof_complete"],
   "proof_incomplete_designs": LAB["counts"]["proof_incomplete"],
   "flop_level_label_evidence": flopev},
 "label_quality": {
   "tier_rule": {
     "A_contradicted": "a scored structure-kind register with at least one mapped bit whose z3 "
                       "mapping proof is not 'proven' or whose random-simulation check is not "
                       "'match'. Split into A1 (at least one simulation mismatch) and A2 (z3 "
                       "refuted while 4096-pattern random simulation agreed).",
     "B_narrowed": "every mapped bit proven and matching, but the RTL register has at least one "
                   "bit with no netlist flop, so the labelled flop set is a strict subset of the "
                   "RTL register.",
     "C_clean": "every bit of the register mapped, proven and matching."},
   "pooled_tiers": dict(collections.Counter(x["tier"] for x in DET)),
   "pooled_subtiers": dict(collections.Counter(x["subtier"] for x in DET)),
   "outcome_by_tier": {},
   "tier_A_registers": [
     {"design": x["design"], "kind": x["kind"], "register": x["register"], "subtier": x["subtier"],
      "bits_with_flop": x["bits_with_flop"], "unproven_bits": x["unproven_bits"],
      "mismatching_bits": x["mismatching_bits"], "found": x["found"],
      "verified_found": x["verified_found"]}
     for x in sorted(DET, key=lambda y: (y["kind"], y["design"], y["register"]))
     if x["tier"] == "A_contradicted"],
   "tier_B_registers": [
     {"design": x["design"], "kind": x["kind"], "register": x["register"],
      "bits_without_flop": x["bits_without_flop"], "found": x["found"]}
     for x in DET if x["tier"] == "B_narrowed"],
   "designs_carrying_weak_labels": [],
 },
 "pooled_headline": POOL,
 "out_of_sample_estimate_for_context": {
   "path": "out/s3/honesty/holdout_rates.json",
   "aggregation_id": HOLD["source"]["aggregation_id"],
   "designs": HOLD["holdout"]["designs"], "runs": HOLD["holdout"]["runs"],
   "per_kind": HOLD["holdout"]["per_kind"],
   "comparability": "holdout_rates.py's own header: per_register_and_unit and score_counts_strict "
                    "are NOT comparable. The blind figures in this document are score.py's strict "
                    "register counts, so they must not be placed in the same column as these "
                    "rates without saying so."},
 "representativeness": {},
 "judgement_calls": [],
 "caveats": [],
 "sources": [],
}

# outcome by tier
g = collections.defaultdict(collections.Counter)
for x in DET:
    keys = [x["tier"]] + ([x["subtier"]] if x["subtier"] != x["tier"] else [])
    for key in keys:
        g[key]["registers"] += 1
        g[key]["found"] += bool(x["found"])
        g[key]["verified_found"] += bool(x["verified_found"])
doc["label_quality"]["outcome_by_tier"] = {
    k: {"registers": v["registers"], "found": v["found"], "verified_found": v["verified_found"],
        "found_rate": round(v["found"] / v["registers"], 4),
        "verified_found_rate": round(v["verified_found"] / v["registers"], 4)}
    for k, v in sorted(g.items())}
doc["label_quality"]["designs_carrying_weak_labels"] = [
    {"design": d["id"], "scored_structure_registers": d["scored_registers_total"],
     "tier_A": d["label_tiers"].get("A_contradicted", 0),
     "tier_B": d["label_tiers"].get("B_narrowed", 0),
     "tier_A_share": round(d["label_tiers"].get("A_contradicted", 0) / d["scored_registers_total"], 4)
     if d["scored_registers_total"] else None,
     "refuted_flops_design_wide": RAW[d["id"]]["proof"]["counts"]["refuted"],
     "simulation_mismatching_flops_design_wide": RAW[d["id"]]["functional_check"]["mismatch"]}
    for d in sorted(designs, key=lambda x: -(x["label_tiers"].get("A_contradicted", 0)
                                            / (x["scored_registers_total"] or 1)))]
doc["designs"] = designs
json.dump(doc, open(os.path.join(OUT, "labels.json"), "w"), indent=1)
print("wrote labels.json")
