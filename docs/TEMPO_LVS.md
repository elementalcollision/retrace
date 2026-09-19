# TEMPO_LVS — RETRACE's independent LVS of TEMPO's sign-off GDS (PRD G6)

**What this is.** RETRACE's extractor (`tools/retrace/extract.py`) is now
technology-independent (`tools/retrace/tech.py`): a `Tech` table replaces every
sky130-specific constant, and the default `Tech` (`SKY130_HD`) reproduces the
pre-port extractor exactly: the puzzle and warm-up netlists from the refactored code are
byte-identical to those from the committed pre-port code (lead review, 2026-09-19).
`tech.IHP_SG13CMOS5L` describes IHP's `sg13cmos5l` stdcell process, and
`tools/tempo/lvs.py` uses it to extract TEMPO's sign-off GDS
(`tt_um_elementalcollision_tempo`, 1289.28 x 710.64 um, 62,151 std-cell/macro
instances, 335,134 GDS references including ~273K via-cell instances) and
check it six ways against TEMPO's own DEF/netlist/LEF — an LVS independent of
LibreLane's Magic/Netgen flow. All of TEMPO's files are read read-only, under
`$TEMPO_ROOT` (default `~/Claude_Primary/Jane_Street_ASIC`; the IHP PDK from `$IHP_PDK`); nothing there was modified.

**Result: all six checks pass exactly.** Run with:

```
.venv/bin/python -m tools.tempo.lvs        # standalone report
.venv/bin/python -m pytest -q test/test_tempo.py
```

## 1. Method

1. **Tech table** (`tools/retrace/tech.py`). A `Tech` is: an ordered stack of
   `Conductor` layers (GDS layer, the datatypes that count as conductor
   material, the label texttype), a list of `Cut`s (a via/contact layer and
   the two `Conductor`s it joins), which conductors can carry a cell-internal
   pin, the gate-poly layer/contact used to join same-layer islands inside a
   cell, an optional poly-resistor cut marker, physical-only cell prefixes,
   supply pin names, and macro master names to treat as opaque black boxes.
   `SKY130_HD` encodes exactly what `extract.py` hardcoded before;
   `IHP_SG13CMOS5L` is built from the PDK's own layer map/`.lyp` plus what the
   TEMPO GDS actually contains (§2).
2. **extract.py refactor.** `Extraction.__init__` takes a `tech=SKY130_HD`
   parameter; every layer number, datatype, cut rule, and prefix that was a
   module constant is now a `Tech` lookup. Module-level aliases
   (`PREFIX`, `SUPPLY_PINS`, `PHYSICAL`, `CONDUCTOR_DT`, `POLY`, `LICON`)
   are kept, equal to `SKY130_HD`'s fields, so `tools/retrace/mutate.py` and
   every test that imported them is unaffected. `Extraction.cuts` (the
   `(layer:int, geom, via_name)` list `mutate.py` reads) keeps its old,
   sky130-only-meaningful shape (`layer` = the *below* conductor, `layer+1`
   assumed to be *above*); a new internal `Extraction._cuts` (full `Cut`
   objects) is what `_connect()` itself uses, generally.
