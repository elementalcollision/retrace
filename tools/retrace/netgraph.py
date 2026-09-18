"""Structural netlist comparison by labelled graph isomorphism.

A cell-level netlist becomes a bipartite graph: one node per cell instance (label = cell
type), one node per net (label = port name for top-level ports, else empty), and one
edge per pin connection (label = pin name). Two netlists are structurally identical
exactly when these graphs are isomorphic, whatever the instance and net names are.

Netlists are read through Yosys (`read_liberty -lib` + `read_verilog` + `write_json`), so
any structural Verilog Yosys accepts can be compared.
"""

import json
import os
import subprocess
import tempfile

import networkx as nx
from networkx.algorithms import isomorphism

YOSYS = os.environ.get("YOSYS", os.path.expanduser("~/ttsetup/oss-cad-suite/bin/yosys"))
LIB = "pdk/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
PHYSICAL = ("tapvpwrvgnd", "decap", "fill", "diode")
SUPPLY = {"VPWR", "VGND", "VPB", "VNB"}


def yosys_json(verilog, top):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as t:
        out = t.name
    script = f"read_liberty -lib {LIB}; read_verilog {verilog}; hierarchy -top {top}; write_json {out}"
    subprocess.run([YOSYS, "-q", "-p", script], check=True)
    with open(out) as f:
        data = json.load(f)
    os.unlink(out)
    return data["modules"][top]


def graph(module):
    """Bipartite labelled graph of a Yosys JSON module; physical-only cells dropped."""
    g = nx.Graph()
    bit_port = {}
    for name, port in module["ports"].items():
        for i, bit in enumerate(port["bits"]):
            if isinstance(bit, int):
                bit_port[bit] = name if len(port["bits"]) == 1 else f"{name}[{i}]"
    for cname, cell in module["cells"].items():
        ctype = cell["type"].split("__")[-1]
        if ctype.startswith(PHYSICAL):
            continue
        g.add_node(("c", cname), kind="cell", label=cell["type"])
        for pin, bits in cell["connections"].items():
            if pin in SUPPLY:
                continue
            for bit in bits:
                if isinstance(bit, str):  # constant
                    node = ("k", bit)
                    g.add_node(node, kind="const", label=bit)
                else:
                    node = ("n", bit)
                    g.add_node(node, kind="net", label=bit_port.get(bit, ""))
                g.add_edge(("c", cname), node, pin=pin)
    return g


def isomorphic(g1, g2):
    nm = isomorphism.categorical_node_match(["kind", "label"], [None, None])
    em = isomorphism.categorical_edge_match("pin", None)
    return nx.is_isomorphic(g1, g2, node_match=nm, edge_match=em)


def compare(verilog_a, top_a, verilog_b, top_b):
    ga, gb = graph(yosys_json(verilog_a, top_a)), graph(yosys_json(verilog_b, top_b))
    stats = lambda g: {k: sum(1 for _n, d in g.nodes(data=True) if d["kind"] == k) for k in ("cell", "net", "const")}
    return isomorphic(ga, gb), stats(ga), stats(gb)
