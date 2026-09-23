"""S3 analysis core: an anonymous gate-level netlist, its cells as Boolean
functions, bit-parallel simulation, fanin cones and SAT (PRD S3, docs/STATUS.md).

Everything a structure recognizer may look at is in `Netlist` (cells by library
master, pins by library pin name, nets as integers) and `GateGraph` (the same
logic as truth tables over integer signals, flops as state elements). Names never
enter either: every loader returns `(Netlist, Key)`, and the `Key` (instance,
net and port names, placement) is for a scoring harness only. The loaders also
permute cell and net ids at random (seeded), so file order, which in a
synthesized netlist follows the RTL, cannot leak structure either.

Library-agnostic: cell functions come from the Liberty file (output-pin function
strings; ff / latch / statetable groups), so sky130_fd_sc_hd and IHP sg13cmos5l
load the same way. Cells absent from the Liberty (TEMPO's SRAM) are black boxes
whose pin directions come from LEF or a Verilog stub.

Sources:
  load_extraction(ex, lib, lef)  a RETRACE Extraction (tools/retrace/extract.py,
                                 tools/tempo/lvs.py extract_tempo()); the GDS has
                                 no names, so this path is anonymous by construction
  load_verilog(path, lib, ...)   a flat structural Verilog netlist

Layers:
  Library, CellModel  Liberty parse; functions as ASTs and truth tables
  Netlist             anonymous structure
  GateGraph           signals and AIG-style literals (2*sig + inv): buffers and
                      inverters folded, constants propagated, gates structurally
                      hashed with sorted fanins and normalized output polarity;
                      flops with an effective next-state literal (scan/enable muxes
                      and clock-gate enables included), clock root, async clear/preset
  Sim                 bit-parallel (numpy uint64, 64*words vectors per pass), two-valued
                      or three-valued (0/1/X), combinational or sequential from reset
  supports(), cone()  flop support sets (bitset DP) and depth-limited cones
  Sat                 CNF of a cone (Tseitin over ISOP covers), solved in-process by
                      z3 or by yices-sat on DIMACS; relation checks between literals

Additions for the S3 control layer and recognizers (docs/S3_DESIGN.md section 8 step 2):
  GateGraph.scratch()        a copy to which derived literals (cofactors, templates,
                             transparency conditions) are added; base signal ids are shared
  GateGraph.cofactor(), substitute()   a literal with sources replaced by literals (built with mk)
  GateGraph.supp_bits(s)     support bitset of any signal (derived ones included)
  GateGraph.wl_labels()      permutation-invariant structural labels (Weisfeiler-Lehman)
  canonical_order(nl)        a canonical (id-free) order of cells and nets (colour refinement with
                             individualization); GateGraph(nl) builds its signals in it by default,
                             so signal ids, flop order and CNF numbering do not depend on ids
  Bdd(g)                     ROBDDs of literals (budgeted), holds() decides Sat.check's question
                             exactly where it fits the budget (XOR-dense logic); opt-in
  GateGraph.net_of_lit()     a net carrying each literal (for claims over opaque net ids)
  eval_tt()                  one truth table evaluated bitwise over lane rows
  Sim(g, words, gates=...)   cone-restricted simulation (only the given gates are evaluated)
  Sim.eval3(..., force=...)  three-valued evaluation with signals forced to values per lane
  Sat.check(..., limit=, extra=, seed=)  deterministic conflict limits (unknown -> (None, None)),
                             extra clauses (blocking), solver seed
  Miter                      CNF over several copies of cones with chosen sources shared,
                             solved under a conflict limit (affinity and equivalence miters)
"""

from __future__ import annotations

import collections
import copy
import dataclasses
import functools
import hashlib
import itertools
import os
import random
import re
import subprocess
import time

import numpy as np

from tools.s3 import params as _params

YICES_SAT = os.path.expanduser("~/ttsetup/oss-cad-suite/bin/yices-sat")
ALL1 = np.uint64(0xFFFFFFFFFFFFFFFF)
_ZERO = np.uint64(0)

# ---------------------------------------------------------------------------
# Budgets of canonical_order() and Bdd: tools.s3.params entries (moved there on 2026-09-22, justified
# there), read once at import and fixed for every run (params.NOT_PER_RUN): the harness builds its
# GateGraph with this same module. They bound work or memory only, never an answer that is given.
CANON_MAX_ROUNDS = _params.CANON_MAX_ROUNDS
CANON_ROUND_BUDGET = _params.CANON_ROUND_BUDGET
CANON_INDIVIDUALIZE = _params.CANON_INDIVIDUALIZE
BDD_MAX_NODES = _params.BDD_MAX_NODES
BDD_MAX_STEPS = _params.BDD_MAX_STEPS
BDD_MAX_VARS = _params.BDD_MAX_VARS
BDD_CACHE_MAX = _params.BDD_CACHE_MAX

# ---------------------------------------------------------------------------
# truth tables: a function of k inputs is an int of 2**k bits, bit m = f(x) with
# x_i = (m >> i) & 1


@functools.cache
def _full(k):
    return (1 << (1 << k)) - 1


@functools.cache
def _vmask(i, k):
    """Truth table of input i among k."""
    s = 1 << i
    return (((1 << s) - 1) << s) * (_full(k) // ((1 << (2 * s)) - 1))


def _cof(tt, k, i, v):
    """Cofactor on input i = v, still a table over k inputs (now independent of i)."""
    m, s = _vmask(i, k), 1 << i
    if v:
        t = tt & m
        return t | (t >> s)
    t = tt & (_full(k) ^ m)
    return t | (t << s)


def _depends(tt, k, i):
    return _cof(tt, k, i, 0) != _cof(tt, k, i, 1)


def _flip(tt, k, i):
    """f(.., !x_i, ..)."""
    m, s = _vmask(i, k), 1 << i
    return ((tt & m) >> s) | ((tt & (_full(k) ^ m)) << s)


@functools.cache
def _drop(tt, k, i):
    """A table over k inputs that does not depend on input i -> k-1 inputs."""
    lo = (1 << i) - 1
    out = 0
    for m in range(1 << (k - 1)):
        if tt >> ((m & lo) | ((m & ~lo) << 1)) & 1:
            out |= 1 << m
    return out


@functools.cache
def _permute(tt, k, perm):
    """New input p is old input perm[p]."""
    out = 0
    for m in range(1 << k):
        old = 0
        for p in range(k):
            if m >> p & 1:
                old |= 1 << perm[p]
        if tt >> old & 1:
            out |= 1 << m
    return out


def tt_of(fn, k):
    """Truth table of a Python predicate over a tuple of k bits."""
    return sum(1 << m for m in range(1 << k) if fn(tuple(m >> i & 1 for i in range(k))))


@functools.cache
def isop(tt, k):
    """Irredundant sum of products (Minato-Morreale) of a complete function:
    a tuple of cubes, each a tuple of (input, value) pairs."""
    return tuple(tuple(sorted(c)) for c in _isop(tt, tt, k, k)[0])


def _isop(L, U, k, top):
    full = _full(k)
    if L == 0:
        return [], 0
    if U == full:
        return [[]], full
    i = top - 1
    while not (_depends(L, k, i) or _depends(U, k, i)):
        i -= 1
    L0, L1, U0, U1 = _cof(L, k, i, 0), _cof(L, k, i, 1), _cof(U, k, i, 0), _cof(U, k, i, 1)
    c0, R0 = _isop(L0 & (full ^ U1), U0, k, i)
    c1, R1 = _isop(L1 & (full ^ U0), U1, k, i)
    cs, Rs = _isop((L0 & (full ^ R0)) | (L1 & (full ^ R1)), U0 & U1, k, i)
    m = _vmask(i, k)
    return [c + [(i, 0)] for c in c0] + [c + [(i, 1)] for c in c1] + cs, (R0 & (full ^ m)) | (R1 & m) | Rs


def _cover_tt(cover, k):
    out = 0
    for cube in cover:
        t = _full(k)
        for i, v in cube:
            t &= _vmask(i, k) if v else _full(k) ^ _vmask(i, k)
        out |= t
    return out


@functools.cache
def canonical_tt(tt, k):
    """The smallest table among all input permutations of `tt` (independent of fanin order)."""
    return min(_permute(tt, k, p) for p in itertools.permutations(range(k)))


@functools.cache
def _eval_plan(tt, k):
    on, off = isop(tt, k), isop(_full(k) ^ tt, k)
    use_off = sum(map(len, off)) < sum(map(len, on))
    return (off if use_off else on), use_off


def eval_tt(tt, k, rows):
    """f(rows) evaluated bitwise: `rows` are k uint64 arrays of one shape (input i = rows[i]);
    the table as in Sim (the smaller of the on-set and off-set ISOPs)."""
    cover, use_off = _eval_plan(tt, k)
    if k == 0:
        return np.full_like(rows[0], ALL1) if (tt & 1 and rows) else None
    acc = None
    neg = {}
    for cube in cover:
        t = None
        for v, b in cube:
            if b:
                x = rows[v]
            else:
                x = neg.get(v)
                if x is None:
                    x = neg[v] = ~rows[v]
            t = x if t is None else t & x
        if t is None:
            t = np.full_like(rows[0], ALL1)
        acc = t if acc is None else acc | t
    if acc is None:
        acc = np.zeros_like(rows[0])
    return ~acc if use_off else acc


# ---------------------------------------------------------------------------
# Liberty

_FTOK = re.compile(r"\s*(?:([A-Za-z_][\w\[\].]*)|([01])|(.))")


def parse_function(s):
    """Liberty Boolean expression -> AST: ('v', name) | ('c', 0/1) | ('!', a) |
    ('&'|'|'|'^', a, b). Precedence as Yosys's libparse: postfix ' and prefix !
    over ^ over & * (and juxtaposition) over | +."""
    toks = []
    for name, const, op in _FTOK.findall(s.strip().strip('"')):
        if op.isspace():
            continue
        tok = ("v", name) if name else ("c", int(const)) if const else ("o", op)
        starts = tok[0] in ("v", "c") or tok in (("o", "("), ("o", "!"))
        if starts and toks and (toks[-1][0] in ("v", "c") or toks[-1] in (("o", ")"), ("o", "'"))):
            toks.append(("o", "&"))  # juxtaposition is AND
        toks.append(tok)
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take():
        pos[0] += 1
        return toks[pos[0] - 1]

    def p_or():
        x = p_and()
        while peek() in (("o", "|"), ("o", "+")):
            take()
            x = ("|", x, p_and())
        return x

    def p_and():
        x = p_xor()
        while peek() in (("o", "&"), ("o", "*")):
            take()
            x = ("&", x, p_xor())
        return x

    def p_xor():
        x = p_un()
        while peek() == ("o", "^"):
            take()
            x = ("^", x, p_un())
        return x

    def p_un():
        if peek() == ("o", "!"):
            take()
            return ("!", p_un())
        x = p_atom()
        while peek() == ("o", "'"):
            take()
            x = ("!", x)
        return x

    def p_atom():
        t = take()
        if t == ("o", "("):
            x = p_or()
            if take() != ("o", ")"):
                raise ValueError(f"unbalanced: {s!r}")
            return x
        if t[0] == "v":
            return ("v", t[1])
        if t[0] == "c":
            return ("c", t[1])
        raise ValueError(f"bad token {t} in {s!r}")

    ast = p_or()
    if pos[0] != len(toks):
        raise ValueError(f"trailing tokens in {s!r}")
    return ast


def ast_vars(ast):
    if ast[0] == "v":
        return {ast[1]}
    if ast[0] == "c":
        return set()
    return set().union(*(ast_vars(a) for a in ast[1:]))


def ast_eval(ast, env, ones):
    """Evaluate on ints/uint64 words; env maps names to values, `ones` is all-ones."""
    op = ast[0]
    if op == "v":
        return env[ast[1]]
    if op == "c":
        return ones if ast[1] else ones & 0
    if op == "!":
        return ones ^ ast_eval(ast[1], env, ones)
    a, b = ast_eval(ast[1], env, ones), ast_eval(ast[2], env, ones)
    return a & b if op == "&" else a | b if op == "|" else a ^ b


@dataclasses.dataclass(frozen=True)
class Func:
    """A Boolean function of named variables: `tt` over `vars` (var i = vars[i])."""
    vars: tuple
    tt: int
    text: str

    @staticmethod
    def parse(text):
        ast = parse_function(text)
        vs = tuple(sorted(ast_vars(ast)))
        k = len(vs)
        return Func(vs, ast_eval(ast, {v: _vmask(i, k) for i, v in enumerate(vs)}, _full(k)), text)


@dataclasses.dataclass
class CellModel:
    """One Liberty cell. kind: comb | ff | latch | icg | physical | unknown."""
    name: str
    kind: str
    pins: dict            # pin -> input | output | inout | internal
    outputs: dict         # output pin -> Func (over input pins; over state vars for ff/latch)
    seq: dict | None = None   # ff: next_state, clocked_on, clear, preset (Func or None), state (IQ, IQN), both
    three_state: dict = dataclasses.field(default_factory=dict)  # pin -> enable-low Func text
    note: str = ""


_GRP = re.compile(r"([A-Za-z_]\w*)\s*\(\s*([^)]*?)\s*\)\s*\{")
_ATT = re.compile(r"([A-Za-z_]\w*)\s*:\s*(.*?)\s*;")


def _unq(s):
    return s.strip().strip('"').strip()


def _read_liberty_groups(path):
    with open(path) as f:
        text = f.read()
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"\\[ \t]*\r?\n", " ", text)
    cells = {}
    stack = []  # (group type, dict to record attributes into, or None)
    for line in text.split("\n"):
        s, pos, n = line, 0, len(line)
        while pos < n:
            while pos < n and s[pos] in " \t\r":
                pos += 1
            if pos >= n:
                break
            if s[pos] == "}":
                stack.pop()
                pos += 1
                continue
            m = _GRP.match(s, pos)
            if m:
                gtype, arg = m.group(1), m.group(2)
                parent = stack[-1] if stack else (None, None)
                rec = None
                if gtype == "cell" and len(stack) == 1:
                    rec = {"name": _unq(arg), "attrs": {}, "pins": {}, "seq": [], "test_cell": False}
                    cells[rec["name"]] = rec
                elif parent[0] == "cell" and parent[1] is not None:
                    cell = parent[1]
                    if gtype == "pin":
                        rec = {}
                        for p in arg.split(","):
                            cell["pins"][_unq(p)] = rec
                    elif gtype in ("ff", "latch", "statetable", "ff_bank", "latch_bank"):
                        rec = {"type": gtype, "args": [_unq(a) for a in arg.split(",")]}
                        cell["seq"].append(rec)
                    elif gtype == "test_cell":
                        cell["test_cell"] = True
                    elif gtype in ("bus", "bundle"):
                        cell["attrs"]["has_bus"] = "true"
                stack.append((gtype, rec))
                pos = m.end()
                continue
            m = _ATT.match(s, pos)
            if m:
                rec = stack[-1][1] if stack else None
                if rec is not None:
                    tgt = rec["attrs"] if "attrs" in rec else rec
                    tgt[m.group(1)] = _unq(m.group(2))
                pos = m.end()
                continue
            j = s.find(";", pos)  # complex attribute, e.g. values ("..."); skip it
            pos = n if j < 0 else j + 1
    return cells


