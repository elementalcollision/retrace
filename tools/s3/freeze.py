"""S3 freeze: pin the recognizer, the scorer, the harness, the truth, the inputs and the class map
before a blind run, and keep the blind ledger (PRD S3; docs/S3_DESIGN.md section 4.4 as amended
by the lead, 2026-09-21, and by the scorer review of 2026-09-22).

    python -m tools.s3.freeze write [--candidates FILE --draw-n N [--max-reserves R]]
                                    [--designs tempo puzzle] [--note TEXT ...] [--force]
                                    [--supersede REASON]
    python -m tools.s3.freeze check
    python -m tools.s3.freeze checklist [--no-leakage] [--jobs N]   (the PRE-FREEZE checklist)
    python -m tools.s3.freeze show
    python -m tools.s3.freeze draw          (the drawn third-party ids under the freeze)
    python -m tools.s3.freeze spent         (what `write --draw-n` would record as draw.excluded now;
                                             exit 1, with each on stderr, on a problem write refuses)

The freeze is a git commit, made by the lead, of every tools/s3/*.py and of out/s3/FREEZE.json
(git-ignored under out/, so it is added with -f). FREEZE.json holds:
  code          sha256 of every tools/s3/*.py (sources only: blind runs never read a bytecode cache,
                see tools/s3/run.py)
  extractor_code sha256 of tools/retrace/*.py (the extractor every blind design passes through);
                info_code: tools/tempo/lvs.py (informational: TEMPO's netlist is pinned instead)
  packages      Python and package versions (numpy, z3-solver, networkx, gdstk, shapely, klayout)
  truth         per FROZEN truth file out/s3/truth_<design>.json: schema.truth_hash (the scored
                content, timings excluded)
  inputs        per pinned design (write --designs): sha256 of every input file the extraction
                reads (GDS, LEF, Liberty) and netlist_hash() of the seed=None anonymous Netlist
  class_map     score.class_map(): kind -> scored class and every scoring rule constant
  git_head      HEAD when the freeze was written (the freeze commit is its child)
  blind_seed    128 bits from os.urandom, drawn now
  blind_candidates  path and sha256 of the candidate list registered before recognizer
                development (null if none was given; then no third-party draw is possible)
  draw          {n, max_reserves, rule, strata, excluded, eligible}: thirdparty.draw(blind_seed, n,
                exclude) picks the n blind designs (then reserves in order, at most max_reserves,
                each replacing a drawn design the frozen labeller could not label) from the
                candidates not in `excluded`: [{id, evidence}] of the designs an earlier blind
                evaluation has seen (spent_designs: a ledger attempt, a blind run record, a truth
                file on disk or in git history, a design labels.json names as drawn, replaced or
                used as a reserve, an anonymised layout, a cached download), computed ONCE at write
                and read back by draw(), never recomputed. `eligible` is the number of candidates
                left after the exclusion; write() refuses a draw when it is below n
                (thirdparty.draw() would silently draw fewer), when the blind ledger, the evidence
                for `excluded`, has problems (ledger_entries, working tree and history), when a
                git history the evidence is read from cannot be read (a shallow clone's
                truncated history included), and when the record it has
                just built fails its own tripwire (draw_excluded_problems: evidence that appeared
                while it was built). check() recomputes `eligible` from the pinned candidate list
                and `excluded`. A record without `excluded` (freeze 1's) excludes nothing; one
                without `eligible` does not hold under check()
  supersedes    (only when a freeze replaces one that has blind attempts, with --supersede) the
                reason and the earlier attempts
  protocol      PROTOCOL: the evaluation protocol run.py applies (K >= 5 os.urandom permutations per
                frozen evaluation, spread reported; the leakage test's rule)
  records       sha256 of the change log (tools/s3/changes.jsonl: every design or parameter change
                after 2026-09-21 with its evidence, S3_DESIGN 4.4) and of the contamination record
                (out/s3/contamination.json); both must exist to write a freeze and both are part of
                the freeze commit (the latter force-added, as out/ is git-ignored)
  contamination the contamination record itself (S3_DESIGN 4.4: "in FREEZE.json")
  records_evidence  record_evidence(): every evidence path the change log and the contamination
                record cite, re-hashed at the freeze, as {checked, stale, missing}. `records` pins
                the two record FILES; this says whether what they cite still is what they say it
                is. write() refuses on a stale hash (a file that is there and changed) unless
                --force; a missing path is reported only (review[2] issue 5)
  notes         free-text declarations (e.g. that the puzzle was probed during design review)
  freeze_hash   sha256 of the canonical JSON of all of the above except `created` and `notes`

Truths. FROZEN truths (present at the freeze) must keep their truth_hash. A truth file added
after the freeze is accepted only when (1) its id is one of the drawn designs (blind or permitted
reserve) of thirdparty.draw(blind_seed, n, the recorded draw.excluded) run from the frozen
tools/s3/thirdparty.py, (2)
tools/s3/thirdparty.py (the labeller) still has its frozen hash, (3) its "design" field names that
id, and (4) if its meta records the labeller's hash (meta.labeller_sha256), that hash is the frozen
one. Any other added truth file is a mismatch.

Blind ledger (out/s3/blind_ledger.jsonl, force-added and committed by the lead after every
attempt): run.py appends an "attempt" entry before extracting a blind design and a "finish" entry
after; each line carries the sha256 of the previous line. blind_results() and write() read the
ledger in the working tree AND in every committed version (git history, on any ref and in the
reflog, so a version orphaned by reset, amend or rebase is read while the reflog holds it, with
--full-history so a version committed on a merged and deleted side branch is not simplified away),
so deleting a record or the ledger does not erase an attempt. In a git repository a history that
cannot be read is a ledger problem, never "no history", and so is a shallow clone's, which git log
reads with exit 0 but cut at the clone's depth (_history); a line that is not a JSON object is an
unparsable line.

check() lists every mismatch between the working tree and FREEZE.json. When a draw is recorded it
also checks draw.excluded against the evidence of earlier evaluations (draw_excluded_problems, the
tripwire): a blind attempt under ANOTHER freeze (ledger, working tree and history, or a blind run
record), a third-party truth of this freeze's own frozen truth block, and a design a version of
labels.json (working tree and history) written under ANOTHER freeze records as drawn, replaced or
used as a reserve must not be a candidate the draw can still offer; and draw.eligible must be the
pinned list's candidates minus the draw.excluded ids that are candidates (draw_eligible_problems,
the count). For a FREEZE.json whose draw.excluded was cut after the write, that catches exactly:
  - the count: an INCONSISTENT cut (an entry removed while draw.eligible keeps its value, or
    draw.eligible changed alone), with or without freeze_hash recomputed;
  - the tripwire: a cut, even a coordinated one (an entry removed, draw.eligible raised by one,
    freeze_hash recomputed), of a design whose evidence is a ledger attempt, a readable run
    record, a frozen truth or a labels.json entry under another freeze;
  - nothing reliable: a coordinated cut of a design whose only evidence is the git-ignored download
    cache or an anonymised layout is NOT reliably detectable by check() (this freeze's own evaluation adds to
    both, and neither records a freeze, so check() does not read them); nor is one whose only
    evidence is a blind run record's file name (a record that cannot be read) or a truth deleted
    from disk before the freeze (in git history only, so not in the frozen truth block), which
    spent_designs() reads and the tripwire does not. Neither the tripwire nor the count reads that
    evidence; the history of out/s3/FREEZE.json in git (the freeze commit, `git log -p --
    out/s3/FREEZE.json`) shows such a cut, and on the machine that holds the cache and the
    anonymised layouts `python -m tools.s3.freeze spent` still lists the cut design. It can surface in
    check() only INCIDENTALLY: (a) through the added-truth rule, when the cut shifts the draw so that a
    design whose truth was added after the freeze is no longer among the drawn designs and permitted
    reserves ("added after the freeze and not a drawn design"); (b) once this freeze's own evaluation
    has recorded a drawn third-party design under its freeze_hash -- a ledger attempt, a blind run
    record, a labels.json -- because ANY recomputed freeze_hash makes that record another freeze's and
    the tripwire fires on it. Neither is guaranteed, so neither is relied on.
This freeze's own evaluation (its attempts and run records, its added truths, the labels.json its
labeller writes under its own freeze_hash) never moves the check. run.py --blind refuses to
start on any mismatch, refuses a second attempt of a design under the same freeze unless given a
reason, and refuses while the ledger has uncommitted entries. write() refuses to replace a freeze
that has blind attempts, and refuses a new freeze while any blind attempt exists anywhere in the
ledger's history, unless --supersede REASON records why (and the earlier attempts) in the new
FREEZE.json.
"""

from __future__ import annotations

import argparse
import datetime
import glob
import hashlib
import importlib.util
import json
import os
import platform
import re
import secrets
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.s3 import schema, score  # noqa: E402

