# S3 blind evaluation - the LABELS lens

Written 2026-09-23T07:52:04Z. Freeze `1ee6a47894359fef` at git head `75803221bc29`; `freeze check` printed exactly `freeze holds` before and after this analysis. Nothing under `tools/`, no truth and no run record was modified.

This document audits **the ground truth**, because every blind figure rests on it. It quotes `tools/s3/score.py`'s definitions and `docs/S3_DESIGN.md` section 4.4's protocol, and it changes no label.

## 0. Which evaluation each number comes from

| Evidence | Status | What it can say |
|---|---|---|
| TEMPO (`out/s3/eval/runs/`) | **in-sample, fitted** | nothing about generalisation |
| corpus holdout (`out/s3/honesty/holdout_rates.json`, 40 synthetic designs, 80 runs) | **pre-published out-of-sample estimate** | synthetic, written by this project; its aggregation is `per_register_and_unit` |
| the 10 drawn Tiny Tapeout designs | **the first true out-of-sample test** | everything below |
| the Jane Street puzzle | **frozen code, known design** | not blind; pooled with nothing here |

Every blind number below is `score.py`'s **strict register count** (`classes.all` / `classes.verified` -> `registers` -> `strict` -> `per_kind`). `out/s3/honesty/holdout_rates.py` states in terms that `per_register_and_unit` and `score_counts_strict` are **not comparable**, so the holdout rates in section 9 must not be put in the same column as these. Under the holdout's aggregation the blind denominator would be 88 items rather than 94 (18 synchronizer registers minus 16 chain members, plus the 10 declared synchronizer units); the matching outcomes for that aggregation are not derivable from the frozen report and were not computed.

## 1. Findings

1. **Roughly a quarter of the blind ground truth is not established.** Of the 94 scored structure-kind registers, **23 are Tier A**: the labeller's own z3 mapping proof refutes at least one of their bits, or 4096-pattern random simulation contradicts it. 2 more are Tier B (sound but narrowed), 69 are clean. At the flop level, 209 of the 885 netlist flops that carry a structure-kind label have a refuted mapping proof (23.6%), and 112 of those are also contradicted by simulation.

2. **The weak labels drag the headline down, not up.** The recognizer scores 53/69 = 0.768 found on clean-label registers and only 5/23 = 0.217 on Tier A ones. Pooled found is 59/94 = 0.628 with every register in, and 54/71 = 0.761 with the 23 Tier A registers removed from the denominator.

3. **One design carries almost all of the damage.** `tt07/tt_um_toivoh_basilisc_2816` has 157 of its 198 flops refuted and 86 simulation-mismatching, and 16 of its 18 scored structure registers are Tier A (89%). It is also the only design contributing any `lfsr_crc` register, and it contributes 3 of the 8 `shift_register` registers.

4. **The single `shift_register` success in the whole blind set is on a Tier A1 label.** `cpu.pref.sreg` (basilisc) is found and harness-verified; all 16 of its bits are z3-refuted and all 16 mismatch in simulation. On the 5 shift registers whose labels are not contradicted, the recognizer found 0.

5. **`lfsr_crc` has no usable blind evidence.** All 9 `lfsr_crc` registers are basilisc's CPU register-file words and stack pointer (2 RTL module definitions), all Tier A, recall 0/9. Meanwhile the two registers their authors literally named `lfsr`, with XOR feedback recorded in the truth's own `params.serial_in`, are labelled `shift_register` - and the recognizer's harness-verified `lfsr_crc` structures over them are scored as misses in one kind and unmatched structures in the other.

6. **Pooled `synchronizer` recall of 17/18 rests on two unit matches.** 16 of the 18 registers are credited through two `copy_lanes` units, one per design, each matched by a single wide structure. Without that unit rule the same structures match nothing and pooled synchronizer recall falls to 1/18.

7. **The join is clean everywhere.** All 10 designs report `clean: true` with 0 layout cells without an instance name, 0 instances on either side without a partner, 0 master mismatches, 0 nets split or spanning, and 0 ports disagreeing. The labels' weakness is in the RTL-to-netlist *correspondence*, never in the layout-to-netlist *join*.

## 2. What the labeller does and what 'refuted' means

`tools/s3/thirdparty.py` (sha256 `51b6088f775769d0`, unchanged on disk at labelling time). RETRACE extraction of the published layout; join to the published gate-level netlist by GDS property 61; RTL at the recorded commit classified by truth_tempo.py's word-level rules with no manual overrides; register bits mapped to netlist flops by Q-net names through Yosys aliases, confirmed by random simulation (map_netlist) and a z3 equivalence proof (prove_mapping); alt_kinds and units only from rules.

prove_mapping asks z3 whether the netlist flop's D function equals the RTL next-state function of the bit it is mapped to, under the register correspondence. 'refuted' = z3 produced a counterexample: the label's flop set, or the RTL the label was read from, does not match the shipped netlist. 'unchecked' = no RTL bit was mapped to that flop at all.

Labels were fixed before scoring: `labels.json` was written 2026-09-23T06:50:45Z, the first blind run started 2026-09-23T06:53:52+00:00. 10 drawn, 10 labelled, 0 failed, 0 reserves used, no replacement. The blind ledger holds 22 lines (11 attempts x 2 events) and no rerun.

All three copies of every truth hash agree - `labels.json`, the committed run record, and a fresh `schema.truth_hash()` over the file on disk - for all 10 designs. `check_truth()` reports 0 problems on every blind truth.

## 3. Per-design label audit

### 3.1 Proof completeness and the simulation check

