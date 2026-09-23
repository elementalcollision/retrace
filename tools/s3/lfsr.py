"""S3 LFSR/CRC recognizer (the S3 design doc, section 3.5; result claims per schema.py's
"Verification (v2, kind-bound)").

Finds words whose next state is a GF(2)-affine map of their own bits for fixed settings of the
signals around them: linear feedback shift registers (Fibonacci or Galois, k steps per clock,
autonomous or with data injected), CRC registers (fixed or programmable taps, serial or word-parallel
with any number of data bits per clock), data-whitening LFSRs, and other GF(2)-affine feedback words
(form "affine"). Everything is computed from the anonymous netlist through the control layer
(tools.s3.controls): lanes, the reset, case-conditioned witnesses, profiles and the support
structure. Simulation suggests, a proof decides: every claim a structure carries is proven here
(exact affine forms, else SAT) before it is emitted, and the harness checks it again.

Pipeline, per candidate word (a block of the state-support graph, at most WORD_CAP flops, except
that a whole SCC or block closed under the combining relation -- nothing outside it feeds any of its
next states -- is analysed whole up to LFSR_WIDE_CAP flops, because it is the only word its flops can
form and needs no choice of cut: see candidates()):
  1. Mode lanes: live lanes where some bit of the word changes (the pool, plus case-conditioned
     witnesses of "the word does not hold" when fewer than N_MIN exist).
  2. Per lane r, the state Jacobian A(r) (flip each bit of the word) and an affinity test
     (random state vectors a: f(r ^ a) = f(r) ^ A(r) a). Rows that fail on most lanes drop out
     of the word, which is retried once; a lane that fails is a mode chosen by the word's own
     state (a reseed) and is left out of the mode classes.
  3. Mode classes: A(r) = C^k for a one-step companion matrix C, read on the columns (Galois:
     C e_j = e_(j-1), C e_0 = t in stage coordinates) or on the rows (Fibonacci: the same on A^T).
     Two root finders, both exact (a root is accepted only when C^k == A), cheapest first:
     (a) chain search, for k < w: the unit columns of C^k are stride-k links forming k chains;
         every interleaving of the chains that fits their lengths is tried (first while there are
         at most w^2 interleavings; up to LFSR_ROOT_MAX only when (b) cannot apply);
     (b) centralizer roots, for any k (word-parallel CRCs with k >= w, and (a) past w^2):
         C commutes with A, so when A is cyclic (it is for a squarefree feedback polynomial and
         k a power of two, and generically otherwise) C = p(A) for a polynomial p of degree < w,
         and p is fixed by one image C e_i = e_j of a unit vector (a Krylov basis of A from e_i).
         Every j is tried for two starts i (at most one index, the feedback stage, has a
         non-unit column), each C = p(A) is kept when it has the companion shape, and k is the
         smallest k <= LFSR_K_MAX with C^k = A.
     The feedback vector t gives the taps and the polynomial (bit i = coefficient of x^i, x^w
     included); the chain gives the bit order. When both readings give roots with the same k
     (the graphs coincide, e.g. a trinomial) the form is "both", the Fibonacci reading's order is
     reported (a convention, unchanged) and the Galois reading's is in
     proof["lfsr"]["other_reading_order"] (the two differ
     by a rotation of the stages; nothing in the netlist prefers one). A partial permutation (a shift, rotation or hold) is not an LFSR; neither is a
     companion whose feedback has fewer than two taps. A word whose matrix is affine, strongly
     connected and not a companion power is reported with form "affine" (poly and k_steps null).
  4. Sources: at a class representative lane, every other source of the word's cone is flipped
     with the state held and under random state vectors. A source whose effect depends on the
     state is a parameter (it selects the mode or sets taps); one whose effect does not is a data
     input, unless data inputs interact with each other (a bit-order select, a read-mux select):
     then a greedy vertex cover of the interaction graph moves the selects to the parameters.
  5. The mode model: with every parameter as at the lane, b = f(V = 0) and the columns of
     [A | B] = f(e_v) ^ b for v in V = word bits + data inputs, checked on random V vectors.
     Steps per clock and inputs per step from the data columns: with one-step companion C they
     are n Krylov chains b_r, C b_r, ..., C^(k-1) b_r (n = n_inputs); k is confirmed by C^k = A.
     Without a chain structure, k is the root's and n_inputs = m / k when integral. When k is
     only known modulo the period (C^k = C^(k+T)), the data chains pick k, among the matrix's
     other companion roots too (C^k = (C^-1)^(T-k): the reciprocal polynomial).
  6. Programmable taps: a parameter whose flip keeps the chain order and k but changes the taps
     is a tap coefficient. A tap coefficient that is a FLOP (or two lanes of one class with
     different taps and no coefficient found) makes the polynomial "programmable": a register
     holds the taps, which is what the truth's convention means by the word. The taps are then
     probed at p = 0 and at every one-hot p (the other parameters as at the lane): matched,
     scope "probed". When every tap coefficient is a signal that is not a flop -- a mode pin --
     each setting is instead an ordinary LFSR/CRC with a constant polynomial: the probed p = 0
     setting becomes the defining mode (pin_mode), its constant is params.poly, proven under
     control.when like any other mode, and the other probed settings are listed in
     proof["lfsr"]["pin_modes"]. Which setting to report is a convention, as for form "both".
  7. Claims (schema v2): control.when = the defining mode's COND; each flop's defining claim is
     {"type": "next", "flop", "equals": XOR of the structure's own q's, nets in control.inputs
     and a constant, "when": control.when, "role": "defining"}. COND = the parameter frontier:
     the parameter-only signals that feed logic reading V, at their lane values, net-carried,
     compressed by controlling values and generalised by dropping literals whose removal is
     proven harmless. Proof per bit, exact, never sampled: under COND (its nets, and the fanins
     they force, replaced by their values) every cone signal is computed as a function of at most
     LFSR_PARITY_BASIS parities of the cone leaves (_Parity: a truth table over affine forms,
     reduced by linear dependencies and by the span of its Walsh support), and the next state's
     single affine form must equal the claim's; a signal past the cap, or a mismatch, goes to SAT
     on the word's incremental solver. COND is non-vacuous: the lane satisfies it, and SAT
     confirms it with every async control of the word inactive. Other modes (other step counts,
     probed tap settings) are proven the same way and listed as cases {when, inputs, claims
     (flop, equals)} in proof["modes"] and proof["probe"]["cases"]; the harness checks
     proof.claims only (schema v2: one "when" per structure). Reset
     values come from the profile's proven cover steps; control.reset / reset_value are set when
     proven for every flop and when & ~reset is satisfiable, control.hold when every flop is
     proven to keep its value outside when and the reset.
  8. Own-matrix gate (_own_gate), applied to the defining claims as the harness reads them: no
     zero row (a bit whose claim reads no own bit restates that flop's D), no dead column (a bit
     no claim reads is a passenger, not a stage) and some row XORing at least two own bits (else
     the matrix is a partial permutation: a shift, a ring or a copy). A word that fails it is not
     emitted; the harness refuses exactly these three.

Results: find(ctl) -> {"structures": [...], "meta": {...}} in the result schema (flop ids are
netlist cell ids); recognize(nl) runs the control layer first and returns a whole result.
"""

from __future__ import annotations

import collections
import hashlib
import itertools
import math
import time

import numpy as np

from tools.s3 import controls as _controls
from tools.s3 import params as _params
from tools.s3.netlist import CONST, FLOP, GATE, Sim, _cof, _full, isop

RESULT_SCHEMA = "retrace-s3-result/1"
KIND = "lfsr_crc"

# =================================================================================================
# This module's thresholds are tools.s3.params entries, each justified there (moved from this module
# on 2026-09-22); each is overridable by name (lfsr.find(ctl, {name: value})). LOCAL is a view by
# name for callers.
LOCAL = {k: getattr(_params, k) for k in ("LFSR_FLIPS", "LFSR_LANES_SCAN", "LFSR_CLASS_LANES",
                                          "LFSR_ROOT_MAX", "LFSR_K_MAX", "LFSR_MODES_CLAIMED",
                                          "LFSR_PROBE", "LFSR_COND_DROPS", "LFSR_MIN_WIDTH",
                                          "LFSR_NONLIN_ROW", "LFSR_AFFINE_MIN_WIDTH",
                                          "LFSR_PARITY_BASIS",
                                          # moved into tools/s3/params.py from this module's own
                                          # block on 2026-09-22 (changes.jsonl C56-C58)
                                          "LFSR_WIDE_CAP", "LFSR_PIN_POLY", "LFSR_OWN_GATE")}

# =================================================================================================

# The harness's published COND limit (verify.COND_LITERALS), mirrored in params: a longer COND cannot verify.
HARNESS_COND_LITERALS = _params.HARNESS_COND_LITERALS
# Derived in the code, not tunable: the chain search runs first while it needs at most w^2
# interleavings (the centralizer's own cost scale); the centralizer tries 2 start indices (only one
# index, the feedback stage, has a non-unit column); a parity function's basis may reach
# 2 x LFSR_PARITY_BASIS forms before it is reduced (a 2-input gate of two full fanins).
# =================================================================================================


def _resolve(params, base=None):
    """Parameters: `base` (the control layer's, when given) or tools.s3.params, then LOCAL, then
    `params` (an unknown name is an error)."""
    P = dict(base) if base is not None else _params.resolve()
    for k, v in LOCAL.items():
        P.setdefault(k, v)
    for k, v in (params or {}).items():
        if k not in P:
            raise KeyError(f"unknown parameter {k}")
        P[k] = v
    return P


def _h(*parts):
    return int.from_bytes(hashlib.blake2b(repr(parts).encode(), digest_size=8).digest(), "little")


def _pc(x):
    return bin(x).count("1")


# ---------------------------------------------------------------------------------------------
# GF(2) matrices as lists of int bitmasks (column j = the image of e_j)

def _transpose(cols, w):
    rows = [0] * w
    for j, c in enumerate(cols):
        while c:
            low = c & -c
            rows[low.bit_length() - 1] |= 1 << j
            c ^= low
    return rows


def _mat_vec(cols, v):
    out = 0
    while v:
        low = v & -v
        out ^= cols[low.bit_length() - 1]
        v ^= low
    return out


def _mat_mul(X, Y):
    return [_mat_vec(X, c) for c in Y]


def _mat_pow(C, k):
    out = [1 << j for j in range(len(C))]
    base = list(C)
    while k:
        if k & 1:
            out = _mat_mul(base, out)
        base = _mat_mul(base, base)
        k >>= 1
    return out


def _galois_cols(w, t):
    """The one-step Galois companion in stage coordinates (C e_j = e_(j-1), C e_0 = t)."""
    return [t] + [1 << (j - 1) for j in range(1, w)]


def _to_stage(v, stage):
    out = 0
    while v:
        low = v & -v
        out |= 1 << stage[low.bit_length() - 1]
        v ^= low
    return out


def _is_partial_perm(cols, w):
    """Every column and every row has at most one 1 (a shift, rotation, hold or drop)."""
    if any(c & (c - 1) for c in cols):
        return False
    rows = _transpose(cols, w)
    return not any(r & (r - 1) for r in rows)


def _strongly_connected(cols, w):
    """The dependency graph (column j reaches row i, i != j) is one strongly connected part."""
    succ = [set() for _ in range(w)]
    for j, c in enumerate(cols):
        while c:
            low = c & -c
            i = low.bit_length() - 1
            if i != j:
                succ[j].add(i)
            c ^= low
    comps = _controls._tarjan(w, [sorted(x) for x in succ])
    return len(comps) == 1 and len(comps[0]) == w


def _chains(cols, w, drop=()):
    """Chains of the unit-column links j -> i (column j is e_i, i != j; columns in `drop` are
    read as feedback): lists head..end, or None when the links are not disjoint acyclic paths
    covering every index."""
    nxt = {}
    indeg = collections.Counter()
    for j, c in enumerate(cols):
        if c and not (c & (c - 1)) and j not in drop:
            i = c.bit_length() - 1
            if i != j:
                nxt[j] = i
                indeg[i] += 1
    if any(v > 1 for v in indeg.values()):
        return None
    out, seen = [], set()
    for h in range(w):
        if indeg[h]:
            continue
        ch = [h]
        seen.add(h)
        while ch[-1] in nxt:
            x = nxt[ch[-1]]
            if x in seen:
                return None
            ch.append(x)
            seen.add(x)
        out.append(ch)
    if len(seen) != w:          # a cycle of unit links (a rotation) is not a chain
        return None
    return out


