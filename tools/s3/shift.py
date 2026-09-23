"""S3 shift-register and synchronizer recognizer (the S3 design doc, section 3.3, with the part-1
feasibility fixes F2, F7, F10 and measurements M8, M9).

Everything comes from the control layer (tools.s3.controls) built on the anonymous netlist: copy
edges with exact transparency conditions, exact copy classes, co-occurrence copy groups, profiles,
the reset. Simulation suggests; every reported "proven" rests on next-state claims that this module
checks by SAT exactly as the harness verifier will (miter unsatisfiable under the claim's COND, COND
satisfiable), with no reset assumption: the reset literal enters a COND like any other net.

API
---
    out = find(ctl, params=None)      # ctl: a Controls object after every stage of controls.STAGES
    out["structures"]                 # result-schema structures (kinds shift_register, synchronizer)
    out["relations"]                  # delay stages, depth-2 transfers, feedback lanes (LFSR candidates)
    out["stats"], out["timings"]
    result = recognize(nl, params=None)   # controls.analyze + find, as a whole result (stand-alone use)

Definitions (S3 design doc, section 1 and 3.3)
----------------------------------------------
  Copy edge j -> i: f_i = q_j (or ~q_j) wherever its transparency condition T holds (controls).
  Seed: an edge set under one condition: the unconditional class (T = 1 while the reset is
    inactive, plus direct wires f_i = source, which hold even under the reset), every exact copy
    class of >= 2 edges, and every copy group (exact classes whose conditions co-occur; a one-hot
    parallel mux leaks bit-specific terms into T in unreachable multi-hot states, so one shift's
    exact conditions can all differ).
  Stage edges: a copy edge is a stage edge only if its source reaches the destination through a
    mux or gating leg: where f_dst also follows ~src on >= 1/GROUP_LIFT of the edge's lanes (the
    inverse edge of the same pair), src is combined, not copied (XOR: LFSR/CRC taps, Gray logic).
    Flops that can invert their own state (q_i in the negative structural polarity of f_i:
    counters, accumulators) are never stages: carry chains otherwise look like conditional copies.
  Lanes: inside a seed, edges form vertex-disjoint paths (each flop has at most one incoming seed
    edge; at a fan-out the longest continuation wins, the other branches start their own paths).
    Stage 0 is the flop fed by the lane's head. Lanes are cut between stages of different clocks
    (root or edge); between stages of different asynchronous controls (clear / preset) only where
    the copy condition class changes too (a pipeline that resets only its first stages is one
    shift: the async controls are part of each stage's flop model and are reported per stage);
    and, in copy groups, where the exact class changes and one of the two classes has >= 2 edges
    (co-occurrence may join singleton classes, never lengthen a lane an exact class defines).
  Heads: a primary input or black-box output ("input"); a flop outside the structure ("flop":
    under the lanes' joint condition it holds, reads itself, or copies a neighbour at the same
    time); a flop loaded with one constant whenever the lanes copy ("const", it becomes stage 0);
    a flop loaded by logic of other signals under the same controls ("logic", stage 0); a copy
    cycle ("cycle": ring and Johnson registers); or a head whose next state reads the seed's own
    stages on the joint condition's lanes ("feedback"). A feedback head is tested (_feedback):
    when, on the joint condition's lanes, it reads the lane's last stage (the loop closes over the
    whole lane) and is NOT GF(2)-affine in the lane's own flops (a second derivative over two of
    them is 1 on some lane: a concrete witness), the lane is a nonlinear feedback shift register
    (NLFSR, de Bruijn, Grain-style NFSR) and becomes a shift lane whose stage 0 is the head
    ("feedback_logic"; stage 0 may read itself). Every other feedback lane (affine in its own bits:
    an LFSR/CRC candidate; or open: the last stage is not read) stays a "feedback" relation for
    tools.s3.lfsr, with the verdict recorded. lfsr.py never models a
    nonlinear feedback, so the two recognizers do not compete for a word; if both ever report
    the same flops, recognize.py's overlap rule keeps the lfsr_crc structure (more specific).
  Repair (group seeds and classes): a lane shorter than the seed's longest lane takes a missing
    edge at its head or tail from any class when that edge's condition co-occurs with the seed's
    joint condition as the copy groups require (GROUP_KEEP, GROUP_LIFT, GROUP_REL_LIFT) and the
    joint condition keeps >= WITNESS_LANES live lanes; this restores shift edges the group growth
    left out (its GROUP_SHARE rule rejects an edge whose own condition is much broader).
    Unconditional edges never repair a conditional seed.
  Synchronizer: stages 1-2 (SYNC_MAX_STAGES) of an unconditional copy path from a primary input;
    1-2 further stages are delay relations, >= SHIFT_MIN_DEPTH further stages a shift structure
    whose head is the second synchronizer stage.
  Shift structure: lanes of one seed with equal depth >= SHIFT_MIN_DEPTH, one head kind and one
    control signature (clock root and edge, asynchronous controls; for unconditional seeds also the
    per-stage reset value relative to the head, which alone tells unconditional registers apart).
    Shorter lanes are relations (depth-2 transfers). Parallel loads are separate cases: classes or
    groups copying outside sources into at least half of the structure's flops under one condition.
  Selection: candidates in order of size (then unconditional, exact-class, group seeds; then, when
    structural labels; and, among candidates over exactly the SAME flop set -- which are one
    structure read through different condition classes, all true of the netlist: a barrel rotate is
    one lane of depth 8 under "rotate by 1" and two lanes of depth 4 under "rotate by 2" -- the
    deepest lanes, then the fewest lanes, so that lanes / depth / serial_in / order are a function of
    the netlist's behaviour and not of which class the sweep happened to hit first
    (SHIFT_DECIDE_TIES; it reorders nothing outside such a group). The decompositions not taken are
    reported as "alternative_decomposition" relations); each one disjoint from those taken is evaluated and taken unless no
    joint cube exists (below): a candidate whose stages never copy at once under one net cube is
    not a shift under one condition and is dropped. One condition class (stage share): every
    copy edge of a conditional structure must copy under the structure's joint condition K on
    >= SHIFT_STAGE_SHARE (1/20) of the lanes where it copies at all (|K & T_e| / |T_e|), judged
    only where that share is expected to leave >= CONTROL_EVIDENCE lanes. A chain assembled from
    conditions of different events fails it: a one-hot FSM's state transitions and the handshake
    pulses they set (each copies on thousands of lanes, together on a few dozen: a data bit
    decoded into a state, the state, then a pulse) are not stages of one shift. Chosen shifts of
    equal depth, head kind and stage controls whose joint conditions co-occur (the copy-group
    rule) are merged into one structure when the merge has a joint cube (a lane the repair
    missed in one seed can come out whole from another).
  Lane order: along the copy chain through the heads when the heads form one (a serial front
    end feeding a parallel shift: the order is structural); otherwise no structural key orders
    the lanes (input pins, identical lanes), params.lanes_unordered = true and the lanes are
    listed by structural label, remaining ties in canonical flop order (GateGraph's canonical
    order: an automorphism orbit's members are interchangeable), never claimed as an order.

Claims (the schema module's "Proof claims"; roles defining, hold, reset, load)
-----------------------------------------------------------------------
  One joint cube K over nets for the whole structure (all stages copy at once under K). For up to
  CASE_WITNESSES live lanes where every edge's condition holds (or one SAT witness), the side
  inputs of the gates on the paths from the sources (and a logic stage 0's own state) into the
  next-state functions give a cube K0 at that lane; K0 must imply every copy (SAT) and is reduced
  greedily against the lanes, SAT confirming (each counterexample puts back the K0 literals it
  falsifies). The smallest of the first CASE_CAP cubes wins. Defining claim per stage: next(stage
  k) = q(stage k-1) (stage 0: its head, an input net, a constant, or the logic head's function
  under K) when K. Hold claims come from proven profile hold steps (earlier steps and the reset
  inactive), reset claims from the synchronous reset's forced value, load claims from load cases
  (their own cube). A claim is emitted only if this module's SAT check verified it; a structure's
  status is "proven" only when every flop has a verified defining claim, "failed" if a defining
  claim was refuted, else "unknown". Nothing here is proven by simulation.

Control (schema v2.1, "Verification (v2, kind-bound)": the harness builds the defining claims from
kind + order + params; this module supplies the conditions), structure["control"]:
  when         the joint cube K as a COND ([] = always); satisfiable with every stage's
               asynchronous clear / preset inactive (checked by SAT, else the structure is dropped)
  reset        a LIST of synchronous cases [{"when": COND, "value": {flop id: 0|1}}, ...]: the
               design's synchronous reset first (when every flop's reset claim verified), then, only
               while the hold obligation still fails, further clear cases found by _clear_cases --
               a netted literal under which every flop takes a constant. Each case's COND carries
               the complements of the single-literal cases before it, so the else-if priority the
               RTL wrote is explicit and two cases cannot disagree on a state. null with no case.
  load         a LIST of the parallel-load CONDs actually needed for the hold obligation, widest
               first (every load case _loads found is in proof.notes), null with none. A load case
               is opaque: nothing is checked under it, which is why one is named only after the
               checked reset cases have failed to close the obligation.
  hold         outside EVERY named case the flops keep their value. True when SAT proves it, and
               also when the hold region is EMPTY -- an unconditional shift register, or one that
               either shifts or loads, has no state outside its cases, and schema v2.1 accepts and
               reports that (the harness's hold_vacuous / load_hidden_share) instead of refusing it.
               False when SAT refutes it or runs out of budget.
  input        synchronizer: the input net of each lane's stage 0 (one lane: a net id; several: a
               list in lane order)
  inputs       [] (lfsr_crc only)
Diagnostics are in proof["notes"]: head kinds, seed, condition lanes, loads, lane order source,
"inverted_stages" (see below) and "stage_async" ({flop id: "clear" | "preset" | "clear+preset"} for
the stages with an asynchronous control: the per-stage controls of a lane that continues across an
asynchronous-control change). stage_async was a control key until 2026-09-22; schema v2's control
keys are exactly verify.CONTROL_KEYS and an unknown one makes the whole structure MALFORMED, so
every shift with an async-reset stage was thrown away by the harness.

Params: besides the schema's, "inverted" gives the per-stage inversion in the shape of "order"
(inverted[lane][k] = 1 when stage k stores the complement of stage k-1, stage 0 of its head). The
harness's shift and synchronizer templates allow an inverted copy edge and report the edges they
found inverted; the defining claims here already negate the source. The schema's PARAMS does not
list the key yet (the second generalisation review asked the lead for the wording); an extra result
param is ignored by the scorer, which reads the truth's params, and by the harness, which builds
the templates from kind + order.

Relations (out["relations"]): "alternative_decomposition" (another condition class's lanes over a
flop set already taken: equally true, not the reading reported), "delay" (unconditional stages after
a synchronizer), "transfer"
(depth-2 lanes of a conditional seed), "feedback" (lanes whose head reads the seed's own stages,
with the _feedback verdict: "affine" (LFSR/CRC candidates for tools.s3.lfsr), "open_loop",
"other_clock", "budget"; "nonlinear" lanes are also reported as shift_register structures),
"input_register" (single unconditional input copies). Flop ids are cell ids.

Thresholds are tools.s3.params entries (read through ctl.P; SHIFT_STAGE_SHARE and NLFSR_PAIRS_MAX
moved there from this module on 2026-09-22); nothing names a design.
"""
from __future__ import annotations