FREEZE_SCHEMA = "retrace-s3-freeze/3"
LEDGER_SCHEMA = "retrace-s3-ledger/1"
FREEZE_REL = os.path.join("out", "s3", "FREEZE.json")
RUNS_REL = os.path.join("out", "s3", "runs")
LEDGER_REL = os.path.join("out", "s3", "blind_ledger.jsonl")
# the record run.py --blind writes into out/s3/runs BEFORE extracting (run.py _open_attempt), and
# logs by path and sha256 in the ledger; run_strays() accepts it only on that ledger proof
ATTEMPT_SCHEMA = "retrace-s3-attempt/1"
ATTEMPT_SUFFIX = ".attempt.json"
THIRDPARTY_REL = os.path.join("tools", "s3", "thirdparty.py")
CANDIDATES_REL = os.path.join("out", "s3", "blind", "candidates.json")
# the labeller's committed record of what it did under a freeze (out/s3/blind/make_labels.py): the
# drawn designs, the listed reserves, a row per design it worked on (a reserve used names the drawn
# design it `replaces`) and the number of reserves used. What it names as drawn, replaced or used is
# spent (spent_designs); a reserve it merely lists is not
LABELS_REL = os.path.join("out", "s3", "blind", "labels.json")
# thirdparty.py's download cache (its CACHE; RETRACE_TT_CACHE moves it): a candidate with a file in
# one of these was fetched, so the labeller has seen it (spent_designs)
CACHE_REL = os.path.join("out", "s3", "blind", "cache")
CACHE_KINDS = ("layout", "rtl")
# the labeller's anonymised layouts (out/s3/blind/label_driver.py: anon/<score.design_id>.gds), the
# file a blind run of a drawn design reads: one there means the design was labelled (spent_designs)
ANON_REL = os.path.join("out", "s3", "blind", "anon")
# run.py _write_record's blind record name: blind-<design>-<utc stamp>-<hash>[.attempt].json. The stamp
# and the hash hold no "-", so the design is everything between "blind-" and the last two fields
_RUN_NAME = re.compile(r"^blind-(.+)-[^-]+-[^-]+\.json$")
CHANGES_REL = os.path.join("tools", "s3", "changes.jsonl")
CONTAMINATION_REL = os.path.join("out", "s3", "contamination.json")
RECORDS = (CHANGES_REL, CONTAMINATION_REL)
DOC_REL = os.path.join("docs", "S3_DESIGN.md")
TEST_RELS = (os.path.join("test", "test_s3.py"), os.path.join("test", "test_s3_verify.py"))
PRIOR_ART_REL = os.path.join("out", "s3", "prior_art.md")
EVAL_RUNS_REL = os.path.join("out", "s3", "eval", "runs")
# the measured artifacts S3_DESIGN quotes BY PATH; git-ignored under out/, so the freeze commit
# force-adds them (commit_command(); the lead's decision of 2026-09-23). The TEMPO evaluation record
# is the fifth and is found by name, not listed here (latest_eval_record()).
PUBLISHED_FIGURE_RELS = (
    os.path.join("out", "s3", "honesty", "honesty_table.json"),
    os.path.join("out", "s3", "honesty", "honesty_table.log"),
    os.path.join("out", "s3", "honesty", "summary.json"),
    os.path.join("out", "s3", "honesty", "params_coverage.json"),
)
PACKAGES = ("numpy", "z3-solver", "networkx", "gdstk", "shapely", "klayout")
# the evaluation protocol run.py applies; frozen with the code (a change after the freeze is a mismatch)
PROTOCOL = {
    "permutations_min": 5,
    "permutations": "every frozen evaluation runs the recognizer under K >= permutations_min independent "
                    "os.urandom permutations inside its one attempt; every metric is reported per permutation and "
                    "as mean / median / min / max (S3_DESIGN section 2; the recognizer is not proven permutation "
                    "invariant, so this protocol does not assume it -- review of 2026-09-22)",
    "leakage_test": "TEMPO: a file-order arm (the loader's ids) next to >= permutations_min permutations; every "
                    "metric and the structure-set agreement of the file-order arm must lie within the permutations' "
                    "spread (S3_DESIGN section 2)",
    "blackboxes": "black-box masters and pins are opaque ids numbered in a random order, directions kept (V13)",
    "records": "development records go to out/s3/eval/runs; out/s3/runs holds blind records only, and the "
               "attempt record each blind run writes there first, proven by the ledger (run_strays)",
}
HASHED = ("schema", "code", "extractor_code", "packages", "truth", "inputs", "class_map", "git_head", "blind_seed",
          "blind_candidates", "draw", "supersedes", "protocol", "records", "contamination", "records_evidence")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_sha256_file = sha256_file


def canonical_hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _glob_hashes(root, *parts):
    return {os.path.relpath(p, root): sha256_file(p) for p in sorted(glob.glob(os.path.join(root, *parts)))}


def code_hashes(root=ROOT):
    """{tools/s3/<file>.py: sha256} for every Python source file of tools/s3."""
    return _glob_hashes(root, "tools", "s3", "*.py")


def extractor_hashes(root=ROOT):
    """{tools/retrace/<file>.py: sha256}: the extractor every blind design passes through."""
    return _glob_hashes(root, "tools", "retrace", "*.py")


def info_hashes(root=ROOT):
    p = os.path.join(root, "tools", "tempo", "lvs.py")
    return {os.path.relpath(p, root): sha256_file(p)} if os.path.exists(p) else {}


