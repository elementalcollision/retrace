"""Independent recomputation of the S3 replication figures (cross-check of numbers.json).

Written from the raw run records (out/s3/runs/blind-*.json), the truth files (out/s3/truth_*.json),
tools/s3/score.py's DEFINITIONS (read, never imported) and docs/S3_REPLICATION_PLAN.md. It does not
read, import or copy compute_numbers.py, and it imports nothing from tools/.

Run: .venv/bin/python -B out/s3/replication/analysis/xcheck.py
Writes: out/s3/replication/analysis/xcheck.json
"""
import sys

sys.dont_write_bytecode = True

import ast
import collections
import glob
import hashlib
import json
import math
import os
import statistics
from fractions import Fraction

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
os.chdir(ROOT)

KINDS = ("shift_register", "counter", "lfsr_crc", "synchronizer")   # schema.STRUCTURE_KINDS
IOU_MIN, MULTI = 0.5, 2                                             # score.IOU_MIN, score.MULTI
ALIASES = {"shift": "shift_register", "lfsr": "lfsr_crc", "regfile": "register_file_word", "fsm": "fsm_state",
           "sync": "synchronizer", "data": "data_register"}          # schema._KIND_ALIASES
B = 10_000
SEED = 20260923
FREEZE1 = "1ee6a4789435"
FREEZE4 = "1196c56304e3"

R_RECORDS = [   # the ten replication records, as the brief lists them (run order)
    "out/s3/runs/blind-tt04__tt_um_jayraj4021_SAP1_cpu-20260923T162732Z-f054fba37113.json",
    "out/s3/runs/blind-ttsky26b__tt_um_tiny_8bit_cpu-20260923T162838Z-ad288b805d1f.json",
    "out/s3/runs/blind-tt06__tt_um_SJ-20260923T163017Z-cb0653238382.json",
    "out/s3/runs/blind-tt06__tt_um_kwilke_cdc_fifo-20260923T164118Z-2a71c3753920.json",
    "out/s3/runs/blind-ttsky25b__tt_um_yorimichi_kittscanner-20260923T164224Z-26c058d662ee.json",
    "out/s3/runs/blind-tt05__tt_um_digital_clock_sellicott-20260923T164430Z-0b3815420281.json",
    "out/s3/runs/blind-tt05__tt_um_nickjhay_processor-20260923T164730Z-bb64c58cedec.json",
    "out/s3/runs/blind-ttsky25b__tt_um_ieeeuoftasic_simproc-20260923T164846Z-96397bfe3677.json",
    "out/s3/runs/blind-ttsky26a__tt_um_parakeet-20260923T165027Z-5cbe0d76609a.json",
    "out/s3/runs/blind-ttcad25a__tt_um_space_invaders_game-20260923T165200Z-120ddfb7dc8a.json",
]


def canon(k):
    return ALIASES.get(k, k)


