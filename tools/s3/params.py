"""S3 recognizer parameters (the S3 design doc, section 3.8): every threshold the recognizer
modules use, each with a short justification. None names a width, a modulus, a polynomial or
anything else of a particular design; measurements cited as M<n> are the design doc's section 3.0
table (development set and synthetic corpus only).

A caller may override any of them for a single run: controls.analyze(nl, params={"N_MIN": 32});
the recognizers read them through the control layer (ctl.P). Two groups are fixed for every run
(NOT_PER_RUN): the netlist core's budgets (the netlist module reads them at import; the harness
builds its GateGraph with the same module) and the harness limits the recognizers mirror (HARNESS_*).

The blocks after the SAT budgets were moved here from the modules' own threshold blocks on
2026-09-22 (integration; the S3 change log says, per value, whether it was chosen on the
development design, on the synthetic corpus or with the generalisation regression set in view).
Every value is the module's value as delivered; nothing was retuned in the move.

Provenance, per BLOCK (a reporting review of 2026-09-22 found the promise above covered only the
moved blocks):
  * lane pool, reset, literal classes and witnesses, control classes and profiles, copy relations,
    the recognizers' own constants and the SAT budgets (every block down to "netlist core"): these
    are the design's own section 3.8 values plus the values the control layer added for them. The
    change log now carries one entry per value: C38.<NAME> for each of the nineteen that were in
    neither section 3.8 nor the earlier log (C38.RESET_NEAR has its own entry: it was chosen
    around one measurement of the development design), and C39 for the seventeen section 3.8
    states in prose, unchanged since the design. Five of the nineteen -- CASE_ROUNDS, CASE_TRIES,
    CASE_MIN_LANES, BLOCK_CUT_SHARE and MUX_LEGS -- have NO recorded selection set at all; their
    entries say so rather than guessing one.
  * netlist core and HARNESS_*: budgets and mirrors of the harness, C18's table.
  * the blocks after the SAT budgets: C18's per-threshold table, as above.
  So every uppercase name in this file now has an entry; the freeze checklist does not check that,
  but the parameter-coverage record written beside this round's reporting output does.

EVERY RECOGNIZER THRESHOLD IS NOW IN THIS FILE (integration round of 2026-09-22, second pass). The
second round's four hardening agents left marked blocks of their own in the control-layer module (the
clock-gate fold and the mode selector), the shift module (the lane-decomposition tie-break), the
counter module (the case-selected step, the quiescent/awake rule, the coverage obligation and the
hold repairs) and the LFSR module (the wide closed word, the pin-selected polynomial and the
own-matrix gate); all of them are here now, in their sections, with one change-log entry each
(C48-C58) and nothing retuned in the move. The modules' own NEW_THRESHOLDS / _NEW / NEW_LOCAL
registries are gone: they read these through ctl.P, DEFAULTS and LOCAL like every other value, so
recognize.split_params validates and routes an override of any of them.

THE HARNESS IS THE ONE EXCEPTION, deliberately. The harness module keeps the live copy of every
limit the HARNESS_* group mirrors below (CLOCK_SUPPORT, COVERAGE_MAX_OWN_BITS, COVERAGE_CALLS_PER_RUN,
HOLD_MUST_BE_NONVACUOUS and, from 2026-09-23, HOLD_EMPTY_NEEDS_VERIFIED_COVER) and does not import
this file: the harness may not
take its limits from the recognizer's parameter file, which a run may override and which is copied
into the recognizer's sandbox. The mirror is what the recognizers read, it is NOT_PER_RUN, and a test
of the harness suite (test_params_mirror_matches_the_harness) fails if the two ever drift.
"""

# --- lane pool (section 3.1) --------------------------------------------------------------------
POOL_LANES = 16384        # initial random lanes: 256 words; a whole-design pass costs ~30 ms on the dev set
POOL_CAP = 49152          # lanes including every witness lane: ~125 MB of bitsets for a 20k-signal graph
BIASES = (1 / 8, 1 / 2, 7 / 8)   # per source and 64-lane word: deep AND/OR conditions still get lanes
RESET_FREE_EVERY = 16     # 1 pool lane in 16 keeps the reset's support random (reset active there)
WL_ROUNDS = 4             # structural-hash rounds for pool seeds (labels stop splitting after ~4 on the dev set)
POOL_SALT = 0             # pool salt; the same salt and netlist give identical lanes under any id permutation

# --- reset (section 3.1, M3) --------------------------------------------------------------------
RESET_SYNC_FRAC = 0.25    # a synchronous reset literal must force >= 25 % of next states (F3), else the async class
RESET_NEAR = 0.9          # literals forcing >= 90 % of the best count compete; widest support wins (M3: the OR gate)
RESET_CHUNK_WORDS = 64    # ternary forcing pass: 4,096 forced literals per pass
RESET_WITNESSES = 8       # distinct inactive assignments of the reset's support used to pin lanes

