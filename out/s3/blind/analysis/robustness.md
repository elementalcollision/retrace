# S3 blind evaluation — robustness and evaluation mechanics

Lens: **robustness**. Scope: the 10 drawn third-party Tiny Tapeout designs (the blind set, the first
true out-of-sample test), reported apart from the Jane Street puzzle (**frozen code on a KNOWN design —
not blind**). TEMPO is the fitted development design and every TEMPO figure here is labelled IN-SAMPLE.
The synthetic corpus holdout is the pre-published out-of-sample estimate. Machine-readable companion:
`out/s3/blind/analysis/robustness.json`. Metric definitions are `tools/s3/score.py`'s module docstring;
the protocol is `docs/S3_DESIGN.md` section 4.4.

## 0. Headline

| Question | Answer |
|---|---|
| Does any headline figure move between permutations? | **No.** 0 of 761 defined headline metrics varied across the 10 blind designs; 0 of 92 on the puzzle |
| distinct_answers | **1** on every one of the 11 records (55 recognizer runs) |
| Pairwise structure-set Jaccard | **1.000** on every design; 0 unstable members anywhere |
| Any record invalid? | No — 10/10 blind and the puzzle all `valid: true`, `invalid_reasons: []` |
| Anonymity leaks | **0** across all 55 relabellings |
| Recognizer timeouts / non-zero exits | **none** |
| Ledger chain | **intact**, 22 lines, 0 uncommitted, exactly one attempt per design |
| Attempt / record / ledger hash cross-checks | **all pass** on all 11 designs; the run commit chain is unbroken from the freeze commit to HEAD |
| Freeze | `freeze holds` before and after this analysis |

The single robustness conclusion is that **the permutation is not a source of uncertainty in this
evaluation at all**. Everything else in this document is about the uncertainty that *is* there: the
denominators.

## 1. Permutation spread of every headline metric

`run.py` runs each frozen evaluation under K = 5 independent `random.SystemRandom` (os.urandom)
relabellings and records every metric per permutation plus mean/median/min/max. Across all 11 records:

| design | role | K | valid evals | distinct answers | metrics defined in all 5 | metrics varying | undefined in all 5 |
|---|---|---|---|---|---|---|---|
| `tt03p5__tt_um_Reloj_top` | blind | 5 | 5 | 1 | 81 | **0** | 18 |
| `tt03p5__tt_um_thorkn_vgaclock` | blind | 5 | 5 | 1 | 65 | **0** | 30 |
| `tt05__tt_um_kskyou` | blind | 5 | 5 | 1 | 72 | **0** | 27 |
| `tt05__tt_um_toivoh_synth` | blind | 5 | 5 | 1 | 91 | **0** | 6 |
| `tt07__tt_um_toivoh_basilisc_2816` | blind | 5 | 5 | 1 | 95 | **0** | 6 |
| `tt07__tt_um_vzayakov_top` | blind | 5 | 5 | 1 | 78 | **0** | 19 |
| `tt09__tt_um_pwm_top` | blind | 5 | 5 | 1 | 65 | **0** | 30 |
| `ttsky25a__tt_um_sjsu_vga_music` | blind | 5 | 5 | 1 | 76 | **0** | 19 |
| `ttsky25a__tt_um_td4` | blind | 5 | 5 | 1 | 61 | **0** | 36 |
| `ttsky26c__tt_um_joonatanalanampa_cordic` | blind | 5 | 5 | 1 | 77 | **0** | 20 |
| `puzzle` | **known design** | 5 | 5 | 1 | 92 | **0** | 9 |

`distinct_answers` is the number of distinct `canonical_result_hash` values over the 5 permutations —
the sha256 of the mapped answer in canonical order: every structure as `(kind, flop set, order, params,
harness outcome class)` and the groups as sorted sets, with the recognizer's own ids stripped. `run.py`
states it is equal under two permutations exactly when the recognizer's answer is the same up to ids. It
is 1 on all 11 records, so the permutations did not merely agree on the scored metrics — they agreed on
every structure's kind, membership, order, parameters, verdict class and grouping. (It does not hash
fields outside that tuple, such as a structure's proof object or the result metadata.) Consequently
min = median = max for every metric, and the mean carries no information either.

A metric "undefined in all 5" has no support and no prediction on that design (e.g. `lfsr_crc.found_r`
on a design with no LFSR): it is `null` in all five permutations, not a stable zero. No metric was
defined in some permutations and not others — the count of such metrics is 0 on every design.

### Why this is stronger than 5 lucky draws

