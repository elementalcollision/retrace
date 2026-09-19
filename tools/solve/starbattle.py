#!/usr/bin/env python3
"""
tools/solve/starbattle.py -- analytical route (route A) for RETRACE sprint 4.

Derives the exact Star-Battle rules encoded in the puzzle's recovered RTL
(rtl_recovered/{counter,array,left_top,left_bottom,check}.v) by direct
translation of those files' combinational equations plus simulation
cross-checks against the RTL itself (via Icarus, see self_test()), then
solves for every satisfying 11x11 star placement with an exact SAT/SMT
(z3) model of those same equations, and validates the result(s) by
simulating the full puzzle_recovered top level from reset.

Run:
    .venv/bin/python -m tools.solve.starbattle             # derive + solve + validate
    .venv/bin/python -m tools.solve.starbattle --selftest   # only the RTL cross-checks

All numbers/claims printed under "DERIVED" are established by simulating the
actual rtl_recovered/*.v files with Icarus (tools/solve/tb/*.v, built into out/solve_a/), not by
trusting the hand-written commentary in those files or in docs/INTENT.md.
"""
import itertools
import os
import random
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RTL = os.path.join(REPO, "rtl_recovered")
OUT = os.path.join(REPO, "out", "solve_a")
_EDA = os.path.expanduser("~/ttsetup/oss-cad-suite/bin")
IVERILOG = os.path.join(_EDA, "iverilog") if os.path.exists(os.path.join(_EDA, "iverilog")) else "iverilog"
VVP = os.path.join(_EDA, "vvp") if os.path.exists(os.path.join(_EDA, "vvp")) else "vvp"


# ---------------------------------------------------------------------------
# 1. Cell order: (row, col) presented on enabled cycle k, k = 0..120.
#    Established by simulating rec_counter.v from reset with enable=1 for
#    130 cycles (out/solve_a/tb_counter.v / tb_counter.log) and reading off
#    HI (=row), LO (=col) at each K. The trace shows: K=1..121 sweep
#    (0,0),(0,1),...,(0,10),(1,0),...,(10,10) i.e. row-major, LO (column)
#    fast, HI (row) slow; K=122 first shows DONE=1 with HI=LO=0 (reset by
#    the counter's own d_f08 latch). The K=0/K=1 duplicate at the very start
#    of the log is a testbench display artifact (NBA hasn't committed at the
#    print statement immediately following the first @(posedge)); every
#    later K advances by exactly one cell per cycle, confirmed by diffing
#    the full log against this closed-form formula below.
def cell_order():
    """Return list of (row, col) for k = 0..120, row-major, row=hi, col=lo."""
    return [(hi, lo) for hi in range(11) for lo in range(11)]


def counter_bits(hi, lo):
    """q_f00..q_f07 for a given (row=hi, col=lo); q_f08 (cnt_done) is 0 for
    all k in 0..120 (established by the same trace: DONE stays 0 through
    K=121 and only becomes 1 at K=122, i.e. after all 121 cells are seen)."""
    hi0, hi1, hi2, hi3 = (hi >> 0) & 1, (hi >> 1) & 1, (hi >> 2) & 1, (hi >> 3) & 1
    lo0, lo1, lo2, lo3 = (lo >> 0) & 1, (lo >> 1) & 1, (lo >> 2) & 1, (lo >> 3) & 1
    return dict(f00=hi0, f01=hi3, f02=hi1, f03=hi2, f04=lo2, f05=lo1, f06=lo0, f07=lo3)


TB_DIR = os.path.join(REPO, "tools", "solve", "tb")
# testbench -> the recovered RTL files it drives; logs are regenerated on every run
TESTBENCHES = {
    "tb_counter": ["counter.v"],
    "tb_array": ["array.v"],
    "tb_left_top": ["left_top.v", "counter.v"],
}


def build_testbenches():
    """Compile the committed testbenches (tools/solve/tb/) against rtl_recovered/ into
    out/solve_a/, and run the two that produce logs. Needed by every cross-check."""
    os.makedirs(OUT, exist_ok=True)
    for tb, rtl in TESTBENCHES.items():
        vvp = os.path.join(OUT, f"{tb}.vvp")
        subprocess.run([IVERILOG, "-g2012", "-o", vvp, os.path.join(TB_DIR, f"{tb}.v")]
                       + [os.path.join(RTL, f) for f in rtl], check=True, cwd=REPO)
        if tb != "tb_left_top":  # tb_left_top is run per sequence by run_icarus_left_top()
            with open(os.path.join(OUT, f"{tb}.log"), "w") as fh:
                subprocess.run([VVP, "-n", vvp], check=True, cwd=REPO, stdout=fh)


