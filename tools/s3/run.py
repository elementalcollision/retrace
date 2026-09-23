"""S3 harness: extract a design's anonymous netlist, run the recognizer on it in an isolated
subprocess, verify its proof claims, map its answer back to the truth's join keys and score it
(PRD S3; docs/S3_DESIGN.md sections 2 and 4, as amended by the lead, 2026-09-21, and by the
scorer review of 2026-09-22).

    python -m tools.s3.run --design tempo [--permutations K] [--jobs N] [--timeout S] [--out DIR]
                                                                          (development)
    python -m tools.s3.run --design tempo --leakage [--permutations K]   (the leakage test, K >= 5)
    python -m tools.s3.run --design puzzle --blind [--rerun-reason TEXT]  (after the freeze)
    python -m tools.s3.run --design <id> --gds FILE [--top CELL] --blind  (a drawn third-party design)
    python -m tools.s3.run --score-record out/s3/runs/blind-<id>-....json (score a blind run whose
                                                                          truth was labelled after it)

Permutations (S3_DESIGN section 2; review of 2026-09-22: the recognizer is not permutation
invariant on TEMPO). A FROZEN evaluation (--blind) runs the recognizer under K >= FROZEN_PERMUTATIONS
(freeze.PROTOCOL, 5) independent os.urandom permutations inside its one attempt and reports every
metric per permutation and as mean / median / min / max ("spread"), plus the pairwise agreement of
the sets of scored-kind structures (kind, join keys, harness outcome). Development runs take one
permutation unless --permutations says otherwise. The LEAKAGE TEST (--leakage: TEMPO, or a blind
design with --blind) adds a
file-order arm: the same netlist with the loader's own ids (seed=None: names sorted, black-box pins
in LEF order), which carry whatever order the names carry; by the design's rule every metric and the
structure-set agreement of the file-order arm must lie within the spread of the K permutations. The
report also gives, per metric, a rank p-value and the rule's own false-alarm rate on the
permutations (each permutation against the other K-1), since a metric that varies between
permutations falls outside the range of K others with probability up to 2/(K+1) (1/3 at K = 5).
All children of one run use ONE staged copy of the recognizer's sources, taken before extraction.

Which designs. Development runs take TEMPO only, always from the frozen snapshot
out/s3/tempo_snapshot (TEMPO_ROOT is set to it; any other TEMPO_ROOT is refused), and synthetic
netlists through evaluate(). The puzzle and third-party designs run only with --blind, i.e. under a
holding freeze (tools/s3/freeze.py): recognizer code never sees them before the freeze.

Steps:
  1. Blind runs only, before anything else: the freeze must hold; the run must be a fresh
     `python -B -X pycache_prefix=<new empty dir> -m tools.s3.run` process (main() re-executes
     itself so; sys.orig_argv is recorded), so no bytecode cache and no wrapper is involved; the
     design's pinned input files must match FREEZE.json; an ATTEMPT record is created exclusively
     (out/s3/runs/blind-<design>-<utc>-<id>.attempt.json, read-only) and its hash appended to the
     blind ledger (out/s3/blind_ledger.jsonl, which the lead commits after every attempt; a blind
     run refuses while the ledger has uncommitted entries). Any earlier attempt of the design under
     the freeze, finished or not, in the runs directory or anywhere in the ledger's git history,
     needs --rerun-reason.
  2. Extraction (tools/retrace/extract.py; TEMPO through tools/tempo/lvs.extract_tempo) and
     load_extraction(seed=None): a Netlist and the Key. Its canonical hash (freeze.netlist_hash)
     is recorded and, for a pinned design in a blind run, must equal FREEZE.json's.
  3. Relabel: every cell id, net id and the port lists are permuted with random.SystemRandom
     (os.urandom); black boxes are anonymised (S3_DESIGN V13): each black-box master becomes
     bb<k> and its pins opaque ids p<j>, both numbered in a random order, directions kept, so a
     macro's LEF bus names (A_DOUT[i]) give no order cue and its name no design cue; pin dicts are
     sorted by (new) pin name; the Library copy drops its file paths. The permutation stays in this
     process (only its sha256 is recorded).
  4. Anonymity: no Key name, black-box macro name or LEF pin name of a black box is reachable from
     the relabelled Netlist (Liberty excluded, as public), and every black-box master and pin of it
     is an opaque id. Library master names stay (they are the public Liberty's cell names; they
     identify the PDK, which is why test/test_s3.py forbids PDK markers and comparisons of master
     strings to literals in recognizer code).
  5. The recognizer runs in a subprocess (run_child) with two layers of isolation:
     * OS level. macOS: `sandbox-exec` with a generated profile: deny by default; file reads only
       of the Python installation, the numpy and z3 package directories, the run's own temporary
       directory (the pickle and a private copy of the recognizer's source files: tools/__init__.py,
       tools/s3/__init__.py, the entry module and the tools.s3 modules it imports, never a harness
       or truth module, never a __pycache__), the dyld/system libraries, and metadata of those
       paths' ancestors; process-exec only of the interpreter and of yices-sat (with the tools its
       wrapper script runs); no network, no writes. Linux (documented alternative, not tested
       here, used only with S3_OS_SANDBOX=bwrap): bubblewrap with --unshare-all (no network) and
       read-only binds of the same paths only (bwrap_argv). Blind runs refuse to start without an
       OS layer; development runs record which layer ran ("none" on a host without one).
     * Python audit hook, installed before the recognizer is imported: the same allow-list for
       open / listdir / subprocess / ctypes.dlopen, ctypes symbol lookups only for z3's Z3_*
       functions, no sockets, no deletes. Fail-closed: the first denial writes the violation to
       the result pipe and ends the process with VIOLATION_RC; the parent marks the run invalid.
     The answer comes back over a dedicated pipe (not stdout), as one JSON line carrying a
     per-run nonce from the parent; anything else on the pipe invalidates the run. The
     recognizer's prints go to stderr. Self-reported fields (timings, peak RSS, the hook's denial
     log) come from the recognizer's own process and are informational only: a determined
     recognizer can forge them in-process. What it cannot forge is file access (OS layer), the
     verification of its proofs (step 6) and the scoring (step 7), which run in this process.
  6. The result is type-checked (validate_result_types; a malformed result invalidates the run),
     schema-checked, checked for Key names and for ids that are not flop cells (both invalidate
     the run), and every structure's proof claims are VERIFIED here (tools/s3/verify.py) on this
     process's own copy of the relabelled netlist.
  7. Flop ids are mapped to join keys and the result is scored against out/s3/truth_<design>.json
     (tools/s3/score.py) together with a structural baseline (copy_graph_baseline) computed here
     from the same anonymous netlist. The scorer is handed the harness's per-structure VERDICTS in
     full, not only the verified flags and outcome classes it took before (2026-09-23), so the
     report's `honesty` block can say what the verified count is worth -- how many of those
     structures had a vacuous hold, the share of the state space their opaque load cases hide,
     whether any carried dead bits or UNCHECKED parameters -- and can split the parameter metric
     into what the harness certified and what it only transcribed. found and verified are carried
     side by side per kind, with the verifier's reason bucket for every unverified structure, into
     the record's `spread` (HEADLINE_METRICS) and into the echoed summary. A blind third-party run
     whose truth does not exist yet (the truth is labelled after the recognizer ran) records the
     result unscored; --score-record scores it later against the drawn truth.
  8. The run record goes to out/s3/eval/runs/<design>-<UTC time>-<sha256[:12]>.json for a
     development run (--out names another directory) and to out/s3/runs/blind-..., read-only, for
     a blind run: out/s3/runs holds blind records only (and each blind run's attempt record, proven by
     the ledger: freeze.run_strays). Records are created exclusively: nothing is
     ever overwritten. Everything after the recognizer is wrapped: an error still writes the
     record, marked invalid. A run of K > 1 permutations records "evaluations" (one per
     permutation, and the file-order arm), "spread" and, with --leakage, "leakage"; a run of one
     permutation keeps the flat layout. Each evaluation also carries "recognize_run": the
     recognizer's own RECOGNIZE_RUN line parsed (stages, control-layer timings, canonical_order,
     bdd). canonical_order is the determinism indicator: a tie left to id order (the stat the
     refinement records only when its round budget was hit), a round budget hit, a missing block,
     or more than one distinct answer over the permutations, each become a "problem" of the run
     (review[2] issue 4); the tied cells and nets a normal run ends with -- the colours the final
     lexsort breaks by id -- become a "note:" line of the same list, because that is the case that
     actually occurs and nothing reported it (review[1] issue 5). Problems never invalidate a run
     by themselves; they are what a report must quote.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import json
import os
import pickle
import random
import re
import resource
import secrets
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.s3 import freeze, schema, score, verify  # noqa: E402
from tools.s3.netlist import YICES_SAT, GateGraph, Library, Netlist, load_extraction, strings_in  # noqa: E402

RUN_SCHEMA = "retrace-s3-run/3"
RUNS = os.path.join(ROOT, "out", "s3", "runs")                 # blind records + their attempts
DEV_RUNS = os.path.join(ROOT, "out", "s3", "eval", "runs")     # development records (default)
FROZEN_PERMUTATIONS = freeze.PROTOCOL["permutations_min"]      # K for every frozen evaluation (>= 5)
EPS = 1e-12
SKY_LIB = os.path.join(ROOT, "pdk", "sky130_fd_sc_hd", "lib", "sky130_fd_sc_hd__tt_025C_1v80.lib")
SKY_LEF = os.path.join(ROOT, "pdk", "sky130_fd_sc_hd", "lef", "sky130_fd_sc_hd.lef")
PUZZLE_GDS = os.path.join(ROOT, "upstream", "puzzle.gds")
TEMPO_SNAPSHOT = os.path.join(ROOT, "out", "s3", "tempo_snapshot")
ENTRY = "tools.s3.recognize"
# tools.s3 modules a recognizer may never import (their files are never copied into the sandbox)
HARNESS_MODULES = frozenset({"schema", "score", "run", "freeze", "verify", "thirdparty"})
DEFAULT_TIMEOUT = 1800
VIOLATION_RC = 86          # the child's exit status after a sandbox denial (fail-closed)
BLIND_PYCACHE_ENV = "RETRACE_S3_BLIND_PYCACHE"
LEDGER_ROOT = ROOT         # the repository whose out/s3/blind_ledger.jsonl records blind attempts


def _peak_mb():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 1e6 if sys.platform == "darwin" else r / 1e3


def _sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


# ----------------------------------------------------------------------------------------------
# designs


def tempo_lvs():
    """tools.tempo.lvs bound to the frozen TEMPO snapshot (never the live TEMPO checkout)."""
    snap = os.path.realpath(TEMPO_SNAPSHOT)
    env = os.environ.get("TEMPO_ROOT")
    if env and os.path.realpath(env) != snap:
        raise SystemExit(f"S3 runs TEMPO from its frozen snapshot only: TEMPO_ROOT={env} is not {snap}")
    os.environ["TEMPO_ROOT"] = snap
    from tools.tempo import lvs
    if os.path.realpath(lvs.TEMPO_ROOT) != snap:
        raise SystemExit(f"tools.tempo.lvs was imported with TEMPO_ROOT={lvs.TEMPO_ROOT}, not the snapshot {snap}")
    return lvs


def tempo_snapshot_check():
    """The snapshot's SHA256SUMS against its files: {path: ok}."""
    sums = os.path.join(TEMPO_SNAPSHOT, "SHA256SUMS")
    out = {}
    if not os.path.exists(sums):
        return {"SHA256SUMS": False}
    for line in open(sums):
        h, _sp, rel = line.strip().partition(" ")
        p = os.path.join(TEMPO_SNAPSHOT, rel.strip())
        out[rel.strip()] = os.path.exists(p) and freeze.sha256_file(p) == h
    return out


