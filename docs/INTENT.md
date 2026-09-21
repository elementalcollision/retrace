# RETRACE — recovered design intent (Jane Street ASIC puzzle)

This document describes what the puzzle's 92-flop, 728-cell netlist (extracted from
`upstream/puzzle.gds`, ports `clk`, `rst_n`, `enable`, `I`, `O[7:0]`, `success`) does,
in the vocabulary of the six recovered RTL blocks in `rtl_recovered/` and the
integrated top level `rtl_recovered/puzzle_recovered.v`. It does **not** search for
the winning input sequence (`success == 1`) — that is V8, the next sprint, and is
explicitly out of scope here. What follows is the exact, proven condition for
`success`, stated in words and as a formula, plus the evidence that the recovered
RTL is that circuit.

## 1. Block diagram

```
                       clk, rst_n ---------> (every flop, async reset/set, see below)
                       enable, I  -----+------------------------------------------+
                                       |                                          |
                                       v                                          v
                              +-----------------+                        +----------------+
                              |     counter     |--- cnt_done (q_f08) -->|  left_bottom   |
                              | mod-121 (11x11)  |--- lo2,lo1,lo0,lo3 --->|  8-bit up-     |
                              | cycle counter +  |   (q_f04..q_f07)       |  counter,      |
                              | one-shot "done"  |         |              |  frozen while  |
                              | latch (f00-f08)  |         |              |  cnt_done      |
                              +--------+---------+         |              |  (f69-f76)     |
                                       |                   |              +-------+--------+
                                       | cnt_done           |                      |
                                       | lo2,lo1,lo0,lo3     |                      | lb_bit[7:0]
                                       v                    v                      |
                              +-----------------+   +-----------------+            |
                              |     array       |   |   left_top      |            |
                              | 22 saturating   |   | 12-tap I shift  |            |
                              | 2-bit "hit bin" |   | register + 2    |            |
                              | counters, one   |   | sticky checkers |            |
                              | per (q_f00..    |   | row_count_err,  |            |
                              | q_f07) pattern  |   | hist_hit(f64)   |            |
                              | (f09-f52)       |   | (f53-f68)       |            |
                              +--------+--------+   +--------+--------+            |
                                       |                      |                    |
                                       | array_bits[43:0]      | 2 sticky flags     |
                                       |                      |                    |
                                       +----------+   +-------+                    |
                                                  |   |                            |
                                                  v   v                            |
                                          +-----------------------+                |
                              cnt_done -->|         check         |                |
                                          | trigger = cnt_done &  |                |
                                          | ~armed (one-shot);    |<---------------+
                                          | on trigger, pass =    |
                                          | array_ok & lb_ok &    |
                                          | ~row_count_err;       |
                                          | latches success or    |
                                          | alt_latch (f77-f79)   |
                                          +-----------+-----------+
                                                      |
                                    success, alt_latch(q_f77), hist_hit(q_f64)
                                                      |
                                                      v
                              I, enable, cnt_done,   +-----------------------+
                              left_bottom(f69-f76) ->|        outgen         |---> O[7:0]
                                                      | scrambler shift reg   |
                                                      | (f80-f87) + 9-step    |
                                                      | playback position     |
                                                      | (f88-f91, no reset);  |
                                                      | 4-way message ROM     |
                                                      +-----------------------+
```

Every arrow above is a **current-flop-value** (`q_fNN`) read, not a clock or reset
wire — `clk`/`rst_n` reach all 92 flops directly (see §2) and are omitted from the
per-block boxes for clarity. Every block's next-state logic is purely combinational;
the flops themselves live in `rtl_recovered/puzzle_recovered.v`, not in the block
files (see §5).

## 2. Blocks: function and register map

### 2.1 `counter` (`rtl_recovered/counter.v`, flops f00-f08, all `dfrtp_2` reset-to-0)

A base-11 x base-11 (mod-121) cycle counter with a one-shot "done" latch, not a
binary counter. `lo` (ones digit) increments every enabled cycle while `~cnt_done`;
at `lo==10` it wraps to 0 and `hi` (elevens digit) increments; when both reach 10
simultaneously (the 121st enabled cycle, count 120) both reset to 0 and `cnt_done`
latches permanently. Once `cnt_done=1`, every next-state output freezes regardless
of `enable`.

