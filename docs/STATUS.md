# RETRACE — status (2026-09-18, sprint 0)

## What exists

| Area | State |
|---|---|
| Docs | PRD (`docs/prd/PRD.md`), approach (`docs/spec/APPROACH.md`), verification plan (`docs/spec/VERIFICATION.md`) |
| Repo | `git init` done (no commits yet); skeleton `tools/retrace`, `tools/l2n`, `test`, `formal`, `rtl_recovered`, `out`, `pdk` |
| Upstream | `janestreet/asic-puzzle-2026` @ `ffd53e0ba24e2fc1c1b12dc824e8eac5888c19a9` (2026-08-05) shallow-cloned into `upstream/` (read-only, git-ignored) |
| PDK | **sky130 installed on the Mac mini** with ciel 2.6.1 (`~/ciel-venv`), open_pdks `0fe599b2afb6708d281543108caf8310912f54af` (the OpenLane 2 default), PDK root `~/pdk-sky130` (sky130A + sky130B). The `sky130_fd_sc_hd` subset (LEF, techlef, tt_025C_1v80 Liberty, Verilog models, cell GDS; ~22 MB) is copied to local `pdk/` (git-ignored; `pdk/VERSION` records the commit). iverilog compiles the warm-up netlist against the models. |
| Env (this Mac) | `.venv/` (Python 3.14) with `gdstk`, `klayout`; oss-cad-suite at `~/ttsetup/oss-cad-suite` (Yosys, eqy, SBY, iverilog, Verilator) |
| Env (mini) | host: Python 3.12.14 and Icarus 13.0 in `/opt/homebrew/bin` (a non-interactive SSH session needs that on PATH), no Yosys; OrbStack VM `tt-runner` **unreachable on 2026-09-18** (`sconrpc ... socket was not connectible`, `orb` hangs). This also affects TEMPO's self-hosted CI runner. |
| Recon | PRD §2: sky130_fd_sc_hd, 728 logic cells, 92 flops, masters and pin labels intact, names stripped, `INTERNAL_*` marker strip at y = -52.72 on layer 200/0 |

## Finding: cell masters vs PDK GDS (2026-09-18)

All 69 `sky130_fd_sc_hd` masters in `puzzle.gds` were compared with the PDK's GDS
layer by layer. Every electrically relevant routing and pin layer (li1, mcon, met1,
pin and label layers) is identical. Four transistor-level layers differ:

| Master | Instances | Layer | Difference |
|---|---|---|---|
| `o211a_2` | 12 | poly 66/20 | 6 shapes vs 5 in the PDK (one polygon split in two), area +0.0017 um^2 |
| `o211a_2` | 12 | licon 66/44 | one contact differs |
| `and4b_2` | 4 | poly 66/20 | one shape differs, area -0.024 um^2 |
| `conb_1` | 6 | 95/20 | one shape moved, same area |

It is probably an open_pdks version difference, but it could be a deliberate
transistor-level change, and the brief hints at easter eggs. It matters because the
extractor treats masters as trusted (PRD non-goal). **Next check:** compare with other
open_pdks versions (for example `bdc9412b`, `cd1748bb`). If no version matches, extract
those three cells to SPICE with Magic and compare transistor netlists against the
PDK's CDL.

## Next (ordered)

1. Decide what to do about the mini's OrbStack VM (restart or wait). It blocks TEMPO CI too.
2. Resolve the cell-master finding above.
3. S1/S2 on the warm-up: V1, V2.
4. S3/S4 on the warm-up: V3 (equivalence with `01_netlist.v`).
5. Puzzle extraction, then V4-V6.
