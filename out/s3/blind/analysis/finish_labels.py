"""Add representativeness, judgement calls, caveats and sources to labels.json."""
import collections, json, os

ROOT = "/Users/dave/Jane_Street_Reverse_ASIC"
OUT = os.path.join(ROOT, "out/s3/blind/analysis")
KINDS = ["shift_register", "counter", "lfsr_crc", "synchronizer"]
doc = json.load(open(os.path.join(OUT, "labels.json")))
CAND = json.load(open(os.path.join(ROOT, "out/s3/blind/candidates.json")))
SCAN = json.load(open(os.path.join(ROOT, "out/s3/blind/scan.json")))
LAB = json.load(open(os.path.join(ROOT, "out/s3/blind/labels.json")))
H1 = doc["pooled_headline"]["H1_all_10_designs"]["pool"]


def rate(a, b):
    return None if not b else round(a / b, 4)


def swing(changes, label, note):
    """changes: {kind: (d_registers, d_found, d_verified_found, d_structures, d_matched)}"""
    per, tot = {}, collections.Counter()
    for c in KINDS:
        d = changes.get(c, (0, 0, 0, 0, 0))
        base = H1[c]
        n = {"registers": base["registers"] + d[0], "found": base["found"] + d[1],
             "verified_found": base["verified_found"] + d[2],
             "structures": base["structures"] + d[3],
             "structures_matched": base["structures_matched"] + d[4]}
        n["found_recall"] = rate(n["found"], n["registers"])
        n["verified_found_recall"] = rate(n["verified_found"], n["registers"])
        n["precision_found"] = rate(n["structures_matched"], n["structures"])
        per[c] = n
        tot.update({k: v for k, v in n.items() if isinstance(v, int)})
    return {"label": label, "note": note, "per_kind": per,
            "pooled": {"registers": tot["registers"], "found": tot["found"],
                       "verified_found": tot["verified_found"],
                       "found_recall": rate(tot["found"], tot["registers"]),
                       "verified_found_recall": rate(tot["verified_found"], tot["registers"]),
                       "structures": tot["structures"],
                       "precision_found": rate(tot["structures_matched"], tot["structures"])}}


