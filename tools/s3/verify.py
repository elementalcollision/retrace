"""S3 proof verification, harness side (schema.py "Verification (v2, kind-bound)"; PRD S3).

    verify_result(nl, result) -> report        (tools/s3/run.py calls it on every result)

A structure's proof status in the result ("proven", ...) is the recognizer's claim and is never
trusted. What counts is what this module verifies, on its own GateGraph of the netlist the harness
pickled for the recognizer (the relabelled one; the recognizer only held a copy).

What "verified" means (v2.1, kind-bound, tightened 2026-09-22 after the second proof re-review).
For the four schema.STRUCTURE_KINDS the harness builds the defining claims itself from the
structure's kind, order and params; the recognizer supplies only the conditions in
structure["control"], whose keys are the kind's own set (CONTROL_KEYS_BY_KIND):

    counter          when, when_down, reset, load, hold, inverted
    shift_register   when, reset, load, hold
    synchronizer     when, reset, load, hold, input
    lfsr_crc         when, reset, load, hold, inputs

A key no kind knows is malformed; a key outside ITS kind's set is malformed when it carries a
value (null, [], {} and false are placeholders the recognizer writes uniformly and are ignored),
so schema drift cannot pass silently in either direction.

  * counter: one lane, LSB first ("order" is a list of lanes; a flat list is malformed). Under
    D = when & ~(every reset case) & ~(every load case) (async controls inactive) the word
    w = (q_0 .. q_{n-1}) steps: w' = w + s (params.direction "up") or w - s ("down"),
    s = params.step (default 1), modulo params.modulus (default 2^n), or saturating at the top
    (params.saturating: true -> the top is modulus - 1, else 2^n - 1; an int -> that value).
    Width >= COUNTER_MIN_WIDTH (2): a 1-bit "counter" is a toggle flop, not a word.
    Width / modulus / limit coherence: 2^(n-1) < modulus <= 2^n and a saturation limit >= 2^(n-1).
    EXTENT AND LIVENESS (schema v2.1): coherence alone does not bound the extent, because a step
    of 2^k makes the low k template bits the identity, so a real w-bit counter could be prepended
    with k foreign flops that merely hold. Every claimed bit must MOVE in the defining region:
    region & (template bit xor its q) must be satisfiable, for each bit (the identical case is
    caught with no SAT at all). A bit that cannot move is dead and the structure is refused. The
    live bits are reported ("live_bits"), so a consumer sees which bits the harness exercised.
    A template that is constant or independent of the word over [0, top] is refused (saturating
    needs top > step). With a modulus or top below 2^n - 1 every obligation assumes w <= top
    (S3_DESIGN 3.7), and the report says whether reset and load keep w in that range (information).
    Bit-level templates are built here from the order (adders and constant compares made with mk).
    "updown": the up template under when and the down template under when_down & ~when;
    params.direction "updown" REQUIRES control.when_down (else half the claim is unproven), and
    control.when_down is refused when the direction is not "updown". control["inverted"]: flops
    that store the complement of their word bit; default none. control.hold is REQUIRED.
  * shift_register: lanes of one depth >= 3 (SHIFT_MIN_DEPTH). Under D, stage k' = stage k-1 for
    k >= 1 in every lane; stage 0 is the lane head and is not checked. Each copy edge may be
    inverted (a flop storing the complement of its stage); the harness tries the plain copy first
    and reports inverted edges. control.hold is REQUIRED.
  * synchronizer: at least SYNC_MIN_STAGES (2) stages -- a one-flop "synchronizer" is the input
    register whose metastability the second stage exists to absorb, and every flop that registers
    a pin or a foreign-domain flop would otherwise verify as one. No condition: control.when must
    be empty and load null (a synchronous reset is allowed). Stage 0' = input or not input for each
    lane's input net (control.input: one net id, or one per lane), stage k' = stage k-1 (either
    polarity). The input net must be a primary input, a black-box output, a latch output or a flop
    of another clock domain.
  * lfsr_crc: proof.claims give each flop's next state {"type": "next", "flop": id, "equals": EXPR};
    EXPR must be an XOR (with "not" and constants) of the structure's own q's, nets listed in
    control.inputs, and constants; an input net may not depend on the structure's own state (else
    a claim could restate D). The own-bit matrix (row i = the own bits flop i's claim XORs) bounds
    the extent: read as a digraph j -> i when row i reads column j it must be STRONGLY CONNECTED
    over the structure's flops, and some row must XOR at least two own bits (else the matrix is a
    shift, a ring or a copy). Strong connectivity subsumes the v2.0 zero-row and dead-column rules
    AND refuses what they missed: a foreign flop that merely holds, carried with the weight-1 SELF
    row {"equals": {"q": itself}} (measured on TEMPO: 264 of its 2,832 flops hold under lfsr0's
    when, and any of them extended the verified 32-bit CRC). Each claim must hold under D. A
    claim's own "when", if present, must equal control.when.
  * hold (control.hold true): outside EVERY named case -- ~when & ~when_down & ~(each reset case) &
    ~(each load case) -- every flop keeps its value. Required for counter and shift_register
    (schema v2). Its region is decided by SAT and reported like the other cases (nonvacuity["hold"],
    hold_vacuous, the summary's verified_vacuous_hold).
    AN OPAQUE LOAD MAY NEVER BE THE THING THAT EMPTIES THE HOLD REGION (the lead's decision of
    2026-09-23, closing review[0] blocker 0; HOLD_EMPTY_NEEDS_VERIFIED_COVER). An empty hold region
    is accepted only when the VERIFIED cases -- the defining case, when_down and the reset cases --
    empty it BY THEMSELVES, which is what a free-running counter (when = []) looks like; if the
    region is empty only once the load cases are conjoined in, the structure is REFUSED. Without
    that rule the obligation was erasable by a content-free rewrite: a COND is a conjunction, so
    ~when is a disjunction of |when| single-literal CONDs, which is exactly what schema v2.1's load
    LIST can name -- load = [[~l] for l in when] empties the hold region, and nothing at all is then
    checked outside the defining case (measured this round on the frozen development snapshot with
    the recorded result: the transform recovers 12 of the 16 counters the hold obligation refuses
    with the rule off, and 0 with it on -- out/s3/verify/hold_gate_v5.json).
    THE COVER IS DECIDED FROM THE CUBES THE HARNESS CHECKED, NOT FROM THE CASE CONDs (2026-09-23,
    closing review[0] blocker 1 of the freeze round). A reset case is only ever CHECKED on its own
    priority cube, and that cube conjoins ~(each load case): the reset CONDs may therefore cover
    ~when at full size while the part of each reset case in which a load is active was checked by
    nothing at all. So an empty hold region is accepted only when BOTH (a) the region without the
    load conjunct is unsatisfiable AND (b) no load case is satisfiable outside the defining cases.
    Test (b) is what refuses the second content-free rewrite (T2, out/s3/verify/hold_gate_t2.py):
    for when = [l_1..l_k] whose ~l_r is the structure's real synchronous reset, set
    reset := [{[~l_i], v} for i != r] + [{[~l_r], v}] and load := [[~l_i, l_r] for i != r]; every
    lying reset case is then checked only inside the real reset, where it is true, the reset CONDs
    cover ~when, and the structure verifies with ZERO hold obligations checked. With test (b) it is
    refused. Test (b) is vacuous when there are no load cases, so a free-running counter and every
    load-free structure are unaffected.
    "hold_vacuous_cover" IS A FIELD ABOUT WHAT THE HARNESS DECIDED, and nothing else. It appears
    only when hold_vacuous is true. Its values: "verified" -- the cubes the harness CHECKED cover
    the hold region, tests (a) and (b) both unsatisfiable, and the structure may verify; "load" --
    one of the two tests was satisfiable, so an opaque load is what empties the obligation, and the
    structure is REFUSED (the reason string says which test); HOLD_COVER_UNDECIDED -- the rule is
    off and load cases exist, so the harness did not decide the question at all (the structure is
    not refused on it, and the verdict must not be read as if it had been decided); "unknown" or
    "budget" -- a solver answer, and the structure is REFUSED, never assumed covered. The summary's
    "hold_emptied_by_load" counts the "load" verdicts.
    WHAT THE RULE DOES NOT DO: it bounds the SHAPE of the cover, NOT ITS SIZE. A PARTIAL complement
    leaves the hold region non-empty on a sliver, and the obligation is then really checked -- on
    that sliver, honestly, and on almost nothing. lane_share["hold"] and load_hidden_share are the
    numbers that bound the SIZE, and they are reported for every structure; nothing here floors
    them (a floor would be a tuned threshold and needs its own changes.jsonl entry). Measured:
    out/s3/verify/hold_gate_v5.json's partial arm reaches lane_share["hold"] 0.0 with
    load_hidden_share 1.0 on a verified structure. "verified" and "verified with 99.7% of the space
    behind an opaque load" are the same word here; the share is where they differ.
  * reset (control.reset): a LIST of cases [{"when": COND, "value": {flop id: 0|1}}, ...], so a
    counter that clears AND reloads can name every case with its own value. Case i is checked on
    its own cube with the EARLIER cases and every load case removed (list order is priority, as an
    RTL if/else chain is), so the union of the named reset cases is covered exactly once. Every
    flop needs a value in every case. Each case must be non-vacuous on its own region.
  * load (control.load): a LIST of CONDs. Opaque cases, allowed, never defining; nothing is checked
    under them. Each case's share of random assignments and the own bits it reads are REPORTED
    ("load_cases"), together with the share of the state space their union hides, because an opaque
    load is the mechanism by which a padded structure hides the states in which its passengers move.
  * The v2.0 single-case forms (control.reset a bare COND with control.reset_value, control.load a
    bare COND) are still accepted while the recognizer is moved over, normalised to one-element
    lists and reported as control_form "legacy" (LEGACY_CONTROL_FORM switches them off in one line;
    the summary counts them). A list whose elements are {"net", "value"} is a COND, one whose
    elements are objects with "when" is a reset case list, one whose elements are lists is a load
    case list; [] names no case at all.
  * Non-vacuity: D (and the down case, the hold case and a claimed reset case) must be satisfiable
    with the reset and every async control of the structure's flops inactive. The report also gives
    each case's share of SHARE_LANES random assignments (information only; satisfiable is not
    common and neither says a case is reachable).
  * Coverage (schema v2; replaces the blanket self-conditioning ban). No condition the harness
    relies on -- when, when_down, reset, load, an async control of the structure's flops, or a
    clock-gating enable -- may depend on the structure's own state, except as coverage admits: the
    defining region must be satisfiable for EVERY value of the structure's own word in range (a
    counter: [0, top]; another kind: every own state). As everywhere else in this module the
    harness decides satisfiability, not reachability over time: a word value the region excludes is
    certainly not reachable in it, so the refusal is sound, while "covered" does not claim the state
    machine ever reaches that value (schema.py's "reachable" reads as this necessary condition). A wrap or reload at a terminal count is
    admitted (its cube still leaves the defining case reachable at that value through the other
    sources); a case carved down to a few own states is refused, which is what the ban existed for
    (any flop verified as a 1-bit counter under when = [its D net = 1, its Q net = 0]; measured on
    TEMPO: 2,768 of 2,832 flops). The check is exact and runs over the own bits the conditions
    actually read: those bits' 2^k assignments that some in-range word value realizes, one SAT call
    each. Past COVERAGE_MAX_OWN_BITS read own bits the structure is refused (the documented
    conservative rule; refusing is never unsound). A clock-gating enable that reads own state is
    refused outright: it is not a conjunct of any region, so coverage cannot admit it.
  * Params. What the harness can check it checks, and what it cannot it copies into the report and
    marks unchecked ("params_checked" / "params_unchecked" per structure), so a reader and score.py
    can tell a certified parameter from a transcribed one. A PARAMETER COUNTS AS CERTIFIED ONLY WHEN
    THE HARNESS ACTUALLY PINNED IT (the lead's decision of 2026-09-23), so two of the v2.1 entries
    move per structure rather than sitting in a fixed per-kind list:
      - the counter's params.modulus is certified when the template reads it, and marked unchecked
        when params.saturating carries the saturation limit itself and the declared modulus is not
        that limit + 1 -- the template then never reads it (review[0] major 3);
      - the lfsr's params.bit_order is certified only when the STAGE ORDER WAS RECONSTRUCTED: the
        own matrix is a one-step companion, or a declared (poly, k_steps) pair matched it. Nothing
        else in _lfsr constrains the order (its obligations are per-flop EXPRs), so a scrambled
        bit_order on a real CRC used to verify with bit_order "certified" (review[0] blocker 1). A
        match in the "reversed" orientation pins the order only up to reversal, and says so.
    Otherwise checked: the counter's direction, step, saturating and bit_order (the template is
    built from them), and "updown" requires control.when_down; the shift register's lanes, depth and order; the synchronizer's stages and
    order; and for lfsr_crc the polynomial and k_steps, reconstructed from the own matrix in stage
    coordinates (params.bit_order) where the form admits it -- a one-step Galois or Fibonacci
    companion reads its taps straight off the matrix, and any (poly, k_steps) pair is checked
    exactly by A == C^k (Galois) or A == (C^k)^T (Fibonacci), C the companion of the polynomial
    (tools/s3/lfsr.py's stage convention: C e_j = e_(j-1), C e_0 = t, poly bit i = coefficient of
    x^i with x^w included; the polynomial is also accepted without its x^w bit). n_inputs is checked
    when k_steps is 1. A contradiction refuses the structure (LFSR_PARAM_CHECK); a polynomial the
    harness cannot reconstruct or verify (programmable taps, form "affine", k_steps null with a
    matrix that is not one step) is marked unchecked, never assumed right. Unchecked everywhere:
    the counter's params.load flag, the shift register's direction and serial_in, lanes_unordered,
    and the lfsr's form (the Galois / Fibonacci reading of one matrix is a convention, not a fact
    of the netlist; see tools/s3/lfsr.py's "both").

WHAT "verified" ACTUALLY CERTIFIES (review[0] minor 5 of the freeze round, reproduced here VERBATIM
at the lead's instruction -- line breaks are this file's 100-column wrap, no word is changed -- so
that it can be copied into schema.py's Verification section and into the writeup, replacing the
sentences that read as though "verified" bounded the structure's description):

    WHAT "verified" ACTUALLY CERTIFIES IS NARROWER THAN schema.py READS, AND THE DIFFERENCE SHOULD
    BE WRITTEN DOWN. Precisely, for a structure S on the harness's own netlist: its flops share one
    clock root and edge; with every async clear/preset of its flops pinned inactive and (for a
    counter with top < 2^w-1) the word assumed <= top, the defining region D = when & ~(every reset
    case) & ~(every load case) is satisfiable, and -- exactly, by the coverage scan over the own
    bits the relied-on conditions read -- D is satisfiable at EVERY own-word value in range; over
    every assignment satisfying D each flop's effective next state equals the harness-built template
    bit; each counter bit's template differs from its own q somewhere in D; the shape rules hold
    (counter width >= 2 and 2^(w-1) < modulus <= 2^w, shift depth >= 3, synchronizer stages >= 2,
    lfsr own matrix strongly connected with some row of weight >= 2); each named reset case, on its
    own priority cube, drives every flop to its declared constant; and, IF the hold region is
    non-empty, the flops hold there. It certifies NOTHING under any load case, nothing about
    reachability over time (every region is decided by satisfiability, not by simulation from
    reset), nothing outside [0, top] when a modulus or limit is claimed, and -- for a synchronizer
    -- nothing about clock domains beyond "a >= 2-deep unconditional copy chain whose head samples a
    primary input, black-box output, latch output or foreign-domain flop": my E1_pin_chain_as_sync
    (a plain input register plus one more stage, scratchpad/adv5/adv5.json) verifies as a 2-stage
    synchronizer, which is correct under that definition and not a CDC claim. Also worth stating in
    schema.py: a reset case is NOT subject to the coverage obligation and may read the structure's
    own state freely (its only gates are non-vacuity on its own priority cube and the constant-value
    obligation) -- I attacked this and it is sound, but it is not written anywhere.

    In particular say (a) load cases are unbounded and unchecked, (b) the synchronizer definition is
    structural, (c) reset cases are exempt from coverage, (d) the counter obligations are
    conditional on w <= top.

ADDENDUM of this round (NOT part of the quotation, and the only sentence of it the code no longer
matches): "IF the hold region is non-empty, the flops hold there" is now also a gate in the other
direction -- an EMPTY hold region is accepted only when the cubes the harness CHECKED (the defining
case, when_down and each reset case on its own priority cube) cover it, and a structure whose hold
region is emptied by its load cases -- either by the load conjunct itself, or by a load case that is
satisfiable outside the defining cases and therefore outside every checked cube -- is refused
(HOLD_EMPTY_NEEDS_VERIFIED_COVER). So "verified" still certifies nothing under a load case, but a
load case can no longer be the reason nothing is certified outside the defining one. It remains a
SHAPE rule: on a NON-empty hold region it says nothing about how small that region is, and
lane_share["hold"] / load_hidden_share are the numbers that do.

Opaque restatements of D never verify a structure: counters, shifts and synchronizers have no
recognizer-supplied EXPR, and an lfsr_crc EXPR may read only own q's, inputs independent of the
own state, and constants. Unscored kinds may carry claims; they are never verified.

Flop model. The effective next state of a flop is D through the cell's scan/enable logic and any
ICG enable (GateGraph's Flop.ns), then logic on the clock path as an enable: a flop whose clock is
a gate over a clock root r fires on r's rising edge when the gate is positive unate in r (enable =
c|r=1 & ~c|r=0), on its falling edge when negative unate (enable = c|r=0 & ~c|r=1); binate or
ambiguous clock logic is an unsupported clock and never verifies. Async clear/preset override it
(clear and preset together: the cell's clear_preset_var1, unspecified -> 0). A claim holds only for
states where no async control of the structure's flops is active, and every region is checked with
them inactive. All flops of a structure must share one clock root and edge.

Checks. Each obligation "region -> a == b" is tried, in this order: (1) a and b are the same
literal; (2) after replacing every signal the region forces (its unit literals: when's nets, a
single-literal reset or load, the async controls) by its value, the literals coincide; (3) both
substituted literals are GF(2)-affine over their leaves (XOR gates, and small cuts of AND/OR logic
whose function is affine, up to AFFINE_CUT signals) with equal forms; (4) for lfsr_crc claims only,
BDDs of region & (a xor b) with a label-ordered variable order, within BDD_MAX_VARS / BDD_MAX_NODES
(an exact decision on the RELAXED space in which a control.inputs net that is an internal gate is a
free variable, so only its "unsat" is used: it is what verifies word-wide CRCs whose XORs ABC mapped
as disjoint halves, while its "sat" may be a phantom that contradicts the cut gate's own definition
and is therefore INCONCLUSIVE -- it falls through to (5) and never refutes anything);
(5) SAT on region & (a xor b) (z3's SAT core, a fresh context per call, conflict limit
CONFLICTS_PER_CHECK, capped by what is left of CONFLICTS_PER_RUN). (2), (3) and the BDD's "unsat"
are exact identities of the circuit functions, so they can only prove, never refute; a mismatch
goes on, and only (5) ever returns "refuted". The CNF is built
in a canonical order: signals
numbered by permutation-invariant structural labels (GateGraph.wl_labels, refined on the query's
cone with the asserted literals marked) and each gate's fanins put in label order, so a verdict is
a function of the netlist and the structure, not of the random id permutation, except between
signals no label separates. An exhausted limit is "unknown"; an exhausted run budget makes the rest
"not checked". Wall time never decides anything.

Ids are ints or ASCII decimal strings in canonical form (no sign, no leading zeros, at most 18
digits). Every structure's JSON is size- and depth-checked before anything recurses into it, its
sha256 (and its claims' sha256) is reported so a recorded run can be replayed (replay()), and any
exception while checking one structure is caught and reported as malformed (and counted), so one
structure can never crash the harness.

verify_structure(ver, s) on a structure without a "kind" keeps the v1 meaning for corpus.py's own
claim sets ("every claim holds and every flop has a defining claim"); verify_result never uses it.
"""

