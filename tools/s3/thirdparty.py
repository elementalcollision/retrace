"""S3 blind set: third-party Tiny Tapeout sky130 designs (candidate registration, flow probes, label pilot).

The puzzle is a frozen-code evaluation on a design the team already knows. A blind evaluation needs
designs nobody on the team has read: third-party Tiny Tapeout (TT) projects on sky130, which publish
the final layout, the gate-level netlist and (in the author's repository) the RTL. This module
registers a candidate list BEFORE recognizer development, by fixed criteria that do not look at a
design's structure, and runs the label pipeline on designs that are then excluded from that list.

    python -m tools.s3.thirdparty scan   [--per-stratum 6]   # -> out/s3/blind/candidates.json, scan.json
    python -m tools.s3.thirdparty probe  ID ...               # flow probes (excluded designs only)
    python -m tools.s3.thirdparty pilot  [ID | --all]         # label pilot -> out/s3/blind/pilot/
                                                              # (--all: the pilot and every flow probe)
    python -m tools.s3.thirdparty draw   --seed S --n N       # after the freeze: the blind draw

Data (checked 2026-09-21; candidates.json["shuttles"] has what each shuttle publishes)
  * TinyTapeout/tinytapeout-index (CC0) lists every shuttle and, per project, the author's repo and
    commit (TT03 records no commits; TT10 is not in the index, its designs were refabbed as CAD25a).
    The shuttle repositories (TinyTapeout/tinytapeout-XX, all Apache-2.0) hold, per project, the
    layout (GDS; OASIS only from TTSKY25b on; gds/*.gds.gz on TT02-TT03p5), the final powered
    gate-level netlist (projects/<macro>/<macro>.v; verilog/gl/<macro>.v on TT02-TT03p5), the LEF and
    copies of info.yaml/LICENSE. No shuttle publishes a per-project DEF. Instead, every std-cell
    reference in the layout carries its netlist instance name as GDS property 61 (flow stream-out;
    DEF-escaped, e.g. `a\\[3\\]`), which joins extracted instances to netlist instances exactly
    (`join_extraction`, checked net by net). gdstk reads the OASIS files with the properties intact.
  * The RTL is in the author's repository at the recorded commit (codeload tarball), not in the
    shuttle repo; it can disappear (deleted/renamed repos), so availability is a criterion.
  * Layout quirks the pipeline handles: every TT layout flattens its vias into top-level cut shapes,
    which RETRACE's extractor honours since Freeze 2 (`Extraction(top_cuts=True)`, the default; before
    it, only cuts inside via-cell references counted, and `prepare_layout`, which still wraps them into
    one, was what made them count);
    flipped and upright rows share GDS origins (the join keys on orientation too). OpenLane-1 era
    layouts (TT03p5-TT06 in the probes) also carry top-level text labels naming internal nets
    (`_0123_`, RTL register names): the blind harness must strip every label but the TT pinout and
    the instance-name properties before the recognizer sees a layout.

Criteria (fixed before recognizer development; none looks at a design's structure beyond size)
  C1 a TT "project" entry on a sky130 shuttle of the index, no analog pins, repo + 40-hex commit
  C2 not written by us (author/owner elementalcollision / Dave Graham), not the Jane Street puzzle,
     not a design inspected during this study (pilot, flow probes, INSPECTED; candidates only)
  C3 layout (GDS or OASIS) and gate-level netlist present in the shuttle repo at the index commit
  C4 netlist: every logic cell is sky130_fd_sc_hd (no macros, no other library) and >= 40 flops
  C5 the author's repo exists, holds the commit, and info.yaml there declares Verilog or
     SystemVerilog with all source files .v/.sv present under src/ (not Wokwi, not VHDL/HLS/etc.);
     the sources instantiate no sky130 flip-flop or latch cell (a hand-placed flop has no RTL register)
  C6 licence: the author's repo has an open licence GitHub recognises (see OK_LICENCES), or the
     shuttle's copy of the project LICENSE is Apache-2.0
  C7 one entry per design: duplicates across re-shuttles (TT03, TT05 open frame, CAD25a = TT08 + TT10
     refab) by repo or top macro, and forks of a TT project repo already accepted, are dropped (forks
     of templates are independent designs)

Draw: strata are the index's sky130 shuttles (a design's stratum is its first appearance); within a
stratum, projects are ranked by sha256(SALT|shuttle|macro) and accepted in rank order until the
stratum quota is met. Every checked project and its verdict is logged in scan.json.
"""

import argparse
import collections
import concurrent.futures as cf
import gzip
import hashlib
import io
import json
import os
import re
import ssl
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "out", "s3", "blind")
CACHE = os.environ.get("RETRACE_TT_CACHE", os.path.join(OUT, "cache"))  # gitignored (out/)
YOSYS = os.environ.get("YOSYS", os.path.expanduser("~/ttsetup/oss-cad-suite/bin/yosys"))
SKY_LIB = os.path.join(ROOT, "pdk/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib")
SKY_LEF = os.path.join(ROOT, "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef")

INDEX_REPO = "TinyTapeout/tinytapeout-index"
SALT_CANDIDATES = "retrace-s3-blind/candidates/v1"
SALT_PILOT = "retrace-s3-blind/pilot/v1"
MIN_FLOPS = 40
LANGUAGES = {"verilog", "systemverilog"}
OK_LICENCES = {"Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "Unlicense", "CC0-1.0",
               "CC-BY-4.0", "CC-BY-SA-4.0", "GPL-2.0", "GPL-3.0", "LGPL-2.1", "LGPL-3.0", "MPL-2.0",
               "CERN-OHL-P-2.0", "CERN-OHL-W-2.0", "CERN-OHL-S-2.0", "BSL-1.0", "Zlib", "WTFPL", "AGPL-3.0",
               "EUPL-1.2", "Apache-1.1", "BSD-4-Clause", "MIT-0", "SHL-0.51", "SHL-2.1"}
OURS = ("elementalcollision", "dave graham")
PUZZLE = ("janestreet", "jane street", "jane-street")
# designs looked at during this study (never candidates); pilot and probes are added by the draw
INSPECTED = {
    "tt06/tt_um_8bitALU": "downloaded (netlist, SPEF, GDS) during the data survey to see the file formats",
    "tt05of/tt_um_diferential_ringy": "label pipeline run as a flow probe before C5's flop-cell clause existed",
    "ttsky25a/tt_um_simonsays": "label pipeline run as a flow probe in an earlier draw of the probes",
    "ttsky25b/tt_um_tiny_shader_v2_mole99": "label pipeline run as a flow probe in an earlier draw of the probes",
}
PHYSICAL = ("tapvpwrvgnd", "decap", "fill", "diode", "fakediode")
HD, EF = "sky130_fd_sc_hd__", "sky130_ef_sc_hd__"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ============================================================================ fetching (cached)

def _cache_path(*parts):
    p = os.path.join(CACHE, *[re.sub(r"[^\w.\-]", "_", x) for x in parts])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def _ssl_context():
    """python.org builds on macOS ship without CA certificates; fall back to the system bundle."""
    for cafile in (os.environ.get("SSL_CERT_FILE"), "/etc/ssl/cert.pem"):
        if cafile and os.path.exists(cafile):
            return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


_SSL = _ssl_context()


def http_get(url, cache_parts=None, tries=4):
    """GET a URL (raw.githubusercontent.com / codeload), cached on disk when `cache_parts` is given.
    Returns bytes, or None on 404."""
    path = _cache_path(*cache_parts) if cache_parts else None
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
        return None if data == b"\0404" else data
    for t in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "retrace-s3"}),
                                        timeout=120, context=_SSL) as r:
                data = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = None
                break
            if t == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if t == tries - 1:
                raise
        time.sleep(2 * (t + 1))
    if path:
        with open(path, "wb") as f:
            f.write(b"\0404" if data is None else data)
    return data


def gh_api(path, cache=True):
    """GitHub REST API through the authenticated `gh` CLI; JSON, or None on 404/409/422."""
    cp = _cache_path("api", hashlib.sha256(path.encode()).hexdigest()[:24] + ".json") if cache else None
    if cp and os.path.exists(cp):
        with open(cp) as f:
            return json.load(f)
    for t in range(4):
        r = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github+json", path],
                           capture_output=True, text=True)
        if r.returncode == 0:
            data = json.loads(r.stdout) if r.stdout.strip() else None
            break
        if re.search(r"HTTP (404|409|422|451)", r.stderr):
            data = None
            break
        if t == 3:
            raise RuntimeError(f"gh api {path}: {r.stderr.strip()[:300]}")
        time.sleep(5 * (t + 1))
    if cp:
        with open(cp, "w") as f:
            json.dump(data, f)
    return data


def raw_url(repo, commit, path):
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"


