# RETRACE — Approach (pipeline architecture)

This document is the counterpart of TEMPO's `ARCH.md`: how the inverse flow is built,
stage by stage, and why each design choice was made. Requirements are in
`docs/prd/PRD.md`, and checks are in `docs/spec/VERIFICATION.md`.

```
 puzzle.gds ──► S1 instances ──► S2 pins ──► S3 connectivity ──► S4 netlist.v
                   │                              │                   │
          (warm-up DEF oracle)          (KLayout L2N, 2nd extractor)  │
                                                                      ▼
        answer ◄── S8 solve ◄── S7 intent (RTL) ◄── S6 analysis ◄── S5 simulate
          │            │               │                              │
   O[7:0] string   SBY cover     eqy per block              example_inputs.vcd replay
```

Forward flow (TEMPO): RTL → synth → place → route → GDS.
Inverse flow (RETRACE): GDS → cells → nets → netlist → blocks → RTL → intent.
Each inverse stage undoes one forward stage, and the warm-up has files for **every**
forward stage (`00`..`04`), so we can test each inverse stage on its own.

## S1. Instances

* `gdstk.read_gds`, top cell `puzzle`. Walk `top.references`, recording master name,
  origin, rotation, and `x_reflection`.
* Classify masters: logic, physical-only (`tapvpwrvgnd`, `decap`, `fill`), `diode`
  (antenna, electrically a pin on a net), `conb` (tie), vias (connectors, S3),
  `INTERNAL_*` (non-electrical, set aside for S2 of the stretch goals).
* **Oracle:** warm-up DEF `COMPONENTS` (name-free comparison: multiset of
  (master, x, y, orient)). DEF uses DBU and a placement origin at the cell's lower
  left, while GDS gives the transformed origin. The conversion is part of what we are
  testing.

## S2. Pin geometry

* For each master, take pin polygons on li1 (67/16) and attach the nearest 67/5
  label. A pin can be several polygons (e.g. `Q` shows up four times in `dfrtp_2`).
  Supply pins sit on met1 (VPWR/VGND, 68/5) and on nwell/pwell (VPB/VNB).
* Transform into top coordinates per instance.
* **Oracle:** the pin set of each master matches the sky130 LEF, and each pin's
  direction comes from the Liberty/LEF (needed later so we know drivers from loads).

## S3. Connectivity (core of the tool)

* **Conductors:** li1 (67/20), met1..met5 (68..72/20) from polygons, and `PATH`s
  converted to polygons with gdstk. The path end type matters: OpenLane writes
  extended ends, and a wrong extension breaks or creates connections.
* **Connectors:** via cell instances. Flatten each via master: its cut layers
  (mcon 67/44, via 68/44, via2 69/44, via3 70/44, via4 71/44) connect the layer below
  to the layer above where both overlap the cut. We derive this from the cut shapes,
  not the via's name, so an oddly named or custom via still works.
* **Algorithm:** per layer, spatial index (R-tree / sorted sweep) of the shapes;
  union-find merges shapes that touch or overlap. Then cuts merge across layers. Then
  cell pin polygons (li1) join li1 nets. Cell-internal li1 that is not a pin must
  *not* join (it is internal to the cell), so a cell contributes only its pin
  polygons.
* **Outputs:** net table with `{pins:[(inst,pin)], ports:[...], layers, bbox}`;
  diagnostics for floating shapes, single-pin nets, nets with more than one driver,
  and nets with no driver.
* **Second extractor (independent):** KLayout `db.LayoutToNetlist`, deep mode, with
  the same layer stack declared through its own connect rules. Standard cells are
  treated as black boxes whose pins come from their li1 pin shapes. We compare
  as graphs (bipartite instance–net graph, canonical hash / networkx isomorphism),
  so different net names do not matter.

## S4. Netlist emission

* Structural Verilog using real `sky130_fd_sc_hd__*` module names and port names, so
  it simulates with the PDK's functional models unchanged.
* Net names are generated deterministically from geometry (lowest layer, then lowest
  x,y), so the same GDS always yields the same file (Q3).
* **Oracle (warm-up):** Yosys equivalence between `out/adder_demo.v` and
  `upstream/warmup/01_netlist.v`. Both are flattened, `equiv_make`/`equiv_induct`
  run on the matched ports, and flops are matched structurally (`equiv_struct`). The
  fallback is SAT-based sequential equivalence via `miter` + `sat -tempinduct`. This
  catches a swapped A/B pin, which a cell-histogram comparison would miss.

## S5. Simulation

