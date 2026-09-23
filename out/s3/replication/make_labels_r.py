"""Replication (Freeze 4) labeller: assemble out/s3/blind/labels.json, and out/s3/replication/labels.{json,log},
from the per-design out/s3/blind/label_<design_id>.json rows written by out/s3/blind/label_driver.py.

A copy of freeze 1's out/s3/blind/make_labels.py (same labels.json layout), adapted in three ways only:
  * the freeze is read from out/s3/FREEZE.json as it stands (Freeze 4); nothing is hard-coded;
  * replacements: a drawn design whose label run FAILED (label_<id>.fail.json, no label_<id>.json) gets a
    designs[] row with ok=false and the recorded error, and the next reserve, in draw order, that the pipeline
    DID label gets a row with "replaces": <that drawn id>; the same row goes in "replacements" and
    "reserves_used" is the number of reserves consumed (docs/S3_REPLICATION_PLAN.md, Labelling). A reserve
    the pipeline could not label either gets an ok=false row with "replaces" (it was used, and is spent) and is in
    "replacements" too; "replaced_by" maps each failed drawn id to the reserve actually labelled in its place;
  * extra per-row fields (a superset; no field of make_labels.py's row is dropped or renamed):
    proof_counts gains unknown / outputs_not_proven / invariants_not_proven, and "anon_check" holds
    out/s3/replication/verify_anon.py's re-open of the anonymised layout.
freeze.py reads only draw, designs[].id/design_id/replaces, replacements, reserves_used and freeze.freeze_hash.

Run from the repository root: .venv/bin/python -B out/s3/replication/make_labels_r.py
The log is NOT written to out/s3/blind/labels.log (freeze 1's committed log); it goes to out/s3/replication/.
"""
import datetime
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, ".")
from tools.s3 import freeze as fz, score, schema  # noqa: E402

OUT = "out/s3/blind"
REP = "out/s3/replication"
fr = fz.load()
d = fz.draw(fr)
blind, reserve = d["blind"], d["reserve"]


def label_path(ident):
    did = score.design_id(ident)
    ok = os.path.join(OUT, "label_%s.json" % did)
    fail = os.path.join(OUT, "label_%s.fail.json" % did)
    if os.path.exists(ok):
        return ok, True
    if os.path.exists(fail):
        return fail, False
    return None, None


def anon_check(did):
    r = subprocess.run([sys.executable, "-B", os.path.join(REP, "verify_anon.py"), did], capture_output=True, text=True)
    if r.returncode not in (0, 1) or not r.stdout.strip():
        return {"ok": False, "error": (r.stderr or r.stdout)[-800:]}
    return json.loads(r.stdout.strip().splitlines()[-1])


def good_row(n, r, replaces):
    did = r["design_id"]
    fc = r["functional_check"]
    t = json.load(open(r["truth"]))
    pr = t["meta"]["proof"]
    ln = lambda k: len(pr.get(k) or [])  # noqa: E731
    return {
        "n": n,
        "id": r["id"],
        "design_id": did,
        "macro": r["macro"],
        "ok": r["ok"],
        "replaces": replaces,
        "gds": r["gds"],
        "gds_bytes": r["gds_bytes"],
        "truth": r["truth"],
        "truth_hash": r["truth_hash"],
        "check_truth": r["check_truth"],
        "registers": r["registers"],
        "units": r["units"],
        "netlist_flops": r["netlist_flops"],
        "netlist_flops_labelled": r["netlist_flops_labelled"],
        "shadow_flops": r["shadow_flops"],
        "unmapped_flops": r["unmapped_flops"],
        "rtl_flop_bits": r["rtl_flop_bits"],
        "latches": r["latches"],
        "opaque_sequential_cells": r["opaque_sequential_cells"],
        "registers_by_kind": r["registers_by_kind"],
        "structure_registers": r["structure_registers"],
        "other_registers": r["other_registers"],
        "proof_complete": r["proof"] == "complete",
        "proof": r["proof"],
        "proof_incomplete": r["proof_incomplete"],
        "proof_counts": {"proven": pr.get("proven"), "refuted": ln("refuted"),
                         "unchecked": ln("unchecked"), "spurious_sat": pr.get("spurious_sat"),
                         "unknown": ln("unknown"), "outputs_not_proven": ln("outputs_not_proven"),
                         "invariants_not_proven": ln("invariants_not_proven")},
        "functional_check": {"flops_checked": fc["flops_checked"], "match": fc["match"],
                             "mismatch": len(fc["mismatch"]), "unchecked": len(fc["unchecked"]),
                             "outputs_match": fc.get("outputs_match"),
                             "outputs_mismatch": len(fc.get("outputs_mismatch") or [])},
        "anonymisation": r["anonymisation"],
        "anon_check": anon_check(did),
        "layout_format": r["layout_format"],
        "flat_cut_shapes_wrapped": r["flat_cut_shapes_wrapped"],
        "join": r["join"],
        "timings_s": r["timings_s"],
    }


