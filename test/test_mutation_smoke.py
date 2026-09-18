"""Fast subset of the mutation campaign (docs/spec/VERIFICATION.md section 2): a handful
of real mutants, asserted killed or equivalent, in well under 30 s total -- so the regular
pytest suite keeps a cheap regression net on the mutation harness itself, without running
the full ~130-mutant campaign (test/mutation/campaign.py, run separately, ~tens of
minutes).

Loads test/mutation/campaign.py directly by file path rather than importing
"test.mutation.campaign": this project's test/ has no top-level __init__.py (pytest's
own rootdir-relative collection does not need one), and the Python stdlib also ships a
`test` package that would otherwise shadow it on a plain `import test...`.
"""

import importlib.util
import os
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_campaign():
    spec = importlib.util.spec_from_file_location("retrace_mutation_campaign",
                                                    os.path.join(ROOT, "test/mutation/campaign.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


campaign = _load_campaign()

# A small, fixed slice of the real deterministic mutant list (same SEED as the full
# campaign, so these are exactly the campaign's own mutants #0 for each operator, not a
# separate hand-picked scenario): two real, unambiguous faults that must be killed, plus
# one with zero electrical effect that must be recognised as equivalent.
KILLED_IDS = ["warmup_via_delete_00", "warmup_cell_flip_00"]
EQUIVALENT_IDS = ["warmup_art_delete_00"]


def _mutant_by_id(mutants, mid):
    return next(m for m in mutants if m["id"] == mid)


@pytest.fixture(scope="module")
def smoke_results():
    mutants, _ = campaign.build_mutants()
    wanted = KILLED_IDS + EQUIVALENT_IDS
    t0 = time.time()
    results = {mid: campaign.run_mutant(_mutant_by_id(mutants, mid)) for mid in wanted}
    results["_seconds"] = time.time() - t0
    return results


def test_smoke_campaign_is_fast(smoke_results):
    assert smoke_results["_seconds"] < 30, smoke_results["_seconds"]


@pytest.mark.parametrize("mid", KILLED_IDS)
def test_killed_mutants_are_caught(smoke_results, mid):
    r = smoke_results[mid]
    assert r["error"] is None, r["error"]
    assert r["classification"] == "killed", (r["classification"], r["layers"])
    failed = [name for name, res in r["layers"].items() if not res["pass"]]
    assert failed, "classified killed but no layer actually failed"


@pytest.mark.parametrize("mid", EQUIVALENT_IDS)
def test_equivalent_mutant_is_recognised(smoke_results, mid):
    r = smoke_results[mid]
    assert r["error"] is None, r["error"]
    assert r["classification"] == "equivalent", (r["classification"], r["layers"])
    assert all(res["pass"] for res in r["layers"].values()), r["layers"]
