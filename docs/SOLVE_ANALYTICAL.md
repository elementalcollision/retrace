# Sprint 4, route A (analytical): solving the puzzle

This is the "solve it as a human would" route: understand the exact rules the recovered
RTL (`rtl_recovered/{counter,array,left_top,left_bottom,check}.v`) implements, state them
as a Star Battle puzzle, and solve that puzzle. Every rule below was established by
**running** the actual `rtl_recovered/*.v` files (Icarus Verilog) and/or translating their
combinational equations verbatim into Python and cross-checking that translation against
those simulations — not by trusting the hypotheses recorded in `docs/INTENT.md` or in the
block files' own header comments. Where a prior hypothesis is confirmed or refuted, that is
called out explicitly. Route B (formal, SAT/BMC over the extracted netlist) was developed
independently in parallel and is out of scope for this document (its files were not read
while writing this one).

Reproduce everything in this document with:

```
.venv/bin/python -m tools.solve.starbattle             # self-test, derive, solve, validate
.venv/bin/python -m tools.solve.starbattle --selftest   # only the RTL cross-checks
```

`tools/solve/starbattle.py` is the single source of truth; this document narrates its
output (`out/solve_a/full_run.log` has a full transcript of the run this document
describes).

## 1. Cell order (which counter value the k-th enabled cycle presents)

Simulated `rec_counter` (`rtl_recovered/counter.v`) standalone from reset with `enable=1`
held for 130 cycles (`out/solve_a/tb_counter.v` / `tb_counter.log`), printing `HI =
{q_f01,q_f03,q_f02,q_f00}` and `LO = {q_f07,q_f04,q_f05,q_f06}` (the bit assemblies the
counter's own next-state logic uses) at every enabled cycle. Result: the 121 enabled
cycles k = 0..120 present, in order, `(HI,LO) = (0,0),(0,1),...,(0,10),(1,0),...,(10,10)` —
row-major, **row = HI, column = LO**, column fastest. `cnt_done` (`q_f08`) is 0 for every
one of these 121 cycles and first becomes 1 the cycle after `(10,10)`. This is exactly the
row-major hypothesis in `docs/INTENT.md`, confirmed by direct RTL simulation (`0` mismatches
against `cell_order()`/`counter_bits()` in `starbattle.py`, see `verify_cell_order_against_icarus()`).

## 2. Region map (group A, bins 0-10)

`rtl_recovered/array.v`'s 22 saturating 2-bit "hit bin" counters split into group A (bins
0-10, an 8-bit exact Boolean decode of `{q_f00..q_f07}`) and group B (bins 11-21, a plain
4-bit equality decode of `{q_f04..q_f07}` = the column `LO`). Group A's `hitNN` conditions
were transcribed verbatim from `array.v` into Python (`GROUP_A_HITS` in `starbattle.py`) and
cross-checked against a **direct Icarus simulation of `rec_array.v`** that pulses `I=1` from
an all-zero bin state at each of the 121 reachable `(HI,LO)` states and reads which bin's
LSB fired (`out/solve_a/tb_array.v` / `tb_array.log`): **0 mismatches over all 121 states**,
for both group A and the group-B/column decode (`verify_region_map_against_icarus()`).

Region map (letters A-K = bins 0-10, row 0 at top, column 0 at left):

```
G G G G G I I F E E J
G G A G G I F F E E J
G G A I I I I F F E J
G G A I B B B J F F J
A G A I B J J J J J J
A A A I B B B J D D D
I I I I I I B J D K K
I H H H B B B J D K K
I H H C J J J J D K K
I I H C C J J J D D D
I H H C J J J J J J J
```

Every one of the 121 cells matches **exactly one** of the 11 `hitNN` conditions (verified
exhaustively, `region_of()` asserts this), so group A is a genuine partition of the grid
into 11 regions.