# --- literal classes and witnesses (section 3.1, M4, M5) ------------------------------------------
CLASS_DEPTH = 4           # literal classes cover each flop's depth-4 next-state cone (12.7 gates, 16.7 leaves, M-table)
FRAIG_ROUNDS = 3          # sweep rounds; counterexamples become lanes between rounds
N_MIN = 64                # a literal or word with fewer lanes (either polarity) gets SAT witnesses (M4)
WITNESS_LANES = 16        # lanes per literal witness: witness on the literal's support, the rest random
WITNESS_BATCH = 64        # witnesses simulated together before rarity is recounted
CASE_WITNESSES = 64       # at most 64 case-conditioned witnesses per word, each blocked after use (M5)
CASE_ROUNDS = 8           # rounds of the rare-flop pre-pass (each gives every rare word <= 16 lanes)
CASE_TRIES = 64           # random lanes tried per case witness; the active ones are kept (<= WITNESS_LANES)

# --- control classes and profiles (section 3.2, F0, F13, M1, M2) ---------------------------------
CONTROL_MIN_FLOPS = 2     # a control class resets or holds >= 2 flops (F0, F13)
CONTROL_EVIDENCE = 8      # a relation counts only if a chance miss is unlikely: expected coincidences >= 8 (e^-8)
CONFIRM_CONTROLS = True   # SAT-confirm each control class's relations (one miter per class); refuted ones drop
COVER_CAP = 6             # hold and set covers: <= 6 literals each (design: 4; dev set: 4 broad classes fill a FIFO LSB's cap, 6 recovers 6/6 FIFO enables)
CASE_DEPTH = 4            # case literals come from the depth-4 cone of f_i (section 3.2)
CASE_CAP = 4              # at most 4 case literals per 'other' flop
CASE_MIN_LANES = 16       # a case literal needs >= 16 lanes of the flop's uncovered live lanes
AFFINE_MAX_SUPP = 64      # affine template tried only for supports of <= 64 sources (Gaussian elimination)
BLOCK_CUT_SHARE = 0.5     # SCC blocks: cut at cover literals shared by >= half the SCC (a common enable, a done flag)
AFFINE_SAMPLE = 512       # lanes used to solve the affine system before checking it on every lane

# --- copy relations (section 3.3, F2, M8, M9) -----------------------------------------------------
COPY_DEPTH = 6            # transparency conditions for sources within 6 gate levels of f_i (dev-set copies: 1-5)
COPY_WITNESS = True       # a transparency condition with < N_MIN lanes gets SAT witnesses of its own (F2)
COPY_WITNESS_MAX = 1024   # at most this many transparency-condition witnesses per run (pool cap guard)
GROUP_MAX_DENSITY = 0.5   # copy groups: conditions on > half the live lanes do not discriminate co-occurrence
GROUP_HASHES = 24         # copy groups: min-hashes per condition (random lane-word orders) ...
GROUP_BAND = 3            # ... in bands of 3: a pair of Jaccard 0.35 (dev-set byte shift) meets in a band w.p. 0.3
GROUP_BUCKET_MAX = 400    # min-hash buckets larger than this are ignored (dense conditions collide by chance)
GROUP_OVERLAP = 0.25      # similar conditions: |A & B| >= 1/4 of the smaller (dev-set byte shift: 0.5-0.6) ...
GROUP_LIFT = 4            # ... and >= 4x the overlap of independent conditions of the same densities
GROUP_REL_LIFT = 0.5      # ... or >= half the largest lift attainable (1/density): synthetic one-hot shift, lift 1.8-2.4
GROUP_KEEP = 0.5          # a group grows while the next member keeps >= half of the group condition's lanes
GROUP_SHARE = 0.1         # ... and the group condition holds on >= 10 % of the member's own lanes (dev-set byte shift: 17 %)
CHAIN_TOP_SLACK = 2       # a chain may run 2 flops past WORD_CAP (flops reading the word sit on top)
CHAIN_PER_LSB = 4         # nested-support chains explored per LSB (runner-up choices; dev set: two PCs share an incrementer)
MUX_LEGS = 3              # blocks: a flop unate in >= 3 flops is a wide mux; those legs are transfers (cut)
CLASS_FAIL_CAP = 8        # copy classes: after 8 consecutive refuted equalities a signature bucket stops merging

# --- counters, shifts, LFSRs (sections 3.3-3.5; read by the recognizers) --------------------------
SHIFT_MIN_DEPTH = 3       # a shift structure needs depth >= 3; depth 2 is a transfer relation (F7, M9)
SYNC_MAX_STAGES = 2       # synchronizer: stages 1-2 of an unconditional input copy path (section 1)
EXHAUSTIVE_WIDTH = 12     # counter functional test enumerates all states up to 12 bits
WORD_CAP = 32             # candidate words have at most 32 flops
TEST_LANES_ACTIVE = 16    # counter test: 16 lanes where some bit is active
TEST_LANES_HOLD = 4       # plus 4 where every bit holds
ORIGINS = 64              # orbit walks start from at most 64 origins
QUADRUPLES = 256          # affinity quadruples per candidate source (section 3.5)

# --- SAT budgets (section 3.7, F9: deterministic conflict limits, never wall-clock) -------------
SAT_LIMIT = 20000         # conflicts per check; the dev set's control checks finish in far fewer
SAT_LIMIT_WITNESS = 20000  # conflicts per witness query
SAT_LIMIT_STRUCTURE = 400000  # conflicts per structure proof (recognizers)
SAT_CALLS_MAX = 40000     # SAT calls per control-layer run; beyond it, remaining queries are skipped and counted