def _model(raw):
    name = raw["name"]
    pins = {p: a.get("direction", "").strip('"') for p, a in raw["pins"].items()}
    outs = [p for p, d in pins.items() if d == "output"]
    ins = {p for p, d in pins.items() if d == "input"}
    seq = [g for g in raw["seq"]]
    three = {p: raw["pins"][p]["three_state"] for p in outs if "three_state" in raw["pins"][p]}
    if any(d == "inout" for d in pins.values()) and not outs:
        return CellModel(name, "unknown", pins, {}, note="inout pin without output function")
    if not outs:
        return CellModel(name, "physical", pins, {}, note="no output pin")
    try:
        if seq and seq[0]["type"] in ("ff", "latch") and len(seq) == 1:
            g = seq[0]
            state = tuple(g["args"][:2]) if len(g["args"]) >= 2 else (g["args"][0], None)
            svars = {v for v in state if v}
            outputs = {}
            for p in outs:
                fn = raw["pins"][p].get("function")
                if fn is None:
                    return CellModel(name, "unknown", pins, {}, note=f"output {p} of a {g['type']} has no function")
                f = Func.parse(fn)
                if not set(f.vars) <= svars:
                    return CellModel(name, "unknown", pins, {}, note=f"output {p} = {fn} is not a function of the state")
                outputs[p] = f
            a = g
            get = lambda key: Func.parse(a[key]) if key in a else None
            cpv = {"L": 0, "H": 1}.get(a.get("clear_preset_var1"), -1)
            if g["type"] == "ff":
                model = {"next_state": get("next_state"), "clocked_on": get("clocked_on"),
                         "clear": get("clear"), "preset": get("preset"), "state": state, "both": cpv}
                ok = model["next_state"] and model["clocked_on"] and "clocked_on_also" not in a
            else:
                model = {"data_in": get("data_in"), "enable": get("enable"), "clear": get("clear"),
                         "preset": get("preset"), "state": state, "both": cpv}
                ok = model["data_in"] and model["enable"]
            for f in model.values():
                if isinstance(f, Func) and not set(f.vars) <= ins | svars:
                    return CellModel(name, "unknown", pins, {}, note=f"{g['type']} refers to non-input {f.text}")
            if not ok:
                return CellModel(name, "unknown", pins, {}, note=f"{g['type']} group incomplete")
            return CellModel(name, g["type"], pins, outputs, model, three)
        if seq and seq[0]["type"] == "statetable":
            gc = [p for p in outs if raw["pins"][p].get("clock_gate_out_pin") == "true"
                  or "state_function" in raw["pins"][p]]
            clocks = [p for p in ins if raw["pins"][p].get("clock") == "true"]
            if len(outs) == 1 and gc and len(clocks) == 1:
                en = sorted(ins - set(clocks))
                return CellModel(name, "icg", pins, {}, {"clock": clocks[0], "enables": tuple(en),
                                                        "state_function": raw["pins"][gc[0]]["state_function"]},
                                 note="latch-based clock gate: GCLK = CLK & latched OR(" + ",".join(en) + ")")
            return CellModel(name, "unknown", pins, {}, note="statetable cell that is not a clock gate")
        if seq:
            return CellModel(name, "unknown", pins, {}, note=f"sequential group {seq[0]['type']} x{len(seq)}")
        outputs = {}
        for p in outs:
            fn = raw["pins"][p].get("function")
            if fn is None:
                return CellModel(name, "unknown", pins, {}, note=f"output {p} has no function")
            f = Func.parse(fn)
            if not set(f.vars) <= ins:
                return CellModel(name, "unknown", pins, {}, note=f"output {p} = {fn} uses non-input pins")
            outputs[p] = f
        note = "three-state output modelled as its data function" if three else ""
        return CellModel(name, "comb", pins, outputs, None, three, note)
    except ValueError as e:
        return CellModel(name, "unknown", pins, {}, note=f"parse error: {e}")


class Library(dict):
    """{cell name: CellModel} from one or more Liberty files."""

    def __init__(self, *paths):
        super().__init__()
        self.paths = paths
        for p in paths:
            for name, raw in _read_liberty_groups(p).items():
                self[name] = _model(raw)

    def unmodelled(self):
        return {n: m.note for n, m in sorted(self.items()) if m.kind == "unknown"}

    def kinds(self):
        return collections.Counter(m.kind for m in self.values())


# ---------------------------------------------------------------------------
# anonymous netlist


@dataclasses.dataclass
class Netlist:
    """Anonymous structure. Cell c is an instance of `master[c]` (a library cell or
    a black box) with `pins[c]` = {pin name: net id}. Nets are 0 .. n_nets-1.
    `inputs`/`outputs` are the primary port nets (bits, in no meaningful order);
    `const` maps nets tied to a supply or a literal to 0/1; `blackbox` gives the
    pin directions of non-library masters; `dropped` counts the physical-only
    instances (fill, decap, tap, antenna) left out. No instance, net or port names."""
    lib: Library
    master: list
    pins: list
    n_nets: int
    inputs: list
    outputs: list
    const: dict
    blackbox: dict
    dropped: dict = dataclasses.field(default_factory=dict)

    def direction(self, cell, pin):
        m = self.master[cell]
        model = self.lib.get(m)
        if model is not None:
            return model.pins.get(pin)
        return self.blackbox.get(m, {}).get(pin)

    def model(self, cell):
        return self.lib.get(self.master[cell])

    @functools.cached_property
    def driver(self):
        d = {}
        for c, conns in enumerate(self.pins):
            for p, n in conns.items():
                if self.direction(c, p) == "output":
                    d.setdefault(n, []).append((c, p))
        return d

    @functools.cached_property
    def loads(self):
        d = collections.defaultdict(list)
        for c, conns in enumerate(self.pins):
            for p, n in conns.items():
                if self.direction(c, p) == "input":
                    d[n].append((c, p))
        return d

    def summary(self):
        kinds = collections.Counter(self.lib[m].kind if m in self.lib else "blackbox" for m in self.master)
        return {"cells": len(self.master), "nets": self.n_nets, "inputs": len(self.inputs),
                "outputs": len(self.outputs), "const_nets": len(self.const), "cell_kinds": dict(kinds),
                "masters": len(set(self.master))}


@dataclasses.dataclass
class Key:
    """The names behind a Netlist's ids: for a scoring harness, never for recognizers."""
    cell_name: list
    net_name: list
    ports: dict           # port bit name -> net id
    position: list | None = None  # (x, y) DBU per cell, extraction only

    def net_id(self, name):
        return self.net_name.index(name)


_BUS_ANGLE = re.compile(r"<(\d+)>$")
_POWER = {"VPWR", "VPB", "VDD", "KAPWR", "VCC"}
_GROUND = {"VGND", "VNB", "VSS", "GND"}


def _build(lib, blackbox, cells, ports, const_nets, seed):
    """cells: [(name, master, {pin: net name}, position)], ports: {port: (net name, dir|None)},
    const_nets: {net name: 0/1}. Returns (Netlist, Key), ids permuted by `seed`."""
    lib_cells = []
    dropped = collections.Counter()
    for name, master, conns, pos in cells:
        model = lib.get(master)
        if model is None and master not in blackbox:
            raise KeyError(f"cell {master} is neither in the Liberty nor a black box")
        if model is not None and model.kind == "physical":
            dropped[master] += 1
            continue
        lib_cells.append((name, master, conns, pos))
    net_names = sorted({n for _nm, _m, conns, _p in lib_cells for n in conns.values()}
                       | {n for n, _d in ports.values()} | set(const_nets))
    order = list(range(len(lib_cells)))
    nperm = list(range(len(net_names)))
    if seed is not None:
        rng = random.Random(seed)
        rng.shuffle(order)
        rng.shuffle(nperm)
    nid = {name: nperm[i] for i, name in enumerate(net_names)}
    net_name = [None] * len(net_names)
    for name, i in nid.items():
        net_name[i] = name
    masters, pins, cname, cpos = [], [], [], []
    for i in order:
        name, master, conns, pos = lib_cells[i]
        masters.append(master)
        pins.append({p: nid[n] for p, n in conns.items()})
        cname.append(name)
        cpos.append(pos)
    nl = Netlist(lib, masters, pins, len(net_names), [], [], {nid[n]: v for n, v in const_nets.items()},
                 blackbox, dict(dropped))
    driven = set(nl.driver)
    ins, outs = set(), set()
    for p, (n, d) in ports.items():
        if d in (None, "inout"):
            d = "output" if nid[n] in driven else "input"
        if d == "output":
            outs.add(nid[n])
        elif nid[n] not in driven and nid[n] not in nl.const:
            ins.add(nid[n])
    rng = random.Random(seed if seed is not None else 0)
    nl.inputs = sorted(ins) if seed is None else rng.sample(sorted(ins), len(ins))
    nl.outputs = sorted(outs) if seed is None else rng.sample(sorted(outs), len(outs))
    key = Key(cname, net_name, {p: nid[n] for p, (n, _d) in ports.items()},
              cpos if any(p is not None for p in cpos) else None)
    return nl, key


