# S3 blind evaluation -- POOLED lens

Frozen code (commit `232cfe6`); `tools/s3/freeze.py check` printed **`freeze holds`** before and after this analysis. Every number below is re-aggregated from the scorer reports inside the frozen run records; nothing was re-run and nothing under `tools/` was touched.

## 0. What each set is

| Set | Designs | What it is | Status |
|---|---|---|---|
| **Blind set** | 10 | third-party Tiny Tapeout designs drawn with the 128-bit freeze seed, anonymised, labelled by the frozen `tools/s3/thirdparty.py` | **the first true out-of-sample test** |
| **Corpus holdout** | 40 | synthetic corpus holdout, published as `out/s3/honesty/holdout_rates.json` **before** the freeze | the pre-published out-of-sample **estimate** |
| **TEMPO** | 1 | the development design | **IN-SAMPLE, fitted** -- never a generalisation estimate |
| **Puzzle** | 1 | the Jane Street puzzle | **frozen code, KNOWN design** -- not blind |

### Pooling rule

**Micro over items.** Raw counts are summed over the designs of the set, then the rate is taken once:

* recall = `sum(registers found) / sum(truth registers of the kind)`
* precision = `sum(structures of the kind that matched) / sum(structures of the kind predicted)`
* F1 = harmonic mean of the pooled precision and recall

**Macro** is the unweighted mean of the per-design rates over the designs that have any register of that kind, and is given beside micro wherever it differs. Each design contributes once: its scorer report is byte-identical across the K = 5 permutations in its record (checked for all 12 records).

**Found and verified are different numbers and are never merged.** *Found* = the recognizer's structure matched the truth register at IoU > 0.5 with the kind accepted. *Verified* = that match made with a structure `tools/s3/verify.py` proved. The scorer re-runs the whole matching over the verified subset, so the two columns are two separate scorings, not a filter of one.

**Strict and lenient were numerically identical on all 12 designs** (blind, puzzle and TEMPO) in every count checked -- registers, structures, found, exact. The denominators are the same in both modes by construction (`Truth.denominators`: `alt_kinds` never shrink a denominator); and on these designs no register was found only through a lenient route (a non-chain unit or an `alt_kinds` acceptance), even though 4 blind truth registers of kind `flag` carry `alt_kinds = ['counter']`. Every table below is therefore *both* modes at once, and says so rather than printing one column twice.

---

## 1. Blind set, pooled -- found vs VERIFIED, strict = lenient

| Kind | Registers (support) | Designs with any | Structures predicted | FOUND regs | found recall | found precision | found F1 | VERIFIED structures | VERIFIED found regs | verified found recall | verified found precision | verified found F1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| counter | **59** | 10 of 10 | 72 | 41 | 0.6949 | 0.5694 | 0.6260 | 34 | 23 | 0.3898 | 0.6765 | 0.4946 |
| shift_register | **8** | 4 of 10 | 1 | 1 | 0.1250 | 1.0000 | 0.2222 | 1 | 1 | 0.1250 | 1.0000 | 0.2222 |
| lfsr_crc | **9** | 1 of 10 | 2 | 0 | 0.0000 | 0.0000 | n/a | 2 | 0 | 0.0000 | 0.0000 | n/a |
| synchronizer | **18** | 4 of 10 | 3 | 17 | 0.9444 | 1.0000 | 0.9714 | 3 | 17 | 0.9444 | 1.0000 | 0.9714 |
| **all four kinds** | **94** | 10 | 78 | 59 | 0.6277 | 0.5769 | 0.6012 | -- | -- | -- | -- | -- |

### Exact, IoU and macro, blind pooled

| Kind | EXACT regs (all structures) | exact recall | exact precision | exact F1 | VERIFIED exact regs | verified exact recall | found@IoU>=0.75 recall | mean IoU over found regs | macro found recall (mean over designs) | false-positive structures |
|---|---|---|---|---|---|---|---|---|---|---|
| counter | 28 | 0.4746 | 0.3889 | 0.4275 | 15 | 0.2542 | 0.5932 | 0.9106 | 0.6383 | 31 of 72 |
| shift_register | 1 | 0.1250 | 1.0000 | 0.2222 | 1 | 0.1250 | 0.1250 | 1.0000 | 0.0833 | 0 of 1 |
| lfsr_crc | 0 | 0.0000 | 0.0000 | n/a | 0 | 0.0000 | 0.0000 | n/a | 0.0000 | 2 of 2 |
| synchronizer | 17 | 0.9444 | 1.0000 | 0.9714 | 17 | 0.9444 | 0.9444 | 1.0000 | 0.7500 | 0 of 3 |