def package_versions():
    from importlib import metadata
    out = {"python": platform.python_version(), "implementation": platform.python_implementation()}
    for p in PACKAGES:
        try:
            out[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            out[p] = None
    return out


def netlist_hash(nl):
    """Canonical sha256 of an anonymous Netlist (seed=None loads are deterministic): masters, pins,
    nets, ports, constants, black-box pin directions and dropped physical cells. The Liberty is
    pinned as a file instead."""
    doc = {"master": list(nl.master), "pins": [sorted(p.items()) for p in nl.pins], "n_nets": nl.n_nets,
           "inputs": sorted(nl.inputs), "outputs": sorted(nl.outputs), "const": sorted(nl.const.items()),
           "blackbox": {m: sorted(v.items()) for m, v in sorted(nl.blackbox.items())},
           "dropped": sorted(nl.dropped.items())}
    return canonical_hash(doc)


def record_hashes(root=ROOT):
    """{path: sha256 or None (missing)} of the change log and the contamination record."""
    return {rel: (sha256_file(os.path.join(root, rel)) if os.path.exists(os.path.join(root, rel)) else None)
            for rel in RECORDS}


def load_contamination(root=ROOT):
    p = os.path.join(root, CONTAMINATION_REL)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


CHANGE_FIELDS = ("id", "date", "module", "change", "evidence")


def check_changes(root=ROOT):
    """Problems of the change log (empty = well formed): one JSON object per line, each with
    CHANGE_FIELDS; evidence a non-empty list of {"path", "sha256"} (sha256 null only with a
    "missing" reason); ids unique."""
    p = os.path.join(root, CHANGES_REL)
    if not os.path.exists(p):
        return [f"{CHANGES_REL}: missing"]
    bad, ids = [], set()
    with open(p) as f:
        lines = [x for x in f.read().splitlines() if x.strip()]
    for n, line in enumerate(lines, 1):
        try:
            e = json.loads(line)
        except ValueError:
            bad.append(f"{CHANGES_REL}:{n}: not JSON")
            continue
        if not isinstance(e, dict):
            bad.append(f"{CHANGES_REL}:{n}: not an object")
            continue
        miss = [k for k in CHANGE_FIELDS if not e.get(k)]
        if miss:
            bad.append(f"{CHANGES_REL}:{n}: missing {miss}")
        if e.get("id") in ids:
            bad.append(f"{CHANGES_REL}:{n}: duplicate id {e.get('id')}")
        ids.add(e.get("id"))
        for ev in e.get("evidence") or []:
            if not isinstance(ev, dict) or not ev.get("path") or not (ev.get("sha256") or ev.get("missing")):
                bad.append(f"{CHANGES_REL}:{n}: evidence without path and sha256 (or a 'missing' reason)")
    return bad


def _evidence_paths(obj, where, out):
    """Collect (where, path, sha256) from every "evidence" list of a record."""
    for e in obj.get("evidence") or []:
        if isinstance(e, dict) and e.get("path"):
            out.append((where, e["path"], e.get("sha256")))


def record_evidence(root=ROOT):
    """Re-hash every evidence path the change log and the contamination record cite.

    freeze.check() only pins the two record FILES; a hash INSIDE one of them can go stale without
    anything noticing, which is how out/s3/contamination.json came to describe a tools/s3/corpus.py
    and an out/s3/corpus/manifest.json that no longer existed (review[2] issue 5). Returns
    {"checked": n, "stale": [...], "moved": [...], "missing": [...]}:

      stale    a CONTAMINATION-record path whose file is there and whose content changed. The
               contamination record describes what the corpus and the development data ARE, so a
               changed file means the record is wrong: this blocks a freeze.
      moved    a CHANGE-LOG path whose content changed. A change-log entry's evidence is a
               historical snapshot ("the value as of this entry"), so a later edit of the same
               file is expected and is reported, never treated as a fault.
      missing  the path is gone (reported only: transcripts and scratch outputs are rotated).
    """
    items = []
    p = os.path.join(root, CHANGES_REL)
    if os.path.exists(p):
        with open(p) as f:
            for n, line in enumerate(f.read().splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    _evidence_paths(e, f"{CHANGES_REL}:{e.get('id') or n}", items)
    con = load_contamination(root)
    if con:
        _evidence_paths({"evidence": con.get("sources")}, f"{CONTAMINATION_REL}:sources", items)
        for it in con.get("items") or []:
            _evidence_paths(it, f"{CONTAMINATION_REL}:{it.get('id')}", items)
    stale, moved, missing = [], [], []
    for where, path, want in items:
        if not want:
            continue
        full = path if os.path.isabs(path) else os.path.join(root, path)
        cur = sha256_file(full) if os.path.exists(full) else None
        if cur is None:
            missing.append(f"{where}: {path}: missing")
        elif cur != want:
            (stale if where.startswith(CONTAMINATION_REL) else moved).append(
                f"{where}: {path}: recorded {want[:12]}, now {cur[:12]}")
    return {"checked": len(items), "stale": stale, "moved": moved, "missing": missing}


PRE_FREEZE = ("change log well formed (check_changes)",
              "contamination record present and its own evidence hashes current (record_evidence)",
              "change-log evidence hashes current (record_evidence)",
              "out/s3/runs holds blind records only (run_strays: `blind` true, or an attempt record the "
              "ledger proves)",
              "the published out-of-sample estimate describes THIS code (score.out_of_sample)",
              "the TEMPO leakage test passes (S3_DESIGN section 2; run.py --leakage)")

# THE ORDER the last edits, the record writers and `freeze write` must run in (freeze-readiness
# review of 2026-09-23). It is an ordering, not a preference, because of three coupled gates that
# nothing else enforces:
#   * out/s3/contamination.json cites docs/S3_DESIGN.md, tools/s3/params.py, tools/s3/corpus.py,
#     out/s3/honesty/holdout_rates.json and out/s3/prior_art.md BY SHA256. record_evidence() calls a
#     changed contamination-cited file `stale` (a change-log citation is only `moved`, which is the
#     documented snapshot convention and blocks nothing), and write() below REFUSES a stale record
#     without --force. So every edit to a cited file must precede write_contamination.py, which
#     re-hashes them.
#   * score.out_of_sample() refuses the published holdout estimate the moment any file of
#     score.OUT_OF_SAMPLE_SOURCES (the recognizer modules, netlist/params/schema/verify, corpus.py,
#     score.py) differs from the hashes it was derived on -- PRE_FREEZE step 5 blocks on exactly
#     that, so such an edit forces a re-derivation before the checklist, not after.
#   * write() runs check_changes() and record_evidence() only. It does NOT run checklist(), and it
#     writes FREEZE.json LAST, pinning code_hashes() as they are at that instant -- so any edit to
#     tools/s3/*.py after `freeze write` invalidates the freeze it just wrote.
FREEZE_ORDER = (
    "make every remaining edit: tools/s3/*.py, docs/S3_DESIGN.md, test/test_s3.py, "
    "test/test_s3_verify.py. If any file of score.OUT_OF_SAMPLE_SOURCES changed, the out-of-sample "
    "estimate must be re-derived first: `.venv/bin/python out/s3/honesty/holdout_rates.py --run`, a "
    "fresh TEMPO run, then `out/s3/honesty/honesty_table.py --tempo-record <record>`",
    "`.venv/bin/python out/s3/honesty/write_contamination.py` (re-hashes every contamination-cited "
    f"path, including {DOC_REL}; without this, record_evidence() reports them stale and `freeze "
    "write` refuses)",
    f"append the {CHANGES_REL} entries for those edits, with evidence sha256s taken AFTER them",
    "`.venv/bin/python out/s3/honesty/summarise.py` TWICE (regenerates out/s3/honesty/summary.json). "
    "It runs AFTER the two steps above, and twice, because it embeds record_evidence() live at write "
    f"time while {CHANGES_REL} entries cite summary.json back by sha256, so one pass does not "
    "converge; the second pass must leave summary.json byte-identical",
    "`.venv/bin/python out/s3/honesty/oos_provenance.py` -- must exit 0",
    "`TEMPO_ROOT=<snapshot> .venv/bin/python -m tools.s3.freeze checklist --jobs 3` -- must print "
    "\"checklist clear\" (the TEMPO leakage arm is most of the wall time)",
    "`TEMPO_ROOT=<snapshot> .venv/bin/python -m tools.s3.freeze write --candidates "
    "out/s3/blind/candidates.json --draw-n N [--max-reserves R] --designs tempo` (--candidates AND "
    "--draw-n together, or no blind draw is recorded). Nothing under tools/s3 may change after this",
    "the `git add ... && git commit` line `freeze write` prints (see commit_command())",
    "`python -m tools.s3.freeze check` -- must print \"freeze holds\"",
)
# indices of the steps the printed cross-references name, 1-based, LOOKED UP rather than written
# down, so a reordering of FREEZE_ORDER cannot make those cross-references lie (they used to be
# arithmetic on the checklist step, which a reordering silently broke -- freeze-readiness review,
# 2026-09-23).
def _freeze_order_step(needle):
    return 1 + next(i for i, s in enumerate(FREEZE_ORDER) if needle in s)


FREEZE_ORDER_CHECKLIST_STEP = _freeze_order_step("tools.s3.freeze checklist")
FREEZE_ORDER_CONTAMINATION_STEP = _freeze_order_step("write_contamination.py")
FREEZE_ORDER_WRITE_STEP = _freeze_order_step("tools.s3.freeze write")
# the order that actually converges: contamination -> the change-log entries -> summarise TWICE
assert (FREEZE_ORDER_CONTAMINATION_STEP
        < _freeze_order_step(f"append the {CHANGES_REL} entries")
        < _freeze_order_step("summarise.py` TWICE")
        < FREEZE_ORDER_CHECKLIST_STEP
        < FREEZE_ORDER_WRITE_STEP)


def commit_command(fr=None, root=ROOT):
    """The git command that makes the freeze commit (S3_DESIGN section 4.4, the Freeze row).

    The ordinary add is every tools/s3 source, the change log, the specification and the two test
    files that state the contract (S3_DESIGN 4.4 names them; they are tracked-able, not ignored).
    The forced add is the paths under the git-ignored out/: FREEZE.json and the two records, the
    blind candidate list FREEZE.json pins by path and sha256, and the two artifacts the
    contamination record pins as stale-blocking evidence -- the out-of-sample estimate every report
    must quote (score.OUT_OF_SAMPLE_REL) and the prior-art note section 7 cites.

    PUBLISHED_FIGURE_RELS and the TEMPO evaluation record are force-added TOO, by the lead's
    decision of 2026-09-23 (freeze-readiness review, issue "the freeze table and the TEMPO record
    are not in the commit"): the freeze table, the honesty summary, the parameter-coverage table and
    the TEMPO record are what S3_DESIGN sections 2, 3.7, 4 and 5 quote BY PATH, all of them are
    git-ignored under out/, and without -f a reader of the freeze commit cannot check a single
    published figure. The rule is: if the specification cites it by path, it is in the commit.
    NOT force-added, and deliberately: the change log's own evidence files (out/s3/verify/*.json and
    the rest). A changes.jsonl entry's evidence is a dated snapshot, all 150 entries cite such paths,
    and none has ever been committed; `records` pins the change log itself by sha256, so adding only
    the newest entry's evidence would be an inconsistency, not a guarantee. They stay in the working
    tree, named by path in the entry.

    check() does NOT verify most of this (it reads FREEZE.json, the tools/s3/*.py it pins and the
    two records only), so after committing, `git show --stat HEAD` is the check that the tracked
    five and every forced path really landed.
    """
    tracked = ["tools/s3/*.py", CHANGES_REL, DOC_REL, *TEST_RELS]
    forced = [FREEZE_REL, CONTAMINATION_REL]
    if (fr or {}).get("blind_candidates"):
        forced.append(fr["blind_candidates"]["path"])
    forced += [score.OUT_OF_SAMPLE_REL, PRIOR_ART_REL]
    forced += [p for p in PUBLISHED_FIGURE_RELS if os.path.exists(os.path.join(root, p))]
    rec = latest_eval_record("tempo", root)
    if rec:
        forced.append(rec)
    return f"git add {' '.join(tracked)} && git add -f {' '.join(forced)} && git commit"


def latest_eval_record(design="tempo", root=ROOT):
    """The newest out/s3/eval/runs/<design>-*.json, relative to root (None if there is none).

    It is the record S3_DESIGN cites for the measured figures, and it is git-ignored, so
    commit_command() force-adds it. Newest by the UTC stamp in the name, which run.py writes."""
    d = os.path.join(root, EVAL_RUNS_REL)
    names = sorted(n for n in (os.listdir(d) if os.path.isdir(d) else [])
                   if n.startswith(f"{design}-") and n.endswith(".json"))
    return os.path.join(EVAL_RUNS_REL, names[-1]) if names else None


_RUNS_RULE = ("out/s3/runs holds blind records only: `blind` true, or an attempt record the ledger proves "
              "(changes.jsonl C16, F01)")


def _logged_attempts(root):
    """{record path: {record_sha256, ...}} of every "attempt" event of the ledger, working tree and
    git history (ledger_entries). A root that is not a git repository has no history: git fails
    there and ledger_entries() reads the working-tree ledger alone. Without a git binary at all the
    history is not read either; that can only turn a record into a stray, never admit one."""
    try:
        entries = ledger_entries(root)[0]
    except OSError:           # no git executable
        entries = ledger_entries(root, history=False)[0]
    out = {}
    for e in entries:
        rec, sha = e.get("record"), e.get("record_sha256")
        if e.get("event") == "attempt" and isinstance(rec, str) and isinstance(sha, str):
            out.setdefault(rec, set()).add(sha)
    return out


def run_strays(root=ROOT):
    """{path relative to root: why} for every *.json in out/s3/runs that does not belong there
    (empty = none). THE rule for that directory: checklist() and test/test_s3.py both call this.

    A file belongs when it is
      * a blind run's ATTEMPT record proven by the ledger: its name ends ATTEMPT_SUFFIX, its
        `schema` is ATTEMPT_SCHEMA, and the ledger (ledger_entries: working tree and git history)
        holds an "attempt" event whose `record` is this file's path relative to root and whose
        `record_sha256` is the file's sha256 NOW. run.py --blind writes that record into
        out/s3/runs before extracting (_open_attempt), and it carries no `blind` key, so the rule
        used to call every blind run's attempt a stray. Name and schema alone prove nothing: a
        renamed record, an attempt with no ledger entry (a "finish" entry is not one) and an attempt
        edited after it was logged are all strays. A file that LOOKS like an attempt (either the
        name or the schema) is judged by this proof alone, whatever its `blind` says: otherwise
        adding `"blind": true` would pass a forged, renamed or edited attempt; or
      * any other file whose top-level `blind` is JSON true (run.py _write_record; not under meta,
        and not merely truthy: "false" or 1 is not true).
    A file that cannot be read or parsed is skipped, as it always was (blind_results() counts it as
    an attempt); a parsed file that is not a JSON object is a stray.
    """
    rdir = os.path.join(root, RUNS_REL)
    strays, logged = {}, None
    for n in sorted(os.listdir(rdir)) if os.path.isdir(rdir) else []:
        if not n.endswith(".json"):
            continue
        rel, path = os.path.join(RUNS_REL, n), os.path.join(rdir, n)
        try:
            with open(path) as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict):
            strays[rel] = f"not a JSON object; {_RUNS_RULE}"
            continue
        design, schema, named = rec.get("design"), rec.get("schema"), n.endswith(ATTEMPT_SUFFIX)
        # attempts first: `blind` never excuses a file that looks like an attempt from the ledger proof
        if not named and schema != ATTEMPT_SCHEMA:
            if rec.get("blind") is True:
                continue
            why = f"a non-blind record ({design}, recognizer {((rec.get('meta') or {}).get('recognizer'))!r})"
        elif not named:
            why = f"an attempt record ({design}) not named *{ATTEMPT_SUFFIX}"
        elif schema != ATTEMPT_SCHEMA:
            why = f"named *{ATTEMPT_SUFFIX} but of schema {schema!r}, not {ATTEMPT_SCHEMA!r} ({design})"
        else:
            if logged is None:
                logged = _logged_attempts(root)
            shas = logged.get(rel)
            now = sha256_file(path)
            if shas and now in shas:
                continue
            why = (f"an attempt record ({design}) with no ledger \"attempt\" entry for {rel}" if not shas else
                   f"an attempt record ({design}) changed after the ledger logged it "
                   f"(logged {', '.join(sorted(s[:12] for s in shas))}, now {now[:12]})")
        strays[rel] = f"{why}; {_RUNS_RULE}"
    return strays


def checklist(root=ROOT, leakage=True, timeout=1800, jobs=3, echo=print):
    """The pre-freeze checklist (PRE_FREEZE). Returns a list of blocking problems (empty = ready).

    The leakage test is part of it because nothing else runs it: test/test_s3.py gates
    test_tempo_leakage on RETRACE_S3_LEAKAGE=1, which neither the fast nor the slow suite sets, so
    the design's own permutation rule was never exercised automatically (review[2] issue 7).
    """
    bad, notes = [], []
    bad += check_changes(root)
    if load_contamination(root) is None:
        bad.append(f"{CONTAMINATION_REL}: missing")
    ev = record_evidence(root)
    bad += [f"stale contamination evidence: {s}" for s in ev["stale"]]
    notes += [f"change-log evidence moved since its entry (a snapshot, not a fault): {m}" for m in ev["moved"][:20]]
    notes += [f"evidence path gone (not blocking): {m}" for m in ev["missing"][:20]]
    echo(f"evidence: {ev['checked']} hashes checked, {len(ev['stale'])} stale (contamination), "
         f"{len(ev['moved'])} moved (change log), {len(ev['missing'])} missing")
    bad += [f"{rel}: {why}" for rel, why in run_strays(root).items()]
    # run_strays() takes an attempt as proven by a ledger line; a ledger whose working copy has a
    # broken hash chain or an unparsable line proves nothing, so the pre-freeze checklist blocks on
    # it here as check() does after the freeze (changes.jsonl F01). The committed versions too: the
    # ledger is the evidence for draw.excluded, and write() refuses a draw on any ledger problem,
    # an unreadable git history included (ledger_entries), so the checklist blocks on the same
    try:
        lproblems = ledger_entries(root)[1]
    except OSError:           # no git executable: the working-tree ledger alone
        lproblems = ledger_entries(root, history=False)[1]
    bad += [f"blind ledger: {q}" for q in lproblems]
    # the freeze publishes TEMPO's IN-SAMPLE figure; the only out-of-sample number beside it is the
    # corpus holdout, and score.py refuses it when it was derived on other code or carries no rates.
    # A freeze that pins a stale or empty estimate is the defect review[1] issues 0 and 1 found.
    oos = score.out_of_sample_problem(root)
    if oos:
        bad.append("out-of-sample estimate: " + oos)
    else:
        doc = score.out_of_sample(root) or {}
        h = doc.get("holdout") or {}
        echo(f"out-of-sample estimate: {h.get('designs')} corpus-holdout designs, {h.get('runs')} runs, "
             f"derived on this code from {(doc.get('source') or {}).get('path')}")
    if leakage:
        from tools.s3 import run as _run  # local: run.py imports this module
        echo("leakage test (TEMPO, file-order arm + "
             f"{_run.FROZEN_PERMUTATIONS} permutations; this takes minutes) ...")
        try:
            rec = _run.run("tempo", write=False, echo=lambda *a: None, timeout=timeout,
                           leakage_arm=True, permutations=_run.FROZEN_PERMUTATIONS, jobs=jobs)
        except BaseException as e:  # noqa: BLE001
            bad.append(f"leakage test did not run: {type(e).__name__}: {e}")
        else:
            leak = rec.get("leakage") or {}
            echo(f"leakage: verdict {leak.get('verdict')}, strong {leak.get('strong')}, "
                 f"distinct answers {(rec.get('spread') or {}).get('distinct_answers')}")
            if not rec.get("valid"):
                bad.append(f"leakage run invalid: {rec.get('invalid_reasons')}")
            if leak.get("verdict") != "pass":
                bad.append(f"leakage test verdict {leak.get('verdict')!r}: strong {leak.get('strong')}, "
                           f"outside {leak.get('outside')}")
            for p in rec.get("problems") or []:
                notes.append("leakage run problem: " + p)
    else:
        bad.append("the leakage test was skipped (--no-leakage): it is part of the checklist")
    # what `freeze write --draw-n` would record as draw.excluded if it ran now, so the lead sees it
    # before the write that fixes it for good (a note: excluding a seen design is the rule, not a fault).
    # A git history the evidence is read from that cannot be read blocks: build() refuses on it
    sproblems = []
    try:
        spent = sorted(spent_designs(root, problems=sproblems))
    except (OSError, ValueError, KeyError, TypeError) as e:
        notes.append(f"draw.excluded: could not compute the spent designs ({type(e).__name__}: {e})")
    else:
        notes.append(f"draw.excluded: `freeze write --candidates {CANDIDATES_REL} --draw-n N` run now would "
                     f"exclude {len(spent)} candidate(s) an earlier blind evaluation has seen "
                     f"(`python -m tools.s3.freeze spent` gives the evidence): {', '.join(spent) or 'none'}")
    bad += [f"draw.excluded evidence: {q}" for q in sproblems]
    for n in notes:
        echo("note: " + n)
    return bad


def truth_files(root=ROOT):
    """{design id: path} for out/s3/truth_<design>.json."""
    out = {}
    for p in sorted(glob.glob(os.path.join(root, "out", "s3", "truth_*.json"))):
        d = os.path.basename(p)[len("truth_"):-len(".json")]
        if not d.endswith(".run"):
            out[d] = p
    return out


def truth_hashes(root=ROOT):
    out = {}
    for d, p in truth_files(root).items():
        with open(p) as f:
            raw = json.load(f)
        out[d] = {"path": os.path.relpath(p, root), "truth_hash": schema.truth_hash(raw),
                  "schema": raw.get("schema"), "design": raw.get("design"),
                  "labeller_sha256": (raw.get("meta") or {}).get("labeller_sha256"), "file_sha256": sha256_file(p)}
    return out


def git(root, *args, strip=True):
    """(returncode, stdout), stdout stripped unless strip=False: `git status --porcelain` output
    must not be, since its first line may start with a space (" M path") that is part of the
    two-column status."""
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)
    return r.returncode, (r.stdout.strip() if strip else r.stdout)