def blackbox_from_lef(lef, masters):
    """{master: {pin: input|output|inout}} for non-library masters, from LEF."""
    out = {}
    for m in masters:
        out[m] = {p: (a["direction"] or "").lower() for p, a in lef[m]["pins"].items()
                  if a.get("use", "SIGNAL") not in ("POWER", "GROUND")}
    return out


def load_extraction(ex, lib, lef=None, seed=0):
    """An anonymous Netlist from a RETRACE Extraction. Supply nets become constants;
    port directions are inferred (a port net with a driver is an output)."""
    supply = set(ex.tech.supply_pins)
    const_nets, supply_ports = {}, set()
    for m in ex.nets:
        names = set(m["supply"]) | set(m["ports"])
        if (m["supply"] or m["ports"]) and names <= _POWER | _GROUND:
            v = {1 if s in _POWER else 0 for s in names}
            if len(v) == 1:  # a supply net (a chip-level VPWR/VGND label is not a signal port)
                const_nets[m["name"]] = v.pop()
                supply_ports.update(m["ports"])
    unknown = sorted({i["master"] for i in ex.logic_instances() if i["master"] not in lib})
    bb = blackbox_from_lef(lef, unknown) if lef is not None else {}
    cells = []
    for inst in ex.logic_instances():
        m = inst["master"]
        valid = lib[m].pins if m in lib else bb.get(m, {})
        conns = {}
        for p in inst["pins"]:
            q = p if p in valid else _BUS_ANGLE.sub(r"[\1]", p)  # GDS labels buses as A<3>, LEF as A[3]
            if p in supply or q not in valid:
                continue
            n = ex.net_of.get((inst["name"], p))
            if n is not None:
                conns[q] = n
        cells.append((inst["name"], m, conns, (inst["x"], inst["y"])))
    ports = {}
    for m in ex.nets:
        for p in m["ports"]:
            if p not in supply_ports:
                ports[p] = (m["name"], None)
    return _build(lib, bb, cells, ports, const_nets, seed)


# --- structural Verilog ------------------------------------------------------

_VTOK = re.compile(r"\s*(?:(//[^\n]*)|(/\*.*?\*/)|(\(\*.*?\*\))|\\(\S+)|(\d*'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_?]+|\d+)"
                   r"|([A-Za-z_][\w$]*)|([()\[\]{},;.:=#]))", re.S)
_DIRS = ("input", "output", "inout")


def _const_bits(tok):
    """A Verilog number -> bits MSB first ('0', '1', 'x')."""
    if "'" not in tok:
        v = int(tok)
        return [c for c in format(v, "032b")]
    size, rest = tok.split("'")
    rest = rest.lstrip("sS")
    base, digits = rest[0].lower(), rest[1:].replace("_", "").lower()
    per = {"b": 1, "o": 3, "h": 4, "d": 0}[base]
    if per == 0:
        bits = list(format(int(digits), "b"))
    else:
        bits = []
        for ch in digits:
            if ch in "xz?":
                bits += ["x"] * per
            else:
                bits += list(format(int(ch, 16 if per == 4 else 8 if per == 3 else 2), f"0{per}b"))
    w = int(size) if size else len(bits)
    bits = (["0"] * max(0, w - len(bits)) + bits)[-w:]
    return bits


class _VParser:
    def __init__(self, text):
        self.t = []
        for lc, bc, attr, esc, num, ident, punct in _VTOK.findall(text):
            if lc or bc or attr:
                continue
            self.t.append(("i", esc) if esc else ("n", num) if num else ("i", ident) if ident else ("p", punct))
        self.i = 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)

    def take(self, want=None):
        tok = self.t[self.i]
        if want is not None and tok[1] != want:
            raise ValueError(f"expected {want!r}, got {tok[1]!r} at token {self.i}")
        self.i += 1
        return tok[1]

    def modules(self):
        mods = {}
        while self.i < len(self.t):
            if self.take() == "module":
                m = self.module()
                mods[m["name"]] = m
        return mods

    def rng(self):
        if self.peek()[1] != "[":
            return None
        self.take("[")
        msb = int(self.take())
        self.take(":")
        lsb = int(self.take())
        self.take("]")
        return msb, lsb

    def module(self):
        m = {"name": self.take(), "ports": [], "dirs": {}, "ranges": {}, "assigns": [], "insts": [], "supply": {}}
        if self.peek()[1] == "#":
            self.skip_parens(after="#")
        if self.peek()[1] == "(":
            self.take("(")
            cur_dir, cur_rng = None, None
            while self.peek()[1] != ")":
                tok = self.take()
                if tok in _DIRS:
                    cur_dir, cur_rng = tok, None
                    while self.peek()[1] in ("wire", "reg", "signed", "logic"):
                        self.take()
                    cur_rng = self.rng()
                    continue
                if tok == ",":
                    continue
                m["ports"].append(tok)
                if cur_dir:
                    m["dirs"][tok] = cur_dir
                    if cur_rng:
                        m["ranges"][tok] = cur_rng
            self.take(")")
        self.take(";")
        while True:
            kw = self.take()
            if kw == "endmodule":
                return m
            if kw in _DIRS or kw in ("wire", "reg", "tri", "supply0", "supply1", "wand", "wor"):
                while self.peek()[1] in ("wire", "reg", "signed", "logic"):
                    self.take()
                r = self.rng()
                while True:
                    name = self.take()
                    if kw in _DIRS:
                        m["dirs"][name] = kw
                    if kw in ("supply0", "supply1"):
                        m["supply"][name] = int(kw[-1])
                    if r:
                        m["ranges"][name] = r
                    if self.peek()[1] == "=":  # wire x = expr;
                        self.take("=")
                        m["assigns"].append(([name], self.expr_tokens()))
                    if self.take() == ";":
                        break
                continue
            if kw == "assign":
                while True:
                    lhs = self.expr_tokens()
                    self.take("=")
                    m["assigns"].append((lhs, self.expr_tokens()))
                    if self.take() == ";":
                        break
                continue
            if kw in ("parameter", "localparam", "defparam", "specify", "initial", "always", "function", "task",
                      "generate"):
                raise ValueError(f"{kw!r}: not a flat structural netlist")
            # instance: MASTER [#(...)] NAME ( .pin(expr), ... ) ;
            master = kw
            if self.peek()[1] == "#":
                self.skip_parens(after="#")
            name = self.take()
            self.take("(")
            conns = {}
            while self.peek()[1] != ")":
                if self.peek()[1] == ",":
                    self.take()
                    continue
                self.take(".")
                pin = self.take()
                self.take("(")
                conns[pin] = self.expr_tokens() if self.peek()[1] != ")" else None
                self.take(")")
            self.take(")")
            self.take(";")
            m["insts"].append((master, name, conns))

    def skip_parens(self, after):
        self.take(after)
        depth = 0
        while True:
            tok = self.take()
            depth += tok == "("
            depth -= tok == ")"
            if depth == 0:
                return

    def expr_tokens(self):
        """Collect one expression (up to a top-level , ; ) or =) as raw tokens."""
        out, depth = [], 0
        while True:
            kind, tok = self.peek()
            if depth == 0 and tok in (",", ";", ")", "="):
                return out
            depth += tok in ("{", "(", "[")
            depth -= tok in ("}", ")", "]")
            out.append((kind, tok))
            self.i += 1


def _bits(expr, ranges):
    """Expression tokens -> net bit names, MSB first ('1'b0' constants as '$0'/'$1'/'$x')."""
    pos = [0]

    def peek():
        return expr[pos[0]][1] if pos[0] < len(expr) else None

    def take():
        pos[0] += 1
        return expr[pos[0] - 1]

    def one():
        kind, tok = take()
        if tok == "{":
            if expr[pos[0]][0] == "n" and pos[0] + 1 < len(expr) and expr[pos[0] + 1][1] == "{":
                rep = int(take()[1])
                inner = one()
                take()  # closing }
                return inner * rep
            out = []
            while True:
                out += one()
                t = take()[1]
                if t == "}":
                    return out
        if kind == "n":
            return ["$" + b for b in _const_bits(tok)]
        name = tok
        if peek() == "[":
            take()
            a = int(take()[1])
            if peek() == ":":
                take()
                b = int(take()[1])
                take()
                step = -1 if a >= b else 1
                return [f"{name}[{i}]" for i in range(a, b + step, step)]
            take()
            return [f"{name}[{a}]"]
        if name in ranges:
            a, b = ranges[name]
            step = -1 if a >= b else 1
            return [f"{name}[{i}]" for i in range(a, b + step, step)]
        return [name]

    out = one()
    if pos[0] != len(expr):
        raise ValueError(f"unsupported expression {' '.join(t for _k, t in expr)}")
    return out


def blackbox_from_verilog(path):
    """{module: {pin bit: direction}} from Verilog stub modules (ports only)."""
    with open(path) as f:
        mods = _VParser(f.read()).modules()
    out = {}
    for name, m in mods.items():
        pins = {}
        for p in m["ports"]:
            d = m["dirs"].get(p)
            if p in m["ranges"]:
                a, b = m["ranges"][p]
                for i in range(min(a, b), max(a, b) + 1):
                    pins[f"{p}[{i}]"] = d
            else:
                pins[p] = d
        out[name] = pins
    return out


def load_verilog(path, lib, blackbox=None, top=None, seed=0):
    """An anonymous Netlist from a flat structural Verilog netlist of library cells
    (and black boxes: {master: {pin bit: direction}})."""
    blackbox = blackbox or {}
    with open(path) as f:
        mods = _VParser(f.read()).modules()
    if top is None:
        used = {mst for m in mods.values() for mst, _n, _c in m["insts"]}
        tops = [n for n in mods if n not in used]
        if len(tops) != 1:
            raise ValueError(f"cannot pick a top module among {tops}")
        top = tops[0]
    m = mods[top]
    sub = [mst for mst, _n, _c in m["insts"] if mst in mods]
    if sub:
        raise ValueError(f"hierarchical netlist ({sub[0]} ...): flatten it first")
    parent = {}

    def find(a):
        while parent.get(a, a) != a:
            parent[a] = parent.get(parent[a], parent[a])
            a = parent[a]
        return a

    const = {}
    for lhs, rhs in m["assigns"]:
        lb, rb = _bits(lhs, m["ranges"]), _bits(rhs, m["ranges"])
        if len(rb) < len(lb):
            rb = ["$0"] * (len(lb) - len(rb)) + rb
        for a, b in zip(lb, rb[-len(lb):]):
            if b.startswith("$"):
                const[a] = b
            else:
                ra, rb_ = find(a), find(b)
                if ra != rb_:
                    # keep port names as representatives
                    if ra.split("[")[0] in m["dirs"]:
                        parent[rb_] = ra
                    else:
                        parent[ra] = rb_
    for n, v in m["supply"].items():
        const[n] = f"${v}"
    const_nets, cells = {}, []
    for n, v in const.items():
        if v in ("$0", "$1"):
            const_nets[find(n)] = int(v[1])
    xnets = 0
    for master, name, conns in m["insts"]:
        valid = lib[master].pins if master in lib else blackbox.get(master)
        if valid is None:
            raise KeyError(f"cell {master} is neither in the Liberty nor a black box")
        pins = {}
        for pin, expr in conns.items():
            if expr is None:
                continue
            bits = _bits(expr, m["ranges"])
            if pin in valid:
                names = [pin]
            else:
                idx = sorted((int(p[len(pin) + 1:-1]) for p in valid if p.startswith(pin + "[")), reverse=True)
                names = [f"{pin}[{i}]" for i in idx]
            if len(names) != len(bits):
                raise ValueError(f"{name}.{pin}: {len(bits)} bits for {len(names)} pins")
            for p, b in zip(names, bits):
                if b.startswith("$"):
                    if b == "$x":
                        xnets += 1
                        b = f"$x{xnets}"
                    else:
                        const_nets[b] = int(b[1])
                    pins[p] = b
                else:
                    pins[p] = find(b)
        cells.append((name, master, pins, None))
    ports = {}
    for p in m["ports"]:
        d = m["dirs"].get(p)
        if p in m["ranges"]:
            a, b = m["ranges"][p]
            for i in range(min(a, b), max(a, b) + 1):
                ports[f"{p}[{i}]"] = (find(f"{p}[{i}]"), d)
        else:
            ports[p] = (find(p), d)
    return _build(lib, blackbox, cells, ports, const_nets, seed)


