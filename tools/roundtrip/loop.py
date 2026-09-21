"""S4 round trip, closing the loop: RTL -> GDS -> extracted netlist -> RTL.

Takes one LibreLane run of rtl_recovered/ (tools/roundtrip/puzzle/harden.sh, e.g.
out/roundtrip/puzzle_run/upstreamlike) and checks that the layout it made still is
the design the RTL describes, using only RETRACE's own tools on the GDS:

  1 extract   the KLayout stream-out (final/klayout_gds/*.klayout.gds) with
              tools/retrace/extract.py -> rt_extracted.v (Extraction.to_verilog).
              Cross-check: every DEF component is found in the GDS with the same
              master, position and orientation, and every multi-pin DEF net is one
              extracted net with the same pins. Clock: the CLK pin of each of the
              92 flops is traced back, driver by driver, to port clk; every cell on
              the way must be a clock buffer (clkbuf/clkinv/clkdlybuf/buf).
  2 prove     the extracted netlist sequentially equivalent to rtl_recovered/ with
              the V7 miter (formal/recovered_miter.sv, SymbiYosys abc pdr), exactly as
              tools/analysis/e2e.py does for the puzzle. e2e.run(--gds) cannot be used
              as is: it expects a top cell named `puzzle` and the puzzle's own Q net
              names (rtl_recovered/blocks.json), so the miter's 92 flop probes are
              found here, twice and independently:
                DEF  flop fNN -> its register name in rtl_recovered/puzzle_recovered.v
                     (`reg name; // fNN`) -> the DEF component whose Q pin is on the
                     net of that name -> the GDS instance at that component's
                     position -> its extracted Q net.
                sim  no DEF and no names: the extracted netlist and the RTL are
                     simulated on the same inputs and flops are paired by identical
                     value traces; flops whose traces coincide are tried in every
                     pairing (at most 24 maps) until one proof passes.
              The probes are only a proof aid: they add assertions, so a wrong map
              makes a proof fail, never pass, and O and success are asserted
              regardless. The sim-map proof is the loop closed from the GDS alone.
              Negative controls, both on the gate nearest (breadth-first backwards)
              the D input of a counter flop, and the same proof must FAIL for each:
                netlist  one instance of the extracted netlist gets its dual master
                         with the same pin names (and3_2 -> or3_2, nand2_2 -> nor2_2,
                         ...); name and connections unchanged, one Verilog line differs.
                gds      tools/retrace/mutate.py master_swap on the GDS (same footprint
                         and pin names, NOT the same pin geometry), then re-extracted;
                         the report shows what extractor 1 makes of the swap (pins
                         that no longer reach their net are opens). That is extractor
                         1's view only: it links routing to master pin shapes, so a
                         route landing on the new master's internal geometry is not
                         seen (KLayout L2N, tools/l2n, reported such a short for the
                         and3_2 -> or3_2 swap where extractor 1 reports two opens).
  3 replay    upstream/example_inputs.vcd (1248 checks) and answer/solution.vcd on
              the extracted netlist in Icarus with the PDK Verilog models
              (tools/retrace/vcdtb.py). For the solution run, `success` must rise
              and stay high and O must spell "(* TWO STARS *)". The mutants replay
              the solution too (informational: shows the replay is not vacuous).
  4 layouts   our extracted netlist against the PUZZLE's extracted netlist
              (upstream/puzzle.gds, flop probes from rtl_recovered/blocks.json), the
              same miter, with our probes from the DEF map and from the sim map, plus
              both mutants against the puzzle (must FAIL).
  5 no probes (opt-in, --no-probe-timeout S) steps 2 and 4 again, mutant controls
              included, with a miter that asserts only O and success and has no flop
              probes at all. Each proof has a time limit; a timeout is reported as
              such, never as a result. Informational: not part of the exit status.
              PDR did not converge on these in 30 minutes when first tried, while
              the mutants fail within seconds.

The formal model is single-clock (SymbiYosys default): every flop steps on the one
global clock, so the proofs cannot see how any flop's CLK pin is wired. A flop whose
CLK is rewired to another net (a review rewired f02's CLK to port I) still PASSes both
proofs. Clock wiring is therefore checked separately, in step 1: every flop's CLK net
must lead back to port clk through clock buffers only (clock_paths()). The Icarus
replays exercise it too (the PDK models propagate clk through every clkbuf; the f02
rewiring gave 110 replay errors), and so does the DEF cross-check.

    .venv/bin/python -m tools.roundtrip.loop RUN_DIR [--work DIR] [--json OUT] [--no-probe-timeout S]

Scratch goes to out/roundtrip/loop/<run tag>/ by default; results.json there.
Exit status 0 when every check of steps 1-4 came out as expected. 50-160 s here, most of it
the simulation map's failing candidate proof (10-110 s, depending on load); the rest ~1 s a step.
"""

import argparse
import collections
import contextlib
import glob
import itertools
import json
import math
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from tools.analysis import e2e
from tools.retrace import mutate
from tools.retrace.defparse import read_def
from tools.retrace.extract import PREFIX, SUPPLY_PINS, Extraction
from tools.retrace.lef import read_lef
from tools.retrace.vcdtb import read_vcd, value_at
from tools.retrace.vcdtb import testbench as make_testbench

REPO = Path(__file__).resolve().parents[2]
BIN = e2e.BIN
LEF, LIB, DIRS, BLOCKS = e2e.LEF, e2e.LIB, e2e.DIRS, e2e.BLOCKS
PUZZLE_GDS = e2e.GDS
MODELS = ["pdk/sky130_fd_sc_hd/verilog/primitives.v", "pdk/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v"]
EXAMPLE_VCD, EXAMPLE_CHECKS = "upstream/example_inputs.vcd", 1248
SOLUTION_VCD = "answer/solution.vcd"
EXPECTED_MESSAGE = "(* TWO STARS *)"
INPUTS, OUTPUTS = ["clk", "rst_n", "enable", "I"], ["O", "success"]
COUNTER_FLOPS = [f"f{i:02d}" for i in range(9)]  # rtl_recovered/blocks.json: counter f00-f08
PHYSICAL_DELETE = ("delete */t:sky130_fd_sc_hd__tapvpwrvgnd_1 */t:sky130_fd_sc_hd__decap_* "
                   "*/t:sky130_fd_sc_hd__fill_* */t:sky130_fd_sc_hd__diode_*")


# ------------------------------------------------------------------ run views --------