from __future__ import annotations

import collections
import functools
import hashlib
import itertools
import json
import random
import re
import time

from tools.s3 import schema
from tools.s3.netlist import BBOX, CONST, FLOP, FREE, GATE, INPUT, KIND_NAMES, GateGraph, _cof, _drop, _full, \
    _permute, _vmask, isop, tt_of

VERIFY_SCHEMA = "retrace-s3-verify/2"
# The report keeps schema /2 (every field below is additive, so a recorded run still reads); this
# names the schema.py contract the obligations follow: v2.1 is the multi-case reset / load lists,
# the extent-and-liveness rules and the certified params of 2026-09-22.
CONTRACT = "v2.1"

# --- limits (deterministic; none depends on wall time) --------------------------------------------
# z3 sat.max_conflicts per SAT call. S3_DESIGN M7: TEMPO's CRC miters with the control pinned solve
# in seconds; next-state obligations over one flop's cone are far smaller. More than this is
# "unknown", never "verified".
CONFLICTS_PER_CHECK = 200_000
# conflicts per run (all SAT calls of one verify_result, the clock-model calls excluded): ~50 checks
# at the per-check limit; the TEMPO snapshot run of this rewrite used a small fraction of it (see
# out/s3/verify/). Structures past it are "not checked: run conflict budget".
CONFLICTS_PER_RUN = 10_000_000
EXPR_NODES = 4096        # one EXPR: a 1,024-input xor tree needs ~1,025 nodes
EXPR_DEPTH = 64          # nesting depth of one EXPR (n-ary operators keep real claims shallow)
COND_LITERALS = 256      # conjuncts of one COND (TEMPO's longest real CONDs: 80)
JSON_NODES = 200_000     # JSON nodes of one structure (a 32-bit CRC with 32 claims: ~7,000)
JSON_DEPTH = EXPR_DEPTH + 16
JSON_STR = 4096          # characters of one string in a structure
JSON_INT_BITS = 256      # bits of one integer (a CRC-64 polynomial has 65)
STRUCTURES_PER_RUN = 50_000   # TEMPO has 2,832 flops; disjoint structures cannot exceed that
FLOPS_PER_STRUCTURE = 4096
COUNTER_MAX_WIDTH = 128  # widest counter template built (TEMPO: 32; 40-64-bit timers exist)
SHIFT_MIN_DEPTH = 3      # schema.py: shift_register depth >= 3
RESET_CASES_MAX = 64     # named reset cases of one structure (each costs a non-vacuity call + w checks)
LOAD_CASES_MAX = 64      # named load cases of one structure (each is one conjunct of every region)
# The polynomial reconstruction works on a w x w GF(2) matrix, so its cost is O(w^2) per multiply and
# O(w^2 log k) for a k-step check. These bound that work on a hostile result; past either the params
# are marked UNCHECKED (never assumed right), which is the conservative side. Real widths measured:
# 32 (the development design's two CRCs and crc32c_d32_sr), 16 (the corpus), and k at most 32.
LFSR_PARAM_MAX_WIDTH = 128
LFSR_PARAM_MAX_K = 4096
AFFINE_CUT = 10          # signals in one cut of the affine recogniser (a 2-input XOR as AND/OR: 2)
AFFINE_EXPAND = 6        # expansion rounds of one cut
# BDD path for XOR-form (lfsr_crc) claims whose cone is not syntactically affine (ABC's AIG mapping
# keeps each XOR as two disjoint halves that no gate joins). Exact, with a canonical variable order
# (structural labels); past either limit the check goes to SAT. Measured on the generalisation
# regression's fast/delay CRC-16/32C netlists (out/s3/verify/): see the report of this rewrite.
BDD_MAX_VARS = 400       # leaves of one BDD check (recursion depth of ITE is at most this)
BDD_MAX_NODES = 400_000  # nodes of one BDD check
CLOCK_SUPPORT = 16       # sources of one clock-gating function (exact truth table: 2^16 bits)
WL_ROUNDS = 4            # Weisfeiler-Lehman rounds of the base labels
REFINE_ROUNDS = 2        # label refinement rounds on each query's cone
PERMS_PER_GATE = 720     # fanin orders tried for one gate with tied labels
SHARE_LANES = 4096       # random lanes behind the reported share of each case (information only)

# --- thresholds owned by this module -------------------------------------------------------------
# NEW (2026-09-22, this rewrite). tools/s3/params.py is the recognizer's parameter file and is not
# ours: this block is marked for the integrator to move there if the lead wants it, and a proposed
# tools/s3/changes.jsonl entry is in out/s3/verify/changes_proposed.jsonl (we may not write the log).
# COVERAGE_MAX_OWN_BITS: own bits of the structure the conditions of a region may read before the
# coverage obligation stops being enumerable. The check costs one SAT call per assignment of those
# bits that an in-range word value realizes, so 12 bits = at most 4,096 small calls on one structure;
# every real self-conditioned case measured (TEMPO's rx_pos_q / tx_samp_q reload and terminal-count
# cubes: 5 own bits; the corpus's cnt_wrap_at_reg / autoreload families: <= 8) is far below it.
# Past it the structure is refused, not admitted: the conservative rule is sound, never permissive.
COVERAGE_MAX_OWN_BITS = 12
# Coverage SAT calls one verify_result may spend, over every structure (the conflict budget already
# bounds the work per call; this bounds their number). TEMPO's recorded result spends 64.
COVERAGE_CALLS_PER_RUN = 200_000
# HOLD_EMPTY_NEEDS_VERIFIED_COVER (2026-09-23, the LEAD'S DECISION on review[0] blocker 0; NOT a
# tuned threshold -- it is a contract rule with one boolean, kept here beside the switch it replaces
# as the default). The hold case is decided by SAT and reported like the others. An EMPTY hold region
# is accepted only when the VERIFIED cases -- the defining case, when_down and the reset cases --
# empty it BY THEMSELVES; a hold region that is empty only once the OPAQUE load cases are conjoined
# in REFUSES the structure. The rule exists because ~when is a disjunction of |when| single-literal
# CONDs and schema v2.1's control.load is a LIST of CONDs, so load = [[~l] for l in when] is a
# content-free rewrite of any structure that erases the hold obligation entirely. Measured, this
# round, on the frozen development snapshot with the RECORDED result (out/s3/verify/hold_gate_v5.py,
# hold_gate_v5.json). With the rule OFF the transform takes the hold-forced arm from 6/22 verified
# counters to 18/22 -- 12 of the 16 counters the hold obligation refuses, recovered with no new
# evidence about the circuit and with ZERO hold obligations checked (23 of 29 scored structures
# verified, 18 of them with a vacuous hold). With it ON the same arm gives 0/22: every transformed
# counter and shift is refused, 19 of them named "the load emptied the hold region". The rule's COST,
# on the result AS RECORDED, is the 32-bit u_tio.time_q counter (when = [ld = 0], load = [ld = 1]),
# 1 of the 6 counters today's recognizer verifies (12/29 -> 11/29 scored), and NOTHING on the 402
# corpus and generalisation references (out/s3/verify/refs_v5.json: 0 lost, 0 gained, no verdict
# differs from out/s3/verify/refs_v4.json's after arm).
# THE COVER IS READ OFF THE CHECKED CUBES (2026-09-23, review[0] blocker 1 of the freeze round). The
# test above is necessary and not sufficient: a reset case is CHECKED only on its own priority cube,
# which conjoins ~(each load case), so the reset CONDs can empty the region at full size while the
# load-active part of each reset case was checked by nothing. The rewrite that exploits it (T2,
# out/s3/verify/hold_gate_t2.py) turns each literal of `when` into its own lying reset case and hides
# the lie behind a load, and passed the test above with zero hold obligations checked. So the cover
# also requires that NO load case be satisfiable outside the defining cases. Both tests must answer
# unsat; "sat" on either gives cover "load" and refuses; unknown/budget refuses too.
# MEASURED on the frozen development snapshot with the RECORDED result, seed 20260922, T2 applied to
# 22 of the 24 counter/shift structures (2 skipped: one `when` of a single literal, one with no
# single-literal reset case) -- out/s3/verify/hold_gate_t2.json. WITHOUT the second test, T2 takes the
# hold-forced arm from 11/29 verified to 22/29, counters 5/22 -> 16/22, 17 of them with a vacuous hold
# whose cover was reported "verified", and 0 hold obligations checked ANYWHERE. WITH it: 5/29,
# counters 0/22, 18 refused "the load emptied the hold region". ITS COST IS ZERO on everything
# honest: 11/29 before and after on the recorded result and on the hold-forced arm with no verdict
# changed (out/s3/verify/tempo_v4_cover_fix.json), all eight arms of out/s3/verify/hold_gate_v5.py
# identical (hold_gate_v5_after_cover_fix.json), 0 lost and 0 gained over the 402 truth-derived
# correct-structure references with every per-kind count identical (refs_v6_cover_fix.json: corpus
# counter 138/218, shift 82/92, lfsr 62/62, sync 20/20; gen 16/34, 22/28, 26/26, 4/4), and 0 verdict
# or reason differences over the 46 structures of the attack battery, 9 verified under both
# (attacks_v6_cover_fix.json).
# WHAT IT DOES NOT CLOSE, stated because the reviewer measured it: a PARTIAL complement that leaves
# one literal's case out keeps the hold region non-empty on a sliver, and the hold obligation is then
# really checked -- on that sliver. The share of that sliver is reported (lane_share["hold"],
# load_hidden_share) and is the number a consumer must look at; THIS RULE BOUNDS THE SHAPE OF THE
# COVER, NOT ITS SIZE, and nothing here floors the share (a floor would be a tuned threshold and
# needs its own changes.jsonl entry).
# HOLD_MUST_BE_NONVACUOUS below is the blunter switch (refuse EVERY empty hold region, even a
# free-running counter's): a measurement switch only, kept because tools/s3/params.py mirrors it.
HOLD_EMPTY_NEEDS_VERIFIED_COVER = True
# Refuse an empty hold region whatever emptied it -- including when = [], whose hold region is empty
# by definition. Measurement switch (out/s3/verify/ref_hold_v3.py's fourth arm); never a mode the
# harness runs in. Every verdict reports "hold_vacuous", "hold_vacuous_cover" and nonvacuity["hold"]
# whatever these two are set to, and the summary counts "verified_vacuous_hold".
HOLD_MUST_BE_NONVACUOUS = False
# NEW (2026-09-22, the second proof re-review). None of the four is tuned: each is a shape rule read
# off schema.py, with one free integer whose value the schema states.
# COUNTER_MIN_WIDTH: a 1-bit counter's template is w' = w + 1 mod 2 = not q -- non-constant and
# word-dependent, so every degenerate gate passed it and any toggle flop (a T flip-flop, a parity
# bit, a divide-by-2) verified as "counter up by 1, mod 2^1, width 1". A word needs two bits for the
# carry that makes it a word. Measured: the development design has 0 unconditionally toggling flops,
# so this costs it nothing (out/s3/verify/blockers_v4.json, T3). THE EARLIER WORDING HERE -- "the
# corpus and generalisation references have no 1-bit counter either" -- WAS FALSE (review[0] minor 4)
# and is replaced by changes.jsonl PV04's own measurement, which was against out/s3/verify/
# refs_v4.json: "COSTS 6 OF 402 CORRECT-STRUCTURE REFERENCES: the corpus designs toggle_en_ar,
# toggle_free_nr and toggle_multi_sr (1-bit counters in the corpus truth) x 2 libraries ... the
# corpus truth calls those three toggle registers counters, so the contract and the truth now
# disagree for them -- the recognizer may still FIND them, they simply cannot be 'verified'."
# THE LEAD DECIDED that disagreement on 2026-09-23, away from this file: a 1-bit toggle register is
# kind "flag" with alt_kinds ["counter"] everywhere (the development design's TOGGLE_RULE), and
# tools/s3/corpus.py now carries the same rule (corpus.TOGGLE_RULE, creg() at width 1). Re-measured
# on that corpus THIS round: the three designs contribute 14 fewer counter references (218 instead of
# 232) and 0 of 402 references are lost to this rule (out/s3/verify/refs_v5.json, n_lost 0,
# after_not_verified has no "template" bucket left). So the rule now costs the corpus nothing either
# -- but it is the corpus truth that moved, not this bound.
COUNTER_MIN_WIDTH = 2
# SYNC_MIN_STAGES: schema.py "synchronizer: at least 2 stages". A 1-stage claim's only obligation is
# "stage 0 = the input net", which every flop registering a pin, a black-box output, a latch or a
# foreign-domain flop satisfies -- an unbounded source of verified false positives on a design with a
# wide input bus (measured on TEMPO: flop 1148; on the synthetic a2: pinr and sy[0], and a 2-lane
# version of both). The real 2-stage synchronizers are unaffected (TEMPO's three, 32 + 2 + 2 flops).
SYNC_MIN_STAGES = 2
# LEGACY_CONTROL_FORM: accept v2.0's single-case control.reset (a bare COND) with control.reset_value,
# and v2.0's single-case control.load (a bare COND), normalising both to one-element lists. The
# recognizer still emits them (every structure of the recorded TEMPO result does); turning this off
# before controls.py is moved over makes every structure with a reset malformed. A transition shim,
# not a contract: the verdict record says control_form "legacy" and the summary counts them.
LEGACY_CONTROL_FORM = True
# LFSR_PARAM_CHECK: refuse an lfsr_crc whose params.poly / k_steps / n_inputs CONTRADICT the own
# matrix (the reconstruction is exact; a value the harness cannot reconstruct or verify is marked
# unchecked instead, never assumed right). Off, the contradiction is only reported. Measured below
# in out/s3/verify/: it refuses the review's P2_lfsr_wrong_params and keeps every real CRC.
LFSR_PARAM_CHECK = True
# --- end of the thresholds block -----------------------------------------------------------------

