import collections, json, os
ROOT = "/Users/dave/Jane_Street_Reverse_ASIC"
OUT = os.path.join(ROOT, "out/s3/blind/analysis")
KINDS = ["shift_register", "counter", "lfsr_crc", "synchronizer"]
d = json.load(open(os.path.join(OUT, "labels.json")))
P = d["pooled_headline"]
L = []
W = L.append


def frac(a, b):
    return f"{a}/{b}" + (f" = {a/b:.3f}" if b else " (no registers of this kind)")


W("# S3 blind evaluation - the LABELS lens")
W("")
W(f"Written {d['written']}. Freeze `{d['freeze']['freeze_hash'][:16]}` at git head "
  f"`{d['freeze']['git_head'][:12]}`; `freeze check` printed exactly `freeze holds` before and after "
  "this analysis. Nothing under `tools/`, no truth and no run record was modified.")
W("")
W("This document audits **the ground truth**, because every blind figure rests on it. It quotes "
  "`tools/s3/score.py`'s definitions and `docs/S3_DESIGN.md` section 4.4's protocol, and it changes "
  "no label.")
W("")
W("## 0. Which evaluation each number comes from")
W("")
W("| Evidence | Status | What it can say |")
W("|---|---|---|")
W("| TEMPO (`out/s3/eval/runs/`) | **in-sample, fitted** | nothing about generalisation |")
W("| corpus holdout (`out/s3/honesty/holdout_rates.json`, 40 synthetic designs, 80 runs) | "
  "**pre-published out-of-sample estimate** | synthetic, written by this project; its aggregation "
  "is `per_register_and_unit` |")
W("| the 10 drawn Tiny Tapeout designs | **the first true out-of-sample test** | everything below |")
W("| the Jane Street puzzle | **frozen code, known design** | not blind; pooled with nothing here |")
W("")
W("Every blind number below is `score.py`'s **strict register count** "
  "(`classes.all` / `classes.verified` -> `registers` -> `strict` -> `per_kind`). "
  "`out/s3/honesty/holdout_rates.py` states in terms that `per_register_and_unit` and "
  "`score_counts_strict` are **not comparable**, so the holdout rates in section 9 must not be put "
  "in the same column as these. Under the holdout's aggregation the blind denominator would be 88 "
  "items rather than 94 (18 synchronizer registers minus 16 chain members, plus the 10 declared "
  "synchronizer units); the matching outcomes for that aggregation are not derivable from the "
  "frozen report and were not computed.")
W("")

W("## 1. Findings")
W("")
h1 = P["H1_all_10_designs"]["pooled"]
ob = d["label_quality"]["outcome_by_tier"]
W(f"1. **Roughly a quarter of the blind ground truth is not established.** Of the 94 scored "
  f"structure-kind registers, **23 are Tier A**: the labeller's own z3 mapping proof refutes at "
  f"least one of their bits, or 4096-pattern random simulation contradicts it. 2 more are Tier B "
  f"(sound but narrowed), 69 are clean. At the flop level, "
  f"{d['totals']['flop_level_label_evidence']['mapping_proof_refuted']} of the "
  f"{d['totals']['flop_level_label_evidence']['flops_carrying_a_structure_kind_label']} netlist "
  f"flops that carry a structure-kind label have a refuted mapping proof "
  f"({d['totals']['flop_level_label_evidence']['mapping_proof_refuted']/885:.1%}), and "
  f"{d['totals']['flop_level_label_evidence']['also_contradicted_by_random_simulation']} of those "
  f"are also contradicted by simulation.")
W("")
W(f"2. **The weak labels drag the headline down, not up.** The recognizer scores "
  f"{ob['C_clean']['found']}/{ob['C_clean']['registers']} = {ob['C_clean']['found_rate']:.3f} found "
  f"on clean-label registers and only {ob['A_contradicted']['found']}/"
  f"{ob['A_contradicted']['registers']} = {ob['A_contradicted']['found_rate']:.3f} on Tier A ones. "
  f"Pooled found is {frac(h1['found'], h1['registers'])} with every register in, and "
  f"{frac(P['H4_all_10_designs_Tier_A_registers_dropped_from_the_denominator']['pooled']['found'], P['H4_all_10_designs_Tier_A_registers_dropped_from_the_denominator']['pooled']['registers'])} "
  f"with the 23 Tier A registers removed from the denominator.")