def owner_repo(url):
    m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+?)(?:\.git)?/?$", (url or "").strip())
    return (m.group(1), m.group(2)) if m else None


def norm_repo(url):
    o = owner_repo(url)
    return f"{o[0]}/{o[1]}".lower() if o else (url or "").lower()


# ============================================================================ index and population

def load_index(commit=None):
    """The TT index at a pinned commit: (commit, {shuttle id: shuttle json}) for sky130 shuttles, in
    the index's own (chronological) order."""
    commit = commit or gh_api(f"repos/{INDEX_REPO}/commits/main", cache=False)["sha"]
    top = json.loads(http_get(raw_url(INDEX_REPO, commit, "index/index.json"), ("index", commit, "index.json")))
    out = {}
    for s in top["shuttles"]:
        if not str(s.get("pdk", "")).startswith("sky130"):
            continue
        data = http_get(raw_url(INDEX_REPO, commit, f"index/{s['id']}.json"), ("index", commit, s["id"] + ".json"))
        if data is None:
            continue
        sj = json.loads(data)
        sj["_meta"] = {k: v for k, v in s.items() if k != "projects"}
        out[s["id"]] = sj
    return commit, out


def shuttle_tree(sj):
    """{path: (blob sha, size)} of the shuttle repo at the index's commit (git trees API)."""
    repo = "/".join(owner_repo(sj["repo"]))
    t = gh_api(f"repos/{repo}/git/trees/{sj['commit']}?recursive=1")
    if t is None:
        raise RuntimeError(f"{repo}@{sj['commit']}: tree not found")
    if t.get("truncated"):
        raise RuntimeError(f"{repo}@{sj['commit']}: tree truncated")
    return {e["path"]: (e["sha"], e.get("size")) for e in t["tree"] if e["type"] == "blob"}


def project_files(tree, macro):
    """Shuttle-repo paths of a project's layout / netlist / LEF / LICENSE (both repo layouts)."""
    f = {}
    for ext, fmt in ((".gds", "gds"), (".oas", "oasis"), (".gds.gz", "gds.gz")):
        for p in (f"projects/{macro}/{macro}{ext}", f"gds/{macro}{ext}"):
            if p in tree and "layout" not in f:
                f["layout"] = {"path": p, "format": fmt, "git_blob": tree[p][0], "size": tree[p][1]}
    for p in (f"projects/{macro}/{macro}.v", f"verilog/gl/{macro}.v"):
        if p in tree:
            f["netlist"] = {"path": p, "git_blob": tree[p][0], "size": tree[p][1]}
            break
    for p in (f"projects/{macro}/{macro}.lef", f"lef/{macro}.lef"):
        if p in tree:
            f["lef"] = {"path": p, "git_blob": tree[p][0], "size": tree[p][1]}
            break
    for p in (f"projects/{macro}/LICENSE",):
        if p in tree:
            f["license"] = {"path": p, "git_blob": tree[p][0], "size": tree[p][1]}
    return f


def population(shuttles):
    """Every project entry, first appearance marked; duplicates point at their first appearance."""
    first_repo, first_macro, entries = {}, {}, []
    for sid, sj in shuttles.items():
        for p in sj["projects"]:
            e = {"id": f"{sid}/{p['macro']}", "shuttle": sid, "macro": p["macro"], "title": p.get("title"),
                 "author": p.get("author"), "repo": p.get("repo"), "commit": p.get("commit") or "",
                 "type": p.get("type", "project"), "analog_pins": p.get("analog_pins") or [],
                 "tiles": p.get("tiles")}
            rk, mk = norm_repo(e["repo"]), e["macro"]
            dup = first_repo.get(rk) or first_macro.get(mk)
            if dup:
                e["duplicate_of"] = dup
            else:
                first_repo[rk] = first_macro[mk] = e["id"]
            entries.append(e)
    return entries


def rank_key(salt, e):
    return hashlib.sha256(f"{salt}|{e['shuttle']}|{e['macro']}".encode()).hexdigest()


# ============================================================================ criteria

_SEQ = None
_SEQ_LOCK = threading.Lock()
POP_REPOS = set()  # normalised owner/repo of every project in the index (set by scan)


def lib_seq():
    """{cell: ('ff', next_state, iq, iqn) | ('latch',)} from the sky130 HD Liberty file."""
    global _SEQ
    with _SEQ_LOCK:  # scan threads call this concurrently: publish the table only when complete
        if _SEQ is None:
            txt = open(SKY_LIB).read()
            seq = {}
            for c in re.split(r'\n\s*cell\s*\(\s*"?', txt)[1:]:
                name = re.match(r"(\w+)", c).group(1)
                m = re.search(r'\n\s*ff\s*\(\s*"?(\w+)"?\s*,\s*"?(\w+)"?', c)
                if m:
                    seq[name] = ("ff", re.search(r'next_state\s*:\s*"([^"]*)"', c).group(1), m.group(1), m.group(2))
                elif re.search(r"\n\s*latch\s*\(", c):
                    seq[name] = ("latch",)
            _SEQ = seq
    return _SEQ


_INST = re.compile(r"(?m)^\s*([A-Za-z_][\w$]*)\s+(\\\S+|[A-Za-z_][\w$\[\]]*)\s*\(")
_KW = {"module", "input", "output", "inout", "wire", "assign", "reg", "endmodule", "parameter", "supply0",
       "supply1", "tri", "specify", "localparam"}


def netlist_facts(text):
    """Cell census of a gate-level netlist (size only): flops, latches, logic cells, foreign masters."""
    seq = lib_seq()
    masters = collections.Counter(m.group(1) for m in _INST.finditer(text) if m.group(1) not in _KW)
    flops = sum(n for c, n in masters.items() if seq.get(c, ("",))[0] == "ff")
    latches = sum(n for c, n in masters.items() if seq.get(c, ("",))[0] == "latch")
    foreign = sorted(c for c in masters if not c.startswith((HD, EF)))
    ef_logic = sorted(c for c in masters if c.startswith(EF) and not c[len(EF):].startswith(PHYSICAL))
    logic = sum(n for c, n in masters.items() if c.startswith(HD) and not c[len(HD):].startswith(PHYSICAL))
    return {"flops": flops, "latches": latches, "logic_cells": logic, "foreign_masters": foreign + ef_logic}


_CELL_INST = re.compile(r"\b(sky130_(?:fd|ef)_sc_\w+)\b")  # any mention outside comments (`ifdef-proof)
_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def _yaml(text):
    import yaml
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return {}


