#!/usr/bin/env bash
# RETRACE S4 round trip, end to end: harden rtl_recovered/ with LibreLane 3.0.14 and check
# the result with RETRACE's own tools. .github/workflows/roundtrip.yml runs this on a
# GitHub-hosted runner; it runs on a workstation too (macOS with Docker Desktop, Linux).
#
#   tools/roundtrip/ci.sh [--no-harden]
#
#   0 preflight  tools, PDK, pdk/ subset (copied from $PDK_ROOT if missing), upstream/;
#                versions recorded
#   1 harden     tools/roundtrip/puzzle/harden.sh VARIANT for each variant (LibreLane via
#                tools/roundtrip/run.sh, in the ghcr.io/librelane/librelane:3.0.14 image);
#                runs land in out/roundtrip/puzzle_run/<variant>/. --no-harden reuses them.
#   2 check      python -m tools.roundtrip.check on each variant (both stream-outs)
#   3 loop       python -m tools.roundtrip.loop on the main run
#   4 vs_puzzle  python -m tools.roundtrip.vs_puzzle on the main run (+ block figure)
#   5 pytest     test/test_roundtrip.py on the main run, every test enabled and required
#   6 identity   informational: sha256 of the synthesized netlist, DEF, nl.v, pnl.v and
#                the netlist extracted from the GDS, against the reference run made on
#                macOS aarch64 (2026-09-21); a difference is reported, not failed
# Then OUT/summary.md (markdown; the workflow appends it to the job summary).
#
# Environment (all optional):
#   RETRACE_ROUNDTRIP_VARIANTS  harden.sh variants, default "upstreamlike clean"; the
#                               main run is upstreamlike when listed, else the first
#   RETRACE_CI_OUT              reports and logs, default out/roundtrip/ci (overwritten)
#   PYTHON                      Python with RETRACE's dependencies; default .venv/bin/python,
#                               else python3
#   LIBRELANE, PDK_ROOT, LIBRELANE_DOCKER   as for tools/roundtrip/run.sh
# oss-cad-suite (Yosys, SymbiYosys, Icarus) must be in ~/ttsetup/oss-cad-suite/bin, where
# the RETRACE modules look for it.
#
# Exit status: 0 when steps 0-5 all passed, 1 otherwise (every step still runs when it
# can, so the reports are complete; the failing steps are listed at the end).
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
cd "$repo" || exit 2

harden=1
case "${1:-}" in
    "") ;;
    --no-harden) harden=0 ;;
    *) sed -n '2,20p' "$0" >&2; exit 2 ;;
esac

read -r -a variants <<<"${RETRACE_ROUNDTRIP_VARIANTS:-upstreamlike clean}"
main="${variants[0]}"
for v in "${variants[@]}"; do [[ "$v" == upstreamlike ]] && main=upstreamlike; done
runs="$repo/out/roundtrip/puzzle_run"
out="${RETRACE_CI_OUT:-}"
if [[ -z "$out" ]]; then
    out="$repo/out/roundtrip/ci"
    rm -rf "$out"  # the default location is ours to clear
fi
mkdir -p "$out"
out="$(cd "$out" && pwd)"
rm -rf "$out/check" "$out/loop"
python="${PYTHON:-}"
if [[ -z "$python" ]]; then
    if [[ -x "$repo/.venv/bin/python" ]]; then python="$repo/.venv/bin/python"; else python=python3; fi
fi
export PYTHON="$python"  # harden.sh runs summarize.py with it
export PDK_ROOT="${PDK_ROOT:-$HOME/pdk-sky130}"
eda="$HOME/ttsetup/oss-cad-suite/bin"
gha="${GITHUB_ACTIONS:-}"

printf 'step\tstatus\tseconds\trequired\n' >"$out/steps.tsv"
failed=()