def run_views(run_dir):
    """The KLayout GDS and the DEF of one LibreLane run."""
    views = {}
    for key, pattern in (("gds", "final/klayout_gds/*.klayout.gds"), ("def", "final/def/*.def")):
        hits = sorted(glob.glob(os.path.join(run_dir, pattern)))
        if len(hits) != 1:
            raise FileNotFoundError(f"expected one {pattern} under {run_dir}, found {hits}")
        views[key] = hits[0]
    return views


def tool_versions():
    def first(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return (r.stdout or r.stderr).strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError, IndexError):
            return None
    return {"yosys": first([f"{BIN}/yosys", "-V"]), "iverilog": first([f"{BIN}/iverilog", "-V"]),
            "python": sys.version.split()[0]}


def _timed(fn, *args, **kw):
    t0 = time.monotonic()
    out = fn(*args, **kw)
    return out, round(time.monotonic() - t0, 2)


# ------------------------------------------------------------------ 1 extract --------

def _ext_name(master, x, y):
    """Extraction's instance name for a DEF component (tools/retrace/extract.py S1)."""
    return f"{master[len(PREFIX):]}_{x}_{y}"


def def_vs_extraction(ex, d):
    """Compare the run's DEF with the GDS extraction: placement and connectivity.

    Single-pin nets (an output that drives nothing, e.g. CTS dummy loads) are listed
    by the extraction but usually not by the DEF, so both sides are compared on nets
    with two or more members (pins or ports)."""
    inst = {i["name"]: i for i in ex.instances}
    name = {c: _ext_name(m, x, y) for c, (m, x, y, _o) in d["components"].items()}
    placed = [c for c, (m, _x, _y, o) in d["components"].items()
              if name[c] in inst and inst[name[c]]["master"] == m and inst[name[c]]["orient"] == o]

    def_nets = {}
    for net, pins in d["nets"].items():
        members = [("PORT", p) if i == "PIN" else (name.get(i, "?" + i), p) for i, p in pins]
        if len(members) >= 2:
            def_nets[frozenset(members)] = net
    ex_nets = {}
    for m in ex.nets:
        if m["supply"]:
            continue
        members = [(i, p) for i, p in m["pins"] if p not in SUPPLY_PINS] + [("PORT", p) for p in m["ports"]]
        if len(members) >= 2:
            ex_nets[frozenset(members)] = m["name"]
    only_def = sorted(def_nets[k] for k in def_nets.keys() - ex_nets.keys())
    only_ex = sorted(ex_nets[k] for k in ex_nets.keys() - def_nets.keys())
    return {
        "def_components": len(d["components"]),
        "gds_instances": len(ex.instances),
        "components_same_master_position_orient": len(placed),
        "def_nets_2plus": len(def_nets),
        "extracted_nets_2plus": len(ex_nets),
        "nets_identical": len(def_nets.keys() & ex_nets.keys()),
        "only_in_def": only_def[:20],
        "only_in_extraction": only_ex[:20],
        "ok": (len(placed) == len(d["components"]) == len(ex.instances)
               and not only_def and not only_ex),
    }


def recovered_regs():
    """{fNN: register name} from the `reg name; // fNN` declarations of the RTL top."""
    with open("rtl_recovered/puzzle_recovered.v") as f:
        src = f.read()
    return {m.group(2): m.group(1) for m in re.finditer(r"^\s*reg\s+(\w+)\s*;\s*//\s*(f\d\d)\b", src, re.M)}


def flop_instances(ex, d):
    """{fNN: extraction instance name} through the DEF (see module docstring)."""
    regs = recovered_regs()
    with open("rtl_recovered/blocks.json") as f:
        flops = json.load(f)["flops"]
    if len(regs) != 92 or set(regs) != set(flops):
        raise ValueError(f"expected the 92 flops of blocks.json as `reg name; // fNN`, found {len(regs)}")
    inst = {i["name"]: i for i in ex.instances}
    out = {}
    for fid, reg in sorted(regs.items()):
        comps = [i for i, p in d["nets"].get(reg, []) if p == "Q"]
        if len(comps) != 1:
            raise ValueError(f"{fid} ({reg}): DEF net {reg!r} has Q pins {comps}")
        master, x, y, _o = d["components"][comps[0]]
        name = _ext_name(master, x, y)
        if name not in inst:
            raise ValueError(f"{fid} ({reg}): DEF {comps[0]} {master} at ({x},{y}) not in the GDS")
        if master != flops[fid]["master"]:
            raise ValueError(f"{fid} ({reg}): {master} in our layout, {flops[fid]['master']} in the puzzle")
        out[fid] = name
    return out


CLOCK_BUFFERS = ("clkbuf_", "clkinv_", "clkdlybuf", "buf_")  # masters a clock path may pass


def clock_paths(ex, lef, flops, net_of=None):
    """Trace each flop's CLK pin back to a port, driver by driver, through clock buffers
    only (CLOCK_BUFFERS; an inverter counts, and the report gives the inversions per
    path). The formal proofs are single-clock and cannot see clock wiring, so this is
    the structural check that every flop is clocked from port clk. `net_of` defaults
    to ex.net_of (a test can pass an altered copy). Returns a dict with "ok"."""
    net_of = ex.net_of if net_of is None else net_of
    master = {i["name"]: i["master"] for i in ex.instances}
    driver, port_of = {}, {}
    for m in ex.nets:
        for p in m["ports"]:
            port_of[m["name"]] = p
    for (inst, pin), net in net_of.items():
        if pin not in SUPPLY_PINS and lef[master[inst]]["pins"].get(pin, {}).get("direction") == "OUTPUT":
            driver[net] = (inst, pin)
    depths, bufs, bad = collections.Counter(), collections.Counter(), {}
    inversions = collections.Counter()
    for fid, name in sorted(flops.items()):
        net, depth, inv, path = net_of.get((name, "CLK")), 0, 0, []
        while True:
            if net is None:
                bad[fid] = f"CLK unconnected after {path}"
                break
            if net in port_of:
                if port_of[net] != "clk":
                    bad[fid] = f"reaches port {port_of[net]!r}, not clk, via {path}"
                break
            d = driver.get(net)
            if d is None:
                bad[fid] = f"net {net} has no driver (after {path})"
                break
            short = master[d[0]][len(PREFIX):]
            if not short.startswith(CLOCK_BUFFERS) or depth > 16:
                bad[fid] = f"driven by {short} {d[0]} (not a clock buffer) after {path}"
                break
            path.append(short)
            inv += "inv" in short
            depth += 1
            net = net_of.get((d[0], "A"))
        if fid not in bad and inv % 2:
            bad[fid] = f"{inv} inversions on the clock path {path} (the RTL clocks every flop on posedge clk)"
        if fid not in bad:
            depths[depth] += 1
            inversions[inv] += 1
            bufs.update(path)
    return {"flops": len(flops), "reach_clk": len(flops) - len(bad), "depths": dict(sorted(depths.items())),
            "buffer_masters_on_paths": dict(sorted(bufs.items())), "inversions": dict(sorted(inversions.items())),
            "bad": bad, "ok": not bad and len(flops) > 0}


