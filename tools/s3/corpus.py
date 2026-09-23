"""S3 synthetic corpus: small labelled RTL designs, each synthesised for sky130_fd_sc_hd and IHP
sg13cmos5l, for recognizer unit tests (docs/S3_DESIGN.md section 4.4).

    python -m tools.s3.corpus [OUTDIR] [--only NAME[,NAME...]] [--jobs N] [--list]

OUTDIR defaults to out/s3/corpus. Per design, OUTDIR/<name>/ holds:
  rtl.v                  the generator's RTL (module `top`, possibly with submodules)
  <lib>.v                the flat structural netlist with every instance and internal net name
                         stripped (ports keep their names): the file a test loads with
                         netlist.load_verilog(path, Library(liberty))
  <lib>.named.v          the same netlist before stripping (Yosys write_verilog), for people
  truth.json             schema.TRUTH_SCHEMA; one truth for both libraries (the join keys agree)
  claims.json            per library, proof claims (schema.py "Proof claims", with symbolic leaves)
                         restating every structure register's params, each verified by the
                         harness's own checker, tools/s3/verify.py, on that library's netlist
OUTDIR/manifest.json lists every design with its family, split ("train" / "holdout"), register
kinds, file hashes, claim counts and check results.

Flow, per design and library (Yosys, `yosys_script()`): read_verilog -sv; hierarchy -check -top
top; synth -flatten; `rename -wire` on every flop, which names it after the register bit its Q
drives (e.g. `u_lo.c[2]$_DFFE_PN0P_`); dfflibmap and abc with the Liberty; setundef -zero; hilomap
to the library's tie cells; opt_clean. The flop names are set before technology mapping, so they
are identical for both libraries: that pre-strip instance name is the truth's join key (the
`flops` keys). This module then writes <lib>.v from Yosys' JSON: cells and internal nets become
_<n>_ in an order shuffled with a seed derived from the design and library names, so neither names
nor file order carry the RTL. Each truth bit records its flop's stripped instance name per library
(`nl_instance`), the cell master and whether the flop stores the RTL bit inverted (`inverted`:
dfflibmap emulates a set flop with a reset flop between inverters where the library has no set
flop, as IHP does).

Truth. Every flop belongs to a labelled register (to several when synthesis merged equivalent
flops: role "shared"); kinds and parameters are stated by the generator, which wrote the RTL. Kinds
follow docs/S3_DESIGN.md section 1 and the conventions of out/s3/truth_tempo.json (see
TRUTH_CONVENTIONS): e.g. a 3-flop synchronizer chain is stages 1-2 synchronizer plus a stage-3 flag,
depth-2 shifts are data registers with alt shift_register, Fibonacci LFSRs accept shift_register.
Each design's truth meta lists the cases where the recognizer's definitions and the RTL intent
differ (known_disagreements). Checks, run on each library's netlist with
netlist.GateGraph and Sim, one clock step from random states (every other flop and input random):
  * model: the generator's numpy model of the RTL predicts the next state of the registers it
    covers, under the stated input condition and register domain (e.g. a mod-M counter in [0, M));
  * params: from the truth's params alone (join keys, per-library polarity): a counter's bit_order
    value steps by +/- step modulo `modulus` under its defining condition; a shift register's or
    synchronizer's stage k takes stage k-1 (stage 0 its serial input); an LFSR/CRC's next state is
    GF(2)-affine in its own bits (n(a) ^ n(b) ^ n(c) == n(a ^ b ^ c) with everything else fixed);
  * negatives from the counter family (Gray, mutated carry): no bit order and polarity makes every
    transition +1 or -1 (exhaustive);
  * LFSR/CRC polynomials: the characteristic polynomial of the model's one-step matrix equals the
    stated polynomial or its reciprocal (and the period is recorded for autonomous ones).
  * claims (SAT, every state the condition admits, not sampling), verified with
    verify.verify_structure on each library's netlist: a counter's bit k is bit k of
    (v + K) mod 2^w over its bit_order under its defining condition, split into disjoint cubes
    (K = the step, or step - modulus on the wrapping states: a mod-M domain [0, M) is a cube
    cover, so no invariant is needed); a shift register's or synchronizer's stage k equals stage
    k-1 and stage 0 its serial input; an LFSR/CRC bit equals the XOR of the flop states and input
    pins its RTL model is affine in (the programmable CRCs at the probed setting poly = reset
    value), and the number of data pins entering must equal k_steps x n_inputs. Claims go through
    verify.verify_structure's legacy claim-set path (no "kind"); where the harness's conflict limit
    runs out, BddProver decides the same claims exactly (independent_proof). The simulation checks
    above miss some wrong params that the claims refute: a 16-bit counter's bit_order with bits
    14 and 15 swapped passes 20 of 20 seeded 1,024-lane runs.
  * model facts: NLFSR / de Bruijn heads are not GF(2)-affine (a witness triple) and a de Bruijn
    shift has period 2^w; every LFSR/CRC's one-step matrix class (one tap row: fibonacci, one tap
    column: galois, both: a trinomial, neither: affine) equals params.form; no bit order makes an
    LCG a counter (exact search).
  * reference result (build_reference): every structure register (or score.py's chain unit) with
    params, order and a v2 control (schema.py "Verification (v2, kind-bound)"; V2_CONTROL says how
    it is derived) must pass verify.verify_result on both netlists, except the counters whose
    defining case needs their own value (reload or stop at terminal count or at a register), which
    v2 cannot state without self-conditions: they are listed (reference.v2_inexpressible) and carry
    proof status "unknown".
A failed check fails the build (exit 1); results are in each register's provenance.params_check
and provenance.claims_check.

Cohort 2 (TRUTH_CONVENTIONS["meta.cohort"]) adds the structure classes the generalisation review of
2026-09-22 found missing, written for this corpus: reloadable down timers and an auto-reload up
timer (13-24 bits), wide counters (33-64 bits), mixed-direction cascades across modules, NLFSRs and
de Bruijn shifts, xorshift maps (lfsr_crc form affine), word-parallel CRCs (k >= w, w 12-32),
trinomial CRCs in Galois and Fibonacci form (form both), shift chains whose stages differ in reset,
case-coded mod-M up/down counters with out-of-range states to 0, narrow-addend accumulators and LCGs
(negatives), per-channel histories under one enable (lenient units, lanes_unordered) and
concatenated {hi, lo} counters (lenient units). out/s3/review_generalisation stays a separate
regression set.

Port names: no port (bit) name is a string of the result vocabulary (RESULT_VOCAB: schema keys,
kinds, params, claim operators and roles, e.g. "q", "load", "up", "hold"), because run.py's leak
check intersects every string of a result, dict keys included, with the Key's names; so scalar
outputs are `qo`, the up/down select is `dir_up`, loads are `ld` and the timer's hold is `pause`.

Split: within each (cohort, family), designs sorted by sha256(name); the first (n + 1) // 4 are
"holdout" (truth meta.split, manifest designs[].split and manifest.holdout). Grouping by cohort
keeps every cohort-1 design in the split it had before cohort 2 existed. On top of that, every
design in FITTED_ON -- a design a recognizer threshold was fitted to -- is forced into "train",
whatever its hash position, so a holdout figure never contains a design a value was chosen on
(review[2] issue 1). Designs in DROPPED are not part of the corpus at all. manifest() applies both
corrections to a manifest written before them and says so in manifest()["corrections"]; the
directories of a dropped design and the file's own counts are only fixed by a rebuild.

API for tests: designs() (the generators), manifest(outdir), load(name, lib, outdir, seed) ->
(Netlist, Key, truth) with the Key's flop cell names replaced by the truth's join keys, so the
harness's id mapping (run.id_mapper), run.evaluate and score.py apply unchanged;
claims(name, outdir) -> claims.json; reference_result(name, lib, nl, key, outdir) -> a perfect,
verifiable result in nl's opaque ids (after run.relabel, permute the Key's cell names and port
nets alongside); Claimer / opaque_claims / id_maps build and translate claims for new cases.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import dataclasses
import datetime
import functools
import hashlib
import itertools
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.s3 import schema  # noqa: E402
from tools.s3 import verify as s3verify  # noqa: E402
from tools.s3.netlist import GateGraph, Key, Library, Sim, load_verilog  # noqa: E402

CORPUS_SCHEMA = "retrace-s3-corpus/1"
DEFAULT_OUT = os.path.join(ROOT, "out", "s3", "corpus")
YOSYS = os.environ.get("YOSYS", os.path.expanduser("~/ttsetup/oss-cad-suite/bin/yosys"))
IHP_PDK = os.environ.get("IHP_PDK", os.path.expanduser("~/ttsetup/pdk/ihp-sg13cmos5l"))
LIBS = {
    "sky130": {"liberty": os.path.join(ROOT, "pdk", "sky130_fd_sc_hd", "lib", "sky130_fd_sc_hd__tt_025C_1v80.lib"),
               "hilo": "-hicell sky130_fd_sc_hd__conb_1 HI -locell sky130_fd_sc_hd__conb_1 LO"},
    "ihp": {"liberty": os.path.join(IHP_PDK, "libs.ref", "sg13cmos5l_stdcell", "lib",
                                    "sg13cmos5l_stdcell_typ_1p20V_25C.lib"),
            "hilo": "-hicell sg13cmos5l_tiehi L_HI -locell sg13cmos5l_tielo L_LO"},
}
LANES_W = 16                      # 64-lane words per check: 1,024 random lanes
# The 1-bit toggle rule, copied VERBATIM from tools/s3/truth_tempo.py's TOGGLE_RULE (the string is
# duplicated rather than imported because truth_tempo.py pulls in the whole TEMPO truth builder;
# test/test_s3.py asserts the two are identical). The lead's decision of 2026-09-23: a 1-bit toggle
# is kind "flag" with alt_kinds ["counter"] EVERYWHERE -- TEMPO, the corpus and the blind labeller
# -- so that schema v2.1's counter width >= 2 rule does not make three corpus designs
# unverifiable by construction.
TOGGLE_RULE = ("a 1-bit toggle (Q <= ~Q, possibly under an enable) is a flag that a structural "
               "recognizer may also report as a 1-flop counter (mod 2); never a required counter")

TRUTH_CONVENTIONS = {
    "flop": "join key: the flop's instance name before stripping, set by Yosys `rename -wire` before "
            "technology mapping (<RTL register bit>$<generic flop type>); identical for both libraries",
    "bits.nl_instance": "per library: the flop's instance name in the stripped netlist <lib>.v",
    "bits.inverted": "per library: true when the flop stores the complement of the RTL bit",
    "bits.index": "bit index within the register (RTL index for whole registers; slice position for "
                  "slices); rtl_bit names the RTL bit",
    "params.bit_order": "join keys by weight, LSB (index 0) first",
    "params.order": "per lane, stage 0 (the stage loading the serial input) first",
    "params.direction (shift_register)": "to_msb: data moves toward higher RTL index; to_lsb: toward "
                                         "lower; null when the chain is not monotonic in the RTL index",
    "params.serial_in": "per lane: port:<pin> for an input pin, or the source flop's join key; null when "
                        "the head is logic or a constant",
    "params.modulus": "the wrap period; 2^w for natural wrap; null for saturating counters and when the "
                      "bound is held in a register or the counter never wraps",
    "params.saturating": "true when the counter stops at 2^w - 1 going up (or at 0 going down); the top as an "
                         "int when it stops below 2^w - 1 (tools/s3/verify.py v2 reads true with a null modulus as "
                         "2^w - 1); false when it wraps; null when the bound is held in a register",
    "params.load": "true when some update writes a non-constant value (opaque data or a relative +c); "
                   "constant loads (clear, preset) do not count",
    "params.poly": "LFSR/CRC polynomial as an integer, bit i = coefficient of x^i including x^n (the "
                   "scorer also accepts the reciprocal); 'programmable' when a register holds the taps",
    "params.k_steps": "LFSR steps per clock in the main (data) mode; other modes in provenance.modes",
    "params.n_inputs": "data bits entering per LFSR step (0 for an autonomous LFSR), per schema.py",
    "units": "declared lenient alternatives (e.g. a cascade read as one counter); never extra targets",
    "flops.role": "bit, or shared when synthesis merged equivalent flops of several registers (opt_merge): the "
                  "flop lists every register using it; primary = the widest",
    "provenance.claims_check": "per library: the claim method, the number of claims and whether "
                               "tools/s3/verify.py verified them all (the claims are in claims.json); when the "
                               "harness's SAT budget runs out (wide XOR cones), independent_proof records the "
                               "corpus's own BDD proof of the same claims",
    "params.form": "fibonacci / galois: the RTL's form, checked on the one-step matrix (one tap row / one tap "
                   "column); both: the polynomial is a trinomial, so the one-step matrix has one tap row and one "
                   "tap column and the two forms coincide (provenance.rtl_form keeps the RTL's); affine: "
                   "GF(2)-linear in its own bits but not a one-step companion matrix (xorshift-style maps), with "
                   "poly and k_steps null",
    "params.lanes_unordered": "multi-lane shift registers and synchronizers (registers and units): true when every "
                              "lane's head is an input pin, so the lane order is only the RTL bus index, which an "
                              "anonymous netlist does not carry; absent for single-lane structures",
    "meta.cohort": "1: the first corpus; 2: structure classes added after the generalisation review of "
                   "2026-09-22 (reload timers, wide counters, mixed-direction cascades, NLFSR / de Bruijn shifts, "
                   "xorshift maps, word-parallel and trinomial CRCs, mixed-reset shifts, case-coded mod-M "
                   "up/down counters, narrow-addend accumulators and LCGs, per-channel histories, concatenated "
                   "counters), written for this corpus (none copied from out/s3/review_generalisation)",
    "meta.split": "train or holdout: per (cohort, family), designs sorted by sha256(name), the first (n + 1) // 4 "
                  "held out; cohort 2 never moves a cohort-1 design between splits",
    "kind (1-bit toggle)": "a width-1 register whose update is Q <= ~Q (possibly under an enable) or an adder on "
                           "its own Q is kind 'flag' with alt_kinds ['counter'] and alt_reason TOGGLE_RULE, the "
                           "same rule out/s3/truth_tempo.json applies (tools/s3/truth_tempo.py TOGGLE_RULE) and "
                           "the blind labeller applies; its counter params are still stated and still checked as "
                           "a counter's (Reg.check_as, as for a depth-2 shift), but it is not a scored counter "
                           "item and the reference result builds no structure for it. Before 2026-09-23 the "
                           "corpus called "
                           "these registers counters, which schema v2.1's counter width >= 2 rule made "
                           "unverifiable by construction (changes.jsonl PV04, I04, T04)",
}

# Strings a recognizer result carries by the schema alone (keys, kinds, params, claim operators and
# roles, parameter values). run.py's leak check intersects every string of a result, keys included,
# with the Key's names, ports among them; so no port (bit) name of a corpus design may be one of these.
RESULT_VOCAB = frozenset(schema.KINDS) | frozenset(schema.PROOF) | {p for v in schema.PARAMS.values() for p in v} | {
    "schema", "structures", "id", "kind", "flops", "order", "params", "control", "proof", "status", "claims",
    "groups", "meta", "type", "next", "flop", "equals", "when", "role", "defining", "hold", "reset", "load",
    "q", "net", "const", "not", "and", "or", "xor", "value", "input", "port", "pi", "up", "down", "updown",
    "to_msb", "to_lsb", "fibonacci", "galois", "programmable", "parallel", "affine", "both", "inputs",
    "reset_value"} | set(schema.LFSR_FORMS)


# ----------------------------------------------------------------------------------------------
# specifications


@dataclasses.dataclass
class Reg:
    """One labelled register. `params` refer to flops as (register name, bit index) tuples and to
    input pins as "port:<pin>"; they are resolved to join keys after synthesis."""
    name: str
    width: int
    kind: str
    params: dict = dataclasses.field(default_factory=dict)
    alt_kinds: tuple = ()
    alt_reason: str | None = None
    rule: str = ""
    module_def: str = "top"
    local: str | None = None          # the name inside module_def (default: name)
    rtl: str | None = None            # RTL vector holding the bits (default: name)
    rtl_bits: tuple | None = None     # RTL index of each bit (default: 0..width-1; None = scalar)
    when: dict | None = None          # defining condition for the params check {"inputs", "domain"}
    when_down: dict | None = None     # second condition (up/down counters: counting down)
    head: list | None = None          # per lane, stage 0's source for the check (default serial_in)
    serial_inv: tuple | None = None   # per lane, stage 0 takes the complement of its source
    check_as: str | None = None       # params check of another kind (depth-2 shifts: "shift_register")
    bit_alt: dict | None = None       # {bit index: [alt kinds]}
    flex: bool = False                # FSM state: synthesis may re-encode it (width from the netlist)
    modes: list | None = None         # other update modes (LFSR/CRC), recorded in provenance
    note: str | None = None
    head_sym: list | None = None      # per lane, stage 0's source as a symbolic EXPR (claims), for logic heads;
    #                                   an entry may be a callable bit -> EXPR (bit(register, index): an RTL bit)
    claim_when: dict | None = None    # the claims' defining condition when it differs from `when`
    rtl_form: str | None = None       # LFSR/CRC: the RTL's form when params.form is "both" (a trinomial)

    @property
    def vec(self):
        return self.rtl or self.name

    def rtl_bit_names(self):
        if self.rtl_bits is None and self.rtl is None and self.width == 1 and not self.flex:
            return [self.name]
        idx = self.rtl_bits if self.rtl_bits is not None else range(self.width)
        return [f"{self.vec}[{i}]" for i in idx]


@dataclasses.dataclass
class Check:
    """Model check: fn(S, I) -> {register or RTL vector: expected next value (int array), or
    (expected, lane mask)}; S and I hold current register values and input pin values per lane."""
    name: str
    fn: object
    inputs: dict = dataclasses.field(default_factory=dict)
    domain: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class Design:
    name: str
    family: str
    desc: str
    rtl: str
    regs: list
    checks: list = dataclasses.field(default_factory=list)
    units: list = dataclasses.field(default_factory=list)
    quiet: dict = dataclasses.field(default_factory=dict)   # inputs that keep every reset inactive
    notes: list = dataclasses.field(default_factory=list)   # known disagreements with S3 definitions
    counter_negatives: list = dataclasses.field(default_factory=list)  # (register, width, step fn)
    lfsr_models: dict = dataclasses.field(default_factory=dict)  # register -> one-step fn (poly check)
    facts: list = dataclasses.field(default_factory=list)   # (register, label, fn() -> {"ok", ...}): model facts
    cohort: int = 1                                          # 1: first corpus; 2: added after review[2]


class OwnHead:
    """A lane head computed from the design's own registers (NLFSR / de Bruijn feedback): fn(S, I)
    is its value per lane for the simulation check, sym(bit) its EXPR for the claims, where
    bit(register, index) is the EXPR of that RTL bit."""

    def __init__(self, fn, sym, text):
        self.fn, self.sym, self.text = fn, sym, text

    def __repr__(self):
        return f"OwnHead({self.text})"


# ----------------------------------------------------------------------------------------------
# small helpers shared by the generators

RST_PORT = {"async": ["input rst_n"], "sync": ["input rst"], "none": []}
QUIET = {"async": {"rst_n": 1}, "sync": {"rst": 0}, "none": {}}


def module(ports, body, name="top"):
    return f"module {name}(\n    " + ",\n    ".join(ports) + "\n);\n" + body.rstrip("\n") + "\nendmodule\n"


def seq(reset, resets, body, ind=2):
    """An always block clocked by clk: `resets` are the reset statements, `body` the update."""
    sp = " " * ind
    b = textwrap.indent(textwrap.dedent(body).strip("\n"), sp + "    ")
    if reset == "none" or not resets:
        return f"{sp}always @(posedge clk) begin\n{b}\n{sp}end\n"
    r = textwrap.indent("\n".join(resets), sp + "    ")
    head = "always @(posedge clk or negedge rst_n)\n" + sp + "  if (!rst_n) begin" if reset == "async" else \
        "always @(posedge clk)\n" + sp + "  if (rst) begin"
    return f"{sp}{head}\n{r}\n{sp}  end else begin\n{b}\n{sp}  end\n"


def d(w, v):
    return f"{w}'d{v}"


def h(w, v):
    return f"{w}'h{v:X}"


def par(x):
    """Parity of each non-negative int64 (< 2^63)."""
    x = x ^ (x >> 32)
    x = x ^ (x >> 16)
    x = x ^ (x >> 8)
    x = x ^ (x >> 4)
    x = x ^ (x >> 2)
    x = x ^ (x >> 1)
    return x & 1


def W(c, a, b):
    return np.where(c != 0, a, b)


def bits_of(name, idxs):
    return [(name, i) for i in idxs]


def creg(name, w, direction="up", step=1, modulus="natural", saturating=False, load=False, **kw):
    """A counter register -- except at width 1, where TOGGLE_RULE makes it a flag that accepts
    counter (the rule out/s3/truth_tempo.json and the blind labeller already apply). The params are
    kept and still checked as a counter's (check_as), so the corpus still proves the toggle counts;
    what changes is the published kind, and so the scored denominator and the reference result."""
    if modulus == "natural":
        modulus = 1 << w
    params = dict(direction=direction, step=step, modulus=modulus, saturating=saturating, load=load)
    if w == 1:
        kw.setdefault("alt_kinds", ("counter",))
        kw.setdefault("alt_reason", TOGGLE_RULE)
        kw.setdefault("check_as", "counter")
        return Reg(name, w, "flag", params, **kw)
    return Reg(name, w, "counter", params, **kw)


def sreg(name, width, lanes, direction, serial_in, kind="shift_register", **kw):
    """lanes: per lane the bit indices in stage order (stage 0 first)."""
    params = {"lanes": len(lanes), "depth": len(lanes[0]), "direction": direction, "serial_in": serial_in,
              "order": [bits_of(name, lane) for lane in lanes]}
    return Reg(name, width, kind, params, **kw)


def yreg(name, width, lanes, sources, **kw):
    """Synchronizer: lanes of stage bit indices; sources: per lane the input pin (check only)."""
    return Reg(name, width, "synchronizer", {"stages": len(lanes[0]), "order": [bits_of(name, lane) for lane in lanes]},
               head=[f"port:{s}" for s in sources], **kw)


def is_trinomial(poly):
    return isinstance(poly, int) and not isinstance(poly, bool) and bin(poly).count("1") == 3


def lreg(name, w, form, poly, k, n_inputs, **kw):
    """An LFSR/CRC register. A trinomial's one-step matrix has one tap row and one tap column, so its
    Fibonacci and Galois forms coincide: params.form is "both" and rtl_form keeps the RTL's form."""
    if form in ("fibonacci", "galois") and is_trinomial(poly):
        kw.setdefault("rtl_form", form)
        form = "both"
    return Reg(name, w, "lfsr_crc", dict(form=form, poly=poly, k_steps=k, n_inputs=n_inputs), **kw)


def rng_(lo, hi):
    """The register domain [lo, hi) (a range: large domains are sampled and cube-covered, never listed)."""
    return range(lo, hi)


def unit(name, kind, registers, reason, flops=None, params=None, head=None, when=None):
    """A declared lenient unit; `head` (per lane, stage 0's source) and `when` (the shift condition)
    are used by the check only."""
    u = {"name": name, "kind": kind, "registers": list(registers), "reason": reason}
    if flops is not None:
        u["flops"] = flops
    if params is not None:
        u["params"] = params
    if head is not None:
        u["_head"] = head
    if when is not None:
        u["_when"] = when
    return u


def lanes_msb(lanes, depth):
    """Bit indices per lane of a register shifted as {sr[W-lanes-1:0], in}: stage 0 lowest."""
    return [[k * lanes + j for k in range(depth)] for j in range(lanes)]


def lanes_lsb(lanes, depth):
    """... shifted as {in, sr[W-1:lanes]}: stage 0 is the top slice."""
    return [[(depth - 1 - k) * lanes + j for k in range(depth)] for j in range(lanes)]


def pin(port, width, j):
    return f"port:{port}" if width == 1 else f"port:{port}[{j}]"


# ----------------------------------------------------------------------------------------------
# design generators: counters


def g_counter(name, w, reset="async", rv=0, en="if", dirn="up", step=1, mod=None, sat=None, load=None, K=5,
              setv=None, cmp="eq", out="all", family="counter_binary", desc=""):
    """Binary counters. en: None | "if" | "carry"; dirn: up | down | updown; mod: modulus by compare
    (else natural wrap); sat: saturate instead of wrapping (up: at `sat`, down: at 0, updown: both);
    load: None | "opaque" (din) | "relative" (+K) | "both" | "const" (clear to 0 / set to setv)."""
    ports = ["input clk"] + RST_PORT[reset]
    if en:
        ports.append("input en")
    if dirn == "updown":
        ports.append("input dir_up")
    if load in ("opaque", "both"):
        ports += ["input ld", f"input [{w - 1}:0] din"]
    if load in ("relative", "both"):
        ports.append("input skip")
    if load == "const":
        ports += ["input clr", "input set"]
    tcv = 0 if dirn == "down" else (sat if sat is not None else (mod - 1 if mod else (1 << w) - 1))
    ports.append(f"output [{w - 1}:0] q" if out == "all" else "output tc")
    E = "en" if en == "if" else None

    def guard(*xs):
        return " && ".join(x for x in (E,) + xs if x)

    if en == "carry":
        pad = f"{{{w - 1}'d0, en}}"
        stmt = f"c <= c {'+' if dirn == 'up' else '-'} {pad};"
    elif sat is not None:
        if dirn == "up":
            stmt = f"if ({guard(f'c != {d(w, sat)}')}) c <= c + {d(w, 1)};"
        elif dirn == "down":
            stmt = f"if ({guard(f'c != {d(w, 0)}')}) c <= c - {d(w, 1)};"
        else:
            stmt = (f"if ({guard('dir_up', f'c != {d(w, sat)}')}) c <= c + {d(w, 1)};\n"
                    f"else if ({guard('!dir_up', f'c != {d(w, 0)}')}) c <= c - {d(w, 1)};")
    else:
        if mod:
            upx = f"(c {'==' if cmp == 'eq' else '>='} {d(w, mod - 1)}) ? {d(w, 0)} : c + {d(w, 1)}"
            dnx = f"(c == {d(w, 0)}) ? {d(w, mod - 1)} : c - {d(w, 1)}"
        else:
            upx, dnx = f"c + {d(w, step)}", f"c - {d(w, step)}"
        nxt = {"up": upx, "down": dnx, "updown": f"dir_up ? ({upx}) : ({dnx})"}[dirn]
        stmt = f"if (en) c <= {nxt};" if E else f"c <= {nxt};"
    pre = []
    if load in ("opaque", "both"):
        pre.append("if (ld) c <= din;")
    if load in ("relative", "both"):
        pre.append(f"if (skip) c <= c + {d(w, K)};")
    if load == "const":
        pre += [f"if (clr) c <= {d(w, 0)};", f"if (set) c <= {d(w, setv)};"]
    if pre:
        body = "\n".join(("else " if i else "") + p for i, p in enumerate(pre))
        body += "\nelse begin\n" + textwrap.indent(stmt, "  ") + "\nend"
    else:
        body = stmt
    rtl = module(ports, f"  reg [{w - 1}:0] c;\n" + seq(reset, [f"c <= {d(w, rv)};"], body) +
                 (f"  assign q = c;\n" if out == "all" else f"  assign tc = (c == {d(w, tcv)});\n"))
    msk = (1 << w) - 1

    def model(S, I):
        c = S["c"]
        e = I["en"] if en else np.ones_like(c)
        if en == "carry":
            n = (c + e) & msk if dirn == "up" else (c - e) & msk
        elif sat is not None:
            upok, dnok = c != sat, c != 0
            if dirn == "up":
                n = W((e == 1) & upok, c + 1, c)
            elif dirn == "down":
                n = W((e == 1) & dnok, c - 1, c)
            else:
                u = I["dir_up"]
                n = W((e == 1) & (u == 1) & upok, c + 1, W((e == 1) & (u == 0) & dnok, c - 1, c))
            n = n & msk
        else:
            if mod:
                upv = W((c == mod - 1) if cmp == "eq" else (c >= mod - 1), 0, c + 1) & msk
                dnv = W(c == 0, mod - 1, c - 1) & msk
            else:
                upv, dnv = (c + step) & msk, (c - step) & msk
            nx = upv if dirn == "up" else dnv if dirn == "down" else W(I["dir_up"] == 1, upv, dnv)
            n = W(e == 1, nx, c)
        if load == "const":
            n = W(I["set"] == 1, setv, n)
            n = W(I["clr"] == 1, 0, n)
        if load in ("relative", "both"):
            n = W(I["skip"] == 1, (c + K) & msk, n)
        if load in ("opaque", "both"):
            n = W(I["ld"] == 1, I["din"], n)
        return {"c": n}

    dom = list(range(mod)) if mod else (list(range(sat + 1)) if sat is not None and dirn != "down" else None)
    quiet = dict(QUIET[reset])
    base = dict({"en": 1} if en else {})
    base.update({k: 0 for k, on in (("ld", load in ("opaque", "both")), ("skip", load in ("relative", "both")),
                                    ("clr", load == "const"), ("set", load == "const")) if on})
    up_in = dict(base, **({"dir_up": 1} if dirn == "updown" else {}))
    if mod:
        up_dom = dn_dom = list(range(mod))
    elif sat is not None:
        up_dom, dn_dom = list(range(sat)), list(range(1, (sat if dirn == "updown" else msk) + 1))
    else:
        up_dom = dn_dom = None
    when = {"inputs": up_in if dirn != "down" else base, "domain": {"c": up_dom if dirn != "down" else dn_dom}}
    when_down = {"inputs": dict(base, dir_up=0), "domain": {"c": dn_dom}} if dirn == "updown" else None
    modulus = mod if mod else (None if sat is not None else 1 << w)
    rule = {"up": "+step per enabled clock", "down": "-step per enabled clock", "updown": "+1 / -1 by `dir_up`"}[dirn]
    if mod:
        rule += f", wraps at {mod} by compare"
    if sat is not None:
        rule += ", saturates" + (f" at {sat}" if dirn != "down" else " at 0") + (" and 0" if dirn == "updown" else "")
    if load:
        rule += {"opaque": "; loads din", "relative": f"; +{K} on skip (relative load)",
                 "both": f"; loads din, +{K} on skip", "const": f"; constant loads 0 and {setv}"}[load]
    if en == "carry":
        rule += "; the enable enters the adder's carry"
    # saturating: the top as an int when it is below 2^w - 1 (verify.py v2 reads true as 2^w - 1)
    reg = creg("c", w, direction=dirn, step=step, modulus=modulus,
               saturating=sat if sat is not None and dirn != "down" and sat < (1 << w) - 1 else sat is not None,
               load=load in ("opaque", "relative", "both"), rule=rule,
               when={"inputs": dict(when["inputs"]), "domain": {k: v for k, v in when["domain"].items() if v}},
               when_down=None if when_down is None else
               {"inputs": when_down["inputs"], "domain": {k: v for k, v in when_down["domain"].items() if v}})
    return Design(name, family, desc or f"{w}-bit {dirn} counter ({rule}); reset {reset}", rtl, [reg],
                  [Check("model", model, domain={"c": dom} if dom else {})], quiet=quiet)


def g_limit(name, w, mode):
    """Up counter bounded by a register: stops at (mode "stop") or wraps after (mode "wrap") lim."""
    ports = ["input clk", "input rst_n", "input en", "input clr", "input lim_we", f"input [{w - 1}:0] din",
             f"output [{w - 1}:0] q", "output at_lim"]
    upd = (f"if (en && c != lim) c <= c + {d(w, 1)};" if mode == "stop" else
           f"if (en) c <= (c == lim) ? {d(w, 0)} : c + {d(w, 1)};")
    body = (f"  reg [{w - 1}:0] lim;\n  reg [{w - 1}:0] c;\n" +
            seq("async", [f"lim <= {d(w, (1 << w) - 1)};"], "if (lim_we) lim <= din;") +
            seq("async", [f"c <= {d(w, 0)};"], f"if (clr) c <= {d(w, 0)};\nelse {upd}") +
            "  assign q = c;\n  assign at_lim = (c == lim);\n")
    top_v = (1 << w) - 1

    def model(S, I):
        c, lim = S["c"], S["lim"]
        if mode == "stop":
            n = W((I["en"] == 1) & (c != lim), c + 1, c)
        else:
            n = W(I["en"] == 1, W(c == lim, 0, c + 1), c)
        return {"c": W(I["clr"] == 1, 0, n & top_v), "lim": W(I["lim_we"] == 1, I["din"], lim)}

    regs = [creg("c", w, modulus=None, saturating=None if mode == "stop" else False,
                 rule=f"+1 per enabled clock, {'stops at' if mode == 'stop' else 'wraps to 0 after'} the value of "
                      "register lim (a bound held in a register: modulus and saturation null)",
                 when={"inputs": {"en": 1, "clr": 0}, "domain": {"lim": [top_v], "c": list(range(top_v))}}),
            Reg("lim", w, "data_register", rule="loaded from din on lim_we")]
    return Design(name, "counter_saturating" if mode == "stop" else "counter_modulo",
                  f"{w}-bit up counter that {mode}s at a register-held bound", module(ports, body), regs,
                  [Check("model", model)], quiet=QUIET["async"])


