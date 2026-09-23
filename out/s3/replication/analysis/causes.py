"""S3 replication (set R, Freeze 4) -- every miss and every false positive traced to its cause.

Reads only: the ten R run records (p1), their truths, the RTL the labeller cached for those ten designs
(read by hand for the mechanism text, not by this script), out/s3/replication/analysis/numbers.json and
freeze 1's out/s3/blind/analysis/misses.json. Writes only causes.json and causes.md next to itself.

The mechanical part (which registers were missed, which scored-kind structures earned no credit, what
overlaps what, what the harness said) is recomputed here with compute_numbers.py's own functions (the
frozen scorer's Truth / _structures / _register_level, read-only) and must equal numbers.json's lists
exactly. The cause of each case is an attribution, written below per case with the evidence it rests on;
it uses docs/S3.md sections 8-9's codes, and a new code only where none fits (each says so and names the
nearest B1 code). Rates are never computed here: any rate quoted is copied from numbers.json with its path.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True   # never write bytecode under tools/ (the freeze covers that tree)

import collections  # noqa: E402
import datetime  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

ROOT = "/Users/dave/Jane_Street_Reverse_ASIC"
HERE = os.path.join(ROOT, "out", "s3", "replication", "analysis")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import compute_numbers as CN  # noqa: E402  (read-only reuse of the numbers script's scorer glue)

S = CN.S
NUMBERS = os.path.join(HERE, "numbers.json")
B1_MISSES = os.path.join(ROOT, "out", "s3", "blind", "analysis", "misses.json")
PLAN = os.path.join(ROOT, "docs", "S3_REPLICATION_PLAN.md")
KINDS = CN.KINDS


def sha(p):
    return CN.sha256_file(p)


def rng(bits):
    bits = sorted(bits)
    if not bits:
        return "[]"
    out, s, p = [], bits[0], bits[0]
    for x in bits[1:]:
        if x == p + 1:
            p = x
            continue
        out.append(f"{s}-{p}" if s != p else f"{s}")
        s = p = x
    out.append(f"{s}-{p}" if s != p else f"{s}")
    return "[" + ",".join(out) + "]"


# ------------------------------------------------------------------------------------------------
# the taxonomy: docs/S3.md sections 8-9 (B1), plus the codes this set needed. Every new code names the
# nearest B1 code and why that one does not fit.

B1_TAX = json.load(open(B1_MISSES))["cause_groups"]["blind"]

NEW_MISS = {
    "M3b": {
        "name": "merged with a parallel register into one multi-lane structure; IoU exactly 0.50 with each, "
                "so strict scoring credits neither",
        "mechanism": "two equal-depth lanes with the same flop controls are joined by the recognizer's lane rule "
                     "into ONE structure holding both truth registers whole; with two equal registers the IoU "
                     "with each is exactly 0.50 and score.py needs IoU > 0.5 (IOU_MIN), so neither is credited "
                     "in strict mode. The truth declares the pair a copy_lanes unit, which is an item only in "
                     "lenient mode, where both are credited",
        "nearest_B1": "M3",
        "why_not_B1": "B1's M3 is a merge in which the one-to-one matcher credited the structure to the larger "
                      "register and the other was a miss; here the two are the same size, so neither passes the "
                      "threshold. Same mechanism (a merge), different scoring consequence",
    },
    "M6b": {
        "name": "shift register of depth 2: below the frozen contract's minimum depth",
        "mechanism": "the truth's shift_register rule accepts a depth-2 register (D[k] = Q[k-1] on 1 of 1 "
                     "shiftable bits); tools/s3/verify.py SHIFT_MIN_DEPTH = 3 and tools/s3/params.py "
                     "SHIFT_MIN_DEPTH = 3 ('depth 2 is a transfer relation'), so no shift_register structure "
                     "can be emitted or verified over it",
        "nearest_B1": "M6",
        "why_not_B1": "M6 is the same contract floor for a synchronizer of one stage; this is its shift_register "
                      "twin, which B1 did not meet",
    },
    "M7": {
        "name": "straddling word: a counter structure over part of the register plus a flop of a neighbouring "
                "register, matching neither",
        "mechanism": "the recognizer's counting word takes one bit of the truth counter and one flop of a "
                     "neighbouring 1-bit register (IoU <= 0.5 with both), leaving the counter's other bit a "
                     "1-bit flag; no structure matches the register",
        "nearest_B1": "M1 / M3",
        "why_not_B1": "not M1 (the word is not a narrower sub-word of the register: half of it is a foreign "
                      "flop); not M3 (no structure holds the whole register, and nothing was matched); not M2 "
                      "(a scored-kind structure does overlap the register)",
    },
    "M8": {
        "name": "multi-mode shift register: the recognizer's structure follows one mode's copy relation, whose "
                "lanes run across the register and a parallel word-wise shift",
        "mechanism": "the register shifts in different directions in different FSM states (and loads constants "
                     "in others); the recognizer's shift structure over its flops follows ONE of those copy "
                     "relations, so its lanes and stages cut across the truth register and a parallel "
                     "register-array shift, and the register is held at IoU <= 0.25",
        "nearest_B1": "M4a / M4b (B1's only shift_register miss causes)",
        "why_not_B1": "B1's shift_register misses all took the affine-feedback exit to lfsr.py; this register has "
                      "no feedback -- shift.py did emit a structure over its flops, along another axis",
    },
}

NEW_FP = {
    "F3b": {
        "name": "counter over a sub-word of a truth counter, paired by the one-to-one matcher with a synthesis "
                "'retimed' register of kind other (matched, kind refused)",
        "mechanism": "the structure is a genuine counting sub-word of a truth counter (F3's mechanism), but the "
                     "truth also assigns its low flops to an 'other' register created for Yosys-merged flops, and "
                     "the matcher took that pair because its IoU is higher",
        "nearest_B1": "F3",
        "why_not_B1": "F3 is defined as 'matched nothing'; this one matched an item of another kind",
    },
    "F5": {
        "name": "shift_register over word-wise (array-entry) shift chains the truth labels data_register per entry",
        "mechanism": "RTL of the form reg[i] <= reg[i-1] over an unpacked array is a multi-lane shift register "
                     "whose stages are separate RTL registers; the labeller's shift rule looks for D[k] = Q[k-1] "
                     "inside ONE register, so each entry is a data_register. The recognizer's lanes are exactly "
                     "those entry-to-entry copies; several such chains that share a shift enable are joined into "
                     "one lanes_unordered structure",
        "nearest_B1": "none (B1 had no shift_register false positive)",
        "why_not_B1": "F1-F4 are counter or lfsr_crc structures",
    },
    "F6": {
        "name": "shift_register over a chain of 1-bit truth registers (a pipeline written one RTL register per "
                "stage, labelled flag per stage)",
        "mechanism": "each stage is its own 1-bit RTL register (per module instance, or three named registers), "
                     "which the labeller's rules call 'single-bit register' (flag); the labeller's copy_lanes "
                     "unit rule joins only registers already labelled shift_register or synchronizer, so no truth "
                     "item spans the chain the recognizer returned",
        "nearest_B1": "none (B1 had no shift_register false positive)",
        "why_not_B1": "F1-F4 are counter or lfsr_crc structures",
    },
    "F7": {
        "name": "counter straddling a truth counter bit and a truth flag (matched nothing)",
        "mechanism": "the structure side of M7",
        "nearest_B1": "F3",
        "why_not_B1": "F3's word is a sub-word of ONE truth counter; half of this word is a flop of another register",
    },
    "F8": {
        "name": "multi-lane shift_register merging two parallel truth shift registers (IoU 0.50 each; matched "
                "nothing in strict mode)",
        "mechanism": "the structure side of M3b",
        "nearest_B1": "none",
        "why_not_B1": "B1's M3 merge was credited to one of its two registers, so it produced no false positive",
    },
}

# ------------------------------------------------------------------------------------------------
# label disagreements (listed, never applied)

DISAGREEMENTS = [
    {"id": "R-D1", "same_as_B1": "D1",
     "designs": ["ttcad25a__tt_um_space_invaders_game"],
     "truth_registers": ["lfsr (8 flops)"], "truth_kind": "shift_register", "recognizer_kind": "lfsr_crc",
     "rtl": "project.v: lfsr <= {lfsr[6:0], lfsr_feedback}; lfsr_feedback = lfsr[7] ^ lfsr[5] ^ lfsr[4] ^ lfsr[3]; "
            "reset to 8'hA5",
     "why": "an author-named 8-bit Fibonacci LFSR. The labeller's lfsr_crc rule needs own-Q XOR feedback into at "
            "least max(2, n/4) bits and a Fibonacci LFSR XORs into one head bit, so its shift_register rule "
            "claimed it; the truth's own params.serial_in is 'lfsr_feedback'. The recognizer's lfsr0 (form "
            "fibonacci, poly 285, k_steps 1) is harness-VERIFIED over exactly those 8 flops (IoU 1.00).",
     "cost": "1 shift_register miss (M4a) and 1 lfsr_crc false positive (F4), the same register counted in both",
     "applied": False},
    {"id": "R-D2", "same_as_B1": "D4",
     "designs": ["ttcad25a__tt_um_space_invaders_game", "tt05__tt_um_nickjhay_processor"],
     "truth_registers": ["prev_button0 (1 flop)", "prev_button1 (1 flop)", "prev_button2 (1 flop)",
                         "sys_in1_buffer (8 flops)"],
     "truth_kind": "synchronizer (params.stages = 1)", "recognizer_kind": "flag (x3); stage 0 of a shift_register",
     "rtl": "space invaders project.v: prev_button0 <= ui_in[0] (likewise 1, 2), commented 'Capture previous "
            "button states for edge-detection'; nickjhay main.v: sys_in1_buffer <= ui_in on the cycles "
            "sys_in1_next is 1, 8'b0 on the others",
     "why": "the labeller's rule 3 calls a register whose D is an input pin a synchronizer of ONE stage; the "
            "frozen contract defines a synchronizer as >= 2 stages (verify.py SYNC_MIN_STAGES = 2). The two "
            "conventions disagree and the recognizer cannot satisfy both. Three of the four are edge-detector "
            "'previous value' flops and the fourth an input capture register, which the RTL does not present as "
            "synchronizers either.",
     "cost": "all 4 R synchronizer misses (M6)",
     "applied": False},
    {"id": "R-D3", "same_as_B1": None,
     "designs": ["tt06__tt_um_SJ", "ttsky25b__tt_um_yorimichi_kittscanner"],
     "truth_registers": ["DUT.U*.filter_spad[0..2], DUT.U*.ifmap_spad[0..2] (54 registers of 8 flops, all "
                         "Tier A)", "i_kitt_scan_core.pwmsel[0..7] (8 registers of 3 flops)"],
     "truth_kind": "data_register (per array entry)", "recognizer_kind": "shift_register (multi-lane)",
     "rtl": "SJ PE.sv: if (read_new_filter_val) { filter_spad[i] <= filter_spad[i-1] (i = 2, 1); filter_spad[0] "
            "<= filter_i } and the same for ifmap_spad; kitt kitt_scan_core.v: next_pwmsel[i] = pwmsel[i-1] "
            "(left shift) or pwmsel[i+1] (right shift) in the scan states",
     "why": "word-wise shift registers over unpacked-array entries. The labeller's shift_register rule looks "
            "for D[k] = Q[k-1] inside one register, so each entry is labelled data_register ('loads external or "
            "computed values'). None of these registers is in any scored denominator, so the disagreement costs "
            "false positives, not misses.",
     "cost": "4 shift_register false positives (F5), 0 misses",
     "note": "RELABELLING ALONE WOULD NOT RECOVER SJ: each of its three structures holds 4 spad chains of 4 "
             "different PEs (12 entries, 96 flops), so a truth that named each 24-flop chain a shift_register "
             "would still sit at IoU 0.25 with it.",
     "applied": False},
    {"id": "R-D4", "same_as_B1": None,
     "designs": ["tt05__tt_um_nickjhay_processor", "tt05__tt_um_digital_clock_sellicott"],
     "truth_registers": ["sa.iloop[i].jloop[j].sxy.out1 / .out2 (1 flop each, 64 + 64 cells)",
                         "clock_inst.refclk_gen_inst.refclk_ext, refclk_pipe0, refclk_pipe1 (1 flop each)"],
     "truth_kind": "flag (per stage)", "recognizer_kind": "shift_register",
     "rtl": "nickjhay main.v systolic_cell: out1 <= in1, out2 <= in2 under sys_in_valid, and cell (i+1, j) reads "
            "out1 of cell (i, j) -- the author's comment: 'successive out1's will form shift registers'; "
            "sellicott reference_clk_stb.v: {refclk_pipe1, refclk_pipe0, refclk_ext} <= {refclk_pipe0, "
            "refclk_ext, i_refclk} under i_en -- the author's comment: 'a clock domain crossing for the refclk "
            "signal'",
     "why": "pipelines written one 1-bit RTL register per stage. The labeller's rules call each a 'single-bit "
            "register' (flag); its synchronizer rule needs 'no enable' (sellicott's chain has i_en), and its "
            "copy_lanes unit rule only joins registers already labelled shift_register or synchronizer. The "
            "recognizer's shift structures over them are real: 2 of the 3 are harness-VERIFIED.",
     "cost": "3 shift_register false positives (F6), 0 misses",
     "applied": False},
    {"id": "R-D5", "same_as_B1": "D3 (the same arithmetic rule firing on a non-counter)",
     "designs": ["ttsky25b__tt_um_yorimichi_kittscanner"],
     "truth_registers": ["i_kitt_scan_core.state (6 flops)"], "truth_kind": "counter (step 1, modulus 2)",
     "recognizer_kind": "data_register (2 flops) + 4 flags",
     "rtl": "kitt_scan_core.v: the FSM state register; next_state = state + 1'b1 through the scan sequences and a "
            "constant (IDLE, CAPT, HEAD_MD0 = 10, HEAD_MD1 = 40, HEAD_MD2 = 50, HEAD_MD3 = 2) elsewhere",
     "why": "the truth's arithmetic rule ('D = Q +/- constant') reads state + 1 as a counter; the register is a "
            "sequencer with constant jumps, and the truth's own params.modulus = 2 is not consistent with the "
            "RTL, whose state codes run to HEAD_MD2 + 9 = 59.",
     "cost": "1 counter miss (M2b)",
     "applied": False},
    {"id": "R-D6", "same_as_B1": None, "strength": "weak",
     "designs": ["ttcad25a__tt_um_space_invaders_game"],
     "truth_registers": ["score (10 bits, 9 flops; every mapped bit z3-refuted, Tier A)"],
     "truth_kind": "counter (step null)", "recognizer_kind": "data_register (7 flops) + 2 flags",
     "rtl": "project.v: score <= score + 10, + 20 or + 30 at 40 hit sites, depending on the alien row",
     "why": "the kind 'counter' is defensible under the rule 'D = Q + constant', but there is no single step "
            "(the truth's params.step is null) and the frozen counter template (verify.py) needs one constant "
            "step, so no structure could ever verify it as labelled; the label is also Tier A.",
     "cost": "1 counter miss (M2b)",
     "applied": False},
    {"id": "R-D7", "same_as_B1": "D4 (the same kind of convention conflict, for shift_register)",
     "designs": ["tt06__tt_um_SJ"],
     "truth_registers": ["DUT.U1.PEStartEN (2 flops; both z3-refuted and mismatching simulation, Tier A)"],
     "truth_kind": "shift_register (depth 2)", "recognizer_kind": "2 flags",
     "rtl": "topLevelControl.sv: nextPEStartEN[1] = PEStartEN[0]; nextPEStartEN[0] = 1'b1 (runOS) or "
            "PEReadNaive[0] | [1] | [2] (endOS)",
     "why": "the labeller accepts a depth-2 shift; the frozen contract requires depth >= 3 (verify.py and "
            "params.py SHIFT_MIN_DEPTH = 3). The two conventions disagree and the recognizer cannot satisfy both.",
     "cost": "1 shift_register miss (M6b)",
     "applied": False},
]

# ------------------------------------------------------------------------------------------------
# per-case attributions. key: (design, truth register) for a miss, (design, structure id) for a false positive.
# Each: cause, mechanism (what happened, with the evidence it rests on), truth_looks_wrong, disagreement.

SJ, KITT, CLK, NICK, SIM, PARA, SPACE, TINY = (
    "tt06__tt_um_SJ", "ttsky25b__tt_um_yorimichi_kittscanner", "tt05__tt_um_digital_clock_sellicott",
    "tt05__tt_um_nickjhay_processor", "ttsky25b__tt_um_ieeeuoftasic_simproc", "ttsky26a__tt_um_parakeet",
    "ttcad25a__tt_um_space_invaders_game", "ttsky26b__tt_um_tiny_8bit_cpu")

_M7_TXT = ("PE.sv: next_counter = calculating_RS ? counter + 1 : 0 -- a 2-bit counter enabled by the FSM flag "
           "calculating_RS, which falls when counter == 3. The recognizer returned the 2-flop counter {S} (down by "
           "1, modulus 3; refused by the harness, bucket 'hold': control.hold not claimed) over counter bit 0 and "
           "the flop the truth maps to {P}.calculating_RS, and left counter bit 1 as the 1-bit flag {W}; IoU "
           "0.33 with the register and 0.50 with the flag, so it matched neither. The truth's mapping of that "
           "calculating_RS flop is z3-refuted and mismatches simulation in every PE (Tier A): the netlist flop "
           "does not compute RTL calculating_RS. The counter register itself is Tier C.")
_M7 = {"DUT.U2": ("counter3", "w58"), "DUT.U3": ("counter9", "w50"), "DUT.U5": ("counter7", "w36"),
       "DUT.U7": ("counter5", "w38"), "DUT.U8": ("counter10", "w59"), "DUT.U9": ("counter8", "w10"),
       "DUT.U10": ("counter4", "w55")}

MISS = {}
for pe, (sid, wid) in _M7.items():
    MISS[(SJ, f"{pe}.counter")] = dict(cause="M7", mechanism=_M7_TXT.format(S=sid, P=pe, W=wid),
                                       truth_looks_wrong="no (register Tier C; the paired calculating_RS flop is "
                                                         "Tier A)", disagreement=None)
for pe, wid in (("DUT.U4", "w37"), ("DUT.U6", "w54")):
    MISS[(SJ, f"{pe}.counter")] = dict(
        cause="M2a",
        mechanism=f"The same PE module as the seven M7 instances; here both counter flops were emitted as one "
                  f"2-flop data_register ({wid}) at IoU 1.00 -- extent right, kind unscored, so the harness never "
                  f"checked it. No scored-kind structure touches the register.",
        truth_looks_wrong="no", disagreement=None)
MISS[(SJ, "DUT.U1.PEStartEN")] = dict(
    cause="M6b",
    mechanism="topLevelControl.sv: nextPEStartEN[1] = PEStartEN[0], nextPEStartEN[0] = 1'b1 or an OR of "
              "PEReadNaive -- a 2-stage shift. verify.py SHIFT_MIN_DEPTH = 3 (and params.py SHIFT_MIN_DEPTH = 3, "
              "'depth 2 is a transfer relation'), so no shift_register structure can be emitted or verified; the "
              "two flops came back as 1-bit flags (w52, w53). Both mapped bits are z3-refuted and mismatch "
              "simulation (Tier A).",
    truth_looks_wrong="convention conflict (and Tier A)", disagreement="R-D7")
MISS[(KITT, "i_kitt_scan_core.prescaler")] = dict(
    cause="M1",
    mechanism="kitt_scan_core.v: prescaler counts up by 1 and wraps at a terminal count chosen by the captured "
              "SPEED flop (NUM_NORM-1 = 1,499,999 or NUM_FAST-1 = 999,999), and is cleared whenever psc_enable is "
              "low -- a wrap that is neither a power of two nor fixed. The recognizer returned two harness-VERIFIED "
              "counting sub-words, counter1 (truth bits 4-12, modulus 512) and counter3 (bits 15-19, modulus 32), "
              "and its own relation record links them (type cascade, lower counter1, upper counter3); bits 1-3 "
              "came back as a data_register and bits 0, 13, 14 and 20 as flags. Best IoU 0.43.",
    truth_looks_wrong="no", disagreement=None)
MISS[(KITT, "i_kitt_scan_core.state")] = dict(
    cause="M2b",
    mechanism="kitt_scan_core.v: the 6-bit FSM state register; next_state is state + 1 through the scan "
              "sequences and a constant state code elsewhere, advancing only on psc_ovf and forced to IDLE when "
              "ENA is low. The recognizer "
              "emitted a 2-flop data_register (bits 4-5) and four flags; no scored-kind structure touches it.",
    truth_looks_wrong="arguable: an FSM with constant jumps labelled counter, with a modulus (2) the RTL "
                      "contradicts", disagreement="R-D5")
MISS[(KITT, "i_kitt_scan_core.pre_lvout")] = dict(
    cause="M8",
    mechanism="kitt_scan_core.v: pre_lvout shifts right ({1'b0, pre_lvout[7:1]}) in some scan states, left "
              "({pre_lvout[6:0], 1'b0}) in others, moves its two halves in opposite directions in mode 1 "
              "(HEAD_MD1+2..4 and HEAD_MD1+7) and loads constants elsewhere; pwmsel[0..7] (3 bits each) shifts "
              "word-wise alongside it. The one shift structure over these flops, shift_register#1, follows ONE of "
              "those copy relations -- the HEAD_MD1+7 step, whose two middle heads load constants (proof notes: "
              "head_kind 'const') -- so it has 8 lanes of depth 4: pre_lvout[3]->[2]->[1]->[0], "
              "pre_lvout[4]->[5]->[6]->[7] and six half-lanes through pwmsel bits. The truth register's 8 flops "
              "are 2 of its 8 lanes (IoU 0.25); the harness refused it ('hold' not claimed). The truth's reading "
              "is one lane of depth 8 toward LSB.",
    truth_looks_wrong="no (a bidirectional shift; the truth picked the right-shift reading)", disagreement=None)
MISS[(CLK, "clock_inst.shift_out_inst.shift_out_inst.transfer_state")] = dict(
    cause="M1",
    mechanism="shift_register.v: reg [2*WIDTH:0] transfer_state is 97 bits for WIDTH = 48 (the 48-flop "
              "serial_data register), counts up by 1 under TRANSFER & i_clk_stb and is cleared in IDLE; the FSM "
              "leaves TRANSFER once transfer_state >= 2*WIDTH-1 = 95, so in operation only the low 7 bits ever "
              "toggle and bits 7-96 never leave 0. The recognizer returned counter0 over bits 1-37 "
              "(harness-VERIFIED, modulus 2^37) and counter4 over bits 84-95 (12 flops = params.py "
              "EXHAUSTIVE_WIDTH; refused, 'vacuous' test (a)), linked as a cascade (lower counter0, upper "
              "counter4); bits 38-83 came back as one 46-flop data_register and bits 0 and 96 as flags. Best IoU "
              "0.47 (the data_register), 0.38 for counter0. The same family as B1's 32-bit integers whose top "
              "bits never reach their toggle point (docs/S3.md 8.1).",
    truth_looks_wrong="no (97 bits is the RTL declaration; most of them are unreachable)", disagreement=None)
for reg in ("clock_inst.mode0_db_inst.samples", "clock_inst.mode1_db_inst.samples"):
    MISS[(CLK, reg)] = dict(
        cause="M3b",
        mechanism="button_debounce.v: samples <= {samples[NUM_SAMPLES-2:0], sample_pipe} -- a 5-deep shift "
                  "register per debounced button; the mode0 and mode1 instances share clock, enable and reset. "
                  "The recognizer joined them into ONE 2-lane x depth-5 shift_register (shift_register#2, "
                  "harness-VERIFIED, lanes_unordered) at IoU exactly 0.50 with each register, so strict scoring "
                  "credits neither. The truth itself declares the pair a copy_lanes unit ('S3's lane rule joins "
                  "such lanes into one structure'), which is an item in lenient mode only: there both registers "
                  "are found and verified (numbers.json notes).",
        truth_looks_wrong="no", disagreement=None)
MISS[(NICK, "sys_in1_buffer")] = dict(
    cause="M6",
    mechanism="main.v: sys_in1_buffer <= ui_in on the cycles sys_in1_next is 1 and 8'b0 on the others -- an "
              "8-bit input capture register the truth labels a synchronizer of one stage (params.stages = 1). "
              "verify.py SYNC_MIN_STAGES = 2, so it can never be reported or verified as labelled. The recognizer "
              "placed its 8 flops as stage 0 of the 8-lane x depth-8 shift structure shift_register#0 that runs "
              "down the systolic array's out1 chain (IoU 0.125; refused, 'hold' not claimed; see F6).",
    truth_looks_wrong="convention conflict", disagreement="R-D2")
_PARA = {
    "race_stage": "project.v: 3-bit stage counter, +1 modulo 5, stepping only on frame_tick & stage_done "
                  "(stage_done = stage_timer == 8'hFF) and cleared by gp_start_held. Bits 1-2 came back as a "
                  "data_register (w7, IoU 0.67: the unaccepted-kind match) and bit 0 as a flag (w6); no "
                  "scored-kind structure touches it.",
    "stage_timer": "project.v: 8-bit counter stepping on frame_tick, cleared at 8'hFF (stage_done) and by "
                   "gp_start_held. Bits 1-6 came back as one data_register (w1, IoU 0.75), bits 0 and 7 as flags; "
                   "no scored-kind structure touches it.",
    "speed": "project.v: 4-bit saturating up/down counter (up on gp_a_held unless 4'hF, down otherwise unless 0, "
             "forced to 0 when not driving), stepping on frame_tick. Two 2-flop data_registers (bits 0-1, 2-3; "
             "best IoU 0.50); no scored-kind structure touches it.",
}
for reg, txt in _PARA.items():
    MISS[(PARA, reg)] = dict(cause="M2b", mechanism=txt, truth_looks_wrong="no", disagreement=None)
MISS[(SPACE, "pb_y")] = dict(
    cause="M1",
    mechanism="project.v: pb_y is loaded with SHOOTER_Y - 25 when a bullet spawns and steps down by 25 once per "
              "frame while pb_y > 130. The recognizer split it at the borrow out of bit 4: counter4 over bits 0-4 "
              "as an up-counter by 7 modulo 32 (-25 = +7 mod 32; refused, 'hold' not claimed) and counter6 over "
              "bits 5-8 as a down-counter by 1 modulo 16 (harness-VERIFIED); bit 9 is a flag. counter4 sits at IoU "
              "exactly 0.50 and score.py needs IoU > 0.5 -- a failure by equality, as two of B1's five M1s were.",
    truth_looks_wrong="no", disagreement=None)
MISS[(SPACE, "sync_gen.vpos")] = dict(
    cause="M1",
    mechanism="vga_sync_generator: vpos counts 0..524 (modulus 525). The recognizer returned counter3 over bits "
              "0-4 (harness-VERIFIED, modulus 32; linked as a cascade above counter0, the found hpos) and left bits "
              "5-9 in a 2-flop data_register (bits 6, 8) and three flags. counter3 is at IoU exactly 0.50 with "
              "vpos (equality again). The truth maps vpos bits 0-3 to flops Yosys merged with "
              "barrier1.bar_rom.row_index[0..3] (bits[].how = 'merged') and lists the same four flops as the "
              "'other' register sync_gen.vpos__retimed, so the one-to-one matcher paired counter3 with that "
              "register instead (IoU 0.80, kind refused; F3b). The same RTL shape was found exactly on "
              "ttsky26a__tt_um_parakeet (vga_sync_gen.vpos: counter0, IoU 1.00, harness-VERIFIED), whose truth "
              "marks one vpos bit merged; this report does not claim the merge is the whole difference.",
    truth_looks_wrong="no", disagreement=None)
MISS[(SPACE, "score")] = dict(
    cause="M2b",
    mechanism="project.v: score <= score + 10, + 20 or + 30 at 40 hit sites -- no single constant step (the "
              "truth's params.step is null). A 7-flop data_register (w4: bits 0 and 2-7, IoU 0.78) and two flags; "
              "no scored-kind structure touches it. Every mapped bit of the truth register is z3-refuted (Tier A) "
              "and RTL bits 0 and 1 share one netlist flop.",
    truth_looks_wrong="arguable (weak): a multi-constant adder no constant-step template fits; Tier A",
    disagreement="R-D6")
MISS[(SPACE, "lfsr")] = dict(
    cause="M4a",
    mechanism="project.v: lfsr <= {lfsr[6:0], lfsr_feedback}, lfsr_feedback = lfsr[7]^lfsr[5]^lfsr[4]^lfsr[3] -- "
              "an author-named Fibonacci LFSR. shift.py recorded one feedback head over 7 stages with verdict "
              "'affine' (stage stats feedback_affine 2: the one head recorded twice), so the lane went to lfsr.py, "
              "which admitted one lfsr_crc (lfsr0: form fibonacci, poly 285, k_steps 1, 0 inputs), "
              "harness-VERIFIED at IoU 1.00 over exactly the truth register's flops -- B1's M4a, exactly.",
    truth_looks_wrong="yes (a Fibonacci LFSR labelled shift_register)", disagreement="R-D1")
for reg, wid, src in (("prev_button0", "w43", "ui_in[0]"), ("prev_button1", "w39", "ui_in[1]"),
                      ("prev_button2", "w8", "ui_in[2]")):
    MISS[(SPACE, reg)] = dict(
        cause="M6",
        mechanism=f"project.v: {reg} <= {src}, an edge detector's previous-value flop ('Capture previous button "
                  f"states for edge-detection'). The truth's rule 3 labels a register whose D is an input pin a "
                  f"synchronizer of ONE stage (params.stages = 1); verify.py SYNC_MIN_STAGES = 2 and shift.py "
                  f"emits a synchronizer only over stages 1-2 of an input copy path, so it can never be reported "
                  f"or verified as labelled. The recognizer emitted the flop as the 1-bit flag {wid} (IoU 1.00).",
        truth_looks_wrong="convention conflict; the RTL presents it as an edge detector", disagreement="R-D2")

FP = {}
FP[(TINY, "counter0")] = dict(
    cause="F2",
    mechanism="registers.v: pc_q <= pc_d under pc_we, where the datapath's pc_d is pc_q plus a multi-bit value "
              "(the truth's rule 'D = Q + a multi-bit variable'). A 2-flop up/down counter (modulus 4) over pc_q "
              "bits 3-4; IoU 0.40; refused ('hold' not claimed). None of its flops was dropped: the design's 72 "
              "unmapped flops fell only in structures of unscored kinds.",
    truth_looks_wrong="no", disagreement=None)
for i in (0, 1, 2):
    FP[(SJ, f"shift_register#{i}")] = dict(
        cause="F5",
        mechanism="PE.sv: if (read_new_filter_val) filter_spad[i] <= filter_spad[i-1] (i = 2, 1), filter_spad[0] "
                  "<= filter_i, and the same for ifmap_spad -- 8-bit x 3-entry word-wise shift registers the "
                  "truth labels data_register per entry (all 54 spad entries Tier A). Every one of the structure's "
                  "32 lanes is exactly spad[0][b] -> spad[1][b] -> spad[2][b] of one PE; 4 spads of 4 different "
                  "PEs are joined because they share a shift enable (lanes_unordered). Refused ('hold' not "
                  "claimed). It overlaps 12 truth data_registers at IoU 0.08 each.",
        truth_looks_wrong="yes (word-wise shift registers labelled data_register; Tier A)", disagreement="R-D3")
for pe, (sid, wid) in _M7.items():
    FP[(SJ, sid)] = dict(
        cause="F7",
        mechanism=f"The structure side of {pe}.counter's M7 miss: a 2-flop down-counter (modulus 3) over "
                  f"{pe}.counter bit 0 and the (Tier A) {pe}.calculating_RS flop; IoU 0.33 / 0.50; refused "
                  f"('hold' not claimed).",
        truth_looks_wrong="no (the flag's mapping is refuted, Tier A)", disagreement=None)
FP[(SJ, "counter6")] = dict(
    cause="F2",
    mechanism="PE.sv: psum_spad <= adder_input + psum_spad (the truth's accumulator; Tier A). A 2-flop "
              "down-counter (modulus 4) over DUT.U7.psum_spad bits 0-1; IoU 0.20; refused ('hold' not claimed); "
              "recorded as a cascade above counter5.",
    truth_looks_wrong="no", disagreement=None)
FP[(KITT, "shift_register#1")] = dict(
    cause="F5",
    mechanism="The structure of pre_lvout's M8 miss: 8 lanes x depth 4 (the HEAD_MD1+7 copy step) through "
              "pre_lvout (truth shift_register, 8 flops) and pwmsel[0..7] (truth data_registers, 24 flops; "
              "next_pwmsel[i] = pwmsel[i+/-1] is a word-wise shift the truth does not name). Refused ('hold' not "
              "claimed); IoU 0.25 with pre_lvout, 0.09 with each pwmsel entry.",
    truth_looks_wrong="partly (pwmsel is a word-wise shift labelled data_register)", disagreement="R-D3")
FP[(KITT, "counter1")] = dict(
    cause="F3", mechanism="The structure side of the prescaler's M1: a harness-VERIFIED counting sub-word (bits "
                          "4-12, modulus 512) of the 21-bit truth counter; IoU 0.43.",
    truth_looks_wrong="no", disagreement=None)
FP[(KITT, "counter3")] = dict(
    cause="F3", mechanism="The structure side of the prescaler's M1: a harness-VERIFIED counting sub-word (bits "
                          "15-19, modulus 32), cascaded above counter1; IoU 0.24.",
    truth_looks_wrong="no", disagreement=None)
FP[(KITT, "counter4")] = dict(
    cause="F3", mechanism="i_debouncer.prescaler (18-bit counter) is FOUND by counter0 (bits 0-11: 12 flops = "
                          "EXHAUSTIVE_WIDTH, IoU 0.67, harness-VERIFIED); counter4 is a further harness-VERIFIED "
                          "2-bit sub-word over bits 16-17, linked as a cascade above counter0; IoU 0.11.",
    truth_looks_wrong="no", disagreement=None)
FP[(CLK, "shift_register#2")] = dict(
    cause="F8", mechanism="The structure side of the mode0/mode1 samples M3b: harness-VERIFIED, 2 lanes x depth 5, "
                          "IoU 0.50 with each truth register; credited to both in lenient mode through the truth's "
                          "copy_lanes unit, to neither in strict mode.",
    truth_looks_wrong="no", disagreement=None)
FP[(CLK, "shift_register#3")] = dict(
    cause="F6", mechanism="reference_clk_stb.v: {refclk_pipe1, refclk_pipe0, refclk_ext} <= {refclk_pipe0, "
                          "refclk_ext, i_refclk} under i_en -- the author's own 'clock domain crossing for the "
                          "refclk signal'. Three 1-bit truth flags; the recognizer's 3-deep shift_register over them "
                          "is harness-VERIFIED (under the contract a synchronizer may carry no condition, so i_en "
                          "makes it a shift register). IoU 0.33 with each flag.",
    truth_looks_wrong="yes (a 3-stage enabled pipeline labelled three flags)", disagreement="R-D4")
FP[(CLK, "counter0")] = dict(
    cause="F3", mechanism="The structure side of transfer_state's M1: a harness-VERIFIED 37-bit counting sub-word "
                          "(bits 1-37) of the 97-bit truth counter; IoU 0.38.",
    truth_looks_wrong="no", disagreement=None)
FP[(CLK, "counter4")] = dict(
    cause="F3", mechanism="The structure side of transfer_state's M1: a 12-flop sub-word (bits 84-95, = "
                          "EXHAUSTIVE_WIDTH), refused by the harness ('vacuous' test (a): the hold region is empty "
                          "only once the opaque load case is conjoined); IoU 0.12.",
    truth_looks_wrong="no", disagreement=None)
FP[(CLK, "counter2")] = dict(
    cause="F1", mechanism="load_divider.v: counter <= counter + incriment, incriment a 25-bit register loaded with "
                          "i_incriment + 1 -- the truth's accumulator (rule 'D = Q + a multi-bit variable'). counter2 "
                          "= bits 5-24, up by 1 modulo 2^20, harness-VERIFIED, matched the accumulator at IoU 0.80 "
                          "and was refused credit on the kind: a constant-step counter proved on the upper lanes, "
                          "whose count condition is the carry out of bits 0-4 -- B1's F1 reading.",
    truth_looks_wrong="no", disagreement=None)
FP[(CLK, "counter8")] = dict(
    cause="F2", mechanism="The same accumulator's bits 0-4: up by 1 modulo 32 with a load case, harness-VERIFIED; "
                          "IoU 0.20.",
    truth_looks_wrong="no", disagreement=None)
_SYS = ("sysclk_divider.v: counter <= counter + INCRIMENT with the constant 858 (the truth's step; bit 0 never "
        "toggles and has no netlist flop, Tier B). The register is FOUND by counter1 (bits 11-31, IoU 0.68, "
        "harness-VERIFIED with step 1 -- a certified step that disagrees with the truth's 858, listed in "
        "numbers.json's wrong parameters). The low bits of a +858 counter form modular sub-counters of their "
        "own; {D}")
FP[(CLK, "counter10")] = dict(cause="F3", mechanism=_SYS.format(
    D="counter10 is bits 1-3 counting down by 3 modulo 8 (858 / 2 = 429 = 5 = -3 mod 8), harness-VERIFIED; IoU "
      "0.10."), truth_looks_wrong="no", disagreement=None)
FP[(CLK, "counter11")] = dict(cause="F3", mechanism=_SYS.format(
    D="counter11 is bits 5-6, down by 1 modulo 4 under a carry condition, harness-VERIFIED; IoU 0.06."),
    truth_looks_wrong="no", disagreement=None)
FP[(CLK, "counter13")] = dict(cause="F3", mechanism=_SYS.format(
    D="counter13 is bits 8-9, down by 1 modulo 4 under a carry condition, harness-VERIFIED; IoU 0.06."),
    truth_looks_wrong="no", disagreement=None)
FP[(NICK, "shift_register#0")] = dict(
    cause="F6", mechanism="main.v systolic_cell: out1 <= in1 under sys_in_valid (out1 <= in1 | acc on readout), and "
                          "cell (i+1, j) reads out1 of cell (i, j) -- the author's comment: 'successive out1's will "
                          "form shift registers'. Each out1 is a 1-bit RTL register the truth labels flag. The "
                          "structure is 8 lanes x depth 8: sys_in1_buffer[j] -> out1 of cells (0..6, j). Refused "
                          "('hold' not claimed). IoU 0.125 with sys_in1_buffer (a truth synchronizer, R-D2), 0.016 "
                          "with each out1 flag.",
    truth_looks_wrong="yes (a pipeline labelled one flag per stage)", disagreement="R-D4")
FP[(NICK, "shift_register#1")] = dict(
    cause="F6", mechanism="main.v: the systolic out2 chain (out2 <= in2; cell (i, j+1) reads out2 of cell (i, j)): "
                          "8 lanes x depth 7 over 56 1-bit truth flags; harness-VERIFIED. IoU 0.018 with each flag.",
    truth_looks_wrong="yes (a pipeline labelled one flag per stage)", disagreement="R-D4")
FP[(SIM, "counter4")] = dict(
    cause="F3", mechanism="simproc_system.sv UART_RX: clkCount counts up to a run-time compare value derived from "
                          "clk_per_bit (adjustable baud) and clears. The register is FOUND by counter0 (bits 0-6, IoU "
                          "0.70; refused, 'vacuous' test (a): a V2 found-but-unverified register); counter4 is a "
                          "harness-VERIFIED 2-bit sub-word over bits 8-9; IoU 0.20.",
    truth_looks_wrong="no", disagreement=None)
FP[(PARA, "counter2")] = dict(
    cause="F2", mechanism="project.v: road_z <= road_z + {8'd0, speed_eff} (the truth's accumulator; Tier A). "
                          "counter2 = road_z bits 1-2, up by 1 modulo 4, harness-VERIFIED; IoU 0.29.",
    truth_looks_wrong="no", disagreement=None)
FP[(SPACE, "counter3")] = dict(
    cause="F3b", mechanism="The structure side of sync_gen.vpos's M1: a harness-VERIFIED 5-bit sub-word (bits 0-4, "
                           "modulus 32) of the mod-525 truth counter (IoU 0.50), paired instead with the 'other' "
                           "register sync_gen.vpos__retimed, whose 4 flops are vpos bits 0-3 (IoU 0.80, kind "
                           "refused).",
    truth_looks_wrong="no (the double assignment of 4 flops is the labeller's retiming convention)",
    disagreement=None)
FP[(SPACE, "counter4")] = dict(
    cause="F3", mechanism="The structure side of pb_y's M1: bits 0-4 as up by 7 modulo 32 (-25 mod 32), refused "
                          "('hold' not claimed); IoU exactly 0.50.",
    truth_looks_wrong="no", disagreement=None)
FP[(SPACE, "counter6")] = dict(
    cause="F3", mechanism="The structure side of pb_y's M1: bits 5-8, down by 1 modulo 16, harness-VERIFIED; IoU "
                          "0.40.",
    truth_looks_wrong="no", disagreement=None)
FP[(SPACE, "counter12")] = dict(
    cause="F3", mechanism="shooter_x moves by +/-10 within bounds (the truth's step 10; Tier A, RTL bits 0 and 1 "
                          "share one flop). The register is FOUND by counter5 (bits 0 and 2-5, IoU 0.56, step 5; "
                          "refused, V1). counter12 is a harness-VERIFIED 2-bit saturating down-counter over bits "
                          "8-9; IoU 0.22.",
    truth_looks_wrong="no", disagreement=None)
FP[(SPACE, "lfsr0")] = dict(
    cause="F4", mechanism="The structure side of the lfsr M4a: an lfsr_crc (fibonacci, poly 285) harness-VERIFIED "
                          "at IoU 1.00 over the truth shift_register 'lfsr'.",
    truth_looks_wrong="yes (a Fibonacci LFSR labelled shift_register)", disagreement="R-D1")


# ------------------------------------------------------------------------------------------------

def taxonomy_entry(code, section):
    if section == "misses" and code in NEW_MISS:
        return dict(NEW_MISS[code], origin="NEW in R (no B1 code fits)")
    if section == "false_positives" and code in NEW_FP:
        return dict(NEW_FP[code], origin="NEW in R (no B1 code fits)")
    b = B1_TAX[section][code]
    return {"name": b["name"], "mechanism": b["mechanism"], "origin": "B1 (docs/S3.md sections 8-9)"}


def main():
    fc_before = CN.freeze_check()
    numbers = json.load(open(NUMBERS))
    b1 = json.load(open(B1_MISSES))

    cases, designs_block = [], {}
    mech_miss, mech_fp, mech_fu = [], [], []
    for design, base in CN.R_RECORDS:
        path = os.path.join(CN.RUNS, base)
        D = CN.design_data("R", path)
        T, structs, ev = D["T"], D["structs"], D["ev"]
        V = ev["verify"]["structures"]
        by_id = {s["id"]: s for s in structs}
        raw = {s["id"]: s for s in ev["result"]["structures"]}
        rows = CN.register_rows(D)
        ms, fps, fu = CN.misses(D, rows), CN.false_positives(D), CN.found_unverified(D, rows)
        mech_miss += ms
        mech_fp += fps
        mech_fu += fu
        rel_counter = ev["result"]["meta"]["relations"].get("counter") or []
        rec_stats = ev["result"]["meta"]["recognizers"]
        rej = (rec_stats.get("counter") or {}).get("rejected") or {}
        designs_block[design] = {
            "record": CN.rel(path), "record_sha256": sha(path),
            "truth": CN.rel(D["truth_path"]), "truth_sha256": sha(D["truth_path"]),
            "rescore_equals_record": D["rescore_equals_record"],
            "counter_rejected_candidates_top5": dict(collections.Counter(rej).most_common(5)),
            "counter_rejected_note": "design-level candidate counts, NOT per-register attributions (docs/S3.md 8.1)",
            "shift_stage": {k: v for k, v in (rec_stats.get("shift") or {}).items()},
            "lfsr_stage": {k: v for k, v in (rec_stats.get("lfsr") or {}).items() if k != "lfsr_words"},
            "shift_relations": {k: (v if k in ("feedback", "alternative_decomposition") else len(v))
                                for k, v in (ev["result"]["meta"]["relations"].get("shift") or {}).items()},
            "counter_relations": rel_counter,
        }

        def verdict(s):
            vd = V[s["pos"]] if s["pos"] < len(V) else {}
            return {"verified": bool(s["verified"]), "bucket": S._bucket(s), "reason": vd.get("reason")}

        def relations_of(ids):
            return [r for r in rel_counter if r.get("lower_word") in ids or r.get("upper_word") in ids]

        for m in ms:
            n = m["register"]
            r = T.regs[n]
            fl = T.flops[n]
            cov = []
            for s in sorted(structs, key=lambda s: (-CN.iou(s["flops"], fl), -len(s["flops"] & fl), s["pos"])):
                inter = s["flops"] & fl
                if not inter:
                    continue
                cov.append({"structure": s["id"], "kind": s["kind"], "n_flops": len(s["flops"]),
                            "truth_bits": rng(T.idx[n][f] for f in inter if f in T.idx[n]),
                            "iou": round(CN.iou(s["flops"], fl), 4), **verdict(s)})
            scored = [c for c in cov if c["kind"] in S.STRUCTURE_KINDS]
            key = (design, n)
            assert key in MISS, f"no cause for miss {key}"
            a = MISS[key]
            t = CN.tier_of(r)
            cases.append({
                "case": "miss", "design": design, "kind": m["kind"], "truth_register": n,
                "truth_width": r["width"], "n_flops": len(fl), "tier": t["tier"], "subtier": t["subtier"],
                "module_def": r.get("module_def"), "truth_rule": r.get("rule"),
                "truth_params": {k: v for k, v in (r.get("params") or {}).items() if k not in ("order",)},
                "alt_kinds": r.get("alt_kinds") or [],
                "mechanical_category": m["category"],
                "coverage": cov,
                "best_scored_kind_structure": scored[0] if scored else None,
                "harness_verdict_on_the_register": (
                    "no scored-kind structure touches it: the harness never adjudicated these flops"
                    if not scored else
                    ("a scored-kind structure over it was harness-VERIFIED" if any(c["verified"] for c in scored)
                     else "every scored-kind structure over it was REFUSED by the harness")),
                "any_scored_structure_over_it_verified": any(c["verified"] for c in scored),
                "counter_relations": relations_of({c["structure"] for c in cov}),
                "cause": a["cause"], "cause_name": taxonomy_entry(a["cause"], "misses")["name"],
                "mechanism": a["mechanism"], "truth_looks_wrong": a["truth_looks_wrong"],
                "truth_disagreement": a["disagreement"],
            })
        missed_here = {m["register"] for m in ms}
        for f in fps:
            s = by_id[f["structure"]]
            ov = collections.Counter(nm for x in s["flops"] for nm in T.flop_regs.get(x, []))
            key = (design, f["structure"])
            assert key in FP, f"no cause for false positive {key}"
            a = FP[key]
            p = raw[f["structure"]].get("params") or {}
            cases.append({
                "case": "false_positive", "design": design, "kind": f["kind"], "structure": f["structure"],
                "n_flops": f["flops"], "dropped_flops": s["dropped"],
                "params": {k: v for k, v in p.items() if k not in ("bit_order", "order", "inverted", "serial_in")},
                **verdict(s),
                "mechanical_category": f["category"],
                "matched_item": f.get("matched_item"), "matched_item_kind": f.get("matched_item_kind"),
                "matched_iou": f.get("iou"),
                "truth_overlaps": [{"register": nm, "truth_kind": T.kind[nm], "truth_flops": len(T.flops[nm]),
                                    "shared_flops": c, "truth_bits": rng(T.idx[nm][x] for x in s["flops"] & T.flops[nm]
                                                                         if x in T.idx[nm]),
                                    "iou": round(CN.iou(s["flops"], T.flops[nm]), 4),
                                    "tier": CN.tier_of(T.regs[nm])["tier"]}
                                   for nm, c in ov.most_common(4)],
                "distinct_truth_registers_overlapped": len(ov),
                "overlaps_a_missed_register": sorted(nm for nm in ov if nm in missed_here),
                "counter_relations": relations_of({f["structure"]}),
                "cause": a["cause"], "cause_name": taxonomy_entry(a["cause"], "false_positives")["name"],
                "mechanism": a["mechanism"], "truth_looks_wrong": a["truth_looks_wrong"],
                "truth_disagreement": a["disagreement"],
            })
        for u in fu:
            code = "V1" if u["cause"].startswith("V1") else ("V2" if u["cause"].startswith("V2") else "other")
            cases.append({"case": "found_unverified", "design": design, "kind": u["kind"],
                          "truth_register": u["register"], "n_flops": u["flops"], "structure": u["structure"],
                          "iou": u["iou"], "exact": u["exact"], "bucket": u["bucket"],
                          "verify_reason": u["verify_reason"], "tier": u["tier"], "cause": code,
                          "cause_name": B1_TAX["found_unverified"][code]["name"] if code in ("V1", "V2") else code})

    # ---- the mechanical lists must equal numbers.json's (same code, same records)
    C = numbers["C_secondary"]
    assert json.dumps(mech_miss, sort_keys=True) == json.dumps(C["misses_mechanical"]["registers"]["R"],
                                                               sort_keys=True), "misses differ from numbers.json"
    assert json.dumps(mech_fp, sort_keys=True) == json.dumps(C["false_positives_mechanical"]["structures"]["R"],
                                                             sort_keys=True), "false positives differ"
    assert json.dumps(mech_fu, sort_keys=True) == json.dumps(C["found_but_unverified"]["registers"]["R"],
                                                             sort_keys=True), "found-unverified differ"
    unused_m = set(MISS) - {(c["design"], c["truth_register"]) for c in cases if c["case"] == "miss"}
    unused_f = set(FP) - {(c["design"], c["structure"]) for c in cases if c["case"] == "false_positive"}
    assert not unused_m and not unused_f, (unused_m, unused_f)

    miss_cases = [c for c in cases if c["case"] == "miss"]
    fp_cases = [c for c in cases if c["case"] == "false_positive"]
    fu_cases = [c for c in cases if c["case"] == "found_unverified"]
    tot = {"misses": len(miss_cases), "false_positives": len(fp_cases),
           "false_positives_verified": sum(c["verified"] for c in fp_cases), "found_unverified": len(fu_cases)}
    ns = C["misses_mechanical"]["summary"]["R"], C["false_positives_mechanical"]["summary"]["R"]
    assert tot["misses"] == ns[0]["total"] and tot["false_positives"] == ns[1]["total"]
    assert tot["false_positives_verified"] == ns[1]["verified"]
    assert tot["found_unverified"] == C["found_but_unverified"]["summary"]["R"]["registers"]

    order_m = ["M1", "M2a", "M2b", "M3", "M3b", "M4a", "M4b", "M5", "M6", "M6b", "M7", "M8"]
    order_f = ["F1", "F2", "F3", "F3b", "F4", "F5", "F6", "F7", "F8"]

    def group(cs, codes, fp=False):
        out = {}
        for code in codes:
            g = [c for c in cs if c["cause"] == code]
            e = {"n": len(g), "by_kind": dict(collections.Counter(c["kind"] for c in g)),
                 "by_design": dict(collections.Counter(c["design"] for c in g))}
            if fp:
                e["harness_verified"] = sum(c["verified"] for c in g)
                e["on_a_missed_register"] = sum(1 for c in g if c["overlaps_a_missed_register"])
                e["only_on_found_or_non_scored_registers"] = sum(1 for c in g if not c["overlaps_a_missed_register"])
                e["refused_by_bucket"] = dict(collections.Counter(c["bucket"] for c in g if not c["verified"]))
            else:
                e["with_a_verified_scored_structure_over_it"] = sum(c["any_scored_structure_over_it_verified"]
                                                                    for c in g)
                e["tiers"] = dict(collections.Counter(c["tier"] for c in g))
                e["iou_equal_to_0_5_exactly"] = sum(1 for c in g if c["best_scored_kind_structure"]
                                                    and c["best_scored_kind_structure"]["iou"] == 0.5)
            out[code] = e
        return out

    R_m, R_f = group(miss_cases, order_m), group(fp_cases, order_f, fp=True)
    R_v = {k: {"n": v, "by_design": dict(collections.Counter(c["design"] for c in fu_cases if c["cause"] == k)),
               "by_kind": dict(collections.Counter(c["kind"] for c in fu_cases if c["cause"] == k))}
           for k, v in collections.Counter(c["cause"] for c in fu_cases).items()}

    # ---- B1, read-only from freeze 1's analysis
    b1c = [c for c in b1["cases"] if c["design_class"] == "blind"]
    B1_m = {code: {"n": len([c for c in b1c if c["cause"] == code]),
                   "by_design": dict(collections.Counter(c["design"] for c in b1c if c["cause"] == code))}
            for code in order_m}
    B1_f = {code: {"n": len([c for c in b1c if c["cause"] == code]),
                   "harness_verified": sum(1 for c in b1c if c["cause"] == code and c.get("verified")),
                   "by_design": dict(collections.Counter(c["design"] for c in b1c if c["cause"] == code))}
            for code in order_f}
    B1_v = {code: {"n": len([c for c in b1c if c["cause"] == code])} for code in ("V1", "V2")}
    assert sum(v["n"] for v in B1_m.values()) == b1["totals"]["blind"]["misses"] == 35
    assert sum(v["n"] for v in B1_f.values()) == b1["totals"]["blind"]["structures_without_credit"] == 33

    def status(b, r):
        return "recurs" if b and r else ("B1 only" if b else ("new in R" if r else "absent in both"))

    table_m = [{"code": k, "B1": B1_m[k]["n"], "R": R_m[k]["n"], "status": status(B1_m[k]["n"], R_m[k]["n"]),
                "B1_designs": len(B1_m[k]["by_design"]), "R_designs": len(R_m[k]["by_design"])} for k in order_m]
    table_f = [{"code": k, "B1": B1_f[k]["n"], "B1_verified": B1_f[k]["harness_verified"], "R": R_f[k]["n"],
                "R_verified": R_f[k]["harness_verified"], "status": status(B1_f[k]["n"], R_f[k]["n"]),
                "B1_designs": len(B1_f[k]["by_design"]), "R_designs": len(R_f[k]["by_design"])} for k in order_f]
    table_v = [{"code": k, "B1": B1_v[k]["n"], "R": R_v.get(k, {}).get("n", 0)} for k in ("V1", "V2")]

    per_design = {}
    for c in miss_cases + fp_cases:
        d = per_design.setdefault(c["design"], {"misses": collections.Counter(), "false_positives": collections.Counter()})
        d["misses" if c["case"] == "miss" else "false_positives"][c["cause"]] += 1
    per_design = {d: {k: dict(v) for k, v in x.items()} for d, x in per_design.items()}
    for d, _ in CN.R_RECORDS:
        per_design.setdefault(d, {"misses": {}, "false_positives": {}})

    NB = numbers
    quoted = {
        "primary_R": NB["B_primary"]["R"], "primary_B1": NB["B_primary"]["B1"],
        "primary_R_minus_B1": NB["B_primary"]["R_minus_B1"], "primary_verdict": NB["B_primary"]["verdict"],
        "R_shift_register_found_strict": C["per_kind"]["R"]["shift_register"]["all/strict"]["found"],
        "R_shift_register_found_lenient": C["per_kind"]["R"]["shift_register"]["all/lenient"]["found"],
        "R_shift_register_verified_found_strict": C["per_kind"]["R"]["shift_register"]["verified/strict"]["found"],
        "R_shift_register_verified_found_lenient": C["per_kind"]["R"]["shift_register"]["verified/lenient"]["found"],
        "source": "out/s3/replication/analysis/numbers.json (B_primary, C_secondary.per_kind.R.shift_register); "
                  "copied, not recomputed",
    }

    fc_after = CN.freeze_check()
    doc = {
        "schema": "retrace-s3-replication-causes/1",
        "lens": "every miss and every false positive of the S3 replication set R (Freeze 4), with its cause, set "
                "beside freeze 1's blind set B1",
        "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": "out/s3/replication/analysis/causes.py",
        "script_sha256": sha(os.path.abspath(__file__)),
        "inputs": {
            "numbers_json": {"path": CN.rel(NUMBERS), "sha256": sha(NUMBERS)},
            "b1_misses_json": {"path": CN.rel(B1_MISSES), "sha256": sha(B1_MISSES), "read_only": True},
            "plan": {"path": CN.rel(PLAN), "sha256": sha(PLAN)},
            "rtl": "the labeller's cached RTL of the ten R designs (out/s3/blind/cache/rtl/<design>.tar.gz), "
                   "extracted to a scratch directory and read by hand for the mechanism text; no other "
                   "candidate's files were opened",
        },
        "freeze_check": {"before": fc_before, "after": fc_after},
        "method": {
            "mechanical": "compute_numbers.py's own functions (frozen score.py Truth/_structures/_register_level, "
                          "read-only) on each R record's permutation p1; strict, all-structures pass. The miss, "
                          "false-positive and found-but-unverified lists are asserted equal to numbers.json's.",
            "attribution": "each case's cause is written by hand from the record (structures, harness verdicts, "
                           "the recognizer's own relation records and stage statistics), the truth (rule, params, "
                           "bit mapping and its proof/simulation status) and the design's RTL. Relation records "
                           "carry structure ids and shapes; rejection histograms are design-level and are never "
                           "used as per-register attributions.",
            "taxonomy": "docs/S3.md sections 8-9 (B1's codes, copied from out/s3/blind/analysis/misses.json). A "
                        "new code is added only where no B1 code fits; each new code names its nearest B1 code and "
                        "why that code does not fit.",
            "rates": "none computed here; the few quoted are copied from numbers.json (see rates_quoted)",
            "harness_verified_for_a_miss": "whether any scored-kind structure overlapping the missed register was "
                                           "harness-VERIFIED (the register itself earned nothing either way)",
        },
        "taxonomy": {
            "misses": {k: taxonomy_entry(k, "misses") for k in order_m},
            "false_positives": {k: taxonomy_entry(k, "false_positives") for k in order_f},
            "found_unverified": {k: {"name": B1_TAX["found_unverified"][k]["name"],
                                     "mechanism": B1_TAX["found_unverified"][k]["mechanism"]} for k in ("V1", "V2")},
        },
        "totals": {"R": tot, "B1": {"misses": 35, "false_positives": 33, "false_positives_verified": 13,
                                    "found_unverified": 18},
                   "cross_check": "R totals equal numbers.json C_secondary (misses 27, false positives 34 of which "
                                  "18 verified, found-but-unverified 13); B1 totals equal misses.json"},
        "R_by_cause": {"misses": R_m, "false_positives": R_f, "found_unverified": R_v},
        "R_per_design": per_design,
        "comparison_with_B1": {
            "misses": table_m, "false_positives": table_f, "found_unverified": table_v,
            "recur": [r["code"] for r in table_m + table_f if r["status"] == "recurs"] + ["V1", "V2"],
            "B1_only": [r["code"] for r in table_m + table_f if r["status"] == "B1 only"],
            "new_in_R": [r["code"] for r in table_m + table_f if r["status"] == "new in R"],
            "shifts": {
                "accumulator_side_false_positives_F1_plus_F2": {"B1": B1_f["F1"]["n"] + B1_f["F2"]["n"],
                                                                "R": R_f["F1"]["n"] + R_f["F2"]["n"]},
                "counter_subword_false_positives_F3_plus_F3b": {"B1": B1_f["F3"]["n"] + B1_f["F3b"]["n"],
                                                                "R": R_f["F3"]["n"] + R_f["F3b"]["n"]},
                "F3_on_a_missed_register": {"B1": B1_f["F3"]["n"], "R": R_f["F3"]["on_a_missed_register"],
                                            "note": "all 6 of B1's F3 mirror an M1 (docs/S3.md 9.1)"},
                "shift_register_false_positives": {"B1": 0, "R": R_f["F5"]["n"] + R_f["F6"]["n"] + R_f["F8"]["n"]},
                "one_stage_synchronizer_M6": {"B1": B1_m["M6"]["n"], "R": R_m["M6"]["n"]},
                "found_unverified_V1": {"B1": B1_v["V1"]["n"], "R": R_v.get("V1", {}).get("n", 0)},
                "found_unverified_V2": {"B1": B1_v["V2"]["n"], "R": R_v.get("V2", {}).get("n", 0)},
                "misses_with_IoU_exactly_0_5_among_M1": {"B1": 2, "R": R_m["M1"]["iou_equal_to_0_5_exactly"],
                                                         "B1_source": "docs/S3.md 8.1 (DIV_FREQ.counter, note_counter)"},
            },
        },
        "label_disagreements": DISAGREEMENTS,
        "disagreement_policy": "docs/S3_DESIGN.md section 4.4 and docs/S3_REPLICATION_PLAN.md: label disagreements "
                               "are listed, never applied. No truth file was modified and no count here assumes one "
                               "resolved.",
        "rates_quoted": quoted,
        "designs": designs_block,
        "cases": cases,
    }
    doc["headline"] = headline(doc)
    doc["caveats"] = CAVEATS
    with open(os.path.join(HERE, "causes.json"), "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=False)
        fh.write("\n")
    with open(os.path.join(HERE, "causes.md"), "w") as fh:
        fh.write(render(doc))
    print(fc_before["stdout"], "/", fc_after["stdout"])
    print("misses", tot["misses"], "false positives", tot["false_positives"], "found-unverified", tot["found_unverified"])


CAVEATS = [
    "Support. R's misses are 27 registers and its false positives 34 structures over 10 designs, and they are "
    "clustered: tt06__tt_um_SJ alone carries 10 misses and 11 false positives, 14 of them (M7 x7, F7 x7) seven "
    "instances of ONE PE module, which is one mechanism met seven times, not seven findings.",
    "Every count is the strict register level on permutation p1; all 10 R designs gave one distinct answer across "
    "their K = 5 permutations (numbers.json E_mechanics), so the causes are permutation-invariant.",
    "Strict and lenient differ on R for exactly the two M3b registers (numbers.json notes); every cause here is "
    "the strict one.",
    "No R miss or false positive is caused by a dropped, unmapped or shadow flop: only ttsky26b__tt_um_tiny_8bit_cpu "
    "has unmapped flops (72, 'no RTL name on the Q net'), all of them in structures of unscored kinds.",
    "Mechanisms that name RTL come from reading the labeller's cached RTL of these ten designs; mechanisms that name "
    "a recognizer rule come from the record's structures, harness verdicts, relation records and stage statistics. "
    "The recognizer was not re-run and nothing under tools/ was changed.",
    "Several truth registers involved are Tier A (a mapped bit z3-refuted or mismatching simulation): "
    "SJ's calculating_RS flags, spads, psum_spad and PEStartEN; space invaders' score and shooter_x; parakeet's "
    "road_z. A Tier A label is not established; the case lists carry each register's tier.",
    "Some events are charged twice by construction and are not netted out: the partial words of the 4 M1 registers "
    "are 7 false positives (6 F3, 1 F3b), each M7 is also an F7, the M3b pair is one F8, the M4a register one F4, "
    "kitt's M8 one F5 and nickjhay's M6 sits inside one F6. 27 + 34 is not 61 independent errors.",
]


def headline(doc):
    Rm, Rf = doc["R_by_cause"]["misses"], doc["R_by_cause"]["false_positives"]
    t = doc["totals"]["R"]
    old_m = sum(Rm[k]["n"] for k in ("M1", "M2a", "M2b", "M3", "M4a", "M4b", "M5", "M6"))
    old_f = sum(Rf[k]["n"] for k in ("F1", "F2", "F3", "F4"))
    return [
        f"R has {t['misses']} misses and {t['false_positives']} false positives ({t['false_positives_verified']} "
        f"harness-VERIFIED). B1's codes cover {old_m} of the {t['misses']} misses "
        f"(M1 {Rm['M1']['n']}, M2a {Rm['M2a']['n']}, M2b {Rm['M2b']['n']}, M4a {Rm['M4a']['n']}, M6 {Rm['M6']['n']}) "
        f"and {old_f} of the {t['false_positives']} false positives (F1 {Rf['F1']['n']}, F2 {Rf['F2']['n']}, "
        f"F3 {Rf['F3']['n']}, F4 {Rf['F4']['n']}); the rest needed new codes: misses M3b {Rm['M3b']['n']}, M6b {Rm['M6b']['n']}, "
        f"M7 {Rm['M7']['n']}, M8 {Rm['M8']['n']}; false positives F3b {Rf['F3b']['n']}, F5 {Rf['F5']['n']}, "
        f"F6 {Rf['F6']['n']}, F7 {Rf['F7']['n']}, F8 {Rf['F8']['n']}.",
        "The biggest new code is one design: M7 and F7 (7 + 7) are seven instances of SJ's PE, where the recognizer "
        "paired counter bit 0 with the Tier A calculating_RS flop.",
        "B1's dominant false-positive cause, a counter over a truth accumulator (F1 + F2: 25 in B1), is 5 in R; the "
        "counter sub-word (F3 + F3b) rises from 6 to 13. Every R counter false positive is still a question of word "
        "extent (F3, F3b, F7) or of constant versus variable step (F1, F2).",
        "R has 8 shift_register false positives where B1 had none: word-wise array shifts the truth labels "
        "data_register (F5, 4), pipelines written one 1-bit register per stage (F6, 3) and a two-register merge "
        "(F8, 1). 3 of the 8 are harness-VERIFIED; the other 5 were refused on the hold obligation. The seven that "
        "are not F8 lie mostly or wholly on registers the truth labels data_register or flag (label disagreements "
        "R-D3, R-D4).",
        "B1's lfsr-side miss causes do not recur: no M4b (lfsr.py admitting nothing) and no M5 (R has no lfsr_crc "
        "truth register); M4a (the author-named LFSR labelled shift_register) recurs once with its F4.",
        "The 1-stage-synchronizer convention conflict (M6, B1 D4) recurs four times and is all of R's synchronizer "
        "misses; its shift_register twin (M6b, depth 2) is new.",
        "Found-but-unverified flips its mix: B1 V1 2 / V2 16, R V1 12 / V2 1 -- in R the recognizer mostly failed to "
        "claim hold at all, and one of the 12 is a shift_register.",
    ]


def render(doc):
    L = []
    W = L.append
    Rm, Rf, Rv = doc["R_by_cause"]["misses"], doc["R_by_cause"]["false_positives"], doc["R_by_cause"]["found_unverified"]
    q = doc["rates_quoted"]
    W("# S3 replication -- every miss and false positive, with its cause\n")
    W(f"Generated {doc['created']} by `out/s3/replication/analysis/causes.py` (sha256 `{doc['script_sha256'][:16]}...`). "
      f"Set **R** = the 10 Freeze-4 designs; **B1** = freeze 1's 10 blind designs (`out/s3/blind/analysis/misses.json`, "
      f"read only). Taxonomy: `docs/S3.md` sections 8-9, with new codes only where none fits.\n")
    W(f"Freeze check before: `{doc['freeze_check']['before']['stdout']}`; after: `{doc['freeze_check']['after']['stdout']}`.\n")
    W("The mechanical lists (which registers were missed, which structures earned nothing) are recomputed with "
      "`compute_numbers.py`'s own scorer glue and asserted equal to `numbers.json`'s. Rates are not computed here; "
      "the few quoted are copied from `numbers.json`:\n")
    W(f"* primary (counter harness-VERIFIED found recall, strict): R {q['primary_R']['num']}/{q['primary_R']['den']} = "
      f"{q['primary_R']['rate_4dp']}, B1 {q['primary_B1']['num']}/{q['primary_B1']['den']} = {q['primary_B1']['rate_4dp']}, "
      f"R - B1 {q['primary_R_minus_B1']['difference_4dp']} {q['primary_R_minus_B1']['bootstrap_95']['interval_4dp']}: "
      f"**{q['primary_verdict']['word']}** (the plan's word).")
    W(f"* R shift_register found: strict {q['R_shift_register_found_strict']['num']}/{q['R_shift_register_found_strict']['den']} = "
      f"{q['R_shift_register_found_strict']['rate_4dp']}, lenient {q['R_shift_register_found_lenient']['num']}/"
      f"{q['R_shift_register_found_lenient']['den']} = {q['R_shift_register_found_lenient']['rate_4dp']} -- the "
      f"difference is exactly the M3b pair.\n")
    W("## Headline\n")
    for h in doc["headline"]:
        W(f"* {h}")
    W("")
    W("## 1. Cause distribution, R beside B1\n")
    W("### Misses (27 in R, 35 in B1)\n")
    W("| Code | What it is | B1 | R | R designs | status |")
    W("|---|---|---|---|---|---|")
    tax = doc["taxonomy"]
    for r in doc["comparison_with_B1"]["misses"]:
        W(f"| **{r['code']}** | {tax['misses'][r['code']]['name']} | {r['B1']} | {r['R']} | {r['R_designs']} | {r['status']} |")
    W("")
    W("### False positives (34 in R, 18 verified; 33 in B1, 13 verified)\n")
    W("| Code | What it is | B1 (verified) | R (verified) | R refused, by harness bucket | R designs | status |")
    W("|---|---|---|---|---|---|---|")
    for r in doc["comparison_with_B1"]["false_positives"]:
        rb = Rf[r["code"]]["refused_by_bucket"]
        W(f"| **{r['code']}** | {tax['false_positives'][r['code']]['name']} | {r['B1']} ({r['B1_verified']}) | "
          f"{r['R']} ({r['R_verified']}) | {', '.join(f'{k} {v}' for k, v in rb.items()) or '-'} | {r['R_designs']} | {r['status']} |")
    W("")
    W(f"F3 in R: {Rf['F3']['on_a_missed_register']} lie on a missed truth counter (the mirror of an M1) and "
      f"{Rf['F3']['only_on_found_or_non_scored_registers']} are extra sub-words of a truth counter that ANOTHER structure "
      f"found (a split word whose larger part matched). All 6 of B1's F3 were the mirror of an M1 (docs/S3.md 9.1).")
    W("")
    W("### Found but unverified (not misses; the harness refused the matching structure)\n")
    W("| Code | B1 | R |")
    W("|---|---|---|")
    for r in doc["comparison_with_B1"]["found_unverified"]:
        W(f"| **{r['code']}** {tax['found_unverified'][r['code']]['name']} | {r['B1']} | {r['R']} |")
    W("")
    W("Every harness refusal in R is the hold obligation -- 27 structures `hold` (not claimed) and 2 `vacuous` "
      "(`HOLD_EMPTY_NEEDS_VERIFIED_COVER` test (a)); there is no refutation, solver `unknown`, budget, clock or "
      "coverage failure (numbers.json: unverified reasons hold 27, vacuous 2).\n")
    W("### Which recur, which are new\n")
    W("* **Recur (both sets):** M1 partial extent, M2a and M2b kind errors, M4a (an author-named LFSR proved "
      "`lfsr_crc` over a truth `shift_register`), M6 (a one-stage synchronizer the contract refuses); F1-F4; V1 and "
      "V2. Two of R's four M1 fail by equality (IoU exactly 0.50), as two of B1's five did; R's `transfer_state` "
      "(97 declared bits, 7 reachable) is B1's wide-integer M1 mechanism again, and its 12-flop `counter4` is again "
      "`EXHAUSTIVE_WIDTH`.")
    W("* **B1 only:** M3 as B1 defined it (merge credited to one register), M4b (lfsr.py admitting nothing: 5 in B1, "
      "on two designs), M5 (B1's 9 register-file `lfsr_crc` labels, one design; R has no `lfsr_crc` truth register "
      "at all).")
    W("* **New in R:** misses M3b, M6b, M7, M8; false positives F3b, F5, F6, F7, F8. M7/F7 is one module met seven "
      "times in one design. M6b is M6's contract floor for `shift_register`. F5 and F6 are the first "
      "`shift_register` false positives in either set, and both sit on label disagreements (R-D3, R-D4).")
    W("* **Shifted weight:** accumulator-side false positives (F1 + F2) 25 -> 5; counter sub-word false positives "
      "(F3 + F3b) 6 -> 13; M6 1 -> 4; V2 16 -> 1 while V1 2 -> 12.\n")
    W("## 2. The new codes, and why no B1 code fits\n")
    for sec in ("misses", "false_positives"):
        for k, v in tax[sec].items():
            if v.get("origin", "").startswith("NEW"):
                W(f"* **{k}** -- {v['name']}. {v['mechanism'][0].upper() + v['mechanism'][1:]}. Nearest B1 code: "
                  f"{v['nearest_B1']}; {v['why_not_B1']}.")
    W("")
    W("## 3. Per design (R)\n")
    W("| Design | misses by cause | false positives by cause |")
    W("|---|---|---|")
    for d, _ in CN.R_RECORDS:
        x = doc["R_per_design"][d]
        W(f"| `{d}` | {', '.join(f'{k} {v}' for k, v in sorted(x['misses'].items())) or '-'} | "
          f"{', '.join(f'{k} {v}' for k, v in sorted(x['false_positives'].items())) or '-'} |")
    W("")
    W("## 4. Every miss\n")
    W("\"Harness\" says what the harness did with the scored-kind structures over the register (the register "
      "itself earned nothing either way).\n")
    for c in [c for c in doc["cases"] if c["case"] == "miss"]:
        sc = [x for x in c["coverage"] if x["kind"] in S.STRUCTURE_KINDS]
        bs = "; ".join(f"`{x['structure']}` ({x['kind']}, {x['n_flops']} flops, IoU {x['iou']:.3f}, "
                       f"{'VERIFIED' if x['verified'] else 'refused: ' + x['bucket']})" for x in sc)
        W(f"### {c['cause']} -- `{c['design']}` `{c['truth_register']}` ({c['kind']}, {c['n_flops']} "
          f"flop{'s' if c['n_flops'] != 1 else ''}, tier {c['tier']})\n")
        W(f"{c['mechanism']}\n")
        W(f"* Harness: {c['harness_verdict_on_the_register']}" + (f" -- {bs}." if bs else "."))
        W(f"* Coverage: " + "; ".join(f"`{x['structure']}` ({x['kind']}) bits {x['truth_bits']} IoU {x['iou']:.3f}"
                                      for x in c["coverage"]))
        W(f"* Truth looks wrong: {c['truth_looks_wrong']}" + (f" ({c['truth_disagreement']})" if c["truth_disagreement"] else "") + "\n")
    W("## 5. Every false positive\n")
    for c in [c for c in doc["cases"] if c["case"] == "false_positive"]:
        ov = "; ".join(f"`{o['register']}` ({o['truth_kind']}, tier {o['tier']}) bits {o['truth_bits']} IoU {o['iou']:.3f}"
                       for o in c["truth_overlaps"][:3])
        W(f"### {c['cause']} -- `{c['design']}` `{c['structure']}` ({c['kind']}, {c['n_flops']} flops, "
          f"{'harness-VERIFIED' if c['verified'] else 'refused: ' + c['bucket']})\n")
        W(f"{c['mechanism']}\n")
        W(f"* Overlaps ({c['distinct_truth_registers_overlapped']} truth registers): {ov}")
        W(f"* Truth looks wrong: {c['truth_looks_wrong']}" + (f" ({c['truth_disagreement']})" if c["truth_disagreement"] else "") + "\n")
    W("## 6. Found but unverified (R)\n")
    W("| Design | Register | kind | structure | IoU | exact | bucket | code |")
    W("|---|---|---|---|---|---|---|---|")
    for c in [c for c in doc["cases"] if c["case"] == "found_unverified"]:
        W(f"| `{c['design']}` | `{c['truth_register']}` | {c['kind']} | `{c['structure']}` | {c['iou']:.2f} | "
          f"{c['exact']} | {c['bucket']} | {c['cause']} |")
    W("")
    W("## 7. Label disagreements -- listed, never applied\n")
    W(doc["disagreement_policy"] + "\n")
    for d in doc["label_disagreements"]:
        W(f"* **{d['id']}**{' (recurs: B1 ' + d['same_as_B1'] + ')' if d.get('same_as_B1') else ' (new)'}"
          f"{' -- weak' if d.get('strength') == 'weak' else ''}: {', '.join(d['truth_registers'])} in "
          f"{', '.join('`' + x + '`' for x in d['designs'])}; truth `{d['truth_kind']}`, recognizer `{d['recognizer_kind']}`. "
          f"RTL: {d['rtl']}. {d['why'][0].upper() + d['why'][1:]} Cost: {d['cost']}." + (f" {d['note']}" if d.get("note") else ""))
    W("")
    W("## 8. Caveats\n")
    for c in doc["caveats"]:
        W(f"* {c}")
    W("")
    return "\n".join(L)


if __name__ == "__main__":
    main()