def design_files(design, gds=None):
    """The files an extraction of `design` reads (for the freeze's pins and the run record)."""
    if design == "tempo":
        lvs = tempo_lvs()
        return [lvs.GDS, lvs.MACRO_LEF, lvs.STDCELL_LEF, _ihp_liberty(lvs)]
    if design == "puzzle":
        return [PUZZLE_GDS, SKY_LIB, SKY_LEF]
    if gds:
        return [gds, SKY_LIB, SKY_LEF]
    raise SystemExit(f"unknown design {design!r}")


def _ihp_liberty(lvs):
    return os.path.join(lvs.IHP_PDK, "libs.ref/sg13cmos5l_stdcell/lib/sg13cmos5l_stdcell_typ_1p20V_25C.lib")


def load_puzzle():
    from tools.retrace.extract import Extraction
    from tools.retrace.lef import read_lef
    lib, lef = Library(SKY_LIB), read_lef(SKY_LEF)
    ex = Extraction(PUZZLE_GDS, lef, top="puzzle")
    return load_extraction(ex, lib, lef, seed=None)


def load_tempo():
    lvs = tempo_lvs()
    lib = Library(_ihp_liberty(lvs))
    lef = lvs.load_lef()
    ex, _dt, _peak = lvs.extract_tempo(lef=lef)
    return load_extraction(ex, lib, lef, seed=None)


def load_sky130(gds, top=None):
    from tools.retrace.extract import Extraction
    from tools.retrace.lef import read_lef
    lib, lef = Library(SKY_LIB), read_lef(SKY_LEF)
    ex = Extraction(gds, lef, top=top) if top else Extraction(gds, lef)
    return load_extraction(ex, lib, lef, seed=None)


def load_design(design, gds=None, top=None):
    if gds:
        return load_sky130(gds, top)
    if design == "tempo":
        return load_tempo()
    if design == "puzzle":
        return load_puzzle()
    raise SystemExit(f"unknown design {design!r}: give --gds for a third-party sky130 design")


def design_available(design):
    if design == "puzzle":
        return all(os.path.exists(p) for p in (PUZZLE_GDS, SKY_LIB, SKY_LEF))
    if design == "tempo":
        try:
            lvs = tempo_lvs()
        except (Exception, SystemExit):
            return False
        return os.path.exists(lvs.GDS) and os.path.exists(lvs.MACRO_LEF)
    return False


# ----------------------------------------------------------------------------------------------
# relabelling


def _public_library(lib):
    """The same cell models without the Liberty file paths."""
    out = Library.__new__(Library)
    dict.update(out, lib)
    out.paths = ()
    return out


class FileOrder:
    """An rng whose shuffle keeps every list as it is: relabel(nl, FileOrder()) keeps the loader's
    ids (seed=None: sorted names; black-box pins in LEF order). The file-order arm of the leakage
    test only; never a recognizer's input in a scored run."""

    def shuffle(self, x):
        return None


OPAQUE_BB = re.compile(r"bb\d+")
OPAQUE_PIN = re.compile(r"p\d+")


def _opaque(prefix, n):
    """n opaque names, zero-padded so that sorting them keeps their numbering."""
    w = len(str(max(n - 1, 0)))
    return [f"{prefix}{j:0{w}d}" for j in range(n)]


def blackbox_names(nl, rng):
    """{black-box master: (bb<k>, {pin: p<j>})}, masters and pins numbered in an order drawn from
    `rng` (S3_DESIGN V13). Pins an instance uses beyond its black box's pin list (none from the
    loaders) are renamed too, without a direction."""
    masters = list(nl.blackbox)
    rng.shuffle(masters)
    used = {}
    for c, m in enumerate(nl.master):
        if m in nl.blackbox:
            used.setdefault(m, set()).update(nl.pins[c])
    out = {}
    for m, new in zip(masters, _opaque("bb", len(masters))):
        pins = list(nl.blackbox[m]) + sorted(used.get(m, set()) - set(nl.blackbox[m]))
        rng.shuffle(pins)
        out[m] = (new, dict(zip(pins, _opaque("p", len(pins)))))
    return out


def relabel(nl, rng=None):
    """A copy of `nl` with cells, nets and port lists permuted by `rng` (default: os.urandom) and
    black boxes anonymised (masters bb<k>, pins p<j>, directions kept; numbering drawn from `rng`).
    Returns (netlist, cell_old_of_new, net_new_of_old)."""
    rng = rng or random.SystemRandom()
    cells = list(range(len(nl.master)))
    rng.shuffle(cells)
    nets = list(range(nl.n_nets))
    rng.shuffle(nets)
    ins = [nets[n] for n in nl.inputs]
    outs = [nets[n] for n in nl.outputs]
    rng.shuffle(ins)
    rng.shuffle(outs)
    bb = blackbox_names(nl, rng)
    masters, pins = [], []
    for c in cells:
        m = nl.master[c]
        if m in bb:
            new, pmap = bb[m]
            masters.append(new)
            pins.append(dict(sorted((pmap[p], nets[n]) for p, n in nl.pins[c].items())))
        else:
            masters.append(m)
            pins.append({p: nets[n] for p, n in sorted(nl.pins[c].items())})
    blackbox = dict(sorted((new, dict(sorted((pmap[p], d) for p, d in nl.blackbox[m].items())))
                           for m, (new, pmap) in bb.items()))
    nl2 = Netlist(_public_library(nl.lib), masters, pins,
                  nl.n_nets, ins, outs, {nets[n]: v for n, v in sorted(nl.const.items(), key=lambda x: nets[x[0]])},
                  blackbox, dict(sorted(nl.dropped.items())))
    return nl2, cells, nets


def key_names(key):
    return set(key.cell_name) | {n for n in key.net_name if n} | set(key.ports)


def blackbox_source_names(nl):
    """The names of `nl`'s black boxes a recognizer must not see: macro (LEF) names and LEF pin
    names. A pin name that is also a Liberty pin name (CLK, D, ...) cannot be told apart from the
    library's and is left to the structural check (every black-box pin of a relabelled netlist is
    an opaque id)."""
    lib_pins = {p for m in nl.lib.values() for p in getattr(m, "pins", {})}
    return set(nl.blackbox) | ({p for v in nl.blackbox.values() for p in v} - lib_pins)


def anonymity(nl, key, source=None):
    """What the relabelled Netlist `nl` exposes that it must not (the Liberty is public and
    skipped): Key names; with `source` (the netlist before relabelling), its black-box macro and
    LEF pin names; and, structurally, any black-box master or pin that is not an opaque id
    (bb<k>, p<j>). "leaks" counts all three; examples of Key and black-box names are listed."""
    reach = strings_in(nl, seen={id(nl.lib)})
    leaked = sorted(reach & key_names(key))
    bb_leaked = sorted(reach & blackbox_source_names(source)) if source is not None else []
    bad = [m for m in nl.blackbox if not OPAQUE_BB.fullmatch(m)]
    bad += [f"{m}.{p}" for m, v in nl.blackbox.items() for p in v if not OPAQUE_PIN.fullmatch(p)]
    for c, m in enumerate(nl.master):
        if m not in nl.lib:
            if not OPAQUE_BB.fullmatch(m):
                bad.append(m)
            bad += [f"{m}.{p}" for p in nl.pins[c] if not OPAQUE_PIN.fullmatch(p)]
    bad = sorted(set(bad))
    return {"strings_reachable": len(reach), "leaks": len(leaked) + len(bb_leaked) + len(bad),
            "leaked_examples": leaked[:10],
            "blackbox": {"masters": len(nl.blackbox), "pins": sum(len(v) for v in nl.blackbox.values()),
                         "instances": sum(1 for m in nl.master if m not in nl.lib),
                         "named_leaks": len(bb_leaked), "named_examples": bb_leaked[:10],
                         "not_opaque": len(bad), "not_opaque_examples": bad[:10]},
            "library_masters": len({m for m in nl.master if m in nl.lib})}


# ----------------------------------------------------------------------------------------------
# the recognizer's modules


def _s3_imports(path):
    """tools.s3 submodules imported by the file (absolute and relative imports)."""
    with open(path) as f:
        tree = ast.parse(f.read(), path)
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("tools.s3."):
                    out.add(a.name.split(".")[2])
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 1:
                mod = "tools.s3." + mod if mod else "tools.s3"
            if mod == "tools.s3":
                out.update(a.name for a in node.names)
            elif mod.startswith("tools.s3."):
                out.add(mod.split(".")[2])
    return out


def recognizer_modules(entry=ENTRY):
    """The recognizer's modules: the entry and, transitively, the tools.s3 modules it imports,
    except harness and truth modules (which it may not import; see test/test_s3.py)."""
    first = entry.split(".")[-1]
    todo, seen = ["netlist", first], []   # entry first; netlist: the pickle's classes live there
    while todo:
        m = todo.pop()
        if m in seen or m in HARNESS_MODULES or m.startswith("truth"):
            continue
        p = os.path.join(ROOT, "tools", "s3", m + ".py")
        if not os.path.exists(p):
            continue
        seen.append(m)
        todo.extend(sorted(_s3_imports(p)))
    return ["tools.s3." + m for m in seen]


def stage_sources(work, entry=ENTRY):
    """Copy the recognizer's source files (and the two package __init__ files) into work/pkg, the
    only source tree the child can read. Returns (pkg dir, {relative path: sha256})."""
    pkg = os.path.join(work, "pkg")
    os.makedirs(os.path.join(pkg, "tools", "s3"))
    rels = [os.path.join("tools", "__init__.py"), os.path.join("tools", "s3", "__init__.py")]
    rels += [os.path.join("tools", "s3", m.split(".")[-1] + ".py") for m in recognizer_modules(entry)]
    hashes = {}
    for rel in rels:
        src = os.path.join(ROOT, rel)
        dst = os.path.join(pkg, rel)
        if os.path.exists(src):
            with open(src, "rb") as f:
                data = f.read()
        else:
            data = b""
        with open(dst, "wb") as f:
            f.write(data)
        hashes[rel] = _sha256_bytes(data)
    return pkg, hashes


# ----------------------------------------------------------------------------------------------
# isolation: paths, the OS layer, the child


def _pkg_dir(name):
    import importlib.util
    spec = importlib.util.find_spec(name)
    return os.path.dirname(os.path.realpath(spec.origin))


def _yices_paths():
    """(exec paths, read trees) that yices-sat's wrapper script needs, or ((), ()) without it."""
    if not os.path.exists(YICES_SAT):
        return (), ()
    top = os.path.realpath(os.path.join(os.path.dirname(YICES_SAT), ".."))
    exe = [os.path.realpath(YICES_SAT), os.path.join(top, "libexec", "realpath"),
           os.path.join(top, "libexec", "yices-sat")]
    exe += [p for p in ("/usr/bin/env", "/bin/bash", "/usr/bin/dirname") if os.path.exists(p)]
    return tuple(exe), (top,)


def interpreter():
    """The real interpreter binary (the venv's python is a symlink; the child runs the base
    interpreter with -S and an explicit sys.path, so the venv itself is never read)."""
    return os.path.realpath(sys.executable)


def sandbox_config(pickle_path, pkg, fd=None, nonce="", fail_closed=True, entry=ENTRY):
    install = os.path.realpath(sys.base_prefix)
    site = os.path.dirname(_pkg_dir("numpy"))
    trees = sorted({install, _pkg_dir("numpy"), _pkg_dir("z3"), os.path.realpath(pkg)})
    dirs = sorted({os.path.realpath(site)})
    for d, _subs, _files in os.walk(pkg):
        dirs.append(os.path.realpath(d))
    yexe, _ytrees = _yices_paths()
    return {"pkg": os.path.realpath(pkg), "pickle": os.path.realpath(pickle_path), "module": entry,
            "site_packages": os.path.realpath(site), "read_files": [os.path.realpath(pickle_path)],
            "read_trees": trees, "list_dirs": sorted(set(dirs)),
            "exec": [os.path.realpath(YICES_SAT)] if yexe else [], "fd": fd, "nonce": nonce,
            "fail_closed": bool(fail_closed), "violation_rc": VIOLATION_RC,
            "recognizer_modules": recognizer_modules(entry)}


