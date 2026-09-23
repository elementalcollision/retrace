# S3 replication — a second blind draw of ten Tiny Tapeout designs

**What this is.** `docs/S3.md` reports the first blind evaluation of RETRACE's S3 recognizer on ten third-party
Tiny Tapeout designs drawn under freeze 1 (commit `232cfe6`). This report repeats it on ten more, drawn under
Freeze 4 from the candidates freeze 1 did not spend and run on recognizer, verifier, scorer and corpus code
byte-identical to freeze 1's. `docs/S3_REPLICATION_PLAN.md` fixed the primary outcome, the interval method and the
verdict words before the seed existed, and this report follows it. Three sets are named apart throughout: **R**,
the ten Freeze-4 designs; **B1**, freeze 1's ten, recomputed from their committed records; and the **pooled set**
B1 + R, twenty designs.

**The answer in one paragraph.** The primary outcome is `counter` harness-verified found recall over registers
(strict). On R the harness verified the matching structure for **19 of 49** counter registers (0.3878,
design-level bootstrap 95% [0.2245, 0.6286]). On B1 it was **23 of 59** (0.3898, [0.2162, 0.6458]). R − B1
is **-0.0021**, bootstrap 95% **[-0.3121, 0.2853]**. That interval contains 0, so under the plan's rule R is
**consistent with freeze 1**. The replication cannot tell R from B1, which is not the same as showing the rates
equal: any difference inside that interval fits these twenty designs. Over the pooled set, 42 of 108 counter
registers are harness-verified found (0.3889; [0.2617, 0.5517] resampling designs within each set,
[0.2583, 0.5534] resampling the 20 as one set). R is too thin in the other kinds to read a rate: strict
`shift_register` 4 of 9 found (3 harness-verified), `synchronizer` 6 of 10 (all 6 harness-verified), no
`lfsr_crc` register. R has 27 misses among its 68 scored registers and 34 false positives among its 72 scored-kind
structures, 18 of the 34 harness-verified. B1's cause codes cover 16 of the misses and 18 of the false positives; of
the 27 cases that needed new codes, 14 are one module of one design, met seven times. Every harness refusal, in R as
in B1, is on the hold obligation. The pooled counter verified-found figure of 0.3889 sits under both corpus-holdout
references (28 of 44 = 0.6364 and 26 of 40 = 0.6500, §7), which come from synthetic designs this project wrote, one
of them counting a different item set. Their own independence-assuming intervals overlap both pooled bootstrap
intervals, so this is not a design-level separation.

**Sources.** Result figures come from `out/s3/replication/analysis/numbers.json` (rendered as `numbers.md`, written
by `compute_numbers.py`), with keys in brackets for the important ones. Cause counts come from `causes.json`,
whose miss and false-positive lists are asserted equal to `numbers.json`'s. §1's pre-draw facts come from
`out/s3/FREEZE.json`, the plan and git, and §3.3's disagreement figures from `xcheck_compare.json`.

---

## 1. What was fixed before the draw

| Time (UTC, 2026-09-23) | What | Where |
|---|---|---|
| 15:30:10 | The analysis plan: primary outcome, interval method, verdict words | `docs/S3_REPLICATION_PLAN.md`, commit `95f7eff` |
| 15:38:55 | Freeze 4 written: freeze `1196c56304e3`, seed `36818e09a9555c29aa45b6917dbce15f` (`os.urandom`, drawn at write), `n` = 10, `max_reserves` = 10 | `out/s3/FREEZE.json` |
| 15:39:34 | Freeze 4 committed; change-log entry `R01` records the draw's preconditions | commit `0aa0698` |
| 16:25:45 | R's labels written | `out/s3/blind/labels.json` (committed with this report, §6), copy at `out/s3/replication/labels.json` |
| 16:27:32 – 16:52:00 | The ten R run records created, one commit per run | commits `511ffe2` … `43623c6` |

**The draw.** `FREEZE.json` `draw.excluded` lists the ten B1 designs as spent (contamination K16), computed once by
`freeze.spent_designs()` (Freeze 3, `F06`) and recorded under `freeze_hash`, leaving 74 candidates eligible
(`draw.eligible`). The ten with the lowest `sha256(seed|id)` are drawn and the next ten, in order, are reserves.
`python -m tools.s3.freeze draw`, run again for this report, prints the same twenty ids as `numbers.json`
`E_mechanics.labelling`. **Three drawn designs were freeze-1 reserves:** `tt04/tt_um_jayraj4021_SAP1_cpu`,
`tt06/tt_um_kwilke_cdc_fifo` and `ttsky25b/tt_um_ieeeuoftasic_simproc`. Freeze 1 used and fetched none of its
reserves (`docs/S3.md` §17), and `spent_designs()` counts reserves that were used, never ones merely listed, so
these three were unseen and eligible. No R design has a ledger attempt under any other freeze
[`E_mechanics.ledger.per_design.*.ledger_attempts_under_any_other_freeze`].

**Code identity, the pooling precondition.** All 10 R records carry the 12 `score.OUT_OF_SAMPLE_SOURCES` hashes and
the 10 `recognizer_sources` hashes byte-identical to B1's: 0 mismatches, and no design is left out of pooling
[`A_pooling_precondition.holds_for_all_10`]. The hashes also equal the current tree and `FREEZE.json`'s `code`, and
both references were measured on this code (`score.out_of_sample_problem()` is `None`). Three files outside the
precondition differ from B1 in every R record: `tools/s3/freeze.py`, `run.py` and `thirdparty.py`, all changed by
Freezes 2 and 3. For `thirdparty.py`, `git diff 232cfe6 0aa0698` touches only `draw()`'s exclusion, its command
line and docstrings. RETRACE's extractor, outside the records' code block, also changed (Freeze 2, `F02`;
limitation 4).