# step NAME REQUIRED(1|0) CMD... : run CMD, log to OUT/NAME.log (and stdout), record status
step() {
    local name="$1" required="$2"
    shift 2
    [[ -n "$gha" ]] && echo "::group::$name"
    echo "== $name: $*"
    local t0 st
    t0=$(date +%s)
    "$@" 2>&1 | tee "$out/$name.log"
    st=${PIPESTATUS[0]}
    local dt=$(( $(date +%s) - t0 ))
    printf '%s\t%s\t%s\t%s\n' "$name" "$st" "$dt" "$required" >>"$out/steps.tsv"
    echo "== $name: exit $st, ${dt} s"
    [[ -n "$gha" ]] && echo "::endgroup::"
    if [[ $st -ne 0 && $required == 1 ]]; then
        failed+=("$name")
        [[ -n "$gha" ]] && echo "::error title=round trip::step $name failed (exit $st); log $out/$name.log"
    fi
    return 0
}

# ---- 0 preflight ----------------------------------------------------------------------
preflight() {
    local ok=0 librelane
    echo "host: $(uname -srm)"
    echo "repo: $(git rev-parse HEAD 2>/dev/null || echo '?') ($(git status --porcelain 2>/dev/null | wc -l | tr -d ' ') changed paths)"
    echo "python: $("$python" --version 2>&1) ($python)"
    "$python" - <<'EOF' || ok=1
import importlib.metadata as m
for p in ("gdstk", "klayout", "shapely", "networkx", "pytest", "z3-solver", "pillow", "numpy"):
    print(f"  {p} {m.version(p)}")
EOF
    if [[ -n "${LIBRELANE:-}" ]]; then librelane="$LIBRELANE"
    elif command -v librelane >/dev/null 2>&1; then librelane="$(command -v librelane)"
    else librelane="$HOME/ttsetup/librelane-venv/bin/librelane"; fi
    local v
    if [[ $harden == 1 ]]; then
        v="$("$librelane" --bare-version 2>/dev/null)" || { ok=1; v=MISSING; }
        echo "librelane: $v ($librelane)"
        if [[ "${LIBRELANE_DOCKER:-1}" != 0 ]]; then
            v="$(docker version --format '{{.Server.Version}} {{.Server.Os}}/{{.Server.Arch}}' 2>/dev/null)" \
                || { ok=1; v="NOT RUNNING"; }
            echo "docker: $v"
            v="$(docker image inspect --format '{{.Id}} {{.Architecture}}' ghcr.io/librelane/librelane:3.0.14 \
                2>/dev/null)" || v="not pulled yet (LibreLane pulls it)"
            echo "image: $v"
        fi
    fi
    v="$(head -1 "$PDK_ROOT/sky130A/SOURCES" 2>/dev/null)" || { ok=1; v="no sky130A"; }
    echo "PDK_ROOT: $PDK_ROOT: $v"
    for t in yosys sby iverilog vvp yosys-abc; do
        [[ -x "$eda/$t" ]] || { echo "missing $eda/$t"; ok=1; }
    done
    echo "yosys: $("$eda/yosys" -V 2>/dev/null)"
    echo "iverilog: $("$eda/iverilog" -V 2>/dev/null | head -1)"
    echo "upstream: $(git -C upstream rev-parse HEAD 2>/dev/null || echo 'not a git checkout')"
    for f in upstream/puzzle.gds upstream/example_inputs.vcd upstream/warmup/00_source.v \
             upstream/warmup/01_netlist.v answer/solution.vcd; do
        [[ -f "$f" ]] || { echo "missing $f"; ok=1; }
    done
    local sub=pdk/sky130_fd_sc_hd src="$PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd"
    if [[ ! -f "$sub/lef/sky130_fd_sc_hd.lef" && -d "$src" ]]; then
        echo "pdk/: copying lef lib verilog gds from $src (README, Reproduce)"
        mkdir -p "$sub"
        for d in lef lib verilog gds; do cp -rL "$src/$d" "$sub/" || ok=1; done
    fi
    for f in lef/sky130_fd_sc_hd.lef gds/sky130_fd_sc_hd.gds lib/sky130_fd_sc_hd__tt_025C_1v80.lib; do
        if cmp -s "$sub/$f" "$src/$f"; then echo "pdk/: $f = \$PDK_ROOT's"; else echo "pdk/: $f differs or missing"; ok=1; fi
    done
    return $ok
}
step preflight 1 preflight

