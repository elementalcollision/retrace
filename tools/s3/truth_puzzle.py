"""S3 ground truth for the puzzle: every flop's register, kind, bit order and parameters.

The puzzle run is a frozen-code evaluation on a design the team already knows (its RTL was
recovered in this repository), not a blind test; see docs/S3_DESIGN.md.

The puzzle's 92 flops are anonymous in the GDS. Their meaning comes from the recovered RTL
(`rtl_recovered/*.v`, proven equivalent to the extracted netlist per block by SAT and end to
end by PDR, docs/INTENT.md section 6) and `rtl_recovered/blocks.json` (fNN -> extracted
instance). This file states the registers by hand, in the RTL's register names, and then
checks every claim it writes against the RTL and the extracted netlist before writing:

  1. extraction: a fresh extraction of upstream/puzzle.gds has exactly the 92 flops of
     blocks.json, with the same masters and the same Q, D, clock and reset nets;
  2. names: puzzle_recovered.v's `reg <name>; // fNN, reset ...` tags name every flop once,
     agree with the rec_* port map and with the reset blocks.json implies;
  3. next-state functions of the rec_* blocks, evaluated with Icarus (exhaustively wherever
     the support is small): bit orders are DERIVED from each counter's orbit from 0 (the
     state after 2^i increments must be one-hot, which makes the order unique), moduli and
     carries, the shift chain, the LFSR's matrix, polynomial, period and print-mode map,
     the array's decode (regions and columns), the saturating bins, the check constants,
     and the message ROM;
  4. a cycle-by-cycle Python model written from this truth alone (its bit orders and
     semantics) run on eight input streams against puzzle_recovered AND against the freshly
     extracted netlist (sky130 cell models): every flop, O and success must agree.

The JSON is written only if every check passes. Parameters (schema.PARAMS) are stated by
hand and each is covered by the checks named in its provenance.params_check.verified_by.

    python -m tools.s3.truth_puzzle [out/s3/truth_puzzle.json] [--run-json PATH] [--work DIR]

Output: schema retrace-s3-truth/2 (tools/s3/schema.py): registers [{name, width, kind,
alt_kinds, alt_reason, module_def (the rec_* block computing it), design_key, params, bits
[{index, flop (join key: the extraction's master_x_y instance name), rtl_bit, flop_id, q_net,
master, reset}], n_flops, provenance, details}], units (declared lenient alternatives), flops
{join key: {registers, primary, role, rtl_bits, flop_id}}, unmapped_flops, operators, meta.
Timings and versions go to the .run.json next to it; the truth file is byte-identical across
reruns. Bit index 0 is a counter's LSB, a shift register's first stage (the one that loads
the serial input) and the LFSR's feedback stage.
"""

import argparse
import hashlib
import json
import os
import platform
import random
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
BIN = os.path.expanduser("~/ttsetup/oss-cad-suite/bin")

from tools.s3 import schema  # noqa: E402

BLOCKS = "rtl_recovered/blocks.json"
TOP = "rtl_recovered/puzzle_recovered.v"
BLOCK_FILES = {b: f"rtl_recovered/{b}.v" for b in ("counter", "array", "left_top", "left_bottom", "check", "outgen")}
RTL_FILES = [TOP, *BLOCK_FILES.values()]
GDS = "upstream/puzzle.gds"
LEF = "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"
MODELS = ["pdk/sky130_fd_sc_hd/verilog/primitives.v", "pdk/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v"]
SOLUTION_DOC = "docs/SOLUTION.md"
INTENT_DOC = "docs/INTENT.md"
# rows, columns and regions hold 2 stars each but 11 pairs touch (copied from test/test_messages.py)
TOUCHING = ("01001000000" "00000010010" "00000001010" "00001001000" "10000100000"
            "00100000100" "00000100100" "00000010001" "00010000001" "10010000000" "01100000000")


def P(path):
    return os.path.join(ROOT, path)


def fid(n):
    return f"f{n:02d}"


# ----------------------------------------------------------------------------------------
# The truth, stated by hand in RTL register names (puzzle_recovered.v). Bits are listed in
# index order. Everything marked "derived" in the output is recomputed by the checks below.
# ----------------------------------------------------------------------------------------

EN = "enable & ~cnt_done"
EN_I = "I & enable & ~cnt_done"
LFSR_TAPS = (3, 4, 5, 7)  # index coordinates: feedback = I ^ s3 ^ s4 ^ s5 ^ s7
MESSAGES = {"empty": "EMPTY SKY", "bigbang": "BIG BANG", "try": "TRY AGAIN", "two": "TWO NOT TOUCH"}
GROUP_A = range(0, 11)   # bins 0-10: regions
GROUP_B = range(11, 22)  # bins 11-21: columns


def _registers():
    regs = [
        dict(name="cnt_lo", kind="counter", bits=["lo0", "lo1", "lo2", "lo3"], details=dict(
            block="counter",
            summary="ones digit of the cycle counter (the grid column): 4-bit binary up-counter, modulus 11",
            direction="up", step=1, modulus=11, saturating=False, enable=EN,
            wrap="cnt_lo == 10 -> 0, and carries into cnt_hi",
            carry_out="enable & ~cnt_done & cnt_lo == 10",
            reachable=[0, 10],
            meaning="column 0..10 of the 11 x 11 grid; enabled cycle k of the sweep presents row k // 11, column k % 11")),
        dict(name="cnt_hi", kind="counter", bits=["hi0", "hi1", "hi2", "hi3"], details=dict(
            block="counter",
            summary="elevens digit of the cycle counter (the grid row): 4-bit binary up-counter, modulus 11, "
                    "counting cnt_lo's carries",
            direction="up", step=1, modulus=11, saturating=False,
            enable="carry from cnt_lo: enable & ~cnt_done & cnt_lo == 10",
            wrap="cnt_hi == 10 on a carry -> 0, and sets cnt_done (terminal count of the 121-state sweep)",
            reachable=[0, 10],
            meaning="row 0..10 of the 11 x 11 grid")),
        dict(name="cnt_done", kind="flag", bits=["cnt_done"], details=dict(
            block="counter",
            summary="sticky terminal-count flag of the mod-121 sweep",
            set="enable & ~cnt_done & cnt_lo == 10 & cnt_hi == 10 (the 121st enabled cycle; cnt_lo and cnt_hi "
                "wrap to 0 on the same edge)",
            clear="none (async reset only)", sticky=True,
            fanout="freezes cnt_lo/cnt_hi, the array bins, the shift register, row_stars and the row/touch checks, "
                   "star_count and the scrambler's shift mode; its first rising edge triggers the decision (check)")),
    ]
    for k in range(22):
        regs.append(dict(name=f"bin{k:02d}", kind="counter", bits=[f"bin{k:02d}_lsb", f"bin{k:02d}_msb"], details=dict(
            block="array",
            summary=("stars in Star Battle region %s: " % "ABCDEFGHIJK"[k] if k in GROUP_A else "stars in a grid column: ")
            + "2-bit saturating up-counter under a decode of the cycle counter",
            direction="up", step=1, modulus=None, saturating=True, saturate_at=3,
            enable=None, decode=None,  # both filled from the RTL's decode by check_array()
            checked_value=2)))
    regs += [
        dict(name="shift_taps", kind="shift_register", bits=[f"shift_tap{k}" for k in range(12)], details=dict(
            block="left_top",
            summary="12-stage shift register of the last 12 grid cells (I), serial in at index 0",
            serial_in="I", enable=EN, stages=12, direction="index k loads index k-1; index 0 loads I",
            serial_out=None,
            taps_read=({"0": "cell to the left (n-1)", "9": "above-right (n-10)", "10": "above (n-11)",
                        "11": "above-left (n-12)"}),
            meaning="after a shift, index k holds the cell entered k+1 enabled cycles ago (index 0 = the last I)")),
        dict(name="row_stars", kind="counter", bits=["row_stars_lo", "row_stars_hi"], details=dict(
            block="left_top",
            summary="stars so far in the current row: 2-bit saturating counter of I with a synchronous clear",
            direction="up", step="I", modulus=None, saturating=True, saturate_at=3, enable=EN,
            sync_clear="enable & ~cnt_done & cnt_lo == 10 (the row's last cell)")),
        dict(name="row_count_err", kind="flag", bits=["row_count_err"], details=dict(
            block="left_top",
            summary="sticky error: some row did not hold exactly 2 stars",
            set="enable & ~cnt_done & cnt_lo == 10 & (row_stars + I) != 2", clear="none (async reset only)",
            sticky=True)),
        dict(name="hist_hit", kind="flag", bits=["hist_hit"], details=dict(
            block="left_top",
            summary="sticky error: a new star touches an earlier one (king move, no wraparound)",
            set="I & enable & ~cnt_done & (tap10 | (cnt_lo != 0 & (tap0 | tap11)) | (cnt_lo != 10 & tap9))",
            clear="none (async reset only)", sticky=True)),
        dict(name="star_count", kind="counter", bits=[f"lb_bit{k}" for k in range(8)], details=dict(
            block="left_bottom",
            summary="stars entered in the sweep: 8-bit binary up-counter (ripple incrementer), counts I",
            direction="up", step=1, modulus=256, saturating=False, enable=EN_I,
            reachable=[0, 121],
            note="flop ids are not in bit order; the check compares it with 22, outgen with 0 and 121")),
        dict(name="armed", kind="flag", bits=["armed"], details=dict(
            block="check",
            summary="sticky 'decision taken' flag: the memory of cnt_done's rising-edge detector",
            set="cnt_done (next = cnt_done | armed)", clear="none (async reset only)", sticky=True,
            fanout="trigger = cnt_done & ~armed; enables pos counting and scrambler print mode; gates O")),
        dict(name="success_latch", kind="flag", bits=["success_latch"], details=dict(
            block="check",
            summary="decision latch driving the success port",
            load="on trigger (cnt_done & ~armed): pass & ~hist_hit; holds otherwise",
            sticky=False, note="loaded exactly once per reset interval (armed blocks further triggers)")),
        dict(name="alt_latch", kind="flag", bits=["alt_latch"], details=dict(
            block="check",
            summary="decision latch for 'rules met but stars touch' (selects the TWO NOT TOUCH message)",
            load="on trigger (cnt_done & ~armed): pass & hist_hit; holds otherwise",
            sticky=False, note="loaded exactly once per reset interval")),
        dict(name="scrambler", kind="lfsr_crc", bits=[f"scr_bit{k}" for k in range(8)], details=dict(
            block="outgen",
            summary="8-bit Fibonacci LFSR, primitive polynomial x^8+x^4+x^3+x^2+1, with the serial input I "
                    "XORed into the feedback; in print mode it advances 8 steps per cycle as a keystream "
                    "generator for the success message",
            taps=list(LFSR_TAPS), serial_in="I", gf2_linear=True)),
        dict(name="pos", kind="counter", bits=["pos2", "pos0", "pos1", "pos3"], details=dict(
            block="outgen",
            summary="print position: 4-bit binary up-counter, saturating at 15, synchronous clear while ~armed",
            direction="up", step=1, modulus=None, saturating=True, saturate_at=15,
            enable="armed (counts every cycle)", sync_clear="~armed (next = 0)",
            note="the RTL calls it a permutation FSM (0,4,1,5,2,6,3,7,8,12,...) over the raw flops "
                 "{pos3,pos2,pos1,pos0} = {f88,f89,f90,f91}; that is this counter with its bits permuted: "
                 "count bits 0..3 = f89, f91, f90, f88. The message ROM is addressed by the raw flops.")),
    ]
    return regs


REGISTERS = _registers()