def verify_cell_order_against_icarus():
    log = os.path.join(OUT, "tb_counter.log")
    if not os.path.exists(log):
        raise RuntimeError(f"missing {log}; run the counter testbench first (see docs)")
    rows = []
    with open(log) as fh:
        for line in fh:
            if not line.startswith("K="):
                continue
            parts = dict(p.split("=") for p in line.split())
            rows.append((int(parts["K"]), int(parts["HI"]), int(parts["LO"]), int(parts["DONE"])))
    # rows[k] for k=1..121 (1-indexed in the log) must equal cell_order()[k-1];
    # rows[0] is the pre-loop duplicate print (see docstring above).
    order = cell_order()
    mismatches = []
    for k, hi, lo, done in rows:
        if k == 0:
            continue
        if k <= 121:
            exp_row, exp_col = order[k - 1]
            if (hi, lo) != (exp_row, exp_col) or done != 0:
                mismatches.append((k, hi, lo, done, exp_row, exp_col))
        elif k == 122:
            if (hi, lo, done) != (0, 0, 1):
                mismatches.append((k, hi, lo, done, "done should latch here"))
    return mismatches, len(rows)


# ---------------------------------------------------------------------------
# 2. Region map (group A, bins 0-10): translated verbatim from the hitNN
#    wire expressions in rtl_recovered/array.v (wr_en & ~q_f08 factored out;
#    q_f08 is always 0 in-domain per step 1, so every hitNN below is exactly
#    the netlist's own condition restricted to the reachable state space).
def _b(bits, name):
    return bits[name]


def hit00(b):
    f0,f1,f2,f3,f4,f5,f6,f7 = (b['f00'],b['f01'],b['f02'],b['f03'],b['f04'],b['f05'],b['f06'],b['f07'])
    return any([
        f1 and f3,
        f0 and f1 and f2,
        f1 and f2 and f4 and f7,
        f1 and f2 and f5 and f6 and f7,
        f3 and not f2 and not f4 and not f6 and not f7,
        f3 and f4 and f7 and not f0 and not f2 and not f5,
        f4 and f6 and f7 and not f1 and not f3 and not f5,
        f0 and f2 and f5 and f6 and f7 and not f3 and not f4,
        f0 and f3 and not f2 and not f4 and not f5 and not f7,
        f3 and f5 and f6 and f7 and not f0 and not f2 and not f4,
        f0 and f5 and not f1 and not f2 and not f4 and not f6 and not f7,
        f2 and f5 and not f1 and not f3 and not f4 and not f6 and not f7,
    ])


def hit01(b):
    f0,f1,f2,f3,f4,f5,f6,f7 = (b['f00'],b['f01'],b['f02'],b['f03'],b['f04'],b['f05'],b['f06'],b['f07'])
    return any([
        f0 and f2 and f4 and not f1 and not f5 and not f7,
        f0 and f2 and f4 and not f1 and not f6 and not f7,
        f0 and f3 and f4 and not f1 and not f5 and not f7,
        f0 and f3 and f4 and not f1 and not f6 and not f7,
        f2 and f4 and f5 and f6 and f7 and not f1 and not f3,
        f3 and f4 and f5 and f6 and f7 and not f0 and not f1,
        f2 and f3 and f4 and f5 and not f1 and not f6 and not f7,
        f3 and f4 and not f1 and not f2 and not f5 and not f6 and not f7,
    ])


def hit02(b):
    f0,f1,f2,f3,f4,f5,f6,f7 = (b['f00'],b['f01'],b['f02'],b['f03'],b['f04'],b['f05'],b['f06'],b['f07'])
    return any([
        f1 and f4 and f5 and f7 and not f0 and not f2 and not f3,
        f1 and f4 and f5 and f7 and not f2 and not f3 and not f6,
        f0 and f2 and f3 and f4 and f5 and f7 and not f1 and not f6,
        f1 and f5 and f6 and not f0 and not f3 and not f4 and not f7,
        f1 and f5 and f6 and not f2 and not f3 and not f4 and not f7,
        f0 and f1 and f4 and not f2 and not f3 and not f5 and not f6 and not f7,
    ])


def hit03(b):
    f0,f1,f2,f3,f4,f5,f6,f7 = (b['f00'],b['f01'],b['f02'],b['f03'],b['f04'],b['f05'],b['f06'],b['f07'])
    return any([
        f0 and f1 and f7 and not f2 and not f3 and not f4 and not f5,
        f0 and f1 and f7 and not f2 and not f3 and not f4 and not f6,
        f0 and f3 and f7 and not f1 and not f2 and not f4 and not f5,
        f0 and f3 and f7 and not f1 and not f2 and not f4 and not f6,
        f2 and f3 and f7 and not f1 and not f4 and not f5 and not f6,
        f1 and f7 and not f2 and not f3 and not f4 and not f5 and not f6,
    ])


