# SOLUTION

**The puzzle's decision output, driven from reset with the winning 121-bit `I`
sequence and simulated to completion on three independent models, reads:**

```
(* TWO STARS *)
```

`success` rises one cycle after the 121st enabled cycle and stays high for the
rest of the run (checked for 39 further cycles, no drop). The message is 15
ASCII bytes, one per clock, printed starting the cycle after the decision:
`28 2a 20 54 57 4f 20 53 54 41 52 53 20 2a 29` = `( * ' ' T W O ' ' S T A R S ' '
* )`.

## The grid

An 11x11 Star Battle ("Two Not Touch") solution: exactly 2 stars per row, per
column, per region; no two stars king-move adjacent.

```
.......*.*.
*....*.....
.......*.*.
*.*........
....*.*....
..*.....*..
....*.....*
.*....*....
...*......*
.....*..*..
.*.*.......
```

`I`-bit string (row-major, row 0 first, column fastest), the literal 121 bits
driven into `I` on the 121 enabled cycles:

```
0000000101010000100000000000010101010000000000001010000001000001000000100000101000010000000100000010000010010001010000000
```

Star coordinates (row, col), 0-indexed: (0,7) (0,9) (1,0) (1,5) (2,7) (2,9)
(3,0) (3,2) (4,4) (4,6) (5,2) (5,8) (6,4) (6,10) (7,1) (7,6) (8,3) (8,10)
(9,5) (9,8) (10,1) (10,3) — 22 stars total.

### Region map (Route A, derived from `rtl_recovered/array.v`'s group-A bins)

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

Region sizes are irregular (4 to 28 cells: `{A:8, B:11, C:4, D:9, E:5, F:7,
G:14, H:8, I:21, J:28, K:6}`), not the equal-11 shape a naive hypothesis would
predict — `check.v` only ever tests "region bin == 2", which needs no
particular region size. Region *contiguity* was not checked (see
`docs/SOLVE_ANALYTICAL.md`'s open questions); it wasn't required for
correctness.

## Two independent routes, one answer

**Route A (analytical)** — recovers every rule (row==2, column==2, region==2,
no-adjacency FSM) from `rtl_recovered/*.v` by direct translation plus
independent Icarus simulation of the actual `.v` files, encodes the exact
rules as a z3 SAT model, and enumerates ALL solutions by blocking each found
model and re-solving to UNSAT. Result: **exactly 1 solution**, found and
proven unique over the exact RTL-derived rule set. Full method and evidence:
`docs/SOLVE_ANALYTICAL.md`.

**Route B (formal)** — treats `success` as an opaque netlist output on the
gate-level extracted netlist (`out/solve_b/puzzle.v`, freshly re-extracted
from `upstream/puzzle.gds`) and runs SymbiYosys BMC/cover with 4
engine/mode combinations (`cover_yices`, `cover_bitwuzla`, `bmc_abc`,
`bmc_yices`) to find an `I` sequence that makes `success` reachable, then a
second harness with a sticky `differs` register to check no *other* sequence
within the same bound also succeeds. Result: all 4 engines agree success is
reachable and land on the identical winning trace; all 4 engines agree no
differing sequence reaches success within the explored bound (depth 135,
`rst_n` low only in cycle 0, `enable` high every cycle thereafter with no
gaps, `I` free). Full method and evidence: `docs/SOLVE_FORMAL.md`.

**Agreement.** Route A's z3 solution and Route B's blind gate-level BMC
witness are **bit-for-bit identical**: same 121-bit `I` sequence
(`out/solve_a/full_run.log`'s `solution 1` vs. `out/solve_b/solve_found_bits.vh`
/ `out/solve_b/solve_found.json`), same 22-star grid, same row/column/region
counts. Route A derives its answer from the puzzle's actual rules (Star
Battle); Route B never uses any rule interpretation, just blind search on the
gate netlist — the two are independent by construction (different tool,
different design representation, different search method), and they agree.
No discrepancy to explain.

**Uniqueness for every input pattern (lead review, 2026-09-19).** Both routes assume a
contiguous run: Route B holds `enable` high after reset, and Route A unrolls the rules over
the fixed 121-cycle schedule. `test/test_uniqueness.py` removes that assumption. It proves by
SAT on every block's gold cone, i.e. on the extracted netlist logic, that before the decision
(`cnt_done` = 0, `armed` = 0) a cycle with `enable` = 0 changes no flop (the four no-reset
`pos` flops are forced to 0). A negative control (the counter with `enable` free) fails as it
must. So any run with `enable` gaps behaves exactly like the same run with the gaps removed,
whatever `I` does during the gaps. After the decision, `armed` is sticky and `success` is
latched (check block, proven equal to the netlist), so nothing later can change it, and
Route B's depth bound (decision at step 123, bound 135) loses nothing. A longer reset only
holds the reset state. **The solution is unique over all input sequences.**