# ---- 1 harden -------------------------------------------------------------------------
if [[ $harden == 1 ]]; then
    for v in "${variants[@]}"; do
        step "harden_$v" 1 "$here/puzzle/harden.sh" "$v"
    done
else
    for v in "${variants[@]}"; do
        [[ -f "$runs/$v.summary.json" ]] || step "summarize_$v" 1 "$python" "$here/puzzle/summarize.py" \
            "$runs/$v" --json "$runs/$v.summary.json"
    done
fi
for v in "${variants[@]}"; do
    [[ -f "$runs/$v.summary.json" ]] && cp "$runs/$v.summary.json" "$out/harden_$v.summary.json"
    [[ -f "$runs/$v.status" ]] && cp "$runs/$v.status" "$out/harden_$v.status"
done

# ---- 2-5 RETRACE on the result ------------------------------------------------------------
for v in "${variants[@]}"; do
    step "check_$v" 1 "$python" -m tools.roundtrip.check "$runs/$v" --work "$out/check/$v" --json "$out/check_$v.json"
done
step loop 1 "$python" -m tools.roundtrip.loop "$runs/$main" --work "$out/loop" --json "$out/loop.json"
step vs_puzzle 1 "$python" -m tools.roundtrip.vs_puzzle "$runs/$main" --json "$out/vs_puzzle.json" \
    --svg "$out/roundtrip_blocks.svg"
clean_run=none  # tells the test to skip the clean-run sign-off
for v in "${variants[@]}"; do [[ "$v" == clean ]] && clean_run="$runs/clean"; done
step pytest 1 env RETRACE_ROUNDTRIP_RUN="$runs/$main" RETRACE_ROUNDTRIP_CLEAN_RUN="$clean_run" \
    RETRACE_ROUNDTRIP_REQUIRE=1 "$python" -m pytest -q -rs -p no:cacheprovider test/test_roundtrip.py \
    --junitxml "$out/pytest.xml"

# ---- 6 identity with the reference run (informational) -------------------------------------
identity() {
    "$python" - "$runs" "$out" "${variants[@]}" <<'EOF'
import hashlib, json, pathlib, sys
runs, out, variants = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3:]
# macOS 26 aarch64, Docker Desktop, LibreLane 3.0.14 image (arm64), open_pdks 8afc8346,
# 2026-09-21; DEF, nl.v and pnl.v were byte-identical over repeated runs there
REF = {
    "upstreamlike": {"synthesis nl.v (Yosys header line dropped)": "09939ebaf1d5658cb04d152baa4a8061297741de10551deed8fc8a3e86146ee9",
                     "final DEF": "a2195c3b9871e0fb25f5e1928fb4a28d64fab93a5be2bf2511d3fd0b7f3cd928",
                     "final nl.v": "8f8659b8c946351805e3e0cd659f21c3c787e00b9bc19f58e7b4918ee68783b9",
                     "final pnl.v": "e05b90f7f08da7fc5dcdcdc4a1920126ca332c7b9025e827d9c69c75444b36d2",
                     "netlist extracted from the KLayout GDS": "60d924bb2f79fa6737f213b845d9ee7e5facf960aabd0a8167ec4722dcff8494"},
    "clean": {"synthesis nl.v (Yosys header line dropped)": "09939ebaf1d5658cb04d152baa4a8061297741de10551deed8fc8a3e86146ee9",
              "final DEF": "d0258313ae660de8080f5ced35bc4e2058af84675fde5a4d99fcd17c9d14edc5",
              "final nl.v": "a4714d0b6f7ea664439e2259cd4331a2d92e1fe409b13808520281691e3999ba",
              "final pnl.v": "ef0c6fd55494e69d654c6febd50e832ab982296cb33015832b0059ccc684ca45",
              "netlist extracted from the KLayout GDS": "60d924bb2f79fa6737f213b845d9ee7e5facf960aabd0a8167ec4722dcff8494"},
}
def sha(path, drop_header=False):
    if path is None or not path.exists():
        return None
    data = path.read_bytes()
    if drop_header:
        data = b"".join(l for l in data.splitlines(keepends=True) if not l.startswith(b"/* Generated by"))
    return hashlib.sha256(data).hexdigest()