# ---------------------------------------------------------------------------
# canonical (id-free) order of a Netlist's cells and nets

_M1, _M2 = np.uint64(0xBF58476D1CE4E5B9), np.uint64(0x94D049BB133111EB)
_K = [np.uint64(x) for x in (0x9E3779B97F4A7C15, 0xD6E8FEB86659FD93, 0x632BE59BD9B4E019,
                             0xA0761D6478BD642F, 0xE7037ED1A0B428DB, 0x8EBC6AF09C88C6E3)]
_S30, _S27, _S31 = np.uint64(30), np.uint64(27), np.uint64(31)


def _mix64(x):
    """splitmix64's finaliser on a uint64 array (wrapping arithmetic)."""
    x = (x ^ (x >> _S30)) * _M1
    x = (x ^ (x >> _S27)) * _M2
    return x ^ (x >> _S31)


def _h64(*parts):
    return int.from_bytes(hashlib.blake2b(repr(parts).encode(), digest_size=8).digest(), "little")


@dataclasses.dataclass
class CanonicalOrder:
    """Permutation-invariant order of a Netlist's cells and nets (canonical_order())."""
    cell_rank: np.ndarray         # cell id -> position in the canonical order
    net_rank: np.ndarray          # net id -> position
    cells: np.ndarray             # cell ids in canonical order
    nets: np.ndarray              # net ids in canonical order
    stats: dict


def canonical_order(nl):
    """A canonical order of the cells and nets of `nl`: the same netlist under any permutation of
    its cell ids, net ids and port lists gets the same order of the same elements (up to an
    automorphism of the netlist). GateGraph builds its signals in this order, so signal ids, flop
    indices, CNF variable numbers and everything ordered by them are independent of the ids.

    Method: colour refinement (1-dimensional Weisfeiler-Lehman) on the bipartite cell-net graph to
    the stable partition. Initial colours: a library cell's master; a black box's count of pins per
    direction (never its master or pin names, which a harness may anonymise at random); a net's
    port role (input, output) and constant value. Edges carry the library pin name (a black box's
    pin direction). Each round a node's colour becomes a hash of its colour and the multiset of
    (edge label, neighbour colour). Classes of source-creating cells (flops, latches, clock gates,
    black boxes, unmodelled cells) or port nets still tied at the stable partition are broken by
    individualization-refinement: the tied class with the smallest colour gives up one member,
    which gets a new colour, and refinement resumes (the member is the smallest id, a free choice
    when the class is an orbit of the automorphism group). After CANON_INDIVIDUALIZE rounds every
    remaining tied class is broken at once; after CANON_ROUND_BUDGET refinement rounds in all, the
    remaining ties stay (stats: round_budget_hit, ties_left_to_id_order). The final order is by
    colour, then id (ties left there are normally combinational cells and internal nets, which do
    not order anything). Cached on `nl`; stats says what was needed."""
    cache = nl.__dict__.get("_canonical_order")
    if cache is not None:
        return cache
    t0 = time.perf_counter()
    C, N = len(nl.master), nl.n_nets
    ic, inn, il = [], [], []
    col_c = np.zeros(C, np.uint64)
    important_c = np.zeros(C, bool)
    labs = {}
    for c, m in enumerate(nl.master):
        model = nl.lib.get(m)
        conns = nl.pins[c]
        if model is None:
            dirs = nl.blackbox.get(m, {})
            col_c[c] = _h64("bb", tuple(sorted(collections.Counter(str(dirs.get(p)) for p in conns).items())))
            important_c[c] = True
        else:
            col_c[c] = _h64("cell", m)
            important_c[c] = model.kind != "comb"
        for p, n in conns.items():
            lab = ("pin", p) if model is not None else ("bbpin", str(nl.blackbox.get(m, {}).get(p)))
            v = labs.get(lab)
            if v is None:
                v = labs[lab] = _h64(*lab)
            ic.append(c)
            inn.append(n)
            il.append(v)
    ic = np.array(ic, np.int64)
    inn = np.array(inn, np.int64)
    il = np.array(il, np.uint64)
    ins, outs = set(nl.inputs), set(nl.outputs)
    col_n = np.array([_h64("net", n in ins, n in outs, nl.const.get(n, -1)) for n in range(N)], np.uint64)
    important_n = np.zeros(N, bool)
    important_n[list(ins | outs)] = True
    # segment sums: incidences sorted by cell and by net (np.add.reduceat wraps modulo 2**64)
    oc = np.argsort(ic, kind="stable")
    on = np.argsort(inn, kind="stable")
    cs, cstart = np.unique(ic[oc], return_index=True)
    ns_, nstart = np.unique(inn[on], return_index=True)
    il_c, il_n = il[oc], (il * _K[1])[on]
    ic_n, inn_c = ic[on], inn[oc]
    stats = collections.Counter()

    def ndistinct(a, b):
        return len(np.unique(a)) + len(np.unique(b))

    def refine(cc, nc):
        cnt = ndistinct(cc, nc)
        for _r in range(CANON_MAX_ROUNDS):
            if stats["rounds"] >= CANON_ROUND_BUDGET:
                stats["round_budget_hit"] = 1
                break
            stats["rounds"] += 1
            sc = np.zeros(C, np.uint64)
            sn = np.zeros(N, np.uint64)
            if len(ic):
                sc[cs] = np.add.reduceat(_mix64(il_c ^ _mix64(nc[inn_c] + _K[0])), cstart)
                sn[ns_] = np.add.reduceat(_mix64(il_n ^ _mix64(cc[ic_n] + _K[2])), nstart)
            cc2 = _mix64(cc * _K[3] + sc)
            nc2 = _mix64(nc * _K[4] + sn)
            c2 = ndistinct(cc2, nc2)
            cc, nc = cc2, nc2
            if c2 == cnt:
                break
            cnt = c2
        return cc, nc

    def tied(col, imp):
        """Colours of important elements shared by >= 2 of them (sorted)."""
        v = col[imp]
        u, k = np.unique(v, return_counts=True)
        return u[k > 1]

    col_c, col_n = refine(col_c, col_n)
    stats["classes_stable"] = ndistinct(col_c, col_n)
    ind = 0
    while True:
        tc, tn = tied(col_c, important_c), tied(col_n, important_n)
        if not len(tc) and not len(tn):
            break
        if stats["round_budget_hit"]:
            stats["ties_left_to_id_order"] = int(len(tc) + len(tn))
            break
        if ind < CANON_INDIVIDUALIZE:
            # the smallest tied colour over both domains; its smallest-id member
            if len(tc) and (not len(tn) or tc[0] <= tn[0]):
                c = int(np.flatnonzero((col_c == tc[0]) & important_c)[0])
                col_c = col_c.copy()
                col_c[c] = _mix64(np.array([col_c[c] ^ _K[5]], np.uint64))[0]
            else:
                n = int(np.flatnonzero((col_n == tn[0]) & important_n)[0])
                col_n = col_n.copy()
                col_n[n] = _mix64(np.array([col_n[n] ^ _K[5]], np.uint64))[0]
            stats["individualized"] += 1
        else:
            col_c, col_n = col_c.copy(), col_n.copy()
            for col, imp, t in ((col_c, important_c, tc), (col_n, important_n, tn)):
                for v in t:
                    x = int(np.flatnonzero((col == v) & imp)[0])
                    col[x] = _mix64(np.array([col[x] ^ _K[5]], np.uint64))[0]
                    stats["individualized_bulk"] += 1
        ind += 1
        col_c, col_n = refine(col_c, col_n)
    cells = np.lexsort((np.arange(C), col_c))
    nets = np.lexsort((np.arange(N), col_n))
    cell_rank = np.empty(C, np.int64)
    cell_rank[cells] = np.arange(C)
    net_rank = np.empty(N, np.int64)
    net_rank[nets] = np.arange(N)
    stats["classes_final"] = ndistinct(col_c, col_n)
    stats["tied_cells"] = int(C - len(np.unique(col_c)))
    stats["tied_nets"] = int(N - len(np.unique(col_n)))
    st = {k: int(v) for k, v in sorted(stats.items())}
    st["seconds"] = round(time.perf_counter() - t0, 3)
    out = CanonicalOrder(cell_rank, net_rank, cells, nets, st)
    nl.__dict__["_canonical_order"] = out
    return out


# ---------------------------------------------------------------------------
# gate graph

CONST, INPUT, FLOP, BBOX, FREE, GATE = range(6)
KIND_NAMES = ("const", "input", "flop", "bbox", "free", "gate")


@dataclasses.dataclass
class Flop:
    """A clocked state element. Literals are 2*signal + inverted."""
    cell: int       # cell id in the Netlist
    q: int          # the state signal (Q = literal 2q, QN = 2q+1)
    ns: int         # effective next state: scan mux, enable feedback and clock-gate enable folded in
    clk: int        # clock literal at the flop; the flop fires on its rising edge
    clear: int      # async clear literal, active high (0 = none)
    preset: int     # async preset literal, active high (0 = none)
    both: int       # state when clear and preset are both active (0, 1, or -1 if unspecified)
    clk_root: int   # the source signal the clock traces back to through buffers/inverters/clock gates
    clk_inv: int    # 1 when the flop fires on the falling edge of clk_root
    gate_en: int    # clock-gate enable literal (1 = no clock gate); already folded into ns
    pins: dict      # the flop's input pins as literals (D, SCD, SCE, DE, ...)


