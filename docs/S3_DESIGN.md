# S3_DESIGN: structure recognition in anonymous netlists, first slice (PRD S3)

**Status.** Revision 3, 2026-09-23: the design of the code the lead freezes. Revision 2 folded in the two part-1 reviews, validity
(**V**) and feasibility (**F**), and the lead's decisions on them; this revision reconciles the document with the code, after the proof
re-reviews of 2026-09-22 and the freeze-readiness review. **The data contract is `tools/s3/schema.py`** (truth `retrace-s3-truth/2`,
result `retrace-s3-result/1`, `KINDS`, `STRUCTURE_KINDS`, `PARAMS`, `PROOF`, `truth_hash()`, `check_truth()`, `check_result()`), not
restated here. **The verification contract is `tools/s3/verify.py` (v2.1)**; §3.7 restates it, because the freeze commits this document
as the specification and the module is the only other place it is written down. Both truth files are on truth/2: TEMPO's passes
`check_truth()` with 0 problems (236 registers, 16 units, *measured*), and the puzzle's is written only when its own checks pass. "S3"
is the PRD stretch goal, not stage S3 of `docs/spec/APPROACH.md`. Figures are *measured* (prototype, truth or evaluation runs; reviewer
measurements are in §3.0) or marked *estimate*.

## 1. Scope and shared definitions

The slice finds the four `STRUCTURE_KINDS` and a word grouping in a netlist without names, states each structure's control conditions so
the harness can verify it, and scores the result against RTL truth. The truth rules follow the recognizer's definitions where they can;
every difference left is a known disagreement (§4.1), in every report and never tuned away (V2).

| Kind | Recognizer definition | Truth rule (`truth_tempo.py`) |
|---|---|---|
| `synchronizer` | **≥ 2** stages of an unconditional copy chain (no hold, no case literal) whose head samples a primary input, a black-box output, a latch output or a flop of another clock domain; further stages are a *delay* relation, more a shift structure | no enable; D is an input pin (stage 1) or a stage-1 flop (stage 2) |
| `shift_register` | copy paths of depth ≥ 3 under one condition class (§3.3), in lanes of equal depth whose heads are of one kind; loads allowed | D[k] = Q[k+s] within one register, on ≥ 75 % of its bits |
| `counter` | under one bit order every transition is +1/−1, hold, constant or +c (a relative load), and at least one counts: binary, up/down, modulo, saturating, loadable. **Width ≥ 2** | innermost adder on its own Q, with a constant or 1-bit step |
| `lfsr_crc` | GF(2)-affine in its own bits for fixed parameters: Fibonacci, Galois, serial injection, k steps, modes, programmable polynomial | its own Q bits at other indices reach D through XOR |

**The 1-bit toggle rule** (`truth_tempo.TOGGLE_RULE`, and the same rule in `corpus.py` and `thirdparty.py`). A width-1 register whose
update is `Q <= ~Q`, possibly under an enable, is kind `flag` with `alt_kinds` `["counter"]` everywhere: a 1-bit counting template (`w'
= not q`) says nothing that every degenerate gate does not also satisfy. The recognizer may still emit such a structure and a lenient
match credits it, but the harness refuses it (`verify.COUNTER_MIN_WIDTH = 2`), so it is **found but never verified**; a 1-stage
"synchronizer" is refused likewise (`SYNC_MIN_STAGES = 2`, §3.7). The rule costs three corpus designs (`toggle_en_ar`, `toggle_free_nr`,
`toggle_multi_sr`), now `flag` with a `counter` alternative rather than `counter` (change log I04, C55).

**Not scored.** Cross-register copy chains of depth ≥ 3 are shifts to the recognizer but data registers to the truth; they count as
false positives and are reported by truth kind. *Relations* are proven facts but not structures: cascades, delay stages, depth-2
transfers, duplicates. Out of scope: combinational operators, FSMs, memory semantics, multiple clocks, latches, imaging errors; the one
exception is `==k`, `<k` and `≥k` compares on a counter's value, reported but not scored.

**Verified, found and matched.** A structure is *verified* when the harness proves its kind's obligations on its own copy of the netlist
(§3.7); a result's own `proof.status` is the recognizer's claim and counts for nothing. It is *matched* when it pairs with a truth item
(§4.2) and *found* when that item also accepts its kind. **Found and verified are reported apart, per kind, everywhere**, with the
harness outcome that explains each found-but-not-verified structure; no report may present one as the other.

## 2. Inputs, anonymity, determinism

| Design | Role | Recognizer input | Truth (scorer only) |
|---|---|---|---|
| TEMPO | development | `extract_tempo()` -> `load_extraction`: 2,832 flops, 17,510 gates, 19 in, 24 out, 32 SRAM outputs | 236 registers, 16 units. The flop mapping is proven by z3. Kinds come from Yosys word-level rules, with 3 manual overrides and 6 `alt_kinds` rules (V12), one of them the toggle rule |
| Synthetic | unit tests and the corpus | small RTL (§4.4), synthesised for sky130 and IHP -> `load_verilog` | netlist names |
| Puzzle | frozen-code evaluation of a known design (we recovered its RTL) | `tools/retrace/extract.py` -> `load_extraction`: 92 flops | registers stated by hand, every claim checked against the recovered RTL, a fresh extraction and a cycle-by-cycle model |
| TT blind set | blind evaluation (§4.4) | N third-party Tiny Tapeout sky130 GDS, extracted | automatic labels (`thirdparty.py`) |

**What the recognizer sees.** Only the `Netlist`: library masters, pin names, Liberty functions, integer nets, ports in random order and
constants. It never sees the `Key`, `nl.v`, the DEF, the RTL or the truth; placement feeds only a scorer-side ablation. The harness
replaces black-box pin names with opaque ids keeping only the direction (V13), else the SRAM's LEF bus names would cue TEMPO's order.

| Enforcement | Rule |
|---|---|
| API | `tools/s3/recognize.py`: `recognize(nl, params) -> result`, importing only `tools.s3.netlist`, `tools.s3.params`, the recognizer modules (`controls`, `counter`, `shift`, `lfsr`, `group`), the standard library minus the forbidden set (native calls, hidden imports, files, the OS, processes, the network, serialisation), numpy and z3 (V3) |
| Isolation | `run.py` asserts `strings_in(nl)` holds no `Key` name, pickles `nl` alone with its sha256, and runs the recognizer as a subprocess under two layers: an in-process guard and, where the host has one, an OS sandbox (read-only binds, no network, no writes; blind runs refuse to start without it). The permutation seed comes from `os.urandom` and is never passed on: the loader sorts names before shuffling, so a known seed is invertible (V10) |
| Audit hook | the recognizer may only read `netlist.pkl`, write `result.json` and run `yices-sat` |
| Static tests (`test/test_s3.py`) | over the recognizer module closure (`run.recognizer_modules()`, which follows absolute and relative imports and holds no harness or `truth*` module): an **AST import scan** — only `tools.s3.netlist` and `tools.s3.params` (`ALLOWED_S3`), the closure's own modules, `numpy`, `z3` (`ALLOWED_TOP`) and the standard library minus `FORBIDDEN_STDLIB`; any other `tools.*` import fails — together with a code scan for `open`/`exec`/`eval`/`compile`/`__import__`/`breakpoint`/`input`, for `__builtins__`/`__loader__`, and for any use of a cell's master name against a string literal (comparison, string method or `re` call); a **salted-digest name scan** of every string and bytes constant against per-process HMAC digests (fresh `os.urandom` salt; a failure names the module, the line and the *kind* of name, never the name) of every truth file's register names, RTL bit identifiers, join keys and instance names, plus design words, PDK and library words, and file paths; and a **large-literal scan** (no literal table over 256 constants, bytes literal over 256 bytes or integer wider than 256 bits). All three have planted-violation negative controls. Which designs may run is enforced in `run.py`, not by a scan: `run.run()` refuses a development run of the puzzle, of any `--gds` third-party design and of an unknown design before any extraction, and `run.tempo_lvs()` refuses a `TEMPO_ROOT` other than the frozen snapshot. **There is no repo-wide scan for readers of `upstream/puzzle.gds` or `truth_puzzle.json`** (V0, F15) |
| Output | no `Key` name; `check_result()` passes; structures pairwise disjoint |

