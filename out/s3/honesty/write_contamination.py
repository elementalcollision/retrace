"""Refresh out/s3/contamination.json (review[2] issue 5; idempotent since review[1] issue 8).

    .venv/bin/python out/s3/honesty/write_contamination.py [--dry-run] [--by ROUND] [--date YYYY-MM-DD]

THE PASS'S OWN STAMPS (2026-09-23, review[1] of the freeze round, minor). `refreshed.date` was the
literal "2026-09-22" and `refreshed.by` the previous round's name, so the 2026-09-23 pass that added
K15 published the previous day's date and another round's attribution inside the record freeze.py
embeds verbatim; `items_added` was rebuilt per pass, so a hash-only pass published [] beside items
this writer had added earlier. The date and the round are now this run's (--date / --by override),
items_added is carried across passes with items_added_this_pass beside it, and a docs/S3_DESIGN.md
evidence note that names a revision is set from the document's own Status line instead of a literal.

IDEMPOTENCE. Running this twice must leave the record byte-identical to running it once: this is
the file freeze.py pins and the puzzle and blind reports cite, and the first version of this script
appended its summary paragraph, its report line and its two open items on every pass, and listed
the same corrected hash once per citing item (review[1] issue 8, which found 7 "open" entries of
which 5 were distinct and the same tools/s3/corpus.py correction four times). Every mutation below
is now stated as "make it so", never "add": text is appended only when absent, lists are deduped
keeping their order, and the corrections are collapsed by (path, was, now) with the citing items
listed under "where".

It re-hashes every evidence path the record already cites, replaces the stale hashes with the
current ones (noting what the old hash was and why it moved), and adds four items:

  K12  corpus cohort 2: why it exists (the generalisation regression set's findings), and the
       puzzle-shape check of its designs, which nobody had recorded
  K13  the regression set is no longer held out (changes.jsonl C25), and a corpus HOLDOUT design
       (fsm_timer_ar) had a threshold fitted to it
  K14  the corpus/regression duplicate crc12_d16_ar, now dropped from the corpus
  K15  the SECOND regression set, out/s3/review_generalisation2, is no longer held out either:
       five entries (C40, C49, C52, C53, C57) were fitted to five of its designs, which K13's
       singular wording hid. Added 2026-09-23 (changes.jsonl T02), and written WHOLE on every
       pass, so its wording can still be corrected here rather than by hand.

It also CLOSES the corpus-rebuild `open` item (done by changes.jsonl I04, re-checked against
corpus.manifest()) into a new `closed` list, and replaces the single-set "draw a fresh held-out
set" item with the two-set wording.

The record's audience note applies to this script's output: it restates puzzle facts and must not
reach recognizer authors. Nothing here reads out/s3/truth_puzzle.json -- the puzzle shapes it
checks against are the ones items K1-K3 of the record already state.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.s3 import corpus  # noqa: E402

PATH = os.path.join(ROOT, "out", "s3", "contamination.json")
DESIGN_REL = os.path.join("docs", "S3_DESIGN.md")
# The provenance stamps of a pass are the pass's OWN, not the first pass's. DATE used to be the
# literal "2026-09-22", so the 2026-09-23 refresh that added K15 stamped itself with the previous
# day's date and the previous round's name, inside the one record freeze.py embeds verbatim
# (review[1] of 2026-09-23, minor). The date is now taken when the writer runs, and the round is
# BY (--by overrides it), so a later round cannot inherit this one's attribution by accident.
DATE = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
BY = "reporting/provenance agent (the freeze round's provenance artefacts)"
REVIEW2 = ("/private/tmp/claude-501/-Users-dave-Jane-Street-Reverse-ASIC/"
           "cf1d1cbd-8f35-4b75-a57d-8114770f25d8/tasks/waufb9mpp.output")


def sha(path):
    full = path if os.path.isabs(path) else os.path.join(ROOT, path)
    if not os.path.exists(full):
        return None
    with open(full, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def ev(*paths, note=None):
    out = []
    for p in paths:
        h = sha(p)
        out.append({"path": p, "sha256": h, **({"note": note} if note else {}),
                    **({} if h else {"missing": "not present when this record was refreshed"})})
    return out


def dedupe(seq):
    """The list with later exact duplicates dropped, order kept (idempotence, review[1] issue 8)."""
    out, seen = [], set()
    for x in seq:
        k = json.dumps(x, sort_keys=True, default=str) if not isinstance(x, str) else x
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def collapse_corrections(fixed):
    """One entry per (path, was, now), with every citing item under "where" (review[1] issue 8:
    the same tools/s3/corpus.py correction was listed four times, once per citing K item)."""
    out = {}
    for x in fixed:
        k = (x["path"], x.get("was"), x.get("now"))
        e = out.setdefault(k, {"where": [], "path": x["path"], "was": x.get("was"), "now": x.get("now")})
        if x.get("where") not in e["where"]:
            e["where"].append(x.get("where"))
        for extra in ("why", "note"):
            if x.get(extra) and extra not in e:
                e[extra] = x[extra]
    return [dict(v, where=v["where"][0] if len(v["where"]) == 1 else v["where"]) for v in out.values()]


def refresh_hashes(doc):
    """Re-hash every evidence entry; return the list of corrections made."""
    fixed = []

    def walk(items, where):
        for e in items or []:
            if not isinstance(e, dict) or not e.get("path"):
                continue
            cur = sha(e["path"])
            if cur is None:
                # IDEMPOTENCE (2026-09-23): report a vanished path ONCE. This branch used to fire on
                # every pass -- it keeps the snapshot sha256 and only adds "missing", so the guard
                # `e["sha256"] is not None` stayed true for ever -- which made `fixed` non-empty on
                # every run, rotated the `refreshed` block into refreshed_history each time and grew
                # the record without end. Two passes of this writer are now byte-identical even when a
                # cited path is gone (K14's crc12_d16_ar/rtl.v, removed by the corpus rebuild I04).
                if e.get("sha256") is not None and not e.get("missing"):
                    fixed.append({"where": where, "path": e["path"], "was": e["sha256"], "now": None,
                                  "note": "the path no longer exists"})
                    e["missing"] = "not present when this record was refreshed"
                continue
            if e.get("sha256") != cur:
                fixed.append({"where": where, "path": e["path"], "was": e.get("sha256"), "now": cur})
                e["sha256"] = cur
    walk(doc.get("sources"), "sources")
    for it in doc.get("items") or []:
        walk(it.get("evidence"), it.get("id"))
        walk(it.get("records"), it.get("id"))
        walk(it.get("also_moved"), it.get("id"))
    return fixed


def cohort2_check():
    """The puzzle-shape check of corpus cohort 2 that nobody had recorded.

    The shapes come from items K1-K3 of this record (the puzzle's mod-11 digits, its mod-121
    cascade with a sticky done flag, its 12-deep tapped shift chain, its 8-step Fibonacci
    scrambler with a serial data mode, and its array of 2-bit saturating bins under a decode).
    Nothing here opens the puzzle truth."""
    ds = [x for x in corpus.designs() if x.cohort == 2]
    sp = corpus.splits(corpus.designs())
    moduli, depths, forms, fams = set(), set(), set(), {}
    for x in ds:
        fams.setdefault(x.family, []).append(x.name)
        t = os.path.join(corpus.DEFAULT_OUT, x.name, "truth.json")
        if not os.path.exists(t):
            continue
        with open(t) as f:
            tr = json.load(f)
        for r in tr["registers"]:
            p = r.get("params") or {}
            if r["kind"] == "counter" and p.get("modulus"):
                moduli.add(int(p["modulus"]))
            if r["kind"] == "shift_register" and p.get("depth"):
                depths.add(int(p["depth"]))
            if r["kind"] == "lfsr_crc" and p.get("form"):
                forms.add(p["form"])
    return {
        "designs": len(ds), "holdout": sum(1 for x in ds if sp.get(x.name) == "holdout"),
        "families": {k: sorted(v) for k, v in sorted(fams.items())},
        "counter_moduli": sorted(moduli), "shift_depths": sorted(depths), "lfsr_forms": sorted(forms),
        "checked_against": "items K1-K3 of this record",
        "result": [
            "NO cohort-2 counter has modulus 11 or 121, and no cohort-2 design is a cascade of two "
            "mod-11 digits: the moduli present are " + ", ".join(map(str, sorted(m for m in moduli if m < 1000)))
            + " and powers of two up to 2^64 (the wide counters).",
            "NO cohort-2 design is a Fibonacci scrambler, with or without an 8-step autonomous mode: its "
            "LFSR/CRC families are trinomial CRCs, word-parallel CRCs and xorshift maps, with forms "
            + ", ".join(sorted(forms)) + ".",
            "NO cohort-2 design is an array of 2-bit saturating bins under a decode; cohort 2 adds no "
            "counter_saturating design at all (casc_pre50up_dnsat10_ar saturates a single down counter).",
            "TWO partial shape matches, recorded rather than waved away: (1) nlfsr_w12_lsb_sr is a 12-deep "
            "shift chain with nonlinear feedback (train split), and the puzzle's tapped shift chain is also "
            "12 deep, although the cohort-2 design's feedback and taps were not taken from it; (2) cohort 2 "
            "adds cascade and concatenation families (counter_cascade_mixed, counter_concat: "
            "casc_div10dn_ev12up_sr, casc_pre200up_tmr16dn_ar, casc_pre50up_dnsat10_ar, cat_hilo_4x12_sr, "
            "cat_hilo_8x8_en_ar, cat_hilo_dn_6x6_en_nr, cat_hml_4x4x4_en_ar), which share the CLASS of the "
            "puzzle's counter cascade already recorded in K2, though none shares its moduli.",
        ],
        "how": "tools/s3/corpus.py designs() with cohort 2, and each design's out/s3/corpus/<name>/truth.json "
               "params (modulus, depth, form). The puzzle truth was not opened.",
    }


STRAY_TEMPO_RECORD = "out/s3/eval/dev_runs/tempo-20260921T231244Z-9ad4b666c101.json"
K7_DETAIL = (
    "three development runs of tools.s3.run on the puzzle with the stub recognizer (meta.recognizer 'stub', "
    "0 structures, 0 groups; modules recognize and netlist only), 2026-09-21 22:52-23:12Z, before any "
    "recognizer module existed (the build workflow started 23:45Z); run.py now refuses a development run of "
    "the puzzle. The third of those PUZZLE records lay in out/s3/runs, where blind records live, and was "
    "moved unchanged to out/s3/eval/dev_runs/ on 2026-09-22 (its sha256 is unchanged; changes.jsonl C16). "
    "That move did NOT empty out/s3/runs: a TEMPO development record was still there on 2026-09-22, which "
    "this item's earlier wording was read as covering (review[1] issue 3), and the pre-freeze checklist "
    "blocked on it until it too was moved unchanged to out/s3/eval/dev_runs/ (see also_moved below). It is a "
    "run of the DEVELOPMENT design with the stub recognizer, not a puzzle run, so it is no contamination "
    "path of its own; it is recorded here only because this item was the place the question was asked. "
    "out/s3/eval/probe_join.py ran extraction, GateGraph and the truth join on the puzzle.")


def correct_k7(doc):
    """K7 said 'the stray record was moved'; that was true of the PUZZLE stub record only, while a TEMPO
    development record stayed in out/s3/runs and blocked the pre-freeze checklist (review[1] issue 3).
    Setting, not appending: running this again changes nothing."""
    for it in doc.get("items") or []:
        if it.get("id") != "K7":
            continue
        it["detail"] = K7_DETAIL
        it["also_moved"] = [{
            "path": STRAY_TEMPO_RECORD,
            "sha256": sha(STRAY_TEMPO_RECORD),
            "note": "a TEMPO (development design) run record with the stub recognizer, blind false, written "
                    "2026-09-21T23:12:44Z; moved unchanged out of out/s3/runs on 2026-09-22 so that directory "
                    "holds blind records only. Not a puzzle run: listed here to correct this item's earlier "
                    "wording, not as a contamination path.",
        }]
    return doc


def design_revision():
    """'revision N' from docs/S3_DESIGN.md's own Status line, or None if it does not say.

    Read rather than hardcoded: K3's evidence note called the document "revision 2" while the hash
    beside it was revision 3's (review[1] of 2026-09-23, minor), and a hardcoded "revision 3" would
    be wrong again the next time the lead revises the document."""
    p = os.path.join(ROOT, DESIGN_REL)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        head = f.read(4000)
    m = re.search(r"\*\*Status\.\*\*\s*Revision\s+(\d+)", head)
    return f"revision {m.group(1)}" if m else None


def correct_design_revision(doc):
    """Make every 'revision N, ...' note on a docs/S3_DESIGN.md citation name the revision the file
    actually is. Setting, not appending: running this again changes nothing, and a note whose shape
    is not 'revision N...' is left exactly as its author wrote it."""
    rev = design_revision()
    if not rev:
        return doc

    def fix(items):
        for e in items or []:
            if not isinstance(e, dict) or e.get("path") != DESIGN_REL:
                continue
            note = e.get("note")
            if isinstance(note, str) and re.match(r"revision \d+", note):
                e["note"] = re.sub(r"^revision \d+", rev, note)

    fix(doc.get("sources"))
    for it in doc.get("items") or []:
        fix(it.get("evidence"))
        fix(it.get("records"))
        fix(it.get("also_moved"))
    return doc


def build(by=BY, date=DATE):
    with open(PATH) as f:
        doc = json.load(f)
    correct_k7(doc)
    correct_design_revision(doc)
    fixed = refresh_hashes(doc)
    ids = {it.get("id") for it in doc["items"]}
    c2 = cohort2_check()
    new = []
    if "K12" not in ids:
        new.append({
            "id": "K12",
            "what": "corpus cohort 2: written from the generalisation regression set's findings, and its "
                    "puzzle-shape check",
            "when": "2026-09-22",
            "who": "the corpus agent (changes.jsonl C23); the class list came from review[2]'s findings on "
                   "out/s3/review_generalisation",
            "detail": "C23 added 55 designs to the development corpus AFTER the record above was written, so "
                      "nothing here covered them. They exist because the generalisation review found classes "
                      "the corpus lacked, which means the regression set shaped the development data: a "
                      "contamination path from the regression set into the corpus and so into the recognizers "
                      "(the agent reports writing the RTL from scratch without reading the regression "
                      "generator). One of the 55, crc12_d16_ar, turned out to be the regression set's own "
                      "CRC-12 and has since been dropped (K14). The remaining 54 were checked for puzzle "
                      "shapes for this record; the check and its two partial matches are below.",
            "cohort2_puzzle_shape_check": c2,
            "effect": "the corpus the counter, shift and LFSR recognizers were tuned on now contains classes "
                      "chosen because the regression set exposed them; corpus figures and regression figures "
                      "are therefore not independent, and no cohort-2 design reproduces a puzzle shape except "
                      "the two partial matches recorded above",
            # tools/s3/changes.jsonl and out/s3/honesty/REPORT.md are cited by entry id in the text,
            # never by hash: the log grows, and a stale hash here would block a freeze for no reason
            "evidence": ev("tools/s3/corpus.py", "out/s3/corpus/manifest.json", REVIEW2),
        })
    if "K13" not in ids:
        new.append({
            "id": "K13",
            "what": "the generalisation regression set is no longer held out, and a corpus HOLDOUT design had a "
                    "threshold fitted to it",
            "when": "2026-09-22",
            "who": "counter.py, lfsr.py, shift.py, controls.py and verify.py (changes.jsonl C25); "
                   "PC02 for the holdout fit",
            "detail": "C25 records that out/s3/review_generalisation was consulted during development by "
                      "counter.py (11 designs read at the start of its phase, names not listed), lfsr.py (C20), "
                      "shift.py (PS04, PS07), the control layer's BDD prover (C21) and verify.py (C22); C26, "
                      "C29 and C40 add more. Its counter, LFSR/CRC and shift figures are a regression "
                      "measurement, not a generalisation estimate. Separately, review[2] found that "
                      "RELOAD_DISTINCT = 4 was set on fsm_timer_ar, which was in the corpus HOLDOUT (PC02, now "
                      "corrected); corpus.FITTED_ON moves it into train and the holdout rates were re-reported "
                      "(changes.jsonl C41). Four further corpus holdout designs are named in the change log as "
                      "MEASUREMENTS, not fits: tmr_up_autoreload_w16_ar (PC02), cnt_down_w36_load_ar (PC03), "
                      "cnt_case_mod5_ud_ar (PC04), acc_w8_en_ar (PC06); their outcomes were read while the "
                      "recognizer was being changed, so the holdout is a weaker estimate than an untouched set. "
                      "The ten controls.py thresholds of C40 were chosen on two REGRESSION designs "
                      "(scan_cnt8_ar, scan_mix_w12_ar).",
            "effect": "after this round no uncontaminated generalisation set exists for counter, shift or "
                      "lfsr. The out-of-sample estimate the reports quote is the synthetic corpus holdout "
                      "(out/s3/honesty/holdout_rates.json), which is itself written by this project and whose "
                      "cohort 2 came from the regression set's findings (K12).",
            "evidence": ev("tools/s3/corpus.py",
                           os.path.join("out", "s3", "honesty", "holdout_rates.json"), REVIEW2),
        })
    if "K14" not in ids:
        new.append({
            "id": "K14",
            "what": "crc12_d16_ar existed in both the development corpus and the held-out regression set",
            "when": "2026-09-22",
            "who": "the corpus agent (C23) added the corpus copy; found at integration (C25), decided by "
                   "review[2] issue 6",
            "detail": "Both are a CRC-12, poly 0x80F, 16 data bits, Galois, init 0; the RTL text differs "
                      "(sha256 833d60c1... vs 18b2ca14...). Any regression LFSR/CRC figure that included it "
                      "included a design that was also corpus training data. The corpus copy is now dropped "
                      "(corpus.DROPPED, changes.jsonl C42) and the corpus train lfsr_crc figure was restated "
                      "(items 50 -> 48, found and exact 48/48 = 1.0000); no holdout figure moves, because the "
                      "design was in the train split. crc16_d16_ar shares only its name between the two sets "
                      "(poly 98309 vs 101303).",
            "effect": "one duplicate removed; the regression set as a whole is still not held out (K13)",
            "evidence": ev("tools/s3/corpus.py", "out/s3/corpus/crc12_d16_ar/rtl.v",
                           "out/s3/review_generalisation/designs/ref/crc12_d16_ar/rtl.v",
                           os.path.join("out", "s3", "honesty", "holdout_rates.json"), REVIEW2),
        })
    # K15 is written WHOLE on every pass ("make it so"), unlike K12-K14 which are appended only when
    # absent: an item added once can never have its wording corrected without hand-editing the
    # record, which is exactly the kind of manual step this writer exists to remove. Replacing it
    # with identical content is still a no-op, so idempotence holds either way.
    k15 = {
            "id": "K15",
            "what": "the SECOND generalisation regression set (out/s3/review_generalisation2) is no longer "
                    "held out either: five change-log entries were fitted to five of its designs",
            "when": "2026-09-22 / 2026-09-23",
            "who": "controls.py (C40, C49), counter.py (C52, C53), lfsr.py (C57); moved into "
                   "tools/s3/params.py unchanged by the integration round (I01, C49/C52/C53/C57)",
            "detail": "K13 said 'the generalisation regression set' in the singular and named only "
                      "out/s3/review_generalisation; the record contained no occurrence of "
                      "'review_generalisation2' at all, although K13's own last sentence ('the ten "
                      "controls.py thresholds of C40 were chosen on two REGRESSION designs, scan_cnt8_ar "
                      "and scan_mix_w12_ar') is about set 2, where both of those designs live. The five "
                      "entries and the designs they were fitted to, each from the entry's own tuned_on / "
                      "regression_set_used field: "
                      "C40, the ten controls.py thresholds (CLOCK_GATE_*, MODE_SELECT*) -- scan_cnt8_ar and "
                      "scan_mix_w12_ar; "
                      "C49, MODE_SELECT_SHARE / MODE_SELECT_MIN_FLOPS / MODE_SELECT_MARGIN (the mode "
                      "selector) -- scan_cnt8_ar and scan_mix_w12_ar, then corrected on the synthetic "
                      "corpus; "
                      "C52, the case-selected step (several constant steps under one enable) -- "
                      "cnt_step12_w9_ar; "
                      "C53, the quiescent / awake rule (a flop that moves only under the detected reset) -- "
                      "cnt_bcd2_w8_ar; "
                      "C57, the pin-poly CONVENTION for a programmable CRC (which probed setting to report) "
                      "-- crc_poly4_modes_w16_ar. "
                      "All five designs are in out/s3/review_generalisation2/designs/ref/ (checked). "
                      "Nothing was retuned when the values of C49, C52, C53 and C57 moved into params.py; the fit happened where "
                      "the entries say it did.",
            "effect": "out/s3/review_generalisation2 is NOT a clean out-of-sample set for the clock-gate fold, "
                      "the mode selector, the case-selected counter step, the quiescent/awake rule or the "
                      "pin-poly convention, and its aggregate figures are a regression measurement, not a "
                      "generalisation estimate -- the same status K13 gives set 1. Both regression sets are "
                      "now contaminated; the only out-of-sample estimate any report may quote is the "
                      "synthetic corpus holdout (out/s3/honesty/holdout_rates.json, itself written by this "
                      "project: K12, K13). The 'no uncontaminated generalisation set' item under `open` "
                      "therefore covers both sets, not one.",
            # like K12-K14: tools/s3/changes.jsonl is cited by ENTRY ID in the text above, never by
            # hash -- the log grows, and a stale hash here would block a freeze for no reason. The
            # five fitted-to designs are hashed instead, because they do not move.
            "evidence": ev("tools/s3/params.py",
                           *[os.path.join("out", "s3", "review_generalisation2", "designs", "ref", d, "rtl.v")
                             for d in ("scan_cnt8_ar", "scan_mix_w12_ar", "cnt_step12_w9_ar",
                                       "cnt_bcd2_w8_ar", "crc_poly4_modes_w16_ar")]),
    }
    if "K15" in ids:
        doc["items"] = [k15 if it.get("id") == "K15" else it for it in doc["items"]]
    else:
        new.append(k15)
    # K16 (Freeze 2, 2026-09-23): the blind evaluation under freeze 1 SPENT its blind set. Stated here
    # because a later freeze that draws from the same candidate list would otherwise be free to draw one
    # of these designs again as if it were unseen.
    spent = ("ttsky26c/tt_um_joonatanalanampa_cordic", "tt05/tt_um_toivoh_synth", "ttsky25a/tt_um_td4",
             "tt03p5/tt_um_Reloj_top", "tt03p5/tt_um_thorkn_vgaclock", "tt07/tt_um_toivoh_basilisc_2816",
             "ttsky25a/tt_um_sjsu_vga_music", "tt07/tt_um_vzayakov_top", "tt05/tt_um_kskyou",
             "tt09/tt_um_pwm_top")
    k16 = {
            "id": "K16",
            "what": "freeze 1's blind evaluation SPENT its blind set: the ten drawn Tiny Tapeout designs, their "
                    "truths and the recognizer's result on each have been read in full",
            "when": "2026-09-23",
            "who": "the blind evaluation under freeze 1ee6a47894359fef (commit 232cfe6): the frozen labeller, the "
                   "run operators, four analysts, the report writer and the fact-checkers of docs/S3.md",
            "detail": "The ten designs drawn with the freeze-1 seed -- " + ", ".join(sorted(spent)) + " -- were "
                      "labelled by the frozen labeller (out/s3/truth_<id>.json), run once each, and every miss and "
                      "false positive on them was traced by truth name (docs/S3.md sections 8-10, "
                      "out/s3/blind/analysis/misses.json). The ten RESERVES were listed but never labelled, "
                      "fetched, extracted or run, and no other candidate was ever fetched: the download cache "
                      "(out/s3/blind/cache) holds exactly the ten drawn designs, the fifteen excluded pilot/probe "
                      "designs, and one design the pre-development scan rejected (tt05of/tt_um_diferential_ringy, "
                      "not a candidate). Freeze 2 extracted the excluded pilot ttsky25a/tt_um_BNN again to test the "
                      "extractor's top-level cuts; that is extractor-side and touched no candidate.",
            "effect": "none of the ten may be treated as unseen again: not drawn again, and no recognizer change "
                      "may be motivated by one of their misses while any of them is still counted as blind. "
                      "tools/s3/thirdparty.py draw() ranks sha256(seed|id) over the WHOLE candidate list and does "
                      "not exclude earlier draws, so the next freeze that records a draw must exclude these ten "
                      "first (listed under `open`). Freeze 2 records no draw.",
            # the truths and the labels file do not move; the ledger grows, so it is cited by path in the
            # text of docs/S3.md, never hashed here (a stale hash would block the next freeze for nothing)
            "evidence": ev("out/s3/blind/labels.json",
                           *[os.path.join("out", "s3", "truth_" + d.replace("/", "__") + ".json") for d in spent]),
    }
    if "K16" in ids:
        doc["items"] = [k16 if it.get("id") == "K16" else it for it in doc["items"]]
    else:
        new.append(k16)
    doc["items"] += new
    fixed = collapse_corrections(fixed)
    # items_added is CARRIED THROUGH (review[1] of 2026-09-23, minor): a pass that only corrects
    # hashes used to publish "items_added: []" beside items this writer had in fact added on an
    # earlier pass, so the live block read as though nothing had ever been added. The field is the
    # ids this writer has introduced, cumulative over its passes, and `items_added_this_pass` is
    # what THIS run introduced (empty on a hash-only pass, which is the normal case).
    this_pass = [n["id"] for n in new]
    carried = [i for blk in list(doc.get("refreshed_history") or []) + [doc.get("refreshed") or {}]
               for i in (blk.get("items_added") or [])]
    refreshed = {
        "date": date,
        "by": by,
        "evidence_hashes_corrected": fixed,
        "items_added": dedupe(carried + this_pass),
        "items_added_this_pass": this_pass,
        "note": "freeze.record_evidence() re-hashes every path this record cites; freeze write() refuses on a "
                "stale one unless --force, and FREEZE.json records the result as records_evidence. A "
                "change-log evidence hash that moved is reported, not blocked: a change-log entry's evidence "
                "is a snapshot of the file as it was, while this record describes the present. This writer is "
                "idempotent: a second pass that finds nothing to correct leaves the record unchanged "
                "(review[1] issue 8). `date` and `by` are THIS pass's, taken when the writer runs (they were "
                "a hardcoded 2026-09-22 and the previous round's name until 2026-09-23); `items_added` is "
                "every item this writer has introduced, carried across passes, and `items_added_this_pass` is "
                "what this run introduced.",
    }
    # rotate the previous pass into the history only when this pass actually did something; a
    # no-op run must not grow the record (idempotence)
    if fixed or new:
        prev = doc.get("refreshed")
        if prev and prev != refreshed:
            doc["refreshed_history"] = dedupe(list(doc.get("refreshed_history") or []) + [prev])
        doc["refreshed"] = refreshed
    elif "refreshed" not in doc:
        doc["refreshed"] = refreshed
    # normalise whatever the current block holds: the list written before this round carried the
    # same correction once per citing item (review[1] issue 8). Collapsing is lossless -- every
    # citing id stays under "where" -- and collapsing twice is the same as once.
    cur = doc["refreshed"]
    cur["evidence_hashes_corrected"] = collapse_corrections(cur.get("evidence_hashes_corrected") or [])
    # and carry the items forward even on a pass that rewrites nothing else, so the live block never
    # reads as though this writer had never added an item (the K15 case): idempotent, since the union
    # of a set with itself is itself.
    cur["items_added"] = dedupe(carried + list(cur.get("items_added") or []) + this_pass)
    cur.setdefault("items_added_this_pass", this_pass)
    cur["normalised"] = ("2026-09-22 (review[1] issue 8): the corrections are collapsed by (path, was, now) "
                         "with every citing item under 'where', and this writer is idempotent")
    para = (" Added 2026-09-22 (review[2] issue 5): corpus cohort 2 was written from the generalisation "
            "regression set's findings and has now been checked for puzzle shapes (K12, two partial matches "
            "recorded); the regression set is no longer held out and one corpus HOLDOUT design had a "
            "threshold fitted to it (K13); the corpus/regression duplicate crc12_d16_ar has been dropped "
            "(K14).")
    para2 = (" Added 2026-09-23 (review[1] of the freeze round, major): the SECOND regression set, "
             "out/s3/review_generalisation2, is no longer held out either -- five entries (C40, C49, C52, "
             "C53, C57) were fitted to five of its designs, which K13's singular wording hid (K15). Neither "
             "regression set is now a generalisation estimate.")
    summary = doc["summary"].rstrip()
    # each paragraph was appended on every pass until it was made conditional; drop the repeats, keep one
    for p in (para2, para):
        while summary.endswith(p.strip()):
            summary = summary[: -len(p.strip())].rstrip()
    doc["summary"] = summary + para + para2
    doc["puzzle_report_must_state"] = dedupe(list(doc["puzzle_report_must_state"]) + [
        "TEMPO's 1.000 is a FITTED development figure; the out-of-sample estimate is the synthetic corpus "
        "holdout, and after this round no uncontaminated generalisation set exists for counter, shift or lfsr "
        "(K13)",
        "NEITHER generalisation regression set is held out: out/s3/review_generalisation (K13) and "
        "out/s3/review_generalisation2 (K15, five entries fitted to five of its designs). A figure from "
        "either set is a regression measurement and must be labelled as one.",
    ])
    # The corpus-rebuild item was CLOSED by the integration round (changes.jsonl I04) and re-checked
    # here against corpus.manifest(): an `open` list that asks for work already done describes a tree
    # that no longer exists, which is the one thing a frozen record must not do (review[1] of
    # 2026-09-23, major). It is dropped rather than rewritten, and `closed` records why.
    rebuilt = corpus.manifest()["corrections"]
    # "make it so", not "add": the fresh-set item is REPLACED by the two-set wording, so the earlier
    # single-set sentence does not survive beside it (dedupe drops only exact repeats)
    doc["open"] = dedupe([o for o in doc["open"] if "crc12" not in o
                          and "a rebuild of out/s3/corpus" not in o
                          and not o.startswith("review[2] issue 0's second half")
                          and not o.startswith("the frozen evaluation of the puzzle runs >= 5 permutations")] + [
        "before the next freeze that records a draw: make tools/s3/thirdparty.py draw() exclude the ten "
        "designs K16 lists (it ranks over the whole candidate list today), so a spent design cannot be "
        "drawn again as unseen (K16)",
    ])
    doc["closed"] = dedupe(list(doc.get("closed") or []) + [{
        "was": "a rebuild of out/s3/corpus (python -m tools.s3.corpus) is needed for the built files to "
               "match corpus.py's FITTED_ON and DROPPED; corpus.manifest() corrects them for readers in "
               "the meantime",
        "closed_by": "changes.jsonl I04 (the integration round rebuilt out/s3/corpus: 168 designs, every "
                     "netlist and every truth_hash byte-identical) and T04 (the three toggle designs "
                     "rebuilt under the flag rule of 2026-09-23)",
        "checked": {"corpus.manifest()['corrections']": rebuilt},
        "when": "2026-09-23",
    }, {
        "was": "review[2] issue 0's second half: draw a fresh held-out set that no recognizer author has seen, or "
               "state in the report that none exists. This now covers BOTH regression sets: "
               "out/s3/review_generalisation (K13) and out/s3/review_generalisation2 (K15).",
        "closed_by": "freeze 1's blind evaluation: ten third-party Tiny Tapeout designs drawn after the freeze "
                     "(commit 232cfe6) with a seed committed in it, from a pool registered by structure-blind "
                     "criteria before recognizer development, labelled by the frozen labeller and run once each "
                     "(docs/S3.md). That set is now spent (K16); a further fresh set would need a new draw.",
        "when": "2026-09-23",
    }, {
        "was": "the frozen evaluation of the puzzle runs >= 5 permutations and reports their spread "
               "(changes.jsonl C14)",
        "closed_by": "out/s3/runs/blind-puzzle-20260923T073045Z-8ea21ef84643.json: K = 5 os.urandom "
                     "permutations, spread reported, 0 of 92 defined metrics varied (docs/S3.md sections 12.4 "
                     "and 13)",
        "when": "2026-09-23",
    }])
    return doc, fixed, [n["id"] for n in new]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--by", default=BY, help="the round running this pass, stamped as refreshed.by")
    ap.add_argument("--date", default=DATE, help="the UTC date to stamp (default: today, when this runs)")
    a = ap.parse_args(argv)
    doc, fixed, added = build(by=a.by, date=a.date)
    if not a.dry_run:
        with open(PATH, "w") as f:
            json.dump(doc, f, indent=1)
            f.write("\n")
    print(f"{'would correct' if a.dry_run else 'corrected'} {len(fixed)} evidence hash(es), added {added}")
    for x in fixed:
        print(f"  {x['where']}: {x['path']}: {str(x['was'])[:12]} -> {str(x['now'])[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
