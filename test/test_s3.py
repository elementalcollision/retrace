"""S3 evaluation side (PRD S3, docs/S3_DESIGN.md section 4 as amended by the lead, 2026-09-21, and
by the scorer review of 2026-09-22): the scorer (tools/s3/score.py), proof verification
(tools/s3/verify.py), the harness and its sandbox (tools/s3/run.py), the freeze and the blind
ledger (tools/s3/freeze.py) and the anonymity rules for recognizer modules.

Fast. Tests that need out/s3/truth_<design>.json or the PDK skip cleanly when they are absent. The
puzzle's TRUTH is used by scorer-only tests (synthetic results scored against it); a failure of one
of them is reported without its details (they may name puzzle registers; set
RETRACE_S3_SHOW_PUZZLE=1 to see them, as the lead), and the static name check compares salted
hashes and never prints a truth name. Nothing here extracts the puzzle or runs recognizer code on it
or on any third-party design (those runs happen once, after the freeze). Harness tests use
synthetic netlists (sky130 cells, tools.s3.netlist's load_verilog). Slow, opt-in: the TEMPO
end-to-end run with the real recognizer (~8 min, the frozen snapshot) with
RETRACE_S3_SLOW=1; the TEMPO leakage test (a file-order arm and 5 permutations, ~8 min with 3 jobs)
with RETRACE_S3_SLOW=1 TOO (it used to need its own RETRACE_S3_LEAKAGE=1, which neither suite set,
so the design's permutation rule was never exercised automatically -- review[2] issue 7; set
RETRACE_S3_LEAKAGE=1 to run it without the rest of the slow suite, and RETRACE_S3_JOBS to pick how
many recognizer children run at once). tools/s3/freeze.py's `checklist` command runs it too.
Thresholds of the gaming tests are stated in each docstring.
"""

import ast
import collections
import functools
import hashlib
import hmac
import itertools
import json
import math
import os
import pickle
import random
import re
import shutil
import subprocess
import sys

import numpy as np
import pytest

from tools.s3 import freeze as F
from tools.s3 import run as R
from tools.s3 import schema
from tools.s3 import score as S
from tools.s3 import verify as V
from tools.s3.netlist import GateGraph, Library, load_verilog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# RETRACE_S3_TRUTH_<DESIGN> points a design at another truth file (e.g. a freshly generated one)
TRUTH = {d: os.environ.get(f"RETRACE_S3_TRUTH_{d.upper()}") or os.path.join(ROOT, "out", "s3", f"truth_{d}.json")
         for d in ("puzzle", "tempo")}
DESIGNS = sorted(TRUTH)


@functools.cache
def _truth(design):
    return S.load_truth(TRUTH[design], design, strict=False)[0]


def withhold_puzzle(fn):
    """For a test parametrized by `design`: when it fails on the puzzle's truth, report only that it
    failed (its assertion values may name puzzle registers, which must not reach recognizer
    authors). RETRACE_S3_SHOW_PUZZLE=1 shows the details."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        if k.get("design") != "puzzle" or os.environ.get("RETRACE_S3_SHOW_PUZZLE") == "1":
            return fn(*a, **k)
        try:
            return fn(*a, **k)
        except KeyboardInterrupt:
            raise
        except pytest.skip.Exception:   # a skip reason may state a puzzle fact too ("no synchronizers")
            pytest.skip(f"{fn.__name__}[puzzle] skipped (reason withheld)")
        except BaseException as e:
            raise AssertionError(f"{fn.__name__}[puzzle] failed ({type(e).__name__}); details withheld as they may "
                                 "name puzzle registers (RETRACE_S3_SHOW_PUZZLE=1 shows them)") from None
    return wrapper


def truth_or_skip(design):
    if not os.path.exists(TRUTH[design]):
        pytest.skip(f"{TRUTH[design]} absent")
    return _truth(design)


def result(structures=(), groups=()):
    return {"schema": schema.RESULT_SCHEMA, "structures": list(structures), "groups": [list(g) for g in groups],
            "meta": {}}


def struct(sid, kind, flops, order=None, params=None, proven=True):
    return {"id": sid, "kind": kind, "flops": list(flops), "order": order, "params": params or {},
            "control": {}, "proof": {"status": "proven" if proven else "not_attempted"}}


def all_verified(res):
    return [True] * len(res["structures"])


# ----------------------------------------------------------------------------------------------
# AMI / ARI: numpy implementation against references written from the formulas, and by hand


def mi_ref(a, b):
    n = len(a)
    ca, cb, cab = collections.Counter(a), collections.Counter(b), collections.Counter(zip(a, b))
    return sum(v / n * math.log(n * v / (ca[x] * cb[y])) for (x, y), v in cab.items())


def emi_ref(a, b):
    """E[MI] straight from Vinh, Epps and Bailey (2010) eq. 24a, looping over clusters, with
    math.comb for the hypergeometric probability (no log-factorials, no size merging)."""
    n = len(a)
    ra, rb = collections.Counter(a).values(), collections.Counter(b).values()
    e = 0.0
    for ai in ra:
        for bj in rb:
            for nij in range(max(1, ai + bj - n), min(ai, bj) + 1):
                p = math.comb(ai, nij) * math.comb(n - ai, bj - nij) / math.comb(n, bj)
                e += nij / n * math.log(n * nij / (ai * bj)) * p
    return e


def emi_enum(a, b):
    """E[MI] by brute force: the mean MI over every permutation of b's labels (the permutation
    model with fixed marginals, which is what the formula computes)."""
    tot = cnt = 0
    for perm in itertools.permutations(b):
        tot += mi_ref(a, perm)
        cnt += 1
    return tot / cnt


def h_ref(a):
    n = len(a)
    return -sum(v / n * math.log(v / n) for v in collections.Counter(a).values())


def ami_ref(a, b):
    mi, emi = mi_ref(a, b), emi_ref(a, b)
    return (mi - emi) / ((h_ref(a) + h_ref(b)) / 2 - emi)


def ari_ref(a, b):
    c2 = lambda x: x * (x - 1) / 2  # noqa: E731
    sij = sum(c2(v) for v in collections.Counter(zip(a, b)).values())
    sa = sum(c2(v) for v in collections.Counter(a).values())
    sb = sum(c2(v) for v in collections.Counter(b).values())
    e = sa * sb / c2(len(a))
    return (sij - e) / ((sa + sb) / 2 - e)


SMALL = [([0, 0, 1, 1], [0, 1, 0, 1]), ([0, 0, 0, 1, 1, 1], [0, 0, 1, 1, 2, 2]),
         ([0, 0, 1, 2, 2, 2, 3], [0, 1, 1, 1, 2, 2, 2]), ([0, 1, 2, 3, 4, 4], [0, 0, 0, 1, 1, 2]),
         ([0, 0, 0, 0, 1, 1, 1], [0, 0, 1, 1, 0, 2, 2])]


@pytest.mark.parametrize("a,b", SMALL)
def test_expected_mi_equals_enumeration(a, b):
    """The numpy E[MI] equals the mean MI over all N! relabellings (N <= 7), and the
    per-cluster reference formula."""
    n_ij, rows, cols, n = S.contingency(np.array(a), np.array(b))
    got = S.expected_mi(rows, cols, n)
    assert got == pytest.approx(emi_enum(a, b), abs=1e-12)
    assert got == pytest.approx(emi_ref(a, b), abs=1e-12)
    assert S.mutual_info(np.array(a), np.array(b)) == pytest.approx(mi_ref(a, b), abs=1e-12)


def test_ami_ari_against_reference_on_random_partitions():
    rng = random.Random(1)
    for _ in range(40):
        n = rng.randint(8, 80)
        a = [rng.randrange(rng.randint(2, 12)) for _ in range(n)]
        b = [rng.randrange(rng.randint(2, 20)) for _ in range(n)]
        if len(set(a)) < 2 or len(set(b)) < 2:
            continue
        got = S.partition_scores(np.array(a), np.array(b))
        assert got["ami"] == pytest.approx(ami_ref(a, b), abs=1e-9)
        assert got["ari"] == pytest.approx(ari_ref(a, b), abs=1e-12)


def test_ami_ari_by_hand():
    """Hand-computed values (natural logs):
    [0,0,1,1] vs [0,1,0,1]: MI 0; the 6 arrangements of b give MI ln2 twice and 0 four times, so
      E[MI] = ln2/3 and AMI = (0 - ln2/3) / (ln2 - ln2/3) = -1/2; pairs: sum C(n_ij,2) = 0,
      E = 2*2/6, max 2, ARI = (0 - 2/3) / (2 - 2/3) = -1/2.
    [0,0,1,1] vs singletons: E[MI] = MI = ln2, so AMI = 0; ARI = 0.
    [0,0,0,1,1,1] vs [0,0,1,1,2,2]: MI = 2/3 ln2; each (3,2) cell pair has n=1 with p 9/15 (log 1)
      and n=2 with p 3/15, so E[MI] = 6 * (1/3 ln2)(1/5) = 2/5 ln2; AMI = (4/15 ln2) /
      ((ln2+ln3)/2 - 2/5 ln2); ARI = (2 - 6*3/15) / (9/2 - 6*3/15) = 8/33."""
    ln2, ln3 = math.log(2), math.log(3)
    s = S.partition_scores(np.array([0, 0, 1, 1]), np.array([0, 1, 0, 1]))
    assert s["ami"] == pytest.approx(-0.5, abs=1e-12) and s["ari"] == pytest.approx(-0.5, abs=1e-12)
    assert s["expected_mi"] == pytest.approx(ln2 / 3, abs=1e-12)
    s = S.partition_scores(np.array([0, 0, 1, 1]), np.array([0, 1, 2, 3]))
    assert s["ami"] == pytest.approx(0.0, abs=1e-12) and s["ari"] == pytest.approx(0.0, abs=1e-12)
    s = S.partition_scores(np.array([0, 0, 0, 1, 1, 1]), np.array([0, 0, 1, 1, 2, 2]))
    assert s["mi"] == pytest.approx(2 / 3 * ln2, abs=1e-12)
    assert s["expected_mi"] == pytest.approx(0.4 * ln2, abs=1e-12)
    assert s["ami"] == pytest.approx((4 / 15 * ln2) / ((ln2 + ln3) / 2 - 0.4 * ln2), abs=1e-12)
    assert s["ari"] == pytest.approx(8 / 33, abs=1e-12)
    s = S.partition_scores(np.array([3, 3, 5, 5, 5]), np.array([1, 1, 0, 0, 0]))
    assert s["ami"] == 1.0 and s["ari"] == 1.0 and s["nmi"] == pytest.approx(1.0)


# ----------------------------------------------------------------------------------------------
# order: concordance over the truth's ordered pairs, coverage, chance


def _brute_chance(order, pos, reversible, part):
    """The chance score of one part by brute force: every within-lane permutation of every result
    lane (within) or every order of the result's lanes (across)."""
    flops = {f for lane in order for f in lane}
    rng = random.Random(0)
    if part == "within":
        perms = itertools.product(*[list(itertools.permutations(lane)) for lane in order])
        variants = [[list(p) for p in combo] for combo in perms]
    else:
        variants = [[order[i] for i in p] for p in itertools.permutations(range(len(order)))]
    vals = [S.order_counts(v, pos, flops, reversible, rng)[part]["score"] for v in variants]
    return sum(vals) / len(vals)


def test_order_chance_by_hand_and_by_enumeration():
    """By hand: one reversible 3-flop chain fully asserted has chance 7/9 (inversions 0..3 give
    max-share 1, 2/3, 2/3, 1 with weights 1,2,2,1); a 2-flop chain 1; without reversal 1/2. A
    4-flop index register split into result lanes [a,b],[c,d] asserts 2 of its 6 pairs: chance =
    (E[max(C, 2-C)] + 4/2) / 6 = (1.5 + 2) / 6. The exact chance (convolved Mahonian within lanes,
    enumerated lane orders across) equals brute force on mixed-lane cases, and the Monte Carlo
    path of the across chance agrees within 0.02."""
    rng = random.Random(0)
    chain = {"a": (0, 0), "b": (0, 1), "c": (0, 2), "d": (0, 3)}
    fl = set(chain)
    assert S.order_counts([["a", "b", "c"]], chain, {"a", "b", "c"}, True, rng)["within"]["chance"] == \
        pytest.approx(7 / 9)
    assert S.order_counts([["a", "b"]], chain, {"a", "b"}, True, rng)["within"]["chance"] == pytest.approx(1.0)
    assert S.order_counts([["a", "b", "c"]], chain, {"a", "b", "c"}, False, rng)["within"]["chance"] == 0.5
    two = S.order_counts([["a", "b"], ["c", "d"]], chain, fl, True, rng)["within"]
    assert two["coverage"] == pytest.approx(2 / 6) and two["chance"] == pytest.approx(3.5 / 6)
    # mixed cases: 2 truth lanes x 3 stages, result lanes cutting across them
    pos = {f"x{l}{s}": (l, s) for l in range(2) for s in range(3)}
    for order in ([["x00", "x10", "x01"], ["x11", "x02", "x12"]], [["x00", "x01"], ["x10", "x11"], ["x02", "x12"]],
                  [["x02", "x00", "x12", "x10"], ["x01", "x11"]]):
        got = S.order_counts(order, pos, set(pos), True, random.Random(0))
        for part in ("within", "across"):
            if got[part] and got[part]["asserted"]:
                assert got[part]["chance"] == pytest.approx(_brute_chance(order, pos, True, part), abs=1e-12), \
                    (order, part)
    eight = {f"z{l}{s}": (l, s) for l in range(8) for s in range(2)}
    lanes8 = [[f"z{l}0", f"z{l}1"] for l in range(8)]
    assert math.factorial(8) <= S.EXACT_ENUM_MAX   # 8 lanes: enumerated exactly
    ex8 = S.order_counts(lanes8, eight, set(eight), True, random.Random(0))["across"]["chance"]
    old = S.EXACT_ENUM_MAX
    S.EXACT_ENUM_MAX = 1   # force the Monte Carlo path
    try:
        mc8 = S.order_counts(lanes8, eight, set(eight), True, random.Random(0))["across"]["chance"]
    finally:
        S.EXACT_ENUM_MAX = old
    assert mc8 == pytest.approx(ex8, abs=0.02)


def _toy_truth(regs, units=(), unmapped=(), design="toy"):
    """regs: [(name, kind, [flops in index order], extra dict)]."""
    registers, flops = [], {}
    for name, kind, fl, extra in regs:
        r = {"name": name, "width": len(fl), "kind": kind, "alt_kinds": [], "alt_reason": None,
             "module_def": "m", "params": {}, "bits": [{"index": i, "flop": f, "rtl_bit": f"{name}[{i}]"}
                                                        for i, f in enumerate(fl)]}
        r.update(extra)
        registers.append(r)
        for f in fl:
            flops.setdefault(f, {"registers": [], "primary": name})["registers"].append(name)
    t = {"schema": schema.TRUTH_SCHEMA, "design": design, "registers": registers, "units": list(units),
         "flops": flops, "unmapped_flops": [{"flop": f, "reason": "test"} for f in unmapped], "meta": {}}
    assert schema.check_truth(t) == []
    return t


def _dreg_truth():
    fl = [f"d{i}" for i in range(32)]
    lanes = [[f"d{24 + j}", f"d{16 + j}", f"d{8 + j}", f"d{j}"] for j in range(8)]
    return _toy_truth([("dreg", "shift_register", fl, {"params": {"order": lanes, "lanes": 8, "depth": 4}}),
                       ("cnt", "counter", [f"c{i}" for i in range(4)], {})]), fl, lanes


def _row(rep, item):
    return [r for r in rep["order"]["per_register"] if r["item"] == item][0]


def test_order_multilane_shift_and_counter():
    """The truth's lanes ordered as in the RTL score 1.0 within lanes (48 pairs) and across lanes
    (112 pairs) with coverage 1; a counter listed MSB first scores 0 within (no reversal for
    counters, chance 1/2); the lane order reversed keeps 1.0 across (reversible kind)."""
    t, fl, lanes = _dreg_truth()
    rep = S.score(t, result([struct("s", "shift_register", fl, lanes),
                             struct("c", "counter", ["c3", "c2", "c1", "c0"], [["c3", "c2", "c1", "c0"]])]))
    r = _row(rep, "dreg")
    assert r["within"]["pairs"] == 48 and r["across"]["pairs"] == 112
    assert r["within"]["score"] == r["across"]["score"] == 1.0 and r["ordered"] and r["all_correct"]
    assert 0.5 < r["within"]["chance"] < 1.0 and r["within"]["kappa"] == 1.0
    c = _row(rep, "cnt")
    assert c["within"]["score"] == 0.0 and c["within"]["chance"] == 0.5 and c["within"]["kappa"] == -1.0
    rev = S.score(t, result([struct("s", "shift_register", fl, lanes[::-1])]))
    r = _row(rev, "dreg")
    assert r["across"]["score"] == 1.0 and r["across"]["concordant"] == 0 and r["within"]["score"] == 1.0


def test_gaming_order_lane_structure(tmp_path):
    """The review's order exploits, on an 8-lane x 4-stage shift register, now score as ties or
    worse and are never 'ordered' (coverage >= 0.5 in every part the truth orders):
    (a) every flop its own lane, listed lane-major: within coverage 0 and score 1/2;
    (b) transposed lanes (result lane = truth stage): coverage 0 within and across, both 1/2;
    (c) a random order cut into 16 lanes of 2: within coverage <= 0.25 and kappa <= 0.25;
    (d) no order at all: both parts 1/2 at coverage 0.
    A register with chance 1 (2 flops, reversible) never counts as 'all correct'."""
    t, fl, lanes = _dreg_truth()
    rng = random.Random(1)
    shuffled = rng.sample(fl, len(fl))
    cases = {"a": [[f] for lane in lanes for f in lane], "b": [list(x) for x in zip(*lanes)],
             "c": [shuffled[i:i + 2] for i in range(0, 32, 2)], "d": None}
    for name, order in cases.items():
        r = _row(S.score(t, result([struct("s", "shift_register", fl, order)])), "dreg")
        assert not r["ordered"] and not r["all_correct"], name
        assert r["within"]["coverage"] <= 0.25 and r["within"]["kappa"] <= 0.25, (name, r["within"])
        if name in ("a", "b", "d"):
            assert r["within"]["score"] == 0.5 and r["within"]["coverage"] == 0.0
        if name in ("b", "d"):
            assert r["across"]["score"] == 0.5 and r["across"]["coverage"] == 0.0
    t2 = _toy_truth([("sy", "synchronizer", ["p", "q"], {})])
    r = _row(S.score(t2, result([struct("s", "synchronizer", ["p", "q"], [["p", "q"]])])), "sy")
    assert r["within"]["chance"] == 1.0 and r["within"]["kappa"] is None and not r["all_correct"]
    summ = S.score(t2, result([struct("s", "synchronizer", ["p", "q"], [["p", "q"]])]))["order"]["summary"]
    assert summ["synchronizer"]["width<=2"]["chance_one"] == 1


@pytest.mark.parametrize("design", ["tempo"])
def test_gaming_order_on_tempo_dreg(design):
    """The same exploits on TEMPO's dreg (8 lanes x 4 stages, truth params.order): none is ordered."""
    T = S.Truth(truth_or_skip(design))
    d = "u_top.u_host.dreg"
    if d not in T.regs:
        pytest.skip("no dreg")
    lanes = T.regs[d]["params"]["order"]
    fl = [f for lane in lanes for f in lane]
    for order in ([[f] for lane in lanes for f in lane], [list(x) for x in zip(*lanes)]):
        r = _row(S.score(T.raw, result([struct("s", "shift_register", fl, order)])), d)
        assert not r["ordered"] and r["within"]["coverage"] == 0.0
    r = _row(S.score(T.raw, result([struct("s", "shift_register", fl, lanes)])), d)
    assert r["ordered"] and r["all_correct"]


def test_order_uses_the_truths_explicit_lanes_and_unit_orders():
    """A unit with its own order (a 2-lane, 3-stage synchronizer chain) is scored against it:
    within (stage order) and across (lane order) both 1.0; its stage count is a parameter."""
    t = _toy_truth([("s0", "synchronizer", ["a0", "a1", "a2"], {}), ("s1", "synchronizer", ["b0", "b1", "b2"], {})],
                   units=[{"name": "chain", "kind": "synchronizer", "registers": ["s0", "s1"], "reason": "one chain",
                           "flops": ["a0", "a1", "a2", "b0", "b1", "b2"],
                           "params": {"stages": 3, "order": [["a0", "a1", "a2"], ["b0", "b1", "b2"]]}}])
    good = S.score(t, result([struct("u", "synchronizer", ["a0", "a1", "a2", "b0", "b1", "b2"],
                                     [["a0", "a1", "a2"], ["b0", "b1", "b2"]], {"stages": 3})]))
    r = _row(good, "chain")
    assert r["reference"] == "lanes" and r["within"]["score"] == 1.0 and r["across"]["score"] == 1.0
    assert good["params"]["accuracy"] == 1.0 and good["params"]["compared"] == 1


def test_lanes_unordered_scores_within_lanes_only():
    """schema v2 params.lanes_unordered: the 8-lane dreg with its lanes listed in a scrambled order
    scores across-lane order below 1 without the flag; with it the across part is not scored (None,
    its 112 pairs counted as across_unscored_pairs, the row and the summary flag it), within stays
    1.0 over 48 pairs and "all" equals within. The flag is ignored on kinds that do not carry it
    (a counter), and it is not a scored parameter."""
    t, fl, lanes = _dreg_truth()
    scrambled = [lanes[i] for i in (3, 0, 6, 1, 7, 2, 5, 4)]
    plain = _row(S.score(t, result([struct("s", "shift_register", fl, scrambled)])), "dreg")
    assert plain["across"]["score"] < 1.0 and plain["across_unscored_pairs"] == 0 and not plain["lanes_unordered"]
    rep = S.score(t, result([struct("s", "shift_register", fl, scrambled, {"lanes_unordered": True, "lanes": 8,
                                                                              "depth": 4})]))
    r = _row(rep, "dreg")
    assert r["lanes_unordered"] and r["across"] is None and r["across_unscored_pairs"] == 112
    assert r["within"]["score"] == 1.0 and r["within"]["pairs"] == 48 and r["all"]["pairs"] == 48
    assert r["ordered"] and r["all_correct"]
    summ = rep["order"]["summary"]["shift_register"]["width>=3"]
    assert summ["lanes_unordered"] == 1 and summ["across_unscored_pairs"] == 112 and "across" not in summ
    assert rep["result"]["lanes_unordered"] == 1 and rep["headline"]["lanes_unordered"] == 1
    assert "shift_register.lanes_unordered" not in rep["params"]["per_param"]
    c = S.score(t, result([struct("c", "counter", ["c0", "c1", "c2", "c3"], [["c0", "c1", "c2", "c3"]],
                                  {"lanes_unordered": True})]))
    assert c["result"]["lanes_unordered"] == 0


