"""S3 word grouping: a partition of every flop of an anonymous netlist into words (the S3 design
doc, section 3.6: DANA's dataflow refinement after grouping by shared controls), with result-schema
structures and next-state proof claims for the words it forms.

    out = group(ctl, fixed=(), params=None)      # ctl: tools.s3.controls.analyze(nl)
    res = recognize(nl, params=None, fixed=())   # a whole result dict (control layer + grouping)

`fixed` holds the structures other recognizers found (result-schema dicts with "flops", or plain
lists of flop ids): they are locked words, never split or merged, and only serve as blocks for the
dataflow signatures. `out` is {"structures": words formed here (never the fixed ones), "groups":
the partition of EVERY flop (fixed words, formed words, singletons), "singletons": flop ids left
alone, "meta": counts}; timings are in run_info(out) only (results must be reproducible).

Stages (flop i: f_i its next-state literal, q_i its state; rho the reset literal)
  1. Fixed words: the given structures, first come first served (a flop joins one word only).
  2. P0, an exact signature without thresholds: clock root and edge, the asynchronous control
     classes (clear or preset, either polarity), and the SET of shared cover classes: literals of
     the flop's hold/set cover (controls.Profile.steps) whose control class holds or sets at least
     CONTROL_MIN_FLOPS distinct flops, minus 'peeling' classes (a class whose flop set is another
     used class's minus one flop: a counter's nested carries). The design names only the dominant
     class; on the dev set the dominant is a broad class (a clear shared by 16 words) and whole
     covers carry single-flop classes (a literal implying q_i = v both holds and sets flop i, so
     ControlClass.n counts it twice), so the shared-class set is used (dev set, P0 alone: AMI 0.64
     dominant, 0.82 whole cover, 0.88 shared set). With P0_MAXIMAL_CLASSES a class that holds
     exactly one block of that key and lies strictly inside another class of the same cover which
     holds exactly the flops whose key uses it (a word's own control) is dropped as well (_inner):
     a later greedy cover step explains the hold lanes the earlier steps left over, so its class
     carves a slice of bits out of a word instead of telling two words apart (synthetic corpus,
     accumulators and an LCG: mean AMI 0.8361 -> 0.8628, 9 of 338 runs better, none worse; the
     dev set's partition is unchanged).
  2b. P0 joined along hold conditions: flops whose exact hold conditions T_i (stage 3) are SAT-equal
     under ~rho, with a live lane where T holds, and whose clock and asynchronous controls agree
     go to the P0 block that holds most of them (the greedy cover reaches one hold condition through
     different classes on different bits of a word: an OR of many write strobes, a hold mux the
     synthesis moved deeper; dev set: 6 registers of 10-32 bits split at P0 by that alone). Classes
     of at least CONTROL_MIN_FLOPS flops; a class only gathers its own flops, it never merges two
     blocks (dev set AMI 0.9675 -> 0.9806; synthetic corpus 3 of 338 runs better, none worse).
  3. Hold classes ("same function across bits"): T_i = f_i|q_i=1 & ~f_i|q_i=0, the exact condition
     under which flop i keeps its state. Within a P0 block, flops whose T are equal under ~rho
     (ctl.equal(bdd=True): SAT, and BDDs for a check SAT leaves open after SAT_STAGE1 conflicts,
     which decide the XOR-dense hold conditions of CRC words; a grouping fact, never a claim)
     (bucketed by live-lane signature, confirmed against the bucket's representatives, at most
     CLASS_FAIL_CAP refutations per flop) share their update events; classes of at least
     CONTROL_MIN_FLOPS flops become blocks, the other flops of the block stay together. A hold
     condition with bit-specific terms (a carry, a sticky bit, the one-hot leak of section 3.3)
     makes a singleton class and so never splits a word; T unsatisfiable under ~rho (no hold at
     all) is no evidence either, and a class with data flowing both ways between it and the rest
     of its block (a counter whose carries give two bits one hold condition) is not carved.
  4. Dataflow refinement (DANA, one pass): pred(i) = the blocks holding the flops of i's data
     support (controls.data_flops: cover literals and rho excluded), succ(i) = the blocks of the
     flops whose data support holds i, both without i's own block. Inside each block, two flops
     stay linked when their pred sets and their succ sets each overlap by at least WORD_JACCARD
     (Jaccard; two empty sets agree; with WORD_CONTAINED, default off, one set inside the other
     agrees too); the linked components are the new blocks, so a flop is isolated only when no
     other flop of its block shares enough of its neighbours. One pass against the stage-3
     blocks: iterating to a fixed point cascades (one split source word splits
     its readers by bit slice; dev set: AMI 0.969 one pass, 0.950 at the fixed point after four
     passes). Nothing merges across blocks. A block whose internal data edges are one bit-for-bit
     transfer is then split in two (the source word and its copy; section 3.3: depth 2 is a
     transfer between words, depth >= 3 a shift structure, which stays together). With
     DANA_SUCC_ROLES (default off) a successor counts with the structural role of the flop in the
     reader's next state (unate +, unate -, binate), which separates a mask word from the value word
     it gates (dev set: AMI 0.966 -> 0.969; synthetic corpus, 228 runs: mean AMI 0.607 -> 0.601, so off).
  5. Duplicates (controls.duplicates: SAT-equal f, same clock and asynchronous controls) join
     their original's word.
  6. Order (labelled, unproven): a word whose flop set is a nested-support chain (controls.chains)
     or a chain prefix takes that order; the fixed structures' lanes are ordered; then, to a fixed
     point, a word that copies bit for bit from an ordered word (a copy template, or a copy edge
     with any condition, one source per flop, a bijection) inherits its order, and the other way
     round.
  7. Claims, per flop of each formed word (schema.py's claim language, over opaque ids; every
     COND literal is carried by a net, a class member standing in for a representative without
     one; members are SAT-equal under ~rho, which every COND but the reset's states. A
     synchronous rho without a net cannot be stated: then nothing is substituted, rho is left out
     and every claim is SAT-checked here without the assumption, refuted ones dropped):
       reset     (synchronous reset with a forced value) rho = 1 -> f_i = v. The ternary forcing
                 pass that found rho proves it (every other signal X).
       hold      for each SAT-proven hold step k of the cover: rho = 0, earlier steps 0, step k
                 1 -> f_i = q_i; a proven set step gives const v, role "reset" (a synchronous
                 clear or preset).
       defining  rho = 0 and every cover step 0 -> the SAT-proven template (const, copy,
                 copy_inv, toggle, affine, hold); otherwise the OPAQUE load f_i itself (the
                 netlist's own next state expanded down to nets: true by construction, counted
                 in proof.opaque_defining and flagged by the harness as an internal-net claim).
     Every COND is non-vacuous by a live lane (a concrete assignment). The structure's status is
     "proven" only when every flop has a non-opaque defining claim and every claim comes from a
     SAT-proven relation (or the reset forcing); otherwise "unknown". The harness verifies the
     claims itself (verify.py); the status is only this module's claim.

Every order here is (structural label, flop index); the flop index is the flop's canonical
position (netlist.canonical_order), never its cell id, so the partition, the words' order and the
claims are the same for the same netlist under any id permutation.

Word kinds (unscored): one flop -> flag; control-grouped words of equal width with equal source
sets (written from the same data, each under its own control) -> register_file_word; the rest
data_register.
"""
from __future__ import annotations