def hit04(b):
    f0,f1,f2,f3,f4,f5,f6,f7 = (b['f00'],b['f01'],b['f02'],b['f03'],b['f04'],b['f05'],b['f06'],b['f07'])
    return any([
        f7 and not f1 and not f2 and not f3 and not f4 and not f5,
        f6 and f7 and not f0 and not f1 and not f3 and not f4 and not f5,
    ])


def hit05(b):
    f0,f1,f2,f3,f4,f5,f6,f7 = (b['f00'],b['f01'],b['f02'],b['f03'],b['f04'],b['f05'],b['f06'],b['f07'])
    return any([
        f0 and f2 and f7 and not f1 and not f3 and not f4 and not f5,
        f0 and f4 and f5 and not f1 and not f2 and not f3 and not f7,
        f4 and f5 and f6 and not f0 and not f1 and not f3 and not f7,
        f2 and f7 and not f1 and not f3 and not f4 and not f5 and not f6,
    ])


def hit06(b):
    f0,f1,f2,f3,f4,f5,f6,f7 = (b['f00'],b['f01'],b['f02'],b['f03'],b['f04'],b['f05'],b['f06'],b['f07'])
    return any([
        not f1 and not f3 and not f4 and not f5 and not f7,
        f4 and f7 and not f1 and not f3 and not f5 and not f6,
        f5 and f6 and not f1 and not f2 and not f3 and not f4,
        f4 and f5 and f7 and not f0 and not f1 and not f2 and not f3,
        f5 and f6 and f7 and not f0 and not f1 and not f3 and not f4,
        not f0 and not f1 and not f2 and not f3 and not f4 and not f7,
        not f1 and not f2 and not f3 and not f5 and not f6 and not f7,
        f6 and not f0 and not f1 and not f2 and not f4 and not f5 and not f7,
    ])


def hit07(b):
    f0,f1,f2,f3,f4,f5,f6,f7 = (b['f00'],b['f01'],b['f02'],b['f03'],b['f04'],b['f05'],b['f06'],b['f07'])
    return any([
        f2 and f3 and f4 and f7 and not f1 and not f5,
        f0 and f1 and f4 and f7 and not f2 and not f3 and not f5,
        f0 and f2 and f3 and f5 and not f1 and not f4 and not f7,
        f0 and f2 and f3 and f6 and not f1 and not f4 and not f7,
        f1 and f4 and f6 and f7 and not f2 and not f3 and not f5,
        f2 and f3 and f4 and f7 and not f0 and not f1 and not f6,
        f1 and f5 and not f0 and not f3 and not f4 and not f6 and not f7,
        f1 and f5 and not f2 and not f3 and not f4 and not f6 and not f7,
        f1 and f6 and not f0 and not f3 and not f4 and not f5 and not f7,
    ])


def hit08(b):
    f0,f1,f2,f3,f4,f5,f6,f7 = (b['f00'],b['f01'],b['f02'],b['f03'],b['f04'],b['f05'],b['f06'],b['f07'])
    return any([
        f0 and f3 and f4 and f7 and not f1 and not f2,
        f0 and f4 and f5 and f7 and not f1 and not f2,
        f2 and f3 and f5 and f6 and f7 and not f1 and not f4,
        f2 and f3 and not f0 and not f1 and not f4 and not f7,
        f2 and f4 and not f0 and not f1 and not f5 and not f7,
        f0 and f3 and f5 and f6 and not f1 and not f2 and not f4,
        f1 and f5 and f6 and f7 and not f2 and not f3 and not f4,
        f2 and f4 and f5 and f7 and not f1 and not f3 and not f6,
        f3 and f4 and f5 and f7 and not f1 and not f2 and not f6,
        f2 and f5 and f6 and not f1 and not f3 and not f4 and not f7,
        f3 and f5 and f6 and not f1 and not f2 and not f4 and not f7,
        f0 and f1 and not f2 and not f3 and not f4 and not f5 and not f7,
        f2 and f3 and not f1 and not f4 and not f5 and not f6 and not f7,
        f4 and f5 and not f0 and not f1 and not f3 and not f6 and not f7,
        f4 and f6 and not f1 and not f2 and not f3 and not f5 and not f7,
        f1 and not f0 and not f3 and not f4 and not f5 and not f6 and not f7,
        f1 and f4 and f7 and not f0 and not f2 and not f3 and not f5 and not f6,
    ])