# Parameters (schema.PARAMS), stated by hand; bit orders are the `bits` lists above, turned into
# join keys when the file is written. verified_by names the checks below that cover them.
C_UP = dict(direction="up", step=1, load=False)
STATED_PARAMS = {
    "cnt_lo": (dict(C_UP, modulus=11, saturating=False), ["C1", "C2", "C3"]),
    "cnt_hi": (dict(C_UP, modulus=11, saturating=False), ["C1", "C2", "C3"]),
    **{f"bin{k:02d}": (dict(C_UP, modulus=None, saturating=True), ["A1", "A3"]) for k in range(22)},
    "row_stars": (dict(C_UP, modulus=None, saturating=True), ["L2", "L3"]),
    "star_count": (dict(C_UP, modulus=256, saturating=False), ["B1", "B2"]),
    "pos": (dict(C_UP, modulus=None, saturating=True), ["G1", "G2"]),
    "shift_taps": (dict(lanes=1, depth=12, direction="to_msb", serial_in=["port:I"]), ["L1", "L3"]),
    # lfsr_crc (schema.py): k_steps = LFSR steps per clock in the main (data) update mode, n_inputs = data
    # bits entering per step; the other modes go to provenance.other_modes (OTHER_MODES)
    "scrambler": (dict(form="fibonacci", poly=0x11D, k_steps=1, n_inputs=1), ["G3", "G4", "G5"]),
}
OTHER_MODES = {
    "scrambler": [
        {"mode": "print", "when": "~(enable & ~cnt_done) & armed & pos != 15", "k_steps": 8, "n_inputs": 0,
         "next": "s' = M^8 s (eight zero-input LFSR steps per clock; check G4)"},
        {"mode": "hold", "when": "otherwise", "k_steps": 0, "n_inputs": 0}],
}
PARAMS_NOTES = {
    "bins": "saturate at 3 (bounds 0..3); the enable is a decode of the cycle counter (details.decode)",
    "row_stars": "adds I (step 1 when I = 1), saturates at 3, synchronous clear at the row's last cell",
    "pos": "saturates at 15; synchronous clear while ~armed (a constant, not a load)",
    "scrambler": "poly is the characteristic polynomial as an integer (bit j = coefficient of x^j): 0x11D = "
                 "x^8+x^4+x^3+x^2+1; the main (data) mode is shift mode: 1 LFSR step per clock with the serial "
                 "input I (k_steps = 1, n_inputs = 1); print mode (M^8 per clock, no input) is in "
                 "provenance.other_modes. Truth/2 before 2026-09-22 said k_steps = 8 (print mode) with n_inputs = 1 "
                 "(shift mode), mixing two modes",
}

# alternative kinds a structural recognizer may fairly report (alt_kinds only widen what a match
# accepts; they never remove a register from a denominator, schema.py)
ALT_KINDS = {
    "scrambler": (["shift_register"], "Fibonacci form: in shift mode stages 1..7 copy their predecessor and only "
                                      "stage 0 takes the XOR feedback (with I), so it also reads as an 8-stage shift "
                                      "register whose serial input is its own parity; print mode (8 steps per cycle) "
                                      "is not a shift"),
    **{n: (["fsm_state"], "one of the three flops of the one-shot decision control (armed is the memory of "
                          "cnt_done's rising-edge detector, the latches load once on its trigger); see the unit "
                          "'decision control'") for n in ("armed", "success_latch", "alt_latch")},
}
# alternatives an earlier truth/2 accepted and the 2026-09-22 truth review removed; kept as history
# in provenance.alt_kinds_removed (never scored)
_REVIEW = "truth review of 2026-09-22 (docs/S3_DESIGN.md section 4.1)"
ALT_KINDS_REMOVED = {
    "pos": (["fsm_state"],
            "read over its raw flops {f88,f89,f90,f91} it walks the permutation 0,4,1,5,2,6,3,7,8,... and the "
            "recovered RTL first called it a permutation FSM; it is a saturating binary counter with permuted bit "
            "wiring",
            f"{_REVIEW}: commit 7580322 corrected the RTL to a saturating binary counter (check G1); its permuted "
            "wiring is exactly the bit-order test S3 scores, so a non-structure alternative is not justified"),
    "cnt_done": (["counter"],
                 "the sweep's terminal-count bit: with cnt_lo and cnt_hi it forms the 9-flop state of a one-shot "
                 "mod-121 counter (unit 'cycle counter with its terminal flag')",
                 f"{_REVIEW}: the 9-flop unit already covers cnt_done without crediting it; the alternative only let "
                 "a 1-flop 'counter' on cnt_done count as correct"),
    **{f"bin{k:02d}": (["register_file_word"],
                       "the 22 bins are written through a decode of the cycle counter (row, column), like the words "
                       "of a register file of counters",
                       f"{_REVIEW}: each bin has its own hit decode and its own saturating-increment logic "
                       "(rtl_recovered/array.v); no shared write data, index or read port, so not a register file")
       for k in range(22)},
}

# declared lenient alternative units (never the rec_* blocks as such)
UNITS = [
    ("cycle counter (cnt_lo + cnt_hi)", "counter", ["cnt_lo", "cnt_hi"],
     "rtl_recovered/counter.v: one mod-121 sweep counter written as two cascaded base-11 digits (cnt_hi counts "
     "cnt_lo's carries); a recognizer may report the 8 flops as one counter",
     dict(direction="up", step=1, modulus=121, saturating=False, load=False, bit_order=None), ["C2", "C3"]),
    ("cycle counter with its terminal flag (cnt_lo + cnt_hi + cnt_done)", "counter", ["cnt_lo", "cnt_hi", "cnt_done"],
     "the 9-flop support SCC of the sweep: the 121st count sets cnt_done, which freezes the digits at 0 (a one-shot "
     "sweep that stays in its terminal state)",
     dict(direction="up", step=1, modulus=None, saturating=True, load=False, bit_order=None), ["C2", "C3"]),
    ("decision control (armed + success_latch + alt_latch)", "fsm_state", ["armed", "success_latch", "alt_latch"],
     "rtl_recovered/check.v: a 3-flop one-shot state machine: idle until cnt_done rises, then decided once "
     "(success, touching, or fail with both latches 0)", {}, ["K1"]),
]
BLOCK_MODULE = {"counter": "rec_counter", "array": "rec_array", "left_top": "rec_left_top",
                "left_bottom": "rec_left_bottom", "check": "rec_check", "outgen": "rec_outgen"}


# ----------------------------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------------------------

def load_blocks():
    with open(P(BLOCKS)) as f:
        return json.load(f)["flops"]


_REG_RE = re.compile(r"^\s*reg\s+(\w+);\s*//\s*(f\d\d),\s*(reset 0|reset 1|no reset)\s*\((\w+)\)", re.M)
_CONN_RE = re.compile(r"\.([qd])_(f\d\d)\((\w+)\)")


def load_rtl_names():
    """fNN -> (reg name, reset text, cell tag) from puzzle_recovered.v, plus the port-map pairs."""
    text = open(P(TOP)).read()
    tags = {}
    for name, f, reset, cell in _REG_RE.findall(text):
        if f in tags:
            raise SystemExit(f"{TOP}: {f} tagged twice")
        tags[f] = (name, reset, cell)
    conns = _CONN_RE.findall(text)
    return tags, conns


