"""S3 data contracts: the ground-truth file, the recognizer's result file, and their checks.

Truth (``retrace-s3-truth/2``), one file per design (out/s3/truth_<design>.json):

    {"schema": "retrace-s3-truth/2", "design": "tempo" | "puzzle" | "<third-party id>",
     "registers": [{
         "name": RTL register name, "width": int, "kind": one of KINDS,
         "alt_kinds": [kinds a scorer also accepts, each with a reason in "alt_reason"],
         "alt_reason": str | null,
         "module_def": RTL module definition, "design_key": module:local name (indices as [*]),
         "params": kind-specific, see PARAMS; unknown values are null and leave the denominator,
         "provenance": {"rule", "auto_kind", "override_reason", "params_source", "params_check"},
         "bits": [{"index": int, "flop": join key (GDS instance name, master_x_y), "rtl_bit": str,
                   "shadow_flops": [join keys of synthesis duplicates of this bit: D(dup) == D(flop)
                                    always; not part of the register's matched flop set],
                   "alt_kinds": [per-bit alternatives, when a rule applies to some bits only]}]}],
     "units": [{"name", "kind", "registers": [names], "reason"}],   # declared lenient alternatives
     "flops": {join key: {"registers": [every register using the flop], "primary": name}},
     "unmapped_flops": [{"flop", "reason"}],
     "operators": [...],                                             # later slices; unscored
     "meta": {...}}                                                  # no timings: see truth_hash()

  Volatile facts (timings, memory, tool versions, commits) go to out/s3/truth_<design>.run.json.

  Rules the truth and the scorer share:
  * alt_kinds (register-level, or per bit in bits[].alt_kinds) only widen what a match accepts;
    they never remove a register from a denominator.
  * A register's matched flop set is its bits' "flop"s; shadow_flops are extra copies that a
    structure may include or omit without penalty.
  * A register that is one stage of a declared unit (e.g. a synchronizer stage) has stage-level
    params null; the unit carries them.
  * Flops that hold a retimed function of a register (synthesis moved logic across them) form their
    own register of kind "other".
  * lfsr_crc params: k_steps = LFSR steps applied per clock in the register's main update mode;
    n_inputs = data bits entering per LFSR step (0 for an autonomous LFSR). A register with several
    update modes records its main (data) mode here and the others in provenance.

Result (``retrace-s3-result/1``), written by the recognizer from the anonymous netlist only:

    {"schema": "retrace-s3-result/1",
     "structures": [{
         "id": str, "kind": one of KINDS,
         "flops": [opaque flop ids],
         "order": [[ids] per lane, in stage / weight order (LSB or stage 0 first)] | null,
         "params": kind-specific (as PARAMS), "control": {see Verification},
         "proof": {"status": one of PROOF (the recognizer's claim), "claims": [see Verification]}}],
     "groups": [[opaque flop ids]],      # word grouping: a partition of the flops it grouped
     "meta": {...}}

  Opaque ids mean nothing outside the run; the harness maps them to join keys with a key it
  never gives the recognizer.

Verification (v2, kind-bound). "proven" is only what the harness verifies (tools/s3/verify.py) on
its own copy of the anonymous netlist, and for the four STRUCTURE_KINDS the harness derives the
defining claims itself from the structure's kind, order and params; the recognizer supplies only
conditions. A restatement of a flop's own D logic never verifies a structure.

  Conditions: COND = [{"net": id, "value": 0 | 1}, ...], a conjunction; [] means always.
  structure["control"] = {"when": COND,          # the structure's defining case (count / shift / step)
                          "when_down": COND | null,  # counter, direction "updown": the down case
                          "reset": [{"when": COND, "value": {flop id: 0 | 1}}, ...] | null,
                          #                        synchronous reset/clear cases, each with its value
                          "load": [COND, ...] | null,  # opaque load cases: allowed, never defining.
                          #                        Nothing is checked under a load case, so a load case
                          #                        is never evidence; it only removes states from the
                          #                        regions the harness does check. A BOUNDED list: at
                          #                        most 64 cases (verify.LOAD_CASES_MAX) of at most 256
                          #                        literals each (verify.COND_LITERALS); a longer list
                          #                        is malformed, i.e. out of scope for "proven", not a
                          #                        refutation of the structure
                          "hold": bool,          # outside EVERY named case the flops keep their value;
                          #                        REQUIRED true for counter and shift_register, and
                          #                        verified: without it a degenerate template passes.
                          #                        An opaque load case may NEVER be the thing that
                          #                        empties the hold region (lead's decision of
                          #                        2026-09-23, verify.HOLD_EMPTY_NEEDS_VERIFIED_COVER).
                          #                        THE COVER IS READ OFF THE CUBES THE HARNESS CHECKED,
                          #                        NOT OFF THE CASE CONDs: a reset case is CHECKED only
                          #                        on its own priority cube, which conjoins ~(each load
                          #                        case), so the reset CONDs can empty the region at
                          #                        full size while the load-active part of each reset
                          #                        case was checked by nothing. So an EMPTY hold region
                          #                        is accepted, and reported as vacuous, only when BOTH
                          #                        (a) the same region WITHOUT the load conjunct is
                          #                        unsatisfiable AND (b) NO load case is satisfiable
                          #                        outside the defining cases. Both tests must answer
                          #                        unsat; "sat" on either gives cover "load" and REFUSES
                          #                        the structure, and an undecided answer (unknown or
                          #                        conflict budget) REFUSES it too. Test (a) alone is
                          #                        necessary and NOT sufficient -- the rewrite that
                          #                        exploits it (T2, out/s3/verify/hold_gate_t2.py) turns
                          #                        each literal of `when` into its own lying reset case
                          #                        and hides the lie behind a load; test (b) is what
                          #                        refuses it, and is vacuous when there are no load
                          #                        cases, so a free-running counter (when = []) and every
                          #                        load-free structure are unaffected. Without the rule
                          #                        the obligation is erasable for free: ~when is a
                          #                        disjunction of single-literal CONDs and a load LIST
                          #                        can name exactly those, so any structure could erase
                          #                        its own hold obligation with no new evidence about
                          #                        the circuit.
                          #                        WHAT THE RULE BOUNDS: the SHAPE of the cover, NOT ITS
                          #                        SIZE. A PARTIAL complement leaves the region
                          #                        non-empty on a sliver and the obligation is then
                          #                        genuinely checked -- on that sliver. The numbers that
                          #                        bound the SIZE are reported on every verdict and
                          #                        never gated: lane_share per case, reset_cases[i].share
                          #                        and load_hidden_share.
                          #                        "hold_vacuous_cover" reports WHAT THE HARNESS DECIDED
                          #                        and nothing else; it appears only when hold_vacuous
                          #                        is true, and its four values assert:
                          #                          "verified" -- the cubes the harness CHECKED cover
                          #                            the hold region: tests (a) and (b) BOTH answered
                          #                            unsatisfiable, and the structure may verify;
                          #                          "load" -- one of the two tests was SATISFIABLE, so
                          #                            an opaque load is what empties the obligation and
                          #                            the structure is REFUSED (the reason string says
                          #                            which test);
                          #                          verify.HOLD_COVER_UNDECIDED -- the rule is OFF and
                          #                            load cases exist, so the harness did not decide
                          #                            the question at all; the structure is not refused
                          #                            on it and the verdict must NOT be read as if it
                          #                            had been decided;
                          #                          "unknown" / "budget" -- a solver answer, and the
                          #                            structure is REFUSED, never assumed covered.
                          #                        The run summary's hold_emptied_by_load counts the
                          #                        "load" verdicts
                          "inverted": [flop ids] | null,  # flops that store the complement of their
                          #                        word bit (a structural choice the harness checks)
                          "input": net id | null # synchronizer: the input net stage 0 samples
                          "inputs": [net ids]}   # lfsr_crc: data nets entering per step
  Flop model: the effective next state honours the cell's async clear/preset (both = the cell's
  rule) and clock gating (an ICG or logic on the clock path is an enable); a claim holds only for
  states where no async control is active, and COND must be satisfiable with them inactive.

  Defining templates the harness builds (q = current flop outputs, w = the structure's word in
  params order, LSB / stage 0 first):
  * counter: under when (and not reset/load): w' = w + step (direction up) or w - step (down),
    modulo params.modulus (default 2^width), or saturating at the limit when params.saturating;
    bit-level expressions built by the harness from the order; direction "updown" counts down under
    when_down. hold (required): w' = w outside when/reset/load. The width must match the modulus or
    saturation limit, 2^(width-1) < modulus <= 2^width and limit >= 2^(width-1), so no claimed bit
    is dead; a template that is constant or independent of the word is refused.
  * shift_register: under when, stage k' = stage k-1 for k >= 1 in every lane (an edge may be
    inverted: stage k' = not stage k-1, reported per stage); stage 0 is the lane head (its function
    is not part of the kind). depth >= 3. hold (required) as above.
  * synchronizer: always stage 0' = input or not input, stage k' = stage k-1; no condition.
  * lfsr_crc: the recognizer gives each bit's EXPR in structure["proof"]["claims"] as
    {"type": "next", "flop": id, "equals": EXPR}; the harness accepts it only if EXPR is an XOR of
    the structure's own q's, nets in control.inputs and constants, the own-bit matrix is not a
    permutation (that is a shift), and it holds under control.when. params.form may be "fibonacci",
    "galois", "parallel", "affine" (GF(2)-linear but not a companion power) or "both" (when the two
    forms coincide, e.g. some trinomials).
  Extent and liveness. A structure may not be padded with flops that ride along:
  * counter: every claimed bit must move in the defining region (a bit whose template is the
    identity there, as the low bits of a step 2^k are, is dead and the structure is refused);
    width >= 2; width and modulus/limit as above.
  * lfsr_crc: the own-bit matrix must be strongly connected over the structure's flops (every flop
    reaches and is reached by the others), which refuses a flop whose only own reference is itself.
  * shift_register: depth >= 3; synchronizer: at least 2 stages.

  Params the harness can check it checks: direction "updown" requires when_down; for lfsr_crc the
  polynomial and k_steps are reconstructed from the own matrix and compared with params where the
  form admits it. Params it cannot check are copied into the report and marked unchecked.

  Non-vacuity and coverage: every defining COND (and the hold region) is satisfiable with reset,
  load and async controls inactive; and for a counter the defining region must be reachable for
  every value of its own word in range, so a case carved down to a few of the word's own states is
  refused. No condition the harness relies on -- when, when_down, reset, load, an async control of
  the structure's flops, or a clock-gating enable -- may depend on the structure's own state,
  except where the coverage obligation above admits it (a wrap or reload at a terminal count).
  A structure is verified when every flop's defining template holds (and hold/reset when claimed).
  Unscored kinds may carry claims; they never count as verified structures.

  Claim EXPR (lfsr_crc, and optional extra claims of any kind):
    EXPR = {"q": flop id} | {"net": id} | {"const": 0 | 1} | {"not": EXPR}
         | {"and": [EXPR, ...]} | {"or": [EXPR, ...]} | {"xor": [EXPR, ...]}

  Order: "order" is always a list of lanes (a list of lists), in stage / weight order. When lanes are structurally identical and no
  structural key separates them, set params.lanes_unordered = true; the scorer then scores only
  within-lane order. Ids carry no order: never order anything by id.
"""