import collections
import time

import numpy as np

from tools.s3 import controls as _controls
from tools.s3 import params as _params
from tools.s3.netlist import ALL1, BBOX, FLOP, GATE, INPUT, isop

# This module's own thresholds (tools.s3.params entries, justified there); a view by name for callers.
THRESHOLDS = {k: getattr(_params, k) for k in ("SHIFT_STAGE_SHARE", "NLFSR_PAIRS_MAX",
                                              "SHIFT_DECIDE_TIES",
                                              # schema v2.1 multi-case control; moved into
                                              # tools/s3/params.py on 2026-09-23 (I01)
                                              "SHIFT_RESET_CASES", "HOLD_VACUOUS")}

# SHIFT_DECIDE_TIES (the deterministic lane decomposition) is a tools.s3.params entry with its
# justification too (moved there from this module on 2026-09-22; changes.jsonl C50).

RESULT_SCHEMA = "retrace-s3-result/1"
SHIFT = "shift_register"
SYNC = "synchronizer"
_TT_EQ = 0b1001          # relation a == b over (a, b)
_TT_NEVER = 0            # relation that never holds: check() answers True only when the assumptions are unsatisfiable
_EXPR_NODES = _params.HARNESS_EXPR_NODES // 2   # an EXPR expanded to sources stays below the verifier's node budget
_COND_MAX = _params.HARNESS_COND_LITERALS       # the verifier's COND conjunct budget
_ONE = np.uint64(1)


def _pc(x):
    return int(np.bitwise_count(x).sum())


def _first_lane(x):
    nz = np.flatnonzero(x)
    if len(nz) == 0:
        return None
    w = int(nz[0])
    v = int(x[w])
    return 64 * w + ((v & -v).bit_length() - 1)


class _Edge:
    """A copy edge: f_dst = src ^ inv wherever cond (a scratch-graph literal) holds."""
    __slots__ = ("src", "dst", "inv", "cond", "cls", "ref", "raw", "lanes")

    def __init__(self, src, dst, inv, cond, cls, ref, raw, lanes):
        self.src, self.dst, self.inv, self.cond, self.cls = src, dst, inv, cond, cls
        self.ref, self.raw, self.lanes = ref, raw, lanes


class _Lane:
    """Stages in order (flop indices), the edge into each stage (None for a logic or constant
    stage 0), the head source signal (None for such a stage 0 or a cycle) and the head kind."""
    __slots__ = ("nodes", "edges", "head", "kind", "const")

    def __init__(self, nodes, edges, head, kind=None):
        self.nodes, self.edges, self.head, self.kind = list(nodes), list(edges), head, kind
        self.const = None           # the constant a "const" stage 0 loads

    @property
    def depth(self):
        return len(self.nodes)