doc["representativeness"] = {
 "what_the_blind_set_IS": [
   "10 third-party Tiny Tapeout projects on sky130, drawn with the freeze's 128-bit seed from a "
   "candidate list of 84 registered before recognizer development, by criteria C1-C7 that look at "
   "no design's structure beyond size. 0 reserves were used and no design was replaced.",
   "Real, taped-out, third-party RTL and real OpenLane/LibreLane layouts and gate-level netlists, "
   "not synthetic cases: the first evidence in this study that is neither fitted (TEMPO), nor "
   "written by this project (the corpus), nor known to the team (the puzzle).",
   "Small designs: 47 to 385 netlist flops, median 169.5, 1,708 flops in total; 9 of 10 occupy one "
   "TT tile.",
   "94 scored structure-kind registers over 60 distinct RTL design_keys."],
 "what_it_is NOT_representative_of": [
   {"claim": "the 14 sky130 shuttles",
    "fact": "the candidate list stratifies 6 designs per shuttle over 14 sky130 shuttles, but the "
            "draw of 10 covers only 6 of them (tt03p5 x2, tt05 x2, tt07 x2, ttsky25a x2, tt09 x1, "
            "ttsky26c x1). tt02, tt04, tt06, tt08, ttcad25a, ttsky25b, ttsky26a and ttsky26b "
            "contribute nothing. The draw rule is the n lowest sha256(seed|id), not a "
            "stratified draw, so this is expected, not a fault -- but no per-shuttle or "
            "per-era claim can rest on it."},
   {"claim": "Tiny Tapeout as a whole",
    "fact": "the index holds 3,411 entries / 2,654 distinct designs; 387 were checked before the "
            "per-stratum quota of 6 was met, and 288 of those were rejected (C1 104, C4 162, "
            "C5 21, C6 1). C4 alone (all cells sky130_fd_sc_hd and >= 40 flops) rejected 162. The "
            "84-design pool is what survives C1-C7, not a sample of TT."},
   {"claim": "larger designs",
    "fact": "the candidate pool holds 55 1x1, 18 1x2, 6 2x2, 1 3x2 and 4 4x2 designs and runs to "
            "1,656 flops; the drawn 10 are 9 x 1x1 and 1 x 1x2, the largest 385 flops. Nothing "
            "here speaks to designs above ~400 flops."},
   {"claim": "author styles",
    "fact": "9 distinct authors over 10 designs: Toivo Henningsson wrote 2 of the 10 "
            "(tt05/tt_um_toivoh_synth and tt07/tt_um_toivoh_basilisc_2816), which are 25 of the 94 "
            "scored registers and include all 9 lfsr_crc registers and 4 of the 8 shift registers. "
            "9 of 10 are Verilog, 1 SystemVerilog; every one carries an Apache-2.0 author repo."},
   {"claim": "hand-instantiated sequential logic",
    "fact": "C5 excludes any design whose sources instantiate a sky130 flip-flop or latch cell, and "
            "every drawn design has 0 latches and 0 opaque sequential cells. Nothing here speaks to "
            "latch-based or hand-placed sequential designs."},
   {"claim": "LFSRs and CRCs",
    "fact": "all 9 lfsr_crc registers in the blind set come from ONE design and 2 RTL module "
            "definitions (regfile x8, regfile_single x1), and all 9 are Tier A. Meanwhile the two "
            "registers their authors named `lfsr` are labelled shift_register. The blind set "
            "supports NO claim about LFSR/CRC recognition in either direction."}],
 "draw_and_pool": {
   "index_commit": SCAN["index_commit"], "population": SCAN["population"],
   "checked": len(SCAN["checked"]), "rejections_among_checked": CAND["rejections_among_checked"],
   "candidates": len(CAND["candidates"]),
   "strata": CAND["strata"] if isinstance(CAND.get("strata"), dict) else None,
   "strata_represented_in_the_draw": dict(collections.Counter(d["shuttle"] for d in doc["designs"])),
   "strata_not_represented": sorted(set(LAB["freeze"]["draw"]["strata"]) -
                                    {d["shuttle"] for d in doc["designs"]}),
   "tiles_in_the_pool": dict(collections.Counter(x["tiles"] for x in CAND["candidates"])),
   "candidate_flops": {"min": 40, "median": 150.0, "max": 1656},
   "drawn_flops": sorted(d["size"]["netlist_flops"] for d in doc["designs"])},
}

