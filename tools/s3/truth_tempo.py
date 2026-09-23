"""TEMPO ground truth for structure recognition (PRD S3, docs/S3_DESIGN.md), schema
retrace-s3-truth/2 (tools/s3/schema.py).

Every register in TEMPO's RTL, classified by the word-level logic that feeds it, and
every register bit mapped to its flop in the sign-off netlist (`nl.v`, DEF instance
names) and to the instance name the anonymous GDS extraction gives that flop
(`tools/tempo/lvs.py extract_tempo()`: `<master minus sg13cmos5l_>_<x>_<y>`, DEF
placement in DBU), which is the join key. TEMPO is the development design for S3.

    TEMPO_ROOT=out/s3/tempo_snapshot python -m tools.s3.truth_tempo [out/s3/truth_tempo.json]
        [--run-json PATH] [--work DIR] [--patterns N]
    TEMPO_ROOT=... python -m tools.s3.truth_tempo --draft PATH [--no-prove] [--no-gds]
    (2-5 min, ~3 GB: Yosys ~5 s, simulation ~5 s, z3 proof 90-200 s, GDS extraction 20-40 s,
    parameter checks ~5 s)

A truth is written only when it is complete: every netlist flop, output and invariant proven
by z3, the GDS extraction's instance names agreeing for every flop, every parameter check
passing, the simulation agreeing on every flop, output, clock and async control. Otherwise
the run exits 2 and writes nothing. `--draft PATH` writes whatever was reached (proof or GDS
check skipped with --no-prove / --no-gds, or failed) to PATH, which must lie outside out/s3,
lists the shortfalls in meta.draft and names the design "tempo-draft" (so a scorer refuses it
as TEMPO's truth and its truth_hash differs from a complete truth's). z3 runs under a
deterministic resource limit (`Z3_RLIMIT` per check, z3's rlimit), never a wall-clock timeout,
so the verdicts do not depend on the machine; a refutation counts only with a model that
satisfies the query, and the solver is rebuilt after any check that hits the limit.

The truth file holds no timings, versions, commits or absolute paths, so reruns are
byte-identical (checked with different PYTHONHASHSEED values); those go to the
`.run.json` next to it. S3 runs TEMPO from the frozen snapshot out/s3/tempo_snapshot
(TEMPO_ROOT), whose TEMPO_COMMIT and SHA256SUMS the run file records and checks.

Inputs (read-only): TEMPO's RTL (`$TEMPO_ROOT/src`, file list from user_config.json,
defines from config.json), its sign-off views (`runs/wokwi/final/{nl,def}`), the IHP
sg13cmos5l Liberty (cell functions for simulation) and LEF. Needs Yosys (oss-cad-suite).

Method
  1. Yosys, word level (script in `WORD_SCRIPT`): read_verilog -sv -mem2reg (arrays
     become one register per word, named `name[i]` exactly as the synthesized netlist
     names them), hierarchy, proc -norom (case statements stay muxes), flatten; every
     wire on the Q port of a flop at this point is tagged `rtl_reg` (the reg the RTL
     assigns in a clocked block, whatever later aliases it); opt -nodffe -nosdff,
     fsm_detect (marks FSM state registers the way LibreLane's `fsm` pass would), opt
     (folds enables and sync resets into $sdffe etc.), wreduce, opt_clean ->
     `wl.json`. Then dffunmap; techmap; opt_clean -> `gates.json`, the same RTL as
     single-bit gates, used to check the mapping by simulation.
     A second Yosys run with LibreLane's own coarse sequence (`FSM_SCRIPT`, fsm -nomap
     -encfile) records how synthesis re-encodes FSM state registers (TEMPO: the host's
     `st`, 4-bit binary -> 10-bit one-hot `st[0..9]` in the netlist).
  2. Classification (`classify`): for each register, the D input of every bit is traced
     back through mux trees ($mux/$pmux data inputs) to its leaves (the register's own
     Q bits, other registers, inputs, constants, operator outputs), and operator
     outputs are traced further through adders (counter/accumulator) or XOR/bitwise
     logic (LFSR/CRC, per-bit read-modify-write). Rules, first match wins:
     register_file_word (a word of an array the RTL writes at a non-constant index; see
     the note in Classifier.classify on why this stays first), fsm_state (Yosys
     fsm_detect), synchronizer (stage 1: D is an input pin; stage 2: D is a stage-1 bit;
     no enable), lfsr_crc (own Q bits of *other* indices reach D through XOR), counter
     (D = Q +/- constant, or +/- a 1-bit condition, under enable/load/clear/wrap),
     accumulator (D = Q + a multi-bit variable), shift_register (D[k] = Q[k+s] for a fixed
     s != 0 on >= 75 % of the bits that can shift), then flag (1 bit, or several bits
     written only with constants) or data_register (everything else: loads of external
     values, computed values, delayed copies, masked per-bit updates). A 1-bit register
     whose update is Q <= ~Q (a toggle, possibly under an enable) or an adder on its own Q
     is a flag with alt_kinds [counter] (`TOGGLE_RULE`: a 1-flop "counter" is accepted,
     never required). `MANUAL` then overrides the rule where reading the RTL shows it is
     wrong (meta.manual_overrides).
  3. Mapping (`map_netlist`): a flop's Q net in nl.v usually keeps a name of its
     register bit, but often an alias from a higher level (`u_top.h_wdata[3]` is
     tempo_host's `h_wdata[3]`, `u_top.u_core.instr[31]` is `x_ir[31]`); names are
     resolved through wl.json's aliases to the tagged register bit. Flops without a
     usable name and RTL bits without a flop are resolved by bit-parallel random
     simulation of both models (RTL gates.json; nl.v with Liberty cell functions),
     cut at the flops: a flop whose next-state function equals another flop's is a
     duplicate (synthesis moved a register into a memory read port), one whose
     next-state function equals an RTL combinational signal evaluated one cycle ahead
     is a retimed register (a register pushed through a case ROM), an RTL bit whose
     next-state function equals a netlist flop's was merged with it, one that never
     reaches a flop is unused, one whose next state is constant was removed, one whose
     value changes nothing downstream is unobservable. In half of the patterns every
     register slice the RTL compares with constants takes one of those constants, so
     decodes are exercised (meta.functional_check). Then z3 proves, per flop, that the
     netlist D function equals the RTL next-state function of what the flop implements,
     for all values of the flops, inputs and SRAM data, under that correspondence (and
     the recoded FSM's valid-state invariant); the 24 outputs likewise; and it proves the
     assumed invariants are preserved (a merged RTL bit's next state is its shared flop's
     D, constant bits stay constant, the FSM's next state is a valid code), so the
     correspondence is inductive: once the chip has been reset, netlist and RTL stay in
     corresponding states (meta.proof; the V7 idea, applied to 2,832 flops).
  4. Operators (`operators`): every word-level adder, subtractor, comparator,
     equality, mux, XOR and shift in wl.json, with widths, source line and the
     registers whose next-state logic it feeds (cell-level cone, over-approximate).

Parameters (step 5)
  params follow schema.PARAMS for the four scored kinds and are stated by hand where the
  rule does not give them (`SHIFT_PARAMS`, `CRC_PARAMS`, `COUNTER_PARAMS`, synchronizers
  from the rule's stage analysis). Every stated value is checked by bit-parallel simulation
  of the RTL gate model (gates.json, which step 3 proves equal to the netlist flop by flop)
  before anything is written (`ParamCheck`): copy chains (shift lanes, synchronizer stages)
  must copy in every pattern under their condition and flip when all their sources flip;
  a counter's claimed step, modulus or saturation must describe its whole transition table
  T_x(v) over its value range in at least one context x found by random biased simulation
  (the per-transition labelling of S3_DESIGN section 3.4); a CRC's claimed form, taps and
  steps must reproduce its next state with its module ports driven at random. A value the
  RTL does not pin down (e.g. a stop point held in another register) is null, which leaves
  the denominator. The check results are in each register's provenance.params_check.
  lfsr_crc (schema.py): k_steps = LFSR steps per clock in the main (data) update mode,
  n_inputs = data bits entering per step; other modes go to provenance.other_modes. TEMPO's
  crc_l takes feed_n = 1..8 steps per feed, a runtime operand, so k_steps is null there (the
  range is in details.stated_params) and n_inputs = 1.

Output (retrace-s3-truth/2, see tools/s3/schema.py; extensions marked +)
  registers: [ {name, width (RTL bits), kind (schema.KINDS), alt_kinds, alt_reason,
      module_def (RTL module declaring it), +design_key (module_def:local name, array and
      generate indices as [*]: the same RTL statement instantiated twice has one key),
      params (schema.PARAMS for the kind, {} otherwise; flops as join keys; stage-level
      params null for a register that is one stage of a declared unit),
      bits: [{index, flop (join key or null), rtl_bit, shadow_flops [join keys of synthesis
             duplicates: D(dup) == D(flop) proven; not in the register's matched flop set],
             +nl_instance, +how (name | alias | merged | fsm_onehot | retimed), +state (FSM
             code), +note (why no flop), alt_kinds (per-bit alternatives, only where they differ
             by bit; the register's alt_kinds are then [])}],
      +n_flops (distinct flops of the bits), +provenance {rule, auto_kind, override_reason,
      params_source, params_check, +stage_of, +other_modes}, +details (rule facts: source
      lines, slices, sources, selects, kind-specific notes)} ]
      The flops that hold a retimed function of a register (synthesis moved logic across
      them) form their own register `<owner>__retimed` of kind "other" (bits[].rtl_bit is the
      RTL signal the flop holds one cycle ahead when it has a public name, else the register's
      own bit name; bits[].holds describes it).
  units: [{name, kind, registers, reason, +flops (join keys), +params, +check, +rules}]
      declared lenient alternatives (synchronizer chains written as one RTL register per
      stage, their third copy stage, per-slice splits); never RTL module blocks. Units are also
      declared by rule (`UNIT_RULES`, `rule_units`; the blind-set labeller, tools/s3/thirdparty.py,
      declares units by these rules only): sync_chain (synchronizer stage registers forming
      chains), copy_lanes (equal-depth copy chains of several registers under one copy condition
      with heads of one external kind: per-channel histories, per-lane synchronizers) and
      concat_adder (counters written by one concatenated adder, {hi, lo} <= {hi, lo} + 1). A
      declared unit a rule reproduces lists the rule in +rules; meta.unit_rules has the report. A register
      none of whose flops it is primary for (RTL registers synthesis merged into another's
      flops, e.g. sck_meta = ui_sync0[0]) is a member of every unit that covers its flops and
      whose kind it accepts; the run fails if such a register is in no unit.
  flops: {join key: {registers (every register using the flop), primary (the widest),
      +role (bit | retimed | fsm_onehot), +rtl_bits, +nl_instance}}  (bit flops only: shadow
      flops are listed in bits[].shadow_flops and meta.coverage, not here)
  unmapped_flops: [{flop, reason}]  (none for TEMPO: every flop is a bit or a shadow)
  operators: [ {cell, type, module, src, widths, signed, const_operand, feeds,
                feeds_outputs, xor_group} ]  (unscored)
  meta: sources (sha256), kinds, counts (per instance and per distinct design),
        coverage, fsm_recoding, manual_overrides, alt_kind_rules, functional_check, proof,
        gds_check, param_checks, conventions (and draft, for a --draft file)
"""

import argparse
import collections
import hashlib
import json
import os
import platform
import random
import re
import resource
import subprocess
import sys
import time

from . import schema
from ..retrace.defparse import read_def
from ..tempo import lvs

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPO_ROOT = lvs.TEMPO_ROOT
SRC = os.path.join(TEMPO_ROOT, "src")
FINAL = os.path.join(TEMPO_ROOT, "runs", "wokwi", "final")
LIB = os.path.join(lvs.IHP_PDK, "libs.ref/sg13cmos5l_stdcell/lib/sg13cmos5l_stdcell_typ_1p20V_25C.lib")
YOSYS = os.environ.get("YOSYS", os.path.expanduser("~/ttsetup/oss-cad-suite/bin/yosys"))
TOP = lvs.TOP
PREFIX = lvs.IHP_SG13CMOS5L.prefix
SRAM = lvs.IHP_SG13CMOS5L.macro_prefixes[0]
WORK = os.path.join(ROOT, "out", "s3", "truth_tempo")
OUT_S3 = os.path.join(ROOT, "out", "s3")
# LibreLane adds these to VERILOG_DEFINES (TEMPO's RTL tests none of them)
FLOW_DEFINES = ("__librelane__", "__pnr__")
# z3 resource limit per check (z3's deterministic rlimit, not a timeout). TEMPO's costliest check
# used 3.5 M units on 2026-09-22 (the .run.json's z3_rlimit records the maximum and the total).
Z3_RLIMIT = 200_000_000
# the 1-bit toggle rule (review of 2026-09-22): a width-1 register whose update is Q <= ~Q (or an
# adder on its own Q) is labelled flag, with counter accepted; the blind-set labeller applies it too
TOGGLE_RULE = ("a 1-bit toggle (Q <= ~Q, possibly under an enable) is a flag that a structural "
               "recognizer may also report as a 1-flop counter (mod 2); never a required counter")

FF_TYPES = {"$dff", "$dffe", "$sdff", "$sdffe", "$sdffce", "$adff", "$adffe", "$aldff", "$aldffe",
            "$dffsr", "$dffsre", "$dlatch", "$adlatch", "$dlatchsr"}
ARITH = {"$add", "$sub"}
XORS = {"$xor", "$xnor"}
BITWISE = {"$and", "$or", "$xor", "$xnor", "$not"}
CMP = {"$eq", "$ne", "$lt", "$le", "$gt", "$ge", "$eqx", "$nex"}
OPERATOR_TYPES = (ARITH | {"$mul", "$div", "$mod", "$neg"} | CMP | {"$mux", "$pmux", "$bmux", "$shiftx"}
                  | XORS | {"$reduce_xor", "$reduce_xnor"} | {"$shl", "$shr", "$sshl", "$sshr", "$shift"})
KINDS = schema.KINDS

# ----------------------------------------------------------------------------- manual overrides
# Applied after the automatic rules; each entry was decided by reading the RTL (tempo_*.v).
# pattern (regex on the register name) -> (kind, reason, extra details)
MANUAL = [
    (r"^u_top\.u_sys\.flags_q$", "flag",
     "tempo_sys.v:156-159: eight independent sticky host flags, each set by IRQ (u_imm bit) and "
     "cleared by the host's W1C pulse; the rule sees a masked per-bit read-modify-write and calls it "
     "data_register, but every bit is a flag", {}),
    (r"^u_top\.u_sys\.sig_q$", "flag",
     "tempo_sys.v:169-177: eight inter-thread signal flags, set by SIGSET and cleared by SIGCLR/WAITSIGC "
     "(masked per-bit set/clear); the rule calls it data_register", {}),
    (r"^u_top\.u_host\.rd_underrun$", "flag",
     "tempo_host.v:423/530: sticky READ_MEM underrun diagnostic; its output is unconnected in tempo_top, "
     "so Yosys removes it before classification and no flop exists", {"width": 1}),
]
# kinds a structural recognizer may also fairly report (regex -> [kinds], reason, per-bit rule).
# The per-bit rule (a function of the bit index, or None) gives the bits the alternative
# applies to when it holds only for part of the register; those bits carry "alt_kinds".
ALT_KINDS = [
    (r"^u_top\.u_tio\.thr\[\d\]\.toq_(t|val|mask)_q\[\d\]$", ["shift_register"],
     "tempo_tio.v:264-279: a 2-deep timed-output queue; on toq_fire word 0 loads word 1 (a word-wide "
     "shift), and a push writes the word at the tail index", None),
    (r"^u_top\.u_host\.dreg$", ["data_register"],
     "tempo_host.v:165: shifts in a byte at a time ({rx_byte, dreg[31:8]}) but is also the parallel-load "
     "holding register for every 4-byte field", None),
    (r"^u_top\.u_core\.pc_r\[\d\]$", ["data_register"],
     "tempo_core.v:573: the PC takes pc+1, a branch/jump target or a host write", None),
    (r"^u_top\.u_host\.sck_p$", ["synchronizer"],
     "tempo_host.v:101,287: third copy stage of the SCK chain sck_meta -> sck_s -> sck_p (no enable, "
     "input-fed), kept for edge detection; its flop is also pins_prev[16]'s (ui_in[0] third stage)", None),
    (r"^u_top\.u_tio\.pins_prev$", ["synchronizer"],
     "tempo_tio.v:132-139: pins_prev <= {ui_sync1, pout_r[15:8], uio_sync1} with no enable, so bits "
     "[23:16] and [7:0] are a third copy stage of the ui_in / uio_in synchronizers; bits [15:10] copy "
     "the POUT register (not input-fed) and bits [9:8] have no flop. Per-bit alt_kinds say which bits",
     lambda i: i >= 16 or i <= 7),
]

# ----------------------------------------------------------------------------- stated parameters
# Hand-stated parameters, each checked by simulation (ParamCheck) before the file is written.
# Register bits are RTL keys (name, index); join keys are filled in from the proven mapping.
# direction for shift registers: "to_msb" = data moves toward higher RTL index (serial input at
# the lowest index), "to_lsb" = toward lower index. Lanes are listed in lane order, each lane
# stage 0 first (the stage that loads the serial input).

HOST = "u_top.u_host"
SHIFT_PARAMS = {
    f"{HOST}.dreg": dict(
        lanes=[[("reg", f"{HOST}.mosi_s", 0) if j == 0 else ("reg", f"{HOST}.rx_shift", j - 1)]
               + [(f"{HOST}.dreg", 24 + j - 8 * s) for s in range(4)] for j in range(8)],
        direction="to_lsb",
        force={f"{HOST}.st": [1, 2, 5], f"{HOST}.bit_cnt": 7, f"{HOST}.sck_s": 1, f"{HOST}.sck_p": 0,
               f"{HOST}.cs_s": 0},
        condition="byte_done (sck_rise & bit_cnt == 7) & ~cs_s in ST_ADDR0, ST_ADDR1 or ST_WDATA",
        note="tempo_host.v:123,165,405-444: dreg <= dreg_shift_in = {rx_byte, dreg[31:8]} with rx_byte = "
             "{rx_shift, mosi_s}: 8 lanes of depth 4, lane j = dreg[24+j] -> [16+j] -> [8+j] -> [j], serial "
             "input rx_byte[j] (mosi_s for lane 0, rx_shift[j-1] otherwise); parallel loads elsewhere"),
    f"{HOST}.rx_shift": dict(
        lanes=[[("reg", f"{HOST}.mosi_s", 0)] + [(f"{HOST}.rx_shift", k) for k in range(7)]],
        direction="to_msb",
        force={f"{HOST}.sck_s": 1, f"{HOST}.sck_p": 0, f"{HOST}.cs_s": 0},
        condition="sck_rise (sck_s & ~sck_p) & ~cs_s",
        note="tempo_host.v:303-308: rx_shift <= {rx_shift[5:0], mosi_s} on each SCK rising edge while "
             "selected: one lane of depth 7, serial input mosi_s"),
}

CRC_PARAMS = {
    f"u_top.u_crc.u_crc{t}.crc_l": dict(
        inst=f"u_top.u_crc.u_crc{t}", form="galois", poly="programmable", k_steps=None, k_steps_range=(1, 8),
        n_inputs=1,
        note="tempo_crc.v:37-86: Galois form shifting toward the MSB, one step c' = {c[30:0], 0} ^ "
             "(c[31] ^ b ? poly_l : 0); feed_n = 1..8 steps per cycle (tempo_crc_block clamps CRCFEED's "
             "imm to 1..8), data bit b of step s = feed_bits[s]; polynomial and width programmable "
             "(poly_l, width_m1; left-aligned so logical bit width-1 is crc_l[31]); init loads "
             "wdata << (31 - width_m1); holds otherwise. Main (data) mode = feed: n_inputs = 1 data bit "
             "per step; k_steps = feed_n, an operand of each CRCFEED (1..8), not a constant of the RTL, "
             "so null (schema.py lfsr_crc convention; truth/2 before 2026-09-22 said k_steps 8, "
             "n_inputs 8 per cycle)",
        other_modes=[{"mode": "init", "when": "init_we", "next": "crc_l <= wdata << (31 - width_m1)",
                      "k_steps": 0, "n_inputs": 0},
                     {"mode": "hold", "when": "otherwise", "k_steps": 0, "n_inputs": 0}]) for t in (0, 1)}

# Counters: (regex, claim, note). A claim states direction, step and either modulus M (every
# count transition is v -> (v +/- step) mod M on 0..M-1) or saturating with bounds (lo, hi), or
# neither (step only, checked on `domain`); null values are unknown to the RTL and leave the
# denominator. `force` pins registers while contexts are searched (a stop point held in another
# register is set to its maximum); `cut` names 1-bit module ports driven at random instead of
# through the logic that feeds them (the FIFO's push/pop, which the core raises rarely).
# `load`: a case loading a data value (register, input or relative offset), read from the
# word-level mux tree, not simulated.
COUNTER_PARAMS = [
    (r"^u_top\.u_arb\.steal_cnt$", dict(direction="up", step=1, modulus=17, saturating=False, load=False),
     "tempo_arb.v:51-60: counts consecutive ungranted host requests; at STEAL = 16 the grant clears it, "
     "so a counting context walks 0..16 -> 0 (mod 17); 17..31 are unreachable and clear too"),
    (r"^u_top\.u_core\.pc_r\[\d\]$", dict(direction="up", step=1, modulus=1024, saturating=False, load=True),
     "tempo_core.v:287-289,573: pc + 1 in 10 bits (natural wrap), relative branch pc + 1 + off, "
     "opaque jump / host write / thread reset loads"),
    (r"^u_top\.u_host\.addr_word$", dict(direction="up", step=1, modulus=1024, saturating=False, load=True),
     "tempo_host.v:145,417-537: word address, +1 per transferred word (10 bits, natural wrap), loaded "
     "from dreg_shift_in[27:18]"),
    (r"^u_top\.u_host\.bit_cnt$", dict(direction="up", step=1, modulus=8, saturating=False, load=False),
     "tempo_host.v:121,303-308: +1 per SCK rising edge (3 bits, natural wrap), cleared while ~CS"),
    (r"^u_top\.u_host\.bw$", dict(direction="up", step=1, modulus=4, saturating=False, load=False),
     "tempo_host.v:147,452-560: byte-in-word position, bw != 3 ? bw + 1 : 0 (mod 4); constant loads 0/1"),
    (r"^u_top\.u_host\.pop_rem$", dict(direction="down", step=1, modulus=8, saturating=False, load=True),
     "tempo_host.v:148,569: words left to pop, -1 per popped word (3 bits, natural wrap in the logic), "
     "loaded with the c2h FIFO level"),
    (r"^u_top\.u_ser\.u_ser\d\.rx_pos_q$", dict(direction="up", step=1, modulus=None, saturating=False, load=False,
                                                 force={"rx_nbits_q": 31}, domain=(0, 30)),
     "tempo_ser.v:85,449-476: bit position, +1 per received bit, back to 0 at rx_nbits_q (a modulus held "
     "in a register: null); checked with rx_nbits_q = 31"),
    (r"^u_top\.u_ser\.u_ser\d\.tx_pos_q$", dict(direction="up", step=1, modulus=None, saturating=None, load=False,
                                                 force={"tx_nbits_q": 31}, domain=(0, 30)),
     "tempo_ser.v:78,427-438: emission position, +1 per bit; stops at tx_nbits_q in timeline mode and "
     "runs on (mod 32) in clocked-like mode, so neither modulus nor saturation is a constant (null); "
     "loads the constants 0/1; checked with tx_nbits_q = 31"),
    (r"^u_top\.u_ser\.u_ser\d\.tx_samp_q$", dict(direction="up", step=1, modulus=None, saturating=None,
                                                  load=False, force={"tx_nbits_q": 31}, domain=(0, 30)),
     "tempo_ser.v:219,400-402: sample index, +1 per sample until it equals tx_nbits_q (a stop held in a "
     "register: null); checked with tx_nbits_q = 31"),
    (r"^u_top\.u_sys\.u_(c2h|h2c)_fifo\.(head_r|tail_r)$",
     dict(direction="up", step=1, modulus=4, saturating=False, load=False),
     "tempo_fifo.v:66-71: ptr == DEPTH-1 ? 0 : ptr + 1 with DEPTH = 4 (mod 4)"),
    (r"^u_top\.u_sys\.u_(c2h|h2c)_fifo\.level_r$",
     dict(direction="updown", step=1, modulus=None, saturating=True, bounds=(0, 4), load=False,
          cut=("push", "pop")),
     "tempo_fifo.v:58-78: +1 on an accepted push, -1 on an accepted pop; a push is refused when full "
     "(level == 4) and a pop when empty, so it saturates at 0 and 4 (5..7 unreachable)"),
    (r"^u_top\.u_tio\.thr\[\d\]\.toq_cnt_q$",
     dict(direction="updown", step=1, modulus=None, saturating=True, bounds=(0, 2), load=False),
     "tempo_tio.v:227-280: +1 on an accepted push, -1 on a fire; a push is refused when full (== 2) and "
     "fire needs a non-zero count, so it saturates at 0 and 2 (3 unreachable)"),
    (r"^u_top\.u_tio\.time_q$", dict(direction="up", step=1, modulus=1 << 32, saturating=False, load=False),
     "tempo_tio.v:100-107: free-running +1 per clock (32 bits, natural wrap), cleared by time_rst"),
]

