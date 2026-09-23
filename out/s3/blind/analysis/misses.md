# S3 blind evaluation — the misses lens

*Every miss and every false positive of the frozen S3 run, with its cause. Generated 2026-09-23T07:55:22+00:00 from the frozen run records under `out/s3/runs/`, the frozen truths `out/s3/truth_*.json` and the frozen sources read as data. Freeze `232cfe67545a`; `tools/s3/freeze check` printed **freeze holds** before and after. Machine-readable twin: `out/s3/blind/analysis/misses.json`.*

## 0. What each number is, and is not

| Evaluation | Status | Used here for |
|---|---|---|
| **blind set** — the 10 drawn third-party Tiny Tapeout designs | the **first true out-of-sample test** of this recognizer | every miss, every false positive, every rate below unless marked |
| **the Jane Street puzzle** | **frozen code on a design the team already knows** — not blind | a contrast, never quoted as out-of-sample |
| **TEMPO** | the development design — **in-sample and fitted** | a contrast, never quoted as out-of-sample |
| **corpus holdout** (`out/s3/honesty/holdout_rates.json`) | the **pre-published out-of-sample estimate**, on a *synthetic* corpus this project wrote | quoted with its own aggregation, never subtracted from a blind figure |

Two mechanics of `tools/s3/score.py` are load-bearing throughout and are quoted, not paraphrased:
a structure and a truth item **match** when `IoU > 0.5` and (for an item of ≥ 2 flops) they share ≥ 2 flops, one to one and kind-agnostic; a register is **found** when it is matched *and* the structure's kind is one the item accepts; it is **verified** only when that structure carries a `tools/s3/verify.py` verdict of verified (*"a result's own 'proven' status is a claim and counts for nothing"*).

**Strict equals lenient on the whole blind set.** strict and lenient give IDENTICAL results on the blind set: no blind truth register of a scored kind carries alt_kinds, there are no excused registers, and the only declared units are synchronizer chain units, which are items in both modes. The reason is structural: tools/s3/thirdparty.py takes alt_kinds only from the design-agnostic rules (in practice the 1-bit toggle rule), never from truth_tempo.ALT_KINDS, whose 5 entries are TEMPO register-name regexes. TEMPO's label ambiguities (shift vs data_register, a third synchronizer stage, the PC) were resolved with hand-written per-register alternatives that no blind design can get.

**Permutation-invariant.** every design's K = 5 permutations gave ONE distinct answer up to ids (spread.distinct_answers = 1, common = union scored-kind structures, no unstable structure), so every count here is permutation-invariant; p1 is quoted.

## 1. Headline

- All 18 blind counter misses and 31 of the 33 blind false positives turn on two questions: how wide is the counting word, and is a word that steps by a variable still a counter? 25 of the 33 false positives lie on truth registers of kind accumulator.
- 7 of the 7 blind shift_register misses come from ONE rule: tools/s3/shift.py keeps a feedback lane as a shift lane only when its head is NOT GF(2)-affine in the lane's own bits, so every affine-feedback chain is handed to tools/s3/lfsr.py. lfsr.py proved 2 of them (as lfsr_crc, which the truth calls shift_register) and admitted none of the other 5.
- 9 of the 9 blind lfsr_crc misses are one design's CPU register file, labelled lfsr_crc by the truth's XOR-feedback rule; the recognizer holds at most 2 of each word's 8 flops, so the label is not what decides it.
- 20 of 20 found-but-unverified registers, blind and puzzle alike, fail the SAME obligation: the counter hold case. There is not one refutation, one solver 'unknown', one budget exhaustion, one clock-domain failure and one coverage failure in the whole blind set.
- 13 of the 40 harness-VERIFIED scored structures in the blind set earned no credit: the harness proving a counter does not make it a register the truth has.

Blind totals: **94 truth registers** of the four scored kinds over 10 designs — 59 found, **35 missed**; of the 59 found, 18 were **not** certified by the harness. The recognizer emitted **78 structures** of a scored kind, of which **33 earned no credit** and 40 were harness-verified.

Puzzle (frozen code, known design): 29 registers, 29 found, **0 missed**, **0 false positives**, 2 found-but-unverified.

## 2. The blind set, kind by kind

| kind | truth registers (designs) | found | exact | harness-verified | missed | structures | of those, no credit | verified structures |
|---|---|---|---|---|---|---|---|---|
| counter | 59 (10) | 41 | 28 | 23 | **18** | 72 | **31** | 34 |
| shift_register | 8 (4) | 1 | 1 | 1 | **7** | 1 | **0** | 1 |
| lfsr_crc | 9 (1) | 0 | 0 | 0 | **9** | 2 | **2** | 2 |
| synchronizer | 18 (4) | 17 | 17 | 17 | **1** | 3 | **0** | 3 |
| **all four** | **94 (10)** | 59 | 46 | 41 | **35** | 78 | **33** | 40 |

Read these as counts, not as rates, wherever the denominator is thin:

