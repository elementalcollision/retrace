# S3 replication — analysis plan, fixed before the draw

**Written and committed 2026-09-23, before Freeze 4 records its seed and before any replication design is
fetched.** The report (`docs/S3_REPLICATION.md`) must follow this plan; any departure is stated there as a
departure, with its reason.

## Question

Does the blind result of `docs/S3.md` hold on a second, independent draw — and what are the pooled estimates
once the sample is twice as large? The first report's binding limit was its denominator (94 structure-kind
registers over 10 designs, §5.2 and §12.4 there), not the recognizer's permutation spread (zero).

## What is fixed

| Item | Rule |
|---|---|
| Code | The recognizer, verifier, scorer and corpus code (`score.OUT_OF_SAMPLE_SOURCES`, 12 files) are **byte-identical** to the code freeze 1's blind runs used: checked on 2026-09-23 against all 11 freeze-1 records (`code` and `recognizer_sources`), 0 mismatches. The replication report re-checks it from the replication records and pools nothing unless it holds. |
| Freeze | Freeze 4 records the draw: a fresh 128-bit `os.urandom` seed, `n = 10`, `max_reserves = 10`, over `out/s3/blind/candidates.json`, with `draw.excluded` = the ten designs freeze 1 spent (contamination K16), recorded under `freeze_hash` (Freeze 3, `F06`). 74 candidates are eligible. |
| Labelling | The frozen labeller (`tools/s3/thirdparty.py` under Freeze 4), the same pipeline as freeze 1, no manual overrides. A drawn design is replaced by the next reserve **only** if the pipeline cannot label it, never because it looks hard; any replacement is recorded in `out/s3/blind/labels.json` (`replaces`, `replacements`, `reserves_used`). |
| Runs | Each design once, `run.py --blind`, K = 5 `os.urandom` permutations, ledger committed after each attempt. No rerun. The puzzle is not re-run. |
| Freeze-1 numbers | Taken from the ten committed freeze-1 blind records in `out/s3/runs/`, not from `docs/S3.md`'s prose. |

## Outcomes

**Primary:** `counter` harness-**verified** found recall over registers (strict) — the only kind with support in
freeze 1 (59 registers over all 10 designs; 23 verified-found, 0.390). Reported three ways:

1. the replication set **R** alone;
2. the difference **R − B1**, where B1 is freeze 1's blind set;
3. the pooled set **B1 + R** (20 designs).

**Interval method:** a design-level cluster bootstrap — resample *designs* with replacement, recompute the pooled
ratio (registers found / registers), 10,000 resamples, NumPy `default_rng(20260923)`, percentile 95% interval —
for each of the three. Registers inside one design are not independent, which is why this, not a per-register
binomial, is the primary interval. Fisher's exact test and Clopper–Pearson intervals are reported beside it,
labelled as the independence-assuming comparison the first report used.

**Verdict words, fixed now.** R is **consistent with freeze 1** if the 95% bootstrap interval of R − B1 contains 0;
otherwise it is **higher** or **lower**. No other verdict word is used for the primary outcome.

**Secondary, descriptive** (the same bootstrap wherever a kind has registers in at least 3 designs of the set in
question; counts only otherwise): `counter` all-structures found recall; found and verified per kind, strict and
lenient; exact; false positives by cause; grouping AMI with each set's own chance floor; bit order; certified and
transcribed parameter accuracy; the found-but-unverified buckets.

**Label quality**, tiered exactly as `docs/S3.md` §4 (Tier A: a mapped bit z3-refuted or mismatching simulation);
the primary outcome is also reported with Tier A registers removed.

**References:** the pooled set only is set beside the corpus holdout (`holdout_rates.json`, and
`honesty_table.json`'s rates on `score.py`'s own denominators), with the first report's caveat that the item sets
differ.

## What does not change

No recognizer, verifier, scorer or labeller change until the report is written. Label disagreements are listed,
never applied. Every miss and false positive is traced to a cause. After the runs, the ten replication designs are
spent too, and the next freeze that draws excludes them automatically.

## What would void the replication

A recognizer, verifier or scorer file differing from freeze 1's in any replication record; a second blind attempt
of a design; a labeller other than the frozen one; a design replaced for any reason other than a labelling failure.
Any of these is reported, and the affected design is left out of every pooled figure.
