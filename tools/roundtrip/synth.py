# Portions of this file are transcribed from LibreLane (https://github.com/librelane/librelane):
# librelane/scripts/pyosys/synthesize.py and librelane/scripts/pyosys/construct_abc_script.py
# (Copyright 2020-2024 Efabless Corporation) and librelane/common/toolbox.py
# (Copyright 2023 Efabless Corporation), licensed under the Apache License, Version 2.0
# (http://www.apache.org/licenses/LICENSE-2.0). synthesize.py in turn adapts parts of Yosys
# (techlibs/common/synth.cc, passes/opt/opt.cc), under this notice:
#
#  Copyright (C) 2012  Claire Xenia Wolf <claire@yosyshq.com>
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
#  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
#  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
#  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
#  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
#  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
#  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
#  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

"""Round-trip synthesis (PRD S4): LibreLane-style Yosys synthesis for sky130_fd_sc_hd.

    python -m tools.roundtrip.synth --top adder_demo --recipe warmup
        --out out/roundtrip/calib/warmup upstream/warmup/00_source.v

A recipe is a named set of knobs (RECIPES below; `--set key=value` overrides one knob,
`--list` prints them all). For a recipe the script
  1. writes synth.lib: the liberty with the excluded cells cut out, as LibreLane's
     Toolbox.remove_cells_from_lib does with SYNTH_EXCLUDED_CELL_FILE + PNR_EXCLUDED_CELL_FILE
     (open_pdks copies in tools/roundtrip/pdk/),
  2. writes the ABC strategy script, as LibreLane's ABCScriptCreator.generate_abc_script,
  3. writes synth.ys, a transcription of LibreLane's scripts/pyosys/synthesize.py into a
     plain Yosys script (the oss-cad-suite Yosys has no Python frontend), and runs it,
  4. flattens the result and writes histogram.json: count per cell master and total
     liberty area, split into logic / physical (tap, decap, fill, diode) / clock-tree cells.
     A synthesis result is pre-CTS, so its clock-tree part is always empty: a clock-family
     master (clkbuf, clkinv, clkdlybuf) that ABC picked, e.g. clkinv_1 as a data inverter when
     no_synth.cells is not applied, is counted as logic (see cell_kinds()).
Outputs in --out: synth.ys, <STRATEGY>.abc, synthesis.abc.sdc, synth.lib, netlist.v (as the
flow writes it, hierarchy kept when the recipe keeps it), netlist_flat.v, netlist_flat.json,
histogram.json, recipe.json, yosys.log, reports/.

LibreLane sources transcribed (Apache-2.0): librelane/scripts/pyosys/synthesize.py and
construct_abc_script.py at tags 3.0.0-3.0.14 (variant "3.0"; the LibreLane line whose
default sky130 PDK is open_pdks 8afc8346, the version this repository pins) and 3.1.0.dev3
(variant "3.1"). tools/roundtrip/librelane_ref.py runs the original script inside a
LibreLane image to check this transcription; with the same Yosys the netlists are
identical (tools/roundtrip/calib.py).

Result depends on the Yosys build, not only on the recipe: recipe `warmup` reproduces
upstream/warmup/01_netlist.v exactly with Yosys 0.62 (LibreLane 3.0.14 image, the
recipe's default) and 0.66 (LibreLane 3.1.0.dev3 image), but not with the oss-cad-suite
0.69 (comparator496 maps to different cells, a logic-histogram distance of 6; adder8 to the
same histogram, but 39 of its 41 instances differ from the reference's instance of the same
name in master or pin nets).
"""