class ShiftRecognizer:
    def __init__(self, ctl, params=None):
        self.ctl = ctl
        self.P = dict(ctl.P)
        for k, v in THRESHOLDS.items():
            self.P.setdefault(k, v)
        for k, v in (params or {}).items():
            if k not in self.P:
                raise KeyError(f"unknown parameter {k}")
            self.P[k] = v
        self.g, self.S = ctl.g, ctl.S
        self.stats = collections.Counter()
        self.timings = collections.OrderedDict()
        self.sat_calls = 0
        self._rowc = {}
        self.relations = {"delay": [], "transfer": [], "feedback": [], "input_register": [],
                          "alternative_decomposition": []}

    # ------------------------------------------------------------------ helpers
    def cell(self, i):
        return int(self.ctl.flops[i].cell)

    def _flop_of(self, s):
        return self.g.q2flop.get(s)

    def _rows(self, lits):
        """Live-lane rows of literals (cached per literal; the pool is fixed while this runs)."""
        need = [l for l in dict.fromkeys(lits) if l not in self._rowc]
        if need:
            for c0 in range(0, len(need), 512):
                got = self.ctl._rows(need[c0:c0 + 512])
                live = self.ctl.live
                for l, r in got.items():
                    self._rowc[l] = r & live
        return [self._rowc[l] for l in lits]

    def _row(self, lit):
        if lit == 1:
            return self.ctl.live.copy()
        if lit == 0:
            return np.zeros(self.ctl.W, np.uint64)
        return self._rows([lit])[0]

    def _sat(self, lits, tt, assume=(), limit=None):
        if self.sat_calls >= self.P["SAT_CALLS_MAX"]:
            self.stats["sat_skipped"] += 1
            return None, None
        self.sat_calls += 1
        return self.ctl.sat.check(lits, tt, list(assume), limit=limit or self.P["SAT_LIMIT"])

    def _label(self, i):
        return self.ctl.labels[self.ctl.flops[i].q]

    # ------------------------------------------------------------------ edges and seeds
    def _prepare(self):
        ctl, g = self.ctl, self.g
        P = self.P
        self.E = []
        self.uncond = ("c", ctl.uncond_class) if ctl.uncond_class is not None else ("u",)
        seen = {}
        for k, e in enumerate(ctl.copy_edges):
            if g.kind[e.src] not in (FLOP, INPUT, BBOX):
                continue
            ed = _Edge(e.src, e.dst, e.inv, e.cond, ("c", e.cls), k, False, e.lanes)
            seen[(e.src, e.dst, e.inv)] = len(self.E)
            self.E.append(ed)
        L = _pc(ctl.live)
        self.L = max(1, L)
        # direct wires: f_i is a source literal (holds with the reset active too)
        for i, fl in enumerate(ctl.flops):
            s, inv = fl.ns >> 1, fl.ns & 1
            if s == 0 or s == fl.q or g.kind[s] not in (FLOP, INPUT, BBOX):
                continue
            k = seen.get((s, i, inv))
            if k is not None and self.E[k].cls == self.uncond:
                self.E[k].raw = True
                continue
            if k is not None:
                continue
            seen[(s, i, inv)] = len(self.E)
            self.E.append(_Edge(s, i, inv, 1, self.uncond, None, True, L))
        self.eligible = [not ctl.self_neg[i] and i not in ctl.quiescent for i in range(ctl.F)]
        self.stats["stage_ineligible_self_inverting"] = sum(1 for i in range(ctl.F) if ctl.self_neg[i])
        self.in_edges = collections.defaultdict(list)
        self.out_edges = collections.defaultdict(list)
        # a stage copies its source through a mux or gating leg; where f_dst also follows ~src on a
        # comparable share of lanes (the inverse edge has >= 1/GROUP_LIFT of the edge's lanes), src
        # is combined, not copied (XOR: LFSR/CRC taps, Gray logic): such edges are no stage edges
        lanes_of = {(e.src, e.dst, e.inv): e.lanes for e in self.E}
        keep = []
        for e in self.E:
            rev = lanes_of.get((e.src, e.dst, e.inv ^ 1), 0)
            if e.cls != self.uncond and rev * P["GROUP_LIFT"] >= e.lanes:
                self.stats["edges_combining_dropped"] += 1
                continue
            keep.append(e)
        self.E = keep
        self.stats["edges"] = len(self.E)
        for k, e in enumerate(self.E):
            self.in_edges[e.dst].append(k)
            self.out_edges[e.src].append(k)
        self.by_cls = collections.defaultdict(list)
        for k, e in enumerate(self.E):
            self.by_cls[e.cls].append(k)
        # per-flop control signature pieces
        self.async_of = []
        for i, fl in enumerate(ctl.flops):
            a = frozenset(ctl.rep(x) for x in (fl.clear, fl.preset) if x)
            self.async_of.append((fl.clk_root, fl.clk_inv, a))
        self.dom_of = []
        for i in range(ctl.F):
            dom = ctl.profile[i].dominant if ctl.profile else None
            self.dom_of.append(None if dom is None else ctl.rep(dom))
        self.reset_of = [ctl.profile[i].reset if ctl.profile else ctl.reset.values.get(i) for i in range(ctl.F)]
        self.dup_rank = {}
        for grp in ctl.duplicates:
            for r, i in enumerate(grp):
                self.dup_rank[i] = r
        self.rho = ctl.reset.lit if ctl.reset.kind == "sync" else None

    def _seeds(self):
        """(key, edge ids): the unconditional class, exact classes of >= 2 edges, copy groups."""
        ctl = self.ctl
        out = [(("unconditional",), list(self.by_cls.get(self.uncond, [])))]
        for c in sorted(ctl.copy_classes):
            key = ("c", c)
            if key == self.uncond:
                continue
            ks = self.by_cls.get(key, [])
            if len(ks) >= 2:
                out.append((("exact_class", c), list(ks)))
        ref2k = {e.ref: k for k, e in enumerate(self.E) if e.ref is not None}
        for gi, grp in enumerate(ctl.copy_groups):
            ks = [ref2k[r] for r in grp["edges"] if r in ref2k]
            if len(ks) >= 2:
                out.append((("copy_group", gi), ks))
        return out

    # ------------------------------------------------------------------ lanes
    def _lanes(self, eids):
        """Vertex-disjoint paths of an edge set (<= 1 edge per destination), longest continuation
        first at a fan-out; copy cycles become cyclic lanes."""
        E = self.E
        into = {}
        for k in eids:
            e = E[k]
            if not self.eligible[e.dst] or e.dst in into:
                continue
            into[e.dst] = k
        nodes = set(into)
        parent = {}
        for v, k in into.items():
            p = self._flop_of(E[k].src)
            if p is not None and p in nodes:
                parent[v] = p
        child = collections.defaultdict(list)
        for v, p in parent.items():
            child[p].append(v)
        below = {}                                   # longest path below each node (cycles cut)
        for v0 in sorted(nodes):
            if v0 in below:
                continue
            stack, on = [(v0, 0)], {v0}
            while stack:
                v, state = stack.pop()
                if state == 0:
                    stack.append((v, 1))
                    for c in child.get(v, ()):
                        if c not in below and c not in on:
                            on.add(c)
                            stack.append((c, 0))
                else:
                    below[v] = 1 + max((below[c] for c in child.get(v, ()) if c in below), default=0)
                    on.discard(v)
        order = lambda v: (self._label(v), self.dup_rank.get(v, 0), v)  # noqa: E731
        pick = lambda c: (below[c], -self.dup_rank.get(c, 0), -self._label(c), -c)  # noqa: E731
        lanes, used, pending = [], set(), []

        def walk(start):
            nodes_, edges_ = [start], [into[start]]
            used.add(start)
            x = start
            while True:
                kids = [c for c in child.get(x, ()) if c not in used]
                if not kids:
                    break
                c = max(kids, key=pick)
                pending.extend(o for o in kids if o != c)
                nodes_.append(c)
                edges_.append(into[c])
                used.add(c)
                x = c
            lanes.append(_Lane(nodes_, edges_, E[into[start]].src))

        def drain():
            while pending:
                v = pending.pop()
                if v not in used:
                    walk(v)

        for r in sorted((v for v in nodes if v not in parent), key=order):
            walk(r)
            drain()
        # cycles: every remaining node lies on or hangs off a copy cycle
        for v in sorted((v for v in nodes if v not in used), key=order):
            if v in used:
                continue
            path, x, pos = [], v, {}
            while x not in pos and x not in used:
                pos[x] = len(path)
                path.append(x)
                x = parent[x]
            if x in used:
                continue
            cyc = path[pos[x]:]
            cyc.reverse()                            # parent -> child order
            cyc = self._cycle_start(cyc, into)
            used.update(cyc)
            lanes.append(_Lane(cyc, [into[c] for c in cyc], None, "cycle"))
        for v in sorted((v for v in nodes if v not in used), key=order):   # trees hanging off cycles
            if v in used:
                continue
            x = v
            while parent[x] not in used:
                x = parent[x]
            walk(x)
            drain()
        return lanes

    def _cycle_start(self, cyc, into):
        """Rotate a copy cycle to its stage 0: with an odd number of inverted edges (Johnson), the
        destination of the one logically inverted edge (raw inversion corrected by the stored reset
        values, since a flop that stores its bit inverted flips both its edges and its reset);
        with an even number (a ring), the one stage whose reset value, relative to the cycle,
        differs from all others; else the lowest structural label."""
        E = self.E
        n = len(cyc)
        inv = [E[into[v]].inv for v in cyc]            # inv[k]: edge into cyc[k]
        rv = [self.reset_of[v] for v in cyc]
        start = None
        if sum(inv) % 2:
            cand = [k for k in range(n) if inv[k]]
            if None not in rv:
                cand = [k for k in range(n) if inv[k] ^ rv[k - 1] ^ rv[k]]
            if len(cand) == 1:
                start = cand[0]
        elif None not in rv:
            acc, rel = 0, []
            for k in range(n):
                if k:
                    acc ^= inv[k]
                rel.append(rv[k] ^ acc)
            cnt = collections.Counter(rel)
            odd = [k for k in range(n) if cnt[rel[k]] == 1]
            if len(cnt) == 2 and len(odd) == 1:
                start = odd[0]
        if start is None:
            start = min(range(n), key=lambda k: (self._label(cyc[k]), cyc[k]))
        return cyc[start:] + cyc[:start]

    # ------------------------------------------------------------------ joint conditions
    def _cond_row(self, eids):
        row = self.ctl.live.copy()
        conds = [self.E[k].cond for k in eids if self.E[k].cond != 1]
        for r in self._rows(conds):
            row &= r
        return row

    def _need_lift(self, a, b):
        P = self.P
        return min(P["GROUP_LIFT"], P["GROUP_REL_LIFT"] * self.L / max(1, max(a, b)))

    def _repair(self, lanes, eids):
        """Give lanes shorter than the seed's longest lane their missing head or tail edge (see the
        module docstring): per round, each short lane offers its best-scoring extension (joint
        lanes kept, then lift); offers are accepted best first while the joint condition keeps
        its lanes. Unconditional edges never repair a conditional seed (they co-occur with
        everything). Returns (edge ids, edges added)."""
        P, E = self.P, self.E
        deep = [ln for ln in lanes if ln.depth >= 2 and ln.kind != "cycle"]
        if not deep:
            return eids, 0
        if len(deep) < 2:
            return eids, 0
        target = max(ln.depth for ln in deep)   # the longest lane: shorter ones lost an edge or two
        if not any(ln.depth < target for ln in lanes if ln.kind != "cycle"):
            return eids, 0
        cur = set(eids)
        G = self._cond_row([k for ln in deep for k in ln.edges if k is not None])
        nG = _pc(G)
        if nG < P["WITNESS_LANES"]:
            return eids, 0
        added = 0
        for _round in range(target):
            nodes = {v for ln in lanes for v in ln.nodes}
            heads = {}
            for ln in lanes:
                h = self._flop_of(ln.head) if ln.head is not None else None
                if h is not None:
                    heads.setdefault(h, ln)
            tails = {ln.nodes[-1]: ln for ln in lanes if ln.kind != "cycle"}
            props = []
            for ln in lanes:
                if ln.depth >= target or ln.kind == "cycle":
                    continue
                opts = []
                h = self._flop_of(ln.head) if ln.head is not None else None
                if h is not None and h not in nodes and self.eligible[h]:
                    for k in self.in_edges.get(h, ()):
                        j = self._flop_of(E[k].src)
                        if j is not None and j in nodes and j not in tails:
                            continue
                        other = tails.get(j) if j is not None else None
                        if ln.depth + 1 + (other.depth if other is not None else 0) > target:
                            continue
                        opts.append((k, h))
                t = ln.nodes[-1]
                for k in self.out_edges.get(self.ctl.flops[t].q, ()):
                    w = E[k].dst
                    if w in nodes or not self.eligible[w]:
                        continue
                    other = heads.get(w)
                    if ln.depth + 1 + (other.depth if other is not None else 0) > target:
                        continue
                    opts.append((k, w))
                opts = [(k, d) for k, d in opts if k not in cur and E[k].cls != self.uncond
                        and E[k].lanes >= P["WITNESS_LANES"]]
                if not opts:
                    continue
                conds = [E[k].cond for k, _d in opts]
                rowd = dict(zip(conds, self._rows(conds)))
                best = None
                for k, d in opts:
                    r = rowd[E[k].cond]
                    keep = _pc(G & r)
                    nT = _pc(r)
                    lift = keep * self.L / max(1, nG * nT)
                    if keep < max(P["WITNESS_LANES"], P["GROUP_KEEP"] * nG) or lift < self._need_lift(nG, nT):
                        continue
                    sc = (keep, lift, -self.ctl.labels[E[k].src], -k)
                    if best is None or sc > best[0]:
                        best = (sc, k, d)
                if best is not None:
                    props.append(best)
            if not props:
                break
            props.sort(key=lambda x: x[0], reverse=True)
            dsts, srcs, changed = set(), set(), False
            for _sc, k, d in props:
                e = E[k]
                if d in dsts or e.src in srcs:
                    continue
                r = self._row(e.cond)
                keep = _pc(G & r)
                if keep < max(P["WITNESS_LANES"], P["GROUP_KEEP"] * nG):
                    continue
                G = G & r
                nG = keep
                cur.add(k)
                dsts.add(d)
                srcs.add(e.src)
                added += 1
                changed = True
            if not changed:
                break
            lanes = self._lanes(sorted(cur))
            if all(ln.depth >= target for ln in lanes if ln.depth >= 2 and ln.kind != "cycle"):
                break
        self.stats["repair_edges"] += added
        return sorted(cur), added

    # ------------------------------------------------------------------ heads
    def _classify_heads(self, lanes, K, seed_nodes):
        """Head kinds under the seed's joint condition row K (see the module docstring)."""
        ctl, E = self.ctl, self.E
        P = self.P
        nK = _pc(K)
        for ln in lanes:
            if ln.kind == "cycle":
                continue
            h = ln.head
            if self.g.kind[h] in (INPUT, BBOX):
                ln.kind = "input"
                continue
            hf = self._flop_of(h)
            if hf is None:
                ln.kind = "input"
                continue
            if hf in seed_nodes:
                ln.kind = "tap"
                continue
            if ln.depth + 1 < P["SHIFT_MIN_DEPTH"] or nK == 0:
                ln.kind = "flop"
                continue
            if self._reads_under(hf, seed_nodes, K):
                ln.kind = "feedback"        # the head reads the seed's own stages: an LFSR candidate
                continue
            f_row, q_row = self._rows([ctl.f(hf), ctl.qlit(hf)])
            changes = _pc((f_row ^ q_row) & K)
            own = self._row(ctl.own_difference(hf))
            if _pc(own & K) or not changes or not self.eligible[hf]:
                ln.kind = "flop"            # holds, toggles or reads itself under the condition
                continue
            if not (f_row & K).any() or not (K & ~f_row).any():
                ln.kind = "const"           # loaded with one constant whenever the lane shifts
                ln.const = int(bool((f_row & K).any()))
            else:
                copies = False
                for k in self.in_edges.get(hf, ()):
                    e = E[k]
                    r = self._row(e.cond) if e.cond != 1 else ctl.live
                    if _pc(r & K) >= P["GROUP_KEEP"] * nK:
                        copies = True
                        break
                if copies:
                    ln.kind = "flop"        # a neighbour that copies at the same time
                    continue
                if not self._same_control(hf, ln.nodes[0]):
                    ln.kind = "flop"        # written under other controls: a separate register
                    continue
                ln.kind = "logic"
            ln.nodes.insert(0, hf)
            ln.edges.insert(0, None)
            ln.head = None
        return lanes

    def _same_control(self, a, b):
        """Two flops share clock, asynchronous controls and dominant control class (the grouping
        signature of section 3.2), a missing dominant counting as a value of its own."""
        return self.async_of[a] == self.async_of[b] and self.dom_of[a] == self.dom_of[b]

    def _compatible(self, a, b, ka, kb, group):
        """Consecutive stages a -> b (entered by edges ka, kb) may share a lane: same clock (root
        and edge); different asynchronous controls (clear / preset) only when both stages copy
        under the same exact copy condition class (one shift whose later stages have no reset,
        or another reset value: the async control is part of each stage's flop model and is
        reported per stage); and, in a copy group (conditions joined by co-occurrence only), not
        a change between exact classes where either class has >= 2 edges: an exact class is
        SAT-proven equality of conditions, so co-occurrence may join singleton classes (a one-hot
        mux gives every bit of one shift its own exact condition) but never lengthen or merge a
        lane an exact class already defines (a word register loading a serial register's byte)."""
        sa, sb = self.async_of[a], self.async_of[b]
        if sa[:2] != sb[:2]:
            return False
        if sa[2] != sb[2]:
            if ka is None or kb is None or self.E[ka].cls != self.E[kb].cls:
                return False
            self.stats["lanes_across_async_change"] += 1
        if not group or ka is None or kb is None:
            return True
        ca, cb = self.E[ka].cls, self.E[kb].cls
        return ca == cb or (len(self.by_cls[ca]) < 2 and len(self.by_cls[cb]) < 2)

    def _split_by_control(self, lanes, group=False):
        """Cut lanes between stages that are not compatible (_compatible): a shift's stages share
        their controls and copy under one condition; the next run's head is the previous run's
        last stage (a flop outside it)."""
        out = []
        for ln in lanes:
            if ln.kind == "cycle":
                if all(self._compatible(ln.nodes[k - 1], ln.nodes[k], ln.edges[k - 1], ln.edges[k], group)
                       for k in range(ln.depth)):
                    out.append(ln)
                else:
                    self.stats["cycles_mixed_control"] += 1
                continue
            start = 0
            for k in range(1, ln.depth + 1):
                if k == ln.depth or not self._compatible(ln.nodes[k - 1], ln.nodes[k], ln.edges[k - 1], ln.edges[k], group):
                    head = ln.head if start == 0 else self.ctl.flops[ln.nodes[start - 1]].q
                    part = _Lane(ln.nodes[start:k], ln.edges[start:k], head, ln.kind if start == 0 else None)
                    out.append(part)
                    if k < ln.depth:
                        self.stats["lanes_cut_by_control"] += 1
                    start = k
        return out

    def _feedback(self, ln, K):
        """Verdict on a feedback lane (its head flop reads the seed's own stages on lanes of K):
        "nonlinear" when, on K's lanes, the head's next state reads the lane's last stage (the loop
        closes over the whole lane) and is not GF(2)-affine in the lane's own flops (head
        included): for some pair (a, b) of them the second derivative f|00 ^ f|10 ^ f|01 ^ f|11 is
        1 on a K lane (every other signal as it is there: a concrete witness, no sampling claim);
        then the lane is a nonlinear feedback shift register (it may also read other flops, as a
        Grain-style NFSR reads its LFSR). Otherwise "affine" (an LFSR/CRC candidate: nonlinear, if
        at all, only in other signals), "open_loop" (the last stage is not read: no feedback
        register), "other_clock" or "budget". Returns (verdict, info)."""
        ctl, S, P = self.ctl, self.S, self.P
        hf = self._flop_of(ln.head)
        own = set(ln.nodes) | {hf}
        if self.async_of[hf][:2] != self.async_of[ln.nodes[0]][:2]:
            return "other_clock", {}
        deps = []
        for j in ctl.supp_flops[hf]:
            T, Ti = ctl.transparency(hf, ctl.flops[j].q)
            if ((self._row(T) | self._row(Ti)) & K).any():
                deps.append(j)
        outside = [j for j in deps if j not in own]
        info = {"reads": len(deps), "outside": len(outside)}
        if ln.nodes[-1] not in deps:
            return "open_loop", info
        mine = [j for j in deps if j in own]
        pairs = [(a, b) for x, a in enumerate(mine) for b in mine[x + 1:]]
        if len(pairs) > P["NLFSR_PAIRS_MAX"]:
            return "budget", info
        f = ctl.f(hf)
        cof = {}

        def c1(lit, j, v):
            key = (lit, j, v)
            if key not in cof:
                cof[key] = S.cofactor(lit, ctl.flops[j].q, v, {})
            return cof[key]
        for a, b in pairs:
            f0, f1 = c1(f, a, 0), c1(f, a, 1)
            d = S.lit_xor(S.lit_xor(c1(f0, b, 0), c1(f0, b, 1)), S.lit_xor(c1(f1, b, 0), c1(f1, b, 1)))
            if d == 0:
                continue
            if (self._row(d) & K).any():
                return "nonlinear", dict(info, witness_pair=[self.cell(a), self.cell(b)])
        return "affine", info

    def _reads_under(self, i, nodes, K):
        """f_i depends on some flop of `nodes` on a lane of K (Boolean difference, by lanes)."""
        ctl = self.ctl
        for j in ctl.supp_flops[i]:
            if j in nodes and j != i:
                T, Ti = ctl.transparency(i, ctl.flops[j].q)
                if (self._row(T) | self._row(Ti)).__and__(K).any():
                    return True
        return False

    # ------------------------------------------------------------------ candidates
    def _signature(self, ln, with_reset):
        E = self.E
        sig, acc = [], 0
        for v, k in zip(ln.nodes, ln.edges):
            if k is not None:
                acc ^= E[k].inv
            r = self.reset_of[v]
            sig.append(self.async_of[v] + ((None if r is None else r ^ acc) if with_reset else None,))
        return tuple(sig)

    def _candidates(self, key, eids):
        P = self.P
        lanes = self._lanes(eids)
        if not any(ln.depth >= 2 for ln in lanes):
            return []
        if key[0] != "unconditional":
            eids, _n = self._repair(lanes, eids)
            lanes = self._lanes(eids)
        lanes = self._split_by_control(lanes, key[0] == "copy_group")
        uncond = key[0] == "unconditional"
        out = []
        work = []
        for ln in lanes:
            if uncond and ln.kind != "cycle" and self.g.kind[ln.head] == INPUT:
                ln.kind = "input"
                self._sync_split(ln, work, out, key)
            else:
                work.append(ln)
        deep = [ln for ln in work if ln.depth + 1 >= P["SHIFT_MIN_DEPTH"]]
        if not deep:
            self._transfers(work, key)
            return out
        seed_nodes = {v for ln in lanes for v in ln.nodes}
        base = [k for ln in deep for k in ln.edges if k is not None]
        K = self._cond_row(base)
        todo = [ln for ln in work if ln.kind is None]
        self._classify_heads(todo, K, seed_nodes)
        groups = collections.defaultdict(list)
        for ln in work:
            if ln.kind == "feedback":
                if ln.depth + 1 >= P["SHIFT_MIN_DEPTH"]:
                    hf = self._flop_of(ln.head)
                    verdict, info = self._feedback(ln, K)
                    self.relations["feedback"].append({"head": self.cell(hf), "stages": [self.cell(v) for v in ln.nodes],
                                                       "verdict": verdict, **info})
                    self.stats[f"feedback_{verdict}"] += 1
                    if verdict == "nonlinear":
                        ln.nodes.insert(0, hf)
                        ln.edges.insert(0, None)
                        ln.head, ln.kind = None, "feedback_logic"
                        groups[(ln.depth, ln.kind, self._signature(ln, uncond))].append(ln)
                continue
            if ln.depth < P["SHIFT_MIN_DEPTH"]:
                self._transfers([ln], key)
                continue
            groups[(ln.depth, ln.kind, self._signature(ln, uncond))].append(ln)
        for gk in sorted(groups, key=lambda x: (-x[0] * len(groups[x]), x[0], x[1])):
            out.append({"kind": SHIFT, "lanes": groups[gk], "seed": key})
        return out

    def _sync_split(self, ln, work, out, key):
        """An unconditional copy path from a primary input: stages 1-2 a synchronizer lane, 1-2
        further stages delay relations, >= SHIFT_MIN_DEPTH further stages a shift lane."""
        P = self.P
        m = P["SYNC_MAX_STAGES"]
        if ln.depth < m:
            if ln.depth == 1:
                self.relations["input_register"].append(self.cell(ln.nodes[0]))
            return
        sync = _Lane(ln.nodes[:m], ln.edges[:m], ln.head, "input")
        out.append({"kind": SYNC, "lanes": [sync], "seed": key})
        rest = _Lane(ln.nodes[m:], ln.edges[m:], self.ctl.flops[ln.nodes[m - 1]].q, "flop")
        if rest.depth >= P["SHIFT_MIN_DEPTH"]:
            work.append(rest)
        else:
            for k, v in enumerate(rest.nodes):
                prev = ln.nodes[m - 1 + k]
                self.relations["delay"].append({"src": self.cell(prev), "dst": self.cell(v),
                                                "inv": int(self.E[rest.edges[k]].inv), "stage": m + k + 1})

    def _transfers(self, lanes, key):
        for ln in lanes:
            if ln.depth == 2 and ln.kind != "cycle" and key[0] != "unconditional":
                self.relations["transfer"].append([self.cell(v) for v in ln.nodes])

    def _merge_sync(self, cands):
        """Synchronizer lanes of the unconditional seed grouped by control signature."""
        sync = [c for c in cands if c["kind"] == SYNC]
        rest = [c for c in cands if c["kind"] != SYNC]
        by = collections.defaultdict(list)
        for c in sync:
            ln = c["lanes"][0]
            by[self._signature(ln, True)].append(ln)
        for sig in sorted(by, key=lambda s: (-len(by[s]), str(s))):
            rest.append({"kind": SYNC, "lanes": by[sig], "seed": ("unconditional",)})
        return rest

    # ------------------------------------------------------------------ selection
    def _select(self, cands):
        """Candidates in priority order (more flops, then unconditional, exact-class, group seeds,
        then labels), except that candidates over exactly the same flop set are ordered among
        themselves by the decomposition (SHIFT_DECIDE_TIES: deepest lanes, then fewest lanes; see
        _decide_ties), which moves no other candidate; each one disjoint from those taken is
        evaluated (_evaluate: joint cube and defining claims) and taken unless rejected. A candidate dropped for overlapping a taken one over the SAME flops is a
        second, equally true decomposition of that flop set (several condition classes; see the NEW
        THRESHOLDS block) and is reported as an "alternative_decomposition" relation."""
        def key(c):
            n = sum(ln.depth for ln in c["lanes"])
            seed_rank = {"unconditional": 0, "exact_class": 1, "copy_group": 2}[c["seed"][0]]
            lab = min(self._label(v) for ln in c["lanes"] for v in ln.nodes)
            return (-n, seed_rank, lab)

        order = sorted(cands, key=key)
        if self.P["SHIFT_DECIDE_TIES"]:
            order = self._decide_ties(order)
        chosen, taken = [], set()
        taken_sets = []
        for c in order:
            fl = {v for ln in c["lanes"] for v in ln.nodes}
            if fl & taken:
                self.stats["candidates_overlapping"] += 1
                if fl in taken_sets:
                    self._alternative(c)
                continue
            ev = self._evaluate(c)
            if ev is None:
                continue
            taken |= fl
            taken_sets.append(fl)
            chosen.append((c, ev))
        return self._adopt(chosen)

    def _decide_ties(self, order):
        """Candidates over exactly the SAME flop set are the same structure read through different
        condition classes (a barrel rotate: one lane of depth 8 under "rotate by 1", two lanes of
        depth 4 under "rotate by 2"); they carry the same flops, the same seed kind and the same
        structural labels, so the sort above leaves them in whatever order the class sweep produced
        and the reading changes with the gate mapping. Within each such group -- and only there, so
        no other candidate's position moves -- put the deepest lanes first, then the fewest lanes,
        then keep the sort's own order. Nothing else about the selection changes."""
        groups = collections.defaultdict(list)
        for i, c in enumerate(order):
            groups[frozenset(v for ln in c["lanes"] for v in ln.nodes)].append(i)
        out = list(order)
        for _fl, idxs in groups.items():
            if len(idxs) < 2:
                continue
            picked = sorted((order[i] for i in idxs),
                            key=lambda c: (-max(ln.depth for ln in c["lanes"]), len(c["lanes"])))
            for pos, c in zip(idxs, picked):
                out[pos] = c
            self.stats["tie_groups_decided"] += 1
        return out

    def _alternative(self, c):
        """A decomposition of an already taken flop set that another condition class supports: true
        of the netlist, but not the reading the structure reports (lanes / depth / serial_in / order
        would all be the other one's). Reported so the ambiguity is visible instead of silent."""
        self.stats["alternative_decompositions"] += 1
        self.relations["alternative_decomposition"].append(
            {"flops": sorted(self.cell(v) for ln in c["lanes"] for v in ln.nodes),
             "lanes": len(c["lanes"]), "depth": c["lanes"][0].depth, "seed": list(c["seed"]),
             "order": [[self.cell(v) for v in ln.nodes] for ln in c["lanes"]],
             "condition_lanes": _pc(self._cond_row([k for ln in c["lanes"] for k in ln.edges if k is not None]))})

    def _adopt(self, chosen):
        """Merge chosen shift structures that are lanes of one shift: equal depth, head kind and
        stage controls, and joint conditions that co-occur as copy groups require (the merged
        condition keeps >= GROUP_KEEP of the smaller one's lanes, >= WITNESS_LANES, with the pair
        lift); the merge stands only if it has a joint cube itself. (Seeds are heuristic: a lane
        the repair could not complete in its group can come out whole from another seed.)"""
        P = self.P
        while True:
            merged = False
            shifts = [k for k, (c, _ev) in enumerate(chosen) if c["kind"] == SHIFT]
            for x in range(len(shifts)):
                for y in range(x + 1, len(shifts)):
                    a, b = chosen[shifts[x]][0], chosen[shifts[y]][0]
                    la, lb = a["lanes"], b["lanes"]
                    if la[0].depth != lb[0].depth or {ln.kind for ln in la} != {ln.kind for ln in lb}:
                        continue
                    if [self.async_of[v] for v in la[0].nodes] != [self.async_of[v] for v in lb[0].nodes]:
                        continue
                    ra = self._cond_row([k for ln in la for k in ln.edges if k is not None])
                    rb = self._cond_row([k for ln in lb for k in ln.edges if k is not None])
                    na, nb, both = _pc(ra), _pc(rb), _pc(ra & rb)
                    lift = both * self.L / max(1, na * nb)
                    if both < max(P["WITNESS_LANES"], P["GROUP_KEEP"] * min(na, nb)) or lift < self._need_lift(na, nb):
                        continue
                    c = {"kind": SHIFT, "lanes": [_Lane(ln.nodes, ln.edges, ln.head, ln.kind) for ln in la + lb],
                         "seed": a["seed"]}
                    for new, old in zip(c["lanes"], la + lb):
                        new.const = old.const
                    ev = self._evaluate(c)
                    if ev is None or len(c["lanes"]) != len(la) + len(lb):
                        continue
                    self.stats["structures_merged"] += 1
                    keep = [t for k, t in enumerate(chosen) if k not in (shifts[x], shifts[y])]
                    chosen = keep + [(c, ev)]
                    merged = True
                    break
                if merged:
                    break
            if not merged:
                return chosen

    def _order_lanes(self, c):
        """Lane order: along the copy chain through the heads when the heads form one (a serial
        front end feeding a parallel shift: a structural order); else no structural key orders
        the lanes: c["lanes_unordered"] (with more than one lane) and a listing by structural
        labels (stage by stage, then the head's), remaining ties in canonical flop order."""
        lanes = c["lanes"]
        c["lanes_unordered"] = False
        E = self.E
        heads = {}
        for k, ln in enumerate(lanes):
            if ln.head is not None and self._flop_of(ln.head) is not None:
                heads[self._flop_of(ln.head)] = k
        if len(heads) == len(lanes) and len(lanes) > 1:
            nxt = {}
            ok = True
            for h in heads:
                for k in self.in_edges.get(h, ()):
                    j = self._flop_of(E[k].src)
                    if j in heads and j != h and E[k].cls != self.uncond:
                        if j in nxt and nxt[j] != h:
                            ok = False
                        nxt.setdefault(j, h)
            if ok:
                start = [h for h in heads if h not in set(nxt.values())]
                if len(start) == 1:
                    chain, x, seen = [], start[0], set()
                    while x is not None and x not in seen:
                        seen.add(x)
                        chain.append(x)
                        x = nxt.get(x)
                    if len(chain) == len(heads):
                        c["lanes"] = [lanes[heads[h]] for h in chain]
                        c["lane_order"] = "head_chain"
                        return
        lab = self.ctl.labels

        def key(ln):
            head = lab[ln.head] if ln.head is not None and ln.head < len(lab) else -1
            return (tuple(self._label(v) for v in ln.nodes), head, ln.nodes[0])
        c["lanes"] = sorted(lanes, key=key)
        c["lane_order"] = "none (labels)" if len(lanes) > 1 else "one lane"
        c["lanes_unordered"] = len(lanes) > 1

    # ------------------------------------------------------------------ cubes and claims
    def _assignment_at(self, lane):
        V, w, b = self.ctl.V, lane >> 6, np.uint64(lane & 63)
        return lambda s: int((V[s, w] >> b) & _ONE)

    def _assignment_of(self, a):
        V1 = np.zeros((self.ctl.n, 1), np.uint64)
        for s, v in a.items():
            if v and s < self.ctl.n:
                V1[s, 0] = ALL1
        self.ctl.sim.eval(V1)
        return lambda s: int(V1[s, 0] & _ONE)

    def _witnesses(self, row, lit, n):
        """Up to n assignments where lit holds with the reset inactive: live lanes spread over the
        row (lanes in word order), else one SAT witness."""
        idx = np.flatnonzero(row)
        if len(idx):
            lanes = []
            for w in idx[np.linspace(0, len(idx) - 1, min(n, len(idx))).astype(np.int64)]:
                v = int(row[w])
                lanes.append(64 * int(w) + ((v & -v).bit_length() - 1))
            for lane in dict.fromkeys(lanes):
                yield self._assignment_at(lane)
            return
        if lit == 1:
            lane = _first_lane(self.ctl.live)
            if lane is not None:
                yield self._assignment_at(lane)
            return
        st, a = self.ctl.witness(lit)
        self.stats["cube_sat_witnesses"] += 1
        if st == "sat":
            yield self._assignment_of(a)

    def _side_inputs(self, pairs, own=()):
        """Base signals feeding the gates on paths from the sources into the destinations' next
        states (not themselves reading a source), expanded through net-less gates. `own`: the
        structure's own state signals; gates reading them belong to the paths too, so no side
        input (no cube literal) reads the structure's own state (schema v2: a condition that
        reads the word's own bits could carve the defining case down to where it happens to hold)."""
        g = self.g
        idx = g._source_index()
        mask = 0
        for s in [s for s, _i in pairs] + list(own):
            if s in idx:
                mask |= 1 << idx[s]
        srcs = {s for s, _i in pairs} | set(own)
        region = set()
        for _s, i in pairs:
            gates, _leaves = g.cone([self.ctl.f(i)])
            for x in gates:
                if g.supp_bits(x) & mask:
                    region.add(x)
        side = set()
        stack = []
        for r in region:
            for x in g.fanin[r]:
                if x not in region and x not in srcs:
                    stack.append(x)
        for i in {i for _s, i in pairs}:          # a destination whose next state is a source literal
            s = self.ctl.f(i) >> 1
            if s not in region and s not in srcs and s != 0:
                stack.append(s)
        net = self.ctl._net
        seen = set()
        while stack:
            x = stack.pop()
            if x in seen or x == 0:
                continue
            seen.add(x)
            if g.kind[x] == GATE and 2 * x not in net:
                stack.extend(g.fanin[x])
            else:
                side.add(x)                      # a net-carried signal or a source
        return sorted(side, key=lambda x: (-int(g.level[x]), self.ctl.labels[x], x))

    def _miter(self, triples, zero=()):
        """Scratch literal: some destination differs from its claimed value (flop, value literal),
        or some literal of `zero` is 1."""
        S = self.S
        acc = 0
        for i, v in triples:
            acc = S.lit_or(acc, S.lit_xor(self.ctl.f(i), v))
        for z in zero:
            acc = S.lit_or(acc, z)
        return acc

    def _miter_row(self, triples, zero=()):
        ctl = self.ctl
        lits = []
        for i, v in triples:
            lits += [ctl.f(i), v]
        rows = [ctl.value(l) for l in lits]
        acc = np.zeros(ctl.W, np.uint64)
        for k in range(0, len(rows), 2):
            acc |= rows[k] ^ rows[k + 1]
        for z in zero:
            acc |= ctl.value(z)
        return acc

    def _implies(self, cube, miter):
        """SAT: the cube (base literals) forces miter = 0: True, False (with cex) or None."""
        ok, cex = self._sat([miter], 0b01, cube, limit=self.P["SAT_LIMIT"])
        return ok, cex

    def _cube(self, triples, cond_lit, cond_row, extra_pairs=(), zero=(), own=()):
        """A cube of net literals implying every (flop, value) pair and zeroing every literal of
        `zero` (see the module docstring), or None. triples: [(flop index, value literal over
        sources)]; extra_pairs: more (source, flop) paths whose side inputs the cube may use (a
        logic stage 0 and its own state). Witnesses of the joint condition (live lanes spread over
        its row, at most CASE_WITNESSES) each give a side-input cube K0 that must imply the pairs
        (SAT); K0 is reduced (_reduce). The smallest of the first CASE_CAP cubes wins (a one-hot
        state's cube is small, a multi-hot junk state's large)."""
        pairs = [(v >> 1, i) for i, v in triples if v > 1] + list(extra_pairs)
        side = self._side_inputs(pairs, own)
        miter = self._miter(triples, zero)
        if not side:
            ok, _c = self._implies([], miter)
            return [] if ok else None
        mrow = self._miter_row(triples, zero)
        best, found = None, 0
        for val in self._witnesses(cond_row, cond_lit, self.P["CASE_WITNESSES"]):
            k0 = [2 * x + (1 - val(x)) for x in side]
            ok, _c = self._implies(k0, miter)
            if not ok:
                self.stats["cube_witness_rejected"] += 1
                continue
            cube = self._reduce(k0, miter, mrow)
            if cube is None:
                continue
            found += 1
            if best is None or len(cube) < len(best):
                best = cube
            if found >= self.P["CASE_CAP"]:
                break
        if best is None:
            self.stats["cube_none"] += 1
        return best

    def _reduce(self, K0, miter, mrow):
        """K0 reduced greedily against the lanes (a literal goes when no lane satisfying the rest
        breaks the miter), then SAT: each counterexample puts back every K0 literal it falsifies,
        until SAT agrees; K0 itself when that fails. None when even K0 exceeds the COND budget."""
        ctl = self.ctl
        V, W = ctl.V, ctl.W
        base_rows = {}

        def lrow(l):
            r = base_rows.get(l)
            if r is None:
                r = V[l >> 1, :W]
                r = ~r if l & 1 else r.copy()
                base_rows[l] = r
            return r

        def excluded(cube):
            row = np.full(W, ALL1)
            for l in cube:
                row &= lrow(l)
            return not (row & mrow).any()

        cur = list(K0)
        for l in list(K0):
            t = [x for x in cur if x != l]
            if excluded(t):
                cur = t
        for _round in range(self.P["CASE_WITNESSES"]):
            ok, cex = self._implies(cur, miter)
            if ok:
                if len(cur) <= _COND_MAX:
                    return cur
                break
            if ok is None:
                break
            ev = self._assignment_of(cex)
            back = [l for l in K0 if l not in cur and not (ev(l >> 1) ^ (l & 1))]
            self.stats["cube_counterexamples"] += 1
            if not back:
                break
            cur += back
        self.stats["cube_fallback_full"] += 1
        return K0 if len(K0) <= _COND_MAX else None

    def _value_lit(self, e):
        return 2 * e.src + e.inv

    def _src_expr(self, s, inv):
        ctl = self.ctl
        if s in self.g.q2flop:
            e = {"q": self.cell(self.g.q2flop[s])}
        else:
            hit = ctl._net.get(2 * s)
            if hit is None:
                return None
            net, ninv = hit
            e = {"net": int(net)}
            inv ^= ninv
        return {"not": e} if inv else e

    def _expr_sources(self, lit):
        """EXPR of a literal expanded down to sources (or-of-ands per gate), or ctl.expr past the
        node budget."""
        S, ctl = self.S, self.ctl
        memo = {}
        budget = [0]

        def rec(l):
            s, inv = l >> 1, l & 1
            if s == 0:
                return {"const": inv}
            if s not in memo:
                budget[0] += 1
                if budget[0] > _EXPR_NODES:
                    raise OverflowError
                if S.kind[s] != GATE:
                    e = self._src_expr(s, 0)
                    if e is None:
                        raise OverflowError
                else:
                    k = len(S.fanin[s])
                    terms = []
                    for cube in isop(S.tt[s], k):
                        lits = [rec(2 * S.fanin[s][v] + (1 - b)) for v, b in cube]
                        terms.append(lits[0] if len(lits) == 1 else {"and": lits})
                    e = terms[0] if len(terms) == 1 else {"or": terms}
                memo[s] = e
            e = memo[s]
            return {"not": e} if inv else e

        try:
            return rec(lit)
        except (OverflowError, RecursionError):
            return ctl.expr(lit)

    def _check(self, i, value_lit, cube):
        """Verify one claim as the harness does: next(i) == value under the cube, cube satisfiable."""
        ok, _c = self._sat([self.ctl.f(i), value_lit], _TT_EQ, cube)
        if not ok:
            return ok
        if cube:
            sat_, _c = self._sat([cube[0]], _TT_NEVER, cube)
            if sat_ is not False:
                return None if sat_ is None else False
        return True

    def _async_inactive(self, flops):
        """Literals (scratch graph) that hold when every asynchronous clear / preset of `flops` is
        inactive (constant controls left out)."""
        out = []
        for i in flops:
            fl = self.ctl.flops[i]
            for a in (fl.clear, fl.preset):
                if a > 1 and (a ^ 1) not in out:
                    out.append(a ^ 1)
        return out

    def _stage_share(self, copy_edges, K):
        """None when every conditional copy edge copies under the joint condition row K on
        >= SHIFT_STAGE_SHARE of its own lanes (see the module docstring); else the worst
        (share, edge lanes). An edge is judged only where the rule's share of its lanes is at
        least CONTROL_EVIDENCE lanes (fewer lanes are no evidence either way)."""
        P = self.P
        worst = None
        for k in copy_edges:
            e = self.E[k]
            if e.cond == 1:
                continue
            r = self._row(e.cond)
            n = _pc(r)
            if n * P["SHIFT_STAGE_SHARE"] < P["CONTROL_EVIDENCE"]:
                continue
            sh = _pc(r & K) / n
            if sh < P["SHIFT_STAGE_SHARE"] and (worst is None or sh < worst[0]):
                worst = (sh, n)
        return worst

    def _claim(self, i, expr, cond, role):
        return {"type": "next", "flop": self.cell(i), "equals": expr, "when": cond, "role": role}

    def _evaluate(self, c):
        """The joint cube and the defining claims of a candidate, or None when it is rejected
        (no cube makes every stage copy at once: not one condition). A logic or constant stage 0
        whose next state under the cube still reads itself, or is not the claimed value, is no
        stage: such heads are then dropped from every lane and the candidate is evaluated again."""
        ctl, E, S, g = self.ctl, self.E, self.S, self.g
        self._order_lanes(c)
        for _attempt in range(2):
            lanes = c["lanes"]
            if any(ln.depth < (self.P["SYNC_MAX_STAGES"] if c["kind"] == SYNC else self.P["SHIFT_MIN_DEPTH"])
                   for ln in lanes):
                self.stats["rejected_too_short"] += 1
                return None
            copy_edges = [k for ln in lanes for k in ln.edges if k is not None]
            cond_lit = 1
            for k in copy_edges:
                if E[k].cond != 1:
                    cond_lit = S.lit_and(cond_lit, E[k].cond)
            cond_row = self._cond_row(copy_edges)
            share = self._stage_share(copy_edges, cond_row)
            if share is not None:
                self.stats["rejected_stage_share"] += 1
                return None
            triples = [(E[k].dst, self._value_lit(E[k])) for k in copy_edges]
            heads = [ln for ln in lanes if ln.edges and ln.edges[0] is None]
            triples += [(ln.nodes[0], ln.const) for ln in heads if ln.const is not None]
            extra = [(ctl.flops[ln.nodes[0]].q, ln.nodes[0]) for ln in heads]
            # a logic stage 0 must not read itself under the cube (else it is a register of its own);
            # an NLFSR's stage 0 may (its feedback can read every stage, stage 0 included)
            zero = [ctl.own_difference(ln.nodes[0]) for ln in heads if ln.const is None and ln.kind != "feedback_logic"]
            idx = g._source_index()
            if c["kind"] == SYNC:
                # no condition: the copies hold always, or whenever the synchronous reset is inactive
                cube = None
                miter = self._miter(triples)
                for k_sync in ([], [self.rho ^ 1] if self.rho is not None else None):
                    if k_sync is not None and self._implies(k_sync, miter)[0] is True:
                        cube = k_sync
                        break
            else:
                own = [ctl.flops[v].q for ln in lanes for v in ln.nodes]
                cube = self._cube(triples, cond_lit, cond_row, extra, zero, own) if triples else []
            if cube is None:
                self.stats["rejected_no_joint_cube"] += 1
                return None
            logic_claims, bad = [], False
            cond = ctl.cond(cube) if cube else []
            for ln in lanes:
                if not ln.edges or ln.edges[0] is not None:
                    continue
                h = ln.nodes[0]
                lit = ln.const if ln.const is not None else S.substitute(ctl.f(h), {l >> 1: 1 ^ (l & 1) for l in cube})
                reads_self = bool((S.supp_bits(lit >> 1) >> idx[ctl.flops[h].q]) & 1) and ln.kind != "feedback_logic"
                if reads_self or cond is None or not self._check(h, lit, cube):
                    bad = True
                    break
                logic_claims.append((h, lit))
            if not bad:
                break
            self.stats["logic_heads_dropped"] += 1
            for ln in lanes:
                if ln.edges and ln.edges[0] is None:
                    h = ln.nodes.pop(0)
                    ln.edges.pop(0)
                    ln.head, ln.kind, ln.const = ctl.flops[h].q, "flop", None
        else:
            return None
        claims, defined, refuted = [], set(), False
        if cond is None:
            self.stats["claims_without_nets"] += 1
            return None
        quiet = self._async_inactive([v for ln in lanes for v in ln.nodes])
        if quiet:
            unsat, _c = self._sat([quiet[0]], _TT_NEVER, list(cube) + quiet)
            if unsat is not False:          # the cube needs an asynchronous control active (or unknown)
                self.stats["rejected_cube_needs_async"] += 1
                return None
        for k in copy_edges:
            e = E[k]
            expr = self._src_expr(e.src, e.inv)
            if expr is None:
                self.stats["claims_without_nets"] += 1
                continue
            ok = self._check(e.dst, self._value_lit(e), cube)
            if ok:
                claims.append(self._claim(e.dst, expr, cond, "defining"))
                defined.add(e.dst)
            elif ok is False:
                refuted = True
                self.stats["claims_refuted"] += 1
        for h, lit in logic_claims:
            expr = {"const": lit} if lit in (0, 1) else self._expr_sources(lit)
            claims.append(self._claim(h, expr, cond, "defining"))
            defined.add(h)
        self.stats["cube_literals_max"] = max(self.stats["cube_literals_max"], len(cube))
        return {"claims": claims, "defined": defined, "refuted": refuted, "cube": cond, "cube_lits": list(cube),
                "condition_lanes": _pc(cond_row)}

    def _hold_reset_claims(self, flops):
        ctl = self.ctl
        out = []
        rho = self.rho
        for i in flops:
            pr = ctl.profile[i]
            prev = []
            for (L, kind), proven in zip(pr.steps, pr.proven):
                if kind == "h" and proven:
                    cube = ([rho ^ 1] if rho is not None else []) + [l ^ 1 for l in prev] + [L]
                    cond = ctl.cond(cube)
                    if cond is not None and len(cube) <= _COND_MAX and self._check(i, ctl.qlit(i), cube):
                        out.append(self._claim(i, {"q": self.cell(i)}, cond, "hold"))
                prev.append(L)
            if rho is not None and ctl.reset.values.get(i) is not None:
                v = int(ctl.reset.values[i])
                cond = ctl.cond([rho])
                if cond is not None and self._check(i, v, [rho]):
                    out.append(self._claim(i, {"const": v}, cond, "reset"))
        return out

    def _loads(self, c):
        """Parallel loads: classes or groups copying outside sources into >= GROUP_KEEP of the
        structure's flops, at most CASE_CAP of them, each with its own cube and load claims."""
        ctl, E, P = self.ctl, self.E, self.P
        fl = [v for ln in c["lanes"] for v in ln.nodes]
        fset = set(fl)
        own = {k for ln in c["lanes"] for k in ln.edges if k is not None}
        qs = {ctl.flops[v].q for v in fl}
        by = collections.defaultdict(dict)
        for v in fl:
            for k in self.in_edges.get(v, ()):
                e = E[k]
                if k in own or e.src in qs or e.cls == self.uncond:
                    continue
                by[("exact_class",) + e.cls[1:]].setdefault(v, k)
        ref2k = {e.ref: k for k, e in enumerate(E) if e.ref is not None}
        for gi, grp in enumerate(ctl.copy_groups):
            hit = {}
            for r in grp["edges"]:
                k = ref2k.get(r)
                if k is None:
                    continue
                e = E[k]
                if e.dst in fset and k not in own and e.src not in qs:
                    hit.setdefault(e.dst, k)
            if len(hit) >= 2:
                by[("copy_group", gi)] = hit
        cands = [(key, m) for key, m in by.items() if len(m) >= max(2, P["GROUP_KEEP"] * len(fl))]
        cands.sort(key=lambda x: (-len(x[1]), x[0]))
        loads, claims, covered = [], [], set()
        for key, m in cands:
            if len(loads) >= P["CASE_CAP"]:
                break
            sig = frozenset(m.items())
            if sig in covered:
                continue
            covered.add(sig)
            ks = sorted(m.values())
            row = self._cond_row(ks)
            if _pc(row) == 0:
                continue
            cl = 1
            for k in ks:
                if E[k].cond != 1:
                    cl = self.S.lit_and(cl, E[k].cond)
            triples = [(E[k].dst, self._value_lit(E[k])) for k in ks]
            cube = self._cube(triples, cl, row, own=[ctl.flops[v].q for v in fl])
            if cube is None:
                continue
            cond = ctl.cond(cube)
            if cond is None:
                continue
            got = []
            for k in ks:
                e = E[k]
                expr = self._src_expr(e.src, e.inv)
                if expr is not None and self._check(e.dst, self._value_lit(e), cube):
                    got.append(self._claim(e.dst, expr, cond, "load"))
            if got:
                claims += got
                loads.append({"flops": len(got), "condition": cond, "condition_lanes": _pc(row), "cube": list(cube),
                              "sources": [[self.cell(E[k].dst), self._src_expr(E[k].src, E[k].inv)] for k in ks]})
        return loads, claims

    # ------------------------------------------------------------------ output
    def _emit(self, c, ev, idx):
        E, ctl = self.E, self.ctl
        lanes = c["lanes"]
        order = [[self.cell(v) for v in ln.nodes] for ln in lanes]
        flops = [x for lane in order for x in lane]
        fl_idx = [v for ln in lanes for v in ln.nodes]
        claims, defined = ev["claims"], ev["defined"]
        extra = self._hold_reset_claims(fl_idx)
        loads, load_claims = ([], []) if c["kind"] == SYNC else self._loads(c)
        all_claims = claims + extra + load_claims
        if ev["refuted"]:
            status = "failed"
        elif all(v in defined for v in fl_idx) and claims:
            status = "proven"
        else:
            status = "unknown"
        serial = []
        for ln in lanes:
            if ln.kind == "cycle":
                serial.append(self.cell(ln.nodes[-1]))
            elif ln.head is not None and self._flop_of(ln.head) is not None:
                serial.append(self.cell(self._flop_of(ln.head)))
            else:
                serial.append(None)
        control = self._control(c, ev, fl_idx, extra, loads)
        heads = collections.Counter(ln.kind for ln in lanes)
        # per-stage inversion, in the shape of "order": inverted[lane][k] = 1 when the edge into
        # stage k stores the complement of stage k-1 (stage 0: of its head). The harness's shift and
        # synchronizer templates allow an inverted copy edge and report the edges they found
        # inverted (verify.py); the claims below already carry it (_src_expr negates the source), so
        # this states per stage what "inverted_edges" only counted. The schema's PARAMS does not list
        # it yet (review[1] minor 7 asks the lead for the wording); an extra result param is ignored
        # by the scorer, which reads the truth's params, and by the harness, which builds the
        # templates from kind + order.
        inverted = [[int(E[k].inv) if k is not None else 0 for k in ln.edges] for ln in lanes]
        notes = {"head_kind": sorted(heads)[0] if len(heads) == 1 else sorted(heads),
                 "condition_lanes": ev["condition_lanes"], "seed": list(c["seed"]),
                 "lane_order": c.get("lane_order"),
                 "loads": [{k: v for k, v in ld.items() if k != "cube"} for ld in loads],
                 "reset_cases_named": len(control["reset"] or []),
                 "load_cases_named": len(control["load"] or []),
                 "inverted_edges": sum(E[k].inv for ln in lanes for k in ln.edges if k is not None),
                 "inverted_stages": inverted,
                 "stage_async": self._stage_async(fl_idx)}
        unordered = bool(c.get("lanes_unordered"))
        if c["kind"] == SYNC:
            params = {"stages": lanes[0].depth, "order": order, "lanes_unordered": unordered,
                      "inverted": inverted}
        else:
            params = {"lanes": len(lanes), "depth": lanes[0].depth, "direction": None,
                      "serial_in": serial, "order": order, "lanes_unordered": unordered,
                      "inverted": inverted}
        self.stats[f"claims_{c['kind']}"] += len(all_claims)
        return {"id": f"{c['kind']}#{idx}", "kind": c["kind"], "flops": flops, "order": order,
                "params": params, "control": control,
                "proof": {"status": status, "claims": all_claims,
                          "defining_flops": len(defined), "flops": len(fl_idx), "notes": notes}}

    def _clear_cases(self, fl_idx, taken, nload, quiet, cap):
        """Further synchronous reset cases for a shift structure: netted literals under which EVERY
        flop of the structure takes a constant (each its own, so a clear and a constant preload are
        both cases), checked outside every load case and outside the cases already taken. Candidates
        come from the control layer's own R cover (profile[i].sets: the literals that force a flop's
        next state to a constant), by how many of the structure's flops they cover, then by lanes,
        then by structural label. A candidate that reads the structure's own state is skipped: it
        would put the harness's coverage obligation on the case, and a clear that depends on the
        shifted data is not a clear. Returns [(base literal, {flop cell: 0|1})]."""
        ctl, S = self.ctl, self.S
        cnt = collections.Counter()
        for i in fl_idx:
            for L, _v in ctl.profile[i].sets:
                if L in (0, 1) or L in taken or (L ^ 1) in taken:
                    continue
                cnt[L] += 1
        if not cnt:
            return []
        idx = S._source_index()
        own = 0
        for i in fl_idx:
            own |= 1 << idx[ctl.flops[i].q]
        cands = [L for L in cnt if not (S.supp_bits(L >> 1) & own) and ctl.cond([L]) is not None]
        cands.sort(key=lambda L: (-cnt[L], -_pc(self._row(L)), ctl.labels[L >> 1], L))
        ntaken = [t ^ 1 for t in taken]
        out = []
        for L in cands[:self.P["CASE_CAP"] * 2]:
            if len(out) >= cap:
                break
            cube = [L] + ntaken + list(nload) + quiet
            if len(cube) > _COND_MAX:
                continue
            vals, ok = {}, True
            for i in fl_idx:
                got = None
                for v in (0, 1):
                    if self._check(i, v, cube) is True:
                        got = v
                        break
                if got is None:
                    ok = False
                    break
                vals[self.cell(i)] = got
            if ok:
                out.append((L, vals))
                self.stats["clear_case"] += 1
        return out

    def _control(self, c, ev, fl_idx, extra, loads):
        """structure["control"] in schema v2.1 (see the module docstring): control.reset is a LIST of
        {"when": COND, "value": {flop: 0|1}} cases and control.load a LIST of CONDs, and control.hold
        means "outside EVERY named case".

        The cases are named in the order a shift register uses them and only while the hold
        obligation still fails: the synchronous reset first (it is CHECKED by the harness), then the
        parallel-load cases _loads found (opaque, one at a time, widest first), then further clear
        cases (_clear_cases, checked again). Each reset case's COND carries the complements of the
        single-literal cases before it, so the else-if priority is explicit and no two cases can
        disagree on a state; the region every obligation is proven on is built from THOSE literal
        lists, so what is proven here is what the harness will state. A hold region that is empty --
        the named cases cover every state, which is what an unconditional shift register looks like,
        and what a shift that either shifts or loads looks like -- is reported as hold true: schema
        v2.1 accepts and reports it (the harness's hold_vacuous and load_hidden_share say how much
        the load cases hide), where v2.0 left hold false and the structure was refused outright."""
        ctl, S = self.ctl, self.S
        cube = ev["cube_lits"]
        quiet = self._async_inactive(fl_idx)
        cells = [self.cell(v) for v in fl_idx]
        when_lit = 1
        for l in cube:
            when_lit = S.lit_and(when_lit, l)
        miter = self._miter([(i, ctl.qlit(i)) for i in fl_idx])
        resets = []                       # [(base literals, {flop cell: 0|1})]
        reset_vals = {}
        for cl in extra:
            if cl["role"] == "reset":
                reset_vals[cl["flop"]] = int(cl["equals"]["const"])
        if self.rho is not None and fl_idx and len(reset_vals) == len(fl_idx):
            resets.append(([self.rho], {x: reset_vals[x] for x in cells}))
        use_loads = []

        def case_lits(i, rs):
            return list(rs[i][0]) + [r[0][0] ^ 1 for r in rs[:i] if len(r[0]) == 1]

        def off(rs, lds):
            """Literals meaning "outside every named reset case" and "outside every load case"."""
            out = []
            for i in range(len(rs)):
                a = 1
                for l in case_lits(i, rs):
                    a = S.lit_and(a, l)
                out.append(a ^ 1)
            for ld in lds:
                a = 1
                for l in ld["cube"]:
                    a = S.lit_and(a, l)
                out.append(a ^ 1)
            return out

        def hold_of(rs, lds):
            """True (proven), "vacuous" (the named cases cover every state: accepted and reported by
            the harness), or False (not proven, or unknown)."""
            assume = [when_lit ^ 1] + quiet + off(rs, lds)
            unsat, _c = self._sat([assume[0]], _TT_NEVER, assume)
            if unsat is True:
                return "vacuous" if self.P["HOLD_VACUOUS"] else False
            if unsat is not False:
                return False
            ok, _c = self._implies(assume, miter)
            return ok is True

        hold = hold_of(resets, use_loads)
        # the load cases, widest first, only while the word still does not hold
        for ld in (loads if c["kind"] != SYNC else []):
            if hold is not False:
                break
            if ld["condition"] is None or len(use_loads) >= self.P["CASE_CAP"]:
                break
            use_loads.append(ld)
            hold = hold_of(resets, use_loads)
        # further clear cases
        if hold is False and c["kind"] != SYNC:
            taken = [r[0][0] for r in resets if len(r[0]) == 1]
            nload = [l for l in off(resets, use_loads)[len(resets):]]
            for L, vals in self._clear_cases(fl_idx, taken, nload, quiet,
                                             self.P["SHIFT_RESET_CASES"] - len(resets)):
                resets.append(([L], vals))
                hold = hold_of(resets, use_loads)
                if hold is not False:
                    break
        if hold is False and use_loads:
            # they hid states and bought nothing: a load case is opaque, so naming one that does not
            # close the hold obligation only keeps the harness from looking, and the structure is
            # refused for hold either way. Name none.
            self.stats["loads_dropped"] += len(use_loads)
            use_loads = []
        # emit: the CONDs decide the harness's regions, so re-prove every case against exactly them
        reset_out = []
        for i in range(len(resets)):
            cond = ctl.cond(case_lits(i, resets))
            if cond is None:
                reset_out = None
                break
            reset_out.append({"when": cond, "value": {str(x): int(resets[i][1][x]) for x in cells}})
        if reset_out is None or not self._reset_cases_ok(resets, case_lits, fl_idx,
                                                         off(resets, use_loads)[len(resets):], quiet):
            self.stats["reset_case_dropped"] += len(resets)
            resets, reset_out = [], []
            hold = hold_of(resets, use_loads)
        load_out = [ld["condition"] for ld in use_loads]
        out = {"when": ev["cube"], "reset": reset_out or None, "load": load_out or None,
               "hold": hold is not False, "input": None, "inputs": []}
        if c["kind"] == SYNC:
            # a synchronizer has no condition: when = [] (its cube may only restate the synchronous
            # reset's inactive value, checked in _evaluate), a synchronous reset stays a reset case
            out["when"], out["hold"], out["load"] = [], False, None
            nets = []
            for ln in c["lanes"]:
                hit = ctl._net.get(2 * ln.head) if ln.head is not None else None
                nets.append(int(hit[0]) if hit is not None else None)
            out["input"] = nets[0] if len(nets) == 1 else nets
        self.stats["hold_vacuous"] += int(hold == "vacuous")
        return out

    def _reset_cases_ok(self, rs, case_lits, fl_idx, nload, quiet):
        """Every reset case's obligation as the harness states it: under the case's EMITTED COND and
        outside every load case, each flop takes that case's value, and the case is satisfiable
        there. Re-proved on the final list because a case named earlier is part of a later case's
        COND, and dropping one would widen the others' regions."""
        for i in range(len(rs)):
            cube = case_lits(i, rs) + list(nload) + quiet
            if len(cube) > _COND_MAX:
                return False
            for v in fl_idx:
                if self._check(v, int(rs[i][1][self.cell(v)]), cube) is not True:
                    return False
        return True
    def _stage_async(self, fl_idx):
        """{flop id: "clear" | "preset" | "clear+preset"} for the stages with an asynchronous
        control. It belongs in proof["notes"], not in structure["control"]: the harness's control
        keys are exactly verify.CONTROL_KEYS and an unknown key makes the whole structure malformed
        (schema v2, tightened 2026-09-22), so every shift with an async-reset stage was thrown away
        before this. The async controls are part of each stage's flop model and the harness applies
        them itself; this is a diagnostic."""
        ctl = self.ctl
        out = {}
        for v in fl_idx:
            fl = ctl.flops[v]
            kinds = [n for n, a in (("clear", fl.clear), ("preset", fl.preset)) if a > 1]
            if kinds:
                out[str(self.cell(v))] = "+".join(kinds)
        return out

    def run(self):
        t0 = time.perf_counter()
        self._prepare()
        seeds = self._seeds()
        self.stats["seeds"] = len(seeds)
        self.timings["prepare"] = time.perf_counter() - t0
        t1 = time.perf_counter()
        cands = []
        for key, eids in seeds:
            got = self._candidates(key, eids)
            cands += got
        cands = self._merge_sync(cands)
        self.stats["candidates"] = len(cands)
        self.timings["candidates"] = time.perf_counter() - t1
        t2 = time.perf_counter()
        chosen = self._select(cands)
        chosen.sort(key=lambda x: (x[0]["kind"] != SYNC, min(self._label(v) for ln in x[0]["lanes"] for v in ln.nodes)))
        structures = [self._emit(c, ev, k) for k, (c, ev) in enumerate(chosen)]
        self.timings["claims"] = time.perf_counter() - t2
        self.stats["structures"] = len(structures)
        self.stats["proven"] = sum(1 for s in structures if s["proof"]["status"] == "proven")
        self.stats["sat_calls"] = self.sat_calls
        rel = {k: v for k, v in self.relations.items()}
        pos = {int(f.cell): i for i, f in enumerate(self.ctl.flops)}   # canonical flop index (ids carry no order)
        rel["delay"] = sorted(rel["delay"], key=lambda r: (r["stage"], self._label(pos[r["dst"]]), pos[r["dst"]]))
        self.timings["total"] = time.perf_counter() - t0
        return {"structures": structures, "relations": rel, "stats": dict(self.stats),
                "timings": {k: round(v, 3) for k, v in self.timings.items()}}


def find(ctl, params=None):
    """Shift registers and synchronizers of an analysed netlist (see the module docstring)."""
    return ShiftRecognizer(ctl, params).run()


def recognize(nl, params=None):
    """Stand-alone result: the control layer, then this recognizer only (no other kinds)."""
    from tools.s3 import controls
    ctl_params = {k: v for k, v in (params or {}).items()}
    t0 = time.perf_counter()
    ctl = controls.analyze(nl, ctl_params)
    t1 = time.perf_counter()
    out = find(ctl)
    groups = [list(s["flops"]) for s in out["structures"]]
    meta = {"recognizer": "shift", "relations": out["relations"], "stats": out["stats"],
            "controls": {"live_lanes": int(_pc(ctl.live)), "copy_edges": len(ctl.copy_edges)}}
    meta["seconds_controls"] = round(t1 - t0, 2)
    return {"schema": RESULT_SCHEMA, "structures": out["structures"], "groups": groups, "meta": meta}
