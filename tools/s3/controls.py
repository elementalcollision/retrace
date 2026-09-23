"""S3 control layer: lanes, reset, literal classes, witnesses, per-flop control profiles, support
structure and conditional copy relations (the S3 design doc, sections 3.1-3.4, with the part-1
feasibility review's fixes). Every recognizer (shift, counter, LFSR, grouping) builds on it.

Everything is computed from the anonymous `Netlist` alone (no names, no files). Simulation
suggests; SAT decides every fact reported as proven (cover steps, control relations, literal
classes, constants, duplicates, copy classes); SAT runs under deterministic conflict limits
(params SAT_LIMIT*, a per-run call cap SAT_CALLS_MAX), never wall-clock timeouts; a check SAT
leaves open after SAT_STAGE1 conflicts is tried on BDDs (netlist.Bdd) before SAT's full limit, which
only turns 'unknown' into proofs (XOR-dense cones), for internal facts (literal classes, duplicates,
copy classes, grouping hold classes), never for the template and cover-step proofs that become claims
(BDD_PROFILES). Permutation invariance: the GateGraph is built
in netlist.canonical_order (colour refinement of the netlist), so signal ids, flop indices and CNF
variable numbers are canonical; every order here is (structural label, signal id or flop index),
never a cell or net id. Pool lanes are seeded by structural (Weisfeiler-Lehman) labels with
canonical tie-breaks, and witness lanes come from SAT models of canonical CNF (z3 is deterministic
on identical input), so the lanes, and everything computed from them, are the same for the same
netlist under any id permutation (up to an automorphism of the netlist).

API
---
    ctl = analyze(nl, params=None)   # every stage in STAGES; params overrides tools.s3.params
    ctl = Controls(nl, params); for st in STAGES: getattr(ctl, st)()     # stage by stage

  Stages (STAGES, in order): build, find_reset, make_pool, support_graph, rare_flops,
  rare_literals, literal_classes, control_relations, confirm_controls, profiles,
  find_duplicates, copy_relations, support_blocks, finish.

  Graph and lanes
    ctl.g, ctl.S, ctl.sat         base GateGraph; its scratch copy (derived literals: cofactors,
                                  conditions, templates); Sat on S (base literals mean the same)
    ctl.flops, ctl.F              g.flops; flop index i <-> ctl.flops[i].cell (the result's flop id)
    ctl.f(i), ctl.qlit(i)         next-state literal f_i and state literal of flop i
    ctl.W, ctl.lanes              64-lane words in use, lanes (<= POOL_CAP)
    ctl.value(lit)                lane values of any literal (base or derived): uint64[W]
    ctl.live                      lanes where the reset is inactive, and the mode selector (below)
                                  is in its functional mode (uint64[W])
    ctl.count(lit, mask=None)     lanes where lit = 1 (within mask, default live)
    ctl.active(i)                 live lanes where f_i != q_i; ctl.active_count (numpy, per flop)
    ctl.origin, origin_counts()   origin of each word, lanes per origin (pool, case, case_dom,
                                  literal, fraig, confirm, uncovered, cover, copy, copy_class)
    ctl.labels                    structural labels of the base signals (deterministic seeds)
    ctl.supp_src[i], supp_flops[i]   source signals, flop indices in supp(f_i)

  Flop model (schema "Flop model": what the harness verifies against)
    ctl.f(i) is the flop's EFFECTIVE next state. the netlist module folds the cell's scan / enable logic
    and an ICG cell's enable into Flop.ns; build() also folds LOGIC on the clock path (gclk =
    clk & en, no ICG cell) as an enable, by the harness's rule -- the gate must be unate in its
    clock root, enable = c|root=1 & ~c|root=0 on the rising edge (the mirror image on the falling
    one) -- and moves the flop's clk_root / clk_inv to that root (ctl.clock_gates {flop index:
    enable literal}, _fold_clock_gates, CLOCK_GATE_FOLD). Without it the recognizer sees a flop
    that updates every clock where the harness sees an enabled one, and every correct claim about
    such a design is refuted.

  Mode selector (ctl.mode, _find_mode in make_pool -- after the reset is known, so the reset's own
  literal is never taken for a mode; MODE_SELECT)
    A two-input mux on D whose select is a global, high-fanout literal (a DFT scan enable is the
    standard case: under se the design's flops chain into a scan chain, under ~se they do their own
    work) is a mode selector. ctl.live is then restricted to the functional cofactor, so every
    simulation-driven search sees one mode instead of a mixture of two; the SAT proofs of every
    recognizer still run on the RAW next state, so a recognizer's conditions have to grow to include
    the select and the test mode comes back as the counter's opaque load case. ctl.mode is None (no
    restriction) or {"sig", "test", "keep", "muxed", "chained", "chained_other", "net"}.

  Reset (ctl.reset: Reset)
    kind 'sync' | 'async' | 'none'; lit (active-high literal rho: a gate or a source, found by a
    ternary forcing pass over every gate literal and source); support (its source signals);
    forced (next states it forces); values {flop index: reset value}; inactive (SAT assignments
    of the support with rho = 0, used to pin lanes: every witness lane and 1 - 1/RESET_FREE_EVERY
    of the pool); async_lits {flop index: (clear, preset)}. A synchronous rho must force >=
    RESET_SYNC_FRAC of the flops, else the async clear/preset class is the reset (lanes unpinned).
    ctl.assume()                  [~rho] for a synchronous reset, else []

  SAT (with ~rho assumed, conflict-limited)
    ctl.check(lits, tt, extra=(), limit=None, bdd=False)   Sat.check: (True, None) | (False, cex) |
                                  (None, None); bdd=True staged through BDDs (SAT_STAGE1)
    ctl.equal(a, b, bdd=False)    a == b: True | False | None (unknown or budget spent)
    ctl.witness(lit, extra=())    ('sat', {source: 0/1}) | ('unsat', None) | ('unknown', None)
    ctl.witness_lanes(lit)        witness lit = 1 and add WITNESS_LANES lanes copying it
    ctl.add_lanes([(assignment, n)], origin)   lanes copying assignments, other sources random
                                  (biased), rho pinned inactive; returns lanes added (0 at the cap)
    ctl.case_witnesses(word, extra_lits=(), max_witnesses=CASE_WITNESSES, want=N_MIN)
                                  case-conditioned witnesses of "the word does not hold" (some
                                  f_k != q_k, rho inactive, every extra literal 1): each witness is
                                  blocked after use on its critical sources (those whose flip
                                  stops the word), copied onto them with the rest random, and only
                                  active lanes are kept; returns {"witnesses", "lanes",
                                  "active_lanes", "status", "blocks"} (pass blocks back to continue)
    Pre-passes: rare_flops (words = rare flops per support SCC; UNSAT marks them ctl.quiescent,
    proven) and, in profiles pass 1, rare flops by dominant cover class. rare_literals witnesses
    every candidate literal with < N_MIN live lanes in either polarity (UNSAT: ctl.const_live).

  Literal classes (FRAIG-style over the depth-CLASS_DEPTH cones of every f_i, under ~rho)
    ctl.rep(lit)                  class representative literal (0/1 for proven constants)
    ctl.members(rep_lit)          the class's literals
    ctl.const_live                {signal: value} proven constant while the reset is inactive

  Control classes and profiles (section 3.2)
    ctl.control[L]                ControlClass: literal L (a class representative) with the flops
                                  it holds (L = 1 -> f = q) and sets (L = 1 -> f = v), counted only
                                  with CONTROL_EVIDENCE expected coincidences, SAT-confirmed (one
                                  miter per class, CONFIRM_CONTROLS); >= CONTROL_MIN_FLOPS flops
    ctl.profile[i]                Profile: reset value; ordered cover steps [(L, 'h' | 0 | 1)] (a
                                  priority chain, each step SAT-proven given the earlier ones inactive)
                                  drawn from control classes, ranked by flops controlled, f_i's
                                  own literal and its SAT-equals excluded, at most COVER_CAP holds
                                  and COVER_CAP sets; holds, sets; template on the uncovered lanes
                                  (const v | hold | copy s | copy_inv s | toggle | affine ([s], c) |
                                  other | unknown), tested before each further step; case literals
                                  ('other': [(L, template, arg, lanes)], CASE_DEPTH cone, CASE_CAP);
                                  dominant (the step literal controlling most flops); signature
                                  (clock root, edge, async classes, dominant); quiescent
    ctl.duplicates                [[flop indices]]: f SAT-equal (no assumption), same clock/async

  Support structure (section 3.4)
    ctl.sccs                      SCCs (>= 2 flops) of the state-support graph
    ctl.blocks[k]                 SCC k's blocks in dependency order (block-triangular over the
                                  combining supports: legs of wide unate muxes are transfers, cut)
    ctl.block_split(comp, share)  blocks cutting at cover literals shared by >= share of the flops
    ctl.data_flops[i]             flops reached from f_i without passing its cover literals or rho
    ctl.chains                    nested-support chains, LSB first: every bit's support holds every
                                  lower bit, no bit's data support a higher one, the LSB can invert
                                  itself (ctl.self_neg); readers may sit on top: test prefixes
    ctl.self_neg[i], self_binate[i]  structural polarity of q_i in f_i

  Conditional copies (section 3.3)
    ctl.transparency(i, j)        (T, T_inv) derived literals: T = f_i|j=1 & ~f_i|j=0 (f_i copies
                                  source j where T = 1), T_inv = ~f_i|j=1 & f_i|j=0 (f_i = ~j)
    ctl.copy_edges                [CopyEdge(src, dst, inv, cond, lanes, cls, depth)]: sources within
                                  COPY_DEPTH levels of f_i whose T (T_inv) is satisfiable with rho
                                  inactive; cond is exact and sufficient (cond -> f_dst = src ^ inv)
    ctl.copy_classes              {cls: [edge indices]}: exact conditions SAT-equal under ~rho, at
                                  most one edge per destination; ctl.uncond_class: cond == 1
    ctl.class_cond(cls)           (literal, live lanes) of an exact class
    ctl.copy_groups               [{"classes", "edges", "lanes"}]: exact classes whose conditions
                                  co-occur far above chance, grown along copy paths (a one-hot
                                  parallel mux leaks bit-specific terms into T in unreachable
                                  multi-hot states, so one shift's exact conditions differ);
                                  "lanes" live lanes satisfy the conjunction (non-vacuous)
    ctl.group_cond(grp)           the conjunction: sufficient for every edge of the group at once
    ctl.joint_cond(edge_ids)      (literal, live lanes) of the conjunction of any edges
    ctl.similar_classes(cls)      exact classes whose conditions co-occur with cls

  Claims (schema: proof claims over opaque ids)
    ctl.expr(lit)                 EXPR ({"q"}, {"net"}, {"const"}, {"not"}, {"and"}, {"or"})
    ctl.cond(lits)                COND [{"net", "value"}] when every literal is carried by a net
    ctl.cubes(lit, max_inputs=12) the literal as a list of CONDs (ISOP over its net cut), or None

  Report
    ctl.meta()                    JSON-ready facts for result["meta"] (reset, per-flop active-lane
                                  counts keyed by flop id, lanes, profiles, classes, structure,
                                  copy relations, SAT and stage statistics)
    ctl.run_info()                volatile facts for the run record: seconds per stage, SAT time
"""
from __future__ import annotations

import collections
import dataclasses
import hashlib
import time

import numpy as np

from tools.s3 import params as _params
from tools.s3.netlist import (ALL1, BBOX, CONST, FLOP, GATE, INPUT, Bdd, Miter, Sat, Sim, _full, _vmask,
                              eval_tt, isop, supports_of, tt_of)

# The staged BDD prover's parameters (SAT_STAGE1, BDD_PROVER, BDD_PROFILES) are tools.s3.params
# entries with their justification (moved there from this module on 2026-09-22), read as self.P.

# The clock-gate fold's and the mode selector's thresholds (CLOCK_GATE_FOLD, CLOCK_GATE_FALLBACK,
# MODE_SELECT, MODE_SELECT_SHARE, MODE_SELECT_MIN_FLOPS, MODE_SELECT_MARGIN, MODE_SELECT_MAX_CANDS,
# MODE_SELECT_SCREEN, MODE_SELECT_MIN_LIVE) are tools.s3.params entries with their justification
# (moved there from this module on 2026-09-22; changes.jsonl C48, C49), read as self.P like the rest.
# The fold's support bound is params.HARNESS_CLOCK_SUPPORT, the mirror of verify.CLOCK_SUPPORT: the
# recognizer folds exactly the gates the harness folds and refuses exactly the same ones.

_Z = np.uint64(0)
_MUX = tt_of(lambda x: x[1] if x[0] else x[2], 3)   # x0 ? x1 : x2
_AND2 = 0b1000


def _pc(x):
    return int(np.bitwise_count(x).sum())


def _pc_rows(X):
    return np.bitwise_count(X).sum(axis=1, dtype=np.int64)


def _count_rows(V, sigs, W, mask, chunk=2048):
    """Popcounts of V[sigs, :W] & mask, in chunks (no whole-matrix scratch arrays: as W grows between
    calls, freed arrays of the previous size would stay resident)."""
    out = np.zeros(len(sigs), np.int64)
    for c0 in range(0, len(sigs), chunk):
        out[c0:c0 + chunk] = _pc_rows(V[sigs[c0:c0 + chunk], :W] & mask)
    return out


def _biased(rng, b, shape):
    """uint64 words whose bits are 1 with probability b (b rounded to 1/256)."""
    m = int(round(b * 256))
    if m <= 0:
        return np.zeros(shape, np.uint64)
    if m >= 256:
        return np.full(shape, ALL1)
    t0 = (m & -m).bit_length() - 1
    x = rng.integers(0, 2 ** 64, size=shape, dtype=np.uint64)
    for t in range(t0 + 1, 8):  # binary expansion of m/256 from its lowest set digit
        r = rng.integers(0, 2 ** 64, size=shape, dtype=np.uint64)
        x = (x | r) if (m >> t) & 1 else (x & r)
    return x


def _gather(rows, lanes):
    """Columns (lanes) of bit rows (m, w) uint64 -> (m, ceil(len/64)) uint64."""
    m = rows.shape[0]
    bits = np.unpackbits(np.ascontiguousarray(rows).view(np.uint8).reshape(m, -1), axis=1, bitorder="little")
    sel = bits[:, np.asarray(lanes, np.int64)]
    pad = (-sel.shape[1]) % 64
    if pad:
        sel = np.concatenate([sel, np.zeros((m, pad), np.uint8)], axis=1)
    return np.ascontiguousarray(np.packbits(sel, axis=1, bitorder="little")).view(np.uint64).reshape(m, -1)


def _lane_mask(lanes, words):
    out = np.zeros(words, np.uint64)
    for k in lanes:
        out[k >> 6] |= np.uint64(1) << np.uint64(k & 63)
    return out


def _bit(x, k):
    return int((int(x[k >> 6]) >> (k & 63)) & 1)


def _first_lane(x):
    nz = np.flatnonzero(x)
    if len(nz) == 0:
        return None
    w = int(nz[0])
    v = int(x[w])
    return 64 * w + ((v & -v).bit_length() - 1)


def _h(*parts):
    return int.from_bytes(hashlib.blake2b(repr(parts).encode(), digest_size=8).digest(), "little")


def _apply_tt(tt, k, ins, full):
    """Gate table tt over k inputs applied to input tables (ints over a common variable set)."""
    out = 0
    for cube in isop(tt, k):
        t = full
        for v, b in cube:
            t &= ins[v] if b else full ^ ins[v]
        out |= t
    return out


def _cone_table(g, lit, cut):
    """The table of `lit` over the signals `cut` (variable i = cut[i]); KeyError when the cone
    reaches a source outside the cut."""
    m = len(cut)
    full = _full(m)
    val = {s: _vmask(i, m) for i, s in enumerate(cut)}
    val[0] = 0
    stack = [lit >> 1]
    while stack:
        s = stack[-1]
        if s in val:
            stack.pop()
            continue
        if g.kind[s] != GATE:
            raise KeyError(s)
        pend = [f for f in g.fanin[s] if f not in val]
        if pend:
            stack.extend(pend)
            continue
        val[s] = _apply_tt(g.tt[s], len(g.fanin[s]), [val[f] for f in g.fanin[s]], full)
        stack.pop()
    t = val[lit >> 1]
    return t ^ full if lit & 1 else t