# --- netlist core (netlist.py; read at import, shared with the harness: NOT_PER_RUN) -------------
# They bound work or memory only, never an answer that is given.
#   canonical_order(): colour refinement of the cell-net graph (the GateGraph's canonical build)
CANON_MAX_ROUNDS = 1024   # refinement rounds per refinement: it stops at the stable partition long before
                          # (TEMPO: 32 rounds); a round only splits, a chain of n identical stages needs ~n/2
CANON_ROUND_BUDGET = 4096  # refinement rounds in total (all individualizations; TEMPO: ~10 ms each); past
                          # it the remaining ties go to id order (reported as ties_left_to_id_order)
CANON_INDIVIDUALIZE = 64  # sequential individualizations of tied source cells / port nets before the rest
                          # are broken at once (TEMPO: 0 needed; 8 synthetic parallel chains: 7)
#   netlist.Bdd (the control layer's staged prover; the harness's verify.py keeps its own BDD limits):
#   a query over budget is undecided and the caller falls back to SAT
BDD_MAX_NODES = 400_000   # nodes per manager (~100 MB of Python objects); then every build gives up
BDD_MAX_STEPS = 50_000    # ite steps per gate or per relation before that one gives up
BDD_MAX_VARS = 256        # literals with larger support are not attempted (also bounds recursion depth)
BDD_CACHE_MAX = 400_000   # computed-table entries before the table is cleared (a cache only)

# --- harness limits, mirrored (tools/s3/verify.py's published limits: not tuning; NOT_PER_RUN) ----
# A recognizer that builds claims or conditions beyond them builds something the harness refuses.
# The harness keeps the live value in its own module and does NOT read this file: the harness must
# not depend on the recognizer's parameter file, which a run may override and which is copied into
# the recognizer's sandbox. These are the mirror the recognizers read, and the harness suite's
# test_params_mirror_matches_the_harness fails if the two ever drift.
HARNESS_CONFLICTS = 200_000     # verify.CONFLICTS_PER_CHECK: conflicts per SAT call
HARNESS_EXPR_NODES = 4096       # verify.EXPR_NODES: nodes of one EXPR
HARNESS_EXPR_DEPTH = 64         # verify.EXPR_DEPTH: nesting of one EXPR
HARNESS_COND_LITERALS = 256     # verify.COND_LITERALS: conjuncts of one COND
HARNESS_SHIFT_MIN_DEPTH = 3     # verify.SHIFT_MIN_DEPTH (schema.py: shift_register depth >= 3)
# Added on 2026-09-23 with schema v2.1's extent rules (integration; I02). Neither is tuned: both are
# read off schema.py, and both are mirrors, so a recognizer that reads them refuses exactly what the
# harness refuses. No recognizer reads them today -- counter.params_ok does NOT encode width >= 2, so
# a 1-bit toggle register is still reported and then refused with a reason (changes.jsonl C55's open
# question, left open deliberately) -- they are mirrored so this file lists every threshold.
HARNESS_COUNTER_MIN_WIDTH = 2   # verify.COUNTER_MIN_WIDTH (schema.py: counter width >= 2)
HARNESS_SYNC_MIN_STAGES = 2     # verify.SYNC_MIN_STAGES (schema.py: synchronizer at least 2 stages)
# The multi-case control's own limits, mirrored so recognize.KindCheck (the overlap mirror) reads a
# control exactly as the harness does. Added 2026-09-23 with the same rule as the group above: not
# tuning, read off tools/s3/verify.py (I03).
HARNESS_RESET_CASES_MAX = 64    # verify.RESET_CASES_MAX: named reset cases of one structure
HARNESS_LOAD_CASES_MAX = 64     # verify.LOAD_CASES_MAX: named load cases of one structure
HARNESS_LEGACY_CONTROL_FORM = True   # verify.LEGACY_CONTROL_FORM: whether schema v2.0's single-case
                                # spellings (control.reset a bare COND with control.reset_value,
                                # control.load a bare COND) are still accepted. A transition shim, not
                                # a contract: with it off, a v2.0 control is malformed.
# Moved here on 2026-09-22 from the modules' own blocks (integration; C48, C51).
HARNESS_CLOCK_SUPPORT = 16      # verify.CLOCK_SUPPORT: sources of one clock-gating function, whose
                                # truth table the harness builds exactly (2^16 bits). The control
                                # layer folds a logic clock gate only up to it, so it folds exactly
                                # the gates the harness folds and refuses exactly the same ones.
HARNESS_COVERAGE_MAX_OWN_BITS = 12   # verify.COVERAGE_MAX_OWN_BITS: own bits of the structure that a
                                # region's conditions may read before the coverage obligation stops
                                # being enumerable (one SAT call per assignment an in-range word
                                # value realizes, so at most 4,096 small calls on one structure).
                                # Past it the harness REFUSES the structure, so the bound can only
                                # make it stricter; a recognizer that mirrors it does not build one.
HARNESS_COVERAGE_CALLS_PER_RUN = 200_000  # verify.COVERAGE_CALLS_PER_RUN: coverage SAT calls one
                                # verify_result may spend over every structure (a budget, like the
                                # conflict budget); past it a structure is "not checked".
HARNESS_HOLD_MUST_BE_NONVACUOUS = False   # verify.HOLD_MUST_BE_NONVACUOUS: whether EVERY empty hold
                                # region refuses the structure, including one the VERIFIED cases empty
                                # by themselves. Off: a free-running counter (when = []) has no hold
                                # states and is not degenerate. NOTE the meaning changed on 2026-09-23
                                # while the value did not: it used to mean "refuse a region a load case
                                # emptied", which the mirror below now decides on its own. No recognizer
                                # reads it; it is mirrored so this file lists every threshold.