---

## 2. The draw and its labelling

R was labelled by the frozen labeller, `tools/s3/thirdparty.py` under Freeze 4 (sha256 `d6ab80d8…`, equal to the
records' hash [`E_mechanics.labelling.labeller_equals_record_code_thirdparty`]), through freeze 1's
`out/s3/blind/label_driver.py` and with no manual overrides. No hash of the driver exists: both labels files list it
as a helper, not frozen, so "unchanged" rests on its file time, which is earlier than freeze 1's labels (written
06:50:45Z). The per-design rows were assembled into `labels.json` by `out/s3/replication/make_labels_r.py`, a copy
of freeze 1's `out/s3/blind/make_labels.py` adapted for replacements, also a helper and not frozen. The pipeline
failed on two drawn designs, and three reserves were used [`E_mechanics.labelling.reserves_used`]:

| Drawn # | Design | What the frozen pipeline did | Replaced by |
|---|---|---|---|
| 2 | `ttsky26c/tt_um_tpcannon7_fir` | `RuntimeError: check_truth: ['spi.tx_buf: lanes x depth != flops']` | reserve 1, `ttsky26b/tt_um_tiny_8bit_cpu` |
| 10 | `ttsky26b/tt_um_fidel_makatia_digital_tapeout` | `RuntimeError: check_truth: ['u_soc.u_uart.shift_reg: lanes x depth != flops']` | reserve 2, `tt08/tt_um_zoom_zoom`, which also failed (`ValueError: unexpected gate $print`); then reserve 3, `ttcad25a/tt_um_space_invaders_game` |