def g_casc_10x6_done():
    ports = ["input clk", "input rst_n", "input en", "input clr", "output [3:0] lo_o", "output [2:0] hi_o",
             "output done_o"]
    body = ("  reg [3:0] lo;\n  reg [2:0] hi;\n  reg done;\n"
            "  wire lo_wrap = (lo == 4'd9);\n  wire hi_wrap = (hi == 3'd5);\n" +
            seq("async", ["lo <= 4'd0;", "hi <= 3'd0;", "done <= 1'b0;"], """
                if (clr) begin
                  lo <= 4'd0; hi <= 3'd0; done <= 1'b0;
                end else if (en && !done) begin
                  lo <= lo_wrap ? 4'd0 : lo + 4'd1;
                  if (lo_wrap) hi <= hi_wrap ? 3'd0 : hi + 3'd1;
                  if (lo_wrap && hi_wrap) done <= 1'b1;
                end""") +
            "  assign lo_o = lo;\n  assign hi_o = hi;\n  assign done_o = done;\n")

    def model(S, I):
        lo, hi, dn = S["lo"], S["hi"], S["done"]
        act = (I["en"] == 1) & (dn == 0)
        clr = I["clr"] == 1
        return {"lo": W(clr, 0, W(act, W(lo == 9, 0, lo + 1), lo)),
                "hi": W(clr, 0, W(act & (lo == 9), W(hi == 5, 0, hi + 1), hi)),
                "done": W(clr, 0, W(act & (lo == 9) & (hi == 5), 1, dn))}

    regs = [creg("lo", 4, modulus=10, rule="mod-10 digit, +1 per enabled clock until done",
                 when={"inputs": {"en": 1, "clr": 0}, "domain": {"done": [0], "lo": list(range(10))}}),
            creg("hi", 3, modulus=6, rule="mod-6 digit, +1 when lo wraps",
                 when={"inputs": {"en": 1, "clr": 0}, "domain": {"done": [0], "lo": [9], "hi": list(range(6))}}),
            Reg("done", 1, "flag", rule="sticky terminal flag: set on the 60th count, freezes the digits (cleared by clr)")]
    units = [unit("lo + hi as one counter", "counter", ["lo", "hi"],
                  "one mod-60 counter written as two cascaded digits (hi counts lo's wraps)",
                  params={"direction": "up", "step": 1, "modulus": 60, "saturating": False, "load": False,
                          "bit_order": None}),
             unit("lo + hi + done as one one-shot counter", "counter", ["lo", "hi", "done"],
                  "the 60th count sets done, which freezes the digits at 0: a one-shot sweep",
                  params={"direction": "up", "step": 1, "modulus": None, "saturating": True, "load": False,
                          "bit_order": None})]
    return Design("casc_mod10x6_done_ar", "counter_cascade", "mod-10 and mod-6 digits in cascade with a sticky done flag",
                  module(ports, body), regs,
                  [Check("model", model, domain={"lo": list(range(10)), "hi": list(range(6))})], units,
                  quiet=QUIET["async"])


def g_casc_bcd3():
    sub = module(["input clk", "input rst", "input ci", "output reg [3:0] d", "output co"],
                 "  assign co = ci & (d == 4'd9);\n" +
                 seq("sync", ["d <= 4'd0;"], "if (ci) d <= (d == 4'd9) ? 4'd0 : d + 4'd1;"), name="bcd")
    ports = ["input clk", "input rst", "input en", "input clr_ovf", "output [11:0] q", "output ovf"]
    body = ("  wire c0, c1, c2;\n"
            "  bcd u0 (.clk(clk), .rst(rst), .ci(en), .d(q[3:0]), .co(c0));\n"
            "  bcd u1 (.clk(clk), .rst(rst), .ci(c0), .d(q[7:4]), .co(c1));\n"
            "  bcd u2 (.clk(clk), .rst(rst), .ci(c1), .d(q[11:8]), .co(c2));\n"
            "  reg ovf_r;\n" + seq("sync", ["ovf_r <= 1'b0;"], "if (clr_ovf) ovf_r <= 1'b0;\nelse if (c2) ovf_r <= 1'b1;") +
            "  assign ovf = ovf_r;\n")

    def model(S, I):
        a, b, c, o = S["u0.d"], S["u1.d"], S["u2.d"], S["ovf_r"]
        e = I["en"] == 1
        c0 = e & (a == 9)
        c1 = c0 & (b == 9)
        c2 = c1 & (c == 9)
        inc = lambda x, go: W(go, W(x == 9, 0, x + 1), x)  # noqa: E731
        return {"u0.d": inc(a, e), "u1.d": inc(b, c0), "u2.d": inc(c, c1),
                "ovf_r": W(I["clr_ovf"] == 1, 0, W(c2, 1, o))}

    dig = list(range(10))
    regs = [creg(f"u{i}.d", 4, modulus=10, module_def="bcd", local="d",
                 rule="BCD digit (submodule bcd): +1 on its carry in, wraps at 10",
                 when={"inputs": {"en": 1}, "domain": dict({f"u{j}.d": [9] for j in range(i)}, **{f"u{i}.d": dig})})
            for i in range(3)]
    regs.append(Reg("ovf_r", 1, "flag", rule="sticky overflow of the three digits"))
    units = [unit("three BCD digits as one counter", "counter", ["u0.d", "u1.d", "u2.d"],
                  "one mod-1000 counter written as three cascaded BCD digits (submodule instances)",
                  params={"direction": "up", "step": 1, "modulus": 1000, "saturating": False, "load": False,
                          "bit_order": None})]
    return Design("casc_bcd3_sr", "counter_cascade", "three cascaded BCD digit submodules and a sticky overflow flag",
                  sub + module(ports, body), regs,
                  [Check("model", model, domain={"u0.d": dig, "u1.d": dig, "u2.d": dig})], units, quiet=QUIET["sync"])


def g_casc_simple(name, reset, lo_w, lo_m, hi_w, hi_m, pulse=False):
    """lo counts enabled clocks (mod lo_m), hi counts lo's wraps (mod hi_m, natural when 2^hi_w)."""
    R = "async" if reset == "async" else "sync"
    ports = ["input clk"] + RST_PORT[R] + ["input en", f"output [{lo_w + hi_w - 1}:0] q"]
    if pulse:
        ports.append("output done")
    lo_wrap = f"(lo == {d(lo_w, lo_m - 1)})"
    hi_next = (f"(hi == {d(hi_w, hi_m - 1)}) ? {d(hi_w, 0)} : hi + {d(hi_w, 1)}" if hi_m != 1 << hi_w
               else f"hi + {d(hi_w, 1)}")
    lo_next = (f"{lo_wrap} ? {d(lo_w, 0)} : lo + {d(lo_w, 1)}" if lo_m != 1 << lo_w else f"lo + {d(lo_w, 1)}")
    upd = f"if (en) begin\n  lo <= {lo_next};\n  if ({lo_wrap}) hi <= {hi_next};\nend"
    resets = [f"lo <= {d(lo_w, 0)};", f"hi <= {d(hi_w, 0)};"]
    if pulse:
        upd = f"done_r <= en && {lo_wrap} && (hi == {d(hi_w, hi_m - 1)});\n" + upd
        resets.append("done_r <= 1'b0;")
    body = (f"  reg [{lo_w - 1}:0] lo;\n  reg [{hi_w - 1}:0] hi;\n" + ("  reg done_r;\n" if pulse else "") +
            seq(R, resets, upd) + "  assign q = {hi, lo};\n" + ("  assign done = done_r;\n" if pulse else ""))

    def model(S, I):
        lo, hi = S["lo"], S["hi"]
        e = I["en"] == 1
        w_ = e & (lo == lo_m - 1)
        out = {"lo": W(e, W(lo == lo_m - 1, 0, lo + 1), lo) & ((1 << lo_w) - 1),
               "hi": W(w_, W(hi == hi_m - 1, 0, hi + 1), hi) & ((1 << hi_w) - 1)}
        if pulse:
            out["done_r"] = (w_ & (hi == hi_m - 1)).astype(np.int64)
        return out

    regs = [creg("lo", lo_w, modulus=lo_m, rule=f"low digit: +1 per enabled clock, mod {lo_m}",
                 when={"inputs": {"en": 1}, "domain": {"lo": list(range(lo_m))}}),
            creg("hi", hi_w, modulus=hi_m, rule=f"high digit: +1 when lo wraps, mod {hi_m}",
                 when={"inputs": {"en": 1}, "domain": {"lo": [lo_m - 1], "hi": list(range(hi_m))}})]
    if pulse:
        regs.append(Reg("done_r", 1, "flag", rule="registered terminal-count pulse (not sticky)"))
    units = [unit("lo + hi as one counter", "counter", ["lo", "hi"],
                  f"one mod-{lo_m * hi_m} counter written as two cascaded digits",
                  params={"direction": "up", "step": 1, "modulus": lo_m * hi_m, "saturating": False, "load": False,
                          "bit_order": None})]
    return Design(name, "counter_cascade", f"mod-{lo_m} prescaler feeding a mod-{hi_m} counter" +
                  (" with a terminal pulse" if pulse else ""), module(ports, body), regs,
                  [Check("model", model, domain={"lo": list(range(lo_m)), "hi": list(range(hi_m))})], units,
                  quiet=QUIET[R])


def g_bins8():
    ports = ["input clk", "input rst_n", "input stb", "input hit", "input [2:0] idx", "input clr",
             "input [2:0] ridx", "output [1:0] rdata"]
    body = ("  reg hit_q;\n  reg [2:0] idx_q;\n" +
            seq("async", ["hit_q <= 1'b0;", "idx_q <= 3'd0;"], "hit_q <= stb & hit;\nif (stb) idx_q <= idx;") +
            "  wire [15:0] all;\n  genvar i;\n  generate for (i = 0; i < 8; i = i + 1) begin : g\n"
            "    reg [1:0] c;\n" +
            seq("async", ["c <= 2'd0;"], "if (clr) c <= 2'd0;\nelse if (hit_q && idx_q == i && c != 2'd3) c <= c + 2'd1;",
                ind=4) +
            "    assign all[2*i+1:2*i] = c;\n  end endgenerate\n  assign rdata = all[2*ridx +: 2];\n")

    def model(S, I):
        out = {"hit_q": I["stb"] & I["hit"], "idx_q": W(I["stb"] == 1, I["idx"], S["idx_q"])}
        for i in range(8):
            c = S[f"g[{i}].c"]
            out[f"g[{i}].c"] = W(I["clr"] == 1, 0, W((S["hit_q"] == 1) & (S["idx_q"] == i) & (c != 3), c + 1, c))
        return out

    regs = [Reg("hit_q", 1, "flag", rule="registered strobe & hit"),
            Reg("idx_q", 3, "data_register", rule="bin index captured on stb")]
    regs += [creg(f"g[{i}].c", 2, modulus=None, saturating=True, local="g[*].c",
                  rule=f"2-bit saturating hit counter of bin {i}: +1 when the registered index decodes to {i}",
                  when={"inputs": {"clr": 0}, "domain": {"hit_q": [1], "idx_q": [i], f"g[{i}].c": [0, 1, 2]}})
             for i in range(8)]
    return Design("sat_bins8_decode_ar", "counter_saturating",
                  "eight 2-bit saturating hit counters selected by a decode of a registered index",
                  module(ports, body), regs, [Check("model", model)], quiet=QUIET["async"])


def g_bins4_updown():
    ports = ["input clk", "input rst", "input upd", "input taken", "input [1:0] idx", "input [1:0] ridx",
             "output pred"]
    body = ("  wire [7:0] ctr;\n  genvar i;\n  generate for (i = 0; i < 4; i = i + 1) begin : g\n    reg [1:0] c;\n" +
            seq("sync", ["c <= 2'd1;"], """
                if (upd && idx == i) begin
                  if (taken) begin
                    if (c != 2'd3) c <= c + 2'd1;
                  end else if (c != 2'd0) c <= c - 2'd1;
                end""", ind=4) +
            "    assign ctr[2*i+1:2*i] = c;\n  end endgenerate\n  assign pred = ctr[2*ridx+1];\n")

    def model(S, I):
        out = {}
        for i in range(4):
            c = S[f"g[{i}].c"]
            sel = (I["upd"] == 1) & (I["idx"] == i)
            out[f"g[{i}].c"] = W(sel & (I["taken"] == 1) & (c != 3), c + 1, W(sel & (I["taken"] == 0) & (c != 0), c - 1, c))
        return out

    regs = [creg(f"g[{i}].c", 2, direction="updown", modulus=None, saturating=True, local="g[*].c",
                 rule=f"2-bit up/down saturating counter (predictor entry {i}) under an index decode",
                 when={"inputs": {"upd": 1, "taken": 1, "idx": i}, "domain": {f"g[{i}].c": [0, 1, 2]}},
                 when_down={"inputs": {"upd": 1, "taken": 0, "idx": i}, "domain": {f"g[{i}].c": [1, 2, 3]}})
            for i in range(4)]
    return Design("sat_bins4_updown_sr", "counter_saturating",
                  "four 2-bit up/down saturating counters (a predictor table) under an index decode",
                  module(ports, body), regs, [Check("model", model)], quiet=QUIET["sync"])


def g_bins6_vec():
    ports = ["input clk", "input rst_n", "input hit", "input [2:0] idx", "input [2:0] ridx", "output [1:0] rdata"]
    body = ("  reg [11:0] bins;\n  integer i;\n" +
            seq("async", ["bins <= 12'd0;"], """
                for (i = 0; i < 6; i = i + 1)
                  if (hit && idx == i && bins[2*i +: 2] != 2'd3) bins[2*i +: 2] <= bins[2*i +: 2] + 2'd1;""") +
            "  assign rdata = bins[2*ridx +: 2];\n")

    def model(S, I):
        v = S["bins"]
        n = v.copy()
        for i in range(6):
            c = (v >> (2 * i)) & 3
            inc = (I["hit"] == 1) & (I["idx"] == i) & (c != 3)
            n = W(inc, (n & ~(3 << (2 * i))) | ((c + 1) << (2 * i)), n)
        return {"bins": n}

    regs = [creg(f"bins[{2 * i + 1}:{2 * i}]", 2, modulus=None, saturating=True, rtl="bins", rtl_bits=(2 * i, 2 * i + 1),
                 local="bins[*]", rule=f"slice {i} of one 12-bit vector: a 2-bit saturating counter under a decode",
                 when={"inputs": {"hit": 1, "idx": i}, "domain": {"bins": [c << (2 * i) for c in range(3)]}})
            for i in range(6)]
    return Design("sat_bins6_vec_ar", "counter_saturating",
                  "six 2-bit saturating counters written as slices of one vector in a for loop",
                  module(ports, body), regs, [Check("model", model)], quiet=QUIET["async"])


def g_toggles():
    out = []
    # 1. toggle with enable
    body = "  reg t;\n" + seq("async", ["t <= 1'b0;"], "t <= t ^ en;") + "  assign qo = t;\n"
    out.append(Design("toggle_en_ar", "counter_toggle", "a 1-bit toggle with enable (t <= t ^ en)",
                      module(["input clk", "input rst_n", "input en", "output qo"], body),
                      [creg("t", 1, rule="1-bit toggle: flips on en", when={"inputs": {"en": 1}})],
                      [Check("model", lambda S, I: {"t": S["t"] ^ I["en"]})], quiet=QUIET["async"]))
    # 2. free-running divide-by-2 without reset
    body = "  reg t;\n" + seq("none", None, "t <= ~t;") + "  assign qo = t;\n"
    out.append(Design("toggle_free_nr", "counter_toggle", "a free-running 1-bit toggle without reset (divide by 2)",
                      module(["input clk", "output qo"], body),
                      [creg("t", 1, rule="1-bit toggle every clock", when={"inputs": {}})],
                      [Check("model", lambda S, I: {"t": S["t"] ^ 1})]))
    # 3. four independent toggles and a toggle on a counter's wrap
    body = ("  genvar i;\n  generate for (i = 0; i < 4; i = i + 1) begin : g\n    reg t;\n" +
            seq("sync", ["t <= 1'b0;"], "if (e[i]) t <= ~t;", ind=4) + "    assign tq[i] = t;\n  end endgenerate\n"
            "  reg [2:0] cnt;\n  reg led;\n" +
            seq("sync", ["cnt <= 3'd0;", "led <= 1'b0;"], "if (run) begin\n  cnt <= cnt + 3'd1;\n  if (cnt == 3'd7) led <= ~led;\nend") +
            "  assign led_o = led;\n")

    def model(S, I):
        o = {f"g[{i}].t": S[f"g[{i}].t"] ^ ((I["e"] >> i) & 1) for i in range(4)}
        r = I["run"] == 1
        o["cnt"] = W(r, (S["cnt"] + 1) & 7, S["cnt"])
        o["led"] = W(r & (S["cnt"] == 7), S["led"] ^ 1, S["led"])
        return o

    regs = [creg(f"g[{i}].t", 1, local="g[*].t", rule=f"1-bit toggle on e[{i}]", when={"inputs": {"e": 1 << i}})
            for i in range(4)]
    regs += [creg("cnt", 3, rule="free-running 3-bit counter under run", when={"inputs": {"run": 1}}),
             creg("led", 1, rule="1-bit toggle when cnt wraps", when={"inputs": {"run": 1}, "domain": {"cnt": [7]}})]
    out.append(Design("toggle_multi_sr", "counter_toggle", "four independent toggles and a toggle on a counter's wrap",
                      module(["input clk", "input rst", "input [3:0] e", "input run", "output [3:0] tq", "output led_o"],
                             body), regs, [Check("model", model)], quiet=QUIET["sync"]))
    return out


def _gray2bin(g, w):
    b = g.copy()
    s = g >> 1
    while np.any(s):
        b ^= s
        s >>= 1
    return b


def g_gray_family():
    out = []
    # Gray-coded counter state: kind other (a counter only after Gray decoding)
    body = ("  reg [3:0] g;\n  wire [3:0] b = {g[3], g[3]^g[2], g[3]^g[2]^g[1], g[3]^g[2]^g[1]^g[0]};\n"
            "  wire [3:0] b1 = b + 4'd1;\n" + seq("async", ["g <= 4'd0;"], "if (en) g <= b1 ^ (b1 >> 1);") +
            "  assign q = g;\n")

    def gstep(g):
        b1 = (_gray2bin(g, 4) + 1) & 15
        return b1 ^ (b1 >> 1)

    out.append(Design("gray_w4_en_ar", "negative_gray", "a 4-bit counter kept in Gray code (negative for counter)",
                      module(["input clk", "input rst_n", "input en", "output [3:0] q"], body),
                      [Reg("g", 4, "other", rule="Gray-code counter: +1 only after Gray decoding; no bit order and "
                                                 "polarity makes every transition +1/-1 (checked exhaustively)")],
                      [Check("model", lambda S, I: {"g": W(I["en"] == 1, gstep(S["g"]), S["g"])})],
                      quiet=QUIET["async"], counter_negatives=[("g", 4, gstep)]))
    # binary pointer with a registered Gray copy (async FIFO style)
    body = ("  reg [4:0] b;\n  reg [4:0] gp;\n  wire [4:0] bn = b + 5'd1;\n" +
            seq("async", ["b <= 5'd0;", "gp <= 5'd0;"], "if (inc) begin\n  b <= bn;\n  gp <= bn ^ (bn >> 1);\nend") +
            "  assign q = b;\n  assign gq = gp;\n")

    def gp_model(S, I):
        bn = (S["b"] + 1) & 31
        e = I["inc"] == 1
        return {"b": W(e, bn, S["b"]), "gp": W(e, bn ^ (bn >> 1), S["gp"])}

    out.append(Design("gray_ptr_w5_ar", "negative_gray", "binary pointer and a registered Gray copy of its next value",
                      module(["input clk", "input rst_n", "input inc", "output [4:0] q", "output [4:0] gq"], body),
                      [creg("b", 5, rule="binary pointer, +1 on inc", when={"inputs": {"inc": 1}}),
                       Reg("gp", 5, "data_register", rule="Gray code of b's next value, loaded with b (a function of "
                                                          "another register, not of itself)")],
                      [Check("model", gp_model)], quiet=QUIET["async"]))
    # Johnson counters
    for name, w, reset, en in (("johnson_w4_ar", 4, "async", False), ("johnson_w8_en_sr", 8, "sync", True)):
        upd = f"j <= {{j[{w - 2}:0], ~j[{w - 1}]}};"
        body = f"  reg [{w - 1}:0] j;\n" + seq(reset, [f"j <= {d(w, 0)};"], f"if (en) {upd}" if en else upd) + \
            "  assign q = j;\n"
        m = (1 << w) - 1

        def jm(S, I, w=w, m=m, en=en):
            nx = ((S["j"] << 1) & m) | (1 - ((S["j"] >> (w - 1)) & 1))
            return {"j": W(I["en"] == 1, nx, S["j"]) if en else nx}

        out.append(Design(name, "gray_johnson_ring", f"{w}-bit Johnson (twisted ring) counter" + (" with enable" if en else ""),
                          module(["input clk"] + RST_PORT[reset] + (["input en"] if en else []) + [f"output [{w - 1}:0] q"],
                                 body),
                          [sreg("j", w, [list(range(w))], "to_msb", [("j", w - 1)], alt_kinds=("lfsr_crc",),
                                alt_reason="Johnson counter: stage 0 takes the complement of the last stage, so the "
                                           "update is GF(2)-affine in its own bits (an LFSR candidate by section 3.3)",
                                serial_inv=(True,), rule="stage k copies stage k-1; stage 0 takes ~last stage",
                                when={"inputs": {"en": 1} if en else {}})],
                          [Check("model", jm)], quiet=QUIET[reset], notes=[FEEDBACK_NOTE]))
    body = "  reg [5:0] r;\n" + seq("async", ["r <= 6'b000001;"], "r <= {r[4:0], r[5]};") + "  assign q = r;\n"
    out.append(Design("ring_w6_ar", "gray_johnson_ring", "6-bit one-hot ring counter (rotate)",
                      module(["input clk", "input rst_n", "output [5:0] q"], body),
                      [sreg("r", 6, [list(range(6))], "to_msb", [("r", 5)], alt_kinds=("lfsr_crc", "fsm_state"),
                            alt_reason="a rotation is GF(2)-linear in its own bits, and a one-hot ring is also a "
                                       "one-hot state machine", rule="stage k copies stage k-1; stage 0 copies the last",
                            when={"inputs": {}})],
                      [Check("model", lambda S, I: {"r": ((S["r"] << 1) & 63) | (S["r"] >> 5)})],
                      quiet=QUIET["async"], notes=[FEEDBACK_NOTE]))
    return out


# ----------------------------------------------------------------------------------------------
# shift registers


def g_shift(name, lanes, depth, reset, en, direction, rv=0, head="port", out="all", pload=False, kind=None, desc=""):
    Wd = lanes * depth
    ports = ["input clk"] + RST_PORT[reset] + (["input sh"] if en else [])
    if head == "logic":
        ports += [f"input [{lanes - 1}:0] din_a" if lanes > 1 else "input din_a",
                  f"input [{lanes - 1}:0] din_b" if lanes > 1 else "input din_b"]
        sin = "(din_a ^ din_b)"
    else:
        ports.append(f"input [{lanes - 1}:0] din" if lanes > 1 else "input din")
        sin = "din"
    if pload:
        ports += ["input ld", f"input [{Wd - 1}:0] pdata"]
    if out == "all":
        ports.append(f"output [{Wd - 1}:0] q")
    else:
        ports.append(f"output [{lanes - 1}:0] dout" if lanes > 1 else "output dout")
    shx = (f"{{sr[{Wd - lanes - 1}:0], {sin}}}" if direction == "to_msb" else f"{{{sin}, sr[{Wd - 1}:{lanes}]}}")
    upd = f"if (sh) sr <= {shx};" if en else f"sr <= {shx};"
    if pload:
        upd = "if (ld) sr <= pdata;\nelse " + upd
    body = f"  reg [{Wd - 1}:0] sr;\n" + seq(reset, [f"sr <= {h(Wd, rv)};"], upd)
    if out == "all":
        body += "  assign q = sr;\n"
    else:
        body += f"  assign dout = sr[{Wd - 1}:{Wd - lanes}];\n" if direction == "to_msb" else \
            f"  assign dout = sr[{lanes - 1}:0];\n"
    m = (1 << Wd) - 1

    def model(S, I):
        s = S["sr"]
        x = (I["din_a"] ^ I["din_b"]) if head == "logic" else I["din"]
        nx = ((s << lanes) | x) & m if direction == "to_msb" else ((x << (Wd - lanes)) | (s >> lanes)) & m
        n = W(I["sh"] == 1, nx, s) if en else nx
        if pload:
            n = W(I["ld"] == 1, I["pdata"], n)
        return {"sr": n}

    order = lanes_msb(lanes, depth) if direction == "to_msb" else lanes_lsb(lanes, depth)
    serial = None if head == "logic" else [pin("din", lanes, j) for j in range(lanes)]
    headf = hsym = None
    if head == "logic":
        headf = [(lambda I, j=j: ((I["din_a"] ^ I["din_b"]) >> j) & 1) for j in range(lanes)]
        hsym = [{"xor": [{"port": pin("din_a", lanes, j)[5:]}, {"port": pin("din_b", lanes, j)[5:]}]}
                for j in range(lanes)]
    when = {"inputs": dict({"sh": 1} if en else {}, **({"ld": 0} if pload else {}))}
    kind = kind or ("shift_register" if depth >= 3 else "data_register")
    rule = f"{lanes} lane(s) x depth {depth}, {direction}" + (", under sh" if en else ", every clock") + \
        (", parallel load (priority)" if pload else "") + (", head is logic (din_a ^ din_b)" if head == "logic" else "")
    kw = {}
    if depth < 3:
        kw = dict(alt_kinds=("shift_register",), check_as="shift_register",
                  alt_reason="depth-2 shift: S3 reports shift structures from depth 3 and depth-2 transfers as "
                             "relations (docs/S3_DESIGN.md section 3.3)")
    notes = []
    if not en and head == "port" and depth >= 3:
        kw = dict(bit_alt={0: ["synchronizer"], 1: ["synchronizer"]},
                  alt_reason="an unconditional copy chain from a pin: S3 reads stages 1-2 as a synchronizer and "
                             "the rest as a shift structure (docs/S3_DESIGN.md section 1)")
        notes.append("unconditional chain from a primary input: by S3's definitions stages 1-2 are a synchronizer "
                     "and stages 3.. a shift structure; the truth labels the RTL register a shift register and "
                     "accepts synchronizer on bits 0-1 (bits[].alt_kinds)")
    reg = sreg("sr", Wd, order, direction, serial, kind=kind, rule=rule, when=when, head=headf, head_sym=hsym, **kw)
    return Design(name, "shift_register", desc or f"shift register: {rule}; reset {reset}", module(ports, body), [reg],
                  [Check("model", model)], quiet=QUIET[reset], notes=notes)


def g_shift_swapped():
    body = ("  reg [3:0] sr;\n" + seq("async", ["sr <= 4'd0;"],
                                     "if (sh) begin\n  sr[0] <= din;\n  sr[2] <= sr[0];\n  sr[1] <= sr[2];\n"
                                     "  sr[3] <= sr[1];\nend") + "  assign dout = sr[3];\n")

    def model(S, I):
        s = S["sr"]
        b = lambda i: (s >> i) & 1  # noqa: E731
        nx = I["din"] | (b(2) << 1) | (b(0) << 2) | (b(1) << 3)
        return {"sr": W(I["sh"] == 1, nx, s)}

    return Design("sr_swapped_d4_en_ar", "shift_register", "4-stage chain whose stages are not in RTL index order (0,2,1,3)",
                  module(["input clk", "input rst_n", "input sh", "input din", "output dout"], body),
                  [sreg("sr", 4, [[0, 2, 1, 3]], None, ["port:din"], when={"inputs": {"sh": 1}},
                        rule="stage order sr[0] -> sr[2] -> sr[1] -> sr[3] under sh")],
                  [Check("model", model)], quiet=QUIET["async"])


def g_two_chains(name, da, db):
    body = (f"  reg [{da - 1}:0] a;\n  reg [{db - 1}:0] b;\n" +
            seq("async", [f"a <= {d(da, 0)};", f"b <= {d(db, 0)};"],
                f"if (en) begin\n  a <= {{a[{da - 2}:0], din_a}};\n  b <= {{b[{db - 2}:0], din_b}};\nend") +
            f"  assign qa = a[{da - 1}];\n  assign qb = b[{db - 1}];\n")

    def model(S, I):
        e = I["en"] == 1
        return {"a": W(e, ((S["a"] << 1) | I["din_a"]) & ((1 << da) - 1), S["a"]),
                "b": W(e, ((S["b"] << 1) | I["din_b"]) & ((1 << db) - 1), S["b"])}

    regs = [sreg("a", da, [list(range(da))], "to_msb", ["port:din_a"], when={"inputs": {"en": 1}},
                 rule="chain a under en"),
            sreg("b", db, [list(range(db))], "to_msb", ["port:din_b"], when={"inputs": {"en": 1}},
                 rule="chain b under the same en")]
    units = []
    if da == db:
        units.append(unit("a + b as one 2-lane shift register", "shift_register", ["a", "b"],
                          "two equal-depth chains under one enable with pin heads: S3's lane rule (section 3.3) "
                          "joins them into one 2-lane structure",
                          params={"lanes": 2, "depth": da, "direction": "to_msb", "serial_in": ["port:din_a", "port:din_b"],
                                  "order": [bits_of("a", range(da)), bits_of("b", range(db))]},
                          when={"inputs": {"en": 1}}))
    return Design(name, "mixed", f"two independent shift chains (depths {da} and {db}) under one enable",
                  module(["input clk", "input rst_n", "input en", "input din_a", "input din_b", "output qa", "output qb"],
                         body), regs, [Check("model", model)], units, quiet=QUIET["async"])


# ----------------------------------------------------------------------------------------------
# synchronizers


def g_sync(name, stages, reset, width=1, style="vector"):
    """Synchronizers. style: "vector" (one register per lane, s <= {s, din}), "stages" (one register
    per stage, TEMPO style), "generate" (a register per lane in a generate block), "hier" (a
    submodule per lane). A 3-flop chain is labelled as TEMPO's truth rule reads it: stages 1-2 a
    synchronizer (slice [1:0]), stage 3 a flag (slice [2], alt synchronizer), with the RTL's
    3-stage chain as a lenient unit. Lanes that share clock and reset and have no enable form one
    declared unit, which score.py scores strictly as a chain unit (its STRICT_SYNC_RULE), as S3's
    lane rule (docs/S3_DESIGN.md section 3.3) merges them."""
    ports = ["input clk"] + RST_PORT[reset] + [f"input [{width - 1}:0] din" if width > 1 else "input din",
                                               f"output [{width - 1}:0] q" if width > 1 else "output qo"]
    regs, units, checks, notes = [], [], [], []
    src = lambda j: f"din[{j}]" if width > 1 else "din"  # noqa: E731
    qn = "q" if width > 1 else "qo"   # scalar ports never take a name of the result vocabulary (RESULT_VOCAB)
    sub = ""
    if style == "stages":
        body = "".join(f"  reg [{width - 1}:0] s{k};\n" for k in range(stages))
        upd = "s0 <= din;\n" + "".join(f"s{k} <= s{k - 1};\n" for k in range(1, stages))
        body += seq(reset, [f"s{k} <= {d(width, 0)};" for k in range(stages)], upd) + f"  assign {qn} = s{stages - 1};\n"
        for k in range(stages):
            regs.append(Reg(f"s{k}", width, "synchronizer", {"stages": None, "order": None},
                            rule=f"stage {k} of a {width}-lane {stages}-stage synchronizer (one register per stage)",
                            check_as="none"))
        units.append(unit(f"{width}-lane {stages}-stage synchronizer", "synchronizer", [f"s{k}" for k in range(stages)],
                          "one multi-lane synchronizer written as one RTL register per stage",
                          params={"stages": stages, "order": [[(f"s{k}", j) for k in range(stages)] for j in range(width)]},
                          head=[f"port:{src(j)}" for j in range(width)]))

        def model(S, I):
            o = {"s0": I["din"]}
            for k in range(1, stages):
                o[f"s{k}"] = S[f"s{k - 1}"]
            return o
        checks.append(Check("model", model))
    else:
        if style == "vector":
            assert width == 1
            body = (f"  reg [{stages - 1}:0] s;\n" + seq(reset, [f"s <= {d(stages, 0)};"], f"s <= {{s[{stages - 2}:0], din}};") +
                    f"  assign {qn} = s[{stages - 1}];\n")
            vecs, mdef, local = ["s"], "top", "s"
        elif style == "generate":
            body = (f"  genvar i;\n  generate for (i = 0; i < {width}; i = i + 1) begin : g\n"
                    f"    reg [{stages - 1}:0] s;\n" +
                    seq(reset, [f"s <= {d(stages, 0)};"], f"s <= {{s[{stages - 2}:0], din[i]}};", ind=4) +
                    f"    assign q[i] = s[{stages - 1}];\n  end endgenerate\n")
            vecs, mdef, local = [f"g[{j}].s" for j in range(width)], "top", "g[*].s"
        else:
            sub = module(["input clk"] + RST_PORT[reset] + ["input d", "output q"],
                         f"  reg [{stages - 1}:0] s;\n" + seq(reset, [f"s <= {d(stages, 0)};"], f"s <= {{s[{stages - 2}:0], d}};") +
                         f"  assign q = s[{stages - 1}];\n", name="sync_cell")
            rp = {"async": ".rst_n(rst_n), ", "sync": ".rst(rst), ", "none": ""}[reset]
            body = "".join(f"  sync_cell u{j} (.clk(clk), {rp}.d(din[{j}]), .q(q[{j}]));\n" for j in range(width))
            vecs, mdef, local = [f"u{j}.s" for j in range(width)], "sync_cell", "s"
        syncs = []
        for j, v in enumerate(vecs):
            pj = f"port:{src(j)}"
            if stages == 2:
                regs.append(yreg(v, 2, [[0, 1]], [src(j)], module_def=mdef, local=local,
                                 rule=f"2-stage synchronizer of {src(j)}"))
                syncs.append(v)
            else:
                a_, b_ = f"{v}[1:0]", f"{v}[2]"
                regs.append(Reg(a_, 2, "synchronizer", {"stages": 2, "order": [[(a_, 0), (a_, 1)]]}, rtl=v, rtl_bits=(0, 1),
                                head=[pj], module_def=mdef, local=f"{local}[1:0]",
                                rule=f"stages 1-2 of the 3-flop chain from {src(j)}"))
                regs.append(Reg(b_, 1, "flag", rtl=v, rtl_bits=(2,), module_def=mdef, local=f"{local}[2]",
                                alt_kinds=("synchronizer",),
                                alt_reason="third stage of the RTL's 3-flop synchronizer: a delay relation by S3's "
                                           "definitions (TEMPO's truth labels such stages flag or data_register)",
                                rule="stage 3: an unconditional copy of stage 2"))
                units.append(unit(f"{v}: 3-stage synchronizer (RTL)", "synchronizer", [a_, b_],
                                  "the RTL writes one 3-flop synchronizer; S3 reads stages 1-2 as the synchronizer and "
                                  "stage 3 as a delay relation", params={"stages": 3, "order": [[(a_, 0), (a_, 1), (b_, 0)]]},
                                  head=[pj]))
                syncs.append(a_)
        if width > 1:
            units.append(unit(f"{width} synchronizers as one {width}-lane synchronizer", "synchronizer", syncs,
                              "the lanes share clock and reset and have no enable: S3's lane rule joins them, and a "
                              "control-signature grouping cannot separate them",
                              params={"stages": 2, "order": [[(r, 0), (r, 1)] for r in syncs]},
                              head=[f"port:{src(j)}" for j in range(width)]))

        def model(S, I, vecs=vecs):
            return {v: ((S[v] << 1) | ((I["din"] >> j) & 1)) & ((1 << stages) - 1) for j, v in enumerate(vecs)}
        checks.append(Check("model", model))
    if stages == 3:
        notes.append("3-flop synchronizer: labelled as TEMPO's truth rule reads it (stages 1-2 synchronizer, stage 3 "
                     "flag with alt synchronizer); the RTL's 3-stage chain is a lenient unit")
    return Design(name, "synchronizer", f"{stages}-stage synchronizer, {width} lane(s), {style} style, reset {reset}",
                  sub + module(ports, body), regs, checks, units, quiet=QUIET[reset], notes=notes)