Five agreeing draws alone would only bound a permutation-sensitivity probability loosely. The mechanism
is recorded: the recognizer's canonical-order refinement left **zero tied cells and zero tied nets on
all 11 designs**, so no part of its answer ever fell back to id order.

| design | refinement rounds | cells individualized to break ties | tied cells left | tied nets left |
|---|---|---|---|---|
| `tt03p5__tt_um_Reloj_top` | 47 | 21 | 0 | 0 |
| `tt03p5__tt_um_thorkn_vgaclock` | 76 | 34 | 0 | 0 |
| `tt05__tt_um_kskyou` | 54 | 15 | 0 | 0 |
| `tt05__tt_um_toivoh_synth` | 53 | 16 | 0 | 0 |
| `tt07__tt_um_toivoh_basilisc_2816` | 81 | 33 | 0 | 0 |
| `tt07__tt_um_vzayakov_top` | 69 | 27 | 0 | 0 |
| `tt09__tt_um_pwm_top` | 75 | 30 | 0 | 0 |
| `ttsky25a__tt_um_sjsu_vga_music` | 70 | 33 | 0 | 0 |
| `ttsky25a__tt_um_td4` | 28 | 10 | 0 | 0 |
| `ttsky26c__tt_um_joonatanalanampa_cordic` | 62 | 24 | 0 | 0 |
| `puzzle` | 9 | none needed | 0 | 0 |

By contrast the frozen TEMPO run (IN-SAMPLE, `out/s3/eval/runs/tempo-20260923T053247Z-ef7fc630631b.json`)
left 79 cells and 79 nets tied and ordered by id — and still produced one canonical answer under 5
permutations *and* the file-order arm. `run.py`'s module docstring records a review of 2026-09-22 that
found the recognizer **not** permutation invariant on TEMPO; on the frozen code that is no longer
observable in any record in this tree. Reported as a historical note, not as a current property.

### Pairwise agreement of the scored structure sets

`structure_set` compares, between permutations, the set of `(kind, truth join keys, outcome class)` over
structures of scored kinds — `unknown` kept as its own outcome.

| design | structures per permutation | common to all 5 | union | pairwise Jaccard (min/mean/max) | unstable members |
|---|---|---|---|---|---|
| `tt03p5__tt_um_Reloj_top` | 12 | 12 | 12 | 1.000 / 1.000 / 1.000 | 0 |
| `tt03p5__tt_um_thorkn_vgaclock` | 6 | 6 | 6 | 1.000 / 1.000 / 1.000 | 0 |
| `tt05__tt_um_kskyou` | 3 | 3 | 3 | 1.000 / 1.000 / 1.000 | 0 |
| `tt05__tt_um_toivoh_synth` | 22 | 22 | 22 | 1.000 / 1.000 / 1.000 | 0 |
| `tt07__tt_um_toivoh_basilisc_2816` | 4 | 4 | 4 | 1.000 / 1.000 / 1.000 | 0 |
| `tt07__tt_um_vzayakov_top` | 18 | 18 | 18 | 1.000 / 1.000 / 1.000 | 0 |
| `tt09__tt_um_pwm_top` | 2 | 2 | 2 | 1.000 / 1.000 / 1.000 | 0 |
| `ttsky25a__tt_um_sjsu_vga_music` | 7 | 7 | 7 | 1.000 / 1.000 / 1.000 | 0 |
| `ttsky25a__tt_um_td4` | 0 | 0 | 0 | 1.000 / 1.000 / 1.000 *(vacuous: both sets empty)* | 0 |
| `ttsky26c__tt_um_joonatanalanampa_cordic` | 4 | 4 | 4 | 1.000 / 1.000 / 1.000 | 0 |
| `puzzle` | 29 | 29 | 29 | 1.000 / 1.000 / 1.000 | 0 |

One caveat on this column: for `ttsky25a__tt_um_td4` the recognizer produced **no** structure of a scored
kind, so both sets in every pair are empty and `_jaccard` returns 1.0 by its own convention. That design's
stability rests entirely on `distinct_answers = 1`, which covers all 21 of its structures (all of unscored
kinds) and its groups. The Jaccard cell is true but says nothing.

## 2. Would any conclusion change under a different permutation?

**No conclusion in the report can change by re-drawing a permutation, on any of the 11 designs.** Every
scored quantity — per-kind found/exact/verified recall and precision, macro- and micro-F1 at register and
bit level, AMI/ARI/NMI, the order scores, the parameter accuracies, the honesty block's verified counts and
`load_hidden_share`, and the harness's own structure and verified counts — was identical under all 5
permutations on all 11 designs. The permutation contributes no uncertainty and therefore costs no digits.