No design was replaced for looking hard: `tt06/tt_um_SJ` (R's weakest labels) stays, and so does
`ttsky26b/tt_um_tiny_8bit_cpu`, which has no scored-kind register but is one of R's ten designs in every bootstrap.

| # | R design, in run order | Netlist flops | Truth registers | `counter` regs / found / verified-found | `shift_register` regs / found / verified-found | `synchronizer` regs / found / verified-found | Tier A of scored regs | AMI |
|---|---|---|---|---|---|---|---|---|
| 1 | `tt04/tt_um_jayraj4021_SAP1_cpu` | 53 | 9 | 1 / 1 / 1 | – | – | 0 of 1 | 0.9248 |
| 2 | `ttsky26b/tt_um_tiny_8bit_cpu` | 308 | 32 | – | – | – | – | 0.9850 |
| 3 | `tt06/tt_um_SJ` | 685 | 109 | 12 / 3 / 2 | 1 / 0 / 0 | – | 4 of 13 | 0.7592 |
| 4 | `tt06/tt_um_kwilke_cdc_fifo` | 158 | 39 | 2 / 2 / 0 | – | – | 0 of 2 | 1.0000 |
| 5 | `ttsky25b/tt_um_yorimichi_kittscanner` | 113 | 28 | 4 / 2 / 2 | 2 / 1 / 1 | 1 / 1 / 1 | 0 of 7 | 0.5700 |
| 6 | `tt05/tt_um_digital_clock_sellicott` | 305 | 38 | 8 / 7 / 7 | 4 / 2 / 1 | – | 1 of 12 | 0.8265 |
| 7 | `tt05/tt_um_nickjhay_processor` | 201 | 188 | 1 / 1 / 0 | – | 1 / 0 / 0 | 0 of 2 | 0.0307 |
| 8 | `ttsky25b/tt_um_ieeeuoftasic_simproc` | 706 | 99 | 4 / 4 / 1 | – | 2 / 2 / 2 | 0 of 6 | 0.9607 |
| 9 | `ttsky26a/tt_um_parakeet` | 77 | 18 | 5 / 2 / 2 | 1 / 1 / 1 | 3 / 3 / 3 | 0 of 9 | 0.8599 |
| 10 | `ttcad25a/tt_um_space_invaders_game` | 197 | 76 | 12 / 9 / 4 | 1 / 0 / 0 | 3 / 0 / 0 | 7 of 16 | 0.6438 |
| | **R total** | **2,803** | **636** | **49 / 31 / 19** | **9 / 4 / 3** | **10 / 6 / 6** | **12 of 68** | |

R has 68 structure-kind registers against B1's 94, 49 counters against B1's 59, and no `lfsr_crc` register. Of
R's 2,803 netlist flops, 2,727 carry a label. The rest are `tiny_8bit_cpu`'s 72 unmapped and 4 shadow flops
[`E_mechanics.per_design[1].join`], all inside structures of unscored kinds (§6). The label proof is complete on
4 of R's 10 designs [`E_mechanics.labelling.counts.proof_complete`].

**Label quality**, tiered exactly as `docs/S3.md` §4 (Tier A: a mapped bit z3-refuted or mismatching simulation)
[`D_label_quality.R`]. Of R's 68 structure-kind registers, 12 are Tier A (5 A1, 7 A2), 3 Tier B and 53 clean, and
10 of the Tier A registers are counters. At flop level, 52 of R's 545 labelled structure-kind flops have a refuted
mapping proof, 27 of them also mismatching in simulation. B1 has 23 Tier A registers of 94 and 209 refuted flops
of 885, 112 of them mismatching. R's refutations sit in `SJ` (20 of 38 flops, all mismatching), `space_invaders`
(25 of 91, none mismatching) and `sellicott` (7 of 236). A refutation means a label is not established, not that
its kind is wrong.

---

## 3. The primary result

### 3.1 `counter` harness-verified found recall over registers (strict)

| Set | Designs (with a counter) | Counter registers | Harness-verified found | Rate | Bootstrap 95% (the plan's interval) | Clopper–Pearson 95% (independence-assuming) |
|---|---|---|---|---|---|---|
| R | 10 (9) | 49 | 19 | 0.3878 | [0.2245, 0.6286] | [0.2520, 0.5376] |
| B1 | 10 (10) | 59 | 23 | 0.3898 | [0.2162, 0.6458] | [0.2655, 0.5256] |
| **R − B1** | | | | **-0.0021** | **[-0.3121, 0.2853]** | Fisher's exact two-sided p = 1.0000 |
| Pooled B1 + R | 20 (19) | 108 | 42 | 0.3889 | [0.2617, 0.5517] within each set; [0.2583, 0.5534] as one set of 20 | [0.2966, 0.4875] |

[`B_primary`.] The bootstrap resamples designs with replacement and recomputes the pooled ratio (10,000 resamples,
NumPy `default_rng(20260923)`, percentile 95%, none undefined). Fisher and Clopper–Pearson treat registers as
independent, which registers in one design are not: they are the first report's comparison, printed beside the
primary interval, not in its place. The recomputed B1 figure equals the plan's 23 of 59.

**Verdict, in the plan's words: consistent with freeze 1.** The 95% bootstrap interval of R − B1,
[-0.3121, 0.2853], contains 0 [`B_primary.verdict`].

The interval is wide because a few designs carry most of the counters. `SJ` and `space_invaders` hold 12 of R's
49 each, and `sellicott` supplies 7 of R's 19 harness-verified found. In B1, `Reloj_top` holds 14 of 59 and
`vzayakov_top` 12, all 12 found but only 2 harness-verified. Per-design rows for both sets are in `numbers.md` §B.

### 3.2 With Tier A registers removed

As the plan requires, the primary outcome is also reported over counter registers that are not Tier A
[`D_label_quality.primary_with_tier_A_removed`]. On R it is 16 of 39 (0.4103, bootstrap [0.1579, 0.6750]), and on
B1 21 of 48 (0.4375, [0.2203, 0.7297]). R − B1 is -0.0272, bootstrap [-0.4143, 0.3168]; Fisher two-sided p
(R vs B1, independence-assuming) is 0.8304. Over the pooled set it is 37 of 87 (0.4253; [0.2545, 0.6234] within
sets, [0.2500, 0.6190] as one set). The R − B1 interval contains 0 here too; the plan's verdict words belong to the
primary outcome alone.

### 3.3 Choices the plan left open, and the independent recomputation

**No departure from the plan was found.** The plan fixes the resampling unit, resample count, generator, seed and
percentile interval, and is silent on three choices, which `numbers.json` `definitions.bootstrap` records. Each
interval uses a fresh `default_rng(20260923)`. For a two-set statistic, B1's index matrix is drawn before R's from
one generator, and R − B1 and the stratified pooled ratio share those resamples. The pooled interval is given both
within sets and as one set of 20, and no verdict depends on which is used.

A second pass recomputed 216 figures from the raw records without reading `compute_numbers.py`
(`xcheck_compare.json`). It agreed on 213: the pooling precondition; every count it recomputed (per-design and
per-kind counts, tiers, and the Tier-A-removed counts); the single-set and pooled intervals, Fisher p and
Clopper–Pearson bounds of the primary, of counter all-structures found and of the primary with Tier A removed;
R's and B1's grouping AMI figures; the verdict; and its B1-first re-draw of the three R − B1 intervals below. It
did not recompute the exact, per-kind or Tier-A-removed-found intervals, the pooled grouping figures, §7's
reference tests, or the harness-result, parameter, order or cause figures. It also re-implemented `score.py`'s
matching and crediting and reproduced every record's `found_registers` lists for all 20 designs (`xcheck.json`
`checks.own_matching_mismatches` is empty). **It disagreed on three R − B1 bootstrap intervals.** For the primary
it got [-0.3067, 0.2931] against the canonical [-0.3121, 0.2853]. The counter all-structures and Tier-A-removed
R − B1 intervals differ for the same reason: the second pass drew R's matrix first. Drawing B1's first, it
reproduces all three canonical intervals exactly. **Both are correct implementations of the plan**, which does not
fix the order. This report quotes the canonical intervals because their scheme is documented and reproduces
exactly. The gap is Monte Carlo noise, and both primary intervals contain 0. The plan fixes a verdict only for the
primary outcome. Whether its three forms (R, R − B1, pooled) carry over to the Tier-A-removed primary and to the
secondary outcomes is open to reading, so this report gives all three forms wherever the data allow; those R − B1
intervals (§3.2, §4.1, §4.2), and §7's Fisher and Clopper–Pearson figures, are descriptive and carry no verdict
word.

---

## 4. Secondary results (descriptive)

### 4.1 `counter`: all structures, and exact

| Over counter registers | R | B1 | R − B1 (descriptive, §3.3; the primary's is the plan's) | Pooled B1 + R (within sets) |
|---|---|---|---|---|
| Found by any structure | 31/49 = 0.6327 [0.4237, 0.8627] | 41/59 = 0.6949 [0.5000, 0.8904] | -0.0623 [-0.3492, 0.2438] | 72/108 = 0.6667 [0.5238, 0.8182] |
| Harness-verified found (primary) | 19/49 = 0.3878 | 23/59 = 0.3898 | -0.0021 [-0.3121, 0.2853] | 42/108 = 0.3889 |
| Exact, any structure | 20/49 = 0.4082 [0.2424, 0.5862] | 28/59 = 0.4746 [0.1746, 0.7963] | [-0.4294, 0.2836] | 48/108 = 0.4444 [0.2600, 0.6456] |
| Exact, harness-verified | 12/49 = 0.2449 [0.1111, 0.4483] | 15/59 = 0.2542 [0.0746, 0.5490] | [-0.3356, 0.2605] | 27/108 = 0.2500 [0.1250, 0.4184] |
| Found, Tier A removed | 22/39 = 0.5641 [0.2889, 0.8636] | 37/48 = 0.7708 [0.5652, 0.9429] | -0.2067 [-0.5439, 0.1578] | 59/87 = 0.6782 [0.4925, 0.8514] |

[`C_secondary.counter_all_structures_found_recall`, `.per_kind_bootstrap.counter`,
`D_label_quality.counter_all_structures_found_with_tier_A_removed`.] Every R − B1 interval here contains 0, and
the Fisher p (R vs B1) for all-structures found is 0.5423. Removing Tier A widens the all-structures gap to -0.2067,
because Tier A counters were found 9 of 10 times in R but 4 of 11 times in B1, so removing them lowers R's rate
(31/49 to 22/39) and raises B1's (41/59 to 37/48). The harness-verified gap barely moves (-0.0021 to -0.0272),
because in both sets the Tier A counters were rarely harness-verified (R 3 of 10, B1 2 of 11), so removing them
raises both verified rates, R's from 0.3878 to 0.4103 and B1's from 0.3898 to 0.4375
[`D_label_quality.R.counter.outcome_by_tier`, `D_label_quality.B1.counter.outcome_by_tier`].

### 4.2 Per kind, found and verified, strict

| Kind | Set | Registers (designs) | Structures | Found regs | Verified structures | Verified-found regs | Exact / verified exact | False-positive structures (verified) |
|---|---|---|---|---|---|---|---|---|
| `counter` | R | 49 (9) | 56 | 31 | 33 | 19 | 20 / 12 | 25 (14) |
| | B1 | 59 (10) | 72 | 41 | 34 | 23 | 28 / 15 | 31 (11) |
| `shift_register` | R | 9 (5) | 12 | 4 | 6 | 3 | 4 / 3 | 8 (3) |
| | B1 | 8 (4) | 1 | 1 | 1 | 1 | 1 / 1 | 0 |
| `lfsr_crc` | R | 0 (0) | 1 | – | 1 | – | – | 1 (1) |
| | B1 | 9 (1) | 2 | 0 | 2 | 0 | 0 / 0 | 2 (2) |
| `synchronizer` | R | 10 (5) | 3 | 6 | 3 | 6 | 6 / 6 | 0 |
| | B1 | 18 (4) | 3 | 17 | 3 | 17 | 17 / 17 | 0 |
| **all four** | R | 68 | 72 | 41 | 43 | 28 | 30 / 21 | 34 (18) |
| | B1 | 94 | 78 | 59 | 40 | 41 | 46 / 33 | 33 (13) |

[`C_secondary.per_kind`; pooled rows in `numbers.md` §C and §7.] **Strict and lenient differ on R**, as they never
did on B1. `sellicott`'s `mode0_db_inst.samples` and `mode1_db_inst.samples` are credited only in lenient mode,
through the truth's `copy_lanes` unit, by one verified 2-lane structure, so lenient R `shift_register` is 6 of 9
found and 5 of 9 harness-verified, against strict 4 and 3. Every other R cell is the same in both modes.

**Only `counter` has the support to be read as a rate.** The plan's per-kind bootstrap (kinds with registers in at
least 3 designs of a set) gives R `shift_register` found [0.0000, 0.6667] and `synchronizer` [0.0000, 1.0000]; the
R − B1 intervals, whose form the plan does not state (§3.3), are [-0.0500, 0.6154] and [-0.8750, 0.4154]. These
drop 7 to 77 of the 10,000 resamples as undefined, and at this width they are no basis for a rate
[`C_secondary.per_kind_bootstrap`]. `lfsr_crc` is counts only. R's one `lfsr_crc` structure is a
harness-verified false positive over an author-named LFSR that the truth calls a `shift_register` (R-D1, §5).

