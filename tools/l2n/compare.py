"""V4: compare extractor 1 (tools/retrace/extract.py) with extractor 2 (KLayout L2N).

Both are reduced to a partition of {(master@gds_x,gds_y, pin)} plus top-level label
names; the partitions must be identical.
"""

from tools.l2n.klayout_extract import extract, partitions
from tools.retrace.extract import Extraction
from tools.retrace.tech import SKY130_HD


def partition_ours(ex: Extraction, labels):
    key = {i["name"]: f"{i['master']}@{i['gds_origin'][0]},{i['gds_origin'][1]}" for i in ex.instances}
    out = set()
    for m in ex.nets:
        s = {(key[i], p) for i, p in m["pins"]}
        s |= {("LABEL", n) for n in list(m["ports"]) + sorted(m["supply"]) if n in labels}
        if s:
            out.add(frozenset(s))
    return out


def partition_klayout(gds, tech=SKY130_HD):
    layout, top, l2n = extract(gds, tech)
    parts = partitions(layout, top, l2n, tech)
    labels = {p["name"] for p in parts if p["name"]}
    out = set()
    for p in parts:
        s = {tuple(m) for m in p["members"]}
        if p["name"]:
            s.add(("LABEL", p["name"]))
        if s:
            out.add(frozenset(s))
    return out, labels


def compare(gds, ex: Extraction, tech=None):
    """Compare extractor 1's already-built `Extraction` (`ex`) against a fresh
    KLayout extraction of `gds` under the same `Tech` (defaulting to `ex.tech`, so
    existing sky130 callers that omit `tech` are unaffected)."""
    tech = tech or ex.tech
    theirs, labels = partition_klayout(gds, tech)
    ours = partition_ours(ex, labels)
    return ours, theirs