**Determinism** (V10, F9). **Pool bits** are seeded from each source's structural hash (Weisfeiler-Lehman over its kind and cone shape),
not its position; tied sources take streams in id order, which can only permute the result by an automorphism. **SAT** uses
deterministic conflict limits, never wall-clock timeouts. The protocol **requires** of an implementation that a fixed permutation seed
and pool salt give a byte-identical `result.json` (timings go to `result.run.json`); that is a requirement, **not a measurement** — no
test replays a run under a fixed seed, and `run.py` exposes no way to fix one, every permutation coming from `os.urandom`. What *is*
measured is the weaker and different thing below: agreement across the permutations and the file-order arm. The recognizer is
**not *proven* permutation invariant, so the protocol does not assume
it**: `freeze.PROTOCOL` makes every frozen evaluation run K ≥ 5 independent `os.urandom` permutations inside its one attempt and report
every metric per permutation and as mean / median / min / max ("spread"), with the pairwise structure-set agreement. What is *measured*
on the freeze code state is the opposite of a spread: the TEMPO run `out/s3/eval/runs/tempo-20260923T053247Z-ef7fc630631b.json` (5
permutations plus the file-order arm) reports `spread.distinct_answers = 1` — one canonical answer up to ids, every headline metric
identical across the six arms — and `leakage.file_equals_a_permutation = true`. That is evidence of invariance on one design, not a
proof of it over all netlists, so the K ≥ 5 rule stays as the conservative protocol. **Leakage test.** A file-order arm (the loader's
ids, seed `None`) must lie within that spread on every metric and on structure-set agreement.

## 3. Algorithms

The pipeline runs from cheap to expensive: simulation proposes, SAT decides, nothing is claimed on simulation alone. Checks are
combinational over flop states, inputs and black-box outputs, so they hold in every state satisfying their region — never only in
reachable ones (§3.7). Notation: `q_i` is flop `i`'s state, `f_i` its next-state literal (`Flop.ns`, enables folded in), `supp` and
`cone` its support and gates, `L(l)` the lanes where `l` is 1, `rho` the reset literal.

### 3.0 Measured findings behind this revision

F re-implemented revision 1's §3 on TEMPO's named `nl.v`; V measured on the truth files. `Mn` refers to this table.

| # | Finding (TEMPO unless noted) | Measurement | Response |
|---|---|---|---|
| M1 | A flop's own literal in its candidates | the cover took `{f_i, ¬f_i}`: no active lane for 347/347 structure flops (F) | exclude it and its SAT-equals (§3.2) |
| M3 | The reset is a gate | `rst = rst_sync[1] \| ~rst_n` (fanout 1,247); `rst_sync[1]=1` forces 2,563 next states and `rst_n=0` 2,564; pinning `rst_n` alone leaves reset active in 55.6 % of lanes (F) | reset over gate literals, support pinned (§3.1) |
| M4 | Rare activity | with reset pinned, 804 flops change in ≤ 64 of 14,395 non-reset lanes and 633 in ≤ 4 (all CRC flops, `addr_word`, `pop_rem`); only 162 gates pool-constant (F) | witnesses for rare literals (§3.1) |
| M5 | CRC activity | a `crc_l` bit changes in 1-3 of 16,384 lanes; the word is active in 1 of 4,096. Unwitnessed affinity put 4 `poly_l` bits, 5 `x_ir` bits and `refin` into V and 16 `x_a` bits into P (F) | case-conditioned witnesses (§3.1, §3.5) |
| M7 | CRC proof cost | unconstrained 4-copy miter: z3 8.4 s (bit 0), 52.5 s (bit 31), > 60 s (bits 8/16/24/28); yices > 120 s; control pinned to a 7-step witness: 2.9-5.2 s per bit per mode; poly fixed: < 10 ms; naive ANF: > 10 min (F) | probed settings only (§3.5) |
| M8 | `dreg`'s shift select | active in 13 of 14,429 non-reset lanes; no literal at depth 4, 8 or unlimited, and no pair of the 106 signals shared by ≥ 20 `dreg` cones, selects it; RTL shifts in several FSM states under priority loads (`tempo_host.v:323-459`) (F) | transparency conditions (§3.3) |
| M9 | Depth-2 copy paths | depth ≥ 2 covers 312 `data_register`, 284 `register_file_word`, 14 `flag`, 4 `fsm_state`, 3 `counter`, 3 `accumulator` flops against 39 synchronizer and 14 shift flops; depth ≥ 3 leaves 20 (`pins_prev` 15, `sck_p` 1, `st` 4) and keeps `rx_shift` (F); 1,940 RTL bits have a direct-copy mux case (V) | depth ≥ 3, delay relations (§3.3) |
| M10 | Per-bit carries | `time_q`, `addr_word`, `steal_cnt`, `rx_pos_q`, `bit_cnt`: one carry gate per bit (F) | carry chains, no signature condition (§3.4) |
| M12 | Lumping under the 50 % rule | one 92-flop "counter" scores recall 27/27 and precision 1/1 on the puzzle; TEMPO's 128 counter flops + 128 others score 23/23, 1/1; both 0 under IoU (V) | IoU matching (§4.2) |
| M13 | NMI chance level | singletons: 0.757 (TEMPO), 0.845 (puzzle); random blocks of truth sizes: 0.389, 0.652; ARI 0 for both (V) | AMI/ARI headline (§4.2) |
| M15 | Development-set gap | TEMPO has no saturating counter and only power-of-two moduli: `bw`, `head_r`, `tail_r` wrap mod 4 (`tempo_host.v:455-460`, `tempo_fifo.v:68-71`) (V; RTL checked) | recorded (§4.4) |

### 3.1 Pool, reset, control classes, witnesses (`tools/s3/controls.py`)

**Pool.** 16,384 lanes, capped at 49,152 (125 MB of bitsets). Each source gets a bias per 64-lane word from {1/8, 1/2, 7/8}.

**Reset** (F3, M3). A ternary pass forces each gate literal and each source to each value with everything else X; `rho` is the one that
makes the most next states known; its support is pinned inactive in 15/16 of pool lanes and in every witness lane, by SAT where needed.
A synchronous `rho` is accepted only if it forces at least 25 % of flops, else the async clear/preset class is the reset and next-state
lanes stay unpinned.

