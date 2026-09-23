import collections, json, os
OUT = "/Users/dave/Jane_Street_Reverse_ASIC/out/s3/blind/analysis"
KINDS = ["shift_register", "counter", "lfsr_crc", "synchronizer"]
D = json.load(open(os.path.join(OUT, "_rows.json")))
designs, rows = D["designs"], D["rows"]
by = {d["id"]: d for d in designs}

def pool_designs(ids):
    t = {c: collections.Counter() for c in KINDS}
    for i in ids:
        for c in KINDS:
            pk = by[i]["per_kind"][c]
            for k in ("registers", "structures", "structures_matched", "found", "exact",
                      "verified_found", "distinct_design_keys", "distinct_design_keys_found_all"):
                t[c][k] += pk[k]
    return {c: dict(t[c]) for c in KINDS}

def pool_rows(keep):
    t = {c: collections.Counter() for c in KINDS}
    for r in rows:
        if not keep(r):
            continue
        t[r["kind"]]["registers"] += 1
        t[r["kind"]]["found"] += bool(r["found"])
        t[r["kind"]]["verified_found"] += bool(r["verified_found"])
    return {c: dict(t[c]) for c in KINDS}

def rate(a, b):
    return None if not b else round(a / b, 4)

allids = [d["id"] for d in designs]
# the weakest-labelled design by a stated rule: > 50% of its scored structure registers Tier A
weakest = [d["id"] for d in designs
           if d["scored_structure_registers"] and
           d["label_tiers"].get("A_contradicted", 0) / d["scored_structure_registers"] > 0.5]
anyA = [d["id"] for d in designs if d["label_tiers"].get("A_contradicted", 0)]

variants = {
    "H1_all_10_designs": {"designs": allids, "pool": pool_designs(allids)},
    "H2_excluding_weakest_labelled_designs": {
        "designs": [i for i in allids if i not in weakest], "excluded": weakest,
        "rule": "a design > 50% of whose scored structure-kind registers are Tier A (mapping contradicted)",
        "pool": pool_designs([i for i in allids if i not in weakest])},
    "H3_excluding_every_design_with_any_Tier_A_register": {
        "designs": [i for i in allids if i not in anyA], "excluded": anyA,
        "pool": pool_designs([i for i in allids if i not in anyA])},
    "H4_all_10_designs_Tier_A_registers_dropped_from_the_denominator": {
        "designs": allids,
        "rule": "every design kept; the 23 Tier A registers removed from their kind's denominator. "
                "exact is NOT available per register from the frozen report, so only found and "
                "verified-found are given.",
        "pool": pool_rows(lambda r: r["tier"] != "A_contradicted")},
    "H5_Tier_A_registers_only": {"designs": anyA,
        "pool": pool_rows(lambda r: r["tier"] == "A_contradicted")},
}
for name, v in variants.items():
    tot = collections.Counter()
    for c in KINDS:
        p = v["pool"][c]
        p.setdefault("registers", 0); p.setdefault("found", 0); p.setdefault("verified_found", 0)
        tot.update(p)
        p["found_recall"] = rate(p.get("found", 0), p["registers"])
        p["exact_recall"] = rate(p.get("exact", 0), p["registers"]) if "exact" in p else None
        p["verified_found_recall"] = rate(p.get("verified_found", 0), p["registers"])
        p["precision_found"] = rate(p.get("structures_matched", 0), p.get("structures", 0)) if "structures" in p else None
    v["pooled"] = {"registers": tot["registers"], "found": tot["found"], "exact": tot.get("exact"),
                   "verified_found": tot["verified_found"],
                   "structures": tot.get("structures"), "structures_matched": tot.get("structures_matched"),
                   "found_recall": rate(tot["found"], tot["registers"]),
                   "exact_recall": rate(tot.get("exact", 0), tot["registers"]) if "exact" in tot else None,
                   "verified_found_recall": rate(tot["verified_found"], tot["registers"]),
                   "precision_found": rate(tot.get("structures_matched", 0), tot.get("structures", 0)) if "structures" in tot else None}
json.dump(variants, open(os.path.join(OUT, "_pool.json"), "w"), indent=1)
for n, v in variants.items():
    print("==", n, "->", len(v["designs"]), "designs")
    for c in KINDS:
        p = v["pool"][c]
        print(f"   {c:15} den={p['registers']:3} found={p.get('found')}/{p['registers']} = {p['found_recall']}  exact={p.get('exact')}  verified_found={p.get('verified_found')}/{p['registers']} = {p['verified_found_recall']}")
    print("   POOLED:", json.dumps(v["pooled"]))