def check(e, shuttles, trees, deep=True):
    """Criteria C1-C6 for one population entry; returns (ok, reason, facts). Network calls are cached."""
    f = {}
    if e["type"] != "project":
        return False, f"C1 index type {e['type']}", f
    if e["analog_pins"]:
        return False, "C1 analog project", f
    if not owner_repo(e["repo"]) or not re.fullmatch(r"[0-9a-f]{40}", e["commit"]):
        return False, "C1 no GitHub repo + commit in the index", f
    blob = " ".join(str(x).lower() for x in (e["author"], e["repo"], e["title"]))
    if any(k in blob for k in OURS):
        return False, "C2 written by us", f
    owner = owner_repo(e["repo"])[0].lower()
    if owner in PUZZLE or any(k in (e["title"] or "").lower() for k in PUZZLE):
        return False, "C2 the Jane Street puzzle", f
    sj = shuttles[e["shuttle"]]
    files = project_files(trees[e["shuttle"]], e["macro"])
    f["files"] = files
    if "layout" not in files or "netlist" not in files:
        return False, "C3 layout or gate-level netlist missing in the shuttle repo", f
    if not deep:
        return True, "C1-C3 pass (shallow)", f
    srepo = "/".join(owner_repo(sj["repo"]))
    text = http_get(raw_url(srepo, sj["commit"], files["netlist"]["path"]),
                    ("shuttle", e["shuttle"], files["netlist"]["path"]))
    if text is None:
        return False, "C3 netlist not downloadable", f
    f["netlist_sha256"] = hashlib.sha256(text).hexdigest()
    facts = netlist_facts(text.decode("utf-8", "replace"))
    f.update(facts)
    if facts["foreign_masters"]:
        return False, f"C4 non-HD cells: {facts['foreign_masters'][:4]}", f
    if facts["flops"] < MIN_FLOPS:
        return False, f"C4 {facts['flops']} flops < {MIN_FLOPS}", f
    o, r = owner_repo(e["repo"])
    info = gh_api(f"repos/{o}/{r}")
    if info is None:
        return False, "C5 author repo not found", f
    f["repo_full_name"] = info["full_name"]
    f["repo_licence"] = (info.get("license") or {}).get("spdx_id")
    f["fork_source"] = (info.get("source") or {}).get("full_name") if info.get("fork") else None
    tree = gh_api(f"repos/{info['full_name']}/git/trees/{e['commit']}?recursive=1")
    if tree is None:
        return False, "C5 commit not in the author repo", f
    paths = {x["path"] for x in tree.get("tree", []) if x["type"] == "blob"}
    iy = http_get(raw_url(info["full_name"], e["commit"], "info.yaml"), ("repo", info["full_name"], e["commit"], "info.yaml"))
    y = _yaml(iy.decode("utf-8", "replace")) if iy else {}
    proj = y.get("project") or {}
    lang = str(proj.get("language") or (y.get("documentation") or {}).get("language") or "").strip()
    srcs = proj.get("source_files") or []
    f["language"], f["top_module"], f["source_files"] = lang, proj.get("top_module"), srcs
    if proj.get("wokwi_id") not in (None, 0, "0"):
        return False, "C5 Wokwi project", f
    if lang and not set(re.split(r"[\s,/+&]+|\band\b", lang.lower())) - {""} <= LANGUAGES:
        return False, f"C5 language {lang!r}", f
    if not srcs or not all(str(s).endswith((".v", ".sv", ".vh", ".svh")) for s in srcs):
        return False, "C5 source files not all Verilog", f
    base = "src/" if all(f"src/{s}" in paths for s in srcs) else ""
    if not all(f"{base}{s}" in paths for s in srcs):
        return False, "C5 listed source files missing at the commit", f
    f["src_dir"] = base.rstrip("/") or "."
    f["rtl_tree_sha"] = tree.get("sha")
    for sname in srcs:
        body = http_get(raw_url(info["full_name"], e["commit"], f"{base}{sname}"),
                        ("repo", info["full_name"], e["commit"], f"{base}{sname}"))
        hand = {m.group(1) for m in _CELL_INST.finditer(_COMMENTS.sub("", body.decode("utf-8", "replace")))} \
            if body else set()
        if any(c in lib_seq() for c in hand):
            return False, "C5 RTL instantiates sky130 flip-flop/latch cells (no RTL register to label)", f
    lic_ok = f["repo_licence"] in OK_LICENCES
    if not lic_ok and "license" in files:
        lt = http_get(raw_url(srepo, sj["commit"], files["license"]["path"]),
                      ("shuttle", e["shuttle"], files["license"]["path"]))
        f["shuttle_license_file"] = "Apache-2.0" if lt and b"Apache License" in lt and b"Version 2.0" in lt else "other"
        lic_ok = f["shuttle_license_file"] == "Apache-2.0"
    if not lic_ok:
        return False, f"C6 licence {f['repo_licence']!r}", f
    # C7 key: a fork counts as the design it was forked from only when that repo is itself a TT project
    # (a re-submission or variant); forks of templates (TinyTapeout/*-template, course templates) are
    # independent designs
    fs = (f["fork_source"] or "").lower()
    f["source_key"] = fs if fs and fs in POP_REPOS else info["full_name"].lower()
    return True, "pass", f


# ============================================================================ scan and draw

def scan(per_stratum=6, index_commit=None, n_probes=0, pilot_stratum="ttsky25a", workers=12):
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    icommit, shuttles = load_index(index_commit)
    log(f"index {INDEX_REPO}@{icommit[:10]}: sky130 shuttles {list(shuttles)}")
    with cf.ThreadPoolExecutor(workers) as ex:
        trees = dict(zip(shuttles, ex.map(lambda s: shuttle_tree(shuttles[s]), shuttles)))
    shuttle_info = {}
    for sid, sj in shuttles.items():
        repo = "/".join(owner_repo(sj["repo"]))
        lic = gh_api(f"repos/{repo}")
        layouts = collections.Counter(project_files(trees[sid], p["macro"]).get("layout", {}).get("format", "none")
                                      for p in sj["projects"])
        shuttle_info[sid] = {"name": sj.get("name"), "repo": sj["repo"], "commit": sj["commit"],
                             "repo_licence": (lic.get("license") or {}).get("spdx_id") if lic else None,
                             "pdk": sj["_meta"].get("pdk"), "projects": len(sj["projects"]),
                             "layout_formats": dict(layouts),
                             "netlists": sum(1 for p in sj["projects"] if "netlist" in project_files(trees[sid], p["macro"])),
                             "projects_with_def": sum(1 for p in sj["projects"]
                                                      if any(k.endswith((".def", ".def.gz")) and p["macro"] in k
                                                             for k in trees[sid]))}
    pop = population(shuttles)
    POP_REPOS.update(norm_repo(e["repo"]) for e in pop)
    primaries = [e for e in pop if "duplicate_of" not in e]
    log(f"population: {len(pop)} entries, {len(primaries)} distinct designs")
    for e in primaries:
        e["rank"] = rank_key(SALT_CANDIDATES, e)
        e["pilot_rank"] = rank_key(SALT_PILOT, e)
    checked, results, used, accepted_sources = {}, {}, set(), set()

    def walk(order, want, pred=lambda e, f: True, role="candidate"):
        """accept entries of `order` in order until `want`; checks run in parallel batches, decisions
        are made strictly in order (C7 depends on what was accepted before)."""
        got, i, step = [], 0, max(want * 2, 8)
        while len(got) < want and i < len(order):
            batch = [e for e in order[i:i + step] if e["id"] not in used]
            i += step
            todo = [e for e in batch if e["id"] not in results]
            with cf.ThreadPoolExecutor(workers) as ex:
                for e, r in zip(todo, ex.map(lambda e: check(e, shuttles, trees), todo)):
                    results[e["id"]] = r
            for e in batch:
                if len(got) >= want:
                    break
                ok, why, f = results[e["id"]]
                if ok and role == "candidate" and e["id"] in INSPECTED:
                    ok, why = False, f"C2 inspected during this study: {INSPECTED[e['id']]}"
                if ok and f.get("source_key") in accepted_sources:
                    ok, why = False, f"C7 fork of / same source as {f['source_key']}"
                if ok and not pred(e, f):
                    checked.setdefault(e["id"], {"verdict": "eligible", "reason": f"passes; outside the {role} rule",
                                                 **_brief(e, f)})
                    continue
                checked[e["id"]] = {"verdict": role if ok else "rejected", "reason": why, **_brief(e, f)}
                if ok:
                    accepted_sources.add(f.get("source_key"))
                    used.add(e["id"])
                    got.append((e, f))
        return got

    # 1. pilot (one design, ttsky25a: it publishes both GDS and OASIS) and flow probes, excluded
    by_pilot = sorted(primaries, key=lambda e: e["pilot_rank"])
    pilot = walk([e for e in by_pilot if e["shuttle"] == pilot_stratum], 1,
                 pred=lambda e, f: f["flops"] <= 1000, role="pilot")
    probes = []
    if n_probes:
        for sid in shuttles:
            probes += walk([e for e in by_pilot if e["shuttle"] == sid], n_probes, role="probe")
    # 2. candidates: per stratum, by candidate rank
    cands = []
    strata = collections.OrderedDict()
    for sid in shuttles:
        order = sorted([e for e in primaries if e["shuttle"] == sid], key=lambda e: e["rank"])
        got = walk(order, per_stratum)
        strata[sid] = {"distinct_designs": len(order), "checked": sum(1 for e in order if e["id"] in checked),
                       "accepted": len(got),
                       "eligible_rate_among_checked": None}
        cands += got
        log(f"  {sid}: {len(got)} of {per_stratum} (checked {strata[sid]['checked']} of {len(order)})")
    for sid, st in strata.items():
        ch = [v for k, v in checked.items() if k.startswith(sid + "/")]
        ok = sum(1 for v in ch if v["verdict"] in ("candidate", "pilot", "probe", "eligible"))
        st["eligible_rate_among_checked"] = round(ok / len(ch), 3) if ch else None
    reasons = collections.Counter(re.match(r"(C\d)", v["reason"]).group(1) if v["reason"].startswith("C") else v["reason"]
                                  for v in checked.values() if v["verdict"] == "rejected")

    def rec(e, f, role):
        sj = shuttles[e["shuttle"]]
        srepo = "/".join(owner_repo(sj["repo"]))
        files = {k: {**v, "url": raw_url(srepo, sj["commit"], v["path"])} for k, v in f["files"].items()}
        return {"id": e["id"], "role": role, "stratum": e["shuttle"], "macro": e["macro"], "title": e["title"],
                "author": e["author"], "tiles": e["tiles"],
                "rank": e["rank"] if role == "candidate" else e["pilot_rank"],
                "shuttle_repo": sj["repo"], "shuttle_commit": sj["commit"], "files": files,
                "netlist_sha256": f["netlist_sha256"],
                "rtl": {"repo": f"https://github.com/{f['repo_full_name']}", "commit": e["commit"],
                        "tarball": f"https://codeload.github.com/{f['repo_full_name']}/tar.gz/{e['commit']}",
                        "tree_sha": f["rtl_tree_sha"], "top_module": f["top_module"], "language": f["language"],
                        "src_dir": f["src_dir"], "source_files": f["source_files"]},
                "licence": {"author_repo": f["repo_licence"], "shuttle_license_file": f.get("shuttle_license_file"),
                            "shuttle_repo": shuttle_info[e["shuttle"]]["repo_licence"]},
                "fork_source": f.get("fork_source"),
                "size": {"flops": f["flops"], "latches": f["latches"], "logic_cells": f["logic_cells"]}}

    excluded = [rec(e, f, "pilot") for e, f in pilot] + [rec(e, f, "probe") for e, f in probes]
    doc = {
        "schema": "retrace-s3-blind-candidates/1",
        "registered": time.strftime("%Y-%m-%d", time.gmtime()),
        "purpose": "pre-registered pool for S3's blind evaluation, fixed before recognizer development; "
                   "after the freeze a seed committed at freeze time draws the blind set from `candidates` "
                   "(python -m tools.s3.thirdparty draw --seed S --n N)",
        "index": {"repo": f"https://github.com/{INDEX_REPO}", "commit": icommit, "licence": "CC0-1.0"},
        "criteria": {"C1": "TT project entry on a sky130 shuttle of the index; no analog pins; GitHub repo and "
                           "commit recorded",
                     "C2": "not ours (elementalcollision / Dave Graham), not the Jane Street puzzle, not inspected "
                           "during this study (pilot, probes, survey downloads)",
                     "C3": "layout (GDS/OASIS) and gate-level netlist in the shuttle repo at the index commit",
                     "C4": f"netlist cells all sky130_fd_sc_hd (+ sky130_ef_sc_hd fill/decap); >= {MIN_FLOPS} flops",
                     "C5": "author repo and commit exist; info.yaml declares Verilog/SystemVerilog; all source "
                           "files .v/.sv present at the commit; no sky130 flip-flop/latch cell instantiated in them",
                     "C6": "open licence on the author repo (GitHub SPDX in OK_LICENCES) or an Apache-2.0 "
                           "LICENSE copy in the shuttle repo",
                     "C7": "one entry per design: first appearance across shuttles; same repo, same macro, or a "
                           "fork of a TT project repo already accepted (template forks are independent)"},
        "draw_rule": {"salt": SALT_CANDIDATES, "rank": "sha256(salt|shuttle|macro), ascending",
                      "strata": list(shuttles), "per_stratum": per_stratum,
                      "procedure": "within each stratum (a design's first shuttle), check entries in rank order "
                                   "and accept the first per_stratum that pass C1-C7",
                      "pilot_rule": {"salt": SALT_PILOT, "stratum": pilot_stratum, "flops_max": 1000,
                                     "why": "ttsky25a publishes GDS and OASIS, so one pilot exercises both readers"}},
        "shuttles": shuttle_info,
        "strata": strata,
        "rejections_among_checked": dict(sorted(reasons.items())),
        "excluded": excluded,
        "candidates": [rec(e, f, "candidate") for e, f in cands],
    }
    doc["candidates_sha256"] = hashlib.sha256(json.dumps(doc["candidates"], sort_keys=True,
                                                         separators=(",", ":")).encode()).hexdigest()
    with open(os.path.join(OUT, "candidates.json"), "w") as fh:
        json.dump(doc, fh, indent=1)
    with open(os.path.join(OUT, "scan.json"), "w") as fh:
        json.dump({"index_commit": icommit, "seconds": round(time.time() - t0, 1),
                   "population": {"entries": len(pop), "distinct_designs": len(primaries),
                                  "duplicates": len(pop) - len(primaries)},
                   "checked": dict(sorted(checked.items()))}, fh, indent=1)
    log(f"wrote {OUT}/candidates.json: {len(cands)} candidates, {len(excluded)} excluded "
        f"({time.time() - t0:.0f} s)")
    return doc