- **counter**: 59 registers over 10 designs — the only kind with enough support on this set to carry a rate. Found 41/59 = 0.695; harness-verified 23/59 = 0.390.
- **synchronizer**: 18 registers, but **not 18 independent events** — 16 of the 17 found were credited through 2 declared chain units (6 registers in `tt03p5/tt_um_Reloj_top`, 10 in `tt07/tt_um_vzayakov_top`), each matched by ONE structure. Read this line as *3 of the 4 synchronizer sites in the blind set*: a 3-lane × 2-stage chain in Reloj (found, verified), a 5-lane × 2-stage chain in vzayakov (found, verified), a 2-flop `strobe_sync` in `tt05/tt_um_toivoh_synth` (found, verified), and `ui_in_reg` in basilisc (missed, §3.4).
- **shift_register**: 8 registers over 4 designs, 1 found. Too small for a rate; see §3.2, where all 7 misses turn out to be one mechanism.
- **lfsr_crc**: 9 registers, **all in one design** (`tt07/tt_um_toivoh_basilisc_2816`) and all from one labelling rule firing on one CPU register file. **0 of 9 is not an out-of-sample LFSR recall**; the blind draw contained no design whose truth names a conventional LFSR as `lfsr_crc`. The two LFSRs the recognizer did find and the harness did verify are counted against it, because their truths call them shift registers (D1).

### Per design

| design | truth regs (scored kinds) | found | missed | found but unverified | structures | no credit |
|---|---|---|---|---|---|---|
| tt09__tt_um_pwm_top | 4 | 1 | 3 | 0 | 2 | 1 |
| ttsky26c__tt_um_joonatanalanampa_cordic | 6 | 3 | 3 | 0 | 4 | 1 |
| tt05__tt_um_toivoh_synth | 7 | 3 | 4 | 1 | 22 | 19 |
| ttsky25a__tt_um_td4 | 1 | 0 | 1 | 0 | 0 | 0 |
| tt03p5__tt_um_Reloj_top | 20 | 13 | 7 | 3 | 12 | 4 |
| tt03p5__tt_um_thorkn_vgaclock | 6 | 6 | 0 | 0 | 6 | 0 |
| tt07__tt_um_toivoh_basilisc_2816 | 18 | 3 | 15 | 2 | 4 | 1 |
| ttsky25a__tt_um_sjsu_vga_music | 7 | 5 | 2 | 0 | 7 | 2 |
| tt07__tt_um_vzayakov_top | 22 | 22 | 0 | 10 | 18 | 5 |
| tt05__tt_um_kskyou | 3 | 3 | 0 | 2 | 3 | 0 |
| puzzle *(known design, frozen code)* | 29 | 29 | 0 | 2 | 29 | 0 |

### The same table on the other three evaluations, each labelled

| kind | blind (out-of-sample) found / regs | puzzle (frozen code, KNOWN design) | TEMPO (IN-SAMPLE, fitted) | corpus holdout (out-of-sample, synthetic) |
|---|---|---|---|---|
| counter | 41/59 (verified 23) | 27/27 (verified 25) | 22/22 (verified 9) | verified-found 28/44 (+10 found unverified) |
| shift_register | 1/8 (verified 1) | 1/1 (verified 1) | 2/2 (verified 1) | verified-found 20/30 (+0 found unverified) |
| lfsr_crc | 0/9 (verified 0) | 1/1 (verified 1) | 2/2 (verified 2) | verified-found 14/14 (+0 found unverified) |
| synchronizer | 17/18 (verified 17) | 0/0 (verified 0) | 11/11 (verified 11) | verified-found 6/6 (+0 found unverified) |

The holdout column uses **a different aggregation** (`per_register_and_unit`: one extra item per declared unit) and its *found* already means *harness-verified*. Compare it with the blind column's verified numbers and with nothing else; the two were never designed to be subtracted.

## 3. The 35 blind misses

| cause | n | what it is |
|---|---|---|
| **M1** | 5 | partial extent: the proved word covers only part of the truth register, IoU <= 0.5 |
| **M2a** | 2 | kind error, extent exact: the whole register is one structure of an unscored kind |
| **M2b** | 10 | kind error with a grouping split: the register is spread over several unscored structures |
| **M3** | 1 | merged with a neighbouring word; one-to-one matching gave the pair to the other register |
| **M4a** | 2 | affine-feedback handoff: shift.py routed the lane to lfsr.py, which proved an lfsr_crc |
| **M4b** | 5 | affine-feedback handoff: shift.py routed the lane to lfsr.py, which admitted nothing |
| **M5** | 9 | truth kind lfsr_crc on a CPU register file; the recognizer holds at most 2 of 8 flops |
| **M6** | 1 | synchronizer of one stage: refused by the frozen contract |

### 3.1 counter — 18 misses of 59 registers

**5 of 18 are partial extent (M1).** The recognizer proved a genuine counting word, but a narrower one than the truth register, and the match threshold is `IoU > 0.5`:

| design | truth register | truth flops | the counting word the recognizer proved | IoU | that structure's harness verdict | also matched by |
|---|---|---|---|---|---|---|
| tt09__tt_um_pwm_top | `PWM_Generador.DIV_FREQ.counter` | 6 | counter1 (counter, 3 flops) — truth bits [0-2] | 0.50 | vacuous | nothing |
| tt03p5__tt_um_Reloj_top | `hourmod.hour` | 28 | counter9 (counter, 12 flops) — truth bits [4-15] | 0.43 | verified | nothing |
| tt03p5__tt_um_Reloj_top | `minites.min` | 30 | counter4 (counter, 12 flops) — truth bits [20-31] | 0.40 | verified | nothing |
| tt03p5__tt_um_Reloj_top | `timedfsm.t` | 32 | counter8 (counter, 12 flops) — truth bits [20-31] | 0.38 | verified | `w5` (data_register) at IoU 0.56 |
| ttsky25a__tt_um_sjsu_vga_music | `note_counter` | 8 | counter4 (counter, 4 flops) — truth bits [1-4] | 0.50 | hold | nothing |