def g_sync_edge():
    body = ("  reg [1:0] s;\n  reg prev;\n  reg pulse;\n" +
            seq("async", ["s <= 2'd0;", "prev <= 1'b0;", "pulse <= 1'b0;"],
                "s <= {s[0], din};\nprev <= s[1];\npulse <= s[1] & ~prev;") + "  assign rise = pulse;\n  assign lvl = s[1];\n")

    def model(S, I):
        s = S["s"]
        return {"s": ((s << 1) | I["din"]) & 3, "prev": (s >> 1) & 1, "pulse": ((s >> 1) & 1) & (1 - S["prev"])}

    regs = [yreg("s", 2, [[0, 1]], ["din"], rule="2-stage synchronizer of din"),
            Reg("prev", 1, "flag", rule="s[1] delayed one clock for edge detection (a third copy stage)"),
            Reg("pulse", 1, "flag", rule="registered rising-edge pulse")]
    return Design("sync2_edge_ar", "synchronizer", "2-stage synchronizer with an edge detector (a third copy stage)",
                  module(["input clk", "input rst_n", "input din", "output rise", "output lvl"], body), regs,
                  [Check("model", model)], quiet=QUIET["async"],
                  notes=["prev is an unconditional third copy stage of an input chain (a delay relation by S3's "
                         "definitions; labelled flag, like TEMPO's sck_p)"])


# ----------------------------------------------------------------------------------------------
# LFSRs, scramblers, CRCs


FIB_ALT = dict(alt_kinds=("shift_register",),
               alt_reason="Fibonacci form, one step per clock: stages 1..w-1 copy their predecessor and only stage 0 "
                          "takes the XOR feedback, so it also reads as a shift register whose serial input is logic "
                          "over its own bits")
FEEDBACK_NOTE = ("a shift structure whose head is fed by its own bits: S3 (docs/S3_DESIGN.md section 3.3) sends it to "
                 "the LFSR test; the truth keeps the RTL intent and accepts the other kind as an alternative")


def fib_step(s, w, T, x=0):
    return ((s << 1) | (par(s & T) ^ x)) & ((1 << w) - 1)


def gal_step_r(s, T, x=0):
    fb = (s & 1) ^ x
    return (s >> 1) ^ (fb * T)


def gal_step_l(s, w, G, x=0):
    fb = ((s >> (w - 1)) & 1) ^ x
    return ((s << 1) & ((1 << w) - 1)) ^ (fb * G)


def g_lfsr(name, w, form, poly, k=1, reset="async", seed=1, en=True, din=None, out="all", family="lfsr"):
    """Fibonacci (shift toward MSB, new bit = parity(s & T) [^ input]) or Galois (shift toward LSB,
    s ^= T when the dropped bit [^ input] is 1), T = poly >> 1, k steps per clock; din: None,
    "serial" (one bit, k = 1) or "parallel" (din[i] enters at step i)."""
    T = poly >> 1
    m = (1 << w) - 1
    ports = ["input clk"] + RST_PORT[reset] + (["input en"] if en else [])
    if din == "serial":
        ports.append("input din")
    elif din == "parallel":
        ports.append(f"input [{k - 1}:0] din")
    ports.append(f"output [{w - 1}:0] q" if out == "all" else "output dout")
    xi = {"serial": " ^ din", "parallel": " ^ din[i]", None: ""}[din]
    if form == "fibonacci":
        stepx = f"nx = {{nx[{w - 2}:0], (^(nx & {h(w, T)})){xi}}};"
    else:
        stepx = f"nx = (nx[0]{xi}) ? ((nx >> 1) ^ {h(w, T)}) : (nx >> 1);"
    body = (f"  reg [{w - 1}:0] s;\n  reg [{w - 1}:0] nx;\n  integer i;\n"
            f"  always @* begin\n    nx = s;\n    for (i = 0; i < {k}; i = i + 1)\n      {stepx}\n  end\n" +
            seq(reset, [f"s <= {h(w, seed)};"], "if (en) s <= nx;" if en else "s <= nx;") +
            ("  assign q = s;\n" if out == "all" else f"  assign dout = s[{w - 1 if form == 'fibonacci' else 0}];\n"))

    def one(s, x=0):
        return fib_step(s, w, T, x) if form == "fibonacci" else gal_step_r(s, T, x)

    def model(S, I):
        s = S["s"]
        n = s
        for i in range(k):
            x = 0 if din is None else (I["din"] if din == "serial" else (I["din"] >> i) & 1)
            n = one(n, x)
        return {"s": W(I["en"] == 1, n, s) if en else n}

    rule = f"{form} LFSR, {k} step(s) per clock" + {None: ", autonomous", "serial": ", one data bit per step",
                                                    "parallel": f", {k} data bits (one per step)"}[din]
    alt = FIB_ALT if form == "fibonacci" and k == 1 else {}
    reg = lreg("s", w, form, poly, k, 0 if din is None else 1, rule=rule, when={"inputs": {"en": 1} if en else {}}, **alt)
    return Design(name, family, f"{w}-bit {rule}; reset {reset}", module(ports, body), [reg],
                  [Check("model", model)], quiet=QUIET[reset], lfsr_models={"s": (w, one)},
                  notes=[FEEDBACK_NOTE] if alt else [])


def g_scr_modes():
    T = 0xB8
    ports = ["input clk", "input rst_n", "input en", "input mode", "input din", "output dout", "output [7:0] q"]
    body = ("  reg [7:0] s;\n  reg [7:0] nx8;\n  integer i;\n"
            f"  always @* begin\n    nx8 = s;\n    for (i = 0; i < 8; i = i + 1)\n"
            f"      nx8 = {{nx8[6:0], ^(nx8 & 8'hB8)}};\n  end\n"
            "  wire fb = din ^ (^(s & 8'hB8));\n" +
            seq("async", ["s <= 8'hFF;"], "if (mode) s <= nx8;\nelse if (en) s <= {s[6:0], fb};") +
            "  assign dout = fb;\n  assign q = s;\n")

    def model(S, I):
        s = S["s"]
        a = s
        for _ in range(8):
            a = fib_step(a, 8, T)
        return {"s": W(I["mode"] == 1, a, W(I["en"] == 1, fib_step(s, 8, T, I["din"]), s))}

    reg = lreg("s", 8, "fibonacci", (T << 1) | 1, 1, 1, rule="self-synchronizing scrambler: one data bit per step "
                                                               "under en; 8 autonomous steps under mode",
               when={"inputs": {"en": 1, "mode": 0}},
               modes=[{"mode": "autonomous (mode = 1)", "k_steps": 8, "n_inputs": 0}], **FIB_ALT)
    return Design("scr_modes_w8_ar", "scrambler", "8-bit scrambler with a serial data mode and an 8-step autonomous mode",
                  module(ports, body), [reg], [Check("model", model)], quiet=QUIET["async"], notes=[FEEDBACK_NOTE],
                  lfsr_models={"s": (8, lambda s, x=0: fib_step(s, 8, T, x))})


def g_crc(name, w, gpoly, k, style, reset="async", init=None, prog=False, family="crc"):
    """CRC register. style "reflected": shift toward LSB, s ^= R (the bit-reversed polynomial) when
    s[0] ^ d is 1, data bit i at step i; style "msb": shift toward MSB, s ^= G when s[w-1] ^ d is 1,
    data bit k-1-i at step i. prog: the polynomial (G, msb style) comes from register `poly`."""
    m = (1 << w) - 1
    G = gpoly & m
    R = int(format(G, f"0{w}b")[::-1], 2)
    init = m if init is None else init
    ports = ["input clk"] + RST_PORT[reset] + ["input init", "input feed",
                                                 f"input [{k - 1}:0] d" if k > 1 else "input d"]
    if prog:
        ports += ["input poly_we", f"input [{w - 1}:0] wdata"]
    ports.append(f"output [{w - 1}:0] crc_o")
    di = (lambda i: "d[i]" if k > 1 else "d")  # noqa: E731
    P = "poly" if prog else h(w, G)
    if style == "reflected":
        stepx = f"nx = (nx[0] ^ {di(0)}) ? ((nx >> 1) ^ {h(w, R)}) : (nx >> 1);"
        loop = f"for (i = 0; i < {k}; i = i + 1)"
    else:
        stepx = f"nx = {{nx[{w - 2}:0], 1'b0}} ^ ({{{w}{{nx[{w - 1}] ^ {di(0)}}}}} & {P});"
        loop = f"for (i = {k - 1}; i >= 0; i = i - 1)"
    body = f"  reg [{w - 1}:0] crc;\n  reg [{w - 1}:0] nx;\n  integer i;\n"
    if prog:
        body += f"  reg [{w - 1}:0] poly;\n" + seq(reset, [f"poly <= {h(w, G)};"], "if (poly_we) poly <= wdata;")
    body += f"  always @* begin\n    nx = crc;\n    {loop}\n      {stepx}\n  end\n"
    load = "if (init) crc <= wdata;" if prog else f"if (init) crc <= {h(w, init)};"
    body += seq(reset, [f"crc <= {h(w, init)};"], load + "\nelse if (feed) crc <= nx;")
    body += "  assign crc_o = ~crc;\n" if style == "reflected" else "  assign crc_o = crc;\n"

    def steps(s, x, g):
        for i in range(k):
            if style == "reflected":
                s = gal_step_r(s, R, (x >> i) & 1)
            else:
                s = gal_step_l(s, w, g, (x >> (k - 1 - i)) & 1)
        return s

    def model(S, I):
        g = S["poly"] if prog else G
        c = S["crc"]
        n = W(I["feed"] == 1, steps(c, I["d"], g), c)
        n = W(I["init"] == 1, I["wdata"] if prog else init, n)
        out = {"crc": n}
        if prog:
            out["poly"] = W(I["poly_we"] == 1, I["wdata"], S["poly"])
        return out

    rule = (f"{'reflected ' if style == 'reflected' else ''}CRC-{w}, {k} step(s) per clock with one data bit per "
            f"step, " + ("polynomial from register poly, initial value loaded from wdata" if prog else
                         f"polynomial {hex(gpoly)}, init {hex(init)}"))
    feed_in = {"init": 0, "feed": 1, **({"poly_we": 0} if prog else {})}
    regs = [lreg("crc", w, "galois", "programmable" if prog else gpoly, k, 1, rule=rule, when={"inputs": feed_in},
                 claim_when={"inputs": feed_in, "domain": {"poly": [G]}} if prog else None,
                 note=f"claims are proven at the probed setting poly = {hex(G)} (the reset value)" if prog else None)]
    checks = [Check("model", model)]
    lm = {}
    if prog:
        regs.append(Reg("poly", w, "data_register", rule="polynomial register, loaded from wdata on poly_we"))
        checks.append(Check(f"probe poly = {hex(G)}", model, domain={"poly": [G]}))
    else:
        lm = {"crc": (w, (lambda s, x=0: gal_step_r(s, R, x)) if style == "reflected" else
                      (lambda s, x=0: gal_step_l(s, w, G, x)))}
    return Design(name, family, rule, module(ports, body), regs, checks, quiet=QUIET[reset], lfsr_models=lm)


def g_prbs():
    ports = ["input clk", "input rst_n", "input en", "input rx", "input clr", "output tx", "output [7:0] errs"]
    body = ("  reg [6:0] g;\n  reg [6:0] c;\n  reg [7:0] ec;\n  wire err = rx ^ c[6] ^ c[5];\n" +
            seq("async", ["g <= 7'h7F;"], "if (en) g <= {g[5:0], g[6] ^ g[5]};") +
            seq("async", ["c <= 7'd0;"], "if (en) c <= {c[5:0], rx};") +
            seq("async", ["ec <= 8'd0;"], "if (clr) ec <= 8'd0;\nelse if (en && err && ec != 8'hFF) ec <= ec + 8'd1;") +
            "  assign tx = g[6];\n  assign errs = ec;\n")
    T = 0x60

    def model(S, I):
        e = I["en"] == 1
        err = I["rx"] ^ ((S["c"] >> 6) & 1) ^ ((S["c"] >> 5) & 1)
        ec = S["ec"]
        return {"g": W(e, fib_step(S["g"], 7, T), S["g"]), "c": W(e, ((S["c"] << 1) | I["rx"]) & 127, S["c"]),
                "ec": W(I["clr"] == 1, 0, W(e & (err == 1) & (ec != 255), ec + 1, ec))}

    regs = [lreg("g", 7, "fibonacci", (T << 1) | 1, 1, 0, rule="PRBS7 generator (x^7 + x^6 + 1)", when={"inputs": {"en": 1}},
                 **FIB_ALT),
            sreg("c", 7, [list(range(7))], "to_msb", ["port:rx"], rule="checker history: the received bits, under en",
                 when={"inputs": {"en": 1}}),
            creg("ec", 8, modulus=None, saturating=True, rule="saturating error counter",
                 when={"inputs": {"en": 1, "clr": 0, "rx": 1}, "domain": {"c": [0], "ec": list(range(255))}})]
    return Design("prbs7_gen_chk_ar", "mixed", "PRBS7 generator, checker history shift register and saturating error counter",
                  module(ports, body), regs, [Check("model", model)], quiet=QUIET["async"], notes=[FEEDBACK_NOTE],
                  lfsr_models={"g": (7, lambda s, x=0: fib_step(s, 7, T, x))})


# ----------------------------------------------------------------------------------------------
# negatives


def g_pipes():
    out = []
    body = ("  reg [7:0] p1;\n  reg [7:0] p2;\n" +
            seq("async", ["p1 <= 8'd0;", "p2 <= 8'd0;"], "if (en) begin\n  p1 <= din;\n  p2 <= p1;\nend") + "  assign q = p2;\n")
    out.append(Design("pipe2_w8_en_ar", "negative_pipeline", "two-stage 8-bit copy pipeline under an enable",
                      module(["input clk", "input rst_n", "input en", "input [7:0] din", "output [7:0] q"], body),
                      [Reg("p1", 8, "data_register", rule="pipeline stage 1 (loads din under en)"),
                       Reg("p2", 8, "data_register", rule="pipeline stage 2 (loads p1 under en): a depth-2 transfer")],
                      [Check("model", lambda S, I: {"p1": W(I["en"] == 1, I["din"], S["p1"]),
                                                    "p2": W(I["en"] == 1, S["p1"], S["p2"])})], quiet=QUIET["async"]))
    body = ("  reg [7:0] p1;\n  reg [7:0] p2;\n  reg [7:0] p3;\n" +
            seq("none", None, "p1 <= a + b;\np2 <= p1 + c;\np3 <= p2 ^ {p2[6:0], 1'b0};") + "  assign q = p3;\n")
    out.append(Design("pipe3_w8_logic_nr", "negative_pipeline", "three-stage pipeline with arithmetic between stages",
                      module(["input clk", "input [7:0] a", "input [7:0] b", "input [7:0] c", "output [7:0] q"], body),
                      [Reg(f"p{i}", 8, "data_register", rule=f"pipeline stage {i} (logic between stages)") for i in (1, 2, 3)],
                      [Check("model", lambda S, I: {"p1": (I["a"] + I["b"]) & 255, "p2": (S["p1"] + I["c"]) & 255,
                                                    "p3": S["p2"] ^ ((S["p2"] << 1) & 255)})]))
    body = ("  reg [3:0] p1;\n  reg [3:0] p2;\n  reg [3:0] p3;\n" +
            seq("sync", ["p1 <= 4'd0;", "p2 <= 4'd0;", "p3 <= 4'd0;"],
                "if (en) begin\n  p1 <= din;\n  p2 <= p1;\n  p3 <= p2;\nend") + "  assign q = p3;\n")
    out.append(Design("pipe3_w4_copy_en_sr", "negative_pipeline", "three-stage 4-bit copy pipeline under one enable",
                      module(["input clk", "input rst", "input en", "input [3:0] din", "output [3:0] q"], body),
                      [Reg(f"p{i}", 4, "data_register", rule=f"pipeline stage {i}: a copy of the previous stage under en")
                       for i in (1, 2, 3)],
                      [Check("model", lambda S, I: {"p1": W(I["en"] == 1, I["din"], S["p1"]),
                                                    "p2": W(I["en"] == 1, S["p1"], S["p2"]),
                                                    "p3": W(I["en"] == 1, S["p2"], S["p3"])})], quiet=QUIET["sync"],
                      notes=["cross-register copy chain of depth 3 under one enable: a 4-lane shift structure to the "
                             "recognizer, data registers to the truth (docs/S3_DESIGN.md section 1, not scored)"]))
    return out


def g_regfiles():
    out = []
    body = ("  wire [31:0] all;\n  genvar i;\n  generate for (i = 0; i < 4; i = i + 1) begin : w\n    reg [7:0] r;\n" +
            seq("async", ["r <= 8'd0;"], "if (we && waddr == i) r <= wdata;", ind=4) +
            "    assign all[8*i+7:8*i] = r;\n  end endgenerate\n  assign rdata = all[8*raddr +: 8];\n")

    def m1(S, I):
        return {f"w[{i}].r": W((I["we"] == 1) & (I["waddr"] == i), I["wdata"], S[f"w[{i}].r"]) for i in range(4)}

    out.append(Design("regfile_4x8_ar", "negative_regfile", "4 x 8 register file written by an address decode",
                      module(["input clk", "input rst_n", "input we", "input [1:0] waddr", "input [7:0] wdata",
                              "input [1:0] raddr", "output [7:0] rdata"], body),
                      [Reg(f"w[{i}].r", 8, "register_file_word", local="w[*].r", rule=f"word {i}: loads wdata when we and waddr == {i}")
                       for i in range(4)], [Check("model", m1)], quiet=QUIET["async"]))
    body = ("  reg [3:0] wreg;\n" + seq("none", None, "if (wv) wreg <= wdata;") +
            "  wire [31:0] all;\n  genvar i;\n  generate for (i = 0; i < 8; i = i + 1) begin : w\n    reg [3:0] r;\n" +
            seq("none", None, "if (we && waddr == i) r <= wreg;", ind=4) +
            "    assign all[4*i+3:4*i] = r;\n  end endgenerate\n  assign rdata = all[4*raddr +: 4];\n")

    def m2(S, I):
        o = {f"w[{i}].r": W((I["we"] == 1) & (I["waddr"] == i), S["wreg"], S[f"w[{i}].r"]) for i in range(8)}
        o["wreg"] = W(I["wv"] == 1, I["wdata"], S["wreg"])
        return o

    out.append(Design("regfile_8x4_from_dreg_nr", "negative_regfile",
                      "8 x 4 register file written from one data register (depth-2 transfers)",
                      module(["input clk", "input wv", "input [3:0] wdata", "input we", "input [2:0] waddr",
                              "input [2:0] raddr", "output [3:0] rdata"], body),
                      [Reg("wreg", 4, "data_register", rule="write data register, loads wdata on wv")] +
                      [Reg(f"w[{i}].r", 4, "register_file_word", local="w[*].r", rule=f"word {i}: loads wreg when we and waddr == {i}")
                       for i in range(8)], [Check("model", m2)]))
    body = ("  reg [15:0] r0;\n  reg [15:0] r1;\n" +
            seq("sync", ["r0 <= 16'd0;", "r1 <= 16'd0;"], """
                if (we && !waddr) begin
                  if (be[0]) r0[7:0] <= wdata[7:0];
                  if (be[1]) r0[15:8] <= wdata[15:8];
                end
                if (we && waddr) begin
                  if (be[0]) r1[7:0] <= wdata[7:0];
                  if (be[1]) r1[15:8] <= wdata[15:8];
                end""") + "  assign rdata = raddr ? r1 : r0;\n")

    def m3(S, I):
        o = {}
        for i, nm in enumerate(("r0", "r1")):
            sel = (I["we"] == 1) & (I["waddr"] == i)
            lo = W(sel & ((I["be"] & 1) == 1), I["wdata"] & 0xFF, S[nm] & 0xFF)
            hi = W(sel & ((I["be"] >> 1) == 1), I["wdata"] & 0xFF00, S[nm] & 0xFF00)
            o[nm] = lo | hi
        return o

    out.append(Design("regfile_2x16_be_sr", "negative_regfile", "2 x 16 register file with byte enables",
                      module(["input clk", "input rst", "input we", "input waddr", "input [1:0] be", "input [15:0] wdata",
                              "input raddr", "output [15:0] rdata"], body),
                      [Reg(n, 16, "register_file_word", rule="word written by address decode and byte enables")
                       for n in ("r0", "r1")], [Check("model", m3)], quiet=QUIET["sync"]))
    return out


def g_fsms():
    out = []
    body = ("  reg [4:0] st;\n" + seq("async", ["st <= 5'b00001;"], """
                case (1'b1)
                  st[0]: if (go) st <= 5'b00010;
                  st[1]: st <= din ? 5'b00100 : 5'b00001;
                  st[2]: st <= 5'b01000;
                  st[3]: if (!din) st <= 5'b10000;
                  st[4]: st <= 5'b00001;
                  default: st <= 5'b00001;
                endcase""") + "  assign busy = ~st[0];\n  assign done = st[4];\n")

    def m1(S, I):
        s = S["st"]
        n = np.full_like(s, 1)
        # case (1'b1): the first set bit decides (priority in case order)
        for b, nxt in reversed(list(enumerate([W(I["go"] == 1, 2, s), W(I["din"] == 1, 4, 1), np.full_like(s, 8),
                                               W(I["din"] == 0, 16, s), np.full_like(s, 1)]))):
            n = W((s >> b) & 1, nxt, n)
        return {"st": n}

    out.append(Design("fsm_onehot5_ar", "negative_fsm", "five-state one-hot FSM written with case (1'b1)",
                      module(["input clk", "input rst_n", "input go", "input din", "output busy", "output done"], body),
                      [Reg("st", 5, "fsm_state", flex=True, rule="one-hot state register (synthesis may re-encode)")],
                      [Check("model", m1, domain={"st": [1, 2, 4, 8, 16]})], quiet=QUIET["async"]))
    body = ("  reg [2:0] st;\n  reg match;\n" + seq("async", ["st <= 3'd0;", "match <= 1'b0;"], """
                if (en) begin
                  match <= (st == 3'd3) & din & arm;
                  case (st)
                    3'd0: st <= din ? 3'd1 : 3'd0;
                    3'd1: st <= din ? 3'd1 : 3'd2;
                    3'd2: st <= din ? 3'd3 : 3'd0;
                    3'd3: st <= din ? 3'd4 : 3'd2;
                    3'd4: st <= din ? 3'd1 : 3'd2;
                    default: st <= 3'd0;
                  endcase
                end""") + "  assign hit = match;\n  assign st_q = st;\n")
    tbl = {0: (0, 1), 1: (2, 1), 2: (0, 3), 3: (2, 4), 4: (2, 1)}

    def m2(S, I):
        s, x = S["st"], I["din"]
        n = np.zeros_like(s)
        for k, (a0, a1) in tbl.items():
            n = W(s == k, W(x == 1, a1, a0), n)
        e = I["en"] == 1
        return {"st": W(e, n, s), "match": W(e, ((s == 3) & (x == 1) & (I["arm"] == 1)).astype(np.int64), S["match"])}

    out.append(Design("fsm_seqdet_ar", "negative_fsm", "binary-encoded sequence detector (1011) with a match flag",
                      module(["input clk", "input rst_n", "input en", "input din", "input arm", "output hit", "output [2:0] st_q"], body),
                      [Reg("st", 3, "fsm_state", flex=True, rule="binary state register of a 5-state detector"),
                       Reg("match", 1, "flag", rule="registered match, qualified by arm")], [Check("model", m2)], quiet=QUIET["async"]))
    body = ('  (* fsm_encoding = "none" *) reg [1:0] st;\n  reg [5:0] tmr;\n' +
            seq("async", ["st <= 2'd0;", "tmr <= 6'd40;"], """
                if (tmr == 6'd0) begin
                  case (st)
                    2'd0: begin st <= 2'd1; tmr <= 6'd30; end
                    2'd1: begin st <= 2'd2; tmr <= 6'd5; end
                    default: begin st <= 2'd0; tmr <= 6'd40; end
                  endcase
                end else if (!pause) tmr <= tmr - 6'd1;""") + "  assign light = st;\n")

    def m3(S, I):
        s, t = S["st"], S["tmr"]
        z = t == 0
        ns_ = W(s == 0, 1, W(s == 1, 2, 0))
        nt = W(s == 0, 30, W(s == 1, 5, 40))
        return {"st": W(z, ns_, s), "tmr": W(z, nt, W(I["pause"] == 0, t - 1, t))}

    out.append(Design("fsm_timer_ar", "negative_fsm", "three-state controller with a down timer reloaded per state",
                      module(["input clk", "input rst_n", "input pause", "output [1:0] light"], body),
                      [Reg("st", 2, "fsm_state", rule="controller state (fsm_encoding none)"),
                       creg("tmr", 6, direction="down", modulus=None, rule="down timer: -1 per clock unless pause; "
                            "reloaded with a per-state constant at 0 (never wraps)",
                            when={"inputs": {"pause": 0}, "domain": {"tmr": list(range(1, 64))}})],
                      [Check("model", m3)], quiet=QUIET["async"]))
    return out


def g_accs():
    out = []
    body = "  reg [7:0] acc;\n" + seq("async", ["acc <= 8'd0;"], "if (en) acc <= acc + din;") + "  assign q = acc;\n"
    out.append(Design("acc_w8_en_ar", "negative_accumulator", "8-bit accumulator of an 8-bit input",
                      module(["input clk", "input rst_n", "input en", "input [7:0] din", "output [7:0] q"], body),
                      [Reg("acc", 8, "accumulator", rule="acc + din (a varying +c)")],
                      [Check("model", lambda S, I: {"acc": W(I["en"] == 1, (S["acc"] + I["din"]) & 255, S["acc"])})],
                      quiet=QUIET["async"]))
    body = "  reg [11:0] acc;\n" + seq("sync", ["acc <= 12'd0;"],
                                       "if (clr) acc <= 12'd0;\nelse if (en) acc <= acc + {4'd0, din};") + "  assign q = acc;\n"
    out.append(Design("acc_w12_clr_sr", "negative_accumulator", "12-bit accumulator with clear",
                      module(["input clk", "input rst", "input en", "input clr", "input [7:0] din", "output [11:0] q"], body),
                      [Reg("acc", 12, "accumulator", rule="acc + zero-extended din, cleared by clr")],
                      [Check("model", lambda S, I: {"acc": W(I["clr"] == 1, 0, W(I["en"] == 1, (S["acc"] + I["din"]) & 4095,
                                                                                 S["acc"]))})], quiet=QUIET["sync"]))
    body = "  reg [9:0] acc;\n" + seq("async", ["acc <= 10'd0;"],
                                      "if (clr) acc <= 10'd0;\nelse if (en) acc <= acc + a * b;") + "  assign q = acc;\n"
    out.append(Design("acc_mac_w10_ar", "negative_accumulator", "10-bit multiply-accumulate of two 3-bit inputs",
                      module(["input clk", "input rst_n", "input en", "input clr", "input [2:0] a", "input [2:0] b",
                              "output [9:0] q"], body),
                      [Reg("acc", 10, "accumulator", rule="acc + a * b")],
                      [Check("model", lambda S, I: {"acc": W(I["clr"] == 1, 0, W(I["en"] == 1,
                                                                                 (S["acc"] + I["a"] * I["b"]) & 1023, S["acc"]))})],
                      quiet=QUIET["async"]))
    return out


def g_flags():
    body = ("  reg ovf;\n  reg perr;\n  reg tmo;\n  reg [7:0] cap;\n" +
            seq("async", ["ovf <= 1'b0;", "perr <= 1'b0;", "tmo <= 1'b0;"], """
                if (clr) begin
                  ovf <= 1'b0; perr <= 1'b0; tmo <= 1'b0;
                end else begin
                  if (e_ovf) ovf <= 1'b1;
                  if (e_par && ^d) perr <= 1'b1;
                  if (e_tmo) tmo <= 1'b1;
                end""") +
            seq("async", ["cap <= 8'd0;"], "if (e_ovf) cap <= d;") + "  assign st = {ovf, perr, tmo};\n  assign q = cap;\n")

    def m(S, I):
        c = I["clr"] == 1
        return {"ovf": W(c, 0, S["ovf"] | I["e_ovf"]), "perr": W(c, 0, S["perr"] | (I["e_par"] & par(I["d"]))),
                "tmo": W(c, 0, S["tmo"] | I["e_tmo"]), "cap": W(I["e_ovf"] == 1, I["d"], S["cap"])}

    return Design("flags_sticky_ar", "negative_flags", "three sticky error flags with clear and a capture register",
                  module(["input clk", "input rst_n", "input clr", "input e_ovf", "input e_par", "input e_tmo",
                          "input [7:0] d", "output [2:0] st", "output [7:0] q"], body),
                  [Reg(n, 1, "flag", rule="sticky flag, cleared by clr") for n in ("ovf", "perr", "tmo")] +
                  [Reg("cap", 8, "data_register", rule="captures d on e_ovf")], [Check("model", m)], quiet=QUIET["async"])


def g_mut_carry():
    body = ("  reg [4:0] c;\n" + seq("async", ["c <= 5'd0;"], """
                if (en) begin
                  c[0] <= ~c[0];
                  c[1] <= c[1] ^ c[0];
                  c[2] <= c[2] ^ (c[1] & c[0]);
                  c[3] <= c[3] ^ (c[1] & c[0]);
                  c[4] <= c[4] ^ (&c[3:0]);
                end""") + "  assign q = c;\n")

    def step(c):
        b = lambda i: (c >> i) & 1  # noqa: E731
        return ((1 - b(0)) | ((b(1) ^ b(0)) << 1) | ((b(2) ^ (b(1) & b(0))) << 2) | ((b(3) ^ (b(1) & b(0))) << 3) |
                ((b(4) ^ (b(3) & b(2) & b(1) & b(0))) << 4))

    return Design("mut_carry_w5_ar", "negative_mutation", "a 5-bit counter whose bit-3 carry skips bit 2 (mutated carry)",
                  module(["input clk", "input rst_n", "input en", "output [4:0] q"], body),
                  [Reg("c", 5, "other", rule="mutated binary counter: bit 3 toggles on c[1] & c[0], ignoring c[2]; no bit "
                                            "order and polarity makes every transition +1/-1 (checked exhaustively)")],
                  [Check("model", lambda S, I: {"c": W(I["en"] == 1, step(S["c"]), S["c"])})], quiet=QUIET["async"],
                  counter_negatives=[("c", 5, step)])


# ----------------------------------------------------------------------------------------------
# mixed designs


def g_pwm():
    body = ("  reg [7:0] cnt;\n  reg [7:0] duty;\n  reg pwm;\n" +
            seq("async", ["cnt <= 8'd0;", "duty <= 8'd128;", "pwm <= 1'b0;"], """
                if (en) cnt <= (cnt == 8'd199) ? 8'd0 : cnt + 8'd1;
                if (we) duty <= wdata;
                pwm <= (cnt < duty);""") + "  assign out = pwm;\n")

    def m(S, I):
        c = S["cnt"]
        return {"cnt": W(I["en"] == 1, W(c == 199, 0, c + 1), c), "duty": W(I["we"] == 1, I["wdata"], S["duty"]),
                "pwm": (c < S["duty"]).astype(np.int64)}

    return Design("pwm_mod200_ar", "mixed", "PWM: a mod-200 counter, a duty register and a compare flag",
                  module(["input clk", "input rst_n", "input en", "input we", "input [7:0] wdata", "output out"], body),
                  [creg("cnt", 8, modulus=200, rule="mod-200 period counter",
                        when={"inputs": {"en": 1}, "domain": {"cnt": list(range(200))}}),
                   Reg("duty", 8, "data_register", rule="duty cycle, loaded on we"),
                   Reg("pwm", 1, "flag", rule="registered compare cnt < duty")],
                  [Check("model", m, domain={"cnt": list(range(200))})], quiet=QUIET["async"])