doc["judgement_calls"] = [
 {"id": "J1", "swings": "shift_register recall, lfsr_crc precision, the pooled headline",
  "what": "Two Fibonacci LFSRs are labelled shift_register, with no alt_kinds.",
  "evidence": "out/s3/truth_tt05__tt_um_toivoh_synth.json register `lfsr` (width 15, kind "
              "shift_register, rule 'D[k] = Q[k-1] on 14 of 14 shiftable bits', params.serial_in "
              "['(lfsr[0] ^ lfsr[14])']) and out/s3/truth_ttsky25a__tt_um_sjsu_vga_music.json "
              "register `lfsr` (width 13, kind shift_register, params.serial_in ['feedback']). "
              "The recognizer emitted a 15-flop and a 13-flop structure of kind lfsr_crc over "
              "exactly those registers; both carry harness outcome 'verified'; both appear in the "
              "strict confusion matrix as 'shift_register->lfsr_crc': 1.",
  "effect_as_scored": "each is a shift_register miss and an lfsr_crc structure that matched no "
                      "item: pooled lfsr_crc precision 0/2.",
  "counterfactual": swing({"shift_register": (-2, 0, 0, 0, 0), "lfsr_crc": (2, 2, 2, 0, 2)},
                          "the two `lfsr` registers labelled lfsr_crc instead",
                          "both structures are harness-verified, so found and verified-found move "
                          "together. The truth was NOT changed; this is arithmetic on the frozen "
                          "report.")},
 {"id": "J2", "swings": "the whole lfsr_crc recall denominator",
  "what": "Nine 8-bit CPU register-file words are labelled lfsr_crc.",
  "evidence": "out/s3/truth_tt07__tt_um_toivoh_basilisc_2816.json: "
              "cpu.dec.sched.alu.registers.general_registers.regs[0..7] (design_key regfile:regs) "
              "and cpu.dec.sched.alu.registers.sp_register.regs (regfile_single:regs), all kind "
              "lfsr_crc, rule 'own Q bits of other indices reach D through XOR (GF(2) feedback)', "
              "every PARAMS field (form, poly, k_steps, n_inputs, bit_order) null.",
  "effect_as_scored": "these 9 registers ARE the blind set's lfsr_crc denominator (9 of 9), over 2 "
                      "distinct design_keys in 1 design; recall 0/9. Every one is Tier A: all 8 "
                      "bits of each have a refuted mapping proof.",
  "counterfactual": "remove the design and the blind set has 0 lfsr_crc registers: the kind has no "
                    "blind evidence at all, in either direction."},
 {"id": "J3", "swings": "pooled synchronizer recall, and the pooled headline by 16 points",
  "what": "The `copy_lanes` unit rule creates one wide synchronizer unit per design over lanes that "
          "are also covered by 2-flop `sync_chain` units.",
  "evidence": "truth units of tt03p5/tt_um_Reloj_top (3 sync_chain units of 2 flops + 1 copy_lanes "
              "unit of 6 flops) and tt07/tt_um_vzayakov_top (5 sync_chain + 1 copy_lanes of 10 "
              "flops). 16 of the 18 synchronizer registers are chain members, so in STRICT mode "
              "they are scored only through chain units. The recognizer emitted exactly one "
              "synchronizer structure per design (6 and 10 flops); each matched its copy_lanes "
              "unit at IoU 1.0 (score report per_kind.synchronizer.via_units names it).",
  "effect_as_scored": "2 structures credit 16 registers. Against the 2-flop sync_chain units alone "
                      "those structures have IoU 2/6 = 0.33 and 2/10 = 0.20, both below score.py's "
                      "0.5 threshold, so without the copy_lanes rule all 16 would be missed.",
  "counterfactual": swing({"synchronizer": (0, -16, -16, 0, -2)},
                          "no copy_lanes units (sync_chain units only)",
                          "the 2 wide structures would match nothing, so they also leave the "
                          "synchronizer precision numerator.")},
 {"id": "J4", "swings": "the one shift_register success in the blind set",
  "what": "The only shift_register the recognizer found, tt07/tt_um_toivoh_basilisc_2816 "
          "cpu.pref.sreg, is a Tier A1 label: all 16 of its bits are refuted by z3 AND contradicted "
          "by random simulation.",
  "evidence": "truth register cpu.pref.sreg, bits[] all check=mismatch, proof=refuted; score report "
              "shift_register found_registers = ['cpu.pref.sreg'].",
  "effect_as_scored": "pooled shift_register found = 1/8 = 0.125. On the 5 shift registers whose "
                      "labels are NOT contradicted, the recognizer found 0.",
  "counterfactual": "dropping Tier A registers leaves shift_register at 0/5."},
 {"id": "J5", "swings": "exact recall on tt03p5/tt_um_Reloj_top",
  "what": "Three Reloj counters are 32 bits in RTL but fewer in the netlist, and `exact` is against "
          "the netlist flop set.",
  "evidence": "hourmod.hour 28 of 32 bits have a flop, minites.min 30 of 32, segmod.seg 30 of 32 "
              "('no flop found'); meta.counts.rtl_bits records 8 'no flop found' and 9 'next state "
              "constant (removed by synthesis)'.",
  "effect_as_scored": "Reloj counter found 7/14, exact 0/14 -- it contributes 7 of the pooled 41 "
                      "found counters and 0 of the pooled 28 exact ones."},
 {"id": "J6", "swings": "the basilisc synchronizer item",
  "what": "ui_in_reg is labelled synchronizer with params.stages = 1 and is 8 bits wide in RTL, of "
          "which only 2 are flops (6 bits 'not a flop in the word-level RTL').",
  "evidence": "truth register ui_in_reg, kind synchronizer, rule 'no enable; D is an input pin "
              "(stage 1) or a stage-1 flop (stage 2)', params {'stages': 1}.",
  "effect_as_scored": "1 of the 18 synchronizer denominators is a 2-flop, 1-stage item; it is the "
                      "one synchronizer the recognizer missed. Tier B (narrowed), not contradicted."},
 {"id": "J7", "swings": "nothing in the headline, but it is a label-coverage gap",
  "what": "7 of ttsky25a/tt_um_sjsu_vga_music's 77 netlist flops have no RTL name on their Q net and "
          "sit in truth.unmapped_flops, outside the scored universe.",
  "evidence": "truth.unmapped_flops (reason 'no RTL name on the Q net'); the score report's "
              "result.dropped_flops = 7 and result.structures_without_labelled_flops = 4.",
  "effect_as_scored": "the 4 result structures built from them are of UNSCORED kinds (3 flag, 1 "
                      "data_register), so no scored-kind precision, found or exact figure moved. "
                      "The gap is real but cost nothing here."},
 {"id": "J8", "swings": "confidence in tt07/tt_um_vzayakov_top's 22 scored registers",
  "what": "vzayakov's register correspondence is not inductive: 3 of its 7 outputs and 1 invariant "
          "are refuted, and only 22 of 192 bits were mapped by name.",
  "evidence": "meta.proof.outputs {'proven': 4, 'refuted': 3} (uo_out[5], uo_out[6], uo_out[7]) and "
              "invariants_not_proven ['merged DUT.b.BallCol.Q[0]']; bits[].how = 114 alias, 56 "
              "retimed, 22 name, 1 merged; 8 '__retimed' registers of kind other absorb 56 flops.",
  "effect_as_scored": "vzayakov contributes 22 of the 94 scored registers (12 counters over ONE "
                      "design_key and 10 synchronizers over 2) and 22 of the 59 found. Only 2 of "
                      "its 22 are Tier A, so the tier rule does not flag it, but the design-level "
                      "proof is the weakest kind of pass."},
 {"id": "J9", "swings": "nothing -- recorded so no reader assumes otherwise",
  "what": "The strict/lenient distinction carries no information on this blind set.",
  "evidence": "only 4 blind registers carry alt_kinds at all (flag with a counter alternative, the "
              "1-bit toggle rule: 1 in tt09/tt_um_pwm_top, 1 in tt03p5/tt_um_Reloj_top, 2 in "
              "ttsky25a/tt_um_sjsu_vga_music); none is of a structure kind, so score.Truth.excused "
              "is 0 for every kind in every design, and the lenient per-kind register counts and "
              "found counts equal the strict ones for all 4 kinds in all 10 designs."},
]