# Added 2026-09-23 with the lead's decision on the hold obligation (changes.jsonl PV12; the same rule
# as the group above: not tuning, read off tools/s3/verify.py). No recognizer reads it either.
HARNESS_HOLD_EMPTY_NEEDS_VERIFIED_COVER = True  # verify.HOLD_EMPTY_NEEDS_VERIFIED_COVER: whether an
                                # empty hold region must be emptied by the VERIFIED cases (the defining
                                # case, when_down, the reset cases) on their own. On: when the region is
                                # empty only once the opaque load cases are conjoined in, the structure
                                # is REFUSED (bucket "vacuous", cover "load"). Without it a content-free
                                # transform -- load := one complement case per literal of `when` --
                                # erases the mandatory hold obligation of any structure.

# --- control layer: staged BDD prover (controls.py) ------------------------------------------------
# SAT_STAGE1 conflicts first: a relation check still open then is tried on BDDs (netlist.Bdd), which
# decide XOR-dense relations exactly where CDCL stalls; only a check the BDDs cannot prove goes back to
# SAT with its full limit. z3 gives the same answer and model under any limit that the search
# finishes within (979 queries of two synthetic designs: 0 differences), so the only change against
# SAT alone is an 'unknown' that becomes a proof. Used for internal facts only (literal classes,
# duplicates, copy-class merges, equal(bdd=True) for the grouping's hold classes); check() and
# equal() stay SAT-only by default because their proofs become claims the harness re-checks.
SAT_STAGE1 = 2000         # conflicts before the BDD stage (TEMPO: no controls query needs more)
BDD_PROVER = True         # the BDD stage above (False: SAT alone, the behaviour before 2026-09-22)
BDD_PROFILES = False      # also for template and cover-step proofs: off, because BDD-proven XOR templates gave
                          # claims the v1 harness could not verify on 13 of 668 wide-CRC corpus/regression runs

# --- control layer: clock gating by ordinary logic (controls.py; moved here 2026-09-22, C48) ------
# The harness's flop model (schema.py "Flop model", tools/s3/verify.py) reads logic on a flop's
# clock path as an enable. The control layer folds it into the flop's effective next state before
# the scratch graph, the simulator, the labels and the supports are built, with exactly the
# harness's rule (unate cofactor of the clock literal at its root, enable = c|r=1 & ~c|r=0,
# ns' = e ? ns : q), so that every recognizer sees the flop the harness verifies. The support
# bound is HARNESS_CLOCK_SUPPORT, which is a mirror and not a value chosen here.
CLOCK_GATE_FOLD = True    # fold logic clock gates (False: the behaviour before 2026-09-22, which is
                          # what the A/B measurements in out/s3/controls/ call the "off" arm)
CLOCK_GATE_FALLBACK = True  # fold even when no flop names the clock root (every flop of the design
                          # is gated), taking the candidate source in the most flops' clock cones,
                          # ties by structural label, and marking the run ambiguous in meta. The
                          # harness refuses such a design today ("clock logic without one clock
                          # root"), so the structure is reported but not verified.

# --- control layer: mode selector (controls.py; moved here 2026-09-22, C49) -----------------------
# A two-input mux on D whose select is a global, high-fanout literal (a DFT scan enable) is a mode
# selector: the lanes are restricted to its functional cofactor, while every SAT proof still runs on
# the raw next state, so the recognizers' conditions grow to include the select and the test mode
# comes back as the counter's opaque load case. The shares were chosen on the SHAPE of a scan chain
# (it covers every flop of the design and chains all of them) with the second generalisation
# regression set's two scan designs in view, and then corrected on the synthetic corpus, which
# exposed a parallel-load register being read as a mode; the change log records that use.
MODE_SELECT = True        # restrict the lanes to a mode selector's functional cofactor (False: the
                          # behaviour before 2026-09-22; the A/B "off" arm)
MODE_SELECT_SHARE = 0.75  # share of the netlist's flops the select must mux, and that must copy a
                          # source in the test mode (a scan chain covers every flop; a functional
                          # mode mux over a quarter of a design is not a global mode)
MODE_SELECT_MIN_FLOPS = 4  # and at least this many flops (a "mode" over 2-3 flops is a datapath mux)
MODE_SELECT_MARGIN = 0.5  # the other polarity may copy at most this share of the test mode's copies
                          # (a shift or load register copies in both and is not a mode)
MODE_SELECT_MAX_CANDS = 4  # candidate selects examined (sources in >= MODE_SELECT_SHARE of the
                          # flops' next-state supports, by structural label): a budget
MODE_SELECT_SCREEN = 32   # flops examined before a candidate that is not muxing them is dropped
MODE_SELECT_MIN_LIVE = 1024  # live lanes that must survive the restriction, else it is dropped