**Literal classes.** Gate signals and sources in some flop's depth-4 cone are grouped by FRAIG-style sweeping (Mishchenko et al. 2005):
bucketed by pool signature (polarity normalised), confirmed by `Sat.equal` and union-found, each counterexample added as a lane, at most
3 rounds. A *control class* resets or holds at least 2 flops on lanes where `rho` is inactive; only control classes are reset or hold
candidates (F0, F13).

**Witnesses** (F4, M4). Every candidate literal with fewer than `N_min` = 64 lanes in either polarity gets a SAT query for that polarity
with `rho` inactive: UNSAT proves it constant, SAT adds 16 lanes that copy the witness on `supp(l)`, randomise the rest and pin `rho`.
**Case-conditioned witnesses** (F1, M5): every candidate word (§3.3-3.5) with fewer than `N_min` active lanes gets up to 64 SAT
witnesses of "the word does not hold" (some `f_k ≠ q_k`), each blocked after use, copied onto the support of the word's enable and case
literals. Per-flop active-lane counts go to `meta`.

### 3.2 Per-flop next-state profile

The candidates are the literals of `cone(f_i) ∪ supp(f_i)`, in both polarities, **minus `f_i` and anything SAT-equal to `f_i` or
`¬f_i`** (F0, M1). Own-bit self-activity is removed (F5); state dependence is judged per word (§3.4).

| Step | Rule |
|---|---|
| Covers (F0) | reset cover `R_i` and hold cover `H_i`: greedy, cap 4, drawn only from control classes, ranked by the number of flops they control (whole covers and lane-count ranking were measured worse: F) |
| Templates | tested before each further cover step; the first that fits the active lanes `A_i` wins: `const`, `copy(j)`, `copy_inv(j)` (F10: `rst_sync[0] <- ~rst_n` measured as one), `toggle`, `affine`, else `other`. A template needs ≥ `N_min` active lanes, else case-conditioned witnesses come first |
| Case literals (`other` only) | ≤ 4 from the depth-4 cone of `f_i` (TEMPO: 12.7 gates, 16.7 leaves on average, *measured*); on `A_i ∩ L(l)`, `f_i` is `q_j`, `¬q_j`, a constant or an opaque load (flipping `q_i` leaves `f_i` unchanged) |
| Duplicates | equal `f` signatures and async controls, confirmed by `Sat.equal` (TEMPO: 8, from `memory_dff`) |
| Grouping signature (F13) | clock root and edge, async class, and the *dominant* shared class (the class in `R_i ∪ H_i` that controls most flops); whole covers over-split because they include bit-specific literals (`time_q` bits 1, 2, 6, 10) |

### 3.3 Shift registers and synchronizers (Subramanyan'13; Wallat'17 chain walk)

**Copy edges.** An edge `j -> i` carries an inversion flag and holds under a condition `kappa`: the active condition of a `copy` or
`copy_inv` template, a copy case literal, or a **transparency condition** (F2, M8) — for any pair where flipping `q_j` flips `f_i` on
some lane, cofactor with `mk` in a scratch graph to get `T_i = f_i|q_j=1 ∧ ¬f_i|q_j=0`. Edges whose `T` are SAT-equal share a class.

**Shift structures.** Within one class, edges must form vertex-disjoint paths; a flop with two incoming edges ends its path. A shift
structure needs depth ≥ 3 (F7, M9); depth-2 transfers become relations, used only for order propagation. Paths are lanes of one
structure only if they have equal depth and heads of one kind (V2): a primary input, a flop outside the structure, a constant, or logic
over the structure's own bits. Lanes are cut between stages of different clock roots or edges, and in copy groups where the exact class
changes; a head fed by the structure's own bits makes an LFSR candidate (§3.5). **Synchronizers** follow §1: stage 0 is the flop loaded
from outside, its input net must be a pin, a black-box output, a latch output or a foreign-domain flop, and copy obligations prove the
order.

### 3.4 Counters (Subramanyan'13 topology; Gascón'14 templates)

**Candidates.** Sets `S` of at most 32 flops, deduplicated; over-generating is safe, as every claim is proven. Four generators: **(a)
Nested-support chains** — bit k's state support within `S` is bits 0..k plus a structural self-loop, so a binary counter's support graph
is triangular and its SCCs are singletons. **(b) Carry chains** (M10) — the lower bit's hold lies inside the higher bit's hold and the
lower `q` is in the support of the higher hold literal; no shared-signature condition (F6). **(c) SCCs of ≥ 2 flops, split by support
closure** (F6) — a block-triangular decomposition in which flops entering only through control literals (a sticky done flag) count as
external; cascades become relations between counters. **(d) Single toggles**; there is no own-bit activity filter (F5), and TEMPO's CRC
is one 32-flop SCC. A flop stays in a candidate only if, on active lanes, `f_i` depends on some flop of the candidate.

**Functional test** (F12). Take up to 16 lanes where some bit of `S` is active (pool or case-conditioned witnesses) plus 4 where all
bits hold, pinning every source outside `S`; enumerate all `2^w` states if `w ≤ 12`, else sample 4,096; label each (lane, state)
transition hold, constant, +1, −1, +c or other. The enable literal absorbs stops that depend on the state. **Order** (`w ≤ 12`): walk
orbits from the reset value if known, else from up to 64 origins; each raw bit's column must equal exactly one binary-weight column
(reversed for down counters), and every weight column must be determined. This yields the order `pi`, the step, and either the modulus
or the saturation value. For `w > 12` the order comes from nested supports and `T(q) − q ∈ {0, ±1}` is checked on the samples.

**Verdict.** Under one `pi`, every transition is +1/−1, hold, constant or +c and at least one counts; if varying +c dominates, the word
is an accumulator. The enable is the first of ≤ 8 literals (hold-class complements, transparency conditions) whose proof succeeds.
**Cases.** The structure names one `reset` case per synchronous clear or restart, in priority order, and one opaque `load` case per
reload, so that the required `hold` obligation still has states to be true on (§3.7): a counter that clears *and* reloads needs both
lists at once, which is what schema v2.1's case lists are for. The saturating, mod-M and cascade templates rest on synthetic cases only
(M15, §4.4).

### 3.5 LFSRs and CRCs (Wallat'17 candidates; textbook algebra)

**Candidates** (F1): SCC blocks from §3.4 (c) that fail the counter test (1-2 bit counters are also affine), and shift structures whose
head depends on their own bits. **Affinity.** Quadruples `(a, b, a⊕b, 0)` are drawn only from case-conditioned witness lanes (M5). The
linear set `V` starts as `S`; each other support source joins while affinity holds on 256 quadruples with every other source fixed; the
rest are parameters `P`. Step count and polynomial are found by probing (F1): `P = 0`, then each one-hot value, gives `A(p)` and `b(p)`
per mode. **Classification.** Fibonacci has one tap row, Galois one tap column, a serial input a data column; k steps means `A = C^k`
for the one-step matrix `C`, found by two exact root finders that accept a root only when `C^k == A`; modes are different matrices under
different case literals. The polynomial comes from `C` and primitivity from the order of `x`.

**Proof** (M7). The affine model is proven only at the probed settings: `poly = 0` and each one-hot, per mode. The programmable form
over all parameters is *matched (probed)*, status `unknown`, scope `probed`. TEMPO's CRC (`tempo_crc.v`) has programmable width, a
left-aligned `poly_l`, 1-8 steps per feed with one data bit per step, and an initial load.