| design | flops | labelled | proven | refuted | unchecked | sim match | sim mismatch | outputs | invariants |
|---|--:|--:|--:|--:|--:|--:|--:|---|---|
| `tt09/tt_um_pwm_top` | 47 | 47 | 47 | 0 | 0 | 47 | 0 | proven 8 | - |
| `ttsky26c/tt_um_joonatanalanampa_cordic` | 191 | 191 | 191 | 0 | 0 | 191 | 0 | proven 8 | proven 1 |
| `tt05/tt_um_toivoh_synth` | 264 | 264 | 264 | 0 | 0 | 264 | 0 | not in the netlist 1, proven 8 | - |
| `ttsky25a/tt_um_td4` | 145 | 145 | 145 | 0 | 0 | 145 | 0 | proven 24 | - |
| `tt03p5/tt_um_Reloj_top` | 385 | 385 | 325 | 60 | 0 | 371 | 14 | proven 15 | proven 12 |
| `tt03p5/tt_um_thorkn_vgaclock` | 61 | 61 | 61 | 0 | 0 | 61 | 0 | proven 5 | proven 3 |
| `tt07/tt_um_toivoh_basilisc_2816` | 198 | 198 | 41 | 157 | 0 | 112 | 86 | proven 8 | proven 4 |
| `ttsky25a/tt_um_sjsu_vga_music` | 77 | 70 | 61 | 9 | 7 | 65 | 5 | not in the netlist 1, proven 8 | - |
| `tt07/tt_um_vzayakov_top` | 192 | 192 | 168 | 24 | 0 | 173 | 19 | proven 4, refuted 3 | proven 1, refuted 1 |
| `tt05/tt_um_kskyou` | 148 | 148 | 148 | 0 | 0 | 148 | 0 | proven 8 | proven 1 |

Notes on the five designs the labeller marks `proof_incomplete`:

* `tt05/tt_um_toivoh_synth` - **incomplete on a bookkeeping item only**. All 264 flops proven, 0 simulation mismatches, 8 of 9 outputs proven; the ninth is `uio_out`, recorded as `not in the netlist` (the bus name has no net). Its labels are as strong as the 5 'complete' designs'.
* `ttsky25a/tt_um_sjsu_vga_music` - 9 flops refuted, 5 mismatching, 7 unchecked (those 7 are the unmapped flops, which carry no label), plus the same `uio_out` bookkeeping item.
* `tt03p5/tt_um_Reloj_top` - 60 of 385 refuted, 14 mismatching; all 15 outputs and all 12 invariants proven.
* `tt07/tt_um_vzayakov_top` - 24 of 192 refuted, 19 mismatching, **3 of 7 outputs refuted** (`uo_out[5..7]`) and 1 invariant refuted (`merged DUT.b.BallCol.Q[0]`). The register correspondence is not inductive for this design.
* `tt07/tt_um_toivoh_basilisc_2816` - **157 of 198 refuted, 86 mismatching**, while all 8 outputs and all 4 invariants are proven. Outputs can be proven from corresponding flop states even where the per-flop next-state functions differ, so this is not a contradiction - but the per-flop correspondence, which is what the labels are attached to, largely fails.

`spurious_sat` is 0 and the z3 rlimit per check is 200,000,000 on every design, so no refutation here is a solver artefact and no check was lost to the limit (`unknown` is 0 everywhere).

### 3.2 Join report, anonymisation, universe

| design | join clean | layout refs w/o name | inst. unmatched (either side) | master mismatch | nets split/spanning | ports disagree | net labels stripped | labels kept | unmapped | shadow |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `tt09/tt_um_pwm_top` | true | 0 | 0 | 0 | 0 | 0 | 0 | 51 | 0 | 0 |
| `ttsky26c/tt_um_joonatanalanampa_cordic` | true | 0 | 0 | 0 | 0 | 0 | 0 | 51 | 0 | 0 |
| `tt05/tt_um_toivoh_synth` | true | 0 | 0 | 0 | 0 | 0 | 2078 | 77 | 0 | 0 |
| `ttsky25a/tt_um_td4` | true | 0 | 0 | 0 | 0 | 0 | 0 | 51 | 0 | 0 |
| `tt03p5/tt_um_Reloj_top` | true | 0 | 0 | 0 | 0 | 0 | 2614 | 63 | 0 | 0 |
| `tt03p5/tt_um_thorkn_vgaclock` | true | 0 | 0 | 0 | 0 | 0 | 526 | 50 | 0 | 0 |
| `tt07/tt_um_toivoh_basilisc_2816` | true | 0 | 0 | 0 | 0 | 0 | 0 | 51 | 0 | 0 |
| `ttsky25a/tt_um_sjsu_vga_music` | true | 0 | 0 | 0 | 0 | 0 | 0 | 51 | 7 | 0 |
| `tt07/tt_um_vzayakov_top` | true | 0 | 0 | 0 | 0 | 0 | 0 | 51 | 0 | 0 |
| `tt05/tt_um_kskyou` | true | 0 | 0 | 0 | 0 | 0 | 1053 | 79 | 0 | 0 |

Four layouts (`tt05/tt_um_toivoh_synth`, `tt03p5/tt_um_Reloj_top`, `tt03p5/tt_um_thorkn_vgaclock`, `tt05/tt_um_kskyou`) carried top-level text labels naming internal nets - 2,078 / 2,614 / 526 / 1,053 removed, of which the join counted 265 / 388 / 127 / 148 as RTL-like. The harness stripped them and kept 50-79 labels (the TT pinout). The other six carried none. Every design's anonymised layout is pinned by sha256 in its run record's `inputs`.

