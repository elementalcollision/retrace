#!/usr/bin/env python3
"""Summarise one LibreLane round-trip run of the recovered puzzle RTL (S4).

    .venv/bin/python tools/roundtrip/puzzle/summarize.py RUN_DIR [--ref upstream/puzzle.gds] [--json OUT]

RUN_DIR is what tools/roundtrip/run.sh made (out/roundtrip/puzzle_run/<tag>).
Reports the final views, the wall time from <tag>.status, every sign-off
result LibreLane recorded (Magic/KLayout DRC per rule, LVS, antenna after GRT
and after DRT, XOR, routing DRC, timing) and the instance histogram by class
from the final DEF (instance names tell endcaps, taps, fill and CTS cells
apart).  The KLayout GDS is censused too, as a check that it holds the same
cells.  With --ref (default upstream/puzzle.gds when present) the puzzle's own
histogram is shown alongside; its classes come from the master alone, which is
exact for the puzzle because every decap_3 there is an endcap and every
clkbuf is a CTS cell.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from tools.retrace.defparse import read_def  # noqa: E402
from tools.roundtrip.warmup.compare import lef_sizes, survey  # noqa: E402

PREFIX = "sky130_fd_sc_hd__"
LEF = REPO / "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"
CLASSES = ("logic", "flop", "clock", "diode", "tap", "endcap", "fill")
FLOP = re.compile(r"(df|sdf|edf|dl[a-z]*tp|dlx)")


def classify(inst: str | None, master: str) -> str:
    """Class of one instance.  inst is None for a GDS reference (no names)."""
    base = master[len(PREFIX):] if master.startswith(PREFIX) else master
    if inst is not None:
        if inst.startswith("PHY_EDGE_ROW_"):
            return "endcap"
        if inst.startswith("TAP_TAPCELL_ROW_"):
            return "tap"
        if inst.startswith("FILLER_"):
            return "fill"
        if base.startswith("diode_"):
            return "diode"
        if inst.startswith(("clkbuf_", "clkload", "clkinv_")) and base.startswith("clk"):
            return "clock"
    else:  # master only: decap_3 = endcap and clkbuf = CTS hold for the puzzle
        if base.startswith("decap_"):
            return "endcap"
        if base.startswith("tapvpwrvgnd"):
            return "tap"
        if base.startswith("fill_"):
            return "fill"
        if base.startswith("diode_"):
            return "diode"
        if base.startswith("clkbuf_"):
            return "clock"
    if FLOP.match(base):
        return "flop"
    return "logic"


def histogram(pairs, sizes) -> dict:
    """pairs: iterable of (instance name or None, master)."""
    count, area, masters = Counter(), Counter(), {c: Counter() for c in CLASSES}
    for inst, master in pairs:
        c = classify(inst, master)
        count[c] += 1
        w, h = sizes.get(master, (0.0, 0.0))
        area[c] += w * h
        masters[c][master[len(PREFIX):]] += 1
    logic = masters["logic"]
    return {
        "count": {c: count.get(c, 0) for c in CLASSES},
        "total": sum(count.values()),
        "area_um2": {c: round(area.get(c, 0.0), 2) for c in CLASSES},
        "logic_detail": {
            "tie_conb": sum(n for m, n in logic.items() if m.startswith("conb_")),
            "buf": sum(n for m, n in logic.items() if re.match(r"buf_", m)),
            "inv_or_clkinv": sum(n for m, n in logic.items() if re.match(r"(clk)?inv_", m)),
            "xor_xnor": sum(n for m, n in logic.items() if re.match(r"x(n)?or", m)),
        },
        "masters": {c: dict(sorted(masters[c].items())) for c in CLASSES if masters[c]},
    }


def magic_drc_by_rule(rpt: Path) -> dict:
    rules, rule = Counter(), None
    for line in rpt.read_text().splitlines()[1:]:
        if not line or line.startswith(("---", "[INFO]")):
            continue
        if line.startswith(" "):
            rules[rule] += 1
        else:
            rule = line.strip()
    return dict(rules.most_common())


def klayout_drc_by_rule(js: Path) -> dict:
    d = json.loads(js.read_text())
    return {k: v for k, v in sorted(d.items(), key=lambda kv: -kv[1]) if v and k != "total"}


def step_dir(run: Path, suffix: str) -> list[Path]:
    return sorted(p for p in run.iterdir() if p.is_dir() and re.fullmatch(rf"\d+-{suffix}(-\d+)?", p.name))


def step_metrics(d: Path) -> dict:
    f = d / "state_out.json"
    return json.loads(f.read_text()).get("metrics", {}) if f.exists() else {}


def one(glob_dir: Path, pattern: str) -> str | None:
    hits = sorted(glob_dir.glob(pattern)) if glob_dir.exists() else []
    return str(hits[0].relative_to(REPO)) if hits and hits[0].is_relative_to(REPO) else (str(hits[0]) if hits else None)


def summarize(run: Path, ref: Path | None) -> dict:
    run = run.resolve()
    final = run / "final"
    m = json.loads((final / "metrics.json").read_text())
    sizes = lef_sizes(LEF)

    status = {}
    st = run.parent / f"{run.name}.status"
    if st.exists():
        for line in st.read_text().splitlines():
            k, _, v = line.partition("=")
            status[k] = v
    step_s = 0.0
    for rt in run.glob("*/runtime.txt"):
        h, mi, s = rt.read_text().strip().split(":")
        step_s += int(h) * 3600 + int(mi) * 60 + float(s)

    views = {
        "gds_primary": one(final / "gds", "*.gds"),
        "gds_klayout": one(final / "klayout_gds", "*.gds"),
        "gds_magic": one(final / "mag_gds", "*.gds"),
        "def": one(final / "def", "*.def"),
        "nl": one(final / "nl", "*.nl.v"),
        "pnl": one(final / "pnl", "*.pnl.v"),
        "odb": one(final / "odb", "*.odb"),
        "metrics": one(final, "metrics.json"),
    }

    signoff: dict = {
        "magic_drc": m.get("magic__drc_error__count"),
        "klayout_drc": m.get("klayout__drc_error__count"),
        "lvs_errors": m.get("design__lvs_error__count"),
        "lvs_detail": {k.split("__")[1]: v for k, v in m.items() if k.startswith("design__lvs_")},
        "xor_difference": m.get("design__xor_difference__count"),
        "magic_illegal_overlap": m.get("magic__illegal_overlap__count"),
        "route_drc_errors": m.get("route__drc_errors"),
        "disconnected_pins": m.get("design__disconnected_pin__count"),
        "critical_disconnected_pins": m.get("design__critical_disconnected_pin__count"),
        "power_grid_violations": m.get("design__power_grid_violation__count"),
        "antenna_final": {
            "violating_nets": m.get("antenna__violating__nets"),
            "violating_pins": m.get("antenna__violating__pins"),
            "violations": m.get("route__antenna_violation__count"),
            "diodes_inserted": m.get("antenna_diodes_count"),
        },
        "antenna_by_step": {
            d.name: {k: step_metrics(d).get(k) for k in (
                "antenna__violating__nets", "antenna__violating__pins", "route__antenna_violation__count")}
            for d in step_dir(run, "openroad-checkantennas")
        },
        "klayout_antenna": "not run: the Classic flow has no KLayout.Antenna step and the sky130A PDK sets no KLAYOUT_ANTENNA_RUNSET",
    }
    for d in step_dir(run, "magic-drc"):
        rpt = d / "reports/drc.magic.rpt"
        if rpt.exists():
            signoff["magic_drc_by_rule"] = magic_drc_by_rule(rpt)
    for d in step_dir(run, "klayout-drc"):
        js = d / "reports/drc.klayout.json"
        if js.exists():
            signoff["klayout_drc_by_rule"] = klayout_drc_by_rule(js)
    for d in step_dir(run, "netgen-lvs"):
        rpt = d / "reports/lvs.netgen.rpt"
        if rpt.exists():
            text = rpt.read_text()
            signoff["lvs_layout_nets_without_match"] = len(re.findall(r"^Net: .*\|\(no matching net\)", text, re.M))
            signoff["lvs_unmatched_well_nets_named_VPB"] = len(re.findall(r"^Net: \S+/VPB\s+\|\(no matching net\)", text, re.M))
            fr = re.findall(r"^Final result:.*$", text, re.M)
            signoff["lvs_final_result"] = fr[-1] if fr else None

    corners = sorted({k.split("corner:")[1] for k in m if "corner:" in k})
    timing = {
        "clock_period_ns": json.loads((run / "resolved.json").read_text()).get("CLOCK_PERIOD")
        if (run / "resolved.json").exists() else None,
        "setup_ws_worst": m.get("timing__setup__ws"),
        "hold_ws_worst": m.get("timing__hold__ws"),
        "setup_ws_nom_tt": m.get("timing__setup__ws__corner:nom_tt_025C_1v80"),
        "hold_ws_nom_tt": m.get("timing__hold__ws__corner:nom_tt_025C_1v80"),
        "setup_vio_worst_corner": m.get("timing__setup_vio__count"),
        "hold_vio_worst_corner": m.get("timing__hold_vio__count"),
        "setup_violating_corners": [c for c in corners if (m.get(f"timing__setup_vio__count__corner:{c}") or 0) > 0],
        "hold_violating_corners": [c for c in corners if (m.get(f"timing__hold_vio__count__corner:{c}") or 0) > 0],
        "max_slew_violations": m.get("design__max_slew_violation__count"),
        "max_cap_violations": m.get("design__max_cap_violation__count"),
        "max_fanout_violations": m.get("design__max_fanout_violation__count"),
    }

    d = read_def(REPO / views["def"] if not Path(views["def"]).is_absolute() else views["def"])
    hist = histogram(((n, c[0]) for n, c in d["components"].items()), sizes)
    gds_path = views["gds_klayout"]
    g = survey(REPO / gds_path if not Path(gds_path).is_absolute() else Path(gds_path))
    def_masters = Counter(c[0] for c in d["components"].values())
    gds_check = {
        "gds_instances": sum(g["cells"].values()),
        "def_instances": sum(def_masters.values()),
        "same_master_histogram": dict(def_masters) == g["cells"],
    }

    out = {
        "run_dir": str(run.relative_to(REPO)) if run.is_relative_to(REPO) else str(run),
        "exit_status": int(status["exit_status"]) if "exit_status" in status else None,
        "wall_time_s": int(status["wall_time_s"]) if "wall_time_s" in status else None,
        "sum_of_step_runtimes_s": round(step_s, 1),
        "views": views,
        "signoff": signoff,
        "timing": timing,
        "histogram": hist,
        "klayout_gds_vs_def": gds_check,
        "utilisation": m.get("design__instance__utilization"),
    }
    if ref is not None and ref.exists():
        r = survey(ref)
        pairs = [(None, mm) for mm, n in r["cells"].items() for _ in range(n)]
        out["reference"] = {"gds": str(ref.relative_to(REPO)) if ref.resolve().is_relative_to(REPO) else str(ref),
                            "histogram": histogram(pairs, sizes)}
    return out


def show(s: dict) -> None:
    print(f"run {s['run_dir']}: exit {s['exit_status']}, wall {s['wall_time_s']} s "
          f"(steps {s['sum_of_step_runtimes_s']} s)")
    for k, v in s["views"].items():
        print(f"  {k:<12}{v}")
    so = s["signoff"]
    print(f"sign-off: Magic DRC {so['magic_drc']}, KLayout DRC {so['klayout_drc']}, LVS {so['lvs_errors']}, "
          f"XOR {so['xor_difference']}, route DRC {so['route_drc_errors']}, "
          f"antenna nets/pins {so['antenna_final']['violating_nets']}/{so['antenna_final']['violating_pins']} "
          f"(diodes {so['antenna_final']['diodes_inserted']}), illegal overlap {so['magic_illegal_overlap']}, "
          f"disconnected pins {so['disconnected_pins']}, PDN {so['power_grid_violations']}")
    if so.get("magic_drc_by_rule"):
        print("  Magic DRC by rule:", so["magic_drc_by_rule"])
    if so.get("klayout_drc_by_rule"):
        print("  KLayout DRC by rule:", so["klayout_drc_by_rule"])
    print("  LVS:", so["lvs_detail"], "| unmatched layout nets:", so.get("lvs_layout_nets_without_match"),
          "of which */VPB:", so.get("lvs_unmatched_well_nets_named_VPB"))
    print("  LVS final:", so.get("lvs_final_result"))
    print("  antenna by step:", so["antenna_by_step"])
    t = s["timing"]
    print(f"timing @ {t['clock_period_ns']} ns: setup WS worst {t['setup_ws_worst']:.3f} (nom_tt {t['setup_ws_nom_tt']:.3f}), "
          f"hold WS worst {t['hold_ws_worst']:.3f}; setup-violating corners {t['setup_violating_corners']}, "
          f"hold-violating corners {t['hold_violating_corners']}; max slew {t['max_slew_violations']}, "
          f"max cap {t['max_cap_violations']}, max fanout {t['max_fanout_violations']}")
    hdr = f"{'class':<8}{'ours':>7}{'um2':>10}"
    ref = s.get("reference", {}).get("histogram")
    if ref:
        hdr += f"{'puzzle':>8}{'um2':>10}"
    print(hdr)
    for c in CLASSES:
        line = f"{c:<8}{s['histogram']['count'][c]:>7}{s['histogram']['area_um2'][c]:>10.1f}"
        if ref:
            line += f"{ref['count'][c]:>8}{ref['area_um2'][c]:>10.1f}"
        print(line)
    line = f"{'total':<8}{s['histogram']['total']:>7}"
    if ref:
        line += f"{'':>10}{ref['total']:>8}"
    print(line)
    print("  logic detail ours:", s["histogram"]["logic_detail"],
          *(("puzzle:", ref["logic_detail"]) if ref else ()))
    print("  KLayout GDS vs DEF:", s["klayout_gds_vs_def"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--ref", type=Path, default=REPO / "upstream/puzzle.gds",
                    help="reference GDS for the histogram (default upstream/puzzle.gds if present)")
    ap.add_argument("--json", type=Path, help="write the summary as JSON")
    a = ap.parse_args()
    s = summarize(a.run_dir, a.ref)
    show(s)
    if a.json:
        a.json.write_text(json.dumps(s, indent=1) + "\n")


if __name__ == "__main__":
    main()