Two of those five fail **by equality**: `PWM_Generador.DIV_FREQ.counter` (3 of 6 flops) and `note_counter` (4 of 8) sit at IoU exactly 0.50, and the rule is strictly greater. Three mechanisms produce the narrow word, and the run records show all three:

- **the 12-bit enumeration frontier.** `tools/s3/params.py EXHAUSTIVE_WIDTH = 12`; wider words only come from carry-chain growth. Every one of the Reloj sub-words is **exactly 12 flops** (`counter4` bits 20–31 of `minites.min`, `counter8` bits 20–31 of `timedfsm.t`, `counter6`/`counter9` of `hourmod.hour`), and so is `counter0` on `DUT.vg.VSCounter.Q` (bits 8–19 of 20, IoU 0.60 — found, but not exact). Where growth did run, it reached 26 bits (`clkdiv.counter_value`, `milimod.t`, `milimod.miliseg`, `segmod.seg`) and those registers were found.
- **dead low bits under a step of 2^k.** `hourmod.hour` has truth step 10000 = 625 × 16, so its low 4 bits cannot move; the recognizer reports `counter9` over truth bits 4–15 with **step 625**, which is 10000 / 2^4 — the arithmetic agrees exactly. `verify.py` refuses a counter with a dead bit (`live_bits`), so those 4 flops could not be in any verified word. `minites.min` (step 100) loses its low 2 bits the same way.
- **a 32-bit RTL `integer` whose top bits never reach their toggle point.** Eight of Reloj's 14 counters are 32 bits wide in the truth; the recognizer's words stop where the carry stops moving within the reachable range.

**12 of 18 are a kind error (M2).** The counter recognizer produced no word over the register at all — for every one of these 12 the best structure of a scored kind over the register has IoU 0. **9 of the 12 are 4 flops wide or narrower**, and the two widest (28 and 32 flops) are the two that the grouping stage split into two large `data_register`s:

| design | truth register | flops | truth params | what the recognizer emitted instead |
|---|---|---|---|---|
| tt09__tt_um_pwm_top | `PWM_Generador.DUTY_CYCLE` | 4 | {'direction': 'updown', 'step': 1} | w10(data_register,n=2) holds truth bits [1-2]; w9(flag,n=1) holds truth bits [0]; w3(flag,n=1) holds truth bits [3] |
| tt09__tt_um_pwm_top | `PWM_Generador.counter_debounce` | 28 | {'direction': 'up', 'step': 1} | w8(data_register,n=16) holds truth bits [1-16]; w2(data_register,n=11) holds truth bits [17-27]; w0(flag,n=1) holds truth bits [0] |
| tt05__tt_um_toivoh_synth | `saw[0]` | 2 | {'direction': 'up', 'step': 1} | w24(flag,n=1) holds truth bits [0]; w34(flag,n=1) holds truth bits [1] |
| tt05__tt_um_toivoh_synth | `saw[1]` | 2 | {'direction': 'up', 'step': 1} | w26(flag,n=1) holds truth bits [0]; w12(flag,n=1) holds truth bits [1] |
| ttsky25a__tt_um_td4 | `cpu.pc` | 4 | {'direction': 'up', 'step': 1} | w10(data_register,n=4) holds truth bits [0-3] |
| tt03p5__tt_um_Reloj_top | `doubledabble.counter` | 6 | {'direction': 'up', 'step': 1} | w10(data_register,n=5) holds truth bits [1-5]; w8(flag,n=1) holds truth bits [0] |
| tt03p5__tt_um_Reloj_top | `doubledabble.shift` | 32 | {'direction': 'up', 'step': 3} | w0(data_register,n=23) holds truth bits [1-2,4-6,8-10,12-14,16-18,20-22,24-26,28-30]; w15(data_register,n=7) holds truth bits [3,7,11,15,19,23,27]; w67(flag,n=1) holds truth bits [0]; w70(flag,n=1) holds truth bits [31] |
| tt03p5__tt_um_Reloj_top | `timedfsm.count` | 3 | {'direction': 'up', 'step': 1, 'modulus': 5} | w66(flag,n=1) holds truth bits [0]; w45(flag,n=1) holds truth bits [1]; w58(flag,n=1) holds truth bits [2] |
| tt03p5__tt_um_Reloj_top | `to7seg.count.count` | 3 | {'direction': 'up', 'step': 1} | w39(data_register,n=2) holds truth bits [1-2]; w60(flag,n=1) holds truth bits [0] |
| tt07__tt_um_toivoh_basilisc_2816 | `cpu.dec.sched.stage` | 2 | {'direction': 'up', 'step': 1} | w3(flag,n=1) holds truth bits [0]; w54(flag,n=1) holds truth bits [1] |
| tt07__tt_um_toivoh_basilisc_2816 | `cpu.mem_if.tx_monitor.counter` | 4 | {'direction': 'up', 'step': 1} | w55(flag,n=1) holds truth bits [0]; w34(flag,n=1) holds truth bits [1]; w23(flag,n=1) holds truth bits [2]; w57(flag,n=1) holds truth bits [3] |
| tt07__tt_um_toivoh_basilisc_2816 | `cpu.pref.num_flushed` | 2 | {'direction': 'down', 'step': 1} | w50(data_register,n=2) holds truth bits [0-1] |