This has a direct consequence for how the report should print these figures: **state each value once and
say the five permutations agreed exactly.** Printing "min/median/max" for a blind figure would print the
same number three times and would falsely suggest a measured range.

What it does *not* license: the figures are exact for *this code on these 10 netlists*. Permutation
invariance says nothing about how the numbers would move on 10 other designs. That uncertainty is
section 3 and it is large.

## 3. How many digits are meaningful

With the permutation contributing nothing, the binding uncertainty is the size of the denominator. Every
rate below is over **truth registers of that kind** (`score.py`: recall = registers of kind c found /
registers of kind c; the denominator is the same in strict and lenient mode).

Blind set totals, cross-checked against `out/s3/blind/labels.json` (agreement: `True`): **240 truth
registers** over **1701 scored flops** from **1708 netlist flops**, of
which **94 registers are of the four scored structure kinds**.
0 designs were replaced by a reserve; 10 of 10 labelled, 0 failed.

| kind | blind registers | designs contributing | largest single design's share | best-case SE (0.5/sqrt n) |
|---|---|---|---|---|
| shift_register | **8** | 4 | 38% | ±17.7 pp |
| counter | **59** | 10 | 24% | ±6.5 pp |
| lfsr_crc | **9** | 1 | 100% | ±16.7 pp |
| synchronizer | **18** | 4 | 56% | ±11.8 pp |
| **all four pooled** | **94** | 10 | 24% (counter, Reloj) | ±5.2 pp |

The SE column is the worst-case binomial standard error and assumes independent registers. The clustering
column shows that assumption fails, so **those figures are a floor on the error, not the error**:

* **`lfsr_crc` on the blind set is one design.** All 9 LFSR/CRC registers are in
  `tt07__tt_um_toivoh_basilisc_2816`. There is no blind LFSR rate — there is one design's result. Report it
  that way; a "blind LFSR/CRC recall" would be a single design dressed as a rate.
* **`synchronizer` is effectively two designs.** 16 of 18 registers come from `tt07__tt_um_vzayakov_top`
  (10) and `tt03p5__tt_um_Reloj_top` (6).
* **`shift_register` is 8 registers over 4 designs**, 6 of them from two designs (3 + 3).
* **`counter` is the only kind with real spread**: 59 registers over all 10 designs, largest share 24%.

### The synchronizer denominator is smaller than it looks

`score.py` strict mode scores a synchronizer register that belongs to a declared **chain unit** only
through its chain units, and a unit match credits every member register the structure holds. On the two
designs that carry the blind set's synchronizer mass:

| design | synchronizer registers | declared chain units | result synchronizer structures |
|---|---|---|---|
| `tt03p5__tt_um_Reloj_top` | 6 | 4 | 1 |
| `tt07__tt_um_vzayakov_top` | 10 | 6 | 1 |

So 16 of 18 synchronizer registers sit behind **two** result structures on **two** designs. A synchronizer
recall over a denominator of 18 is not 18 independent trials and must not be quoted as though it were.

### Cells too small to support any claim

`score.SMALL_SUPPORT = 3`: the scorer flags any kind with fewer than 3 registers, because one miss then
swings recall by more than a third. Of the 40 (design, kind) cells in the blind set, **21 hold no
register of that kind at all** and **5 hold 1–2** — so the scorer raises its
flag on 26 of 40 cells, and only
**14 cells hold 3 or more**. The 5 non-empty flagged cells are:

* `tt05__tt_um_toivoh_synth` / shift_register: 1 register
* `tt05__tt_um_toivoh_synth` / synchronizer: 1 register
* `tt07__tt_um_toivoh_basilisc_2816` / synchronizer: 1 register
* `ttsky25a__tt_um_sjsu_vga_music` / shift_register: 1 register
* `ttsky25a__tt_um_td4` / counter: 1 register

**No per-design, per-kind percentage should be printed for any of these, nor for the 21 empty cells.**
`ttsky25a__tt_um_td4` deserves a specific warning: its entire structure-kind truth is **one** counter
register, so its "counter recall 0.0" is one miss, and its macro-F1 is that one miss plus three undefined
kinds. It is a single observation, not a design-level score.

### Recommended reporting

* State each blind figure once; say the 5 permutations agreed exactly, do not print a min/median/max range.
* Pooled blind rates: at most 2 significant figures (94 structure-kind registers -> best-case SE 5.2 pp).
* Per-kind blind rates: give the fraction with its own denominator (e.g. 'n of 59' for counter), never a bare percentage.
* lfsr_crc on the blind set is ONE design's 9 registers: report it as that design's result, not a rate.
* Do not report a rate for any of the 5 (design, kind) cells with 1-2 registers or the 21 with none.
* Never pool the puzzle with the blind 10: frozen code on a KNOWN design is not an out-of-sample test.