import collections
import hashlib
import time

from tools.s3 import controls as _controls
from tools.s3 import params as _params
from tools.s3.netlist import FLOP

RESULT_SCHEMA = "retrace-s3-result/1"

# This module's thresholds (WORD_JACCARD, DANA_SUCC_ROLES, P0_MAXIMAL_CLASSES, WORD_CONTAINED) are
# tools.s3.params entries with their justification (moved there on 2026-09-22), read as self.P like
# every other parameter.


def resolve(params=None):
    """tools.s3.params with `params` applied (an unknown name is an error)."""
    return _params.resolve(dict(params or {}))


def _jac(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _compatible(a, b, theta, contained):
    """Do two neighbour sets agree enough to keep their flops in one word? Jaccard >= theta, or
    (WORD_CONTAINED) one set inside the other: a bit that reads or feeds everything another bit of
    the same word does, and more, is evidence of an extra reader, not of a second word. The empty
    set is inside every set, so a flop without data predecessors is never split off on predecessor
    evidence (Jaccard against an empty set is 0, which reads as maximal disagreement)."""
    if contained and (a <= b or b <= a):
        return True
    return _jac(a, b) >= theta


class Grouper:
    def __init__(self, ctl, fixed=(), params=None):
        self.ctl = ctl
        self.P = resolve(dict(params or {}))
        self.stats = collections.Counter()
        self.timings = collections.OrderedDict()
        self.idx = {int(f.cell): i for i, f in enumerate(ctl.flops)}
        self.F = ctl.F
        self.lab = [ctl.labels[f.q] for f in ctl.flops]
        self.fixed_in = list(fixed or ())

    # ------------------------------------------------------------------ helpers
    def _okey(self, i):
        """Deterministic flop order: structural label first, then the flop index, which is the
        canonical (id-free) position of the flop in the GateGraph (netlist.canonical_order), never
        the flop's cell id."""
        return (self.lab[i], i)

    def _bkey(self, b):
        return min(self._okey(i) for i in b)

    def _class_flops(self, L):
        c = self.ctl.control.get(L)
        return len(set(c.holds) | set(c.sets)) if c is not None else 0

    # ------------------------------------------------------------------ 1. fixed words
    def fix(self):
        self.fixed = []            # [(flop indices, source structure or None)]
        self.owner = {}            # flop index -> fixed word number
        for s in self.fixed_in:
            ids = s.get("flops", []) if isinstance(s, dict) else list(s)
            mem = []
            for x in ids:
                try:
                    i = self.idx.get(int(x))
                except (TypeError, ValueError):
                    i = None
                if i is None or i in self.owner:
                    self.stats["fixed_flops_ignored"] += 1
                    continue
                mem.append(i)
            if not mem:
                continue
            k = len(self.fixed)
            for i in mem:
                self.owner[i] = k
            self.fixed.append((sorted(mem, key=self._okey), s if isinstance(s, dict) else None))
        self.free = [i for i in range(self.F) if i not in self.owner]
        self.pred = [set(d) - {i} for i, d in enumerate(self.ctl.data_flops)]
        self.succ = [set() for _ in range(self.F)]
        for i in range(self.F):
            for j in self.pred[i]:
                self.succ[j].add(i)
        self.role = {}             # (reader r, flop j) -> structural role of q_j in f_r: "+", "-", "b"
        if self.P["DANA_SUCC_ROLES"]:
            g = self.ctl.g
            pos, neg = g.unate_supports()
            idx = g._source_index()
            for r in range(self.F):
                for j in self.pred[r]:
                    b = 1 << idx[self.ctl.flops[j].q]
                    p, n = bool(pos[r] & b), bool(neg[r] & b)
                    self.role[(r, j)] = "b" if p and n else ("+" if p else "-")
        self.stats["fixed_words"] = len(self.fixed)
        self.stats["fixed_flops"] = len(self.owner)

    # ------------------------------------------------------------------ 2. P0
    def _peeling(self, used):
        """Cover classes that add a single flop to a nested chain: L whose flop set is another used
        class's set minus exactly one flop (a counter's carries hold bits k.., k+1.., ...). Such a
        class separates one bit, not a word, so the P0 key ignores it."""
        sets = {L: frozenset(set(self.ctl.control[L].holds) | set(self.ctl.control[L].sets)) for L in used}
        has = collections.defaultdict(set)          # flop -> used classes holding it
        for L, S in sets.items():
            for i in S:
                has[i].add(L)
        out = set()
        for L, S in sets.items():
            x = next(iter(S))                       # any superset of S holds x, so has[x] is complete
            for L2 in has[x]:
                S2 = sets[L2]
                if len(S2) == len(S) + 1 and S < S2:
                    out.add(L)
                    break
        return out

    def _inner(self, full, sets):
        """Cover classes that slice the bits of a word instead of telling two words apart.

        L qualifies when (a) L holds and sets exactly the flops of one block of the full key, so L
        tells that block from its neighbours only because they do not carry it (and dropping L can
        therefore not disturb any other block: every flop L controls is in this one); and (b) some
        other class M of the same cover strictly contains L and holds exactly the flops whose key
        uses M, that is M is a word's own control and L a condition inside that word. A later
        greedy cover step explains the hold lanes the earlier steps left over, so its class holds a
        subset of the broader step's flops: an accumulator bit that also keeps its value when its
        own addend bit and carry are 0. A class that controls flops past the word M covers -- a
        per-slot write strobe under a module-wide enable -- is what holds two words apart and
        stays, whatever its size.

        `full` maps each full P0 key to its flops (the free ones: a class that also controls a flop
        of a fixed structure is not that word's own control either, and keeps its key)."""
        out = set()
        usedby = collections.defaultdict(set)
        for (_c, cov), mem in full.items():
            for L in cov:
                usedby[L] |= set(mem)
        for key, mem in full.items():
            ctlk, cov = key
            if len(cov) < 2:
                continue
            block = frozenset(mem)
            inner = [L for L in cov if sets[L] == block and any(sets[L] < sets[M] for M in cov if M != L)]
            if not inner:
                continue
            rest = tuple(x for x in cov if x not in inner)
            if any(sets[M] == usedby[M] and all(sets[L] < sets[M] for L in inner) for M in rest):
                out |= set(inner)
        return out

    def p0(self):
        ctl, P = self.ctl, self.P
        by = collections.defaultdict(list)
        self.shared = {}
        used = {L for i in self.free for L, _k in ctl.profile[i].steps
                if self._class_flops(L) >= P["CONTROL_MIN_FLOPS"]}
        peel = self._peeling(used)
        self.stats["p0_classes_shared"] = len(used)
        self.stats["p0_classes_peeling"] = len(peel)
        base = {}
        for i in self.free:
            fl, pr = ctl.flops[i], ctl.profile[i]
            asy = tuple(sorted({ctl.rep(x) for x in (fl.clear, fl.preset) if x}))
            cov = tuple(sorted({L for L, _k in pr.steps if L in used and L not in peel}))
            base[i] = ((fl.clk_root, fl.clk_inv, asy), cov)
        dropped = set()
        if P["P0_MAXIMAL_CLASSES"]:
            full = collections.defaultdict(list)
            for i in self.free:
                full[base[i]].append(i)
            sets = {L: frozenset(set(ctl.control[L].holds) | set(ctl.control[L].sets)) for L in used}
            dropped = self._inner(full, sets)
        for i in self.free:
            ctlk, cov = base[i]
            if dropped:
                cov = tuple(L for L in cov if L not in dropped)
            self.shared[i] = cov
            by[ctlk + (cov,)].append(i)
        self.blocks = [sorted(v, key=self._okey) for v in by.values()]
        self.stats["p0_classes_contained"] = len(dropped)
        self.stats["p0_blocks"] = len(self.blocks)
        self.basis = {}            # flop -> "control" when a shared class or hold class grouped it
        for b in self.blocks:
            if self.shared[b[0]]:
                for i in b:
                    self.basis[i] = "control"

    # ------------------------------------------------------------------ 2b. P0 joined along hold conditions
    def _hold_sigs(self, flops):
        """hold_lit (T_i) for the flops, and a live-lane signature per non-trivial T literal."""
        ctl = self.ctl
        for i in flops:
            if i not in self.hold_lit:
                self.hold_lit[i] = ctl.transparency(i, ctl.flops[i].q)[0]
        lits = sorted({self.hold_lit[i] for i in flops if self.hold_lit[i] > 1} - set(self.hold_sig))
        for c0 in range(0, len(lits), 512):
            rows = ctl._rows(lits[c0:c0 + 512])
            for L, r in rows.items():
                r = r & ctl.live
                self.hold_sig[L] = (hashlib.blake2b(r.tobytes(), digest_size=16).digest(), bool(r.any()))

    def p0_holds(self):
        """Flops whose exact hold conditions T_i are SAT-equal under ~rho (the same update events)
        and whose clock and asynchronous controls agree go to the P0 block that holds most of them
        (ties: structural order). The P0 key is the set of shared cover classes, and the greedy cover
        (COVER_CAP literals, candidates from a bounded cone) reaches one hold condition through
        different classes on different bits when the condition is an OR of many write strobes or
        the synthesis moved a bit's hold mux deeper: bits of one word then fall into different P0
        blocks although their controls are identical. Only classes with a live lane where T holds
        count (a satisfiable, observed hold), of at least CONTROL_MIN_FLOPS flops; a class splits
        nothing and merges no block with another, it only gathers its own flops."""
        ctl, P = self.ctl, self.P
        self.hold_lit, self.hold_sig = {}, {}
        where = {}
        for k, b in enumerate(self.blocks):
            for i in b:
                where[i] = k
        flops = sorted(where, key=self._okey)
        self._hold_sigs(flops)
        buckets = collections.defaultdict(list)
        for i in flops:
            L = self.hold_lit[i]
            if L <= 1 or not self.hold_sig[L][1]:
                continue
            fl = ctl.flops[i]
            asy = tuple(sorted({ctl.rep(x) for x in (fl.clear, fl.preset) if x}))
            buckets[(fl.clk_root, fl.clk_inv, asy, self.hold_sig[L][0])].append(i)
        moved = 0
        for key in sorted(buckets, key=lambda k: self._okey(buckets[k][0])):
            mem = buckets[key]
            if len(mem) < P["CONTROL_MIN_FLOPS"] or len({where[i] for i in mem}) < 2:
                continue
            reps = []
            for i in mem:
                L = self.hold_lit[i]
                fails = 0
                for r in reps:
                    if r[0] == L or ctl.equal(r[0], L, bdd=True):     # a grouping fact, never a claim
                        r[1].append(i)
                        break
                    fails += 1
                    if fails >= P["CLASS_FAIL_CAP"]:
                        reps.append((L, [i]))
                        break
                else:
                    reps.append((L, [i]))
            for _L, m in reps:
                if len(m) < P["CONTROL_MIN_FLOPS"]:
                    continue
                cnt = collections.Counter(where[i] for i in m)
                if len(cnt) < 2:
                    continue
                tgt = min(cnt, key=lambda k: (-cnt[k], self._bkey(self.blocks[k])))
                for i in m:
                    if where[i] != tgt:
                        self.blocks[where[i]].remove(i)
                        self.blocks[tgt].append(i)
                        where[i] = tgt
                        self.basis[i] = "control"
                        moved += 1
        self.blocks = sorted((sorted(b, key=self._okey) for b in self.blocks if b), key=self._bkey)
        self.stats["p0_hold_moved"] = moved
        self.stats["p0_blocks_after_holds"] = len(self.blocks)

    # ------------------------------------------------------------------ 3. hold classes
    def _coupled(self, m, b):
        """Data flows both ways between the class m and the rest of its block b (the class reads
        a flop of the rest and the rest reads a flop of the class): one arithmetic word (a
        counter's carries give some bits a common hold condition), not two words."""
        ms = set(m)
        rest = set(b) - ms
        out = any(j in rest for i in m for j in self.pred[i])
        back = any(j in ms for i in rest for j in self.pred[i])
        return out and back

    def hold_classes(self):
        ctl, P = self.ctl, self.P
        if not hasattr(self, "hold_lit"):
            self.hold_lit, self.hold_sig = {}, {}
        self._hold_sigs(list(self.free))
        sig = self.hold_sig
        self.hold_class = {}       # flop -> class id (flops of one class have SAT-equal T)
        nxt = 0
        out = []
        for b in self.blocks:
            if len(b) < 2:
                out.append(b)
                continue
            buckets = collections.defaultdict(list)
            for i in b:
                L = self.hold_lit[i]
                if L == 0:
                    self.stats["hold_never"] += 1
                    continue
                if L == 1:
                    self.stats["hold_always"] += 1
                    continue
                buckets[sig[L]].append(i)
            cls = []
            for key, mem in buckets.items():
                reps = []          # [(literal, [flops])]
                for i in mem:
                    L = self.hold_lit[i]
                    if not key[1]:     # no live lane: no evidence unless T is satisfiable
                        st, _a = ctl.witness(L)
                        self.stats["hold_witness_queries"] += 1
                        if st != "sat":
                            self.stats["hold_unsat_or_unknown"] += 1
                            continue
                    joined = False
                    fails = 0
                    for r in reps:
                        if r[0] == L:
                            r[1].append(i)
                            joined = True
                            break
                        ok = ctl.equal(r[0], L, bdd=True)    # a grouping fact, never a claim
                        self.stats["hold_equal_queries"] += 1
                        if ok:
                            r[1].append(i)
                            joined = True
                            break
                        if ok is None:
                            self.stats["hold_equal_unknown"] += 1
                        fails += 1
                        if fails >= P["CLASS_FAIL_CAP"]:
                            break
                    if not joined:
                        reps.append((L, [i]))
                cls += [m for _L, m in reps]
            carved = set()
            for m in sorted(cls, key=lambda m: min(self._okey(i) for i in m)):
                if len(m) >= P["CONTROL_MIN_FLOPS"] and self._coupled(m, b):
                    self.stats["hold_classes_coupled"] += 1
                elif len(m) >= P["CONTROL_MIN_FLOPS"]:
                    out.append(sorted(m, key=self._okey))
                    for i in m:
                        self.hold_class[i] = nxt
                        self.basis[i] = "control"
                        carved.add(i)
                    nxt += 1
            rest = [i for i in b if i not in carved]
            if rest:
                out.append(rest)
        self.stats["hold_classes"] = nxt
        self.stats["hold_blocks_after"] = len(out)
        self.blocks = out

    # ------------------------------------------------------------------ 4. DANA pass
    def dataflow(self):
        ctl, P = self.ctl, self.P
        theta = P["WORD_JACCARD"]
        blk = {}
        for k, (mem, _s) in enumerate(self.fixed):
            for i in mem:
                blk[i] = ("f", k)
        for k, b in enumerate(self.blocks):
            for i in b:
                blk[i] = ("b", k)
        pred, succ = self.pred, self.succ
        out = []
        for k, b in enumerate(self.blocks):
            if len(b) < 2:
                out.append(b)
                continue
            me = ("b", k)
            sigs = collections.defaultdict(list)
            role = self.role
            for i in b:
                ps = frozenset(blk[j] for j in pred[i] if blk[j] != me)
                if role:
                    ss = frozenset(blk[j] + (role[(j, i)],) for j in succ[i] if blk[j] != me)
                else:
                    ss = frozenset(blk[j] for j in succ[i] if blk[j] != me)
                sigs[(ps, ss)].append(i)
            keys = sorted(sigs, key=lambda s: min(self._okey(i) for i in sigs[s]))
            parent = list(range(len(keys)))

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            contained = P["WORD_CONTAINED"]
            for a in range(len(keys)):
                for c in range(a + 1, len(keys)):
                    if find(a) == find(c):
                        continue
                    if (_compatible(keys[a][0], keys[c][0], theta, contained)
                            and _compatible(keys[a][1], keys[c][1], theta, contained)):
                        parent[find(c)] = find(a)
            comp = collections.defaultdict(list)
            for a, s in enumerate(keys):
                comp[find(a)] += sigs[s]
            parts = sorted((sorted(v, key=self._okey) for v in comp.values()), key=lambda v: self._okey(v[0]))
            if len(parts) > 1:
                self.stats["dana_split_blocks"] += 1
            for part in parts:
                out += self._transfer_split(part)
        self.stats["dana_blocks_after"] = len(out)
        self.blocks = out

    def _transfer_split(self, b):
        """A block whose internal data edges are one bit-for-bit transfer (depth 2: every reader
        reads exactly one flop of the block, no flop of the block reads a reader, distinct readers
        read distinct flops) is two words, the source word and the copy (section 3.3: depth-2
        copies are transfers between words; depth >= 3 is a shift structure and stays together).
        Both words need CONTROL_MIN_FLOPS flops."""
        m = self.P["CONTROL_MIN_FLOPS"]
        if len(b) < 2 * m:
            return [b]
        inside = set(b)
        rd = {i: [j for j in self.pred[i] if j in inside] for i in b}
        readers = [i for i in b if rd[i]]
        if not readers:
            return [b]
        srcs = [rd[i][0] for i in readers if len(rd[i]) == 1]
        if len(srcs) != len(readers) or len(set(srcs)) != len(srcs) or set(srcs) & set(readers):
            return [b]
        second = sorted(readers, key=self._okey)
        first = sorted(inside - set(readers), key=self._okey)
        if len(first) < m or len(second) < m:
            return [b]
        self.stats["transfer_splits"] += 1
        return [first, second]

    # ------------------------------------------------------------------ 5. duplicates
    def duplicates(self):
        where = {}
        for k, b in enumerate(self.blocks):
            for i in b:
                where[i] = ("b", k)
        for k, (mem, _s) in enumerate(self.fixed):
            for i in mem:
                where[i] = ("f", k)
        self.extra_fixed = collections.defaultdict(list)    # fixed word -> duplicates joined to it
        moved = 0
        for dup in self.ctl.duplicates:
            base = dup[0]
            for i in dup[1:]:
                if where.get(i) == where.get(base) or i in self.owner:
                    continue
                src = where[i]
                self.blocks[src[1]].remove(i)
                tgt = where[base]
                if tgt[0] == "b":
                    self.blocks[tgt[1]].append(i)
                else:
                    self.extra_fixed[tgt[1]].append(i)
                where[i] = tgt
                moved += 1
        self.blocks = [sorted(b, key=self._okey) for b in self.blocks if b]
        self.blocks.sort(key=self._bkey)
        self.stats["duplicates_moved"] = moved

    # ------------------------------------------------------------------ 6. order
    def order(self):
        ctl = self.ctl
        self.order_of = {}          # block number -> (flop list, source)
        chains = [c for c in getattr(ctl, "chains", [])]
        for k, b in enumerate(self.blocks):
            if len(b) < 2:
                continue
            s = set(b)
            for c in chains:
                if len(c) >= len(b) and set(c[:len(b)]) == s:
                    self.order_of[k] = (list(c[:len(b)]), "chain")
                    break
        seqs = []                  # ordered sequences usable for propagation: (flops, block or None)
        for k, (mem, st) in enumerate(self.fixed):
            o = (st or {}).get("order") if st else None
            if o:
                for lane in o:
                    lane_i = [self.idx.get(int(x)) for x in lane if str(x).strip().lstrip("-").isdigit()]
                    lane_i = [i for i in lane_i if i is not None]
                    if len(lane_i) >= 2:
                        seqs.append(lane_i)
        # copy sources of each flop: template copy/copy_inv and copy edges (any condition)
        src = collections.defaultdict(set)
        for i, pr in enumerate(ctl.profile):
            if pr.template in ("copy", "copy_inv") and pr.arg in ctl.g.q2flop:
                src[i].add(ctl.g.q2flop[pr.arg])
        for e in ctl.copy_edges:
            if e.src in ctl.g.q2flop:
                src[e.dst].add(ctl.g.q2flop[e.src])
        for i in list(src):
            src[i].discard(i)
        self.copy_src = src

        def image(b, seq):
            """Positions in seq of b's unique copy sources, if a bijection onto part of seq."""
            pos = {j: p for p, j in enumerate(seq)}
            got = {}
            for i in b:
                ss = [pos[j] for j in src.get(i, ()) if j in pos]
                if len(ss) != 1:
                    return None
                got[i] = ss[0]
            if len(set(got.values())) != len(b):
                return None
            return got

        for _round in range(len(self.blocks) + 1):
            changed = False
            ordered = seqs + [o for o, _s in self.order_of.values()]
            for k, b in enumerate(self.blocks):
                if len(b) < 2 or k in self.order_of:
                    continue
                for seq in ordered:
                    got = image(b, seq)
                    if got is not None:
                        self.order_of[k] = (sorted(b, key=lambda i: got[i]), "propagated")
                        changed = True
                        break
                    # the other way round: b's flops are the unique copy sources of seq's flops
                    if len(seq) == len(b):
                        bs = set(b)
                        m = {}
                        for p, i in enumerate(seq):
                            ss = [j for j in src.get(i, ()) if j in bs]
                            if len(ss) != 1:
                                m = None
                                break
                            m[ss[0]] = p
                        if m is not None and len(m) == len(b):
                            self.order_of[k] = (sorted(b, key=lambda i: m[i]), "propagated")
                            changed = True
                            break
            if not changed:
                break
        self.stats["words_ordered_chain"] = sum(1 for _o, s in self.order_of.values() if s == "chain")
        self.stats["words_ordered_propagated"] = sum(1 for _o, s in self.order_of.values() if s == "propagated")

    # ------------------------------------------------------------------ 7. claims
    def _claims_setup(self):
        """The reset literal's nets. A class member may stand in for a literal only where the COND
        states rho = 0 itself (classes are SAT-equal under ~rho), so rho must be carried by a net;
        without one (or without a synchronous reset) nothing is substituted and, for a synchronous
        reset, every claim is SAT-checked here without the assumption."""
        ctl, R = self.ctl, self.ctl.reset
        self.sync = R.kind == "sync" and R.lit is not None
        self.rho1 = ctl.cond([R.lit]) if self.sync else None
        self.rho0 = ctl.cond([R.lit ^ 1]) if self.sync else None
        self.subst_ok = (not self.sync) or self.rho0 is not None
        self.check_all = self.sync and self.rho0 is None
        self.stats["reset_without_net"] = int(self.check_all)

    def _netlit(self, L):
        """A net-carried literal equal to L (L itself, or a member of its class when allowed)."""
        ctl = self.ctl
        if L in (0, 1) or ctl.cond([L]) is not None:
            return L
        if not self.subst_ok:
            return None
        R = ctl.rep(L)
        for m in ctl.members(R):          # m equals R's class literal; m ^ (R & 1) equals R, i.e. L
            c = m ^ (R & 1)
            if ctl.cond([c]) is not None:
                return c
        return None

    def _cond(self, lits):
        """COND for the conjunction of literals (each 1), or None if some has no net."""
        out = []
        for L in lits:
            if L == 1:
                continue
            n = self._netlit(L)
            if n is None:
                return None
            c = self.ctl.cond([n])
            if c is None:
                return None
            out += c
        return out

    def _check(self, lits, f, eq):
        """SAT, no assumption: the conjunction of lits implies f == eq (a literal or 0/1)."""
        ctl = self.ctl
        m = len(lits)
        const = eq in (0, 1)
        allv = lits + [f] + ([] if const else [eq])

        def ok(v):
            if not all(v >> b & 1 for b in range(m)):
                return True
            fv = v >> m & 1
            return fv == (eq if const else v >> (m + 1) & 1)

        tt = sum(1 << v for v in range(1 << len(allv)) if ok(v))
        self.stats["claim_checks"] += 1
        res, _c = ctl.sat.check(allv, tt, [], limit=self.P["SAT_LIMIT"])
        return res is True

    def _lanes(self, lits):
        """Live lanes where every literal is 1 (a concrete witness of non-vacuity)."""
        ctl = self.ctl
        acc = ctl.live.copy()
        for L in lits:
            if L == 1:
                continue
            if L == 0:
                return 0
            acc &= ctl.value(L)
        return _controls._pc(acc)

    def _src_expr(self, s, inv=0):
        ctl = self.ctl
        if ctl.g.kind[s] == FLOP:
            e = {"q": int(ctl.flops[ctl.g.q2flop[s]].cell)}
        else:
            e = ctl.expr(2 * s)
        if e is None:
            return None
        return {"not": e} if inv else e

    def _template_expr(self, i, pr):
        t, cell = pr.template, int(self.ctl.flops[i].cell)
        if t == "const":
            return {"const": int(pr.arg)}
        if t == "hold":
            return {"q": cell}
        if t == "toggle":
            return {"not": {"q": cell}}
        if t in ("copy", "copy_inv"):
            return self._src_expr(pr.arg, t == "copy_inv")
        if t == "affine":
            use, c = pr.arg
            terms = [self._src_expr(s) for s in use]
            if any(x is None for x in terms):
                return None
            if c:
                terms.append({"const": 1})
            if not terms:
                return {"const": 0}
            return terms[0] if len(terms) == 1 else {"xor": terms}
        return None

    def flop_claims(self, i):
        """(claims, info) for flop i; info: opaque (bool), proven (every claim from a proof)."""
        ctl = self.ctl
        pr = ctl.profile[i]
        cell = int(ctl.flops[i].cell)
        R = ctl.reset
        rho0 = [R.lit ^ 1] if self.sync and not self.check_all else []
        claims, proven, opaque = [], True, False
        if self.sync and self.rho1 is not None and pr.reset is not None:
            claims.append({"type": "next", "flop": cell, "equals": {"const": int(pr.reset)}, "when": self.rho1,
                           "role": "reset"})
        steps = [L for L, _k in pr.steps]
        for k, ((L, kind), ok) in enumerate(zip(pr.steps, pr.proven)):
            if not ok:
                continue
            lits = rho0 + [x ^ 1 for x in steps[:k]] + [L]
            c = self._cond(lits)
            if c is None or not self._lanes(lits):
                self.stats["hold_claims_dropped"] += 1
                continue
            tgt = self.ctl.qlit(i) if kind == "h" else int(kind)
            if self.check_all and not self._check(lits, ctl.f(i), tgt):
                self.stats["hold_claims_refuted"] += 1
                continue
            eq = {"q": cell} if kind == "h" else {"const": int(kind)}
            claims.append({"type": "next", "flop": cell, "equals": eq, "when": c,
                           "role": "hold" if kind == "h" else "reset"})
        lits = rho0 + [x ^ 1 for x in steps]
        c = self._cond(lits)
        eq = self._template_expr(i, pr) if pr.template_proven else None
        if eq is not None and self.check_all:
            t = ctl.template_lit(i, pr)
            if t is None or not self._check(lits, ctl.f(i), t):
                eq = None
        if c is not None and eq is not None and self._lanes(lits):
            claims.append({"type": "next", "flop": cell, "equals": eq, "when": c, "role": "defining"})
        else:
            opaque = True
            proven = False
            e = ctl.expr(ctl.f(i))
            if c is None or not self._lanes(lits):
                c = self._cond(rho0) or []
            if e is not None:
                claims.append({"type": "next", "flop": cell, "equals": e, "when": c, "role": "defining"})
            else:
                self.stats["no_defining_claim"] += 1
        return claims, {"opaque": opaque, "proven": proven}

    # ------------------------------------------------------------------ output
    def kinds(self):
        """Word kinds (unscored): flag for one flop; register_file_word for sibling words (equal
        width, equal source sets: the words of the other flops read and the inputs; written from
        the same data, each word under its own control); data_register otherwise."""
        blk = {}
        for k, b in enumerate(self.blocks):
            for i in b:
                blk[i] = ("b", k)
        for k, (mem, _s) in enumerate(self.fixed):
            for i in mem + self.extra_fixed.get(k, []):
                blk[i] = ("f", k)
        fam = collections.defaultdict(list)
        for k, b in enumerate(self.blocks):
            if len(b) < 2 or not all(self.basis.get(i) == "control" for i in b):
                continue
            q2 = self.ctl.g.q2flop
            ps = frozenset(("w",) + blk[q2[x]] if x in q2 else ("s", x) for i in b for x in self.ctl.supp_src[i]
                           if x not in q2 or blk[q2[x]] != ("b", k))
            fam[(len(b), ps)].append(k)
        rfw = set()
        for (_w, ps), ks in fam.items():
            if len(ks) >= 2 and ps:
                rfw.update(ks)
        self.kind_of = {}
        for k, b in enumerate(self.blocks):
            self.kind_of[k] = "flag" if len(b) == 1 else ("register_file_word" if k in rfw else "data_register")

    def output(self):
        ctl = self.ctl
        self._claims_setup()
        cell = lambda i: int(ctl.flops[i].cell)  # noqa: E731
        structures, groups, singletons = [], [], []
        claims_n = collections.Counter()
        for k, (mem, st) in enumerate(self.fixed):
            groups.append((self._bkey(mem), [cell(i) for i in mem + sorted(self.extra_fixed.get(k, []), key=self._okey)]))
        for k, b in enumerate(self.blocks):
            ids = [cell(i) for i in b]
            groups.append((self._bkey(b), ids))
            if len(b) == 1:
                singletons.append(ids[0])
            claims, n_opaque, all_proven = [], 0, True
            for i in b:
                cl, info = self.flop_claims(i)
                claims += cl
                n_opaque += info["opaque"]
                all_proven &= info["proven"]
                for c in cl:
                    claims_n[c["role"]] += 1
            order, osrc = None, None
            if k in self.order_of:
                o, osrc = self.order_of[k]
                order = [[cell(i) for i in o]]
            basis = "singleton" if len(b) == 1 else (
                "control" if all(self.basis.get(i) == "control" for i in b) else "dataflow")
            shared = self.shared.get(b[0], ())
            common = [L for L in shared if all(L in self.shared.get(i, ()) for i in b)]
            cc = self._cond(common) if common else []
            control = {"basis": basis, "shared_cover": cc if cc is not None else [],
                       "hold_class": all(i in self.hold_class for i in b) and len({self.hold_class.get(i) for i in b}) == 1,
                       "order_source": osrc, "confidence": "low" if len(b) == 1 else "normal"}
            status = "proven" if all_proven and claims else "unknown"
            structures.append({"id": f"w{k}", "kind": self.kind_of[k], "flops": ids, "order": order, "params": {},
                               "control": control,
                               "proof": {"status": status, "claims": claims, "opaque_defining": n_opaque,
                                         "scope": "claims"}})
        groups.sort(key=lambda x: x[0])
        meta = {"grouping": {k: int(v) for k, v in sorted(self.stats.items())},
                "claims_by_role": dict(sorted(claims_n.items())),
                "words": len(self.blocks), "words_multi": sum(1 for b in self.blocks if len(b) > 1),
                "singletons": len(singletons),
                "structures_proven": sum(1 for s in structures if s["proof"]["status"] == "proven"),
                "flops_opaque_defining": sum(s["proof"]["opaque_defining"] for s in structures)}
        return {"structures": structures, "groups": [g for _k, g in groups], "singletons": sorted(singletons),
                "meta": meta}

    def run(self):
        for st in ("fix", "p0", "p0_holds", "hold_classes", "dataflow", "duplicates", "order", "kinds"):
            t0 = time.perf_counter()
            getattr(self, st)()
            self.timings[st] = time.perf_counter() - t0
        t0 = time.perf_counter()
        out = self.output()
        self.timings["claims"] = time.perf_counter() - t0
        return out


def group(ctl, fixed=(), params=None):
    """Word grouping on a finished control layer (see the module docstring)."""
    G = Grouper(ctl, fixed, params)
    out = G.run()
    out["_timings"] = {k: round(v, 3) for k, v in G.timings.items()}
    return out


def run_info(out):
    """Volatile facts (timings) that stay out of the result."""
    return {"timings": out.get("_timings", {})}


def recognize(nl, params=None, fixed=()):
    """Control layer plus grouping on an anonymous netlist: a result dict (RESULT_SCHEMA) whose
    structures are the formed words and whose groups partition every flop."""
    P = dict(params or {})
    ctl = _controls.analyze(nl, P)
    out = group(ctl, fixed, P)
    return {"schema": RESULT_SCHEMA, "structures": out["structures"], "groups": out["groups"],
            "meta": {"recognizer": "group", "grouping": out["meta"], "singletons": out["singletons"],
                     "controls": ctl.meta()}}