def _refresh(g):
    """After signals were added to a GateGraph outside its constructor: the signal count, the gate
    levels (this graph is simulated, unlike the harness's) and the cached per-signal views (the
    harness does the same in tools.s3.verify's _refresh)."""
    n0, g.n = len(g.level), len(g.kind)
    for k in ("fanout", "sources", "_supp", "_srcidx"):
        g.__dict__.pop(k, None)
    if g.n > n0:
        lvl = np.zeros(g.n, np.int32)
        lvl[:n0] = g.level
        for s in range(n0, g.n):
            if g.kind[s] == GATE:
                lvl[s] = 1 + max(int(lvl[f]) for f in g.fanin[s])
        g.level = lvl


def _clock_logic(g, L, known, max_support):
    """((root, edge), enable literal) for a clock that is logic over one clock root, or a reason
    string. The harness's flop model (schema "Flop model", tools.s3.verify's _clock_logic):
    the gate must be unate in its root; positive unate -> the flop fires on the root's rising edge
    with enable c|r=1 & ~c|r=0, negative unate -> the falling edge with c|r=0 & ~c|r=1. `known` are
    the clock roots other flops (or ICG cells) already name; when exactly one of them is in the
    gate's support it is the root, else the unique INPUT / BBOX source is. The reason string
    "clock logic without one clock root" is returned with the candidates appended, so the caller
    can fall back on them."""
    idx = g._source_index()
    sup = [s for s in g.sources if g.supp_bits(L >> 1) >> idx[s] & 1]
    cands = [s for s in sup if s in known]
    if len(cands) != 1:
        cands = [s for s in sup if g.kind[s] in (INPUT, BBOX)]
    if len(cands) != 1:
        return ("clock logic without one clock root", tuple(sorted(cands)))
    return _clock_enable(g, L, cands[0], max_support)


def _clock_enable(g, L, r, max_support):
    """The (root, edge), enable of clock literal L with root r, or a reason."""
    idx = g._source_index()
    sup = [s for s in g.sources if g.supp_bits(L >> 1) >> idx[s] & 1]
    if r not in sup:
        return "clock logic not over its root"
    if len(sup) > max_support:
        return f"clock logic over more than {max_support} sources"
    try:
        t = _cone_table(g, L, sup)
    except KeyError:
        return "clock logic not over sources"
    i = sup.index(r)
    m = len(sup)
    mk_ = _vmask(i, m)
    full = _full(m)
    c1 = t & mk_
    c1 |= c1 >> (1 << i)
    c0 = t & (full ^ mk_)
    c0 |= c0 << (1 << i)
    pos, neg = c0 & ~c1 & full == 0, c1 & ~c0 & full == 0
    if pos and neg:
        return "the clock does not depend on its root"
    if not (pos or neg):
        return "clock logic binate in its root"
    C1, C0 = g.cofactor(L, r, 1), g.cofactor(L, r, 0)
    if pos:
        return ((r, 0), g.mk(_AND2, [C1, C0 ^ 1]))
    return ((r, 1), g.mk(_AND2, [C0, C1 ^ 1]))