import argparse
import dataclasses
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
from typing import Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
YOSYS = os.environ.get("YOSYS", os.path.expanduser("~/ttsetup/oss-cad-suite/bin/yosys"))
# Yosys builds by alias. ll3014 is the Yosys 0.62 inside the LibreLane 3.0.14 image, the
# LibreLane line whose default sky130 PDK is open_pdks 8afc8346, and the warmup recipe's
# default. On the warm-up (calib.py; out/roundtrip/calib/sweep) recipe warmup reproduces
# upstream/warmup/01_netlist.v exactly with ll3014 (0.62) and with ll31dev3 (0.66): logic
# histogram distance 0, same instance names and nets. With oss (0.69) it misses by 6, all
# in the comparator (cmp0: +and4_2 +and4b_2 +nor3_2, -and3_2 -2 and4bb_2); adder8 (add0)
# has the reference's histogram, but 39 of its 41 instances differ from the reference's
# instance of the same name in master or pin nets, as do 8 in each shift register (pin nets
# only) (calib attempt 03_keep_area0_y069).
YOSYS_ALIASES = {
    "oss": YOSYS,
    "ll3014": "docker:ghcr.io/librelane/librelane:3.0.14",
    "ll31dev3": "docker:ghcr.io/librelane/librelane:3.1.0.dev3",
}
LIB = os.path.join(ROOT, "pdk/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib")
LIST_FILES = {
    "no_synth": os.path.join(HERE, "pdk/no_synth.cells"),
    "drc_exclude": os.path.join(HERE, "pdk/drc_exclude.cells"),
}
TRISTATE_MAP = os.path.join(HERE, "pdk/tribuff_map.v")
LATCH_MAP = os.path.join(HERE, "pdk/latch_map.v")
PHYSICAL = ("tapvpwrvgnd", "decap", "fill", "diode")
# Clock-family masters. CTS builds clock trees from them, and the sky130 no_synth.cells keeps
# them out of synthesis, so in a LibreLane netlist after CTS each one is normally a clock-tree
# cell. A synthesis run without no_synth.cells may use them as ordinary logic (ABC picks
# clkinv_1 as a data inverter), so the master name alone does not make a cell a clock-tree
# cell: cell_kinds() decides.
CLOCK = ("clkbuf", "clkinv", "clkdlybuf")
KINDS = ("logic", "clock", "physical")


@dataclasses.dataclass(frozen=True)
class Recipe:
    """Synthesis knobs. Defaults are LibreLane 3.0.x defaults with the sky130A PDK config."""

    librelane: str = "3.0"  # script variant: "3.0" or "3.1" (see module docstring)
    strategy: str = "AREA 0"  # SYNTH_STRATEGY
    hierarchy: str = "flatten"  # SYNTH_HIERARCHY_MODE: flatten | deferred_flatten | keep
    exclude: Tuple[str, ...] = ("no_synth", "drc_exclude")  # cell list files (LIST_FILES keys)
    extra_exclude: Tuple[str, ...] = ()  # EXTRA_EXCLUDED_CELLS wildcards
    keep_only: Tuple[str, ...] = ()  # experiment: if set, keep only cells matching these
    generic_abc: str = "auto"  # auto (as the variant does) | fast | fast_script | default
    clock_period: float = 10.0  # CLOCK_PERIOD (ns)
    max_fanout: int = 10  # MAX_FANOUT_CONSTRAINT
    max_transition: float = 0.75  # MAX_TRANSITION_CONSTRAINT (ns)
    abc_buffering: bool = False  # SYNTH_ABC_BUFFERING
    sizing: bool = False  # SYNTH_SIZING
    legacy_refactor: bool = False  # SYNTH_ABC_LEGACY_REFACTOR
    legacy_rewrite: bool = False  # SYNTH_ABC_LEGACY_REWRITE
    use_mfs3: bool = False  # SYNTH_ABC_USE_MFS3
    area_use_nf: bool = False  # SYNTH_ABC_AREA_USE_NF
    abc_dff: bool = False  # SYNTH_ABC_DFF
    abc_script: str = ""  # custom ABC script text (replaces the strategy script)
    tie_undefined: str = "low"  # SYNTH_TIE_UNDEFINED: low | high | "" (none)
    driving_cell: str = "sky130_fd_sc_hd__inv_2/Y"  # SYNTH_DRIVING_CELL (after pdk_compat)
    output_cap: float = 33.442  # OUTPUT_CAP_LOAD (fF)
    tiehi: str = "sky130_fd_sc_hd__conb_1/HI"  # SYNTH_TIEHI_CELL
    tielo: str = "sky130_fd_sc_hd__conb_1/LO"  # SYNTH_TIELO_CELL
    splitnets: bool = True  # SYNTH_SPLITNETS
    direct_wire_buffering: bool = True  # SYNTH_DIRECT_WIRE_BUFFERING
    buffer_cell: str = "sky130_fd_sc_hd__buf_2/A/X"  # SYNTH_BUFFER_CELL
    arith_tree: bool = True  # SYNTH_ARITH_TREE (variant 3.1 only)
    booth: bool = False  # SYNTH_MUL_BOOTH
    tristate_map: bool = True  # SYNTH_TRISTATE_MAP set by the PDK config
    latch_map: bool = True  # SYNTH_LATCH_MAP set by the PDK config
    yosys: str = ""  # default Yosys for this recipe (alias, path or docker:<image>); "" = YOSYS
    no_sort: bool = False  # experiment: omit librelane_opt's design.sort() (see ys_script)