def sha256_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def truth_hash(t):   # schema.truth_hash, re-typed
    core = {k: t.get(k) for k in ("schema", "design", "registers", "units", "flops", "unmapped_flops")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def score_sources():
    """RECOGNIZER_SOURCES and OUT_OF_SAMPLE_SOURCES read out of score.py's text (not imported)."""
    tree = ast.parse(open("tools/s3/score.py").read())
    env = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name == "RECOGNIZER_SOURCES":
                env[name] = ast.literal_eval(node.value)
            elif name == "OUT_OF_SAMPLE_SOURCES":
                v = node.value
                assert isinstance(v, ast.BinOp) and isinstance(v.left, ast.Name) and v.left.id == "RECOGNIZER_SOURCES"
                env[name] = env["RECOGNIZER_SOURCES"] + ast.literal_eval(v.right)
    return env["RECOGNIZER_SOURCES"], env["OUT_OF_SAMPLE_SOURCES"]


# ------------------------------------------------------------------------------------------------
# records

def load_sets():
    b1 = []
    for p in sorted(glob.glob("out/s3/runs/blind-*.json")):
        if p.endswith(".attempt.json"):
            continue
        r = json.load(open(p))
        if r["freeze"]["freeze_hash"].startswith(FREEZE1) and r["design"] != "puzzle":
            b1.append((p, r))
    b1.sort(key=lambda pr: pr[1]["created"])   # run order
    rr = [(p, json.load(open(p))) for p in R_RECORDS]
    assert len(b1) == 10 and len(rr) == 10
    for _, r in rr:
        assert r["freeze"]["freeze_hash"].startswith(FREEZE4), r["design"]
    return b1, rr


def same_across_perms(r, getter, what):
    vals = [json.dumps(getter(e), sort_keys=True) for e in r["evaluations"]]
    if len(set(vals)) != 1:
        raise AssertionError(f"{r['design']}: {what} differs across permutations")
    return getter(r["evaluations"][0])


# ------------------------------------------------------------------------------------------------
# my own truth view and matching (score.py's rules re-implemented: Truth, _items, _held, match,
# _register_level's crediting), used to check the per-register lists the records carry

class TV:
    def __init__(self, t):
        shadow = set()
        for r in t["registers"]:
            for b in r.get("bits", []):
                for f in list(b.get("shadow_flops") or []) + list(b.get("duplicates") or []):
                    shadow.add(f)
        self.shadow = shadow
        self.universe = {f for f in t["flops"] if f not in shadow}
        members = collections.defaultdict(set)
        for f, v in t["flops"].items():
            if f in self.universe:
                for n in v.get("registers", []):
                    members[n].add(f)
        self.kind, self.flops, self.accepts, self.bit_alt, self.regs = {}, {}, {}, {}, {}
        for r in t["registers"]:
            n = r["name"]
            self.regs[n] = r
            self.kind[n] = canon(r["kind"])
            self.accepts[n] = {self.kind[n]} | {canon(k) for k in r.get("alt_kinds") or []}
            fl = set()
            for b in r["bits"]:
                f = b.get("flop")
                if f in self.universe:
                    fl.add(f)
                    if b.get("alt_kinds") is not None:
                        self.bit_alt.setdefault((n, f), set()).update(canon(k) for k in b["alt_kinds"])
            self.flops[n] = frozenset(fl | members.get(n, set()))
        self.scored = [r["name"] for r in t["registers"] if self.flops[r["name"]]]
        self.units = []
        for u in t.get("units") or []:
            k = canon(u["kind"])
            mem = [m for m in u["registers"] if m in self.regs]
            if u.get("flops") is not None:
                fl = frozenset(f for f in u["flops"] if f in self.universe)
            else:
                fl = frozenset().union(*(self.flops[m] for m in mem)) if mem else frozenset()
            if not fl:
                continue
            credit = [m for m in mem if all(k in self.flop_acc(m, f) for f in fl & self.flops[m])]
            chain = k == "synchronizer" and bool(mem) and all(self.kind[m] == "synchronizer" for m in mem)
            self.units.append({"name": u["name"], "kind": k, "registers": mem, "credit": credit, "flops": fl,
                               "chain": chain})
        self.chain_members = {m for u in self.units if u["chain"] for m in u["registers"]}

    def flop_acc(self, n, f):
        a = self.bit_alt.get((n, f))
        return self.accepts[n] if a is None else {self.kind[n]} | a

    def den(self, c):
        return [n for n in self.scored if self.kind[n] == c]


def my_structs(tv, e):
    out = []
    for i, s in enumerate(e["result"]["structures"]):
        keep = [f for f in s["flops"] if f in tv.universe]
        if not keep:
            continue
        out.append({"i": len(out), "pos": i, "id": s["id"], "kind": canon(s["kind"]), "flops": frozenset(keep),
                    "dropped": len(s["flops"]) - len(keep),
                    "hkey": hashlib.sha256("\n".join(sorted(keep)).encode()).hexdigest(),
                    "verified": bool(e["verified_flags"][i])})
    return out


def my_credit(tv, structs, lenient):
    items = []
    for n in tv.scored:
        if not lenient and n in tv.chain_members:
            continue
        items.append({"name": n, "unit": False, "flops": tv.flops[n],
                      "accepts": tv.accepts[n] if lenient else {tv.kind[n]}})
    for u in tv.units:
        if lenient or u["chain"]:
            items.append({"name": u["name"], "unit": True, "flops": u["flops"], "registers": u["registers"],
                          "credit": u["credit"], "accepts": {u["kind"]}})
    cands = []
    for i, s in enumerate(structs):
        for j, it in enumerate(items):
            inter = len(s["flops"] & it["flops"])
            if not inter:
                continue
            iou = inter / len(s["flops"] | it["flops"])
            if iou > IOU_MIN and (len(it["flops"]) < MULTI or inter >= MULTI):
                cands.append((-iou, it["unit"], s["hkey"], s["pos"], it["name"], i, j))
    cands.sort()
    used_s, used_r, credit = set(), set(), {}
    for negiou, _u, _h, _p, _n, i, j in cands:
        it, s = items[j], structs[i]
        if i in used_s:
            continue
        if it["unit"]:
            held = []
            for m in it["registers"]:
                fm = tv.flops[m]
                h = len(s["flops"] & fm)
                if 2 * h > len(fm) and (len(fm) < MULTI or h >= MULTI):
                    held.append(m)
            regs = [m for m in held if m not in used_r]
            if not regs:
                continue
        else:
            if it["name"] in used_r:
                continue
            regs = [it["name"]]
        used_s.add(i)
        used_r.update(regs)
        ok = s["kind"] in it["accepts"]
        got = [r for r in regs if r in it["credit"]] if it["unit"] else regs
        if ok and got:
            for r in got:
                credit[r] = s["id"]
    return credit


# ------------------------------------------------------------------------------------------------
# per-design extraction

def tier_of(reg, universe):
    bits = reg["bits"]
    mapped = [b for b in bits if b.get("flop") is not None and b.get("flop") in universe]
    if any(b.get("proof") != "proven" or b.get("check") != "match" for b in mapped):
        return "A1" if any(b.get("check") != "match" for b in mapped) else "A2"
    if any(b.get("flop") is None for b in bits):
        return "B"
    return "C"


def design_row(path, r):
    d = r["design"]
    tpath = f"out/s3/truth_{d}.json"
    t = json.load(open(tpath))
    th = truth_hash(t)
    ths = {e["score"]["truth_hash"] for e in r["evaluations"]}
    row = {"design": d, "record": path, "truth": tpath, "truth_hash_matches_all_evaluations": ths == {th},
           "record_valid": not r["invalid_reasons"] and all(not e["invalid_reasons"] for e in r["evaluations"]),
           "distinct_answers": r["spread"]["distinct_answers"],
           "canonical_result_sha256_distinct": len({e["canonical_result_sha256"] for e in r["evaluations"]})}
    # per-kind counts from the record's own score blocks (asserted identical in all 5 permutations)
    pk = {}
    for sub in ("all", "verified"):
        for mode in ("strict", "lenient"):
            blk = same_across_perms(r, lambda e, s=sub, m=mode: {
                k: {"registers": v["registers"], "structures": v["structures"],
                    "found": v["found"]["registers_found"], "exact": v["exact"]["registers_found"],
                    "found_registers": v["found_registers"], "missed": v["missed"]}
                for k, v in e["score"]["classes"][s]["registers"][m]["per_kind"].items()}, f"{sub}/{mode}")
            pk[(sub, mode)] = blk
    row["per_kind"] = {f"{sub}/{mode}": {k: {x: v[x] for x in ("registers", "structures", "found", "exact")}
                                         for k, v in blk.items()} for (sub, mode), blk in pk.items()}
    # honesty cross-check of the primary
    hon = same_across_perms(r, lambda e: e["score"]["honesty"]["per_kind"]["counter"], "honesty.counter")
    c_all, c_ver = pk[("all", "strict")]["counter"], pk[("verified", "strict")]["counter"]
    assert hon["registers"] == c_all["registers"] == c_ver["registers"]
    assert hon["verified_found_registers"] == c_ver["found"] and hon["found_registers"] == c_all["found"]
    row["counter"] = {"registers": c_all["registers"], "found": c_all["found"], "verified_found": c_ver["found"]}

    # my own matching against the record's per-register lists
    tv = TV(t)
    mism = []
    for e in r["evaluations"]:
        ss = my_structs(tv, e)
        for sub, sel in (("all", ss), ("verified", [s for s in ss if s["verified"]])):
            for mode in ("strict", "lenient"):
                cr = my_credit(tv, sel, mode == "lenient")
                blk = e["score"]["classes"][sub]["registers"][mode]["per_kind"]
                for k in KINDS:
                    den = tv.den(k)
                    mine = sorted(n for n in den if n in cr)
                    if len(den) != blk[k]["registers"] or mine != blk[k]["found_registers"]:
                        mism.append({"perm": e["label"], "sub": sub, "mode": mode, "kind": k,
                                     "mine": mine, "record": blk[k]["found_registers"],
                                     "den_mine": len(den), "den_record": blk[k]["registers"]})
    row["own_matching_mismatches"] = mism

    # label tiers over the scored structure-kind registers (denominators = found + missed, record lists)
    tiers, tiers_counter = collections.Counter(), collections.Counter()
    tier_rows = []
    fa, fv = pk[("all", "strict")], pk[("verified", "strict")]
    for k in KINDS:
        den = sorted(fa[k]["found_registers"] + fa[k]["missed"])
        assert den == sorted(tv.den(k)), (d, k)
        for n in den:
            tr = tier_of(tv.regs[n], tv.universe)
            tiers[tr] += 1
            if k == "counter":
                tiers_counter[tr] += 1
            tier_rows.append({"kind": k, "register": n, "tier": tr, "found": n in fa[k]["found_registers"],
                              "verified_found": n in fv[k]["found_registers"]})
    row["tiers"] = dict(tiers)
    row["tiers_counter"] = dict(tiers_counter)
    row["tier_rows"] = tier_rows
    # a variant: Tier B also when the register's declared width exceeds its bit list
    row["tier_B_width_variant"] = sum(1 for x in tier_rows if x["tier"] == "C"
                                      and int(tv.regs[x["register"]].get("width") or 0) > len(tv.regs[x["register"]]["bits"]))
    # counter, Tier A removed
    ca = [x for x in tier_rows if x["kind"] == "counter" and not x["tier"].startswith("A")]
    row["counter_tierA_removed"] = {"registers": len(ca), "found": sum(x["found"] for x in ca),
                                    "verified_found": sum(x["verified_found"] for x in ca)}
    # flop level: labelled structure-kind flops; refuted; refuted and mismatching
    sk_flops, refuted, refmis = set(), set(), set()
    for k in KINDS:
        for n in tv.den(k):
            sk_flops |= tv.flops[n]
            for b in tv.regs[n]["bits"]:
                f = b.get("flop")
                if f in tv.universe:
                    if b.get("proof") == "refuted":
                        refuted.add(f)
                        if b.get("check") == "mismatch":
                            refmis.add(f)
    row["flop_level"] = {"structure_kind_flops": len(sk_flops), "refuted": len(refuted),
                         "refuted_and_mismatching": len(refmis)}

    # grouping
    g = same_across_perms(r, lambda e: e["score"]["grouping"]["all_flops"], "grouping")
    row["grouping"] = {"ami": g["ami"], "ari": g["ari"], "n": g["n"],
                       "singletons_ami": g["baseline_singletons"]["ami"],
                       "random_blocks_ami_mean": g["baseline_random_blocks"]["ami"]["mean"],
                       "spread_ami_mean": r["spread"]["metrics"]["ami"]["mean"]}
    return row


# ------------------------------------------------------------------------------------------------
# statistics

def ratio_boot(num, den, idx):
    N = num[idx].sum(axis=1)
    D = den[idx].sum(axis=1)
    ok = D > 0
    out = np.full(idx.shape[0], np.nan)
    out[ok] = N[ok] / D[ok]
    return out


def pct(x):
    x = x[~np.isnan(x)]
    lo, hi = np.percentile(x, [2.5, 97.5])
    return [float(lo), float(hi)]


def boot_all(numR, denR, numB, denB, order="R_first"):
    """My scheme: a fresh default_rng(SEED) per interval; for R - B1 one generator draws the R matrix
    first, then B1's; pooled = the 20 designs (B1 then R, each in run order) as ONE set; the
    stratified pooled variant draws B1 then R from one fresh generator."""
    nR, nB = len(numR), len(numB)
    res = {}
    rng = np.random.default_rng(SEED)
    bR = ratio_boot(numR, denR, rng.integers(0, nR, size=(B, nR)))
    res["R"] = {"ci": pct(bR), "undefined": int(np.isnan(bR).sum())}
    rng = np.random.default_rng(SEED)
    bB = ratio_boot(numB, denB, rng.integers(0, nB, size=(B, nB)))
    res["B1"] = {"ci": pct(bB), "undefined": int(np.isnan(bB).sum())}
    rng = np.random.default_rng(SEED)
    if order == "R_first":
        iR = rng.integers(0, nR, size=(B, nR))
        iB = rng.integers(0, nB, size=(B, nB))
    else:
        iB = rng.integers(0, nB, size=(B, nB))
        iR = rng.integers(0, nR, size=(B, nR))
    d = ratio_boot(numR, denR, iR) - ratio_boot(numB, denB, iB)
    res["R_minus_B1"] = {"ci": pct(d), "undefined": int(np.isnan(d).sum()), "draw_order": order}
    num = np.concatenate([numB, numR])
    den = np.concatenate([denB, denR])
    rng = np.random.default_rng(SEED)
    bp = ratio_boot(num, den, rng.integers(0, nR + nB, size=(B, nR + nB)))
    res["pooled_one_set"] = {"ci": pct(bp), "undefined": int(np.isnan(bp).sum())}
    rng = np.random.default_rng(SEED)
    iB2 = rng.integers(0, nB, size=(B, nB))
    iR2 = rng.integers(0, nR, size=(B, nR))
    N = numB[iB2].sum(1) + numR[iR2].sum(1)
    D = denB[iB2].sum(1) + denR[iR2].sum(1)
    bs = np.where(D > 0, N / np.where(D > 0, D, 1), np.nan)
    res["pooled_stratified_B1_then_R"] = {"ci": pct(bs), "undefined": int(np.isnan(bs).sum())}
    return res


def fisher_two_sided(a, b, c, d):
    """Fisher's exact test on [[a, b], [c, d]], two-sided: the sum of the probabilities of every table
    with the same margins that is no more probable than the observed one (relative tolerance 1e-7,
    the convention scipy uses)."""
    r1, r2, c1 = a + b, c + d, a + c
    n = r1 + r2
    lo, hi = max(0, c1 - r2), min(r1, c1)
    tot = math.comb(n, c1)
    p = {x: Fraction(math.comb(r1, x) * math.comb(r2, c1 - x), tot) for x in range(lo, hi + 1)}
    obs = p[a]
    return float(sum(v for v in p.values() if v <= obs * Fraction(10**7 + 1, 10**7)))


def binom_cdf(k, n, p):   # P(X <= k)
    return sum(math.comb(n, i) * p**i * (1 - p)**(n - i) for i in range(0, k + 1))


def clopper_pearson(x, n, alpha=0.05):
    def solve(f, target, increasing):
        lo, hi = 0.0, 1.0
        for _ in range(200):
            mid = (lo + hi) / 2
            v = f(mid)
            if (v < target) == increasing:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    lower = 0.0 if x == 0 else solve(lambda p: 1 - binom_cdf(x - 1, n, p), alpha / 2, True)
    upper = 1.0 if x == n else solve(lambda p: binom_cdf(x, n, p), alpha / 2, False)
    return [lower, upper]


# ------------------------------------------------------------------------------------------------

def main():
    rec_src, oos = score_sources()
    b1, rr = load_sets()
    out = {"sources": {"RECOGNIZER_SOURCES": list(rec_src), "OUT_OF_SAMPLE_SOURCES": list(oos)}}

    # A. pooling precondition
    def code12(r):
        return {f"tools/s3/{n}": r["code"].get(f"tools/s3/{n}") for n in oos}
    b1_code = {json.dumps(code12(r), sort_keys=True) for _, r in b1}
    b1_rs = {json.dumps(r["recognizer_sources"], sort_keys=True) for _, r in b1}
    b1_rs_eval = {json.dumps(e["recognizer"]["recognizer_sources"], sort_keys=True) for _, r in b1 for e in r["evaluations"]}
    assert len(b1_code) == 1 and len(b1_rs) == 1, "B1 records disagree among themselves"
    ref_code = json.loads(b1_code.pop())
    ref_rs = json.loads(b1_rs.pop())
    tree = {f"tools/s3/{n}": sha256_file(f"tools/s3/{n}") for n in oos}
    pre = []
    for p, r in rr:
        c = code12(r)
        mm = sorted(k for k in c if c[k] != ref_code[k] or c[k] is None)
        rs_mm = sorted(k for k in set(ref_rs) | set(r["recognizer_sources"])
                       if ref_rs.get(k) != r["recognizer_sources"].get(k))
        ev_mm = sum(1 for e in r["evaluations"]
                    if json.dumps(e["recognizer"]["recognizer_sources"], sort_keys=True) != json.dumps(ref_rs, sort_keys=True))
        other = sorted(k for k in set(r["code"]) | set(b1[0][1]["code"]) if k not in c
                       and r["code"].get(k) != b1[0][1]["code"].get(k))
        pre.append({"design": r["design"], "oos12_mismatches": mm, "recognizer_sources_mismatches": rs_mm,
                    "evaluations_with_recognizer_sources_mismatch": ev_mm, "oos12_count": len(c),
                    "recognizer_sources_count": len(r["recognizer_sources"]),
                    "other_code_files_differing_from_B1": other})
    out["A_pooling_precondition"] = {
        "holds_for_all": all(not x["oos12_mismatches"] and not x["recognizer_sources_mismatches"]
                             and not x["evaluations_with_recognizer_sources_mismatch"] for x in pre),
        "B1_records_agree_among_themselves": True,
        "B1_evaluation_recognizer_sources_distinct": len(b1_rs_eval),
        "oos12_equal_current_tree": tree == ref_code,
        "per_R_record": pre}
    excluded = {x["design"] for x in pre if x["oos12_mismatches"] or x["recognizer_sources_mismatches"]}

    rowsB = [design_row(p, r) for p, r in b1]
    rowsR = [design_row(p, r) for p, r in rr if r["design"] not in excluded]
    out["designs"] = {"B1": [x["design"] for x in rowsB], "R": [x["design"] for x in rowsR], "excluded": sorted(excluded)}
    out["checks"] = {
        "truth_hash_ok": {x["design"]: x["truth_hash_matches_all_evaluations"] for x in rowsB + rowsR},
        "valid": {x["design"]: x["record_valid"] for x in rowsB + rowsR},
        "distinct_answers": {x["design"]: x["distinct_answers"] for x in rowsB + rowsR},
        "own_matching_mismatches": {x["design"]: x["own_matching_mismatches"] for x in rowsB + rowsR
                                    if x["own_matching_mismatches"]}}

    def arrays(rows, key, sub="counter"):
        num = np.array([x[sub][key] for x in rows], dtype=float)
        den = np.array([x[sub]["registers"] for x in rows], dtype=float)
        return num, den

    def outcome(key, sub="counter"):
        nR, dR = arrays(rowsR, key, sub)
        nB, dB = arrays(rowsB, key, sub)
        o = {"R": {"x": int(nR.sum()), "n": int(dR.sum()), "rate": float(nR.sum() / dR.sum())},
             "B1": {"x": int(nB.sum()), "n": int(dB.sum()), "rate": float(nB.sum() / dB.sum())}}
        o["R_minus_B1"] = o["R"]["rate"] - o["B1"]["rate"]
        o["pooled"] = {"x": o["R"]["x"] + o["B1"]["x"], "n": o["R"]["n"] + o["B1"]["n"]}
        o["pooled"]["rate"] = o["pooled"]["x"] / o["pooled"]["n"]
        o["bootstrap"] = boot_all(nR, dR, nB, dB, "R_first")
        o["bootstrap_B1_first_diff"] = boot_all(nR, dR, nB, dB, "B1_first")["R_minus_B1"]
        o["fisher_p_R_vs_B1"] = fisher_two_sided(o["R"]["x"], o["R"]["n"] - o["R"]["x"],
                                                 o["B1"]["x"], o["B1"]["n"] - o["B1"]["x"])
        o["clopper_pearson"] = {s: clopper_pearson(o[s]["x"], o[s]["n"]) for s in ("R", "B1", "pooled")}
        lo, hi = o["bootstrap"]["R_minus_B1"]["ci"]
        o["verdict"] = "consistent with freeze 1" if lo <= 0 <= hi else ("higher" if lo > 0 else "lower")
        o["designs_with_registers"] = {"R": int((dR > 0).sum()), "B1": int((dB > 0).sum())}
        return o

    out["B_primary_counter_verified_found"] = outcome("verified_found")
    out["C_counter_all_structures_found"] = outcome("found")
    out["D_primary_tierA_removed"] = outcome("verified_found", "counter_tierA_removed")
    out["D2_counter_found_tierA_removed"] = {s: {"x": int(sum(x["counter_tierA_removed"]["found"] for x in rows)),
                                                 "n": int(sum(x["counter_tierA_removed"]["registers"] for x in rows))}
                                            for s, rows in (("R", rowsR), ("B1", rowsB))}

    # E. per kind, R and B1 (strict and lenient; found and verified-found; structures)
    def per_kind(rows):
        res = {}
        for mode in ("strict", "lenient"):
            res[mode] = {}
            for k in KINDS:
                a = [x["per_kind"][f"all/{mode}"][k] for x in rows]
                v = [x["per_kind"][f"verified/{mode}"][k] for x in rows]
                res[mode][k] = {"registers": sum(z["registers"] for z in a),
                                "designs_with_registers": sum(1 for z in a if z["registers"]),
                                "structures": sum(z["structures"] for z in a),
                                "found": sum(z["found"] for z in a),
                                "exact": sum(z["exact"] for z in a),
                                "verified_structures": sum(z["structures"] for z in v),
                                "verified_found": sum(z["found"] for z in v),
                                "verified_exact": sum(z["exact"] for z in v)}
        return res
    out["E_per_kind"] = {"R": per_kind(rowsR), "B1": per_kind(rowsB)}

    # F. grouping AMI with each set's chance floor
    def grouping(rows):
        ami = [x["grouping"]["ami"] for x in rows]
        sing = statistics.fmean(x["grouping"]["singletons_ami"] for x in rows)
        rb = statistics.fmean(x["grouping"]["random_blocks_ami_mean"] for x in rows)
        floor = max(sing, rb)
        return {"n": len(ami), "ami_mean": statistics.fmean(ami), "ami_median": statistics.median(ami),
                "ami_min": min(ami), "ami_max": max(ami),
                "singletons_ami_mean": sing, "random_blocks_ami_mean": rb, "chance_floor": floor,
                "ami_mean_minus_floor": statistics.fmean(ami) - floor,
                "per_design": {x["design"]: x["grouping"]["ami"] for x in rows},
                "spread_mean_agrees": all(abs(x["grouping"]["ami"] - x["grouping"]["spread_ami_mean"]) < 1e-12 for x in rows)}
    out["F_grouping"] = {"R": grouping(rowsR), "B1": grouping(rowsB)}

    # G. label tiers
    def tiers(rows):
        t = collections.Counter()
        tc = collections.Counter()
        fl = collections.Counter()
        by = collections.defaultdict(lambda: {"registers": 0, "found": 0, "verified_found": 0})
        for x in rows:
            t.update(x["tiers"])
            tc.update(x["tiers_counter"])
            fl.update(x["flop_level"])
            for y in x["tier_rows"]:
                b = by[y["tier"]]
                b["registers"] += 1
                b["found"] += y["found"]
                b["verified_found"] += y["verified_found"]
        return {"all_kinds": {"A": t["A1"] + t["A2"], "A1": t["A1"], "A2": t["A2"], "B": t["B"], "C": t["C"],
                              "total": sum(t.values())},
                "counter": {"A": tc["A1"] + tc["A2"], "A1": tc["A1"], "A2": tc["A2"], "B": tc["B"], "C": tc["C"],
                            "total": sum(tc.values())},
                "by_tier_found": dict(by),
                "flop_level": dict(fl),
                "tier_B_width_variant_extra": sum(x["tier_B_width_variant"] for x in rows),
                "per_design": {x["design"]: x["tiers"] for x in rows}}
    out["G_tiers"] = {"R": tiers(rowsR), "B1": tiers(rowsB)}
    out["per_design"] = {s: [{k: x[k] for k in ("design", "counter", "counter_tierA_removed", "tiers",
                                                  "tiers_counter", "flop_level", "grouping")} for x in rows]
                         for s, rows in (("R", rowsR), ("B1", rowsB))}
    out["tier_rows_R"] = [dict(y, design=x["design"]) for x in rowsR for y in x["tier_rows"]]

    with open("out/s3/replication/analysis/xcheck.json", "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    # print a summary
    for key in ("B_primary_counter_verified_found", "C_counter_all_structures_found", "D_primary_tierA_removed"):
        o = out[key]
        print(key)
        for s in ("R", "B1", "pooled"):
            print(f"  {s}: {o[s]['x']}/{o[s]['n']} = {o[s]['rate']:.4f}  CP {o['clopper_pearson'][s]}")
        print(f"  R-B1 = {o['R_minus_B1']:.4f}")
        for k, v in o["bootstrap"].items():
            print(f"  boot {k}: {v}")
        print(f"  boot R-B1 (B1 drawn first): {o['bootstrap_B1_first_diff']}")
        print(f"  fisher p = {o['fisher_p_R_vs_B1']:.6f}; verdict: {o['verdict']}")
    print("precondition holds:", out["A_pooling_precondition"]["holds_for_all"])
    print("own-matching mismatches:", out["checks"]["own_matching_mismatches"] or "none")
    print(json.dumps(out["E_per_kind"]["R"], indent=None))
    print(json.dumps({s: {k: v for k, v in out["F_grouping"][s].items() if k != "per_design"} for s in ("R", "B1")}))
    print(json.dumps({s: {k: out["G_tiers"][s][k] for k in ("all_kinds", "counter", "flop_level", "tier_B_width_variant_extra")}
                      for s in ("R", "B1")}))


if __name__ == "__main__":
    main()