def _chain_root(cols, w, cap):
    """Chain search (k < w): (k, stage, t), None, or "budget" (an interleaving search was cut by
    the budget `cap`). A feedback column of C^k can itself be a unit vector (C^m t = e_i); when
    the unit links do not form valid chains, each unit column in turn is read as feedback."""
    r = _root_chains(cols, w, cap, _chains(cols, w))
    if isinstance(r, tuple):
        return r
    if r is False:
        return None
    cut = r == "budget"
    units = [j for j, c in enumerate(cols) if c and not (c & (c - 1)) and c != 1 << j]
    for j in units:
        r = _root_chains(cols, w, cap, _chains(cols, w, (j,)))
        if isinstance(r, tuple):
            return r
        cut = cut or r == "budget"
    return "budget" if cut else None


def _root_chains(cols, w, cap, chains):
    """The interleaving search over given chains: (k, stage, t), None (the chains do not fit a
    stride-k structure: worth another reading), False (they fit, but no interleaving works) or
    "budget" (more interleavings than `cap`)."""
    if not chains:
        return None
    k = len(chains)
    q, rem = divmod(w, k)
    longs = [c for c in chains if len(c) == q + 1]
    shorts = [c for c in chains if len(c) == q]
    if len(longs) != rem or len(shorts) != k - rem:
        return None
    n = math.factorial(len(longs)) * math.factorial(len(shorts))
    if n > cap:
        return "budget"
    for pl in itertools.permutations(longs):
        for ps in itertools.permutations(shorts):
            order = list(pl) + list(ps)             # order[r] = chain with residue r
            stage = [0] * w
            for r, ch in enumerate(order):
                L = len(ch)
                for m, node in enumerate(ch):
                    stage[node] = r + k * (L - 1 - m)
            t = _to_stage(cols[order[k - 1][-1]], stage)
            v = t
            ok = True
            for r in range(k - 1, -1, -1):
                if _to_stage(cols[order[r][-1]], stage) != v:
                    ok = False
                    break
                v = (v >> 1) ^ (t if v & 1 else 0)
            if ok:
                return k, stage, t
    return False


def _companion_shape(C, w):
    """(stage, t) when C (columns, word coordinates) is a Galois-reading companion: w - 1 unit
    columns forming one chain (stage j -> stage j - 1) and one feedback column at its end
    (stage 0) with at least two taps; else None."""
    nxt = {}
    fb = None
    for j, c in enumerate(C):
        if c and not (c & (c - 1)) and c != 1 << j:
            nxt[j] = c.bit_length() - 1
        else:
            if fb is not None:
                return None
            fb = j
    if fb is None or len(nxt) != w - 1:
        return None
    indeg = [0] * w
    for i in nxt.values():
        indeg[i] += 1
    heads = [j for j in range(w) if indeg[j] == 0]
    if len(heads) != 1 or max(indeg) > 1:
        return None
    stage = [None] * w
    x, s = heads[0], w - 1
    while True:
        stage[x] = s
        if x not in nxt:
            break
        x = nxt[x]
        s -= 1
    if s != 0 or x != fb:
        return None
    t = _to_stage(C[fb], stage)
    if _pc(t) < 2:
        return None
    return stage, t


class _Krylov:
    """Per start index i, the Krylov basis A^m e_i (m < w) of a matrix in reduced form, when it
    spans (A is cyclic and e_i a cyclic vector); and C = p(A) from one image C e_i = e_j, its
    columns p(A) e_x built from the columns of A^0..A^(w-1) (computed on first use)."""

    def __init__(self, M, w):
        self.M, self.w = M, w
        self._piv = {}
        self._cols = None

    def basis(self, i):
        if i not in self._piv:
            piv = {}
            x0 = 1 << i
            for m in range(self.w):
                x, comb = x0, 1 << m
                while x:
                    p = x.bit_length() - 1
                    if p not in piv:
                        break
                    vx, vc = piv[p]
                    x ^= vx
                    comb ^= vc
                if not x:
                    piv = None
                    break
                piv[x.bit_length() - 1] = (x, comb)
                x0 = _mat_vec(self.M, x0)
            self._piv[i] = piv
        return self._piv[i]

    def poly(self, i, j):
        """The coefficients p (bit m = coefficient of A^m) with p(A) e_i = e_j, or None."""
        piv = self.basis(i)
        if piv is None:
            return None
        comb, y = 0, 1 << j
        while y:
            vx, vc = piv[y.bit_length() - 1]
            y ^= vx
            comb ^= vc
        return comb

    def column(self, p, x):
        """Column x of p(A)."""
        if self._cols is None:
            w = self.w
            P = [[1 << j for j in range(w)]]
            for _ in range(w - 1):
                P.append(_mat_mul(self.M, P[-1]))
            self._cols = [[P[m][c] for m in range(w)] for c in range(w)]
        col = self._cols[x]
        v, m = 0, 0
        while p:
            if p & 1:
                v ^= col[m]
            p >>= 1
            m += 1
        return v

    def root(self, i, j):
        """C = p(A) with C e_i = e_j (None when e_i is not a cyclic vector of A)."""
        p = self.poly(i, j)
        if p is None:
            return None
        return [self.column(p, x) for x in range(self.w)]

    def companion(self, i, j):
        """C = p(A) with C e_i = e_j when it has the companion shape (columns built one at a
        time, rejected at the second non-unit column), else None."""
        p = self.poly(i, j)
        if p is None:
            return None
        C, nonunit = [], 0
        for x in range(self.w):
            c = self.column(p, x)
            if not c or (c & (c - 1)) or c == 1 << x:
                nonunit += 1
                if nonunit > 1:
                    return None
            C.append(c)
        return C


def _centralizer_roots(M, w, kmax):
    """Every companion root of M found through the centralizer: ([(k, stage, t)], smallest k
    first; whether some unit vector is a cyclic vector of M). C commutes with M = C^k, so for a
    cyclic M, C = p(M), and one image C e_i = e_j fixes p. Two cyclic starts e_i are tried (at
    most one index, the feedback stage, has a non-unit column in C, so one of any two starts
    meets a unit column); for an invertible C all unit vectors are cyclic or none (e_s = C^s e_0
    in stage coordinates), a singular C (no constant term) may leave only some of them cyclic."""
    if w < 2:
        return [], False
    K = _Krylov(M, w)
    found = {}
    starts = 0
    for i in range(w):
        if K.basis(i) is None:
            continue
        starts += 1
        for j in range(w):
            if j == i:
                continue
            C = K.companion(i, j)
            if C is None:
                continue
            r = _companion_shape(C, w)
            if r is None:
                continue
            stage, t = r
            key = (tuple(stage), t)
            if key in found:
                continue
            Ck = C
            for k in range(1, kmax + 1):
                if Ck == M:
                    found[key] = k
                    break
                Ck = _mat_mul(C, Ck)
        if starts == 2:
            break
    return sorted(((k, list(st), t) for (st, t), k in found.items()), key=lambda x: (x[0], x[2], x[1])), starts > 0


def _companion_roots(M, w, cap, kmax):
    """Companion roots of M in its column (Galois) reading: [(k, stage, t)], the preferred first.
    Cheapest exact method first: the chain search while it needs no more interleavings than w^2
    (the centralizer's own cost scale), then the centralizer roots (any k; A cyclic), then, only
    when the unit vectors are not cyclic vectors of M (the centralizer cannot apply), the chain
    search up to `cap` interleavings (a derogatory A with k < w)."""
    r = _chain_root(M, w, w * w)
    if isinstance(r, tuple) and _pc(r[2]) >= 2:
        return [r]
    roots, cyclic = _centralizer_roots(M, w, kmax)
    if roots:
        return roots
    if r == "budget" and not cyclic and cap > w * w:
        r = _chain_root(M, w, cap)
        if isinstance(r, tuple) and _pc(r[2]) >= 2:
            return [r]
    return []


def _root_given(cols, w, k, stage):
    """t if A (columns) = C^k for the companion C of the given stage numbering, else None."""
    at = [0] * w
    for idx in range(w):
        at[stage[idx]] = idx
    if k > w:                  # k <= w: every column is a chain end or a stride-k link (direct check)
        C = _Krylov(cols, w).root(at[w - 1], at[w - 2])
        if C is None:
            return None
        r = _companion_shape(C, w)
        if r is None or r[0] != list(stage) or _mat_pow(C, k) != list(cols):
            return None
        return r[1]
    conv_of = {}

    def conv(c):
        v = conv_of.get(c)
        if v is None:
            v = conv_of[c] = _to_stage(c, stage)
        return v

    for st in range(k, w):
        if conv(cols[at[st]]) != 1 << (st - k):
            return None
    t = conv(cols[at[k - 1]])
    v = t
    for r in range(k - 1, -1, -1):
        if conv(cols[at[r]]) != v:
            return None
        v = (v >> 1) ^ (t if v & 1 else 0)
    return t


def _poly_of(t, w):
    """Characteristic polynomial of the companion matrix with feedback t (stage coordinates):
    x^w + sum_j t_j x^(w-1-j); bit i = coefficient of x^i."""
    p = 1 << w
    for j in range(w):
        if (t >> j) & 1:
            p |= 1 << (w - 1 - j)
    return p


def _matrix_gate(cols, w):
    """The harness's own-matrix gates on a matrix in column form (column j = the image of e_j): no
    zero row, no dead column, some row with at least two entries. A companion power passes; a
    programmable word at a tap setting that leaves a stage constant (its polynomial has no tap
    there, so that stage holds 0 and nothing reads it) does not, and neither does the harness."""
    rows = _transpose(cols, w)
    return bool(all(rows) and all(cols) and max((_pc(r) for r in rows), default=0) >= 2)


def _own_gate(claims, cells):
    """The own-bit matrix of a set of defining claims, as the harness reads it (its own _lfsr and
    _xor_form: the {"q": id} leaves of each claim's EXPR, odd multiplicities kept), against
    the gates it applies: every row holds at least one own bit (no zero row: a bit whose next state
    is input and constant only is not part of the recurrence), every own bit is read by some row (no
    dead column: a bit nothing reads is a tail, not a stage), and some row XORs at least two own bits
    (else the matrix is a partial permutation: a shift, a ring or a copy). Returns the report
    (own_matrix in the harness's own words) with "ok"."""
    own = {f: set() for f in cells}
    for cl in claims:
        if cl.get("role", "defining") != "defining":
            continue
        acc = set()
        stack = [cl.get("equals")]
        while stack:
            x = stack.pop()
            if not isinstance(x, dict) or len(x) != 1:
                continue
            (op, a), = x.items()
            if op == "q":
                acc ^= {a}
            elif op == "not":
                stack.append(a)
            elif op == "xor" and isinstance(a, list):
                stack.extend(a)
        own[cl.get("flop")] = acc
    rows = [own.get(f) or set() for f in cells]
    cols = collections.Counter(x for r in rows for x in r)
    wmax = max((len(r) for r in rows), default=0)
    zero_rows = sum(1 for r in rows if not r)
    dead_cols = sum(1 for f in cells if not cols.get(f))
    return {"ok": bool(wmax >= 2 and not zero_rows and not dead_cols), "max_row_weight": wmax,
            "zero_rows": zero_rows, "dead_columns": dead_cols}