| Register | Flop | Meaning | Reset |
|---|---|---|---|
| `lo0` | f06 | ones digit, bit 0 (LSB) | 0 |
| `lo1` | f05 | ones digit, bit 1 | 0 |
| `lo2` | f04 | ones digit, bit 2 | 0 |
| `lo3` | f07 | ones digit, bit 3 (MSB) | 0 |
| `hi0` | f00 | elevens digit, bit 0 (LSB) | 0 |
| `hi1` | f02 | elevens digit, bit 1 | 0 |
| `hi2` | f03 | elevens digit, bit 2 | 0 |
| `hi3` | f01 | elevens digit, bit 3 (MSB) | 0 |
| `cnt_done` | f08 | sticky "121 enabled cycles seen" flag | 0 |

### 2.2 `array` (`rtl_recovered/array.v`, flops f09-f52, all `dfrtp_2` reset-to-0)

22 independent 2-bit **saturating** up-counters ("bins"), each incrementing
0->1->2->3 (then holding at 3) on a cycle where `I & enable` and the bin's private
"hit" condition over `{lo0,lo1,lo2,lo3,hi0,hi1,hi2,hi3,cnt_done}` (i.e. `q_f00..
q_f08`) is true. Bins 0-10 decode an irregular (but exact, exhaustively verified)
8-bit Boolean match on `{q_f00..q_f07}` with `cnt_done=0`; bins 11-21 decode a plain
one-hot 4-bit equality on `{lo2,lo1,lo0,lo3}` (`q_f04..q_f07`) with `cnt_done=0`.
Register map (msb/lsb per bin, all reset 0):

| Bin | msb flop | lsb flop | Bin | msb flop | lsb flop |
|---|---|---|---|---|---|
| 0 | f09 | f10 | 11 | f31 | f32 |
| 1 | f11 | f12 | 12 | f33 | f34 |
| 2 | f16 | f13 | 13 | f35 | f36 |
| 3 | f15 | f14 | 14 | f37 | f38 |
| 4 | f17 | f18 | 15 | f39 | f40 |
| 5 | f19 | f20 | 16 | f41 | f42 |
| 6 | f21 | f22 | 17 | f43 | f44 |
| 7 | f23 | f24 | 18 | f46 | f45 |
| 8 | f25 | f27 | 19 | f47 | f49 |
| 9 | f26 | f28 | 20 | f48 | f50 |
| 10 | f29 | f30 | 21 | f52 | f51 |

### 2.3 `left_top` (`rtl_recovered/left_top.v`, flops f53-f68, all `dfrtp_2` reset-to-0)