def _stimulus_from_vcd(vcd):
    """Per rising clk edge of a recorded run, the (rst_n, enable, I) that edge samples."""
    _widths, events = read_vcd(vcd)
    edges = [t for t, v in events["clk"] if v == "1"]
    return [tuple(value_at(events[n], t - 1) for n in ("rst_n", "enable", "I")) for t in edges]


def _stimulus_random(seed, cycles, p_reset=0.01, p_enable=0.7, p_i=0.5):
    rng = random.Random(seed)
    out = [("0", "0", "0")] * 2
    for _ in range(cycles):
        out.append(("0" if rng.random() < p_reset else "1", str(int(rng.random() < p_enable)),
                    str(int(rng.random() < p_i))))
    return out


def _flop_traces(work, tag, sources, top, probes, stimulus, defines=()):
    """Simulate `top` (Icarus) cycle by cycle and return {probe id: string of its value
    after every rising edge}. `probes` maps an id to a signal name inside `top`."""
    ids = sorted(probes)
    stim = "".join(f"    {{rst_n, enable, I}} = 3'b{''.join(c)}; tick;\n" for c in stimulus)
    fmt = "%b" * len(ids)
    args = ", ".join(f"dut.{probes[i]}" for i in ids)
    tb = f"""`timescale 1ns/1ps
module tb;
  reg clk = 0, rst_n = 0, enable = 0, I = 0;
  wire [7:0] O;
  wire success;
  {top} dut (.clk(clk), .rst_n(rst_n), .enable(enable), .I(I), .O(O), .success(success));
  task tick; begin #5 clk = 1; #1 $display("S {fmt}", {args}); #4 clk = 0; end endtask
  initial begin
{stim}    $finish;
  end
endmodule
"""
    tb_path, vvp = os.path.join(work, f"flops_{tag}.v"), os.path.join(work, f"flops_{tag}.vvp")
    with open(tb_path, "w") as f:
        f.write(tb)
    subprocess.run([f"{BIN}/iverilog", "-g2012", *defines, "-o", vvp, tb_path, *sources], check=True,
                   capture_output=True, text=True)
    r = subprocess.run([f"{BIN}/vvp", "-n", vvp], check=True, capture_output=True, text=True)
    rows = [ln[2:] for ln in r.stdout.splitlines() if ln.startswith("S ")]
    if len(rows) != len(stimulus) or any(len(x) != len(ids) for x in rows):
        raise RuntimeError(f"flop trace {tag}: {len(rows)} rows for {len(stimulus)} cycles")
    return {i: "".join(row[k] for row in rows) for k, i in enumerate(ids)}


def sim_flop_groups(work, ex, netlist, top):
    """Flop correspondence by simulation alone (no DEF, no names). The extracted netlist
    and rtl_recovered/ get the same inputs (answer/solution.vcd, upstream/
    example_inputs.vcd, four random runs with occasional resets, two long runs with I
    mostly 1 so the left_bottom counter passes 64) and flops are grouped by their value
    trace; cycles where either side shows x are ignored. Returns (groups, cycles): each
    group is (fNN ids, extraction instance names) sharing one trace; a group with one
    of each is a unique match."""
    stimulus = _stimulus_from_vcd(SOLUTION_VCD) + _stimulus_from_vcd(EXAMPLE_VCD)
    for seed in range(4):
        stimulus += _stimulus_random(seed, 400)
    for seed in (4, 5):
        stimulus += _stimulus_random(seed, 300, p_reset=0, p_enable=0.95, p_i=0.85)
    flops = [i for i in ex.logic_instances() if i["master"][len(PREFIX):].startswith("df")]
    ours = _flop_traces(work, "extracted", [netlist, *MODELS], top,
                        {i["name"]: ex.net_of[(i["name"], "Q")] for i in flops}, stimulus,
                        ("-DFUNCTIONAL", "-DUNIT_DELAY="))
    srcs = ["rtl_recovered/puzzle_recovered.v"] + [f"rtl_recovered/{b}.v" for b in BLOCKS]
    rtl = _flop_traces(work, "rtl", srcs, "puzzle_recovered", recovered_regs(), stimulus)
    unknown = {k for tr in [*ours.values(), *rtl.values()] for k, c in enumerate(tr) if c not in "01"}
    keep = [k for k in range(len(stimulus)) if k not in unknown]
    groups = collections.defaultdict(lambda: ([], []))
    for fid, tr in sorted(rtl.items()):
        groups["".join(tr[k] for k in keep)][0].append(fid)
    for name, tr in sorted(ours.items()):
        groups["".join(tr[k] for k in keep)][1].append(name)
    return list(groups.values()), len(keep)


def sim_probe_maps(groups, limit=24):
    """Every full {fNN: instance} map the groups allow (permutations inside groups of
    identical traces), or [] if a group does not pair up or there are more than
    `limit`. Any map whose proof passes is a valid proof aid: the probes only add
    assertions, so a wrong pairing can make a proof fail, never pass wrongly."""
    if any(len(a) != len(b) for a, b in groups):
        return []
    count = 1
    for a, _b in groups:
        count *= math.factorial(len(a))
    if count > limit:
        return []
    maps = [{}]
    for a, b in groups:
        maps = [dict(m, **dict(zip(a, perm, strict=True))) for m in maps for perm in itertools.permutations(b)]
    return maps


