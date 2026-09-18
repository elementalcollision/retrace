# RETRACE — status (2026-09-18, sprint 0)

## What exists

| Area | State |
|---|---|
| Docs | PRD (`docs/prd/PRD.md`), approach (`docs/spec/APPROACH.md`), verification plan (`docs/spec/VERIFICATION.md`) |
| Repo | private GitHub repo `elementalcollision/retrace` (main), Apache-2.0; skeleton `tools/retrace`, `tools/l2n`, `test`, `formal`, `rtl_recovered`, `out`, `pdk` |
| Upstream | `janestreet/asic-puzzle-2026` @ `ffd53e0ba24e2fc1c1b12dc824e8eac5888c19a9` (2026-08-05) shallow-cloned into `upstream/` (read-only, git-ignored) |
| PDK | **sky130 installed on the Mac mini** with ciel 2.6.1 (`~/ciel-venv`), open_pdks `8afc8346a57fe1ab7934ba5a6056ea8b43078e71` (matches the puzzle's cells exactly, see below; first pinned `0fe599b2`, the OpenLane 2 default), PDK root `~/pdk-sky130` (sky130A + sky130B). The `sky130_fd_sc_hd` subset (LEF, techlef, tt_025C_1v80 Liberty, Verilog models, cell GDS; ~22 MB) is copied to local `pdk/` (git-ignored; `pdk/VERSION` records the commit). iverilog compiles the warm-up netlist against the models. |
| Env (this Mac) | `.venv/` (Python 3.14) with `gdstk`, `klayout`; oss-cad-suite at `~/ttsetup/oss-cad-suite` (Yosys, eqy, SBY, iverilog, Verilator) |
| Env (mini) | host: Python 3.12.14 and Icarus 13.0 in `/opt/homebrew/bin` (a non-interactive SSH session needs that on PATH), no Yosys. OrbStack VM `tt-runner` (Ubuntu noble arm64, 11 cores, Python 3.12.3, iverilog in `/usr/bin`, `~/pdk` has IHP only) was unreachable for a while on 2026-09-18 (`sconrpc ... socket was not connectible`, load average ~110) and was back later that day: `mini-orb-tt` runner online and idle. |
| Recon | PRD §2: sky130_fd_sc_hd, 728 logic cells, 92 flops, masters and pin labels intact, names stripped, `INTERNAL_*` marker strip at y = -52.72 on layer 200/0 |

## Finding (resolved): the puzzle was built with open_pdks `8afc8346`

`tools/retrace/cellcheck.py` compares every `sky130_fd_sc_hd` master in a design GDS
with a PDK's cell GDS, layer by layer (polygons normalised on a 1 nm grid,
independent of order and start vertex).

Against the first pinned version (`0fe599b2`, the OpenLane 2 default), 66 of 69 masters
matched. `o211a_2` (poly, licon), `and4b_2` (poly) and `conb_1` (95/20) differed.
Scanning 24 of the 116 released sky130 versions (standard-cell library only, fetched with
`ciel fetch -l sky130_fd_sc_hd` on the mini) found two families:

| Versions (list position, newest = 1) | Result |
|---|---|
| 1, 13, 25, 37, 49, 50, 51, 52 | `and4b_2` and `o211a_2` match; `conb_1` differs on 66/15 |
| **53: `8afc8346a57fe1ab7934ba5a6056ea8b43078e71`** | **all 69 masters identical** |
| 54-116 (sampled: 54-60, 61, 62 = `0fe599b2`, 68 = `bdc9412b`, 70, 73, 85, 97, 109, 116) | `and4b_2` and `o211a_2` differ; `conb_1` on 95/20 or matching |

**No tampering.** The differences were PDK revisions. The puzzle and the warm-up
(18/18 masters) both match `8afc8346` exactly, so it is now the pinned PDK: enabled on
the mini (`~/pdk-sky130`) and copied to local `pdk/`. Against `0fe599b2`, its
`sky130_fd_sc_hd` LEF, tt Liberty and `primitives.v` are byte-identical, and
`sky130_fd_sc_hd.v` only *adds* `sky130_ef_sc_hd__decap_*`/`fill_2` modules, so the
logic cell models are unchanged.

## Next (ordered)

1. S1/S2 on the warm-up: V1, V2.
2. S3/S4 on the warm-up: V3 (equivalence with `01_netlist.v`).
3. Puzzle extraction, then V4-V6.