def git_head(root=ROOT):
    rc, out = git(root, "rev-parse", "HEAD")
    return out if rc == 0 else None


# How the ledger, the truth files and labels.json are read from git history: every ref (--all) AND
# the reflog (--reflog: a version orphaned by reset, amend or rebase is still read while the reflog
# holds it), with --full-history (a version on a merged and then deleted side branch is not
# simplified away). Each only adds versions; every reader deduplicates what it takes from them.
HISTORY_LOG = ("log", "--all", "--reflog", "--full-history")


def _is_shallow(root):
    """True in a shallow clone. `git rev-parse --is-shallow-repository` needs git 2.15; older git
    echoes the unknown flag back, so the marker file `git rev-parse --git-path shallow` names is
    checked as well (it exists exactly when the repository is shallow, on any git version)."""
    if git(root, "rev-parse", "--is-shallow-repository")[1] == "true":
        return True
    rc, rel = git(root, "rev-parse", "--git-path", "shallow")
    return rc == 0 and bool(rel) and os.path.exists(rel if os.path.isabs(rel) else os.path.join(root, rel))


def _history(root, *args):
    """(stdout, problem) of `git log --all --reflog --full-history <args>`. A root that is not a
    git repository has no history: ("", None), as before. In one (git rev-parse --git-dir
    succeeds) a failed read is a problem, never "no history": the history is the evidence of
    earlier blind evaluations. So is a SHALLOW clone's history (`git rev-parse
    --is-shallow-repository` prints "true"): git log reads it and exits 0, but every commit
    before the clone's depth is missing, so a ledger attempt, a truth or a labels.json version
    committed and deleted before the cut reads as never having existed. The part that can be read
    is returned with the problem, so it still counts. No git executable: OSError, for the caller."""
    rc, out = git(root, *HISTORY_LOG, *args)
    if rc == 0:
        if _is_shallow(root):
            return out, ("the git history is truncated: this is a shallow clone (`git rev-parse "
                         "--is-shallow-repository` prints true), so `git log` exits 0 without the commits "
                         "before its depth; `git fetch --unshallow` reads the whole history")
        return out, None
    if git(root, "rev-parse", "--git-dir")[0] != 0:
        return "", None
    return "", f"the git history could not be read (`git {' '.join(HISTORY_LOG + args)}` exited {rc})"


def _show(root, commit, rel):
    """(text, problem) of `rel` at a commit _history() listed for it. The commit that DELETED rel
    is listed too and holds no such file: (None, None). A file the commit's tree lists but git
    cannot show (a missing blob), or a tree git cannot list: (None, problem)."""
    rc, txt = git(root, "show", f"{commit}:{rel}")
    if rc == 0:
        return txt, None
    rc2, entry = git(root, "ls-tree", commit, "--", rel)
    if rc2 == 0 and not entry:
        return None, None
    return None, f"{rel} at commit {commit[:12]} is in the git history but could not be read (git show exited {rc})"


def freeze_hash(fr):
    return canonical_hash({k: fr.get(k) for k in HASHED})


def load(root=ROOT):
    p = os.path.join(root, FREEZE_REL)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


# ----------------------------------------------------------------------------------------------
# the draw


def _thirdparty(root):
    """tools/s3/thirdparty.py of `root` (the frozen file is what draws)."""
    path = os.path.join(root, THIRDPARTY_REL)
    if os.path.realpath(root) == os.path.realpath(ROOT):
        from tools.s3 import thirdparty
        return thirdparty
    spec = importlib.util.spec_from_file_location(f"s3_thirdparty_{abs(hash(path))}", path)
    mod = importlib.util.module_from_spec(spec)
    saved = list(sys.path)   # the module puts its own root on sys.path; keep ours
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = saved
    return mod


DRAW_RULE = ("tools/s3/thirdparty.py draw(blind_seed, n, exclude=the ids of draw.excluded): the candidates in "
             "draw.excluded (designs an earlier blind evaluation has seen, computed once when this freeze was "
             "written: freeze.spent_designs) are removed first; then the n remaining candidates with the lowest "
             "sha256(seed|id), then reserves in the same order")


def _cache_form(ident):
    """The file-name stem thirdparty.py gives a candidate's cached download: _cache_path() of
    id.replace("/", "__") + an extension (.gds, .oas, .prep.gds, .tar.gz)."""
    return re.sub(r"[^\w.\-]", "_", ident.replace("/", "__"))


def _cache_dirs(root):
    """The download cache under root, and (for this checkout only) the one RETRACE_TT_CACHE names
    for thirdparty.py, when it points elsewhere. A cache can only add a spent design."""
    dirs = [os.path.join(root, CACHE_REL)]
    env = os.environ.get("RETRACE_TT_CACHE")
    if env and os.path.realpath(root) == os.path.realpath(ROOT) and \
            os.path.realpath(env) != os.path.realpath(dirs[0]):
        dirs.append(env)
    return dirs


def _run_record_design(name):
    """The file-safe design (score.design_id) a blind run record's file name carries (_RUN_NAME:
    run.py _write_record's blind-<design>-<utc>-<hash>[.attempt].json), or None for another name."""
    m = _RUN_NAME.match(name)
    return score.design_id(m.group(1)) if m else None


