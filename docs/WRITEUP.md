# Reverse-engineering Jane Street's ASIC puzzle: from GDS to "(* TWO STARS *)"

*RETRACE project writeup, 2026-09-19. Repository: `elementalcollision/retrace` (private).*

**Answer.** The chip is an 11 x 11 Star Battle ("Two Not Touch") checker. Clocked in row
by row, one cell per enabled cycle, the only accepted grid raises `success` and makes the
chip print `(* TWO STARS *)` on `O[7:0]`.

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

**How we know.** Every stage of the inverse flow has its own oracle, and nothing downstream was
trusted until the stage above it passed. The answer was found twice, independently: once by
solving the puzzle from rules read out of proven RTL, and once by blind formal search on the
raw extracted netlist. Both routes returned the same 121 bits. A SAT lemma on the netlist
shows the solution is unique over every possible input sequence.

This was done after the contest closed (2026-09-04), as a learning exercise for our own ASIC
project, TEMPO. See [How this was built](#how-this-was-built): it was done end to end with
Claude Code agents, which the contest rules would not have allowed.

## The puzzle

Jane Street published a GDS (`puzzle.gds`), a sample waveform whose inputs do not solve it,
a hint image, and a fully worked warm-up: the same flow applied to a small adder, with
source, netlist, DEF and GDS. The task: recover a netlist from the layout, work out what
it does, find the input that raises `success`, and simulate the "output generator" to read
the answer.

What the GDS actually contains (measured, not assumed):

| | Puzzle | Warm-up |
|---|---|---|
| Process | SkyWater SKY130, `sky130_fd_sc_hd` | same |
| Die | 200 x 300 um | 100 x 100 um |
| Logic cells | 728 (1618 instances with taps, decaps, fill) | 79 (230) |
| Flops | 92: 84 `dfrtp_2`, 4 `dfstp_2`, 4 `dfxtp_2` | 16 |
| Ports | `clk rst_n enable I O[7:0] success` | `clk rst_n en A B S` |
| Names | cell masters and their pin labels intact; instance and net names stripped | same |

That last row sets the shape of the problem. There are no transistors to recognise: every
instance is a named library cell. What was removed is connectivity-by-name, so the
work is to rebuild connectivity from geometry and then understand 728 anonymous gates.

## Thesis: every stage has an oracle

Reverse engineering fails quietly: one missed via merges two nets, and everything you reason
about afterwards is fiction. TEMPO's verification answer to "is the RTL right?" is an
independent model, co-simulation, formal checks and a mutation campaign. RETRACE applies the
same answer to each stage of the inverse flow:

| Stage | Output | Oracle |
|---|---|---|
| Geometry to instances | placed cell list | warm-up DEF, exact (V1) |
| Pins | per-master pin conductors | PDK LEF pin rectangles (V2) |
| Connectivity | flat netlist | warm-up: DEF nets, graph isomorphism with the synthesised netlist, and a formal equivalence proof (V3); puzzle: a second, independent extractor (V4) and electrical sanity (V5) |
| Behaviour | simulation | the sample VCD, in two simulators with two sources of cell models (V6) |
| Intent | readable RTL | SAT per block and an unbounded end-to-end proof against the netlist (V7) |
| Answer | input sequence | two independent solving routes, plus uniqueness (V8) |

Because the warm-up ships every forward-flow stage, each inverse stage was built and proven
on it before touching the puzzle.

## 1. Recon: identify the exact PDK from geometry

The extractor trusts cell masters, so the first check compared each master's polygons in
the GDS against the PDK's copy (`cellcheck.py`, layer by layer, on a 1 nm grid). Against the
OpenLane 2 default PDK (`0fe599b2`), 3 of 69 masters differed: `o211a_2` and `and4b_2` on
poly or licon, the layers that form transistors, and `conb_1` on layer 95/20. Those
differences could have meant tampering. Scanning 25 of the 116 released sky130 builds settled
it: open_pdks **`8afc8346`** matches all 69 puzzle masters and
all 18 warm-up masters exactly. The differences were PDK revisions, and that build became
the pinned PDK.

## 2. Extraction: what a pin really is

Extractor 1 (`tools/retrace/extract.py`, gdstk + shapely) places each instance from the LEF
cell size and its GDS transform, builds pin conductors per master, and merges routing, via
pads and pins with union-find, joining layers only through via cuts. It runs on the puzzle in
0.7 s. The interesting part is what a *pin* is, and each answer below came from a check
failing:

1. **The pin-layer shapes are markers.** In these files `li1` datatype 16 is a 0.17 um square
   at each label, not the pin. A pin is the cell-internal conductor under the label.
   (Found by the DEF net comparison: nets split, and some pins were named wrongly.)
2. **A pin can be a met1 strap over separate li1 islands** (`xor2_2` B, `dfrtp_2` RESET_B),
   and the router lands on the strap. (Same check.)
3. **A pin can be two li1 islands joined only by gate poly** (`a31oi_2` A1: its LEF port
   lists both rectangles). In the puzzle, the router ran a net *through* such a pin. With
   metal-only connectivity, **both** extractors reported an undriven net there. What exposed
   it was a disagreement: KLayout reported an unnamed pin where ours saw nothing. Following
   poly through licon fixed both extractors.
4. **Tie cells reach the supplies through poly resistors.** Once poly was followed,
   `conb_1`'s HI output merged into VPWR. Poly is now cut at the PDK's resistor marker
   (66/15), which only `conb_1` uses.

Extractor 2 (`tools/l2n/`) is KLayout's hierarchical LayoutToNetlist engine with its own
connectivity rules and no shared code. The two agree net for net: warm-up 86/86, puzzle
719/719 multi-pin nets.

## 3. Proving the extraction

On the warm-up (ground truth at every stage):

* **V1:** all 230 placements equal the DEF.
* **V3a:** the net partition over (instance, pin) equals the DEF, 84/84 nets.
* **V3b:** the extracted netlist is a labelled-graph isomorph of the synthesised netlist
  (79 cells, 84 nets).
* **V3c:** a miter of the two netlists, from an asserted reset, is proven sequentially
  equivalent by SymbiYosys `abc pdr`, *without a name mapping*: PDR finds the state
  correspondence itself. A negative control (A0/A1 swapped on one `mux2_1`) fails. That
  matters, because a proof that passes instantly is also what a vacuous proof looks like.

On the puzzle (no ground truth):

* **V4:** the two extractors agree exactly.
* **V5:** power and ground are separate and reach all 1618 instances; every signal net has
  exactly one driver; no logic input floats. The only unloaded outputs are 15 `clkbuf_4`
  clock-tree dummy loads and unused tie outputs.
* **V6:** the extracted netlist replays the sample VCD with 1248 checks and 0 errors in
  Icarus (PDK Verilog models) and in Verilator (logic built from the Liberty functions).
  The sample prints `TRY AGAIN`, twice.

**Mutation campaign.** Does any of this notice a wrong extraction? 130 mutants over 10
operators, on both designs: deleted vias, near-miss wire shifts, shorts, flipped cells,
same-footprint master swaps, swapped pin labels, transistor-level tampering, deleted art,
changed path end caps, and inserted vias. Result: 90 killed, 39 equivalent (no electrical change), 1 survived. On the
warm-up, the ground-truth checks V3a and V3b alone kill 100% of the non-equivalent mutants. On
the puzzle, electrical sanity (67%) and the two simulators (59% and 57%) carry the weight.
The survivor is a `nor2_2` swapped for a `nand2_2`. That is not an extraction error: it is a
different chip, which only a behavioural oracle can see, and the sample VCD does not exercise
that gate. Once the recovered design existed, proving it against the mutant layout killed this
mutant as well.

## 4. Understanding: from 92 flops to six blocks

The fan-in cones gave the first cut: `success` is the output of a single flop, and each `O[i]`
is purely combinational logic over 16 flops (23 across the byte: the output generator's 12, the
star counter's 8 and the decision block's 3). The strongly connected components of the
flop-to-flop dependency graph, together with placement, gave six blocks: `counter` (9 flops),
`array` (44), `left_top` (16), `left_bottom` (8), `check` (3) and `outgen` (12). The layout
really is "arranged to hint": each block is a cluster on the die.

**The V7 harness** (`tools/analysis/cone.py`) cuts the netlist at the flops. For each block it
exports the exact gate logic as a "gold" module (inputs: ports and current flop values;
outputs: next flop values and owned outputs). Recovered RTL for a block is accepted only if a
SAT miter proves it equal to the gold module. Six agents recovered one block each. Six
independent skeptics, one per block, re-ran each proof and tested each claim, and three blocks
got a repair pass.
An integration agent assembled `puzzle_recovered`. The whole design is then proven equal to
the extracted netlist by `abc pdr` (`tools/analysis/e2e.py`), with no assumption beyond the
initial reset. It takes about 2 s because the miter asserts all 92 flop pairs equal, not just
the outputs, which makes the property 1-inductive given the block proofs. Changing one byte of
a message makes the proof fail.

Three errors were caught in review, and each one is a lesson:

* **The harness itself was blind to `O`.** Nets named after bus bits were emitted as
  `wire O[3];`, which Verilog reads as a separate array, so the gold `O` was undriven and
  anything matched it. The self-test ("gold renamed as recovered passes") had the same defect
  on both sides. The outgen reviewer found it. The fix now carries a test that a flipped `O`
  bit fails.
* **Bit order: 11 versus 22.** The check block compares eight counter flops against the
  pattern `0000_1011` in flop-id order. The integration draft read that as "the counter must
  equal 11". The counter's real bit weights run in a different order, and simulating the proven
  counter from reset reaches the pattern after exactly 22 increments. 22 is also the only value
  consistent with the other conditions.
* **The same trap in the output generator.** "BIG BANG" is selected by the raw byte `0xAE`,
  with yet another bit order. That byte is the count 121: every cell lit.

## 5. What the chip is

| Block | Flops | Function |
|---|---|---|
| counter | 9 | base-11 column digit and row digit (0-10 each), plus a sticky `done` flag after 121 enabled cycles |
| array | 44 | 22 two-bit saturating bins: 11 irregular region masks and 11 column decodes |
| left_top | 16 | a 12-cell shift register of `I` (the current neighbourhood), with two sticky error flags: a per-row star count checked at the end of each row, and touching stars |
| left_bottom | 8 | star counter |
| check | 3 | the one-shot decision on the cycle `done` first rises; `success` latch; "touching" latch |
| outgen | 12 | message ROMs and a scrambler (an LFSR over `I`); prints the message after the decision |

`success` is set if and only if, at the decision: exactly 22 stars were entered; every
region and every column holds exactly 2; the row flag and the touching flag are clear. The
messages tell the story: `EMPTY SKY` for 0 stars, `BIG BANG` for all 121 cells, `TWO NOT
TOUCH` when everything is right except that stars touch, `TRY AGAIN` otherwise. On success,
`O` prints a table XORed with the scrambler, so the text is only readable for the right grid.

The region map (letters are the 11 regions, sizes 4 to 28 cells):

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

## 6. Solving it twice

* **Route A, analytical** (`tools/solve/starbattle.py`): derive every rule from the proven RTL
  by simulation (cell order, region masks, column bins, the exact behaviour of both flags,
  including that adjacency is king-move with no wraparound). Encode the rules in z3,
  including the flag logic unrolled over the 121-cell schedule, and enumerate by blocking each
  model. Result: exactly one solution.
* **Route B, formal** (`tools/solve/formal_solve.py`): no interpretation at all. SymbiYosys
  on the extracted netlist with `cover(success)` or `assert(!success)`, in four engines (yices,
  bitwuzla, `abc bmc3`, yices BMC). All four reach `success` at step 123 in 4 to 12 s. A second
  run adds a sticky "differs from the found sequence" register: no other sequence reaches
  `success` within depth 135.

The two agents could not see each other's work, and they returned the same 121 bits.

**Uniqueness over every input.** Both routes assume `enable` stays high through the 121
cells. A SAT lemma on every block's gold cone, i.e. on the netlist logic, closes that gap:
before the decision, a cycle with `enable` low changes no flop (the four no-reset flops are
forced to 0). A negative control fails. A run with gaps is therefore the same run with the
gaps removed, whatever `I` does during them, and after the decision the outcome is latched.

**Confirmation.** The answer was run on three models: the netlist in Icarus with the PDK
models, the netlist as Liberty logic in Verilator, and the recovered RTL. A separately written
testbench replayed it on a freshly extracted netlist with a 5-cycle reset, 17 `enable` gaps and
the wrong bit on `I` during every gap. Every run shows `success` high and the 15 bytes
`28 2a 20 54 57 4f 20 53 54 41 52 53 20 2a 29`: **`(* TWO STARS *)`**.
`answer/solution.vcd` is the winning run, in the format of the sample.

## Easter eggs

* A row of rectangles below the die, in two widths with a 1:3 ratio: Morse code for
  **PER ARENAM AD ASTRA**, "through sand to the stars" (silicon, then the Star Battle).
* 1366 met2 squares, 0.3 um each, draw a 57 x 57 logo of four broken concentric rings,
  in both the puzzle and the warm-up. They extract as three floating islands that touch no
  signal.
* The sample VCD is dated `Sat Dec 31 23:59:60 2016`, the 2016 leap second, and its version
  string reads "Leave no stone unturned!".
* `EMPTY SKY`, `BIG BANG` and `TWO NOT TOUCH` are reachable in their own right. Simulated on
  the extracted netlist: 0 stars prints `EMPTY SKY`, all 121 cells print `BIG BANG`, and a grid
  that obeys every rule except that stars touch prints `TWO NOT TOUCH` (`test/test_messages.py`).

## Lessons that transfer

1. **Make every proof prove it can fail.** Three of our "passes" would have been vacuous
   without a planted negative: the warm-up PDR proof, the per-block V7 harness (which really
   was blind to `O`), and the uniqueness lemma.
2. **Disagreement is the most valuable signal.** The poly-joined pin bug fooled both
   extractors in the same way. Only a difference in how each *reported* that pin exposed it.
   Two independent implementations of the same step are worth their cost.
3. **Bit order is where interpretation goes wrong.** The gates were proven correct. The
   error was in reading a correct pattern as a number.
4. **Separate "the extraction is right" from "this is the chip".** Extraction checks are
   blind to a legitimate different chip. The recovered, proven RTL is what turns into a
   regression oracle for that.
5. **Agents with skeptics.** Agents drafted, independent agents tried to refute, and the
   lead re-ran every decisive check. Every error listed in this writeup was caught by an
   oracle, a reviewer or a negative control, not by the one who made it. This writeup was
   itself fact-checked claim by claim by three more agents, which found 13 problems, all
   fixed, including a reproduction command that did not work from a clean checkout.

## How this was built

RETRACE was run by Claude Code (Claude Opus 5 as lead, Sonnet 5 subagents for parallel
work), directed by the project owner, on 2026-09-18 and 19, after the contest deadline. The
contest rules, as stated in the announcement post, prohibited feeding the puzzle files to AI
tools and using AI for writeups, so this is not a contest entry. The approach kept one line on purpose: AI wrote and ran *tools*, and the tools
did the analysis, so every result here can be reproduced from the repository without an AI in
the loop. The two multi-agent phases used 21 subagent runs (about 3.4 M subagent tokens):
intent recovery and the mutation campaign took 83 minutes of wall time, and solving took 31
minutes.

Stack: gdstk, shapely, KLayout (Python), Yosys, SymbiYosys (abc pdr, abc bmc3, smtbmc with
yices and bitwuzla), Icarus Verilog, Verilator, z3, networkx; sky130 via ciel
(open_pdks `8afc8346`).

## Reproduce

```bash
.venv/bin/python -m pytest -q                       # V1-V8, uniqueness, mutation smoke tests
.venv/bin/python -m tools.retrace.extract upstream/puzzle.gds --verilog out/puzzle.v
.venv/bin/python -m tools.analysis.e2e              # recovered RTL == extracted netlist
.venv/bin/python -m tools.solve.formal_solve        # route B
.venv/bin/python -m tools.solve.starbattle          # route A
.venv/bin/python -m tools.analysis.eastereggs       # Morse strip and pixel art
```

Details: `docs/STATUS.md` (ledger), `docs/INTENT.md` (design), `docs/MUTATION.md`,
`docs/SOLUTION.md`, `docs/SOLVE_ANALYTICAL.md`, `docs/SOLVE_FORMAL.md`.