### 4.3 Found but unverified, and what the verified count is worth

R has 13 of its 41 found registers not harness-verified (12 counters, 1 `shift_register`, 9 exact). Twelve never
claimed `control.hold` (V1); in one, only the opaque load cases emptied the hold region (V2,
`HOLD_EMPTY_NEEDS_VERIFIED_COVER` test (a)). B1 has 18 of 59, all counters, 2 V1 and 16 V2, the reverse mix
[`C_secondary.found_but_unverified.summary`]. R's recognizer returned 455 structures and claimed 172 proven
(`score.py`'s count over the 446 it scored; `verify.py`'s summary counts 173); the harness adjudicated the 72 of a
scored kind, verified 43, refused 29 (27 `hold`, 2 `vacuous`), and never checked the 383 of unscored kinds
[`C_secondary.honesty.R`]. B1 returned 409, claimed 215 and had 40 verified, with 20
`hold` and 18 `vacuous` refusals. Neither set has an unclaimed verified structure, an `unknown` verdict or a budget
stop. `load_hidden_share`, how much of the state space the opaque load cases hide from a verified structure, has
mean 0.4263 and max 1.0000 over the 17 R verified structures that name a load case (B1: 0.5098 and 0.9929 over
17). R's max is `space_invaders`'s `counter6`, 4 flops, which earned no credit. As in B1, none of R's 43 verified
structures has all of its parameters certified (43 of 43 have an unchecked parameter; B1 40 of 40). Ten had no
liveness obligation (B1 6), and five had an empty hold region that the harness covered (B1 6)
[`C_secondary.honesty.*.verified_with_unchecked_params`, `.verified_without_a_liveness_obligation`,
`.verified_vacuous_hold`].