# --- shift registers (shift.py) ---------------------------------------------------------------------
# One condition class: every copy edge of a conditional shift copies under the structure's joint
# condition on >= 1/20 of the lanes where it copies at all (judged only where 1/20 of its lanes is
# >= CONTROL_EVIDENCE). Stages of one shift copy on one event, up to per-stage leakage into the exact
# conditions (a one-hot mux's unreachable multi-hot states, M8); an FSM chain's edges copy mostly on
# other events. Measured: TEMPO's byte shift 0.140 (every permutation), synthetic shifts 1.0, TEMPO's
# one-hot FSM chains <= 0.027; the value sits between them on a log scale.
SHIFT_STAGE_SHARE = 0.05
NLFSR_PAIRS_MAX = 4096    # budget: second-derivative pairs per feedback head (nonlinearity test); past it
                          # the lane stays an LFSR/CRC candidate relation (never reached on any design run)
# Moved here on 2026-09-22 (C50). Several condition classes can decompose one flop set into lanes in
# different ways and all be true of the netlist (a barrel rotate: rotate by 1 is one lane of depth 8,
# rotate by 2 is two lanes of depth 4 over the same eight flops). Both candidates carry the same flop
# count, the same seed kind and -- being one automorphism orbit -- the same structural labels, so the
# choice used to fall to the order the class sweep happened to produce and moved with the gate mapping
# (lanes 2 / depth 4 in 3 of sh_barrel_w8_ar's 8 netlists, lanes 1 / depth 8 in the other 5). On, the
# candidates over exactly the same flop set are ordered among themselves by the decomposition --
# deepest lanes first, then fewest -- which is a function of the netlist's behaviour and of nothing
# else, and the decompositions not taken are reported as "alternative_decomposition" relations.
# Deepest first because a lane of depth d is the stronger claim and the harness's template is per
# lane. It applies WITHIN a same-flop-set group only: an earlier form that put the decomposition into
# every candidate's sort key also reordered candidates that merely had the same total size and cost
# the development design's headline (micro F1 1.000 -> 0.724 on that build).
SHIFT_DECIDE_TIES = True  # False: the behaviour before 2026-09-22 (the A/B "off" arm)
# Moved here on 2026-09-23 from shift.PENDING_PARAMS (integration of the schema v2.1 round; I01).
# Nothing was retuned in the move; the values are the module's as delivered.
SHIFT_RESET_CASES = 3     # at most 3 reset cases per shift structure: the synchronous reset the
                          # control layer finds is the first, leaving two further clear cases. Every
                          # case shrinks the hold region, so this is the ceiling on "explain the rest
                          # away". Tuned on the development design and the corpus TRAIN split only;
                          # 1 is schema v2.0's behaviour, and no set ever needed more than 1, so it
                          # is a ceiling and not a fitted value. The harness allows 64
                          # (verify.RESET_CASES_MAX). Load cases keep CASE_CAP, which already bounded
                          # how many parallel-load cases _loads collects; what changed is that the
                          # ones NEEDED for the hold obligation are emitted, not only the widest.
HOLD_VACUOUS = True       # a measurement switch, not a value with a decision in it (the shape of
                          # HOLD_REQUIRED below). True (here): an EMPTY hold region -- the named
                          # cases cover every state, which is what an unconditional shift register
                          # and a "shifts or loads" shift look like -- is reported as hold true,
                          # which schema v2.1 accepts and the harness reports (hold_vacuous). False:
                          # reported as hold false, which is schema v2.0's behaviour and makes the
                          # harness refuse the structure outright. Measured both ways on the corpus
                          # and on the second regression set (changes.jsonl MC04); the vacuous-hold
                          # count the harness reports rises with it, which is the honest read.

# --- counters (counter.py; besides EXHAUSTIVE_WIDTH, WORD_CAP, TEST_LANES_*, N_MIN) -------------------
LOAD_DISTINCT = 3         # a load needs >= 3 distinct unexplained next values (a clear and a set give two)
RELOAD_DISTINCT = 4       # a reload at the terminal count is a data load with >= 4 targets across lanes (presets give a few)
REL_STEPS_MAX = 2         # constant steps besides the count step (relative loads); more is an accumulator
MODE_LANES = 4            # pool lanes per rarer mode (a down step, a relative step) checked by a full table
MODE_MIN_LANES = 8        # a rarer mode is looked at only with >= 8 pool lanes ...
MODE_MIN_SHARE = 0.001    # ... and >= 1/1000 of the live lanes (single lanes are witness noise)
NEST_MIN = 0.5            # toggle nesting: >= half of a candidate's counting changes inside the top bit's
NEST_RATE = 1.25          # toggle nesting: a next bit changes at most 1.25x as often as the bit below ...
NEST_SLACK = 8            # ... plus 8 lanes (bit k+1 of a counter changes half as often as bit k)
NEST_TRIES = 3            # toggle nesting: runner-up next bits explored per growth step
NEST_BINS = 20            # nesting shares are compared in 5 % steps (then by the number of changes)
ORDER_TRIES = 24          # bit orders tried per table (equal change counts permuted)
COUNTER_SAT_CALLS = 30000  # SAT calls per run of the counter module (the control layer has its own cap)
CLAIM_SAT_LIMIT = 100000  # conflicts per counter proof query: half the harness's per-check limit
GROW_LIMIT = 48           # counterexample-guided literal additions per condition before giving up
UP_TRIES = 2              # upward growth: flops tried on top of a word per step (fewest support first)
REFINE_ROUNDS = 4         # chosen words widened by one bit (below, above) and reselected, up to 4 times
SENS_VECTORS = 1 << 18    # sensitivity simulation: at most 2^18 (variant, state) vectors per pass
LANE_TRIES = 3            # counting lanes tried per direction for a proof
NET_TRIES = 4             # internal enable / load nets tried per lane (fewest sources first)
WIDE_CAP = 256            # carry-chain growth: a budget only (WORD_CAP bounds candidate enumeration)
WIDE_SAMPLES = 384        # random states per proof or growth step of a word wider than EXHAUSTIVE_WIDTH
WIDE_EXCEPTIONS = 4       # SAT-found exceptional states per lane of a wide word (wrap, reload)
WIDE_RETRIES = 3          # a grown word that does not prove is retried at most 3 times, shorter
CHAIN_SAMPLES = 64        # carry-chain search: sampled states per step (a wrong next bit survives 64 coin flips w.p. 2^-64)
CHAIN_LANES = 4           # carry-chain search: counting lanes tried per LSB
CHAIN_FANOUT = 64         # carry-chain search: toggling readers simulated per step (fewest-key first)
CHAIN_LSB = 0.7           # carry-chain search: an LSB toggles in >= 70 % of states (all but a stop or wrap point:
                          # a 2-bit word loses a quarter; bit 1 of a counter toggles in half)