def failed_row(n, r):
    row = {"n": n, "id": r["id"], "design_id": r["design_id"], "macro": r["macro"], "ok": False,
           "replaces": None, "error": r.get("error"), "label_record": label_path(r["id"])[0]}
    # what the failed run left behind: the pilot's own truth (if pilot got that far) and label_driver's
    # unchanged copy under out/s3/ (label_driver copies BEFORE it runs check_truth)
    for key, path in (("pilot_truth", os.path.join(OUT, "pilot", "truth_%s.json" % r["design_id"])),
                      ("truth_copy_left_on_disk", "out/s3/truth_%s.json" % r["design_id"])):
        if os.path.exists(path):
            t = json.load(open(path))
            row[key] = {"path": path, "truth_hash": schema.truth_hash(t), "check_truth": schema.check_truth(t)}
        else:
            row[key] = None
    return row


designs, replacements = [], []
replaced_by = {}   # drawn id -> the reserve that was labelled in its place
next_reserve = 0
problems = []
for i, ident in enumerate(blind, 1):
    p, ok = label_path(ident)
    if p is None:
        raise SystemExit("missing label record for drawn design %s" % ident)
    r = json.load(open(p))
    if ok:
        designs.append(good_row(i, r, None))
        continue
    row = failed_row(i, r)
    row["outcome"] = "not labelled (frozen pipeline failure); replaced"
    designs.append(row)
    # replacement: the next reserve in order the frozen pipeline labelled (a reserve that also failed is
    # recorded as worked on and consumed, and the one after it is tried)
    while True:
        if next_reserve >= len(reserve):
            problems.append("no reserve left to replace %s" % ident)
            break
        rid = reserve[next_reserve]
        next_reserve += 1
        rp, rok = label_path(rid)
        if rp is None:
            problems.append("reserve %s not labelled yet (replacing %s)" % (rid, ident))
            break
        rr = json.load(open(rp))
        if rok:
            row = good_row(i, rr, ident)
            row["reserve_rank"] = next_reserve
            row["outcome"] = "labelled: replaces %s" % ident
            designs.append(row)
            replacements.append(row)
            replaced_by[ident] = rid
            break
        fr_row = failed_row(i, rr)
        fr_row["replaces"] = ident
        fr_row["reserve_rank"] = next_reserve
        fr_row["outcome"] = ("not labelled (frozen pipeline failure) when tried as the replacement of %s; "
                             "the next reserve in order was then tried" % ident)
        designs.append(fr_row)
        replacements.append(fr_row)
if problems:
    raise SystemExit("; ".join(problems))

scored = [r for r in designs if r["ok"]]
doc = {
    "schema": "retrace-s3-blind-labels/1",
    "written": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "role": "LABELLER: ground truth for the S3 blind set. The recognizer never sees any of this.",
    "freeze": {"git_head": fr.get("git_head"), "freeze_hash": fr.get("freeze_hash"),
               "blind_seed": fr.get("blind_seed"),
               "candidates": fr.get("blind_candidates"), "draw": fr.get("draw")},
    "draw": {"blind": blind, "reserve": reserve},
    "labeller": {"module": "tools/s3/thirdparty.py",
                 "entry_points": ["pilot", "fetch_layout", "prepare_layout", "anonymise_layout"],
                 "sha256": (fr.get("code") or {}).get("tools/s3/thirdparty.py"),
                 "sha256_on_disk": hashlib.sha256(open("tools/s3/thirdparty.py", "rb").read()).hexdigest(),
                 "driver": "out/s3/blind/label_driver.py (helper, not frozen; freeze 1's, unchanged)",
                 "assembler": "out/s3/replication/make_labels_r.py (a copy of out/s3/blind/make_labels.py "
                              "adapted for replacements; helper, not frozen)"},
    "replacements": replacements,
    "reserves_used": next_reserve,
    "replaced_by": replaced_by,
    "evaluation_set": [r["id"] for r in designs if r["ok"]],
    "counts": {"drawn": len(blind), "labelled": len(scored),
               "failed": sum(1 for r in designs if not r["ok"]),
               "proof_complete": sum(1 for r in scored if r["proof_complete"]),
               "proof_incomplete": sum(1 for r in scored if not r["proof_complete"]),
               "registers": sum(r["registers"] for r in scored),
               "netlist_flops": sum(r["netlist_flops"] for r in scored),
               "netlist_flops_labelled": sum(r["netlist_flops_labelled"] for r in scored),
               "unmapped_flops": sum(r["unmapped_flops"] for r in scored),
               "structure_registers": {k: sum(r["structure_registers"][k] for r in scored)
                                       for k in schema.STRUCTURE_KINDS}},
    "designs": designs,
}
text = json.dumps(doc, indent=1) + "\n"
with open(os.path.join(OUT, "labels.json"), "w") as f:
    f.write(text)
