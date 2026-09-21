#!/usr/bin/env bash
# S4 round trip: harden the recovered puzzle RTL (rtl_recovered/) with LibreLane.
#
#   tools/roundtrip/puzzle/harden.sh [VARIANT...] [-- EXTRA_LIBRELANE_ARGS...]
#
# VARIANT (default: upstreamlike clean) is one of
#   upstreamlike  config.json as inferred for Jane Street's flow (no fill).  Magic
#                 DRC, KLayout DRC and LVS fail by construction without fill, so
#                 their checkers are demoted to warnings (ERROR_ON_*=false): they
#                 still run and record every count and report, and the run exits
#                 0 if nothing else fails.
#   clean         config.json with fill insertion on and every checker at its
#                 LibreLane default, so exit 0 means DRC/LVS/XOR-clean.
# Each run lands in out/roundtrip/puzzle_run/<variant>/ (overwritten) and is
# summarised to out/roundtrip/puzzle_run/<variant>.summary.json.  Environment:
# as for tools/roundtrip/run.sh (LIBRELANE, PDK_ROOT, LIBRELANE_DOCKER), plus
# PYTHON for the summary (default .venv/bin/python, else python3).
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
variants=()
while [[ $# -gt 0 && "$1" != "--" ]]; do variants+=("$1"); shift; done
[[ $# -gt 0 ]] && shift
[[ ${#variants[@]} -gt 0 ]] || variants=(upstreamlike clean)
python="${PYTHON:-}"
if [[ -z "$python" ]]; then
    if [[ -x "$repo/.venv/bin/python" ]]; then python="$repo/.venv/bin/python"; else python=python3; fi
fi

worst=0
for v in "${variants[@]}"; do
    case "$v" in
        upstreamlike)
            over=(-c ERROR_ON_MAGIC_DRC=false -c ERROR_ON_KLAYOUT_DRC=false -c ERROR_ON_LVS_ERROR=false) ;;
        clean)
            over=(-c RUN_FILL_INSERTION=true) ;;
        *) echo "harden.sh: unknown variant '$v'" >&2; exit 2 ;;
    esac
    "$here/../run.sh" "$here/config.json" "$v" -- "${over[@]}" "$@"
    status=$?
    echo "harden.sh: $v exited $status" >&2
    [[ $status -gt $worst ]] && worst=$status
    run_dir="$repo/out/roundtrip/puzzle_run/$v"
    if [[ -f "$run_dir/final/metrics.json" ]]; then
        "$python" "$here/summarize.py" "$run_dir" --json "$run_dir.summary.json" || worst=1
    fi
done
exit "$worst"