### 3.6 Word grouping (DANA'20; shared controls from Tashjian'15, Subramanyan'13)

(1) **P0.** Partition flops by the exact §3.2 signature, with no thresholds. Pins give nothing on TEMPO: every `RESET_B` has its own
tiehi and `CLK` spreads over 239 CTS leaf nets *(measured)*. (2) **Lock.** Chosen structures and duplicate pairs become fixed words
(Klix); a multi-lane synchronizer is fixed one word per stage. (3) **Refine** the rest to a fixed point with DANA's predecessor and
successor passes: `pred(i)` is the set of blocks of flops in `supp(f_i)`, excluding control supports and `i`'s own block, `succ(i)`
mirrors it, unlocked blocks split by `(pred, succ)`, and a flop is isolated only if its `pred ∪ succ` is disjoint from its block's.
Nothing merges across P0. (4) **Propagate order** (Klix'24): a word that copies bit for bit from an ordered word under one class
inherits that order and vice versa; conflicts leave the word unordered, and propagated orders are labelled and unproven.

### 3.7 Verification (`tools/s3/verify.py`, contract v2.1)

`verify_result(nl, result)` runs in the harness (`run.py`) on the harness's own `GateGraph` of the netlist it pickled for the
recognizer. A structure's `proof.status` is the recognizer's **claim and is never trusted**. For the four `STRUCTURE_KINDS` the harness
**builds the defining templates itself** from the structure's kind, its `order` / `params.bit_order` and its `params`; the recognizer
supplies only the conditions in `structure["control"]` and, for `lfsr_crc` alone, one XOR expression per flop. A restatement of a flop's
own D therefore never verifies a structure, and unscored kinds never count as verified.

**Control keys** (`CONTROL_KEYS_BY_KIND`): `counter` — `when`, `when_down`, `reset`, `load`, `hold`, `inverted`; `shift_register` —
`when`, `reset`, `load`, `hold`; `synchronizer` — those four plus `input`; `lfsr_crc` — those four plus `inputs`. A key no kind knows is
malformed; a key outside its own kind's set is malformed **when it carries a value** (`null`, `[]`, `{}` and `false` are the uniform
placeholders the recognizer writes), so schema drift cannot pass silently either way. `COND = [{"net": id, "value": 0|1}, …]` is a
conjunction; `[]` means "always". The v2.0 single-case spellings are normalised to one-element lists and reported as `control_form:
"legacy"` (`LEGACY_CONTROL_FORM`) while the recognizer is moved over.

**Case lists and priority.** `reset` is a **list** of `{"when": COND, "value": {flop: 0|1}}`, so a counter that clears from several
places names one case each with its own value, and every flop needs a value in every case. Case *i* is checked on its own cube — its
COND with every **earlier** case and every load case removed — so list order *is* priority, exactly as an RTL `if/else` chain is: the
union of the reset cases is covered once, and a case a higher-priority one shadows is vacuous and refuses the structure. `load` is a
**list** of CONDs: opaque cases, allowed, never defining, and **nothing is checked under them**. Each load case's literal count, share
of random assignments and own bits read are reported, with the share of the state space their union hides (`load_hidden_share`), because
an opaque load is how a padded structure hides the states in which its passengers move. Limits: 64 reset and 64 load cases, 256 literals
per COND. **A named case's value claim is certified only on the cube the harness checked, which can be strictly narrower than the COND
printed beside it** — load cases shrink it — so a claim can be false over most of its own declared COND and still verify. The pair that
bounds that gap is `reset_cases[i].share` (the share of the COND as declared) against `lane_share["reset[i]"]` (the share of the cube
actually checked); `load_hidden_share` does *not* bound it, because it measures the whole structure and not one case.

**Defining region.** `D = when ∧ ¬(every reset case) ∧ ¬(every load case)`, with every async clear/preset of the structure's flops
pinned inactive and, for a counter whose top < 2^w − 1, the word assumed ≤ top. An "updown" counter's down case is `when_down ∧ ¬when`
under the same removals.

**Hold.** `control.hold` is **required** for `counter` and `shift_register`, and it is decided, not assumed: its region is outside EVERY
named case (`¬when ∧ ¬when_down ∧ ¬(each reset case) ∧ ¬(each load case)`, async controls inactive, in range), and every flop must keep
its value there. Emptiness is decided by SAT, never by syntax. An opaque **load** case may never be the thing that empties the region,
because a load case costs no evidence: a COND is a conjunction, so `¬when` is a disjunction of |`when`| single-literal CONDs that a load
*list* can name outright, and without the rule any structure could erase its whole hold obligation by a content-free rewrite of its own
control. **The cover is read off the cubes the harness *checked*, not off the case CONDs** — a reset case is checked only on its own
priority cube, which conjoins `¬(each load case)`, so the reset CONDs can empty the region at full size while the load-active part of
each reset case was checked by nothing. So (`HOLD_EMPTY_NEEDS_VERIFIED_COVER`) **an empty hold region is accepted, and reported as
vacuous, only when the cubes the harness CHECKED cover it**, decided by **two** tests: **(a)** the same region *without* the load
conjunct is unsatisfiable, **and (b)** no load case is satisfiable outside the defining cases. Both must answer unsatisfiable; **"sat"
on either** gives `hold_vacuous_cover = "load"` and **refuses** the structure (the reason string says which test), and an **undecided**
answer — solver `unknown` or the conflict budget — refuses it too, never assumed covered. Test (a) alone is necessary and *not*
sufficient: the rewrite that exploits it (T2, `out/s3/verify/hold_gate_t2.py`) turns each literal of `when` into its own lying reset
case and hides the lie behind a load, and passes (a) with zero hold obligations checked; test (b) is what refuses it. Test (b) is
vacuous when there are no load cases, so a free-running counter (`when = []`) and every load-free structure are unaffected — it is the
absence of load cases that makes it vacuous, not the kind: an up/down counter that does carry a load case is tested like any other. **The rule bounds the *shape* of the cover, not its *size*.** A *partial* complement leaves the region non-empty on a
sliver, and the obligation is then genuinely checked — on that sliver. What bounds the size is reported and never gated:
`lane_share["hold"]` for the region actually checked, `reset_cases[i].share` against `lane_share["reset[i]"]` for each named case, and
`load_hidden_share` for the share of the state space the load cases hide (measured on TEMPO's freeze run,
`out/s3/eval/runs/tempo-20260923T053247Z-ef7fc630631b.json`: mean 0.587, max 0.971 over the 4 verified structures carrying a load case,
mean 0.157 over all 15). A reader who wants "verified" to mean "verified over most of the space" must read those numbers; a floor on
any of them would be a tuned threshold and is deliberately not one of these rules. The verdict reports `hold_vacuous`,
`hold_vacuous_cover` and `nonvacuity["hold"]` either way and the summary counts `verified_vacuous_hold` and `hold_emptied_by_load`;
§4.4's change log records what the rule costs.

