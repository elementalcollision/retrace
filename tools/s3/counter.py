"""S3 counter recognizer: binary up/down, modulo-M, saturating, loadable, reloadable, wide (to
WIDE_CAP bits) and 1-bit counters in an anonymous netlist (the S3 design doc, section 3.4, with the
part-1 reviews' fixes F5, F6, F12, M10, M15 and the generalisation review's). Each structure
carries the control conditions of schema v2 ("Verification (v2, kind-bound)" in the schema module): the
harness (the verify module) builds the counting claims from kind + order + params; this module
supplies only the conditions, and proves every claim as the harness states it before it calls a
word proven. structure["proof"]["claims"] is empty.

Everything comes from the control layer (tools.s3.controls) and the netlist API; simulation
suggests, SAT decides. Nothing is ordered by cell or net ids: ties go to structural labels, then
to the GateGraph's flop and signal order (which the netlist module builds canonically).

The claims (as the harness's verifier checks them; marked X where they rest on its extensions). The value of
a word is v = sum_k (q_k xor c_k) 2^k over params.bit_order (LSB first), c_k = 1 for the flops in
control["inverted"] (X: a flop storing its bit complemented, e.g. a reset-to-1 bit on a library without set flops); M =
params.modulus (default 2^w); params.saturating is true (the top is M - 1) or the top itself (an int
below 2^w - 1), the truth's convention. Every claim assumes no async control of the word active.
  count   under control.when (not control.reset, not control.load), for every v in the domain
          (v <= top): v' = (v + step) mod M (up) or (v - step) mod M (down), or, saturating, v + step
          stopping at the top counting up and v - step stopping at 0 counting down. An up/down
          counter gives the up case in "when" and the down case in "when_down" (X; checked under
          when_down and not when).
  hold    control.hold: outside EVERY named case (every when, every reset case, every load case),
          v' = v. Required for a counter and verified; an empty hold region (the named cases cover
          every state in range) is accepted and reported, not refused.
  reset   control.reset, a LIST of synchronous cases [{"when": COND, "value": {flop: 0|1}}, ...]:
          under each case's COND (and outside every load case) every flop takes that case's value.
          A counter that clears from several places -- the design's synchronous reset, a local
          clear, a restart at a compare -- names one case per place, and each case's COND carries
          the complement of the cases named before it, so the priority the RTL wrote as
          `if (rst) ... else if (clr) ...` is explicit and no two cases can disagree on a state.
  load    control.load, a LIST of opaque CONDs (never defining): a reload from a register, a data
          load, or a when literal turned around, one case each, so that hold holds. A counter that
          clears AND reloads needs both lists at once; with one COND apiece (schema v2.0) its hold
          obligation had no states left to be true on and the harness refused the structure.
No condition reads the word's own state (the verifier's rule; SELF_CONDITIONS): a counter that
reloads at its terminal count from a register, clears at a compare with a register or stops at a
register's value is proven for register values that make it count plainly (the reload target at
the natural wrap: a timer reloaded from 0xFFFF counts down modulo 2^16; a compare register at the
top), or, when no such values exist, for the lane's values with the modulus or stop point that
they set (params then describe that case).

Pipeline
  1. Candidates (flop sets of at most EXHAUSTIVE_WIDTH self-looped flops, ordered ones LSB first):
     nested-support chains (ctl.chains) cut at the first flop without a self-loop, and partner
     chains of words sharing an incrementer; SCC blocks (ctl.blocks); toggle nesting over counting
     changes (changes no clear or set literal makes), ranked by how completely the next bit's
     changes nest in the top bit's, twice (the second time mutual readers first), runner-ups
     explored, plus every nested mutual pair; blocks and nesting sequences closed over the flops
     they read that read only them and grown downward one tightest container at a time; carry
     chains found by simulation (_carry_chains: independent of support nesting and of pool
     statistics, so reload timers and wide counters get their full order; a chain continues along
     the chain from one of its own higher bits where the two agree, since where sampling stops a
     chain near a reload or a wrap is noise); single toggles.
     Ordered candidates wider than EXHAUSTIVE_WIDTH are tested first and the flops of the complete
     wide words they prove are not screened again.
  2. Transition tables: on test lanes (live pool lanes where the word changes, with no async
     control active where possible) every state of the word is simulated with the other sources
     pinned: next state per (lane, state). A 4-lane table screens first. When every lane drawn was
     a load or a reset (no changing or no clean lane), lanes where the next state depends on the
     word's own state are drawn (COUNTER_DEP_SCAN) and the table is tested once more.
  3. Interpretation: bit orders by change frequency over all states and over the orbits from 0 and
     the reset value (a case-coded counter sends its out-of-range states anywhere), polarities from
     the carry values, the best by one-step transitions; wraps at the lane's terminal state are
     canonical (onto 0 or from the top counting up, from 0 or onto the top counting down).
  4. Labels per lane and state: the lane's step, stop, a wrap onto one target, other. The domain
     is the closure of 0 and the reset value under each dense lane's own transitions (a lane
     counting down that stays under half the range from them also starts from the top value),
     pooled over the dense lanes; no dense lane counts one step and holds from every state (its
     count enabled by one of its own bits: a flag beside the counter it enables reads as its LSB);
     a counter has no other transition in the domain, its wraps close
     a count cycle, every bit changes while counting, a lane counts through half the range, at
     most REL_STEPS_MAX further constant steps, no single-source flip gives twice the count step.
  5. Parameters: direction, step, modulus (the cycle through 0 common to every counting lane),
     saturating (every counting lane ends in a stop), load (relative steps, data values nothing
     else explains, or a reload at the terminal count with RELOAD_DISTINCT targets or more).
  6. Proof (per direction, on a counting lane): the lane's exceptions to the template are removed
     by other values of the sources that set them (SAT over the next states with the word's state
     substituted: a reload register set to the natural wrap target, a compare register moved away)
     or, for a word counting one way, by a template that fits the lane (a modulus or a stop point
     that a register sets), or by nets that do not read the word (an enable, a load select). The
     condition is the lane's assignment of the miter's other sources, cut to those whose flip
     breaks the claim (simulated) and proven by SAT, sources coming back from counterexamples; then
     the reset case, the hold case and non-vacuity.
  7. Wider words: a proven word with a binary cycle (or a reload) grows one bit at a time (the
     chain's next flop, else a flop that reads every bit), each step simulated on the proven lanes
     at the new bit's carry boundaries with the rival candidate bits random; the grown word is
     proven as a whole (a wrap found by SAT becomes its modulus).
  8. Selection: disjoint words, wider first; chosen words are tried one bit wider and reselected.
     A chosen word is dropped as a fragment when its count condition pins a toggling flop that
     can change (a) that belongs to another proven word sharing flops with it that is no fragment
     itself (a counter split at a pinned bit), or (b) that sits below it in one arithmetic (nested
     support), does not read it (or, a sum bit, reads it only where the word stops, through the
     enable that stops both: a deadline adder comparing its own sum), belongs to no counter, and is
     a sum bit (x' = x xor g) or makes an adder when put under it (an accumulator's upper part); or
     (c) the condition pins some of the toggling bits below the word that feed its LSB and those
     bits make an adder under it (the addend and one low bit make the carry certain). A chosen
     word is dropped as truncated when a flop outside it is an adder's bit reading it at two or
     more states either way, not as a threshold, and belongs to no whole counter (an LCG's or a broken carry's low bits). A word
     whose stored polarity changes in runs of two or more bits is cut there when the parts prove
     on their own and count opposite ways as stored (a prescaler under a down timer).
  9. Relations: cascades (the upper word's condition holds the lower word at its terminal count:
     condition evidence; or it counts only where the lower word wraps: simulation evidence) are
     reported, never merged.

API
    rep = find(ctl, params=None)    # ctl: tools.s3.controls.analyze(nl) (every stage run)
        rep["structures"]           result-schema structures of kind "counter", disjoint
        rep["relations"]            cascades between them
        rep["words"]                per structure: flop indices LSB first, inverted bits, generator,
                                    flops its condition pins
        rep["meta"]                 statistics and rejected candidates by reason
        rep["run"]                  timings (volatile)
    recognize(nl, params=None)      the control layer and this module alone, as a result dict
"""

from __future__ import annotations

import collections
import itertools
import time

import numpy as np

from tools.s3 import controls as _controls
from tools.s3 import params as _params
from tools.s3.netlist import GATE, eval_tt

RESULT_SCHEMA = "retrace-s3-result/1"

# ================================================================================================
# This module's thresholds besides the shared ones (EXHAUSTIVE_WIDTH, WORD_CAP, TEST_LANES_ACTIVE,
# TEST_LANES_HOLD, N_MIN) are tools.s3.params entries, each justified there (moved from this module
# on 2026-09-22); each is overridable per run (find(ctl, params)); none names a width, modulus or
# design. DEFAULTS is a view by name for callers.
_OWN = ("LOAD_DISTINCT", "RELOAD_DISTINCT", "REL_STEPS_MAX", "MODE_LANES", "MODE_MIN_LANES",
        "MODE_MIN_SHARE", "NEST_MIN", "NEST_RATE", "NEST_SLACK", "NEST_TRIES", "ORDER_TRIES",
        "COUNTER_SAT_CALLS", "CLAIM_SAT_LIMIT", "GROW_LIMIT", "UP_TRIES", "REFINE_ROUNDS", "SENS_VECTORS",
        "LANE_TRIES", "NET_TRIES", "WIDE_CAP", "WIDE_SAMPLES", "WIDE_EXCEPTIONS", "WIDE_RETRIES",
        "CHAIN_SAMPLES", "CHAIN_LANES", "CHAIN_FANOUT", "CHAIN_LSB", "CHAIN_AGREE", "NEST_SHARE_SLACK",
        "REGULARIZE_ROUNDS", "REGULARIZE_OK_STATES", "FLIP_SAMPLE", "NEST_BINS", "FRAGMENT_DEPTH",
        "TRUNC_DEPTH", "SELF_CONDITIONS", "COUNTER_DEP_SCAN",
        # moved into tools/s3/params.py from this module's own block on 2026-09-22 (C52-C55)
        "MODE_STEPS_MAX", "MODE_STEP_SOURCES", "QUIET_LANES", "SELF_COVERAGE", "COVER_VECTORS",
        "COVER_SAT", "NET_COND", "ENABLE_TRIES", "RESET_TRIES", "LOAD_CUBE_ROUNDS", "HOLD_REQUIRED",
        # schema v2.1's multi-case control: how many reset / load cases this module may name (moved
        # into tools/s3/params.py from this module's own block on 2026-09-23, integration; I01)
        "RESET_CASES", "LOAD_CASES",
        # the harness's own bound on the coverage obligation, mirrored (params.NOT_PER_RUN)
        "HARNESS_COVERAGE_MAX_OWN_BITS")


DEFAULTS = {k: getattr(_params, k) for k in _OWN}


_AND2, _OR2, _XOR2 = 0b1000, 0b1110, 0b0110
# table verdicts that mark an adder (a data addend), not a counter
_ADDER = ("steps s and 2s (a two-bit addend: an adder)", "accumulator (many constant steps)",
          "every step occurs (an adder)")
# rejections that come from the lanes drawn (every change lane a load or a reset), not from the word:
# the table is retried once on lanes where the next state depends on the word's own state
_LANE_STARVED = ("no changing lane", "no clean lane")
# rejections that more lanes cannot undo (the quick 4-lane screen stops on these only)
_FIRM = ("other transitions in the domain", "accumulator (many constant steps)", "every step occurs (an adder)")


# ----------------------------------------------------------------------------------------------
# bit rows


def _pack(bits):
    """Bits (last axis) packed into uint64 words, little endian: lane n is bit (n mod 64) of word (n div 64)."""
    b = np.asarray(bits, np.uint8)
    lead = b.shape[:-1]
    n = b.shape[-1]
    pad = (-n) % 64
    if pad:
        b = np.concatenate([b, np.zeros(lead + (pad,), np.uint8)], axis=-1)
    return np.ascontiguousarray(np.packbits(b, axis=-1, bitorder="little")).view(np.uint64).reshape(lead + (-1,))


def _unpack(words, n):
    return np.unpackbits(np.ascontiguousarray(words).view(np.uint8), bitorder="little")[:n]


def _lanes_of(mask):
    return np.flatnonzero(np.unpackbits(np.ascontiguousarray(mask).view(np.uint8), bitorder="little"))