def one(d, pattern):
    hits = sorted(d.glob(pattern))
    return hits[0] if len(hits) == 1 else None
rows = []
for v in variants:
    r = runs / v
    files = {"synthesis nl.v (Yosys header line dropped)": (one(r, "*-yosys-synthesis/*.nl.v"), True),
             "final DEF": (one(r / "final/def", "*.def"), False),
             "final nl.v": (one(r / "final/nl", "*.nl.v"), False),
             "final pnl.v": (one(r / "final/pnl", "*.pnl.v"), False),
             "netlist extracted from the KLayout GDS": (out / "check" / v / "klayout.v", False)}
    for what, (path, drop) in files.items():
        got, ref = sha(path, drop), REF.get(v, {}).get(what)
        rows.append({"variant": v, "file": what, "sha256": got, "reference": ref,
                     "same": None if ref is None or got is None else got == ref})
        print(f"{v:13s} {what:42s} {got and got[:16]}  ref {ref and ref[:16]}  "
              f"{'same' if rows[-1]['same'] else 'DIFFERENT' if rows[-1]['same'] is False else '-'}")
(out / "identity.json").write_text(json.dumps(rows, indent=1) + "\n")
sys.exit(3 if any(r["same"] is False for r in rows) else 0)
EOF
}
step identity 0 identity

# ---- summary -------------------------------------------------------------------------------
"$python" - "$out" "$runs" "$main" "${variants[@]}" >"$out/summary.md" <<'EOF'
import csv, json, pathlib, platform, re, subprocess, sys
out, runs, main, variants = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3], sys.argv[4:]
def load(p):
    try:
        return json.loads(pathlib.Path(p).read_text())
    except (OSError, ValueError):
        return None
def pf(ok):
    return "PASS" if ok else "**FAIL**"
w = print
sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
w(f"## RETRACE S4 round trip ({sha}, {platform.machine()})\n")
w("Hardens `rtl_recovered/` with LibreLane 3.0.14 (Classic, open_pdks 8afc8346) and checks the "
  "layout with RETRACE: its own oracles against the run's DEF and nl.v, the loop back to the RTL, "
  "and the comparison with Jane Street's `puzzle.gds`.\n")
w("| step | result | seconds |\n|---|---|---|")
steps = list(csv.DictReader(open(out / "steps.tsv"), delimiter="\t"))
for s in steps:
    res = "PASS" if s["status"] == "0" else ("**FAIL**" if s["required"] == "1" else "differs (informational)")
    w(f"| {s['step']} | {res} (exit {s['status']}) | {s['seconds']} |")
w("")
w("### Hardening (LibreLane sign-off)\n")
w("| variant | exit | wall s | logic / flops / clock / diodes / fill | Magic DRC | KLayout DRC | LVS errors "
  "| XOR | route DRC | antenna nets | setup WS worst (ns) |\n|---|---|---|---|---|---|---|---|---|---|---|")