- **2 of the 12 recover the extent exactly and only get the kind wrong (M2a)**: `ttsky25a/tt_um_td4` `cpu.pc` (4 flops, one `data_register`, IoU 1.00) and `tt07/tt_um_toivoh_basilisc_2816` `cpu.pref.num_flushed` (2 flops, one `data_register`, IoU 1.00). Both are loadable words — a program counter and a flush counter — which is what the counter recognizer's domain rules push out.
- **10 of the 12 are shattered (M2b)**: the flops end up as 1-bit `flag` structures and small `data_register`s. The recognizer's candidate-rejection histograms name the dominant reasons per design — `tt07/tt_um_toivoh_basilisc_2816`: 447 candidates rejected as *"every count step lands where the word holds (a flag enables the count)"*; `tt09/tt_um_pwm_top`: 36 *"other transitions in the domain"* and 18 *"a wrap that does not close a count cycle"*. Those are candidate counts, not per-register attributions, and this document does not claim otherwise.

**A cross-cutting split worth reading beside the causes.** Of the 35 blind misses, **12 had their extent essentially recovered by a structure of an unscored kind** (matched at IoU > 0.5, credit refused only on the kind) and **23 were not matched by anything at all**. The first group is a labelling failure with the grouping right — `cpu.pc` (IoU 1.00), `cpu.pref.num_flushed` (1.00), `ui_in_reg` (1.00), `u_cordic.z` (0.90), `doubledabble.counter` (0.83), `cpu.pref.pc` (0.75), `doubledabble.shift` (0.72), `to7seg.count.count` (0.67), `counter_debounce` (0.57), `timedfsm.t` (0.56), and the two `lfsr` registers (1.00 each, to a verified `lfsr_crc`). The second group is a grouping or extent failure as well as a kind failure.

**1 of 18 is a merge (M3).** In `tt05/tt_um_toivoh_synth`, `counter0` is a harness-**verified** 21-flop counter that holds all 16 flops of `oct_counter` *and* all 5 flops of `state`. Matching is one to one: it was credited to `oct_counter` (IoU 0.76) and `state` (IoU 0.24) was left with nothing. The truth's two registers are one counting word in the netlist.

### 3.2 shift_register — 7 misses of 8 registers, all one mechanism

`tools/s3/shift.py` turns a feedback lane into a shift lane **only when the head is NOT GF(2)-affine in the lane's own bits** (an NLFSR); *"Every other feedback lane (affine in its own bits: an LFSR/CRC candidate; or open ...) stays a 'feedback' relation for tools.s3.lfsr"*. All 7 misses are lanes that took that exit:

| design | truth register | flops | shift.py's own record | lfsr.py's answer | outcome |
|---|---|---|---|---|---|
| ttsky26c/…_cordic | `u_cordic.x`, `u_cordic.y`, `u_cordic.z` | 20 each | 3 distinct feedback heads, **19 stages each**, verdict `affine`; `candidates: 0` from 88 seeds | `lfsr_structures: 0` — *"no strongly connected affine mode could be modelled"*, *"not affine in its own bits"* | no structure of any scored kind; flops fell to `data_register` (M4b) |
| tt07/…_basilisc_2816 | `cpu.pref.pc`, `cpu.pref.imm_reg` | 16 each (2 lanes × depth 8) | 4 feedback relations with **7 stages** each (= head + 7 = depth 8), verdict `affine`; only 1 of 95 seeds became a candidate | `lfsr_blocks: 2`, `lfsr_structures: 0` | no structure (M4b) |
| tt05/…_toivoh_synth | `lfsr` | 15 | `feedback_affine: 2` | **verified** `lfsr_crc`, form fibonacci, IoU 1.00 | shift miss **and** an lfsr_crc false positive (M4a, disagreement D1) |
| ttsky25a/…_sjsu_vga_music | `lfsr` | 13 | `feedback_affine: 1` | **verified** `lfsr_crc`, fibonacci, poly 13329, IoU 1.00 | shift miss **and** a false positive (M4a, D1) |

The control case proves the mechanism rather than the design: in the *same* basilisc netlist, `cpu.pref.sreg` — identical shape, 2 lanes × depth 8, but with **input-pin heads** (`ui_in_reg[0]`, `ui_in_reg[1]`) instead of a feedback head — was found **exactly** and verified. Same design, same depth, same lane count; the head is the whole difference.

These identifications are by **shape**: the relation records carry head counts and stage depths, not flop names. 3 heads × 19 stages against 3 truth registers of 20 flops, and 4 lanes × 7 stages against 2 truth registers of 2 lanes × depth 8, is an exact fit in both designs.

### 3.3 lfsr_crc — 9 misses of 9 registers, all one design and one label

All 9 are `tt07/tt_um_toivoh_basilisc_2816`'s CPU register file: `…general_registers.regs[0..7]` and `…sp_register.regs`, 8 flops each, `module_def` `regfile` / `regfile_single`. The truth's rule is *"own Q bits of other indices reach D through XOR (GF(2) feedback)"* — `truth_tempo.py` rule 4, which fires when ≥ max(2, n/4) bits have such feedback. An ALU that shifts and XORs its register file satisfies that on every word. The truth's own params for all 9 are null: no form, no polynomial, no k_steps, no bit_order.

The recognizer split each 8-bit word into **four 2-flop pieces** (three `data_register`, one `register_file_word`), each piece straddling two words (e.g. `w20` holds 2 bits of `regs[0]` and 2 of `regs[4]`). Its largest overlap with any of these registers is **2 of 8 flops, IoU ≤ 0.25** — so these 9 would be missed under *any* kind label. Listing this as a disagreement (D2) does not recover a single register.

### 3.4 synchronizer — 1 miss of 18 registers