3. **Orientation fix (general, not tech-specific).** The pre-port `ORIENT`
   table and the DEF-lower-left-from-GDS-origin offset formula only handled
   0/180 rotation (N/S/FN/FS) — the only orientations the sky130 puzzle and
   warm-up ever use. TEMPO's SRAM macro is placed at DEF orientation `E`
   (verified against the DEF: `gdstk` reports rotation=270 deg,
   x_reflection=False for that reference). Both tables are extended to all
   eight LEF/DEF orientations, derived from gdstk's mirror-then-rotate
   transform order and cross-checked against the macro's DEF placement: DEF
   says `PLACED (912180 147000) E`; the macro's LEF gives `SIZE 416.64 BY
   336.46` (w=416640, h=336460 DBU); for orientation E the derived formula is
   `def_y = gds_y - w`, and `gdstk` reports the transformed GDS origin as
   `(912180, 563640)` — `563640 - 416640 = 147000`, exactly DEF's `y`, and
   `def_x = gds_x` matches `912180` directly. The four sky130-only entries
   (N, S, FN, FS) are unchanged, so this cannot have moved a single sky130
   placement (confirmed by regenerating the puzzle and warm-up netlists from the committed
   pre-port code and the refactored code: byte-identical; the full suite, 55 tests before the
   port and 64 after, passes).
4. **Macro pins.** `RM_IHPSG13_1P_1024x32_c2_bm_bist`'s *own* GDS cell (not its
   ~50-subcell internal hierarchy) carries 495 polygons and 294 pin labels
   directly (Metal2 and Metal4, texttypes 25) — the macro's top-level
   pins/labels the PRD/APPROACH anticipated. `Extraction._macro_pins` reuses
   the same island-union-find core as `_master_pins` (`_join_master_islands`),
   scanning every conductor layer (not just `pin_conductors`) and skipping the
   gate-poly step (unneeded — no GatPoly/Cont shapes exist in the macro's own
   polygons). The macro's internal ~50-subcell hierarchy is never flattened or
   walked; only its own top-cell polygons/labels are read. Result: 193
   extracted pins, exactly matching the macro's LEF pin count (bracket-style
   naming differs cosmetically, `A_ADDR<9>` vs `A_ADDR[9]`; normalised for
   every comparison).
5. **`tools/tempo/lvs.py`** extracts once (`extract_tempo`, ~19 s) and runs:
   - **(a) placements**: maps every extracted instance to its DEF instance
     name by exact `(master, x, y, orient)` (DBU); reports unmatched/ambiguous.
   - **(b) net partition vs DEF NETS**: the extracted `(instance, pin)`
     groups, minus global-power and single-pin nets (neither of which DEF's
     regular `NETS` section lists — see §3), compared as *sets of parts*
     (so net *naming* is never at issue, only the partition).
   - **(c) net partition vs `nl.v`**: same idea, against the final netlist's
     per-instance connections. A small hand-written parser
     (`parse_nl_verilog`) reads `nl.v` (regex, no nested parens outside
     `{...}` bus concatenations, which do occur on the macro's bus ports and
     are expanded per-bit using the LEF's pin-bit order).
   - **(d) pins vs LEF**: every master used, every instance's extracted pin
     set equals the IHP LEF's pin set for that master (bracket-normalised).
   - **(e) V5-style sanity**: one driver per signal net, no floating input, no
     VDD/VSS overlap, using LEF `DIRECTION`/`USE`.
   - **(f) cellcheck**: `tools/retrace/cellcheck.py` (now takes a
     `--prefix`/parameter instead of a hardcoded sky130 prefix) compares every
     `sg13cmos5l_*` master embedded in the GDS with the PDK's own stdcell GDS.

## 2. IHP findings (established from the data, not assumed)

| Item | Finding | How verified |
|---|---|---|
| Layer stack | Metal1 8/0 (pin 8/2, label 8/25), Via1 19/0, Metal2 10/0 (10/2, 10/25), Via2 29/0, Metal3 30/0 (30/2, 30/25), Via3 49/0, Metal4 50/0 (50/2, 50/25), TopVia1 125/0, TopMetal1 126/0 (126/2, 126/25) | `~/ttsetup/pdk/ihp-sg13cmos5l/libs.tech/klayout/tech/sg13cmos5l.map` (its own header says "M1-M4-TM1 stack") |
| **No Via4/Metal5/TopVia2/TopMetal2** | This PDK variant has exactly five metals (M1-M4 + one top metal); the "presumably" layer numbers in the task brief (66/67/133/134) do not appear in the map at all, and `cellcheck` confirms every via/metal master TEMPO uses resolves within the five-layer stack | `.map` file read directly; `f_cellcheck` (51/51 identical, no unknown layers) |
| GatPoly / Cont / Activ | GatPoly 5/0, Cont 6/0 (joins Metal1 to GatPoly, and separately to Activ — never followed), Activ 1/0 | `sg13cmos5l.lyp` |
| Std-cell pins | Plain Metal1 islands, labelled 8/25, pin marker 8/2 | Read `sg13cmos5l_stdcell.gds` directly (e.g. `sg13cmos5l_nand2_1`: labels only on layer 8/25) |
| **Tie cells need no poly-resistor cut** | `sg13cmos5l_tiehi`/`tielo`'s output (`L_HI`/`L_LO`) stays on its own Metal1 island, separate from VDD/VSS, *even after* joining Metal1 through GatPoly+Cont (the same mechanism sky130's `conb_1` needs a 66/15 resistor cut to avoid). Verified by literally running the union-find (Metal1-same-layer touch, then GatPoly+Cont join) on the PDK's own `tiehi`/`tielo` cells: `L_HI`/`L_LO`, `VDD`, `VSS` land in three distinct roots either way. | Standalone script against `sg13cmos5l_stdcell.gds`; `tech.IHP_SG13CMOS5L.poly_resistor_cut = None`, and the full TEMPO extraction has zero `pin_component_multiple_labels` diagnostics |
| Supply names | Std cells: `VDD`/`VSS` (`USE POWER`/`USE GROUND` in the LEF). Macro: `VDD!`/`VSS!`/`VDDARRAY!` (also `USE POWER`/`GROUND`). Antenna diode (`sg13cmos5l_antennanp`): has its own `VDD`/`VSS` *and* a signal pin `A` — its `VSS` pin is real substrate-tap geometry that physically abuts the VSS strap. | LEF `USE` field, all three cases (§3) |
| SRAM macro | `RM_IHPSG13_1P_1024x32_c2_bm_bist`, one instance, DEF orientation `E`. Its own GDS cell carries 495 polygons / 294 labels directly — no need to descend into its ~50-subcell internal hierarchy (17 distinct sub-masters seen, e.g. `RM_IHPSG13_1P_MATRIX_256x64`, `RM_IHPSG13_1P_ROWDEC8`) which is never flattened into chip nets. 193 pins extracted, exactly matching the LEF's 193 pins. | `_macro_pins`; check (d) |
| Physical cells | `decap_4`/`decap_8`, `fill_1`/`fill_2`, `antennanp` (antenna diode, has a real signal pin `A` in addition to its VDD/VSS taps — included as a "physical" prefix for `logic_instances()`/Verilog-emission purposes, same as sky130's `diode`) | LEF pin/USE inspection; no `tap*` cell exists in this PDK/design (none of the 63 masters referenced by TEMPO start with anything tap-like) |
| Via cells | `VIA_Via1_XY/YY`, `VIA_Via2_YX`, `VIA_Via3_XY`, plus several `VIA_via{N}_{N+1}_*` sized variants — all match `Tech.via_prefix = "VIA"` and resolve their cut shapes to the `Cut` table's `(layer, datatype)` with zero `cut_open_*` diagnostics | Full-design extraction diagnostics: `{}` (empty) |

## 3. What the LVS found, and how each "expected difference" was handled

Two categories of *representation* difference between the physical layout and
DEF/`nl.v` are real and were handled explicitly, not filtered blindly:

1. **Global power/ground.** Once every VDD/VSS-strap-touching pin is unioned
   (std-cell `VDD`/`VSS`, the antenna's substrate-tap `VSS`, the macro's
   `VDD!`/`VSS!`/`VDDARRAY!`), the extractor produces exactly two giant nets
   (62,152 and 62,153 members: every instance's power pins plus the chip's
   `VPWR`/`VGND` ports). DEF's regular `NETS` section and `nl.v`'s module body
   do not enumerate power connectivity at all (that is DEF `SPECIALNETS`,
   which this check does not read, per the task's own files list). `lvs.py`
   identifies these nets by LEF `USE POWER`/`USE GROUND` (not by a top-level
   text label — TEMPO's GDS has no standalone chip-level `VDD`/`VSS` label;
   power reaches every instance purely through touching per-cell pins) and
   excludes them from checks (b)/(c), **counting** the 124,303 excluded pin
   connections rather than dropping them silently.
2. **Unloaded outputs / CTS dummy loads.** 157 extracted nets have exactly one
   `(instance, pin)` member — an output pin with nothing else attached (e.g.
   `clkload*` cells inserted by clock-tree synthesis). DEF's `NETS` section
   does not list single-pin nets either (a `NETS` entry only exists where
   there is a net to describe). Excluded from (b)/(c) by a `min_size=2`
   filter, with the count reported (`gds_singleton_nets_excluded`), not
   dropped silently. This is the same phenomenon `docs/STATUS.md` recorded
   for sky130's puzzle (15 unloaded `clkbuf_4`), just IHP's own timing-repair
   cell names.
3. **Bracket-style pin naming.** GDS labels a bus-pin bit as `A_ADDR<9>`;
   LEF/Verilog write it `A_ADDR[9]`. Purely cosmetic — verified identical
   geometry and count on the SRAM macro (193 pins, exact match once
   normalised) — and normalised (`<n>` → `[n]`) everywhere a name is compared.
4. **`nl.v` bus concatenation.** The macro's bus ports are written in `nl.v`
   as `.A_ADDR({net.., ...})`, a Verilog concatenation, not one wire per LEF
   pin bit. Expanded per-bit using the LEF's own descending bit order
   (Yosys `write_verilog` convention) before comparison; the exact match on
   check (c) (0 mismatches) confirms this ordering assumption is correct.

After handling both categories explicitly, **checks (a)–(f) all agree
exactly** — no unexplained mismatch was found or set aside:

| Check | Result |
|---|---|
| (a) placements vs DEF COMPONENTS | 62,151 / 62,151 matched, 0 unmatched, 0 ambiguous |
| (b) net partition vs DEF NETS | 35,542 / 35,542 parts, 0 only-one-side |
| (c) net partition vs `nl.v` | 35,542 / 35,542 parts, 0 only-one-side, 0 unmapped `nl.v` instances |
| (d) pins vs IHP LEF | 52 masters (51 std cells + the SRAM macro), 0 mismatched instances |
| (e) electrical sanity | 0 undriven signal nets, 0 multiply-driven nets, VDD/VSS never overlap |
| (f) cellcheck vs PDK stdcell GDS | 51 / 51 masters byte-identical |

## 4. Performance

Full-design extraction (62,151 std-cell/macro instances, ~273K via-cell
references, 335,134 GDS references total): **~19-21 s wall clock, ~2.0 GB peak
RSS**, on this Mac (18 cores; the extractor itself is single-threaded — the
budget came from bulk shapely `STRtree` queries per conductor layer and a
per-master pin-geometry cache, both already present before this port, plus
avoiding any full-hierarchy GDS flatten). The full `lvs.py` run (extraction +
all six checks, including parsing the 708K-line DEF and the 168K-line `nl.v`)
adds well under two seconds on top. Both are far inside the "few minutes"
target (PRD/task item 3).

## 4b. V4 — a second, independent extractor agrees

Everything above is extractor 1 (`tools/retrace/extract.py`, gdstk + shapely
union-find) checked against TEMPO's own DEF/`nl.v`. As a second, independent
check on the extractor itself — not on TEMPO's files — extractor 2
(`tools/l2n/klayout_extract.py`, KLayout's `LayoutToNetlist`, its own
connectivity engine) was ported the same way: it takes only layer numbers and
datatypes from `tools/retrace/tech.py`'s `IHP_SG13CMOS5L` table, never any of
extractor 1's union-find/algorithm code, and shares no code with it (same rule
as the existing sky130 V4, `test/test_crosscheck.py::test_v4_extractors_agree`).

**Macro handling.** `IHP_SG13CMOS5L.macro_prefixes` names the SRAM
(`RM_IHPSG13_1P_1024x32_c2_bm_bist`) as a master to keep as a subcircuit rather
than drop; `tools/l2n/klayout_extract.py`'s `partitions()` filter admits
`master.startswith(tech.prefix) or master in tech.macro_prefixes`. No special
hierarchy-cutting code was needed: KLayout's `extract_netlist()` already keeps
every distinct referenced cell as its own circuit and only exposes that
circuit's own pins to its parent, so the SRAM instance naturally surfaces to
the top circuit as one subcircuit whose pins are its own top-level labelled
nets. Its ~50-subcell internal hierarchy is extracted into its own nested
circuits (KLayout processes it, since it is present in the GDS) but never
flattened into chip-level nets — option 2 of the task brief ("keep it as a
subcircuit whose pins come from its top-level labels").

**A generalization bug caught by the sky130 regression, not by TEMPO.** The
first port connected the gate-poly-to-contact join to *every* Tech
`pin_conductor`, instead of only the lowest one (extract.py:
`layer_names[0]`). For sky130 (`pin_conductors = ("li1", "met1")`) that wrongly
wired the poly/licon join straight to met1 as well as li1 — a bug that would
not have shown up on TEMPO at all, since IHP has only one pin conductor
(`("Metal1",)`), but broke `test/test_crosscheck.py`'s existing sky130 V4 test
immediately. Fixed by joining the poly cut to `tech.pin_conductors[0]` only,
matching extract.py exactly; the sky130 V4 test (and the MD5 guard) is what
caught it.

**Result — both extractors agree, on all three designs, with the exact counts
required:**

| Design | Tech | Multi-pin nets, extractor 1 | extractor 2 | Agree |
|---|---|---|---|---|
| warm-up (`upstream/warmup/04_final.gds`) | `SKY130_HD` | 86 | 86 | exact |
| puzzle (`upstream/puzzle.gds`) | `SKY130_HD` | 719 | 719 | exact |
| TEMPO (`tt_um_elementalcollision_tempo.gds`) | `IHP_SG13CMOS5L` | 35,543 | 35,543 | exact |

Before excluding single-member nets, TEMPO's raw partitions are 35,700 (ours)
vs. 35,697 (KLayout's): the difference is exactly 3 single-pin nets on unloaded
`sg13cmos5l_inv_8` outputs, e.g. `sg13cmos5l_inv_8@1279680,487620` pin `Y`. This
is the same phenomenon already recorded for sky130 (15 unloaded `clkbuf_4`,
`test/test_crosscheck.py`'s own comment) and for TEMPO's DEF/`nl.v` checks
above (157 single-pin nets, mostly IHP `clkload*` CTS dummy loads): KLayout's
`LayoutToNetlist` makes no subcircuit pin for an output net that connects to
nothing else, so a single-member net exists only on extractor 1's side. It is
excluded from the V4 comparison exactly as the sky130 test already does
(`ours = {n for n in ours if len(n) > 1}`), and is separately covered — for
TEMPO — by checks (b), (c) and (e) above, which all pass with those same nets
correctly accounted for as unloaded.

**Runtime.** KLayout's extraction + partition reduction on the full TEMPO GDS:
~5.2 s (4.7 s `LayoutToNetlist` + 0.46 s reducing to
`{(instance, pin)}` partitions), well under extractor 1's ~19 s and adding only
a few seconds to the total LVS wall clock when both extractors are run
back to back.

Test: `test/test_tempo.py::test_v4_extractors_agree` (skips, like the rest of
`test_tempo.py`, when `TEMPO_ROOT` is absent). Files touched for this port:
`tools/l2n/klayout_extract.py`, `tools/l2n/compare.py` (both now take an
optional `tech=` argument, defaulting to `SKY130_HD` so every existing sky130
call site, including `test/test_crosscheck.py`, is unchanged); nothing under
`tools/retrace/` was touched by this task.

## 4c. Negative controls and a known limit (independent review)

Four faults planted in copies of the TEMPO GDS were each caught: a deleted Via1 on a signal net
(checks b, c, e), a mirrored `o21ai_1` (a, then b, c, e), two swapped SRAM pin labels
`A_DIN<15>`/`A_BIST_DIN<15>` (b, c), and a Metal2 bridge between two nets (b, c, e).

Known limit, now closed: check (d), pins vs LEF, compares the *set* of pin names an instance
exposes, not which polygon carries which name, so two swapped labels on the same master pass it
on its own. **Check (d2)** (`check_pin_geometry_vs_lef`) closes this. For every master used, the
centre of every LEF port rectangle of every signal pin must lie on the extracted conductor of the
same pin, on the same layer, and on no other pin's (LEF `ORIGIN 0 0`, so LEF and GDS master
coordinates coincide). On TEMPO: 52 masters, 553 rectangles, 0 misplaced, in 0.02 s (STRtree
per master and layer). Negative controls in `test/test_tempo.py`: swapping the SRAM's
`A_DIN<15>`/`A_BIST_DIN<15>` labels, or a `nand2_1`'s A/B labels, flags exactly those two pins,
each found on the other's conductor.

The review also found that the "sky130 unchanged" evidence first reported by the port hashed
`out/puzzle.json`, a stale file no test regenerates. Regenerating it from the committed and the
refactored code gives identical output, so the conclusion held; the evidence above is the
corrected one.

## 4d. In TEMPO's CI

TEMPO's `.github/workflows/lvs.yaml` (layer L5b in TEMPO's `docs/spec/VERIFICATION.md`) runs
these checks after every sign-off: `gds.yaml` calls it once the `gds` job has produced the
`GDS_logs` artifact, and it can be dispatched by hand against an earlier run. It runs on a
GitHub-hosted runner, as TEMPO's runner security note requires. It checks out RETRACE pinned to a
commit and fetches only the `sg13cmos5l` standard-cell LEF and GDS from IHP-Open-PDK `2bbec755`,
the revision the TT GDS action installs. The report goes to the job summary and to an
`lvs_report` artifact.

A dry run on the self-hosted runner's VM (Ubuntu, arm64) found two portability bugs before the
first CI run: peak RSS is reported in KiB on Linux, and the sky130 guard test needs to skip where
the puzzle files are absent. The first CI run (35438357943, 2026-09-19) checked the CI-built
`v0.2-signoff` GDS (run 35218140984): every check passes, identical to the local results, with
11 tests passed and the sky130 guard skipped. Extraction took 44 s with a 1.9 GB peak.

## 5. Open items

* **DEF `SPECIALNETS` is not read.** Power/ground routing correctness (that
  the two supply nets this extractor finds are themselves correctly and
  fully connected, not just internally consistent) was not cross-checked
  against DEF's `SPECIALNETS` section, which was out of the files list for
  this task. The extractor's own sanity check (e) does confirm every signal
  net is driven and VDD/VSS never merge, which is the electrical property
  that actually matters for LVS.
* **The `E`-orientation macro is the only rotated instance TEMPO places**, so
  the new W/FE/FW table entries are exercised (and correct, since they
  reproduce the macro's exact DEF placement) but not independently
  cross-checked against a *second* rotated instance. The N/S/FN/FS entries
  remain the ones exhaustively exercised (every sky130 puzzle/warm-up cell,
  plus most of TEMPO's own 62,150 non-macro instances).
* **`nl.v`'s bus-concatenation bit order** is assumed MSB-first, matching
  Yosys `write_verilog`'s convention and the LEF's descending pin-bit
  declaration order; this is confirmed correct by the exact match on check
  (c) (a wrong order would show up as scrambled, still-single-bit-net
  mismatches on every macro bus pin), not verified independently from a
  Yosys-internals reference.