# Declared lenient alternative units: (name, kind, [(register, bit filter or None)], reason, lanes).
# lanes (synchronizer chains): per lane [source, stage 0, stage 1, ...] as in SHIFT_PARAMS.
TIO, SYNC_UI = "u_top.u_tio", lambda i: i >= 16
UNITS = [
    ("ui_in synchronizer, 2 stages", "synchronizer", [(f"{TIO}.ui_sync0", None), (f"{TIO}.ui_sync1", None)],
     "tempo_tio.v:113-127: one 8-lane two-flop synchronizer written as one RTL register per stage",
     [[("pi", "ui_in", j), (f"{TIO}.ui_sync0", j), (f"{TIO}.ui_sync1", j)] for j in range(8)]),
    ("uio_in synchronizer, 2 stages", "synchronizer", [(f"{TIO}.uio_sync0", None), (f"{TIO}.uio_sync1", None)],
     "tempo_tio.v:113-127: one 8-lane two-flop synchronizer written as one RTL register per stage",
     [[("pi", "uio_in", j), (f"{TIO}.uio_sync0", j), (f"{TIO}.uio_sync1", j)] for j in range(8)]),
    ("ui_in + uio_in synchronizers, 2 stages", "synchronizer",
     [(f"{TIO}.ui_sync0", None), (f"{TIO}.ui_sync1", None), (f"{TIO}.uio_sync0", None), (f"{TIO}.uio_sync1", None)],
     "tempo_tio.v:116-127: both pads' synchronizers sit in one always block with the same controls (no "
     "enable, reset rst); a control-signature grouping cannot separate them",
     [[("pi", f"{p}_in", j), (f"{TIO}.{p}_sync0", j), (f"{TIO}.{p}_sync1", j)] for p in ("ui", "uio")
      for j in range(8)]),
    ("ui_in synchronizer + pins_prev[23:16], 3 stages", "synchronizer",
     [(f"{TIO}.ui_sync0", None), (f"{TIO}.ui_sync1", None), (f"{TIO}.pins_prev", SYNC_UI)],
     "tempo_tio.v:132-139: pins_prev[23:16] <= ui_sync1 unconditionally, a third copy stage",
     [[("pi", "ui_in", j), (f"{TIO}.ui_sync0", j), (f"{TIO}.ui_sync1", j), (f"{TIO}.pins_prev", 16 + j)]
      for j in range(8)]),
    ("uio_in synchronizer + pins_prev[7:0], 3 stages", "synchronizer",
     [(f"{TIO}.uio_sync0", None), (f"{TIO}.uio_sync1", None), (f"{TIO}.pins_prev", lambda i: i <= 7)],
     "tempo_tio.v:132-139: pins_prev[7:0] <= uio_sync1 unconditionally, a third copy stage",
     [[("pi", "uio_in", j), (f"{TIO}.uio_sync0", j), (f"{TIO}.uio_sync1", j), (f"{TIO}.pins_prev", j)]
      for j in range(8)]),
    ("ui_in + uio_in synchronizers + pins_prev, 3 stages", "synchronizer",
     [(f"{TIO}.ui_sync0", None), (f"{TIO}.ui_sync1", None), (f"{TIO}.uio_sync0", None), (f"{TIO}.uio_sync1", None),
      (f"{TIO}.pins_prev", lambda i: i >= 16 or i <= 7)],
     "the two 3-stage chains above share one control class (no enable, reset rst)",
     [[("pi", "ui_in", j), (f"{TIO}.ui_sync0", j), (f"{TIO}.ui_sync1", j), (f"{TIO}.pins_prev", 16 + j)]
      for j in range(8)]
     + [[("pi", "uio_in", j), (f"{TIO}.uio_sync0", j), (f"{TIO}.uio_sync1", j), (f"{TIO}.pins_prev", j)]
        for j in range(8)]),
    ("CS synchronizer", "synchronizer", [(f"{HOST}.cs_meta", None), (f"{HOST}.cs_s", None)],
     "tempo_host.v:102,288: a two-flop synchronizer written as two 1-bit RTL registers (reset to 1, so "
     "separate flops from ui_sync0/1[1])",
     [[("pi", "ui_in", 1), (f"{HOST}.cs_meta", 0), (f"{HOST}.cs_s", 0)]]),
    ("SCK synchronizer", "synchronizer", [(f"{HOST}.sck_meta", None), (f"{HOST}.sck_s", None)],
     "tempo_host.v:101,287: a two-flop synchronizer written as two 1-bit RTL registers (its flops are "
     "ui_sync0[0] and ui_sync1[0])",
     [[("pi", "ui_in", 0), (f"{HOST}.sck_meta", 0), (f"{HOST}.sck_s", 0)]]),
    ("SCK synchronizer + sck_p, 3 stages", "synchronizer",
     [(f"{HOST}.sck_meta", None), (f"{HOST}.sck_s", None), (f"{HOST}.sck_p", None)],
     "tempo_host.v:101,287: sck_p <= sck_s, a third copy stage for edge detection",
     [[("pi", "ui_in", 0), (f"{HOST}.sck_meta", 0), (f"{HOST}.sck_s", 0), (f"{HOST}.sck_p", 0)]]),
    ("MOSI synchronizer", "synchronizer", [(f"{HOST}.mosi_meta", None), (f"{HOST}.mosi_s", None)],
     "tempo_host.v:103,289: a two-flop synchronizer written as two 1-bit RTL registers (its flops are "
     "ui_sync0[2] and ui_sync1[2])",
     [[("pi", "ui_in", 2), (f"{HOST}.mosi_meta", 0), (f"{HOST}.mosi_s", 0)]]),
]

WORD_SCRIPT = """\
{read}
hierarchy -check -top {top}
proc -norom
flatten
tee -q -o {regs} select -list t:$*dff* %x:+[Q] t:$*dff* %d
setattr -set rtl_reg 1 t:$*dff* %x:+[Q] t:$*dff* %d
opt_expr
opt_clean
opt -nodffe -nosdff
fsm_detect
opt
wreduce
opt_clean
tee -q -o {stat} stat
write_json {wl}
dffunmap
techmap
opt_clean
write_json {gates}
"""

# LibreLane 3.x's coarse synthesis sequence up to its `fsm` pass
# (tools/roundtrip/synth.py transcribes the whole script)
FSM_SCRIPT = """\
{read}
hierarchy -check -top {top} -nokeep_prints -nokeep_asserts
proc
opt_expr
flatten
opt_expr
opt_clean
opt -nodffe -nosdff
fsm -nomap -encfile {enc}
"""


def _q(s):
    return '"' + s + '"' if re.search(r"\s", s) else s


def rtl_inputs():
    """(design, [verilog files], [defines]) as TEMPO's flow configures them."""
    with open(os.path.join(SRC, "user_config.json")) as f:
        uc = json.load(f)
    files = [os.path.join(SRC, v[len("dir::"):]) if v.startswith("dir::") else v for v in uc["VERILOG_FILES"]]
    with open(os.path.join(SRC, "config.json")) as f:
        cfg = json.load(f)
    defines = list(cfg.get("VERILOG_DEFINES") or []) + list(FLOW_DEFINES)
    return uc["DESIGN_NAME"], files, defines