Universe facts: **0 shadow flops in all 10 designs**, so no register loses bits to the shadow rule anywhere. 7 unmapped flops in one design (`ttsky25a/tt_um_sjsu_vga_music`, reason 'no RTL name on the Q net'); the scorer dropped exactly those 7 result flops, and the 4 structures built from them are of unscored kinds (3 `flag`, 1 `data_register`), so no scored-kind figure moved. Three designs hold one register each with no scored flop: `u_cordic.mode_q` (flag, constant in RTL), `cpu.fifo.entries[0]` (flag, constant in RTL), `DUT.doneff.Q` (flag, next state constant) - all non-structure kinds, so no structure denominator is affected. `tt03p5/tt_um_thorkn_vgaclock`'s `meta.registers_without_primary_flop` lists its three `__retimed` registers, which are kind `other` by the truth/2 rule and never enter a structure denominator.

### 3.3 Units admitted by rule

Two designs declare units; the other eight declare none. All 10 units are of kind `synchronizer`, and all 10 are chain units under `score.Truth` (a synchronizer unit all of whose members are synchronizer registers), so the 16 member registers are scored **only through them** in strict mode.

| design | unit kind | admitted by rule | member registers | flops | chain unit |
|---|---|---|--:|--:|---|
| `tt03p5/tt_um_Reloj_top` | synchronizer | `sync_chain` | 2 | 2 | yes |
| `tt03p5/tt_um_Reloj_top` | synchronizer | `sync_chain` | 2 | 2 | yes |
| `tt03p5/tt_um_Reloj_top` | synchronizer | `sync_chain` | 2 | 2 | yes |
| `tt03p5/tt_um_Reloj_top` | synchronizer | `copy_lanes` | 6 | 6 | yes |
| `tt07/tt_um_vzayakov_top` | synchronizer | `sync_chain` | 2 | 2 | yes |
| `tt07/tt_um_vzayakov_top` | synchronizer | `sync_chain` | 2 | 2 | yes |
| `tt07/tt_um_vzayakov_top` | synchronizer | `sync_chain` | 2 | 2 | yes |
| `tt07/tt_um_vzayakov_top` | synchronizer | `sync_chain` | 2 | 2 | yes |
| `tt07/tt_um_vzayakov_top` | synchronizer | `sync_chain` | 2 | 2 | yes |
| `tt07/tt_um_vzayakov_top` | synchronizer | `copy_lanes` | 10 | 10 | yes |

No `shift_register`, `counter` or `lfsr_crc` unit was admitted anywhere in the blind set, and no unit was rejected as malformed (`bad_units` empty in all 10).

### 3.4 Scored registers per kind, per design

The denominator is `score.Truth.denominators(c)`: registers of kind `c` with at least one flop in the universe. It is the same in strict and lenient mode.

| design | shift | counter | lfsr_crc | sync | total | distinct design_keys | Tier A | Tier B |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| `tt09/tt_um_pwm_top` | 0 | 4 | 0 | 0 | 4 | 4 | 0 | 0 |
| `ttsky26c/tt_um_joonatanalanampa_cordic` | 3 | 3 | 0 | 0 | 6 | 6 | 0 | 0 |
| `tt05/tt_um_toivoh_synth` | 1 | 5 | 0 | 1 | 7 | 6 | 0 | 1 |
| `ttsky25a/tt_um_td4` | 0 | 1 | 0 | 0 | 1 | 1 | 0 | 0 |
| `tt03p5/tt_um_Reloj_top` | 0 | 14 | 0 | 6 | 20 | 14 | 4 | 0 |
| `tt03p5/tt_um_thorkn_vgaclock` | 0 | 6 | 0 | 0 | 6 | 6 | 0 | 0 |
| `tt07/tt_um_toivoh_basilisc_2816` | 3 | 5 | 9 | 1 | 18 | 10 | 16 | 1 |
| `ttsky25a/tt_um_sjsu_vga_music` | 1 | 6 | 0 | 0 | 7 | 7 | 1 | 0 |
| `tt07/tt_um_vzayakov_top` | 0 | 12 | 0 | 10 | 22 | 3 | 2 | 0 |
| `tt05/tt_um_kskyou` | 0 | 3 | 0 | 0 | 3 | 3 | 0 | 0 |
| **pooled** | **8** | **59** | **9** | **18** | **94** | **60** | **23** | **2** |

`score.SMALL_SUPPORT` is 3, so a kind with fewer than 3 registers in a design is flagged. Flagged per design: `tt05/tt_um_toivoh_synth` shift (1) and synchronizer (1); `ttsky25a/tt_um_td4` counter (1); `tt07/tt_um_toivoh_basilisc_2816` synchronizer (1); `ttsky25a/tt_um_sjsu_vga_music` shift (1).

