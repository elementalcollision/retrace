"""Collect this round's reporting/provenance facts into out/s3/honesty/summary.json, the one
machine-readable artefact the lead's report and the change log can cite.

    .venv/bin/python out/s3/honesty/summarise.py [--out FILE]

It reads only artefacts produced earlier in this round (the two ablation files, the holdout rates,
the parameter coverage, the leakage logs) plus tools/s3 for the counts it states, and recomputes
nothing. Every number in it can be traced to the file it came from.

THE OUT-OF-SAMPLE BLOCK IS GATED (review[1] blocker of 2026-09-23). This file used to copy
holdout_rates.json's blocks in whole, so when the recognizer moved the summary went on publishing
shift_register 16/30 with "code_matches_tree": true and nothing anywhere said otherwise, while
score.py had already begun refusing the same numbers. The estimate now comes through
tools/s3/score.out_of_sample(), the one gate the harness and the pre-freeze checklist use: when
that gate refuses, this file records the refusal INSTEAD of the rates, exactly as score.py's report
does. It also writes its own `code_state` (the sha256 of every file of score.OUT_OF_SAMPLE_SOURCES
as it stands now), so a reader can tell whether the document in front of them still describes the
tree, and out/s3/honesty/oos_provenance.py checks that and the sibling artefacts, listing every
snapshot this summary supersedes. Regenerate after ANY tools/s3 edit; test/test_s3.py fails while
this file is stale.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import oos_provenance  # noqa: E402  (this directory)

from tools.s3 import freeze, score  # noqa: E402

ARMS = ("base", "cover_cap4", "p0_dominant", "dana_fixpoint", "jaccard_half", "no_transfer_split")
ARM_OF = {"cover_cap4": "C01", "p0_dominant": "C02", "dana_fixpoint": "C04", "jaccard_half": "C05",
          "no_transfer_split": "C06"}


def _read(name):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f) if name.endswith(".json") else f.read()


def _text(name):
    p = os.path.join(HERE, name)
    return open(p).read() if os.path.exists(p) else None


def ablations():
    t, c = _read("ablations_tempo.json"), _read("ablations_corpus_holdout.json")
    if not (t and c):
        return None
    rows = [r for r in c["rows"] if "error" not in r]
    out = {}
    for a in ARMS:
        tg = t["arms"][a]["grouping"]
        g = [r["arms"][a]["grouping"] for r in rows if a in r["arms"]]
        out[a] = {
            "change_log_entry": ARM_OF.get(a),
            "tempo": {k: tg[k] for k in ("ami", "ari", "exact_words", "truth_words_multi", "splits", "merges")},
            "tempo_headline": t["arms"][a].get("headline"),
            "tempo_counts": t["arms"][a].get("counts"),
            "corpus_holdout": {
                "runs": len(g),
                "ami_mean": round(statistics.fmean(x["ami"] for x in g), 4),
                "ari_mean": round(statistics.fmean(x["ari"] for x in g), 4),
                "exact_words": sum(x["exact_words"] or 0 for x in g),
                "truth_words_multi": sum(x["truth_words_multi"] or 0 for x in g)},
            "same_as_base_on_holdout": None,
        }
    b = out["base"]["corpus_holdout"]
    for a in ARMS:
        out[a]["same_as_base_on_holdout"] = out[a]["corpus_holdout"] == b
    return out


def leakage():
    out = {}
    for name, how in (("leakage_slow_suite.log", "test/test_s3.py::test_tempo_leakage with RETRACE_S3_SLOW=1"),
                      ("freeze_checklist.log", "python -m tools.s3.freeze checklist")):
        txt = _text(name)
        if txt is None:
            out[name] = {"how": how, "ran": False, "note": "not present"}
            continue
        m = re.search(r"verdict (\w+)", txt)
        out[name] = {"how": how, "ran": True,
                     "passed": bool(re.search(r"\b1 passed|checklist clear", txt)),
                     "failed": bool(re.search(r"\b\d+ failed|BLOCKS:", txt)),
                     "verdict": m.group(1) if m else None,
                     "tail": txt.strip().splitlines()[-25:]}
    return out


def code_drift():
    """Does the reference corpus evaluation still describe this tree, and did it move under this
    round's own runs? Several agents change tools/s3 in one session."""
    rates = _read("holdout_rates.json")
    now, prev = _read("ablations_corpus_holdout.json"), _read("ablations_corpus_holdout.prev.json")
    out = {
        "reference_evaluation": None if not rates else {
            "path": rates["source"]["path"], "code_sha256_16": rates["source"].get("code_sha256_16"),
            # answered, not left null: score.py's own gate decides it, and the answer is the one
            # thing a reader of this block needs (review[1] blocker, 2026-09-23)
            "matches_this_tree": score.out_of_sample_problem() is None,
            "refusal": score.out_of_sample_problem()},
        "recognizer_code_now": freeze.code_hashes(),
        # CORRECTED 2026-09-23: this note used to name out/s3/dev2/corpus_final.json as the source of
        # the published rates. It has not been since review[1] of 2026-09-22 (H03): the deriver's --run
        # produces out/s3/honesty/corpus_holdout_eval.json and derives from that, so the evaluation and
        # the code check cannot drift apart. The source is read from the artefact above, not asserted.
        "note": "the holdout rates score.py prints are derived from the evaluation named in "
                "reference_evaluation.path, of the recognizer AS IT WAS when that run was made. If any "
                "file of score.OUT_OF_SAMPLE_SOURCES has moved since, score.py refuses them and the "
                "evaluation must be re-run (out/s3/honesty/holdout_rates.py --run) before they are quoted.",
    }
    if now and prev:
        def agg(doc):
            rows = [r for r in doc["rows"] if "error" not in r]
            g = [r["arms"]["base"]["grouping"] for r in rows]
            per = {}
            for r in rows:
                for k, v in r["arms"]["base"]["counts"].items():
                    if not k.startswith("all/"):
                        continue
                    d = per.setdefault(k[4:], {"registers": 0, "found": 0, "exact": 0})
                    for f in d:
                        d[f] += v[f]
            return {"runs": len(rows),
                    "ami_mean": round(statistics.fmean(x["ami"] for x in g), 4),
                    "exact_words": sum(x["exact_words"] or 0 for x in g), "per_kind": per}
        out["corpus_holdout_under_this_rounds_own_runs"] = {
            "first_run": agg(prev), "second_run": agg(now),
            "same": agg(prev) == agg(now),
            "what_it_means": "the two runs of the SAME ablation, about ninety minutes apart in one session, "
                             "used different tools/s3 states because other agents were editing the recognizer. "
                             "The arms of one run stay comparable (they share a code state); the ABSOLUTE "
                             "figures do not carry across runs.",
            "code_first_run": (prev or {}).get("code"), "code_second_run": (now or {}).get("code")}
    t = _read("ablations_tempo.json")
    if t and now:
        tc, cc = t.get("code") or {}, now.get("code") or {}
        differ = sorted(k for k in set(tc) | set(cc) if tc.get(k) != cc.get(k))
        out["tempo_and_corpus_arms_share_a_code_state"] = not differ
        out["files_differing_between_the_tempo_and_corpus_ablation_runs"] = differ
        out["how_to_read_it"] = ("the arms WITHIN one ablation file share a code state and are comparable; the "
                                 "TEMPO file and the corpus file were produced minutes apart and, when the list "
                                 "above is non-empty, not on the same tree, so a TEMPO figure and a corpus "
                                 "figure must not be subtracted from each other")
    return out