def netlist_delta(a, b):
    """Name-free difference between two extractions of the same placement: instances
    keyed by DEF position, nets as sets of (position, pin) plus ports. Extracted net
    names (n0, n1, ...) follow instance names, so a text diff overstates a change."""
    pos_a = {i["name"]: (i["x"], i["y"]) for i in a.instances}
    pos_b = {i["name"]: (i["x"], i["y"]) for i in b.instances}
    ma = {pos_a[i["name"]]: i["master"] for i in a.instances}
    mb = {pos_b[i["name"]]: i["master"] for i in b.instances}

    def nets(ex, pos):
        return {frozenset([(pos[i], p) for i, p in m["pins"]] + [("PORT", p) for p in m["ports"]]) for m in ex.nets}

    na, nb = nets(a, pos_a), nets(b, pos_b)
    changed = [k for k in sorted(ma.keys() & mb.keys()) if ma[k] != mb[k]]

    def pin_nets(ex, pos, where):
        out = {}
        for m in ex.nets:
            members = [(pos[i], p) for i, p in m["pins"]] + [("PORT", p) for p in m["ports"]]
            for xy, p in members:
                if xy == where and p not in SUPPLY_PINS:
                    out[p] = sorted(str(x) for x in members if x != (xy, p))
        return out

    return {"positions_only_in_one": len(ma.keys() ^ mb.keys()),
            "masters_changed": [f"{ma[k][len(PREFIX):]} -> {mb[k][len(PREFIX):]} at {k}" for k in changed],
            "nets_changed": len(na ^ nb),
            "pins_before_after": {str(k): {"before": pin_nets(a, pos_a, k), "after": pin_nets(b, pos_b, k)}
                                  for k in changed}}


def q_nets(ex, flops):
    return {fid: ex.net_of[(name, "Q")] for fid, name in flops.items()}


def extract(gds, lef, out_v, top=None):
    ex = Extraction(gds, lef, top=top)
    src = ex.to_verilog(DIRS, lef)
    with open(out_v, "w") as f:
        f.write(src)
    return ex, src


# ------------------------------------------------------------------ 2/4 prove --------

def noprobe_miter(gold, gate):
    """O/success-only miter: same reset convention as formal/recovered_miter.sv, no
    flop probes (so no correspondence information of any kind)."""
    return f"""// generated by tools/roundtrip/loop.py: {gold} vs {gate}, O and success only
module noprobe_miter (input clk, input rst_n, input enable, input I);
  wire [7:0] o_gold, o_gate;
  wire s_gold, s_gate;
  {gold} gold (.clk(clk), .rst_n(rst_n), .enable(enable), .I(I), .O(o_gold), .success(s_gold));
  {gate} gate (.clk(clk), .rst_n(rst_n), .enable(enable), .I(I), .O(o_gate), .success(s_gate));
  reg init = 1'b1;
  always @(posedge clk) init <= 1'b0;
  always @(*) begin
    if (init) assume (!rst_n);
    if (!init) begin
      assert (s_gold == s_gate);
      assert (o_gold == o_gate);
    end
  end
endmodule
"""


def descendants(pid):
    """Every live descendant of `pid` (from one `ps` snapshot), children before theirs."""
    try:
        table = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True,
                               check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    children = collections.defaultdict(list)
    for line in table.splitlines():
        a, b = line.split()
        children[int(b)].append(int(a))
    out, stack = [], [pid]
    while stack:
        for c in children.get(stack.pop(), []):
            out.append(c)
            stack.append(c)
    return out


def kill_tree(pid):
    """SIGKILL `pid`, its descendants and their process groups. sby starts each engine
    (`bash -c ... yosys-abc ...`) in a process group of its own (sby_core.py: preexec_fn
    os.setpgrp), so killing sby's group alone can leave the ABC engine running after a
    timeout (seen in review). sby's group is stopped first so that it cannot start another
    step between the process-table snapshot and the kill; every group in the snapshot is
    then killed, which also catches a child an engine forks after the snapshot (it inherits
    the engine's group). Our own process group is never signalled. Returns the pids that
    were signalled. Checked on the no-probe proof with 0.4, 3 and 20 s limits (sby in a
    model step, and sby + engine bash + yosys-abc in its own group): the yosys-abc pids are
    among those signalled and nothing is left in `ps` afterwards; prove() re-checks that on
    every TIMEOUT (`survivors`). A killpg of sby's group alone also left nothing in that test,
    because `pdr -v` writes to sby's pipe and dies of SIGPIPE once sby is gone; an engine
    that stays silent does not (a synthetic parent -> own-group bash -> sleep tree survives
    killpg of the parent, and not kill_tree)."""
    own = os.getpgrp()
    with contextlib.suppress(ProcessLookupError, PermissionError):
        if os.getpgid(pid) != own:
            os.killpg(os.getpgid(pid), signal.SIGSTOP)  # sby cannot start another engine now
    procs = [pid] + descendants(pid)
    groups = set()
    for q in procs:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            groups.add(os.getpgid(q))
    for g in sorted(groups - {own}):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(g, signal.SIGKILL)
    for q in procs:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(q, signal.SIGKILL)
    return procs


def survivors(pids, wait=2.0):
    """The pids of `pids` still running (zombies excluded) after up to `wait` seconds, from
    `ps`; [] when ps cannot be run."""
    deadline = time.monotonic() + wait
    while True:
        try:
            table = subprocess.run(["ps", "-A", "-o", "pid=,stat="], capture_output=True, text=True,
                                   check=True).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        live = {int(a) for a, st in (ln.split() for ln in table.splitlines() if ln.strip()) if not st.startswith("Z")}
        left = sorted(set(pids) & live)
        if not left or time.monotonic() >= deadline:
            return left
        time.sleep(0.1)