## 4. Record validity, problems and the harness's refusals

| design | valid | invalid_reasons | harness problems | result structures | of scored kinds | verified |
|---|---|---|---|---|---|---|
| `tt03p5__tt_um_Reloj_top` | True | — | — | 85 | 12 | 8 |
| `tt03p5__tt_um_thorkn_vgaclock` | True | — | — | 6 | 6 | 6 |
| `tt05__tt_um_kskyou` | True | — | — | 25 | 3 | 1 |
| `tt05__tt_um_toivoh_synth` | True | — | — | 59 | 22 | 8 |
| `tt07__tt_um_toivoh_basilisc_2816` | True | — | — | 67 | 4 | 1 |
| `tt07__tt_um_vzayakov_top` | True | — | — | 72 | 18 | 5 |
| `tt09__tt_um_pwm_top` | True | — | — | 13 | 2 | 1 |
| `ttsky25a__tt_um_sjsu_vga_music` | True | — | 5 (see below) | 21 | 7 | 6 |
| `ttsky25a__tt_um_td4` | True | — | — | 21 | 0 | 0 |
| `ttsky26c__tt_um_joonatanalanampa_cordic` | True | — | — | 40 | 4 | 4 |
| `puzzle` | True | — | — | 34 | 29 | 27 |

**Every record is valid with an empty `invalid_reasons`.** Exactly one design recorded a `problem`, and it
recorded it identically in all five permutations:

* `ttsky25a__tt_um_sjsu_vga_music`: *"7 result flops were dropped (unmapped, unknown to the truth or not
  flop ids) from 4 structures; those structures cannot be exact"*. The cause is on the truth side: the
  frozen labeller left 7 of that design's 77 netlist flops unmapped, so the scored universe is 70 flops and
  4 result structures lost **every** flop they held and were dropped from the scored view entirely (21
  structures, 17 scored). This is the blind set's only scoring anomaly and the only 7 unmapped flops in it.

### What the recognizer claimed and what the harness certified

`score.py` is explicit that a result's own `proven` status *"is a claim and counts for nothing"*. The
harness's verdict is the only thing that counts, and a kind outside `STRUCTURE_KINDS` is never verified at
all — its claim is bucketed `unscored kind`, which is **not** a refutation. Splitting on that line:

| | blind set (10) | puzzle (known design) |
|---|---|---|
| result structures | 409 | 34 |
| of scored kinds | 78 | 29 |
| scored-kind structures claiming `proven` | 78 | 29 |
| scored-kind structures the harness VERIFIED | 40 | 27 |
| scored-kind claims the harness REFUSED | 38 | 2 |
| structures of unscored kinds | 331 | 5 |
| of those, claiming `proven` (never checkable) | 137 | 1 |
| refusal reasons | {'vacuous': 18, 'hold': 20} | {'hold': 2} |

On the blind set the recognizer claimed `proven` on **all 78** of its scored-kind structures and the harness
certified **40**, refusing **38** — 20 on the `hold` obligation and 18 as `vacuous`. On the puzzle it
claimed 29 and the harness certified 27, refusing 2, both on `hold`. The `hold` refusals are the known
ceiling that `docs/S3_DESIGN.md` section 6 and `score.HOLD_CEILING_NOTE` declare an accepted limitation of
this freeze. `verified_not_claimed_proven` is **0** everywhere: the harness never certified a structure the
recognizer had not claimed.

A separate 137 blind (and 1 puzzle) `proven` claims sit on structures of unscored kinds (`data_register`,
`flag`). Those were never checked and must not be counted either as refuted or as certified.

### The harness never ran out of budget

* `budget` outcomes: **0** blind, **0** puzzle.
* `unknown` outcomes (a solver limit, which `score.py` reports apart from refutations): **0** blind, **0** puzzle.
* Peak conflicts used in any run: **2,995** against a limit of 10,000,000 (0.03%).
* Peak coverage calls used: **16,384** against a limit of 200,000 (8.2%).

Every refusal in this evaluation is a substantive verdict, not a solver giving up. That matters for
interpretation: the found/verified gap cannot be blamed on compute.

## 5. Anonymity and isolation

`run.py` step 4 checks that no Key name, black-box macro name or LEF pin name is reachable from the
relabelled netlist, and that every black-box master and pin is an opaque id.