def test_order_from_params_when_order_is_null():
    """schema v2: a counter may give its order as params.bit_order (and a shift as params.order)
    with "order" null, as the verifier reads it; the scorer then scores that order too."""
    t, fl, lanes = _dreg_truth()
    rep = S.score(t, result([struct("c", "counter", ["c0", "c1", "c2", "c3"], None,
                                    {"bit_order": ["c0", "c1", "c2", "c3"]}),
                             struct("s", "shift_register", fl, None, {"order": lanes})]))
    assert _row(rep, "cnt")["within"]["score"] == 1.0 and _row(rep, "cnt")["asserts_order"]
    assert _row(rep, "dreg")["across"]["score"] == 1.0 and _row(rep, "dreg")["within"]["score"] == 1.0


def test_lfsr_form_both_and_affine():
    """lfsr_crc.form (schema v2): 'both' matches fibonacci, galois and both, on either side;
    'affine' and 'parallel' match only themselves; a 'both' answer against a single-form truth is
    counted (form_both_answers) so hedging is visible."""
    eq = S.param_equal
    for tv, rv, want in (("galois", "both", True), ("fibonacci", "both", True), ("both", "galois", True),
                         ("both", "Fibonacci", True), ("both", "both", True), ("galois", "fibonacci", False),
                         ("affine", "affine", True), ("affine", "both", False), ("both", "affine", False),
                         ("galois", "affine", False), ("parallel", "parallel", True), ("parallel", "both", False),
                         ("galois", None, False)):
        assert eq("form", tv, rv) is want, (tv, rv)
    trin = 0b100101   # x^5 + x^2 + 1: a trinomial, whose Fibonacci and Galois readings coincide
    t = _toy_truth([("l0", "lfsr_crc", [f"a{i}" for i in range(5)], {"params": {"form": "galois", "poly": trin}}),
                    ("l1", "lfsr_crc", [f"b{i}" for i in range(5)], {"params": {"form": "fibonacci", "poly": trin}}),
                    ("l2", "lfsr_crc", [f"c{i}" for i in range(4)], {"params": {"form": "affine"}})])
    res = result([struct("x", "lfsr_crc", [f"a{i}" for i in range(5)], params={"form": "both", "poly": 0b100101}),
                  struct("y", "lfsr_crc", [f"b{i}" for i in range(5)], params={"form": "both", "poly": 0b101001}),
                  struct("z", "lfsr_crc", [f"c{i}" for i in range(4)], params={"form": "affine"})])
    p = S.score(t, res)["params"]
    assert p["per_param"]["lfsr_crc.form"]["correct"] == 3 and p["form_both_answers"] == 2
    assert p["per_param"]["lfsr_crc.poly"]["correct"] == 2   # the reciprocal polynomial matches too


def test_harness_outcomes_are_counted_per_kind():
    """With the harness's outcomes, the register level counts them per kind and 'unknown' (a solver
    limit) is reported apart; without them every structure is 'not checked'."""
    t = _toy_truth([("A", "counter", ["a0", "a1"], {}), ("B", "counter", ["b0", "b1"], {})])
    res = result([struct("s", "counter", ["a0", "a1"]), struct("u", "counter", ["b0", "b1"])])
    rep = S.score(t, res, verified=[True, False], outcomes=["verified", "unknown"])
    pk = rep["classes"]["all"]["registers"]["strict"]["per_kind"]["counter"]
    assert pk["outcomes"] == {"verified": 1, "unknown": 1} and pk["unknown"] == 1
    assert rep["headline"]["counter"]["unknown"] == 1 and rep["headline"]["unknown"] == 1
    assert rep["result"]["outcomes"] == {"verified": 1, "unknown": 1}
    bare = S.score(t, res)
    assert bare["result"]["outcomes"] == {"not checked": 2}


# ----------------------------------------------------------------------------------------------
# honesty: found beside verified, what the verified count is worth, certified vs transcribed params
# (the lead's decisions of 2026-09-23; score.py's `honesty` block and the params split)


def _verdict(sid, kind, verified=True, bucket=None, **kw):
    """A tools/s3/verify.py per-structure verdict, in the shape verify_result() emits."""
    vd = {"id": sid, "kind": kind, "scored": kind in schema.STRUCTURE_KINDS, "verified": verified,
          "bucket": bucket or ("verified" if verified else "refuted"),
          "cases": {"reset": kw.pop("reset_cases", 0), "load": kw.pop("load_cases", 0),
                    "when_down": False, "hold": kw.pop("hold", True)}}
    vd.update(kw)
    return vd


def _honesty_fixture():
    """Four counters and one lfsr: one plainly verified, one verified with a VACUOUS hold and an
    opaque load case that hides most of the state space, one verified with TRANSCRIBED params only,
    one refused on hold, and an lfsr whose polynomial the harness could not certify."""
    names = [("A", "counter", ["a0", "a1"]), ("B", "counter", ["b0", "b1"]), ("C", "counter", ["c0", "c1"]),
             ("D", "counter", ["d0", "d1"]), ("L", "lfsr_crc", ["l0", "l1", "l2"])]
    pars = {"counter": {"direction": "up", "step": 1, "modulus": 4, "load": False},
            "lfsr_crc": {"form": "galois", "poly": 0b1011, "k_steps": 1, "n_inputs": 0}}
    t = _toy_truth([(n, k, fl, {"params": dict(pars[k])}) for n, k, fl in names])
    res = result([struct(n.lower(), k, fl, params=dict(pars[k])) for n, k, fl in names])
    verdicts = [
        # A: nothing to qualify -- a live, non-vacuous hold and every declared param certified
        _verdict("a", "counter", live_bits=[0, 1], dead_bits=[],
                 params_checked=["direction", "modulus", "step"], params_unchecked=["load"]),
        # B: an EMPTY hold region that the VERIFIED cases empty by themselves, plus a load case that
        # hides 0.99 of the state space -- verified, but not the same evidence as A
        _verdict("b", "counter", load_cases=1, hold_vacuous=True, hold_vacuous_cover="verified",
                 load_hidden_share=0.99, live_bits=[0, 1], dead_bits=[],
                 params_checked=["direction", "step"], params_unchecked=["load", "modulus"],
                 params_notes={"modulus": "params.saturating carries the limit, so the template never reads it"}),
        # C: verified, but the harness pinned NO parameter at all: every compared param is transcribed
        _verdict("c", "counter", live_bits=[0, 1], dead_bits=[],
                 params_checked=[], params_unchecked=["direction", "load", "modulus", "step"]),
        # D: refused on hold -- found by the recognizer, never certified
        _verdict("d", "counter", verified=False, bucket="hold", hold=False),
        # L: verified with the polynomial TRANSCRIBED (the matrix is not a one-step companion)
        _verdict("l", "lfsr_crc", params_checked=[], params_unchecked=["form", "k_steps", "n_inputs", "poly"]),
    ]
    return t, res, verdicts


def test_honesty_reports_found_beside_verified_with_a_reason_for_every_unverified_structure():
    """Found and verified stand side by side per kind, and every unverified structure carries its
    verify.py REASON BUCKET (here "hold"), spelled out in `reasons`; the accepted hold-ceiling
    limitation is stated with it. All four counters are found, three are verified."""
    t, res, vds = _honesty_fixture()
    rep = S.score(t, res, verdicts=vds)
    hon = rep["honesty"]
    c = hon["per_kind"]["counter"]
    assert c["registers"] == 4 and c["structures"] == 4
    assert c["found_registers"] == 4 and c["found_recall"] == 1.0
    assert c["verified_found_registers"] == 3 and c["verified_found_recall"] == 0.75
    assert c["found_not_verified_registers"] == 1 and c["verified_not_found_registers"] == 0
    assert c["verified_structures"] == 3 and c["unverified_structures"] == 1
    assert c["unverified_reasons"] == {"hold": 1}
    assert hon["unverified_reasons"] == {"hold": 1} and rep["result"]["buckets"]["hold"] == 1
    assert "hold" in hon["reasons"] and "control.hold is required" in hon["reasons"]["hold"]
    assert hon["hold_ceiling"] == S.HOLD_CEILING_NOTE
    h = rep["headline"]
    assert h["counter"]["found_r"] == 1.0 and h["counter"]["verified_found_r"] == 0.75
    assert h["counter"]["unverified_structures"] == 1 and h["counter"]["found_not_verified_registers"] == 1
    assert h["unverified_by_reason"] == {"hold": 1}
    text = S.render(rep)
    assert "Honesty (found =" in text and "hold 1" in text and "LIMITATION:" in text


def test_honesty_qualifies_the_verified_count():
    """The verified count never stands alone: how many had a VACUOUS hold (and what emptied it),
    the mean and max load_hidden_share, how many carried dead bits or unchecked params, and how many
    kinds carry no per-bit liveness obligation at all."""
    t, res, vds = _honesty_fixture()
    v = S.score(t, res, verdicts=vds)["honesty"]["verified"]
    assert v["structures"] == 4 and v["with_a_verdict"] == 4
    assert v["vacuous_hold"] == 1 and v["vacuous_hold_cover"] == {"verified": 1}
    assert v["with_a_load_case"] == 1
    # only B names a load case, so the mean over "the verified set that hides anything" is 0.99 and
    # the mean over every verified structure is 0.99/4 (no load case hides nothing)
    assert v["load_hidden_share"] == {"n": 1, "mean": 0.99, "max": 0.99, "min": 0.99}
    assert v["load_hidden_share_over_all_verified"]["n"] == 4
    assert v["load_hidden_share_over_all_verified"]["mean"] == pytest.approx(0.99 / 4)
    assert v["load_hidden_share_over_all_verified"]["max"] == 0.99
    assert v["with_unchecked_params"] == 4 and v["with_only_certified_params"] == 0
    assert v["unchecked_param_names"]["load"] == 3 and v["unchecked_param_names"]["poly"] == 1
    assert v["certified_param_names"] == {"direction": 2, "step": 2, "modulus": 1}
    assert v["with_dead_bits"] == 0 and v["liveness_checked"] == 3
    assert v["without_a_liveness_obligation"] == 1     # the lfsr: only a counter has one
    assert v["lfsr_poly_certified"] == 0 and v["lfsr_structures"] == 1
    assert "saturating" in v["param_notes"]["modulus"]
    h = S.score(t, res, verdicts=vds)["headline"]
    assert h["verified_vacuous_hold"] == 1 and h["verified_with_unchecked_params"] == 4
    assert h["verified_with_dead_bits"] == 0 and h["verified_without_liveness"] == 1
    assert h["verified_load_hidden_share_mean"] == 0.99 and h["verified_load_hidden_share_max"] == 0.99
    assert h["verified_lfsr_poly_certified"] == 0
    text = S.render(S.score(t, res, verdicts=vds))
    assert "vacuous hold 1" in text and "load_hidden_share" in text and "dead bit" in text


def test_honesty_counts_a_dead_bit_and_a_structure_with_no_verdict():
    """A verified structure the harness reports dead bits for is counted as such, and a structure no
    verdict reached is bucketed "not checked" rather than read as a pass."""
    t = _toy_truth([("A", "counter", ["a0", "a1"], {}), ("B", "counter", ["b0", "b1"], {})])
    res = result([struct("s", "counter", ["a0", "a1"]), struct("u", "counter", ["b0", "b1"])])
    vds = [_verdict("s", "counter", live_bits=[1], dead_bits=[0], params_checked=[], params_unchecked=[]), None]
    rep = S.score(t, res, verdicts=vds)
    hon = rep["honesty"]
    assert hon["verified"]["structures"] == 1 and hon["verified"]["with_dead_bits"] == 1
    assert hon["verified"]["live_bits"] == 1 and hon["verified"]["hold_claimed"] == 1
    assert hon["verdicts"] == {"structures": 2, "with_a_verdict": 1,
                               "source": "tools/s3/verify.py per-structure verdicts"}
    assert rep["result"]["verdicts"] == 1 and rep["result"]["buckets"] == {"verified": 1, S.NOT_CHECKED: 1}
    assert hon["per_kind"]["counter"]["unverified_reasons"] == {S.NOT_CHECKED: 1}
    assert hon["per_kind"]["counter"]["verdicts_missing"] == 1
    assert hon["per_kind"]["counter"]["exact_recall"] == 1.0
    assert hon["per_kind"]["counter"]["verified_exact_recall"] == 0.5
    assert S.NOT_CHECKED in hon["reasons"]


def test_an_unscored_kind_structure_is_bucketed_not_silently_dropped():
    """A structure of a kind the harness never verifies (schema.KINDS outside STRUCTURE_KINDS) is
    counted under the "unscored kind" reason, not left out of the unverified tally: a report that
    says "15 of 225 verified" must be able to say what the other 210 were."""
    t = _toy_truth([("A", "counter", ["a0", "a1"], {}), ("D", "data_register", ["d0", "d1"], {})])
    res = result([struct("s", "counter", ["a0", "a1"]), struct("d", "data_register", ["d0", "d1"])])
    vds = [_verdict("s", "counter", params_checked=["step"], params_unchecked=[]),
           {"id": "d", "kind": "data_register", "scored": False, "verified": False, "bucket": "unscored kind"}]
    hon = S.score(t, res, verdicts=vds)["honesty"]
    assert hon["unscored_kind_structures"] == 1
    assert hon["unverified_reasons"] == {"unscored kind": 1}
    assert "never verified" in hon["reasons"]["unscored kind"]
    # and it belongs to no per-kind row, because it is not a structure kind
    assert all(not e["unverified_reasons"] for e in hon["per_kind"].values())
    text = S.render(S.score(t, res, verdicts=vds))
    assert "'unscored kind': 1" in text and "including 1 of unscored kinds" in text


def test_params_split_into_certified_and_transcribed():
    """A compared parameter counts as CERTIFIED only when the harness verified the matched structure
    AND named the parameter in params_checked; everything else is TRANSCRIBED. The combined number
    stays beside the split, never instead of it."""
    t, res, vds = _honesty_fixture()
    p = S.score(t, res, verdicts=vds)["params"]
    # 4 counters x 4 params + 1 lfsr x 4 params = 20 compared; certified: A direction/modulus/step
    # and B direction/step (C and D and L certify nothing)
    assert p["compared"] == 20 and p["correct"] == 20 and p["accuracy"] == 1.0
    assert p["certified"]["compared"] == 5 and p["certified"]["correct"] == 5
    assert p["transcribed"]["compared"] == 15 and p["transcribed"]["correct"] == 15
    assert p["certified"]["compared"] + p["transcribed"]["compared"] == p["compared"]
    assert p["certified"]["params"] == ["counter.direction", "counter.modulus", "counter.step"]
    assert "counter.load" in p["transcribed"]["params"] and "lfsr_crc.poly" in p["transcribed"]["params"]
    assert p["per_param"]["counter.direction"]["certified"]["compared"] == 2
    assert p["per_param"]["counter.load"]["certified"]["compared"] == 0
    assert p["per_param"]["counter.load"]["transcribed"]["compared"] == 4
    assert p["per_param"]["lfsr_crc.poly"]["certified"]["compared"] == 0
    assert p["certification_rule"] == S.PARAMS_CERTIFIED_RULE
    h = S.score(t, res, verdicts=vds)["headline"]
    assert h["params_certified_compared"] == 5 and h["params_certified_accuracy"] == 1.0
    assert h["params_transcribed_compared"] == 15 and h["params_transcribed_accuracy"] == 1.0
    assert "CERTIFIED   5/5" in S.render(S.score(t, res, verdicts=vds))


def test_a_transcribed_parameter_is_never_counted_as_certified_when_it_is_wrong():
    """The split is the point: a WRONG transcribed parameter drags only the transcribed accuracy
    down, and an unverified structure certifies nothing even when its verdict lists params_checked
    (verify.py fills that list last, but the scorer does not rely on that)."""
    t = _toy_truth([("A", "counter", ["a0", "a1"], {"params": {"step": 1, "modulus": 4}}),
                    ("B", "counter", ["b0", "b1"], {"params": {"step": 1, "modulus": 4}})])
    res = result([struct("s", "counter", ["a0", "a1"], params={"step": 1, "modulus": 9}),
                  struct("u", "counter", ["b0", "b1"], params={"step": 1, "modulus": 4})])
    vds = [_verdict("s", "counter", params_checked=["step"], params_unchecked=["modulus"]),
           _verdict("u", "counter", verified=False, bucket="refuted",
                    params_checked=["step", "modulus"], params_unchecked=[])]
    p = S.score(t, res, verdicts=vds)["params"]
    assert p["certified"] == {"compared": 1, "correct": 1, "accuracy": 1.0, "params": ["counter.step"]}
    assert p["transcribed"]["compared"] == 3 and p["transcribed"]["correct"] == 2
    assert p["transcribed"]["accuracy"] == pytest.approx(2 / 3)
    assert p["compared"] == 4 and p["correct"] == 3
    wrong = [w for w in p["wrong"] if w["param"] == "counter.modulus"]
    assert wrong and wrong[0]["certified"] is False


def test_without_verdicts_nothing_is_certified_and_nothing_is_verified():
    """A scoring run with no harness verdicts (score.py's own CLI: no netlist) certifies nothing:
    every compared parameter is transcribed, every structure is bucketed "not checked", and the
    honesty block says so instead of printing zeros that read as evidence."""
    t, res, _vds = _honesty_fixture()
    rep = S.score(t, res)
    hon = rep["honesty"]
    assert hon["verdicts"]["with_a_verdict"] == 0 and "no verdicts" in hon["verdicts"]["source"]
    assert hon["verified"]["structures"] == 0
    assert hon["unverified_reasons"] == {S.NOT_CHECKED: 5}
    assert rep["params"]["certified"]["compared"] == 0
    assert rep["params"]["transcribed"]["compared"] == rep["params"]["compared"] == 20
    assert "hold_ceiling" not in hon


def test_honesty_columns_read_the_real_verifier(tmp_path, monkeypatch):
    """End to end through run.evaluate() against tools/s3/verify.py itself, so the field names
    cannot drift: on the synthetic netlist the shift chain verifies with a VACUOUS hold (its `when`
    is empty, so the VERIFIED cases cover the space by themselves and no load case is what emptied
    it), the counter verifies with live bits, the MSB-first counter is refuted and the input-less
    synchronizer fails on its template -- and every one of those reaches the honesty block."""
    nl, key = synthetic(tmp_path)
    monkeypatch.setattr(R, "run_child", _fake_child(_syn_recognize))
    out = R.evaluate(nl, key, _syn_truth(), baseline=False)
    assert out["invalid_reasons"] == [], out["problems"]
    vds = {v["id"]: v for v in out["verify"]["structures"]}
    assert vds["sh"]["verified"] and vds["sh"]["hold_vacuous"] is True
    assert vds["sh"]["hold_vacuous_cover"] == "verified"      # not emptied by an opaque load case
    assert vds["cnt"]["verified"] and vds["cnt"]["dead_bits"] == []
    hon = out["score"]["honesty"]
    assert hon["verdicts"]["with_a_verdict"] == 4
    assert hon["verified"]["structures"] == 2 and hon["verified"]["vacuous_hold"] == 1
    assert hon["verified"]["vacuous_hold_cover"] == {"verified": 1}
    assert hon["verified"]["with_a_load_case"] == 0 and hon["verified"]["load_hidden_share"]["n"] == 0
    assert hon["verified"]["liveness_checked"] == 1 and hon["verified"]["without_a_liveness_obligation"] == 1
    assert hon["unverified_reasons"] == {"refuted": 1, "template": 1}
    assert set(hon["reasons"]) == {"refuted", "template"}
    assert hon["per_kind"]["counter"]["found_recall"] == 1.0
    assert hon["per_kind"]["counter"]["verified_found_recall"] == 1.0
    assert hon["per_kind"]["counter"]["unverified_reasons"] == {"refuted": 1}
    # the shift's lanes and depth are the only params the harness pinned here
    assert out["score"]["params"]["certified"]["params"] == ["shift_register.depth", "shift_register.lanes"]
    assert out["score"]["params"]["certified"]["compared"] == 2
    assert out["score"]["params"]["transcribed"]["compared"] == out["score"]["params"]["compared"] - 2
    assert "Honesty (found =" in out["text"]


def _verify_buckets():
    """Every bucket tools/s3/verify.py raises: the LAST argument of each `_Fail(...)` in its source,
    read with a balanced-paren scan so a reason string holding a comma cannot be mistaken for it."""
    src = open(os.path.join(ROOT, "tools", "s3", "verify.py")).read()
    out, i = set(), 0
    while (j := src.find("_Fail(", i)) >= 0:
        k, depth = j + 6, 1
        while depth and k < len(src):
            depth += {"(": 1, ")": -1}.get(src[k], 0)
            k += 1
        body, depth, last = src[j + 6:k - 1], 0, None
        for n, ch in enumerate(body):
            depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(ch, 0)
            if ch == "," and depth == 0:
                last = n
        arg = body[last + 1:].strip() if last is not None else ""
        for lit in re.findall(r'"([a-z][a-z -]*)"', arg):
            out.add(lit)
        i = k
    return out