def g_fifo():
    body = ("  reg [1:0] wp;\n  reg [1:0] rp;\n  reg [2:0] lvl;\n"
            "  wire do_push = push & (lvl != 3'd4);\n  wire do_pop = pop & (lvl != 3'd0);\n" +
            seq("async", ["wp <= 2'd0;", "rp <= 2'd0;", "lvl <= 3'd0;"], """
                if (do_push) wp <= wp + 2'd1;
                if (do_pop) rp <= rp + 2'd1;
                case ({do_push, do_pop})
                  2'b10: lvl <= lvl + 3'd1;
                  2'b01: lvl <= lvl - 3'd1;
                  default: lvl <= lvl;
                endcase""") +
            "  wire [31:0] all;\n  genvar i;\n  generate for (i = 0; i < 4; i = i + 1) begin : g\n    reg [7:0] m;\n" +
            seq("async", ["m <= 8'd0;"], "if (do_push && wp == i) m <= wdata;", ind=4) +
            "    assign all[8*i+7:8*i] = m;\n  end endgenerate\n"
            "  assign rdata = all[8*rp +: 8];\n  assign full = (lvl == 3'd4);\n  assign empty = (lvl == 3'd0);\n")

    def mdl(S, I):
        lvl = S["lvl"]
        pu = (I["push"] == 1) & (lvl != 4)
        po = (I["pop"] == 1) & (lvl != 0)
        o = {"wp": W(pu, (S["wp"] + 1) & 3, S["wp"]), "rp": W(po, (S["rp"] + 1) & 3, S["rp"]),
             "lvl": W(pu & ~po, lvl + 1, W(po & ~pu, lvl - 1, lvl))}
        for i in range(4):
            o[f"g[{i}].m"] = W(pu & (S["wp"] == i), I["wdata"], S[f"g[{i}].m"])
        return o

    regs = [creg("wp", 2, rule="write pointer, +1 per accepted push (mod 4)",
                 when={"inputs": {"push": 1}, "domain": {"lvl": [0, 1, 2, 3]}}),
            creg("rp", 2, rule="read pointer, +1 per accepted pop (mod 4)",
                 when={"inputs": {"pop": 1}, "domain": {"lvl": [1, 2, 3, 4]}}),
            creg("lvl", 3, direction="updown", modulus=None, saturating=4,
                 rule="fill level: +1 on an accepted push, -1 on an accepted pop; bounded 0..4 (5..7 unreachable)",
                 when={"inputs": {"push": 1, "pop": 0}, "domain": {"lvl": [0, 1, 2, 3]}},
                 when_down={"inputs": {"push": 0, "pop": 1}, "domain": {"lvl": [1, 2, 3, 4]}})]
    regs += [Reg(f"g[{i}].m", 8, "register_file_word", local="g[*].m", rule=f"FIFO entry {i}") for i in range(4)]
    return Design("fifo4x8_ar", "mixed", "4-entry FIFO: storage words, two pointers and an up/down level",
                  module(["input clk", "input rst_n", "input push", "input pop", "input [7:0] wdata", "output [7:0] rdata",
                          "output full", "output empty"], body), regs,
                  [Check("model", mdl, domain={"lvl": [0, 1, 2, 3, 4]})], quiet=QUIET["async"])


def g_debounce():
    body = ("  reg [1:0] s;\n  reg [3:0] cnt;\n  reg stable;\n" +
            seq("async", ["s <= 2'd0;"], "s <= {s[0], din};") +
            seq("async", ["cnt <= 4'd0;", "stable <= 1'b0;"], """
                if (s[1] == stable) cnt <= 4'd0;
                else if (cnt == 4'd11) begin
                  stable <= s[1];
                  cnt <= 4'd0;
                end else cnt <= cnt + 4'd1;""") + "  assign qo = stable;\n")

    def m(S, I):
        s1 = (S["s"] >> 1) & 1
        eq = s1 == S["stable"]
        c = S["cnt"]
        top_ = (~eq) & (c == 11)
        return {"s": ((S["s"] << 1) | I["din"]) & 3, "cnt": W(eq | top_, 0, c + 1) & 15,
                "stable": W(top_, s1, S["stable"])}

    return Design("debounce_ar", "mixed", "debouncer: a 2-stage synchronizer, a mod-12 run counter and a stable flag",
                  module(["input clk", "input rst_n", "input din", "output qo"], body),
                  [yreg("s", 2, [[0, 1]], ["din"], rule="2-stage synchronizer of din"),
                   creg("cnt", 4, modulus=12, rule="counts clocks while the input differs from stable; cleared "
                                                   "(constant) when equal; wraps at 12 when stable flips",
                        when={"inputs": {}, "domain": {"s": [2, 3], "stable": [0], "cnt": list(range(12))}}),
                   Reg("stable", 1, "flag", rule="debounced level")],
                  [Check("model", m, domain={"cnt": list(range(12))})], quiet=QUIET["async"])


def g_timer_hms():
    body = ("  reg [5:0] pre;\n  reg [5:0] sec;\n  reg [5:0] mins;\n  reg [5:0] alarm;\n  reg ring;\n"
            "  wire t1 = en && (pre == 6'd49);\n  wire t2 = t1 && (sec == 6'd59);\n" +
            seq("async", ["pre <= 6'd0;", "sec <= 6'd0;", "mins <= 6'd0;", "alarm <= 6'd0;", "ring <= 1'b0;"], """
                if (en) pre <= (pre == 6'd49) ? 6'd0 : pre + 6'd1;
                if (t1) sec <= (sec == 6'd59) ? 6'd0 : sec + 6'd1;
                if (t2) mins <= (mins == 6'd59) ? 6'd0 : mins + 6'd1;
                if (set_al) alarm <= din;
                if (clr) ring <= 1'b0;
                else if (t2 && mins == alarm) ring <= 1'b1;""") +
            "  assign m_o = mins;\n  assign s_o = sec;\n  assign ring_o = ring;\n")

    def m(S, I):
        e = I["en"] == 1
        t1 = e & (S["pre"] == 49)
        t2 = t1 & (S["sec"] == 59)
        inc = lambda x, go, M: W(go, W(x == M - 1, 0, x + 1), x)  # noqa: E731
        return {"pre": inc(S["pre"], e, 50), "sec": inc(S["sec"], t1, 60), "mins": inc(S["mins"], t2, 60),
                "alarm": W(I["set_al"] == 1, I["din"], S["alarm"]),
                "ring": W(I["clr"] == 1, 0, W(t2 & (S["mins"] == S["alarm"]), 1, S["ring"]))}

    regs = [creg("pre", 6, modulus=50, rule="mod-50 prescaler", when={"inputs": {"en": 1}, "domain": {"pre": list(range(50))}}),
            creg("sec", 6, modulus=60, rule="mod-60 seconds, +1 on the prescaler's wrap",
                 when={"inputs": {"en": 1}, "domain": {"pre": [49], "sec": list(range(60))}}),
            creg("mins", 6, modulus=60, rule="mod-60 minutes, +1 on the seconds' wrap",
                 when={"inputs": {"en": 1}, "domain": {"pre": [49], "sec": [59], "mins": list(range(60))}}),
            Reg("alarm", 6, "data_register", rule="alarm minute, loaded on set_al"),
            Reg("ring", 1, "flag", rule="sticky alarm flag")]
    units = [unit("pre + sec + mins as one counter", "counter", ["pre", "sec", "mins"],
                  "three cascaded digits (mod 50, 60, 60) read as one mod-180000 counter",
                  params={"direction": "up", "step": 1, "modulus": 180000, "saturating": False, "load": False,
                          "bit_order": None})]
    return Design("timer_hms_ar", "counter_cascade", "prescaler, seconds and minutes in cascade with an alarm compare",
                  module(["input clk", "input rst_n", "input en", "input set_al", "input clr", "input [5:0] din",
                          "output [5:0] m_o", "output [5:0] s_o", "output ring_o"], body), regs,
                  [Check("model", m, domain={"pre": list(range(50)), "sec": list(range(60)), "mins": list(range(60))})],
                  units, quiet=QUIET["async"])


def g_uart_rx():
    body = ('  reg [1:0] rx_s;\n  (* fsm_encoding = "none" *) reg [1:0] st;\n  reg [3:0] baud;\n  reg [2:0] nbit;\n'
            "  reg [7:0] sh;\n  reg [7:0] data_r;\n  reg valid_r;\n  wire tick = (baud == 4'd9);\n" +
            seq("async", ["rx_s <= 2'b11;"], "rx_s <= {rx_s[0], rx};") +
            seq("async", ["st <= 2'd0;", "baud <= 4'd0;", "nbit <= 3'd0;", "sh <= 8'd0;", "data_r <= 8'd0;",
                          "valid_r <= 1'b0;"], """
                valid_r <= 1'b0;
                case (st)
                  2'd0: begin
                    baud <= 4'd0;
                    if (!rx_s[1]) st <= 2'd1;
                  end
                  2'd1: begin
                    baud <= tick ? 4'd0 : baud + 4'd1;
                    if (tick) begin st <= 2'd2; nbit <= 3'd0; end
                  end
                  2'd2: begin
                    baud <= tick ? 4'd0 : baud + 4'd1;
                    if (tick) begin
                      sh <= {rx_s[1], sh[7:1]};
                      nbit <= nbit + 3'd1;
                      if (nbit == 3'd7) st <= 2'd3;
                    end
                  end
                  default: begin
                    baud <= tick ? 4'd0 : baud + 4'd1;
                    if (tick) begin st <= 2'd0; data_r <= sh; valid_r <= rx_s[1]; end
                  end
                endcase""") + "  assign data = data_r;\n  assign valid = valid_r;\n")

    def m(S, I):
        st, b, nb, sh = S["st"], S["baud"], S["nbit"], S["sh"]
        r1 = (S["rx_s"] >> 1) & 1
        tick = b == 9
        bn = W(tick, 0, b + 1)
        nst = W(st == 0, W(r1 == 0, 1, 0), W(st == 1, W(tick, 2, 1), W(st == 2, W(tick & (nb == 7), 3, 2), W(tick, 0, 3))))
        return {"rx_s": ((S["rx_s"] << 1) | I["rx"]) & 3, "st": nst, "baud": W(st == 0, 0, bn),
                "nbit": W((st == 1) & tick, 0, W((st == 2) & tick, (nb + 1) & 7, nb)),
                "sh": W((st == 2) & tick, (r1 << 7) | (sh >> 1), sh),
                "data_r": W((st == 3) & tick, sh, S["data_r"]), "valid_r": W((st == 3) & tick, r1, 0)}

    regs = [yreg("rx_s", 2, [[0, 1]], ["rx"], rule="2-stage synchronizer of rx (reset high)"),
            Reg("st", 2, "fsm_state", rule="receiver state: idle, start, data, stop"),
            creg("baud", 4, modulus=10, rule="bit-time counter: +1 per clock outside idle, wraps at 10; cleared in idle",
                 when={"inputs": {}, "domain": {"st": [1, 2, 3], "baud": list(range(10))}}),
            creg("nbit", 3, rule="received-bit counter: +1 per data bit (mod 8), cleared at the start bit",
                 when={"inputs": {}, "domain": {"st": [2], "baud": [9]}}),
            sreg("sh", 8, lanes_lsb(1, 8), "to_lsb", [("rx_s", 1)], rule="deserializer: shifts in the synchronized rx "
                 "toward the LSB only in the data state on a bit tick", when={"inputs": {}, "domain": {"st": [2], "baud": [9]}}),
            Reg("data_r", 8, "data_register", rule="received byte, loaded from sh in the stop state"),
            Reg("valid_r", 1, "flag", rule="one-clock valid pulse")]
    return Design("uart_rx_ar", "deserializer", "UART receiver: synchronizer, FSM, bit-time and bit counters, deserializer",
                  module(["input clk", "input rst_n", "input rx", "output [7:0] data", "output valid"], body), regs,
                  [Check("model", m, domain={"baud": list(range(10))})], quiet=QUIET["async"])


def g_uart_tx():
    body = ("  reg [3:0] baud;\n  reg [3:0] nb;\n  reg [9:0] sh;\n  reg busy;\n" +
            seq("async", ["baud <= 4'd0;", "nb <= 4'd0;", "sh <= 10'h3FF;", "busy <= 1'b0;"], """
                if (!busy) begin
                  if (start) begin
                    sh <= {^data, data, 1'b0};
                    busy <= 1'b1;
                    baud <= 4'd0;
                    nb <= 4'd0;
                  end
                end else begin
                  baud <= (baud == 4'd11) ? 4'd0 : baud + 4'd1;
                  if (baud == 4'd11) begin
                    sh <= {1'b1, sh[9:1]};
                    nb <= nb + 4'd1;
                    if (nb == 4'd9) busy <= 1'b0;
                  end
                end""") + "  assign txd = sh[0];\n  assign busy_o = busy;\n")

    def m(S, I):
        b, nb, sh, bz = S["baud"], S["nb"], S["sh"], S["busy"]
        go = (bz == 0) & (I["start"] == 1)
        tick = (bz == 1) & (b == 11)
        return {"sh": W(go, (par(I["data"]) << 9) | (I["data"] << 1), W(tick, (1 << 9) | (sh >> 1), sh)),
                "busy": W(go, 1, W(tick & (nb == 9), 0, bz)),
                "baud": W(go, 0, W(bz == 1, W(b == 11, 0, b + 1), b)),
                "nb": W(go, 0, W(tick, (nb + 1) & 15, nb))}

    regs = [creg("baud", 4, modulus=12, rule="bit-time counter while busy, wraps at 12; cleared on start",
                 when={"inputs": {}, "domain": {"busy": [1], "baud": list(range(12))}}),
            creg("nb", 4, modulus=None, saturating=None, rule="sent-bit counter: +1 per bit, cleared on start; stops "
                 "when busy drops (never wraps)", when={"inputs": {}, "domain": {"busy": [1], "baud": [11], "nb": list(range(10))}}),
            sreg("sh", 10, lanes_lsb(1, 10), "to_lsb", None, head=[("const", 1)],
                 rule="serializer: parallel load of the frame {parity, data, start} on start, then shifts toward the "
                      "LSB with a constant-1 fill",
                 when={"inputs": {}, "domain": {"busy": [1], "baud": [11]}}),
            Reg("busy", 1, "flag", rule="transmitting")]
    return Design("uart_tx_ar", "deserializer", "UART transmitter: loadable 10-bit serializer, bit-time and bit counters",
                  module(["input clk", "input rst_n", "input start", "input [7:0] data", "output txd", "output busy_o"], body),
                  regs, [Check("model", m, domain={"baud": list(range(12))})], quiet=QUIET["async"],
                  notes=["sh shifts in a constant 1: serial_in is null (the schema has no constant source)"])


def g_spi():
    body = ("  reg [1:0] sck_s;\n  reg [1:0] mosi_s;\n  reg [1:0] cs_s;\n  reg sck_p;\n  reg [7:0] sh;\n  reg [2:0] bitc;\n"
            "  reg [7:0] rx_r;\n  reg v;\n  wire rise = sck_s[1] & ~sck_p;\n" +
            seq("async", ["sck_s <= 2'd0;", "mosi_s <= 2'd0;", "cs_s <= 2'b11;", "sck_p <= 1'b0;"],
                "sck_s <= {sck_s[0], sck};\nmosi_s <= {mosi_s[0], mosi};\ncs_s <= {cs_s[0], cs_n};\nsck_p <= sck_s[1];") +
            seq("async", ["sh <= 8'd0;", "bitc <= 3'd0;", "rx_r <= 8'd0;", "v <= 1'b0;"], """
                v <= 1'b0;
                if (cs_s[1]) bitc <= 3'd0;
                else if (rise) begin
                  sh <= {sh[6:0], mosi_s[1]};
                  bitc <= bitc + 3'd1;
                  if (bitc == 3'd7) begin
                    rx_r <= {sh[6:0], mosi_s[1]};
                    v <= 1'b1;
                  end
                end""") + "  assign rx = rx_r;\n  assign rx_valid = v;\n  assign miso = sh[7];\n")

    def m(S, I):
        s1 = lambda r: (S[r] >> 1) & 1  # noqa: E731
        rise = (s1("sck_s") == 1) & (S["sck_p"] == 0)
        act = (s1("cs_s") == 0) & rise
        newsh = ((S["sh"] << 1) | s1("mosi_s")) & 255
        last = act & (S["bitc"] == 7)
        return {"sck_s": ((S["sck_s"] << 1) | I["sck"]) & 3, "mosi_s": ((S["mosi_s"] << 1) | I["mosi"]) & 3,
                "cs_s": ((S["cs_s"] << 1) | I["cs_n"]) & 3, "sck_p": s1("sck_s"),
                "sh": W(act, newsh, S["sh"]), "bitc": W(s1("cs_s") == 1, 0, W(act, (S["bitc"] + 1) & 7, S["bitc"])),
                "rx_r": W(last, newsh, S["rx_r"]), "v": last.astype(np.int64)}

    act = {"cs_s": [0, 1], "sck_s": [2, 3], "sck_p": [0]}
    regs = [yreg("sck_s", 2, [[0, 1]], ["sck"], rule="2-stage synchronizer of sck"),
            yreg("mosi_s", 2, [[0, 1]], ["mosi"], rule="2-stage synchronizer of mosi"),
            yreg("cs_s", 2, [[0, 1]], ["cs_n"], rule="2-stage synchronizer of cs_n (reset high)"),
            Reg("sck_p", 1, "flag", rule="sck_s[1] delayed one clock for edge detection (a third copy stage)"),
            sreg("sh", 8, lanes_msb(1, 8), "to_msb", [("mosi_s", 1)], rule="shifts in synchronized mosi on each "
                 "sck rising edge while selected", when={"inputs": {}, "domain": act}),
            creg("bitc", 3, rule="bit counter: +1 per sck rising edge (mod 8), cleared while deselected",
                 when={"inputs": {}, "domain": act}),
            Reg("rx_r", 8, "data_register", rule="received byte"),
            Reg("v", 1, "flag", rule="one-clock byte-valid pulse")]
    units = [unit("three synchronizers as one 3-lane synchronizer", "synchronizer", ["sck_s", "mosi_s", "cs_s"],
                  "one always block, same reset, no enable: S3's lane rule joins them and a control-signature "
                  "grouping cannot separate them (score.py scores this strictly as a chain unit)",
                  params={"stages": 2, "order": [bits_of(n, [0, 1]) for n in ("sck_s", "mosi_s", "cs_s")]},
                  head=["port:sck", "port:mosi", "port:cs_n"])]
    return Design("spi_slave_ar", "deserializer", "SPI receiver: three synchronizers, an edge detector, a shift register "
                  "and a bit counter", module(["input clk", "input rst_n", "input sck", "input mosi", "input cs_n",
                                               "output [7:0] rx", "output rx_valid", "output miso"], body), regs,
                  [Check("model", m)], units, quiet=QUIET["async"],
                  notes=["sck_p is an unconditional third copy stage of the sck chain: a delay relation by S3's "
                         "definitions; labelled flag (as TEMPO's sck_p)",
                         "rx_r loads sh's next value: cross-register copies (depth-2 transfers)"])


def g_deser_dreg():
    body = ('  (* fsm_encoding = "none" *) reg [1:0] st;\n  reg [1:0] cnt;\n  reg [23:0] dreg;\n' +
            seq("async", ["st <= 2'd0;", "cnt <= 2'd0;", "dreg <= 24'd0;"], """
                case (st)
                  2'd0: if (rx_stb) begin
                    st <= 2'd1;
                    cnt <= 2'd0;
                    dreg <= 24'd0;
                  end
                  2'd1: if (rx_stb) begin
                    dreg <= {rx_byte, dreg[23:8]};
                    cnt <= (cnt == 2'd2) ? 2'd0 : cnt + 2'd1;
                    if (cnt == 2'd2) st <= cmd ? 2'd2 : 2'd3;
                  end
                  2'd2: if (abort) begin
                    dreg <= rdata;
                    st <= 2'd0;
                  end else if (rx_stb) begin
                    dreg <= {rx_byte, dreg[23:8]};
                    cnt <= (cnt == 2'd2) ? 2'd0 : cnt + 2'd1;
                    if (cnt == 2'd2) st <= 2'd0;
                  end
                  default: begin
                    dreg <= rdata;
                    st <= 2'd0;
                  end
                endcase""") + "  assign q = dreg;\n  assign st_o = st;\n")

    def m(S, I):
        st, c, dr = S["st"], S["cnt"], S["dreg"]
        stb = I["rx_stb"] == 1
        shf = (I["rx_byte"] << 16) | (dr >> 8)
        cn = W(c == 2, 0, c + 1)
        ab = (st == 2) & (I["abort"] == 1)
        sh = ((st == 1) | (st == 2)) & stb & ~ab
        nst = W(st == 0, W(stb, 1, 0),
                W(st == 1, W(stb & (c == 2), W(I["cmd"] == 1, 2, 3), 1),
                  W(st == 2, W(ab, 0, W(stb & (c == 2), 0, 2)), 0)))
        return {"st": nst, "cnt": W((st == 0) & stb, 0, W(sh, cn, c)),
                "dreg": W((st == 0) & stb, 0, W(ab | (st == 3), I["rdata"], W(sh, shf, dr)))}

    regs = [Reg("st", 2, "fsm_state", rule="idle, address, data, read"),
            creg("cnt", 2, modulus=3, rule="byte counter within a field (mod 3), cleared at the start",
                 when={"inputs": {"rx_stb": 1, "abort": 0}, "domain": {"st": [1, 2], "cnt": [0, 1, 2]}}),
            sreg("dreg", 24, lanes_lsb(8, 3), "to_lsb", [f"port:rx_byte[{j}]" for j in range(8)],
                 alt_kinds=("data_register",), alt_reason="shifts a byte in per strobe ({rx_byte, dreg[23:8]}) in two "
                 "FSM states but is also the parallel-load holding register (rdata, priority in the data state)",
                 rule="8 lanes x depth 3 toward the LSB, shifting in two FSM states under higher-priority loads",
                 when={"inputs": {"rx_stb": 1, "abort": 0}, "domain": {"st": [1, 2]}})]
    return Design("deser_dreg_fsm_ar", "deserializer", "byte deserializer that shifts in several FSM states under "
                  "priority parallel loads (TEMPO dreg style)",
                  module(["input clk", "input rst_n", "input rx_stb", "input [7:0] rx_byte", "input cmd", "input abort",
                          "input [23:0] rdata", "output [23:0] q", "output [1:0] st_o"], body), regs,
                  [Check("model", m, domain={"cnt": [0, 1, 2]})], quiet=QUIET["async"])


# ----------------------------------------------------------------------------------------------
# cohort 2: structure classes the generalisation review of 2026-09-22 found missing (reviews[2]).
# Written for this corpus; nothing is copied from out/s3/review_generalisation, which stays a
# separate regression set. Each family has 3-5 designs, so the per-(cohort, family) split holds one
# out.


def g_reload_timer(name, w, reset, style, oneshot=False, out="all", p0=1000):
    """Down timer reloaded from a period register (written on per_we) on start and at terminal count
    on a tick: style "case" (casez over {start, tick, zero}) or "if"; oneshot: a mode bit written with
    the period chooses between reload at zero (periodic) and stop at zero (one-shot)."""
    ports = ["input clk"] + RST_PORT[reset] + ["input start", "input tick", "input per_we", f"input [{w - 1}:0] per_d"]
    if oneshot:
        ports.append("input per_mode")
    ports.append("output expired")
    if out == "all":
        ports.append(f"output [{w - 1}:0] cnt_o")
    zero_reload = "auto_r ? period : c" if oneshot else "period"
    if style == "case":
        upd = f"""
            exp_r <= tick & zero & ~start;
            casez ({{start, tick, zero}})
              3'b1??: c <= period;
              3'b011: c <= {zero_reload};
              3'b010: c <= c - {d(w, 1)};
              default: c <= c;
            endcase"""
    else:
        upd = f"""
            exp_r <= tick && zero && !start;
            if (start) c <= period;
            else if (tick) begin
              if (zero) c <= {zero_reload};
              else c <= c - {d(w, 1)};
            end"""
    per = ("if (per_we) begin\n  period <= per_d;\n  auto_r <= per_mode;\nend" if oneshot else
           "if (per_we) period <= per_d;")
    body = (f"  reg [{w - 1}:0] period;\n  reg [{w - 1}:0] c;\n  reg exp_r;\n" + ("  reg auto_r;\n" if oneshot else "") +
            f"  wire zero = (c == {d(w, 0)});\n" +
            seq(reset, [f"period <= {d(w, p0)};"] + (["auto_r <= 1'b1;"] if oneshot else []), per) +
            seq(reset, [f"c <= {d(w, 0)};", "exp_r <= 1'b0;"], upd) +
            "  assign expired = exp_r;\n" + ("  assign cnt_o = c;\n" if out == "all" else ""))
    msk = (1 << w) - 1

    def model(S, I):
        c, p = S["c"], S["period"]
        z, st, tk = c == 0, I["start"] == 1, I["tick"] == 1
        at_zero = W(S["auto_r"] == 1, p, c) if oneshot else p
        o = {"c": W(st, p, W(tk, W(z, at_zero, (c - 1) & msk), c)),
             "period": W(I["per_we"] == 1, I["per_d"], p), "exp_r": (tk & z & ~st).astype(np.int64)}
        if oneshot:
            o["auto_r"] = W(I["per_we"] == 1, I["per_mode"], S["auto_r"])
        return o

    kind_txt = "reloads from period at zero (auto_r) or stops there (one-shot)" if oneshot else "reloads from period at zero"
    regs = [creg("c", w, direction="down", modulus=None, saturating=None if oneshot else False, load=True,
                 rule=f"down timer: -1 per tick; {kind_txt}; start loads period (opaque loads from a register: "
                      f"modulus null{', saturation null' if oneshot else ''}); written as {style}",
                 when={"inputs": {"start": 0, "tick": 1}, "domain": {"c": rng_(1, 1 << w)}}),
            Reg("period", w, "data_register", rule="period register, written on per_we"),
            Reg("exp_r", 1, "flag", rule="registered terminal-count pulse (tick at zero)")]
    if oneshot:
        regs.append(Reg("auto_r", 1, "flag", rule="mode bit: periodic reload (1) or one-shot (0), written with the period"))
    return Design(name, "counter_reload", f"{w}-bit down timer reloaded from a period register on start and at zero "
                  f"({style}{', one-shot mode' if oneshot else ''}); reset {reset}", module(ports, body), regs,
                  [Check("model", model)], quiet=QUIET[reset],
                  notes=["the reload writes a register's value at the terminal count (an opaque load case, "
                         "docs/S3_DESIGN.md section 3.4), not a data path; the counting case is c != 0 under tick"])


def g_autoreload_up(name, w, reset):
    """Up timer that reloads from a register when it overflows (8051 mode-2 style auto-reload)."""
    top_v = (1 << w) - 1
    ports = ["input clk"] + RST_PORT[reset] + ["input run", "input rl_we", f"input [{w - 1}:0] rl_d", "output ovf",
                                               f"output [{w - 1}:0] cnt_o"]
    body = (f"  reg [{w - 1}:0] rl;\n  reg [{w - 1}:0] c;\n  reg ovf_r;\n  wire full = (c == {h(w, top_v)});\n" +
            seq(reset, [f"rl <= {d(w, 0)};"], "if (rl_we) rl <= rl_d;") +
            seq(reset, [f"c <= {d(w, 0)};", "ovf_r <= 1'b0;"],
                f"ovf_r <= run & full;\nif (run) c <= full ? rl : c + {d(w, 1)};") +
            "  assign ovf = ovf_r;\n  assign cnt_o = c;\n")

    def model(S, I):
        c, r = S["c"], I["run"] == 1
        full = c == top_v
        return {"c": W(r, W(full, S["rl"], c + 1), c), "rl": W(I["rl_we"] == 1, I["rl_d"], S["rl"]),
                "ovf_r": (r & full).astype(np.int64)}

    regs = [creg("c", w, modulus=None, saturating=False, load=True,
                 rule="up timer: +1 per clock under run; at all-ones it reloads the value of register rl (an opaque "
                      "load at overflow: modulus null)",
                 when={"inputs": {"run": 1}, "domain": {"c": rng_(0, top_v)}}),
            Reg("rl", w, "data_register", rule="reload register, written on rl_we"),
            Reg("ovf_r", 1, "flag", rule="registered overflow pulse")]
    return Design(name, "counter_reload", f"{w}-bit up timer with auto-reload from a register at overflow; reset {reset}",
                  module(ports, body), regs, [Check("model", model)], quiet=QUIET[reset])


def _sub(name, ports, body):
    return module(ports, body, name=name)


def g_casc_mixed(variant):
    """Two counters of opposite count directions in separate modules, the second counting the
    first's terminal count: a cascade relation between two counters, never one counter."""
    note = ("two counters of opposite count directions in separate modules, the second enabled by the first's "
            "terminal count: a cascade relation between two counters (docs/S3_DESIGN.md section 3.4), never one "
            "counter (no lenient unit)")
    if variant == "pre_up_tmr_dn":
        pre = _sub("presc", ["input clk", "input rst_n", "input en", "output tick"],
                   "  reg [7:0] p;\n  assign tick = en & (p == 8'd199);\n" +
                   seq("async", ["p <= 8'd0;"], "if (en) p <= (p == 8'd199) ? 8'd0 : p + 8'd1;"))
        tmr = _sub("dtimer", ["input clk", "input rst_n", "input tick", "input start", "input per_we",
                              "input [15:0] per_d", "output expired", "output [15:0] cnt"],
                   "  reg [15:0] period;\n  reg [15:0] c;\n  reg exp_r;\n  wire zero = (c == 16'd0);\n" +
                   seq("async", ["period <= 16'd999;"], "if (per_we) period <= per_d;") +
                   seq("async", ["c <= 16'd0;", "exp_r <= 1'b0;"],
                       "exp_r <= tick & zero;\nif (start) c <= period;\nelse if (tick) c <= zero ? period : c - 16'd1;") +
                   "  assign expired = exp_r;\n  assign cnt = c;\n")
        top = module(["input clk", "input rst_n", "input en", "input start", "input per_we", "input [15:0] per_d",
                      "output expired", "output [15:0] cnt_o"],
                     "  wire tick;\n  presc u_pre (.clk(clk), .rst_n(rst_n), .en(en), .tick(tick));\n"
                     "  dtimer u_tm (.clk(clk), .rst_n(rst_n), .tick(tick), .start(start), .per_we(per_we), "
                     ".per_d(per_d), .expired(expired), .cnt(cnt_o));\n")

        def model(S, I):
            p, c, pr = S["u_pre.p"], S["u_tm.c"], S["u_tm.period"]
            e = I["en"] == 1
            tick = e & (p == 199)
            z = c == 0
            return {"u_pre.p": W(e, W(p == 199, 0, p + 1), p),
                    "u_tm.c": W(I["start"] == 1, pr, W(tick, W(z, pr, (c - 1) & 0xFFFF), c)),
                    "u_tm.period": W(I["per_we"] == 1, I["per_d"], pr), "u_tm.exp_r": (tick & z).astype(np.int64)}

        regs = [creg("u_pre.p", 8, modulus=200, module_def="presc", local="p",
                     rule="prescaler (module presc): +1 per enabled clock, mod 200; its wrap is the timer's tick",
                     when={"inputs": {"en": 1}, "domain": {"u_pre.p": list(range(200))}}),
                creg("u_tm.c", 16, direction="down", modulus=None, saturating=False, load=True, module_def="dtimer",
                     local="c", rule="timer (module dtimer): -1 per prescaler tick, reloads the period register at "
                                     "zero and on start",
                     when={"inputs": {"en": 1, "start": 0}, "domain": {"u_pre.p": [199], "u_tm.c": rng_(1, 1 << 16)}}),
                Reg("u_tm.period", 16, "data_register", module_def="dtimer", local="period", rule="period register"),
                Reg("u_tm.exp_r", 1, "flag", module_def="dtimer", local="exp_r", rule="registered expiry pulse")]
        return Design("casc_pre200up_tmr16dn_ar", "counter_cascade_mixed",
                      "mod-200 up prescaler (own module) ticking a 16-bit reloadable down timer (own module)",
                      pre + tmr + top, regs, [Check("model", model, domain={"u_pre.p": list(range(200))})],
                      quiet=QUIET["async"], notes=[note])
    if variant == "div_dn_ev_up":
        div = _sub("divdn", ["input clk", "input rst", "input en", "output tc"],
                   "  reg [3:0] dv;\n  assign tc = en & (dv == 4'd0);\n" +
                   seq("sync", ["dv <= 4'd9;"], "if (en) dv <= (dv == 4'd0) ? 4'd9 : dv - 4'd1;"))
        ev = _sub("evcnt", ["input clk", "input rst", "input inc", "output [11:0] n_o"],
                  "  reg [11:0] n;\n" + seq("sync", ["n <= 12'd0;"], "if (inc) n <= n + 12'd1;") + "  assign n_o = n;\n")
        top = module(["input clk", "input rst", "input en", "output [11:0] events"],
                     "  wire tc;\n  divdn u_div (.clk(clk), .rst(rst), .en(en), .tc(tc));\n"
                     "  evcnt u_ev (.clk(clk), .rst(rst), .inc(tc), .n_o(events));\n")

        def model(S, I):
            dv, n = S["u_div.dv"], S["u_ev.n"]
            e = I["en"] == 1
            tc = e & (dv == 0)
            return {"u_div.dv": W(e, W(dv == 0, 9, dv - 1), dv), "u_ev.n": W(tc, (n + 1) & 4095, n)}

        regs = [creg("u_div.dv", 4, direction="down", modulus=10, module_def="divdn", local="dv",
                     rule="down divider (module divdn): -1 per enabled clock, 9..0 then 9 again (mod 10)",
                     when={"inputs": {"en": 1}, "domain": {"u_div.dv": list(range(10))}}),
                creg("u_ev.n", 12, module_def="evcnt", local="n",
                     rule="up event counter (module evcnt): +1 on the divider's terminal count (mod 4096)",
                     when={"inputs": {"en": 1}, "domain": {"u_div.dv": [0]}})]
        return Design("casc_div10dn_ev12up_sr", "counter_cascade_mixed",
                      "mod-10 down divider (own module) counted by a 12-bit up event counter (own module)",
                      div + ev + top, regs, [Check("model", model, domain={"u_div.dv": list(range(10))})],
                      quiet=QUIET["sync"], notes=[note])
    # variant "pre_up_sat_dn": a mod-50 prescaler and a loadable down counter that stops at 0
    pre = _sub("pre50", ["input clk", "input rst_n", "input en", "output wrap"],
               "  reg [5:0] p;\n  assign wrap = en & (p == 6'd49);\n" +
               seq("async", ["p <= 6'd0;"], "if (en) p <= (p == 6'd49) ? 6'd0 : p + 6'd1;"))
    ds = _sub("dsat", ["input clk", "input rst_n", "input dec", "input ld", "input [9:0] din", "output done"],
              "  reg [9:0] r;\n  assign done = (r == 10'd0);\n" +
              seq("async", ["r <= 10'd0;"], "if (ld) r <= din;\nelse if (dec && r != 10'd0) r <= r - 10'd1;"))
    top = module(["input clk", "input rst_n", "input en", "input ld", "input [9:0] din", "output done"],
                 "  wire wrap;\n  pre50 u_p (.clk(clk), .rst_n(rst_n), .en(en), .wrap(wrap));\n"
                 "  dsat u_d (.clk(clk), .rst_n(rst_n), .dec(wrap), .ld(ld), .din(din), .done(done));\n")

    def model3(S, I):
        p, r = S["u_p.p"], S["u_d.r"]
        e = I["en"] == 1
        wrap = e & (p == 49)
        return {"u_p.p": W(e, W(p == 49, 0, p + 1), p),
                "u_d.r": W(I["ld"] == 1, I["din"], W(wrap & (r != 0), r - 1, r))}

    regs = [creg("u_p.p", 6, modulus=50, module_def="pre50", local="p", rule="mod-50 up prescaler (module pre50)",
                 when={"inputs": {"en": 1}, "domain": {"u_p.p": list(range(50))}}),
            creg("u_d.r", 10, direction="down", modulus=None, saturating=True, load=True, module_def="dsat", local="r",
                 rule="down counter (module dsat): -1 per prescaler wrap, stops at 0; loads din on ld",
                 when={"inputs": {"en": 1, "ld": 0}, "domain": {"u_p.p": [49], "u_d.r": list(range(1, 1024))}})]
    return Design("casc_pre50up_dnsat10_ar", "counter_cascade_mixed",
                  "mod-50 up prescaler (own module) decrementing a loadable 10-bit down counter that stops at 0 "
                  "(own module)", pre + ds + top, regs, [Check("model", model3, domain={"u_p.p": list(range(50))})],
                  quiet=QUIET["async"], notes=[note])