def hit09(b):
    f0,f1,f2,f3,f4,f5,f6,f7 = (b['f00'],b['f01'],b['f02'],b['f03'],b['f04'],b['f05'],b['f06'],b['f07'])
    return any([
        f1 and f4 and not f0 and not f3 and not f7,
        f3 and f4 and f5 and f6 and not f1 and not f7,
        f0 and f2 and f3 and f4 and f5 and f6 and not f1,
        f1 and f4 and f5 and not f2 and not f3 and not f7,
        f1 and f4 and f6 and not f2 and not f3 and not f7,
        f0 and f1 and f4 and f5 and f6 and not f2 and not f3,
        f0 and f2 and f4 and f5 and f6 and not f1 and not f7,
        f5 and f7 and not f1 and not f3 and not f4 and not f6,
        f1 and f2 and f7 and not f0 and not f3 and not f4 and not f5,
        f2 and f5 and f7 and not f0 and not f3 and not f4 and not f6,
        f3 and f4 and f5 and not f0 and not f1 and not f2 and not f7,
        f3 and f4 and f6 and not f0 and not f1 and not f2 and not f7,
        f3 and f7 and not f0 and not f1 and not f2 and not f4 and not f5,
        f5 and f7 and not f0 and not f1 and not f2 and not f4 and not f6,
    ])


def hit10(b):
    f0,f1,f2,f3,f4,f5,f6,f7 = (b['f00'],b['f01'],b['f02'],b['f03'],b['f04'],b['f05'],b['f06'],b['f07'])
    return any([
        f2 and f3 and f5 and f7 and not f1 and not f4 and not f6,
        f2 and f3 and f6 and f7 and not f1 and not f4 and not f5,
        f1 and f5 and f7 and not f0 and not f2 and not f3 and not f4 and not f6,
        f1 and f6 and f7 and not f0 and not f2 and not f3 and not f4 and not f5,
    ])


GROUP_A_HITS = [hit00, hit01, hit02, hit03, hit04, hit05, hit06, hit07, hit08, hit09, hit10]


def region_of(row, col):
    b = counter_bits(row, col)
    hits = [i for i, fn in enumerate(GROUP_A_HITS) if fn(b)]
    assert len(hits) == 1, f"({row},{col}) matched {len(hits)} group-A bins: {hits}"
    return hits[0]


def verify_region_map_against_icarus():
    """Cross-check region_of()/column decode against out/solve_a/tb_array.log
    (direct Icarus simulation of rec_array.v with a single I=1 pulse injected
    at every one of the 121 reachable (hi,lo) states, all bins starting at 0
    so a bin's LSB output equals its hitNN directly)."""
    log = os.path.join(OUT, "tb_array.log")
    if not os.path.exists(log):
        raise RuntimeError(f"missing {log}")
    # LSB position (0-indexed pair) for group-A bins 0..10 and group-B bins 11..21
    # in the printf order used by tb_array.v (see its $display format string).
    mismatches = 0
    total = 0
    with open(log) as fh:
        for line in fh:
            if not line.startswith("HI="):
                continue
            parts = line.split()
            hi = int(parts[0].split("=")[1])
            lo = int(parts[1].split("=")[1])
            bits = parts[2].split("=")[1].replace("_", "")
            assert len(bits) == 44
            pairs = [bits[i:i+2] for i in range(0, 44, 2)]
            lsbs = [p[1] for p in pairs]  # bit0=msb,bit1=lsb per our %b%b order
            fired = [i for i, v in enumerate(lsbs) if v == "1"]
            total += 1
            exp_region = region_of(hi, lo)
            exp_col_bin = 11 + LO_TO_COLBIN[lo]
            if sorted(fired) != sorted([exp_region, exp_col_bin]):
                mismatches += 1
    return mismatches, total


# Group B (bins 11-21): direct equality decode on {q_f04,q_f05,q_f06,q_f07}
# = lo bits, i.e. exactly the column index lo. Derived by inspection of
# array.v's hit11..hit21 (each is a 4-bit AND/AND2B on lo's bits only) and
# confirmed bit-for-bit by verify_region_map_against_icarus() above.
LO_TO_COLBIN = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 9: 8, 8: 9, 10: 10}


# ---------------------------------------------------------------------------
# 3. left_top.v translated verbatim: 12-tap I-history shift register plus
#    two independent sticky flags, row_count_err (f53) and hist_hit (f64).
SHIFT_TAPS = ["f67", "f66", "f68", "f63", "f60", "f58", "f61", "f56", "f57", "f59", "f62", "f65"]