CHAIN_AGREE = 0.9         # carry-chain search: the next bit toggles in >= 90 % of carry states, <= 10 % of others
NEST_SHARE_SLACK = 0.05   # below-the-word test: x's sources outside the word's LSB's: at most one (a per-bit load) or 5 %
REGULARIZE_ROUNDS = 4     # rounds of other register values for a lane's loads before its template adapts
REGULARIZE_OK_STATES = 8  # counting states that must stay regular in each such round (besides the exceptions)
FLIP_SAMPLE = 32          # counting states sampled per single-source flip (data-dependent steps of an accumulator)
FRAGMENT_DEPTH = 4        # fragment test: overlapping witness words are themselves tested to depth 4 (a budget)
TRUNC_DEPTH = 2           # truncation test: a reader's own counter is tested for truncation to depth 2 (a budget)
SELF_CONDITIONS = False   # counter conditions never read the word's own state (the harness's rule); True: they may
COUNTER_DEP_SCAN = 4096   # budget: change lanes simulated (3 states each) when a table's lanes were all loads or
                          # resets and are redrawn where the next state depends on the word's own state; a quarter
                          # of the base pool, so a count mode on >= 1/1000 of the lanes is met w.p. > 0.98
# Moved here on 2026-09-22 from counter.py's own block (C52-C55). None names a width, a modulus or a
# design; each is overridable per run like the rest.
# A word whose lanes take several constant steps under one enable (c <= c + (two ? 2 : 1)) is a
# counter with a case-selected step, not an adder, when the steps are few, no step is the sum of two
# others (a 2-bit addend gives 1, 2 AND 3) and a single source chooses between them (a k-bit addend
# gives one step per addend bit). The defining case is the domain split by that case literal, proven
# on the whole word; the other steps are non-defining and are reported in proof.alt_steps. The values
# are the smallest that admit a two-way case; raising either admits addends. (C52)
MODE_STEPS_MAX = 2        # distinct constant steps a word may take under one enable
MODE_STEP_SOURCES = 1     # sources whose single flip may change the step
# A flop the control layer proved quiescent (it changes only where the detected synchronous reset is
# active) is a counter candidate again when its next state depends on its own value on the lanes
# where it does change: the detected reset is then a case literal, not a reset (a carry into the next
# digit sets the low digit to a constant and passes the reset test). Such a word is tested on every
# pool lane instead of the live ones. (C53)
QUIET_LANES = 64          # lanes simulated per flop to decide (a load or a reset sends both of the
                          # flop's own states to one value, which the test separates)
# Conditions may read the word's own state where schema v2's coverage obligation admits it (a wrap, a
# stop or a reload at a terminal count), and the module discharges that obligation the way the harness
# does, so that it does not emit a word the harness will refuse: the own bits the conditions read are
# enumerated, and each assignment an in-range word value realizes must leave the defining region
# satisfiable. COVER_VECTORS random source assignments are simulated first, so the common case costs
# no SAT call; past COVER_SAT calls, or past HARNESS_COVERAGE_MAX_OWN_BITS own bits, the word is
# REFUSED, never admitted. SELF_COVERAGE = False restores the blanket ban (SELF_CONDITIONS alone,
# the behaviour before 2026-09-22). (C54)
SELF_COVERAGE = True
COVER_VECTORS = 64        # random source assignments simulated before the check spends SAT calls
COVER_SAT = 64            # coverage SAT calls per word
# Repairs that let a counter discharge control.hold, which schema v2 requires: a condition is
# generalised by dropping redundant literals, re-expressed over the netlist's own signals (generalize
# can only name cone leaves, so a condition the design writes as two internal signals came back as a
# cube over every flop driving them), weakened to a single enable net where one implies the same
# template, and the restart case is named as the reset or load case. Each is a budget on SAT calls,
# not a value with a decision in it. (C55)
NET_COND = 24             # netted signals of the word's cone offered to a count condition besides the
                          # cone's leaves (_netify), highest first; one SAT call per literal considered
ENABLE_TRIES = 6          # netted enable literals tried when a direction's lane cube is weakened to
                          # the design's own count enable (_enable_net), weakest first