def g_nlfsr(name, w, terms, reset, en, direction, seed=1, debruijn=False, family="shift_nonlinear"):
    """A shift chain whose head is nonlinear logic over its own stages: stage k (0 = head) copies
    stage k-1; the head takes XOR over `terms` of AND(stages in the term) (an NLFSR). debruijn: the
    head also XORs NOR(stages 0..w-2), which inserts the all-zero state into a maximal LFSR's cycle
    (a de Bruijn sequence, period 2^w). Stage k is RTL bit k (to_msb) or w-1-k (to_lsb)."""
    rb = (lambda k: k) if direction == "to_msb" else (lambda k: w - 1 - k)
    parts = [" & ".join(f"s[{rb(k)}]" for k in t) for t in terms]
    fb = " ^ ".join(f"({p})" if "&" in p else p for p in parts)
    if debruijn:
        fb += f" ^ (s[{w - 2}:0] == {d(w - 1, 0)})" if direction == "to_msb" else f" ^ (s[{w - 1}:1] == {d(w - 1, 0)})"
    shx = f"{{s[{w - 2}:0], fb}}" if direction == "to_msb" else f"{{fb, s[{w - 1}:1]}}"
    ports = ["input clk"] + RST_PORT[reset] + (["input en"] if en else []) + [f"output [{w - 1}:0] q"]
    body = (f"  reg [{w - 1}:0] s;\n  wire fb = {fb};\n" +
            seq(reset, [f"s <= {h(w, seed)};"], f"if (en) s <= {shx};" if en else f"s <= {shx};") + "  assign q = s;\n")
    m = (1 << w) - 1

    def stage(s, k):
        return (s >> rb(k)) & 1

    def fbv(s):
        v = 0
        for t in terms:
            a = 1
            for k in t:
                a = a & stage(s, k)
            v = v ^ a
        if debruijn:
            rest = (s & (m >> 1)) if direction == "to_msb" else (s >> 1)
            v = v ^ (rest == 0).astype(np.int64) if isinstance(s, np.ndarray) else v ^ int(rest == 0)
        return v

    def step(s):
        f = fbv(s)
        return (((s << 1) | f) & m) if direction == "to_msb" else ((f << (w - 1)) | (s >> 1))

    def model(S, I):
        return {"s": W(I["en"] == 1, step(S["s"]), S["s"]) if en else step(S["s"])}

    def sym(bit):
        xs = [e_and([bit("s", rb(k)) for k in t]) for t in terms]
        if debruijn:
            xs.append(e_and([e_not(bit("s", rb(k))) for k in range(w - 1)]))
        return e_xor(xs)

    order = [rb(k) for k in range(w)]
    head = OwnHead(lambda S, I: fbv(S["s"]), sym, fb)
    kind_txt = "de Bruijn shift (a maximal LFSR with the all-zero state inserted)" if debruijn else "NLFSR"
    reg = sreg("s", w, [order], direction, [None], head=[head], head_sym=[sym],
               rule=f"{kind_txt}: stages 1..{w - 1} copy their predecessor" + (" under en" if en else "") +
                    f"; the head takes {fb} (nonlinear in its own bits)",
               when={"inputs": {"en": 1} if en else {}})

    def f_nonlinear():
        rng = np.random.default_rng(w)
        a, b, c = (rng.integers(0, 1 << w, 4096, dtype=np.int64) for _ in range(3))
        bad = int(((step(a) ^ step(b) ^ step(c)) != step(a ^ b ^ c)).sum())
        return {"method": "the model's update fails n(a)^n(b)^n(c) == n(a^b^c) on some of 4,096 random triples "
                          "(a witness proves it is not GF(2)-affine: not an lfsr_crc)", "violations": bad, "ok": bad > 0}

    facts = [("s", "nonlinear", f_nonlinear)]
    if debruijn:
        def f_period():
            s, seen = 0, set()
            while s not in seen:
                seen.add(s)
                s = int(step(np.int64(s)))
            return {"method": "orbit of the model from state 0", "period": len(seen), "returns_to_0": s == 0,
                    "ok": len(seen) == 1 << w and s == 0}
        facts.append(("s", "de_bruijn_period", f_period))
    return Design(name, family, f"{w}-bit {kind_txt}, {direction}" + (", enable" if en else "") + f"; reset {reset}",
                  module(ports, body), [reg], [Check("model", model)], quiet=QUIET[reset], facts=facts,
                  notes=["a shift chain whose head is nonlinear in its own bits: S3 sends a self-fed head to the LFSR "
                         "test (docs/S3_DESIGN.md section 3.3); it is not GF(2)-affine, so the truth is shift_register "
                         f"(D[k] = Q[k-1] on {w - 1} of {w} bits) with a logic head (serial_in null)"])


def g_gf2map(name, w, ops, reset, en, seed=1, family="lfsr_affine"):
    """A GF(2)-linear register that is not a companion matrix: a product of xorshift steps. ops:
    ("xl", a): x ^= x << a; ("xr", a): x ^= x >> a (each step is invertible)."""
    m = (1 << w) - 1
    wires, prev = [], "x"
    for i, (op, a) in enumerate(ops):
        wires.append(f"  wire [{w - 1}:0] t{i} = {prev} ^ ({prev} {'<<' if op == 'xl' else '>>'} {a});\n")
        prev = f"t{i}"
    ports = ["input clk"] + RST_PORT[reset] + (["input en"] if en else []) + [f"output [{w - 1}:0] rnd"]
    body = (f"  reg [{w - 1}:0] x;\n" + "".join(wires) +
            seq(reset, [f"x <= {h(w, seed)};"], f"if (en) x <= {prev};" if en else f"x <= {prev};") + "  assign rnd = x;\n")

    def step(x, _x=0):
        for op, a in ops:
            x = x ^ (((x << a) & m) if op == "xl" else (x >> a))
        return x & m

    def model(S, I):
        return {"x": W(I["en"] == 1, step(S["x"]), S["x"]) if en else step(S["x"])}

    txt = "; ".join(f"x ^= x {'<<' if op == 'xl' else '>>'} {a}" for op, a in ops)
    reg = Reg("x", w, "lfsr_crc", dict(form="affine", poly=None, k_steps=None, n_inputs=0),
              rule=f"xorshift map ({txt}): GF(2)-linear in its own bits, not a companion matrix (poly and step count "
                   "undefined; the characteristic polynomial is in provenance.polynomial)",
              when={"inputs": {"en": 1} if en else {}})
    return Design(name, family, f"{w}-bit xorshift register ({txt})" + (", enable" if en else "") + f"; reset {reset}",
                  module(ports, body), [reg], [Check("model", model)], quiet=QUIET[reset], lfsr_models={"x": (w, step)},
                  notes=["GF(2)-linear in its own bits but not a Fibonacci or Galois companion matrix (every row and "
                         "column has several taps): lfsr_crc with form affine (schema.py LFSR_FORMS)"])


def g_shift_mixrst(name, lanes, parts, out="all"):
    """One RTL vector shifted toward the MSB under `sh`, whose stages differ in reset: parts are
    (stages, "async" | "async_set" | "sync" | "none") from stage 0, each written by its own always block."""
    depth = sum(n for n, _k in parts)
    Wd = lanes * depth
    kinds = {k for _n, k in parts}
    ports = ["input clk"] + (["input rst_n"] if kinds & {"async", "async_set"} else []) + \
        (["input rst"] if "sync" in kinds else []) + ["input sh", f"input [{lanes - 1}:0] din" if lanes > 1 else "input din"]
    ports.append(f"output [{Wd - 1}:0] q" if out == "all" else
                 (f"output [{lanes - 1}:0] dout" if lanes > 1 else "output dout"))
    body, a = f"  reg [{Wd - 1}:0] v;\n", 0
    for n, kind in parts:
        lo, hi = a * lanes, (a + n) * lanes - 1
        if a == 0:
            nxt = "din" if n == 1 else f"{{v[{hi - lanes}:0], din}}"
        else:
            nxt = f"v[{hi - lanes}:{lo - lanes}]"
        width = hi - lo + 1
        upd = f"if (sh) v[{hi}:{lo}] <= {nxt};"
        if kind in ("async", "async_set"):
            rv = h(width, (1 << width) - 1) if kind == "async_set" else d(width, 0)
            body += (f"  always @(posedge clk or negedge rst_n)\n    if (!rst_n) v[{hi}:{lo}] <= {rv};\n"
                     f"    else {upd}\n")
        elif kind == "sync":
            body += f"  always @(posedge clk)\n    if (rst) v[{hi}:{lo}] <= {d(width, 0)};\n    else {upd}\n"
        else:
            body += f"  always @(posedge clk)\n    {upd}\n"
        a += n
    body += "  assign q = v;\n" if out == "all" else f"  assign dout = v[{Wd - 1}:{Wd - lanes}];\n"
    msk = (1 << Wd) - 1

    def model(S, I):
        return {"v": W(I["sh"] == 1, ((S["v"] << lanes) | I["din"]) & msk, S["v"])}

    def span(i):
        a0, a1 = sum(n for n, _ in parts[:i]), sum(n for n, _ in parts[:i + 1]) - 1
        return f"stage {a0}" if a0 == a1 else f"stages {a0}-{a1}"
    what = {"async": "async clear", "async_set": "async set", "sync": "sync clear", "none": "no reset"}
    txt = ", ".join(f"{span(i)} {what[k]}" for i, (_n, k) in enumerate(parts))
    quiet = {**({"rst_n": 1} if kinds & {"async", "async_set"} else {}), **({"rst": 0} if "sync" in kinds else {})}
    reg = sreg("v", Wd, lanes_msb(lanes, depth), "to_msb", [pin("din", lanes, j) for j in range(lanes)],
               rule=f"{lanes} lane(s) x depth {depth} under sh, one RTL vector whose stages differ in reset ({txt})",
               when={"inputs": {"sh": 1}})
    return Design(name, "shift_mixed_reset", f"shift register, {lanes} lane(s) x depth {depth}, stages with mixed resets "
                  f"({txt})", module(ports, body), [reg], [Check("model", model)], quiet=quiet,
                  notes=["one RTL shift vector whose stages differ in reset (asynchronous, synchronous or none): one "
                         "shift register; its flops differ in master and reset pins, not in the copy condition"])


def g_case_updown(name, w, M, reset, en):
    """Mod-M up/down counter written as a case table over {dir_up, c}; every out-of-range state
    (M..2^w-1) goes to 0 in both directions (the case default)."""
    items = [f"      {d(w + 1, (1 << w) | s)}: c <= {d(w, (s + 1) % M)};" for s in range(M)]
    items += [f"      {d(w + 1, s)}: c <= {d(w, (s - 1) % M)};" for s in range(M)]
    case = "case ({dir_up, c})\n" + "\n".join(x.strip() for x in items) + f"\ndefault: c <= {d(w, 0)};\nendcase"
    upd = ("if (en) begin\n" + textwrap.indent(case, "  ") + "\nend") if en else case
    ports = ["input clk"] + RST_PORT[reset] + (["input en"] if en else []) + ["input dir_up", f"output [{w - 1}:0] cnt_o"]
    body = f"  reg [{w - 1}:0] c;\n" + seq(reset, [f"c <= {d(w, 0)};"], upd) + "  assign cnt_o = c;\n"

    def model(S, I):
        c = S["c"]
        ok = c < M
        nx = W(I["dir_up"] == 1, W(ok, (c + 1) % M, 0), W(ok, (c - 1) % M, 0))
        return {"c": W(I["en"] == 1, nx, c) if en else nx}

    base = {"en": 1} if en else {}
    reg = creg("c", w, direction="updown", modulus=M,
               rule=f"mod-{M} up/down counter by dir_up, written as a case table over {{dir_up, c}}; out-of-range states "
                    f"{M}..{(1 << w) - 1} go to 0 (case default)",
               when={"inputs": dict(base, dir_up=1), "domain": {"c": list(range(M))}},
               when_down={"inputs": dict(base, dir_up=0), "domain": {"c": list(range(M))}})
    return Design(name, "counter_case", f"case-coded mod-{M} up/down counter, out-of-range states to 0"
                  + (", enable" if en else "") + f"; reset {reset}", module(ports, body), [reg], [Check("model", model)],
                  quiet=QUIET[reset])


def g_acc_narrow(name, w, sw, reset, en=True, dump=False):
    """An accumulator whose addend is a narrow input sample (sw bits into w): its upper bits count the
    carries out of the lower ones. dump: the sum is copied out and the accumulator restarts."""
    ports = ["input clk"] + RST_PORT[reset] + (["input en"] if en else []) + (["input dump"] if dump else []) + \
        [f"input [{sw - 1}:0] smp", f"output [{w - 1}:0] sum_o"]
    add = f"acc <= acc + {{{d(w - sw, 0)}, smp}};"
    if dump:
        upd = f"if (dump) begin\n  out_r <= acc;\n  acc <= {{{d(w - sw, 0)}, smp}};\nend else " + (f"if (en) {add}" if en else add)
        body = (f"  reg [{w - 1}:0] acc;\n  reg [{w - 1}:0] out_r;\n" +
                seq(reset, [f"acc <= {d(w, 0)};", f"out_r <= {d(w, 0)};"], upd) + "  assign sum_o = out_r;\n")
    else:
        body = f"  reg [{w - 1}:0] acc;\n" + seq(reset, [f"acc <= {d(w, 0)};"], f"if (en) {add}" if en else add) + \
            "  assign sum_o = acc;\n"
    msk = (1 << w) - 1

    def model(S, I):
        a = S["acc"]
        nx = W(I["en"] == 1, (a + I["smp"]) & msk, a) if en else (a + I["smp"]) & msk
        o = {}
        if dump:
            dp = I["dump"] == 1
            o["acc"] = W(dp, I["smp"], nx)
            o["out_r"] = W(dp, a, S["out_r"])
        else:
            o["acc"] = nx
        return o

    regs = [Reg("acc", w, "accumulator", rule=f"acc + a {sw}-bit sample (a varying +c); its upper {w - sw} bits count "
                                              "the carries out of the lower ones")]
    if dump:
        regs.append(Reg("out_r", w, "data_register", rule="the sum, copied out on dump"))
    return Design(name, "negative_accumulator", f"{w}-bit accumulator of a {sw}-bit sample" +
                  (" with accumulate-and-dump" if dump else "") + f"; reset {reset}", module(ports, body), regs,
                  [Check("model", model)], quiet=QUIET[reset],
                  notes=["an accumulator's upper bits count the carries out of its lower bits: a counter only under a "
                         "condition that reads its own register; the truth kind is accumulator (not scored)"])


def g_nco(name, w, reset):
    """A phase accumulator (NCO): phase += fcw, the frequency word held in a register."""
    ports = ["input clk"] + RST_PORT[reset] + ["input we", f"input [{w - 1}:0] wdata", "output tone"]
    body = (f"  reg [{w - 1}:0] fcw;\n  reg [{w - 1}:0] phase;\n" +
            seq(reset, [f"fcw <= {d(w, 0)};"], "if (we) fcw <= wdata;") +
            seq(reset, [f"phase <= {d(w, 0)};"], "phase <= phase + fcw;") + f"  assign tone = phase[{w - 1}];\n")
    msk = (1 << w) - 1
    return Design(name, "negative_accumulator", f"{w}-bit phase accumulator (NCO) with a frequency register; reset {reset}",
                  module(ports, body),
                  [Reg("phase", w, "accumulator", rule="phase + fcw (fcw a register: a varying +c)"),
                   Reg("fcw", w, "data_register", rule="frequency control word, written on we")],
                  [Check("model", lambda S, I: {"phase": (S["phase"] + S["fcw"]) & msk,
                                                "fcw": W(I["we"] == 1, I["wdata"], S["fcw"])})], quiet=QUIET[reset])


def g_lcg(name, w, a, c, reset, en):
    """Linear congruential generator x' = a*x + c mod 2^w (a = 1 mod 4, c odd: full period)."""
    assert a % 4 == 1 and c % 2 == 1
    ports = ["input clk"] + RST_PORT[reset] + (["input en"] if en else []) + [f"output [{w - 1}:0] rnd"]
    upd = f"x <= x * {d(w, a)} + {d(w, c)};"
    body = f"  reg [{w - 1}:0] x;\n" + seq(reset, [f"x <= {d(w, 1)};"], f"if (en) {upd}" if en else upd) + "  assign rnd = x;\n"
    msk = (1 << w) - 1

    def step(x):
        return (x * a + c) & msk

    def model(S, I):
        return {"x": W(I["en"] == 1, step(S["x"]), S["x"]) if en else step(S["x"])}

    dirn = "up" if c % 4 == 1 else "down"
    reg = Reg("x", w, "other", rule=f"LCG x' = {a}x + {c} mod 2^{w}: an integer affine map (a varying +c), neither a "
                                    "counter nor GF(2)-linear; no bit order makes the word a counter (checked)",
              bit_alt={0: ["counter"], 1: ["counter"]},
              alt_reason=f"bits 0-1 alone form a mod-4 {dirn} counter (a = 1 mod 4, so x mod 4 steps by c mod 4 = "
                         f"{c % 4}); bit-level alternatives only")
    return Design(name, "negative_lcg", f"{w}-bit linear congruential generator (x*{a} + {c})" +
                  (", enable" if en else "") + f"; reset {reset}", module(ports, body), [reg], [Check("model", model)],
                  quiet=QUIET[reset], counter_negatives=[("x", w, step)],
                  notes=["the low bits of an LCG are counters (x mod 4 counts by c mod 4); the register is not"])


def g_hist(name, ch, sw, depth, reset, style):
    """Per-channel sample histories of equal depth under one enable: channel i shifts din's sample
    i. style "gen": a register per channel (generate); "vec": slices of one vector in a for loop."""
    L = sw * depth
    ports = ["input clk"] + RST_PORT[reset] + ["input en", f"input [{ch * sw - 1}:0] din", f"input [{max(1, (ch - 1).bit_length()) - 1}:0] rsel",
                                               f"output [{L - 1}:0] rhist"]
    shx = (lambda v: f"{{{v}[{L - sw - 1}:0], din[{sw}*i +: {sw}]}}") if depth > 1 else None
    if style == "gen":
        body = ("  wire [{0}:0] all;\n  genvar i;\n  generate for (i = 0; i < {1}; i = i + 1) begin : g\n"
                "    reg [{2}:0] h;\n").format(ch * L - 1, ch, L - 1) + \
            seq(reset, [f"h <= {d(L, 0)};"], f"if (en) h <= {shx('h')};", ind=4) + \
            f"    assign all[{L}*i +: {L}] = h;\n  end endgenerate\n  assign rhist = all[{L}*rsel +: {L}];\n"
        names = [f"g[{i}].h" for i in range(ch)]
        regs = [sreg(n, L, lanes_msb(sw, depth), "to_msb", [pin("din", ch * sw, sw * i + j) for j in range(sw)],
                     local="g[*].h", rule=f"channel {i} history: {sw} lane(s) x depth {depth} under the shared en",
                     when={"inputs": {"en": 1}}) for i, n in enumerate(names)]
        lane_bits = lambda i: [(names[i], b) for b in range(L)]  # noqa: E731
    else:
        body = (f"  reg [{ch * L - 1}:0] hist;\n  integer i;\n" +
                seq(reset, [f"hist <= {d(ch * L, 0)};"],
                    f"if (en)\n  for (i = 0; i < {ch}; i = i + 1)\n"
                    f"    hist[{L}*i +: {L}] <= {{hist[{L}*i +: {L - sw}], din[{sw}*i +: {sw}]}};") +
                f"  assign rhist = hist[{L}*rsel +: {L}];\n")
        names = [f"hist[{(i + 1) * L - 1}:{i * L}]" for i in range(ch)]
        regs = []
        for i, n in enumerate(names):
            r = sreg(n, L, lanes_msb(sw, depth), "to_msb", [pin("din", ch * sw, sw * i + j) for j in range(sw)],
                     rtl="hist", rtl_bits=tuple(range(i * L, (i + 1) * L)), local="hist[*]",
                     rule=f"channel {i} history (slice of one vector): {sw} lane(s) x depth {depth} under the shared en",
                     when={"inputs": {"en": 1}})
            regs.append(r)
        lane_bits = lambda i: [(names[i], b) for b in range(L)]  # noqa: E731
    msk = (1 << L) - 1
    smask = (1 << sw) - 1

    def model(S, I):
        e = I["en"] == 1
        o = {}
        if style == "gen":
            for i, n in enumerate(names):
                o[n] = W(e, ((S[n] << sw) | ((I["din"] >> (sw * i)) & smask)) & msk, S[n])
        else:
            v = S["hist"]
            nv = 0
            for i in range(ch):
                sl = (v >> (L * i)) & msk
                nv = nv | ((((sl << sw) | ((I["din"] >> (sw * i)) & smask)) & msk) << (L * i))
            o["hist"] = W(e, nv, v)
        return o

    order = []
    for i in range(ch):
        bits = lane_bits(i)
        for j in range(sw):
            order.append([bits[k * sw + j] for k in range(depth)])
    heads = [pin("din", ch * sw, sw * i + j) for i in range(ch) for j in range(sw)]
    units = [unit(f"{ch} channel histories as one {ch * sw}-lane shift register", "shift_register", names,
                  "equal-depth histories under one enable with input-pin heads: S3's lane rule (section 3.3) joins "
                  "them into one multi-lane structure, and no structural key orders the channels (lanes_unordered)",
                  params={"lanes": ch * sw, "depth": depth, "direction": "to_msb", "serial_in": heads, "order": order},
                  when={"inputs": {"en": 1}})]
    return Design(name, "shift_multichannel", f"{ch} per-channel histories ({sw}-bit samples, depth {depth}) under one "
                  f"enable, {style} style; reset {reset}", module(ports, body), regs, [Check("model", model)], units,
                  quiet=QUIET[reset],
                  notes=["per-channel histories under one enable merge into one multi-lane shift structure by S3's "
                         "lane rule: the strict truth has one register per channel, the lenient unit all channels"])


def g_concat(name, parts, reset, en, dirn="up"):
    """Several RTL registers written by one adder over their concatenation ({hi, lo} <= {hi, lo} + 1)."""
    Wt = sum(wp for _n, wp in parts)
    cat = "{" + ", ".join(n for n, _w in reversed(parts)) + "}"
    op = "+" if dirn == "up" else "-"
    upd = f"{cat} <= {cat} {op} {d(Wt, 1)};"
    ports = ["input clk"] + RST_PORT[reset] + (["input en"] if en else []) + [f"output [{Wt - 1}:0] cnt_o"]
    body = "".join(f"  reg [{wp - 1}:0] {n};\n" for n, wp in parts) + \
        seq(reset, [f"{n} <= {d(wp, 0)};" for n, wp in parts], f"if (en) {upd}" if en else upd) + f"  assign cnt_o = {cat};\n"
    msk = (1 << Wt) - 1

    def model(S, I):
        v, off = 0, 0
        for n, wp in parts:
            v = v | (S[n] << off)
            off += wp
        nv = (v + (1 if dirn == "up" else -1)) & msk
        if en:
            nv = W(I["en"] == 1, nv, v)
        out, off = {}, 0
        for n, wp in parts:
            out[n] = (nv >> off) & ((1 << wp) - 1)
            off += wp
        return out

    base = {"en": 1} if en else {}
    regs, lower = [], {}
    for i, (n, wp) in enumerate(parts):
        regs.append(creg(n, wp, direction=dirn, rule=f"bits of one {Wt}-bit {dirn} counter written as {cat}: "
                                                      + ("counts every enabled clock" if i == 0 else
                                                         "counts the carries of the registers below it"),
                         when={"inputs": dict(base), "domain": dict(lower)} if lower else {"inputs": dict(base)}))
        lower[n] = [(1 << wp) - 1 if dirn == "up" else 0]
    units = [unit(f"{cat} as one counter", "counter", [n for n, _w in parts],
                  f"one {Wt}-bit counter: the RTL writes {cat} with a single adder",
                  params={"direction": dirn, "step": 1, "modulus": 1 << Wt, "saturating": False, "load": False,
                          "bit_order": [(n, b) for n, wp in parts for b in range(wp)]}, when={"inputs": dict(base)})]
    return Design(name, "counter_concat", f"{cat}: {len(parts)} registers written by one {Wt}-bit {dirn} adder"
                  + (" under en" if en else "") + f"; reset {reset}", module(ports, body), regs, [Check("model", model)],
                  units, quiet=QUIET[reset],
                  notes=["registers written by one adder over their concatenation: one counter (lenient unit) or "
                         "cascaded counters (strict registers)"])


def cohort2():
    C = g_counter
    ds = [
        # reloadable down timers (and an auto-reload up timer), widths above EXHAUSTIVE_WIDTH
        g_reload_timer("tmr_reload_w16_case_sr", 16, "sync", "case"),
        g_reload_timer("tmr_reload_w20_if_ar", 20, "async", "if"),
        g_reload_timer("tmr_oneshot_w24_if_ar", 24, "async", "if", oneshot=True),
        g_reload_timer("tmr_reload_w13_case_nr", 13, "none", "case", out="flag", p0=4000),
        g_autoreload_up("tmr_up_autoreload_w16_ar", 16, "async"),
        # wide counters (above WORD_CAP = 32 bits)
        C("cnt_up_w40_en_ar", 40, family="counter_wide"),
        C("cnt_up_w48_free_sr", 48, en=None, reset="sync", family="counter_wide"),
        C("cnt_up_w64_en_clrset_ar", 64, load="const", setv=0x0123456789ABCDEF, family="counter_wide"),
        C("cnt_down_w36_load_ar", 36, dirn="down", load="opaque", family="counter_wide"),
        C("cnt_updown_w33_en_nr", 33, reset="none", dirn="updown", family="counter_wide"),
        # mixed-direction cascades across modules
        g_casc_mixed("pre_up_tmr_dn"), g_casc_mixed("div_dn_ev_up"), g_casc_mixed("pre_up_sat_dn"),
        # NLFSRs and de Bruijn shifts
        g_nlfsr("nlfsr_w9_en_ar", 9, [(8,), (3,), (5, 1), (6, 2, 0)], "async", True, "to_msb", seed=0x1B5),
        g_nlfsr("nlfsr_w12_lsb_sr", 12, [(11,), (8,), (2,), (9, 4), (7, 6, 3)], "sync", False, "to_lsb", seed=0x9C3),
        g_nlfsr("debruijn_w6_ar", 6, [(4,), (5,)], "async", False, "to_msb", seed=0, debruijn=True),
        g_nlfsr("debruijn_w10_lsb_en_nr", 10, [(6,), (9,)], "none", True, "to_lsb", debruijn=True),
        # GF(2)-linear maps that are not companion matrices
        g_gf2map("xorshift16_en_ar", 16, [("xl", 5), ("xr", 11), ("xl", 6)], "async", True, seed=0xACE1),
        g_gf2map("xorshift32_en_sr", 32, [("xl", 13), ("xr", 17), ("xl", 5)], "sync", True, seed=0x2545F491),
        g_gf2map("xorshift20_rlr_nr", 20, [("xr", 7), ("xl", 9), ("xr", 4)], "none", False),
        g_gf2map("xorshift12_two_ar", 12, [("xl", 3), ("xr", 1)], "async", True, seed=0x5A5),
        # word-parallel CRCs, k >= w, w in 12..32
        # (crc12_d16_ar, poly 0x180F, was DROPPED on 2026-09-22: functionally the same CRC-12 as the
        #  held-out regression set's crc12_d16_ar, so every regression LFSR/CRC figure that included
        #  it was part training data. See DROPPED below and changes.jsonl C25 / C36.)
        g_crc("crc15_d16_sr", 15, 0xC599, 16, "msb", reset="sync", init=0, family="crc_wide"),
        g_crc("crc16_d16_ar", 16, 0x18005, 16, "reflected", family="crc_wide"),
        g_crc("crc24_d32_ar", 24, 0x1864CFB, 32, "msb", init=0xB704CE, family="crc_wide"),
        g_crc("crc32_d32_nr", 32, 0x104C11DB7, 32, "reflected", reset="none", family="crc_wide"),
        # trinomial CRCs, Galois and Fibonacci RTL (params.form "both")
        g_crc("crc6_tri_gal_ar", 6, 0x43, 1, "msb", init=0, family="crc_trinomial"),
        g_lfsr("crc9_tri_fib_sr", 9, "fibonacci", 0x211, reset="sync", seed=0, din="serial", family="crc_trinomial"),
        g_crc("crc11_tri_gal_k4_ar", 11, 0x805, 4, "reflected", family="crc_trinomial"),
        g_lfsr("crc15_tri_fib_k2_nr", 15, "fibonacci", 0x8003, k=2, reset="none", seed=0, din="parallel",
               family="crc_trinomial"),
        # shift chains whose stages differ in reset
        g_shift_mixrst("sr_mixrst_d8_ar", 1, [(4, "async"), (4, "none")], out="serial"),
        g_shift_mixrst("sr_mixrst_head_d6_ar", 1, [(1, "async"), (5, "none")]),
        g_shift_mixrst("sr_mixrst_l2_d5_ar", 2, [(2, "async"), (3, "none")]),
        g_shift_mixrst("sr_mixrst_set_d7_ar", 1, [(3, "none"), (2, "async"), (2, "async_set")]),
        g_shift_mixrst("sr_mixrst_sync_d6_ar", 1, [(3, "async"), (3, "sync")], out="serial"),
        # case-coded mod-M up/down counters, out-of-range states to 0
        g_case_updown("cnt_case_mod5_ud_ar", 3, 5, "async", False),
        g_case_updown("cnt_case_mod9_ud_sr", 4, 9, "sync", False),
        g_case_updown("cnt_case_mod12_ud_en_ar", 4, 12, "async", True),
        g_case_updown("cnt_case_mod25_ud_en_nr", 5, 25, "none", True),
        # negatives: narrow-addend accumulators and LCGs
        g_acc_narrow("acc_w10_s4_en_sr", 10, 4, "sync"),
        g_acc_narrow("acc_w9_s2_en_nr", 9, 2, "none"),
        g_acc_narrow("acc_dump_w14_s3_ar", 14, 3, "async", dump=True),
        g_nco("nco_w16_ar", 16, "async"),
        g_lcg("lcg_w8_ar", 8, 13, 7, "async", False),
        g_lcg("lcg_w10_nr", 10, 21, 5, "none", False),
        g_lcg("lcg_w12_en_sr", 12, 1029, 221, "sync", True),
        g_lcg("lcg_w16_en_ar", 16, 25173, 13849, "async", True),
        # per-channel histories under one enable
        g_hist("hist_ch3_d5_gen_ar", 3, 1, 5, "async", "gen"),
        g_hist("hist_ch4_s2_d4_gen_sr", 4, 2, 4, "sync", "gen"),
        g_hist("hist_ch3_d4_vec_nr", 3, 1, 4, "none", "vec"),
        g_hist("hist_ch2_s3_d3_vec_ar", 2, 3, 3, "async", "vec"),
        # concatenated counters
        g_concat("cat_hilo_8x8_en_ar", [("lo", 8), ("hi", 8)], "async", True),
        g_concat("cat_hilo_4x12_sr", [("lo", 4), ("hi", 12)], "sync", False),
        g_concat("cat_hml_4x4x4_en_ar", [("lo", 4), ("mid", 4), ("hi", 4)], "async", True),
        g_concat("cat_hilo_dn_6x6_en_nr", [("lo", 6), ("hi", 6)], "none", True, dirn="down"),
    ]
    for x in ds:
        x.cohort = 2
    return ds


