"""V7 harness: per-block combinational equivalence between recovered RTL and the netlist.

The 92 flops are partitioned into blocks (rtl_recovered/blocks.json, generated here).
Each flop gets a stable id fNN. For a block, the "gold" module is the exact netlist
logic, cut at flops: its inputs are the primary input ports and the Q outputs of every
flop the block reads (q_fNN), and its outputs are the next-state value of each of the
block's flops (d_fNN) plus any primary outputs the block owns (O, success). Recovered
RTL for the block must implement a module `rec_<block>` with the same ports, and is
accepted only when a SAT miter proves it combinationally equivalent to the gold module.
Together with the flop list (reset kind per flop) this is a full register-correspondence
equivalence proof of the design.

    python -m tools.analysis.cone blocks                 # (re)write rtl_recovered/blocks.json
    python -m tools.analysis.cone gold BLOCK             # write rtl_recovered/gold/gold_BLOCK.v and a stub
    python -m tools.analysis.cone check BLOCK RTL.v      # prove rec_BLOCK == gold_BLOCK
"""

import argparse
import collections
import functools
import json
import os
import subprocess
import sys

from tools.retrace.extract import PREFIX, SUPPLY_PINS, Extraction
from tools.retrace.lef import read_lef

GDS = "upstream/puzzle.gds"
LEF = "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"
LIB = "pdk/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
YOSYS = os.path.expanduser("~/ttsetup/oss-cad-suite/bin/yosys")
BLOCKS = "rtl_recovered/blocks.json"
GOLD_DIR = "rtl_recovered/gold"
INPUT_PORTS = ("clk", "rst_n", "enable", "I")
FLOP_KINDS = {"dfrtp": "async_reset_to_0", "dfstp": "async_set_to_1", "dfxtp": "no_reset"}


@functools.cache
def design():
    lef = read_lef(LEF)
    ex = Extraction(GDS, lef)
    inst = {i["name"]: i for i in ex.logic_instances()}
    pins = collections.defaultdict(dict)
    for (i, p), n in ex.net_of.items():
        if i in inst and p not in SUPPLY_PINS:
            pins[i][p] = n
    direction = lambda i, p: lef[inst[i]["master"]]["pins"][p]["direction"]
    driver = {}
    for i, ps in pins.items():
        for p, n in ps.items():
            if direction(i, p) == "OUTPUT":
                driver[n] = (i, p)
    for port, sid in ex.ports.items():
        if port in INPUT_PORTS:
            driver[ex.uf.find(sid)] = None
    port_net = {}
    for m in ex.nets:
        for p in m["ports"]:
            port_net[p] = m["name"]
    return ex, lef, inst, pins, direction, driver, port_net


def kind(master):
    short = master[len(PREFIX):]
    return next((v for k, v in FLOP_KINDS.items() if short.startswith(k)), None)


def _block_of(x, y, scc_of, f):
    """Partition found by the flop-level SCC scout (docs/STATUS.md); positions in um."""
    if f in scc_of["counter"]:
        return "counter"
    if x > 160 and y > 265:
        return "check"
    if x > 160:
        return "outgen"
    if 105 < x < 130:
        return "array"
    if x < 100 and y > 85:
        return "left_top"
    if x < 100:
        return "left_bottom"
    raise ValueError((f, x, y))