def test_the_freeze_pins_the_honesty_rules():
    """score.class_map() is what tools/s3/freeze.py hashes, so the rules that decide what a published
    number may claim -- the certified / transcribed split, the reason bucket of every unverified
    structure, which kinds carry a liveness obligation, and the accepted hold ceiling -- are frozen
    with the code and cannot be relaxed after the freeze without breaking it."""
    cm = S.class_map()
    assert cm["params_certification"] == S.PARAMS_CERTIFIED_RULE
    assert cm["hold_ceiling"] == S.HOLD_CEILING_NOTE
    assert cm["liveness_kinds"] == ["counter"]
    assert "found and verified are separate columns" in cm["found_vs_verified"]
    # every bucket tools/s3/verify.py can raise, read off its own source (the last argument of each
    # _Fail), is spelled out here, so no structure is ever reported refused for a reason the frozen
    # specification does not name
    raised = _verify_buckets() | {"refuted", "unknown", "budget", "malformed", S.NOT_CHECKED}
    missing = sorted(b for b in raised if b and b not in cm["unverified_reasons"])
    assert not missing, missing
    for b in ("hold", "coverage", "unsupported clock", "unscored kind", "refuted", S.NOT_CHECKED):
        assert cm["unverified_reasons"].get(b), b
    assert F.canonical_hash(cm) == F.canonical_hash(S.class_map())


def test_designs_without_multi_flop_registers_score():
    """A truth whose registers all have one flop (the corpus's toggle designs) scores without a
    crash: the multi-flop grouping block is reported empty."""
    t = _toy_truth([("a", "counter", ["f0"], {}), ("b", "flag", ["f1"], {})])
    rep = S.score(t, result([struct("x", "counter", ["f0"])]))
    assert rep["grouping"]["multi_flop_registers"] == {"n": 0, "empty": True}
    assert rep["headline"]["counter"]["found_r"] == 1.0 and "no flops to group" in S.render(rep)


# ----------------------------------------------------------------------------------------------
# matching


def test_matching_found_exact_units_one_credit():
    """IoU > 0.5, one to one; exact next to found; a 2-flop register needs 2 flops; two structures
    cannot both take one register. D and E are per-stage synchronizer registers of the chain unit
    DE: strictly they are scored only through DE, so one structure over DE finds both, strict and
    lenient."""
    t = _toy_truth([("A", "counter", ["a0", "a1", "a2", "a3"], {}), ("B", "counter", ["b0", "b1", "b2", "b3"], {}),
                    ("D", "synchronizer", ["d0", "d1"], {}), ("E", "synchronizer", ["e0", "e1"], {}),
                    ("X", "counter", ["x0", "x1"], {}), ("C", "flag", ["c0"], {})],
                   units=[{"name": "DE", "kind": "synchronizer", "registers": ["D", "E"], "reason": "one chain"}])
    rep = S.score(t, result([
        struct("s1", "counter", ["a0", "a1", "a2", "a3"]),            # A exact
        struct("s1b", "counter", ["a1", "a2", "a3"]),                 # A again: no second credit
        struct("s2", "counter", ["b0", "b1", "b2"]),                  # B found, not exact
        struct("s3", "synchronizer", ["d0", "d1", "e0", "e1"]),       # the chain DE
        struct("s4", "counter", ["x0"]),                              # 1 of 2 flops: not found
        struct("s5", "shift_register", ["c0"])]))                     # a flag: false positive
    st = rep["classes"]["all"]["registers"]["strict"]["per_kind"]
    le = rep["classes"]["all"]["registers"]["lenient"]["per_kind"]
    assert st["counter"]["found"]["registers_found"] == 2 and st["counter"]["exact"]["registers_found"] == 1
    assert st["counter"]["found"]["precision"] == pytest.approx(2 / 4)
    assert st["counter"]["found"]["recall"] == pytest.approx(2 / 3)
    assert st["synchronizer"]["found"]["recall"] == 1.0 and st["synchronizer"]["exact"]["recall"] == 1.0
    assert le["synchronizer"]["found"]["recall"] == 1.0 and le["synchronizer"]["found"]["precision"] == 1.0
    assert st["shift_register"]["found"]["precision"] == 0.0 and st["shift_register"]["registers"] == 0
    assert rep["classes"]["all"]["registers"]["lenient"]["unit_matches"] == ["DE"]
    assert st["counter"]["found_iou75"]["registers_found"] == 2 and st["counter"]["mean_iou_found"] == \
        pytest.approx((1 + 0.75) / 2)
    assert rep["headline"]["micro_f1_registers"] is not None


def test_unit_match_credits_only_members_it_holds():
    """A unit match credits a member only when the structure holds more than half of the member's
    flops (the review's TEMPO case: ui_sync0 + 1 of 8 ui_sync1 flops + uio_sync0, IoU 17/32 with
    the 4-register unit, used to credit all 4 registers; now 2). Bit-level unit acceptance follows
    the credited members."""
    regs = [(n, "synchronizer", [f"{n}{i}" for i in range(8)], {}) for n in ("u0", "u1", "v0", "v1")]
    t = _toy_truth(regs, units=[{"name": "all4", "kind": "synchronizer", "registers": ["u0", "u1", "v0", "v1"],
                                 "reason": "one block"}])
    fl = [f"u0{i}" for i in range(8)] + ["u10"] + [f"v0{i}" for i in range(8)]
    rep = S.score(t, result([struct("s", "synchronizer", fl)]))
    le = rep["classes"]["all"]["registers"]["lenient"]["per_kind"]["synchronizer"]
    st = rep["classes"]["all"]["registers"]["strict"]["per_kind"]["synchronizer"]
    assert le["found"]["registers_found"] == 2 and st["found"]["registers_found"] == 2
    assert sorted(le["found_registers"]) == ["u0", "v0"]


@pytest.mark.parametrize("design", ["tempo"])
def test_unit_member_credit_on_tempo(design):
    """On TEMPO: the review's 17-flop structure (ui_sync0 + 1 of 8 ui_sync1 flops + uio_sync0)
    no longer credits ui_sync1 or uio_sync1; every register it credits has more than half of its
    flops in the structure (ui_sync0, uio_sync0 and the 1-flop RTL aliases of ui_sync0's bits)."""
    T = S.Truth(truth_or_skip(design))
    names = ["u_top.u_tio.ui_sync0", "u_top.u_tio.ui_sync1", "u_top.u_tio.uio_sync0", "u_top.u_tio.uio_sync1"]
    if not all(n in T.regs for n in names):
        pytest.skip("TEMPO synchronizer registers renamed")
    fl = sorted(T.flops[names[0]]) + sorted(T.flops[names[1]])[:1] + sorted(T.flops[names[2]])
    rep = S.score(T.raw, result([struct("s", "synchronizer", fl)]))
    for mode in ("strict", "lenient"):
        got = rep["classes"]["all"]["registers"][mode]["per_kind"]["synchronizer"]["found_registers"]
        assert names[0] in got and names[2] in got and names[1] not in got and names[3] not in got, got
        assert all(2 * len(T.flops[n] & set(fl)) > len(T.flops[n]) for n in got), got


def test_strict_synchronizers_are_scored_by_chain():
    """Per-stage synchronizer registers score strictly through their chain units: every flop its
    own synchronizer structure finds nothing (the review measured 6/11 on TEMPO before), while one
    structure per chain finds every register of the chain."""
    regs = [("m0", "synchronizer", ["m0"], {}), ("m1", "synchronizer", ["m1"], {}),
            ("w0", "synchronizer", [f"w0_{i}" for i in range(4)], {}),
            ("w1", "synchronizer", [f"w1_{i}" for i in range(4)], {}), ("r", "synchronizer", ["r0", "r1"], {})]
    units = [{"name": "M", "kind": "synchronizer", "registers": ["m0", "m1"], "reason": "chain",
              "params": {"stages": 2, "order": [["m0", "m1"]]}},
             {"name": "W", "kind": "synchronizer", "registers": ["w0", "w1"], "reason": "chain",
              "params": {"stages": 2, "order": [[f"w0_{i}", f"w1_{i}"] for i in range(4)]}}]
    t = _toy_truth(regs, units)
    T = S.Truth(t)
    each = S.score(t, result([struct(f, "synchronizer", [f]) for f in sorted(T.universe)]))
    assert each["classes"]["all"]["registers"]["strict"]["per_kind"]["synchronizer"]["found"]["registers_found"] == 0
    chains = S.score(t, result([struct("M", "synchronizer", ["m0", "m1"], [["m0", "m1"]]),
                                struct("W", "synchronizer", sorted(T.flops["w0"] | T.flops["w1"]),
                                       [[f"w0_{i}", f"w1_{i}"] for i in range(4)]),
                                struct("R", "synchronizer", ["r0", "r1"], [["r0", "r1"]])]))
    st = chains["classes"]["all"]["registers"]["strict"]["per_kind"]["synchronizer"]
    assert st["found"]["recall"] == 1.0 and st["exact"]["recall"] == 1.0 and st["found"]["precision"] == 1.0


@pytest.mark.parametrize("design", DESIGNS)
@withhold_puzzle
def test_gaming_every_flop_its_own_synchronizer(design):
    """Every flop its own synchronizer structure: strict synchronizer recall is at most the share
    of 1-flop synchronizer registers that belong to no chain unit (TEMPO: 0 of 11; before the
    chain rule 6 of 11)."""
    T = S.Truth(truth_or_skip(design))
    den = T.denominators("synchronizer")
    if not den:
        pytest.skip("no synchronizers")
    rep = S.score(T.raw, result([struct(f, "synchronizer", [f]) for f in sorted(T.universe)]))
    free1 = sum(1 for n in den if len(T.flops[n]) == 1 and n not in T.chain_members)
    got = rep["classes"]["all"]["registers"]["strict"]["per_kind"]["synchronizer"]["found"]["registers_found"]
    assert got <= free1


def test_tie_break_ignores_recognizer_ids():
    """Two structures over the same flops with different kinds tie on IoU; which one matches must
    not depend on the ids the recognizer chose (it is decided by result position)."""
    t = _toy_truth([("A", "counter", ["a0", "a1", "a2"], {})])
    outs = []
    for ids in (("aaa", "zzz"), ("zzz", "aaa")):
        rep = S.score(t, result([struct(ids[0], "shift_register", ["a0", "a1", "a2"]),
                                 struct(ids[1], "counter", ["a0", "a1", "a2"])]))
        outs.append(rep["classes"]["all"]["registers"]["strict"]["per_kind"]["counter"]["found"]["registers_found"])
    assert outs[0] == outs[1]


def test_dropped_flops_block_exact_and_are_counted():
    """Result flops the truth does not know (unmapped, unknown, or a non-flop id) are dropped and
    counted; a structure that lost flops can be found but never exact. Shadow flops are ignored."""
    t = _toy_truth([("A", "counter", ["a0", "a1"], {})], unmapped=["r0"])
    t["registers"][0]["bits"][0]["shadow_flops"] = ["a0dup"]
    rep = S.score(t, result([struct("s", "counter", ["a0", "a1", "r0", "zz", "?17"])], [["a0", "a1", "r0", "zz"]]))
    assert rep["result"]["unmapped_flops_in_result"] == 1 and rep["result"]["unknown_flops_in_result"] == 2
    assert rep["result"]["dropped_flops"] == 3 and rep["result"]["structures_with_dropped_flops"] == 1
    st = rep["classes"]["all"]["registers"]["strict"]["per_kind"]["counter"]
    assert st["found"]["recall"] == 1.0 and st["exact"]["recall"] == 0.0
    assert rep["grouping"]["all_flops"]["ami"] == 1.0
    shadow = S.score(t, result([struct("s", "counter", ["a0", "a1", "a0dup"])]))
    assert shadow["classes"]["all"]["registers"]["strict"]["per_kind"]["counter"]["exact"]["recall"] == 1.0
    assert shadow["result"]["shadow_flops_in_result"] == 1 and shadow["result"]["dropped_flops"] == 0


def test_lenient_exact_words_use_declared_units():
    """A register split into its two declared per-slice units, and a two-register unit grouped as
    one word, count as exact words only under the lenient rule."""
    t = _toy_truth([("R", "data_register", ["r0", "r1", "r2", "r3"], {}), ("D", "synchronizer", ["d0", "d1"], {}),
                    ("E", "synchronizer", ["e0", "e1"], {})],
                   units=[{"name": "R[1:0]", "kind": "data_register", "registers": ["R"], "flops": ["r0", "r1"],
                           "reason": "slice"},
                          {"name": "R[3:2]", "kind": "data_register", "registers": ["R"], "flops": ["r2", "r3"],
                           "reason": "slice"},
                          {"name": "DE", "kind": "synchronizer", "registers": ["D", "E"], "reason": "one chain"}])
    g = S.score(t, result(groups=[["r0", "r1"], ["r2", "r3"], ["d0", "d1", "e0", "e1"]]))["grouping"]["all_flops"]
    assert g["exact_words"] == 0 and g["exact_words_lenient"] == 3 and g["truth_words_multi"] == 3


def test_lenient_denominators_keep_excused_registers():
    """alt_kinds widen what a match accepts and never remove a register from a denominator
    (S3_DESIGN 4.2): a counter with a non-structure alt kind stays in the lenient counter
    denominator and is listed as excused, with the recall without it reported beside."""
    t = _toy_truth([("A", "counter", ["a0", "a1"], {}),
                    ("B", "counter", ["b0", "b1"], {"alt_kinds": ["register_file_word"], "alt_reason": "test"})])
    rep = S.score(t, result([struct("s", "counter", ["a0", "a1"])]))
    le = rep["classes"]["all"]["registers"]["lenient"]["per_kind"]["counter"]
    assert le["registers"] == 2 and le["found"]["recall"] == 0.5
    assert le["excused"]["registers"] == 1 and le["excused"]["recall_without_excused"] == 1.0


@pytest.mark.parametrize("design", DESIGNS)
@withhold_puzzle
def test_truth_files_validate(design):
    """Each truth file present is retrace-s3-truth/2 and passes schema.check_truth (a failure here
    is a stale truth file, owned by the truth generators), covers its flops, and its declared
    units reference known registers."""
    t = truth_or_skip(design)
    assert t["schema"] == schema.TRUTH_SCHEMA
    assert not schema.check_truth(t), f"{TRUTH[design]} fails check_truth (stale truth file?)"
    assert t["flops"] and all(v["primary"] in v["registers"] for v in t["flops"].values())
    assert not S.Truth(t).bad_units


def test_load_truth_refuses_other_schemas(tmp_path):
    p = tmp_path / "truth_x.json"
    p.write_text(json.dumps({"registers": [], "meta": {}}))
    with pytest.raises(ValueError):
        S.load_truth(str(p))


# ----------------------------------------------------------------------------------------------
# gaming tests on both truths


def _universe(T):
    return sorted(T.universe)


def _kinds_with_support(T):
    return [c for c in schema.STRUCTURE_KINDS if T.denominators(c, False)]


def _chain_units_to_report(T):
    """Chain units a perfect result reports: not the union of other chain units (TEMPO: ui_in,
    uio_in, CS, SCK, MOSI; not "ui_in + uio_in")."""
    chains = [u for u in T.units if u["chain"]]
    out = []
    for u in chains:
        regs = set(u["registers"])
        inner = [set(v["registers"]) for v in chains if v is not u and set(v["registers"]) < regs]
        if not (inner and set().union(*inner) == regs):
            out.append(u)
    return out


def _lanes_of(ref, flops):
    lanes = collections.defaultdict(list)
    for f, (li, si) in sorted(ref[1].items(), key=lambda x: x[1]):
        if f in flops:
            lanes[li].append(f)
    order = [lanes[k] for k in sorted(lanes)]
    rest = [f for f in sorted(flops) if f not in ref[1]]
    return order + ([rest] if rest else [])


def _perfect(T):
    """One structure per structure-kind register (per chain unit for per-stage synchronizers): its
    flops, the truth's own order, its params; groups = the truth partition."""
    structs, blocks = [], collections.defaultdict(list)
    for n in T.scored:
        if T.kind[n] in schema.STRUCTURE_KINDS and n not in T.chain_members:
            ref = S.reference(T, {"unit": False, "name": n})
            structs.append(struct(n, T.kind[n], sorted(T.flops[n]), _lanes_of(ref, T.flops[n]),
                                  T.regs[n].get("params") or {}))
    for u in _chain_units_to_report(T):
        ref = S.reference(T, {"unit": True, "name": u["name"], "params": u["params"]})
        order = _lanes_of(ref, u["flops"]) if ref else [sorted(u["flops"])]
        structs.append(struct(u["name"], "synchronizer", sorted(u["flops"]), order, u["params"]))
    for f in T.universe:
        blocks[T.primary[f]].append(f)
    return result(structs, blocks.values())


@pytest.mark.parametrize("design", DESIGNS)
@withhold_puzzle
def test_gaming_one_structure_holding_all_flops(design):
    """One structure of the majority kind holding every flop, one group: no register is found or
    exact under strict or lenient scoring (threshold: exactly 0), precision 0, AMI and ARI 0
    (|x| < 1e-9); every non-majority kind has bit-level F1 0."""
    T = S.Truth(truth_or_skip(design))
    k = S.majority_kind(T)
    rep = S.score(T.raw, result([struct("all", k, _universe(T))], [_universe(T)]))
    for mode in ("strict", "lenient"):
        for c, v in rep["classes"]["all"]["registers"][mode]["per_kind"].items():
            assert v["found"]["registers_found"] == 0 and v["exact"]["registers_found"] == 0
            assert v["found"]["precision"] in (None, 0.0)
    assert abs(rep["grouping"]["all_flops"]["ami"]) < 1e-9 and abs(rep["grouping"]["all_flops"]["ari"]) < 1e-9
    for c in schema.STRUCTURE_KINDS:
        if c != k:
            assert rep["classes"]["all"]["bits"]["strict"][c]["f1"] in (None, 0.0)


@pytest.mark.parametrize("design", DESIGNS)
@withhold_puzzle
def test_gaming_every_flop_its_own_structure(design):
    """Every flop its own structure (majority kind), no groups: a register can only be found if it
    has one flop, so found recall of kind c equals exactly the share of 1-flop registers of kind c
    (outside chain units), precision is at most 0.05, and AMI = ARI = 0 (|x| < 1e-9)."""
    T = S.Truth(truth_or_skip(design))
    k = S.majority_kind(T)
    rep = S.score(T.raw, result([struct(f"s{i}", k, [f]) for i, f in enumerate(_universe(T))]))
    per = rep["classes"]["all"]["registers"]["strict"]["per_kind"]
    den = T.denominators(k, False)
    ones = sum(1 for n in den if len(T.flops[n]) == 1 and n not in T.chain_members)
    assert per[k]["found"]["recall"] == pytest.approx(ones / len(den))
    assert per[k]["found"]["precision"] <= 0.05
    assert abs(rep["grouping"]["all_flops"]["ami"]) < 1e-9 and abs(rep["grouping"]["all_flops"]["ari"]) < 1e-9


@pytest.mark.parametrize("design", DESIGNS)
@withhold_puzzle
def test_gaming_every_flop_the_majority_kind(design):
    """The truth's own grouping (every register a structure) but every structure labelled the
    majority kind: other kinds get recall 0 at register and bit level, the majority kind's
    precision is at most its share of the registers, and macro-F1 (registers and bits, strict)
    stays below 0.5 (it is at most 1/k for k kinds with support)."""
    T = S.Truth(truth_or_skip(design))
    k = S.majority_kind(T)
    structs = [struct(n, k, sorted(T.flops[n])) for n in T.scored]
    rep = S.score(T.raw, result(structs))
    reg, bits = rep["classes"]["all"]["registers"]["strict"], rep["classes"]["all"]["bits"]["strict"]
    for c in _kinds_with_support(T):
        if c != k:
            assert reg["per_kind"][c]["found"]["recall"] == 0.0 and bits[c]["recall"] == 0.0
    assert reg["per_kind"][k]["found"]["precision"] <= len(T.denominators(k, False)) / len(T.scored) + 1e-12
    kk = len(_kinds_with_support(T))
    bmacro = rep["classes"]["all"]["bits"]["macro_f1"]
    assert reg["macro_f1"] <= 1 / kk + 1e-12 and bmacro <= 1 / kk + 1e-12
    assert reg["macro_f1"] < 0.5 and bmacro < 0.5


@pytest.mark.parametrize("design", DESIGNS)
@withhold_puzzle
def test_gaming_random_grouping(design):
    """Random partitions with the truth's block sizes (5 seeds), each block of >= 2 flops a
    structure of the majority kind: mean AMI and ARI within 0.03 of 0 and every draw within 0.1
    (N = 92 on the puzzle, so single draws scatter); found recall of every kind <= 0.1."""
    T = S.Truth(truth_or_skip(design))
    k = S.majority_kind(T)
    sizes = sorted(collections.Counter(T.primary[f] for f in T.universe).values(), reverse=True)
    amis, aris = [], []
    for seed in range(5):
        rng = random.Random(seed)
        fl = rng.sample(_universe(T), len(T.universe))
        blocks, i = [], 0
        for s in sizes:
            blocks.append(fl[i:i + s])
            i += s
        structs = [struct(f"r{j}", k, b) for j, b in enumerate(blocks) if len(b) >= 2]
        rep = S.score(T.raw, result(structs, blocks), draws=1)
        amis.append(rep["grouping"]["all_flops"]["ami"])
        aris.append(rep["grouping"]["all_flops"]["ari"])
        for c, v in rep["classes"]["all"]["registers"]["strict"]["per_kind"].items():
            assert v["found"]["recall"] in (None,) or v["found"]["recall"] <= 0.1
    assert abs(np.mean(amis)) < 0.03 and abs(np.mean(aris)) < 0.03
    assert max(map(abs, amis)) < 0.1 and max(map(abs, aris)) < 0.1