# Conditions may not read the structure's own state except as the coverage obligation admits (see
# the module docstring). SELF_CONDITIONS_ALLOWED = True switches the coverage obligation off; it is
# a measurement switch only (out/s3/verify/ uses it to show what the obligation refuses), never a
# mode the harness runs in. It does not switch off the clock-gating-enable rule, which coverage
# cannot express.
SELF_CONDITIONS_ALLOWED = False
# The keys each kind's "control" may carry (schema.py "Verification (v2, kind-bound)"). A key no kind
# knows is malformed; a key outside its own kind's set is malformed when it carries a value, so
# control.input on a counter or control.when_down on a shift register cannot be ignored in silence.
# The recognizer writes one uniform control object with null / [] placeholders for the keys the kind
# does not use, and those placeholders are what _given() lets through.
CONTROL_KEYS_BY_KIND = {
    "counter": ("when", "when_down", "reset", "load", "hold", "inverted"),
    "shift_register": ("when", "reset", "load", "hold"),
    # "when" and "load" stay in the synchronizer's set so that _sync's own rules ("a synchronizer has
    # no condition" / "no load case") give the reason, instead of a bare "malformed".
    "synchronizer": ("when", "reset", "load", "hold", "input"),
    "lfsr_crc": ("when", "reset", "load", "hold", "inputs"),
}
# the v2.0 key the legacy single-case reset form needs (LEGACY_CONTROL_FORM)
LEGACY_CONTROL_KEYS = ("reset_value",)
# every key any kind knows, v1 name kept: outside this an unknown key is malformed for every kind
CONTROL_KEYS = tuple(sorted({k for ks in CONTROL_KEYS_BY_KIND.values() for k in ks} | set(LEGACY_CONTROL_KEYS)))
# kinds whose template is incomplete without the hold obligation (schema.py: "hold (required)")
HOLD_REQUIRED_KINDS = ("counter", "shift_register")
# params of each kind this module certifies UNCONDITIONALLY; everything else in schema.PARAMS is
# copied and marked unchecked. Params that move between the two lists PER STRUCTURE are not listed
# here and are added through _Ctx.certified / _Ctx.uncertified (which _params_report unions in):
#   * lfsr_crc's poly / k_steps / n_inputs, and its BIT_ORDER -- the only thing that constrains an
#     lfsr's stage order is the polynomial reconstruction in _lfsr_params, which does not run for a
#     matrix that is not a one-step companion and carries no declared (poly, k_steps) pair; _lfsr's
#     own obligations are per-flop EXPRs and never read the order. It was listed here unconditionally
#     until 2026-09-23, so a real CRC declared with a SCRAMBLED params.bit_order verified with
#     bit_order reported as certified (review[0] blocker 1).
#   * counter's MODULUS, which the template does not read when params.saturating carries the
#     saturation limit itself (review[0] major 3).
PARAMS_CHECKED = {
    "counter": ("direction", "step", "saturating", "bit_order"),
    "shift_register": ("lanes", "depth", "order"),
    "synchronizer": ("stages", "order"),
    "lfsr_crc": (),
}
# legacy (v1 claim sets, corpus.py): claims per structure and per run
CLAIMS_PER_STRUCTURE = 20_000
CLAIMS_PER_RUN = 500_000
ROLES = ("defining", "hold", "reset", "load")
# "hold_vacuous_cover" (written only when hold_vacuous is true) says WHAT THE HARNESS DECIDED about
# the cover of an empty hold region, and nothing else:
#   "verified"          the cubes the harness CHECKED cover the region -- both tests of
#                       _hold_reset unsat -- and the structure may verify;
#   "load"              one of the two was satisfiable: an opaque load empties the obligation, and
#                       the structure is REFUSED (the reason string says which test);
#   the string below    the rule is off and load cases exist: the question was not decided;
#   "unknown"/"budget"  a solver answer; the structure is REFUSED, never assumed covered.
# The summary's "hold_emptied_by_load" counts the "load" verdicts. The field says nothing about the
# SIZE of anything -- lane_share["hold"] and load_hidden_share are those numbers.
HOLD_COVER_UNDECIDED = "not decided (HOLD_EMPTY_NEEDS_VERIFIED_COVER off)"

_AND2, _OR2, _XOR2 = 0b1000, 0b1110, 0b0110   # truth tables over (x0, x1), bit m = f(m & 1, m >> 1)
_MUX = tt_of(lambda x: x[1] if x[0] else x[2], 3)   # x0 ? x1 : x2
_XOR3 = tt_of(lambda x: x[0] ^ x[1] ^ x[2], 3)
_MAJ = tt_of(lambda x: int(x[0] + x[1] + x[2] >= 2), 3)
_ID = re.compile(r"(?:0|[1-9][0-9]{0,17})")
_SOURCE_OK = (INPUT, BBOX, FLOP)
# label tags: ints only (hash() of str is salted per process; of int tuples it is not)
_TAG_DERIVED, _TAG_ROOT = 0x6465726976, 0x726f6f74


class Malformed(ValueError):
    """The input does not follow the schema (reported as "malformed: ...")."""


class _Fail(Exception):
    """A well-formed structure that is not verified; `bucket` is the summary class."""

    def __init__(self, reason, bucket):
        super().__init__(reason)
        self.reason, self.bucket = reason, bucket


def as_id(x):
    """An opaque id: a non-negative int (not bool) below 10^18, or its canonical ASCII decimal string;
    None otherwise ('05', ' 5', '+5', '٥', '²' are not ids)."""
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x if 0 <= x < 10 ** 18 else None
    if isinstance(x, str) and _ID.fullmatch(x):
        return int(x)
    return None


_as_id = as_id   # v1 name


def _json_check(obj, max_nodes=JSON_NODES, max_depth=JSON_DEPTH):
    """Size and depth of a JSON value, walked iteratively (nothing recurses before this passes).
    Raises Malformed on a limit or a non-JSON value; returns the node count."""
    stack = [(obj, 0)]
    n = 0
    while stack:
        o, d = stack.pop()
        n += 1
        if n > max_nodes:
            raise Malformed(f"more than {max_nodes} JSON nodes")
        if d > max_depth:
            raise Malformed(f"nested deeper than {max_depth}")
        if isinstance(o, dict):
            for k, v in o.items():
                if not isinstance(k, str) or len(k) > JSON_STR:
                    raise Malformed("object key is not a short string")
                stack.append((v, d + 1))
        elif isinstance(o, list):
            stack.extend((v, d + 1) for v in o)
        elif isinstance(o, str):
            if len(o) > JSON_STR:
                raise Malformed(f"string longer than {JSON_STR}")
        elif isinstance(o, bool) or o is None or isinstance(o, float):
            pass
        elif isinstance(o, int):
            if o.bit_length() > JSON_INT_BITS:
                raise Malformed(f"integer wider than {JSON_INT_BITS} bits")
        else:
            raise Malformed(f"not a JSON value: {type(o).__name__}")
    return n


def _sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                                     default=repr).encode()).hexdigest()


@functools.lru_cache(maxsize=None)
def _canon_tt(tt, k):
    return min(_permute(tt, k, p) for p in itertools.permutations(range(k))) if k <= 6 else tt


def _apply_tt(tt, k, ins, full):
    """Gate table tt over k inputs applied to input tables (ints over a common variable set)."""
    out = 0
    for cube in isop(tt, k):
        t = full
        for v, b in cube:
            t &= ins[v] if b else full ^ ins[v]
        out |= t
    return out


def _affine_of_table(t, m):
    """(mask of variables, constant) when the m-variable table t is affine, else None."""
    full = _full(m)
    c = t & 1
    mask = 0
    p = 0
    for i in range(m):
        if (t >> (1 << i)) & 1 != c:
            mask |= 1 << i
            p ^= _vmask(i, m)
    return (mask, c) if t == (p ^ full if c else p) else None


def _given(v):
    """Is a control key's value a real value, or the null / [] / {} / false placeholder the
    recognizer writes uniformly for the keys a kind does not use?"""
    if v is None or v is False:
        return False
    return not (isinstance(v, (list, dict, str)) and len(v) == 0)


# --- GF(2) matrices in row form (row i = a bitmask over the columns) ------------------------------
def _mat_mul(a, b, w):
    """a * b over GF(2); both in row form, w columns."""
    out = []
    for r in a:
        acc = 0
        for j in range(w):
            if (r >> j) & 1:
                acc ^= b[j]
        out.append(acc)
    return out


def _mat_pow(m, k, w):
    r = [1 << i for i in range(w)]
    base = list(m)
    while k:
        if k & 1:
            r = _mat_mul(r, base, w)
        k >>= 1
        if k:
            base = _mat_mul(base, base, w)
    return r


def _mat_t(m, w):
    out = [0] * w
    for i, r in enumerate(m):
        for j in range(w):
            if (r >> j) & 1:
                out[j] |= 1 << i
    return out


def _companion(t, w):
    """tools/s3/lfsr.py's one-step Galois companion in stage coordinates (C e_j = e_(j-1),
    C e_0 = t), in row form: row i = {i + 1} + {0 if t_i}."""
    return [((1 << (i + 1)) if i + 1 < w else 0) | (1 if (t >> i) & 1 else 0) for i in range(w)]


def _poly_of_taps(t, w):
    """lfsr.py's _poly_of: x^w + sum_j t_j x^(w-1-j), bit i = coefficient of x^i."""
    p = 1 << w
    for j in range(w):
        if (t >> j) & 1:
            p |= 1 << (w - 1 - j)
    return p


def _taps_of_poly(p, w):
    """The inverse, tolerating a polynomial written without its x^w bit."""
    return sum(1 << j for j in range(w) if (p >> (w - 1 - j)) & 1)


def _reciprocal(p, w):
    """x^w * p(1/x): bit i <-> bit w - i."""
    return sum(1 << (w - i) for i in range(w + 1) if (p >> i) & 1)


def _poly_variants(p, w):
    """One polynomial as the project's conventions write it: with and without its x^w bit, and
    REFLECTED (bit i = coefficient of x^(w-i)). tools/s3/lfsr.py's _poly_of writes bit i = the
    coefficient of x^i; the corpus truth writes the reflection (measured: every one of the 62 corpus
    lfsr references, e.g. lfsr_gal_w7_ar's 0xc1 against the matrix's 0x83), and the generalisation
    references use lfsr.py's. Which reflection a polynomial is written in is a convention nothing in
    the netlist fixes, so both are accepted -- the check still pins the matrix to 4 polynomials out
    of 2^w."""
    base = p | (1 << w)
    r = _reciprocal(base, w)
    return {base, base ^ (1 << w), r, r ^ (1 << w)}


def _strongly_connected(adj, n):
    """Is the digraph (adj[j] = the list of i with an edge j -> i) strongly connected?"""
    if n <= 1:
        return True
    back = [[] for _ in range(n)]
    for j, outs in enumerate(adj):
        for i in outs:
            back[i].append(j)
    for g in (adj, back):
        seen = {0}
        stack = [0]
        while stack:
            s = stack.pop()
            for t in g[s]:
                if t not in seen:
                    seen.add(t)
                    stack.append(t)
        if len(seen) != n:
            return False
    return True


def _refresh(g):
    """After signals were added to a GateGraph outside its constructor: the signal count and the
    cached per-signal views."""
    g.n = len(g.kind)
    for k in ("fanout", "sources", "_supp", "_srcidx"):
        g.__dict__.pop(k, None)


# ----------------------------------------------------------------------------------------------
# the verifier


class Verifier:
    """Checks on one netlist. Builds its own GateGraph (the caller's netlist is only read), resolves
    every net, builds the flop model (effective next state, async controls, clock domain) and the
    structural labels once; each structure is then checked on its own scratch copy, so its verdict
    does not depend on the structures checked before it (only on what is left of the run budget)."""

    def __init__(self, nl, conflicts=CONFLICTS_PER_CHECK, conflicts_total=CONFLICTS_PER_RUN,
                 self_conditions_allowed=SELF_CONDITIONS_ALLOWED):
        t0 = time.perf_counter()
        self.nl = nl
        self.self_conditions_allowed = self_conditions_allowed
        g = self.g = GateGraph(nl)
        for n in range(nl.n_nets):
            g.resolve(n)
        _refresh(g)
        self.flop_at = {f.cell: f for f in g.flops}
        self.stats = collections.Counter()
        self.model = {}
        self._flop_models()
        _refresh(g)
        g.supp_bits(0)
        self.src_index = g._source_index()
        self.labels = g.wl_labels(rounds=WL_ROUNDS)
        self.n_base = g.n
        self.conflicts = conflicts
        self.conflicts_total = conflicts_total
        self.conflicts_left = conflicts_total
        self.coverage_calls_left = COVERAGE_CALLS_PER_RUN
        self.model_s = round(time.perf_counter() - t0, 3)

    # --- flop model ------------------------------------------------------------------------------
    def _flop_models(self):
        g = self.g
        known = set()
        for f in g.flops:
            if g.kind[f.clk_root] in (INPUT, BBOX):
                known.add(f.clk_root)
        for _s, (ck, _en) in g.icg.items():
            if g.kind[ck >> 1] in (INPUT, BBOX):
                known.add(ck >> 1)
        for f in g.flops:
            m = {"domain": None, "unsupported": None, "gated": False, "async": (), "root_kind": None}
            root, inv = f.clk_root, f.clk_inv
            k = g.kind[root]
            en = 1
            if k in _SOURCE_OK:
                m["domain"] = (root, inv)
            elif k == GATE:
                r = self._clock_logic(2 * root + inv, known)
                if isinstance(r, str):
                    m["unsupported"] = r
                else:
                    m["domain"], en = r[0], r[1]
                    m["gated"] = True
            elif k == CONST:
                m["unsupported"] = "the clock is a constant"
            else:
                info = g.info[root]
                m["unsupported"] = f"the clock is a {KIND_NAMES[k]} signal ({info[0] if info else '?'})"
            if m["domain"] is not None:
                m["root_kind"] = KIND_NAMES[g.kind[m["domain"][0]]]
            ns = f.ns
            if en != 1:
                ns = g.mk(_MUX, [en, ns, 2 * f.q])
            clr, pre = f.clear, f.preset
            if clr or pre:
                both = f.both if f.both in (0, 1) else 0
                ns = g.mk(_MUX, [pre, 1, ns]) if pre else ns
                if clr:
                    ns = g.mk(_MUX, [clr, g.mk(_MUX, [pre, both, 0]) if pre else 0, ns])
            m["async"] = tuple(sorted({a for a in (clr, pre) if a}))
            m["enable"] = en          # the clock-gating enable folded into ns (1: not gated)
            m["ns"] = ns
            self.model[f.cell] = m
            self.stats["model_flops_gated_by_logic"] += m["gated"]
            self.stats["model_flops_async"] += bool(m["async"])
            self.stats["model_flops_unsupported_clock"] += m["unsupported"] is not None

    def _clock_logic(self, L, known):
        """((root, edge), enable literal) for a clock that is logic over one clock root, or a reason."""
        g = self.g
        idx = g._source_index()
        sup = [s for s in g.sources if g.supp_bits(L >> 1) >> idx[s] & 1]
        cands = [s for s in sup if s in known]
        if len(cands) != 1:
            cands = [s for s in sup if g.kind[s] in (INPUT, BBOX)]
        if len(cands) != 1:
            return "clock logic without one clock root"
        r = cands[0]
        if len(sup) > CLOCK_SUPPORT:
            return f"clock logic over more than {CLOCK_SUPPORT} sources"
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

    # --- structures ----------------------------------------------------------------------------------
    def verify(self, s):
        """The v2 verdict of one structure (never raises)."""
        rep = {"id": None, "kind": None, "scored": False, "verified": False, "reason": "", "bucket": "",
               "sha256": None, "claims_sha256": None, "n_flops": 0, "n_claims": 0, "checks": {},
               "conflicts": 0, "sat_calls": 0}
        ctx = None
        try:
            if not isinstance(s, dict):
                raise Malformed("a structure must be an object")
            rep["id"] = str(s.get("id"))[:80]
            _json_check(s)
            proof = s.get("proof") if isinstance(s.get("proof"), dict) else {}
            claims = proof.get("claims")
            rep["sha256"] = _sha(s)
            rep["claims_sha256"] = _sha(claims)
            rep["n_claims"] = len(claims) if isinstance(claims, list) else 0
            kind = s.get("kind")
            if kind not in schema.KINDS:
                raise Malformed(f"kind {str(kind)[:40]!r} is not a schema kind")
            rep["kind"] = kind
            if kind not in schema.STRUCTURE_KINDS:
                raise _Fail("unscored kind: never verified", "unscored kind")
            rep["scored"] = True
            if self.conflicts_left <= 0:
                raise _Fail("not checked: the run conflict budget is exhausted", "budget")
            ctx = _Ctx(self, s, rep)
            ctx.run()
            rep["verified"] = True
            rep["reason"] = "verified"
            rep["bucket"] = "verified"
            self.stats["verified"] += 1
        except _Fail as e:
            rep["reason"], rep["bucket"] = e.reason, e.bucket
        except Malformed as e:
            rep["reason"], rep["bucket"] = f"malformed: {e}", "malformed"
            self.stats["malformed"] += 1
        except Exception as e:  # noqa: BLE001  (one structure never crashes the harness)
            rep["reason"] = f"malformed: {type(e).__name__}: {str(e)[:200]}"
            rep["bucket"] = "malformed"
            rep["exception"] = True
            self.stats["exceptions"] += 1
        if ctx is not None:
            rep["conflicts"] = ctx.conflicts
            rep["sat_calls"] = ctx.sat_calls
            for k, v in ctx.methods.items():
                self.stats[f"method_{k}"] += v
        return rep

    # --- legacy single claims (v1 meaning; corpus.py and extra claims) --------------------------------
    def check_claim(self, c):
        """One v1 claim {"type": "next", "flop", "equals": EXPR, "when": COND, "role"} under the v2
        flop model (async controls of the flop inactive, clock logic as an enable):
        {"verified", "reason", "flop", "role", "internal_net"}. Not a structure verdict."""
        try:
            if not isinstance(c, dict):
                raise Malformed("a claim must be an object")
            _json_check(c)
            if c.get("type") != "next":
                raise Malformed(f"claim type {str(c.get('type'))[:40]!r} is not 'next'")
            role = c.get("role")
            if role not in ROLES:
                raise Malformed(f"role {str(role)[:40]!r} is not one of {ROLES}")
            f = self.flop(c.get("flop"))
            if "equals" not in c:
                raise Malformed("claim without 'equals'")
            ctx = _Ctx(self, None, {"checks": {}})
            nets = []
            e = ctx.expr(c["equals"], nets)
            when = ctx.cond(c.get("when", []))
        except Malformed as err:
            self.stats["malformed"] += 1
            return {"verified": False, "reason": f"malformed: {err}"}
        except Exception as err:  # noqa: BLE001
            self.stats["exceptions"] += 1
            return {"verified": False, "reason": f"malformed: {type(err).__name__}: {str(err)[:200]}"}
        m = self.model[f.cell]
        out = {"flop": f.cell, "role": role, "internal_net": any(self.g.kind[l >> 1] == GATE for l in nets)}
        if m["unsupported"]:
            return dict(out, verified=False, reason=f"unsupported clock: {m['unsupported']}")
        region = list(when) + [a ^ 1 for a in m["async"]]
        r, _how = ctx.holds(region, m["ns"], e)
        if r == "refuted":
            out.update(verified=False, reason="refuted: D differs from EXPR on some assignment satisfying COND")
        elif r in ("unknown", "budget"):
            out.update(verified=False, reason=f"unknown: conflict limit reached (D xor EXPR; {r})")
        else:
            rc = ctx.solve(region)
            if rc == "unsat":
                out.update(verified=False, reason="vacuous: COND is unsatisfiable with the async controls inactive")
            elif rc != "sat":
                out.update(verified=False, reason=f"unknown: conflict limit reached (COND; {rc})")
            else:
                out.update(verified=True, reason="verified")
        self.stats["claims_checked"] += 1
        self.stats["claims_verified"] += out["verified"]
        return out

    def flop(self, x):
        i = as_id(x)
        if i is None or i not in self.flop_at:
            raise Malformed(f"not a flop id: {str(x)[:40]!r}")
        return self.flop_at[i]

    def net_lit(self, x):
        i = as_id(x)
        if i is None or i >= self.nl.n_nets:
            raise Malformed(f"not a net id: {str(x)[:40]!r}")
        return self.g.lit_of_net[i]


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