Pooled over all four kinds (strict, all structures): micro-F1 found **0.6012**, micro-F1 exact **0.4463**; macro-F1 over the kinds with registers or predictions found **0.6065**, exact **0.5404**. `lfsr_crc` contributes no F1 (found precision and recall are both 0), so it is absent from the macro-F1 means -- the macro figure is over three kinds, not four.

**Support, said plainly.** `counter` 59 registers over 10 designs is the only kind with real support. `synchronizer` 18 registers sit in 4 designs, and 10 of the 18 are one design (`tt07/tt_um_vzayakov_top`). `lfsr_crc` 9 registers are ALL in ONE design (`tt07/tt_um_toivoh_basilisc_2816`): that is a rate over one design, not over nine independent cases. `shift_register` 8 registers sit in 4 designs. `score.SMALL_SUPPORT` is 3, so none of the pooled kinds is flagged small by the scorer's own rule -- but a pooled rate over 8 or 9 registers still cannot carry a claim.

---

## 2. Blind beside the two pre-published references

> **THE HOLDOUT'S 'found' IS A VERIFIED RATE. holdout_rates.json's own aggregation string: "found = matched a harness-verified structure of an accepted kind at IoU > 0.5; exact = equal flop sets and verified". So holdout.found_rate must be put beside the blind set's VERIFIED found recall, not beside its all-structures found recall. The all-structures comparator is DERIVED HERE as (found + found_unverified) / items from the document's own columns; it is not a number the document publishes.**

> **DIFFERENT ITEM SETS. The holdout counts one item per structure-kind truth register (a synchronizer register of a declared chain unit counted through its unit) PLUS one item per declared structure-kind unit. The blind figures here are score.py's register denominators (tools/s3/score.py Truth.denominators: the truth registers of the kind, identical in strict and lenient). The two denominators are not the same object; holdout_rates.py says so itself ("the two are NOT comparable" of its own two aggregations).**

> **DIFFERENT POPULATIONS. The holdout is 40 SYNTHETIC designs written by this project (its own caveat: "the best out-of-sample estimate that survives this round, not an independent one"); the blind set is 10 real third-party Tiny Tapeout designs.**

> **The holdout rates come from ONE seeded evaluation and carry NO confidence interval (its own caveat). The Clopper-Pearson intervals given below for the BLIND rates are computed here, are not in any record, and assume independent registers -- registers inside one design are not independent, so they are an optimistic floor on the true uncertainty, not a finished inference.**

### 2a. The like-for-like pairing: VERIFIED found