def _json_design(path):
    """The "design" field of a JSON file, or None (unreadable, not an object, not a string)."""
    try:
        with open(path) as f:
            design = json.load(f).get("design")
    except (OSError, ValueError, AttributeError):
        return None
    return design if isinstance(design, str) else None


def _truth_history(root, problems=None):
    """{path relative to root: design field or None} of every out/s3/truth_<id>.json that git
    history holds (HISTORY_LOG: any ref and the reflog, --full-history) and that is gone from disk.
    The design field is read from the newest commit that still has the file. No git, or no
    repository: {}. In a repository, a history or a version that cannot be read is appended to
    `problems` (when given) instead of being taken for no history."""
    try:
        out, prob = _history(root, "--format=@%H", "--name-only", "--", "out/s3/truth_*.json")
    except OSError:
        return {}
    if prob and problems is not None:
        problems.append(f"truth files (git history): {prob}")
    commits = {}    # path -> [commit, ...], newest first
    head = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("@"):
            head = line[1:]
        elif line and head:
            d, n = os.path.split(line)
            if d == "out/s3" and n.startswith("truth_") and n.endswith(".json") and not n.endswith(".run.json"):
                commits.setdefault(line, []).append(head)
    gone = {}
    for rel, hs in sorted(commits.items()):
        if os.path.exists(os.path.join(root, rel)):
            continue
        design = None
        for h in hs:
            txt, prob = _show(root, h, rel)
            if prob and problems is not None:
                problems.append(f"truth files (git history): {prob}")
            if txt is not None:
                try:
                    design = json.loads(txt).get("design")
                except (ValueError, AttributeError):
                    design = None
                break
        gone[rel] = design if isinstance(design, str) else None
    return gone


def _labels_named(doc):
    """[(design as the file spells it, what)] one version of labels.json names, `what` one of
    "drawn", "replaced", "reserve used" (make_labels.py's layout):

      draw.blind          every id: drawn
      designs[]           a row per design the labeller worked on: its id and design_id are drawn,
                          or, when the row `replaces` a drawn design, a reserve used; that
                          `replaces` is replaced
      replacements[]      the replacement rows again (a bare id: a reserve used)
      reserves_used       an int k: the first k of draw.reserve, the reserves being used in order

    draw.reserve beyond reserves_used is only LISTED and names nothing. A version that is not an
    object, and fields of other types, name nothing."""
    if not isinstance(doc, dict):
        return []
    dr = doc.get("draw") if isinstance(doc.get("draw"), dict) else {}
    lst = lambda v: v if isinstance(v, list) else []  # noqa: E731
    out = [(x, "drawn") for x in lst(dr.get("blind"))]
    used = doc.get("reserves_used")
    if type(used) is int and used > 0:
        out += [(x, "reserve used") for x in lst(dr.get("reserve"))[:used]]
    for key in ("designs", "replacements"):
        for r in lst(doc.get(key)):
            if isinstance(r, dict):
                rep = r.get("replaces")
                what = "reserve used" if rep or key == "replacements" else "drawn"
                out += [(r.get("id"), what), (r.get("design_id"), what)] + ([(rep, "replaced")] if rep else [])
            elif key == "replacements":
                out.append((r, "reserve used"))
    return [(x, what) for x, what in out if isinstance(x, str)]


def _labels_freeze(doc):
    """The freeze_hash one version of labels.json records (make_labels.py writes the freeze it
    labelled under as freeze.freeze_hash), as stored; None when the version records none."""
    fz = doc.get("freeze") if isinstance(doc, dict) else None
    return fz.get("freeze_hash") if isinstance(fz, dict) else None


def _labels_versions(root, problems=None):
    """Every version of labels.json: the working tree's and each one git history holds
    (HISTORY_LOG), as parsed JSON (None where it is not JSON). No git, or no repository: the
    working tree's alone. In a repository, a history or a version that cannot be read is appended
    to `problems` (when given) instead of being taken for no history."""
    texts = []
    p = os.path.join(root, LABELS_REL)
    if os.path.exists(p):
        with open(p) as f:
            texts.append(f.read())
    try:
        out, prob = _history(root, "--format=%H", "--", LABELS_REL)
        found = [_show(root, h, LABELS_REL) for h in out.split()]      # [(text, problem)]
    except OSError:           # no git executable: the working tree's alone
        prob, found = None, []
    for q in [prob] + [q for _t, q in found]:
        if q and problems is not None:
            problems.append(f"{LABELS_REL} (git history): {q}")
    texts += [t for t, _q in found if t is not None]
    docs = []
    for t in texts:
        try:
            docs.append(json.loads(t))
        except ValueError:
            docs.append(None)
    return docs


def spent_designs(root=ROOT, candidates=None, problems=None):
    """{candidate id: [evidence, ...]}: the candidates an earlier evaluation has SEEN, so a new
    draw must not offer them as unseen. Six sources, each of which can only ADD:

      ledger  every "attempt" event of the blind ledger, working tree and git history
              (ledger_entries); its "design" is run.py's --design (normalised at the source
              since run.py normalises it, but an older ledger line may carry any spelling
              score.design_id() accepts: "tt09__x", "tt09/x", "tt:tt09/x"), so it is normalised
              with score.design_id() before it is compared
      run     every blind run record out/s3/runs/blind-*.json, results and *.attempt.json alike
              (all_blind_attempts() and blind_results() count each as an attempt): its "design"
              field and the design its file name carries (_run_record_design), both normalised, so
              a record whose ledger line is missing, or which cannot be read, still spends its design
      truth   every truth file out/s3/truth_<id>.json on disk: its file-name id, and its "design"
              field in any spelling, normalised the same way (score.load_truth() matches it so);
              and every such file git history holds that is gone from disk (_truth_history)
      labels  every design out/s3/blind/labels.json names as drawn, replaced or used as a reserve
              (_labels_named), in the working tree and in every committed version (git history,
              HISTORY_LOG: any ref and the reflog; _labels_versions), under whatever freeze that
              version records, normalised the same way: a drawn design the labeller fetched but
              could not label is replaced and never run, and the cache that would show it is
              git-ignored, so in a fresh clone this committed record is its only evidence. A
              reserve it merely LISTS is not spent
      anon    every anonymised layout out/s3/blind/anon/<score.design_id>.gds (the labeller's)
      cache   every file in the download cache's layout/ and rtl/ (_cache_dirs): a fetched design
              has been seen by the labeller even if labelling failed; no cache adds nothing

    The mapping runs FORWARD, from each candidate of the list (`candidates`, default
    out/s3/blind/candidates.json) to the forms a source would carry, never by splitting a file-safe
    id on "__" (a macro can contain "__"). So only candidates can be spent: the puzzle, TEMPO, the
    excluded pilot and probe designs and any non-candidate are ignored. Evidence strings start
    "ledger: ", "run: ", "truth: ", "labels: ", "anon: " or "cache: " and name no machine path:
    repository files relative to root, cache files relative to the cache root ("cache:
    layout/<name>"), whichever cache (RETRACE_TT_CACHE or out/s3/blind/cache) holds them, because
    the evidence is recorded in FREEZE.json. No candidate list: nothing can be spent, {}.

    `problems` (a list, when given) receives every git history of the truth files and of
    labels.json that could not be read in a git repository (_history, _show), a shallow clone's
    truncated history included: the result is then short of evidence, so build() refuses to
    record a draw and the checklist blocks. The ledger's own problems are ledger_entries()'
    (write() and the checklist read them there).

    build() calls this ONCE and records the result in FREEZE.json draw.excluded; draw() reads the
    recorded list and never this function. Computed live, the designs a freeze's own evaluation
    labels and runs would become spent, the re-derived draw would move, and check() would refuse
    the truths it had accepted."""
    path = candidates or os.path.join(root, CANDIDATES_REL)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        ids = [c["id"] for c in json.load(f).get("candidates", [])]
    by_id = {}      # file-safe design id a ledger entry, run record or truth file carries -> evidence
    cached = []     # (file name, evidence) of every cached download
    try:
        entries = ledger_entries(root)[0]
    except OSError:           # no git executable: the working-tree ledger alone
        entries = ledger_entries(root, history=False)[0]
    for e in entries:
        if e.get("event") == "attempt" and isinstance(e.get("design"), str):
            by_id.setdefault(score.design_id(e["design"]), set()).add(
                f"ledger: attempt {e.get('attempt')} under freeze {str(e.get('freeze_hash'))[:12]}")
    for p in sorted(glob.glob(os.path.join(root, RUNS_REL, "blind-*.json"))):
        ev = f"run: {os.path.relpath(p, root)}"
        for design in (_run_record_design(os.path.basename(p)), _json_design(p)):
            if design is not None:
                by_id.setdefault(score.design_id(design), set()).add(ev)
    for d, p in truth_files(root).items():
        ev = f"truth: {os.path.relpath(p, root)}"
        by_id.setdefault(d, set()).add(ev)
        design = _json_design(p)            # unreadable: its file name still counts
        if design is not None:
            by_id.setdefault(score.design_id(design), set()).add(ev)
    for rel, design in _truth_history(root, problems).items():
        ev = f"truth: {rel} (deleted from disk; in git history)"
        by_id.setdefault(os.path.basename(rel)[len("truth_"):-len(".json")], set()).add(ev)
        if design is not None:
            by_id.setdefault(score.design_id(design), set()).add(ev)
    for doc in _labels_versions(root, problems):
        fh = str(_labels_freeze(doc))[:12]
        for design, what in _labels_named(doc):
            by_id.setdefault(score.design_id(design), set()).add(f"labels: {what} under freeze {fh} ({LABELS_REL})")
    adir = os.path.join(root, ANON_REL)
    anon = set(os.listdir(adir)) if os.path.isdir(adir) else set()
    for base in _cache_dirs(root):
        for kind in CACHE_KINDS:
            d = os.path.join(base, kind)
            for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                cached.append((n, f"cache: {kind}/{n}"))     # relative to the cache root, never a machine path
    out = {}
    for cid in ids:
        fid, form = score.design_id(cid), _cache_form(cid) + "."
        ev = by_id.get(fid, set()) | {e for n, e in cached if n.startswith(form)}
        if fid + ".gds" in anon:
            ev.add(f"anon: {os.path.join(ANON_REL, fid + '.gds')}")
        if ev:
            out[cid] = sorted(ev)
    return out


