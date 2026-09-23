"""Compare xcheck.json (independent recomputation) with numbers.json (the canonical agent's output),
figure by figure. Run after xcheck.py:  .venv/bin/python -B out/s3/replication/analysis/xcheck_compare.py
Writes out/s3/replication/analysis/xcheck_compare.json."""
import sys

sys.dont_write_bytecode = True
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
os.chdir(ROOT)
X = json.load(open("out/s3/replication/analysis/xcheck.json"))
N = json.load(open("out/s3/replication/analysis/numbers.json"))
TOL = 1e-12
rows = []


def cmp(name, mine, canon, tol=TOL):
    if isinstance(mine, (list, tuple)) and isinstance(canon, (list, tuple)):
        ok = len(mine) == len(canon) and all(
            (abs(a - b) <= tol if isinstance(a, float) or isinstance(b, float) else a == b) for a, b in zip(mine, canon))
    elif isinstance(mine, float) or isinstance(canon, float):
        ok = mine is not None and canon is not None and abs(mine - canon) <= tol
    else:
        ok = mine == canon
    rows.append({"figure": name, "independent": mine, "canonical": canon, "agree": ok})


def ci(b):
    return [b["lo"], b["hi"]]


def outcome_block(label, mine, nb, pooled_key_strat="bootstrap_95_stratified"):
    for s in ("R", "B1"):
        cmp(f"{label} {s} num/den", [mine[s]["x"], mine[s]["n"]], [nb[s]["num"], nb[s]["den"]])
        cmp(f"{label} {s} rate", mine[s]["rate"], nb[s]["rate"])
        cmp(f"{label} {s} bootstrap 95%", mine["bootstrap"][s]["ci"], ci(nb[s]["bootstrap_95"]))
        cmp(f"{label} {s} designs_with_registers", mine["designs_with_registers"][s], nb[s]["designs_with_registers"])
    cmp(f"{label} R-B1 difference", mine["R_minus_B1"], nb["R_minus_B1"]["difference"])
    cmp(f"{label} R-B1 bootstrap 95% (my scheme: one generator, R matrix drawn first)",
        mine["bootstrap"]["R_minus_B1"]["ci"], ci(nb["R_minus_B1"]["bootstrap_95"]))
    cmp(f"{label} R-B1 bootstrap 95% (B1 matrix drawn first, as canonical documents)",
        mine["bootstrap_B1_first_diff"]["ci"], ci(nb["R_minus_B1"]["bootstrap_95"]))
    p = nb["pooled_B1_plus_R"]
    cmp(f"{label} pooled num/den", [mine["pooled"]["x"], mine["pooled"]["n"]], [p["num"], p["den"]])
    cmp(f"{label} pooled rate", mine["pooled"]["rate"], p["rate"])
    cmp(f"{label} pooled bootstrap, 20 designs as one set", mine["bootstrap"]["pooled_one_set"]["ci"],
        ci(p["bootstrap_95_sensitivity_20_designs_as_one_set"]))
    cmp(f"{label} pooled bootstrap, stratified (B1 then R)", mine["bootstrap"]["pooled_stratified_B1_then_R"]["ci"],
        ci(p[pooled_key_strat]))
    ic = nb["independence_assuming_comparison"]
    cmp(f"{label} Fisher two-sided p", mine["fisher_p_R_vs_B1"], ic["fisher_exact_two_sided_p_R_vs_B1"], 1e-9)
    for s, k in (("R", "clopper_pearson_95_R"), ("B1", "clopper_pearson_95_B1"), ("pooled", "clopper_pearson_95_pooled")):
        cmp(f"{label} Clopper-Pearson {s}", mine["clopper_pearson"][s], ic[k], 1e-9)


# A. precondition
A = N["A_pooling_precondition"]
cmp("A precondition holds for all 10", X["A_pooling_precondition"]["holds_for_all"], A["holds_for_all_10"])
cmp("A designs excluded from pooling", X["designs"]["excluded"], A["R_designs_with_any_mismatch"])
cmp("A 12 OUT_OF_SAMPLE_SOURCES names", sorted(X["sources"]["OUT_OF_SAMPLE_SOURCES"]),
    sorted(os.path.basename(p) for p in A["out_of_sample_sources"]))