def _tarjan(n, succ):
    """SCCs of a graph on 0..n-1 (succ: list of iterables), iterative; each SCC sorted."""
    index, low, on, stack, out = [None] * n, [0] * n, [False] * n, [], []
    counter = 0
    for root in range(n):
        if index[root] is not None:
            continue
        work = [(root, iter(succ[root]))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on[root] = True
        while work:
            v, it = work[-1]
            pushed = False
            for w in it:
                if index[w] is None:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on[w] = True
                    work.append((w, iter(succ[w])))
                    pushed = True
                    break
                if on[w]:
                    low[v] = min(low[v], index[w])
            if pushed:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on[w] = False
                    comp.append(w)
                    if w == v:
                        break
                out.append(sorted(comp))
    return out


@dataclasses.dataclass
class Reset:
    kind: str = "none"            # sync | async | none
    lit: int | None = None        # active-high literal (sync: gate or source; async: clear/preset literal)
    support: list = dataclasses.field(default_factory=list)
    forced: int = 0               # next states made known by forcing lit = 1 (everything else X)
    values: dict = dataclasses.field(default_factory=dict)      # flop index -> reset value
    inactive: list = dataclasses.field(default_factory=list)    # [{source: value}] with lit = 0
    candidates: list = dataclasses.field(default_factory=list)  # top (literal, forced, support size)
    async_lits: dict = dataclasses.field(default_factory=dict)  # flop index -> (clear, preset)
    baseline: int = 0             # next states known with nothing forced


@dataclasses.dataclass
class ControlClass:
    lit: int                      # class representative literal, active when 1
    holds: set = dataclasses.field(default_factory=set)         # flop indices: lit -> f == q
    sets: dict = dataclasses.field(default_factory=dict)        # flop index -> v: lit -> f == v
    lanes: int = 0                # live lanes where lit = 1
    confirmed: bool | None = None  # SAT-confirmed (None: not attempted or unknown)

    @property
    def n(self):
        return len(self.holds) + len(self.sets)


@dataclasses.dataclass
class Profile:
    flop: int
    reset: int | None = None      # value under the reset (sync: forced next state; async: clear 0 / preset 1)
    live: int = 0
    active: int = 0               # live lanes with f != q
    steps: list = dataclasses.field(default_factory=list)       # ordered cover: (literal, "h" | 0 | 1)
    proven: list = dataclasses.field(default_factory=list)      # per step: SAT-proven (given the earlier steps)
    holds: list = dataclasses.field(default_factory=list)       # H cover: literals (steps of kind "h")
    sets: list = dataclasses.field(default_factory=list)        # R cover: (literal, value)
    template: str = "unknown"     # const | hold | copy | copy_inv | toggle | affine | other | unknown
    arg: object = None            # const: value; copy/copy_inv: source signal; affine: ([sources], c)
    lanes: int = 0                # uncovered live lanes the template was judged on
    cases: list = dataclasses.field(default_factory=list)       # [(literal, template, arg, lanes)]
    dominant: int | None = None   # the cover literal controlling most flops
    signature: tuple = ()         # (clock root, edge, async literals, dominant)
    quiescent: bool = False       # proven: f == q whenever the reset is inactive
    template_proven: bool | None = None   # SAT: no cover step active (rho inactive) -> f == template


@dataclasses.dataclass
class CopyEdge:
    src: int                      # source signal (a flop state, input or black-box output)
    dst: int                      # flop index
    inv: int                      # 1: f_dst = ~src where cond
    cond: int                     # transparency literal (scratch graph)
    lanes: int                    # live lanes where cond = 1
    cls: int = -1                 # copy class (SAT-equal keys)
    depth: int = 0                # gate levels from f_dst down to src


class Controls:
    def __init__(self, nl, params=None):
        self.nl = nl
        self.P = _params.resolve(dict(params or {}))
        self.mode = None               # the mode selector in force: {"lit", "net", "keep", ...} or None
        self.clock_gates = {}          # flop index -> the folded logic clock gate's enable literal
        self.timings = collections.OrderedDict()
        self.stats = collections.Counter()
        self.reset = Reset()
        self.const_live = {}
        self._rep = {}
        self._members = collections.defaultdict(list)
        self.control = {}
        self.profile = []
        self.duplicates = []
        self.copy_edges = []
        self.copy_classes = {}
        self.copy_groups = []
        self.uncond_class = None
        self._class_cond = {}
        self._dcache = {}
        self._trans = {}
        self._proven = set()           # (literal, flop, "h" | 0 | 1): SAT-proven control relations
        self._refuted = set()
        self.quiescent = set()
        self.bdd = None                # netlist.Bdd on the scratch graph, made on first use (_sat)

    # ------------------------------------------------------------------ graph
    def build(self):
        t0 = time.perf_counter()
        from tools.s3.netlist import GateGraph
        g = self.g = GateGraph(self.nl)
        self._fold_clock_gates(g)     # logic clock gates as enables: the harness's flop model
        self.n = g.n
        self.flops = g.flops
        self.F = len(g.flops)
        self.S = g.scratch()
        self.sat = Sat(self.S)
        self.sim = Sim(g, 1)
        self.labels = g.wl_labels(self.P["WL_ROUNDS"])
        src = list(g.sources)
        self.src_order = np.array(sorted(src, key=lambda s: (self.labels[s], s)), np.int64)
        self.supp = g.supports()
        self.supp_src = supports_of(self.supp, g.sources)
        self.supp_flops = [sorted(g.q2flop[s] for s in ss if s in g.q2flop) for ss in self.supp_src]
        self.cone4 = []                  # literal-class candidates: the depth-CLASS_DEPTH cone of f_i
        for f in g.flops:
            gates, leaves = g.cone([f.ns], self.P["CLASS_DEPTH"])
            self.cone4.append(sorted((gates | leaves) - {0}))
        if self.P["CASE_DEPTH"] == self.P["CLASS_DEPTH"]:
            self.cone_case = self.cone4
        else:
            self.cone_case = []
            for f in g.flops:
                gates, leaves = g.cone([f.ns], self.P["CASE_DEPTH"])
                self.cone_case.append(sorted((gates | leaves) - {0}))
        self._net = g.net_of_lit()
        self.timings["build"] = time.perf_counter() - t0

    def f(self, i):
        return self.flops[i].ns

    def qlit(self, i):
        return 2 * self.flops[i].q

    # ------------------------------------------------------------------ clock model
    def _fold_clock_gates(self, g):
        """Fold logic on a flop's clock path into its effective next state, exactly as the harness's
        flop model does (schema "Flop model", tools.s3.verify): a flop whose clock is a gate
        over a clock root r fires on r's edge when the gate is unate in r, with enable
        e = c|r=1 & ~c|r=0 (rising) or c|r=0 & ~c|r=1 (falling), so the effective next state is
        e ? ns : q and the flop's clock root and edge become r's. An ICG cell's enable is already in
        Flop.ns (the netlist module builds it); this is the same rule for ordinary logic (gclk = clk & en),
        which the netlist module leaves on the clock path. Without it the recognizer sees a flop that
        updates every clock while the harness sees an enabled one, and every correct claim on such a
        design is refuted (review[1] blocker 1).

        Clock logic the harness refuses (binate in its root, wider than HARNESS_CLOCK_SUPPORT, not over
        sources) is left alone: the recognizer then models what the netlist module modelled and the harness
        reports the structure as an unsupported clock either way. When no flop names the clock root
        (every flop of the design is gated), the harness refuses too; CLOCK_GATE_FALLBACK still folds
        the gate, taking the candidate source that most flops' clock cones share (ties by structural
        label, so the choice is a function of the netlist), and meta marks the run ambiguous: the
        structure is then reported, and verifies once the harness names a root the same way."""
        todo = [(i, f) for i, f in enumerate(g.flops) if g.kind[f.clk_root] == GATE]
        self.stats["clock_gate_logic_flops"] = len(todo)
        if not todo or not self.P["CLOCK_GATE_FOLD"]:
            return
        known = {f.clk_root for f in g.flops if g.kind[f.clk_root] in (INPUT, BBOX)}
        known |= {ck >> 1 for ck, _en in g.icg.values() if g.kind[ck >> 1] in (INPUT, BBOX)}
        cap = self.P["HARNESS_CLOCK_SUPPORT"]
        got, pend = {}, []
        for i, f in todo:
            r = _clock_logic(g, 2 * f.clk_root + f.clk_inv, known, cap)
            if isinstance(r, tuple) and isinstance(r[0], str):
                pend.append((i, f, r[1]))
            elif isinstance(r, str):
                self.stats[f"clock_gate_refused_{r[:40]}"] += 1
            else:
                got[i] = r
        if pend and self.P["CLOCK_GATE_FALLBACK"]:
            cnt = collections.Counter()
            for _i, _f, cands in pend:
                cnt.update(cands)
            lab = g.wl_labels(self.P["WL_ROUNDS"]) if cnt else []   # pre-fold labels: a canonical tie-break
            for i, f, cands in pend:
                if not cands:
                    self.stats["clock_gate_refused_no_root_candidate"] += 1
                    continue
                r = _clock_enable(g, 2 * f.clk_root + f.clk_inv,
                                  min(cands, key=lambda s: (-cnt[s], lab[s], s)), cap)
                if isinstance(r, str):
                    self.stats[f"clock_gate_refused_{r[:40]}"] += 1
                else:
                    got[i] = r
                    self.stats["clock_gate_root_ambiguous"] += 1
        for i, ((root, inv), en) in sorted(got.items()):
            f = g.flops[i]
            f.ns = g.mk(_MUX, [en, f.ns, 2 * f.q])
            f.gate_en = en if f.gate_en == 1 else g.mk(_AND2, [f.gate_en, en])
            f.clk_root, f.clk_inv = root, inv
            self.clock_gates[i] = en
        if got:
            _refresh(g)
        self.stats["clock_gate_folded"] = len(got)

    # ------------------------------------------------------------------ mode selector
    def _find_mode(self):
        """A two-input mux on D whose select is a global, high-fanout literal is a mode selector
        (a DFT scan enable is the standard case): under one polarity of the select most flops copy
        a source (the scan chain), under the other they do their own work. The lanes are then
        restricted to the functional cofactor, so every simulation-driven search (the counter's
        functional test above all) sees one mode instead of a mixture of two; the SAT proofs of
        every recognizer still run on the raw next state, so their conditions grow to include the
        select and the test mode comes back as the counter's opaque load case (schema: "load: an
        opaque case, allowed, never defining"). Without this, a scan-inserted counter produces no
        structure at all (review[1] blocker 2).

        A candidate select s (a primary input or black-box output, never the reset) must lie in
        >= MODE_SELECT_SHARE of the flops' next-state supports. For each flop, A = f_i|s=1 and
        B = f_i|s=0: the flop is *muxed* only when neither cofactor is its own state (an enable and
        a clock gate hold in one branch, so they are not modes) and the two differ. A polarity
        *chains* when the cofactor is ANOTHER FLOP's state -- a scan chain moves the design's own
        state through itself, which is what separates it from a parallel load (whose branch is a
        primary input: measured on the corpus, where `ld ? pdata : ...` otherwise looked like a mode
        and cost sr_pload_d8_ar its load case) -- and the chaining flops must take distinct sources
        (a chain is injective; a broadcast is not). s is a mode selector when >= MODE_SELECT_SHARE
        of the flops are muxed and chain under one polarity while the other polarity chains at most
        MODE_SELECT_MARGIN of that (a ring counter chains under both and is not a mode; a
        synchronous reset's branch is a constant, not a chain)."""
        P, g, S = self.P, self.g, self.S
        F = self.F
        if F < P["MODE_SELECT_MIN_FLOPS"] or not P["MODE_SELECT"]:
            return
        need = max(P["MODE_SELECT_MIN_FLOPS"], int(-(-P["MODE_SELECT_SHARE"] * F // 1)))
        cnt = collections.Counter()
        for i in range(F):
            for s in self.supp_src[i]:
                if g.kind[s] in (INPUT, BBOX):
                    cnt[s] += 1
        skip = set(self.reset.support or ()) | ({self.reset.lit >> 1} if self.reset.lit is not None else set())
        cands = [s for s, c in cnt.items() if c >= need and s not in skip]
        cands.sort(key=lambda s: (-cnt[s], self.labels[s], s))
        best = None
        for s in cands[:P["MODE_SELECT_MAX_CANDS"]]:
            r = self._mode_of(s, need)
            self.stats["mode_candidates"] += 1
            if r is not None and (best is None or r["chained"] > best["chained"]):
                best = r
        if best is None:
            return
        self.mode = best
        self.stats["mode_selector"] = 1
        self.stats["mode_muxed_flops"] = best["muxed"]

    def _mode_of(self, s, need):
        """The mode selector reading of source `s`, or None (see _find_mode)."""
        P, g, S = self.P, self.g, self.S
        memo = ({}, {})
        muxed = 0
        chain = ({}, {})            # polarity -> {flop index: the other flop's state it copies}
        const = [0, 0]              # polarity -> flops whose next state is a constant there
        seen = 0
        for i in range(self.F):
            if s not in self.supp_src[i]:
                continue
            seen += 1
            q = 2 * self.flops[i].q
            cof = [S.cofactor(self.flops[i].ns, s, v, memo[v]) for v in (0, 1)]
            if cof[0] != cof[1] and cof[0] != q and cof[1] != q:
                muxed += 1
                for v in (0, 1):
                    t = cof[v] >> 1
                    if t == 0:
                        const[v] += 1
                    elif t < self.n and g.kind[t] == FLOP and t != self.flops[i].q:
                        chain[v][i] = t
            if seen >= P["MODE_SELECT_SCREEN"] and muxed * 2 < seen:
                self.stats["mode_screened_out"] += 1
                return None
        if muxed < need:
            return None
        n = [len(chain[v]) if len(set(chain[v].values())) == len(chain[v]) else 0 for v in (0, 1)]
        v = 1 if n[1] >= n[0] else 0
        if n[v] < need or n[1 - v] > P["MODE_SELECT_MARGIN"] * n[v]:
            return None
        if const[1 - v] >= need:     # the kept branch loads a constant into most flops: that is a
            self.stats["mode_kept_branch_constant"] += 1   # reset or a clear, not a functional mode
            return None
        net = self._net.get(2 * s)
        return {"sig": int(s), "test": int(v), "keep": int(1 - v), "muxed": int(muxed),
                "chained": int(n[v]), "chained_other": int(n[1 - v]),
                "net": int(net[0]) if net is not None else None}

    # ------------------------------------------------------------------ lanes
    def _alloc(self):
        cap = -(-self.P["POOL_CAP"] // 64)
        self.cap = cap
        self.V = np.zeros((self.n, cap), np.uint64)
        self.live_all = np.zeros(cap, np.uint64)
        self.W = 0
        self.origin = []
        self.rng = np.random.default_rng(_h("pool", self.P["POOL_SALT"]) & 0xFFFFFFFF)

    @property
    def lanes(self):
        return 64 * self.W

    @property
    def live(self):
        return self.live_all[:self.W]

    def _random_sources(self, w0, w1):
        """Biased random values for every source over words w0..w1 (rows by structural label)."""
        nw = w1 - w0
        ns = len(self.src_order)
        B = self.P["BIASES"]
        code = self.rng.integers(0, len(B), size=(ns, nw))
        vals = np.zeros((ns, nw), np.uint64)
        for k, b in enumerate(B):
            x = _biased(self.rng, b, (ns, nw))
            vals = np.where(code == k, x, vals)
        self.V[self.src_order, w0:w1] = vals
        self.V[0, w0:w1] = 0

    def _eval_words(self, w0, w1):
        self.sim.eval(self.V[:, w0:w1])
        if self.reset.kind == "sync":
            rho = self.V[self.reset.lit >> 1, w0:w1]
            self.live_all[w0:w1] = rho if self.reset.lit & 1 else ~rho
        else:
            self.live_all[w0:w1] = ALL1
        if self.mode is not None:     # the functional cofactor of the mode selector (see _find_mode)
            m = self.V[self.mode["sig"], w0:w1]
            self.live_all[w0:w1] &= m if self.mode["keep"] else ~m

    def _pin(self, w0, w1, free_every=0):
        """Make rho inactive in words w0..w1 (except 1 lane in `free_every`, when given) by
        overwriting its support with inactive assignments where it is active."""
        if self.reset.kind != "sync" or not self.reset.inactive:
            return
        nw = w1 - w0
        pinned = np.full(nw, ALL1)
        if free_every:
            free = _lane_mask(range(free_every - 1, 64 * nw, free_every), nw)
            pinned &= ~free
        self.sim_rho.eval(self.V[:, w0:w1])
        rho = self.V[self.reset.lit >> 1, w0:w1]
        act = (rho if not self.reset.lit & 1 else ~rho) & pinned
        if not act.any():
            return
        K = len(self.reset.inactive)
        for k, a in enumerate(self.reset.inactive):
            m = act & _lane_mask(range(k, 64 * nw, K), nw) if K > 1 else act
            for s, v in a.items():
                row = self.V[s, w0:w1]
                self.V[s, w0:w1] = (row & ~m) | (m if v else _Z)

    def _push_words(self, nw, origin):
        if self.W + nw > self.cap:
            self.stats["lanes_refused"] += 64 * nw
            return None
        w0 = self.W
        self.W += nw
        self.origin += [origin] * nw
        self._dcache.clear()
        return w0

    def add_lanes(self, assigns, origin="witness", fixed_rows=None):
        """Add lanes: assigns = [(assignment {source: value}, n_lanes)]; each lane copies its
        assignment, every other source is random (biased), rho is pinned inactive. Returns the
        number of lanes added (0 when the pool cap is reached)."""
        lanes = []
        for a, k in assigns:
            lanes += [a] * k
        if not lanes:
            return 0
        nw = -(-len(lanes) // 64)
        i = 0
        while len(lanes) < 64 * nw:      # fill the last word by cycling the assignments
            lanes.append(lanes[i])
            i += 1
        w0 = self._push_words(nw, origin)
        if w0 is None:
            return 0
        w1 = w0 + nw
        self._random_sources(w0, w1)
        by_a = collections.defaultdict(list)
        for k, a in enumerate(lanes):
            by_a[id(a)].append(k)
        objs = {id(a): a for a in lanes}
        for key, ks in by_a.items():
            m = _lane_mask(ks, nw)
            for s, v in objs[key].items():
                row = self.V[s, w0:w1]
                self.V[s, w0:w1] = (row & ~m) | (m if v else _Z)
        self._pin(w0, w1)
        self._eval_words(w0, w1)
        self.stats[f"lanes_{origin}"] += 64 * nw
        return 64 * nw

    def add_rows(self, rows, origin):
        """Add lanes given as source rows in src_order order (m, nw); rho pinned; evaluated."""
        nw = rows.shape[1]
        w0 = self._push_words(nw, origin)
        if w0 is None:
            return 0
        self.V[self.src_order, w0:w0 + nw] = rows
        self.V[0, w0:w0 + nw] = 0
        self._pin(w0, w0 + nw)
        self._eval_words(w0, w0 + nw)
        self.stats[f"lanes_{origin}"] += 64 * nw
        return 64 * nw

    def origin_counts(self):
        return dict(collections.Counter(o for o in self.origin for _ in range(64)))

    # ------------------------------------------------------------------ values
    def value(self, lit, w0=0, w1=None):
        """Lane values of a literal (base or derived) over words w0..w1 (default: all in use)."""
        w1 = self.W if w1 is None else w1
        s = lit >> 1
        if s < self.n:
            row = self.V[s, w0:w1]
        else:
            row = self._derived([s], w0, w1)[s]
        return ~row if lit & 1 else row

    def _derived(self, sigs, w0, w1, memo=None):
        """Values of derived (scratch) signals over words w0..w1; memo shared across calls."""
        S = self.S
        memo = {} if memo is None else memo
        full = (w0 == 0 and w1 == self.W)
        for s0 in sigs:
            if s0 in memo:
                continue
            if full and s0 in self._dcache:
                memo[s0] = self._dcache[s0]
                continue
            stack = [s0]
            while stack:
                s = stack[-1]
                if s in memo:
                    stack.pop()
                    continue
                pend = [x for x in S.fanin[s] if x >= self.n and x not in memo]
                if pend:
                    stack.extend(pend)
                    continue
                rows = [memo[x] if x >= self.n else self.V[x, w0:w1] for x in S.fanin[s]]
                memo[s] = eval_tt(S.tt[s], len(rows), rows)
                stack.pop()
        return memo

    def keep(self, lit):
        """Cache a derived literal's full-width values (cleared whenever lanes are added)."""
        s = lit >> 1
        if s >= self.n and s not in self._dcache:
            self._dcache[s] = self._derived([s], 0, self.W)[s]

    def count(self, lit, mask=None):
        m = self.live if mask is None else mask
        return _pc(self.value(lit) & m)

    def active(self, i):
        f, q = self.value(self.f(i)), self.value(self.qlit(i))
        return (f ^ q) & self.live

    def _activity(self):
        ns = np.array([f.ns for f in self.flops], np.int64)
        F = Sim.lits(self.V[:, :self.W], ns)
        Q = self.V[self.g.q, :self.W]
        self.active_count = _pc_rows((F ^ Q) & self.live)
        return self.active_count

    # ------------------------------------------------------------------ SAT
    def assume(self):
        return [self.reset.lit ^ 1] if self.reset.kind == "sync" else []

    def _budget(self):
        if self.sat.stats["calls"] >= self.P["SAT_CALLS_MAX"]:
            self.stats["sat_skipped"] += 1
            return False
        return True

    def _sat(self, lits, tt, assume, limit, extra=(), need_cex=True, stage=True):
        """Sat.check in two stages (SAT_STAGE1 conflicts, then BDDs, then SAT with the full limit;
        see tools.s3.params). Counted as one query in sat.stats (the SAT_CALLS_MAX budget
        counts queries). Blocking clauses (extra) go to SAT alone. need_cex=False: a relation the
        BDDs refute is answered (False, None) without the SAT model."""
        first = self.P["SAT_STAGE1"]
        if extra or not stage or not self.P["BDD_PROVER"] or not first or first >= limit:
            return self.sat.check(lits, tt, assume, limit=limit, extra=extra)
        ok, cex = self.sat.check(lits, tt, assume, limit=first)
        if ok is not None:
            return ok, cex
        st = self.sat.stats
        st["calls"] -= 1
        st["unknown"] -= 1
        if not st["unknown"]:
            del st["unknown"]
        self.stats["sat_stage2"] += 1
        if self.bdd is None:
            self.bdd = Bdd(self.S)
        t0 = time.perf_counter()
        r = self.bdd.holds(lits, tt, assume)
        self.stats["bdd_s"] = self.stats.get("bdd_s", 0.0) + time.perf_counter() - t0
        if r is True:
            self.stats["bdd_proved"] += 1
            st["calls"] += 1
            return True, None
        self.stats["bdd_refuted" if r is False else "bdd_undecided"] += 1
        if r is False and not need_cex:
            st["calls"] += 1
            return False, None
        return self.sat.check(lits, tt, assume, limit=limit, extra=extra)

    def check(self, lits, tt, extra=(), limit=None, bdd=False):
        """Sat.check under ~rho; bdd=True: staged through the BDD prover (see _sat)."""
        if not self._budget():
            return None, None
        return self._sat(lits, tt, self.assume(), limit or self.P["SAT_LIMIT"], extra, stage=bdd)

    def witness(self, lit, extra=(), limit=None, seed=None):
        """An assignment of lit's support (and rho's) with lit = 1 and rho inactive."""
        if not self._budget():
            return "unknown", None
        ok, cex = self.sat.check([lit], 0b01, self.assume(), limit=limit or self.P["SAT_LIMIT_WITNESS"],
                                 extra=extra, seed=seed)
        self.stats["witness_queries"] += 1
        if ok is None:
            return "unknown", None
        if ok:
            return "unsat", None
        return "sat", cex

    def witness_lanes(self, lit, lanes=None, origin="literal"):
        st, a = self.witness(lit)
        if st == "sat":
            self.add_lanes([(a, lanes or self.P["WITNESS_LANES"])], origin)
        return st

    def equal(self, a, b, limit=None, bdd=False):
        """a == b under ~rho; bdd=True: staged through the BDD prover (for internal facts only)."""
        if not self._budget():
            return None
        ok, _cex = self._sat([a, b], 0b1001, self.assume(), limit or self.P["SAT_LIMIT"], need_cex=False, stage=bdd)
        return ok

    # ------------------------------------------------------------------ reset
    def find_reset(self):
        """Ternary forcing: every gate literal and source forced to each value with everything
        else X; the reset is the literal making the most next states known (support pinned)."""
        t0 = time.perf_counter()
        g, P = self.g, self.P
        n = self.n
        cands = [s for s in range(1, n) if g.kind[s] != CONST]
        items = [None] + [(s, v) for s in cands for v in (0, 1)]    # lane 0 forces nothing
        ns = np.array([f.ns for f in self.flops], np.int64)
        per = 64 * P["RESET_CHUNK_WORDS"]
        counts = np.zeros(len(items), np.int64)
        best_vals = None
        for c0 in range(0, len(items), per):
            part = items[c0:c0 + per]
            nw = -(-len(part) // 64)
            V0 = np.full((n, nw), ALL1)
            V1 = np.full((n, nw), ALL1)
            V1[0] = 0
            fsig, frows = {}, []
            for k, it in enumerate(part):
                if it is None:
                    continue
                s, v = it
                w, b = k >> 6, np.uint64(1) << np.uint64(k & 63)
                if g.kind[s] == GATE:
                    r = fsig.get(s)
                    if r is None:
                        r = fsig[s] = len(frows)
                        frows.append([np.zeros(nw, np.uint64), np.zeros(nw, np.uint64)])
                    frows[r][v][w] |= b
                else:
                    (V1 if v == 0 else V0)[s, w] &= ~b
            sig_arr = np.array(list(fsig), np.int64)
            F0 = np.array([frows[fsig[s]][0] for s in fsig], np.uint64).reshape(len(fsig), nw)
            F1 = np.array([frows[fsig[s]][1] for s in fsig], np.uint64).reshape(len(fsig), nw)
            self.sim.eval3(V0, V1, force=(sig_arr, F0, F1))
            n0, n1 = Sim.lits3(V0, V1, ns)
            known = n0 ^ n1
            bits = np.unpackbits(known.view(np.uint8), axis=1, bitorder="little")[:, :len(part)]
            counts[c0:c0 + len(part)] = bits.sum(axis=0)
        base = int(counts[0])
        counts = counts - base
        order = sorted(range(1, len(items)), key=lambda k: -counts[k])
        top = int(counts[order[0]]) if order else 0
        near = [k for k in order if counts[k] >= P["RESET_NEAR"] * top and counts[k] > 0]
        supsize = lambda s: bin(g.supp_bits(s)).count("1")  # noqa: E731
        near.sort(key=lambda k: (-supsize(items[k][0]), -counts[k], self.labels[items[k][0]], items[k][0]))
        R = self.reset
        R.baseline = base
        R.candidates = [(2 * items[k][0] + (1 - items[k][1]), int(counts[k]), supsize(items[k][0])) for k in order[:8]]
        for i, f in enumerate(self.flops):
            if f.clear or f.preset:
                R.async_lits[i] = (f.clear, f.preset)
        if near and top >= P["RESET_SYNC_FRAC"] * self.F:
            s, v = items[near[0]]
            R.kind, R.lit, R.forced = "sync", 2 * s + (1 - v), int(counts[near[0]])
            # the forced values, from one more pass with only rho forced
            V0 = np.full((n, 1), ALL1)
            V1 = np.full((n, 1), ALL1)
            V1[0] = 0
            if g.kind[s] == GATE:
                F0 = np.array([[ALL1 if v == 0 else _Z]], np.uint64)
                F1 = np.array([[ALL1 if v == 1 else _Z]], np.uint64)
                self.sim.eval3(V0, V1, force=(np.array([s], np.int64), F0, F1))
            else:
                (V1 if v == 0 else V0)[s] = 0
                self.sim.eval3(V0, V1)
            n0, n1 = Sim.lits3(V0, V1, ns)
            for i in range(self.F):
                a0, a1 = int(n0[i, 0]) & 1, int(n1[i, 0]) & 1
                if a0 != a1:
                    R.values[i] = a1
            R.support = supports_of([g.supp_bits(s)], g.sources)[0]
            # inactive assignments of the support
            blocks = []
            for k in range(P["RESET_WITNESSES"]):
                ok, cex = self.sat.check([R.lit ^ 1], 0b01, limit=P["SAT_LIMIT_WITNESS"],
                                         extra=[[(2 * t) | b[t] for t in b] for b in blocks] if blocks else ())
                if ok is not False:
                    break
                a = {t: cex.get(t, 0) for t in R.support}
                R.inactive.append(a)
                blocks.append(a)
            if not R.inactive:          # rho cannot be inactive: not a reset
                R.kind, R.lit = "none", None
        if R.kind != "sync" and R.async_lits:
            c = collections.Counter(x for cl, pr in R.async_lits.values() for x in (cl, pr) if x)
            lit, _cnt = min(c.items(), key=lambda kv: (-kv[1], self.labels[kv[0] >> 1], kv[0]))
            R.kind, R.lit = "async", lit
            R.support = supports_of([g.supp_bits(lit >> 1)], g.sources)[0]
            for i, (cl, pr) in R.async_lits.items():
                if cl == lit:
                    R.values[i] = 0
                elif pr == lit:
                    R.values[i] = 1
            R.forced = len(R.values)
        if R.kind == "sync":
            cone, _l = g.cone([R.lit])
            self.sim_rho = Sim(g, 1, gates=cone)
        self.timings["reset"] = time.perf_counter() - t0
        return R

    # ------------------------------------------------------------------ pool
    def make_pool(self):
        t0 = time.perf_counter()
        self._find_mode()     # after find_reset: the reset's own literal is never a mode selector
        self._alloc()
        nw = -(-self.P["POOL_LANES"] // 64)
        w0 = self._push_words(nw, "pool")
        self._random_sources(w0, w0 + nw)
        self._pin(w0, w0 + nw, free_every=self.P["RESET_FREE_EVERY"])
        self._eval_words(w0, w0 + nw)
        if self.mode is not None and _pc(self.live) < self.P["MODE_SELECT_MIN_LIVE"]:
            self.stats["mode_selector_dropped_few_lanes"] = _pc(self.live)
            self.stats["mode_selector"] = 0
            self.mode = None
            self._eval_words(w0, w0 + nw)
        self.stats["lanes_pool"] += 64 * nw
        self._activity()
        self.stats["pool_live_lanes"] = _pc(self.live)
        self.timings["pool"] = time.perf_counter() - t0

    # ------------------------------------------------------------------ support graph
    def support_graph(self):
        t0 = time.perf_counter()
        succ = [[] for _ in range(self.F)]
        for i, js in enumerate(self.supp_flops):
            for j in js:
                if j != i:
                    succ[j].append(i)
        self.state_succ = succ
        comps = _tarjan(self.F, succ)
        self.scc_of = [0] * self.F
        for k, c in enumerate(comps):
            for i in c:
                self.scc_of[i] = k
        self.sccs = sorted((c for c in comps if len(c) >= 2), key=lambda c: (-len(c), min(self.labels[self.flops[i].q] for i in c)))
        self.timings["support_graph"] = time.perf_counter() - t0

    # ------------------------------------------------------------------ rare flops (case witnesses)
    def _word_lit(self, word):
        S = self.S
        acc = 0
        for i in word:
            acc = S.lit_or(acc, S.lit_xor(self.f(i), self.qlit(i)))
        return acc

    def case_witnesses(self, word, extra_lits=(), max_witnesses=None, want=None, origin="case", blocks=None):
        """SAT witnesses of "the word does not hold" (some f_k != q_k, rho inactive, every literal in
        extra_lits = 1), each blocked after use on its critical sources (those whose flip stops
        the word), copied onto them with the rest random; only lanes where the word is active are
        kept. Stops at `want` active lanes (default N_MIN), `max_witnesses` (default
        CASE_WITNESSES) or UNSAT. Returns {"witnesses", "lanes", "status", "blocks"}; pass the
        returned blocks back in to continue an earlier enumeration."""
        P = self.P
        want = P["N_MIN"] if want is None else want
        max_witnesses = P["CASE_WITNESSES"] if max_witnesses is None else max_witnesses
        wl = self._word_lit(word)
        for x in extra_lits:
            wl = self.S.lit_and(wl, x)
        blocks = list(blocks or [])
        out = {"witnesses": 0, "lanes": 0, "status": "open", "blocks": blocks}
        have = _pc(self.value(wl) & self.live)
        k = 0
        while have < want and k < max_witnesses:
            st, a = self.witness(wl, extra=[[(2 * t) | b[t] for t in b] for b in blocks], seed=k)
            k += 1
            if st != "sat":
                out["status"] = st
                break
            lanes, crit = self._case_lanes([(wl, a)], origin)
            out["witnesses"] += 1
            out["lanes"] += lanes
            c = crit[0]
            blocks.append({t: a[t] for t in c} if c else dict(a))
            have = _pc(self.value(wl) & self.live)
        out["active_lanes"] = have
        return out

    def _case_lanes(self, items, origin):
        """items: [(word literal, witness)]. Finds each witness's critical sources by flipping a single
        source per lane, then tries CASE_TRIES lanes per witness that copy the critical sources
        (and rho's support) with the rest random and keeps the active ones (<= WITNESS_LANES, the
        exact witness always). Returns (lanes added, [critical source lists])."""
        P = self.P
        if not items:
            return 0, []
        src_pos = {int(s): r for r, s in enumerate(self.src_order)}
        # 1. flip lanes
        layout = []
        for wl, a in items:
            srcs = sorted(a, key=lambda s: (self.labels[s], s))
            layout.append(srcs)
        total = sum(1 + len(s) for s in layout)
        nw = -(-total // 64)
        tmp = np.zeros((self.n, nw), np.uint64)
        tmp[self.src_order] = self._scratch_random(nw)
        tmp[0] = 0
        lane = 0
        spans = []
        for (wl, a), srcs in zip(items, layout):
            span = list(range(lane, lane + 1 + len(srcs)))
            m = _lane_mask(span, nw)
            for s in srcs:
                row = tmp[s]
                tmp[s] = (row & ~m) | (m if a[s] else _Z)
            for t, s in enumerate(srcs):
                k = lane + 1 + t
                tmp[s, k >> 6] ^= np.uint64(1) << np.uint64(k & 63)
            spans.append(span)
            lane += len(span)
        self.sim.eval(tmp)
        crits = []
        for (wl, a), srcs, span in zip(items, layout, spans):
            act = self._derived_tmp(wl, tmp)
            crit = [s for t, s in enumerate(srcs) if not _bit(act, span[0] + 1 + t)]
            if not _bit(act, span[0]):
                crit = []
            crits.append(crit)
        # 2. tries: copy critical sources (and rho's support) from the witness, the rest random
        tries = P["CASE_TRIES"]
        nw2 = -(-(tries * len(items)) // 64)
        tmp2 = np.zeros((self.n, nw2), np.uint64)
        tmp2[self.src_order] = self._scratch_random(nw2)
        tmp2[0] = 0
        keep_rows = []
        for t, ((wl, a), crit) in enumerate(zip(items, crits)):
            span = list(range(t * tries, (t + 1) * tries))
            m = _lane_mask(span, nw2)
            m0 = _lane_mask(span[:1], nw2)
            fix = set(crit) | set(self.reset.support if self.reset.kind == "sync" else ())
            for s in a:
                mm = m if s in fix else m0          # lane 0 of the span is the exact witness
                row = tmp2[s]
                tmp2[s] = (row & ~mm) | (mm if a[s] else _Z)
        self._pin_tmp(tmp2)
        self.sim.eval(tmp2)
        live2 = self._live_tmp(tmp2)
        sel = []
        for t, (wl, a) in enumerate(items):
            act = self._derived_tmp(wl, tmp2) & live2
            got = [k for k in range(t * tries, (t + 1) * tries) if _bit(act, k)]
            sel += got[:P["WITNESS_LANES"]]
        if not sel:
            return 0, crits
        rows = _gather(tmp2[self.src_order], sel)
        n = self.add_rows(rows, origin)
        return n, crits

    def _scratch_random(self, nw):
        ns = len(self.src_order)
        B = self.P["BIASES"]
        code = self.rng.integers(0, len(B), size=(ns, nw))
        vals = np.zeros((ns, nw), np.uint64)
        for k, b in enumerate(B):
            vals = np.where(code == k, _biased(self.rng, b, (ns, nw)), vals)
        return vals

    def _pin_tmp(self, tmp):
        if self.reset.kind != "sync" or not self.reset.inactive:
            return
        self.sim_rho.eval(tmp)
        rho = tmp[self.reset.lit >> 1]
        act = rho if not self.reset.lit & 1 else ~rho
        if not act.any():
            return
        nw = tmp.shape[1]
        K = len(self.reset.inactive)
        for k, a in enumerate(self.reset.inactive):
            m = act & _lane_mask(range(k, 64 * nw, K), nw) if K > 1 else act
            for s, v in a.items():
                tmp[s] = (tmp[s] & ~m) | (m if v else _Z)

    def _live_tmp(self, tmp):
        if self.reset.kind != "sync":
            return np.full(tmp.shape[1], ALL1)
        r = tmp[self.reset.lit >> 1]
        return r if self.reset.lit & 1 else ~r

    def _derived_tmp(self, lit, tmp):
        s = lit >> 1
        if s < self.n:
            r = tmp[s]
        else:
            S = self.S
            memo = {}
            stack = [s]
            while stack:
                t = stack[-1]
                if t in memo:
                    stack.pop()
                    continue
                pend = [x for x in S.fanin[t] if x >= self.n and x not in memo]
                if pend:
                    stack.extend(pend)
                    continue
                memo[t] = eval_tt(S.tt[t], len(S.fanin[t]), [memo[x] if x >= self.n else tmp[x] for x in S.fanin[t]])
                stack.pop()
            r = memo[s]
        return ~r if lit & 1 else r

    def rare_flops(self):
        """Pre-pass: flops active in fewer than N_MIN live lanes get case-conditioned witnesses,
        by word (their state-support SCC, restricted to rare flops). Flops whose word can never
        change with rho inactive are marked quiescent (proven)."""
        t0 = time.perf_counter()
        self.quiescent = set()
        self._rare_words(lambda i: ("scc", self.scc_of[i]), self.P["CASE_ROUNDS"], "case", mark_quiescent=True)
        act = self._activity()
        self.stats["rare_flops_after_prepass"] = int(sum(1 for i in range(self.F) if act[i] < self.P["N_MIN"] and i not in self.quiescent))
        self.stats["quiescent_flops"] = len(self.quiescent)
        self.timings["rare_flops"] = time.perf_counter() - t0

    def _rare_words(self, word_key, rounds, origin, mark_quiescent=False):
        """Case-conditioned witnesses for the flops active in fewer than N_MIN live lanes, grouped
        into words by word_key(flop): per round one witness of "the word does not hold" per word
        (blocked on its critical sources in later rounds), activity recounted between rounds; a
        word stops at UNSAT (with mark_quiescent and no earlier witness: its flops are proven
        quiescent), an unknown, CASE_WITNESSES witnesses, or when no rare flop is left."""
        P = self.P
        state = {}                       # word key -> (blocks, done)
        for rnd in range(rounds):
            act = self._activity()
            rare = [i for i in range(self.F) if act[i] < P["N_MIN"] and i not in self.quiescent]
            if not rare:
                break
            words = collections.defaultdict(list)
            for i in rare:
                words[word_key(i)].append(i)
            items, keys = [], []
            for key in sorted(words, key=lambda k: min((self.labels[self.flops[i].q], i) for i in words[k])):
                word = words[key]
                blocks, done = state.get(key, ([], False))
                if done or len(blocks) >= P["CASE_WITNESSES"]:
                    continue
                wl = self._word_lit(word)
                sat_st, a = self.witness(wl, extra=[[(2 * t) | b[t] for t in b] for b in blocks], seed=rnd)
                if sat_st == "unsat":
                    if mark_quiescent and not blocks:
                        self.quiescent.update(word)
                    state[key] = (blocks, True)
                    continue
                if sat_st != "sat":
                    state[key] = (blocks, True)
                    continue
                items.append((wl, a))
                keys.append(key)
            if not items:
                break
            added = 0
            for c0 in range(0, len(items), P["WITNESS_BATCH"]):
                n, crits = self._case_lanes(items[c0:c0 + P["WITNESS_BATCH"]], origin)
                added += n
                for key, (wl, a), crit in zip(keys[c0:c0 + P["WITNESS_BATCH"]], items[c0:c0 + P["WITNESS_BATCH"]], crits):
                    blocks = state.get(key, ([], False))[0]
                    state[key] = (blocks + [{t: a[t] for t in crit} if crit else dict(a)], False)
            self.stats[f"{origin}_rounds"] = rnd + 1
            if not added:
                break

    # ------------------------------------------------------------------ literal classes
    def _candidates(self):
        if getattr(self, "_cand_cache", None) is not None:
            return list(self._cand_cache)
        c = set()
        for cone in self.cone4:
            c.update(cone)
        for f in self.flops:
            c.add(f.ns >> 1)
        c.discard(0)
        self._cand_cache = sorted(c, key=lambda s: (self.labels[s], s))
        return list(self._cand_cache)

    def rare_literals(self):
        """SAT witnesses for every candidate literal with fewer than N_MIN live lanes in either
        polarity; UNSAT proves it constant while the reset is inactive."""
        t0 = time.perf_counter()
        P = self.P
        base = self._candidates()
        inb = set(base)
        cand = np.array(base + [int(s) for s in self.g.q if int(s) not in inb], np.int64)
        done = set()
        rounds = 0
        while True:
            live = self.live
            L = _pc(live)
            n1 = _count_rows(self.V, cand, self.W, live)
            n0 = L - n1
            rare = [(int(s), 1 if a < P["N_MIN"] else 0) for s, a, b in zip(cand, n1, n0)
                    if (a < P["N_MIN"] or b < P["N_MIN"]) and int(s) not in done and int(s) not in self.const_live]
            if not rare:
                break
            batch = rare[:P["WITNESS_BATCH"]]
            assigns = []
            for s, pol in batch:
                done.add(s)
                st, a = self.witness(2 * s + (1 - pol))
                if st == "unsat":
                    self.const_live[s] = 1 - pol
                elif st == "sat":
                    assigns.append((a, P["WITNESS_LANES"]))
            rounds += 1
            if assigns and not self.add_lanes(assigns, "literal"):
                break
        self.stats["rare_literal_rounds"] = rounds
        self.stats["rare_literals_witnessed"] = len(done)
        self.stats["const_live"] = len(self.const_live)
        self.timings["rare_literals"] = time.perf_counter() - t0

    def literal_classes(self):
        """FRAIG-style sweep of the candidate literals under ~rho: bucket by live-lane signature
        (polarity normalised), confirm by SAT against the bucket's representative, union;
        counterexamples become lanes; at most FRAIG_ROUNDS rounds."""
        t0 = time.perf_counter()
        P = self.P
        cand = [s for s in self._candidates() if s not in self.const_live]
        rep = {s: 2 * s for s in cand}
        for s, v in self.const_live.items():
            rep[s] = v
        open_ = list(cand)
        refuted = set()
        for rnd in range(P["FRAIG_ROUNDS"]):
            live = self.live
            fl = _first_lane(live)
            if fl is None:
                break
            buckets = collections.defaultdict(list)
            for s in open_:
                row = self.V[s, :self.W]
                inv = _bit(row, fl)
                sig = (row ^ ALL1 if inv else row) & live
                buckets[hashlib.blake2b(sig.tobytes(), digest_size=16).digest()].append((s, inv))
            cex_assigns = []
            nxt = []
            for key, mem in buckets.items():
                if len(mem) < 2:
                    continue
                mem.sort(key=lambda x: (self.g.kind[x[0]] == GATE, int(self.g.level[x[0]]), self.labels[x[0]], x[0]))
                r, rinv = mem[0]
                for s, inv in mem[1:]:
                    if (r, s) in refuted:
                        continue
                    lit_r, lit_s = 2 * r + rinv, 2 * s + inv
                    if not self._budget():
                        break
                    ok, cex = self._sat([lit_r, lit_s], 0b1001, self.assume(), P["SAT_LIMIT"])
                    self.stats["fraig_checks"] += 1
                    if ok:
                        rep[s] = rep[r] ^ rinv ^ inv
                        self.stats["fraig_merged"] += 1
                    elif ok is False:
                        refuted.add((r, s))
                        cex_assigns.append((cex, P["WITNESS_LANES"]))
                        nxt.append(s)
                    else:
                        self.stats["fraig_unknown"] += 1
            if not cex_assigns:
                break
            if not self.add_lanes(cex_assigns, "fraig"):
                break
            open_ = [s for s in cand if rep[s] == 2 * s]
        # resolve chains (a representative merged into another in a later round)
        def find(lit):
            for _ in range(64):
                s = lit >> 1
                r = rep.get(s)
                if r is None or r == 2 * s or s == 0:
                    return lit
                lit = r ^ (lit & 1)
            return lit

        rep = {s: find(2 * s) for s in rep}
        self._rep = rep
        self._members = collections.defaultdict(list)
        for s, r in rep.items():           # member literal 2s ^ (r & 1) equals class literal r & ~1
            self._members[r & ~1].append(2 * s ^ (r & 1))
        self.stats["classes"] = sum(1 for s in cand if rep[s] == 2 * s)
        self.timings["literal_classes"] = time.perf_counter() - t0

    def rep(self, lit):
        s = lit >> 1
        r = self._rep.get(s)
        if r is None:
            return lit
        if r <= 1:
            return r ^ (lit & 1)
        return r ^ (lit & 1)

    def members(self, rep_lit):
        return list(self._members.get(rep_lit & ~1, []))

    # ------------------------------------------------------------------ control classes
    def _cand_reps(self, i, cone=None):
        """Class representatives (signals, with the class polarity folded in later) of the
        depth-CLASS_DEPTH cone literals of f_i (or of `cone`), minus constants and the classes of
        f_i and q_i."""
        own = {self.rep(self.f(i)) & ~1, self.rep(self.qlit(i)) & ~1}
        out = set()
        for s in (self.cone4[i] if cone is None else cone):
            r = self.rep(2 * s)
            if r <= 1 or (r & ~1) in own:
                continue
            out.add(r & ~1)
        return sorted(out, key=lambda L: (self.labels[L >> 1], L))

    def control_relations(self):
        """Per flop and candidate class literal (both polarities): hold (L=1 -> f = q) and set
        (L=1 -> f = v) on live lanes, counted only with CONTROL_EVIDENCE expected coincidences.
        Then control classes: literals relating to >= CONTROL_MIN_FLOPS flops."""
        t0 = time.perf_counter()
        P = self.P
        live = self.live
        Lc = max(1, _pc(live))
        ev = P["CONTROL_EVIDENCE"]
        rel = collections.defaultdict(lambda: [set(), {}])
        self._cand = []
        act_all = self._activity()
        for i in range(self.F):
            cands = self._cand_reps(i)
            self._cand.append(cands)
            if not cands or i in self.quiescent:
                continue
            f = self.value(self.f(i))
            q = self.value(self.qlit(i))
            act = (f ^ q) & live
            a = int(act_all[i])
            f1 = f & live
            cnt_f1 = _pc(f1)
            cnt_f0 = Lc - cnt_f1
            sig = np.array([L >> 1 for L in cands], np.int64)
            X = self.V[sig, :self.W]
            n1 = _pc_rows(X & live)
            n0 = Lc - n1
            h1 = _pc_rows(X & act)
            h0 = a - h1
            r0_1 = _pc_rows(X & f1)          # X=1 lanes with f=1 (break "set 0")
            r1_1 = n1 - r0_1                 # X=1 lanes with f=0 (break "set 1")
            r0_0 = cnt_f1 - r0_1
            r1_0 = cnt_f0 - r1_1
            bad = self._refuted
            for k, L in enumerate(cands):
                for pol, nl, hm, m0, m1 in ((0, n1[k], h1[k], r0_1[k], r1_1[k]), (1, n0[k], h0[k], r0_0[k], r1_0[k])):
                    if nl < P["WITNESS_LANES"]:
                        continue
                    lit = L | pol
                    if hm == 0 and a * nl >= ev * Lc and (lit, i, "h") not in bad:
                        rel[lit][0].add(i)
                    if m0 == 0 and cnt_f1 * nl >= ev * Lc and (lit, i, 0) not in bad:
                        rel[lit][1][i] = 0
                    elif m1 == 0 and cnt_f0 * nl >= ev * Lc and (lit, i, 1) not in bad:
                        rel[lit][1][i] = 1
        self.control = {}
        for lit, (h, s) in rel.items():
            if len(h) + len(s) >= P["CONTROL_MIN_FLOPS"]:
                self.control[lit] = ControlClass(lit, set(h), dict(s), self.count(lit))
        self.stats["control_classes"] = len(self.control)
        self.timings.setdefault("control_relations", 0.0)
        self.timings["control_relations"] += time.perf_counter() - t0

    def confirm_controls(self):
        """One miter per control class: L = 1, rho inactive and some held flop changing or some
        set flop differing from its value (relations not yet proven only). UNSAT proves them; a
        model refutes the relations it breaks (dropped for good) and becomes lanes; repeat up to 4
        times per class. Proven and refuted relations are remembered across calls."""
        t0 = time.perf_counter()
        P = self.P
        order = sorted(self.control.values(), key=lambda c: (-c.n, self.labels[c.lit >> 1], c.lit))
        cex_assigns = []
        for c in order:
            for _it in range(4):
                todo_h = [i for i in sorted(c.holds) if (c.lit, i, "h") not in self._proven]
                todo_s = [(i, v) for i, v in sorted(c.sets.items()) if (c.lit, i, v) not in self._proven]
                if not todo_h and not todo_s:
                    c.confirmed = True
                    break
                if not self._budget():
                    break
                m = Miter(self.S)
                k = m.copy()
                ors = []
                for i in todo_h:
                    ors.append(m.gate(0b0110, [m.lit(k, self.f(i)), m.lit(k, self.qlit(i))]))
                for i, v in todo_s:
                    x = m.lit(k, self.f(i))
                    ors.append(-x if v else x)
                m.add(ors)
                assume = [m.lit(k, c.lit)] + [m.lit(k, a) for a in self.assume()]
                want = {abs(m.lit(k, self.f(i))) for i in todo_h + [i for i, _v in todo_s]}
                want |= {abs(m.lit(k, self.qlit(i))) for i in todo_h}
                want |= {v for sg, v in m.maps[k].items() if sg and self.S.kind[sg] != GATE}
                sat, model = m.solve(assume, limit=P["SAT_LIMIT"] * 4, want=want)
                self.sat.stats["calls"] += 1
                self.stats["confirm_queries"] += 1
                if sat is False:
                    self._proven.update((c.lit, i, "h") for i in todo_h)
                    self._proven.update((c.lit, i, v) for i, v in todo_s)
                    c.confirmed = True
                    break
                if sat is None:
                    c.confirmed = None
                    self.stats["confirm_unknown"] += 1
                    break

                def val(lit):
                    d = m.lit(k, lit)
                    return model.get(abs(d), 0) ^ (1 if d < 0 else 0)

                for i in todo_h:
                    if val(self.f(i)) != val(self.qlit(i)):
                        c.holds.discard(i)
                        self._refuted.add((c.lit, i, "h"))
                        self.stats["confirm_refuted"] += 1
                for i, v in todo_s:
                    if val(self.f(i)) != v:
                        del c.sets[i]
                        self._refuted.add((c.lit, i, v))
                        self.stats["confirm_refuted"] += 1
                cex_assigns.append((m.sources(model, k), P["WITNESS_LANES"]))
                c.confirmed = False
        for c0 in range(0, len(cex_assigns), P["WITNESS_BATCH"]):
            if not self.add_lanes(cex_assigns[c0:c0 + P["WITNESS_BATCH"]], "confirm"):
                break
        for lit in list(self.control):
            if self.control[lit].n < P["CONTROL_MIN_FLOPS"]:
                del self.control[lit]
        self.stats["control_classes_confirmed"] = sum(1 for c in self.control.values() if c.confirmed)
        self.stats["control_relations_proven"] = len(self._proven)
        self.timings["confirm_controls"] = self.timings.get("confirm_controls", 0.0) + time.perf_counter() - t0

    # ------------------------------------------------------------------ profiles
    def _templates(self, i, U):
        """The first template that fits flop i on lanes U, or None."""
        P = self.P
        f = self.value(self.f(i))
        q = self.value(self.qlit(i))
        if not ((f & U).any()):
            return "const", 0
        if not ((~f & U).any()):
            return "const", 1
        if not (((f ^ q) & U).any()):
            return "hold", None
        srcs = [s for s in self.supp_src[i] if s != self.flops[i].q]
        if srcs:
            X = self.V[np.array(srcs, np.int64), :self.W]
            d = (X ^ f) & U
            ok = np.flatnonzero(~d.any(axis=1))
            if len(ok):
                s = min((srcs[k] for k in ok), key=lambda s: (self.g.kind[s] != FLOP, self.labels[s], s))
                return "copy", s
            d = (X ^ ~f) & U
            ok = np.flatnonzero(~d.any(axis=1))
            if len(ok):
                s = min((srcs[k] for k in ok), key=lambda s: (self.g.kind[s] != FLOP, self.labels[s], s))
                return "copy_inv", s
        if not (((f ^ ~q) & U).any()):
            return "toggle", None
        allsrc = self.supp_src[i]
        if len(allsrc) <= P["AFFINE_MAX_SUPP"]:
            a = self._affine(f, allsrc, U)
            if a is not None:
                return "affine", a
        return "other", None

    def _affine(self, f, srcs, U):
        """f = c xor (xor of some srcs) on lanes U? Gaussian elimination over GF(2) on a sample
        of U, then checked on every lane of U."""
        lanes = np.flatnonzero(np.unpackbits(U.view(np.uint8), bitorder="little"))
        if len(lanes) == 0:
            return None
        samp = lanes[:self.P["AFFINE_SAMPLE"]]
        rows = self.V[np.array(srcs, np.int64), :self.W]
        varies = (rows & U).any(axis=1) & (~rows & U).any(axis=1)
        srcs = [s for s, v in zip(srcs, varies) if v]
        rows = rows[varies]
        cols = _gather(np.vstack([rows, f[None, :]]), samp)
        ints = [int.from_bytes(c.tobytes(), "little") for c in cols]
        ones = (1 << len(samp)) - 1
        basis = {}                      # pivot bit -> (vector, combination mask)
        vecs = ints[:-1] + [ones]
        for idx, v in enumerate(vecs):
            comb = 1 << idx
            while v:
                p = v & -v
                if p in basis:
                    bv, bc = basis[p]
                    v ^= bv
                    comb ^= bc
                else:
                    basis[p] = (v, comb)
                    break
        v, comb = ints[-1], 0
        while v:
            p = v & -v
            if p not in basis:
                return None
            bv, bc = basis[p]
            v ^= bv
            comb ^= bc
        use = [srcs[k] for k in range(len(srcs)) if comb >> k & 1]
        c = comb >> len(srcs) & 1
        acc = np.full(self.W, ALL1 if c else _Z)
        for s in use:
            acc = acc ^ self.V[s, :self.W]
        if ((acc ^ f) & U).any():
            return None
        return (use, c)

    def profiles(self, witness=True):
        """Per flop: reset value, then an ordered cover (priority cases, as RTL if/else chains
        read): each step is a control-class literal (ranked by flops controlled; own literal and
        its equals excluded) that holds (f = q) or sets (f = v) the flop on the lanes the earlier
        steps left, with enough lane evidence and, when CONFIRM_CONTROLS, proven by SAT (globally
        proven relations need no query; otherwise: earlier steps inactive, this step active, rho
        inactive -> f = target). Templates are tested before each further step; case literals for
        'other'. Each template is then checked by SAT (no step active -> f = template:
        Profile.template_proven). Pass 1 collects flops whose uncovered lanes are fewer than N_MIN,
        refuted steps and refuted templates; they become lanes (with case witnesses for rare flops
        by dominant class) and pass 2 recomputes everything."""
        t0 = time.perf_counter()
        P = self.P
        passes = 2 if witness else 1
        self._step_cache = getattr(self, "_step_cache", {})
        for pas in range(passes):
            need, cex = [], []
            self.profile = []
            act = self._activity()
            for i in range(self.F):
                self.profile.append(self._profile(i, int(act[i]), need if (pas == 0 and witness) else None, cex))
            for i, pr in enumerate(self.profile):
                self._prove_template(i, pr, cex if pas == 0 else None)
            if pas == 0 and witness:
                # rare flops by dominant cover class (a word written under one condition), then by SCC
                self._rare_words(lambda i: ("dom", self.profile[i].dominant) if self.profile[i].dominant is not None
                                 else ("scc", self.scc_of[i]), P["CASE_ROUNDS"] // 2, "case_dom")
                self._uncovered_witnesses(need)
                for c0 in range(0, len(cex), P["WITNESS_BATCH"]):
                    if not self.add_lanes(cex[c0:c0 + P["WITNESS_BATCH"]], "cover"):
                        break
                self.control_relations()
                if P["CONFIRM_CONTROLS"]:
                    self.confirm_controls()
            else:
                break
        cnt = collections.Counter(p.template for p in self.profile)
        self.stats.update({f"template_{k}": v for k, v in cnt.items()})
        self.stats["flops_with_hold_cover"] = sum(1 for p in self.profile if p.holds)
        self.stats["flops_with_set_cover"] = sum(1 for p in self.profile if p.sets)
        self.stats["flops_with_cover"] = sum(1 for p in self.profile if p.holds or p.sets)
        self.stats["flops_with_reset_value"] = sum(1 for p in self.profile if p.reset is not None)
        self.stats["cover_steps_proven"] = sum(sum(p.proven) for p in self.profile)
        self.stats["templates_proven"] = sum(1 for p in self.profile if p.template_proven)
        self.stats["templates_refuted"] = sum(1 for p in self.profile if p.template_proven is False)
        self.stats["cover_steps"] = sum(len(p.steps) for p in self.profile)
        self.timings["profiles"] = time.perf_counter() - t0

    def _profile(self, i, act_i, need, cex):
        P = self.P
        live = self.live
        pr = Profile(i)
        pr.reset = self.reset.values.get(i)
        pr.live = _pc(live)
        pr.active = act_i
        pr.quiescent = i in self.quiescent
        fl = self.flops[i]
        cands = []
        for L in self._cand[i]:
            for lit in (L, L | 1):
                if lit in self.control:
                    cands.append(lit)
        cands.sort(key=self._rank_key)
        f = self.value(self.f(i))
        q = self.value(self.qlit(i))
        X = self.V[np.array([c >> 1 for c in cands], np.int64), :self.W] if cands else None
        inv = np.array([c & 1 for c in cands], bool)
        used = np.zeros(len(cands), bool)
        U = live.copy()
        tpl, judged = None, None
        ev = P["CONTROL_EVIDENCE"]
        while not pr.quiescent:
            nU = _pc(U)
            if nU < P["N_MIN"]:
                if need is not None:
                    need.append(i)
                break
            tpl, judged = self._templates(i, U), nU
            if X is None or tpl[0] not in ("other", "affine"):
                break
            if len(pr.holds) >= P["COVER_CAP"] and len(pr.sets) >= P["COVER_CAP"]:
                break
            XU = X & U
            XU[inv] = ~X[inv] & U
            nl = _pc_rows(XU)
            a = (f ^ q) & U
            na = _pc(a)
            f1 = f & U
            c1 = _pc(f1)
            c0 = nU - c1
            miss_h = _pc_rows(XU & a)
            miss_0 = _pc_rows(XU & f1)            # l=1 lanes with f=1 break "set 0"
            miss_1 = nl - miss_0                  # l=1 lanes with f=0 break "set 1"
            pick = None
            for k in range(len(cands)):
                if used[k] or nl[k] < P["WITNESS_LANES"]:
                    continue
                kinds = []
                if miss_h[k] == 0 and na * nl[k] >= ev * nU and len(pr.holds) < P["COVER_CAP"]:
                    kinds.append("h")
                if miss_0[k] == 0 and c1 * nl[k] >= ev * nU and len(pr.sets) < P["COVER_CAP"]:
                    kinds.append(0)
                elif miss_1[k] == 0 and c0 * nl[k] >= ev * nU and len(pr.sets) < P["COVER_CAP"]:
                    kinds.append(1)
                for kind in kinds:
                    ok = self._prove_step(i, pr.steps, cands[k], kind, cex)
                    if ok is False:
                        continue
                    pick = (k, kind, ok)
                    break
                if pick is not None:
                    break
                used[k] = True if kinds else used[k]
            if pick is None:
                if tpl[0] == "affine":
                    break
                break
            if tpl[0] == "affine" and (cands[pick[0]] >> 1) not in set(tpl[1][0]):
                break              # an affine fit stands unless one of its variables is a cover literal
            k, kind, ok = pick
            used[k] = True
            lit = cands[k]
            pr.steps.append((lit, kind))
            pr.proven.append(bool(ok))
            if kind == "h":
                pr.holds.append(lit)
            else:
                pr.sets.append((lit, kind))
            U = U & ~XU[k]             # the step's lanes are covered
        pr.lanes = judged if judged is not None else _pc(U)
        if pr.quiescent:
            pr.template, pr.arg = "hold", None
        elif tpl is not None:
            pr.template, pr.arg = tpl
        covers = [l for l, _k in pr.steps]
        if covers:
            pr.dominant = min(covers, key=self._rank_key)
        pr.signature = (fl.clk_root, fl.clk_inv, self.rep(fl.clear) if fl.clear else 0,
                        self.rep(fl.preset) if fl.preset else 0, pr.dominant)
        if pr.template == "other":
            pr.cases = self._cases(i, U, set(covers))
        return pr

    def template_lit(self, i, pr=None):
        """The literal flop i's template gives for f_i (const v, hold q_i, copy 2s, copy_inv 2s+1,
        toggle ~q_i, affine c ^ xor(sources)), or None ('other', 'unknown')."""
        pr = self.profile[i] if pr is None else pr
        t = pr.template
        if t == "const":
            return int(pr.arg)
        if t == "hold":
            return self.qlit(i)
        if t in ("copy", "copy_inv"):
            return 2 * pr.arg + (t == "copy_inv")
        if t == "toggle":
            return self.qlit(i) ^ 1
        if t == "affine":
            acc = int(pr.arg[1])
            for x in pr.arg[0]:
                acc = self.S.lit_xor(acc, 2 * x)
            return acc
        return None

    def _prove_template(self, i, pr, cex):
        """SAT: with rho inactive and no cover step active, f_i equals the template literal. Sets
        pr.template_proven (True, False, or None for 'other', unknown or no budget); a refutation's
        counterexample goes to cex (lanes for the next pass) when cex is not None."""
        if pr.quiescent:
            pr.template_proven = True
            return
        t = self.template_lit(i, pr)
        if t is None:
            return
        steps = [l for l, _k in pr.steps]
        m = len(steps)
        tt = sum(1 << v for v in range(1 << (m + 2)) if any(v >> b & 1 for b in range(m)) or ((v >> m) & 1) == ((v >> (m + 1)) & 1))
        res, c = self.check(steps + [self.f(i), t], tt, bdd=self.P["BDD_PROFILES"])
        self.stats["template_queries"] += 1
        pr.template_proven = res
        if res is False and cex is not None:
            cex.append((c, self.P["WITNESS_LANES"]))

    def _prove_step(self, i, steps, lit, kind, cex):
        """True (proven), None (not attempted or unknown) or False (refuted; the counterexample
        goes to cex) for: earlier steps inactive, lit = 1, rho inactive -> f_i = q_i (kind 'h')
        or f_i = kind."""
        if not self.P["CONFIRM_CONTROLS"]:
            return None
        if (lit, i, kind) in self._proven:
            return True
        key = (i, tuple(steps), lit, kind)
        hit = self._step_cache.get(key)
        if hit is not None:
            return hit
        prev = [l for l, _k in steps]
        m = len(prev)
        lits = prev + [lit, self.f(i)] + ([self.qlit(i)] if kind == "h" else [])
        tgt = kind

        def ok(x):
            if any(x[:m]) or not x[m]:
                return True
            return x[m + 1] == (x[m + 2] if tgt == "h" else tgt)

        tt = sum(1 << v for v in range(1 << len(lits)) if ok(tuple(v >> b & 1 for b in range(len(lits)))))
        res, c = self.check(lits, tt, bdd=self.P["BDD_PROFILES"])
        self.stats["cover_step_queries"] += 1
        if res is False:
            cex.append((c, self.P["WITNESS_LANES"]))
            self.stats["cover_steps_refuted"] += 1
        out = res if res is not None else None
        self._step_cache[key] = out
        return out

    def _rank_key(self, lit):
        c = self.control.get(lit)
        return (-(c.n if c else 0), -(c.lanes if c else 0), self.labels[lit >> 1], lit)

    def _uncovered_witnesses(self, flops):
        """Witnesses for flops whose uncovered live lanes are too few: rho inactive, every cover
        literal of the flop inactive, and the flop changing (a case of the word {i})."""
        P = self.P
        items = []
        for i in sorted(set(flops), key=lambda i: (self.labels[self.flops[i].q], i)):
            pr = self.profile[i]
            wl = self._word_lit([i])
            for lit in pr.holds + [l for l, _v in pr.sets]:
                wl = self.S.lit_and(wl, lit ^ 1)
            st, a = self.witness(wl)
            if st == "sat":
                items.append((wl, a))
            elif st == "unsat":
                self.stats["uncovered_unsat"] += 1
        for c0 in range(0, len(items), P["WITNESS_BATCH"]):
            n, _c = self._case_lanes(items[c0:c0 + P["WITNESS_BATCH"]], "uncovered")
            if not n:
                break

    def own_difference(self, i):
        """Derived literal: lanes where flipping q_i changes f_i (Boolean difference)."""
        a, b = self.transparency(i, self.flops[i].q)
        return self.S.lit_or(a, b)

    def _cases(self, i, U, covers):
        """Up to CASE_CAP case literals from the depth-4 cone: on U & L(l), f_i is q_j, ~q_j, a
        constant or an opaque load (independent of q_i)."""
        P = self.P
        f = self.value(self.f(i))
        own = None
        nU = _pc(U)
        cands = []
        reps = self._cand[i] if self.cone_case is self.cone4 else self._cand_reps(i, self.cone_case[i])
        for L in reps:
            for lit in (L, L | 1):
                if lit in covers:
                    continue
                row = self.value(lit)
                Ul = U & row
                n = _pc(Ul)
                if n < P["CASE_MIN_LANES"] or n == nU:
                    continue
                cands.append((lit, Ul, n))
        cands.sort(key=lambda x: (-x[2], self.labels[x[0] >> 1], x[0]))
        out = []
        covered = np.zeros(self.W, np.uint64)
        srcs = [s for s in self.supp_src[i] if s != self.flops[i].q]
        X = self.V[np.array(srcs, np.int64), :self.W] if srcs else None
        for lit, Ul, n in cands:
            if len(out) >= P["CASE_CAP"]:
                break
            if not (Ul & ~covered).any():
                continue
            tpl = None
            if not (f & Ul).any():
                tpl = ("const", 0)
            elif not (~f & Ul).any():
                tpl = ("const", 1)
            elif X is not None:
                ok = np.flatnonzero(~((X ^ f) & Ul).any(axis=1))
                if len(ok):
                    tpl = ("copy", min((srcs[k] for k in ok), key=lambda s: (self.labels[s], s)))
                else:
                    ok = np.flatnonzero(~((X ^ ~f) & Ul).any(axis=1))
                    if len(ok):
                        tpl = ("copy_inv", min((srcs[k] for k in ok), key=lambda s: (self.labels[s], s)))
            if tpl is None:
                if own is None:
                    own = self.value(self.own_difference(i))
                if not (own & Ul).any():
                    tpl = ("load", None)
            if tpl is None:
                continue
            out.append((lit, tpl[0], tpl[1], n))
            covered |= Ul
        return out

    # ------------------------------------------------------------------ duplicates, support blocks
    def find_duplicates(self):
        t0 = time.perf_counter()
        groups = collections.defaultdict(list)
        for i, fl in enumerate(self.flops):
            groups[(self.rep(fl.ns), fl.clk_root, fl.clk_inv, fl.clear, fl.preset)].append(i)
        self.duplicates = []
        for key, mem in groups.items():
            if len(mem) < 2 or key[0] <= 1:
                continue
            mem.sort(key=lambda i: (self.labels[self.flops[i].q], i))
            base = mem[0]
            dup = [base]
            for i in mem[1:]:
                if not self._budget():
                    break
                ok, _c = self._sat([self.f(base), self.f(i)], 0b1001, [], self.P["SAT_LIMIT"], need_cex=False)
                if ok:
                    dup.append(i)
            if len(dup) > 1:
                self.duplicates.append(dup)
        self.timings["duplicates"] = time.perf_counter() - t0

    def support_blocks(self):
        """Data support, combining dependencies, blocks and nested-support chains.

        data_flops[i]: flops reached from f_i without passing any of its cover literals or rho.
        combining[i]: supp(f_i) minus the legs of a wide mux: when f_i is (structurally) unate
          in >= MUX_LEGS flops (copy or gating legs: a register-file read, a multi-source load,
          a write-back mux), those legs are transfers and are dropped; binate sources (XOR,
          adders, carries, selects) and the legs of narrow muxes (an LFSR's shift) stay.
        blocks: per state-support SCC, the SCCs of the combining graph inside it in dependency
          order (block-triangular): copy loops through register transfers are cut, words that
          combine their own bits (an LFSR/CRC, a counter with wrap logic) stay together.
        chains: nested-support chains over combining edges (see _chains)."""
        t0 = time.perf_counter()
        g = self.g
        rho_sig = {self.reset.lit >> 1} if self.reset.kind == "sync" else set()
        self.data_flops = []
        for i in range(self.F):
            pr = self.profile[i] if self.profile else None
            stop = set(rho_sig)
            if pr is not None:
                for l, _k in pr.steps:
                    stop |= {m >> 1 for m in self.members(self.rep(l) & ~1)} | {l >> 1}
            stop.discard(self.f(i) >> 1)
            _gates, leaves = g.cone([self.f(i)], stop=stop)
            self.data_flops.append(sorted(g.q2flop[s] for s in leaves if s in g.q2flop))
        P_, N_ = g.unate_supports()
        idx = g._source_index()
        self.combining = []
        self.self_binate = []          # f_i structurally binate in q_i
        self.self_neg = []             # q_i in the negative polarity of f_i: f_i can invert q_i (a toggle)
        for i in range(self.F):
            both = P_[i] & N_[i]
            self.self_binate.append(bool((both >> idx[self.flops[i].q]) & 1))
            self.self_neg.append(bool((N_[i] >> idx[self.flops[i].q]) & 1))
            one = (P_[i] | N_[i]) & ~both
            unate = [j for j in self.supp_flops[i] if j != i and (one >> idx[self.flops[j].q]) & 1]
            wide = len(unate) >= self.P["MUX_LEGS"]
            cut = set(unate) if wide else set()
            self.combining.append([j for j in self.supp_flops[i] if j != i and j not in cut])
        self.blocks = []
        for comp in self.sccs:
            inside = set(comp)
            pos = {i: k for k, i in enumerate(comp)}
            succ = [[] for _ in comp]
            for i in comp:
                for j in self.combining[i]:
                    if j in inside:
                        succ[pos[j]].append(pos[i])
            sub = _tarjan(len(comp), succ)          # Tarjan emits sinks first: reversed = sources first
            self.blocks.append([[comp[k] for k in b] for b in reversed(sub)])
        self.chains = self._chains()
        self.stats["blocks_multi"] = sum(1 for bl in self.blocks for b in bl if len(b) > 1)
        self.stats["chains"] = len(self.chains)
        self.timings["support_blocks"] = time.perf_counter() - t0

    def block_split(self, comp, share=None):
        """Blocks of a flop set (an SCC) in dependency order, cutting paths at rho and at the
        cover literals (every member of their classes) found in the covers of at least `share`
        (default BLOCK_CUT_SHARE) of the set's flops; share=1.0 cuts only controls common to all,
        share=0 every cover literal. Returns (blocks, cut literals)."""
        g = self.g
        share = self.P["BLOCK_CUT_SHARE"] if share is None else share
        rho_sig = {self.reset.lit >> 1} if self.reset.kind == "sync" else set()
        cnt = collections.Counter()
        for i in comp:
            if self.profile:
                cnt.update({l >> 1 for l, _k in self.profile[i].steps})
        cut = sorted(sg for sg, n in cnt.items() if n >= share * len(comp))
        stop = set(rho_sig)
        for sg in cut:
            stop |= {m >> 1 for m in self.members(self.rep(2 * sg) & ~1)} | {sg}
        inside = set(comp)
        pos = {i: k for k, i in enumerate(comp)}
        succ = [[] for _ in comp]
        for i in comp:
            st = set(stop)
            st.discard(self.f(i) >> 1)
            _gates, leaves = g.cone([self.f(i)], stop=st)
            for s in leaves:
                j = g.q2flop.get(s)
                if j is not None and j in inside and j != i:
                    succ[pos[j]].append(pos[i])
        sub = _tarjan(len(comp), succ)          # Tarjan emits sinks first: reversed = sources first
        return [[comp[k] for k in b] for b in reversed(sub)], [2 * sg for sg in cut]

    def _chains(self):
        """Nested-support chains, LSB first: b_0 .. b_k, each with a self-loop, where every bit's
        state support holds every lower bit (a carry may enter through a hold literal) and no
        bit's data support holds a higher bit (data support: data_flops, reached without passing
        the flop's cover literals or rho, so a full/empty or stop guard entering through a hold or
        set literal does not break the nesting), and b_0 able to invert its own state (q_0 in the
        negative structural polarity of f_0: an LSB toggles; an enable flag below it only holds).
        Grown upward from every such b_0: the candidates are the self-looped flops whose support
        holds every bit so far and that no bit so far depends on (data support); the next bit is
        a lowest candidate (no candidate strictly below it in data support; mutually dependent
        candidates, like two PCs sharing an incrementer, are one level), ranked twice: by the
        number of other candidates depending on it (a counter's next bit is read by every higher
        bit and every reader), then shared hold classes with the chain (a word holds under its own
        enable), and the other way round; then the smallest support. Each ranking also explores
        runner-up choices, up to CHAIN_PER_LSB chains per LSB. Flops that read the word
        (compare flags) may end up on top of a counter: the recognizers test prefixes. Chains of
        length >= 2 whose flop set is no prefix set of a longer chain, longest first."""
        F = self.F
        sup = [set(s) for s in self.supp_flops]
        dsup = [set(d) for d in getattr(self, "data_flops", [])] or sup
        selfloop = [i in sup[i] for i in range(F)]
        lsb = getattr(self, "self_neg", None) or selfloop
        dep = [set() for _ in range(F)]            # dep[j]: self-looped flops whose state support holds j
        for i in range(F):
            if selfloop[i]:
                for j in sup[i]:
                    if j != i:
                        dep[j].add(i)
        lab = lambda i: self.labels[self.flops[i].q]  # noqa: E731
        holds = [set(p.holds) for p in self.profile] if self.profile else [set() for _ in range(F)]
        cap_len = self.P["WORD_CAP"] + self.P["CHAIN_TOP_SLACK"]
        found = []
        for b0, by_holds in ((b, r) for b in sorted(range(F), key=lambda i: (lab(i), i)) for r in (False, True)):
            if not (selfloop[b0] and lsb[b0]) or not dep[b0]:
                continue
            # depth-first growth; the second-best choice of a step is explored while the LSB has
            # fewer than CHAIN_PER_LSB chains (the recognizers test each)
            stack = [([b0], set(dep[b0]), set(holds[b0]))]
            n_b0 = 0
            while stack and n_b0 < self.P["CHAIN_PER_LSB"]:
                chain, cand, H = stack.pop()
                while True:
                    X = [x for x in cand if x not in chain and not any(x in dsup[b] for b in chain)]
                    if not X or len(chain) >= cap_len:
                        break
                    Xs = set(X)
                    low = [x for x in X if not any(y in Xs and x not in dsup[y] for y in dsup[x] if y != x)] or X
                    def rank(x, Xs=Xs, H=H):
                        d = -sum(1 for y in dep[x] if y in Xs)
                        h = -len(holds[x] & H)
                        return ((h, d) if by_holds else (d, h)) + (len(sup[x]), lab(x), x)

                    ranked = sorted(low, key=rank)
                    if len(ranked) > 1 and len(stack) + n_b0 + 1 < self.P["CHAIN_PER_LSB"]:
                        y = ranked[1]
                        stack.append((chain + [y], cand & dep[y], H | holds[y]))
                    x = ranked[0]
                    chain = chain + [x]
                    cand = cand & dep[x]
                    H = H | holds[x]
                if len(chain) >= 2:
                    found.append(chain)
                    n_b0 += 1
        found.sort(key=lambda c: (-len(c), [lab(i) for i in c]))
        kept, prefixes = [], set()
        for c in found:                 # drop a chain whose flop set is a prefix set of a kept one
            if frozenset(c) in prefixes:
                continue
            kept.append(c)
            for n in range(2, len(c) + 1):
                prefixes.add(frozenset(c[:n]))
        return kept

    # ------------------------------------------------------------------ copy relations
    def transparency(self, i, j):
        """(T, T_inv) for flop i and source node j (derived literals in the scratch graph)."""
        key = (i, j)
        t = self._trans.get(key)
        if t is None:
            memo0, memo1 = self._cof_memo(j)
            c0 = self.S.cofactor(self.f(i), j, 0, memo0)
            c1 = self.S.cofactor(self.f(i), j, 1, memo1)
            S = self.S
            t = self._trans[key] = (S.lit_and(c1, c0 ^ 1), S.lit_and(c1 ^ 1, c0))
        return t

    def _cof_memo(self, j):
        m = getattr(self, "_cofm", None)
        if m is None or m[0] != j:
            self._cofm = m = (j, {}, {})
        return m[1], m[2]

    def copy_relations(self):
        """Conditional copy relations (section 3.3, F2, M8).

        1. Edges: for every flop i and source j (flop state, input, black-box output) within
           COPY_DEPTH gate levels of f_i, the transparency conditions T = f_i|j=1 & ~f_i|j=0 (f_i
           copies j where T = 1) and T_inv = ~f_i|j=1 & f_i|j=0 (f_i = ~j where T_inv = 1), built by
           cofactoring in the scratch graph. An edge exists when its condition is satisfiable with
           rho inactive: live lanes, else a SAT witness (at most COPY_WITNESS_MAX per run), whose
           lanes are added; UNSAT conditions are dropped. cond is exact and sufficient:
           cond -> f_dst = src (or ~src).
        2. Copy classes: edges whose conditions are SAT-equal under ~rho (bucketed by live-lane
           signature, confirmed against the bucket's representative; at most one edge per
           destination). The class of edges whose condition is 1 is 'unconditional'.
        3. Copy groups: exact classes whose conditions co-occur far above chance (see
           _copy_groups). On the dev set the exact conditions of one shift differ between bits:
           in multi-hot states of a one-hot FSM (unreachable, so not excluded combinationally),
           other mux legs and constant legs leak bit-specific terms into T (measured on the dev set's
           byte shift: pairwise Jaccard 0.34-0.43, equal on every one-hot lane). A group's
           condition is the conjunction of its members' conditions: sufficient for every edge at
           once, and non-vacuous by its live lanes (concrete assignments with rho inactive)."""
        t0 = time.perf_counter()
        g, P = self.g, self.P
        D = P["COPY_DEPTH"]
        near = collections.defaultdict(list)          # source -> [(flop, depth)]
        for i, fl in enumerate(self.flops):
            best = {}
            fr = [(fl.ns >> 1, 0)]
            while fr:
                s, d = fr.pop()
                if s in best and best[s] <= d:
                    continue
                best[s] = d
                if g.kind[s] != GATE or d >= D:
                    continue
                for x in g.fanin[s]:
                    fr.append((x, d + 1))
            for s, d in best.items():
                if g.kind[s] in (FLOP, INPUT, BBOX) and s != fl.q and s not in self.const_live:
                    near[s].append((i, d))
        self.stats["copy_pairs"] = sum(len(v) for v in near.values())
        # 1. conditions and their lanes on the current words
        edges = []
        live = self.live
        for j in sorted(near, key=lambda s: (self.labels[s], s)):
            self._cofm = (j, {}, {})
            conds = []
            for i, d in sorted(near[j]):
                T, Ti = self.transparency(i, j)
                for inv, c in ((0, T), (1, Ti)):
                    if c != 0:
                        conds.append((i, d, inv, c))
            self._trans.clear()
            rows = self._rows([c for _i, _d, _v, c in conds])
            for i, d, inv, c in conds:
                edges.append(CopyEdge(j, i, inv, c, _pc(rows[c] & live), -1, d))
        self._cofm = None
        t1 = time.perf_counter()
        # 2. rare conditions: SAT witnesses (bounded); impossible ones are dropped
        dead = set()
        if P["COPY_WITNESS"]:
            done = 0
            rare = [e for e in edges if e.lanes < P["N_MIN"]]
            rare.sort(key=lambda e: (e.lanes, self.labels[e.src], self.labels[self.flops[e.dst].q], e.dst, e.inv))
            seen = set()
            k = 0
            while k < len(rare) and done < P["COPY_WITNESS_MAX"]:
                assigns = []
                W0 = self.W
                while k < len(rare) and len(assigns) < P["WITNESS_BATCH"] and done < P["COPY_WITNESS_MAX"]:
                    e = rare[k]
                    k += 1
                    if e.cond in seen:
                        continue
                    seen.add(e.cond)
                    if self.W > W0 and self._cnt_derived(e.cond) >= P["N_MIN"]:
                        continue
                    st, a = self.witness(e.cond)
                    done += 1
                    if st == "unsat":
                        dead.add(e.cond)
                    elif st == "sat":
                        assigns.append((a, P["WITNESS_LANES"]))
                if assigns and not self.add_lanes(assigns, "copy"):
                    break
            self.stats["copy_witnesses"] = done
            self.stats["copy_conditions_unsat"] = len(dead)
        edges = [e for e in edges if e.cond not in dead]
        t2 = time.perf_counter()
        # 3. final lane counts and live-lane signatures of the exact conditions (edges without
        # lanes are dropped: their conditions were never witnessed)
        sig = {}
        for c0 in range(0, len(edges), 1024):
            chunk = edges[c0:c0 + 1024]
            rows = self._rows([e.cond for e in chunk])
            live = self.live
            for e in chunk:
                r = rows[e.cond] & live
                e.lanes = _pc(r)
                if e.cond not in sig:
                    sig[e.cond] = hashlib.blake2b(r.tobytes(), digest_size=16).digest()
        edges = [e for e in edges if e.lanes > 0]
        edges.sort(key=lambda e: (self.labels[e.src], self.labels[self.flops[e.dst].q], e.src, e.dst, e.inv))
        self.copy_edges = edges
        self._cond_sig = sig
        t3 = time.perf_counter()
        W0 = self.W
        self._copy_classes()
        if self.W != W0:              # counterexample lanes: recount (the classes stand: SAT decided them)
            for c0 in range(0, len(edges), 1024):
                chunk = edges[c0:c0 + 1024]
                rows = self._rows([e.cond for e in chunk])
                for e in chunk:
                    e.lanes = _pc(rows[e.cond] & self.live)
        t4 = time.perf_counter()
        self._copy_groups()
        t5 = time.perf_counter()
        self.stats["copy_edges"] = len(edges)
        self.stats["copy_classes"] = len(self.copy_classes)
        self.stats["copy_classes_multi"] = sum(1 for v in self.copy_classes.values() if len(v) > 1)
        self.stats["copy_edges_in_multi_classes"] = sum(len(v) for v in self.copy_classes.values() if len(v) > 1)
        self.stats["copy_unconditional"] = len(self.copy_classes.get(self.uncond_class, [])) if self.uncond_class is not None else 0
        self.stats["copy_groups"] = len(self.copy_groups)
        self.timings["copy_relations"] = time.perf_counter() - t0
        for name, dt in (("conditions", t1 - t0), ("witnesses", t2 - t1), ("lanes", t3 - t2), ("classes", t4 - t3),
                         ("groups", t5 - t4)):
            self.timings[f"copy_relations.{name}"] = dt

    def _rows(self, lits):
        """Full-width lane rows of many literals: {literal: row}. Derived intermediates are shared
        and evaluated in id (topological) order; each is freed after its last consumer, so memory
        stays at the requested rows plus the evaluation frontier."""
        S, n, W = self.S, self.n, self.W
        want = {l >> 1 for l in lits if (l >> 1) >= n}
        need, stack = set(), list(want)
        while stack:
            t = stack.pop()
            if t in need:
                continue
            need.add(t)
            stack.extend(x for x in S.fanin[t] if x >= n and x not in need)
        uses = collections.Counter(x for t in need for x in S.fanin[t] if x >= n)
        memo = {}
        for t in sorted(need):
            fan = S.fanin[t]
            memo[t] = eval_tt(S.tt[t], len(fan), [memo[x] if x >= n else self.V[x, :W] for x in fan])
            for x in fan:
                if x >= n:
                    uses[x] -= 1
                    if not uses[x] and x not in want:
                        del memo[x]
        out = {}
        for l in lits:
            t = l >> 1
            r = memo[t] if t >= n else self.V[t, :W]
            out[l] = ~r if l & 1 else r
        return out

    def _cnt_derived(self, lit):
        return _pc(self.value(lit) & self.live)

    def _copy_classes(self):
        """Copy classes: edges whose exact conditions are SAT-equal under ~rho, found within buckets
        of equal live-lane signature (a class takes at most one edge per destination flop). A
        refuted equality adds its counterexample as lanes at the end of the stage; after
        CLASS_FAIL_CAP consecutive refutations the rest of a bucket stays apart. The bucket whose
        signature is 'every live lane' is checked against the constant 1 first: its members form
        the unconditional class (self.uncond_class)."""
        P = self.P
        E = self.copy_edges
        live = self.live
        all_sig = hashlib.blake2b(live.tobytes(), digest_size=16).digest()
        buckets = collections.defaultdict(list)
        for k, e in enumerate(E):
            buckets[self._cond_sig[e.cond]].append(k)
        cls = 0
        self.copy_classes = {}
        self.uncond_class = None
        cex = []
        fails_total = 0
        for bkey in sorted(buckets, key=lambda b: min(buckets[b])):
            pending = list(buckets[bkey])
            if bkey == all_sig:
                one, rest = [], []
                dsts = set()
                for k in pending:
                    c = E[k].cond
                    ok = True if c == 1 else self.equal(c, 1)
                    self.stats["copy_class_checks"] += c != 1
                    if ok and E[k].dst not in dsts:
                        one.append(k)
                        dsts.add(E[k].dst)
                    else:
                        rest.append(k)
                if one:
                    for k in one:
                        E[k].cls = cls
                    self.copy_classes[cls] = one
                    self.uncond_class = cls
                    cls += 1
                pending = rest
            while pending:
                r = pending[0]
                cur, rest, dsts = [r], [], {E[r].dst}
                fails = 0
                for k in pending[1:]:
                    if E[k].dst in dsts or fails >= P["CLASS_FAIL_CAP"]:
                        rest.append(k)
                        continue
                    a, b = E[r].cond, E[k].cond
                    if a == b:
                        ok, c = True, None
                    elif not self._budget():
                        ok, c = None, None
                    else:
                        ok, c = self._sat([a, b], 0b1001, self.assume(), P["SAT_LIMIT"])
                        self.stats["copy_class_checks"] += 1
                    if ok:
                        cur.append(k)
                        dsts.add(E[k].dst)
                        fails = 0
                    else:
                        rest.append(k)
                        fails += 1
                        if ok is False:
                            fails_total += 1
                            cex.append((c, 1))      # one lane each: it only has to split the bucket
                for k in cur:
                    E[k].cls = cls
                self.copy_classes[cls] = cur
                cls += 1
                if len(rest) == len(pending) - 1 and fails >= P["CLASS_FAIL_CAP"]:
                    for k in rest:              # the remaining edges stay singletons
                        E[k].cls = cls
                        self.copy_classes[cls] = [k]
                        cls += 1
                    break
                pending = rest
        self.stats["copy_class_refuted"] = fails_total
        for c0 in range(0, len(cex), P["WITNESS_BATCH"]):
            if not self.add_lanes(cex[c0:c0 + P["WITNESS_BATCH"]], "copy_class"):
                break
        self._class_cond = {}

    def _minhash(self, M, perms):
        """Min-hash values of bit rows M (m, W): per permutation of the lane words, the rank of
        the first set lane (word rank * 64 + bit), -1 for an empty row. Pool lanes are drawn
        independently, so word order is the only order that matters."""
        m = M.shape[0]
        out = np.full((m, len(perms)), -1, np.int64)
        nz = M != 0
        has = nz.any(axis=1)
        ar = np.arange(m)
        for h, perm in enumerate(perms):
            pos = nz[:, perm].argmax(axis=1)
            v = M[ar, perm[pos]]
            low = v & (~v + np.uint64(1))
            bit = np.zeros(m, np.int64)
            ok = low != 0
            bit[ok] = np.log2(low[ok].astype(np.float64)).astype(np.int64)
            out[has, h] = (pos * 64 + bit)[has]
        return out

    def _copy_groups(self):
        """Copy groups: exact copy classes whose conditions co-occur far above chance, grown into
        groups whose conjunction still holds on live lanes.

        Nodes are the exact classes with WITNESS_LANES .. GROUP_MAX_DENSITY * live lanes (the
        unconditional class excluded: it co-occurs with everything). Candidate pairs come from
        min-hash banding (GROUP_HASHES hashes over random permutations of the lane words, bands
        of GROUP_BAND; buckets above GROUP_BUCKET_MAX members are skipped); a pair is similar when
        its exact overlap |A & B| is >= GROUP_OVERLAP of the smaller condition and its lift
        |A & B| L/(|A| |B|) is >= GROUP_LIFT, or >= GROUP_REL_LIFT of the largest lift attainable
        at these densities (L/max(|A|, |B|): containment) when that is smaller (dense conditions). Groups grow from
        seeds (most path-adjacent similar neighbours first, then most similar neighbours): the member
        added next extends a copy path of the group if one can (its source is a group destination's
        state, or its destination's state a group source: copy structures are paths), then has the
        highest lift over the group's current condition (|cond & T| L/(|cond| |T|):
        a narrow condition that holds wherever the group's does ranks above a broad one), among
        those keeping >= GROUP_KEEP of the condition's lanes (and >= WITNESS_LANES) with the lift
        a similar pair needs, whose own condition has >= GROUP_SHARE of its lanes inside (a shrunken
        group condition left only on multi-hot junk lanes cannot take unrelated edges); at most one
        edge per destination. A condition that contains the group's (an
        edge that copies whenever the group does, e.g. a serial front end feeding a shift) can
        still join late: the recognizers pick their paths inside a group. Each group
        is {"classes", "edges", "lanes"}; its condition is group_cond(group)."""
        P = self.P
        E = self.copy_edges
        live = self.live
        L = max(1, _pc(live))
        cls_ids = [c for c in sorted(self.copy_classes) if c != self.uncond_class]
        node_cls, node_cond, node_lanes = [], [], []
        for c in cls_ids:
            e0 = E[self.copy_classes[c][0]]
            if P["WITNESS_LANES"] <= e0.lanes <= P["GROUP_MAX_DENSITY"] * L:
                node_cls.append(c)
                node_cond.append(e0.cond)
                node_lanes.append(e0.lanes)
        m = len(node_cls)
        self.copy_groups = []
        if m < 2:
            return
        rng = np.random.default_rng(_h("minhash", P["POOL_SALT"]) & 0xFFFFFFFF)
        H, B = P["GROUP_HASHES"], P["GROUP_BAND"]
        perms = [rng.permutation(self.W) for _ in range(H)]
        MH = np.zeros((m, H), np.int64)
        for c0 in range(0, m, 1024):
            conds = node_cond[c0:c0 + 1024]
            rows = self._rows(conds)
            M = np.vstack([rows[c] & live for c in conds])
            MH[c0:c0 + len(conds)] = self._minhash(M, perms)
        PA, PB = [], []
        big = 0
        for b in range(H // B):
            band = np.ascontiguousarray(MH[:, b * B:(b + 1) * B])
            ok = np.flatnonzero((band >= 0).all(axis=1))
            if len(ok) < 2:
                continue
            _u, inv, cnts = np.unique(band[ok], axis=0, return_inverse=True, return_counts=True)
            inv = inv.reshape(-1)
            order = np.argsort(inv, kind="stable")
            starts = np.concatenate([[0], np.cumsum(cnts)])
            for u in np.flatnonzero(cnts >= 2):
                if cnts[u] > P["GROUP_BUCKET_MAX"]:
                    big += 1
                    continue
                mem = np.sort(ok[order[starts[u]:starts[u + 1]]])
                ia, ib = np.triu_indices(len(mem), 1)
                PA.append(mem[ia])
                PB.append(mem[ib])
        del MH
        self.stats["group_buckets_skipped"] = big
        if not PA:
            self.stats["group_candidate_pairs"] = 0
            return
        pk = np.unique(np.concatenate(PA).astype(np.int64) * m + np.concatenate(PB))
        del PA, PB
        self.stats["group_candidate_pairs"] = len(pk)
        # rows of the nodes in some candidate pair
        used = np.unique(np.concatenate([pk // m, pk % m]))
        pos = np.full(m, -1, np.int64)
        pos[used] = np.arange(len(used))
        R = np.empty((len(used), self.W), np.uint64)
        for c0 in range(0, len(used), 1024):
            conds = [node_cond[x] for x in used[c0:c0 + 1024]]
            rows = self._rows(conds)
            for k, c in enumerate(conds):
                R[c0 + k] = rows[c] & live
            del rows
        cnt = np.concatenate([_pc_rows(R[c0:c0 + 1024]) for c0 in range(0, len(R), 1024)])
        self.stats["group_rows_mb"] = round(R.nbytes / 1e6, 1)
        pa, pb = pos[pk // m], pos[pk % m]
        del pk
        both = np.zeros(len(pa), np.int64)
        for c0 in range(0, len(pa), 4096):
            both[c0:c0 + 4096] = _pc_rows(R[pa[c0:c0 + 4096]] & R[pb[c0:c0 + 4096]])
        na, nb = cnt[pa], cnt[pb]
        overlap = both / np.maximum(1, np.minimum(na, nb))
        lift = both * L / np.maximum(1, na * nb)
        need = np.minimum(P["GROUP_LIFT"], P["GROUP_REL_LIFT"] * L / np.maximum(1, np.maximum(na, nb)))
        good = (overlap >= P["GROUP_OVERLAP"]) & (lift >= need) & (both >= P["WITNESS_LANES"])
        ga, gb = pa[good], pb[good]
        del pa, pb, both, na, nb, overlap, lift
        self.stats["group_similar_pairs"] = int(good.sum())
        # neighbour lists (CSR over positions in `used`)
        src_ = np.concatenate([ga, gb])
        dst_ = np.concatenate([gb, ga])
        order = np.argsort(src_, kind="stable")
        src_, dst_ = src_[order], dst_[order]
        ptr = np.searchsorted(src_, np.arange(len(used) + 1))
        nbr = {int(u): dst_[ptr[u]:ptr[u + 1]] for u in np.unique(src_)}
        used = [int(x) for x in used]
        dst_of = [{E[k].dst for k in self.copy_classes[node_cls[x]]} for x in used]
        srcs_of = [{E[k].src for k in self.copy_classes[node_cls[x]]} for x in used]
        dstq_of = [{self.flops[i].q for i in d} for d in dst_of]
        lab = lambda u: min((self.labels[E[k].src], self.labels[self.flops[E[k].dst].q]) for k in self.copy_classes[node_cls[used[u]]])  # noqa: E731
        adj = lambda u, v: bool(srcs_of[u] & dstq_of[v] or srcs_of[v] & dstq_of[u])  # noqa: E731
        adj_n = {u: sum(1 for v in nbr[u].tolist() if adj(u, v)) for u in nbr}
        taken = set()
        grown = []
        for seed in sorted(nbr, key=lambda u: (-adj_n[u], -len(nbr[u]), lab(u), u)):
            if seed in taken:
                continue
            members, dsts = [seed], set(dst_of[seed])
            g_src, g_dstq = set(srcs_of[seed]), set(dstq_of[seed])
            cond = R[seed].copy()
            nc = int(cnt[seed])
            front = set(nbr[seed].tolist()) - taken
            while front:
                cand = np.array(sorted(u for u in front if not (dst_of[u] & dsts)), np.int64)
                if not len(cand):
                    break
                keep = np.concatenate([_pc_rows(R[cand[c0:c0 + 1024]] & cond) for c0 in range(0, len(cand), 1024)])
                lift = keep * L / np.maximum(1, nc * cnt[cand])
                need = np.minimum(P["GROUP_LIFT"], P["GROUP_REL_LIFT"] * L / np.maximum(nc, cnt[cand]))
                ok = (keep >= max(P["WITNESS_LANES"], P["GROUP_KEEP"] * nc)) & (lift >= need) & (keep >= P["GROUP_SHARE"] * cnt[cand])
                if not ok.any():
                    break
                on_path = np.array([bool(srcs_of[u] & g_dstq or dstq_of[u] & g_src) for u in cand])
                score = np.where(ok, lift + np.where(on_path, lift.max() + 1.0, 0.0), -1.0)
                k = int(np.argmax(score))
                u = int(cand[k])
                members.append(u)
                dsts |= dst_of[u]
                g_src |= srcs_of[u]
                g_dstq |= dstq_of[u]
                cond &= R[u]
                nc = int(keep[k])
                front.update(nbr[u].tolist())
                front -= set(members) | taken
            if len(members) < 2:
                continue
            taken.update(members)
            grown.append((members, cond, nc, dsts, g_src, g_dstq))
        grown = self._regrow(grown, R, cnt, L, dst_of, srcs_of, dstq_of)
        self._group_nbr = {int(node_cls[used[u]]): sorted(int(node_cls[used[v]]) for v in nbr[u].tolist()) for u in nbr}
        del R
        for members, _cond, nc, _d, _s, _q in grown:
            classes = sorted(node_cls[used[u]] for u in members)
            self.copy_groups.append({"classes": classes, "edges": sorted(k for c in classes for k in self.copy_classes[c]),
                                     "lanes": nc})
        self.copy_groups.sort(key=lambda g: (-len(g["edges"]), g["edges"][0]))
        self.stats["copy_group_edges"] = sum(len(g["edges"]) for g in self.copy_groups)

    def _regrow(self, grown, R, cnt, L, dst_of, srcs_of, dstq_of):
        """Second growth pass along copy paths: each group, largest first, takes path-adjacent
        nodes (an edge starting at the state of a group destination, or ending at the state of a
        group source) from smaller groups or from no group, by the growth rule (keep >= GROUP_KEEP
        of the group condition's lanes, the pair lift, highest lift first, no common
        destination). The first pass is greedy from seeds, so a shift can end up split: a one-hot
        mux with a constant leg splits it into bit populations whose multi-hot junk differs
        (measured on a synthetic case), and junk-seeded groups take single edges (dev set). A group
        left with fewer than 2 members dissolves. Entries: (members, cond row, lanes, dsts, source
        signals, destination states)."""
        P = self.P
        m = R.shape[0]
        by_src, by_dstq = collections.defaultdict(set), collections.defaultdict(set)
        for u in range(m):
            for x in srcs_of[u]:
                by_src[x].add(u)
            for x in dstq_of[u]:
                by_dstq[x].add(u)
        grown = [list(t) for t in grown]
        owner = {u: gi for gi, t in enumerate(grown) for u in t[0]}
        moved = 0
        for gi in sorted(range(len(grown)), key=lambda k: (-len(grown[k][0]), -grown[k][2], grown[k][0][0])):
            g = grown[gi]
            if len(g[0]) < 2:
                continue
            while True:
                members, cond, nc, dsts, g_src, g_dstq = g
                mem = set(members)
                cand = ({u for x in g_dstq for u in by_src.get(x, ())} | {u for x in g_src for u in by_dstq.get(x, ())}) - mem
                cand = sorted(u for u in cand if not (dst_of[u] & dsts)
                              and (owner.get(u) is None or len(grown[owner[u]][0]) <= len(members)))
                if not cand:
                    break
                ca = np.array(cand, np.int64)
                keep = np.concatenate([_pc_rows(R[ca[c0:c0 + 1024]] & cond) for c0 in range(0, len(ca), 1024)])
                lift = keep * L / np.maximum(1, nc * cnt[ca])
                need = np.minimum(P["GROUP_LIFT"], P["GROUP_REL_LIFT"] * L / np.maximum(nc, cnt[ca]))
                ok = (keep >= max(P["WITNESS_LANES"], P["GROUP_KEEP"] * nc)) & (lift >= need) & (keep >= P["GROUP_SHARE"] * cnt[ca])
                if not ok.any():
                    break
                k = int(np.flatnonzero(ok)[np.argmax(lift[ok])])
                u = cand[k]
                old = owner.get(u)
                if old is not None:                    # leave the old group; recompute its condition
                    h = grown[old]
                    rest = [x for x in h[0] if x != u]
                    cr = R[rest[0]].copy() if rest else np.zeros_like(cond)
                    for x in rest[1:]:
                        cr &= R[x]
                    grown[old] = [rest, cr, _pc(cr), set().union(*(dst_of[x] for x in rest)) if rest else set(),
                                  set().union(*(srcs_of[x] for x in rest)) if rest else set(),
                                  set().union(*(dstq_of[x] for x in rest)) if rest else set()]
                g = [members + [u], cond & R[u], int(keep[k]), dsts | dst_of[u], g_src | srcs_of[u], g_dstq | dstq_of[u]]
                grown[gi] = g
                owner[u] = gi
                moved += 1
        self.stats["copy_group_moves"] = moved
        return [tuple(t) for t in grown if len(t[0]) >= 2]

    def similar_classes(self, cls):
        """Exact copy classes whose conditions co-occur with class `cls` (the similarity graph the
        groups were grown on: min-hash candidates verified by exact overlap and lift)."""
        return list(getattr(self, "_group_nbr", {}).get(cls, []))

    def group_cond(self, grp):
        """The conjunction of a copy group's exact conditions (a derived literal): when it holds,
        every edge of the group copies. Non-vacuous: grp["lanes"] live lanes satisfy it."""
        c = 1
        for k in grp["edges"]:
            c = self.S.lit_and(c, self.copy_edges[k].cond)
        return c

    def class_cond(self, cls):
        """The condition shared by every edge of an exact copy class (they are SAT-equal) and its
        live lanes: (literal, lanes). 1 for the unconditional class."""
        hit = self._class_cond.get(cls)
        if hit is None:
            e = self.copy_edges[self.copy_classes[cls][0]]
            c = 1 if cls == self.uncond_class else e.cond
            hit = self._class_cond[cls] = (c, self._cnt_derived(c) if c > 1 else _pc(self.live))
        return hit

    def joint_cond(self, edge_ids):
        """(literal, live lanes) of the conjunction of any edges' conditions (sufficient for all of
        them at once); a literal with 0 lanes may still be satisfiable: ask ctl.witness."""
        c = 1
        for k in edge_ids:
            c = self.S.lit_and(c, self.copy_edges[k].cond)
        return c, (self._cnt_derived(c) if c > 1 else (_pc(self.live) if c == 1 else 0))

    # ------------------------------------------------------------------ claims
    def expr(self, lit, _memo=None):
        """A claim EXPR for a literal: flop states as {"q": flop id}, net-carried signals as
        {"net": id}, other (derived or net-less) gates expanded as or-of-ands of their fanins."""
        s, inv = lit >> 1, lit & 1
        if s == 0:
            return {"const": inv}
        memo = {} if _memo is None else _memo
        if s not in memo:
            S = self.S
            if S.kind[s] == FLOP:
                e = {"q": int(self.flops[self.g.q2flop[s]].cell)}
            elif s < self.n and 2 * s in self._net:
                net, ninv = self._net[2 * s]
                e = {"not": {"net": int(net)}} if ninv else {"net": int(net)}
            elif S.kind[s] == GATE:
                k = len(S.fanin[s])
                terms = []
                for cube in isop(S.tt[s], k):
                    lits = [self.expr(2 * S.fanin[s][v] + (1 - b), memo) for v, b in cube]
                    terms.append(lits[0] if len(lits) == 1 else {"and": lits})
                e = terms[0] if len(terms) == 1 else {"or": terms}
            else:
                e = None
            memo[s] = e
        e = memo[s]
        if e is None:
            return None
        return {"not": e} if inv else e

    def cond(self, lits):
        out = []
        for lit in lits:
            s = lit >> 1
            hit = self._net.get(2 * s)
            if hit is None:
                return None
            net, ninv = hit
            out.append({"net": int(net), "value": int(1 ^ (lit & 1) ^ ninv)})
        return out

    def cubes(self, lit, max_inputs=12):
        """The literal as a disjunction of CONDs: its function over the first net-carried base
        signals below it (the cut), as an ISOP; None if the cut has more than max_inputs signals."""
        S = self.S
        cut, stack, seen = [], [lit >> 1], set()
        while stack:
            s = stack.pop()
            if s in seen:
                continue
            seen.add(s)
            if s == 0:
                continue
            if S.kind[s] != GATE or (s < self.n and 2 * s in self._net):
                cut.append(s)
                if len(cut) > max_inputs:
                    return None
                continue
            stack.extend(S.fanin[s])
        cut.sort()
        k = len(cut)
        pos = {s: i for i, s in enumerate(cut)}
        memo = {0: 0}

        def tt(s):
            if s in memo:
                return memo[s]
            if s in pos:
                memo[s] = _vmask(pos[s], k)
                return memo[s]
            ins = [tt(x) for x in S.fanin[s]]
            acc = 0
            for cube in isop(S.tt[s], len(ins)):
                t = _full(k)
                for v, b in cube:
                    t &= ins[v] if b else _full(k) ^ ins[v]
                acc |= t
            memo[s] = acc
            return acc

        t = tt(lit >> 1)
        if lit & 1:
            t ^= _full(k)
        out = []
        for cube in isop(t, k):
            c = self.cond([2 * cut[v] + (1 - b) for v, b in cube])
            if c is None:
                return None
            out.append(c)
        return out

    # ------------------------------------------------------------------ report
    def finish(self):
        """Final per-flop activity over every lane (the counts meta() reports) and lane statistics."""
        act = self._activity()
        self.stats["rare_flops_final"] = int(sum(1 for i in range(self.F) if act[i] < self.P["N_MIN"] and i not in self.quiescent))
        self.stats["lanes_final"] = self.lanes
        self.stats["live_lanes_final"] = _pc(self.live)

    def meta(self):
        """JSON-ready facts for result["meta"] (no timings: see run_info): the reset, per-flop
        active-lane counts keyed by flop id, lane origins, profile and control-class counts,
        support structure, duplicates, copy relations and SAT statistics."""
        R = self.reset
        cell = lambda i: int(self.flops[i].cell)  # noqa: E731
        prof = self.profile
        return {
            "reset": {"kind": R.kind, "literal_expr": self.expr(R.lit) if R.lit is not None else None,
                      "forced": R.forced, "of_flops": self.F, "support_size": len(R.support),
                      "flops_with_value": len(R.values), "async_flops": len(R.async_lits)},
            "mode_selector": (None if self.mode is None else
                              {**{k: v for k, v in self.mode.items() if k != "sig"},
                               "ambiguous_clock_root": bool(self.stats.get("clock_gate_root_ambiguous"))}),
            "clock_gates": {"logic_gated_flops": int(self.stats.get("clock_gate_logic_flops", 0)),
                            "folded": int(self.stats.get("clock_gate_folded", 0)),
                            "root_ambiguous": int(self.stats.get("clock_gate_root_ambiguous", 0)),
                            "flops": [cell(i) for i in sorted(self.clock_gates)]},
            "active_lanes": {str(cell(i)): int(self.active_count[i]) for i in range(self.F)},
            "rare_flops": int(sum(1 for i in range(self.F) if self.active_count[i] < self.P["N_MIN"])),
            "quiescent_flops": [cell(i) for i in sorted(self.quiescent)],   # canonical flop order, not ids
            "live_lanes": _pc(self.live), "lanes": self.lanes, "lanes_by_origin": self.origin_counts(),
            "templates": dict(sorted(collections.Counter(p.template for p in prof).items())),
            "profiles": {"with_cover": sum(1 for p in prof if p.steps), "with_hold": sum(1 for p in prof if p.holds),
                         "with_set": sum(1 for p in prof if p.sets),
                         "with_reset_value": sum(1 for p in prof if p.reset is not None),
                         "cover_steps": sum(len(p.steps) for p in prof),
                         "cover_steps_proven": sum(sum(p.proven) for p in prof)},
            "control_classes": len(self.control),
            "control_classes_confirmed": sum(1 for c in self.control.values() if c.confirmed),
            "const_live": len(self.const_live),
            "sccs": [len(c) for c in self.sccs],
            "blocks_multi": sum(1 for bl in getattr(self, "blocks", []) for b in bl if len(b) > 1),
            "chains": len(getattr(self, "chains", [])),
            "duplicates": [[cell(i) for i in d] for d in self.duplicates],
            "copy_edges": len(self.copy_edges), "copy_classes": len(self.copy_classes),
            "copy_classes_multi": sum(1 for v in self.copy_classes.values() if len(v) > 1),
            "copy_unconditional": len(self.copy_classes.get(self.uncond_class, [])) if self.uncond_class is not None else 0,
            "copy_groups": len(self.copy_groups),
            "sat": {k: v for k, v in sorted(self.sat.stats.items()) if not isinstance(v, float)},
            "stats": {k: v for k, v in sorted(self.stats.items()) if not isinstance(v, float)},
        }

    def run_info(self):
        """Volatile facts for the run record: timings per stage and SAT time."""
        return {"timings": {k: round(v, 3) for k, v in self.timings.items()},
                "sat_s": {k: round(v, 3) for k, v in self.sat.stats.items() if isinstance(v, float)},
                "bdd": {"s": round(self.stats.get("bdd_s", 0.0), 3), "nodes": self.bdd.nodes if self.bdd else 0,
                        **(dict(self.bdd.stats) if self.bdd else {})},
                "canonical_order": dict(getattr(self.g, "canon", None).stats) if getattr(self.g, "canon", None) else None}


STAGES = ("build", "find_reset", "make_pool", "support_graph", "rare_flops", "rare_literals", "literal_classes",
          "control_relations", "confirm_controls", "profiles", "find_duplicates", "copy_relations", "support_blocks",
          "finish")


def analyze(nl, params=None, stages=None):
    """Run the control layer on an anonymous netlist and return the Controls object."""
    ctl = Controls(nl, params)
    all_stages = STAGES
    for st in (stages or all_stages):
        if st == "confirm_controls" and not ctl.P["CONFIRM_CONTROLS"]:
            continue
        t0 = time.perf_counter()
        getattr(ctl, st)()
        ctl.timings.setdefault(st, time.perf_counter() - t0)
    return ctl
