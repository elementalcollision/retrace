"""S3 recognizer entry point: the control layer once, the structure recognizers, overlap
resolution, then word grouping, as one result (schema retrace-s3-result/1).

Contract (enforced by the harness and by the S3 tests): recognize(nl, params=None) takes an
anonymous netlist and returns a result dict; every flop id is a cell index of `nl`.
"""

# Pipeline (S3 design sections 3.1-3.8):
#   1. controls.analyze(nl): lanes, reset, control classes, profiles, copy relations, blocks.
#   2. shift.find, counter.find, lfsr.find on that one control layer, in this order. lfsr.find adds
#      case-witness lanes to the shared layer, so it runs after the two recognizers that were
#      developed on the bare layer. Each recognizer's structures are pairwise disjoint; a crash in
#      one recognizer is recorded in meta and the others still run. Every parameter (tools.s3.params,
#      which holds every threshold of every module) reaches every recognizer through ctl.P.
#   3. Overlaps between recognizers: a flop claimed by several structures goes to the structure the
#      harness would verify, then to the one explaining more flops, then to the more specific model
#      (lfsr_crc, counter, shift_register, synchronizer: a Fibonacci LFSR's stages are also copies),
#      then to recognizer output order. "Would verify" is KindCheck: schema v2's kind-bound rules
#      (the harness builds the defining templates from kind + order + params; the recognizer gives
#      the conditions in structure["control"], and an lfsr_crc its XOR claims), mirrored on a
#      private GateGraph of the same netlist with SAT alone under the harness's conflict limit. The
#      harness also has affine and BDD checks that SAT lacks, and models gated clocks, so a check
#      the mirror cannot decide (a conflict limit, a clock that is logic) ranks below a verified one
#      and above a refuted one when the recognizer itself proved the structure. Losers are dropped
#      whole and listed in meta with the structures they lost to.
#   4. group.group(ctl, fixed=...): the chosen structures are fixed words. A synchronizer structure
#      of several lanes is fixed one word per stage (the flops of stage k across its lanes): a
#      synchronized bus is usually one register per stage. A one-lane synchronizer stays one word
#      (the usual two-bit shift idiom).
#   5. The result: chosen structures plus the grouping's formed words (data_register, flag,
#      register_file_word, with their claims), groups = the grouping's partition of every flop.
#
# Timings and peak memory are volatile, so they stay out of the result (a fixed permutation must
# give a byte-identical result); they go to stderr as one JSON line, which the harness keeps in
# its run record.

from __future__ import annotations

import collections
import gc
import json
import resource
import sys
import time
import traceback

import numpy as np

from tools.s3 import controls, counter, group, lfsr, shift
from tools.s3 import params as _params
from tools.s3.netlist import BBOX, FLOP, FREE, INPUT, GateGraph, Sat, tt_of

RESULT_SCHEMA = "retrace-s3-result/1"
STRUCTURE_KINDS = ("shift_register", "counter", "lfsr_crc", "synchronizer")

# Tie-break between equally verified structures of equal size: the more specific model first.
KIND_RANK = {"lfsr_crc": 0, "counter": 1, "shift_register": 2, "synchronizer": 3}

# The harness's published limits (tools.s3.params HARNESS_*, mirrored from verify.py; not tuning).
CHECK_CONFLICTS = _params.HARNESS_CONFLICTS
CHECK_EXPR_NODES = _params.HARNESS_EXPR_NODES
CHECK_EXPR_DEPTH = _params.HARNESS_EXPR_DEPTH
CHECK_COND_LITERALS = _params.HARNESS_COND_LITERALS
CHECK_SHIFT_MIN_DEPTH = _params.HARNESS_SHIFT_MIN_DEPTH
CHECK_RESET_CASES = _params.HARNESS_RESET_CASES_MAX
CHECK_LOAD_CASES = _params.HARNESS_LOAD_CASES_MAX
LEGACY_CONTROL_FORM = _params.HARNESS_LEGACY_CONTROL_FORM
_AND2, _OR2, _XOR2 = 0b1000, 0b1110, 0b0110
_MUX = tt_of(lambda x: x[1] if x[0] else x[2], 3)   # x0 ? x1 : x2
_XOR3 = tt_of(lambda x: x[0] ^ x[1] ^ x[2], 3)
_MAJ = tt_of(lambda x: int(x[0] + x[1] + x[2] >= 2), 3)
_TT_EQ, _TT_NEVER = 0b1001, 0
_CLOCK_SOURCES = (INPUT, BBOX, FLOP)
COLLECT_BETWEEN_STAGES = True


# ----------------------------------------------------------------------------------------------
# parameters


