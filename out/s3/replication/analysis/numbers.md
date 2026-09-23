# S3 replication -- canonical numbers

Generated 2026-09-23T17:12:22Z by `out/s3/replication/analysis/compute_numbers.py` (sha256 `7d10502447ba5495...`). Every figure below is in `numbers.json` with its numerator, denominator and the record field it came from; the report may quote no figure that is not there. Plan: `docs/S3_REPLICATION_PLAN.md` (95f7eff).

Freeze check before: `freeze holds`; after: `freeze holds`.

Sets: **R** = 10 Freeze-4 designs (freeze `1196c56304e3`, seed `36818e09a9555c29aa45b6917dbce15f`); **B1** = 10 freeze-1 blind designs (`1ee6a4789435`); pooled = B1 + R (20 designs).

## A. Pooling precondition (code identity)

all 10 R records carry the 12 score.OUT_OF_SAMPLE_SOURCES hashes and the 10 recognizer_sources hashes byte-identical to B1's; 0 mismatches; no design is excluded from pooling.

* B1 records agree among themselves: True; also equal to the current tree: True; to out/s3/FREEZE.json's code: True.
* `tt04__tt_um_jayraj4021_SAP1_cpu`: 12 OUT_OF_SAMPLE_SOURCES mismatches 0, recognizer_sources (10) mismatches 0, evaluations with differing recognizer_sources 0; other (non-precondition) code files that differ from B1: tools/s3/freeze.py, tools/s3/run.py, tools/s3/thirdparty.py
* `ttsky26b__tt_um_tiny_8bit_cpu`: 12 OUT_OF_SAMPLE_SOURCES mismatches 0, recognizer_sources (10) mismatches 0, evaluations with differing recognizer_sources 0; other (non-precondition) code files that differ from B1: tools/s3/freeze.py, tools/s3/run.py, tools/s3/thirdparty.py
* `tt06__tt_um_SJ`: 12 OUT_OF_SAMPLE_SOURCES mismatches 0, recognizer_sources (10) mismatches 0, evaluations with differing recognizer_sources 0; other (non-precondition) code files that differ from B1: tools/s3/freeze.py, tools/s3/run.py, tools/s3/thirdparty.py
* `tt06__tt_um_kwilke_cdc_fifo`: 12 OUT_OF_SAMPLE_SOURCES mismatches 0, recognizer_sources (10) mismatches 0, evaluations with differing recognizer_sources 0; other (non-precondition) code files that differ from B1: tools/s3/freeze.py, tools/s3/run.py, tools/s3/thirdparty.py
* `ttsky25b__tt_um_yorimichi_kittscanner`: 12 OUT_OF_SAMPLE_SOURCES mismatches 0, recognizer_sources (10) mismatches 0, evaluations with differing recognizer_sources 0; other (non-precondition) code files that differ from B1: tools/s3/freeze.py, tools/s3/run.py, tools/s3/thirdparty.py
* `tt05__tt_um_digital_clock_sellicott`: 12 OUT_OF_SAMPLE_SOURCES mismatches 0, recognizer_sources (10) mismatches 0, evaluations with differing recognizer_sources 0; other (non-precondition) code files that differ from B1: tools/s3/freeze.py, tools/s3/run.py, tools/s3/thirdparty.py
* `tt05__tt_um_nickjhay_processor`: 12 OUT_OF_SAMPLE_SOURCES mismatches 0, recognizer_sources (10) mismatches 0, evaluations with differing recognizer_sources 0; other (non-precondition) code files that differ from B1: tools/s3/freeze.py, tools/s3/run.py, tools/s3/thirdparty.py
* `ttsky25b__tt_um_ieeeuoftasic_simproc`: 12 OUT_OF_SAMPLE_SOURCES mismatches 0, recognizer_sources (10) mismatches 0, evaluations with differing recognizer_sources 0; other (non-precondition) code files that differ from B1: tools/s3/freeze.py, tools/s3/run.py, tools/s3/thirdparty.py
* `ttsky26a__tt_um_parakeet`: 12 OUT_OF_SAMPLE_SOURCES mismatches 0, recognizer_sources (10) mismatches 0, evaluations with differing recognizer_sources 0; other (non-precondition) code files that differ from B1: tools/s3/freeze.py, tools/s3/run.py, tools/s3/thirdparty.py
* `ttcad25a__tt_um_space_invaders_game`: 12 OUT_OF_SAMPLE_SOURCES mismatches 0, recognizer_sources (10) mismatches 0, evaluations with differing recognizer_sources 0; other (non-precondition) code files that differ from B1: tools/s3/freeze.py, tools/s3/run.py, tools/s3/thirdparty.py

## B. Primary outcome

```
PRIMARY -- counter harness-VERIFIED found recall over registers (strict); design-level cluster bootstrap, 10,000 resamples, numpy default_rng(20260923), percentile 95%.
  R  (replication, 10 designs):  19/49 = 0.3878  bootstrap 95% [0.2245, 0.6286]
  B1 (freeze 1, 10 designs):    23/59 = 0.3898  bootstrap 95% [0.2162, 0.6458]
  R - B1:  -0.0021  bootstrap 95% [-0.3121, 0.2853] (each set resampled independently)
  Pooled B1+R (20 designs): 42/108 = 0.3889  bootstrap 95% [0.2617, 0.5517] (resampled within each set); sensitivity, 20 designs as one set: [0.2583, 0.5534]
  Independence-assuming comparison (the first report's): Fisher exact two-sided p (R vs B1) = 1.0000; Clopper-Pearson 95%: R [0.2520, 0.5376], B1 [0.2655, 0.5256], pooled [0.2966, 0.4875]
  VERDICT (plan's words): consistent with freeze 1
```