`tt07/tt_um_toivoh_basilisc_2816` `ui_in_reg`: the truth labels it a synchronizer with **`stages: 1`** (2 of its 8 bits have flops). The frozen contract refuses that by definition — `verify.py` `SYNC_MIN_STAGES = 2`, *"a one-flop 'synchronizer' is the input register whose metastability the second stage exists to absorb, and every flop that registers a pin or a foreign-domain flop would otherwise verify as one"*. The recognizer emitted a 2-flop `data_register` over exactly those flops (IoU 1.00). A **synchronizer of one stage** cannot be reported or verified by this freeze (disagreement D4).

## 4. Found but not verified — 18 blind registers, 20 with the puzzle, one obligation

Every single one is the **counter hold obligation**. Nothing else failed anywhere in the blind set: no refutation, no solver `unknown`, no `budget`, no `clock domains`, no `coverage`, no `template`, no `params`, no `not checked`.

| cause | blind | puzzle | verifier's words |
|---|---|---|---|
| **V1** hold obligation not claimed | 2 | 2 | verify.py: 'control.hold is required for a counter (schema v2) and is not claimed' |
| **V2** hold region emptied only by the opaque load cases | 16 | 0 | verify.py HOLD_EMPTY_NEEDS_VERIFIED_COVER test (a): without the opaque load case(s) the hold region is satisfiable, so the load is what erases the hold obligation; the structure is refused |

| design | truth register | flops | structure | IoU | exact | bucket |
|---|---|---|---|---|---|---|
| tt05__tt_um_toivoh_synth | `pwm_counter` | 5 | counter6 | 1.00 | True | vacuous |
| tt03p5__tt_um_Reloj_top | `clkdiv.counter_value` | 32 | counter0 | 0.81 | False | vacuous |
| tt03p5__tt_um_Reloj_top | `debdown.delay_timer` | 20 | counter10 | 0.60 | False | vacuous |
| tt03p5__tt_um_Reloj_top | `milimod.t` | 32 | counter1 | 0.81 | False | vacuous |
| tt07__tt_um_toivoh_basilisc_2816 | `cpu.dec.sched.alu.state` | 3 | counter2 | 0.67 | False | hold |
| tt07__tt_um_toivoh_basilisc_2816 | `cpu.mem_if.sbio_rx.counter` | 4 | counter0 | 0.75 | False | vacuous |
| tt07__tt_um_vzayakov_top | `DUT.s.LScore1.Q` | 4 | counter15 | 1.00 | True | vacuous |
| tt07__tt_um_vzayakov_top | `DUT.s.LScore2.Q` | 4 | counter14 | 1.00 | True | vacuous |
| tt07__tt_um_vzayakov_top | `DUT.s.LScore3.Q` | 4 | counter10 | 1.00 | True | vacuous |
| tt07__tt_um_vzayakov_top | `DUT.s.LScore4.Q` | 4 | counter12 | 1.00 | True | vacuous |
| tt07__tt_um_vzayakov_top | `DUT.s.RScore1.Q` | 4 | counter9 | 1.00 | True | vacuous |
| tt07__tt_um_vzayakov_top | `DUT.s.RScore2.Q` | 4 | counter11 | 1.00 | True | vacuous |
| tt07__tt_um_vzayakov_top | `DUT.s.RScore3.Q` | 4 | counter8 | 1.00 | True | vacuous |
| tt07__tt_um_vzayakov_top | `DUT.s.RScore4.Q` | 4 | counter13 | 1.00 | True | vacuous |
| tt07__tt_um_vzayakov_top | `DUT.vg.HSCounter.Q` | 11 | counter1 | 1.00 | True | vacuous |
| tt07__tt_um_vzayakov_top | `DUT.vg.RowCounter.Q` | 9 | counter5 | 1.00 | True | vacuous |
| tt05__tt_um_kskyou | `R` | 8 | counter0 | 1.00 | True | vacuous |
| tt05__tt_um_kskyou | `temp1` | 8 | counter1 | 1.00 | True | hold |
| puzzle *(known design, frozen code)* | `bin00` | 2 | counter4 | 1.00 | True | hold |
| puzzle *(known design, frozen code)* | `bin09` | 2 | counter11 | 1.00 | True | hold |

The 16 `vacuous` verdicts are the freeze's own anti-erasure rule doing its job: `HOLD_EMPTY_NEEDS_VERIFIED_COVER` refuses a structure whose hold region is empty only once the **opaque load cases** are conjoined in, because *"an opaque load may never be the thing that empties the hold region"*. Ten of the sixteen are `tt07/tt_um_vzayakov_top`'s eight 4-bit score counters and two video counters, all matched at IoU 1.00 and exact. The recognizer's extent was perfect; the certificate was refused.

**Where the gap falls.** Counter is the only kind with a found/verified gap on the blind set: 41 found, 23 verified (18 short). shift_register (1/1), synchronizer (17/17) and the puzzle's lfsr_crc (1/1) have none. This is the same ceiling `score.py`'s `HOLD_CEILING_NOTE` records on the development design, reached again on designs nobody had seen — on TEMPO (IN-SAMPLE) the recognizer finds 22 of 22 counters and the harness certifies 9.

## 5. The 33 blind false positives

| cause | n | what it is |
|---|---|---|
| **F1** | 15 | counter proved over a truth accumulator (matched, wrong kind) |
| **F2** | 10 | counter proved over a fragment of a truth accumulator (matched nothing) |
| **F3** | 6 | counter proved over a sub-word of a truth counter (matched nothing) |
| **F4** | 2 | lfsr_crc proved over a truth shift_register |