def split_params(params=None):
    """Route overrides: every threshold is a tools.s3.params entry, so every override goes to the
    control layer (and so to every recognizer through ctl.P) and to the grouping. An unknown name,
    or a change to a NOT_PER_RUN value, is an error."""
    P = dict(params or {})
    _params.resolve(P)
    return {"controls": P, "counter": {}, "lfsr": {}, "group": dict(P)}


# ----------------------------------------------------------------------------------------------
# the harness's kind-bound check (schema v2), mirrored


def _as_id(x):
    """An opaque id as the harness reads it: an int (not bool) or its canonical ASCII decimal."""
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x if 0 <= x < 10 ** 18 else None
    if isinstance(x, str) and x.isascii() and x.isdigit() and (x == "0" or x[0] != "0") and len(x) <= 18:
        return int(x)
    return None


class _Bad(ValueError):
    """Malformed for the harness: never verified."""


class _No(Exception):
    """Not verified: refuted or ruled out (unknown=False), or undecided by the mirror (unknown=True)."""

    def __init__(self, reason, unknown=False):
        super().__init__(reason)
        self.reason, self.unknown = reason, unknown


class KindCheck:
    """Schema v2 verdicts for the structures an overlap involves, as the harness (tools.s3.verify)
    gives them:
    the defining templates built from kind + order + params (counter: w' = w +/- step modulo
    params.modulus or saturating, over the word's range, control.inverted bits complemented, the
    down case under control.when_down; shift_register: stage k' = stage k-1 in lanes of one depth
    >= 3; synchronizer: no condition, stage 0' = control.input, stage k' = stage k-1; lfsr_crc: the
    claims, each an XOR of own q's, control.inputs nets independent of the own state, and
    constants, not a partial permutation), under control.when & ~reset & ~load with every async
    control of the structure's flops inactive; hold and the reset case when claimed; every case
    satisfiable; no condition reading the structure's own state; one clock root and edge.
    structure(s) -> (True | False | None, reason); None: the mirror cannot decide (the SAT conflict
    limit, or a clock that is logic, which the harness models as an enable and this mirror does
    not). Built lazily on its own GateGraph, so the control layer's graphs are never touched."""

    def __init__(self, nl):
        self.nl = nl
        g = self.g = GateGraph(nl)
        for n in range(nl.n_nets):
            g.resolve(n)
        g.n = len(g.kind)
        for k in ("fanout", "sources", "_supp", "_srcidx"):
            g.__dict__.pop(k, None)
        g.supp_bits(0)
        self.src_index = g._source_index()
        self.sat = Sat(g)
        self.flop_at = {f.cell: f for f in g.flops}
        self.stats = collections.Counter()

    # --- parsing -----------------------------------------------------------------------------------
    def _flop(self, x):
        i = _as_id(x)
        if i is None or i not in self.flop_at:
            raise _Bad("not a flop id")
        return self.flop_at[i]

    def _net(self, x):
        i = _as_id(x)
        if i is None or i >= self.nl.n_nets:
            raise _Bad("not a net id")
        return self.g.lit_of_net[i]

    def _cond(self, cond):
        if not isinstance(cond, list) or len(cond) > CHECK_COND_LITERALS:
            raise _Bad("COND is not a list within the limits")
        out = []
        for c in cond:
            if not isinstance(c, dict) or set(c) != {"net", "value"} or isinstance(c["value"], bool) \
                    or c["value"] not in (0, 1):
                raise _Bad("COND conjunct is not {net, value}")
            lit = self._net(c["net"])
            out.append(lit if c["value"] == 1 else lit ^ 1)
        return out

    def _lanes(self, s, kind, flops, params):
        pkey = "bit_order" if kind in ("counter", "lfsr_crc") else "order"

        def norm(o):
            if o is None:
                return None
            if not isinstance(o, list) or not o:
                raise _Bad("an order must be a non-empty list")
            lanes = o if all(isinstance(l, list) for l in o) else [o]
            out = [[_as_id(x) for x in lane] for lane in lanes]
            if any(not lane or None in lane for lane in out) or sorted(i for l in out for i in l) != sorted(flops):
                raise _Bad("an order is not a permutation of the structure's flops")
            return out

        order, porder = norm(s.get("order")), norm(params.get(pkey))
        if order is None:
            order = porder
        elif porder is not None and porder != order:
            raise _No(f"order and params.{pkey} disagree")
        if order is None and kind != "lfsr_crc":
            raise _No("no order: the harness builds the templates from it")
        return order

    # --- building and solving ------------------------------------------------------------------------
    def _tree(self, tt, lits, unit):
        lits = list(lits)
        if not lits:
            return unit
        while len(lits) > 1:
            nxt = [self.g.mk(tt, [lits[i], lits[i + 1]]) for i in range(0, len(lits) - 1, 2)]
            if len(lits) % 2:
                nxt.append(lits[-1])
            lits = nxt
        return lits[0]

    def _land(self, lits):
        return self._tree(_AND2, lits, 1)

    def _region(self, lits):
        lits = sorted(set(lits))
        if 0 in lits or any((l ^ 1) in lits for l in lits):
            return None
        return [l for l in lits if l != 1]

    def _sat(self, region):
        """'sat' | 'unsat' | 'unknown': is the region satisfiable?"""
        r = self._region(region)
        if r is None:
            return "unsat"
        if not r:
            return "sat"
        self.stats["sat_calls"] += 1
        ok, _cex = self.sat.check([r[0]], _TT_NEVER, assume=r, limit=CHECK_CONFLICTS)
        return "unknown" if ok is None else "unsat" if ok else "sat"

    def _holds(self, region, a, b):
        """'holds' | 'refuted' | 'unknown': a == b under the region."""
        if a == b:
            return "holds"
        r = self._region(region)
        if r is None:
            return "holds"
        self.stats["sat_calls"] += 1
        ok, _cex = self.sat.check([a, b], _TT_EQ, assume=r, limit=CHECK_CONFLICTS)
        return "unknown" if ok is None else "holds" if ok else "refuted"

    def _nonvacuous(self, name, region):
        r = self._sat(region)
        if r == "unsat":
            raise _No(f"vacuous: the {name} case")
        if r != "sat":
            raise _No(f"unknown: non-vacuity of the {name} case", unknown=True)

    def _obligations(self, name, region, pairs, polarity=False):
        for f, a, b in pairs:
            r = self._holds(region, a, b)
            if r == "refuted" and polarity:
                r = self._holds(region, a, b ^ 1)
            if r == "unknown":
                raise _No(f"unknown (conflict limit): the {name} template of flop {f}", unknown=True)
            if r != "holds":
                raise _No(f"refuted: the {name} template of flop {f}")

    # --- a structure ------------------------------------------------------------------------------------
    def structure(self, s):
        try:
            return self._structure(s)
        except _Bad as e:
            return False, f"malformed: {e}"
        except _No as e:
            return (None if e.unknown else False), e.reason
        except Exception as e:  # noqa: BLE001  (a structure the mirror cannot read ranks as undecided)
            return None, f"mirror error: {type(e).__name__}: {str(e)[:200]}"

    def _structure(self, s):
        if not isinstance(s, dict):
            raise _Bad("a structure must be an object")
        kind = s.get("kind")
        if kind not in STRUCTURE_KINDS:
            return False, "unscored kind: never verified"
        fl = s.get("flops")
        if not isinstance(fl, list) or not fl:
            raise _Bad("flops must be a non-empty list")
        flops = [self._flop(x).cell for x in fl]
        if len(set(flops)) != len(flops):
            raise _Bad("a flop is listed twice")
        params = s.get("params") if s.get("params") is not None else {}
        c = s.get("control") if s.get("control") is not None else {}
        if not isinstance(params, dict) or not isinstance(c, dict):
            raise _Bad("params and control must be objects")
        lanes = self._lanes(s, kind, flops, params)
        F = [self.flop_at[f] for f in flops]
        doms = set()
        for f in F:
            if self.g.kind[f.clk_root] not in _CLOCK_SOURCES:
                raise _No("a clock that is logic (the harness models it as an enable; this mirror does not)",
                          unknown=True)
            doms.add((f.clk_root, f.clk_inv))
        if len(doms) != 1:
            raise _No("the structure's flops are in several clock domains")
        self.flops, self.fset = flops, set(flops)
        self.pos = {f: i for i, f in enumerate(flops)}
        self.own_mask = 0
        for f in F:
            self.own_mask |= 1 << self.src_index[f.q]
        when = self._cond([] if c.get("when") is None else c["when"])
        resets = self._reset_cases(c)            # [(COND literals, {flop: 0|1})] in priority order
        loads = self._load_cases(c)              # [COND literals]
        when_down = self._cond(c["when_down"]) if kind == "counter" and c.get("when_down") is not None else None
        hold = c.get("hold", False)
        hold = False if hold is None else hold
        if not isinstance(hold, bool):
            raise _Bad("control.hold must be true or false")
        named = [("when", when), ("when_down", when_down)]
        named += [(f"reset[{i}]", l) for i, (l, _v) in enumerate(resets)]
        named += [(f"load[{i}]", l) for i, l in enumerate(loads)]
        for name, lits in named:
            if lits and any(self.g.supp_bits(l >> 1) & self.own_mask for l in lits):
                raise _No(f"self-conditioned: control.{name} reads the structure's own state")
        self.when, self.resets, self.loads, self.when_down = when, resets, loads, when_down
        self.async_off = sorted({a ^ 1 for f in F for a in (f.clear, f.preset) if a})
        # "outside every named case", as schema v2.1 and tools/s3/verify.py read it
        self.n_r = self._land([self._land(l) ^ 1 for l, _v in resets])
        self.n_l = self._land([self._land(l) ^ 1 for l in loads])
        if kind == "counter":
            self._counter(lanes[0], params, c, hold)
        elif kind == "shift_register":
            self._shift(lanes, params, hold)
        elif kind == "synchronizer":
            self._sync(lanes, params, c, hold)
        else:
            self._lfsr(s, c, hold)
        return True, "verified"

    def _values(self, x, what):
        vals = {}
        if not isinstance(x, dict):
            raise _Bad(f"{what} must be an object {{flop id: 0 | 1}}")
        for k, y in x.items():
            i = _as_id(k)
            if i is None or i not in self.fset or isinstance(y, bool) or y not in (0, 1):
                raise _Bad(f"{what} is not {{flop of the structure: 0 | 1}}")
            vals[i] = y
        if len(vals) != len(self.fset):
            raise _Bad(f"{what} misses a flop of the structure")
        return vals

    def _reset_cases(self, c):
        """control.reset -> [(COND literals, {flop: 0|1})] in the list's own (priority) order, as the
        harness module reads it. Schema v2.1 gives a list of {"when": COND, "value": {...}}; the v2.0
        bare COND with control.reset_value beside it is accepted while LEGACY_CONTROL_FORM is on."""
        r = c.get("reset")
        if r is None:
            if c.get("reset_value") is not None:
                raise _Bad("control.reset_value without control.reset")
            return []
        if not isinstance(r, list):
            raise _Bad("control.reset must be null or a list of reset cases")
        if not r:
            return []
        if all(isinstance(e, dict) and set(e) >= {"net", "value"} for e in r):
            if not LEGACY_CONTROL_FORM:
                raise _Bad("control.reset is a bare COND: schema v2.1 wants a list of cases")
            return [(self._cond(r), self._values(c.get("reset_value"), "control.reset_value"))]
        if len(r) > CHECK_RESET_CASES:
            raise _Bad(f"control.reset has more than {CHECK_RESET_CASES} cases")
        out = []
        for e in r:
            if not isinstance(e, dict) or set(e) - {"when", "value"} or "value" not in e:
                raise _Bad('a reset case must be {"when": COND, "value": {flop id: 0 | 1}}')
            out.append((self._cond([] if e.get("when") is None else e["when"]),
                        self._values(e["value"], "a reset case's value")))
        if c.get("reset_value") is not None:
            raise _Bad("control.reset_value belongs to the v2.0 form: a v2.1 case carries its own value")
        return out

    def _load_cases(self, c):
        """control.load -> [COND literals] (v2.1 a list of CONDs; v2.0's bare COND while legacy)."""
        l = c.get("load")
        if l is None:
            return []
        if not isinstance(l, list):
            raise _Bad("control.load must be null or a list of load cases")
        if not l:
            return []
        if all(isinstance(e, dict) and "net" in e for e in l):
            if not LEGACY_CONTROL_FORM:
                raise _Bad("control.load is a bare COND: schema v2.1 wants a list of CONDs")
            return [self._cond(l)]
        if len(l) > CHECK_LOAD_CASES:
            raise _Bad(f"control.load has more than {CHECK_LOAD_CASES} cases")
        return [self._cond(e) for e in l]

    def _def_region(self, dom=()):
        return list(self.when) + [self.n_r, self.n_l] + self.async_off + list(dom)

    def _hold_reset(self, hold, extra_off=(), dom=()):
        flops = self.flops   # the structure's own order (ids carry no order)
        if hold:
            region = [self._land(self.when) ^ 1] + list(extra_off) + [self.n_r, self.n_l] + self.async_off + list(dom)
            if 0 not in region:
                self._obligations("hold", region, [(f, self.flop_at[f].ns, 2 * self.flop_at[f].q) for f in flops])
        # each reset case on its own cube, with the EARLIER cases and every load case removed, so the
        # list order is priority and the union of the named cases is covered exactly once, as the
        # harness module does it
        for i, (lits, rv) in enumerate(self.resets):
            earlier = [self._land(l) ^ 1 for l, _v in self.resets[:i]]
            region = list(lits) + earlier + [self.n_l] + self.async_off + list(dom)
            self._nonvacuous(f"reset[{i}]", region)
            self._obligations(f"reset[{i}]", region, [(f, self.flop_at[f].ns, rv[f]) for f in flops])

    # --- templates ----------------------------------------------------------------------------------------
    def _add_const(self, bits, K, n):
        g = self.g
        out, cy = [], 0
        for i in range(n):
            a = bits[i] if i < len(bits) else 0
            kb = (K >> i) & 1
            out.append(g.mk(_XOR3, [a, kb, cy]))
            cy = g.mk(_MAJ, [a, kb, cy])
        return out

    def _ge_const(self, bits, K):
        if K <= 0:
            return 1
        if K >> len(bits):
            return 0
        ge = 1
        for i, b in enumerate(bits):
            ge = self.g.mk(_AND2, [b, ge]) if (K >> i) & 1 else self.g.mk(_OR2, [b, ge])
        return ge

    def _mux_word(self, sel, x, y):
        return [self.g.mk(_MUX, [sel, a, b]) for a, b in zip(x, y)]

    def _counter(self, lane, params, c, hold):
        w = len(lane)
        if len(self.fset) != w:
            raise _No("a counter has one lane")
        d = params.get("direction")
        if d not in ("up", "down", "updown"):
            raise _No("params.direction is not up, down or updown")
        step = 1 if params.get("step") is None else params.get("step")
        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            raise _No("params.step must be a positive integer")
        M = params.get("modulus")
        if M is not None and (isinstance(M, bool) or not isinstance(M, int) or not 2 <= M <= 1 << w):
            raise _No("params.modulus must be an integer in [2, 2^width]")
        sat = params.get("saturating")
        sat = False if sat is None else sat
        if isinstance(sat, bool):
            top = M - 1 if M is not None else (1 << w) - 1
        elif isinstance(sat, int) and 1 <= sat < 1 << w:
            top, sat = sat, True
        else:
            raise _No("params.saturating must be true, false or the saturation value")
        if not sat:
            M = 1 << w if M is None else M
            top = M - 1
            if step >= M:
                raise _No("params.step must be below the modulus")
        inv = set()
        for x in c.get("inverted") or []:
            i = _as_id(x)
            if i is None or i not in self.fset:
                raise _Bad("control.inverted names a flop outside the structure")
            inv.add(i)
        val = [2 * self.flop_at[f].q ^ (f in inv) for f in lane]
        nxt = [self.flop_at[f].ns ^ (f in inv) for f in lane]
        dom = [] if top == (1 << w) - 1 else [self._ge_const(val, top + 1) ^ 1]
        if sat:
            up_sum = self._add_const(val, step, w + 1)
            up = self._mux_word(self._ge_const(up_sum, top + 1), [(top >> i) & 1 for i in range(w)], up_sum[:w])
            down = self._mux_word(self._ge_const(val, step) ^ 1, [0] * w, self._add_const(val, (1 << w) - step, w))
        elif M == 1 << w:
            up = self._add_const(val, step, w)
            down = self._add_const(val, (1 << w) - step, w)
        else:
            s1 = self._add_const(val, step, w + 1)
            up = self._mux_word(self._ge_const(s1, M), self._add_const(s1, (1 << (w + 1)) - M, w + 1)[:w], s1[:w])
            down = self._mux_word(self._ge_const(val, step) ^ 1, self._add_const(val, M - step, w),
                                  self._add_const(val, (1 << w) - step, w))
        main = down if d == "down" else up
        region = self._def_region(dom)
        self._nonvacuous("when", region)
        extra_off, down_region = [], None
        if d == "updown" and self.when_down is not None:
            down_region = list(self.when_down) + [self._land(self.when) ^ 1, self.n_r, self.n_l] + self.async_off + dom
            self._nonvacuous("when_down", down_region)
            extra_off = [self._land(self.when_down) ^ 1]
        self._obligations("defining", region, [(f, nxt[i], main[i]) for i, f in enumerate(lane)])
        if down_region is not None:
            self._obligations("defining_down", down_region, [(f, nxt[i], down[i]) for i, f in enumerate(lane)])
        self._hold_reset(hold, extra_off, dom)

    def _shift(self, lanes, params, hold):
        depth = {len(l) for l in lanes}
        if len(depth) != 1:
            raise _No("shift lanes of unequal depth")
        d = depth.pop()
        if d < CHECK_SHIFT_MIN_DEPTH:
            raise _No(f"shift depth {d} < {CHECK_SHIFT_MIN_DEPTH}")
        for k, want in (("depth", d), ("lanes", len(lanes))):
            if params.get(k) is not None and params.get(k) != want:
                raise _No(f"params.{k} disagrees with the order")
        region = self._def_region()
        self._nonvacuous("when", region)
        pairs = [(l[k], self.flop_at[l[k]].ns, 2 * self.flop_at[l[k - 1]].q) for l in lanes for k in range(1, d)]
        self._obligations("defining", region, pairs, polarity=True)
        self._hold_reset(hold)

    def _sync(self, lanes, params, c, hold):
        depth = {len(l) for l in lanes}
        if len(depth) != 1:
            raise _No("synchronizer lanes of unequal depth")
        d = depth.pop()
        if params.get("stages") is not None and params.get("stages") != d:
            raise _No("params.stages disagrees with the order")
        if self.when:
            raise _No("a synchronizer has no condition: control.when must be empty")
        if self.loads:
            raise _No("a synchronizer has no load case")
        inp = c.get("input")
        if inp is None:
            raise _No("control.input is missing")
        inps = inp if isinstance(inp, list) else [inp]
        if len(inps) != len(lanes):
            raise _Bad("control.input does not give one net per lane")
        g = self.g
        dom = (self.flop_at[lanes[0][0]].clk_root, self.flop_at[lanes[0][0]].clk_inv)
        heads = []
        for x in inps:
            lit = self._net(x)
            sg = lit >> 1
            k = g.kind[sg]
            ok = k in (INPUT, BBOX) or (k == FREE and (g.info[sg] or ("",))[0] == "latch")
            if k == FLOP:
                f = g.flops[g.q2flop[sg]]
                ok = f.cell not in self.fset and g.kind[f.clk_root] in _CLOCK_SOURCES \
                    and (f.clk_root, f.clk_inv) != dom
            if not ok:
                raise _No("the synchronizer input is not a primary input, black-box output, latch output or "
                          "flop of another clock domain")
            heads.append(lit)
        region = self._def_region()
        self._nonvacuous("when", region)
        pairs = []
        for l, h in zip(lanes, heads):
            pairs.append((l[0], self.flop_at[l[0]].ns, h))
            pairs += [(l[k], self.flop_at[l[k]].ns, 2 * self.flop_at[l[k - 1]].q) for k in range(1, d)]
        self._obligations("defining", region, pairs, polarity=True)
        self._hold_reset(hold)

    def _lfsr(self, s, c, hold):
        g = self.g
        inputs = c.get("inputs") or []
        if not isinstance(inputs, list):
            raise _Bad("control.inputs must be a list of net ids")
        in_lit, in_pos = {}, {}
        for x in inputs:
            lit = self._net(x)
            if _as_id(x) in in_lit:
                raise _Bad("control.inputs lists a net twice")
            if g.supp_bits(lit >> 1) & self.own_mask:
                raise _No("a control.inputs net depends on the structure's own state")
            in_lit[_as_id(x)] = lit
            in_pos[_as_id(x)] = len(in_pos)
        claims = (s.get("proof") or {}).get("claims") if isinstance(s.get("proof"), dict) else None
        if not isinstance(claims, list):
            raise _No("no claims: an lfsr_crc gives each flop's next state")
        wset = {(_as_id(x.get("net")), x.get("value")) for x in (c.get("when") or []) if isinstance(x, dict)}
        forms = {}
        for cl in claims:
            if not isinstance(cl, dict) or cl.get("type") != "next":
                raise _Bad("an lfsr_crc claim must be {type: next, flop, equals}")
            if cl.get("role", "defining") != "defining":
                continue
            f = self._flop(cl.get("flop")).cell
            if f not in self.fset or f in forms:
                raise _Bad("a defining claim names a flop outside the structure, or one flop twice")
            cw = cl.get("when")
            if cw and {(_as_id(x.get("net")), x.get("value")) for x in cw if isinstance(x, dict)} != wset:
                raise _No("an lfsr_crc claim's own 'when' differs from control.when")
            if "equals" not in cl:
                raise _Bad("claim without 'equals'")
            forms[f] = self._xor_form(cl["equals"], in_lit)
        if any(f not in forms for f in self.flops):
            raise _No("a flop has no defining claim")
        if max(len(forms[f][0]) for f in self.flops) < 2:
            raise _No("the own-bit matrix is a (partial) permutation: a shift or copy, not an LFSR")
        region = self._def_region()
        self._nonvacuous("when", region)
        pairs = []
        for f in self.flops:
            own, ins, k = forms[f]
            leaves = [2 * self.flop_at[x].q for x in sorted(own, key=self.pos.get)] + \
                [in_lit[x] for x in sorted(ins, key=in_pos.get)]
            pairs.append((f, self.flop_at[f].ns, self._tree(_XOR2, leaves, 0) ^ k))
        self._obligations("defining", region, pairs)
        self._hold_reset(hold)

    def _xor_form(self, e, in_lit):
        own, ins, k = set(), set(), 0
        stack, n = [(e, 0)], 0
        while stack:
            x, d = stack.pop()
            n += 1
            if n > CHECK_EXPR_NODES or d > CHECK_EXPR_DEPTH:
                raise _Bad("EXPR over the size limits")
            if not isinstance(x, dict) or len(x) != 1:
                raise _Bad("EXPR is not a one-key object")
            (op, a), = x.items()
            if op == "q":
                f = self._flop(a).cell
                if f not in self.fset:
                    raise _No("an lfsr_crc EXPR reads a flop outside the structure")
                own ^= {f}
            elif op == "net":
                i = _as_id(a)
                if i is None or i not in in_lit:
                    raise _No("an lfsr_crc EXPR reads a net not in control.inputs")
                ins ^= {i}
            elif op == "const":
                if isinstance(a, bool) or a not in (0, 1):
                    raise _Bad("const is not 0 or 1")
                k ^= a
            elif op == "not":
                k ^= 1
                stack.append((a, d + 1))
            elif op == "xor" and isinstance(a, list) and a:
                stack.extend((y, d + 1) for y in a)
            elif op in ("and", "or"):
                raise _No("an lfsr_crc EXPR is not an XOR of own q's, inputs and constants")
            else:
                raise _Bad("unknown EXPR operator")
        return own, ins, k