**Extent and liveness.** A structure may not be padded with flops that ride along.
* `counter`: width ≥ 2 (a 1-bit word is a toggle flop); `2^(w−1) < modulus ≤ 2^w` and a saturation limit ≥ 2^(w−1), so no claimed bit is
  dead by range alone; and, because a step of 2^k makes the low k template bits the identity, **every claimed bit must move** — `D ∧
  (template bit xor its q)` must be satisfiable for each bit. Dead bits refuse the structure, the live ones are reported (`live_bits`),
  and a template constant or independent of the word over [0, top] is refused.
* `shift_register`: depth ≥ 3, lanes of equal depth. `synchronizer`: ≥ 2 stages.
* `lfsr_crc`: the own-bit matrix, read as a digraph `j -> i` when row *i* reads column *j*, must be **strongly connected** over the
  structure's flops, and some row must XOR at least two own bits (else the matrix is a shift, a ring or a copy). Strong connectivity
  subsumes the v2.0 zero-row and dead-column rules and also refuses the weight-1 self row — a foreign flop that merely holds under
  `when`, carried as `{"equals": {"q": itself}}`.

**Coverage** (replacing the blanket self-conditioning ban). No condition the harness relies on — `when`, `when_down`, a reset case, a
load case, an async control of the structure's flops or a clock-gating enable — may depend on the structure's own state, except as
coverage admits: **the defining region must be satisfiable for every value of the structure's own word in range** (a counter's [0, top];
every own state otherwise). The check is exact and runs over the own bits the relied-on conditions read: one SAT call per assignment of
those k bits that some in-range word value realizes. Past `COVERAGE_MAX_OWN_BITS` = 12 read own bits the structure is refused
(conservative; refusing is never unsound). A wrap or reload at a terminal count is admitted; a case carved down to a few of the word's
own states is refused, which is what the old ban existed for. A clock-gating enable reading own state is refused outright: it is folded
into the effective next state, so no region has it as a conjunct and coverage cannot express it. **Reset cases are exempt from
coverage** and may read the own state freely; their only gates are non-vacuity on their own priority cube and the constant-value
obligation.

**Non-vacuity.** Every region the harness relies on — the defining case, the down case, each reset case, the hold region — must be
satisfiable with the reset and every async control inactive. Each case's share of 4,096 random source assignments is reported:
information, never a gate, since satisfiable means neither common nor reachable.

**Params.** What the harness pins it certifies; everything else it copies into the verdict and marks unchecked (`params_checked` /
`params_unchecked` per structure, `verified_with_unchecked_params` in the summary). **A parameter counts as certified only where the
harness actually read it.**
* `counter`: `direction`, `step`, `saturating`, `bit_order` (`PARAMS_CHECKED`, the template is built from them), and `modulus` where the
  template reads it — when `params.saturating` is an integer it *is* the limit, so a declared modulus that says something else is dead
  and is marked unchecked with its reason. `direction: "updown"` requires `control.when_down`; a `when_down` with any other direction is
  refused. `shift_register`: `lanes`, `depth`, `order`. `synchronizer`: `stages`, `order`.
* `lfsr_crc`: `poly` and `k_steps` where the own matrix admits it — a one-step Galois or Fibonacci companion is read straight off the
  matrix, and any declared (poly, k_steps) pair is checked exactly by `A == C^k` (Galois) or `A == (C^k)^T` (Fibonacci), in both stage
  orientations and with or without the `x^w` bit; `n_inputs` only at one step per clock; **`bit_order` only when the stage order was
  actually pinned**, i.e. when a one-step reconstruction or a declared pair matched (a match in the reversed orientation pins it only up
  to reversal). A declared value contradicting the matrix refuses the structure (`LFSR_PARAM_CHECK`); one the harness cannot reconstruct
  (programmable taps, form `affine`, `k_steps` null with a matrix that is not one step) is marked unchecked, never assumed right.
* Never certified for any kind: the LFSR's `form` (which of two readings of one matrix to report is a convention), the counter's
  `params.load` flag, the shift register's `direction` and `serial_in`, and `lanes_unordered`.

**What "verified" certifies.** For a structure S, exactly this: its flops share one clock root and edge; with every async clear/preset
of its flops pinned inactive and (for a counter with top < 2^w − 1) the word assumed ≤ top, the defining region D is satisfiable and —
exactly, by the coverage scan over the own bits the relied-on conditions read — is satisfiable at **every** own-word value in range;
over every assignment satisfying D each flop's effective next state equals the harness-built template bit; each counter bit's template
differs from its own q somewhere in D; the shape rules above hold; each named reset case, on its own priority cube, drives every flop to
its declared constant; and, if the hold region is non-empty, the flops hold there. **It certifies nothing under any load case**, nothing
about reachability over time (every region is decided by satisfiability, not by simulation from reset), nothing outside [0, top] when a
modulus or limit is claimed, and — for a synchronizer — nothing about clock domains beyond "a ≥ 2-deep unconditional copy chain whose
head samples a primary input, black-box output, latch output or foreign-domain flop". Nor does it certify the *name* a design would give
the structure: verification proves a template, so a shift register's first two stages satisfy a 2-stage synchronizer's obligations, and
a verified structure can still be a false positive against the truth (§4.2).

**Checks and budgets.** Each obligation "region -> a == b" is tried in order: identical literals; equal after substituting the region's
unit literals; equal GF(2)-affine forms over their leaves; for `lfsr_crc` claims a BDD with a label-ordered variable order (exact on a
relaxed space, so only its "unsat" is used, its "sat" being inconclusive); then SAT (z3, fresh context, conflict limits per check and
per run). The first four can only prove, never refute; only SAT returns "refuted". The CNF is built in a canonical order from
permutation-invariant structural labels, so a verdict is a function of the netlist and the structure, not of the id permutation. An
exhausted limit is `unknown`, an exhausted run budget leaves the rest `not checked`, and **wall time never decides anything**. Every
structure's JSON is size- and depth-checked before anything recurses into it and its sha256 is reported so a recorded run replays
(`replay()`); an exception while checking one structure is caught and reported as `malformed`, so one structure can never crash the
harness.

### 3.8 Output and parameters

`result.json` follows `schema.RESULT_SCHEMA`. Structures are disjoint (overlaps resolve by what the harness would verify, then by flops
explained, then by the more specific model, then by output order); each lane is ordered from its LSB, stage 0 or feedback stage;
`params` use `PARAMS` names; `control` carries §3.7's conditions; `proof` carries the recognizer's status and its claims (empty for
counters, shifts and synchronizers, whose templates the harness builds; one XOR expression per flop for `lfsr_crc`); `meta` carries
hashes, the reset, per-flop active-lane counts, relations.

**Parameters** (`tools/s3/params.py`; none names a width, modulus or polynomial of any design): pool 16,384 lanes (cap 49,152), biases
{1/8, 1/2, 7/8}, `rho` inactive in 15/16; synchronous-reset threshold 25 %; control class ≥ 2 flops; `N_min` 64, 16 lanes per literal
witness, ≤ 64 case witnesses per word; cover cap 4; case depth 4, cap 4; shift depth ≥ 3; exhaustive width 12; word cap 32; 16 + 4 test
lanes; 64 origins; 256 quadruples; the recognizer's own case caps (`RESET_CASES`, `LOAD_CASES`, `SHIFT_RESET_CASES`); SAT conflict
limits. The `HARNESS_*` group mirrors `verify.py`'s published limits (conflicts, COND size, minimum width/depth/stages, case caps,
coverage bounds) so a recognizer can stay inside them; mirrors are not tuning.