**25 of the 33 lie on truth registers of kind `accumulator`** — 15 matched one at IoU > 0.5 with the wrong kind (F1) and 10 are fragments of one, too small to match (F2). Every one of those truth registers carries the rule *"D = Q + a multi-bit variable (the adder on own Q)"* and **no `alt_kinds`**, so neither strict nor lenient scoring can accept a counter over it. The recognizer proved a constant step on the lanes it exercised; the RTL adds a variable. The harness agrees with the truth far more often than not: **14 of those 15 wrong-kind matches were refused** (13 on the hold obligation, 1 vacuous) and only `tt07/tt_um_vzayakov_top` `counter4` (on `DUT.b.BallCol.Q`, IoU 0.90) was verified.

| design | structure | flops | truth register it lands on | truth kind | IoU | harness verdict |
|---|---|---|---|---|---|---|
| ttsky26c__tt_um_joonatanalanampa_cordic | counter1 | 9 | `phase` (20 flops) | accumulator | 0.45 | verified |
| tt05__tt_um_toivoh_synth | counter1 | 8 | `cfg[0]` (13 flops) | accumulator | 0.62 | hold |
| tt05__tt_um_toivoh_synth | counter2 | 8 | `cfg[2]` (13 flops) | accumulator | 0.62 | hold |
| tt05__tt_um_toivoh_synth | counter3 | 8 | `cfg[4]` (13 flops) | accumulator | 0.62 | hold |
| tt05__tt_um_toivoh_synth | counter4 | 7 | `saw_counter_state[0]` (10 flops) | accumulator | 0.70 | hold |
| tt05__tt_um_toivoh_synth | counter5 | 6 | `saw_counter_state[1]` (10 flops) | accumulator | 0.60 | hold |
| tt05__tt_um_toivoh_synth | counter7 | 5 | `cfg[0]` (13 flops) | accumulator | 0.38 | verified |
| tt05__tt_um_toivoh_synth | counter8 | 5 | `cfg[1]` (13 flops) | accumulator | 0.38 | hold |
| tt05__tt_um_toivoh_synth | counter9 | 5 | `cfg[1]` (13 flops) | accumulator | 0.38 | verified |
| tt05__tt_um_toivoh_synth | counter10 | 4 | `sweep_counter_state[0]` (4 flops) | accumulator | 1.00 | hold |
| tt05__tt_um_toivoh_synth | counter11 | 4 | `sweep_counter_state[4]` (4 flops) | accumulator | 1.00 | hold |
| tt05__tt_um_toivoh_synth | counter12 | 4 | `sweep_counter_state[2]` (4 flops) | accumulator | 1.00 | hold |
| tt05__tt_um_toivoh_synth | counter13 | 4 | `sweep_counter_state[3]` (4 flops) | accumulator | 1.00 | hold |
| tt05__tt_um_toivoh_synth | counter14 | 4 | `cfg[2]` (13 flops) | accumulator | 0.31 | verified |
| tt05__tt_um_toivoh_synth | counter15 | 4 | `sweep_counter_state[1]` (4 flops) | accumulator | 1.00 | hold |
| tt05__tt_um_toivoh_synth | counter16 | 4 | `y` (20 flops) | accumulator | 0.20 | hold |
| tt05__tt_um_toivoh_synth | counter17 | 4 | `cfg[4]` (13 flops) | accumulator | 0.31 | verified |
| tt05__tt_um_toivoh_synth | counter18 | 4 | `cfg[3]` (13 flops) | accumulator | 0.31 | verified |
| tt05__tt_um_toivoh_synth | counter19 | 3 | `v` (20 flops) | accumulator | 0.15 | hold |
| tt07__tt_um_toivoh_basilisc_2816 | counter1 | 2 | `cpu.pref.num_prefetched` (2 flops) | accumulator | 1.00 | hold |
| tt07__tt_um_vzayakov_top | counter3 | 9 | `DUT.b.BallRow.Q` (9 flops) | accumulator | 1.00 | vacuous |
| tt07__tt_um_vzayakov_top | counter4 | 9 | `DUT.b.BallCol.Q` (10 flops) | accumulator | 0.90 | verified |
| tt07__tt_um_vzayakov_top | counter6 | 6 | `DUT.leftPaddle.PaddleRow.Q` (9 flops) | accumulator | 0.67 | hold |
| tt07__tt_um_vzayakov_top | counter7 | 6 | `DUT.rightPaddle.PaddleRow.Q` (9 flops) | accumulator | 0.67 | hold |
| tt07__tt_um_vzayakov_top | counter16 | 3 | `DUT.leftPaddle.PaddleRow.Q` (9 flops) | accumulator | 0.33 | verified |

**6 of the 33 are the mirror image of the M1 misses (F3)**: a proved counting sub-word of a wider truth counter, below the IoU threshold, so the same event is charged twice — once as a miss, once as a false positive. `hourmod.hour` alone contributes two (`counter6`, `counter9`).

| design | structure | flops | truth counter | truth flops | IoU | harness verdict |
|---|---|---|---|---|---|---|
| tt09__tt_um_pwm_top | counter1 | 3 | `PWM_Generador.DIV_FREQ.counter` | 6 | 0.50 | vacuous |
| tt03p5__tt_um_Reloj_top | counter4 | 12 | `minites.min` | 30 | 0.40 | verified |
| tt03p5__tt_um_Reloj_top | counter6 | 12 | `hourmod.hour` | 28 | 0.43 | hold |
| tt03p5__tt_um_Reloj_top | counter8 | 12 | `timedfsm.t` | 32 | 0.38 | verified |
| tt03p5__tt_um_Reloj_top | counter9 | 12 | `hourmod.hour` | 28 | 0.43 | verified |
| ttsky25a__tt_um_sjsu_vga_music | counter4 | 4 | `note_counter` | 8 | 0.50 | hold |