def draw(fr, root=ROOT):
    """thirdparty.draw(blind_seed, n) under the freeze: {"blind": [ids], "reserve": [ids]} (the
    reserves cut at max_reserves), or None without candidates or a draw size.

    The ids of the RECORDED draw.excluded are passed as `exclude` -- never spent_designs() now,
    which grows as this very freeze's designs are labelled and run (see there). A record without
    draw.excluded (freeze 1's) passes none and draws exactly as it did."""
    if not fr or not fr.get("blind_candidates") or not (fr.get("draw") or {}).get("n"):
        return None
    kw = {}
    if "excluded" in fr["draw"]:
        kw["exclude"] = [e["id"] for e in fr["draw"]["excluded"]]
    d = _thirdparty(root).draw(fr["blind_seed"], fr["draw"]["n"],
                               path=os.path.join(root, fr["blind_candidates"]["path"]), **kw)
    return {"blind": d["blind"], "reserve": d["reserve"][:fr["draw"].get("max_reserves", 0)]}


def drawn_ids(fr, root=ROOT):
    """File-safe ids (score.design_id) of every design the draw permits: drawn and reserves."""
    d = draw(fr, root)
    return set() if d is None else {score.design_id(x) for x in d["blind"] + d["reserve"]}


def draw_excluded_problems(fr, root=ROOT, truths=None):
    """check()'s tripwire on a recorded draw: every piece of evidence of an EARLIER evaluation
    that names a candidate the draw can still offer (a candidate not in draw.excluded; a record
    without draw.excluded excludes nothing, so deleting the key hides nothing). freeze_hash covers
    draw.excluded, but a hand edit that also recomputes freeze_hash passes that; this does not,
    for the evidence it reads. The evidence, compared by score.design_id() of each side:

      * a blind attempt under ANOTHER freeze: an "attempt" of the ledger (working tree and git
        history) or a readable blind run record in out/s3/runs, whose freeze_hash is not this
        freeze's own. Attempts under this freeze's own hash are its own evaluation and are
        ignored; attempts under another freeze are the earlier evaluations write() excluded;
      * a truth of this freeze's own frozen `truth` block: labelled before this freeze was
        written, so spent_designs() saw it. Its key (the file-name id) and, when the file is on
        disk (`truths`: truth_hashes()), its design field. Truths added after the freeze are not
        in the block, and the block does not change;
      * a design a version of labels.json (the working tree's and every committed one, as
        spent_designs() reads them: _labels_versions) records as drawn, replaced or used as a
        reserve (_labels_named) under ANOTHER freeze: the freeze_hash that version records
        (_labels_freeze) is not this freeze's own (a version that records none is not this
        freeze's either). A version written under this freeze's own hash is its own labeller's
        and is ignored, so the check does not move while this freeze is evaluated.

    So a cut of draw.excluded -- even a coordinated one, draw.eligible raised to match and
    freeze_hash recomputed -- is caught for a design whose evidence is any of those. Four kinds of
    evidence spent_designs() reads are NOT read here: the download cache (git-ignored) and the
    anonymised layouts, which this freeze's own evaluation adds to and which record no freeze; a
    blind run record's file name (a record that cannot be read, or has no design field, has no
    freeze to tell it by; of a readable one only the design field is read); and a truth deleted
    from disk before this freeze was written (spent_designs() reads it from git history; it is not
    in the frozen truth block). Truths added after the freeze are not read either (check() accepts
    one only for a drawn design). So a coordinated cut of a design whose only evidence is of those
    four kinds is NOT reliably detectable by check(): the count (draw_eligible_problems) catches only
    an INCONSISTENT cut, and the history of out/s3/FREEZE.json in git (the freeze commit) shows a
    coordinated one. It can surface in check() only incidentally -- through the added-truth rule when
    the shifted draw leaves out a design whose truth was added after the freeze, or, once this
    freeze's own evaluation has recorded a drawn design under its freeze_hash (a ledger attempt, a
    run record, a labels.json), through this function, since a recomputed freeze_hash makes that
    record another freeze's; until that first record nothing of this freeze's own trips here. write() runs this on the record it has just built (its
    self-check). [] without a draw."""
    dr = fr.get("draw") or {}
    if not dr.get("n") or not fr.get("blind_candidates"):
        return []
    try:
        with open(os.path.join(root, fr["blind_candidates"]["path"])) as f:
            cids = [c["id"] for c in json.load(f).get("candidates", [])]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []   # check() reports the candidate list itself as missing or changed
    excluded = {e.get("id") for e in dr.get("excluded") or [] if isinstance(e, dict)}
    drawable = {score.design_id(c): c for c in cids if c not in excluded}
    own = fr.get("freeze_hash")
    bad = []
    try:
        entries = ledger_entries(root)[0]
    except OSError:           # no git executable: the working-tree ledger alone
        entries = ledger_entries(root, history=False)[0]
    for e in entries:
        if e.get("event") == "attempt" and e.get("freeze_hash") != own and isinstance(e.get("design"), str):
            cid = drawable.get(score.design_id(e["design"]))
            if cid:
                bad.append(f"draw.excluded omits {cid}: the blind ledger holds attempt {e.get('attempt')} of it under "
                           f"freeze {str(e.get('freeze_hash'))[:12]}, an earlier evaluation, yet the draw can offer "
                           "it (draw.excluded edited?)")
    for p in sorted(glob.glob(os.path.join(root, RUNS_REL, "blind-*.json"))):
        try:
            with open(p) as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue            # unreadable: no freeze to tell; spent_designs() counts it by name
        if not isinstance(rec, dict) or not isinstance(rec.get("design"), str):
            continue
        fz = rec.get("freeze")
        fh = fz.get("freeze_hash") if isinstance(fz, dict) else None
        cid = drawable.get(score.design_id(rec["design"]))
        if cid and fh != own:
            bad.append(f"draw.excluded omits {cid}: {os.path.relpath(p, root)} is a blind run of it under freeze "
                       f"{str(fh)[:12]}, an earlier evaluation, yet the draw can offer it (draw.excluded edited?)")
    truths = truth_hashes(root) if truths is None else truths
    for d, v in sorted((fr.get("truth") or {}).items()):
        on_disk = (truths.get(d) or {}).get("design")
        for form in {d, score.design_id(on_disk) if isinstance(on_disk, str) else d}:
            cid = drawable.get(form)
            if cid:
                bad.append(f"draw.excluded omits {cid}: its truth {(v or {}).get('path')} is in this freeze's "
                           "frozen truth block (labelled before the freeze), yet the draw can offer it "
                           "(draw.excluded edited?)")
    seen = set()
    for doc in _labels_versions(root):
        fh = _labels_freeze(doc)
        if fh is not None and fh == own:
            continue            # this freeze's own labeller: its own evaluation
        for design, what in _labels_named(doc):
            cid = drawable.get(score.design_id(design))
            msg = (f"draw.excluded omits {cid}: {LABELS_REL} records it as {what} under freeze {str(fh)[:12]}, "
                   "an earlier evaluation, yet the draw can offer it (draw.excluded edited?)")
            if cid and msg not in seen:     # every version that names it alike: once
                seen.add(msg)
                bad.append(msg)
    return bad


def draw_eligible_problems(fr, root=ROOT):
    """check()'s count on a recorded draw: draw.eligible must be an integer equal to the number of
    candidates of the pinned candidate list minus the number of draw.excluded ids that are
    candidates (build() computes it so). It catches an INCONSISTENT cut: an entry removed from
    draw.excluded (or the key deleted) while draw.eligible keeps its value, or draw.eligible
    changed, deleted or made a non-integer on its own. A record without draw.eligible (freeze 1's)
    does not hold either: deleting both keys must not pass.

    It does NOT catch a coordinated cut: an entry removed, draw.eligible raised by one and
    freeze_hash recomputed agree again. The tripwire (draw_excluded_problems) is what catches that,
    and only for a design whose evidence it reads: a ledger attempt, a readable blind run record,
    a frozen truth or a labels.json entry under another freeze. A coordinated cut of a design whose
    only evidence is the git-ignored download cache or an anonymised layout (or a run record's file
    name, or a truth deleted before the freeze: draw_excluded_problems lists what it does not read)
    is NOT reliably detectable by check() -- it can surface only incidentally, as
    draw_excluded_problems explains -- and the history of out/s3/FREEZE.json in git (the freeze
    commit) shows it. [] without a draw, or when the candidate list cannot be read (check()
    reports that list itself)."""
    dr = fr.get("draw") or {}
    if not dr.get("n") or not fr.get("blind_candidates"):
        return []
    try:
        with open(os.path.join(root, fr["blind_candidates"]["path"])) as f:
            cids = [c["id"] for c in json.load(f).get("candidates", [])]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []
    excluded = {e.get("id") for e in dr.get("excluded") or [] if isinstance(e, dict)}
    want = sum(1 for c in cids if c not in excluded)
    got = dr.get("eligible")
    if type(got) is int and got == want:
        return []
    return [f"draw.eligible {got!r} != {want}: the pinned candidate list has {len(cids)} candidates and "
            f"draw.excluded removes {len(cids) - want} of them (draw.excluded or draw.eligible edited?)"]


def _strata(path):
    import collections
    with open(path) as f:
        doc = json.load(f)
    return dict(sorted(collections.Counter(c.get("stratum") for c in doc.get("candidates", [])).items()))


# ----------------------------------------------------------------------------------------------
# the blind ledger


def _ledger_path(root):
    return os.path.join(root, LEDGER_REL)


def _parse_lines(text):
    """[(line, entry)] of every non-blank line. A line that is not JSON, or is JSON but not an
    object ("[1]", "5", "null"), is {"event": "unparsable"}: every reader calls entry.get()."""
    out = []
    for line in text.splitlines():
        if line.strip():
            try:
                e = json.loads(line)
            except ValueError:
                e = None
            out.append((line, e if isinstance(e, dict) else {"event": "unparsable"}))
    return out