| Set | designs | registers | verified found | rate | bootstrap 95% | Clopper-Pearson 95% |
|---|---|---|---|---|---|---|
| R | 10 | 49 | 19 | 0.3878 | [0.2245, 0.6286] | [0.2520, 0.5376] |
| B1 | 10 | 59 | 23 | 0.3898 | [0.2162, 0.6458] | [0.2655, 0.5256] |
| R - B1 | | | | -0.0021 | [-0.3121, 0.2853] | Fisher p = 1.0000 |
| pooled B1+R | 20 | 108 | 42 | 0.3889 | [0.2617, 0.5517] (stratified); [0.2583, 0.5534] (one set) | [0.2966, 0.4875] |

**Verdict (the plan's words):** consistent with freeze 1.

Per design (registers / verified found / found):

| R design | regs | verified | found |  | B1 design | regs | verified | found |
|---|---|---|---|---|---|---|---|---|
| `tt04__tt_um_jayraj4021_SAP1_cpu` | 1 | 1 | 1 |  | `tt09__tt_um_pwm_top` | 4 | 1 | 1 |
| `ttsky26b__tt_um_tiny_8bit_cpu` | 0 | 0 | 0 |  | `ttsky26c__tt_um_joonatanalanampa_cordic` | 3 | 3 | 3 |
| `tt06__tt_um_SJ` | 12 | 2 | 3 |  | `tt05__tt_um_toivoh_synth` | 5 | 1 | 2 |
| `tt06__tt_um_kwilke_cdc_fifo` | 2 | 0 | 2 |  | `ttsky25a__tt_um_td4` | 1 | 0 | 0 |
| `ttsky25b__tt_um_yorimichi_kittscanner` | 4 | 2 | 2 |  | `tt03p5__tt_um_Reloj_top` | 14 | 4 | 7 |
| `tt05__tt_um_digital_clock_sellicott` | 8 | 7 | 7 |  | `tt03p5__tt_um_thorkn_vgaclock` | 6 | 6 | 6 |
| `tt05__tt_um_nickjhay_processor` | 1 | 0 | 1 |  | `tt07__tt_um_toivoh_basilisc_2816` | 5 | 0 | 2 |
| `ttsky25b__tt_um_ieeeuoftasic_simproc` | 4 | 1 | 4 |  | `ttsky25a__tt_um_sjsu_vga_music` | 6 | 5 | 5 |
| `ttsky26a__tt_um_parakeet` | 5 | 2 | 2 |  | `tt07__tt_um_vzayakov_top` | 12 | 2 | 12 |
| `ttcad25a__tt_um_space_invaders_game` | 12 | 4 | 9 |  | `tt05__tt_um_kskyou` | 3 | 1 | 3 |

## C. Secondary (descriptive)

### counter all-structures found recall

* R 31/49 = 0.6327, bootstrap [0.4237, 0.8627]
* B1 41/59 = 0.6949, bootstrap [0.5000, 0.8904]
* R - B1 -0.0623, bootstrap [-0.3492, 0.2438]
* pooled 72/108 = 0.6667, bootstrap [0.5238, 0.8182] (stratified), [0.5231, 0.8191] (one set)
* independence-assuming: Fisher p 0.5423; CP R [0.4829, 0.7658], B1 [0.5613, 0.8081], pooled [0.5695, 0.7545]

### Per kind (strict; lenient identical where flagged)

**R**

| kind | regs | designs | structs | found | recall | verified structs | verified found | v. recall | exact | v. exact | precision | v. precision | FP | v. FP | mean IoU | found@0.75 | strict = lenient |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| counter | 49 | 9 | 56 | 31 | 0.6327 | 33 | 19 | 0.3878 | 20 | 12 | 0.5536 | 0.5758 | 25 | 14 | 0.8986 | 23 | True |
| shift_register | 9 | 5 | 12 | 4 | 0.4444 | 6 | 3 | 0.3333 | 4 | 3 | 0.3333 | 0.5000 | 8 | 3 | 1.0000 | 4 | False |
| lfsr_crc | 0 | 0 | 1 | 0 | n/a | 1 | 0 | n/a | 0 | 0 | 0.0000 | 0.0000 | 1 | 1 | n/a | 0 | True |
| synchronizer | 10 | 5 | 3 | 6 | 0.6000 | 3 | 6 | 0.6000 | 6 | 6 | 1.0000 | 1.0000 | 0 | 0 | 1.0000 | 6 | True |
| all four | 68 | | 72 | 41 | 0.6029 | 43 | 28 | 0.4118 | 30 | 21 | 0.5278 | 0.5814 | 34 | 18 | | | |

Register micro-F1 found 0.5629, exact 0.4054; macro-F1 found 0.4304 (score.py convention) / 0.5738 (docs/S3.md convention), exact 0.3780 / 0.5040. Counter distinct design keys found_all / found_any / total: 23/23/33; counter macro recall 0.7528.

**B1**

| kind | regs | designs | structs | found | recall | verified structs | verified found | v. recall | exact | v. exact | precision | v. precision | FP | v. FP | mean IoU | found@0.75 | strict = lenient |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| counter | 59 | 10 | 72 | 41 | 0.6949 | 34 | 23 | 0.3898 | 28 | 15 | 0.5694 | 0.6765 | 31 | 11 | 0.9106 | 35 | True |
| shift_register | 8 | 4 | 1 | 1 | 0.1250 | 1 | 1 | 0.1250 | 1 | 1 | 1.0000 | 1.0000 | 0 | 0 | 1.0000 | 1 | True |
| lfsr_crc | 9 | 1 | 2 | 0 | 0.0000 | 2 | 0 | 0.0000 | 0 | 0 | 0.0000 | 0.0000 | 2 | 2 | n/a | 0 | True |
| synchronizer | 18 | 4 | 3 | 17 | 0.9444 | 3 | 17 | 0.9444 | 17 | 17 | 1.0000 | 1.0000 | 0 | 0 | 1.0000 | 17 | True |
| all four | 94 | | 78 | 59 | 0.6277 | 40 | 41 | 0.4362 | 46 | 33 | 0.5769 | 0.6750 | 33 | 13 | | | |

Register micro-F1 found 0.6012, exact 0.4463; macro-F1 found 0.4549 (score.py convention) / 0.6065 (docs/S3.md convention), exact 0.4053 / 0.5404. Counter distinct design keys found_all / found_any / total: 27/28/44; counter macro recall 0.6383.

**pooled_B1_plus_R**

| kind | regs | designs | structs | found | recall | verified structs | verified found | v. recall | exact | v. exact | precision | v. precision | FP | v. FP | mean IoU | found@0.75 | strict = lenient |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| counter | 108 | 19 | 128 | 72 | 0.6667 | 67 | 42 | 0.3889 | 48 | 27 | 0.5625 | 0.6269 | 56 | 25 | 0.9054 | 58 | True |
| shift_register | 17 | 9 | 13 | 5 | 0.2941 | 7 | 4 | 0.2353 | 5 | 4 | 0.3846 | 0.5714 | 8 | 3 | 1.0000 | 5 | False |
| lfsr_crc | 9 | 1 | 3 | 0 | 0.0000 | 3 | 0 | 0.0000 | 0 | 0 | 0.0000 | 0.0000 | 3 | 3 | n/a | 0 | True |
| synchronizer | 28 | 9 | 6 | 23 | 0.8214 | 6 | 23 | 0.8214 | 23 | 23 | 1.0000 | 1.0000 | 0 | 0 | 1.0000 | 23 | True |
| all four | 162 | | 150 | 100 | 0.6173 | 83 | 69 | 0.4259 | 76 | 54 | 0.5533 | 0.6265 | 67 | 31 | | | |

Register micro-F1 found 0.5836, exact 0.4279; macro-F1 found 0.4614 (score.py convention) / 0.6152 (docs/S3.md convention), exact 0.4105 / 0.5474. Counter distinct design keys found_all / found_any / total: 50/51/77; counter macro recall 0.6925.

* R shift_register: LENIENT differs from strict -- found 6/9 = 0.6667, exact 6, precision 5/12; verified found 5/9 = 0.5556
* pooled_B1_plus_R shift_register: LENIENT differs from strict -- found 7/17 = 0.4118, exact 7, precision 6/13; verified found 6/17 = 0.3529

### Per-kind bootstrap (kinds with registers in >= 3 designs of the set)

| kind | designs R / B1 / pooled | metric | R | B1 | pooled (stratified) | R - B1 |
|---|---|---|---|---|---|---|
| counter | 9 / 10 / 19 | found | [0.4237, 0.8627] | [0.5000, 0.8904] | [0.5238, 0.8182] | [-0.3492, 0.2438] |
| counter | 9 / 10 / 19 | verified_found | [0.2245, 0.6286] | [0.2162, 0.6458] | [0.2617, 0.5517] | [-0.3121, 0.2853] |
| counter | 9 / 10 / 19 | exact | [0.2424, 0.5862] | [0.1746, 0.7963] | [0.2600, 0.6456] | [-0.4294, 0.2836] |
| counter | 9 / 10 / 19 | verified_exact | [0.1111, 0.4483] | [0.0746, 0.5490] | [0.1250, 0.4184] | [-0.3356, 0.2605] |
| shift_register | 5 / 4 / 9 | found | [0.0000, 0.6667] | [0.0000, 0.3077] | [0.0909, 0.4615] | [-0.0500, 0.6154] |
| shift_register | 5 / 4 / 9 | verified_found | [0.0000, 0.6667] | [0.0000, 0.3077] | [0.0833, 0.4000] | [-0.0857, 0.5831] |
| shift_register | 5 / 4 / 9 | exact | [0.0000, 0.6667] | [0.0000, 0.3077] | [0.0909, 0.4615] | [-0.0500, 0.6154] |
| shift_register | 5 / 4 / 9 | verified_exact | [0.0000, 0.6667] | [0.0000, 0.3077] | [0.0833, 0.4000] | [-0.0857, 0.5831] |
| lfsr_crc | 0 / 1 / 1 | found | counts only | counts only | counts only | - |
| lfsr_crc | 0 / 1 / 1 | verified_found | counts only | counts only | counts only | - |
| lfsr_crc | 0 / 1 / 1 | exact | counts only | counts only | counts only | - |
| lfsr_crc | 0 / 1 / 1 | verified_exact | counts only | counts only | counts only | - |
| synchronizer | 5 / 4 / 9 | found | [0.0000, 1.0000] | [0.2500, 1.0000] | [0.4167, 1.0000] | [-0.8750, 0.4154] |
| synchronizer | 5 / 4 / 9 | verified_found | [0.0000, 1.0000] | [0.2500, 1.0000] | [0.4167, 1.0000] | [-0.8750, 0.4154] |
| synchronizer | 5 / 4 / 9 | exact | [0.0000, 1.0000] | [0.2500, 1.0000] | [0.4167, 1.0000] | [-0.8750, 0.4154] |
| synchronizer | 5 / 4 / 9 | verified_exact | [0.0000, 1.0000] | [0.2500, 1.0000] | [0.4167, 1.0000] | [-0.8750, 0.4154] |

### Found but unverified

* R: 13 registers; by cause {'V1 control.hold not claimed': 12, 'V2 hold region emptied only by the opaque load cases (HOLD_EMPTY_NEEDS_VERIFIED_COVER (a))': 1}; by kind {'counter': 12, 'shift_register': 1}; exact among them 9
* B1: 18 registers; by cause {'V2 hold region emptied only by the opaque load cases (HOLD_EMPTY_NEEDS_VERIFIED_COVER (a))': 16, 'V1 control.hold not claimed': 2}; by kind {'counter': 18}; exact among them 13
* pooled: {'registers': 31, 'by_cause': {'V2 hold region emptied only by the opaque load cases (HOLD_EMPTY_NEEDS_VERIFIED_COVER (a))': 17, 'V1 control.hold not claimed': 14}}

### Misses and false positives (mechanical split, strict)

* R misses 27: {'counter | matched by nothing (best IoU <= 0.5)': 13, 'counter | matched, kind refused: unscored kind': 5, 'shift_register | matched by nothing (best IoU <= 0.5)': 4, 'synchronizer | matched by nothing (best IoU <= 0.5)': 1, 'shift_register | matched, kind refused: scored kind': 1, 'synchronizer | matched, kind refused: unscored kind': 3}
* R false positives 34 (18 verified): {'counter | matched nothing': 23, 'shift_register | matched nothing': 8, 'counter | matched a truth accumulator register (kind refused)': 1, 'counter | matched a truth other register (kind refused)': 1, 'lfsr_crc | matched a truth shift_register register (kind refused)': 1}; verified by category {'matched nothing': 15, 'matched a truth accumulator register (kind refused)': 1, 'matched a truth other register (kind refused)': 1, 'matched a truth shift_register register (kind refused)': 1}; matched-nothing by best register kind {'accumulator': 4, 'data_register': 3, 'flag': 9, 'shift_register': 2, 'counter': 12, 'synchronizer': 1}
* B1 misses 35: {'counter | matched by nothing (best IoU <= 0.5)': 11, 'counter | matched, kind refused: unscored kind': 7, 'shift_register | matched by nothing (best IoU <= 0.5)': 3, 'shift_register | matched, kind refused: unscored kind': 2, 'shift_register | matched, kind refused: scored kind': 2, 'lfsr_crc | matched by nothing (best IoU <= 0.5)': 9, 'synchronizer | matched, kind refused: unscored kind': 1}
* B1 false positives 33 (13 verified): {'counter | matched nothing': 16, 'counter | matched a truth accumulator register (kind refused)': 15, 'lfsr_crc | matched a truth shift_register register (kind refused)': 2}; verified by category {'matched nothing': 10, 'matched a truth shift_register register (kind refused)': 2, 'matched a truth accumulator register (kind refused)': 1}; matched-nothing by best register kind {'counter': 6, 'accumulator': 10}

### What the verified count is worth

| set | returned | scored | verified | claimed proven | verified not claimed | vacuous hold | unchecked params | dead bits | no liveness | LFSR polys certified | load share mean / max (n) | budget | unknown | unverified reasons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R | 455 | 446 | 43 | 172 | 0 | 5 | 43 | 0 | 10 | 1 | 0.4263 / 1.0000 (17) | 0 | 0 | {'unscored kind': 374, 'hold': 27, 'vacuous': 2} |
| B1 | 409 | 405 | 40 | 215 | 0 | 6 | 40 | 0 | 6 | 2 | 0.5098 / 0.9929 (17) | 0 | 0 | {'unscored kind': 327, 'hold': 20, 'vacuous': 18} |
| pooled_B1_plus_R | 864 | 851 | 83 | 387 | 0 | 11 | 83 | 0 | 16 | 3 | 0.4681 / 1.0000 (34) | 0 | 0 | {'unscored kind': 701, 'hold': 47, 'vacuous': 20} |

### Grouping (all flops; each set's own random-block chance floor)

| set | designs | AMI mean | median | min | max | ARI mean | random-block AMI mean / median | singletons AMI mean | AMI mean - floor | exact words | splits / merges | pair P / R / F1 (means) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R | 10 | 0.7561 | 0.8432 | 0.0307 | 1.0000 | 0.6534 | -0.0007 / -0.0014 | 0.0000 | 0.7567 | 212/329 | 62 / 47 | 0.6904 / 0.7979 / 0.6679 |
| B1 | 10 | 0.8425 | 0.8310 | 0.6641 | 1.0000 | 0.7864 | -0.0010 / 0.0009 | 0.0000 | 0.8435 | 73/162 | 82 / 33 | 0.9452 / 0.7234 / 0.8058 |
| pooled_B1_plus_R | 20 | 0.7993 | 0.8323 | 0.0307 | 1.0000 | 0.7199 | -0.0008 / -0.0014 | 0.0000 | 0.8001 | 285/491 | 144 / 80 | 0.8178 / 0.7607 / 0.7369 |

### Order (counter and the other kinds; both bands and pooled as honesty_table.py pools)

| set | kind | band | items | ordered | all correct | pairs | asserted | score | chance | kappa |
|---|---|---|---|---|---|---|---|---|---|---|
| R | counter | width<=2 | 2 | 2 | 2 | 2 | 2 | 1.0000 | 0.5000 | 1.0000 |
| R | counter | width>=3 | 29 | 29 | 29 | 820 | 820 | 1.0000 | 0.5000 | 1.0000 |
| R | counter | **both** | 31 | 31 | 31 | 822 | 822 | 1.0000 | 0.5000 | 1.0000 |
| R | data_register | width<=2 | 2 | 0 | 0 | 2 | 0 | 0.5000 | 0.5000 | 0.0000 |
| R | data_register | width>=3 | 50 | 3 | 3 | 1440 | 100 | 0.5347 | 0.5000 | 0.0694 |
| R | data_register | **both** | 52 | 3 | 3 | 1442 | 100 | 0.5347 | 0.5000 | 0.0693 |
| R | register_file_word | width>=3 | 124 | 0 | 0 | 2768 | 0 | 0.5000 | 0.5000 | 0.0000 |
| R | register_file_word | **both** | 124 | 0 | 0 | 2768 | 0 | 0.5000 | 0.5000 | 0.0000 |
| R | shift_register | width>=3 | 5 | 5 | 5 | 1223 | 1223 | 1.0000 | 0.5451 | 1.0000 |
| R | shift_register | **both** | 5 | 5 | 5 | 1223 | 1223 | 1.0000 | 0.5451 | 1.0000 |
| R | synchronizer | width<=2 | 2 | 2 | 0 | 2 | 2 | 1.0000 | 1.0000 | n/a |
| R | synchronizer | width>=3 | 1 | 1 | 1 | 3 | 3 | 1.0000 | 0.7500 | 1.0000 |
| R | synchronizer | **both** | 3 | 3 | 1 | 5 | 5 | 1.0000 | 0.8500 | 1.0000 |
| B1 | counter | width<=2 | 1 | 1 | 1 | 1 | 1 | 1.0000 | 0.5000 | 1.0000 |
| B1 | counter | width>=3 | 40 | 40 | 40 | 2797 | 2797 | 1.0000 | 0.5000 | 1.0000 |
| B1 | counter | **both** | 41 | 41 | 41 | 2798 | 2798 | 1.0000 | 0.5000 | 1.0000 |
| B1 | data_register | width<=2 | 1 | 1 | 1 | 1 | 1 | 1.0000 | 0.5000 | 1.0000 |
| B1 | data_register | width>=3 | 11 | 7 | 4 | 1120 | 513 | 0.6335 | 0.5000 | 0.2670 |
| B1 | data_register | **both** | 12 | 8 | 5 | 1121 | 514 | 0.6338 | 0.5000 | 0.2676 |
| B1 | register_file_word | width>=3 | 16 | 0 | 0 | 448 | 0 | 0.5000 | 0.5000 | 0.0000 |
| B1 | register_file_word | **both** | 16 | 0 | 0 | 448 | 0 | 0.5000 | 0.5000 | 0.0000 |
| B1 | shift_register | width>=3 | 1 | 0 | 0 | 120 | 56 | 0.7333 | 0.5381 | 0.4226 |
| B1 | shift_register | **both** | 1 | 0 | 0 | 120 | 56 | 0.7333 | 0.5381 | 0.4226 |
| B1 | synchronizer | width<=2 | 1 | 1 | 0 | 1 | 1 | 1.0000 | 1.0000 | n/a |
| B1 | synchronizer | width>=3 | 2 | 2 | 2 | 8 | 8 | 1.0000 | 0.7109 | 1.0000 |
| B1 | synchronizer | **both** | 3 | 3 | 2 | 9 | 9 | 1.0000 | 0.7431 | 1.0000 |
| pooled_B1_plus_R | counter | width<=2 | 3 | 3 | 3 | 3 | 3 | 1.0000 | 0.5000 | 1.0000 |
| pooled_B1_plus_R | counter | width>=3 | 69 | 69 | 69 | 3617 | 3617 | 1.0000 | 0.5000 | 1.0000 |
| pooled_B1_plus_R | counter | **both** | 72 | 72 | 72 | 3620 | 3620 | 1.0000 | 0.5000 | 1.0000 |
| pooled_B1_plus_R | data_register | width<=2 | 3 | 1 | 1 | 3 | 1 | 0.6667 | 0.5000 | 0.3333 |
| pooled_B1_plus_R | data_register | width>=3 | 61 | 10 | 7 | 2560 | 613 | 0.5779 | 0.5000 | 0.1559 |
| pooled_B1_plus_R | data_register | **both** | 64 | 11 | 8 | 2563 | 614 | 0.5780 | 0.5000 | 0.1561 |
| pooled_B1_plus_R | register_file_word | width>=3 | 140 | 0 | 0 | 3216 | 0 | 0.5000 | 0.5000 | 0.0000 |
| pooled_B1_plus_R | register_file_word | **both** | 140 | 0 | 0 | 3216 | 0 | 0.5000 | 0.5000 | 0.0000 |
| pooled_B1_plus_R | shift_register | width>=3 | 6 | 5 | 5 | 1343 | 1279 | 0.9762 | 0.5445 | 0.9477 |
| pooled_B1_plus_R | shift_register | **both** | 6 | 5 | 5 | 1343 | 1279 | 0.9762 | 0.5445 | 0.9477 |
| pooled_B1_plus_R | synchronizer | width<=2 | 3 | 3 | 0 | 3 | 3 | 1.0000 | 1.0000 | n/a |
| pooled_B1_plus_R | synchronizer | width>=3 | 3 | 3 | 3 | 11 | 11 | 1.0000 | 0.7216 | 1.0000 |
| pooled_B1_plus_R | synchronizer | **both** | 6 | 6 | 3 | 14 | 14 | 1.0000 | 0.7812 | 1.0000 |

### Parameters

| set | certified | transcribed | combined | informative | majority baseline |
|---|---|---|---|---|---|
| R | 45/50 = 0.9000 | 26/34 = 0.7647 | 71/84 = 0.8452 | 30/38 = 0.7895 | 70/84 = 0.8333 |
| B1 | 58/60 = 0.9667 | 36/38 = 0.9474 | 94/98 = 0.9592 | 29/31 = 0.9355 | 90/98 = 0.9184 |
| pooled_B1_plus_R | 103/110 = 0.9364 | 62/72 = 0.8611 | 165/182 = 0.9066 | 59/69 = 0.8551 | 160/182 = 0.8791 |

R per parameter: `counter.direction` 31/31 (certified 19/19); `counter.modulus` 0/4 (certified 0/1); `counter.step` 26/31 (certified 15/19); `shift_register.depth` 5/5 (certified 4/4); `shift_register.lanes` 5/5 (certified 4/4); `shift_register.serial_in` 1/5 (certified 0/0); `synchronizer.stages` 3/3 (certified 3/3)

R wrong parameters: `tt06__tt_um_SJ` `DUT.U1.countPE` counter.modulus answered null truth 4 (transcribed); `tt06__tt_um_SJ` `DUT.U1.countRow` counter.modulus answered 64 truth 4 (certified); `ttsky25b__tt_um_yorimichi_kittscanner` `i_debouncer.sample_ff` shift_register.serial_in answered ["dfrtp_1_144900_100640"] truth ["i_debouncer.sync_ff[1]"] (transcribed); `tt05__tt_um_digital_clock_sellicott` `clock_inst.shift_out_inst.shift_reg_div_inst.counter` counter.step answered 1 truth 1073741824 (certified); `tt05__tt_um_digital_clock_sellicott` `clock_inst.clock_gen_inst.sysclk_div_inst.counter` counter.step answered 1 truth 858 (certified); `tt05__tt_um_digital_clock_sellicott` `clock_inst.shift_out_stb_delay` shift_register.serial_in answered [null] truth ["clock_inst.clk_1hz_stb", "clock_inst.clock_in_timeset_stb", "clock_inst.refclk_1hz_stb"] (transcribed); `tt05__tt_um_digital_clock_sellicott` `clock_inst.shift_out_inst.shift_out_inst.serial_data` shift_register.serial_in answered [null] truth ["1'b0", "1'b1", "1'bx"] (transcribed); `tt05__tt_um_nickjhay_processor` `text_idx` counter.modulus answered null truth 2 (transcribed); `ttsky25b__tt_um_ieeeuoftasic_simproc` `U1.UART1.UART_TX1.index` counter.modulus answered null truth 10 (transcribed); `ttsky26a__tt_um_parakeet` `driver.driver.shift_reg` shift_register.serial_in answered ["dfxtp_2_135240_100640"] truth ["driver.driver.pmod_data_sync[1]"] (transcribed); `ttcad25a__tt_um_space_invaders_game` `group_x` counter.step answered 1 truth 2 (certified); `ttcad25a__tt_um_space_invaders_game` `abullet_y` counter.step answered 1 truth 10 (certified); `ttcad25a__tt_um_space_invaders_game` `shooter_x` counter.step answered 5 truth 10 (transcribed)

### Bit level (all structures, strict)

| set | counter P/R/F1 | shift P/R/F1 | lfsr P/R/F1 | sync P/R/F1 | micro F1 | macro F1 (score.py / docs) |
|---|---|---|---|---|---|---|
| R | 0.888 / 0.702 / 0.784 | 0.163 / 0.895 / 0.276 | 0.000 / n/a / 0.000 | 1.000 / 0.476 / 0.645 | 0.5570 | 0.4264 / 0.5685 |
| B1 | 0.769 / 0.694 / 0.730 | 1.000 / 0.118 / 0.211 | 0.000 / 0.000 / 0.000 | 1.000 / 0.900 / 0.947 | 0.6364 | 0.4719 / 0.6292 |
| pooled_B1_plus_R | 0.812 / 0.697 / 0.750 | 0.188 / 0.437 / 0.263 | 0.000 / 0.000 / 0.000 | 1.000 / 0.683 / 0.812 | 0.5982 | 0.4563 / 0.6084 |

### Per design, R

| design | flops | regs | structs | verified | counter r/f/v/e | shift r/f/v | lfsr r/f/v | sync r/f/v | AMI | ARI | params cert. | transcr. | tiers | dropped flops |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `tt04__tt_um_jayraj4021_SAP1_cpu` | 53 | 9 | 15 | 1 | 1/1/1/1 | 0/0/0 | 0/0/0 | 0/0/0 | 0.9248 | 0.9514 | 2/2 | 0/0 | {'C_clean': 1} | 0 |
| `ttsky26b__tt_um_tiny_8bit_cpu` | 232 | 32 | 45 | 0 | 0/0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 | 0.9850 | 0.9822 | 0/0 | 0/0 | {} | 72 |
| `tt06__tt_um_SJ` | 685 | 109 | 78 | 2 | 12/3/2/2 | 1/0/0 | 0/0/0 | 0/0/0 | 0.7592 | 0.2604 | 4/5 | 2/3 | {'A_contradicted': 4, 'C_clean': 9} | 0 |
| `tt06__tt_um_kwilke_cdc_fifo` | 158 | 39 | 38 | 0 | 2/2/0/2 | 0/0/0 | 0/0/0 | 0/0/0 | 1.0000 | 1.0000 | 0/0 | 4/4 | {'C_clean': 2} | 0 |
| `ttsky25b__tt_um_yorimichi_kittscanner` | 113 | 28 | 33 | 7 | 4/2/2/0 | 2/1/1 | 0/0/0 | 1/1/1 | 0.5700 | 0.3168 | 7/7 | 0/1 | {'C_clean': 7} | 0 |
| `tt05__tt_um_digital_clock_sellicott` | 305 | 38 | 48 | 16 | 8/7/7/5 | 4/2/1 | 0/0/0 | 0/0/0 | 0.8265 | 0.6447 | 16/18 | 3/5 | {'B_narrowed': 2, 'C_clean': 9, 'A_contradicted': 1} | 0 |
| `tt05__tt_um_nickjhay_processor` | 201 | 188 | 10 | 1 | 1/1/0/0 | 0/0/0 | 0/0/0 | 1/0/0 | 0.0307 | 0.0098 | 0/0 | 2/3 | {'C_clean': 2} | 0 |
| `ttsky25b__tt_um_ieeeuoftasic_simproc` | 706 | 99 | 108 | 3 | 4/4/1/2 | 0/0/0 | 0/0/0 | 2/2/2 | 0.9607 | 0.9366 | 3/3 | 6/7 | {'C_clean': 6} | 0 |
| `ttsky26a__tt_um_parakeet` | 77 | 18 | 20 | 5 | 5/2/2/2 | 1/1/1 | 0/0/0 | 3/3/3 | 0.8599 | 0.9052 | 7/7 | 0/1 | {'C_clean': 9} | 0 |
| `ttcad25a__tt_um_space_invaders_game` | 197 | 76 | 60 | 8 | 12/9/4/6 | 1/0/0 | 0/0/0 | 3/0/0 | 0.6438 | 0.5267 | 6/8 | 9/10 | {'C_clean': 8, 'A_contradicted': 7, 'B_narrowed': 1} | 0 |

## D. Label quality (R)

Rule: docs/S3.md section 4, exactly as freeze 1's analysis computed it (out/s3/blind/analysis/
audit_labels.py reg_weakness + build_labels.py tier): over the register's truth bits that carry a
netlist flop, a bit whose z3 mapping proof is not 'proven' or whose random-simulation check is not
'match' (an absent field counts as not proven / not matching) makes the register Tier A
('A_contradicted'); otherwise a bit with no netlist flop makes it Tier B ('B_narrowed'); otherwise
'C_clean'. Sub-tier (write_labels.py's A1/A2): A1 when at least one mapped bit is not 'match' in
simulation, else A2 (z3 not proven while simulation agreed).

* R: tiers {'C_clean': 53, 'A_contradicted': 12, 'B_narrowed': 3}; sub-tiers {'C_clean': 53, 'A1_simulation_mismatch': 5, 'B_narrowed': 3, 'A2_z3_refuted_only': 7}; counter tiers {'C_clean': 36, 'A_contradicted': 10, 'B_narrowed': 3}
* B1: tiers {'C_clean': 69, 'B_narrowed': 2, 'A_contradicted': 23}; sub-tiers {'C_clean': 69, 'B_narrowed': 2, 'A1_simulation_mismatch': 16, 'A2_z3_refuted_only': 7}; counter tiers {'C_clean': 47, 'B_narrowed': 1, 'A_contradicted': 11}
* pooled_B1_plus_R: tiers {'C_clean': 122, 'B_narrowed': 5, 'A_contradicted': 35}; sub-tiers {'C_clean': 122, 'B_narrowed': 5, 'A1_simulation_mismatch': 21, 'A2_z3_refuted_only': 14}; counter tiers {'C_clean': 83, 'B_narrowed': 4, 'A_contradicted': 21}
* R flop level: {'flops': 545, 'mapping_proof_refuted': 52, 'refuted_and_simulation_mismatch': 27}
* B1 flop level: {'flops': 885, 'mapping_proof_refuted': 209, 'refuted_and_simulation_mismatch': 112}
* outcome by tier, R: C_clean 28/53 found, 22 verified; B_narrowed 3/3 found, 3 verified; A_contradicted 10/12 found, 3 verified; A1_simulation_mismatch 4/5 found, 2 verified; A2_z3_refuted_only 6/7 found, 1 verified

**Primary with Tier A removed:** R 16/39 = 0.4103 [0.1579, 0.6750]; B1 21/48 = 0.4375 [0.2203, 0.7297]; R - B1 -0.0272 [-0.4143, 0.3168]; pooled 37/87 = 0.4253 [0.2545, 0.6234] (stratified).

All four kinds, Tier A removed: R found 31/56 = 0.5536, verified 25/56 = 0.4464; B1 found 54/71 = 0.7606, verified 38/71 = 0.5352; pooled_B1_plus_R found 85/127 = 0.6693, verified 63/127 = 0.4961

## E. Mechanics (R)

* records: 10
* valid_records: 10
* records_with_problems: ['ttsky26b__tt_um_tiny_8bit_cpu']
* evaluations: 50
* evaluations_valid: 50
* distinct_answers_per_design: {'tt04__tt_um_jayraj4021_SAP1_cpu': 1, 'ttsky26b__tt_um_tiny_8bit_cpu': 1, 'tt06__tt_um_SJ': 1, 'tt06__tt_um_kwilke_cdc_fifo': 1, 'ttsky25b__tt_um_yorimichi_kittscanner': 1, 'tt05__tt_um_digital_clock_sellicott': 1, 'tt05__tt_um_nickjhay_processor': 1, 'ttsky25b__tt_um_ieeeuoftasic_simproc': 1, 'ttsky26a__tt_um_parakeet': 1, 'ttcad25a__tt_um_space_invaders_game': 1}
* all_one_distinct_answer: True
* unstable_structures_total: 0
* metrics_varying_total: 0
* metrics_defined_range: [56, 92]
* metrics_total_range: [95, 103]
* anonymity_leaks_total: 0
* timeouts_total: 0
* recognizer_failures: 0
* sandbox_blocked_max: 0
* recognizer_wall_s_range: [0.881, 107.928]
* recognizer_peak_rss_mb_range: [118.6, 1453.1]
* record_total_s_range: [3.103, 112.733]
* record_total_s_sum: 404.107
* harness_peak_rss_mb_range: [166.1, 512.8]
* leakage_file_order_arm_run_on_any: False
* permutation_k: [5]
* all_freeze_4: True
* all_attempt_records_match_sha256: True
* no_rerun: True
* truth_hashes_agree_all: True
* per_kind_counts_identical_across_permutations_all: True
* unmapped_or_dropped: {'ttsky26b__tt_um_tiny_8bit_cpu': {'dropped_flops_p1': 72, 'structures_with_dropped_flops': 9, 'truth_unmapped': 72, 'truth_shadow_flops': 4}}

Ledger: 42 lines, hash chain intact True, uncommitted lines 0, git status `clean`, freeze-4 attempts 10 over 10 designs, exactly one per design True, record cross-checks pass True, ledger problems none.

Labelling: drawn 10, reserves used 3, replaced_by {'ttsky26c/tt_um_tpcannon7_fir': 'ttsky26b/tt_um_tiny_8bit_cpu', 'ttsky26b/tt_um_fidel_makatia_digital_tapeout': 'ttcad25a/tt_um_space_invaders_game'}; failures: ttsky26c/tt_um_tpcannon7_fir (RuntimeError: check_truth: ['spi.tx_buf: lanes x depth != flops']); ttsky26b/tt_um_fidel_makatia_digital_tapeout (RuntimeError: check_truth: ['u_soc.u_uart.shift_reg: lanes x depth != flops']); tt08/tt_um_zoom_zoom (ValueError: unexpected gate $print)

## F. References for the pooled set

| kind | pooled regs | pooled found | pooled verified found | holdout_rates items / found / rate | honesty_table regs / found / verified found |
|---|---|---|---|---|---|
| counter | 108 | 72 = 0.6667 | 42 = 0.3889 | 44 / 28 / 0.6364 | 40 / 36 (0.9000) / 26 (0.6500) |
| shift_register | 17 | 5 = 0.2941 | 4 = 0.2353 | 30 / 20 / 0.6667 | 26 / 16 (0.6154) / 16 (0.6154) |
| lfsr_crc | 9 | 0 = 0.0000 | 0 = 0.0000 | 14 / 14 / 1.0000 | 14 / 14 (1.0000) / 14 (1.0000) |
| synchronizer | 28 | 23 = 0.8214 | 23 = 0.8214 | 6 / 6 / 1.0000 | 10 / 8 (0.8000) / 8 (0.8000) |

Caveat: The item sets differ. Every blind figure (B1, R, pooled) counts score.py's strict register denominators. holdout_rates.json counts registers plus declared units (aggregation 'per_register_and_unit', which holdout_rates.py itself calls not comparable with score.py's strict register counts), over 40 synthetic holdout designs and 80 runs; its 'found' is harness-VERIFIED found and it carries no confidence interval. honesty_table.json's corpus_holdout arm uses score.py's own register denominators, which removes the item-set objection, but it is a different seeded run (seed 20260923, libraries ihp and sky130, each design twice). The synthetic corpus was written by the same project as the recognizer. docs/S3.md sections 2 and 6 state the same caveat for the first report.