**2 of the 33 are the LFSR/shift disagreement (F4)** — `lfsr0` in `tt05/tt_um_toivoh_synth` (15 flops) and in `ttsky25a/tt_um_sjsu_vga_music` (13 flops), both matched at IoU 1.00 and both **harness-verified**, against truth registers of kind `shift_register`. See D1.

### What a verified structure is worth

**13 of the 40 harness-verified scored structures in the blind set earned no credit.** The harness proving a counter or an LFSR is a statement about the netlist, not about the truth's register list:

| design | structure | kind | flops | why no credit |
|---|---|---|---|---|
| ttsky26c__tt_um_joonatanalanampa_cordic | counter1 | counter | 9 | matched nothing; best overlap `phase` (accumulator) at IoU 0.45 |
| tt05__tt_um_toivoh_synth | counter7 | counter | 5 | matched nothing; best overlap `cfg[0]` (accumulator) at IoU 0.38 |
| tt05__tt_um_toivoh_synth | counter9 | counter | 5 | matched nothing; best overlap `cfg[1]` (accumulator) at IoU 0.38 |
| tt05__tt_um_toivoh_synth | counter14 | counter | 4 | matched nothing; best overlap `cfg[2]` (accumulator) at IoU 0.31 |
| tt05__tt_um_toivoh_synth | counter17 | counter | 4 | matched nothing; best overlap `cfg[4]` (accumulator) at IoU 0.31 |
| tt05__tt_um_toivoh_synth | counter18 | counter | 4 | matched nothing; best overlap `cfg[3]` (accumulator) at IoU 0.31 |
| tt05__tt_um_toivoh_synth | lfsr0 | lfsr_crc | 15 | matched `lfsr` (shift_register) at IoU 1.00 — kind not accepted |
| tt03p5__tt_um_Reloj_top | counter4 | counter | 12 | matched nothing; best overlap `minites.min` (counter) at IoU 0.40 |
| tt03p5__tt_um_Reloj_top | counter8 | counter | 12 | matched nothing; best overlap `timedfsm.t` (counter) at IoU 0.38 |
| tt03p5__tt_um_Reloj_top | counter9 | counter | 12 | matched nothing; best overlap `hourmod.hour` (counter) at IoU 0.43 |
| ttsky25a__tt_um_sjsu_vga_music | lfsr0 | lfsr_crc | 13 | matched `lfsr` (shift_register) at IoU 1.00 — kind not accepted |
| tt07__tt_um_vzayakov_top | counter4 | counter | 9 | matched `DUT.b.BallCol.Q` (accumulator) at IoU 0.90 — kind not accepted |
| tt07__tt_um_vzayakov_top | counter16 | counter | 3 | matched nothing; best overlap `DUT.leftPaddle.PaddleRow.Q` (accumulator) at IoU 0.33 |

## 6. Label disagreements — listed, never applied

*docs/S3_DESIGN.md section 4.4: 'Labels are fixed before scoring; later disagreements are listed, never applied.' No truth file was read-modified and no number in this document applies a disagreement.*

### D1 — shift_register vs lfsr_crc

- **Designs**: tt05__tt_um_toivoh_synth, ttsky25a__tt_um_sjsu_vga_music
- **Registers**: lfsr (15 flops); lfsr (13 flops)
- **Harness**: both lfsr_crc structures were VERIFIED by tools/s3/verify.py (form fibonacci; sjsu poly 13329, k_steps 1, 0 input nets)
- **Why the truth says what it says**: tools/s3/truth_tempo.py Classifier.classify tries its lfsr_crc rule (rule 4) BEFORE its shift_register rule (rule 6), but rule 4 needs own-Q XOR feedback into at least max(2, n/4) bits. A Fibonacci LFSR XORs into ONE head bit, so rule 4 does not fire and rule 6 labels the register a shift_register with serial_in '(lfsr[0] ^ lfsr[14])' (synth) / 'feedback' (sjsu) -- the truth's own params record the XOR feedback it declined to name.
- **What it costs**: 2 of the 8 blind shift_register registers and 2 of the 33 blind false-positive structures; counted as errors in both directions for the same 2 registers
- **Applied to any number in this document**: no

### D2 — lfsr_crc vs data_register / register_file_word (2-bit pieces)

- **Designs**: tt07__tt_um_toivoh_basilisc_2816
- **Registers**: cpu.dec.sched.alu.registers.general_registers.regs[0] (8 flops); cpu.dec.sched.alu.registers.general_registers.regs[1] (8 flops); cpu.dec.sched.alu.registers.general_registers.regs[2] (8 flops); cpu.dec.sched.alu.registers.general_registers.regs[3] (8 flops); cpu.dec.sched.alu.registers.general_registers.regs[4] (8 flops); cpu.dec.sched.alu.registers.general_registers.regs[5] (8 flops); cpu.dec.sched.alu.registers.general_registers.regs[6] (8 flops); cpu.dec.sched.alu.registers.general_registers.regs[7] (8 flops); cpu.dec.sched.alu.registers.sp_register.regs (8 flops)
- **Harness**: not applicable: no lfsr_crc structure was emitted on this design
- **Why the truth says what it says**: the same rule 4 fires on a CPU register file because the ALU writes each word through shift and XOR paths, so own Q bits of other indices reach D through XOR on >= max(2, 8/4) = 2 bits. The truth's own params for all 9 registers are null (form, poly, k_steps, n_inputs, bit_order), module_def 'regfile' and 'regfile_single'. The labeller's register_file_word rule (rule 1) did not claim them.
- **What it costs**: all 9 blind lfsr_crc registers, i.e. the whole lfsr_crc denominator of the blind set
- **RELABELLING WOULD NOT CHANGE THE SCORE: the recognizer's largest structure over any of these words holds 2 of the 8 flops (IoU <= 0.25), so each register is missed under any kind.**
- **Applied to any number in this document**: no