LL30 = Recipe()
RECIPES = {
    # LibreLane 3.0.x defaults: flatten, AREA 0
    "ll30": LL30,
    # Calibrated on the warm-up (tools/roundtrip/calib.py): LibreLane 3.0.x defaults with
    # SYNTH_HIERARCHY_MODE=keep, run with LibreLane 3.0.14's Yosys 0.62, gives the same
    # cells, instance names and nets as upstream/warmup/01_netlist.v (minus CTS/physical cells).
    "warmup": dataclasses.replace(LL30, hierarchy="keep", yosys="ll3014"),
    "ll30_keep": dataclasses.replace(LL30, hierarchy="keep"),
    "ll30_deferred": dataclasses.replace(LL30, hierarchy="deferred_flatten"),
    "ll31": dataclasses.replace(LL30, librelane="3.1"),
    "ll31_keep": dataclasses.replace(LL30, librelane="3.1", hierarchy="keep"),
}


def with_overrides(recipe, sets):
    """Apply `key=value` strings to a recipe (types follow the field defaults)."""
    changes = {}
    fields = {f.name: f for f in dataclasses.fields(Recipe)}
    for s in sets or []:
        key, _, value = s.partition("=")
        if key not in fields:
            raise SystemExit(f"unknown recipe knob {key!r}; knobs: {', '.join(fields)}")
        cur = getattr(recipe, key)
        if isinstance(cur, bool):
            v = value.lower() in ("1", "true", "yes", "on")
        elif isinstance(cur, int):
            v = int(value)
        elif isinstance(cur, float):
            v = float(value)
        elif isinstance(cur, tuple):
            v = tuple(x for x in value.split(",") if x)
        else:
            v = value
        changes[key] = v
    return dataclasses.replace(recipe, **changes)


# ---- liberty -----------------------------------------------------------------------------