@pytest.mark.parametrize("design", DESIGNS)
@withhold_puzzle
def test_gaming_multilabel_hedging(design):
    """The review's bit-level exploits: every register reported once per structure kind, and four
    whole-universe structures, one per kind. Each flop now gets one predicted class ("several"),
    wrong unless the truth accepts every kind, so bit-level macro- and micro-F1 are 0 (threshold:
    exactly 0 strict; lenient <= the majority baseline's)."""
    T = S.Truth(truth_or_skip(design))
    hedged = [struct(f"{n}:{k}", k, sorted(T.flops[n])) for n in T.scored for k in schema.STRUCTURE_KINDS]
    whole = [struct(k, k, _universe(T)) for k in schema.STRUCTURE_KINDS]
    base = S.score(T.raw, S.majority_result(T))["classes"]["all"]["bits"]
    for res in (hedged, whole):
        b = S.score(T.raw, result(res))["classes"]["all"]["bits"]
        assert b["macro_f1"] == 0.0 and b["micro_f1"] == 0.0
        assert b["macro_f1_lenient"] <= max(base["macro_f1_lenient"], 0.0) + 1e-12


@pytest.mark.parametrize("design", DESIGNS)
@withhold_puzzle
def test_gaming_proven_is_not_self_declared(design):
    """Right flop sets with random kinds, all marked "proven": without harness verification
    nothing counts as verified, so the verified block finds nothing; only the harness's flags
    (tools/s3/verify.py via run.py) put a structure there."""
    T = S.Truth(truth_or_skip(design))
    rng = random.Random(3)
    res = result([struct(n, rng.choice(schema.STRUCTURE_KINDS), sorted(T.flops[n])) for n in T.scored])
    rep = S.score(T.raw, res)
    assert rep["result"]["claimed_proven"] == len(T.scored) and rep["result"]["verified"] == 0
    for mode in ("strict", "lenient"):
        for v in rep["classes"]["verified"]["registers"][mode]["per_kind"].values():
            assert v["found"]["registers_found"] == 0 and v["structures"] == 0
    flagged = S.score(T.raw, res, verified=[i % 2 == 0 for i in range(len(res["structures"]))])
    assert flagged["result"]["verified"] == (len(res["structures"]) + 1) // 2


@pytest.mark.parametrize("design", DESIGNS)
@withhold_puzzle
def test_gaming_constant_parameters(design):
    """The review's constant-parameter answer (perfect matches, every parameter the majority
    value): its accuracy equals the per-parameter majority baseline, so kappa is 0 (to 1e-12) for
    every parameter; the true parameters score kappa 1 wherever the baseline is below 1."""
    T = S.Truth(truth_or_skip(design))
    perfect = _perfect(T)
    rep = S.score(T.raw, perfect)
    per = rep["params"]["per_param"]
    if not per:
        pytest.skip("no comparable parameters")
    maj = {k: v["majority_value"] for k, v in per.items()}
    const = json.loads(json.dumps(perfect))
    for s in const["structures"]:
        for p in list(s["params"]):
            key = f"{s['kind']}.{p}"
            if key in maj:
                s["params"][p] = maj[key]
    c = S.score(T.raw, const)["params"]
    for k, v in c["per_param"].items():
        assert v["correct"] == v["majority_correct"], k
        assert v["kappa"] in (None,) or abs(v["kappa"]) < 1e-12
    for k, v in per.items():
        if v["majority_accuracy"] < 1:
            assert v["kappa"] == pytest.approx(1.0), k


@pytest.mark.parametrize("design", DESIGNS)
@withhold_puzzle
def test_gaming_split_registers(design):
    """The review's split exploit (each register as (w//2+1, rest)): found@IoU>=0.75 credits only
    registers whose larger part reaches IoU 0.75, exact only registers of <= 2 flops, and the mean
    IoU of found pairs stays below 1 (thresholds computed from the truth's widths)."""
    T = S.Truth(truth_or_skip(design))
    structs, hi, small = [], set(), set()
    for n in T.scored:
        if T.kind[n] not in schema.STRUCTURE_KINDS or n in T.chain_members:
            continue
        fl = sorted(T.flops[n])
        w = len(fl)
        cut = w // 2 + 1
        structs.append(struct(f"{n}:a", T.kind[n], fl[:cut]))
        if fl[cut:]:
            structs.append(struct(f"{n}:b", T.kind[n], fl[cut:]))
        if cut / w >= S.IOU_HIGH:
            hi.add(n)
        if cut == w:
            small.add(n)
    rep = S.score(T.raw, result(structs))
    for c, v in rep["classes"]["all"]["registers"]["strict"]["per_kind"].items():
        den = [n for n in T.denominators(c) if n not in T.chain_members]
        assert v["found_iou75"]["registers_found"] <= sum(1 for n in den if n in hi)
        assert v["exact"]["registers_found"] <= sum(1 for n in den if n in small)


@pytest.mark.parametrize("design", DESIGNS)
@withhold_puzzle
def test_gaming_module_lumping(design):
    """The review's lumping exploit (one structure per RTL module definition, labelled with the
    module's commonest structure kind; puzzle: strict found macro-F1 0.689). Macro-F1 over kinds
    with one register stays high by construction, so the scorer shows what exposes it: micro-F1
    (found) <= 0.3 and exact macro-F1 <= 0.1 (measured 2026-09-22: puzzle 0.176 / 0.022, TEMPO
    0.089 / 0.036), and kinds with fewer than 3 registers are flagged."""
    T = S.Truth(truth_or_skip(design))
    by = collections.defaultdict(list)
    for n in T.scored:
        by[T.regs[n].get("module_def")].append(n)
    structs = []
    for m, regs in sorted(by.items(), key=lambda x: str(x[0])):
        ks = collections.Counter(T.kind[n] for n in regs if T.kind[n] in schema.STRUCTURE_KINDS)
        if ks:
            fl = sorted(set().union(*(T.flops[n] for n in regs)))
            structs.append(struct(str(m), ks.most_common(1)[0][0], fl))
    r = S.score(T.raw, result(structs))["classes"]["all"]["registers"]["strict"]
    assert r["micro_f1"] <= 0.3 and r["macro_f1_exact"] <= 0.1, (r["micro_f1"], r["macro_f1_exact"])
    for k, v in r["per_kind"].items():
        assert v["small_support"] == (v["registers"] < S.SMALL_SUPPORT)


def test_tempo_multilane_chains_score_strictly():
    """TEMPO's natural synchronizer answer, one multi-lane structure per chain (ui_in 16 flops,
    uio_in 16, CS 2) plus rst_sync, is found strictly (the review measured 0/11 for the per-lane
    version before chain units): every structure found and at least 7 of the 11 registers (11 once
    the truth lists the SCK/MOSI aliases as ui_in members, as it does since 2026-09-22)."""
    T = S.Truth(truth_or_skip("tempo"))
    want = {"ui_in synchronizer, 2 stages", "uio_in synchronizer, 2 stages", "CS synchronizer"}
    units = [u for u in T.units if u["name"] in want]
    if len(units) != 3 or "rst_sync" not in T.regs:
        pytest.skip("TEMPO synchronizer units renamed")
    structs = [struct(u["name"], "synchronizer", sorted(u["flops"])) for u in units]
    structs.append(struct("rst", "synchronizer", sorted(T.flops["rst_sync"])))
    st = S.score(T.raw, result(structs))["classes"]["all"]["registers"]["strict"]["per_kind"]["synchronizer"]
    assert st["found"]["precision"] == 1.0 and st["found"]["registers_found"] >= 7, st


@pytest.mark.parametrize("design", DESIGNS)
@withhold_puzzle
def test_perfect_result_scores_one(design):
    """A result built from the truth (one structure per structure-kind register, per chain unit
    for per-stage synchronizers, in the truth's order, with the truth's parameters; groups = the
    truth partition; every structure verified) scores 1.0 on every metric that has a denominator:
    found and exact precision/recall/F1 per kind, macro- and micro-F1 (strict and lenient, all and
    verified structures), bit-level P/R/F1, order (score and coverage within and across lanes),
    parameter accuracy, AMI, ARI, NMI, pair F1, purity, inverse purity and exact-word recall."""
    T = S.Truth(truth_or_skip(design))
    res = _perfect(T)
    rep = S.score(T.raw, res, verified=all_verified(res))
    for sub in ("all", "verified"):
        c = rep["classes"][sub]
        for mode in ("strict", "lenient"):
            r = c["registers"][mode]
            for k, v in r["per_kind"].items():
                for part in ("found", "exact"):
                    for m in ("precision", "recall", "f1"):
                        assert v[part][m] in (None, 1.0), (sub, mode, k, part, m, v[part][m], v["missed"])
            assert r["macro_f1"] == 1.0 and r["macro_f1_exact"] == 1.0
            assert r["micro_f1"] == 1.0 and r["micro_f1_exact"] == 1.0
        for mode in ("strict", "lenient"):
            for k, v in c["bits"][mode].items():
                for m in ("precision", "recall", "f1"):
                    assert v[m] in (None, 1.0), (sub, mode, k, m)
        assert c["bits"]["macro_f1"] == 1.0 and c["bits"]["macro_f1_lenient"] == 1.0
    for kind, bands in rep["order"]["summary"].items():
        for band, e in bands.items():
            assert e["ordered"] == e["pairs_found"]
            for part in ("within", "across"):
                if part in e:
                    assert e[part]["score"] == 1.0 and e[part]["coverage"] == 1.0
            assert e["all_correct"] == e["pairs_found"] - e["chance_one"]
    assert rep["params"]["accuracy"] in (None, 1.0)
    for g in rep["grouping"].values():
        for m in ("ami", "ari", "nmi", "pair_f1", "purity", "inverse_purity", "exact_word_recall",
                  "exact_word_recall_lenient"):
            assert g[m] == pytest.approx(1.0), m


@pytest.mark.parametrize("design", DESIGNS)
@withhold_puzzle
def test_stub_scores_zero(design):
    """The stub (no structures, no groups): every recall 0, AMI and ARI of the singletons 0."""
    T = S.Truth(truth_or_skip(design))
    rep = S.score(T.raw, result())
    for mode in ("strict", "lenient"):
        for v in rep["classes"]["all"]["registers"][mode]["per_kind"].values():
            assert v["found"]["recall"] in (None, 0.0)
    assert abs(rep["grouping"]["all_flops"]["ami"]) < 1e-9 and abs(rep["grouping"]["all_flops"]["ari"]) < 1e-9


# ----------------------------------------------------------------------------------------------
# synthetic netlists (sky130 cells) for verify.py and the harness

SYN_V = """
module top(clk, din, en, q0, q1, q2, c0, c1);
  input clk, din, en;
  output q0, q1, q2, c0, c1;
  wire n0, n1, t1;
  sky130_fd_sc_hd__dfxtp_1 s0 (.CLK(clk), .D(din), .Q(q0));
  sky130_fd_sc_hd__dfxtp_1 s1 (.CLK(clk), .D(q0), .Q(q1));
  sky130_fd_sc_hd__dfxtp_1 s2 (.CLK(clk), .D(q1), .Q(q2));
  sky130_fd_sc_hd__xor2_1 x0 (.A(c0), .B(en), .X(n0));
  sky130_fd_sc_hd__and2_1 a0 (.A(c0), .B(en), .X(t1));
  sky130_fd_sc_hd__xor2_1 x1 (.A(c1), .B(t1), .X(n1));
  sky130_fd_sc_hd__dfxtp_1 k0 (.CLK(clk), .D(n0), .Q(c0));
  sky130_fd_sc_hd__dfxtp_1 k1 (.CLK(clk), .D(n1), .Q(c1));
endmodule
"""


@functools.cache
def _sky_lib():
    if not os.path.exists(R.SKY_LIB):
        return None
    return Library(R.SKY_LIB)


def synthetic(tmp_path):
    lib = _sky_lib()
    if lib is None:
        pytest.skip("sky130 Liberty absent")
    p = tmp_path / "syn.v"
    p.write_text(SYN_V)
    nl, key = load_verilog(str(p), lib, seed=None)
    return nl, key


def _syn_truth():
    return _toy_truth([("sh", "shift_register", ["s0", "s1", "s2"],
                        {"params": {"order": [["s0", "s1", "s2"]], "lanes": 1, "depth": 3}}),
                       ("cnt", "counter", ["k0", "k1"], {"params": {"bit_order": ["k0", "k1"]}})], design="synthetic")


def _claim(flop, equals, when=(), role="defining"):
    return {"type": "next", "flop": flop, "equals": equals, "when": list(when), "role": role}


def _syn_recognize(nl):
    """A test recognizer for the synthetic netlist (any id permutation): finds the shift chain and
    the 2-bit counter structurally and states them as schema v2 asks: kind, order, params and the
    control conditions over opaque ids (the harness builds the defining templates itself)."""
    g = GateGraph(nl)
    q_of = {f.q: f for f in g.flops}
    pin = {g.lit_of_net[n]: n for n in nl.inputs}
    sup = dict(zip([f.cell for f in g.flops], g.supports()))
    src = g.sources
    chain = {}
    for f in g.flops:
        if f.ns & 1 == 0 and (f.ns >> 1) in q_of:
            chain[f.cell] = q_of[f.ns >> 1].cell
    head = [f for f in g.flops if f.ns in pin and any(v == f.cell for v in chain.values())][0]
    order = [head.cell]
    while any(v == order[-1] for v in chain.values()):
        order.append([k for k, v in chain.items() if v == order[-1]][0])
    rest = [f for f in g.flops if f.cell not in order]
    en_net = [n for n in nl.inputs if g.lit_of_net[n] != head.ns and any(
        src[i] == g.lit_of_net[n] >> 1 for i in range(len(src)) if sup[rest[0].cell] >> i & 1)][0]
    nsup = {f.cell: bin(sup[f.cell]).count("1") for f in rest}
    k0, k1 = sorted(rest, key=lambda f: nsup[f.cell])
    shift = struct("sh", "shift_register", order, [order], {"lanes": 1, "depth": len(order)})
    shift["control"] = {"when": [], "hold": True}   # schema v2 requires it for a shift_register; the
    # chain's when is [] so the hold region is empty, which the harness accepts and counts as vacuous
    cnt = struct("cnt", "counter", [k0.cell, k1.cell], [[k0.cell, k1.cell]], {"direction": "up"})
    cnt["control"] = {"when": [{"net": en_net, "value": 1}], "hold": True}
    fake = struct("fake", "synchronizer", order[:2], [order[:2]])            # "proven", no input net
    wrong = struct("wrong", "counter", [k0.cell, k1.cell], [[k1.cell, k0.cell]], {"direction": "up"})
    wrong["control"] = {"when": [{"net": en_net, "value": 1}], "hold": True}   # MSB first: refuted
    return result([shift, cnt, fake, wrong])


def test_verify_true_false_and_vacuous_claims(tmp_path):
    """verify.py on synthetic claims: a true claim verifies (shift stage = previous stage; counter
    bit = q xor carry; hold under en=0); a false one is refuted (stage 1 = stage 2, a counter bit
    = its own q always); a vacuous COND (en=0 and en=1) is rejected; malformed claims (not a flop,
    not a net, unknown operator, bad role) are rejected; verdicts are deterministic."""
    nl, key = synthetic(tmp_path)
    cell = {n: i for i, n in enumerate(key.cell_name)}
    net = {n: i for i, n in enumerate(key.net_name)}
    q = lambda n: {"q": cell[n]}  # noqa: E731
    ver = V.Verifier(nl)
    ok = [_claim(cell["s1"], q("s0")), _claim(cell["s0"], {"net": net["din"]}),
          _claim(cell["k1"], {"xor": [q("k1"), {"and": [q("k0"), {"net": net["en"]}]}]}),
          _claim(cell["k0"], q("k0"), [{"net": net["en"], "value": 0}], "hold"),
          _claim(str(cell["k0"]), {"not": {"xor": [q("k0"), {"net": net["en"]}, {"const": 1}]}})]
    for c in ok:
        assert ver.check_claim(c)["verified"], c
    bad = [_claim(cell["s1"], q("s2")), _claim(cell["k0"], q("k0")),
           _claim(cell["k1"], {"xor": [q("k1"), q("k0")]})]
    for c in bad:
        v = ver.check_claim(c)
        assert not v["verified"] and v["reason"].startswith("refuted"), c
    vac = _claim(cell["k0"], {"const": 0}, [{"net": net["en"], "value": 0}, {"net": net["en"], "value": 1}], "hold")
    v = ver.check_claim(vac)
    assert not v["verified"] and v["reason"].startswith("vacuous")
    for c in (_claim(cell["x0"], {"const": 0}), _claim(cell["k0"], {"net": 10 ** 6}),
              _claim(cell["k0"], {"nand": [q("k0")]}), _claim(cell["k0"], q("k0"), role="guess"),
              {"type": "next", "flop": cell["k0"]}, "claim"):
        v = ver.check_claim(c)
        assert not v["verified"] and v["reason"].startswith("malformed"), c
    again = V.Verifier(nl)
    assert [again.check_claim(c)["verified"] for c in ok + bad] == [True] * len(ok) + [False] * len(bad)


def test_verify_structure_rules(tmp_path):
    """Schema v2 (kind-bound) at the harness boundary: the harness builds the defining templates
    from kind, order and params; the recognizer's conditions only select the case. A 3-stage shift
    in chain order and the 2-bit counter under en=1 (LSB first, with hold) verify; the same shift in
    a wrong order, the counter MSB first, a 2-deep 'shift', a counter bit restated alone, a counter
    under a vacuous condition and an unscored kind do not; the "proven" status counts for nothing."""
    nl, key = synthetic(tmp_path)
    cell = {n: i for i, n in enumerate(key.cell_name)}
    net = {n: i for i, n in enumerate(key.net_name)}
    en1 = [{"net": net["en"], "value": 1}]

    # schema v2 (2026-09-22) requires control.hold for counter and shift_register and verifies it, so
    # every fixture of those two kinds claims it; each negative below then still fails for its OWN
    # reason (a wrong order, depth 2, a single bit, a vacuous case), not for a missing obligation.
    def st(sid, kind, names, params=None, when=(), hold=None):
        s = struct(sid, kind, [cell[n] for n in names], [[cell[n] for n in names]], params)
        s["control"] = {"when": list(when),
                        "hold": (kind in ("counter", "shift_register")) if hold is None else hold}
        return s
    structs = [st("g", "shift_register", ["s0", "s1", "s2"]),
               st("c", "counter", ["k0", "k1"], {"direction": "up"}, en1),
               st("wo", "shift_register", ["s0", "s2", "s1"]),
               st("msb", "counter", ["k1", "k0"], {"direction": "up"}, en1),
               st("d2", "shift_register", ["s0", "s1"]),
               st("r", "counter", ["k1"], {"direction": "up"}),
               st("vac", "counter", ["k0", "k1"], {"direction": "up"}, en1 + [{"net": net["en"], "value": 0}]),
               st("u", "data_register", ["s0", "s1", "s2"]),
               st("nohold", "shift_register", ["s0", "s1", "s2"], hold=False)]
    rep = V.verify_result(nl, result(structs))
    got = [s["verified"] for s in rep["structures"]]
    assert got == [True, True, False, False, False, False, False, False, False], [s["reason"] for s in rep["structures"]]
    assert "control.hold is required" in rep["structures"][8]["reason"]
    outs = [R.outcome(s) for s in rep["structures"]]
    assert outs[:2] == ["verified", "verified"] and outs[2] == outs[3] == "refuted", outs
    assert outs[6] == "vacuous" and outs[7] == "unscored kind", outs
    assert rep["summary"]["claimed_proven"] == len(structs) and rep["summary"]["verified"] == 2
    assert V.verify_result(nl, {"structures": "x"})["structures"] == []


def test_relabel_is_a_hidden_bijection(tmp_path):
    """The relabelled netlist has the same logic (GateGraph summary), no Key name is reachable
    from it, two relabellings differ, and mapping flop ids back through the kept permutation gives
    exactly the original flop instance names."""
    nl, key = synthetic(tmp_path)
    nl2, cells, nets = R.relabel(nl)
    seen = {tuple(R.relabel(nl)[1]) for _ in range(6)}
    assert len(seen) > 1
    g1, g2 = GateGraph(nl).summary(), GateGraph(nl2).summary()
    for k in ("signals", "kinds", "depth", "flops", "gate_arity", "flops_async_clear", "flops_async_preset"):
        assert g1[k] == g2[k], k
    assert R.anonymity(nl2, key)["leaks"] == 0
    assert nl2.lib.paths == ()
    conv, stats = R.id_mapper(nl2, key, cells)
    mapped = {conv(c) for c in R.flop_cells(nl2)}
    assert mapped == {key.cell_name[c] for c in R.flop_cells(nl)}
    assert conv("not-an-id").startswith("?") and stats["not_an_id"] == 1


SYN_BB_V = """
module top(clk, din, wen, q0, q1);
  input clk, din, wen;
  output q0, q1;
  wire m0, m1;
  RM_TEST_SRAM_2x1 u_mem (.CLK(clk), .A_DIN0(din), .A_WEN(wen), .A_DOUT0(m0), .A_DOUT1(m1));
  sky130_fd_sc_hd__dfxtp_1 r0 (.CLK(clk), .D(m0), .Q(q0));
  sky130_fd_sc_hd__dfxtp_1 r1 (.CLK(clk), .D(m1), .Q(q1));
endmodule
"""
SYN_BB = {"RM_TEST_SRAM_2x1": {"CLK": "input", "A_DIN0": "input", "A_WEN": "input", "A_DOUT0": "output",
                               "A_DOUT1": "output"}}


def synthetic_blackbox(tmp_path):
    lib = _sky_lib()
    if lib is None:
        pytest.skip("sky130 Liberty absent")
    p = tmp_path / "syn_bb.v"
    p.write_text(SYN_BB_V)
    return load_verilog(str(p), lib, blackbox=SYN_BB, seed=None)