### 4.4 Grouping, order and parameters

**Grouping** (per-design AMI over all flops; each set's own random-block floor) [`C_secondary.grouping.*.all_flops`].
R: mean 0.7561, median 0.8432, min 0.0307, floor -0.0007, exact multi-flop words 212 of 329. B1: mean 0.8425,
median 0.8310, min 0.6641, floor -0.0010, exact words 73 of 162. Pooled: mean 0.7993, median 0.8323, floor -0.0008.
R's minimum is `nickjhay_processor`: 188 truth registers over 201 flops, mostly 1-bit systolic cells (R-D4).

**Bit order** [`C_secondary.order`]. R ordered all 31 found counter items perfectly: 822 pairs, concordance 1.0000
against a chance of 0.5000, 411 of the pairs from `sellicott`. B1 has 41 items and 2,798 pairs, and the pooled set
72 items and 3,620 pairs, all correct. R ordered all 5 of its `shift_register` order items correctly, over 1,223
pairs against a chance of 0.5451, but 1,154 of those pairs come from `sellicott`. Order is scored over lenient
matches, so the 5 are the 4 strict found registers plus `sellicott`'s lenient-only `copy_lanes` unit (§4.2). B1
could not test shift-register order at all (`docs/S3.md` §12.3).

**Parameters** [`C_secondary.params`]. A parameter is certified only when the harness verified the structure and
checked that parameter. Certified accuracy is 45/50 = 0.9000 on R, 58/60 = 0.9667 on B1 and 103/110 = 0.9364
pooled. Transcribed accuracy is 26/34 = 0.7647 on R, 36/38 = 0.9474 on B1 and 62/72 = 0.8611 pooled. R's five
wrong certified parameters are `SJ` `DUT.U1.countRow`'s modulus (answered 64, truth 4) and four steps answered 1:
`sellicott`'s two divider counters (truths 1073741824 and 858) and `space_invaders`' `group_x` (truth 2) and
`abullet_y` (truth 10). B1's two were counter moduli. Of R's 8 wrong transcribed parameters, 4 are
`shift_register.serial_in` and 3 are counter moduli answered `null`.

None of R's five certified errors is a value the harness left unchecked: each is certified over the flops its
structure names. They disagree with the truth's value for the whole register. Three structures cover only part of
their register, so a sub-word's step is set against the whole word's: `sellicott`'s +858 divider at IoU 0.68,
`group_x` at 0.89 and `abullet_y` at 0.67. The 1073741824 = 2^30 step is exact over the register's 2 netlist flops:
synthesis removed its low bits, which a 2^30 step never changes, and 1 = 2^30 / 2^30 is `docs/S3.md` §8.1's
dead-low-bit arithmetic. `countRow` is different. Its structure is `countRow[7:2]`, a 6-flop sub-word at IoU 0.75
verified as counting modulo 64, and no sub-word of a modulo-4 register can count modulo 64, so partial coverage does
not explain it. Its label is Tier A1 -- all 8 mapped bits z3-refuted and mismatching simulation
[`D_label_quality.R.registers`] -- so the truth's modulus 4 is not established. As far as the harness's own check
goes, four of the five come from the scorer setting a partial or dead-bit word's parameter against the full
register's, and the fifth rests on a label that is not established; none shows the recognizer mis-describing the
flops it names.

---

## 5. Causes: what recurs, what is new

Each of R's 27 misses (counter 18, `shift_register` 5, `synchronizer` 4) and 34 false positives (18
harness-verified) was traced by hand from the record, the truth and the cached RTL (`causes.md` §§4–5), in
`docs/S3.md` §§8–9's codes; a new code was added only where none fits, naming its nearest B1 code.

| Miss code | What it is | B1 | R |
|---|---|---|---|
| M1 | partial extent: the proved word covers only part of the register, IoU ≤ 0.5 | 5 | 4 |
| M2a / M2b | kind error: the register came back as one unscored structure / several | 2 / 10 | 2 / 5 |
| M3 | merged with a neighbour; one-to-one matching gave the pair to the other register | 1 | 0 |
| **M3b** (new) | two equal parallel registers merged into one 2-lane structure, IoU exactly 0.50 with each | 0 | 2 |
| M4a / M4b | affine-feedback handoff to `lfsr.py`, which proved an `lfsr_crc` / admitted nothing | 2 / 5 | 1 / 0 |
| M5 | `lfsr_crc` truth on a CPU register file | 9 | 0 |
| M6 | one-stage synchronizer, refused by the contract (`SYNC_MIN_STAGES` = 2) | 1 | 4 |
| **M6b** (new) | depth-2 shift register, below the contract's `SHIFT_MIN_DEPTH` = 3 | 0 | 1 |
| **M7** (new) | a 2-flop counter word straddling one counter bit and a neighbouring flag | 0 | 7 |
| **M8** (new) | multi-mode shift register; the structure follows one mode's copy step, IoU 0.25 | 0 | 1 |