cmp("A 12 hashes equal current tree", X["A_pooling_precondition"]["oos12_equal_current_tree"], A["also_equal_to_the_current_tree"])
for mine, can in zip(X["A_pooling_precondition"]["per_R_record"], A["per_R_record"]):
    assert mine["design"] == can["design"]
    cmp(f"A {mine['design']} oos12 mismatches", mine["oos12_mismatches"], can["code_12_mismatches"])
    cmp(f"A {mine['design']} recognizer_sources mismatches", mine["recognizer_sources_mismatches"], can["recognizer_sources_mismatches"])
    cmp(f"A {mine['design']} evaluations with recognizer_sources mismatch", mine["evaluations_with_recognizer_sources_mismatch"],
        len(can["evaluations_whose_recognizer_sources_differ"]))
    cmp(f"A {mine['design']} other code files differing from B1 (informational)", mine["other_code_files_differing_from_B1"],
        can["non_precondition_code_files_that_differ_from_B1_informational"])

# B. primary
outcome_block("B primary", X["B_primary_counter_verified_found"], N["B_primary"])
cmp("B verdict", X["B_primary_counter_verified_found"]["verdict"], N["B_primary"]["verdict"]["word"])
for s in ("R", "B1"):
    mine = {r["design"]: r["counter"] for r in X["per_design"][s]}
    for r in N["B_primary"][f"per_design_{s}"]:
        m = mine[r["design"]]
        cmp(f"B per-design {s} {r['design']} (registers, verified_found, found)",
            [m["registers"], m["verified_found"], m["found"]], [r["den"], r["verified_found"], r["found"]])
# C. counter all-structures found
outcome_block("C counter all-structures found", X["C_counter_all_structures_found"],
              N["C_secondary"]["counter_all_structures_found_recall"])
# per kind, R and B1
for s in ("R", "B1"):
    for mode in ("strict", "lenient"):
        for k, mv in X["E_per_kind"][s][mode].items():
            a = N["C_secondary"]["per_kind"][s][k][f"all/{mode}"]
            v = N["C_secondary"]["per_kind"][s][k][f"verified/{mode}"]
            cmp(f"E per-kind {s} {k} {mode}: registers, structures, found, exact",
                [mv["registers"], mv["structures"], mv["found"], mv["exact"]],
                [a["registers"], a["structures"], a["found"]["num"], a["exact"]["num"]])
            cmp(f"E per-kind {s} {k} {mode}: verified structures, verified found, verified exact",
                [mv["verified_structures"], mv["verified_found"], mv["verified_exact"]],
                [v["structures"], v["found"]["num"], v["exact"]["num"]])
            cmp(f"E per-kind {s} {k} {mode}: designs with registers", mv["designs_with_registers"], a["designs_with_any"])
# grouping
for s in ("R", "B1"):
    g, cg = X["F_grouping"][s], N["C_secondary"]["grouping"][s]["all_flops"]
    cmp(f"F grouping {s} AMI mean/median/min/max", [g["ami_mean"], g["ami_median"], g["ami_min"], g["ami_max"]],
        [cg["ami"]["mean"], cg["ami"]["median"], cg["ami"]["min"], cg["ami"]["max"]])
    cmp(f"F grouping {s} singletons AMI mean", g["singletons_ami_mean"], cg["baseline_singletons_ami"]["mean"])
    cmp(f"F grouping {s} random-block AMI mean", g["random_blocks_ami_mean"], cg["baseline_random_blocks_ami"]["mean"])
    cmp(f"F grouping {s} chance floor (higher baseline)", g["chance_floor"], cg["higher_baseline_ami_mean"])
    cmp(f"F grouping {s} AMI mean minus floor", g["ami_mean_minus_floor"], cg["ami_mean_minus_higher_baseline"])
if "per_design_R" in N["C_secondary"]:
    for r in N["C_secondary"]["per_design_R"]["rows"]:
        cmp(f"F per-design AMI {r['design']}", X["F_grouping"]["R"]["per_design"][r["design"]], r["ami"])
