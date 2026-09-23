"""Re-open an anonymised blind layout and count what a recognizer could still read (replication labeller helper).

Usage: verify_anon.py <design_id> ...   -> one JSON line each; exit 1 if any layout fails the rule
Rule (the brief): 0 reference properties anywhere, 0 top-level labels outside thirdparty.TT_PINS.
Also reported for information: top-level labels kept, labels inside non-top cells, and properties
on top-level polygons/labels and on cells (none of which is part of the rule)."""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
import gdstk  # noqa: E402
from tools.s3 import thirdparty  # noqa: E402

rc = 0
for did in sys.argv[1:]:
    path = os.path.join(ROOT, "out", "s3", "blind", "anon", did + ".gds")
    lib = gdstk.read_gds(path)
    tops = lib.top_level()
    macro = json.load(open(os.path.join(ROOT, "out", "s3", "blind", "label_%s.json" % did)))["macro"]
    top = next(c for c in tops if c.name == macro)
    ref_props = sum(1 for c in lib.cells for r in c.references if r.properties)
    bad_labels = [lb.text for lb in top.labels if not thirdparty.TT_PINS.match(lb.text)]
    row = {"design_id": did, "gds": os.path.relpath(path, ROOT), "top": top.name,
           "top_level_cells": [c.name for c in tops],
           "reference_properties": ref_props,
           "top_labels_outside_tt_pins": len(bad_labels),
           "top_labels_outside_tt_pins_examples": bad_labels[:5],
           "top_labels_kept": len(top.labels),
           "subcell_labels": sum(len(c.labels) for c in lib.cells if c is not top),
           "top_polygon_properties": sum(1 for q in top.polygons if q.properties),
           "top_label_properties": sum(1 for lb in top.labels if lb.properties),
           "cell_properties": sum(1 for c in lib.cells if c.properties),
           "cells": len(lib.cells)}
    row["ok"] = ref_props == 0 and not bad_labels
    rc |= not row["ok"]
    print(json.dumps(row), flush=True)
raise SystemExit(rc)