W("")
W("3. **One design carries almost all of the damage.** `tt07/tt_um_toivoh_basilisc_2816` has 157 of "
  "its 198 flops refuted and 86 simulation-mismatching, and 16 of its 18 scored structure registers "
  "are Tier A (89%). It is also the only design contributing any `lfsr_crc` register, and it "
  "contributes 3 of the 8 `shift_register` registers.")
W("")
W("4. **The single `shift_register` success in the whole blind set is on a Tier A1 label.** "
  "`cpu.pref.sreg` (basilisc) is found and harness-verified; all 16 of its bits are z3-refuted and "
  "all 16 mismatch in simulation. On the 5 shift registers whose labels are not contradicted, the "
  "recognizer found 0.")
W("")
W("5. **`lfsr_crc` has no usable blind evidence.** All 9 `lfsr_crc` registers are basilisc's CPU "
  "register-file words and stack pointer (2 RTL module definitions), all Tier A, recall 0/9. "
  "Meanwhile the two registers their authors literally named `lfsr`, with XOR feedback recorded in "
  "the truth's own `params.serial_in`, are labelled `shift_register` - and the recognizer's "
  "harness-verified `lfsr_crc` structures over them are scored as misses in one kind and "
  "unmatched structures in the other.")
W("")
W("6. **Pooled `synchronizer` recall of 17/18 rests on two unit matches.** 16 of the 18 registers "
  "are credited through two `copy_lanes` units, one per design, each matched by a single wide "
  "structure. Without that unit rule the same structures match nothing and pooled synchronizer "
  "recall falls to 1/18.")
W("")
W("7. **The join is clean everywhere.** All 10 designs report `clean: true` with 0 layout cells "
  "without an instance name, 0 instances on either side without a partner, 0 master mismatches, 0 "
  "nets split or spanning, and 0 ports disagreeing. The labels' weakness is in the RTL-to-netlist "
  "*correspondence*, never in the layout-to-netlist *join*.")
W("")

W("## 2. What the labeller does and what 'refuted' means")
W("")
W(f"`{d['label_pipeline']['module']}` (sha256 `{d['label_pipeline']['sha256'][:16]}`, unchanged on "
  f"disk at labelling time). {d['label_pipeline']['what_it_does']}")
W("")
W(f"{d['label_pipeline']['what_refuted_means']}")
W("")
W(f"Labels were fixed before scoring: `labels.json` was written "
  f"{d['label_pipeline']['labels_fixed_before_scoring']['labels_json_written']}, the first blind run "
  f"started {d['label_pipeline']['labels_fixed_before_scoring']['first_blind_run']}. "
  f"{d['label_pipeline']['draw']['drawn']} drawn, {d['label_pipeline']['draw']['labelled']} "
  f"labelled, {d['label_pipeline']['draw']['failed']} failed, "
  f"{d['label_pipeline']['draw']['reserves_used']} reserves used, no replacement. The blind ledger "
  "holds 22 lines (11 attempts x 2 events) and no rerun.")
W("")
W("All three copies of every truth hash agree - `labels.json`, the committed run record, and a "
  "fresh `schema.truth_hash()` over the file on disk - for all 10 designs. `check_truth()` reports "
  "0 problems on every blind truth.")
W("")