ClaimCheck = KindCheck   # the name this module used before schema v2


# ----------------------------------------------------------------------------------------------
# overlaps


def _flop_set(s):
    return {i for i in (_as_id(x) for x in s.get("flops") or []) if i is not None}


def _tier(verdict, s):
    """0: the mirrored harness check verifies; 1: the mirror cannot decide (a conflict limit, a
    gated clock) and the recognizer proved the structure itself; 2: otherwise (refuted, malformed,
    ruled out by the kind-bound rules, or undecided and not proven by its recognizer)."""
    if verdict is True:
        return 0
    if verdict is None and (s.get("proof") or {}).get("status") == "proven":
        return 1
    return 2


def resolve_overlaps(nl, found, checker=None):
    """found: [(recognizer, structure)] in output order. Returns (kept [(recognizer, structure)] in
    output order, losers [meta record], checked {index: (verdict, reason)}, checker). Only
    structures that share a flop with another structure are checked (KindCheck) and ranked; the
    rest are kept unchecked (each recognizer proves its own structures before calling them
    proven)."""
    fl = [_flop_set(s) for _, s in found]
    holders = collections.defaultdict(list)
    for k, fs in enumerate(fl):
        for f in fs:
            holders[f].append(k)
    involved = sorted({k for ks in holders.values() if len(ks) > 1 for k in ks})
    if not involved:
        return list(found), [], {}, checker
    if checker is None:
        checker = ClaimCheck(nl)
    checked = {k: checker.structure(found[k][1]) for k in involved}

    def rank(k):
        s = found[k][1]
        return (_tier(checked[k][0], s), -len(fl[k]), KIND_RANK.get(s.get("kind"), len(KIND_RANK)), k)

    taken, owner, drop, losers = set(), {}, set(), []
    for k in sorted(involved, key=rank):
        clash = fl[k] & taken
        if not clash:
            taken |= fl[k]
            for f in fl[k]:
                owner[f] = k
            continue
        drop.add(k)
        rec, s = found[k]
        winners = sorted({owner[f] for f in clash})     # indices in output order
        losers.append({"id": s.get("id"), "kind": s.get("kind"), "recognizer": rec, "n_flops": len(fl[k]),
                       "flops": list(s.get("flops") or []), "would_verify": checked[k][0], "check": checked[k][1],
                       "tier": _tier(checked[k][0], s), "shared_flops": len(clash),
                       "lost_to": [{"id": found[w][1].get("id"), "kind": found[w][1].get("kind"),
                                    "recognizer": found[w][0], "n_flops": len(fl[w]),
                                    "would_verify": checked[w][0], "tier": _tier(checked[w][0], found[w][1])}
                                   for w in winners]})
    kept = [x for k, x in enumerate(found) if k not in drop]
    return kept, losers, checked, checker