def run_yosys(work, top=None, files=None, defines=None, incdir=None, extra_read="", cwd=None,
              fsm_defer=True, fsm_noautowire=True):
    """Run the two Yosys scripts (WORD_SCRIPT, FSM_SCRIPT) on an RTL design; returns (paths, the
    scripts' text, Yosys version, files, defines). Defaults: TEMPO as its flow configures it
    (`rtl_inputs`). Third-party designs (tools/s3/thirdparty.py) pass their own top, files,
    defines and include directory, `extra_read` (e.g. a Liberty file for hand-instantiated
    combinational cells, read after the sources), `cwd` (where $readmem paths resolve) and
    the FSM read flags their flow used."""
    os.makedirs(work, exist_ok=True)
    if files is None:
        top, files, defines = rtl_inputs()
        incdir = SRC
    dflags = " ".join(f"-D{d}" for d in defines or ())
    srcs = " ".join(_q(f) for f in files)
    inc = f" -I{_q(incdir)}" if incdir else ""
    p = {k: os.path.join(work, v) for k, v in dict(wl="wl.json", gates="gates.json", regs="rtl_regs.txt",
                                                   stat="wl_stat.txt", enc="fsm_encoding.txt",
                                                   word_ys="word.ys", fsm_ys="fsm.ys", word_log="word.log",
                                                   fsm_log="fsm.log").items()}
    word = WORD_SCRIPT.format(read=f"read_verilog -sv -mem2reg {dflags}{inc} {srcs}{extra_read}", top=top,
                              regs=_q(p["regs"]), stat=_q(p["stat"]), wl=_q(p["wl"]), gates=_q(p["gates"]))
    flags = ("-defer " if fsm_defer else "") + ("-noautowire " if fsm_noautowire else "")
    fsm = FSM_SCRIPT.format(read=f"read_verilog {flags}-sv {dflags}{inc} {srcs}{extra_read}", top=top,
                            enc=_q(p["enc"]))
    for name, text in (("word", word), ("fsm", fsm)):
        with open(p[f"{name}_ys"], "w") as f:
            f.write(text)
        r = subprocess.run([YOSYS, "-q", "-l", p[f"{name}_log"], "-s", p[f"{name}_ys"]], cwd=cwd,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if r.returncode:
            raise RuntimeError(f"yosys {name} failed:\n{r.stderr[-2000:]}")
    ver = subprocess.run([YOSYS, "-V"], capture_output=True, text=True).stdout.strip()
    return p, {"word": word, "fsm": fsm}, ver, files, defines


def _short_src(src):
    """'/x/y/tempo_core.v:198.3-211.6|...' -> 'tempo_core.v:198' (first location)."""
    if not src:
        return None
    first = src.split("|")[0]
    m = re.match(r".*/([^/]+?):(\d+)", first)
    return f"{m.group(1)}:{m.group(2)}" if m else first


def _indices(w):
    n, off = len(w["bits"]), w.get("offset", 0)
    return [off + n - 1 - i for i in range(n)] if w.get("upto") else [off + i for i in range(n)]


def _module_of(name, top=None):
    """hierarchical instance path of a flattened wire/cell name (`top` for the top module)."""
    top = top or TOP
    name = name.lstrip("\\$")
    if name.startswith("flatten\\"):
        parts = re.findall(r"\\([^\\$]+?)\.", name)
        return ".".join(parts) or top
    return name.rsplit(".", 1)[0] if "." in name else top


def _pint(v):
    """Yosys JSON parameter (binary string or int) -> int (x/z -> 0)."""
    if isinstance(v, int):
        return v
    return int(re.sub("[^01]", "0", v) or "0", 2)


# ============================================================================ word-level model

class Word:
    """wl.json: the flattened word-level RTL of module `top` (default TOP). `sources` are the RTL
    files scanned for `integer` declarations (default: the .v/.sv files in SRC).

    A flop Q bit that several tagged register names share (Yosys merged registers that are always
    assigned alike) lists them all in reg_of[bit], sorted by (name, index); the first is the bit's
    canonical key, which RtlGates uses too, so both models key the flop alike."""

    def __init__(self, path, regs_file=None, top=None, sources=None):
        self.top = top or TOP
        with open(path) as f:
            m = json.load(f)["modules"][self.top]
        self.cells = {n: c for n, c in m["cells"].items() if c["type"] != "$scopeinfo"}
        self.netnames = m["netnames"]
        self.ports = m["ports"]
        self.driver, self.users = {}, collections.defaultdict(list)
        for pname, p in self.ports.items():
            for i, b in enumerate(p["bits"]):
                if isinstance(b, str):
                    continue
                if p["direction"] == "input":
                    self.driver[b] = ("PI", pname, i)
                else:
                    self.users[b].append(("PO", pname, i))
        for cn, c in self.cells.items():
            dirs = c.get("port_directions", {})
            for pn, bits in c["connections"].items():
                for i, b in enumerate(bits):
                    if isinstance(b, str):
                        continue
                    if dirs.get(pn) == "output":
                        self.driver[b] = (cn, pn, i)
                    else:
                        self.users[b].append((cn, pn, i))
        self.names = collections.defaultdict(list)
        self.byname = {}
        for n, w in self.netnames.items():
            for idx, b in zip(_indices(w), w["bits"]):
                if not w["hide_name"] and not isinstance(b, str):
                    self.names[b].append((n, idx))
                self.byname[(n, idx)] = b
            if len(w["bits"]) == 1:
                self.byname[(n, None)] = w["bits"][0]
        self.ffbit = {}
        for cn, c in self.cells.items():
            if c["type"] in FF_TYPES:
                for i, b in enumerate(c["connections"]["Q"]):
                    self.ffbit[b] = (cn, i)
        # registers: public wires tagged rtl_reg (the Q wire of a clocked assignment)
        self.regs, self.reg_of = {}, collections.defaultdict(list)
        for n, w in sorted(self.netnames.items()):
            if w["hide_name"] or "rtl_reg" not in w["attributes"]:
                continue
            bits = dict(zip(_indices(w), w["bits"]))
            self.regs[n] = {"bits": bits, "src": w["attributes"].get("src"), "attrs": w["attributes"]}
            for idx, b in bits.items():
                if b in self.ffbit:
                    self.reg_of[b].append((n, idx))
        for keys in self.reg_of.values():
            keys.sort()  # canonical key first (RtlGates.qkey picks the same)
        # registers tagged after proc but gone from wl.json (removed as unused); `integer`
        # loop variables of clocked for-loops are tagged too and are not registers
        self.removed_regs, self.loop_vars = [], []
        self.dyn_arrays = collections.defaultdict(set)  # array -> write sites (non-constant index)
        integers = set()
        if sources is None:
            sources = [os.path.join(SRC, fn) for fn in sorted(os.listdir(SRC) if os.path.isdir(SRC) else [])]
        for path in sources:
            if path.endswith((".v", ".sv")) and os.path.isfile(path):
                with open(path, errors="replace") as f:
                    for decl in re.findall(r"\binteger\s+([\w\s,]+);", f.read()):
                        integers.update(x.strip() for x in decl.split(","))
        if regs_file and os.path.exists(regs_file):
            with open(regs_file) as f:
                for line in f:
                    w = line.strip().split("/", 1)[-1]
                    # an array written at a non-constant index: mem2reg's write-port wires, in a
                    # flattened submodule ($flatten\u_a.\u_b.$mem2reg_wr$\arr$...) or in the top
                    # module ($mem2reg_wr$\arr$...)
                    m = re.match(r"^(?:\$flatten(.*)\.)?\$mem2reg_wr\$\\(.+?)\$(.+)_(ADDR|DATA)$", w)
                    if m:
                        scope = ".".join(re.findall(r"\\([^\\]+?)(?=\.|$)", m.group(1) or ""))
                        self.dyn_arrays[f"{scope}.{m.group(2)}" if scope else m.group(2)].add(_short_src(m.group(3)))
                    elif w and not w.startswith("$") and w not in self.regs:
                        (self.loop_vars if w.rsplit(".", 1)[-1] in integers else self.removed_regs).append(w)
        self._ml, self._sel, self._ac, self._xc = {}, {}, {}, {}

    # ------------------------------------------------------------------ naming
    _SYM = {"$reduce_and": "&", "$reduce_or": "|", "$reduce_bool": "|", "$logic_and": "&&", "$logic_or": "||",
            "$logic_not": "!", "$not": "~", "$and": "&", "$or": "|", "$eq": "==", "$ne": "!=", "$xor": "^"}

    def bitname(self, b, depth=2):
        """best human name for a bit: a public alias, else its driving gate spelled out over
        named inputs (`depth` levels), else the driving cell and its source line."""
        if isinstance(b, str):
            return f"1'b{b}"
        ns = self.names.get(b)
        if ns:
            n, i = min(ns, key=lambda x: ("rtl_reg" not in self.netnames[x[0]]["attributes"], x[0].count("."), x[0]))
            w = self.netnames[n]
            return n if len(w["bits"]) == 1 else f"{n}[{i}]"
        d = self.driver.get(b)
        if d is None:
            return "<undriven>"
        if d[0] == "PI":
            return f"{d[1]}[{d[2]}]" if len(self.ports[d[1]]["bits"]) > 1 else d[1]
        c = self.cells[d[0]]
        sym = self._SYM.get(c["type"])
        if sym and depth > 0 and len(c["connections"].get("Y", [])) == 1:
            con = c["connections"]
            if c["type"].startswith("$reduce") or len(con["A"]) == 1 and "B" not in con:
                args = [self.bitname(x, depth - 1) for x in con["A"]]
                if sym in ("!", "~"):
                    return f"{sym}{args[0]}"
                return "(" + f" {sym} ".join(args[:6]) + (" ..." if len(args) > 6 else "") + ")"
            if "B" in con:
                a = self.bitname(con["A"][0], depth - 1) if len(con["A"]) == 1 else self.signal(con["A"])
                bb = self.bitname(con["B"][0], depth - 1) if len(con["B"]) == 1 else self.signal(con["B"])
                return f"({a} {sym} {bb})"
        return f"<{c['type'][1:]} {_short_src(c['attributes'].get('src')) or 'from an opt pass'}>"

    def signal(self, bits):
        """name for a list of bits (a vector, a slice or a single bit)."""
        bits = list(bits)
        if len(bits) == 1:
            return self.bitname(bits[0])
        if all(isinstance(b, str) for b in bits):
            return f"{len(bits)}'b" + "".join(reversed(bits))
        for n, w in self.netnames.items():
            if w["hide_name"]:
                continue
            wb = w["bits"]
            if len(wb) >= len(bits) and bits[0] in wb:
                i = wb.index(bits[0])
                if wb[i:i + len(bits)] == bits:
                    idx = _indices(w)
                    return n if len(bits) == len(wb) else f"{n}[{idx[i + len(bits) - 1]}:{idx[i]}]"
        return "{" + ", ".join(self.bitname(b) for b in reversed(bits)) + "}"

    # ------------------------------------------------------------------ tracing
    def mux_leaves(self, b):
        """leaves of the mux tree driving bit b: ('const', v) ('pi', port, i) ('ff', qbit)
        ('cell', cell, port, off) ('undriven', b); select bits collected in self._sel[b]."""
        if isinstance(b, str):
            return frozenset({("const", b)})
        if b in self._ml:
            return self._ml[b]
        d = self.driver.get(b)
        sel = set()
        if d is None:
            res = frozenset({("undriven", b)})
        elif d[0] == "PI":
            res = frozenset({("pi", d[1], d[2])})
        else:
            cn, pn, off = d
            c = self.cells[cn]
            t, con = c["type"], c["connections"]
            if t in FF_TYPES:
                res = frozenset({("ff", b)})
            elif t == "$mux":
                res = self.mux_leaves(con["A"][off]) | self.mux_leaves(con["B"][off])
                sel = {con["S"][0]} | self._sel.get(con["A"][off], set()) | self._sel.get(con["B"][off], set())
            elif t == "$pmux":
                w = len(con["Y"])
                ins = [con["A"][off]] + [con["B"][j * w + off] for j in range(len(con["S"]))]
                res = frozenset().union(*(self.mux_leaves(x) for x in ins))
                sel = set(con["S"]).union(*(self._sel.get(x, set()) for x in ins))
            else:
                res = frozenset({("cell", cn, pn, off)})
        self._ml[b] = res
        self._sel[b] = sel
        return res

    def _aligned_inputs(self, cn, off, types):
        """input bits feeding output bit `off` of cell cn, bit-aligned, if its type is in `types`."""
        c = self.cells[cn]
        t, con = c["type"], c["connections"]
        if t not in types:
            return None
        if t in ("$mux",):
            return [con["A"][off], con["B"][off]]
        if t == "$pmux":
            w = len(con["Y"])
            return [con["A"][off]] + [con["B"][j * w + off] for j in range(len(con["S"]))]
        ins = []
        for p in ("A", "B"):
            if p in con:
                bits = con[p]
                if off < len(bits):
                    ins.append(bits[off])
                elif bits and _pint(c["parameters"].get(f"{p}_SIGNED", 0)):
                    ins.append(bits[-1])  # sign extension
        return ins

    def closure(self, b, types, memo):
        """leaves reachable from bit b through bit-aligned cells of `types` (and mux data)."""
        if isinstance(b, str):
            return frozenset({("const", b)})
        if b in memo:
            return memo[b]
        memo[b] = frozenset()  # cycle guard (combinational loops do not exist; be safe)
        d = self.driver.get(b)
        if d is None:
            res = frozenset({("undriven", b)})
        elif d[0] == "PI":
            res = frozenset({("pi", d[1], d[2])})
        elif self.cells[d[0]]["type"] in FF_TYPES:
            res = frozenset({("ff", b)})
        else:
            ins = self._aligned_inputs(d[0], d[2], types | {"$mux", "$pmux"})
            if ins is None:
                res = frozenset({("cell",) + d})
            else:
                res = frozenset().union(*(self.closure(x, types, memo) for x in ins)) if ins else frozenset()
        memo[b] = res
        return res

    def xor_closure(self, b):
        """(all leaves, leaves reached through at least one XOR) through bitwise logic and mux data."""
        if isinstance(b, str):
            return frozenset(), frozenset()
        if b in self._xc:
            return self._xc[b]
        self._xc[b] = (frozenset(), frozenset())
        d = self.driver.get(b)
        if d is None or d[0] == "PI" or self.cells[d[0]]["type"] in FF_TYPES:
            leaf = frozenset({("ff", b)}) if d and d[0] != "PI" else frozenset({("pi", b)})
            res = (leaf, frozenset())
        else:
            t = self.cells[d[0]]["type"]
            ins = self._aligned_inputs(d[0], d[2], BITWISE | {"$mux", "$pmux"})
            if ins is None:
                res = (frozenset({("cell",) + d}), frozenset())
            else:
                subs = [self.xor_closure(x) for x in ins]
                every = frozenset().union(*(s[0] for s in subs)) if subs else frozenset()
                via = every if t in XORS else (frozenset().union(*(s[1] for s in subs)) if subs else frozenset())
                res = (every, via)
        self._xc[b] = res
        return res

    def cone_cells(self, bits, depth=8):
        """cells (and FF Q bits) in the combinational fan-in of `bits`, up to `depth` cells deep."""
        seen, ffs, frontier = set(), set(), [b for b in bits if not isinstance(b, str)]
        for _ in range(depth):
            nxt = []
            for b in frontier:
                d = self.driver.get(b)
                if d is None or d[0] == "PI":
                    continue
                if self.cells[d[0]]["type"] in FF_TYPES:
                    ffs.add(b)
                    continue
                if d[0] in seen:
                    continue
                seen.add(d[0])
                c = self.cells[d[0]]
                for pn, bs in c["connections"].items():
                    if c.get("port_directions", {}).get(pn) == "input":
                        nxt.extend(x for x in bs if not isinstance(x, str))
            frontier = nxt
        return seen, ffs


# ============================================================================ classification

def _const_value(bits):
    if all(isinstance(b, str) for b in bits):
        return int("".join(reversed([("1" if b == "1" else "0") for b in bits])) or "0", 2)
    return None


class Classifier:
    def __init__(self, word, fsm_regs):
        self.w = word
        self.fsm_regs = fsm_regs
        self.sync_stage = {}  # ff Q bit -> stage
        self._find_sync()
        # the chip reset: the sync-reset signal shared by most flops
        srst = collections.Counter(c["connections"]["SRST"][0] for c in word.cells.values()
                                   if c["type"] in FF_TYPES and "SRST" in c["connections"])
        self.chip_reset = srst.most_common(1)[0][0] if srst else None

    def _ff_of(self, q):
        cn, off = self.w.ffbit[q]
        return self.w.cells[cn], off

    def _d(self, q):
        c, off = self._ff_of(q)
        return c["connections"]["D"][off]

    def _has_en(self, q):
        c, _ = self._ff_of(q)
        return "EN" in c["connections"]

    def _find_sync(self):
        """stage 1: no enable, D is an input pin (or its inverse); stage 2: D is a stage-1 bit."""
        w = self.w
        for q in w.ffbit:
            if self._has_en(q):
                continue
            L = w.mux_leaves(self._d(q))
            if len(L) != 1:
                continue
            (leaf,) = L
            if leaf[0] == "pi" and leaf[1] != "clk":
                self.sync_stage[q] = 1
            elif leaf[0] == "cell":
                c = w.cells[leaf[1]]
                if c["type"] in ("$not", "$logic_not") and len(c["connections"]["A"]) == 1:
                    src = w.driver.get(c["connections"]["A"][0])
                    if src and src[0] == "PI":
                        self.sync_stage[q] = 1
        for q in w.ffbit:
            if q in self.sync_stage or self._has_en(q):
                continue
            L = w.mux_leaves(self._d(q))
            if len(L) == 1:
                (leaf,) = L
                if leaf[0] == "ff" and self.sync_stage.get(leaf[1]) == 1:
                    self.sync_stage[q] = 2

    # ------------------------------------------------------------------
    def regname(self, q):
        rs = self.w.reg_of.get(q)
        return rs[0][0] if rs else self.w.bitname(q)

    def classify(self, name):
        """(kind, details) of register `name` by the word-level rules (module docstring, step 2).
        details may carry "alt_kinds" and "alt_reason" when a rule itself names alternatives
        (TOGGLE_RULE); the caller moves them to the register."""
        w = self.w
        reg = w.regs[name]
        bits = reg["bits"]
        ff = {i: b for i, b in bits.items() if b in w.ffbit}
        mine = {b: i for i, b in ff.items()}
        det = {"module": _module_of(name, w.top)}
        det["src"] = {"decl": _short_src(reg["src"]),
                      "always": sorted({_short_src(w.cells[w.ffbit[b][0]]["attributes"].get("src")) for b in ff.values()}
                                       - {None})}
        det["slices"] = self._slices(ff)
        if not ff:
            det["rule"] = "no flop in the RTL netlist (all bits constant)"
            return "flag", det
        n = len(ff)
        leaves = {i: w.mux_leaves(self._d(b)) for i, b in ff.items()}
        sels = set().union(*(w._sel.get(self._d(b), set()) for b in ff.values()))
        own_off = collections.Counter()
        srcs = {"registers": set(), "inputs": set(), "constants": set(), "operators": collections.Counter()}
        cell_leaves = []
        for i, L in leaves.items():
            for lf in L:
                if lf[0] == "ff":
                    if lf[1] in mine:
                        own_off[mine[lf[1]] - i] += 1
                    else:
                        srcs["registers"].add(self.regname(lf[1]))
                elif lf[0] == "pi":
                    srcs["inputs"].add(lf[1])
                elif lf[0] == "const":
                    srcs["constants"].add(lf[1])
                elif lf[0] == "cell":
                    cell_leaves.append((i, lf))
                    srcs["operators"][w.cells[lf[1]]["type"]] += 1
        # constants as values per slice: collect whole-vector constant loads
        det["sources"] = {"registers": sorted(srcs["registers"])[:24], "inputs": sorted(srcs["inputs"]),
                          "constants": sorted(srcs["constants"]),
                          "operators": dict(sorted(srcs["operators"].items()))}
        det["selects"] = sorted({w.bitname(s) for s in sels})[:16]

        def done(kind, rule, **extra):
            det["rule"] = rule
            det.update(extra)
            return kind, det

        # 1. a word of an RTL array written at a non-constant index: register_file_word. (Tried on
        # 2026-09-22: the structure rules first, as the truth review proposed so that an array of
        # counters stays counters. On the 15 excluded third-party designs that labelled 36
        # ALU-written register-file words (a Forth stack, shader registers) shift_register: a
        # word read through the index mux and written back through a wiring shift has D[k] =
        # Q[k+1] structurally, whether or not the write and read index can agree; no array of
        # counters or shifts turned up. The rule order stays array-first until that is decided
        # per word, e.g. by SAT on write index == read index.)
        m = re.match(r"^(.*)\[(\d+)\]$", name)
        if m and m.group(1) in w.dyn_arrays:
            base, word = m.group(1), int(m.group(2))
            words = sorted(int(re.match(r".*\[(\d+)\]$", r).group(1)) for r in w.regs
                           if re.match(re.escape(base) + r"\[\d+\]$", r))
            nxt = f"{base}[{word + 1}]"
            shift = False
            if nxt in w.regs:
                nb = {b: i for i, b in w.regs[nxt]["bits"].items()}
                shift = sum(1 for i, L in leaves.items() for lf in L
                            if lf[0] == "ff" and nb.get(lf[1]) == i) >= n // 2
            return done("register_file_word", "word of an RTL array written at a non-constant index",
                        register_file_word={"array": base, "word": word, "words": len(words),
                                            "dynamic_write_sites": sorted(w.dyn_arrays[base]),
                                            "word_shift": shift})
        # 2. FSM
        if name in self.fsm_regs or "fsm_encoding" in reg["attrs"]:
            enc = self.fsm_regs.get(name)
            return done("fsm_state", "Yosys fsm_detect marks it an FSM state register",
                        fsm_state={"states": len(enc) if enc else None,
                                   "state_codes": sorted({c for c in enc.values()}) if enc else None})
        # 3. synchronizer
        stages = {i: self.sync_stage.get(b) for i, b in ff.items()}
        if all(stages.values()):
            return done("synchronizer", "no enable; D is an input pin (stage 1) or a stage-1 flop (stage 2)",
                        synchronizer={"stages": sorted(set(stages.values())),
                                      "source": sorted({w.bitname(self._d(b)) for b in ff.values()})[:8]})
        # 4. LFSR / CRC: own Q bits of other indices reach D through XOR
        cross, xor_bits, xor_other = collections.Counter(), 0, set()
        for i, L in leaves.items():
            hit = False
            for lf in L:
                if lf[0] != "cell" or w.cells[lf[1]]["type"] not in XORS:
                    continue
                _every, via = w.xor_closure(w.cells[lf[1]]["connections"][lf[2]][lf[3]])
                for x in via:
                    if x[0] == "ff" and x[1] in mine and mine[x[1]] != i:
                        cross[mine[x[1]] - i] += 1
                        hit = True
                    elif x[0] == "ff" and x[1] not in mine:
                        xor_other.add(self.regname(x[1]))
                    elif x[0] == "cell":
                        for y in w.closure(w.cells[x[1]]["connections"][x[2]][x[3]], BITWISE, w._ac):
                            if y[0] == "ff" and y[1] not in mine:
                                xor_other.add(self.regname(y[1]))
            xor_bits += hit
        if xor_bits >= max(2, n // 4):
            poly = sorted(r for r in xor_other if r != name)
            return done("lfsr_crc", "own Q bits of other indices reach D through XOR (GF(2) feedback)",
                        lfsr_crc={"bits_with_feedback": xor_bits,
                                  "cross_offsets": dict(sorted(sorted(cross.items(), key=lambda kv: (-kv[1], kv[0]))[:12])),
                                  "other_registers_in_xor_cone": poly[:12]})
        # 5. counter / accumulator
        arith = self._arith(name, ff, mine, leaves)
        if arith:
            kind, info = arith
            info["compares"] = self._compares(sels, mine, name)
            if kind == "counter" and info["direction"] == "up" and info.get("step") == 1:
                wraps = [c for c in info["compares"] if c.startswith("==")]
                if wraps and "0" in srcs["constants"]:
                    info["modulus"] = int(wraps[0][2:]) + 1
            info["loads"] = {"registers": sorted(srcs["registers"])[:12], "inputs": sorted(srcs["inputs"]),
                             "constants": sorted(srcs["constants"])}
            if kind == "counter" and n == 1:  # a 1-bit counter is a toggle (TOGGLE_RULE)
                return done("flag", "one bit counting by an adder on its own Q (a toggle); " + TOGGLE_RULE,
                            flag={"toggle": True, "modulus": 2, "counter_rule": info},
                            alt_kinds=["counter"], alt_reason=TOGGLE_RULE)
            return done(kind, info.pop("rule"), **{kind: info})
        # 6. shift register
        shifts = {s: c for s, c in own_off.items() if s != 0}
        if n >= 2 and shifts:
            s, c = max(shifts.items(), key=lambda kv: (kv[1], -abs(kv[0]), kv[0]))
            if c >= max(1, 0.75 * (n - abs(s))):
                fed = {i for i, L in leaves.items() if any(lf[0] == "ff" and mine.get(lf[1]) == i + s for lf in L)}
                serial = sorted({self._leafname(lf) for i, L in leaves.items() if i not in fed for lf in L
                                 if not (lf[0] == "ff" and lf[1] in mine)})[:8]
                return done("shift_register", f"D[k] = Q[k{s:+d}] on {c} of {n - abs(s)} shiftable bits",
                            shift_register={"shift": s, "direction": "toward MSB" if s < 0 else "toward LSB",
                                            "shifted_bits": c, "serial_in": serial})
        # 7. one bit
        if n == 1:
            (i, L), = leaves.items()
            q = ff[i]
            nots = [lf for lf in L if lf[0] == "cell" and w.cells[lf[1]]["type"] in ("$not", "$logic_not")
                    and w.cells[lf[1]]["connections"]["A"] == [q]]
            rest = [lf for lf in L if lf not in nots and lf[0] != "const" and not (lf[0] == "ff" and lf[1] == q)]
            if nots and not rest:
                return done("flag", "one bit with D = ~Q (a toggle); " + TOGGLE_RULE,
                            flag={"toggle": True, "modulus": 2}, alt_kinds=["counter"], alt_reason=TOGGLE_RULE)
            return done("flag", "single-bit register")
        # 8. several bits
        nonown = [lf for L in leaves.values() for lf in L if not (lf[0] == "ff" and lf[1] in mine)]
        if nonown and all(lf[0] == "const" for lf in nonown):
            return done("flag", "several bits written only with constants (independent control bits)")
        # per-bit read-modify-write: own Q[k] reaches D[k] through bitwise logic
        rmw, indexed = 0, False
        for i, L in leaves.items():
            for lf in sorted(L, key=repr):
                if lf[0] != "cell" or w.cells[lf[1]]["type"] not in BITWISE:
                    continue
                cl = w.closure(w.cells[lf[1]]["connections"][lf[2]][lf[3]], BITWISE, w._ac)
                if any(x[0] == "ff" and mine.get(x[1]) == i for x in cl):
                    rmw += 1
                    indexed |= any(x[0] == "cell" and w.cells[x[1]]["type"] in ("$shl", "$sshl", "$shr")
                                   and _const_value(w.cells[x[1]]["connections"]["B"]) is None
                                   for x in cl)
                    break
        if rmw >= n // 2:
            sub = "indexed bit insert (bit << index)" if indexed else "masked per-bit read-modify-write"
            return done("data_register", f"own Q[k] reaches D[k] through bitwise logic: {sub}",
                        data_register={"update": sub})
        plain = all("EN" not in w.cells[w.ffbit[b][0]]["connections"] and
                    w.cells[w.ffbit[b][0]]["connections"].get("SRST", [self.chip_reset])[0] == self.chip_reset
                    for b in ff.values())
        if plain and not sels and all(lf[0] in ("ff", "const") for lf in nonown) and \
                any(lf[0] == "ff" for lf in nonown):
            return done("data_register", "no enable, no mux, only the chip reset: a delayed copy of "
                        "other registers", data_register={"update": "delay (previous value)"})
        ops = sorted({w.cells[lf[1]]["type"] for _i, lf in cell_leaves})
        return done("data_register", "loads external or computed values (no own feedback beyond hold)",
                    data_register={"update": "load", "loaded_from_operators": ops})

    def _leafname(self, lf):
        if lf[0] == "ff":
            return self.w.bitname(lf[1])
        if lf[0] == "pi":
            return f"{lf[1]}[{lf[2]}]"
        if lf[0] == "const":
            return f"1'b{lf[1]}"
        if lf[0] == "cell":
            return self.w.bitname(self.w.cells[lf[1]]["connections"][lf[2]][lf[3]])
        return str(lf)

    def _slices(self, ff):
        w, out = self.w, []
        by_cell = collections.defaultdict(list)
        for i, b in ff.items():
            by_cell[w.ffbit[b][0]].append(i)
        for cn, idx in sorted(by_cell.items(), key=lambda kv: min(kv[1])):
            c = w.cells[cn]
            con, par = c["connections"], c["parameters"]
            s = {"bits": [min(idx), max(idx)], "cell": c["type"]}
            if "EN" in con:
                s["enable"] = ("" if _pint(par.get("EN_POLARITY", 1)) else "!") + w.bitname(con["EN"][0])
            if "SRST" in con:
                s["sync_reset"] = ("" if _pint(par.get("SRST_POLARITY", 1)) else "!") + w.bitname(con["SRST"][0])
                v = par.get("SRST_VALUE")
                s["reset_value"] = hex(_pint(v)) if v is not None else None
            if "ARST" in con:
                s["async_reset"] = w.bitname(con["ARST"][0])
            out.append(s)
        return out

    def _arith(self, name, ff, mine, leaves):
        """counter/accumulator: an adder chain in D with the register's own Q (aligned) on one side."""
        w = self.w
        adders, found = {}, set()

        def walk(cn, off, i, sign, depth=0):
            if (cn, off) in found or depth > 6:
                return
            found.add((cn, off))
            c = w.cells[cn]
            con = c["connections"]
            own_side = None
            for p in ("A", "B"):
                bits = con[p]
                if off < len(bits):
                    cl = w.closure(bits[off], ARITH, w._ac)
                    if any(x[0] == "ff" and mine.get(x[1]) == i for x in cl):
                        own_side = p
                        break
            if own_side is None:
                return
            other = "B" if own_side == "A" else "A"
            osign = -sign if (c["type"] == "$sub" and other == "B") else sign
            # innermost: the own side is the register itself (through muxes), not another adder
            inner = any(x[0] == "ff" and mine.get(x[1]) == i for x in w.mux_leaves(con[own_side][off]))
            adders[cn] = (c["type"], own_side, other, osign, inner)
            for lf in w.mux_leaves(con[own_side][off]):
                if lf[0] == "cell" and w.cells[lf[1]]["type"] in ARITH:
                    walk(lf[1], lf[3], i, sign if not (c["type"] == "$sub" and own_side == "B") else -sign, depth + 1)

        for i, L in leaves.items():
            for lf in L:
                if lf[0] == "cell" and w.cells[lf[1]]["type"] in ARITH:
                    walk(lf[1], lf[3], i, +1)
        if not adders:
            return None
        # the adder that consumes the register itself decides: +/- a constant or a 1-bit
        # condition makes a counter (outer adders on its result are relative loads, e.g. a
        # PC's branch offset); + a multi-bit variable makes an accumulator
        terms = []  # (inner, "const"|"bit"|"var", sign, value/text)
        for cn, (t, own, other, sgn, inner) in sorted(adders.items()):
            ob = w.cells[cn]["connections"][other]
            cv = _const_value(ob)
            if cv is not None:
                if cv:
                    terms.append((inner, "const", sgn, cv))
            elif all(isinstance(b, str) and b == "0" for b in ob[1:]):
                terms.append((inner, "bit", sgn, w.bitname(ob[0])))
            else:
                terms.append((inner, "var", sgn, w.signal(ob)))
        if not terms:
            return None
        terms = sorted(set(terms), key=lambda tm: (not tm[0], tm[1], -tm[2], str(tm[3])))
        fmt = lambda tm: ("+" if tm[2] > 0 else "-") + str(tm[3])
        srcs = sorted({_short_src(w.cells[cn]["attributes"].get("src")) for cn in adders} - {None})
        if any(tm[0] and tm[1] == "var" for tm in terms):
            signs = {tm[2] for tm in terms if tm[0] and tm[1] == "var"}
            info = {"rule": "D = Q + a multi-bit variable (the adder on own Q)",
                    "direction": "updown" if len(signs) > 1 else ("up" if signs == {1} else "down"),
                    "addend": [fmt(tm) for tm in terms if tm[0] and tm[1] == "var"][:6], "adders": srcs}
            rest = [fmt(tm) for tm in terms if not (tm[0] and tm[1] == "var")]
            if rest:
                info["further_terms"] = rest[:6]
            return "accumulator", info
        # counter: constant steps on own Q, 1-bit conditional steps anywhere in the chain;
        # multi-bit terms of outer adders are relative loads (a PC's branch offset)
        stepping = [tm for tm in terms if (tm[0] and tm[1] == "const") or tm[1] == "bit"]
        if not stepping:
            return None
        signs = {tm[2] for tm in stepping}
        direction = "updown" if len(signs) > 1 else ("up" if signs == {1} else "down")
        steps = {tm[3] for tm in stepping if tm[1] == "const"}
        conditional = [fmt(tm) for tm in stepping if tm[1] == "bit"]
        offsets = [fmt(tm) for tm in terms if tm not in stepping]
        info = {"rule": "D = Q +/- constant or +/- a 1-bit condition (the adder on own Q)",
                "direction": direction, "adders": srcs}
        if steps:
            info["step"] = min(steps) if len(steps) == 1 else sorted(steps)
        if conditional:
            info["conditional_step"] = conditional
            info.setdefault("step", 1)
        if offsets:
            info["relative_loads"] = offsets[:6]
        return "counter", info

    def _compares(self, sels, mine, name):
        """comparisons of the register's own value against constants in its mux selects."""
        w, out = self.w, set()
        cells, _ffs = w.cone_cells(list(sels), depth=4)
        for cn in cells:
            c = w.cells[cn]
            if c["type"] not in CMP:
                continue
            a, b = c["connections"]["A"], c["connections"]["B"]
            for x, y in ((a, b), (b, a)):
                if x and all(bb in mine for bb in x if not isinstance(bb, str)) and any(bb in mine for bb in x):
                    cv = _const_value(y)
                    if cv is not None:
                        op = {"$eq": "==", "$ne": "!=", "$lt": "<", "$le": "<=", "$gt": ">", "$ge": ">="}.get(
                            c["type"], c["type"])
                        if x is b:
                            op = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}.get(op, op)
                        out.add(f"{op}{cv}")
        return sorted(out)

    # ------------------------------------------------------------------ lenient units by rule
    # The RTL facts behind UNIT_RULES; rule_units() below turns them into truth units with join
    # keys. TEMPO's build and the blind-set labeller (tools/s3/thirdparty.py) both call it.
    PATH_CAP = 256  # mux paths per D input beyond which the input counts as irregular (no lane)

    def _mux_paths(self, b):
        """{leaf: {path}} for the mux tree driving bit b (leaves as in Word.mux_leaves); a path is
        the frozenset of (select bit, value) literals that routes the leaf to b ($pmux: that case's
        select 1, or every select 0 for its default). Paths with contradictory literals are dropped,
        a constant select routes one way only. None when the tree has more than PATH_CAP paths."""
        memo = self.__dict__.setdefault("_mpaths", {})
        if b in memo:
            return memo[b]
        memo[b] = None  # cycle guard
        w = self.w
        if isinstance(b, str):
            res = {("const", b): {frozenset()}}
        else:
            d = w.driver.get(b)
            if d is None:
                res = {("undriven", b): {frozenset()}}
            elif d[0] == "PI":
                res = {("pi", d[1], d[2]): {frozenset()}}
            else:
                cn, pn, off = d
                c = w.cells[cn]
                t, con = c["type"], c["connections"]
                if t in FF_TYPES:
                    res = {("ff", b): {frozenset()}}
                elif t in ("$mux", "$pmux"):
                    if t == "$mux":
                        arms = [(con["A"][off], [(con["S"][0], 0)]), (con["B"][off], [(con["S"][0], 1)])]
                    else:
                        wd, S = len(con["Y"]), con["S"]
                        arms = [(con["A"][off], [(s, 0) for s in S])] + \
                               [(con["B"][j * wd + off], [(S[j], 1)]) for j in range(len(S))]
                    res, total = {}, 0
                    for x, lits in arms:
                        if any(isinstance(s, str) and s != str(v) for s, v in lits):
                            continue  # a constant select never takes this arm
                        extra = frozenset((s, v) for s, v in lits if not isinstance(s, str))
                        sub = self._mux_paths(x)
                        if sub is None:
                            return None
                        for leaf, ps in sub.items():
                            for p in ps:
                                q = p | extra
                                if any((s, 1 - v) in q for s, v in q):
                                    continue
                                res.setdefault(leaf, set()).add(q)
                                total += 1
                                if total > self.PATH_CAP:
                                    return None
                else:
                    res = {("cell", cn, pn, off): {frozenset()}}
        memo[b] = res
        return res

    def _ctl_sig(self, q):
        """(controls, reset values) of the flop holding Q bit q: the Yosys cell type and each control
        pin's net and polarity (clock, enable, sync reset, async reset / set / clear / load), and the
        bit's sync and async reset values."""
        c, off = self._ff_of(q)
        con, par = c["connections"], c["parameters"]
        ctl = [c["type"]]
        for pn in ("CLK", "EN", "SRST", "ARST", "ALOAD", "SET", "CLR"):
            if pn in con:
                bits = con[pn]
                ctl.append((pn, bits[off] if len(bits) > 1 else bits[0], _pint(par.get(pn + "_POLARITY", 1))))
        rv = tuple((k, _param_bit(par[k], off)) for k in ("SRST_VALUE", "ARST_VALUE") if k in par)
        return tuple(ctl), rv

    def _ctl_text(self, q):
        """the flop controls of Q bit q in words (for unit reasons)."""
        c, off = self._ff_of(q)
        con, par = c["connections"], c["parameters"]
        out = []
        for pn, what in (("EN", "enable"), ("SRST", "sync reset"), ("ARST", "async reset"), ("ALOAD", "async load"),
                         ("SET", "async set"), ("CLR", "async clear")):
            if pn in con:
                bits = con[pn]
                pol = "" if _pint(par.get(pn + "_POLARITY", 1)) else "!"
                out.append(f"{what} {pol}{self.w.bitname(bits[off] if len(bits) > 1 else bits[0])}")
        for k, what in (("SRST_VALUE", "sync reset value"), ("ARST_VALUE", "async reset value")):
            if k in par:
                out.append(f"{what} {_param_bit(par[k], off)}")
        return ", ".join(out) or "no enable, no reset"

    def _bkey(self, q, names=None):
        """the (register, index) key of Q bit q: the smallest among `names` (default: every register
        naming it, as Word.reg_of)."""
        keys = [k for k in self.w.reg_of.get(q, []) if names is None or k[0] in names]
        return min(keys) if keys else (self.w.bitname(q), 0)

    def _sync_lanes(self, kinds):
        """Copy lanes of the synchronizer registers (kinds[name] == "synchronizer"): each stage-1 bit
        with each stage-2 bit that copies it (or alone), as lane dicts (see copy_lanes)."""
        w = self.w
        sync = {n for n, k in kinds.items() if k == "synchronizer" and n in w.regs}
        owner = collections.defaultdict(set)
        for n in sync:
            for b in w.regs[n]["bits"].values():
                if b in w.ffbit and self.sync_stage.get(b):
                    owner[b].add(n)
        succ = collections.defaultdict(list)
        for q in owner:
            if self.sync_stage[q] == 2:
                (leaf,) = w.mux_leaves(self._d(q))
                if leaf[0] == "ff" and leaf[1] in owner and self.sync_stage.get(leaf[1]) == 1:
                    succ[leaf[1]].append(q)
        lanes = []
        for q1 in sorted((q for q in owner if self.sync_stage[q] == 1), key=lambda q: self._bkey(q, owner[q])):
            (leaf,) = w.mux_leaves(self._d(q1))
            if leaf[0] == "pi":
                head = ("pi", leaf[1], leaf[2])
            else:  # the inverse of an input pin (_find_sync)
                d = w.driver[w.cells[leaf[1]]["connections"]["A"][0]]
                head = ("pi", d[1], d[2], "inv")
            for q2 in sorted(succ.get(q1, []), key=lambda q: self._bkey(q, owner[q])) or [None]:
                stages = [q1] + ([q2] if q2 is not None else [])
                lanes.append({"kind": "synchronizer", "stages": stages,
                              "keys": [self._bkey(q, owner[q]) for q in stages],
                              "registers": [sorted(owner[q]) for q in stages],
                              "head": head, "head_kind": "input", "cond": frozenset(),
                              "sigs": tuple(self._ctl_sig(q) for q in stages)})
        return lanes

    def _shift_lanes(self, name):
        """(lanes, None) of a shift register whose bits form equal-depth copy chains, every stage
        after the first copying its predecessor under one mux path, the same for all stages, with
        every flop under the same controls; else (None, why). Stage 0 is the bit whose predecessor
        lies outside the register; its head is the one leaf its D reaches under that path (a
        primary input: "input"; another register's flop: "flop"; else "logic", "const" or, for
        the register's own bits, "feedback")."""
        w = self.w
        ff = {i: b for i, b in w.regs[name]["bits"].items() if b in w.ffbit}
        mine = {b: i for i, b in ff.items()}
        paths = {i: self._mux_paths(self._d(b)) for i, b in ff.items()}
        if any(p is None for p in paths.values()):
            return None, f"a D input has more than {self.PATH_CAP} mux paths"
        off = collections.Counter()
        for i, P in paths.items():
            for leaf in P:
                if leaf[0] == "ff" and leaf[1] in mine and mine[leaf[1]] != i:
                    off[mine[leaf[1]] - i] += 1
        if not off:
            return None, "no bit copies another bit of the register"
        s = max(off.items(), key=lambda kv: (kv[1], -abs(kv[0]), kv[0]))[0]  # as classify() picks it
        idx = []
        for h in sorted(i for i in ff if i + s not in ff):
            lane = [h]
            while lane[-1] - s in ff:
                lane.append(lane[-1] - s)
            idx.append(lane)
        if sorted(i for lane in idx for i in lane) != sorted(ff) or len({len(l) for l in idx}) != 1:
            return None, "the bits do not form equal-depth chains"
        conds = set()
        for lane in idx:
            for k in lane[1:]:
                ps = paths[k].get(("ff", ff[k + s]))
                if not ps or len(ps) != 1:
                    return None, f"bit {k} is not a single-path copy of bit {k + s}"
                conds |= ps
        if len(conds) != 1:
            return None, "the stages copy under different mux conditions"
        (cond,) = conds
        sigs = [self._ctl_sig(ff[i]) for i in sorted(ff)]
        if len({sg[0] for sg in sigs}) != 1:
            return None, "the flops sit under different controls"
        lanes = []
        for lane in idx:
            hits = sorted({leaf for leaf, ps in paths[lane[0]].items() if any(cond <= p for p in ps)}, key=repr)
            if len(hits) != 1:
                head, hk = None, "logic"
            else:
                head = hits[0]
                hk = {"pi": "input", "const": "const"}.get(head[0], "logic")
                if head[0] == "ff":
                    hk = "feedback" if head[1] in mine else "flop"
            stages = [ff[i] for i in lane]
            lanes.append({"kind": "shift_register", "stages": stages, "keys": [(name, i) for i in lane],
                          "registers": [[name] for _ in lane], "head": head, "head_kind": hk, "cond": cond,
                          "sigs": tuple(self._ctl_sig(q) for q in stages),
                          "direction": "to_msb" if s < 0 else "to_lsb"})
        return lanes, None

    def _adder_slots(self, name):
        """{adder cell: {bit index: output offset}}: the innermost $add / $sub cells writing the
        register, i.e. whose output bit `offset` is a mux leaf of D[i] and whose operand bit
        `offset` is Q[i] itself (through muxes)."""
        w = self.w
        out = collections.defaultdict(dict)
        for i, b in w.regs[name]["bits"].items():
            if b not in w.ffbit:
                continue
            for lf in sorted(w.mux_leaves(self._d(b)), key=repr):
                if lf[0] != "cell" or w.cells[lf[1]]["type"] not in ARITH or lf[2] != "Y":
                    continue
                con = w.cells[lf[1]]["connections"]
                if any(lf[3] < len(con[p]) and ("ff", b) in w.mux_leaves(con[p][lf[3]]) for p in ("A", "B")):
                    out[lf[1]].setdefault(i, lf[3])
        return out

    def unit_facts(self, kinds, accepts=None):
        """RTL-level lenient units by UNIT_RULES. `kinds`: {register: final kind}; `accepts(name)`:
        the kinds a register accepts (kind plus alt_kinds; default its kind), used by concat_adder.
        Returns (units, notes): units [{rule, kind, registers, lanes (lane dicts, see _sync_lanes /
        _shift_lanes) | bit_order (RTL keys), direction, step, detail}], in rule order; notes: the
        registers a rule looked at and left out, with why."""
        w = self.w
        accepts = accepts or (lambda n: {kinds[n]})
        units, notes = [], []
        # ---- copy lanes: synchronizer stages, and shift registers whose bits form clean lanes
        lanes = self._sync_lanes(kinds)
        for n in sorted(n for n, k in kinds.items() if k == "shift_register" and n in w.regs):
            ls, why = self._shift_lanes(n)
            if ls is None:
                notes.append({"rule": "copy_lanes", "registers": [n], "left_out": why})
            else:
                lanes += ls
        regs_of = [{r for st in ln["registers"] for r in st} for ln in lanes]
        lanes_of = collections.defaultdict(set)   # register -> indices of the lanes through its bits
        for j, rs in enumerate(regs_of):
            for r in rs:
                lanes_of[r].add(j)
        # rule sync_chain: synchronizer registers linked by a stage-1 -> stage-2 copy
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for ln in lanes:
            if ln["kind"] == "synchronizer" and len(ln["stages"]) == 2:
                for a in ln["registers"][0]:
                    for b in ln["registers"][1]:
                        if a != b:
                            parent[find(a)] = find(b)
        comps = collections.defaultdict(set)
        for x in list(parent):
            comps[find(x)].add(x)
        for comp in sorted((c for c in comps.values() if len(c) >= 2), key=sorted):
            js = sorted(set().union(*(lanes_of[r] for r in comp)))
            stage_regs = [sorted({r for j in js if k < len(lanes[j]["stages"]) for r in lanes[j]["registers"][k]})
                          for k in range(max(len(lanes[j]["stages"]) for j in js))]
            regs = list(dict.fromkeys(r for st in stage_regs for r in st))
            units.append({"rule": "sync_chain", "kind": "synchronizer", "registers": regs,
                          "lanes": [lanes[j] for j in js],
                          "detail": "stage 1 in " + " + ".join(stage_regs[0]) + (
                              ", stage 2 in " + " + ".join(stage_regs[1]) if len(stage_regs) > 1 else "")})
        # rule copy_lanes: lanes of equal depth, one copy condition and heads of one external kind
        # (input pins, or flops of other registers) across >= 2 registers. A lane whose head is the
        # last stage of another lane copying under the same controls and mux condition continues
        # that lane (one longer chain, not two lanes): neither takes part.
        last_of = {ln["stages"][-1]: j for j, ln in enumerate(lanes)}
        continued = set()
        for j, ln in enumerate(lanes):
            h = ln["head"]
            i = last_of.get(h[1]) if h is not None and h[0] == "ff" else None
            if i is not None and not regs_of[i] & regs_of[j] and lanes[i]["sigs"][-1][0] == ln["sigs"][0][0] \
                    and lanes[i]["cond"] == ln["cond"]:
                continued |= {i, j}
        for j in sorted(continued):
            note = {"rule": "copy_lanes", "registers": sorted({r for st in lanes[j]["registers"] for r in st}),
                    "left_out": "a lane of these registers continues, or is continued by, another register's lane "
                                "under the same controls and copy condition (one longer chain)"}
            if note not in notes:
                notes.append(note)
        groups = collections.defaultdict(list)
        for j, ln in enumerate(lanes):
            if ln["head_kind"] not in ("input", "flop") or len(ln["stages"]) < UNIT_MIN_DEPTH[ln["kind"]]:
                continue
            if j in continued:
                continue
            ctl = tuple(sg[0] for sg in ln["sigs"])
            uncond = not ln["cond"] and not any(pin[0] == "EN" for c in ctl for pin in c[1:])
            # reset values relative to the head's polarity (a lane from an inverted pin that resets
            # to 1 is a plain lane that resets to 0), as the recognizer's lane signature takes them
            inv = ln["head"] is not None and len(ln["head"]) > 3
            rel = tuple(tuple((k, {"0": "1", "1": "0"}.get(v, v) if inv else v) for k, v in sg[1]) for sg in ln["sigs"])
            key = (ln["kind"], len(ln["stages"]), ln["head_kind"], ctl, ln["cond"], rel if uncond else None)
            groups[key].append(j)
        for key in sorted(groups, key=repr):
            js = set(groups[key])
            while True:  # every lane of a member register must be in the group
                bad = {r for j in js for r in regs_of[j] if not lanes_of[r] <= js}
                keep = {j for j in js if not regs_of[j] & bad}
                if keep == js:
                    break
                js = keep
            regs = sorted(set().union(*(regs_of[j] for j in js))) if js else []
            if len(js) < 2 or len(regs) < 2:
                continue
            ln0 = lanes[min(js)]
            cond = " & ".join(("" if v else "!") + w.bitname(s) for s, v in sorted(key[4], key=repr))
            units.append({"rule": "copy_lanes", "kind": key[0], "registers": regs, "lanes": [lanes[j] for j in sorted(js)],
                          "detail": f"{len(js)} lanes of depth {key[1]} with "
                                    f"{'input-pin' if key[2] == 'input' else 'flop (other register)'} heads, "
                                    f"flop controls: {self._ctl_text(ln0['stages'][0])}"
                                    + (f"; copy mux condition {cond}" if cond else "")
                                    + ("; reset values relative to the head's polarity (inverted-pin heads)"
                                       if any(lanes[j]["head"] is not None and len(lanes[j]["head"]) > 3 for j in js)
                                       else "")})
        # rule concat_adder: counters written by disjoint aligned slices of one innermost adder
        by_adder = collections.defaultdict(dict)
        for n in sorted(n for n in kinds if n in w.regs and "counter" in accepts(n)):
            ff = {i for i, b in w.regs[n]["bits"].items() if b in w.ffbit}
            for cn, slots in self._adder_slots(n).items():
                if set(slots) == ff and len({o - i for i, o in slots.items()}) == 1:
                    by_adder[cn][n] = slots
        for cn in sorted(by_adder):
            regs = by_adder[cn]
            if len(regs) < 2:
                continue
            offs = [o for sl in regs.values() for o in sl.values()]
            if len(offs) != len(set(offs)):
                notes.append({"rule": "concat_adder", "registers": sorted(regs),
                              "left_out": "the registers take the same output bits of one adder (an incrementer "
                                          "shared between registers, not a concatenation)"})
                continue
            order = sorted((o, n, i) for n, sl in regs.items() for i, o in sl.items())
            members = list(dict.fromkeys(n for _o, n, _i in order))
            c = w.cells[cn]
            con = c["connections"]
            o0, n0, i0 = order[0]
            own = "A" if ("ff", w.regs[n0]["bits"][i0]) in w.mux_leaves(con["A"][o0]) else "B"
            other = con["B" if own == "A" else "A"]
            cv = _const_value(other)
            onebit = cv is None and all(isinstance(x, str) and x == "0" for x in other[1:])
            direction = None if (c["type"] == "$sub" and own == "B") else ("down" if c["type"] == "$sub" else "up")
            units.append({"rule": "concat_adder", "kind": "counter", "registers": members,
                          "bit_order": [(n, i) for _o, n, i in order], "direction": direction,
                          "step": cv if cv else (1 if onebit else None),
                          "detail": f"one {c['type'][1:]} ({_short_src(c['attributes'].get('src')) or 'no src'}) "
                                    "writes " + ", ".join(
                                        f"{n}[{max(regs[n])}:{min(regs[n])}] from its output bits "
                                        f"[{max(regs[n].values())}:{min(regs[n].values())}]" for n in members)})
        return units, notes


def _param_bit(v, off):
    """bit `off` of a Yosys JSON parameter (int, or binary string MSB first) as '0' / '1' / 'x'."""
    if isinstance(v, int):
        return str((v >> off) & 1)
    s = str(v)
    return s[len(s) - 1 - off] if off < len(s) else "0"


# minimum lane depth for a copy_lanes unit: the recognizer's structure definitions (S3_DESIGN
# section 1): a synchronizer is stages 1-2 of a copy path, a shift register has depth >= 3; shorter
# lanes are relations, never structures, so no merge of them can be credited
UNIT_MIN_DEPTH = {"synchronizer": 2, "shift_register": 3}
# lenient units declared by rule (review of 2026-09-22, generalisation, last minor issue): TEMPO's
# truth and the blind-set labels (tools/s3/thirdparty.py) apply the same rules through rule_units()
UNIT_RULES = {
    "sync_chain": "synchronizer stage registers forming chains: synchronizer registers linked by a stage-1 -> "
                  "stage-2 copy (a chain written as one RTL register per stage) form one unit of kind synchronizer "
                  "(a chain unit: score.py scores its stage registers strictly through it)",
    "copy_lanes": "equal-depth copy chains under one copy condition with heads of one external kind: lanes of "
                  "synchronizer registers (depth 2) or of shift registers (depth >= 3; every stage a single-path "
                  "copy of the previous one) of >= 2 registers, with equal depth, the same flop controls (clock, "
                  "enable, sync and async reset nets and polarities), the same copy mux condition, the same "
                  "per-stage reset values when the lanes copy unconditionally, and heads that are all input "
                  "pins or all flops of other registers, form one unit of the lanes' kind (per-channel histories; "
                  "S3's lane rule joins such lanes into one structure)",
    "concat_adder": "registers written by one concatenated adder: counters whose every bit is the aligned output of "
                    "disjoint slices of one innermost $add/$sub on their own Q ({hi, lo} <= {hi, lo} + 1) form one "
                    "unit of kind counter, bit order by adder output offset",
    "per_slice": "per-slice splits: the bits of one register under different flop controls (cell type, enable, "
                 "sync and async reset nets) form one unit per slice, of the register's kind (a control-signature "
                 "grouping splits the register there); TEMPO's truth only, not (yet) the blind-set labeller",
}


def _chain_source(cls, head):
    """a lane head as a ParamCheck.chain source: ('pi', port, i[, 'inv']) or ('reg', name, idx);
    None for a head that is neither."""
    if head is None:
        return None
    if head[0] == "pi":
        return tuple(head)
    if head[0] == "ff":
        return ("reg",) + tuple(cls._bkey(head[1]))
    return None


def rule_units(cls, kinds, flop_of, taken=(), accepts=None, per_slice=False):
    """The lenient units of UNIT_RULES as truth units [{name, kind, registers, reason, flops, params,
    rules}], with join keys from flop_of((register, index)) (None: the bit has no flop), and a
    report {rules, units, left_out}. `cls` is a Classifier; `kinds` and `accepts` as in
    Classifier.unit_facts. A unit equal (kind and flop set) to one in `taken` (truth units already
    declared, e.g. TEMPO's UNITS) or to an earlier rule unit is not repeated: that unit lists the
    rule in its "rules". A unit whose flops are one member register's flops adds nothing and is
    left out. Lanes that map to the same flops (RTL registers synthesis merged) appear once.
    per_slice: also the per-slice splits (UNIT_RULES["per_slice"]), which TEMPO's truth declares
    and the blind-set labeller does not (yet): a per-slice unit of a structure kind credits a
    structure that matches one slice (lenient), and one of a synchronizer register is a chain
    unit that score.py scores strictly; the lead decides whether third-party truths take it."""
    facts, notes = cls.unit_facts(kinds, accepts)
    out, report, left = [], [], list(notes)
    seen = {(u["kind"], frozenset(u.get("flops") or ())): u for u in taken}

    def src_key(head):
        if head is None:
            return None
        if head[0] == "pi":
            return f"port:{'~' if len(head) > 3 else ''}{head[1]}[{head[2]}]"
        if head[0] == "ff":
            return flop_of(cls._bkey(head[1]))
        return None

    def head_rank(head):  # lanes in input-pin order (port, index), then by the head register bit
        if head is None:
            return (2, "", 0)
        if head[0] == "pi":
            return (0, head[1], head[2], len(head))
        if head[0] == "ff":
            k = cls._bkey(head[1])
            return (1, k[0], k[1])
        return (2, repr(head), 0)

    for f in facts:
        if "lanes" in f:
            order, heads, lset = [], [], set()
            for ln in sorted(f["lanes"], key=lambda ln: (head_rank(ln["head"]), ln["keys"])):
                keys = [flop_of(k) for k in ln["keys"]]
                if None in keys:
                    order = None
                    break
                if tuple(keys) in lset:
                    continue
                lset.add(tuple(keys))
                order.append(keys)
                heads.append(src_key(ln["head"]))
            if order is None:
                left.append({"rule": f["rule"], "registers": f["registers"], "left_out": "a lane bit has no flop"})
                continue
            flops = list(dict.fromkeys(k for lane in order for k in lane))
            depth = max(len(l) for l in order)
            if f["kind"] == "synchronizer":
                params = {"stages": depth, "order": order}
            else:
                dirs = {ln.get("direction") for ln in f["lanes"]}
                params = {"lanes": len(order), "depth": depth, "direction": dirs.pop() if len(dirs) == 1 else None,
                          "serial_in": heads, "order": order}
        else:
            keys = [flop_of(k) for k in f["bit_order"]]
            if None in keys:
                left.append({"rule": f["rule"], "registers": f["registers"], "left_out": "a bit has no flop"})
                continue
            flops = list(dict.fromkeys(keys))
            params = {"direction": f["direction"], "step": f["step"], "modulus": None, "saturating": None,
                      "load": None, "bit_order": keys}
        rec = {"rule": f["rule"], "kind": f["kind"], "registers": f["registers"], "flops": len(flops),
               "detail": f["detail"]}
        member_flops = [{flop_of((r, i)) for i in cls.w.regs[r]["bits"]} - {None} for r in f["registers"]]
        if any(set(flops) == fl for fl in member_flops):
            left.append(dict(rec, left_out="the unit's flops are one member register's flops"))
            continue
        key = (f["kind"], frozenset(flops))
        if key in seen:
            prev = seen[key]
            prev.setdefault("rules", [])
            if f["rule"] not in prev["rules"]:
                prev["rules"].append(f["rule"])
            report.append(dict(rec, same_as=prev["name"]))
            continue
        regs = f["registers"]
        short = " + ".join(regs[:6]) + (f" + {len(regs) - 6} more" if len(regs) > 6 else "")
        u = {"name": f"{short} ({f['rule']})", "kind": f["kind"], "registers": list(regs),
             "reason": f"rule {f['rule']}: {f['detail']}. {UNIT_RULES[f['rule']]}", "flops": flops,
             "params": params, "rules": [f["rule"]],
             # RTL view for the caller's checks (popped before a truth is written): lanes as
             # [source, stage 0, stage 1, ...] in ParamCheck.chain's terms, or the bit order
             "_rtl": {"lanes": [[_chain_source(cls, ln["head"])] + list(ln["keys"]) for ln in f["lanes"]]}
             if "lanes" in f else {"bit_order": list(f["bit_order"])}}
        seen[key] = u
        out.append(u)
        report.append(dict(rec, added=u["name"]))
    # rule per_slice: the bits of one register under different flop controls, one unit per slice
    w = cls.w
    for name in sorted(kinds) if per_slice else ():
        if name not in w.regs:
            continue
        groups = collections.defaultdict(list)
        for idx, b in sorted(w.regs[name]["bits"].items()):
            if isinstance(b, str) or b not in w.ffbit or flop_of((name, idx)) is None:
                continue
            c = w.cells[w.ffbit[b][0]]
            sig = (c["type"],) + tuple((pn, tuple(c["connections"][pn]), str(c["parameters"].get(pn + "_POLARITY")))
                                       for pn in ("EN", "SRST", "ARST") if pn in c["connections"])
            groups[sig].append(idx)
        if len(groups) < 2:
            continue
        desc = []
        for sig, idx in sorted(groups.items(), key=lambda kv: min(kv[1])):
            ctl = [f"{pn} {w.bitname(bits[0])}" for pn, bits, _pol in sig[1:]]
            desc.append((idx, f"bits [{_index_ranges(idx)}]: {sig[0]}" + (" with " + ", ".join(ctl) if ctl else "")))
        for idx, _d in desc:
            u = {"name": f"{name}[{_index_ranges(idx)}]", "kind": kinds[name], "registers": [name],
                 "reason": "per-slice split: the register's bits sit under different controls, so a "
                           "control-signature grouping splits it here (" + "; ".join(d for _i, d in desc) + ")",
                 "flops": [flop_of((name, i)) for i in idx], "params": {}, "rules": ["per_slice"], "_rtl": {}}
            key = (u["kind"], frozenset(u["flops"]))
            if key in seen:
                seen[key].setdefault("rules", [])
                if "per_slice" not in seen[key]["rules"]:
                    seen[key]["rules"].append("per_slice")
                report.append({"rule": "per_slice", "kind": u["kind"], "registers": [name], "flops": len(idx),
                               "same_as": seen[key]["name"]})
                continue
            seen[key] = u
            out.append(u)
            report.append({"rule": "per_slice", "kind": u["kind"], "registers": [name], "flops": len(idx),
                           "added": u["name"]})
    return out, {"rules": dict(UNIT_RULES), "units": report, "left_out": left}


# ============================================================================ operators

def operators(word, register_names):
    """word-level operators with widths and the registers they feed (cell-level cones)."""
    w = word
    ops = {cn: c for cn, c in w.cells.items() if c["type"] in OPERATOR_TYPES}
    feeds = collections.defaultdict(set)
    to_out = set()
    ff_regs = collections.defaultdict(set)
    for q, rs in w.reg_of.items():
        for r, _i in rs:
            ff_regs[w.ffbit[q][0]].add(r)

    def backward(start_bits):
        seen, stack, found = set(), [b for b in start_bits if not isinstance(b, str)], set()
        while stack:
            b = stack.pop()
            d = w.driver.get(b)
            if d is None or d[0] == "PI" or d[0] in seen:
                continue
            c = w.cells[d[0]]
            if c["type"] in FF_TYPES:
                continue
            seen.add(d[0])
            if d[0] in ops:
                found.add(d[0])
            for pn, bs in c["connections"].items():
                if c.get("port_directions", {}).get(pn) == "input":
                    stack.extend(bs)
        return found

    for cn, c in w.cells.items():
        if c["type"] in FF_TYPES:
            ins = [b for p in ("D", "EN", "SRST", "ARST", "CE") for b in c["connections"].get(p, [])]
            for o in backward(ins):
                feeds[o] |= ff_regs.get(cn, set())
    sinks = [b for p in w.ports.values() if p["direction"] == "output" for b in p["bits"]]
    for cn, c in w.cells.items():
        if not c["type"].startswith("$"):
            sinks += [b for pn, bs in c["connections"].items()
                      if c.get("port_directions", {}).get(pn) == "input" for b in bs]
    to_out = backward(sinks)
    # XOR groups: XOR cells connected output -> input
    xcells = [cn for cn, c in ops.items() if c["type"] in XORS | {"$reduce_xor", "$reduce_xnor"}]
    parent = {cn: cn for cn in xcells}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for cn in xcells:
        for b in w.cells[cn]["connections"]["Y"]:
            for (u, _p, _o) in w.users.get(b, []):
                if u in parent:
                    parent[find(u)] = find(cn)
    groups, gid = {}, {}
    for cn in sorted(xcells):
        r = find(cn)
        gid[cn] = groups.setdefault(r, len(groups))
    def module(cn):
        if cn.startswith("$flatten"):
            return _module_of(cn)
        c = w.cells[cn]  # made by an optimization pass: take the scope of a connected public name
        dirs = c.get("port_directions", {})
        for want in ("output", "input"):
            for pn, bs in c["connections"].items():
                if dirs.get(pn) != want:
                    continue
                for b in bs:
                    for n, _i in w.names.get(b, []):
                        return _module_of(n)
        return TOP

    mods = {cn: module(cn) for cn in ops}
    out = []
    for cn in sorted(ops, key=lambda x: (mods[x], ops[x]["type"], x)):
        c = ops[cn]
        par, con = c["parameters"], c["connections"]
        widths = {p: len(con[p]) for p in ("A", "B", "S", "Y") if p in con}
        # Yosys auto names embed the source path ($ternary$/abs/path/tempo_top.v:177$1790): drop the directory
        e = {"cell": re.sub(r"\$/[^$]*/([^/$]+\.s?v:)", r"$\1", cn), "type": c["type"], "module": mods[cn],
             "src": _short_src(c["attributes"].get("src")), "widths": widths,
             "signed": bool(_pint(par.get("A_SIGNED", 0)) or _pint(par.get("B_SIGNED", 0)))}
        for p in ("A", "B"):
            if p in con and c["type"] not in ("$mux", "$pmux"):
                cv = _const_value(con[p])
                if cv is not None:
                    e["const_operand"] = {p: cv}
        if c["type"] in ("$mux", "$pmux"):
            e["select"] = w.signal(con["S"]) if len(con["S"]) <= 1 else f"{len(con['S'])} selects"
        e["feeds"] = sorted(feeds.get(cn, ()))
        e["feeds_outputs"] = cn in to_out
        if cn in gid:
            e["xor_group"] = gid[cn]
        out.append(e)
    return out


# ============================================================================ simulation

class Circuit:
    """single-output gates over integer net ids, evaluated bit-parallel on Python ints."""

    def __init__(self):
        self.idx, self.gates, self.driven = {}, [], set()

    def net(self, name):
        i = self.idx.get(name)
        if i is None:
            i = self.idx[name] = len(self.idx)
        return i

    def add(self, fn, ins, out):
        o = self.net(out)
        if o in self.driven:
            raise ValueError(f"net {out} has two drivers")
        self.driven.add(o)
        self.gates.append((fn, tuple(self.net(x) for x in ins), o))

    def order(self):
        users = collections.defaultdict(list)
        pending = []
        for gi, (_fn, ins, _o) in enumerate(self.gates):
            deps = {i for i in ins if i in self.driven}
            pending.append(len(deps))
            for i in deps:
                users[i].append(gi)
        ready = [gi for gi, p in enumerate(pending) if p == 0]
        out = []
        while ready:
            gi = ready.pop()
            out.append(self.gates[gi])
            for u in users[self.gates[gi][2]]:
                pending[u] -= 1
                if pending[u] == 0:
                    ready.append(u)
        if len(out) != len(self.gates):
            raise ValueError(f"combinational loop: {len(self.gates) - len(out)} gates unordered")
        self.ordered = out

    def run(self, leaves, M):
        v = [0] * len(self.idx)
        for i, x in leaves.items():
            v[i] = x
        for fn, ins, o in self.ordered:
            v[o] = fn(M, *[v[i] for i in ins])
        return v


_GATE = {
    "$_AND_": lambda M, a, b: a & b, "$_OR_": lambda M, a, b: a | b, "$_XOR_": lambda M, a, b: a ^ b,
    "$_NAND_": lambda M, a, b: M ^ (a & b), "$_NOR_": lambda M, a, b: M ^ (a | b),
    "$_XNOR_": lambda M, a, b: M ^ a ^ b, "$_ANDNOT_": lambda M, a, b: a & (M ^ b),
    "$_ORNOT_": lambda M, a, b: a | (M ^ b), "$_NOT_": lambda M, a: M ^ a, "$_BUF_": lambda M, a: a,
    "$_MUX_": lambda M, a, b, s: (a & (M ^ s)) | (b & s),
}
_GATE_PINS = {"$_NOT_": ("A",), "$_BUF_": ("A",), "$_MUX_": ("A", "B", "S")}


_FF_CELL = re.compile(r"^\$_(DFF|DFFE|DFFSR|DFFSRE|ALDFF|ALDFFE)_([NP]+)([01]?)([NP]?)_$")


def rtl_flop_type(t):
    """Yosys gate-level flop cell type -> {"clock": pos|neg, "async": None | "reset0" | "reset1" |
    "set_reset" | "load", "enable": bool, "pol": {control pin: "P"|"N"}}, or None when `t` is not
    a flop. Latches ($_DLATCH*), and cells dffunmap removes ($_SDFF*), are not flops here
    (RtlGates rejects them)."""
    m = _FF_CELL.match(t)
    if not m:
        return None
    base, pol, val, _epol = m.groups()
    ctl = {"C": pol[0]}
    if base == "DFF" and len(pol) == 1:
        asy = None
    elif base in ("DFF", "DFFE") and len(pol) >= 2 and val:
        asy, ctl["R"] = f"reset{val}", pol[1]
    elif base in ("DFFSR", "DFFSRE") and len(pol) >= 3:
        asy, ctl["S"], ctl["R"] = "set_reset", pol[1], pol[2]
    elif base in ("ALDFF", "ALDFFE") and len(pol) >= 2:
        asy, ctl["L"] = "load", pol[1]
    elif base == "DFFE" and len(pol) == 2 and not val:
        asy = None  # $_DFFE_PP_: clock and enable polarity
    else:
        return None
    return {"clock": "pos" if pol[0] == "P" else "neg", "async": asy, "enable": base.endswith("E"), "pol": ctl}


class RtlGates:
    """gates.json: the RTL as single-bit gates; flops are cut (Q leaves, D next state).

    Flops: every Yosys gate-level flop type ($_DFF_P_/N_, async reset/set $_DFF_PN0_ etc.,
    $_DFFSR_*, async-load $_ALDFF_*, and enable variants, whose enable becomes a hold mux). The
    next state is the synchronous one (D, or E ? D : Q); clock edge, async control and the nets on
    the clock and async pins are kept in `ff_type[key]` ("nets": {pin: circuit net}), which
    map_netlist compares with the netlist flop's. Latches are refused. A Q bit several tagged
    names share is keyed by the smallest (name, index), as Word does."""

    def __init__(self, path, top=None):
        with open(path) as f:
            m = json.load(f)["modules"][top or TOP]
        self.c = Circuit()
        self.ff = {}  # key (reg, idx) -> (qnet, dnet)
        self.ff_type = {}  # key -> rtl_flop_type()
        self.pi = {}  # (port, i) -> net
        self.sram = {}  # i -> net
        self.named = {}  # (wire, idx) -> net
        self.undriven = 0
        self.pubname = {}  # bit -> public "name[idx]"
        self.src = {}  # gate output bit -> src of the RTL cell it came from
        q2key = {}
        for n, w in m["netnames"].items():
            for idx, b in zip(_indices(w), w["bits"]):
                if not isinstance(b, str):
                    self.named[(n, idx)] = b
                    if len(w["bits"]) == 1:
                        self.named[(n, None)] = b
                    if not w["hide_name"] and "rtl_reg" in w["attributes"]:
                        q2key[b] = min(q2key.get(b, (n, idx)), (n, idx))
                    if not w["hide_name"]:
                        nm = n if len(w["bits"]) == 1 else f"{n}[{idx}]"
                        if b not in self.pubname or (nm.count("."), nm) < (self.pubname[b].count("."), self.pubname[b]):
                            self.pubname[b] = nm
        self.qkey = {q: k for q, k in q2key.items()}
        self.po = {}
        for pn, p in m["ports"].items():
            for i, b in enumerate(p["bits"]):
                if isinstance(b, str):
                    continue
                (self.pi if p["direction"] == "input" else self.po)[(pn, i)] = b
        for cn, cell in m["cells"].items():
            t, con = cell["type"], cell["connections"]
            if t == "$scopeinfo":
                continue
            ft = rtl_flop_type(t)
            if ft is not None:
                q, d = con["Q"][0], con["D"][0]
                key = q2key.get(q, ("?" + cn, 0))
                if ft["enable"]:  # next state = E ? D : Q (enable polarity is the type's last letter)
                    e = self._bit(con["E"][0])
                    nxt = ("next", cn)
                    if t[-2] == "P":
                        self.c.add(_GATE["$_MUX_"], [q, self._bit(d), e], nxt)
                    else:
                        self.c.add(_GATE["$_MUX_"], [self._bit(d), q, e], nxt)
                    d = nxt
                self.ff[key] = (q, d)
                self.ff_type[key] = dict(ft, nets={p: self._bit(con[p][0]) for p in ft["pol"]})
                continue
            if t.startswith(("$_DLATCH", "$_SR_")):
                raise ValueError(f"latch {t} ({cn}): a latch has no next-state function; not supported")
            if t == SRAM:
                for i, b in enumerate(con["A_DOUT"]):
                    self.sram[i] = b
                continue
            if t not in _GATE:
                raise ValueError(f"unexpected gate {t}")
            pins = _GATE_PINS.get(t, ("A", "B"))
            self.c.add(_GATE[t], [self._bit(con[p][0]) for p in pins], con["Y"][0])
            self.src[con["Y"][0]] = cell["attributes"].get("src")
        for b in list(self.named.values()) + list(self.pi.values()) + list(self.po.values()) + list(self.sram.values()):
            self.c.net(b)  # every net a caller may look up exists before the first run
        for q, d in self.ff.values():
            self.c.net(q)
            self.c.net(self._bit(d))
        for ft in self.ff_type.values():
            for b in ft["nets"].values():
                self.c.net(b)
        self.c.net(("const", "1"))
        self.c.order()

    def _bit(self, b):
        if isinstance(b, str):
            return ("const", b)
        return b

    def _ensure(self):
        if not hasattr(self, "_rev"):
            self._rev = {i: n for n, i in self.c.idx.items()}
            self._drv = {o: ins for _fn, ins, o in self.c.gates}

    def describe(self, net):
        """(name, public?) of circuit net index `net`: its public name, else its driver's RTL source."""
        self._ensure()
        b = self._rev.get(net)
        if b in self.pubname:
            return self.pubname[b], True
        return f"<internal signal, {_short_src(self.src.get(b)) or 'no src'}>", False

    def support(self, net):
        """RTL register bits and inputs in the combinational fan-in of circuit net index `net`."""
        self._ensure()
        seen, stack, keys, pis = set(), [net], set(), set()
        pi_nets = {self.c.idx[b]: k for k, b in self.pi.items()}
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            if x in self._drv:
                stack.extend(self._drv[x])
                continue
            b = self._rev.get(x)
            if b in self.qkey:
                keys.add(self.qkey[b])
            elif x in pi_nets:
                pis.add(pi_nets[x])
        return keys, pis


def _liberty(path):
    """{cell: {"out": {pin: function}, "seq": bool, "ff": None | {iq, iqn, clocked_on, next_state,
    clear, preset}}} from a Liberty file (functions and flip-flop groups only)."""
    cells, cell, pin, depth, pin_depth, ff_depth = {}, None, None, 0, None, None
    rx_cell = re.compile(r'^\s*cell\s*\(\s*"?([\w$]+)"?\s*\)')
    rx_pin = re.compile(r'^\s*pin\s*\(\s*"?([\w\[\]]+)"?\s*\)')
    rx_fn = re.compile(r'^\s*function\s*:\s*"([^"]*)"')
    rx_ff = re.compile(r'^\s*ff\s*\(\s*"?(\w+)"?\s*,\s*"?(\w+)"?\s*\)')
    rx_attr = re.compile(r'^\s*(clocked_on|next_state|clear|preset)\s*:\s*"([^"]*)"')
    with open(path) as f:
        for line in f:
            s = line.split("/*")[0]
            m = rx_cell.match(s)
            if m:
                cell = cells.setdefault(m.group(1), {"out": {}, "seq": False, "ff": None})
            elif cell is not None:
                if re.match(r"^\s*(ff|latch|statetable)\s*\(", s):
                    cell["seq"] = True
                m = rx_ff.match(s)
                if m:
                    cell["ff"], ff_depth = {"iq": m.group(1), "iqn": m.group(2)}, depth
                m = rx_attr.match(s)
                if m and ff_depth is not None and depth > ff_depth:
                    cell["ff"][m.group(1)] = m.group(2)
                m = rx_pin.match(s)
                if m:
                    pin, pin_depth = m.group(1), depth
                m = rx_fn.match(s)
                if m and pin:
                    cell["out"][pin] = m.group(1)
            depth += s.count("{") - s.count("}")
            if pin is not None and depth <= pin_depth:
                pin = None
            if ff_depth is not None and depth <= ff_depth:
                ff_depth = None
    return cells


def liberty_flop_type(ff):
    """a Liberty ff group -> {"clock": pos|neg, "clear": expr|None, "preset": expr|None}."""
    clk = (ff.get("clocked_on") or "").replace(" ", "")
    neg = clk.startswith("!") or clk.endswith("'")
    return {"clock": "neg" if neg else "pos", "clear": ff.get("clear"), "preset": ff.get("preset")}


def _compile(expr):
    """Liberty function string -> (lambda M, *pins, [pin names])."""
    toks = re.findall(r"[A-Za-z_]\w*|[01]|[!*&+|^()']", expr)
    pos, names = [0], []

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take():
        pos[0] += 1
        return toks[pos[0] - 1]

    def p_or():
        a = p_and()
        while peek() in ("+", "|"):
            take()
            a = f"({a} | {p_and()})"
        return a

    def p_and():
        a = p_xor()
        while peek() in ("*", "&") or (peek() is not None and peek() not in ("+", "|", ")", "^", "'")):
            if peek() in ("*", "&"):
                take()
            a = f"({a} & {p_xor()})"
        return a

    def p_xor():
        a = p_un()
        while peek() == "^":
            take()
            a = f"({a} ^ {p_un()})"
        return a

    def p_un():
        if peek() == "!":
            take()
            return f"(M ^ {p_un()})"
        t = take()
        if t == "(":
            e = p_or()
            take()
        elif t == "0":
            e = "0"
        elif t == "1":
            e = "M"
        else:
            if t not in names:
                names.append(t)
            e = f"p_{t}"
        while peek() == "'":
            take()
            e = f"(M ^ {e})"
        return e

    code = p_or()
    fn = eval(f"lambda M, {', '.join('p_' + n for n in names)}: {code}" if names else f"lambda M: {code}")
    return fn, names


def flop_controls(circ, inst, ff, net_of, compiled):
    """Clock edge and async controls of a netlist flop from its Liberty ff group: the clear and
    preset expressions become gates driving nets `<inst>$clear` / `<inst>$preset` (1 = the
    control is active), and the clock pin's net is registered as "clk", so a simulation can
    compare the effective clock and the async controls with the RTL flop's. `net_of(pin)` is the
    net on a pin (None if unconnected). Returns liberty_flop_type() with those nets."""
    ft = liberty_flop_type(ff or {})
    pins = re.findall(r"[A-Za-z_]\w*", (ff or {}).get("clocked_on") or "")
    ft["clk"] = net_of(pins[0]) if pins else None
    if ft["clk"] is not None:
        circ.net(ft["clk"])
    for a in ("clear", "preset"):
        expr, ft[a] = ft[a], None
        if not expr:
            continue
        if expr not in compiled:
            compiled[expr] = _compile(expr)
        fn, names = compiled[expr]
        nets = [net_of(n) for n in names]
        if all(x is not None for x in nets):
            ft[a] = f"{inst}${a}"
            circ.add(fn, nets, ft[a])
    return ft


def async_class(clear_live, preset_live):
    return {(False, False): None, (True, False): "reset0", (False, True): "reset1"}.get(
        (bool(clear_live), bool(preset_live)), "set_reset")


class NetlistSim:
    """nl.v as a Circuit with Liberty functions; flops cut (flop_type: clock edge and the nets of
    the async controls, see flop_controls)."""

    def __init__(self, insts, lef, lib_path):
        lib = _liberty(lib_path)
        compiled = {}
        self.c = Circuit()
        self.flops = {}  # inst -> (qnet, dnet)
        self.flop_type = {}  # inst -> flop_controls()
        self.sram = {}
        for iname, (master, conns) in insts.items():
            if master == SRAM:
                pins = lvs._expand_nl_pins(master, conns, lef)
                for i in range(32):
                    self.sram[i] = pins[f"A_DOUT[{i}]"]
                continue
            cm = lib.get(master)
            if cm is None:
                raise ValueError(f"no Liberty cell {master}")
            if cm["seq"]:
                self.flops[iname] = (conns["Q"], conns["D"])
                self.flop_type[iname] = flop_controls(self.c, iname, cm["ff"], conns.get, compiled)
                continue
            for pin, fexpr in cm["out"].items():
                if pin not in conns:
                    continue
                if fexpr not in compiled:
                    compiled[fexpr] = _compile(fexpr)
                fn, names = compiled[fexpr]
                self.c.add(fn, [conns[n] for n in names], conns[pin])
        for q, d in self.flops.values():
            self.c.net(q)
            self.c.net(d)
        for n in self.sram.values():
            self.c.net(n)
        self.c.order()


# ============================================================================ mapping

def _split(qnet):
    name = qnet.lstrip("\\").strip()
    m = re.match(r"^(.*)\[(\d+)\]$", name)
    return name, (m.group(1), int(m.group(2))) if m else None


def compare_constants(word):
    """[(register bit keys LSB first, [constants])]: every register slice the RTL compares with
    constants ($eq/$ne/... with one side all Q bits of one register, the other constant)."""
    groups = collections.defaultdict(set)
    for c in word.cells.values():
        if c["type"] not in CMP:
            continue
        a, b = c["connections"]["A"], c["connections"]["B"]
        for x, y in ((a, b), (b, a)):
            cv = _const_value(y)
            if cv is None or not x or any(isinstance(q, str) or q not in word.ffbit for q in x):
                continue
            keys = tuple(word.reg_of[q][0] for q in x if word.reg_of.get(q))
            if len(keys) == len(x) and len({k[0] for k in keys}) == 1 and len(keys) <= 16:
                groups[keys].add(cv & ((1 << len(keys)) - 1))
    return [(list(k), sorted(v)) for k, v in sorted(groups.items())]


def _pack(bits):
    """numpy 0/1 array (pattern j at index j) -> Python int with pattern j at bit j."""
    import numpy as np
    return int.from_bytes(np.packbits(bits.astype(np.uint8), bitorder="little").tobytes(), "little")


def load_fsm_encoding(path):
    """{state register: {one-hot bit index: old code}} from `fsm -encfile`, read MSB first."""
    out, cur = {}, None
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            t = line.split()
            if not t:
                continue
            if t[0] == ".fsm":
                cur = out.setdefault(t[2], {})
            elif t[0] == ".map" and cur is not None:
                old, new = t[1], t[2]
                if new.count("1") == 1:
                    cur[len(new) - 1 - new.index("1")] = int(old, 2)
    return out


def map_netlist(word, rtl, nlsim, insts, fsm_enc, npat, seed, log):
    """Resolve every netlist flop and every RTL register bit; check next-state functions.

    Returns (flop_rel, key_rel, check) where
      flop_rel[f] = ("bit", key, how) | ("fsm", reg, k) | ("dup", g) | ("comb", (wire, idx)) | ("unknown", why)
      key_rel[key] = ("flop", f) | ("merged", f) | ("unused",) | ("constant", v) | ("fsm",) | ("unresolved",)
    """
    rng = random.Random(seed)
    M = (1 << npat) - 1
    flops = sorted(nlsim.flops)
    rtl_keys = set(rtl.ff)
    # ---- name resolution
    flop_rel = {}
    for f in flops:
        q = nlsim.flops[f][0]
        full, split = _split(q)
        cands = ([split] if split else []) + [(full, None)]
        rel = None
        for base, idx in cands:
            if base in fsm_enc:
                rel = ("fsm", base, idx)
                break
            b = word.byname.get((base, idx))
            if b is None:
                continue
            if b in word.ffbit:
                # the canonical key of the Q bit (Word.reg_of sorted; RtlGates keys the flop alike),
                # also when Yosys merged several registers into it and the netlist names another
                keys = word.reg_of.get(b) or []
                if keys:
                    rel = ("bit", keys[0], "name" if any(k[0] == base for k in keys) else "alias")
                    break
            else:
                rb = rtl.named.get((base, idx))
                if rb is not None and rb in rtl.c.idx:
                    rel = ("comb", rtl.c.idx[rb], base if idx is None else f"{base}[{idx}]")
                    break
        flop_rel[f] = rel or ("unknown", "no RTL name on the Q net")
    # ---- random patterns; in ~7/8 of them the chip reset is held inactive
    quiet = rng.getrandbits(npat) | rng.getrandbits(npat) | rng.getrandbits(npat)
    P = {f: rng.getrandbits(npat) for f in flops}
    PI = {k: rng.getrandbits(npat) for k in rtl.pi}
    if ("rst_n", 0) in PI:
        PI[("rst_n", 0)] |= quiet
    SR = {i: rng.getrandbits(npat) for i in rtl.sram}
    # constant-biased patterns: in half of them, each register slice the RTL compares with
    # constants takes one of those constants (decodes such as cmd == WRITE_CSR && idx == SCRATCH
    # are otherwise almost never true on uniform random values)
    import numpy as np
    nrng = np.random.default_rng(seed)
    key2flop = {r[1]: f for f, r in flop_rel.items() if r[0] == "bit"}
    biased = 0
    for keys, consts in compare_constants(word):
        fl = [key2flop.get(k) for k in keys]
        if any(x is None for x in fl):
            continue
        sel = nrng.integers(0, 2, npat).astype(bool)
        pick = np.asarray(consts, dtype=np.int64)[nrng.integers(0, len(consts), npat)]
        smask = _pack(sel)
        for bit, f in enumerate(fl):
            P[f] = (P[f] & (M ^ smask)) | _pack(((pick >> bit) & 1).astype(bool) & sel)
        biased += 1
    # reset synchronizer output low in quiet patterns (rst = rst_sync[1] | ~rst_n)
    for f, r in flop_rel.items():
        if r[0] == "bit" and r[1] == ("rst_sync", 1):
            P[f] &= M ^ quiet
    # FSM state partition: each pattern holds one valid state of each recoded FSM
    fsm_masks = {}
    for reg, enc in fsm_enc.items():
        codes = sorted(set(enc.values()))
        pick = [rng.randrange(len(codes)) for _ in range(npat)]
        masks = {}
        for ci, code in enumerate(codes):
            masks[code] = int("".join("1" if pick[j] == ci else "0" for j in reversed(range(npat))), 2)
        fsm_masks[reg] = masks
    fsm_width = {reg: max(max(enc.values()).bit_length(), 1) for reg, enc in fsm_enc.items()}
    for reg in fsm_enc:
        fsm_width[reg] = max(fsm_width[reg], sum(1 for k in rtl_keys if k[0] == reg))
    key_rel = {}
    for k in rtl_keys:
        if k[0] in fsm_enc:
            key_rel[k] = ("fsm",)
    for f, r in flop_rel.items():
        if r[0] == "bit" and r[1] in rtl_keys:
            key_rel.setdefault(r[1], ("flop", f))
    KR = {k: rng.getrandbits(npat) for k in sorted(rtl_keys)}  # leaves for keys with no flop yet

    def rtl_leaves(state):
        L = {}
        for k, (qn, _dn) in rtl.ff.items():
            L[rtl.c.net(qn)] = state[k]
        for k, b in rtl.pi.items():
            L[rtl.c.net(b)] = PI[k]
        for i, b in rtl.sram.items():
            L[rtl.c.net(b)] = SR[i]
        L[rtl.c.net(("const", "1"))] = M
        return L

    def rtl_state():
        st = {}
        for k in rtl_keys:
            r = key_rel.get(k)
            if r is None:
                st[k] = KR[k]
            elif r[0] in ("flop", "merged"):
                st[k] = P[r[1]]
            elif r[0] == "constant":
                st[k] = r[1]
            elif r[0] == "fsm":
                masks = fsm_masks[k[0]]
                st[k] = 0
                for code, mk in masks.items():
                    if (code >> k[1]) & 1:
                        st[k] |= mk
            else:
                st[k] = KR[k]
        return st

    history, rejected = [], set()
    for rnd in range(8):
        st = rtl_state()
        V1 = rtl.c.run(rtl_leaves(st), M)
        NS = {k: V1[rtl.c.net(d)] if not isinstance(d, str) else (M if d == "1" else 0) for k, (_q, d) in rtl.ff.items()}
        V2 = rtl.c.run(rtl_leaves(NS), M)
        # netlist leaves
        Lq = {}
        for f in flops:
            r = flop_rel[f]
            if r[0] == "bit":
                val = st.get(r[1], P[f])
            elif r[0] == "fsm":
                code = fsm_enc[r[1]].get(r[2])
                val = fsm_masks[r[1]].get(code, 0)
            elif r[0] == "dup":
                val = None  # set below from the original
            elif r[0] == "comb":
                val = V1[r[1]]
            else:
                val = P[f]
            Lq[f] = val
        for f in flops:  # duplicates take their original's value
            if flop_rel[f][0] == "dup":
                Lq[f] = Lq[flop_rel[f][1]]
        L = {nlsim.c.net(nlsim.flops[f][0]): v for f, v in Lq.items()}
        for (pn, i), v in PI.items():
            net = pn if len([k for k in PI if k[0] == pn]) == 1 else f"{pn}[{i}]"
            if net in nlsim.c.idx:
                L[nlsim.c.net(net)] = v
        for i, v in SR.items():
            L[nlsim.c.net(nlsim.sram[i])] = v
        VN = nlsim.c.run(L, M)
        D = {f: VN[nlsim.c.net(nlsim.flops[f][1])] for f in flops}
        # expected D per flop
        exp = {}
        for f in flops:
            r = flop_rel[f]
            if r[0] == "bit" and r[1] in NS:
                exp[f] = NS[r[1]]
            elif r[0] == "fsm":
                code = fsm_enc[r[1]].get(r[2])
                e = M
                for bit in range(fsm_width[r[1]]):
                    kk = (r[1], bit)
                    if kk not in NS:
                        continue
                    e &= NS[kk] if (code >> bit) & 1 else (M ^ NS[kk])
                exp[f] = e
            elif r[0] == "dup":
                exp[f] = exp.get(r[1])
            elif r[0] == "comb":
                exp[f] = V2[r[1]]
        for f in flops:
            if flop_rel[f][0] == "dup":
                exp[f] = exp.get(flop_rel[f][1])
        changed = False
        # discovery: unknown flops -> duplicate of a known flop, or retimed RTL signal
        dsig = collections.defaultdict(list)
        for f in flops:
            if flop_rel[f][0] in ("bit", "fsm") and exp.get(f) == D[f]:
                dsig[D[f]].append(f)
        wsig = None
        for f in flops:
            r = flop_rel[f]
            if r[0] != "unknown" and not (r[0] == "comb" and exp.get(f) != D[f]):
                continue
            if D[f] in (0, M):
                flop_rel[f] = ("unknown", "next state constant in simulation")
                continue
            if D[f] in dsig:
                g = sorted(dsig[D[f]])[0]
                flop_rel[f] = ("dup", g)
                changed = True
                continue
            if wsig is None:  # every RTL net, one cycle ahead (leaves = next state)
                wsig = collections.defaultdict(list)
                for i, val in enumerate(V2):
                    if val not in (0, M):
                        wsig[val].append(i)
            hits = wsig.get(D[f], [])
            best = None
            for i in hits:
                keys, pis = rtl.support(i)
                if pis or not keys:
                    continue  # a retimed register is a function of registers only
                name, public = rtl.describe(i)
                rank = (not public, len(keys), name)
                if best is None or rank < best[0]:
                    best = (rank, i, name)
            if best and (r[0] != "comb" or r[1] != best[1]):
                flop_rel[f] = ("comb", best[1], best[2])
                changed = True
        # discovery: RTL bits without a flop -> constant / merged / unobservable
        nsig = collections.defaultdict(list)
        for f in flops:
            nsig[D[f]].append(f)
        same_reg = collections.defaultdict(list)
        for f in flops:
            if flop_rel[f][0] == "bit":
                same_reg[flop_rel[f][1][0]].append(f)
        pending = []
        for k in sorted(rtl_keys):
            r = key_rel.get(k)
            if r is not None and r[0] in ("flop", "fsm"):
                continue
            ns = NS[k]
            if r and ((r[0] == "merged" and ns == D[r[1]]) or (r[0] == "constant" and ns == r[1])):
                continue  # hypothesis confirmed
            if r and r[0] == "merged":
                rejected.add((k, r[1]))  # agreed only where the bit's own value did not matter
                key_rel.pop(k)
                changed = True
            if ns in (0, M):
                key_rel[k] = ("constant", ns)
                changed = True
            elif ns in nsig:
                f = sorted(nsig[ns], key=lambda g: (g not in same_reg.get(k[0], ()), g))[0]
                key_rel[k] = ("merged", f)
                changed |= r != ("merged", f)
            else:
                pending.append(k)
        if pending:
            # a merged bit that holds its value compares only where its next state does not
            # depend on its own (still unknown) value: flip all open bits and keep the patterns
            # where the next state stays put; confirm the hypothesis exactly in the next round
            st0, st1 = dict(st), dict(st)
            for k in pending:
                st0[k], st1[k] = 0, M
            W0, W1 = rtl.c.run(rtl_leaves(st0), M), rtl.c.run(rtl_leaves(st1), M)
            for k in pending:
                dn = rtl.c.net(rtl.ff[k][1])
                n0, indep = W0[dn], M ^ (W0[dn] ^ W1[dn])
                if bin(indep & quiet).count("1") >= 16:
                    cands = [f for f in flops if D[f] not in (0, M) and not ((D[f] ^ n0) & indep)
                             and (k, f) not in rejected]
                    if cands:
                        f = sorted(cands, key=lambda g: (g not in same_reg.get(k[0], ()), g))[0]
                        changed |= key_rel.get(k) != ("merged", f)
                        key_rel[k] = ("merged", f)
                        continue
                # observability: flip this bit alone; does any other next state or output change?
                stf = dict(st)
                stf[k] = st[k] ^ M
                Wf = rtl.c.run(rtl_leaves(stf), M)
                seen = [kk for kk, (_q, d2) in rtl.ff.items() if kk != k and not isinstance(d2, str)
                        and Wf[rtl.c.net(d2)] != V1[rtl.c.net(d2)]]
                seen += [po for po, b in rtl.po.items() if Wf[rtl.c.net(b)] != V1[rtl.c.net(b)]]
                new = ("unresolved", len(seen)) if seen else ("unobservable",)
                changed |= key_rel.get(k) != new
                key_rel[k] = new
        history.append(sum(1 for f in flops if exp.get(f) == D[f]))
        log(f"  simulation round {rnd + 1}: {history[-1]} of {len(flops)} flops agree")
        if not changed and rnd >= 1:
            break
    # final comparison and activity
    check = {}
    for f in flops:
        e = exp.get(f)
        if e is None:
            check[f] = "unchecked"
        else:
            check[f] = "match" if e == D[f] else "mismatch"
    idle = sorted(f for f in flops if check[f] == "match" and not ((D[f] ^ Lq[f]) & quiet))
    active = sum(1 for f in flops if check[f] == "match") - len(idle)
    # primary outputs of both models, same leaves (an RTL output never assigned is unspecified:
    # any netlist value refines it)
    unspecified = rtl_undriven_outputs(rtl)
    po_ok, po_bad = 0, []
    for (pn, i), b in sorted(rtl.po.items()):
        net = pn if sum(1 for k in rtl.po if k[0] == pn) == 1 else f"{pn}[{i}]"
        if net not in nlsim.c.idx or (pn, i) in unspecified:
            continue
        if VN[nlsim.c.idx[net]] == V1[rtl.c.net(b)]:
            po_ok += 1
        else:
            po_bad.append(net)
    # flop types: each netlist flop's effective clock (its clock pin's net, inverted for a
    # falling-edge cell) and its async clear / preset (active = 1) against the RTL flop it
    # implements, bit-parallel over the same patterns: an inverter on the clock of a rising-edge
    # cell implements a falling-edge RTL flop, a clock from another flop (a ripple divider) must
    # be the corresponding RTL flop's Q, an async control tied off must be inactive in the RTL
    ftype = {"compared": 0, "clock_mismatch": [], "async_mismatch": [], "netlist_cells": collections.Counter(),
             "netlist_clock_inverted": 0, "rtl": collections.Counter()}
    nl_types = getattr(nlsim, "flop_type", {})

    def rval(b):
        return V1[rtl.c.net(rtl._bit(b))]

    def nval(net):
        return VN[nlsim.c.idx[net]] if net is not None and net in nlsim.c.idx else 0

    for f in flops:
        r = flop_rel[f]
        g = r[1] if r[0] == "dup" else f
        rg = flop_rel[g]
        key = rg[1] if rg[0] == "bit" else ((rg[1], 0) if rg[0] == "fsm" else None)
        rt, nt = rtl.ff_type.get(key), nl_types.get(f)
        if rt is None or nt is None:
            continue
        ftype["compared"] += 1
        pol, nets = rt["pol"], rt["nets"]
        act = lambda p: rval(nets[p]) ^ (0 if pol[p] == "P" else M) if p in nets else 0  # noqa: E731
        n_clk = nval(nt["clk"]) ^ (M if nt["clock"] == "neg" else 0)
        if nt["clk"] is None or n_clk != act("C"):
            ftype["clock_mismatch"].append(f)
        elif nt["clock"] != rt["clock"]:
            ftype["netlist_clock_inverted"] += 1  # the other edge's cell on an inverted clock
        if rt["async"] == "load":  # an async load has no clear/preset equivalent to compare bitwise
            r_clear = r_preset = None
        else:
            r_clear = act("R") if rt["async"] in ("reset0", "set_reset") else 0
            r_preset = act("S") if rt["async"] == "set_reset" else (act("R") if rt["async"] == "reset1" else 0)
        if r_clear is not None and (nval(nt["clear"]) != r_clear or nval(nt["preset"]) != r_preset):
            ftype["async_mismatch"].append(f)
        ftype["netlist_cells"][f"{nt['clock']}edge cell/{async_class(nt['clear'], nt['preset']) or 'no async pin'}"] += 1
        ftype["rtl"][f"{rt['clock']}edge/{rt['async'] or 'no async'}"] += 1
    ftype = {k: (dict(sorted(v.items())) if isinstance(v, collections.Counter) else v) for k, v in ftype.items()}
    stats = {"method": "bit-parallel random simulation of both models cut at the flops (leaves: flop "
                       "outputs, input pins, SRAM read data); each netlist flop's D compared with the RTL "
                       "next-state function of the bit it implements; evidence, not a proof",
             "patterns": npat, "seed": seed, "reset_inactive_patterns": bin(quiet).count("1"),
             "constant_biased_slices": biased,
             "rounds": len(history), "agree_per_round": history,
             "flops_checked": sum(1 for v in check.values() if v != "unchecked"),
             "match": sum(1 for v in check.values() if v == "match"),
             "mismatch": sorted(f for f, v in check.items() if v == "mismatch"),
             "unchecked": sorted(f for f, v in check.items() if v == "unchecked"),
             "exercised": active, "not_exercised": idle,
             "exercised_note": "flops whose next state differs from their current value in at least one "
                               "pattern with reset inactive; the rest were compared on hold/reset behaviour only",
             "outputs_match": po_ok, "outputs_mismatch": po_bad,
             "outputs_unspecified_in_rtl": sorted(f"{k[0]}[{k[1]}]" for k in unspecified),
             "flop_types": ftype}
    return flop_rel, key_rel, check, stats


def rtl_undriven_outputs(rtl):
    """RTL output bits no gate, input, flop or macro drives (declared, never assigned)."""
    driven = {o for _fn, _ins, o in rtl.c.gates}
    driven |= {rtl.c.net(b) for b in list(rtl.pi.values()) + list(rtl.sram.values())}
    driven |= {rtl.c.net(q) for q, _d in rtl.ff.values()}
    return {k for k, b in rtl.po.items() if rtl.c.net(b) not in driven}


def _sym_run(circ, leaves, targets, one, zero):
    """evaluate the cone of `targets` symbolically (z3 1-bit bit-vectors); {net index: term}."""
    if not hasattr(circ, "_drv"):
        circ._drv = {o: ins for _fn, ins, o in circ.ordered}
    need, stack = set(), list(targets)
    while stack:
        x = stack.pop()
        if x in need:
            continue
        need.add(x)
        stack.extend(circ._drv.get(x, ()))
    val = dict(leaves)
    for fn, ins, o in circ.ordered:
        if o in need and o not in val:
            r = fn(one, *[val.get(i, zero) for i in ins])
            val[o] = (one if r else zero) if isinstance(r, int) else r
    return val


def _z3_verdict(z3, r):
    return "proven" if r == z3.unsat else "refuted" if r == z3.sat else "unknown"


def prove_mapping(rtl, nlsim, flop_rel, key_rel, fsm_enc, rlimit=Z3_RLIMIT, log=print):
    """z3: every netlist flop's D function equals the RTL next-state function of what it
    implements, for all values of the flops, inputs and SRAM read data, under the register
    correspondence found by map_netlist (and the FSM's valid-state invariant). Each check runs
    under z3's deterministic resource limit `rlimit` (per check; "unknown" when exceeded), never
    a wall-clock timeout. RTL outputs no logic drives are unspecified and left out (listed).
    Returns ({flop: proven|refuted|unknown|unchecked}, stats)."""
    import z3
    one, zero = z3.BitVecVal(1, 1), z3.BitVecVal(0, 1)
    flops = sorted(nlsim.flops)
    pi = {k: z3.BitVec(f"pi_{k[0]}_{k[1]}", 1) for k in rtl.pi}
    sram = {i: z3.BitVec(f"sram_{i}", 1) for i in rtl.sram}
    fvar = {f: z3.BitVec(f"q_{f}", 1) for f in flops}
    stbits = {}
    for reg in fsm_enc:
        for k in rtl.ff:
            if k[0] == reg:
                stbits[k] = z3.BitVec(f"st_{reg}_{k[1]}", 1)

    def rtl_leaf(k):
        r = key_rel.get(k)
        if r and r[0] in ("flop", "merged"):
            return fvar[r[1]]
        if r and r[0] == "constant":
            return one if r[1] else zero
        if k in stbits:
            return stbits[k]
        return z3.BitVec(f"r_{k[0]}_{k[1]}", 1)

    def leaves_rtl(state):
        L = {rtl.c.net(q): state[k] for k, (q, _d) in rtl.ff.items()}
        L.update({rtl.c.net(b): pi[k] for k, b in rtl.pi.items()})
        L.update({rtl.c.net(b): sram[i] for i, b in rtl.sram.items()})
        L[rtl.c.net(("const", "1"))] = one
        return L

    state = {k: rtl_leaf(k) for k in rtl.ff}
    Lr = leaves_rtl(state)
    comb_nets = [r[1] for r in flop_rel.values() if r[0] == "comb"]
    dnets = [rtl.c.net(d) for (_q, d) in rtl.ff.values() if not isinstance(d, str)]
    V1 = _sym_run(rtl.c, Lr, dnets + comb_nets + [rtl.c.net(b) for b in rtl.po.values()], one, zero)
    NS = {k: (V1[rtl.c.net(d)] if not isinstance(d, str) else (one if d == "1" else zero))
          for k, (_q, d) in rtl.ff.items()}
    V2 = _sym_run(rtl.c, leaves_rtl(NS), comb_nets, one, zero) if comb_nets else {}

    def st_code(reg, sv):
        bits = [sv[(reg, b)] for b in range(max(k[1] for k in stbits if k[0] == reg) + 1)]
        return z3.Concat(*reversed(bits)) if len(bits) > 1 else bits[0]

    # netlist leaves
    Ln = {}
    for f in flops:
        r = flop_rel[f]
        q = nlsim.c.net(nlsim.flops[f][0])
        if r[0] == "bit":
            Ln[q] = state.get(r[1], fvar[f])
        elif r[0] == "fsm":
            w = st_code(r[1], state)
            Ln[q] = z3.If(w == fsm_enc[r[1]][r[2]], one, zero)
        elif r[0] == "comb":
            Ln[q] = V1[r[1]]
        else:
            Ln[q] = fvar[f]
    for f in flops:
        r = flop_rel[f]
        if r[0] == "dup":
            Ln[nlsim.c.net(nlsim.flops[f][0])] = Ln[nlsim.c.net(nlsim.flops[r[1]][0])]
    npi = collections.Counter(k[0] for k in rtl.pi)
    for k, v in pi.items():
        net = k[0] if npi[k[0]] == 1 else f"{k[0]}[{k[1]}]"
        if net in nlsim.c.idx:
            Ln[nlsim.c.idx[net]] = v
    for i, v in sram.items():
        Ln[nlsim.c.net(nlsim.sram[i])] = v
    npo = collections.Counter(k[0] for k in rtl.po)
    unspecified = rtl_undriven_outputs(rtl)
    po_nets = {k: (k[0] if npo[k[0]] == 1 else f"{k[0]}[{k[1]}]") for k in rtl.po if k not in unspecified}
    VN = _sym_run(nlsim.c, Ln, [nlsim.c.net(nlsim.flops[f][1]) for f in flops]
                  + [nlsim.c.idx[n] for n in po_nets.values() if n in nlsim.c.idx], one, zero)

    def expected(f):
        r = flop_rel[f]
        if r[0] == "bit":
            return NS.get(r[1])
        if r[0] == "fsm":
            return z3.If(st_code(r[1], NS) == fsm_enc[r[1]][r[2]], one, zero)
        if r[0] == "dup":
            return expected(r[1])
        if r[0] == "comb":
            return V2[r[1]]
        return None

    base = []
    for reg, enc in fsm_enc.items():  # reachable-state invariant of the recoded FSM
        w = st_code(reg, state)
        base.append(z3.Or(*[w == c for c in sorted(set(enc.values()))]))

    def fresh():
        sv = z3.SolverFor("QF_BV")
        sv.set("rlimit", rlimit)
        sv.add(*base)
        return sv

    def count(sv):
        st = sv.statistics()
        return st.get_key_value("rlimit count") if "rlimit count" in st.keys() else 0

    s = fresh()
    used = []  # rlimit units per check (z3 counts resources cumulatively)
    spurious = []  # "sat" answers whose model does not satisfy the query (seen after a check hit the limit)

    def check(neg):
        """proven | refuted | unknown. A refutation must come with a model that satisfies the
        query; a check that hits the limit leaves z3's incremental state behind, so the solver is
        rebuilt after every unknown."""
        nonlocal s
        before = count(s)
        s.push()
        s.add(neg)
        v = _z3_verdict(z3, s.check())
        if v == "refuted" and not z3.is_true(s.model().eval(z3.And(*base, neg), model_completion=True)):
            v = "unknown"
            spurious.append(str(neg)[:80])
        s.pop()
        used.append(count(s) - before)
        if v == "unknown":
            s = fresh()
        return v

    result, t0 = {}, time.time()
    for n, f in enumerate(flops):
        e = expected(f)
        if e is None:
            result[f] = "unchecked"
            continue
        result[f] = check(VN[nlsim.c.net(nlsim.flops[f][1])] != e)
        if (n + 1) % 500 == 0:
            log(f"  z3: {n + 1} of {len(flops)} flops, {time.time() - t0:.0f} s")
    po, po_bad = collections.Counter(), []
    for k, net in sorted(po_nets.items()):
        if net not in nlsim.c.idx:
            po["not in the netlist"] += 1
            po_bad.append(net)
            continue
        v = check(VN[nlsim.c.idx[net]] != V1[rtl.c.net(rtl.po[k])])
        po[v] += 1
        if v != "proven":
            po_bad.append(net)
    # the invariants assumed above are preserved: a merged RTL bit's next state is its shared
    # flop's D, a constant bit stays constant, the recoded FSM's next state is a valid code
    inv, inv_bad = collections.Counter(), []
    obligations = []
    for k, r in sorted(key_rel.items()):
        if r[0] == "merged":
            obligations.append((f"merged {k[0]}[{k[1]}]", NS[k] != VN[nlsim.c.net(nlsim.flops[r[1]][1])]))
        elif r[0] == "constant":
            obligations.append((f"constant {k[0]}[{k[1]}]", NS[k] != (one if r[1] else zero)))
    for reg, enc in fsm_enc.items():
        w = st_code(reg, NS)
        obligations.append((f"fsm {reg} valid", z3.Not(z3.Or(*[w == c for c in sorted(set(enc.values()))]))))
    for name, neg in obligations:
        v = check(neg)
        inv[v] += 1
        if v != "proven":
            inv_bad.append(name)
    c = collections.Counter(result.values())
    stats = {"method": "z3 (QF_BV) combinational equivalence per flop: netlist D (Liberty functions) vs RTL "
                       "next state (gates.json), flops cut, leaves shared through the correspondence; FSM "
                       "one-hot flops constrained to the RTL's valid state codes",
             "z3": z3.get_version_string(), "rlimit_per_check": rlimit, "spurious_sat": len(spurious),
             "rlimit_max_per_check": max(used) if used else 0, "rlimit_total": sum(used),
             "seconds": round(time.time() - t0, 1),
             "proven": c.get("proven", 0), "refuted": sorted(f for f, v in result.items() if v == "refuted"),
             "unknown": sorted(f for f, v in result.items() if v == "unknown"),
             "unchecked": sorted(f for f, v in result.items() if v == "unchecked"),
             "outputs": dict(sorted(po.items())), "outputs_not_proven": po_bad,
             "outputs_unspecified_in_rtl": sorted(f"{k[0]}[{k[1]}]" for k in unspecified),
             "invariants": dict(sorted(inv.items())), "invariants_not_proven": inv_bad,
             "note": "all flops, outputs and invariants proven = an inductive register correspondence: "
                     "once the chip has been reset (every register but rst_sync has a synchronous reset), "
                     "the netlist and the RTL stay in corresponding states"}
    return result, stats


def proof_complete(pstats):
    """[] when every flop, output and invariant is proven, else what is not."""
    bad = []
    if pstats.get("skipped"):
        return ["proof skipped (--no-prove)"]
    for k in ("refuted", "unknown", "unchecked"):
        if pstats.get(k):
            bad.append(f"{len(pstats[k])} flops {k}: {pstats[k][:5]}")
    if pstats.get("outputs_not_proven"):
        bad.append(f"outputs not proven: {pstats['outputs_not_proven'][:8]}")
    if pstats.get("invariants_not_proven"):
        bad.append(f"invariants not proven: {pstats['invariants_not_proven'][:8]}")
    return bad


# ============================================================================ RTL hierarchy

class RtlHierarchy:
    """Module definitions and instances parsed from the RTL sources: which module declares a
    register (module_def) and its name local to that module (for design_key)."""

    def __init__(self, files):
        self.modules = {}  # name -> (file basename, first line, last line)
        self.insts = collections.defaultdict(dict)  # module -> {instance: child module}
        texts = {}
        for path in files:
            with open(path) as f:
                raw = f.read()
            # blank comments but keep line numbers
            text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), raw, flags=re.S)
            text = re.sub(r"//[^\n]*", "", text)
            texts[path] = text
            for m in re.finditer(r"\bmodule\s+(\w+)", text):
                end = text.find("endmodule", m.end())
                self.modules[m.group(1)] = (os.path.basename(path), text.count("\n", 0, m.start()) + 1,
                                            text.count("\n", 0, end) + 1, text[m.end():end])
        names = sorted(self.modules, key=len, reverse=True)
        for mod, (_fn, _a, _b, body) in self.modules.items():
            for child in names:
                for m in re.finditer(r"\b" + re.escape(child) + r"\b\s*(?:#\s*\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\))?"
                                     r"\s*(\w+)\s*\(", body):
                    self.insts[mod][m.group(1)] = child

    def split(self, name, top):
        """'u_top.u_ser.u_ser0.frac_q' -> ('tempo_ser', 'frac_q')."""
        mod, parts = top, name.split(".")
        while len(parts) > 1 and parts[0] in self.insts.get(mod, {}):
            mod = self.insts[mod][parts[0]]
            parts = parts[1:]
        return mod, ".".join(parts)

    def module_at(self, src):
        """'tempo_ser.v:85' -> the module whose text contains that line."""
        m = re.match(r"(.+):(\d+)$", src or "")
        if not m:
            return None
        for mod, (fn, a, b, _body) in self.modules.items():
            if fn == m.group(1) and a <= int(m.group(2)) <= b:
                return mod
        return None