W("## 3. Per-design label audit")
W("")
W("### 3.1 Proof completeness and the simulation check")
W("")
W("| design | flops | labelled | proven | refuted | unchecked | sim match | sim mismatch | outputs | invariants |")
W("|---|--:|--:|--:|--:|--:|--:|--:|---|---|")
for x in d["designs"]:
    p = x["proof_completeness"]
    fc = p["random_simulation"]
    outs = ", ".join(f"{k} {v}" for k, v in sorted((p["outputs"] or {}).items()))
    inv = ", ".join(f"{k} {v}" for k, v in sorted((p["invariants"] or {}).items())) or "-"
    W(f"| `{x['id']}` | {x['size']['netlist_flops']} | {x['size']['netlist_flops_labelled']} | "
      f"{p['flops']['proven']} | {p['flops']['refuted']} | {p['flops']['unchecked']} | "
      f"{fc['match']} | {fc['mismatch']} | {outs} | {inv} |")
W("")
W("Notes on the five designs the labeller marks `proof_incomplete`:")
W("")
W("* `tt05/tt_um_toivoh_synth` - **incomplete on a bookkeeping item only**. All 264 flops proven, 0 "
  "simulation mismatches, 8 of 9 outputs proven; the ninth is `uio_out`, recorded as `not in the "
  "netlist` (the bus name has no net). Its labels are as strong as the 5 'complete' designs'.")
W("* `ttsky25a/tt_um_sjsu_vga_music` - 9 flops refuted, 5 mismatching, 7 unchecked (those 7 are the "
  "unmapped flops, which carry no label), plus the same `uio_out` bookkeeping item.")
W("* `tt03p5/tt_um_Reloj_top` - 60 of 385 refuted, 14 mismatching; all 15 outputs and all 12 "
  "invariants proven.")
W("* `tt07/tt_um_vzayakov_top` - 24 of 192 refuted, 19 mismatching, **3 of 7 outputs refuted** "
  "(`uo_out[5..7]`) and 1 invariant refuted (`merged DUT.b.BallCol.Q[0]`). The register "
  "correspondence is not inductive for this design.")
W("* `tt07/tt_um_toivoh_basilisc_2816` - **157 of 198 refuted, 86 mismatching**, while all 8 "
  "outputs and all 4 invariants are proven. Outputs can be proven from corresponding flop states "
  "even where the per-flop next-state functions differ, so this is not a contradiction - but the "
  "per-flop correspondence, which is what the labels are attached to, largely fails.")
W("")
W("`spurious_sat` is 0 and the z3 rlimit per check is 200,000,000 on every design, so no refutation "
  "here is a solver artefact and no check was lost to the limit (`unknown` is 0 everywhere).")
W("")

W("### 3.2 Join report, anonymisation, universe")
W("")
W("| design | join clean | layout refs w/o name | inst. unmatched (either side) | master mismatch | "
  "nets split/spanning | ports disagree | net labels stripped | labels kept | unmapped | shadow |")