class GateGraph:
    """The Netlist's logic as signals. Signal 0 is constant 0 (literal 0 = false,
    1 = true). Sources: primary inputs (INPUT), flop states (FLOP), black-box
    outputs (BBOX), and FREE signals (undriven nets, loop cuts, latch/unknown-cell
    outputs, clock-gate outputs). Every other signal is a GATE: a truth table
    `tt[s]` over `fanin[s]` (sorted signal ids, all positive; inversions are
    absorbed into the tables and into output literals). Signal ids are
    topologically ordered: every gate's fanins have smaller ids.

    canonical=True (default): signals are created in canonical_order(nl) (cells, black-box pins and
    ports in that order; multi-driver nets take the first driver in it), so signal ids, the order of
    `flops`, `sources`, CNF variable numbers and everything ordered by them depend on the netlist's
    structure only, never on its cell or net ids. `pi` and `po` stay aligned with nl.inputs and
    nl.outputs. canonical=False builds in id order (the behaviour before 2026-09-22)."""

    def __init__(self, nl: Netlist, strash=True, canonical=True):
        self.nl = nl
        self.kind, self.tt, self.fanin, self.info = [CONST], [0], [()], [None]
        self._hash = {} if strash else None
        self.notes = collections.Counter()
        self.lit_of_net = {}
        self.cell_lit = {}   # cell -> {output pin: literal}
        co = self.canon = canonical_order(nl) if canonical else None
        lib = nl.lib
        lit = self.lit_of_net
        for n, v in nl.const.items():
            lit[n] = v
        self.pi = []
        if co is None:
            for n in nl.inputs:
                if n in lit:
                    continue
                s = self._src(INPUT)
                lit[n] = 2 * s
                self.pi.append(s)
        else:
            for n in sorted(set(nl.inputs), key=lambda n: co.net_rank[n]):
                if n not in lit:
                    lit[n] = 2 * self._src(INPUT)
            seen = set(nl.const)
            for n in nl.inputs:
                if n not in seen:
                    seen.add(n)
                    self.pi.append(lit[n] >> 1)
        self.driver = {}
        for n, ds in nl.driver.items():
            if len(ds) > 1:
                self.notes["multi-driver nets"] += 1
                self.driver[n] = ds[0] if co is None else min(ds, key=lambda d: (co.cell_rank[d[0]], d[1]))
            else:
                self.driver[n] = ds[0]
        cell_seq = range(len(nl.master)) if co is None else [int(c) for c in co.cells]

        def bb_pins(c, want):
            conns = nl.pins[c]
            ps = [p for p, d in nl.blackbox[nl.master[c]].items() if d == want and p in conns]
            return ps if co is None else sorted(ps, key=lambda p: (co.net_rank[conns[p]], p))
        # state elements and other sources first, so every comb cone ends at them
        flop_cells, latch_cells, icg_cells = [], [], []
        self.bb_out, self.bb_in = [], []
        self.icg = {}
        for c in cell_seq:
            master = nl.master[c]
            model = lib.get(master)
            conns = nl.pins[c]
            if model is None:
                for p in bb_pins(c, "output"):
                    s = self._src(BBOX, (c, p))
                    lit[conns[p]] = 2 * s
                    self.bb_out.append(s)
                continue
            if model.kind == "ff":
                q = self._src(FLOP, c)
                sv = model.seq["state"]
                env = {sv[0]: 2 * q}
                if sv[1]:
                    env[sv[1]] = 2 * q + 1
                outs = {}
                for p, f in model.outputs.items():
                    outs[p] = self.mk(f.tt, [env[v] for v in f.vars])
                    if p in conns:
                        lit[conns[p]] = outs[p]
                self.cell_lit[c] = outs
                flop_cells.append((c, q))
            elif model.kind in ("latch", "unknown", "icg"):
                for p in model.outputs or [p for p, d in model.pins.items() if d == "output"]:
                    if p in conns:
                        s = self._src(FREE, (model.kind, c, p))
                        lit[conns[p]] = 2 * s
                        if model.kind == "icg":
                            icg_cells.append((c, s))
                self.notes[f"{model.kind} cells"] += 1
                if model.kind == "latch":
                    latch_cells.append(c)
        # flops
        self.flops = []
        for c, q in flop_cells:
            model = lib[nl.master[c]]
            seq = model.seq
            conns = nl.pins[c]
            sv = seq["state"]
            env = {sv[0]: 2 * q}
            if sv[1]:
                env[sv[1]] = 2 * q + 1
            pins = {}
            for p, d in model.pins.items():
                if d == "input":
                    pins[p] = self.resolve(conns[p]) if p in conns else self._unconnected()
            env.update(pins)
            fn = lambda f: self.mk(f.tt, [env[v] for v in f.vars]) if f is not None else 0
            self.flops.append(Flop(c, q, fn(seq["next_state"]), fn(seq["clocked_on"]), fn(seq["clear"]),
                                   fn(seq["preset"]), seq["both"], 0, 0, 1, pins))
        for c, s in icg_cells:
            model = lib[nl.master[c]]
            conns = nl.pins[c]
            ck = self.resolve(conns[model.seq["clock"]]) if model.seq["clock"] in conns else self._unconnected()
            ens = [self.resolve(conns[p]) if p in conns else 0 for p in model.seq["enables"]]
            self.icg[s] = (ck, self.mk(_full(len(ens)) ^ 1, ens) if ens else 1)
        for f in self.flops:
            clk = f.clk
            s = clk >> 1
            if s in self.icg:
                ck, en = self.icg[s]
                f.gate_en = en
                f.ns = self.mk(tt_of(lambda x: x[1] if x[0] else x[2], 3), [en, f.ns, 2 * f.q])
                clk = ck ^ (clk & 1)
                s = clk >> 1
            f.clk_root, f.clk_inv = s, clk & 1
            if self.kind[s] != INPUT:
                self.notes[f"flops clocked by a {KIND_NAMES[self.kind[s]]} signal"] += 1
        self.latches = latch_cells
        if co is not None:
            for n in sorted(set(nl.outputs), key=lambda n: co.net_rank[n]):
                self.resolve(n)
        self.po = [self.resolve(n) for n in nl.outputs]
        for c in cell_seq:
            if nl.master[c] in nl.blackbox:
                for p in bb_pins(c, "input"):
                    self.bb_in.append((c, p, self.resolve(nl.pins[c][p])))
        self.q = np.array([f.q for f in self.flops], np.int64)
        self.q2flop = {f.q: i for i, f in enumerate(self.flops)}
        self.n = len(self.kind)
        self.level = np.zeros(self.n, np.int32)
        for s in range(self.n):
            if self.kind[s] == GATE:
                self.level[s] = 1 + max(self.level[f] for f in self.fanin[s])

    # --- construction --------------------------------------------------------
    def _src(self, kind, info=None):
        self.kind.append(kind)
        self.tt.append(None)
        self.fanin.append(())
        self.info.append(info)
        return len(self.kind) - 1

    def _unconnected(self):
        self.notes["unconnected input pins"] += 1
        return 2 * self._src(FREE, ("unconnected",))

    def mk(self, tt, lits):
        """The literal of f(lits) for truth table tt: constants, inversions and repeated
        inputs folded into the table, unused inputs dropped, inputs sorted, output
        polarity normalized (f(0..0) = 0), then structurally hashed."""
        lits = list(lits)
        k = len(lits)
        i = 0
        while i < k:
            v = lits[i]
            if v >> 1 == 0:
                tt = _drop(_cof(tt, k, i, v & 1), k, i)
                del lits[i]
                k -= 1
                continue
            if v & 1:
                tt = _flip(tt, k, i)
                lits[i] = v ^ 1
            i += 1
        i = 0
        while i < k:
            j = i + 1
            while j < k:
                if lits[j] == lits[i]:
                    m = _vmask(i, k)
                    t = (_cof(tt, k, j, 0) & (_full(k) ^ m)) | (_cof(tt, k, j, 1) & m)
                    tt = _drop(t, k, j)
                    del lits[j]
                    k -= 1
                else:
                    j += 1
            i += 1
        for i in range(k - 1, -1, -1):
            if not _depends(tt, k, i):
                tt = _drop(tt, k, i)
                del lits[i]
                k -= 1
        order = tuple(sorted(range(k), key=lambda i: lits[i]))
        if order != tuple(range(k)):
            tt = _permute(tt, k, order)
            lits = [lits[i] for i in order]
        if k == 0:
            return tt & 1
        inv = tt & 1
        if inv:
            tt ^= _full(k)
        if k == 1:
            return lits[0] ^ inv
        fan = tuple(v >> 1 for v in lits)
        key = (tt, fan)
        if self._hash is not None and key in self._hash:
            return 2 * self._hash[key] + inv
        s = len(self.kind)
        self.kind.append(GATE)
        self.tt.append(tt)
        self.fanin.append(fan)
        self.info.append(None)
        if self._hash is not None:
            self._hash[key] = s
        return 2 * s + inv

    def resolve(self, net):
        """Literal of a net (resolving its combinational fanin cone on first use)."""
        lit = self.lit_of_net
        if net in lit:
            return lit[net]
        nl = self.nl
        gray = set()
        stack = [net]
        while stack:
            n = stack[-1]
            if n in lit:
                stack.pop()
                continue
            d = self.driver.get(n)
            if d is None:
                lit[n] = 2 * self._src(FREE, ("undriven",))
                self.notes["undriven nets"] += 1
                stack.pop()
                continue
            c, p = d
            model = nl.lib.get(nl.master[c])
            f = model.outputs.get(p) if model is not None and model.kind == "comb" else None
            if f is None:  # an output of a cell kind that was not pre-assigned
                lit[n] = 2 * self._src(FREE, ("unmodelled", c, p))
                stack.pop()
                continue
            conns = nl.pins[c]
            ins = [conns.get(v) for v in f.vars]
            if n not in gray:
                pending = [i for i in ins if i is not None and i not in lit and i not in gray]
                if pending:
                    gray.add(n)
                    stack.extend(pending)
                    continue
            gray.discard(n)
            lits = []
            for i in ins:
                if i is None:
                    lits.append(self._unconnected())
                elif i in lit:
                    lits.append(lit[i])
                else:  # an ancestor still being resolved: a combinational loop; cut it here
                    self.notes["combinational loop cuts"] += 1
                    lits.append(2 * self._src(FREE, ("loop", i)))
            lit[n] = self.mk(f.tt, lits)
            self.cell_lit.setdefault(c, {})[p] = lit[n]
            stack.pop()
        return lit[net]

    # --- queries --------------------------------------------------------------
    @functools.cached_property
    def fanout(self):
        """signal -> gate signals that read it."""
        fo = collections.defaultdict(list)
        for s in range(self.n):
            for f in self.fanin[s]:
                fo[f].append(s)
        return fo

    @functools.cached_property
    def sources(self):
        """Source signals: flop states first (in flop order), then inputs, black-box
        outputs, free signals. Support bitsets index this list."""
        rest = [s for s in range(1, self.n) if self.kind[s] in (INPUT, BBOX, FREE)]
        return [f.q for f in self.flops] + sorted(rest, key=lambda s: (self.kind[s], s))

    def gates(self):
        return [s for s in range(self.n) if self.kind[s] == GATE]

    def summary(self):
        kinds = collections.Counter(KIND_NAMES[k] for k in self.kind)
        ar = collections.Counter(len(self.fanin[s]) for s in range(self.n) if self.kind[s] == GATE)
        return {"signals": self.n, "kinds": dict(kinds), "gate_arity": dict(sorted(ar.items())),
                "distinct_tables": len({(len(self.fanin[s]), self.tt[s]) for s in self.gates()}),
                "depth": int(self.level.max()) if self.n else 0, "flops": len(self.flops),
                "flops_async_clear": sum(f.clear != 0 for f in self.flops),
                "flops_async_preset": sum(f.preset != 0 for f in self.flops),
                "clock_roots": dict(collections.Counter(
                    f"{KIND_NAMES[self.kind[f.clk_root]]} s{f.clk_root} {'fall' if f.clk_inv else 'rise'}"
                    for f in self.flops).most_common()),
                "resolved_cells": len(self.cell_lit),
                "dead_comb_cells": sum(1 for c, m in enumerate(self.nl.master) if c not in self.cell_lit
                                       and m in self.nl.lib and self.nl.lib[m].kind == "comb"),
                "notes": dict(self.notes)}

    # --- cones ---------------------------------------------------------------
    def supports(self, lits=None):
        """Support of each literal (default: every flop's next state) as a Python int
        bitset over `self.sources`; bottom-up over all gates, one pass."""
        idx = {s: i for i, s in enumerate(self.sources)}
        bits = [0] * self.n
        for s, i in idx.items():
            bits[s] = 1 << i
        kind, fanin = self.kind, self.fanin
        for s in range(self.n):
            if kind[s] == GATE:
                b = 0
                for f in fanin[s]:
                    b |= bits[f]
                bits[s] = b
        lits = [f.ns for f in self.flops] if lits is None else lits
        return [bits[v >> 1] for v in lits]

    def unate_supports(self, lits=None):
        """Structural polarity of each source in each literal (default: every flop's next
        state): (pos, neg) lists of int bitsets over `sources`; a source is in pos (neg) when
        some path reaches the literal with even (odd) inversion parity, a binate gate input
        counting as both. A source in both is (structurally) binate: it can move the literal
        both ways (XOR, adders, mux selects); in one only, the literal is unate in it (a copy or
        gating leg). Structural, so it may call binate what is functionally unate."""
        idx = {s: i for i, s in enumerate(self.sources)}
        n = len(self.kind)
        pos, neg = [0] * n, [0] * n
        for s, i in idx.items():
            pos[s] = 1 << i
        kind, fanin, tt = self.kind, self.fanin, self.tt
        for s in range(n):
            if kind[s] != GATE:
                continue
            k = len(fanin[s])
            p = q = 0
            for v, x in enumerate(fanin[s]):
                c0, c1 = _cof(tt[s], k, v, 0), _cof(tt[s], k, v, 1)
                up, down = bool(c1 & ~c0 & _full(k)), bool(c0 & ~c1 & _full(k))
                if up:
                    p |= pos[x]
                    q |= neg[x]
                if down:
                    p |= neg[x]
                    q |= pos[x]
            pos[s], neg[s] = p, q
        lits = [f.ns for f in self.flops] if lits is None else lits
        P, N = [], []
        for v in lits:
            a, b = pos[v >> 1], neg[v >> 1]
            if v & 1:
                a, b = b, a
            P.append(a)
            N.append(b)
        return P, N

    def cone(self, lits, max_depth=None, stop=None):
        """Gates in the transitive fanin of `lits` up to `max_depth` gate levels, and
        the leaves: sources reached, plus gates at the depth limit (the frontier).
        `stop` (set of signals) ends the search early, like sources."""
        seen, leaves = set(), set()
        frontier = [(v >> 1, 0) for v in lits]
        depth = {}
        while frontier:
            s, d = frontier.pop()
            if s in depth and depth[s] <= d:
                continue
            depth[s] = d
            if self.kind[s] != GATE or (stop is not None and s in stop and d > 0):
                leaves.add(s)
                continue
            if max_depth is not None and d >= max_depth:
                leaves.add(s)
                continue
            leaves.discard(s)
            seen.add(s)
            for f in self.fanin[s]:
                frontier.append((f, d + 1))
        return seen, leaves - seen

    # --- derived literals ------------------------------------------------------
    def scratch(self):
        """A copy of this graph for derived literals (cofactors, templates, conditions). Signal ids
        below `n_base` are this graph's and mean the same there; new gates made by `mk` on the copy
        get ids >= n_base and never touch this graph. Queries that iterate `range(self.n)`
        (gates(), supports(), Sim) still see the base signals only."""
        s = copy.copy(self)
        s.kind, s.tt, s.fanin, s.info = list(self.kind), list(self.tt), list(self.fanin), list(self.info)
        s._hash = dict(self._hash) if self._hash is not None else None
        s.notes = collections.Counter(self.notes)
        s.n_base = self.n
        s.__dict__.pop("fanout", None)
        if "_supp" in self.__dict__:
            s.__dict__["_supp"] = list(self.__dict__["_supp"][:self.n])
        return s

    @property
    def n_base(self):
        return self.__dict__.get("_n_base", self.n)

    @n_base.setter
    def n_base(self, v):
        self.__dict__["_n_base"] = v

    def _source_index(self):
        idx = self.__dict__.get("_srcidx")
        if idx is None:
            idx = self.__dict__["_srcidx"] = {s: i for i, s in enumerate(self.sources)}
        return idx

    def supp_bits(self, s):
        """Support of signal s (any id, derived gates included) as an int bitset over `sources`."""
        sup = self.__dict__.get("_supp")
        if sup is None:
            idx = self._source_index()
            sup = [0] * self.n
            for t, i in idx.items():
                sup[t] = 1 << i
            for t in range(self.n):
                if self.kind[t] == GATE:
                    b = 0
                    for f in self.fanin[t]:
                        b |= sup[f]
                    sup[t] = b
            self.__dict__["_supp"] = sup
        while len(sup) <= s:           # derived gates, in id (topological) order
            t = len(sup)
            b = 0
            if self.kind[t] == GATE:
                for f in self.fanin[t]:
                    b |= sup[f]
            else:
                i = self._source_index().get(t)
                b = 0 if i is None else 1 << i
            sup.append(b)
        return sup[s]

    def substitute(self, lit, repl, memo=None):
        """`lit` with signals replaced: repl = {signal: literal}. The rebuilt gates are made with mk
        (constants fold), so call it on a scratch() graph. Only gates whose support meets a
        replaced source are rebuilt (replacing a gate signal rebuilds its whole fanout cone within
        the cone of lit). `memo` ({signal: literal}) may be shared across calls with the same repl."""
        memo = {} if memo is None else memo
        idx = self._source_index()
        mask = 0
        gate_repl = False
        for s in repl:
            if s in idx:
                mask |= 1 << idx[s]
            else:
                gate_repl = True
        root = lit >> 1
        stack = [root]
        while stack:
            s = stack[-1]
            if s in memo:
                stack.pop()
                continue
            if s in repl:
                memo[s] = repl[s]
                stack.pop()
                continue
            if self.kind[s] != GATE or (not gate_repl and not (self.supp_bits(s) & mask)):
                memo[s] = 2 * s
                stack.pop()
                continue
            pending = [f for f in self.fanin[s] if f not in memo]
            if pending:
                stack.extend(pending)
                continue
            new = [memo[f] for f in self.fanin[s]]
            memo[s] = 2 * s if new == [2 * f for f in self.fanin[s]] else self.mk(self.tt[s], new)
            stack.pop()
        return memo[root] ^ (lit & 1)

    def cofactor(self, lit, sig, value, memo=None):
        """`lit` with source signal `sig` fixed to `value` (0/1); see substitute()."""
        return self.substitute(lit, {sig: value}, memo)

    def lit_and(self, a, b):
        return self.mk(0b1000, [a, b])

    def lit_or(self, a, b):
        return self.mk(0b1110, [a, b])

    def lit_xor(self, a, b):
        return self.mk(0b0110, [a, b])

    # --- structure without ids ------------------------------------------------
    def wl_labels(self, rounds=4, salt=b""):
        """Permutation-invariant 64-bit labels of the base signals (Weisfeiler-Lehman refinement).
        Initial label: kind; gates add their table canonical under input permutation; flop states
        add their cell master and clock edge. Each round hashes a signal's label with the sorted
        labels of its fanins and of its fanouts; a flop state also takes its next-state literal's
        label and polarity. Signals with equal labels are structurally alike up to depth `rounds`,
        so the labels can seed anything that must not depend on ids."""
        n = self.n_base

        def h(*parts):
            return int.from_bytes(hashlib.blake2b(repr(parts).encode(), digest_size=8, key=salt[:64]).digest(), "little")

        lab = [0] * n
        ns_of = {f.q: f.ns for f in self.flops}
        master = {f.q: (self.nl.master[f.cell], f.clk_inv) for f in self.flops}
        for s in range(n):
            k = self.kind[s]
            if k == GATE:
                lab[s] = h("g", len(self.fanin[s]), canonical_tt(self.tt[s], len(self.fanin[s])))
            elif k == FLOP:
                lab[s] = h("f", master[s])
            else:
                lab[s] = h("s", k)
        fo = self.fanout
        for _r in range(rounds):
            new = [0] * n
            for s in range(n):
                fi = sorted(lab[f] for f in self.fanin[s]) if self.kind[s] == GATE else ()
                fos = sorted(lab[t] for t in fo.get(s, ()) if t < n)
                extra = ()
                if s in ns_of:
                    v = ns_of[s]
                    extra = (lab[v >> 1], v & 1)
                new[s] = h(lab[s], tuple(fi), tuple(fos), extra)
            lab = new
        return lab

    def net_of_lit(self):
        """{literal: (net, inverted)}: a net carrying each literal that some net carries (the first
        such net in canonical order, or the smallest net id for a canonical=False graph; any of
        them is equivalent). Literal L is carried by net n when lit_of_net[n] is L (inverted 0) or
        L ^ 1 (inverted 1)."""
        out = {}
        co = self.__dict__.get("canon")
        order = sorted(self.lit_of_net) if co is None else sorted(self.lit_of_net, key=lambda n: co.net_rank[n])
        for n in order:
            v = self.lit_of_net[n]
            for L, inv in ((v, 0), (v ^ 1, 1)):
                if L not in out or (out[L][1] and not inv):
                    out[L] = (n, inv)
        return out


