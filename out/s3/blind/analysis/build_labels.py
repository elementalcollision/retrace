"""Build out/s3/blind/analysis/labels.json (+ .md) -- the labels lens of the S3 blind evaluation.
Helper, not frozen. Reads only; modifies no truth, no run record, nothing under tools/."""
import collections, glob, json, os, sys

ROOT = "/Users/dave/Jane_Street_Reverse_ASIC"
OUT = os.path.join(ROOT, "out/s3/blind/analysis")
KINDS = ["shift_register", "counter", "lfsr_crc", "synchronizer"]
sys.path.insert(0, ROOT)
from tools.s3 import score as S

RAW = json.load(open(os.path.join(OUT, "_raw.json")))["designs"]
LAB = json.load(open(os.path.join(ROOT, "out/s3/blind/labels.json")))


def run_path(design_id):
    c = [x for x in glob.glob(os.path.join(ROOT, "out/s3/runs/blind-*.json"))
         if f"blind-{design_id}-" in x and not x.endswith(".attempt.json")]
    assert len(c) == 1, (design_id, c)
    return c[0]


def tier(w):
    """A: the bit-level evidence CONTRADICTS the mapping. B: sound but narrowed. C: clean."""
    bad = sum(v for k, v in w["proof"].items() if k != "proven") + \
          sum(v for k, v in w["check"].items() if k != "match")
    if bad:
        return "A_contradicted"
    if w["bits_without_flop"]:
        return "B_narrowed"
    return "C_clean"


designs, pooled_rows = [], []
for d in RAW:
    sc = json.load(open(run_path(d["design_id"])))["evaluations"][0]["score"]
    st = sc["classes"]["all"]["registers"]["strict"]["per_kind"]
    ve = sc["classes"]["verified"]["registers"]["strict"]["per_kind"]
    allreg = d["all_registers"]
    per_kind = {}
    for c in KINDS:
        a, v = st[c], ve[c]
        names = sorted(n for n, w in allreg.items() if S.canonical_kind(w["kind"]) == c
                       and n in set(a["found_registers"]) | set(a["missed"]) )
        # the scorer's own denominator list is found_registers + missed (both uncapped here)
        assert len(a["found_registers"]) == a["found"]["registers_found"]
        assert len(a["found_registers"]) + len(a["missed"]) == a["registers"], (d["id"], c)
        den = sorted(set(a["found_registers"]) | set(a["missed"]))
        tiers = {n: tier(allreg[n]) for n in den}
        found = set(a["found_registers"]); vfound = set(v["found_registers"])
        per_kind[c] = {
            "registers": a["registers"], "structures": a["structures"],
            "structures_matched": a["found"]["structures_matched"],
            "found": a["found"]["registers_found"], "exact": a["exact"]["registers_found"],
            "verified_found": v["found"]["registers_found"],
            "small_support": a["small_support"],
            "distinct_design_keys": a["distinct_designs"]["total"],
            "distinct_design_keys_found_all": a["distinct_designs"]["found_all"],
            "via_units": a["via_units"],
            "label_tiers": dict(collections.Counter(tiers.values())),
            "registers_by_tier": {t: sorted(n for n, x in tiers.items() if x == t)
                                  for t in sorted(set(tiers.values()))},
            "found_by_tier": dict(collections.Counter(tiers[n] for n in found)),
            "verified_found_by_tier": dict(collections.Counter(tiers[n] for n in vfound)),
        }
        for n in den:
            pooled_rows.append({"design": d["id"], "kind": c, "register": n, "tier": tiers[n],
                                "found": n in found, "exact": n in set(a["exact"].get("found_registers", []))
                                if isinstance(a["exact"], dict) and "found_registers" in a["exact"] else None,
                                "verified_found": n in vfound})
    scored = [r for r in pooled_rows if r["design"] == d["id"]]
    tcount = collections.Counter(r["tier"] for r in scored)
    designs.append({
        "id": d["id"], "design_id": d["design_id"], "shuttle": d["shuttle"],
        "author": d["source"].get("author"), "title": d["source"].get("title"),
        "replaces": d["replaces"], "layout_format": d["layout_format"],
        "rtl": {"repo": json.load(open(os.path.join(ROOT, f"out/s3/truth_{d['design_id']}.json")))["meta"]["rtl"]["repo"],
                "commit": json.load(open(os.path.join(ROOT, f"out/s3/truth_{d['design_id']}.json")))["meta"]["rtl"]["commit"]},
        "counts": d["counts"], "rtl_bits": d["rtl_bits"],
        "registers_by_kind": d["registers_by_kind"],
        "scorer_view": d["scorer_view"],
        "proof": d["proof"], "functional_check": d["functional_check"],
        "join": d["join"], "anonymisation": d["anonymisation"],
        "units": d["units"],
        "scored_structure_registers": sum(per_kind[c]["registers"] for c in KINDS),
        "label_tiers": dict(tcount),
        "weak_structure_registers": d["weak_structure_registers"],
        "per_kind": per_kind,
        "headline": {"structures": sc["headline"]["structures"], "verified": sc["headline"]["verified"],
                     "dropped_flops": sc["headline"]["dropped_flops"]},
        "permutations_agree": True,
    })

json.dump({"designs": designs, "rows": pooled_rows}, open(os.path.join(OUT, "_rows.json"), "w"), indent=1)
print("rows:", len(pooled_rows))
for t, n in collections.Counter(r["tier"] for r in pooled_rows).most_common():
    print(" ", t, n)
