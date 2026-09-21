"""Cross-check synth.py against LibreLane's own synthesis script, run inside a LibreLane image.

    python -m tools.roundtrip.librelane_ref --image ghcr.io/librelane/librelane:3.0.14
        --top adder_demo --recipe warmup --out out/roundtrip/calib/native_3.0.14 \
        upstream/warmup/00_source.v

Runs `yosys -y <librelane>/scripts/pyosys/synthesize.py` from the image (the script the
Yosys.Synthesis step runs) with a config.json/extra.json built from a synth.py recipe: the
same trimmed liberty (synth.lib written by synth.write_trimmed_lib), the sky130 PDK values
and the recipe's SYNTH_* knobs. The result is <out>/netlist.v, which can be compared with
synth.py's output (tools.roundtrip.compare) to show that the transcription is faithful.
The knobs map one to one onto LibreLane 3.0.x variables (plus the two 3.1 adds).
"""

import argparse
import json
import os
import subprocess
import sys

from tools.roundtrip import synth


def config_for(recipe, top, sources):
    return {
        "DESIGN_NAME": top,
        "PDK": "sky130A",
        "STD_CELL_LIBRARY": "sky130_fd_sc_hd",
        "VERILOG_FILES": sources,
        "VERILOG_DEFINES": None,
        "VERILOG_INCLUDE_DIRS": None,
        "SYNTH_PARAMETERS": None,
        "USE_SLANG": False,
        "SLANG_ARGUMENTS": None,
        "GHDL_ARGUMENTS": None,
        "SYNTH_SHOW": False,
        "SYNTH_NORMALIZE_SINGLE_BIT_VECTORS": True,
        "SYNTH_ELABORATE_ONLY": False,
        "SYNTH_HIERARCHY_MODE": recipe.hierarchy,
        "SYNTH_KEEP_HIERARCHY_MIN_COST": None,
        "SYNTH_KEEP_HIERARCHY_INSTANCES": None,
        "SYNTH_KEEP_HIERARCHY_MODULES": None,
        "SYNTH_TRISTATE_MAP": synth.TRISTATE_MAP if recipe.tristate_map else None,
        "SYNTH_LATCH_MAP": synth.LATCH_MAP if recipe.latch_map else None,
        "SYNTH_FA_MAP": None,
        "SYNTH_CSA_MAP": None,
        "SYNTH_RCA_MAP": None,
        "SYNTH_EXTRA_MAPPING_FILE": None,
        "SYNTH_ADDER_TYPE": "YOSYS",
        "SYNTH_MUL_BOOTH": recipe.booth,
        "SYNTH_ABC_DFF": recipe.abc_dff,
        "SYNTH_TIE_UNDEFINED": recipe.tie_undefined or None,
        "SYNTH_CLOCKGATE_MIN_WIDTH": None,
        "SYNTH_CLOCKGATE_POSEDGE_ICG": None,
        "SYNTH_CLOCKGATE_NEGEDGE_ICG": None,
        "SYNTH_STRATEGY": recipe.strategy,
        "SYNTH_ABC_LEGACY_REFACTOR": recipe.legacy_refactor,
        "SYNTH_ABC_LEGACY_REWRITE": recipe.legacy_rewrite,
        "SYNTH_ABC_USE_MFS3": recipe.use_mfs3,
        "SYNTH_ABC_AREA_USE_NF": recipe.area_use_nf,
        "SYNTH_ABC_BUFFERING": recipe.abc_buffering,
        "SYNTH_SIZING": recipe.sizing,
        "CLOCK_PERIOD": recipe.clock_period,
        "MAX_FANOUT_CONSTRAINT": recipe.max_fanout,
        "MAX_TRANSITION_CONSTRAINT": recipe.max_transition,
        "SYNTH_DRIVING_CELL": recipe.driving_cell,
        "OUTPUT_CAP_LOAD": recipe.output_cap,
        "SYNTH_TIEHI_CELL": recipe.tiehi,
        "SYNTH_TIELO_CELL": recipe.tielo,
        "SYNTH_SPLITNETS": recipe.splitnets,
        "SYNTH_DIRECT_WIRE_BUFFERING": recipe.direct_wire_buffering,
        "SYNTH_BUFFER_CELL": recipe.buffer_cell,
        "SYNTH_AUTONAME": False,
        "SYNTH_WRITE_NOATTR": True,
        # read by 3.1.x only
        "SYNTH_ARITH_TREE": recipe.arith_tree,
        "SYNTH_ABC_STRATEGY_SCRIPT": None,
    }


def run(sources, top, recipe, out, image):
    out = os.path.abspath(out)
    for p in [out] + [os.path.abspath(s) for s in sources]:
        if not p.startswith(synth.ROOT + os.sep):
            raise SystemExit(f"{p} must be inside {synth.ROOT} (mounted into the container)")
    os.makedirs(out, exist_ok=True)
    lib = os.path.join(out, "synth.lib")
    synth.write_trimmed_lib(synth.LIB, lib, recipe)
    cfg = os.path.join(out, "config.json")
    with open(cfg, "w") as f:
        json.dump(config_for(recipe, top, [os.path.abspath(s) for s in sources]), f, indent=1)
    extra = os.path.join(out, "extra.json")
    with open(extra, "w") as f:
        json.dump({"blackbox_models": [synth.LIB], "libs_synth": [lib]}, f, indent=1)
    netlist = os.path.join(out, "netlist.v")
    inner = (
        'd=$(python3 -c "import librelane,os;print(os.path.dirname(librelane.__file__))")/scripts/pyosys; '
        f'PYTHONPATH=$d yosys -l {out}/yosys.log -q -y $d/synthesize.py -- '
        f"--config-in {cfg} --extra-in {extra} --output {netlist}"
    )
    cmd = ["docker", "run", "--rm", "-v", f"{synth.ROOT}:{synth.ROOT}", "-w", out, image, "sh", "-c", inner]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
        raise RuntimeError(f"LibreLane synthesize.py failed in {image}")
    return netlist


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--top", required=True)
    ap.add_argument("--recipe", default="warmup")
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--image", default="ghcr.io/librelane/librelane:3.0.14")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    recipe = synth.with_overrides(synth.RECIPES[a.recipe], a.set)
    print(run(a.sources, a.top, recipe, a.out, a.image))
    return 0


if __name__ == "__main__":
    sys.exit(main())