def out_of_sample():
    """The out-of-sample estimate as this tree may quote it, or the refusal in its place.

    The rates come through tools/s3/score.out_of_sample(), NOT from a direct read of
    holdout_rates.json: that is the gate score.py's report and freeze.py's pre-freeze checklist
    already use, and a summary with a softer gate than the report is the review[1] blocker this
    answers. Whichever branch is taken, the block names the code state and the snapshots it
    supersedes, so nothing here can be read as current by accident."""
    doc, bad = score._load_out_of_sample()          # noqa: SLF001 -- the public pair, in one call
    sup = oos_provenance.superseded()
    common = {
        "gate": "tools/s3/score.py out_of_sample(): the document is quoted only while every file of "
                "score.OUT_OF_SAMPLE_SOURCES hashes as it did when the rates were derived, and only "
                "when it carries rates at all",
        "source_of_truth": oos_provenance.RATES_REL,
        "superseded": sup,
        "superseded_note": "measurements of an EARLIER code state that also publish a corpus-holdout "
                           "figure; they are listed so a reader never meets one without the label "
                           "(out/s3/honesty/oos_provenance.py, rule R3). A file whose code state is "
                           "UNRECOVERABLE can never be made current and is named permanently.",
    }
    if doc is None:
        return {**common, "available": False, "refused_because": bad,
                "note": "the estimate is ABSENT in this tree, exactly as tools/s3/score.py reports it. "
                        "No holdout number may be quoted from this document until it is rebuilt: "
                        + oos_provenance.REFRESH}
    return {**common, "available": True, "refused_because": None,
            "source": doc["source"], "split": doc["split"], "aggregation": doc["aggregation"],
            "holdout": doc["holdout"], "train": doc["train"],
            "holdout_as_built_before_the_correction": doc["holdout_as_built"],
            "caveats": doc["caveats"]}