def write_blocks():
    import networkx as nx

    ex, lef, inst, pins, direction, driver, port_net = design()
    flops = sorted(i for i in inst if kind(inst[i]["master"]))
    deps = {f: cone_sources(pins[f]["D"])[1] for f in flops}
    g = nx.DiGraph()
    g.add_nodes_from(flops)
    for f, src in deps.items():
        g.add_edges_from((s, f) for s in src)
    sccs = sorted(nx.strongly_connected_components(g), key=len, reverse=True)
    counter = sccs[0]  # the 9-flop SCC every other block depends on
    blocks = collections.defaultdict(list)
    for f in flops:
        x, y = inst[f]["x"] / 1000, inst[f]["y"] / 1000
        blocks[_block_of(x, y, {"counter": counter}, f)].append(f)
    order = ["counter", "array", "left_top", "left_bottom", "check", "outgen"]
    table, k = {}, 0
    for b in order:
        for f in sorted(blocks[b], key=lambda f: (inst[f]["y"], inst[f]["x"])):
            m = inst[f]["master"]
            table[f"f{k:02d}"] = {
                "instance": f, "master": m, "kind": kind(m), "block": b,
                "x_um": inst[f]["x"] / 1000, "y_um": inst[f]["y"] / 1000,
                "Q_net": pins[f]["Q"], "D_net": pins[f]["D"],
                "reset_net": pins[f].get("RESET_B") or pins[f].get("SET_B"),
                "clk_net": pins[f]["CLK"],
            }
            k += 1
    # success is the Q of a check-block flop; every O[i] is combinational in outgen
    owners = {"success": "check", **{f"O[{i}]": "outgen" for i in range(8)}}
    out = {"flops": table, "outputs": owners,
           "note": "flop ids fNN are stable for this GDS; blocks from the SCC/placement scout"}
    os.makedirs("rtl_recovered", exist_ok=True)
    with open(BLOCKS, "w") as f:
        json.dump(out, f, indent=1)
    return out


def cone_sources(net):
    """Combinational cells, source flops, and input ports behind a net."""
    ex, lef, inst, pins, direction, driver, port_net = design()
    seen, stack, cells, flops, ports = set(), [net], set(), set(), set()
    port_of = {v: k for k, v in port_net.items()}
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        if n in port_of and port_of[n] in INPUT_PORTS:
            ports.add(port_of[n])
            continue
        d = driver.get(n)
        if d is None:
            raise ValueError(f"net {n} has no driver")
        i, _p = d
        if kind(inst[i]["master"]):
            flops.add(i)
            continue
        cells.add(i)
        for q, nn in pins[i].items():
            if direction(i, q) == "INPUT":
                stack.append(nn)
    return cells, flops, ports


def clock_sources(net):
    """Cells between a flop CLK pin and its source; they must all be buffers of clk."""
    ex, lef, inst, pins, direction, driver, port_net = design()
    cells, _flops, ports = cone_sources(net)
    return sorted({inst[c]["master"][len(PREFIX):] for c in cells}), ports


@functools.cache
def blocks():
    with open(BLOCKS) as f:
        return json.load(f)


