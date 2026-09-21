#!/usr/bin/env bash
# RETRACE S4 round trip: run one LibreLane (Classic flow) hardening.
#
#   tools/roundtrip/run.sh CONFIG TAG [RUN_ROOT] [-- EXTRA_LIBRELANE_ARGS...]
#
#   CONFIG    a LibreLane config, e.g. tools/roundtrip/puzzle/config.json
#   TAG       run tag; the run lands in RUN_ROOT/TAG (overwritten if present)
#   RUN_ROOT  default out/roundtrip/<design>_run, where <design> is the name of
#             the config's directory (tools/roundtrip/puzzle -> puzzle_run)
#   after --  passed to LibreLane verbatim, e.g. -c KEY=VALUE or --to STEP
#
# Environment (all optional):
#   LIBRELANE        LibreLane launcher; default: `librelane` on PATH, else
#                    ~/ttsetup/librelane-venv/bin/librelane
#   PDK_ROOT         ciel PDK root holding open_pdks 8afc8346; default ~/pdk-sky130
#   LIBRELANE_DOCKER 1 (default) runs the flow in ghcr.io/librelane/librelane:<version>
#                    via --dockerized; 0 runs the tools from the host (e.g. under nix)
#
# One-time setup (any host with Docker and Python >= 3.10):
#   python3 -m venv VENV && VENV/bin/pip install librelane==3.0.14
#   VENV/bin/ciel enable --pdk-root "$PDK_ROOT" --pdk-family sky130 \
#       8afc8346a57fe1ab7934ba5a6056ea8b43078e71
#
# The flow runs in the LibreLane image matching the launcher's version (3.0.14
# here).  The container sees $HOME, the PDK root and the current directory;
# RUN_ROOT and the config's directory are mounted too when they lie elsewhere.
# A failing DRC/LVS/XOR/timing checker does not stop the Classic flow: it is a
# deferred error, so every step still runs, final/ is written, and LibreLane
# exits 2 at the end (ERROR_ON_*=false turns such a checker into a warning).
# Lint, unmapped-cell, synth-check and disconnected-pin checkers stop at once.
# This script passes LibreLane's exit status on, after writing TAG.status
# (exit code, wall time, command) next to the run directory.  Sign-off results are in RUN_ROOT/TAG/final/metrics.json
# and the per-step reports; tools/roundtrip/puzzle/summarize.py collects them.
set -euo pipefail

usage() { sed -n '2,12p' "$0" >&2; exit 2; }
[[ $# -ge 2 ]] || usage
cfg_arg="$1"; tag="$2"; shift 2
run_root=""
if [[ $# -gt 0 && "$1" != "--" ]]; then run_root="$1"; shift; fi
if [[ $# -gt 0 ]]; then [[ "$1" == "--" ]] || usage; shift; fi
extra=("$@")
case "$tag" in ""|.|..|*/*) echo "run.sh: bad tag '$tag'" >&2; exit 2 ;; esac

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ -f "$cfg_arg" ]] || { echo "run.sh: no such config: $cfg_arg" >&2; exit 2; }
cfg="$(cd "$(dirname "$cfg_arg")" && pwd)/$(basename "$cfg_arg")"
design="$(basename "$(dirname "$cfg")")"
run_root="${run_root:-$repo/out/roundtrip/${design}_run}"
mkdir -p "$run_root"
run_root="$(cd "$run_root" && pwd)"
run_dir="$run_root/$tag"

if [[ -n "${LIBRELANE:-}" ]]; then
    librelane="$LIBRELANE"
elif command -v librelane >/dev/null 2>&1; then
    librelane="$(command -v librelane)"
elif [[ -x "$HOME/ttsetup/librelane-venv/bin/librelane" ]]; then
    librelane="$HOME/ttsetup/librelane-venv/bin/librelane"
else
    echo "run.sh: no LibreLane found (set LIBRELANE or put librelane on PATH)" >&2
    exit 2
fi
pdk_root="${PDK_ROOT:-$HOME/pdk-sky130}"
[[ -d "$pdk_root" ]] || { echo "run.sh: PDK root $pdk_root does not exist" >&2; exit 2; }
pdk_root="$(cd "$pdk_root" && pwd)"
# --pdk-root and --dockerized are both eager CLI options, handled in command
# line order; the container launcher decides what to mount from PDK_ROOT (or
# ~/.ciel) before it ever sees a later --pdk-root, so export it as well.
export PDK_ROOT="$pdk_root"

launch=("$librelane")
if [[ "${LIBRELANE_DOCKER:-1}" != 0 ]]; then
    launch+=(--docker-no-tty)
    for d in "$run_root" "$(dirname "$cfg")"; do
        case "$d/" in "$HOME"/*|"$repo"/*) ;; *) launch+=(--docker-mount "$d") ;; esac
    done
    launch+=(--dockerized)
fi
# --force-run-dir is a hidden LibreLane debug flag: it puts the run where we
# want it instead of <config dir>/runs/<tag>.  It needs an existing directory.
launch+=(--pdk-root "$pdk_root" --run-tag "$tag" --force-run-dir "$run_dir")
launch+=(${extra[@]+"${extra[@]}"} "$cfg")

cd "$repo"
rm -rf "$run_dir"
mkdir -p "$run_dir"
echo "run.sh: $(${launch[0]} --bare-version 2>/dev/null || echo '?') -> $run_dir" >&2
start=$(date +%s)
set +e
"${launch[@]}"
status=$?
set -e
end=$(date +%s)
{
    echo "exit_status=$status"
    echo "wall_time_s=$((end - start))"
    echo "started=$(date -u -r "$start" +%FT%TZ 2>/dev/null || date -u -d "@$start" +%FT%TZ)"
    echo "config=${cfg#"$repo"/}"
    printf 'command='; printf '%q ' "${launch[@]}"; echo
} >"$run_root/$tag.status"
exit "$status"