class _BddLimit(Exception):
    pass


class _BDD:
    """A small reduced ordered BDD (no complement edges): node 0 = false, 1 = true; node i > 1 is
    (var[i], lo[i], hi[i]); variables are levels 0.. in the caller's order."""

    def __init__(self, max_nodes):
        self.v, self.lo, self.hi = [1 << 30, 1 << 30], [0, 1], [0, 1]
        self.unique = {}
        self.memo = {}
        self.max_nodes = max_nodes

    def node(self, v, lo, hi):
        if lo == hi:
            return lo
        k = (v, lo, hi)
        x = self.unique.get(k)
        if x is None:
            if len(self.v) >= self.max_nodes:
                raise _BddLimit()
            x = self.unique[k] = len(self.v)
            self.v.append(v)
            self.lo.append(lo)
            self.hi.append(hi)
        return x

    def var(self, i):
        return self.node(i, 0, 1)

    def neg(self, f):
        return self.ite(f, 0, 1)

    def ite(self, f, g, h):
        if f == 1:
            return g
        if f == 0:
            return h
        if g == h:
            return g
        if g == 1 and h == 0:
            return f
        k = (f, g, h)
        r = self.memo.get(k)
        if r is not None:
            return r
        v = min(self.v[f], self.v[g], self.v[h])
        f0, f1 = (self.lo[f], self.hi[f]) if self.v[f] == v else (f, f)
        g0, g1 = (self.lo[g], self.hi[g]) if self.v[g] == v else (g, g)
        h0, h1 = (self.lo[h], self.hi[h]) if self.v[h] == v else (h, h)
        r = self.node(v, self.ite(f0, g0, h0), self.ite(f1, g1, h1))
        self.memo[k] = r
        return r

    def gate(self, tt, ins):
        """The gate table over input BDDs (Shannon expansion on the last input)."""
        k = len(ins)
        if k == 0:
            return tt & 1
        t0, t1 = _drop(_cof(tt, k, k - 1, 0), k, k - 1), _drop(_cof(tt, k, k - 1, 1), k, k - 1)
        r0 = self.gate(t0, ins[:-1])
        r1 = self.gate(t1, ins[:-1]) if t1 != t0 else r0
        return self.ite(ins[-1], r1, r0)


# ----------------------------------------------------------------------------------------------
# one structure