import hashlib
import json

TRUTH_SCHEMA = "retrace-s3-truth/2"
RESULT_SCHEMA = "retrace-s3-result/1"

KINDS = (
    "shift_register", "counter", "lfsr_crc", "synchronizer",    # scored structure kinds
    "register_file_word", "fsm_state", "data_register", "accumulator", "flag", "other",
)
STRUCTURE_KINDS = KINDS[:4]
PROOF = ("proven", "unknown", "failed", "not_attempted")
LFSR_FORMS = ("fibonacci", "galois", "parallel", "affine", "both")

# kind-specific parameters (truth and result use the same names; null = unknown)
PARAMS = {
    "shift_register": ("lanes", "depth", "direction", "serial_in", "order", "lanes_unordered"),
    "counter": ("direction", "step", "modulus", "saturating", "load", "bit_order"),
    "lfsr_crc": ("form", "poly", "k_steps", "n_inputs", "bit_order"),
    "synchronizer": ("stages", "order", "lanes_unordered"),
}

_KIND_ALIASES = {  # truth_puzzle.py's first vocabulary
    "shift": "shift_register", "lfsr": "lfsr_crc", "regfile": "register_file_word", "fsm": "fsm_state",
    "sync": "synchronizer", "data": "data_register",
}


def canonical_kind(kind):
    return _KIND_ALIASES.get(kind, kind)