| False-positive code | What it is | B1 (verified) | R (verified) |
|---|---|---|---|
| F1 / F2 | counter over a truth accumulator / over a fragment of one | 15 (1) / 10 (7) | 1 (1) / 4 (2) |
| F3 | counter over a sub-word of a truth counter | 6 (3) | 12 (10) |
| **F3b** (new) | F3's sub-word, paired by the matcher with a synthesis-retimed `other` register | 0 | 1 (1) |
| F4 | `lfsr_crc` over a truth `shift_register` | 2 (2) | 1 (1) |
| **F5** (new) | `shift_register` over word-wise array shifts that the truth labels `data_register` per entry | 0 | 4 (0) |
| **F6** (new) | `shift_register` over a pipeline written one 1-bit register per stage | 0 | 3 (2) |
| **F7** / **F8** (new) | the structure side of M7 / of M3b | 0 | 7 (0) / 1 (1) |

**What recurs** is mostly word extent. Two of R's four M1 misses fail at IoU exactly 0.50, as two of B1's five did.
`sellicott`'s `transfer_state` (97 declared bits, 7 reachable) is B1's wide-integer mechanism again, its 12-flop
upper sub-word again `EXHAUSTIVE_WIDTH`, refused `vacuous`. M4a recurs once, with its F4, on `space_invaders`'
author-named `lfsr`. M6 is all four R synchronizer misses (three edge-detector flops, one input capture register).
Every R counter false positive is still about word extent (F3, F3b, F7) or constant against variable step (F1, F2).

**What is new.** M7 and F7, 7 + 7 cases, are one processing-element module of `SJ` met seven times: the recognizer
paired counter bit 0 with a flop the truth maps to `calculating_RS`, a mapping z3-refuted and mismatching
simulation in every PE (Tier A), and the harness refused all seven on `hold`. It is one mechanism, not fourteen
findings. R has 8 `shift_register` false positives, 3 harness-verified, where B1 had none. Seven (F5, F6) lie
mostly or wholly on registers the truth labels `data_register` or `flag` (R-D3, R-D4); the eighth is F8.

**Where the weight moved.** From B1 to R, accumulator-side false positives (F1 + F2) fall from 25 to 5 and counter
sub-word false positives (F3 + F3b) rise from 6 to 13. Of B1's 25, 18 are one design, `toivoh_synth`. With
byte-identical code, these shifts reflect which designs were drawn, not a change in the recognizer. Six of R's F3
are extra sub-words of a counter another structure found, which B1 never showed. Of B1's lfsr-side miss causes only M4a
recurs, once, with its F4 (above). There is no M4b (in B1, 5 `shift_register` misses on two designs where `lfsr.py` admitted nothing). M5 (B1's
9 register-file `lfsr_crc` labels) cannot recur, because R has no `lfsr_crc` truth register. Some events count on
both sides by construction: the four M1 registers' partial words make 7 false positives, each M7 is an F7, and the
M3b pair, the M4a register, `kittscanner`'s M8 and `nickjhay`'s M6 each sit inside one false positive. `SJ` alone
carries 10 misses and 11 false positives. No R miss or false positive comes from a dropped, unmapped or shadow flop.

**Label disagreements, listed and never applied** (`causes.md` §7; no truth file was modified):

| Id | Registers | Truth says | What the RTL and the recognizer say | Cost in R |
|---|---|---|---|---|
| R-D1 (B1 D1) | `space_invaders` `lfsr` | `shift_register` | author-named Fibonacci LFSR; `lfsr_crc` harness-verified at IoU 1.00 | 1 miss (M4a), 1 FP (F4) |
| R-D2 (B1 D4) | `space_invaders` `prev_button0/1/2`, `nickjhay` `sys_in1_buffer` | `synchronizer`, 1 stage | edge-detect and capture flops; the contract needs ≥ 2 stages | 4 misses (M6) |
| R-D3 (new) | `SJ` `filter_spad` / `ifmap_spad` (54 regs, Tier A), `kittscanner` `pwmsel[0..7]` | `data_register` per entry | `spad[i] <= spad[i-1]`: word-wise shift registers | 4 FPs (F5); relabelling alone would not recover `SJ` (IoU 0.25) |
| R-D4 (new) | `nickjhay` systolic `out1` / `out2`, `sellicott` `refclk` pipe | `flag` per stage | per-stage pipelines ("successive out1's will form shift registers") | 3 FPs (F6), 2 harness-verified |
| R-D5 (like B1 D3) | `kittscanner` `state` | counter, modulus 2 | FSM with constant jumps; state codes run to 59 | 1 miss (M2b) |
| R-D6 (new, weak) | `space_invaders` `score` (Tier A) | counter, step `null` | adds 10, 20 or 30; the frozen template needs one step | 1 miss (M2b) |
| R-D7 (like B1 D4) | `SJ` `PEStartEN` (Tier A) | `shift_register`, depth 2 | the contract needs depth ≥ 3 | 1 miss (M6b) |

---

## 6. Mechanics

[`E_mechanics.summary`, `E_mechanics.ledger`.] All 10 R records and all 50 evaluations are valid. Each design gave
one distinct answer across its K = 5 `os.urandom` permutations (0 unstable structures, 0 varying metrics). There
were 0 anonymity leaks, 0 timeouts, 0 recognizer failures and 0 sandbox blocks; every truth hash agrees three
ways. Recognizer wall time ranged 0.881–107.928 s and peak RSS 118.6–1453.1 MB; whole records took
3.103–112.733 s, 404.107 s in all. The ledger has 42 lines, an intact hash chain and no uncommitted line. It holds
exactly 10 Freeze-4 attempts, one per R design, each attempt and finish record passing its sha256 cross-check. No
Freeze-4 attempt names a design outside R, so the puzzle was not run, and no R design was rerun. The only record
`problems` entry is `tiny_8bit_cpu`'s, the same in every permutation: 72 result flops dropped from 9 of its 45
structures (the design has 308 netlist flops, 72 of them unmapped), all of unscored kinds.