def _spread(lanes, n):
    lanes = np.asarray(lanes)
    if len(lanes) <= n:
        return [int(x) for x in lanes]
    return [int(lanes[(k * len(lanes)) // n]) for k in range(n)]


def _pc(x):
    return int(np.bitwise_count(x).sum())


def _sdt(w):
    """Array dtype of the state numbers of a w-bit word: int64 up to 62 bits, Python ints above."""
    return np.int64 if w <= 62 else object


def _rand_states(rng, n, w):
    """n uniformly random w-bit state numbers (Python ints above 62 bits)."""
    if w <= 62:
        return rng.integers(0, 1 << w, size=n, dtype=np.int64)
    out = np.zeros(n, object)
    for k in range(0, w, 62):
        out = out | (rng.integers(0, 1 << min(62, w - k), size=n, dtype=np.int64).astype(object) << k)
    return out


class _Cone:
    """Literals of a graph evaluated over given source rows (cone-restricted, compact)."""

    def __init__(self, g, lits):
        gates, leaves = g.cone(lits)
        self.g = g
        self.lits = list(lits)
        self.gates = sorted(gates)
        self.leaves = sorted(s for s in leaves if s != 0)
        self.leaf_set = set(self.leaves)

    def eval(self, rows, nw, extra=()):
        """Values of self.lits (and of the gate signals `extra`, uncomplemented) over the rows."""
        g = self.g
        val = dict(rows)
        val[0] = np.zeros(nw, np.uint64)
        for s in self.leaves:
            if s not in val:
                val[s] = val[0]
        for s in self.gates:
            val[s] = eval_tt(g.tt[s], len(g.fanin[s]), [val[f] for f in g.fanin[s]])
        out = [~val[v >> 1] if v & 1 else val[v >> 1] for v in self.lits]
        if extra:
            return out, [val[s] for s in extra]
        return out


# ----------------------------------------------------------------------------------------------
# claim templates as circuits (on the control layer's scratch graph; the harness builds the same)


def _mk(S, tt, a, b):
    return S.mk(tt, [a, b])


def _tree(S, tt, lits, empty):
    lits = list(lits)
    if not lits:
        return empty
    while len(lits) > 1:
        nxt = [S.mk(tt, [lits[i], lits[i + 1]]) for i in range(0, len(lits) - 1, 2)]
        if len(lits) % 2:
            nxt.append(lits[-1])
        lits = nxt
    return lits[0]


def _AND(S, lits):
    return _tree(S, _AND2, lits, 1)


def _OR(S, lits):
    return _tree(S, _OR2, lits, 0)


def _add_const(S, bits, c):
    """(value(bits) + c) mod 2^len(bits), LSB first, and the carry out."""
    out, carry = [], 0
    for k, b in enumerate(bits):
        if (c >> k) & 1:
            out.append(_mk(S, _XOR2, b, carry) ^ 1)
            carry = _mk(S, _OR2, b, carry)
        else:
            out.append(_mk(S, _XOR2, b, carry))
            carry = _mk(S, _AND2, b, carry)
    return out, carry


def _lt_const(S, bits, c):
    """value(bits) < c."""
    w = len(bits)
    if c >= 1 << w:
        return 1
    if c <= 0:
        return 0
    lt, eq = 0, 1
    for k in reversed(range(w)):
        if (c >> k) & 1:
            lt = _mk(S, _OR2, lt, _mk(S, _AND2, eq, bits[k] ^ 1))
            eq = _mk(S, _AND2, eq, bits[k])
        else:
            eq = _mk(S, _AND2, eq, bits[k] ^ 1)
    return lt


def _mux(S, s, a, b):
    return [_mk(S, _OR2, _mk(S, _AND2, s, x), _mk(S, _AND2, s ^ 1, y)) for x, y in zip(a, b)]


def template_lits(S, V, d, step, M, sat):
    """(next value literals, domain literal) of the counting claim in value space: V are the
    value-bit literals (LSB first), d "up" | "down", M the modulus (None: 2^w; for a saturating
    counter its range: it stops at M - 1 counting up, at 0 counting down)."""
    w = len(V)
    ns = 1 << w
    MM = ns if M is None else int(M)
    if sat:
        dom = _lt_const(S, V, MM)
        if d == "up":
            inc, _c = _add_const(S, V + [0], step)
            over = _lt_const(S, inc, MM) ^ 1
            return _mux(S, over, [((MM - 1) >> k) & 1 for k in range(w)], inc[:w]), dom
        under = _lt_const(S, V, step)
        dec, _c = _add_const(S, V, (ns - step) % ns)
        return _mux(S, under, [0] * w, dec), dom
    dom = _lt_const(S, V, MM) if MM < ns else 1
    if d == "up":
        if MM == ns:
            return _add_const(S, V, step % ns)[0], dom
        t, _c = _add_const(S, V + [0], step)
        ge = _lt_const(S, t, MM) ^ 1
        tm, _c = _add_const(S, t, (1 << (w + 1)) - MM)
        return _mux(S, ge, tm[:w], t[:w]), dom
    if MM == ns:
        return _add_const(S, V, (ns - step) % ns)[0], dom
    borrow = _lt_const(S, V, step)
    a, _c = _add_const(S, V, MM - step)
    b, _c = _add_const(S, V, (ns - step) % ns)
    return _mux(S, borrow, a, b), dom


def template_ok(w, M, sat, step=1):
    """Schema v2's width / modulus / limit coherence: 2^(w-1) < modulus <= 2^w and a saturation
    limit >= 2^(w-1) and above the step, so no claimed bit is dead and the template is not constant
    (the harness refuses the rest; verify.py's counter check). M is None for the natural modulus
    2^w; sat is true with the limit M - 1."""
    ns = 1 << w
    if sat:
        top = (M - 1) if M is not None else ns - 1
        return (ns >> 1) <= top < ns and top > step
    return M is None or (ns >> 1) < M <= ns


def params_ok(w, params):
    """The emitted counter params obey template_ok as the harness reads them (params.saturating
    true: the top is modulus - 1, else 2^w - 1; an int: that top)."""
    sp = params.get("saturating")
    step = int(params.get("step") or 1)
    M = params.get("modulus")
    if sp:
        return template_ok(w, (int(sp) + 1) if not isinstance(sp, bool) else M, True, step)
    return template_ok(w, M, False, step)


def template_values(v, d, step, M, sat, w):
    """The same claim on value arrays: (next values, domain mask)."""
    ns = 1 << w
    MM = ns if M is None else int(M)
    v = np.asarray(v, _sdt(w))
    if sat:
        dom = v < MM
        if d == "up":
            return np.where(v + step > MM - 1, MM - 1, v + step), dom
        return np.where(v < step, 0, v - step), dom
    dom = v < MM
    return ((v + step) % MM if d == "up" else (v - step) % MM), dom


# ----------------------------------------------------------------------------------------------
# interpretation of a transition table


def _value_maps(pi, p, w):
    """(value of each raw state, raw state of each value) for bit order pi (pi[k] = raw bit of
    weight 2^k) and polarity p (bit k: the weight-k bit is stored complemented)."""
    ns = 1 << w
    x = np.arange(ns, dtype=np.int64)
    v = np.zeros(ns, np.int64)
    for k, j in enumerate(pi):
        v |= (((x >> j) & 1) ^ ((p >> k) & 1)) << k
    inv = np.empty(ns, np.int64)
    inv[v] = x
    return v, inv


def _orders(tog, w, hint, cap):
    """Bit orders to try: by change count (descending); each group of equal counts permuted (all
    ways up to 3 bits, else reversed) one group at a time; and the hint's order. Ties in the base
    order go to raw position (the candidate's own order: LSB first for chains)."""
    groups = []
    for j in sorted(range(w), key=lambda j: (-tog[j], j)):
        if groups and tog[groups[-1][0]] == tog[j]:
            groups[-1].append(j)
        else:
            groups.append([j])
    base = [j for gr in groups for j in gr]
    out = [tuple(base)]
    k0 = 0
    for gr in groups:
        n = len(gr)
        if n >= 2:
            perms = itertools.permutations(gr) if n <= 3 else [tuple(reversed(gr))]
            for pm in perms:
                o = tuple(base[:k0] + list(pm) + base[k0 + n:])
                if o not in out:
                    out.append(o)
                if len(out) >= cap:
                    break
        k0 += n
        if len(out) >= cap:
            break
    if hint is not None and tuple(hint) not in out:
        out.append(tuple(hint))
    return out


def _polarities(A, x, pi, w):
    """Candidate polarities: from each changing lane's carry pattern (the value of bit pi[j] in the
    states where bit pi[j+1] changes), as an up count, the MSB both ways, and complements."""
    ns = 1 << w
    pats = collections.Counter()
    for row in A:
        T = row ^ x
        c = 0
        for j in range(w - 1):
            t = ((T >> pi[j + 1]) & 1).astype(bool)
            if not t.any():
                break
            b = (x[t] >> pi[j]) & 1
            c |= (1 if 2 * int(b.sum()) >= len(b) else 0) << j
        pats[c] += 1
    low = (1 << (w - 1)) - 1 if w > 1 else 0
    out = []
    for c, _n in sorted(pats.items(), key=lambda kv: (-kv[1], kv[0]))[:3] + [(low, 0)]:
        p0 = (~c) & low
        for pm in (0, 1):
            p = p0 | ((pm << (w - 1)) if w > 1 else pm)
            for q in (p, p ^ (ns - 1)):
                if q not in out:
                    out.append(q)
    return out


def _dedupe(X):
    """(unique rows in first-seen order, index of each row's unique row)."""
    X = np.ascontiguousarray(X)
    first, inv = {}, np.empty(X.shape[0], np.int64)
    for k in range(X.shape[0]):
        inv[k] = first.setdefault(X[k].tobytes(), len(first))
    keep = np.zeros(len(first), np.int64)
    keep[inv[::-1]] = np.arange(X.shape[0])[::-1]
    return X[keep], inv


def _reach_rows(rows, starts, ns):
    """Per row, the states reachable along it from that row's starts (an array per start set):
    (m, ns) bool (pointer doubling, complete after log2(ns) + 1 rounds; identical rows with
    identical starts are computed once)."""
    P = np.asarray(rows, np.int64)
    m = P.shape[0]
    if m == 0:
        return np.zeros((0, ns), bool)
    S = np.stack([np.asarray(st, np.int64) for st in starts], axis=1)
    uk, inv = _dedupe(np.concatenate([P, S], axis=1))
    P, S = uk[:, :ns], uk[:, ns:]
    mu = P.shape[0]
    dom = np.zeros((mu, ns), bool)
    for k in range(S.shape[1]):
        dom[np.arange(mu), S[:, k]] = True
    for _r in range(max(1, (ns - 1).bit_length()) + 1):
        r, c = np.nonzero(dom)
        dom[r, P[r, c]] = True
        P = np.take_along_axis(P, P, axis=1)
    return dom[inv]


def _power(rows, starts, n):
    """rows^n applied to one start per row (pointer doubling)."""
    P = np.asarray(rows, np.int64)
    if P.shape[0] == 0:
        return np.zeros(0, np.int64)
    ns = P.shape[1]
    uk, inv = _dedupe(np.concatenate([P, np.asarray(starts, np.int64)[:, None]], axis=1))
    P, cur = uk[:, :ns], uk[:, ns].copy()
    idx = np.arange(P.shape[0])
    while n:
        if n & 1:
            cur = P[idx, cur]
        n >>= 1
        if n:
            P = np.take_along_axis(P, P, axis=1)
    return cur[inv]


def _judge(F, act, const, pi, p, w, reset_raw, rel_max, full=True, mode_max=0):
    """The counter verdict under one interpretation (see the module docstring, steps 3-5), or a
    rejection {"ok": False, "why"}. mode_max > 0 admits a word whose lanes take several constant
    steps under one enable as a case-selected step (the domain split by the case literal): the
    lanes of the smallest step are the defining ones and the rest come back in "alt_steps"; the
    caller still has to confirm that one source chooses between them (Counters._mode_ok)."""
    ns = 1 << w
    vr, rv = _value_maps(pi, p, w)
    G = vr[F[:, rv]]                      # value-space next state, lanes x value
    v = np.arange(ns, dtype=np.int64)
    d = (G - v[None, :]) % ns
    A = np.flatnonzero(act)
    na = len(A)
    dA, GA = d[A], G[A]
    base = (ns * np.arange(na, dtype=np.int64))[:, None]
    cnt = np.bincount((dA + base).ravel(), minlength=na * ns).reshape(na, ns)
    cnt[:, 0] = -1
    mag = np.minimum(v, ns - v)
    top = np.argmax(cnt * (ns + 1) - mag[None, :], axis=1).astype(np.int64)
    reg = dA == top[:, None]
    stop = dA == 0
    rest = ~reg & ~stop
    regular = int(reg.sum())
    st = np.where(top <= ns // 2, top, top - ns)
    dense = reg.sum(1) >= max(2, ns // 8)        # a lane step on enough states (else a sparse lane: holds
    if len({abs(int(x)) for x in st[dense]}) > rel_max + 1:     # with a few state-dependent changes)
        return {"ok": False, "why": "accumulator (many constant steps)", "regular": regular}
    # each lane's closure of 0 and the reset value under its own transitions; a lane stepping down
    # that stays under half the range from them (a timer loaded with data and stopping at 0) also
    # starts from the top value
    starts = [np.zeros(na, np.int64)]
    if reset_raw is not None:
        starts.append(np.full(na, int(vr[reset_raw]), np.int64))
    dom = _reach_rows(GA, starts, ns)
    small = (dom.sum(1) < ns // 2) & (st < 0)
    if small.any():
        dom[small] |= _reach_rows(GA[small], [np.full(int(small.sum()), ns - 1, np.int64)], ns)
    # the domain is pooled over the lanes that step densely (one counter, one state space): every
    # lane's irregular transitions inside it must be one wrap (a single target)
    pool = dom[dense].any(0) if dense.any() else dom.any(0)
    dom = np.broadcast_to(pool, dom.shape)
    # a lane on which every count step lands on a state that holds there counts one step and stops
    # from every state: the count is enabled by one of the word's own bits (a flag set under one
    # condition and cleared under another, next to the counter it enables, reads as that counter's
    # LSB); a counter's enable does not read its state, so only its stop states hold
    Rd = reg & dom
    lands = np.take_along_axis(stop & dom, GA, axis=1)
    if (dense & (Rd.sum(1) >= 2) & ~(Rd & ~lands).any(1)).any():
        return {"ok": False, "why": "every count step lands where the word holds (a flag enables the count)",
                "regular": regular}
    rin = rest & dom
    tc = np.bincount((GA + base)[rin], minlength=na * ns).reshape(na, ns)
    tgt = np.argmax(tc, axis=1)
    has_rest = rin.any(1)
    wrap = rin & (GA == tgt[:, None])
    other = rin & ~wrap
    if other.any():
        return {"ok": False, "why": "other transitions in the domain", "regular": regular}
    clean = dense
    if not clean.any():
        return {"ok": False, "why": "no clean lane", "regular": regular}
    s = int(np.abs(st[clean]).min())
    cmask = clean & (np.abs(st) == s)
    rmask = dense & ~cmask
    rel_steps = sorted({int(x) for x in st[rmask]})
    if len(rel_steps) > rel_max:
        return {"ok": False, "why": "accumulator (many constant steps)", "regular": regular}
    if s % 2 == 0:
        return {"ok": False, "why": "even step (a bit that never changes)", "regular": regular}
    alt_steps = []
    if any(abs(x) == 2 * s for x in rel_steps):
        # Several constant steps under one enable. An addend of k >= 2 bits gives every sum of its
        # bits' weights, so some step is the sum of two others (1, 2 and 3 for two bits); a
        # case-selected step (c <= c + (two ? 2 : 1)) gives only the selected values. Keep the
        # smallest step's lanes as the defining case and report the rest; they are not a data load.
        O = sorted({int(x) for x in st[dense]} - {0})
        sums = {a + b for i, a in enumerate(O) for b in O[i + 1:]}
        if mode_max < 2 or len(O) > mode_max or (set(O) & sums):
            return {"ok": False, "why": "steps s and 2s (a two-bit addend: an adder)", "regular": regular}
        alt_steps = [int(x) for x in rel_steps]
        rmask = np.zeros(na, bool)
        rel_steps = []
    if ns > 2 and len({int(x) for x in top[dense]}) == ns - 1:
        return {"ok": False, "why": "every step occurs (an adder)", "regular": regular}
    # a wrap in a lane's domain closes the lane's count cycle: the orbit from its target returns to
    # it with that one irregular step (mod-M wraps onto 0, reloads at a terminal count)
    K = np.flatnonzero(cmask & wrap.any(1))
    if len(K):
        rows, t = GA[K], tgt[K].astype(np.int64)
        orb = _reach_rows(rows, [t], ns)
        oncyc = _reach_rows(rows, [_power(rows, t, ns)], ns)[np.arange(len(K)), t]
        if not (oncyc & ((orb & ~reg[K]).sum(1) == 1) & ~((wrap[K] & dom[K]) & ~orb).any(1)).all():
            return {"ok": False, "why": "a wrap that does not close a count cycle", "regular": regular}
    mv = (reg | wrap) & dom & cmask[:, None]
    moved = int(np.bitwise_or.reduce((GA ^ v[None, :])[mv])) if mv.any() else 0
    if moved != ns - 1:
        return {"ok": False, "why": "a bit that never changes while counting", "regular": regular}
    up_l = (st > 0) | (ns == 2)
    C = np.flatnonzero(cmask)
    # counting evidence: some counting lane counts through half the range from its origin (the
    # lowest state of its domain counting up, the highest counting down) by counting steps alone
    lo = np.argmax(dom[C], axis=1)
    hi = ns - 1 - np.argmax(dom[C][:, ::-1], axis=1)
    orig = np.where(up_l[C], lo, hi).astype(np.int64)
    need = ns // 2
    Rg = np.concatenate([np.where(reg[C], GA[C], ns), np.full((len(C), 1), ns)], axis=1)   # ns: a sink
    if not (_power(Rg, orig, need) != ns).any():
        return {"ok": False, "why": "no lane counts through half the range", "regular": regular}
    # wraps at the lane's terminal state (its highest domain state counting up, its lowest counting
    # down) with targets that differ between lanes: reloads from a register or clears at a compare
    wk = [(k, np.flatnonzero(wrap[c])) for k, c in enumerate(C) if wrap[c].any()]
    terminal = all(len(ws) == 1 and int(ws[0]) == (hi[k] if up_l[C[k]] else lo[k]) for k, ws in wk)
    wtargets = {(bool(up_l[C[k]]), int(tgt[C[k]])) for k, _ws in wk}      # per direction
    wstates = {(bool(up_l[C[k]]), int(ws[0])) for k, ws in wk if len(ws)}
    ndirs = len({u for u, _t in wtargets})
    modulus, saturating, natural = None, None, False
    stops = {"up": set(), "down": set()}
    if full:
        rows = GA[C]
        fin = _power(rows, orig, ns)
        fixed = (rows[np.arange(len(C)), fin] == fin) & (fin != orig)
        orb0 = _reach_rows(rows, [np.zeros(len(C), np.int64)], ns)
        zero_on_cycle = _reach_rows(rows, [_power(rows, np.zeros(len(C), np.int64), ns)], ns)[:, 0]
        mods = set()
        for k, c in enumerate(C):
            if fixed[k]:
                stops["up" if up_l[c] else "down"].add(int(fin[k]))
            else:
                n_cyc = int(orb0[k].sum()) if zero_on_cycle[k] else None
                mods.add(n_cyc if n_cyc and n_cyc > 1 else None)
        natural = ns in mods
        n_stop = int(fixed.sum())
        if n_stop:
            common = all(len(x) <= 1 for x in stops.values())
            saturating = True if (n_stop == len(C) and common) else None
        else:
            saturating = False
            modulus = mods.pop() if len(mods) == 1 else None
            if s != 1 and modulus is not None and modulus != ns:
                modulus = None
    info = []
    for k, l in enumerate(A):
        info.append({"lane": int(l), "top": int(top[k]), "s": int(st[k]), "reg": reg[k], "stop": stop[k],
                     "wrap": wrap[k], "target": int(tgt[k]) if has_rest[k] else None, "other": other[k],
                     "dom": dom[k]})
    counting = [info[k] for k in C]
    rel = [info[k] for k in np.flatnonzero(rmask)]
    ups = [info[k] for k in C if up_l[k]]
    downs = [] if ns == 2 else [info[k] for k in C if not up_l[k]]
    direction = "updown" if ups and downs else ("up" if ups else "down")
    targets = sorted({int(F[l, 0]) for l in np.flatnonzero(const)})
    # canonical wraps: counting up onto 0 or from the top value, counting down from 0 or onto the top
    wrap0 = sum(1 for i in counting if i["wrap"].any() and (
        (i["s"] > 0 and (i["target"] == 0 or bool(i["wrap"][ns - 1]))) or
        (i["s"] < 0 and (bool(i["wrap"][0]) or i["target"] == ns - 1))))
    key = (regular, wrap0, -bin(p).count("1"), len(ups) >= len(downs))
    return {"ok": True, "pi": tuple(int(j) for j in pi), "p": int(p), "w": w, "step": s, "direction": direction,
            "modulus": modulus, "saturating": saturating, "load": bool(rel), "const_targets": targets,
            "info": info, "counting": counting, "ups": ups, "downs": downs, "rel": rel, "rel_steps": rel_steps,
            "alt_steps": alt_steps,
            "domain": dom[cmask].any(0), "G": G, "vr": vr, "rv": rv, "key": key, "regular": regular,
            "terminal_wraps": bool(wk) and terminal and (len(wtargets) > ndirs or len(wstates) > ndirs),
            "reload": bool(wk) and terminal and len(wtargets) > ndirs,
            "reload_values": max(collections.Counter(u for u, _t in wtargets).values(), default=0),
            "natural": natural, "stops": {k: sorted(x) for k, x in stops.items()}}


def interpret(F, w, reset_raw=None, hint=None, rel_max=2, order_cap=24, mode_max=0):
    """The best counter interpretation of a transition table F (lanes x 2^w raw states), or a
    rejection {"ok": False, "why"}."""
    ns = 1 << w
    x = np.arange(ns, dtype=np.int64)
    hold = (F == x[None, :]).all(1)
    const = (F == F[:, :1]).all(1) & ~hold
    act = ~hold & ~const
    if not act.any():
        return {"ok": False, "why": "no changing lane"}
    A = F[act]
    tog = [int((((A ^ x[None, :]) >> j) & 1).sum()) for j in range(w)]
    # change counts along the orbits from 0 and the reset state as well (a counter coded as a case
    # table sends its out-of-range states anywhere, which swamps the counts over all states)
    starts = [np.zeros(len(A), np.int64)] + ([np.full(len(A), reset_raw, np.int64)] if reset_raw is not None else [])
    orb = _reach_rows(A, starts, ns)
    tog2 = [int(((((A ^ x[None, :]) >> j) & 1) * orb).sum()) for j in range(w)]
    orders = _orders(tog, w, hint, order_cap)
    orders += [o for o in _orders(tog2, w, None, order_cap) if o not in orders]
    best, worst = None, None
    combos = []
    for pi in orders:
        for p in _polarities(A, x, pi, w):
            if (pi, p ^ (ns - 1)) not in combos:
                combos.append((pi, p))
    # pre-score: the number of one-lane-step transitions (the complement gives the same); the full
    # judgement goes down the ranking and stops below the best passing score
    base = (ns * np.arange(len(A), dtype=np.int64))[:, None]
    sc = []
    for k, (pi, p) in enumerate(combos):
        vr, rv = _value_maps(pi, p, w)
        d = (vr[A[:, rv]] - x[None, :]) % ns
        cnt = np.bincount((d + base).ravel(), minlength=len(A) * ns).reshape(len(A), ns)
        cnt[:, 0] = 0
        sc.append((-int(cnt.max(1).sum()), k))
    ranked = [(-v, combos[k]) for v, k in sorted(sc)[:4]]
    for score0, (pi, p0) in ranked:
        if best is not None and score0 < best["regular"]:
            break
        for p in (p0, p0 ^ (ns - 1)):
            r = _judge(F, act, const, pi, p, w, reset_raw, rel_max, full=False, mode_max=mode_max)
            if not r["ok"]:
                if worst is None or r["regular"] > worst["regular"]:
                    worst = r
                continue
            k = r["key"] + ((tuple(hint) == tuple(pi)) if hint is not None else False,)
            if best is None or k > best["key2"]:
                r["key2"] = k
                best = r
    if best is None:
        return worst or {"ok": False, "why": "no interpretation"}
    key2 = best["key2"]
    best = _judge(F, act, const, best["pi"], best["p"], w, reset_raw, rel_max, full=True, mode_max=mode_max)
    best["key2"] = key2
    best["hold_lanes"] = [int(l) for l in np.flatnonzero(hold)]
    best["const_lanes"] = [int(l) for l in np.flatnonzero(const)]
    return best


# ----------------------------------------------------------------------------------------------
# the recognizer


class Counters:
    def __init__(self, ctl, params=None):
        self.ctl = ctl
        P = dict(ctl.P)
        for k, v in DEFAULTS.items():
            P.setdefault(k, v)
        for k, v in (params or {}).items():
            if k not in P:
                raise KeyError(f"unknown parameter {k}")
            P[k] = v
        self.P = P
        self.g, self.S = ctl.g, ctl.S
        self.lab = [ctl.labels[f.q] for f in ctl.flops]
        self.q2flop = ctl.g.q2flop
        self.stats = collections.Counter()
        self.timings = collections.OrderedDict()
        self.rejects = collections.Counter()
        self._cones = {}
        self._fcones = {}
        self._act = {}
        self._cact = {}
        self._tables = {}
        self._aoff = {}

    # ------------------------------------------------------------------ basics
    def cell(self, i):
        return int(self.ctl.flops[i].cell)

    def fk(self, i):
        """Order key of flop i: its structural label, then its GateGraph index (built in a
        canonical, id-independent order), never its cell id."""
        return (self.lab[i], i)

    def _cone(self, word):
        """The next-state cone of a word: the union of its flops' cones (each computed once)."""
        key = tuple(word)
        c = self._cones.get(key)
        if c is None:
            if len(self._cones) > 256:
                self._cones.clear()
            gs, ls = [], []
            for i in word:
                fc = self._fcones.get(i)
                if fc is None:
                    g0, l0 = self.g.cone([self.ctl.f(i)])
                    fc = self._fcones[i] = (np.array(sorted(g0), np.int32), np.array(sorted(l0), np.int32))
                gs.append(fc[0])
                ls.append(fc[1])
            gates = np.unique(np.concatenate(gs))
            leaves = np.setdiff1d(np.unique(np.concatenate(ls)), gates)
            c = _Cone.__new__(_Cone)
            c.g, c.lits = self.g, [self.ctl.f(i) for i in word]
            c.gates = gates.tolist()
            c.leaves = [x for x in leaves.tolist() if x != 0]
            c.leaf_set = set(c.leaves)
            self._cones[key] = c
        return c

    def _active(self, i, full=False):
        """Live lanes where flop i changes; with full, every pool lane (see _awake)."""
        key = (i, bool(full))
        a = self._act.get(key)
        if a is None:
            ctl = self.ctl
            a = ctl.value(ctl.f(i)) ^ ctl.value(ctl.qlit(i)) if full else ctl.active(i)
            self._act[key] = a
        return a

    def _counting(self, i, full=False):
        """Live lanes where flop i changes with none of its clear or set literals active."""
        key = (i, bool(full))
        a = self._cact.get(key)
        if a is None:
            a = self._active(i, full).copy()
            for L, _v in self.ctl.profile[i].sets:
                a &= ~self.ctl.value(L)
            self._cact[key] = a
        return a

    def _awake(self):
        """Flops the control layer proved quiescent (they change only where the literal it took for
        a synchronous reset is active) whose next state depends on their own value where that
        literal IS active. The literal is then a case literal, not a reset -- a carry into the next
        BCD digit clears the low digit, which forces a quarter of the next states and so passes the
        reset test, and enables the high digit -- and the flop is a counter candidate again, tested
        on every pool lane instead of the live ones. A flop that only takes a reset value goes to
        one state from either of its own there and stays quiescent.
        (The lanes are the pool's reset-free ones, RESET_FREE_EVERY of the control layer.)"""
        aw = getattr(self, "_awake_set", None)
        if aw is None:
            ctl, P = self.ctl, self.P
            aw = self._awake_set = set()
            if ctl.reset.kind == "sync":
                on = ctl.value(ctl.reset.lit)
                for i in sorted(ctl.quiescent, key=self.fk):
                    if i not in ctl.supp_flops[i]:
                        continue
                    m = on & self._async_off([i])
                    A = _spread(_lanes_of(m if m.any() else on), P["QUIET_LANES"])
                    if not A:
                        continue
                    cone = self._cone([i])
                    ext = [x for x in cone.leaves if x != ctl.flops[i].q]
                    F = self.states_eval([i], self._lane_bits(ext, A), [0, 1], cone, ext)
                    # the flop must both depend on its own value there and change from one of its
                    # own states: a flop that simply keeps its value (f == q) depends on it too
                    if ((F[:, 0] != F[:, 1]) & ((F[:, 0] == 1) | (F[:, 1] == 0))).any():
                        aw.add(i)
                # the literal gates a whole word: a quiescent flop of an awake flop's support SCC
                # is awake with it (a digit's top bit changes only at two of the lower bits'
                # values, so the per-flop test alone is lane-hungry for it)
                hot = {ctl.scc_of[i] for i in aw}
                for i in sorted(ctl.quiescent, key=self.fk):
                    if ctl.scc_of[i] in hot and i in ctl.supp_flops[i]:
                        aw.add(i)
            self.stats["awake_flops"] = len(aw)
        return aw

    def _quiet(self, i):
        """Flop i is quiescent and stays out of every candidate word (see _awake)."""
        return i in self.ctl.quiescent and i not in self._awake()

    def _full(self, word):
        """The word is tested on every pool lane: every one of its flops is awake (see _awake)."""
        aw = self._awake()
        return bool(aw) and all(i in aw for i in word)

    def _async_off(self, word):
        """Lanes where no async clear or preset of the word is active."""
        key = tuple(sorted(word))
        m = self._aoff.get(key)
        if m is None:
            m = np.full(self.ctl.W, ~np.uint64(0), np.uint64)
            for i in word:
                f = self.ctl.flops[i]
                for a in (f.clear, f.preset):
                    if a not in (0, 1):
                        m &= ~self.ctl.value(a)
                    elif a == 1:
                        m[:] = 0
            self._aoff[key] = m
        return m

    def _async_lit(self, word):
        """Literal (scratch graph) of 'no async control of the word active'."""
        return _AND(self.S, [a ^ 1 for i in word for a in (self.ctl.flops[i].clear, self.ctl.flops[i].preset) if a])

    def _bits(self, kind, i, full=False):
        """Unpacked 0/1 row (uint8, every lane) of flop i: 'a' changes (live), 'q' state, 'f' next state."""
        ctl = self.ctl
        src = self._active(i, full) if kind == "a" else ctl.value(ctl.qlit(i) if kind == "q" else ctl.f(i))
        return _unpack(src, 64 * ctl.W)

    def _lane_bits(self, sigs, lanes):
        """Source values (len(sigs), len(lanes)) of pool lanes, 0/1."""
        ctl = self.ctl
        if not len(sigs):
            return np.zeros((0, len(lanes)), np.uint8)
        rows = ctl.V[np.asarray(sigs, np.int64), :ctl.W]
        ln = np.asarray(lanes, np.int64)
        return ((rows[:, ln >> 6] >> (ln & 63).astype(np.uint64)) & np.uint64(1)).astype(np.uint8)

    def _sat(self, lits, tt, assume=(), extra=()):
        """Sat.check with no reset assumption (claims are checked as the harness does)."""
        if self.stats["sat_calls"] >= self.P["COUNTER_SAT_CALLS"]:
            self.stats["sat_skipped"] += 1
            return None, None
        self.stats["sat_calls"] += 1
        return self.ctl.sat.check(lits, tt, list(assume), limit=self.P["CLAIM_SAT_LIMIT"], extra=extra)

    def _unsat(self, lits):
        """The conjunction of literals is unsatisfiable: True | False | None (unknown, budget)."""
        lits = [l for l in lits if l != 1]
        if 0 in lits:
            return True
        if not lits:
            return False
        res, _c = self._sat([_AND(self.S, lits)], 0b01)
        return res

    def test_lanes(self, word, n_act=None, n_hold=None):
        """Live lanes where the word changes, diverse in which of its bits change (round robin over
        the change masks, most frequent first; lanes spread within each), with no async control of
        the word active where there are such lanes, and lanes where it holds."""
        P = self.P
        ctl = self.ctl
        full = self._full(word)
        n_act = P["TEST_LANES_ACTIVE"] if n_act is None else n_act
        act = np.zeros(ctl.W, np.uint64)
        n = 64 * ctl.W
        cm = np.zeros(n, np.int64)
        for k, i in enumerate(word):
            act |= self._active(i, full)
            if k < 62:
                cm |= self._bits("a", i, full).astype(np.int64) << k
        aoff = self._async_off(word)
        if (act & aoff).any():
            act &= aoff
        live = np.full(ctl.W, ~np.uint64(0), np.uint64) if full else ctl.live
        noset = live.copy()
        for i in word:
            for L, _v in ctl.profile[i].sets:
                noset &= ~ctl.value(L)
        A = _lanes_of(act)
        hl = live & ~act & aoff
        H = _lanes_of(hl if hl.any() else live & ~act)
        pick = []
        A2 = _lanes_of(act & noset)            # changes that no clear or set explains: counting ones
        if len(A2) and len(A2) < len(A):
            pick = _spread(A2, n_act // 2)
        if len(A):
            vals, inv, cnt = np.unique(cm[A], return_inverse=True, return_counts=True)
            srt = np.argsort(inv, kind="stable")
            parts = np.split(A[srt], np.cumsum(cnt)[:-1])
            rank = sorted(range(len(vals)), key=lambda g: (-cnt[g], int(vals[g])))[:n_act]
            groups = [parts[g] for g in rank]
            depth = 0
            n0 = len(pick)
            while len(pick) < min(n_act, len(A)) and len(pick) - n0 < n_act:
                added = False
                for gr in groups:
                    if depth < len(gr) and len(pick) < n_act:
                        pick.append(int(gr[(depth * 7919) % len(gr)]) if depth else int(gr[len(gr) // 2]))
                        added = True
                if not added:
                    break
                depth += 1
            pick = list(dict.fromkeys(pick))
        return pick, _spread(H, P["TEST_LANES_HOLD"] if n_hold is None else n_hold)

    def _dependent_lanes(self, word):
        """Up to TEST_LANES_ACTIVE live lanes (spread) where the word changes, no async control of it
        is active, and its next state depends on its own state: three raw states (all zeros, all
        ones, alternating) do not all go to one value, as they do under a load or a reset. At most
        COUNTER_DEP_SCAN change lanes are simulated (spread over them)."""
        ctl, P = self.ctl, self.P
        full = self._full(word)
        act = np.zeros(ctl.W, np.uint64)
        for i in word:
            act |= self._active(i, full)
        aoff = self._async_off(word)
        if (act & aoff).any():
            act &= aoff
        A = _spread(_lanes_of(act), P["COUNTER_DEP_SCAN"])
        if not A:
            return []
        w = len(word)
        ns = 1 << w
        cone = self._cone(word)
        qset = {ctl.flops[i].q for i in word}
        ext = [s for s in cone.leaves if s not in qset]
        E = self._lane_bits(ext, A)
        alt = sum(1 << k for k in range(0, w, 2))
        F = self.states_eval(word, E, [0, ns - 1, alt], cone, ext)
        dep = (F != F[:, :1]).any(1)
        return _spread([l for l, d in zip(A, dep) if d], P["TEST_LANES_ACTIVE"])

    def states_eval(self, word, E, states, cone=None, ext=None):
        """Next raw states (variants, len(states)) of `word` with its other sources set per variant
        (E: (len(ext), variants) 0/1) and the word in each raw state of `states`."""
        cone = cone or self._cone(word)
        qs = [self.ctl.flops[i].q for i in word]
        qset = set(qs)
        ext = [s for s in cone.leaves if s not in qset] if ext is None else ext
        states = np.asarray(states, _sdt(len(word)))
        nv = E.shape[1] if E.ndim == 2 else 1
        n = nv * len(states)
        nw = -(-n // 64)
        rows = {}
        if len(ext):
            packed = _pack(np.repeat(E, len(states), axis=1))
            for s, r in zip(ext, packed):
                rows[s] = r
        for k, s in enumerate(qs):
            if s in cone.leaf_set:
                rows[s] = _pack(np.tile(((states >> k) & 1).astype(np.uint8), nv))
        outs = cone.eval(rows, nw)
        dt = _sdt(len(word))
        F = np.zeros(n, dt)
        for k, o in enumerate(outs):
            F |= _unpack(o, n).astype(dt) << k
        self.stats["sim_vectors"] += n
        return F.reshape(nv, len(states))

    def lit_eval(self, cone, word, ext, E, states, extra=()):
        """Values (variants, len(states)) of cone.lits[0] (a literal of the scratch graph over the
        word's states and the sources `ext`), and of the gate signals `extra` (a list of such
        arrays), with the word in each raw state and ext set per variant (E: (len(ext), variants))."""
        qs = [self.ctl.flops[i].q for i in word]
        states = np.asarray(states, _sdt(len(word)))
        nv = E.shape[1] if E.ndim == 2 else 1
        n = nv * len(states)
        nw = -(-n // 64)
        rows = {}
        if len(ext):
            packed = _pack(np.repeat(E, len(states), axis=1))
            for s, r in zip(ext, packed):
                rows[s] = r
        for k, s in enumerate(qs):
            rows[s] = _pack(np.tile(((states >> k) & 1).astype(np.uint8), nv))
        self.stats["sim_vectors"] += n
        if extra:
            outs, ex = cone.eval(rows, nw, extra)
            return (_unpack(outs[0], n).reshape(nv, len(states)).astype(bool),
                    [_unpack(x, n).reshape(nv, len(states)).astype(bool) for x in ex])
        outs = cone.eval(rows, nw)
        return _unpack(outs[0], n).reshape(nv, len(states)).astype(bool)

    def table(self, word, lanes):
        """(F, ext, E): next raw state per (lane, state) over all 2^w states, the word's other
        sources and their lane values."""
        cone = self._cone(word)
        qset = {self.ctl.flops[i].q for i in word}
        ext = [s for s in cone.leaves if s not in qset]
        E = self._lane_bits(ext, lanes)
        F = self.states_eval(word, E, np.arange(1 << len(word)), cone, ext)
        self.stats["tables"] += 1
        return F, ext, E

    def reset_raw(self, word):
        vals = [self.ctl.profile[i].reset for i in word]
        if any(v is None for v in vals):
            return None
        return sum(int(v) << k for k, v in enumerate(vals))

    # ------------------------------------------------------------------ word analysis
    def analyze_word(self, word, hint=None, quick=True, modes=True):
        """Counter test of one flop set (w <= EXHAUSTIVE_WIDTH): the interpretation with its
        lanes, or None (the reason counted in self.rejects). modes=False refuses a word whose lanes
        take several constant steps outright, as before the case-selected step: the tests that ask
        whether a neighbouring flop makes an ADDER under the word need that reading."""
        P = self.P
        w = len(word)
        if w == 0 or w > P["EXHAUSTIVE_WIDTH"]:
            return None
        mm = P["MODE_STEPS_MAX"] if modes else 0
        key = (tuple(word), None if hint is None else tuple(hint), mm)
        if key in self._tables:
            return self._tables[key]
        act, hold = self.test_lanes(word)
        if not act:
            self.rejects["no active lane"] += 1
            self._tables[key] = None
            return None
        reset_raw = self.reset_raw(word)
        if quick and len(act) > 4 and w > 4:
            Fq, _e, _E = self.table(word, act[:4])
            r = interpret(Fq, w, reset_raw, hint, P["REL_STEPS_MAX"], P["ORDER_TRIES"], mm)
            if not r["ok"] and r["why"] in _FIRM:
                self.rejects[r["why"]] += 1
                self._tables[key] = None
                return None
        lanes = act + hold
        F, ext, E = self.table(word, lanes)
        r = interpret(F, w, reset_raw, hint, P["REL_STEPS_MAX"], P["ORDER_TRIES"], mm)
        if not r["ok"] and r["why"] in _LANE_STARVED:
            # the change lanes drawn were loads or resets (the next state does not depend on the
            # word's own state there: a data load, a reset to an input value, a host write); draw
            # lanes where it does (counting, shifting or relative steps) and test again
            seen = set(act)
            more = [l for l in self._dependent_lanes(word) if l not in seen]
            if more:
                self.stats["lanes_redrawn"] += 1
                act = more + act
                lanes = act + hold
                F, ext, E = self.table(word, lanes)
                r = interpret(F, w, reset_raw, hint, P["REL_STEPS_MAX"], P["ORDER_TRIES"], mm)
        if not r["ok"]:
            self.rejects[r["why"]] += 1
            self._tables[key] = None
            return None
        r.update(word=list(word), F=F, ext=ext, E=E, lanes=lanes, reset_raw=reset_raw)
        self._pool_modes(r)
        if r["alt_steps"] and not self._mode_ok(r):
            # several constant steps that one source does not choose between: an addend, not a
            # case-selected step. Refused here, so every later test reads the word as _judge does
            # without the case split (the fragment and adder tests ask exactly that question).
            self.rejects["steps s and 2s (a two-bit addend: an adder)"] += 1
            self._tables[key] = None
            return None
        self._tables[key] = r
        return r

    def _pool_values(self, word, full=None):
        """(raw state, raw next state) of the word on every live lane (with full, on every pool
        lane: an awake word does not change on a live one, see _awake)."""
        ctl = self.ctl
        full = self._full(word) if full is None else full
        live = _lanes_of(np.full(ctl.W, ~np.uint64(0), np.uint64) if full else ctl.live)
        q = np.zeros(len(live), np.int64)
        f = np.zeros(len(live), np.int64)
        for k, i in enumerate(word[:62]):
            q |= self._bits("q", i)[live].astype(np.int64) << k
            f |= self._bits("f", i)[live].astype(np.int64) << k
        return live, q, f

    def _pool_modes(self, r):
        """Pool evidence under the interpretation: rarer modes (a down step when the tables saw
        only up, and the reverse; relative steps) confirmed by full tables on MODE_LANES pool lanes,
        and load evidence (distinct next values nothing else explains)."""
        P = self.P
        w = r["w"]
        ns = 1 << w
        word = r["word"]
        live, q, f = self._pool_values(word)
        vq, vf = r["vr"][q], r["vr"][f]
        d = (vf - vq) % ns
        s = r["step"]
        exc = np.zeros(ns, bool)
        for i in r["counting"]:
            exc |= i["stop"] | i["wrap"] | i["other"]
        free = ~exc[vq]
        up, down = (d == s % ns) & free, (d == (-s) % ns) & free
        extra = []
        if ns > 2:
            if not r["downs"] and down.any():
                extra += _spread(live[down], P["MODE_LANES"])
            if not r["ups"] and up.any():
                extra += _spread(live[up], P["MODE_LANES"])
        alt = np.zeros(len(d), bool)
        for a_ in r.get("alt_steps") or []:        # a case-selected second step is not unexplained
            alt |= (d == a_ % ns) | (d == (-a_) % ns)
        other = (d != 0) & ~up & ~down & ~(alt & free) & free
        if other.any():
            vals, cnt = np.unique(d[other], return_counts=True)
            for dv in vals[np.argsort(-cnt, kind="stable")][:P["REL_STEPS_MAX"]]:
                sel = other & (d == dv)
                if sel.sum() >= max(P["MODE_MIN_LANES"], sel.size * P["MODE_MIN_SHARE"]):
                    extra += _spread(live[sel], 2)
        r["pool"] = {"live": int(len(live)), "up": int(up.sum()), "down": int(down.sum()),
                     "unexplained": int(other.sum()), "unexplained_values": int(len(np.unique(vf[other])))}
        extra = [int(l) for l in dict.fromkeys(extra) if l not in set(r["lanes"])]
        if extra:
            F2, _ext, E2 = self.table(word, extra)
            F = np.concatenate([r["F"], F2])
            x = np.arange(ns)
            hold = (F == x[None, :]).all(1)
            const = (F == F[:, :1]).all(1) & ~hold
            r2 = _judge(F, ~hold & ~const, const, r["pi"], r["p"], w, r["reset_raw"], P["REL_STEPS_MAX"],
                        mode_max=P["MODE_STEPS_MAX"] if r.get("alt_steps") else 0)
            if r2["ok"]:
                keep = {k: r[k] for k in ("word", "ext", "reset_raw", "key2", "pool")}
                lanes = r["lanes"] + extra
                E = np.concatenate([r["E"], E2], axis=1)
                r.clear()
                r.update(r2)
                r.update(keep)
                r.update(F=F, E=E, lanes=lanes, hold_lanes=[int(l) for l in np.flatnonzero(hold)],
                         const_lanes=[int(l) for l in np.flatnonzero(const)])
            self.stats["mode_tables"] += 1
        r["load"] = bool(r["load"] or r["pool"]["unexplained_values"] >= P["LOAD_DISTINCT"]
                         or len(r["const_targets"]) >= P["LOAD_DISTINCT"])

    def _data_step(self, r):
        """Single-source flips on a counting lane give more than REL_STEPS_MAX other constant steps,
        or twice the count step (the next bit of an addend): an accumulator's word."""
        steps = self._flip_steps(r)
        ns = 1 << r["w"]
        s = r["step"] % ns
        return len(steps) > self.P["REL_STEPS_MAX"] or (ns > 4 and bool({(2 * s) % ns, (-2 * s) % ns} & steps))

    def _mode_ok(self, r):
        """A word whose lanes took several constant steps (r["alt_steps"]) counts with a
        case-selected step, not with a data addend: at most MODE_STEP_SOURCES of its other sources
        change the step when flipped alone on a counting state, and every step they give is one the
        lanes already took (an addend's bits each give their own weight, and their sums are new
        steps). This is the test _data_step makes for a single-step word."""
        ns = 1 << r["w"]
        allowed = set()
        for x in [r["step"]] + list(r["alt_steps"]):
            allowed |= {x % ns, (-x) % ns}
        hot = {s2: v for s2, v in self._flip_sources(r).items() if v}
        if len(hot) > self.P["MODE_STEP_SOURCES"]:
            return False
        return all(v <= allowed for v in hot.values())

    def _flip_sources(self, r, sample=None):
        """{source: the constant steps a counting lane takes when that one source is flipped}
        (_flip_steps, keyed by the source that gives each step)."""
        out = collections.defaultdict(set)
        for s2, st in self._flip_steps(r, sample, by_source=True):
            out[s2].add(st)
        for s2 in r["ext"]:
            out.setdefault(s2, set())
        return dict(out)

    def _flip_steps(self, r, sample=None, by_source=False):
        """Constant steps (other than the count step and 0) that a counting lane takes when one of the
        word's other sources is flipped, on a sample of its counting states: a counter's sources are
        enables, loads and modes; an accumulator's addend gives a step per addend bit. by_source:
        the (source, step) pairs instead of the steps."""
        w, ns = r["w"], 1 << r["w"]
        ext = r["ext"]
        steps = set()
        sample = self.P["FLIP_SAMPLE"] if sample is None else sample
        if not len(ext):
            return [] if by_source else steps
        for group in (r["ups"], r["downs"]):
            if not group:
                continue
            i = max(group, key=lambda i: (int(i["reg"].sum()), -i["lane"]))
            regs = r["rv"][np.flatnonzero(i["reg"])]
            X = regs[np.linspace(0, len(regs) - 1, min(sample, len(regs))).astype(np.int64)]
            vals = r["E"][:, i["lane"]]
            E = np.repeat(vals[:, None], len(ext), axis=1)
            E[np.arange(len(ext)), np.arange(len(ext))] ^= 1
            Fv = self.states_eval(r["word"], E, X, ext=ext)
            d = (r["vr"][Fv] - r["vr"][X][None, :]) % ns
            const = (d == d[:, :1]).all(1)
            hit = [(ext[k], int(d[k, 0])) for k in np.flatnonzero(const)
                   if d[k, 0] != 0 and int(d[k, 0]) not in (i["top"], (-i["top"]) % ns)]
            steps |= set(hit) if by_source else {x for _s2, x in hit}
        return sorted(steps) if by_source else steps

    # ------------------------------------------------------------------ conditions
    def _netted(self, s):
        return (2 * s) in self.ctl._net

    def _critical(self, lit, cex, restore):
        """Index of the first (source, value) of `restore` that alone makes `lit` 0 when set in
        the counterexample, else 0."""
        cone = _Cone(self.S, [lit])
        nv = len(restore)
        rows = {}
        for s in cone.leaves:
            b = np.full(nv, cex.get(s, 0), np.uint8)
            for k, (t, v) in enumerate(restore):
                if t == s:
                    b[k] = v
            rows[s] = _pack(b)
        out = _unpack(cone.eval(rows, -(-nv // 64))[0], nv)
        z = np.flatnonzero(out == 0)
        return int(z[0]) if len(z) else 0

    def generalize(self, word, miter, vals_of, states):
        """The sources a claim needs (a lane's values kept): `miter` (scratch literal over the word's
        states and other sources) is 1 exactly where the claim fails. Sources whose single flip
        makes it 1 on some state (simulated) are kept, then random flips of the rest (simulated)
        add critical ones, then SAT adds sources back from counterexamples until the miter is
        unsatisfiable. vals_of: {source: lane value}. Returns (sources, values) or None."""
        P = self.P
        cone = _Cone(self.S, [miter])
        qset = {self.ctl.flops[i].q for i in word}
        ext = [s for s in cone.leaves if s not in qset]
        vals = np.array([vals_of.get(s, 0) for s in ext], np.uint8)
        n = len(ext)
        rank = {k: r for r, k in enumerate(sorted(range(n), key=lambda k: (self.ctl.labels[ext[k]], ext[k])))}
        X = np.asarray(states, _sdt(len(word)))
        need = set()
        base = self.lit_eval(cone, word, ext, vals[:, None], X)
        if base.any():
            self.stats["generalize_lane_fails"] += 1
            return None
        if n:
            chunk = max(1, P["SENS_VECTORS"] // max(1, len(X)))
            for c0 in range(0, n, chunk):
                ks = list(range(c0, min(n, c0 + chunk)))
                E = np.repeat(vals[:, None], len(ks), axis=1)
                for col, k in enumerate(ks):
                    E[k, col] ^= 1
                bad = self.lit_eval(cone, word, ext, E, X).any(axis=1)
                need |= {ks[c] for c in np.flatnonzero(bad)}
        keep = sorted(need, key=lambda k: rank[k])
        keep = self._sim_refine(cone, word, ext, vals, X, keep, rank)
        for _it in range(P["GROW_LIMIT"]):
            if any(not self._netted(ext[k]) for k in keep):
                self.stats["cond_without_net"] += 1
                return None
            lits = [2 * ext[k] + (1 - int(vals[k])) for k in keep]
            res, cex = self._sat([miter], 0b01, lits)
            if res:
                keep = self._drop(miter, ext, vals, keep, rank)
                return [ext[k] for k in keep], [int(vals[k]) for k in keep]
            if res is None:
                self.stats["generalize_unknown"] += 1
                return None
            ks = set(keep)
            diff = [k for k in sorted(range(n), key=lambda k: rank[k]) if k not in ks and ext[k] in cex
                    and cex[ext[k]] != int(vals[k])]
            if not diff:
                self.stats["generalize_stuck"] += 1
                return None
            pick = self._critical(miter, cex, [(ext[k], int(vals[k])) for k in diff])
            keep.append(diff[pick])
            self.stats["cond_added_back"] += 1
        self.stats["generalize_limit"] += 1
        return None

    def _netify(self, bits, miter, lits, lane):
        """The count condition re-expressed over the netlist's own signals. `generalize` can only
        name the cone's leaves (the word's other flops and the primary inputs), so a condition the
        design writes as two internal signals (a FIFO level counts up under push & ~pop) comes back
        as a cube over every flop that drives them -- a condition far narrower than the design's,
        which then leaves states outside it where the word does not hold, and no hold obligation.
        Here the netted signals of the word's next-state cone, at the values the proof lane gives
        them, join the cube (so the conjunction still holds on that lane and still implies the
        claim), and then every literal that can go, goes: the ones that read the word's own state
        first (they cost a coverage obligation), then by support size, so the design's own high
        signals survive and the flops below them do not. Returns the literals."""
        S, ctl = self.S, self.ctl
        idx = S._source_index()
        own = 0
        for i in bits:
            own |= 1 << idx[ctl.flops[i].q]
        cands = []
        for s2 in self._cone(bits).gates:
            if not self._netted(s2) or 2 * s2 in {l & ~1 for l in lits} or (S.supp_bits(s2) & own):
                continue                  # a signal that reads the word is a stop or wrap condition,
                                          # not a re-expression of the enable: _find_nets offers those
            v = int(ctl.value(2 * s2)[lane >> 6] >> (lane & 63)) & 1
            sup = len(self.g.cone([2 * s2])[1])
            cands.append((-sup, ctl.labels[s2], s2, 2 * s2 + (1 - v)))
        if not cands:
            return lits
        cands.sort()
        keep = list(lits) + [c[-1] for c in cands[:self.P["NET_COND"]]]
        if self._sat([miter], 0b01, keep)[0] is not True:
            return lits                     # the lane's values do not imply the claim: keep the cube
        order = sorted(keep, key=lambda l: (bool(S.supp_bits(l >> 1) & own),
                                            len(self.g.cone([l])[1]), ctl.labels[l >> 1], l))
        for l in order:
            if len(keep) <= 1:
                break
            rest = [x for x in keep if x != l]
            if self._sat([miter], 0b01, rest)[0] is True:
                keep = rest
        if len(keep) < len(lits):
            self.stats["cond_netified"] += 1
        return sorted(keep, key=lambda l: (ctl.labels[l >> 1], l))

    def _drop(self, miter, ext, vals, keep, rank):
        """The condition made locally weakest: every literal whose removal still leaves the claim
        unrefutable is dropped (last by structural rank first, so the answer does not depend on ids).
        The sensitivity pass and the counterexample loop both add literals that a later addition
        makes redundant, and a condition narrower than the design's own count case leaves states
        outside it where the word does not hold -- which is what schema v2's hold obligation asks
        about. One SAT call per literal."""
        out = list(keep)
        for k in sorted(keep, key=lambda k: -rank[k]):
            if len(out) <= 1:
                break
            rest = [x for x in out if x != k]
            if self._sat([miter], 0b01, [2 * ext[x] + (1 - int(vals[x])) for x in rest])[0]:
                out = rest
                self.stats["cond_dropped"] += 1
        return sorted(out, key=lambda k: rank[k])

    def _sim_refine(self, cone, word, ext, vals, X, keep, rank):
        """Simulated refinement of a condition before SAT: variants that flip every source outside
        it with probability 1/2 (by structural rank, so any id permutation draws alike); in the first
        variant that breaks the claim, the flipped sources whose restoring alone repairs it are
        critical, and the first by rank joins the condition; until a round of variants passes."""
        P = self.P
        n = len(ext)
        keep = list(keep)
        ks = set(keep)
        rng = np.random.default_rng(1000003 * len(word) + n)
        nv = max(1, min(64, P["SENS_VECTORS"] // max(1, len(X))))
        for _it in range(P["GROW_LIMIT"]):
            fr = sorted((k for k in range(n) if k not in ks), key=lambda k: rank[k])
            if not fr:
                break
            E = np.repeat(np.asarray(vals, np.uint8)[:, None], nv, axis=1)
            E[fr, :] ^= rng.integers(0, 2, size=(len(fr), nv), dtype=np.uint8)
            bad = np.flatnonzero(self.lit_eval(cone, word, ext, E, X).any(axis=1))
            if not len(bad):
                break
            v = int(bad[0])
            D = [k for k in fr if E[k, v] != vals[k]]
            E2 = np.repeat(E[:, v:v + 1], len(D), axis=1)
            for c, k in enumerate(D):
                E2[k, c] = vals[k]
            fixed = np.flatnonzero(~self.lit_eval(cone, word, ext, E2, X).any(axis=1))
            k = D[int(fixed[0])] if len(fixed) else D[0]
            keep.append(k)
            ks.add(k)
            self.stats["cond_added_sim"] += 1
        return sorted(keep, key=lambda k: rank[k])

    def _find_nets(self, word, lane_vals, states, want1, want0):
        """Literals of netted gates in the word's next-state cone that are 1 on every state of
        want1 and 0 on every state of want0 on the lane (either polarity); fewest sources first,
        and the ones that read the word's own state last. A self-reading net (a compare of the word
        against a limit or a reload register at its terminal count) is a candidate only under
        SELF_COVERAGE, and the caller still has to discharge the coverage obligation for it
        (_covers); with SELF_CONDITIONS it is one without the obligation."""
        cone = self._cone(word)
        cands = [s for s in cone.gates if self._netted(s)]
        idx = self.S._source_index()
        own = 0
        for i in word:
            own |= 1 << idx[self.ctl.flops[i].q]
        if not (self.P["SELF_CONDITIONS"] or self.P["SELF_COVERAGE"]):
            cands = [s for s in cands if not (self.S.supp_bits(s) & own)]
        if not cands or not want1.any() or not want0.any():
            return []
        qset = {self.ctl.flops[i].q for i in word}
        ext = [s for s in cone.leaves if s not in qset]
        vals = np.array([lane_vals.get(s, 0) for s in ext], np.uint8)[:, None]
        c2 = _Cone.__new__(_Cone)
        c2.g, c2.lits, c2.gates, c2.leaves, c2.leaf_set = self.g, [0], cone.gates, cone.leaves, cone.leaf_set
        _o, ex = self.lit_eval(c2, word, ext, vals, states, extra=cands)
        out = []
        for s, row in zip(cands, ex):
            r = row[0]
            if r[want1].all() and not r[want0].any():
                out.append(2 * s)
            elif not r[want1].any() and r[want0].all():
                out.append(2 * s + 1)
        if len(out) > 1:
            sup = {l: len(self.g.cone([l])[1]) for l in out}
            out.sort(key=lambda l: (bool(self.S.supp_bits(l >> 1) & own), sup[l], self.ctl.labels[l >> 1], l))
        plain = [l for l in out if not (self.S.supp_bits(l >> 1) & own)][:self.P["NET_TRIES"]]
        selfr = [l for l in out if self.S.supp_bits(l >> 1) & own][:self.P["NET_TRIES"]]
        return plain + selfr

    # ------------------------------------------------------------------ proofs (schema v2)
    def _states(self, w, lane_row=None, extra=()):
        """States to simulate: all of them up to EXHAUSTIVE_WIDTH, else random states (seeded by the
        width), the carry boundaries of every bit (low bits all ones or all zeros, the rest random)
        and `extra`."""
        if w <= self.P["EXHAUSTIVE_WIDTH"]:
            return np.arange(1 << w, dtype=np.int64)
        rng = np.random.default_rng(7919 * w + 17)
        dt = _sdt(w)
        cap = (1 << w) - 1
        n = self.P["WIDE_SAMPLES"]
        x = _rand_states(rng, n, w)
        hi = _rand_states(rng, w, w)
        low = np.array([(1 << k) - 1 for k in range(w)], dt)
        b1 = (hi & ~low) | low            # bits 0..k-1 ones
        b0 = hi & ~low                    # bits 0..k-1 zeros
        return np.unique(np.concatenate([x, b1, b0, np.array([0, cap] + [int(e) for e in extra], dt)]) & cap)

    def _value_lits(self, m):
        return [2 * self.ctl.flops[b].q ^ c for b, c in zip(m["bits"], m["comp"])]

    def _reset_case(self, m):
        """Synchronous reset case of a word: the reset literal's net forces every bit (proven)."""
        R = self.ctl.reset
        if R.kind != "sync":
            return None
        cond = self.ctl.cond([R.lit])
        vals = [self.ctl.profile[i].reset for i in m["bits"]]
        if cond is None or any(v is None for v in vals) or self._reads_own(R.lit, m["bits"]):
            return None
        S = self.S
        aoff = self._async_lit(m["bits"])
        diff = _OR(S, [_mk(S, _XOR2, self.ctl.f(i), int(v)) for i, v in zip(m["bits"], vals)])
        if self._unsat([R.lit, aoff, diff]) is not True:
            return None
        if self._unsat([R.lit, aoff]) is not False:
            return None
        return {"lit": R.lit, "cond": cond, "values": [int(v) for v in vals]}

    def _lane_view(self, m, d, bits, cone, ext, vals, X, M, sat):
        """On one assignment of the word's other sources: (value states, value next states, the
        template's next values, the domain mask, the exceptions: domain states off the template)."""
        w = len(bits)
        lv = np.array([vals.get(s, 0) for s in ext], np.uint8)
        F = self.states_eval(bits, lv[:, None], X, cone, ext)[0]
        c = sum(int(b) << k for k, b in enumerate(m["comp"]))
        vx, vf = X ^ c, F ^ c
        Tv, dm = template_values(vx, d, m["step"], M, sat, w)
        return vx, vf, Tv, dm, dm & (vf != Tv)

    def _wide_exceptions(self, m, d, bits, vals, M, sat, aoff):
        """States of a wide word where the template fails under the source values (SAT, blocked
        one by one; WIDE_EXCEPTIONS at most)."""
        S, ctl = self.S, self.ctl
        T, dom = template_lits(S, self._value_lits(m), d, m["step"], M, sat)
        diff = _OR(S, [_mk(S, _XOR2, ctl.f(b), t ^ c) for b, t, c in zip(bits, T, m["comp"])])
        mit = _AND(S, [dom, diff, aoff])
        qset = {ctl.flops[i].q for i in bits}
        lits = [2 * s + (1 - int(v)) for s, v in vals.items() if s not in qset]
        found = []
        for _k in range(self.P["WIDE_EXCEPTIONS"]):
            block = [[2 * ctl.flops[b].q + ((int(x) >> k) & 1) for k, b in enumerate(bits)] for x in found]
            res, cex = self._sat([mit], 0b01, lits, extra=block)
            if res is not False:
                break
            found.append(sum(int(cex.get(ctl.flops[b].q, 0)) << k for k, b in enumerate(bits)))
        return found

    def _regularize(self, m, d, bits, vals, X_exc, X_ok, M, sat, aoff):
        """Source values under which the word follows the template at the exceptional states (a
        reload at the terminal count from a register set to the natural wrap target, a clear at a
        compare with a register set out of the way) and at some counting states: SAT over the next
        states with the word's state substituted, or None. The rest keeps the lane's values."""
        S, ctl = self.S, self.ctl
        w = len(bits)
        c = sum(int(b) << k for k, b in enumerate(m["comp"]))
        qs = [ctl.flops[b].q for b in bits]
        lits = [aoff]
        for x in list(X_exc) + list(X_ok):
            raw = int(x)
            vx = raw ^ c
            t = int(template_values(np.array([vx], _sdt(w)), d, m["step"], M, sat, w)[0][0]) ^ c
            repl = {q: (raw >> k) & 1 for k, q in enumerate(qs)}
            memo = {}
            for k, b in enumerate(bits):
                fk = S.substitute(ctl.f(b), repl, memo)
                lits.append(fk if (t >> k) & 1 else fk ^ 1)
        res, cex = self._sat([_AND(S, lits)], 0b01)
        if res is not False:
            return None
        return {s: int(v) for s, v in cex.items() if s not in set(qs)}

    def _adapt(self, d, vx, vf, exc, w, M, sat, step=1):
        """A template that absorbs the lane's single exceptional state: counting up, a stop at x
        (saturating at x) or a wrap from x onto 0 (modulus x + 1); counting down, a wrap from 0
        onto y (modulus y + 1) or a stop at 0 (saturating). (M, sat) or None. A template the width
        does not admit (schema v2: 2^(w-1) < modulus <= 2^w, a limit >= 2^(w-1)) is not one: the
        lane's stop or reload point is then a register's value, not the word's modulus, and the
        word proves on its whole range with that compare in the condition instead (_prove_dir)."""
        xs = np.flatnonzero(exc)
        if len(xs) != 1 or M is not None or sat:
            return None
        x, y = int(vx[xs[0]]), int(vf[xs[0]])
        out = None
        if d == "up":
            if y == x:
                out = (x + 1, True)
            elif y == 0:
                out = (x + 1, False)
        else:
            if x == 0 and y == 0:
                out = (None, True)
            elif x == 0 and 0 < y < (1 << w) - 1:
                out = (y + 1, False)
        if out is not None and not template_ok(w, out[0], out[1], step):
            self.rejects["the lane's stop or wrap point does not match the width (a register sets it)"] += 1
            return None
        return out

    def _reads_own(self, lit, word):
        """The literal's support holds a flop of the word (a condition reads its own word)."""
        idx = self.S._source_index()
        own = 0
        for i in word:
            own |= 1 << idx[self.ctl.flops[i].q]
        return bool(self.S.supp_bits(lit >> 1) & own)

    def _own_read(self, lits, bits):
        """Word-bit positions (LSB first) of the word's own flops that the literals read."""
        idx = self.S._source_index()
        ls = [l for l in lits if l not in (0, 1)]
        out = []
        for k, i in enumerate(bits):
            b = 1 << idx[self.ctl.flops[i].q]
            if any(self.S.supp_bits(l >> 1) & b for l in ls):
                out.append(k)
        return out

    def _covers(self, region, cond, bits, comp, M, sat, lane=None):
        """Schema v2's coverage obligation, as the harness checks it (verify._coverage): the
        defining region (a list of literals, the domain and the async controls among them) must be
        satisfiable for every value of the word in range. Only the own bits the region's literals
        read matter; each assignment of them that an in-range value realizes costs one SAT call,
        and COVER_VECTORS random assignments of the other sources are simulated first so the common
        case costs none. Past HARNESS_COVERAGE_MAX_OWN_BITS own bits read, or past COVER_SAT calls, the word
        is refused (never admitted), as the harness refuses it.
        `region` is the whole conjunction (the domain and the async controls among it); `cond` are
        the condition literals alone -- the domain reads every own bit by construction and is not a
        condition, so it does not enter the enumeration."""
        P, ctl = self.P, self.ctl
        w = len(bits)
        pos = self._own_read(cond, bits)
        if not pos:
            return True
        if len(pos) > P["HARNESS_COVERAGE_MAX_OWN_BITS"]:
            self.rejects["conditions read too many of the word's own bits for the coverage check"] += 1
            return False
        ns = 1 << w
        top = ((M - 1) if M is not None else ns - 1) if sat else ((M or ns) - 1)
        c = sum(int(b) << k for k, b in enumerate(comp))
        # assignments of the read bits that some in-range value realizes: the smallest value with
        # those bits set and the rest 0 must be <= top
        want = [a for a in range(1 << len(pos))
                if sum(((a >> j) & 1) << pk for j, pk in enumerate(pos)) <= top]
        lit = _AND(self.S, list(region))
        cone = _Cone(self.S, [lit])
        qset = {ctl.flops[i].q for i in bits}
        ext = [x for x in cone.leaves if x not in qset]
        base = np.array([int(self._lane_bits([x], [lane])[0, 0]) if lane is not None else 0 for x in ext], np.uint8) \
            if ext else np.zeros(0, np.uint8)
        rng = np.random.default_rng(1000003 * w + len(ext) + 7919 * len(pos))
        nv = max(1, P["COVER_VECTORS"])
        E = np.repeat(base[:, None], nv, axis=1)
        if len(ext):
            E[:, 1:] ^= rng.integers(0, 2, size=(len(ext), nv - 1), dtype=np.uint8)
        states = np.array([sum(((a >> j) & 1) << pk for j, pk in enumerate(pos)) ^ c for a in want], _sdt(w))
        seen = self.lit_eval(cone, bits, ext, E, states).any(axis=0) if len(want) else np.zeros(0, bool)
        todo = [want[k] for k in np.flatnonzero(~seen)]
        if len(todo) > P["COVER_SAT"]:
            self.rejects["the defining case is not reachable for every value of the word"] += 1
            return False
        for a in todo:
            ql = [2 * ctl.flops[bits[pk]].q + (1 - (((a >> j) & 1) ^ int(comp[pk])))
                  for j, pk in enumerate(pos)]
            if self._unsat(list(region) + ql) is not False:
                self.rejects["the defining case is not reachable for every value of the word"] += 1
                return False
        self.stats["coverage_checked"] += 1
        return True

    def _prove_dir(self, m, d, lane, nres, aoff, nload, tmpl, adapt):
        """One direction's count condition on one pool lane: {"lits", "cond", "load", "flops",
        "template"} or None. Exceptions to the template on the lane are absorbed, in order, by a
        template that fits the lane (single-direction words: a modulus or a saturation point that
        a register sets, and only one the width admits), by other values of the sources that set
        them (a reload or a compare register), or by nets (an enable or a load select). A net that
        reads the word's own state -- a compare at a terminal count -- is tried last and only with
        the coverage obligation discharged (_covers), which is what schema v2 admits it under.
        `nres` and `nload` are the literals "outside every reset case" and "outside every load case
        named so far" (1 when none is); res["load"] is the ONE further load case this direction
        needed, which the caller adds to the list."""
        S, ctl = self.S, self.ctl
        bits, w = m["bits"], len(m["bits"])
        cone = self._cone(bits)
        qset = {ctl.flops[i].q for i in bits}
        ext = [s for s in cone.leaves if s not in qset]
        vals = dict(zip(ext, self._lane_bits(ext, [lane])[:, 0].tolist()))
        vals0 = dict(vals)
        M, sat = tmpl
        X = self._states(w)
        wide = w > self.P["EXHAUSTIVE_WIDTH"]
        seen = np.zeros(0, _sdt(w))          # exceptional states met so far: all must turn regular
        tried_adapt = False
        for _round in range(self.P["REGULARIZE_ROUNDS"] + 1):
            if wide:
                found = self._wide_exceptions(m, d, bits, vals, M, sat, aoff)
                if found:
                    X = np.unique(np.concatenate([X, np.asarray(found, _sdt(w))]))
            vx, vf, Tv, dm, exc = self._lane_view(m, d, bits, cone, ext, vals, X, M, sat)
            if not exc.any():
                break
            ok_states = X[dm & ~exc]
            nk = min(self.P["REGULARIZE_OK_STATES"], len(ok_states))
            pick = ok_states[np.linspace(0, len(ok_states) - 1, nk).astype(np.int64)] \
                if len(ok_states) else ok_states
            # a load (a reload, a clear at a compare) first gets other register values (the natural
            # wrap target: every exceptional state met so far must turn regular), a stop first gets a
            # template that stops there; when the rounds run out, the lane's own values come back
            # and the template adapts to it
            seen = np.unique(np.concatenate([seen, X[exc][:self.P["WIDE_EXCEPTIONS"]]]))
            loads_first = bool((exc & (vf != vx)).any()) and _round < self.P["REGULARIZE_ROUNDS"]
            if loads_first:
                new = self._regularize(m, d, bits, vals, seen, pick, M, sat, aoff)
                if new is not None:
                    vals.update(new)
                    self.stats["lane_regularized"] += 1
                    continue
            if adapt and not tried_adapt:
                tried_adapt = True
                if loads_first or _round:
                    vals = dict(vals0)
                    vx, vf, Tv, dm, exc = self._lane_view(m, d, bits, cone, ext, vals, X, M, sat)
                t2 = self._adapt(d, vx, vf, exc, w, M, sat, m["step"])
                if t2 is not None:
                    M, sat = t2
                    self.stats["template_adapted"] += 1
                    continue
            if not loads_first and _round < self.P["REGULARIZE_ROUNDS"]:
                new = self._regularize(m, d, bits, vals, seen, pick, M, sat, aoff)
                if new is not None:
                    vals.update(new)
                    self.stats["lane_regularized"] += 1
                    continue
            break
        vx, vf, Tv, dm, exc = self._lane_view(m, d, bits, cone, ext, vals, X, M, sat)
        stops = exc & (vf == vx)
        loads = exc & ~stops
        ok = dm & ~exc
        en_opts, load_opts = [None], [None]
        if stops.any():
            en_opts = self._find_nets(bits, vals, X, ok, stops)
            if not en_opts:
                self.rejects["no enable net for state-dependent stops"] += 1
                return None
        if loads.any():
            # a load case named earlier may already hide these states: try "no further case" first
            load_opts = ([None] if nload != 1 else []) + self._find_nets(bits, vals, X, loads, ok)
            if not load_opts:
                self.rejects["no load net for irregular transitions"] += 1
                return None
        T, dom = template_lits(S, self._value_lits(m), d, m["step"], M, sat)
        diff = _OR(S, [_mk(S, _XOR2, ctl.f(b), t ^ c) for b, t, c in zip(bits, T, m["comp"])])
        for en in en_opts:
            for ld in load_opts:
                parts = [dom, nres, aoff, diff] + ([nload] if nload != 1 else [])
                if en is not None:
                    parts.append(en)
                if ld is not None:
                    parts.append(ld ^ 1)
                miter = _AND(S, parts)
                cone2 = _Cone(S, [miter])
                allv = dict(vals)
                for s2 in cone2.leaves:
                    if s2 not in allv and s2 not in qset:
                        allv[s2] = int(self._lane_bits([s2], [lane])[0, 0])
                g = self.generalize(bits, miter, allv, X)
                if g is None:
                    continue
                srcs, vs = g
                lits = [2 * s2 + (1 - v) for s2, v in zip(srcs, vs)] + ([en] if en is not None else [])
                # the emitted condition is re-expressed over the netlist's own signals; the cube over
                # the cone's leaves stays as "lits", because the fragment, truncation and cascade
                # tests read the flop states a count condition pins
                out = self._netify(bits, miter, lits, lane) if len(lits) > 1 else list(lits)
                cond = ctl.cond(out)
                if cond is None:
                    continue
                tl = ([nload] if nload != 1 else []) + ([ld ^ 1] if ld is not None else [])
                cnd = out + ([nres] if nres != 1 else []) + tl
                nv = [dom, nres, aoff] + out + tl
                if self._unsat(nv) is not False:
                    self.stats["vacuous_when"] += 1
                    continue
                if not self._covers(nv, cnd, bits, m["comp"], M, sat, lane):
                    continue
                fl = sorted({self.q2flop[s2] for s2 in srcs if s2 in self.q2flop} - set(bits))
                return {"lits": lits, "out": out, "cond": cond, "load": ld, "en": en, "lane": int(lane),
                        "flops": fl, "template": (M, sat)}
        return None

    def _enable_net(self, m, d, res, nres, aoff, nload, tmpl):
        """The design's own count enable in place of a direction's lane cube: a netted literal the
        cube implies and under which the template still holds, the weakest (most lanes) first.
        The cube pins the sources one lane happened to have, so the word keeps counting outside it
        and the hold obligation fails; the enable net is the condition the design itself uses, and
        outside it the word holds or takes a case the reset or the load covers. Returns the literal
        or None. A self-reading enable (a stop or a wrap at a terminal count) is admitted only with
        the coverage obligation discharged, as in _prove_dir."""
        S, ctl = self.S, self.ctl
        bits = m["bits"]
        M, sat = tmpl
        cube = _AND(S, res["lits"])
        cv = ctl.value(cube)
        if not cv.any():
            return None
        cands = []
        own = 0
        idx = S._source_index()
        for i in bits:
            own |= 1 << idx[ctl.flops[i].q]
        for s2 in self._cone(bits).gates:
            if not self._netted(s2):
                continue
            if (S.supp_bits(s2) & own) and not (self.P["SELF_CONDITIONS"] or self.P["SELF_COVERAGE"]):
                continue
            for lit in (2 * s2, 2 * s2 + 1):
                v = ctl.value(lit)
                if (cv & ~v).any() or not (~v & ctl.live).any():
                    continue                       # the cube must imply it, and it must not be all lanes
                cands.append((-_pc(v), ctl.labels[s2], s2, lit))
        if not cands:
            return None
        cands.sort()
        T, dom = template_lits(S, self._value_lits(m), d, m["step"], M, sat)
        diff = _OR(S, [_mk(S, _XOR2, ctl.f(b), t ^ c) for b, t, c in zip(bits, T, m["comp"])])
        tail = ([nload] if nload != 1 else [])
        for _n, _lb, _s2, lit in cands[:self.P["ENABLE_TRIES"]]:
            if ctl.cond([lit]) is None:
                continue
            if self._unsat([lit, dom, nres, aoff, diff] + tail) is not True:
                continue
            nv = [dom, nres, aoff, lit] + tail
            if self._unsat(nv) is not False:
                continue
            if not self._covers(nv, [lit] + ([nres] if nres != 1 else []) + tail, bits, m["comp"], M, sat,
                                res["lane"]):
                continue
            self.stats["when_weakened"] += 1
            return lit
        return None

    def _const_case(self, lit, bits, aoff, nload, dom=1, extra=()):
        """Under `lit` (and the async controls and every load case inactive, and `extra`: the
        complements of the reset cases named before this one) every flop of the word takes a
        constant: the per-flop values, or None. A clear outside the count case (a counter that
        restarts instead of holding) is such a case, and schema v2's reset cases are what state it:
        the harness checks q' = that case's value there, and with the defining case they then cover
        every state, so the hold obligation is discharged without a load hiding anything."""
        S, ctl = self.S, self.ctl
        tail = ([nload] if nload != 1 else []) + ([dom] if dom != 1 else []) + list(extra)
        vals = []
        for b in bits:
            f = ctl.f(b)
            if self._unsat([lit, aoff, f] + tail) is True:
                vals.append(0)
            elif self._unsat([lit, aoff, f ^ 1] + tail) is True:
                vals.append(1)
            else:
                return None
        if self._unsat([lit, aoff] + tail) is not False:
            return None
        return vals

    def _reset_net(self, m, aoff, nload, notwhen, diffh, dom=1, taken=(), need_hold=True):
        """One further reset case of the word: a netted literal under which every flop takes a
        constant, and outside which (and outside the count cases, the load cases and the reset cases
        already `taken`) the word holds. A counter that clears instead of holding -- `else cnt <= 0`,
        or a pointer that clears AND reloads -- has no hold states at all otherwise, and the harness
        requires the hold obligation; naming each restart makes the defining and reset cases cover
        everything and the hold case is then honestly empty. With need_hold false the case is
        accepted without closing the hold obligation on its own, which is what lets a word that
        clears from two places name the first case and then look for the second. Pool lanes screen
        the candidates (the next state must be the same on every lane where the literal holds), SAT
        decides. (literal, values) or None."""
        S, ctl = self.S, self.ctl
        bits = m["bits"]
        ntaken = [l ^ 1 for l in taken]
        rows = [ctl.value(ctl.f(b)) for b in bits]
        live = ctl.live
        cone = self._cone(bits)
        cands = []
        for s2 in list(cone.gates) + list(cone.leaves):
            if not self._netted(s2):
                continue
            for lit in (2 * s2, 2 * s2 + 1):
                v = ctl.value(lit) & live
                n = _pc(v)
                if not n or n == _pc(live):
                    continue
                if all(not (r & v).any() or not (~r & v).any() for r in rows):
                    cands.append((-n, ctl.labels[s2], s2, lit))
        cands.sort()
        tail = ([nload] if nload != 1 else [])
        for _n, _lb, _s2, lit in cands[:self.P["RESET_TRIES"]]:
            if lit in taken or (lit ^ 1) in taken or ctl.cond([lit]) is None:
                continue
            # the case is proven where it applies and no case named before it does, so overlapping
            # clears with different values cannot contradict each other (the RTL's else-if priority)
            vals = self._const_case(lit, bits, aoff, nload, dom, ntaken)
            if vals is None:
                continue
            if not need_hold:
                # progress: the case must cover states the word neither counts nor holds on, else
                # naming it only shrinks the hold region for nothing
                if self._unsat(notwhen + ntaken + [lit, aoff, diffh, dom] + tail) is False:
                    self.stats["reset_net_partial"] += 1
                    return lit, vals
                continue
            if self._unsat(notwhen + ntaken + [lit ^ 1, aoff, diffh, dom] + tail) is True:
                self.stats["reset_net"] += 1
                return lit, vals
        return None

    def _eval_at(self, sigs, cex):
        """Values of the signals under a SAT counterexample (leaves it leaves free count as 0)."""
        sigs = sorted(set(sigs))
        if not sigs:
            return {}
        cone = _Cone(self.S, [2 * x for x in sigs])
        rows = {x: _pack(np.array([int(cex.get(x, 0))], np.uint8)) for x in cone.leaves}
        outs = cone.eval(rows, 1)
        return {x: int(_unpack(o, 1)[0]) for x, o in zip(sigs, outs)}

    def _load_cubes(self, m, when, nres, aoff, diffh, tmpl, srcs, nload=1, cap=1, dom=1):
        """Load cases (opaque, never defining) covering the states outside every count case and
        outside every case named so far where the word does not hold: counterexample-guided, one
        case per counterexample, at most `cap` of them (schema v2.1's control.load is a LIST, so a
        word that does not hold for two unrelated reasons -- a FIFO level pushed and popped at once
        AND reloaded on a flush -- can name both instead of failing the hold obligation).
        Each cube takes the sources the count cases name at the values one such state gives them (a
        FIFO level that counts up under push & ~pop and down under pop & ~push does not hold under
        push & pop when it is empty, and [push, pop] is the cube that hides that case), then drops
        every literal it can while every count case still proves and still has states of its own
        outside the union of the cases. Returns the list of literal lists (the whole union closes
        the hold obligation) or None; an empty list means hold already held."""
        S, ctl = self.S, self.ctl
        bits = m["bits"]
        V = self._value_lits(m)
        notwhen = [_AND(S, r["out"]) ^ 1 for r in when.values()]
        doms, diffs = {}, {}
        for d2 in when:
            T, doms[d2] = template_lits(S, V, d2, m["step"], *tmpl)
            diffs[d2] = _OR(S, [_mk(S, _XOR2, ctl.f(b), t ^ c) for b, t, c in zip(bits, T, m["comp"])])
        cubes = []

        def outside(extra=()):
            """The literal "outside every load case named so far, and outside `extra`"."""
            ls = ([nload] if nload != 1 else []) + [_AND(S, c) ^ 1 for c in cubes] \
                + [_AND(S, c) ^ 1 for c in extra]
            return _AND(S, ls) if ls else 1

        def fits(extra):
            """Every count case still proves outside the union of the load cases (a load found
            earlier for a reload may only be replaced by a set that covers that reload too), and no
            count case loses all its own states to them (a load over a count case would leave that
            direction with nothing to prove)."""
            if any(ctl.cond(c) is None for c in extra):
                return False
            nl2 = outside(extra)
            for d2 in when:
                base = [doms[d2], nres, aoff] + ([nl2] if nl2 != 1 else []) + when[d2]["out"]
                if self._unsat(base + [diffs[d2]]) is not True or self._unsat(base) is not False:
                    return False
            return True

        for _round in range(cap):
            nl2 = outside()
            res, cex = self._sat([_AND(S, notwhen + [nres, aoff, diffh, dom] + ([nl2] if nl2 != 1 else []))], 0b01)
            if res is True:
                return cubes                      # unsat: the word holds outside every named case
            if res is not False:
                self.stats["load_cube_unknown"] += 1
                return None                       # unknown
            at = self._eval_at(srcs, cex)
            cube = [2 * x + (1 - at[x]) for x in srcs]
            if not cube or ctl.cond(cube) is None:
                self.stats["load_cube_not_a_cond"] += 1
                return None
            if not fits([cube]):
                self.stats["load_cube_unfit"] += 1
                return None
            keep = list(cube)
            for l in sorted(cube, key=lambda l: (ctl.labels[l >> 1], l), reverse=True):
                rest = [x for x in keep if x != l]
                if rest and fits([rest]):
                    keep = rest
            cubes.append(keep)
            self.stats["load_cube"] += 1
        nl2 = outside()
        if self._unsat(notwhen + [nres, aoff, diffh, dom, nl2]) is True:
            return cubes
        self.stats["load_cube_exhausted"] += 1
        return None

    def prove(self, m):
        """Schema-v2.1 control for a counter model m = {bits (LSB first), comp, step, modulus,
        saturating, dirs {up|down: [pool lanes]}}: {"when": {d: case}, "resets": [{"base", "values",
        "cond"}], "loads": [literal list], "load_conds", "nres", "nload", "hold",
        "template": (modulus, saturating)} or None.

        control.hold is required and proven here: the count case is first weakened to the design's
        own enable net (_enable_net), then, while the word restarts instead of holding outside the
        cases named so far, further RESET cases are named (a netted literal under which every flop
        takes a constant, _reset_net -- at most RESET_CASES), and only then do LOAD cases get tried
        (at most LOAD_CASES). Schema v2.1 makes control.reset a list of cases and control.load a list
        of CONDs, which is what lets a counter that clears AND reloads -- a FIFO pointer, a serial
        position counter, a timer -- state every case it has instead of failing the hold
        obligation with one COND apiece. Reset cases are preferred over load cases at every step
        because a reset case is CHECKED by the harness (q' = the case's value) while a load case is
        opaque.

        Each case carries its own base literals; the COND emitted for case i is its base plus the
        complements of the single-literal cases before it, so the else-if priority the RTL wrote is
        explicit and two cases cannot disagree on a state. The regions this method proves on are
        derived from THOSE literal lists (nres_for), never from the bases alone: dropping a case
        changes what the harness's "outside every reset case" means, and a proof taken before the
        drop would no longer be about the structure that is emitted. The last block re-proves
        everything against the final lists for the same reason."""
        S = self.S
        bits = m["bits"]
        aoff = self._async_lit(bits)
        resets = []                      # each {"base": [literals], "values": [0|1 per bit]}
        r0 = self._reset_case(m)
        if r0:
            resets.append({"base": [r0["lit"]], "values": r0["values"]})
        loads = []                       # each a literal list (a cube over netted signals)

        def case_lits(i, rs):
            """The literals of reset case i as they are EMITTED: its own base, then the complements
            of the single-literal cases before it (a multi-literal case's complement is not a
            conjunction, so it cannot go into a COND and is left out)."""
            return list(rs[i]["base"]) + [r["base"][0] ^ 1 for r in rs[:i] if len(r["base"]) == 1]

        def nres_for(rs):
            """"Outside every reset case", exactly as the harness builds it from the emitted CONDs."""
            ls = [_AND(S, case_lits(i, rs)) ^ 1 for i in range(len(rs))]
            return _AND(S, ls) if ls else 1

        def nload_of():
            ls = [_AND(S, c) ^ 1 for c in loads]
            return _AND(S, ls) if ls else 1

        nres, nload = nres_for(resets), nload_of()
        when = {}
        tmpl = (m["modulus"], m["saturating"])
        dirs = [d for d in ("up", "down") if m["dirs"].get(d)]
        adapt = len(dirs) == 1
        for d in dirs:
            res = None
            for lane in m["dirs"][d][:self.P["LANE_TRIES"]]:
                res = self._prove_dir(m, d, lane, nres, aoff, nload, tmpl, adapt)
                if res is not None:
                    break
            if res is None:
                self.rejects[f"{d} count not proven"] += 1
                continue
            res.setdefault("out", list(res["lits"]))
            when[d] = res
            tmpl = res["template"]
            if res["load"] is not None and len(loads) < self.P["LOAD_CASES"]:
                loads.append([res["load"]])
                nload = nload_of()
        if not when:
            return None
        V = self._value_lits(m)
        if loads:
            # a load case found by the second direction also bounds the first: every direction must
            # still prove outside the whole set
            for d, res in when.items():
                T, dom = template_lits(S, V, d, m["step"], *tmpl)
                if self._unsat([dom, nres, aoff, nload] + res["lits"]) is not False:
                    return None
        for d, res in when.items():
            lit = self._enable_net(m, d, res, nres, aoff, nload, tmpl)
            if lit is not None:
                res["out"] = [lit]
        # hold: outside every when, every reset case and every load case. A count case that restarts
        # the word instead of holding it gets its complement as a reset case (the defining and reset
        # cases then cover every state, which the harness accepts with no load); failing that, a when
        # literal may become a load case (a clear or a data load outside the count case), and last
        # the counterexample-guided load cubes.
        diffh = _OR(S, [_mk(S, _XOR2, self.ctl.f(i), 2 * self.ctl.flops[i].q) for i in bits])
        # The hold obligation carries the DOMAIN, exactly as the harness states it (verify._hold_reset
        # takes the same `dom` as the defining case): a word with a modulus or a saturation limit
        # below 2^w - 1 says nothing about states above the limit, so requiring it to hold there was
        # this module refusing itself structures the harness would have verified -- a FIFO level that
        # saturates at 4 in 3 bits does whatever the encoder leaves it doing at 5, 6 and 7.
        dom0 = template_lits(S, V, next(iter(when)), m["step"], *tmpl)[1]

        def hold_ok(nl_, notwhen, nr):
            return self._unsat(notwhen + [nr, aoff, diffh, dom0] + ([nl_] if nl_ != 1 else [])) is True

        def notw():
            return [_AND(S, r["out"]) ^ 1 for r in when.values()]

        def dirs_ok(nr, nl_, extra_off=(), cover=False):
            """Every count case still proves, and still has states of its own, under (nr, nl_);
            with cover, also the coverage obligation the harness will put on the final region."""
            for d2, r2 in when.items():
                T, dom = template_lits(S, V, d2, m["step"], *tmpl)
                diff = _OR(S, [_mk(S, _XOR2, self.ctl.f(b), t ^ c)
                               for b, t, c in zip(bits, T, m["comp"])])
                tl = list(extra_off) + ([nl_] if nl_ != 1 else [])
                base = [dom, nr, aoff] + tl + r2["out"]
                if self._unsat(base + [diff]) is not True or self._unsat(base) is not False:
                    return False
                if cover and not self._covers(base, r2["out"] + ([nr] if nr != 1 else []) + tl,
                                              bits, m["comp"], tmpl[0], tmpl[1], r2["lane"]):
                    return False
            return True

        def cases_ok(rs, nl_, dom):
            """Every reset case's own obligation, as the harness states it: under the case's emitted
            COND and outside every load case, each flop takes that case's value, and the case is
            satisfiable there."""
            for i, r in enumerate(rs):
                ls = case_lits(i, rs)
                if self.ctl.cond(ls) is None:
                    return False
                v = self._const_case(_AND(S, ls), bits, aoff, nl_, dom)
                if v is None or list(v) != list(r["values"]):
                    return False
            return True

        hold = hold_ok(nload, notw(), nres)
        # (1) further reset cases, widest first, while the word still does not hold
        while not hold and len(resets) < self.P["RESET_CASES"]:
            taken = [r["base"][0] for r in resets if len(r["base"]) == 1]
            need = len(resets) + 1 >= self.P["RESET_CASES"]
            got = self._reset_net(m, aoff, nload, notw(), diffh, dom0, taken, need_hold=need)
            if got is None:
                break
            cand, vals = got
            rs2 = resets + [{"base": [cand], "values": vals}]
            nres2 = nres_for(rs2)
            d0 = next(iter(when))
            if self.ctl.cond(case_lits(len(rs2) - 1, rs2)) is None or not dirs_ok(nres2, nload) \
                    or not self._covers(
                        [dom0, nres2, aoff] + ([nload] if nload != 1 else []) + when[d0]["out"],
                        when[d0]["out"] + [nres2] + ([nload] if nload != 1 else []),
                        bits, m["comp"], tmpl[0], tmpl[1], when[d0]["lane"]):
                break
            resets, nres = rs2, nres2
            self.stats["reset_from_enable"] += 1
            hold = hold_ok(nload, notw(), nres)
        # (1b) the cap is reached and the word still restarts: the design's own clear may be the
        # better single case than the synchronous reset the control layer found, so try it in the
        # last case's place. (With RESET_CASES = 1 this is schema v2.0's behaviour exactly: one
        # reset COND, either the design's reset or the restart net.)
        if not hold and resets and len(resets) >= self.P["RESET_CASES"]:
            taken = [r["base"][0] for r in resets[:-1] if len(r["base"]) == 1]
            got = self._reset_net(m, aoff, nload, notw(), diffh, dom0, taken, need_hold=True)
            if got is not None:
                cand, vals = got
                rs2 = resets[:-1] + [{"base": [cand], "values": vals}]
                nres2 = nres_for(rs2)
                d0 = next(iter(when))
                if self.ctl.cond(case_lits(len(rs2) - 1, rs2)) is not None and dirs_ok(nres2, nload) \
                        and self._covers([dom0, nres2, aoff] + ([nload] if nload != 1 else []) + when[d0]["out"],
                                         when[d0]["out"] + [nres2] + ([nload] if nload != 1 else []),
                                         bits, m["comp"], tmpl[0], tmpl[1], when[d0]["lane"]):
                    resets, nres = rs2, nres2
                    self.stats["reset_replaced"] += 1
                    hold = hold_ok(nload, notw(), nres)
        # (2) a when literal turned around as a load case
        if not hold and not loads:
            for r in when.values():
                for l in r["out"]:
                    if l == r.get("en"):
                        continue
                    cand = l ^ 1
                    if self.ctl.cond([cand]) is None or not hold_ok(_AND(S, [cand ^ 1]), notw(), nres):
                        continue
                    if dirs_ok(nres, _AND(S, [cand ^ 1])):
                        loads, hold = [[cand]], True
                        nload = nload_of()
                        break
                if hold:
                    break
        # (3) counterexample-guided load cubes, at most LOAD_CASES in all
        if not hold:
            srcs = sorted({l >> 1 for r in when.values() for l in r["out"]}
                          | {l >> 1 for r in when.values() for l in r["lits"]}
                          | {l >> 1 for c in loads for l in c})
            cap = self.P["LOAD_CASES"] - len(loads)
            keep = self._load_cubes(m, when, nres, aoff, diffh, tmpl, srcs, nload, cap, dom0) \
                if cap > 0 else None
            if keep is not None:
                loads += keep
                nload = nload_of()
                hold = True
        # schema v2 requires (and verifies) control.hold for a counter: without it the template says
        # nothing outside the count case and a load covering its complement leaves the flops
        # unconstrained, so the harness refuses the structure. HOLD_REQUIRED decides whether such a
        # word is dropped or reported with hold false; that decision is taken once, on the FINAL
        # cases, at the end of this method.
        while loads and hold_ok(1, notw(), nres):
            loads, nload = [], 1          # no load case is needed: an empty hold case with one is refused
            self.stats["loads_dropped"] += 1
        if loads and self._unsat(notw() + [nres, aoff, dom0, nload ^ 1]) is True:
            # the load cases cover the complement of the count cases, so nothing would be checked
            # outside them, which is the degenerate template the review found. When the word takes
            # constants there it is a reset case instead, which the harness does check.
            ok2, vals, cand = None, None, None
            if len(loads) == 1:
                cand = _AND(S, loads[0])
                rs2 = resets + [{"base": list(loads[0]), "values": None}]
                vals = self._const_case(cand, bits, aoff, 1, 1, [r["base"][0] ^ 1 for r in resets
                                                                 if len(r["base"]) == 1])
                ok2 = vals is not None and self.ctl.cond(case_lits(len(rs2) - 1, rs2)) is not None
                if ok2:
                    rs2[-1]["values"] = vals
                    ok2 = dirs_ok(nres_for(rs2), 1)
            if not ok2 and any(r2["out"] != r2["lits"] for r2 in when.values()):
                # the re-expressed condition (over the design's own signals) is the complement of
                # the loads, which leaves no hold case; the cube over the cone's leaves does not
                for r2 in when.values():
                    r2["out"] = list(r2["lits"])
                if hold_ok(nload, notw(), nres) \
                        and self._unsat(notw() + [nres, aoff, dom0, nload ^ 1]) is not True:
                    self.stats["netified_reverted"] += 1
                    ok2, vals = None, None
            if ok2 is not None and not ok2:
                self.rejects["the load covers the complement of the count case (no hold case left)"] += 1
                if self.P["HOLD_REQUIRED"]:
                    return None
            elif ok2:
                resets = rs2
                loads, nload = [], 1
                nres = nres_for(resets)
                self.stats["reset_from_load"] += 1
        if not template_ok(len(bits), tmpl[0], tmpl[1], m["step"]):
            self.rejects["the proven template does not match the width (schema v2)"] += 1
            return None
        # The harness checks every reset case under the load cases inactive and inside the domain and
        # refuses one nothing is left of; a load found for the count case can swallow one. A case is
        # dropped only when the word still proves, still holds and every surviving case still proves
        # without it -- dropping it widens every other region (its complement leaves their CONDs), so
        # an unconditional drop would leave obligations that were proven against cases no longer
        # named, which is how a structure comes to be claimed proven and then refuted.
        for r in list(resets):
            i = resets.index(r)
            if self._unsat(case_lits(i, resets) + [aoff, dom0] + ([nload] if nload != 1 else [])) is not True:
                continue
            rest = [x for x in resets if x is not r]
            nres2 = nres_for(rest)
            if dirs_ok(nres2, nload) and (not hold or hold_ok(nload, notw(), nres2)) \
                    and cases_ok(rest, nload, dom0):
                resets, nres = rest, nres2
                self.stats["reset_dropped_vacuous"] += 1
            else:
                self.rejects["the reset case is empty once the load is taken out"] += 1
        # Final re-proof of exactly what is emitted. Every step above proves something against the
        # cases named AT THAT MOMENT, and a later step changes them; this one proves the count
        # templates (with their coverage obligation), every reset case's value obligation and the
        # hold obligation against the final lists, so structure()'s "proven" is a claim this module
        # has just discharged as the harness will state it. hold is recomputed rather than carried,
        # so an unknown or budget-exhausted SAT call becomes hold false (the harness then refuses the
        # structure with a reason) and never a claim.
        for d, res in when.items():
            res["cond"] = self.ctl.cond(res["out"])
            if res["cond"] is None:
                return None
        load_conds = []
        for c in loads:
            cd = self.ctl.cond(c)
            if cd is None:
                return None
            load_conds.append(cd)
        for i, r in enumerate(resets):
            r["cond"] = self.ctl.cond(case_lits(i, resets))
            if r["cond"] is None:
                return None
        nres = nres_for(resets)
        if not dirs_ok(nres, nload, cover=True):
            # The count condition re-expressed over the design's own signals (_netify, _enable_net)
            # can be weaker than the cube the template was actually proven under; the cube is what
            # proves, so fall back to it rather than throw the word away. (Without this fallback the
            # word is dropped and a narrower sub-word of it wins the selection instead -- on the
            # development design that turned a 5-bit position counter into a 4-bit one.)
            if any(r2["out"] != r2["lits"] for r2 in when.values()):
                for r2 in when.values():
                    r2["out"] = list(r2["lits"])
                    r2["cond"] = self.ctl.cond(r2["out"])
                    if r2["cond"] is None:
                        return None
                self.stats["netified_reverted_final"] += 1
            if not dirs_ok(nres, nload, cover=True):
                self.rejects["the count case does not prove against the emitted control cases"] += 1
                return None
        if not cases_ok(resets, nload, dom0):
            self.rejects["a reset case does not prove against the emitted control cases"] += 1
            return None
        hold = hold_ok(nload, notw(), nres)
        if not hold:
            self.rejects["hold not proven (schema v2 requires it for a counter)"] += 1
            if self.P["HOLD_REQUIRED"]:
                return None
        return {"when": when, "resets": resets, "loads": loads, "load_conds": load_conds,
                "nres": nres, "nload": nload, "template": tmpl, "hold": bool(hold)}

    # ------------------------------------------------------------------ word records
    def model_of(self, r):
        """A counter model from a table interpretation (bits LSB first in value order)."""
        w = r["w"]
        bits = [r["word"][j] for j in r["pi"]]
        comp = [(r["p"] >> k) & 1 for k in range(w)]
        sat = r["saturating"] is True
        M = r["modulus"]
        if sat:
            su, sd = r["stops"]["up"], r["stops"]["down"]
            if (sd and sd != [0]) or len(su) > 1:
                sat, M = False, None
            else:
                M = su[0] + 1 if su and su[0] < (1 << w) - 1 else None
        elif M is not None and M == 1 << w:
            M = 1 << w
        elif r["saturating"] is None or M is None:
            M = None
        dirs = {}
        for name, group in (("up", r["ups"]), ("down", r["downs"])):
            if group:
                ls = sorted(group, key=lambda i: (-int(i["reg"].sum()), i["lane"]))
                dirs[name] = [r["lanes"][i["lane"]] for i in ls]
        if w == 1:
            dirs = {"up": dirs.get("up") or dirs.get("down") or []}
        return {"bits": bits, "comp": comp, "step": int(r["step"]), "modulus": M, "saturating": sat, "dirs": dirs}

    def build(self, r, gen):
        """The proven word record of an interpretation that passed the table test, or None."""
        m = self.model_of(r)
        pr = self.prove(m)
        if pr is None:
            self.rejects["count claims not proven"] += 1
            return None
        rec = self._record(m, pr, gen, r)
        if rec is not None:
            rec["alt_steps"] = [int(x) for x in (r.get("alt_steps") or [])]
        return rec

    def _record(self, m, pr, gen, r=None):
        w = len(m["bits"])
        when = pr["when"]
        direction = "updown" if ("up" in when and "down" in when) else next(iter(when))
        if w == 1:
            direction = "up"
        M, sat = pr["template"]
        if sat:
            # the saturation point as an int below 2^w - 1 (the truth's and the verifier's convention)
            top = (M - 1) if M is not None else (1 << w) - 1
            mod_param, sat_param = None, (int(top) if top < (1 << w) - 1 else True)
        elif M is not None:
            mod_param, sat_param = int(M), False
        elif r is not None:
            natural = (r["natural"] or r["modulus"] == 1 << w) and not r["terminal_wraps"]
            mod_param = (1 << w) if natural else None
            sat_param = r["saturating"] if r["saturating"] is not True else None
        else:
            mod_param, sat_param = (None if m.get("reload") else 1 << w), False
        # a reload from a register (many targets) is a load; a state machine's constant presets
        # (a few targets) are not (the truth's convention: constant loads do not count)
        load = bool(r["load"] or (r["reload"] and r["reload_values"] >= self.P["RELOAD_DISTINCT"])) \
            if r is not None else bool(m.get("load"))
        cond_flops = sorted({f for res in when.values() for f in res["flops"]})
        params = {"direction": direction, "step": int(m["step"]), "modulus": mod_param,
                  "saturating": sat_param, "load": load}
        if not params_ok(w, params):
            self.rejects["the emitted modulus or limit does not match the width (schema v2)"] += 1
            return None
        return {"bits": list(m["bits"]), "comp": list(m["comp"]), "gen": gen, "model": m, "proof": pr,
                "params": params,
                "cond_flops": cond_flops, "lanes": {d: [res["lane"]] + [l for l in m["dirs"].get(d, [])
                                                                        if l != res["lane"]]
                                                    for d, res in when.items()}}

    def structure(self, rec, k):
        cells = [self.cell(i) for i in rec["bits"]]
        pr = rec["proof"]
        when = pr["when"]
        main = "up" if "up" in when else "down"
        control = {"when": when[main]["cond"]}
        if rec["params"]["direction"] == "updown":
            control["when_down"] = when["down"]["cond"]
        rs = pr["resets"]
        # schema v2.1: reset is a LIST of cases, each with its own value map; load a LIST of CONDs
        control["reset"] = [{"when": r["cond"], "value": {str(c): int(v) for c, v in zip(cells, r["values"])}}
                            for r in rs] or None
        control["load"] = list(pr["load_conds"]) or None
        control["hold"] = bool(pr["hold"])
        inv = [c for c, b in zip(cells, rec["comp"]) if b]
        if inv:
            control["inverted"] = inv       # flops storing the complement of their bit (the verifier's extension)
        params = dict(rec["params"], bit_order=list(cells))
        modes = sorted(when) + ["load"] * len(pr["loads"]) + (["hold"] if pr["hold"] else []) + \
            ["reset"] * len(rs)
        params = {k: (int(v) if isinstance(v, (int, np.integer)) and not isinstance(v, bool) else v)
                  for k, v in params.items()}
        proof = {"status": "proven", "claims": [], "modes": modes,
                 "obligations": len(when) * 2 + int(pr["hold"]) + 2 * len(rs)}
        if rec.get("alt_steps"):
            # the other steps of a case-selected step (c <= c + (two ? 2 : 1)): the defining case is
            # the split by the case literal, and params.step can only state one step, so the rest are
            # reported here. Not a claim: nothing outside control["when"] is defining.
            proof["alt_steps"] = [int(x) for x in rec["alt_steps"]]
        return {"id": f"counter{k}", "kind": "counter", "flops": list(cells), "order": [list(cells)],
                "params": params, "control": control, "proof": proof}

    # ------------------------------------------------------------------ wider words (carry-chain growth)
    def _readers(self):
        """flop -> the self-looped flops whose next state reads it."""
        rd = getattr(self, "_rd", None)
        if rd is None:
            ctl = self.ctl
            rd = self._rd = collections.defaultdict(set)
            for j in range(ctl.F):
                if j in ctl.supp_flops[j] and not self._quiet(j):
                    for i in ctl.supp_flops[j]:
                        rd[i].add(j)
        return rd

    def _grow_ok(self, bits, comp, d, lane, step, others=()):
        """The (k+1)-bit word counts on the lane at the new bit's carry boundaries (states whose
        lower k bits all carry), and on random states, but for its terminal states: simulated with
        the other candidate bits random (a higher bit of the same counter imitates the next one
        when the lane holds the bits between them at their carry values)."""
        w = len(bits)
        others = [o for o in others if o not in bits]
        rng = np.random.default_rng(104729 * w + 3)
        n = self.P["WIDE_SAMPLES"]
        cap = (1 << w) - 1
        hi = _rand_states(rng, n, w)
        low = (1 << (w - 1)) - 1
        c = sum(int(b) << k for k, b in enumerate(comp))
        vb = ((hi | low) if d == "up" else (hi & ~low)) & cap
        vx = np.concatenate([vb, hi])
        tc = cap if d == "up" else 0
        vx = vx[vx != tc]
        if not len(vx):
            return False
        word = list(bits) + others
        X = (vx ^ c).astype(_sdt(len(word)))
        if others:                  # every sample draws the rivals afresh (the boundary states repeat)
            X = X | (_rand_states(rng, len(X), len(others)).astype(_sdt(len(word))) << w)
        X = np.unique(X)
        vx = (X & cap) ^ c
        cone = self._cone(word)
        qset = {self.ctl.flops[i].q for i in word}
        ext = [s for s in cone.leaves if s not in qset]
        lv = self._lane_bits(ext, [lane])
        F = (self.states_eval(word, lv, X, cone, ext)[0] & cap) ^ c
        T = ((vx + step) if d == "up" else (vx - step)) & cap
        return not bool((F != T).any())

    def extend(self, rec, chain):
        """Grow a proven word with a binary cycle (or a reload) along its carry chain beyond
        EXHAUSTIVE_WIDTH: the chain's next flop, else a flop that reads every bit (fewest other
        sources first), the previous top bit's polarity tried both ways; then prove the whole."""
        P = self.P
        sup = self.ctl.supp_flops
        bits, comp = list(rec["bits"]), list(rec["comp"])
        lanes = {d: ls[0] for d, ls in rec["lanes"].items()}
        step = rec["params"]["step"]
        w0 = len(bits)
        grown = []
        while len(bits) < P["WIDE_CAP"]:
            k = len(bits)
            nxt = [chain[k]] if chain is not None and k < len(chain) and chain[k] not in bits else []
            ups = set.intersection(*(self._readers()[b] for b in bits)) - set(bits) - set(nxt)
            here = set(bits)
            ranked = sorted(ups, key=lambda i: (len(set(sup[i]) - here), self.fk(i)))
            nxt += ranked[:P["UP_TRIES"] + 2]
            rivals = (nxt + ranked)[:P["CHAIN_FANOUT"]]
            ok = None
            for j in nxt:
                for flip in (0, 1):
                    for cj in (0, 1):
                        comp2 = comp[:k - 1] + [comp[k - 1] ^ flip] + [cj]
                        if all(self._grow_ok(bits + [j], comp2, d, ln, step, rivals) for d, ln in lanes.items()):
                            ok = (j, comp2)
                            break
                    if ok:
                        break
                if ok:
                    break
            if ok is None:
                break
            bits.append(ok[0])
            comp = ok[1]
            grown.append((list(bits), list(comp)))
        if not grown:
            return rec
        self.stats["grown_bits"] += len(bits) - w0
        tries = [grown[-1]]
        for r in range(1, P["WIDE_RETRIES"]):
            n = len(grown) - (len(grown) * r) // P["WIDE_RETRIES"]
            if 1 <= n < len(grown) and grown[n - 1] not in tries:
                tries.append(grown[n - 1])
        for b2, c2 in tries:
            for M in (None, "find"):
                m = {"bits": b2, "comp": c2, "step": step, "modulus": None, "saturating": False,
                     "dirs": {d: rec["lanes"][d] for d in rec["lanes"]}, "reload": rec["params"]["modulus"] is None}
                if M == "find":
                    Mv = self._find_modulus(m)
                    if Mv is None:
                        break
                    m["modulus"] = Mv
                pr = self.prove(m)
                if pr is not None and set(pr["when"]) == set(rec["proof"]["when"]):
                    self.stats["extended_words"] += 1
                    m["load"] = rec["params"]["load"]
                    out = self._record(m, pr, rec["gen"] + "+sat")
                    return out
        self.stats["extend_failed"] += 1
        return rec

    def _find_modulus(self, m):
        """A wide up (down) counter's wrap: the lane state from which it steps to 0 (from 0 to): its
        modulus is that state + 1, found by SAT on the proven lane (None if it is not a plain wrap)."""
        S, ctl = self.S, self.ctl
        bits = m["bits"]
        w = len(bits)
        V = self._value_lits(m)
        d = "up" if "up" in m["dirs"] else "down"
        lane = m["dirs"][d][0]
        T, dom = template_lits(S, V, d, m["step"], None, False)
        diff = _OR(S, [_mk(S, _XOR2, ctl.f(b), t ^ c) for b, t, c in zip(bits, T, m["comp"])])
        cone = _Cone(S, [diff])
        qset = {ctl.flops[i].q for i in bits}
        ext = [s for s in cone.leaves if s not in qset]
        lv = self._lane_bits(ext, [lane])[:, 0]
        lits = [2 * s + (1 - int(v)) for s, v in zip(ext, lv)]
        res, cex = self._sat([_AND(S, [diff, self._async_lit(bits)])], 0b01, lits)
        if res is not False:
            return None
        x = sum(int(cex.get(ctl.flops[b].q, 0)) << k for k, b in enumerate(bits))
        c = sum(int(b) << k for k, b in enumerate(m["comp"]))
        vx = x ^ c
        F = int(self.states_eval(bits, lv[:, None], np.array([x], _sdt(w)))[0, 0]) ^ c
        if d == "up" and F == 0 and vx + 1 < (1 << w):
            return vx + 1
        if d == "down" and vx == 0 and 0 < F < (1 << w) - 1:
            return F + 1
        return None

    # ------------------------------------------------------------------ candidates
    def candidates(self):
        """(generator, flops, ordered) triples, deduplicated; ordered ones are chains (LSB first)."""
        ctl, P = self.ctl, self.P
        sn = ctl.self_neg
        cap = P["WORD_CAP"]
        out, seen = [], set()

        def add(gen, fl, ordered):
            fl = tuple(fl[:cap]) if ordered else tuple(fl)     # a chain may run past WORD_CAP (readers)
            if not fl or len(set(fl)) != len(fl) or len(fl) > cap:
                return
            key = (fl if ordered else tuple(sorted(fl, key=self.fk)), ordered)
            if key in seen:
                return
            seen.add(key)
            out.append((gen, key[0], ordered))

        loop = [i in ctl.supp_flops[i] for i in range(ctl.F)]
        chains = []
        for ch in ctl.chains:
            pre = tuple(itertools.takewhile(lambda i: loop[i], ch))
            if len(pre) >= 2:
                chains.append(pre)
                add("chain", pre, True)
        pair = {}
        for bl in getattr(ctl, "blocks", []):
            for b in bl:
                if len(b) == 2:
                    pair[b[0]], pair[b[1]] = b[1], b[0]
        for pre in chains:
            part = tuple(pair[i] for i in itertools.takewhile(lambda i: i in pair and loop[pair[i]], pre))
            if len(part) >= 2 and sn[part[0]]:
                add("partner", part, True)
        sup = [set(s) for s in ctl.supp_flops]
        W = P["EXHAUSTIVE_WIDTH"]

        def closure(B):
            """B plus the self-looped flops it reads that read B and nothing else but themselves (a bit
            that the chain order skipped inside a mod-M word)."""
            S = set(B)
            grow = True
            while grow and len(S) <= W:
                grow = False
                for i in sorted({j for x in S for j in sup[x]} - S, key=self.fk):
                    if loop[i] and not self._quiet(i) and sup[i] <= S | {i} and sup[i] & S:
                        S.add(i)
                        grow = True
            return sorted(S, key=self.fk)

        def closures(gen, B, down=True):
            S = closure(B)
            if len(S) > len(B) and len(S) <= W:
                add(gen + "+", S, False)
            T = S if len(S) <= W else list(B)
            while down and len(T) < W:   # low bits outside a mod-M SCC, one tightest container at a time
                T = self._tight(T)
                if T is None:
                    break
                add(gen + "+lsb", T, False)

        for pre in list(chains):
            closures("chain", list(pre[:W]), down=False)     # a chain starts at a bit that toggles
        for bl in getattr(ctl, "blocks", []):
            for b in bl:
                B = [i for i in b if loop[i]]
                if not any(sn[i] for i in B) or len(B) > W:
                    continue
                add("block", B, False)
                closures("block", B)
        for seq in self._nesting():
            add("nest", seq, True)
            closures("nest", seq)
        for seq in self._carry_chains():
            add("carry", seq, True)
        return out

    def _carry_chains(self):
        """Carry chains found by simulation, LSB first: from each flop that toggles on one of its
        counting lanes whatever the state of its readers, the next bit is the toggling flop reading
        every bit so far that toggles in every sampled state where the bits so far sit at their
        carry values (the rest random) and in none where the last of them does not; the carry value
        of each bit (1 counting up, 0 counting down; per bit, as a flop may store its complement)
        is the one under which the next bit toggles. Independent of support nesting and of the
        pool's activity statistics (a reload or a terminal-count clear makes every bit read every
        other; a counter's pool activity depends on the lanes' biases)."""
        ctl, P = self.ctl, self.P
        sn = ctl.self_neg
        rd = self._readers()
        out = []
        n = P["CHAIN_SAMPLES"]
        for b0 in sorted(range(ctl.F), key=self.fk):
            if not sn[b0] or b0 not in ctl.supp_flops[b0] or self._quiet(b0):
                continue
            if not any(sn[j] for j in rd[b0] if j != b0):
                continue
            A = _lanes_of(self._counting(b0) & self._async_off([b0]))
            for lane in _spread(A, P["CHAIN_LANES"]):
                seq = self._carry_chain(b0, lane, n)
                if seq is not None and len(seq) >= 2:
                    out.append(seq)
                    break
        out = self._join_chains(out)
        self.stats["carry_chains"] = len(out)
        return out

    def _join_chains(self, chains):
        """Each carry chain continued along the chain found from one of its own higher bits where that
        chain agrees with it bit for bit and runs further: the carry passes on the same way, and where
        a chain stops is sampling noise (near a reload or a wrap the next bit's agreement drops below
        CHAIN_AGREE after a random number of steps), so chains from neighbouring LSBs of one counter
        otherwise end at different heights and a higher start can outreach the true LSB."""
        cap = self.P["WIDE_CAP"]
        start = {}
        for s in chains:
            start.setdefault(s[0], s)
        out = []
        for s in chains:
            cur, used = list(s), {s[0]}
            grown = True
            while grown and len(cur) < cap:
                grown = False
                for k in range(1, len(cur)):
                    t = start.get(cur[k])
                    if t is None or t[0] in used:
                        continue
                    tail = cur[k:]
                    if len(t) > len(tail) and list(t[:len(tail)]) == tail and not set(t[len(tail):]) & set(cur):
                        cur = cur[:k] + list(t)
                        used.add(t[0])
                        grown = True
                        self.stats["carry_chains_joined"] += 1
                        break
            out.append(cur[:cap])
        return out

    def _carry_chain(self, b0, lane, n):
        ctl = self.ctl
        sn = ctl.self_neg
        rd = self._readers()
        rng = np.random.default_rng(7 * n + 1)
        bits, cv = [b0], []
        cap = self.P["WIDE_CAP"]
        while len(bits) < cap:
            cands = [j for j in set.intersection(*(rd[b] for b in bits)) - set(bits) if sn[j]]
            k = len(bits)
            cands = sorted(cands, key=self.fk)[:self.P["CHAIN_FANOUT"]]
            word = bits + cands
            cone = self._cone(word)
            qset = {ctl.flops[i].q for i in word}
            ext = [s for s in cone.leaves if s not in qset]
            E = self._lane_bits(ext, [lane])
            if k == 1:
                # the LSB toggles whatever the state of the flops that read it (a higher bit of a
                # counter may pass on a lane that holds the bits below it at their carry values: it
                # starts a shorter chain, which the full one covers)
                X = _rand_states(rng, n, len(word))
                F = self.states_eval(word, E, X, cone, ext)[0]
                if float(((F ^ X) & 1).astype(np.int64).mean()) < self.P["CHAIN_LSB"]:
                    return None
            found = None
            for v in (1, 0):
                cvv = cv + [v]
                base = sum(b << j for j, b in enumerate(cvv))
                mask = (1 << k) - 1
                X = (_rand_states(rng, n, len(word)) & ~mask) | base
                Xo = X ^ (1 << (k - 1))          # the last bit away from its carry value
                F = self.states_eval(word, E, np.concatenate([X, Xo]), cone, ext)[0]
                T = F ^ np.concatenate([X, Xo])
                on, off = T[:n], T[n:]
                # the next bit toggles in (nearly) every state with the bits below at their carry
                # values and in (nearly) none otherwise; a reload or a clear at the word's terminal
                # state, which random upper bits sometimes reach, spoils a few samples
                ok = []
                for m, c in enumerate(cands):
                    r_on = float(((on >> (k + m)) & 1).mean())
                    r_off = float(((off >> (k + m)) & 1).mean())
                    if r_on >= self.P["CHAIN_AGREE"] and r_off <= 1 - self.P["CHAIN_AGREE"]:
                        ok.append((r_off - r_on, self.fk(c), c))
                if ok:
                    found = (min(ok)[2], v)
                    break
            if found is None:
                break
            bits.append(found[0])
            cv.append(found[1])
        return bits if len(bits) >= 2 else None

    def _tight(self, B, n=1):
        """B plus the toggling flop it reads whose counting changes hold most of B's (in steps of 5 %;
        then the fewest counting changes, the tightest container): the bit below B's LSB changes
        whenever B counts. Sorted by structural key, or None; with n > 1 the n best such flops."""
        ctl, P = self.ctl, self.P
        sn = ctl.self_neg
        sup = ctl.supp_flops
        full = self._full(B)
        TB = np.zeros(ctl.W, np.uint64)
        for i in B:
            TB |= self._counting(i, full)
        nb = _pc(TB)
        if not nb:
            return [] if n > 1 else None
        ranked = []
        for j in {j for x in B for j in sup[x]} - set(B):
            if not sn[j] or self._quiet(j):
                continue
            Aj = self._counting(j, full)
            na = _pc(Aj)
            if not na:
                continue
            inside = _pc(Aj & TB)
            if inside >= P["NEST_MIN"] * nb:
                ranked.append((-int(P["NEST_BINS"] * inside / nb), na, self.fk(j), j, inside * inside / (nb * na)))
        ranked.sort()
        if n > 1:        # also by recall x precision (a flop that changes every cycle holds all of B's lanes)
            alt = sorted(ranked, key=lambda k: (-k[4], k[2]))
            return list(dict.fromkeys([k[3] for k in ranked[:n]] + [k[3] for k in alt[:n]]))
        return None if not ranked else sorted(set(B) | {ranked[0][3]}, key=self.fk)

    def _nesting(self):
        """Toggle-nesting growth sequences (LSB first) from every toggling flop, over counting
        changes (changes made by a clear or set literal do not nest)."""
        ctl, P = self.ctl, self.P
        sn = ctl.self_neg
        sup = [set(s) for s in ctl.supp_flops]
        tog = [i for i in range(ctl.F) if i in sup[i] and not self._quiet(i)]
        togset = set(tog)
        rdr = collections.defaultdict(set)
        for i in tog:
            for j in sup[i]:
                rdr[j].add(i)
        cnt = {i: _pc(self._counting(i)) for i in tog}
        seqs = []
        for b0, mutual_first in ((b, m) for b in sorted(tog, key=self.fk) for m in (False, True)):
            if not sn[b0] or cnt[b0] < P["N_MIN"]:
                continue
            stack = [[b0]]
            done = 0
            while stack and done < P["NEST_TRIES"]:
                seq = stack.pop()
                while len(seq) < P["EXHAUSTIVE_WIDTH"]:
                    top = seq[-1]
                    At = self._counting(top)
                    nb = ((sup[top] | rdr[top]) & togset) - set(seq)
                    sc = []
                    for j in nb:
                        if cnt[j] == 0 or cnt[j] > P["NEST_RATE"] * cnt[top] + P["NEST_SLACK"]:
                            continue
                        both = _pc(self._counting(j) & At)
                        if both >= P["NEST_MIN"] * cnt[j]:
                            mutual = mutual_first and not (j in sup[top] and top in sup[j])
                            # the next bit changes only when this one does (nested in 5 % steps),
                            # then the most such changes
                            sc.append((not sn[j], mutual, -int(P["NEST_BINS"] * both / cnt[j]), -both, self.fk(j), j))
                    if not sc:
                        break
                    sc.sort()
                    if len(sc) > 1 and len(stack) + done + 1 < P["NEST_TRIES"]:
                        stack.append(seq + [sc[1][-1]])
                    seq = seq + [sc[0][-1]]
                if len(seq) >= 2:
                    seqs.append(seq)
                done += 1
        # every nested mutual pair too: the runner-up limit can hide a 2-bit counter's upper bit
        # behind wider registers whose changes also nest in the LSB's (a queue slot shifting when
        # its fill level counts down)
        for b0 in sorted(tog, key=self.fk):
            if not sn[b0] or cnt[b0] < P["N_MIN"]:
                continue
            A0 = self._counting(b0)
            for j in sorted(((sup[b0] & rdr[b0]) & togset) - {b0}, key=self.fk):
                if 0 < cnt[j] <= P["NEST_RATE"] * cnt[b0] + P["NEST_SLACK"] \
                        and _pc(self._counting(j) & A0) >= P["NEST_MIN"] * cnt[j]:
                    seqs.append([b0, j])
        return seqs

    # ------------------------------------------------------------------ candidate tests
    def screen(self, word, gen, hint=None, chain=None, modes=True):
        """The table test and the cheap rejections (no SAT): a screening record {word, hint, gen,
        bits (LSB first), params, chain} or None; cached by (word, hint, modes)."""
        key = ("screen", tuple(word), None if hint is None else tuple(hint),
               len(word) == 1 and gen == "toggle", modes)
        if key in self._tables:
            return self._with_reach(self._tables[key], gen, chain)
        r = self.analyze_word(word, hint=hint, modes=modes) if (len(word) > 1 or gen == "toggle") else None
        sr = None
        if r is not None:
            w = r["w"]
            if w == 2 and r["modulus"] is None and r["saturating"] is not True:
                self.rejects["two-bit word with lane-dependent wraps or stops"] += 1
            elif w == 2 and r["load"]:
                self.rejects["two-bit word with data loads (an affine fragment)"] += 1
            elif w >= 2 and r["modulus"] is not None and r["modulus"] <= 1 << (w - 1):
                self.rejects["the count cycle fits in fewer bits (a bit that is not the counter's)"] += 1
            elif (w >= 2 and r["modulus"] is None and r["saturating"] is not True and r["load"]
                  and not r["terminal_wraps"] and not r["natural"]):
                self.rejects["lane-dependent wraps or stops with data loads (a data path)"] += 1
            elif w <= 2 and r["const_lanes"] and not r["hold_lanes"]:
                self.rejects["a tiny word that sets or clears itself but never holds (flags)"] += 1
            elif not r["alt_steps"] and self._data_step(r):
                self.rejects["step set by data (an accumulator)"] += 1
            else:
                sr = {"word": list(word), "hint": None if hint is None else tuple(hint),
                      "bits": [word[j] for j in r["pi"]],
                      "params": {"direction": r["direction"], "step": int(r["step"]), "modulus": r["modulus"],
                                 "saturating": r["saturating"], "load": bool(r["load"])},
                      "wide_ok": (r["natural"] or r["modulus"] == 1 << w or r["terminal_wraps"]) and r["step"] == 1,
                      "split": bool(r["alt_steps"])}
        self._tables[key] = sr
        return self._with_reach(sr, gen, chain)

    def _with_reach(self, sr, gen, chain):
        if sr is None:
            return None
        out = dict(sr, gen=gen, chain=chain)
        W = self.P["EXHAUSTIVE_WIDTH"]
        if chain is not None and len(chain) > W and len(sr["bits"]) == W and sr["wide_ok"] \
                and sorted(sr["bits"]) == sorted(chain[:W]):
            out["reach"] = len(chain)      # carry-chain growth may widen it (realize)
        return out

    def realize(self, sr):
        """The proven word record of a screening record (the table test rerun, the proof and, for a
        word of EXHAUSTIVE_WIDTH bits with a binary cycle or a reload, carry-chain growth), or None."""
        key = ("real", tuple(sr["word"]), sr["hint"], None if sr.get("chain") is None else tuple(sr["chain"]))
        if key in self._tables:
            return self._tables[key]
        r = self.analyze_word(sr["word"], hint=sr["hint"])
        rec = self.build(r, sr["gen"]) if r is not None else None
        W = self.P["EXHAUSTIVE_WIDTH"]
        if rec is not None and len(rec["bits"]) == W and sr.get("wide_ok") and rec["params"]["step"] == 1:
            rec = self.extend(rec, sr.get("chain"))
        self._tables[key] = rec
        return rec

    def _prefixes(self, gen, fl, chain=None):
        """Prefix tests of an ordered candidate (a chain or a nesting sequence: LSB first, readers or
        the next cascaded word on top): prefixes pass the table test from two bits up until the
        first that fails; the longest passing prefix, and the longest regular one when that is
        irregular (see _select)."""
        W = self.P["EXHAUSTIVE_WIDTH"]
        head = list(fl[:W])
        passing = []
        for k in range(2, len(head) + 1):
            key = ("pass", tuple(head[:k]))
            ok = self._tables.get(key)
            if ok is None:
                ok = self._tables[key] = self.analyze_word(head[:k], hint=tuple(range(k))) is not None
            if not ok:
                break
            passing.append(k)
        if not passing:
            self.stats["prefix_pair_rejected"] += 1
        out = []
        for k in reversed(passing):
            sr = self.screen(head[:k], gen, hint=tuple(range(k)), chain=chain if k == len(head) else None)
            if sr is None:
                continue
            out.append(sr)
            if self._regular(sr):
                break
        return out

    def test(self, gen, fl, ordered):
        """Screening records for one candidate (an empty list when none passes)."""
        W = self.P["EXHAUSTIVE_WIDTH"]
        if ordered:
            return self._prefixes(gen, fl, chain=list(fl) if len(fl) > W else None)
        if len(fl) > W:
            return []
        sr = self.screen(list(fl), gen)
        return [sr] if sr is not None else []

    # ------------------------------------------------------------------ driver
    def run(self):
        t0 = time.perf_counter()
        cands = self.candidates()
        self.timings["candidates"] = time.perf_counter() - t0
        self.stats.update({f"candidates_{g}": n for g, n in collections.Counter(c[0] for c in cands).items()})
        t0 = time.perf_counter()
        srs = []
        # ordered candidates longer than EXHAUSTIVE_WIDTH first, longest first: the flops of the wide
        # words they prove are not screened again as parts of other candidates (a wide counter's
        # sub-chains and prefixes from every bit would each be screened, and each loses to it)
        covered = set()
        W = self.P["EXHAUSTIVE_WIDTH"]
        long = [k for k, (gen, fl, ordered) in enumerate(cands) if ordered and len(fl) > W]
        for k in sorted(long, key=lambda k: -len(cands[k][1])):
            gen, fl, ordered = cands[k]
            if covered and set(fl) <= covered:
                continue
            got = self.test(gen, fl, ordered)
            srs += got
            for sr in got:
                if sr.get("reach"):
                    rec = self.realize(sr)
                    # a covering word is complete in itself: its condition pins no toggling flop
                    # (else it may be a fragment of a cascade) and it is not two counters (_cut)
                    if rec is not None and len(rec["bits"]) > W and not any(
                            self.ctl.self_neg[j] and j in self.ctl.supp_flops[j] for j in rec["cond_flops"]) \
                            and not self._is_cut(rec):
                        covered |= set(rec["bits"])
        done = set(long)
        for k, (gen, fl, ordered) in enumerate(cands):
            if k in done:
                continue
            if covered and set(fl) <= covered:
                self.stats["candidates_covered"] += 1
                continue
            srs += self.test(gen, fl, ordered)
        srs += self._grow_up(srs)
        self.timings["screen"] = time.perf_counter() - t0
        t0 = time.perf_counter()
        chosen = self._choose(srs)
        for _round in range(self.P["REFINE_ROUNDS"]):
            more = self._widen(chosen)
            if not more:
                break
            srs += more
            chosen = self._choose(srs)
        self.timings["claims"] = time.perf_counter() - t0
        t0 = time.perf_counter()
        taken = {i for rec in chosen for i in rec["bits"]}
        chosen += self._toggles(taken)
        self.timings["toggles"] = time.perf_counter() - t0
        chosen.sort(key=lambda rec: (-len(rec["bits"]), [self.fk(i) for i in rec["bits"]]))
        structs = [self.structure(rec, k) for k, rec in enumerate(chosen)]
        t0 = time.perf_counter()
        rels = self._cascades(chosen, structs)
        self.timings["relations"] = time.perf_counter() - t0
        self.stats["words_screened"] = len(srs)
        self.stats["structures"] = len(structs)
        return chosen, structs, rels

    def _widen(self, chosen):
        """Chosen words tried one bit wider, below (the tightest container of the word: its missing
        LSB) and above (UP_TRIES flops that read every bit, fewest other sources first): the
        screening records of wider words that pass (the candidate generators can start a word one
        bit too high or stop one too low, as a permutation changes the control layer's lanes)."""
        W = self.P["EXHAUSTIVE_WIDTH"]
        sup = self.ctl.supp_flops
        out = []
        for rec in chosen:
            bits = list(rec["bits"])
            if len(bits) >= W:
                continue
            tries = [[j] + bits for j in (self._tight(bits, n=self.P["UP_TRIES"] + 1) or [])]
            ups = set.intersection(*(self._readers()[b] for b in bits)) - set(bits)
            here = set(bits)
            ranked = sorted(ups, key=lambda i: (len(set(sup[i]) - here), self.fk(i)))
            if ranked:                  # every reader tied with the best, and UP_TRIES in all at least
                best = len(set(sup[ranked[0]]) - here)
                n = max(self.P["UP_TRIES"], sum(1 for i in ranked if len(set(sup[i]) - here) == best))
                tries += [bits + [j] for j in ranked[:n]]
            while tries:
                word = tries.pop(0)
                key = ("widen", tuple(word))
                if key in self._tables or len(word) > W:
                    continue
                self._tables[key] = True
                sr = self.screen(word, rec["gen"] + "+wide", hint=tuple(range(len(word))))
                if sr is not None:
                    out.append(sr)
                if len(word) == len(bits) + 1 and word[-1] != bits[-1] and word[0] == bits[0]:
                    # one more reader on top: a regular low word and an irregular one-bit extension
                    # yield to each other (see _select); the two-bit extension does not
                    here2 = set(word)
                    ups2 = set.intersection(*(self._readers()[b] for b in word)) - here2
                    tries += [word + [j] for j in sorted(ups2, key=lambda i: (len(set(sup[i]) - here2),
                                                                              self.fk(i)))[:self.P["UP_TRIES"]]]
        self.stats["widened"] += len(out)
        return out

    def _choose(self, srs):
        """Select disjoint screened words (_select), prove the chosen (realize), drop words whose
        claims do not prove or whose count condition makes them a fragment (_fragment), and redo the
        selection; words grown past their screened width win overlaps with the words they reach into."""
        failed = set()
        while True:
            self._frag_memo = {}         # verdicts depend on the chosen words
            live = [sr for sr in srs if (tuple(sr["word"]), sr["hint"]) not in failed]
            picked = self._select(live)
            recs, redo = [], False
            for sr in picked:
                rec = self.realize(sr)
                if rec is None:
                    failed.add((tuple(sr["word"]), sr["hint"]))
                    self.stats["claims_failed"] += 1
                    redo = True
                    break
                recs.append((sr, rec))
            if redo:
                continue
            chosen = self._disjoint([rec for _sr, rec in recs])
            for sr, rec in recs:
                if any(rec is c for c in chosen):
                    why = self._fragment(rec, chosen, srs) or self._truncated(rec, chosen, srs)
                    if why:
                        self.rejects[why] += 1
                        failed.add((tuple(sr["word"]), sr["hint"]))
                        redo = True
            if not redo:
                return self._cut(chosen)

    def _disjoint(self, recs):
        recs = sorted(recs, key=lambda r: (-len(r["bits"]), [self.fk(i) for i in r["bits"]]))
        taken, out = set(), []
        for r in recs:
            if taken & set(r["bits"]):
                self.stats["overlap_after_growth"] += 1
                continue
            taken |= set(r["bits"])
            out.append(r)
        return out

    def _pinned(self, rec, d=None):
        """{flop: value} of the flop states that a word's count condition(s) fix."""
        out = {}
        for dd, res in rec["proof"]["when"].items():
            if d is not None and dd != d:
                continue
            for l in res["lits"]:
                j = self.q2flop.get(l >> 1)
                if j is not None:
                    out[j] = 1 - (l & 1)
        return out

    def _sum_bit(self, x, lits, v=None):
        """Flop x is a sum bit under the literals (its own literal dropped): its next state is its
        state xor a function of the rest (an adder's or counter's bit, not a held register or an
        FSM bit), and that function can be 1 (it can change). With v (the value the literals pin x
        to): an update enabled by a condition that reads x itself (a compare of the sum against
        another word) counts too: where the next state is not x xor g, x at the other value holds."""
        memo = self.__dict__.setdefault("_sum_memo", {})
        key = (x, tuple(sorted(set(lits))), v)
        if key not in memo:
            memo[key] = self._sum_bit1(x, lits, v)
        return memo[key]

    def _sum_bit1(self, x, lits, v=None):
        S, ctl = self.S, self.ctl
        q = ctl.flops[x].q
        lits = [l for l in lits if l >> 1 != q]
        f = ctl.f(x)
        f0, f1 = S.cofactor(f, q, 0), S.cofactor(f, q, 1)
        bad = [_mk(S, _XOR2, f0, f1) ^ 1]
        if v is not None:
            bad.append(f0 if v else f1 ^ 1)     # and x at not-v changes: no hold there
        if self._unsat(lits + bad) is not True:
            return False
        return self._unsat(lits + [f0]) is False

    def _word_of(self, x, rec, chosen, srs, lits=None, trunc_depth=None):
        """A proven counter (other than rec) that holds flop x: a chosen word, else a screened
        candidate that proves (widest first), else x as a 1-bit toggle; or None. With `lits` (the
        word's count condition and context) "toggling" neighbours are sum bits under them, else any
        structurally self-inverting self-looped flop."""
        def whole(r):              # a witness is a word of its own: no fragment, no cut, not truncated
            if self._fragment(r, chosen, srs, 1) or self._is_cut(r):
                return False
            return trunc_depth is None or trunc_depth > self.P["TRUNC_DEPTH"] or \
                not self._truncated(r, chosen, srs, trunc_depth)

        for c in chosen:
            if c is not rec and x in c["bits"] and whole(c):
                return c
        for sr in sorted((sr for sr in srs if x in sr["word"]), key=lambda sr: -len(sr["word"])):
            r = self.realize(sr)
            if r is not None and r is not rec and x in r["bits"] and r["bits"] != rec["bits"] and whole(r):
                return r
        # a lone toggle: none of the flops it reads (outside the word) toggles itself (an adder's
        # bit reads the toggling bits below it), and no toggling flop that reads it feeds the word
        # (an adder's low bit carries into the word through the bits above it)
        ctl = self.ctl
        W = set(rec["bits"])

        def tog(j):
            if not (ctl.self_neg[j] and j in ctl.supp_flops[j]):
                return False
            return lits is None or self._sum_bit(j, lits)

        def counted(y):          # y is a bit of some candidate word that proves (a counter enabled by x)
            return any(y in sr["word"] and (r := self.realize(sr)) is not None and y in r["bits"]
                       for sr in srs)

        # (a toggle that reads the word, above it, is driven by the word's bits: no lone toggle)
        if any(j != x and ((j in W and trunc_depth is not None) or (j not in W and tog(j) and not counted(j)))
               for j in ctl.supp_flops[x]):
            return None
        wsup = set().union(*(ctl.supp_flops[b] for b in W))
        if any(y != x and y not in W and y in wsup and tog(y) and not counted(y) for y in self._readers()[x]):
            return None
        sr = self.screen([x], "toggle")
        return self.realize(sr) if sr is not None else None

    def _truncated(self, rec, chosen, srs, depth=0):
        """Why a proven word is the low part of wider arithmetic, or None: a flop outside it that
        reads some of its bits is an adder's bit on a counting lane (its next state is its state xor a
        function of the word) and depends on the word's value at more than one state (an adder, a
        multiplier or a broken carry above it; a counter's next bit, a cascaded counter and a
        terminal-count reader depend on one state), and that flop belongs to no separate counter."""
        ctl = self.ctl
        W = rec["bits"]
        if len(W) < 2 or len(W) > self.P["EXHAUSTIVE_WIDTH"]:
            return None
        Ws = set(W)
        readers = set().union(*(self._readers()[b] for b in W)) - Ws
        memo = self.__dict__.setdefault("_arith_memo", {})
        for y in sorted(readers, key=self.fk):
            if not ctl.self_neg[y]:
                continue
            key = (y, tuple(W), tuple(r["lane"] for r in rec["proof"]["when"].values()))
            if key not in memo:
                memo[key] = self._arith_reader(y, rec)
            if not memo[key]:
                continue
            L = self._word_of(y, rec, chosen, srs, trunc_depth=depth + 1)
            if L is None or set(L["bits"]) & Ws:
                return "read by adder logic outside every counter (a truncated arithmetic word)"
        return None

    def _arith_reader(self, y, rec):
        """On a counting lane of the word, flop y's next state is y xor g(word) with g a function
        of the word's value that is 1 at more than one state and not everywhere."""
        ctl = self.ctl
        W = rec["bits"]
        w = len(W)
        states = np.arange(1 << w, dtype=np.int64)
        word = list(W) + [y]
        cones = self.__dict__.setdefault("_ycones", {})
        cone = cones.get(y)
        if cone is None:
            cone = cones[y] = _Cone(self.g, [ctl.f(y)])
        qset = {ctl.flops[i].q for i in word}
        ext = [s for s in cone.leaves if s not in qset]
        val = np.zeros(len(states), np.int64)
        for k, (b, cp) in enumerate(zip(W, rec["comp"])):
            val |= (((states >> k) & 1) ^ cp) << k
        M, _sat = rec["proof"]["template"]
        lim = (1 << w) if M is None else int(M)
        step = int(rec["params"]["step"])
        for d, res in rec["proof"]["when"].items():
            E = self._lane_bits(ext, [res["lane"]])
            f0 = self.lit_eval(cone, word, ext, E, states)[0]
            f1 = self.lit_eval(cone, word, ext, E, states | (1 << w))[0]
            if not (f0 != f1).all():          # not y xor g: y holds or is set somewhere (an FSM bit, a register)
                continue
            n = int(f0.sum())                  # g = f0: the states where y toggles
            if n == 1:
                # one toggle state: a counter's next bit, a cascade and a terminal-count reader
                # toggle where the word wraps, stops or leaves its count (a clear, a reload); an
                # adder's bit above the word's own carry toggles at a plain count step
                p = int(np.flatnonzero(f0)[0])
                if val[p] >= lim:
                    continue
                cw = self._cone(W)
                qw = {ctl.flops[i].q for i in W}
                extw = [s for s in cw.leaves if s not in qw]
                nxt = self.states_eval(W, self._lane_bits(extw, [res["lane"]]), states[p:p + 1], cw, extw)[0][0]
                nv = 0
                for k, cp in enumerate(rec["comp"]):
                    nv |= ((int(nxt) >> k) & 1 ^ cp) << k
                if nv != int(val[p]) + (step if d == "up" else -step):
                    continue
                return True
            if min(n, len(states) - n) < 2:    # a point (a compare with one value) either way
                continue
            # in the word's count order: a threshold (a full / empty flag, a limit compare) is a
            # comparator reading the word; an adder's bit toggles on scattered values
            g = f0[np.argsort(val)].astype(np.int8)
            if (np.diff(g) >= 0).all() or (np.diff(g) <= 0).all():
                continue
            return True
        return False

    def _fragment(self, rec, chosen, srs, depth=0):
        """Why a proven word is a fragment, or None. Its count condition fixes a sum bit x (a flop
        that toggles as an adder's bit under that condition) that belongs to another proven word
        sharing flops with this one that is not a fragment itself (a counter split at a pinned bit),
        or that belongs to no counter and does not read the word (the low bits of an accumulator
        whose carry-out the word counts). A sum bit of a separate counter is an enable (a compare)
        or a cascade (held at its terminal count); a sum bit that reads the word is a sequencer
        stepping on the word's terminal count. Memoized; a word under test counts as whole."""
        memo = self.__dict__.setdefault("_frag_memo", {})
        busy = self.__dict__.setdefault("_frag_busy", set())
        key = tuple(rec["bits"])
        if key in memo:
            return memo[key]
        if key in busy:                  # a cycle: the word under test counts as whole
            self._frag_cycle = True
            return None
        busy.add(key)
        outer = getattr(self, "_frag_cycle", False)
        self._frag_cycle = False
        try:
            why = self._fragment_why(rec, chosen, srs, depth)
        finally:
            busy.discard(key)
        if not self._frag_cycle:         # a verdict that leaned on a word under test is not kept
            memo[key] = why
        self._frag_cycle = self._frag_cycle or outer
        return why

    def _prescaling(self, rec, srs):
        """The word's LSB x only prescales another proven word W at least as wide: W's count
        condition pins x and W's low bits are the word's other bits (a phase flag that enables a
        counter makes a counter with it; W, the counter itself, is preferred). A counter's own LSB
        is pinned only by its upper bits, a narrower word. A prescaled word one bit wider than the
        counter (the flag under all of its bits) is functionally a counter too and is kept."""
        x, rest = rec["bits"][0], rec["bits"][1:]
        if not rest:
            return None
        need = len(rec["bits"])
        for sr in sorted((sr for sr in srs if x not in sr["word"] and set(rest) <= set(sr["word"])),
                         key=lambda sr: -len(sr["word"])):
            W = self.realize(sr)
            if W is None or len(W["bits"]) < need or W["bits"][:len(rest)] != rest:
                continue
            if x in W["cond_flops"]:
                return "its lowest bit only prescales a counter as wide that pins it (a phase flag)"
        return None

    def _fragment_why(self, rec, chosen, srs, depth):
        why = self._prescaling(rec, srs)
        if why:
            return why
        ctl = self.ctl
        bits = set(rec["bits"])
        pr = rec["proof"]
        ctx = [self._async_lit(rec["bits"])] + ([pr["nres"]] if pr["nres"] != 1 else []) + \
            ([pr["nload"]] if pr["nload"] != 1 else [])
        for d, res in pr["when"].items():
            pinned = self._pinned(rec, d)
            loose = []
            for x in sorted(pinned, key=self.fk):
                if x in bits or not ctl.self_neg[x] or x not in ctl.supp_flops[x]:
                    continue
                if not self._can_change(x, pinned[x], res["lits"] + ctx):
                    continue
                if depth < self.P["FRAGMENT_DEPTH"]:
                    # a word the case-selected step admitted is not an answer to "does x belong
                    # to a counter of its own": an accumulator's upper part counts under one value
                    # of its addend, and that reading would excuse the fragment it is
                    for sr in sorted((sr for sr in srs if x in sr["word"] and bits & set(sr["word"])
                                      and not sr.get("split")),
                                     key=lambda sr: -len(sr["word"])):
                        L = self.realize(sr)
                        if L is None or L is rec or L["bits"] == rec["bits"] or x not in L["bits"] \
                                or not (bits & set(L["bits"])):
                            continue
                        if L["bits"][0] == x and L["bits"][1:] == rec["bits"][:len(L["bits"]) - 1]:
                            continue          # x only prescales this word (see _prescaling)
                        if not self._fragment(L, chosen, srs, depth + 1) and not self._is_cut(L):
                            why = "count condition pins a bit of an overlapping counter (a fragment)"
                            break
                if why:
                    break
                # an accumulator's upper part: x does not read the word (a sequencer's bit, a queue
                # slot indexed by it, a compare-enabled bit do) and is a sum bit below it (x = x xor g
                # under the condition; x under the word no counter: an enabling toggle makes a counter
                # with it), or, updated under the word's dominant control class, makes an adder under
                # it; unless x belongs to a counter of its own (an enable, a cascade)
                lits = res["lits"] + ctx
                if not self._nested_below(x, rec):
                    continue
                same_enable = ctl.profile[x].dominant == ctl.profile[rec["bits"][0]].dominant
                strict = self._sum_bit(x, lits)
                # (a sum bit that reads the word only where the word stops is gated with it by one
                # enable, like the word's own low bits: it stays a candidate)
                if self._reads(x, rec["bits"], lits) and not (strict and not self._reads_counting(x, rec, res)):
                    continue
                if ((strict and not self._prescaled(x, rec)) or (same_enable and self._adder_below([x], rec))) \
                        and self._word_of(x, rec, chosen, srs, lits) is None:
                    why = "count condition pins the low bit of an adder under the word (an accumulator's upper part)"
                    break
                if not strict and same_enable and self._sum_bit(x, lits, pinned[x]) \
                        and self._word_of(x, rec, chosen, srs, lits) is None:
                    loose.append(x)         # a sum bit whose update is enabled by a compare that reads it
            if not why and loose and self._adder_below(loose, rec):
                # the pinned carry bits below, under the word, make an adder (bits of a wide adder
                # whose enable compares the sum; a set/clear flag under a counter makes a counter)
                why = "count condition pins the carry bits of an adder under the word (an accumulator's upper part)"
            if not why:
                # the count condition pins some of the toggling bits below the word that feed its LSB
                # (the addend and one low bit can make the carry certain without pinning the bits in
                # between); with all of them under it the word is an adder (an accumulator's upper part);
                # a cascaded counter's bits under it make a wider counter
                B = self._carry_in(rec, res["lits"] + ctx)
                if B and set(B) & set(pinned) and self._adder_below(B, rec):
                    why = "count condition pins the carry-in bits of an adder under the word (an accumulator's upper part)"
            if why:
                break
        return why

    def _reads_counting(self, x, rec, res):
        """On the word's proof lane (x at its lane value), flop x's next state depends on the word's
        state at some state where the word counts: x reads the word where it counts (a sequencer, a
        queue slot indexed by it, a flag set at its terminal count), not only at the states where it
        stops, through the one enable that stops the word and x together (a deadline adder whose
        update compares its own sum: its upper bits read as a saturating counter over its low bits).
        True when the lane cannot tell (a word counting or stopping at every state)."""
        ctl = self.ctl
        W = rec["bits"]
        w = len(W)
        if w > self.P["EXHAUSTIVE_WIDTH"]:
            return True
        memo = self.__dict__.setdefault("_rc_memo", {})
        key = (x, tuple(W), res["lane"])
        if key in memo:
            return memo[key]
        states = np.arange(1 << w, dtype=np.int64)
        cw = self._cone(W)
        qw = {ctl.flops[i].q for i in W}
        extw = [s for s in cw.leaves if s not in qw]
        nxt = self.states_eval(W, self._lane_bits(extw, [res["lane"]]), states, cw, extw)[0]
        counting = nxt != states
        out = True
        if counting.any() and not counting.all():
            cones = self.__dict__.setdefault("_ycones", {})
            cone = cones.get(x)
            if cone is None:
                cone = cones[x] = _Cone(self.g, [ctl.f(x)])
            ext = [s for s in cone.leaves if s not in qw]
            fx = self.lit_eval(cone, W, ext, self._lane_bits(ext, [res["lane"]]), states)[0]
            out = bool(fx[counting].any() and not fx[counting].all())
        memo[key] = out
        return out

    def _carry_in(self, rec, lits):
        """The toggling self-looped flops outside the word that its LSB reads, sitting below it in
        one arithmetic (_nested_below) and not reading it under the literals: the bits whose carry
        the word may count (a cascaded counter's, or an adder's low bits), structural order."""
        ctl = self.ctl
        W = set(rec["bits"])
        out = []
        for y in sorted(set(ctl.supp_flops[rec["bits"][0]]) - W, key=self.fk):
            if ctl.self_neg[y] and y in ctl.supp_flops[y] and not self._quiet(y) \
                    and self._nested_below(y, rec) and not self._reads(y, rec["bits"], lits):
                out.append(y)
        return out

    def _nested_below(self, x, rec):
        """Flop x sits below the word in one arithmetic: every source x's next state reads (but x)
        is read by the word's lowest bit too (an adder's bit reads the addend and the bits below,
        as the next bit does); an enable or a compare reads sources of its own."""
        ctl = self.ctl
        qx = ctl.flops[x].q
        sx = set(ctl.supp_src[x]) - {qx}
        if not sx:
            return False
        # a per-bit load (x's own data bit) is the one source the next bit may not share
        return len(sx - set(ctl.supp_src[rec["bits"][0]])) <= max(1, int(self.P["NEST_SHARE_SLACK"] * len(sx)))

    def _can_change(self, x, v, lits):
        """Flop x (pinned to v by the literals) can take the other value next (SAT; memoized)."""
        memo = self.__dict__.setdefault("_cc_memo", {})
        key = (x, v, tuple(sorted(set(lits))))
        if key not in memo:
            f = self.ctl.f(x)
            memo[key] = self._unsat(list(lits) + [f ^ 1 if v else f]) is False
        return memo[key]

    def _adder_below(self, xs, rec):
        """Flops xs put under the word as its low bits make an adder: the table of xs + word is
        rejected as one (two steps s and 2s, many constant steps, every step) or, read as a counter,
        takes data-dependent steps; a toggle that enables the word (a phase, a prescaler) makes a
        counter or something irregular, a sequencer's bit something irregular."""
        word = list(xs) + list(rec["bits"])
        if len(word) > self.P["EXHAUSTIVE_WIDTH"]:
            return False
        key = ("adder_below", tuple(word))
        if key in self._tables:
            return self._tables[key]
        out = False
        act, hold = self.test_lanes(word)
        if act:
            lanes = act + hold
            F, ext, E = self.table(word, lanes)
            r = interpret(F, len(word), self.reset_raw(word), tuple(range(len(word))), self.P["REL_STEPS_MAX"],
                          self.P["ORDER_TRIES"])
            if r["ok"]:
                r.update(word=list(word), F=F, ext=ext, E=E, lanes=lanes, reset_raw=self.reset_raw(word))
                out = self._data_step(r)
            else:
                out = r["why"] in _ADDER
        self._tables[key] = out
        return out

    def _prescaled(self, x, rec):
        """Flop x under the word as its LSB makes a counter (x a toggle that enables the word every
        other step: a phase or a 1-bit prescaler), where an adder's low bit makes an adder."""
        bits = [x] + list(rec["bits"])
        if len(bits) > self.P["EXHAUSTIVE_WIDTH"]:
            return True
        return self.screen(bits, "prescaled", hint=tuple(range(len(bits))), modes=False) is not None

    def _reads(self, x, word, lits):
        """Flop x's next state depends on some bit of the word under the literals (SAT; memoized)."""
        memo = self.__dict__.setdefault("_reads_memo", {})
        key = (x, tuple(word), tuple(sorted(set(lits))))
        if key not in memo:
            memo[key] = self._reads1(x, word, lits)
        return memo[key]

    def _reads1(self, x, word, lits):
        S, ctl = self.S, self.ctl
        f = ctl.f(x)
        leaves = self.g.cone([f])[1]
        for b in word:
            q = ctl.flops[b].q
            if q not in leaves:
                continue
            d = _mk(S, _XOR2, S.cofactor(f, q, 0), S.cofactor(f, q, 1))
            if self._unsat([l for l in lits if l >> 1 != q] + [d]) is False:
                return True
        return False

    def _at_terminal(self, L, pinned):
        """The pinned values hold every bit of word L at its terminal count (the state it wraps from
        counting up, or 0 counting down)."""
        w = len(L["bits"])
        M = L["params"]["modulus"] or (1 << w)
        tcs = []
        if L["params"]["direction"] in ("up", "updown"):
            tcs.append(M - 1)
        if L["params"]["direction"] in ("down", "updown"):
            tcs.append(0)
        for tc in tcs:
            if all(b in pinned and (pinned[b] ^ c) == ((tc >> k) & 1)
                   for k, (b, c) in enumerate(zip(L["bits"], L["comp"]))):
                return True
        return False

    def _cut(self, chosen):
        """A word whose bits store their value bit plainly in one run and complemented in the next
        (runs of two or more bits, in value order) is cut at such run boundaries when every part
        proves on its own and neighbouring parts count in opposite directions in their stored
        polarity: two cascaded counters of opposite directions (a prescaler counting up under a
        timer counting down reads as one counter over the timer's complemented bits), reported as
        a relation, never merged. Inverted storage for a reset value (a library without set flops)
        scatters the complemented bits instead; a counter reset to a value whose inverted bits form
        runs of two or more is cut too (a known risk)."""
        out = []
        for rec in chosen:
            comp = rec["comp"]
            n = len(comp)
            runs = []
            for k in range(n):
                if runs and comp[k] == comp[runs[-1][0]]:
                    runs[-1][1] = k + 1
                else:
                    runs.append([k, k + 1])
            edges = [0] + [runs[r][0] for r in range(1, len(runs))
                           if runs[r][1] - runs[r][0] >= 2 and runs[r - 1][1] - runs[r - 1][0] >= 2] + [n]
            if len(edges) <= 2:
                out.append(rec)
                continue
            parts = []
            for a, b in zip(edges, edges[1:]):
                word = rec["bits"][a:b]
                p = self._part(word, rec["gen"])
                if p is None or sorted(p["bits"]) != sorted(word):
                    parts = None
                    break
                parts.append(p)
            if not parts:
                out.append(rec)
                continue

            def stored_up(p):
                up = p["params"]["direction"] != "down"
                return up != (2 * sum(p["comp"]) > len(p["comp"]))

            dirs = [stored_up(p) for p in parts]
            if any(x != y for x, y in zip(dirs, dirs[1:])):
                self.stats["cut_words"] += 1
                out += parts
            else:
                out.append(rec)
        return out

    def _is_cut(self, rec):
        """The word would be cut into cascaded counters (_cut): no witness for another word."""
        memo = self.__dict__.setdefault("_cut_memo", {})
        key = tuple(rec["bits"])
        if key not in memo:
            memo[key] = self._cut([rec]) != [rec]
        return memo[key]

    def _part(self, word, gen):
        """A proven word of exactly these flops (value order), or None."""
        W = self.P["EXHAUSTIVE_WIDTH"]
        if len(word) < 2:
            return None
        if len(word) <= W:
            sr = self.screen(word, gen + "+cut", hint=tuple(range(len(word))))
            return self.realize(sr) if sr is not None else None
        sr = self.screen(word[:W], gen + "+cut", hint=tuple(range(W)), chain=list(word))
        return self.realize(sr) if sr is not None and sr.get("wide_ok") else None

    @staticmethod
    def _regular(rec):
        p = rec["params"]
        return p["modulus"] is not None or p["saturating"] is True

    def _grow_up(self, recs):
        """Screened words extended upward: a self-looped flop that reads every bit of the word (a next
        higher bit reads the whole carry) is tried on top, repeatedly, while the wider word passes."""
        ctl, W = self.ctl, self.P["EXHAUSTIVE_WIDTH"]
        sup = [set(s) for s in ctl.supp_flops]
        readers = self._readers()
        tried = {frozenset(r["bits"]) for r in recs}
        sets = [frozenset(r["bits"]) for r in recs]
        maximal = [r for r, S in zip(recs, sets) if not any(S < T for T in sets)]
        out, frontier = [], [r for r in maximal if len(r["bits"]) < W]
        while frontier:
            nxt = []
            for rec in frontier:
                S = set(rec["bits"])
                ups = set.intersection(*(readers[i] for i in S)) - S if S else set()
                # the next bit reads little besides the word: the fewest-support readers first
                for j in sorted(ups, key=lambda i: (len(sup[i]), self.fk(i)))[:self.P["UP_TRIES"]]:
                    key = frozenset(S | {j})
                    if key in tried:
                        continue
                    tried.add(key)
                    word = list(rec["bits"]) + [j]
                    rec2 = self.screen(word, rec["gen"] + "+up", hint=tuple(range(len(word))))
                    if rec2 is not None:
                        out.append(rec2)
                        if len(rec2["bits"]) < W:
                            nxt.append(rec2)
            frontier = nxt
        self.stats["grown_up"] = len(out)
        return out

    def _select(self, recs):
        """Disjoint words: wider over narrower (all are proven), except that a word with lane-dependent
        wraps or stops yields to a regular proven word of all but one of its bits (a data bit loaded
        at one count state, a flag set on the wrap, are no counter bits); equal widths (a
        chain prefix counts with the chain it may grow along): more flops that can toggle, regular,
        the busier LSB (the true LSB of a long chain changes most), then structural keys."""
        sn = self.ctl.self_neg
        regular = [r for r in recs if self._regular(r)]
        keep = []
        for r in recs:
            if not self._regular(r) and not r.get("wide_ok") and any(
                    len(a["bits"]) >= 2 and set(a["bits"]) < set(r["bits"]) and len(r["bits"]) - len(a["bits"]) == 1
                    for a in regular):
                self.stats["irregular_yields"] += 1
                continue
            keep.append(r)
        order = sorted(keep, key=lambda r: (-r.get("reach", len(r["bits"])), -sum(1 for i in r["bits"] if sn[i]),
                                            not self._regular(r), -_pc(self._active(r["bits"][0])),
                                            [self.fk(i) for i in r["bits"]]))
        taken, out = set(), []
        for r in order:
            if taken & set(r["bits"]):
                self.stats["overlap_dropped"] += 1
                continue
            taken |= set(r["bits"])
            out.append(r)
        return out

    def _toggles(self, taken):
        """1-bit counters: a flop that can invert its own state, outside every chosen word, whose
        change is not driven by a flop that reads it back (the bit of a larger feedback word)."""
        ctl = self.ctl
        sup = [set(s) for s in ctl.supp_flops]
        readers = collections.defaultdict(set)
        for j in range(ctl.F):
            for i in sup[j]:
                readers[i].add(j)
        in_block = {i for bl in getattr(ctl, "blocks", []) for b in bl if len(b) > 1 for i in b}
        out = []
        for i in sorted(range(ctl.F), key=self.fk):
            if not ctl.self_neg[i] or i in taken or self._quiet(i):
                continue
            if any(i in sup[j] for j in sup[i] if j != i):
                self.rejects["toggle read back"] += 1
                continue
            if any(ctl.self_neg[j] and j != i for j in readers.get(i, ())):
                self.rejects["toggle read by a toggling flop"] += 1
                continue
            if any(ctl.self_neg[j] and j != i for j in sup[i]):
                self.rejects["toggle driven by a toggling flop"] += 1
                continue
            if i in in_block:
                self.rejects["toggle inside a multi-flop block"] += 1
                continue
            if len({v for _L, v in ctl.profile[i].sets}) == 2:
                self.rejects["toggle with a set and a clear (a flag)"] += 1
                continue
            sr = self.screen([i], "toggle")
            rec = self.realize(sr) if sr is not None else None
            if rec is not None:
                out.append(rec)
        self.stats["toggles"] = len(out)
        return out

    def _cascades(self, chosen, structs):
        """Cascades A -> B: word B's count condition holds word A at its terminal count (the
        condition evidence); and, from every live lane, B counts only where A wraps (simulation
        evidence; words of at most 62 bits)."""
        info = []
        for rec in chosen:
            if len(rec["bits"]) > 62:
                info.append(None)
                continue
            _l, q, f = self._pool_values(rec["bits"], full=False)   # one lane set for every word
            p = sum(b << k for k, b in enumerate(rec["comp"]))
            vq, vf = q ^ p, f ^ p
            ns = 1 << len(rec["bits"])
            M = rec["params"]["modulus"] or ns
            s = rec["params"]["step"]
            d = (vf - vq) % ns
            cnt = ((d == s % ns) | (d == (-s) % ns)) & (vq != vf)
            up = rec["params"]["direction"] != "down"
            wrap = ((vq == M - 1) & (vf == 0)) if up else ((vq == 0) & (vf == M - 1))
            info.append((cnt, wrap))
        rels = []
        sup = [set(s) for s in self.ctl.supp_flops]
        for b, rb in enumerate(chosen):
            reads = set().union(*(sup[i] for i in rb["bits"]))
            pinned = {}
            for res in rb["proof"]["when"].values():
                for l in res["lits"]:
                    j = self.q2flop.get(l >> 1)
                    if j is not None:
                        pinned[j] = 1 - (l & 1)
            for a, ra in enumerate(chosen):
                if a == b:
                    continue
                by_cond = bool(pinned) and self._at_terminal(ra, pinned)
                by_sim = False
                if info[a] is not None and info[b] is not None and info[b][0].any() and reads & set(ra["bits"]):
                    cb, wa = info[b][0], info[a][1]
                    by_sim = bool(not (cb & ~wa).any())
                if by_cond or by_sim:
                    rels.append({"type": "cascade", "lower_word": structs[a]["id"], "upper_word": structs[b]["id"],
                                 "evidence": "condition" if by_cond else "simulation",
                                 "lanes": int(info[b][0].sum()) if info[b] is not None else None})
        return rels

    def meta(self):
        return {"stats": {k: int(v) for k, v in sorted(self.stats.items())},
                "rejected": {k: int(v) for k, v in sorted(self.rejects.items())}}


def find(ctl, params=None):
    """Counters of an analysed netlist (tools.s3.controls.analyze): see the module docstring."""
    t0 = time.perf_counter()
    C = Counters(ctl, params)
    chosen, structs, rels = C.run()
    words = [{"id": s["id"], "bits": [int(i) for i in rec["bits"]], "comp": [int(b) for b in rec["comp"]],
              "gen": rec["gen"], "cond_flops": [int(i) for i in rec["cond_flops"]]} for s, rec in zip(structs, chosen)]
    C.timings["total"] = time.perf_counter() - t0
    return {"structures": structs, "relations": rels, "words": words, "meta": C.meta(),
            "run": {"timings": {k: round(v, 3) for k, v in C.timings.items()},
                    "sat_calls": int(C.stats["sat_calls"])}}


def recognize(nl, params=None):
    """The control layer and this module alone, as a result dict (for development runs)."""
    over = dict(params or {})
    ctl = _controls.analyze(nl, over)   # every name is a params entry now, so the layer takes them all
    rep = find(ctl, over)
    return {"schema": RESULT_SCHEMA, "structures": rep["structures"],
            "groups": [list(s["flops"]) for s in rep["structures"]],
            "meta": {"recognizer": "counter", "counter": rep["meta"], "relations": rep["relations"]}}