# ----------------------------------------------------------------------------------------------
# the corpus


def designs():
    C = g_counter
    ds = [
        C("cnt_up_w4_ar", 4, en=None),
        C("cnt_up_w8_en_ar", 8),
        C("cnt_up_w13_en_sr", 13, reset="sync"),
        C("cnt_up_w6_en_nr", 6, reset="none"),
        C("cnt_up_w16_en_ar_rv", 16, rv=0x00A5, out="tc"),
        C("cnt_up_w10_carry_ar", 10, en="carry"),
        C("cnt_up_w8_step3_sr", 8, reset="sync", step=3),
        C("cnt_down_w5_en_ar", 5, dirn="down"),
        C("cnt_down_w8_rvff_ar", 8, en=None, dirn="down", rv=255),
        C("cnt_down_w12_timer_ar", 12, dirn="down", sat=0, load="opaque", out="tc", family="counter_load"),
        C("cnt_updown_w4_ar", 4, en=None, dirn="updown", family="counter_updown"),
        C("cnt_updown_w7_en_sr", 7, reset="sync", dirn="updown", family="counter_updown"),
        C("cnt_updown_w10_load_ar", 10, dirn="updown", load="opaque", family="counter_updown"),
        C("cnt_load_opaque_w8_ar", 8, load="opaque", family="counter_load"),
        C("cnt_load_rel_w8_ar", 8, load="relative", K=5, family="counter_load"),
        C("cnt_load_both_w12_sr", 12, reset="sync", load="both", K=100, family="counter_load"),
        C("cnt_load_const_w6_ar", 6, load="const", setv=33, family="counter_load"),
        C("cnt_stop40_w6_ar", 6, sat=40, family="counter_saturating"),
        C("sat_up_w3_clr_ar", 3, sat=7, load="const", setv=4, family="counter_saturating"),
        C("sat_updown_w4_ar", 4, dirn="updown", sat=15, family="counter_saturating"),
        C("mod3_ar", 2, en=None, mod=3, family="counter_modulo"),
        C("mod5_en_ar", 3, mod=5, family="counter_modulo"),
        C("mod6_en_sr", 3, reset="sync", mod=6, family="counter_modulo"),
        C("mod10_en_ar", 4, mod=10, out="tc", family="counter_modulo"),
        C("mod11_ar", 4, en=None, mod=11, family="counter_modulo"),
        C("mod12_en_nr", 4, reset="none", mod=12, family="counter_modulo"),
        C("mod100_en_ar", 7, mod=100, family="counter_modulo"),
        C("mod10_down_en_ar", 4, dirn="down", mod=10, family="counter_modulo"),
        C("mod1000_en_sr", 10, reset="sync", mod=1000, out="tc", family="counter_modulo"),
        C("mod7_updown_ar", 3, dirn="updown", mod=7, family="counter_modulo"),
        C("mod20_ge_ar", 5, mod=20, cmp="ge", family="counter_modulo"),
        g_limit("cnt_stop_at_reg_w5_ar", 5, "stop"),
        g_limit("cnt_wrap_at_reg_w5_ar", 5, "wrap"),
        g_casc_10x6_done(),
        g_casc_bcd3(),
        g_casc_simple("casc_bin4x4_ar", "async", 4, 16, 4, 16),
        g_casc_simple("casc_mod5x7_pulse_sr", "sync", 3, 5, 3, 7, pulse=True),
        g_casc_simple("casc_pre12_cnt8_ar", "async", 4, 12, 8, 256),
        g_timer_hms(),
        g_bins8(), g_bins4_updown(), g_bins6_vec(),
    ]
    ds += g_toggles()
    ds += g_gray_family()
    S = g_shift
    ds += [
        S("sr_d3_en_ar", 1, 3, "async", True, "to_msb"),
        S("sr_d4_en_ar", 1, 4, "async", True, "to_msb"),
        S("sr_d8_en_nr_lsb", 1, 8, "none", True, "to_lsb", out="serial"),
        S("sr_d16_en_sr", 1, 16, "sync", True, "to_msb", out="serial"),
        S("sr_d6_en_ar_rv", 1, 6, "async", True, "to_lsb", rv=0b101101),
        S("sr_d5_loghead_ar", 1, 5, "async", False, "to_msb", head="logic"),
        S("sr_d8_noen_nr", 1, 8, "none", False, "to_msb", out="serial"),
        S("sr_l8_d4_en_ar", 8, 4, "async", True, "to_msb"),
        S("sr_l4_d3_en_nr_lsb", 4, 3, "none", True, "to_lsb"),
        S("sr_l2_d6_en_sr", 2, 6, "sync", True, "to_msb", out="serial"),
        S("sr_pload_d8_ar", 1, 8, "async", True, "to_msb", pload=True, out="serial"),
        S("sr_pload_l4_d4_sr_lsb", 4, 4, "sync", True, "to_lsb", pload=True),
        S("sr_d2_en_ar", 1, 2, "async", True, "to_msb"),
        S("sr_l8_d2_en_nr", 8, 2, "none", True, "to_msb"),
        g_shift_swapped(),
        g_two_chains("two_chains_d4_d5_en_ar", 4, 5),
        g_two_chains("two_chains_d4_d4_en_ar", 4, 4),
        g_uart_rx(), g_uart_tx(), g_spi(), g_deser_dreg(),
        g_sync("sync2_ar", 2, "async"),
        g_sync("sync3_ar", 3, "async"),
        g_sync("sync2_sr", 2, "sync"),
        g_sync("sync2_w4_stages_nr", 2, "none", width=4, style="stages"),
        g_sync("sync3_w2_gen_ar", 3, "async", width=2, style="generate"),
        g_sync("sync2_w3_hier_ar", 2, "async", width=3, style="hier"),
        g_sync_edge(),
    ]
    L = g_lfsr
    ds += [
        L("lfsr_fib_w5_ar", 5, "fibonacci", 0x29, en=False),
        L("lfsr_fib_w8_en_ar", 8, "fibonacci", 0x171, seed=0x5A),
        L("lfsr_fib_w16_en_sr", 16, "fibonacci", 0x16801, reset="sync", seed=0xACE1),
        L("lfsr_gal_w7_ar", 7, "galois", 0xC1, en=False),
        L("lfsr_gal_w12_en_sr", 12, "galois", 0x1053, reset="sync"),
        L("lfsr_gal_w16_ar_rv", 16, "galois", 0x16801, seed=0xACE1, out="serial"),
        L("lfsr_fib_w8_k4_ar", 8, "fibonacci", 0x171, k=4, seed=0xFF),
        L("lfsr_gal_w16_k8_ar", 16, "galois", 0x16801, k=8),
        L("lfsr_gal_w10_k3_nr", 10, "galois", 0x481, k=3, reset="none"),
        L("scr_fib_w7_serial_ar", 7, "fibonacci", 0x91, din="serial", seed=0x7F, family="scrambler"),
        L("scr_fib_w9_k8_ar", 9, "fibonacci", 0x221, k=8, din="parallel", seed=0x1FF, family="scrambler"),
        g_scr_modes(),
        g_crc("crc32_byte_ar", 32, 0x104C11DB7, 8, "reflected"),
        g_crc("crc16_ccitt_serial_sr", 16, 0x11021, 1, "msb", reset="sync"),
        g_crc("crc8_byte_ar", 8, 0x107, 8, "msb", init=0),
        g_crc("crc_prog_w16_serial_ar", 16, 0x11021, 1, "msb", prog=True),
        g_crc("crc_prog_w8_byte_ar", 8, 0x107, 8, "msb", prog=True),
        g_crc("crc_prog_w32_byte_ar", 32, 0x104C11DB7, 8, "msb", prog=True),
        g_prbs(),
    ]
    ds += g_pipes() + g_regfiles() + g_fsms() + g_accs() + [g_flags(), g_mut_carry()]
    ds += [g_pwm(), g_fifo(), g_debounce()]
    ds += cohort2()
    names = [x.name for x in ds]
    dup = [n for n, c in collections.Counter(names).items() if c > 1]
    if dup:
        raise ValueError(f"duplicate design names: {dup}")
    return ds


# Designs a recognizer threshold was FITTED to. They are training data whatever the hash split
# says, so splits() forces them into "train" and no holdout figure may be quoted with them in it
# (review[2] issue 1; changes.jsonl C35). A design merely MEASURED on (a run whose outcome was
# reported, without a value being chosen from it) does not belong here; C35 lists those separately.
FITTED_ON = {
    "fsm_timer_ar": "RELOAD_DISTINCT = 4 was set when this design's constant presets were reported "
                    "as a load (changes.jsonl PC02)",
}

# Designs removed from the corpus, with the reason (kept here so the record survives the build).
DROPPED = {
    "crc12_d16_ar": "the same CRC-12 (poly 0x80F, 16 data bits, Galois, init 0) as the held-out "
                    "regression set's crc12_d16_ar, so it was training data on both sides "
                    "(changes.jsonl C25, C36; review[2] issue 6)",
}


def splits(ds):
    """{name: "train" | "holdout"}: per (cohort, family), sorted by sha256(name), the first (n + 1) // 4
    held out, except that every FITTED_ON design is forced into "train". Grouping by cohort keeps
    every cohort-1 design in the split it had before cohort 2 was added (a design used for
    development never becomes held out, and vice versa); forcing a fitted design into train does
    not move any other design, so every other split is the one figures were quoted from, and a
    family whose only holdout design was fitted on simply contributes none."""
    fam = collections.defaultdict(list)
    for x in ds:
        fam[(x.cohort, x.family)].append(x.name)
    out = {}
    for f, names in fam.items():
        names = sorted(names, key=lambda n: hashlib.sha256(n.encode()).hexdigest())
        k = (len(names) + 1) // 4
        for i, n in enumerate(names):
            out[n] = "holdout" if i < k else "train"
    for n in FITTED_ON:
        if n in out:
            out[n] = "train"
    return out


# ----------------------------------------------------------------------------------------------
# synthesis


def yosys_script(rtl, lib, work):
    L = LIBS[lib]
    return "\n".join([
        f"read_verilog -sv {rtl}",
        "hierarchy -check -top top",
        "synth -flatten -top top",
        "delete t:$scopeinfo",
        "rename -wire t:$_*DFF*",
        f"write_json {work}/gen.json",
        f"dfflibmap -liberty {L['liberty']}",
        f"write_json {work}/dff.json",
        f"abc -liberty {L['liberty']}",
        "setundef -zero",
        f"hilomap {L['hilo']}",
        "opt_clean",
        f"write_json {work}/mapped.json",
        f"write_verilog -noattr -noexpr {work}/named.v",
    ]) + "\n"


def yosys_version():
    try:
        return subprocess.run([YOSYS, "-V"], capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"unavailable: {e}"


def run_yosys(rtl_path, lib, work):
    os.makedirs(work, exist_ok=True)
    script = os.path.join(work, "flow.ys")
    with open(script, "w") as f:
        f.write(yosys_script(rtl_path, lib, work))
    log = os.path.join(work, "yosys.log")
    env = dict(os.environ, TMPDIR=work)
    p = subprocess.run([YOSYS, "-q", "-l", log, "-s", script], capture_output=True, text=True, env=env, timeout=600)
    if p.returncode != 0:
        tail = open(log).read()[-3000:] if os.path.exists(log) else p.stderr[-3000:]
        raise RuntimeError(f"yosys failed ({lib}): {tail}")
    out = {}
    for k in ("gen", "dff", "mapped"):
        with open(os.path.join(work, f"{k}.json")) as f:
            out[k] = json.load(f)["modules"]["top"]
    with open(os.path.join(work, "named.v")) as f:
        out["named_v"] = f.read()
    return out


_LIBRARY = {}


def library(lib):
    if lib not in _LIBRARY:
        _LIBRARY[lib] = Library(LIBS[lib]["liberty"])
    return _LIBRARY[lib]


_BIT = re.compile(r"^(.*)\[(\d+)\]$")


def _split_bit(name):
    m = _BIT.match(name)
    return (m.group(1), int(m.group(2))) if m else (name, None)


def _reg_index(r):
    """RTL (vector, index) of each bit of a non-flex register; index None for a scalar."""
    if r.rtl_bits is None and r.rtl is None and r.width == 1:
        return [(r.name, None)]
    idx = r.rtl_bits if r.rtl_bits is not None else range(r.width)
    return [(r.vec, i) for i in idx]


def map_flops(design, gen):
    """{Yosys flop cell name: [(register, bit index, (netname, position) of its Q), ...]} from the
    generic netlist, the register the cell is named after first. Several entries mean synthesis
    merged equivalent flops (opt_merge): the flop holds a bit of each register. Flex registers take
    their width from the flops found."""
    spec, flex = {}, {r.vec: r for r in design.regs if r.flex}
    for r in design.regs:
        if not r.flex:
            for i, (v, ri) in enumerate(_reg_index(r)):
                spec[(v, ri)] = (r.name, i)
    alias = collections.defaultdict(list)
    for n, info in gen["netnames"].items():
        if info.get("hide_name"):
            continue
        off = info.get("offset", 0)
        for p, b in enumerate(info["bits"]):
            if isinstance(b, int):
                alias[b].append((n, p + off, len(info["bits"])))
    found, flex_found, bad = {}, collections.defaultdict(list), []
    for cn, c in gen["cells"].items():
        t = c["type"]
        if "DLATCH" in t or "SR_" in t:
            bad.append(f"latch-like cell {cn} ({t})")
            continue
        if "DFF" not in t:
            continue
        q = c["connections"]["Q"][0]
        cands = []
        if not cn.startswith("$"):
            v, i = _split_bit(cn.split("$", 1)[0])
            cands.append((v, i, None))
        for n, p, w in alias.get(q, []):
            cands.append((n, p, (n, p)))
            if w == 1:
                cands.append((n, None, (n, p)))
        hits, seen = [], set()
        for v, i, src in cands:
            if (v, i) in spec and spec[(v, i)] not in seen:
                seen.add(spec[(v, i)])
                hits.append(spec[(v, i)] + (src or _alias_of(alias, q, v, i),))
            elif v in flex and i is not None and not hits:
                flex_found[v].append((i, cn, src or _alias_of(alias, q, v, i)))
                hits = None
                break
        if hits == []:
            bad.append(f"flop {cn} matches no register ({[c_[:2] for c_ in cands]})")
        elif hits:
            found[cn] = hits
    for v, lst in flex_found.items():
        r = flex[v]
        for bi, (i, cn, src) in enumerate(sorted(lst)):
            found[cn] = [(r.name, bi, src)]
    return found, {flex[v].name: len(lst) for v, lst in flex_found.items()}, bad


def _alias_of(alias, q, v, i):
    for n, p, w in alias.get(q, []):
        if n == v and (p == i or (i is None and w == 1)):
            return (n, p)
    return None


def polarity(dff, cell, src):
    """True when the mapped flop stores the complement of the RTL bit (found through dfflibmap's
    inverters), False when it stores the bit, None when neither holds."""
    if src is None or src[0] not in dff["netnames"]:
        return None
    info = dff["netnames"][src[0]]
    rb = info["bits"][src[1] - info.get("offset", 0)]
    conns = dff["cells"][cell]["connections"]
    q, qn = (conns.get("Q") or [None])[0], (conns.get("Q_N") or [None])[0]
    if q == rb:
        return False
    if qn == rb:
        return True
    for c in dff["cells"].values():
        if c["type"] == "$_NOT_" and c["connections"]["Y"][0] == rb:
            a = c["connections"]["A"][0]
            if a == q:
                return True
            if a == qn:
                return False
    return None


def write_stripped(mapped, path, seed_text, header):
    """Write the mapped netlist with ports named and every cell and internal net renamed _<n>_ in a
    seeded shuffled order. Returns {stripped cell name: Yosys cell name}."""
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], "big"))
    ports = mapped["ports"]
    names, assigns, decl = {}, [], []
    for p, info in ports.items():
        if not re.fullmatch(r"[A-Za-z_]\w*", p) or info.get("offset", 0) or info.get("upto"):
            raise ValueError(f"port {p}: unsupported name or range")
        w = len(info["bits"])
        decl.append(f"  {info['direction']} {'' if w == 1 else f'[{w - 1}:0] '}{p};")
    for phase in ("input", "inout", "output"):
        for p, info in ports.items():
            if info["direction"] != phase:
                continue
            w = len(info["bits"])
            for i, b in enumerate(info["bits"]):
                nm = p if w == 1 else f"{p}[{i}]"
                if isinstance(b, str):
                    assigns.append((nm, f"1'b{'1' if b == '1' else '0'}"))
                elif b in names:
                    assigns.append((nm, names[b]))
                else:
                    names[b] = nm
    cells = list(mapped["cells"].items())
    internal = sorted({b for _n, c in cells for bs in c["connections"].values() for b in bs
                       if isinstance(b, int) and b not in names})
    objs = [("cell", n) for n, _c in cells] + [("net", b) for b in internal]
    rng.shuffle(objs)
    cell_name = {}
    for k, (kind, x) in enumerate(objs):
        if kind == "net":
            names[x] = f"_{k}_"
        else:
            cell_name[x] = f"_{k}_"
    lines = [f"/* {header} */", "module top(" + ", ".join(ports) + ");"] + decl
    lines += [f"  wire {names[b]};" for b in sorted(internal, key=lambda b: int(names[b][1:-1]))]
    for n, c in sorted(cells, key=lambda nc: int(cell_name[nc[0]][1:-1])):
        pins = []
        for pn, bs in sorted(c["connections"].items()):
            if len(bs) != 1:
                raise ValueError(f"cell {n} pin {pn}: {len(bs)} bits")
            b = bs[0]
            pins.append(f"    .{pn}({names[b] if isinstance(b, int) else ('1' + chr(39) + 'b' + ('1' if b == '1' else '0'))})")
        lines.append(f"  {c['type']} {cell_name[n]} (\n" + ",\n".join(pins) + "\n  );")
    lines += [f"  assign {a} = {b};" for a, b in assigns]
    lines.append("endmodule")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return {v: k for k, v in cell_name.items()}


# ----------------------------------------------------------------------------------------------
# checks on a synthesised netlist

_SH = np.arange(64, dtype=np.uint64)
_ALL1 = np.uint64(0xFFFFFFFFFFFFFFFF)
WIDE = 62      # registers wider than this are handled as Python ints (object arrays), not int64


def _unpack(rows):
    rows = np.asarray(rows, dtype=np.uint64)
    return ((rows[:, :, None] >> _SH) & np.uint64(1)).reshape(rows.shape[0], -1).astype(np.int64)


def _pack(bits):
    b = np.asarray(bits, dtype=np.uint64).reshape(-1, 64)
    return np.bitwise_or.reduce(b << _SH, axis=1)


class Bench:
    """One library's stripped netlist of one design, loaded with netlist.load_verilog, for checks."""

    def __init__(self, path, lib, regs_jk, vecs_jk, inv, jk_of):
        nl, key = load_verilog(path, library(lib), seed=None)
        self.nl, self.key = nl, key
        self.g = g = GateGraph(nl)
        self.sim = Sim(g, words=LANES_W)
        self.L = 64 * LANES_W
        self.q, self.ns = {}, {}
        for f in g.flops:
            jk = jk_of[key.cell_name[f.cell]]
            self.q[jk], self.ns[jk] = f.q, f.ns
        self.inv = inv
        ins = set(nl.inputs)
        self.ports = collections.defaultdict(list)
        self.pinsig = {}
        for pb, net in key.ports.items():
            if net in ins and net in g.lit_of_net:
                self.pinsig[pb] = g.lit_of_net[net] >> 1
                p, i = _split_bit(pb)
                self.ports[p].append((0 if i is None else i, pb))
        self.regs = dict(regs_jk)          # register -> [jk by bit index]
        for v, lst in vecs_jk.items():     # RTL vector -> [jk by RTL index]
            self.regs.setdefault(v, lst)

    def fresh(self, rng, inputs, domain):
        V = self.sim.zeros()
        self.sim.random_sources(V, rng)
        for p, val in inputs.items():
            if p not in self.ports:
                raise KeyError(f"no input port {p!r}")
            for i, pb in self.ports[p]:
                V[self.pinsig[pb]] = _ALL1 if (int(val) >> i) & 1 else np.uint64(0)
        for r, dom in (domain or {}).items():
            if isinstance(dom, range) and dom.step == 1:
                vals = rng.integers(dom.start, dom.stop, self.L, dtype=np.int64)
            else:
                vals = rng.choice(np.asarray(list(dom), dtype=np.int64), self.L)
            self.set(V, self.regs[r], vals)
        return V

    def set(self, V, jks, vals):
        for k, jk in enumerate(jks):
            V[self.q[jk]] = _pack(((vals >> k) & 1) ^ int(self.inv[jk]))

    def get(self, V, jks, which="q"):
        """Register values per lane (int64; Python ints in an object array above WIDE bits)."""
        rows = V[[self.q[j] for j in jks]] if which == "q" else Sim.lits(V, [self.ns[j] for j in jks])
        bits = _unpack(rows) ^ np.array([int(self.inv[j]) for j in jks], dtype=np.int64)[:, None]
        if len(jks) > WIDE:
            return (bits.astype(object) * np.array([1 << k for k in range(len(jks))], dtype=object)[:, None]).sum(axis=0)
        return (bits << np.arange(len(jks), dtype=np.int64)[:, None]).sum(axis=0)

    def port(self, V, p):
        rows = V[[self.pinsig[pb] for _i, pb in sorted(self.ports[p])]]
        idx = np.array([i for i, _pb in sorted(self.ports[p])], dtype=np.int64)[:, None]
        return (_unpack(rows) << idx).sum(axis=0)

    def source(self, V, src, I, S=None):
        """Value per lane of a stage-0 source: "port:<pin>", a join key, ("const", v), an OwnHead
        (logic over the design's registers) or a callable of the inputs."""
        if isinstance(src, OwnHead):
            return np.asarray(src.fn(S, I), dtype=np.int64) & 1
        if callable(src):
            return np.asarray(src(I), dtype=np.int64) & 1
        if isinstance(src, tuple) and src[0] == "const":
            return np.full(self.L, src[1], dtype=np.int64)
        if isinstance(src, str) and src.startswith("port:"):
            pb = src[5:]
            return _unpack(V[[self.pinsig[pb]]])[0]
        return self.get(V, [src])

    # --- checks ---------------------------------------------------------------------------------
    def model(self, chk, quiet, rng):
        V = self.fresh(rng, dict(quiet, **chk.inputs), chk.domain)
        self.sim.eval(V)
        S = {n: self.get(V, j) for n, j in self.regs.items()}
        I = {p: self.port(V, p) for p in self.ports}
        exp = chk.fn(S, I)
        res, ok = {}, True
        for n, e in sorted(exp.items()):
            mask = None
            if isinstance(e, tuple):
                e, mask = e
            j = self.regs[n]
            act = self.get(V, j, "ns")
            e = np.broadcast_to(np.asarray(e, dtype=object if len(j) > WIDE else np.int64), act.shape) & \
                ((1 << len(j)) - 1)
            bad = act != e
            if mask is not None:
                bad &= np.asarray(mask, dtype=bool)
            res[n] = {"mismatches": int(bad.sum()), "changed_lanes": int((act != S[n]).sum())}
            ok &= not bad.any()
        return {"check": chk.name, "method": "model", "lanes": self.L, "inputs": dict(quiet, **chk.inputs),
                "domain": _dom_summary(chk.domain), "registers": res, "ok": bool(ok)}

    def counter(self, params, when, sign, quiet, rng):
        bo = params["bit_order"]
        V = self.fresh(rng, dict(quiet, **when.get("inputs", {})), when.get("domain"))
        self.sim.eval(V)
        v, n = self.get(V, bo), self.get(V, bo, "ns")
        mod = params["modulus"] if isinstance(params["modulus"], int) else 1 << len(bo)
        exp = (v + sign * (params.get("step") or 1)) % mod
        bad = int((n != exp).sum())
        return {"method": f"counter {'+' if sign > 0 else '-'}{params.get('step') or 1} mod {mod} on bit_order",
                "lanes": self.L, "inputs": dict(quiet, **when.get("inputs", {})),
                "domain": _dom_summary(when.get("domain")), "mismatches": bad, "ok": bad == 0}

    def chain(self, order, heads, inv0, when, quiet, rng):
        V = self.fresh(rng, dict(quiet, **(when or {}).get("inputs", {})), (when or {}).get("domain"))
        self.sim.eval(V)
        I = {p: self.port(V, p) for p in self.ports}
        S = {n: self.get(V, j) for n, j in self.regs.items()} if any(isinstance(x, OwnHead) for x in heads or []) \
            else None
        bad, n = 0, 0
        for li, lane in enumerate(order):
            for k, jk in enumerate(lane):
                if k == 0:
                    if heads is None or heads[li] is None:
                        continue
                    exp = self.source(V, heads[li], I, S) ^ int(bool(inv0 and inv0[li]))
                else:
                    exp = self.get(V, [lane[k - 1]])
                bad += int((self.get(V, [jk], "ns") != exp).sum())
                n += 1
        return {"method": "stage k takes stage k-1 (stage 0 its serial input)", "lanes": self.L, "stage_checks": n,
                "inputs": dict(quiet, **(when or {}).get("inputs", {})), "domain": _dom_summary((when or {}).get("domain")),
                "mismatches": bad, "ok": bad == 0 and n > 0}

    def affine(self, bo, when, quiet, rng):
        V0 = self.fresh(rng, dict(quiet, **when.get("inputs", {})), when.get("domain"))
        w = len(bo)
        a, b, c = (rng.integers(0, 1 << w, self.L, dtype=np.int64) for _ in range(3))
        outs = []
        for s in (a, b, c, a ^ b ^ c):
            V = V0.copy()
            self.set(V, bo, s)
            self.sim.eval(V)
            outs.append(self.get(V, bo, "ns"))
        bad = int(((outs[0] ^ outs[1] ^ outs[2]) != outs[3]).sum())
        changed = int((outs[0] != a).sum())
        return {"method": "GF(2)-affine in its own bits: n(a)^n(b)^n(c) == n(a^b^c), everything else fixed",
                "lanes": self.L, "inputs": dict(quiet, **when.get("inputs", {})), "mismatches": bad,
                "changed_lanes": changed, "ok": bad == 0 and changed > 0}


def _dom_summary(dom):
    if not dom:
        return {}
    out = {}
    for r, vals in dom.items():
        if isinstance(vals, range) and vals.step == 1 and len(vals) > 8:
            out[r] = {"min": vals.start, "max": vals.stop - 1, "count": len(vals)}
            continue
        vals = sorted(set(int(x) for x in vals))
        out[r] = vals if len(vals) <= 8 else {"min": vals[0], "max": vals[-1], "count": len(vals)}
    return out


def counter_orders(step, w):
    """(bit permutation, polarity mask, direction) triples under which `step` is +1 or -1 modulo 2^w
    on every state it changes (exhaustive; a counter has at least one). Up to 6 bits by brute force
    over all w! x 2^w orders; above, by an exact depth-first search over weight positions: position
    i must be a bit that flips exactly on the changing states where every lower position carries
    (all mapped 1 for +1, all 0 for -1), and its polarity decides where the carry continues."""
    st = np.arange(1 << w, dtype=np.int64)
    nx = step(st) & ((1 << w) - 1)
    ch = nx != st
    if w > 6:
        flips = [(((st ^ nx) >> b) & 1).astype(bool)[ch] for b in range(w)]
        vals = [((st >> b) & 1).astype(bool)[ch] for b in range(w)]
        count = [0]

        def dfs(i, used, M, dd):
            if i == w:
                count[0] += 1
                return
            for b in range(w):
                if b in used or not np.array_equal(flips[b], M):
                    continue
                for pol in (False, True):
                    before = vals[b] ^ pol                  # the mapped bit before the step
                    dfs(i + 1, used | {b}, M & (before if dd > 0 else ~before), dd)
        for dd in (1, -1):
            dfs(0, frozenset(), np.ones(int(ch.sum()), dtype=bool), dd)
        return count[0]
    found = 0
    for perm in itertools.permutations(range(w)):
        for pol in range(1 << w):
            def mp(x, perm=perm, pol=pol):
                y = x ^ pol
                return sum(((y >> perm[i]) & 1) << i for i in range(w))
            a, b = mp(st), mp(nx)
            for dd in (1, -1):
                if np.all(((a + dd) % (1 << w) == b)[ch]):
                    found += 1
    return found


def minpoly(step, w, start):
    """Minimal polynomial (bit i = coefficient of x^i) of the Krylov sequence of `start` under the
    GF(2)-linear map `step` on w-bit ints."""
    piv = {}
    cur = start
    for i in range(w + 1):
        x, comb = cur, 1 << i
        while x:
            p = x.bit_length() - 1
            if p not in piv:
                break
            vx, vc = piv[p]
            x ^= vx
            comb ^= vc
        if x == 0:
            return comb
        piv[x.bit_length() - 1] = (x, comb)
        cur = int(step(cur))
    raise AssertionError("no dependency within w + 1 steps")


def charpoly(step, w):
    for start in [1, 1 << (w - 1)] + [1 << i for i in range(1, w - 1)]:
        m = minpoly(step, w, start)
        if m.bit_length() - 1 == w:
            return m
    return None


def _reciprocal(p):
    w = p.bit_length()
    return int(format(p, f"0{w}b")[::-1], 2)


def matrix_form(step, w):
    """The one-step GF(2) matrix's shape (inputs 0): rows / columns with more than one 1 ("tap" rows
    and columns) and its class: permutation (a shift or rotation), both (one tap row and one tap
    column: Fibonacci and Galois coincide, as for a trinomial), fibonacci (one tap row), galois (one
    tap column) or affine (neither: not a one-step companion matrix)."""
    cols = [int(step(1 << j, 0)) & ((1 << w) - 1) for j in range(w)]
    rows = [sum((c >> i) & 1 for c in cols) for i in range(w)]
    tr = sum(r > 1 for r in rows)
    tc = sum(bin(c).count("1") > 1 for c in cols)
    cls = ("permutation" if tr == 0 and tc == 0 else "both" if tr == 1 and tc == 1 else
           "fibonacci" if tr == 1 else "galois" if tc == 1 else "affine")
    return {"tap_rows": tr, "tap_columns": tc, "unit_rows": sum(r == 1 for r in rows),
            "unit_columns": sum(bin(c).count("1") == 1 for c in cols), "class": cls}


def lfsr_facts(step, w, stated, form=None):
    cp = charpoly(lambda s: step(s, 0), w)
    out = {"method": "characteristic polynomial of the model's one-step GF(2) map (inputs 0), by a Krylov "
                     "sequence", "charpoly": None if cp is None else hex(cp)}
    if isinstance(stated, int):
        out["matches"] = "stated" if cp == stated else "reciprocal" if cp == _reciprocal(stated) else "no"
        out["ok"] = out["matches"] != "no"
    elif form == "affine":
        out["ok"] = True          # no polynomial is stated; the matrix class below decides
    else:
        out["ok"] = cp is not None
    if form in ("fibonacci", "galois", "both", "affine"):
        mf = matrix_form(step, w)
        out["one_step_matrix"] = dict(mf, stated_form=form, ok=mf["class"] == form)
        out["ok"] = out["ok"] and mf["class"] == form
    if cp is not None and w <= 20:
        s, n = 1, 0
        while True:
            s = int(step(s, 0))
            n += 1
            if s == 1 or n > (1 << w):
                break
        out["period_from_1"] = n if s == 1 else None
        out["primitive"] = n == (1 << w) - 1
    return out


# ----------------------------------------------------------------------------------------------
# proof claims: the truth's params restated as schema.py "Proof claims" and verified by
# tools/s3/verify.py (the harness's own checker) on each library's netlist, for every state the
# defining condition admits (SAT, not sampling). Stored symbolically in claims.json:
#   EXPR leaves {"q": join key} (the flop's stored value), {"port": pin bit}, {"const": 0|1};
#   COND conjuncts {"q": join key, "value"} (the flop's Q net) and {"port": pin bit, "value"}.
# reference_result() turns them into opaque ids for any loaded copy of the netlist.

CLAIMS_SCHEMA = "retrace-s3-corpus-claims/1"
CLAIM_METHODS = {
    "counter": "per bit: the flop's next state equals bit k of (v + K) mod 2^w over the truth's bit_order, "
               "K = the step (or step - modulus on the wrapping states), under the defining condition split "
               "into disjoint cubes (a mod-M domain [0, M) is a cube cover, so no invariant is needed)",
    "chain": "per stage: stage k's next state equals stage k-1 (stage 0: its serial input, or its complement "
             "for a Johnson counter) under the defining condition",
    "affine": "per bit: the flop's next state equals the XOR of the variables (flop states, input pins) whose "
              "unit flip changes the generator's RTL model, plus the model's constant, after the model was "
              "found GF(2)-affine on 256 random states; the polynomial check ties the model to params.poly",
}


def _c(v):
    return {"const": int(v)}


def _is_c(e):
    return "const" in e


def e_not(e):
    if _is_c(e):
        return _c(1 - e["const"])
    if "not" in e:
        return e["not"]
    return {"not": e}


def _nary(op, xs, absorb, unit):
    out = []
    for x in xs:
        if _is_c(x):
            if x["const"] == absorb:
                return _c(absorb)
            continue
        out.extend(x[op] if op in x else [x])
    if not out:
        return _c(unit)
    return out[0] if len(out) == 1 else {op: out}


def e_and(xs):
    return _nary("and", xs, 0, 1)


def e_or(xs):
    return _nary("or", xs, 1, 0)