def corpus_state():
    """The built corpus as it is NOW, read from the manifest rather than described from memory.
    The round that first wrote this block said the built tree was stale against corpus.py; the
    integration round rebuilt it (changes.jsonl I04) and the toggle round rebuilt three designs
    (T04), so the sentence is computed here instead of asserted."""
    from tools.s3 import corpus  # local: importing corpus pulls in numpy and the generators
    man = corpus.manifest()
    c, corr = man["counts"], man["corrections"]
    return {
        "fitted_on_moved_to_train": sorted(corpus.FITTED_ON) if hasattr(corpus, "FITTED_ON") else None,
        "dropped": sorted(corpus.DROPPED) if hasattr(corpus, "DROPPED") else None,
        "designs": c["designs"], "holdout_designs": c["holdout"], "train_designs": c["train"],
        "registers_by_kind": c["registers_by_kind"],
        "designs_whose_build_checks_pass": f"{c['checks_ok']}/{c['designs']}",
        "reference_structures_verified": c["reference_structures_verified"],
        "built_tree_matches_corpus_py": not corr["rebuild_needed"] and not corr["dropped"] and not corr["moved"],
        "manifest_corrections": corr,
        "toggle_rule": "1-bit toggles are kind 'flag' with alt_kinds ['counter'] (corpus.TOGGLE_RULE, the "
                       "string out/s3/truth_tempo.json uses): the lead's decision of 2026-09-23, so schema "
                       "v2.1's counter width >= 2 does not make toggle_en_ar, toggle_free_nr and "
                       "toggle_multi_sr unverifiable by construction (changes.jsonl T04)",
    }


TEMPO_LABEL = ("IN-SAMPLE and FITTED, not a generalisation estimate: thresholds were chosen on TEMPO (changes.jsonl "
               "C01-C06, C10, C21d, PC03, PC06, PC07, PC09) and four fixes were traced from TEMPO misses by truth "
               "name (C27-C30). Quote a TEMPO figure only with the record and code state it was measured on, and "
               "quote the corpus holdout beside it (C45, H02).")
TEMPO_HISTORY = (
    "HISTORY -- earlier code states, NOT the current figures, kept so a reader of an older copy can tell: "
    "review[2] measured macro and micro F1 1.000 on registers (found and exact), AMI 0.9806, ARI 0.9726 (its own "
    "four-place figures, truncated; the record's AMI is 0.98066), 106 of "
    "147 exact words, and this round reproduced it early in the 2026-09-22 session; the same run later in that "
    "session gave macro 0.9891, micro 0.9667, AMI 0.9788, ARI 0.9685, 104 of 147, the counter recognizer "
    "returning 24 structures for 22 truth registers (changes.jsonl C47, an intermediate tree other agents were "
    "editing; see code_drift); C60 then reported macro and micro F1 1.000 (found and exact), AMI 0.981, ARI 0.973 "
    "and 106 of 147 on the integrated code. CORRECTED 2026-09-22 (review[1] issue 7): this file once ended 'IT NO "
    "LONGER REPRODUCES ... do not quote 1.000', true only of that intermediate tree. CORRECTED 2026-09-23 "
    "(freeze 2): this headline "
    "used to present review[2]'s figures, 'found and exact' and '106 of 147' included, as the TEMPO result, "
    "citing C60 / C47 for the code state; the TEMPO record the freeze commit force-added disagrees on the exact "
    "F1s and the exact-word count (docs/S3.md section 15 item 9), so the current figures are now read from that "
    "record when this file is generated instead of being written here.")