def left_top_step(state, I, row, col):
    """state: dict of f53,f54,f55,<12 taps>,f64 (python bools). Returns next
    state dict. row/col give check_slot/any_low_counter_bit for this cycle
    (concrete, since the counter schedule is fixed and I-independent)."""
    check_slot = (col == 10)
    any_low = (col != 0)
    f54, f55 = state["f54"], state["f55"]
    taps = {t: state[t] for t in SHIFT_TAPS}

    # 1. shift register (shift_en = enable & ~cnt_done = 1 for k=0..120)
    new_taps = {}
    new_taps["f67"] = I
    new_taps["f66"] = taps["f67"]
    new_taps["f68"] = taps["f66"]
    new_taps["f63"] = taps["f68"]
    new_taps["f60"] = taps["f63"]
    new_taps["f58"] = taps["f60"]
    new_taps["f61"] = taps["f58"]
    new_taps["f56"] = taps["f61"]
    new_taps["f57"] = taps["f56"]
    new_taps["f59"] = taps["f57"]
    new_taps["f62"] = taps["f59"]
    new_taps["f65"] = taps["f62"]

    # 5. hist_hit
    any_low_gate = (taps["f65"] or taps["f67"]) and any_low
    tap9_off_slot = taps["f59"] and (not check_slot)
    hist_hit_cond = taps["f62"] or any_low_gate or tap9_off_slot
    new_hist_hit = state["f64"] or (I and hist_hit_cond)

    # 4. row_stars = {f54, f55}: stars so far in this row, saturating at 3, cleared at the
    #    row's last cell (check_slot, col == 10). row_count_err (f53) is set there unless
    #    the row, including the current cell, holds exactly two stars.
    row_final = 2 * int(f54) + int(f55) + int(I)
    row_next = 0 if check_slot else min(row_final, 3)
    new_f54, new_f55 = bool(row_next & 2), bool(row_next & 1)
    new_row_count_err = state["f53"] or (check_slot and row_final != 2)

    out = dict(new_taps)
    out["f54"] = new_f54
    out["f55"] = new_f55
    out["f53"] = new_row_count_err
    out["f64"] = new_hist_hit
    return out


def left_top_reset_state():
    st = {t: False for t in SHIFT_TAPS}
    st["f53"] = False
    st["f54"] = False
    st["f55"] = False
    st["f64"] = False
    return st


def simulate_left_top(I_seq):
    """I_seq: list of 121 python bools, cell order = cell_order(). Returns
    (row_count_err, hist_hit) after all 121 steps."""
    st = left_top_reset_state()
    order = cell_order()
    for k, I in enumerate(I_seq):
        row, col = order[k]
        st = left_top_step(st, bool(I), row, col)
    return st["f53"], st["f64"]


def run_icarus_left_top(I_seq):
    seqpath = os.path.join(OUT, "_seq_tmp.txt")
    with open(seqpath, "w") as fh:
        fh.write("".join("1" if b else "0" for b in I_seq))
    vvp = os.path.join(OUT, "tb_left_top.vvp")
    res = subprocess.run([VVP, vvp, f"+seq={seqpath}"], cwd=REPO, capture_output=True, text=True, timeout=30)
    for line in res.stdout.splitlines():
        if line.startswith("RESULT"):
            parts = dict(p.split("=") for p in line.split()[1:])
            return parts["row_count_err"] == "1", parts["hist_hit"] == "1", parts["cnt_done"] == "1"
    raise RuntimeError(f"no RESULT line from icarus: {res.stdout}\n{res.stderr}")


def cross_check_left_top(n_random=40, seed=0):
    rng = random.Random(seed)
    mismatches = []
    tests = []
    # directed: all-zero, all-one, single star at every one of the 121 cells alone,
    # a full row, a full column, two adjacent cells (h/v/diag), two cells two apart.
    tests.append(("all_zero", [0]*121))
    tests.append(("all_one", [1]*121))
    order = cell_order()
    idx = {(r, c): k for k, (r, c) in enumerate(order)}
    def single(r, c):
        v = [0]*121
        v[idx[(r, c)]] = 1
        return v
    tests.append(("single_0_0", single(0, 0)))
    tests.append(("single_5_5", single(5, 5)))
    tests.append(("single_10_10", single(10, 10)))
    tests.append(("row5_all", [1 if r == 5 else 0 for r, c in order]))
    tests.append(("col5_all", [1 if c == 5 else 0 for r, c in order]))
    for (r1, c1), (r2, c2), name in [
        ((3, 3), (3, 4), "h_adjacent"), ((3, 3), (4, 3), "v_adjacent"),
        ((3, 3), (4, 4), "diag_adjacent"), ((3, 3), (4, 2), "antidiag_adjacent"),
        ((3, 3), (3, 5), "h_gap2"), ((3, 3), (5, 3), "v_gap2"),
        ((0, 10), (1, 0), "row_wrap_adjacent_cols"), ((0, 0), (10, 0), "col_wrap"),
    ]:
        v = [0]*121
        v[idx[(r1, c1)]] = 1
        v[idx[(r2, c2)]] = 1
        tests.append((name, v))
    for i in range(n_random):
        v = [1 if rng.random() < 0.18 else 0 for _ in range(121)]
        tests.append((f"random_{i}", v))

    for name, v in tests:
        py_match, py_hist = simulate_left_top(v)
        ic_match, ic_hist, ic_done = run_icarus_left_top(v)
        if ic_done is not True:
            mismatches.append((name, "icarus cnt_done did not latch"))
            continue
        if (py_match, py_hist) != (ic_match, ic_hist):
            mismatches.append((name, f"python=({py_match},{py_hist}) icarus=({ic_match},{ic_hist})"))
    return mismatches, len(tests)