def sha256(path):
    with open(P(path), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def solution_bits():
    text = open(P(SOLUTION_DOC)).read()
    found = re.findall(r"^([01]{121})$", text, re.M)
    if len(found) != 1:
        raise SystemExit(f"{SOLUTION_DOC}: expected exactly one 121-bit I string, found {len(found)}")
    return found[0]


# ----------------------------------------------------------------------------------------
# Check bookkeeping
# ----------------------------------------------------------------------------------------

class Checks:
    def __init__(self):
        self.items = []
        self.failed = []

    def add(self, cid, what, ok, **numbers):
        self.items.append({"id": cid, "what": what, "result": "pass" if ok else "FAIL", **numbers})
        if not ok:
            self.failed.append(cid)
        extra = " ".join(f"{k}={v}" for k, v in numbers.items())
        print(f"[{'pass' if ok else 'FAIL'}] {cid}: {what}" + (f" ({extra})" if extra else ""), flush=True)
        return ok


# ----------------------------------------------------------------------------------------
# Icarus harness
# ----------------------------------------------------------------------------------------

class Sim:
    def __init__(self, work):
        self.work = work
        os.makedirs(work, exist_ok=True)

    def _run(self, tag, tb, files, defines=()):
        tbp = os.path.join(self.work, f"tb_{tag}.v")
        with open(tbp, "w") as f:
            f.write(tb)
        vvp = os.path.join(self.work, f"tb_{tag}.vvp")
        r = subprocess.run([f"{BIN}/iverilog", "-g2012", *defines, "-o", vvp, tbp, *files],
                           capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"iverilog failed for {tag}:\n{r.stderr[-3000:]}")
        r = subprocess.run([f"{BIN}/vvp", "-n", vvp], capture_output=True, text=True, cwd=self.work)
        if r.returncode:
            raise SystemExit(f"vvp failed for {tag}:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")

    def comb(self, tag, block, module, inputs, outputs, vectors):
        """Evaluate a combinational rec_* module. inputs: scalar port names; outputs: [(name, width)];
        vectors: dicts port -> 0/1 (missing ports are 0). Returns dicts name -> int (None on x/z)."""
        n, nv = len(inputs), len(vectors)
        mem = os.path.join(self.work, f"vec_{tag}.mem")
        with open(mem, "w") as f:
            for v in vectors:
                f.write("".join("1" if v.get(p, 0) else "0" for p in reversed(inputs)) + "\n")
        res = os.path.join(self.work, f"res_{tag}.txt")
        lines = ["`timescale 1ns/1ps", "module tb;", f"  reg [{n - 1}:0] mem [0:{nv - 1}];",
                 f"  reg [{n - 1}:0] v;", "  integer i, fd;"]
        for name, w in outputs:
            lines.append(f"  wire {'[%d:0] ' % (w - 1) if w > 1 else ''}{name};")
        conns = [f".{p}(v[{i}])" for i, p in enumerate(inputs)] + [f".{name}({name})" for name, _ in outputs]
        lines.append(f"  {module} dut({', '.join(conns)});")
        fmt = " ".join(["%b"] * len(outputs))
        lines += ["  initial begin", f'    $readmemb("{mem}", mem);', f'    fd = $fopen("{res}", "w");',
                  f"    for (i = 0; i < {nv}; i = i + 1) begin", "      v = mem[i]; #1;",
                  f'      $fdisplay(fd, "{fmt}", {", ".join(name for name, _ in outputs)});', "    end",
                  "    $fclose(fd); $finish;", "  end", "endmodule"]
        self._run(tag, "\n".join(lines) + "\n", [P(block)])
        out = []
        with open(res) as f:
            for line in f:
                toks = line.split()
                out.append({name: (int(t, 2) if set(t) <= {"0", "1"} else None)
                            for (name, _w), t in zip(outputs, toks)})
        if len(out) != nv:
            raise SystemExit(f"{tag}: {len(out)} results for {nv} vectors")
        return out

    def seq(self, tag, files, module, probes, stim, defines=()):
        """Clock a puzzle-shaped module through stim [(rst_n, enable, I)]; after each rising edge
        record the probes (hierarchical names under dut), O and success."""
        mem = os.path.join(self.work, f"stim_{tag}.mem")
        with open(mem, "w") as f:
            for r, e, i in stim:
                f.write(f"{r}{e}{i}\n")
        res = os.path.join(self.work, f"trace_{tag}.txt")
        fmt = " ".join(["%b"] * (len(probes) + 2))
        args = ", ".join([f"dut.{p}" for p in probes] + ["O", "success"])
        tb = "\n".join([
            "`timescale 1ns/1ps", "module tb;",
            "  reg clk = 0, rst_n = 1, enable = 0, I = 0;", "  wire [7:0] O; wire success;",
            f"  reg [2:0] stim [0:{len(stim) - 1}];", "  integer i, fd;",
            f"  {module} dut(.clk(clk), .rst_n(rst_n), .enable(enable), .I(I), .O(O), .success(success));",
            "  initial begin", f'    $readmemb("{mem}", stim);', f'    fd = $fopen("{res}", "w");',
            "    #1;  // stim[0] drops rst_n here: a real negedge, so the async reset fires before the first edge",
            f"    for (i = 0; i < {len(stim)}; i = i + 1) begin",
            "      {rst_n, enable, I} = stim[i];", "      #5 clk = 1;",
            f'      #1 $fdisplay(fd, "{fmt}", {args});', "      #4 clk = 0;", "    end",
            "    $fclose(fd); $finish;", "  end", "endmodule"]) + "\n"
        self._run(tag, tb, files, defines)
        rows = []
        with open(res) as f:
            for line in f:
                rows.append(line.split())
        if len(rows) != len(stim):
            raise SystemExit(f"{tag}: {len(rows)} trace rows for {len(stim)} cycles")
        return rows


# ----------------------------------------------------------------------------------------
# Register helpers
# ----------------------------------------------------------------------------------------

class Truth:
    def __init__(self, tags):
        self.name_to_fid = {v[0]: f for f, v in tags.items()}
        self.fid_to_name = {f: v[0] for f, v in tags.items()}
        self.regs = {r["name"]: r for r in REGISTERS}
        self.fids = {r["name"]: [self.name_to_fid[b] for b in r["bits"]] for r in REGISTERS}

    def put(self, v, reg, value, prefix="q_"):
        for i, f in enumerate(self.fids[reg]):
            v[prefix + f] = (value >> i) & 1
        return v

    def get(self, res, reg, prefix="d_"):
        val = 0
        for i, f in enumerate(self.fids[reg]):
            b = res[prefix + f]
            if b is None:
                return None
            val |= b << i
        return val


def all_vectors(ports, base=None):
    base = base or {}
    for k in range(1 << len(ports)):
        v = dict(base)
        for i, p in enumerate(ports):
            v[p] = (k >> i) & 1
        yield v


def derive_order(orbit, flops):
    """orbit[k] = {flop: bit} after k increments from 0. The state after 2^i increments must be
    one-hot; its flop is bit i. Returns the flops in weight order (unique by construction), or None."""
    order = []
    i = 0
    while (1 << i) < len(orbit) and len(order) < len(flops):
        ones = [f for f in flops if orbit[1 << i][f]]
        if len(ones) != 1:
            return None
        order.append(ones[0])
        i += 1
    return order if len(order) == len(flops) else None


def parity(x):
    return bin(x).count("1") & 1


def lfsr_step(s, i, taps=None):
    mask = sum(1 << t for t in (LFSR_TAPS if taps is None else taps))
    return ((s << 1) & 0xFF) | (parity(s & mask) ^ i)


def lfsr_steps(s, k):
    for _ in range(k):
        s = lfsr_step(s, 0)
    return s


def gf2_mulmod(a, b, p):
    deg = p.bit_length() - 1
    r = 0
    while b:
        if b & 1:
            r ^= a
        b >>= 1
        a <<= 1
        if (a >> deg) & 1:
            a ^= p
    return r


def gf2_powmod(a, e, p):
    r = 1
    while e:
        if e & 1:
            r = gf2_mulmod(r, a, p)
        a = gf2_mulmod(a, a, p)
        e >>= 1
    return r


def x_order(p):
    """Multiplicative order of x modulo p (None if x is not invertible or order > 2^deg - 1)."""
    n = (1 << (p.bit_length() - 1)) - 1
    if gf2_powmod(2, n, p) != 1:
        return None
    order = n
    for q in (d for d in range(2, n + 1) if n % d == 0 and all(d % e for e in range(2, d))):
        while order % q == 0 and gf2_powmod(2, order // q, p) == 1:
            order //= q
    return order


def berlekamp_massey(seq):
    c, b, L, m = [1], [1], 0, 1
    for n in range(len(seq)):
        d = seq[n]
        for i in range(1, L + 1):
            d ^= c[i] & seq[n - i]
        if d == 0:
            m += 1
            continue
        t = c[:]
        c = c + [0] * max(0, len(b) + m - len(c))
        for i, bi in enumerate(b):
            c[i + m] ^= bi
        if 2 * L <= n:
            L, b, m = n + 1 - L, t, 1
        else:
            m += 1
    return L, sum(ci << i for i, ci in enumerate(c[:L + 1]))


def poly_str(p):
    terms = []
    for k in range(p.bit_length() - 1, -1, -1):
        if (p >> k) & 1:
            terms.append("1" if k == 0 else "x" if k == 1 else f"x^{k}")
    return "+".join(terms)


# ----------------------------------------------------------------------------------------
# Checks 1-2: extraction and names
# ----------------------------------------------------------------------------------------

def check_extraction(checks, blocks, work):
    from tools.retrace.extract import Extraction
    from tools.retrace.lef import read_lef

    lef = read_lef(P(LEF))
    ex = Extraction(P(GDS), lef, top="puzzle")
    j = ex.to_json()
    pinnet = {}
    for net in j["nets"]:
        for inst, pin in net["pins"]:
            pinnet[(inst, pin)] = net["name"]
    seq = {i["name"]: i["master"] for i in j["instances"]
           if re.match(r"sky130_fd_sc_hd__(df|edf|sdf|dlx|dlr|dlclkp|sdlclkp)", i["master"])}
    ours = {v["instance"]: v["master"] for v in blocks.values()}
    checks.add("X1", "fresh extraction has exactly the 92 sequential cells of blocks.json, same masters",
               seq == ours and len(ours) == 92, sequential_cells=len(seq),
               logic_instances=j["summary"]["logic_instances"])
    bad = []
    qnet = {}
    for f, v in blocks.items():
        inst = v["instance"]
        want = {"Q": v["Q_net"], "D": v["D_net"], "CLK": v["clk_net"]}
        if "dfrtp" in v["master"]:
            want["RESET_B"] = v["reset_net"]
        elif "dfstp" in v["master"]:
            want["SET_B"] = v["reset_net"]
        for pin, net in want.items():
            if pinnet.get((inst, pin)) != net:
                bad.append((f, pin, pinnet.get((inst, pin)), net))
        qnet[f] = pinnet.get((inst, "Q"))
    checks.add("X2", "each flop's Q, D, CLK and RESET_B/SET_B nets in the fresh extraction match blocks.json",
               not bad, pins_checked=sum(4 if "dfxtp" not in v["master"] else 3 for v in blocks.values()),
               mismatches=len(bad))
    dirs = {p: "input" for p in ("clk", "rst_n", "enable", "I")} | {"O": "output", "success": "output"}
    netlist = os.path.join(work, "puzzle_extracted.v")
    with open(netlist, "w") as f:
        f.write(ex.to_verilog(dirs, lef))
    return qnet, netlist, j["summary"]


def check_names(checks, blocks, tags, conns):
    reset_of = {"sky130_fd_sc_hd__dfrtp_2": ("reset 0", "dfrtp"), "sky130_fd_sc_hd__dfstp_2": ("reset 1", "dfstp"),
                "sky130_fd_sc_hd__dfxtp_2": ("no reset", "dfxtp")}
    ok = set(tags) == set(blocks) and len({t[0] for t in tags.values()}) == 92
    ok = ok and all(reset_of[blocks[f]["master"]] == tags[f][1:] for f in blocks)
    checks.add("N1", "puzzle_recovered.v tags every flop once with the reset its blocks.json master implies",
               ok, tagged=len(tags))
    bad = 0
    for kind, f, sig in conns:
        name = tags[f][0]
        if sig != (name if kind == "q" else f"next_{name}"):
            bad += 1
    d_seen = {f for kind, f, _ in conns if kind == "d"}
    checks.add("N2", "the rec_* port map binds q_fNN to the tagged register and d_fNN to its next_ wire",
               bad == 0 and d_seen == set(blocks), connections=len(conns), mismatches=bad)
    names = [b for r in REGISTERS for b in r["bits"]]
    checks.add("N3", "the registers below partition the 92 flops (every RTL register bit used exactly once)",
               sorted(names) == sorted(t[0] for t in tags.values()) and len(names) == 92, bits=len(names))


# ----------------------------------------------------------------------------------------
# Check 3: next-state functions, block by block
# ----------------------------------------------------------------------------------------

def check_counter(sim, checks, T):
    ins = ["enable"] + [f"q_{fid(n)}" for n in range(9)]
    outs = [(f"d_{fid(n)}", 1) for n in range(9)]
    vecs = list(all_vectors(ins))
    res = sim.comb("counter", BLOCK_FILES["counter"], "rec_counter", ins, outs, vecs)
    table = {tuple(v[p] for p in ins[1:]): r for v, r in zip(vecs, res) if v["enable"]}
    # trajectory from reset with enable held
    state = tuple(0 for _ in range(9))
    traj = [state]
    for _ in range(125):
        r = table[state]
        state = tuple(r[f"d_{fid(n)}"] for n in range(9))
        traj.append(state)
    as_dict = [{fid(n): s[n] for n in range(9)} for s in traj]
    lo_order = derive_order(as_dict[:12], T.fids["cnt_lo"])
    hi_order = derive_order([as_dict[11 * k] for k in range(12)], T.fids["cnt_hi"])
    done_at = next(k for k, s in enumerate(as_dict) if s[T.fids["cnt_done"][0]])
    checks.add("C1", "cycle counter bit orders derived from its orbit: cnt_lo = f06,f05,f04,f07 and "
               "cnt_hi = f00,f02,f03,f01 (LSB first), unique",
               lo_order == T.fids["cnt_lo"] and hi_order == T.fids["cnt_hi"],
               derived_lo=",".join(lo_order or []), derived_hi=",".join(hi_order or []))
    lo_seq = [sum(s[f] << i for i, f in enumerate(T.fids["cnt_lo"])) for s in as_dict]
    hi_seq = [sum(s[f] << i for i, f in enumerate(T.fids["cnt_hi"])) for s in as_dict]
    lo_mod = lo_seq[1:].index(0) + 1
    hi_mod = [hi_seq[11 * k] for k in range(1, 12)].index(0) + 1
    ok = all(lo_seq[k] == k % 11 and hi_seq[k] == k // 11 for k in range(121))
    ok = ok and done_at == 121 and lo_seq[121] == 0 and hi_seq[121] == 0 and all(
        as_dict[k] == as_dict[121] for k in range(121, len(as_dict)))
    checks.add("C2", "from reset with enable held: enabled cycle k presents (cnt_hi, cnt_lo) = (k // 11, k % 11), "
               "k = 0..120; cnt_done rises after the 121st and the counter freezes at 0",
               ok and lo_mod == 11 and hi_mod == 11, modulus_lo=lo_mod, modulus_hi=hi_mod, done_after=done_at)
    bad = 0
    unreach = {}
    for v, r in zip(vecs, res):
        lo, hi, done = T.get(v, "cnt_lo", "q_"), T.get(v, "cnt_hi", "q_"), v["q_f08"]
        if not v["enable"] or done:
            want = (lo, hi, done)
        else:
            lo2 = 0 if lo == 10 else (lo + 1) & 15
            hi2 = ((0 if hi == 10 else (hi + 1) & 15) if lo == 10 else hi)
            want = (lo2, hi2, int(lo == 10 and hi == 10))
            if lo > 10 and hi == 0:
                unreach[lo] = lo2
        if (T.get(r, "cnt_lo"), T.get(r, "cnt_hi"), r["d_f08"]) != want:
            bad += 1
    checks.add("C3", "rec_counter exhaustively: holds unless enable & ~cnt_done; cnt_lo' = cnt_lo == 10 ? 0 : "
               "cnt_lo + 1; cnt_hi' = carry ? (cnt_hi == 10 ? 0 : cnt_hi + 1) : cnt_hi; cnt_done' |= both == 10",
               bad == 0, vectors=len(vecs), mismatches=bad)
    return {"lo_unreachable": {str(k): v for k, v in sorted(unreach.items())}}


def check_left_bottom(sim, checks, T):
    lb = [fid(n) for n in range(69, 77)]
    ins = ["I", "enable", "q_f08"] + [f"q_{f}" for f in lb]
    outs = [(f"d_{f}", 1) for f in lb]
    vecs = list(all_vectors(ins))
    res = sim.comb("left_bottom", BLOCK_FILES["left_bottom"], "rec_left_bottom", ins, outs, vecs)
    table = {tuple(v[f"q_{f}"] for f in lb): r for v, r in zip(vecs, res) if v["I"] and v["enable"] and not v["q_f08"]}
    state = (0,) * 8
    orbit = []
    for _ in range(257):
        orbit.append(dict(zip(lb, state)))
        r = table[state]
        state = tuple(r[f"d_{f}"] for f in lb)
    order = derive_order(orbit, lb)
    checks.add("B1", "star_count bit order derived from its orbit: f75,f70,f72,f74,f69,f71,f73,f76 (LSB first), unique",
               order == T.fids["star_count"], derived=",".join(order or []))
    period = [k for k in range(1, 257) if orbit[k] == orbit[0]][0]
    bad = 0
    for v, r in zip(vecs, res):
        val = T.get(v, "star_count", "q_")
        want = (val + (v["I"] & v["enable"] & (1 - v["q_f08"]))) & 255
        bad += T.get(r, "star_count") != want
    checks.add("B2", "rec_left_bottom exhaustively: star_count' = star_count + (I & enable & ~cnt_done) mod 256",
               bad == 0 and period == 256, vectors=len(vecs), mismatches=bad, period=period)


def check_array(sim, checks, T):
    ctr = [f"q_{fid(n)}" for n in range(9)]
    binf = [fid(n) for n in range(9, 53)]
    ins = ["I", "enable"] + ctr + [f"q_{f}" for f in binf]
    outs = [(f"d_{f}", 1) for f in binf]
    base = list(all_vectors(["I", "enable"] + ctr))
    key = lambda v: tuple(v[p] for p in ["I", "enable"] + ctr)  # noqa: E731
    pairs = {k: set(T.fids[f"bin{k:02d}"]) for k in range(22)}
    # step 0: all bins at raw 0 -> which vectors fire each bin, and which flop sets first
    patterns = {k: {f: 0 for f in pairs[k]} for k in range(22)}
    orbit = {k: [dict(patterns[k])] for k in range(22)}
    hits = None
    consistent = True
    for step in range(4):
        vecs = []
        for b in base:
            v = dict(b)
            for k in range(22):
                for f, bit in patterns[k].items():
                    v[f"q_{f}"] = bit
            vecs.append(v)
        res = sim.comb(f"array_s{step}", BLOCK_FILES["array"], "rec_array", ins, outs, vecs)
        step_hits = {}
        nxt = {}
        for k in range(22):
            fired = set()
            for v, r in zip(vecs, res):
                new = {f: r[f"d_{f}"] for f in pairs[k]}
                if new != patterns[k]:
                    fired.add(key(v))
                    if k in nxt and nxt[k] != new:
                        consistent = False
                    nxt[k] = new
                # flops outside the pair never change here: checked by the random pass below
            step_hits[k] = fired
        if step < 3:
            if hits is None:
                hits = step_hits
            elif step_hits != hits:
                consistent = False
            for k in range(22):
                patterns[k] = nxt.get(k, patterns[k])
                orbit[k].append(dict(patterns[k]))
        else:  # saturated: nothing may change
            consistent = consistent and all(not s for s in step_hits.values())
            for k in range(22):
                orbit[k].append(dict(patterns[k]))
    orders_ok = all(derive_order(orbit[k], sorted(pairs[k])) == T.fids[f"bin{k:02d}"] for k in range(22))
    sat_ok = all(orbit[k][3] == {f: 1 for f in pairs[k]} and orbit[k][4] == orbit[k][3] for k in range(22))
    checks.add("A1", "each of the 22 bins, stepped through its orbit from 0: 0 -> lsb -> msb -> both -> both "
               "(2-bit saturating up-counter, lsb/msb as stated), with a decode independent of the bin's state",
               orders_ok and sat_ok and consistent, bins=22, vectors=4 * len(base))
    # which bins fire at each reachable grid cell
    ctr_hits = {k: {h[2:] for h in hits[k]} for k in range(22)}  # drop I, enable
    gate_ok = all(h[0] == 1 and h[1] == 1 and h[2 + 8] == 0 for k in range(22) for h in hits[k])
    region, colbin = {}, {}
    one_hot = True
    for row in range(11):
        for col in range(11):
            v = T.put(T.put({}, "cnt_hi", row), "cnt_lo", col)
            k9 = tuple(v.get(p, 0) for p in ctr)
            a = [k for k in GROUP_A if k9 in ctr_hits[k]]
            b = [k for k in GROUP_B if k9 in ctr_hits[k]]
            one_hot = one_hot and len(a) == 1 and len(b) == 1
            if a:
                region[(row, col)] = a[0]
            if b:
                if colbin.get(col, b[0]) != b[0]:
                    one_hot = False
                colbin[col] = b[0]
    all256 = sum(1 for k8 in range(256)
                 if sum(tuple((k8 >> i) & 1 for i in range(8)) + (0,) in ctr_hits[k] for k in GROUP_A) == 1)
    checks.add("A2", "every bin fires only when I & enable & ~cnt_done; on each of the 121 reachable (row, column) "
               "states exactly one region bin (0-10) and exactly one column bin (11-21) fires",
               gate_ok and one_hot and len(set(colbin.values())) == 11, cells=121,
               region_decode_one_hot_over_all_256=all256)
    # random mixed states: other bins' states never matter
    rng = random.Random(3)
    vecs = []
    for _ in range(3000):
        v = {p: rng.getrandbits(1) for p in ins}
        vecs.append(v)
    res = sim.comb("array_rand", BLOCK_FILES["array"], "rec_array", ins, outs, vecs)
    bad = 0
    for v, r in zip(vecs, res):
        for k in range(22):
            cur = T.get(v, f"bin{k:02d}", "q_")
            want = min(3, cur + (key(v) in hits[k]))
            bad += T.get(r, f"bin{k:02d}") != want
    checks.add("A3", "3000 random states of all 55 inputs: bin' = min(3, bin + hit) for all 22 bins",
               bad == 0, vectors=len(vecs), mismatches=bad)
    return region, colbin, all256


def check_left_top(sim, checks, T):
    tapf = T.fids["shift_taps"]
    lo_f = T.fids["cnt_lo"]
    ins = ["I", "enable"] + [f"q_{fid(n)}" for n in range(4, 9)] + [f"q_{fid(n)}" for n in range(53, 69)]
    outs = [(f"d_{fid(n)}", 1) for n in range(53, 69)]
    own = [fid(n) for n in range(53, 69)]
    # chain derivation: shift enabled, a single 1 at I or at one flop
    vecs, probes = [], []
    for lo in (0, 3, 10):
        for src in ["I"] + own:
            v = T.put({"enable": 1, "q_f08": 0}, "cnt_lo", lo)
            v["I" if src == "I" else f"q_{src}"] = 1
            vecs.append(v)
            probes.append((lo, src))
    res = sim.comb("left_top_chain", BLOCK_FILES["left_top"], "rec_left_top", ins, outs, vecs)
    succ = {}
    for (lo, src), r in zip(probes, res):
        ones = tuple(f for f in tapf if r[f"d_{f}"])
        succ.setdefault(src, set()).add(ones)
    chain, cur, ok = [], "I", True
    while True:
        nxt = succ.get(cur, {()})
        if len(nxt) != 1:
            ok = False
            break
        (ones,) = nxt
        if not ones:
            break
        if len(ones) != 1 or ones[0] in chain:
            ok = False
            break
        chain.append(ones[0])
        cur = ones[0]
    checks.add("L1", "shift chain derived from single-1 probes with shift enabled: I -> f67 -> f66 -> f68 -> f63 -> "
               "f60 -> f58 -> f61 -> f56 -> f57 -> f59 -> f62 -> f65 (index 0..11), last stage feeds no stage",
               ok and chain == tapf, derived=",".join(chain))
    # row_stars orbit
    rs_f = T.fids["row_stars"]
    state = {f: 0 for f in rs_f}
    orbit = [dict(state)]
    for step in range(4):
        v = T.put({"enable": 1, "q_f08": 0, "I": 1}, "cnt_lo", 0)
        for f, b in state.items():
            v[f"q_{f}"] = b
        r = sim.comb(f"left_top_rs{step}", BLOCK_FILES["left_top"], "rec_left_top", ins, outs, [v])[0]
        state = {f: r[f"d_{f}"] for f in rs_f}
        orbit.append(dict(state))
    checks.add("L2", "row_stars orbit under I = 1: 0 -> f55 -> f54 -> both -> both (2-bit saturating, f55 = LSB)",
               derive_order(orbit, sorted(rs_f)) == rs_f and orbit[3] == orbit[4] == {f: 1 for f in rs_f})
    # exhaustive over the support of row_stars/row_count_err/hist_hit, other taps random
    sup = ["I", "enable", "q_f08"] + [f"q_{f}" for f in lo_f] + [
        "q_" + T.fids[n][0] for n in ("row_count_err", "hist_hit")] + [f"q_{f}" for f in rs_f] + [
        f"q_{tapf[k]}" for k in (0, 9, 10, 11)]
    rng = random.Random(5)
    vecs = []
    for v in all_vectors(sup):
        for p in ins:
            if p not in v:
                v[p] = rng.getrandbits(1)
        vecs.append(v)
    for _ in range(4000):
        vecs.append({p: rng.getrandbits(1) for p in ins})
    res = sim.comb("left_top_all", BLOCK_FILES["left_top"], "rec_left_top", ins, outs, vecs)
    bad = 0
    for v, r in zip(vecs, res):
        i, sh = v["I"], v["enable"] & (1 - v["q_f08"])
        lo = T.get(v, "cnt_lo", "q_")
        taps = T.get(v, "shift_taps", "q_")
        rs = T.get(v, "row_stars", "q_")
        err, hit = T.get(v, "row_count_err", "q_"), T.get(v, "hist_hit", "q_")
        tap = lambda k: (taps >> k) & 1  # noqa: E731
        taps2 = ((taps << 1) | i) & 0xFFF if sh else taps
        if sh:
            rs2 = 0 if lo == 10 else min(3, rs + i)
            err2 = err | int(lo == 10 and rs + i != 2)
            hit2 = hit | (i & (tap(10) | ((lo != 0) & (tap(0) | tap(11))) | ((lo != 10) & tap(9))))
        else:
            rs2, err2, hit2 = rs, err, hit
        got = (T.get(r, "shift_taps"), T.get(r, "row_stars"), T.get(r, "row_count_err"), T.get(r, "hist_hit"))
        bad += got != (taps2, rs2, err2, hit2)
    checks.add("L3", "rec_left_top, exhaustive over the 15-bit support of row_stars/row_count_err/hist_hit (other "
               "taps random) plus 4000 random vectors: shift, row_stars, row_count_err and hist_hit as stated",
               bad == 0, vectors=len(vecs), mismatches=bad)


def check_check(sim, checks, T):
    ins = ["q_f08"] + [f"q_{fid(n)}" for n in range(9, 53)] + ["q_f53", "q_f64"] + [
        f"q_{fid(n)}" for n in range(69, 80)]
    outs = [("d_f77", 1), ("d_f78", 1), ("d_f79", 1), ("success", 1)]
    bin_bits = [f for k in range(22) for f in T.fids[f"bin{k:02d}"]]
    lb_bits = T.fids["star_count"]
    rng = random.Random(7)

    def passing(hist):
        v = {p: 0 for p in ins}
        v.update({"q_f08": 1, "q_f79": 0, "q_f53": 0, "q_f64": hist,
                  "q_f77": rng.getrandbits(1), "q_f78": rng.getrandbits(1)})
        for k in range(22):
            T.put(v, f"bin{k:02d}", 2)
        return T.put(v, "star_count", 22)

    vecs, want = [], []
    for hist in (0, 1):
        vecs.append(passing(hist))
        want.append((hist, 1 - hist))
        for f in bin_bits + lb_bits:
            v = passing(hist)
            v[f"q_{f}"] ^= 1
            vecs.append(v)
            want.append((0, 0))
        v = passing(hist)
        v["q_f53"] = 1
        vecs.append(v)
        want.append((0, 0))
    n_directed = len(vecs)
    for _ in range(3000):
        v = passing(rng.getrandbits(1)) if rng.random() < 0.5 else {p: rng.getrandbits(1) for p in ins}
        for _k in range(rng.choice((0, 0, 1, 2))):
            f = rng.choice(bin_bits + lb_bits)
            v[f"q_{f}"] ^= 1
        v["q_f08"], v["q_f79"] = rng.getrandbits(1), rng.getrandbits(1)
        vecs.append(v)
        want.append(None)
    res = sim.comb("check", BLOCK_FILES["check"], "rec_check", ins, outs, vecs)
    bad = 0
    for v, r, w in zip(vecs, res, want):
        trig = v["q_f08"] & (1 - v["q_f79"])
        ok_bins = all(T.get(v, f"bin{k:02d}", "q_") == 2 for k in range(22))
        pas = trig and not v["q_f53"] and ok_bins and T.get(v, "star_count", "q_") == 22
        alt = int(pas and v["q_f64"]) if trig else v["q_f77"]
        suc = int(pas and not v["q_f64"]) if trig else v["q_f78"]
        if w is not None and (alt, suc) != w:
            bad += 1
        bad += (r["d_f77"], r["d_f78"], r["d_f79"], r["success"]) != (alt, suc, v["q_f08"] | v["q_f79"], v["q_f78"])
    checks.add("K1", "rec_check: armed' = cnt_done | armed; on trigger = cnt_done & ~armed the latches load "
               "pass & ~hist_hit / pass & hist_hit with pass = ~row_count_err & star_count == 22 & every bin == 2 "
               "(each of the 52 compared bits flipped alone fails); otherwise they hold; success = success_latch",
               bad == 0, directed=n_directed, vectors=len(vecs), mismatches=bad)


def check_outgen(sim, checks, T):
    ins = ["I", "enable", "q_f08"] + [f"q_{fid(n)}" for n in range(69, 92)]
    outs = [(f"d_{fid(n)}", 1) for n in range(80, 92)] + [("O", 8)]
    scr_f, pos_f = T.fids["scrambler"], T.fids["pos"]
    rng = random.Random(11)
    fixed = {f"q_{fid(n)}": b for n, b in zip(range(69, 77), (1, 0, 1, 0, 1, 0, 1, 0))}
    fixed.update({"q_f77": 0, "q_f78": 0})
    sup = ["I", "enable", "q_f08", "q_f79"] + [f"q_{fid(n)}" for n in range(80, 92)]
    vecs = list(all_vectors(sup, fixed))
    for _ in range(3000):
        vecs.append({p: rng.getrandbits(1) for p in ins})
    res = sim.comb("outgen_state", BLOCK_FILES["outgen"], "rec_outgen", ins, outs, vecs)
    nfull = 1 << len(sup)
    # pos: orbit from 0 while armed
    table = {}
    for v, r in zip(vecs[:nfull], res[:nfull]):
        if v["q_f79"] and not v["enable"] and not v["I"] and not v["q_f08"] and not any(v[f"q_{f}"] for f in scr_f):
            table[tuple(v[f"q_{f}"] for f in sorted(pos_f))] = r
    state = (0, 0, 0, 0)
    orbit = []
    for _ in range(17):
        orbit.append(dict(zip(sorted(pos_f), state)))
        r = table[state]
        state = tuple(r[f"d_{f}"] for f in sorted(pos_f))
    order = derive_order(orbit, sorted(pos_f))
    raw_seq = [int("".join(str(o[f]) for f in ("f88", "f89", "f90", "f91")), 2) for o in orbit]
    checks.add("G1", "pos bit order derived from its orbit while armed: f89,f91,f90,f88 (LSB first), unique; "
               "raw {f88..f91} walks 0,4,1,5,2,6,3,7,8,12,9,13,10,14,11,15 then holds",
               order == pos_f and raw_seq == [0, 4, 1, 5, 2, 6, 3, 7, 8, 12, 9, 13, 10, 14, 11, 15, 15],
               derived=",".join(order or []))
    # scrambler: shift-mode affine map, print-mode linear map, hold
    idx = {f: i for i, f in enumerate(scr_f)}

    def scr_of(d, prefix):
        return sum(d[f"{prefix}{f}"] << idx[f] for f in scr_f)

    shift_map, print_map = {}, {}
    bad_pos = bad_mode = 0
    for v, r in zip(vecs, res):
        s, i = scr_of(v, "q_"), v["I"]
        c = T.get(v, "pos", "q_")
        armed = v["q_f79"]
        c2 = min(c + 1, 15) if armed else 0
        bad_pos += T.get(r, "pos") != c2
        s2 = scr_of(r, "d_")
        sh = v["enable"] and not v["q_f08"]
        if sh:
            shift_map.setdefault((s, i), set()).add(s2)
        elif armed and c != 15:
            print_map.setdefault((s, i), set()).add(s2)
        else:
            bad_mode += s2 != s
    functional = all(len(x) == 1 for x in shift_map.values()) and all(len(x) == 1 for x in print_map.values())
    M = {k: next(iter(x)) for k, x in shift_map.items()}
    Pm = {k: next(iter(x)) for k, x in print_map.items()}
    complete = len(M) == 512 and len(Pm) == 512
    checks.add("G2", "rec_outgen, exhaustive over its 16-bit state support plus 3000 random vectors: pos' = armed ? "
               "min(pos + 1, 15) : 0; the scrambler is a function of (state, I) per mode and holds outside "
               "shift/print; nothing depends on star_count or the latches",
               bad_pos == 0 and bad_mode == 0 and functional and complete, vectors=len(vecs),
               mismatches=bad_pos + bad_mode)
    # shift mode in flop coordinates: which flop takes I, and who copies whom
    col = {f: M[(1 << idx[f], 0)] for f in scr_f}
    b = M[(0, 1)]
    linear = all(M[(s, i)] == (b if i else 0) ^ _xor_cols(col, s, idx) for (s, i) in M)
    in_flop = [f for f in scr_f if (b >> idx[f]) & 1]
    rows = {g: [f for f in scr_f if (col[f] >> idx[g]) & 1] for g in scr_f}
    chain = list(in_flop)
    while len(in_flop) == 1 and len(chain) < 9:
        nxt = [g for g in scr_f if rows[g] == [chain[-1]] and g not in chain]
        if len(nxt) != 1:
            break
        chain.append(nxt[0])
    taps = sorted(idx[f] for f in rows[in_flop[0]]) if len(in_flop) == 1 else None
    checks.add("G3", "shift mode (enable & ~cnt_done) is GF(2)-affine: s' = M s ^ I e0; I enters f87 alone, every other "
               "flop copies one neighbour, chain f87 -> f86 -> f84 -> f85 -> f82 -> f83 -> f80 -> f81 (index 0..7), "
               "feedback from index 3,4,5,7 (f85,f82,f83,f81)",
               linear and chain == scr_f and taps == list(LFSR_TAPS)
               and all(M[(s, i)] == lfsr_step(s, i) for (s, i) in M),
               derived_chain=",".join(chain), derived_taps=str(taps))
    # print mode
    pcol = {f: Pm[(1 << idx[f], 0)] for f in scr_f}
    plinear = all(Pm[(s, i)] == _xor_cols(pcol, s, idx) for (s, i) in Pm)
    ks = [k for k in range(1, 256) if all(lfsr_steps(1 << j, k) == Pm[(1 << j, 0)] for j in range(8))]
    checks.add("G4", "print mode (~shift & armed & pos != 15) is GF(2)-linear, ignores I, and equals the shift-mode "
               "LFSR advanced k steps with zero input for exactly k = 8 (k in 1..255)",
               plinear and ks == [8], k=str(ks))
    # polynomial, period
    reset = sum(1 << idx[f] for f in scr_f if T.reset_bits[f] == 1)
    seq = [(reset >> (7 - k)) & 1 for k in range(8)]
    s = reset
    for _ in range(64):
        s = lfsr_step(s, 0)
        seq.append(s & 1)
    L, conn = berlekamp_massey(seq)
    charp = int(format(conn, "09b")[::-1], 2)  # reciprocal of the connection polynomial
    order = x_order(charp)
    period, s = 1, lfsr_step(reset, 0)
    while s != reset and period <= 256:  # a non-invertible map need not return to the reset state
        s, period = lfsr_step(s, 0), period + 1
    annihilates = all(
        _poly_apply(charp, 1 << j) == 0 for j in range(8))
    checks.add("G5", "LFSR: linear complexity 8, connection polynomial 1+x^4+x^5+x^6+x^8 (0x171), characteristic "
               "polynomial x^8+x^4+x^3+x^2+1 (0x11D) annihilates M, order of x = 255 (primitive), reset state 0xA5 "
               "has period 255",
               L == 8 and conn == 0x171 and charp == 0x11D and order == 255 and period == 255 and reset == 0xA5
               and annihilates, connection=hex(conn), characteristic=hex(charp), period=period, reset=hex(reset))
    # O: messages and the O <- scrambler bit mapping
    lb_vals = {"zero": 0, "bigbang": 121, "other": 22}
    ovecs, keys = [], []
    for lbn, lbv in lb_vals.items():
        for alt, suc in ((0, 0), (1, 0), (0, 1), (1, 1)):
            for c in range(16):
                v = {p: rng.getrandbits(1) for p in ("I", "enable", "q_f08")}
                v.update({"q_f79": 1, "q_f77": alt, "q_f78": suc})
                T.put(v, "star_count", lbv)
                T.put(v, "pos", c)
                T.put(v, "scrambler", 0)
                ovecs.append(v)
                keys.append((lbn, alt, suc, c, 0))
    for j in range(8):
        for c in range(16):
            v = {"q_f79": 1, "q_f77": 0, "q_f78": 1}
            T.put(v, "star_count", 22)
            T.put(v, "pos", c)
            T.put(v, "scrambler", 1 << j)
            ovecs.append(v)
            keys.append(("other", 0, 1, c, 1 << j))
    for _ in range(400):
        v = {p: rng.getrandbits(1) for p in ins}
        ovecs.append(v)
        keys.append(None)
    ores = sim.comb("outgen_O", BLOCK_FILES["outgen"], "rec_outgen", ins, outs, ovecs)
    got = {k: r["O"] for k, r in zip(keys, ores) if k is not None}
    tables = {
        "empty": [got[("zero", 0, 0, c, 0)] for c in range(16)],
        "bigbang": [got[("bigbang", 0, 0, c, 0)] for c in range(16)],
        "success": [got[("other", 0, 1, c, 0)] for c in range(16)],
        "two": [got[("other", 1, 0, c, 0)] for c in range(16)],
        "try": [got[("other", 0, 0, c, 0)] for c in range(16)],
    }
    prio = all(got[("zero", a, s_, c, 0)] == tables["empty"][c] and got[("bigbang", a, s_, c, 0)] == tables["bigbang"][c]
               and got[("other", a, 1, c, 0)] == tables["success"][c] for a in (0, 1) for s_ in (0, 1) for c in range(16))
    xor_ok = all(got[("other", 0, 1, c, 1 << j)] == (tables["success"][c] ^ (1 << j) if c < 15 else 0)
                 for j in range(8) for c in range(16))

    def text(t):
        body = bytes(t[:15]).rstrip(b"\0")
        return body.decode("latin-1") if 0 not in body else None

    msgs_ok = all(text(tables[k]) == MESSAGES[k] for k in MESSAGES) and all(t[15] == 0 for t in tables.values())
    bad = 0
    for k, v, r in zip(keys, ovecs, ores):
        if k is None:
            bad += r["O"] != _o_model(T, v, tables)
    checks.add("G6", "O: with armed and pos = count c < 15 it prints, in count order, EMPTY SKY (star_count == 0), "
               "BIG BANG (== 121), the success table XOR the scrambler (O bit i = scrambler index i), "
               "TWO NOT TOUCH (alt_latch), else TRY AGAIN, in that priority; 0 at c = 15 or when ~armed",
               prio and xor_ok and msgs_ok and bad == 0, vectors=len(ovecs), random_mismatches=bad)
    return {"tables": tables, "shift_matrix_rows": {str(i): _rows(col, idx, i) for i in range(8)},
            "print_matrix_rows": {str(i): _rows(pcol, idx, i) for i in range(8)}, "reset": reset}


def _xor_cols(col, s, idx):
    out = 0
    for f, i in idx.items():
        if (s >> i) & 1:
            out ^= col[f]
    return out


def _rows(col, idx, i):
    """Indices j whose bit feeds index i (row i of the matrix, index coordinates)."""
    return sorted(idx[f] for f in idx if (col[f] >> i) & 1)


def _poly_apply(p, v):
    """(p(M)) v for the shift-mode matrix M with zero input."""
    acc, cur = 0, v
    for k in range(p.bit_length()):
        if (p >> k) & 1:
            acc ^= cur
        cur = lfsr_step(cur, 0)
    return acc


def _o_model(T, v, tables):
    c = T.get(v, "pos", "q_")
    if not v["q_f79"] or c == 15:
        return 0
    lb = T.get(v, "star_count", "q_")
    if lb == 0:
        return tables["empty"][c]
    if lb == 121:
        return tables["bigbang"][c]
    if v["q_f78"]:
        return tables["success"][c] ^ T.get(v, "scrambler", "q_")
    if v["q_f77"]:
        return tables["two"][c]
    return tables["try"][c]


# ----------------------------------------------------------------------------------------
# Check 4: a model written from the truth, against the RTL and the extracted netlist
# ----------------------------------------------------------------------------------------

class Model:
    def __init__(self, T, region, colbin, tables, reset_scr):
        self.T, self.region, self.colbin, self.tables, self.reset_scr = T, region, colbin, tables, reset_scr
        self.s = {r["name"]: None for r in REGISTERS}

    def reset(self):
        s = {r["name"]: 0 for r in REGISTERS}
        s["scrambler"] = self.reset_scr
        s["pos"] = 0  # no reset pin, but armed = 0 during reset loads 0 on the edge
        self.s = s

    def step(self, rst_n, en, i):
        if not rst_n:
            self.reset()
            return
        s = self.s
        n = dict(s)
        lo, hi, done = s["cnt_lo"], s["cnt_hi"], s["cnt_done"]
        sh = en and not done
        if sh:
            if lo == 10:
                n["cnt_lo"] = 0
                n["cnt_hi"] = 0 if hi == 10 else hi + 1
                n["cnt_done"] = int(hi == 10)
            else:
                n["cnt_lo"] = lo + 1
            if i:
                for k in (self.region[(hi, lo)], self.colbin[lo]):
                    n[f"bin{k:02d}"] = min(3, s[f"bin{k:02d}"] + 1)
                n["star_count"] = (s["star_count"] + 1) & 255
            t = s["shift_taps"]
            n["shift_taps"] = ((t << 1) | i) & 0xFFF
            tap = lambda k: (t >> k) & 1  # noqa: E731
            if lo == 10:
                n["row_stars"] = 0
                if s["row_stars"] + i != 2:
                    n["row_count_err"] = 1
            else:
                n["row_stars"] = min(3, s["row_stars"] + i)
            if i and (tap(10) or (lo != 0 and (tap(0) or tap(11))) or (lo != 10 and tap(9))):
                n["hist_hit"] = 1
            n["scrambler"] = lfsr_step(s["scrambler"], i)
        elif s["armed"] and s["pos"] != 15:
            n["scrambler"] = lfsr_steps(s["scrambler"], 8)
        if done and not s["armed"]:
            ok = (not s["row_count_err"] and s["star_count"] == 22
                  and all(s[f"bin{k:02d}"] == 2 for k in range(22)))
            n["success_latch"] = int(ok and not s["hist_hit"])
            n["alt_latch"] = int(ok and bool(s["hist_hit"]))
        n["armed"] = int(bool(done or s["armed"]))
        n["pos"] = min(15, s["pos"] + 1) if s["armed"] else 0
        self.s = n

    def outputs(self):
        s = self.s
        if s["armed"] is None or not s["armed"] or s["pos"] == 15:
            o = 0
        elif s["star_count"] == 0:
            o = self.tables["empty"][s["pos"]]
        elif s["star_count"] == 121:
            o = self.tables["bigbang"][s["pos"]]
        elif s["success_latch"]:
            o = self.tables["success"][s["pos"]] ^ s["scrambler"]
        elif s["alt_latch"]:
            o = self.tables["two"][s["pos"]]
        else:
            o = self.tables["try"][s["pos"]]
        return o, s["success_latch"]


def stimuli():
    rng = random.Random(2026)
    segs = []

    def grid(name, bits, tail=24):
        segs.append((name, [(0, 0, 0)] * 2 + [(1, 1, int(b)) for b in bits] + [(1, 0, 0)] * tail))

    grid("solution", solution_bits())
    grid("empty", "0" * 121)
    grid("bigbang", "1" * 121)
    grid("touching", TOUCHING)
    for k, (pe, pi) in enumerate(((0.8, 0.2), (0.6, 0.5), (0.95, 0.1), (0.9, 0.9))):
        cyc = [(0, 0, 0)] * 2
        for t in range(420):
            if k == 1 and t == 200:
                cyc += [(0, rng.getrandbits(1), rng.getrandbits(1))] * 2  # a reset mid-run
            cyc.append((1, int(rng.random() < pe), int(rng.random() < pi)))
        segs.append((f"random{k}", cyc))
    return segs


def check_sequential(sim, checks, T, qnet, netlist, region, colbin, tables, reset_scr):
    segs = stimuli()
    stim = [c for _n, cyc in segs for c in cyc]
    order = [fid(n) for n in range(92)]
    rtl = sim.seq("rtl", [P(f) for f in RTL_FILES], "puzzle_recovered", [T.fid_to_name[f] for f in order], stim)
    esc = lambda n: n if re.fullmatch(r"[A-Za-z_]\w*", n) else f"\\{n} "  # noqa: E731
    net = sim.seq("netlist", [netlist, *(P(m) for m in MODELS)], "puzzle", [esc(qnet[f]) for f in order], stim,
                  defines=("-DFUNCTIONAL", "-DUNIT_DELAY="))
    same = sum(a == b for a, b in zip(rtl, net))
    diff = next(((k, [j for j, (x, y) in enumerate(zip(a, b)) if x != y]) for k, (a, b) in enumerate(zip(rtl, net))
                 if a != b), None)
    checks.add("S1", "puzzle_recovered and the freshly extracted netlist (sky130 models, flops probed on blocks.json's "
               "Q nets) agree on all 92 flops, O and success after every edge",
               same == len(stim), cycles=len(stim), agreeing_cycles=same,
               first_difference="none" if diff is None else f"cycle {diff[0]}, columns {diff[1]}")
    model = Model(T, region, colbin, tables, reset_scr)
    pos_in_row = {f: k for k, f in enumerate(order)}
    bad_cycles = 0
    printed = {}
    k = 0
    first_bad = None
    for name, cyc in segs:
        text = []
        for r_, e_, i_ in cyc:
            if not r_ and text and text[-1] != ord("/"):
                text.append(ord("/"))  # a reset inside the stream: separate the printouts
            model.step(r_, e_, i_)
            row = rtl[k]
            k += 1
            ok = True
            for reg in REGISTERS:
                bits = [row[pos_in_row[f]] for f in T.fids[reg["name"]]]
                val = None if any(b not in "01" for b in bits) else sum(int(b) << j for j, b in enumerate(bits))
                if val != model.s[reg["name"]]:
                    ok = False
                    if first_bad is None:
                        first_bad = (name, k, reg["name"], val, model.s[reg["name"]])
            o, suc = model.outputs()
            ok = ok and row[92] == format(o, "08b") and row[93] == str(suc)
            bad_cycles += not ok
            if o:
                text.append(o)
        printed[name] = (bytes(text).decode("latin-1").strip("/"), model.s["success_latch"], model.s["alt_latch"])
    want = {"solution": ("(* TWO STARS *)", 1, 0), "empty": ("EMPTY SKY", 0, 0), "bigbang": ("BIG BANG", 0, 0),
            "touching": ("TWO NOT TOUCH", 0, 1)}
    msgs_ok = all(printed[n] == w for n, w in want.items())
    tries = [printed[n][0] for n in printed if n.startswith("random")]
    checks.add("S2", "a cycle model written from this truth alone (bit orders, moduli, LFSR, decode, flags) matches "
               "puzzle_recovered on every register, O and success, for 8 input streams (solution, 0 stars, "
               "121 stars, touching grid, 4 random with a mid-run reset)",
               bad_cycles == 0, cycles=len(stim), mismatching_cycles=bad_cycles,
               first_mismatch=str(first_bad) if first_bad else "none")
    checks.add("S3", "printed messages: solution -> '(* TWO STARS *)' with success = 1; 0 stars -> EMPTY SKY; "
               "121 stars -> BIG BANG; touching grid -> TWO NOT TOUCH with alt_latch = 1",
               msgs_ok, random_streams=" | ".join(tries))


# ----------------------------------------------------------------------------------------
# Operators (combinational structure), stated from the RTL; semantics covered by the checks
# ----------------------------------------------------------------------------------------

def _operators(region_sizes, colbin, tables, gen):
    bins = [f"bin{k:02d}" for k in range(22)]
    ops = [
        dict(name="cnt_lo_inc", kind="adder", width=4, inputs=["cnt_lo"], outputs=["cnt_lo"], details=dict(
            block="counter", function="cnt_lo + 1 (incrementer); the next-state mux picks 0 when cnt_lo == 10",
            verified_by=["C2", "C3"])),
        dict(name="cnt_lo_eq10", kind="comparator", width=4, inputs=["cnt_lo"],
             outputs=["cnt_lo", "cnt_hi", "cnt_done"], details=dict(
                 block="counter", function="cnt_lo == 10 (digit maximum); & enable & ~cnt_done = carry into cnt_hi",
                 constant=10, verified_by=["C3"])),
        dict(name="cnt_hi_inc", kind="adder", width=4, inputs=["cnt_hi"], outputs=["cnt_hi"], details=dict(
            block="counter", function="cnt_hi + 1 on cnt_lo's carry; 0 when cnt_hi == 10", verified_by=["C2", "C3"])),
        dict(name="cnt_hi_eq10", kind="comparator", width=4, inputs=["cnt_hi"], outputs=["cnt_hi", "cnt_done"],
             details=dict(block="counter", function="cnt_hi == 10", constant=10, verified_by=["C3"])),
        dict(name="enable_gate", kind="other", width=2, inputs=["enable", "cnt_done"],
             outputs=["cnt_lo", "cnt_hi", "cnt_done", *bins, "shift_taps", "row_stars", "row_count_err",
                      "hist_hit", "star_count", "scrambler"], details=dict(
                 block="counter/left_top/outgen", function="enable & ~cnt_done: the shared enable (shift_en) of "
                 "the sweep; ANDed with I it is the strobe of star_count and the bins", verified_by=["S2"])),
        dict(name="region_decode", kind="decoder", width=9, inputs=["cnt_hi", "cnt_lo", "cnt_done", "I", "enable"],
             outputs=bins[:11], details=dict(
                 block="array", function="(row, column) -> one of 11 irregular Star Battle regions; one-hot over "
                 "the 121 reachable states (a sum of products per region), gated by I & enable & ~cnt_done",
                 region_sizes=region_sizes, verified_by=["A2", "A3"])),
        dict(name="column_decode", kind="decoder", width=4, inputs=["cnt_lo", "cnt_done", "I", "enable"],
             outputs=bins[11:], details=dict(
                 block="array", function="cnt_lo == c for c = 0..10, gated by I & enable & ~cnt_done",
                 column_to_bin={str(c): f"bin{colbin[c]:02d}" for c in range(11)}, verified_by=["A2", "A3"])),
    ]
    for k in range(22):
        ops.append(dict(name=f"{bins[k]}_inc", kind="adder", width=2, inputs=[bins[k]], outputs=[bins[k]],
                        details=dict(block="array", function="saturating increment (+1, holds at 3) when the bin's "
                                     "decode line fires", verified_by=["A1", "A3"])))
    ops += [
        dict(name="check_slot", kind="comparator", width=4, inputs=["cnt_lo"],
             outputs=["row_stars", "row_count_err", "hist_hit"], details=dict(
                 block="left_top", function="cnt_lo == 10 (the row's last cell); the RTL computes it separately "
                 "from the counter's own == 10", constant=10, verified_by=["L3"])),
        dict(name="col_nonzero", kind="comparator", width=4, inputs=["cnt_lo"], outputs=["hist_hit"], details=dict(
            block="left_top", function="cnt_lo != 0 (4-input OR)", constant=0, verified_by=["L3"])),
        dict(name="row_stars_inc", kind="adder", width=2, inputs=["row_stars", "I"], outputs=["row_stars"],
             details=dict(block="left_top", function="saturating add of I (holds at 3), cleared by check_slot",
                          verified_by=["L2", "L3"])),
        dict(name="row_not_two", kind="comparator", width=3, inputs=["row_stars", "I"], outputs=["row_count_err"],
             details=dict(block="left_top", function="(row_stars + I) != 2", constant=2, verified_by=["L3"])),
        dict(name="adjacency", kind="other", width=7, inputs=["shift_taps", "cnt_lo", "I"], outputs=["hist_hit"],
             details=dict(block="left_top", function="I & (tap10 | (cnt_lo != 0 & (tap0 | tap11)) | "
                          "(cnt_lo != 10 & tap9)): the new star touches the cell left, above-left, above or "
                          "above-right", verified_by=["L3"])),
        dict(name="star_count_inc", kind="adder", width=8, inputs=["star_count"], outputs=["star_count"],
             details=dict(block="left_bottom", function="+1 ripple-carry incrementer (running AND chain), strobe "
                          "I & enable & ~cnt_done", verified_by=["B1", "B2"])),
        dict(name="array_eq_target", kind="comparator", width=44, inputs=bins,
             outputs=["success_latch", "alt_latch"], details=dict(
                 block="check", function="every bin == 2: the 44 flops in id order f52..f09 equal "
                 "44'b1000_1110_0101_0101_0101_0101_0011_0101_0101_1100_0101", constant="each bin = 2",
                 verified_by=["K1"])),
        dict(name="star_count_eq22", kind="comparator", width=8, inputs=["star_count"],
             outputs=["success_latch", "alt_latch"], details=dict(
                 block="check", function="star_count == 22 (raw flop pattern {f76..f69} = 8'b0000_1011)",
                 constant=22, verified_by=["K1"])),
        dict(name="trigger", kind="other", width=2, inputs=["cnt_done", "armed"],
             outputs=["success_latch", "alt_latch"], details=dict(
                 block="check", function="cnt_done & ~armed: rising-edge detector of cnt_done (armed is its memory); "
                 "load enable of the decision latches", verified_by=["K1"])),
        dict(name="star_count_eq0", kind="comparator", width=8, inputs=["star_count"], outputs=["O"], details=dict(
            block="outgen", function="star_count == 0 (selects EMPTY SKY)", constant=0, verified_by=["G6"])),
        dict(name="star_count_eq121", kind="comparator", width=8, inputs=["star_count"], outputs=["O"], details=dict(
            block="outgen", function="star_count == 121 (raw {f69..f76} = 8'hAE; selects BIG BANG)", constant=121,
            verified_by=["G6"])),
        dict(name="pos_eq15", kind="comparator", width=4, inputs=["pos"], outputs=["pos", "scrambler", "O"],
             details=dict(block="outgen", function="pos == 15 (all ones: saturation and end of printing)",
                          constant=15, verified_by=["G2", "G6"])),
        dict(name="pos_inc", kind="adder", width=4, inputs=["pos", "armed"], outputs=["pos"], details=dict(
            block="outgen", function="saturating +1 while armed, 0 otherwise", verified_by=["G1", "G2"])),
        dict(name="scr_feedback", kind="xor", width=5, inputs=["scrambler", "I"], outputs=["scrambler"],
             details=dict(block="outgen", function="I ^ s3 ^ s4 ^ s5 ^ s7 (LFSR feedback parity into index 0)",
                          verified_by=["G3"])),
        dict(name="scr_step8", kind="xor", width=8, inputs=["scrambler"], outputs=["scrambler"], details=dict(
            block="outgen", function="8x8 GF(2) matrix = the LFSR advanced 8 steps with zero input (print mode)",
            rows_index_coordinates=gen["print_matrix_rows"], verified_by=["G4"])),
        dict(name="message_rom", kind="rom", width=4, inputs=["pos"], outputs=["O"], details=dict(
            block="outgen", function="5 tables of 16 bytes addressed by the raw pos flops {f88,f89,f90,f91}; "
            "listed here in count order", tables_hex={k: bytes(t).hex() for k, t in tables.items()},
            verified_by=["G6"])),
        dict(name="keystream_xor", kind="xor", width=8, inputs=["message_rom", "scrambler"], outputs=["O"],
             details=dict(block="outgen", function="success table XOR scrambler (O bit i = table bit i ^ scrambler "
                          "index i)", verified_by=["G6", "S3"])),
        dict(name="o_select", kind="mux", width=8,
             inputs=["message_rom", "keystream_xor", "star_count_eq0", "star_count_eq121", "success_latch",
                     "alt_latch", "armed", "pos_eq15"], outputs=["O"], details=dict(
                 block="outgen", function="priority select EMPTY SKY / BIG BANG / success / TWO NOT TOUCH / TRY AGAIN, "
                 "then AND with armed & pos != 15", verified_by=["G6"])),
    ]
    return ops


# ----------------------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------------------

def build(work):
    checks = Checks()
    blocks = load_blocks()
    tags, conns = load_rtl_names()
    check_names(checks, blocks, tags, conns)
    T = Truth(tags)
    T.reset_bits = {f: (1 if "dfstp" in v["master"] else 0 if "dfrtp" in v["master"] else None)
                    for f, v in blocks.items()}
    sim = Sim(work)
    qnet, netlist, summary = check_extraction(checks, blocks, work)

    def stage(cid, fn, *args):
        """Run one check stage; a truth that breaks the checker (e.g. names a flop the block
        does not read) is a failed check, not a crash."""
        try:
            return fn(*args)
        except (KeyError, IndexError, ValueError, TypeError, StopIteration) as e:
            checks.add(cid, f"{fn.__name__} could not evaluate the stated truth", False, error=repr(e))
            return None

    ctr = stage("C0", check_counter, sim, checks, T)
    stage("B0", check_left_bottom, sim, checks, T)
    arr = stage("A0", check_array, sim, checks, T)
    stage("L0", check_left_top, sim, checks, T)
    stage("K0", check_check, sim, checks, T)
    gen = stage("G0", check_outgen, sim, checks, T)
    if arr and gen:
        stage("S0", check_sequential, sim, checks, T, qnet, netlist, arr[0], arr[1], gen["tables"], gen["reset"])
    if checks.failed:
        raise SystemExit(f"{len(checks.failed)} check(s) failed: {', '.join(checks.failed)}; nothing written")

    # ---- assemble ----
    region, colbin, all256 = arr
    col_of_bin = {b: c for c, b in colbin.items()}
    region_cells = {k: sorted([list(rc) for rc, b in region.items() if b == k]) for k in GROUP_A}
    registers = []
    for r in REGISTERS:
        d = json.loads(json.dumps(r["details"]))
        name = r["name"]
        if name.startswith("bin"):
            k = int(name[3:])
            if k in GROUP_A:
                d["decode"] = {"type": "region", "region": "ABCDEFGHIJK"[k], "size": len(region_cells[k]),
                               "cells_row_col": region_cells[k]}
                d["enable"] = f"{EN_I} & (cnt_hi, cnt_lo) in region {'ABCDEFGHIJK'[k]}"
            else:
                d["decode"] = {"type": "column", "column": col_of_bin[k]}
                d["enable"] = f"{EN_I} & cnt_lo == {col_of_bin[k]}"
        if name == "cnt_lo":
            d["unreachable_values"] = "11..15 step +1 (15 -> 0); never reached from reset: " + json.dumps(
                ctr["lo_unreachable"])
        if name == "scrambler":
            d.update({
                "chain": "index 0 (f87, loads feedback) -> 1 (f86) -> 2 (f84) -> 3 (f85) -> 4 (f82) -> 5 (f83) -> "
                         "6 (f80) -> 7 (f81, oldest)",
                "modes": {
                    "shift": {"when": EN, "next": "s' = ((s << 1) | (I ^ s3 ^ s4 ^ s5 ^ s7)) & 0xFF",
                              "matrix_rows_index_coordinates": gen["shift_matrix_rows"], "input_column": [0]},
                    "print": {"when": "~(enable & ~cnt_done) & armed & pos != 15",
                              "next": "s' = M^8 s (eight zero-input LFSR steps per cycle)"},
                    "hold": {"when": "otherwise"}},
                "polynomial": {"characteristic": "x^8+x^4+x^3+x^2+1", "characteristic_hex": "0x11D",
                               "connection": "1+x^4+x^5+x^6+x^8", "connection_hex": "0x171",
                               "convention": "state s_k(n) = a(n-1-k); a(n) = a(n-4)+a(n-5)+a(n-6)+a(n-8) (+ I); "
                                             "Fibonacci taps at stages 4,5,6,8 counted from the input (1-based)"},
                "primitive": True, "period": 255, "linear_complexity": 8,
                "reset_value": "0xA5 (index 0,2,5,7 = f87,f84,f83,f81 are dfstp set-to-1; the rest dfrtp)",
                "use": "O = success_table[pos] ^ s while printing with success_latch; O bit i = s bit i",
                "kind_note": "a true LFSR: next state GF(2)-affine in (state, I) in shift mode and linear in print "
                             "mode; with I injected at the feedback it is also a serial-input signature register "
                             "(multiplicative scrambler form)"})
        bits = []
        for i, b in enumerate(r["bits"]):
            f = T.name_to_fid[b]
            bits.append({"index": i, "flop": blocks[f]["instance"], "rtl_bit": b, "flop_id": f,
                         "q_net": blocks[f]["Q_net"], "master": blocks[f]["master"].split("__")[1],
                         "reset": T.reset_bits[f]})
        keys = [b["flop"] for b in bits]
        stated, verified_by = STATED_PARAMS.get(name, ({}, []))
        params = dict(stated)
        if r["kind"] == "counter":
            params["bit_order"] = keys
        elif r["kind"] == "shift_register":
            params["order"] = [keys]
        elif r["kind"] == "lfsr_crc":
            params["bit_order"] = keys
        extra = set(params) - set(schema.PARAMS.get(r["kind"], ()))
        if extra:
            raise SystemExit(f"{name}: parameters {sorted(extra)} are not in schema.PARAMS[{r['kind']!r}]")
        params = {k: params[k] for k in schema.PARAMS.get(r["kind"], ()) if k in params}
        note = PARAMS_NOTES.get("bins" if name.startswith("bin") else name)
        if note:
            d["params_note"] = note
        alt, alt_reason = ALT_KINDS.get(name, ([], None))
        block = d["block"]
        prov = {"rule": "stated by hand from the recovered RTL (rtl_recovered/), checked by meta.checks",
                "auto_kind": None, "override_reason": None,
                "params_source": "hand (STATED_PARAMS)" if params else None,
                "params_check": ({"verified_by": verified_by,
                                  "result": "pass" if all(c not in checks.failed for c in verified_by)
                                  else "FAIL"} if params else None)}
        if name in OTHER_MODES:
            prov["other_modes"] = OTHER_MODES[name]
        if name in ALT_KINDS_REMOVED:
            kinds, reason, why = ALT_KINDS_REMOVED[name]
            prov["alt_kinds_removed"] = [{"alt_kinds": kinds, "alt_reason": reason, "removed": why}]
        registers.append({
            "name": name, "width": len(bits), "kind": r["kind"], "alt_kinds": alt, "alt_reason": alt_reason,
            "module_def": BLOCK_MODULE[block],
            "design_key": BLOCK_MODULE[block] + ":" + ("bin[*]" if name.startswith("bin") else name),
            "params": params, "bits": bits, "n_flops": len(set(keys)),
            "provenance": prov, "details": d})

    region_sizes = {"ABCDEFGHIJK"[k]: len(region_cells[k]) for k in GROUP_A}
    operators = _operators(region_sizes, colbin, gen["tables"], gen)
    reg_fids = {r["name"]: [b["flop_id"] for b in r["bits"]] for r in registers}
    for op in operators:
        op["reads"] = sorted({f for x in op["inputs"] for f in reg_fids.get(x, [])})
        op["feeds"] = sorted({f for x in op["outputs"] for f in reg_fids.get(x, [])}) + [
            x for x in op["outputs"] if x in ("O", "success")]

    by_kind = {}
    for r in registers:
        e = by_kind.setdefault(r["kind"], {"registers": 0, "bits": 0, "distinct_designs": set()})
        e["registers"] += 1
        e["bits"] += r["width"]
        e["distinct_designs"].add(r["design_key"])
    for e in by_kind.values():
        e["distinct_designs"] = len(e["distinct_designs"])
    by_kind = dict(sorted(by_kind.items()))
    flops = {}
    for r in registers:
        for b in r["bits"]:
            flops[b["flop"]] = {"registers": [r["name"]], "primary": r["name"], "role": "bit",
                                "rtl_bits": [b["rtl_bit"]], "flop_id": b["flop_id"]}
    flops = dict(sorted(flops.items()))
    reg_by_name = {r["name"]: r for r in registers}
    units = []
    for uname, ukind, members, reason, uparams, verified_by in UNITS:
        fl = [b["flop"] for m in members for b in reg_by_name[m]["bits"]]
        units.append({"name": uname, "kind": ukind, "registers": members, "reason": reason, "flops": fl,
                      "params": uparams, "check": {"verified_by": verified_by,
                                                   "result": "pass" if all(c not in checks.failed
                                                                           for c in verified_by) else "FAIL"}})
    op_kinds = {}
    for op in operators:
        op_kinds[op["kind"]] = op_kinds.get(op["kind"], 0) + 1
    names = lambda pred: [r["name"] for r in registers if pred(r)]  # noqa: E731
    meta = {
        "design": "puzzle",
        "description": "Jane Street ASIC puzzle (sky130_fd_sc_hd): a Star Battle checker. 92 flops, 728 logic cells; "
                       "names are stripped in the GDS, so the extracted netlist is anonymous by construction.",
        "generated_by": "python -m tools.s3.truth_puzzle",
        "netlist": {"gds": GDS, "extractor": "tools/retrace/extract.py (Extraction, SKY130_HD)",
                    "logic_instances": summary["logic_instances"], "flops": 92,
                    "flop_masters": {"dfrtp_2": 84, "dfstp_2": 4, "dfxtp_2": 4},
                    "instance_names": "master_x_y (DEF-style lower-left in nm), e.g. dfrtp_2_32200_92480",
                    "net_names": "generated nNNN by the extractor (q_net), except ports (success)"},
        "sources": {p: sha256(p) for p in [*RTL_FILES, BLOCKS, INTENT_DOC, SOLUTION_DOC]},
        "conventions": {
            "bits.index": "counter: weight 2^index (LSB = 0); shift: stage number, 0 loads the serial input; "
                          "lfsr: 0 is the feedback stage, index k loads k-1, and index = bit of the byte XORed into O; "
                          "flag: 0",
            "bits.flop": "join key: instance name in tools/retrace/extract.py's extraction of upstream/puzzle.gds "
                         "(master_x_y)",
            "bits.flop_id": "fNN, stable ids of rtl_recovered/blocks.json",
            "bits.rtl_bit": "register name in rtl_recovered/puzzle_recovered.v",
            "bits.reset": "async reset value (1 = dfstp set, 0 = dfrtp reset, null = dfxtp, no reset pin)",
            "params": "schema.PARAMS for the kind; flops as join keys (bit_order LSB / stage 0 first); "
                      "shift direction to_msb = data moves toward higher index; lfsr poly = characteristic "
                      "polynomial as an integer; lfsr k_steps = LFSR steps per clock in the main (data) update "
                      "mode and n_inputs = data bits entering per step (schema.py), other modes in "
                      "provenance.other_modes; null = unknown, leaves the denominator",
            "alt_kinds": "only widen what a match accepts; never remove a register from a denominator (schema.py); "
                         "alternatives the 2026-09-22 review removed are kept in provenance.alt_kinds_removed",
            "module_def": "the rec_* block (rtl_recovered/<block>.v) that computes the register's next state; "
                          "design_key merges the 22 bins, one repeated design",
            "units": "declared lenient alternatives: a matched unit credits its member registers; never an extra "
                     "target and never the rec_* blocks as such",
            "details": "a dict; 'summary' is prose, the other keys are structured and checked where noted",
            "operators": "combinational structure stated from the RTL; inputs/outputs name registers, ports or "
                         "other operators; reads/feeds are the flop ids involved; verified_by names checks",
        },
        "counts": {"registers": len(registers), "bits": sum(r["width"] for r in registers), "by_kind": by_kind,
                   "units": len(units), "operators": len(operators), "operators_by_kind": op_kinds},
        "kinds": list(schema.KINDS), "structure_kinds": list(schema.STRUCTURE_KINDS),
        "kind_names_note": "retrace-s3-truth/2 uses schema.KINDS; truth/1 said shift and lfsr "
                           "(schema.canonical_kind maps the old names)",
        "operator_kinds": ["adder", "comparator", "decoder", "xor", "mux", "rom", "other"],
        "operator_kind_aliases": {"adder": ["$add", "$sub"], "comparator": ["$eq", "$ne", "$lt", "$le", "$gt", "$ge"],
                                  "xor": ["$xor", "$xnor", "$reduce_xor", "$reduce_xnor"], "mux": ["$mux", "$pmux"],
                                  "decoder": ["$eq (one per output)"], "rom": ["$memrd", "$shiftx", "$pmux"],
                                  "note": "nearest Yosys cell types, for joining with a Yosys-derived truth"},
        "rtl_blocks_note": "the rec_* blocks of rtl_recovered/, for orientation only: not scoring units "
                           "(see units for the declared alternatives)",
        "rtl_blocks": [
            {"name": "cycle_counter", "registers": ["cnt_lo", "cnt_hi", "cnt_done"],
             "details": "cascaded base-11 x base-11 counter (mod 121, the grid sweep): cnt_lo counts enabled cycles, "
                        "cnt_hi counts its carries, cnt_done is the terminal count; runs once, then freezes"},
            {"name": "array", "registers": [f"bin{k:02d}" for k in range(22)],
             "details": "22 saturating 2-bit counters, each enabled by its own decode of the cycle counter (bins "
                        "0-10 regions, 11-21 columns; no shared write data, index or read port); the check wants "
                        "every bin == 2"},
            {"name": "left_top", "registers": ["shift_taps", "row_stars", "row_count_err", "hist_hit"],
             "details": "the grid-rule checker: 12-cell history, per-row star count, two sticky error flags"},
            {"name": "left_bottom", "registers": ["star_count"], "details": "total star counter"},
            {"name": "check", "registers": ["armed", "success_latch", "alt_latch"],
             "details": "one-shot decision on cnt_done's rising edge (a 3-flop control structure)"},
            {"name": "outgen", "registers": ["scrambler", "pos"],
             "details": "message printer: pos addresses the ROM, the LFSR is the success message's keystream"},
        ],
        "enable_groups": {
            EN: names(lambda r: r["name"] in ("cnt_lo", "shift_taps", "row_stars", "row_count_err", "scrambler")),
            EN_I + " (& decode for bins)": ["star_count", "hist_hit"] + [f"bin{k:02d}" for k in range(22)],
            "cnt_lo carry": ["cnt_hi", "cnt_done"],
            "armed": ["pos", "scrambler (print mode)"],
            "cnt_done & ~armed (trigger)": ["success_latch", "alt_latch"],
            "always (d = cnt_done | armed)": ["armed"],
        },
        "reset_groups": {
            "rst_n async reset to 0 (dfrtp)": [f for f in sorted(blocks) if T.reset_bits[f] == 0],
            "rst_n async set to 1 (dfstp)": [f for f in sorted(blocks) if T.reset_bits[f] == 1],
            "no reset (dfxtp)": [f for f in sorted(blocks) if T.reset_bits[f] is None],
        },
        "grid": {"rows": 11, "columns": 11, "cell_order": "row-major, column fastest (cnt_hi = row, cnt_lo = column)",
                 "region_map": ["".join("ABCDEFGHIJK"[region[(r, c)]] for c in range(11)) for r in range(11)],
                 "region_decode_one_hot_over_all_256_states": all256},
        "checks": checks.items,
        "source_discrepancies": [
            "rtl_recovered/left_top.v's comment calls q_f08 'the top bit of the 5-bit counter block (f04..f08)'; "
            "f08 is cnt_done and f04..f07 are cnt_lo's bits 2,1,0,3.",
        ],
        "source_corrections": [
            "docs/INTENT.md section 2.6 and rtl_recovered/outgen.v's header gave the scrambler reset as 8'b1011_0110 "
            "and INTENT's table listed f85 as dfstp; corrected on 2026-09-21 to 0xA5 with f85 dfrtp, as this truth's "
            "check G5 and blocks.json say.",
            "the same two files called pos a permutation FSM with 9 live steps; corrected on 2026-09-21 to a "
            "saturating binary counter with permuted bits and 15 printing steps (check G1).",
        ],
    }
    known = {c["id"] for c in checks.items}
    for r in registers + units:
        vb = ((r.get("provenance") or {}).get("params_check") or r.get("check") or {}).get("verified_by", [])
        if any(c not in known for c in vb):
            raise SystemExit(f"{r['name']}: verified_by names an unknown check: {vb}")
    return {"schema": schema.TRUTH_SCHEMA, "design": "puzzle", "registers": registers, "units": units,
            "flops": flops, "unmapped_flops": [], "operators": operators, "meta": meta}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", nargs="?", default=P("out/s3/truth_puzzle.json"), help="output JSON")
    ap.add_argument("--run-json", help="volatile facts (default: OUT with .run.json)")
    ap.add_argument("--work", default=P("out/s3/truth_puzzle_work"), help="scratch directory for Icarus runs")
    args = ap.parse_args(argv)
    out = os.path.abspath(args.out)
    t0 = time.time()
    truth = build(os.path.abspath(args.work))
    problems = schema.check_truth(truth)
    if problems:
        raise SystemExit(f"check_truth: {problems[:10]}; nothing written")
    text = json.dumps(truth, indent=1) + "\n"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(text)
    th = schema.truth_hash(json.loads(text))  # of the file as read back
    ver = subprocess.run([f"{BIN}/iverilog", "-V"], capture_output=True, text=True).stdout.splitlines()
    head = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--", "tools/s3", "rtl_recovered"],
                            capture_output=True, text=True).stdout.splitlines()
    run = {"truth": os.path.relpath(out, ROOT), "truth_hash": th, "truth_sha256": hashlib.sha256(text.encode()).hexdigest(),
           "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "argv": sys.argv,
           "seconds": round(time.time() - t0, 1),
           "versions": {"python": platform.python_version(), "iverilog": ver[0] if ver else None,
                        "platform": platform.platform()},
           "retrace": {"head": head, "status": status}, "paths": {"work": os.path.abspath(args.work)}}
    run_path = args.run_json or re.sub(r"\.json$", "", out) + ".run.json"
    with open(run_path, "w") as f:
        json.dump(run, f, indent=1)
        f.write("\n")
    c = truth["meta"]["counts"]
    print(f"wrote {out}: {c['registers']} registers, {c['bits']} bits, {c['units']} units, {c['operators']} "
          "operators; by kind " + ", ".join(f"{k} {v['registers']}/{v['bits']}" for k, v in c["by_kind"].items())
          + f"; truth_hash {th}")
    print(f"wrote {run_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
