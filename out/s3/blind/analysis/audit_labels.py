"""Labels-lens audit of the S3 blind set (helper, not frozen; writes out/s3/blind/analysis/)."""
import collections, json, os, sys

ROOT = "/Users/dave/Jane_Street_Reverse_ASIC"
OUT = os.path.join(ROOT, "out/s3/blind/analysis")
KINDS = ["shift_register", "counter", "lfsr_crc", "synchronizer"]

RUNS = {
 "tt09__tt_um_pwm_top": "blind-tt09__tt_um_pwm_top-20260923T065352Z-c8f61bba8b4e.json",
 "ttsky26c__tt_um_joonatanalanampa_cordic": "blind-ttsky26c__tt_um_joonatanalanampa_cordic-20260923T065543Z-90e4754651b4.json",
 "tt05__tt_um_toivoh_synth": "blind-tt05__tt_um_toivoh_synth-20260923T065720Z-7726a13a515d.json",
 "ttsky25a__tt_um_td4": "blind-ttsky25a__tt_um_td4-20260923T070128Z-4b16b78fd8be.json",
 "tt03p5__tt_um_Reloj_top": "blind-tt03p5__tt_um_Reloj_top-20260923T070322Z-a821516b2a2a.json",
 "tt03p5__tt_um_thorkn_vgaclock": "blind-tt03p5__tt_um_thorkn_vgaclock-20260923T071042Z-606b627a02fa.json",
 "tt07__tt_um_toivoh_basilisc_2816": "blind-tt07__tt_um_toivoh_basilisc_2816-20260923T071314Z-ec77d9db88ef.json",
 "ttsky25a__tt_um_sjsu_vga_music": "blind-ttsky25a__tt_um_sjsu_vga_music-20260923T071525Z-c3d1391efe1f.json",
 "tt07__tt_um_vzayakov_top": "blind-tt07__tt_um_vzayakov_top-20260923T071718Z-2c662362bf31.json",
 "tt05__tt_um_kskyou": "blind-tt05__tt_um_kskyou-20260923T072856Z-13ba663ae60c.json",
}
PUZZLE_RUN = "blind-puzzle-20260923T073045Z-8ea21ef84643.json"

labels = json.load(open(os.path.join(ROOT, "out/s3/blind/labels.json")))
by_id = {d["design_id"]: d for d in labels["designs"]}

sys.path.insert(0, ROOT)
from tools.s3 import score as S  # frozen; read only

def load_truth(did):
    return json.load(open(os.path.join(ROOT, f"out/s3/truth_{did}.json")))

def reg_weakness(truth):
    """Per register: bit-level proof / simulation-check status from the truth's bits[].
    A bit with no `flop` carries a `note` instead and no proof/check: it is an RTL bit with no
    netlist flop, counted here as `no_flop` and NOT as evidence for or against the label."""
    out = {}
    for r in truth["registers"]:
        pc = collections.Counter(); cc = collections.Counter(); how = collections.Counter()
        combo = collections.Counter(); notes = collections.Counter(); no_flop = 0
        for b in r["bits"]:
            if b.get("flop") is None:
                no_flop += 1
                notes[b.get("note") or "(no note)"] += 1
                continue
            pr, ck = b.get("proof") or "(absent)", b.get("check") or "(absent)"
            pc[pr] += 1; cc[ck] += 1; how[b.get("how") or "(absent)"] += 1
            combo[f"check={ck},proof={pr}"] += 1
        out[r["name"]] = {"kind": r["kind"], "width": r.get("width"),
                          "bits": len(r["bits"]), "bits_with_flop": len(r["bits"]) - no_flop,
                          "bits_without_flop": no_flop, "notes": dict(notes),
                          "proof": dict(pc), "check": dict(cc), "how": dict(how), "combo": dict(combo),
                          "alt_kinds": r.get("alt_kinds") or []}
    return out