def test_relabel_anonymises_black_boxes(tmp_path):
    """V13: after relabel a black box's master is bb<k> and its pins opaque ids p<j> (directions
    kept, the same nets), numbered in a random order: over 12 relabellings the LEF pin order is not
    fixed; the file-order rng keeps LEF order. No macro or LEF pin name is reachable (the pin named
    CLK, also a Liberty pin name, is covered by the structural check); the logic is unchanged."""
    nl, key = synthetic_blackbox(tmp_path)
    nl2, cells, nets = R.relabel(nl)
    (bbm, pins), = nl2.blackbox.items()
    assert R.OPAQUE_BB.fullmatch(bbm) and all(R.OPAQUE_PIN.fullmatch(p) for p in pins)
    assert sorted(pins.values()) == sorted(SYN_BB["RM_TEST_SRAM_2x1"].values())
    c_new = [c for c, m in enumerate(nl2.master) if m == bbm][0]
    c_old = cells[c_new]
    old_nets = {nets[n] for n in nl.pins[c_old].values()}
    assert set(nl2.pins[c_new].values()) == old_nets and list(nl2.pins[c_new]) == sorted(nl2.pins[c_new])
    reach = R.strings_in(nl2, seen={id(nl2.lib)})
    assert not reach & {"RM_TEST_SRAM_2x1", "A_DIN0", "A_WEN", "A_DOUT0", "A_DOUT1"}
    anon = R.anonymity(nl2, key, nl)
    assert anon["leaks"] == 0 and anon["blackbox"]["masters"] == 1 and anon["blackbox"]["instances"] == 1
    g1, g2 = GateGraph(nl).summary(), GateGraph(nl2).summary()
    for k in ("signals", "kinds", "depth", "flops"):
        assert g1[k] == g2[k], k
    orders = set()
    for _ in range(12):
        bb = R.blackbox_names(nl, random.SystemRandom())
        pmap = bb["RM_TEST_SRAM_2x1"][1]
        orders.add(tuple(sorted(pmap, key=pmap.get)))
    assert len(orders) > 1
    fo = R.blackbox_names(nl, R.FileOrder())["RM_TEST_SRAM_2x1"][1]
    assert sorted(fo, key=fo.get) == list(SYN_BB["RM_TEST_SRAM_2x1"])


def test_anonymity_catches_named_black_boxes(tmp_path):
    """Negative control: a relabelled netlist that kept the macro and LEF pin names is reported
    (named leaks and non-opaque masters/pins), and evaluate() refuses to run the recognizer on it."""
    nl, key = synthetic_blackbox(tmp_path)
    nl2, cells, nets = R.relabel(nl)
    leaky = R.Netlist(nl2.lib, [nl.master[c] for c in cells],
                      [{p: nets[n] for p, n in sorted(nl.pins[c].items())} for c in cells],
                      nl2.n_nets, nl2.inputs, nl2.outputs, nl2.const, nl.blackbox, nl2.dropped)
    anon = R.anonymity(leaky, key, nl)
    assert anon["leaks"] > 0 and anon["blackbox"]["named_leaks"] >= 4 and anon["blackbox"]["not_opaque"] > 0
    orig = R.relabel
    try:
        R.relabel = lambda n, rng=None: (leaky, cells, nets)
        with pytest.raises(SystemExit, match="anonymity"):
            R.evaluate(nl, key, None, baseline=False)
    finally:
        R.relabel = orig


def test_map_result_maps_reset_values():
    """schema v2 control.reset_value is keyed by flop ids: the harness maps the keys to join keys
    (a non-flop key counts against the run like any other bad id); net ids stay opaque."""
    stats = {"n": 0}

    def conv(x):
        stats["n"] += 1
        return f"K{x}"
    res = result([struct("s", "counter", [3, 4])])
    res["structures"][0]["control"] = {"when": [{"net": 9, "value": 1}], "reset_value": {"3": 0, "4": 1},
                                       "input": 7}
    m = R.map_result(res, conv)
    c = m["structures"][0]["control"]
    assert c["reset_value"] == {"K3": 0, "K4": 1} and c["when"] == [{"net": 9, "value": 1}] and c["input"] == 7


def test_permutation_counts_and_record_locations(tmp_path, monkeypatch):
    """Frozen (blind) evaluations and the leakage test take at least FROZEN_PERMUTATIONS (5, pinned
    in freeze.PROTOCOL) permutations, development runs one unless asked; development records go to
    out/s3/eval/runs, blind records to out/s3/runs (which holds no puzzle development record)."""
    assert R.FROZEN_PERMUTATIONS == F.PROTOCOL["permutations_min"] >= 5
    assert R.permutations_for(True) == R.permutations_for(False, None, True) == R.FROZEN_PERMUTATIONS
    assert R.permutations_for(True, 9) == 9 and R.permutations_for(False) == 1 and R.permutations_for(False, 3) == 3
    monkeypatch.setattr(R, "DEV_RUNS", str(tmp_path / "dev"))
    monkeypatch.setattr(R, "RUNS", str(tmp_path / "blind"))
    rec = {"design": "toy", "created": "2026-09-22T00:00:00+00:00"}
    p, _ = R._write_record(rec, blind=False)
    q, _ = R._write_record(rec, blind=True)
    assert os.path.dirname(p) == str(tmp_path / "dev") and os.path.dirname(q) == str(tmp_path / "blind")
    # out/s3/runs holds BLIND records only (changes.jsonl C16, H05, T05). The assertion used to look
    # for a "puzzle" name prefix, which let a TEMPO development record sit there while the suite was
    # green and only the pre-freeze checklist complained (review[1] issue 3 of 2026-09-22, still open
    # as review[1]'s minor of 2026-09-23). It then copied freeze.checklist()'s rule (top-level `blind`
    # true), and both copies failed on the attempt record every blind run writes there first. It now
    # CALLS the one rule, freeze.run_strays(), which checklist() calls too: `blind` true, or an
    # attempt record the ledger proves (test_run_strays_accept_only_ledger_proven_attempts).
    strays = F.run_strays(ROOT)
    assert not strays, "strays in out/s3/runs: " + "; ".join(f"{p}: {why}" for p, why in strays.items())
    # --leakage is refused for a DEVELOPMENT run of anything but TEMPO; a blind run may take the
    # file-order arm (review[2] issue 4, changes.jsonl C43)
    with pytest.raises(SystemExit, match="--leakage runs on TEMPO"):
        R.run("puzzle", leakage_arm=True, write=False, echo=lambda *a: None)


def test_run_strays_accept_only_ledger_proven_attempts(tmp_path, monkeypatch):
    """freeze.run_strays(), the one rule for out/s3/runs (checklist() applies it too): a record with
    top-level `blind` true belongs, and so does the attempt record run.py --blind writes before
    extracting -- but only on the ledger's proof: named *.attempt.json, schema
    freeze.ATTEMPT_SCHEMA, and an "attempt" event with this path and this sha256. A non-blind
    record, the same renamed *.attempt.json, a correct-schema attempt with no ledger entry (or only a
    "finish" entry), a logged attempt copied to another name and a logged attempt edited after
    logging are strays -- and stay strays when they also carry `"blind": true`, since a file that
    looks like an attempt (name or schema) is judged by the ledger proof alone; elsewhere `blind`
    must be JSON true, not merely truthy. tmp_path is kept out of any enclosing git repository, so
    ledger_entries() has no history to read and the working-tree ledger alone is the proof."""
    root = str(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    if shutil.which("git"):
        assert F.git(root, "rev-parse", "--git-dir")[0] != 0, "tmp_path must not be inside a git repository"
    runs = os.path.join(root, F.RUNS_REL)
    assert F.run_strays(root) == {}                       # no out/s3/runs at all
    # the attempt exactly as a blind run makes it: run.py's own writer and ledger entry
    monkeypatch.setattr(R, "RUNS", runs)
    monkeypatch.setattr(R, "ROOT", root)
    monkeypatch.setattr(R, "LEDGER_ROOT", root)
    att = R._open_attempt("toy", "2026-09-23T00:00:00+00:00", {"freeze_hash": "f" * 64}, None, None)
    good = os.path.join(root, att["record"])
    assert att["record"] == os.path.relpath(good, root) and good.endswith(F.ATTEMPT_SUFFIX)
    assert json.load(open(good))["schema"] == F.ATTEMPT_SCHEMA and F.sha256_file(good) == att["record_sha256"]
    blind_rec, _sha = R._write_record({"schema": "retrace-s3-run/1", "design": "toy", "blind": True,
                                       "created": "2026-09-23T00:00:00+00:00"}, True)
    with open(os.path.join(runs, "unreadable.json"), "w") as f:
        f.write("{not json")                             # skipped, as it always was
    assert F.run_strays(root) == {}, "a ledger-proven attempt and a blind record are not strays"

    def put(name, body):
        p = os.path.join(runs, name)
        with open(p, "w") as f:
            f.write(body if isinstance(body, str) else json.dumps(body))
        return os.path.join(F.RUNS_REL, name), F.sha256_file(p)

    def log(event, rel, sha):
        F.ledger_append({"event": event, "attempt": "x", "design": "toy", "freeze_hash": "f" * 64,
                         "record": rel, "record_sha256": sha}, root)

    dev = {"schema": "retrace-s3-run/1", "design": "toy", "blind": False, "meta": {"recognizer": "r"}}
    forged = dict(json.load(open(good)), attempt="0" * 16)
    cases = {}
    cases["non-blind"] = put("toy-dev.json", dev)[0]
    cases["renamed"] = put("blind-toy-dev.attempt.json", dev)[0]
    log("attempt", *put("blind-toy-dev2.attempt.json", dev))       # a ledger entry does not make it an attempt
    cases["renamed, logged"] = os.path.join(F.RUNS_REL, "blind-toy-dev2.attempt.json")
    cases["forged"] = put("blind-toy-forged.attempt.json", forged)[0]
    log("finish", *put("blind-toy-finish.attempt.json", forged))   # only an "attempt" event proves
    cases["finish only"] = os.path.join(F.RUNS_REL, "blind-toy-finish.attempt.json")
    cases["copied"] = put("blind-toy-copy.attempt.json", open(good).read())[0]   # proof is for another path
    log("attempt", *put("blind-toy-bare.json", forged))            # attempt schema, logged, wrong name
    cases["not named"] = os.path.join(F.RUNS_REL, "blind-toy-bare.json")
    cases["not an object"] = put("list.json", [1, 2])[0]
    edited_rel, edited_sha = put("blind-toy-edited.attempt.json", forged)
    log("attempt", edited_rel, edited_sha)
    assert edited_rel not in F.run_strays(root), "logged with its sha256: not a stray"
    put("blind-toy-edited.attempt.json", dict(forged, rerun={"reason": "edited after logging"}))
    cases["edited"] = edited_rel
    # `"blind": true` must not stand in for the ledger proof of anything that looks like an attempt
    cases["forged, blind"] = put("blind-toy-forgedb.attempt.json", dict(forged, blind=True))[0]
    cases["renamed, blind"] = put("blind-toy-run.attempt.json", dict(dev, blind=True))[0]
    log("attempt", *put("blind-toy-bareb.json", dict(forged, blind=True)))   # attempt schema, wrong name
    cases["not named, blind"] = os.path.join(F.RUNS_REL, "blind-toy-bareb.json")
    eb_rel, eb_sha = put("blind-toy-editedb.attempt.json", forged)
    log("attempt", eb_rel, eb_sha)
    assert eb_rel not in F.run_strays(root), "logged with its sha256: not a stray"
    put("blind-toy-editedb.attempt.json", dict(forged, design="other", blind=True, structures=["smuggled"]))
    cases["edited, blind"] = eb_rel
    # outside the attempt rule `blind` must be JSON true, not merely truthy
    cases["blind 'false'"] = put("toy-str.json", dict(dev, blind="false"))[0]
    cases["blind 1"] = put("toy-one.json", dict(dev, blind=1))[0]
    os.chmod(good, 0o644)                                 # run.py leaves it read-only
    with open(good, "a") as f:
        f.write(" ")                                      # the real attempt, one byte changed
    cases["real attempt edited"] = att["record"]
    strays = F.run_strays(root)
    assert set(strays) == set(cases.values()), {k: v in strays for k, v in cases.items()}
    assert os.path.relpath(blind_rec, root) not in strays
    assert "no ledger" in strays[cases["forged"]] and "no ledger" in strays[cases["finish only"]]
    assert "no ledger" in strays[cases["copied"]]
    assert "changed after the ledger logged it" in strays[cases["edited"]]
    assert "changed after the ledger logged it" in strays[cases["real attempt edited"]]
    assert "changed after the ledger logged it" in strays[cases["edited, blind"]]
    assert "no ledger" in strays[cases["forged, blind"]]
    assert "not named" in strays[cases["not named"]] and "not named" in strays[cases["not named, blind"]]
    assert all(f"but of schema {s!r}" in strays[cases[k]]
               for k, s in (("renamed", dev["schema"]), ("renamed, blind", dev["schema"])))
    assert all("non-blind" in strays[cases[k]] for k in ("non-blind", "blind 'false'", "blind 1"))
    assert all("holds blind records only" in why for why in strays.values())
    # checklist() blocks on exactly these, worded the same
    bad = F.checklist(root, leakage=False, echo=lambda *a: None)
    assert [b for b in bad if b.startswith(F.RUNS_REL)] == [f"{p}: {why}" for p, why in strays.items()]


SYN_CHAIN_V = """
module top(clk, din, q7);
  input clk, din;
  output q7;
  wire q0, q1, q2, q3, q4, q5, q6;
  sky130_fd_sc_hd__dfxtp_1 s0 (.CLK(clk), .D(din), .Q(q0));
  sky130_fd_sc_hd__dfxtp_1 s1 (.CLK(clk), .D(q0), .Q(q1));
  sky130_fd_sc_hd__dfxtp_1 s2 (.CLK(clk), .D(q1), .Q(q2));
  sky130_fd_sc_hd__dfxtp_1 s3 (.CLK(clk), .D(q2), .Q(q3));
  sky130_fd_sc_hd__dfxtp_1 s4 (.CLK(clk), .D(q3), .Q(q4));
  sky130_fd_sc_hd__dfxtp_1 s5 (.CLK(clk), .D(q4), .Q(q5));
  sky130_fd_sc_hd__dfxtp_1 s6 (.CLK(clk), .D(q5), .Q(q6));
  sky130_fd_sc_hd__dfxtp_1 s7 (.CLK(clk), .D(q6), .Q(q7));
endmodule
"""


def _chain(tmp_path):
    lib = _sky_lib()
    if lib is None:
        pytest.skip("sky130 Liberty absent")
    p = tmp_path / "chain.v"
    p.write_text(SYN_CHAIN_V)
    nl, key = load_verilog(str(p), lib, seed=None)
    names = [f"s{i}" for i in range(8)]
    t = _toy_truth([("sh", "shift_register", names, {"params": {"order": [names], "lanes": 1, "depth": 8}})],
                   design="synthetic")
    return nl, key, t


def _chain_recognizer(by_id):
    """A test recognizer for the 8-flop chain: the flops found structurally; the order read from
    the D->Q links (canonical) or, leaking, from the ids (by_id)."""
    def make(nl):
        g = GateGraph(nl)
        q_of = {f.q: f for f in g.flops}
        nxt = {q_of[f.ns >> 1].cell: f.cell for f in g.flops if f.ns & 1 == 0 and (f.ns >> 1) in q_of}
        head = [f.cell for f in g.flops if f.cell not in nxt.values()][0]
        order = [head]
        while order[-1] in nxt:
            order.append(nxt[order[-1]])
        if by_id:
            order = sorted(order)
        return result([struct("sh", "shift_register", order, [order])], [order])
    return make


def test_leakage_test_flags_an_id_reading_recognizer(tmp_path, monkeypatch):
    """The design's leakage test on a synthetic 8-flop chain (file order: ids in chain order):
    a recognizer that orders the chain by id scores 1.0 in file order and less under the 5 seeded
    permutations, so its within-lane order is OUTSIDE the spread and the verdict fails; a canonical
    recognizer gives one answer under every permutation (distinct answers 1), equal to the file
    order's, and passes. The spread reports mean/min/max per metric."""
    nl, key, t = _chain(tmp_path)
    seeds = iter(range(100, 200))
    factory = lambda: random.Random(next(seeds))  # noqa: E731
    metric = "order.shift_register.width>=3.within.score"
    monkeypatch.setattr(R, "run_child", _fake_child(_chain_recognizer(by_id=True)))
    evs, sp, leak = R.evaluate_permutations(nl, key, t, 5, file_order=True, rng_factory=factory, baseline=False)
    assert [e["label"] for e in evs] == ["file", "p1", "p2", "p3", "p4", "p5"]
    assert all(not e["invalid_reasons"] for e in evs), [e["problems"] for e in evs]
    assert leak["metrics"][metric]["file"] == 1.0 and not leak["metrics"][metric]["inside"]
    assert metric in leak["outside"] and leak["verdict"] == "fail" and sp["k"] == 5
    assert set(sp["metrics"][metric]) >= {"mean", "median", "min", "max", "values"} and sp["metrics"][metric]["max"] < 1
    assert "OUTSIDE" in R.render_spread(sp, leak)
    monkeypatch.setattr(R, "run_child", _fake_child(_chain_recognizer(by_id=False)))
    evs, sp, leak = R.evaluate_permutations(nl, key, t, 5, file_order=True, rng_factory=factory, baseline=False)
    assert sp["distinct_answers"] == 1 and leak["file_equals_a_permutation"] and leak["verdict"] == "pass"
    assert leak["structures"]["inside"] and sp["structures"]["pairwise_jaccard"]["min"] == 1.0
    assert sp["metrics"][metric]["min"] == sp["metrics"][metric]["max"] == 1.0


def test_run_writes_a_multi_permutation_record(tmp_path, monkeypatch):
    """run() end to end with a stand-in design and recognizer: --leakage writes one development
    record (JSON, exclusive) with the file-order arm and 5 permutations as "evaluations", the
    "spread", the "leakage" report and the sources staged once; the echo shows the spread table."""
    nl, key, t = _chain(tmp_path)
    tp = tmp_path / "truth.json"
    t["design"] = "tempo"
    tp.write_text(json.dumps(t))
    monkeypatch.setattr(R, "load_design", lambda *a, **k: (nl, key))
    monkeypatch.setattr(R, "design_files", lambda *a, **k: [])
    monkeypatch.setattr(R, "tempo_snapshot_check", lambda: {"stand-in": True})
    monkeypatch.setattr(R, "run_child", _fake_child(_chain_recognizer(by_id=False)))
    lines = []
    rec = R.run("tempo", truth_path=str(tp), leakage_arm=True, runs=str(tmp_path / "runs"), echo=lines.append,
                baseline=False)
    assert rec["valid"], rec["invalid_reasons"]
    body = json.load(open(rec["path"]))
    assert os.path.dirname(rec["path"]) == str(tmp_path / "runs")
    assert [e["label"] for e in body["evaluations"]] == ["file", "p1", "p2", "p3", "p4", "p5"]
    assert body["permutations"]["k"] == 5 and body["permutations"]["file_order_arm"]
    assert body["spread"]["k"] == 5 and body["leakage"]["verdict"] == "pass"
    assert body["recognizer_sources"] and "Permutations: K = 5" in "\n".join(lines)


def test_multi_permutation_pending_record_is_scored_later(tmp_path, monkeypatch):
    """A blind record of K permutations waiting for its truth is scored per permutation later,
    with the spread over them."""
    nl, key, t = _chain(tmp_path)
    monkeypatch.setattr(R, "run_child", _fake_child(_chain_recognizer(by_id=False)))
    evs, sp, leak = R.evaluate_permutations(nl, key, None, 3, baseline=False)
    assert leak is None and all("score" not in e for e in evs)
    for e in evs:
        e.pop("flop_keys", None)
    rec = {"schema": R.RUN_SCHEMA, "design": "tt01__tt_um_chain", "created": "2026-09-22T00:00:00+00:00",
           "blind": True, "pending_truth": True, "valid": True, "invalid_reasons": [],
           "freeze": {"freeze_hash": "f" * 64}, "attempt": {"id": "a"}, "evaluations": evs,
           "flop_keys": [f"s{i}" for i in range(8)]}
    path = tmp_path / "blind-tt01__tt_um_chain-x.json"
    path.write_text(json.dumps(rec, default=str))
    t["design"] = "tt:tt01/tt_um_chain"
    (tmp_path / "truth_tt01__tt_um_chain.json").write_text(json.dumps(t))
    monkeypatch.setattr(R.freeze, "check", lambda *a, **k: [])
    monkeypatch.setattr(R.freeze, "load", lambda *a, **k: {"freeze_hash": "f" * 64})
    monkeypatch.setattr(R, "clean_blind_process", lambda: [])
    out = R.score_record(str(path), echo=lambda *a: None, write=False, truth_dir=str(tmp_path))
    assert out["valid"] and len(out["evaluations"]) == 3 and out["spread"]["k"] == 3
    assert out["spread"]["metrics"]["shift_register.found_r"]["min"] == 1.0


def _fake_child(make):
    """A stand-in for run_child: reads the harness's pickle (the relabelled netlist) and answers
    with make(netlist), as a recognizer would."""
    def fake(pkl, entry=None, timeout=None, **kw):
        with open(pkl, "rb") as f:
            nl = pickle.load(f)
        return {"ok": True, "result": make(nl), "returncode": 0, "wall_s": 0.0, "os_sandbox": "test",
                "recognizer_modules": [], "recognizer_sources": {}, "blocked": [], "blocked_count": 0}
    return fake


def test_harness_verifies_claims_end_to_end(tmp_path, monkeypatch):
    """evaluate() on the synthetic netlist with a schema-v2 recognizer: the harness verifies 2 of
    the 4 structures (shift and counter; the "proven" synchronizer without an input net and the
    counter listed MSB first are not); the verified block finds the shift register and the counter;
    the harness outcomes are recorded and scored; the run is valid; order and parameters are
    scored; claims leave the record as counts."""
    nl, key = synthetic(tmp_path)

    def make(n):
        res = _syn_recognize(n)
        res["structures"][2]["proof"]["claims"] = [_claim(res["structures"][2]["flops"][1],
                                                          {"q": res["structures"][2]["flops"][0]})]
        return res
    monkeypatch.setattr(R, "run_child", _fake_child(make))
    out = R.evaluate(nl, key, _syn_truth())
    assert out["invalid_reasons"] == [], out["problems"]
    assert out["verified_flags"] == [True, True, False, False]
    assert out["outcomes"][:2] == ["verified", "verified"] and out["outcomes"][3] == "refuted", out["outcomes"]
    assert out["verify"]["summary"]["verified"] == 2 and out["verify"]["summary"]["claimed_proven"] == 4
    rep = out["score"]
    ver = rep["classes"]["verified"]["registers"]["strict"]["per_kind"]
    assert ver["shift_register"]["found"]["recall"] == 1.0 and ver["counter"]["found"]["recall"] == 1.0
    assert ver["counter"]["structures"] == 1 and rep["classes"]["all"]["registers"]["strict"]["per_kind"][
        "counter"]["structures"] == 2
    assert rep["classes"]["all"]["registers"]["strict"]["per_kind"]["counter"]["outcomes"] == {"verified": 1,
                                                                                            "refuted": 1}
    assert _row(rep, "sh")["within"]["score"] == 1.0 and _row(rep, "cnt")["within"]["score"] == 1.0
    counted = [s["proof"]["claims"] for s in out["result"]["structures"] if "claims" in s["proof"]]
    assert counted == [1]   # claims leave the record as counts


def test_harness_invalidates_bad_ids_and_malformed_results(tmp_path, monkeypatch):
    """A structure naming a gate cell (not a flop) invalidates the run; so do the review's
    crashing shapes (a list result, a string structure, int flops, an int group), which are now
    type-checked instead of crashing the harness; a failed recognizer is invalid too."""
    nl, key = synthetic(tmp_path)

    def gate_id(n):
        res = _syn_recognize(n)
        gate = [c for c, m in enumerate(n.master) if "xor2" in m][0]
        res["structures"][0]["flops"].append(gate)
        return res
    monkeypatch.setattr(R, "run_child", _fake_child(gate_id))
    out = R.evaluate(nl, key, _syn_truth(), baseline=False)
    assert any("not flop cells" in r for r in out["invalid_reasons"])
    for bad in ([], {"structures": ["x"]}, {"structures": [{"kind": "counter", "flops": 3}]},
                {"structures": [], "groups": [3]}, {"structures": [{"kind": "counter", "flops": [], "order": "x"}]}):
        assert R.validate_result_types(bad), bad
        monkeypatch.setattr(R, "run_child", _fake_child(lambda n, b=bad: b))
        out = R.evaluate(nl, key, _syn_truth(), baseline=False)
        assert "the result is malformed" in out["invalid_reasons"], bad
        assert "score" in out   # scored as an empty result, no crash
    monkeypatch.setattr(R, "run_child", lambda *a, **k: {"ok": False, "error": "boom", "returncode": 1, "wall_s": 0})
    out = R.evaluate(nl, key, _syn_truth(), baseline=False)
    assert "the recognizer failed" in out["invalid_reasons"]


def test_synthetic_in_the_real_sandbox(tmp_path):
    """The real isolated child (OS sandbox where available, audit hook, result pipe) running the
    real recognizer on the synthetic netlist: no denial, a valid, scored run (what it finds is the
    recognizers' business, not asserted here)."""
    nl, key = synthetic(tmp_path)
    out = R.evaluate(nl, key, _syn_truth(), timeout=300)
    assert out["invalid_reasons"] == [], out["problems"]
    rec = out["recognizer"]
    assert rec["ok"] and rec["returncode"] == 0 and rec["blocked_count"] == 0
    assert rec["os_sandbox"] == R.os_sandbox_kind()
    assert set(rec["recognizer_sources"]) >= {"tools/s3/recognize.py", "tools/s3/netlist.py", "tools/__init__.py"}
    assert "headline" in out["score"] and len(out["outcomes"]) == len(out["result"]["structures"])


# ----------------------------------------------------------------------------------------------
# static anonymity of recognizer modules

ALLOWED_TOP = {"numpy", "z3"}
ALLOWED_S3 = {"netlist", "params"}
# standard-library modules a recognizer module may not import: native calls and hidden imports
# (ctypes, importlib), and every file, OS, process, network and serialisation module (review of
# 2026-09-22; the sandbox blocks these at run time too, this is hygiene)
FORBIDDEN_STDLIB = {
    "ctypes", "importlib", "zipimport", "pkgutil", "runpy", "builtins", "inspect", "code", "codeop", "pdb", "site",
    "sysconfig", "os", "io", "pathlib", "shutil", "tempfile", "glob", "fileinput", "filecmp", "linecache", "mmap",
    "fcntl", "posix", "nt", "pwd", "grp", "getpass", "platform", "pty", "tty", "termios", "signal", "subprocess",
    "multiprocessing", "concurrent", "_posixsubprocess", "socket", "socketserver", "ssl", "select", "selectors",
    "asyncio", "http", "urllib", "ftplib", "smtplib", "imaplib", "poplib", "nntplib", "telnetlib", "xmlrpc",
    "webbrowser", "mailbox", "email", "pickle", "shelve", "dbm", "sqlite3", "marshal", "zipfile", "tarfile", "gzip",
    "bz2", "lzma"}
# calls and names a recognizer module may not use (files, dynamic code, the builtins module)
FORBIDDEN_CALLS = {"open", "exec", "eval", "compile", "__import__", "breakpoint", "input"}
FORBIDDEN_NAMES = {"__builtins__", "__loader__"}
DESIGN_WORDS = ("tempo", "puzzle", "elementalcollision", "tt_um")
# PDK and library markers: IHP masters would identify TEMPO (the only IHP design), sky130 the rest
PDK_WORDS = ("sky130", "sg13", "ihp", "rm_ihpsg13", "gf180", "freepdk", "nangate", "asap7")
REPO_DIRS = ("out/", "tools/", "upstream/", "pdk/", "answer/", "rtl_recovered/", "docs/", "runs/", "src/")
PATH_EXT = re.compile(r"\.(json|pkl|pickle|gds|oas|v|sv|vh|lib|lef|def|vcd|fst|py|txt|log|ys|csv|spice|mag)\b", re.I)
# register names that are also ordinary words (and schema vocabulary) are not treated as leaks; the
# words themselves are not spelled out here (sha256[:32] of each lower-case word), so this file
# names no truth register
GENERIC_SHA256 = {
    "dc083dbe056a217097b6d6aba9e34f05", "4e73ff840ac8644a388365f8b5cff0b0", "0081779c287d567d9ca622f4c0cc2ede",
    "6fe2e0f6071ac2bb8d0b1ef26d1b691e", "3eeb7e96e59ce40f9cb1a089daba079f", "514cb13f603464f97849ba88d2d4f969",
    "02195b8e989603e4dfb45352b902e8dc", "7160f8688035138fcbc9a6c8041949eb", "a83a31320d921b888a48fa5edd0b4b5a",
    "acba25512100f80b56fc3ccd14c65be5", "3e64cc41cf8e07b43936d7bc4eaf8bdb"}
TABLE_MAX = 256        # literal tables longer than this are flagged (a memorised fingerprint would be one)
INT_BITS_MAX = 256     # integer literals wider than this are flagged
WORD = re.compile(r"[A-Za-z_]\w*")
DOTTED = re.compile(r"[A-Za-z_][\w$]*(?:\[\d+\])?(?:\.[A-Za-z_][\w$]*(?:\[\d+\])?)*")


def _recognizer_files():
    mods = [m for m in R.recognizer_modules() if m != "tools.s3.netlist"]  # the reviewed analysis core
    return {m: os.path.join(ROOT, *m.split(".")) + ".py" for m in mods}


def _generic(word):
    return hashlib.sha256(word.lower().encode()).hexdigest()[:32] in GENERIC_SHA256


class TruthDigests:
    """Salted digests of every truth file's names (review of 2026-09-22: the name check must never
    print or hold a puzzle name): register names (full hierarchical names), identifiers of local
    names and RTL bits (>= 3 characters, not an ordinary word or schema vocabulary), and exact join
    keys and netlist instance names. The salt is fresh per test process (os.urandom), so the
    digests are useless outside it. find(s) returns the kinds of names s contains, never the name."""

    def __init__(self, designs=None):
        self.salt = os.urandom(16)
        self.full, self.tokens, self.exact = {}, {}, {}
        vocab = set(schema.KINDS) | set(schema.PROOF) | {p for ps in schema.PARAMS.values() for p in ps}
        for d in designs if designs is not None else DESIGNS:
            if not os.path.exists(TRUTH[d]):
                continue
            with open(TRUTH[d]) as f:
                raw = json.load(f)
            for r in raw["registers"]:
                self._add(self.full, r["name"], d)
                self._token(S._local_name(r["name"]), d, vocab)
                for b in r["bits"]:
                    for k in ("rtl_bit", "rtl_name"):
                        if b.get(k):
                            toks = WORD.findall(b[k])
                            if " " in b[k]:   # prose (e.g. a retimed flop's description): identifiers only
                                toks = [x for x in toks if "_" in x or any(c.isdigit() for c in x)]
                            for x in toks:
                                self._token(x, d, vocab)
                    for k in ("flop", "gds_instance", "nl_instance", "q_net"):
                        if b.get(k):
                            self._add(self.exact, b[k], d)
            for f in (raw.get("flops") or {}):
                self._add(self.exact, f, d)
            del raw

    def h(self, s):
        return hmac.new(self.salt, s.encode(), "sha256").digest()

    def _add(self, table, s, d):
        table.setdefault(self.h(s), set()).add(d)

    def _token(self, t, d, vocab):
        if len(t) >= 3 and not _generic(t) and t not in vocab:
            self._add(self.tokens, t, d)

    def find(self, s):
        """[(what, designs)] for the names s contains (full register names as dotted tokens or
        their dotted sub-sequences; identifiers; exact keys), without saying which."""
        out = []
        for tok in DOTTED.findall(s):
            parts = tok.split(".")
            subs = {".".join(parts[i:j]) for i in range(len(parts)) for j in range(i + 1, len(parts) + 1)}
            hit = set().union(*(self.full.get(self.h(x), set()) for x in subs))
            if hit:
                out.append(("a register name", sorted(hit)))
        words = set(WORD.findall(s))
        hit = set().union(*(self.tokens.get(self.h(w), set()) for w in words)) if words else set()
        if hit:
            out.append(("a register or RTL bit name", sorted(hit)))
        hit = set().union(*(self.exact.get(self.h(w), set()) for w in words | {s}))
        if hit:
            out.append(("a join key or instance name", sorted(hit)))
        return out

    def __len__(self):
        return len(self.full) + len(self.tokens) + len(self.exact)


@functools.cache
def _truth_digests():
    return TruthDigests()


def _strings(tree):
    """(line, text) of every string and bytes constant (bytes decoded as latin-1, so no byte is lost)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value
        elif isinstance(node, ast.Constant) and isinstance(node.value, bytes):
            yield node.lineno, node.value.decode("latin-1")


def _large_literals(tree):
    """Literal tables a memorised design could hide in: list/tuple/set/dict displays of more than
    TABLE_MAX constant elements, bytes constants longer than TABLE_MAX, integers wider than
    INT_BITS_MAX bits."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            elts = node.elts
        elif isinstance(node, ast.Dict):
            elts = node.keys + node.values
        else:
            elts = None
        if elts is not None and sum(isinstance(e, ast.Constant) for e in elts) > TABLE_MAX:
            out.append(f"line {node.lineno}: a literal table of {len(elts)} elements")
        if isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bytes) and len(v) > TABLE_MAX:
                out.append(f"line {node.lineno}: a bytes literal of {len(v)} bytes")
            if isinstance(v, int) and not isinstance(v, bool) and abs(v).bit_length() > INT_BITS_MAX:
                out.append(f"line {node.lineno}: an integer literal of {abs(v).bit_length()} bits")
    return out