for v in variants:
    s = load(out / f"harden_{v}.summary.json")
    if not s:
        w(f"| {v} | no summary | | | | | | | | | |")
        continue
    so, c, t = s["signoff"], s["histogram"]["count"], s["timing"]
    w(f"| {v} | {s['exit_status']} | {s['wall_time_s']} | {c['logic']} / {c['flop']} / {c['clock']} / {c['diode']} / "
      f"{c['fill']} | {so['magic_drc']} | {so['klayout_drc']} | {so['lvs_errors']} | {so['xor_difference']} | "
      f"{so['route_drc_errors']} | {so['antenna_final']['violating_nets']} | "
      f"{t['setup_ws_worst'] if t['setup_ws_worst'] is None else round(t['setup_ws_worst'], 3)} |")
w("\nupstreamlike has no fill, like the puzzle, so its Magic/KLayout DRC and LVS findings are the floating "
  "n-well islands fill removes (demoted to warnings); clean is the same layout with fill and every checker enforced.\n")
w("### RETRACE oracles on each GDS (`tools.roundtrip.check`)\n")
keys = ["X", "V1", "V2", "V3a", "V3b", "V4", "V5", "CC"]
w("| variant | GDS | " + " | ".join(keys) + " | XS |\n|---|---|" + "---|" * (len(keys) + 1))
notes = []
for v in variants:
    r = load(out / f"check_{v}.json")
    if not r:
        w(f"| {v} | no report |" + " |" * (len(keys) + 1))
        continue
    for g, x in r["gds"].items():
        cells = [pf(x.get(k, {}).get("pass")) if k in x else "-" for k in keys]
        w(f"| {v} | {g} | " + " | ".join(cells) + f" | {pf(r['XS']['pass']) if 'XS' in r else '-'} |")
    k = r["gds"].get("klayout", {})
    if "V1" in k:
        notes.append(f"{v} (KLayout GDS): {k['V1']['matched']}/{k['V1']['def_components']} placements, "
                     f"{k['V3a']['matched']}/{k['V3a']['golden_nets']} DEF nets, isomorphic to nl.v: "
                     f"{k['V3b']['isomorphic']}, {k['CC']['identical']}/{k['CC']['masters']} masters PDK-identical.")
w("")
for n in notes:
    w(f"- {n}")
w("")
w("### Loop back to the RTL (`tools.roundtrip.loop`)\n")
lp = load(out / "loop.json")
if lp:
    for name, ok in lp["checks"].items():
        w(f"- {pf(ok)} {name}")
    rs = lp.get("replay_solution", {})
    w(f"\nsolution.vcd on the extracted netlist: O = `{rs.get('message')}`, success from cycle "
      f"{rs.get('success_first_cycle')}; {lp.get('seconds_total')} s in all.\n")
else:
    w("no loop report\n")
w("### Against Jane Street's puzzle.gds (`tools.roundtrip.vs_puzzle`)\n")
vs = load(out / "vs_puzzle.json")
for line in (vs or {}).get("headline", ["no report"]):
    w(f"- {line}")
w("\n### Tests (`test/test_roundtrip.py`)\n")
try:
    tail = [l for l in (out / "pytest.log").read_text().splitlines() if l.strip()][-1]
except (OSError, IndexError):
    tail = "no pytest log"
w(f"`{tail}`\n")
w("### Same bytes as the macOS aarch64 reference run? (informational)\n")
ident = load(out / "identity.json") or []
w("| variant | file | this run | reference | same |\n|---|---|---|---|---|")
for r in ident:
    same = "yes" if r["same"] else ("**no**" if r["same"] is False else "-")
    w(f"| {r['variant']} | {r['file']} | `{(r['sha256'] or 'missing')[:16]}` | `{(r['reference'] or '-')[:16]}` | {same} |")
pre = (out / "preflight.log").read_text() if (out / "preflight.log").exists() else ""
w("\n<details><summary>tool versions (preflight)</summary>\n\n```\n" + pre.strip() + "\n```\n</details>")
EOF

printf '\nsummary: %s\n' "$out/summary.md"
cat "$out/steps.tsv"
if [[ ${#failed[@]} -gt 0 ]]; then
    echo "round trip: FAILED steps: ${failed[*]}" >&2
    exit 1
fi
echo "round trip: all steps passed"
