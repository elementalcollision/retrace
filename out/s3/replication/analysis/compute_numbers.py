#!/usr/bin/env python3
"""S3 replication -- the ONE canonical computation of every figure docs/S3_REPLICATION.md may quote.

Helper, not frozen, read-only. Inputs (nothing else is read):
  * the ten Freeze-4 replication run records (set R) and the ten freeze-1 blind run records (set B1;
    the records whose freeze.freeze_hash is freeze 1's, the puzzle excluded) in out/s3/runs/, with their
    attempt records;
  * each record's truth, out/s3/truth_<id>.json;
  * the blind ledger out/s3/blind_ledger.jsonl (working tree and git history, via tools/s3/freeze.py's own
    reader), out/s3/FREEZE.json, and the replication labels out/s3/replication/labels.json (for the
    mechanics block only);
  * for block F only, the two references out/s3/honesty/holdout_rates.json and
    out/s3/honesty/honesty_table.json.
The frozen scorer tools/s3/score.py is imported as a LIBRARY (never modified, no bytecode written) to
recover per-register credit exactly as it scores: Truth, _structures, _register_level on each record's
permutation p1 with the record's own verdicts. Every per-kind block so recovered is asserted equal to the
record's own score block before any per-register figure is used.

The analysis plan is docs/S3_REPLICATION_PLAN.md (committed 95f7eff, before the seed existed). It fixes
the primary outcome, the interval method and the verdict words; this file follows it and states each
implementation choice the plan leaves open in numbers.json["definitions"].

Writes out/s3/replication/analysis/numbers.json and out/s3/replication/analysis/numbers.md.
Run: .venv/bin/python -B out/s3/replication/analysis/compute_numbers.py
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True   # never write bytecode under tools/ (the freeze covers that tree)

import collections  # noqa: E402
import datetime  # noqa: E402
import glob  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import statistics  # noqa: E402
import subprocess  # noqa: E402

import numpy as np  # noqa: E402

ROOT = "/Users/dave/Jane_Street_Reverse_ASIC"
OUT = os.path.join(ROOT, "out", "s3", "replication", "analysis")
RUNS = os.path.join(ROOT, "out", "s3", "runs")
sys.path.insert(0, ROOT)
from tools.s3 import freeze as FZ  # noqa: E402  frozen, read only (ledger readers)
from tools.s3 import schema  # noqa: E402  frozen, read only
from tools.s3 import score as S  # noqa: E402  frozen, read only

KINDS = ["counter", "shift_register", "lfsr_crc", "synchronizer"]     # report order
assert set(KINDS) == set(S.STRUCTURE_KINDS)
F1_HASH = "1ee6a47894359fefa10b0507ac610db6d19fb1426c6626b7162e5f977e5c4838"
F4_HASH = "1196c56304e3fdd8076345085860288b829228d8d47a84ca2e5909114c62b9bc"
F4_SEED = "36818e09a9555c29aa45b6917dbce15f"
BOOT_SEED = 20260923
BOOT_N = 10_000
ALPHA = 0.05

# the replication records, as the run agent reported them (design -> record basename), in run order
R_RECORDS = [
    ("tt04__tt_um_jayraj4021_SAP1_cpu", "blind-tt04__tt_um_jayraj4021_SAP1_cpu-20260923T162732Z-f054fba37113.json"),
    ("ttsky26b__tt_um_tiny_8bit_cpu", "blind-ttsky26b__tt_um_tiny_8bit_cpu-20260923T162838Z-ad288b805d1f.json"),
    ("tt06__tt_um_SJ", "blind-tt06__tt_um_SJ-20260923T163017Z-cb0653238382.json"),
    ("tt06__tt_um_kwilke_cdc_fifo", "blind-tt06__tt_um_kwilke_cdc_fifo-20260923T164118Z-2a71c3753920.json"),
    ("ttsky25b__tt_um_yorimichi_kittscanner",
     "blind-ttsky25b__tt_um_yorimichi_kittscanner-20260923T164224Z-26c058d662ee.json"),
    ("tt05__tt_um_digital_clock_sellicott", "blind-tt05__tt_um_digital_clock_sellicott-20260923T164430Z-0b3815420281.json"),
    ("tt05__tt_um_nickjhay_processor", "blind-tt05__tt_um_nickjhay_processor-20260923T164730Z-bb64c58cedec.json"),
    ("ttsky25b__tt_um_ieeeuoftasic_simproc",
     "blind-ttsky25b__tt_um_ieeeuoftasic_simproc-20260923T164846Z-96397bfe3677.json"),
    ("ttsky26a__tt_um_parakeet", "blind-ttsky26a__tt_um_parakeet-20260923T165027Z-5cbe0d76609a.json"),
    ("ttcad25a__tt_um_space_invaders_game", "blind-ttcad25a__tt_um_space_invaders_game-20260923T165200Z-120ddfb7dc8a.json"),
]

PC = "evaluations[label=p1].score"          # record-field prefix used in every "source" string


def rel(p):
    return os.path.relpath(p, ROOT)


def sha256_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load(p):
    with open(p) as f:
        return json.load(f)


def rate(a, b):
    return (a / b) if b else None


def fx(x, d=4):
    """Display form of a number (the JSON keeps the full float beside it)."""
    if x is None:
        return "n/a"
    if isinstance(x, float) and not math.isfinite(x):
        return str(x)
    return f"{x:.{d}f}"


def frac(num, den, source, **extra):
    """A figure: numerator, denominator, rate, and the record field it came from."""
    out = {"num": num, "den": den, "rate": rate(num, den), "rate_4dp": fx(rate(num, den)), "source": source}
    out.update(extra)
    return out


# ------------------------------------------------------------------------------------------------
# statistics: Fisher's exact test, Clopper-Pearson, the design-level cluster bootstrap


def fisher_exact_two_sided(a, b, c, d):
    """Two-sided Fisher exact p for [[a, b], [c, d]]: the sum of the hypergeometric probabilities of
    every table with the same margins whose probability is <= that of the observed table (relative
    tolerance 1e-7, the convention scipy.stats.fisher_exact uses). Exact integer arithmetic."""
    r1, r2, c1 = a + b, c + d, a + c
    n = r1 + r2
    lo, hi = max(0, c1 - r2), min(c1, r1)
    denom = math.comb(n, c1)
    probs = {x: math.comb(r1, x) * math.comb(r2, c1 - x) for x in range(lo, hi + 1)}
    pobs = probs[a]
    tot = sum(v for v in probs.values() if v <= pobs * (1 + 1e-7))
    return min(1.0, tot / denom)


def _binom_cdf(x, n, p):
    """P(X <= x), X ~ Binomial(n, p)."""
    if x < 0:
        return 0.0
    if x >= n:
        return 1.0
    return math.fsum(math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(0, x + 1))


def clopper_pearson(x, n, alpha=ALPHA):
    """Exact (Clopper-Pearson) two-sided 1-alpha interval for x successes of n, by bisection on the
    binomial tails (no scipy in this environment)."""
    if n == 0:
        return (None, None)

    def solve(f, target):          # f increasing in p on [0, 1]
        lo, hi = 0.0, 1.0
        for _ in range(200):
            mid = (lo + hi) / 2
            if f(mid) < target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    lower = 0.0 if x == 0 else solve(lambda p: 1.0 - _binom_cdf(x - 1, n, p), alpha / 2)   # P(X >= x) = a/2
    upper = 1.0 if x == n else solve(lambda p: 1.0 - _binom_cdf(x, n, p), 1 - alpha / 2)   # P(X <= x) = a/2
    return (lower, upper)


def _ratio_rows(num, den, idx):
    N = num[idx].sum(axis=1)
    D = den[idx].sum(axis=1)
    return N, D


def _pct(stat):
    if len(stat) == 0:
        return None, None
    lo, hi = np.percentile(stat, [2.5, 97.5])
    return float(lo), float(hi)


def _se(stat):
    return float(stat.std(ddof=1)) if len(stat) > 1 else None


def _iv(lo, hi):
    return f"[{fx(lo)}, {fx(hi)}]"


def boot_one(num, den):
    """One set: resample its designs with replacement; the pooled ratio sum(num)/sum(den)."""
    num, den = np.asarray(num, float), np.asarray(den, float)
    rng = np.random.default_rng(BOOT_SEED)
    idx = rng.integers(0, len(num), size=(BOOT_N, len(num)))
    N, D = _ratio_rows(num, den, idx)
    ok = D > 0
    st = N[ok] / D[ok]
    lo, hi = _pct(st)
    return {"lo": lo, "hi": hi, "interval_4dp": _iv(lo, hi), "resamples": BOOT_N,
            "undefined_resamples_dropped": int((~ok).sum()), "bootstrap_se": _se(st)}


def boot_two(numB, denB, numR, denR):
    """Two sets resampled independently (B1 matrix drawn first, then R, from one fresh generator):
    returns the R - B1 difference and the stratified pooled ratio from the SAME resamples."""
    numB, denB, numR, denR = (np.asarray(x, float) for x in (numB, denB, numR, denR))
    rng = np.random.default_rng(BOOT_SEED)
    iB = rng.integers(0, len(numB), size=(BOOT_N, len(numB)))
    iR = rng.integers(0, len(numR), size=(BOOT_N, len(numR)))
    NB, DB = _ratio_rows(numB, denB, iB)
    NR, DR = _ratio_rows(numR, denR, iR)
    okd = (DB > 0) & (DR > 0)
    diff = NR[okd] / DR[okd] - NB[okd] / DB[okd]
    okp = (DB + DR) > 0
    pooled = (NB[okp] + NR[okp]) / (DB[okp] + DR[okp])
    dlo, dhi = _pct(diff)
    plo, phi = _pct(pooled)
    return ({"lo": dlo, "hi": dhi, "interval_4dp": _iv(dlo, dhi), "resamples": BOOT_N,
             "undefined_resamples_dropped": int((~okd).sum()), "bootstrap_se": _se(diff)},
            {"lo": plo, "hi": phi, "interval_4dp": _iv(plo, phi), "resamples": BOOT_N,
             "undefined_resamples_dropped": int((~okp).sum()), "bootstrap_se": _se(pooled)})


def verdict_word(lo, hi):
    """docs/S3_REPLICATION_PLAN.md, fixed before the draw: 'consistent with freeze 1' if the 95%
    bootstrap interval of R - B1 contains 0; otherwise 'higher' or 'lower'."""
    if lo <= 0.0 <= hi:
        return "consistent with freeze 1"
    return "higher" if lo > 0.0 else "lower"


def full_comparison(label, num_field, rowsB, rowsR, numkey, denkey="den"):
    """R alone, B1 alone, R - B1 and pooled B1+R (stratified; plus the 20-design one-set sensitivity),
    each with the cluster bootstrap; Fisher and Clopper-Pearson beside, labelled."""
    nB = [r[numkey] for r in rowsB]
    dB = [r[denkey] for r in rowsB]
    nR = [r[numkey] for r in rowsR]
    dR = [r[denkey] for r in rowsR]
    xB, NB, xR, NR = sum(nB), sum(dB), sum(nR), sum(dR)
    bR = boot_one(nR, dR)
    bB = boot_one(nB, dB)
    bD, bP = boot_two(nB, dB, nR, dR)
    bS = boot_one(nB + nR, dB + dR)
    rR, rB = rate(xR, NR), rate(xB, NB)
    p = fisher_exact_two_sided(xR, NR - xR, xB, NB - xB)
    cpR, cpB, cpP = clopper_pearson(xR, NR), clopper_pearson(xB, NB), clopper_pearson(xR + xB, NR + NB)
    out = {
        "what": label, "record_field": num_field,
        "R": frac(xR, NR, num_field, designs=len(rowsR), designs_with_registers=sum(1 for x in dR if x),
                  bootstrap_95=bR),
        "B1": frac(xB, NB, num_field, designs=len(rowsB), designs_with_registers=sum(1 for x in dB if x),
                   bootstrap_95=bB),
        "R_minus_B1": {"difference": rR - rB, "difference_4dp": fx(rR - rB), "bootstrap_95": bD},
        "pooled_B1_plus_R": frac(xR + xB, NR + NB, num_field, designs=len(rowsR) + len(rowsB),
                                 bootstrap_95_stratified=bP,
                                 bootstrap_95_sensitivity_20_designs_as_one_set=bS),
        "independence_assuming_comparison": {
            "label": "the independence-assuming comparison the first report used (registers treated as independent "
                     "trials; registers inside one design are not independent, so the p-value is anti-conservative "
                     "and the intervals are a floor). Not the primary interval.",
            "fisher_exact_two_sided_p_R_vs_B1": p,
            "table_[[R_hit,R_miss],[B1_hit,B1_miss]]": [[xR, NR - xR], [xB, NB - xB]],
            "clopper_pearson_95_R": list(cpR), "clopper_pearson_95_B1": list(cpB),
            "clopper_pearson_95_pooled": list(cpP),
            "clopper_pearson_95_R_4dp": f"[{fx(cpR[0])}, {fx(cpR[1])}]",
            "clopper_pearson_95_B1_4dp": f"[{fx(cpB[0])}, {fx(cpB[1])}]",
            "clopper_pearson_95_pooled_4dp": f"[{fx(cpP[0])}, {fx(cpP[1])}]"},
        "per_design_R": rowsR, "per_design_B1": rowsB,
    }
    return out


# ------------------------------------------------------------------------------------------------
# records


def freeze_check():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([os.path.join(ROOT, ".venv", "bin", "python"), "-B", "-m", "tools.s3.freeze", "check"],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    return {"stdout": p.stdout.strip(), "stderr_tail": p.stderr.strip()[-500:], "returncode": p.returncode,
            "holds": p.stdout.strip() == "freeze holds"}


def p1(rec):
    evs = [e for e in rec["evaluations"] if e.get("label") == "p1"]
    assert len(evs) == 1, rec["design"]
    return evs[0]


def discover(fhash, exclude=("puzzle",)):
    out = []
    for p in sorted(glob.glob(os.path.join(RUNS, "blind-*.json"))):
        if p.endswith(".attempt.json"):
            continue
        d = load(p)
        if (d.get("freeze") or {}).get("freeze_hash") == fhash and d.get("design") not in exclude:
            out.append((d["created"], d["design"], p))
    return sorted(out)


def tier_of(reg):
    """docs/S3.md section 4, exactly as freeze 1's analysis computed it (out/s3/blind/analysis/
    audit_labels.py reg_weakness + build_labels.py tier): over the register's truth bits that carry a
    netlist flop, a bit whose z3 mapping proof is not 'proven' or whose random-simulation check is not
    'match' (an absent field counts as not proven / not matching) makes the register Tier A
    ('A_contradicted'); otherwise a bit with no netlist flop makes it Tier B ('B_narrowed'); otherwise
    'C_clean'. Sub-tier (write_labels.py's A1/A2): A1 when at least one mapped bit is not 'match' in
    simulation, else A2 (z3 not proven while simulation agreed)."""
    proof, check, no_flop = collections.Counter(), collections.Counter(), 0
    for b in reg["bits"]:
        if b.get("flop") is None:
            no_flop += 1
            continue
        proof[b.get("proof") or "(absent)"] += 1
        check[b.get("check") or "(absent)"] += 1
    unproven = sum(v for k, v in proof.items() if k != "proven")
    unmatched = sum(v for k, v in check.items() if k != "match")
    if unproven or unmatched:
        t = "A_contradicted"
        sub = "A1_simulation_mismatch" if unmatched else "A2_z3_refuted_only"
    elif no_flop:
        t = sub = "B_narrowed"
    else:
        t = sub = "C_clean"
    return {"tier": t, "subtier": sub, "bits": len(reg["bits"]), "bits_with_flop": len(reg["bits"]) - no_flop,
            "bits_without_flop": no_flop, "unproven_bits": unproven, "mismatching_bits": unmatched,
            "proof": dict(proof), "check": dict(check)}


def rescore(truth, ev):
    """Per-register credit, recovered with the frozen scorer's own functions on the record's p1 answer and
    verdicts (score.score's call: Truth(truth), _structures(T, result, verified_flags, outcomes, verdicts),
    _register_level per class and mode). The credit rule below is _register_level's, line for line."""
    T = S.Truth(truth)
    verdicts = ev["verify"]["structures"]
    structs, _info = S._structures(T, ev["result"], ev["verified_flags"], ev["outcomes"], verdicts)
    res = {}
    for sub, sel in (("all", structs), ("verified", [s for s in structs if s["verified"]])):
        for mode, lenient in (("strict", False), ("lenient", True)):
            rep, m = S._register_level(T, sel, lenient)
            credit, smatch = {}, {}
            for s, it, iou, regs in m:
                ok = s["kind"] in it["accepts"]
                ex = ok and s["flops"] == it["flops"] and not s["dropped"]
                got = [r for r in regs if r in it["credit"]] if it["unit"] else regs
                ok = ok and bool(got)
                smatch[s["pos"]] = {"item": it["name"], "item_kind": it["kind"], "unit": it["unit"], "iou": iou,
                                    "found": ok, "exact": bool(ex and ok), "registers": list(regs)}
                if ok:
                    for r in got:
                        credit[r] = {"exact": bool(ex), "iou": iou, "pos": s["pos"], "structure": s["id"],
                                     "structure_kind": s["kind"], "via": it["name"] if it["unit"] else None}
            res[(sub, mode)] = {"rep": rep, "m": m, "credit": credit, "smatch": smatch}
    return T, structs, res


def design_data(set_name, path):
    rec = load(path)
    ev = p1(rec)
    sc = ev["score"]
    tpath = os.path.join(ROOT, rec["truth"]["path"])
    truth = load(tpath)
    T, structs, res = rescore(truth, ev)
    checks = {}
    # the recovered per-kind blocks must equal the record's own
    for (sub, mode), v in res.items():
        mine = json.dumps(v["rep"]["per_kind"], sort_keys=True)
        theirs = json.dumps(sc["classes"][sub]["registers"][mode]["per_kind"], sort_keys=True)
        checks[f"{sub}/{mode}"] = mine == theirs
    assert all(checks.values()), (rec["design"], checks)
    # every permutation gives the same per-kind counts (each design contributes once, from p1)
    def sig(e):
        s = e["score"]
        return json.dumps({f"{sub}/{mode}/{c}": [s["classes"][sub]["registers"][mode]["per_kind"][c][k] if k in
                                                ("registers", "structures") else
                                                s["classes"][sub]["registers"][mode]["per_kind"][c][k]["registers_found"]
                                                for k in ("registers", "structures", "found", "exact")]
                           for sub in ("all", "verified") for mode in ("strict", "lenient") for c in KINDS},
                          sort_keys=True)
    perm_same = len({sig(e) for e in rec["evaluations"]}) == 1
    truth_hash_disk = schema.truth_hash(truth)
    return {"set": set_name, "design": rec["design"], "path": path, "rec": rec, "ev": ev, "sc": sc, "truth": truth,
            "truth_path": tpath, "T": T, "structs": structs, "res": res, "rescore_equals_record": checks,
            "per_kind_counts_identical_across_permutations": perm_same,
            "truth_hash": {"record": rec["truth"]["truth_hash"], "score_block": sc["truth_hash"],
                           "disk": truth_hash_disk,
                           "agree": rec["truth"]["truth_hash"] == sc["truth_hash"] == truth_hash_disk}}


# ------------------------------------------------------------------------------------------------
# per-register rows (strict), tiers, misses, false positives, found-but-unverified


def iou(a, b):
    u = len(a | b)
    return len(a & b) / u if u else 0.0


def register_rows(D):
    T, res = D["T"], D["res"]
    a_s, v_s = res[("all", "strict")]["credit"], res[("verified", "strict")]["credit"]
    a_l, v_l = res[("all", "lenient")]["credit"], res[("verified", "lenient")]["credit"]
    rows = []
    for c in KINDS:
        for n in T.denominators(c):
            a, v = a_s.get(n), v_s.get(n)
            t = tier_of(T.regs[n])
            rows.append({"design": D["design"], "kind": c, "register": n, "flops": len(T.flops[n]),
                         "found": a is not None, "exact": bool(a and a["exact"]), "iou": a["iou"] if a else None,
                         "structure": a["structure"] if a else None, "via_unit": a["via"] if a else None,
                         "verified_found": v is not None, "verified_exact": bool(v and v["exact"]),
                         "lenient_found": n in a_l, "lenient_verified_found": n in v_l,
                         "lenient_via_unit": a_l[n]["via"] if n in a_l else None,
                         "lenient_structure": a_l[n]["structure"] if n in a_l else None,
                         "design_key": T.design_key(n), **t})
    return rows


def found_unverified(D, rows):
    """Registers the all-structures strict pass credits and the verified-only strict pass does not, with the
    verify.py verdict of the structure that took them in the all-structures pass."""
    out = []
    verdicts = D["ev"]["verify"]["structures"]
    by_pos = {s["pos"]: s for s in D["structs"]}
    credit = D["res"][("all", "strict")]["credit"]
    for r in rows:
        if r["found"] and not r["verified_found"]:
            cr = credit[r["register"]]
            s = by_pos[cr["pos"]]
            vd = verdicts[cr["pos"]] if cr["pos"] < len(verdicts) else {}
            reason = vd.get("reason") or ""
            if S._bucket(s) == "hold" and "is not claimed" in reason:
                cause = "V1 control.hold not claimed"
            elif S._bucket(s) == "vacuous" and "the hold region is empty only once control.load is conjoined in" \
                    in reason:
                cause = "V2 hold region emptied only by the opaque load cases (HOLD_EMPTY_NEEDS_VERIFIED_COVER (a))"
            else:
                cause = "other: " + S._bucket(s)
            out.append({"design": D["design"], "kind": r["kind"], "register": r["register"], "flops": r["flops"],
                        "structure": cr["structure"], "iou": cr["iou"], "exact": cr["exact"],
                        "bucket": S._bucket(s), "verify_reason": reason, "cause": cause, "tier": r["tier"]})
    return out


def misses(D, rows):
    """Every strict miss, mechanically: matched at IoU > 0.5 by a structure whose kind the truth refuses
    (and which kind), or matched by nothing (best IoU of any structure <= 0.5, or > 0.5 but that
    structure was taken by another item in the one-to-one matching)."""
    out = []
    m = D["res"][("all", "strict")]["m"]
    structs = D["structs"]
    for r in rows:
        if r["found"]:
            continue
        n = r["register"]
        hit = [(s, it, iu) for s, it, iu, regs in m if it["name"] == n or (it["unit"] and n in it["registers"])]
        fl = D["T"].flops[n]
        best = max(((iou(s["flops"], fl), s) for s in structs), key=lambda x: x[0], default=(0.0, None))
        if hit:
            s, it, iu = hit[0]
            cat = ("matched, kind refused: unscored kind" if s["kind"] not in S.STRUCTURE_KINDS
                   else "matched, kind refused: scored kind")
            out.append({"design": D["design"], "kind": r["kind"], "register": n, "flops": r["flops"], "category": cat,
                        "structure": s["id"], "structure_kind": s["kind"], "iou": iu, "structure_verified": s["verified"],
                        "tier": r["tier"]})
        else:
            bi, bs = best
            cat = "matched by nothing (best IoU <= 0.5)" if bi <= S.IOU_MIN else \
                "matched by nothing (a structure over IoU 0.5 was taken by another item)"
            out.append({"design": D["design"], "kind": r["kind"], "register": n, "flops": r["flops"], "category": cat,
                        "best_iou_any_structure": bi, "best_structure_kind": bs["kind"] if bs else None,
                        "tier": r["tier"]})
    return out


def false_positives(D):
    """Every scored-kind structure the all-structures strict pass does not credit, mechanically: matched an item
    whose kind the truth refuses (which truth kind), or matched nothing (the truth kind of the register with the
    largest IoU over it). Verified or refused, with the verify.py bucket."""
    out = []
    T = D["T"]
    sm = D["res"][("all", "strict")]["smatch"]
    for s in D["structs"]:
        if s["kind"] not in S.STRUCTURE_KINDS:
            continue
        x = sm.get(s["pos"])
        if x and x["found"]:
            continue
        best = max(((iou(s["flops"], T.flops[n]), n) for n in T.scored), key=lambda z: z[0], default=(0.0, None))
        row = {"design": D["design"], "structure": s["id"], "kind": s["kind"], "flops": len(s["flops"]),
               "verified": s["verified"], "bucket": S._bucket(s)}
        if x:
            row.update(category=f"matched a truth {x['item_kind']} {'unit' if x['unit'] else 'register'} "
                                "(kind refused)", matched_item=x["item"], matched_item_kind=x["item_kind"],
                       iou=x["iou"])
        else:
            row.update(category="matched nothing", best_register=best[1], best_register_kind=T.kind.get(best[1]),
                       best_iou=best[0])
        out.append(row)
    return out


def verified_list(D):
    """Every harness-VERIFIED structure of the design with what it certifies and what it earned (strict,
    all-structures pass)."""
    out = []
    sm = D["res"][("all", "strict")]["smatch"]
    for s in D["structs"]:
        if not s["verified"]:
            continue
        vd = s["verdict"] or {}
        x = sm.get(s["pos"]) or {}
        out.append({"design": D["design"], "structure": s["id"], "kind": s["kind"], "flops": len(s["flops"]),
                    "credited": bool(x.get("found")), "matched_item": x.get("item"),
                    "matched_item_kind": x.get("item_kind"), "iou": x.get("iou"), "exact": bool(x.get("exact")),
                    "load_hidden_share": vd.get("load_hidden_share"), "hold_vacuous": vd.get("hold_vacuous"),
                    "load_cases": vd.get("load_cases"),
                    "params_checked": sorted(vd.get("params_checked") or []),
                    "params_unchecked": sorted(vd.get("params_unchecked") or [])})
    return out


def flop_evidence(D):
    """Distinct netlist flops in the scored structure-kind registers; how many carry a refuted mapping proof
    and how many of those also mismatch in simulation (docs/S3.md section 4's flop-level figures)."""
    T = D["T"]
    seen, refuted, both = set(), set(), set()
    for c in KINDS:
        for n in T.denominators(c):
            for b in T.regs[n]["bits"]:
                f = b.get("flop")
                if f is None:
                    continue
                seen.add(f)
                if b.get("proof") == "refuted":
                    refuted.add(f)
                    if b.get("check") == "mismatch":
                        both.add(f)
    return {"flops": len(seen), "mapping_proof_refuted": len(refuted), "refuted_and_simulation_mismatch": len(both)}


# ------------------------------------------------------------------------------------------------
# aggregation


def pk(D, cls, mode, c):
    return D["sc"]["classes"][cls]["registers"][mode]["per_kind"][c]


def kind_block(Ds, c, cls, mode):
    """Micro pooling over designs (raw counts summed, rate taken once), as docs/S3.md 5.1."""
    t = collections.Counter()
    iou_sum = 0.0
    per_design_recall = []
    for D in Ds:
        x = pk(D, cls, mode, c)
        t["registers"] += x["registers"]
        t["structures"] += x["structures"]
        t["found"] += x["found"]["registers_found"]
        t["structures_matched"] += x["found"]["structures_matched"]
        t["exact"] += x["exact"]["registers_found"]
        t["exact_structures_matched"] += x["exact"]["structures_matched"]
        t["found_iou75"] += x["found_iou75"]["registers_found"]
        t["excused_registers"] += x["excused"]["registers"]
        t["excused_found"] += x["excused"]["found"]
        t["design_keys"] += x["distinct_designs"]["total"]
        t["design_keys_found_all"] += x["distinct_designs"]["found_all"]
        t["design_keys_found_any"] += x["distinct_designs"]["found_any"]
        t["design_keys_exact_all"] += x["distinct_designs"]["exact_all"]
        t["designs_with_any"] += x["registers"] > 0
        t["designs_with_structures"] += x["structures"] > 0
        if x["mean_iou_found"] is not None:
            iou_sum += x["mean_iou_found"] * x["found"]["registers_found"]
        if x["registers"]:
            per_design_recall.append(x["found"]["registers_found"] / x["registers"])
    src = f"{PC}.classes.{cls}.registers.{mode}.per_kind.{c}"
    p = rate(t["structures_matched"], t["structures"])
    r = rate(t["found"], t["registers"])
    return {
        "registers": t["registers"], "designs_with_any": t["designs_with_any"],
        "designs_with_structures_of_the_kind": t["designs_with_structures"],
        "structures": t["structures"],
        "found": frac(t["found"], t["registers"], src + ".found.registers_found / .registers"),
        "exact": frac(t["exact"], t["registers"], src + ".exact.registers_found / .registers"),
        "found_iou75": frac(t["found_iou75"], t["registers"], src + ".found_iou75.registers_found / .registers"),
        "precision_over_structures": frac(t["structures_matched"], t["structures"],
                                          src + ".found.structures_matched / .structures"),
        "exact_precision_over_structures": frac(t["exact_structures_matched"], t["structures"],
                                                src + ".exact.structures_matched / .structures"),
        "f1_mixed_precision_structures_recall_registers": (2 * p * r / (p + r)) if (p is not None and r is not None
                                                                                    and p + r) else None,
        "false_positive_structures": t["structures"] - t["structures_matched"],
        "mean_iou_over_found": (iou_sum / t["found"]) if t["found"] else None,
        "macro_found_recall_over_designs_with_any": (statistics.fmean(per_design_recall)
                                                     if per_design_recall else None),
        "excused_registers": t["excused_registers"], "excused_found": t["excused_found"],
        "distinct_design_keys": {"total": t["design_keys"], "found_all": t["design_keys_found_all"],
                                 "found_any": t["design_keys_found_any"], "exact_all": t["design_keys_exact_all"]},
        "small_support_flag_score_py": t["registers"] < S.SMALL_SUPPORT,
    }


def kind_tables(Ds):
    out = {}
    for c in KINDS:
        out[c] = {f"{cls}/{mode}": kind_block(Ds, c, cls, mode)
                  for cls in ("all", "verified") for mode in ("strict", "lenient")}
        a, al = out[c]["all/strict"], out[c]["all/lenient"]
        v, vl = out[c]["verified/strict"], out[c]["verified/lenient"]

        def _nums(x):
            return [x["registers"], x["structures"], x["found"]["num"], x["exact"]["num"],
                    x["precision_over_structures"]["num"], x["exact_precision_over_structures"]["num"],
                    x["found_iou75"]["num"], x["excused_registers"], x["excused_found"]]
        out[c]["strict_equals_lenient_counts"] = _nums(a) == _nums(al) and _nums(v) == _nums(vl)
        out[c]["strict_equals_lenient_rule"] = ("registers, structures, found, exact, structures matched (found and "
                                                "exact), found@IoU>=0.75, excused: all/strict == all/lenient and "
                                                "verified/strict == verified/lenient")
        # the headline columns of docs/S3.md 5.1, side by side (verified-found is over the same registers)
        out[c]["summary"] = {
            "registers": a["registers"], "designs_with_any": a["designs_with_any"],
            "structures": a["structures"], "verified_structures": v["structures"],
            "found": a["found"]["num"], "found_recall": a["found"]["rate"],
            "verified_found": v["found"]["num"], "verified_found_recall": v["found"]["rate"],
            "exact": a["exact"]["num"], "exact_recall": a["exact"]["rate"],
            "verified_exact": v["exact"]["num"], "verified_exact_recall": v["exact"]["rate"],
            "precision_over_structures": a["precision_over_structures"]["rate"],
            "verified_precision_over_verified_structures": v["precision_over_structures"]["rate"],
            "false_positive_structures": a["false_positive_structures"],
            "verified_false_positive_structures": v["false_positive_structures"]}
    tot = collections.Counter()
    for c in KINDS:
        a, v = out[c]["all/strict"], out[c]["verified/strict"]
        tot.update(registers=a["registers"], structures=a["structures"], found=a["found"]["num"],
                   matched=a["precision_over_structures"]["num"], exact=a["exact"]["num"],
                   ematched=a["exact_precision_over_structures"]["num"],
                   vstructures=v["structures"], vfound=v["found"]["num"], vmatched=v["precision_over_structures"]["num"],
                   vexact=v["exact"]["num"])
    src = f"{PC}.classes.<all|verified>.registers.strict.per_kind.<kind>, summed over the four kinds"

    def _f1(tp_p, npred, tp_r, nsup):
        """score._prf's F1: None only when there is neither support nor a prediction; 0.0 when P + R = 0."""
        if not npred and not nsup:
            return None
        pp = tp_p / npred if npred else 0.0
        rr = tp_r / nsup if nsup else 0.0
        return 2 * pp * rr / (pp + rr) if pp + rr else 0.0

    per_f1 = {c: (_f1(out[c]["all/strict"]["precision_over_structures"]["num"], out[c]["all/strict"]["structures"],
                      out[c]["all/strict"]["found"]["num"], out[c]["all/strict"]["registers"]),
                  _f1(out[c]["all/strict"]["exact_precision_over_structures"]["num"],
                      out[c]["all/strict"]["structures"], out[c]["all/strict"]["exact"]["num"],
                      out[c]["all/strict"]["registers"])) for c in KINDS}
    f_sc = [v[0] for v in per_f1.values() if v[0] is not None]
    e_sc = [v[1] for v in per_f1.values() if v[1] is not None]
    f_doc = [v[0] for v in per_f1.values() if v[0]]          # docs/S3.md: kinds whose P and R are both 0 left out
    e_doc = [v[1] for c, v in per_f1.items() if per_f1[c][0]]
    out["all_four_kinds_strict"] = {
        "registers": tot["registers"], "structures": tot["structures"], "verified_structures": tot["vstructures"],
        "found": frac(tot["found"], tot["registers"], src),
        "verified_found": frac(tot["vfound"], tot["registers"], src),
        "exact": frac(tot["exact"], tot["registers"], src),
        "verified_exact": frac(tot["vexact"], tot["registers"], src),
        "precision_over_structures": frac(tot["matched"], tot["structures"], src),
        "exact_precision_over_structures": frac(tot["ematched"], tot["structures"], src),
        "verified_precision": frac(tot["vmatched"], tot["vstructures"], src),
        "false_positive_structures": tot["structures"] - tot["matched"],
        "verified_false_positive_structures": tot["vstructures"] - tot["vmatched"],
        "micro_f1_found": _f1(tot["matched"], tot["structures"], tot["found"], tot["registers"]),
        "micro_f1_exact": _f1(tot["ematched"], tot["structures"], tot["exact"], tot["registers"]),
        "per_kind_f1_found_exact": {c: {"found": v[0], "exact": v[1]} for c, v in per_f1.items()},
        "macro_f1_found_score_py_convention": statistics.fmean(f_sc) if f_sc else None,
        "macro_f1_exact_score_py_convention": statistics.fmean(e_sc) if e_sc else None,
        "macro_f1_found_docs_S3_convention": statistics.fmean(f_doc) if f_doc else None,
        "macro_f1_exact_docs_S3_convention": statistics.fmean(e_doc) if e_doc else None,
        "f1_conventions": "micro: pooled P (structures matched / structures) and R (registers credited / registers) "
                          "over the four kinds. Macro, score.py convention: mean of per-kind F1 over kinds with "
                          "registers or structures, F1 = 0 when P + R = 0. Macro, docs/S3.md 5.1 convention: kinds "
                          "whose found P and R are both 0 are left out (the same kinds for exact)."}
    return out


def honesty_block(Ds):
    t = collections.Counter()
    reasons = collections.Counter()
    per_kind_reasons = {c: collections.Counter() for c in KINDS}
    per_kind_unverified = collections.Counter()
    fnv = collections.Counter()
    vnf = collections.Counter()
    share_sum = share_n = 0.0
    share_max = None
    share_all_sum = share_all_n = 0.0
    peak_conf = peak_cov = 0
    outcomes = collections.Counter()
    for D in Ds:
        sc, ev = D["sc"], D["ev"]
        hv = sc["honesty"]["verified"]
        t["structures_returned"] += sc["result"]["structures"]
        t["structures_scored"] += sc["result"]["structures_scored"]
        t["claimed_proven_score"] += sc["result"]["claimed_proven"]
        t["verified"] += sc["result"]["verified"]
        vs = ev["verify"]["summary"]
        t["verify_claimed_proven"] += vs.get("claimed_proven", 0)
        t["verify_verified_not_claimed_proven"] += vs.get("verified_not_claimed_proven", 0)
        t["verify_hold_emptied_by_load"] += vs.get("hold_emptied_by_load", 0)
        for k in ("vacuous_hold", "with_unchecked_params", "with_dead_bits", "without_a_liveness_obligation",
                  "lfsr_poly_certified", "lfsr_structures", "with_a_load_case", "with_only_certified_params",
                  "liveness_checked", "hold_claimed"):
            t[k] += hv.get(k, 0)
        lh, la = hv["load_hidden_share"], hv["load_hidden_share_over_all_verified"]
        if lh["n"]:
            share_sum += lh["mean"] * lh["n"]
            share_n += lh["n"]
            share_max = lh["max"] if share_max is None else max(share_max, lh["max"])
        if la["n"]:
            share_all_sum += la["mean"] * la["n"]
            share_all_n += la["n"]
        reasons.update(sc["honesty"]["unverified_reasons"])
        for c in KINDS:
            hk = sc["honesty"]["per_kind"][c]
            per_kind_reasons[c].update(hk["unverified_reasons"])
            per_kind_unverified[c] += hk["unverified_structures"]
            fnv[c] += hk["found_not_verified_registers"]
            vnf[c] += hk["verified_not_found_registers"]
        peak_conf = max(peak_conf, vs.get("conflicts_used", 0) or 0)
        peak_cov = max(peak_cov, vs.get("coverage_calls_used", 0) or 0)
        outcomes.update(ev["outcomes"])
    lim = Ds[0]["ev"]["verify"]["limits"]
    return {
        "source": f"{PC}.result, {PC}.honesty, evaluations[p1].verify.summary / .limits / outcomes",
        "structures_returned": t["structures_returned"], "structures_scored": t["structures_scored"],
        "verified_structures": t["verified"], "claimed_proven_score_py": t["claimed_proven_score"],
        "claimed_proven_verify_py": t["verify_claimed_proven"],
        "verified_not_claimed_proven": t["verify_verified_not_claimed_proven"],
        "hold_emptied_by_load_verify_summary": t["verify_hold_emptied_by_load"],
        "verified_vacuous_hold": t["vacuous_hold"], "verified_with_unchecked_params": t["with_unchecked_params"],
        "verified_with_only_certified_params": t["with_only_certified_params"],
        "verified_with_dead_bits": t["with_dead_bits"],
        "verified_without_a_liveness_obligation": t["without_a_liveness_obligation"],
        "verified_liveness_checked": t["liveness_checked"], "verified_hold_claimed": t["hold_claimed"],
        "verified_lfsr_structures": t["lfsr_structures"], "verified_lfsr_poly_certified": t["lfsr_poly_certified"],
        "verified_with_a_load_case": t["with_a_load_case"],
        "load_hidden_share_over_verified_naming_one": {"n": int(share_n),
                                                       "mean": (share_sum / share_n) if share_n else None,
                                                       "max": share_max},
        "load_hidden_share_over_all_verified": {"n": int(share_all_n),
                                                "mean": (share_all_sum / share_all_n) if share_all_n else None},
        "unverified_reasons_all_structures": dict(reasons.most_common()),
        "per_kind": {c: {"unverified_structures": per_kind_unverified[c],
                         "unverified_reasons": dict(per_kind_reasons[c].most_common()),
                         "found_not_verified_registers": fnv[c], "verified_not_found_registers": vnf[c]}
                     for c in KINDS},
        "outcome_counts_all_structures": dict(outcomes.most_common()),
        "budget_outcomes": outcomes.get("budget", 0), "unknown_outcomes": outcomes.get("unknown", 0),
        "peak_conflicts_used": peak_conf, "conflicts_per_run_limit": lim.get("conflicts_per_run"),
        "peak_coverage_calls_used": peak_cov, "coverage_calls_per_run_limit": lim.get("coverage_calls_per_run"),
    }


def bits_block(Ds, cls="all", mode="strict"):
    per = {}
    tot = collections.Counter()
    f1s = []
    for c in KINDS:
        t = collections.Counter()
        for D in Ds:
            b = D["sc"]["classes"][cls]["bits"][mode][c]
            t["predicted"] += b["predicted"]
            t["support"] += b["support"]
            t["right"] += b["right"]
            t["several"] += b.get("several", 0)
            ris = (b["recall"] or 0.0) * b["support"]
            assert abs(ris - round(ris)) < 1e-6, (D["design"], c, ris)
            t["right_in_support"] += round(ris)
        p, r = rate(t["right"], t["predicted"]), rate(t["right_in_support"], t["support"])
        f1 = None if (not t["predicted"] and not t["support"]) else \
            ((2 * (p or 0) * (r or 0) / ((p or 0) + (r or 0))) if ((p or 0) + (r or 0)) else 0.0)
        per[c] = dict(t, precision=p, recall=r, f1=f1)
        if t["predicted"] or t["support"]:
            f1s.append(f1)
        tot.update(t)
    p, r = rate(tot["right"], tot["predicted"]), rate(tot["right_in_support"], tot["support"])
    per["_micro"] = dict(tot, precision=p, recall=r,
                         f1=(2 * p * r / (p + r)) if (p is not None and r is not None and p + r) else None)
    per["_macro_f1_over_kinds_with_support_or_predictions"] = statistics.fmean(f1s) if f1s else None
    nz = [x for x in f1s if x]
    per["_macro_f1_docs_S3_convention_kinds_with_P_and_R_both_0_left_out"] = statistics.fmean(nz) if nz else None
    per["_f1_convention"] = ("per-kind F1 = 0 when P + R = 0 (score._prf); the first macro averages every kind with "
                             "support or predictions, the second leaves out kinds whose F1 is 0 because P and R are "
                             "both 0 (the convention docs/S3.md's pooled figures used)")
    per["_source"] = f"{PC}.classes.{cls}.bits.{mode}.<kind> (right_in_support = recall x support)"
    return per


GROUP_RATES = ("ami", "ari", "nmi", "pair_precision", "pair_recall", "pair_f1", "purity", "inverse_purity",
               "exact_word_recall")
GROUP_COUNTS = ("n", "exact_words", "exact_words_lenient", "truth_words_multi", "splits", "merges", "pred_blocks",
                "truth_blocks")


def _st(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "mean": statistics.fmean(xs), "median": statistics.median(xs), "min": min(xs),
            "max": max(xs)}


def grouping_block(Ds):
    out = {}
    for blk in ("all_flops", "multi_flop_registers"):
        gs = [D["sc"]["grouping"][blk] for D in Ds if not D["sc"]["grouping"][blk].get("empty")]
        e = {"designs": len(gs), "source": f"{PC}.grouping.{blk}"}
        for k in GROUP_RATES:
            e[k] = _st([g.get(k) for g in gs])
        for k in GROUP_COUNTS:
            e[k + "_sum"] = sum(g.get(k) or 0 for g in gs)
        e["exact_words_over_truth_words_multi"] = frac(e["exact_words_sum"], e["truth_words_multi_sum"],
                                                       f"{PC}.grouping.{blk}.exact_words / .truth_words_multi (sums)")
        e["baseline_singletons_ami"] = _st([g["baseline_singletons"]["ami"] for g in gs])
        e["baseline_singletons_ari"] = _st([g["baseline_singletons"]["ari"] for g in gs])
        e["baseline_random_blocks_ami"] = _st([g["baseline_random_blocks"]["ami"]["mean"] for g in gs])
        e["baseline_random_blocks_ari"] = _st([g["baseline_random_blocks"]["ari"]["mean"] for g in gs])
        if gs:
            floor = e["baseline_random_blocks_ami"]["mean"]
            hi_floor = max(e["baseline_singletons_ami"]["mean"], floor)
            e["chance_floor_random_blocks_ami_mean"] = floor
            e["ami_mean_minus_random_block_floor"] = e["ami"]["mean"] - floor
            e["ami_median_minus_random_block_median"] = e["ami"]["median"] - e["baseline_random_blocks_ami"]["median"]
            e["higher_baseline_ami_mean"] = hi_floor
            e["ami_mean_minus_higher_baseline"] = e["ami"]["mean"] - hi_floor
        out[blk] = e
    out["rule"] = ("per-design grouping numbers (score.py, one partition per design) summarised as mean / median / "
                   "min / max over the designs; counts are sums. The chance floor is the set's own "
                   "score.py random-block baseline (baseline_random_blocks: the truth's block sizes, 5 seeded "
                   "draws per design, the per-design mean), summarised over the designs the same way.")
    return out


def order_block(Ds):
    """score.order.summary pooled over designs: per kind and width band (pair-weighted score and chance, as
    score.py weights them inside one design), and pooled over both bands exactly as out/s3/honesty/
    honesty_table.py quality()/pool_quality() pools them (the 'all' part; ordered and all_correct summed;
    concordance and chance pair-weighted; kappa recomputed from the pooled rates). Rows are score.py's
    order rows: LENIENT matches filed under the matched item's own truth kind."""
    kinds = sorted({k for D in Ds for k in D["sc"]["order"]["summary"]})
    out = {}
    for k in kinds:
        bands = {}
        pooled = collections.Counter()
        per_design_pairs = {}
        for band in ("width<=2", "width>=3"):
            t = collections.Counter()
            parts = {p: collections.Counter() for p in ("within", "across", "all")}
            for D in Ds:
                e = (D["sc"]["order"]["summary"].get(k) or {}).get(band)
                if not e:
                    continue
                for f in ("pairs_found", "ordered", "all_correct", "chance_one", "lanes_unordered",
                          "across_unscored_pairs"):
                    t[f] += e.get(f, 0)
                t["designs"] += 1
                for p in parts:
                    x = e.get(p)
                    if not x:
                        continue
                    parts[p]["pairs"] += x["pairs"]
                    parts[p]["asserted"] += x["asserted"]
                    parts[p]["registers"] += x["registers"]
                    parts[p]["score_x_pairs"] += (x["score"] or 0.0) * x["pairs"]
                    parts[p]["chance_x_pairs"] += (x["chance"] or 0.0) * x["pairs"]
                a = e.get("all") or {}
                pooled["ordered"] += e.get("ordered", 0)
                pooled["all_correct"] += e.get("all_correct", 0)
                pooled["items"] += e.get("pairs_found", 0)
                pooled["pairs"] += a.get("pairs", 0)
                pooled["asserted"] += a.get("asserted", 0)
                pooled["score_x_pairs"] += (a.get("score") or 0.0) * a.get("pairs", 0)
                pooled["chance_x_pairs"] += (a.get("chance") or 0.0) * a.get("pairs", 0)
                per_design_pairs[D["design"]] = per_design_pairs.get(D["design"], 0) + a.get("pairs", 0)
            if not t["designs"]:
                continue
            pe = {}
            for p, x in parts.items():
                if not x["pairs"]:
                    continue
                sc_, ch = x["score_x_pairs"] / x["pairs"], x["chance_x_pairs"] / x["pairs"]
                pe[p] = {"pairs": x["pairs"], "asserted": x["asserted"], "registers": x["registers"],
                         "pairs_weighted_score": sc_, "pairs_weighted_chance": ch,
                         "coverage": x["asserted"] / x["pairs"],
                         "kappa": (sc_ - ch) / (1 - ch) if ch < 1 else None}
            bands[band] = dict(t, parts=pe)
        n = pooled["pairs"]
        conc = pooled["score_x_pairs"] / n if n else None
        ch = pooled["chance_x_pairs"] / n if n else None
        out[k] = {"bands": bands,
                  "pooled_over_both_bands_as_honesty_table": {
                      "items": pooled["items"], "ordered": pooled["ordered"], "all_correct": pooled["all_correct"],
                      "pairs": n, "asserted": pooled["asserted"], "concordance": conc, "chance": ch,
                      "kappa": (conc - ch) / (1 - ch) if (conc is not None and ch is not None and ch < 1) else None,
                      "coverage": pooled["asserted"] / n if n else None,
                      "pairs_by_design": dict(sorted(per_design_pairs.items(), key=lambda z: -z[1]))}}
    out["_source"] = f"{PC}.order.summary.<kind>.<band>"
    return out


def params_block(Ds):
    t = collections.Counter()
    per = {}
    wrong = []
    for D in Ds:
        p = D["sc"]["params"]
        t["compared"] += p["compared"]
        t["correct"] += p["correct"]
        t["certified_compared"] += p["certified"]["compared"]
        t["certified_correct"] += p["certified"]["correct"]
        t["transcribed_compared"] += p["transcribed"]["compared"]
        t["transcribed_correct"] += p["transcribed"]["correct"]
        t["informative_compared"] += p["informative"]["compared"]
        t["informative_correct"] += p["informative"]["correct"]
        t["form_both_answers"] += p.get("form_both_answers", 0)
        for key, x in p["per_param"].items():
            e = per.setdefault(key, collections.Counter())
            e["n"] += x["n"]
            e["correct"] += x["correct"]
            e["certified_compared"] += x["certified"]["compared"]
            e["certified_correct"] += x["certified"]["correct"]
            e["transcribed_compared"] += x["transcribed"]["compared"]
            e["transcribed_correct"] += x["transcribed"]["correct"]
            e["majority_correct"] += x["majority_correct"]
            e["designs"] += 1
            e["informative_designs"] += bool(x["informative"])
            t["majority_correct"] += x["majority_correct"]
        for w in p["wrong"]:
            wrong.append(dict(w, design=D["design"]))
    src = f"{PC}.params"
    return {
        "combined": frac(t["correct"], t["compared"], src + ".correct / .compared"),
        "certified": frac(t["certified_correct"], t["certified_compared"], src + ".certified.correct / .compared"),
        "transcribed": frac(t["transcribed_correct"], t["transcribed_compared"],
                            src + ".transcribed.correct / .compared"),
        "informative": frac(t["informative_correct"], t["informative_compared"],
                            src + ".informative.correct / .compared"),
        "majority_baseline_over_all_compared": frac(t["majority_correct"], t["compared"],
                                                    src + ".per_param.*.majority_correct / .compared"),
        "form_both_answers": t["form_both_answers"],
        "per_param": {k: dict(v, accuracy=rate(v["correct"], v["n"]),
                              certified_accuracy=rate(v["certified_correct"], v["certified_compared"]),
                              transcribed_accuracy=rate(v["transcribed_correct"], v["transcribed_compared"]),
                              majority_accuracy=rate(v["majority_correct"], v["n"]))
                      for k, v in sorted(per.items())},
        "wrong": wrong,
        "rule": S.PARAMS_CERTIFIED_RULE,
        "matching_note": "score.py compares parameters over the LENIENT matches whose structure kind equals the "
                         "item kind (score._params)."}


def tier_summary(rows, kind=None):
    sel = [r for r in rows if kind is None or r["kind"] == kind]
    out = {"registers": len(sel), "tiers": dict(collections.Counter(r["tier"] for r in sel)),
           "subtiers": dict(collections.Counter(r["subtier"] for r in sel)), "outcome_by_tier": {}}
    for t in ("C_clean", "B_narrowed", "A_contradicted", "A1_simulation_mismatch", "A2_z3_refuted_only"):
        s = [r for r in sel if r["tier"] == t or r["subtier"] == t]
        out["outcome_by_tier"][t] = {"registers": len(s), "found": sum(r["found"] for r in s),
                                     "verified_found": sum(r["verified_found"] for r in s),
                                     "exact": sum(r["exact"] for r in s),
                                     "verified_exact": sum(r["verified_exact"] for r in s),
                                     "found_rate": rate(sum(r["found"] for r in s), len(s)),
                                     "verified_found_rate": rate(sum(r["verified_found"] for r in s), len(s))}
    return out


def design_rows_for(rows, designs, kind, keep=lambda r: True):
    """Per-design counts of one kind, from the per-register rows (after an optional filter)."""
    out = []
    for d in designs:
        s = [r for r in rows if r["design"] == d and r["kind"] == kind and keep(r)]
        out.append({"design": d, "den": len(s), "found": sum(r["found"] for r in s),
                    "verified_found": sum(r["verified_found"] for r in s), "exact": sum(r["exact"] for r in s)})
    return out


def design_rows_record(Ds, kind, cls_mode_num):
    """Per-design (numerator, registers) straight from the record fields."""
    out = []
    for D in Ds:
        a = pk(D, "all", "strict", kind)
        v = pk(D, "verified", "strict", kind)
        out.append({"design": D["design"], "den": a["registers"], "found": a["found"]["registers_found"],
                    "verified_found": v["found"]["registers_found"], "exact": a["exact"]["registers_found"],
                    "verified_exact": v["exact"]["registers_found"]})
    return out


# ------------------------------------------------------------------------------------------------
# main


def main():
    created = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fc_before = freeze_check()
    FREEZE = load(os.path.join(ROOT, "out", "s3", "FREEZE.json"))

    # ---------------------------------------------------------------- the two sets
    b1_found = discover(F1_HASH)
    r_found = discover(F4_HASH)
    r_paths = [os.path.join(RUNS, b) for _d, b in R_RECORDS]
    notes = []
    assert sorted(rel(p) for _c, _d, p in r_found) == sorted(rel(p) for p in r_paths), \
        ("R records on disk under freeze 4 differ from the task list", r_found)
    assert len(b1_found) == 10, b1_found
    B1 = [design_data("B1", p) for _c, _d, p in b1_found]
    R = [design_data("R", p) for p in r_paths]
    for (d, _b), D in zip(R_RECORDS, R):
        assert D["design"] == d, (d, D["design"])
    b1_ids = [D["design"] for D in B1]
    r_ids = [D["design"] for D in R]

    # ---------------------------------------------------------------- A. pooling precondition
    oos = list(S.OUT_OF_SAMPLE_SOURCES)
    oos_keys = [os.path.join("tools", "s3", n) for n in oos]
    ref_code = {k: B1[0]["rec"]["code"].get(k) for k in oos_keys}
    ref_rs = dict(B1[0]["rec"]["recognizer_sources"])
    b1_internal = []
    for D in B1:
        for k in oos_keys:
            if D["rec"]["code"].get(k) != ref_code[k]:
                b1_internal.append(f"{D['design']}: code {k}")
        if D["rec"]["recognizer_sources"] != ref_rs:
            b1_internal.append(f"{D['design']}: recognizer_sources")
    per_r = []
    for D in R:
        mism = [k for k in oos_keys if D["rec"]["code"].get(k) != ref_code[k]]
        rs = D["rec"]["recognizer_sources"]
        rs_mism = sorted(set(rs) ^ set(ref_rs)) + [k for k in rs if k in ref_rs and rs[k] != ref_rs[k]]
        ev_rs_mism = []
        for e in D["rec"]["evaluations"]:
            ers = (e.get("recognizer") or {}).get("recognizer_sources") or {}
            if ers != ref_rs:
                ev_rs_mism.append(e.get("label"))
        other = sorted(k for k in D["rec"]["code"] if k not in oos_keys
                       and D["rec"]["code"][k] != B1[0]["rec"]["code"].get(k))
        per_r.append({"design": D["design"], "code_12_present": all(k in D["rec"]["code"] for k in oos_keys),
                      "code_12_mismatches": mism, "recognizer_sources_count": len(rs),
                      "recognizer_sources_mismatches": rs_mism,
                      "evaluations_whose_recognizer_sources_differ": ev_rs_mism,
                      "identical": not mism and not rs_mism and not ev_rs_mism,
                      "non_precondition_code_files_that_differ_from_B1_informational": other})
    mismatch_designs = [x["design"] for x in per_r if not x["identical"]]
    tree_now = S._code_hashes(ROOT)
    freeze_code = FREEZE.get("code") or {}
    A = {
        "rule": "docs/S3_REPLICATION_PLAN.md: the 12 files of score.OUT_OF_SAMPLE_SOURCES in each R record's `code` "
                "and every `recognizer_sources` hash must equal B1's; a mismatching design is left out of every "
                "pooled figure.",
        "out_of_sample_sources": oos_keys,
        "B1_reference_hashes": ref_code, "B1_reference_recognizer_sources": ref_rs,
        "B1_records_agree_among_themselves": not b1_internal, "B1_internal_mismatches": b1_internal,
        "per_R_record": per_r,
        "R_designs_with_any_mismatch": mismatch_designs,
        "holds_for_all_10": not mismatch_designs and not b1_internal,
        "also_equal_to_the_current_tree": all(tree_now.get(k) == ref_code[k] for k in oos_keys),
        "also_equal_to_FREEZE_json_code": all(freeze_code.get(k) == ref_code[k] for k in oos_keys
                                              if k in freeze_code) and all(k in freeze_code for k in oos_keys),
        "statement": ("all 10 R records carry the 12 score.OUT_OF_SAMPLE_SOURCES hashes and the 10 "
                      "recognizer_sources hashes byte-identical to B1's; 0 mismatches; no design is excluded from "
                      "pooling") if not mismatch_designs and not b1_internal else
                     (f"MISMATCH: {mismatch_designs} (B1 internal: {b1_internal}); those R designs are left out "
                      "of every pooled figure"),
    }
    R_pool = [D for D in R if D["design"] not in mismatch_designs]

    # ---------------------------------------------------------------- per-register rows
    rows = {"B1": [r for D in B1 for r in register_rows(D)], "R": [r for D in R for r in register_rows(D)]}
    # rows reproduce the record's per-kind counts
    for sname, Ds in (("B1", B1), ("R", R)):
        for D in Ds:
            for c in KINDS:
                s = [r for r in rows[sname] if r["design"] == D["design"] and r["kind"] == c]
                a, v = pk(D, "all", "strict", c), pk(D, "verified", "strict", c)
                assert len(s) == a["registers"]
                assert sum(r["found"] for r in s) == a["found"]["registers_found"]
                assert sum(r["exact"] for r in s) == a["exact"]["registers_found"]
                assert sum(r["verified_found"] for r in s) == v["found"]["registers_found"]
                assert sum(r["verified_exact"] for r in s) == v["exact"]["registers_found"]
                if a["registers"] <= 40:
                    assert {r["register"] for r in s if r["found"]} == set(a["found_registers"])
                    assert {r["register"] for r in s if not r["found"]} == set(a["missed"])
                if v["registers"] <= 40:
                    assert {r["register"] for r in s if r["verified_found"]} == set(v["found_registers"])

    # ---------------------------------------------------------------- B. primary
    def rec_rows(Ds, numkey):
        out = []
        for D in Ds:
            a = pk(D, "all", "strict", "counter")
            v = pk(D, "verified", "strict", "counter")
            out.append({"design": D["design"], "den": a["registers"],
                        "verified_found": v["found"]["registers_found"], "found": a["found"]["registers_found"]})
        return out
    prim_src = (f"{PC}.classes.verified.registers.strict.per_kind.counter.found.registers_found / "
                f"{PC}.classes.all.registers.strict.per_kind.counter.registers (= the verified class's .registers)")
    for D in B1 + R:
        assert pk(D, "all", "strict", "counter")["registers"] == pk(D, "verified", "strict", "counter")["registers"]
    primary = full_comparison("counter harness-VERIFIED found recall over registers (strict)", prim_src,
                              rec_rows(B1, None), rec_rows(R_pool, None), "verified_found")
    d = primary["R_minus_B1"]["bootstrap_95"]
    primary["verdict"] = {"word": verdict_word(d["lo"], d["hi"]),
                          "rule": "docs/S3_REPLICATION_PLAN.md (fixed before the draw): R is 'consistent with freeze "
                                  "1' if the 95% bootstrap interval of R - B1 contains 0; otherwise 'higher' or "
                                  "'lower'. No other verdict word is used for the primary outcome.",
                          "interval_used": [d["lo"], d["hi"]]}
    primary["B1_matches_the_plan_statement_23_of_59"] = (primary["B1"]["num"], primary["B1"]["den"]) == (23, 59)
    pr = primary
    primary_text = (
        "PRIMARY -- counter harness-VERIFIED found recall over registers (strict); design-level cluster bootstrap, "
        f"{BOOT_N:,} resamples, numpy default_rng({BOOT_SEED}), percentile 95%.\n"
        f"  R  (replication, {pr['R']['designs']} designs):  {pr['R']['num']}/{pr['R']['den']} = {pr['R']['rate_4dp']}"
        f"  bootstrap 95% {pr['R']['bootstrap_95']['interval_4dp']}\n"
        f"  B1 (freeze 1, {pr['B1']['designs']} designs):    {pr['B1']['num']}/{pr['B1']['den']} = "
        f"{pr['B1']['rate_4dp']}  bootstrap 95% {pr['B1']['bootstrap_95']['interval_4dp']}\n"
        f"  R - B1:  {pr['R_minus_B1']['difference_4dp']}  bootstrap 95% {d['interval_4dp']} "
        "(each set resampled independently)\n"
        f"  Pooled B1+R ({pr['pooled_B1_plus_R']['designs']} designs): {pr['pooled_B1_plus_R']['num']}/"
        f"{pr['pooled_B1_plus_R']['den']} = {pr['pooled_B1_plus_R']['rate_4dp']}  bootstrap 95% "
        f"{pr['pooled_B1_plus_R']['bootstrap_95_stratified']['interval_4dp']} (resampled within each set); "
        f"sensitivity, 20 designs as one set: "
        f"{pr['pooled_B1_plus_R']['bootstrap_95_sensitivity_20_designs_as_one_set']['interval_4dp']}\n"
        f"  Independence-assuming comparison (the first report's): Fisher exact two-sided p (R vs B1) = "
        f"{pr['independence_assuming_comparison']['fisher_exact_two_sided_p_R_vs_B1']:.4f}; Clopper-Pearson 95%: "
        f"R {pr['independence_assuming_comparison']['clopper_pearson_95_R_4dp']}, "
        f"B1 {pr['independence_assuming_comparison']['clopper_pearson_95_B1_4dp']}, "
        f"pooled {pr['independence_assuming_comparison']['clopper_pearson_95_pooled_4dp']}\n"
        f"  VERDICT (plan's words): {primary['verdict']['word']}")
    primary["text"] = primary_text

    # ---------------------------------------------------------------- C. secondary
    counter_all = full_comparison(
        "counter all-structures found recall over registers (strict)",
        f"{PC}.classes.all.registers.strict.per_kind.counter.found.registers_found / .registers",
        rec_rows(B1, None), rec_rows(R_pool, None), "found")
    counter_all["note"] = "secondary, descriptive: the plan's verdict words apply to the primary outcome only"

    pooled_Ds = B1 + R_pool
    per_kind = {"R": kind_tables(R), "B1": kind_tables(B1), "pooled_B1_plus_R": kind_tables(pooled_Ds)}
    # the bootstrap wherever a kind has registers in >= 3 designs of the set
    kind_boot = {}
    for c in KINDS:
        rB, rR = design_rows_record(B1, c, None), design_rows_record(R_pool, c, None)
        nB = sum(1 for x in rB if x["den"])
        nR = sum(1 for x in rR if x["den"])
        e = {"designs_with_registers": {"R": nR, "B1": nB, "pooled": nB + nR}}
        for numkey in ("found", "verified_found", "exact", "verified_exact"):
            f = {}
            if nR >= 3:
                f["R"] = boot_one([x[numkey] for x in rR], [x["den"] for x in rR])
            if nB >= 3:
                f["B1"] = boot_one([x[numkey] for x in rB], [x["den"] for x in rB])
            if nB + nR >= 3:
                bd, bp = boot_two([x[numkey] for x in rB], [x["den"] for x in rB],
                                  [x[numkey] for x in rR], [x["den"] for x in rR])
                f["pooled_stratified"] = bp
                if nR >= 3 and nB >= 3:
                    f["R_minus_B1"] = bd
            e[numkey] = f
        e["rule"] = ("bootstrap only where the kind has registers in >= 3 designs of the set in question (counts only "
                     "otherwise); R - B1 only where both sets qualify; resamples with no register of the kind are "
                     "dropped and counted")
        kind_boot[c] = e

    fu = {"B1": [x for D in B1 for x in found_unverified(D, [r for r in rows["B1"] if r["design"] == D["design"]])],
          "R": [x for D in R for x in found_unverified(D, [r for r in rows["R"] if r["design"] == D["design"]])]}
    fu_summary = {}
    for sname in ("R", "B1"):
        xs = fu[sname]
        fu_summary[sname] = {"registers": len(xs), "by_cause": dict(collections.Counter(x["cause"] for x in xs)),
                             "by_bucket": dict(collections.Counter(x["bucket"] for x in xs)),
                             "by_kind": dict(collections.Counter(x["kind"] for x in xs)),
                             "exact_among_them": sum(x["exact"] for x in xs),
                             "reason_texts": dict(collections.Counter(re.sub(r"\d+", "N", x["verify_reason"])
                                                                      for x in xs))}
    fu_summary["pooled_B1_plus_R"] = {
        "registers": len(fu["B1"]) + len([x for x in fu["R"] if x["design"] not in mismatch_designs]),
        "by_cause": dict(collections.Counter(x["cause"] for x in fu["B1"] + [x for x in fu["R"]
                                                                            if x["design"] not in mismatch_designs]))}

    miss = {"R": [x for D in R for x in misses(D, [r for r in rows["R"] if r["design"] == D["design"]])],
            "B1": [x for D in B1 for x in misses(D, [r for r in rows["B1"] if r["design"] == D["design"]])]}
    fp = {"R": [x for D in R for x in false_positives(D)], "B1": [x for D in B1 for x in false_positives(D)]}

    def cat_summary(xs):
        out = {"total": len(xs), "by_kind": dict(collections.Counter(x["kind"] for x in xs))}
        out["by_category"] = dict(collections.Counter(x["category"] for x in xs))
        out["by_kind_and_category"] = dict(collections.Counter(f"{x['kind']} | {x['category']}" for x in xs))
        return out

    def fp_summary(xs):
        out = cat_summary(xs)
        out["verified"] = sum(x["verified"] for x in xs)
        out["by_category_verified"] = dict(collections.Counter(x["category"] for x in xs if x["verified"]))
        out["by_bucket"] = dict(collections.Counter(x["bucket"] for x in xs))
        out["matched_nothing_by_best_register_kind"] = dict(collections.Counter(
            x.get("best_register_kind") for x in xs if x["category"] == "matched nothing"))
        return out

    secondary = {
        "counter_all_structures_found_recall": counter_all,
        "per_kind": per_kind,
        "per_kind_bootstrap": kind_boot,
        "found_but_unverified": {"summary": fu_summary, "registers": fu},
        "misses_mechanical": {"summary": {s: cat_summary(miss[s]) for s in ("R", "B1")}, "registers": miss,
                              "rule": "strict all-structures pass: a missed register is either matched (IoU > 0.5, one "
                                      "to one) by a structure whose kind the truth refuses, or matched by nothing; "
                                      "a mechanical split, not a cause attribution"},
        "false_positives_mechanical": {"summary": {s: fp_summary(fp[s]) for s in ("R", "B1")}, "structures": fp,
                                       "rule": "every scored-kind structure the strict all-structures pass does not "
                                               "credit: matched a truth item of another kind (kind refused), or "
                                               "matched nothing (the truth kind of the register it overlaps most "
                                               "by IoU is given); a mechanical split, not a cause attribution"},
        "honesty": {"R": honesty_block(R), "B1": honesty_block(B1), "pooled_B1_plus_R": honesty_block(pooled_Ds),
                    "verified_structures_R": [x for D in R for x in verified_list(D)],
                    "verified_structures_B1": [x for D in B1 for x in verified_list(D)]},
        "bits": {s: {"all/strict": bits_block(Ds, "all", "strict"), "verified/strict": bits_block(Ds, "verified", "strict")}
                 for s, Ds in (("R", R), ("B1", B1), ("pooled_B1_plus_R", pooled_Ds))},
        "grouping": {"R": grouping_block(R), "B1": grouping_block(B1), "pooled_B1_plus_R": grouping_block(pooled_Ds)},
        "order": {"R": order_block(R), "B1": order_block(B1), "pooled_B1_plus_R": order_block(pooled_Ds)},
        "params": {"R": params_block(R), "B1": params_block(B1), "pooled_B1_plus_R": params_block(pooled_Ds)},
    }

    # per-design table for R
    pdt = []
    for D in R:
        sc = D["sc"]
        row = {"design": D["design"], "universe_flops": sc["truth"]["flops"],
               "truth_registers": sc["truth"]["registers"], "truth_registers_with_flops": sc["truth"]["registers_with_flops"],
               "shadow_flops": sc["truth"]["shadow_flops"], "unmapped_flops": sc["truth"]["unmapped_flops"],
               "units": sc["truth"]["units"], "chain_units": len(sc["truth"]["chain_units"]),
               "structures_returned": sc["result"]["structures"], "structures_scored": sc["result"]["structures_scored"],
               "verified_structures": sc["result"]["verified"], "claimed_proven": sc["result"]["claimed_proven"],
               "dropped_flops": sc["result"]["dropped_flops"],
               "structures_with_dropped_flops": sc["result"]["structures_with_dropped_flops"]}
        for c in KINDS:
            a, v = pk(D, "all", "strict", c), pk(D, "verified", "strict", c)
            row[c] = {"registers": a["registers"], "found": a["found"]["registers_found"],
                      "verified_found": v["found"]["registers_found"], "exact": a["exact"]["registers_found"],
                      "verified_exact": v["exact"]["registers_found"], "structures": a["structures"],
                      "verified_structures": v["structures"],
                      "false_positive_structures": a["structures"] - a["found"]["structures_matched"]}
        g = sc["grouping"]["all_flops"]
        row["ami"], row["ari"] = g.get("ami"), g.get("ari")
        row["random_block_ami"] = (g.get("baseline_random_blocks") or {}).get("ami", {}).get("mean")
        p = sc["params"]
        row["params_combined"] = f"{p['correct']}/{p['compared']}"
        row["params_certified"] = f"{p['certified']['correct']}/{p['certified']['compared']}"
        row["params_transcribed"] = f"{p['transcribed']['correct']}/{p['transcribed']['compared']}"
        row["tiers"] = dict(collections.Counter(r["tier"] for r in rows["R"] if r["design"] == D["design"]))
        pdt.append(row)
    secondary["per_design_R"] = {"rows": pdt, "source": f"{PC}.truth / .result / .classes / .grouping / .params"}

    # ---------------------------------------------------------------- D. label quality
    rows_pool = rows["B1"] + [r for r in rows["R"] if r["design"] not in mismatch_designs]
    labq = {"rule": tier_of.__doc__.strip().replace("\n    ", " "),
            "R": {"all_kinds": tier_summary(rows["R"]), "counter": tier_summary(rows["R"], "counter"),
                  "flop_level": {D["design"]: flop_evidence(D) for D in R},
                  "per_design_tier_counts": {D["design"]: dict(collections.Counter(
                      r["tier"] for r in rows["R"] if r["design"] == D["design"])) for D in R},
                  "registers": rows["R"]},
            "B1": {"all_kinds": tier_summary(rows["B1"]), "counter": tier_summary(rows["B1"], "counter"),
                   "flop_level": {D["design"]: flop_evidence(D) for D in B1}},
            "pooled_B1_plus_R": {"all_kinds": tier_summary(rows_pool), "counter": tier_summary(rows_pool, "counter")}}
    for sname in ("R", "B1"):
        fl = labq[sname]["flop_level"]
        labq[sname]["flop_level_total"] = {k: sum(v[k] for v in fl.values())
                                           for k in ("flops", "mapping_proof_refuted",
                                                     "refuted_and_simulation_mismatch")}
    notA = lambda r: r["tier"] != "A_contradicted"   # noqa: E731
    rB_na = design_rows_for(rows["B1"], b1_ids, "counter", notA)
    rR_na = design_rows_for(rows["R"], [D["design"] for D in R_pool], "counter", notA)
    prim_noA = full_comparison(
        "PRIMARY WITH TIER A REMOVED: counter harness-VERIFIED found recall over the registers that are not Tier A "
        "(strict)", "per-register rows (score.py credit recovered from the record; tier from the truth's bits)",
        rB_na, rR_na, "verified_found")
    prim_noA["note"] = ("label-quality reading of the primary outcome (plan: 'the primary outcome is also reported with "
                        "Tier A registers removed'); the plan's verdict words apply to the primary as reported, not "
                        "to this variant; R - B1 is given for description only")
    labq["primary_with_tier_A_removed"] = prim_noA
    labq["counter_all_structures_found_with_tier_A_removed"] = full_comparison(
        "counter all-structures found recall over the registers that are not Tier A (strict)",
        "per-register rows", rB_na, rR_na, "found")
    # all four kinds, Tier A removed (docs/S3.md section 11's row)
    def pooled_noA(rs):
        s = [r for r in rs if notA(r)]
        return {"registers": len(s), "found": frac(sum(r["found"] for r in s), len(s), "per-register rows"),
                "verified_found": frac(sum(r["verified_found"] for r in s), len(s), "per-register rows")}
    labq["all_kinds_tier_A_removed"] = {"R": pooled_noA(rows["R"]), "B1": pooled_noA(rows["B1"]),
                                        "pooled_B1_plus_R": pooled_noA(rows_pool)}

    # ---------------------------------------------------------------- E. mechanics
    mech = {"per_design": [], "ledger": {}, "labelling": {}}
    for D in R:
        rec = D["rec"]
        evs = rec["evaluations"]
        sp = rec["spread"]
        mets = sp["metrics"]
        all_none = [m for m, e in mets.items() if e["n"] == 0]
        varying = [m for m, e in mets.items() if e["n"] and (e["n"] != sp["k"] or e["min"] != e["max"])]
        att_path = os.path.join(ROOT, rec["attempt"]["record"])
        att = load(att_path) if os.path.exists(att_path) else None
        mech["per_design"].append({
            "design": D["design"], "record": rel(D["path"]), "record_sha256": sha256_file(D["path"]),
            "created": rec["created"], "git_head": rec["git_head"],
            "freeze_hash": rec["freeze"]["freeze_hash"], "freeze_is_freeze_4": rec["freeze"]["freeze_hash"] == F4_HASH,
            "freeze_git_head": rec["freeze"]["git_head"], "blind": rec["blind"], "valid": rec["valid"],
            "invalid_reasons": rec["invalid_reasons"], "problems": rec["problems"], "rerun": rec["rerun"],
            "attempt_id": rec["attempt"]["id"], "attempt_record": rec["attempt"]["record"],
            "attempt_record_sha256_matches": (sha256_file(att_path) == rec["attempt"]["record_sha256"])
            if att else False,
            "attempt_record_rerun": (att or {}).get("rerun"),
            "attempt_record_freeze_hash_is_freeze_4": ((att or {}).get("freeze") or {}).get("freeze_hash") == F4_HASH,
            "evaluations": len(evs), "evaluation_labels": [e.get("label") for e in evs],
            "evaluations_valid": sum(1 for e in evs if not e["invalid_reasons"]),
            "evaluation_invalid_reasons": sorted({x for e in evs for x in e["invalid_reasons"]}),
            "evaluation_problems": sorted({x for e in evs for x in e["problems"]}),
            "score_problems_p1": D["sc"]["problems"],
            "permutations": rec["permutations"], "leakage_arm": rec["leakage"],
            "spread": {"k": sp["k"], "valid": sp["valid"], "distinct_answers": sp["distinct_answers"],
                       "structures": {k: v for k, v in sp["structures"].items()},
                       "metrics": len(mets), "metrics_all_none": len(all_none), "metrics_varying": varying},
            "per_kind_counts_identical_across_permutations": D["per_kind_counts_identical_across_permutations"],
            "anonymity": {"netlist_leaks_max": max(e["netlist"]["anonymity"]["leaks"] for e in evs),
                          "blackbox_named_leaks_max": max(e["netlist"]["anonymity"]["blackbox"]["named_leaks"]
                                                          for e in evs),
                          "blackbox_not_opaque_max": max(e["netlist"]["anonymity"]["blackbox"]["not_opaque"]
                                                         for e in evs),
                          "result_key_name_leaks": sum(1 for e in evs for x in e["problems"]
                                                       if "Key names" in x),
                          "ids_not_an_id": sum(e["ids"]["not_an_id"] for e in evs),
                          "ids_not_a_flop": sum(e["ids"]["not_a_flop"] for e in evs)},
            "recognizer": {"ok_all": all(e["recognizer"]["ok"] for e in evs),
                           "returncodes": sorted({e["recognizer"].get("returncode") for e in evs}, key=str),
                           "timeouts": sum(1 for e in evs if "TIMEOUT" in (e["recognizer"].get("stderr_tail") or "")),
                           "sandbox": sorted({e["recognizer"].get("os_sandbox") for e in evs}, key=str),
                           "blocked_count_max": max(e["recognizer"].get("blocked_count", 0) for e in evs),
                           "wall_s": [e["recognizer"]["wall_s"] for e in evs],
                           "peak_rss_mb": [e["recognizer"]["peak_rss_mb"] for e in evs]},
            "record_total_s": rec["timings_s"]["total_s"],
            "record_extract_and_load_s": rec["timings_s"]["extract_and_load_s"],
            "harness_peak_rss_mb": rec["harness_peak_rss_mb"],
            "join": D["ev"]["join"],
            "truth_hash_three_way_agree": D["truth_hash"]["agree"],
            "truth_check_problems": rec["truth"]["check_truth_problems"],
        })
    pdm = mech["per_design"]
    walls = [w for x in pdm for w in x["recognizer"]["wall_s"]]
    rss = [w for x in pdm for w in x["recognizer"]["peak_rss_mb"]]
    mech["summary"] = {
        "records": len(pdm), "valid_records": sum(x["valid"] for x in pdm),
        "records_with_problems": [x["design"] for x in pdm if x["problems"]],
        "evaluations": sum(x["evaluations"] for x in pdm),
        "evaluations_valid": sum(x["evaluations_valid"] for x in pdm),
        "distinct_answers_per_design": {x["design"]: x["spread"]["distinct_answers"] for x in pdm},
        "all_one_distinct_answer": all(x["spread"]["distinct_answers"] == 1 for x in pdm),
        "unstable_structures_total": sum(len(x["spread"]["structures"].get("unstable") or []) for x in pdm),
        "metrics_varying_total": sum(len(x["spread"]["metrics_varying"]) for x in pdm),
        "metrics_defined_range": [min(x["spread"]["metrics"] - x["spread"]["metrics_all_none"] for x in pdm),
                                  max(x["spread"]["metrics"] - x["spread"]["metrics_all_none"] for x in pdm)],
        "metrics_total_range": [min(x["spread"]["metrics"] for x in pdm), max(x["spread"]["metrics"] for x in pdm)],
        "anonymity_leaks_total": sum(x["anonymity"]["netlist_leaks_max"] + x["anonymity"]["blackbox_named_leaks_max"]
                                     + x["anonymity"]["blackbox_not_opaque_max"]
                                     + x["anonymity"]["result_key_name_leaks"] for x in pdm),
        "timeouts_total": sum(x["recognizer"]["timeouts"] for x in pdm),
        "recognizer_failures": sum(0 if x["recognizer"]["ok_all"] else 1 for x in pdm),
        "sandbox_blocked_max": max(x["recognizer"]["blocked_count_max"] for x in pdm),
        "recognizer_wall_s_range": [min(walls), max(walls)],
        "recognizer_peak_rss_mb_range": [min(rss), max(rss)],
        "record_total_s_range": [min(x["record_total_s"] for x in pdm), max(x["record_total_s"] for x in pdm)],
        "record_total_s_sum": sum(x["record_total_s"] for x in pdm),
        "harness_peak_rss_mb_range": [min(x["harness_peak_rss_mb"] for x in pdm),
                                      max(x["harness_peak_rss_mb"] for x in pdm)],
        "leakage_file_order_arm_run_on_any": any(x["permutations"].get("file_order_arm") for x in pdm),
        "permutation_k": sorted({x["permutations"]["k"] for x in pdm}),
        "all_freeze_4": all(x["freeze_is_freeze_4"] for x in pdm),
        "all_attempt_records_match_sha256": all(x["attempt_record_sha256_matches"] for x in pdm),
        "no_rerun": all(x["rerun"] is None and x["attempt_record_rerun"] is None for x in pdm),
        "truth_hashes_agree_all": all(x["truth_hash_three_way_agree"] for x in pdm),
        "per_kind_counts_identical_across_permutations_all": all(
            x["per_kind_counts_identical_across_permutations"] for x in pdm),
        "unmapped_or_dropped": {x["design"]: {"dropped_flops_p1": D["sc"]["result"]["dropped_flops"],
                                              "structures_with_dropped_flops": D["sc"]["result"]
                                              ["structures_with_dropped_flops"],
                                              "truth_unmapped": x["join"]["truth_unmapped"],
                                              "truth_shadow_flops": x["join"]["truth_shadow_flops"]}
                                for x, D in zip(pdm, R) if D["sc"]["result"]["dropped_flops"]
                                or x["join"]["truth_unmapped"] or x["join"]["truth_shadow_flops"]},
    }
    # ledger
    entries, lproblems = FZ.ledger_entries(ROOT)
    lp = os.path.join(ROOT, "out", "s3", "blind_ledger.jsonl")
    lines = [x for x in open(lp).read().splitlines() if x.strip()]
    prev, breaks = None, []
    for i, ln in enumerate(lines):
        e = json.loads(ln)
        if e.get("prev") != prev:
            breaks.append(i + 1)
        prev = hashlib.sha256(ln.encode()).hexdigest()
    f4_att = collections.defaultdict(list)
    f4_fin = collections.defaultdict(list)
    att_to_design = {}
    for e in entries:
        if e.get("freeze_hash") == F4_HASH and e.get("event") == "attempt":
            f4_att[e["design"]].append(e)
            att_to_design[e["attempt"]] = e["design"]
    for e in entries:
        if e.get("event") == "finish" and e.get("attempt") in att_to_design:
            f4_fin[att_to_design[e["attempt"]]].append(e)
    xcheck = {}
    for D in R:
        a = f4_att.get(D["design"], [])
        f = f4_fin.get(D["design"], [])
        ok = (len(a) == 1 and len(f) == 1 and a[0]["attempt"] == D["rec"]["attempt"]["id"]
              and a[0]["record"] == D["rec"]["attempt"]["record"]
              and a[0]["record_sha256"] == D["rec"]["attempt"]["record_sha256"]
              and f[0]["record"] == rel(D["path"]) and f[0]["record_sha256"] == sha256_file(D["path"])
              and f[0].get("valid") is True and a[0].get("rerun_reason") is None)
        other = [e for e in entries if e.get("event") == "attempt" and e.get("design") == D["design"]
                 and e.get("freeze_hash") != F4_HASH]
        other_recs = [x for _c, dd, x in discover(F1_HASH) if dd == D["design"]]
        xcheck[D["design"]] = {"attempts_under_freeze_4": len(a), "finishes": len(f), "cross_check_pass": ok,
                               "ledger_attempts_under_any_other_freeze": len(other),
                               "freeze_1_run_records": len(other_recs),
                               "freeze_blind_results_under_freeze_4": FZ.blind_results(D["design"], F4_HASH, ROOT)}
    rc = subprocess.run(["git", "status", "--porcelain", "out/s3/blind_ledger.jsonl"], cwd=ROOT,
                        capture_output=True, text=True)
    mech["ledger"] = {
        "path": rel(lp), "lines_working_tree": len(lines), "working_tree_hash_chain_intact": not breaks,
        "chain_breaks_at_lines": breaks, "freeze_ledger_entries_problems": lproblems,
        "entries_working_tree_and_history": len(entries),
        "uncommitted_lines": FZ.ledger_uncommitted(ROOT),
        "git_status_porcelain": rc.stdout.strip(),
        "freeze_4_attempt_designs": sorted(f4_att), "freeze_4_attempts_total": sum(len(v) for v in f4_att.values()),
        "freeze_4_designs_not_in_R": sorted(set(f4_att) - set(r_ids)),
        "per_design": xcheck,
        "exactly_one_attempt_per_design_under_freeze_4": all(v["attempts_under_freeze_4"] == 1 for v in xcheck.values())
        and not (set(f4_att) - set(r_ids)),
        "all_cross_checks_pass": all(v["cross_check_pass"] for v in xcheck.values()),
        "hash_semantics": "each line's `prev` is the sha256 of the previous line's text (tools/s3/freeze.py "
                          "ledger_append); ledger_entries reads the working tree and every committed version"}
    # labelling (the replication labels; mechanics only)
    labp = os.path.join(ROOT, "out", "s3", "replication", "labels.json")
    lab = load(labp)
    blind_labp = os.path.join(ROOT, "out", "s3", "blind", "labels.json")
    head = subprocess.run(["git", "show", "HEAD:out/s3/blind/labels.json"], cwd=ROOT, capture_output=True, text=True)
    head_doc = json.loads(head.stdout) if head.returncode == 0 else {}
    wt_doc = load(blind_labp)
    mech["out_s3_blind_labels_json"] = {
        "working_tree_freeze_hash": wt_doc["freeze"]["freeze_hash"], "working_tree_written": wt_doc.get("written"),
        "HEAD_freeze_hash": (head_doc.get("freeze") or {}).get("freeze_hash"), "HEAD_written": head_doc.get("written"),
        "working_tree_differs_from_HEAD": head.stdout.encode() != open(blind_labp, "rb").read(),
        "git_status_porcelain": subprocess.run(["git", "status", "--porcelain", "out/s3/blind/labels.json"], cwd=ROOT,
                                               capture_output=True, text=True).stdout.strip()}
    mech["labelling"] = {
        "path": rel(labp), "sha256": sha256_file(labp),
        "out_s3_blind_labels_json_is_byte_identical": sha256_file(blind_labp) == sha256_file(labp),
        "freeze_hash": lab["freeze"]["freeze_hash"], "blind_seed": lab["freeze"]["blind_seed"],
        "seed_is_freeze_4s": lab["freeze"]["blind_seed"] == F4_SEED == FREEZE.get("blind_seed"),
        "labeller_sha256": lab["labeller"]["sha256"], "labeller_sha256_on_disk": lab["labeller"]["sha256_on_disk"],
        "labeller_equals_record_code_thirdparty": all(D["rec"]["code"].get("tools/s3/thirdparty.py")
                                                      == lab["labeller"]["sha256"] for D in R),
        "drawn": lab["draw"]["blind"], "reserve": lab["draw"]["reserve"],
        "evaluation_set": lab["evaluation_set"], "replaced_by": lab["replaced_by"],
        "reserves_used": lab["reserves_used"], "counts": lab["counts"],
        "failures": [{"id": x["id"], "n": x["n"], "replaces": x.get("replaces"), "error": x.get("error")}
                     for x in lab["designs"] if not x["ok"]],
        "evaluation_set_equals_R": [x.replace("/", "__") for x in lab["evaluation_set"]] == r_ids,
        "truth_hashes_equal_records": all(
            next(x for x in lab["designs"] if x["design_id"] == D["design"] and x["ok"])["truth_hash"]
            == D["rec"]["truth"]["truth_hash"] for D in R)}

    # ---------------------------------------------------------------- F. references
    HR = load(os.path.join(ROOT, "out", "s3", "honesty", "holdout_rates.json"))
    HT = load(os.path.join(ROOT, "out", "s3", "honesty", "honesty_table.json"))
    ch = HT["results"]["corpus_holdout"]
    pooled_kind = per_kind["pooled_B1_plus_R"]
    refs = {"pooled_set": {}, "holdout_rates_json": {}, "honesty_table_json_corpus_holdout": {}}
    for c in KINDS:
        s = pooled_kind[c]["summary"]
        refs["pooled_set"][c] = {k: s[k] for k in ("registers", "designs_with_any", "found", "found_recall",
                                                   "verified_found", "verified_found_recall", "exact",
                                                   "exact_recall", "verified_exact", "verified_exact_recall")}
        h = HR["holdout"]["per_kind"][c]
        refs["holdout_rates_json"][c] = dict(h, derived_all_structures_rate=rate(h["found"] + h["found_unverified"],
                                                                                h["items"]),
                                             derived_all_structures_label="derived here as (found + found_unverified) "
                                                                          "/ items; holdout_rates.json publishes no "
                                                                          "all-structures rate")
        t = ch["per_kind"][c]
        refs["honesty_table_json_corpus_holdout"][c] = {k: t[k] for k in (
            "registers", "found", "found_recall", "verified_found", "verified_found_recall", "structures",
            "verified_structures", "found_not_verified", "unverified_reasons")}
        # descriptive, not in the plan: exact intervals and Fisher p on the counts, independence assumed
        refs["pooled_set"][c]["descriptive_not_in_plan"] = {
            "clopper_pearson_95_verified_found": list(clopper_pearson(s["verified_found"], s["registers"])),
            "clopper_pearson_95_found": list(clopper_pearson(s["found"], s["registers"])),
            "fisher_p_verified_found_vs_holdout_rates_found": fisher_exact_two_sided(
                s["verified_found"], s["registers"] - s["verified_found"], h["found"], h["items"] - h["found"]),
            "fisher_p_verified_found_vs_honesty_table_verified_found": fisher_exact_two_sided(
                s["verified_found"], s["registers"] - s["verified_found"], t["verified_found"],
                t["registers"] - t["verified_found"]),
            "fisher_p_found_vs_honesty_table_found": fisher_exact_two_sided(
                s["found"], s["registers"] - s["found"], t["found"], t["registers"] - t["found"]),
            "clopper_pearson_95_holdout_rates_found": list(clopper_pearson(h["found"], h["items"])),
            "clopper_pearson_95_honesty_table_verified_found": list(clopper_pearson(t["verified_found"],
                                                                                    t["registers"])),
            "label": "computed here, in no frozen record and not in the plan; they assume independent items, which "
                     "registers inside one design are not, and the item sets differ (see caveat)"}
    refs["holdout_rates_json"]["_meta"] = {"path": "out/s3/honesty/holdout_rates.json",
                                           "sha256": sha256_file(os.path.join(ROOT, "out/s3/honesty/holdout_rates.json")),
                                           "aggregation_id": HR["source"].get("aggregation_id"),
                                           "aggregation": HR.get("aggregation"),
                                           "designs": HR["holdout"]["designs"], "runs": HR["holdout"]["runs"],
                                           "grouping": HR["holdout"]["grouping"],
                                           "false_positive_structures": HR["holdout"]["false_positive_structures"],
                                           "caveats": HR["caveats"],
                                           "found_means": "harness-VERIFIED found; exact_rate is verified exact"}
    refs["honesty_table_json_corpus_holdout"]["_meta"] = {
        "path": "out/s3/honesty/honesty_table.json",
        "sha256": sha256_file(os.path.join(ROOT, "out/s3/honesty/honesty_table.json")),
        "seed": HT["seed"], "designs": ch["designs"], "evaluations": ch["evaluations"], "libraries": ch["libraries"],
        "arm_note": HT["arm_notes"]["corpus_holdout"], "code_state": HT["code_state"],
        "params": ch["params"], "quality_grouping": ch["quality"]["grouping"],
        "quality_order": {k: ch["quality"]["per_kind"][k]["order"] for k in KINDS},
        "quality_exact": {k: ch["quality"]["per_kind"][k]["exact"] for k in KINDS},
        "verified": ch["verified"], "unverified_reasons": ch["unverified_reasons"]}
    rec_code = B1[0]["rec"]["code"]
    hr_code = HR["source"].get("code_sha256") or {}
    ht_code = HT.get("code") or {}
    refs["code_state"] = {
        "holdout_rates_code_equals_records": all(hr_code.get(k) == rec_code.get(k) for k in oos_keys),
        "honesty_table_code_equals_records": all(ht_code.get(k) == rec_code.get(k) for k in oos_keys),
        "score_out_of_sample_problem_in_this_tree": S.out_of_sample_problem(ROOT)}
    refs["pooled_set_other"] = {
        "grouping_all_flops_ami": secondary["grouping"]["pooled_B1_plus_R"]["all_flops"]["ami"],
        "grouping_random_block_floor": secondary["grouping"]["pooled_B1_plus_R"]["all_flops"]
        ["baseline_random_blocks_ami"],
        "params": {k: secondary["params"]["pooled_B1_plus_R"][k] for k in ("certified", "transcribed", "combined")},
        "order_counter_both_bands": secondary["order"]["pooled_B1_plus_R"].get("counter", {})
        .get("pooled_over_both_bands_as_honesty_table")}
    refs["caveat"] = (
        "The item sets differ. Every blind figure (B1, R, pooled) counts score.py's strict register denominators. "
        "holdout_rates.json counts registers plus declared units (aggregation 'per_register_and_unit', which "
        "holdout_rates.py itself calls not comparable with score.py's strict register counts), over 40 synthetic "
        "holdout designs and 80 runs; its 'found' is harness-VERIFIED found and it carries no confidence interval. "
        "honesty_table.json's corpus_holdout arm uses score.py's own register denominators, which removes the "
        "item-set objection, but it is a different seeded run (seed 20260923, libraries ihp and sky130, each "
        "design twice). The synthetic corpus was written by the same project as the recognizer. docs/S3.md "
        "sections 2 and 6 state the same caveat for the first report.")

    # ---------------------------------------------------------------- cross-checks against docs/S3.md (B1)
    b1k = per_kind["B1"]
    b1h = secondary["honesty"]["B1"]
    b1g = secondary["grouping"]["B1"]["all_flops"]
    b1p = secondary["params"]["B1"]
    b1o = secondary["order"]["B1"]["counter"]
    xc = {
        "counter 59 registers / 41 found / 23 verified / 28 exact / 15 verified exact / 72 structures / 34 verified "
        "structures / 31 FP": [b1k["counter"]["summary"][k] for k in ("registers", "found", "verified_found", "exact",
                                                                      "verified_exact", "structures",
                                                                      "verified_structures",
                                                                      "false_positive_structures")]
        == [59, 41, 23, 28, 15, 72, 34, 31],
        "shift 8/1/1, lfsr 9/0/0, sync 18/17/17 (registers/found/verified)": [
            [b1k[c]["summary"][k] for k in ("registers", "found", "verified_found")]
            for c in ("shift_register", "lfsr_crc", "synchronizer")] == [[8, 1, 1], [9, 0, 0], [18, 17, 17]],
        "all four: 94 registers, 59 found, 41 verified found, 78 structures, 45 matched": [
            b1k["all_four_kinds_strict"]["registers"], b1k["all_four_kinds_strict"]["found"]["num"],
            b1k["all_four_kinds_strict"]["verified_found"]["num"], b1k["all_four_kinds_strict"]["structures"],
            b1k["all_four_kinds_strict"]["precision_over_structures"]["num"]] == [94, 59, 41, 78, 45],
        "tiers A 23 / B 2 / C 69; A1 16 / A2 7": (labq["B1"]["all_kinds"]["tiers"] ==
                                                  {"A_contradicted": 23, "B_narrowed": 2, "C_clean": 69} and
                                                  labq["B1"]["all_kinds"]["subtiers"].get("A1_simulation_mismatch") == 16
                                                  and labq["B1"]["all_kinds"]["subtiers"].get("A2_z3_refuted_only") == 7),
        "Tier A removed, all kinds: 54/71 found, 38/71 verified": [
            labq["all_kinds_tier_A_removed"]["B1"]["found"]["num"],
            labq["all_kinds_tier_A_removed"]["B1"]["verified_found"]["num"],
            labq["all_kinds_tier_A_removed"]["B1"]["registers"]] == [54, 38, 71],
        "Tier A removed, counter: 21/48 verified, 37/48 found (freeze-1 analysis H4)": [
            prim_noA["B1"]["num"], prim_noA["B1"]["den"],
            labq["counter_all_structures_found_with_tier_A_removed"]["B1"]["num"]] == [21, 48, 37],
        "flop level: 885 flops, 209 refuted, 112 also mismatching": [
            labq["B1"]["flop_level_total"][k] for k in ("flops", "mapping_proof_refuted",
                                                         "refuted_and_simulation_mismatch")] == [885, 209, 112],
        "found-but-unverified 18 = V1 2 + V2 16": (fu_summary["B1"]["registers"] == 18 and
                                                   fu_summary["B1"]["by_cause"].get("V1 control.hold not claimed") == 2),
        "misses 35 = 12 matched by a refused kind (10 unscored, 2 scored) + 23 matched by nothing": (
            secondary["misses_mechanical"]["summary"]["B1"]["total"] == 35 and
            secondary["misses_mechanical"]["summary"]["B1"]["by_category"].get(
                "matched, kind refused: unscored kind") == 10 and
            secondary["misses_mechanical"]["summary"]["B1"]["by_category"].get(
                "matched, kind refused: scored kind") == 2),
        "false positives 33, of which 13 verified": (secondary["false_positives_mechanical"]["summary"]["B1"]["total"]
                                                    == 33 and
                                                    secondary["false_positives_mechanical"]["summary"]["B1"]["verified"]
                                                    == 13),
        "honesty: 409 returned, 40 verified, 215 claimed proven, 6 vacuous hold, n=17 load share": [
            b1h["structures_returned"], b1h["verified_structures"], b1h["claimed_proven_score_py"],
            b1h["verified_vacuous_hold"], b1h["load_hidden_share_over_verified_naming_one"]["n"]]
        == [409, 40, 215, 6, 17],
        "grouping AMI mean 0.8425 / median 0.8310, random-block floor -0.0010, exact words 73/162": (
            fx(b1g["ami"]["mean"]) == "0.8425" and fx(b1g["ami"]["median"]) == "0.8310"
            and fx(b1g["baseline_random_blocks_ami"]["mean"]) == "-0.0010"
            and [b1g["exact_words_sum"], b1g["truth_words_multi_sum"]] == [73, 162]),
        "params certified 58/60, transcribed 36/38, combined 94/98, informative 29/31, majority 90/98": [
            (b1p[k]["num"], b1p[k]["den"]) for k in ("certified", "transcribed", "combined", "informative",
                                                     "majority_baseline_over_all_compared")]
        == [(58, 60), (36, 38), (94, 98), (29, 31), (90, 98)],
        "order counter: width>=3 40 items / 2797 pairs; both bands 41 items / 2798 pairs": (
            b1o["bands"]["width>=3"]["pairs_found"] == 40 and b1o["bands"]["width>=3"]["parts"]["all"]["pairs"] == 2797
            and b1o["pooled_over_both_bands_as_honesty_table"]["items"] == 41
            and b1o["pooled_over_both_bands_as_honesty_table"]["pairs"] == 2798),
        "bits micro F1 0.6364, macro (docs convention) 0.6292": (
            fx(secondary["bits"]["B1"]["all/strict"]["_micro"]["f1"]) == "0.6364" and
            fx(secondary["bits"]["B1"]["all/strict"]
               ["_macro_f1_docs_S3_convention_kinds_with_P_and_R_both_0_left_out"]) == "0.6292"),
        "register micro-F1 found 0.6012 / exact 0.4463; macro-F1 (docs convention) 0.6065 / 0.5404": [
            fx(b1k["all_four_kinds_strict"][k]) for k in ("micro_f1_found", "micro_f1_exact",
                                                           "macro_f1_found_docs_S3_convention",
                                                           "macro_f1_exact_docs_S3_convention")]
        == ["0.6012", "0.4463", "0.6065", "0.5404"],
        "counter macro recall 0.6383, mean IoU over found 0.9106, found@0.75 35": (
            fx(b1k["counter"]["all/strict"]["macro_found_recall_over_designs_with_any"]) == "0.6383"
            and fx(b1k["counter"]["all/strict"]["mean_iou_over_found"]) == "0.9106"
            and b1k["counter"]["all/strict"]["found_iou75"]["num"] == 35),
        "counter distinct design keys: found_all 27/44, found_any 28/44": [
            b1k["counter"]["all/strict"]["distinct_design_keys"][k] for k in ("found_all", "found_any", "total")]
        == [27, 28, 44],
        "strict equals lenient on every B1 kind": all(b1k[c]["strict_equals_lenient_counts"] for c in KINDS),
        "Fisher / Clopper-Pearson implementation: 23/59 vs 28/44 p = 0.017, CP 23/59 = [0.265, 0.526]": (
            f"{fisher_exact_two_sided(23, 36, 28, 16):.3f}" == "0.017"
            and [f"{x:.3f}" for x in clopper_pearson(23, 59)] == ["0.265", "0.526"]
            and [f"{x:.3f}" for x in clopper_pearson(28, 44)] == ["0.478", "0.776"]
            and f"{fisher_exact_two_sided(58, 2, 178, 2):.2f}" == "0.26"),
    }
    cross = {"against_docs_S3_md_freeze_1_published_figures": xc, "all_pass": all(xc.values()),
             "note": "B1 recomputed from its raw records with this file's code must reproduce docs/S3.md's published "
                     "figures; a failure here means this file's pipeline, not freeze 1, is wrong"}

    # ---------------------------------------------------------------- notes (facts the report must not miss)
    ob = mech["out_s3_blind_labels_json"]
    if ob["working_tree_differs_from_HEAD"]:
        notes.append(f"out/s3/blind/labels.json in the working tree is NOT the committed file: HEAD holds freeze 1's "
                     f"labels (freeze {str(ob['HEAD_freeze_hash'])[:12]}, written {ob['HEAD_written']}); the working "
                     f"tree holds Freeze 4's (freeze {ob['working_tree_freeze_hash'][:12]}, written "
                     f"{ob['working_tree_written']}), byte-identical to out/s3/replication/labels.json "
                     f"({mech['labelling']['out_s3_blind_labels_json_is_byte_identical']}). git status: "
                     f"'{ob['git_status_porcelain']}'. This script did not write it; freeze 1's version survives in git "
                     "history. The plan says replacements are recorded in out/s3/blind/labels.json.")
    for sname in ("R", "B1"):
        diff = [r for r in rows[sname] if r["found"] != r["lenient_found"]
                or r["verified_found"] != r["lenient_verified_found"]]
        if diff:
            notes.append(f"{sname}: strict and lenient credit differ on {len(diff)} register(s): " + "; ".join(
                f"{r['design']} {r['kind']} {r['register']} (strict found {r['found']} / verified "
                f"{r['verified_found']}; lenient found {r['lenient_found']} / verified {r['lenient_verified_found']}, "
                f"via unit {r['lenient_via_unit']!r}, structure {r['lenient_structure']})" for r in diff))
        else:
            notes.append(f"{sname}: strict and lenient credit agree on every scored register")
    zero = [r["design"] for r in pdt if all(r[c]["registers"] == 0 for c in KINDS)]
    if zero:
        notes.append(f"{zero} carry no register of any scored kind in score.py's denominators: they add 0 to every "
                     "recall denominator and only structures (false positives) to precision; each is still one of "
                     "R's 10 designs in the bootstrap")
    nz = primary["R"]["designs_with_registers"]
    notes.append(f"primary: counter registers sit in {nz} of R's {len(R_pool)} designs and "
                 f"{primary['B1']['designs_with_registers']} of B1's {len(B1)}")
    for x in mech["per_design"]:
        if x["problems"]:
            notes.append(f"{x['design']} record problems (verbatim): {x['problems']}")
    top = sorted((v for v in secondary["honesty"]["verified_structures_R"] if v["load_hidden_share"] is not None),
                 key=lambda v: -v["load_hidden_share"])[:3]
    if top:
        notes.append("R verified structures with the largest load_hidden_share: " + "; ".join(
            f"{v['design']} {v['structure']} ({v['kind']}, {v['flops']} flops) {v['load_hidden_share']}, credited "
            f"{v['credited']}" for v in top))

    fc_after = freeze_check()
    doc = {
        "schema": "retrace-s3-replication-numbers/1",
        "created": created,
        "generated_by": rel(os.path.abspath(__file__)),
        "script_sha256": sha256_file(os.path.abspath(__file__)),
        "plan": {"path": "docs/S3_REPLICATION_PLAN.md", "sha256": sha256_file(os.path.join(ROOT,
                                                                                          "docs/S3_REPLICATION_PLAN.md")),
                 "committed": "95f7eff (before the Freeze-4 seed existed)"},
        "freeze_check": {"before": fc_before, "after": fc_after},
        "sets": {
            "R": {"freeze_hash": F4_HASH, "seed": F4_SEED, "designs": r_ids,
                  "records": [{"design": D["design"], "record": rel(D["path"]), "sha256": sha256_file(D["path"]),
                               "truth": rel(D["truth_path"]), "truth_sha256": sha256_file(D["truth_path"])}
                              for D in R]},
            "B1": {"freeze_hash": F1_HASH, "designs": b1_ids,
                   "records": [{"design": D["design"], "record": rel(D["path"]), "sha256": sha256_file(D["path"]),
                                "truth": rel(D["truth_path"]), "truth_sha256": sha256_file(D["truth_path"])}
                               for D in B1],
                   "selection": "every out/s3/runs/blind-*.json (not .attempt.json) whose freeze.freeze_hash is freeze "
                                "1's, the puzzle record excluded"},
            "pooled_B1_plus_R": {"designs": b1_ids + [D["design"] for D in R_pool],
                                 "excluded_for_code_mismatch": mismatch_designs}},
        "definitions": {
            "evaluation": "each design contributes once, from its permutation p1; the per-kind counts are checked "
                          "identical across all K = 5 permutations of every record "
                          f"(all: {all(D['per_kind_counts_identical_across_permutations'] for D in B1 + R)})",
            "pooling": "MICRO over items: raw counts summed over the designs of the set, the rate taken once "
                       "(docs/S3.md 5.1). Macro recall = unweighted mean of per-design recall over designs with a "
                       "register of the kind.",
            "recall": "registers of the kind credited / registers of the kind (score.py Truth.denominators, strict "
                      "items: a synchronizer register in a declared chain unit is credited through the unit)",
            "precision": "structures of the kind that are found (matched an item accepting the kind) / structures "
                         "of the kind (docs/S3.md: the two rates have different denominators)",
            "verified": "the same, over harness-VERIFIED structures only (score.py classes.verified)",
            "false_positive_structures": "structures of the kind - structures matched (found)",
            "bootstrap": (f"design-level cluster bootstrap: resample designs with replacement, recompute the pooled "
                          f"ratio sum(numerator)/sum(registers); {BOOT_N} resamples; a FRESH "
                          f"numpy.random.default_rng({BOOT_SEED}) for every interval; index matrices drawn with "
                          f"rng.integers(0, n_designs, size=({BOOT_N}, n_designs)); for a two-set statistic the B1 "
                          "matrix is drawn first, then the R matrix, from the same generator, and the R - B1 "
                          "difference and the stratified pooled ratio are computed from those same resamples; the "
                          "pooled sensitivity resamples the 20 designs (B1 then R, in run order) as one set; "
                          "percentile interval numpy.percentile(stat, [2.5, 97.5]) (numpy's default linear method); "
                          "a resample with no register of the kind is dropped and counted. Designs are indexed in "
                          "run order within each set."),
            "fisher": "two-sided Fisher exact test on [[R hits, R misses], [B1 hits, B1 misses]]; p = sum of table "
                      "probabilities <= the observed one (relative tolerance 1e-7); exact integer arithmetic",
            "clopper_pearson": "exact binomial 95% interval by bisection on the binomial tails",
            "tiers": tier_of.__doc__.strip(),
            "numpy_version": np.__version__,
        },
        "A_pooling_precondition": A,
        "B_primary": primary,
        "C_secondary": secondary,
        "D_label_quality": labq,
        "E_mechanics": mech,
        "F_references": refs,
        "cross_checks": cross,
        "notes": notes,
    }
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "numbers.json"), "w") as f:
        json.dump(doc, f, indent=1, sort_keys=False, default=str)
        f.write("\n")
    with open(os.path.join(OUT, "numbers.md"), "w") as f:
        f.write(render_md(doc))
    print(primary_text)
    print("cross-checks against docs/S3.md (B1):", "ALL PASS" if cross["all_pass"] else
          {k: v for k, v in xc.items() if not v})
    print("freeze check before:", fc_before["stdout"], "| after:", fc_after["stdout"])