# ----------------------------------------------------------------------------------------------
# grouping


def fixed_words(structures):
    """Fixed words for the grouping: each structure is one word, except a synchronizer structure
    of several lanes, which is one word per stage (stage k of every lane)."""
    out = []
    for s in structures:
        order = s.get("order")
        if s.get("kind") == "synchronizer" and order and len(order) > 1 \
                and all(isinstance(l, list) for l in order):
            depth = max(len(l) for l in order)
            for k in range(depth):
                stage = [l[k] for l in order if len(l) > k]
                if stage:
                    out.append(stage)
        else:
            out.append(s)
    return out


# ----------------------------------------------------------------------------------------------
# the entry point


def _rss_mb():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(r / 1e6 if sys.platform == "darwin" else r / 1e3, 1)


def _short(e):
    return f"{type(e).__name__}: {str(e)[:300]}"


def _report(stage, e):
    # frames without source lines: formatting a traceback normally reads source files
    frames = traceback.StackSummary.extract(traceback.walk_tb(e.__traceback__), lookup_lines=False)
    where = " < ".join(f"{fs.filename.rsplit(chr(47), 1)[-1]}:{fs.lineno} {fs.name}" for fs in reversed(frames))
    print(f"RECOGNIZE_ERROR {stage}: {_short(e)} at {where}", file=sys.stderr)