def design_key(module_def, local):
    return module_def + ":" + re.sub(r"\[\d+\]", "[*]", local)


# ============================================================================ truth/2 rules on registers and units

def accepted_kinds(r, flop):
    """Kinds register dict `r` accepts at its flop: kind plus alt_kinds, or plus the bit's own
    alt_kinds where the bit carries them (they override the register's)."""
    for b in r["bits"]:
        if b.get("flop") == flop and b.get("alt_kinds") is not None:
            return {r["kind"]} | set(b["alt_kinds"])
    return {r["kind"]} | set(r.get("alt_kinds") or [])


def flop_primaries(registers):
    """{join key: primary register}: the widest register using the flop as a bit (ties by name).
    Shadow flops are no register's bits and have no entry."""
    users = collections.defaultdict(set)
    for r in registers:
        for b in r["bits"]:
            if b.get("flop"):
                users[b["flop"]].add(r["name"])
    width = {r["name"]: r.get("width") or len(r["bits"]) for r in registers}
    return {f: min(ns, key=lambda n: (-width[n], n)) for f, ns in users.items()}


def add_alias_members(registers, units):
    """A register that is primary for none of its flops (synthesis merged it into another
    register's flops, e.g. TEMPO's sck_meta = ui_sync0[0]) can never be matched by a natural
    structure on its own, so it becomes a member of every declared unit whose flops cover its
    flops and whose kind it accepts at each of them (units are changed in place). Returns
    ([{unit, register} added], [such registers no unit covers])."""
    prim = flop_primaries(registers)
    added, uncovered = [], []
    for r in registers:
        fl = {b["flop"] for b in r["bits"] if b.get("flop")}
        if not fl or any(prim[f] == r["name"] for f in fl):
            continue
        covered = False
        for u in units:
            if not fl <= set(u.get("flops") or ()) or not all(u["kind"] in accepted_kinds(r, f) for f in fl):
                continue
            covered = True
            if r["name"] not in u["registers"]:
                u["registers"].append(r["name"])
                added.append({"unit": u["name"], "register": r["name"]})
        if not covered:
            uncovered.append(r["name"])
    return added, uncovered