doc["caveats"] = [
 "Every blind figure here is score.py's STRICT REGISTER count (classes.all/verified -> registers -> "
 "strict -> per_kind). The published corpus-holdout rates use the per_register_and_unit "
 "aggregation, and out/s3/honesty/holdout_rates.py states the two are NOT comparable. Under "
 "per_register_and_unit the blind denominator would be 88 items, not 94 (18 synchronizer registers "
 "minus 16 chain members, plus the 10 declared synchronizer units); the outcome counts for that "
 "aggregation are not derivable from the frozen report and were NOT computed.",
 "'Tier A' means the labeller's own mapping proof or its random simulation contradicts the "
 "register's bit-to-flop mapping. It does NOT prove the kind is wrong: a refutation can equally "
 "mean the shipped netlist was built from other RTL than the recorded commit. Either way the label "
 "is not established, which is what the tiers measure.",
 "A harness-VERIFIED structure over a Tier A register is still a proved statement about the "
 "netlist: verify.py proves a template, not the truth's label. What Tier A puts in doubt is the "
 "truth item the structure was matched against, not the structure.",
 "The 10 blind truths are NOT pinned by out/s3/FREEZE.json, which carries truth_hash only for TEMPO "
 "and the puzzle. They are pinned by out/s3/blind/labels.json (written 2026-09-23T06:50:45Z, before "
 "the first run at 06:53:52Z) and by each committed run record's truth.truth_hash. All 30 hashes "
 "(labels.json, run record, recomputed from disk with schema.truth_hash) agree. labels.json and the "
 "truth files themselves are in the git-ignored out/ tree and are not force-added into the freeze "
 "commit, so only the committed run records prove what was scored.",
 "The labeller's RULES were exercised on 15 third-party designs on the truth side before the blind "
 "draw (contamination.json K11). None of those 15 is in the 84-candidate pool and no recognizer "
 "code ran on them, but the label rules are not naive with respect to third-party RTL.",
 "Per-kind blind rates for shift_register (8 registers), lfsr_crc (9, all from one design) and "
 "synchronizer (18, of which 16 are credited through 2 unit matches) are too small, or too "
 "concentrated, to support a rate claim. They are reported as counts with their denominators and "
 "should be read that way.",
 "All 5 permutations of every blind run produced identical per-kind register counts, so nothing "
 "here depends on which permutation is quoted.",
 "The puzzle is frozen-code-but-known and its truth is written by tools/s3/truth_puzzle.py, not by "
 "the design-agnostic labeller. It is described separately and is pooled with nothing.",
]

