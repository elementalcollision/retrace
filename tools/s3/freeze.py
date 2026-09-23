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
  draw          {n, max_reserves, rule, strata}: thirdparty.draw(blind_seed, n) picks the n blind
                designs (then reserves in order, at most max_reserves, each replacing a drawn design
                the frozen labeller could not label)
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
reserve) of thirdparty.draw(blind_seed, n) run from the frozen tools/s3/thirdparty.py, (2)
tools/s3/thirdparty.py (the labeller) still has its frozen hash, (3) its "design" field names that
id, and (4) if its meta records the labeller's hash (meta.labeller_sha256), that hash is the frozen
one. Any other added truth file is a mismatch.

Blind ledger (out/s3/blind_ledger.jsonl, force-added and committed by the lead after every
attempt): run.py appends an "attempt" entry before extracting a blind design and a "finish" entry
after; each line carries the sha256 of the previous line. blind_results() and write() read the
ledger in the working tree AND in every committed version (git history), so deleting a record or
the ledger does not erase an attempt.

check() lists every mismatch between the working tree and FREEZE.json. run.py --blind refuses to
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
THIRDPARTY_REL = os.path.join("tools", "s3", "thirdparty.py")
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
    "records": "development records go to out/s3/eval/runs; out/s3/runs holds blind records only",
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
              "out/s3/runs holds blind records only",
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
    rdir = os.path.join(root, RUNS_REL)
    strays = []
    for n in sorted(os.listdir(rdir)) if os.path.isdir(rdir) else []:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(rdir, n)) as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if not rec.get("blind"):
            strays.append(f"{RUNS_REL}/{n}: a non-blind record ({rec.get('design')}, "
                          f"recognizer {((rec.get('meta') or {}).get('recognizer'))!r}); "
                          "out/s3/runs holds blind records only (changes.jsonl C16)")
    bad += strays
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


def git(root, *args):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def git_head(root=ROOT):
    rc, out = git(root, "rev-parse", "HEAD")
    return out if rc == 0 else None


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


def draw(fr, root=ROOT):
    """thirdparty.draw(blind_seed, n) under the freeze: {"blind": [ids], "reserve": [ids]} (the
    reserves cut at max_reserves), or None without candidates or a draw size."""
    if not fr or not fr.get("blind_candidates") or not (fr.get("draw") or {}).get("n"):
        return None
    d = _thirdparty(root).draw(fr["blind_seed"], fr["draw"]["n"],
                               path=os.path.join(root, fr["blind_candidates"]["path"]))
    return {"blind": d["blind"], "reserve": d["reserve"][:fr["draw"].get("max_reserves", 0)]}


def drawn_ids(fr, root=ROOT):
    """File-safe ids (score.design_id) of every design the draw permits: drawn and reserves."""
    d = draw(fr, root)
    return set() if d is None else {score.design_id(x) for x in d["blind"] + d["reserve"]}


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
    out = []
    for line in text.splitlines():
        if line.strip():
            try:
                out.append((line, json.loads(line)))
            except ValueError:
                out.append((line, {"event": "unparsable"}))
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
    ledger on any ref, deduplicated by line. Returns (entries, problems): a broken hash chain in
    the working copy or a line that cannot be parsed is a problem (and still counts)."""
    seen, entries, problems = set(), [], []
    p = _ledger_path(root)
    texts = []
    if os.path.exists(p):
        with open(p) as f:
            texts.append(("working tree", f.read()))
    if history:
        rc, out = git(root, "log", "--all", "--format=%H", "--", LEDGER_REL)
        for h in (out.split() if rc == 0 else []):
            rc2, txt = git(root, "show", f"{h}:{LEDGER_REL}")
            if rc2 == 0:
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
    history). Unreadable records count as existing."""
    out = []
    for p in sorted(glob.glob(os.path.join(root, RUNS_REL, "blind-*.json"))):
        try:
            with open(p) as f:
                rec = json.load(f)
        except (OSError, ValueError):
            if os.path.basename(p).startswith(f"blind-{design}-"):
                out.append(os.path.relpath(p, root))  # unreadable counts as existing: never silently replaced
            continue
        if rec.get("design") == design and (rec.get("freeze") or {}).get("freeze_hash") == fhash:
            out.append(os.path.relpath(p, root))
    entries, _problems = ledger_entries(root)
    for e in entries:
        if e.get("event") == "attempt" and e.get("design") == design and e.get("freeze_hash") == fhash:
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
                    "rule": "tools/s3/thirdparty.py draw(blind_seed, n): the n candidates with the lowest "
                            "sha256(seed|id), then reserves in the same order",
                    "strata": _strata(candidates)} if candidates and draw_n else None),
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
            _rc, diff = git(root, "status", "--porcelain", "--ignored", "--", *paths)
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
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(fr, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)
    return fr


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
    a = ap.parse_args(argv)
    if a.cmd == "write":
        fr = write(candidates=a.candidates, notes=a.note, force=a.force, draw_n=a.draw_n,
                   max_reserves=a.max_reserves, designs=a.designs, supersede=a.supersede)
        print(f"wrote {FREEZE_REL}: freeze {fr['freeze_hash'][:12]}, {len(fr['code'])} code files, "
              f"truths {sorted(fr['truth'])}, pinned designs {sorted(fr['inputs'])}, HEAD {str(fr['git_head'])[:12]}")
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
    else:
        print(json.dumps(load(), indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