# ---------------------------------------------------------------------------
# 4. left_bottom / array bin targets reduce to exact-count constraints.
#    ARRAY_TARGET and LEFT_BOTTOM_TARGET are transcribed verbatim from
#    rtl_recovered/check.v.
ARRAY_TARGET_BITS = "1000_1110_0101_0101_0101_0101_0011_0101_0101_1100_0101".replace("_", "")
# array_bits = {f52,f51,...,f10,f09}; MSB=f52 first char above.

BIN_MSB_LSB = {
    0: ("f09", "f10"), 1: ("f11", "f12"), 2: ("f16", "f13"), 3: ("f15", "f14"),
    4: ("f17", "f18"), 5: ("f19", "f20"), 6: ("f21", "f22"), 7: ("f23", "f24"),
    8: ("f25", "f27"), 9: ("f26", "f28"), 10: ("f29", "f30"),
    11: ("f31", "f32"), 12: ("f33", "f34"), 13: ("f35", "f36"), 14: ("f37", "f38"),
    15: ("f39", "f40"), 16: ("f41", "f42"), 17: ("f43", "f44"), 18: ("f46", "f45"),
    19: ("f47", "f49"), 20: ("f48", "f50"), 21: ("f52", "f51"),
}


def array_target_per_bin():
    """Decode ARRAY_TARGET into a 2-bit value per bin id 0..21 and confirm the
    'every bin == exactly 2' claim by construction (from check.v's own bit
    order, independent of any hypothesis)."""
    flop_order = [f"f{n:02d}" for n in range(52, 8, -1)]  # f52..f09, MSB first
    bitval = dict(zip(flop_order, ARRAY_TARGET_BITS))
    out = {}
    for bin_id, (msb, lsb) in BIN_MSB_LSB.items():
        val = int(bitval[msb]) * 2 + int(bitval[lsb])
        out[bin_id] = val
    return out


def _decode_left_bottom_target():
    """check.v compares {q_f76,...,q_f69} against raw pattern 8'b0000_1011
    (flop-id order, NOT bit-significance order). left_bottom.v's own true
    bit weights are LSB..MSB = f75,f70,f72,f74,f69,f71,f73,f76 (see that
    file's docstring, itself established there by exhaustive permutation
    search against the gold netlist). Decode the raw pattern into flop
    values, then re-assemble by true weight to get the actual counter
    value the check requires."""
    raw_flop_order = ["f76", "f75", "f74", "f73", "f72", "f71", "f70", "f69"]  # MSB..LSB as printed
    raw_bits = "00001011"
    flopval = dict(zip(raw_flop_order, raw_bits))
    weight_order = ["f75", "f70", "f72", "f74", "f69", "f71", "f73", "f76"]  # LSB..MSB, true weights
    val = 0
    for i, f in enumerate(weight_order):
        val |= int(flopval[f]) << i
    return val


LEFT_BOTTOM_TARGET = _decode_left_bottom_target()  # decimal 22


# ---------------------------------------------------------------------------
# 5. Region-map pretty printer
def print_region_map():
    letters = "ABCDEFGHIJK"
    lines = []
    for r in range(11):
        row = []
        for c in range(11):
            row.append(letters[region_of(r, c)])
        lines.append(" ".join(row))
    return "\n".join(lines)


def region_cells():
    cells = {i: [] for i in range(11)}
    for r in range(11):
        for c in range(11):
            cells[region_of(r, c)].append((r, c))
    return cells