def _classify(cols, w, cap, kmax, known=None):
    """The one-step form of a per-clock matrix A (columns): {"kind": "lfsr", "form" (the reading
    whose stage order is reported: "galois" or "fibonacci"), "k", "stage", "taps", "poly", "both",
    "alts"} | {"kind": "partial_permutation" (a shift, rotation or drop) | "no_state_term" (a
    load) | "identity" (a hold, with or without data) | "other_affine"}. `known` (a list of
    (form, k, stage, both) found on other lanes of the word) is tried first. "both": the other
    reading has a root with the same k (the two graphs are one, e.g. a trinomial); the Fibonacci
    reading's order is reported then, and "other_stage" is the other reading's. "alts": further
    centralizer roots of the same reading (larger k or other taps), for the data-chain check."""
    if all(c == 0 for c in cols):
        return {"kind": "no_state_term"}
    if all(c == 1 << j for j, c in enumerate(cols)):
        return {"kind": "identity"}
    if _is_partial_perm(cols, w):
        return {"kind": "partial_permutation"}
    rows = _transpose(cols, w)
    mats = {"fibonacci": rows, "galois": cols}
    other = {"fibonacci": "galois", "galois": "fibonacci"}
    for form, k, stage, both in (known or ()):
        t = _root_given(mats[form], w, k, list(stage))
        if t is not None and _pc(t) >= 2:
            ro = None
            if both:
                ro = next((r for r in _companion_roots(mats[other[form]], w, cap, kmax) if r[0] == k), None)
            return {"kind": "lfsr", "form": form, "k": k, "stage": list(stage), "taps": t,
                    "poly": _poly_of(t, w), "both": ro is not None, "other_stage": list(ro[1]) if ro else None,
                    "alts": None}                                          # None: not searched
    found = {}
    for form in ("galois", "fibonacci"):
        roots = _companion_roots(mats[form], w, cap, kmax)
        if roots:
            found[form] = roots
    if not found:
        return {"kind": "other_affine"}
    form = min(found, key=lambda f: (found[f][0][0], f != "fibonacci"))
    k, stage, t = found[form][0]
    ro = next((r for r in found.get(other[form], ()) if r[0] == k), None)
    return {"kind": "lfsr", "form": form, "k": k, "stage": list(stage), "taps": t, "poly": _poly_of(t, w),
            "both": ro is not None, "other_stage": list(ro[1]) if ro else None, "alts": [r for r in found[form][1:]]}


def _data_chains(D, Ct):
    """Data columns D (stage coordinates) as Krylov chains b_r, C b_r, ..., C^(L-1) b_r of the
    one-step matrix Ct: (L, number of chains) when every chain has the same length L, else None."""
    if not D or 0 in D or len(set(D)) != len(D):
        return None
    pos = {v: n for n, v in enumerate(D)}
    succ = {}
    for n, v in enumerate(D):
        m = pos.get(_mat_vec(Ct, v))
        if m is not None and m != n:
            succ[n] = m
    indeg = collections.Counter(succ.values())
    if indeg and max(indeg.values()) > 1:
        return None
    heads = [n for n in range(len(D)) if n not in indeg]
    lengths, seen = [], set()
    for h in heads:
        x, L = h, 0
        while x is not None and x not in seen:
            seen.add(x)
            L += 1
            x = succ.get(x)
        lengths.append(L)
    if len(seen) != len(D) or len(set(lengths)) != 1:
        return None
    return lengths[0], len(heads)


# ---------------------------------------------------------------------------------------------
# lane simulation of one word's cone

def _pack(X):
    """(m, L) uint8 bits -> (m, ceil(L div 64)) uint64 words, lane j = bit j & 63 of word j >> 6."""
    m, L = X.shape
    pad = (-L) % 64
    if pad:
        X = np.concatenate([X, np.zeros((m, pad), np.uint8)], axis=1)
    return np.ascontiguousarray(np.packbits(X, axis=1, bitorder="little")).view(np.uint64).reshape(m, -1)


def _unpack(W, L):
    m = W.shape[0]
    return np.unpackbits(np.ascontiguousarray(W).view(np.uint8).reshape(m, -1), axis=1, bitorder="little")[:, :L]