**`out/s3/blind/labels.json` now holds Freeze 4's labels.** Freeze 1's labels (freeze `1ee6a4789435`, written
06:50:45Z) were committed with `docs/S3.md` [`E_mechanics.out_s3_blind_labels_json`]. The labeller wrote Freeze 4's
(freeze `1196c56304e3`, written 16:25:45Z) to the same path, because the plan says replacements are recorded in that
file, so freeze 1's version now lives in git history, where `freeze.spent_designs()` still reads it. Freeze 4's file
is committed with this report. It is the only committed record `freeze.spent_designs()` reads for three more
candidates that were seen: `ttsky26c/tt_um_tpcannon7_fir` and
`ttsky26b/tt_um_fidel_makatia_digital_tapeout` (drawn, labelling failed) and `tt08/tt_um_zoom_zoom` (reserve,
labelling failed). `freeze.spent_designs()` reads labels only at `out/s3/blind/labels.json`, in the working tree and
in git history, so force-adding `out/s3/replication/labels.json` does not help. Their other evidence (the download
cache, and the truth files left on disk for the two drawn designs) is git-ignored, so without the committed
`labels.json` a fresh clone would treat those three as unseen. `freeze check` prints `freeze holds`.

---

## 7. The pooled set beside the corpus holdout

As the plan specifies, only the pooled set is set beside the references: the pre-published `holdout_rates.json`,
whose "found" is already harness-verified, and `honesty_table.json`'s corpus holdout on `score.py`'s own register
denominators. Both were measured on the same code as the records [`F_references`]:

| Kind | Pooled B1 + R: registers (designs) | found | harness-verified found | `holdout_rates.json`: items / verified found | `honesty_table.json`: registers / found / verified found |
|---|---|---|---|---|---|
| `counter` | 108 (19) | 72 (0.6667) | 42 (0.3889) | 44 / 28 (0.6364) | 40 / 36 (0.9000) / 26 (0.6500) |
| `shift_register` | 17 (9) | 5 | 4 | 30 / 20 | 26 / 16 / 16 |
| `lfsr_crc` | 9 (1) | 0 | 0 | 14 / 14 | 14 / 14 / 14 |
| `synchronizer` | 28 (9) | 23 | 23 | 6 / 6 | 10 / 8 / 8 |

**The item sets differ.** Every blind figure counts `score.py`'s strict register denominators. `holdout_rates.json`
counts registers plus declared units, which `holdout_rates.py` itself calls not comparable with `score.py`'s, over
40 synthetic designs in 80 runs. `honesty_table.json` uses `score.py`'s denominators but is a different seeded run.
Neither publishes an interval, and the synthetic corpus was written by this project (`docs/S3.md` §§2, 6, 15). Nor
is the holdout untouched: the one design a threshold was fitted on was moved to train and the rates re-reported,
but four designs still in the holdout had their outcomes read while the recognizer was being changed, and one was
written from puzzle knowledge, so `docs/S3.md` §15 item 1 calls it "a weaker estimate than an untouched set"
(contamination K13, K2).