class _Clock:
    def __init__(self):
        self.t = time.perf_counter()
        self.stages = {}

    def mark(self, stage):
        if COLLECT_BETWEEN_STAGES:
            gc.collect()      # a stage's garbage (cycles too) is freed before the next stage allocates
        now = time.perf_counter()
        self.stages[stage] = {"s": round(now - self.t, 3), "peak_rss_mb": _rss_mb()}
        self.t = now


def plain(x):
    """x with every value a plain JSON type: numpy integers, booleans and floats as int, bool and
    float, arrays and tuples as lists, dict keys as str or int. A recognizer that leaks a numpy
    scalar (numpy's bool is not an int) would otherwise make the harness's result unserialisable,
    which invalidates the run."""
    if isinstance(x, dict):
        return {(k if isinstance(k, (str, int)) and not isinstance(k, bool) else
                 int(k) if isinstance(k, np.integer) else str(k)): plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [plain(v) for v in x]
    if isinstance(x, np.ndarray):
        return [plain(v) for v in x.tolist()]
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return float(x)
    return x


def recognize(nl, params=None):
    parts = split_params(params)
    clock = _Clock()
    ctl = controls.analyze(nl, parts["controls"])
    clock.mark("controls")
    res = plain(from_controls(nl, ctl, parts, clock))
    info = ctl.run_info()
    # canonical_order and bdd travel with the timings: the harness (tools/s3/run.py) parses this
    # line into the run record and raises a problem when the colour refinement left ties to id
    # order or ran out of its round budget, which is the one indicator that permutation invariance
    # failed on a design the leakage test does not cover (review[2] issue 4).
    print("RECOGNIZE_RUN " + json.dumps({"stages": clock.stages, "controls": info["timings"],
                                        "canonical_order": info["canonical_order"], "bdd": info["bdd"],
                                        "peak_rss_mb": _rss_mb()}), file=sys.stderr)
    return res


def from_controls(nl, ctl, parts=None, clock=None):
    """Steps 2-5 on a finished control layer of `nl` (parts: split_params output)."""
    parts = parts if parts is not None else split_params(None)
    clock = clock if clock is not None else _Clock()
    meta = {"recognizer": "retrace-s3", "stages": ["controls", "shift", "counter", "lfsr", "overlaps", "group"],
            "flops": ctl.F, "errors": []}
    if ctl.F == 0:
        return {"schema": RESULT_SCHEMA, "structures": [], "groups": [], "meta": meta}

    found, relations, per = [], {}, {}
    runs = (("shift", lambda: shift.find(ctl)),
            ("counter", lambda: counter.find(ctl, parts["counter"])),
            ("lfsr", lambda: lfsr.find(ctl, parts["lfsr"])))
    for name, fn in runs:
        try:
            out = fn()
        except Exception as e:  # noqa: BLE001  (one recognizer's failure must not lose the others)
            meta["errors"].append({"stage": name, "error": _short(e)})
            _report(name, e)
            clock.mark(name)
            continue
        found += [(name, s) for s in out.get("structures", [])]
        if name == "shift":
            relations["shift"] = out.get("relations", {})
            per["shift"] = out.get("stats", {})
        elif name == "counter":
            relations["counter"] = out.get("relations", [])
            per["counter"] = {**out.get("meta", {}), "words": out.get("words", [])}
        else:
            per["lfsr"] = out.get("meta", {})
        clock.mark(name)

    kept, losers, checked, checker = resolve_overlaps(nl, found)
    meta["overlaps"] = {"structures_found": len(found), "structures_checked": len(checked),
                        "checked_verified": sum(1 for v in checked.values() if v[0] is True),
                        "checked_undecided": sum(1 for v in checked.values() if v[0] is None),
                        "checked": [{"id": found[k][1].get("id"), "kind": found[k][1].get("kind"),
                                     "recognizer": found[k][0], "verdict": v[0], "reason": v[1]}
                                    for k, v in sorted(checked.items())],
                        "dropped": losers,
                        "check_sat_calls": int(checker.stats["sat_calls"]) if checker else 0}
    clock.mark("overlaps")

    chosen = [s for _, s in kept]
    try:
        g = group.group(ctl, fixed=fixed_words(chosen), params=parts["group"])
    except Exception as e:  # noqa: BLE001  (fall back to the structures as groups)
        meta["errors"].append({"stage": "group", "error": _short(e)})
        _report("group", e)
        g = {"structures": [], "groups": [list(s["flops"]) for s in chosen], "singletons": [], "meta": {}}
    clock.mark("group")

    meta["structures_by_recognizer"] = dict(collections.Counter(rec for rec, _ in kept))
    meta["structures_by_recognizer"]["group"] = len(g["structures"])
    meta["relations"] = relations
    meta["recognizers"] = per
    meta["grouping"] = g.get("meta", {})
    meta["singletons"] = g.get("singletons", [])
    meta["controls"] = ctl.meta()
    return {"schema": RESULT_SCHEMA, "structures": chosen + list(g["structures"]), "groups": g["groups"],
            "meta": meta}