designs = []
for did, fn in RUNS.items():
    L = by_id[did]
    T = load_truth(did)
    meta = T["meta"]
    rw = reg_weakness(T)
    tr = S.Truth(T)                       # the scorer's own view: universe, denominators, units
    scored_by_kind = {c: sorted(tr.denominators(c)) for c in KINDS}
    excused_by_kind = {c: sorted(tr.excused(c)) for c in KINDS}
    chain_units = sorted(u["name"] for u in tr.units if u["chain"])
    # weak = a scored structure-kind register with any bit not z3-proven or not simulation-matching
    weak = {}
    for c in KINDS:
        for n in scored_by_kind[c]:
            w = rw.get(n)
            if not w:
                continue
            unproven = sum(v for k, v in w["proof"].items() if k != "proven")
            unmatched = sum(v for k, v in w["check"].items() if k != "match")
            if unproven or unmatched or w["bits_without_flop"]:
                weak[n] = {"kind": c, "bits": w["bits"], "bits_with_flop": w["bits_with_flop"],
                           "bits_without_flop": w["bits_without_flop"], "notes": w["notes"],
                           "unproven_bits": unproven, "mismatching_bits": unmatched,
                           "proof": w["proof"], "check": w["check"], "combo": w["combo"]}
    # all registers (any kind) touched by an unproven bit, for context
    weak_any = {n: w for n, w in rw.items()
                if sum(v for k, v in w["proof"].items() if k != "proven")
                or sum(v for k, v in w["check"].items() if k != "match")
                or w["bits_without_flop"]}
    units = [{"name": u["name"], "kind": u["kind"], "rules": u.get("rules") or [],
              "registers": u["registers"], "flops": len(u.get("flops") or []),
              "chain": u["name"] in chain_units} for u in T.get("units") or []]
    run = json.load(open(os.path.join(ROOT, "out/s3/runs", fn)))
    evs = []
    for e in run["evaluations"]:
        sc = e["score"]
        rec = {"label": e["label"], "per_kind": {}}
        for c in KINDS:
            a = sc["classes"]["all"]["registers"]["strict"]["per_kind"][c]
            v = sc["classes"]["verified"]["registers"]["strict"]["per_kind"][c]
            al = sc["classes"]["all"]["registers"]["lenient"]["per_kind"][c]
            rec["per_kind"][c] = {
                "registers": a["registers"], "structures": a["structures"],
                "found": a["found"]["registers_found"], "exact": a["exact"]["registers_found"],
                "struct_found": a["found"]["structures_matched"],
                "verified_found": v["found"]["registers_found"],
                "verified_structures": v["structures"],
                "lenient_registers": al["registers"], "lenient_found": al["found"]["registers_found"]}
        rec["structures"] = sc["headline"]["structures"]
        rec["verified"] = sc["headline"]["verified"]
        evs.append(rec)
    designs.append({
        "id": L["id"], "design_id": did, "macro": L["macro"], "replaces": L["replaces"],
        "source": meta["source"], "shuttle": L["id"].split("/")[0],
        "layout_format": L["layout_format"],
        "counts": {"registers": L["registers"], "units": L["units"],
                   "netlist_flops": L["netlist_flops"], "netlist_flops_labelled": L["netlist_flops_labelled"],
                   "shadow_flops": L["shadow_flops"], "unmapped_flops": L["unmapped_flops"],
                   "rtl_flop_bits": L["rtl_flop_bits"], "latches": L["latches"],
                   "opaque_sequential_cells": L["opaque_sequential_cells"]},
        "rtl_bits": meta["counts"].get("rtl_bits"),
        "registers_by_kind": L["registers_by_kind"],
        "structure_registers": L["structure_registers"],
        "other_registers": L["other_registers"],
        "scorer_view": {"universe_flops": len(tr.universe),
                        "registers_with_flops": len(tr.scored),
                        "registers_without_flops": len(tr.no_flop),
                        "registers_without_flops_names": sorted(tr.no_flop),
                        "scored_by_kind": {c: len(scored_by_kind[c]) for c in KINDS},
                        "excused_by_kind": {c: len(excused_by_kind[c]) for c in KINDS},
                        "excused_registers": {c: excused_by_kind[c] for c in KINDS if excused_by_kind[c]},
                        "chain_units": chain_units,
                        "bad_units": tr.bad_units,
                        "check_truth_problems": len(tr.problems)},
        "meta_registers_without_primary_flop": meta.get("registers_without_primary_flop"),
        "meta_register_names_sharing_a_flop": meta.get("register_names_sharing_a_flop"),
        "meta_removed_rtl_registers": meta.get("removed_rtl_registers"),
        "meta_undriven_rtl_outputs": meta.get("undriven_rtl_outputs"),
        "meta_fsm_recoding": list((meta.get("fsm_recoding") or {}).get("registers", {}).keys()),
        "proof": {"complete": L["proof_complete"], "summary": L["proof"],
                  "incomplete": L["proof_incomplete"], "counts": L["proof_counts"],
                  "outputs_not_proven": meta["proof"].get("outputs_not_proven"),
                  "invariants_not_proven": meta["proof"].get("invariants_not_proven"),
                  "outputs": meta["proof"].get("outputs"),
                  "invariants": meta["proof"].get("invariants"),
                  "outputs_unspecified_in_rtl": meta["proof"].get("outputs_unspecified_in_rtl"),
                  "spurious_sat": meta["proof"].get("spurious_sat"),
                  "rlimit_per_check": meta["proof"].get("rlimit_per_check")},
        "functional_check": {"match": L["functional_check"]["match"],
                             "mismatch": L["functional_check"]["mismatch"],
                             "unchecked": L["functional_check"]["unchecked"],
                             "flops_checked": L["functional_check"]["flops_checked"],
                             "outputs_match": L["functional_check"]["outputs_match"],
                             "outputs_mismatch": L["functional_check"]["outputs_mismatch"],
                             "patterns": meta["functional_check"].get("patterns"),
                             "exercised": meta["functional_check"].get("exercised")},
        "join": L["join"],
        "anonymisation": L["anonymisation"],
        "units": units,
        "weak_structure_registers": weak,
        "weak_any_kind_registers": {n: {"kind": w["kind"], "bits": w["bits"],
                                        "bits_without_flop": w["bits_without_flop"],
                                        "proof": w["proof"], "check": w["check"],
                                        "combo": w["combo"]} for n, w in weak_any.items()},
        "all_registers": rw,
        "evaluations": evs,
    })

json.dump({"designs": designs}, open(os.path.join(OUT, "_raw.json"), "w"), indent=1, sort_keys=True)
print("wrote _raw.json;", len(designs), "designs")
