#!/usr/bin/env bash
# S4 round trip: harden the upstream warm-up (adder_demo) with LibreLane.
#
#   tools/roundtrip/warmup/run.sh [config.json|config_upstreamlike.json] [tag]
#
# A thin wrapper around tools/roundtrip/run.sh (see there for LIBRELANE,
# PDK_ROOT and LIBRELANE_DOCKER).  The run lands in
# out/roundtrip/warmup_run/<tag>/ (git-ignored); an existing run of the same tag
# is overwritten.  Then compare with the upstream GDS:
#
#   .venv/bin/python tools/roundtrip/warmup/compare.py upstream/warmup/04_final.gds \
#       out/roundtrip/warmup_run/<tag>/final/gds/adder_demo.gds
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cfg="${1:-config.json}"
tag="${2:-$(basename "$cfg" .json)}"
exec "$here/../run.sh" "$here/$cfg" "$tag"