| design | anonymity leaks (all 5 perms) | strings reachable | black-box masters / pins / instances | OS sandbox | audit-hook denials | recognizer exit codes |
|---|---|---|---|---|---|---|
| `tt03p5__tt_um_Reloj_top` | 0 | 134 | 0 / 0 / 0 | sandbox-exec | 0 | [0] |
| `tt03p5__tt_um_thorkn_vgaclock` | 0 | 112 | 0 / 0 / 0 | sandbox-exec | 0 | [0] |
| `tt05__tt_um_kskyou` | 0 | 121 | 0 / 0 / 0 | sandbox-exec | 0 | [0] |
| `tt05__tt_um_toivoh_synth` | 0 | 136 | 0 / 0 / 0 | sandbox-exec | 0 | [0] |
| `tt07__tt_um_toivoh_basilisc_2816` | 0 | 143 | 0 / 0 / 0 | sandbox-exec | 0 | [0] |
| `tt07__tt_um_vzayakov_top` | 0 | 121 | 0 / 0 / 0 | sandbox-exec | 0 | [0] |
| `tt09__tt_um_pwm_top` | 0 | 66 | 0 / 0 / 0 | sandbox-exec | 0 | [0] |
| `ttsky25a__tt_um_sjsu_vga_music` | 0 | 90 | 0 / 0 / 0 | sandbox-exec | 0 | [0] |
| `ttsky25a__tt_um_td4` | 0 | 94 | 0 / 0 / 0 | sandbox-exec | 0 | [0] |
| `ttsky26c__tt_um_joonatanalanampa_cordic` | 0 | 88 | 0 / 0 / 0 | sandbox-exec | 0 | [0] |
| `puzzle` | 0 | 95 | 0 / 0 / 0 | sandbox-exec | 0 | [0] |

**Zero leaks across all 55 relabellings**, zero audit-hook
denials, every child under `sandbox-exec` with `fail_closed` true, every exit code 0. No design carries a
black box at all, so the black-box anonymisation path (S3_DESIGN V13) was never exercised by the blind set —
its correctness is untested here, not confirmed.

The result-side checks are equally clean: across the blind set `result ids that are not flop cells` = 
**0**, `not an id` = **0**, and
`netlist flops unknown to the truth` = **0**. No run was
invalidated for a Key-name leak in a result.

## 6. Timings and memory

Wall times are wall times; `docs/S3_DESIGN.md` section 5 says they are reported and never gate a result.
The harness timeout was the default **1800 s**; the design-document budget for the recognizer is **≤ 5 min
and ≤ 1.5 GB excluding extraction**.

| design | extract+load s | recognizer wall s (min/median/max over 5) | harness verify s (min/max) | run total s | recognizer peak RSS MB (max, self-reported) | harness peak RSS MB (measured) |
|---|---|---|---|---|---|---|
| `tt03p5__tt_um_Reloj_top` | 1.829 | 280.89 / 281.54 / 281.95 | 11.063 / 11.444 | 341.2 | 1763.4 ⚠ | 262.3 |
| `tt03p5__tt_um_thorkn_vgaclock` | 0.623 | 11.69 / 11.77 / 11.84 | 0.112 / 0.211 | 14.2 | 225.4 | 182.2 |
| `tt05__tt_um_kskyou` | 0.942 | 11.73 / 11.83 / 11.88 | 0.063 / 0.280 | 14.7 | 271.4 | 199.0 |
| `tt05__tt_um_toivoh_synth` | 1.535 | 146.96 / 147.18 / 147.35 | 0.345 / 0.493 | 152.1 | 328.3 | 245.4 |
| `tt07__tt_um_toivoh_basilisc_2816` | 1.127 | 17.42 / 17.45 / 17.47 | 0.043 / 0.179 | 20.1 | 217.3 | 221.0 |
| `tt07__tt_um_vzayakov_top` | 1.018 | 31.28 / 31.39 / 31.49 | 2.226 / 2.389 | 45.1 | 290.4 | 214.6 |
| `tt09__tt_um_pwm_top` | 0.452 | 2.52 / 2.53 / 2.57 | 0.021 / 0.114 | 4.2 | 151.8 | 162.6 |
| `ttsky25a__tt_um_sjsu_vga_music` | 0.521 | 9.56 / 9.74 / 9.79 | 0.090 / 0.184 | 11.9 | 232.2 | 176.0 |
| `ttsky25a__tt_um_td4` | 0.734 | 2.23 / 2.30 / 2.37 | 0.016 / 0.051 | 4.4 | 146.1 | 174.7 |
| `ttsky26c__tt_um_joonatanalanampa_cordic` | 0.764 | 4.01 / 4.21 / 4.22 | 0.089 / 0.228 | 6.7 | 197.3 | 189.6 |
| `puzzle` | 0.951 | 6.63 / 6.71 / 6.72 | 0.210 / 0.408 | 10.2 | 170.7 | 191.3 |