### D3 — counter vs two interleaved data_registers (23 and 7 flops) plus 2 flags

- **Designs**: tt03p5__tt_um_Reloj_top
- **Registers**: doubledabble.shift (32 flops)
- **Harness**: not applicable: no counter structure covers these flops
- **Why the truth says what it says**: the truth's arithmetic rule (rule 5, 'D = Q +/- constant') reads the double-dabble add-3 correction as a counter of step 3. The recognizer's split is periodic mod 4 -- one structure holds truth bits {3,7,11,15,19,23,27} and the other the rest -- which is the BCD nibble structure of a shift-and-add-3 datapath, not a counting word.
- **What it costs**: 1 of the 18 blind counter misses
- **Applied to any number in this document**: no

### D4 — synchronizer vs data_register (2 flops, IoU 1.00)

- **Designs**: tt07__tt_um_toivoh_basilisc_2816
- **Registers**: ui_in_reg (2 flops of 8 bits)
- **Harness**: a 1-stage synchronizer can never be verified: tools/s3/verify.py SYNC_MIN_STAGES = 2
- **Why the truth says what it says**: the truth's rule 3 accepts a register whose D is an input pin as a synchronizer of ONE stage; the frozen contract defines a synchronizer as >= 2 stages ('a one-flop synchronizer is the input register whose metastability the second stage exists to absorb'). The two conventions disagree, and the recognizer cannot satisfy both.
- **What it costs**: the single blind synchronizer miss (1 of 18)
- **Applied to any number in this document**: no

One structural asymmetry underlies D1 and D4 and is worth stating on its own. `tools/s3/thirdparty.py` takes `alt_kinds` **only from the design-agnostic classification rules** — in practice the 1-bit toggle rule. `truth_tempo.ALT_KINDS`, the five hand-written entries that let TEMPO's truth say *"a structural recognizer may also fairly report this as a shift_register / data_register / synchronizer"*, are keyed by **TEMPO register-name regexes** and can never fire on a third-party design. So the blind set is scored under a **strictly harsher labelling convention than the development design**: on the blind truths not one register of a scored kind carries an alternative, and strict and lenient scoring coincide. The puzzle's own truth, by contrast, does carry `lfsr_crc` with `alt_kinds: [shift_register]` — the very ambiguity that D1 charges as two errors.

## 7. The puzzle, and what it does and does not add

On the puzzle — **frozen code, a design the team has worked on all along, not a blind test** — the recognizer has **0 misses and 0 false positives** over 29 registers of scored kinds (27 counter, 1 shift_register, 1 lfsr_crc) and 29 structures, all 29 credited and all 29 exact. Two counters (`bin00`, `bin09`, 2 flops each, matched at IoU 1.00) were found but not verified, both because `control.hold` was not claimed — the same obligation as §4. This is a frozen-code result on known ground and carries no out-of-sample weight; it is here because it shows the found/verified gap is not an artifact of unfamiliar designs.

## 8. Caveats

- Sample sizes. The blind denominators are 59 counter registers over 10 designs, 18 synchronizer registers over 4 designs, 8 shift_register registers over 4 designs and 9 lfsr_crc registers over ONE design. Anything said about lfsr_crc out of sample rests on one design and one labelling rule; it is not a rate. score.py's SMALL_SUPPORT is 3 registers per kind per design, and most per-design kind counts are below it.
- The 18 synchronizer registers are not 18 independent events: 16 of the 17 found were credited through 2 declared chain units (6 registers in tt03p5/tt_um_Reloj_top, 10 in tt07/tt_um_vzayakov_top), each matched by ONE recognizer structure. Read the synchronizer line as 3 chains found of 4.
- Every count is the strict register level on permutation p1; strict equals lenient on this set (see method).
- One design has unmapped flops: ttsky25a/tt_um_sjsu_vga_music, 7 of 77 netlist flops with 'no RTL name on the Q net'. All 7 fell in structures of unscored kinds (4 structures lost every flop and were dropped), so no miss and no false positive in this document is caused by a dropped or unmapped flop. No other design has any unmapped, shadow or unknown flop, and no scored structure anywhere lost a flop.
- The corpus-holdout figures are quoted with their own aggregation and their own meaning of 'found' (harness-verified); they are not comparable term by term with the blind counts.
- This document explains outcomes; it does not re-run the recognizer. Where a cause names a recognizer rule, the evidence is the run record's own stage statistics and relation records (which carry shapes, not flop names), the harness verdict text, and the truth's own rule string. Those identifications are marked in the per-case 'mechanism' text and are by shape, not by flop id.

---

*Case-by-case data, including every register's per-bit coverage and every structure's parameters, harness verdict and truth overlaps, is in `out/s3/blind/analysis/misses.json` (`cases`, one row per miss, found-but-unverified register and false positive; `designs`, one entry per run with its permutation spread, join counts and recognizer stage statistics).*