# ------------------------------------------------------------------------------------------------
# numbers.md


def render_md(doc):
    L = []
    W = L.append
    A, P, C, D, E, F = (doc["A_pooling_precondition"], doc["B_primary"], doc["C_secondary"], doc["D_label_quality"],
                        doc["E_mechanics"], doc["F_references"])
    W("# S3 replication -- canonical numbers\n")
    W(f"Generated {doc['created']} by `{doc['generated_by']}` (sha256 `{doc['script_sha256'][:16]}...`). "
      "Every figure below is in `numbers.json` with its numerator, denominator and the record field it came from; "
      "the report may quote no figure that is not there. Plan: `docs/S3_REPLICATION_PLAN.md` (95f7eff).\n")
    W(f"Freeze check before: `{doc['freeze_check']['before']['stdout']}`; after: "
      f"`{doc['freeze_check']['after']['stdout']}`.\n")
    W(f"Sets: **R** = {len(doc['sets']['R']['designs'])} Freeze-4 designs (freeze `{doc['sets']['R']['freeze_hash'][:12]}`, "
      f"seed `{doc['sets']['R']['seed']}`); **B1** = {len(doc['sets']['B1']['designs'])} freeze-1 blind designs "
      f"(`{doc['sets']['B1']['freeze_hash'][:12]}`); pooled = B1 + R ({len(doc['sets']['pooled_B1_plus_R']['designs'])} "
      "designs).\n")
    W("## A. Pooling precondition (code identity)\n")
    W(A["statement"] + ".\n")
    W(f"* B1 records agree among themselves: {A['B1_records_agree_among_themselves']}; also equal to the current tree: "
      f"{A['also_equal_to_the_current_tree']}; to out/s3/FREEZE.json's code: {A['also_equal_to_FREEZE_json_code']}.")
    for x in A["per_R_record"]:
        W(f"* `{x['design']}`: 12 OUT_OF_SAMPLE_SOURCES mismatches {len(x['code_12_mismatches'])}, "
          f"recognizer_sources ({x['recognizer_sources_count']}) mismatches {len(x['recognizer_sources_mismatches'])}, "
          f"evaluations with differing recognizer_sources {len(x['evaluations_whose_recognizer_sources_differ'])}; "
          f"other (non-precondition) code files that differ from B1: "
          f"{', '.join(x['non_precondition_code_files_that_differ_from_B1_informational']) or 'none'}")
    W("")
    W("## B. Primary outcome\n")
    W("```\n" + P["text"] + "\n```\n")
    W("| Set | designs | registers | verified found | rate | bootstrap 95% | Clopper-Pearson 95% |")
    W("|---|---|---|---|---|---|---|")
    ia = P["independence_assuming_comparison"]
    W(f"| R | {P['R']['designs']} | {P['R']['den']} | {P['R']['num']} | {P['R']['rate_4dp']} | "
      f"{P['R']['bootstrap_95']['interval_4dp']} | {ia['clopper_pearson_95_R_4dp']} |")
    W(f"| B1 | {P['B1']['designs']} | {P['B1']['den']} | {P['B1']['num']} | {P['B1']['rate_4dp']} | "
      f"{P['B1']['bootstrap_95']['interval_4dp']} | {ia['clopper_pearson_95_B1_4dp']} |")
    W(f"| R - B1 | | | | {P['R_minus_B1']['difference_4dp']} | {P['R_minus_B1']['bootstrap_95']['interval_4dp']} | "
      f"Fisher p = {ia['fisher_exact_two_sided_p_R_vs_B1']:.4f} |")
    pp = P["pooled_B1_plus_R"]
    W(f"| pooled B1+R | {pp['designs']} | {pp['den']} | {pp['num']} | {pp['rate_4dp']} | "
      f"{pp['bootstrap_95_stratified']['interval_4dp']} (stratified); "
      f"{pp['bootstrap_95_sensitivity_20_designs_as_one_set']['interval_4dp']} (one set) | "
      f"{ia['clopper_pearson_95_pooled_4dp']} |")
    W(f"\n**Verdict (the plan's words):** {P['verdict']['word']}.\n")
    W("Per design (registers / verified found / found):\n")
    W("| R design | regs | verified | found |  | B1 design | regs | verified | found |")
    W("|---|---|---|---|---|---|---|---|---|")
    for a, b in zip(P["per_design_R"] + [None] * 10, P["per_design_B1"]):
        ra = f"`{a['design']}` | {a['den']} | {a['verified_found']} | {a['found']}" if a else " | | |"
        W(f"| {ra} |  | `{b['design']}` | {b['den']} | {b['verified_found']} | {b['found']} |")
    W("")
    W("## C. Secondary (descriptive)\n")
    ca = C["counter_all_structures_found_recall"]
    W("### counter all-structures found recall\n")
    W(f"* R {ca['R']['num']}/{ca['R']['den']} = {ca['R']['rate_4dp']}, bootstrap {ca['R']['bootstrap_95']['interval_4dp']}")
    W(f"* B1 {ca['B1']['num']}/{ca['B1']['den']} = {ca['B1']['rate_4dp']}, bootstrap {ca['B1']['bootstrap_95']['interval_4dp']}")
    W(f"* R - B1 {ca['R_minus_B1']['difference_4dp']}, bootstrap {ca['R_minus_B1']['bootstrap_95']['interval_4dp']}")
    W(f"* pooled {ca['pooled_B1_plus_R']['num']}/{ca['pooled_B1_plus_R']['den']} = {ca['pooled_B1_plus_R']['rate_4dp']}, "
      f"bootstrap {ca['pooled_B1_plus_R']['bootstrap_95_stratified']['interval_4dp']} (stratified), "
      f"{ca['pooled_B1_plus_R']['bootstrap_95_sensitivity_20_designs_as_one_set']['interval_4dp']} (one set)")
    ia = ca["independence_assuming_comparison"]
    W(f"* independence-assuming: Fisher p {ia['fisher_exact_two_sided_p_R_vs_B1']:.4f}; CP R {ia['clopper_pearson_95_R_4dp']}, "
      f"B1 {ia['clopper_pearson_95_B1_4dp']}, pooled {ia['clopper_pearson_95_pooled_4dp']}\n")
    W("### Per kind (strict; lenient identical where flagged)\n")
    for sname in ("R", "B1", "pooled_B1_plus_R"):
        W(f"**{sname}**\n")
        W("| kind | regs | designs | structs | found | recall | verified structs | verified found | v. recall | exact "
          "| v. exact | precision | v. precision | FP | v. FP | mean IoU | found@0.75 | strict = lenient |")
        W("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for c in KINDS:
            k = C["per_kind"][sname][c]
            s, a = k["summary"], k["all/strict"]
            W(f"| {c} | {s['registers']} | {s['designs_with_any']} | {s['structures']} | {s['found']} | "
              f"{fx(s['found_recall'])} | {s['verified_structures']} | {s['verified_found']} | "
              f"{fx(s['verified_found_recall'])} | {s['exact']} | {s['verified_exact']} | "
              f"{fx(s['precision_over_structures'])} | {fx(s['verified_precision_over_verified_structures'])} | "
              f"{s['false_positive_structures']} | {s['verified_false_positive_structures']} | "
              f"{fx(a['mean_iou_over_found'])} | {a['found_iou75']['num']} | {k['strict_equals_lenient_counts']} |")
        t = C["per_kind"][sname]["all_four_kinds_strict"]
        W(f"| all four | {t['registers']} | | {t['structures']} | {t['found']['num']} | {t['found']['rate_4dp']} | "
          f"{t['verified_structures']} | {t['verified_found']['num']} | {t['verified_found']['rate_4dp']} | "
          f"{t['exact']['num']} | {t['verified_exact']['num']} | {t['precision_over_structures']['rate_4dp']} | "
          f"{t['verified_precision']['rate_4dp']} | {t['false_positive_structures']} | "
          f"{t['verified_false_positive_structures']} | | | |\n")
        W(f"Register micro-F1 found {fx(t['micro_f1_found'])}, exact {fx(t['micro_f1_exact'])}; macro-F1 found "
          f"{fx(t['macro_f1_found_score_py_convention'])} (score.py convention) / "
          f"{fx(t['macro_f1_found_docs_S3_convention'])} (docs/S3.md convention), exact "
          f"{fx(t['macro_f1_exact_score_py_convention'])} / {fx(t['macro_f1_exact_docs_S3_convention'])}. "
          "Counter distinct design keys found_all / found_any / total: "
          + "/".join(str(C['per_kind'][sname]['counter']['all/strict']['distinct_design_keys'][k])
                     for k in ('found_all', 'found_any', 'total'))
          + f"; counter macro recall {fx(C['per_kind'][sname]['counter']['all/strict']['macro_found_recall_over_designs_with_any'])}.\n")
    for sname in ("R", "B1", "pooled_B1_plus_R"):
        for c in KINDS:
            k = C["per_kind"][sname][c]
            if not k["strict_equals_lenient_counts"]:
                al, vl = k["all/lenient"], k["verified/lenient"]
                W(f"* {sname} {c}: LENIENT differs from strict -- found {al['found']['num']}/{al['registers']} = "
                  f"{al['found']['rate_4dp']}, exact {al['exact']['num']}, precision "
                  f"{al['precision_over_structures']['num']}/{al['structures']}; verified found "
                  f"{vl['found']['num']}/{vl['registers']} = {vl['found']['rate_4dp']}")
    W("")
    W("### Per-kind bootstrap (kinds with registers in >= 3 designs of the set)\n")
    W("| kind | designs R / B1 / pooled | metric | R | B1 | pooled (stratified) | R - B1 |")
    W("|---|---|---|---|---|---|---|")
    for c in KINDS:
        e = C["per_kind_bootstrap"][c]
        dw = e["designs_with_registers"]
        for m in ("found", "verified_found", "exact", "verified_exact"):
            x = e[m]
            W(f"| {c} | {dw['R']} / {dw['B1']} / {dw['pooled']} | {m} | "
              f"{x.get('R', {}).get('interval_4dp', 'counts only')} | {x.get('B1', {}).get('interval_4dp', 'counts only')} | "
              f"{x.get('pooled_stratified', {}).get('interval_4dp', 'counts only')} | "
              f"{x.get('R_minus_B1', {}).get('interval_4dp', '-')} |")
    W("")
    W("### Found but unverified\n")
    for sname in ("R", "B1"):
        s = C["found_but_unverified"]["summary"][sname]
        W(f"* {sname}: {s['registers']} registers; by cause {s['by_cause']}; by kind {s['by_kind']}; exact among them "
          f"{s['exact_among_them']}")
    W(f"* pooled: {C['found_but_unverified']['summary']['pooled_B1_plus_R']}\n")
    W("### Misses and false positives (mechanical split, strict)\n")
    for sname in ("R", "B1"):
        m = C["misses_mechanical"]["summary"][sname]
        fpp = C["false_positives_mechanical"]["summary"][sname]
        W(f"* {sname} misses {m['total']}: {m['by_kind_and_category']}")
        W(f"* {sname} false positives {fpp['total']} ({fpp['verified']} verified): {fpp['by_kind_and_category']}; "
          f"verified by category {fpp['by_category_verified']}; matched-nothing by best register kind "
          f"{fpp['matched_nothing_by_best_register_kind']}")
    W("")
    W("### What the verified count is worth\n")
    W("| set | returned | scored | verified | claimed proven | verified not claimed | vacuous hold | unchecked params "
      "| dead bits | no liveness | LFSR polys certified | load share mean / max (n) | budget | unknown | "
      "unverified reasons |")
    W("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for sname in ("R", "B1", "pooled_B1_plus_R"):
        h = C["honesty"][sname]
        ls = h["load_hidden_share_over_verified_naming_one"]
        W(f"| {sname} | {h['structures_returned']} | {h['structures_scored']} | {h['verified_structures']} | "
          f"{h['claimed_proven_score_py']} | {h['verified_not_claimed_proven']} | {h['verified_vacuous_hold']} | "
          f"{h['verified_with_unchecked_params']} | {h['verified_with_dead_bits']} | "
          f"{h['verified_without_a_liveness_obligation']} | {h['verified_lfsr_poly_certified']} | "
          f"{fx(ls['mean'])} / {fx(ls['max'])} ({ls['n']}) | {h['budget_outcomes']} | {h['unknown_outcomes']} | "
          f"{h['unverified_reasons_all_structures']} |")
    W("")
    W("### Grouping (all flops; each set's own random-block chance floor)\n")
    W("| set | designs | AMI mean | median | min | max | ARI mean | random-block AMI mean / median | singletons AMI "
      "mean | AMI mean - floor | exact words | splits / merges | pair P / R / F1 (means) |")
    W("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for sname in ("R", "B1", "pooled_B1_plus_R"):
        g = C["grouping"][sname]["all_flops"]
        W(f"| {sname} | {g['designs']} | {fx(g['ami']['mean'])} | {fx(g['ami']['median'])} | {fx(g['ami']['min'])} | "
          f"{fx(g['ami']['max'])} | {fx(g['ari']['mean'])} | {fx(g['baseline_random_blocks_ami']['mean'])} / "
          f"{fx(g['baseline_random_blocks_ami']['median'])} | {fx(g['baseline_singletons_ami']['mean'])} | "
          f"{fx(g['ami_mean_minus_random_block_floor'])} | {g['exact_words_sum']}/{g['truth_words_multi_sum']} | "
          f"{g['splits_sum']} / {g['merges_sum']} | {fx(g['pair_precision']['mean'])} / "
          f"{fx(g['pair_recall']['mean'])} / {fx(g['pair_f1']['mean'])} |")
    W("")
    W("### Order (counter and the other kinds; both bands and pooled as honesty_table.py pools)\n")
    W("| set | kind | band | items | ordered | all correct | pairs | asserted | score | chance | kappa |")
    W("|---|---|---|---|---|---|---|---|---|---|---|")
    for sname in ("R", "B1", "pooled_B1_plus_R"):
        for k, v in C["order"][sname].items():
            if k.startswith("_"):
                continue
            for band, e in v["bands"].items():
                a = e["parts"].get("all", {})
                W(f"| {sname} | {k} | {band} | {e['pairs_found']} | {e['ordered']} | {e['all_correct']} | "
                  f"{a.get('pairs')} | {a.get('asserted')} | {fx(a.get('pairs_weighted_score'))} | "
                  f"{fx(a.get('pairs_weighted_chance'))} | {fx(a.get('kappa'))} |")
            p = v["pooled_over_both_bands_as_honesty_table"]
            W(f"| {sname} | {k} | **both** | {p['items']} | {p['ordered']} | {p['all_correct']} | {p['pairs']} | "
              f"{p['asserted']} | {fx(p['concordance'])} | {fx(p['chance'])} | {fx(p['kappa'])} |")
    W("")
    W("### Parameters\n")
    W("| set | certified | transcribed | combined | informative | majority baseline |")
    W("|---|---|---|---|---|---|")
    for sname in ("R", "B1", "pooled_B1_plus_R"):
        p = C["params"][sname]
        W(f"| {sname} | " + " | ".join(f"{p[k]['num']}/{p[k]['den']} = {p[k]['rate_4dp']}" for k in
                                      ("certified", "transcribed", "combined", "informative",
                                       "majority_baseline_over_all_compared")) + " |")
    W("")
    for sname in ("R",):
        W(f"{sname} per parameter: " + "; ".join(f"`{k}` {v['correct']}/{v['n']} (certified {v['certified_correct']}/"
                                                  f"{v['certified_compared']})" for k, v in C["params"][sname]
                                                  ["per_param"].items()))
        W(f"\n{sname} wrong parameters: " + ("; ".join(f"`{w['design']}` `{w['item']}` {w['param']} answered "
                                                        f"{json.dumps(w['result'])} truth {json.dumps(w['truth'])} "
                                                        f"({'certified' if w['certified'] else 'transcribed'})"
                                                        for w in C["params"][sname]["wrong"]) or "none") + "\n")
    W("### Bit level (all structures, strict)\n")
    W("| set | counter P/R/F1 | shift P/R/F1 | lfsr P/R/F1 | sync P/R/F1 | micro F1 | macro F1 (score.py / docs) |")
    W("|---|---|---|---|---|---|---|")
    for sname in ("R", "B1", "pooled_B1_plus_R"):
        b = C["bits"][sname]["all/strict"]
        W(f"| {sname} | " + " | ".join(f"{fx(b[c]['precision'], 3)} / {fx(b[c]['recall'], 3)} / {fx(b[c]['f1'], 3)}"
                                      for c in KINDS) + f" | {fx(b['_micro']['f1'])} | "
          f"{fx(b['_macro_f1_over_kinds_with_support_or_predictions'])} / "
          f"{fx(b['_macro_f1_docs_S3_convention_kinds_with_P_and_R_both_0_left_out'])} |")
    W("")
    W("### Per design, R\n")
    W("| design | flops | regs | structs | verified | counter r/f/v/e | shift r/f/v | lfsr r/f/v | sync r/f/v | "
      "AMI | ARI | params cert. | transcr. | tiers | dropped flops |")
    W("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in C["per_design_R"]["rows"]:
        k = {c: r[c] for c in KINDS}
        W(f"| `{r['design']}` | {r['universe_flops']} | {r['truth_registers_with_flops']} | {r['structures_returned']} | "
          f"{r['verified_structures']} | {k['counter']['registers']}/{k['counter']['found']}/"
          f"{k['counter']['verified_found']}/{k['counter']['exact']} | "
          + " | ".join(f"{k[c]['registers']}/{k[c]['found']}/{k[c]['verified_found']}"
                       for c in ("shift_register", "lfsr_crc", "synchronizer"))
          + f" | {fx(r['ami'])} | {fx(r['ari'])} | {r['params_certified']} | {r['params_transcribed']} | "
          f"{r['tiers']} | {r['dropped_flops']} |")
    W("")
    W("## D. Label quality (R)\n")
    W(f"Rule: {D['rule']}\n")
    for sname in ("R", "B1", "pooled_B1_plus_R"):
        W(f"* {sname}: tiers {D[sname]['all_kinds']['tiers']}; sub-tiers {D[sname]['all_kinds']['subtiers']}; "
          f"counter tiers {D[sname]['counter']['tiers']}")
    for sname in ("R", "B1"):
        W(f"* {sname} flop level: {D[sname]['flop_level_total']}")
    W("* outcome by tier, R: " + "; ".join(f"{t} {v['found']}/{v['registers']} found, {v['verified_found']} verified"
                                         for t, v in D["R"]["all_kinds"]["outcome_by_tier"].items()))
    pn = D["primary_with_tier_A_removed"]
    W(f"\n**Primary with Tier A removed:** R {pn['R']['num']}/{pn['R']['den']} = {pn['R']['rate_4dp']} "
      f"{pn['R']['bootstrap_95']['interval_4dp']}; B1 {pn['B1']['num']}/{pn['B1']['den']} = {pn['B1']['rate_4dp']} "
      f"{pn['B1']['bootstrap_95']['interval_4dp']}; R - B1 {pn['R_minus_B1']['difference_4dp']} "
      f"{pn['R_minus_B1']['bootstrap_95']['interval_4dp']}; pooled {pn['pooled_B1_plus_R']['num']}/"
      f"{pn['pooled_B1_plus_R']['den']} = {pn['pooled_B1_plus_R']['rate_4dp']} "
      f"{pn['pooled_B1_plus_R']['bootstrap_95_stratified']['interval_4dp']} (stratified).\n")
    ak = D["all_kinds_tier_A_removed"]
    W("All four kinds, Tier A removed: " + "; ".join(
        f"{s} found {ak[s]['found']['num']}/{ak[s]['registers']} = {ak[s]['found']['rate_4dp']}, verified "
        f"{ak[s]['verified_found']['num']}/{ak[s]['registers']} = {ak[s]['verified_found']['rate_4dp']}"
        for s in ("R", "B1", "pooled_B1_plus_R")) + "\n")
    W("## E. Mechanics (R)\n")
    s = E["summary"]
    for k, v in s.items():
        W(f"* {k}: {v}")
    W("")
    lg = E["ledger"]
    W(f"Ledger: {lg['lines_working_tree']} lines, hash chain intact {lg['working_tree_hash_chain_intact']}, "
      f"uncommitted lines {lg['uncommitted_lines']}, git status `{lg['git_status_porcelain'] or 'clean'}`, "
      f"freeze-4 attempts {lg['freeze_4_attempts_total']} over {len(lg['freeze_4_attempt_designs'])} designs, "
      f"exactly one per design {lg['exactly_one_attempt_per_design_under_freeze_4']}, record cross-checks pass "
      f"{lg['all_cross_checks_pass']}, ledger problems {lg['freeze_ledger_entries_problems'] or 'none'}.\n")
    lb = E["labelling"]
    W(f"Labelling: drawn {len(lb['drawn'])}, reserves used {lb['reserves_used']}, replaced_by {lb['replaced_by']}; "
      "failures: " + "; ".join(f"{x['id']} ({x['error']})" for x in lb["failures"]) + "\n")
    W("## F. References for the pooled set\n")
    W("| kind | pooled regs | pooled found | pooled verified found | holdout_rates items / found / rate | "
      "honesty_table regs / found / verified found |")
    W("|---|---|---|---|---|---|")
    for c in KINDS:
        p, h, t = F["pooled_set"][c], F["holdout_rates_json"][c], F["honesty_table_json_corpus_holdout"][c]
        W(f"| {c} | {p['registers']} | {p['found']} = {fx(p['found_recall'])} | {p['verified_found']} = "
          f"{fx(p['verified_found_recall'])} | {h['items']} / {h['found']} / {fx(h['found_rate'])} | "
          f"{t['registers']} / {t['found']} ({fx(t['found_recall'])}) / {t['verified_found']} "
          f"({fx(t['verified_found_recall'])}) |")
    W(f"\nCaveat: {F['caveat']}\n")
    W("## Cross-checks (B1 recomputed here against docs/S3.md)\n")
    for k, v in doc["cross_checks"]["against_docs_S3_md_freeze_1_published_figures"].items():
        W(f"* {'PASS' if v else 'FAIL'} -- {k}")
    W("")
    W("## Notes\n")
    for n in doc["notes"]:
        W(f"* {n}")
    W("")
    return "\n".join(L)


if __name__ == "__main__":
    main()