Pooled over the blind set's **50 recognizer runs**: wall time min 2.226 s, median
11.796 s, max 281.952 s; self-reported peak RSS min 143.0 MB, median 227.2 MB,
max 1763.4 MB. Whole-run wall time summed over the 10 blind runs: 614.702 s.

* **No design timed out.** The longest recognizer arm, `tt03p5__tt_um_Reloj_top` at 281.95 s, used 15.7% of
  the 1800 s harness timeout.
* **No design exceeded the 5-minute recognizer budget**, but Reloj reached **94% of it** (281.95 s of 300 s).
  It is also the largest blind netlist (2,622 cells, 385 flops). A design of this size is the edge of the
  budget, and the budget is not a hard limit in the harness — a slower host would push it over with no
  failure signal.
* **One design exceeded the 1.5 GB memory budget**: Reloj's child peaked at **1,763.4 MB** against a 1,536 MB
  budget (+15%). This is the same budget S3_DESIGN section 5 already records TEMPO as missing on its upper
  arms (1.47–1.65 GB). It is reported, not adjusted. The figure is **self-reported by the recognizer's own
  process** — `run.py` states self-reported timings and RSS are informational only and forgeable in-process.
  The measured harness-side peak RSS (162.6–262.3 MB on the blind set) does not include the child.
* Recognizer wall time spread *within* a design is tiny (Reloj 280.89–281.95 s, a 0.4% band), consistent with
  the permutations doing identical work.
* The harness's own verification is cheap: median 0.103 s, max 11.44 s (Reloj), and scoring is 0.006–0.2 s.

## 7. Ledger, attempts and the freeze