def mark_unit_stages(registers, units):
    """{register: [{unit, stage}]} for every synchronizer register whose flops all sit at one stage
    of a declared synchronizer unit's lanes (params.order): such a register is one stage of the
    unit and carries no stage-level params (schema.py)."""
    by_name = {r["name"]: r for r in registers}
    out = collections.defaultdict(list)
    for u in units:
        order = (u.get("params") or {}).get("order")
        if u["kind"] != "synchronizer" or not order:
            continue
        pos = {k: s for lane in order for s, k in enumerate(lane)}
        for rn in u["registers"]:
            r = by_name[rn]
            st = {pos.get(b["flop"]) for b in r["bits"] if b.get("flop")}
            if r["kind"] == "synchronizer" and len(st) == 1 and None not in st:
                out[rn].append({"unit": u["name"], "stage": st.pop()})
    return dict(out)


# ============================================================================ parameter checks

def _popcount(x):
    return bin(x).count("1")


def _lanes(x, n):
    """Python int -> numpy uint8 array of its n low bits (lane j = bit j)."""
    import numpy as np
    b = np.frombuffer(x.to_bytes((n + 7) // 8, "little"), dtype=np.uint8)
    return np.unpackbits(b, bitorder="little")[:n]


class ParamCheck:
    """Bit-parallel simulation of the RTL gate model (gates.json; step 3 proves it equal to the
    netlist flop by flop) to check the stated structure parameters. Patterns are random, with the
    register slices the RTL compares with constants biased to those constants (3 in 4 patterns),
    and the chip reset inactive unless a check says otherwise. Deterministic for a given seed."""

    ROUNDS = 12      # base pattern sets searched for counter contexts
    CONTEXTS = 8     # contexts replicated over the value range per counter direction

    def __init__(self, word, rtl, npat, seed):
        import numpy as np
        self.np = np
        self.w, self.rtl, self.npat, self.seed = word, rtl, npat, seed
        self.M = (1 << npat) - 1
        self.d_of_q = {q: d for q, d in rtl.ff.values()}
        self.drv = {o: ins for _fn, ins, o in rtl.c.ordered}
        self._cones, self._base = {}, {}
        self.const_slices = compare_constants(word)

    # ---- nets
    def width(self, name):
        return len(self.w.regs[name]["bits"]) if name in self.w.regs else \
            sum(1 for k in self.rtl.named if k[0] == name and k[1] is not None)

    def qnet(self, name, idx):
        return self.rtl.c.idx[self.rtl.named[(name, idx)]]

    def dnet(self, name, idx):
        d = self.d_of_q[self.rtl.named[(name, idx)]]
        return self.rtl.c.net(self.rtl._bit(d))

    def pinet(self, port, i):
        return self.rtl.c.net(self.rtl.pi[(port, i)])

    def src_net(self, src):
        """(net, inverted) of a chain source: ('pi', port, i[, 'inv']) or ('reg', name, idx)."""
        if src[0] == "pi":
            return self.pinet(src[1], src[2]), len(src) > 3 and src[3] == "inv"
        return self.qnet(src[1], src[2]), False

    # ---- patterns
    def base(self, k):
        """k-th base pattern set {leaf net: int}; the reset is left random here."""
        if k in self._base:
            return self._base[k]
        np, n, rtl = self.np, self.npat, self.rtl
        s = self.seed + 7919 * (k + 1)
        rng, nrng = random.Random(s), np.random.default_rng(s)
        L = {}
        for key in sorted(rtl.ff):
            L[rtl.c.net(rtl.ff[key][0])] = rng.getrandbits(n)
        for key in sorted(rtl.pi):
            L[rtl.c.net(rtl.pi[key])] = rng.getrandbits(n)
        for i in sorted(rtl.sram):
            L[rtl.c.net(rtl.sram[i])] = rng.getrandbits(n)
        for keys, consts in self.const_slices:
            try:
                nets = [self.qnet(*kk) for kk in keys]
            except KeyError:
                continue
            sel = nrng.random(n) < 0.75
            pick = np.asarray(consts, dtype=np.int64)[nrng.integers(0, len(consts), n)]
            smask = _pack(sel)
            for bit, net in enumerate(nets):
                L[net] = (L[net] & (self.M ^ smask)) | _pack(((pick >> bit) & 1).astype(bool) & sel)
        L[rtl.c.net(("const", "1"))] = self.M
        self._base[k] = L
        return L

    def forced(self, L, force, k=0, reset_inactive=True):
        """copy of L with registers pinned: {reg name: value or [values]} (a list spreads the
        values over the patterns); ports as 'pi:<port>'."""
        np, n = self.np, self.npat
        L = dict(L)
        force = dict(force or {})
        if reset_inactive:
            L[self.qnet("rst_sync", 1)] = 0
            L[self.pinet("rst_n", 0)] = self.M
        nrng = np.random.default_rng(self.seed + 104729 * (k + 1))
        for name, val in sorted(force.items()):
            if val is None:
                continue
            if name.startswith("pi:"):
                port = name[3:]
                nets = [self.pinet(port, i) for i in range(sum(1 for kk in self.rtl.pi if kk[0] == port))]
            else:
                nets = [self.qnet(name, i) for i in range(self.width(name))]
            vals = np.asarray(val if isinstance(val, list) else [val], dtype=np.int64)
            pick = vals[nrng.integers(0, len(vals), n)]
            for bit, net in enumerate(nets):
                L[net] = _pack(((pick >> bit) & 1).astype(bool))
        return L

    def cone(self, targets):
        key = tuple(sorted(set(targets)))
        if key not in self._cones:
            need, stack = set(), list(key)
            while stack:
                x = stack.pop()
                if x in need:
                    continue
                need.add(x)
                stack.extend(self.drv.get(x, ()))
            self._cones[key] = ([g for g in self.rtl.c.ordered if g[2] in need],
                                sorted(x for x in need if x not in self.drv), need)
        return self._cones[key]

    def run(self, targets, L, M=None, cut=()):
        """evaluate the cone of `targets`; nets in `cut` keep their value from L."""
        M = self.M if M is None else M
        gates, _leaves, _need = self.cone(targets)
        v = dict(L)
        cut = set(cut)
        for fn, ins, o in gates:
            if o not in cut:
                v[o] = fn(M, *[v.get(i, 0) for i in ins])
        return v

    def word_values(self, V, nets, n=None):
        """per-lane integer values of a word whose bits (LSB first) are `nets`."""
        np = self.np
        n = self.npat if n is None else n
        out = np.zeros(n, dtype=np.uint64)
        for b, net in enumerate(nets):
            out |= _lanes(V.get(net, 0), n).astype(np.uint64) << np.uint64(b)
        return out

    # ---- copy chains: shift lanes and synchronizer stages
    def chain(self, lanes, force=None, reset_inactive=True):
        """every lane [source, stage 0, stage 1, ...]: D(stage 0) = source, D(stage k) = Q(stage k-1)
        in every pattern, and every D flips when all sources flip together."""
        L = self.forced(self.base(0), force, 0, reset_inactive)
        dests = [self.dnet(*st) for lane in lanes for st in lane[1:]]
        V = self.run(dests, L)
        srcs, bad = [], 0
        for lane in lanes:
            net, inv = self.src_net(lane[0])
            prev = L.get(net, 0) ^ (self.M if inv else 0)
            srcs.append(net)
            for st in lane[1:]:
                bad |= V[self.dnet(*st)] ^ prev
                prev = L[self.qnet(*st)]
                srcs.append(self.qnet(*st))
            srcs.pop()  # the last stage feeds nothing in the chain
        L2 = dict(L)
        for net in set(srcs):
            L2[net] = L.get(net, 0) ^ self.M
        V2 = self.run(dests, L2)
        flip_bad = 0
        for d in dests:
            flip_bad |= V2[d] ^ V[d] ^ self.M
        return {"method": "copy chain", "patterns": self.npat, "copy_mismatches": _popcount(bad),
                "flip_mismatches": _popcount(flip_bad), "ok": bad == 0 and flip_bad == 0}

    def with_cut(self, L, cut, k):
        """L plus random values on the 1-bit nets in `cut` (module ports driven directly)."""
        if not cut:
            return L
        L = dict(L)
        rng = random.Random(self.seed + 15485863 * (k + 1))
        for net in cut:
            L[net] = rng.getrandbits(self.npat)
        return L

    # ---- counters: per-transition labelling in found contexts
    def counter(self, name, width, claim):
        np = self.np
        qn = [self.qnet(name, i) for i in range(width)]
        dn = [self.dnet(name, i) for i in range(width)]
        inst = name.rsplit(".", 1)[0]
        force = {(f"{inst}.{r}" if "." not in r else r): v for r, v in (claim.get("force") or {}).items()}
        cut = [self.rtl.c.idx[self.rtl.named[(f"{inst}.{p}", 0)]] for p in claim.get("cut", ())]
        mask = (1 << width) - 1
        step = claim["step"]
        out = {"method": "per-transition labelling: contexts where one plain step matches the claim, then "
                         "the whole table T_x(v) over the value range", "force": force or None,
               "ports_driven_at_random": [f"{inst}.{p}" for p in claim.get("cut", ())] or None}
        dirs = ["up", "down"] if claim["direction"] == "updown" else [claim["direction"]]
        # A data or relative load can reproduce a whole table v -> v + c (pc + 1 + off with off = 1
        # is a step of 2), so for loadable counters the claimed step(s) must also be the most
        # frequent change d - v (mod 2^w) over all patterns where the register changes to a
        # non-zero value (clears and wraps to 0 excluded; loads spread thin). Constant loads skew
        # this histogram under the constant bias (bw: 3 -> 1), so it gates loadable counters only.
        hist = collections.Counter()
        for k in range(self.ROUNDS // 2):
            L = self.with_cut(self.forced(self.base(k), force, k), cut, k)
            V = self.run(dn, L, cut=cut)
            v = self.word_values(L, qn).astype(np.int64)
            d = self.word_values(V, dn).astype(np.int64)
            sel = (d != v) & (d != 0)
            hist.update(((d[sel] - v[sel]) % (1 << width)).tolist())
        top = [c for c, _n in sorted(hist.items(), key=lambda kv: (-kv[1], kv[0]))[:len(dirs)]]
        want_steps = sorted((step if dd == "up" else -step) % (1 << width) for dd in dirs)
        out["most_frequent_changes"] = [[int(c), int(hist[c])] for c, _n in
                                        sorted(hist.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
        out["claimed_step_is_most_frequent"] = sorted(top) == want_steps
        ok_all = out["claimed_step_is_most_frequent"] or not claim.get("load")
        for direction in dirs:
            sgn = 1 if direction == "up" else -1
            M = claim.get("modulus")
            if M:
                lo, hi = 0, M - 1
                f = lambda v, M=M, sgn=sgn: ((v.astype(np.int64) + sgn * step) % M).astype(np.uint64)  # noqa: E731
                model = f"{direction} {step} mod {M}"
            elif claim.get("saturating"):
                lo, hi = claim["bounds"]
                f = (lambda v, hi=hi: np.minimum(v + step, hi)) if sgn > 0 else \
                    (lambda v, lo=lo: np.maximum(v.astype(np.int64) - step, lo).astype(np.uint64))  # noqa: E731
                model = f"{direction} {step} saturating at {hi if sgn > 0 else lo}"
            else:
                lo, hi = claim.get("domain") or ((0, mask - step) if sgn > 0 else (step, mask))
                f = lambda v, sgn=sgn: (v.astype(np.int64) + sgn * step).astype(np.uint64)  # noqa: E731
                model = f"{direction} {step} on {lo}..{hi}"
            ctx = []
            for k in range(self.ROUNDS):
                L = self.with_cut(self.forced(self.base(k), force, k), cut, k)
                V = self.run(dn, L, cut=cut)
                v = self.word_values(L, qn)
                d = self.word_values(V, dn)
                plain = v.astype(np.int64) + sgn * step  # a step that neither wraps nor saturates
                cand = np.nonzero((v >= lo) & (v <= hi) & (plain >= lo) & (plain <= hi)
                                  & (d.astype(np.int64) == plain))[0]
                need = self.CONTEXTS - len(ctx)
                if len(cand):
                    pick = cand[np.linspace(0, len(cand) - 1, min(need, len(cand))).astype(int)]
                    ctx += [(k, int(x)) for x in pick]
                if len(ctx) >= self.CONTEXTS:
                    break
            # replicate each context over the value range
            vals = list(range(lo, hi + 1)) if hi - lo < 4096 else sorted(
                {lo, hi, lo + 1, hi - 1} | {(1 << b) - 1 for b in range(1, width + 1) if lo <= (1 << b) - 1 <= hi}
                | set(random.Random(self.seed).sample(range(lo, hi + 1), 250)))
            W = len(vals)
            passed = 0
            for k in sorted({c[0] for c in ctx}):
                lanes = [c[1] for c in ctx if c[0] == k]
                L = self.with_cut(self.forced(self.base(k), force, k), cut, k)
                _g, leaves, _n = self.cone(dn)
                block = (1 << W) - 1
                R = {}
                for net in list(leaves) + cut:
                    x = L.get(net, 0)
                    R[net] = sum(block << (c * W) for c, ln in enumerate(lanes) if (x >> ln) & 1)
                n2 = W * len(lanes)
                for b, net in enumerate(qn):
                    pb = sum(((vv >> b) & 1) << j for j, vv in enumerate(vals))
                    R[net] = sum(pb << (c * W) for c in range(len(lanes)))
                V = self.run(dn, R, M=(1 << n2) - 1, cut=cut)
                d = self.word_values(V, dn, n2).reshape(len(lanes), W)
                want = np.asarray(f(np.asarray(vals, dtype=np.uint64)), dtype=np.uint64) & np.uint64(mask)
                passed += int(np.sum(np.all(d == want[None, :], axis=1)))
            out[direction] = {"model": model, "contexts": len(ctx), "contexts_matching_whole_table": passed,
                              "values_per_context": W}
            ok_all &= passed > 0
        out["ok"] = bool(ok_all)
        return out

    # ---- CRC: module ports driven at random
    def crc(self, inst):
        np, n = self.np, self.npat
        crc = [self.qnet(f"{inst}.crc_l", i) for i in range(32)]
        dn = [self.dnet(f"{inst}.crc_l", i) for i in range(32)]
        poly = [self.qnet(f"{inst}.poly_l", i) for i in range(32)]
        port = lambda p, i: self.rtl.c.idx[self.rtl.named[(f"{inst}.{p}", i)]]  # noqa: E731
        fwe, iwe = port("feed_we", 0), port("init_we", 0)
        fn_ = [port("feed_n", i) for i in range(4)]
        fb_ = [port("feed_bits", i) for i in range(8)]
        wd_ = [port("wdata", i) for i in range(32)]
        cut = [fwe, iwe] + fn_ + fb_ + wd_
        _g, _l, need = self.cone(dn)
        missing = [x for x in [fwe, iwe] + fn_ + fb_ if x not in need]
        out = {"method": "module ports cut and driven at random (feed_we, init_we, feed_n, feed_bits, wdata); "
                         "state and poly_l random; next state compared with the stated model", "patterns": n}
        rng = np.random.default_rng(self.seed + 31)
        L = self.forced(self.base(0), None, 0)
        k = rng.integers(1, 9, n)
        for b, net in enumerate(fn_):
            L[net] = _pack(((k >> b) & 1).astype(bool))
        for net in fb_ + wd_:
            L[net] = _pack(rng.integers(0, 2, n).astype(bool))
        mode = rng.integers(0, 3, n)  # 0 feed, 1 init, 2 hold
        L[fwe] = _pack(mode == 0)
        L[iwe] = _pack(mode == 1)
        V = self.run(dn, L, cut=cut)
        c = self.word_values(L, crc)
        p = self.word_values(L, poly)
        bits = [_lanes(L[x], n).astype(np.uint64) for x in fb_]
        e = c.copy()
        for s_ in range(8):
            fb = ((e >> np.uint64(31)) & np.uint64(1)) ^ bits[s_]
            nxt = ((e << np.uint64(1)) & np.uint64(0xFFFFFFFF)) ^ (fb * p)
            e = np.where(s_ < k, nxt, e)
        wm1 = self.word_values(L, [self.qnet(f"{inst}.width_m1", i) for i in range(5)])
        init = (self.word_values(L, wd_) << (np.uint64(31) - wm1)) & np.uint64(0xFFFFFFFF)
        want = np.where(mode == 0, e, np.where(mode == 1, init, c))
        got = self.word_values(V, dn)
        per = {}
        for kk in range(1, 9):
            sel = (mode == 0) & (k == kk)
            per[str(kk)] = [int(sel.sum()), int((got[sel] != want[sel]).sum())]
        out.update(feed_patterns_and_mismatches_by_k=per,
                   init_patterns=int((mode == 1).sum()), init_mismatches=int((got != want)[mode == 1].sum()),
                   hold_patterns=int((mode == 2).sum()), hold_mismatches=int((got != want)[mode == 2].sum()),
                   ports_outside_cone=len(missing))
        out["ok"] = bool(np.all(got == want)) and not missing and all(v[0] > 0 for v in per.values())
        return out


# ============================================================================ main

def gds_name(comp):
    master, x, y, _orient = comp
    short = master[len(PREFIX):] if master.startswith(PREFIX) else master
    return f"{short}_{x}_{y}"


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def tempo_source_facts(commit, rtl_paths):
    """Where TEMPO's inputs come from (for the run file): the frozen snapshot S3 uses
    (out/s3/tempo_snapshot: TEMPO_COMMIT and SHA256SUMS, checked here), or a git checkout of
    TEMPO (its HEAD and whether the RTL matches the sign-off commit), or a plain directory."""
    root = os.path.abspath(TEMPO_ROOT)
    marker = os.path.join(root, "TEMPO_COMMIT")
    if os.path.exists(marker):
        with open(marker) as f:
            tc = f.read().strip()
        checked, bad = 0, []
        sums = os.path.join(root, "SHA256SUMS")
        if os.path.exists(sums):
            with open(sums) as f:
                for line in f:
                    if not line.strip():
                        continue
                    h, rel = line.split(None, 1)
                    path = os.path.join(root, rel.strip().lstrip("*"))
                    checked += 1
                    if not os.path.exists(path) or _sha256(path) != h:
                        bad.append(rel.strip())
        return {"kind": "snapshot", "root": TEMPO_ROOT, "tempo_commit": tc, "signoff_commit": commit,
                "snapshot_is_signoff_commit": tc == commit, "sha256sums_checked": checked,
                "sha256sums_mismatch": bad}
    top = subprocess.run(["git", "-C", root, "rev-parse", "--show-toplevel"], capture_output=True,
                         text=True).stdout.strip()
    if not top or os.path.realpath(top) != os.path.realpath(root):
        return {"kind": "directory (no snapshot marker, not a git checkout)", "root": TEMPO_ROOT,
                "signoff_commit": commit}
    git = subprocess.run(["git", "-C", root, "diff", "--quiet", commit, "--"] + rtl_paths, capture_output=True)
    changed = subprocess.run(["git", "-C", root, "diff", "--name-only", commit, "--", "src/"],
                             capture_output=True, text=True).stdout.split()
    head = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return {"kind": "git checkout", "root": TEMPO_ROOT, "head": head, "signoff_commit": commit,
            "rtl_matches_signoff_commit": git.returncode == 0, "src_files_changed_since_signoff": changed}


def _rel_source(path):
    """absolute input path -> '$TEMPO_ROOT/...' or '$IHP_PDK/...' (no machine paths in the truth)."""
    for var, root in (("$TEMPO_ROOT", TEMPO_ROOT), ("$IHP_PDK", lvs.IHP_PDK)):
        if os.path.abspath(path).startswith(os.path.abspath(root) + os.sep):
            return var + "/" + os.path.relpath(path, root)
    return os.path.basename(path)


def _index_ranges(idx):
    idx = sorted(idx)
    out, run = [], [idx[0]]
    for i in idx[1:] + [None]:
        if i is not None and i == run[-1] + 1:
            run.append(i)
            continue
        out.append(f"{run[-1]}:{run[0]}" if len(run) > 1 else f"{run[0]}")
        if i is not None:
            run = [i]
    return ",".join(reversed(out))


class Incomplete(SystemExit):
    """the truth is not complete (a proof, the GDS check or the simulation fell short) and no
    --draft path was given: nothing is written, exit status 2."""


def build(out_path, run_path=None, work=WORK, npat=1 << 14, seed=20260921, gds_check=True, prove=True,
          draft=False, log=print):
    """Generate the TEMPO truth. Writes `out_path` (and its .run.json) only when complete, unless
    `draft` (then the shortfalls go to meta.draft); raises Incomplete otherwise."""
    t0 = time.time()
    tim = {}
    shortfalls = []  # why the truth is incomplete (proof, GDS check, simulation)

    def fall_short(what):
        shortfalls.extend(what)
        if what and not draft:
            for x in what:
                log(f"INCOMPLETE: {x}")
            log("nothing written: a truth needs every proof and check (--draft PATH writes a draft outside out/s3)")
            raise Incomplete(2)

    if not prove:
        fall_short(["z3 proof skipped (--no-prove)"])
    if not gds_check:
        fall_short(["GDS instance-name check skipped (--no-gds)"])
    p, scripts, yver, files, defines = run_yosys(work)
    tim["yosys"] = round(time.time() - t0, 1)
    rtl_paths = sorted({os.path.relpath(f, TEMPO_ROOT) for f in files} |
                       {os.path.join("src", f) for f in os.listdir(SRC) if f.endswith(".vh")})
    with open(os.path.join(FINAL, "commit_id.json")) as f:
        commit = json.load(f).get("commit")
    tempo = tempo_source_facts(commit, rtl_paths)
    if tempo.get("sha256sums_mismatch"):
        raise RuntimeError(f"TEMPO snapshot {TEMPO_ROOT} differs from its SHA256SUMS: {tempo['sha256sums_mismatch']}")
    log(f"TEMPO inputs: {tempo['kind']} at {TEMPO_ROOT} (sign-off commit {commit[:10]})")
    word = Word(p["wl"], p["regs"])
    fsm_enc = load_fsm_encoding(p["enc"])
    log(f"yosys: {len(word.regs)} registers, {len(word.ffbit)} flop bits; FSMs re-encoded: {sorted(fsm_enc)}")
    # ---- classification
    t1 = time.time()
    cls = Classifier(word, fsm_enc)
    regs = {}
    for name in word.regs:
        kind, det = cls.classify(name)
        rule_alts, rule_reason = det.pop("alt_kinds", []), det.pop("alt_reason", None)
        regs[name] = {"name": name, "width": len(word.regs[name]["bits"]), "kind": kind, "auto_kind": kind,
                      "details": det, "override_reason": None, "alt_kinds": list(rule_alts),
                      "alt_reason": rule_reason}
    for name in word.removed_regs:
        regs[name] = {"name": name, "width": None, "kind": None, "auto_kind": None, "override_reason": None,
                      "details": {"rule": "removed by Yosys before classification (no loads)",
                                  "module": _module_of(name)}, "alt_kinds": [], "alt_reason": None}
    overrides = []
    for pat, kind, reason, extra in MANUAL:
        hit = [n for n in regs if re.search(pat, n)]
        if not hit:
            raise RuntimeError(f"manual override {pat} matches no register")
        for n in hit:
            r = regs[n]
            overrides.append({"register": n, "auto_kind": r["auto_kind"], "kind": kind, "reason": reason})
            r["kind"], r["override_reason"] = kind, reason
            r["alt_kinds"], r["alt_reason"] = [], None  # a rule's alternatives go with the rule's kind
            for k, v in extra.items():
                (r if k in r else r["details"])[k] = v
    missing = sorted(n for n, r in regs.items() if r["kind"] not in KINDS)
    if missing:
        raise RuntimeError(f"registers without a kind: {missing}")
    toggles = sorted(n for n, r in regs.items() if r["alt_reason"] == TOGGLE_RULE)
    alt_rules = [{"pattern": "rule: 1-bit toggle (Classifier)", "kinds": ["counter"], "reason": TOGGLE_RULE,
                  "registers": len(toggles), "per_bit": False, "applies_to": toggles}]
    for pat, kinds, reason, per_bit in ALT_KINDS:
        hit = sorted(n for n in regs if re.search(pat, n))
        if not hit:
            raise RuntimeError(f"alt_kinds pattern {pat} matches no register")
        alt_rules.append({"pattern": pat, "kinds": kinds, "reason": reason, "registers": len(hit),
                          "per_bit": per_bit is not None})
        for n in hit:
            r = regs[n]
            if r["alt_kinds"]:
                raise RuntimeError(f"{n}: alt_kinds from a rule and from ALT_KINDS")
            if per_bit is None:
                r["alt_kinds"], r["alt_reason"] = list(kinds), reason
            else:  # per-bit alternatives live on the bits only; the register accepts nothing extra
                r["alt_kinds"], r["alt_reason"], r["alt_bits"], r["bit_alt_kinds"] = [], reason, per_bit, list(kinds)
    tim["classify"] = round(time.time() - t1, 1)
    # ---- netlist
    t2 = time.time()
    insts = lvs.parse_nl_verilog(lvs.NL_V)
    lef = lvs.load_lef()
    comps = read_def(lvs.DEF)["components"]
    nlsim = NetlistSim(insts, lef, LIB)
    rtl = RtlGates(p["gates"])
    tim["load_netlists"] = round(time.time() - t2, 1)
    t3 = time.time()
    flop_rel, key_rel, check, stats = map_netlist(word, rtl, nlsim, insts, fsm_enc, npat, seed, log)
    tim["simulate"] = round(time.time() - t3, 1)
    ft = stats["flop_types"]
    fall_short([f"simulation: {len(stats[k])} flops {k}" for k in ("mismatch", "unchecked") if stats[k]]
               + ([f"simulation: outputs mismatch {stats['outputs_mismatch'][:8]}"] if stats["outputs_mismatch"] else [])
               + [f"flop types: {len(ft[k])} {k.replace('_', ' ')} {ft[k][:4]}" for k in
                  ("clock_mismatch", "async_mismatch") if ft[k]]
               + ([f"flop types: only {ft['compared']} of {len(nlsim.flops)} flops compared"]
                  if ft["compared"] != sum(1 for r in flop_rel.values() if r[0] in ("bit", "dup", "fsm")) else []))
    proof, pstats = {}, {"skipped": True}
    if prove:
        t5 = time.time()
        proof, pstats = prove_mapping(rtl, nlsim, flop_rel, key_rel, fsm_enc, log=log)
        tim["prove"] = round(time.time() - t5, 1)
        fall_short(proof_complete(pstats))
    z3_version, proof_seconds = pstats.pop("z3", None), pstats.pop("seconds", None)
    z3_rlimit_used = {k: pstats.pop(k, None) for k in ("rlimit_max_per_check", "rlimit_total")}

    def keyname(k):
        return k[0] if len(word.regs.get(k[0], {"bits": [0, 0]})["bits"]) == 1 else f"{k[0]}[{k[1]}]"

    def gkey(f):
        if f not in comps:
            raise RuntimeError(f"netlist flop {f} has no DEF component")
        return gds_name(comps[f])

    # ---- duplicates, retimed flops
    dups = collections.defaultdict(list)
    for f, r in sorted(flop_rel.items()):
        if r[0] == "dup":
            dups[r[1]].append(f)
    key_flop = {}
    for f, r in sorted(flop_rel.items()):
        if r[0] == "bit":
            key_flop.setdefault(r[1], (f, r[2]))
    retimed, unresolved = [], []
    for f, r in sorted(flop_rel.items()):
        if r[0] == "comb":
            keys, _pis = rtl.support(r[1])
            retimed.append({"nl_instance": f, "flop": gkey(f), "holds": r[2], "function_of": _ranges(keys),
                            "check": check.get(f), "proof": proof.get(f)})
        elif r[0] == "unknown":
            unresolved.append({"flop": gkey(f), "nl_instance": f, "reason": r[1]})
    # ---- per-register bits (RTL key -> flop join key)
    fsm_flops = collections.defaultdict(dict)
    for f, r in flop_rel.items():
        if r[0] == "fsm":
            fsm_flops[r[1]][r[2]] = f
    bits_without = collections.Counter()
    bit_flop = {}  # (name, idx) -> join key
    for name, r in regs.items():
        out = []
        if name in word.removed_regs:
            r["bits"] = out
            continue
        if name in fsm_enc:
            for k, f in sorted(fsm_flops[name].items()):
                out.append({"index": k, "flop": gkey(f), "rtl_bit": f"{name}=={fsm_enc[name].get(k)}",
                            "nl_instance": f, "how": "fsm_onehot", "state": fsm_enc[name].get(k)})
            r["details"].setdefault("fsm_state", {})["netlist_encoding"] = (
                f"one-hot, {len(fsm_flops[name])} flops (Yosys fsm_recode 'auto' -> one-hot); bits[].index is "
                "the one-hot position, bits[].state the RTL state code")
            r["bits"] = out
            continue
        for idx, b in sorted(word.regs[name]["bits"].items()):
            key = (name, idx)
            e = {"index": idx, "flop": None, "rtl_bit": keyname(key), "nl_instance": None}
            if isinstance(b, str):
                e["note"] = f"constant {b} in the RTL (no flop)"
                bits_without["constant in RTL"] += 1
            elif b not in word.ffbit:
                e["note"] = "not a flop in the word-level RTL"
                bits_without["not a flop"] += 1
            else:
                owner = (word.reg_of[b] or [key])[0]
                kf = key_flop.get(key) or key_flop.get(owner)
                kr = key_rel.get(key)
                if kf:
                    f, how = kf
                    e.update(flop=gkey(f), nl_instance=f, how=how if key_flop.get(key) else "alias")
                    if dups.get(f):  # synthesis copies (D(dup) == D(flop), proven): not matched flops
                        e["shadow_flops"] = sorted(gkey(g) for g in dups[f])
                elif kr and kr[0] == "merged":
                    f = kr[1]
                    e.update(flop=gkey(f), nl_instance=f, how="merged")
                    bits_without["merged into another register's flop"] += 1
                elif key not in rtl.ff:
                    e["note"] = "unused: no path to a flop or output once bit-blasted (removed by opt_clean)"
                    bits_without["unused"] += 1
                elif kr and kr[0] == "constant":
                    e["note"] = f"next state constant {'1' if kr[1] else '0'} (removed by synthesis)"
                    bits_without["constant next state"] += 1
                elif kr and kr[0] == "unobservable":
                    e["note"] = ("unobservable: flipping it changes no other next state and no output in "
                                 "simulation, so synthesis's logic optimization dropped its only reader")
                    bits_without["unobservable"] += 1
                else:
                    e["note"] = "no flop found"
                    bits_without["unexplained"] += 1
            if e["flop"]:
                bit_flop[key] = e["flop"]
            if r.get("alt_bits"):
                e["alt_kinds"] = list(r["bit_alt_kinds"]) if r["alt_bits"](idx) else []
            out.append(e)
        r["bits"] = out
    # ---- retimed flops: their own register of kind "other" per owning register (schema.py)
    by_owner = collections.defaultdict(list)
    for e in retimed:
        owners = sorted({re.sub(r"\[\d+(:\d+)?\]$", "", s) for s in e["function_of"]} & set(regs))
        if not owners:
            raise RuntimeError(f"retimed flop {e['flop']} is a function of no register: {e['function_of']}")
        by_owner["+".join(owners)].append(e)
    for owner, es in sorted(by_owner.items()):
        rname = f"{owner}__retimed"  # not an RTL name ("__": no word-like token of its own)
        first = regs[owner.split("+")[0]]
        rbits = [{"index": i, "flop": e["flop"],
                  "rtl_bit": e["holds"] if not e["holds"].startswith("<") else f"{rname}[{i}]",
                  "nl_instance": e["nl_instance"], "how": "retimed", "holds": f"{e['holds']}, one cycle ahead",
                  "function_of": e["function_of"]}
                 for i, e in enumerate(sorted(es, key=lambda e: e["flop"]))]
        regs[rname] = {"name": rname, "width": len(rbits), "kind": "other", "auto_kind": "other",
                       "override_reason": None, "alt_kinds": [], "alt_reason": None, "bits": rbits,
                       "details": {"module": first["details"].get("module"),
                                   "src": {"decl": first["details"].get("src", {}).get("decl"), "always": []},
                                   "rule": "retimed: synthesis moved logic across these flops, so each holds a "
                                           "function of the owning register one cycle ahead (found by simulation, "
                                           "proven by z3); a register of their own, kind other (schema.py)",
                                   "retimed_from": owner.split("+")}}
        for o in owner.split("+"):
            regs[o]["details"]["retimed_register"] = rname
    # ---- GDS names
    gds = {"method": "DEF placement: <master minus 'sg13cmos5l_'>_<x>_<y> (DBU), as extract.py names instances"}
    gds_run = {}
    if gds_check:
        t4 = time.time()
        ex, dt, peak = lvs.extract_tempo(lef=lef)
        name_map, rep = lvs.map_to_def(ex, comps)
        back = {v: k for k, v in name_map.items()}
        ok = sum(1 for f in nlsim.flops if back.get(f) == gds_name(comps[f]))
        gds.update(checked=True, flops_agree=ok, flops_disagree=len(nlsim.flops) - ok, ambiguous=len(rep["ambiguous"]))
        gds_run = {"extract_seconds": round(dt, 1), "process_peak_rss_mb": round(peak)}
        tim["gds_check"] = round(time.time() - t4, 1)
        del ex
        fall_short([f"GDS check: {len(nlsim.flops) - ok} of {len(nlsim.flops)} flops' instance names disagree"]
                   if ok != len(nlsim.flops) else [])
    else:
        gds["checked"] = False
    # ---- operators
    ops = operators(word, set(regs))
    # ---- module definitions
    hier = RtlHierarchy(files)
    for name, r in regs.items():
        mod, local = hier.split(name, TOP)
        decl = hier.module_at(r["details"].get("src", {}).get("decl"))
        if decl is not None and decl != mod:
            raise RuntimeError(f"{name}: instance walk says {mod}, declaration line says {decl}")
        r["module_def"], r["design_key"] = mod, design_key(mod, local)
    # ---- parameters, checked by simulation
    t6 = time.time()
    pc = ParamCheck(word, rtl, npat, seed)
    n_checks, bad_checks = 0, []

    def lane_keys(lanes):
        return [[bit_flop[st] for st in lane[1:]] for lane in lanes]

    def source_key(src):
        """a serial or synchronizer source as a joinable value: a flop join key, or port:<pin>"""
        if src[0] == "pi":
            return f"port:{'~' if len(src) > 3 else ''}{src[1]}[{src[2]}]"
        return bit_flop.get((src[1], src[2]))

    def source_rtl(src):
        if src[0] == "pi":
            return f"{'~' if len(src) > 3 else ''}{src[1]}[{src[2]}]"
        return keyname((src[1], src[2]))

    def sync_lanes(name):
        """lanes [source, stage, ...] of a synchronizer register from its bits' D leaves."""
        src = {}
        for idx, b in sorted(word.regs[name]["bits"].items()):
            (leaf,) = word.mux_leaves(cls._d(b))
            if leaf[0] == "pi":
                src[idx] = ("pi", leaf[1], leaf[2])
            elif leaf[0] == "cell":
                d = word.driver[word.cells[leaf[1]]["connections"]["A"][0]]
                src[idx] = ("pi", d[1], d[2], "inv")
            else:
                src[idx] = ("reg",) + word.reg_of[leaf[1]][0]
        nxt = {s[2]: i for i, s in src.items() if s[0] == "reg" and s[1] == name}
        lanes = []
        for i in sorted(i for i, s in src.items() if not (s[0] == "reg" and s[1] == name)):
            lane = [src[i], (name, i)]
            while lane[-1][1] in nxt:
                lane.append((name, nxt[lane[-1][1]]))
            lanes.append(lane)
        return lanes

    def record(r, check):
        nonlocal n_checks
        n_checks += 1
        if not check.get("ok"):
            bad_checks.append(r["name"] if isinstance(r, dict) else r)
        return check

    for name in sorted(regs):
        r = regs[name]
        kind, params, source, chk, stated = r["kind"], {}, None, None, None
        if kind == "shift_register":
            sp = SHIFT_PARAMS.get(name)
            if sp is None:
                raise RuntimeError(f"shift register {name} has no stated parameters")
            lanes = sp["lanes"]
            params = {"lanes": len(lanes), "depth": len(lanes[0]) - 1, "direction": sp["direction"],
                      "serial_in": [source_key(l[0]) for l in lanes], "order": lane_keys(lanes)}
            chk = record(r, pc.chain(lanes, sp["force"]))
            chk["condition"] = sp["condition"]
            source = "hand (SHIFT_PARAMS)"
            stated = {"note": sp["note"], "serial_in_rtl": [source_rtl(l[0]) for l in lanes],
                      "order_rtl": [[keyname(st) for st in l[1:]] for l in lanes]}
        elif kind == "lfsr_crc":
            cp = CRC_PARAMS.get(name)
            if cp is None:
                raise RuntimeError(f"LFSR/CRC {name} has no stated parameters")
            params = {"form": cp["form"], "poly": cp["poly"], "k_steps": cp["k_steps"], "n_inputs": cp["n_inputs"],
                      "bit_order": [bit_flop.get((name, i)) for i in range(r["width"])]}
            chk = record(r, pc.crc(cp["inst"]))
            source = "hand (CRC_PARAMS)"
            stated = {"note": cp["note"], "poly_register": f"{cp['inst']}.poly_l",
                      "poly_flops": [bit_flop.get((f"{cp['inst']}.poly_l", i)) for i in range(32)],
                      "feedback_source_index": 31,
                      "characteristic_polynomial": "x^32 + sum_j poly_l[j] x^j at width 32 (poly_l left-aligned "
                                                   "for narrower widths)",
                      "k_steps_range": list(cp["k_steps_range"]),
                      "modes": {"feed": "feed_we: k = feed_n (1..8) Galois steps with data feed_bits[0..k-1]",
                                "init": "init_we: crc_l <= wdata << (31 - width_m1)", "hold": "otherwise"}}
            r["other_modes"] = cp["other_modes"]
        elif kind == "counter":
            hits = [(pat, cl, note) for pat, cl, note in COUNTER_PARAMS if re.search(pat, name)]
            if len(hits) != 1:
                raise RuntimeError(f"counter {name}: {len(hits)} COUNTER_PARAMS entries")
            _pat, cl, note = hits[0]
            params = {k: cl.get(k) for k in schema.PARAMS["counter"] if k != "bit_order"}
            params["bit_order"] = [bit_flop.get((name, i)) for i in range(r["width"])]
            chk = record(r, pc.counter(name, r["width"], cl))
            source = "hand (COUNTER_PARAMS)"
            stated = {"note": note, **({"bounds": list(cl["bounds"])} if cl.get("bounds") else {}),
                      "load_source": "word-level mux tree (RTL structure), not simulated"}
        elif kind == "synchronizer":
            lanes = sync_lanes(name)
            params = {"stages": max(len(l) - 1 for l in lanes), "order": lane_keys(lanes)}
            chk = record(r, pc.chain(lanes, reset_inactive=not any(l[0][:2] == ("pi", "rst_n") for l in lanes)))
            chk["sources"] = [source_rtl(l[0]) for l in lanes]
            source = "rule (synchronizer stages from the D leaves)"
        r["params"] = params
        r["prov_params"] = (source, chk, stated)
    # ---- declared units
    units = []
    for uname, ukind, members, reason, lanes in UNITS:
        fl = []
        for rn, filt in members:
            for b in regs[rn]["bits"]:
                if b["flop"] and (filt is None or filt(b["index"])) and b["flop"] not in fl:
                    fl.append(b["flop"])
        u = {"name": uname, "kind": ukind, "registers": [m[0] for m in members], "reason": reason, "flops": fl,
             "params": {"stages": max(len(l) - 1 for l in lanes), "order": lane_keys(lanes)}}
        u["check"] = record(uname, pc.chain(lanes))
        if sorted(fl) != sorted({k for lk in u["params"]["order"] for k in lk}):
            raise RuntimeError(f"unit {uname}: flops and order disagree")
        units.append(u)
    # ---- lenient units by rule (UNIT_RULES), exactly as the blind-set labeller declares them
    # (tools/s3/thirdparty.py). A rule unit equal to a declared unit above is not repeated: the
    # declared unit lists the rule in "rules"; a new one is checked by simulation like UNITS
    # (synchronizer lanes: ParamCheck.chain) or, where no unconditional check exists, says so.
    n_declared = len(units)
    runits, unit_report = rule_units(cls, {n: regs[n]["kind"] for n in regs if n in word.regs}, bit_flop.get,
                                     taken=units,
                                     accepts=lambda n: {regs[n]["kind"]} | set(regs[n].get("alt_kinds") or []),
                                     per_slice=True)
    for u in runits:
        rtl_view = u.pop("_rtl")
        if u["rules"] == ["per_slice"]:
            pass  # no params to check (as before the rules moved into rule_units)
        elif u["kind"] == "synchronizer" and all(l[0] is not None for l in rtl_view["lanes"]):
            u["check"] = record(u["name"], pc.chain(rtl_view["lanes"], reset_inactive=not any(
                l[0][:2] == ("pi", "rst_n") for l in rtl_view["lanes"])))
        else:
            u["check"] = {"method": "none: the lanes copy under a condition (or count) that no unconditional "
                                    "simulation exercises; the rule's facts are structural", "ok": None}
        units.append(u)
    unit_report["declared_units_the_rules_reproduce"] = sorted(u["name"] for u in units[:n_declared] if u.get("rules"))
    unit_report["declared_units_no_rule_gives"] = sorted(u["name"] for u in units[:n_declared] if not u.get("rules"))
    unit_report["added_by_rule"] = collections.Counter(r for u in runits for r in u["rules"])
    log(f"units by rule: {len(runits)} added {dict(sorted(unit_report['added_by_rule'].items()))}; "
        f"{len(unit_report['declared_units_the_rules_reproduce'])} of {n_declared} hand-declared units (UNITS) "
        f"reproduced by a rule")
    unit_report["added_by_rule"] = dict(sorted(unit_report["added_by_rule"].items()))
    # ---- registers none of whose flops they are primary for join the units covering them
    reg_list = [r for _n, r in sorted(regs.items())]
    alias_added, alias_uncovered = add_alias_members(reg_list, units)
    if alias_uncovered:
        raise RuntimeError(f"registers with no primary flop and no declared unit covering their flops (a "
                           f"correct answer could never be credited): {alias_uncovered}")
    # ---- a register that is one stage of a declared synchronizer unit: stage-level params null
    stage_of = mark_unit_stages(reg_list, units)
    for name, st in sorted(stage_of.items()):
        r = regs[name]
        r["params"] = {k: None for k in schema.PARAMS[r["kind"]]}
        src, chk, stated = r["prov_params"]
        r["prov_params"] = ("unit: one stage of the declared unit(s) in provenance.stage_of, which carry the "
                            "stage count and order (schema.py); the stage copy is checked here", chk, stated)
        r["stage_of"] = st
    tim["param_checks"] = round(time.time() - t6, 1)
    # negative controls: wrong claims the checks must reject
    negatives = []
    for label, fn in (
            ("bw modulus 3", lambda: pc.counter(f"{HOST}.bw", 2, dict(direction="up", step=1, modulus=3))),
            ("steal_cnt modulus 32", lambda: pc.counter("u_top.u_arb.steal_cnt", 5,
                                                         dict(direction="up", step=1, modulus=32))),
            ("steal_cnt saturating at 16", lambda: pc.counter("u_top.u_arb.steal_cnt", 5, dict(
                direction="up", step=1, modulus=None, saturating=True, bounds=(0, 16)))),
            ("h2c level_r modulus 8", lambda: pc.counter("u_top.u_sys.u_h2c_fifo.level_r", 3, dict(
                direction="updown", step=1, modulus=8, cut=("push", "pop")))),
            ("time_q modulus 2^31", lambda: pc.counter("u_top.u_tio.time_q", 32,
                                                        dict(direction="up", step=1, modulus=1 << 31))),
            ("pc_r[0] step 2 (a branch with offset +1 is a whole-table step of 2)",
             lambda: pc.counter("u_top.u_core.pc_r[0]", 10, dict(direction="up", step=2, modulus=1024, load=True))),
            ("dreg lanes 0 and 1 with swapped serial inputs", lambda: pc.chain(
                [[SHIFT_PARAMS[f"{HOST}.dreg"]["lanes"][1][0]] + SHIFT_PARAMS[f"{HOST}.dreg"]["lanes"][0][1:]],
                SHIFT_PARAMS[f"{HOST}.dreg"]["force"])),
            ("dreg stages reversed", lambda: pc.chain([[l[0]] + l[1:][::-1] for l in SHIFT_PARAMS[f"{HOST}.dreg"]["lanes"]],
                                                     SHIFT_PARAMS[f"{HOST}.dreg"]["force"])),
            ("dreg shifting outside its condition", lambda: pc.chain(SHIFT_PARAMS[f"{HOST}.dreg"]["lanes"], {})),
            ("rx_shift direction to_lsb", lambda: pc.chain(
                [[SHIFT_PARAMS[f"{HOST}.rx_shift"]["lanes"][0][0]] + SHIFT_PARAMS[f"{HOST}.rx_shift"]["lanes"][0][1:][::-1]],
                SHIFT_PARAMS[f"{HOST}.rx_shift"]["force"])),
            ("pins_prev[15] as a third ui_in stage", lambda: pc.chain(
                [[("pi", "ui_in", 7), (f"{TIO}.ui_sync0", 7), (f"{TIO}.ui_sync1", 7), (f"{TIO}.pins_prev", 15)]]))):
        res = fn()
        negatives.append({"claim": label, "rejected": not res["ok"]})
    if not all(n["rejected"] for n in negatives):
        raise RuntimeError(f"parameter checks accepted a wrong claim: {[n for n in negatives if not n['rejected']]}")
    if bad_checks:
        raise RuntimeError(f"parameter checks failed: {bad_checks}")
    log(f"parameter checks: {n_checks} passed; {len(negatives)} negative controls rejected")
    # ---- registers in schema v2
    registers = []
    for name in sorted(regs):
        r = regs[name]
        det = r["details"]
        rule = det.pop("rule", None)
        det.pop("override", None)
        src, chk, stated = r.get("prov_params", (None, None, None))
        if stated is not None:
            det["stated_params"] = stated
        width = r["width"] or len(r["bits"])
        prov = {"rule": rule, "auto_kind": r["auto_kind"], "override_reason": r["override_reason"],
                "params_source": src, "params_check": chk}
        if r.get("stage_of"):
            prov["stage_of"] = r["stage_of"]
        if r.get("other_modes"):
            prov["other_modes"] = r["other_modes"]
        registers.append({
            "name": name, "width": width, "kind": r["kind"], "alt_kinds": r.get("alt_kinds", []),
            "alt_reason": r.get("alt_reason"), "module_def": r["module_def"], "design_key": r["design_key"],
            "params": r.get("params", {}), "bits": r["bits"],
            "n_flops": len({b["flop"] for b in r["bits"] if b["flop"]}),
            "provenance": prov, "details": det})
    width_of = {r["name"]: r["width"] for r in registers}
    # ---- flops: every register using each flop as a bit; primary = the widest
    flops = {}

    def use(key, reg, rtl_bit, role, nl, **extra):
        e = flops.setdefault(key, {"registers": [], "primary": None, "role": role, "rtl_bits": [], "nl_instance": nl,
                                   **extra})
        if reg not in e["registers"]:
            e["registers"].append(reg)
        if rtl_bit and rtl_bit not in e["rtl_bits"]:
            e["rtl_bits"].append(rtl_bit)

    roles = {"fsm_onehot": "fsm_onehot", "retimed": "retimed"}
    for r in registers:
        for b in r["bits"]:
            if b["flop"]:
                use(b["flop"], r["name"], b["rtl_bit"], roles.get(b.get("how"), "bit"), b["nl_instance"])
    for key, e in flops.items():
        e["registers"].sort(key=lambda n: (-width_of[n], n))
        e["primary"] = e["registers"][0]
    flops = dict(sorted(flops.items()))
    if {k: v["primary"] for k, v in flops.items()} != flop_primaries(registers):
        raise RuntimeError("flops.primary disagrees with flop_primaries()")
    shadow = {d: (r["name"], b["flop"]) for r in registers for b in r["bits"] for d in b.get("shadow_flops", [])}
    why = {u["flop"]: u["reason"] for u in unresolved}
    unmapped = [{"flop": gkey(f), "reason": why.get(gkey(f), "no register uses it")} for f in sorted(nlsim.flops)
                if gkey(f) not in flops and gkey(f) not in shadow]
    every = {gkey(f) for f in nlsim.flops}
    if set(shadow) & set(flops) or len(flops) + len(shadow) + len(unmapped) != len(every) or \
            set(flops) | set(shadow) | {u["flop"] for u in unmapped} != every:
        raise RuntimeError("bit flops, shadow flops and unmapped flops do not partition the netlist's flops")
    # ---- counts
    nflops = len(nlsim.flops)
    labels = {"fsm": "FSM one-hot state flop", "dup": "shadow flop (synthesis duplicate of a register bit's flop)",
              "comb": "retimed register (function of labelled registers)", "unknown": "unresolved"}
    by = collections.Counter()
    for f, r in flop_rel.items():
        by[("register bit by name" if r[2] == "name" else "register bit by alias") if r[0] == "bit"
           else labels[r[0]]] += 1
    kinds = collections.Counter(r["kind"] for r in registers)
    kind_of = {r["name"]: r["kind"] for r in registers}
    designs = collections.defaultdict(set)
    kflops = collections.defaultdict(set)  # a flop two registers of different kinds share counts twice
    for r in registers:
        designs[r["kind"]].add(r["design_key"])
    for key, e in flops.items():
        for n in e["registers"]:
            kflops[kind_of[n]].add(key)
    primary_flops = collections.Counter(kind_of[e["primary"]] for e in flops.values())
    sources ={f"$TEMPO_ROOT/{rp}": _sha256(os.path.join(TEMPO_ROOT, rp)) for rp in rtl_paths}
    for path in (lvs.NL_V, lvs.DEF, LIB):
        sources[_rel_source(path)] = _sha256(path)
    meta = {
        "design": "tempo", "top": TOP,
        "description": "TEMPO (Tiny Tapeout, IHP sg13cmos5l): two-thread microcontroller with a host SPI port, "
                       "timed I/O, serializers, CRC engines and a 1024x32 SRAM macro",
        "generated_by": "python -m tools.s3.truth_tempo",
        "sources": dict(sorted(sources.items())),
        "rtl": {"files": [os.path.relpath(f, TEMPO_ROOT) for f in files], "defines": defines},
        "yosys_scripts": {"word": WORD_SCRIPT, "fsm": FSM_SCRIPT},
        "kinds": list(KINDS), "structure_kinds": list(schema.STRUCTURE_KINDS),
        "counts": {"registers": len(registers), "registers_by_kind": dict(sorted(kinds.items())),
                   "distinct_designs_by_kind": {k: len(v) for k, v in sorted(designs.items())},
                   "flops_by_kind": {k: len(v) for k, v in sorted(kflops.items())},
                   "flops_by_primary_kind": dict(sorted(primary_flops.items())),
                   "units": len(units), "rtl_flop_bits": len(word.ffbit), "netlist_flops": nflops,
                   "operators": len(ops),
                   "operators_by_type": dict(sorted(collections.Counter(o["type"] for o in ops).items()))},
        "coverage": {"netlist_flops": nflops, "by_resolution": dict(sorted(by.items())),
                     "in_flops_map": len(flops), "shadow_flops": len(shadow), "unmapped": len(unmapped),
                     "partition": "netlist flops = flops map (register bits) + shadow flops + unmapped flops, "
                                  "disjoint (checked)",
                     "shadow_flops_of": {d: {"register": rn, "flop": f} for d, (rn, f) in sorted(shadow.items())},
                     "shared_flops": sum(1 for e in flops.values() if len(e["registers"]) > 1),
                     "registers_without_primary_flop": sorted(
                         r["name"] for r in registers if any(b["flop"] for b in r["bits"])
                         and all(flops[b["flop"]]["primary"] != r["name"] for b in r["bits"] if b["flop"])),
                     "alias_unit_members_added": alias_added,
                     "rtl_bits_without_own_flop": dict(sorted(bits_without.items()))},
        "fsm_recoding": {"format": "{state register: {one-hot position (bits[].index): RTL state code}}",
                         "registers": {k: {str(i): c for i, c in sorted(v.items())} for k, v in fsm_enc.items()}},
        "manual_overrides": overrides,
        "alt_kind_rules": alt_rules,
        "unit_rules": unit_report,
        "functional_check": stats,
        "proof": pstats,
        "gds_check": gds,
        "param_checks": {"method": ParamCheck.__doc__.split("\n\n")[0].replace("\n", " ").strip(),
                         "patterns": npat, "seed": seed, "checks": n_checks, "failed": bad_checks,
                         "negative_controls": negatives},
        "removed_rtl_registers": word.removed_regs,
        "ignored_loop_variables": word.loop_vars,
        "dynamic_arrays": {k: sorted(v) for k, v in sorted(word.dyn_arrays.items())},
        "conventions": {
            "flop": "join key: the GDS extraction's instance name <master minus 'sg13cmos5l_'>_<x>_<y>",
            "bits.index": "RTL bit index (FSM: one-hot position in the netlist encoding)",
            "params.bit_order": "join keys by weight, LSB (index 0) first; null where the bit has no flop",
            "params.order": "per lane, stage 0 (the stage loading the serial input) first; lanes in RTL index order",
            "params.direction (shift_register)": "to_msb: data moves toward higher RTL index; to_lsb: toward lower",
            "params.serial_in": "per lane: the source flop's join key, or port:<pin> for an input pin (RTL names "
                                "in details.stated_params.serial_in_rtl)",
            "params.k_steps": "lfsr_crc (schema.py): LFSR steps per clock in the main (data) update mode, null when "
                              "a runtime operand sets it (crc_l: feed_n = 1..8, in details.stated_params."
                              "k_steps_range); n_inputs: data bits entering per LFSR step (0 = autonomous); other "
                              "modes in provenance.other_modes",
            "params.poly": "'programmable' when a register holds the taps",
            "params (unit stages)": "a synchronizer register that is one stage of a declared unit has stages and "
                                    "order null; the unit carries them (provenance.stage_of names the unit and stage)",
            "null": "unknown or not a constant of the RTL: leaves the denominator",
            "units": "lenient alternatives: a matched unit credits its member registers; never an extra target. A "
                     "register primary for none of its flops (merged by synthesis into another register's flops) is a "
                     "member of every unit covering its flops whose kind it accepts",
            "units.rules": "the UNIT_RULES (meta.unit_rules) that derive the unit; a hand-declared unit (UNITS) a "
                           "rule reproduces lists the rule, a unit the rules add is named '<members> (<rule>)' (per_slice: "
                           "'<register>[<bits>]'); the blind-set labeller (tools/s3/thirdparty.py) declares units by "
                           "sync_chain, copy_lanes and concat_adder only",
            "alt_kinds": "only widen what a match accepts; never remove a register from a denominator (schema.py)",
            "flops": "register bits only: shadow flops are in bits[].shadow_flops (and meta.coverage), not here",
            "flops.primary": "the widest register using the flop (partition metrics); registers lists all",
            "flops.role": "bit | retimed (a bit of an <owner>__retimed register: holds a function of the owner one "
                          "cycle ahead) | fsm_onehot",
            "bits.shadow_flops": "synthesis duplicates of the bit's flop (a memory read port's copy): D(dup) == "
                                 "D(flop) proven by z3; a structure may include or omit them",
            "bits.alt_kinds": "present only when alternative kinds differ by bit (the register's alt_kinds are then "
                              "[] and alt_reason explains the bits'); overrides the register's alt_kinds",
            "toggle rule": TOGGLE_RULE,
            "details": "rule facts for humans, unscored"},
    }
    if draft:  # design "tempo-draft": the scorer's design check refuses it and its truth_hash differs
        meta["draft"] = {"incomplete": shortfalls or ["none: complete, but written with --draft"],
                         "note": "a draft is not a truth: written outside out/s3 with design 'tempo-draft', so it "
                                 "is never loaded or hashed as TEMPO's truth"}
        meta["design"] = "tempo-draft"
    truth = {"schema": schema.TRUTH_SCHEMA, "design": meta["design"], "registers": registers, "units": units,
             "flops": flops, "unmapped_flops": unmapped, "operators": ops, "meta": meta}
    problems = schema.check_truth(truth)
    if problems:
        raise RuntimeError(f"check_truth: {problems[:10]}")
    text = json.dumps(truth, indent=1) + "\n"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(text)
    th = schema.truth_hash(json.loads(text))  # of the file as read back (int dict keys become strings)
    # ---- volatile facts
    me = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--", "tools/s3"], capture_output=True,
                           text=True).stdout.strip()
    import numpy as np
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    tim["total"] = round(time.time() - t0, 1)
    run = {"truth": os.path.relpath(os.path.abspath(out_path), ROOT), "truth_hash": th,
           "truth_sha256": hashlib.sha256(text.encode()).hexdigest(),
           "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "argv": sys.argv,
           "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
           "versions": {"python": platform.python_version(), "numpy": np.__version__, "z3": z3_version,
                        "yosys": yver, "platform": platform.platform()},
           "retrace": {"head": me, "tools_s3_status": dirty.splitlines()},
           "tempo": tempo,
           "draft": bool(draft), "incomplete": shortfalls,
           "paths": {"liberty": LIB, "work": work, "netlist": lvs.NL_V, "def": lvs.DEF},
           "yosys_scripts": scripts, "timings_s": tim, "proof_seconds": proof_seconds,
           "z3_rlimit": {"per_check": Z3_RLIMIT, **z3_rlimit_used}, "gds_check": gds_run,
           "peak_rss": {"ru_maxrss": rss, "unit": "bytes" if sys.platform == "darwin" else "KiB"}}
    run_path = run_path or re.sub(r"\.json$", "", out_path) + ".run.json"
    with open(run_path, "w") as f:
        json.dump(run, f, indent=1)
        f.write("\n")
    log(f"wrote {'DRAFT ' if draft else ''}{out_path}: {len(registers)} registers, {len(units)} units, "
        f"{len(flops)} flops mapped, {len(shadow)} shadow, {len(unmapped)} unmapped, {len(ops)} operators; "
        f"simulation: {stats['match']} match, "
        f"{len(stats['mismatch'])} mismatch, {len(stats['unchecked'])} unchecked"
        + (f"; z3: {pstats['proven']} proven, {len(pstats['refuted'])} refuted, {len(pstats['unknown'])} unknown, "
           f"outputs {pstats['outputs']}" if prove else "") + f"; truth_hash {th}")
    log(f"wrote {run_path}")
    return truth, run


def _ranges(keys):
    """{(reg, idx)} -> ['reg[hi:lo]', ...] with contiguous runs merged."""
    regs = collections.defaultdict(list)
    for r, i in keys:
        regs[r].append(i)
    out = []
    for r, idx in sorted(regs.items()):
        idx = sorted(idx)
        run = [idx[0]]
        for i in idx[1:] + [None]:
            if i is not None and i == run[-1] + 1:
                run.append(i)
                continue
            out.append(f"{r}[{run[-1]}:{run[0]}]" if len(run) > 1 else f"{r}[{run[0]}]")
            if i is not None:
                run = [i]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", nargs="?", default=os.path.join(ROOT, "out", "s3", "truth_tempo.json"))
    ap.add_argument("--run-json", help="volatile facts (default: OUT with .run.json)")
    ap.add_argument("--work", default=WORK, help="directory for Yosys scripts, logs and JSON")
    ap.add_argument("--patterns", type=int, default=1 << 14, help="random simulation patterns")
    ap.add_argument("--seed", type=int, default=20260921)
    ap.add_argument("--draft", metavar="PATH",
                    help="write a draft to PATH (outside out/s3) even when a proof or check is skipped or fails")
    ap.add_argument("--no-prove", action="store_true", help="skip the z3 proof of the mapping (~90 s; --draft only)")
    ap.add_argument("--no-gds", action="store_true",
                    help="skip extracting TEMPO's GDS (~20 s, ~2 GB) to confirm every flop's GDS instance name "
                         "(--draft only)")
    ap.add_argument("--gds", action="store_true", help=argparse.SUPPRESS)  # the default since truth/2
    a = ap.parse_args(argv)
    out = a.out
    if a.draft:
        out = os.path.abspath(a.draft)
        s3 = os.path.realpath(OUT_S3)
        if os.path.realpath(out) == s3 or os.path.realpath(out).startswith(s3 + os.sep):
            ap.error(f"--draft {a.draft}: a draft must be written outside {OUT_S3}")
        if a.run_json and os.path.realpath(os.path.abspath(a.run_json)).startswith(s3 + os.sep):
            ap.error("--run-json of a draft must lie outside out/s3 too")
    elif a.no_prove or a.no_gds:
        ap.error("--no-prove / --no-gds give an incomplete truth: use --draft PATH (outside out/s3)")
    sys.setrecursionlimit(100000)
    try:
        build(out, run_path=a.run_json, work=a.work, npat=a.patterns, seed=a.seed, gds_check=not a.no_gds,
              prove=not a.no_prove, draft=bool(a.draft))
    except Incomplete:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