def truth_hash(truth):
    """Content hash of the scored part of a truth file: registers, units, flops, unmapped flops.
    Independent of key order and of meta, so reruns that only differ in timings agree."""
    core = {k: truth.get(k) for k in ("schema", "design", "registers", "units", "flops", "unmapped_flops")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _flat_order(order):
    if order is None:
        return None
    return [f for lane in order for f in lane] if order and isinstance(order[0], list) else list(order)


def check_truth(truth):
    """Structural checks; returns a list of problems (empty when valid)."""
    bad = []
    if truth.get("schema") != TRUTH_SCHEMA:
        bad.append(f"schema {truth.get('schema')!r} != {TRUTH_SCHEMA}")
    names = set()
    for r in truth.get("registers", []):
        names.add(r["name"])
        if r.get("kind") not in KINDS:
            bad.append(f"{r['name']}: kind {r.get('kind')!r}")
        for k in r.get("alt_kinds") or []:
            if k not in KINDS:
                bad.append(f"{r['name']}: alt kind {k!r}")
        if (r.get("alt_kinds") or []) and not r.get("alt_reason"):
            bad.append(f"{r['name']}: alt_kinds without alt_reason")
        params = r.get("params") or {}
        for p in params:
            if r["kind"] in PARAMS and p not in PARAMS[r["kind"]]:
                bad.append(f"{r['name']}: unknown param {p!r} for {r['kind']}")
        own = sorted(b["flop"] for b in r.get("bits", []) if b.get("flop"))
        for key in ("order", "bit_order"):
            flat = _flat_order(params.get(key))
            if flat is not None and sorted(flat) != own:
                bad.append(f"{r['name']}: params.{key} is not a permutation of the register's flops")
        if r["kind"] == "shift_register" and params.get("lanes") and params.get("depth"):
            if params["lanes"] * params["depth"] != len(own):
                bad.append(f"{r['name']}: lanes x depth != flops")
        for b in r.get("bits", []):
            for k in b.get("alt_kinds") or []:
                if k not in KINDS:
                    bad.append(f"{r['name']}[{b['index']}]: alt kind {k!r}")
            for d in b.get("shadow_flops") or []:
                if d == b.get("flop"):
                    bad.append(f"{r['name']}[{b['index']}]: shadow flop equals the flop")
    flops = truth.get("flops", {})
    for r in truth.get("registers", []):
        for b in r.get("bits", []):
            f = b.get("flop")
            if f is not None and r["name"] not in flops.get(f, {}).get("registers", []):
                bad.append(f"{r['name']}[{b['index']}]: flop {f} does not list the register")
    for f, v in flops.items():
        if v.get("primary") not in v.get("registers", []):
            bad.append(f"flop {f}: primary not among its registers")
        for n in v.get("registers", []):
            if n not in names:
                bad.append(f"flop {f}: unknown register {n}")
    by_name = {r["name"]: r for r in truth.get("registers", [])}
    for u in truth.get("units", []):
        if u.get("kind") not in KINDS or not u.get("reason"):
            bad.append(f"unit {u.get('name')}: kind or reason missing")
        for n in u.get("registers", []):
            if n not in names:
                bad.append(f"unit {u.get('name')}: unknown register {n}")
        member_flops = {b["flop"] for n in u.get("registers", []) if n in by_name
                        for b in by_name[n].get("bits", []) if b.get("flop")}
        for f in u.get("flops") or []:
            if f not in member_flops:
                bad.append(f"unit {u.get('name')}: flop {f} not in any member register")
    covered = {b["flop"] for r in truth.get("registers", []) for b in r.get("bits", []) if b.get("flop")}
    for f in flops:
        if f not in covered:
            bad.append(f"flop {f}: listed in flops but no register bit uses it")
    return bad


def check_result(result):
    bad = []
    if result.get("schema") != RESULT_SCHEMA:
        bad.append(f"schema {result.get('schema')!r} != {RESULT_SCHEMA}")
    seen = set()
    for s in result.get("structures", []):
        if s.get("kind") not in KINDS:
            bad.append(f"{s.get('id')}: kind {s.get('kind')!r}")
        if (s.get("proof") or {}).get("status", "not_attempted") not in PROOF:
            bad.append(f"{s.get('id')}: proof status")
        if s.get("order"):
            flat = [f for lane in s["order"] for f in lane]
            if sorted(flat) != sorted(s["flops"]):
                bad.append(f"{s.get('id')}: order is not a permutation of its flops")
    for g in result.get("groups", []):
        for f in g:
            if f in seen:
                bad.append(f"groups: flop {f} in two groups")
            seen.add(f)
    return bad