def _sb_quote(p):
    return p.replace("\\", "\\\\").replace('"', '\\"')


def _ancestors(paths):
    out = set()
    for p in paths:
        p = os.path.realpath(p)
        while True:
            parent = os.path.dirname(p)
            if parent == p:
                break
            out.add(parent)
            p = parent
    return sorted(out)


def macos_profile(cfg, work):
    """The sandbox-exec profile for one child (see the module docstring, step 5)."""
    exe = interpreter()
    app = os.path.join(os.path.realpath(sys.base_prefix), "Resources", "Python.app", "Contents", "MacOS", "Python")
    execs = [exe] + ([app] if os.path.exists(app) else [])
    yexe, ytrees = _yices_paths()
    trees = list(cfg["read_trees"]) + list(ytrees)
    files = list(cfg["read_files"]) + list(yexe)
    lit = lambda ps: " ".join(f'(literal "{_sb_quote(p)}")' for p in ps)  # noqa: E731
    sub = lambda ps: " ".join(f'(subpath "{_sb_quote(p)}")' for p in ps)  # noqa: E731
    anc = _ancestors(trees + files + cfg["list_dirs"] + execs + [os.path.realpath(work)])
    lines = ["(version 1)", "(deny default)",
             f"(allow process-exec {lit(execs + list(yexe))})",
             f"(allow file-read* {sub(trees)} {lit(files + execs)})",
             f"(allow file-read-data {lit(cfg['list_dirs'] + [os.path.realpath(work)])})",
             f"(allow file-read-metadata {lit(anc + [os.path.realpath(work)])})",
             '(allow file-read* (literal "/") (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/stdin") '
             '(subpath "/dev/fd"))',
             '(allow file-read* (subpath "/usr/lib") (subpath "/System/Library") '
             '(subpath "/System/Volumes/Preboot/Cryptexes") (literal "/private/var/db/dyld"))',
             '(allow file-write-data (literal "/dev/null"))',
             "(allow sysctl-read)"]
    if yexe:
        lines.append("(allow process-fork)")   # yices-sat runs as a subprocess (still inside this profile)
    return "\n".join(lines) + "\n"


def bwrap_argv(cfg, work):
    """The Linux alternative to sandbox-exec (bubblewrap; NOT TESTED on this macOS host, used
    only when S3_OS_SANDBOX=bwrap): no network (--unshare-all), a fresh /proc and /dev, read-only
    binds of the interpreter's installation, the numpy/z3 packages, the system libraries and the
    run directory, nothing else of the host filesystem."""
    binds = []
    for p in sorted(set(cfg["read_trees"]) | {os.path.realpath(work)} | set(_yices_paths()[1])):
        binds += ["--ro-bind", p, p]
    for p in ("/usr", "/lib", "/lib64", "/bin", "/etc/ld.so.cache"):
        if os.path.exists(p):
            binds += ["--ro-bind", p, p]
    return ["bwrap", "--die-with-parent", "--unshare-all", "--new-session", "--proc", "/proc", "--dev", "/dev",
            *binds, "--chdir", os.path.realpath(work)]


def os_sandbox_kind():
    """"sandbox-exec" on macOS, "bwrap" on Linux when S3_OS_SANDBOX=bwrap and bwrap exists, else "none"."""
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return "sandbox-exec"
    if sys.platform.startswith("linux") and os.environ.get("S3_OS_SANDBOX") == "bwrap" and shutil.which("bwrap"):
        return "bwrap"
    return "none"


# The child process. Only the standard library is imported before the hook is installed.
CHILD = r'''
import json, os, sys
import ctypes  # before the hook: its import dlopens the running process (numpy imports it); later
               # dlopens are limited to the allowed trees, symbol lookups to z3's Z3_* functions
sys.stdout = sys.stderr   # the recognizer's prints go to stderr; the answer goes over the pipe


def _setup():
    cfg = json.loads(sys.argv[1])
    del sys.argv[1:]
    real = os.path.realpath
    files = frozenset(cfg["read_files"])
    trees = tuple(t.rstrip(os.sep) + os.sep for t in cfg["read_trees"])
    dirs = frozenset(cfg["list_dirs"])
    exe = frozenset(cfg["exec"])
    fail_closed, vrc, nonce = cfg["fail_closed"], cfg["violation_rc"], cfg["nonce"]
    pipe = os.fdopen(cfg["fd"], "w") if cfg["fd"] is not None else None
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
    deny_events = frozenset((
        "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty", "os.startfile", "pty.spawn",
        "os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.symlink", "os.link", "os.truncate", "os.chmod",
        "os.chown", "os.chflags", "os.lchflags", "os.utime", "os.kill", "os.killpg", "os.setxattr", "os.removexattr",
        "os.chdir", "shutil.copyfile", "shutil.copymode", "shutil.copystat", "shutil.copytree", "shutil.move",
        "shutil.rmtree", "shutil.make_archive", "shutil.unpack_archive", "tempfile.mkstemp", "tempfile.mkdtemp",
        "webbrowser.open", "urllib.Request", "http.client.connect", "ftplib.connect", "smtplib.connect",
        "imaplib.open", "poplib.connect", "sqlite3.connect", "sqlite3.connect/handle"))
    blocked = []
    sent = [False]

    def readable(p):
        return p in files or (p + os.sep).startswith(trees) or p.startswith(trees)

    def default(o):
        import numpy as np
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, (np.ndarray, set, frozenset)):
            return list(o.tolist() if isinstance(o, np.ndarray) else o)
        raise TypeError(f"not JSON serializable: {type(o).__name__}")

    def emit(rep):
        if sent[0] or pipe is None:
            return
        sent[0] = True
        rep["nonce"] = nonce
        rep["blocked"] = blocked[:50]
        rep["blocked_count"] = len(blocked)
        try:
            line = json.dumps(rep, default=default)
        except Exception as e:
            line = json.dumps({"nonce": nonce, "ok": False, "error": f"result not JSON serializable: {e}",
                               "blocked": blocked[:50], "blocked_count": len(blocked)})
        pipe.write(line + "\n")
        pipe.flush()

    def deny(event, what):
        blocked.append([event, str(what)[:300]])
        if fail_closed:
            try:
                emit({"ok": False, "violation": [event, str(what)[:300]]})
            finally:
                os._exit(vrc)
        raise PermissionError(f"S3 sandbox: {event} {what!r} is not allowed")

    def path(x):
        return real(os.fsdecode(os.fspath(x)))

    def hook(event, args):
        if event == "open":
            p, mode, flags = args
            if p is None or isinstance(p, int):
                return
            p = path(p)
            if os.path.basename(p).startswith("<"):   # linecache probing "<string>" for a traceback
                raise PermissionError(p)
            write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool((flags or 0) & write_flags)
            if write or not readable(p):
                deny(event, p)
        elif event in ("os.listdir", "os.scandir"):
            a = args[0] if args else None
            p = real(".") if a is None or isinstance(a, int) else path(a)
            if p not in dirs and not (p + os.sep).startswith(trees):
                deny(event, p)
        elif event == "subprocess.Popen":
            x, argv = args[0], args[1]
            if x is None and argv:
                x = argv if isinstance(argv, (str, bytes)) else argv[0]
            if x is None or path(x) not in exe:
                deny(event, x)
        elif event == "ctypes.dlopen":
            if not args[0] or not readable(path(args[0])):
                deny(event, args[0])
        elif event in ("ctypes.dlsym", "ctypes.dlsym/handle"):
            name = args[1] if len(args) > 1 else None
            if not (isinstance(name, str) and name.startswith("Z3_")):
                deny(event, name)
        elif event in deny_events or event.startswith("socket."):
            deny(event, args[:1])

    sys.addaudithook(hook)
    sys.dont_write_bytecode = True
    sys.path[:] = [cfg["pkg"]] + [p for p in sys.path if p and (real(p) + os.sep).startswith(trees)] \
        + [cfg["site_packages"]]
    return cfg["pickle"], cfg["module"], emit


def _main(pkl, module, emit):
    import importlib, pickle, resource, time, traceback
    t0 = time.perf_counter()
    try:
        with open(pkl, "rb") as f:
            data = f.read()
        import tools.s3.netlist  # noqa: F401  (the pickle's classes)
        nl = pickle.loads(data)
        del data
        mod = importlib.import_module(module)
        t1 = time.perf_counter()
        res = mod.recognize(nl)
        t2 = time.perf_counter()
        rep = {"ok": True, "result": res, "load_s": round(t1 - t0, 3), "recognize_s": round(t2 - t1, 3)}
    except BaseException:
        rep = {"ok": False, "error": traceback.format_exc()[-6000:]}
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rep["peak_rss_mb"] = round(r / 1e6 if sys.platform == "darwin" else r / 1e3, 1)
    emit(rep)


_main(*_setup())
'''