class _Ctx:
    """Checks of one structure on a scratch copy of the verifier's graph."""

    def __init__(self, ver, s, rep):
        self.v, self.s, self.rep = ver, s, rep
        self.sg = ver.g.scratch()
        self.nb = ver.n_base
        self.dlab = {}
        self.aff_memo = {}
        self.sub_memo = {}
        self.conflicts = 0
        self.sat_calls = 0
        self.methods = collections.Counter()
        self.resets, self.loads, self.control_form = [], [], "v2.1"
        self.when, self.when_down = [], None
        # params this structure's own checks pinned / could not pin, beside the fixed per-kind
        # PARAMS_CHECKED list (a parameter counts as certified only when the harness actually
        # pinned it -- the lead's decision of 2026-09-23). `uncertified` wins over both.
        self.certified, self.uncertified, self.param_notes = set(), set(), {}

    # --- building --------------------------------------------------------------------------------
    def lit_tree(self, tt, lits, unit):
        """A balanced tree of a 2-input operator over lits, leaves in label order (canonical shape)."""
        lits = sorted(set(lits) if tt != _XOR2 else lits, key=lambda l: (self.label(l >> 1), l))
        if not lits:
            return unit
        while len(lits) > 1:
            nxt = [self.sg.mk(tt, [lits[i], lits[i + 1]]) for i in range(0, len(lits) - 1, 2)]
            if len(lits) % 2:
                nxt.append(lits[-1])
            lits = nxt
        return lits[0]

    def land(self, lits):
        return self.lit_tree(_AND2, lits, 1)

    def expr(self, e, nets=None):
        """The literal of an EXPR (schema.py); `nets` collects the literals of {"net"} leaves."""
        nets = [] if nets is None else nets
        cnt = [0]
        return self._expr(e, nets, 0, cnt)

    def _expr(self, e, nets, depth, cnt):
        cnt[0] += 1
        if cnt[0] > EXPR_NODES:
            raise Malformed(f"EXPR has more than {EXPR_NODES} nodes")
        if depth > EXPR_DEPTH:
            raise Malformed(f"EXPR nested deeper than {EXPR_DEPTH}")
        if not isinstance(e, dict) or len(e) != 1:
            raise Malformed(f"EXPR must be a one-key object: {str(e)[:60]!r}")
        (op, arg), = e.items()
        if op == "q":
            return 2 * self.v.flop(arg).q
        if op == "net":
            lit = self.v.net_lit(arg)
            nets.append(lit)
            return lit
        if op == "const":
            if isinstance(arg, bool) or arg not in (0, 1):
                raise Malformed(f"const must be 0 or 1: {str(arg)[:20]!r}")
            return arg
        if op == "not":
            return self._expr(arg, nets, depth + 1, cnt) ^ 1
        if op in ("and", "or", "xor"):
            if not isinstance(arg, list) or not arg:
                raise Malformed(f"{op} needs a non-empty list")
            lits = [self._expr(x, nets, depth + 1, cnt) for x in arg]
            return self.lit_tree({"and": _AND2, "or": _OR2, "xor": _XOR2}[op], lits,
                                 {"and": 1, "or": 0, "xor": 0}[op])
        raise Malformed(f"unknown EXPR operator {str(op)[:20]!r}")

    def cond(self, cond):
        """COND -> literals true when each conjunct holds."""
        if not isinstance(cond, list):
            raise Malformed("COND must be a list")
        if len(cond) > COND_LITERALS:
            raise Malformed(f"COND has more than {COND_LITERALS} conjuncts")
        out = []
        for c in cond:
            if not isinstance(c, dict) or set(c) != {"net", "value"} or isinstance(c["value"], bool) \
                    or c["value"] not in (0, 1):
                raise Malformed(f"COND conjunct must be {{net, value 0|1}}: {str(c)[:60]!r}")
            lit = self.v.net_lit(c["net"])
            out.append(lit if c["value"] == 1 else lit ^ 1)
        return out

    # --- labels and canonical CNF ------------------------------------------------------------------
    def label(self, s):
        if s < self.nb:
            return self.v.labels[s]
        x = self.dlab.get(s)
        if x is not None:
            return x
        sg = self.sg
        stack = [s]
        while stack:
            t = stack[-1]
            if t < self.nb or t in self.dlab:
                stack.pop()
                continue
            pend = [f for f in sg.fanin[t] if f >= self.nb and f not in self.dlab]
            if pend:
                stack.extend(pend)
                continue
            k = len(sg.fanin[t])
            labs = tuple(sorted(self.label(f) for f in sg.fanin[t]))
            self.dlab[t] = hash((_TAG_DERIVED, k, _canon_tt(sg.tt[t], k), labs))
            stack.pop()
        return self.dlab[s]

    def _perm(self, s, lab):
        sg = self.sg
        fan = sg.fanin[s]
        k = len(fan)
        tt = sg.tt[s]
        idx = sorted(range(k), key=lambda i: lab[fan[i]])
        groups = [list(g) for _key, g in itertools.groupby(idx, key=lambda i: lab[fan[i]])]
        if all(len(x) == 1 for x in groups):
            p = tuple(idx)
            return p, _permute(tt, k, p)
        n = 1
        for x in groups:
            for j in range(2, len(x) + 1):
                n *= j
        if n > PERMS_PER_GATE:
            p = tuple(idx)
            return p, _permute(tt, k, p)
        best = None
        for combo in itertools.product(*[itertools.permutations(x) for x in groups]):
            p = tuple(i for part in combo for i in part)
            t = _permute(tt, k, p)
            if best is None or t < best[1]:
                best = (p, t)
        return best

    def cnf(self, lits):
        """Clauses for the conjunction of `lits`, numbered in canonical (label) order."""
        sg = self.sg
        gates, leaves = sg.cone(lits)
        nodes = sorted(gates | leaves)
        lab = {s: self.label(s) for s in nodes}
        mark = collections.defaultdict(int)
        for l in lits:
            mark[l >> 1] |= 1 << (l & 1)
        for s, m in mark.items():
            lab[s] = hash((lab[s], _TAG_ROOT, m))
        gl = [s for s in nodes if s in gates]
        for _r in range(REFINE_ROUNDS):
            perms = {s: self._perm(s, lab) for s in gl}
            new = dict(lab)
            for s in gl:
                p, ptt = perms[s]
                new[s] = hash((lab[s], ptt, tuple(new[sg.fanin[s][i]] for i in p)))
            up = collections.defaultdict(list)
            for s in gl:
                for pos, i in enumerate(perms[s][0]):
                    up[sg.fanin[s][i]].append((new[s], pos))
            lab = {s: hash((new[s], tuple(sorted(up.get(s, ()))))) for s in nodes}
        perms = {s: self._perm(s, lab) for s in gl}
        order = sorted(nodes, key=lambda s: (lab[s], s))
        var = {s: i + 1 for i, s in enumerate(order)}
        clauses = []
        for s in order:
            if s in gates:
                p, ptt = perms[s]
                k = len(p)
                fan = [var[sg.fanin[s][i]] for i in p]
                y = var[s]
                for cube in isop(ptt, k):
                    clauses.append([-fan[v] if b else fan[v] for v, b in cube] + [y])
                for cube in isop(_full(k) ^ ptt, k):
                    clauses.append([-fan[v] if b else fan[v] for v, b in cube] + [-y])
        for l in sorted(lits, key=lambda l: (var[l >> 1], l & 1)):
            clauses.append([-var[l >> 1] if l & 1 else var[l >> 1]])
        return clauses, len(order)

    def solve(self, lits):
        """Satisfiability of a conjunction of literals: "sat", "unsat", "unknown" (the per-check
        limit) or "budget" (the run budget ran out first)."""
        lits = set(lits)
        if 0 in lits:
            return "unsat"
        lits.discard(1)
        if any(l ^ 1 in lits for l in lits):
            return "unsat"
        if not lits:
            return "sat"
        v = self.v
        limit = min(v.conflicts, v.conflicts_left)
        if limit <= 0:
            return "budget"
        import z3
        clauses, nv = self.cnf(sorted(lits))
        body = " 0\n".join(" ".join(map(str, c)) for c in clauses)
        s = z3.SolverFor("QF_FD", ctx=z3.Context())
        s.set("max_conflicts", int(limit))
        s.set("random_seed", 0)
        s.from_string(f"p cnf {nv} {len(clauses)}\n{body} 0\n")
        r = s.check()
        st = s.statistics()
        used = int(st.get_key_value("sat conflicts")) if "sat conflicts" in st.keys() else 0
        v.conflicts_left -= used
        self.conflicts += used
        self.sat_calls += 1
        v.stats["sat_calls"] += 1
        v.stats["conflicts"] += used
        if r == z3.unsat:
            return "unsat"
        if r == z3.sat:
            return "sat"
        v.stats["unknown"] += 1
        return "budget" if limit < v.conflicts else "unknown"

    # --- obligations -----------------------------------------------------------------------------
    def _units(self, region):
        """The signals the region forces, {signal: value}, or None when two units contradict."""
        repl = {}
        for L in region:
            if L == 1:
                continue
            if L == 0:
                return None
            s, val = L >> 1, (L & 1) ^ 1
            if repl.get(s, val) != val:
                return None
            repl[s] = val
        # derived signals (the negated reset/load cube, the counter's range) never occur in a base
        # cone; replacing them would only force a rebuild of whole cones
        return {s: x for s, x in repl.items() if s < self.nb}

    def affine(self, lit, stop):
        """(frozenset of leaf signals, constant) when `lit` is affine over its leaves (sources and
        the signals in `stop`), else None. Gates: an affine table over affine fanins, or a cut of at
        most AFFINE_CUT affine signals below the gate over which its function is affine."""
        sg = self.sg
        memo = self.aff_memo.setdefault(stop, {0: (frozenset(), 0)})
        stack = [lit >> 1]
        while stack:
            s = stack[-1]
            if s in memo:
                stack.pop()
                continue
            if sg.kind[s] != GATE or s in stop:
                memo[s] = (frozenset([s]), 0)
                stack.pop()
                continue
            pend = [f for f in sg.fanin[s] if f not in memo]
            if pend:
                stack.extend(pend)
                continue
            stack.pop()
            k = len(sg.fanin[s])
            forms = [memo[f] for f in sg.fanin[s]]
            a = _affine_of_table(sg.tt[s], k)
            if a is not None and all(forms[i] is not None for i in range(k) if a[0] >> i & 1):
                acc, c = set(), a[1]
                for i in range(k):
                    if a[0] >> i & 1:
                        acc ^= forms[i][0]
                        c ^= forms[i][1]
                memo[s] = (frozenset(acc), c)
                continue
            memo[s] = self._affine_cut(s, memo)
        r = memo[lit >> 1]
        return None if r is None else (r[0], r[1] ^ (lit & 1))

    def _affine_cut(self, s, memo):
        sg = self.sg
        cut = {s}
        for _r in range(AFFINE_EXPAND):
            bad = [c for c in cut if memo.get(c) is None]
            if not bad:
                break
            for c in bad:
                if sg.kind[c] != GATE:
                    return None
                cut.discard(c)
                cut.update(sg.fanin[c])
            if len(cut) > AFFINE_CUT:
                return None
        if any(memo.get(c) is None for c in cut):
            return None
        cl = sorted(cut)
        try:
            t = _cone_table(sg, 2 * s, cl)
        except KeyError:
            return None
        a = _affine_of_table(t, len(cl))
        if a is None:
            return None
        acc, c = set(), a[1]
        for i, x in enumerate(cl):
            if a[0] >> i & 1:
                acc ^= memo[x][0]
                c ^= memo[x][1]
        return frozenset(acc), c

    def bdd_check(self, region, a, b, stop):
        """region & (a xor b) by BDDs: "unsat", "sat", or None past the limits."""
        sg = self.sg
        lits = [l for l in region if l != 1] + [sg.mk(_XOR2, [a, b])]
        if 0 in lits:
            return "unsat"
        gates, leaves = sg.cone(lits)
        leaves = set(leaves)
        for s in stop:
            if s in gates:
                leaves.add(s)
        if len(leaves) > BDD_MAX_VARS:
            return None
        order = sorted(leaves, key=lambda s: (self.label(s), s))
        bdd = _BDD(BDD_MAX_NODES)
        val = {0: 0}
        for i, s in enumerate(order):
            val[s] = bdd.var(i)
        try:
            for s in sorted(gates):
                if s in val:
                    continue
                val[s] = bdd.gate(sg.tt[s], [val[f] for f in sg.fanin[s]])
            acc = 1
            for l in lits:
                x = val[l >> 1]
                acc = bdd.ite(acc, bdd.neg(x) if l & 1 else x, 0)
                if acc == 0:
                    return "unsat"
        except _BddLimit:
            self.methods["bdd limit"] += 1
            return None
        return "unsat" if acc == 0 else "sat"

    def holds(self, region, a, b, stop=frozenset(), xor_claim=False):
        """Does region (literals, all true) imply a == b? -> (verdict, method); verdict is "holds",
        "refuted", "unknown" or "budget"."""
        if a == b:
            self.methods["identical"] += 1
            return "holds", "identical"
        repl = self._units(region)
        if repl is None:
            self.methods["empty region"] += 1
            return "holds", "empty region"
        key = frozenset(repl.items())
        memo = self.sub_memo.setdefault(key, {})
        sg = self.sg
        a2 = sg.substitute(a, repl, memo) if repl else a
        b2 = sg.substitute(b, repl, memo) if repl else b
        if a2 == b2:
            self.methods["units"] += 1
            return "holds", "units"
        st = frozenset(sg.substitute(2 * x, repl, memo) >> 1 for x in stop) if repl else frozenset(stop)
        fa = self.affine(a2, st)
        if fa is not None:
            fb = self.affine(b2, st)
            if fa == fb:
                self.methods["affine"] += 1
                return "holds", "affine"
        if xor_claim:
            # The BDD cuts at every `stop` signal, so a control.inputs net that is an internal GATE
            # becomes a free variable uncorrelated with its own fanins. That relaxation is sound in
            # one direction only: "unsat" over the relaxed space implies "unsat" over the real one,
            # while "sat" may be a phantom assignment that contradicts the cut gate's definition
            # (the review's example: a mapped a21oi whose fanin is (a1, a2, b1) directly rather than
            # through the `a & b` node control.inputs names). So a "sat" is INCONCLUSIVE and falls
            # through to SAT on the real cones; the BDD path never refutes anything.
            rb = self.bdd_check(region, a2, b2, st)
            if rb == "unsat":
                self.methods["bdd"] += 1
                return "holds", "bdd"
            if rb == "sat":
                self.methods["bdd inconclusive"] += 1
        self.methods["sat"] += 1
        r = self.solve(list(region) + [sg.mk(_XOR2, [a2, b2])])
        return {"unsat": "holds", "sat": "refuted"}.get(r, r), "sat"

    # --- the structure ---------------------------------------------------------------------------
    def run(self):
        v, s, rep = self.v, self.s, self.rep
        kind = s["kind"]
        flops = self._flops(s.get("flops"))
        rep["n_flops"] = len(flops)
        params = s.get("params") if s.get("params") is not None else {}
        if not isinstance(params, dict):
            raise Malformed("params must be an object")
        lanes = self._lanes(s, kind, flops, params)
        c = s.get("control") if s.get("control") is not None else {}
        if not isinstance(c, dict):
            raise Malformed("control must be an object")
        unknown = sorted(k for k in c if k not in CONTROL_KEYS)
        if unknown:
            raise Malformed(f"control has unknown key(s) {unknown[:4]}: the schema's keys are {list(CONTROL_KEYS)}")
        allowed = set(CONTROL_KEYS_BY_KIND[kind]) | (set(LEGACY_CONTROL_KEYS) if LEGACY_CONTROL_FORM else set())
        foreign = sorted(k for k, x in c.items() if k not in allowed and _given(x))
        if foreign:
            raise Malformed(f"control key(s) {foreign[:4]} do not belong to a {kind}: its keys are "
                            f"{list(CONTROL_KEYS_BY_KIND[kind])}")
        self.flops = flops
        self.fset = set(flops)
        self.own_mask = 0
        for f in flops:
            self.own_mask |= 1 << v.src_index[v.flop_at[f].q]
        # clock domain
        doms = set()
        for f in flops:
            m = v.model[f]
            if m["unsupported"]:
                raise _Fail(f"unsupported clock: {m['unsupported']}", "unsupported clock")
            doms.add(m["domain"])
        if len(doms) != 1:
            raise _Fail(f"the structure's flops are in {len(doms)} clock domains (root and edge)", "clock domains")
        self.domain = next(iter(doms))
        rep["clock"] = {"root_kind": v.model[flops[0]]["root_kind"], "edge": "fall" if self.domain[1] else "rise",
                        "gated_flops": sum(v.model[f]["gated"] for f in flops),
                        "async_flops": sum(bool(v.model[f]["async"]) for f in flops)}
        # control (schema v2.1: reset a list of cases, load a list of CONDs)
        when = self.cond([] if c.get("when") is None else c["when"])
        resets, loads = self._reset_cases(c), self._load_cases(c)
        hold = c.get("hold", False)
        if hold is None:
            hold = False
        if not isinstance(hold, bool):
            raise Malformed("control.hold must be true or false")
        if kind in HOLD_REQUIRED_KINDS and not hold:
            raise _Fail(f"control.hold is required for a {kind} (schema v2) and is not claimed", "hold")
        when_down = None
        if _given(c.get("when_down")):
            when_down = self.cond(c["when_down"])
        self.async_off = sorted({a ^ 1 for f in flops for a in v.model[f]["async"]})
        self.when, self.when_down = when, when_down
        self.resets, self.loads = resets, loads
        # the negated cubes: outside EVERY named case
        n_r = self.land([self.land(r[0]) ^ 1 for r in resets]) if resets else 1
        n_l = self.land([self.land(l) ^ 1 for l in loads]) if loads else 1
        self.n_r, self.n_l = n_r, n_l
        rep["control_form"] = self.control_form
        rep["cases"] = {"reset": len(resets), "load": len(loads),
                        "when_down": when_down is not None, "hold": bool(hold)}
        rep["self_conditioned"] = sc = self._self_conditioning()
        self._case_report()
        # A clock-gating enable that reads the structure's own state is not a conjunct of any region
        # (it is folded into the effective next state), so the coverage obligation cannot admit it.
        if sc["clock_enable"]:
            raise _Fail("self-conditioned: the clock-gating enable of a flop reads the structure's own state",
                        "self-conditioned")
        self.word, self.top = [2 * v.flop_at[f].q for f in flops], (1 << len(flops)) - 1
        if kind == "counter":
            self._counter(lanes[0], params, c, hold)
        elif kind == "shift_register":
            self._shift(lanes, params, hold)
        elif kind == "synchronizer":
            self._sync(lanes, params, c, hold)
        else:
            self._lfsr(s, c, hold, lanes)
        self._params_report(kind, params)

    # --- control cases -----------------------------------------------------------------------------
    def _values(self, x, what):
        """{flop id: 0|1} for every flop of the structure."""
        if not isinstance(x, dict):
            raise Malformed(f"{what} must be an object {{flop id: 0|1}}")
        vals = {}
        for k, y in x.items():
            i = as_id(k)
            if i is None or i not in self.fset:
                raise Malformed(f"{what} key {str(k)[:40]!r} is not a flop of the structure")
            if isinstance(y, bool) or y not in (0, 1):
                raise Malformed(f"{what} values must be 0 or 1")
            vals[i] = y
        missing = [f for f in self.flops if f not in vals]
        if missing:
            raise Malformed(f"{what} misses {len(missing)} of the structure's flops")
        return vals

    @staticmethod
    def _is_cond(x):
        return isinstance(x, list) and all(isinstance(e, dict) and "net" in e for e in x)

    def _reset_cases(self, c):
        """control.reset -> [(COND literals, {flop: 0|1})], in the list's own (priority) order.
        schema v2.1 gives a list of {"when": COND, "value": {...}}; LEGACY_CONTROL_FORM also accepts
        v2.0's bare COND with control.reset_value beside it."""
        self.control_form = "v2.1"
        r = c.get("reset")
        if r is None:
            if _given(c.get("reset_value")):
                raise Malformed("control.reset_value without control.reset")
            return []
        if not isinstance(r, list):
            raise Malformed("control.reset must be null or a list of reset cases")
        if not r:
            return []                                   # names no case at all
        if all(isinstance(e, dict) and set(e) >= {"net", "value"} for e in r):
            if not LEGACY_CONTROL_FORM:
                raise Malformed("control.reset is a bare COND: schema v2.1 wants a list of "
                                '{"when": COND, "value": {flop: 0|1}} cases')
            self.control_form = "legacy"
            return [(self.cond(r), self._values(c.get("reset_value"), "control.reset_value"))]
        if len(r) > RESET_CASES_MAX:
            raise Malformed(f"control.reset has more than {RESET_CASES_MAX} cases")
        out = []
        for e in r:
            if not isinstance(e, dict) or set(e) - {"when", "value"} or "value" not in e:
                raise Malformed('a reset case must be {"when": COND, "value": {flop id: 0|1}}: '
                                f"{str(e)[:60]!r}")
            out.append((self.cond([] if e.get("when") is None else e["when"]),
                        self._values(e["value"], "a reset case's value")))
        if _given(c.get("reset_value")):
            raise Malformed("control.reset_value belongs to the v2.0 single-case form: a v2.1 reset "
                            "case carries its own 'value'")
        return out

    def _load_cases(self, c):
        """control.load -> [COND literals]. schema v2.1 gives a list of CONDs; LEGACY_CONTROL_FORM
        also accepts v2.0's bare COND."""
        l = c.get("load")
        if l is None:
            return []
        if not isinstance(l, list):
            raise Malformed("control.load must be null or a list of load cases")
        if not l:
            return []                                   # names no case at all
        if all(isinstance(e, dict) and "net" in e for e in l):
            if not LEGACY_CONTROL_FORM:
                raise Malformed("control.load is a bare COND: schema v2.1 wants a list of CONDs")
            self.control_form = "legacy"
            return [self.cond(l)]
        if len(l) > LOAD_CASES_MAX:
            raise Malformed(f"control.load has more than {LOAD_CASES_MAX} cases")
        if not all(self._is_cond(e) for e in l):
            raise Malformed("control.load must be a list of CONDs (each a list of {net, value})")
        return [self.cond(e) for e in l]

    def _case_report(self):
        """Each named case's share of random assignments and the own bits it reads, and the share of
        the state space the load cases hide (information: this is the mechanism by which a padded
        structure keeps the harness away from the states in which its passengers move)."""
        sg, rep = self.sg, self.rep
        off = self.async_off

        def own_bits(lits):
            b = 0
            for l in lits:
                b |= sg.supp_bits(l >> 1) & self.own_mask
            return bin(b).count("1")

        rep["load_cases"] = [{"literals": len(l), "share": self.share(list(l) + off),
                              "own_bits_read": own_bits(l)} for l in self.loads]
        rep["reset_cases"] = [{"literals": len(r[0]), "share": self.share(list(r[0]) + off),
                               "own_bits_read": own_bits(r[0]),
                               "ones": sum(1 for x in r[1].values() if x)} for r in self.resets]
        if self.loads:
            any_load = self.lit_tree(_OR2, [self.land(l) for l in self.loads], 0)
            rep["load_hidden_share"] = self.share([any_load] + off)

    def _params_report(self, kind, params):
        """Which of the structure's declared params this verdict certifies and which it only copies.
        PARAMS_CHECKED is the fixed per-kind list of what a kind's template always reads; a param the
        harness pinned only for THIS structure comes from self.certified (lfsr_crc's poly / k_steps /
        n_inputs and its bit_order, per _lfsr_params; nothing else today), and one it could not pin
        from self.uncertified, which wins over both lists. The lfsr's `form` is never certified."""
        known = set(schema.PARAMS.get(kind, ()))
        lp = self.rep.get("lfsr_params") or {}
        checked = set(PARAMS_CHECKED.get(kind, ())) | set(lp.get("checked", ())) | self.certified
        checked -= set(lp.get("unchecked", ())) | self.uncertified
        given = [k for k in sorted(params) if k in known and params[k] is not None]
        self.rep["params_checked"] = [k for k in given if k in checked]
        self.rep["params_unchecked"] = [k for k in given if k not in checked]
        notes = {k: why for k, why in sorted(self.param_notes.items()) if k in given}
        if notes:
            self.rep["params_notes"] = notes
        extra = sorted(k for k in params if k not in known)
        if extra:
            self.rep["params_unknown"] = extra[:8]

    def _flops(self, x):
        if not isinstance(x, list) or not x:
            raise Malformed("flops must be a non-empty list")
        if len(x) > FLOPS_PER_STRUCTURE:
            raise Malformed(f"more than {FLOPS_PER_STRUCTURE} flops")
        out = [self.v.flop(f).cell for f in x]
        if len(set(out)) != len(out):
            raise Malformed("a flop is listed twice")
        return out

    def _lanes(self, s, kind, flops, params):
        pkey = "bit_order" if kind in ("counter", "lfsr_crc") else "order"

        def norm(o, what, flat_ok=False):
            """schema.py: "order" is always a list of lanes. Only params.bit_order (one word, LSB
            first) may be flat; a flat "order" is malformed, as run.py's validate_result_types and
            schema.check_result already treat it (a type problem invalidates the whole run)."""
            if o is None:
                return None
            if not isinstance(o, list) or not o:
                raise Malformed(f"{what} must be a non-empty list")
            if all(isinstance(l, list) for l in o):
                lanes = o
            elif not any(isinstance(l, list) for l in o):
                if not flat_ok:
                    raise Malformed(f"{what} is a flat list: it must be a list of lanes")
                lanes = [o]
            else:
                raise Malformed(f"{what} mixes lanes and ids")
            out = []
            for lane in lanes:
                if not lane:
                    raise Malformed(f"{what} has an empty lane")
                ids = []
                for x in lane:
                    i = as_id(x)
                    if i is None:
                        raise Malformed(f"{what}: not an id: {str(x)[:40]!r}")
                    ids.append(i)
                out.append(ids)
            flat = [i for lane in out for i in lane]
            if sorted(flat) != sorted(flops):
                raise Malformed(f"{what} is not a permutation of the structure's flops")
            return out

        order = norm(s.get("order"), "order")
        porder = norm(params.get(pkey), f"params.{pkey}", flat_ok=pkey == "bit_order")
        if order is None:
            order = porder
        elif porder is not None and porder != order:
            raise _Fail(f"order and params.{pkey} disagree", "order")
        if order is None and kind != "lfsr_crc":
            raise _Fail("no order: the harness builds the templates from it", "order")
        return order

    def _self_conditioning(self):
        """Per condition the harness relies on, the conjuncts that read the structure's own state:
        when / when_down / reset / load, the async controls of its flops, and the clock-gating
        enable folded into their effective next state. Reported, and gating only for the clock
        enable; the rest are decided by the coverage obligation (see the module docstring)."""
        sg, v = self.sg, self.v
        out = {}
        cases = [("when", self.when), ("when_down", self.when_down)]
        cases += [("reset", r[0]) for r in self.resets] + [("load", l) for l in self.loads]
        for name, lits in cases:
            if lits:
                out[name] = out.get(name, 0) + sum(1 for l in lits if sg.supp_bits(l >> 1) & self.own_mask)
        out["async"] = sum(1 for l in self.async_off if v.g.supp_bits(l >> 1) & self.own_mask)
        out["clock_enable"] = sum(1 for f in self.flops
                                  if v.model[f]["enable"] != 1 and v.g.supp_bits(v.model[f]["enable"] >> 1)
                                  & self.own_mask)
        out["state_literals"] = sum(1 for l in self.when if self.sg.kind[l >> 1] == FLOP)
        return out

    def _coverage(self, name, region, dom_lits=(), word=None, top=None):
        """Schema v2: the defining region must be reachable for every value of the structure's own
        word in range -- a counter's [0, top], every own state for another kind. Exact: the region's
        satisfiability depends on the own word only through the own bits its conditions read (the
        rest are free sources), so it is enough to check, for each assignment of those k bits that
        some in-range word value realizes, that the region is satisfiable with the bits pinned to it.
        `dom_lits` (the counter's `val <= top` literal) is left out of the scan and kept in the
        region: it is the range itself, and any assignment with the free bits 0 satisfies it.
        Past COVERAGE_MAX_OWN_BITS own bits the structure is refused (conservative, see the header)."""
        v, sg = self.v, self.sg
        word = self.word if word is None else word
        top = self.top if top is None else top
        skip = {l >> 1 for l in dom_lits}
        bits = 0
        for l in region:
            if (l >> 1) not in skip:
                bits |= sg.supp_bits(l >> 1) & self.own_mask
        pos = [i for i, lit in enumerate(word) if bits >> v.src_index[lit >> 1] & 1]
        rep = self.rep.setdefault("coverage", {})
        if not pos:
            # no relied-on condition reads the own word: the region is a predicate over the other
            # sources, so its satisfiability (_nonvacuous) gives every own value in range at once.
            rep[name] = {"own_bits": 0, "values": 0, "status": "free"}
            return
        if len(pos) > COVERAGE_MAX_OWN_BITS:
            rep[name] = {"own_bits": len(pos), "values": 0, "status": "too wide"}
            raise _Fail(f"coverage: the {name} case reads {len(pos)} of the structure's own bits, more than "
                        f"{COVERAGE_MAX_OWN_BITS}: the obligation is not enumerable at this width", "coverage")
        n = 0
        for m in range(1 << len(pos)):
            low = sum(1 << pos[j] for j in range(len(pos)) if m >> j & 1)
            if low > top:                      # no word value in range realizes this assignment
                continue
            if self.v.coverage_calls_left <= 0:
                rep[name] = {"own_bits": len(pos), "values": n, "status": "budget"}
                raise _Fail(f"not checked: the run's coverage call budget is exhausted ({name})", "budget")
            self.v.coverage_calls_left -= 1
            cube = [word[pos[j]] ^ (1 - (m >> j & 1)) for j in range(len(pos))]
            r = self.solve(list(region) + cube)
            n += 1
            if r == "unsat":
                rep[name] = {"own_bits": len(pos), "values": n, "status": "uncovered", "uncovered_bits": low}
                raise _Fail(f"coverage: the {name} case is unreachable for own-word values with bits "
                            f"{low:#x} on the read bits {pos}: a case carved down to some of the word's own "
                            f"states is refused", "coverage")
            if r != "sat":
                rep[name] = {"own_bits": len(pos), "values": n, "status": r}
                raise _Fail(f"unknown: coverage of the {name} case ({r})", "budget" if r == "budget" else "unknown")
        rep[name] = {"own_bits": len(pos), "values": n, "status": "covered"}

    def share(self, region):
        """Share of SHARE_LANES uniformly random source assignments that satisfy the region (reported,
        never gating: a satisfiable case can still be rare). Each source's random stream is seeded by
        its structural label, so the share does not depend on the id permutation."""
        lits = [l for l in region if l != 1]
        if 0 in lits:
            return 0.0
        if not lits:
            return 1.0
        sg = self.sg
        gates, leaves = sg.cone(lits)
        full = (1 << SHARE_LANES) - 1
        val = {0: 0}
        for s in leaves:
            val[s] = random.Random(self.label(s) & ((1 << 64) - 1)).getrandbits(SHARE_LANES)
        for s in sorted(gates):
            val[s] = _apply_tt(sg.tt[s], len(sg.fanin[s]), [val[f] for f in sg.fanin[s]], full)
        acc = full
        for l in lits:
            x = val[l >> 1]
            acc &= (full ^ x) if l & 1 else x
        return round(bin(acc).count("1") / SHARE_LANES, 4)

    def _nonvacuous(self, name, region):
        r = self.solve(region)
        self.rep.setdefault("nonvacuity", {})[name] = r
        self.rep.setdefault("lane_share", {})[name] = self.share(region)
        if r == "unsat":
            raise _Fail(f"vacuous: the {name} case is unsatisfiable with the reset and async controls inactive",
                        "vacuous")
        if r != "sat":
            raise _Fail(f"unknown: non-vacuity of the {name} case ({r})", "budget" if r == "budget" else "unknown")

    def _defining_case(self, name, region, dom_lits=(), word=None, top=None):
        """A defining region's two obligations before its templates are checked: non-vacuity, and
        coverage of every own-word value in range (SELF_CONDITIONS_ALLOWED switches coverage off:
        a measurement switch, see the header)."""
        self._nonvacuous(name, region)
        if not self.v.self_conditions_allowed:
            self._coverage(name, region, dom_lits, word, top)

    def _obligations(self, name, region, pairs, polarity=False, stop=frozenset(), xor_claim=False):
        """pairs: [(flop, a, b)]; every a == b under region (polarity: a == b or a == not b)."""
        inv = 0
        n = 0
        for f, a, b in pairs:
            if polarity:
                repl = self._units(region)
                first = b
                if repl:
                    memo = self.sub_memo.setdefault(frozenset(repl.items()), {})
                    if self.sg.substitute(a, repl, memo) == self.sg.substitute(b, repl, memo) ^ 1:
                        first = b ^ 1
                r, how = self.holds(region, a, first, stop)
                if r == "refuted":
                    r, how = self.holds(region, a, first ^ 1, stop)
                    first ^= 1
                inv += first != b
            else:
                r, how = self.holds(region, a, b, stop, xor_claim)
            n += 1
            if r != "holds":
                self.rep["failed_check"] = {"case": name, "flop": f, "result": r, "method": how}
                bucket = {"refuted": "refuted", "budget": "budget"}.get(r, "unknown")
                what = {"refuted": "refuted", "budget": "not checked (run conflict budget)"}.get(r, "unknown (conflict limit)")
                raise _Fail(f"{what}: the {name} template of flop {f}", bucket)
        self.rep["checks"][name] = n
        if polarity:
            self.rep["inverted_edges"] = self.rep.get("inverted_edges", 0) + inv

    def _hold_reset(self, hold, extra_off=(), dom=()):
        """The hold case (outside EVERY named case) and one obligation per named reset case."""
        v = self.v
        if hold:
            verified_only = [self.land(self.when) ^ 1] + list(extra_off) + [self.n_r] + self.async_off + list(dom)
            region = verified_only + [self.n_l]
            # like when / when_down / reset, the hold case gets its non-vacuity decided and reported,
            # not only the syntactic `0 in region` of v2.0: a hold region that is unsatisfiable
            # through logic must not pass as trivially true.
            r = "unsat" if 0 in region else self.solve(region)
            self.rep.setdefault("nonvacuity", {})["hold"] = r
            self.rep.setdefault("lane_share", {})["hold"] = self.share(region)
            if r == "unsat":
                self.rep["hold_vacuous"] = True
                # AN OPAQUE LOAD MAY NEVER BE THE THING THAT EMPTIES THE HOLD REGION (the lead's
                # decision of 2026-09-23; HOLD_EMPTY_NEEDS_VERIFIED_COVER). TWO tests, because the
                # cover is decided from the cubes the harness CHECKED and not from the case CONDs
                # (review[0] blocker 1 of the freeze round):
                #   (a) the same region WITHOUT the load conjunct. Unsat there too means the VERIFIED
                #       cases (the defining case, when_down, the reset cases -- with the async
                #       controls inactive and the counter's word in range) empty it by themselves,
                #       which is what a free-running counter looks like; satisfiable there means the
                #       load cases are what erased the obligation, and the structure is refused.
                #       Without this, load = [[~l] for l in control.when] verifies any structure with
                #       no hold check at all.
                #   (b) (a) alone is NOT the cover, because a reset case is only ever CHECKED on its
                #       own priority cube, and that cube conjoins self.n_l -- it EXCLUDES the load
                #       cases. So test (a) can be unsat because the reset CONDs cover ~when AT FULL
                #       SIZE while the part of each reset case in which a load is active was never
                #       checked by anything. The content-free rewrite that exploits exactly that
                #       (reviewer's T2: for when = [l_1..l_k] whose ~l_r is the real reset, set
                #       reset := [{[~l_i], v} for i != r] + [{[~l_r], v}] and
                #       load := [[~l_i, l_r] for i != r]) makes every lying case check out inside the
                #       real reset, empties the hold region and passes (a) -- with ZERO hold
                #       obligations checked. So also require that NO load case be satisfiable outside
                #       the defining cases: [~when] + extra_off + async_off + dom + [~n_l] unsat.
                #       With no load cases n_l = 1 and the test is vacuously satisfied, so a
                #       free-running counter is unaffected.
                # Either test answering "sat" gives cover "load" and refuses; an undecided answer
                # (unknown / budget) is refused too and never assumed covered.
                cover, why, how = "verified", r, None
                if self.loads and HOLD_EMPTY_NEEDS_VERIFIED_COVER:
                    why = "unsat" if 0 in verified_only else self.solve(verified_only)
                    if why == "sat":
                        cover, how = "load", "conjoined"
                    elif why != "unsat":
                        cover = why       # unknown / budget: refused below, never assumed covered
                    else:
                        outside = [self.land(self.when) ^ 1] + list(extra_off) + self.async_off + \
                            list(dom) + [self.n_l ^ 1]
                        why = "unsat" if 0 in outside else self.solve(outside)
                        if why == "sat":
                            cover, how = "load", "outside"
                        elif why != "unsat":
                            cover = why
                elif self.loads:
                    cover = HOLD_COVER_UNDECIDED
                self.rep["hold_vacuous_cover"] = cover
                self.rep["hold_named_cases"] = named = \
                    ["defining"] + (["down"] if self.when_down is not None else []) + \
                    ([f"reset x{len(self.resets)}"] if self.resets else []) + \
                    ([f"load x{len(self.loads)}"] if self.loads else [])
                if cover == "load" and how == "conjoined":
                    raise _Fail("vacuous: the hold region is empty only once control.load is conjoined in -- "
                                f"without the {len(self.loads)} opaque load case(s) it is satisfiable, so the "
                                "load is what erases the hold obligation and nothing at all would be checked "
                                "outside the defining case", "vacuous")
                if cover == "load":
                    raise _Fail(f"vacuous: the hold region is empty, but one of the {len(self.loads)} opaque "
                                "load case(s) is satisfiable OUTSIDE the defining case(s) -- a reset case is "
                                "only ever CHECKED on its own priority cube, which excludes the load cases, so "
                                "the load is what erases the obligation there and nothing at all is checked in "
                                "that part of the space", "vacuous")
                if cover not in ("verified", HOLD_COVER_UNDECIDED):
                    raise _Fail(f"unknown: whether the cubes the harness checked cover the hold region ({why})",
                                "budget" if why == "budget" else "unknown")
                if HOLD_MUST_BE_NONVACUOUS:
                    raise _Fail("vacuous: the hold region is empty and HOLD_MUST_BE_NONVACUOUS refuses every "
                                "empty hold region", "vacuous")
                # State only what was DECIDED (review[0] minor 6.1): the region whose unsatisfiability
                # this reports also conjoins the async-controls-inactive literals and the counter's
                # in-range literal, so the named cases are a hint, not the established cause.
                self.rep["checks"]["hold"] = \
                    f"vacuous (the hold region is empty; named case(s): {', '.join(named)})"
            elif r != "sat":
                raise _Fail(f"unknown: non-vacuity of the hold case ({r})", "budget" if r == "budget" else "unknown")
            else:
                self._obligations("hold", region, [(f, v.model[f]["ns"], 2 * v.flop_at[f].q) for f in self.flops])
        # Reset cases in list order, each on its own cube with the EARLIER cases and every load case
        # removed: list order is priority, exactly as an RTL if/else chain is, so the union of the
        # named reset cases is covered once and a case a higher-priority one shadows is vacuous.
        for i, (lits, vals) in enumerate(self.resets):
            name = "reset" if len(self.resets) == 1 else f"reset[{i}]"
            region = list(lits) + [self.land(self.resets[j][0]) ^ 1 for j in range(i)] + \
                [self.n_l] + self.async_off + list(dom)
            self._nonvacuous(name, region)
            self._obligations(name, region, [(f, v.model[f]["ns"], vals[f]) for f in self.flops])

    def _def_region(self, dom=()):
        return list(self.when) + [self.n_r, self.n_l] + self.async_off + list(dom)

    # --- counter ---------------------------------------------------------------------------------
    def _add_const(self, bits, K, n):
        sg = self.sg
        out, c = [], 0
        for i in range(n):
            a = bits[i] if i < len(bits) else 0
            kb = (K >> i) & 1
            out.append(sg.mk(_XOR3, [a, kb, c]))
            c = sg.mk(_MAJ, [a, kb, c])
        return out

    def _ge_const(self, bits, K):
        """value(bits) >= K (bits LSB first)."""
        if K <= 0:
            return 1
        if K >> len(bits):
            return 0
        sg = self.sg
        ge = 1
        for i, b in enumerate(bits):
            ge = sg.mk(_AND2, [b, ge]) if (K >> i) & 1 else sg.mk(_OR2, [b, ge])
        return ge

    def _mux_word(self, sel, x, y):
        return [self.sg.mk(_MUX, [sel, a, b]) for a, b in zip(x, y)]

    def _counter(self, lane, params, c, hold):
        v, rep = self.v, self.rep
        w = len(lane)
        if w > COUNTER_MAX_WIDTH:
            raise _Fail(f"counter wider than {COUNTER_MAX_WIDTH} bits", "template")
        if w < COUNTER_MIN_WIDTH:
            raise _Fail(f"counter width {w} < {COUNTER_MIN_WIDTH}: a 1-bit word is a toggle flop, not a "
                        "counter (its template is w' = not q, which every degenerate gate passes)", "template")
        if len(self.flops) != w:
            raise _Fail("a counter has one lane", "template")
        d = params.get("direction")
        if d not in ("up", "down", "updown"):
            raise _Fail(f"params.direction {str(d)[:20]!r} is not up, down or updown", "params")
        # What the harness can check of the params it must: "updown" without control.when_down proves
        # only the up half, and a when_down with any other direction is a case no template uses.
        if d == "updown" and self.when_down is None:
            raise _Fail('params.direction "updown" without control.when_down: the down half of the '
                        "claim would never be checked", "params")
        if d != "updown" and self.when_down is not None:
            raise _Fail(f'control.when_down with params.direction "{d}": only an updown counter has a '
                        "down case", "params")
        step = params.get("step")
        step = 1 if step is None else step
        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            raise _Fail("params.step must be a positive integer", "params")
        M = params.get("modulus")
        if M is not None and (isinstance(M, bool) or not isinstance(M, int) or not 2 <= M <= 1 << w):
            raise _Fail("params.modulus must be an integer in [2, 2^width]", "params")
        sat = params.get("saturating")
        sat = False if sat is None else sat
        if isinstance(sat, bool):
            top = (M - 1 if M is not None else (1 << w) - 1)
        elif isinstance(sat, int) and 1 <= sat < 1 << w:
            top, sat = sat, True
            # params.saturating carries the LIMIT, so the limit and not params.modulus is what the
            # template reads from here on -- the `if not sat` branch below is skipped and the
            # saturating branch uses only `top`. A declared modulus is then certified only when it
            # says the same thing (modulus - 1 == top); otherwise it is DEAD and must be reported
            # unchecked rather than certified (review[0] major 3: a 4-bit "counter up by 1,
            # saturating at 12" verified with params {saturating: 12, modulus: 3} and modulus in
            # params_checked). Refusing the disagreement would also be sound; marking it unchecked is
            # the conservative side and matches what _lfsr_params does with a param it cannot pin.
            if M is not None and M - 1 != top:
                self.uncertified.add("modulus")
                self.param_notes["modulus"] = (
                    f"not read: params.saturating carries the limit {top}, so the template saturates there and "
                    f"params.modulus {M} (limit {M - 1}) is never used")
        else:
            raise _Fail("params.saturating must be true, false or the saturation value", "params")
        if not sat:
            M = 1 << w if M is None else M
            top = M - 1
            if step >= M:
                raise _Fail("params.step must be below the modulus", "params")
        # width / modulus / limit coherence (schema v2): no claimed bit may be dead, so the range
        # must need every one of the w bits. This is what refuses a word padded with foreign flops
        # (48 bits declared with modulus 2^32: the range assumption pins the top 16 to 0) and the
        # degenerate saturating templates (a 1-bit saturating counter's word template is constant).
        if not (1 << (w - 1)) <= top < (1 << w):
            what = f"the saturation limit {top}" if sat else f"params.modulus {M}"
            raise _Fail(f"{what} does not match width {w}: it needs 2^(w-1) < modulus <= 2^w "
                        f"(limit >= 2^(w-1)), else the top bit(s) of the claimed word are dead", "template")
        # modulus is certified in every shape but the dead one marked above (self.uncertified wins)
        self.certified.add("modulus")
        inv_ids = c.get("inverted")
        inv = set()
        if inv_ids is not None:
            if not isinstance(inv_ids, list):
                raise Malformed("control.inverted must be a list of flop ids")
            for x in inv_ids:
                i = as_id(x)
                if i is None or i not in self.fset:
                    raise Malformed("control.inverted names a flop outside the structure")
                inv.add(i)
        val = [2 * v.flop_at[f].q ^ (f in inv) for f in lane]
        nxt = [v.model[f]["ns"] ^ (f in inv) for f in lane]
        dom = [] if top == (1 << w) - 1 else [self._ge_const(val, top + 1) ^ 1]
        if sat:
            up_sum = self._add_const(val, step, w + 1)
            over = self._ge_const(up_sum, top + 1)
            up = self._mux_word(over, [(top >> i) & 1 for i in range(w)], up_sum[:w])
            under = self._ge_const(val, step) ^ 1
            down = self._mux_word(under, [0] * w, self._add_const(val, (1 << w) - step, w))
            desc = f"saturating at {top} (up) / 0 (down)"
        elif M == 1 << w:
            up = self._add_const(val, step, w)
            down = self._add_const(val, (1 << w) - step, w)
            desc = f"mod 2^{w}"
        else:
            s1 = self._add_const(val, step, w + 1)
            wrap = self._ge_const(s1, M)
            up = self._mux_word(wrap, self._add_const(s1, (1 << (w + 1)) - M, w + 1)[:w], s1[:w])
            under = self._ge_const(val, step) ^ 1
            down = self._mux_word(under, self._add_const(val, M - step, w), self._add_const(val, (1 << w) - step, w))
            desc = f"mod {M}"
        rep["template"] = f"counter {d} by {step}, {desc}, width {w}" + (f", {len(inv)} inverted bits" if inv else "")
        main = down if d == "down" else up
        # A template that is constant or independent of the word over [0, top] proves nothing about
        # the flops: every flop forced to a constant by some condition would be such a "counter".
        # Arithmetic: w' = w +- step mod M is a bijection for M >= 2 (step < M is checked above),
        # while the saturating map min(w + step, top) / max(w - step, 0) is constant iff step >= top.
        if sat and step >= top:
            raise _Fail(f"the saturating template with step {step} and limit {top} is constant on [0, {top}]",
                        "template")
        for nm, tmpl in [("defining", main)] + ([("defining_down", down)] if d == "updown" else []):
            if all(x in (0, 1) for x in tmpl):
                raise _Fail(f"the {nm} counter template is constant: it says nothing about the word", "template")
            if not any(self.sg.supp_bits(x >> 1) & self.own_mask for x in tmpl if x >> 1):
                raise _Fail(f"the {nm} counter template does not depend on the structure's own word", "template")
        region = self._def_region(dom)
        self._defining_case("when", region, dom, val, top)
        self._liveness(region, val, main)
        extra_off = []
        down_region = None
        if d == "updown":
            down_region = list(self.when_down) + [self.land(self.when) ^ 1, self.n_r, self.n_l] + self.async_off + dom
            self._defining_case("when_down", down_region, dom, val, top)
            extra_off = [self.land(self.when_down) ^ 1]
        self._obligations("defining", region, [(f, nxt[i], main[i]) for i, f in enumerate(lane)])
        if down_region is not None:
            self._obligations("defining_down", down_region, [(f, nxt[i], down[i]) for i, f in enumerate(lane)])
        self._hold_reset(hold, extra_off, dom)
        if dom:
            rep["domain"] = self._domain_report(val, nxt, top, inv, lane, dom)

    def _liveness(self, region, val, tmpl):
        """EXTENT (schema v2.1): every claimed bit must MOVE somewhere in the defining region.
        Width / modulus / limit coherence does not bound the extent on its own, because a step of
        2^k makes the low k template bits the identity, so a real w-bit counter can be prepended
        with k foreign flops that merely hold under the defining case (and a word of 7 config bits
        and one counter bit verified as "counter up by 128, mod 2^8"). One holds() per bit: the
        identical case costs no SAT at all, "holds" means the bit is dead there, "refuted" is the
        witness that it moves. The live bits are reported so a consumer can see what was exercised."""
        live, dead = [], []
        for i, (a, b) in enumerate(zip(tmpl, val)):
            r, _how = self.holds(region, a, b)
            if r == "holds":
                dead.append(i)
            elif r == "refuted":
                live.append(i)
            else:
                raise _Fail(f"unknown: liveness of bit {i} ({r})", "budget" if r == "budget" else "unknown")
        self.rep["live_bits"] = live
        self.rep["dead_bits"] = dead
        if dead:
            raise _Fail(f"{len(dead)} of {len(val)} claimed bits never move in the defining region "
                        f"(bit(s) {dead[:6]}): a bit whose template is the identity there is dead, and a word "
                        "padded with flops that ride along is not a counter", "template")

    def _domain_report(self, val, nxt, top, inv, lane, dom):
        """Whether reset and load keep the word in [0, top] (information: S3_DESIGN 3.7's scope)."""
        out = {"top": top}
        if self.resets:
            out["reset_in_range"] = [sum((vals[f] ^ (f in inv)) << i for i, f in enumerate(lane)) <= top
                                     for _lits, vals in self.resets]
        if self.loads:
            out["load_in_range"] = []
            for l in self.loads:
                r = self.solve(list(l) + self.async_off + list(dom) + [self._ge_const(nxt, top + 1)])
                out["load_in_range"].append({"unsat": True, "sat": False}.get(r, r))
        return out

    # --- shift register and synchronizer -----------------------------------------------------------
    def _shift(self, lanes, params, hold):
        v, rep = self.v, self.rep
        depth = {len(l) for l in lanes}
        if len(depth) != 1:
            raise _Fail("shift lanes of unequal depth", "template")
        d = depth.pop()
        if d < SHIFT_MIN_DEPTH:
            raise _Fail(f"shift depth {d} < {SHIFT_MIN_DEPTH}", "template")
        for k, want in (("depth", d), ("lanes", len(lanes))):
            x = params.get(k)
            if x is not None and x != want:
                raise _Fail(f"params.{k} = {str(x)[:20]} but the order has {want}", "params")
        rep["template"] = f"shift register, {len(lanes)} lane(s) of depth {d}"
        region = self._def_region()
        self._defining_case("when", region)
        pairs = [(lane[k], v.model[lane[k]]["ns"], 2 * v.flop_at[lane[k - 1]].q) for lane in lanes
                 for k in range(1, d)]
        self._obligations("defining", region, pairs, polarity=True)
        self._hold_reset(hold)

    def _sync(self, lanes, params, c, hold):
        v, rep = self.v, self.rep
        depth = {len(l) for l in lanes}
        if len(depth) != 1:
            raise _Fail("synchronizer lanes of unequal depth", "template")
        d = depth.pop()
        if d < SYNC_MIN_STAGES:
            raise _Fail(f"synchronizer depth {d} < {SYNC_MIN_STAGES}: one flop registering a net is the "
                        "input register whose metastability a synchronizer's second stage absorbs, not a "
                        "synchronizer", "template")
        x = params.get("stages")
        if x is not None and x != d:
            raise _Fail(f"params.stages = {str(x)[:20]} but the order has {d}", "params")
        if self.when:
            raise _Fail("a synchronizer has no condition: control.when must be empty", "template")
        if self.loads:
            raise _Fail("a synchronizer has no load case", "template")
        inp = c.get("input")
        if inp is None:
            raise _Fail("control.input is missing (the net stage 0 samples)", "template")
        inps = inp if isinstance(inp, list) else [inp]
        if len(inps) != len(lanes):
            raise Malformed(f"control.input gives {len(inps)} nets for {len(lanes)} lanes")
        g = v.g
        heads = []
        for x in inps:
            lit = v.net_lit(x)
            s = lit >> 1
            k = g.kind[s]
            ok = k in (INPUT, BBOX) or (k == FREE and (g.info[s] or ("",))[0] == "latch")
            if k == FLOP:
                f = v.flop_at[g.flops[g.q2flop[s]].cell]
                ok = f.cell not in self.fset and v.model[f.cell]["domain"] != self.domain
            if not ok:
                raise _Fail("the synchronizer input is not a primary input, black-box output, latch output or "
                            "flop of another clock domain", "template")
            heads.append(lit)
        rep["template"] = f"synchronizer, {len(lanes)} lane(s) of {d} stage(s)"
        region = self._def_region()
        self._defining_case("when", region)
        pairs = []
        for lane, h in zip(lanes, heads):
            pairs.append((lane[0], v.model[lane[0]]["ns"], h))
            pairs += [(lane[k], v.model[lane[k]]["ns"], 2 * v.flop_at[lane[k - 1]].q) for k in range(1, d)]
        self._obligations("defining", region, pairs, polarity=True)
        self._hold_reset(hold)

    # --- lfsr / crc --------------------------------------------------------------------------------
    def _lfsr(self, s, c, hold, lanes):
        v, rep = self.v, self.rep
        g = v.g
        inputs = c.get("inputs", [])
        inputs = [] if inputs is None else inputs
        if not isinstance(inputs, list) or len(inputs) > FLOPS_PER_STRUCTURE:
            raise Malformed("control.inputs must be a list of net ids")
        in_lit = {}
        for x in inputs:
            i = as_id(x)
            lit = v.net_lit(x)
            if i in in_lit:
                raise Malformed("control.inputs lists a net twice")
            if g.supp_bits(lit >> 1) & self.own_mask:
                raise _Fail("a control.inputs net depends on the structure's own state", "form")
            in_lit[i] = lit
        claims = (s.get("proof") or {}).get("claims") if isinstance(s.get("proof"), dict) else None
        if not isinstance(claims, list):
            raise _Fail("no claims: an lfsr_crc gives each flop's next state", "form")
        wset = {(as_id(x.get("net")), x.get("value")) for x in (c.get("when") or []) if isinstance(x, dict)}
        forms = {}
        extra = 0
        for cl in claims:
            if not isinstance(cl, dict) or cl.get("type") != "next":
                raise Malformed("an lfsr_crc claim must be {type: next, flop, equals}")
            role = cl.get("role", "defining")
            if role != "defining":
                if role not in ROLES:
                    raise Malformed(f"claim role {str(role)[:20]!r}")
                extra += 1
                continue
            f = v.flop(cl.get("flop")).cell
            if f not in self.fset:
                raise Malformed("a claim names a flop outside the structure")
            if f in forms:
                raise Malformed("two defining claims for one flop")
            cw = cl.get("when")
            if cw:
                if not isinstance(cw, list) or {(as_id(x.get("net")) if isinstance(x, dict) else None,
                                                 x.get("value") if isinstance(x, dict) else None) for x in cw} != wset:
                    raise _Fail("an lfsr_crc claim's own 'when' differs from control.when", "form")
            if "equals" not in cl:
                raise Malformed("claim without 'equals'")
            forms[f] = self._xor_form(cl["equals"], in_lit)
        rep["extra_claims"] = extra
        missing = [f for f in self.flops if f not in forms]
        if missing:
            raise _Fail(f"{len(missing)} of {len(self.flops)} flops have no defining claim", "form")
        rows = [forms[f][0] for f in self.flops]
        wmax = max(len(r) for r in rows)
        cols = collections.Counter(x for r in rows for x in r)
        perm = all(len(r) == 1 for r in rows) and len(cols) == len(rows) and all(n == 1 for n in cols.values())
        zero = [f for f, r in zip(self.flops, rows) if not r]
        dead = [f for f in self.flops if f not in cols]
        self_only = [f for f, r in zip(self.flops, rows) if r == {f}]
        # The own-bit matrix bounds the structure's extent. Read it as a digraph j -> i when row i
        # reads column j: strong connectivity refuses a zero row (nothing reaches it: an opaque
        # restatement of that flop's D), a dead column (it reaches nothing: a passenger bit) AND the
        # weight-1 SELF row the v2.0 gates missed, which is a foreign flop that merely holds under
        # control.when carried along with {"equals": {"q": itself}} -- measured on TEMPO, 264 of its
        # 2,832 flops hold under lfsr0's when and any of them extended the verified 32-bit CRC. It
        # also refuses an appended sub-LFSR that nothing in the real word reads.
        idx = {f: i for i, f in enumerate(self.flops)}
        adj = [[] for _ in self.flops]
        for i, f in enumerate(self.flops):
            for x in rows[i]:
                adj[idx[x]].append(i)
        sc = _strongly_connected(adj, len(self.flops))
        rep["own_matrix"] = {"max_row_weight": wmax, "zero_rows": len(zero), "permutation": perm,
                             "dead_columns": len(dead), "self_only_rows": len(self_only),
                             "strongly_connected": sc,
                             "inputs_used": len({x for f in self.flops for x in forms[f][1]})}
        if not sc:
            if zero:
                raise _Fail(f"{len(zero)} of {len(rows)} claims read no own bit (e.g. flop {zero[0]}): an LFSR "
                            "bit's next state is an XOR of own bits; a bare input net restates that flop's D",
                            "form")
            if dead:
                raise _Fail(f"{len(dead)} of {len(rows)} flops are read by no claim (e.g. flop {dead[0]}): a dead "
                            "column is a passenger bit, not part of the LFSR", "form")
            raise _Fail(f"the own-bit matrix is not strongly connected over the structure's flops "
                        f"({len(self_only)} flop(s) whose only own reference is themselves, e.g. "
                        f"{(self_only or [None])[0]}): a bit that no cycle of the recurrence reaches rides "
                        "along, it is not part of the LFSR", "form")
        if wmax < 2:
            raise _Fail("the own-bit matrix is a (partial) permutation: a shift or copy, not an LFSR", "form")
        rep["template"] = f"lfsr_crc, {len(self.flops)} bits, {len(in_lit)} input net(s)"
        self._lfsr_params(s, forms, lanes)
        region = self._def_region()
        self._defining_case("when", region)
        pairs = []
        for f in self.flops:
            own, ins, k = forms[f]
            leaves = [2 * v.flop_at[x].q for x in own] + [in_lit[x] for x in ins]
            e = self.lit_tree(_XOR2, leaves, 0) ^ k
            pairs.append((f, v.model[f]["ns"], e))
        stop = frozenset(l >> 1 for l in in_lit.values())
        self._obligations("defining", region, pairs, stop=stop, xor_claim=True)
        self._hold_reset(hold)

    def _lfsr_params(self, s, forms, lanes):
        """Certify params.poly / k_steps / n_inputs against the own matrix where the form admits it.

        The matrix A is read in STAGE coordinates -- params.bit_order / "order", which is what
        tools/s3/lfsr.py emits (by_stage) -- so A[i] is the set of stages stage i's claim XORs. Its
        one-step Galois companion is C e_j = e_(j-1), C e_0 = t, and a k-step word satisfies
        A == C^k (Galois reading) or A == (C^k)^T (Fibonacci reading, the same matrix transposed).
        Two exact readings, no search:
          * a ONE-STEP shape is read straight off A (t_i = "stage i also reads stage 0" for Galois,
            or A[0] itself for Fibonacci), giving poly and k_steps = 1;
          * any declared (poly, k_steps) pair is CHECKED by building C and raising it to the power,
            in both readings and with the polynomial written with or without its x^w bit.
        Anything else -- a programmable polynomial, form "affine", k_steps null with a matrix that is
        not one step -- is left unchecked and said to be unchecked. The lfsr's `form` is never a
        refusal: which of two readings of one matrix to report is a convention (lfsr.py's "both").

        This is ALSO the only thing in the module that constrains params.bit_order for an lfsr_crc
        (_lfsr's obligations are per-flop EXPRs and never read the order), so bit_order is certified
        HERE and only when the stage order was actually PINNED -- `recon` exists, or a declared
        (poly, k_steps) pair matched -- and never by PARAMS_CHECKED (review[0] blocker 1: a real
        Galois CRC-16 declared with a scrambled bit_order verified with bit_order "certified", the
        reconstruction having not run at all). A match in the "reversed" orientation reads the same
        matrix from the other end of the stage chain, so it pins the order only UP TO REVERSAL, and
        the report says which orientation matched. More precisely, what "pinned" claims is that the
        DECLARED order is one in which the own matrix is a companion power of the polynomial: it is
        structural evidence about the order (a scrambled order is not), not a proof that no other
        order is, and the two orientations are the pair the harness itself knows of."""
        rep, params = self.rep, (s.get("params") or {})
        info = {"checked": [], "unchecked": []}
        stages = lanes[0] if lanes and len(lanes) == 1 and len(lanes[0]) == len(self.flops) else None
        p_poly, p_k, p_n = params.get("poly"), params.get("k_steps"), params.get("n_inputs")
        n_used = len({x for f in self.flops for x in forms[f][1]})
        if stages is None or len(stages) > LFSR_PARAM_MAX_WIDTH:
            info["reason"] = ("no single-lane stage order (params.bit_order): the matrix has no stage "
                              "coordinates" if stages is None else
                              f"wider than {LFSR_PARAM_MAX_WIDTH} bits: the reconstruction is not run")
            info["unchecked"] = [k for k in ("poly", "k_steps", "n_inputs") if params.get(k) is not None]
            info["bit_order_pinned"] = False            # the reconstruction that pins it does not run
            self.uncertified.add("bit_order")
            if params.get("bit_order") is not None:
                info["unchecked"].append("bit_order")
                self.param_notes["bit_order"] = "not pinned: " + info["reason"]
            rep["lfsr_params"] = info
            return
        w = len(stages)
        # Two orientations of one stage order. Reversing the stages maps a Galois companion to
        # another companion, and the development data uses both: the generalisation reference's
        # crc32c_d32_sr matches on the stage order as given, crc16_d16_ar only on its reverse. Which
        # end of a stage chain is stage 0 is a convention nothing in the netlist fixes (the same
        # convention risk tools/s3/lfsr.py records for form "both" and for pin-selected polynomials),
        # so both are accepted -- 8 candidate matrices in all against one own matrix, which still
        # refuses an invented polynomial.
        mats = {}
        for tag, order in (("stage", stages), ("reversed", list(reversed(stages)))):
            pos = {f: i for i, f in enumerate(order)}
            mats[tag] = [0] * w
            for f in self.flops:
                mats[tag][pos[f]] = sum(1 << pos[x] for x in forms[f][0])
        bad = None

        def match(P):
            """Which (orientation, reading) the matrix P (a companion power) is the own matrix in."""
            PT = _mat_t(P, w)
            for tag, A in mats.items():
                if P == A:
                    return tag, "galois"
                if PT == A:
                    return tag, "fibonacci"
            return None

        # A ONE-STEP shape, read straight off the matrix in either orientation. Reported whenever it
        # exists, and it is what a structure that declares no (poly, k_steps) pair is compared with.
        recon = None
        for tag, A in mats.items():
            g_t = sum(1 << i for i in range(w) if A[i] & 1)
            if _companion(g_t, w) == A:
                recon = (tag, "galois", g_t)
                break
            f_t = A[0]
            if _mat_t(_companion(f_t, w), w) == A:
                recon = (tag, "fibonacci", f_t)
                break
        if recon is not None:
            info.update(one_step=True, orientation=recon[0], reading=recon[1],
                        reconstructed_poly=_poly_of_taps(recon[2], w), reconstructed_k_steps=1)
        an_int = (lambda x: isinstance(x, int) and not isinstance(x, bool))
        # A w-bit LFSR's polynomial has degree w, so it fits in w + 1 bits. Checking this FIRST is
        # load-bearing: without it a wholly invented value can still match once it is reflected,
        # because the reflection would read only its low w + 1 bits (the review's P2 poly 12345 on a
        # 4-bit LFSR reflects to 0x13, the right polynomial, out of its low five bits alone).
        if an_int(p_poly) and not 0 <= p_poly < (1 << (w + 1)):
            info["checked"].append("poly")
            bad = (f"params.poly {p_poly:#x} does not fit a degree-{w} polynomial (at most {w + 1} bits), "
                   f"so it is not this structure's")
            p_poly = None
        if an_int(p_poly) and an_int(p_k) and 1 <= p_k <= LFSR_PARAM_MAX_K:
            # The DECLARED pair, checked exactly: A == C^k in some orientation and reading. This runs
            # even when the matrix is also a one-step companion, because C^k can itself have the
            # companion shape for some k -- comparing such a matrix with the one-step reading alone
            # would refuse a correct (poly, k_steps) pair.
            hit = None
            for poly in sorted(_poly_variants(p_poly, w)):
                hit = match(_mat_pow(_companion(_taps_of_poly(poly, w), w), p_k, w))
                if hit:
                    info["poly_as_read"] = poly
                    break
            info["checked"] += ["poly", "k_steps"]
            if hit:
                info.update(checked_orientation=hit[0], checked_reading=hit[1], k_effective=p_k)
            else:
                bad = (f"params.poly {p_poly:#x} raised to params.k_steps {p_k} is not the own matrix in "
                       "either the Galois or the Fibonacci reading, in either stage orientation")
                if recon is not None:
                    bad += (f"; its one-step {recon[1]} companion ({recon[0]} stage order) has polynomial "
                            f"{info['reconstructed_poly']:#x} "
                            f"(reflection {_reciprocal(info['reconstructed_poly'], w):#x}) at k_steps 1")
        elif recon is not None:
            # only one of the pair is declared: compare it with the one-step reading
            info["k_effective"] = 1
            if an_int(p_poly):
                info["checked"].append("poly")
                if p_poly not in _poly_variants(info["reconstructed_poly"], w):
                    bad = (f"params.poly {p_poly:#x} contradicts the own matrix, whose one-step "
                           f"{recon[1]} companion ({recon[0]} stage order) has polynomial "
                           f"{info['reconstructed_poly']:#x} "
                           f"(reflection {_reciprocal(info['reconstructed_poly'], w):#x})")
            elif p_poly is not None:
                info["unchecked"].append("poly")
            if an_int(p_k):
                info["checked"].append("k_steps")
                if p_k != 1:
                    bad = bad or (f"params.k_steps {p_k} contradicts the own matrix, which is a one-step "
                                  f"{recon[1]} companion (k_steps 1) and carries no polynomial to raise")
            elif p_k is not None:
                info["unchecked"].append("k_steps")
        else:
            info["reason"] = "the matrix is not a one-step companion and params give no (poly, k_steps) pair"
            info["unchecked"] += [k for k in ("poly", "k_steps") if params.get(k) is not None]
        # n_inputs is exact only at one step per clock: then it is the data bits entering per step
        if info.get("k_effective") == 1 and an_int(p_n):
            info["checked"].append("n_inputs")
            if p_n != n_used:
                bad = bad or (f"params.n_inputs {p_n} but the claims read {n_used} of control.inputs at one "
                              "step per clock")
        elif p_n is not None:
            info["unchecked"].append("n_inputs")
        if params.get("form") is not None:
            info["unchecked"].append("form")
        # params.bit_order: certified only where the stage order was pinned (see the docstring).
        # `recon` is the one-step reading of the matrix in a named orientation; `checked_orientation`
        # is set when a DECLARED (poly, k_steps) pair matched. Either pins the order up to the
        # orientation that matched; neither leaves it a transcription.
        pin = info.get("checked_orientation") or info.get("orientation")
        if pin and not bad:
            info["bit_order_pinned"] = pin
            if pin == "reversed":
                info["bit_order_note"] = ("the match is in the REVERSED stage orientation, so the order is "
                                          "pinned only up to reversal (which end of a stage chain is stage 0 "
                                          "is a convention nothing in the netlist fixes)")
            self.certified.add("bit_order")
            if params.get("bit_order") is not None:
                info["checked"].append("bit_order")
                self.param_notes["bit_order"] = \
                    f"pinned by the polynomial reconstruction (stage orientation: {pin})" + \
                    (", i.e. only up to reversal" if pin == "reversed" else "")
        else:
            info["bit_order_pinned"] = False
            self.uncertified.add("bit_order")
            if params.get("bit_order") is not None:
                info["unchecked"].append("bit_order")
                self.param_notes["bit_order"] = (
                    "not pinned: nothing in an lfsr_crc's obligations reads the stage order, and the polynomial "
                    "reconstruction that would pin it did not run or did not match, so the declared order is "
                    "transcribed, not certified")
        info["inputs_used"] = n_used
        rep["lfsr_params"] = info
        if bad:
            info["contradiction"] = bad
            if LFSR_PARAM_CHECK:
                raise _Fail(f"params: {bad}", "params")

    def _xor_form(self, e, in_lit):
        """(own flops, input nets, constant) of an XOR-form EXPR; odd multiplicities kept."""
        own, ins, k = set(), set(), 0
        stack = [(e, 0)]
        n = 0
        while stack:
            x, d = stack.pop()
            n += 1
            if n > EXPR_NODES or d > EXPR_DEPTH:
                raise Malformed("EXPR too large or too deep")
            if not isinstance(x, dict) or len(x) != 1:
                raise Malformed(f"EXPR must be a one-key object: {str(x)[:60]!r}")
            (op, a), = x.items()
            if op == "q":
                f = self.v.flop(a).cell
                if f not in self.fset:
                    raise _Fail("an lfsr_crc EXPR reads a flop outside the structure (give it as an input net)",
                                "form")
                own ^= {f}
            elif op == "net":
                i = as_id(a)
                if i is None or i not in in_lit:
                    raise _Fail("an lfsr_crc EXPR reads a net not in control.inputs", "form")
                ins ^= {i}
            elif op == "const":
                if isinstance(a, bool) or a not in (0, 1):
                    raise Malformed("const must be 0 or 1")
                k ^= a
            elif op == "not":
                k ^= 1
                stack.append((a, d + 1))
            elif op == "xor":
                if not isinstance(a, list) or not a:
                    raise Malformed("xor needs a non-empty list")
                stack.extend((y, d + 1) for y in a)
            elif op in ("and", "or"):
                raise _Fail("an lfsr_crc EXPR is not an XOR of own q's, inputs and constants", "form")
            else:
                raise Malformed(f"unknown EXPR operator {str(op)[:20]!r}")
        return frozenset(own), frozenset(ins), k