def _looks_like_path(s):
    for tok in re.split(r"[\s'\"(),;]+", s):
        if "/" not in tok and "\\" not in tok:
            continue
        # a lone "/" (a division in prose, "a / b") names no file; "/x..." does
        if (re.match(r"/[\w.~-]", tok) or tok.startswith(("~", "./", "../", "\\")) or PATH_EXT.search(tok)
                or any(d in tok for d in REPO_DIRS)):
            return True
    return bool(PATH_EXT.search(s) and re.search(r"\w\.(json|pkl|gds|v|lib|lef|def|vcd)\b", s))


STR_METHODS = {"startswith", "endswith", "find", "rfind", "index", "rindex", "count", "split", "rsplit", "partition",
               "rpartition", "strip", "lstrip", "rstrip", "replace", "lower", "upper", "casefold", "removeprefix",
               "removesuffix", "__contains__", "__eq__", "__ne__", "format", "encode"}


def _is_master(n):
    """An expression that is a cell's master name: x.master, x.master[i], a name called master(s),
    or a string method / str() applied to one."""
    if isinstance(n, ast.Subscript):
        n = n.value
    if isinstance(n, ast.Call):
        if isinstance(n.func, ast.Attribute) and n.func.attr in STR_METHODS:
            return _is_master(n.func.value)
        if isinstance(n.func, ast.Name) and n.func.id == "str" and n.args:
            return _is_master(n.args[0])
        return False
    return (isinstance(n, ast.Attribute) and n.attr == "master") or (isinstance(n, ast.Name) and n.id in
                                                                     ("master", "masters", "master_name"))


def _is_str_literal(n):
    if isinstance(n, ast.Constant):
        return isinstance(n.value, (str, bytes))
    if isinstance(n, (ast.Tuple, ast.List, ast.Set)):
        return bool(n.elts) and all(_is_str_literal(e) for e in n.elts)
    return isinstance(n, ast.JoinedStr)


def _code_violations(tree):
    """Forbidden calls and names, and uses of a master name against a literal: a comparison (==,
    !=, in, ...) of a master expression with a string literal, a string method called on a master
    name, or a regular-expression call on one."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            out.append(f"line {node.lineno}: call of {node.func.id}()")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            out.append(f"line {node.lineno}: use of {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            out.append(f"line {node.lineno}: use of .{node.attr}")
        if isinstance(node, ast.Compare):
            sides = [node.left] + node.comparators
            if any(_is_master(x) for x in sides) and any(_is_str_literal(x) for x in sides):
                out.append(f"line {node.lineno}: a master name compared with a string literal")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            f = node.func
            if f.attr in STR_METHODS and _is_master(f.value):
                out.append(f"line {node.lineno}: string method {f.attr}() on a master name")
            elif isinstance(f.value, ast.Name) and f.value.id == "re" and any(_is_master(a) for a in node.args):
                out.append(f"line {node.lineno}: re.{f.attr}() on a master name")
    return out


def test_recognizer_modules_import_only_what_is_allowed():
    """Recognizer modules (tools/s3/recognize.py and the tools.s3 modules it imports, netlist
    excepted) import only the standard library (minus FORBIDDEN_STDLIB: native calls, hidden
    imports, files, the OS, processes, the network, serialisation), numpy, z3, tools.s3.netlist,
    tools.s3.params and each other; they never call open, exec, eval, compile, __import__,
    breakpoint or input, never touch __builtins__ or __loader__, and never compare a master name
    with a string literal (IHP masters would identify TEMPO)."""
    files = _recognizer_files()
    own = {m.split(".")[-1] for m in files}
    stdlib = set(sys.stdlib_module_names)
    assert "tools.s3.recognize" in files
    for mod, path in files.items():
        with open(path) as f:
            tree = ast.parse(f.read(), path)
        bad = _code_violations(tree)
        assert not bad, (mod, bad[:5])
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = "tools.s3" + ("." + node.module if node.module else "")
                    names = [base + "." + a.name if not node.module else base for a in node.names]
                else:
                    names = [node.module] + [f"{node.module}.{a.name}" for a in node.names if node.module == "tools.s3"]
            for n in names:
                top = n.split(".")[0]
                if n == "tools.s3":
                    continue
                if n.startswith("tools.s3."):
                    assert n.split(".")[2] in ALLOWED_S3 | own, f"{mod} imports {n}"
                elif top == "tools":
                    pytest.fail(f"{mod} imports {n}")
                else:
                    assert top in ALLOWED_TOP or (top in stdlib and top not in FORBIDDEN_STDLIB), f"{mod} imports {n}"


def test_recognizer_modules_hold_no_names_or_paths():
    """No string or bytes literal (docstrings included) in a recognizer module names a design, a
    PDK or cell library (sky130, sg13/IHP, ...), a register (full hierarchical name, or a local name
    of >= 3 characters that is not an ordinary word or schema vocabulary), an RTL bit, a join key
    or netlist instance, or a file path (leading / or ~, a repository directory, or a file
    extension). Truth names are compared as salted hashes and a failure names the module, the line
    and the kind of name only, never the name. Strings built at run time are not caught: this is
    hygiene; the post-freeze draw is the defence against memorisation."""
    dig = _truth_digests()
    bad = []
    for mod, path in _recognizer_files().items():
        with open(path) as f:
            tree = ast.parse(f.read(), path)
        for line, s in _strings(tree):
            low = s.lower()
            where = f"{mod}:{line}"
            if any(w in low for w in DESIGN_WORDS):
                bad.append(f"{where}: a design name")
            if any(w in low for w in PDK_WORDS):
                bad.append(f"{where}: a PDK or library name")
            if _looks_like_path(s):
                bad.append(f"{where}: a file path")
            for what, designs in dig.find(s):
                bad.append(f"{where}: {what} of truth {'/'.join(designs)} (salted hash; the name is withheld)")
    assert not bad, bad[:10]


def test_recognizer_modules_hold_no_large_literal_tables():
    """No recognizer module holds a literal table of more than 256 constants, a bytes literal of
    more than 256 bytes or an integer wider than 256 bits (flagged for review: a memorised
    fingerprint of a known design would need one)."""
    for mod, path in _recognizer_files().items():
        with open(path) as f:
            tree = ast.parse(f.read(), path)
        assert not _large_literals(tree), (mod, _large_literals(tree)[:3])


def test_static_checks_catch_planted_violations(tmp_path):
    """Negative controls: the literal checks fire on a path, a design word, a PDK word, a truth
    name (a TEMPO register's local name and its full name, found by salted hash without printing
    it), a bytes literal naming a design, and a large literal table / integer / bytes blob; the code
    checks fire on open/eval/__import__/__builtins__, on a master name compared with a literal (==
    and in), on a string method and a re call applied to a master name, and not on legitimate
    library lookups."""
    assert _looks_like_path("out/s3/truth_x.json") and _looks_like_path("/etc/hosts") and _looks_like_path("~/x")
    assert not _looks_like_path(schema.RESULT_SCHEMA) and not _looks_like_path("bias 1/8 of lanes")
    assert not _looks_like_path("lanes / words, LFSR/CRC candidates")
    assert any(w in "cells like sg13g2_dfrbp_1".lower() for w in PDK_WORDS)
    assert any(w in "SKY130_FD_SC_HD__DFXTP_1".lower() for w in PDK_WORDS)
    if os.path.exists(TRUTH["tempo"]):
        dig = TruthDigests(["tempo"])
        assert len(dig)
        T = S.Truth(_truth("tempo"))
        name = max(T.regs, key=lambda n: (n.count("."), n))   # a deep hierarchical name
        assert "a register name" in [w for w, _d in dig.find(f"see {name} here")]
        vocab = set(schema.KINDS) | {p for ps in schema.PARAMS.values() for p in ps}
        local = [S._local_name(n) for n in sorted(T.regs) if len(S._local_name(n)) >= 3
                 and not _generic(S._local_name(n)) and S._local_name(n) not in vocab][0]
        assert "a register or RTL bit name" in [w for w, _d in dig.find(f"x {local} y")]
        assert not dig.find("lorem ipsum dolor sit amet")
    planted = ast.parse("A = b'puzzle'\nB = [" + ", ".join(str(i) for i in range(300)) + "]\nC = " + str(1 << 300)
                        + "\nD = b'" + "x" * 300 + "'\n")
    assert any("puzzle" in s for _l, s in _strings(planted))
    assert len(_large_literals(planted)) == 3
    code = ast.parse("open('x')\neval('1')\n__import__('os')\nb = __builtins__\n"
                     "if nl.master[c] == 'sky130_fd_sc_hd__dfxtp_1': pass\n"
                     "if 'dfrtp' in self.nl.master[c]: pass\n"
                     "if master.startswith('sg13'): pass\n"
                     "re.match('x', nl.master[i])\n"
                     "if nl.master[c] in ('a', 'b'): pass\n")
    got = _code_violations(code)
    assert len(got) == 9, got
    ok = ast.parse("m = nl.lib.get(nl.master[c])\nif m is not None and m.kind == 'ff': pass\n"
                   "if nl.master[c] in nl.lib: pass\nx = self.sim.eval(V)\n")
    assert _code_violations(ok) == []


def test_recognizer_module_closure_follows_imports(tmp_path):
    """The sandbox's module list and the static checks follow absolute and relative imports."""
    src = tmp_path / "m.py"
    src.write_text("import tools.s3.alpha\nfrom tools.s3 import beta, gamma as g\nfrom .delta import x\n"
                   "from . import epsilon\nfrom tools.s3.zeta import y\nimport numpy\n")
    assert R._s3_imports(str(src)) == {"alpha", "beta", "gamma", "delta", "epsilon", "zeta"}
    mods = R.recognizer_modules()
    assert mods[0] == "tools.s3.recognize" and "tools.s3.netlist" in mods
    assert not any(m.split(".")[-1] in R.HARNESS_MODULES or m.split(".")[-1].startswith("truth") for m in mods)


def test_recognize_signature():
    from tools.s3 import recognize
    assert callable(recognize.recognize)
    out = recognize.recognize(R.Netlist(S_lib(), [], [], 0, [], [], {}, {}))
    assert schema.check_result(out) == [] and out["schema"] == schema.RESULT_SCHEMA


def S_lib():
    lib = R.Library.__new__(R.Library)
    lib.paths = ()
    return lib


# ----------------------------------------------------------------------------------------------
# the sandbox


def _tiny_pickle(tmp_path):
    p = tmp_path / "netlist.pkl"
    p.write_bytes(pickle.dumps(R.Netlist(S_lib(), [], [], 0, [], [], {}, {})))
    return str(p)