RESET_TRIES = 6           # candidate reset-case literals tried by _reset_net, widest first
LOAD_CUBE_ROUNDS = 3      # counterexample rounds of the load-cube search (_load_cube)
HOLD_REQUIRED = False     # True: a word whose hold obligation does not prove is DROPPED, so every
                          # emitted counter carries a proven control.hold and the harness verifies
                          # every structure the module reports. False (here): it is reported with
                          # hold false -- a correct recognition the scorer credits and the harness
                          # then refuses with an explicit reason. Measured both ways (C55): on the
                          # second regression set True gives 208 structures / precision 1.000 / all
                          # verified / recall 0.963, False 220 / 0.964 / 216 verified / recall 0.981;
                          # on the development design True drops found-recall to 0.27 with 6/6
                          # verified, False keeps it at 1.000 with 7/22 verified. A counter that
                          # clears or reloads outside its count case has no hold states at all and
                          # schema v2 has one reset COND and one load COND to name them with, so this
                          # is a reporting choice between a refused claim and an absent one.
# Moved here on 2026-09-23 from counter.PENDING_PARAMS (integration of the schema v2.1 round; I01).
# Schema v2.1 made control.reset a LIST of cases and control.load a LIST of CONDs, so the search that
# names a counter's restart cases needs a bound on how many it may name. Nothing was retuned in the
# move. The paragraph above (HOLD_REQUIRED) is the reason these exist: naming the other cases is how
# a word that clears AND reloads gets a hold region at all.
RESET_CASES = 3           # at most 3 reset cases named per word. Each one shrinks the hold region,
                          # so this is the honest ceiling on "explain the rest away": a word that
                          # still does not hold after 3 clears is not a counter this module can
                          # state. Tuned on the development design and the corpus TRAIN split only;
                          # 1 is schema v2.0's behaviour. The harness allows 64 (verify.RESET_CASES_MAX).
                          # Never observed above 2 on any set, so it is a ceiling, not a fitted value.
LOAD_CASES = 3            # at most 3 load cases per word, same bound and the same reason. A load
                          # case is opaque (nothing is checked under it), so this is the tighter of
                          # the two ceilings in what it could buy an unsound structure; the harness
                          # still reports an empty hold region (hold_vacuous) and how much the load
                          # cases hide (load_hidden_share), and still requires the defining case to
                          # be reachable at every word value in range. Never observed above 3.

# --- LFSRs and CRCs (lfsr.py) ---------------------------------------------------------------------------
LFSR_FLIPS = 8            # random state vectors per lane: a bilinear source-state coupling survives all 8 w.p. 1/256
LFSR_LANES_SCAN = 1024    # active lanes scanned for mode classes per word (a budget: more lanes only re-find classes)
LFSR_CLASS_LANES = 2      # lanes per mode class analysed in full (a second lane exposes a second tap setting)
LFSR_ROOT_MAX = 40320     # chain-search budget (interleavings, 8!), only for matrices the centralizer cannot root
                          # (no cyclic unit vector); it bounds time, and recall only for derogatory k-step matrices
LFSR_K_MAX = 128          # steps per clock tried by the centralizer root (a 128-bit data path at one step per bit);
                          # a larger k is reported as form "affine", never as a wrong LFSR
LFSR_MODES_CLAIMED = 8    # mode classes proven per word (a SAT budget; past it fewer modes are listed and k_steps
                          # comes from those, never a wrong claim)
LFSR_PROBE = True         # programmable taps: also prove the probed settings p = 0 and each one-hot p
LFSR_COND_DROPS = 128     # proofs per mode spent generalising a claim's condition (drop one literal each)
LFSR_MIN_WIDTH = 2        # a word has at least 2 flops (a 1-flop "LFSR" is a toggle or a copy)
LFSR_NONLIN_ROW = 0.5     # a row nonlinear in the word's bits on most lanes is not an LFSR bit; a minority of
                          # nonlinear lanes is a mode chosen by the word's own state (a reseed, a stop)
LFSR_AFFINE_MIN_WIDTH = 3  # an "affine" word has >= 3 flops: every strongly connected 2x2 GF(2) map is a
                          # companion (an LFSR), a swap (a shift) or singular (two copies of one XOR)
LFSR_PARITY_BASIS = 6     # exact proof by parity functions: a signal is a function of at most 6 affine forms (a
                          # 64-entry table; a split XOR needs 2-3); a signal past it is left to SAT, never guessed
