"""Puzzle extraction checks (docs/spec/VERIFICATION.md V5 electrical sanity).

There is no golden netlist for the puzzle; these checks hold for any correctly
extracted synchronous netlist, so a missed or false connection usually trips one.
"""

import collections
import functools

import pytest

from tools.retrace.extract import PHYSICAL, PREFIX, SUPPLY_PINS, Extraction
from tools.retrace.lef import read_lef

GDS = "upstream/puzzle.gds"
LEF = "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"
INPUTS = {"clk", "rst_n", "enable", "I"}
OUTPUTS = {"success"} | {f"O[{i}]" for i in range(8)}


@functools.cache
def lef():
    return read_lef(LEF)


@functools.cache
def extraction():
    return Extraction(GDS, lef())


def _is_logic(inst_name):
    master = next(i["master"] for i in extraction().instances if i["name"] == inst_name)
    return not master[len(PREFIX):].startswith(PHYSICAL)


@functools.cache
def masters():
    return {i["name"]: i["master"] for i in extraction().instances}


def _direction(inst, pin):
    return lef()[masters()[inst]]["pins"][pin]["direction"]


def _signal_nets():
    for m in extraction().nets:
        pins = [(i, p) for i, p in m["pins"] if p not in SUPPLY_PINS]
        if pins or m["ports"]:
            yield m, pins


def test_no_diagnostics():
    assert dict(extraction().diag) == {}, extraction().notes[:10]


def test_all_ports_bound():
    assert set(extraction().ports) == INPUTS | OUTPUTS


def test_supplies_separate_and_complete():
    sup = [m for m in extraction().nets if m["supply"]]
    assert sorted(tuple(sorted(m["supply"])) for m in sup) == [("VGND",), ("VPWR",)]
    n_inst = len(extraction().instances)
    for m in sup:
        (name,) = m["supply"]
        pins = collections.Counter(p for _i, p in m["pins"])
        assert set(pins) == {name}, f"{name} net touches signal pins {pins}"
        assert pins[name] == n_inst, f"{name} reaches {pins[name]} of {n_inst} instances"


def test_every_signal_net_has_exactly_one_driver():
    bad = []
    for m, pins in _signal_nets():
        drivers = [ip for ip in pins if _direction(*ip) == "OUTPUT"]
        drivers += [("PORT", p) for p in m["ports"] if p in INPUTS]
        if len(drivers) != 1:
            bad.append((m["name"], drivers, pins[:4], m["ports"]))
    assert not bad, bad[:5]


def test_no_floating_logic_inputs():
    floating = []
    for m, pins in _signal_nets():
        driven = any(_direction(*ip) == "OUTPUT" for ip in pins) or any(p in INPUTS for p in m["ports"])
        if not driven:
            floating += [ip for ip in pins if _is_logic(ip[0])]
    assert not floating, floating[:10]


def test_unloaded_outputs_are_only_known_benign():
    """Unloaded outputs must be (a) clock-tree dummy loads: a clkbuf whose input is on a
    clock net and whose output goes nowhere (OpenROAD CTS balancing), or (b) the unused
    output of a conb_1 tie cell. Anything else would be a missed connection."""
    unexpected = []
    clk_bufs = 0
    for m, pins in _signal_nets():
        loads = [ip for ip in pins if _direction(*ip) == "INPUT"] + [p for p in m["ports"] if p in OUTPUTS]
        if loads:
            continue
        for inst, pin in pins:
            short = masters()[inst][len(PREFIX):]
            if short.startswith("conb_"):
                continue
            if short.startswith("clkbuf_"):
                net_a = extraction().net_of[(inst, "A")]
                clk_pins = [p for m2 in extraction().nets if m2["name"] == net_a for _i, p in m2["pins"] if p == "CLK"]
                if clk_pins:
                    clk_bufs += 1
                    continue
            unexpected.append((inst, pin))
    assert not unexpected, unexpected
    assert clk_bufs == 15