def ledger_append(entry, root=ROOT):
    """Append one entry (hash-chained to the previous line). Returns the line's sha256."""
    p = _ledger_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    prev = None
    if os.path.exists(p):
        with open(p) as f:
            lines = [x for x in f.read().splitlines() if x.strip()]
        if lines:
            prev = hashlib.sha256(lines[-1].encode()).hexdigest()
    line = json.dumps({"schema": LEDGER_SCHEMA, "prev": prev, **entry}, sort_keys=True, separators=(",", ":"))
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (line + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    return hashlib.sha256(line.encode()).hexdigest()


def ledger_entries(root=ROOT, history=True):
    """Every ledger entry in the working tree and (history=True) in every committed version of the
    ledger on any ref and in the reflog, deduplicated by line. Returns (entries, problems): a
    broken hash chain in the working copy or a line that cannot be parsed (not JSON, or JSON that
    is not an object) is a problem (and still counts).

    The history is read with HISTORY_LOG: --full-history, because git log's default
    simplification follows only the parent a merge is TREESAME to for the path, so a ledger version
    committed on a side branch that was merged (its ledger resolved to the other side's) and then
    deleted would be skipped; and --reflog, so a version orphaned by reset, amend or rebase is read
    while the reflog holds it. More versions can only add entries, and entries are deduplicated by
    line. In a git repository a history that cannot be read (git log fails, or the repository is
    a shallow clone, whose history git log reads cut short) or a listed version that cannot be
    shown is a problem, never "no history" (_history, _show); a root that is not a git repository
    has no history. No git executable: OSError, for the caller."""
    seen, entries, problems = set(), [], []
    p = _ledger_path(root)
    texts = []
    if os.path.exists(p):
        with open(p) as f:
            texts.append(("working tree", f.read()))
    if history:
        out, prob = _history(root, "--format=%H", "--", LEDGER_REL)
        if prob:
            problems.append(f"ledger (git history): {prob}")
        for h in out.split():
            txt, prob = _show(root, h, LEDGER_REL)
            if prob:
                problems.append(f"ledger (git history): {prob}")
            if txt is not None:
                texts.append((h[:12], txt))
    for where, txt in texts:
        prev = None
        for line, e in _parse_lines(txt):
            if where == "working tree" and e.get("prev") != prev:
                problems.append(f"ledger ({where}): hash chain broken before {line[:80]}")
            prev = hashlib.sha256(line.encode()).hexdigest()
            if e.get("event") == "unparsable":
                problems.append(f"ledger ({where}): unparsable line {line[:80]}")
            if line not in seen:
                seen.add(line)
                entries.append(e)
    return entries, problems


def ledger_uncommitted(root=ROOT):
    """Number of working-tree ledger lines not in the ledger committed at HEAD."""
    p = _ledger_path(root)
    if not os.path.exists(p):
        return 0
    with open(p) as f:
        cur = [x for x in f.read().splitlines() if x.strip()]
    rc, txt = git(root, "show", f"HEAD:{LEDGER_REL}")
    committed = set(txt.splitlines()) if rc == 0 else set()
    return sum(1 for x in cur if x not in committed)


def blind_results(design, fhash, root=ROOT):
    """Every blind attempt of exactly `design` under the freeze `fhash`: run records (attempts,
    results, scorings) in out/s3/runs and attempt entries of the ledger (working tree and git
    history). Unreadable records count as existing. Designs are compared as score.design_id()
    normalises them (the record's field, the ledger's field, the name of an unreadable record and
    `design` alike), so respelling a design ("tt:tt09/x" for "tt09__x") cannot pass run.py's
    second-attempt guard."""
    want = score.design_id(design)
    out = []
    for p in sorted(glob.glob(os.path.join(root, RUNS_REL, "blind-*.json"))):
        try:
            with open(p) as f:
                rec = json.load(f)
            if not isinstance(rec, dict):
                raise ValueError("not a JSON object")
        except (OSError, ValueError):
            n = os.path.basename(p)
            if _run_record_design(n) == want or n.startswith((f"blind-{design}-", f"blind-{want}-")):
                out.append(os.path.relpath(p, root))  # unreadable counts as existing: never silently replaced
            continue
        if isinstance(rec.get("design"), str) and score.design_id(rec["design"]) == want and \
                (rec.get("freeze") or {}).get("freeze_hash") == fhash:
            out.append(os.path.relpath(p, root))
    entries, _problems = ledger_entries(root)
    for e in entries:
        if e.get("event") == "attempt" and isinstance(e.get("design"), str) and \
                score.design_id(e["design"]) == want and e.get("freeze_hash") == fhash:
            tag = f"ledger attempt {e.get('attempt')} ({e.get('record')})"
            if e.get("record") not in out:
                out.append(tag)
    return out


def all_blind_attempts(root=ROOT):
    """Every blind attempt on record under any freeze (ledger with history, and run records)."""
    entries, _p = ledger_entries(root)
    out = [f"{e.get('design')} under {str(e.get('freeze_hash'))[:12]} (attempt {e.get('attempt')})"
           for e in entries if e.get("event") == "attempt"]
    for p in sorted(glob.glob(os.path.join(root, RUNS_REL, "blind-*.json"))):
        out.append(os.path.relpath(p, root))
    return out


# ----------------------------------------------------------------------------------------------
# write / check


def pin_design(design, root=ROOT):
    """{"files": {path: sha256}, "netlist_sha256"} for a design (extracts it: TEMPO ~20-60 s)."""
    from tools.s3 import run
    files = run.design_files(design)
    nl, _key = run.load_design(design)
    rel = lambda p: os.path.relpath(p, root) if os.path.abspath(p).startswith(root + os.sep) else p  # noqa: E731
    return {"files": {rel(p): sha256_file(p) for p in files}, "netlist_sha256": netlist_hash(nl)}


def build(root=ROOT, candidates=None, notes=(), draw_n=None, max_reserves=None, designs=(), supersedes=None):
    # the designs an earlier blind evaluation has seen, computed ONCE, here, and recorded in
    # draw.excluded (inside freeze_hash); draw() reads that record, never a live recomputation
    sproblems = []
    spent = spent_designs(root, candidates, sproblems) if candidates and draw_n else {}
    if sproblems:
        # the exclusion is fixed for good by this write: evidence that could not be read cannot be excluded
        raise SystemExit("refusing to record a draw: the evidence for draw.excluded could not be read:\n  "
                         + "\n  ".join(sproblems[:10]))
    eligible = None
    if candidates and draw_n:
        with open(candidates) as f:
            cids = [c["id"] for c in json.load(f).get("candidates", [])]
        eligible = sum(1 for c in cids if c not in spent)
        if eligible < int(draw_n):
            # thirdparty.draw() takes what is left without complaint, so a short draw would be
            # recorded as a draw of n and evaluated as fewer: refuse it here, before anything is written
            raise SystemExit(f"refusing to record a draw of {int(draw_n)}: only {eligible} of {len(cids)} "
                             f"candidates remain after excluding the {len(spent)} an earlier blind evaluation has "
                             f"seen (draw.excluded; `python -m tools.s3.freeze spent` lists them)")
    fr = {"schema": FREEZE_SCHEMA,
          "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
          "code": code_hashes(root), "extractor_code": extractor_hashes(root), "info_code": info_hashes(root),
          "packages": package_versions(),
          "truth": {d: {k: v[k] for k in ("path", "truth_hash")} for d, v in truth_hashes(root).items()},
          "inputs": {d: pin_design(d, root) for d in designs},
          "class_map": score.class_map(), "git_head": git_head(root),
          "blind_seed": secrets.token_hex(16),
          "blind_candidates": ({"path": os.path.relpath(os.path.abspath(candidates), root),
                                "sha256": sha256_file(candidates)} if candidates else None),
          "draw": ({"n": int(draw_n), "max_reserves": int(max_reserves if max_reserves is not None else draw_n),
                    "rule": DRAW_RULE, "strata": _strata(candidates),
                    "excluded": [{"id": i, "evidence": spent[i]} for i in sorted(spent)],
                    "eligible": eligible}
                   if candidates and draw_n else None),
          "supersedes": supersedes,
          "protocol": dict(PROTOCOL), "records": record_hashes(root), "contamination": load_contamination(root),
          # the records' OWN evidence, re-hashed at the freeze: "records" pins the two files, this says
          # whether what they cite still is what they say it is (review[2] issue 5)
          "records_evidence": record_evidence(root),
          "notes": list(notes)}
    fr["freeze_hash"] = freeze_hash(fr)
    return fr


def check(root=ROOT, fr=None, require_commit=True):
    """Mismatches between the working tree and FREEZE.json (empty list = the freeze holds)."""
    fr = load(root) if fr is None else fr
    if fr is None:
        return [f"no {FREEZE_REL}: run `python -m tools.s3.freeze write` and commit it"]
    bad = []
    if fr.get("schema") != FREEZE_SCHEMA:
        bad.append(f"FREEZE.json schema {fr.get('schema')!r} != {FREEZE_SCHEMA}")
    if fr.get("freeze_hash") != freeze_hash(fr):
        bad.append("FREEZE.json freeze_hash does not match its content (edited by hand?)")
    now = code_hashes(root)
    for label, frozen, cur in (("", fr.get("code", {}), now),
                               ("extractor ", fr.get("extractor_code", {}), extractor_hashes(root))):
        for p in sorted(set(frozen) | set(cur)):
            a, b = frozen.get(p), cur.get(p)
            if a is None:
                bad.append(f"{label}{p}: added after the freeze")
            elif b is None:
                bad.append(f"{label}{p}: removed after the freeze")
            elif a != b:
                bad.append(f"{label}{p}: changed after the freeze")
    pk = package_versions()
    for k, v in (fr.get("packages") or {}).items():
        if pk.get(k) != v:
            bad.append(f"package {k}: {pk.get(k)} != frozen {v}")
    th = truth_hashes(root)
    frozen_truth = fr.get("truth", {})
    for d, v in frozen_truth.items():
        if d not in th:
            bad.append(f"truth {v['path']}: missing")
        elif th[d]["truth_hash"] != v["truth_hash"]:
            bad.append(f"truth {v['path']}: truth_hash changed after the freeze")
    added = sorted(set(th) - set(frozen_truth))
    if added:
        try:
            permitted = drawn_ids(fr, root)
        except (Exception, SystemExit) as e:
            permitted = set()
            bad.append(f"the blind draw failed: {e}")
        tp_frozen = fr.get("code", {}).get(THIRDPARTY_REL)
        tp_ok = tp_frozen is not None and now.get(THIRDPARTY_REL) == tp_frozen
        for d in added:
            v = th[d]
            if d not in permitted:
                bad.append(f"truth {v['path']}: added after the freeze and not a drawn design")
            elif not tp_ok:
                bad.append(f"truth {v['path']}: drawn, but the labeller {THIRDPARTY_REL} is not the frozen file")
            elif score.design_id(v.get("design")) != d:
                bad.append(f"truth {v['path']}: its design {v.get('design')!r} is not {d}")
            elif v.get("labeller_sha256") not in (None, tp_frozen):
                bad.append(f"truth {v['path']}: labelled by another {THIRDPARTY_REL} ({str(v['labeller_sha256'])[:12]})")
    if canonical_hash(fr.get("class_map")) != canonical_hash(score.class_map()):
        bad.append("class map changed after the freeze")
    if canonical_hash(fr.get("protocol")) != canonical_hash(PROTOCOL):
        bad.append("evaluation protocol (freeze.PROTOCOL) changed after the freeze")
    for rel, h in (fr.get("records") or {}).items():
        p = os.path.join(root, rel)
        cur = sha256_file(p) if os.path.exists(p) else None
        if h is None:
            bad.append(f"{rel}: missing at the freeze")
        elif cur != h:
            bad.append(f"{rel}: {'missing' if cur is None else 'changed'} after the freeze")
    if canonical_hash(fr.get("contamination")) != canonical_hash(load_contamination(root)):
        bad.append(f"{CONTAMINATION_REL}: differs from the record in FREEZE.json")
    if fr.get("blind_candidates"):
        p = os.path.join(root, fr["blind_candidates"]["path"])
        if not os.path.exists(p) or sha256_file(p) != fr["blind_candidates"]["sha256"]:
            bad.append(f"blind candidate list {fr['blind_candidates']['path']}: missing or changed")
    bad += draw_excluded_problems(fr, root, th)
    bad += draw_eligible_problems(fr, root)
    _entries, lproblems = ledger_entries(root, history=False)
    bad += lproblems
    if require_commit:
        head = git_head(root)
        if head is None:
            bad.append("not a git repository: the freeze must be a commit")
        else:
            if fr.get("git_head") and git(root, "merge-base", "--is-ancestor", fr["git_head"], head)[0] != 0:
                bad.append(f"frozen HEAD {str(fr.get('git_head'))[:12]} is not an ancestor of HEAD {head[:12]}")
            paths = [FREEZE_REL] + list(fr.get("code", {})) + [r for r, h in (fr.get("records") or {}).items() if h]
            for p in paths:
                if git(root, "ls-files", "--error-unmatch", p)[0] != 0:
                    bad.append(f"{p}: not committed (the freeze is a commit of tools/s3/*.py and FREEZE.json)")
            # unstripped: a stripped first line " M path" would lose its first column and then, cut
            # at [3:], the first letter of its path
            _rc, diff = git(root, "status", "--porcelain", "--ignored", "--", *paths, strip=False)
            for line in diff.splitlines():
                if not line.startswith(("??", "!!")):   # untracked/ignored ones are reported above
                    bad.append(f"{line[3:]}: uncommitted change")
    return bad


def write(root=ROOT, candidates=None, notes=(), force=False, draw_n=None, max_reserves=None, designs=(),
          supersede=None):
    p = os.path.join(root, FREEZE_REL)
    old = load(root)
    supersedes = None
    if old is not None and not force:
        raise SystemExit(f"{p} exists (freeze {old.get('freeze_hash', '')[:12]}); use --force to replace it")
    prior = all_blind_attempts(root)
    if prior:
        if not supersede:
            raise SystemExit(f"refusing to write a freeze while blind attempts exist ({len(prior)}: {prior[:5]}); "
                             "give --supersede REASON to record why")
        supersedes = {"reason": supersede, "previous_freeze": (old or {}).get("freeze_hash"), "attempts": prior}
    if candidates and not draw_n:
        raise SystemExit("--candidates needs --draw-n (the number of blind designs)")
    if candidates and draw_n:
        # the ledger is the evidence for draw.excluded (spent_designs), and the exclusion is fixed for
        # good by this write: a broken chain or an unparsable line, in the working tree or in any
        # committed version, means that evidence cannot be read as written
        lproblems = ledger_entries(root)[1]
        if lproblems:
            raise SystemExit("refusing to record a draw: the blind ledger, the evidence for draw.excluded, has "
                             "problems (working tree and git history):\n  " + "\n  ".join(lproblems[:10]))
    missing = [rel for rel, h in record_hashes(root).items() if h is None]
    if missing:
        raise SystemExit(f"refusing to write a freeze without {missing} (S3_DESIGN 4.4: the change log and the "
                         "contamination record are part of the freeze)")
    bad = check_changes(root)
    if bad:
        raise SystemExit("refusing to write a freeze: the change log is malformed: " + "; ".join(bad[:5]))
    ev = record_evidence(root)
    if ev["stale"] and not force:
        raise SystemExit("refusing to write a freeze: the records cite evidence that has changed since they were "
                         "written (refresh the record, or --force):\n  " + "\n  ".join(ev["stale"][:10]))
    fr = build(root, candidates, notes, draw_n, max_reserves, designs, supersedes)
    # the self-check: build() reads spent_designs() first and truth_hashes() after it, so a truth
    # labelled, or an attempt logged under another freeze, in between is in the frozen truth block
    # (or the ledger) and not in draw.excluded. check()'s tripwire on the record just built sees
    # exactly that; nothing is written while it reports anything
    selfcheck = draw_excluded_problems(fr, root)
    if selfcheck:
        raise SystemExit("refusing to write a freeze: the self-check of the draw just built failed (evidence of "
                         "an earlier blind evaluation appeared while it was built; run `freeze write` again):\n  "
                         + "\n  ".join(selfcheck[:10]))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(fr, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)
    return fr


def write_summary(fr):
    """The line `freeze write` prints: the freeze, its code, truths and pinned designs, and the draw
    with the number of designs it excludes as seen by an earlier blind evaluation."""
    dr = fr.get("draw")
    drew = (f"draw n={dr['n']} (at most {dr['max_reserves']} reserves), {len(dr.get('excluded') or [])} "
            f"design(s) an earlier blind evaluation has seen excluded (draw.excluded), "
            f"{dr.get('eligible')} candidate(s) eligible" if dr
            else "no blind draw recorded")
    return (f"wrote {FREEZE_REL}: freeze {fr['freeze_hash'][:12]}, {len(fr['code'])} code files, "
            f"truths {sorted(fr['truth'])}, pinned designs {sorted(fr['inputs'])}, {drew}, "
            f"HEAD {str(fr['git_head'])[:12]}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="write out/s3/FREEZE.json (then commit it with tools/s3/*.py)")
    w.add_argument("--candidates", help="the third-party blind candidate list registered before development")
    w.add_argument("--draw-n", type=int, help="number of blind designs drawn from the candidates")
    w.add_argument("--max-reserves", type=int, help="reserves that may replace unlabellable drawn designs "
                   "(default: the draw size)")
    w.add_argument("--designs", nargs="*", default=[], help="designs whose inputs and netlist to pin "
                   "(extracts each: tempo, puzzle)")
    w.add_argument("--note", action="append", default=[], help="a declaration recorded in the freeze")
    w.add_argument("--force", action="store_true", help="replace an existing freeze that has no blind attempts")
    w.add_argument("--supersede", help="write although blind attempts exist; the reason is recorded")
    sub.add_parser("check", help="list mismatches between the tree and the freeze (exit 1 if any)")
    cl = sub.add_parser("checklist", help="the pre-freeze checklist: the records, their evidence hashes, "
                        "out/s3/runs, and the TEMPO leakage test (exit 1 if anything blocks)")
    cl.add_argument("--no-leakage", action="store_true", help="skip the leakage test (recorded as a blocking item)")
    cl.add_argument("--jobs", type=int, default=3, help="recognizer children at once in the leakage test")
    cl.add_argument("--timeout", type=int, default=1800)
    sub.add_parser("show", help="print FREEZE.json")
    sub.add_parser("draw", help="print the drawn third-party designs under the freeze")
    sp = sub.add_parser("spent", help="print the candidates an earlier blind evaluation has seen (what `write "
                        "--draw-n` would record as draw.excluded now; read-only)")
    sp.add_argument("--candidates", help=f"the candidate list (default {CANDIDATES_REL})")
    a = ap.parse_args(argv)
    if a.cmd == "write":
        fr = write(candidates=a.candidates, notes=a.note, force=a.force, draw_n=a.draw_n,
                   max_reserves=a.max_reserves, designs=a.designs, supersede=a.supersede)
        print(write_summary(fr))
        # The whole file list, not only the code: S3_DESIGN 4.4 makes the two test files part of the
        # commit, and out/ is git-ignored, so FREEZE.json, the two records, the candidate list
        # FREEZE.json pins by path and sha256, and the two contamination-pinned artifacts all need
        # -f. A freeze whose candidate list or holdout estimate is untracked cannot be checked, or
        # its published numbers read, by anyone else. See commit_command().
        print("next: " + commit_command(fr))
        print("then: python -m tools.s3.freeze check   (must print \"freeze holds\")")
    elif a.cmd == "check":
        bad = check()
        for b in bad:
            print("MISMATCH:", b)
        print("freeze holds" if not bad else f"{len(bad)} mismatches")
        sys.exit(1 if bad else 0)
    elif a.cmd == "checklist":
        print("pre-freeze checklist:")
        for i, step in enumerate(PRE_FREEZE, 1):
            print(f"  {i}. {step}")
        bad = checklist(leakage=not a.no_leakage, timeout=a.timeout, jobs=a.jobs)
        for b in bad:
            print("BLOCKS:", b)
        print("checklist clear" if not bad else f"{len(bad)} blocking item(s)")
        print(f"\nthe order the last edits, the record writers and `freeze write` must run in "
              f"(FREEZE_ORDER; this checklist is step {FREEZE_ORDER_CHECKLIST_STEP}, and re-running "
              f"it is the only thing that revalidates an edit made after it):")
        for i, step in enumerate(FREEZE_ORDER, 1):
            print(f"  {i}. {step}")
        print(f"  a contamination-cited file edited after step {FREEZE_ORDER_CONTAMINATION_STEP}, or "
              f"any tools/s3/*.py edited after step {FREEZE_ORDER_WRITE_STEP}, puts you back "
              f"at step 1.")
        sys.exit(1 if bad else 0)
    elif a.cmd == "draw":
        print(json.dumps(draw(load()), indent=1))
    elif a.cmd == "spent":
        # the spent designs on stdout; on stderr, and exit 1, every problem that would make `freeze
        # write --draw-n` refuse the draw: an unreadable history of the evidence, a ledger problem
        probs = []
        print(json.dumps(spent_designs(ROOT, a.candidates, probs), indent=1))
        try:
            probs += ledger_entries(ROOT)[1]
        except OSError:
            probs += ledger_entries(ROOT, history=False)[1]
        for q in probs:
            print(f"problem: {q}", file=sys.stderr)
        sys.exit(1 if probs else 0)
    else:
        print(json.dumps(load(), indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
