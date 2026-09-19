# RETRACE — Product Requirements Document

**Project:** RETRACE, a GDS-to-intent reverse-engineering toolchain, first
applied to the Jane Street ASIC puzzle
**Challenge:** Jane Street "Can you reverse-engineer an ASIC?"
(https://blog.janestreet.com/can-you-reverse-engineer-an-asic/),
files at https://github.com/janestreet/asic-puzzle-2026 (vendored read-only in `upstream/`)
**Process of the target:** SkyWater SKY130, `sky130_fd_sc_hd` standard cells from
open_pdks `8afc8346` (identified from cell geometry), OpenLane-style flow (Tiny Tapeout lineage)
**Deadline:** the competition closed 2026-09-04. This is a post-competition learning
project with no external deadline, so milestones below are internal.
**Sister project:** TEMPO (`~/Claude_Primary/Jane_Street_ASIC`), the forward
design flow. RETRACE is the inverse flow, and part of its payoff is a reusable,
independent layout-to-netlist check for TEMPO (see §5, G6).
**Status:** v0.1 draft, 2026-09-18

---

## 1. Problem statement (from the brief)

Jane Street gives a GDS layout and nothing else of the real design: no source, no
netlist, no net names. It also gives sample input waveforms that do not solve the
puzzle, a hint image, and a fully worked warm-up (source, netlist, powered netlist,
DEF, GDS) run through "a very similar flow". Solvers must:

1. recover a netlist from the physical layout,
2. work out what the circuit does,
3. simulate it, including the "output generator" block, to find the output string, and
4. find the input that drives `success` high (after toggling `rst_n`).

The brief says "the circuit is physically arranged to hint at its functionality" and
that one region (the output generator) affects `O[7:0]` but not `success`. Judging
rewarded interesting write-ups and techniques over speed.

## 2. Ground truth measured on 2026-09-18 (not assumed)

Measured with `gdstk` on `upstream/puzzle.gds` and `upstream/warmup/04_final.gds`.

| Fact | Puzzle | Warm-up |
|---|---|---|
| Top cell | `puzzle` | `adder_demo` |
| Extent | 200 x 300 um die, plus a strip down to y = -52.72 | 100 x 100 um |
| Ports (labels on met3, 70/5) | `clk`, `rst_n`, `enable`, `I`, `O[7:0]`, `success` | `clk`, `rst_n`, `en`, `A`, `B`, `S` |
| Logic cells (excl. tap/decap/fill/diode) | **728** | ~57 |
| Flops | 84 `dfrtp_2` (async reset), 4 `dfstp_2` (async set), 4 `dfxtp_2` (no reset): **92** | 16 `dfrtp_2` |
| Distinct cell masters | 80 (all `sky130_fd_sc_hd__*_2`/`_1` plus vias) | 26 |
| Routing | paths on met1..met5 (68..72 / 20): 3707 / 2421 / 868 / 47 / 18; via cells `VIA_L1M1_PR_MR`, `VIA_M1M2_PR`, `VIA_M2M3_PR`, `VIA_M3M4_PR`, power `VIA_via*` | same styles |
| Std-cell masters | **kept intact, including pin labels on li1 (67/5) and pin shapes (67/16)** | same |
| Non-standard cells | `INTERNAL_3` (x21), `INTERNAL_7` (x15): single rectangles on layer 200/0 placed in a row at y = -52.72, outside the die. Probably a drawing or message (easter egg), not logic. | none |

**What this means:** the hard part is *connectivity*, not recognizing devices. Every
instance is a named SKY130 cell with labelled pins, so there is no transistor-level
extraction. What was removed is instance and net names, and with them the
hierarchy.

The sample VCD (`example_inputs.vcd`) records **both inputs and outputs** (`O`,
`success`) with a 10 ns clock, so it is a golden trace for checking extraction
end to end.

## 3. Product thesis: "every stage has an oracle"

Reverse engineering usually fails quietly: one missed via merges two nets, and the
netlist you then reason about is subtly fiction. TEMPO's answer to "is the RTL
right?" was an independent model plus co-simulation, formal checks, and mutation
testing. RETRACE applies the same idea to each stage of the inverse flow:

| Stage | Output | Oracle |
|---|---|---|
| Geometry to instances | instance list (master, origin, orientation) | warm-up DEF `COMPONENTS` (exact) |
| Instances + routing to nets | flat cell-level netlist | warm-up `01_netlist.v` (**equivalence-checked, not just compared**); a second, independent extractor (KLayout L2N) on the puzzle |
| Netlist to behaviour | simulatable Verilog | the puzzle's `example_inputs.vcd` (outputs must match every cycle) |
| Behaviour to intent | readable RTL | formal equivalence (Yosys `equiv`/`eqy`) against the extracted netlist |
| Intent to answer | input sequence | `success` goes high in the simulation of the *extracted netlist*, cross-checked with two simulators |

A stage is not "done" until its oracle passes. Because the warm-up has ground truth at
every stage, the toolchain gets built and proven on it before it touches the
puzzle.

## 4. Why this is worth doing after the deadline

* **Cross-training for TEMPO.** RETRACE runs the TEMPO flow backwards. A generic
  GDS-to-netlist extractor lets us check TEMPO's own sign-off GDS independently of
  LibreLane's LVS (Magic/Netgen).
* **Verification practice on an adversarial target.** The design is unknown and there
  is no spec, so the oracles are the only truth. That is the discipline TEMPO's
  verification plan argues for.
* **Formal methods as a solver, not just a checker.** Finding an input that raises
  `success` is a BMC cover property. It is a good test case for SymbiYosys used
  generatively.
* **Writeup value.** The contest judged technique, so the deliverable is a method
  others can reuse, not only a string.

## 5. Goals and non-goals

### Goals (v1.0)
G1. **Extractor:** GDS to a flat cell-level structural Verilog netlist for any
    `sky130_fd_sc_hd` OpenLane GDS. Proven on the warm-up: equivalence with
    `01_netlist.v` modulo net names.
G2. **Independent second extractor** (KLayout `LayoutToNetlist` with cell pins as
    terminals) whose puzzle netlist is graph-isomorphic to G1's.
G3. **Behavioural match:** the extracted puzzle netlist, simulated with the sky130
    functional models, reproduces `O[7:0]` and `success` in `example_inputs.vcd` on
    every sampled cycle.
G4. **Intent recovery:** readable, commented RTL of each functional block (word
    registers, datapath, FSM/checker, output generator), each proven equivalent to its
    netlist slice. Uses placement clusters, since the layout is "arranged to hint".
G5. **Solution:** the input stream that raises `success`, found at least two ways
    (analytical from G4, and a SymbiYosys cover/BMC on the raw netlist), plus the
    `O[7:0]` string the output generator produces.
G6. **Transfer to TEMPO (stretch into v1.0):** port the extractor to the IHP
    `sg13cmos5l` cells and check that TEMPO's sprint-6h GDS matches its LibreLane
    netlist. That is an LVS independent of Netgen.
G7. **Writeup:** a technique-first report (layers, oracles, failures found) in the
    style of TEMPO's STATUS and VERIFICATION ledgers.

### Stretch
S1. A layer-aware viewer overlay: colour extracted nets or blocks on `layout.png`-style
    renders. Useful for "the layout hints at function" and for the writeup.
S2. Decode the `INTERNAL_*` strip (layer 200/0) and the other easter eggs the brief
    mentions, including the `$date`/`$version` fields of the VCD.
S3. Automatic structure recognition: find shift registers, adders, comparators,
    counters, and LFSRs in an anonymous netlist by pattern and SAT-based matching.
    This generalises beyond this puzzle.
S4. Round trip: run our recovered RTL through OpenLane/LibreLane for sky130 and
    compare cell histograms and area with the puzzle, as a sanity check on synthesis
    style.

### Non-goals
* No transistor-level extraction or device recognition. The masters are named, and we
  treat them as trusted, which `tools/retrace/cellcheck.py` justifies by comparing every
  master's geometry with the pinned PDK (all identical for `8afc8346`).
* No timing or parasitics. Simulation is zero-delay functional plus the flop
  semantics. The puzzle is a logic puzzle, not a timing one.
* No general-purpose LVS product. RETRACE supports standard-cell digital designs from
  OpenLane-family flows.

## 6. Users

* **Us, now:** learn the inverse flow and strengthen TEMPO's verification story.
* **Future puzzle/CTF work:** hardware RE challenges built on open PDKs.
* **TEMPO reviewers/judges:** an independent layout check is a verification artifact.

## 7. Requirements

### 7.1 Functional
| ID | Requirement | Verification |
|---|---|---|
| F1 | Parse GDS, resolve the top cell, flatten references with correct orientation/mirroring; list instances as (master, x, y, orient) | warm-up: exact match with DEF `COMPONENTS` placements (V1) |
| F2 | Pin geometry per master from the GDS's own cell definitions (li1 67/16 pin shapes + 67/5 labels), cross-checked against the PDK LEF | every master's pin set equals its LEF pin set (V2) |
| F3 | Connectivity: li1, met1..met5 conductors; the via cells and the power vias as inter-layer connectors; union-find over overlapping or touching shapes per layer | warm-up netlist equivalence (V3); puzzle: two extractors isomorphic (V4) |
| F4 | Power/ground separation: VPWR/VGND/VPB/VNB nets identified and excluded from signal nets; tie cells (`conb_1`) resolved to constants | no signal net touches a supply (V5) |
| F5 | Port binding from top-level labels (met3 70/5) to nets | all 13 ports bound, no port shorted (V5) |
| F6 | Emit structural Verilog (sky130 cell instances, generated net names like `n_<layer>_<x>_<y>`) and a JSON graph | Yosys/Verilator read clean (V0) |
| F7 | Simulation harness: iverilog + Verilator with sky130 functional models; VCD replay of `example_inputs.vcd` | V6 |
| F8 | Analysis kit: Yosys-based slicing (fan-in cone of `success`, of each `O[i]`), flop grouping by placement and connectivity, FSM extraction, spatial clustering keyed to `layout.png` regions | V7 (equivalence of each recovered block) |
| F9 | Solver: SymbiYosys `cover(success)` on the extracted netlist with `rst_n` sequencing assumptions; answer trace exported as VCD and as an `I`/`enable` bit string | V8 |
| F10 | Report generator: per-stage metrics (nets, fanout, dangling pins, unmatched shapes) for STATUS | review |

### 7.2 Quality bars
| ID | Requirement |
|---|---|
| Q1 | Zero unexplained shapes: every conductor shape belongs to a net or is listed as floating, with a reason (fill, antenna diode, obstruction) |
| Q2 | Zero dangling input pins on logic cells; any floating output is listed |
| Q3 | Deterministic output: same GDS gives a byte-identical netlist |
| Q4 | Full puzzle pipeline in under 60 s on this Mac |

### 7.3 Deliverables
D1 extractor (`tools/retrace/`), D2 second extractor (`tools/l2n/`), D3 generated
netlists (`out/`), D4 sim harness and tests (`test/`), D5 formal solver files
(`formal/`), D6 recovered RTL (`rtl_recovered/`), D7 docs (`docs/`: PRD, APPROACH,
VERIFICATION, STATUS, WRITEUP), D8 IHP port for TEMPO (G6).

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Missed or false connection (via off-grid, touching vs. overlapping shapes, path end-caps/extensions) makes the netlist silently wrong | two independent extractors (V4) + warm-up equivalence (V3) + VCD behavioural match (V6). All three must pass before any reasoning. |
| GDS `PATH` semantics (width, pathtype end extension) handled wrong | convert paths to polygons with gdstk (honours pathtype), property-test on the warm-up against DEF wire segments |
| Cell orientation or mirroring bugs put pins in the wrong place | F1 checked against DEF orientation (N/FS/etc.) for all warm-up cells before the puzzle |
| Puzzle flow differs from the warm-up ("very similar", not identical) | the puzzle has its own oracle (the VCD), plus the tool reports every unmatched shape (Q1) |
| sky130 PDK version may not match the puzzle's flow | resolved 2026-09-18: `cellcheck.py` scan of 24 released versions; open_pdks `8afc8346` matches all 69 puzzle masters and all 18 warm-up masters exactly, and is pinned (STATUS) |
| A cell master was tampered with at transistor level (the extractor trusts masters) | layer-by-layer comparison of every master with the PDK GDS; any diff is escalated to a Magic SPICE extraction of that cell |
| Obfuscated logic (such as a hash) is too big to invert by hand | formal solver (F9) is the primary path, analysis is secondary; if SAT is slow, use BMC depth from the flop-count/structure analysis and `abc pdr` |
| The output generator depends on reaching `success` by the *intended* input, not any satisfying input | enumerate all solutions (block each found trace, re-run cover), compare output strings, prefer the one consistent with the recovered intent |
| Spoilers: public writeups exist now that the deadline has passed | decision in §11. Default: clean room until G5, then read other writeups for the retrospective. |
| Contest rule said "don't feed puzzle files to AI". Moot after the deadline, but relevant to how we present the writeup. | AI writes and runs the *tools*, and the tools do the analysis. We keep this separation so the writeup's method stays honest and reproducible. |

## 9. Milestones

| When | Milestone |
|---|---|
| Sprint 0 | PRD, APPROACH, VERIFICATION, STATUS; sky130 PDK installed; repo skeleton; recon facts (§2) |
| Sprint 1 | Extractor v0.1 on the warm-up: V1-V3 green (instances, pins, netlist equivalent to `01_netlist.v`) |
| Sprint 2 | Puzzle extraction: V4-V6 green (two extractors agree, VCD replay matches) |
| Sprint 3 | Intent recovery: block map, recovered RTL, per-block equivalence (V7) |
| Sprint 4 | Solve: formal cover plus analytical solution, output string, all-solutions check (V8) |
| Sprint 5 | Writeup; stretch S1-S3; start the IHP port for TEMPO (G6) |

## 10. Success criteria

1. `success` goes high in simulation of **our extracted netlist**, reproduced by two
   simulators and one formal trace.
2. Every stage's oracle is green, recorded in `docs/STATUS.md` with numbers.
3. Recovered RTL of every block is formally equivalent to its netlist slice.
4. A writeup a stranger could follow to reverse-engineer a different sky130 GDS.
5. (G6) TEMPO's sign-off GDS is checked by RETRACE against its netlist.

## 11. Open decisions

| # | Decision | Default |
|---|---|---|
| 1 | Clean room (no public writeups) until solved? | Yes. Read them afterwards for the retrospective. |
| 2 | Python (`gdstk` + union-find) as the primary extractor and KLayout L2N as the second, or the reverse? | Python primary (we own every rule), KLayout as the independent check |
| 3 | Put RETRACE under git and in the same GitHub org as TEMPO? | Done: `elementalcollision/retrace`, public since 2026-09-19 after the writeup |
| 4 | Start G6 (IHP port) as soon as the warm-up passes, or after the solve? | After the solve |