doc["puzzle_for_contrast"] = {
 "status": "FROZEN CODE, KNOWN DESIGN -- not blind, not pooled with the blind set",
 "truth": "out/s3/truth_puzzle.json, written by tools/s3/truth_puzzle.py (a different artifact from "
          "the blind labeller: hand-derived checks, no z3 register-correspondence proof and no "
          "random-simulation flop check of the kind the blind truths carry).",
 "scale": {"registers": 35, "flops": 92, "units": 3,
           "scored_structure_registers": {"counter": 27, "shift_register": 1, "lfsr_crc": 1,
                                          "synchronizer": 0},
           "registers_without_a_scored_flop": 0, "excused_by_kind": {k: 0 for k in KINDS},
           "chain_units": 0},
 "label_provenance": "meta.checks records 'pass' on N1-N3 (RTL tagging, port binding, the 92 flops "
                     "partitioned), X1-X2 (fresh extraction and per-pin net agreement) and the "
                     "per-structure checks; meta.source_discrepancies and meta.source_corrections "
                     "record two corrections made on 2026-09-21 to the project's own recovered RTL "
                     "and INTENT notes.",
 "why_it_is_separate": "the design has been read by the team all along (contamination.json), so its "
                       "numbers say what frozen code does on a known design, never what it does "
                       "out of sample.",
}

doc["sources"] = [
 "tools/s3/score.py (frozen) -- module docstring: universe, matching, strict/lenient, excused, "
 "SMALL_SUPPORT, found/exact/verified, provenance",
 "docs/S3_DESIGN.md sections 4.1-4.4 (frozen) -- truth, join, units, the evaluation protocol",
 "tools/s3/thirdparty.py (frozen) -- criteria C1-C7, the draw, the join through GDS property 61",
 "tools/s3/truth_tempo.py (frozen) -- prove_mapping, proof_complete, the word-level label rules",
 "out/s3/blind/labels.json and labels.log -- the labelling summary and per-design log",
 "out/s3/truth_<design>.json x 10 -- the blind truths (read only)",
 "out/s3/runs/blind-<design>-<utc>-<id>.json x 10 -- the frozen run records (evaluation p1 quoted; "
 "all 5 permutations agree)",
 "out/s3/honesty/holdout_rates.json -- the pre-published out-of-sample estimate and its aggregation",
 "out/s3/contamination.json -- K11 (labeller exercised on 15 third-party designs), the puzzle items",
 "out/s3/blind/candidates.json and scan.json -- the registered candidate pool and the scan funnel",
 "out/s3/blind_ledger.jsonl -- 22 lines = 11 attempts x 2 events, no rerun",
]
json.dump(doc, open(os.path.join(OUT, "labels.json"), "w"), indent=1)
print("ok")
for j in doc["judgement_calls"]:
    if isinstance(j.get("counterfactual"), dict):
        print(j["id"], j["counterfactual"]["label"], "->", json.dumps(j["counterfactual"]["pooled"]))