def child_env(home):
    """A minimal environment: nothing of the caller's except thread-count settings."""
    env = {"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C",
           "HOME": home, "TMPDIR": home}
    env.update({k: v for k, v in os.environ.items() if k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS")})
    return env


def run_child(pickle_path, entry=ENTRY, timeout=DEFAULT_TIMEOUT, extra="", fail_closed=True, os_sandbox=None,
              staged=None):
    """Run the recognizer (or, for tests, CHILD with `extra` source run before the recognizer) on
    the pickle, isolated (module docstring, step 5). `staged`: (pkg dir, {path: sha256}) from
    stage_sources, shared by every child of one run; default: staged now, next to the pickle.
    Returns a report: ok, result, returncode, violation, os_sandbox, the staged sources' hashes,
    stderr tail, timings."""
    work = os.path.dirname(os.path.realpath(pickle_path))
    if staged is None:
        staged = stage_sources(tempfile.mkdtemp(prefix="src-", dir=work), entry)
    pkg, sources = staged
    r, w = os.pipe()
    nonce = secrets.token_hex(16)
    cfg = sandbox_config(pickle_path, pkg, fd=w, nonce=nonce, fail_closed=fail_closed, entry=entry)
    anchor = "\n_main(*_setup())"
    src = CHILD if not extra else CHILD.replace(anchor, "\n_a = _setup()\n" + extra + "\n_main(*_a)", 1)
    kind = os_sandbox or os_sandbox_kind()
    argv = [interpreter(), "-S", "-s", "-B", "-P", "-c", src, json.dumps(cfg)]
    if kind == "sandbox-exec":
        argv = ["sandbox-exec", "-p", macos_profile(cfg, work)] + argv
    elif kind == "bwrap":
        argv = bwrap_argv(cfg, work) + argv
    chunks = []

    def reader():
        with os.fdopen(r, "rb") as f:
            while True:
                b = f.read(1 << 20)
                if not b:
                    break
                chunks.append(b)

    t0 = time.perf_counter()
    rc, out, err = None, "", ""
    try:
        p = subprocess.Popen(argv, cwd=work, env=child_env(work), pass_fds=(w,), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    except BaseException:
        os.close(r)
        raise
    finally:
        os.close(w)   # the child holds the write end now; EOF on r when it exits
    th = threading.Thread(target=reader, daemon=True)
    th.start()
    try:
        out, err = p.communicate(timeout=timeout)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        err = (err or "") + f"\nTIMEOUT after {timeout} s"
    th.join(timeout=60)
    wall = time.perf_counter() - t0
    lines = [x for x in b"".join(chunks).decode(errors="replace").splitlines() if x.strip()]
    rep, foreign = None, 0
    for line in lines:
        try:
            msg = json.loads(line)
        except ValueError:
            foreign += 1
            continue
        if isinstance(msg, dict) and msg.get("nonce") == nonce and rep is None:
            rep = msg
        else:
            foreign += 1
    if rep is None:
        rep = {"ok": False, "error": f"no result message on the result pipe (returncode {rc})"}
    rep.pop("nonce", None)
    if foreign:
        rep["ok"] = False
        rep["error"] = (rep.get("error") or "") + f"; {foreign} foreign messages on the result pipe"
    if rc == VIOLATION_RC or rep.get("violation"):
        rep["ok"] = False
        rep.setdefault("error", "sandbox violation")
    elif rc != 0:
        rep["ok"] = False
        rep.setdefault("error", f"returncode {rc}")
    rep.update(returncode=rc, wall_s=round(wall, 3), stderr_tail=(err or "")[-4000:], stdout_tail=(out or "")[-1000:],
               os_sandbox=kind, fail_closed=fail_closed, recognizer_modules=cfg["recognizer_modules"],
               recognizer_sources=sources)
    return rep


# ----------------------------------------------------------------------------------------------
# the result: types, ids back to join keys


def _is_id(x):
    return (isinstance(x, int) and not isinstance(x, bool)) or isinstance(x, str)


def validate_result_types(res):
    """Type problems that would make schema.check_result or the mapping crash (empty = well
    typed): a dict; structures a list of dicts with a str kind, a list of ids as flops, order
    null or a list of lists of ids, params and proof dicts (or null), proof.claims a list; groups
    a list of lists of ids. Ids are ints or strings."""
    bad = []
    if not isinstance(res, dict):
        return [f"result is a {type(res).__name__}, not an object"]
    ss = res.get("structures", [])
    if not isinstance(ss, list):
        bad.append("structures is not a list")
        ss = []
    for i, s in enumerate(ss):
        w = f"structures[{i}]"
        if not isinstance(s, dict):
            bad.append(f"{w} is not an object")
            continue
        if not isinstance(s.get("kind"), str):
            bad.append(f"{w}.kind is not a string")
        if not isinstance(s.get("flops"), list) or not all(_is_id(x) for x in s["flops"]):
            bad.append(f"{w}.flops is not a list of ids")
        o = s.get("order")
        if o is not None and (not isinstance(o, list) or not all(isinstance(l, list) and all(_is_id(x) for x in l)
                                                                  for l in o)):
            bad.append(f"{w}.order is not null or a list of lists of ids")
        for k in ("params", "proof", "control"):
            if s.get(k) is not None and not isinstance(s[k], dict):
                bad.append(f"{w}.{k} is not an object")
        pr = s.get("proof")
        if isinstance(pr, dict) and pr.get("claims") is not None and not isinstance(pr["claims"], list):
            bad.append(f"{w}.proof.claims is not a list")
        if s.get("id") is not None and not isinstance(s["id"], (str, int)):
            bad.append(f"{w}.id is not a string or int")
    gs = res.get("groups", [])
    if not isinstance(gs, list) or not all(isinstance(g, list) and all(_is_id(x) for x in g) for g in gs):
        bad.append("groups is not a list of lists of ids")
    if res.get("meta") is not None and not isinstance(res["meta"], dict):
        bad.append("meta is not an object")
    return bad


def flop_cells(nl):
    return {c for c, m in enumerate(nl.master) if m in nl.lib and nl.lib[m].kind == "ff"}


def id_mapper(nl, key, cell_old_of_new):
    flops = flop_cells(nl)
    stats = {"mapped": 0, "not_an_id": 0, "not_a_flop": 0, "examples": []}

    def conv(x):
        i = None
        if isinstance(x, int) and not isinstance(x, bool):
            i = x
        elif isinstance(x, str) and x.strip().isdigit():
            i = int(x)
        if i is None or i not in flops:
            stats["not_an_id" if i is None else "not_a_flop"] += 1
            if len(stats["examples"]) < 10:
                stats["examples"].append(repr(x)[:40])
            return f"?{x}"
        stats["mapped"] += 1
        return key.cell_name[cell_old_of_new[i]]
    return conv, stats


# params that hold flop ids (lists, nested lists, or {"flop": id} entries); null / "input" stay as they are
FLOP_PARAMS = ("order", "bit_order", "serial_in")


def _map_ids(v, conv):
    if isinstance(v, list):
        return [_map_ids(x, conv) for x in v]
    if isinstance(v, dict):
        return {k: (_map_ids(x, conv) if k == "flop" else x) for k, x in v.items()}
    if v is None or (isinstance(v, str) and not v.strip().isdigit()):
        return v
    return conv(v)


def map_result(result, conv):
    """The result with flop ids mapped to join keys (flops, order, the FLOP_PARAMS, and the keys of
    control.reset_value, schema v2); proof claims (over opaque ids, meaningless outside the run)
    are replaced by their count (the verification report keeps the verdicts). Net ids in control
    (conditions, input, inputs) stay opaque."""
    out = json.loads(json.dumps(result))
    for s in out.get("structures") or []:
        s["flops"] = [conv(x) for x in s.get("flops") or []]
        if s.get("order"):
            s["order"] = [[conv(x) for x in lane] for lane in s["order"]]
        for k in FLOP_PARAMS:
            if (s.get("params") or {}).get(k) is not None:
                s["params"][k] = _map_ids(s["params"][k], conv)
        ctl = s.get("control")
        if isinstance(ctl, dict) and isinstance(ctl.get("reset_value"), dict):
            ctl["reset_value"] = {conv(f): v for f, v in ctl["reset_value"].items()}   # v2.0 form
        if isinstance(ctl, dict) and isinstance(ctl.get("reset"), list):   # v2.1: a list of cases
            for case in ctl["reset"]:
                if isinstance(case, dict) and isinstance(case.get("value"), dict):
                    case["value"] = {conv(f): v for f, v in case["value"].items()}
        if isinstance(s.get("proof"), dict) and "claims" in s["proof"]:
            s["proof"]["claims"] = len(s["proof"]["claims"]) if isinstance(s["proof"]["claims"], list) else None
    out["groups"] = [[conv(x) for x in g] for g in out.get("groups") or []]
    return out


# ----------------------------------------------------------------------------------------------
# the structural baseline

CONTROL_FRACTION = 0.05
BASELINE_DEFINITION = (
    "copy graph: edge j->i when flop j is the only flop, other than i itself and the 'control flops' "
    f"(flops in the next-state support of more than {CONTROL_FRACTION:.0%} of all flops), in the support "
    "of i's next-state function; components of >= 2 flops are groups; a simple path of >= 3 flops is a "
    "shift_register ordered head to tail, a 2-flop path whose head has no such flop in its support is a "
    "synchronizer, other components are data_register (unscored)")


def copy_graph_baseline(nl):
    """The structural baseline (BASELINE_DEFINITION), from the anonymous netlist; flop ids are
    cell indices, as a recognizer's would be."""
    g = GateGraph(nl)
    nf = len(g.flops)
    mask = (1 << nf) - 1
    fsup = [b & mask for b in g.supports()]   # g.sources lists the flops first, in flop order
    fan = [0] * nf
    for b in fsup:
        while b:
            low = b & -b
            fan[low.bit_length() - 1] += 1
            b ^= low
    cmask = 0
    for j in range(nf):
        if fan[j] > CONTROL_FRACTION * nf:
            cmask |= 1 << j
    parent = list(range(nf))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    succ, pred = {}, {}
    for i, b in enumerate(fsup):
        o = b & ~cmask & ~(1 << i)
        if o and not o & (o - 1):
            j = o.bit_length() - 1
            succ.setdefault(j, []).append(i)
            pred.setdefault(i, []).append(j)
            parent[find(i)] = find(j)
    comps = {}
    for i in range(nf):
        comps.setdefault(find(i), []).append(i)
    structures, groups = [], []
    for members in sorted((sorted(v) for v in comps.values() if len(v) >= 2), key=lambda v: v[0]):
        ids = [g.flops[i].cell for i in members]
        groups.append(ids)
        path = all(len(succ.get(i, ())) <= 1 and len(pred.get(i, ())) <= 1 for i in members)
        heads = [i for i in members if not pred.get(i)]
        order = None
        if path and len(heads) == 1:
            order, x = [], heads[0]
            while x is not None:
                order.append(x)
                x = succ.get(x, [None])[0]
            path = len(order) == len(members)
        else:
            path = False
        if path and len(order) >= 3:
            kind = "shift_register"
        elif path and len(order) == 2 and not (fsup[order[0]] & ~cmask & ~(1 << order[0])):
            kind = "synchronizer"
        else:
            kind, path = "data_register", False
        structures.append({"id": f"b{len(structures)}", "kind": kind, "flops": ids,
                           "order": [[g.flops[i].cell for i in order]] if path else None, "params": {},
                           "control": {}, "proof": {"status": "not_attempted"}})
    return {"schema": schema.RESULT_SCHEMA, "structures": structures, "groups": groups,
            "meta": {"baseline": "copy_graph", "definition": BASELINE_DEFINITION,
                     "control_flops": bin(cmask).count("1")}}


# ----------------------------------------------------------------------------------------------
# evaluation of one netlist


def _prepare(nl, key, rng=None, label=None):
    """Relabel (rng: default os.urandom; FileOrder() for the leakage test's file-order arm), check
    anonymity, pickle the relabelled netlist into a fresh directory. Returns the state _finish needs."""
    t0 = time.perf_counter()
    file_order = isinstance(rng, FileOrder)
    nl2, cells, nets = relabel(nl, rng)
    perm_hash = hashlib.sha256(json.dumps([cells, nets]).encode()).hexdigest()
    anon = anonymity(nl2, key, nl)
    if anon["leaks"]:
        raise SystemExit(f"anonymity check failed: {anon['leaked_examples']} {anon['blackbox']}")
    work = tempfile.mkdtemp(prefix="s3-")
    pkl = os.path.join(work, "netlist.pkl")
    data = pickle.dumps(nl2, protocol=pickle.HIGHEST_PROTOCOL)
    with open(pkl, "wb") as f:
        f.write(data)
    pkl_sha = _sha256_bytes(data)
    del data
    source = ("file order: the loader's ids (seed=None), no permutation" if file_order
              else "random.SystemRandom (os.urandom)" if rng is None or isinstance(rng, random.SystemRandom)
              else f"caller's rng ({type(rng).__name__})")
    return {"label": label, "file_order": file_order, "nl2": nl2, "cells": cells, "work": work, "pkl": pkl,
            "netlist": {"summary": nl2.summary(), "pickle_sha256": pkl_sha, "permutation_sha256": perm_hash,
                        "permutation_source": source, "anonymity": anon},
            "t": {"relabel_pickle_s": round(time.perf_counter() - t0, 3)}}


def _run_prepared(prep, entry=ENTRY, timeout=DEFAULT_TIMEOUT, fail_closed=True, os_sandbox=None, staged=None):
    try:
        return run_child(prep["pkl"], entry, timeout, fail_closed=fail_closed, os_sandbox=os_sandbox,
                         **({"staged": staged} if staged is not None else {}))
    finally:
        shutil.rmtree(prep["work"], ignore_errors=True)


def outcome(vs):
    """The harness's outcome class of one structure verdict (verify.py): "verified", "unknown" (a
    solver limit), "refuted", "vacuous", "malformed", "budget", "missing defining claims", "no
    claims", ... A verdict that names its own class (verify v2: "bucket") keeps it."""
    if not isinstance(vs, dict):
        return "not checked"
    if vs.get("verified"):
        return "verified"
    st = vs.get("bucket") or vs.get("status") or vs.get("outcome")
    if isinstance(st, str) and st and st != "verified":
        return st
    why = str(vs.get("reason") or "")
    if why.startswith("claim ") and ": " in why:
        why = why.split(": ", 1)[1]
    for tag in ("unknown", "refuted", "vacuous", "malformed", "budget"):
        if why.startswith(tag):
            return tag
    if "no verified defining claim" in why:
        return "missing defining claims"
    return why.split(":")[0][:40] or "not verified"


RECOGNIZE_RUN_PREFIX = "RECOGNIZE_RUN "


def recognize_run_info(stderr_tail):
    """The recognizer's last RECOGNIZE_RUN line, parsed (None when it printed none or it is not
    JSON). Self-reported, like every other field from the child: informational only."""
    best = None
    for line in (stderr_tail or "").splitlines():
        if line.startswith(RECOGNIZE_RUN_PREFIX):
            try:
                v = json.loads(line[len(RECOGNIZE_RUN_PREFIX):])
            except ValueError:
                continue
            if isinstance(v, dict):
                best = v
    return best


def canonical_order_notes(info, label=None):
    """What the canonical order left to id order WITHOUT hitting a budget: netlist.canonical_order
    individualizes every tied class of source-creating cells and port nets, then orders by colour
    and, inside a colour, by id (`np.lexsort((np.arange(C), col_c))`). Its stats['tied_cells'] and
    stats['tied_nets'] count the elements still sharing a colour at that point -- normally
    combinational cells and internal nets, which order nothing the recognizer reads.

    canonical_order_problems() only ever fired on stats['ties_left_to_id_order'], which
    canonical_order sets ONLY when the round budget was hit, so the case that actually occurs (79
    tied cells and 79 tied nets on every TEMPO arm) was never reported anywhere (review[1] issue 5
    of 2026-09-22). These lines are NOTES, not problems: the empirical evidence is that they change
    nothing (TEMPO: one answer over 5 permutations and the file-order arm; 336 corpus runs under
    two id-permutation seeds: 0 differences), and the leakage test remains the check that would
    catch it if they ever did."""
    co = (info or {}).get("canonical_order") or {}
    pre = f"[{label}] " if label else ""
    tc, tn = co.get("tied_cells"), co.get("tied_nets")
    if not tc and not tn:
        return []
    left = co.get("ties_left_to_id_order") or 0
    important = (f"{left} tied class(es) of them were left to id order as well, reported as a problem above"
                 if left else "every tied class of flops, latches, clock gates, black boxes and port nets was "
                              "individualized (0 of those left to id order), so these are combinational cells "
                              "and internal nets")
    return [pre + f"note: canonical order: {tc or 0} cell(s) and {tn or 0} net(s) still share a colour after "
                  f"refinement and are ordered by id; {important}. Not blocking: the leakage test and the "
                  "permutation spread are what would show it if the answer depended on them"]


def canonical_order_problems(info, label=None):
    """Problems of the recognizer's canonical order (netlist.canonical_order stats, forwarded
    through recognize.py's RECOGNIZE_RUN line): a tie left to id order, or the refinement's round
    budget hit, means the answer can depend on the ids the harness handed out, which is exactly
    what the leakage test checks on TEMPO and nothing checks elsewhere (review[2] issue 4).

    Ties among unimportant elements are NOT problems; canonical_order_notes() reports those."""
    co = (info or {}).get("canonical_order")
    pre = f"[{label}] " if label else ""
    if info is None:
        return [pre + "the recognizer printed no RECOGNIZE_RUN line: no canonical-order statistics "
                      "for this evaluation"]
    if co is None:
        return [pre + "the recognizer built no canonical order (run_info()['canonical_order'] is null): "
                      "nothing pins its answer to the netlist rather than to the ids"]
    out = []
    if co.get("round_budget_hit"):
        out.append(pre + f"canonical order: the refinement's round budget was hit after {co.get('rounds')} "
                         "rounds (params.CANON_ROUND_BUDGET); the remaining ties fall back to id order")
    if co.get("ties_left_to_id_order"):
        out.append(pre + f"canonical order: {co['ties_left_to_id_order']} tied classes left to id order; "
                         "the answer may depend on the ids the harness handed out")
    return out


def _finish(prep, child, key, truth, baseline=True):
    """Verify, map and (when `truth` is given) score one recognizer answer; never raises (errors
    are recorded and invalidate the evaluation)."""
    t, problems, invalid = dict(prep["t"]), [], []
    nl2, cells = prep["nl2"], prep["cells"]
    t["recognizer_wall_s"] = child.get("wall_s")
    out = {"netlist": prep["netlist"], "recognizer": {k: v for k, v in child.items() if k != "result"},
           "timings_s": t}
    if prep["label"] is not None:
        out["label"] = prep["label"]
    # the recognizer's own run info (stages, control timings, canonical_order, bdd), lifted out of
    # the stderr tail so the record carries it as data instead of as a line of text
    out["recognize_run"] = recognize_run_info(child.get("stderr_tail"))
    if child.get("ok"):
        problems += canonical_order_problems(out["recognize_run"])
        problems += canonical_order_notes(out["recognize_run"])
    raw = child.pop("result", None) if child.get("ok") else None
    if not child.get("ok"):
        invalid.append("the recognizer failed" + (" (sandbox violation)" if child.get("violation") else ""))
        problems.append("recognizer failed: " + str(child.get("error") or child.get("violation") or "")[-800:])
    try:
        types = validate_result_types(raw) if raw is not None else []
        if types:
            invalid.append("the result is malformed")
            problems += [f"result type: {b}" for b in types[:20]]
        if raw is None or types:
            result = {"schema": schema.RESULT_SCHEMA, "structures": [], "groups": [], "meta": {"failed": True}}
        else:
            result = raw
        out["result_sha256"] = hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()
        bad = score._safe_check_result(result)
        problems += [f"result: {b}" for b in bad]
        if bad:
            invalid.append("the result breaks the schema")
        leaked = sorted(strings_in(result) & key_names(key))
        if leaked:
            problems.append(f"result holds Key names (leak?): {leaked[:10]}")
            invalid.append("anonymity")
        # proofs, on this process's own copy of the relabelled netlist
        t1 = time.perf_counter()
        ver = verify.verify_result(nl2, result)
        t["verify_s"] = round(time.perf_counter() - t1, 3)
        out["verify"] = ver
        flags = [bool(s.get("verified")) for s in ver["structures"]]
        outcomes = [outcome(s) for s in ver["structures"]]
        conv, idstats = id_mapper(nl2, key, cells)
        mapped = map_result(result, conv)
        out["ids"] = idstats
        if idstats["not_an_id"] or idstats["not_a_flop"]:
            problems.append(f"result ids that are not flop cells: {idstats}")
            invalid.append("the result names ids that are not flop cells")
        out["result"] = mapped
        out["verified_flags"] = flags
        out["outcomes"] = outcomes
        out["canonical_result_sha256"] = canonical_result_hash(mapped, outcomes)
        flop_keys = {key.cell_name[cells[c]] for c in flop_cells(nl2)}
        bls = {}
        if baseline:
            t1 = time.perf_counter()
            b = copy_graph_baseline(nl2)
            bconv, _bst = id_mapper(nl2, key, cells)
            bls["structural"] = {"definition": BASELINE_DEFINITION, "result": map_result(b, bconv)}
            t["baseline_s"] = round(time.perf_counter() - t1, 3)
        out["baselines"] = bls
        out["flop_keys"] = flop_keys
        if truth is not None:
            sc = score_mapped(truth, mapped, flags, bls, flop_keys, outcomes, ver["structures"])
            problems += sc.pop("problems_join")
            invalid += sc.pop("invalid_join")
            out.update(sc)
    except Exception:
        invalid.append("harness error after the recognizer ran")
        problems.append("harness error: " + traceback.format_exc()[-3000:])
    out["problems"] = problems
    out["invalid_reasons"] = invalid
    return out


def evaluate(nl, key, truth, *, entry=ENTRY, timeout=DEFAULT_TIMEOUT, baseline=True, os_sandbox=None,
             fail_closed=True, rng=None, label=None, staged=None):
    """Relabel (rng: default os.urandom), isolate, run the recognizer, verify, map and (when `truth`
    is given) score one netlist. Returns a dict of record fields; never raises after the recognizer
    ran (errors are recorded and invalidate the run)."""
    prep = _prepare(nl, key, rng, label)
    child = _run_prepared(prep, entry, timeout, fail_closed, os_sandbox, staged)
    return _finish(prep, child, key, truth, baseline)


def evaluate_permutations(nl, key, truth, k, *, file_order=False, jobs=1, rng_factory=None, entry=ENTRY,
                          timeout=DEFAULT_TIMEOUT, baseline=True, os_sandbox=None, fail_closed=True, staged=None):
    """evaluate() under k independent permutations (rng_factory() each; default os.urandom) and,
    with file_order, the file-order arm first. The children run up to `jobs` at a time and share
    ONE staged copy of the recognizer's sources. Returns (evaluations, spread over the k
    permutations, leakage report or None)."""
    factory = rng_factory or random.SystemRandom
    labels = (["file"] if file_order else []) + [f"p{i}" for i in range(1, k + 1)]
    own_stage = None
    if staged is None:
        own_stage = tempfile.mkdtemp(prefix="s3-src-")
        staged = stage_sources(own_stage, entry)
    try:
        preps = [_prepare(nl, key, FileOrder() if lab == "file" else factory(), lab) for lab in labels]
        run1 = lambda p: _run_prepared(p, entry, timeout, fail_closed, os_sandbox, staged)  # noqa: E731
        if jobs > 1 and len(preps) > 1:
            with ThreadPoolExecutor(max_workers=jobs) as ex:
                children = list(ex.map(run1, preps))
        else:
            children = [run1(p) for p in preps]
        evs = []
        for p, c in zip(preps, children):
            evs.append(_finish(p, c, key, truth, baseline))
            p.pop("nl2", None)
    finally:
        if own_stage:
            shutil.rmtree(own_stage, ignore_errors=True)
    perms = [e for e in evs if e.get("label") != "file"]
    files = [e for e in evs if e.get("label") == "file"]
    return evs, spread(perms), (leakage(files[0], perms) if files else None)


# ----------------------------------------------------------------------------------------------
# permutation spread and the leakage test (S3_DESIGN section 2)

HEADLINE_KIND_METRICS = ("found_p", "found_r", "found_f1", "exact_p", "exact_r", "exact_f1", "found75_r", "bit_f1",
                         "verified_found_r", "structures", "verified_structures", "unknown",
                         # found beside verified, per kind (score.py's honesty block)
                         "unverified_structures", "found_not_verified_registers")
HEADLINE_METRICS = ("macro_f1_registers", "macro_f1_registers_exact", "micro_f1_registers", "micro_f1_registers_exact",
                    "macro_f1_bits", "micro_f1_bits", "macro_f1_registers_verified", "params_accuracy",
                    "params_informative_accuracy", "ami", "ari", "nmi", "structures", "claimed_proven", "verified",
                    "unknown",
                    # what the verified count is worth, and the certified / transcribed params split
                    "params_certified_compared", "params_certified_accuracy", "params_transcribed_compared",
                    "params_transcribed_accuracy", "verified_vacuous_hold", "verified_with_unchecked_params",
                    "verified_with_dead_bits", "verified_without_liveness", "verified_load_hidden_share_mean",
                    "verified_load_hidden_share_max", "verified_load_hidden_share_mean_all",
                    "verified_lfsr_poly_certified")


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def headline_metrics(ev):
    """{metric: float or None} of one evaluation: its score headline (per kind and overall), the
    order summary (score and coverage per truth kind, width band and part) and the harness's
    verified / structure counts."""
    h = (ev.get("score") or {}).get("headline") or {}
    out = {}
    for kind in schema.STRUCTURE_KINDS:
        for m in HEADLINE_KIND_METRICS:
            out[f"{kind}.{m}"] = _num((h.get(kind) or {}).get(m))
    for m in HEADLINE_METRICS:
        out[m] = _num(h.get(m))
    for kind, bands in (h.get("order") or {}).items():
        for band, e in bands.items():
            for part in ("within", "across"):
                if isinstance(e.get(part), dict):
                    for m in ("score", "coverage"):
                        out[f"order.{kind}.{band}.{part}.{m}"] = _num(e[part].get(m))
    vs = (ev.get("verify") or {}).get("summary") or {}
    out["harness.structures"] = _num(vs.get("structures"))
    out["harness.verified"] = _num(vs.get("verified"))
    # the verifier's own qualifications of that count, so a permutation that moves them is visible
    for m in ("verified_vacuous_hold", "verified_with_unchecked_params", "verified_lfsr_poly_certified",
              "verified_self_conditioned", "multi_case_structures", "hold_emptied_by_load",
              "verified_load_hidden_share_max"):
        out[f"harness.{m}"] = _num(vs.get(m))
    return out


def _outcome_class(o):
    """The design's leakage comparison counts "unknown" as its own outcome; other failures are one."""
    return o if o in ("verified", "unknown") else "not verified"


def structure_set(ev):
    """{(kind, join keys, outcome class)} of an evaluation's scored-kind structures: comparable
    across permutations, as the harness mapped the ids to join keys."""
    res = ev.get("result") or {}
    outs = ev.get("outcomes") or []
    out = set()
    for i, s in enumerate(res.get("structures") or []):
        if isinstance(s, dict) and s.get("kind") in schema.STRUCTURE_KINDS:
            out.add((s["kind"], tuple(sorted(str(f) for f in s.get("flops") or [])),
                     _outcome_class(outs[i] if i < len(outs) else None)))
    return out


def canonical_result_hash(mapped, outcomes):
    """sha256 of a mapped result without its recognizer-chosen ids and in a canonical order: every
    structure as (kind, flops, order, params, outcome class), the groups as sorted sets. Equal
    under two permutations exactly when the recognizer's answer is the same up to ids."""
    rows = []
    for i, s in enumerate(mapped.get("structures") or []):
        if not isinstance(s, dict):
            continue
        rows.append(json.dumps([s.get("kind"), sorted(map(str, s.get("flops") or [])), s.get("order"),
                                s.get("params"), _outcome_class(outcomes[i] if i < len(outcomes) else None)],
                               sort_keys=True, default=str))
    groups = sorted(json.dumps(sorted(map(str, g))) for g in mapped.get("groups") or [] if isinstance(g, list))
    return hashlib.sha256(json.dumps([sorted(rows), groups]).encode()).hexdigest()


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 1.0


def spread(evs):
    """Per metric over the evaluations: values, n, mean, median, min, max; plus the structure sets'
    pairwise Jaccard, the structures common to all and found by some only, and how many distinct
    answers (up to ids) the evaluations gave."""
    if not evs:
        return None
    mets = [headline_metrics(e) for e in evs]
    out = {}
    for m in sorted(set().union(*mets)):
        vals = [x.get(m) for x in mets]
        xs = [v for v in vals if v is not None]
        out[m] = {"values": vals, "n": len(xs)}
        if xs:
            out[m].update(mean=statistics.fmean(xs), median=statistics.median(xs), min=min(xs), max=max(xs))
    sets = [structure_set(e) for e in evs]
    pair = [_jaccard(sets[i], sets[j]) for i in range(len(sets)) for j in range(i + 1, len(sets))]
    common = set.intersection(*sets) if sets else set()
    union = set.union(*sets) if sets else set()
    return {"k": len(evs), "labels": [e.get("label") for e in evs], "metrics": out,
            "structures": {"per_evaluation": [len(s) for s in sets], "common": len(common), "union": len(union),
                           "pairwise_jaccard": ({"min": min(pair), "mean": statistics.fmean(pair), "max": max(pair)}
                                                if pair else None),
                           "unstable": sorted((k, len(f), o) for k, f, o in union - common)[:30]},
            "distinct_answers": len({e.get("canonical_result_sha256") for e in evs}),
            "valid": sum(1 for e in evs if not e.get("invalid_reasons"))}


LEAKAGE_RULE = ("S3_DESIGN section 2: every metric of the file-order arm (the loader's ids) must lie within [min, "
                "max] of K >= 5 os.urandom permutations, and so must its structure set's mean Jaccard to the "
                "permutations' sets (against each permutation's mean Jaccard to the others); unknown is its own "
                "outcome")
LEAKAGE_NOTE = ("a metric that varies between permutations puts an exchangeable file-order value outside the range "
                "of K others with probability up to 2/(K+1) (1/3 at K = 5): 'loo_outside' applies the same rule to "
                "each permutation against the other K-1 (the rule's false-alarm rate on this data), 'p_two_sided' is "
                "the rank p-value (its minimum is 2/(K+1)); 'strong' lists metrics outside the spread on which the "
                "permutations all agree (loo_outside 0)")


def leakage(file_ev, perm_evs):
    """The leakage test (LEAKAGE_RULE; see LEAKAGE_NOTE for how to read it)."""
    k = len(perm_evs)
    fm = headline_metrics(file_ev)
    pm = [headline_metrics(e) for e in perm_evs]
    rows, outside, strong = {}, [], []
    for m in sorted(set(fm) | set().union(*pm) if pm else set(fm)):
        v = fm.get(m)
        xs = [x.get(m) for x in pm if x.get(m) is not None]
        if v is None or len(xs) < 2:
            rows[m] = {"file": v, "status": "n/a"}
            continue
        lo, hi = min(xs), max(xs)
        inside = lo - EPS <= v <= hi + EPS
        ge = sum(1 for x in xs if x >= v - EPS)
        le = sum(1 for x in xs if x <= v + EPS)
        loo = sum(1 for j, x in enumerate(xs)
                  if not (min(xs[:j] + xs[j + 1:]) - EPS <= x <= max(xs[:j] + xs[j + 1:]) + EPS)) / len(xs)
        rows[m] = {"file": v, "min": lo, "max": hi, "mean": statistics.fmean(xs), "inside": inside,
                   "p_two_sided": min(1.0, 2 * min(1 + ge, 1 + le) / (len(xs) + 1)), "loo_outside": loo}
        if not inside:
            outside.append(m)
            if loo == 0:
                strong.append(m)
    fs = structure_set(file_ev)
    ps = [structure_set(e) for e in perm_evs]
    f_to_p = statistics.fmean(_jaccard(fs, s) for s in ps) if ps else None
    p_to_p = [statistics.fmean(_jaccard(ps[i], ps[j]) for j in range(k) if j != i) for i in range(k)] if k > 1 else []
    union = set.union(*ps) if ps else set()
    novel = sorted((kk, len(f), o) for kk, f, o in fs - union)
    loo_novel = [len(ps[i] - set.union(*(ps[j] for j in range(k) if j != i))) for i in range(k)] if k > 1 else []
    set_inside = bool(p_to_p) and min(p_to_p) - EPS <= f_to_p <= max(p_to_p) + EPS
    return {"rule": LEAKAGE_RULE, "note": LEAKAGE_NOTE, "k": k, "metrics": rows,
            "outside": outside, "strong": strong,
            "structures": {"file_mean_jaccard_to_permutations": f_to_p, "permutation_mean_jaccard_to_others": p_to_p,
                           "inside": set_inside, "file_only": len(novel), "file_only_examples": novel[:20],
                           "permutation_only_counts": loo_novel},
            "file_canonical_result_sha256": file_ev.get("canonical_result_sha256"),
            "file_equals_a_permutation": file_ev.get("canonical_result_sha256") in
            {e.get("canonical_result_sha256") for e in perm_evs},
            "verdict": "pass" if not outside and set_inside else "fail"}


def render_spread(sp, leak=None, top=None):
    """Text: the headline metrics over the permutations (mean, min, max), with the file-order value
    and the leakage verdict per metric when a leakage report is given."""
    if not sp:
        return ""
    keys = top or ["macro_f1_registers", "macro_f1_registers_exact", "micro_f1_registers", "macro_f1_bits",
                   "macro_f1_registers_verified", "ami", "ari", "params_accuracy",
                   "params_certified_accuracy", "params_certified_compared", "params_transcribed_accuracy",
                   "params_transcribed_compared", "verified", "unknown", "verified_vacuous_hold",
                   "verified_with_unchecked_params", "verified_with_dead_bits",
                   "verified_load_hidden_share_mean", "verified_load_hidden_share_max"] + [
        f"{k}.{m}" for k in schema.STRUCTURE_KINDS
        for m in ("found_p", "found_r", "exact_r", "verified_found_r", "unverified_structures")] + sorted(
        m for m in sp["metrics"] if m.startswith("order.") and m.endswith(".score"))
    L = [f"Permutations: K = {sp['k']} ({sp['valid']} valid), {sp['distinct_answers']} distinct answers up to ids; "
         f"scored-kind structure sets: common {sp['structures']['common']} of union {sp['structures']['union']}, "
         f"pairwise Jaccard {sp['structures']['pairwise_jaccard']}"]
    L.append(f"  {'metric':<52}{'mean':>8}{'min':>8}{'max':>8}" + (f"{'file':>8}  leakage" if leak else ""))
    for m in keys:
        e = sp["metrics"].get(m)
        if not e or not e.get("n"):
            continue
        line = f"  {m:<52}{e['mean']:>8.3f}{e['min']:>8.3f}{e['max']:>8.3f}"
        if leak:
            r = leak["metrics"].get(m) or {}
            if r.get("file") is not None and "inside" in r:
                line += f"{r['file']:>8.3f}  {'inside' if r['inside'] else 'OUTSIDE'} (p {r['p_two_sided']:.2f}, " \
                        f"loo {r['loo_outside']:.2f})"
        L.append(line)
    if leak:
        s = leak["structures"]
        L.append(f"leakage test: {leak['verdict'].upper()}; outside the spread: {len(leak['outside'])} metrics "
                 f"({', '.join(leak['outside'][:8])}{' ...' if len(leak['outside']) > 8 else ''}); strong (the "
                 f"permutations agree): {leak['strong'][:8]}; structure sets: file-order mean Jaccard "
                 f"{s['file_mean_jaccard_to_permutations']} vs permutations {s['permutation_mean_jaccard_to_others']} "
                 f"({'inside' if s['inside'] else 'OUTSIDE'}), file-only structures {s['file_only']}; file order "
                 f"equals a permutation's answer: {leak['file_equals_a_permutation']}")
        L.append(f"  ({LEAKAGE_NOTE})")
    return "\n".join(L)


def score_mapped(truth, mapped, flags, baselines, flop_keys, outcomes=None, verdicts=None):
    """Score a mapped result; join statistics between the truth and the netlist's flops. `verdicts`
    is the harness's per-structure verdict record (verify_result()["structures"]), from which the
    scorer takes its honesty columns and the certified / transcribed params split; `flags` and
    `outcomes` are the two flat projections of the same verdicts and stay for records written
    before the verdicts were carried through."""
    T = score.Truth(truth)
    join = {"netlist_flops": len(flop_keys), "truth_flops": len(T.universe), "truth_unmapped": len(T.unmapped),
            "truth_shadow_flops": len(T.shadow_of), "truth_flops_in_netlist": len(T.universe & flop_keys),
            "netlist_flops_unknown_to_truth": len(flop_keys - T.universe - set(T.unmapped) - set(T.shadow_of))}
    problems, invalid = [], []
    if join["truth_flops_in_netlist"] != join["truth_flops"]:
        problems.append(f"join: only {join['truth_flops_in_netlist']}/{join['truth_flops']} truth flops are in "
                        "the netlist")
        invalid.append("the truth's join keys do not match this GDS (regenerate the truth)")
    t1 = time.perf_counter()
    rep = score.score(truth, mapped, baselines, verified=flags, outcomes=outcomes, verdicts=verdicts)
    return {"join": join, "score": rep, "text": score.render(rep), "score_s": round(time.perf_counter() - t1, 3),
            "problems_join": problems + rep["problems"], "invalid_join": invalid}


# ----------------------------------------------------------------------------------------------
# records, the blind protocol


def _utc():
    return datetime.datetime.now(datetime.timezone.utc)


def _stamp(created):
    return created.replace("-", "").replace(":", "").split("+")[0].split(".")[0] + "Z"


def _write_record(rec, blind, suffix="", runs=None):
    # blind records always go to out/s3/runs, development records to out/s3/eval/runs (or `runs`)
    runs = RUNS if blind else (runs or DEV_RUNS)
    os.makedirs(runs, exist_ok=True)
    body = json.dumps(rec, indent=1, sort_keys=True, default=str)
    h = hashlib.sha256(body.encode()).hexdigest()[:12]
    name = f"{'blind-' if blind else ''}{rec['design']}-{_stamp(rec['created'])}-{h}{suffix}.json"
    path = os.path.join(runs, name)
    with open(path, "x") as f:   # exclusive: never overwrite
        f.write(body + "\n")
    if blind:
        os.chmod(path, 0o444)
    return path, hashlib.sha256((body + "\n").encode()).hexdigest()


def clean_blind_process():
    """Problems with this process for a blind run (empty = fine): it must be the re-executed
    `python -B -X pycache_prefix=<fresh empty dir> -m tools.s3.run` (main() does that), and every
    loaded tools module must come from its source file."""
    bad = []
    prefix = os.environ.get(BLIND_PYCACHE_ENV)
    if not sys.flags.dont_write_bytecode:
        bad.append("not started with -B")
    if not prefix or sys.pycache_prefix != prefix:
        bad.append(f"pycache_prefix {sys.pycache_prefix!r} is not the fresh directory {prefix!r}")
    elif os.listdir(prefix):
        bad.append(f"pycache_prefix {prefix} is not empty")
    argv = list(getattr(sys, "orig_argv", []))
    want = ["-B", "-X", f"pycache_prefix={prefix}", "-m", "tools.s3.run"]
    if argv[1:6] != want:
        bad.append(f"started as {argv[:6]}, not python {' '.join(want)}")
    for name, m in list(sys.modules.items()):
        if name == "tools" or name.startswith("tools."):
            f = getattr(m, "__file__", None) or ""
            if f and not f.endswith(".py"):
                bad.append(f"module {name} loaded from {f}")
    return bad


def reexec_blind(argv):
    """Replace this process with `python -B -X pycache_prefix=<fresh dir> -m tools.s3.run argv`."""
    prefix = tempfile.mkdtemp(prefix="s3-pycache-")
    env = dict(os.environ, **{BLIND_PYCACHE_ENV: prefix})
    os.chdir(ROOT)
    args = [sys.executable, "-B", "-X", f"pycache_prefix={prefix}", "-m", "tools.s3.run", *argv]
    os.execve(sys.executable, args, env)


def _pinned_inputs(fr, design, files):
    """Mismatches between the design's input files and the freeze's pins (none pinned: [])."""
    pins = ((fr or {}).get("inputs") or {}).get(design) or {}
    bad = []
    for p, h in (pins.get("files") or {}).items():
        full = p if os.path.isabs(p) else os.path.join(ROOT, p)
        if not os.path.exists(full) or freeze.sha256_file(full) != h:
            bad.append(f"input {p}: missing or changed since the freeze")
    return bad


def _blind_preflight(design, gds, rerun_reason):
    """The freeze and ledger checks of a blind run; returns (freeze, rerun info, drawn flag)."""
    bad = freeze.check()
    if bad:
        raise SystemExit("blind run refused: the freeze does not hold:\n  " + "\n  ".join(bad))
    fr = freeze.load()
    prior = freeze.blind_results(design, fr["freeze_hash"])
    if prior and not rerun_reason:
        raise SystemExit(f"blind run refused: {design} already has a blind attempt under freeze "
                         f"{fr['freeze_hash'][:12]}: {prior} (pass --rerun-reason to add a labelled rerun)")
    rerun = {"reason": rerun_reason, "previous": prior} if prior else None
    unc = freeze.ledger_uncommitted(LEDGER_ROOT)
    if unc:
        raise SystemExit(f"blind run refused: {freeze.LEDGER_REL} has uncommitted entries ({unc}); commit it first")
    drawn = False
    if gds:
        ids = freeze.drawn_ids(fr)
        if score.design_id(design) not in ids:
            raise SystemExit(f"blind run refused: {design} is not among the designs drawn under this freeze")
        drawn = True
    elif design not in (fr.get("truth") or {}):
        raise SystemExit(f"blind run refused: {design} has no frozen truth")
    kind = os_sandbox_kind()
    if kind == "none":
        raise SystemExit("blind run refused: no OS-level sandbox on this host (macOS sandbox-exec, or Linux bwrap "
                         "with S3_OS_SANDBOX=bwrap)")
    bad = clean_blind_process()
    if bad:
        raise SystemExit("blind run refused: start it as `python -m tools.s3.run --blind ...` (it re-executes "
                         "itself with -B and a fresh pycache_prefix): " + "; ".join(bad))
    return fr, rerun, drawn


def permutations_for(blind, permutations=None, leakage_arm=False):
    """How many os.urandom permutations a run takes: a frozen (blind) evaluation and the leakage
    test at least FROZEN_PERMUTATIONS, a development run `permutations` (default 1)."""
    k = int(permutations or 0)
    if blind or leakage_arm:
        return max(k, FROZEN_PERMUTATIONS)
    return max(k, 1)


def run(design, gds=None, top=None, blind=False, rerun_reason=None, timeout=DEFAULT_TIMEOUT, truth_path=None,
        entry=ENTRY, baseline=True, write=True, echo=print, runs=None, permutations=None, leakage_arm=False, jobs=1):
    t_all = time.perf_counter()
    created = _utc().isoformat(timespec="seconds")
    fr, rerun, attempt = None, None, None
    if leakage_arm and not (blind or design == "tempo"):
        raise SystemExit("--leakage runs on TEMPO, or on a blind design together with --blind (a development run "
                         "of any other design is refused for the same reason as a plain run of it)")
    if blind:
        fr, rerun, _drawn = _blind_preflight(design, gds, rerun_reason)
    elif design == "puzzle" or gds:
        raise SystemExit(f"{design}: recognizer code runs on the puzzle and on third-party designs only once, after "
                         "the freeze (--blind); development runs take --design tempo (or synthetic netlists)")
    elif design != "tempo":
        raise SystemExit(f"unknown development design {design!r} (development: tempo)")
    k = permutations_for(blind, permutations, leakage_arm)
    default_truth = os.path.join(ROOT, "out", "s3", f"truth_{score.design_id(design)}.json")
    if blind and truth_path and os.path.realpath(truth_path) != os.path.realpath(default_truth):
        raise SystemExit("blind run refused: a blind run scores against the frozen out/s3/truth_<design>.json only")
    truth_path = truth_path or default_truth
    files = design_files(design, gds)
    inputs = {_rel(p): freeze.sha256_file(p) for p in files if os.path.exists(p)}
    if blind:
        bad = _pinned_inputs(fr, design, files)
        if bad:
            raise SystemExit("blind run refused: " + "; ".join(bad))
    truth = None
    if os.path.exists(truth_path):
        truth, _raw = score.load_truth(truth_path, design, strict=blind)
    elif not (blind and gds):
        raise SystemExit(f"no truth file {truth_path}")
    if blind:   # the attempt is on record before the netlist is even extracted
        attempt = _open_attempt(design, created, fr, rerun, gds)
    # one copy of the recognizer's sources for every child of this run, taken before extraction
    src_dir = tempfile.mkdtemp(prefix="s3-src-")
    staged = stage_sources(src_dir, entry)
    code = freeze.code_hashes()
    changed = sorted(rel for rel, h in staged[1].items() if rel in code and code[rel] != h)
    rec = {"schema": RUN_SCHEMA, "design": design, "created": created, "blind": blind, "rerun": rerun,
           "attempt": attempt, "freeze": {"freeze_hash": fr["freeze_hash"], "git_head": fr.get("git_head")} if fr else None,
           "git_head": freeze.git_head(), "code": code, "packages": freeze.package_versions(),
           "recognizer_sources": staged[1],
           "process": {"orig_argv": list(getattr(sys, "orig_argv", [])), "flags": str(sys.flags),
                       "pycache_prefix": sys.pycache_prefix, "executable": sys.executable},
           "inputs": inputs, "truth": ({"path": _rel(truth_path), "truth_hash": schema.truth_hash(truth),
                                        "check_truth_problems": len(schema.check_truth(truth))} if truth else None),
           "permutations": {"k": k, "file_order_arm": bool(leakage_arm), "jobs": int(jobs),
                            "source": "random.SystemRandom (os.urandom), one per evaluation; the file-order arm "
                                      "keeps the loader's ids"}}
    if design == "tempo":
        rec["tempo_snapshot"] = {"root": _rel(TEMPO_SNAPSHOT), "sha256sums": tempo_snapshot_check()}
    invalid, problems = [], []
    if changed:
        problems.append(f"recognizer files changed between staging and hashing (a concurrent edit): {changed}")
    t0 = time.perf_counter()
    try:
        nl, key = load_design(design, gds, top)
    except BaseException as e:
        shutil.rmtree(src_dir, ignore_errors=True)
        if blind:
            _close_attempt(attempt, None, None, False, f"extraction failed: {type(e).__name__}: {e}")
        raise
    extract_s = round(time.perf_counter() - t0, 3)
    nhash = freeze.netlist_hash(nl)
    rec["netlist_sha256"] = nhash
    pinned = (((fr or {}).get("inputs") or {}).get(design) or {}).get("netlist_sha256")
    if blind and pinned and pinned != nhash:
        shutil.rmtree(src_dir, ignore_errors=True)
        _close_attempt(attempt, None, None, False, "netlist differs from the freeze")
        raise SystemExit(f"blind run refused: the extracted netlist {nhash[:12]} differs from the frozen {pinned[:12]}")
    try:
        if k == 1 and not leakage_arm:
            evs, sp, leak = [evaluate(nl, key, truth, entry=entry, timeout=timeout, baseline=baseline,
                                      staged=staged)], None, None
        else:
            evs, sp, leak = evaluate_permutations(nl, key, truth, k, file_order=leakage_arm, jobs=jobs, entry=entry,
                                                  timeout=timeout, baseline=baseline, staged=staged)
    finally:
        shutil.rmtree(src_dir, ignore_errors=True)
    for ev in evs:
        ev["timings_s"]["extract_and_load_s"] = extract_s
        problems += [f"[{ev['label']}] {p}" if ev.get("label") else p for p in ev["problems"]]
        invalid += [f"[{ev['label']}] {p}" if ev.get("label") else p for p in ev["invalid_reasons"]]
        if ev["recognizer"].get("os_sandbox") == "none":
            problems.append("no OS-level sandbox on this host: the audit hook was the only isolation layer")
    flop_keys = evs[0].get("flop_keys", set())
    if truth is None:   # kept for --score-record: the netlist's flop join keys and the structural baseline
        rec["flop_keys"] = sorted(flop_keys)
    for ev in evs:
        ev.pop("flop_keys", None)
        bls = ev.pop("baselines", {})
        if truth is None:
            ev["baseline_results"] = bls
    if len(evs) == 1:   # the flat layout of a one-permutation run
        ev = evs[0]
        if truth is None:
            rec["baseline_results"] = ev.pop("baseline_results", {})
        for kk, v in ev.items():
            if kk not in ("problems", "invalid_reasons"):
                rec[kk] = v
    else:
        rec["evaluations"] = evs
        rec["spread"] = sp
        rec["leakage"] = leak
        if sp and sp.get("distinct_answers", 1) > 1:
            problems.append(f"the recognizer gave {sp['distinct_answers']} distinct answers (up to ids) over "
                            f"{sp['k']} permutations: it is not permutation invariant on this design, so every "
                            "metric below is one draw of a distribution (S3_DESIGN section 2)")
        if leak and leak.get("verdict") != "pass":
            problems.append(f"leakage test verdict {leak.get('verdict')!r}: strong {leak.get('strong')}, "
                            f"outside {leak.get('outside')}")
        rec["timings_s"] = {"extract_and_load_s": extract_s}
        first = next((e for e in evs if e.get("label") != "file"), evs[0])
        rec["text"] = "\n".join(x for x in (render_spread(sp, leak),
                                            f"\nFirst permutation ({first.get('label')}), in full:",
                                            first.get("text") or "") if x)
    if truth is None:
        rec["pending_truth"] = True
        problems.append("no truth yet: scored later with --score-record")
    rec["valid"] = not invalid
    rec["invalid_reasons"] = invalid
    rec["problems"] = problems
    rec["timings_s"]["total_s"] = round(time.perf_counter() - t_all, 3)
    rec["harness_peak_rss_mb"] = round(_peak_mb(), 1)
    path = None
    if write:
        path, rsha = _write_record(rec, blind, runs=runs)
        if blind:
            shas = [e.get("result_sha256") for e in evs]
            _close_attempt(attempt, path, rsha, rec["valid"], None, shas[0] if len(shas) == 1 else shas)
    _echo(rec, path, echo)
    rec["path"] = path
    return rec


def _rel(p):
    p = os.path.abspath(p)
    return os.path.relpath(p, ROOT) if p.startswith(ROOT + os.sep) else p


def _open_attempt(design, created, fr, rerun, gds):
    aid = secrets.token_hex(8)
    body = {"schema": freeze.ATTEMPT_SCHEMA, "design": design, "created": created, "attempt": aid,
            "freeze": {"freeze_hash": fr["freeze_hash"]}, "rerun": rerun, "gds": _rel(gds) if gds else None,
            "orig_argv": list(getattr(sys, "orig_argv", []))}
    path, sha = _write_record(body, True, suffix=".attempt")
    freeze.ledger_append({"event": "attempt", "attempt": aid, "design": design, "freeze_hash": fr["freeze_hash"],
                          "created": created, "record": _rel(path), "record_sha256": sha,
                          "rerun_reason": (rerun or {}).get("reason")}, LEDGER_ROOT)
    return {"id": aid, "record": _rel(path), "record_sha256": sha}


def _close_attempt(attempt, path, sha, valid, error, result_sha=None):
    if attempt is None:
        return
    freeze.ledger_append({"event": "finish", "attempt": attempt["id"], "record": _rel(path) if path else None,
                          "record_sha256": sha, "valid": valid, "error": error, "result_sha256": result_sha,
                          "created": _utc().isoformat(timespec="seconds")}, LEDGER_ROOT)


def _echo(rec, path, echo):
    if rec.get("text"):
        echo(rec["text"])
        echo("")
    for ev in rec.get("evaluations") or [rec]:
        r = ev.get("recognizer") or {}
        v = (ev.get("verify") or {}).get("summary") or {}
        lab = f"[{ev['label']}] " if ev.get("label") else ""
        echo(f"{lab}recognizer: ok={r.get('ok')} rc={r.get('returncode')} wall {r.get('wall_s')} s, child peak RSS "
             f"{r.get('peak_rss_mb')} MB (self-reported), OS sandbox {r.get('os_sandbox')}, audit-hook denials "
             f"{r.get('blocked_count')}")
        res = ((ev.get("score") or {}).get("result")) or {}
        echo(f"{lab}proofs: {v.get('verified', 0)}/{v.get('structures', 0)} structures verified by the harness "
             f"({v.get('claimed_proven', 0)} claimed proven; outcomes {res.get('outcomes', v.get('reasons'))}); "
             f"answer {str(ev.get('canonical_result_sha256'))[:12]}")
        # what that count is worth: never print "verified N" without the qualifications beside it
        hon = ((ev.get("score") or {}).get("honesty")) or {}
        hv = hon.get("verified") or {}
        if hv:
            sh = hv.get("load_hidden_share") or {}
            echo(f"{lab}of the verified: vacuous hold {hv.get('vacuous_hold', 0)}; with unchecked params "
                 f"{hv.get('with_unchecked_params', 0)}; with dead bits {hv.get('with_dead_bits', 0)}; "
                 f"load_hidden_share mean {sh.get('mean')} max {sh.get('max')} over {sh.get('n', 0)}; "
                 f"unverified by reason {hon.get('unverified_reasons', {})}")
        co = ((ev.get("recognize_run") or {}).get("canonical_order"))
        echo(f"{lab}canonical order: " + (json.dumps(co, sort_keys=True) if co else
                                          "none reported (see problems)"))
    first = rec.get("recognizer") or (rec.get("evaluations") or [{}])[0].get("recognizer") or {}
    echo(f"modules {first.get('recognizer_modules')}; netlist {str(rec.get('netlist_sha256'))[:12]}")
    echo(f"timings (s): {rec.get('timings_s')}; harness peak RSS {rec.get('harness_peak_rss_mb')} MB")
    if not rec.get("valid", True):
        echo("INVALID RUN: " + "; ".join(rec.get("invalid_reasons") or []))
    if path:
        echo(f"wrote {_rel(path)}")


def score_record(path, echo=print, write=True, truth_dir=None):
    """Score a blind run recorded before its (drawn, third-party) truth existed. The freeze must
    hold with the truth now present; the result is scored as recorded (with the harness's
    verified flags) and written as a new record that names the original."""
    bad = freeze.check()
    if bad:
        raise SystemExit("scoring refused: the freeze does not hold:\n  " + "\n  ".join(bad))
    bad = clean_blind_process()
    if bad:
        raise SystemExit("scoring refused: start it as `python -m tools.s3.run --score-record ...`: " + "; ".join(bad))
    with open(path, "rb") as f:
        body = f.read()
    rec = json.loads(body)
    if not rec.get("pending_truth") or not rec.get("blind"):
        raise SystemExit(f"{path}: not a blind record waiting for its truth")
    fr = freeze.load()
    if (rec.get("freeze") or {}).get("freeze_hash") != fr["freeze_hash"]:
        raise SystemExit(f"{path}: recorded under another freeze")
    tp = os.path.join(truth_dir or os.path.join(ROOT, "out", "s3"), f"truth_{score.design_id(rec['design'])}.json")
    truth, _raw = score.load_truth(tp, rec["design"], strict=True)
    flop_keys = set(rec.get("flop_keys") or [])
    out = {"schema": RUN_SCHEMA, "design": rec["design"], "created": _utc().isoformat(timespec="seconds"),
           "blind": True, "scores_record": {"path": _rel(path), "sha256": _sha256_bytes(body)},
           "freeze": rec["freeze"], "truth": {"path": _rel(tp), "truth_hash": schema.truth_hash(truth)},
           "code": freeze.code_hashes()}
    invalid = list(rec.get("invalid_reasons") or [])
    if rec.get("evaluations"):
        scored = []
        for ev in rec["evaluations"]:
            sc = score_mapped(truth, ev["result"], ev.get("verified_flags"), ev.get("baseline_results") or {},
                              flop_keys, ev.get("outcomes"), ((ev.get("verify") or {}).get("structures")))
            invalid += [f"[{ev.get('label')}] {x}" for x in sc["invalid_join"]]
            scored.append({"label": ev.get("label"), "join": sc["join"], "score": sc["score"], "text": sc["text"],
                           "problems": sc["problems_join"], "result": ev["result"], "outcomes": ev.get("outcomes"),
                           "verify": {"summary": (ev.get("verify") or {}).get("summary")},
                           "canonical_result_sha256": ev.get("canonical_result_sha256")})
        sp = spread([e for e in scored if e.get("label") != "file"])
        for e in scored:
            e.pop("result", None)
        out.update(evaluations=scored, spread=sp, join=scored[0]["join"],
                   text=render_spread(sp) + "\n\nFirst permutation, in full:\n" + scored[0]["text"],
                   problems=[p for e in scored for p in e["problems"]])
        join_bad = any(e["join"]["truth_flops_in_netlist"] != e["join"]["truth_flops"] for e in scored)
    else:
        sc = score_mapped(truth, rec["result"], rec.get("verified_flags"), rec.get("baseline_results") or {},
                          flop_keys, rec.get("outcomes"), ((rec.get("verify") or {}).get("structures")))
        invalid += sc["invalid_join"]
        out.update(join=sc["join"], score=sc["score"], text=sc["text"], problems=sc["problems_join"])
        join_bad = bool(sc["invalid_join"])
    out["valid"] = bool(rec.get("valid")) and not join_bad
    out["invalid_reasons"] = invalid
    p = None
    if write:
        p, sha = _write_record(out, True, suffix=".scored")
        freeze.ledger_append({"event": "scored", "attempt": (rec.get("attempt") or {}).get("id"),
                              "record": _rel(p), "record_sha256": sha, "scores": _rel(path),
                              "created": out["created"]}, LEDGER_ROOT)
    echo(out["text"])
    if p:
        echo(f"wrote {_rel(p)}")
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--design", help="tempo (development); puzzle or a drawn third-party id (--blind only)")
    ap.add_argument("--gds", help="GDS of a drawn third-party sky130_fd_sc_hd design (--blind only)")
    ap.add_argument("--top", help="top cell of --gds")
    ap.add_argument("--truth", help="truth file (development only; default out/s3/truth_<design>.json)")
    ap.add_argument("--blind", action="store_true", help="refuse unless the freeze holds; never overwrite")
    ap.add_argument("--rerun-reason", help="allow another blind attempt under one freeze (a new, labelled file)")
    ap.add_argument("--score-record", help="score a blind record whose truth was labelled after the run")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="recognizer time limit, seconds")
    ap.add_argument("--no-baseline", action="store_true", help="skip the structural baseline")
    ap.add_argument("--out", help="directory for a development run's record (default out/s3/eval/runs; blind "
                    "records always go to out/s3/runs)")
    ap.add_argument("--permutations", type=int, help="evaluate under K independent os.urandom permutations "
                    f"(development default 1; --blind and --leakage: at least {FROZEN_PERMUTATIONS})")
    ap.add_argument("--leakage", action="store_true", help="the leakage test (a file-order arm next to "
                    f">= {FROZEN_PERMUTATIONS} permutations): TEMPO, or a blind design with --blind")
    ap.add_argument("--jobs", type=int, default=1, help="recognizer children run at once (default 1)")
    a = ap.parse_args(argv)
    if (a.blind or a.score_record) and not os.environ.get(BLIND_PYCACHE_ENV):
        reexec_blind(argv)   # does not return
    if os.environ.get(BLIND_PYCACHE_ENV):   # the fresh, still empty cache directory goes when we exit
        import atexit
        atexit.register(lambda d=os.environ[BLIND_PYCACHE_ENV]: os.path.isdir(d) and not os.listdir(d) and os.rmdir(d))
    if a.score_record:
        out = score_record(a.score_record)
        sys.exit(0 if out["valid"] else 2)
    if not a.design:
        ap.error("--design is required")
    if a.blind and a.out:
        ap.error("--out is for development runs; blind records always go to out/s3/runs")
    rec = run(a.design, a.gds, a.top, a.blind, a.rerun_reason, a.timeout, a.truth, baseline=not a.no_baseline,
              runs=a.out, permutations=a.permutations, leakage_arm=a.leakage, jobs=max(1, a.jobs))
    sys.exit(0 if rec["valid"] else 2)


if __name__ == "__main__":
    main()