def supports_of(bitsets, sources):
    """Decode support bitsets into lists of source signals."""
    out = []
    for b in bitsets:
        lst = []
        while b:
            low = b & -b
            lst.append(sources[low.bit_length() - 1])
            b ^= low
        out.append(lst)
    return out


# ---------------------------------------------------------------------------
# bit-parallel simulation


class Sim:
    """Levelized bit-parallel simulation of a GateGraph: every signal holds `words`
    uint64 words (64*words independent vectors). Gates of one level and one
    truth table are evaluated together with numpy fancy indexing, each table as its
    ISOP (or the complement of its off-set ISOP, whichever has fewer literals).
    Three-valued mode keeps two planes per signal, can-be-0 and can-be-1 (X = both),
    and evaluates on-set and off-set covers, which is exact for each gate."""

    def __init__(self, g: GateGraph, words=1, gates=None):
        """gates: evaluate only these base gates (e.g. a cone: see cone()); default all. The
        caller must provide every other signal the evaluated gates read."""
        self.g, self.W = g, words
        groups = collections.defaultdict(list)
        for s in (g.gates() if gates is None else sorted(s for s in gates if g.kind[s] == GATE and s < g.n)):
            groups[(int(g.level[s]), len(g.fanin[s]), g.tt[s])].append(s)
        self.groups = []
        self.group_of = {}
        for (_lv, k, tt), sigs in sorted(groups.items()):
            out = np.array(sigs, np.int64)
            fan = np.array([g.fanin[s] for s in sigs], np.int64)
            ins = [np.ascontiguousarray(fan[:, j]) for j in range(k)]
            on, off = isop(tt, k), isop(_full(k) ^ tt, k)
            use_off = sum(map(len, off)) < sum(map(len, on))
            for r, s in enumerate(sigs):
                self.group_of[s] = (len(self.groups), r)
            self.groups.append((out, ins, on, off, use_off))
        self.q = g.q
        self.ns = np.array([f.ns for f in g.flops], np.int64)
        self.clear = np.array([f.clear for f in g.flops], np.int64)
        self.preset = np.array([f.preset for f in g.flops], np.int64)
        self.pi = np.array(g.pi, np.int64)
        self.po = np.array(g.po, np.int64)
        self.other = np.array([s for s in range(g.n) if g.kind[s] in (BBOX, FREE)], np.int64)
        asyn = [v >> 1 for v in np.concatenate([self.clear, self.preset])]
        self.async_needs_eval = any(g.kind[s] not in (CONST, INPUT) for s in asyn)
        self.has_async = bool(np.any(self.clear) or np.any(self.preset))

    def zeros(self):
        return np.zeros((self.g.n, self.W), np.uint64)

    def random_sources(self, V, rng):
        src = np.array(self.g.sources, np.int64)
        V[src] = rng.integers(0, 2 ** 64, size=(len(src), self.W), dtype=np.uint64)
        V[0] = 0
        return V

    # --- two-valued ------------------------------------------------------------
    def eval(self, V):
        """Evaluate every gate in place from the source rows of V."""
        for out, ins, on, off, use_off in self.groups:
            X = [V[i] for i in ins]
            nX = {}
            acc = _ZERO
            for cube in (off if use_off else on):
                t = ALL1  # an empty cube is a tautology (only in hand-edited graphs)
                for v, b in cube:
                    if b:
                        x = X[v]
                    else:
                        x = nX.get(v)
                        if x is None:
                            x = nX[v] = ~X[v]
                    t = x if t is ALL1 else t & x
                acc = t if acc is _ZERO else acc | t
            V[out] = ~acc if use_off else acc
        return V

    @staticmethod
    def lits(V, lits):
        """Values of literals (rows)."""
        lits = np.asarray(lits, np.int64)
        out = V[lits >> 1]
        inv = (lits & 1).astype(bool)
        out[inv] = ~out[inv]
        return out

    # --- three-valued ------------------------------------------------------------
    def eval3(self, V0, V1, force=None):
        """Three-valued evaluation in place (V0: can be 0, V1: can be 1). force = (signals, F0, F1):
        after a forced gate is evaluated, lanes set in F0[r] (F1[r]) make signals[r] exactly 0 (1);
        forced sources must be set by the caller."""
        per_group = {}
        if force is not None:
            sigs, F0, F1 = force
            for r, s in enumerate(sigs):
                gi = self.group_of.get(int(s))
                if gi is not None:
                    per_group.setdefault(gi[0], []).append((int(s), r))
        for gi, (out, ins, on, off, _u) in enumerate(self.groups):
            X0 = [V0[i] for i in ins]
            X1 = [V1[i] for i in ins]
            for cover, dst in ((on, V1), (off, V0)):
                acc = _ZERO
                for cube in cover:
                    t = ALL1
                    for v, b in cube:
                        x = X1[v] if b else X0[v]
                        t = x if t is ALL1 else t & x
                    acc = t if acc is _ZERO else acc | t
                dst[out] = acc
            for s, r in per_group.get(gi, ()):
                f0, f1 = F0[r], F1[r]
                V0[s] = (V0[s] & ~f1) | f0
                V1[s] = (V1[s] & ~f0) | f1
        return V0, V1

    @staticmethod
    def lits3(V0, V1, lits):
        lits = np.asarray(lits, np.int64)
        a0, a1 = V0[lits >> 1], V1[lits >> 1]
        inv = (lits & 1).astype(bool)
        a0[inv], a1[inv] = a1[inv], a0[inv].copy()
        return a0, a1

    # --- sequential --------------------------------------------------------------
    def run(self, cycles, inputs, init="x", ternary=True, rng=None, record_state=False):
        """Cycle-based simulation of one clock domain (every flop fires once per cycle).

        inputs(t) gives the primary inputs of cycle t, rows in `g.pi` order: a uint64
        array (n_pi, words), or for ternary runs optionally a (can0, can1) pair.
        init: "x" (ternary only), "zero", "random" or an explicit state (array, or pair).
        Black-box outputs and free signals are X (ternary) or random (two-valued).
        Async clear/preset act at once and at the clock edge. Returns
        {"po": [per-cycle PO values], "state": final state, "states": [...]}"""
        rng = rng or np.random.default_rng(0)
        F, W = len(self.q), self.W
        out = {"po": [], "states": []}
        if ternary:
            V0, V1 = self.zeros(), self.zeros()
            V0[0], V1[0] = ALL1, 0
            if isinstance(init, tuple):
                s0, s1 = init
            elif init == "x":
                s0, s1 = np.full((F, W), ALL1), np.full((F, W), ALL1)
            elif init == "zero":
                s0, s1 = np.full((F, W), ALL1), np.zeros((F, W), np.uint64)
            else:
                r = rng.integers(0, 2 ** 64, size=(F, W), dtype=np.uint64)
                s0, s1 = ~r, r
            for t in range(cycles):
                x = inputs(t)
                i0, i1 = x if isinstance(x, tuple) else (~x, x)
                V0[self.pi], V1[self.pi] = i0, i1
                V0[self.other], V1[self.other] = ALL1, ALL1
                s0, s1 = self._override3(V0, V1, s0, s1)
                V0[self.q], V1[self.q] = s0, s1
                self.eval3(V0, V1)
                out["po"].append(self.lits3(V0, V1, self.po))
                n0, n1 = self.lits3(V0, V1, self.ns)
                s0, s1 = self._override3(V0, V1, n0, n1, evaluated=True)
                if record_state:
                    out["states"].append((s0.copy(), s1.copy()))
            out["state"] = (s0, s1)
            return out
        V = self.zeros()
        if isinstance(init, np.ndarray):
            s = init
        elif init == "random":
            s = rng.integers(0, 2 ** 64, size=(F, W), dtype=np.uint64)
        else:
            s = np.zeros((F, W), np.uint64)
        for t in range(cycles):
            V[self.pi] = inputs(t)
            V[self.other] = rng.integers(0, 2 ** 64, size=(len(self.other), W), dtype=np.uint64)
            s = self._override(V, s)
            V[self.q] = s
            self.eval(V)
            out["po"].append(self.lits(V, self.po))
            s = self._override(V, self.lits(V, self.ns), evaluated=True)
            if record_state:
                out["states"].append(s.copy())
        out["state"] = s
        return out

    def _override(self, V, s, evaluated=False):
        if not self.has_async:
            return s
        if self.async_needs_eval and not evaluated:
            V[self.q] = s
            self.eval(V)
        c, p = self.lits(V, self.clear), self.lits(V, self.preset)
        return (s & ~c) | p

    def _override3(self, V0, V1, s0, s1, evaluated=False):
        if not self.has_async:
            return s0, s1
        if self.async_needs_eval and not evaluated:
            V0[self.q], V1[self.q] = s0, s1
            self.eval3(V0, V1)
        c0, c1 = self.lits3(V0, V1, self.clear)
        p0, p1 = self.lits3(V0, V1, self.preset)
        s0, s1 = s0 | c1, s1 & c0   # clear: may be 0 if clear may be 1; cannot be 1 if clear surely 1
        return s0 & p0, s1 | p1