def e_xor(xs):
    p, out = 0, []
    for x in xs:
        if _is_c(x):
            p ^= x["const"]
        else:
            out.extend(x["xor"] if "xor" in x else [x])
    if not out:
        return _c(p)
    e = out[0] if len(out) == 1 else {"xor": out}
    return e_not(e) if p else e


def e_add_const(xs, K):
    """EXPRs of the bits of (x + K) mod 2^w, x given LSB first as EXPRs of its RTL bits."""
    w = len(xs)
    K %= 1 << w
    if K == 0:
        return list(xs)
    if K == 1:       # increment: bit k flips when every lower bit is 1
        return [e_xor([x, e_and(xs[:k])]) for k, x in enumerate(xs)]
    if K == (1 << w) - 1:   # decrement: bit k flips when every lower bit is 0
        return [e_xor([x, e_and([e_not(y) for y in xs[:k]])]) for k, x in enumerate(xs)]
    out, carry = [], _c(0)
    for k, x in enumerate(xs):
        kb = (K >> k) & 1
        out.append(e_xor([x, _c(kb), carry]))
        carry = e_or([x, carry]) if kb else e_and([x, carry])
    return out


def range_cubes(lo, hi, n):
    """Disjoint cubes covering the interval [lo, hi) of n-bit values: aligned power-of-two blocks."""
    if lo < 0 or hi > 1 << n:
        raise ValueError(f"domain value outside {n} bits")
    out = []
    while lo < hi:
        size = (lo & -lo) if lo else 1 << n
        while size > hi - lo:
            size >>= 1
        b = size.bit_length() - 1
        out.append({i: (lo >> i) & 1 for i in range(b, n)})
        lo += size
    return out


def cube_cover(values, n):
    """Disjoint cubes ({bit position: value} over bits 0..n-1) whose union is exactly `values` (a
    range above 2^16 values is covered by aligned blocks without listing it)."""
    if isinstance(values, range) and values.step == 1 and len(values) > 1 << 16:
        return range_cubes(values.start, values.stop, n)

    def rec(vs, b, pre):
        if not vs:
            return []
        if len(vs) == 1 << (b + 1):
            return [pre]
        lo = [v for v in vs if not (v >> b) & 1]
        hi = [v for v in vs if (v >> b) & 1]
        return rec(lo, b - 1, {**pre, b: 0}) + rec(hi, b - 1, {**pre, b: 1})
    vs = sorted({int(v) for v in values})
    if any(v < 0 or v >> n for v in vs):
        raise ValueError(f"domain value outside {n} bits")
    return rec(vs, n - 1, {})


def domain_cubes(domain, names):
    """The defining condition's register domain as disjoint cubes {join key: RTL bit}."""
    combos = [{}]
    for n, vals in (domain or {}).items():
        jks = names[n]
        opts = [{jks[b]: v for b, v in c.items()} for c in cube_cover(vals, len(jks))]
        combos = [{**base, **c} for base in combos for c in opts
                  if all(base.get(k, v) == v for k, v in c.items())]
    return combos


class Claimer:
    """Builds one library's symbolic claims for one design. names: register or RTL vector -> join
    keys by bit; ports: input port -> [(bit index, pin bit)]; inv: join key -> flop stores ~bit."""

    def __init__(self, names, ports, inv, quiet):
        self.names, self.ports, self.inv, self.quiet = names, ports, inv, quiet

    def rv(self, jk, fixed=None):
        """EXPR of the RTL value of a flop's bit (a constant when a cube fixes it)."""
        if fixed and jk in fixed:
            return _c(fixed[jk])
        return e_not({"q": jk}) if self.inv[jk] else {"q": jk}

    def port_fix(self, inputs):
        out = {}
        for p, val in dict(self.quiet, **(inputs or {})).items():
            for i, pb in self.ports[p]:
                out[pb] = (int(val) >> i) & 1
        return out

    def cond(self, pfix, cube):
        return ([{"port": pb, "value": v} for pb, v in sorted(pfix.items())] +
                [{"q": jk, "value": v ^ int(self.inv[jk])} for jk, v in sorted(cube.items())])

    def claim(self, jk, rtl_expr, cond, role="defining"):
        return {"type": "next", "flop": jk, "equals": e_xor([rtl_expr, _c(int(self.inv[jk]))]), "when": cond,
                "role": role}

    # --- per kind -----------------------------------------------------------------------------
    def counter(self, p, when, sign):
        bo = p["bit_order"]
        w = len(bo)
        full = 1 << w
        step = p.get("step") or 1
        M = p["modulus"] if isinstance(p.get("modulus"), int) else full
        pfix = self.port_fix(when.get("inputs"))
        out = []
        for cube in domain_cubes(when.get("domain"), self.names):
            own = {k: cube[jk] for k, jk in enumerate(bo) if jk in cube}
            if M == full:
                groups = {(sign * step) % full: [{}]}
            else:
                if w > 16:
                    raise ValueError("modulus below 2^w on more than 16 bits")
                free = [k for k in range(w) if k not in own]
                base = sum(v << k for k, v in own.items())
                by_k = collections.defaultdict(list)
                for i in range(1 << len(free)):
                    v = base | sum(((i >> j) & 1) << k for j, k in enumerate(free))
                    by_k[((v + sign * step) % M - v) % full].append(v)
                groups = {K: [{bo[b]: x for b, x in c.items()} for c in cube_cover(vs, w)] for K, vs in by_k.items()}
            for K, cubes in sorted(groups.items()):
                for sub in cubes:
                    fixed = {**cube, **sub}
                    s = e_add_const([self.rv(jk, fixed) for jk in bo], K)
                    cond = self.cond(pfix, fixed)
                    out += [self.claim(jk, s[k], cond) for k, jk in enumerate(bo)]
        return out

    def chain(self, order, heads, inv0, when, head_sym=None):
        when = when or {}
        pfix = self.port_fix(when.get("inputs"))
        out, skipped = [], 0
        for cube in domain_cubes(when.get("domain"), self.names):
            cond = self.cond(pfix, cube)
            for li, lane in enumerate(order):
                for k, jk in enumerate(lane):
                    if k:
                        e = self.rv(lane[k - 1], cube)
                    else:
                        src = heads[li] if heads is not None else None
                        if head_sym is not None:
                            e = head_sym[li]
                            if callable(e):
                                e = e(lambda n, i, cube=cube: self.rv(self.names[n][i], cube))
                        elif isinstance(src, tuple) and src[0] == "const":
                            e = _c(src[1])
                        elif isinstance(src, str) and src.startswith("port:"):
                            e = {"port": src[5:]}
                        elif isinstance(src, str):
                            e = self.rv(src, cube)
                        else:
                            skipped += 1
                            continue
                        if inv0 and inv0[li]:
                            e = e_not(e)
                    out.append(self.claim(jk, e, cond))
        return out, skipped

    def affine(self, fn, target, when, rng, quads=256):
        """Claims for the register bits `target` from the RTL model fn(S, I), when it is GF(2)-affine
        in every free variable (flop bits and input pins not fixed by the condition). Returns
        (claims, facts) or (None, reason)."""
        when = when or {}
        pfix = self.port_fix(when.get("inputs"))
        all_jk = sorted({jk for js in self.names.values() for jk in js})
        pbits = [pb for p in sorted(self.ports) for _i, pb in self.ports[p]]
        claims, data_bits = [], set()
        for cube in domain_cubes(when.get("domain"), self.names):
            var = [("q", jk) for jk in all_jk if jk not in cube] + [("port", pb) for pb in pbits if pb not in pfix]
            nv = len(var)
            X = np.zeros((1 + nv + 4 * quads, nv), dtype=np.int64)
            X[1 + np.arange(nv), np.arange(nv)] = 1
            a, b, c = (rng.integers(0, 2, (quads, nv), dtype=np.int64) for _ in range(3))
            X[1 + nv:] = np.concatenate([a, b, c, a ^ b ^ c])
            L = X.shape[0]
            val = {n: X[:, i] for i, (_t, n) in enumerate(var)}
            val.update({jk: np.full(L, v, dtype=np.int64) for jk, v in cube.items()})
            val.update({pb: np.full(L, v, dtype=np.int64) for pb, v in pfix.items()})
            S = {n: sum(val[jk] << k for k, jk in enumerate(js)) for n, js in self.names.items()}
            I = {p: sum(val[pb] << i for i, pb in lst) for p, lst in self.ports.items()}
            nxt = {}
            for n, e in fn(S, I).items():
                if isinstance(e, tuple) or n not in self.names:
                    continue
                e = np.broadcast_to(np.asarray(e, dtype=np.int64), (L,))
                for k, jk in enumerate(self.names[n]):
                    nxt[jk] = (e >> k) & 1
            if any(jk not in nxt for jk in target):
                return None, "the model does not give every bit's next state"
            N = np.stack([nxt[jk] for jk in target])            # (bits, lanes)
            n0, cols = N[:, 0], N[:, 1:1 + nv] ^ N[:, :1]
            q = [N[:, 1 + nv + i * quads:1 + nv + (i + 1) * quads] for i in range(4)]
            if np.any(q[0] ^ q[1] ^ q[2] ^ q[3]):
                return None, "the model is not GF(2)-affine under the condition"
            pred = (n0[:, None] ^ (cols @ X[1 + nv:1 + nv + quads].T) % 2)
            if np.any(pred != q[0]):
                return None, "the model is not reproduced by its affine form"
            cond = self.cond(pfix, cube)
            for k, jk in enumerate(target):
                leaves = [self.rv(n) if t == "q" else {"port": n} for (t, n), on in zip(var, cols[k]) if on]
                data_bits |= {n for (t, n), on in zip(var, cols[k]) if on and t == "port"}
                claims.append(self.claim(jk, e_xor(leaves + [_c(n0[k])]), cond))
        return claims, {"data_input_bits": len(data_bits)}


def opaque_claims(sym, cell_of, qnet_of, port_net):
    """Symbolic claims -> schema claims over the ids of one loaded netlist."""
    def ex(e):
        (op, a), = e.items()
        if op == "q":
            return {"q": cell_of[a]}
        if op == "port":
            return {"net": port_net[a]}
        if op == "const":
            return e
        if op == "not":
            return {"not": ex(a)}
        return {op: [ex(x) for x in a]}

    def cd(c):
        if "port" in c:
            return {"net": port_net[c["port"]], "value": c["value"]}
        net, ninv = qnet_of[c["q"]]
        return {"net": net, "value": c["value"] ^ ninv}
    return [{"type": "next", "flop": cell_of[c["flop"]], "equals": ex(c["equals"]),
             "when": [cd(x) for x in c["when"]], "role": c["role"]} for c in sym]


def id_maps(nl, key, g=None):
    """(cell_of, qnet_of, port_net) for a netlist whose Key names flops by join key (load())."""
    g = g or GateGraph(nl)
    nol = g.net_of_lit()
    cell_of, qnet_of = {}, {}
    for f in g.flops:
        jk = key.cell_name[f.cell]
        cell_of[jk] = f.cell
        qnet_of[jk] = nol[2 * f.q]
    return cell_of, qnet_of, dict(key.ports)


# ----------------------------------------------------------------------------------------------
# independent proof for claims the harness's SAT budget does not reach. A CDCL solver without XOR
# reasoning needs exponentially many conflicts to show two differently associated XOR trees equal
# (the word-parallel CRCs: every next-state bit is an XOR of 30-60 variables), so verify.py returns
# "unknown" there although the claims are true. A reduced ordered BDD represents any XOR of n
# variables in n nodes under every variable order, so equality of D and EXPR is decided exactly.
# This proves the corpus's truth; it does not make the harness verify the structure (that is
# recorded as "harness unknown").

_BDD_T = 1 << 30   # terminal level


@functools.lru_cache(maxsize=None)
def _tt_cof(tt, k, v):
    """Cofactor of a k-input table on its last input = v: a table over the first k - 1 inputs."""
    s = 1 << (k - 1)
    return (tt >> s) & ((1 << s) - 1) if v else tt & ((1 << s) - 1)


class Bdd:
    """A minimal ROBDD package: node 0 = false, 1 = true; ITE with unique and computed tables."""

    def __init__(self):
        self.nodes = [(_BDD_T, 0, 0), (_BDD_T, 1, 1)]
        self.unique, self.cache, self.level = {}, {}, {}

    def var(self, key):
        return self.mk(self.level.setdefault(key, len(self.level)), 0, 1)

    def mk(self, v, lo, hi):
        if lo == hi:
            return lo
        k = (v, lo, hi)
        n = self.unique.get(k)
        if n is None:
            n = self.unique[k] = len(self.nodes)
            self.nodes.append(k)
        return n

    def ite(self, f, g, h):
        if f == 1:
            return g
        if f == 0:
            return h
        if g == h:
            return g
        if g == 1 and h == 0:
            return f
        k = (f, g, h)
        r = self.cache.get(k)
        if r is None:
            v = min(self.nodes[f][0], self.nodes[g][0], self.nodes[h][0])
            c = [(n[1], n[2]) if n[0] == v else (x, x) for x, n in ((x, self.nodes[x]) for x in (f, g, h))]
            r = self.cache[k] = self.mk(v, self.ite(c[0][0], c[1][0], c[2][0]), self.ite(c[0][1], c[1][1], c[2][1]))
        return r

    def table(self, tt, k, ins):
        """The function of truth table tt (bit m = f(x), x_i = (m >> i) & 1) over BDDs ins."""
        if k == 0:
            return tt & 1
        return self.ite(ins[k - 1], self.table(_tt_cof(tt, k, 1), k - 1, ins), self.table(_tt_cof(tt, k, 0), k - 1, ins))


class BddProver:
    """Claims (opaque ids of one netlist, schema.py's claim language) decided with BDDs on a GateGraph
    of that netlist: a claim is proven when D xor EXPR is 0 on every assignment satisfying COND and
    COND is satisfiable. COND literals on sources (pins, flop states) are substituted as constants."""

    def __init__(self, nl):
        self.g = GateGraph(nl)
        self.flop_at = {f.cell: f for f in self.g.flops}
        self.B = Bdd()
        self.memo = {}

    def _lit(self, e):
        (op, a), = e.items()
        g = self.g
        if op == "q":
            return 2 * self.flop_at[a].q
        if op == "net":
            return g.resolve(a)
        if op == "const":
            return int(a)
        if op == "not":
            return self._lit(a) ^ 1
        tt = {"and": 0b1000, "or": 0b1110, "xor": 0b0110}[op]
        lits = [self._lit(x) for x in a]
        while len(lits) > 1:
            nxt = [g.mk(tt, [lits[i], lits[i + 1]]) for i in range(0, len(lits) - 1, 2)]
            lits = nxt + ([lits[-1]] if len(lits) % 2 else [])
        return lits[0]

    def bdd(self, lit, fixed):
        """BDD of a literal with the source signals in `fixed` set to constants."""
        memo = self.memo.setdefault(tuple(sorted(fixed.items())), {})
        g, B = self.g, self.B
        stack = [lit >> 1]
        while stack:
            s = stack[-1]
            if s in memo:
                stack.pop()
                continue
            if s in fixed:
                memo[s] = fixed[s]
            elif s == 0:
                memo[s] = 0
            elif g.tt[s] is None:           # a source: primary input, flop state, black-box output, free
                memo[s] = B.var(s)
            else:
                pend = [x for x in g.fanin[s] if x not in memo]
                if pend:
                    stack.extend(pend)
                    continue
                memo[s] = B.table(g.tt[s], len(g.fanin[s]), [memo[x] for x in g.fanin[s]])
            stack.pop()
        f = memo[lit >> 1]
        return B.ite(f, 0, 1) if lit & 1 else f

    def prove(self, c):
        g, B = self.g, self.B
        f = self.flop_at[c["flop"]]
        miter = g.mk(0b0110, [f.ns, self._lit(c["equals"])])
        fixed, rest = {}, []
        for x in c["when"]:
            lit = g.resolve(x["net"]) ^ (1 - x["value"])     # true when the conjunct holds
            s, want = lit >> 1, 1 - (lit & 1)
            if s == 0:
                if want != 0:
                    return "vacuous: COND is unsatisfiable"
                continue
            if g.tt[s] is None:
                if fixed.get(s, want) != want:
                    return "vacuous: COND is unsatisfiable"
                fixed[s] = want
            else:
                rest.append(lit)
        cond = 1
        for lit in rest:
            cond = B.ite(cond, self.bdd(lit, fixed), 0)
        if cond == 0:
            return "vacuous: COND is unsatisfiable"
        return "proven" if B.ite(cond, self.bdd(miter, fixed), 0) == 0 else "refuted"


# ----------------------------------------------------------------------------------------------
# build


def _resolve(v, jk_of):
    if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], int) and v[0] != "const":
        return jk_of[v]
    if isinstance(v, list):
        return [_resolve(x, jk_of) for x in v]
    if isinstance(v, dict):
        return {k: _resolve(x, jk_of) for k, x in v.items()}
    return v


def lanes_unordered(order, heads):
    """params.lanes_unordered by rule (TRUTH_CONVENTIONS): None for fewer than 2 lanes; else True
    when every lane head is an input pin (the lane order is then only the RTL bus index)."""
    if not order or len(order) < 2 or not isinstance(order[0], list):
        return None
    heads = heads if isinstance(heads, list) else None
    return bool(heads) and len(heads) == len(order) and all(isinstance(h, str) and h.startswith("port:") for h in heads)


def _flops_of_params(params):
    out = []
    for k in ("order", "bit_order"):
        v = params.get(k)
        if v:
            out += [f for lane in v for f in (lane if isinstance(lane, list) else [lane])]
    return out


def finish(design, outdir, syn, split, echo=print):
    """Post-process one design's two syntheses: map flops, write stripped netlists, check, write truth."""
    ddir = os.path.join(outdir, design.name)
    per_lib, problems = {}, []
    widths = {}
    for lib in [x for x in LIBS if x in syn]:   # fixed library order (threads finish in any order)
        s = syn[lib]
        found, flexw, bad = map_flops(design, s["gen"])
        problems += [f"{lib}: {b}" for b in bad]
        widths[lib] = flexw
        model_of = library(lib)
        flops_mapped = {n for n, c in s["mapped"]["cells"].items() if c["type"] in model_of and model_of[c["type"]].kind == "ff"}
        other_seq = {n: c["type"] for n, c in s["mapped"]["cells"].items()
                     if c["type"] in model_of and model_of[c["type"]].kind in ("latch", "icg", "unknown")}
        unknown = {c["type"] for c in s["mapped"]["cells"].values() if c["type"] not in model_of}
        if other_seq or unknown:
            problems.append(f"{lib}: unexpected cells {sorted(set(other_seq.values()) | unknown)}")
        if set(found) != flops_mapped:
            problems.append(f"{lib}: labelled flops {len(found)} != mapped flops {len(flops_mapped)} "
                            f"({sorted(set(found) ^ flops_mapped)[:4]})")
        inv = {}
        for cn, hits in found.items():
            ps = [polarity(s["dff"], cn, src) for _r, _i, src in hits]
            if ps[0] is None or any(p != ps[0] for p in ps):
                problems.append(f"{lib}: no single polarity for {cn}: {ps}")
            inv[cn] = bool(ps[0])
        path = os.path.join(ddir, f"{lib}.v")
        strip = write_stripped(s["mapped"], path, f"{design.name}/{lib}",
                               f"RETRACE S3 synthetic corpus: {design.name} ({lib}); names stripped by tools/s3/corpus.py")
        with open(os.path.join(ddir, f"{lib}.named.v"), "w") as f:
            f.write(s["named_v"])
        per_lib[lib] = {"found": found, "inv": inv, "strip": strip, "path": path,
                        "masters": {cn: s["mapped"]["cells"][cn]["type"] for cn in found if cn in s["mapped"]["cells"]},
                        "cells": len(s["mapped"]["cells"]), "flops": len(flops_mapped)}
    libs = list(per_lib)
    keys = [set(per_lib[lib]["found"]) for lib in libs]
    if any(k != keys[0] for k in keys):
        problems.append(f"join keys differ between libraries: {sorted(keys[0] ^ keys[-1])[:4]}")
    if widths and any(widths[lib] != widths[libs[0]] for lib in libs):
        problems.append(f"FSM widths differ between libraries: {widths}")
    ref = per_lib[libs[0]]["found"]
    # register -> [jk by bit index]
    jk_of, regs_jk = {}, collections.defaultdict(dict)
    for cn, hits in ref.items():
        for r, i, _src in hits:
            jk_of[(r, i)] = cn
            regs_jk[r][i] = cn
    reg_w = {}
    for r in design.regs:
        n = len(regs_jk.get(r.name, {}))
        reg_w[r.name] = n
        if not r.flex and n != r.width:
            problems.append(f"register {r.name}: {n} of {r.width} bits have a flop")
    regs_list = {r: [m[i] for i in sorted(m)] for r, m in regs_jk.items()}
    vecs = collections.defaultdict(dict)
    for r in design.regs:
        if r.flex:
            continue
        for i, (v, ri) in enumerate(_reg_index(r)):
            if (r.name, i) in jk_of:
                vecs[v][0 if ri is None else ri] = jk_of[(r.name, i)]
    vecs_list = {v: [m[i] for i in sorted(m)] for v, m in vecs.items() if sorted(m) == list(range(len(m)))}
    flex_changed = any(r.flex and reg_w[r.name] != r.width for r in design.regs)
    # checks per library
    reg_by = {r.name: r for r in design.regs}
    resolved = {}
    for r in design.regs:
        p = dict(r.params)
        # the EFFECTIVE kind: a register checked as a counter (a 1-bit toggle, TOGGLE_RULE) needs
        # bit_order for the params check and the claims even though its published kind is "flag"
        if (r.check_as or r.kind) in ("counter", "lfsr_crc") and "bit_order" not in p:
            p["bit_order"] = bits_of(r.name, range(reg_w[r.name]))
        try:
            resolved[r.name] = _resolve(p, jk_of)
        except KeyError as e:
            problems.append(f"register {r.name}: unresolved param reference {e}")
            resolved[r.name] = {}
        lu = lanes_unordered(p.get("order"), r.head if r.head is not None else p.get("serial_in"))
        if lu is not None:
            resolved[r.name]["lanes_unordered"] = lu
    checks = collections.defaultdict(dict)
    unit_checks = collections.defaultdict(dict)
    benches, claim_recs = {}, collections.defaultdict(dict)
    cdoc = {"schema": CLAIMS_SCHEMA, "design": design.name,
            "claim_language": "tools/s3/schema.py 'Proof claims' with symbolic leaves: EXPR {\"q\": join key} is the "
                              "flop's stored value, {\"port\": pin bit} an input pin; COND {\"q\": join key, \"value\"} "
                              "constrains the flop's Q, {\"port\", \"value\"} a pin. reference_result() maps them to "
                              "the opaque ids of a loaded netlist",
            "methods": CLAIM_METHODS, "v2_control": V2_CONTROL, "libs": {}}
    if not problems:
        for lib in libs:
            L = per_lib[lib]
            jk_of_stripped = {s_: cn for s_, cn in L["strip"].items()}
            inv_jk = L["inv"]
            try:
                b = Bench(L["path"], lib, regs_list, vecs_list, inv_jk, jk_of_stripped)
            except Exception as e:  # noqa: BLE001
                problems.append(f"{lib}: netlist does not load: {e!r}")
                continue
            notes = {k: v for k, v in b.g.notes.items() if k in ("combinational loop cuts", "undriven nets",
                                                                 "multi-driver nets", "latch cells", "unknown cells",
                                                                 "icg cells")}
            if notes:
                problems.append(f"{lib}: gate graph notes {notes}")
            per_lib[lib]["graph"] = {"flops": len(b.g.flops), "gates": len(b.g.gates()), "inputs": len(b.nl.inputs),
                                     "outputs": len(b.nl.outputs)}
            clash = sorted(set(b.key.ports) & RESULT_VOCAB)
            if clash:
                problems.append(f"{lib}: port names {clash} are result vocabulary (run.py's leak check would flag them)")
            seed0 = int.from_bytes(hashlib.sha256(f"{design.name}/{lib}".encode()).digest()[:8], "big")
            rng = np.random.default_rng(seed0)
            if flex_changed:
                checks["*"].setdefault(lib, []).append({"check": "model", "ok": True, "skipped":
                                                        "an FSM state register was re-encoded by synthesis"})
            else:
                for chk in design.checks:
                    res = b.model(chk, design.quiet, rng)
                    for n in res["registers"]:   # an RTL vector's result belongs to each register slicing it
                        for rn in {n} | {r.name for r in design.regs if r.vec == n}:
                            checks[rn].setdefault(lib, []).append(res)
                    if not res["ok"]:
                        problems.append(f"{lib}: model check {chk.name} failed: "
                                        f"{ {k: v for k, v in res['registers'].items() if v['mismatches']} }")
            for r in design.regs:
                kind = r.check_as or r.kind
                p = resolved[r.name]
                res = []
                if kind == "counter" and r.when is not None:
                    sign = -1 if p.get("direction") == "down" else 1
                    res.append(b.counter(p, r.when, sign, design.quiet, rng))
                    if r.when_down is not None:
                        res.append(b.counter(p, r.when_down, -1, design.quiet, rng))
                elif kind in ("shift_register", "synchronizer") and p.get("order"):
                    heads = _resolve(r.head, jk_of) if r.head is not None else p.get("serial_in")
                    res.append(b.chain(p["order"], heads, r.serial_inv, r.when, design.quiet, rng))
                elif kind == "lfsr_crc":
                    res.append(b.affine(p["bit_order"], r.when or {}, design.quiet, rng))
                for x in res:
                    checks[r.name].setdefault(lib, []).append(dict(x, check="params"))
                    if not x["ok"]:
                        problems.append(f"{lib}: params check of {r.name} failed: {x}")
            for u in design.units:
                up = u.get("params") or {}
                if u["kind"] in ("shift_register", "synchronizer") and up.get("order"):
                    x = b.chain(_resolve(up["order"], jk_of), _resolve(u.get("_head") or up.get("serial_in"), jk_of),
                                None, u.get("_when"), design.quiet, rng)
                elif u["kind"] == "counter" and up.get("bit_order") and u.get("_when") is not None:
                    x = b.counter(_resolve(up, jk_of), u["_when"], -1 if up.get("direction") == "down" else 1,
                                  design.quiet, rng)
                else:
                    continue
                unit_checks[u["name"]][lib] = dict(x, check="params")
                if not x["ok"]:
                    problems.append(f"{lib}: params check of unit {u['name']} failed")
            # proof claims, verified by the harness's checker (tools/s3/verify.py) on this netlist
            key_jk = Key([jk_of_stripped.get(n, n) for n in b.key.cell_name], b.key.net_name, b.key.ports,
                         b.key.position)
            benches[lib] = (b.nl, key_jk, b.g)
            cdoc["libs"][lib] = make_claims(design, b, key_jk, inv_jk, resolved, regs_list, jk_of, flex_changed,
                                            rng, claim_recs, problems, lib)
            try:
                cdoc["libs"][lib]["control"] = make_control(design, b, inv_jk, resolved, regs_list, rng)
            except Exception as e:  # noqa: BLE001
                problems.append(f"{lib}: v2 control failed to build: {e!r}")
                cdoc["libs"][lib]["control"] = {"registers": {}, "units": {}}
            per_lib[lib]["n_claims"] = cdoc["libs"][lib]["n_claims"]
    # design-level facts that do not depend on the library
    extra = collections.defaultdict(dict)
    for rn, w, step in design.counter_negatives:
        n = counter_orders(step, w)
        extra[rn]["no_counter_order"] = {"method": f"all {w}! bit orders x 2^{w} polarities x (+1, -1) on every "
                                                   "changing state (the generator's model)", "orders_found": n, "ok": n == 0}
        if n:
            problems.append(f"{rn}: {n} bit orders make the negative a counter")
    for rn, (w, step) in design.lfsr_models.items():
        facts = lfsr_facts(step, w, reg_by[rn].params.get("poly"), reg_by[rn].params.get("form"))
        extra[rn]["polynomial"] = facts
        if not facts["ok"]:
            problems.append(f"{rn}: model polynomial {facts['charpoly']} or one-step matrix "
                            f"{facts.get('one_step_matrix')} does not match the stated params")
    for rn, label, fn in design.facts:
        try:
            res = fn()
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "error": repr(e)}
        extra[rn][label] = res
        if not res.get("ok"):
            problems.append(f"{rn}: model fact {label} does not hold: {res}")
    for rn, rec in claim_recs.items():
        extra[rn]["claims_check"] = rec
    truth = make_truth(design, per_lib, ref, resolved, reg_w, checks, unit_checks, extra, split, jk_of)
    bad = schema.check_truth(truth)
    problems += [f"check_truth: {x}" for x in bad]
    # the reference result (every verified structure register, as a recognizer would report it) must
    # pass the harness's verify_result() on each library's netlist
    for lib, (nl, key_jk, g) in benches.items():
        refr, ref_names = _reference(truth, cdoc, lib, nl, key_jk, g)
        vr = s3verify.verify_result(nl, refr)
        rep = vr["summary"]
        indep = {n for grp in ("registers", "units") for n, c in cdoc["libs"][lib][grp].items()
                 if (c.get("independent_proof") or {}).get("proven")}
        unknown, inexpr, bad = [], [], []
        ctl_lib = cdoc["libs"][lib].get("control") or {"registers": {}, "units": {}}
        for srep, (name, ok, why) in zip(vr["structures"], ref_names):
            if srep["verified"]:
                if not ok:   # the conservative rule expected a self-condition, but v2 verifies it
                    rec_c = ctl_lib["registers"].get(name) or ctl_lib["units"].get(name)
                    rec_c.update(v2_expressible=True, why=None, rule_expected_inexpressible=why)
                continue
            if not ok:
                inexpr.append({"name": name, "why": why, "harness": srep["reason"]})
            elif _hold_refuted(srep):
                inexpr.append({"name": name, "why": HOLD_REFUTED, "harness": srep["reason"]})
                rec_c = ctl_lib["registers"].get(name) or ctl_lib["units"].get(name)
                if rec_c is not None:
                    rec_c.update(v2_expressible=False, why=HOLD_REFUTED)
            elif name in indep and srep.get("bucket") in ("unknown", "budget"):
                unknown.append(name)
            else:
                bad.append(f"{name} ({srep['reason']})")
        cdoc["libs"][lib]["reference"] = {
            "structures": rep["structures"], "verified": rep["verified"], "claims": rep["claims"],
            "reasons": rep["reasons"], "v2_inexpressible": inexpr,
            "harness_unknown_independently_proven": unknown,
            "structure_registers_without_claims": refr["meta"]["structure_registers_without_claims"]}
        per_lib[lib]["reference"] = cdoc["libs"][lib]["reference"]
        if bad:
            problems.append(f"{lib}: reference result: {rep['verified']}/{rep['structures']} structures verified "
                            f"(not verified: {'; '.join(bad)})")
    truth["meta"]["build_problems"] = problems
    truth["meta"]["checks_ok"] = not problems
    with open(os.path.join(ddir, "truth.json"), "w") as f:
        json.dump(truth, f, indent=1)
        f.write("\n")
    with open(os.path.join(ddir, "claims.json"), "w") as f:
        json.dump(cdoc, f, indent=1)
        f.write("\n")
    return truth, per_lib, problems


def _model_fn(design):
    for c in design.checks:
        if c.name == "model":
            return c.fn
    return design.checks[0].fn if design.checks else None


def make_claims(design, b, key_jk, inv, resolved, regs_list, jk_of, flex_changed, rng, recs, problems, lib):
    """One library's claims for every structure-kind register (and depth-2 shift) and every shift or
    synchronizer unit, each verified as a structure by verify.verify_structure on the Bench's netlist."""
    cl = Claimer(b.regs, b.ports, inv, design.quiet)
    ver = s3verify.Verifier(b.nl)
    maps = id_maps(b.nl, key_jk, b.g)
    out = {"registers": {}, "units": {}}
    prover = []

    def check(label, sym, jks, method, facts):
        opq = opaque_claims(sym, *maps)
        rep = s3verify.verify_structure(ver, {"id": label, "flops": [maps[0][j] for j in jks],
                                               "proof": {"claims": opq}}, [s3verify.CLAIMS_PER_RUN])
        rec = {"method": method, "claims": len(sym), "verified": rep["verified"], "reason": rep["reason"], **facts}
        if not rep["verified"] and "conflict limit" in rep["reason"]:
            # the harness's SAT budget ran out: decide the same claims exactly with BDDs
            if not prover:
                prover.append(BddProver(b.nl))
            verdicts = collections.Counter(prover[0].prove(c) for c in opq)
            defined = {c["flop"] for c in opq if c["role"] == "defining"}
            ok = verdicts == collections.Counter({"proven": len(opq)}) and all(maps[0][j] in defined for j in jks)
            rec["independent_proof"] = {"method": "ROBDD equivalence of D and EXPR under COND, every assignment "
                                                  "(tools/s3/corpus.py BddProver)", "claims": len(opq),
                                        "verdicts": dict(verdicts), "proven": ok}
            rec["harness"] = "unknown: the harness's conflict limit, not a refutation"
            if ok:
                return rec
        if not rep["verified"]:
            problems.append(f"{lib}: claims of {label} do not verify: {rep['reason']}")
        return rec

    for r in design.regs:
        kind = r.check_as or r.kind
        p = resolved[r.name]
        when = r.claim_when or r.when
        sym, method, facts = None, None, {}
        try:
            if kind == "counter" and r.when is not None:
                method = "counter"
                sym = cl.counter(p, when, -1 if p.get("direction") == "down" else 1)
                if r.when_down is not None:
                    sym += cl.counter(p, r.when_down, -1)
            elif kind in ("shift_register", "synchronizer") and p.get("order"):
                method = "chain"
                heads = _resolve(r.head, jk_of) if r.head is not None else p.get("serial_in")
                sym, skipped = cl.chain(p["order"], heads, r.serial_inv, when, r.head_sym)
                if skipped:
                    facts["stage0_without_claim"] = skipped
            elif kind == "lfsr_crc" and not flex_changed:
                method = "affine"
                sym, facts = cl.affine(_model_fn(design), p["bit_order"], when, rng)
                if sym is None:
                    problems.append(f"{lib}: no claims for {r.name}: {facts}")
                    facts = {"reason": facts}
                else:
                    want = (p.get("k_steps") * p.get("n_inputs")) if isinstance(p.get("k_steps"), int) and \
                        isinstance(p.get("n_inputs"), int) else None
                    facts["k_steps_x_n_inputs"] = want
                    if want is not None and want != facts["data_input_bits"]:
                        problems.append(f"{lib}: {r.name}: {facts['data_input_bits']} data bits enter per clock, "
                                        f"params say k_steps x n_inputs = {want}")
        except Exception as e:  # noqa: BLE001
            problems.append(f"{lib}: claims of {r.name} failed to build: {e!r}")
            continue
        if method is None:
            continue
        if not sym:
            recs[r.name][lib] = {"method": method, "claims": 0, "verified": False, **facts}
            continue
        rec = check(r.name, sym, regs_list[r.name], method, facts)
        recs[r.name][lib] = rec
        out["registers"][r.name] = dict(rec, claims=sym)
    for u in design.units:
        up = u.get("params") or {}
        if u["kind"] in ("shift_register", "synchronizer") and up.get("order"):
            order = _resolve(up["order"], jk_of)
            sym, _sk = cl.chain(order, _resolve(u.get("_head") or up.get("serial_in"), jk_of), None, u.get("_when"))
            rec = check(u["name"], sym, [j for lane in order for j in lane], "chain", {})
            out["units"][u["name"]] = dict(rec, claims=sym)
        elif u["kind"] == "counter" and up.get("bit_order") and u.get("_when") is not None:
            p = _resolve(up, jk_of)
            try:
                sym = cl.counter(p, u["_when"], -1 if p.get("direction") == "down" else 1)
            except Exception as e:  # noqa: BLE001
                problems.append(f"{lib}: claims of unit {u['name']} failed to build: {e!r}")
                continue
            rec = check(u["name"], sym, p["bit_order"], "counter", {})
            out["units"][u["name"]] = dict(rec, claims=sym)
    out["n_claims"] = sum(len(v["claims"]) for g in ("registers", "units") for v in out[g].values())
    return out