# ----------------------------------------------------------------------------------------------
# legacy claim sets (corpus.py) and the result


def _legacy_structure(ver, s, budget):
    """v1: every claim holds and every flop has a verified 'defining' claim. Not a structure verdict."""
    rep = {"verified": False, "reason": "", "claims": [], "n_claims": 0, "claims_verified": 0,
           "missing_defining": [], "defining_internal_net": 0, "id": str(s.get("id"))[:80]}
    try:
        _json_check(s)
    except Malformed as e:
        rep["reason"] = f"malformed: {e}"
        return rep
    flops = s.get("flops")
    proof = s.get("proof") if isinstance(s.get("proof"), dict) else {}
    claims = proof.get("claims")
    if not isinstance(flops, list) or not flops:
        rep["reason"] = "no flops"
        return rep
    if not isinstance(claims, list) or not claims:
        rep["reason"] = "no claims"
        return rep
    rep["n_claims"] = len(claims)
    if len(claims) > CLAIMS_PER_STRUCTURE:
        rep["reason"] = f"budget: {len(claims)} claims > {CLAIMS_PER_STRUCTURE} per structure"
        return rep
    defined = set()
    for j, c in enumerate(claims):
        if budget[0] <= 0:
            rep["reason"] = "budget: claims per run"
            return rep
        budget[0] -= 1
        r = ver.check_claim(c)
        rep["claims"].append({"verified": r["verified"], "reason": r["reason"]})
        if not r["verified"]:
            rep["reason"] = f"claim {j}: {r['reason']}"
            return rep
        rep["claims_verified"] += 1
        if r.get("role") == "defining":
            defined.add(r["flop"])
            rep["defining_internal_net"] += r.get("internal_net", False)
    missing = [x for x in flops if as_id(x) not in defined]
    if missing:
        rep["missing_defining"] = [str(x)[:40] for x in missing[:10]]
        rep["reason"] = f"{len(missing)} of {len(flops)} flops have no verified defining claim"
        return rep
    rep["verified"], rep["reason"] = True, "verified"
    return rep