# ---------------------------------------------------------------------------
# SAT


class Sat:
    """Relation checks on a GateGraph by SAT over the combinational cone.

    check(lits, tt, assume) asks: does the relation `tt` (a truth table over the
    literals `lits`, input i = lits[i]) hold for every value of the cone's sources,
    given that every literal in `assume` is true? The cone of all literals is
    encoded in CNF (per gate: one clause per on-set and off-set ISOP cube) and
    solved by `backend`: "z3" (z3's SAT core in-process, fed DIMACS text; the
    fastest here), "z3-api" (the same solver, clauses built as z3 Bool objects) or
    "yices" (yices-sat on DIMACS, a subprocess). pysat is not installed.
    Returns (True, None) or (False, counterexample {source signal: 0/1})."""

    def __init__(self, g: GateGraph, backend="z3"):
        self.g, self.backend = g, backend
        self.stats = collections.Counter()

    def cnf(self, lits):
        """Clauses (DIMACS literals; variable of signal s is s+1) for the cone of lits."""
        g = self.g
        gates, leaves = g.cone(lits)
        clauses = [[-1]]
        for s in sorted(gates):
            k = len(g.fanin[s])
            fan = g.fanin[s]
            for cube in isop(g.tt[s], k):
                clauses.append([-(fan[v] + 1) if b else fan[v] + 1 for v, b in cube] + [s + 1])
            for cube in isop(_full(k) ^ g.tt[s], k):
                clauses.append([-(fan[v] + 1) if b else fan[v] + 1 for v, b in cube] + [-(s + 1)])
        return clauses, gates, leaves

    @staticmethod
    def _dl(lit):
        v = (lit >> 1) + 1
        return -v if lit & 1 else v

    def check(self, lits, tt, assume=(), limit=None, extra=(), seed=None):
        """limit: z3 conflict limit (deterministic; None = unlimited): when it is reached the
        answer is (None, None). extra: clauses over graph literals (each a list of literals, one
        of which must hold), e.g. blocking clauses. seed: the solver's random seed (z3 only)."""
        t0 = time.perf_counter()
        lits, assume = list(lits), list(assume)
        extra = [list(c) for c in extra]
        clauses, gates, leaves = self.cnf(lits + assume + [v for c in extra for v in c])
        r = len(self.g.kind) + 1  # relation output variable (above every signal, derived included)
        k = len(lits)
        dl = [self._dl(v) for v in lits]
        for cube in isop(tt, k):
            clauses.append([-dl[v] if b else dl[v] for v, b in cube] + [r])
        for cube in isop(_full(k) ^ tt, k):
            clauses.append([-dl[v] if b else dl[v] for v, b in cube] + [-r])
        clauses.append([-r])
        clauses += [[self._dl(a)] for a in assume]
        clauses += [[self._dl(a) for a in c] for c in extra]
        self.stats["clauses"] += len(clauses)
        self.stats["gates"] += len(gates)
        t1 = time.perf_counter()
        # dense renumbering: DIMACS variables are signal ids, and solvers allocate up to the largest
        dense = {}
        for c in clauses:
            for v in c:
                dense.setdefault(abs(v), len(dense) + 1)
        clauses = [[dense[v] if v > 0 else -dense[-v] for v in c] for c in clauses]
        if self.backend == "z3":
            want = [dense[s + 1] for s in leaves if (s + 1) in dense]
            sat, model = solve_dimacs(clauses, limit, seed, len(dense), want)
        else:
            sat, model = {"z3-api": self._z3, "yices": self._yices}[self.backend](clauses, len(dense))
        if model is not None:
            back = {d: v for v, d in dense.items()}
            model = {back[d]: b for d, b in model.items() if d in back}
        t2 = time.perf_counter()
        self.stats["encode_s"] += t1 - t0
        self.stats["solve_s"] += t2 - t1
        self.stats["calls"] += 1
        if sat is None:
            self.stats["unknown"] += 1
            return None, None
        if not sat:
            return True, None
        return False, {s: model.get(s + 1, 0) for s in leaves if self.g.kind[s] != CONST}

    def equal(self, a, b, assume=(), limit=None):
        """a == b for every source assignment (literals; b ^ 1 checks a == !b)."""
        return self.check([a, b], 0b1001, assume, limit=limit)

    def _z3(self, clauses, nvars):
        import z3
        s = z3.SolverFor("QF_FD")
        v = {}

        def var(i):
            x = v.get(i)
            if x is None:
                x = v[i] = z3.Bool(f"v{i}")
            return x

        for c in clauses:
            s.add(z3.Or([var(l) if l > 0 else z3.Not(var(-l)) for l in c]) if len(c) > 1 else
                  (var(c[0]) if c[0] > 0 else z3.Not(var(-c[0]))))
        res = s.check()
        if res == z3.unsat:
            return False, None
        m = s.model()
        return True, {i: int(z3.is_true(m.eval(x, model_completion=True))) for i, x in v.items()}

    @staticmethod
    def dimacs(clauses, nvars=None):
        if nvars is None:
            nvars = max(max(map(abs, c)) for c in clauses if c)
        body = " 0\n".join(" ".join(map(str, c)) for c in clauses)
        return f"p cnf {nvars} {len(clauses)}\n{body} 0\n"

    def _z3_dimacs(self, clauses, nvars, limit=None, seed=None):
        return solve_dimacs(clauses, limit, seed)

    def _yices(self, clauses, nvars):
        text = self.dimacs(clauses)
        r = subprocess.run([YICES_SAT, "--model", "/dev/stdin"], input=text, capture_output=True, text=True)
        lines = r.stdout.split()
        if not lines or lines[0] not in ("sat", "unsat"):
            raise RuntimeError(f"yices-sat: {r.stdout[:200]} {r.stderr[:200]}")
        if lines[0] == "unsat":
            return False, None
        return True, {abs(int(t)): int(int(t) > 0) for t in lines[1:] if t not in ("0",)}