def read_list_file(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


def excluded_cells(recipe):
    cells = set(recipe.extra_exclude)
    for key in recipe.exclude:
        cells.update(read_list_file(LIST_FILES[key]))
    return cells


def write_trimmed_lib(src, dst, recipe):
    """LibreLane Toolbox.remove_cells_from_lib (brace counting on cell groups)."""
    excl = excluded_cells(recipe)

    def removed(name):
        if any(fnmatch.fnmatch(name, w) for w in excl):
            return True
        return bool(recipe.keep_only) and not any(fnmatch.fnmatch(name, w) for w in recipe.keep_only)

    cell_start = re.compile(r"(\s*)cell\s*\(\"?(.*?)\"?\)\s*\{")
    kept, dropped = [], []
    state, depth = "initial", 0
    with open(src) as fi, open(dst, "w") as fo:
        for line in fi:
            if state == "initial":
                m = cell_start.search(line)
                if m:
                    depth = 1
                    if removed(m[2]):
                        state = "excluded"
                        dropped.append(m[2])
                        fo.write(f"{m[1]}/* removed {m[2]} */\n")
                    else:
                        state = "cell"
                        kept.append(m[2])
                        fo.write(line)
                else:
                    fo.write(line)
            else:
                if "{" in line:
                    depth += 1
                if "}" in line:
                    depth -= 1
                if state == "cell":
                    fo.write(line)
                if depth == 0:
                    state = "initial"
    return kept, dropped


_AREA_CACHE = {}


def cell_areas(lib=LIB):
    """{cell name: liberty area} for every cell in the liberty."""
    if lib not in _AREA_CACHE:
        areas, cur = {}, None
        rx_cell = re.compile(r'^\s*cell\s*\(\s*"?([\w$]+)"?\s*\)')
        rx_area = re.compile(r"^\s*area\s*:\s*([0-9.eE+-]+)")
        with open(lib) as f:
            for line in f:
                m = rx_cell.match(line)
                if m:
                    cur = m[1]
                    continue
                if cur is not None:
                    m = rx_area.match(line)
                    if m:
                        areas[cur] = float(m[1])
                        cur = None
        _AREA_CACHE[lib] = areas
    return _AREA_CACHE[lib]


# ---- ABC script (LibreLane ABCScriptCreator) ---------------------------------------------


def abc_script(recipe):
    if recipe.abc_script:
        return recipe.abc_script.replace(";", "\n") + "\n"
    D = recipe.clock_period * 1000
    v31 = recipe.librelane == "3.1"
    rf, rfz = ("refactor", "refactor -z") if recipe.legacy_refactor else ("drf -l", "drf -l -z")
    rw, rwz = ("rewrite", "rewrite -z") if recipe.legacy_rewrite else ("drw -l", "drw -l -z")
    b = "balance"
    resyn2 = f"{b}; {rw}; {rf}; {b}; {rw}; {rwz}; {b}; {rfz}; {rwz}; {b}"
    choice = f"fraig_store; {resyn2}; fraig_store; {resyn2}; fraig_store; fraig_restore"
    choice2 = (
        f"fraig_store; {b}; fraig_store; {resyn2}; fraig_store; {resyn2}; fraig_store; "
        f"{resyn2}; fraig_store; fraig_restore"
    )
    area_mfs3 = "mfs3 -aemvz -I 4 -O 2" if recipe.use_mfs3 else ""
    delay_mfs3 = "mfs3 -emvz -I 4 -O 2" if recipe.use_mfs3 else ""
    map_old_dly = "map -p -B 0.2 -A 0.9 -M 0"
    retime_area = f"retime -D {D} -M 5" if v31 else "retime -M 5"
    retime_dly = f"retime -D {D} -M 6" if v31 else "retime -M 6"
    map_new_area = "&get -n; &nf -R 1000; &put" if recipe.area_use_nf else "amap -m -Q 0.1 -F 20 -A 20 -C 5000"
    sz = f"upsize -D {D};dnsize -D {D}" if v31 else "upsize;dnsize"
    fine_tune = ""
    if recipe.abc_buffering:
        mt = recipe.max_transition * 1000
        fine_tune = f"buffer -N {recipe.max_fanout}" + (f" -S {mt}" if mt else "") + f";{sz}"
    elif recipe.sizing:
        fine_tune = sz

    s = recipe.strategy
    L = []
    if s == "AREA 3":
        L += ["strash", "dch", "map -B 0.9", "topo", "stime -c", f"buffer -c -N {recipe.max_fanout}",
              "upsize -c", "dnsize -c"]
    elif s == "DELAY 4":
        L += ["&get -n", "&st", "&dch", "&nf"]
        for _ in range(5):
            L += ["&st", "&syn2", "&if -g -K 6", "&synch2", "&nf"]
        L += ["&put", f"buffer -c -N {recipe.max_fanout}", "topo", "stime -c", "upsize -c", "dnsize -c"]
    else:
        L += ["fx", "mfs", "strash", rf]
        L.append(choice2 if s == "AREA 2" else resyn2)
        L.append(retime_area if s.startswith("AREA ") or s == "DELAY 3" else retime_dly)
        L.append("scleanup")
        if s in ("AREA 4", "DELAY 2"):
            L.append(choice)
        elif s != "DELAY 0":
            L.append(choice2)
        L.append(map_new_area if s.startswith("AREA ") or s == "DELAY 3" else map_old_dly)
        if s in ("AREA 1", "AREA 2"):
            L += [choice2, map_new_area]
        elif s == "DELAY 1":
            L += [choice2, "map"]
        elif s == "DELAY 2":
            L += [choice, "map"]
        elif s == "DELAY 3":
            L += [choice2, map_old_dly]
        L.append(area_mfs3 if s.startswith("AREA ") else delay_mfs3)
        L.append(f"retime -D {D}" if v31 else "retime")
        L += ["&get -n", "&st", "&dch", "&nf", "&put", fine_tune]
    L += ["stime -p", "print_stats -m"]
    return "\n".join(L) + "\n"


# ---- Yosys script (LibreLane synthesize.py) ----------------------------------------------


def yosys_version(yosys_cmd):
    out = subprocess.run(yosys_cmd + ["-V"], capture_output=True, text=True).stdout
    m = re.search(r"Yosys (\d+)\.(\d+)", out)
    return (int(m[1]), int(m[2])) if m else (999, 999), out.strip()


def q(path):
    return shlex.quote(path)


def ys_script(recipe, top, sources, out, abc_path, sdc_path, lib_synth, yver):
    rep = os.path.join(out, "reports")
    netlist = os.path.join(out, "netlist.v")
    lib_args = f"-liberty {q(lib_synth)}"
    v31 = recipe.librelane == "3.1"
    defines = "-DPDK_sky130A -DSCL_sky130_fd_sc_hd -D__librelane__ -D__pnr__"
    S = [f"# generated by tools/roundtrip/synth.py; recipe = {json.dumps(dataclasses.asdict(recipe))}"]
    blackbox = f"read_liberty -lib -ignore_miss_dir -setattr blackbox -setattr keep_hierarchy {q(LIB)}"
    S.append(blackbox)
    for src in sources:
        S.append(f"read_verilog -defer -noautowire -sv {defines} {q(src)}")
    hier = f"hierarchy -check -top {top} -nokeep_prints -nokeep_asserts"
    S += [hier, f"rename -top {top}", f"select -module {top}", "attrmap -remove single_bit_vector", "select -clear"]
    if recipe.tristate_map:
        S.append("tribuf")

    # librelane_synth
    S.append(hier)
    if v31:
        S.append("chformal -remove")
    S += ["proc_clean", "proc_rmdead", "proc_prune", "proc_init", "proc_arst", "proc_rom", "proc_mux",
          f"tee -o {q(rep + '/latch.rpt')} proc_dlatch", "proc_dff", "proc_memwr", "proc_clean",
          f"tee -o {q(rep + '/pre_synth_chk.rpt')} check", "opt_expr"]
    if recipe.hierarchy == "flatten":
        S.append("flatten")
    undriven = " -undriven" if recipe.tie_undefined else ""
    full = f"-mux_undef -mux_bool{undriven} -fine"  # librelane_opt(opt_share, mux_*, undriven, fine)
    # librelane_opt(...) is Yosys `opt` with the same flags followed by design.optimize();
    # design.sort(); design.check(). Yosys `opt` itself still sorts the design in 0.62 but
    # not in 0.66 or 0.69 (checked on all three), and the order decides the order in which
    # ABC sees the gates, hence its result: emit the sort explicitly (`write_rtlil -sort`
    # sorts in place; 0.62 has it too). Without it, 0.66 and 0.69 miss the warm-up netlist
    # (calib attempts *_nosort).
    # `opt -full` forces -undriven, so with tie_undefined unset the non-fast loop drops
    # opt_share (an approximation; the default tie_undefined=low is exact).
    sort = [] if recipe.no_sort else ["write_rtlil -sort /dev/null"]

    def llopt(args):
        return [f"opt {args}".strip()] + sort

    opt_full = "-full" if undriven else full
    S += ["opt_expr", "opt_clean"] + llopt("-nodffe -nosdff") + ["fsm"] + llopt("")
    S += ["wreduce", "peepopt", "opt_clean"]
    if recipe.booth:
        S.append("booth")
    S.append("alumacc")
    if v31 and recipe.arith_tree:
        S.append("arith_tree")
    S += ["share"] + llopt("") + ["memory -nomap", "opt_clean"] + llopt(f"-fast {full}") + ["memory_map"]
    S += llopt(opt_full) + ["techmap"] + llopt("-fast") + llopt("-fast")
    mode = recipe.generic_abc
    if mode == "auto":
        mode = "fast" if (not v31 or yver < (0, 68)) else "default"
    dff = " -dff" if recipe.abc_dff else ""
    if mode in ("fast", "fast_script"):
        # Yosys < 0.68 `abc -fast` without a cell library runs "strash; dretime; map";
        # 0.68 dropped -fast, so give 0.68+ the same commands as a script ("fast_script"
        # forces the script on older Yosys too, to test that emulation).
        if yver < (0, 68) and mode == "fast":
            S.append(f"abc -fast{dff}")
        else:
            fast = os.path.join(out, "generic_fast.abc")
            with open(fast, "w") as f:
                f.write("strash\ndretime\nmap\n")
            S.append(f"abc -script {q(fast)}{dff}")
    else:
        S.append(f"abc{dff}")
    S += ["opt -fast", hier, "check", "stat"]

    S += ["delete t:$print", "delete t:$assert", "opt", "opt_clean -purge",
          f"tee -o {q(rep + '/pre_techmap.rpt')} stat {lib_args}"]
    if recipe.tristate_map:
        S += [f"techmap -map {q(TRISTATE_MAP)}", "simplemap"]
    if recipe.latch_map:
        S += [f"techmap -map {q(LATCH_MAP)}", "simplemap"]
    S += [f"dfflibmap {lib_args}", f"tee -o {q(rep + '/post_dff.rpt')} stat {lib_args}"]

    def run_strategy(S, suffix=""):
        dopt = "" if v31 else f" -D {recipe.clock_period * 1000}"
        S.append(f"abc -script {q(abc_path)}{dopt} -constr {q(sdc_path)} -showtmp {lib_args}{dff}")
        if recipe.tie_undefined:
            S.append("setundef " + ("-zero" if recipe.tie_undefined == "low" else "-one"))
        hc, hp = recipe.tiehi.split("/")
        lc, lp = recipe.tielo.split("/")
        S.append(f"hilomap -hicell {hc} {hp} -locell {lc} {lp}")
        if recipe.splitnets:
            S += ["splitnets", "opt_clean -purge"]
        if recipe.direct_wire_buffering:
            S.append("insbuf -buf " + " ".join(recipe.buffer_cell.split("/")))
        S += [f"tee -o {q(rep + '/chk' + suffix + '.rpt')} check",
              f"tee -o {q(rep + '/stat' + suffix + '.rpt')} stat {lib_args}",
              f"write_verilog -noattr -noexpr -nohex -nodec -defparam {q(netlist)}"]

    run_strategy(S)
    if recipe.hierarchy == "deferred_flatten":
        S += [f"write_verilog -noattr -noexpr -nohex -nodec -defparam {q(netlist + '.hierarchy.nl.v')}",
              "design -reset", blackbox, f"read_verilog -sv {q(netlist)}",
              "synth -flatten" + (" -booth" if recipe.booth else "")]
        run_strategy(S, "_flat")

    # ours: a flat copy for the histogram and structural comparison
    flat = os.path.join(out, "netlist_flat")
    S += [f"hierarchy -top {top}", "flatten -noscopeinfo", f"tee -o {q(rep + '/stat_flat.rpt')} stat {lib_args}",
          f"write_verilog -noattr -noexpr -nohex -nodec {q(flat + '.v')}", f"write_json {q(flat + '.json')}"]
    return "\n".join(S) + "\n"


# ---- histogram ---------------------------------------------------------------------------


def classify(master):
    """Kind of a cell judged by its master name alone: "physical" (PHYSICAL), "clock" (a
    clock-family master, CLOCK) or "logic".

    Name only: right for a netlist after CTS from a flow that keeps clock-family masters out
    of synthesis (LibreLane with the sky130 no_synth.cells), wrong for a synthesis result made
    without that list, where a clock-family master can be ordinary logic (the rt_synth runs
    ll30_nosynthlist and ll30_nolists have 10 and 9 clkinv_1 data inverters). Where the
    netlist is at hand, use cell_kinds(); histograms written by run() do.
    """
    short = master.split("__")[-1]
    if short.startswith(PHYSICAL):
        return "physical"
    if short.startswith(CLOCK):
        return "clock"
    return "logic"


_PIN_CACHE = {}


def cell_pins(lib=LIB):
    """{cell: {pin: (direction, is_clock)}} from the liberty's `pin` groups directly under each
    cell (not those of a scan cell's `test_cell`); is_clock is the pin's `clock : "true"`
    (sky130_fd_sc_hd: flop CLK/CLK_N, latch GATE/GATE_N, clock-gate CLK)."""
    if lib not in _PIN_CACHE:
        rx_cell = re.compile(r'^\s*cell\s*\(\s*"?([\w$]+)"?\s*\)')
        rx_pin = re.compile(r'^\s*pin\s*\(\s*"?([\w$\[\]]+)"?\s*\)')
        rx_attr = re.compile(r'^\s*(direction|clock)\s*:\s*"?(\w+)"?\s*;')
        pins, cell, cell_depth, pin, pin_depth, depth = {}, None, 0, None, 0, 0
        with open(lib) as f:
            for line in f:
                m = rx_cell.match(line)
                if m:
                    cell, cell_depth = m[1], depth
                    pins[cell] = {}
                elif cell is not None:
                    m = rx_pin.match(line) if depth == cell_depth + 1 else None
                    if m:
                        pin, pin_depth = m[1], depth
                        pins[cell][pin] = [None, False]
                    elif pin is not None and depth == pin_depth + 1:  # the pin's own attributes
                        m = rx_attr.match(line)
                        if m and m[1] == "direction":
                            pins[cell][pin][0] = m[2]
                        elif m:
                            pins[cell][pin][1] = m[2] == "true"
                depth += line.count("{") - line.count("}")
                if pin is not None and depth <= pin_depth:
                    pin = None
        _PIN_CACHE[lib] = {c: {p: tuple(v) for p, v in ps.items()} for c, ps in pins.items()}
    return _PIN_CACHE[lib]


def clock_tree_cells(module, lib=LIB):
    """Names of the clock-tree cells of a Yosys JSON module: the clock-family cells (CLOCK)
    whose output drives a liberty clock pin (cell_pins), directly or through other such cells,
    plus the clock-family cells that hang off a net of that tree (CTS dummy loads: the
    puzzle's 15 clkbuf_4 are driven by clock-tree clkbuf_8 and drive nothing). Any other
    clock-family cell, e.g. a clkinv_1 in a data path, is not one."""
    pins = cell_pins(lib)

    def bits_of(cell, direction):
        out = []
        for pin, bits in cell["connections"].items():
            d = pins.get(cell["type"], {}).get(pin)
            if (d[0] if d else cell.get("port_directions", {}).get(pin)) == direction:
                out += [b for b in bits if isinstance(b, int)]
        return out

    clock_bits, driver, loads = set(), {}, {}
    for name, cell in module["cells"].items():
        for pin, bits in cell["connections"].items():
            d = pins.get(cell["type"], {}).get(pin)
            if d and d[1] and d[0] == "input":
                clock_bits.update(b for b in bits if isinstance(b, int))
        if classify(cell["type"]) == "clock":
            driver.update((b, name) for b in bits_of(cell, "output"))
            for b in bits_of(cell, "input"):
                loads.setdefault(b, []).append(name)
    # back from the clock pins through clock-family drivers
    tree, todo = set(), list(clock_bits)
    while todo:
        name = driver.get(todo.pop())
        if name is not None and name not in tree:
            tree.add(name)
            todo += bits_of(module["cells"][name], "input")
    # forward from the tree's nets to clock-family loads
    todo = list(clock_bits) + [b for name in tree for b in bits_of(module["cells"][name], "output")]
    while todo:
        for name in loads.get(todo.pop(), []):
            if name not in tree:
                tree.add(name)
                todo += bits_of(module["cells"][name], "output")
    return tree


def cell_kinds(module, pre_cts=False, lib=LIB):
    """{cell name: "logic" | "clock" | "physical"} for the cells of a Yosys JSON module.

    Physical by master name (PHYSICAL). "clock" only for a clock-tree cell
    (clock_tree_cells()); every other cell, clock-family or not, is logic. pre_cts=True
    declares the netlist a synthesis result, before CTS: then no cell is a clock-tree cell,
    since everything in it was made by synthesis (a clkinv_1 that ABC put in a clock path
    too)."""
    tree = set() if pre_cts else clock_tree_cells(module, lib)
    kinds = {}
    for name, cell in module["cells"].items():
        kind = classify(cell["type"])
        kinds[name] = "logic" if kind == "clock" and name not in tree else kind
    return kinds


def histogram_of_module(module, lib=LIB, pre_cts=False):
    """summarize() of a Yosys JSON module, its cells split by cell_kinds(); adds "by_kind"
    ({kind: {master: n}}) and "classified_by" (the rule used)."""
    kinds = cell_kinds(module, pre_cts, lib)
    counts, by_kind = {}, {k: {} for k in KINDS}
    for name, cell in module["cells"].items():
        m = cell["type"]
        counts[m] = counts.get(m, 0) + 1
        by_kind[kinds[name]][m] = by_kind[kinds[name]].get(m, 0) + 1
    out = summarize(counts, lib, by_kind)
    out["by_kind"] = {k: dict(sorted(v.items())) for k, v in by_kind.items()}
    out["classified_by"] = ("pre-CTS netlist: no clock-tree cells, clock-family masters count as logic"
                            if pre_cts else "clock = clock-tree cell (synth.clock_tree_cells: clock-family "
                            "cell that drives a liberty clock pin or hangs off such a tree)")
    return out


def summarize(counts, lib=LIB, by_kind=None):
    """Count and liberty area per kind of a {master: n} histogram. by_kind ({kind: {master:
    n}}, e.g. from cell_kinds()) splits the cells; without it each master is split by name
    alone (classify(), with its caveat about clock-family masters)."""
    areas = cell_areas(lib)
    if by_kind is None:
        by_kind = {k: {m: n for m, n in counts.items() if classify(m) == k} for k in KINDS}
    out = {"cells": dict(sorted(counts.items()))}
    for kind in KINDS:
        sel = by_kind.get(kind, {})
        out[kind] = {"count": sum(sel.values()), "area": round(sum(areas.get(m, 0.0) * n for m, n in sel.items()), 4)}
    out["unknown_area"] = sorted(m for m in counts if m not in areas)
    return out


def histogram_of_netlist(verilog, top, yosys=YOSYS, lib=LIB, pre_cts=False):
    """Flattened cell histogram of any structural netlist (via Yosys); pre_cts as cell_kinds()."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as t:
        js = t.name
    script = f"read_liberty -lib {q(lib)}; read_verilog {q(verilog)}; hierarchy -top {top}; flatten; write_json {q(js)}"
    subprocess.run([yosys, "-q", "-p", script], check=True)
    with open(js) as f:
        mod = json.load(f)["modules"][top]
    os.unlink(js)
    return histogram_of_module(mod, lib, pre_cts)


# ---- driver ------------------------------------------------------------------------------


def yosys_command(spec):
    """`--yosys` value: an alias (YOSYS_ALIASES), a path, or docker:<image> (the image's yosys,
    with this repository mounted at the same path; sources and --out must be inside it)."""
    spec = YOSYS_ALIASES.get(spec, spec)
    if spec.startswith("docker:"):
        img = spec[len("docker:"):]
        return ["docker", "run", "--rm", "-v", f"{ROOT}:{ROOT}", "-w", ROOT, img, "yosys"]
    return [spec]


def run(sources, top, recipe, out, yosys=None, name=None):
    out = os.path.abspath(out)
    sources = [os.path.abspath(s) for s in sources]
    ycmd = yosys_command(yosys or recipe.yosys or YOSYS)
    if ycmd[0] == "docker":
        for p in [out] + sources:
            if not p.startswith(ROOT + os.sep):
                raise SystemExit(f"{p} must be inside {ROOT} to be visible in the container")
    os.makedirs(os.path.join(out, "reports"), exist_ok=True)
    yver, yver_str = yosys_version(ycmd)

    lib_synth = os.path.join(out, "synth.lib")
    kept, dropped = write_trimmed_lib(LIB, lib_synth, recipe)
    abc_path = os.path.join(out, re.sub(r"\s+", "_", recipe.strategy) + ".abc")
    with open(abc_path, "w") as f:
        f.write(abc_script(recipe))
    sdc_path = os.path.join(out, "synthesis.abc.sdc")
    with open(sdc_path, "w") as f:
        f.write(f"set_driving_cell {recipe.driving_cell}\nset_load {recipe.output_cap}\n")
    ys_path = os.path.join(out, "synth.ys")
    with open(ys_path, "w") as f:
        f.write(ys_script(recipe, top, sources, out, abc_path, sdc_path, lib_synth, yver))
    log = os.path.join(out, "yosys.log")
    r = subprocess.run(ycmd + ["-q", "-l", log, "-s", ys_path], capture_output=True, text=True)
    meta = {
        "recipe_name": name,
        "recipe": dataclasses.asdict(recipe),
        "top": top,
        "sources": [os.path.relpath(s, ROOT) for s in sources],
        "yosys": yver_str,
        "yosys_cmd": ycmd,
        "lib_cells_kept": len(kept),
        "lib_cells_removed": len(dropped),
        "returncode": r.returncode,
    }
    with open(os.path.join(out, "recipe.json"), "w") as f:
        json.dump(meta, f, indent=1)
    if r.returncode != 0:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
        raise RuntimeError(f"yosys failed (rc={r.returncode}); see {log}")
    with open(os.path.join(out, "netlist_flat.json")) as f:
        mod = json.load(f)["modules"][top]
    hist = histogram_of_module(mod, pre_cts=True)  # a synthesis result: no CTS has run
    hist["meta"] = meta
    with open(os.path.join(out, "histogram.json"), "w") as f:
        json.dump(hist, f, indent=1)
    return hist


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="*", help="Verilog sources")
    ap.add_argument("--top")
    ap.add_argument("--recipe", default="warmup", help=f"one of {', '.join(RECIPES)}")
    ap.add_argument("--set", action="append", default=[], metavar="KNOB=VALUE", help="override a recipe knob")
    ap.add_argument("--out")
    ap.add_argument("--yosys", help=f"yosys: alias ({', '.join(YOSYS_ALIASES)}), path or docker:<image>; "
                    "default: the recipe's, else the oss-cad-suite one")
    ap.add_argument("--list", action="store_true", help="print the recipes and exit")
    a = ap.parse_args(argv)
    if a.list:
        for k, v in RECIPES.items():
            diff = {f.name: getattr(v, f.name) for f in dataclasses.fields(v) if getattr(v, f.name) != getattr(LL30, f.name)}
            print(f"{k:14s} {diff or '(LibreLane 3.0 defaults)'}")
        return 0
    if not (a.sources and a.top and a.out):
        ap.error("sources, --top and --out are required")
    recipe = with_overrides(RECIPES[a.recipe], a.set)
    hist = run(a.sources, a.top, recipe, a.out, a.yosys, name=a.recipe)
    for m, n in hist["cells"].items():
        print(f"{n:6d}  {m}")
    print(f"logic {hist['logic']['count']} cells, {hist['logic']['area']} um^2; yosys: {hist['meta']['yosys']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