# Moved here on 2026-09-22 from lfsr.py's own block (C56-C58).
# A word wider than WORD_CAP is never ENUMERATED (the cap bounds candidate enumeration), but a whole
# SCC or block of the state-support graph that is closed under the combining relation -- no flop
# outside it feeds any of its next states -- is one word by construction and not a choice among many,
# so it is analysed whole up to this width; its sub-blocks stay capped. A budget, not a recall limit:
# every wide positive of the cost family comes back whole and verified with all four params right to
# w = 160. find() costs, median of 3 runs in one process: an autonomous one-step LFSR 0.06 s at
# w = 32, 0.12 at 64, 0.26 at 128, 0.36 at 160; a CRC of 8 steps and one data bit per step 0.09 /
# 0.16 at 32 / 64; the worst wide word that is NOT an LFSR (a closed binate NLFSR, rejected by the
# affinity test after the lane scan) 0.18 at 64 and 0.58 at 160. 128 covers the widest common
# whitening or CRC word (a 128-bit data path); past it the word is left to the grouping, as before.
LFSR_WIDE_CAP = 128
# Taps selected by signals that are not flops (a mode pin) are not the truth's "programmable", which
# the corpus conventions reserve for taps a REGISTER holds. On, the probed setting with every
# tap-selecting signal at 0 becomes the defining mode and its constant polynomial is reported, with
# the other probed settings in proof["lfsr"]["pin_modes"]. WHICH setting to report is a CONVENTION,
# not something the netlist decides: the all-zero setting is the one the netlist names without
# reference to a lane, and it was chosen after the alternative (the defining lane's own polynomial)
# proved unstable on the second regression set's one such design -- whose truth value it then also
# matched. One design is not evidence that the convention is right. False: poly "programmable" (the
# behaviour before 2026-09-22).
LFSR_PIN_POLY = True
# Mirror the own-bit matrix gates the harness applies (verify.py's _lfsr: no zero row, no dead
# column, not a partial permutation) when the lane and the defining mode are chosen: a class's lanes
# share (form, k, chain) but not the taps, and a programmable word sampled at a tap setting with no
# tap at the top stage has a stage that holds 0 and that nothing reads, which the harness refuses.
# On, prefer a lane and a mode whose matrix passes and emit nothing when none does (the harness would
# refuse it anyway); False: the first modelled lane (the behaviour before 2026-09-22). Applying the
# gate UNCONDITIONALLY instead -- dropping such a word -- lost two corpus designs outright, which is
# why this is a preference and why it is a switch.
LFSR_OWN_GATE = True

# --- word grouping (group.py) ----------------------------------------------------------------------------
# DANA pass: two flops' neighbour block sets share >= a third of their union (TEMPO, two id
# permutations: AMI 0.967-0.969 at 0.3, 0.962-0.964 at 0.5, 0.94 at 0.7; below 0.25 unrelated words
# merge, ARI 0.92; synthetic training split: identical at 1/3 and 1/2). Chosen by TEMPO AMI (C05).
WORD_JACCARD = 1 / 3
DANA_SUCC_ROLES = False   # DANA successor signatures carry the reader's role of the flop (unate +/-, binate):
                          # off (TEMPO AMI 0.9660 -> 0.9686 on, synthetic corpus mean AMI 0.6067 -> 0.6008)
WORD_CONTAINED = False    # DANA pass: two flops also stay in one word when one's neighbour block set lies
                          # inside the other's, whatever the Jaccard. Off: it heals 10 of TEMPO's 18 split
                          # registers but merges words the DANA pass has to separate (TEMPO AMI 0.9806 ->
                          # 0.9638, ARI 0.9726 -> 0.8803, exact words 106 -> 99 of 147; synthetic corpus
                          # mean AMI 0.8361 -> 0.8349 over 338 runs)
P0_MAXIMAL_CLASSES = True  # P0 key: drop a shared cover class that holds exactly one block of the full key
                          # when another class of the same cover strictly contains it and holds exactly the
                          # flops whose key uses it (group.Grouper._inner: the broader class is a word's own
                          # control, the narrower one a condition inside that word -- a later greedy cover
                          # step explains the hold lanes the earlier steps left, as for an accumulator bit
                          # that also keeps its value when its own addend bit and carry are 0). A class that
                          # controls flops past that word stays whatever its size: it is what holds two words
                          # apart. Synthetic corpus mean AMI 0.8361 -> 0.8628 (9 of 338 runs better, none
                          # worse); TEMPO's partition is unchanged. False: the whole shared set (before
                          # 2026-09-22)

# names a single run may not override (see the module docstring)
NOT_PER_RUN = frozenset({"CANON_MAX_ROUNDS", "CANON_ROUND_BUDGET", "CANON_INDIVIDUALIZE", "BDD_MAX_NODES",
                         "BDD_MAX_STEPS", "BDD_MAX_VARS", "BDD_CACHE_MAX", "HARNESS_CONFLICTS",
                         "HARNESS_EXPR_NODES", "HARNESS_EXPR_DEPTH", "HARNESS_COND_LITERALS",
                         "HARNESS_SHIFT_MIN_DEPTH", "HARNESS_CLOCK_SUPPORT",
                         "HARNESS_COVERAGE_MAX_OWN_BITS", "HARNESS_COVERAGE_CALLS_PER_RUN",
                         "HARNESS_HOLD_MUST_BE_NONVACUOUS", "HARNESS_HOLD_EMPTY_NEEDS_VERIFIED_COVER",
                         "HARNESS_COUNTER_MIN_WIDTH", "HARNESS_SYNC_MIN_STAGES",
                         "HARNESS_RESET_CASES_MAX", "HARNESS_LOAD_CASES_MAX",
                         "HARNESS_LEGACY_CONTROL_FORM"})

def resolve(overrides=None):
    """The parameters as a dict (module values, then `overrides`); an unknown name, or a changed
    NOT_PER_RUN value, is an error."""
    out = {k: v for k, v in globals().items() if k.isupper() and k != "NOT_PER_RUN"}
    for k, v in (overrides or {}).items():
        if k not in out:
            raise KeyError(f"unknown parameter {k}")
        if k in NOT_PER_RUN and v != out[k]:
            raise KeyError(f"parameter {k} is fixed for every run (params.NOT_PER_RUN)")
        out[k] = v
    return out