def verify_structure(ver, s, budget=None):
    """One structure's verdict (v2). A structure without "kind" is a v1 claim set (corpus.py's own
    checks): `budget` is then a one-element list of claims left."""
    if isinstance(s, dict) and "kind" not in s:
        return _legacy_structure(ver, s, budget if budget is not None else [CLAIMS_PER_RUN])
    return ver.verify(s)


def _claimed(s):
    return isinstance(s, dict) and isinstance(s.get("proof"), dict) and s["proof"].get("status") == "proven"


def verify_result(nl, result, conflicts=CONFLICTS_PER_CHECK, conflicts_total=CONFLICTS_PER_RUN,
                  self_conditions_allowed=SELF_CONDITIONS_ALLOWED):
    """Verify every structure of a result (opaque ids of `nl`). Returns {"schema", "limits",
    "model", "structures": [per-structure verdict, in result order], "summary", "seconds"}."""
    t0 = time.perf_counter()
    structs = result.get("structures") if isinstance(result, dict) else None
    structs = structs if isinstance(structs, list) else []
    ver = Verifier(nl, conflicts, conflicts_total, self_conditions_allowed)
    out = []
    for i, s in enumerate(structs):
        if i >= STRUCTURES_PER_RUN:
            out.append({"id": None, "kind": None, "scored": False, "verified": False, "bucket": "budget",
                        "reason": f"not checked: more than {STRUCTURES_PER_RUN} structures", "sha256": None})
            continue
        out.append(ver.verify(s))
    by_kind = {k: [0, 0] for k in schema.STRUCTURE_KINDS}
    for r in out:
        if r.get("scored") and r["kind"] in by_kind:
            by_kind[r["kind"]][1] += 1
            by_kind[r["kind"]][0] += r["verified"]
    flags = [r["verified"] for r in out]
    summary = {
        "structures": len(out), "scored_structures": sum(1 for r in out if r.get("scored")),
        "verified": sum(flags), "verified_by_kind": by_kind,
        "unscored_structures": sum(1 for r in out if r.get("kind") and not r.get("scored")),
        "claimed_proven": sum(1 for s in structs if _claimed(s)),
        "claimed_proven_not_verified": sum(1 for s, f in zip(structs, flags) if _claimed(s) and not f),
        "verified_not_claimed_proven": sum(1 for s, f in zip(structs, flags) if f and not _claimed(s)),
        "verified_self_conditioned": sum(1 for r in out if r["verified"] and any(
            v for k, v in (r.get("self_conditioned") or {}).items() if k != "state_literals")),
        "verified_vacuous_hold": sum(1 for r in out if r["verified"] and r.get("hold_vacuous")),
        # the hold/load evidence a consumer must read beside "verified" (review[0] major 2): how many
        # structures were REFUSED because their load cases are what emptied the hold region, and the
        # largest share of the state space any verified structure's load cases hide.
        "hold_emptied_by_load": sum(1 for r in out if r.get("hold_vacuous_cover") == "load"),
        "verified_load_hidden_share_max": max(
            [r.get("load_hidden_share", 0.0) for r in out if r["verified"]] or [0.0]),
        "legacy_control_form": sum(1 for r in out if r.get("control_form") == "legacy"),
        "multi_case_structures": sum(1 for r in out if max((r.get("cases") or {}).get("reset", 0),
                                                           (r.get("cases") or {}).get("load", 0)) > 1),
        "verified_with_unchecked_params": sum(1 for r in out if r["verified"] and r.get("params_unchecked")),
        "verified_lfsr_poly_certified": sum(1 for r in out if r["verified"] and r["kind"] == "lfsr_crc"
                                            and "poly" in (r.get("params_checked") or ())),
        "claims": sum(r.get("n_claims", 0) for r in out),
        "reasons": dict(collections.Counter(r["bucket"] for r in out).most_common()),
        "conflicts_used": ver.conflicts_total - ver.conflicts_left,
        "coverage_calls_used": COVERAGE_CALLS_PER_RUN - ver.coverage_calls_left,
        "coverage_checked": sum(1 for r in out if any(
            (x or {}).get("status") == "covered" for x in (r.get("coverage") or {}).values())),
        **{k: int(v) for k, v in sorted(ver.stats.items())}}
    return {"schema": VERIFY_SCHEMA, "contract": CONTRACT,
            "limits": {"conflicts_per_check": conflicts, "conflicts_per_run": conflicts_total,
                       "expr_nodes": EXPR_NODES, "expr_depth": EXPR_DEPTH, "cond_literals": COND_LITERALS,
                       "json_nodes": JSON_NODES, "json_depth": JSON_DEPTH, "structures_per_run": STRUCTURES_PER_RUN,
                       "flops_per_structure": FLOPS_PER_STRUCTURE, "counter_max_width": COUNTER_MAX_WIDTH,
                       "counter_min_width": COUNTER_MIN_WIDTH, "sync_min_stages": SYNC_MIN_STAGES,
                       "shift_min_depth": SHIFT_MIN_DEPTH, "affine_cut": AFFINE_CUT,
                       "coverage_max_own_bits": COVERAGE_MAX_OWN_BITS,
                       "hold_must_be_nonvacuous": HOLD_MUST_BE_NONVACUOUS,
                       "hold_empty_needs_verified_cover": HOLD_EMPTY_NEEDS_VERIFIED_COVER,
                       "coverage_calls_per_run": COVERAGE_CALLS_PER_RUN,
                       "hold_required_kinds": list(HOLD_REQUIRED_KINDS),
                       "reset_cases_max": RESET_CASES_MAX, "load_cases_max": LOAD_CASES_MAX,
                       "lfsr_param_max_width": LFSR_PARAM_MAX_WIDTH, "lfsr_param_max_k": LFSR_PARAM_MAX_K,
                       "legacy_control_form": LEGACY_CONTROL_FORM, "lfsr_param_check": LFSR_PARAM_CHECK,
                       "self_conditions_allowed": self_conditions_allowed},
            "model": {"flops": len(ver.g.flops), "model_s": ver.model_s},
            "structures": out, "structures_sha256": _sha([r.get("sha256") for r in out]),
            "summary": summary, "seconds": round(time.perf_counter() - t0, 3)}


def replay(nl, result, report, **kw):
    """Re-verify a recorded result on the recorded netlist and compare with the recorded report:
    [(index, field, recorded, now)] for every difference in sha256, verified or reason."""
    now = verify_result(nl, result, **kw)
    diffs = []
    old = report.get("structures") or []
    if len(old) != len(now["structures"]):
        diffs.append((None, "structures", len(old), len(now["structures"])))
    for i, (a, b) in enumerate(zip(old, now["structures"])):
        for k in ("sha256", "verified", "reason"):
            if a.get(k) != b.get(k):
                diffs.append((i, k, a.get(k), b.get(k)))
    return diffs
