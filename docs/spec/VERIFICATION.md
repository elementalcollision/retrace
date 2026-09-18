# RETRACE Verification Plan — v0.1

As in TEMPO, verification is the product. Every PRD claim maps to a check below.
Nothing downstream is trusted until the stage above it is green.

## 1. Layers

| ID | Layer | Check | Pass criterion | Location |
|---|---|---|---|---|
| V0 | Lint | generated netlists read by Yosys and Verilator | no errors, no implicit nets | `make lint` |
| V1 | Instances | warm-up GDS instances vs DEF `COMPONENTS` | multiset of (master, x, y, orient) identical | `test/test_instances.py` |
| V2 | Pins | per master: GDS pin labels vs sky130 LEF pins, directions from Liberty | identical sets for all 80 masters in use | `test/test_pins.py` |
| V3 | Warm-up netlist | extracted `adder_demo` vs `01_netlist.v` | Yosys equivalence proven (combinational and sequential) | `test/test_warmup_equiv.py`, `formal/warmup_equiv.ys` |
| V4 | Extractor diversity | gdstk extractor vs KLayout L2N on the puzzle | instance–net bipartite graphs isomorphic | `test/test_diversity.py` |
| V5 | Electrical sanity | supply isolation, port binding, drivers | 0 signal–supply shorts, 13/13 ports bound, every net exactly 1 driver (or a port), 0 floating logic inputs | `test/test_sanity.py` |
| V6 | Behaviour | puzzle netlist replaying `example_inputs.vcd` in iverilog and Verilator | `O` and `success` match at every clock edge after reset | `test/test_vcd_replay.py` |
| V7 | Intent | recovered RTL vs extracted netlist | `eqy` proven per block and top-level | `formal/eqy/` |
| V8 | Answer | SBY cover trace + analytical input | both raise `success` in V6's harness; all-solutions enumeration is finite and documented | `formal/solve.sby`, `test/test_answer.py` |

## 2. Mutation campaign (the TEMPO move)

Plant faults in *copies* of the warm-up and puzzle GDS, one at a time, and require at
least one layer to catch each:

| Class | Example mutant | Expected killer |
|---|---|---|
| Open | delete one `VIA_M1M2_PR` | V3 (warm-up), V4/V6 (puzzle) |
| Short | widen a met2 path to touch its neighbour | V5 (multi-driver) or V3 |
| Near-miss | move a path 5 nm so it stops touching | V3/V6. Tests the touch-vs-overlap rule. |
| Orientation | flip one cell to FS | V1, V3 |
| Pin swap | exchange A/B labels on a `nand2b_2` | V3 (histogram checks miss this) |
| Path end | change a path's pathtype 2 → 0 | V3/V6 |

Target, as in TEMPO: every non-equivalent mutant killed. Survivors get recorded with a
reason.

## 3. Test data

* Warm-up: all five stages are ground truth.
* Puzzle: `example_inputs.vcd` (outputs included) is the only ground truth before the
  answer.
* Synthetic: run small Verilog designs through OpenLane sky130 ourselves (S4 stretch)
  to get more (source, GDS) pairs for regression, in case the warm-up is too small to
  exercise every case. The warm-up has paths on all of met1-met5 (366/230/116/7/5),
  but only about 1/10 as many as the puzzle.

## 4. Metrics tracked in STATUS

Nets, instances, floating shapes, dangling pins, extraction time; V-layer pass counts;
mutants killed / planted; SAT solve time and depth.