## Cross-checks (B1 recomputed here against docs/S3.md)

* PASS -- counter 59 registers / 41 found / 23 verified / 28 exact / 15 verified exact / 72 structures / 34 verified structures / 31 FP
* PASS -- shift 8/1/1, lfsr 9/0/0, sync 18/17/17 (registers/found/verified)
* PASS -- all four: 94 registers, 59 found, 41 verified found, 78 structures, 45 matched
* PASS -- tiers A 23 / B 2 / C 69; A1 16 / A2 7
* PASS -- Tier A removed, all kinds: 54/71 found, 38/71 verified
* PASS -- Tier A removed, counter: 21/48 verified, 37/48 found (freeze-1 analysis H4)
* PASS -- flop level: 885 flops, 209 refuted, 112 also mismatching
* PASS -- found-but-unverified 18 = V1 2 + V2 16
* PASS -- misses 35 = 12 matched by a refused kind (10 unscored, 2 scored) + 23 matched by nothing
* PASS -- false positives 33, of which 13 verified
* PASS -- honesty: 409 returned, 40 verified, 215 claimed proven, 6 vacuous hold, n=17 load share
* PASS -- grouping AMI mean 0.8425 / median 0.8310, random-block floor -0.0010, exact words 73/162
* PASS -- params certified 58/60, transcribed 36/38, combined 94/98, informative 29/31, majority 90/98
* PASS -- order counter: width>=3 40 items / 2797 pairs; both bands 41 items / 2798 pairs
* PASS -- bits micro F1 0.6364, macro (docs convention) 0.6292
* PASS -- register micro-F1 found 0.6012 / exact 0.4463; macro-F1 (docs convention) 0.6065 / 0.5404
* PASS -- counter macro recall 0.6383, mean IoU over found 0.9106, found@0.75 35
* PASS -- counter distinct design keys: found_all 27/44, found_any 28/44
* PASS -- strict equals lenient on every B1 kind
* PASS -- Fisher / Clopper-Pearson implementation: 23/59 vs 28/44 p = 0.017, CP 23/59 = [0.265, 0.526]