def solve_dimacs(clauses, limit=None, seed=None, nvars=None, want=None):
    """z3's SAT core on DIMACS clauses (variables 1..N). Returns (True, {var: 0/1}),
    (False, None), or (None, None) when the conflict limit is reached (deterministic).
    want: the variables whose values the caller needs (default all); others may be missing."""
    import z3
    # A fresh context per query: in a shared context z3 can return different models for the same
    # DIMACS text (its internal ids differ between parses), which would make lanes irreproducible.
    s = z3.SolverFor("QF_FD", ctx=z3.Context())
    if limit is not None:
        s.set("max_conflicts", int(limit))
    if seed is not None:
        s.set("random_seed", int(seed))
    s.from_string(Sat.dimacs(clauses, nvars) if clauses else "p cnf 1 0\n")  # variable N is named "k!N"
    r = s.check()
    if r == z3.unsat:
        return False, None
    if r != z3.sat:
        return None, None
    m = s.model()
    want = None if want is None else {f"k!{v}" for v in want}
    out = {}
    for d in m.decls():
        nm = d.name()
        if nm.startswith("k!") and (want is None or nm in want):
            out[int(nm[2:])] = int(z3.is_true(m[d]))
    return True, out


# ---------------------------------------------------------------------------
# BDD proofs (opt-in; an exact decision procedure beside SAT)


class _BddOverflow(Exception):
    pass


class Bdd:
    """Reduced ordered BDDs of a GateGraph's literals (a scratch graph's derived gates included),
    variables = the graph's sources in `sources` order (canonical for a canonical graph). No
    complement edges; node 0 is false, 1 true. One manager per graph: a signal's BDD is built once
    (bottom-up through its fanin, each gate by Shannon expansion of its table) and reused; a signal
    over budget is marked and never retried.

    holds(lits, tt, assume) decides Sat.check's question exactly: True when the relation holds
    for every source assignment with every assumed literal true, False when it does not, None when
    over budget. XOR-dense logic, where CDCL SAT stalls, has small BDDs under any order; wide
    arithmetic and muxes may not, and those fall back to SAT."""

    def __init__(self, g, max_nodes=BDD_MAX_NODES, max_steps=BDD_MAX_STEPS, max_vars=BDD_MAX_VARS):
        self.g = g
        self.max_nodes, self.max_steps, self.max_vars = min(max_nodes, (1 << 21) - 1), max_steps, max_vars
        self.lv = [1 << 30, 1 << 30]
        self.lo = [0, 1]
        self.hi = [0, 1]
        self.uniq = {}
        self.cache = {}
        self.memo = {0: 0}
        self.level = g._source_index()
        self.steps = 0
        self.stats = collections.Counter()

    def _node(self, l, lo, hi):
        if lo == hi:
            return lo
        k = (l << 42) | (lo << 21) | hi
        r = self.uniq.get(k)
        if r is None:
            r = len(self.lv)
            if r >= self.max_nodes:
                self.stats["overflow_nodes"] += 1
                raise _BddOverflow
            self.lv.append(l)
            self.lo.append(lo)
            self.hi.append(hi)
            self.uniq[k] = r
        return r

    def ite(self, f, g, h):
        if f < 2:
            return g if f else h
        if g == h:
            return g
        if g == 1 and h == 0:
            return f
        k = (f << 42) | (g << 21) | h
        r = self.cache.get(k)
        if r is not None:
            return r
        self.steps += 1
        if self.steps > self.max_steps:
            self.stats["overflow_steps"] += 1
            raise _BddOverflow
        lv, lo, hi = self.lv, self.lo, self.hi
        l = lv[f]
        if lv[g] < l:
            l = lv[g]
        if lv[h] < l:
            l = lv[h]
        f0, f1 = (lo[f], hi[f]) if lv[f] == l else (f, f)
        g0, g1 = (lo[g], hi[g]) if lv[g] == l else (g, g)
        h0, h1 = (lo[h], hi[h]) if lv[h] == l else (h, h)
        r = self._node(l, self.ite(f0, g0, h0), self.ite(f1, g1, h1))
        if len(self.cache) >= BDD_CACHE_MAX:
            self.cache.clear()
        self.cache[k] = r
        return r

    def _table(self, tt, xs):
        """BDD of the truth table tt over the BDDs xs (input i = xs[i])."""
        memo = {}

        def rec(t, j):
            if t == 0:
                return 0
            if t == _full(j):
                return 1
            key = (t, j)
            r = memo.get(key)
            if r is None:     # rows with input j-1 = 0 are the low half of the table
                h = 1 << (j - 1)
                t0, t1 = t & _full(j - 1), t >> h
                r = memo[key] = self.ite(xs[j - 1], rec(t1, j - 1), rec(t0, j - 1))
            return r
        return rec(tt, len(xs))

    def signal(self, s):
        """BDD node of signal s, or -1 when over budget (or its support is too wide)."""
        m = self.memo
        r = m.get(s)
        if r is not None:
            return r
        g = self.g
        if bin(g.supp_bits(s)).count("1") > self.max_vars:
            m[s] = -1
            self.stats["too_wide"] += 1
            return -1
        stack = [s]
        while stack:
            t = stack[-1]
            if t in m:
                stack.pop()
                continue
            if g.kind[t] != GATE:
                lvl = self.level.get(t)
                try:
                    m[t] = -1 if lvl is None else self._node(lvl, 0, 1)
                except _BddOverflow:
                    m[t] = -1
                stack.pop()
                continue
            pend = [f for f in g.fanin[t] if f not in m]
            if pend:
                stack.extend(pend)
                continue
            xs = [m[f] for f in g.fanin[t]]
            if min(xs) < 0:
                m[t] = -1
            else:
                self.steps = 0
                try:
                    m[t] = self._table(g.tt[t], xs)
                    self.stats["gates"] += 1
                except _BddOverflow:
                    m[t] = -1
            stack.pop()
        return m[s]

    def literal(self, lit):
        n = self.signal(lit >> 1)
        if n < 0 or not lit & 1:
            return n
        self.steps = 0
        try:
            return self.ite(n, 0, 1)
        except _BddOverflow:
            return -1

    def holds(self, lits, tt, assume=()):
        """Sat.check's question, decided on BDDs: True | False | None (over budget)."""
        xs = [self.literal(v) for v in lits]
        asm = [self.literal(v) for v in assume]
        if (xs and min(xs) < 0) or (asm and min(asm) < 0):
            self.stats["gave_up"] += 1
            return None
        self.steps = 0
        try:
            rel = self._table(tt, xs)
            a = 1
            for x in asm:
                a = self.ite(a, x, 0)
            bad = self.ite(a, self.ite(rel, 0, 1), 0)
        except _BddOverflow:
            self.stats["gave_up"] += 1
            return None
        self.stats["decided"] += 1
        return bad == 0

    @property
    def nodes(self):
        return len(self.lv)


class Miter:
    """CNF over several copies of cones of one GateGraph (a scratch graph's derived gates
    included). Copy c encodes a literal's cone on first use; the sources listed in `shared` when a
    copy is made take the same variable as in the copy they are shared with. Relations are added
    as clauses over DIMACS literals (lit()/gate()/add()), then solve() under a conflict limit.

        m = Miter(g); a = m.copy(); b = m.copy(share=a, sources=params)
        m.add([m.lit(a, f) , m.lit(b, f)]) ...; ok, model = m.solve(limit=10000)
        m.sources(model, a) -> {source signal: 0/1} of copy a
    """

    def __init__(self, g: GateGraph):
        self.g = g
        self.nv = 1                   # variable 1 is constant false
        self.clauses = [[-1]]
        self.maps = []                # per copy: {signal: DIMACS var}
        self.stats = collections.Counter()

    def copy(self, share=None, sources=()):
        m = {0: 1}
        if share is not None:
            base = self.maps[share]
            for s in sources:
                m[s] = self._var_of(share, s) if s not in base else base[s]
        self.maps.append(m)
        return len(self.maps) - 1

    def new_var(self):
        self.nv += 1
        return self.nv

    def _var_of(self, c, s):
        m = self.maps[c]
        v = m.get(s)
        if v is not None:
            return v
        g = self.g
        stack = [s]
        while stack:
            t = stack[-1]
            if t in m:
                stack.pop()
                continue
            if g.kind[t] != GATE:
                m[t] = self.new_var()
                stack.pop()
                continue
            pending = [f for f in g.fanin[t] if f not in m]
            if pending:
                stack.extend(pending)
                continue
            k = len(g.fanin[t])
            fan = [m[f] for f in g.fanin[t]]
            y = m[t] = self.new_var()
            for cube in isop(g.tt[t], k):
                self.clauses.append([-fan[i] if b else fan[i] for i, b in cube] + [y])
            for cube in isop(_full(k) ^ g.tt[t], k):
                self.clauses.append([-fan[i] if b else fan[i] for i, b in cube] + [-y])
            stack.pop()
        return m[s]

    def lit(self, c, lit):
        """DIMACS literal of graph literal `lit` in copy c."""
        v = self._var_of(c, lit >> 1)
        return -v if lit & 1 else v

    def gate(self, tt, dlits):
        """A new variable equal to tt(dlits) (DIMACS literals, input i = dlits[i])."""
        k = len(dlits)
        y = self.new_var()
        for cube in isop(tt, k):
            self.clauses.append([-dlits[i] if b else dlits[i] for i, b in cube] + [y])
        for cube in isop(_full(k) ^ tt, k):
            self.clauses.append([-dlits[i] if b else dlits[i] for i, b in cube] + [-y])
        return y

    def add(self, clause):
        self.clauses.append(list(clause))

    def solve(self, assume=(), limit=None, seed=None, want=None):
        """want: DIMACS variables whose values are needed (default: every copy's sources and
        every variable passed in `assume`)."""
        t0 = time.perf_counter()
        cl = self.clauses + [[a] for a in assume]
        if want is None:
            g = self.g
            want = {v for m in self.maps for s, v in m.items() if s and g.kind[s] != GATE}
        sat, model = solve_dimacs(cl, limit, seed, self.nv, want)
        self.stats["calls"] += 1
        self.stats["solve_s"] += time.perf_counter() - t0
        if sat is None:
            self.stats["unknown"] += 1
        return sat, model

    def sources(self, model, c):
        """{source signal: 0/1} of copy c in a model (sources its encoded cones reach)."""
        g = self.g
        return {s: model.get(v, 0) for s, v in self.maps[c].items() if s and g.kind[s] != GATE}


# ---------------------------------------------------------------------------
# anonymity check


def strings_in(obj, seen=None, out=None):
    """Every str reachable from obj's containers/attributes (for the anonymity check)."""
    seen = set() if seen is None else seen
    out = set() if out is None else out
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, str):
            out.add(o)
            continue
        if isinstance(o, (int, float, bool, type(None), bytes, np.ndarray, np.generic)):
            continue
        if id(o) in seen:
            continue
        seen.add(id(o))
        if isinstance(o, dict):
            stack.extend(o.keys())
            stack.extend(o.values())
        elif isinstance(o, (list, tuple, set, frozenset)):
            stack.extend(o)
        elif hasattr(o, "__dict__"):
            stack.extend(vars(o).values())
    return out