W("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
for x in d["designs"]:
    j = x["join"]; a = x["anonymisation"]
    W(f"| `{x['id']}` | {str(j['clean']).lower()} | {j['layout_std_cell_refs_without_name']} | "
      f"{j['extracted_without_netlist_instance'] + j['netlist_without_extracted_instance']} | "
      f"{j['master_mismatch']} | "
      f"{j['extracted_nets_spanning_several_netlist_nets'] + j['netlist_nets_split_over_several_extracted_nets'] + j['netlist_nets_without_extracted_net']} | "
      f"{len(j['ports_disagree'])} | {a['labels_removed']} | {a['labels_kept']} | "
      f"{x['universe']['unmapped_flops']} | {x['universe']['shadow_flops']} |")
W("")
W("Four layouts (`tt05/tt_um_toivoh_synth`, `tt03p5/tt_um_Reloj_top`, `tt03p5/tt_um_thorkn_vgaclock`, "
  "`tt05/tt_um_kskyou`) carried top-level text labels naming internal nets - 2,078 / 2,614 / 526 / "
  "1,053 removed, of which the join counted 265 / 388 / 127 / 148 as RTL-like. The harness stripped "
  "them and kept 50-79 labels (the TT pinout). The other six carried none. Every design's "
  "anonymised layout is pinned by sha256 in its run record's `inputs`.")
W("")
W("Universe facts: **0 shadow flops in all 10 designs**, so no register loses bits to the shadow "
  "rule anywhere. 7 unmapped flops in one design (`ttsky25a/tt_um_sjsu_vga_music`, reason 'no RTL "
  "name on the Q net'); the scorer dropped exactly those 7 result flops, and the 4 structures built "
  "from them are of unscored kinds (3 `flag`, 1 `data_register`), so no scored-kind figure moved. "
  "Three designs hold one register each with no scored flop: `u_cordic.mode_q` (flag, constant in "
  "RTL), `cpu.fifo.entries[0]` (flag, constant in RTL), `DUT.doneff.Q` (flag, next state constant) "
  "- all non-structure kinds, so no structure denominator is affected. "
  "`tt03p5/tt_um_thorkn_vgaclock`'s `meta.registers_without_primary_flop` lists its three "
  "`__retimed` registers, which are kind `other` by the truth/2 rule and never enter a structure "
  "denominator.")
W("")

W("### 3.3 Units admitted by rule")
W("")
W("Two designs declare units; the other eight declare none. All 10 units are of kind "
  "`synchronizer`, and all 10 are chain units under `score.Truth` (a synchronizer unit all of whose "
  "members are synchronizer registers), so the 16 member registers are scored **only through them** "
  "in strict mode.")
W("")
W("| design | unit kind | admitted by rule | member registers | flops | chain unit |")
W("|---|---|---|--:|--:|---|")
for x in d["designs"]:
    for u in x["units_admitted_by_rule"]:
        W(f"| `{x['id']}` | {u['kind']} | `{', '.join(u['rules'])}` | {len(u['registers'])} | "
          f"{u['flops']} | {'yes' if u['chain'] else 'no'} |")
W("")
W("No `shift_register`, `counter` or `lfsr_crc` unit was admitted anywhere in the blind set, and no "
  "unit was rejected as malformed (`bad_units` empty in all 10).")
W("")

W("### 3.4 Scored registers per kind, per design")
W("")
W("The denominator is `score.Truth.denominators(c)`: registers of kind `c` with at least one flop "
  "in the universe. It is the same in strict and lenient mode.")
W("")
W("| design | shift | counter | lfsr_crc | sync | total | distinct design_keys | Tier A | Tier B |")
W("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
for x in d["designs"]:
    s = x["scored_registers"]; k = x["distinct_design_keys"]
    W(f"| `{x['id']}` | {s['shift_register']} | {s['counter']} | {s['lfsr_crc']} | "
      f"{s['synchronizer']} | {x['scored_registers_total']} | "
      f"{sum(k.values())} | {x['label_tiers'].get('A_contradicted', 0)} | "
      f"{x['label_tiers'].get('B_narrowed', 0)} |")
tot = {c: P["H1_all_10_designs"]["pool"][c]["registers"] for c in KINDS}
dk = {c: P["H1_all_10_designs"]["pool"][c]["distinct_design_keys"] for c in KINDS}
W(f"| **pooled** | **{tot['shift_register']}** | **{tot['counter']}** | **{tot['lfsr_crc']}** | "
  f"**{tot['synchronizer']}** | **94** | **{sum(dk.values())}** | **23** | **2** |")
W("")
W("`score.SMALL_SUPPORT` is 3, so a kind with fewer than 3 registers in a design is flagged. Flagged "
  "per design: `tt05/tt_um_toivoh_synth` shift (1) and synchronizer (1); `ttsky25a/tt_um_td4` "
  "counter (1); `tt07/tt_um_toivoh_basilisc_2816` synchronizer (1); "
  "`ttsky25a/tt_um_sjsu_vga_music` shift (1).")
W("")
W("**Instance counts overstate the independent evidence.** Pooled per distinct RTL `design_key` "
  "(`score.py`'s own `distinct_designs` counts): counter 27 of 44 found in every instance, "
  "shift_register 1 of 8, lfsr_crc 0 of 2, synchronizer 5 of 6 - "
  f"{27+1+0+5}/{sum(dk.values())} = {(27+1+0+5)/sum(dk.values()):.3f} against "
  f"{frac(h1['found'], h1['registers'])} per instance. The gap is concentrated: "
  "`tt07/tt_um_vzayakov_top`'s 12 counters are 12 instances of a single 4-bit `Counter:Q` module, "
  "all found; its 10 synchronizers are 10 instances of 2 module definitions.")
W("")

W("## 4. Label quality: the tiers")
W("")
tq = d["label_quality"]
W(f"* **Tier A (contradicted)** - {tq['tier_rule']['A_contradicted']}")
W(f"* **Tier B (narrowed)** - {tq['tier_rule']['B_narrowed']}")
W(f"* **Tier C (clean)** - {tq['tier_rule']['C_clean']}")
W("")
W("| tier | registers | found | found rate | verified-found | verified-found rate |")
W("|---|--:|--:|--:|--:|--:|")
for k in ("C_clean", "B_narrowed", "A_contradicted", "A1_simulation_mismatch", "A2_z3_refuted_only"):
    v = ob[k]
    W(f"| {k} | {v['registers']} | {v['found']} | {v['found_rate']:.3f} | "
      f"{v['verified_found']} | {v['verified_found_rate']:.3f} |")
W("")
W("The 2 Tier B registers are `oct_counter` (`tt05/tt_um_toivoh_synth`, 1 of 17 RTL bits has no "
  "flop, 'unused (removed)'; found) and `ui_in_reg` (basilisc, 6 of 8 RTL bits are not flops in the "
  "word-level RTL; missed).")
W("")
W("### 4.1 Which designs carry weak labels")
W("")
W("| design | scored structure regs | Tier A | Tier A share | refuted flops (design-wide) | sim mismatches |")
W("|---|--:|--:|--:|--:|--:|")
for r in tq["designs_carrying_weak_labels"]:
    W(f"| `{r['design']}` | {r['scored_structure_registers']} | {r['tier_A']} | "
      f"{r['tier_A_share']:.2f} | {r['refuted_flops_design_wide']} | "
      f"{r['simulation_mismatching_flops_design_wide']} |")
W("")
W("Four designs contribute Tier A registers; six contribute none. On the stated rule - **a design "
  "more than half of whose scored structure registers are Tier A** - exactly one design qualifies "
  "as weakest-labelled: `tt07/tt_um_toivoh_basilisc_2816` (16 of 18).")
W("")
W("### 4.2 Every Tier A register")
W("")
W("| kind | design | register | subtier | bits | unproven | mismatching | found | verified-found |")
W("|---|---|---|---|--:|--:|--:|---|---|")
for r in tq["tier_A_registers"]:
    W(f"| {r['kind']} | `{r['design'].split('/')[1]}` | `{r['register']}` | "
      f"{r['subtier'].split('_', 1)[0]} | {r['bits_with_flop']} | {r['unproven_bits']} | "
      f"{r['mismatching_bits']} | {'yes' if r['found'] else 'no'} | "
      f"{'yes' if r['verified_found'] else 'no'} |")
W("")
W("Three of the 41 pooled verified-found registers are Tier A1: `segmod.seg` (Reloj), "
  "`DUT.vg.ColCounter.Q` (vzayakov) and `cpu.pref.sreg` (basilisc). A harness verdict proves a "
  "template about the netlist, not the truth's label, so these remain proved structural claims "
  "matched against truth items that are not established.")
W("")

W("## 5. How much of the pooled figure depends on the weak labels")
W("")


def block(key, title):
    v = P[key]
    W(f"**{title}** ({len(v['designs'])} designs)")
    if v.get("excluded"):
        W("")
        W("Excluded: " + ", ".join(f"`{x}`" for x in v["excluded"]) + ".")
    if v.get("rule"):
        W("")
        W("Rule: " + v["rule"])
    W("")
    W("| kind | registers | found | exact | verified-found |")
    W("|---|--:|---|---|---|")
    for c in KINDS:
        p = v["pool"][c]
        ex = frac(p["exact"], p["registers"]) if p.get("exact") is not None else "n/a"
        W(f"| {c} | {p['registers']} | {frac(p['found'], p['registers'])} | {ex} | "
          f"{frac(p['verified_found'], p['registers'])} |")
    q = v["pooled"]
    ex = frac(q["exact"], q["registers"]) if q.get("exact") is not None else "n/a"
    W(f"| **pooled** | **{q['registers']}** | **{frac(q['found'], q['registers'])}** | **{ex}** | "
      f"**{frac(q['verified_found'], q['registers'])}** |")
    W("")


block("H1_all_10_designs", "H1 - all 10 blind designs (the headline)")
block("H2_excluding_weakest_labelled_designs", "H2 - excluding the weakest-labelled design")
block("H3_excluding_every_design_with_any_Tier_A_register",
      "H3 - excluding every design with any Tier A register")
block("H4_all_10_designs_Tier_A_registers_dropped_from_the_denominator",
      "H4 - all 10 designs, Tier A registers removed from the denominator")
block("H5_Tier_A_registers_only", "H5 - the Tier A registers alone")
W("**Read H1 and H2 together, and prefer H4 for the label question.** H2 answers 'what if the "
  "weakest-labelled design had not been drawn' and moves pooled found from "
  f"{frac(P['H1_all_10_designs']['pooled']['found'], 94)} to "
  f"{frac(P['H2_excluding_weakest_labelled_designs']['pooled']['found'], 76)} - but it also deletes "
  "the `lfsr_crc` kind entirely and removes 3 of the 8 shift registers, so the two figures are over "
  "different kind mixes. H4 keeps every design and removes only the 23 registers whose labels are "
  "contradicted: pooled found "
  f"{frac(P['H4_all_10_designs_Tier_A_registers_dropped_from_the_denominator']['pooled']['found'], 71)}, "
  f"verified-found {frac(P['H4_all_10_designs_Tier_A_registers_dropped_from_the_denominator']['pooled']['verified_found'], 71)}. "
  "H3 leaves 27 registers (4 shift, 22 counter, 0 lfsr_crc, 1 synchronizer) - too few for anything "
  "but the counter figure.")
W("")
W("The direction matters: the weak labels **suppress** the headline. The recognizer finds "
  f"{ob['A_contradicted']['found']}/{ob['A_contradicted']['registers']} of the contradicted "
  f"registers and {ob['C_clean']['found']}/{ob['C_clean']['registers']} of the clean ones. The one "
  "exception is `shift_register`, whose single success is itself a Tier A register.")
W("")

W("## 6. Truth judgement calls that swing a number")
W("")
for j in d["judgement_calls"]:
    W(f"### {j['id']}. {j['what']}")
    W("")
    W(f"*Swings:* {j['swings']}.")
    W("")
    W(f"*Evidence:* {j['evidence']}")
    W("")
    if "effect_as_scored" in j:
        W(f"*As scored:* {j['effect_as_scored']}")
    cf = j.get("counterfactual")
    if isinstance(cf, dict):
        q = cf["pooled"]
        W("")
        W(f"*Counterfactual ({cf['label']}):* pooled found "
          f"{frac(q['found'], q['registers'])}, verified-found "
          f"{frac(q['verified_found'], q['registers'])}, precision {q['precision_found']:.3f} "
          f"(headline: {frac(h1['found'], h1['registers'])}, "
          f"{frac(h1['verified_found'], h1['registers'])}, {h1['precision_found']:.3f}). "
          f"Per kind: " + "; ".join(
            f"{c} found {frac(cf['per_kind'][c]['found'], cf['per_kind'][c]['registers'])}"
            for c in KINDS) + ". " + cf["note"][0].upper() + cf["note"][1:])
    elif cf:
        W("")
        W(f"*Counterfactual:* {cf}")
    W("")

W("## 7. What the blind set is, and is not, representative of")
W("")
r = d["representativeness"]
for s in r["what_the_blind_set_IS"]:
    W(f"* {s}")
W("")
W("It is **not** representative of:")
W("")
for x in r["what_it_is NOT_representative_of"]:
    W(f"* **{x['claim']}** - {x['fact']}")
W("")

W("## 8. Figures too small to support a claim")
W("")
W("* **`lfsr_crc`**: 9 registers, all from one design, 2 RTL module definitions, all Tier A. Recall "
  "0/9 and precision 0/2 are counts, not rates, and the two structures in the precision denominator "
  "are the two real LFSRs of judgement call J1. **No blind claim about LFSR/CRC recognition is "
  "supportable in either direction.**")
W("* **`shift_register`**: 8 registers in 4 designs. 1 found, and that one is Tier A1. Report as "
  "1/8, never as 12.5%.")
W("* **`synchronizer`**: 18 registers, but 16 are credited by 2 structure matches against 2 "
  "`copy_lanes` units in 2 designs. 17/18 is 3 successes, not 17.")
W("* **H3** (27 registers over 6 designs) supports at most the counter figure (15/22); its shift "
  "(0/4) and synchronizer (1/1) cells are too small to read.")
W("* **Per-design rates** for any kind with fewer than 3 registers are flagged by "
  "`score.SMALL_SUPPORT` and are listed in section 3.4; none of them should be quoted as a rate.")
W("")

W("## 9. The pre-published out-of-sample estimate, for context only")
W("")
o = d["out_of_sample_estimate_for_context"]
W(f"`{o['path']}`, aggregation `{o['aggregation_id']}`, {o['designs']} synthetic holdout designs, "
  f"{o['runs']} runs. Its `found` already means harness-VERIFIED.")
W("")
W("| kind | items | found | exact |")
W("|---|--:|---|---|")
for c in KINDS:
    p = o["per_kind"][c]
    W(f"| {c} | {p['items']} | {p['found']}/{p['items']} = {p['found_rate']} | "
      f"{p['exact']}/{p['items']} = {p['exact_rate']} |")
W("")
W(f"**{o['comparability']}** The corpus is also synthetic and written by this project, and both "
  "generalisation regression sets are no longer held out (contamination record, quoted in every "
  "score report's provenance block). These rows are here so a reader knows what the prior estimate "
  "said, not to be differenced against section 5.")
W("")

W("## 10. The puzzle, kept separate")
W("")
pz = d["puzzle_for_contrast"]
W(f"**{pz['status']}.** {pz['truth']}")
W("")
W(f"Scale: {pz['scale']['registers']} registers, {pz['scale']['flops']} flops, "
  f"{pz['scale']['units']} units; scored structure registers "
  f"counter {pz['scale']['scored_structure_registers']['counter']}, "
  f"shift_register {pz['scale']['scored_structure_registers']['shift_register']}, "
  f"lfsr_crc {pz['scale']['scored_structure_registers']['lfsr_crc']}, "
  f"synchronizer {pz['scale']['scored_structure_registers']['synchronizer']}; no chain units, no "
  "excused registers, no register without a scored flop.")
W("")
W(f"Label provenance: {pz['label_provenance']}")
W("")
W(pz['why_it_is_separate'][0].upper() + pz['why_it_is_separate'][1:] +
  " Its truth is **not** produced by the frozen design-agnostic "
  "labeller, so the Tier A/B/C audit above does not apply to it and its numbers are pooled with "
  "nothing here.")
W("")

W("## 11. Caveats")
W("")
for c in d["caveats"]:
    W(f"* {c}")
W("")
W("## 12. Sources")
W("")
for s in d["sources"]:
    W(f"* {s}")
W("")

open(os.path.join(OUT, "labels.md"), "w").write("\n".join(x for x in L if x is not None) + "\n")
print("wrote labels.md", len(L), "lines")