with open(os.path.join(REP, "labels.json"), "w") as f:
    f.write(text)

log_lines = []
for row in designs:
    if not row["ok"]:
        log_lines.append("%2d %-46s ok=False%s error: %s | %s | truth copy left on disk: %s" % (
            row["n"], row["id"], (" replaces=%s" % row["replaces"]) if row["replaces"] else "", row["error"],
            row["outcome"], json.dumps(row["truth_copy_left_on_disk"])))
        continue
    sr, pc, an = row["structure_registers"], row["proof_counts"], row["anon_check"]
    log_lines.append(
        "%2d %-46s ok=%s%s registers=%-3d flops=%-4d labelled=%-4d shadow=%-2d unmapped=%-2d "
        "counter=%-2d shift_register=%-2d lfsr_crc=%-2d synchronizer=%-2d other=%s units=%d "
        "anon(props=%d labels_removed=%d labels_kept=%d; reopened: ref_props=%s labels_outside_pins=%s) "
        "truth_hash=%s proof_counts(proven=%s refuted=%d unknown=%d unchecked=%d outputs_not_proven=%d "
        "invariants_not_proven=%d) proof: %s" % (
            row["n"], row["id"], row["ok"], (" replaces=%s" % row["replaces"]) if row["replaces"] else "",
            row["registers"], row["netlist_flops"],
            row["netlist_flops_labelled"], row["shadow_flops"], row["unmapped_flops"],
            sr["counter"], sr["shift_register"], sr["lfsr_crc"], sr["synchronizer"],
            json.dumps(row["other_registers"], separators=(",", ":")), row["units"],
            row["anonymisation"]["properties_removed"], row["anonymisation"]["labels_removed"],
            row["anonymisation"]["labels_kept"], an.get("reference_properties"), an.get("top_labels_outside_tt_pins"),
            row["truth_hash"][:12], pc["proven"], pc["refuted"], pc["unknown"], pc["unchecked"],
            pc["outputs_not_proven"], pc["invariants_not_proven"], row["proof"]))

nrep = len([r for r in replacements if r["ok"]])
hdr = ["S3 replication (Freeze 4) blind set: labeller log (%s)" % doc["written"],
       "freeze git_head %s  freeze_hash %s  seed %s" % (fr.get("git_head"), fr.get("freeze_hash"), fr.get("blind_seed")),
       "draw: %d drawn, %d reserves listed; reserves used: %d%s" % (
           len(blind), len(reserve), next_reserve,
           " (every drawn design was labelled by the frozen pipeline)" if not next_reserve else
           " (%d replacement(s) labelled: %s)" % (nrep, json.dumps(replaced_by))),
       "evaluation set (the %d labelled designs): %s" % (len(doc["evaluation_set"]), ", ".join(doc["evaluation_set"])),
       ""]
c = doc["counts"]
tail = ["",
        "totals: %d designs labelled, %d registers, %d netlist flops (%d labelled, %d unmapped)"
        % (c["labelled"], c["registers"], c["netlist_flops"], c["netlist_flops_labelled"], c["unmapped_flops"]),
        "structure registers in the truth: %s (total %d)" % (json.dumps(c["structure_registers"]),
                                                              sum(c["structure_registers"].values())),
        "proof complete on %d of %d labelled designs; the other %d carry the labeller's proof line verbatim above"
        % (c["proof_complete"], c["labelled"], c["proof_incomplete"]),
        "anonymised layouts re-opened: %d of %d with 0 reference properties and 0 top-level labels outside TT_PINS"
        % (sum(1 for r in scored if r["anon_check"].get("ok")), len(scored))]
with open(os.path.join(REP, "labels.log"), "w") as f:
    f.write("\n".join(hdr + log_lines + tail) + "\n")
print("\n".join(hdr + log_lines + tail))