* iverilog (primary) and Verilator (second) with sky130 `*_fd_sc_hd` functional
  models (`USE_POWER_PINS` off, `FUNCTIONAL` defined). An optional pure-Python
  evaluator driven by the Liberty `function` strings works as a third, independent
  simulator.
* Replay `example_inputs.vcd`: drive `clk`, `rst_n`, `enable`, `I` from the file,
  compare `O` and `success` at each clock edge. The VCD has 10 ns cycles and
  `rst_n` rising at 30 ns.
* **Oracle:** every recorded output transition is reproduced. This is the puzzle's
  only external truth before `success`, so it is the gate before any reasoning.

## S6. Analysis (from netlist to structure)

Several lenses, cheapest first:

1. **Cones.** Yosys `select` the fan-in cone of `success`, then of each `O[i]`. The
   brief says the output generator affects `O` but not `success`, which should show
   up as a clean cut between the two cones. That checks our reading of `layout.png`.
2. **Flop map.** 92 flops: 84 async-reset, 4 async-set, 4 no-reset. Group them by
   (a) shared enable/mux structure (`mux2_1` feedback means a load-enable register),
   (b) D-to-Q chains (shift registers fed by `I` while `enable` is high, as in the
   warm-up), and (c) placement cluster. Flops with set vs. reset give the reset value
   of a register, which is often a constant of the puzzle (key, seed, initial state).
3. **Spatial clusters.** The layout "hints at functionality": the hint image shows
   separate blobs, one per block. Cluster instances by placement (DBSCAN on origins,
   weighted by connectivity) and label blocks. Render with S1-stretch overlays.
4. **Functional recognition.** For each combinational block between register groups,
   try candidate functions with SAT: `a+b`, `a^b`, `a==K`, rotations, LFSR taps,
   popcount, S-box lookup. Yosys `extract`/`extract_fa` finds adders. `abc` cut
   enumeration plus truth-table matching handles small blocks (8 inputs or fewer).
5. **FSM extraction.** Yosys `fsm_detect`/`fsm_extract` on the re-read netlist, for any
   control state machine (e.g. a sequence detector gating `success`).

## S7. Intent recovery

* Hand-write readable RTL per block (`rtl_recovered/*.v`) from S6 findings.
* **Oracle:** `eqy` partitioned equivalence against the extracted netlist, one
  partition per block, then the whole design. A recovered RTL is only accepted when
  it is proven equivalent, never because it "looks right".

## S8. Solve

Two independent routes. They must agree.

* **Formal (generative).** `formal/solve.sby`: the extracted netlist, `assume` that
  `rst_n` is low for N cycles then high, `clk` driven by `$global_clock` or a
  multiclock setup, `I`/`enable` free, `cover(success)`. The flop count and the
  shift-register length from S6 bound the BMC depth. The engines are `smtbmc`
  (bitwuzla/yices) and `abc bmc3`. To find every solution, add an `assume` that
  blocks each found `I` sequence and repeat until UNSAT.
* **Analytical.** Invert the recovered RTL (e.g. solve `f(x) == K` from the
  constants found in S6).
* Then simulate the extracted netlist with the answer: `success` must rise, and we
  record `O[7:0]` over time and decode it (the "output string"; its encoding comes
  from the output generator RTL, most likely ASCII per cycle or per enable).

## Tooling decisions

| Choice | Why |
|---|---|
| `gdstk` + our own union-find for extractor 1 | small, transparent, and we own every rule, which is what the writeup is about |
| KLayout Python (`klayout.db`) for extractor 2 | mature L2N engine, independent code base |
| oss-cad-suite already in `~/ttsetup` | Yosys, eqy, SBY, iverilog, Verilator, bitwuzla are there, the same versions TEMPO uses |
| sky130 PDK via `ciel`/`volare`, pinned | need `sky130_fd_sc_hd` LEF, Liberty, Verilog models; only IHP is installed today |
| Python 3 venv at `.venv/` | `gdstk`, `klayout`, `networkx`, `pytest` |

## Mapping to TEMPO practices

| TEMPO practice | RETRACE equivalent |
|---|---|
| ISS vs RTL co-simulation | extractor 1 vs extractor 2; netlist sim vs VCD |
| Yosys `equiv` traced core vs production core | recovered RTL vs extracted netlist (eqy) |
| Mutation campaign (46 planted faults) | planted layout faults: delete a via, shift a wire 5 nm, mirror a cell. Every mutant must be caught by V3/V4/V6 |
| riscv-formal-style ISA checks | SBY cover as solver and per-block equivalence |
| STATUS ledger with counts | same, per stage |