**Instance counts overstate the independent evidence.** Pooled per distinct RTL `design_key` (`score.py`'s own `distinct_designs` counts): counter 27 of 44 found in every instance, shift_register 1 of 8, lfsr_crc 0 of 2, synchronizer 5 of 6 - 33/60 = 0.550 against 59/94 = 0.628 per instance. The gap is concentrated: `tt07/tt_um_vzayakov_top`'s 12 counters are 12 instances of a single 4-bit `Counter:Q` module, all found; its 10 synchronizers are 10 instances of 2 module definitions.

## 4. Label quality: the tiers

* **Tier A (contradicted)** - a scored structure-kind register with at least one mapped bit whose z3 mapping proof is not 'proven' or whose random-simulation check is not 'match'. Split into A1 (at least one simulation mismatch) and A2 (z3 refuted while 4096-pattern random simulation agreed).
* **Tier B (narrowed)** - every mapped bit proven and matching, but the RTL register has at least one bit with no netlist flop, so the labelled flop set is a strict subset of the RTL register.
* **Tier C (clean)** - every bit of the register mapped, proven and matching.

| tier | registers | found | found rate | verified-found | verified-found rate |
|---|--:|--:|--:|--:|--:|
| C_clean | 69 | 53 | 0.768 | 37 | 0.536 |
| B_narrowed | 2 | 1 | 0.500 | 1 | 0.500 |
| A_contradicted | 23 | 5 | 0.217 | 3 | 0.130 |
| A1_simulation_mismatch | 16 | 5 | 0.312 | 3 | 0.188 |
| A2_z3_refuted_only | 7 | 0 | 0.000 | 0 | 0.000 |

The 2 Tier B registers are `oct_counter` (`tt05/tt_um_toivoh_synth`, 1 of 17 RTL bits has no flop, 'unused (removed)'; found) and `ui_in_reg` (basilisc, 6 of 8 RTL bits are not flops in the word-level RTL; missed).

### 4.1 Which designs carry weak labels

| design | scored structure regs | Tier A | Tier A share | refuted flops (design-wide) | sim mismatches |
|---|--:|--:|--:|--:|--:|
| `tt07/tt_um_toivoh_basilisc_2816` | 18 | 16 | 0.89 | 157 | 86 |
| `tt03p5/tt_um_Reloj_top` | 20 | 4 | 0.20 | 60 | 14 |
| `ttsky25a/tt_um_sjsu_vga_music` | 7 | 1 | 0.14 | 9 | 5 |
| `tt07/tt_um_vzayakov_top` | 22 | 2 | 0.09 | 24 | 19 |
| `tt09/tt_um_pwm_top` | 4 | 0 | 0.00 | 0 | 0 |
| `ttsky26c/tt_um_joonatanalanampa_cordic` | 6 | 0 | 0.00 | 0 | 0 |
| `tt05/tt_um_toivoh_synth` | 7 | 0 | 0.00 | 0 | 0 |
| `ttsky25a/tt_um_td4` | 1 | 0 | 0.00 | 0 | 0 |
| `tt03p5/tt_um_thorkn_vgaclock` | 6 | 0 | 0.00 | 0 | 0 |
| `tt05/tt_um_kskyou` | 3 | 0 | 0.00 | 0 | 0 |

Four designs contribute Tier A registers; six contribute none. On the stated rule - **a design more than half of whose scored structure registers are Tier A** - exactly one design qualifies as weakest-labelled: `tt07/tt_um_toivoh_basilisc_2816` (16 of 18).

### 4.2 Every Tier A register

| kind | design | register | subtier | bits | unproven | mismatching | found | verified-found |
|---|---|---|---|--:|--:|--:|---|---|
| counter | `tt_um_Reloj_top` | `doubledabble.shift` | A1 | 32 | 1 | 1 | no | no |
| counter | `tt_um_Reloj_top` | `hourmod.hour` | A2 | 28 | 13 | 0 | no | no |
| counter | `tt_um_Reloj_top` | `minites.min` | A2 | 30 | 10 | 0 | no | no |
| counter | `tt_um_Reloj_top` | `segmod.seg` | A1 | 30 | 30 | 13 | yes | yes |
| counter | `tt_um_toivoh_basilisc_2816` | `cpu.dec.sched.alu.state` | A1 | 3 | 3 | 3 | yes | no |
| counter | `tt_um_toivoh_basilisc_2816` | `cpu.dec.sched.stage` | A1 | 2 | 2 | 2 | no | no |
| counter | `tt_um_toivoh_basilisc_2816` | `cpu.mem_if.tx_monitor.counter` | A2 | 4 | 1 | 0 | no | no |
| counter | `tt_um_toivoh_basilisc_2816` | `cpu.pref.num_flushed` | A2 | 2 | 2 | 0 | no | no |
| counter | `tt_um_vzayakov_top` | `DUT.vg.ColCounter.Q` | A1 | 10 | 10 | 10 | yes | yes |
| counter | `tt_um_vzayakov_top` | `DUT.vg.RowCounter.Q` | A1 | 9 | 9 | 9 | yes | no |
| counter | `tt_um_sjsu_vga_music` | `note_counter` | A1 | 8 | 8 | 4 | no | no |
| lfsr_crc | `tt_um_toivoh_basilisc_2816` | `cpu.dec.sched.alu.registers.general_registers.regs[0]` | A1 | 8 | 8 | 8 | no | no |
| lfsr_crc | `tt_um_toivoh_basilisc_2816` | `cpu.dec.sched.alu.registers.general_registers.regs[1]` | A1 | 8 | 8 | 8 | no | no |
| lfsr_crc | `tt_um_toivoh_basilisc_2816` | `cpu.dec.sched.alu.registers.general_registers.regs[2]` | A1 | 8 | 8 | 7 | no | no |
| lfsr_crc | `tt_um_toivoh_basilisc_2816` | `cpu.dec.sched.alu.registers.general_registers.regs[3]` | A1 | 8 | 8 | 4 | no | no |
| lfsr_crc | `tt_um_toivoh_basilisc_2816` | `cpu.dec.sched.alu.registers.general_registers.regs[4]` | A1 | 8 | 8 | 5 | no | no |
| lfsr_crc | `tt_um_toivoh_basilisc_2816` | `cpu.dec.sched.alu.registers.general_registers.regs[5]` | A1 | 8 | 8 | 4 | no | no |
| lfsr_crc | `tt_um_toivoh_basilisc_2816` | `cpu.dec.sched.alu.registers.general_registers.regs[6]` | A2 | 8 | 8 | 0 | no | no |
| lfsr_crc | `tt_um_toivoh_basilisc_2816` | `cpu.dec.sched.alu.registers.general_registers.regs[7]` | A1 | 8 | 8 | 2 | no | no |
| lfsr_crc | `tt_um_toivoh_basilisc_2816` | `cpu.dec.sched.alu.registers.sp_register.regs` | A2 | 8 | 8 | 0 | no | no |
| shift_register | `tt_um_toivoh_basilisc_2816` | `cpu.pref.imm_reg` | A1 | 16 | 16 | 16 | no | no |
| shift_register | `tt_um_toivoh_basilisc_2816` | `cpu.pref.pc` | A2 | 16 | 16 | 0 | no | no |
| shift_register | `tt_um_toivoh_basilisc_2816` | `cpu.pref.sreg` | A1 | 16 | 16 | 16 | yes | yes |

Three of the 41 pooled verified-found registers are Tier A1: `segmod.seg` (Reloj), `DUT.vg.ColCounter.Q` (vzayakov) and `cpu.pref.sreg` (basilisc). A harness verdict proves a template about the netlist, not the truth's label, so these remain proved structural claims matched against truth items that are not established.

## 5. How much of the pooled figure depends on the weak labels

**H1 - all 10 blind designs (the headline)** (10 designs)

| kind | registers | found | exact | verified-found |
|---|--:|---|---|---|
| shift_register | 8 | 1/8 = 0.125 | 1/8 = 0.125 | 1/8 = 0.125 |
| counter | 59 | 41/59 = 0.695 | 28/59 = 0.475 | 23/59 = 0.390 |
| lfsr_crc | 9 | 0/9 = 0.000 | 0/9 = 0.000 | 0/9 = 0.000 |
| synchronizer | 18 | 17/18 = 0.944 | 17/18 = 0.944 | 17/18 = 0.944 |
| **pooled** | **94** | **59/94 = 0.628** | **46/94 = 0.489** | **41/94 = 0.436** |

**H2 - excluding the weakest-labelled design** (9 designs)

Excluded: `tt07/tt_um_toivoh_basilisc_2816`.

Rule: a design > 50% of whose scored structure-kind registers are Tier A (mapping contradicted)

| kind | registers | found | exact | verified-found |
|---|--:|---|---|---|
| shift_register | 5 | 0/5 = 0.000 | 0/5 = 0.000 | 0/5 = 0.000 |
| counter | 54 | 39/54 = 0.722 | 28/54 = 0.519 | 23/54 = 0.426 |
| lfsr_crc | 0 | 0/0 (no registers of this kind) | 0/0 (no registers of this kind) | 0/0 (no registers of this kind) |
| synchronizer | 17 | 17/17 = 1.000 | 17/17 = 1.000 | 17/17 = 1.000 |
| **pooled** | **76** | **56/76 = 0.737** | **45/76 = 0.592** | **40/76 = 0.526** |

**H3 - excluding every design with any Tier A register** (6 designs)

Excluded: `tt03p5/tt_um_Reloj_top`, `tt07/tt_um_toivoh_basilisc_2816`, `ttsky25a/tt_um_sjsu_vga_music`, `tt07/tt_um_vzayakov_top`.

| kind | registers | found | exact | verified-found |
|---|--:|---|---|---|
| shift_register | 4 | 0/4 = 0.000 | 0/4 = 0.000 | 0/4 = 0.000 |
| counter | 22 | 15/22 = 0.682 | 14/22 = 0.636 | 12/22 = 0.545 |
| lfsr_crc | 0 | 0/0 (no registers of this kind) | 0/0 (no registers of this kind) | 0/0 (no registers of this kind) |
| synchronizer | 1 | 1/1 = 1.000 | 1/1 = 1.000 | 1/1 = 1.000 |
| **pooled** | **27** | **16/27 = 0.593** | **15/27 = 0.556** | **13/27 = 0.481** |

**H4 - all 10 designs, Tier A registers removed from the denominator** (10 designs)

Rule: every design kept; the 23 Tier A registers removed from their kind's denominator. exact is NOT available per register from the frozen report, so only found and verified-found are given.

| kind | registers | found | exact | verified-found |
|---|--:|---|---|---|
| shift_register | 5 | 0/5 = 0.000 | n/a | 0/5 = 0.000 |
| counter | 48 | 37/48 = 0.771 | n/a | 21/48 = 0.438 |
| lfsr_crc | 0 | 0/0 (no registers of this kind) | n/a | 0/0 (no registers of this kind) |
| synchronizer | 18 | 17/18 = 0.944 | n/a | 17/18 = 0.944 |
| **pooled** | **71** | **54/71 = 0.761** | **n/a** | **38/71 = 0.535** |

**H5 - the Tier A registers alone** (4 designs)

| kind | registers | found | exact | verified-found |
|---|--:|---|---|---|
| shift_register | 3 | 1/3 = 0.333 | n/a | 1/3 = 0.333 |
| counter | 11 | 4/11 = 0.364 | n/a | 2/11 = 0.182 |
| lfsr_crc | 9 | 0/9 = 0.000 | n/a | 0/9 = 0.000 |
| synchronizer | 0 | 0/0 (no registers of this kind) | n/a | 0/0 (no registers of this kind) |
| **pooled** | **23** | **5/23 = 0.217** | **n/a** | **3/23 = 0.130** |

**Read H1 and H2 together, and prefer H4 for the label question.** H2 answers 'what if the weakest-labelled design had not been drawn' and moves pooled found from 59/94 = 0.628 to 56/76 = 0.737 - but it also deletes the `lfsr_crc` kind entirely and removes 3 of the 8 shift registers, so the two figures are over different kind mixes. H4 keeps every design and removes only the 23 registers whose labels are contradicted: pooled found 54/71 = 0.761, verified-found 38/71 = 0.535. H3 leaves 27 registers (4 shift, 22 counter, 0 lfsr_crc, 1 synchronizer) - too few for anything but the counter figure.

The direction matters: the weak labels **suppress** the headline. The recognizer finds 5/23 of the contradicted registers and 53/69 of the clean ones. The one exception is `shift_register`, whose single success is itself a Tier A register.

## 6. Truth judgement calls that swing a number

### J1. Two Fibonacci LFSRs are labelled shift_register, with no alt_kinds.

*Swings:* shift_register recall, lfsr_crc precision, the pooled headline.

*Evidence:* out/s3/truth_tt05__tt_um_toivoh_synth.json register `lfsr` (width 15, kind shift_register, rule 'D[k] = Q[k-1] on 14 of 14 shiftable bits', params.serial_in ['(lfsr[0] ^ lfsr[14])']) and out/s3/truth_ttsky25a__tt_um_sjsu_vga_music.json register `lfsr` (width 13, kind shift_register, params.serial_in ['feedback']). The recognizer emitted a 15-flop and a 13-flop structure of kind lfsr_crc over exactly those registers; both carry harness outcome 'verified'; both appear in the strict confusion matrix as 'shift_register->lfsr_crc': 1.

*As scored:* each is a shift_register miss and an lfsr_crc structure that matched no item: pooled lfsr_crc precision 0/2.

*Counterfactual (the two `lfsr` registers labelled lfsr_crc instead):* pooled found 61/94 = 0.649, verified-found 43/94 = 0.457, precision 0.603 (headline: 59/94 = 0.628, 41/94 = 0.436, 0.577). Per kind: shift_register found 1/6 = 0.167; counter found 41/59 = 0.695; lfsr_crc found 2/11 = 0.182; synchronizer found 17/18 = 0.944. Both structures are harness-verified, so found and verified-found move together. The truth was NOT changed; this is arithmetic on the frozen report.

### J2. Nine 8-bit CPU register-file words are labelled lfsr_crc.

*Swings:* the whole lfsr_crc recall denominator.

*Evidence:* out/s3/truth_tt07__tt_um_toivoh_basilisc_2816.json: cpu.dec.sched.alu.registers.general_registers.regs[0..7] (design_key regfile:regs) and cpu.dec.sched.alu.registers.sp_register.regs (regfile_single:regs), all kind lfsr_crc, rule 'own Q bits of other indices reach D through XOR (GF(2) feedback)', every PARAMS field (form, poly, k_steps, n_inputs, bit_order) null.

*As scored:* these 9 registers ARE the blind set's lfsr_crc denominator (9 of 9), over 2 distinct design_keys in 1 design; recall 0/9. Every one is Tier A: all 8 bits of each have a refuted mapping proof.

*Counterfactual:* remove the design and the blind set has 0 lfsr_crc registers: the kind has no blind evidence at all, in either direction.

### J3. The `copy_lanes` unit rule creates one wide synchronizer unit per design over lanes that are also covered by 2-flop `sync_chain` units.

*Swings:* pooled synchronizer recall, and the pooled headline by 16 points.

*Evidence:* truth units of tt03p5/tt_um_Reloj_top (3 sync_chain units of 2 flops + 1 copy_lanes unit of 6 flops) and tt07/tt_um_vzayakov_top (5 sync_chain + 1 copy_lanes of 10 flops). 16 of the 18 synchronizer registers are chain members, so in STRICT mode they are scored only through chain units. The recognizer emitted exactly one synchronizer structure per design (6 and 10 flops); each matched its copy_lanes unit at IoU 1.0 (score report per_kind.synchronizer.via_units names it).

*As scored:* 2 structures credit 16 registers. Against the 2-flop sync_chain units alone those structures have IoU 2/6 = 0.33 and 2/10 = 0.20, both below score.py's 0.5 threshold, so without the copy_lanes rule all 16 would be missed.

*Counterfactual (no copy_lanes units (sync_chain units only)):* pooled found 43/94 = 0.457, verified-found 25/94 = 0.266, precision 0.551 (headline: 59/94 = 0.628, 41/94 = 0.436, 0.577). Per kind: shift_register found 1/8 = 0.125; counter found 41/59 = 0.695; lfsr_crc found 0/9 = 0.000; synchronizer found 1/18 = 0.056. The 2 wide structures would match nothing, so they also leave the synchronizer precision numerator.

### J4. The only shift_register the recognizer found, tt07/tt_um_toivoh_basilisc_2816 cpu.pref.sreg, is a Tier A1 label: all 16 of its bits are refuted by z3 AND contradicted by random simulation.

*Swings:* the one shift_register success in the blind set.

*Evidence:* truth register cpu.pref.sreg, bits[] all check=mismatch, proof=refuted; score report shift_register found_registers = ['cpu.pref.sreg'].

*As scored:* pooled shift_register found = 1/8 = 0.125. On the 5 shift registers whose labels are NOT contradicted, the recognizer found 0.

*Counterfactual:* dropping Tier A registers leaves shift_register at 0/5.

### J5. Three Reloj counters are 32 bits in RTL but fewer in the netlist, and `exact` is against the netlist flop set.

*Swings:* exact recall on tt03p5/tt_um_Reloj_top.

*Evidence:* hourmod.hour 28 of 32 bits have a flop, minites.min 30 of 32, segmod.seg 30 of 32 ('no flop found'); meta.counts.rtl_bits records 8 'no flop found' and 9 'next state constant (removed by synthesis)'.

*As scored:* Reloj counter found 7/14, exact 0/14 -- it contributes 7 of the pooled 41 found counters and 0 of the pooled 28 exact ones.

### J6. ui_in_reg is labelled synchronizer with params.stages = 1 and is 8 bits wide in RTL, of which only 2 are flops (6 bits 'not a flop in the word-level RTL').

*Swings:* the basilisc synchronizer item.

*Evidence:* truth register ui_in_reg, kind synchronizer, rule 'no enable; D is an input pin (stage 1) or a stage-1 flop (stage 2)', params {'stages': 1}.

*As scored:* 1 of the 18 synchronizer denominators is a 2-flop, 1-stage item; it is the one synchronizer the recognizer missed. Tier B (narrowed), not contradicted.

### J7. 7 of ttsky25a/tt_um_sjsu_vga_music's 77 netlist flops have no RTL name on their Q net and sit in truth.unmapped_flops, outside the scored universe.

*Swings:* nothing in the headline, but it is a label-coverage gap.

*Evidence:* truth.unmapped_flops (reason 'no RTL name on the Q net'); the score report's result.dropped_flops = 7 and result.structures_without_labelled_flops = 4.

*As scored:* the 4 result structures built from them are of UNSCORED kinds (3 flag, 1 data_register), so no scored-kind precision, found or exact figure moved. The gap is real but cost nothing here.

### J8. vzayakov's register correspondence is not inductive: 3 of its 7 outputs and 1 invariant are refuted, and only 22 of 192 bits were mapped by name.

*Swings:* confidence in tt07/tt_um_vzayakov_top's 22 scored registers.

*Evidence:* meta.proof.outputs {'proven': 4, 'refuted': 3} (uo_out[5], uo_out[6], uo_out[7]) and invariants_not_proven ['merged DUT.b.BallCol.Q[0]']; bits[].how = 114 alias, 56 retimed, 22 name, 1 merged; 8 '__retimed' registers of kind other absorb 56 flops.

*As scored:* vzayakov contributes 22 of the 94 scored registers (12 counters over ONE design_key and 10 synchronizers over 2) and 22 of the 59 found. Only 2 of its 22 are Tier A, so the tier rule does not flag it, but the design-level proof is the weakest kind of pass.

### J9. The strict/lenient distinction carries no information on this blind set.

*Swings:* nothing -- recorded so no reader assumes otherwise.

*Evidence:* only 4 blind registers carry alt_kinds at all (flag with a counter alternative, the 1-bit toggle rule: 1 in tt09/tt_um_pwm_top, 1 in tt03p5/tt_um_Reloj_top, 2 in ttsky25a/tt_um_sjsu_vga_music); none is of a structure kind, so score.Truth.excused is 0 for every kind in every design, and the lenient per-kind register counts and found counts equal the strict ones for all 4 kinds in all 10 designs.


## 7. What the blind set is, and is not, representative of

* 10 third-party Tiny Tapeout projects on sky130, drawn with the freeze's 128-bit seed from a candidate list of 84 registered before recognizer development, by criteria C1-C7 that look at no design's structure beyond size. 0 reserves were used and no design was replaced.
* Real, taped-out, third-party RTL and real OpenLane/LibreLane layouts and gate-level netlists, not synthetic cases: the first evidence in this study that is neither fitted (TEMPO), nor written by this project (the corpus), nor known to the team (the puzzle).
* Small designs: 47 to 385 netlist flops, median 169.5, 1,708 flops in total; 9 of 10 occupy one TT tile.
* 94 scored structure-kind registers over 60 distinct RTL design_keys.

It is **not** representative of:

* **the 14 sky130 shuttles** - the candidate list stratifies 6 designs per shuttle over 14 sky130 shuttles, but the draw of 10 covers only 6 of them (tt03p5 x2, tt05 x2, tt07 x2, ttsky25a x2, tt09 x1, ttsky26c x1). tt02, tt04, tt06, tt08, ttcad25a, ttsky25b, ttsky26a and ttsky26b contribute nothing. The draw rule is the n lowest sha256(seed|id), not a stratified draw, so this is expected, not a fault -- but no per-shuttle or per-era claim can rest on it.
* **Tiny Tapeout as a whole** - the index holds 3,411 entries / 2,654 distinct designs; 387 were checked before the per-stratum quota of 6 was met, and 288 of those were rejected (C1 104, C4 162, C5 21, C6 1). C4 alone (all cells sky130_fd_sc_hd and >= 40 flops) rejected 162. The 84-design pool is what survives C1-C7, not a sample of TT.
* **larger designs** - the candidate pool holds 55 1x1, 18 1x2, 6 2x2, 1 3x2 and 4 4x2 designs and runs to 1,656 flops; the drawn 10 are 9 x 1x1 and 1 x 1x2, the largest 385 flops. Nothing here speaks to designs above ~400 flops.
* **author styles** - 9 distinct authors over 10 designs: Toivo Henningsson wrote 2 of the 10 (tt05/tt_um_toivoh_synth and tt07/tt_um_toivoh_basilisc_2816), which are 25 of the 94 scored registers and include all 9 lfsr_crc registers and 4 of the 8 shift registers. 9 of 10 are Verilog, 1 SystemVerilog; every one carries an Apache-2.0 author repo.
* **hand-instantiated sequential logic** - C5 excludes any design whose sources instantiate a sky130 flip-flop or latch cell, and every drawn design has 0 latches and 0 opaque sequential cells. Nothing here speaks to latch-based or hand-placed sequential designs.
* **LFSRs and CRCs** - all 9 lfsr_crc registers in the blind set come from ONE design and 2 RTL module definitions (regfile x8, regfile_single x1), and all 9 are Tier A. Meanwhile the two registers their authors named `lfsr` are labelled shift_register. The blind set supports NO claim about LFSR/CRC recognition in either direction.

## 8. Figures too small to support a claim

* **`lfsr_crc`**: 9 registers, all from one design, 2 RTL module definitions, all Tier A. Recall 0/9 and precision 0/2 are counts, not rates, and the two structures in the precision denominator are the two real LFSRs of judgement call J1. **No blind claim about LFSR/CRC recognition is supportable in either direction.**
* **`shift_register`**: 8 registers in 4 designs. 1 found, and that one is Tier A1. Report as 1/8, never as 12.5%.
* **`synchronizer`**: 18 registers, but 16 are credited by 2 structure matches against 2 `copy_lanes` units in 2 designs. 17/18 is 3 successes, not 17.
* **H3** (27 registers over 6 designs) supports at most the counter figure (15/22); its shift (0/4) and synchronizer (1/1) cells are too small to read.
* **Per-design rates** for any kind with fewer than 3 registers are flagged by `score.SMALL_SUPPORT` and are listed in section 3.4; none of them should be quoted as a rate.

## 9. The pre-published out-of-sample estimate, for context only

`out/s3/honesty/holdout_rates.json`, aggregation `per_register_and_unit`, 40 synthetic holdout designs, 80 runs. Its `found` already means harness-VERIFIED.

| kind | items | found | exact |
|---|--:|---|---|
| shift_register | 30 | 20/30 = 0.6667 | 18/30 = 0.6 |
| counter | 44 | 28/44 = 0.6364 | 28/44 = 0.6364 |
| lfsr_crc | 14 | 14/14 = 1.0 | 14/14 = 1.0 |
| synchronizer | 6 | 6/6 = 1.0 | 4/6 = 0.6667 |

**holdout_rates.py's own header: per_register_and_unit and score_counts_strict are NOT comparable. The blind figures in this document are score.py's strict register counts, so they must not be placed in the same column as these rates without saying so.** The corpus is also synthetic and written by this project, and both generalisation regression sets are no longer held out (contamination record, quoted in every score report's provenance block). These rows are here so a reader knows what the prior estimate said, not to be differenced against section 5.

## 10. The puzzle, kept separate

**FROZEN CODE, KNOWN DESIGN -- not blind, not pooled with the blind set.** out/s3/truth_puzzle.json, written by tools/s3/truth_puzzle.py (a different artifact from the blind labeller: hand-derived checks, no z3 register-correspondence proof and no random-simulation flop check of the kind the blind truths carry).

Scale: 35 registers, 92 flops, 3 units; scored structure registers counter 27, shift_register 1, lfsr_crc 1, synchronizer 0; no chain units, no excused registers, no register without a scored flop.

Label provenance: meta.checks records 'pass' on N1-N3 (RTL tagging, port binding, the 92 flops partitioned), X1-X2 (fresh extraction and per-pin net agreement) and the per-structure checks; meta.source_discrepancies and meta.source_corrections record two corrections made on 2026-09-21 to the project's own recovered RTL and INTENT notes.

The design has been read by the team all along (contamination.json), so its numbers say what frozen code does on a known design, never what it does out of sample. Its truth is **not** produced by the frozen design-agnostic labeller, so the Tier A/B/C audit above does not apply to it and its numbers are pooled with nothing here.

## 11. Caveats

* Every blind figure here is score.py's STRICT REGISTER count (classes.all/verified -> registers -> strict -> per_kind). The published corpus-holdout rates use the per_register_and_unit aggregation, and out/s3/honesty/holdout_rates.py states the two are NOT comparable. Under per_register_and_unit the blind denominator would be 88 items, not 94 (18 synchronizer registers minus 16 chain members, plus the 10 declared synchronizer units); the outcome counts for that aggregation are not derivable from the frozen report and were NOT computed.
* 'Tier A' means the labeller's own mapping proof or its random simulation contradicts the register's bit-to-flop mapping. It does NOT prove the kind is wrong: a refutation can equally mean the shipped netlist was built from other RTL than the recorded commit. Either way the label is not established, which is what the tiers measure.
* A harness-VERIFIED structure over a Tier A register is still a proved statement about the netlist: verify.py proves a template, not the truth's label. What Tier A puts in doubt is the truth item the structure was matched against, not the structure.
* The 10 blind truths are NOT pinned by out/s3/FREEZE.json, which carries truth_hash only for TEMPO and the puzzle. They are pinned by out/s3/blind/labels.json (written 2026-09-23T06:50:45Z, before the first run at 06:53:52Z) and by each committed run record's truth.truth_hash. All 30 hashes (labels.json, run record, recomputed from disk with schema.truth_hash) agree. labels.json and the truth files themselves are in the git-ignored out/ tree and are not force-added into the freeze commit, so only the committed run records prove what was scored.
* The labeller's RULES were exercised on 15 third-party designs on the truth side before the blind draw (contamination.json K11). None of those 15 is in the 84-candidate pool and no recognizer code ran on them, but the label rules are not naive with respect to third-party RTL.
* Per-kind blind rates for shift_register (8 registers), lfsr_crc (9, all from one design) and synchronizer (18, of which 16 are credited through 2 unit matches) are too small, or too concentrated, to support a rate claim. They are reported as counts with their denominators and should be read that way.
* All 5 permutations of every blind run produced identical per-kind register counts, so nothing here depends on which permutation is quoted.
* The puzzle is frozen-code-but-known and its truth is written by tools/s3/truth_puzzle.py, not by the design-agnostic labeller. It is described separately and is pooled with nothing.

## 12. Sources

* tools/s3/score.py (frozen) -- module docstring: universe, matching, strict/lenient, excused, SMALL_SUPPORT, found/exact/verified, provenance
* docs/S3_DESIGN.md sections 4.1-4.4 (frozen) -- truth, join, units, the evaluation protocol
* tools/s3/thirdparty.py (frozen) -- criteria C1-C7, the draw, the join through GDS property 61
* tools/s3/truth_tempo.py (frozen) -- prove_mapping, proof_complete, the word-level label rules
* out/s3/blind/labels.json and labels.log -- the labelling summary and per-design log
* out/s3/truth_<design>.json x 10 -- the blind truths (read only)
* out/s3/runs/blind-<design>-<utc>-<id>.json x 10 -- the frozen run records (evaluation p1 quoted; all 5 permutations agree)
* out/s3/honesty/holdout_rates.json -- the pre-published out-of-sample estimate and its aggregation
* out/s3/contamination.json -- K11 (labeller exercised on 15 third-party designs), the puzzle items
* out/s3/blind/candidates.json and scan.json -- the registered candidate pool and the scan funnel
* out/s3/blind_ledger.jsonl -- 22 lines = 11 attempts x 2 events, no rerun