PROBES = r'''
import json as _j
_probe = {}
def _try(name, fn):
    try:
        fn()
        _probe[name] = "allowed"
    except BaseException as e:
        _probe[name] = type(e).__name__
_try("read_truth", lambda: open(%(truth)r).read())
_try("stat_truth", lambda: os.stat(%(truth)r))
_try("read_repo_source", lambda: open(%(src)r).read())
_try("read_pycache", lambda: open(%(pyc)r, "rb").read())
_try("write_file", lambda: open(%(out)r, "w").write("x"))
_try("import_truth_module", lambda: __import__("tools.s3.truth_puzzle"))
_try("import_harness_module", lambda: __import__("tools.s3.score"))
_try("import_other_package", lambda: __import__("networkx"))
_try("listdir_out", lambda: os.listdir(%(outdir)r))
_try("listdir_root", lambda: os.listdir(%(root)r))
_try("subprocess", lambda: __import__("subprocess").run(["/bin/echo", "x"]))
_try("socket", lambda: __import__("socket").socket())
_try("remove", lambda: os.remove(%(pkl)r))
_try("ctypes_libc", lambda: __import__("ctypes").CDLL("libc.dylib"))
_try("ctypes_symbol", lambda: __import__("ctypes").pythonapi.system)
_try("import_numpy", lambda: __import__("numpy").arange(3).sum())
_try("z3_solve", lambda: __import__("z3").Solver().check())
_try("yices", lambda: __import__("subprocess").run([%(yices)r, "--model", "/dev/stdin"], input="p cnf 1 1\n1 0\n",
     capture_output=True, text=True, check=True) if os.path.exists(%(yices)r) else None)
_try("read_pickle", lambda: open(%(pkl)r, "rb").read(1))
print("PROBE " + _j.dumps(_probe))
'''


def _probe(tmp_path, os_sandbox):
    pkl = _tiny_pickle(tmp_path)
    pyc = os.path.join(ROOT, "tools", "s3", "__pycache__", "score.cpython-314.pyc")
    truth = TRUTH["puzzle"] if os.path.exists(TRUTH["puzzle"]) else os.path.join(ROOT, "tools", "s3", "schema.py")
    probe = PROBES % {"truth": truth, "src": os.path.join(ROOT, "tools", "s3", "score.py"), "pyc": pyc,
                      "out": str(tmp_path / "leak.txt"), "outdir": os.path.join(ROOT, "out"), "root": ROOT,
                      "pkl": pkl, "yices": R.YICES_SAT}
    rep = R.run_child(pkl, extra=probe, timeout=120, fail_closed=False, os_sandbox=os_sandbox)
    line = [x for x in rep["stderr_tail"].splitlines() if x.startswith("PROBE ")]
    assert line, rep
    assert not os.path.exists(tmp_path / "leak.txt") and os.path.exists(pkl)
    return rep, json.loads(line[-1][6:])


@pytest.mark.parametrize("layer", ["hook", "os"])
def test_sandbox_blocks_file_access(tmp_path, layer):
    """In the recognizer's subprocess, with the audit hook alone ("hook") and with the OS layer
    too ("os", skipped without one): reading a truth file, repository source or a bytecode cache,
    writing a file, importing a truth or harness module or another package, listing out/ or the
    repository root, spawning a process, opening a socket, deleting the pickle, loading libc and
    looking up a libc symbol are refused; importing numpy, solving with z3, running yices-sat and
    reading the pickle are allowed; the stub still returns a valid result. The OS layer also
    hides a truth file's existence from os.stat (the hook alone cannot)."""
    kind = "none" if layer == "hook" else R.os_sandbox_kind()
    if layer == "os" and kind == "none":
        pytest.skip("no OS-level sandbox on this host")
    rep, got = _probe(tmp_path, kind)
    for k in ("read_truth", "read_repo_source", "read_pycache", "write_file", "listdir_out", "listdir_root",
              "subprocess", "socket", "remove", "ctypes_libc", "ctypes_symbol"):
        assert got[k] in ("PermissionError", "FileNotFoundError"), (k, got[k])
    for k in ("import_truth_module", "import_harness_module", "import_other_package"):
        assert got[k] in ("PermissionError", "ModuleNotFoundError", "ImportError"), (k, got[k])
    assert got["import_numpy"] == got["read_pickle"] == got["z3_solve"] == got["yices"] == "allowed"
    if layer == "os":
        assert got["stat_truth"] == "PermissionError"
    assert rep["ok"] and schema.check_result(rep["result"]) == []
    assert {"open", "os.listdir", "subprocess.Popen", "os.remove"} <= {e for e, _w in rep["blocked"]}


def test_sandbox_fails_closed_and_ignores_forged_messages(tmp_path):
    """Fail-closed: the first denial ends the child with VIOLATION_RC although the recognizer
    catches the PermissionError, and the run is not ok. A result printed to stdout is ignored (the
    answer only counts from the pipe, with the nonce), and a foreign line written to the result
    pipe invalidates the run."""
    pkl = _tiny_pickle(tmp_path)
    truth = os.path.join(ROOT, "tools", "s3", "score.py")
    rep = R.run_child(pkl, extra=f"try:\n    open({truth!r}).read()\nexcept PermissionError:\n    pass\n", timeout=60)
    assert rep["returncode"] == R.VIOLATION_RC and not rep["ok"] and rep["violation"][0] == "open"
    rep = R.run_child(pkl, extra='print(\'{"ok": true, "result": {"structures": [1]}}\')\n', timeout=60)
    assert rep["ok"] and rep["result"]["structures"] == []
    forge = ("for _fd in range(3, 64):\n    try:\n        os.write(_fd, b'{\"ok\": true, \"result\": {}}\\n')\n"
             "    except OSError:\n        pass\n")
    rep = R.run_child(pkl, extra=forge, timeout=60)
    assert not rep["ok"] and "foreign" in rep["error"]


def test_recognizer_runs_clean_in_sandbox_on_an_empty_netlist(tmp_path):
    rep = R.run_child(_tiny_pickle(tmp_path), timeout=120)
    assert rep["ok"] and rep["blocked_count"] == 0 and rep["result"]["structures"] == []
    assert rep["recognizer_modules"][:1] and "tools.s3.recognize" in rep["recognizer_modules"]
    assert not any("__pycache__" in p for p in rep["recognizer_sources"])


def test_children_share_one_staged_copy_of_the_sources(tmp_path):
    """The children of one multi-permutation run read ONE staged copy of the recognizer's sources
    (taken once, outside the pickle directories): two children report identical source hashes and
    run clean in the sandbox from it."""
    src = tmp_path / "src"
    src.mkdir()
    staged = R.stage_sources(str(src))
    reps = []
    for i in range(2):
        d = tmp_path / f"w{i}"
        d.mkdir()
        p = d / "netlist.pkl"
        p.write_bytes(pickle.dumps(R.Netlist(S_lib(), [], [], 0, [], [], {}, {})))
        reps.append(R.run_child(str(p), timeout=120, staged=staged))
    assert all(r["ok"] and r["blocked_count"] == 0 for r in reps), [r.get("error") for r in reps]
    assert reps[0]["recognizer_sources"] == reps[1]["recognizer_sources"] == staged[1]


def test_macos_profile_denies_by_default(tmp_path):
    """The generated sandbox-exec profile denies by default, allows no network and no writes but
    /dev/null, and names only the run directory, the Python installation, numpy, z3 and system
    paths as readable trees (never the repository, never the venv root)."""
    pkl = _tiny_pickle(tmp_path)
    pkg, _h = R.stage_sources(str(tmp_path / "src"))
    cfg = R.sandbox_config(pkl, pkg)
    prof = R.macos_profile(cfg, str(tmp_path))
    assert "(deny default)" in prof and "network" not in prof
    assert prof.count("file-write") == 1 and '(allow file-write-data (literal "/dev/null"))' in prof
    subpaths = re.findall(r'\(subpath "([^"]+)"\)', prof)
    assert not any(os.path.realpath(ROOT) == p or p == os.path.realpath(os.path.join(ROOT, ".venv")) for p in subpaths)
    assert all(not p.startswith(os.path.realpath(ROOT) + os.sep) or "site-packages" in p for p in subpaths)


# ----------------------------------------------------------------------------------------------
# which designs a run may take


def test_development_runs_refuse_the_puzzle_and_third_party_designs():
    """Recognizer code runs on the puzzle and on third-party designs only with --blind (under a
    holding freeze); a development run of either is refused before any extraction, as is an
    unknown design and a TEMPO_ROOT other than the frozen snapshot."""
    for kw in ({"design": "puzzle"}, {"design": "tt06__tt_um_x", "gds": "/nonexistent.gds"}, {"design": "foo"}):
        with pytest.raises(SystemExit):
            R.run(write=False, echo=lambda *a: None, **kw)


def test_tempo_runs_only_from_the_snapshot(monkeypatch):
    monkeypatch.setenv("TEMPO_ROOT", "/somewhere/else")
    with pytest.raises(SystemExit, match="snapshot"):
        R.tempo_lvs()


@pytest.mark.skipif(os.environ.get("RETRACE_S3_SLOW") != "1",
                    reason="slow (~8 min, ~2 GB harness + ~1.3 GB child): set RETRACE_S3_SLOW=1")
def test_tempo_end_to_end():
    """The real recognizer on TEMPO (frozen snapshot) through the harness; replaces the stub-era
    test (which asserted that nothing is found). A smoke floor, not a quality gate: a valid run, the
    snapshot's checksums hold, every truth flop joins, no Key or black-box name reaches the
    recognizer and the SRAM black boxes are opaque; every scored kind with truth support is found
    at least once; the register macro-F1 beats the majority-class and structural baselines and AMI
    beats the structural baseline (no absolute numbers: those move with the recognizer); a second
    extraction gives the same canonical netlist hash."""
    if not R.design_available("tempo"):
        pytest.skip("TEMPO snapshot absent")
    truth_or_skip("tempo")
    rec = R.run("tempo", write=False, echo=lambda *a: None, timeout=1800)
    assert all(rec["tempo_snapshot"]["sha256sums"].values())
    j = rec["join"]
    assert j["truth_flops_in_netlist"] == j["truth_flops"], "truth_tempo.json does not match the TEMPO GDS"
    assert rec["valid"], rec["invalid_reasons"]
    anon = rec["netlist"]["anonymity"]
    assert anon["leaks"] == 0 and anon["blackbox"]["masters"] >= 1 and anon["blackbox"]["not_opaque"] == 0
    h = rec["score"]["headline"]
    for k in schema.STRUCTURE_KINDS:
        if h[k]["support"]:
            assert h[k]["found_r"] and h[k]["found_r"] > 0, k
    bl = rec["score"]["baselines"]
    assert h["macro_f1_registers"] > bl["majority_class"]["headline"]["macro_f1_registers"]
    assert h["macro_f1_registers"] > bl["structural"]["headline"]["macro_f1_registers"]
    assert h["ami"] > bl["structural"]["headline"]["ami"]
    nl, _key = R.load_tempo()
    assert F.netlist_hash(nl) == rec["netlist_sha256"]


@pytest.mark.skipif(os.environ.get("RETRACE_S3_LEAKAGE") != "1" and os.environ.get("RETRACE_S3_SLOW") != "1",
                    reason="very slow (6 recognizer runs; 8 min with 3 jobs): set RETRACE_S3_SLOW=1 "
                           "(the slow suite) or RETRACE_S3_LEAKAGE=1 (this test alone)")
def test_tempo_leakage():
    """The design's leakage test on TEMPO (S3_DESIGN section 2): the file-order arm must lie within
    the spread of 5 os.urandom permutations on every metric and on structure-set agreement. With a
    recognizer that is not permutation invariant the rule's false-alarm rate is up to 1/3 per
    varying metric (see run.LEAKAGE_NOTE); the failure message lists the 'strong' metrics (outside
    where the permutations agree) first.

    It runs with the rest of the slow suite (RETRACE_S3_SLOW=1) since review[2] issue 7: its own
    RETRACE_S3_LEAKAGE=1 gate meant no suite ever ran it. tools/s3/freeze.py's `checklist` runs the
    same thing before a freeze."""
    if not R.design_available("tempo"):
        pytest.skip("TEMPO snapshot absent")
    truth_or_skip("tempo")
    rec = R.run("tempo", write=False, echo=lambda *a: None, timeout=1800, leakage_arm=True,
                permutations=R.FROZEN_PERMUTATIONS, jobs=int(os.environ.get("RETRACE_S3_JOBS", "3")))
    assert rec["valid"], rec["invalid_reasons"]
    leak = rec["leakage"]
    assert leak["verdict"] == "pass", {"strong": leak["strong"], "outside": leak["outside"],
                                       "structures": leak["structures"]}
    # the determinism indicators the run record now carries (review[2] issue 4)
    for ev in rec["evaluations"]:
        info = ev.get("recognize_run")
        assert info and info.get("canonical_order") is not None, ev.get("label")
        assert not R.canonical_order_problems(info, ev.get("label")), ev["recognize_run"]["canonical_order"]


# ----------------------------------------------------------------------------------------------
# reporting and provenance (review[2]: the run record's determinism block, the corrected corpus
# split, the records' own evidence hashes, and the scorer's in-sample / out-of-sample labelling)


def test_recognize_run_line_carries_canonical_order_and_bdd():
    """recognize.py's RECOGNIZE_RUN line must forward ctl.run_info()['canonical_order'] and ['bdd'],
    not the timings alone: it is the only place the run record can learn whether the colour
    refinement left ties to id order (review[2] issue 4)."""
    src = open(os.path.join(ROOT, "tools", "s3", "recognize.py")).read()
    i = src.index("RECOGNIZE_RUN ")
    line = src[i:src.index("file=sys.stderr", i)]
    for key in ("canonical_order", "bdd", "stages"):
        assert f'"{key}"' in line, (key, line)


def test_recognize_run_info_parsing_takes_the_last_line():
    tail = ("noise\n"
            'RECOGNIZE_RUN {"stages": {"a": 1}, "canonical_order": {"rounds": 3}}\n'
            "RECOGNIZE_RUN not json\n"
            'RECOGNIZE_RUN {"stages": {"a": 2}, "canonical_order": {"rounds": 4}, "bdd": {"s": 0.1}}\n')
    info = R.recognize_run_info(tail)
    assert info["stages"] == {"a": 2} and info["canonical_order"] == {"rounds": 4}
    assert R.recognize_run_info("nothing here") is None


def test_canonical_order_problems():
    """A tie left to id order, a hit round budget, a missing block and a missing line are all
    problems; a clean refinement is not."""
    assert R.canonical_order_problems({"canonical_order": {"rounds": 32, "classes_stable": 900}}) == []
    assert any("id order" in p for p in
               R.canonical_order_problems({"canonical_order": {"rounds": 4096, "ties_left_to_id_order": 7}}))
    assert any("round budget" in p for p in
               R.canonical_order_problems({"canonical_order": {"rounds": 4096, "round_budget_hit": 1}}))
    assert any("no canonical order" in p for p in R.canonical_order_problems({"canonical_order": None}))
    assert any("no RECOGNIZE_RUN line" in p for p in R.canonical_order_problems(None))
    assert R.canonical_order_problems(None, label="perm3")[0].startswith("[perm3] ")


def test_leakage_arm_allowed_for_blind_designs():
    """--leakage is refused for a development run of a design other than TEMPO, but a blind run may
    take the file-order arm: the loader's sorted-name ids carry the same bus-order cue there
    (review[2] issue 4). The blind path still refuses for its own reasons, never for --leakage."""
    with pytest.raises(SystemExit) as e:
        R.run("tt06__tt_um_x", write=False, leakage_arm=True)
    assert "--leakage" in str(e.value)
    with pytest.raises(SystemExit) as e:
        R.run("tt06__tt_um_x", blind=True, leakage_arm=True, write=False)
    assert "--leakage" not in str(e.value) and "blind run refused" in str(e.value)


def test_corpus_split_forces_fitted_designs_into_train_and_drops_dropped():
    """corpus.splits() puts every FITTED_ON design in train whatever its hash position, corpus
    designs() no longer holds a DROPPED design, and manifest() applies both to a manifest written
    before them (review[2] issues 1 and 6)."""
    from tools.s3 import corpus as C
    assert "fsm_timer_ar" in C.FITTED_ON and "crc12_d16_ar" in C.DROPPED
    sp = C.splits(C.designs())
    for n in C.FITTED_ON:
        assert sp.get(n) in (None, "train"), n
    assert all(n not in sp for n in C.DROPPED)
    if not os.path.exists(os.path.join(C.DEFAULT_OUT, "manifest.json")):
        pytest.skip("corpus not built")
    man, raw = C.manifest(), C.manifest(raw=True)
    assert all(e["name"] not in C.DROPPED for e in man["designs"])
    assert {e["name"] for e in man["designs"] if e["split"] == "holdout"} == set(man["holdout"])
    assert not (set(man["holdout"]) & set(C.FITTED_ON))
    # every OTHER design keeps the split it was built with: the correction moves nothing else
    built = {e["name"]: e["split"] for e in raw["designs"]}
    moved = {e["name"] for e in man["designs"] if built.get(e["name"]) != e["split"]}
    assert moved <= set(C.FITTED_ON), moved


def test_record_evidence_separates_stale_contamination_from_a_moved_change_log(tmp_path):
    """freeze.record_evidence re-hashes what the records cite: a changed file under the
    CONTAMINATION record is stale (it describes the present and blocks a freeze), the same under
    the change log is only 'moved' (an entry's evidence is a snapshot), a vanished path is
    'missing' (review[2] issue 5)."""
    root = tmp_path / "r"
    (root / "tools" / "s3").mkdir(parents=True)
    (root / "out" / "s3").mkdir(parents=True)
    ev = root / "out" / "s3" / "thing.json"
    ev.write_text("one")
    good = hashlib.sha256(b"one").hexdigest()
    (root / "tools" / "s3" / "changes.jsonl").write_text(json.dumps(
        {"id": "C1", "date": "d", "module": "m", "change": "c",
         "evidence": [{"path": "out/s3/thing.json", "sha256": good}]}) + "\n")
    (root / "out" / "s3" / "contamination.json").write_text(json.dumps(
        {"schema": "t", "items": [{"id": "K1", "evidence": [{"path": "out/s3/thing.json", "sha256": good},
                                                            {"path": "out/s3/gone.json", "sha256": "0" * 64}]}]}))
    r = F.record_evidence(str(root))
    assert r["stale"] == [] and r["moved"] == [] and len(r["missing"]) == 1
    ev.write_text("two")
    r = F.record_evidence(str(root))
    assert len(r["stale"]) == 1 and F.CONTAMINATION_REL in r["stale"][0]
    assert len(r["moved"]) == 1 and F.CHANGES_REL in r["moved"][0]