def _brief(e, f):
    return {"author": e["author"], "repo": e["repo"], "commit": e["commit"],
            **{k: f[k] for k in ("flops", "latches", "language", "repo_licence", "fork_source") if k in f}}


def draw(seed, n, path=None):
    """The blind draw (run after the freeze): the n candidates with the lowest sha256(seed|id), and
    the rest in the same order as reserves. Rule: a drawn design the frozen label pipeline cannot
    label (e.g. Yosys rejects its SystemVerilog) is replaced by the next reserve, and reported."""
    path = path or os.path.join(OUT, "candidates.json")
    doc = json.load(open(path))
    got = hashlib.sha256(json.dumps(doc["candidates"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if got != doc["candidates_sha256"]:
        raise SystemExit(f"candidates changed since registration ({got} != {doc['candidates_sha256']})")
    order = sorted(doc["candidates"], key=lambda c: hashlib.sha256(f"{seed}|{c['id']}".encode()).hexdigest())
    return {"seed": seed, "candidates_sha256": got, "blind": [c["id"] for c in order[:n]],
            "reserve": [c["id"] for c in order[n:]]}


# ============================================================================ layout, netlist, join

def _git_blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def fetch_layout(rec):
    """A plain GDS file for a record's layout (gunzip, or OASIS -> GDS through gdstk); the download
    is checked against the git blob id the registration recorded."""
    import gdstk
    lay = rec["files"]["layout"]
    out = _cache_path("layout", rec["id"].replace("/", "__") + ".gds")
    raw = http_get(lay["url"], ("shuttle", rec["stratum"], lay["path"]))
    if raw is None:
        raise RuntimeError(f"{rec['id']}: layout not downloadable")
    if _git_blob_sha(raw) != lay["git_blob"]:
        raise RuntimeError(f"{rec['id']}: layout content differs from the registered blob")
    if not os.path.exists(out):
        if lay["format"] == "gds":
            with open(out, "wb") as f:
                f.write(raw)
        elif lay["format"] == "gds.gz":
            with open(out, "wb") as f:
                f.write(gzip.decompress(raw))
        else:
            oas = out[:-4] + ".oas"
            with open(oas, "wb") as f:
                f.write(raw)
            gdstk.read_oas(oas).write_gds(out)
    return out, lay["format"], len(raw)


def prepare_layout(gds, top):
    """Every TT layout seen flattens its vias into top-level polygons. Move top-level cut polygons
    into one via-prefixed cell (`Tech.via_prefix`) referenced at the origin (geometry unchanged).
    Before Freeze 2 RETRACE's extractor joined layers only through cuts inside via-cell references,
    so this move was what connected the vias; the extractor now binds top-level cuts itself
    (`Extraction(top_cuts=True)`, the default) and gives the same nets either way, so the move is
    redundant for extraction but harmless, and kept so that runs stay reproducible. TT02-era
    layouts put their pin labels on texttype 16 (pin) instead of 5: retype those to 5 so the pins
    keep their names (still needed). Returns (path to use, number of cut shapes moved)."""
    import gdstk
    from ..retrace.tech import SKY130_HD
    lib = gdstk.read_gds(gds)
    cell = next(c for c in lib.top_level() if c.name == top)
    cuts = {(c.layer, c.datatype) for c in SKY130_HD.cuts}
    flat = [q for q in cell.polygons if (q.layer, q.datatype) in cuts]
    layers = {c.layer: c.label_dt for c in SKY130_HD.conductors}
    pin_text = [lb for lb in cell.labels if lb.layer in layers and lb.texttype == 16]
    if not flat and not pin_text:
        return gds, 0
    out = gds[:-4] + ".prep.gds"
    if not os.path.exists(out):
        for lb in pin_text:
            lb.texttype = layers[lb.layer]
        if flat:
            via = gdstk.Cell(SKY130_HD.via_prefix + "_RETRACE_FLAT_CUTS")
            via.add(*[q.copy() for q in flat])
            cell.remove(*flat)
            cell.add(gdstk.Reference(via))
            lib.add(via)
        lib.write_gds(out)
    return out, len(flat)


TT_PINS = re.compile(r"^(clk|ena|rst_n|ui_in\[\d\]|uo_out\[\d\]|uio_in\[\d\]|uio_out\[\d\]|uio_oe\[\d\]|"
                     r"io_in\[\d\]|io_out\[\d\]|VPWR|VGND|VDPWR|VAPWR)$")


def anonymise_layout(gds, top, out):
    """The layout a recognizer may see: every reference property (the instance names) and every
    top-level label that is not a Tiny Tapeout pin or supply removed. OpenLane-1 layouts label
    internal nets (`_0123_`, RTL register names), which the extractor would use as net names.
    Returns {"properties_removed", "labels_removed", "labels_kept"}."""
    import gdstk
    lib = gdstk.read_gds(gds)
    cell = next(c for c in lib.top_level() if c.name == top)
    props = 0
    for c in lib.cells:
        for ref in c.references:
            if ref.properties:
                props += 1
                ref.properties = []
    drop = [lb for lb in cell.labels if not TT_PINS.match(lb.text)]
    cell.remove(*drop)
    lib.write_gds(out)
    return {"properties_removed": props, "labels_removed": len(drop), "labels_kept": len(cell.labels)}


def fetch_netlist(rec):
    nl = rec["files"]["netlist"]
    raw = http_get(nl["url"], ("shuttle", rec["stratum"], nl["path"]))
    if raw is None or hashlib.sha256(raw).hexdigest() != rec["netlist_sha256"]:
        raise RuntimeError(f"{rec['id']}: netlist missing or changed since registration")
    return raw.decode("utf-8", "replace")


_PHYS_INST = re.compile(r"(?ms)^\s*sky130_(?:fd_sc_hd__(?:%s)\w*|ef_sc_hd__\w+)\s+\S+\s*\(.*?\);" % "|".join(PHYSICAL))
_SUPPLY_CONN = re.compile(r"\.(?:VPWR|VGND|VPB|VNB)\s*\([^()]*\)\s*,?")


def clean_netlist(text):
    """The powered gate-level netlist without physical-only cells and supply pins (the Liberty
    models Yosys reads have no pg pins)."""
    text = _PHYS_INST.sub("", text)
    text = _SUPPLY_CONN.sub("", text)
    return re.sub(r",\s*\)", ")", text)


def yosys_json(verilog_path, top, out_json, lib=SKY_LIB):
    script = f"read_liberty -lib {lib}; read_verilog {verilog_path}; hierarchy -top {top}; write_json {out_json}"
    r = subprocess.run([YOSYS, "-q", "-p", script], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"yosys: {r.stderr[-1500:]}")
    with open(out_json) as f:
        return json.load(f)["modules"][top]


class GateNetlist:
    """A Yosys JSON module of a gate-level netlist: cells {inst: (type, {pin: bit})}, names per bit."""

    def __init__(self, module):
        from . import truth_tempo as tt
        self.ports = module["ports"]
        self.cells = {}
        for cn, c in module["cells"].items():
            self.cells[cn.lstrip("\\")] = (c["type"], {p: b[0] for p, b in c["connections"].items() if len(b) == 1})
        self.port_name, self.names = {}, collections.defaultdict(list)
        for pn, p in module["ports"].items():
            for i, b in enumerate(p["bits"]):
                if not isinstance(b, str):
                    self.port_name[b] = pn if len(p["bits"]) == 1 else f"{pn}[{i}]"
        for n, w in module["netnames"].items():
            if w.get("hide_name"):
                continue
            for idx, b in zip(tt._indices(w), w["bits"]):
                if not isinstance(b, str):
                    self.names[b].append(n.lstrip("\\") if len(w["bits"]) == 1 else f"{n.lstrip(chr(92))}[{idx}]")

    def pins(self):
        """{(inst, pin): bit} over signal pins."""
        return {(i, p): b for i, (_t, con) in self.cells.items() for p, b in con.items()}


_GENERATED = re.compile(r"^(net\d+|_\d+_|clknet_\w+|clkbuf_\w+|n\d+|output\d+|input\d+|rebuffer\d+|split\d+|"
                        r"wire\d+|max_cap\d+|fanout\d+|place\d+|hold\d+|ANTENNA\w*|.*\$.*)$")


def is_generated(name):
    return bool(_GENERATED.match(name))


def join_extraction(ex, gn):
    """Map extracted instances to netlist instances through the layout's GDS property 61 (instance
    name), then check connectivity: every extracted signal net must be exactly one netlist net and
    vice versa. Returns (ex_name -> nl_name, report)."""
    import math
    from ..retrace.extract import ORIENT
    # rows abut, so a flipped cell and an upright one can share a GDS origin: key on orientation too
    ex_by_key = {(i["master"], *i["gds_origin"], i["orient"]): i["name"] for i in ex.instances}
    name_map, no_prop = {}, 0
    for ref in ex.top.references:
        nm = None
        for p in ref.properties or []:
            vals = list(p[1:]) if isinstance(p, (list, tuple)) else []
            if 61 in vals:
                v = vals[vals.index(61) + 1] if vals.index(61) + 1 < len(vals) else None
                nm = (v.rstrip(b"\0").decode() if isinstance(v, bytes) else str(v)).strip()
        orient = ORIENT.get((int(round(math.degrees(ref.rotation))) % 360, bool(ref.x_reflection)))
        key = (ref.cell.name, int(round(ref.origin[0] * 1000)), int(round(ref.origin[1] * 1000)), orient)
        if key in ex_by_key:
            if nm is None:
                no_prop += 1
            else:  # DEF escapes brackets (and other specials) in instance names; Verilog/Yosys does not
                name_map[ex_by_key[key]] = re.sub(r"\\(.)", r"\1", nm.lstrip("\\"))
    logic = {i["name"] for i in ex.logic_instances()}
    master = {i["name"]: i["master"] for i in ex.instances}
    nl_pins = gn.pins()
    unknown = sorted(n for n in logic if name_map.get(n) not in gn.cells)
    missing = sorted(set(gn.cells) - {name_map.get(n) for n in logic})
    master_bad = sorted(n for n in logic if name_map.get(n) in gn.cells and gn.cells[name_map[n]][0] != master[n])
    supply = set(ex.tech.supply_pins)
    ok = split = merged = 0
    seen = collections.defaultdict(set)
    for m in ex.nets:
        bits = set()
        for inst, pin in m["pins"]:
            if pin in supply or inst not in logic:
                continue
            b = nl_pins.get((name_map.get(inst), pin))
            bits.add(b)
        bits.discard(None)
        if not bits:
            continue
        for b in bits:
            seen[b].add(m["root"])
        if len(bits) == 1:
            ok += 1
        else:
            merged += 1
    split = sum(1 for b, roots in seen.items() if len(roots) > 1)
    nl_bits = {b for b in nl_pins.values() if not isinstance(b, str)}
    absent = len(nl_bits - set(seen))
    port_ok, port_bad = 0, []
    nl_ports = set(gn.port_name.values())
    labels = [n for n in ex.ports if n not in nl_ports]
    net_at = {m["root"]: m for m in ex.nets}
    for pname, sid in ex.ports.items():
        if pname not in nl_ports:
            continue
        m = net_at.get(ex.uf.find(sid))
        bits = {nl_pins.get((name_map.get(i), p)) for i, p in (m["pins"] if m else []) if i in logic} - {None}
        want = {b for b, n in gn.port_name.items() if n == pname}
        if bits and bits == want:
            port_ok += 1
        elif bits:
            port_bad.append(pname)
    rep = {"method": "GDS property 61 on each std-cell reference = netlist instance name",
           "layout_std_cell_refs_without_name": no_prop, "extracted_logic_instances": len(logic),
           "netlist_logic_instances": len(gn.cells), "extracted_without_netlist_instance": len(unknown),
           "netlist_without_extracted_instance": len(missing), "master_mismatch": len(master_bad),
           "nets_one_to_one": ok, "extracted_nets_spanning_several_netlist_nets": merged,
           "netlist_nets_split_over_several_extracted_nets": split,
           "netlist_nets_without_extracted_net": absent,
           "ports_agree": port_ok, "ports_disagree": port_bad[:10],
           "non_port_net_labels": len(labels),
           "non_port_net_labels_rtl_like": sum(1 for n in labels if not is_generated(n)),
           "examples": {"unknown": unknown[:5], "missing": missing[:5], "master_mismatch": master_bad[:5]}}
    rep["clean"] = not (no_prop or unknown or missing or master_bad or merged or split or absent or port_bad)
    return name_map, rep


def extract_and_join(rec, work):
    """Download (checked against the registered blob ids), RETRACE extraction (sky130 HD) of the
    layout and its join to the named gate-level netlist. Returns (Extraction, GateNetlist,
    {extracted instance: netlist instance}, facts, timings, cleaned netlist path)."""
    import resource
    from ..retrace.extract import Extraction
    from ..retrace.lef import read_lef
    res, tim = {}, {}
    t = time.time()
    gds, fmt, nbytes = fetch_layout(rec)
    text = fetch_netlist(rec)
    tim["download"] = round(time.time() - t, 1)
    os.makedirs(work, exist_ok=True)
    clean = os.path.join(work, "netlist_clean.v")
    with open(clean, "w") as f:
        f.write(clean_netlist(text))
    t = time.time()
    gn = GateNetlist(yosys_json(clean, rec["macro"], os.path.join(work, "netlist.json")))
    tim["read_netlist"] = round(time.time() - t, 1)
    t = time.time()
    gds, moved = prepare_layout(gds, rec["macro"])
    lef = read_lef(SKY_LEF)
    ex = Extraction(gds, lef, top=rec["macro"])
    tim["extract"] = round(time.time() - t, 1)
    t = time.time()
    name_map, rep = join_extraction(ex, gn)
    tim["join"] = round(time.time() - t, 1)
    seq = lib_seq()
    flops = [n for n, (typ, _c) in gn.cells.items() if seq.get(typ, ("",))[0] == "ff"]
    named = 0
    for n in flops:
        b = gn.cells[n][1].get("Q")
        nms = gn.names.get(b, []) + ([gn.port_name[b]] if b in gn.port_name else [])
        named += any(not is_generated(x) for x in nms)
    res.update(layout_format=fmt, layout_bytes=nbytes, flat_cut_shapes_wrapped=moved,
               extraction=ex.summary()["diagnostics"],
               join=rep, netlist_flops=len(flops), flops_with_rtl_like_q_name=named,
               peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20))
    return ex, gn, name_map, res, tim, clean


def probe(rec):
    """Flow probe on an excluded design: layout readable, instance names in the layout, join clean,
    share of flop Q nets that keep a non-generated name. Aggregate numbers only."""
    ex, gn, name_map, res, tim, _clean = extract_and_join(rec, os.path.join(CACHE, "work", rec["id"].replace("/", "__")))
    return {"id": rec["id"], **res, "timings_s": tim}


# ============================================================================ RTL labels (pilot)

def fetch_rtl(rec, work):
    """The author's sources at the recorded commit (codeload tarball) -> work/src; returns paths."""
    rtl = rec["rtl"]
    raw = http_get(rtl["tarball"], ("rtl", rec["id"].replace("/", "__") + ".tar.gz"))
    if raw is None:
        raise RuntimeError(f"{rec['id']}: RTL tarball not found")
    repo = os.path.join(work, "repo")
    os.makedirs(repo, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:  # whole repo: $readmem paths may leave src/
        for m in tf.getmembers():
            parts = m.name.split("/", 1)
            if len(parts) < 2 or not m.isfile() or ".." in parts[1].split("/") or m.size > 64 << 20:
                continue
            path = os.path.join(repo, parts[1])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(tf.extractfile(m).read())
    dst = os.path.join(repo, rtl["src_dir"]) if rtl["src_dir"] != "." else repo
    files = [os.path.join(dst, s) for s in rtl["source_files"]]
    missing = [f for f in files if not os.path.exists(f)]
    if missing:
        raise RuntimeError(f"{rec['id']}: sources missing after extraction: {missing}")
    return dst, files


# defines a TT hardening flow sets (OpenLane 2 / LibreLane); the RTL is read as the flow read it
FLOW_DEFINES = ("SYNTHESIS", "__openlane__", "__librelane__", "__pnr__")


def run_rtl_yosys(top, src, files, work):
    """truth_tempo's two Yosys scripts (truth_tempo.run_yosys) on third-party RTL, read as a TT
    hardening flow reads it: FLOW_DEFINES, implicit wires allowed, $readmem paths relative to the
    source directory. Hand-instantiated combinational library cells (delay/buffer cells; C5 already
    excludes hand-instantiated flops and latches) get their functions from the Liberty file, read
    after the sources with -nooverwrite so a design's own stub of a library cell wins."""
    from . import truth_tempo as tt
    cells = any(_CELL_INST.search(_COMMENTS.sub("", open(f, errors="replace").read())) for f in files)
    lib = f"\nread_liberty -nooverwrite -ignore_miss_func {tt._q(SKY_LIB)}" if cells else ""
    p, scripts, ver, _files, _defines = tt.run_yosys(work, top=top, files=files, defines=FLOW_DEFINES, incdir=src,
                                                     extra_read=lib, cwd=src, fsm_defer=not cells,
                                                     fsm_noautowire=False)
    return p, scripts, ver


class Sky130Sim:
    """The gate-level netlist as a truth_tempo.Circuit (sky130 HD Liberty functions, flops cut): the
    interface truth_tempo.map_netlist/prove_mapping expect (c, flops {inst: (q net, next-state net)},
    flop_type {inst: clock edge and async-control nets}, sram). Q_N outputs are NOT(Q); enable/scan
    flops get their Liberty next_state as a gate."""

    def __init__(self, gn, name_of):
        from . import truth_tempo as tt
        lib, seq = tt._liberty(SKY_LIB), lib_seq()
        compiled = {}

        def comp(expr):
            if expr not in compiled:
                compiled[expr] = tt._compile(expr)
            return compiled[expr]

        self.c, self.flops, self.sram, self.latches, self.opaque = tt.Circuit(), {}, {}, [], []
        self.flop_type = {}
        consts = {"0": "$const0", "1": "$const1"}
        self.c.add(lambda M: 0, [], "$const0")
        self.c.add(lambda M: M, [], "$const1")

        def nm(b):
            return consts.get(b, "$constx") if isinstance(b, str) else name_of(b)

        for inst, (typ, con) in sorted(gn.cells.items()):
            s = seq.get(typ)
            if s and s[0] == "ff":
                _k, ns, iq, iqn = s
                q = nm(con["Q"]) if "Q" in con else f"{inst}$IQ"
                if ns == "D":
                    d = nm(con["D"])
                else:
                    fn, names = comp(ns)
                    d = f"{inst}$next"
                    self.c.add(fn, [q if n == iq else nm(con[n]) for n in names], d)
                if "Q_N" in con:
                    self.c.add(lambda M, a: M ^ a, [q], nm(con["Q_N"]))
                self.flops[inst] = (q, d)
                self.flop_type[inst] = tt.flop_controls(self.c, inst, lib[typ]["ff"],
                                                        lambda pin: nm(con[pin]) if pin in con else None, compiled)
                continue
            if s and s[0] == "latch" or (lib.get(typ, {}).get("seq")):
                (self.latches if s else self.opaque).append(inst)
                continue
            cm = lib.get(typ)
            if cm is None:
                raise ValueError(f"no Liberty cell {typ}")
            for pin, fexpr in cm["out"].items():
                if pin in con:
                    fn, names = comp(fexpr)
                    self.c.add(fn, [nm(con[n]) for n in names], nm(con[pin]))
        for q, d in self.flops.values():
            self.c.net(q)
            self.c.net(d)
        self.c.order()


def bit_namer(gn, word):
    """One canonical name per netlist bit: the port name for port bits (map_netlist looks inputs and
    outputs up by port name); otherwise the public name that resolves to an RTL flop bit in wl.json,
    else any public name, else the Yosys bit id."""
    from . import truth_tempo as tt
    cache = {}

    def score(n):
        full, split = tt._split(n)
        for base, idx in ([split] if split else []) + [(full, None)]:
            b = word.byname.get((base, idx))
            if b is not None and b in word.ffbit:
                return 0
            if b is not None:
                return 1
        return 3 if is_generated(n) else 2

    def name_of(b):
        if b in cache:
            return cache[b]
        if b in gn.port_name:
            n = gn.port_name[b]
        else:
            cands = sorted(gn.names.get(b, []), key=lambda n: (score(n), n.count("."), n))
            n = cands[0] if cands else f"$bit{b}"
        cache[b] = n
        return n

    return name_of


def _scopes(wl_path, top):
    m = json.load(open(wl_path))["modules"][top]
    return {n.lstrip("\\"): c["attributes"].get("module_hdlname") or c["attributes"].get("module")
            for n, c in m["cells"].items() if c["type"] == "$scopeinfo"}


def module_def(name, scopes, top):
    parts = name.split(".")
    for k in range(len(parts) - 1, 0, -1):
        s = ".".join(parts[:k])
        if s in scopes and scopes[s]:
            return scopes[s]
    return top


def v2_params(kind, det, width):
    """PARAMS values the automatic classifier states; everything else null (unknown)."""
    from .schema import PARAMS
    p = {k: None for k in PARAMS.get(kind, ())}
    d = det.get(kind) or {}
    if kind == "counter":
        p["direction"] = d.get("direction")
        p["step"] = d.get("step") if isinstance(d.get("step"), int) else None
        p["modulus"] = d.get("modulus")
    elif kind == "shift_register" and d.get("shift"):
        s = abs(d["shift"])
        p["lanes"] = s
        p["depth"] = width // s if width % s == 0 else None
        p["direction"] = d.get("direction")
        p["serial_in"] = d.get("serial_in") or None
    elif kind == "synchronizer":
        p["stages"] = max(d.get("stages") or [0]) or None
    return p


def pilot(rec, npat=1 << 12, seed=20260921, prove=True):
    """The label pipeline on one excluded design: extraction + join, RTL classification with
    truth_tempo's rules (no manual overrides; alt_kinds only from those rules, e.g. the 1-bit
    toggle rule), register-bit -> flop mapping by names checked by simulation and z3
    (truth_tempo.map_netlist / prove_mapping, under z3's deterministic rlimit), schema-v2 truth
    with truth_tempo's truth/2 rules: synthesis duplicates as bits[].shadow_flops, retimed flops
    as an `<owner>__retimed` register of kind other, primary = the widest register; lenient
    units only by truth_tempo.UNIT_RULES (truth_tempo.rule_units, the rules TEMPO's truth applies:
    synchronizer stage chains, equal-depth copy lanes under one copy condition, counters written
    by one concatenated adder), with a unit's synchronizer stage registers' params null."""
    import resource
    from . import schema
    from . import truth_tempo as tt
    sys.setrecursionlimit(100000)
    t_all = time.time()
    work = os.path.join(OUT, "pilot", "work", rec["id"].replace("/", "__"))
    ex, gn, name_map, res, tim, clean = extract_and_join(rec, work)
    back = {v: k for k, v in name_map.items()}
    t = time.time()
    src, files = fetch_rtl(rec, work)
    top = rec["rtl"]["top_module"]
    p, scripts, yver = run_rtl_yosys(top, src, files, work)
    tim["rtl_yosys"] = round(time.time() - t, 1)
    t = time.time()
    word = tt.Word(p["wl"], p["regs"], top=top, sources=files)
    fsm_enc = tt.load_fsm_encoding(p["enc"])
    cls = tt.Classifier(word, fsm_enc)
    regs = {}
    for name in word.regs:
        kind, det = cls.classify(name)
        regs[name] = {"kind": kind, "details": det, "width": len(word.regs[name]["bits"]),
                      "alt_kinds": det.pop("alt_kinds", []), "alt_reason": det.pop("alt_reason", None)}
    tim["classify"] = round(time.time() - t, 1)
    t = time.time()
    rtl = tt.RtlGates(p["gates"], top=top)
    nlsim = Sky130Sim(gn, bit_namer(gn, word))
    tim["load_models"] = round(time.time() - t, 1)
    t = time.time()
    flop_rel, key_rel, check, stats = tt.map_netlist(word, rtl, nlsim, None, fsm_enc, npat, seed, log)
    tim["simulate"] = round(time.time() - t, 1)
    proof, pstats = {}, {"skipped": True}
    if prove:
        t = time.time()
        proof, pstats = tt.prove_mapping(rtl, nlsim, flop_rel, key_rel, fsm_enc, log=log)
        tim["prove"] = round(time.time() - t, 1)
    # ---- schema v2
    scopes = _scopes(p["wl"], top)
    jk = lambda f: back.get(f)  # join key: the extracted instance name (master_x_y)
    key_flop = {}
    for f, r in flop_rel.items():
        if r[0] == "bit":
            key_flop.setdefault(r[1], f)
    dups = collections.defaultdict(list)
    for f, r in flop_rel.items():
        if r[0] == "dup":
            dups[r[1]].append(f)
    fsm_flops = collections.defaultdict(dict)
    for f, r in flop_rel.items():
        if r[0] == "fsm":
            fsm_flops[r[1]][r[2]] = f
    registers, notes = [], collections.Counter()
    for name in sorted(regs):
        r = regs[name]
        bits = []
        if name in fsm_enc:
            for k, f in sorted(fsm_flops[name].items()):
                bits.append({"index": k, "flop": jk(f), "rtl_bit": f"{name}=={fsm_enc[name].get(k)}",
                             "how": "fsm_onehot", "check": check.get(f), "proof": proof.get(f)})
        else:
            for idx, b in sorted(word.regs[name]["bits"].items()):
                key = (name, idx)
                e = {"index": idx, "flop": None, "rtl_bit": name if r["width"] == 1 else f"{name}[{idx}]"}
                if isinstance(b, str):
                    e["note"] = "constant in the RTL"
                elif b not in word.ffbit:
                    e["note"] = "not a flop in the word-level RTL"
                else:
                    owner = (word.reg_of[b] or [key])[0]
                    f = key_flop.get(key) or key_flop.get(owner)
                    kr = key_rel.get(key)
                    if f is None and kr and kr[0] == "merged":
                        f = kr[1]
                        e["how"] = "merged"
                    if f is not None:
                        e.update(flop=jk(f), check=check.get(f), proof=proof.get(f))
                        e.setdefault("how", flop_rel[f][2] if flop_rel[f][0] == "bit" else flop_rel[f][0])
                        if dups.get(f):  # synthesis copies: not part of the register's matched flops
                            e["shadow_flops"] = sorted(jk(g) for g in dups[f])
                    else:
                        e["note"] = {"constant": "next state constant (removed by synthesis)",
                                     "unobservable": "unobservable (removed by synthesis)"}.get(
                            (kr or ("none",))[0], "no flop found" if key in rtl.ff else "unused (removed)")
                notes[e.get("note", "mapped")] += 1
                bits.append(e)
        registers.append({"name": name, "width": r["width"], "kind": r["kind"], "alt_kinds": list(r["alt_kinds"]),
                          "alt_reason": r["alt_reason"], "module_def": module_def(name, scopes, top),
                          "params": v2_params(r["kind"], r["details"], r["width"]),
                          "rule": r["details"].get("rule"), "bits": bits})
    # retimed flops (a netlist flop holding a function of registers one cycle ahead): a register of
    # their own per owning register, kind other (schema.py, as truth_tempo does)
    retimed = collections.defaultdict(list)
    for f in sorted(nlsim.flops):
        r = flop_rel[f]
        if r[0] == "comb":
            fo = tt._ranges(rtl.support(r[1])[0])
            owners = sorted({re.sub(r"\[\d+(:\d+)?\]$", "", s) for s in fo} & set(regs))
            if owners:
                retimed["+".join(owners)].append((jk(f), r[2], fo, f))
    for owner, es in sorted(retimed.items()):
        rname = f"{owner}__retimed"
        registers.append({"name": rname, "width": len(es), "kind": "other", "alt_kinds": [],
                          "alt_reason": None, "module_def": module_def(owner.split("+")[0], scopes, top), "params": {},
                          "rule": "retimed: each flop holds a function of the owning register(s) one cycle ahead",
                          "bits": [{"index": i, "flop": k, "rtl_bit": holds if not holds.startswith("<") else
                                    f"{rname}[{i}]", "how": "retimed", "holds": f"{holds}, one cycle ahead",
                                    "function_of": fo, "check": check.get(f), "proof": proof.get(f)}
                                   for i, (k, holds, fo, f) in enumerate(sorted(es))]})
    registers.sort(key=lambda r: r["name"])
    prim = tt.flop_primaries(registers)
    width = {r["name"]: r["width"] or len(r["bits"]) for r in registers}
    flops_v2 = collections.defaultdict(lambda: {"registers": [], "primary": None})
    for r in registers:
        for b in r["bits"]:
            if b.get("flop") and r["name"] not in flops_v2[b["flop"]]["registers"]:
                flops_v2[b["flop"]]["registers"].append(r["name"])
    for f, v in flops_v2.items():
        v["registers"].sort(key=lambda n: (-width[n], n))
        v["primary"] = prim[f]
    shadow = sorted({d for r in registers for b in r["bits"] for d in b.get("shadow_flops", [])})
    unmapped = []  # the netlist flops that are neither a register bit nor a shadow flop
    for f in sorted(nlsim.flops):
        if jk(f) not in flops_v2 and jk(f) not in shadow:
            r = flop_rel[f]
            unmapped.append({"flop": jk(f), "reason": {"comb": f"retimed: holds {r[-1]} (no owning register)",
                                                       "unknown": r[-1]}.get(r[0], f"unused relation {r}"),
                             "netlist_instance": f})
    if set(shadow) & set(flops_v2) or len(flops_v2) + len(shadow) + len(unmapped) != len(nlsim.flops):
        raise RuntimeError("register bit flops, shadow flops and unmapped flops do not partition the netlist's flops")
    # lenient units by rule only (truth_tempo.UNIT_RULES, the rules TEMPO's truth applies too; no
    # hand-declared units): synchronizer stage chains, equal-depth copy lanes under one copy
    # condition (per-channel histories), counters written by one concatenated adder. TEMPO's
    # per-slice split units are not applied here (rule_units' per_slice; see its docstring)
    bit_flop = {(r["name"], b["index"]): b["flop"] for r in registers for b in r["bits"]
                if b.get("flop") and b.get("how") not in ("fsm_onehot", "retimed")}
    units, unit_report = tt.rule_units(cls, {n: regs[n]["kind"] for n in regs}, bit_flop.get,
                                       accepts=lambda n: {regs[n]["kind"]} | set(regs[n]["alt_kinds"] or []))
    for u in units:
        u.pop("_rtl", None)
    _added, no_primary = tt.add_alias_members(registers, units)
    # a synchronizer register that is one stage of a declared unit carries no stage-level params;
    # the unit does (schema.py, as truth_tempo does)
    stage_of = tt.mark_unit_stages(registers, units)
    for r in registers:
        if r["name"] in stage_of:
            r["params"] = {k: None for k in schema.PARAMS[r["kind"]]}
            r["stage_of"] = stage_of[r["name"]]
    ops = tt.operators(word, set(regs))
    kinds = collections.Counter(r["kind"] for r in registers)
    rtl_types = collections.Counter(f"{v['clock']}edge/{v['async'] or 'no async'}" for v in rtl.ff_type.values())
    truth = {"schema": schema.TRUTH_SCHEMA, "design": "tt:" + rec["id"], "registers": registers, "units": units,
             "flops": {k: flops_v2[k] for k in sorted(flops_v2)}, "unmapped_flops": unmapped, "operators": ops,
             "meta": {
                 "source": {k: rec[k] for k in ("id", "macro", "title", "author", "shuttle_repo", "shuttle_commit")},
                 "files": {k: {"url": v["url"], "git_blob": v["git_blob"]} for k, v in rec["files"].items()},
                 "rtl": {**{k: rec["rtl"][k] for k in ("repo", "commit", "top_module", "source_files")},
                         "defines": list(FLOW_DEFINES)},
                 "licence": rec["licence"],
                 "join_key": "extracted instance name <master minus sky130_fd_sc_hd__>_<x>_<y> (tools/retrace/"
                             "extract.py, DEF-style lower-left in DBU); netlist instance via GDS property 61",
                 "method": "RETRACE extraction of the published layout; join to the published gate-level netlist "
                           "by the layout's instance-name property (connectivity checked net by net); RTL at the "
                           "recorded commit classified by tools/s3/truth_tempo.py's word-level rules (no manual "
                           "overrides; alt_kinds only from those rules, e.g. the 1-bit toggle rule); register bits "
                           "mapped to netlist flops by Q-net names through wl.json aliases, confirmed by "
                           "truth_tempo.map_netlist (random simulation, flop clock edge and async control compared) "
                           "and prove_mapping (z3, deterministic rlimit); truth/2 rules as in truth_tempo.py "
                           "(shadow flops, <owner>__retimed registers of kind other, primary = the widest register); "
                           "lenient units by truth_tempo.UNIT_RULES only (meta.unit_rules), synchronizer stage "
                           "registers of a unit with stage-level params null",
                 "unit_rules": unit_report,
                 "alias_unit_members_added": _added,
                 "yosys": yver, "yosys_scripts": scripts, "rtl_flop_types": dict(sorted(rtl_types.items())),
                 "top_level_dynamic_arrays": sorted(k for k in word.dyn_arrays if "." not in k),
                 "undriven_rtl_outputs": stats["outputs_unspecified_in_rtl"],
                 "register_names_sharing_a_flop": sum(1 for keys in word.reg_of.values() if len(keys) > 1),
                 "registers_without_primary_flop": no_primary,
                 "join": res["join"],
                 "counts": {"registers": len(registers), "registers_by_kind": dict(sorted(kinds.items())),
                            "units": len(units),
                            "rtl_flop_bits": len(word.ffbit), "netlist_flops": len(nlsim.flops),
                            "netlist_flops_labelled": len(flops_v2), "shadow_flops": len(shadow),
                            "unmapped_flops": len(unmapped),
                            "rtl_bits": dict(sorted(notes.items())), "latches": len(nlsim.latches),
                            "opaque_sequential_cells": len(nlsim.opaque)},
                 "fsm_recoding": {"format": "{state register: {one-hot position (bits[].index): RTL state code}}",
                                  "registers": {k: {str(i): c for i, c in sorted(v.items())}
                                                for k, v in fsm_enc.items()}},
                 "removed_rtl_registers": word.removed_regs,
                 "functional_check": {k: v for k, v in stats.items() if k not in ("not_exercised",)},
                 "proof": {k: v for k, v in pstats.items()
                           if k not in ("z3", "seconds", "rlimit_max_per_check", "rlimit_total")},
                 "proof_incomplete": tt.proof_complete(pstats)}}
    bad = schema.check_truth(truth)
    tim["total"] = round(time.time() - t_all, 1)
    out_dir = os.path.join(OUT, "pilot")
    base = "truth_" + rec["id"].replace("/", "__")
    text = json.dumps(truth, indent=1) + "\n"
    with open(os.path.join(out_dir, base + ".json"), "w") as f:
        f.write(text)
    run = {"design": truth["design"], "truth_hash": schema.truth_hash(json.loads(text)), "check_truth": bad,
           "timings_s": tim, "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20),
           "yosys": yver, "z3": {k: pstats.get(k) for k in ("z3", "seconds", "rlimit_max_per_check", "rlimit_total")},
           "probe": res}
    with open(os.path.join(out_dir, base + ".run.json"), "w") as f:
        json.dump(run, f, indent=1)
    log(f"pilot {rec['id']}: {len(registers)} registers {dict(sorted(kinds.items()))}; {len(flops_v2)} of "
        f"{len(nlsim.flops)} flops labelled, {len(shadow)} shadow, {len(unmapped)} unmapped; units by rule: "
        f"{[u['name'] for u in units]}; proof: "
        f"{'; '.join(truth['meta']['proof_incomplete']) or 'complete'}; check_truth: {bad or 'clean'}; {tim}")
    return truth, run


def find_record(ident=None, role=None):
    doc = json.load(open(os.path.join(OUT, "candidates.json")))
    for r in doc["excluded"]:
        if (ident and r["id"] == ident) or (not ident and r["role"] == role):
            return r
    raise SystemExit(f"{ident or role}: not an excluded (pilot/probe) design; candidates are never inspected")



# ============================================================================ CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="register the candidate list (and choose the excluded pilot/probes)")
    s.add_argument("--per-stratum", type=int, default=6)
    s.add_argument("--probes", type=int, default=1, help="flow probes per shuttle (excluded from candidates)")
    s.add_argument("--index-commit")
    pr = sub.add_parser("probe", help="flow probes on the excluded probe designs (aggregate numbers only)")
    pr.add_argument("ids", nargs="*", help="excluded ids (default: every probe)")
    pl = sub.add_parser("pilot", help="the label pipeline on the excluded pilot design (or --all: the pilot and "
                                      "every flow probe; never a candidate)")
    pl.add_argument("id", nargs="?")
    pl.add_argument("--all", action="store_true", help="every excluded design (pilot and probes), one line each")
    pl.add_argument("--patterns", type=int, default=1 << 12)
    pl.add_argument("--no-prove", action="store_true")
    d = sub.add_parser("draw", help="after the freeze: draw the blind set")
    d.add_argument("--seed", required=True)
    d.add_argument("--n", type=int, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "scan":
        scan(per_stratum=a.per_stratum, index_commit=a.index_commit, n_probes=a.probes)
    elif a.cmd == "probe":
        doc = json.load(open(os.path.join(OUT, "candidates.json")))
        recs = [r for r in doc["excluded"] if (r["id"] in a.ids if a.ids else r["role"] == "probe")]
        rows = []
        for r in recs:
            try:
                rows.append(probe(r))
            except Exception as e:  # a probe reports failures, it does not stop
                rows.append({"id": r["id"], "error": f"{type(e).__name__}: {e}"[:600]})
            log(json.dumps(rows[-1])[:400])
        with open(os.path.join(OUT, "probes.json"), "w") as fh:
            json.dump(rows, fh, indent=1)
    elif a.cmd == "pilot" and a.all:
        doc = json.load(open(os.path.join(OUT, "candidates.json")))
        failed = 0
        for r in doc["excluded"]:  # the pilot and the flow probes only; candidates are never labelled here
            t0 = time.time()
            try:
                truth, _run = pilot(r, npat=a.patterns, prove=not a.no_prove)
                m = truth["meta"]
                line = (f"{len(truth['registers'])} registers, {len(truth['units'])} units by rule, "
                        f"{m['counts']['netlist_flops_labelled']} of "
                        f"{m['counts']['netlist_flops']} flops labelled, proof "
                        f"{'; '.join(m['proof_incomplete']) or 'complete'}")
                rc = 0
            except Exception as e:  # report and go on with the next design
                line, rc = f"{type(e).__name__}: {e}"[:600], 1
                failed += 1
            print(f"{r['id']} {rc} {time.time() - t0:.1f} {line}", flush=True)
        return 1 if failed else 0
    elif a.cmd == "pilot":
        pilot(find_record(a.id, "pilot"), npat=a.patterns, prove=not a.no_prove)
    elif a.cmd == "draw":
        print(json.dumps(draw(a.seed, a.n), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