# ---------------------------------------------------------------------------
# 6. SAT solve with z3, over the EXACT rules derived above.
def solve_all(max_solutions=1000, verbose=True):
    import z3

    order = cell_order()
    cells = {(r, c): z3.Bool(f"I_{r}_{c}") for r, c in order}

    s = z3.Solver()

    # region (group A) and column (group B) exact-2 constraints
    regs = region_cells()
    for reg_id, cs in regs.items():
        s.add(z3.PbEq([(cells[c], 1) for c in cs], 2))
    cols = {c: [] for c in range(11)}
    for r, c in order:
        cols[c].append((r, c))
    for col_id, cs in cols.items():
        s.add(z3.PbEq([(cells[c], 1) for c in cs], 2))

    # left_bottom: total stars == 22 (implied by the above, added for belt-and-braces)
    s.add(z3.PbEq([(cells[c], 1) for c in order], 22))

    # left_top FSM, symbolically unrolled with z3 booleans standing in for I[k]
    st = {t: z3.BoolVal(False) for t in SHIFT_TAPS}
    st["f53"] = z3.BoolVal(False)
    st["f54"] = z3.BoolVal(False)
    st["f55"] = z3.BoolVal(False)
    st["f64"] = z3.BoolVal(False)

    def zstep(state, I, row, col):
        check_slot = (col == 10)
        any_low = (col != 0)
        f54, f55 = state["f54"], state["f55"]
        taps = {t: state[t] for t in SHIFT_TAPS}
        new_taps = {}
        new_taps["f67"] = I
        new_taps["f66"] = taps["f67"]
        new_taps["f68"] = taps["f66"]
        new_taps["f63"] = taps["f68"]
        new_taps["f60"] = taps["f63"]
        new_taps["f58"] = taps["f60"]
        new_taps["f61"] = taps["f58"]
        new_taps["f56"] = taps["f61"]
        new_taps["f57"] = taps["f56"]
        new_taps["f59"] = taps["f57"]
        new_taps["f62"] = taps["f59"]
        new_taps["f65"] = taps["f62"]

        if any_low:
            any_low_gate = z3.Or(taps["f65"], taps["f67"])
        else:
            any_low_gate = z3.BoolVal(False)
        if check_slot:
            tap9_off_slot = z3.BoolVal(False)
        else:
            tap9_off_slot = taps["f59"]
        hist_hit_cond = z3.Or(taps["f62"], any_low_gate, tap9_off_slot)
        new_hist_hit = z3.Or(state["f64"], z3.And(I, hist_hit_cond))

        # 4. row_stars = {f54, f55} and row_count_err, as in left_top_step()
        row_final = 2 * z3.If(f54, 1, 0) + z3.If(f55, 1, 0) + z3.If(I, 1, 0)
        if check_slot:
            new_f54, new_f55 = z3.BoolVal(False), z3.BoolVal(False)
            new_row_count_err = z3.Or(state["f53"], row_final != 2)
        else:
            row_next = z3.If(row_final > 3, 3, row_final)
            new_f54 = row_next >= 2
            new_f55 = z3.Or(row_next == 1, row_next == 3)
            new_row_count_err = state["f53"]

        out = dict(new_taps)
        out["f54"] = new_f54
        out["f55"] = new_f55
        out["f53"] = new_row_count_err
        out["f64"] = new_hist_hit
        return out

    for r, c in order:
        st = zstep(st, cells[(r, c)], r, c)

    s.add(z3.Not(st["f53"]))  # row_count_err must be 0
    s.add(z3.Not(st["f64"]))  # hist_hit must be 0

    solutions = []
    while True:
        res = s.check()
        if res != z3.sat:
            break
        m = s.model()
        sol = frozenset((r, c) for r, c in order if z3.is_true(m.eval(cells[(r, c)], model_completion=True)))
        solutions.append(sol)
        if verbose:
            print(f"  solution {len(solutions)}: {sorted(sol)}")
        # block this exact assignment
        s.add(z3.Or([cells[c] != (c in sol) for c in order]))
        if len(solutions) >= max_solutions:
            break
    return solutions


def grid_from_solution(sol):
    g = [["." for _ in range(11)] for _ in range(11)]
    for r, c in sol:
        g[r][c] = "*"
    return ["".join(row) for row in g]


# ---------------------------------------------------------------------------
# 7. End-to-end validation: simulate the real puzzle_recovered.v top level
#    from reset, feeding the solution's I sequence for 121 enabled cycles,
#    and confirm `success` rises (and stays high).
E2E_TB = """`timescale 1ns/1ps
module tb;
  reg clk=0, rst_n=0, enable=0, I=0;
  wire [7:0] O;
  wire success;
  puzzle_recovered dut(.clk(clk), .rst_n(rst_n), .enable(enable), .I(I), .O(O), .success(success));
  always #5 clk = ~clk;
  reg [0:2047] seqfile;
  integer fd, k, c;
  reg [120:0] iseq;
  initial begin
    if (!$value$plusargs("seq=%s", seqfile)) begin
      $display("ERROR: need +seq=file"); $finish;
    end
    fd = $fopen(seqfile, "r");
    for (k = 0; k < 121; k = k + 1) begin
      c = $fgetc(fd);
      iseq[120-k] = (c == "1") ? 1'b1 : 1'b0;
    end
    $fclose(fd);
    rst_n = 0; enable = 0; I = 0;
    @(posedge clk); @(posedge clk);
    rst_n = 1;
    @(negedge clk);
    enable = 1;
    for (k = 0; k < 121; k = k + 1) begin
      I = iseq[120-k];
      @(posedge clk);
    end
    enable = 0; I = 0;
    #1;
    $display("POST121 success=%b", success);
    // let outgen play out a couple cycles too, success is sticky regardless
    repeat (12) @(posedge clk);
    $display("FINAL success=%b", success);
    $finish;
  end
endmodule
"""