`counter` is the only kind read as a rate. The pooled harness-verified found figure of 0.3889 sits under both
references, whose point values lie above the upper end of either pooled bootstrap interval. The references carry no
interval of their own. Under the independence assumption, and outside the plan, `numbers.json` gives them
Clopper–Pearson [0.4777, 0.7759] for `holdout_rates.json`'s 28 of 44 and [0.4832, 0.7937] for
`honesty_table.json`'s 26 of 40. Both overlap both pooled intervals, so this is not a design-level separation.
Fisher two-sided p against the pooled 42 of 108 is 0.0071 and 0.0055, and for all-structures found (pooled 72 of
108 against `honesty_table.json`'s 36 of 40) it is 0.0037 [`F_references.pooled_set.counter.descriptive_not_in_plan`].
These treat registers as independent. The last does not continue `docs/S3.md`'s comparison: its §6.2 set
all-structures found against `holdout_rates.json`'s derived (28 + 10) / 44 = 0.8636 and got p = 0.060 on B1, while
this figure is against `honesty_table.json`'s 36 of 40. None of these carries a verdict word. In the other kinds
the pooled set has `shift_register` 4 of 17 harness-verified found across 9 designs, `lfsr_crc` 0 of 9 in one design
and `synchronizer` 23 of 28 across 9 designs, B1's part of it credited mostly through two declared chain units
(`docs/S3.md` §5.2).

`docs/S3.md` found that grouping "held in the mean only" (B1 0.8425 against the holdout's 0.8453). That does not carry
to R: R's mean is 0.7561, pulled down most by `nickjhay_processor`'s 0.0307, with a median of 0.8432. Pooled grouping
AMI has mean 0.7993 and median 0.8323 against its own random-block floor of -0.0008; the holdout publishes 0.8453
and 1.0, with a random-block AMI mean of 0.7009 (`honesty_table.json`). Read as lift over each set's own floor, as
`docs/S3.md` §12.2 also read it, the pooled set clears its floor by more, as B1 did. Pooled counter order is 72 items
and 3,620 pairs, all correct (`honesty_table.json`: 38 and 2,236, all correct). Pooled certified parameter accuracy
is 103/110 = 0.9364 (`honesty_table.json`: 178/180 = 0.9889). `docs/S3.md` §12.1 read B1's 58/60 as two named
errors, not a measured drop against 178/180. R's five more errors (45/50) make that reading weaker on the pooled
set, though four of the five are partial or dead-bit words set against the whole register's value and the fifth
rests on a Tier A label (§4.4). Transcribed
accuracy also falls, from 36/38 on B1 to 26/34 on R.

---

## 8. Limitations

1. **The denominator is still the binding limit.** R's 49 counters sit in 9 designs, with 12 each in `SJ` and
   `space_invaders`. The R − B1 interval, [-0.3121, 0.2853], fits any difference in that range, and "consistent
   with freeze 1" says no more. Even the pooled interval is [0.2617, 0.5517] resampling within each set, and
   [0.2583, 0.5534] resampling the 20 as one set. No other kind supports a rate in R, B1 or the pooled set.
2. **The cases cluster.** One `SJ` module accounts for 14 of R's 27 + 34 cases, and several kinds of event are
   charged on both sides (§5). The design-level bootstrap allows for clustering. Fisher and Clopper–Pearson do
   not, so their figures are a floor on the uncertainty. Nor is the bootstrap a ceiling: a percentile interval
   over 9 or 10 designs of very unequal size can itself under-cover.
3. **The labels are not established everywhere.** 12 of R's 68 scored registers are Tier A, and so is the flop
   behind all seven M7 cases. Seven label disagreements are listed and not applied. In two (R-D2, R-D7) the
   labeller's convention conflicts with the frozen contract, and no recognizer answer can satisfy both.
4. **Not everything outside the precondition matches B1.** Besides the three files of §1, RETRACE's extractor
   (outside the records' code block) changed in Freeze 2 (`F02`). `docs/S3.md` §17 says it gives the same nets on
   `prepare_layout` outputs with no top-level cut shape left. R's layouts are `prepare_layout` outputs too.
   Whether any of them keeps a top-level cut shape is a cheap check on R's ten anonymised layouts, but it is not
   among this replication's recorded outputs, so the point stays open.
5. **Both draws come from one pool** (the same pre-registered candidates and shuttle strata, without replacement):
   R is a second sample of that population, not a different one. The independent recomputation was another pass
   of the same workflow, not an outside party.
6. **The references are synthetic and were written by this project**, count different items and publish no
   interval (§7). They are not untouched either: four holdout designs had their outcomes read while the recognizer
   was being changed (the one fitted on was moved to train; contamination K13), and one was written from puzzle
   knowledge (K2), so the holdout is a weaker
   estimate than an untouched set (`docs/S3.md` §15 item 1).
7. **This replication spent 13 more candidates**: R's ten, and the two drawn designs and one reserve whose
   labelling failed (§2). R's designs and truths were read in full for this report. With freeze 1's ten,
   `freeze.spent_designs()` now returns 23, and the next freeze that draws excludes all of them; the three failed
   ones through the committed `out/s3/blind/labels.json` (§6).

---

## 9. Artifacts

| What | Path | In a commit? |
|---|---|---|
| Analysis plan | `docs/S3_REPLICATION_PLAN.md` | `95f7eff` |
| Freeze 4 record, draw and seed; change-log `R01` | `out/s3/FREEZE.json`, `tools/s3/changes.jsonl` | `0aa0698` |
| The 10 R run records and 10 attempt files | `out/s3/runs/blind-<design>-20260923T16*.json` (`numbers.json` `sets.R.records`) | run commits `511ffe2` … `43623c6` |
| Blind ledger (42 lines, hash-chained) | `out/s3/blind_ledger.jsonl` | run commits |
| Freeze 4's labels (read by `freeze.spent_designs()`) | `out/s3/blind/labels.json` (freeze 1's is in git history, §6) | with this report |
| R labels copy, labeller log, replacement driver | `out/s3/replication/labels.json`, `labels.log`, `make_labels_r.py` (a copy of `make_labels.py` adapted for replacements), `verify_anon.py`, `run_one.sh`, `run_*.log` | with this report |
| R truths and run logs | the ten `out/s3/truth_<design>.json` of R; `out/s3/replication/runlog/` | with this report |
| Canonical numbers; every miss and false positive with its cause; the independent recomputation | `out/s3/replication/analysis/`: `compute_numbers.py`, `numbers.json`, `numbers.md`; `causes.py`, `causes.json`, `causes.md`; `xcheck.py`, `xcheck.json`, `xcheck_compare.py`, `xcheck_compare.json` | with this report |
| Anonymised layouts; per-design label files | `out/s3/blind/anon/<design>.gds`; `out/s3/blind/label_<id>.json` for R's ten and `label_<id>.fail.json` for the three failures | no (as for freeze 1) |
| Truth files left on disk by the two failed drawn designs (§2, §6); not valid truths, never scored | `out/s3/truth_ttsky26c__tt_um_tpcannon7_fir.json`, `out/s3/truth_ttsky26b__tt_um_fidel_makatia_digital_tapeout.json` | no |
| B1's inputs (read only) | the ten freeze-1 records in `out/s3/runs/`; `out/s3/blind/analysis/misses.json` | freeze-1 run commits; `docs/S3.md`'s commit |

`out/` is git-ignored; the replication's outputs marked above are force-added with this report, so R's figures
can be checked from a commit. B1 is recomputed from its committed records, and 20 cross-checks against `docs/S3.md`'s
freeze-1 figures all pass [`cross_checks.all_pass`]. The replication's own commits are the plan (`95f7eff`), Freeze 4
(`0aa0698`: `FREEZE.json`, change-log `R01`, the regenerated `summary.json`), the ten run commits, and this report's.
Labelling, running and analysis modified nothing under `tools/`, `test/` or `docs/`, no existing truth, run record or
freeze-1 analysis file; the labeller overwrote `out/s3/blind/labels.json` with Freeze 4's labels by design (§6) and
left truth files for the two failed drawn designs on disk (above). `.venv/bin/python -m tools.s3.freeze check` printed exactly `freeze holds` before and after.