## Notes

* out/s3/blind/labels.json in the working tree is NOT the committed file: HEAD holds freeze 1's labels (freeze 1ee6a4789435, written 2026-09-23T06:50:45Z); the working tree holds Freeze 4's (freeze 1196c56304e3, written 2026-09-23T16:25:45Z), byte-identical to out/s3/replication/labels.json (True). git status: 'M out/s3/blind/labels.json'. This script did not write it; freeze 1's version survives in git history. The plan says replacements are recorded in out/s3/blind/labels.json.
* R: strict and lenient credit differ on 2 register(s): tt05__tt_um_digital_clock_sellicott shift_register clock_inst.mode0_db_inst.samples (strict found False / verified False; lenient found True / verified True, via unit 'clock_inst.mode0_db_inst.samples + clock_inst.mode1_db_inst.samples (copy_lanes)', structure shift_register#2); tt05__tt_um_digital_clock_sellicott shift_register clock_inst.mode1_db_inst.samples (strict found False / verified False; lenient found True / verified True, via unit 'clock_inst.mode0_db_inst.samples + clock_inst.mode1_db_inst.samples (copy_lanes)', structure shift_register#2)
* B1: strict and lenient credit agree on every scored register
* ['ttsky26b__tt_um_tiny_8bit_cpu'] carry no register of any scored kind in score.py's denominators: they add 0 to every recall denominator and only structures (false positives) to precision; each is still one of R's 10 designs in the bootstrap
* primary: counter registers sit in 9 of R's 10 designs and 10 of B1's 10
* ttsky26b__tt_um_tiny_8bit_cpu record problems (verbatim): ['[p1] 72 result flops were dropped (unmapped, unknown to the truth or not flop ids) from 9 structures; those structures cannot be exact', '[p2] 72 result flops were dropped (unmapped, unknown to the truth or not flop ids) from 9 structures; those structures cannot be exact', '[p3] 72 result flops were dropped (unmapped, unknown to the truth or not flop ids) from 9 structures; those structures cannot be exact', '[p4] 72 result flops were dropped (unmapped, unknown to the truth or not flop ids) from 9 structures; those structures cannot be exact', '[p5] 72 result flops were dropped (unmapped, unknown to the truth or not flop ids) from 9 structures; those structures cannot be exact']
* R verified structures with the largest load_hidden_share: ttcad25a__tt_um_space_invaders_game counter6 (counter, 4 flops) 1.0, credited False; ttsky25b__tt_um_ieeeuoftasic_simproc counter4 (counter, 2 flops) 0.8796, credited False; ttcad25a__tt_um_space_invaders_game counter2 (counter, 6 flops) 0.876, credited True