**Region-size-11 hypothesis: REFUTED.** `docs/INTENT.md` speculated "11 group-A array bins
... = regions?" without asserting equal size; a natural first guess (this being an 11x11
grid) is that each region has 11 cells like a Latin-square Star Battle. Measured region
sizes are `{0:8, 1:11, 2:4, 3:9, 4:5, 5:7, 6:14, 7:8, 8:21, 9:28, 10:6}` (sum 121) — wildly
unequal, from 4 to 28 cells. This makes sense once you look at how the `hitNN` equations
were built: `array.v`'s own header says they were minimized (`sympy SOPform`) to be exactly
equivalent to the gold netlist **over all 256 states of `{q_f00..q_f07}`**, not specifically
to give 11 equal-size groups over the 121 states that are actually reachable — synthesis
had no reason to produce evenly sized regions, only a correct decode. `check.v` only ever
requires each region's saturating counter to read exactly 2, which needs no particular
region size (every region here has >= 2 cells, so it's satisfiable).

## 3. Group B = columns

`hit11..hit21` each match one fixed 4-bit value of `{q_f04,q_f05,q_f06,q_f07}` (= `LO`, the
column), one value per bin, all 11 column values 0-10 covered exactly once
(`LO_TO_COLBIN` in `starbattle.py`, cross-checked against the same `tb_array.log`, 0
mismatches). So group B is literally "count of stars in this column."

## 4. `match_ok` (f53): exact trigger, established by directed simulation

`match_ok` only ever updates on a `check_slot` cycle (`LO == 10`, i.e. the last cell of each
row — one `check_slot` per row, 11 total over the sweep), confirmed by both reading
`left_top.v`'s `check_slot` equation (`~q_f04 & q_f05 & ~q_f06 & q_f07`, which decodes to
`LO == 10` under the counter's own bit weights) and by simulation.

Directed test (`out/solve_a` runs, reproduced by the snippet in this doc's history):
holding every other row at exactly 2 stars and sweeping one row's star count through
0,1,2,3,4:

| row star count | `match_ok` |
|---|---|
| 0 | 1 (bad) |
| 1 | 1 (bad) |
| **2** | **0 (good)** |
| 3 | 1 (bad) |
| 4 | 1 (bad) |

This holds for row 0, row 5, and row 10 alike (no special-case for the first/last row).
Five additional random trials, each with every row given a *different pair* of columns (so
column and region counts are not the all-2 pattern), still show `match_ok=0` whenever every
row's count is exactly 2, regardless of *which* two columns. **Confirms the `docs/INTENT.md`
hypothesis exactly: `match_ok` is a per-row "does this row have exactly 2 stars" checker**,
evaluated independently for each of the 11 rows (via the small serial comparator
`cmp_state`/`cmp_hold`, which is force-cleared to 0 at every `check_slot`, i.e. it restarts
fresh each row) and OR'd sticky into one flag. `check.v` requires `match_ok == 0` for
`success`, so **every row must have exactly 2 stars.**

## 5. `hist_hit` (f64): exact trigger, established by directed simulation

Directed two-star tests, one pair of cells at a time (all other cells 0):

| pair | `hist_hit` |
|---|---|
| horizontally adjacent | 1 (bad) |
| vertically adjacent | 1 (bad) |
| diagonally adjacent | 1 (bad) |
| anti-diagonally adjacent | 1 (bad) |
| same row, one gap | 0 (good) |
| same column, one gap | 0 (good) |
| row-10-col-10 next to row-0-col-0 of the *next* row (i.e. treating the 121 cells as one
  linear shift-register stream, "wraps" from one row's end to the next row's start) | 0 (good) |
| column-wraps (row 0 vs row 10, same column) | 0 (good) |
| a knight's move apart, or far apart | 0 (good) |

**Confirms the `docs/INTENT.md` hypothesis exactly: `hist_hit` is the standard "Two Not
Touch" king-move adjacency checker** — any two stars that are horizontal, vertical, or
diagonal neighbours (8-neighbourhood) set it, with **no wraparound** across row ends or
grid edges. `check.v` requires `hist_hit == 0` for `success` (if it alone is violated while
everything else holds, `alt_latch` — "TWO NOT TOUCH" — is set instead and `success` stays 0
permanently).

## 6. `left_bottom` and the array target: exact counts, not raw patterns

`check.v` compares `left_bottom`'s 8 flops against the **raw flop-id-order** pattern
`{f76,...,f69} == 8'b0000_1011`. Decoded through `left_bottom.v`'s own true bit-significance
order (LSB..MSB = f75,f70,f72,f74,f69,f71,f73,f76, established there by exhaustive
permutation search against the gold netlist), this pattern is the decimal value **22**
(`_decode_left_bottom_target()` in `starbattle.py`). Since `left_bottom` is a plain
(non-saturating) up-counter that increments once per `I=1` enabled cycle, "target == 22"
is exactly "total stars placed == 22."

`check.v`'s 44-bit `ARRAY_TARGET` constant, decoded bin-by-bin through `array.v`'s own
msb/lsb flop map (`array_target_per_bin()`), gives **decimal 2 for every one of the 22
bins**, confirmed programmatically (no exceptions). Since each bin is a *saturating*
up-counter (0,1,2,3,3,3,... — never decreasing, never wrapping), "final value == 2" is
exactly "exactly 2 hits counted for this bin during the sweep" (any hit count above 2 would
saturate past 2 and fail the equality; any count below 2 obviously fails it too). So:

* every one of the 11 group-A regions must contain **exactly 2 stars**,
* every one of the 11 columns must contain **exactly 2 stars**,
* total stars placed must be **exactly 22** (implied by, and cross-checked against, the
  above: 11 x 2 = 22 either way).

## 7. Other conditions checked

* **Timing / one-shot.** `check.v`'s `trigger = q_f08 & ~q_f79` fires on exactly one cycle
  (the first time `cnt_done` is seen high, i.e. the cycle right after the 121st enabled
  cycle), and `armed` (f79) latches permanently right after, so nothing after that cycle can
  change `success` — confirmed both by reading `check.v` and by the end-to-end Icarus run in
  step 9 below (`success` is 0 immediately after the 121-cycle loop, then 1 one clock later,
  then stays 1).
* **Enable gaps / I while `enable=0`.** Every next-state equation in `counter.v`, `array.v`
  (`wr_en = I & enable`), and `left_top.v` (`shift_en = enable & ~cnt_done`) is gated by
  `enable`; with `enable=0` every block holds its state exactly, `I` has no effect. This is
  read directly off the RTL and needs no extra simulation: the recovered blocks have no
  other path from `I`/`enable` to any `d_fNN`.

## 8. Formal rule statement (Star Battle, as actually implemented)

An 11x11 grid. Place stars ("I=1") in cells such that:

1. Every one of the 11 **rows** contains exactly 2 stars (`match_ok == 0`).
2. Every one of the 11 **columns** contains exactly 2 stars (group B / `array_ok`'s column
   half, `left_bottom == 22` is implied).
3. Every one of the 11 **regions** in the map above (letters A-K) contains exactly 2 stars
   (group A / `array_ok`'s region half).
4. No two stars are horizontally, vertically, or diagonally adjacent, i.e. no two stars
   occupy king-move-neighbouring cells, and adjacency does **not** wrap across row/column
   edges (`hist_hit == 0`).

This is a standard "two stars per row/column/region, no touching" Star Battle, except that
(a) the regions are the specific irregular partition derived in step 2 (not a hand-designed
Star Battle region set — a straightforward consequence of how the design's Boolean decode
was synthesized), and (b) adjacency does not wrap around the grid edges.

## 9. Solving and enumerating all solutions

`tools/solve/starbattle.py::solve_all()` builds this exact rule set as a `z3` model: one
Boolean variable per cell, pseudo-Boolean `== 2` constraints for every region/row/column
(rules 1-3), and the `left_top` shift-register + `match_ok`/`hist_hit` FSM (section 4-5)
symbolically unrolled over the 121-cell schedule from section 1, using `z3.Bool` cell
variables as the free `I[k]` inputs and everything else (row/column indices, `check_slot`,
`cnt_done`) as concrete constants per the fixed schedule — i.e. the *exact* equations from
`left_top.v`, not a re-derived "adjacency" rule, so the SAT result does not depend on
sections 4-5's English description being complete. Solving and then blocking each found
model and re-solving until UNSAT gives:

```
== SOLVING (z3, exact FSM/region/column model, enumerating ALL solutions) ==
  solution 1: [(0,7),(0,9),(1,0),(1,5),(2,7),(2,9),(3,0),(3,2),(4,4),(4,6),(5,2),(5,8),
               (6,4),(6,10),(7,1),(7,6),(8,3),(8,10),(9,5),(9,8),(10,1),(10,3)]

total solutions found: 1
```

**The puzzle has exactly one solution.**

```
. . . . . . . * . * .
* . . . . * . . . . .
. . . . . . . * . * .
* . * . . . . . . . .
. . . . * . * . . . .
. . * . . . . . * . .
. . . . * . . . . . *
. * . . . . * . . . .
. . . * . . . . . . *
. . . . . * . . * . .
. * . * . . . . . . .
```

Row/column/region sums: every row and every column has exactly 2 stars (checked
programmatically); every region A-K has exactly 2 stars; no two stars are king-move
adjacent (checked by the exact FSM constraint itself, section 9).

## 10. Validation against `puzzle_recovered.v`

The unique solution's 121-bit `I` sequence (row-major, matching section 1) was fed to a
fresh Icarus simulation of the **real top-level** `rtl_recovered/puzzle_recovered.v`
(all six blocks integrated, `out/solve_a/tb_e2e.v`, generated by
`validate_solution_icarus()`) from reset:

```
POST121 success=0     (immediately after the 121st enabled cycle -- check.v's registered
                        success_latch has not yet been clocked)
FINAL   success=1     (one cycle later, and stays 1 for the remaining cycles simulated)
```

`success` rises exactly where the derivation predicts (one cycle after the 121st enabled
cycle) and stays high, on the real integrated RTL, not just the isolated block model used to
solve. This is the same behavioural model already proven (via `tools/analysis/cone.py`
SAT-equivalence, `docs/STATUS.md` sprint 3) bit-exact to the extracted gate netlist, so this
also constitutes strong (though not independently re-proven here) evidence that `success`
would rise on the real `upstream/puzzle.gds` netlist for this same `I` sequence.

## Summary of hypothesis outcomes (vs. `docs/INTENT.md`)

| Hypothesis | Outcome |
|---|---|
| Row-major cell order, column fastest | **Confirmed** (direct RTL simulation) |
| Group A bins = grid regions | **Confirmed**, but region sizes are irregular (4-28 cells), not all 11 as a naive Latin-square guess might suggest — **that stronger claim is refuted** |
| Group B bins = columns | **Confirmed** |
| `match_ok` = per-row star-count check | **Confirmed exactly**, including that row 0 and row 10 behave identically to interior rows |
| `hist_hit` = adjacency ("stars may not touch, incl. diagonally") | **Confirmed exactly**, and additionally established: no wraparound across row/column edges |
| Left-bottom target = 22 total stars | **Confirmed** (matches lead-review correction already in `docs/INTENT.md`) |
| Every array bin target = 2 | **Confirmed** for all 22 bins |

## Files

* `tools/solve/starbattle.py` — derivation, self-test, solver, validator (re-runnable).
* `out/solve_a/tb_counter.v`, `tb_array.v`, `tb_left_top.v`, `tb_left_top_trace.v` — Icarus
  testbenches used to establish sections 1-5 directly from the RTL.
* `out/solve_a/tb_counter.log`, `tb_array.log` — raw simulation logs cross-checked against.
* `out/solve_a/full_run.log` — full transcript of `python -m tools.solve.starbattle`.
* `out/solve_a/tb_e2e.v` (generated on each run) — end-to-end validation testbench.