def validate_solution_icarus(sol):
    order = cell_order()
    seq = [1 if (r, c) in sol else 0 for r, c in order]
    seqpath = os.path.join(OUT, "_e2e_seq.txt")
    with open(seqpath, "w") as fh:
        fh.write("".join(str(b) for b in seq))
    tbpath = os.path.join(OUT, "tb_e2e.v")
    with open(tbpath, "w") as fh:
        fh.write(E2E_TB)
    vvp_path = os.path.join(OUT, "tb_e2e.vvp")
    rtl_files = [os.path.join(RTL, n) for n in
                 ["counter.v", "array.v", "left_top.v", "left_bottom.v", "check.v", "outgen.v", "puzzle_recovered.v"]]
    subprocess.run([IVERILOG, "-g2012", "-o", vvp_path] + rtl_files + [tbpath],
                    cwd=REPO, check=True, capture_output=True, text=True)
    res = subprocess.run([VVP, vvp_path, f"+seq={seqpath}"], cwd=REPO, capture_output=True, text=True, timeout=30)
    lines = [l for l in res.stdout.splitlines() if l.startswith("POST121") or l.startswith("FINAL")]
    return lines, res.stdout, res.stderr


# ---------------------------------------------------------------------------
def self_test():
    print("== self-test: cross-checking derived rules against Icarus simulation of rtl_recovered/*.v ==")
    mism, n = verify_cell_order_against_icarus()
    print(f"cell order: {n} log lines checked, {len(mism)} mismatches")
    if mism:
        for m in mism[:10]:
            print("  MISMATCH", m)
        raise SystemExit(1)

    mism, n = verify_region_map_against_icarus()
    print(f"region/column map: {n} states checked against tb_array.log, {mism} mismatches")
    if mism:
        raise SystemExit(1)

    tgt = array_target_per_bin()
    bad = {b: v for b, v in tgt.items() if v != 2}
    print(f"array bin targets from ARRAY_TARGET: {len(tgt)} bins decoded, "
          f"{'all == 2 (confirmed)' if not bad else f'MISMATCH {bad}'}")
    if bad:
        raise SystemExit(1)
    print(f"left_bottom target decimal value: {LEFT_BOTTOM_TARGET} (expect 22)")
    assert LEFT_BOTTOM_TARGET == 22

    mism, n = cross_check_left_top()
    print(f"left_top row_count_err/hist_hit FSM: {n} sequences cross-checked against Icarus rec_left_top, "
          f"{len(mism)} mismatches")
    if mism:
        for m in mism[:10]:
            print("  MISMATCH", m)
        raise SystemExit(1)
    print("== self-test PASS ==")


def main():
    build_testbenches()
    if "--selftest" in sys.argv:
        self_test()
        return

    self_test()

    print()
    print("== DERIVED region map (group A, letters A-K = bins 0-10) ==")
    print(print_region_map())
    regs = region_cells()
    sizes = {k: len(v) for k, v in regs.items()}
    print(f"region sizes: {sizes} (sum={sum(sizes.values())}, expect 121; sizes need NOT be")
    print("equal -- that was an a-priori hypothesis in docs/INTENT.md, REFUTED by this")
    print("simulation: array.v's hitNN equations were minimized by synthesis to be exactly")
    print("correct over all 256 states of {q_f00..q_f07}, not to give 11 equal regions over")
    print("just the 121 reachable ones, so region sizes vary a lot (4..28 here). check.v")
    print("only ever requires each region's saturating counter == 2, which needs no")
    print("particular region size (every region has >= 2 cells, confirmed below).")
    assert sum(sizes.values()) == 121
    assert all(v >= 2 for v in sizes.values())

    print()
    print("== SOLVING (z3, exact FSM/region/column model, enumerating ALL solutions) ==")
    sols = solve_all()
    print(f"\ntotal solutions found: {len(sols)}")

    if sols:
        print()
        print("== VALIDATING solution(s) against puzzle_recovered.v (Icarus, from reset) ==")
        for i, sol in enumerate(sols):
            lines, out, err = validate_solution_icarus(sol)
            print(f"solution {i+1}: {lines}")
            for row in grid_from_solution(sol):
                print("  " + row)


if __name__ == "__main__":
    main()