## 4. Evaluation (`tools/s3/score.py`)

### 4.1 Truth, join, units, disagreements

**Truth files** follow `schema.TRUTH_SCHEMA`, pass `check_truth()`, and are pinned by `truth_hash()`, which excludes timings; volatile
facts go to `truth_<design>.run.json` (V11).

| Item | Rule |
|---|---|
| Shared flops (V5) | a flop lists every register using it, primary = the widest; exact matches use each register's full flop set. Truth/1 split TEMPO's input chain (`mosi_meta`/`ui_sync0[2]`, `ui_sync1[2]`/`mosi_s`, `sck_meta`/`ui_sync0[0]`, `ui_sync1[0]`/`sck_s`, `sck_p`/`pins_prev[16]`), so only 9 of 11 synchronizer registers were scorable; truth/2 keeps all 11 |
| Parameters (V4) | stated by hand and checked by simulation: `dreg` (8 lanes, depth 4, toward the LSB, serial input `rx_byte = {rx_shift, mosi_s}`), `rx_shift`, `crc_l[0..1]` (Galois, programmable width and polynomial, `k_steps` 1-8, one input per step, initial load); modulus `2^w` for natural wrap and 4 for `bw`; unknown values null, leaving the denominator |
| Distinct designs (V8) | TEMPO's 22 counters are 14 distinct `design_key`s in 6 module definitions; its 2 CRCs are one *(measured)* |
| Units (V9) | explicit, each with a reason and one kind: TEMPO's 16 units (the `ui_sync0`+`ui_sync1` chains and their per-slice splits, the `CS`/`SCK`/`MOSI` chains, the `cfg_q` and `pc_we` splits), the puzzle's counter cascade. The puzzle's `meta.groups` (RTL module blocks) are not used |

**Join.** Each opaque id maps through the harness key to `Key.cell_name` (`master_x_y`), the truth's `flops` key. TEMPO's 2,832 netlist
flops partition into 2,824 register bits, 8 shadow flops and 0 unmapped, checked on a fresh extraction *(measured)*; the puzzle joins
92/92. A shadow flop is a synthesis duplicate a structure may include or omit without penalty; the 2 retimed flops form one kind-less
block, excluded from exact recall; the 10 one-hot FSM flops form one register.

**Known disagreements**, listed in every report: `st`'s one-hot transitions look like copies (4 flops); cross-register copy chains of
depth ≥ 3; the two-deep `toq_*` queues (`alt_kinds` shift) are never found at depth 2; `dreg` also has the `alt_kind` `data_register`;
the truth labels the input-fed third stages, `sck_p` and `pins_prev`, as `flag` and `data_register`; and 1-bit toggles are `flag` with a
`counter` alternative (§1), found but never verified.

### 4.2 Matching and metrics

**Matching** (V1, M12). Structures match truth items one to one, by IoU > 0.5 over flops and, for an item of ≥ 2 flops, at least 2
shared flops. Candidate pairs are taken greedily by IoU, then registers before units, then a harness-side hash of the structure's flop
set, then result position, then item name — never the recognizer-chosen id. **Strict** items are the registers (a synchronizer register
inside a declared chain unit is scored only through its chain units, which are items too); **lenient** items are every register plus
every declared unit. A match counts for kind `c` if the structure's kind is the item's kind (strict) or is in its `alt_kinds` or the
unit's kind (lenient); `alt_kinds` never remove a register from a denominator. **Found** means matched with the kind accepted, **exact**
equal flop sets with no dropped flop. **Precision** is found structures over structures of the kind, **recall** found registers over
registers of the kind; merges and splits are counted separately and never credited.

**Headline.** Per kind, as x/y and side by side: **found** over all structures, and **found and harness-verified** (§3.7), with exact
beside each, per instance and per distinct `design_key` (V8). The difference between the two is broken down by harness outcome —
`refuted`, `unknown` (a solver limit, reported apart), `vacuous`, `hold`, `coverage`, `template`, `params`, `form`, `self-conditioned`,
`malformed`, `budget`, and `not checked` for a structure with no verdict at all — so a report states *why* a found structure is not
verified instead of dropping it. A **honesty block** says what the verified count is worth: verified structures with a vacuous hold
region, the mean and max `load_hidden_share` of the verified set, those carrying dead bits or unchecked params, the kinds with no
per-bit liveness obligation, and the LFSR polynomials certified. **Bit level.** Per-flop labels (the kind of the flop's structure, or
none) give precision, recall and F1 per kind, a confusion matrix, and macro- and micro-F1 over `STRUCTURE_KINDS` (V8). Shift and
synchronizer false positives are reported by truth kind (V2); some are harness-verified, because verification proves a template and not
the truth's label (§3.7).

**Order** (V6). Kendall concordance over the pairs a structure orders, beside each item's chance rate under the same reversal rule, with
coverage and kappa. Counters must match their weights; shifts, synchronizers and LFSRs may match reversed. Width ≤ 2 is reported
separately; multi-lane structures are scored within and across lanes, and `params.lanes_unordered` leaves the across part unscored and
counted.

**Parameters** are scored only where the truth's `PARAMS` value is non-null, against a majority-value baseline on the same pairs;
LFSR/CRC parameters are case studies, not rates (V4). The metric is **split into certified and transcribed** (`PARAMS_CERTIFIED_RULE`):
a compared parameter is certified only when the harness verified the matched structure and named that parameter in the verdict's
`params_checked`; every other one is transcribed — copied from the recognizer's answer and never checked. The combined accuracy is kept
beside the two, never instead of them, so no published number says more than the harness proved. In the transcribed column by
construction: the LFSR's `form`, any unreconstructed `poly` / `k_steps` / `n_inputs` or unpinned `bit_order`, the counter's
`params.load` flag and a `modulus` an integer `saturating` makes dead, the shift register's `direction` and `serial_in`, and
`lanes_unordered`.

**Grouping** (V7, M13). AMI and ARI are the headline, beside singleton and random-block baselines; also reported: pairwise F1,
exact-word recall, splits and merges by kind over all flops and over width ≥ 2, the harness outcome counts, runtime and peak RSS per
stage.

### 4.3 Baselines and ablations