V2_CONTROL = ("the reference result's structure['control'] (schema.py 'Verification (v2, kind-bound)'): when = the "
              "quiet inputs and the defining case's inputs, plus the other registers of its domain fixed to one cube "
              "(the largest when the domain needs several: a sub-case, flagged subcase); the structure's own range is "
              "never a condition (the template carries a modulus or saturation top); counters add when_down (updown) "
              "and inverted (flops storing the complement); a synchronizer has no condition, so a synchronous reset "
              "becomes a control.reset case with its value read off the netlist -- as does the synchronous reset of a "
              "counter or shift register, since schema v2.1 (2026-09-23) makes control.reset a list of cases and "
              "hold mean 'outside every named case'; an lfsr_crc gives its XOR claims with "
              "control.inputs = the pins and other registers' outputs they read. A counter whose defining case needs "
              "its own value beyond its modulus / saturation range (reload or stop at terminal count or at a "
              "register) is not expressible without self-conditions (v2_expressible false)")


def make_control(design, b, inv, resolved, regs_list, rng):
    """Per structure register and shift/synchronizer unit: the v2 control, symbolic (COND conjuncts
    {"port"|"q", "value"}, join keys), with v2_expressible and the reason when it is not."""
    cl = Claimer(b.regs, b.ports, inv, design.quiet)
    g = b.g
    by = {r.name: r for r in design.regs}
    jk_of_q = {q: jk for jk, q in b.q.items()}
    fl_of = {jk_of_q[f.q]: f for f in g.flops}
    out = {"registers": {}, "units": {}}

    def quiet_split(jks):
        """The quiet inputs the structure's flops depend on that are not implied by their async
        controls: its synchronous resets."""
        asyncs = {a for j in jks for a in (fl_of[j].clear, fl_of[j].preset) if a}
        keep = {}
        for p, v in design.quiet.items():
            for i, pb in b.ports.get(p, []):
                lit = g.lit_of_net[b.key.ports[pb]]
                active = lit if not (int(v) >> i) & 1 else lit ^ 1      # true when this input resets
                if active not in asyncs and depends(pb, jks):
                    keep.setdefault(p, v)
        return keep

    def depends(pb, jks):
        """Does some flop's next state change when pin bit pb flips (everything else random, quiet)?"""
        V = b.fresh(rng, dict(design.quiet), None)
        b.sim.eval(V)
        before = Sim.lits(V, [b.ns[j] for j in jks]).copy()
        V[b.pinsig[pb]] ^= _ALL1
        b.sim.eval(V)
        return bool(np.any(Sim.lits(V, [b.ns[j] for j in jks]) != before))

    def reset_values(sync_in, jks):
        """The stored value of each flop after one clock with the synchronous resets active, or None."""
        act = {p: ((1 << len(b.ports[p])) - 1) ^ int(v) for p, v in sync_in.items()}
        V = b.fresh(rng, dict(design.quiet, **act), None)
        b.sim.eval(V)
        vals = {}
        for j in jks:
            bits = _unpack(Sim.lits(V, [b.ns[j]]))[0]
            if bits.min() != bits.max():
                return None
            vals[j] = int(bits[0])
        return vals

    def when_of(when, own_regs):
        """(COND: quiet and defining inputs, other registers fixed to their largest cube; whether that
        is a sub-case; the own-register range, which is never a condition)."""
        when = when or {}
        dom = when.get("domain") or {}
        cubes = domain_cubes({r: v for r, v in dom.items() if r not in own_regs}, cl.names)
        best = min(cubes, key=len) if cubes else None
        pf = cl.port_fix(dict(when.get("inputs") or {}))
        return (None if best is None else cl.cond(pf, best)), len(cubes) > 1, {r: v for r, v in dom.items()
                                                                               if r in own_regs}

    def counter_ok(p, own_dom, w):
        """Is the defining case expressible without the counter's own state (v2: no self-conditions)?
        Yes when every own-range restriction is exactly the template's range [0, modulus) (or the
        counter saturates: the template then carries the top)."""
        M, sat = p.get("modulus"), p.get("saturating")
        top = M if isinstance(M, int) else 1 << w
        for vals in own_dom:
            if vals is None or (sat is not None and sat is not False):   # saturating: the template's range
                continue
            if isinstance(vals, range):
                span = (vals.start, vals.stop) if vals.step == 1 else None
            else:
                vs = sorted({int(x) for x in vals})
                span = (vs[0], vs[-1] + 1) if vs and vs == list(range(vs[0], vs[-1] + 1)) else None
            if span != (0, top):
                return False
        return True

    def sync_reset(jks):
        """The synchronous-reset case of a flop set: (COND with the resets active, {flop: 0|1}), or
        None when there is no synchronous reset, or False when there is one but it stores no
        constant. Read off the netlist by simulation, exactly as the synchronizer branch always did."""
        sync_in = quiet_split(jks)
        if not sync_in:
            return None
        rv = reset_values(sync_in, jks)
        if rv is None:
            return False
        act = {p_: ((1 << len(b.ports[p_])) - 1) ^ int(v) for p_, v in sync_in.items()}
        return cl.cond({pb: (int(val) >> i) & 1 for p_, val in act.items()
                        for i, pb in b.ports[p_]}, {}), rv

    def one(kind, p, jks, own_regs, when, when_down=None, heads=None):
        rec = {"subcase": False, "v2_expressible": True, "why": None}
        if kind == "synchronizer":
            sr = sync_reset(jks)
            rec["when"] = []
            if sr is False:
                rec.update(v2_expressible=False, why="a synchronous reset without a constant reset value")
            elif sr:
                rec["reset"], rec["reset_value"] = sr
            rec["input"] = [h[5:] if isinstance(h, str) and h.startswith("port:") else None for h in (heads or [])]
            if not heads or any(x is None for x in rec["input"]):
                rec.update(v2_expressible=False, why="a synchronizer lane head that is not an input pin")
            return rec
        wc, sub, own_dom = when_of(when, own_regs)
        if wc is None:
            rec.update(v2_expressible=False, why="the defining case's domain is empty")
            return rec
        rec["when"], rec["subcase"] = wc, sub
        # schema v2.1 (2026-09-23): control.reset is a LIST of cases and hold means "outside EVERY
        # named case", so a counter or shift register with a synchronous clear can NAME that clear and
        # keep a hold region. Under v2.0 this branch named no reset at all for these two kinds, which
        # refuted the hold obligation of every reference structure that clears (74 of the corpus's 203
        # on the code state of 2026-09-23, before this line). The value obligation the harness then
        # checks is the one reset_values() read off the netlist, so naming it claims nothing extra.
        if kind in ("counter", "shift_register"):
            sr = sync_reset(jks)
            if sr:
                rec["reset"], rec["reset_value"] = sr
        doms = [own_dom.get(n) for n in own_regs]
        if kind == "counter":
            if when_down is not None:
                wd, sub2, od2 = when_of(when_down, own_regs)
                rec["when_down"] = wd
                rec["subcase"] |= sub2
                doms += [od2.get(n) for n in own_regs]
            rec["inverted"] = [j for j in p["bit_order"] if inv[j]]
            if not counter_ok(p, doms, len(p["bit_order"])):
                rec.update(v2_expressible=False,
                           why="the counting case needs the counter's own value beyond its modulus / saturation range "
                               "(it reloads or stops on its own value): v2 allows no self-conditions")
        elif any(d_ is not None for d_ in doms):
            rec.update(v2_expressible=False, why="the defining case restricts the structure's own state")
        return rec

    for r in design.regs:
        kind = r.check_as or r.kind
        if r.kind not in schema.STRUCTURE_KINDS:
            continue
        p = resolved.get(r.name) or {}
        order = p.get("order") or ([p["bit_order"]] if p.get("bit_order") else None)
        if not order:
            continue
        jks = [j for lane in order for j in lane]
        heads = None
        if kind == "synchronizer":
            heads = _resolve(r.head, {}) if r.head is not None else p.get("serial_in")
        out["registers"][r.name] = one(kind, p, jks, {r.name, r.vec}, r.claim_when or r.when, r.when_down, heads)
    for u in design.units:
        up = u.get("params") or {}
        if u["kind"] == "synchronizer" and up.get("order") and all(by[n].kind == "synchronizer" for n in u["registers"]):
            order = up["order"]
            jks = [regs_list[n][i] for lane in order for n, i in lane]
            out["units"][u["name"]] = one("synchronizer", up, jks, set(u["registers"]), None,
                                          heads=u.get("_head") or up.get("serial_in"))
    return out


def _ref_params(p, cell_of):
    out = {}
    for k, v in (p or {}).items():
        if k in ("order", "bit_order") and v is not None:
            out[k] = [[cell_of[j] for j in lane] for lane in v] if v and isinstance(v[0], list) else \
                [cell_of[j] for j in v]
        elif k == "serial_in" and v is not None:
            out[k] = [None if s is None else "input" if s.startswith("port:") else cell_of[s]
                      for s in (v if isinstance(v, list) else [v])]
        else:
            out[k] = v
    return out


def build_reference(truth, cdoc, lib, nl, key, g=None):
    """The perfect result of one design on one loaded netlist (opaque ids of `nl`; `key` names the
    flops by join key, as load() returns it): every structure-kind register with verified claims,
    except that a synchronizer unit whose members are all synchronizer registers (score.py's chain
    unit, STRICT_SYNC_RULE: lanes merged, or one register per stage) is reported as the unit; with
    params, order and claims, and the truth's registers as groups. "Verified" includes claims the
    harness's SAT budget could not decide but the corpus's BDD prover proved (claims.json:
    independent_proof); the harness reports those structures unknown."""
    return _reference(truth, cdoc, lib, nl, key, g)[0]


HOLD_REFUTED = ("the register does not hold outside its defining case (it clears, reloads or takes a "
                "second defining mode there) and this reference names no case that covers it. Schema "
                "v2.1 (2026-09-23) DOES let a reference name several reset cases and several load "
                "cases, and _reference now names the synchronous reset of a counter or shift register "
                "(29 of the corpus's 203 reference structures went from refuted to verified on that "
                "line alone, 122 -> 151); what is left is a RELOAD or a second defining mode, whose "
                "condition this builder does not hold symbolically, so it still cannot name it "
                "(changes.jsonl C59, I03)")


def _hold_refuted(srep):
    """Did the harness refute exactly the hold obligation of this reference structure? Read from the
    report's structured failed_check, not from its prose."""
    fc = srep.get("failed_check") or {}
    return fc.get("case") == "hold" and fc.get("result") == "refuted"


def _reference(truth, cdoc, lib, nl, key, g=None):
    """(reference result, [(truth register or unit name, v2 expressible, why)] per structure). The
    names stay out of the result: run.py's leak check flags any result string that names a port."""
    cell_of, qnet_of, port_net = id_maps(nl, key, g)
    L = cdoc["libs"][lib]
    CT = L.get("control") or {"registers": {}, "units": {}}
    by = {r["name"]: r for r in truth["registers"]}
    structs, missing, names = [], [], []
    chains = [u for u in truth.get("units", []) if u["kind"] == "synchronizer" and u["registers"] and
              all(by[n]["kind"] == "synchronizer" for n in u["registers"])]
    in_chain = {n for u in chains for n in u["registers"]}

    def proven(c):   # verified by the harness, or (its SAT budget exhausted) proven by the corpus's BDDs
        return bool(c) and (c["verified"] or (c.get("independent_proof") or {}).get("proven", False))

    def cd(x):
        if "port" in x:
            return {"net": port_net[x["port"]], "value": x["value"]}
        net, ninv = qnet_of[x["q"]]
        return {"net": net, "value": x["value"] ^ ninv}

    def lfsr_claims(sym, own, when_sym):
        """The defining XOR claims of the defining case `when_sym` (one cube), with other registers'
        states and pins as input nets."""
        inputs = set()

        def ex(e):
            (op, a), = e.items()
            if op == "q":
                if a in own:
                    return {"q": cell_of[a]}
                net, ninv = qnet_of[a]
                inputs.add(net)
                return {"not": {"net": net}} if ninv else {"net": net}
            if op == "port":
                inputs.add(port_net[a])
                return {"net": port_net[a]}
            if op == "const":
                return e
            if op == "not":
                return {"not": ex(a)}
            return {op: [ex(x) for x in a]}
        key_w = json.dumps(when_sym, sort_keys=True)
        pick = [c for c in sym if c["role"] == "defining" and json.dumps(c["when"], sort_keys=True) == key_w]
        if not pick:
            first = json.dumps(sym[0]["when"], sort_keys=True) if sym else None
            pick = [c for c in sym if c["role"] == "defining" and json.dumps(c["when"], sort_keys=True) == first]
        return [{"type": "next", "flop": cell_of[c["flop"]], "equals": ex(c["equals"]), "role": "defining"}
                for c in pick], sorted(inputs)

    def add(name, kind, params, order, c, ctl):
        flat = [cell_of[j] for lane in order for j in lane]
        own = {j for lane in order for j in lane}
        prm = _ref_params(params, cell_of)
        # schema v2 (2026-09-22) REQUIRES control.hold for counter and shift_register and verifies it,
        # so a reference that leaves it false is refused for a missing hold obligation, not for
        # anything about the design (it took every corpus and regression counter and shift reference
        # from verified to refused). The reference therefore claims it for those two kinds. Where the
        # design has no hold states at all -- it clears or reloads outside its `when`, and v2 has one
        # reset COND and one load COND to name the other cases with -- the claim is REFUTED, and the
        # caller reads that as "not expressible in v2" rather than as a broken reference; see
        # HOLD_REFUTED and changes.jsonl C59.
        control, claims = {"hold": kind in schema.STRUCTURE_KINDS[:2]}, []
        ok, why = True, None
        if ctl is None:
            ok, why = False, "no v2 control"
        else:
            ok, why = ctl.get("v2_expressible", True), ctl.get("why")
            control["when"] = [cd(x) for x in ctl.get("when") or []]
            if kind == "counter":
                if ctl.get("when_down") is not None:
                    control["when_down"] = [cd(x) for x in ctl["when_down"]]
                if ctl.get("inverted"):
                    control["inverted"] = sorted(cell_of[j] for j in ctl["inverted"])
            if ctl.get("reset"):
                # schema v2.1's multi-case form: a LIST of {"when": COND, "value": {flop: 0|1}}. The
                # v2.0 spelling (a bare COND with control.reset_value beside it) survives only behind
                # verify.LEGACY_CONTROL_FORM, and reset_value beside a v2.1 case is malformed, so the
                # reference states the case form the contract asks for.
                control["reset"] = [{"when": [cd(x) for x in ctl["reset"]],
                                     "value": {str(cell_of[j]): v for j, v in ctl["reset_value"].items()}}]
            if kind == "synchronizer":
                control["input"] = [port_net[pb] for pb in ctl.get("input") or []]
            if kind == "lfsr_crc":
                claims, control["inputs"] = lfsr_claims(c["claims"], own, ctl.get("when") or [])
        names.append((name, ok, why))
        structs.append({"id": f"ref{len(structs)}", "kind": kind, "flops": sorted(flat),
                        "order": [[cell_of[j] for j in lane] for lane in order], "params": prm, "control": control,
                        "proof": {"status": "proven" if ok else "unknown", "claims": claims}})

    for r in truth["registers"]:
        if r["kind"] not in schema.STRUCTURE_KINDS or r["name"] in in_chain:
            continue
        p = r.get("params") or {}
        order = p.get("order") or ([p["bit_order"]] if p.get("bit_order") else None)
        c = L["registers"].get(r["name"])
        if order is None:
            continue
        if not proven(c):
            missing.append(r["name"])
            continue
        add(r["name"], r["kind"], p, order, c, CT["registers"].get(r["name"]))
    for u in chains:
        c = L["units"].get(u["name"])
        if not proven(c):
            missing.append(u["name"])
            continue
        add(u["name"], u["kind"], u["params"], u["params"]["order"], c, CT["units"].get(u["name"]))
    groups = collections.defaultdict(list)
    for jk, v in truth["flops"].items():
        groups[v["primary"]].append(cell_of[jk])
    return {"schema": schema.RESULT_SCHEMA, "structures": structs,
            "groups": [sorted(v) for _n, v in sorted(groups.items())],
            "meta": {"reference": "tools/s3/corpus.py build_reference (v2 control)",
                     "v2_inexpressible": [s_["id"] for s_, (_n, ok, _w) in zip(structs, names) if not ok],
                     "structure_registers_without_claims": missing}}, names


def make_truth(design, per_lib, ref, resolved, reg_w, checks, unit_checks, extra, split, jk_of):
    libs = list(per_lib)
    regs, flops = [], {}
    by_reg = collections.defaultdict(list)
    width = {r.name: r.width for r in design.regs}
    order = {r.name: k for k, r in enumerate(design.regs)}
    for cn, hits in ref.items():
        for r, i, _s in hits:
            by_reg[r].append((i, cn))
    inst = {lib: {y: s_ for s_, y in per_lib[lib]["strip"].items()} for lib in libs}
    for r in design.regs:
        bits = []
        names = r.rtl_bit_names() if not r.flex else None
        for i, cn in sorted(by_reg.get(r.name, [])):
            rb = names[i] if names else f"{r.vec}[{_split_bit(cn.split('$', 1)[0])[1]}]"
            b = {"index": i, "flop": cn, "rtl_bit": rb,
                 "nl_instance": {lib: inst[lib].get(cn) for lib in libs},
                 "master": {lib: per_lib[lib]["masters"].get(cn) for lib in libs},
                 "inverted": {lib: per_lib[lib]["inv"].get(cn) for lib in libs}}
            if r.bit_alt and i in r.bit_alt:
                b["alt_kinds"] = sorted(set(r.bit_alt[i]) | set(r.alt_kinds))
            bits.append(b)
            if cn in flops:
                flops[cn]["registers"].append(r.name)
                flops[cn]["rtl_bits"].append(rb)
                flops[cn]["role"] = "shared"
                flops[cn]["primary"] = max(flops[cn]["registers"], key=lambda n: (width[n], -order[n]))
            else:
                flops[cn] = {"registers": [r.name], "primary": r.name, "role": "bit", "rtl_bits": [rb]}
        pc = dict(checks.get(r.name, {}))
        if "*" in checks:
            for lib, v in checks["*"].items():
                pc.setdefault(lib, []).extend(v)
        local = r.local or r.name
        prov = {"rule": r.rule, "auto_kind": None, "override_reason": None,
                "params_source": "stated by the generator (tools/s3/corpus.py), which wrote the RTL",
                "params_check": pc or None}
        if r.modes:
            prov["modes"] = r.modes
        if r.rtl_form:
            prov["rtl_form"] = r.rtl_form
        if r.note:
            prov["note"] = r.note
        if r.flex:
            prov["fsm_width_in_netlist"] = reg_w[r.name]
        prov.update(extra.get(r.name, {}))
        regs.append({"name": r.name, "width": reg_w[r.name] if r.flex else r.width, "kind": r.kind,
                     "alt_kinds": list(r.alt_kinds), "alt_reason": r.alt_reason, "module_def": r.module_def,
                     "design_key": f"{r.module_def}:{re.sub(r'\[\d+\](?=\.)', '[*]', local)}",
                     "params": resolved[r.name] if r.kind in schema.PARAMS or r.check_as else {},
                     "provenance": prov, "bits": bits, "n_flops": len(bits)})
    units = []
    for u in design.units:
        uu = {k: v for k, v in u.items() if not k.startswith("_")}
        if "flops" in uu:
            uu["flops"] = _resolve(uu["flops"], jk_of)
        if "params" in uu:
            uu["params"] = _resolve(uu["params"], jk_of)
            lu = lanes_unordered(u["params"].get("order"), u.get("_head") or u["params"].get("serial_in"))
            if lu is not None:
                uu["params"]["lanes_unordered"] = lu
        if u["name"] in unit_checks:
            uu["check"] = unit_checks[u["name"]]
        units.append(uu)
    return {"schema": schema.TRUTH_SCHEMA, "design": design.name, "registers": regs, "units": units, "flops": flops,
            "unmapped_flops": [], "operators": [],
            "meta": {"corpus": CORPUS_SCHEMA, "family": design.family, "cohort": design.cohort, "split": split,
                     "description": design.desc,
                     "top": "top", "rtl": "rtl.v", "netlists": {lib: f"{lib}.v" for lib in libs},
                     "quiet_inputs": design.quiet, "known_disagreements": design.notes,
                     "conventions": TRUTH_CONVENTIONS,
                     "kinds": dict(collections.Counter(r["kind"] for r in regs))}}


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def build(outdir, only=None, jobs=None, echo=print):
    ds = designs()
    sp = splits(ds)
    if only:
        missing = set(only) - {x.name for x in ds}
        if missing:
            raise SystemExit(f"unknown designs: {sorted(missing)}")
        ds = [x for x in ds if x.name in only]
    os.makedirs(outdir, exist_ok=True)
    work_root = tempfile.mkdtemp(prefix="s3corpus-")
    for x in ds:
        ddir = os.path.join(outdir, x.name)
        os.makedirs(ddir, exist_ok=True)
        with open(os.path.join(ddir, "rtl.v"), "w") as f:
            f.write(f"// RETRACE S3 synthetic corpus: {x.name} ({x.family}): {x.desc}\n// generated by tools/s3/corpus.py\n")
            f.write(x.rtl)
    syn = collections.defaultdict(dict)
    errors = {}
    tasks = [(x, lib) for x in ds for lib in LIBS]
    with concurrent.futures.ThreadPoolExecutor(jobs or min(8, os.cpu_count() or 4)) as ex:
        fut = {ex.submit(run_yosys, os.path.join(outdir, x.name, "rtl.v"), lib,
                         os.path.join(work_root, x.name, lib)): (x.name, lib) for x, lib in tasks}
        for f in concurrent.futures.as_completed(fut):
            n, lib = fut[f]
            try:
                syn[n][lib] = f.result()
            except Exception as e:  # noqa: BLE001
                errors[n] = f"{lib}: {e}"
    entries, failed = [], {}
    for x in ds:
        if x.name in errors:
            failed[x.name] = [errors[x.name]]
            echo(f"FAIL {x.name}: {errors[x.name][:400]}")
            continue
        truth, per_lib, problems = finish(x, outdir, syn[x.name], sp[x.name], echo)
        if problems:
            failed[x.name] = problems
            echo(f"FAIL {x.name}: " + "; ".join(problems)[:1200])
        ddir = os.path.join(outdir, x.name)
        entries.append({
            "name": x.name, "family": x.family, "cohort": x.cohort, "split": sp[x.name], "description": x.desc,
            "rtl": f"{x.name}/rtl.v", "truth": f"{x.name}/truth.json", "truth_hash": schema.truth_hash(truth),
            "registers": len(truth["registers"]), "flops": len(truth["flops"]),
            "kinds": {k: sum(r["n_flops"] for r in truth["registers"] if r["kind"] == k)
                      for k in sorted({r["kind"] for r in truth["registers"]})},
            "structure_registers": sum(1 for r in truth["registers"] if r["kind"] in schema.STRUCTURE_KINDS),
            "units": len(truth["units"]), "known_disagreements": len(x.notes),
            "netlists": {lib: {"file": f"{x.name}/{lib}.v", "named": f"{x.name}/{lib}.named.v",
                               "sha256": _sha(os.path.join(ddir, f"{lib}.v")), "cells": per_lib[lib]["cells"],
                               "flops": per_lib[lib]["flops"],
                               "inverted_flops": sum(per_lib[lib]["inv"].values()),
                               "claims": per_lib[lib].get("n_claims"), "reference": per_lib[lib].get("reference"),
                               **per_lib[lib].get("graph", {})} for lib in per_lib},
            "claims": f"{x.name}/claims.json",
            "checks_ok": not problems})
    shutil.rmtree(work_root, ignore_errors=True)
    mpath = os.path.join(outdir, "manifest.json")
    old = {}
    if only and os.path.exists(mpath):
        with open(mpath) as f:
            old = {e["name"]: e for e in json.load(f).get("designs", [])}
    allnames = [x.name for x in designs()]
    merged = {**old, **{e["name"]: e for e in entries}}
    ordered = [merged[n] for n in allnames if n in merged]
    if not only:  # drop directories of designs that no longer exist
        for n in os.listdir(outdir):
            p = os.path.join(outdir, n)
            if os.path.isdir(p) and n not in merged and os.path.exists(os.path.join(p, "truth.json")):
                shutil.rmtree(p)
    counts = {
        "designs": len(ordered), "train": sum(e["split"] == "train" for e in ordered),
        "holdout": sum(e["split"] == "holdout" for e in ordered),
        "checks_ok": sum(e["checks_ok"] for e in ordered),
        "families": dict(collections.Counter(e["family"] for e in ordered)),
        "cohorts": {str(c): {"designs": sum(e.get("cohort", 1) == c for e in ordered),
                             "holdout": sum(e.get("cohort", 1) == c and e["split"] == "holdout" for e in ordered)}
                    for c in sorted({e.get("cohort", 1) for e in ordered})},
        "flops_by_kind": dict(sum((collections.Counter(e["kinds"]) for e in ordered), collections.Counter())),
        "flops": sum(e["flops"] for e in ordered)}
    rk = collections.Counter()
    for e in ordered:
        with open(os.path.join(outdir, e["truth"])) as f:
            rk.update(r["kind"] for r in json.load(f)["registers"])
    counts["registers_by_kind"] = dict(rk)
    counts["claims"] = {lib: sum((e["netlists"].get(lib) or {}).get("claims") or 0 for e in ordered) for lib in LIBS}
    counts["reference_structures_verified"] = {
        lib: f"{sum(((e['netlists'].get(lib) or {}).get('reference') or {}).get('verified', 0) for e in ordered)}/"
             f"{sum(((e['netlists'].get(lib) or {}).get('reference') or {}).get('structures', 0) for e in ordered)}"
        for lib in LIBS}
    counts["reference_harness_unknown"] = {
        lib: sorted(f"{e['name']}:{n}" for e in ordered
                    for n in (((e["netlists"].get(lib) or {}).get("reference") or {})
                              .get("harness_unknown_independently_proven") or []))
        for lib in LIBS}
    man = {"schema": CORPUS_SCHEMA, "generated_by": "tools/s3/corpus.py",
           "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "yosys": yosys_version(),
           "libs": {lib: {"liberty": LIBS[lib]["liberty"].replace(os.path.expanduser("~"), "~"),
                          "sha256": _sha(LIBS[lib]["liberty"]), "tie_cells": LIBS[lib]["hilo"]} for lib in LIBS},
           "flow": yosys_script("<rtl.v>", "sky130", "<work>").replace(LIBS["sky130"]["liberty"], "<liberty>")
           .replace(LIBS["sky130"]["hilo"], "<tie cells>"),
           "split_rule": "per (cohort, family), designs sorted by sha256(name); the first (n + 1) // 4 are holdout "
                         "(cohort 2 leaves every cohort-1 split unchanged)",
           "holdout": [e["name"] for e in ordered if e["split"] == "holdout"],
           "regression_sets": {"out/s3/review_generalisation": "the generalisation reviewer's 33 designs x 5 flows x 2 "
                                                               "libraries: a regression set, not part of this corpus "
                                                               "and not copied into it; tuning on it is logged in "
                                                               "tools/s3/changes.jsonl"},
           "check_lanes": 64 * LANES_W, "counts": counts, "designs": ordered}
    with open(mpath, "w") as f:
        json.dump(man, f, indent=1)
        f.write("\n")
    return man, failed


# ----------------------------------------------------------------------------------------------
# API for tests


def manifest(outdir=None, raw=False):
    """The built manifest, CORRECTED against this module (raw=True: the file as written).

    The file on disk is whatever the last build wrote. Two corrections are applied here so that
    every reader gets them without a rebuild, and so that a stale build can never re-admit a design
    this module dropped (review[2] issues 1 and 6):
      * designs in DROPPED are removed (their directories may still be on disk);
      * every design's split is re-stamped from splits(designs()), which forces FITTED_ON designs
        into "train"; manifest["holdout"] and counts follow.
    manifest()["corrections"] says what was changed, and is empty when the build is current.
    """
    with open(os.path.join(outdir or DEFAULT_OUT, "manifest.json")) as f:
        man = json.load(f)
    if raw:
        return man
    sp = splits(designs())
    dropped = [e["name"] for e in man.get("designs", []) if e["name"] in DROPPED]
    man["designs"] = [e for e in man.get("designs", []) if e["name"] not in DROPPED]
    moved = {}
    for e in man["designs"]:
        new = sp.get(e["name"], e.get("split"))
        if new != e.get("split"):
            moved[e["name"]] = f"{e.get('split')} -> {new}"
        e["split"] = new
    man["holdout"] = [e["name"] for e in man["designs"] if e["split"] == "holdout"]
    c = man.setdefault("counts", {})
    c["designs"] = len(man["designs"])
    c["train"] = sum(1 for e in man["designs"] if e["split"] == "train")
    c["holdout"] = len(man["holdout"])
    man["corrections"] = {"dropped": {n: DROPPED[n] for n in dropped},
                          "moved": {n: {"change": v, "reason": FITTED_ON.get(n)} for n, v in moved.items()},
                          "rebuild_needed": bool(dropped or moved)}
    return man


def load(name, lib, outdir=None, seed=0):
    """(Netlist, Key, truth) of one corpus design and library. The netlist comes from <lib>.v through
    netlist.load_verilog(seed=seed); the Key's flop cell names are replaced by the truth's join keys."""
    ddir = os.path.join(outdir or DEFAULT_OUT, name)
    with open(os.path.join(ddir, "truth.json")) as f:
        truth = json.load(f)
    nl, key = load_verilog(os.path.join(ddir, f"{lib}.v"), library(lib), seed=seed)
    jk = {b["nl_instance"][lib]: b["flop"] for r in truth["registers"] for b in r["bits"]}
    key2 = Key([jk.get(n, n) for n in key.cell_name], key.net_name, key.ports, key.position)
    return nl, key2, truth


def claims(name, outdir=None):
    """The design's claims.json: per library, the symbolic claims of every structure register and
    shift/synchronizer unit, with their verification records."""
    with open(os.path.join(outdir or DEFAULT_OUT, name, "claims.json")) as f:
        return json.load(f)


def reference_result(name, lib, nl, key, outdir=None):
    """A schema result that a perfect recognizer could return for this design, in the opaque ids of
    `nl`, with proof claims that tools/s3/verify.py verifies. `key` must name nl's flops by join key
    and its ports by pin bit (load() returns such a pair; after run.relabel(nl), permute both)."""
    ddir = os.path.join(outdir or DEFAULT_OUT, name)
    with open(os.path.join(ddir, "truth.json")) as f:
        truth = json.load(f)
    return build_reference(truth, claims(name, outdir), lib, nl, key)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("outdir", nargs="?", default=DEFAULT_OUT)
    ap.add_argument("--only", help="comma-separated design names")
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--list", action="store_true", help="list the designs and exit")
    a = ap.parse_args(argv)
    if a.list:
        ds = designs()
        sp = splits(ds)
        for x in ds:
            print(f"{x.name:32s} {x.family:22s} {sp[x.name]:8s} {x.desc}")
        print(f"{len(ds)} designs")
        return 0
    only = [n for n in a.only.split(",") if n] if a.only else None
    man, failed = build(os.path.abspath(a.outdir), only, a.jobs)
    c = man["counts"]
    print(f"{c['designs']} designs ({c['train']} train, {c['holdout']} holdout), {c['flops']} flops, "
          f"checks ok {c['checks_ok']}/{c['designs']}")
    print("registers by kind:", c["registers_by_kind"])
    print("claims:", c["claims"], "reference structures verified:", c["reference_structures_verified"])
    if failed:
        print(f"{len(failed)} design(s) failed: {sorted(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