| check | result |
|---|---|
| `out/s3/blind_ledger.jsonl` lines | 22 (11 `attempt` + 11 `finish`) |
| Hash chain (each line carries the previous line's sha256) | **intact** — 0 breaks |
| `freeze.ledger_entries()` problems (working tree + all git history) | **none** |
| Uncommitted ledger lines | **0** |
| `git status --porcelain` on the ledger | **clean** |
| Exactly one attempt per design under this freeze | **True** |
| Attempts under any other freeze hash | **none** |
| `--rerun-reason` used anywhere | **never** |
| Designs in the ledger not in the evaluation set | **none** |
| Freeze hash in `FREEZE.json` | `1ee6a47894359fef…` |
| `.venv/bin/python -m tools.s3.freeze check` | **`freeze holds`** (before and after this analysis) |

Two hashes with different meanings, both re-computed here from the files on disk:

* a record's `attempt.record_sha256` hashes the **attempt file** (`<id>.attempt.json`), which the harness
  writes read-only before extracting — not the final record;
* the ledger's **finish** entry (keyed by attempt id, carrying no design field) hashes the **final run
  record**, and also carries that run's five per-permutation `result_sha256` values.

| design | attempt id | attempt file sha256 = record = ledger | finish entries | finish sha256 = record file | finish valid / error | result sha256 count | freeze hash matches | freeze.git_head matches |
|---|---|---|---|---|---|---|---|---|
| `tt03p5__tt_um_Reloj_top` | `da01fb9dfcfa0e0f` | True | 1 | True | True / None | 5 | True | True |
| `tt03p5__tt_um_thorkn_vgaclock` | `76ac104b0392ef20` | True | 1 | True | True / None | 5 | True | True |
| `tt05__tt_um_kskyou` | `28983a5cab53d151` | True | 1 | True | True / None | 5 | True | True |
| `tt05__tt_um_toivoh_synth` | `4325410fcca47dcc` | True | 1 | True | True / None | 5 | True | True |
| `tt07__tt_um_toivoh_basilisc_2816` | `c4b1eb2474043b1b` | True | 1 | True | True / None | 5 | True | True |
| `tt07__tt_um_vzayakov_top` | `78544b0a503b06af` | True | 1 | True | True / None | 5 | True | True |
| `tt09__tt_um_pwm_top` | `eecffa74018ab777` | True | 1 | True | True / None | 5 | True | True |
| `ttsky25a__tt_um_sjsu_vga_music` | `9ffb0c41a8367ea9` | True | 1 | True | True / None | 5 | True | True |
| `ttsky25a__tt_um_td4` | `c6f41505f271a117` | True | 1 | True | True / None | 5 | True | True |
| `ttsky26c__tt_um_joonatanalanampa_cordic` | `80bc9522e634567d` | True | 1 | True | True / None | 5 | True | True |
| `puzzle` | `1e5c526bab75d5de` | True | 1 | True | True / None | 5 | True | True |

**Every cross-check passes on all 11 designs** (`all_cross_checks_pass: True`):
one attempt, one finish, one record, five result hashes, `valid: true`, `error: null`, under the single
freeze `1ee6a47894359fef…`. No design was run twice and no result was discarded.

### The run commit chain

`run.py` refuses a blind run while the ledger has uncommitted entries, and the lead commits the ledger
after every attempt. Each run's `git_head` is therefore the commit that recorded the **previous** run's
ledger entry. The chain is independent, tamper-evident evidence of how many runs happened and in what
order:

| # | design | started (UTC) | git_head at run time | that commit's subject | as expected |
|---|---|---|---|---|---|
| 1 | `tt09__tt_um_pwm_top` | 2026-09-23T06:53:52+00:00 | `232cfe67` | S3: freeze the first slice of structure recognition before the blind evaluation | True |
| 2 | `ttsky26c__tt_um_joonatanalanampa_cordic` | 2026-09-23T06:55:43+00:00 | `a7a81db2` | S3 blind run: tt09__tt_um_pwm_top | True |
| 3 | `tt05__tt_um_toivoh_synth` | 2026-09-23T06:57:20+00:00 | `99b0a4e8` | S3 blind run: ttsky26c__tt_um_joonatanalanampa_cordic | True |
| 4 | `ttsky25a__tt_um_td4` | 2026-09-23T07:01:28+00:00 | `2ae5aaab` | S3 blind run: tt05__tt_um_toivoh_synth | True |
| 5 | `tt03p5__tt_um_Reloj_top` | 2026-09-23T07:03:22+00:00 | `8fb0bbeb` | S3 blind run: ttsky25a__tt_um_td4 | True |
| 6 | `tt03p5__tt_um_thorkn_vgaclock` | 2026-09-23T07:10:42+00:00 | `938ae661` | S3 blind run: tt03p5__tt_um_Reloj_top | True |
| 7 | `tt07__tt_um_toivoh_basilisc_2816` | 2026-09-23T07:13:14+00:00 | `12ca2cf0` | S3 blind run: tt03p5__tt_um_thorkn_vgaclock | True |
| 8 | `ttsky25a__tt_um_sjsu_vga_music` | 2026-09-23T07:15:25+00:00 | `1b8e7f40` | S3 blind run: tt07__tt_um_toivoh_basilisc_2816 | True |
| 9 | `tt07__tt_um_vzayakov_top` | 2026-09-23T07:17:18+00:00 | `930a8931` | S3 blind run: ttsky25a__tt_um_sjsu_vga_music | True |
| 10 | `tt05__tt_um_kskyou` | 2026-09-23T07:28:56+00:00 | `02e7aedf` | S3 blind run: tt07__tt_um_vzayakov_top | True |
| 11 | `puzzle` | 2026-09-23T07:30:45+00:00 | `161ca318` | S3 blind run: tt05__tt_um_kskyou | True |

HEAD now is `0984b3c0` — *S3 blind run: puzzle*. The chain starts at the freeze commit
`232cfe67` (*S3: freeze the first slice of structure recognition before the blind evaluation*) and closes at HEAD with **no gap and no
extra link**; every commit named is in the repository and an ancestor of HEAD. The 10 blind designs ran
in exactly the drawn order (`run_order_equals_draw_order: True`) and the
puzzle ran last (`puzzle_ran_last: True`).

A note on the two `git_head` fields, which differ by construction and are **not** a mismatch:
`FREEZE.json.git_head` is `75803221`, the commit that was HEAD when
`freeze write` ran — necessarily the *parent* of the freeze commit, since a commit cannot contain its own
hash. Every record reproduces that value in `freeze.git_head`, while the record's own top-level
`git_head` is the commit the run actually executed on.

## 8. Protocol gaps worth stating in the report

Three mechanics facts a reader cannot get from the run records alone:

**(a) The leakage (file-order) arm was not run on any blind design.** S3_DESIGN section 2 defines a leakage
test in which the loader's own id order — which carries whatever signal the names carried — is run as an
extra arm and must land inside the permutations' spread. The blind and puzzle runs were launched as
`--blind --jobs 5` with no `--leakage`, so `permutations.file_order_arm` is `false` on all 11 records and
`leakage` is `null`. It was run on TEMPO only, where the verdict was `pass` with the file arm's canonical
answer identical to all five permutations. The blind set therefore has no *direct* test that id order
carries no signal. In this case the substitute is unusually strong — zero tied cells and nets means there
is no id-order fallback left to leak through — but the test itself was not performed and the report should
say so rather than cite TEMPO's pass as covering the blind set.

**(b) `score.py`'s provenance block cannot tell the puzzle from a blind design.** It has two categories,
TEMPO and not-TEMPO, so the puzzle's own score record reads `in_sample: false`, `"not the development
design"` — the same label a genuinely blind design gets:

| design | provenance `in_sample` | provenance label |
|---|---|---|
| `tt09__tt_um_pwm_top` | False | not the development design |
| `puzzle` | False | not the development design |
| `tempo` (development, for contrast) | true | in-sample (fitted development figure) |

`out/s3/contamination.json` is the record that corrects this. It classifies the puzzle as *"frozen code,
known design, puzzle-informed development", never blind*, and its `puzzle_report_must_state` list requires
the report to say that the counter and LFSR templates were exercised on puzzle-shaped synthetic cases and
that puzzle register names and measurements reached recognizer authors. **The puzzle's numbers must never
be pooled with the blind 10 and must never be described as out-of-sample.** Its `open` list also required
that the frozen puzzle evaluation run ≥ 5 permutations and report their spread (changes.jsonl C14) — that
obligation is met: K = 5, distinct_answers 1, zero varying metrics.

**(c) The out-of-sample estimate every record prints is synthetic and same-project.** Each score report
quotes `out/s3/honesty/holdout_rates.json` (40 holdout designs, 80 runs, 128 train designs; items per kind:
shift_register 30, counter 44, lfsr_crc 14,
synchronizer 6), and `score.out_of_sample()` accepted it — the 12 recognizer/harness
sources hash as they did when the rates were derived. But that document's own caveats say the corpus is
**synthetic and written by this project**, that neither generalisation regression set is held out any more,
and that the rates carry no confidence interval. So the ordering to state in the report is:

1. **TEMPO** — fitted development design, every figure IN-SAMPLE.
2. **Corpus holdout** — the pre-published out-of-sample estimate; synthetic, same-project, one seeded run.
3. **The blind 10** — the first out-of-sample test on designs this project did not write, over
   94 structure-kind registers and 1701 scored flops.
4. **The puzzle** — frozen code on a known design; not blind, not out-of-sample, never pooled.

## 9. Caveats on this lens's own claims

* "Zero varying metrics" is over the metrics `run.py`'s `headline_metrics()` collects into the spread
  block — per-kind found/exact/verified/F1, the overall macro/micro F1s, AMI/ARI/NMI, the parameter
  accuracies, the order score and coverage per kind and width band, and the verifier's counts and
  qualifications. That is 761 defined metric instances on the blind
  set. It is not literally every number in a score report; a figure outside the spread block (e.g. a
  per-structure detail) was not checked for permutation stability here. `distinct_answers = 1` does cover
  those, since it hashes the whole mapped answer.
* Permutation invariance is established for **these 11 netlists under 5 draws each**, supported by the
  zero-tie mechanism. It is not a proof that the recognizer is permutation invariant in general.
* Recognizer wall time and peak RSS are **self-reported by the sandboxed child**. `run.py` says such fields
  are informational and a determined recognizer could forge them. The memory-budget finding rests on a
  self-reported number; the harness's own measured RSS excludes the child.
* The blind set contains **no black boxes**, so the black-box anonymisation path was not exercised.
* This lens reports counts and stability, not accuracy. Per-kind found/exact/verified rates belong to the
  accuracy lens; the denominators and the precision limits in section 3 are binding on whatever it reports.
* **Filename collision in the shared output directory.** `out/s3/blind/analysis/` is written by several
  concurrent analyst sessions. This lens first used `build.py` / `pool.py` / `finish.py` / `md.py` there,
  and its `pool.py` was overwritten by another lens's file of the same name. Nothing in this lens's output
  was corrupted — `robustness.json` was rebuilt end to end afterwards from scratchpad copies and every
  figure in it was re-derived from the raw run records and asserted — but the collision is real, and
  generic script names in that directory can silently clobber a sibling session's work.

---

Generated by the scratchpad helpers `robustness_build.py` -> `_pool` -> `_finish` -> `_xcheck` ->
`_xcheck2` -> `_md` (read-only, outside the freeze; they modify no truth, no run record and nothing under
`tools/`). Data: `out/s3/blind/analysis/robustness.json`. `freeze check` printed `freeze holds` before and
after.