**Class baselines** (V8): majority class, and a structural baseline with no simulation or SAT (chains of ≥ 3 flops whose `f` is another
flop's `q` through buffers are shifts; triangular-support sets with self-loops are counters). **Grouping baselines:** singletons, random
blocks, `CLK`/`RESET` net grouping, P0 alone. **Ablations:** no witnesses, no transparency conditions, placement clustering (scorer
only).

### 4.4 Development, freeze, evaluations

**Development** uses TEMPO (always from the frozen snapshot `out/s3/tempo_snapshot`; any other `TEMPO_ROOT` is refused) plus a synthetic
corpus of small RTL, each case labelled by its own names.

| Group | Synthetic cases |
|---|---|
| Counters | binary, up/down, modulo, saturating, loadable, enable in carry, compare-stopped, mod-M cascade with sticky done, 1-bit toggles (`flag` + `alt_kinds`) |
| Shift registers | single-lane, multi-lane, loadable, multi-source with priority loads |
| LFSRs and CRCs | Fibonacci, Galois, serial, k per cycle, programmable, variable step count |
| Mixed / negatives | two independent chains under one enable; one-hot FSM; register file written from one data register; two-stage pipeline; accumulator; sticky flags |
| Mutations | off-by-one step; moved tap; swapped stages; mutated carry |

| Protocol step | Rule |
|---|---|
| Change log (V0) | `tools/s3/changes.jsonl`: one dated entry per design or parameter change after 2026-09-21, naming the path and sha256 of the TEMPO, corpus or regression output that motivated it, saved before the change, with `tuned_on` naming the designs it was fitted to. Every rule taken from a review is justified by a TEMPO measurement (§3.0) or a synthetic case, never by the puzzle |
| Evidence hashes | `freeze.record_evidence()` re-hashes every path the change log and the contamination record cite. A **change-log** hash is a *snapshot* — the value as of that entry — so a later edit of the same file is reported as `moved` and is **expected, not a fault**. A **contamination-record** hash is a claim about what the corpus and the development data *are*, so a changed file is `stale` and blocks the freeze (`--force` only). A missing path is reported only: transcripts and scratch outputs are rotated, and one lost artifact (C54) cannot be restored |
| Corpus split | `corpus.splits()`: within each (cohort, family), designs sorted by `sha256(name)`, the first `(n + 1) // 4` **holdout**, the rest **train**. Two corrections sit on top and both only ever move a design towards train: every `corpus.FITTED_ON` design (one whose measurement set a threshold) is forced into train, and every `corpus.DROPPED` design is not in the corpus at all. Grouping by cohort keeps every cohort-1 design in the split it had before cohort 2 existed, so a design never changes sides and no published figure is quietly re-based. `corpus.manifest()` re-stamps a manifest built before a correction and reports the corrections |
| In-sample vs out-of-sample | TEMPO is the development design — thresholds were selected on it and fixes traced from its misses by truth name — so **every TEMPO figure is in-sample and fitted**, and `score.py` labels it IN-SAMPLE on every report. The **corpus holdout** is the only out-of-sample estimate, published as `out/s3/honesty/holdout_rates.json` and printed beside the TEMPO figure. `score.out_of_sample()` refuses a document with no rates, or one derived on other code than this tree: every file of `score.OUT_OF_SAMPLE_SOURCES` (the recognizer modules, `verify.py`, `corpus.py`, `score.py`) must hash as it did when the rates were derived. A refused estimate is reported as absent with the command that rebuilds it, never printed, and the pre-freeze checklist blocks on the same condition. A report must name which evaluation each number came from and never present one as the other |
| Contamination record (V0, F15) | `out/s3/contamination.json`, pinned in `FREEZE.json`: the prototype ran loader, simulation, SAT sweeping and reset discovery on the puzzle; both reviews probed the puzzle netlist; V predicted one puzzle failure (two chains under one select merged into one structure), which §3.3's lane-head split avoids, adopted on its synthetic case and recorded as puzzle-informed; the saturating, mod-M and cascade templates are synthetic-only (M15). It also records the two limits that belong in every quotation of the holdout estimate: the corpus is **synthetic and written by this project** (cohort 2 from the first regression set's findings), and **both** generalisation regression sets (`out/s3/review_generalisation`, `out/s3/review_generalisation2`) are no longer held out, because recognizer and harness thresholds were fitted on them |
| Blind candidates | `out/s3/blind/candidates.json` is the canonical list (`python -m tools.s3.thirdparty scan`); `FREEZE.json.blind_candidates` pins its path and sha256, `freeze.check()` fails if it changes, and `thirdparty.draw()` re-checks its own `candidates_sha256`. `out/` is git-ignored, so the lead **force-adds it in the freeze commit** beside `FREEZE.json` and `contamination.json`. It was registered before recognizer development by criteria that look at no design's structure, but it was not committed then: the record states that its precedence rests on those fixed criteria and the registration date, not on a commit |
| Eligibility | `thirdparty.py`'s criteria C1-C7, fixed before development: a sky130 TT project with repo and commit and no analog pins; not ours, not the puzzle, not a design inspected in this study (`INSPECTED`); layout and gate-level netlist in the shuttle repo; every logic cell `sky130_fd_sc_hd` and ≥ 40 flops; Verilog/SystemVerilog sources present, instantiating no flop or latch cell by hand; an open licence; one entry per design. After the draw, a design the frozen labeller cannot label is replaced by the next reserve and reported |
| Freeze | a git commit by the lead of every `tools/s3/*.py`, `tools/s3/changes.jsonl`, this document and the two test files (`test/test_s3.py`, `test/test_s3_verify.py`), plus (force-added, because `out/` is git-ignored) `out/s3/FREEZE.json`, `out/s3/contamination.json`, `out/s3/blind/candidates.json` and the two git-ignored artifacts the contamination record pins as stale-blocking evidence and every report must be able to quote: `out/s3/honesty/holdout_rates.json` (the out-of-sample estimate, K13/K14) and `out/s3/prior_art.md` (§7, K9) — **and the measured artifacts this document cites by path** (`freeze.PUBLISHED_FIGURE_RELS` and the TEMPO evaluation record: `out/s3/honesty/honesty_table.json` and `honesty_table.log`, `out/s3/honesty/summary.json`, `out/s3/honesty/params_coverage.json`, `out/s3/eval/runs/tempo-<utc>-<hash>.json`), because without them not one published figure is readable from the freeze commit (lead's decision, 2026-09-23). The change log's own evidence files are deliberately **not** force-added: a `changes.jsonl` entry's evidence is a dated snapshot, every entry cites such paths, and `FREEZE.json.records` pins the log itself by sha256. `freeze write` prints exactly that command, and `freeze checklist` prints the order in which the last edits, the record writers and `freeze write` must run (`freeze.FREEZE_ORDER`): editing this document or `tools/s3/params.py` makes the contamination record's evidence `stale`, which `freeze.write()` refuses, and editing any file of `score.OUT_OF_SAMPLE_SOURCES` invalidates the published holdout estimate, which the checklist blocks on — so the record writers run after the last edit and `freeze write` last of all, and within them `write_contamination.py`, then the `changes.jsonl` entries, then `summarise.py` **twice** (it embeds `record_evidence()` live while entries cite `summary.json` back by sha256, so one pass does not converge). `freeze.check()` still verifies only `FREEZE.json`, the `tools/s3/*.py` it pins and the two records as committed; the other paths are the lead's to add, and `git show --stat HEAD` is the check that they landed. `FREEZE.json` holds: sha256 of every `tools/s3/*.py` and `tools/retrace/*.py`; package versions; `truth_hash()` of every frozen truth; per pinned design the sha256 of every extraction input and the canonical hash of the seed-`None` netlist; `score.class_map()` and every scoring constant; `git_head`; a 128-bit `os.urandom` blind seed; the candidate list's path and hash; the draw; `PROTOCOL`; the hashes of both records; the contamination record itself; `record_evidence()`; and `freeze_hash` over all of it |
| Runs | `run.py --blind` refuses to start on any freeze mismatch, on an uncommitted blind ledger, or on a second attempt of a design without `--rerun-reason`; it writes an attempt record before extracting and appends its hash to `out/s3/blind_ledger.jsonl` (each line carrying the previous line's hash), which the lead commits after every attempt. Blind records go to `out/s3/runs/blind-<design>-<utc>-<id>.json` and development records to `out/s3/eval/runs/`; nothing is overwritten |

**Frozen evaluations**, in order: (1) TEMPO and its robustness variants, now inside the freeze (V0): RTL re-synthesised with other
Yosys/ABC settings, and `tools/retrace/mutate.py` extraction faults; (2) the puzzle, once, as "frozen code, known design"; (3) the blind
set — N designs drawn with the freeze seed (the download needs the user's approval), labelled by `tools/s3/thirdparty.py`
(`truth_tempo.py`'s rules and z3 mapping proof made design-agnostic: no manual overrides, `alt_kinds` and units only from rules, the
toggle rule included), scored singly and pooled. Labels are fixed before scoring; later disagreements are listed, never applied.

**Blind-set feasibility.** The shuttle repositories publish per-project GDS/OASIS, LEF and gate-level netlists and link each project's
HDL repository; none publishes a per-project DEF, so extracted instances join netlist instances through GDS property 61, which every
std-cell reference carries (checked net by net). The blind harness must strip every top-level text label but the TT pinout and those
properties before the recognizer sees a layout. The labeller is validated by relabelling TEMPO and comparing with `truth_tempo.json`,
and on flow probes and a pilot run on designs then excluded from the candidate list. If none of the N designs passes, `docs/S3.md` says
the blind set proved infeasible and why, and the evaluation rests on TEMPO and the puzzle.

**Reporting.** A later `docs/S3.md` lists every miss and false positive with its cause, shows strict and lenient scores side by side,
reports found and verified apart everywhere, and names the truth judgement calls that swing a number.

## 5. Performance (budgets are estimates until measured)

Measured basis (prototype): extraction 18.7 s, 1.97 GB; `Netlist` + `GateGraph` 0.25 s; z3 checks median 0.85 ms, max 20 ms (F's figures
are M7).

| Stage | Budget (estimate) |
|---|---|
| Extraction (existing; pickle cacheable) | 25 s, 2.5 GB (measured: 19 s, 2.0 GB) |
| Load, graph, pool, reset, literal classes, literal witnesses (≤ 8,000 SAT calls) | 40 s |
| Profiles and covers; transparency conditions and case-conditioned witnesses | 90 s |
| Recognizers and grouping | 35 s |
| Recognizer-side proofs, including 528 CRC miters (2 words × 33 poly settings × 8 step counts) | 120 s |
| **Recognizer, excluding extraction** | **≤ 5 min, ≤ 1.5 GB** |

The puzzle must take at most 10 s. Harness verification is budgeted separately by conflict limits (`CONFLICTS_PER_CHECK`,
`CONFLICTS_PER_RUN`, `COVERAGE_CALLS_PER_RUN`). Wall time is reported but never decides a result; a stage exceeding twice its budget
fails a benchmark test.

**Measured at the freeze** (TEMPO, `--leakage --permutations 5 --jobs 3`, one 18-core host, record
`out/s3/eval/runs/tempo-20260923T053247Z-ef7fc630631b.json`): extraction and load 17.9 s; **recognizer 211.5–219.8 s per arm**, child
peak RSS 1.47–1.65 GB (self-reported); harness verification 2.9–5.0 s per arm; scoring 0.12–0.20 s per arm; whole run 473.4 s wall,
harness peak RSS 1.96 GB. The recognizer is therefore ≈ 3.7 min against the ≤ 5 min budget and inside 1.5 GB only on the lower arms —
the RSS budget is the one that is not met, and it is reported rather than adjusted. The corpus evaluation (336 runs, 5 workers) is
56.4 s wall (`out/s3/honesty/corpus_holdout_eval.json`); its memory is not recorded, so no figure is given for it. Wall times are
wall times: they move between runs on the same host and are reported, never gated.

## 6. Residual risks

Most risks are handled where they arise. Five stay open and are reported, not tuned away: templates checked only on synthetic cases
(M15); the unproven programmable CRC form (M7); the known disagreements (§4.1); a blind set that may prove infeasible or be mislabelled
by rule (§4.4); and **the hold ceiling** — on TEMPO the recognizer finds all 22 counters and the harness certifies fewer than half of
them (**9 of 22** on the freeze code state, `out/s3/eval/runs/tempo-20260923T053247Z-ef7fc630631b.json`, the same figure under each of
the 5 permutations and the file-order arm; the other 13 are refused with reason bucket `hold`), because the count condition is a long
cube pinning a reload register whose complement is
not a bounded set of cubes, so no set of verified cases covers the space and the required `hold` obligation cannot be discharged. This
is accepted as a limitation of the freeze, not closed by widening the contract: it is a `controls.py` enable-net problem, and every
report states found and verified separately with this reason (`score.HOLD_CEILING_NOTE`).

## 7. Relation to prior art (`out/s3/prior_art.md`)

**Borrowed, not claimed:** DANA's flop graph and predecessor/successor refinement (Albartus et al., TCHES 2020) with NMI and purity
(Meade et al., JHSS 2018); topology plus SAT for counters and shift registers and grouping by identical controls (Subramanyan et al.,
DATE 2013); functional control recovery (Li et al., HOST 2013; Tashjian and Davoodi, DAC 2015); modulo-counter templates (Gascón et al.,
FMCAD 2014); SMT-verified structures with bit order and order propagation (Klix et al., CCS 2024); chain-based LFSR detection (Wallat et
al., IVSW 2017); FRAIG sweeping (Mishchenko et al., 2005); per-class F1 and whole-design hold-out (SPHINX, GLSVLSI 2026; ReIGNN, ICCAD
2021); the SoK's benchmark practice (Karadağ et al., TCHES 2026).

**What this may add** (gaps only in what our searches found): (1) scoring every flop of an anonymous netlist extracted from real
sign-off GDS against RTL truth, where published evaluations use synthesised netlists that keep their names; (2) recognise-then-verify,
where the harness — not the recognizer — builds each kind's defining templates and checks them under extent, liveness, coverage and hold
obligations a padded or carved-out structure cannot pass; (3) LFSR/CRC characterisation as a classified GF(2) matrix whose polynomial is
reconstructed and compared with the claim; (4) pin-less control recovery measured on 2,832 labelled flops, a measurement rather than a
method.

## 8. Implementation order

0. The lead registers `out/s3/blind/candidates.json` before any recognizer code and force-adds it in the freeze commit.
1. Truth/2 migration of both generators (§4.1) until `check_truth()` is clean.
2. `netlist.py`: cone-restricted `Sim`, conflict-limited multi-copy `Sat`, scratch-graph templates and cofactors, structural pool seeds;
   black-box pin anonymisation in the harness.
3. `run.py`, `test/test_s3.py` and `score.py` with every baseline, so each later step is measured; then the synthetic corpus, negatives
   included, with its train/holdout split.
4. `controls.py` (§3.1-3.2), on the synthetic corpus first, then TEMPO, re-checking M1-M4.
5. Recognizers stating the §3.7 control conditions, and `verify.py` checking them independently: shifts and synchronizers (with
   transparency conditions), counters, LFSRs and CRCs.
6. Grouping and propagation; a TEMPO development run and report; the change log throughout.
7. `thirdparty.py`'s automatic labeller, validated on TEMPO.
8. The freeze (lead), then the frozen evaluations of §4.4.