class _Cone:
    """The next-state cone of a word: its source leaves and a cone-restricted simulator."""

    CHUNK = 8192                 # lanes per simulation pass (memory: signals x CHUNK / 8 bytes)

    def __init__(self, ctl, word):
        g = ctl.g
        self.ctl, self.g = ctl, g
        self.word = list(word)
        self.w = len(word)
        self.f = np.array([ctl.f(i) for i in word], np.int64)
        gates, leaves = g.cone([int(x) for x in self.f])
        self.gates = gates
        self.leaves = np.array(sorted(s for s in leaves if g.kind[s] != CONST), np.int64)
        self.lidx = {int(s): k for k, s in enumerate(self.leaves)}
        self.qs = [ctl.flops[i].q for i in word]
        self.sidx = np.array([self.lidx.get(q, -1) for q in self.qs], np.int64)
        self.sim = Sim(g, 1, gates=gates)
        self.gate_list = np.array(sorted(gates), np.int64)

    def lane(self, r):
        """Leaf values of ctl lane r (uint8)."""
        V = self.ctl.V
        return ((V[self.leaves, r >> 6] >> np.uint64(r & 63)) & np.uint64(1)).astype(np.uint8)

    def run(self, X, want=None):
        """Evaluate the word's next states on lanes X (leaf rows x lanes, uint8). Returns (w, L)
        uint8, and with `want` (signals) also their values (len(want), L)."""
        L = X.shape[1]
        outs, extra = [], []
        for c0 in range(0, L, self.CHUNK):
            Xc = X[:, c0:c0 + self.CHUNK]
            Lc = Xc.shape[1]
            nw = -(-Lc // 64)
            V = np.zeros((self.g.n, nw), np.uint64)
            V[self.leaves] = _pack(Xc)
            self.sim.eval(V)
            outs.append(_unpack(Sim.lits(V, self.f), Lc))
            if want is not None:
                extra.append(_unpack(V[np.asarray(want, np.int64)], Lc))
        F = np.concatenate(outs, axis=1) if outs else np.zeros((self.w, 0), np.uint8)
        if want is None:
            return F
        return F, (np.concatenate(extra, axis=1) if extra else np.zeros((len(want), 0), np.uint8))


def _col_ints(M):
    out = []
    for j in range(M.shape[1]):
        v = 0
        nz = np.flatnonzero(M[:, j])
        for i in nz:
            v |= 1 << int(i)
        out.append(v)
    return out


# ---------------------------------------------------------------------------------------------
# proofs

class _IncSat:
    """One incremental SAT solver per word (z3's SAT core through its API): cones of the scratch
    graph are encoded on first use and kept, so the many claim checks of a word pay the encoding
    once; each check runs under assumptions with a per-call conflict limit (deterministic for a
    given sequence of checks). Answers: True (the literal is 0 whenever every assumed literal is
    1), False (refuted), None (conflict limit)."""

    def __init__(self, S, limit):
        import z3
        self.z3, self.S = z3, S
        self.ctx = z3.Context()
        self.s = z3.SolverFor("QF_FD", ctx=self.ctx)
        self.s.set("max_conflicts", int(limit))
        self.v = {}
        self.lits = {}
        self.acts = {}
        self.calls = 0

    def _var(self, sig):
        z3, S, V = self.z3, self.S, self.v
        stack = [sig]
        while stack:
            t = stack[-1]
            if t in V:
                stack.pop()
                continue
            if t == 0:
                x = z3.Bool("c0", self.ctx)
                self.s.add(z3.Not(x))
                V[0] = x
                stack.pop()
                continue
            if S.kind[t] != GATE:
                V[t] = z3.Bool(f"s{t}", self.ctx)
                stack.pop()
                continue
            pend = [f for f in S.fanin[t] if f not in V]
            if pend:
                stack.extend(pend)
                continue
            k = len(S.fanin[t])
            fan = [V[f] for f in S.fanin[t]]
            y = z3.Bool(f"s{t}", self.ctx)
            cl = []
            for cube in isop(S.tt[t], k):
                cl.append(z3.Or([z3.Not(fan[i]) if b else fan[i] for i, b in cube] + [y]))
            for cube in isop(_full(k) ^ S.tt[t], k):
                cl.append(z3.Or([z3.Not(fan[i]) if b else fan[i] for i, b in cube] + [z3.Not(y)]))
            self.s.add(*cl)
            V[t] = y
            stack.pop()
        return V[sig]

    def lit(self, L):
        x = self.lits.get(L)
        if x is None:
            v = self._var(L >> 1)
            x = self.lits[L] = self.z3.Not(v) if L & 1 else v
        return x

    def _act(self, assume):
        """An activation literal implying every assumed literal (one per distinct condition)."""
        key = tuple(sorted(set(assume)))
        a = self.acts.get(key)
        if a is None:
            z3 = self.z3
            a = self.acts[key] = z3.Bool(f"a{len(self.acts)}", self.ctx)
            na = z3.Not(a)
            self.s.add(*[z3.Or(na, self.lit(L)) for L in key])
        return a

    def zero(self, m, assume):
        """Is literal m 0 on every assignment satisfying the assumed literals?"""
        if m == 0 or any(a == 0 for a in assume):
            return True
        assume = [a for a in assume if a != 1]
        asm = [self._act(assume)] if assume else []
        if m != 1:
            asm.append(self.lit(m))
        self.calls += 1
        r = self.s.check(asm)
        if r == self.z3.unsat:
            return True
        if r == self.z3.sat:
            return False
        return None

    def satisfiable(self, assume):
        r = self.zero(1, assume)
        return None if r is None else not r


_PROJ = {}


def _proj(i, n):
    """Truth table of variable i over n variables (bit m = bit i of m), as an int of 2^n bits."""
    key = (i, n)
    v = _PROJ.get(key)
    if v is None:
        block = (1 << (1 << i)) - 1              # 2^i zeros then 2^i ones, repeated
        unit = block << (1 << i)
        v, step = 0, 1 << (i + 1)
        for m in range(0, 1 << n, step):
            v |= unit << m
        _PROJ[key] = v
    return v


def _tt_apply(tt, k, ins, full):
    """Truth table of a k-input function (table tt) applied to the inputs' truth tables."""
    out = 0
    for m in range(1 << k):
        if (tt >> m) & 1:
            term = full
            for i in range(k):
                term &= ins[i] if (m >> i) & 1 else full ^ ins[i]
                if not term:
                    break
            out |= term
    return out


def _tt_shift(T, u, n):
    """T(x ^ u) as a truth table over n variables."""
    for i in range(n):
        if (u >> i) & 1:
            s = 1 << i
            lo = _proj(i, n) ^ ((1 << (1 << n)) - 1)
            T = ((T >> s) & lo) | ((T & lo) << s)
    return T


class _Parity:
    """Exact next-state functions as functions of a few parities: every signal of a word's cone is
    h(z_1, ..., z_m), h a truth table and z_i affine forms over the cone leaves (an int: bit 0 the
    constant term, bit p + 1 leaf p), under a substitution of signals by constants. A gate composes
    its fanins' bases (made linearly independent), and the result is reduced exactly: variables h
    does not read are dropped, and a linear structure u (h(z ^ u) = h(z) for all z) merges
    variables (h then reads only parities of the z's). A signal is affine when one form remains:
    XORs built from NAND/AOI gates, or kept as two disjoint rails (a ^ b = (a & ~b) | (~a & b)),
    reduce to one form within a few gates. A signal whose basis would exceed `cap` parities has no
    function (None) and the caller falls back to SAT. Exact, never sampled."""

    def __init__(self, S, cap):
        self.S, self.cap = S, cap
        self.pre = 2 * cap              # parities before reduction (tables of 2^pre bits)
        self.pos = {}
        self.stats = collections.Counter()

    def leaf(self, s):
        p = self.pos.get(s)
        if p is None:
            p = self.pos[s] = len(self.pos)
        return 2 << p

    def closure(self, lits):
        """{signal: value} for COND literals (true when 1) and the fanin values they force: a gate
        at value v whose table, with its known fanins fixed, gives v only with fanin i = x forces
        fanin i to x (to a fixpoint). None when the values contradict each other (COND
        unsatisfiable: left to SAT)."""
        S = self.S
        out = {}
        for L in lits:
            s, v = L >> 1, 1 ^ (L & 1)
            if s == 0:
                if v:
                    return None
                continue
            if out.get(s, v) != v:
                return None
            out[s] = v
        changed = True
        while changed:
            changed = False
            for s in list(out):
                if S.kind[s] != GATE:
                    continue
                v, tt, fan = out[s], S.tt[s], S.fanin[s]
                k = len(fan)
                full = _full(k)
                for i, f in enumerate(fan):
                    if f in out:
                        tt = _cof(tt, k, i, out[f])
                if (tt if v else full ^ tt) == 0:
                    return None
                for i, f in enumerate(fan):
                    if f in out:
                        continue
                    for x in (0, 1):
                        cf = _cof(tt, k, i, 1 - x)
                        if (cf if v else full ^ cf) == 0:
                            out[f] = x
                            tt = _cof(tt, k, i, x)
                            changed = True
                            break
        return out

    def _reduce(self, T, B):
        """(T, B) reduced exactly, or None past the cap. h reads only the parities in the span of
        its Walsh spectrum's support (the annihilator of its linear structures u, h(z ^ u) = h(z)):
        those become the new variables, as XORs of the old forms. Unread variables drop out on the
        way (a variable outside every support vector); an affine h collapses to one form."""
        n = len(B)
        if n == 0:
            return T & 1, []
        N = 1 << n
        full = (1 << N) - 1
        # affine h (one support vector): collapse at once
        f0 = T & 1
        c = 0
        for i in range(n):
            if ((T >> (1 << i)) & 1) ^ f0:
                c |= 1 << i
        pred = full if f0 else 0
        for i in range(n):
            if (c >> i) & 1:
                pred ^= _proj(i, n)
        if pred == T:
            if c == 0:
                return f0, []
            z = f0
            for i in range(n):
                if (c >> i) & 1:
                    z ^= B[i]
            return 0b10, [z]
        # the span of the Walsh support (dimension m: h reads m parities)
        if n <= 4:
            U, uspan = [], {0}
            for u in range(1, N):
                if u not in uspan and _tt_shift(T, u, n) == T:
                    U.append(u)
                    uspan |= {x ^ u for x in uspan}
            W, span = [], {0}
            for w in range(1, N):
                if w in span or any(bin(w & u).count("1") & 1 for u in U):
                    continue
                W.append(w)
                span |= {x ^ w for x in span}
        else:
            v = 1 - 2 * np.unpackbits(np.frombuffer(T.to_bytes(max(1, N // 8), "little"), np.uint8),
                                      bitorder="little")[:N].astype(np.int64)
            h = 1
            while h < N:
                v = v.reshape(-1, 2, h)
                v = np.stack((v[:, 0, :] + v[:, 1, :], v[:, 0, :] - v[:, 1, :]), axis=1).reshape(-1)
                h *= 2
            W, piv = [], {}
            for a in np.flatnonzero(v).tolist():
                x = a
                while x:
                    p = x.bit_length() - 1
                    if p not in piv:
                        break
                    x ^= piv[p]
                if x:
                    piv[x.bit_length() - 1] = x
                    W.append(a)
                    if len(W) > self.cap:
                        return None
        m = len(W)
        if m > self.cap:
            return None
        if m == n:
            return T, B
        T2 = 0
        seen = set()
        for x in range(N):
            y = 0
            for r, w in enumerate(W):
                if bin(w & x).count("1") & 1:
                    y |= 1 << r
            if y not in seen:
                seen.add(y)
                if (T >> x) & 1:
                    T2 |= 1 << y
                if len(seen) == 1 << m:
                    break
        B2 = []
        for w in W:
            z = 0
            for j in range(n):
                if (w >> j) & 1:
                    z ^= B[j]
            B2.append(z)
        if m == 1 and T2 == 0b01:                # h = not z: fold into the form's constant
            return 0b10, [B2[0] ^ 1]
        return T2, B2

    @staticmethod
    def _restrict(T, n, keep):
        """T over the variables in `keep` (the others are not read)."""
        out = 0
        for y in range(1 << len(keep)):
            x = 0
            for r, i in enumerate(keep):
                if (y >> r) & 1:
                    x |= 1 << i
            if (T >> x) & 1:
                out |= 1 << y
        return out

    def _compose(self, s, memo):
        """The function of gate s from its fanins' functions (all known), or None."""
        S = self.S
        fan = S.fanin[s]
        # the union of the fanins' bases, made independent: form = XOR of basis[mask] ^ const
        basis, piv, expr = [], {}, {}
        for f in fan:
            for z in memo[f][1]:
                if z in expr:
                    continue
                x, mask = z, 0
                while x >> 1:
                    p = (x >> 1).bit_length() - 1
                    if p not in piv:
                        break
                    vx, vm = piv[p]
                    x ^= vx
                    mask ^= vm
                if x >> 1:
                    idx = len(basis)
                    basis.append(z)
                    piv[(x >> 1).bit_length() - 1] = (x, mask ^ (1 << idx))
                    expr[z] = (1 << idx, 0)
                else:
                    expr[z] = (mask, x & 1)
                if len(basis) > self.pre:
                    return None
        n = len(basis)
        full = (1 << (1 << n)) - 1
        ztt = {}
        ins = []
        for f in fan:
            h, Bf = memo[f]
            if not Bf:
                ins.append(full if h & 1 else 0)
                continue
            vals = []
            for z in Bf:
                v = ztt.get(z)
                if v is None:
                    mask, c = expr[z]
                    v = full if c else 0
                    j = 0
                    while mask:
                        if mask & 1:
                            v ^= _proj(j, n)
                        mask >>= 1
                        j += 1
                    ztt[z] = v
                vals.append(v)
            ins.append(_tt_apply(h, len(Bf), vals, full))
        T = _tt_apply(S.tt[s], len(fan), ins, full)
        if T == 0 or T == full:
            return (1 if T else 0), []
        return self._reduce(T, list(basis))

    def forms(self, lits, subst):
        """{literal: affine form (int) or None} under subst ({signal: 0 | 1}); None: not affine as
        far as the parity functions show (or past the cap). Incremental: a gate computed by the
        previous call is reused when none of its fanins changed (substituted differently, or
        recomputed here); every fanin is visited first (ids are topological), so a reused gate
        has its previous inputs exactly."""
        S = self.S
        old_sub, old = self._last if hasattr(self, "_last") else ({}, {})
        changed = {x for x in set(old_sub) | set(subst) if old_sub.get(x) != subst.get(x)}
        memo = {0: (0, [])}
        for x, v in subst.items():
            memo[x] = (v, [])
        need, stack = set(), [L >> 1 for L in lits]
        while stack:
            x = stack.pop()
            if x in need or x in memo:
                continue
            need.add(x)
            if S.kind[x] == GATE:
                stack.extend(S.fanin[x])
        dirty = set(changed)
        for x in sorted(need):                      # signal ids are topological
            if S.kind[x] != GATE:
                memo[x] = (0b10, [self.leaf(x)])
                continue
            fan = S.fanin[x]
            if x in old and not any(f in dirty for f in fan):
                memo[x] = old[x]
                self.stats["reused"] += 1
                continue
            dirty.add(x)
            if any(memo[f] is None for f in fan):
                memo[x] = None
                continue
            memo[x] = self._compose(x, memo)
            self.stats["gates"] += 1
        self._last = (dict(subst), memo)            # valid for this substitution only
        out = {}
        for L in lits:
            r = memo[L >> 1]
            if r is None:
                out[L] = None
            elif not r[1]:
                out[L] = (r[0] & 1) ^ (L & 1)
            elif len(r[1]) == 1 and r[0] == 0b10:
                out[L] = r[1][0] ^ (L & 1)
            else:
                out[L] = None
        return out


# ---------------------------------------------------------------------------------------------
# the recognizer

class _Word:
    """Analysis state of one candidate word."""

    def __init__(self, lf, word):
        self.lf = lf
        ctl = lf.ctl
        lab = ctl.labels
        self.word = sorted(word, key=lambda i: (lab[ctl.flops[i].q], i))
        self.cone = _Cone(ctl, self.word)
        self.w = len(self.word)
        self.rng = np.random.default_rng(_h("lfsr", sorted(lab[ctl.flops[i].q] for i in self.word)) & 0xFFFFFFFF)
        c = self.cone
        wset = set(c.qs)
        self.X = [int(s) for s in c.leaves if int(s) not in wset]
        self.X.sort(key=lambda s: (lab[s], s))
        self.xidx = np.array([c.lidx[s] for s in self.X], np.int64)
        self.info = {"flops": self.w, "sources": len(self.X), "cone_gates": len(c.gates)}
        self.sat = None
        self.pf = _Parity(ctl.S, lf.P["LFSR_PARITY_BASIS"])


class LFSR:
    def __init__(self, ctl, params=None):
        self.ctl = ctl
        self.P = _resolve(params, getattr(ctl, "P", None))
        self.stats = collections.Counter()
        self.timings = collections.OrderedDict()
        self.words = []
        self.structures = []
        self.sat_calls = 0

    # ----------------------------------------------------------------------- candidates
    def candidates(self):
        """Blocks of the state-support graph (and whole SCCs) of LFSR_MIN_WIDTH..WORD_CAP flops,
        each with a flop whose next state is structurally binate in another flop of the block
        (XOR feedback); deduplicated, in a label order.

        WORD_CAP bounds candidate *enumeration*: it is there because the blocks of a wide SCC can be
        cut in many ways and each cut is a guess. A whole SCC or block that is closed under the
        combining relation is not a guess -- no flop outside it feeds any of its next states, so it
        is the only word its flops can form -- and the affine solve runs on it whole up to
        LFSR_WIDE_CAP flops (a wide CRC or whitening word). Its sub-blocks are still capped."""
        ctl, P = self.ctl, self.P
        lab = ctl.labels
        seen, out = set(), []
        lo, hi = P["LFSR_MIN_WIDTH"], P["WORD_CAP"]
        wide_cap = max(hi, int(P["LFSR_WIDE_CAP"]))
        n_wide = 0

        def add(ws, cap=None):
            key = frozenset(ws)
            if lo <= len(key) <= (hi if cap is None else cap) and key not in seen:
                seen.add(key)
                out.append(sorted(key))
                return True
            return False

        def closed(ws):
            """No flop outside `ws` combines into it: the word's next states read its own bits and
            signals that are not flops of the design (ctl.combining drops wide-mux legs, so a load
            or read port does not open the word)."""
            s = set(ws)
            return all(set(ctl.combining[i]) <= s for i in ws)

        for k, comp in enumerate(ctl.sccs):
            add(comp)
            for b in ctl.blocks[k]:
                add(b)
            if len(comp) > hi:
                for share in (1.0, 0.0):
                    blocks, _cut = ctl.block_split(comp, share)
                    for b in blocks:
                        add(b)
                for b in [comp] + list(ctl.blocks[k]):        # whole closed blocks, past the cap
                    if hi < len(b) <= wide_cap and closed(b) and add(b, wide_cap):
                        n_wide += 1
        self.stats["candidates_wide_admitted"] = n_wide
        g = ctl.g
        Pp, Nn = self._unate()
        idx = g._source_index()
        keep = []
        for ws in out:
            bits = 0
            for j in ws:
                bits |= 1 << idx[ctl.flops[j].q]
            if any((Pp[i] & Nn[i] & bits) & ~(1 << idx[ctl.flops[i].q]) for i in ws):
                keep.append(ws)
        keep.sort(key=lambda ws: (-len(ws), min(lab[ctl.flops[i].q] for i in ws)))
        self.stats["candidates_blocks"] = len(out)
        self.stats["candidates_binate"] = len(keep)
        self.stats["candidates_wide"] = sum(1 for ws in keep if len(ws) > hi)
        return keep

    def _unate(self):
        if not hasattr(self, "_un"):
            self._un = self.ctl.g.unate_supports()
        return self._un

    # ----------------------------------------------------------------------- lanes
    def mode_lanes(self, W):
        """Live lanes where the word changes (case witnesses first when fewer than N_MIN)."""
        ctl, P = self.ctl, self.P
        act = np.zeros(ctl.W, np.uint64)
        for i in W.word:
            act |= ctl.active(i)
        n = int(np.bitwise_count(act).sum())
        if n < P["N_MIN"]:
            res = ctl.case_witnesses(W.word)
            W.info["case_witnesses"] = res["witnesses"]
            W.info["case_status"] = res["status"]
            act = np.zeros(ctl.W, np.uint64)
            for i in W.word:
                act |= ctl.active(i)
        lanes = np.flatnonzero(_unpack(act[None, :], 64 * ctl.W)[0])
        W.info["active_lanes"] = int(len(lanes))
        cap = P["LFSR_LANES_SCAN"]
        if len(lanes) > cap:
            sel = np.linspace(0, len(lanes) - 1, cap).round().astype(np.int64)
            lanes = lanes[np.unique(sel)]
        return [int(x) for x in lanes]

    # ----------------------------------------------------------------------- pass 0: Jacobians
    def scan(self, W, lanes):
        """Per lane: the state Jacobian (columns), affinity in the word's own bits, failing rows."""
        c, w = W.cone, W.w
        m = self.P["LFSR_FLIPS"]
        A_rand = W.rng.integers(0, 2, size=(m, w), dtype=np.uint8)
        per = 1 + w + m
        out = []
        for c0 in range(0, len(lanes), max(1, _Cone.CHUNK // per)):
            part = lanes[c0:c0 + max(1, _Cone.CHUNK // per)]
            X = np.empty((len(c.leaves), per * len(part)), np.uint8)
            for t, r in enumerate(part):
                base = c.lane(r)
                blk = np.repeat(base[:, None], per, axis=1)
                blk[c.sidx, 1 + np.arange(w)] ^= 1
                blk[np.ix_(c.sidx, 1 + w + np.arange(m))] ^= A_rand.T
                X[:, per * t: per * (t + 1)] = blk
            F = c.run(X)
            for t, r in enumerate(part):
                B = F[:, per * t: per * (t + 1)]
                F0 = B[:, 0]
                J = B[:, 1:1 + w] ^ F0[:, None]
                G = B[:, 1 + w:] ^ F0[:, None]
                pred = (J.astype(np.int64) @ A_rand.T.astype(np.int64)) & 1
                bad = (G != pred).any(axis=1)
                out.append((r, _col_ints(J), bad))
        return out

    # ----------------------------------------------------------------------- pass 1: sources
    def sources(self, W, r):
        """At lane r: (parameters, data candidates): sources whose flip effect depends on the word's
        state (under LFSR_FLIPS random state vectors), and sources whose effect does not but is
        nonzero somewhere."""
        c, w = W.cone, W.w
        m = self.P["LFSR_FLIPS"]
        nx = len(W.X)
        A_rand = W.rng.integers(0, 2, size=(m, w), dtype=np.uint8)
        per = 1 + nx + m * (1 + nx)
        base = c.lane(r)
        X = np.repeat(base[:, None], per, axis=1)
        if nx:
            X[W.xidx, 1 + np.arange(nx)] ^= 1
        for t in range(m):
            c0 = 1 + nx + t * (1 + nx)
            X[np.ix_(c.sidx, np.arange(c0, c0 + 1 + nx))] ^= A_rand[t][:, None]
            if nx:
                X[W.xidx, c0 + 1 + np.arange(nx)] ^= 1
        F = c.run(X)
        F0 = F[:, 0]
        d = F[:, 1:1 + nx] ^ F0[:, None]
        inter = np.zeros(nx, bool)
        eff = d.any(axis=0)
        for t in range(m):
            c0 = 1 + nx + t * (1 + nx)
            G = F[:, c0]
            H = F[:, c0 + 1:c0 + 1 + nx] ^ G[:, None]
            inter |= (H != d).any(axis=0)
            eff |= H.any(axis=0)
        params = [W.X[k] for k in range(nx) if inter[k]]
        data = [W.X[k] for k in range(nx) if not inter[k] and eff[k]]
        return params, data

    def model(self, W, r, data, params, zero_extra=None):
        """The affine model at lane r over V = word bits + data (every other source as at r; with
        zero_extra = {source: value}, those sources set so): {"vs": V, "b": f(V = 0), "M": columns
        f(e_v) ^ b, "ok": f = b ^ M v on random V vectors, "z": the leaf row with V = 0, "base"}."""
        c, w = W.cone, W.w
        Q = max(8, self.P["QUADRUPLES"] // 4)
        vs = list(W.cone.qs) + list(data)
        vidx = np.array([c.lidx[s] for s in vs], np.int64)
        nv = len(vs)
        base = c.lane(r)
        if zero_extra:
            for s, v in zero_extra.items():
                base[c.lidx[s]] = v
        z = base.copy()
        z[vidx] = 0
        R = W.rng.integers(0, 2, size=(Q, nv), dtype=np.uint8)
        per = 1 + nv + Q
        X = np.repeat(z[:, None], per, axis=1)
        X[vidx, 1 + np.arange(nv)] ^= 1
        X[np.ix_(vidx, 1 + nv + np.arange(Q))] ^= R.T
        F = c.run(X)
        b = F[:, 0]
        M = F[:, 1:1 + nv] ^ b[:, None]
        pred = ((M.astype(np.int64) @ R.T.astype(np.int64)) & 1) ^ b[:, None]
        ok = bool((F[:, 1 + nv:] == pred).all())
        return {"vs": vs, "b": b, "M": M, "ok": ok, "z": z, "base": base}

    def interactions(self, W, z, vs):
        """Pairs (x, y) of V sources (not both word bits) whose flips do not add up at z."""
        c = W.cone
        nq = W.w
        vidx = [c.lidx[s] for s in vs]
        pairs = [(a, b) for a in range(len(vs)) for b in range(a + 1, len(vs)) if b >= nq]
        per = 1 + len(vs) + len(pairs)
        X = np.repeat(z[:, None], per, axis=1)
        for a in range(len(vs)):
            X[vidx[a], 1 + a] ^= 1
        for k, (a, b) in enumerate(pairs):
            X[vidx[a], 1 + len(vs) + k] ^= 1
            X[vidx[b], 1 + len(vs) + k] ^= 1
        F = c.run(X)
        f0 = F[:, 0]
        out = []
        for k, (a, b) in enumerate(pairs):
            if ((F[:, 1 + len(vs) + k] ^ F[:, 1 + a] ^ F[:, 1 + b] ^ f0) != 0).any():
                out.append((vs[a], vs[b]))
        return out

    def fit(self, W, r, params, data, zero_extra=None):
        """Data inputs and the affine model at lane r; data sources that interact with each other
        are moved to the parameters by a greedy vertex cover (highest degree first)."""
        ctl = self.ctl
        lab = ctl.labels
        data = list(data)
        params = list(params)
        wset = set(W.cone.qs)
        for _it in range(4):
            mdl = self.model(W, r, data, params, zero_extra)
            if mdl["ok"]:
                break
            pairs = self.interactions(W, mdl["z"], mdl["vs"])
            if not pairs:
                return None
            deg = collections.Counter()
            edges = set()
            for a, b in pairs:
                if a in wset and b in wset:
                    return None
                edges.add((a, b))
                deg[a] += a not in wset
                deg[b] += b not in wset
            cover = set()
            while edges:
                x = max((s for s in deg if s not in wset and s not in cover),
                        key=lambda s: (deg[s], -lab[s], -s), default=None)
                if x is None:
                    return None
                cover.add(x)
                edges = {(a, b) for a, b in edges if a != x and b != x}
                deg = collections.Counter()
                for a, b in edges:
                    deg[a] += a not in wset
                    deg[b] += b not in wset
            data = [s for s in data if s not in cover]
            params = params + sorted(cover, key=lambda s: (lab[s], s))
        else:
            return None
        if not mdl["ok"]:
            return None
        nq = W.w
        M = mdl["M"]
        live = [k for k in range(len(data)) if M[:, nq + k].any()]
        zero = [data[k] for k in range(len(data)) if not M[:, nq + k].any()]
        if zero:
            data = [data[k] for k in live]
            params = params + zero
            mdl = self.model(W, r, data, params, zero_extra)
            if not mdl["ok"]:
                return None
        mdl["data"] = data
        mdl["params"] = params
        mdl["A"] = _col_ints(mdl["M"][:, :nq])
        mdl["B"] = _col_ints(mdl["M"][:, nq:])
        return mdl

    def steps(self, W, cl, mdl):
        """(k, n_inputs, root) of a mode from its data columns: n Krylov chains of equal length L
        under the one-step matrix, with C^L = C^k (L is the step count; the root's own k is only
        known modulo the period). The class root first, then its alternatives (other companion
        roots of the same matrix, e.g. the reciprocal polynomial's C^-1 when C^k = C^-(T-k) for
        period T). (k, None, root) when the data columns have no such structure."""
        w = W.w
        if not mdl["B"]:
            return cl["k"], None, (cl["k"], cl["stage"], cl["taps"])

        def fits(k, stage, t):
            Cg = _galois_cols(w, t)
            Ct = Cg if cl["form"] == "galois" else _transpose(Cg, w)
            ch = _data_chains([_to_stage(v, stage) for v in mdl["B"]], Ct)
            if ch is not None and (ch[0] == k or _mat_pow(Ct, ch[0]) == _mat_pow(Ct, k)):
                return ch
            return None

        primary = (cl["k"], list(cl["stage"]), cl["taps"])
        ch = fits(*primary)
        if ch is not None:
            return ch[0], ch[1], primary
        alts = cl.get("alts")
        if alts is None:
            M = mdl["A"] if cl["form"] == "galois" else _transpose(mdl["A"], w)
            alts = _companion_roots(M, w, self.P["LFSR_ROOT_MAX"], self.P["LFSR_K_MAX"])
        for k, stage, t in alts:
            root = (k, list(stage), t)
            if root == primary:
                continue
            ch = fits(*root)
            if ch is not None:
                return ch[0], ch[1], root
        return cl["k"], None, (cl["k"], cl["stage"], cl["taps"])

    # ----------------------------------------------------------------------- conditions
    def frontier(self, W, mdl):
        """Parameter-only signals feeding logic that reads V (or a next state that reads nothing
        of V), as literals true at the model's lane; net-less gates are replaced by their fanins.
        Returns (literals, values of every cone signal at the lane) or (None, _) when a signal can
        be neither named by a net nor split."""
        ctl, g = self.ctl, self.ctl.g
        c = W.cone
        idx = g._source_index()
        vmask = 0
        for s in mdl["vs"]:
            vmask |= 1 << idx[s]
        z = mdl["z"]
        sigs = c.gate_list
        _F, vals = c.run(z[:, None], want=sigs)
        val = {int(s): int(v) for s, v in zip(sigs, vals[:, 0])}
        for s, v in zip(c.leaves, z):
            val[int(s)] = int(v)
        vdep = {}

        def dep(s):
            x = vdep.get(s)
            if x is None:
                x = vdep[s] = bool(g.supp_bits(s) & vmask)
            return x

        front = set()
        for s in sigs:
            s = int(s)
            if not dep(s):
                continue
            for t in g.fanin[s]:
                if not dep(t) and g.kind[t] != CONST:
                    front.add(t)
        for x in c.f:
            s = int(x) >> 1
            if s and not dep(s):
                front.add(s)
        net = ctl._net
        lits = set()
        stack = sorted(front)
        seen = set()
        while stack:
            t = stack.pop()
            if t in seen:
                continue
            seen.add(t)
            if 2 * t in net:
                lits.add(2 * t + (1 - val[t]))
                continue
            if g.kind[t] != GATE:
                return None, val
            stack.extend(g.fanin[t])
        return sorted(lits), val

    def compress(self, lits, val):
        """Replace groups of literals by one fanin literal that forces each of them (a controlling
        value): sound, as the new literal implies every literal it replaced."""
        ctl, g = self.ctl, self.ctl.g
        lab = ctl.labels
        net = ctl._net
        cur = set(lits)
        for _level in range(4):
            force = collections.defaultdict(set)
            for L in cur:
                t, v = L >> 1, 1 - (L & 1)
                if g.kind[t] != GATE:
                    continue
                k = len(g.fanin[t])
                if k < 2:
                    continue
                for pos, x in enumerate(g.fanin[t]):
                    if 2 * x not in net or x not in val:
                        continue
                    vx = val[x]
                    cf = _cof(g.tt[t], k, pos, vx)       # still over k inputs, now independent of x
                    if cf == (_full(k) if v else 0):     # x = vx alone forces t = v
                        force[2 * x + (1 - vx)].add(L)
            changed = False
            while True:
                best, gain = None, 0
                for X, covered in force.items():
                    cov = covered & cur
                    gn = len(cov) - (0 if X in cur else 1)
                    key = (gn, -lab[X >> 1], -X)
                    if gn > 0 and (best is None or key > (gain, -lab[best >> 1], -best)):
                        best, gain = X, gn
                if best is None:
                    break
                cur -= force[best]
                cur.add(best)
                changed = True
            if not changed:
                break
        return sorted(cur, key=lambda L: (lab[L >> 1], L))

    # ----------------------------------------------------------------------- claims
    def _leaf(self, s, own):
        """EXPR leaf of source s: (json, inversion, input net or None). A flop of the structure is
        {"q": id}; any other source is the net carrying it (an input of the structure)."""
        ctl = self.ctl
        cell = own.get(s)
        if cell is not None:
            return {"q": cell}, 0, None
        hit = ctl._net.get(2 * s)
        if hit is None:
            return None
        n, inv = hit
        return {"net": int(n)}, int(inv), int(n)

    def expr_lits(self, W, mdl):
        """Per bit: (claimed literal on the scratch graph, EXPR (schema v2: an XOR of the
        structure's own q's, input nets and one constant), affine form over the cone leaves),
        and the input nets read ({net: source signal}); None when a data source has no net."""
        ctl = self.ctl
        S = ctl.S
        vs = mdl["vs"]
        M, b = mdl["M"], mdl["b"]
        own = {q: int(ctl.flops[i].cell) for q, i in zip(W.cone.qs, W.word)}
        out, inputs = [], {}
        for k in range(W.w):
            terms = [vs[j] for j in np.flatnonzero(M[k])]
            acc = int(b[k])
            par = int(b[k])
            leaves = []
            form = int(b[k])
            for s in terms:
                acc = S.lit_xor(acc, 2 * s)
                lf = self._leaf(s, own)
                if lf is None:
                    return None
                e, inv, net = lf
                leaves.append(e)
                par ^= inv
                if net is not None:
                    inputs[net] = s
                form ^= W.pf.leaf(s)
            if not leaves:
                e = {"const": par}
            elif par:
                e = {"xor": leaves + [{"const": 1}]}
            else:
                e = leaves[0] if len(leaves) == 1 else {"xor": leaves}
            out.append((acc, e, form))
        return out, inputs

    def _sat(self, W):
        if W.sat is None:
            W.sat = _IncSat(self.ctl.S, self.P["SAT_LIMIT_STRUCTURE"])
        return W.sat

    def _zero(self, W, m, assume):
        """SAT on the word's incremental solver: literal m is 0 whenever every assumed literal is 1."""
        self.sat_calls += 1
        self.stats["sat_calls"] += 1
        return self._sat(W).zero(m, assume)

    def _form_proven(self, W, items, cond):
        """Affine-form proofs: items [(key, next-state literal, expected form)] under COND
        literals; returns the keys whose next state's exact form equals the expected one."""
        sub = W.pf.closure(cond)
        if sub is None:
            return set()
        forms = W.pf.forms([f for _k, f, _e in items], sub)
        out = {k for k, f, e in items if forms[f] is not None and forms[f] == e}
        self.stats["parity_proven"] += len(out)
        self.stats["parity_open"] += len(items) - len(out)
        return out

    def check_word(self, W, ex, cond, first=None, bits=None):
        """Proof, one bit at a time (as the harness checks claims): under the COND literals, every
        bit's next state (or those in `bits`) equals its claimed literal; exact forms first, SAT
        for the bits it leaves open. True, False (refuted: that bit goes first next time, via
        `first`) or None (a conflict limit was reached)."""
        ctl = self.ctl
        S = ctl.S
        order = list(range(len(ex))) if bits is None else list(bits)
        if first is not None and first[0] is not None and first[0] in order:
            order.remove(first[0])
            order.insert(0, first[0])
        done = self._form_proven(W, [(k, ctl.f(W.word[k]), ex[k][2]) for k in order], cond)
        res = True
        for k in order:
            if k in done:
                continue
            i = W.word[k]
            m = S.lit_xor(ctl.f(i), ex[k][0])
            if m == 0:
                continue
            ok = self._zero(W, m, cond)
            if ok is True:
                continue
            if first is not None:
                first[0] = k
            if ok is False:
                return False
            res = None
        return res

    def _bit_supports(self, W, ex):
        """Per bit: the source bitset of its next state and of its claimed literal."""
        g, S = self.ctl.g, self.ctl.S
        return [g.supp_bits(self.ctl.f(i) >> 1) | S.supp_bits(x[0] >> 1) for i, x in zip(W.word, ex)]

    def generalise(self, W, ex, cond, drop_first=()):
        """Drop COND literals whose removal is proven harmless. A drop is tested on the bits whose
        sources meet the literal's support (the others cannot see it directly), then the result is
        checked on every bit; if that fails the input COND is returned unchanged (it was checked).
        drop_first: literal signals dropped for another mode of the word, tried together first.
        Budget: LFSR_COND_DROPS drop tests."""
        g = self.ctl.g
        sup = self._bit_supports(W, ex)
        cur = list(cond)
        if drop_first:
            trial = [L for L in cur if (L >> 1) not in drop_first]
            if len(trial) < len(cur) and self.check_word(W, ex, trial) is True:
                cur = trial
        budget = self.P["LFSR_COND_DROPS"]
        first = [None]
        i = 0
        while i < len(cur) and budget > 0:
            ls = g.supp_bits(cur[i] >> 1)
            bits = [k for k in range(len(ex)) if sup[k] & ls]
            trial = cur[:i] + cur[i + 1:]
            budget -= 1
            if self.check_word(W, ex, trial, first, bits) is True:
                cur = trial
            else:
                i += 1
        if len(cur) < len(cond) and self.check_word(W, ex, cur) is not True:
            self.stats["generalise_reverted"] += 1
            return list(cond)
        return cur

    def _async_off(self, W):
        """Literals (true when 1) saying every async clear / preset of the word's flops is inactive."""
        out = []
        for i in W.word:
            f = self.ctl.flops[i]
            for L in (f.clear, f.preset):
                if L and L != 1:
                    out.append(L ^ 1)
                elif L == 1:
                    out.append(0)                   # always active: no state satisfies the claim
        return out

    def mode_claims(self, W, mdl, generalise=True, drop_first=None):
        """Defining claims for one mode: (claims, info) or (None, reason). generalise: full
        literal-by-literal generalisation; drop_first (signals): only try dropping those, together."""
        ctl = self.ctl
        r = self.expr_lits(W, mdl)
        if r is None:
            return None, "a data source has no net"
        ex, inputs = r
        lits, val = self.frontier(W, mdl)
        if lits is None:
            return None, "a parameter signal has no net"
        n_front = len(lits)
        lits = self.compress(lits, val)
        n_comp = len(lits)
        ok = self.check_word(W, ex, lits)
        if ok is not True:
            return None, "refuted" if ok is False else "unknown"
        dropped = set()
        if generalise:
            g2 = self.generalise(W, ex, lits)
            dropped = {L >> 1 for L in lits} - {L >> 1 for L in g2}
            lits = g2
        elif drop_first:
            trial = [L for L in lits if (L >> 1) not in drop_first]
            if len(trial) < len(lits) and self.check_word(W, ex, trial) is True:
                dropped = {L >> 1 for L in lits} - {L >> 1 for L in trial}
                lits = trial
        cj = ctl.cond(lits)
        if cj is None or len(cj) > HARNESS_COND_LITERALS:
            return None, "condition not expressible"
        live = self._sat(W).satisfiable(list(lits) + self._async_off(W))
        if live is not True:
            return None, "condition not satisfiable with async controls inactive"
        claims = [{"type": "next", "flop": int(ctl.flops[i].cell), "equals": e, "when": cj, "role": "defining"}
                  for i, (_l, e, _f) in zip(W.word, ex)]
        lab = ctl.labels
        nets = sorted(inputs, key=lambda n: (lab[inputs[n]], n))
        return claims, {"cond_frontier": n_front, "cond_compressed": n_comp, "cond": len(lits), "lits": lits,
                        "dropped": dropped, "when": cj, "inputs": nets, "input_rank": {n: lab[inputs[n]] for n in nets}}

    def _prove(self, W, lit, expect_lit, expect_form, cond):
        """lit == expect_lit whenever the COND literals hold: exact forms, then SAT (True/False/None)."""
        if self._form_proven(W, [(0, lit, expect_form)], cond):
            return True
        return self._zero(W, self.ctl.S.lit_xor(lit, expect_lit), cond)

    def control_claims(self, W):
        """Reset (synchronous rho) and hold claims from each flop's proven cover steps, and the
        reset case for control when every flop has one: (claims, reset COND literals | None,
        {flop id: reset value})."""
        ctl = self.ctl
        R = ctl.reset
        rho = R.lit if R.kind == "sync" else None
        out = []
        rst, rst_c = {}, None
        for i in W.word:
            pr = ctl.profile[i] if ctl.profile else None
            if pr is None:
                continue
            cell = int(ctl.flops[i].cell)
            qf = W.pf.leaf(ctl.flops[i].q)
            if rho is not None and pr.reset is not None:
                c = self._named([rho])
                if c is not None:
                    v = int(pr.reset)
                    ok = self._prove(W, ctl.f(i), v, v, c)
                    if ok is True and self._sat(W).satisfiable(c):
                        out.append({"type": "next", "flop": cell, "equals": {"const": v},
                                    "when": ctl.cond(c), "role": "reset"})
                        rst[cell] = v
                        rst_c = c
            prev = []
            for (L, kind), proven in zip(pr.steps, pr.proven):
                if rho is not None and (ctl.rep(L) & ~1) == (ctl.rep(rho) & ~1):
                    prev.append(L ^ 1)
                    continue
                if kind == "h" and proven:
                    lits = prev + [L] + ([rho ^ 1] if rho is not None else [])
                    c = self._named(lits)
                    if c is not None:
                        ok = self._prove(W, ctl.f(i), ctl.qlit(i), qf, c)
                        if ok is True and self._sat(W).satisfiable(c):
                            out.append({"type": "next", "flop": cell, "equals": {"q": cell},
                                        "when": ctl.cond(c), "role": "hold"})
                            break
                prev.append(L ^ 1)
        full = rst_c is not None and len(rst) == W.w
        return out, (rst_c if full else None), (rst if full else None)

    def hold_outside(self, W, when_lits, reset_lits):
        """control.hold: outside the defining case and the reset, every flop keeps its value
        (proven per flop; the first failure answers False)."""
        ctl, S = self.ctl, self.ctl.S
        nw = 0
        for L in when_lits:
            nw = S.lit_or(nw, L ^ 1)
        if nw == 0:                                  # "when" is always: nothing lies outside it
            return False
        assume = [nw] + [L ^ 1 for L in (reset_lits or [])]
        for i in W.word:
            qf = W.pf.leaf(ctl.flops[i].q)
            if self._prove(W, ctl.f(i), ctl.qlit(i), qf, assume) is not True:
                return False
        return bool(self._sat(W).satisfiable(assume))

    def _named(self, lits):
        """Literals replaced by net-carried members of their literal classes (SAT-equal with rho
        inactive, which every condition here includes or is about), or None."""
        ctl = self.ctl
        out = []
        for L in lits:
            if L in ctl._net:
                out.append(L)
                continue
            rep = ctl.rep(L)                     # L == rep (the class literal, L's polarity)
            found = None
            for m in sorted(ctl.members(rep)):   # m == rep & ~1
                lit = m ^ (rep & 1)
                if lit in ctl._net:
                    found = lit
                    break
            if found is None:
                return None
            out.append(found)
        return out

    # ----------------------------------------------------------------------- one word
    def analyse(self, word, depth=0):
        """Structures found in one candidate word (a list: a split word can hold several)."""
        W = _Word(self, word)
        self.words.append(W.info)
        W.info["depth"] = depth
        try:
            out = self._analyse(W, depth)
        finally:
            W.sat = None                     # the word's solver and cone go with it
            W.info["parity_gates"] = int(W.pf.stats["gates"])
        if out is None:
            return []
        return out if isinstance(out, list) else [out]

    def _analyse(self, W, depth):
        P = self.P
        if W.cone.sidx.min() < 0:
            W.info["verdict"] = "a flop of the word is outside its own cone"
            return None
        lanes = self.mode_lanes(W)
        if not lanes:
            W.info["verdict"] = "never active"
            return None
        scan = self.scan(W, lanes)
        nbad = np.zeros(W.w, np.int64)
        for _r, _J, bad in scan:
            nbad += bad
        W.info["lanes_scanned"] = len(scan)
        badrows = nbad > P["LFSR_NONLIN_ROW"] * len(scan)
        if badrows.any():
            W.info["nonlinear_rows"] = int(badrows.sum())
            keep = [W.word[k] for k in range(W.w) if not badrows[k]]
            if depth < 2 and len(keep) >= P["LFSR_MIN_WIDTH"] and len(keep) < W.w:
                W.info["verdict"] = "retried without its nonlinear rows"
                return self.analyse(keep, depth + 1)
            W.info["verdict"] = "not affine in its own bits"
            return None
        nonlin = sum(1 for _r, _J, bad in scan if bad.any())
        if nonlin:
            W.info["nonlinear_lanes"] = nonlin     # a mode chosen by the word's own state
        scan = [x for x in scan if not x[2].any()]
        classes = collections.OrderedDict()
        affine = collections.OrderedDict()
        J_of = {r: tuple(J) for r, J, _bad in scan}
        cls_cache = {}
        kinds = collections.Counter()
        known = []
        t0 = time.perf_counter()
        for r, J, _bad in scan:
            key = tuple(J)
            cl = cls_cache.get(key)
            if cl is None:
                cl = cls_cache[key] = _classify(J, W.w, P["LFSR_ROOT_MAX"], P["LFSR_K_MAX"], known)
                if cl["kind"] == "lfsr" and all(kn[:3] != (cl["form"], cl["k"], tuple(cl["stage"])) for kn in known):
                    known.append((cl["form"], cl["k"], tuple(cl["stage"]), cl["both"]))
            kinds["lfsr_step" if cl["kind"] == "lfsr" else cl["kind"]] += 1
            if cl["kind"] == "lfsr":
                classes.setdefault((cl["form"], cl["k"], tuple(cl["stage"])), []).append((r, cl))
            elif cl["kind"] == "other_affine":
                affine.setdefault(key, []).append((r, cl))
        self.timings["classify"] = self.timings.get("classify", 0.0) + time.perf_counter() - t0
        W.info["lane_kinds"] = dict(sorted(kinds.items()))
        W.info["distinct_matrices"] = len(cls_cache)
        if not classes:
            if affine:
                st = self._affine_word(W, affine)
                if st is not None:
                    return st
            if depth < 2 and kinds.get("other_affine"):
                subs = self._split(W, scan)
                if subs:
                    W.info["verdict"] = f"split into {len(subs)} strongly connected parts"
                    return [st for sub in subs for st in self.analyse(sub, depth + 1)]
            if "verdict" not in W.info:
                W.info["verdict"] = "no LFSR mode"
            return None
        # one representative class order per chain order: the stage order must agree across modes
        order_key = collections.Counter()
        for (form, k, stage), lst in classes.items():
            order_key[(form, stage)] += len(lst)
        (form0, stage0), _n = max(order_key.items(), key=lambda kv: (kv[1], kv[0]))
        W.info["mode_classes"] = len(classes)
        modes = []
        prog_lanes = False
        chosen = sorted(((ck, lst) for ck, lst in classes.items() if (ck[0], ck[2]) == (form0, stage0)),
                        key=lambda kv: (kv[0][1], -len(kv[1])))
        for (form, k, stage), lst in chosen[:P["LFSR_MODES_CLAIMED"]]:
            taps = {cl["taps"] for _r, cl in lst}
            if len(taps) > 1:
                prog_lanes = True
            rep = None
            # a class's lanes share (form, k, chain) but not the taps: a lane whose own matrix the
            # harness's gates refuse (a tap setting that leaves a stage constant) goes last, so a
            # programmable word is reported at a setting that is a whole LFSR. Stable: lanes keep
            # their scan order within each group, and the key is the matrix, never an id.
            order = sorted(lst, key=lambda rc: not _matrix_gate(list(J_of[rc[0]]), W.w)) \
                if P["LFSR_OWN_GATE"] else lst
            for r, cl in order[:P["LFSR_CLASS_LANES"]]:
                pr, da = self.sources(W, r)
                mdl = self.fit(W, r, pr, da)
                if mdl is None or tuple(mdl["A"]) != J_of[r]:
                    continue
                rep = (r, cl, mdl)
                break
            if rep is None:
                continue
            r, cl, mdl = rep
            ks, n_in, root = self.steps(W, cl, mdl)
            if root[0] != cl["k"] or list(root[1]) != list(cl["stage"]):
                cl = dict(cl, k=root[0], stage=list(root[1]), taps=root[2], poly=_poly_of(root[2], W.w),
                          both=False, other_stage=None)          # an alternative root fits the data
            modes.append({"k": ks, "n_in": n_in, "taps": cl["taps"], "poly": cl["poly"], "lane": r, "model": mdl,
                          "cls": cl, "lanes": len(lst), "data": len(mdl["data"]), "tap_settings": len(taps),
                          "both": bool(cl["both"])})
        if not modes:
            W.info["verdict"] = "no LFSR mode could be modelled"
            return None
        # tap coefficients: parameters whose flip keeps the chain and k but moves the taps
        coef = self.coefficients(W, modes[0])
        coef_flops = [s for s in coef if self.ctl.g.kind[s] == FLOP]
        W.info["tap_coefficients"] = len(coef)
        # a register holding the taps is the truth's "programmable" polynomial; taps selected by
        # signals that are not flops (a mode pin) are a constant per setting, so the probed all-zero
        # setting becomes the defining mode and its polynomial is reported (see pin_mode)
        pin_selected = bool(coef) and not coef_flops and bool(P["LFSR_PIN_POLY"])
        if pin_selected:
            pm = self.pin_mode(W, modes[0], coef)
            if pm is None:
                pin_selected = False
            else:
                modes.insert(0, pm)
        programmable = (prog_lanes or bool(coef)) and not pin_selected
        W.info["tap_coefficient_flops"] = len(coef_flops)
        W.info["pin_selected_taps"] = pin_selected
        if not self.claim_modes(W, modes):
            W.info["verdict"] = "no mode claim verified"
            return None
        if pin_selected and modes[0].get("claims") is None:
            pin_selected, programmable = False, prog_lanes or bool(coef)   # the probed setting did not prove
            W.info["pin_selected_taps"] = "the all-zero probed setting did not prove"
        probe_info = None
        if coef and P["LFSR_PROBE"] and (programmable or pin_selected):
            base_md = next((md for md in modes if md.get("claims") is not None), None)
            if base_md is not None:
                probe_info = self.probe(W, base_md, coef)
        form = "both" if all(md["both"] for md in modes if md.get("claims") is not None) else form0
        st = self.structure(W, modes, form, programmable, coef, probe_info, pin_selected)
        if st is None:
            W.info["verdict"] = "the own-bit matrix has a zero row, a dead column or one bit per row"
        return st

    def claim_modes(self, W, modes):
        """Claims for every mode (the first proven one generalises its condition; the others try
        dropping the same literals); returns the number of proven modes."""
        dropped = None
        n = 0
        for md in modes:
            if dropped is None:
                cl, info = self.mode_claims(W, md["model"])
            else:
                cl, info = self.mode_claims(W, md["model"], generalise=False, drop_first=dropped)
            md["claim"] = info if cl is None else {k: v for k, v in info.items() if k not in ("lits", "dropped")}
            if cl is None:
                continue
            if dropped is None:
                dropped = info["dropped"]
            n += 1
            md["claims"] = cl
            md["cond_lits"] = info["lits"]
            md["dropped"] = info["dropped"]
        return n

    def _affine_word(self, W, affine):
        """Form "affine": strongly connected GF(2)-affine matrices that are not companion powers,
        one mode per distinct matrix (most lanes first); None when none qualifies."""
        P = self.P
        if W.w < P["LFSR_AFFINE_MIN_WIDTH"]:
            W.info["affine"] = "narrower than LFSR_AFFINE_MIN_WIDTH"
            return None
        items = sorted(affine.items(), key=lambda kv: (-len(kv[1]), kv[1][0][0]))
        modes = []
        for J, lst in items[:P["LFSR_MODES_CLAIMED"]]:
            if not _strongly_connected(list(J), W.w):
                continue
            for r, _cl in lst[:P["LFSR_CLASS_LANES"]]:
                pr, da = self.sources(W, r)
                mdl = self.fit(W, r, pr, da)
                if mdl is None or tuple(mdl["A"]) != J:
                    continue
                modes.append({"k": None, "n_in": len(mdl["data"]), "taps": None, "poly": None, "lane": r,
                              "model": mdl, "cls": {"kind": "affine"}, "lanes": len(lst), "data": len(mdl["data"]),
                              "tap_settings": 1, "both": False})
                break
        if not modes:
            W.info["affine"] = "no strongly connected affine mode could be modelled"
            return None
        if not self.claim_modes(W, modes):
            W.info["verdict"] = "no affine mode claim verified"
            return None
        W.info["verdict"] = "affine"
        st = self.structure(W, modes, "affine", False, [], None)
        if st is None:
            W.info["verdict"] = "affine, but the own-bit matrix has a zero row or a dead column"
        return st

    def _split(self, W, scan):
        """Strongly connected parts (>= LFSR_MIN_WIDTH flops, smaller than the word) of the union of
        the lanes' dependency graphs (row i reads column j): an LFSR's companion graph is strongly
        connected, flops that only read it (a counter of its output) are not in its part."""
        w = W.w
        succ = [set() for _ in range(w)]
        for _r, J, _bad in scan:
            for j, c in enumerate(J):
                while c:
                    low = c & -c
                    i = low.bit_length() - 1
                    if i != j:
                        succ[j].add(i)
                    c ^= low
        comps = _controls._tarjan(w, [sorted(x) for x in succ])
        return [[W.word[k] for k in comp] for comp in comps
                if self.P["LFSR_MIN_WIDTH"] <= len(comp) < w]

    def coefficients(self, W, md):
        """Parameters whose flip at the mode lane keeps the class (form, k, chain) but changes the
        taps."""
        c = W.cone
        r = md["lane"]
        cl = md["cls"]
        prm = [s for s in md["model"]["params"] if s in c.lidx]
        if not prm:
            return []
        w = W.w
        per = 1 + w
        base = c.lane(r)
        X = np.repeat(base[:, None], per * len(prm), axis=1)
        for t, s in enumerate(prm):
            X[c.lidx[s], per * t: per * (t + 1)] ^= 1
            X[c.sidx, per * t + 1 + np.arange(w)] ^= 1
        F = c.run(X)
        out = []
        known = [(cl["form"], cl["k"], tuple(cl["stage"]), cl["both"])]
        for t, s in enumerate(prm):
            B = F[:, per * t: per * (t + 1)]
            J = _col_ints(B[:, 1:] ^ B[:, :1])
            k2 = _classify(J, w, self.P["LFSR_ROOT_MAX"], self.P["LFSR_K_MAX"], known)
            if k2["kind"] == "lfsr" and k2["form"] == cl["form"] and k2["k"] == cl["k"] and \
                    k2["stage"] == cl["stage"] and k2["taps"] != cl["taps"]:
                out.append(s)
        return out

    def pin_mode(self, W, md, coef):
        """The mode at the probed setting "every tap-selecting signal 0" (other parameters as at
        `md`'s lane), as a mode dict, or None when it is not an LFSR mode of the same reading.

        Used when no tap coefficient is a flop: the taps are then chosen by signals outside the
        design's state (a mode pin), so each setting is a CRC/LFSR with a constant polynomial
        rather than a register-held, "programmable" one. Which setting to report is a convention,
        as it is for form "both": this module reports the all-zero probed setting, because it is
        the one setting the netlist names without reference to a lane the sweep happened to hit
        (the defining mode's own lane carries whatever the pool drew), and lists the rest in
        proof["lfsr"]["pin_modes"]."""
        r, mdl0 = md["lane"], md["model"]
        mdl = self.model(W, r, mdl0["data"], mdl0["params"], zero_extra=dict.fromkeys(coef, 0))
        if not mdl["ok"]:
            return None
        mdl["data"], mdl["params"] = list(mdl0["data"]), list(mdl0["params"])
        mdl["A"] = _col_ints(mdl["M"][:, :W.w])
        mdl["B"] = _col_ints(mdl["M"][:, W.w:])
        cl0 = md["cls"]
        cl = _classify(mdl["A"], W.w, self.P["LFSR_ROOT_MAX"], self.P["LFSR_K_MAX"],
                       [(cl0["form"], cl0["k"], tuple(cl0["stage"]), cl0["both"])])
        if cl["kind"] != "lfsr" or cl["form"] != cl0["form"] or cl["stage"] != cl0["stage"]:
            return None
        if self.P["LFSR_OWN_GATE"] and not _matrix_gate(mdl["A"], W.w):
            return None          # this setting leaves a stage constant: not a whole LFSR to report
        ks, n_in, root = self.steps(W, cl, mdl)
        if root[0] != cl["k"] or list(root[1]) != list(cl["stage"]):
            cl = dict(cl, k=root[0], stage=list(root[1]), taps=root[2], poly=_poly_of(root[2], W.w),
                      both=False, other_stage=None)
        return {"k": ks, "n_in": n_in, "taps": cl["taps"], "poly": cl["poly"], "lane": r, "model": mdl,
                "cls": cl, "lanes": 0, "data": len(mdl["data"]), "tap_settings": 1,
                "both": bool(cl["both"]), "pin_zero": True}

    def probe(self, W, md, coef):
        """Programmable taps probed at p = 0 and at each one-hot p (other parameters as at the
        mode lane): taps per setting and proven claims for each setting whose model is affine."""
        r = md["lane"]
        mdl0 = md["model"]
        settings = [dict.fromkeys(coef, 0)] + [{s: int(s == x) for s in coef} for x in coef]
        claims = []
        taps = []
        per_setting = []
        ok_n = 0
        known = [(md["cls"]["form"], md["cls"]["k"], tuple(md["cls"]["stage"]), md["cls"]["both"])]
        for n, st in enumerate(settings):
            mdl = self.model(W, r, mdl0["data"], mdl0["params"], zero_extra=st)
            if not mdl["ok"]:
                taps.append(None)
                per_setting.append({"setting": n, "taps": None, "poly": None, "claimed": False})
                continue
            mdl["data"], mdl["params"] = mdl0["data"], mdl0["params"]
            A = _col_ints(mdl["M"][:, :W.w])
            cl = _classify(A, W.w, self.P["LFSR_ROOT_MAX"], self.P["LFSR_K_MAX"], known)
            t = cl.get("taps") if cl["kind"] == "lfsr" else None
            taps.append(t)
            cc, info = self.mode_claims(W, mdl, generalise=False, drop_first=md.get("dropped"))
            if cc is not None:
                claims.append({"when": info["when"], "inputs": info["inputs"], "input_rank": info["input_rank"],
                               "claims": _case_claims(cc)})
                ok_n += 1
            # setting 0 is "every tap-selecting signal 0"; setting n > 0 raises the n-th alone
            per_setting.append({"setting": n, "taps": t, "poly": _poly_of(t, W.w) if t else None,
                                "k": cl.get("k") if cl["kind"] == "lfsr" else None,
                                "claimed": cc is not None})
        return {"settings": len(settings), "claimed": ok_n, "zero_setting": taps[0] if taps else None,
                "per_setting": per_setting, "cases": claims}

    # ----------------------------------------------------------------------- output
    def structure(self, W, modes, form, programmable, coef, probe_info, pin_selected=False):
        ctl = self.ctl
        cells = [int(ctl.flops[i].cell) for i in W.word]
        claimed = [md for md in modes if md.get("claims") is not None]
        data_modes = [md for md in claimed if md["data"] > 0]
        main = data_modes or claimed
        # the defining mode (control.when): the first whose own-bit matrix passes the gates the
        # harness applies (no zero row, no dead column, not a partial permutation)
        lead = next((md for md in main if _own_gate(md["claims"], cells)["ok"]), None) \
            if self.P["LFSR_OWN_GATE"] else main[0]
        if lead is None:
            W.info["own_matrix"] = _own_gate(main[0]["claims"], cells)
            return None                                  # the harness refuses it: not an LFSR
        gate = _own_gate(lead["claims"], cells)
        pin_selected = bool(pin_selected and lead.get("pin_zero"))
        other = None
        if form == "affine":
            order, bit_order, k_steps, poly = None, None, None, None
        else:
            stage = lead["cls"]["stage"]
            by_stage = [None] * W.w
            for pos, st in enumerate(stage):
                by_stage[st] = cells[pos]
            order, bit_order = [by_stage], list(by_stage)
            other = None
            if form == "both" and lead["cls"].get("other_stage"):
                other = [None] * W.w
                for pos, st in enumerate(lead["cls"]["other_stage"]):
                    other[st] = cells[pos]
            ks = sorted({md["k"] for md in main})
            k_steps = ks[0] if len(ks) == 1 else None
            if programmable:
                poly = "programmable"
            elif pin_selected:
                poly = lead["poly"]      # the probed setting's constant; the others in proof["lfsr"]
            else:
                poly = lead["poly"] if len({md["poly"] for md in main}) == 1 else None
        per = set()
        for md in main:
            if md["n_in"] is not None:
                per.add(md["n_in"])
            elif md["k"]:
                v = md["data"] / md["k"]
                per.add(int(v) if float(v).is_integer() else None)
            else:
                per.add(None)
        n_in = per.pop() if len(per) == 1 else None
        rclaims, rst_lits, rst_vals = self.control_claims(W)
        if rst_lits and self._sat(W).satisfiable(list(lead["cond_lits"]) + [L ^ 1 for L in rst_lits]
                                                 + self._async_off(W)) is not True:
            rst_lits, rst_vals = None, None          # the harness's defining case is when & ~reset
        hold = self.hold_outside(W, lead["cond_lits"], rst_lits) if W.w else False
        rank = {}
        for md in claimed:
            rank.update(md["claim"]["input_rank"])
        for case in (probe_info or {}).get("cases", []):
            rank.update(case.pop("input_rank"))
        inputs = sorted(rank, key=lambda n: (rank[n], n))
        # schema v2.1 (2026-09-23): control.reset is a LIST of {"when": COND, "value": {flop: 0|1}}
        # cases. The v2.0 spelling this module used (a bare COND with control.reset_value beside it)
        # survives only behind verify.LEGACY_CONTROL_FORM, and reset_value beside a v2.1 case is
        # malformed. A reset whose stored value this module did not read names NO case, which widens
        # the region the harness checks the template on and so is never the laxer reading.
        reset_cases = None
        if rst_lits and rst_vals:
            reset_cases = [{"when": ctl.cond(rst_lits), "value": {str(k): v for k, v in rst_vals.items()}}]
        control = {"when": lead["claim"]["when"], "reset": reset_cases,
                   "load": None, "hold": bool(hold), "input": None, "inputs": inputs}
        # every claim below was proven here; a programmable polynomial is proven only at its
        # probed and witnessed settings (the design doc, section 3.5: matched, scope "probed")
        status = "unknown" if programmable else "proven"
        mode_info = [{"steps_per_clock": md["k"], "data_bits": md["data"], "inputs_per_step": md["n_in"],
                      "lanes": md["lanes"], "tap_settings": md["tap_settings"],
                      "one_step_poly": md["poly"] if not programmable else None,
                      "defining": md is lead, "claimed": md.get("claims") is not None,
                      "pin_zero_setting": bool(md.get("pin_zero")),
                      "condition_literals": (md.get("claim") or {}).get("cond"),
                      "frontier_literals": (md.get("claim") or {}).get("cond_frontier"),
                      "compressed_literals": (md.get("claim") or {}).get("cond_compressed"),
                      **({"when": md["claim"]["when"], "inputs": md["claim"]["inputs"],
                          "claims": _case_claims(md["claims"])}
                         if md.get("claims") is not None and md is not lead else {})}
                     for md in modes]
        # proof.claims: the defining mode's per-flop claims only (schema v2: each claim's own
        # "when" equals control.when); hold and reset are control.hold / control.reset, and the
        # per-flop cover claims behind them are counted in proof["lfsr"]
        claims = list(lead["claims"])
        s = {"kind": KIND, "flops": list(cells), "order": order,     # W.word's structural order, not ids
             "params": {"form": form, "poly": poly, "k_steps": k_steps, "n_inputs": n_in, "bit_order": bit_order},
             "control": control,
             "proof": {"status": status, "scope": "probed" if programmable else "modes",
                       "claims_by_role": dict(sorted(collections.Counter(c["role"] for c in claims).items())),
                       "claims": claims,
                       "modes": mode_info,
                       "lfsr": {"programmable_taps": bool(programmable),
                                # taps chosen by signals that are not flops (a mode pin): params.poly
                                # is the probed all-zero setting's constant, proven under control.when;
                                # pin_modes lists the other probed settings' polynomials
                                "pin_selected_taps": bool(pin_selected),
                                "pin_modes": ([p for p in (probe_info or {}).get("per_setting", [])
                                               if p["setting"]] if pin_selected else None),
                                "own_matrix": gate,
                                "cover_claims_proven": dict(sorted(collections.Counter(c["role"] for c in rclaims).items())),
                                "tap_coefficient_flops": [int(ctl.flops[ctl.g.q2flop[s]].cell)
                                                          for s in sorted(coef) if ctl.g.kind[s] == FLOP],
                                "lane_kinds": W.info.get("lane_kinds"),
                                # form "both": the other reading's stage order (the two readings of
                                # one graph differ by a rotation of the stages)
                                "other_reading_order": other}}}
        if probe_info:
            s["proof"]["probe"] = probe_info
        return s

    # ----------------------------------------------------------------------- run
    def run(self):
        t0 = time.perf_counter()
        cands = self.candidates()
        self.timings["candidates"] = time.perf_counter() - t0
        found = []
        for ws in cands:
            t1 = time.perf_counter()
            found += self.analyse(ws)
            self.stats["words_analysed"] += 1
            self.timings["analyse"] = self.timings.get("analyse", 0.0) + time.perf_counter() - t1
        # disjoint: larger first, then in the order found (candidates are in a structural label
        # order; never by id)
        used = set()
        out = []
        for s in sorted(found, key=lambda s: -len(s["flops"])):
            if used & set(s["flops"]):
                self.stats["overlapping_dropped"] += 1
                continue
            used |= set(s["flops"])
            out.append(s)
        for n, s in enumerate(out):
            s["id"] = f"lfsr{n}"
        self.structures = out
        self.timings["total"] = time.perf_counter() - t0
        return out

    def meta(self):
        return {"lfsr_candidates": self.stats.get("candidates_binate", 0),
                "lfsr_blocks": self.stats.get("candidates_blocks", 0),
                "lfsr_wide_candidates": self.stats.get("candidates_wide", 0),
                "lfsr_wide_admitted": self.stats.get("candidates_wide_admitted", 0),
                "lfsr_words": [dict(w) for w in self.words],
                "lfsr_structures": len(self.structures),
                "lfsr_sat_calls": self.sat_calls,
                "lfsr_parity_proven": int(self.stats.get("parity_proven", 0)),
                "lfsr_parity_open": int(self.stats.get("parity_open", 0))}


def _case_claims(claims):
    """A case's claims without their repeated condition (the case holds its "when" once)."""
    return [{"type": "next", "flop": c["flop"], "equals": c["equals"]} for c in claims]


def find(ctl, params=None):
    """LFSR/CRC structures of an analysed control layer: {"structures": [...], "meta": {...}}."""
    lf = LFSR(ctl, params)
    structs = lf.run()
    return {"structures": structs, "meta": lf.meta(), "timings": dict(lf.timings)}


def recognize(nl, params=None):
    """The control layer, then find(): a whole result with LFSR/CRC structures only."""
    ctl = _controls.analyze(nl, dict(params or {}))
    out = find(ctl, params)
    return {"schema": RESULT_SCHEMA, "structures": out["structures"], "groups": [s["flops"] for s in out["structures"]],
            "meta": {"recognizer": "lfsr", **out["meta"]}}