# tiers
TMAP = {"C_clean": "C", "B_narrowed": "B", "A1_simulation_mismatch": "A1", "A2_z3_refuted_only": "A2"}
for s in ("R", "B1"):
    for part in ("all_kinds", "counter"):
        mt, ct = X["G_tiers"][s][part], N["D_label_quality"][s][part]["subtiers"]
        cmp(f"G tiers {s} {part} A1/A2/B/C",
            [mt["A1"], mt["A2"], mt["B"], mt["C"]],
            [ct.get("A1_simulation_mismatch", 0), ct.get("A2_z3_refuted_only", 0), ct.get("B_narrowed", 0), ct.get("C_clean", 0)])
    fl, cf = X["G_tiers"][s]["flop_level"], N["D_label_quality"][s]["flop_level_total"]
    cmp(f"G flop level {s} (flops, refuted, refuted+mismatch)",
        [fl["structure_kind_flops"], fl["refuted"], fl["refuted_and_mismatching"]],
        [cf["flops"], cf["mapping_proof_refuted"], cf["refuted_and_simulation_mismatch"]])
# found / verified-found by tier, R, all kinds
mt = X["G_tiers"]["R"]["by_tier_found"]
ct = N["D_label_quality"]["R"]["all_kinds"]["outcome_by_tier"]
for t, ck in (("A1", "A1_simulation_mismatch"), ("A2", "A2_z3_refuted_only"), ("B", "B_narrowed"), ("C", "C_clean")):
    m = mt.get(t, {"registers": 0, "found": 0, "verified_found": 0})
    c = ct.get(ck, {"registers": 0, "found": 0, "verified_found": 0})
    cmp(f"G R tier {t}: registers, found, verified found", [m["registers"], m["found"], m["verified_found"]],
        [c["registers"], c["found"], c["verified_found"]])
# per-register tier rows, R
mine = {(r["design"], r["kind"], r["register"]): r for r in X["tier_rows_R"]}
canr = {(r["design"], r["kind"], r["register"]): r for r in N["D_label_quality"]["R"]["registers"]}
cmp("G R per-register row keys", sorted(map(list, mine)), sorted(map(list, canr)))
bad = [k for k in mine if k in canr and (mine[k]["tier"] != TMAP[canr[k]["subtier"]] or mine[k]["found"] != canr[k]["found"]
                                         or mine[k]["verified_found"] != canr[k]["verified_found"])]
cmp("G R per-register tier/found/verified_found disagreements", bad, [])
# per-design tier counts
for d, tc in N["D_label_quality"]["R"]["per_design_tier_counts"].items():
    m = X["G_tiers"]["R"]["per_design"][d]
    cmp(f"G per-design tiers {d}", {"A": m.get("A1", 0) + m.get("A2", 0), "B": m.get("B", 0), "C": m.get("C", 0)},
        {"A": tc.get("A_contradicted", 0), "B": tc.get("B_narrowed", 0), "C": tc.get("C_clean", 0)})
# Tier A removed
outcome_block("D primary, Tier A removed", X["D_primary_tierA_removed"], N["D_label_quality"]["primary_with_tier_A_removed"])
for s in ("R", "B1"):
    c = N["D_label_quality"]["counter_all_structures_found_with_tier_A_removed"][s]
    cmp(f"D counter found, Tier A removed, {s}", [X["D2_counter_found_tierA_removed"][s]["x"], X["D2_counter_found_tierA_removed"][s]["n"]],
        [c["num"], c["den"]])
    # all kinds, Tier A removed
    by = X["G_tiers"][s]["by_tier_found"]
    keep = [by.get(t, {"registers": 0, "found": 0, "verified_found": 0}) for t in ("B", "C")]
    c = N["D_label_quality"]["all_kinds_tier_A_removed"][s]
    cmp(f"D all kinds, Tier A removed, {s}: registers, found, verified found",
        [sum(k["registers"] for k in keep), sum(k["found"] for k in keep), sum(k["verified_found"] for k in keep)],
        [c["registers"], c["found"]["num"], c["verified_found"]["num"]])

json.dump(rows, open("out/s3/replication/analysis/xcheck_compare.json", "w"), indent=1)
dis = [r for r in rows if not r["agree"]]
print(f"{len(rows)} figures compared, {len(rows) - len(dis)} agree, {len(dis)} disagree")
for r in dis:
    print("DISAGREE:", r["figure"], "| independent:", r["independent"], "| canonical:", r["canonical"])
