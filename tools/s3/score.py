"""S3 scorer: a recognizer result against RTL ground truth (PRD S3; docs/S3_DESIGN.md section 4
as amended by the lead's scoring decisions of 2026-09-21 and the scorer review of 2026-09-22).

    score(truth, result, baselines=None, verified=None) -> report dict      render(report) -> text

`truth` is a retrace-s3-truth/2 dict (tools/s3/schema.py). `result` is a retrace-s3-result/1
dict whose flop ids the harness (tools/s3/run.py) has already mapped to the truth's join keys
(GDS instance names). `verified` is the harness's verdict per result structure (a list aligned
with result["structures"], from tools/s3/verify.py); without it nothing counts as verified.
Nothing here imports or depends on a recognizer.

Universe. The scored flops are the truth's `flops` minus shadow flops (bits[].shadow_flops, and
the legacy spelling bits[].duplicates: synthesis copies a structure may include or omit without
penalty). Result flops in `unmapped_flops`, unknown to the truth, or not flop ids at all are
DROPPED from their structures and groups before scoring and counted per structure; a structure
with any dropped flop can be found but never exact. Shadow flops in a structure are ignored.

Structures and matching (register level).
  * Only structures of schema.STRUCTURE_KINDS are scored; other kinds count as "none".
  * Items. Strict: every register, except that a synchronizer register which is a member of a
    declared CHAIN UNIT (a unit of kind synchronizer whose members are all synchronizer registers:
    per-stage RTL registers of one chain) is scored only through its chain units, which are items
    too. Lenient: every register plus every declared unit.
  * A structure S and an item U match when IoU = |S & U| / |S | U| > 0.5 and, for an item of >= 2
    flops, |S & U| >= 2. Matching is one to one and kind-agnostic: candidate pairs are taken
    greedily by IoU, then registers before units, then a harness-side hash of the structure's flop
    set, then the structure's position in the result, then the item name (never the
    recognizer-chosen id). A structure is used once; a register is credited at most once.
  * A unit match credits a member register only when S holds more than half of the member's flops
    (and >= 2 when the member has >= 2) and the member accepts the unit's kind on those flops;
    other members are "covered", not found. A unit match needs at least one such held member not
    yet credited.
  * Found: matched and the structure's kind is accepted (strict: the register's kind, or the chain
    unit's; lenient: kind or alt_kinds, or the unit's kind). Exact: found, equal flop sets and no
    dropped flop. found@IoU>=0.75 and the mean IoU of found pairs are reported next to found.
  * Precision (kind c) = structures of kind c that are found / structures of kind c; recall =
    registers of kind c found / registers of kind c. Denominators are the registers of kind c in
    both modes: alt_kinds only widen what a match accepts and never remove a register from a
    denominator (S3_DESIGN 4.2); registers with a non-structure alt kind are listed as "excused"
    and a recall without them is shown beside, never instead. Kinds with fewer than SMALL_SUPPORT
    registers are flagged. Macro-F1 (mean over kinds with support or predictions) and micro-F1
    (pooled over kinds) are reported together, for found and exact.
  * Counts per distinct RTL design (design_key): all / any of its instances found.
  * Everything is computed for all structures and for the harness-VERIFIED structures only
    ("verified"; a result's own "proven" status is a claim and counts for nothing).

Bit level. Each flop gets ONE predicted class: the kind of the structures holding it, or "several"
when structures of different kinds hold it. A flop is right when its predicted kinds are all kinds
the truth accepts for it (strict: kinds of the registers using it; lenient: plus alt_kinds and the
kinds of units in which it belongs to a member that accepts the unit's kind). Per kind c:
precision = right flops predicted c / flops predicted c; recall = right flops predicted c among
flops of registers of kind c / those flops. Macro- and micro-F1; per-flop confusion matrix.

Order (Kendall concordance against the TRUTH's ordered pairs), for every found (structure, item)
pair. The truth's order is its params `order` (lanes, stage 0 first) or `bit_order` (one lane, LSB
first), else the RTL bit index (one lane); a unit without an order is scored per member. Among the
shared flops, the truth orders "within" pairs (same truth lane, different stage) and "across" pairs
(same stage, different truth lane). The result asserts a within pair when it puts both flops in one
lane, and an across pair when it puts them at one position of two lanes; an asserted pair is
concordant or discordant, an unasserted pair is a tie worth 1/2. Per part: score = (C + U/2) / N
(reversible kinds, REVERSIBLE: max(C, D) + U/2, as direction is a convention), coverage = (C + D)
/ N, chance = the same score under uniformly random orders within each result lane (exact:
convolved Mahonian distributions) or of the result's lanes (exact enumeration up to
EXACT_ENUM_MAX orders, else seeded Monte Carlo), kappa = (score - chance) / (1 - chance). A pair
is "ordered" when coverage >= ORDER_COVERAGE_MIN in every part the truth orders; "all correct"
needs score 1 and coverage 1 with chance < 1. Summaries pool pairs, per truth kind, width <= 2 and
>= 3 apart.
  * The result's order is the structure's "order" or, when that is null, params.bit_order (one
    lane) or params.order (lanes), which is where the kind-bound verifier (schema v2) takes it from.
  * lanes_unordered (schema v2): a shift_register or synchronizer structure whose params set
    lanes_unordered = true declares that no structural key separates its lanes. Its across part is
    then not scored (None; the pairs are counted as "across_unscored_pairs" and the rows as
    "lanes_unordered", per kind and band, so a recognizer that sets the flag everywhere is
    visible); the within part and "all" (= within) are scored as usual.

Parameters: for found pairs of the same kind, every PARAMS entry the truth knows (non-null), except
the orders (ORDER_PARAMS), the order directive lanes_unordered (ORDER_DIRECTIVES) and
UNSCORED_PARAMS, after normalisation (strings case-folded, integral floats as ints; an LFSR
polynomial also matches its bit reversal; serial inputs per lane as a multiset). The LFSR form
(schema.LFSR_FORMS): "both" (the Fibonacci and Galois readings coincide, e.g. a trinomial) matches
"fibonacci", "galois" and "both" on either side; every other form, "affine" and "parallel"
included, matches only itself. Result answers of "both" against a single-form truth are counted
("form_both_answers") so a hedging recognizer is visible. Per parameter: accuracy next to the
majority-value baseline on the same pairs (the most common truth value, answered for every pair)
and kappa; "informative" parameters are those whose truth values are not all equal across the
design's registers of the kind, and are headlined.

Harness outcomes. With `outcomes` (run.py: one per result structure, from tools/s3/verify.py:
"verified", "unknown", "refuted", "vacuous", "malformed", "budget", "no claims", ...), the
register level also counts, per kind, the structures of each outcome; "unknown" (a solver limit,
not a refutation) is reported apart from the other non-verified outcomes.

Honesty (`verdicts`, the lead's decisions of 2026-09-23 closing review[0] issues 0 and 2 and
review[1] issue 4). `verdicts` is the harness's per-structure verdict dict (tools/s3/verify.py,
position-aligned with result["structures"]); `verified` and `outcomes` are the two flat projections
of it this file already took. Given the verdicts, the report carries a `honesty` block and the
params metric is split, so that no published number can say more than the harness proved:
  * FOUND vs VERIFIED side by side, per kind: the registers the recognizer's answer matched, and the
    registers it matched with a structure the harness VERIFIED, with the structure counts beside
    them and the verify.py REASON BUCKET of every unverified structure ("hold", "coverage",
    "unsupported clock", "unscored kind", "refuted", ... -- UNVERIFIED_REASONS spells each one out).
    A structure with no verdict at all is bucketed "not checked", never silently as verified.
  * What the VERIFIED count is worth: how many of those structures had a VACUOUS hold region, the
    mean and max of their load_hidden_share (the share of the state space their opaque load cases
    hide, over the verified structures that name one and over the whole verified set), how many
    carried DEAD BITS, how many carried UNCHECKED PARAMS, and how many kinds carry no per-bit
    liveness obligation at all. lfsr_crc polynomials are counted certified separately.
  * PARAMS split into CERTIFIED and TRANSCRIBED. A compared parameter is certified only when the
    harness VERIFIED the matched structure and listed that parameter in the verdict's
    `params_checked`; everything else is transcribed -- copied from the recognizer's answer and
    never checked (verify.py's own header: a reader must be able to tell the two apart). The
    combined accuracy is kept beside them, never instead of them.
The hold ceiling on the development design is an ACCEPTED limitation of this freeze
(HOLD_CEILING_NOTE), reported as a reason, not closed by widening the contract.

Grouping, against the partition of the universe by each flop's primary register; result `groups`
are restricted to the universe and every ungrouped flop is a singleton. AMI (arithmetic
normalisation, expected MI after Vinh, Epps and Bailey 2010, in numpy) and ARI are the headline;
NMI, pairwise precision/recall/F1, purity, inverse purity, exact words (lenient: a declared unit
holding the word's register, or all its per-slice units, as predicted groups) and split/merge
counts are secondary. Computed over all flops and over flops of registers with >= 2 flops, with two baselines:
every flop a singleton, and random partitions with the truth's block sizes (seeded draws).

Baselines for the class metrics: majority class (every flop its own structure, labelled with the
structure kind that owns the most truth flops) and, when the harness supplies it, a structural
baseline computed from the anonymous netlist (tools/s3/run.py: copy_graph_baseline).

Provenance (review[2] issue 0). Every report carries `provenance`, and render() prints it: whether
the scored design is the DEVELOPMENT design (TEMPO), in which case its numbers are labelled
IN-SAMPLE (a fitted development figure, not a generalisation estimate), and the out-of-sample
estimate to quote beside them -- the synthetic corpus HOLDOUT's per-kind found and exact rates,
read from out/s3/honesty/holdout_rates.json (written by out/s3/honesty/holdout_rates.py; the
scorer sees one design at a time and never runs a recognizer, so it cannot compute them). A missing
file is reported as a missing estimate, never silently skipped.

An out-of-sample document is quoted only when it can still be true of this tree (review[1] issue 0
and 1 of 2026-09-22, which found a stale artifact printed as current and a refresh path that wrote
an empty one in silence). out_of_sample() REFUSES a document that
  * carries no rates at all (every per-kind item count 0, or a kind with items and no rate), or
  * was derived on other code: every file in OUT_OF_SAMPLE_SOURCES -- the recognizer, verify.py
    (the rates count harness-VERIFIED structures, so they are a function of the verifier),
    corpus.py (it defines the designs and the split) and this file (it defines the scored items) --
    must hash exactly as it did when the rates were derived.
A refused document is reported like a missing one, with the command that rebuilds it; the numbers
are never printed. tools/s3/freeze.py's pre-freeze checklist blocks on the same condition.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import itertools
import json
import math
import os
import random
import re
import sys

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.s3 import schema  # noqa: E402
from tools.s3.schema import KINDS, PARAMS, STRUCTURE_KINDS, canonical_kind  # noqa: E402

REPORT_SCHEMA = "retrace-s3-score/3"
NONE = "none"
SEVERAL = "several"
CLASSES = STRUCTURE_KINDS + (NONE,)
# the class map: truth/result kind -> scored class (frozen with the code, tools/s3/freeze.py)
CLASS_MAP = {k: (k if k in STRUCTURE_KINDS else NONE) for k in KINDS}
REVERSIBLE = frozenset({"shift_register", "synchronizer", "lfsr_crc"})
ORDER_PARAMS = frozenset({"order", "bit_order"})
# order-scoring directives in params (never scored as parameters); the kinds that may carry them
ORDER_DIRECTIVES = frozenset({"lanes_unordered"})
LANES_UNORDERED_KINDS = frozenset(k for k, ps in PARAMS.items() if "lanes_unordered" in ps)
LANES_UNORDERED_RULE = ("a shift_register or synchronizer structure with params.lanes_unordered = true is scored "
                        "within lanes only (its across-lane pairs are counted, not scored)")
# LFSR forms: "both" stands for either companion reading; every other form matches only itself
LFSR_FORM_BOTH = "both"
LFSR_FORM_READINGS = ("fibonacci", "galois")
LFSR_FORM_RULE = ("lfsr_crc.form: 'both' matches 'fibonacci', 'galois' and 'both' on either side; 'affine', "
                  "'parallel', 'fibonacci' and 'galois' otherwise match only themselves")
# parameters an anonymous netlist cannot express, with the reason (reported, never scored)
UNSCORED_PARAMS = {("shift_register", "direction"): "RTL index direction (to_msb/to_lsb): the netlist has no "
                   "RTL indices; the stage order is scored by concordance instead"}
IOU_MIN = 0.5
IOU_HIGH = 0.75                # found@IoU>=0.75, reported next to found (IoU > 0.5)
MULTI = 2                      # a register of >= MULTI flops needs >= MULTI flops in a match
SMALL_SUPPORT = 3              # kinds with fewer registers are flagged: one miss swings recall by > 1/3
ORDER_COVERAGE_MIN = 0.5       # "ordered": the result asserts at least half the truth's ordered pairs
EXACT_ENUM_MAX = 100_000       # across-lane chance: enumerate every lane order up to this many (8 lanes)
MC_DRAWS = 2000
RANDOM_BLOCK_DRAWS = 5
SEED = 20260921
STRICT_SYNC_RULE = ("a synchronizer register that is a member of a declared chain unit (a synchronizer unit whose "
                    "members are all synchronizer registers) is scored strictly through its chain units only")

# --- honesty: what a harness verdict certifies, and what it does not -----------------------------
# Every reason tools/s3/verify.py can give for NOT verifying a structure, with what it means. The
# keys are verify.py's own "bucket" values (its _Fail bucket argument, plus "verified" and
# "malformed"); NOT_CHECKED is this file's bucket for a structure no verdict reached, so that a
# missing verdict is visible as a gap and never read as a pass.
NOT_CHECKED = "not checked"
UNVERIFIED_REASONS = {
    "hold": "hold: control.hold is required for a counter and a shift_register and either was not claimed or the "
            "hold region could not be discharged (an opaque load case may not be what empties it)",
    "coverage": "coverage: a condition the harness relies on reads the structure's own state and the defining case "
                "is not reachable at every own-word value in range",
    "vacuous": "vacuous: a named case is unsatisfiable with the reset and async controls inactive, so it would be "
               "checked nowhere",
    "template": "template: a harness-built template does not fit the structure's shape -- the extent and liveness "
                "rules (counter width >= 2 with every claimed bit live, shift depth >= 3, synchronizer stages >= 2) "
                "or a constant / word-independent template",
    "refuted": "refuted: a template obligation is FALSE on the netlist; the harness holds a counter-example",
    "form": "form: lfsr_crc -- the own-bit matrix is a permutation or is not strongly connected, or an EXPR is not "
            "an XOR of the structure's own q's, control.inputs nets and constants",
    "params": "params: a declared parameter contradicts the structure or the control the harness needs",
    "order": "order: the structure gives no order (the harness builds its templates from it) or order and params "
             "disagree",
    "clock domains": "clock domains: the structure's flops are not all in one clock domain (root and edge)",
    "unsupported clock": "unsupported clock: the harness does not model this flop's clock path, so it proves "
                         "nothing about it",
    "self-conditioned": "self-conditioned: a clock-gating enable reads the structure's own state, which is folded "
                        "into the next state and which no region can express",
    "unknown": "unknown: a SOLVER LIMIT, not a refutation -- the obligation was neither proved nor refuted",
    "budget": "budget: a run budget (conflicts or coverage calls) ran out before the obligation was decided",
    "malformed": "malformed: the structure does not follow the result schema",
    "unscored kind": "unscored kind: not one of the four STRUCTURE_KINDS, so it is never verified",
    NOT_CHECKED: "not checked: no harness verdict reached the scorer (no netlist, or this run did not verify)",
}
# The development design's ceiling, accepted for this freeze by the lead (2026-09-23) and reported
# as a reason rather than closed by loosening the contract.
HOLD_CEILING_NOTE = ("found and verified are reported separately because the harness certifies fewer structures than "
                     "the recognizer finds. On the development design the gap is the hold obligation: the count "
                     "condition pins a reload register whose complement is not a bounded set of cubes, so no legal "
                     "set of VERIFIED cases (the defining case, when_down and the reset cases) covers the space and "
                     "the hold region cannot be discharged -- and an opaque load case may not be the thing that "
                     "empties it. This is an ACCEPTED limitation of this freeze, not a recognizer miss and not a "
                     "contract to widen (lead decision, 2026-09-23).")
# A parameter is certified only where the harness pinned it; everything else was copied from the
# recognizer's answer (verify.py: params_checked / params_unchecked; lfsr_crc's bit_order counts
# only when the stage order was actually reconstructed).
PARAMS_CERTIFIED_RULE = ("a compared parameter is CERTIFIED only when the harness VERIFIED the matched structure and "
                         "named the parameter in the verdict's params_checked; every other compared parameter is "
                         "TRANSCRIBED -- copied from the recognizer's answer and never checked")
# Kinds whose verdict carries a per-bit liveness obligation (verify.py _liveness). For the others a
# verified structure has no live/dead bit report, which is reported as such and not as "0 dead".
LIVENESS_KINDS = frozenset({"counter"})

# --- provenance: in-sample vs out-of-sample (review[2] issue 0) ----------------------------------
# TEMPO is the development design. Recognizer thresholds were chosen on it (tools/s3/changes.jsonl
# C01-C06, C10, C21(d), PC03, PC06, PC07, PC09) and four fixes were traced from TEMPO misses by
# truth name (C27-C30), so every TEMPO number this file prints is a FITTED development figure and
# is labelled as one. The out-of-sample estimate quoted beside it is the synthetic corpus HOLDOUT
# (tools/s3/corpus.py splits(); rates precomputed by out/s3/honesty/holdout_rates.py, since the
# scorer sees one design at a time and never runs a recognizer).
DEV_DESIGNS = ("tempo",)
IN_SAMPLE_NOTE = ("TEMPO is the development design: this score is IN-SAMPLE (a fitted development figure), not a "
                  "generalisation estimate. Thresholds were selected on it (changes.jsonl C01-C06, C10, C21d, "
                  "PC03, PC06, PC07, PC09) and four recognizer fixes were traced from TEMPO misses by truth name "
                  "(C27-C30).")
OUT_OF_SAMPLE_REL = os.path.join("out", "s3", "honesty", "holdout_rates.json")
OUT_OF_SAMPLE_REFRESH = ("rebuild it: .venv/bin/python out/s3/review_generalisation2/evaluate.py --corpus "
                         "--seed 20260922 --out out/s3/honesty/corpus_holdout_eval.json && "
                         ".venv/bin/python out/s3/honesty/holdout_rates.py "
                         "--eval out/s3/honesty/corpus_holdout_eval.json")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _out_of_sample_refusal(doc, root=None):
    """Why this out-of-sample document may not be quoted in this tree, or None (review[1] issues
    0 and 1). Every message says the estimate is absent: a refused document is reported exactly
    like a missing one, never as a table of dashes."""
    tail = f": the out-of-sample estimate is absent until it is rebuilt ({OUT_OF_SAMPLE_REFRESH})"
    if not isinstance(doc, dict) or not isinstance(doc.get("holdout"), dict) \
            or not isinstance(doc.get("train"), dict) or not isinstance(doc.get("source"), dict):
        return f"{OUT_OF_SAMPLE_REL} is malformed (no holdout / train / source block){tail}"
    h = doc["holdout"]
    per = h.get("per_kind") or {}
    items = 0
    for k in STRUCTURE_KINDS:
        c = per.get(k) or {}
        n = c.get("items") or 0
        items += n
        if n and (c.get("found_rate") is None or c.get("exact_rate") is None):
            return (f"{OUT_OF_SAMPLE_REL} has {n} {k} item(s) and no rate for them, so it was written by a "
                    f"reader that could not tally its evaluation{tail}")
    if not items or not h.get("runs") or not h.get("designs"):
        return (f"{OUT_OF_SAMPLE_REL} carries no rates ({h.get('designs')} designs, {h.get('runs')} runs, "
                f"{items} scored items): an empty estimate is not an estimate{tail}")
    # the rates are a function of the recognizer, the verifier, the corpus and the scored-item
    # definition; quoting them in a tree where any of those has moved would be a false claim
    # "code_sha256" is the retrace-s3-holdout-rates/2 field: the code the EVALUATION ran on. When
    # the deriver could not vouch for it (--stale-ok) the key is present and empty, and an empty
    # map must refuse, never fall back to "recognizer_code_now" (which is only this tree, then).
    src = doc["source"]
    recorded = src["code_sha256"] if "code_sha256" in src else (src.get("recognizer_code_now") or {})
    recorded = recorded or {}
    now = _code_hashes(root)
    unrecorded = [p for p in sorted(now) if p not in recorded]
    if unrecorded:
        return (f"{OUT_OF_SAMPLE_REL} does not record the code it was derived on "
                f"({', '.join(unrecorded[:6])}{' ...' if len(unrecorded) > 6 else ''}), so nothing can say "
                f"whether it describes this tree{tail}")
    moved = [p for p, v in sorted(now.items()) if recorded.get(p) != v]
    if moved:
        return (f"{OUT_OF_SAMPLE_REL} was derived on other code: {len(moved)} of {len(now)} recognizer / "
                f"harness source(s) differ ({', '.join(moved[:6])}{' ...' if len(moved) > 6 else ''}), so "
                f"these rates do not describe this tree{tail}")
    return None


def out_of_sample(root=None):
    """The corpus-holdout rates (out/s3/honesty/holdout_rates.json), or None when the file is
    absent, unreadable, empty or derived on other code. Data only: nothing here recomputes them;
    out_of_sample_problem() gives the reason when this returns None."""
    doc, _bad = _load_out_of_sample(root)
    return doc


def out_of_sample_problem(root=None):
    """The reason the out-of-sample estimate cannot be quoted here, or None when it can."""
    return _load_out_of_sample(root)[1]


def _load_out_of_sample(root=None):
    p = os.path.join(root or ROOT, OUT_OF_SAMPLE_REL)
    try:
        with open(p) as f:
            doc = json.load(f)
    except FileNotFoundError:
        return None, (f"{OUT_OF_SAMPLE_REL} is absent: no out-of-sample estimate is available "
                      f"({OUT_OF_SAMPLE_REFRESH})")
    except (OSError, ValueError) as e:
        return None, (f"{OUT_OF_SAMPLE_REL} is unreadable ({type(e).__name__}): the out-of-sample estimate is "
                      f"absent until it is rebuilt ({OUT_OF_SAMPLE_REFRESH})")
    bad = _out_of_sample_refusal(doc, root)
    return (None, bad) if bad else (doc, None)


def provenance(design, root=None):
    """What a reader must be told about this design's numbers: whether they are in-sample, and the
    out-of-sample estimate to quote beside them (review[2] issue 0)."""
    in_sample = design_id(design) in DEV_DESIGNS
    doc, bad = _load_out_of_sample(root)
    out = {"design": design, "in_sample": in_sample,
           "label": "in-sample (fitted development figure)" if in_sample else "not the development design",
           "note": IN_SAMPLE_NOTE if in_sample else None,
           "out_of_sample": None}
    if doc is None:
        out["out_of_sample_missing"] = bad
        return out
    out["out_of_sample"] = {
        "set": "synthetic corpus holdout (tools/s3/corpus.py)", "source": doc["source"],
        "split": doc["split"], "aggregation": doc["aggregation"],
        "runs": doc["holdout"]["runs"], "designs": doc["holdout"]["designs"],
        "per_kind": doc["holdout"]["per_kind"], "grouping": doc["holdout"]["grouping"],
        "false_positive_structures": doc["holdout"]["false_positive_structures"],
        "train_per_kind": doc["train"]["per_kind"], "caveats": doc["caveats"],
        "code_state": "every file of OUT_OF_SAMPLE_SOURCES hashes as it did when these rates were derived"}
    return out


# The modules whose change can move the published holdout rates, checked before they are quoted.
# RECOGNIZER_SOURCES is the recognizer's own answer AND verify.py: "found" means the item matched a
# harness-VERIFIED structure, so the rates are a function of the verifier too, and a round in which
# only verify.py moved (mandatory control.hold, 2026-09-22) dropped 8 holdout items while this file
# reported nothing (review[1] issue 2).
RECOGNIZER_SOURCES = ("recognize.py", "controls.py", "counter.py", "lfsr.py", "shift.py", "group.py",
                      "netlist.py", "params.py", "schema.py", "verify.py")
# plus the two files that decide WHAT was measured: corpus.py (the designs and the train/holdout
# split) and this file (Truth: which registers and units are scored items at all)
OUT_OF_SAMPLE_SOURCES = RECOGNIZER_SOURCES + ("corpus.py", "score.py")


def _code_hashes(root=None):
    """sha256 of the sources the published out-of-sample estimate depends on, computed here so the
    scorer imports no harness module."""
    out = {}
    for name in OUT_OF_SAMPLE_SOURCES:
        p = os.path.join(root or ROOT, "tools", "s3", name)
        if os.path.exists(p):
            with open(p, "rb") as f:
                out[os.path.join("tools", "s3", name)] = hashlib.sha256(f.read()).hexdigest()
    return out


def render_provenance(rep):
    """The in-sample / out-of-sample block, as lines."""
    pv = rep.get("provenance") or {}
    L = []
    if pv.get("in_sample"):
        L.append("IN-SAMPLE: " + IN_SAMPLE_NOTE)
    oos = pv.get("out_of_sample")
    if not oos:
        if pv.get("out_of_sample_missing"):
            L.append("OUT-OF-SAMPLE: " + pv["out_of_sample_missing"])
        return L
    sp = oos["split"]
    L.append(f"OUT-OF-SAMPLE estimate, {oos['set']}: {oos['designs']} designs, {oos['runs']} runs "
             f"({sp['train_designs']} train), from {oos['source']['path']}")
    L.append(f"  aggregation: {oos['source'].get('aggregation_id', 'unrecorded')}; measured on the code in this "
             f"tree ({len(OUT_OF_SAMPLE_SOURCES)} recognizer / harness sources hash as recorded)")
    def _r(x):
        return "-" if x is None else f"{x:.4f}"

    L.append(f"  {'kind':<16}{'found':>18}{'exact':>18}    train: found / exact")
    for k in STRUCTURE_KINDS:
        h = oos["per_kind"].get(k) or {}
        t = oos["train_per_kind"].get(k) or {}
        if not h.get("items"):
            continue
        fr = f"{h['found']:>3}/{h['items']:<3} {_r(h['found_rate'])}"
        ex = f"{h['exact']:>3}/{h['items']:<3} {_r(h['exact_rate'])}"
        L.append(f"  {k:<16}{fr:>18}{ex:>18}    {_r(t.get('found_rate'))} / {_r(t.get('exact_rate'))}")
    g = oos["grouping"]
    L.append(f"  grouping AMI mean {g['ami_mean']} median {g['ami_median']}; false-positive structures "
             f"{oos['false_positive_structures']}")
    for c in oos.get("caveats") or []:
        L.append("  caveat: " + c)
    return L


def class_map():
    """Everything that decides which kinds are scored as what (frozen, tools/s3/freeze.py)."""
    return {"class_map": dict(CLASS_MAP), "aliases": dict(schema._KIND_ALIASES),
            "structure_kinds": list(STRUCTURE_KINDS), "reversible": sorted(REVERSIBLE),
            "order_params": sorted(ORDER_PARAMS), "iou_min": IOU_MIN, "iou_high": IOU_HIGH, "multi": MULTI,
            "small_support": SMALL_SUPPORT, "order_coverage_min": ORDER_COVERAGE_MIN,
            "strict_synchronizers": STRICT_SYNC_RULE, "shadow_fields": ["shadow_flops", "duplicates"],
            "lenient_denominators": "all registers of the kind (alt_kinds never remove a register)",
            "unit_member_credit": "more than half of the member's flops (>= 2 when it has >= 2)",
            "bit_level": "one predicted class per flop; 'several' is right only if the truth accepts every kind",
            "unscored_params": {f"{k}.{p}": why for (k, p), why in sorted(UNSCORED_PARAMS.items())},
            "order_directives": sorted(ORDER_DIRECTIVES), "lanes_unordered": LANES_UNORDERED_RULE,
            "lanes_unordered_kinds": sorted(LANES_UNORDERED_KINDS), "lfsr_form": LFSR_FORM_RULE,
            # the honesty rules (2026-09-23): what a published number is allowed to claim
            "params_certification": PARAMS_CERTIFIED_RULE, "unverified_reasons": dict(UNVERIFIED_REASONS),
            "liveness_kinds": sorted(LIVENESS_KINDS), "hold_ceiling": HOLD_CEILING_NOTE,
            "found_vs_verified": "found and verified are separate columns everywhere: found is the recognizer's "
                                 "answer matching the register, verified is that match with a structure the harness "
                                 "proved, and every unverified structure carries its verify.py reason bucket"}


# ----------------------------------------------------------------------------------------------
# truth


def load_truth(path, design=None, strict=True):
    """A retrace-s3-truth/2 file. With strict (the default, and always for blind runs) it raises
    unless schema.check_truth passes; with strict=False the problems are only recorded (the Truth
    view lists them). When `design` is given the file must be that design's (a third-party truth's
    "tt:<shuttle>/<macro>" also matches "<shuttle>__<macro>"). Returns (truth, raw), the same dict
    twice (kept as a pair so callers pin the file's own truth_hash)."""
    with open(path) as f:
        raw = json.load(f)
    bad = schema.check_truth(raw) if strict else []
    if design is not None and design_id(raw.get("design")) != design_id(design):
        bad.append(f"design {raw.get('design')!r} != {design!r}")
    if bad:
        raise ValueError(f"{path}: invalid truth: {bad[:5]}{' ...' if len(bad) > 5 else ''}")
    return raw, raw


def design_id(name):
    """The file-safe design id: "tt:tt06/tt_um_x" and "tt06/tt_um_x" -> "tt06__tt_um_x"."""
    name = str(name or "")
    if name.startswith("tt:"):
        name = name[3:]
    return name.replace("/", "__")


def _local_name(name):
    last = re.split(r"\.(?![^\[]*\])", name)[-1]
    return re.sub(r"\[\d+\]", "", last)


class Truth:
    """Indexed view of a retrace-s3-truth/2 dict."""

    def __init__(self, t, strict=False):
        self.problems = schema.check_truth(t)
        if strict and self.problems:
            raise ValueError(f"invalid truth: {self.problems[:5]}")
        self.raw = t
        self.design = t.get("design")
        self.shadow_of = collections.defaultdict(set)   # shadow flop -> registers it shadows
        for r in t.get("registers", []):
            for b in r.get("bits", []):
                for f in list(b.get("shadow_flops") or []) + list(b.get("duplicates") or []):
                    self.shadow_of[f].add(r["name"])
        self.universe = frozenset(f for f in t.get("flops", {}) if f not in self.shadow_of)
        self.unmapped = {u["flop"]: u.get("reason", "") for u in t.get("unmapped_flops") or []}
        self.primary = {f: v["primary"] for f, v in t["flops"].items() if f in self.universe}
        self.regs, self.flops, self.idx, self.kind, self.accepts = {}, {}, {}, {}, {}
        self.bit_alt = {}   # (register, flop) -> per-bit alt kinds (override the register's alt_kinds)
        self.no_flop = []
        members = collections.defaultdict(set)         # register -> flops listing it (truth["flops"])
        for f, v in t["flops"].items():
            if f in self.universe:
                for n in v.get("registers", []):
                    members[n].add(f)
        for r in t["registers"]:
            n = r["name"]
            self.regs[n] = r
            self.kind[n] = canonical_kind(r["kind"])
            self.accepts[n] = frozenset({self.kind[n]} | {canonical_kind(k) for k in r.get("alt_kinds") or []})
            idx = {}
            for b in r["bits"]:
                f = b.get("flop")
                if f in self.universe:
                    idx[f] = min(idx.get(f, b["index"]), b["index"])
                    if b.get("alt_kinds") is not None:
                        self.bit_alt.setdefault((n, f), set()).update(canonical_kind(k) for k in b["alt_kinds"])
            self.idx[n] = idx   # truth bit index per flop (flops known only from truth["flops"] have none)
            self.flops[n] = frozenset(idx) | frozenset(members.get(n, ()))
            if not self.flops[n]:
                self.no_flop.append(n)
        self.scored = [n for n in self.regs if self.flops[n]]
        self.flop_regs = collections.defaultdict(list)
        for n in self.scored:
            for f in self.flops[n]:
                self.flop_regs[f].append(n)
        self.units, self.bad_units = [], []
        for u in t.get("units") or []:
            k = canonical_kind(u["kind"])
            mem = [m for m in u["registers"] if m in self.regs]
            if u.get("flops") is not None:   # a unit may take only some bits of a member
                fl = frozenset(f for f in u["flops"] if f in self.universe)
            else:
                fl = frozenset().union(*(self.flops[m] for m in mem)) if mem else frozenset()
            if not fl:
                self.bad_units.append({"name": u["name"], "why": "no labelled flop"})
                continue
            # members that accept the unit's kind on every bit the unit takes (e.g. not a terminal
            # flag inside a counter unit, which the unit only covers)
            credit = [m for m in mem if all(k in self.flop_accepts(m, f) for f in fl & self.flops[m])]
            chain = (k == "synchronizer" and bool(mem) and all(self.kind[m] == "synchronizer" for m in mem))
            self.units.append({"name": u["name"], "kind": k, "registers": mem, "credit": credit, "flops": fl,
                               "params": u.get("params") or {}, "reason": u.get("reason"), "chain": chain})
        self.chain_members = {m for u in self.units if u["chain"] for m in u["registers"]}

    def flop_accepts(self, name, f):
        """Kinds register `name` accepts for its flop f: per-bit alt_kinds override the register's."""
        alt = self.bit_alt.get((name, f))
        return self.accepts[name] if alt is None else frozenset({self.kind[name]} | alt)

    def design_key(self, name):
        r = self.regs[name]
        return r.get("design_key") or f"{r.get('module_def') or ''}:{_local_name(name)}"

    def denominators(self, c, lenient=False):
        """Registers of kind c (both modes: alt_kinds never shrink a denominator)."""
        return [n for n in self.scored if self.kind[n] == c]

    def excused(self, c):
        """Registers of kind c with a non-structure alt kind (reported beside lenient recall)."""
        return [n for n in self.denominators(c) if not self.accepts[n] <= set(STRUCTURE_KINDS)]

    def strict_kinds(self, f):
        return {self.kind[n] for n in self.flop_regs.get(f, ())}

    @property
    def lenient_accepts(self):
        """flop -> kinds some register holding it accepts, plus the kinds of units in which it belongs
        to a member that accepts the unit's kind."""
        if not hasattr(self, "_lacc"):
            acc = collections.defaultdict(set)
            for n in self.scored:
                for f in self.flops[n]:
                    acc[f] |= self.flop_accepts(n, f)
            for u in self.units:
                for m in u["credit"]:
                    for f in u["flops"] & self.flops[m]:
                        acc[f].add(u["kind"])
            self._lacc = acc
        return self._lacc


# ----------------------------------------------------------------------------------------------
# result


def _hkey(flops):
    """Harness-side tie-break key of a flop set (never the recognizer-chosen structure id)."""
    return hashlib.sha256("\n".join(sorted(flops)).encode()).hexdigest()


def _outcome(verified, outcomes, i, verdict=None):
    """The harness's outcome for result structure i: outcomes[i] when given, else the verdict's own
    bucket, else verified/not."""
    if outcomes is not None and i < len(outcomes) and isinstance(outcomes[i], str):
        return outcomes[i]
    if verdict is not None and verdict["bucket"]:
        return verdict["bucket"]
    if verified is None:
        return NOT_CHECKED
    return "verified" if i < len(verified) and verified[i] else "not verified"


def _verdict_view(vd):
    """The honesty fields of one harness verdict (tools/s3/verify.py), normalised; None when no
    verdict was given for the structure. A field the verdict does not carry stays None or False --
    nothing here supplies a default that would read as evidence. `params_checked` is meaningful only
    on a verdict that verified (verify.py fills it last, after every obligation held), so
    `certifies` says so explicitly."""
    if not isinstance(vd, dict):
        return None
    ok = bool(vd.get("verified"))
    pc = vd.get("params_checked")
    pu = vd.get("params_unchecked")
    live, dead = vd.get("live_bits"), vd.get("dead_bits")
    share = vd.get("load_hidden_share")
    cases = vd.get("cases") if isinstance(vd.get("cases"), dict) else {}
    bucket = vd.get("bucket") if isinstance(vd.get("bucket"), str) and vd.get("bucket") else None
    notes = vd.get("params_notes")
    return {"bucket": bucket or ("verified" if ok else None), "verified": ok,
            "kind": vd.get("kind"), "scored": bool(vd.get("scored")),
            "hold_claimed": bool(cases.get("hold")), "hold_vacuous": bool(vd.get("hold_vacuous")),
            # verify.py 2026-09-23: what emptied an empty hold region -- "verified" when the defining,
            # when_down and reset cases do it by themselves, "load" when the opaque load cases did
            # (which is refused, so it never reaches a verified structure)
            "hold_vacuous_cover": vd.get("hold_vacuous_cover"),
            "params_notes": dict(notes) if isinstance(notes, dict) else {},
            "load_cases": int(cases.get("load") or 0), "reset_cases": int(cases.get("reset") or 0),
            "load_hidden_share": (float(share) if isinstance(share, (int, float))
                                  and not isinstance(share, bool) else None),
            "params_checked": frozenset(x for x in pc if isinstance(x, str)) if isinstance(pc, list) else frozenset(),
            "params_unchecked": frozenset(x for x in pu if isinstance(x, str)) if isinstance(pu, list) else frozenset(),
            "params_reported": isinstance(pc, list) or isinstance(pu, list),
            "certifies": ok and isinstance(pc, list),
            "live_bits": len(live) if isinstance(live, list) else None,
            "dead_bits": len(dead) if isinstance(dead, list) else None,
            "liveness_checked": isinstance(live, list) or isinstance(dead, list),
            "poly_certified": ok and isinstance(pc, list) and "poly" in pc}


def certified_param(s, p):
    """Did the harness CERTIFY parameter `p` of the structure `s` (a _structures() row)? Only a
    verdict that verified certifies, and only the names it listed in params_checked."""
    vd = s.get("verdict")
    return bool(vd and vd["certifies"] and p in vd["params_checked"])


def _bucket(s):
    """The verify.py reason bucket of one _structures() row: "verified" when the harness verified
    it, the verdict's own bucket when it did not, and NOT_CHECKED when no verdict reached us. The
    outcome string is the fallback so a record that carries only `outcomes` still buckets."""
    if s["verified"]:
        return "verified"
    vd = s.get("verdict")
    if vd is not None and vd["bucket"]:
        return vd["bucket"]
    o = s.get("outcome")
    if isinstance(o, str) and o and o not in ("not verified", "verified"):
        return o
    return NOT_CHECKED


def _params_order(params):
    """A structure's order from params.bit_order (one lane) or params.order (lanes), as verify.py
    reads it when structure["order"] is null; None when neither is a list of ids or lanes."""
    for key in ("bit_order", "order"):
        v = params.get(key)
        if not isinstance(v, list) or not v:
            continue
        if all(isinstance(x, list) for x in v):
            return v
        if not any(isinstance(x, (list, dict)) for x in v):
            return [v]
    return None


def _structures(T, result, verified=None, outcomes=None, verdicts=None):
    """Result structures restricted to the universe, plus bookkeeping. `verified`: the harness's
    verdict per result structure (position-aligned); `outcomes`: its outcome class, likewise;
    `verdicts`: the full per-structure verdict dicts (tools/s3/verify.py), likewise."""
    out, unmapped, unknown, shadow, empty, unscored = [], set(), set(), set(), 0, collections.Counter()
    dropped_by = []
    raw = result.get("structures") or []
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            empty += 1
            continue
        kind = canonical_kind(s.get("kind"))
        keep, drop = [], 0
        fl = s.get("flops") if isinstance(s.get("flops"), list) else []
        for f in fl:
            if not isinstance(f, str):
                f = str(f)
            if f in T.universe:
                keep.append(f)
            elif f in T.shadow_of:
                shadow.add(f)
            else:
                drop += 1
                (unmapped if f in T.unmapped else unknown).add(f)
        if kind not in STRUCTURE_KINDS:
            unscored[kind] += 1
        if drop:
            dropped_by.append({"structure": str(s.get("id", f"#{i}"))[:60], "dropped": drop, "kept": len(keep)})
        if not keep:
            empty += 1
            continue
        order = s.get("order") if isinstance(s.get("order"), list) and all(isinstance(x, list) for x in s["order"]) \
            else None
        vd = _verdict_view(verdicts[i]) if isinstance(verdicts, list) and i < len(verdicts) else None
        v = bool(verified[i]) if verified is not None and i < len(verified) else (bool(vd and vd["verified"]))
        proof = s.get("proof") if isinstance(s.get("proof"), dict) else {}
        params = s.get("params") if isinstance(s.get("params"), dict) else {}
        if not order:   # schema v2: the harness takes the order from params when "order" is null
            order = _params_order(params)
        out.append({"i": len(out), "pos": i, "id": str(s.get("id", f"#{i}")), "kind": kind,
                    "flops": frozenset(keep), "dropped": drop, "hkey": _hkey(keep),
                    "order": [[str(x) for x in lane] for lane in order] if order else None,
                    "params": params,
                    "lanes_unordered": kind in LANES_UNORDERED_KINDS and params.get("lanes_unordered") is True,
                    "claimed": proof.get("status") == "proven", "verified": v, "verdict": vd,
                    "outcome": _outcome(verified, outcomes, i, vd)})
    count = collections.Counter(f for s in out for f in s["flops"])
    info = {"structures": len(raw), "structures_scored": len(out),
            "structures_without_labelled_flops": empty, "structures_of_unscored_kinds": dict(unscored),
            "by_kind": dict(collections.Counter(s["kind"] for s in out)),
            "claimed_proven": sum(s["claimed"] for s in out), "verified": sum(s["verified"] for s in out),
            "verification": "harness (tools/s3/verify.py)" if (verified is not None or verdicts) else
                            "none: no netlist, nothing counts as verified",
            "outcomes": dict(collections.Counter(s["outcome"] for s in out).most_common()),
            "verdicts": sum(1 for s in out if s["verdict"] is not None),
            "buckets": dict(collections.Counter(_bucket(s) for s in out).most_common()),
            "lanes_unordered": sum(s["lanes_unordered"] for s in out),
            "flops_in_structures": len(count), "flops_in_several_structures": sum(1 for v in count.values() if v > 1),
            "dropped_flops": sum(x["dropped"] for x in dropped_by), "structures_with_dropped_flops": len(dropped_by),
            "dropped_examples": dropped_by[:20],
            "unmapped_flops_in_result": len(unmapped), "unknown_flops_in_result": len(unknown),
            "shadow_flops_in_result": len(shadow), "unknown_flop_examples": sorted(unknown)[:10]}
    return out, info


def _groups(T, result):
    groups, seen, dup = [], set(), 0
    for g in result.get("groups") or []:
        if not isinstance(g, list):
            continue
        keep = []
        for f in g:
            f = f if isinstance(f, str) else str(f)
            if f in T.universe:
                if f in seen:
                    dup += 1
                    continue
                seen.add(f)
                keep.append(f)
        if keep:
            groups.append(keep)
    return groups, dup


# ----------------------------------------------------------------------------------------------
# matching and class metrics


def _items(T, lenient):
    items = []
    for n in T.scored:
        if not lenient and n in T.chain_members:
            continue   # a per-stage synchronizer register: scored through its chain units
        items.append({"name": n, "unit": False, "flops": T.flops[n], "registers": [n],
                      "accepts": T.accepts[n] if lenient else frozenset({T.kind[n]}), "kind": T.kind[n]})
    for u in T.units:
        if lenient or u["chain"]:
            items.append({"name": u["name"], "unit": True, "flops": u["flops"], "registers": u["registers"],
                          "credit": u["credit"], "accepts": frozenset({u["kind"]}), "kind": u["kind"],
                          "params": u["params"], "chain": u["chain"]})
    return items


def _held(T, s, it):
    """Members of a unit item that structure s holds: more than half of the member's flops (and
    >= MULTI of them when it has >= MULTI)."""
    out = []
    for m in it["registers"]:
        fm = T.flops[m]
        h = len(s["flops"] & fm)
        if 2 * h > len(fm) and (len(fm) < MULTI or h >= MULTI):
            out.append(m)
    return out


def match(T, structs, items):
    """One-to-one IoU > 0.5 matching (see the module docstring). Returns
    [(structure, item, iou, registers taken)]; for a unit, the registers taken are its held members
    not taken before."""
    by_flop = collections.defaultdict(list)
    for j, it in enumerate(items):
        for f in it["flops"]:
            by_flop[f].append(j)
    cands = []
    for i, s in enumerate(structs):
        seen = set()
        for f in s["flops"]:
            for j in by_flop.get(f, ()):
                if j in seen:
                    continue
                seen.add(j)
                it = items[j]
                inter = len(s["flops"] & it["flops"])
                iou = inter / len(s["flops"] | it["flops"])
                if iou > IOU_MIN and (len(it["flops"]) < MULTI or inter >= MULTI):
                    cands.append((-iou, it["unit"], s["hkey"], s["pos"], it["name"], i, j))
    cands.sort()
    used_s, used_r, out = set(), set(), []
    for negiou, _u, _h, _p, _n, i, j in cands:
        it = items[j]
        if i in used_s:
            continue
        if it["unit"]:
            regs = [m for m in _held(T, structs[i], it) if m not in used_r]
            if not regs:
                continue
        else:
            if it["name"] in used_r:
                continue
            regs = [it["name"]]
        used_s.add(i)
        used_r.update(regs)
        out.append((structs[i], it, -negiou, regs))
    return out


def _prf(tp, npred, nsup, tp_recall=None):
    """Precision tp/npred, recall tp_recall/nsup (tp_recall defaults to tp), F1; None where a
    denominator is 0; F1 is None only when there is neither support nor a prediction."""
    tp_recall = tp if tp_recall is None else tp_recall
    p = tp / npred if npred else None
    r = tp_recall / nsup if nsup else None
    if not npred and not nsup:
        f1 = None
    else:
        pp, rr = p or 0.0, r or 0.0
        f1 = 2 * pp * rr / (pp + rr) if pp + rr else 0.0
    return p, r, f1


def _macro(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _register_level(T, structs, lenient):
    items = _items(T, lenient)
    m = match(T, structs, items)
    credit = {}          # register -> {"exact", "iou", "structure", "via"}
    ok_struct = {}       # structure index -> (found, exact, iou)
    for s, it, iou, regs in m:
        ok = s["kind"] in it["accepts"]
        ex = ok and s["flops"] == it["flops"] and not s["dropped"]
        got = [r for r in regs if r in it["credit"]] if it["unit"] else regs
        ok = ok and bool(got)
        ok_struct[s["i"]] = (ok, ex and ok, iou)
        if ok:
            for r in got:
                credit[r] = {"exact": ex, "iou": iou, "structure": s["id"], "via": it["name"] if it["unit"] else None}
    per = {}
    tot = collections.Counter()
    for c in STRUCTURE_KINDS:
        sk = [s for s in structs if s["kind"] == c]
        tp_f = sum(1 for s in sk if ok_struct.get(s["i"], (False,))[0])
        tp_e = sum(1 for s in sk if ok_struct.get(s["i"], (False, False))[1])
        den = T.denominators(c, lenient)
        fnd = [n for n in den if n in credit]
        exa = [n for n in den if n in credit and credit[n]["exact"]]
        hi = [n for n in den if n in credit and credit[n]["iou"] >= IOU_HIGH]
        pf, rf, f1 = _prf(tp_f, len(sk), len(den), len(fnd))
        pe, re_, f1e = _prf(tp_e, len(sk), len(den), len(exa))
        exc = T.excused(c) if lenient else []
        designs = collections.defaultdict(list)
        for n in den:
            designs[T.design_key(n)].append(n)
        per[c] = {
            "structures": len(sk), "registers": len(den), "small_support": len(den) < SMALL_SUPPORT,
            "outcomes": dict(collections.Counter(s["outcome"] for s in sk).most_common()),
            "unknown": sum(1 for s in sk if s["outcome"] == "unknown"),
            "found": {"structures_matched": tp_f, "registers_found": len(fnd), "precision": pf, "recall": rf, "f1": f1},
            "exact": {"structures_matched": tp_e, "registers_found": len(exa), "precision": pe, "recall": re_,
                      "f1": f1e},
            "found_iou75": {"registers_found": len(hi), "recall": len(hi) / len(den) if den else None},
            "mean_iou_found": (sum(credit[n]["iou"] for n in fnd) / len(fnd)) if fnd else None,
            "excused": {"registers": len(exc), "found": sum(1 for n in exc if n in credit),
                        "recall_without_excused": ((len(fnd) - sum(1 for n in exc if n in credit)) / (len(den) - len(exc))
                                                   if len(den) > len(exc) else None)},
            "distinct_designs": {
                "total": len(designs),
                "found_all": sum(all(n in credit for n in v) for v in designs.values()),
                "found_any": sum(any(n in credit for n in v) for v in designs.values()),
                "exact_all": sum(all(n in credit and credit[n]["exact"] for n in v) for v in designs.values()),
                "exact_any": sum(any(n in credit and credit[n]["exact"] for n in v) for v in designs.values())},
            "missed": sorted(n for n in den if n not in credit)[:40],
            "found_registers": sorted(fnd)[:40],
            "via_units": sorted({credit[n]["via"] for n in fnd if credit[n]["via"]})[:20]}
        tot.update(structures=len(sk), tp_f=tp_f, tp_e=tp_e, den=len(den), fnd=len(fnd), exa=len(exa))
    # register-level confusion: truth class of the matched item x structure class
    conf = collections.Counter()
    for s, it, _iou, _regs in m:
        conf[(CLASS_MAP.get(it["kind"], NONE), s["kind"])] += 1
    matched = {s["i"] for s, _it, _iou, _r in m}
    for s in structs:
        if s["kind"] in STRUCTURE_KINDS and s["i"] not in matched:
            conf[("unmatched", s["kind"])] += 1
    micro_f = _prf(tot["tp_f"], tot["structures"], tot["den"], tot["fnd"])
    micro_e = _prf(tot["tp_e"], tot["structures"], tot["den"], tot["exa"])
    out = {"per_kind": per, "matches": len(m),
           "unit_matches": sorted({it["name"] for s, it, _i, r in m if it["unit"] and s["kind"] in it["accepts"]}),
           "confusion": {f"{a}->{b}": v for (a, b), v in sorted(conf.items())},
           "macro_f1": _macro([per[c]["found"]["f1"] for c in STRUCTURE_KINDS]),
           "macro_f1_exact": _macro([per[c]["exact"]["f1"] for c in STRUCTURE_KINDS]),
           "micro": {"found": dict(zip(("precision", "recall", "f1"), micro_f)),
                     "exact": dict(zip(("precision", "recall", "f1"), micro_e))},
           "micro_f1": micro_f[2], "micro_f1_exact": micro_e[2]}
    if lenient:
        out["excused_registers"] = sorted(n for c in STRUCTURE_KINDS for n in T.excused(c))
    return out, m


def _bit_level(T, structs):
    pred = collections.defaultdict(set)   # flop -> predicted structure kinds
    for s in structs:
        if s["kind"] in STRUCTURE_KINDS:
            for f in s["flops"]:
                pred[f].add(s["kind"])
    lacc = T.lenient_accepts
    strict, lenient = {}, {}
    tot = {m: collections.Counter() for m in ("strict", "lenient")}
    for c in STRUCTURE_KINDS:
        pc = [f for f, ks in pred.items() if c in ks]
        tc = set().union(*(T.flops[n] for n in T.denominators(c)))
        for mode, ok_of, out in (("strict", T.strict_kinds, strict), ("lenient", lambda f: lacc.get(f, set()), lenient)):
            right = {f for f in pc if pred[f] <= ok_of(f)}
            tp_p = len(right)
            tp_r = len(right & tc)
            p, r, f1 = _prf(tp_p, len(pc), len(tc), tp_r)
            out[c] = {"predicted": len(pc), "support": len(tc), "right": tp_p,
                      "several": sum(1 for f in pc if len(pred[f]) > 1), "precision": p, "recall": r, "f1": f1}
            tot[mode].update(pred=len(pc), sup=len(tc), tp_p=tp_p, tp_r=tp_r)
    conf = collections.Counter()
    for f in T.universe:
        t = CLASS_MAP.get(T.kind[T.primary[f]], NONE)
        ks = pred.get(f, set())
        conf[(t, next(iter(ks)) if len(ks) == 1 else (NONE if not ks else SEVERAL))] += 1
    micro = {m: _prf(tot[m]["tp_p"], tot[m]["pred"], tot[m]["sup"], tot[m]["tp_r"]) for m in tot}
    return {"strict": strict, "lenient": lenient,
            "macro_f1": _macro([strict[c]["f1"] for c in STRUCTURE_KINDS]),
            "macro_f1_lenient": _macro([lenient[c]["f1"] for c in STRUCTURE_KINDS]),
            "micro_f1": micro["strict"][2], "micro_f1_lenient": micro["lenient"][2],
            "flops_several": sum(1 for ks in pred.values() if len(ks) > 1),
            "confusion": {f"{a}->{b}": v for (a, b), v in sorted(conf.items())}}


# ----------------------------------------------------------------------------------------------
# order


def mahonian(m):
    """P(a uniformly random permutation of m items has k inversions), k = 0 .. m(m-1)/2."""
    d = np.ones(1)
    for k in range(2, m + 1):
        d = np.convolve(d, np.ones(k) / k)
    return d


def _best_expect(dist):
    """E[max(K, N-K)] for K distributed as `dist` over 0..N."""
    n = len(dist) - 1
    k = np.arange(n + 1)
    return float(np.sum(dist * np.maximum(k, n - k)))


def reference(T, item):
    """How the truth orders an item's flops: (mode, {flop: (lane, stage)}) with mode "lanes" (params
    `order`, stage 0 first), "bit_order" (one lane, LSB first) or "index" (one lane, RTL bit index;
    registers only). None for a unit without an explicit order. Positions are unique: a flop at an
    already taken (lane, stage) is left unordered."""
    params = item["params"] if item["unit"] else (T.regs[item["name"]].get("params") or {})
    for key in ("order", "bit_order"):
        v = params.get(key)
        if isinstance(v, list) and v:
            lanes = v if all(isinstance(x, list) for x in v if x is not None) else [v]
            pos, taken = {}, set()
            for li, lane in enumerate(lanes):
                if not isinstance(lane, list):
                    continue
                for si, f in enumerate(lane):
                    if isinstance(f, str) and f in T.universe and f not in pos and (li, si) not in taken:
                        pos[f] = (li, si)
                        taken.add((li, si))
            if len(pos) >= 2:
                return ("lanes" if key == "order" else "bit_order", pos)
    if item["unit"]:
        return None
    pos, taken = {}, set()
    for f, i in sorted(T.idx[item["name"]].items(), key=lambda x: (x[1], x[0])):
        if i not in taken:
            pos[f] = (0, i)
            taken.add(i)
    return ("index", pos)


def _pairs_total(pos, flops):
    """Numbers of truth-ordered pairs among `flops`: (within, across)."""
    fl = [f for f in flops if f in pos]
    by_lane = collections.Counter(pos[f][0] for f in fl)
    by_stage = collections.Counter(pos[f][1] for f in fl)
    c2 = lambda x: x * (x - 1) // 2  # noqa: E731
    within = sum(c2(v) for v in by_lane.values())
    across = sum(c2(v) for v in by_stage.values()) - sum(c2(v) for v in collections.Counter(pos[f] for f in fl).values())
    return within, across


def _sign_counts(truth_key, result_key):
    """Concordant and discordant pairs between two orderings of one group (numpy, O(k^2))."""
    t = np.asarray(truth_key)
    r = np.asarray(result_key)
    if len(t) < 2:
        return 0, 0
    st = np.sign(t[:, None] - t[None, :])
    sr = np.sign(r[:, None] - r[None, :])
    prod = np.triu(st * sr, 1)
    return int(np.sum(prod > 0)), int(np.sum(prod < 0))


def order_counts(order, pos, flops, reversible, rng, lanes_unordered=False):
    """Score one (structure, truth reference) pair: {"within": part, "across": part, "all": part}
    with part = {pairs, asserted, concordant, discordant, score, coverage, chance, kappa}. With
    lanes_unordered the across part is None (not scored) and "across_unscored_pairs" counts the
    truth's across pairs among `flops`."""
    rpos = {}
    for li, lane in enumerate(order or []):
        for si, f in enumerate(lane):
            if f in flops and f in pos and f not in rpos:
                rpos[f] = (li, si)
    n_within, n_across = _pairs_total(pos, flops)
    # within: groups (truth lane, result lane); asserted pairs are the pairs inside a group
    wg = collections.defaultdict(list)
    for f, (rl, rs) in rpos.items():
        wg[(pos[f][0], rl)].append((pos[f][1], rs))
    cw = dw = 0
    wdist = np.ones(1)
    for grp in wg.values():
        c, d = _sign_counts([g[0] for g in grp], [g[1] for g in grp])
        cw, dw = cw + c, dw + d
        if len(grp) >= 2:
            wdist = np.convolve(wdist, mahonian(len(grp)))
    # across: groups (truth stage, result position); asserted pairs: different truth lanes and
    # different result lanes inside a group
    ag = collections.defaultdict(list)
    for f, (rl, rs) in rpos.items():
        ag[(pos[f][1], rs)].append((pos[f][0], rl))
    lane_pairs = collections.Counter()      # (i, j) result lanes, i < j -> [c_ij, d_ij]
    ca = da = 0
    for grp in ag.values():
        for (ta, ra), (tb, rb) in itertools.combinations(grp, 2):
            if ta == tb or ra == rb:
                continue
            i, j, agree = (ra, rb, ta < tb) if ra < rb else (rb, ra, tb < ta)
            lane_pairs[(i, j, agree)] += 1
            ca, da = ca + agree, da + (not agree)
    out = {"across_unscored_pairs": n_across if lanes_unordered else 0}
    for part, n, c, d in (("within", n_within, cw, dw), ("across", n_across, ca, da)):
        if not n or (part == "across" and lanes_unordered):
            out[part] = None
            continue
        a = c + d
        best = max(c, d) if reversible else c
        if not a:
            chance_best = 0.0
        elif not reversible:
            chance_best = a / 2
        elif part == "within":
            chance_best = _best_expect(wdist) if len(wdist) - 1 == a else _mc_within(wg, a, rng)
        else:
            chance_best = _chance_across(lane_pairs, a, rng)
        out[part] = _part(n, c, d, best, chance_best)
        out[part]["truth_direction"] = c >= d
    parts = [p for p in (out["within"], out["across"]) if p]
    if parts:
        n = sum(p["pairs"] for p in parts)
        num = sum(p["_num"] for p in parts)
        ch = sum(p["_chance_num"] for p in parts)
        out["all"] = _finish(n, sum(p["asserted"] for p in parts), num, ch)
    else:
        out["all"] = None
    for p in (out["within"], out["across"]):
        if p:
            p.pop("_num")
            p.pop("_chance_num")
    return out


def _part(n, c, d, best, chance_best):
    u = n - c - d
    p = _finish(n, c + d, best + u / 2, chance_best + u / 2)
    p.update(concordant=c, discordant=d, _num=best + u / 2, _chance_num=chance_best + u / 2)
    return p


def _finish(n, asserted, num, chance_num):
    score, chance = num / n, chance_num / n
    return {"pairs": n, "asserted": asserted, "coverage": asserted / n, "score": score, "chance": chance,
            "kappa": (score - chance) / (1 - chance) if chance < 1 - 1e-12 else None}


def _mc_within(groups, a, rng):
    """Fallback (a group with tied truth stages): E[max(C, D)] by seeded Monte Carlo."""
    tot = 0.0
    for _ in range(MC_DRAWS):
        c = d = 0
        for grp in groups.values():
            rs = [g[1] for g in grp]
            rng.shuffle(rs)
            x, y = _sign_counts([g[0] for g in grp], rs)
            c, d = c + x, d + y
        tot += max(c, d)
    return tot / MC_DRAWS


def _chance_across(lane_pairs, a, rng):
    """E[max(C, D)] over uniformly random orders of the result's lanes: exact when the involved
    lanes have at most EXACT_ENUM_MAX orders, else seeded Monte Carlo (MC_DRAWS draws)."""
    lanes = sorted({x for i, j, _g in lane_pairs for x in (i, j)})
    idx = {x: k for k, x in enumerate(lanes)}
    items = sorted(lane_pairs.items())
    I = np.array([idx[i] for (i, _j, _g), _v in items])
    J = np.array([idx[j] for (_i, j, _g), _v in items])
    G = np.array([g for (_i, _j, g), _v in items], dtype=bool)
    V = np.array([v for _k, v in items], dtype=np.int64)
    n = len(lanes)
    if math.factorial(n) <= EXACT_ENUM_MAX:
        perms = np.array(list(itertools.permutations(range(n))), dtype=np.int32).reshape(-1, n)
    else:
        perms = np.array([rng.sample(range(n), n) for _ in range(MC_DRAWS)], dtype=np.int32)
    tot = 0.0
    step = max(1, 4_000_000 // max(1, len(V)))   # bound the (orders x terms) block in memory
    for k in range(0, len(perms), step):
        p = perms[k:k + step]
        c = (((p[:, I] < p[:, J]) == G) * V).sum(axis=1)
        tot += float(np.maximum(c, a - c).sum())
    return tot / len(perms)


def _order(T, matches):
    rng = random.Random(SEED)
    rows = []
    for s, it, _iou, regs in matches:
        if s["kind"] not in it["accepts"]:
            continue
        refs = []
        ref = reference(T, it)
        if ref is not None:   # a register, or a unit with its own order
            refs.append((it["name"], it["kind"], len(it["flops"]), ref))
        else:                 # a unit without one: each held member by its own reference
            for r in regs:
                refs.append((r, T.kind[r], len(T.flops[r]), reference(T, {"unit": False, "name": r, "params": None})))
        for label, kind, size, (mode, pos) in refs:
            shared = [f for f in s["flops"] if f in pos]
            if len(shared) < 2:
                continue
            res = order_counts(s["order"], pos, set(shared), kind in REVERSIBLE, rng,
                               lanes_unordered=s["lanes_unordered"])
            parts = [res[p] for p in ("within", "across") if res[p]]
            row = {"item": label, "kind": kind, "flops": size, "structure": s["id"], "reference": mode,
                   "asserts_order": bool(s["order"]), "shared": len(shared),
                   "lanes_unordered": s["lanes_unordered"], **res}
            row["ordered"] = bool(parts) and all(p["coverage"] >= ORDER_COVERAGE_MIN for p in parts)
            row["all_correct"] = bool(parts) and all(p["score"] == 1.0 and p["coverage"] == 1.0 for p in parts) \
                and res["all"]["chance"] < 1 - 1e-12
            rows.append(row)
    summary = {}
    for kind in KINDS:
        for band, test in (("width<=2", lambda n: n <= 2), ("width>=3", lambda n: n >= 3)):
            sel = [x for x in rows if x["kind"] == kind and test(x["flops"])]
            if not sel:
                continue
            ent = {"pairs_found": len(sel), "ordered": sum(x["ordered"] for x in sel),
                   "all_correct": sum(x["all_correct"] for x in sel),
                   "chance_one": sum(1 for x in sel if x["all"] and x["all"]["chance"] >= 1 - 1e-12),
                   "lanes_unordered": sum(1 for x in sel if x["lanes_unordered"]),
                   "across_unscored_pairs": sum(x["across_unscored_pairs"] for x in sel)}
            for part in ("within", "across", "all"):
                sc = [x[part] for x in sel if x.get(part)]
                if not sc:
                    continue
                n = sum(y["pairs"] for y in sc)
                num = sum(y["score"] * y["pairs"] for y in sc)
                ch = sum(y["chance"] * y["pairs"] for y in sc)
                e = _finish(n, sum(y["asserted"] for y in sc), num, ch)
                e.update(registers=len(sc), mean_score=sum(y["score"] for y in sc) / len(sc))
                ent[part] = e
            summary.setdefault(kind, {})[band] = ent
    return {"per_register": rows, "summary": summary}


# ----------------------------------------------------------------------------------------------
# parameters


def _norm(v):
    if isinstance(v, str):
        return v.strip().casefold()
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _norm(x) for k, x in v.items()}
    return v


def _as_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v.strip(), 0)
        except ValueError:
            return None
    return None


def _serial_key(v):
    """A serial input as a truth writes it ({rtl, flop}, {port} or "port:<name>") or as a result may
    (a flop's join key, or null / "input" for a pin or logic): the flop's join key, else "input"."""
    if isinstance(v, dict):
        return v.get("flop") or "input"
    if not isinstance(v, str) or v in ("", "input", "port", "pi") or v.startswith(("port:", "pi:")):
        return "input"
    return v


def _lfsr_forms(v):
    """The companion readings a form value stands for: "both" -> {fibonacci, galois}, else itself."""
    v = _norm(v)
    if v == LFSR_FORM_BOTH:
        return frozenset(LFSR_FORM_READINGS)
    return frozenset({v if isinstance(v, str) else json.dumps(v, sort_keys=True)})


def param_equal(name, truth_v, result_v):
    if result_v is None:
        return False
    if name == "form" and LFSR_FORM_BOTH in (_norm(truth_v), _norm(result_v)):
        return bool(_lfsr_forms(truth_v) & _lfsr_forms(result_v))
    if name == "serial_in":   # per lane; lane order is scored by concordance, so compare as multisets
        tv = truth_v if isinstance(truth_v, list) else [truth_v]
        rv = result_v if isinstance(result_v, list) else [result_v]
        return collections.Counter(map(_serial_key, tv)) == collections.Counter(map(_serial_key, rv))
    if name == "poly":
        a, b = _as_int(truth_v), _as_int(result_v)
        if a is not None and b is not None:
            if a == b:
                return True
            w = a.bit_length()  # the reciprocal polynomial: the same coefficients read the other way
            return b.bit_length() <= w and a == int(format(b, f"0{w}b")[::-1], 2)
    return json.dumps(_norm(truth_v), sort_keys=True) == json.dumps(_norm(result_v), sort_keys=True)


def _pkey(v):
    return json.dumps(_norm(v), sort_keys=True)


def _truth_values(T):
    """{"kind.param": [truth values over the design's registers and units of the kind]}."""
    vals = collections.defaultdict(list)
    for r in T.scored:
        k = T.kind[r]
        if k in PARAMS:
            for p, v in (T.regs[r].get("params") or {}).items():
                if v is not None and _scored_param(k, p):
                    vals[f"{k}.{p}"].append(v)
    for u in T.units:
        k = u["kind"]
        if k in PARAMS:
            for p, v in u["params"].items():
                if v is not None and _scored_param(k, p):
                    vals[f"{k}.{p}"].append(v)
    return vals


def _scored_param(kind, p):
    return (p in PARAMS[kind] and p not in ORDER_PARAMS and p not in ORDER_DIRECTIVES
            and (kind, p) not in UNSCORED_PARAMS)


def _split(n, c):
    return {"compared": n, "correct": c, "accuracy": (c / n) if n else None}


def _params(T, matches):
    """Every compared parameter, and the same numbers split into what the harness CERTIFIED and what
    it only TRANSCRIBED (PARAMS_CERTIFIED_RULE). Without verdicts nothing is certified, so the
    certified column is empty and the transcribed column carries everything -- which is the honest
    reading of a run that verified nothing."""
    pairs = collections.defaultdict(list)   # "kind.param" -> [(truth value, result value, item, certified)]
    for s, it, _iou, _regs in matches:
        k = it["kind"]
        if s["kind"] != k or k not in PARAMS:
            continue
        tp = it["params"] if it["unit"] else (T.regs[it["name"]].get("params") or {})
        for p in PARAMS[k]:
            if not _scored_param(k, p) or tp.get(p) is None:
                continue
            pairs[f"{k}.{p}"].append((tp[p], s["params"].get(p), it["name"], certified_param(s, p)))
    tvals = _truth_values(T)
    per, wrong = {}, []
    tot = collections.Counter()
    for key, lst in sorted(pairs.items()):
        p = key.split(".", 1)[1]
        ok = [param_equal(p, tv, rv) for tv, rv, _n, _cert in lst]
        counts = collections.Counter(_pkey(tv) for tv, _rv, _n, _cert in lst)
        maj_key = min(counts, key=lambda x: (-counts[x], x))
        maj = json.loads(maj_key)
        base = sum(param_equal(p, tv, maj) for tv, _rv, _n, _cert in lst)
        n, c = len(lst), sum(ok)
        cn = sum(1 for row in lst if row[3])
        cc = sum(1 for row, good in zip(lst, ok) if row[3] and good)
        acc, bacc = c / n, base / n
        informative = len({_pkey(v) for v in tvals.get(key, [])}) >= 2
        per[key] = {"n": n, "correct": c, "accuracy": acc, "majority_value": maj, "majority_correct": base,
                    "majority_accuracy": bacc, "kappa": (acc - bacc) / (1 - bacc) if bacc < 1 else None,
                    "informative": informative,
                    "certified": _split(cn, cc), "transcribed": _split(n - cn, c - cc)}
        tot.update(n=n, c=c, b=base, cn=cn, cc=cc)
        if informative:
            tot.update(ni=n, ci=c, bi=base)
        for (tv, rv, name, cert), good in zip(lst, ok):
            if not good and len(wrong) < 40:
                wrong.append({"item": name, "param": key, "truth": tv, "result": rv, "certified": cert})
    known = {k: len(v) for k, v in sorted(tvals.items())}
    hedges = [(tv, rv) for tv, rv, _n, _cert in pairs.get("lfsr_crc.form", [])
              if _norm(rv) == LFSR_FORM_BOTH and _norm(tv) in LFSR_FORM_READINGS]
    acc = tot["c"] / tot["n"] if tot["n"] else None
    bacc = tot["b"] / tot["n"] if tot["n"] else None
    iacc = tot["ci"] / tot["ni"] if tot["ni"] else None
    ibacc = tot["bi"] / tot["ni"] if tot["ni"] else None
    return {"compared": tot["n"], "correct": tot["c"], "accuracy": acc, "majority_accuracy": bacc,
            "kappa": (acc - bacc) / (1 - bacc) if acc is not None and bacc < 1 else None,
            "informative": {"compared": tot["ni"], "correct": tot["ci"], "accuracy": iacc, "majority_accuracy": ibacc,
                            "kappa": (iacc - ibacc) / (1 - ibacc) if iacc is not None and ibacc < 1 else None,
                            "params": sorted(k for k, v in per.items() if v["informative"])},
            "certified": dict(_split(tot["cn"], tot["cc"]),
                              params=sorted(k for k, v in per.items() if v["certified"]["compared"])),
            "transcribed": dict(_split(tot["n"] - tot["cn"], tot["c"] - tot["cc"]),
                                params=sorted(k for k, v in per.items() if v["transcribed"]["compared"])),
            "certification_rule": PARAMS_CERTIFIED_RULE,
            "per_param": per, "known_in_truth": known,
            "unscored": {f"{k}.{p}": why for (k, p), why in UNSCORED_PARAMS.items()}, "wrong": wrong,
            "form_both_answers": len(hedges)}


# ----------------------------------------------------------------------------------------------
# grouping: contingency-table measures (numpy only; neither scipy nor sklearn is installed)


def _labels(a):
    _u, inv = np.unique(np.asarray(a), return_inverse=True)
    return inv.ravel()


def contingency(a, b):
    """(n_ij counts of nonzero cells, row sums, column sums, N) for two label arrays."""
    a, b = _labels(a), _labels(b)
    nb = int(b.max()) + 1 if len(b) else 1
    _codes, n_ij = np.unique(a.astype(np.int64) * nb + b, return_counts=True)
    return n_ij, np.bincount(a), np.bincount(b), len(a)


def _entropy(sizes, n):
    p = sizes[sizes > 0] / n
    return float(-np.sum(p * np.log(p)))


def _cells(a, b):
    """Nonzero contingency cells: (row index, column index, count) arrays."""
    a, b = _labels(a), _labels(b)
    nb = int(b.max()) + 1
    codes, cnt = np.unique(a.astype(np.int64) * nb + b, return_counts=True)
    return codes // nb, codes % nb, cnt


def mutual_info(a, b):
    """MI (nats) = sum over nonzero cells n_ij/N log(N n_ij / (a_i b_j))."""
    ri, cj, cnt = _cells(a, b)
    rows, cols, n = np.bincount(_labels(a)), np.bincount(_labels(b)), len(a)
    return float(np.sum(cnt / n * (np.log(n * cnt) - np.log(rows[ri].astype(float) * cols[cj]))))


def expected_mi(rows, cols, n):
    """E[MI] under the permutation model with fixed marginals (Vinh, Epps and Bailey 2010, eq. 24a):
    sum_i sum_j sum_nij (nij/N) log(N nij / (a_i b_j)) * hypergeometric(nij; a_i, b_j, N).
    Rows and columns of equal size are merged (their terms are identical)."""
    lf = np.concatenate(([0.0], np.cumsum(np.log(np.arange(1, n + 1)))))  # log k!
    ra, rc = np.unique(rows[rows > 0], return_counts=True)
    ca, cc = np.unique(cols[cols > 0], return_counts=True)
    emi = 0.0
    for a, ma in zip(ra.tolist(), rc.tolist()):
        for b, mb in zip(ca.tolist(), cc.tolist()):
            lo, hi = max(1, a + b - n), min(a, b)
            if lo > hi:
                continue
            k = np.arange(lo, hi + 1)
            logp = (lf[a] + lf[b] + lf[n - a] + lf[n - b] - lf[n] - lf[k] - lf[a - k] - lf[b - k] - lf[n - a - b + k])
            emi += ma * mb * float(np.sum(k / n * (np.log(n * k) - math.log(a * b)) * np.exp(logp)))
    return emi


def _comb2(x):
    x = np.asarray(x, dtype=object)
    return int(sum(int(v) * (int(v) - 1) // 2 for v in x))


def partition_scores(a, b):
    """AMI (arithmetic), ARI, NMI (arithmetic) and pair/purity measures of label arrays a (truth)
    and b (prediction) over the same items."""
    a, b = np.asarray(a), np.asarray(b)
    n = len(a)
    n_ij, rows, cols, _ = contingency(a, b)
    hu, hv = _entropy(rows, n), _entropy(cols, n)
    mi = mutual_info(a, b)
    same = len(rows) == len(cols) == len(n_ij)  # identical partitions (up to relabelling)
    if same or (len(rows) == len(cols) and len(rows) in (1, n)):
        ami = nmi = 1.0 if same else 0.0
        emi = mi if same else expected_mi(rows, cols, n)
    else:
        emi = expected_mi(rows, cols, n)
        norm = (hu + hv) / 2
        den = norm - emi
        den = min(den, -np.finfo(float).eps) if den < 0 else max(den, np.finfo(float).eps)
        ami = (mi - emi) / den
        nmi = mi / norm if norm > 0 else 1.0
    s_ij, s_a, s_b, tot = _comb2(n_ij), _comb2(rows), _comb2(cols), n * (n - 1) // 2
    exp_ = s_a * s_b / tot if tot else 0.0
    mx = (s_a + s_b) / 2
    ari = 1.0 if same or mx == exp_ else (s_ij - exp_) / (mx - exp_)
    pp = s_ij / s_b if s_b else None
    pr = s_ij / s_a if s_a else None
    pf = 2 * pp * pr / (pp + pr) if pp and pr else 0.0
    # purity: per predicted block its largest truth share; inverse: per truth block its largest predicted share
    ri, cj, cnt = _cells(a, b)
    best_col = np.zeros(len(cols), dtype=np.int64)
    np.maximum.at(best_col, cj, cnt)
    best_row = np.zeros(len(rows), dtype=np.int64)
    np.maximum.at(best_row, ri, cnt)
    return {"ami": float(ami), "ari": float(ari), "nmi": float(nmi), "mi": mi, "expected_mi": emi,
            "h_truth": hu, "h_pred": hv, "pair_precision": pp, "pair_recall": pr, "pair_f1": pf,
            "purity": float(best_col.sum() / n), "inverse_purity": float(best_row.sum() / n),
            "truth_blocks": int(len(rows)), "pred_blocks": int(len(cols)), "n": int(n)}


def _grouping_block(T, groups, flops):
    flops = sorted(flops)
    pos = {f: i for i, f in enumerate(flops)}
    tl = [T.primary[f] for f in flops]
    pl = [None] * len(flops)
    for gi, g in enumerate(groups):
        for f in g:
            if f in pos:
                pl[pos[f]] = f"g{gi}"
    pl = [x if x is not None else f"s:{f}" for x, f in zip(pl, flops)]
    out = partition_scores(np.array(tl), np.array(pl))
    tb = collections.defaultdict(set)
    pb = collections.defaultdict(set)
    for f, x, y in zip(flops, tl, pl):
        tb[x].add(f)
        pb[y].add(f)
    pblocks = {frozenset(v) for v in pb.values()}
    multi = {x: v for x, v in tb.items() if len(v) >= 2}
    out["exact_words"] = sum(1 for v in multi.values() if frozenset(v) in pblocks)
    out["truth_words_multi"] = len(multi)
    out["exact_word_recall"] = out["exact_words"] / len(multi) if multi else None
    # lenient: a word also counts when a declared unit holding its register is a predicted group,
    # or when the single-register units of its register (per-slice splits) are all predicted groups
    fset = set(flops)
    lenient = 0
    for x, v in multi.items():
        units = [u for u in T.units if x in u["registers"] and u["flops"] <= fset]
        slices = [u["flops"] for u in units if u["registers"] == [x]]
        if (frozenset(v) in pblocks or any(u["flops"] in pblocks for u in units)
                or (slices and frozenset().union(*slices) >= frozenset(v) and all(sl in pblocks for sl in slices))):
            lenient += 1
    out["exact_words_lenient"] = lenient
    out["exact_word_recall_lenient"] = lenient / len(multi) if multi else None
    p_of = dict(zip(flops, pl))
    t_of = dict(zip(flops, tl))
    out["splits"] = sum(1 for v in tb.values() if len({p_of[f] for f in v}) > 1)
    out["merges"] = sum(1 for v in pb.values() if len({t_of[f] for f in v}) > 1)
    return out


def _random_blocks(T, flops, draws, seed):
    flops = sorted(flops)
    sizes = sorted(collections.Counter(T.primary[f] for f in flops).values(), reverse=True)
    rng = random.Random(seed)
    res = []
    for _ in range(draws):
        sh = rng.sample(flops, len(flops))
        gs, i = [], 0
        for s in sizes:
            gs.append(sh[i:i + s])
            i += s
        res.append(_grouping_block(T, gs, flops))
    keys = ("ami", "ari", "nmi", "pair_f1", "exact_word_recall")
    return {k: {"mean": float(np.mean([r[k] or 0 for r in res])), "min": float(min(r[k] or 0 for r in res)),
                "max": float(max(r[k] or 0 for r in res))} for k in keys} | {"draws": draws, "seed": seed}


def _grouping(T, groups, draws=RANDOM_BLOCK_DRAWS, baselines=True):
    sizes = collections.Counter(T.primary[f] for f in T.universe)
    multi = frozenset(f for f in T.universe if sizes[T.primary[f]] >= 2)
    out = {}
    for name, fl in (("all_flops", T.universe), ("multi_flop_registers", multi)):
        if not fl:   # e.g. a design without multi-flop registers: nothing to measure (was a crash)
            out[name] = {"n": 0, "empty": True}
            continue
        blk = _grouping_block(T, groups, fl)
        if baselines:
            blk["baseline_singletons"] = {k: v for k, v in _grouping_block(T, [], fl).items()
                                          if k in ("ami", "ari", "nmi", "pair_f1", "exact_word_recall")}
            blk["baseline_random_blocks"] = _random_blocks(T, fl, draws, SEED)
        out[name] = blk
    return out


# ----------------------------------------------------------------------------------------------
# baselines and the report


def majority_kind(T):
    sup = {c: len(set().union(*(T.flops[n] for n in T.scored if T.kind[n] == c))) for c in STRUCTURE_KINDS}
    return max(STRUCTURE_KINDS, key=lambda c: (sup[c], -STRUCTURE_KINDS.index(c)))


def majority_result(T):
    """Every flop its own structure, labelled with the structure kind that owns the most truth flops."""
    k = majority_kind(T)
    return {"schema": schema.RESULT_SCHEMA, "groups": [],
            "structures": [{"id": f"m{i}", "kind": k, "flops": [f], "order": None, "params": {}, "control": {},
                            "proof": {"status": "not_attempted"}} for i, f in enumerate(sorted(T.universe))],
            "meta": {"baseline": "majority_class", "kind": k}}


def _stats(xs):
    """n / mean / max / min of a list of numbers (None where there is nothing to average)."""
    xs = [float(x) for x in xs if isinstance(x, (int, float)) and not isinstance(x, bool)]
    if not xs:
        return {"n": 0, "mean": None, "max": None, "min": None}
    return {"n": len(xs), "mean": sum(xs) / len(xs), "max": max(xs), "min": min(xs)}


def _honesty(T, structs, classes):
    """FOUND beside VERIFIED, with the reason bucket of every unverified structure, and what the
    verified count is worth (vacuous holds, the state space the opaque load cases hide, dead bits,
    unchecked params). This block exists because "verified" is the number a reader quotes: the lead's
    decision of 2026-09-23 is that found and verified are reported separately EVERYWHERE, with the
    reason, rather than by widening the contract until the two agree."""
    all_strict = classes["all"]["registers"]["strict"]["per_kind"]
    ver_strict = classes["verified"]["registers"]["strict"]["per_kind"]
    ver = [s for s in structs if s["verified"]]
    with_verdict = [s for s in ver if s["verdict"] is not None]
    per, buckets = {}, collections.Counter()
    for k in STRUCTURE_KINDS:
        sk = [s for s in structs if s["kind"] == k]
        bad = collections.Counter(_bucket(s) for s in sk if not s["verified"])
        buckets.update(bad)
        a, v = all_strict[k], ver_strict[k]
        per[k] = {"registers": a["registers"],
                  "structures": len(sk), "verified_structures": sum(1 for s in sk if s["verified"]),
                  "unverified_structures": sum(1 for s in sk if not s["verified"]),
                  "found_registers": a["found"]["registers_found"], "found_recall": a["found"]["recall"],
                  "verified_found_registers": v["found"]["registers_found"],
                  "verified_found_recall": v["found"]["recall"],
                  "found_not_verified_registers": max(0, a["found"]["registers_found"] - v["found"]["registers_found"]),
                  # matching is kind-agnostic, so an unverified structure of the WRONG kind can take a
                  # register in the all-structures pass that the verified-only pass then credits to a
                  # verified structure: the two credit sets are not nested and this is the difference
                  # the other way, reported rather than clamped away
                  "verified_not_found_registers": max(0, v["found"]["registers_found"] - a["found"]["registers_found"]),
                  "exact_recall": a["exact"]["recall"], "verified_exact_recall": v["exact"]["recall"],
                  "unverified_reasons": dict(bad.most_common()),
                  "verdicts_missing": sum(1 for s in sk if s["verdict"] is None)}
    unscored = [s for s in structs if s["kind"] not in STRUCTURE_KINDS]
    buckets.update(collections.Counter(_bucket(s) for s in unscored if not s["verified"]))
    # what the verified count is worth
    shares = [s["verdict"]["load_hidden_share"] for s in with_verdict
              if s["verdict"]["load_hidden_share"] is not None]
    # a verified structure that names no load case hides nothing, so it enters the whole-set mean at 0
    all_shares = [(s["verdict"]["load_hidden_share"] or 0.0) for s in with_verdict]
    unchecked = collections.Counter(p for s in with_verdict for p in s["verdict"]["params_unchecked"])
    certified = collections.Counter(p for s in with_verdict for p in s["verdict"]["params_checked"])
    lf = [s for s in with_verdict if s["kind"] == "lfsr_crc"]
    live = [s for s in with_verdict if s["verdict"]["liveness_checked"]]
    out = {
        "verdicts": {"structures": len(structs), "with_a_verdict": sum(1 for s in structs if s["verdict"] is not None),
                     "source": "tools/s3/verify.py per-structure verdicts"
                               if any(s["verdict"] is not None for s in structs) else
                               "none: no verdicts were given, so nothing below is evidence"},
        "verified": {
            "structures": len(ver), "with_a_verdict": len(with_verdict),
            "vacuous_hold": sum(1 for s in with_verdict if s["verdict"]["hold_vacuous"]),
            "vacuous_hold_cover": dict(collections.Counter(
                s["verdict"]["hold_vacuous_cover"] or "unreported"
                for s in with_verdict if s["verdict"]["hold_vacuous"]).most_common()),
            "hold_claimed": sum(1 for s in with_verdict if s["verdict"]["hold_claimed"]),
            "with_a_load_case": sum(1 for s in with_verdict if s["verdict"]["load_cases"]),
            "load_hidden_share": _stats(shares),
            "load_hidden_share_over_all_verified": _stats(all_shares),
            "with_unchecked_params": sum(1 for s in with_verdict if s["verdict"]["params_unchecked"]),
            "with_only_certified_params": sum(1 for s in with_verdict if s["verdict"]["params_reported"]
                                              and not s["verdict"]["params_unchecked"]),
            "unchecked_param_names": dict(unchecked.most_common()),
            "certified_param_names": dict(certified.most_common()),
            "param_notes": {p: why for s in with_verdict for p, why in s["verdict"]["params_notes"].items()},
            "with_dead_bits": sum(1 for s in with_verdict if (s["verdict"]["dead_bits"] or 0) > 0),
            "liveness_checked": len(live),
            "without_a_liveness_obligation": len(with_verdict) - len(live),
            "live_bits": sum(s["verdict"]["live_bits"] or 0 for s in live),
            "lfsr_poly_certified": sum(1 for s in lf if s["verdict"]["poly_certified"]),
            "lfsr_structures": len(lf)},
        "per_kind": per,
        "unverified_reasons": dict(buckets.most_common()),
        "unscored_kind_structures": len(unscored),
        "reasons": {b: UNVERIFIED_REASONS.get(b, "an outcome tools/s3/score.py does not know; see verify.py")
                    for b in sorted(buckets)},
        "params_rule": PARAMS_CERTIFIED_RULE,
        "liveness_kinds": sorted(LIVENESS_KINDS)}
    if buckets.get("hold"):
        out["hold_ceiling"] = HOLD_CEILING_NOTE
    return out


def _core(T, result, verified=None, grouping=True, draws=RANDOM_BLOCK_DRAWS, grouping_baselines=True,
          outcomes=None, verdicts=None):
    structs, info = _structures(T, result, verified, outcomes, verdicts)
    groups, gdup = _groups(T, result)
    info["groups"] = len(result.get("groups") or [])
    info["flops_grouped"] = sum(len(g) for g in groups)
    info["flops_in_several_groups"] = gdup
    classes = {}
    matches = None
    for sub, sel in (("all", structs), ("verified", [s for s in structs if s["verified"]])):
        strict, _m_strict = _register_level(T, sel, False)
        lenient, m_len = _register_level(T, sel, True)
        classes[sub] = {"registers": {"strict": strict, "lenient": lenient}, "bits": _bit_level(T, sel)}
        if sub == "all":
            matches = m_len
    out = {"result": info, "classes": classes, "order": _order(T, matches), "params": _params(T, matches),
           "honesty": _honesty(T, structs, classes)}
    if grouping:
        out["grouping"] = _grouping(T, groups, draws, grouping_baselines)
    return out


def headline(rep):
    """A flat dict of the numbers a reader looks at first (strict, all structures; synchronizers
    strictly by chain units; verified-structure recall beside)."""
    c = rep["classes"]["all"]
    v = rep["classes"]["verified"]
    rs, rl, b = c["registers"]["strict"], c["registers"]["lenient"], c["bits"]
    h = {}
    for k in STRUCTURE_KINDS:
        pk = rs["per_kind"][k]
        h[k] = {"support": pk["registers"], "small_support": pk["small_support"], "structures": pk["structures"],
                "found_p": pk["found"]["precision"], "found_r": pk["found"]["recall"], "found_f1": pk["found"]["f1"],
                "exact_p": pk["exact"]["precision"], "exact_r": pk["exact"]["recall"], "exact_f1": pk["exact"]["f1"],
                "found75_r": pk["found_iou75"]["recall"], "mean_iou": pk["mean_iou_found"],
                "lenient_found_r": rl["per_kind"][k]["found"]["recall"], "lenient_support": rl["per_kind"][k]["registers"],
                "verified_found_r": v["registers"]["strict"]["per_kind"][k]["found"]["recall"],
                "verified_structures": v["registers"]["strict"]["per_kind"][k]["structures"],
                "bit_p": b["strict"][k]["precision"], "bit_r": b["strict"][k]["recall"], "bit_f1": b["strict"][k]["f1"],
                "bit_support": b["strict"][k]["support"], "unknown": pk.get("unknown", 0)}
        hk = (rep.get("honesty") or {}).get("per_kind", {}).get(k) or {}
        h[k]["unverified_structures"] = hk.get("unverified_structures", 0)
        h[k]["found_not_verified_registers"] = hk.get("found_not_verified_registers", 0)
    h["macro_f1_registers"] = rs["macro_f1"]
    h["macro_f1_registers_exact"] = rs["macro_f1_exact"]
    h["micro_f1_registers"] = rs["micro_f1"]
    h["micro_f1_registers_exact"] = rs["micro_f1_exact"]
    h["macro_f1_bits"] = b["macro_f1"]
    h["micro_f1_bits"] = b["micro_f1"]
    h["macro_f1_registers_verified"] = v["registers"]["strict"]["macro_f1"]
    p = rep["params"]
    h["params_accuracy"] = p["accuracy"]
    h["params_majority_accuracy"] = p["majority_accuracy"]
    h["params_informative_accuracy"] = p["informative"]["accuracy"]
    h["params_informative_kappa"] = p["informative"]["kappa"]
    # the split the freeze publishes: a certified parameter is one the harness pinned, a transcribed
    # one was copied from the recognizer's answer and never checked (PARAMS_CERTIFIED_RULE)
    h["params_certified_compared"] = p["certified"]["compared"]
    h["params_certified_accuracy"] = p["certified"]["accuracy"]
    h["params_transcribed_compared"] = p["transcribed"]["compared"]
    h["params_transcribed_accuracy"] = p["transcribed"]["accuracy"]
    hon = rep.get("honesty") or {}
    hv = hon.get("verified") or {}
    h["verified_vacuous_hold"] = hv.get("vacuous_hold", 0)
    h["verified_with_unchecked_params"] = hv.get("with_unchecked_params", 0)
    h["verified_with_dead_bits"] = hv.get("with_dead_bits", 0)
    h["verified_without_liveness"] = hv.get("without_a_liveness_obligation", 0)
    h["verified_load_hidden_share_mean"] = (hv.get("load_hidden_share") or {}).get("mean")
    h["verified_load_hidden_share_max"] = (hv.get("load_hidden_share") or {}).get("max")
    h["verified_load_hidden_share_mean_all"] = (hv.get("load_hidden_share_over_all_verified") or {}).get("mean")
    h["verified_lfsr_poly_certified"] = hv.get("lfsr_poly_certified", 0)
    h["unverified_by_reason"] = dict(hon.get("unverified_reasons") or {})
    h["order"] = {k: {band: {part: {m: e[part][m] for m in ("score", "coverage", "chance", "kappa")}
                             for part in ("within", "across") if part in e} | {"ordered": e["ordered"],
                                                                              "pairs_found": e["pairs_found"]}
                      for band, e in bands.items()} for k, bands in rep["order"]["summary"].items()}
    r = rep["result"]
    h["structures"], h["claimed_proven"], h["verified"] = r["structures"], r["claimed_proven"], r["verified"]
    h["unknown"] = (r.get("outcomes") or {}).get("unknown", 0)
    h["lanes_unordered"] = r.get("lanes_unordered", 0)
    h["dropped_flops"] = r["dropped_flops"]
    g = rep.get("grouping", {}).get("all_flops")
    if g and not g.get("empty"):
        h["ami"], h["ari"], h["nmi"] = g["ami"], g["ari"], g["nmi"]
    return h


def score(truth, result, baselines=None, *, verified=None, outcomes=None, verdicts=None,
          draws=RANDOM_BLOCK_DRAWS, strict_truth=False):
    """Score a result (flop ids = join keys) against a retrace-s3-truth/2 dict. `verified`: the
    harness's per-structure verdict flags (tools/s3/verify.py), aligned with result["structures"];
    `outcomes`: the harness's outcome class per structure, likewise (optional); `verdicts`: the full
    per-structure verdict dicts, likewise (optional, and what the `honesty` block and the certified /
    transcribed params split are computed from -- without them nothing counts as certified).
    `baselines` maps a name to a result dict (or {"result", "definition"}) scored the same way,
    e.g. the harness's structural baseline."""
    T = Truth(truth, strict=strict_truth)
    problems = [f"truth: {p}" for p in T.problems[:20]]
    problems += [f"result: {p}" for p in _safe_check_result(result)]
    problems += [f"truth unit ignored: {u['name']}: {u['why']}" for u in T.bad_units]
    rep = {"schema": REPORT_SCHEMA, "design": T.design, "truth_hash": schema.truth_hash(truth),
           "truth": {"registers": len(T.regs), "registers_with_flops": len(T.scored),
                     "registers_without_flops": len(T.no_flop), "flops": len(T.universe),
                     "shadow_flops": len(T.shadow_of), "unmapped_flops": len(T.unmapped), "units": len(T.units),
                     "chain_units": sorted(u["name"] for u in T.units if u["chain"]),
                     "problems": len(T.problems),
                     "by_kind": {c: len(T.denominators(c)) for c in STRUCTURE_KINDS},
                     "excused_by_kind": {c: len(T.excused(c)) for c in STRUCTURE_KINDS},
                     "majority_kind": majority_kind(T)},
           "class_map": class_map()}
    rep.update(_core(T, result, verified, draws=draws, outcomes=outcomes, verdicts=verdicts))
    notes = []
    if rep["result"]["flops_in_several_structures"]:   # legitimate where truth registers share flops
        notes.append(f"{rep['result']['flops_in_several_structures']} flops lie in more than one structure")
    if rep["result"]["dropped_flops"]:
        problems.append(f"{rep['result']['dropped_flops']} result flops were dropped (unmapped, unknown to the truth "
                        f"or not flop ids) from {rep['result']['structures_with_dropped_flops']} structures; "
                        "those structures cannot be exact")
    rep["problems"] = problems
    rep["notes"] = notes
    rep["headline"] = headline(rep)
    rep["provenance"] = provenance(T.design)
    bl = {"majority_class": {"definition": f"every flop its own structure of kind {majority_kind(T)} (the "
                                           "structure kind owning the most truth flops); groups: singletons",
                             "result": majority_result(T)}}
    for name, v in (baselines or {}).items():
        bl[name] = v if "result" in v else {"definition": (v.get("meta") or {}).get("definition", ""), "result": v}
    rep["baselines"] = {}
    for name, v in bl.items():
        sub = _core(T, v["result"], None, grouping=name != "majority_class", draws=draws, grouping_baselines=False)
        sub["headline"] = headline(sub)
        rep["baselines"][name] = {"definition": v.get("definition", ""), "headline": sub["headline"],
                                  "result": sub["result"]}
    return rep


def _safe_check_result(result):
    try:
        return schema.check_result(result)
    except Exception as e:   # schema.check_result assumes well-typed input; run.py type-checks first
        return [f"check_result raised {type(e).__name__}: {e}"]


# ----------------------------------------------------------------------------------------------
# text


def _f(x, w=5):
    return f"{'-':>{w}}" if x is None else f"{x:{w}.3f}"


def render_honesty(rep):
    """FOUND beside VERIFIED per kind with the reason of every unverified structure, and what the
    verified count is worth. Lines, so the callers can place the block where they want it."""
    hon = rep.get("honesty")
    if not hon:
        return []
    v, L = hon["verified"], []
    src = hon["verdicts"]
    L.append(f"Honesty (found = the recognizer's answer matched the register; verified = it matched a structure the "
             f"HARNESS proved; {src['with_a_verdict']}/{src['structures']} structures carry a verdict):")
    L.append(f"  {'kind':<16}{'regs':>5}{'strs':>5}   {'found R':>8}{'verif R':>8}{'gap':>5}   "
             f"{'verified/structures':>19}   unverified by reason")
    for k in STRUCTURE_KINDS:
        e = hon["per_kind"][k]
        reasons = ", ".join(f"{b} {n}" for b, n in e["unverified_reasons"].items()) or "-"
        gap = e["found_registers"] - e["verified_found_registers"]
        L.append(f"  {k:<16}{e['registers']:>5}{e['structures']:>5}   {_f(e['found_recall'], 8)}"
                 f"{_f(e['verified_found_recall'], 8)}{gap:>5}   "
                 f"{e['verified_structures']:>9}/{e['structures']:<9}   {reasons}")
    L.append(f"  every unverified structure by reason: {hon['unverified_reasons'] or '-'}"
             f" (including {hon['unscored_kind_structures']} of unscored kinds)")
    sh, sha = v["load_hidden_share"], v["load_hidden_share_over_all_verified"]
    L.append(f"  verified structures: {v['structures']} ({v['with_a_verdict']} with a verdict); vacuous hold "
             f"{v['vacuous_hold']} (emptied by {v['vacuous_hold_cover'] or '-'}); with a load case "
             f"{v['with_a_load_case']}")
    L.append(f"  load_hidden_share of the verified set: mean {_f(sh['mean'])} max {_f(sh['max'])} over the "
             f"{sh['n']} that name a load case; mean {_f(sha['mean'])} over all {sha['n']} verified (a structure "
             "with no load case hides nothing)")
    L.append(f"  params of the verified set: {v['with_unchecked_params']} carry an UNCHECKED parameter, "
             f"{v['with_only_certified_params']} only certified ones; unchecked names {v['unchecked_param_names'] or '-'}")
    for p, why in sorted((v.get("param_notes") or {}).items()):
        L.append(f"    {p}: {why}")
    L.append(f"  liveness: {v['with_dead_bits']} verified structures carry a dead bit; "
             f"{v['without_a_liveness_obligation']} of {v['with_a_verdict']} carry NO per-bit liveness obligation "
             f"(only {', '.join(hon['liveness_kinds'])} does); lfsr_crc polynomial certified "
             f"{v['lfsr_poly_certified']}/{v['lfsr_structures']}")
    if hon.get("hold_ceiling"):
        L.append("  LIMITATION: " + hon["hold_ceiling"])
    for b, why in hon["reasons"].items():
        if b != "verified":
            L.append(f"    reason {why}")
    return L


def render(rep):
    L = []
    t = rep["truth"]
    L.append(f"S3 score: design {rep['design']}  truth {rep['truth_hash'][:12]}")
    L.append(f"truth: {t['registers_with_flops']} registers with flops ({t['registers_without_flops']} without), "
             f"{t['flops']} flops, {t['shadow_flops']} shadow flops, {t['unmapped_flops']} unmapped flops excluded, "
             f"{t['units']} declared units ({len(t['chain_units'])} synchronizer chain units)"
             + (f"; {t['problems']} check_truth problems" if t["problems"] else ""))
    r = rep["result"]
    L.append(f"result: {r['structures']} structures ({r['structures_scored']} with labelled flops; by kind "
             f"{r['by_kind']}), {r['groups']} groups over {r['flops_grouped']} flops; dropped: {r['dropped_flops']} "
             f"flops ({r['unmapped_flops_in_result']} unmapped, {r['unknown_flops_in_result']} unknown) in "
             f"{r['structures_with_dropped_flops']} structures")
    L.append(f"proofs: {r['claimed_proven']} structures claim 'proven'; {r['verified']} verified by the harness "
             f"({r['verification']}); harness outcomes {r.get('outcomes', {})}; reason buckets {r.get('buckets', {})}")
    sk = rep["classes"]["all"]["registers"]["strict"]["per_kind"]
    L.append("  scored kinds: " + "; ".join(
        f"{k} {sum(v for o, v in sk[k]['outcomes'].items() if o == 'verified')}/{sk[k]['structures']} verified"
        + (f", {sk[k]['unknown']} unknown" if sk[k]["unknown"] else "") for k in STRUCTURE_KINDS)
        + f"; unscored kinds: {sum(r['structures_of_unscored_kinds'].values())} structures")
    for p in rep["problems"]:
        L.append(f"PROBLEM: {p}")
    for p in rep.get("notes", []):
        L.append(f"note: {p}")
    hon = render_honesty(rep)
    if hon:
        L.append("")
        L += hon
    pv = render_provenance(rep)
    if pv:
        L.append("")
        L += pv
    for sub, title in (("all", "all structures"), ("verified", "harness-verified structures only")):
        c = rep["classes"][sub]
        L.append("")
        mark = " [IN-SAMPLE]" if (rep.get("provenance") or {}).get("in_sample") else ""
        L.append(f"Register level{mark}, {title}: found | exact  (P = structures matched / structures, R = registers "
                 "found / registers; IoU > 0.5, one to one; R75 = found at IoU >= 0.75; * = support < "
                 f"{SMALL_SUPPORT})")
        L.append(f"  {'kind':<15}{'mode':<9}{'regs':>5}{'strs':>5}   {'P':>5} {'R':>5} {'F1':>5} |"
                 f" {'P':>5} {'R':>5} {'F1':>5} | {'R75':>5} {'mIoU':>5}   designs found all/any/total")
        for mode in ("strict", "lenient"):
            for k in STRUCTURE_KINDS:
                pk = c["registers"][mode]["per_kind"][k]
                fd, ex, dd = pk["found"], pk["exact"], pk["distinct_designs"]
                star = "*" if pk["small_support"] else " "
                L.append(f"  {k:<15}{mode:<9}{pk['registers']:>4}{star}{pk['structures']:>5}   {_f(fd['precision'])} "
                         f"{_f(fd['recall'])} {_f(fd['f1'])} | {_f(ex['precision'])} {_f(ex['recall'])} "
                         f"{_f(ex['f1'])} | {_f(pk['found_iou75']['recall'])} {_f(pk['mean_iou_found'])}   "
                         f"{dd['found_all']}/{dd['found_any']}/{dd['total']}")
            rr = c["registers"][mode]
            L.append(f"  F1 {mode}: macro found {_f(rr['macro_f1'])} exact {_f(rr['macro_f1_exact'])}; "
                     f"micro found {_f(rr['micro_f1'])} exact {_f(rr['micro_f1_exact'])}")
        b = c["bits"]
        L.append(f"Bit level, {title} (one class per flop):  {'kind':<15}{'pred':>6}{'supp':>6}   P     R     F1   "
                 "| lenient P R F1")
        for k in STRUCTURE_KINDS:
            s, le = b["strict"][k], b["lenient"][k]
            L.append(f"  {'':<27}{k:<15}{s['predicted']:>6}{s['support']:>6} {_f(s['precision'])} {_f(s['recall'])} "
                     f"{_f(s['f1'])} | {_f(le['precision'])} {_f(le['recall'])} {_f(le['f1'])}")
        L.append(f"  F1 bits: macro strict {_f(b['macro_f1'])} lenient {_f(b['macro_f1_lenient'])}; micro strict "
                 f"{_f(b['micro_f1'])} lenient {_f(b['micro_f1_lenient'])}; flops in structures of several kinds "
                 f"{b['flops_several']}")
    L.append(f"strict synchronizers: {STRICT_SYNC_RULE}")
    excused = rep["classes"]["all"]["registers"]["lenient"].get("excused_registers") or []
    if excused:
        L.append(f"excused (kept in every denominator; recall without them is in the report): {len(excused)} "
                 "registers with a non-structure alt kind: " + ", ".join(excused[:8]) + (" ..." if len(excused) > 8 else ""))
    L.append("")
    L.append("Order (Kendall concordance over the truth's ordered pairs; unasserted pairs are ties worth 1/2; "
             "chance under random order; kappa = (score - chance) / (1 - chance)):")
    if not rep["order"]["summary"]:
        L.append("  no found (structure, register) pair with >= 2 shared flops")
    for k, bands in rep["order"]["summary"].items():
        for band, e in bands.items():
            parts = [f"{e['ordered']}/{e['pairs_found']} ordered, {e['all_correct']} all correct"]
            for part in ("within", "across"):
                if part in e:
                    x = e[part]
                    parts.append(f"{part} lanes {x['score']:.3f} (coverage {x['coverage']:.2f}, chance "
                                 f"{x['chance']:.3f}, kappa {_f(x['kappa'])}) over {x['pairs']} pairs")
            if e.get("lanes_unordered"):
                parts.append(f"{e['lanes_unordered']} declared lanes_unordered: {e['across_unscored_pairs']} "
                             "across pairs not scored")
            L.append(f"  {k} {band}: " + "; ".join(parts))
    p = rep["params"]
    L.append(f"Parameters (only where the truth knows them): {p['correct']}/{p['compared']} correct ({_f(p['accuracy'])}; "
             f"majority-value baseline {_f(p['majority_accuracy'])}, kappa {_f(p['kappa'])}); informative parameters "
             f"{p['informative']['correct']}/{p['informative']['compared']} ({_f(p['informative']['accuracy'])}, "
             f"baseline {_f(p['informative']['majority_accuracy'])})")
    ce, tr = p["certified"], p["transcribed"]
    L.append(f"  split ({PARAMS_CERTIFIED_RULE}):")
    L.append(f"    CERTIFIED   {ce['correct']}/{ce['compared']} ({_f(ce['accuracy'])})  over {len(ce['params'])} "
             f"parameter name(s): {', '.join(ce['params']) or '-'}")
    L.append(f"    TRANSCRIBED {tr['correct']}/{tr['compared']} ({_f(tr['accuracy'])})  over {len(tr['params'])} "
             f"parameter name(s): {', '.join(tr['params']) or '-'}")
    for key, v in p["per_param"].items():
        c_, t_ = v["certified"], v["transcribed"]
        L.append(f"  {key:<28} {v['correct']}/{v['n']}  majority {v['majority_correct']}/{v['n']}"
                 f"  certified {c_['correct']}/{c_['compared']} transcribed {t_['correct']}/{t_['compared']}"
                 f"{'' if v['informative'] else '  (constant in the truth)'}")
    if p.get("form_both_answers"):
        L.append(f"  lfsr_crc.form: {p['form_both_answers']} answers of 'both' against a single-form truth "
                 f"(accepted: {LFSR_FORM_RULE})")
    L.append("")
    L.append("Grouping (truth partition = primary register of each flop; ungrouped flops are singletons):")
    for name, g in rep.get("grouping", {}).items():
        if g.get("empty"):
            L.append(f"  {name}: no flops to group")
            continue
        L.append(f"  {name} (n={g['n']}, truth blocks {g['truth_blocks']}, predicted {g['pred_blocks']}): "
                 f"AMI {g['ami']:.3f}  ARI {g['ari']:.3f}  NMI {g['nmi']:.3f}  pair P/R/F1 {_f(g['pair_precision'])}/"
                 f"{_f(g['pair_recall'])}/{_f(g['pair_f1'])}  purity {g['purity']:.3f}/{g['inverse_purity']:.3f}  "
                 f"exact words {g['exact_words']}/{g['truth_words_multi']} (lenient {g['exact_words_lenient']})  "
                 f"splits {g['splits']} merges {g['merges']}")
        s, rb = g["baseline_singletons"], g["baseline_random_blocks"]
        L.append(f"    baselines: singletons AMI {s['ami']:.3f} ARI {s['ari']:.3f} NMI {s['nmi']:.3f}; random blocks "
                 f"({rb['draws']} draws) AMI {rb['ami']['mean']:.3f} ARI {rb['ari']['mean']:.3f} "
                 f"NMI {rb['nmi']['mean']:.3f}")
    L.append("")
    L.append("Baselines (strict, all structures):")
    for name, b in rep["baselines"].items():
        h = b["headline"]
        L.append(f"  {name}: {b['definition']}")
        L.append("    found R " + ", ".join(f"{k} {_f(h[k]['found_r'])}" for k in STRUCTURE_KINDS)
                 + "; bit F1 " + ", ".join(f"{k} {_f(h[k]['bit_f1'])}" for k in STRUCTURE_KINDS)
                 + f"; F1 registers macro {_f(h['macro_f1_registers'])} micro {_f(h['micro_f1_registers'])}"
                 + f"; bits macro {_f(h['macro_f1_bits'])} micro {_f(h['micro_f1_bits'])}"
                 + (f"; AMI {h['ami']:.3f} ARI {h['ari']:.3f}" if "ami" in h else ""))
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Score an S3 result (flop ids = join keys) against a truth file. "
                                 "Standalone scoring has no netlist, so no structure counts as verified.")
    ap.add_argument("truth")
    ap.add_argument("result")
    ap.add_argument("--json", help="write the report here")
    a = ap.parse_args(argv)
    truth, _raw = load_truth(a.truth, strict=False)
    with open(a.result) as f:
        result = json.load(f)
    rep = score(truth, result)
    print(render(rep))
    if a.json:
        with open(a.json, "x") as f:
            json.dump(rep, f, indent=1, sort_keys=True, default=str)


if __name__ == "__main__":
    main()