**Independent replay (lead review).** A separately written testbench on a freshly extracted
netlist (Icarus, PDK models) used a 5-cycle reset, 17 `enable` gaps with the *wrong* bit on
`I` during each gap, and `enable` = 0 with `I` = 1 after the last cell. `success` rose and `O`
printed `(* TWO STARS *)` (`out/lead/tb.v`). The grid was also checked directly against the
rules: 22 stars, 2 per row, column and region, no two touching.

## Simulation evidence (this task)

Driven from reset — `rst_n` low for 3 cycles, then `enable=1` for 121 cycles
with `I` = the bit string above (row-major, column fastest), then `enable=0`
for 40 more cycles while the message prints — on three independent models,
all built fresh in this session:

| Model | Tool | Cell behaviour | Result |
|---|---|---|---|
| (a) extracted netlist | Icarus (`-DFUNCTIONAL -DUNIT_DELAY=`) | PDK Verilog cell models (`pdk/sky130_fd_sc_hd/verilog/{primitives,sky130_fd_sc_hd}.v`) | success rises, stays high; message = `(* TWO STARS *)` |
| (b) extracted netlist, Liberty-flattened | Verilator | `yosys read_liberty -ignore_miss_func` + `flatten` | identical: same cycle, same 15 bytes |
| (c) `rtl_recovered/puzzle_recovered.v` | Icarus | recovered RTL, no PDK models | identical: same cycle, same 15 bytes |

All three agree exactly: `success` first reads 1 on the cycle immediately
after the 121st enabled cycle (matching Route A's "`cnt_done` first 1 at
K=122, decision cycle K=123" and Route B's "all 4 engines converge on step
123"), and stays 1 for the rest of each run (39 further cycles checked, 0
drops). The message bytes are byte-for-byte identical across all three
models. **Dropping `enable` immediately after the 121st cell does not
prevent the decision or the message print** — both are driven off the
counter's done flag and the `armed`/`pos` playback register (`check.v`,
`outgen.v`), not off `enable` — confirmed empirically here, not just by RTL
reading.

Reproduced by `test/test_answer.py` (`pytest test/test_answer.py`, ~5 s):
drives models (a) and (c) (and (b) when Verilator is present) from reset and
asserts `success` rises and holds and the decoded message equals
`(* TWO STARS *)`; also replays `answer/solution.vcd` on the extracted
netlist and asserts 0 mismatches.

## `answer/solution.vcd`

Generated from simulation (a) above (Icarus, extracted netlist, PDK models),
same variables as `upstream/example_inputs.vcd` (`clk`, `rst_n`, `enable`,
`I`, `O[7:0]`, `success`), same VCD idiom (one `$scope module ... $end` /
`$var` / `$upscope` block per variable, `$dumpall` initial dump, then
`#`-delimited value changes). Self-consistency check: replaying it on the
extracted netlist with `tools/retrace/vcdtb.py`'s testbench generator gives
**`VCD-REPLAY checked=660 errors=0`** — the recorded trace and the netlist
that produced it agree exactly when re-simulated, i.e. the file is a faithful,
internally consistent record of the run (not a proof of the *answer*, which
rests on the two solve routes and the 3-model cross-check above).

## Message decode

| Byte # | Hex | ASCII |
|---|---|---|
| 1 | 28 | `(` |
| 2 | 2a | `*` |
| 3 | 20 | ` ` |
| 4 | 54 | `T` |
| 5 | 57 | `W` |
| 6 | 4f | `O` |
| 7 | 20 | ` ` |
| 8 | 53 | `S` |
| 9 | 54 | `T` |
| 10 | 41 | `A` |
| 11 | 52 | `R` |
| 12 | 53 | `S` |
| 13 | 20 | ` ` |
| 14 | 2a | `*` |
| 15 | 29 | `)` |

**`(* TWO STARS *)`**

This is `rtl_recovered/outgen.v`'s success-branch message table, read through
the scrambler state that `I` (the winning bit sequence above) drives it to
while shifting in the 121 cells — i.e. the puzzle's answer is only readable
because this specific `I` sequence is the one both solve routes found. (The
design's other canned messages — `TRY AGAIN`, `EMPTY SKY`, `BIG BANG`, `TWO
NOT TOUCH` — are fixed/unencrypted and unrelated to the actual solution; see
`rtl_recovered/outgen.v` and `docs/INTENT.md`.)