def prove(work, designs, miter_name, miter_src, top, timeout=None):
    """SymbiYosys abc pdr on `top` (the e2e.py script shape). `designs` is an ordered
    list of read_verilog groups, each a list of (file name, source text) or
    (file name, Path of a file to copy).
    Returns {"status": PASS|FAIL|UNKNOWN|ERROR|TIMEOUT, "seconds", "detail"}."""
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    files = []
    reads = []
    for group in designs:
        names = []
        for fname, src in group:
            if isinstance(src, Path):
                shutil.copy(src, os.path.join(work, fname))
            else:
                with open(os.path.join(work, fname), "w") as f:
                    f.write(src)
            names.append(fname)
        files += names
        reads.append("read_verilog " + " ".join(names))
    with open(os.path.join(work, miter_name), "w") as f:
        f.write(miter_src)
    shutil.copy(LIB, work)
    lib = os.path.basename(LIB)
    nl = "\n"
    sby = f"""[options]
mode prove

[engines]
abc pdr

[script]
read_liberty -ignore_miss_func {lib}
{nl.join(reads)}
read_verilog -formal {miter_name}
{PHYSICAL_DELETE}
hierarchy -check -top {top}
flatten
prep -top {top}

[files]
{lib}
{nl.join(files)}
{miter_name}
"""
    with open(os.path.join(work, "loop.sby"), "w") as f:
        f.write(sby)
    env = dict(os.environ, PATH=BIN + os.pathsep + os.environ["PATH"])
    t0 = time.monotonic()
    p = subprocess.Popen([f"{BIN}/sby", "-f", "loop.sby"], cwd=work, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        killed = kill_tree(p.pid)
        out, _ = p.communicate()
        left = survivors(killed)
        detail = f"no result within {timeout} s" + (f"; STILL RUNNING after the kill: pids {left}" if left else "")
        return {"status": "TIMEOUT", "seconds": round(time.monotonic() - t0, 1),
                "detail": detail, "work": work, "failed": [], "killed_pids": killed, "survivors": left}
    secs = round(time.monotonic() - t0, 1)
    m = re.search(r"DONE \((\w+)", out)
    status = m.group(1) if m else "ERROR"
    keep = [ln.split("] ", 1)[-1].strip() for ln in out.splitlines()
            if re.search(r"summary:|Assert failed|failed assertion|counterexample|ERROR", ln)]
    with open(os.path.join(work, "sby.log"), "w") as f:
        f.write(out)
    lines = miter_src.splitlines()
    failed = sorted({(lines[int(m.group(1)) - 1].strip(), int(m.group(2))) for m in
                     re.finditer(re.escape(miter_name) + r":(\d+)\.\d+-\S+ step (\d+)", out)})
    return {"status": status, "seconds": secs, "detail": keep[:12], "work": work,
            "failed": [{"assert": a, "step": k} for a, k in failed]}


def prove_against_rtl(work, rt_src, rt_top, drivers):
    """Step 2: our extracted netlist (gold side) vs rtl_recovered/ (gate side)."""
    gold = e2e._add_probes(rt_src, rt_top, "puzzle_probe", drivers)
    gate = e2e.gate_probe()
    blocks = [(f"{b}.v", Path(f"rtl_recovered/{b}.v")) for b in BLOCKS]
    with open("formal/recovered_miter.sv") as f:
        miter = f.read()
    return prove(work, [[("puzzle_probe.v", gold)], [("puzzle_recovered_probe.v", gate)] + blocks],
                 "recovered_miter.sv", miter, "recovered_miter")


def prove_against_puzzle(work, rt_src, rt_top, drivers):
    """Step 4: the puzzle's extracted netlist (gold side, e2e.gold_probe()) vs ours."""
    gold = e2e.gold_probe()
    gate = e2e._add_probes(rt_src, rt_top, "puzzle_recovered_probe", drivers)
    with open("formal/recovered_miter.sv") as f:
        miter = f.read()
    return prove(work, [[("puzzle_probe.v", gold)], [("puzzle_recovered_probe.v", gate)]],
                 "recovered_miter.sv", miter, "recovered_miter")


def prove_noprobe(work, gold_group, gold_top, gate_group, gate_top, timeout):
    return prove(work, [gold_group, gate_group], "noprobe_miter.sv", noprobe_miter(gold_top, gate_top),
                 "noprobe_miter", timeout=timeout)


# ------------------------------------------------------------------ mutation ---------

# One-gate functional mutation of the extracted netlist: the instance keeps its name
# and every connection, only its master changes to the dual with the same pin names.
NETLIST_DUALS = {"nand2_2": "nor2_2", "nor2_2": "nand2_2", "and2_2": "or2_2", "or2_2": "and2_2",
                 "and3_2": "or3_2", "or3_2": "and3_2", "nand3_2": "nor3_2", "nor3_2": "nand3_2"}


def pick_instance(ex, lef, flops, accept):
    """The first instance, breadth-first backwards from the D inputs of the counter
    flops (f00-f08, in order), for which accept(instance) holds; so a real fault shows
    within a few cycles. Deterministic. Returns (instance, depth, flop id)."""
    master = {i["name"]: i["master"] for i in ex.instances}
    driver = {}
    inputs = collections.defaultdict(list)
    for m in ex.nets:
        for i, p in m["pins"]:
            if p in SUPPLY_PINS:
                continue
            d = lef[master[i]]["pins"][p]["direction"]
            if d == "OUTPUT":
                driver[m["name"]] = i
            elif d == "INPUT":
                inputs[i].append((p, m["name"]))
    by_name = {i["name"]: i for i in ex.instances}
    flop_names = set(flops.values())
    queue = collections.deque((1, ex.net_of[(flops[f], "D")], f) for f in COUNTER_FLOPS)
    seen = set()
    while queue:
        depth, net, fid = queue.popleft()
        inst = driver.get(net)
        if inst is None or inst in seen:
            continue
        seen.add(inst)
        if accept(by_name[inst]):
            return by_name[inst], depth, fid
        if inst not in flop_names:
            queue.extend((depth + 1, n, fid) for _p, n in sorted(inputs[inst]))
    raise LookupError("no candidate in the counter's cone")


def netlist_mutant(ex, lef, flops, src):
    """Swap one instance's master in the extracted Verilog for its same-pin dual."""
    def ok(i):
        short = i["master"][len(PREFIX):]
        dual = NETLIST_DUALS.get(short)
        return dual is not None and set(lef[i["master"]]["pins"]) == set(lef[PREFIX + dual]["pins"])

    inst, depth, fid = pick_instance(ex, lef, flops, ok)
    new_master = PREFIX + NETLIST_DUALS[inst["master"][len(PREFIX):]]
    pat = re.compile(r"^(\s*)" + re.escape(inst["master"]) + r"(\s+" + re.escape(inst["name"]) + r"\s*\()", re.M)
    out, n = pat.subn(lambda m: m.group(1) + new_master + m.group(2), src)
    changed = sum(a != b for a, b in zip(src.splitlines(), out.splitlines(), strict=True))
    if n != 1 or changed != 1:
        raise ValueError(f"netlist mutation of {inst['name']} changed {n} instances / {changed} lines")
    desc = (f"extracted netlist: {inst['name']} {inst['master'][len(PREFIX):]} -> {new_master[len(PREFIX):]}, "
            f"same instance name and connections ({changed} line of Verilog changed)")
    return out, {"instance": inst["name"], "new_master": new_master, "depth": depth, "toward": fid,
                 "description": desc}


def gds_mutant(ex, lef, flops, gds, top, out):
    """tools/retrace/mutate.py master_swap on the GDS (same footprint, not the same pin
    geometry, so re-extraction shows what extractor 1 makes of the swap; see the module
    docstring for what it cannot see)."""
    sites = {(s["master"], s["x"], s["y"], s["orient"]): s for s in mutate.sites_master_swap(ex, lef)}
    inst, depth, fid = pick_instance(ex, lef, flops,
                                     lambda i: (i["master"], i["x"], i["y"], i["orient"]) in sites)
    site = sites[(inst["master"], inst["x"], inst["y"], inst["orient"])]
    lib = mutate.load(gds)
    mutate.apply_master_swap(lib, top, site, lef, mutate.load_pdk_cells())
    lib.write_gds(out)
    desc = (f"GDS: master_swap {site['master'][len(PREFIX):]} -> {site['new_master'][len(PREFIX):]} at DEF "
            f"({site['x'] / 1000:.3f},{site['y'] / 1000:.3f}) {site['orient']} (tools/retrace/mutate.py), "
            f"then re-extracted")
    return {"instance": inst["name"], "new_master": site["new_master"], "depth": depth, "toward": fid,
            "site": site, "description": desc, "gds": out}


# ------------------------------------------------------------------ 3 replay ---------

_MONITOR = """  always @(posedge clk) begin
    #1;
    $display("CYCLE t=%0t O=%02x success=%b", $time, O, success);
  end
"""


def replay(work, tag, netlist, top, vcd):
    """Replay a recorded VCD on a gate netlist (Icarus + PDK models) and decode O."""
    widths, events = read_vcd(vcd)
    tb = make_testbench(widths, events, top, INPUTS, OUTPUTS, "clk")
    i = tb.rindex("endmodule")
    tb = tb[:i] + _MONITOR + tb[i:]
    tb_path, vvp = os.path.join(work, f"tb_{tag}.v"), os.path.join(work, f"tb_{tag}.vvp")
    with open(tb_path, "w") as f:
        f.write(tb)
    t0 = time.monotonic()
    subprocess.run([f"{BIN}/iverilog", "-g2012", "-DFUNCTIONAL", "-DUNIT_DELAY=", "-o", vvp, tb_path, netlist,
                    *MODELS], check=True, capture_output=True, text=True)
    r = subprocess.run([f"{BIN}/vvp", "-n", vvp], check=True, capture_output=True, text=True)
    secs = round(time.monotonic() - t0, 2)
    with open(os.path.join(work, f"tb_{tag}.log"), "w") as f:
        f.write(r.stdout)
    line = next(ln for ln in r.stdout.splitlines() if ln.startswith("VCD-REPLAY"))
    res = {k: int(v) for k, v in (kv.split("=") for kv in line.split()[1:])}
    o_bytes, succ = [], []
    for ln in r.stdout.splitlines():
        if ln.startswith("CYCLE"):
            kv = dict(x.split("=") for x in ln.split()[1:])
            o_bytes.append(kv["O"])
            succ.append(kv["success"])
    first = succ.index("1") if "1" in succ else None
    msg = None
    if first is not None:
        msg = "".join(chr(int(b, 16)) for b in o_bytes[first:] if re.fullmatch(r"[0-9a-f]{2}", b) and b != "00")
    return {"vcd": vcd, "checked": res["checked"], "errors": res["errors"],
            "mismatches": [ln for ln in r.stdout.splitlines() if ln.startswith("MISMATCH")][:5],
            "cycles": len(succ), "success_first_cycle": first,
            "success_stays_high": first is not None and "0" not in succ[first:] and "x" not in succ[first:],
            "message": msg, "seconds": secs}


# ------------------------------------------------------------------ driver -----------

def _noprobe_groups(src, top, pz_v):
    ours = [("rt_extracted.v", e2e._add_probes(src, top, "rt_extracted", {}))]
    rtl = [(f"{b}.v", Path(f"rtl_recovered/{b}.v")) for b in ["puzzle_recovered"] + BLOCKS]
    puz = [("puzzle_extracted.v", Path(pz_v))]
    return ours, rtl, puz


def run(run_dir, work, noprobe_timeout=0):
    t_all = time.monotonic()
    os.makedirs(work, exist_ok=True)
    lef = read_lef(LEF)
    views = run_views(run_dir)
    res = {"run_dir": run_dir, "gds": views["gds"], "def": views["def"], "work": work, "tools": tool_versions()}

    # 1 extract ------------------------------------------------------------------------
    rt_v = os.path.join(work, "rt_extracted.v")
    (ex, rt_src), secs = _timed(extract, views["gds"], lef, rt_v)
    rt_top = ex.top.name
    d = read_def(views["def"])
    cross = def_vs_extraction(ex, d)
    flops = flop_instances(ex, d)
    drivers = q_nets(ex, flops)
    masters = collections.Counter(i["master"][len(PREFIX):] for i in ex.logic_instances())
    res["extract"] = {"seconds": secs, "netlist": rt_v, "top": rt_top, "summary": ex.summary(),
                      "logic_instances_by_master": dict(sorted(masters.items())),
                      "def_cross_check": cross, "flop_probes": len(drivers),
                      "clock_paths": clock_paths(ex, lef, flops)}
    (groups, cycles), secs = _timed(sim_flop_groups, work, ex, rt_v, rt_top)
    unique = {a[0]: b[0] for a, b in groups if len(a) == len(b) == 1}
    sim_maps = sim_probe_maps(groups)
    res["extract"]["sim_flop_map"] = {
        "seconds": secs, "cycles": cycles, "unique": len(unique),
        "groups_not_unique": [{"rtl": a, "extracted": b} for a, b in groups if not len(a) == len(b) == 1],
        "candidate_maps": len(sim_maps),
        "unique_agree_with_def": sum(unique[f] == flops[f] for f in unique),
        "unique_disagree_with_def": sorted(f for f in unique if unique[f] != flops[f])}
    with open(os.path.join(work, "flop_map.json"), "w") as f:
        json.dump({fid: {"instance": flops[fid], "Q_net": drivers[fid], "sim_unique": unique.get(fid)}
                   for fid in flops}, f, indent=1)

    t0 = time.monotonic()
    pex = Extraction(PUZZLE_GDS, lef, top="puzzle")
    pz_v = os.path.join(work, "puzzle_extracted.v")
    with open(pz_v, "w") as f:
        f.write(pex.to_verilog(DIRS, lef))
    res["puzzle_extract"] = {"seconds": round(time.monotonic() - t0, 2), "netlist": pz_v, "summary": pex.summary()}

    # negative controls: one netlist mutant, one GDS mutant ------------------------------
    mutants = {}
    t0 = time.monotonic()
    nsrc, info = netlist_mutant(ex, lef, flops, rt_src)
    path = os.path.join(work, "mutant_netlist.v")
    with open(path, "w") as f:
        f.write(nsrc)
    mutants["netlist"] = dict(info, netlist=path, src=nsrc, drivers=drivers, seconds=round(time.monotonic() - t0, 2))
    t0 = time.monotonic()
    info = gds_mutant(ex, lef, flops, views["gds"], rt_top, os.path.join(work, "mutant.gds"))
    path = os.path.join(work, "mutant_gds_extracted.v")
    mex, gsrc = extract(info["gds"], lef, path, top=rt_top)
    info["delta"] = netlist_delta(ex, mex)
    info["summary"] = mex.summary()
    # flop positions are unchanged, net names may not be
    mutants["gds"] = dict(info, netlist=path, src=gsrc, drivers=q_nets(mex, flops),
                          seconds=round(time.monotonic() - t0, 2))

    # 2 prove against the RTL, 4 against the puzzle's layout ----------------------------
    res["prove_rtl"] = prove_against_rtl(os.path.join(work, "prove_rtl"), rt_src, rt_top, drivers)
    res["prove_puzzle"] = prove_against_puzzle(os.path.join(work, "prove_puzzle"), rt_src, rt_top, drivers)
    for kind, m in mutants.items():
        m["prove_rtl"] = prove_against_rtl(os.path.join(work, f"prove_rtl_mut_{kind}"), m["src"], rt_top,
                                           m["drivers"])
        m["prove_puzzle"] = prove_against_puzzle(os.path.join(work, f"prove_puzzle_mut_{kind}"), m["src"], rt_top,
                                                 m["drivers"])

    # 2/4 again with flop probes from simulation alone (no DEF): the GDS-only loop ------
    for key, fn in (("prove_rtl_simmap", prove_against_rtl), ("prove_puzzle_simmap", prove_against_puzzle)):
        res[key] = {"status": "NO MAP", "seconds": 0, "detail": "simulation left the map open", "tries": []}
        for k, smap in enumerate(sim_maps):
            r = fn(os.path.join(work, f"{key}_{k}"), rt_src, rt_top, q_nets(ex, smap))
            res[key]["tries"].append({"status": r["status"], "seconds": r["seconds"], "failed": r["failed"][:2],
                                      "pairs_differing_from_def": {f: smap[f] for f in smap if smap[f] != flops[f]}})
            if r["status"] == "PASS":
                res[key] = dict(r, tries=res[key]["tries"],
                                map_equals_def=all(smap[f] == flops[f] for f in flops))
                break
            res[key]["status"] = r["status"]

    # 3 replay --------------------------------------------------------------------------
    res["replay_example"] = replay(work, "example", rt_v, rt_top, EXAMPLE_VCD)
    res["replay_solution"] = replay(work, "solution", rt_v, rt_top, SOLUTION_VCD)
    for kind, m in mutants.items():
        m["replay_solution"] = replay(work, f"solution_mut_{kind}", m["netlist"], rt_top, SOLUTION_VCD)

    # 5 no hints (informational) --------------------------------------------------------
    if noprobe_timeout:
        ours, rtl, puz = _noprobe_groups(rt_src, rt_top, pz_v)
        res["noprobe_rtl"] = prove_noprobe(os.path.join(work, "noprobe_rtl"), ours, "rt_extracted", rtl,
                                         "puzzle_recovered", noprobe_timeout)
        res["noprobe_puzzle"] = prove_noprobe(os.path.join(work, "noprobe_puzzle"), puz, "puzzle", ours,
                                            "rt_extracted", noprobe_timeout)
        for kind, m in mutants.items():
            mo, _, _ = _noprobe_groups(m["src"], rt_top, pz_v)
            m["noprobe_rtl"] = prove_noprobe(os.path.join(work, f"noprobe_rtl_mut_{kind}"), mo, "rt_extracted", rtl,
                                           "puzzle_recovered", noprobe_timeout)
            m["noprobe_puzzle"] = prove_noprobe(os.path.join(work, f"noprobe_puzzle_mut_{kind}"), puz, "puzzle", mo,
                                              "rt_extracted", noprobe_timeout)

    for m in mutants.values():
        del m["src"], m["drivers"]
    res["mutants"] = mutants

    sm = res["extract"]["sim_flop_map"]
    ex_ok = (cross["ok"] and not ex.summary()["diagnostics"] and len(drivers) == 92
             and not sm["unique_disagree_with_def"])
    rs, re_ = res["replay_solution"], res["replay_example"]
    cp = res["extract"]["clock_paths"]
    checks = {
        "1 extraction clean, placement and nets identical to the DEF, 92 flops mapped, "
        "simulation agrees": ex_ok,
        "1 clock: every flop's CLK pin reaches port clk through clock buffers only": cp["ok"] and cp["flops"] == 92,
        "2 our extracted netlist == rtl_recovered (PDR PASS)": res["prove_rtl"]["status"] == "PASS",
        "2 same, flop probes from simulation alone (no DEF)": res["prove_rtl_simmap"]["status"] == "PASS",
    }
    for kind in mutants:
        checks[f"2 {kind} mutant != rtl_recovered (PDR FAIL)"] = mutants[kind]["prove_rtl"]["status"] == "FAIL"
    checks[f"3 example_inputs.vcd: {EXAMPLE_CHECKS} checks, 0 errors"] = (re_["checked"], re_["errors"]) == (
        EXAMPLE_CHECKS, 0)
    checks[f"3 solution.vcd: 0 errors, success rises and stays, O spells {EXPECTED_MESSAGE}"] = (
        rs["checked"] > 0 and rs["errors"] == 0 and rs["success_stays_high"] and rs["message"] == EXPECTED_MESSAGE)
    checks["4 our extracted netlist == puzzle's extracted netlist (PDR PASS)"] = res["prove_puzzle"]["status"] == "PASS"
    checks["4 same, flop probes from simulation alone (no DEF)"] = res["prove_puzzle_simmap"]["status"] == "PASS"
    for kind in mutants:
        checks[f"4 {kind} mutant != puzzle's extracted netlist (PDR FAIL)"] = (
            mutants[kind]["prove_puzzle"]["status"] == "FAIL")
    res["checks"] = checks
    res["ok"] = all(checks.values())
    res["seconds_total"] = round(time.monotonic() - t_all, 1)
    return res


def _proof_line(label, r):
    if r["status"] == "PASS":
        extra = ""
    elif r.get("failed"):
        extra = "; first failing " + ", ".join(f"`{f['assert'].split(';')[0]}` at step {f['step']}"
                                                for f in r["failed"][:2])
    else:
        detail = r["detail"] if isinstance(r["detail"], list) else [r["detail"]]
        extra = "; " + " | ".join(detail[-2:])
    if r.get("tries"):
        extra += "; candidate maps tried: " + ", ".join(
            f"{t['status']} {t['seconds']} s" + (f" (`{t['failed'][0]['assert'].split(';')[0]}` step "
                                                 f"{t['failed'][0]['step']})" if t["failed"] else "")
            for t in r["tries"])
        if "map_equals_def" in r:
            extra += f"; passing map equals the DEF map: {r['map_equals_def']}"
    print(f"{label:32s} PDR {r['status']} in {r['seconds']} s{extra}")


def _replay_line(label, r):
    print(f"{label:32s} checked={r['checked']} errors={r['errors']} cycles={r['cycles']} success from cycle "
          f"{r['success_first_cycle']} (stays high: {r['success_stays_high']}) O={r['message']!r} ({r['seconds']} s)")


def report(res):
    e = res["extract"]
    s, c = e["summary"], e["def_cross_check"]
    print(f"GDS  {res['gds']}")
    print(f"1 extract   {e['seconds']} s: top {e['top']}, {s['instances']} instances, {s['logic_instances']} logic, "
          f"{s['signal_nets']} signal nets, diagnostics {s['diagnostics'] or 'none'}")
    print(f"            DEF: {c['components_same_master_position_orient']}/{c['def_components']} components same "
          f"master/position/orient; {c['nets_identical']}/{c['def_nets_2plus']} multi-pin DEF nets identical "
          f"({c['extracted_nets_2plus']} extracted); flop probes {e['flop_probes']}")
    sm = e["sim_flop_map"]
    print(f"            flop map by simulation alone ({sm['cycles']} cycles, {sm['seconds']} s): {sm['unique']} "
          f"unique, {sm['unique_agree_with_def']} of them as the DEF says (disagree: "
          f"{sm['unique_disagree_with_def'] or 'none'}); identical-trace groups {sm['groups_not_unique']}; "
          f"{sm['candidate_maps']} candidate map(s)")
    cp = e["clock_paths"]
    print(f"            clock: {cp['reach_clk']}/{cp['flops']} flop CLK pins reach port clk through clock buffers "
          f"only (buffers per path {cp['depths']}, masters on the paths {cp['buffer_masters_on_paths']}, "
          f"inversions {cp['inversions']})" + (f"; NOT: {cp['bad']}" if cp["bad"] else ""))
    p = res["puzzle_extract"]
    print(f"            puzzle.gds: {p['summary']['instances']} instances, {p['summary']['logic_instances']} logic "
          f"({p['seconds']} s)")
    for kind, m in res["mutants"].items():
        print(f"   mutant {kind:8s}{m['description']}")
        print(f"                  {m['instance']}, {m['depth']} gate(s) back from the D pin of {m['toward']}")
        if "delta" in m:
            dl = m["delta"]
            print(f"                  re-extracted: masters changed {dl['masters_changed']}, nets changed "
                  f"{dl['nets_changed']}, instances moved {dl['positions_only_in_one']}")
            for ba in dl["pins_before_after"].values():
                for pin in sorted(ba["before"]):
                    before, after = ba["before"][pin], ba["after"].get(pin, [])
                    if before != after:
                        print(f"                  pin {pin}: {len(before)} other member(s) on its net before, "
                              f"{len(after)} after{' (open)' if not after else ''}")
    _proof_line("2 ours vs RTL", res["prove_rtl"])
    _proof_line("  same, sim-only probes", res["prove_rtl_simmap"])
    for kind, m in res["mutants"].items():
        _proof_line(f"  {kind} mutant vs RTL", m["prove_rtl"])
    _replay_line("3 example_inputs.vcd", res["replay_example"])
    _replay_line("3 solution.vcd", res["replay_solution"])
    for kind, m in res["mutants"].items():
        _replay_line(f"  {kind} mutant solution", m["replay_solution"])
    _proof_line("4 ours vs puzzle", res["prove_puzzle"])
    _proof_line("  same, sim-only probes", res["prove_puzzle_simmap"])
    for kind, m in res["mutants"].items():
        _proof_line(f"  {kind} mutant vs puzzle", m["prove_puzzle"])
    if "noprobe_rtl" in res:
        _proof_line("5 no-probe ours vs RTL", res["noprobe_rtl"])
        _proof_line("5 no-probe ours vs puzzle", res["noprobe_puzzle"])
        for kind, m in res["mutants"].items():
            _proof_line(f"  no-probe {kind} mut vs RTL", m["noprobe_rtl"])
            _proof_line(f"  no-probe {kind} mut vs puzzle", m["noprobe_puzzle"])
    for k, v in res["checks"].items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    print(f"round trip {'PASS' if res['ok'] else 'FAIL'} ({res['seconds_total']} s)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", help="a LibreLane run, e.g. out/roundtrip/puzzle_run/upstreamlike")
    ap.add_argument("--work", help="scratch (default out/roundtrip/loop/<run tag>)")
    ap.add_argument("--json", help="results file (default <work>/results.json)")
    ap.add_argument("--no-probe-timeout", type=float, default=0,
                    help="run the probe-free O/success-only proofs with this time limit each, in seconds "
                         "(default 0: skip them)")
    args = ap.parse_args(argv)
    run_dir = os.path.abspath(args.run_dir)
    os.chdir(REPO)  # e2e.py and the RETRACE modules use repo-relative paths
    work = args.work or os.path.join("out/roundtrip/loop", os.path.basename(run_dir.rstrip("/")))
    res = run(run_dir, work, args.no_probe_timeout)
    out = args.json or os.path.join(work, "results.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=1, default=str)
    report(res)
    print(f"results: {out}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
