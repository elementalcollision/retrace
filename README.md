# RETRACE

The inverse of an ASIC flow: GDS to cells, nets, a netlist, readable RTL and intent, with an
oracle at every stage. Built to reverse-engineer Jane Street's ASIC puzzle
(https://blog.janestreet.com/can-you-reverse-engineer-an-asic/, closed 2026-09-04), then
ported to IHP `sg13cmos5l` as an independent LVS for our own Tiny Tapeout design, TEMPO.

**Spoiler warning:** this repository contains the puzzle's solution.

* Writeup: https://theelementalcodices.com/artifacts/retracing-two-stars/ (source: `docs/WRITEUP.md`)
* Answer: `docs/SOLUTION.md`, and the winning run as `answer/solution.vcd`

## What is here

| Path | What it does |
|---|---|
| `tools/retrace/extract.py`, `tech.py` | extractor 1: GDS to cell-level netlist (gdstk + shapely), technology tables for sky130 HD and IHP sg13cmos5l |
| `tools/l2n/` | extractor 2: KLayout LayoutToNetlist, independent; partition comparison |
| `tools/retrace/cellcheck.py` | compare a design's cell masters with a PDK, layer by layer (PDK fingerprinting) |
| `tools/retrace/vcdtb.py` | turn a VCD into a self-checking testbench |
| `tools/retrace/mutate.py`, `test/mutation/` | layout-mutation campaign for the checks |
| `tools/analysis/cone.py`, `e2e.py` | per-block SAT and end-to-end PDR proofs of recovered RTL against the netlist |
| `rtl_recovered/` | the recovered, proven RTL of the puzzle |
| `tools/solve/` | the two solving routes (z3 on the recovered rules; SymbiYosys on the netlist) |
| `tools/tempo/lvs.py` | LVS of TEMPO's sign-off GDS against its DEF, netlist and LEF |
| `tools/viz/` | layout overlays: the puzzle's die by recovered block, TEMPO's by RTL module, and where an LVS found something (`docs/figures/`) |
| `tools/tempo/faults.py` | six planted layout faults (opens, shorts, a supply short and a rail cut off from the grid), each of which a check must report where it was planted |
| `tools/roundtrip/` | the round trip: harden `rtl_recovered/` with LibreLane 3.0.14 as Jane Street's flow was inferred to be, then check our own GDS with the oracles above, prove it equivalent to the RTL and to the puzzle's netlist, and compare it with `puzzle.gds` (`ci.sh`; CI in `.github/workflows/roundtrip.yml`) |
| `docs/` | PRD, approach, verification plan, status ledger, design intent, mutation report, solution, writeup |

## Reproduce

Requirements: Python 3.12+, [oss-cad-suite](https://github.com/YosysHQ/oss-cad-suite-build)
(Yosys, SymbiYosys, Icarus Verilog, Verilator; the tools look in `~/ttsetup/oss-cad-suite/bin`),
and [ciel](https://github.com/fossi-foundation/ciel) for the PDK.

```bash
git clone https://github.com/janestreet/asic-puzzle-2026 upstream   # the puzzle files (not redistributed here)
python3 -m venv .venv && .venv/bin/pip install gdstk klayout shapely networkx pytest z3-solver markdown ciel pillow
.venv/bin/ciel enable --pdk-root ~/pdk-sky130 --pdk-family sky130 8afc8346a57fe1ab7934ba5a6056ea8b43078e71
mkdir -p pdk/sky130_fd_sc_hd && for d in lef lib verilog gds; do \
  cp -rL ~/pdk-sky130/sky130A/libs.ref/sky130_fd_sc_hd/$d pdk/sky130_fd_sc_hd/; done
.venv/bin/python -m pytest -q
python3.12 -m venv ~/ttsetup/librelane-venv && ~/ttsetup/librelane-venv/bin/pip install librelane==3.0.14
tools/roundtrip/ci.sh   # the round trip (needs Docker; see docs/ROUNDTRIP.md section 9), ~7 min
```

The TEMPO tests skip unless `TEMPO_ROOT` points at a TEMPO checkout with a sign-off run and
`IHP_PDK` at the IHP `sg13cmos5l` PDK.

## License

Apache License 2.0 (`LICENSE`). The puzzle files in `upstream/` belong to Jane Street and are not
part of this repository. Built with Claude Code after the contest deadline; see the writeup.