def _sha256(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def tempo_headline():
    """(sentence, fields) for headline.tempo: the CURRENT TEMPO figures, read from the TEMPO evaluation
    record when this file is generated, then the earlier figures as labelled history.

    The record is the one tools/s3/freeze.py latest_eval_record("tempo") names -- the record S3_DESIGN
    cites and the freeze commit force-adds (commit_command()) -- so this headline and the freeze always
    point at the same file. Every figure is taken from the record's own scores (score.headline and
    score.grouping.all_flops of each evaluation: the file-order arm and the permutations); none is typed
    here. The record's pinned code state is compared with this tree, so the sentence says whether the
    figures are of this tree's tools/s3 or of an earlier one."""
    rel = freeze.latest_eval_record("tempo", ROOT)
    if rel is None:
        return (f"NO TEMPO EVALUATION RECORD: tools/s3/freeze.py latest_eval_record() finds none in "
                f"{freeze.EVAL_RUNS_REL}, so no current TEMPO figure may be quoted from this document. "
                f"{TEMPO_LABEL} {TEMPO_HISTORY}"), {"record": None}
    with open(os.path.join(ROOT, rel)) as f:
        rec = json.load(f)
    evs = [e for e in rec.get("evaluations") or [] if e.get("score") and not e.get("invalid_reasons")]
    if not evs:
        return (f"THE TEMPO RECORD {rel} HOLDS NO VALID SCORED EVALUATION, so no current TEMPO figure may be "
                f"quoted from this document. {TEMPO_LABEL} {TEMPO_HISTORY}"), {"record": rel, "evaluations": 0}

    def vals(get):
        return [get(e["score"]) for e in evs]

    def f4(v):
        lo, hi = min(v), max(v)
        return f"{lo:.4f}" if lo == hi else f"{lo:.4f}-{hi:.4f} (varies over the {len(v)} evaluations)"

    def n(v):
        lo, hi = min(v), max(v)
        return f"{lo}" if lo == hi else f"{lo}-{hi} (varies over the {len(v)} evaluations)"

    h = lambda k: vals(lambda s: s["headline"][k])                      # noqa: E731
    g = lambda k: vals(lambda s: s["grouping"]["all_flops"][k])         # noqa: E731
    fig = {"found_macro_f1_registers": h("macro_f1_registers"), "found_micro_f1_registers": h("micro_f1_registers"),
           "exact_macro_f1_registers": h("macro_f1_registers_exact"),
           "exact_micro_f1_registers": h("micro_f1_registers_exact"),
           "verified_macro_f1_registers": h("macro_f1_registers_verified"),
           "ami": h("ami"), "ari": h("ari"), "exact_words": g("exact_words"), "truth_words_multi": g("truth_words_multi")}
    code = rec.get("code") or {}
    moved = sorted(p for p, sha in code.items() if _sha256(p) != sha)
    rsrc = rec.get("recognizer_sources") or {}
    rmoved = sorted(p for p, sha in rsrc.items() if _sha256(p) != sha)
    labels = [e.get("label") for e in evs]
    prov = evs[0]["score"].get("provenance") or {}
    state = (f"all {len(code)} tools/s3 files the record pins still hash as recorded, so these are this tree's figures"
             if not moved else
             f"{len(moved)} of the {len(code)} tools/s3 files the record pins differ from this tree "
             f"({', '.join(moved)}); {len(rmoved)} of its {len(rsrc)} recognizer_sources differ"
             + (f" ({', '.join(rmoved)})" if rmoved else "")
             + ", so these are the figures of the record's code state, not a measurement of this tree")
    sentence = (
        f"CURRENT, read from {rel} when this file was generated (the TEMPO evaluation record tools/s3/freeze.py "
        f"latest_eval_record() names and the freeze commit force-adds; created {rec.get('created')}, "
        f"{len(evs)} valid evaluations: {', '.join(map(str, labels))}; the record's own label: "
        f"'{prov.get('label')}'): registers FOUND (any returned structure, NOT harness-verified) macro F1 "
        f"{f4(fig['found_macro_f1_registers'])}, micro F1 {f4(fig['found_micro_f1_registers'])}; registers found "
        f"by a HARNESS-VERIFIED structure macro F1 {f4(fig['verified_macro_f1_registers'])}; registers EXACT macro F1 {f4(fig['exact_macro_f1_registers'])}, "
        f"micro F1 {f4(fig['exact_micro_f1_registers'])}; AMI {f4(fig['ami'])}, ARI {f4(fig['ari'])} (all flops); "
        f"{n(fig['exact_words'])} of {n(fig['truth_words_multi'])} exact words. Code state: {state}. "
        f"{TEMPO_LABEL} {TEMPO_HISTORY}")
    fields = {
        "record": rel, "record_sha256": _sha256(rel), "created": rec.get("created"), "valid": rec.get("valid"),
        "evaluations": labels, "in_sample": prov.get("in_sample"), "label": prov.get("label"),
        "figures": {k: (v[0] if len(set(v)) == 1 else v) for k, v in fig.items()},
        "figures_source": "each evaluation's score.headline (F1, AMI, ARI) and score.grouping.all_flops "
                          "(exact_words, truth_words_multi); a list where the evaluations disagree",
        "code_pinned": len(code), "code_differing_from_this_tree": moved,
        "recognizer_sources_differing_from_this_tree": rmoved,
    }
    return sentence, fields


def code_state():
    """The code this document describes, and how a reader checks it still does."""
    return {
        "code_sha256": oos_provenance.code_hashes(),
        "sources": "score.OUT_OF_SAMPLE_SOURCES: the recognizer modules, verify.py (found means "
                   "harness-VERIFIED), corpus.py (the designs and the split) and score.py (which "
                   "registers are scored items) -- the files whose change can move a holdout rate",
        "check": ".venv/bin/python out/s3/honesty/oos_provenance.py  (exit 1 when this document, or "
                 "the rates it quotes, no longer describe the tree)",
        "rebuild": oos_provenance.REFRESH,
        "provenance_check": oos_provenance.check(),
    }


def build():
    cov, abl = _read("params_coverage.json"), ablations()
    evd = freeze.record_evidence()
    tempo_sentence, tempo_fields = tempo_headline()
    return {
        "schema": "retrace-s3-honesty-summary/2",
        "created": datetime.datetime.now(datetime.UTC).date().isoformat(),   # the DATE, not the
        # second: tools/s3/changes.jsonl cites this document by sha256, so a per-second stamp made
        # every re-run of the record chain rewrite the change log, which could then never settle
        # (found while checking the chain's idempotence for the freeze, 2026-09-23)

        "generated_by": "out/s3/honesty/summarise.py",
        "scope": "review[2]'s reporting and provenance items (issues 0-7), regenerated 2026-09-23 for the "
                 "freeze round's provenance items. The soundness and generalisation reviews are answered "
                 "elsewhere. No recognizer code ran on the puzzle or on a third-party design; "
                 "out/s3/truth_puzzle.json and out/s3/blind/ were not read.",
        "schema_note": "retrace-s3-honesty-summary/2 (2026-09-23) adds code_state (the sha256 of every "
                       "score.OUT_OF_SAMPLE_SOURCES file this document describes, with the check that "
                       "decides whether it still does) and replaces the copied out_of_sample block with "
                       "the gated one; /1 had neither, which is how it went on publishing a superseded "
                       "estimate as current.",
        "headline": {
            # built from the TEMPO record at generation time (tempo_headline()); the figures once typed
            # here are kept as labelled history inside it (docs/S3.md section 15 item 9)
            "tempo": tempo_sentence,
            "tempo_record": tempo_fields,
            "out_of_sample": "the synthetic corpus holdout, per kind, in out_of_sample below -- and ONLY "
                             "when out_of_sample.available is true. When it is false the estimate is "
                             "absent in this tree and no holdout number may be quoted from this document "
                             "(out_of_sample.refused_because says why, and gives the rebuild).",
            "caveat": "the corpus holdout is not clean either: it is synthetic and written by this project, its "
                      "cohort 2 exists because the generalisation regression set showed which classes were "
                      "missing (contamination K12), and the regression sets themselves were consulted (C25, "
                      "K13). After this round no uncontaminated generalisation set exists for counter, shift "
                      "or lfsr.",
        },
        "code_state": code_state(),
        "out_of_sample": out_of_sample(),
        "ablations": abl,
        "ablations_code_state": "EVERY corpus_holdout figure in `ablations` is a SNAPSHOT of the code "
                                "state its ablation file records, not of this tree. The arms within one "
                                "file share a code state and are comparable -- that is what the ablation "
                                "says -- but no absolute number here is the out-of-sample estimate; that "
                                "is out_of_sample, and only when it is available. Whether each ablation "
                                "file still describes this tree is in out_of_sample.superseded and in "
                                "code_state.provenance_check.",
        "code_drift": code_drift(),
        "ablation_findings": [
            "C01 (COVER_CAP 6 over the design's 4) bought exactly ONE TEMPO counter register in the EARLY run "
            "(macro F1 1.0000 -> 0.9886, micro 1.0000 -> 0.9692) and NONE in the LATE one (identical register "
            "counts at cap 4 and cap 6, macro 0.9891, micro 0.9667 in both); nothing at all on the holdout in "
            "either.",
            "C02 (P0 on the shared-class set over the design's dominant class) is WORSE out of sample than the "
            "design it replaced, in BOTH code states: holdout AMI 0.8453 against 0.8703 (early) and 0.7624 "
            "against 0.7874 (late), exact words 99 against 101 and 88 against 90 of 130. On TEMPO it is better, "
            "which is the set it was chosen on.",
            "C04's recorded gap (TEMPO AMI 0.969 one pass vs 0.950 at the fixed point) is NOT reproduced in "
            "either code state: the gap is 0.0039, and the fixed point is BETTER on ARI and on exact words. "
            "No-op on the holdout.",
            "C05: the corrected holdout confirms C05's own note that the synthetic set does not separate 1/3 "
            "from 1/2 (identical in both code states). The value rests on TEMPO alone.",
            "C06 (the depth-2 transfer split) changes NOTHING on TEMPO or on any of the 80 holdout runs, in "
            "both code states: its stated measurement is not reproducible.",
        ],
        "parameters": None if not cov else {
            "params_py_total": cov["params_total"],
            "in_change_log_before": len(cov["in_change_log"]),
            "design_3_8_only": sorted(cov["design_3_8_only"]),
            "undocumented_now_logged": sorted(cov["undocumented"]),
            "no_selection_set_recorded": ["CASE_ROUNDS", "CASE_TRIES", "CASE_MIN_LANES", "BLOCK_CUT_SHARE",
                                          "MUX_LEGS"],
            "outside_params_py": cov["outside_params_py"]},
        "change_log_corrections": {
            "PC02": "tuned_on ['corpus holdout: fsm_timer_ar', 'corpus']; fitted on the HOLDOUT design "
                    "fsm_timer_ar, measured on tmr_up_autoreload_w16_ar",
            "PC03": "tuned_on ['tempo', 'corpus']; measured on the holdout design cnt_down_w36_load_ar",
            "PC04": "tuned_on ['corpus']; measured on the holdout design cnt_case_mod5_ud_ar",
            "PC06": "tuned_on ['corpus', 'tempo']; measured on the holdout design acc_w8_en_ar",
            "C25": "status closed on crc12_d16_ar (dropped, C42)",
            "how": "every correction is recorded in the entry's own 'corrections' list with the previous value "
                   "and the reason; no entry's prose was rewritten",
        },
        "corpus": corpus_state(),
        "determinism": {
            "recognize_run": "recognize.py's RECOGNIZE_RUN line now carries canonical_order and bdd; run.py "
                             "parses it into every evaluation as 'recognize_run' and raises a problem on a tie "
                             "left to id order, a hit round budget, a missing block, a missing line, or more "
                             "than one distinct answer over the permutations",
            "blind_file_order_arm": "--leakage is now allowed with --blind",
            "leakage_test": leakage(),
        },
        "records_evidence": {"checked": evd["checked"], "stale": evd["stale"], "moved": len(evd["moved"]),
                             "missing": len(evd["missing"]),
                             "rule": "a stale CONTAMINATION hash blocks a freeze (the record describes the "
                                     "present); a moved CHANGE-LOG hash is reported only (an entry's evidence "
                                     "is a snapshot)"},
        "open_problems": [
            "No uncontaminated generalisation set survives for counter, shift or lfsr (review[2] issue 0). A "
            "fresh draw is a lead decision; until then every report must say so.",
            "C02 is worse out of sample than the design it replaced and stays only because nobody re-selected "
            "it (lead decision).",
            "C06 is dead code on TEMPO and on the whole corpus holdout.",
            "C01's only measured benefit is in-sample: one TEMPO counter register.",
            "C40's remainder, and ONLY its remainder: none of the nine moved thresholds is in "
            "params.NOT_PER_RUN, so a caller may still override them per run. That is a lead decision, not "
            "work. CORRECTED 2026-09-23 (checked against this tree, not copied from a review): this item used "
            "to read 'Ten recognizer thresholds live outside params.py (controls.py's NEW THRESHOLDS block), "
            "outside NOT_PER_RUN, with no proposed entries where their own comment says they are', which is "
            "false of this tree on three counts. Nine of the ten -- CLOCK_GATE_FOLD, CLOCK_GATE_FALLBACK, "
            "MODE_SELECT, MODE_SELECT_SHARE, MODE_SELECT_MIN_FLOPS, MODE_SELECT_MARGIN, MODE_SELECT_MAX_CANDS, "
            "MODE_SELECT_SCREEN, MODE_SELECT_MIN_LIVE -- resolve in tools/s3/params.py, moved unchanged by the "
            "integration round (I01) and logged one per value (C48, C49, C52, C53, C57 and their neighbours); "
            "controls.py has no _NEW_THRESHOLDS block left, only a comment recording the move; "
            "out/s3/controls/changes_proposed.jsonl does exist; and the tenth, CLOCK_GATE_SUPPORT, is in "
            "NEITHER module -- it is not a live threshold in this tree, the fold's support bound being "
            "params.HARNESS_CLOCK_SUPPORT = 16, the mirror of verify.CLOCK_SUPPORT. The parameters block "
            "above (outside_params_py, empty since the integration round) and C40's own corrected status say "
            "the same; this list had been missed. Logged as C40, closed_by I01 / C49 / C52 / C53 / C57.",
            "THE RECOGNIZER MOVED UNDER THIS ROUND'S MEASUREMENTS. The same ablation, run twice about ninety "
            "minutes apart in one session, gave corpus-holdout base AMI 0.8453 and then 0.7624, counter exact "
            "38 then 28, lfsr_crc found 12 then 14: other agents were editing tools/s3 (controls.py grew the "
            "clock-gate fold and the mode selector between the two runs). Every arm of ONE run shares a code "
            "state, so the ablation conclusions hold; the ABSOLUTE figures are a snapshot. "
            "CORRECTED 2026-09-23: this sentence used to end 'every ablation file now pins the tools/s3 "
            "hashes it was produced with', which is FALSE of "
            "out/s3/honesty/ablations_corpus_holdout.prev.json -- that file has no code block at all and "
            "the code state of its run cannot be reconstructed. It is listed permanently under "
            "out_of_sample.superseded (out/s3/honesty/oos_provenance.py), and no absolute figure of it may "
            "be quoted.",
            "THE TREE MOVED WHILE THIS DOCUMENT WAS BEING WRITTEN (2026-09-23): tools/s3/verify.py and "
            "tools/s3/score.py were edited by other agents of the same round minutes before the "
            "out-of-sample estimate below was re-derived. Whether the estimate still describes the tree is "
            "not a matter of memory: code_state.provenance_check answers it, and "
            "out/s3/honesty/oos_provenance.py answers it again for any reader, at any later time.",
            "FIXED SINCE THIS LIST WAS FIRST WRITTEN, and kept here so a reader of an older copy can tell: "
            "the built corpus is no longer stale against corpus.py (see corpus above; changes.jsonl I04, "
            "T04); out/s3/runs no longer holds the stray TEMPO development record (H05); and the four "
            "test/test_s3.py failures that round reported are not present in this tree.",
        ],
        "corrections": [
            {"what": "headline.tempo", "date": "2026-09-23",
             "was": "review[2]'s figures presented as the TEMPO result: 'macro and micro F1 1.000 on registers "
                    "(found and exact)' and '106 of 147 exact words', citing C60 / C47 for the code state",
             "now": "the current figures are read from the TEMPO evaluation record freeze.latest_eval_record() "
                    "names, with found (any structure) and harness-verified reported apart and exact beside "
                    "them; the earlier figures follow, labelled HISTORY",
             "why": "docs/S3.md section 15 item 9: the record the freeze commit force-added gives exact macro "
                    "0.9773 / micro 0.9384 and 103 of 147 exact words; fixed in Freeze 2 (changes.jsonl F03)"},
            {"what": "the out_of_sample block", "date": "2026-09-23",
             "was": "a verbatim copy of holdout_rates.json's blocks, with code_matches_tree true and the "
                    "2026-09-22 hashes, republished whatever the tree had since become",
             "now": "the estimate comes through tools/s3/score.out_of_sample(), the gate the report and "
                    "the pre-freeze checklist use; when it refuses, this file records the refusal in place "
                    "of the rates and quotes no number",
             "why": "review[1] of 2026-09-23, blocker: 'summary.json republishes a SUPERSEDED "
                    "out-of-sample estimate with no gate and no staleness marker'"},
            {"what": "code_drift.reference_evaluation.matches_this_tree", "date": "2026-09-23",
             "was": "null", "now": "score.out_of_sample_problem() is None, with the refusal text beside it",
             "why": "the one question that block exists to answer was left unanswered"},
            {"what": "code_drift.note", "date": "2026-09-23",
             "was": "'the holdout rates score.py prints come from out/s3/dev2/corpus_final.json'",
             "now": "the source is read from reference_evaluation.path, which is "
                    "out/s3/honesty/corpus_holdout_eval.json",
             "why": "false since H03 of 2026-09-22 gave the deriver its own --run; a reader chasing the "
                    "named file would have found a different evaluation"},
            {"what": "the corpus block and three open problems", "date": "2026-09-23",
             "was": "prose asserting a stale built corpus, a stray record in out/s3/runs and four failing "
                    "tests", "now": "the corpus block is computed from corpus.manifest(); the three items "
                    "are restated as fixed",
             "why": "all three were closed by later rounds (I04, H05) and a frozen record must not "
                    "describe a tree that no longer exists"},
            {"what": "open_problems item 5 (C40's ten thresholds)", "date": "2026-09-23",
             "was": "'Ten recognizer thresholds live outside params.py (controls.py's NEW THRESHOLDS block), "
                    "outside NOT_PER_RUN, with no proposed entries where their own comment says they are'",
             "now": "the nine that moved into params.py by I01 are named as moved; CLOCK_GATE_SUPPORT is "
                    "recorded as live in neither module; only the NOT_PER_RUN half is still open, and it is "
                    "the lead's call",
             "why": "review[1] of 2026-09-23 (freeze readiness), major: 'summary.json republishes a stale "
                    "open problem that its own body contradicts' -- parameters.outside_params_py in this "
                    "same file has been empty since the integration round, and C40's own status was "
                    "corrected on 2026-09-23. Re-checked against tools/s3/params.py, tools/s3/controls.py "
                    "and out/s3/controls/changes_proposed.jsonl in this tree before rewriting."},
            {"what": "'every ablation file now pins the tools/s3 hashes it was produced with'",
             "date": "2026-09-23", "was": "asserted", "now": "corrected: ablations_corpus_holdout.prev.json "
             "pins nothing and never will", "why": "checked by out/s3/honesty/oos_provenance.py (rule R1)"},
        ],
        "files_written": [
            "tools/s3/changes.jsonl", "out/s3/contamination.json", "tools/s3/params.py (docstring only; no "
            "value changed)", "tools/s3/corpus.py", "tools/s3/score.py", "tools/s3/run.py", "tools/s3/freeze.py",
            "tools/s3/recognize.py (the RECOGNIZE_RUN line)", "test/test_s3.py", "out/s3/honesty/",
            "out/s3/corpus/ (2026-09-23: the three toggle designs rebuilt under the flag rule)",
        ],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=os.path.join(HERE, "summary.json"))
    a = ap.parse_args(argv)
    doc = build()

    def write():
        with open(a.out, "w") as f:
            json.dump(doc, f, indent=1)
            f.write("\n")
    # twice, because the provenance check reads THIS file: the first pass gives it the code state
    # and the superseded list to check, the second records the verdict on the document as written.
    # Nothing but code_state.provenance_check and `created` differs between the two.
    write()
    doc["code_state"]["provenance_check"] = oos_provenance.check()
    write()
    print("wrote", a.out)
    pc = doc["code_state"]["provenance_check"]
    print(oos_provenance.render(pc))
    oos = doc["out_of_sample"]
    print("OUT-OF-SAMPLE: " + ("available" if oos["available"] else "ABSENT -- " + oos["refused_because"]))
    if pc["blocks"]:
        print(f"!! {len(pc['blocks'])} blocking provenance problem(s): this summary must not be frozen as is")
    if doc["ablations"]:
        for arm, v in doc["ablations"].items():
            print(f"  {arm:20s} TEMPO ami {v['tempo']['ami']:.4f}  holdout ami {v['corpus_holdout']['ami_mean']:.4f}"
                  f"  same as base on holdout: {v['same_as_base_on_holdout']}")
    # a non-zero exit is the loud failure: a stale summary must not pass for a fresh one
    return 1 if pc["blocks"] else 0


if __name__ == "__main__":
    sys.exit(main())