def gold_module(block):
    ex, lef, inst, pins, direction, driver, port_net = design()
    b = blocks()
    fid = {v["instance"]: k for k, v in b["flops"].items()}
    mine = {k: v for k, v in b["flops"].items() if v["block"] == block}
    targets = {f"d_{k}": v["D_net"] for k, v in mine.items()}
    for o, owner in b["outputs"].items():
        if owner == block:
            targets[o] = port_net[o]
    cells, flops, ports = set(), set(), set()
    for n in targets.values():
        c, f, p = cone_sources(n)
        cells |= c
        flops |= f
        ports |= p
    # reset/set pins must come straight from rst_n; checked, not modelled
    for k, v in mine.items():
        assert v["reset_net"] in (None, port_net["rst_n"]), (k, v["reset_net"])
    rename = {pins[f]["Q"]: f"q_{fid[f]}" for f in flops}
    rename.update({port_net[p]: p for p in ports})
    # nets named after output port bits ("O[3]") must not be emitted as `wire O[3];`,
    # which Verilog reads as an unconnected array and leaves the real O port undriven
    for o in targets:
        if "[" in o and port_net[o] not in rename:
            rename[port_net[o]] = "o_" + o.replace("[", "").replace("]", "")
    ins = sorted(ports) + sorted(f"q_{fid[f]}" for f in flops)
    outs = list(targets)
    bus_o = sorted(o for o in outs if o.startswith("O["))
    scalar_outs = [o for o in outs if not o.startswith("O[")]
    header = ins + scalar_outs + (["O"] if bus_o else [])
    lines = [f"// gold cone of block {block}, generated by tools/analysis/cone.py; do not edit",
             f"module gold_{block} ({', '.join(header)});"]
    lines += [f"  input {p};" for p in ins]
    lines += [f"  output {o};" for o in scalar_outs]
    if bus_o:
        idx = sorted(int(o[2:-1]) for o in bus_o)
        lines.append(f"  output [{max(idx)}:{min(idx)}] O;")
    ref = lambda n: rename.get(n, n)
    internal = set()
    body = []
    for c in sorted(cells):
        conns = []
        for p, n in sorted(pins[c].items()):
            r = ref(n)
            if r == n:
                internal.add(n)
            conns.append(f".{p}({r})")
        body.append(f"  {inst[c]['master']} {c} ({', '.join(conns)});")
    lines += [f"  wire {n};" for n in sorted(internal)]
    lines += [f"  wire {r};" for r in sorted(v for v in rename.values() if v.startswith("o_"))]
    lines += body
    for o, n in targets.items():
        lines.append(f"  assign {o} = {ref(n)};")
    lines.append("endmodule")
    stub = [f"// interface of block {block}; implement the body (combinational only)",
            f"module rec_{block} ({', '.join(header)});"]
    stub += [f"  input {p};" for p in ins]
    stub += [f"  output {o};" for o in scalar_outs]
    if bus_o:
        stub.append(f"  output [{max(idx)}:{min(idx)}] O;")
    stub.append("endmodule")
    return "\n".join(lines) + "\n", "\n".join(stub) + "\n", {"inputs": ins, "outputs": header[len(ins):],
                                                              "cells": len(cells)}


def write_gold(block):
    gold, stub, info = gold_module(block)
    os.makedirs(GOLD_DIR, exist_ok=True)
    with open(f"{GOLD_DIR}/gold_{block}.v", "w") as f:
        f.write(gold)
    with open(f"{GOLD_DIR}/rec_{block}.stub.v", "w") as f:
        f.write(stub)
    return info


def check(block, rtl):
    """SAT-prove rec_<block> (in rtl) equivalent to gold_<block>. Returns (ok, log)."""
    write_gold(block)
    script = (f"read_liberty -ignore_miss_func {LIB}; read_verilog {GOLD_DIR}/gold_{block}.v; "
              f"read_verilog -sv {rtl}; hierarchy -check; proc; flatten; opt_clean; "
              f"miter -equiv -flatten -make_assert gold_{block} rec_{block} miter; "
              f"hierarchy -top miter; sat -verify -prove-asserts -show-inputs -show-outputs miter")
    r = subprocess.run([YOSYS, "-p", script], capture_output=True, text=True)
    ok = r.returncode == 0 and "SUCCESS!" in r.stdout
    return ok, (r.stdout + r.stderr)[-6000:]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("blocks")
    g = sub.add_parser("gold")
    g.add_argument("block")
    c = sub.add_parser("check")
    c.add_argument("block")
    c.add_argument("rtl")
    args = ap.parse_args(argv)
    if args.cmd == "blocks":
        out = write_blocks()
        print(json.dumps(collections.Counter(v["block"] for v in out["flops"].values())))
        for k, v in out["flops"].items():
            masters, ports = clock_sources(v["clk_net"])
            assert ports == {"clk"} and all(m.startswith(("clkbuf", "buf")) for m in masters), (k, masters, ports)
        print("all 92 flops clocked by clk through buffers only")
    elif args.cmd == "gold":
        print(json.dumps(write_gold(args.block)))
    else:
        ok, log = check(args.block, args.rtl)
        print(log if not ok else "EQUIVALENT")
        print("V7", args.block, "PASS" if ok else "FAIL")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