@pytest.mark.skipif(shutil.which("git") is None, reason="git absent")
def test_freeze_write_refuses_stale_contamination_evidence(tmp_path):
    root, _g = _mini_repo(tmp_path)
    p = os.path.join(root, F.CONTAMINATION_REL)
    with open(p, "w") as f:
        json.dump({"schema": "test", "items": [{"id": "K1", "evidence": [
            {"path": "tools/s3/schema.py", "sha256": "0" * 64}]}]}, f)
    with pytest.raises(SystemExit) as e:
        F.write(root)
    assert "evidence that has changed" in str(e.value)
    fr = F.write(root, force=True)                       # --force records it instead of refusing
    assert fr["records_evidence"]["stale"] and F.freeze_hash(fr) == fr["freeze_hash"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git absent")
def test_freeze_checklist_reports_records_and_stray_run_records(tmp_path):
    """The pre-freeze checklist (without the leakage test, which needs TEMPO) reports a malformed
    change log, a missing contamination record, stale contamination evidence and a non-blind record
    left in out/s3/runs; skipping the leakage test is itself a blocking item (review[2] issue 7)."""
    root, _g = _mini_repo(tmp_path)
    os.makedirs(os.path.join(root, F.RUNS_REL), exist_ok=True)
    bad = F.checklist(root, leakage=False, echo=lambda *a: None)
    assert any("leakage test was skipped" in b for b in bad)
    with open(os.path.join(root, F.RUNS_REL, "tempo-x.json"), "w") as f:
        json.dump({"schema": "retrace-s3-run/1", "design": "tempo", "blind": False}, f)
    bad = F.checklist(root, leakage=False, echo=lambda *a: None)
    assert any("holds blind records only" in b for b in bad)
    os.remove(os.path.join(root, F.CONTAMINATION_REL))
    assert any("contamination.json: missing" in b for b in F.checklist(root, leakage=False, echo=lambda *a: None))


def test_score_labels_tempo_in_sample_and_prints_the_holdout_beside_it():
    """Every report carries `provenance`; a TEMPO report is labelled IN-SAMPLE and renders the
    corpus-holdout per-kind rates as the out-of-sample estimate (review[2] issue 0)."""
    t = _toy_truth([("A", "counter", ["a0", "a1", "a2"], {})], design="tempo")
    res = {"schema": schema.RESULT_SCHEMA, "structures": [], "groups": [], "meta": {}}
    rep = S.score(t, res)
    pv = rep["provenance"]
    assert pv["in_sample"] and "IN-SAMPLE" in S.render(rep)
    doc = S.out_of_sample()
    if doc is None:
        assert "absent" in pv["out_of_sample_missing"]
        pytest.skip("out/s3/honesty/holdout_rates.json not built")
    oos = pv["out_of_sample"]
    assert oos["designs"] and oos["per_kind"]["counter"]["items"]
    assert not (set(doc["split"]["corrections"]["moved"]) & set(doc["holdout"]["per_kind"]))
    text = S.render(rep)
    assert "OUT-OF-SAMPLE estimate" in text and "caveat:" in text
    other = S.score(_toy_truth([("A", "counter", ["a0", "a1", "a2"], {})], design="toy"), res)
    assert not other["provenance"]["in_sample"] and "IN-SAMPLE" not in S.render(other)


def _oos_provenance():
    """out/s3/honesty/oos_provenance.py, or None when the honesty tree is not built."""
    here = os.path.join(ROOT, "out", "s3", "honesty")
    if not os.path.exists(os.path.join(here, "oos_provenance.py")):
        return None
    if here not in sys.path:
        sys.path.insert(0, here)
    import oos_provenance                                   # noqa: PLC0415
    return oos_provenance


def test_every_published_out_of_sample_estimate_names_the_code_it_was_measured_on():
    """No artefact may publish a corpus-holdout figure without the code state it was measured on,
    and a stale one must be visible without reading it (changes.jsonl T01).

    This is the suite's half of the gate tools/s3/score.py and freeze.checklist() already apply to
    out/s3/honesty/holdout_rates.json: score.py protects the ONE file it prints from, while
    review[1] of 2026-09-23 found the honesty summary republishing a superseded estimate with
    "code_matches_tree": true beside it and nothing anywhere to say otherwise. A failure here means
    a tools/s3 file moved after the estimate was derived: re-run

        .venv/bin/python out/s3/honesty/holdout_rates.py --run
        .venv/bin/python out/s3/honesty/write_contamination.py
        .venv/bin/python out/s3/honesty/write_changes_review1.py
        .venv/bin/python out/s3/honesty/write_changes_integration.py
        .venv/bin/python out/s3/honesty/write_changes_freeze.py
        .venv/bin/python out/s3/honesty/summarise.py

    -- it is not a test to relax. It skips only when the honesty tree is not built at all."""
    mod = _oos_provenance()
    if mod is None:
        pytest.skip("out/s3/honesty/oos_provenance.py not present")
    rep = mod.check(ROOT)
    if not any(a["present"] for a in rep["artifacts"]):
        pytest.skip("no out-of-sample artefact is built")
    # R1 holds of every artefact that exists, whatever its role: an estimate whose code state is
    # unknown cannot be shown to describe anything (the one permanently-lost case is named in the
    # registry itself and reported through the summary instead)
    for a in rep["artifacts"]:
        if a["present"] and not a["code_recorded"]:
            assert mod.ARTIFACTS[[x.rel for x in mod.ARTIFACTS].index(a["path"])].unrecoverable, \
                f"{a['path']} publishes an out-of-sample figure and records no code state"
    assert not rep["blocks"], "stale out-of-sample provenance:\n  " + "\n  ".join(rep["blocks"])


def test_the_corpus_and_tempo_apply_one_toggle_rule():
    """A 1-bit toggle is kind "flag" with alt_kinds ["counter"] in EVERY truth (the lead's decision
    of 2026-09-23, changes.jsonl T04): the rule text is one string, and no corpus design declares a
    width-1 counter, which schema v2.1's counter width >= 2 would make unverifiable by
    construction."""
    corpus = pytest.importorskip("tools.s3.corpus")
    tempo = pytest.importorskip("tools.s3.truth_tempo")
    assert corpus.TOGGLE_RULE == tempo.TOGGLE_RULE
    ds = corpus.designs()
    assert not [(d.name, r.name) for d in ds for r in d.regs if r.kind == "counter" and r.width == 1]
    toggles = [(d.name, r) for d in ds for r in d.regs if r.width == 1 and r.alt_reason == corpus.TOGGLE_RULE]
    assert toggles, "the corpus has no 1-bit toggle at all: the rule would be untested"
    for name, r in toggles:
        assert r.kind == "flag" and tuple(r.alt_kinds) == ("counter",), f"{name}.{r.name}"
        # the params are still checked as a counter's, so the corpus still proves it counts
        assert r.check_as == "counter" and r.params.get("modulus") == 2, f"{name}.{r.name}"


def test_params_mirrors_the_harness_extent_limits():
    """tools/s3/params.py's mirror of the two extent limits schema v2.1 added, and both fixed for
    every run (changes.jsonl I02, PV10).

    It lives HERE, beside the corpus toggle rule it is the counterpart of, because
    test_s3_verify.py's test_params_mirror_matches_the_harness -- where the other eleven HARNESS_*
    assertions are -- was outside the write list of the round that added these two, so nothing
    asserted them at all (the integration round's own remaining item 8)."""
    from tools.s3 import params as P
    assert P.HARNESS_COUNTER_MIN_WIDTH == V.COUNTER_MIN_WIDTH
    assert P.HARNESS_SYNC_MIN_STAGES == V.SYNC_MIN_STAGES
    for n in ("HARNESS_COUNTER_MIN_WIDTH", "HARNESS_SYNC_MIN_STAGES"):
        assert n in P.NOT_PER_RUN
        with pytest.raises(KeyError):
            P.resolve({n: getattr(P, n) + 1})


# ----------------------------------------------------------------------------------------------
# the freeze, the draw and the blind ledger


def _commit(g, msg):
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", msg)


def _mini_repo(tmp_path, candidates=5):
    root = tmp_path / "repo"
    (root / "tools" / "s3").mkdir(parents=True)
    (root / "tools" / "retrace").mkdir(parents=True)
    (root / "out" / "s3" / "blind").mkdir(parents=True)
    for name in ("recognize.py", "schema.py", "thirdparty.py"):
        shutil.copy(os.path.join(ROOT, "tools", "s3", name), root / "tools" / "s3" / name)
    (root / "tools" / "retrace" / "extract.py").write_text("# extractor\n")
    t = _toy_truth([("A", "counter", ["a0", "a1"], {})])
    (root / "out" / "s3" / "truth_toy.json").write_text(json.dumps(t))
    cands = [{"id": f"tt0{i}/tt_um_c{i}", "stratum": f"tt0{i % 2}"} for i in range(candidates)]
    doc = {"candidates": cands, "candidates_sha256": F.canonical_hash(cands)}
    (root / "out" / "s3" / "blind" / "candidates.json").write_text(json.dumps(doc))
    (root / "tools" / "s3" / "changes.jsonl").write_text(json.dumps(
        {"id": "C1", "date": "2026-09-22", "module": "tools/s3/x.py", "change": "test entry",
         "evidence": [{"path": "out/s3/x.json", "sha256": "0" * 64}]}) + "\n")
    (root / "out" / "s3" / "contamination.json").write_text(json.dumps({"schema": "test", "items": []}))
    g = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)  # noqa: E731
    g("init", "-q")
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base")
    return str(root), g


def _frozen_repo(tmp_path):
    root, g = _mini_repo(tmp_path)
    fr = F.write(root, candidates=os.path.join(root, "out", "s3", "blind", "candidates.json"), draw_n=2,
                 max_reserves=1)
    g("add", "tools", "out/s3/blind/candidates.json")
    g("add", "-f", F.FREEZE_REL, F.CONTAMINATION_REL)
    _commit(g, "freeze")
    return root, g, fr


def _drawn_truth(root, ident, design=None):
    t = _toy_truth([("B", "counter", ["b0", "b1"], {})], design=design or f"tt:{ident}")
    p = os.path.join(root, "out", "s3", f"truth_{S.design_id(ident)}.json")
    with open(p, "w") as f:
        json.dump(t, f)
    return p


@pytest.mark.skipif(shutil.which("git") is None, reason="git absent")
def test_freeze_detects_every_kind_of_change(tmp_path):
    """After the freeze commit the check holds; it then reports an uncommitted FREEZE.json, a
    changed, added or removed tools/s3 file, a changed extractor file, a changed frozen truth, a
    changed package version, and a hand-edited FREEZE.json."""
    root, g = _mini_repo(tmp_path)
    assert any("not committed" in b for b in F.check(root, F.write(root)))
    g("add", "tools")
    g("add", "-f", F.FREEZE_REL, F.CONTAMINATION_REL)
    _commit(g, "freeze")
    assert F.check(root) == []
    rec = os.path.join(root, "tools", "s3", "recognize.py")
    with open(rec, "a") as f:
        f.write("\n# tuned\n")
    assert any("changed after the freeze" in b for b in F.check(root))
    g("checkout", "--", "tools/s3/recognize.py")
    open(os.path.join(root, "tools", "s3", "extra.py"), "w").close()
    assert any("added after the freeze" in b for b in F.check(root))
    os.remove(os.path.join(root, "tools", "s3", "extra.py"))
    with open(os.path.join(root, "tools", "retrace", "extract.py"), "a") as f:
        f.write("# changed\n")
    assert any(b.startswith("extractor ") for b in F.check(root))
    g("checkout", "--", "tools/retrace/extract.py")
    tp = os.path.join(root, "out", "s3", "truth_toy.json")
    t = json.load(open(tp))
    t["registers"][0]["kind"] = "shift_register"
    open(tp, "w").write(json.dumps(t))
    assert any("truth_hash changed" in b for b in F.check(root))
    fr = F.load(root)
    fr["code"]["tools/s3/recognize.py"] = "0" * 64
    assert any("edited by hand" in b for b in F.check(root, fr))
    fr = F.load(root)
    fr["packages"]["numpy"] = "0.0.1"
    fr["freeze_hash"] = F.freeze_hash(fr)
    assert any(b.startswith("package numpy") for b in F.check(root, fr, require_commit=False))


@pytest.mark.skipif(shutil.which("git") is None, reason="git absent")
def test_freeze_pins_change_log_contamination_and_protocol(tmp_path, monkeypatch):
    """S3_DESIGN 4.4: a freeze needs the change log and the contamination record (write refuses
    without either, or with a malformed change log), records their hashes and the contamination
    record itself, and pins the evaluation protocol (K >= 5 permutations); after the freeze commit
    a changed change log, a changed contamination record or a changed protocol is a mismatch, and
    both records must be committed."""
    root, g = _mini_repo(tmp_path)
    cpath = os.path.join(root, F.CONTAMINATION_REL)
    lpath = os.path.join(root, F.CHANGES_REL)
    saved = open(lpath).read()
    open(lpath, "w").write('{"id": "C1", "date": "2026-09-22"}\n')
    with pytest.raises(SystemExit, match="malformed"):
        F.write(root)
    os.remove(lpath)
    with pytest.raises(SystemExit, match="changes.jsonl"):
        F.write(root)
    open(lpath, "w").write(saved)
    fr = F.write(root)
    assert fr["protocol"]["permutations_min"] >= 5 and fr["contamination"] == {"schema": "test", "items": []}
    assert set(fr["records"]) == {F.CHANGES_REL, F.CONTAMINATION_REL} and all(fr["records"].values())
    g("add", "tools")
    g("add", "-f", F.FREEZE_REL)
    assert any(F.CONTAMINATION_REL in b and "not committed" in b for b in F.check(root))
    g("add", "-f", F.CONTAMINATION_REL)
    _commit(g, "freeze")
    assert F.check(root) == []
    with open(lpath, "a") as f:
        f.write(json.dumps({"id": "C2", "date": "2026-09-23", "module": "m", "change": "late",
                            "evidence": [{"path": "p", "sha256": "1" * 64}]}) + "\n")
    assert any(F.CHANGES_REL in b and "changed after the freeze" in b for b in F.check(root))
    g("checkout", "--", F.CHANGES_REL)
    open(cpath, "w").write(json.dumps({"schema": "test", "items": ["edited"]}))
    bad = F.check(root)
    assert any(F.CONTAMINATION_REL in b and "changed" in b for b in bad) and any("differs from the record" in b
                                                                                 for b in bad)
    g("checkout", "--", F.CONTAMINATION_REL)
    assert F.check(root) == []
    monkeypatch.setitem(F.PROTOCOL, "permutations_min", 1)
    assert any("protocol" in b for b in F.check(root))


@pytest.mark.skipif(shutil.which("git") is None, reason="git absent")
def test_freeze_accepts_drawn_truths_only(tmp_path):
    """The blocker: a truth labelled after the freeze for a DRAWN design is accepted; one for a
    design outside the draw, one whose design field names another id, one recorded by another
    labeller, and any drawn truth once tools/s3/thirdparty.py has changed are refused. The draw
    size, reserves and strata are in FREEZE.json."""
    root, g, fr = _frozen_repo(tmp_path)
    assert fr["draw"]["n"] == 2 and fr["draw"]["max_reserves"] == 1 and sum(fr["draw"]["strata"].values()) == 5
    d = F.draw(fr, root)
    assert len(d["blind"]) == 2 and len(d["reserve"]) == 1
    all_ids = {f"tt0{i}/tt_um_c{i}" for i in range(5)}
    outside = sorted(all_ids - set(d["blind"]) - set(d["reserve"]))[0]
    p = _drawn_truth(root, d["blind"][0])
    assert F.check(root) == []
    p2 = _drawn_truth(root, d["reserve"][0])
    assert F.check(root) == []
    os.remove(p2)
    q = _drawn_truth(root, outside)
    assert any("not a drawn design" in b for b in F.check(root))
    os.remove(q)
    os.remove(p)
    _drawn_truth(root, d["blind"][1], design="tt:someone/else")
    assert any("its design" in b for b in F.check(root))
    t = json.load(open(os.path.join(root, "out", "s3", f"truth_{S.design_id(d['blind'][1])}.json")))
    t["design"] = f"tt:{d['blind'][1]}"
    t["meta"]["labeller_sha256"] = "f" * 64
    json.dump(t, open(os.path.join(root, "out", "s3", f"truth_{S.design_id(d['blind'][1])}.json"), "w"))
    assert any("labelled by another" in b for b in F.check(root))
    os.remove(os.path.join(root, "out", "s3", f"truth_{S.design_id(d['blind'][1])}.json"))
    _drawn_truth(root, d["blind"][0])
    with open(os.path.join(root, "tools", "s3", "thirdparty.py"), "a") as f:
        f.write("\n# relabel\n")
    bad = F.check(root)
    assert any("labeller" in b for b in bad) and any("thirdparty.py: changed" in b for b in bad)


@pytest.mark.skipif(shutil.which("git") is None, reason="git absent")
def test_blind_ledger_survives_deletion_and_blocks_refreeze(tmp_path):
    """A blind attempt goes to the hash-chained ledger; once committed, deleting both the run
    record and the ledger file does not erase it (blind_results reads the git history), so a
    second attempt still needs a reason and a new freeze is refused unless it records a
    --supersede reason (and the attempts). Uncommitted ledger lines are counted; an edited line
    breaks the chain."""
    root, g, fr = _frozen_repo(tmp_path)
    fh = fr["freeze_hash"]
    runs = os.path.join(root, F.RUNS_REL)
    os.makedirs(runs)
    recp = os.path.join(runs, "blind-toy-20260101T000000Z-abc.attempt.json")
    json.dump({"design": "toy", "freeze": {"freeze_hash": fh}}, open(recp, "w"))
    F.ledger_append({"event": "attempt", "attempt": "a1", "design": "toy", "freeze_hash": fh,
                     "record": os.path.relpath(recp, root)}, root)
    assert F.ledger_uncommitted(root) == 1
    g("add", "-f", F.LEDGER_REL)
    _commit(g, "ledger")
    assert F.ledger_uncommitted(root) == 0
    assert F.blind_results("toy", fh, root)
    os.remove(recp)
    os.remove(os.path.join(root, F.LEDGER_REL))
    assert F.blind_results("toy", fh, root), "the attempt must survive in the ledger's git history"
    with pytest.raises(SystemExit):
        F.write(root, force=True)
    os.remove(os.path.join(root, F.FREEZE_REL))
    with pytest.raises(SystemExit, match="blind attempts exist"):
        F.write(root)
    fr2 = F.write(root, supersede="test: re-freeze after a harness bug")
    assert fr2["supersedes"]["reason"].startswith("test") and fr2["supersedes"]["attempts"]
    g("checkout", "--", F.LEDGER_REL)
    F.ledger_append({"event": "finish", "attempt": "a1"}, root)
    lines = open(os.path.join(root, F.LEDGER_REL)).read().splitlines()
    lines[0] = lines[0].replace('"a1"', '"a2"')
    open(os.path.join(root, F.LEDGER_REL), "w").write("\n".join(lines) + "\n")
    assert any("hash chain broken" in p for p in F.ledger_entries(root)[1])


def test_blind_results_match_the_design_exactly(tmp_path):
    """blind_results for design "tt" does not pick up a record of design "tt-a"."""
    root = str(tmp_path)
    runs = os.path.join(root, F.RUNS_REL)
    os.makedirs(runs)
    json.dump({"design": "tt-a", "freeze": {"freeze_hash": "f"}}, open(os.path.join(runs, "blind-tt-a-1-x.json"), "w"))
    assert F.blind_results("tt", "f", root) == []
    assert F.blind_results("tt-a", "f", root)


def test_netlist_hash_is_canonical(tmp_path):
    """The freeze's netlist hash: equal for two seed=None loads, different after a relabelling."""
    nl, _key = synthetic(tmp_path)
    nl_b, _k = synthetic(tmp_path)
    assert F.netlist_hash(nl) == F.netlist_hash(nl_b)
    assert F.netlist_hash(R.relabel(nl)[0]) != F.netlist_hash(nl)


def test_blind_run_refusals(monkeypatch):
    """run.py --blind stops before extraction when the freeze does not hold, when an attempt of the
    design already exists under the freeze (a record or a ledger entry) and no rerun reason is
    given, when the ledger has uncommitted entries, when a third-party design was not drawn, and
    when the process is not the re-executed `python -B -X pycache_prefix=... -m tools.s3.run`."""
    quiet = {"write": False, "echo": lambda *a: None}
    monkeypatch.setattr(R.freeze, "check", lambda *a, **k: ["code changed"])
    with pytest.raises(SystemExit, match="freeze does not hold"):
        R.run("puzzle", blind=True, **quiet)
    monkeypatch.setattr(R.freeze, "check", lambda *a, **k: [])
    monkeypatch.setattr(R.freeze, "load", lambda *a, **k: {"freeze_hash": "f" * 64, "truth": {"puzzle": {}}})
    monkeypatch.setattr(R.freeze, "blind_results", lambda *a, **k: ["ledger attempt x"])
    with pytest.raises(SystemExit, match="already has a blind attempt"):
        R.run("puzzle", blind=True, **quiet)
    monkeypatch.setattr(R.freeze, "blind_results", lambda *a, **k: [])
    monkeypatch.setattr(R.freeze, "ledger_uncommitted", lambda *a, **k: 2)
    with pytest.raises(SystemExit, match="uncommitted"):
        R.run("puzzle", blind=True, **quiet)
    monkeypatch.setattr(R.freeze, "ledger_uncommitted", lambda *a, **k: 0)
    monkeypatch.setattr(R.freeze, "drawn_ids", lambda *a, **k: {"tt01__tt_um_c1"})
    with pytest.raises(SystemExit, match="not among the designs drawn"):
        R.run("tt02__tt_um_c2", gds="/nonexistent.gds", blind=True, **quiet)
    with pytest.raises(SystemExit, match=r"-B|pycache|OS-level"):
        R.run("puzzle", blind=True, **quiet)
    assert R.clean_blind_process()   # this pytest process is not a clean blind process


def test_blind_cli_reexecutes_itself():
    """`python -m tools.s3.run --blind` re-executes itself as `python -B -X pycache_prefix=<fresh>
    -m tools.s3.run` before anything else; here the re-executed process then refuses because this
    working tree has no freeze (nothing is extracted)."""
    if F.load(ROOT) is not None:
        pytest.skip("a freeze exists in this tree")
    env = {k: v for k, v in os.environ.items() if k != R.BLIND_PYCACHE_ENV}
    code = ("import sys, os\nsys.argv = ['run', '--design', 'puzzle', '--blind']\n"
            "from tools.s3 import run\nrun.main()\n")
    p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode != 0 and "freeze does not hold" in p.stderr, p.stderr[-2000:]


def test_pending_truth_record_is_scored_later(tmp_path, monkeypatch):
    """The stronger blind ordering: a drawn design's run is recorded before its truth exists
    (result, harness verdicts, the netlist's flop keys and the structural baseline), and
    score_record scores it afterwards against the drawn truth, keeping the harness's verified
    flags; a record that is not pending, or from another freeze, is refused."""
    nl, key = synthetic(tmp_path)
    monkeypatch.setattr(R, "run_child", _fake_child(_syn_recognize))
    ev = R.evaluate(nl, key, None)
    assert "score" not in ev and ev["invalid_reasons"] == []
    rec = {"schema": R.RUN_SCHEMA, "design": "tt01__tt_um_syn", "created": "2026-09-22T00:00:00+00:00",
           "blind": True, "pending_truth": True, "valid": True, "invalid_reasons": [],
           "freeze": {"freeze_hash": "f" * 64}, "attempt": {"id": "a"}, "result": ev["result"],
           "verified_flags": ev["verified_flags"], "flop_keys": sorted(ev["flop_keys"]),
           "baseline_results": ev["baselines"]}
    path = tmp_path / "blind-tt01__tt_um_syn-x.json"
    path.write_text(json.dumps(rec))
    truth = _syn_truth()
    truth["design"] = "tt:tt01/tt_um_syn"
    (tmp_path / "truth_tt01__tt_um_syn.json").write_text(json.dumps(truth))
    monkeypatch.setattr(R.freeze, "check", lambda *a, **k: [])
    monkeypatch.setattr(R.freeze, "load", lambda *a, **k: {"freeze_hash": "f" * 64})
    monkeypatch.setattr(R, "clean_blind_process", lambda: [])
    out = R.score_record(str(path), echo=lambda *a: None, write=False, truth_dir=str(tmp_path))
    assert out["valid"] and out["join"]["truth_flops_in_netlist"] == 5
    ver = out["score"]["classes"]["verified"]["registers"]["strict"]["per_kind"]
    assert ver["shift_register"]["found"]["recall"] == 1.0 and out["score"]["result"]["verified"] == 2
    assert "structural" in out["score"]["baselines"]
    monkeypatch.setattr(R.freeze, "load", lambda *a, **k: {"freeze_hash": "0" * 64})
    with pytest.raises(SystemExit, match="another freeze"):
        R.score_record(str(path), echo=lambda *a: None, write=False, truth_dir=str(tmp_path))
    rec["pending_truth"] = False
    path.write_text(json.dumps(rec))
    with pytest.raises(SystemExit, match="not a blind record waiting"):
        R.score_record(str(path), echo=lambda *a: None, write=False, truth_dir=str(tmp_path))


def test_run_records_are_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "RUNS", str(tmp_path))
    rec = {"design": "toy", "created": "2026-09-21T00:00:00+00:00", "x": 1}
    p, _sha = R._write_record(rec, blind=True)
    with pytest.raises(FileExistsError):
        R._write_record(rec, blind=True)
    assert not os.access(p, os.W_OK) or os.geteuid() == 0
    q, _ = R._write_record(rec, blind=False, runs=str(tmp_path / "dev"))
    assert os.path.dirname(q) == str(tmp_path / "dev")