Two cooperating pieces of state, both gated by `shift_en = enable & ~cnt_done`:
(1) a 12-stage shift register recording the last 12 samples of `I`
(`I -> f67 -> f66 -> f68 -> f63 -> f60 -> f58 -> f61 -> f56 -> f57 -> f59 -> f62 ->
f65`), advancing one tap per `shift_en` cycle; (2) two independent **sticky** ("set
once, stay set until reset") flags, `row_count_err` (f53) and `hist_hit` (f64), each
latched from a small combinational condition over the taps, `I`, and
`check_slot = ~lo2 & lo1 & ~lo0 & lo3` (true on one specific value of the counter's
low 4 bits: column 10, the last cell of a row). `row_stars_hi`(f54)/`row_stars_lo`(f55) form
`row_stars`, a 2-bit saturating count of the stars so far in the current row, cleared at the
row's last cell. `row_count_err` is set there unless the row holds exactly 2 stars, and
`hist_hit` is set when a new star touches an earlier one. (Renamed on 2026-09-19 from the first
recovered names `match_ok`/`cmp_state`/`cmp_hold`, which described the logic as a "serial
comparator" and read the error flag as its opposite.)

| Register | Flop | Meaning | Reset |
|---|---|---|---|
| `row_count_err` | f53 | sticky error: some row did not hold exactly 2 stars | 0 |
| `row_stars_hi` | f54 | `row_stars` bit 1 (stars so far in this row, saturating at 3) | 0 |
| `row_stars_lo` | f55 | `row_stars` bit 0 | 0 |
| `shift_tap0..11` | f67,f66,f68,f63,f60,f58,f61,f56,f57,f59,f62,f65 | 12-tap `I` shift register, tap0=newest .. tap11=oldest | 0 |
| `hist_hit` | f64 | sticky error: a star touched an earlier one (from the shift-register taps) | 0 |

### 2.4 `left_bottom` (`rtl_recovered/left_bottom.v`, flops f69-f76, all `dfrtp_2` reset-to-0)

An 8-bit synchronous up-counter (plain ripple-carry incrementer). Frozen whenever
`cnt_done=1`; otherwise increments by 1 (8-bit wraparound) whenever `I & enable`;
otherwise holds. Bit-significance order across the flop ids is scrambled by
placement/synthesis (LSB..MSB = f75,f70,f72,f74,f69,f71,f73,f76), not sequential.

| Register | Flop | Bit | Reset |
|---|---|---|---|
| `lb_bit0` | f75 | LSB | 0 |
| `lb_bit1` | f70 | 1 | 0 |
| `lb_bit2` | f72 | 2 | 0 |
| `lb_bit3` | f74 | 3 | 0 |
| `lb_bit4` | f69 | 4 | 0 |
| `lb_bit5` | f71 | 5 | 0 |
| `lb_bit6` | f73 | 6 | 0 |
| `lb_bit7` | f76 | MSB | 0 |

### 2.5 `check` (`rtl_recovered/check.v`, flops f77-f79, all `dfrtp_2` reset-to-0; owns `success`)

A one-shot "did the puzzle solve?" decision. `armed` (f79) is a sticky OR-latch
(`d_f79 = cnt_done | armed`), so `trigger = cnt_done & ~armed` is high on exactly one
cycle per reset interval: the first time `cnt_done` (counter's `q_f08`) is seen 1.
On that cycle only, `check` evaluates `pass = trigger & ~row_count_err & lb_ok & array_ok`
(see §3 for `lb_ok`/`array_ok`) and, if `pass`, sets exactly one of `success_latch`
(f78, when `hist_hit=0`) or `alt_latch` (f77, when `hist_hit=1`); if the trigger
fires without `pass`, both are cleared. Every other cycle both hold. `success` wires
directly to `success_latch` (f78).

| Register | Flop | Meaning | Reset |
|---|---|---|---|
| `alt_latch` | f77 | latched instead of `success` when the trigger fires with `hist_hit=1` | 0 |
| `success_latch` | f78 | drives `success` | 0 |
| `armed` | f79 | sticky "already evaluated" flag | 0 |

### 2.6 `outgen` (`rtl_recovered/outgen.v`, flops f80-f91; owns `O[7:0]`)

An 8-bit ASCII message printer. `pos` (f88-f91, `dfxtp_2`, **no reset**) is a 4-bit
feedback register that, while `armed` (`q_f79`) is 1, steps through the fixed
permutation `0,4,1,5,2,6,3,7,8,12,9,13,10,14,11,15` (9 live steps, then locks at 15);
while `armed=0` it is forced to 0 every cycle. The 8-bit `scrambler` register
(f80-f87; f80/f82/f85/f86 reset to 0, f81/f83/f84/f87 async-**set** to 1, giving
reset value `8'b1011_0110`, i.e. `scr_bit7..scr_bit0` = `1,0,1,1,0,1,1,0`) either
shifts in a new LFSR-mixed bit of `I` (while `shift_en = enable & ~cnt_done`), or
runs a second self-XOR update once per printed byte (while printing and not
shifting), or holds. `O` is silent (`8'h00`) unless `armed & ~pos_locked`; while
active it emits one byte per cycle selected, in priority order, by `left_bottom ==
0` ("EMPTY SKY" easter egg), `left_bottom == 0xAE` (raw byte with f69 as MSB, i.e. count 121: "BIG BANG" easter egg),
`success_latch` set (a fixed table XORed with the live scrambler byte — unreadable
unless the scrambler was driven, via `I`, to the value that decrypts it), `alt_latch`
set ("TWO NOT TOUCH" easter egg), else "TRY AGAIN" (the failure message, and the
case the sample trace exercises).

| Register | Flop | Meaning | Reset |
|---|---|---|---|
| `scr_bit7` | f81 | scrambler bit 7 (chain-oldest) | 1 (dfstp) |
| `scr_bit6` | f80 | scrambler bit 6 | 0 (dfrtp) |
| `scr_bit5` | f83 | scrambler bit 5 | 1 (dfstp) |
| `scr_bit4` | f82 | scrambler bit 4 | 0 (dfrtp) |
| `scr_bit3` | f85 | scrambler bit 3 | 1 (dfstp) |
| `scr_bit2` | f84 | scrambler bit 2 | 1 (dfstp) |
| `scr_bit1` | f86 | scrambler bit 1 | 0 (dfrtp) |
| `scr_bit0` | f87 | scrambler bit 0 (chain-newest) | 1 (dfstp) |
| `pos3` | f88 | playback position, bit 3 (MSB) | none (dfxtp) |
| `pos2` | f89 | playback position, bit 2 | none (dfxtp) |
| `pos1` | f90 | playback position, bit 1 | none (dfxtp) |
| `pos0` | f91 | playback position, bit 0 (LSB) | none (dfxtp) |

All 92 register-to-flop mappings above are reproduced verbatim in
`rtl_recovered/puzzle_recovered.v`'s `reg <name>; // fNN, reset ...` declarations,
which is the single source of truth for the reset/set behaviour (cross-checked
against `rtl_recovered/blocks.json`: 84 `dfrtp_2` reset-to-0, 4 `dfstp_2` reset-to-1,
4 `dfxtp_2` no-reset — matches exactly, 92 total).

## 3. Data flow and the exact success condition

`success` is a registered, **sticky** output: once set it never clears (except by
`rst_n`), and it can only ever be set (or permanently forfeited to `alt_latch`) on
one single cycle per reset interval — the cycle `counter`'s `cnt_done` (q_f08) first
goes high, which is the 121st enabled clock cycle after the counter last started
from 0 (see §2.1). At that instant:

```
trigger        = cnt_done & ~armed                          (one-shot, always true this cycle)
rows_ok        = ~row_count_err                             (left_top's f53 must be 0)
left_bottom_ok = ({f76,...,f69} == 8'b0000_1011)              (raw flop-id order; the counter VALUE is 22)
array_ok       = (array_bits[43:0] == ARRAY_TARGET)           (see below)
pass           = trigger & rows_ok & left_bottom_ok & array_ok
success        = success_latch, set to 1 iff  pass & ~hist_hit   (f64 == 0)
                                (if pass & hist_hit, alt_latch is set instead and
                                 success stays 0; if trigger fires without pass,
                                 both latches are cleared to 0 and stay 0 forever)
```

**`ARRAY_TARGET`** (`array_bits = {f52,f51,...,f10,f09}`, MSB=f52) is the fixed
44-bit constant `44'b1000_1110_0101_0101_0101_0101_0011_0101_0101_1100_0101`.
Decoding it bin-by-bin (§2.2's msb/lsb map) shows every one of the 22 array bins
must equal exactly `2'b10` (decimal 2) — i.e. **every bin must have counted exactly
2 "hits" by the time `cnt_done` first fires**, no more (3 would saturate to
`2'b11`) and no fewer. This is a clean, notable structural fact: the puzzle isn't
asking for an arbitrary array state, it is asking that the entire `array` block be
driven to "every bin hit exactly twice."

**Note on the `left_bottom` value (corrected by the lead review, 2026-09-18).** `check.v`
compares the eight flops in flop-id order, `{f76,...,f69} == 8'b0000_1011`, which is a raw
pattern, not the counter value. The counter's bit weights are LSB->MSB
f75, f70, f72, f74, f69, f71, f73, f76 (§2.4), so the pattern is the value **22**; a
simulation of the proven `rec_left_bottom` from reset reaches it after exactly 22
increments (`out/audit/tb_lb.v`). The integration draft read the raw pattern as 11. 22 is
also the only value consistent with condition 4: each `I = 1` cycle adds one hit to one
group-A bin and one group-B bin, and 11 bins x 2 hits = 22 in each group.

**In words, `success` becomes and stays 1 if and only if**, on the single cycle the
counter's mod-121 sweep first completes (the 121st enabled cycle since the counter
was last at 0):
1. `left_top`'s `row_count_err` (f53) is **0**: every row held exactly 2 stars,
2. `left_top`'s `hist_hit` (f64) is **0** (the history-pattern sticky flag must
   never have latched — if this alone is violated while everything else holds,
   `alt_latch` is set instead and `success` stays 0 permanently),
3. `left_bottom`'s 8-bit counter equals decimal **22**, i.e. exactly 22 enabled
   cycles with `I = 1` (see the note below), and
4. every one of `array`'s 22 saturating bins has been incremented to exactly
   **2** (not 0, 1, or saturated-at-3).

All four conditions depend on how many times, and under what conditions on the
counter's own low bits, `I` was driven to 1 during the 121-cycle sweep — i.e.
`success` is purely a function of the `I` sequence fed in during exactly one
121-cycle enabled run (from reset, or from the previous run's `cnt_done` clearing).
Nothing later in the run (after `cnt_done` first fires) can change the outcome:
`armed` latches permanently on that same cycle, so `trigger` (and thus `pass`) can
never fire again. **No search for a satisfying `I` sequence was performed** — per
the task, finding one is V8, out of scope here.

## 4. `outgen`: what `O` emits and when

`O` is silent (`8'h00`) whenever `armed` (`q_f79`, the `check` block's sticky
"cnt_done has fired" flag) is 0 — i.e. for the entire first 121-cycle sweep, `O`
says nothing. Only after `cnt_done` first fires (the same cycle `success`/`alt_latch`
are decided) does `armed` go high and `outgen` start playing back a 9-byte message,
one byte per clock cycle, at the fixed `pos` schedule `0,4,1,5,2,6,3,7,8` (then
`pos` locks at 15 and `O` returns to silent). Which message plays is selected, in
priority order, by `left_bottom`'s value **at the moment `armed` is first checked
each cycle** and by which of `success_latch`/`alt_latch` got set on the trigger
cycle:

| Condition (checked in this order) | Message | Note |
|---|---|---|
| `left_bottom == 8'h00` | `"EMPTY SKY"` | easter egg, independent of `success` |
| `left_bottom == 8'hAE` (raw, f69 = MSB; count 121) | `"BIG BANG"` | easter egg, independent of `success` |
| else, `success_latch` (`q_f78`) set | fixed 8-bit table XOR'd with the live `scrambler` byte each position | **in the success case**: readable only if the `I` sequence fed during printing also happens to drive `scrambler` to the decrypting value at each position — this block does not itself know or enforce that; it is documented, not solved, here |
| else, `alt_latch` (`q_f77`) set | `"TWO NOT TOUCH"` | easter egg |
| else (the case the sample trace exercises: `success=0`, `alt_latch=0`, `left_bottom` never 0/0xAE at any of the 9 print positions) | `"TRY AGAIN"` | the documented failure message |

So in the success case, `O` **does** emit 9 bytes starting the cycle after
`cnt_done` first fires, exactly as in the failure case — the mechanism is identical
and proven identical (same `outgen` RTL, same V7 proof) — but per the task's scope,
whether those 9 bytes spell anything readable depends on an `I`-sequence property
during printing that this pass does not search for or claim to satisfy.

## 5. Physical layout vs. recovered blocks

`rtl_recovered/blocks.json` records each flop's placement (`x_um`, `y_um`) from the
extracted GDS. Per-block bounding boxes and centroids:

| Block | Flops | x range (um) | y range (um) | Centroid (um) |
|---|---|---|---|---|
| `counter` | f00-f08 (9) | 26.2 - 33.1 | 92.5 - 201.3 | (29.5, 133.6) |
| `array` | f09-f52 (44) | 113.2 - 123.3 | 46.2 - 285.6 | (115.4, 169.1) |
| `left_top` | f53-f68 (16) | 75.0 - 87.9 | 92.5 - 163.2 | (80.2, 138.4) |
| `left_bottom` | f69-f76 (8) | 75.9 - 82.8 | 35.4 - 57.1 | (79.3, 45.6) |
| `check` | f77-f79 (3) | 167.9 - 172.0 | 272.0 - 282.9 | (169.3, 278.3) |
| `outgen` | f80-f91 (12) | 167.0 - 174.8 | 176.8 - 253.0 | (169.7, 208.1) |

On a 200x300 um die, this reads as four clusters left-to-right/bottom-to-top:
- **`counter`** sits alone on the far left (x~26-33), spanning nearly the full die
  height (y 92-201) — consistent with it fanning out to every other block (`cnt_done`
  and the low counter bits feed `array`, `left_top`, `left_bottom`, `check`, and
  `outgen`).
- **`left_bottom`** (y 35-57) sits directly below **`left_top`** (y 92-163) at
  almost the same x (75-88 um) — the physical layout literally matches the block
  names chosen for this recovery (bottom block below top block, same column),
  which is strong independent evidence the block-boundary hypothesis (from
  placement/SCC clustering, per `blocks.json`'s note) is right, not just a
  convenient recovery-time label.
- **`array`** is a tall, narrow column (x 113-123, spanning almost the entire
  y 46-286 range) — plausible for a 22-bin x 2-bit register file needing uniform,
  repeated access to the same 9-bit address bus (`counter`'s state) across its
  whole height.
- **`check`** (y 272-283) sits directly above **`outgen`** (y 177-253) at nearly the
  same x (167-175, the far right edge of the die) — again the two blocks that are
  most tightly coupled in the dataflow (`check` drives `success`/`alt_latch`
  straight into `outgen`'s message-select logic) are physically adjacent and
  stacked, on the side of the die farthest from `counter`.

This placement structure was not assumed going in — `blocks.json`'s block
assignment came from an independent SCC/placement scout pass (see its `"note"`
field) — but it lines up with the recovered dataflow well enough that the
plain-English block names (`left_top`/`left_bottom`, `check`/`outgen` adjacency)
were chosen to match it.

## 6. Verification evidence

All of the following run in the test suite (`test/test_recovered.py`) and were re-run
by the lead review on 2026-09-18.

### 6.1 Per-block proofs (V7)

`python -m tools.analysis.cone check <block> rtl_recovered/<block>.v` SAT-proves each
block's `rec_<block>` equal to its gold cone: the exact netlist logic cut at the flops
(inputs: ports and `q_fNN`; outputs: `d_fNN` and owned primary outputs). **All six
blocks PASS**, including `O` of `outgen`.

`O` was not actually covered until the lead review fixed the harness: gold nets named
after bus bits (`O[3]`) were emitted as `wire O[3];` plus `assign O[3] = O[3];`, which
Verilog reads as a separate, unconnected array. That left the gold module's real `O`
undriven, so any implementation matched (the harness's own sanity check had the same
defect on both sides). The outgen reviewer found it; `cone.py` now renames those nets
(`o_O3`). A planted wrong `O[3]` now FAILS and the recovered `outgen.v` PASSES. Each
block's recovery pass also ran its own directed and exhaustive simulations, recorded in
the block file headers.

### 6.2 Behavioural replay of `example_inputs.vcd`

`tools/retrace/vcdtb.py` turns the sample VCD into a self-checking testbench for
`puzzle_recovered`. Icarus with `rtl_recovered/*.v`: `VCD-REPLAY checked=1248 errors=0`,
the same result as the extracted netlist (V6), including both "TRY AGAIN" printouts.

### 6.3 End-to-end sequential equivalence with the extracted netlist

`python -m tools.analysis.e2e` rebuilds everything in a fresh work directory
(`out/e2e/main`) from the GDS and `rtl_recovered/`, and runs SymbiYosys `abc pdr` on
`formal/recovered_miter.sv`: gold = the extracted netlist (Liberty cell functions),
gate = `puzzle_recovered`, shared inputs, reset asserted in the first cycle, then `O`,
`success` and all 92 flops asserted equal on every later cycle. **Result: PASS, with no
assumption beyond the initial reset** (about 2 s).

* Asserting all 92 flop pairs equal (not just the outputs) makes the property
  1-inductive, given the per-block proofs; with only `O`/`success` asserted, PDR stalled
  around frame 120 on the mod-121 counter.
* The flop values reach the miter through probe ports. `e2e.py` generates both probe
  wrappers by adding `probe_fNN` output ports to the unmodified sources (gold driven by
  each flop's Q net from `blocks.json`, gate by the register tagged `// fNN`). They only
  add ports, and a pass means every assertion holds, so `O`/`success` equality is proven
  independently of the probe mapping. (Hierarchical references into the instances were
  tried first and silently came out undriven after Yosys `flatten`; ports avoid that.)
* The four no-reset `pos` flops (f88-f91) need no assumption: `pos_next = armed ?
  next_pos(pos) : 0` and `armed` (f79) has a real reset, so `pos` is 0 by the second
  cycle in both designs. The optional `ASSUME_EQUAL_NO_RESET_STATE` block in the miter
  is not used.
* Negative test: changing the last byte of "TRY AGAIN" from "N" to "M" in a copy of
  `outgen.v` makes the proof FAIL at the `O` assertion.

## 7. Questions this pass left open, since answered

- **Why the group-A `array` bins (0-10) use an irregular 8-bit match** rather than a clean
  address decode like bins 11-21: they are the Star Battle regions. Each group-A bin is one
  irregular region of the 11 x 11 grid (4 to 28 cells), and each must hold exactly two stars
  (`docs/SOLVE_ANALYTICAL.md` section 2, region map; `docs/SOLUTION.md`).
- **Whether the success message decrypts to readable text:** it does. The only solving input
  makes `O` print `(* TWO STARS *)` (`docs/SOLUTION.md`), and every message is demonstrated on
  the extracted netlist (`test/test_messages.py`).
- **`check.v`'s proof status:** `check` has its own per-block SAT proof against its gold cone,
  like the other five blocks (`test/test_recovered.py::test_v7_block_equivalent[check]`), as
  well as the end-to-end proof of section 6.3.