| Kind | BLIND verified found | rate | blind 95% CI | corpus holdout published found rate (= verified) | items | holdout 95% CI | Fisher p | TEMPO verified found (IN-SAMPLE) | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| counter | 23/59 | 0.3898 | [0.265, 0.526] | 0.6364 | 44 | [0.478, 0.776] | 0.0171 | 0.4091 (22 regs) | BELOW the pre-published estimate (Fisher's exact two-sided p = 0.017) -- note the two 95% intervals do overlap, which is the weaker, over-conservative test |
| shift_register | 1/8 | 0.1250 | [0.003, 0.527] | 0.6667 | 30 | [0.472, 0.827] | 0.0130 | 0.5000 (2 regs) | BELOW the pre-published estimate (Fisher's exact two-sided p = 0.013) -- note the two 95% intervals do overlap, which is the weaker, over-conservative test; blind support is 1 of 8 registers -- too small for a rate claim |
| lfsr_crc | 0/9 | 0.0000 | [0.000, 0.336] | 1.0000 | 14 | [0.768, 1.000] | 0.0000 | 1.0000 (2 regs) | BELOW the pre-published estimate (Fisher's exact two-sided p = 1.2e-06); blind support is 0 of 9 registers -- too small for a rate claim; the reference is a boundary rate (exactly 0 or 1), so a point-in-interval test would be degenerate; the two-proportion test above is used instead |
| synchronizer | 17/18 | 0.9444 | [0.727, 0.999] | 1.0000 | 6 | [0.541, 1.000] | 1.0000 | 1.0000 (11 regs) | INDISTINGUISHABLE from the pre-published estimate at this support (Fisher's exact two-sided p = 1.000); the counts differ but the supports cannot separate them; the REFERENCE itself is 6 of 6 items -- too small to be a rate; the reference is a boundary rate (exactly 0 or 1), so a point-in-interval test would be degenerate; the two-proportion test above is used instead |

### 2b. All-structures found (the recognizer's answer, verified or not)

The holdout document publishes no all-structures rate. The comparator below is **derived here** as `(found + found_unverified) / items` from its own columns.

| Kind | BLIND found | rate | 95% CI (computed here) | holdout derived all-structures rate | TEMPO found recall (IN-SAMPLE) | Verdict |
|---|---|---|---|---|---|---|
| counter | 41/59 | 0.6949 | [0.561, 0.808] | 0.8636 (= (28 + 10) / 44) | 1.0000 | INDISTINGUISHABLE from the pre-published estimate at this support (Fisher's exact two-sided p = 0.060); the counts differ but the supports cannot separate them |
| shift_register | 1/8 | 0.1250 | [0.003, 0.527] | 0.6667 (= (20 + 0) / 30) | 1.0000 | BELOW the pre-published estimate (Fisher's exact two-sided p = 0.013) -- note the two 95% intervals do overlap, which is the weaker, over-conservative test; blind support is 1 of 8 registers -- too small for a rate claim |
| lfsr_crc | 0/9 | 0.0000 | [0.000, 0.336] | 1.0000 (= (14 + 0) / 14) | 1.0000 | BELOW the pre-published estimate (Fisher's exact two-sided p = 1.2e-06); blind support is 0 of 9 registers -- too small for a rate claim; the reference is a boundary rate (exactly 0 or 1), so a point-in-interval test would be degenerate; the two-proportion test above is used instead |
| synchronizer | 17/18 | 0.9444 | [0.727, 0.999] | 1.0000 (= (6 + 0) / 6) | 1.0000 | INDISTINGUISHABLE from the pre-published estimate at this support (Fisher's exact two-sided p = 1.000); the counts differ but the supports cannot separate them; the REFERENCE itself is 6 of 6 items -- too small to be a rate; the reference is a boundary rate (exactly 0 or 1), so a point-in-interval test would be degenerate; the two-proportion test above is used instead |

### 2c. EXACT

The holdout's `exact_rate` is also a VERIFIED figure ("equal flop sets **and verified**").

| Kind | BLIND verified exact | rate | holdout published exact rate (= verified) | items | BLIND all-structures exact | TEMPO all-structures exact (IN-SAMPLE) | Verdict (verified vs verified) |
|---|---|---|---|---|---|---|---|
| counter | 15/59 | 0.2542 | 0.6364 | 44 | 28/59 (0.4746) | 20/22 (0.9091) | BELOW the pre-published estimate (Fisher's exact two-sided p = 0.00013) |
| shift_register | 1/8 | 0.1250 | 0.6000 | 30 | 1/8 (0.1250) | 2/2 (1.0000) | BELOW the pre-published estimate (Fisher's exact two-sided p = 0.042) -- note the two 95% intervals do overlap, which is the weaker, over-conservative test; blind support is 1 of 8 registers -- too small for a rate claim |
| lfsr_crc | 0/9 | 0.0000 | 1.0000 | 14 | 0/9 (0.0000) | 2/2 (1.0000) | BELOW the pre-published estimate (Fisher's exact two-sided p = 1.2e-06); blind support is 0 of 9 registers -- too small for a rate claim; the reference is a boundary rate (exactly 0 or 1), so a point-in-interval test would be degenerate; the two-proportion test above is used instead |
| synchronizer | 17/18 | 0.9444 | 0.6667 | 6 | 17/18 (0.9444) | 11/11 (1.0000) | INDISTINGUISHABLE from the pre-published estimate at this support (Fisher's exact two-sided p = 0.143); the counts differ but the supports cannot separate them; the REFERENCE itself is 4 of 6 items -- too small to be a rate |

### 2d. In one sentence per kind

The decision rule is **Fisher's exact two-sided test at alpha = 0.05** on the two item counts, with Clopper-Pearson intervals reported for context. Both assume independent items; registers inside one design are not independent, so the p-values below are anti-conservative and the intervals are a floor on the true uncertainty.

* **counter** -- 59 blind registers over 10 designs, the only kind with real support. **Verified found 23/59 = 0.390** against the pre-published out-of-sample **28/44 = 0.636**: **BELOW** (p = 0.017), though the two 95% intervals ([0.265, 0.526] and [0.478, 0.776]) do graze each other. **All-structures found 41/59 = 0.695** against a derived **38/44 = 0.864**: lower, but **INDISTINGUISHABLE** at this support (p = 0.060). **Verified exact 15/59 = 0.254** against **28/44 = 0.636**: **BELOW**, and this one is not marginal (p = 0.00013). TEMPO's in-sample counter figures (found 22/22 = 1.000, verified found 9/22 = 0.409) are a fitted development number and estimate none of this.
* **shift_register** -- 8 blind registers in 4 designs. **1 of 8 = 0.125** found, verified or not, against a pre-published **20/30 = 0.667**: **BELOW** (p = 0.013), but 8 registers is a thin base and the honest finding is the *shape*, not the rate: the recognizer returned exactly **one** shift-register structure across the entire blind set -- on `tt07/tt_um_toivoh_basilisc_2816` -- and that one was right, exact and verified. The other 7 shift registers (3 on `ttsky26c/.../cordic`, 2 more on basilisc, 1 each on `tt05/tt_um_toivoh_synth` and `ttsky25a/tt_um_sjsu_vga_music`) drew no shift-register answer at all.
* **lfsr_crc** -- 9 blind registers, **every one of them in a single design** (`tt07/tt_um_toivoh_basilisc_2816`). **0 of 9 found**, against a pre-published **14/14 = 1.000**. The shape is worse than the rate: on that one design the recognizer returned **no `lfsr_crc` structure at all**, and the only two `lfsr_crc` structures it returned anywhere on the blind set were on `tt05/tt_um_toivoh_synth` and `ttsky25a/tt_um_sjsu_vga_music`, **neither of which has a single `lfsr_crc` register** -- and the harness **verified both**. The Fisher test says BELOW at p = 1.2e-06, but that p-value treats 9 registers of one design as 9 independent cases, which they are not. **Report this as: the recognizer missed every LFSR/CRC of the one blind design that has any, and its two LFSR/CRC answers were both false positives that the harness nevertheless proved.** It is not an LFSR/CRC rate.
* **synchronizer** -- 18 blind registers in 4 designs, 10 of them in one (`tt07/tt_um_vzayakov_top`). **17 of 18 = 0.944** found and verified (the two columns coincide: every found synchronizer was also verified), against a pre-published **6/6 = 1.000**: **INDISTINGUISHABLE** (p = 1.000). Verified exact 17/18 = 0.944 against the published 4/6 = 0.667 is also **INDISTINGUISHABLE** (p = 0.143). The reference is six items; it cannot support a claim in either direction, and neither the 1.000 nor the 0.667 should be quoted as an established rate.

**Blind supports, said once more, because the rates are meaningless without them:** counter 59 registers / 10 designs; synchronizer 18 / 4 (10 in one design); lfsr_crc 9 / **1** design; shift_register 8 / 4. The pre-published references are 44, 6, 14 and 30 items over 40 synthetic designs. Only the counter comparison rests on two supports that are both worth the name.


---

## 3. Parameters: CERTIFIED vs TRANSCRIBED

A compared parameter is **certified** only when the harness verified the matched structure *and* named that parameter in the verdict's `params_checked`; everything else is **transcribed** -- copied from the recognizer's answer and never checked (`score.PARAMS_CERTIFIED_RULE`).

| Set | Certified compared | certified accuracy | Transcribed compared | transcribed accuracy | Combined compared | combined accuracy | Majority-value baseline | Informative compared | informative accuracy |
|---|---|---|---|---|---|---|---|---|---|
| **Blind set (10 designs)** | 60 | 0.9667 | 38 | 0.9474 | 98 | 0.9592 | 0.9184 (90/98) | 31 | 0.9355 |
| Puzzle (known design) | 83 | 1.0000 | 35 | 1.0000 | 118 | 1.0000 | 0.9661 (114/118) | 30 | 1.0000 |
| TEMPO (IN-SAMPLE) | 43 | 1.0000 | 68 | 0.9412 | 111 | 0.9640 | 0.7928 (88/111) | 83 | 0.9518 |

**Blind, per parameter** (n = comparisons pooled over the 10 designs):

| Parameter | n | correct | accuracy | certified n / correct | transcribed n / correct | majority baseline | designs | informative on |
|---|---|---|---|---|---|---|---|---|
| `counter.direction` | 41 | 41 | 1.0000 | 23 / 23 | 18 / 18 | 0.9268 | 9 | 5 |
| `counter.step` | 41 | 41 | 1.0000 | 23 / 23 | 18 / 18 | 1.0000 | 9 | 1 |
| `counter.modulus` | 10 | 7 | 0.7000 | 9 / 7 | 1 / 0 | 0.5000 | 4 | 2 |
| `synchronizer.stages` | 3 | 3 | 1.0000 | 3 / 3 | 0 / 0 | 1.0000 | 3 | 0 |
| `shift_register.depth` | 1 | 1 | 1.0000 | 1 / 1 | 0 / 0 | 1.0000 | 1 | 0 |
| `shift_register.lanes` | 1 | 1 | 1.0000 | 1 / 1 | 0 / 0 | 1.0000 | 1 | 0 |
| `shift_register.serial_in` | 1 | 0 | 0.0000 | 0 / 0 | 1 / 0 | 1.0000 | 1 | 1 |

> **Two CERTIFIED parameters were WRONG on the blind set.** `counter.modulus` on `ttsky25a/tt_um_sjsu_vga_music` (`noise_counter`: answered 4, truth 3) and on `tt07/tt_um_vzayakov_top` (`DUT.vg.VSCounter.Q`: answered 4096, truth 833600). Both carry `certified: true` in the scorer's `params.wrong` list, i.e. the harness verified the structure and listed `modulus` in `params_checked`. Certified accuracy on the blind set is therefore **58/60 = 0.967, not 1.000** -- against 43/43 = 1.000 on TEMPO and 83/83 = 1.000 on the puzzle. This is either a gap in `verify.py`'s modulus obligation or two truth labels from the frozen third-party labeller; this lens establishes the fact and does not settle which. It is the single most load-bearing number in this report, because 'certified' is what the design document offers as the figure that says no more than the harness proved.

> Two further blind parameter misses are in the TRANSCRIBED column and never claimed proof: `counter.modulus` on `ttsky26c/.../cordic` (`u_cordic.i`: answered `null`, truth 16) and `shift_register.serial_in` on `tt07/tt_um_toivoh_basilisc_2816` (`cpu.pref.sreg`: answered two netlist flop ids, truth the RTL names `ui_in_reg[0]`, `ui_in_reg[1]`).

`lfsr_crc` parameters were compared **zero** times on the blind set: no LFSR/CRC register was found, so `poly`, `form`, `k_steps` and `n_inputs` have **no blind evidence at all**. The honesty block does report `lfsr_poly_certified = 2` over 2 verified `lfsr_crc` structures -- so the harness proved an LFSR polynomial twice, on **two structures that matched no truth register of any kind**. That is `S3_DESIGN` section 3.7's own point made out of sample: verification proves a TEMPLATE, not the truth's label. Both blind `lfsr_crc` structures are verified false positives.

---

## 4. Grouping (AMI / ARI against the baselines)

AMI and ARI are per-design partition scores; they do not sum, so the set figure is the **mean and median over designs**, with each design's own baselines averaged the same way. The random-block baseline is itself the mean of `score.RANDOM_BLOCK_DRAWS` = 5 seeded draws per design.

| Set | designs | AMI mean | AMI median | AMI min | AMI max | ARI mean | ARI median | singleton AMI / ARI | random-block AMI / ARI | pooled exact-word recall |
|---|---|---|---|---|---|---|---|---|---|---|
| **Blind (all flops)** | 10 | 0.8425 | 0.8310 | 0.6641 | 1.0000 | 0.7864 | 0.7283 | 0.0000 / 0.0000 | -0.0010 / 0.0025 | 0.4506 (73/162) |
| Puzzle (all flops) | 1 | 0.9933 | 0.9933 | 0.9933 | 0.9933 | 0.9968 | 0.9968 | 0.0000 / 0.0000 | 0.0107 / 0.0042 | 1.0000 (29/29) |
| TEMPO (all flops) | 1 | 0.9807 | 0.9807 | 0.9807 | 0.9807 | 0.9722 | 0.9722 | 0.0000 / 0.0000 | -0.0009 / -0.0002 | 0.7007 (103/147) |
| Blind (width >= 2 only) | 10 | 0.8421 | 0.8298 | 0.6460 | 1.0000 | 0.7842 | 0.7273 | -0.0000 / 0.0000 | -0.0059 / -0.0059 | 0.4568 (74/162) |
| Puzzle (width >= 2) | 1 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 / 0.0000 | -0.0174 / -0.0107 | 1.0000 (29/29) |
| TEMPO (width >= 2) | 1 | 0.9823 | 0.9823 | 0.9823 | 0.9823 | 0.9727 | 0.9727 | -0.0000 / 0.0000 | 0.0023 / 0.0004 | 0.7007 (103/147) |

The pre-published holdout estimate for grouping is **AMI mean 0.8453, median 1.0** over its 40 synthetic designs (`holdout_rates.json.holdout.grouping`). The blind set's AMI mean is **0.8425** (median 0.8310, min 0.6641, max 1.0000) over 10 designs -- a touch below the estimate's mean and well below its median of 1.0, on 10 design-level observations. Both baselines sit at essentially 0 on both sets, so grouping is the one part of this evaluation that is clearly far better than chance out of sample.

Blind pairwise: precision mean **0.9452**, recall mean **0.7234**, F1 mean **0.8058** -- the recognizer's words are pure but fragmented: 82 splits against 33 merges, 407 predicted blocks over 234 truth blocks.

---

## 5. Bit level (each flop gets one predicted class)

| Set | Kind | flops predicted | flops of the kind (support) | right | precision | recall | F1 |
|---|---|---|---|---|---|---|---|
| Blind | counter | 593 | 657 | 456 | 0.7690 | 0.6941 | 0.7296 |
| Blind | shift_register | 16 | 136 | 16 | 1.0000 | 0.1176 | 0.2105 |
| Blind | lfsr_crc | 28 | 72 | 0 | 0.0000 | 0.0000 | n/a |
| Blind | synchronizer | 18 | 20 | 18 | 1.0000 | 0.9000 | 0.9474 |
| Blind | **micro over kinds** | 655 | 885 | 490 | 0.7481 | 0.5537 | **0.6364** |
| Puzzle | counter | 66 | 66 | 66 | 1.0000 | 1.0000 | 1.0000 |
| Puzzle | shift_register | 12 | 12 | 12 | 1.0000 | 1.0000 | 1.0000 |
| Puzzle | lfsr_crc | 8 | 8 | 8 | 1.0000 | 1.0000 | 1.0000 |
| Puzzle | synchronizer | 0 | 0 | 0 | n/a | n/a | n/a |
| Puzzle | **micro over kinds** | 86 | 86 | 86 | 1.0000 | 1.0000 | **1.0000** |
| TEMPO (IN-SAMPLE) | counter | 121 | 123 | 121 | 1.0000 | 0.9837 | 0.9918 |
| TEMPO (IN-SAMPLE) | shift_register | 39 | 39 | 39 | 1.0000 | 1.0000 | 1.0000 |
| TEMPO (IN-SAMPLE) | lfsr_crc | 64 | 64 | 64 | 1.0000 | 1.0000 | 1.0000 |
| TEMPO (IN-SAMPLE) | synchronizer | 36 | 36 | 36 | 1.0000 | 1.0000 | 1.0000 |
| TEMPO (IN-SAMPLE) | **micro over kinds** | 260 | 262 | 260 | 1.0000 | 0.9924 | **0.9962** |

No flop on any of the 12 designs was predicted into two structure kinds at once (`several` = 0 everywhere), so the `several` class never fires here.

---

## 6. What the VERIFIED count is worth (honesty block, pooled)

| Set | structures returned | scored | VERIFIED | claimed 'proven' by the recognizer | vacuous hold | with unchecked params | with dead bits | without any liveness obligation | LFSR polys certified | load_hidden_share mean / max (over verified naming one) |
|---|---|---|---|---|---|---|---|---|---|---|
| **Blind** | 409 | 405 | 40 | 215 | 6 | 40 | 0 | 6 | 2 | 0.5098 / 0.9929 (n=17) |
| Puzzle | 34 | 34 | 27 | 30 | 1 | 27 | 0 | 2 | 1 | 0.2779 / 0.4541 (n=5) |
| TEMPO (IN-SAMPLE) | 226 | 225 | 15 | 103 | 1 | 15 | 0 | 6 | 0 | 0.5870 / 0.9712 (n=4) |

**Why a found structure was not verified, pooled** (`verify.py` reason buckets):

| Set | unscored kind | hold | vacuous | other |
|---|---|---|---|---|
| **Blind** | 327 | 20 | 18 | none |
| Puzzle | 5 | 2 | 0 | none |
| TEMPO (IN-SAMPLE) | 196 | 14 | 0 | none |

On the blind set the recognizer **claimed** 215 of its 409 structures 'proven'; the harness verified **40**. The scorer counts a result's own `proven` status for nothing, and the gap is exactly why. Of the 38 unverified counter structures, 20 fell to `hold` (the accepted freeze limitation the design document records) and 18 to `vacuous`.

`with_unchecked_params` is 40 of 40 verified structures on the blind set, 27 of 27 on the puzzle and 15 of 15 on TEMPO: **not one verified structure anywhere had all of its parameters certified**.

**Join quality.** 9 of the 10 blind designs joined cleanly. On `ttsky25a/tt_um_sjsu_vga_music` the harness could not map **7 result flops** to the truth's join keys; they were dropped from 4 structures, all 4 of which lost every flop and so left the scoring entirely (21 structures returned, 17 scored). The scorer raised this as a problem on each of the 5 permutations, and it is the only problem raised by any blind record. The 4 lost structures were of unscored kinds (`flag`, `data_register`), so no structure-kind figure in this report moves because of it, but the design's structure count does.

**A verified structure is not a correct one.** On the blind set 40 structures were verified and 45 structures of the four kinds matched something; the harness verified 2 `lfsr_crc` structures that matched nothing at all, and 11 of the 34 verified counter structures matched no counter register (verified found precision 23/34 = 0.676).

---

## 7. Order (Kendall concordance against the truth's order)

Pooled by pairs: each band's score and coverage are the pair-count-weighted means of the per-design figures. For the reversible kinds (`shift_register`, `synchronizer`, `lfsr_crc`) the scorer takes `max(C, D)`, so a pair-weighted mean is the honest pooling and not an exact recomputation.

| Set | Truth kind | Band | registers in found pairs | 'ordered' | 'all correct' | pairs | asserted | score | coverage | chance | lanes_unordered |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Blind | counter | width<=2 | 1 | 1 | 1 | 1 | 1 | 1.0000 | 1.0000 | 0.5000 | 0 |
| Blind | counter | width>=3 | 40 | 40 | 40 | 2797 | 2797 | 1.0000 | 1.0000 | 0.5000 | 0 |
| Blind | data_register | width<=2 | 1 | 1 | 1 | 1 | 1 | 1.0000 | 1.0000 | 0.5000 | 0 |
| Blind | data_register | width>=3 | 11 | 7 | 4 | 1120 | 513 | 0.6335 | 0.4580 | 0.5000 | 0 |
| Blind | register_file_word | width>=3 | 16 | 0 | 0 | 448 | 0 | 0.5000 | 0.0000 | 0.5000 | 0 |
| Blind | shift_register | width>=3 | 1 | 0 | 0 | 120 | 56 | 0.7333 | 0.4667 | 0.5381 | 1 |
| Blind | synchronizer | width<=2 | 1 | 1 | 0 | 1 | 1 | 1.0000 | 1.0000 | 1.0000 | 0 |
| Blind | synchronizer | width>=3 | 2 | 2 | 2 | 8 | 8 | 1.0000 | 1.0000 | 0.7109 | 2 |
| Puzzle | counter | width<=2 | 23 | 23 | 23 | 23 | 23 | 1.0000 | 1.0000 | 0.5000 | 0 |
| Puzzle | counter | width>=3 | 4 | 4 | 4 | 46 | 46 | 1.0000 | 1.0000 | 0.5000 | 0 |
| Puzzle | lfsr_crc | width>=3 | 1 | 1 | 1 | 28 | 28 | 1.0000 | 1.0000 | 0.6160 | 0 |
| Puzzle | shift_register | width>=3 | 1 | 1 | 1 | 66 | 66 | 1.0000 | 1.0000 | 0.5887 | 0 |
| TEMPO | counter | width<=2 | 7 | 7 | 7 | 7 | 7 | 1.0000 | 1.0000 | 0.5000 | 0 |
| TEMPO | counter | width>=3 | 15 | 15 | 15 | 705 | 705 | 1.0000 | 1.0000 | 0.5000 | 0 |
| TEMPO | data_register | width>=3 | 44 | 4 | 4 | 13041 | 1082 | 0.5415 | 0.0830 | 0.5000 | 0 |
| TEMPO | lfsr_crc | width>=3 | 2 | 2 | 2 | 992 | 992 | 1.0000 | 1.0000 | 0.5497 | 0 |
| TEMPO | register_file_word | width>=3 | 21 | 0 | 0 | 10416 | 0 | 0.5000 | 0.0000 | 0.5000 | 0 |
| TEMPO | shift_register | width>=3 | 2 | 2 | 2 | 181 | 181 | 1.0000 | 1.0000 | 0.6050 | 0 |
| TEMPO | synchronizer | width<=2 | 2 | 2 | 0 | 2 | 2 | 1.0000 | 1.0000 | 1.0000 | 0 |
| TEMPO | synchronizer | width>=3 | 1 | 1 | 1 | 16 | 16 | 1.0000 | 1.0000 | 0.5982 | 1 |

Blind headline: **every found counter of width >= 3 was ordered perfectly** -- 40 registers, 2797 ordered pairs, score 1.000 at coverage 1.000 against a chance of 0.500, 40 of 40 'all correct'. That is the strongest blind result in this report and it rests on a real base. The one found `shift_register` asserted only 47% of its pairs (score 0.733), below the `ORDER_COVERAGE_MIN` = 0.5 needed to count as 'ordered'.

---

## 8. Per blind design

| Design | flops | truth regs | structures | verified | counter regs / found / verified | shift regs / found | lfsr regs / found | sync regs / found | AMI | ARI | params correct/compared |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `tt09__tt_um_pwm_top` | 47 | 9 | 13 | 1 | 4 / 1 / 1 | -- | -- | -- | 0.6765 | 0.5112 | 2/2 |
| `ttsky26c__tt_um_joonatanalanampa_cordic` | 191 | 22 | 40 | 4 | 3 / 3 / 3 | 3 / 0 | -- | -- | 0.8239 | 0.7506 | 7/8 |
| `tt05__tt_um_toivoh_synth` | 264 | 31 | 59 | 8 | 5 / 2 / 1 | 1 / 0 | 0 regs, 1 struct predicted (all FP) | 1 / 1 | 0.8382 | 0.7059 | 5/5 |
| `ttsky25a__tt_um_td4` | 145 | 21 | 21 | 0 | 1 / 0 / 0 | -- | -- | -- | 1.0000 | 1.0000 | 0/0 |
| `tt03p5__tt_um_Reloj_top` | 385 | 35 | 85 | 8 | 14 / 7 / 4 | -- | -- | 6 / 6 | 0.7971 | 0.6701 | 15/15 |
| `tt03p5__tt_um_thorkn_vgaclock` | 61 | 9 | 6 | 6 | 6 / 6 / 6 | -- | -- | -- | 1.0000 | 1.0000 | 18/18 |
| `tt07__tt_um_toivoh_basilisc_2816` | 198 | 43 | 67 | 1 | 5 / 2 / 0 | 3 / 1 | 9 / 0 | 1 / 0 | 0.6641 | 0.6464 | 6/7 |
| `ttsky25a__tt_um_sjsu_vga_music` | 70 | 12 | 21 | 6 | 6 / 5 / 5 | 1 / 0 | 0 regs, 1 struct predicted (all FP) | -- | 0.9287 | 0.9364 | 10/11 |
| `tt07__tt_um_vzayakov_top` | 192 | 43 | 72 | 5 | 12 / 12 / 2 | -- | -- | 10 / 10 | 0.7492 | 0.6908 | 25/26 |
| `tt05__tt_um_kskyou` | 148 | 15 | 25 | 1 | 3 / 3 / 1 | -- | -- | -- | 0.9477 | 0.9529 | 6/6 |
| `puzzle` (KNOWN, not blind) | 92 | 35 | 34 | 27 | 27 / 27 / 25 | 1 / 1 | 1 / 1 | -- | 0.9933 | 0.9968 | 118/118 |

---

## 9. The puzzle, kept apart

Frozen code on a design the team has worked on all along -- **not blind, and not an out-of-sample estimate of anything**. Pooled: all four kinds found 29/29 registers, micro-F1 found **1.0000**, micro-F1 exact **1.0000**, bit-level micro-F1 **1.0000**, AMI **0.9933**, ARI **0.9968**, exact words 29/29, parameters 118/118 with 83 certified and all correct. Counter verified found recall is **0.9259** (25 of 27; 2 fell to `hold`). Read it as a regression check on known code, never as evidence about unseen designs.

---

## 10. Things a reader must not do with these numbers

1. Do not quote a TEMPO figure as a generalisation estimate. `score.py` stamps every TEMPO report IN-SAMPLE and the record says so in `provenance.in_sample: true`.
2. Do not quote the puzzle as blind. The run used `--blind` only because the harness requires that flag for the pinned-input path.
3. Do not put the holdout's `found_rate` beside the blind all-structures found recall. The holdout's 'found' already means verified.
4. Do not read `lfsr_crc 0.000` as an LFSR/CRC rate. It is one design.
5. Do not read `synchronizer 1.000` in the holdout column as an established rate: it is 6 items.
6. Do not quote the combined parameter accuracy without the certified/transcribed split beside it, and do not quote the blind certified accuracy as 1.000 -- it is 58/60.
7. `summary.json`'s headline sentence says TEMPO scored "macro and micro F1 1.000 on registers (found and exact)" and "106 of 147 exact words". The **frozen TEMPO record** (`out/s3/eval/runs/tempo-20260923T053247Z-ef7fc630631b.json`, the one force-added in the freeze commit) gives found macro/micro F1 1.000 but **exact** macro 0.977 / micro 0.938, and **103** of 147 exact words. Quote the record, not the summary sentence, and say which.

*Generated from the frozen run records listed in `pooled.json`. Blind set: 10 designs, 1701 flops, 240 truth registers, 409 returned structures. `freeze holds`.*
