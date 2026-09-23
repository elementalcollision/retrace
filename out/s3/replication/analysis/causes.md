# S3 replication -- every miss and false positive, with its cause

Generated 2026-09-23T17:34:34Z by `out/s3/replication/analysis/causes.py` (sha256 `0cf99b857f9d3710...`). Set **R** = the 10 Freeze-4 designs; **B1** = freeze 1's 10 blind designs (`out/s3/blind/analysis/misses.json`, read only). Taxonomy: `docs/S3.md` sections 8-9, with new codes only where none fits.

Freeze check before: `freeze holds`; after: `freeze holds`.

The mechanical lists (which registers were missed, which structures earned nothing) are recomputed with `compute_numbers.py`'s own scorer glue and asserted equal to `numbers.json`'s. Rates are not computed here; the few quoted are copied from `numbers.json`:

* primary (counter harness-VERIFIED found recall, strict): R 19/49 = 0.3878, B1 23/59 = 0.3898, R - B1 -0.0021 [-0.3121, 0.2853]: **consistent with freeze 1** (the plan's word).
* R shift_register found: strict 4/9 = 0.4444, lenient 6/9 = 0.6667 -- the difference is exactly the M3b pair.

## Headline

* R has 27 misses and 34 false positives (18 harness-VERIFIED). B1's codes cover 16 of the 27 misses (M1 4, M2a 2, M2b 5, M4a 1, M6 4) and 18 of the 34 false positives (F1 1, F2 4, F3 12, F4 1); the rest needed new codes: misses M3b 2, M6b 1, M7 7, M8 1; false positives F3b 1, F5 4, F6 3, F7 7, F8 1.
* The biggest new code is one design: M7 and F7 (7 + 7) are seven instances of SJ's PE, where the recognizer paired counter bit 0 with the Tier A calculating_RS flop.
* B1's dominant false-positive cause, a counter over a truth accumulator (F1 + F2: 25 in B1), is 5 in R; the counter sub-word (F3 + F3b) rises from 6 to 13. Every R counter false positive is still a question of word extent (F3, F3b, F7) or of constant versus variable step (F1, F2).
* R has 8 shift_register false positives where B1 had none: word-wise array shifts the truth labels data_register (F5, 4), pipelines written one 1-bit register per stage (F6, 3) and a two-register merge (F8, 1). 3 of the 8 are harness-VERIFIED; the other 5 were refused on the hold obligation. The seven that are not F8 lie mostly or wholly on registers the truth labels data_register or flag (label disagreements R-D3, R-D4).
* B1's lfsr-side miss causes do not recur: no M4b (lfsr.py admitting nothing) and no M5 (R has no lfsr_crc truth register); M4a (the author-named LFSR labelled shift_register) recurs once with its F4.
* The 1-stage-synchronizer convention conflict (M6, B1 D4) recurs four times and is all of R's synchronizer misses; its shift_register twin (M6b, depth 2) is new.
* Found-but-unverified flips its mix: B1 V1 2 / V2 16, R V1 12 / V2 1 -- in R the recognizer mostly failed to claim hold at all, and one of the 12 is a shift_register.

## 1. Cause distribution, R beside B1

### Misses (27 in R, 35 in B1)

| Code | What it is | B1 | R | R designs | status |
|---|---|---|---|---|---|
| **M1** | partial extent: the proved word covers only part of the truth register, IoU <= 0.5 | 5 | 4 | 3 | recurs |
| **M2a** | kind error, extent exact: the whole register is one structure of an unscored kind | 2 | 2 | 1 | recurs |
| **M2b** | kind error with a grouping split: the register is spread over several unscored structures | 10 | 5 | 3 | recurs |
| **M3** | merged with a neighbouring word; one-to-one matching gave the pair to the other register | 1 | 0 | 0 | B1 only |
| **M3b** | merged with a parallel register into one multi-lane structure; IoU exactly 0.50 with each, so strict scoring credits neither | 0 | 2 | 1 | new in R |
| **M4a** | affine-feedback handoff: shift.py routed the lane to lfsr.py, which proved an lfsr_crc | 2 | 1 | 1 | recurs |
| **M4b** | affine-feedback handoff: shift.py routed the lane to lfsr.py, which admitted nothing | 5 | 0 | 0 | B1 only |
| **M5** | truth kind lfsr_crc on a CPU register file; the recognizer holds at most 2 of 8 flops | 9 | 0 | 0 | B1 only |
| **M6** | synchronizer of one stage: refused by the frozen contract | 1 | 4 | 2 | recurs |
| **M6b** | shift register of depth 2: below the frozen contract's minimum depth | 0 | 1 | 1 | new in R |
| **M7** | straddling word: a counter structure over part of the register plus a flop of a neighbouring register, matching neither | 0 | 7 | 1 | new in R |
| **M8** | multi-mode shift register: the recognizer's structure follows one mode's copy relation, whose lanes run across the register and a parallel word-wise shift | 0 | 1 | 1 | new in R |

### False positives (34 in R, 18 verified; 33 in B1, 13 verified)

| Code | What it is | B1 (verified) | R (verified) | R refused, by harness bucket | R designs | status |
|---|---|---|---|---|---|---|
| **F1** | counter proved over a truth accumulator (matched, wrong kind) | 15 (1) | 1 (1) | - | 1 | recurs |
| **F2** | counter proved over a fragment of a truth accumulator (matched nothing) | 10 (7) | 4 (2) | hold 2 | 4 | recurs |
| **F3** | counter proved over a sub-word of a truth counter (matched nothing) | 6 (3) | 12 (10) | vacuous 1, hold 1 | 4 | recurs |
| **F3b** | counter over a sub-word of a truth counter, paired by the one-to-one matcher with a synthesis 'retimed' register of kind other (matched, kind refused) | 0 (0) | 1 (1) | - | 1 | new in R |
| **F4** | lfsr_crc proved over a truth shift_register | 2 (2) | 1 (1) | - | 1 | recurs |
| **F5** | shift_register over word-wise (array-entry) shift chains the truth labels data_register per entry | 0 (0) | 4 (0) | hold 4 | 2 | new in R |
| **F6** | shift_register over a chain of 1-bit truth registers (a pipeline written one RTL register per stage, labelled flag per stage) | 0 (0) | 3 (2) | hold 1 | 2 | new in R |
| **F7** | counter straddling a truth counter bit and a truth flag (matched nothing) | 0 (0) | 7 (0) | hold 7 | 1 | new in R |
| **F8** | multi-lane shift_register merging two parallel truth shift registers (IoU 0.50 each; matched nothing in strict mode) | 0 (0) | 1 (1) | - | 1 | new in R |

F3 in R: 6 lie on a missed truth counter (the mirror of an M1) and 6 are extra sub-words of a truth counter that ANOTHER structure found (a split word whose larger part matched). All 6 of B1's F3 were the mirror of an M1 (docs/S3.md 9.1).

### Found but unverified (not misses; the harness refused the matching structure)

| Code | B1 | R |
|---|---|---|
| **V1** hold obligation not claimed | 2 | 12 |
| **V2** hold region emptied only by the opaque load cases | 16 | 1 |

Every harness refusal in R is the hold obligation -- 27 structures `hold` (not claimed) and 2 `vacuous` (`HOLD_EMPTY_NEEDS_VERIFIED_COVER` test (a)); there is no refutation, solver `unknown`, budget, clock or coverage failure (numbers.json: unverified reasons hold 27, vacuous 2).

### Which recur, which are new

* **Recur (both sets):** M1 partial extent, M2a and M2b kind errors, M4a (an author-named LFSR proved `lfsr_crc` over a truth `shift_register`), M6 (a one-stage synchronizer the contract refuses); F1-F4; V1 and V2. Two of R's four M1 fail by equality (IoU exactly 0.50), as two of B1's five did; R's `transfer_state` (97 declared bits, 7 reachable) is B1's wide-integer M1 mechanism again, and its 12-flop `counter4` is again `EXHAUSTIVE_WIDTH`.
* **B1 only:** M3 as B1 defined it (merge credited to one register), M4b (lfsr.py admitting nothing: 5 in B1, on two designs), M5 (B1's 9 register-file `lfsr_crc` labels, one design; R has no `lfsr_crc` truth register at all).
* **New in R:** misses M3b, M6b, M7, M8; false positives F3b, F5, F6, F7, F8. M7/F7 is one module met seven times in one design. M6b is M6's contract floor for `shift_register`. F5 and F6 are the first `shift_register` false positives in either set, and both sit on label disagreements (R-D3, R-D4).
* **Shifted weight:** accumulator-side false positives (F1 + F2) 25 -> 5; counter sub-word false positives (F3 + F3b) 6 -> 13; M6 1 -> 4; V2 16 -> 1 while V1 2 -> 12.

## 2. The new codes, and why no B1 code fits

* **M3b** -- merged with a parallel register into one multi-lane structure; IoU exactly 0.50 with each, so strict scoring credits neither. Two equal-depth lanes with the same flop controls are joined by the recognizer's lane rule into ONE structure holding both truth registers whole; with two equal registers the IoU with each is exactly 0.50 and score.py needs IoU > 0.5 (IOU_MIN), so neither is credited in strict mode. The truth declares the pair a copy_lanes unit, which is an item only in lenient mode, where both are credited. Nearest B1 code: M3; B1's M3 is a merge in which the one-to-one matcher credited the structure to the larger register and the other was a miss; here the two are the same size, so neither passes the threshold. Same mechanism (a merge), different scoring consequence.
* **M6b** -- shift register of depth 2: below the frozen contract's minimum depth. The truth's shift_register rule accepts a depth-2 register (D[k] = Q[k-1] on 1 of 1 shiftable bits); tools/s3/verify.py SHIFT_MIN_DEPTH = 3 and tools/s3/params.py SHIFT_MIN_DEPTH = 3 ('depth 2 is a transfer relation'), so no shift_register structure can be emitted or verified over it. Nearest B1 code: M6; M6 is the same contract floor for a synchronizer of one stage; this is its shift_register twin, which B1 did not meet.
* **M7** -- straddling word: a counter structure over part of the register plus a flop of a neighbouring register, matching neither. The recognizer's counting word takes one bit of the truth counter and one flop of a neighbouring 1-bit register (IoU <= 0.5 with both), leaving the counter's other bit a 1-bit flag; no structure matches the register. Nearest B1 code: M1 / M3; not M1 (the word is not a narrower sub-word of the register: half of it is a foreign flop); not M3 (no structure holds the whole register, and nothing was matched); not M2 (a scored-kind structure does overlap the register).
* **M8** -- multi-mode shift register: the recognizer's structure follows one mode's copy relation, whose lanes run across the register and a parallel word-wise shift. The register shifts in different directions in different FSM states (and loads constants in others); the recognizer's shift structure over its flops follows ONE of those copy relations, so its lanes and stages cut across the truth register and a parallel register-array shift, and the register is held at IoU <= 0.25. Nearest B1 code: M4a / M4b (B1's only shift_register miss causes); B1's shift_register misses all took the affine-feedback exit to lfsr.py; this register has no feedback -- shift.py did emit a structure over its flops, along another axis.
* **F3b** -- counter over a sub-word of a truth counter, paired by the one-to-one matcher with a synthesis 'retimed' register of kind other (matched, kind refused). The structure is a genuine counting sub-word of a truth counter (F3's mechanism), but the truth also assigns its low flops to an 'other' register created for Yosys-merged flops, and the matcher took that pair because its IoU is higher. Nearest B1 code: F3; F3 is defined as 'matched nothing'; this one matched an item of another kind.
* **F5** -- shift_register over word-wise (array-entry) shift chains the truth labels data_register per entry. RTL of the form reg[i] <= reg[i-1] over an unpacked array is a multi-lane shift register whose stages are separate RTL registers; the labeller's shift rule looks for D[k] = Q[k-1] inside ONE register, so each entry is a data_register. The recognizer's lanes are exactly those entry-to-entry copies; several such chains that share a shift enable are joined into one lanes_unordered structure. Nearest B1 code: none (B1 had no shift_register false positive); F1-F4 are counter or lfsr_crc structures.
* **F6** -- shift_register over a chain of 1-bit truth registers (a pipeline written one RTL register per stage, labelled flag per stage). Each stage is its own 1-bit RTL register (per module instance, or three named registers), which the labeller's rules call 'single-bit register' (flag); the labeller's copy_lanes unit rule joins only registers already labelled shift_register or synchronizer, so no truth item spans the chain the recognizer returned. Nearest B1 code: none (B1 had no shift_register false positive); F1-F4 are counter or lfsr_crc structures.
* **F7** -- counter straddling a truth counter bit and a truth flag (matched nothing). The structure side of M7. Nearest B1 code: F3; F3's word is a sub-word of ONE truth counter; half of this word is a flop of another register.
* **F8** -- multi-lane shift_register merging two parallel truth shift registers (IoU 0.50 each; matched nothing in strict mode). The structure side of M3b. Nearest B1 code: none; B1's M3 merge was credited to one of its two registers, so it produced no false positive.

## 3. Per design (R)

| Design | misses by cause | false positives by cause |
|---|---|---|
| `tt04__tt_um_jayraj4021_SAP1_cpu` | - | - |
| `ttsky26b__tt_um_tiny_8bit_cpu` | - | F2 1 |
| `tt06__tt_um_SJ` | M2a 2, M6b 1, M7 7 | F2 1, F5 3, F7 7 |
| `tt06__tt_um_kwilke_cdc_fifo` | - | - |
| `ttsky25b__tt_um_yorimichi_kittscanner` | M1 1, M2b 1, M8 1 | F3 3, F5 1 |
| `tt05__tt_um_digital_clock_sellicott` | M1 1, M3b 2 | F1 1, F2 1, F3 5, F6 1, F8 1 |
| `tt05__tt_um_nickjhay_processor` | M6 1 | F6 2 |
| `ttsky25b__tt_um_ieeeuoftasic_simproc` | - | F3 1 |
| `ttsky26a__tt_um_parakeet` | M2b 3 | F2 1 |
| `ttcad25a__tt_um_space_invaders_game` | M1 2, M2b 1, M4a 1, M6 3 | F3 3, F3b 1, F4 1 |

## 4. Every miss

"Harness" says what the harness did with the scored-kind structures over the register (the register itself earned nothing either way).

### M7 -- `tt06__tt_um_SJ` `DUT.U10.counter` (counter, 2 flops, tier C_clean)

PE.sv: next_counter = calculating_RS ? counter + 1 : 0 -- a 2-bit counter enabled by the FSM flag calculating_RS, which falls when counter == 3. The recognizer returned the 2-flop counter counter4 (down by 1, modulus 3; refused by the harness, bucket 'hold': control.hold not claimed) over counter bit 0 and the flop the truth maps to DUT.U10.calculating_RS, and left counter bit 1 as the 1-bit flag w55; IoU 0.33 with the register and 0.50 with the flag, so it matched neither. The truth's mapping of that calculating_RS flop is z3-refuted and mismatches simulation in every PE (Tier A): the netlist flop does not compute RTL calculating_RS. The counter register itself is Tier C.

* Harness: every scored-kind structure over it was REFUSED by the harness -- `counter4` (counter, 2 flops, IoU 0.333, refused: hold).
* Coverage: `w55` (flag) bits [1] IoU 0.500; `counter4` (counter) bits [0] IoU 0.333
* Truth looks wrong: no (register Tier C; the paired calculating_RS flop is Tier A)

### M7 -- `tt06__tt_um_SJ` `DUT.U2.counter` (counter, 2 flops, tier C_clean)

PE.sv: next_counter = calculating_RS ? counter + 1 : 0 -- a 2-bit counter enabled by the FSM flag calculating_RS, which falls when counter == 3. The recognizer returned the 2-flop counter counter3 (down by 1, modulus 3; refused by the harness, bucket 'hold': control.hold not claimed) over counter bit 0 and the flop the truth maps to DUT.U2.calculating_RS, and left counter bit 1 as the 1-bit flag w58; IoU 0.33 with the register and 0.50 with the flag, so it matched neither. The truth's mapping of that calculating_RS flop is z3-refuted and mismatches simulation in every PE (Tier A): the netlist flop does not compute RTL calculating_RS. The counter register itself is Tier C.

* Harness: every scored-kind structure over it was REFUSED by the harness -- `counter3` (counter, 2 flops, IoU 0.333, refused: hold).
* Coverage: `w58` (flag) bits [1] IoU 0.500; `counter3` (counter) bits [0] IoU 0.333
* Truth looks wrong: no (register Tier C; the paired calculating_RS flop is Tier A)

### M7 -- `tt06__tt_um_SJ` `DUT.U3.counter` (counter, 2 flops, tier C_clean)

PE.sv: next_counter = calculating_RS ? counter + 1 : 0 -- a 2-bit counter enabled by the FSM flag calculating_RS, which falls when counter == 3. The recognizer returned the 2-flop counter counter9 (down by 1, modulus 3; refused by the harness, bucket 'hold': control.hold not claimed) over counter bit 0 and the flop the truth maps to DUT.U3.calculating_RS, and left counter bit 1 as the 1-bit flag w50; IoU 0.33 with the register and 0.50 with the flag, so it matched neither. The truth's mapping of that calculating_RS flop is z3-refuted and mismatches simulation in every PE (Tier A): the netlist flop does not compute RTL calculating_RS. The counter register itself is Tier C.

* Harness: every scored-kind structure over it was REFUSED by the harness -- `counter9` (counter, 2 flops, IoU 0.333, refused: hold).
* Coverage: `w50` (flag) bits [1] IoU 0.500; `counter9` (counter) bits [0] IoU 0.333
* Truth looks wrong: no (register Tier C; the paired calculating_RS flop is Tier A)

### M2a -- `tt06__tt_um_SJ` `DUT.U4.counter` (counter, 2 flops, tier C_clean)

The same PE module as the seven M7 instances; here both counter flops were emitted as one 2-flop data_register (w37) at IoU 1.00 -- extent right, kind unscored, so the harness never checked it. No scored-kind structure touches the register.

* Harness: no scored-kind structure touches it: the harness never adjudicated these flops.
* Coverage: `w37` (data_register) bits [0-1] IoU 1.000
* Truth looks wrong: no

### M7 -- `tt06__tt_um_SJ` `DUT.U5.counter` (counter, 2 flops, tier C_clean)

PE.sv: next_counter = calculating_RS ? counter + 1 : 0 -- a 2-bit counter enabled by the FSM flag calculating_RS, which falls when counter == 3. The recognizer returned the 2-flop counter counter7 (down by 1, modulus 3; refused by the harness, bucket 'hold': control.hold not claimed) over counter bit 0 and the flop the truth maps to DUT.U5.calculating_RS, and left counter bit 1 as the 1-bit flag w36; IoU 0.33 with the register and 0.50 with the flag, so it matched neither. The truth's mapping of that calculating_RS flop is z3-refuted and mismatches simulation in every PE (Tier A): the netlist flop does not compute RTL calculating_RS. The counter register itself is Tier C.

* Harness: every scored-kind structure over it was REFUSED by the harness -- `counter7` (counter, 2 flops, IoU 0.333, refused: hold).
* Coverage: `w36` (flag) bits [1] IoU 0.500; `counter7` (counter) bits [0] IoU 0.333
* Truth looks wrong: no (register Tier C; the paired calculating_RS flop is Tier A)

### M2a -- `tt06__tt_um_SJ` `DUT.U6.counter` (counter, 2 flops, tier C_clean)

The same PE module as the seven M7 instances; here both counter flops were emitted as one 2-flop data_register (w54) at IoU 1.00 -- extent right, kind unscored, so the harness never checked it. No scored-kind structure touches the register.

* Harness: no scored-kind structure touches it: the harness never adjudicated these flops.
* Coverage: `w54` (data_register) bits [0-1] IoU 1.000
* Truth looks wrong: no

### M7 -- `tt06__tt_um_SJ` `DUT.U7.counter` (counter, 2 flops, tier C_clean)

PE.sv: next_counter = calculating_RS ? counter + 1 : 0 -- a 2-bit counter enabled by the FSM flag calculating_RS, which falls when counter == 3. The recognizer returned the 2-flop counter counter5 (down by 1, modulus 3; refused by the harness, bucket 'hold': control.hold not claimed) over counter bit 0 and the flop the truth maps to DUT.U7.calculating_RS, and left counter bit 1 as the 1-bit flag w38; IoU 0.33 with the register and 0.50 with the flag, so it matched neither. The truth's mapping of that calculating_RS flop is z3-refuted and mismatches simulation in every PE (Tier A): the netlist flop does not compute RTL calculating_RS. The counter register itself is Tier C.

* Harness: every scored-kind structure over it was REFUSED by the harness -- `counter5` (counter, 2 flops, IoU 0.333, refused: hold).
* Coverage: `w38` (flag) bits [1] IoU 0.500; `counter5` (counter) bits [0] IoU 0.333
* Truth looks wrong: no (register Tier C; the paired calculating_RS flop is Tier A)

### M7 -- `tt06__tt_um_SJ` `DUT.U8.counter` (counter, 2 flops, tier C_clean)

PE.sv: next_counter = calculating_RS ? counter + 1 : 0 -- a 2-bit counter enabled by the FSM flag calculating_RS, which falls when counter == 3. The recognizer returned the 2-flop counter counter10 (down by 1, modulus 3; refused by the harness, bucket 'hold': control.hold not claimed) over counter bit 0 and the flop the truth maps to DUT.U8.calculating_RS, and left counter bit 1 as the 1-bit flag w59; IoU 0.33 with the register and 0.50 with the flag, so it matched neither. The truth's mapping of that calculating_RS flop is z3-refuted and mismatches simulation in every PE (Tier A): the netlist flop does not compute RTL calculating_RS. The counter register itself is Tier C.

* Harness: every scored-kind structure over it was REFUSED by the harness -- `counter10` (counter, 2 flops, IoU 0.333, refused: hold).
* Coverage: `w59` (flag) bits [1] IoU 0.500; `counter10` (counter) bits [0] IoU 0.333
* Truth looks wrong: no (register Tier C; the paired calculating_RS flop is Tier A)

### M7 -- `tt06__tt_um_SJ` `DUT.U9.counter` (counter, 2 flops, tier C_clean)

PE.sv: next_counter = calculating_RS ? counter + 1 : 0 -- a 2-bit counter enabled by the FSM flag calculating_RS, which falls when counter == 3. The recognizer returned the 2-flop counter counter8 (down by 1, modulus 3; refused by the harness, bucket 'hold': control.hold not claimed) over counter bit 0 and the flop the truth maps to DUT.U9.calculating_RS, and left counter bit 1 as the 1-bit flag w10; IoU 0.33 with the register and 0.50 with the flag, so it matched neither. The truth's mapping of that calculating_RS flop is z3-refuted and mismatches simulation in every PE (Tier A): the netlist flop does not compute RTL calculating_RS. The counter register itself is Tier C.

* Harness: every scored-kind structure over it was REFUSED by the harness -- `counter8` (counter, 2 flops, IoU 0.333, refused: hold).
* Coverage: `w10` (flag) bits [1] IoU 0.500; `counter8` (counter) bits [0] IoU 0.333
* Truth looks wrong: no (register Tier C; the paired calculating_RS flop is Tier A)

### M6b -- `tt06__tt_um_SJ` `DUT.U1.PEStartEN` (shift_register, 2 flops, tier A_contradicted)

topLevelControl.sv: nextPEStartEN[1] = PEStartEN[0], nextPEStartEN[0] = 1'b1 or an OR of PEReadNaive -- a 2-stage shift. verify.py SHIFT_MIN_DEPTH = 3 (and params.py SHIFT_MIN_DEPTH = 3, 'depth 2 is a transfer relation'), so no shift_register structure can be emitted or verified; the two flops came back as 1-bit flags (w52, w53). Both mapped bits are z3-refuted and mismatch simulation (Tier A).

* Harness: no scored-kind structure touches it: the harness never adjudicated these flops.
* Coverage: `w52` (flag) bits [0] IoU 0.500; `w53` (flag) bits [1] IoU 0.500
* Truth looks wrong: convention conflict (and Tier A) (R-D7)

### M1 -- `ttsky25b__tt_um_yorimichi_kittscanner` `i_kitt_scan_core.prescaler` (counter, 21 flops, tier C_clean)

kitt_scan_core.v: prescaler counts up by 1 and wraps at a terminal count chosen by the captured SPEED flop (NUM_NORM-1 = 1,499,999 or NUM_FAST-1 = 999,999), and is cleared whenever psc_enable is low -- a wrap that is neither a power of two nor fixed. The recognizer returned two harness-VERIFIED counting sub-words, counter1 (truth bits 4-12, modulus 512) and counter3 (bits 15-19, modulus 32), and its own relation record links them (type cascade, lower counter1, upper counter3); bits 1-3 came back as a data_register and bits 0, 13, 14 and 20 as flags. Best IoU 0.43.

* Harness: a scored-kind structure over it was harness-VERIFIED -- `counter1` (counter, 9 flops, IoU 0.429, VERIFIED); `counter3` (counter, 5 flops, IoU 0.238, VERIFIED).
* Coverage: `counter1` (counter) bits [4-12] IoU 0.429; `counter3` (counter) bits [15-19] IoU 0.238; `w13` (data_register) bits [1-3] IoU 0.143; `w2` (flag) bits [0] IoU 0.048; `w7` (flag) bits [14] IoU 0.048; `w12` (flag) bits [13] IoU 0.048; `w14` (flag) bits [20] IoU 0.048
* Truth looks wrong: no

### M2b -- `ttsky25b__tt_um_yorimichi_kittscanner` `i_kitt_scan_core.state` (counter, 6 flops, tier C_clean)

kitt_scan_core.v: the 6-bit FSM state register; next_state is state + 1 through the scan sequences and a constant state code elsewhere, advancing only on psc_ovf and forced to IDLE when ENA is low. The recognizer emitted a 2-flop data_register (bits 4-5) and four flags; no scored-kind structure touches it.

* Harness: no scored-kind structure touches it: the harness never adjudicated these flops.
* Coverage: `w6` (data_register) bits [4-5] IoU 0.333; `w11` (flag) bits [2] IoU 0.167; `w16` (flag) bits [1] IoU 0.167; `w20` (flag) bits [3] IoU 0.167; `w21` (flag) bits [0] IoU 0.167
* Truth looks wrong: arguable: an FSM with constant jumps labelled counter, with a modulus (2) the RTL contradicts (R-D5)

### M8 -- `ttsky25b__tt_um_yorimichi_kittscanner` `i_kitt_scan_core.pre_lvout` (shift_register, 8 flops, tier C_clean)

kitt_scan_core.v: pre_lvout shifts right ({1'b0, pre_lvout[7:1]}) in some scan states, left ({pre_lvout[6:0], 1'b0}) in others, moves its two halves in opposite directions in mode 1 (HEAD_MD1+2..4 and HEAD_MD1+7) and loads constants elsewhere; pwmsel[0..7] (3 bits each) shifts word-wise alongside it. The one shift structure over these flops, shift_register#1, follows ONE of those copy relations -- the HEAD_MD1+7 step, whose two middle heads load constants (proof notes: head_kind 'const') -- so it has 8 lanes of depth 4: pre_lvout[3]->[2]->[1]->[0], pre_lvout[4]->[5]->[6]->[7] and six half-lanes through pwmsel bits. The truth register's 8 flops are 2 of its 8 lanes (IoU 0.25); the harness refused it ('hold' not claimed). The truth's reading is one lane of depth 8 toward LSB.

* Harness: every scored-kind structure over it was REFUSED by the harness -- `shift_register#1` (shift_register, 32 flops, IoU 0.250, refused: hold).
* Coverage: `shift_register#1` (shift_register) bits [0-7] IoU 0.250
* Truth looks wrong: no (a bidirectional shift; the truth picked the right-shift reading)

### M1 -- `tt05__tt_um_digital_clock_sellicott` `clock_inst.shift_out_inst.shift_out_inst.transfer_state` (counter, 97 flops, tier C_clean)

shift_register.v: reg [2*WIDTH:0] transfer_state is 97 bits for WIDTH = 48 (the 48-flop serial_data register), counts up by 1 under TRANSFER & i_clk_stb and is cleared in IDLE; the FSM leaves TRANSFER once transfer_state >= 2*WIDTH-1 = 95, so in operation only the low 7 bits ever toggle and bits 7-96 never leave 0. The recognizer returned counter0 over bits 1-37 (harness-VERIFIED, modulus 2^37) and counter4 over bits 84-95 (12 flops = params.py EXHAUSTIVE_WIDTH; refused, 'vacuous' test (a)), linked as a cascade (lower counter0, upper counter4); bits 38-83 came back as one 46-flop data_register and bits 0 and 96 as flags. Best IoU 0.47 (the data_register), 0.38 for counter0. The same family as B1's 32-bit integers whose top bits never reach their toggle point (docs/S3.md 8.1).

* Harness: a scored-kind structure over it was harness-VERIFIED -- `counter0` (counter, 37 flops, IoU 0.381, VERIFIED); `counter4` (counter, 12 flops, IoU 0.124, refused: vacuous).
* Coverage: `w0` (data_register) bits [38-83] IoU 0.474; `counter0` (counter) bits [1-37] IoU 0.381; `counter4` (counter) bits [84-95] IoU 0.124; `w6` (flag) bits [96] IoU 0.010; `w23` (flag) bits [0] IoU 0.010
* Truth looks wrong: no (97 bits is the RTL declaration; most of them are unreachable)

### M3b -- `tt05__tt_um_digital_clock_sellicott` `clock_inst.mode0_db_inst.samples` (shift_register, 5 flops, tier C_clean)

button_debounce.v: samples <= {samples[NUM_SAMPLES-2:0], sample_pipe} -- a 5-deep shift register per debounced button; the mode0 and mode1 instances share clock, enable and reset. The recognizer joined them into ONE 2-lane x depth-5 shift_register (shift_register#2, harness-VERIFIED, lanes_unordered) at IoU exactly 0.50 with each register, so strict scoring credits neither. The truth itself declares the pair a copy_lanes unit ('S3's lane rule joins such lanes into one structure'), which is an item in lenient mode only: there both registers are found and verified (numbers.json notes).

* Harness: a scored-kind structure over it was harness-VERIFIED -- `shift_register#2` (shift_register, 10 flops, IoU 0.500, VERIFIED).
* Coverage: `shift_register#2` (shift_register) bits [0-4] IoU 0.500
* Truth looks wrong: no

### M3b -- `tt05__tt_um_digital_clock_sellicott` `clock_inst.mode1_db_inst.samples` (shift_register, 5 flops, tier C_clean)

button_debounce.v: samples <= {samples[NUM_SAMPLES-2:0], sample_pipe} -- a 5-deep shift register per debounced button; the mode0 and mode1 instances share clock, enable and reset. The recognizer joined them into ONE 2-lane x depth-5 shift_register (shift_register#2, harness-VERIFIED, lanes_unordered) at IoU exactly 0.50 with each register, so strict scoring credits neither. The truth itself declares the pair a copy_lanes unit ('S3's lane rule joins such lanes into one structure'), which is an item in lenient mode only: there both registers are found and verified (numbers.json notes).

* Harness: a scored-kind structure over it was harness-VERIFIED -- `shift_register#2` (shift_register, 10 flops, IoU 0.500, VERIFIED).
* Coverage: `shift_register#2` (shift_register) bits [0-4] IoU 0.500
* Truth looks wrong: no

### M6 -- `tt05__tt_um_nickjhay_processor` `sys_in1_buffer` (synchronizer, 8 flops, tier C_clean)

main.v: sys_in1_buffer <= ui_in on the cycles sys_in1_next is 1 and 8'b0 on the others -- an 8-bit input capture register the truth labels a synchronizer of one stage (params.stages = 1). verify.py SYNC_MIN_STAGES = 2, so it can never be reported or verified as labelled. The recognizer placed its 8 flops as stage 0 of the 8-lane x depth-8 shift structure shift_register#0 that runs down the systolic array's out1 chain (IoU 0.125; refused, 'hold' not claimed; see F6).

* Harness: every scored-kind structure over it was REFUSED by the harness -- `shift_register#0` (shift_register, 64 flops, IoU 0.125, refused: hold).
* Coverage: `shift_register#0` (shift_register) bits [0-7] IoU 0.125
* Truth looks wrong: convention conflict (R-D2)

### M2b -- `ttsky26a__tt_um_parakeet` `race_stage` (counter, 3 flops, tier C_clean)

project.v: 3-bit stage counter, +1 modulo 5, stepping only on frame_tick & stage_done (stage_done = stage_timer == 8'hFF) and cleared by gp_start_held. Bits 1-2 came back as a data_register (w7, IoU 0.67: the unaccepted-kind match) and bit 0 as a flag (w6); no scored-kind structure touches it.

* Harness: no scored-kind structure touches it: the harness never adjudicated these flops.
* Coverage: `w7` (data_register) bits [1-2] IoU 0.667; `w6` (flag) bits [0] IoU 0.333
* Truth looks wrong: no

### M2b -- `ttsky26a__tt_um_parakeet` `speed` (counter, 4 flops, tier C_clean)

project.v: 4-bit saturating up/down counter (up on gp_a_held unless 4'hF, down otherwise unless 0, forced to 0 when not driving), stepping on frame_tick. Two 2-flop data_registers (bits 0-1, 2-3; best IoU 0.50); no scored-kind structure touches it.

* Harness: no scored-kind structure touches it: the harness never adjudicated these flops.
* Coverage: `w3` (data_register) bits [0-1] IoU 0.500; `w4` (data_register) bits [2-3] IoU 0.500
* Truth looks wrong: no

### M2b -- `ttsky26a__tt_um_parakeet` `stage_timer` (counter, 8 flops, tier C_clean)

project.v: 8-bit counter stepping on frame_tick, cleared at 8'hFF (stage_done) and by gp_start_held. Bits 1-6 came back as one data_register (w1, IoU 0.75), bits 0 and 7 as flags; no scored-kind structure touches it.

* Harness: no scored-kind structure touches it: the harness never adjudicated these flops.
* Coverage: `w1` (data_register) bits [1-6] IoU 0.750; `w11` (flag) bits [7] IoU 0.125; `w14` (flag) bits [0] IoU 0.125
* Truth looks wrong: no

### M1 -- `ttcad25a__tt_um_space_invaders_game` `pb_y` (counter, 10 flops, tier C_clean)

project.v: pb_y is loaded with SHOOTER_Y - 25 when a bullet spawns and steps down by 25 once per frame while pb_y > 130. The recognizer split it at the borrow out of bit 4: counter4 over bits 0-4 as an up-counter by 7 modulo 32 (-25 = +7 mod 32; refused, 'hold' not claimed) and counter6 over bits 5-8 as a down-counter by 1 modulo 16 (harness-VERIFIED); bit 9 is a flag. counter4 sits at IoU exactly 0.50 and score.py needs IoU > 0.5 -- a failure by equality, as two of B1's five M1s were.

* Harness: a scored-kind structure over it was harness-VERIFIED -- `counter4` (counter, 5 flops, IoU 0.500, refused: hold); `counter6` (counter, 4 flops, IoU 0.400, VERIFIED).
* Coverage: `counter4` (counter) bits [0-4] IoU 0.500; `counter6` (counter) bits [5-8] IoU 0.400; `w30` (flag) bits [9] IoU 0.100
* Truth looks wrong: no

### M2b -- `ttcad25a__tt_um_space_invaders_game` `score` (counter, 9 flops, tier A_contradicted)

project.v: score <= score + 10, + 20 or + 30 at 40 hit sites -- no single constant step (the truth's params.step is null). A 7-flop data_register (w4: bits 0 and 2-7, IoU 0.78) and two flags; no scored-kind structure touches it. Every mapped bit of the truth register is z3-refuted (Tier A) and RTL bits 0 and 1 share one netlist flop.

* Harness: no scored-kind structure touches it: the harness never adjudicated these flops.
* Coverage: `w4` (data_register) bits [0,2-7] IoU 0.778; `w6` (flag) bits [9] IoU 0.111; `w40` (flag) bits [8] IoU 0.111
* Truth looks wrong: arguable (weak): a multi-constant adder no constant-step template fits; Tier A (R-D6)

### M1 -- `ttcad25a__tt_um_space_invaders_game` `sync_gen.vpos` (counter, 10 flops, tier C_clean)

vga_sync_generator: vpos counts 0..524 (modulus 525). The recognizer returned counter3 over bits 0-4 (harness-VERIFIED, modulus 32; linked as a cascade above counter0, the found hpos) and left bits 5-9 in a 2-flop data_register (bits 6, 8) and three flags. counter3 is at IoU exactly 0.50 with vpos (equality again). The truth maps vpos bits 0-3 to flops Yosys merged with barrier1.bar_rom.row_index[0..3] (bits[].how = 'merged') and lists the same four flops as the 'other' register sync_gen.vpos__retimed, so the one-to-one matcher paired counter3 with that register instead (IoU 0.80, kind refused; F3b). The same RTL shape was found exactly on ttsky26a__tt_um_parakeet (vga_sync_gen.vpos: counter0, IoU 1.00, harness-VERIFIED), whose truth marks one vpos bit merged; this report does not claim the merge is the whole difference.

* Harness: a scored-kind structure over it was harness-VERIFIED -- `counter3` (counter, 5 flops, IoU 0.500, VERIFIED).
* Coverage: `counter3` (counter) bits [0-4] IoU 0.500; `w25` (data_register) bits [6,8] IoU 0.200; `w9` (flag) bits [9] IoU 0.100; `w28` (flag) bits [5] IoU 0.100; `w29` (flag) bits [7] IoU 0.100
* Truth looks wrong: no

### M4a -- `ttcad25a__tt_um_space_invaders_game` `lfsr` (shift_register, 8 flops, tier C_clean)

project.v: lfsr <= {lfsr[6:0], lfsr_feedback}, lfsr_feedback = lfsr[7]^lfsr[5]^lfsr[4]^lfsr[3] -- an author-named Fibonacci LFSR. shift.py recorded one feedback head over 7 stages with verdict 'affine' (stage stats feedback_affine 2: the one head recorded twice), so the lane went to lfsr.py, which admitted one lfsr_crc (lfsr0: form fibonacci, poly 285, k_steps 1, 0 inputs), harness-VERIFIED at IoU 1.00 over exactly the truth register's flops -- B1's M4a, exactly.

* Harness: a scored-kind structure over it was harness-VERIFIED -- `lfsr0` (lfsr_crc, 8 flops, IoU 1.000, VERIFIED).
* Coverage: `lfsr0` (lfsr_crc) bits [0-7] IoU 1.000
* Truth looks wrong: yes (a Fibonacci LFSR labelled shift_register) (R-D1)

### M6 -- `ttcad25a__tt_um_space_invaders_game` `prev_button0` (synchronizer, 1 flop, tier C_clean)

project.v: prev_button0 <= ui_in[0], an edge detector's previous-value flop ('Capture previous button states for edge-detection'). The truth's rule 3 labels a register whose D is an input pin a synchronizer of ONE stage (params.stages = 1); verify.py SYNC_MIN_STAGES = 2 and shift.py emits a synchronizer only over stages 1-2 of an input copy path, so it can never be reported or verified as labelled. The recognizer emitted the flop as the 1-bit flag w43 (IoU 1.00).

* Harness: no scored-kind structure touches it: the harness never adjudicated these flops.
* Coverage: `w43` (flag) bits [0] IoU 1.000
* Truth looks wrong: convention conflict; the RTL presents it as an edge detector (R-D2)

### M6 -- `ttcad25a__tt_um_space_invaders_game` `prev_button1` (synchronizer, 1 flop, tier C_clean)

project.v: prev_button1 <= ui_in[1], an edge detector's previous-value flop ('Capture previous button states for edge-detection'). The truth's rule 3 labels a register whose D is an input pin a synchronizer of ONE stage (params.stages = 1); verify.py SYNC_MIN_STAGES = 2 and shift.py emits a synchronizer only over stages 1-2 of an input copy path, so it can never be reported or verified as labelled. The recognizer emitted the flop as the 1-bit flag w39 (IoU 1.00).

* Harness: no scored-kind structure touches it: the harness never adjudicated these flops.
* Coverage: `w39` (flag) bits [0] IoU 1.000
* Truth looks wrong: convention conflict; the RTL presents it as an edge detector (R-D2)

### M6 -- `ttcad25a__tt_um_space_invaders_game` `prev_button2` (synchronizer, 1 flop, tier C_clean)

project.v: prev_button2 <= ui_in[2], an edge detector's previous-value flop ('Capture previous button states for edge-detection'). The truth's rule 3 labels a register whose D is an input pin a synchronizer of ONE stage (params.stages = 1); verify.py SYNC_MIN_STAGES = 2 and shift.py emits a synchronizer only over stages 1-2 of an input copy path, so it can never be reported or verified as labelled. The recognizer emitted the flop as the 1-bit flag w8 (IoU 1.00).

* Harness: no scored-kind structure touches it: the harness never adjudicated these flops.
* Coverage: `w8` (flag) bits [0] IoU 1.000
* Truth looks wrong: convention conflict; the RTL presents it as an edge detector (R-D2)

## 5. Every false positive

### F2 -- `ttsky26b__tt_um_tiny_8bit_cpu` `counter0` (counter, 2 flops, refused: hold)

registers.v: pc_q <= pc_d under pc_we, where the datapath's pc_d is pc_q plus a multi-bit value (the truth's rule 'D = Q + a multi-bit variable'). A 2-flop up/down counter (modulus 4) over pc_q bits 3-4; IoU 0.40; refused ('hold' not claimed). None of its flops was dropped: the design's 72 unmapped flops fell only in structures of unscored kinds.

* Overlaps (1 truth registers): `u_cpu_top.u_datapath.u_registers.pc_q` (accumulator, tier C_clean) bits [3-4] IoU 0.400
* Truth looks wrong: no

### F5 -- `tt06__tt_um_SJ` `shift_register#0` (shift_register, 96 flops, refused: hold)

PE.sv: if (read_new_filter_val) filter_spad[i] <= filter_spad[i-1] (i = 2, 1), filter_spad[0] <= filter_i, and the same for ifmap_spad -- 8-bit x 3-entry word-wise shift registers the truth labels data_register per entry (all 54 spad entries Tier A). Every one of the structure's 32 lanes is exactly spad[0][b] -> spad[1][b] -> spad[2][b] of one PE; 4 spads of 4 different PEs are joined because they share a shift enable (lanes_unordered). Refused ('hold' not claimed). It overlaps 12 truth data_registers at IoU 0.08 each.

* Overlaps (12 truth registers): `DUT.U9.filter_spad[2]` (data_register, tier A_contradicted) bits [0-7] IoU 0.083; `DUT.U3.filter_spad[0]` (data_register, tier A_contradicted) bits [0-7] IoU 0.083; `DUT.U9.filter_spad[1]` (data_register, tier A_contradicted) bits [0-7] IoU 0.083
* Truth looks wrong: yes (word-wise shift registers labelled data_register; Tier A) (R-D3)

### F5 -- `tt06__tt_um_SJ` `shift_register#1` (shift_register, 96 flops, refused: hold)

PE.sv: if (read_new_filter_val) filter_spad[i] <= filter_spad[i-1] (i = 2, 1), filter_spad[0] <= filter_i, and the same for ifmap_spad -- 8-bit x 3-entry word-wise shift registers the truth labels data_register per entry (all 54 spad entries Tier A). Every one of the structure's 32 lanes is exactly spad[0][b] -> spad[1][b] -> spad[2][b] of one PE; 4 spads of 4 different PEs are joined because they share a shift enable (lanes_unordered). Refused ('hold' not claimed). It overlaps 12 truth data_registers at IoU 0.08 each.

* Overlaps (12 truth registers): `DUT.U2.ifmap_spad[0]` (data_register, tier A_contradicted) bits [0-7] IoU 0.083; `DUT.U4.filter_spad[1]` (data_register, tier A_contradicted) bits [0-7] IoU 0.083; `DUT.U4.filter_spad[2]` (data_register, tier A_contradicted) bits [0-7] IoU 0.083
* Truth looks wrong: yes (word-wise shift registers labelled data_register; Tier A) (R-D3)

### F5 -- `tt06__tt_um_SJ` `shift_register#2` (shift_register, 96 flops, refused: hold)

PE.sv: if (read_new_filter_val) filter_spad[i] <= filter_spad[i-1] (i = 2, 1), filter_spad[0] <= filter_i, and the same for ifmap_spad -- 8-bit x 3-entry word-wise shift registers the truth labels data_register per entry (all 54 spad entries Tier A). Every one of the structure's 32 lanes is exactly spad[0][b] -> spad[1][b] -> spad[2][b] of one PE; 4 spads of 4 different PEs are joined because they share a shift enable (lanes_unordered). Refused ('hold' not claimed). It overlaps 12 truth data_registers at IoU 0.08 each.

* Overlaps (12 truth registers): `DUT.U8.filter_spad[2]` (data_register, tier A_contradicted) bits [0-7] IoU 0.083; `DUT.U7.ifmap_spad[0]` (data_register, tier A_contradicted) bits [0-7] IoU 0.083; `DUT.U5.filter_spad[2]` (data_register, tier A_contradicted) bits [0-7] IoU 0.083
* Truth looks wrong: yes (word-wise shift registers labelled data_register; Tier A) (R-D3)

### F7 -- `tt06__tt_um_SJ` `counter3` (counter, 2 flops, refused: hold)

The structure side of DUT.U2.counter's M7 miss: a 2-flop down-counter (modulus 3) over DUT.U2.counter bit 0 and the (Tier A) DUT.U2.calculating_RS flop; IoU 0.33 / 0.50; refused ('hold' not claimed).

* Overlaps (2 truth registers): `DUT.U2.counter` (counter, tier C_clean) bits [0] IoU 0.333; `DUT.U2.calculating_RS` (flag, tier A_contradicted) bits [0] IoU 0.500
* Truth looks wrong: no (the flag's mapping is refuted, Tier A)

### F7 -- `tt06__tt_um_SJ` `counter4` (counter, 2 flops, refused: hold)

The structure side of DUT.U10.counter's M7 miss: a 2-flop down-counter (modulus 3) over DUT.U10.counter bit 0 and the (Tier A) DUT.U10.calculating_RS flop; IoU 0.33 / 0.50; refused ('hold' not claimed).

* Overlaps (2 truth registers): `DUT.U10.calculating_RS` (flag, tier A_contradicted) bits [0] IoU 0.500; `DUT.U10.counter` (counter, tier C_clean) bits [0] IoU 0.333
* Truth looks wrong: no (the flag's mapping is refuted, Tier A)

### F7 -- `tt06__tt_um_SJ` `counter5` (counter, 2 flops, refused: hold)

The structure side of DUT.U7.counter's M7 miss: a 2-flop down-counter (modulus 3) over DUT.U7.counter bit 0 and the (Tier A) DUT.U7.calculating_RS flop; IoU 0.33 / 0.50; refused ('hold' not claimed).

* Overlaps (2 truth registers): `DUT.U7.calculating_RS` (flag, tier A_contradicted) bits [0] IoU 0.500; `DUT.U7.counter` (counter, tier C_clean) bits [0] IoU 0.333
* Truth looks wrong: no (the flag's mapping is refuted, Tier A)

### F2 -- `tt06__tt_um_SJ` `counter6` (counter, 2 flops, refused: hold)

PE.sv: psum_spad <= adder_input + psum_spad (the truth's accumulator; Tier A). A 2-flop down-counter (modulus 4) over DUT.U7.psum_spad bits 0-1; IoU 0.20; refused ('hold' not claimed); recorded as a cascade above counter5.

* Overlaps (1 truth registers): `DUT.U7.psum_spad` (accumulator, tier A_contradicted) bits [0-1] IoU 0.200
* Truth looks wrong: no

### F7 -- `tt06__tt_um_SJ` `counter7` (counter, 2 flops, refused: hold)

The structure side of DUT.U5.counter's M7 miss: a 2-flop down-counter (modulus 3) over DUT.U5.counter bit 0 and the (Tier A) DUT.U5.calculating_RS flop; IoU 0.33 / 0.50; refused ('hold' not claimed).

* Overlaps (2 truth registers): `DUT.U5.calculating_RS` (flag, tier A_contradicted) bits [0] IoU 0.500; `DUT.U5.counter` (counter, tier C_clean) bits [0] IoU 0.333
* Truth looks wrong: no (the flag's mapping is refuted, Tier A)

### F7 -- `tt06__tt_um_SJ` `counter8` (counter, 2 flops, refused: hold)

The structure side of DUT.U9.counter's M7 miss: a 2-flop down-counter (modulus 3) over DUT.U9.counter bit 0 and the (Tier A) DUT.U9.calculating_RS flop; IoU 0.33 / 0.50; refused ('hold' not claimed).

* Overlaps (2 truth registers): `DUT.U9.counter` (counter, tier C_clean) bits [0] IoU 0.333; `DUT.U9.calculating_RS` (flag, tier A_contradicted) bits [0] IoU 0.500
* Truth looks wrong: no (the flag's mapping is refuted, Tier A)

### F7 -- `tt06__tt_um_SJ` `counter9` (counter, 2 flops, refused: hold)

The structure side of DUT.U3.counter's M7 miss: a 2-flop down-counter (modulus 3) over DUT.U3.counter bit 0 and the (Tier A) DUT.U3.calculating_RS flop; IoU 0.33 / 0.50; refused ('hold' not claimed).

* Overlaps (2 truth registers): `DUT.U3.calculating_RS` (flag, tier A_contradicted) bits [0] IoU 0.500; `DUT.U3.counter` (counter, tier C_clean) bits [0] IoU 0.333
* Truth looks wrong: no (the flag's mapping is refuted, Tier A)

### F7 -- `tt06__tt_um_SJ` `counter10` (counter, 2 flops, refused: hold)

The structure side of DUT.U8.counter's M7 miss: a 2-flop down-counter (modulus 3) over DUT.U8.counter bit 0 and the (Tier A) DUT.U8.calculating_RS flop; IoU 0.33 / 0.50; refused ('hold' not claimed).

* Overlaps (2 truth registers): `DUT.U8.counter` (counter, tier C_clean) bits [0] IoU 0.333; `DUT.U8.calculating_RS` (flag, tier A_contradicted) bits [0] IoU 0.500
* Truth looks wrong: no (the flag's mapping is refuted, Tier A)

### F5 -- `ttsky25b__tt_um_yorimichi_kittscanner` `shift_register#1` (shift_register, 32 flops, refused: hold)

The structure of pre_lvout's M8 miss: 8 lanes x depth 4 (the HEAD_MD1+7 copy step) through pre_lvout (truth shift_register, 8 flops) and pwmsel[0..7] (truth data_registers, 24 flops; next_pwmsel[i] = pwmsel[i+/-1] is a word-wise shift the truth does not name). Refused ('hold' not claimed); IoU 0.25 with pre_lvout, 0.09 with each pwmsel entry.

* Overlaps (9 truth registers): `i_kitt_scan_core.pre_lvout` (shift_register, tier C_clean) bits [0-7] IoU 0.250; `i_kitt_scan_core.pwmsel[7]` (data_register, tier C_clean) bits [0-2] IoU 0.094; `i_kitt_scan_core.pwmsel[0]` (data_register, tier C_clean) bits [0-2] IoU 0.094
* Truth looks wrong: partly (pwmsel is a word-wise shift labelled data_register) (R-D3)

### F3 -- `ttsky25b__tt_um_yorimichi_kittscanner` `counter1` (counter, 9 flops, harness-VERIFIED)

The structure side of the prescaler's M1: a harness-VERIFIED counting sub-word (bits 4-12, modulus 512) of the 21-bit truth counter; IoU 0.43.

* Overlaps (1 truth registers): `i_kitt_scan_core.prescaler` (counter, tier C_clean) bits [4-12] IoU 0.429
* Truth looks wrong: no

### F3 -- `ttsky25b__tt_um_yorimichi_kittscanner` `counter3` (counter, 5 flops, harness-VERIFIED)

The structure side of the prescaler's M1: a harness-VERIFIED counting sub-word (bits 15-19, modulus 32), cascaded above counter1; IoU 0.24.

* Overlaps (1 truth registers): `i_kitt_scan_core.prescaler` (counter, tier C_clean) bits [15-19] IoU 0.238
* Truth looks wrong: no

### F3 -- `ttsky25b__tt_um_yorimichi_kittscanner` `counter4` (counter, 2 flops, harness-VERIFIED)

i_debouncer.prescaler (18-bit counter) is FOUND by counter0 (bits 0-11: 12 flops = EXHAUSTIVE_WIDTH, IoU 0.67, harness-VERIFIED); counter4 is a further harness-VERIFIED 2-bit sub-word over bits 16-17, linked as a cascade above counter0; IoU 0.11.

* Overlaps (1 truth registers): `i_debouncer.prescaler` (counter, tier C_clean) bits [16-17] IoU 0.111
* Truth looks wrong: no

### F8 -- `tt05__tt_um_digital_clock_sellicott` `shift_register#2` (shift_register, 10 flops, harness-VERIFIED)

The structure side of the mode0/mode1 samples M3b: harness-VERIFIED, 2 lanes x depth 5, IoU 0.50 with each truth register; credited to both in lenient mode through the truth's copy_lanes unit, to neither in strict mode.

* Overlaps (2 truth registers): `clock_inst.mode1_db_inst.samples` (shift_register, tier C_clean) bits [0-4] IoU 0.500; `clock_inst.mode0_db_inst.samples` (shift_register, tier C_clean) bits [0-4] IoU 0.500
* Truth looks wrong: no

### F6 -- `tt05__tt_um_digital_clock_sellicott` `shift_register#3` (shift_register, 3 flops, harness-VERIFIED)

reference_clk_stb.v: {refclk_pipe1, refclk_pipe0, refclk_ext} <= {refclk_pipe0, refclk_ext, i_refclk} under i_en -- the author's own 'clock domain crossing for the refclk signal'. Three 1-bit truth flags; the recognizer's 3-deep shift_register over them is harness-VERIFIED (under the contract a synchronizer may carry no condition, so i_en makes it a shift register). IoU 0.33 with each flag.

* Overlaps (3 truth registers): `clock_inst.refclk_gen_inst.refclk_pipe1` (flag, tier C_clean) bits [0] IoU 0.333; `clock_inst.refclk_gen_inst.refclk_pipe0` (flag, tier C_clean) bits [0] IoU 0.333; `clock_inst.refclk_gen_inst.refclk_ext` (flag, tier C_clean) bits [0] IoU 0.333
* Truth looks wrong: yes (a 3-stage enabled pipeline labelled three flags) (R-D4)

### F3 -- `tt05__tt_um_digital_clock_sellicott` `counter0` (counter, 37 flops, harness-VERIFIED)

The structure side of transfer_state's M1: a harness-VERIFIED 37-bit counting sub-word (bits 1-37) of the 97-bit truth counter; IoU 0.38.

* Overlaps (1 truth registers): `clock_inst.shift_out_inst.shift_out_inst.transfer_state` (counter, tier C_clean) bits [1-37] IoU 0.381
* Truth looks wrong: no

### F1 -- `tt05__tt_um_digital_clock_sellicott` `counter2` (counter, 20 flops, harness-VERIFIED)

load_divider.v: counter <= counter + incriment, incriment a 25-bit register loaded with i_incriment + 1 -- the truth's accumulator (rule 'D = Q + a multi-bit variable'). counter2 = bits 5-24, up by 1 modulo 2^20, harness-VERIFIED, matched the accumulator at IoU 0.80 and was refused credit on the kind: a constant-step counter proved on the upper lanes, whose count condition is the carry out of bits 0-4 -- B1's F1 reading.

* Overlaps (1 truth registers): `clock_inst.clock_gen_inst.timeset_div_inst.divider_inst.counter` (accumulator, tier C_clean) bits [5-24] IoU 0.800
* Truth looks wrong: no

### F3 -- `tt05__tt_um_digital_clock_sellicott` `counter4` (counter, 12 flops, refused: vacuous)

The structure side of transfer_state's M1: a 12-flop sub-word (bits 84-95, = EXHAUSTIVE_WIDTH), refused by the harness ('vacuous' test (a): the hold region is empty only once the opaque load case is conjoined); IoU 0.12.

* Overlaps (1 truth registers): `clock_inst.shift_out_inst.shift_out_inst.transfer_state` (counter, tier C_clean) bits [84-95] IoU 0.124
* Truth looks wrong: no

### F2 -- `tt05__tt_um_digital_clock_sellicott` `counter8` (counter, 5 flops, harness-VERIFIED)

The same accumulator's bits 0-4: up by 1 modulo 32 with a load case, harness-VERIFIED; IoU 0.20.

* Overlaps (1 truth registers): `clock_inst.clock_gen_inst.timeset_div_inst.divider_inst.counter` (accumulator, tier C_clean) bits [0-4] IoU 0.200
* Truth looks wrong: no

### F3 -- `tt05__tt_um_digital_clock_sellicott` `counter10` (counter, 3 flops, harness-VERIFIED)

sysclk_divider.v: counter <= counter + INCRIMENT with the constant 858 (the truth's step; bit 0 never toggles and has no netlist flop, Tier B). The register is FOUND by counter1 (bits 11-31, IoU 0.68, harness-VERIFIED with step 1 -- a certified step that disagrees with the truth's 858, listed in numbers.json's wrong parameters). The low bits of a +858 counter form modular sub-counters of their own; counter10 is bits 1-3 counting down by 3 modulo 8 (858 / 2 = 429 = 5 = -3 mod 8), harness-VERIFIED; IoU 0.10.

* Overlaps (1 truth registers): `clock_inst.clock_gen_inst.sysclk_div_inst.counter` (counter, tier B_narrowed) bits [1-3] IoU 0.097
* Truth looks wrong: no

### F3 -- `tt05__tt_um_digital_clock_sellicott` `counter11` (counter, 2 flops, harness-VERIFIED)

sysclk_divider.v: counter <= counter + INCRIMENT with the constant 858 (the truth's step; bit 0 never toggles and has no netlist flop, Tier B). The register is FOUND by counter1 (bits 11-31, IoU 0.68, harness-VERIFIED with step 1 -- a certified step that disagrees with the truth's 858, listed in numbers.json's wrong parameters). The low bits of a +858 counter form modular sub-counters of their own; counter11 is bits 5-6, down by 1 modulo 4 under a carry condition, harness-VERIFIED; IoU 0.06.

* Overlaps (1 truth registers): `clock_inst.clock_gen_inst.sysclk_div_inst.counter` (counter, tier B_narrowed) bits [5-6] IoU 0.065
* Truth looks wrong: no

### F3 -- `tt05__tt_um_digital_clock_sellicott` `counter13` (counter, 2 flops, harness-VERIFIED)

sysclk_divider.v: counter <= counter + INCRIMENT with the constant 858 (the truth's step; bit 0 never toggles and has no netlist flop, Tier B). The register is FOUND by counter1 (bits 11-31, IoU 0.68, harness-VERIFIED with step 1 -- a certified step that disagrees with the truth's 858, listed in numbers.json's wrong parameters). The low bits of a +858 counter form modular sub-counters of their own; counter13 is bits 8-9, down by 1 modulo 4 under a carry condition, harness-VERIFIED; IoU 0.06.

* Overlaps (1 truth registers): `clock_inst.clock_gen_inst.sysclk_div_inst.counter` (counter, tier B_narrowed) bits [8-9] IoU 0.065
* Truth looks wrong: no

### F6 -- `tt05__tt_um_nickjhay_processor` `shift_register#0` (shift_register, 64 flops, refused: hold)

main.v systolic_cell: out1 <= in1 under sys_in_valid (out1 <= in1 | acc on readout), and cell (i+1, j) reads out1 of cell (i, j) -- the author's comment: 'successive out1's will form shift registers'. Each out1 is a 1-bit RTL register the truth labels flag. The structure is 8 lanes x depth 8: sys_in1_buffer[j] -> out1 of cells (0..6, j). Refused ('hold' not claimed). IoU 0.125 with sys_in1_buffer (a truth synchronizer, R-D2), 0.016 with each out1 flag.

* Overlaps (57 truth registers): `sys_in1_buffer` (synchronizer, tier C_clean) bits [0-7] IoU 0.125; `sa.iloop[2].jloop[3].sxy.out1` (flag, tier C_clean) bits [0] IoU 0.016; `sa.iloop[6].jloop[3].sxy.out1` (flag, tier C_clean) bits [0] IoU 0.016
* Truth looks wrong: yes (a pipeline labelled one flag per stage) (R-D4)

### F6 -- `tt05__tt_um_nickjhay_processor` `shift_register#1` (shift_register, 56 flops, harness-VERIFIED)

main.v: the systolic out2 chain (out2 <= in2; cell (i, j+1) reads out2 of cell (i, j)): 8 lanes x depth 7 over 56 1-bit truth flags; harness-VERIFIED. IoU 0.018 with each flag.

* Overlaps (56 truth registers): `sa.iloop[4].jloop[6].sxy.out2` (flag, tier C_clean) bits [0] IoU 0.018; `sa.iloop[7].jloop[3].sxy.out2` (flag, tier C_clean) bits [0] IoU 0.018; `sa.iloop[7].jloop[4].sxy.out2` (flag, tier C_clean) bits [0] IoU 0.018
* Truth looks wrong: yes (a pipeline labelled one flag per stage) (R-D4)

### F3 -- `ttsky25b__tt_um_ieeeuoftasic_simproc` `counter4` (counter, 2 flops, harness-VERIFIED)

simproc_system.sv UART_RX: clkCount counts up to a run-time compare value derived from clk_per_bit (adjustable baud) and clears. The register is FOUND by counter0 (bits 0-6, IoU 0.70; refused, 'vacuous' test (a): a V2 found-but-unverified register); counter4 is a harness-VERIFIED 2-bit sub-word over bits 8-9; IoU 0.20.

* Overlaps (1 truth registers): `U1.UART1.UART_RX1.clkCount` (counter, tier C_clean) bits [8-9] IoU 0.200
* Truth looks wrong: no

### F2 -- `ttsky26a__tt_um_parakeet` `counter2` (counter, 2 flops, harness-VERIFIED)

project.v: road_z <= road_z + {8'd0, speed_eff} (the truth's accumulator; Tier A). counter2 = road_z bits 1-2, up by 1 modulo 4, harness-VERIFIED; IoU 0.29.

* Overlaps (1 truth registers): `road_z` (accumulator, tier A_contradicted) bits [1-2] IoU 0.286
* Truth looks wrong: no

### F3b -- `ttcad25a__tt_um_space_invaders_game` `counter3` (counter, 5 flops, harness-VERIFIED)

The structure side of sync_gen.vpos's M1: a harness-VERIFIED 5-bit sub-word (bits 0-4, modulus 32) of the mod-525 truth counter (IoU 0.50), paired instead with the 'other' register sync_gen.vpos__retimed, whose 4 flops are vpos bits 0-3 (IoU 0.80, kind refused).

* Overlaps (2 truth registers): `sync_gen.vpos` (counter, tier C_clean) bits [0-4] IoU 0.500; `sync_gen.vpos__retimed` (other, tier C_clean) bits [0-3] IoU 0.800
* Truth looks wrong: no (the double assignment of 4 flops is the labeller's retiming convention)

### F3 -- `ttcad25a__tt_um_space_invaders_game` `counter4` (counter, 5 flops, refused: hold)

The structure side of pb_y's M1: bits 0-4 as up by 7 modulo 32 (-25 mod 32), refused ('hold' not claimed); IoU exactly 0.50.

* Overlaps (1 truth registers): `pb_y` (counter, tier C_clean) bits [0-4] IoU 0.500
* Truth looks wrong: no

### F3 -- `ttcad25a__tt_um_space_invaders_game` `counter6` (counter, 4 flops, harness-VERIFIED)

The structure side of pb_y's M1: bits 5-8, down by 1 modulo 16, harness-VERIFIED; IoU 0.40.

* Overlaps (1 truth registers): `pb_y` (counter, tier C_clean) bits [5-8] IoU 0.400
* Truth looks wrong: no

### F3 -- `ttcad25a__tt_um_space_invaders_game` `counter12` (counter, 2 flops, harness-VERIFIED)

shooter_x moves by +/-10 within bounds (the truth's step 10; Tier A, RTL bits 0 and 1 share one flop). The register is FOUND by counter5 (bits 0 and 2-5, IoU 0.56, step 5; refused, V1). counter12 is a harness-VERIFIED 2-bit saturating down-counter over bits 8-9; IoU 0.22.

* Overlaps (1 truth registers): `shooter_x` (counter, tier A_contradicted) bits [8-9] IoU 0.222
* Truth looks wrong: no

### F4 -- `ttcad25a__tt_um_space_invaders_game` `lfsr0` (lfsr_crc, 8 flops, harness-VERIFIED)

The structure side of the lfsr M4a: an lfsr_crc (fibonacci, poly 285) harness-VERIFIED at IoU 1.00 over the truth shift_register 'lfsr'.

* Overlaps (1 truth registers): `lfsr` (shift_register, tier C_clean) bits [0-7] IoU 1.000
* Truth looks wrong: yes (a Fibonacci LFSR labelled shift_register) (R-D1)

## 6. Found but unverified (R)

| Design | Register | kind | structure | IoU | exact | bucket | code |
|---|---|---|---|---|---|---|---|
| `tt06__tt_um_SJ` | `DUT.U1.countPE` | counter | `counter2` | 1.00 | True | hold | V1 |
| `tt06__tt_um_kwilke_cdc_fifo` | `kwilke_fifo.readstate.read_address` | counter | `counter0` | 1.00 | True | hold | V1 |
| `tt06__tt_um_kwilke_cdc_fifo` | `kwilke_fifo.writestate.write_address` | counter | `counter1` | 1.00 | True | hold | V1 |
| `tt05__tt_um_digital_clock_sellicott` | `clock_inst.shift_out_inst.shift_out_inst.serial_data` | shift_register | `shift_register#0` | 1.00 | True | hold | V1 |
| `tt05__tt_um_nickjhay_processor` | `text_idx` | counter | `counter0` | 0.71 | False | hold | V1 |
| `ttsky25b__tt_um_ieeeuoftasic_simproc` | `U1.UART1.UART_RX1.clkCount` | counter | `counter0` | 0.70 | False | vacuous | V2 |
| `ttsky25b__tt_um_ieeeuoftasic_simproc` | `U1.UART1.UART_TX1.clkCount` | counter | `counter1` | 0.60 | False | hold | V1 |
| `ttsky25b__tt_um_ieeeuoftasic_simproc` | `U1.UART1.UART_TX1.index` | counter | `counter2` | 1.00 | True | hold | V1 |
| `ttcad25a__tt_um_space_invaders_game` | `barrier_health[0]` | counter | `counter7` | 1.00 | True | hold | V1 |
| `ttcad25a__tt_um_space_invaders_game` | `barrier_health[1]` | counter | `counter10` | 1.00 | True | hold | V1 |
| `ttcad25a__tt_um_space_invaders_game` | `barrier_health[2]` | counter | `counter8` | 1.00 | True | hold | V1 |
| `ttcad25a__tt_um_space_invaders_game` | `barrier_health[3]` | counter | `counter9` | 1.00 | True | hold | V1 |
| `ttcad25a__tt_um_space_invaders_game` | `shooter_x` | counter | `counter5` | 0.56 | False | hold | V1 |

## 7. Label disagreements -- listed, never applied

docs/S3_DESIGN.md section 4.4 and docs/S3_REPLICATION_PLAN.md: label disagreements are listed, never applied. No truth file was modified and no count here assumes one resolved.

* **R-D1** (recurs: B1 D1): lfsr (8 flops) in `ttcad25a__tt_um_space_invaders_game`; truth `shift_register`, recognizer `lfsr_crc`. RTL: project.v: lfsr <= {lfsr[6:0], lfsr_feedback}; lfsr_feedback = lfsr[7] ^ lfsr[5] ^ lfsr[4] ^ lfsr[3]; reset to 8'hA5. An author-named 8-bit Fibonacci LFSR. The labeller's lfsr_crc rule needs own-Q XOR feedback into at least max(2, n/4) bits and a Fibonacci LFSR XORs into one head bit, so its shift_register rule claimed it; the truth's own params.serial_in is 'lfsr_feedback'. The recognizer's lfsr0 (form fibonacci, poly 285, k_steps 1) is harness-VERIFIED over exactly those 8 flops (IoU 1.00). Cost: 1 shift_register miss (M4a) and 1 lfsr_crc false positive (F4), the same register counted in both.
* **R-D2** (recurs: B1 D4): prev_button0 (1 flop), prev_button1 (1 flop), prev_button2 (1 flop), sys_in1_buffer (8 flops) in `ttcad25a__tt_um_space_invaders_game`, `tt05__tt_um_nickjhay_processor`; truth `synchronizer (params.stages = 1)`, recognizer `flag (x3); stage 0 of a shift_register`. RTL: space invaders project.v: prev_button0 <= ui_in[0] (likewise 1, 2), commented 'Capture previous button states for edge-detection'; nickjhay main.v: sys_in1_buffer <= ui_in on the cycles sys_in1_next is 1, 8'b0 on the others. The labeller's rule 3 calls a register whose D is an input pin a synchronizer of ONE stage; the frozen contract defines a synchronizer as >= 2 stages (verify.py SYNC_MIN_STAGES = 2). The two conventions disagree and the recognizer cannot satisfy both. Three of the four are edge-detector 'previous value' flops and the fourth an input capture register, which the RTL does not present as synchronizers either. Cost: all 4 R synchronizer misses (M6).
* **R-D3** (new): DUT.U*.filter_spad[0..2], DUT.U*.ifmap_spad[0..2] (54 registers of 8 flops, all Tier A), i_kitt_scan_core.pwmsel[0..7] (8 registers of 3 flops) in `tt06__tt_um_SJ`, `ttsky25b__tt_um_yorimichi_kittscanner`; truth `data_register (per array entry)`, recognizer `shift_register (multi-lane)`. RTL: SJ PE.sv: if (read_new_filter_val) { filter_spad[i] <= filter_spad[i-1] (i = 2, 1); filter_spad[0] <= filter_i } and the same for ifmap_spad; kitt kitt_scan_core.v: next_pwmsel[i] = pwmsel[i-1] (left shift) or pwmsel[i+1] (right shift) in the scan states. Word-wise shift registers over unpacked-array entries. The labeller's shift_register rule looks for D[k] = Q[k-1] inside one register, so each entry is labelled data_register ('loads external or computed values'). None of these registers is in any scored denominator, so the disagreement costs false positives, not misses. Cost: 4 shift_register false positives (F5), 0 misses. RELABELLING ALONE WOULD NOT RECOVER SJ: each of its three structures holds 4 spad chains of 4 different PEs (12 entries, 96 flops), so a truth that named each 24-flop chain a shift_register would still sit at IoU 0.25 with it.
* **R-D4** (new): sa.iloop[i].jloop[j].sxy.out1 / .out2 (1 flop each, 64 + 64 cells), clock_inst.refclk_gen_inst.refclk_ext, refclk_pipe0, refclk_pipe1 (1 flop each) in `tt05__tt_um_nickjhay_processor`, `tt05__tt_um_digital_clock_sellicott`; truth `flag (per stage)`, recognizer `shift_register`. RTL: nickjhay main.v systolic_cell: out1 <= in1, out2 <= in2 under sys_in_valid, and cell (i+1, j) reads out1 of cell (i, j) -- the author's comment: 'successive out1's will form shift registers'; sellicott reference_clk_stb.v: {refclk_pipe1, refclk_pipe0, refclk_ext} <= {refclk_pipe0, refclk_ext, i_refclk} under i_en -- the author's comment: 'a clock domain crossing for the refclk signal'. Pipelines written one 1-bit RTL register per stage. The labeller's rules call each a 'single-bit register' (flag); its synchronizer rule needs 'no enable' (sellicott's chain has i_en), and its copy_lanes unit rule only joins registers already labelled shift_register or synchronizer. The recognizer's shift structures over them are real: 2 of the 3 are harness-VERIFIED. Cost: 3 shift_register false positives (F6), 0 misses.
* **R-D5** (recurs: B1 D3 (the same arithmetic rule firing on a non-counter)): i_kitt_scan_core.state (6 flops) in `ttsky25b__tt_um_yorimichi_kittscanner`; truth `counter (step 1, modulus 2)`, recognizer `data_register (2 flops) + 4 flags`. RTL: kitt_scan_core.v: the FSM state register; next_state = state + 1'b1 through the scan sequences and a constant (IDLE, CAPT, HEAD_MD0 = 10, HEAD_MD1 = 40, HEAD_MD2 = 50, HEAD_MD3 = 2) elsewhere. The truth's arithmetic rule ('D = Q +/- constant') reads state + 1 as a counter; the register is a sequencer with constant jumps, and the truth's own params.modulus = 2 is not consistent with the RTL, whose state codes run to HEAD_MD2 + 9 = 59. Cost: 1 counter miss (M2b).
* **R-D6** (new) -- weak: score (10 bits, 9 flops; every mapped bit z3-refuted, Tier A) in `ttcad25a__tt_um_space_invaders_game`; truth `counter (step null)`, recognizer `data_register (7 flops) + 2 flags`. RTL: project.v: score <= score + 10, + 20 or + 30 at 40 hit sites, depending on the alien row. The kind 'counter' is defensible under the rule 'D = Q + constant', but there is no single step (the truth's params.step is null) and the frozen counter template (verify.py) needs one constant step, so no structure could ever verify it as labelled; the label is also Tier A. Cost: 1 counter miss (M2b).
* **R-D7** (recurs: B1 D4 (the same kind of convention conflict, for shift_register)): DUT.U1.PEStartEN (2 flops; both z3-refuted and mismatching simulation, Tier A) in `tt06__tt_um_SJ`; truth `shift_register (depth 2)`, recognizer `2 flags`. RTL: topLevelControl.sv: nextPEStartEN[1] = PEStartEN[0]; nextPEStartEN[0] = 1'b1 (runOS) or PEReadNaive[0] | [1] | [2] (endOS). The labeller accepts a depth-2 shift; the frozen contract requires depth >= 3 (verify.py and params.py SHIFT_MIN_DEPTH = 3). The two conventions disagree and the recognizer cannot satisfy both. Cost: 1 shift_register miss (M6b).

## 8. Caveats

* Support. R's misses are 27 registers and its false positives 34 structures over 10 designs, and they are clustered: tt06__tt_um_SJ alone carries 10 misses and 11 false positives, 14 of them (M7 x7, F7 x7) seven instances of ONE PE module, which is one mechanism met seven times, not seven findings.
* Every count is the strict register level on permutation p1; all 10 R designs gave one distinct answer across their K = 5 permutations (numbers.json E_mechanics), so the causes are permutation-invariant.
* Strict and lenient differ on R for exactly the two M3b registers (numbers.json notes); every cause here is the strict one.
* No R miss or false positive is caused by a dropped, unmapped or shadow flop: only ttsky26b__tt_um_tiny_8bit_cpu has unmapped flops (72, 'no RTL name on the Q net'), all of them in structures of unscored kinds.
* Mechanisms that name RTL come from reading the labeller's cached RTL of these ten designs; mechanisms that name a recognizer rule come from the record's structures, harness verdicts, relation records and stage statistics. The recognizer was not re-run and nothing under tools/ was changed.
* Several truth registers involved are Tier A (a mapped bit z3-refuted or mismatching simulation): SJ's calculating_RS flags, spads, psum_spad and PEStartEN; space invaders' score and shooter_x; parakeet's road_z. A Tier A label is not established; the case lists carry each register's tier.
* Some events are charged twice by construction and are not netted out: the partial words of the 4 M1 registers are 7 false positives (6 F3, 1 F3b), each M7 is also an F7, the M3b pair is one F8, the M4a register one F4, kitt's M8 one F5 and nickjhay's M6 sits inside one F6. 27 + 34 is not 61 independent errors.
