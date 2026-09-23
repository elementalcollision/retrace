"""Tests for the S3 harness verifier, tools/s3/verify.py (schema.py "Verification (v2, kind-bound)").

Inline sky130 gate-level netlists (no synthesis, no out/ data except the optional wide-CRC regression
at the end): every template (counter up/down/mod-M/saturating/updown/inverted storage, shift register
with an inverted stage, synchronizer, lfsr_crc), hold/reset/load cases, the flop model's async
controls and clock gating (the proof-soundness review's reproductions), vacuity, the carve-out and
restatement attacks, malformed input, budgets, replay, and permutation invariance of verdicts and of
the canonical CNF.

The "test_v5_*" group is the FREEZE ROUND of 2026-09-23 -- the lead's decisions on the last
proof-soundness review's two blockers and one major, one test each:
  * the hold obligation may not be erased by an OPAQUE LOAD. The reviewer's content-free transform
    (load = [[~l] for l in control.when], a set of load cases whose union is the complement of the
    defining case, and the degenerate load case []) is refused; an empty hold region is accepted only
    where the VERIFIED cases -- defining, when_down, reset -- empty it by themselves, which is what a
    free-running counter looks like with or without an unrelated load case beside it. The PARTIAL
    complement, which leaves a sliver and is checked on it, is pinned as a stated limit, not a fix.
  * an lfsr_crc's params.bit_order is certified only where the polynomial reconstruction PINNED the
    stage order (a real CRC declared with a scrambled order verifies, and says bit_order is not
    certified), and a counter's params.modulus only where the template reads it (with params.
    saturating carrying the limit it does not).
  * the vacuous-hold message states only what was decided.

The "test_blocker2_*" and "test_v21_*" groups are the SECOND proof-soundness re-review (the freeze
round) and schema v2.1's multi-case control, one test per blocker and per major: the counter's
per-bit liveness in its defining region (a step of 2^k made the low template bits the identity, so a
real counter could be prepended with flops that merely hold), the lfsr_crc own matrix's strong
connectivity (which refuses the weight-1 SELF row the v2.0 gates missed), a minimum of 2 synchronizer
stages and 2 counter bits, a BDD "sat" that is inconclusive and falls through to SAT instead of
refuting, the params the harness certifies and those it marks unchecked (including the lfsr
polynomial and k_steps reconstructed from the own matrix), the per-kind control-key sets, the
multi-case control.reset / control.load lists with the hold region outside every named case, the
reported load-case shares and own-bit reads, and the legacy single-case shim. The same attacks are
measured on the frozen development-design snapshot by out/s3/verify/blockers_v4.py and on a
synthesised adversarial netlist by out/s3/verify/attacks_v4.py.

The older "test_blocker_*" group has one test per blocker and major of the first re-review,
each named after what it closes: the counter width / modulus / limit coherence rule (padding a real
counter with foreign flops, and the harness's own range assumption as a carve-out), constant and
word-independent counter templates, the mandatory hold and its reported vacuity, the lfsr_crc
own-matrix gates (zero rows = an opaque restatement of D, dead columns = passenger bits), the async
controls and the clock-gating enable in the self-condition scan (the synthetic cases TEMPO cannot
exercise: it has no async and no logic-gated flop), the coverage obligation that replaced the blanket
self-conditioning ban (with its conservative bound), the flat "order", and the control-key whitelist.
The same attacks are measured on the frozen TEMPO snapshot by out/s3/verify/blockers_v3.py.
"""
import copy
import functools
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.s3 import run as R  # noqa: E402
from tools.s3 import verify as V  # noqa: E402
from tools.s3.netlist import Library, load_verilog  # noqa: E402

P = "sky130_fd_sc_hd__"


def _c(cell, name, **pins):
    return f"  {P}{cell} {name} (" + ", ".join(f".{p}({n})" for p, n in pins.items()) + ");"


def _dff(name, d, q, clk="clk"):
    return _c("dfxtp_1", name, CLK=clk, D=d, Q=q)


def _main_netlist():
    L = []
    # S: 3-stage shift under en (mux2), async reset rstn (dfrtp); stage c stores the complement of stage b
    L += [_c("mux2_1", "ma", A0="sa", A1="din", S="en", X="na"), _c("mux2_1", "mb", A0="sb", A1="sa", S="en", X="nb"),
          _c("inv_1", "ib", A="sb", Y="nbi"), _c("mux2_1", "mc", A0="sc", A1="nbi", S="en", X="nc")]
    L += [_c("dfrtp_1", f"f{x}", CLK="clk", D=f"n{x}", RESET_B="rstn", Q=f"s{x}") for x in "abc"]
    # K: 3-bit up counter under en with a synchronous reset srst
    L += [_c("xor2_1", "xk0", A="k0", B="en", X="x0"), _c("and2_1", "ak1", A="k0", B="en", X="t1"),
          _c("xor2_1", "xk1", A="k1", B="t1", X="x1"), _c("and2_1", "ak2", A="k1", B="t1", X="t2"),
          _c("xor2_1", "xk2", A="k2", B="t2", X="x2")]
    L += [_c("and2b_1", f"rk{i}", A_N="srst", B=f"x{i}", X=f"r{i}") for i in range(3)]
    L += [_dff(f"fk{i}", f"r{i}", f"k{i}") for i in range(3)]
    # M: 3-bit free-running down counter
    L += [_c("inv_1", "im0", A="m0", Y="dm0"), _c("xnor2_1", "xm1", A="m1", B="m0", Y="dm1"),
          _c("nor2_1", "bm2", A="m0", B="m1", Y="b2"), _c("xor2_1", "xm2", A="m2", B="b2", X="dm2")]
    L += [_dff(f"fm{i}", f"dm{i}", f"m{i}") for i in range(3)]
    # P: mod-3 counter under en
    L += [_c("nor2_1", "np0", A="p0", B="p1", Y="u_p0"), _c("mux2_1", "mp0", A0="p0", A1="u_p0", S="en", X="dp0"),
          _c("and2b_1", "ap1", A_N="p1", B="p0", X="u_p1"), _c("mux2_1", "mp1", A0="p1", A1="u_p1", S="en", X="dp1")]
    L += [_dff(f"fp{i}", f"dp{i}", f"p{i}") for i in range(2)]
    # U: 2-bit up counter saturating at 3, under en
    L += [_c("inv_1", "iu0", A="u0", Y="nu0"), _c("or2_1", "ou0", A="nu0", B="u1", X="o0"),
          _c("mux2_1", "mu0", A0="u0", A1="o0", S="en", X="du0"), _c("or2_1", "ou1", A="u0", B="u1", X="o1"),
          _c("mux2_1", "mu1", A0="u1", A1="o1", S="en", X="du1")]
    L += [_dff(f"fu{i}", f"du{i}", f"u{i}") for i in range(2)]
    # W: 2-bit up/down counter (dir 1 up, 0 down) under en
    L += [_c("xor2_1", "xw", A="w0", B="dir", X="xw"), _c("and2b_1", "aw", A_N="xw", B="en", X="tw"),
          _c("xor2_1", "xw0", A="w0", B="en", X="dw0"), _c("xor2_1", "xw1", A="w1", B="tw", X="dw1")]
    L += [_dff(f"fw{i}", f"dw{i}", f"w{i}") for i in range(2)]
    # I: 2-bit up counter under en whose bit 0 is stored inverted
    L += [_c("xor2_1", "xi0", A="i0", B="en", X="di0"), _c("and2b_1", "ai", A_N="i0", B="en", X="ti"),
          _c("xor2_1", "xi1", A="i1", B="ti", X="di1")]
    L += [_dff(f"fi{i}", f"di{i}", f"i{i}") for i in range(2)]
    # Lf: 4-bit Fibonacci LFSR with a data input: l0' = l3 ^ l2 ^ din, l[k]' = l[k-1]
    L += [_c("xor2_1", "xl", A="l3", B="l2", X="xa"), _c("xor2_1", "xl2", A="xa", B="din", X="xb")]
    L += [_dff("fl0", "xb", "l0"), _dff("fl1", "l0", "l1"), _dff("fl2", "l1", "l2"), _dff("fl3", "l2", "l3")]
    # Y: 2-stage synchronizer of ain; Z: a 2-stage chain from flop sa (same clock domain)
    L += [_dff("fy0", "ain", "y0"), _dff("fy1", "y0", "y1"), _dff("fz0", "sa", "z0"), _dff("fz1", "z0", "z1")]
    # H: chain whose last stage is clocked by and2(clk, gen); E: by or2(clk, gen) (enable = !gen)
    L += [_c("and2_1", "gh", A="clk", B="gen", X="hclk"), _dff("fh0", "din", "h0"), _dff("fh1", "h0", "h1"),
          _dff("fh2", "h1", "h2", clk="hclk")]
    L += [_c("or2_1", "ge", A="clk", B="gen", X="eclk"), _dff("fe0", "din", "e0"), _dff("fe1", "e0", "e1"),
          _dff("fe2", "e1", "e2", clk="eclk")]
    # F: chain whose last stage is a falling-edge flop; B: a flop clocked by xor2(clk, gen) (binate)
    L += [_dff("ff0", "din", "g0"), _dff("ff1", "g0", "g1"),
          _c("dfrtn_1", "ff2", CLK_N="clk", D="g1", RESET_B="rstn", Q="g2")]
    L += [_c("xor2_1", "gb", A="clk", B="gen", X="bclk"), _dff("fb0", "din", "bq0"), _dff("fb1", "bq0", "bq1"),
          _dff("fb2", "bq1", "bq2", clk="bclk")]
    # C: chain whose last stage sits behind an ICG (dlclkp, GATE icg_en); Q: last stage a scan flop
    L += [_c("dlclkp_1", "icg", CLK="clk", GATE="icg_en", GCLK="iclk"), _dff("fc0", "din", "c0"),
          _dff("fc1", "c0", "c1"), _dff("fc2", "c1", "c2", clk="iclk")]
    L += [_dff("fq0", "din", "q0"), _dff("fq1", "q0", "q1"),
          _c("sdfxtp_1", "fq2", CLK="clk", D="q1", SCD="din", SCE="scan_en", Q="q2")]
    # X: 12-bit register, x[k]' = x[k-1] for k >= 1, x0' = xor of all 12 bits built as "dual-rail" halves
    # (and2b / nor3b / o21ba) that no gate joins until the end: not syntactically affine -> the BDD path
    L += [_c("and2b_1", "dh1", A_N="xr1", B="xr0", X="h1_0"), _c("and2b_1", "dh2", A_N="xr0", B="xr1", X="h2_0")]
    for k in range(1, 11):
        v = f"xr{k + 1}"
        L += [_c("nor3b_1", f"dg1_{k}", A=f"h1_{k - 1}", B=f"h2_{k - 1}", C_N=v, Y=f"h1_{k}"),
              _c("o21ba_1", f"dg2_{k}", A1=f"h1_{k - 1}", A2=f"h2_{k - 1}", B1_N=v, X=f"h2_{k}")]
    L += [_c("or2_1", "dor", A="h1_10", B="h2_10", X="xfb"), _dff("fx0", "xfb", "xr0")]
    L += [_dff(f"fx{k}", f"xr{k - 1}", f"xr{k}") for k in range(1, 12)]
    # HG / CG: chains every stage of which is clock-gated (and2(clk, gen) / the ICG): unlike H and C
    # these do hold outside their enable, so they are shift registers under schema v2's hold rule
    L += [_dff("fhg0", "din", "hg0", clk="hclk"), _dff("fhg1", "hg0", "hg1", clk="hclk"),
          _dff("fhg2", "hg1", "hg2", clk="hclk")]
    L += [_dff("fcg0", "din", "cg0", clk="iclk"), _dff("fcg1", "cg0", "cg1", clk="iclk"),
          _dff("fcg2", "cg1", "cg2", clk="iclk")]
    # J: a chain whose clock gate is a decode of the chain's own last stage (enable = ~j2)
    L += [_c("inv_1", "ij", A="j2", Y="nj"), _c("and2_1", "gj", A="clk", B="nj", X="jclk"),
          _dff("fj0", "din", "j0", clk="jclk"), _dff("fj1", "j0", "j1", clk="jclk"),
          _dff("fj2", "j1", "j2", clk="jclk")]
    # A: 2-bit up counter under en whose flops async-clear on their own terminal count (a0 & a1)
    L += [_c("xor2_1", "xa0", A="a0", B="en", X="da0"), _c("and2_1", "aa", A="a0", B="en", X="ta"),
          _c("xor2_1", "xa1", A="a1", B="ta", X="da1"), _c("nand2_1", "na", A="a0", B="a1", Y="aclr_n")]
    L += [_c("dfrtp_1", "fa0", CLK="clk", D="da0", RESET_B="aclr_n", Q="a0"),
          _c("dfrtp_1", "fa1", CLK="clk", D="da1", RESET_B="aclr_n", Q="a1")]
    # V: 3-bit up counter under en that reloads to 0 at its own terminal count when ld is high
    # (the wrap / reload the coverage obligation admits: ~load is still reachable at value 7)
    L += [_c("inv_1", "iv0", A="v0", Y="xv0"), _c("xor2_1", "xv1c", A="v1", B="v0", X="xv1"),
          _c("and2_1", "cv", A="v0", B="v1", X="cv2"), _c("xor2_1", "xv2c", A="v2", B="cv2", X="xv2")]
    L += [_c("mux2_1", f"mv{i}", A0=f"v{i}", A1=f"xv{i}", S="en", X=f"uv{i}") for i in range(3)]
    L += [_c("and2_1", "av", A="cv2", B="v2", X="allv"), _c("and2_1", "lv", A="allv", B="ld", X="ldv")]
    L += [_c("and2b_1", f"dv{i}", A_N="ldv", B=f"uv{i}", X=f"nv{i}") for i in range(3)]
    L += [_dff(f"fv{i}", f"nv{i}", f"v{i}") for i in range(3)]
    # R: 3-bit up counter under en with THREE further named cases, which is what schema v2.1's
    # multi-case control.reset / control.load lists exist for: a synchronous clear (srst -> 0), a
    # reload to the constant 5 (ld), and a down step (dec). v2.0 could name one reset COND and one
    # load COND, so one of the three was always left inside the hold region and refuted it.
    L += [_c("inv_1", "irr0", A="mr0", Y="rn0"), _c("xor2_1", "xrr1", A="mr1", B="mr0", X="rx1"),
          _c("and2_1", "arr", A="mr0", B="mr1", X="rc2"), _c("xor2_1", "xrr2", A="mr2", B="rc2", X="rx2"),
          _c("xnor2_1", "yrr1", A="mr1", B="mr0", Y="ry1"), _c("nor2_1", "brr", A="mr0", B="mr1", Y="rb2"),
          _c("xor2_1", "yrr2", A="mr2", B="rb2", X="ry2")]
    L += [_c("mux2_1", f"mre{i}", A0=f"mr{i}", A1=x, S="en", X=f"re{i}")
          for i, x in enumerate(("rn0", "rx1", "rx2"))]
    L += [_c("mux2_1", f"mrd{i}", A0=f"re{i}", A1=x, S="dec", X=f"rg{i}")
          for i, x in enumerate(("rn0", "ry1", "ry2"))]
    L += [_c("or2_1", "mrl0", A="rg0", B="ld", X="rh0"), _c("and2b_1", "mrl1", A_N="ld", B="rg1", X="rh1"),
          _c("or2_1", "mrl2", A="rg2", B="ld", X="rh2")]                       # ld loads the constant 5
    L += [_c("and2b_1", f"mrs{i}", A_N="srst", B=f"rh{i}", X=f"rd{i}") for i in range(3)]
    L += [_dff(f"fr{i}", f"rd{i}", f"mr{i}") for i in range(3)]
    # G: a 2-bit config register written only under wr, so it HOLDS whenever wr = 0. This is the
    # passenger every extent attack rides on (the review's `kept`): a flop that holds through both
    # the defining and the hold region of another structure.
    L += [_c("mux2_1", "mcf0", A0="cf0", A1="din", S="wr", X="ncf0"),
          _c("mux2_1", "mcf1", A0="cf1", A1="ain", S="wr", X="ncf1")]
    L += [_dff("fcf0", "ncf0", "cf0"), _dff("fcf1", "ncf1", "cf1")]
    L += [_c("buf_1", "ob", A="sc", X="o")]
    ins = ["clk", "rstn", "en", "srst", "dir", "din", "gen", "scan_en", "ain", "icg_en", "ld", "dec", "wr"]
    return "module top(" + ", ".join(ins + ["o"]) + ");\n  input " + ", ".join(ins) + ";\n  output o;\n" + \
        "\n".join(L) + "\nendmodule\n"


@functools.cache
def _lib():
    if not os.path.exists(R.SKY_LIB):
        return None
    return Library(R.SKY_LIB)


@functools.cache
def _nl(seed):
    lib = _lib()
    if lib is None:
        pytest.skip("sky130 Liberty absent")
    import tempfile
    d = tempfile.mkdtemp(prefix="s3v-")
    p = os.path.join(d, "top.v")
    with open(p, "w") as f:
        f.write(_main_netlist())
    return load_verilog(p, lib, seed=seed)


class N:
    """Ids of one loaded netlist by name: N.f('fk0') -> flop cell id, N.n('en') -> net id."""

    def __init__(self, seed=None):
        self.nl, self.key = _nl(seed)
        self.cell = {n: i for i, n in enumerate(self.key.cell_name)}
        self.net = {n: i for i, n in enumerate(self.key.net_name)}

    def f(self, name):
        return self.cell[name]

    def n(self, name):
        return self.net[name]

    def w(self, *pairs):
        return [{"net": self.n(a), "value": v} for a, v in pairs]


def S(kind, order, params=None, control=None, claims=None, sid="s"):
    flops = [x for lane in order for x in lane]
    return {"id": sid, "kind": kind, "flops": flops, "order": order, "params": params or {},
            "control": control or {}, "proof": {"status": "proven", "claims": claims or []}}


def verdict(n, s, **kw):
    return V.verify_result(n.nl, {"structures": [s]}, **kw)["structures"][0]


def structures(n):
    """Named structures that verify on the main netlist (built from names, so any id permutation)."""
    f, w = n.f, n.w
    x = {}
    x["K"] = S("counter", [[f("fk0"), f("fk1"), f("fk2")]], {"direction": "up"},
               {"when": w(("en", 1)), "reset": w(("srst", 1)), "reset_value": {str(f(c)): 0 for c in ("fk0", "fk1", "fk2")},
                "hold": True}, sid="K")
    x["M"] = S("counter", [[f("fm0"), f("fm1"), f("fm2")]], {"direction": "down"}, {"when": [], "hold": True}, sid="M")
    x["P"] = S("counter", [[f("fp0"), f("fp1")]], {"direction": "up", "modulus": 3}, {"when": w(("en", 1)), "hold": True},
               sid="P")
    x["U"] = S("counter", [[f("fu0"), f("fu1")]], {"direction": "up", "saturating": True}, {"when": w(("en", 1)),
                                                                                          "hold": True}, sid="U")
    x["W"] = S("counter", [[f("fw0"), f("fw1")]], {"direction": "updown"},
               {"when": w(("en", 1), ("dir", 1)), "when_down": w(("en", 1), ("dir", 0)), "hold": True}, sid="W")
    x["I"] = S("counter", [[f("fi0"), f("fi1")]], {"direction": "up"},
               {"when": w(("en", 1)), "hold": True, "inverted": [f("fi0")]}, sid="I")
    x["Sh"] = S("shift_register", [[f("fa"), f("fb"), f("fc")]], {"lanes": 1, "depth": 3},
                {"when": w(("en", 1)), "hold": True}, sid="Sh")
    q = lambda c: {"q": f(c)}  # noqa: E731
    x["L"] = S("lfsr_crc", [[f("fl0"), f("fl1"), f("fl2"), f("fl3")]], {"form": "fibonacci"},
               {"when": [], "inputs": [n.n("din")]},
               [{"type": "next", "flop": f("fl0"), "equals": {"xor": [q("fl3"), q("fl2"), {"net": n.n("din")}]}},
                {"type": "next", "flop": f("fl1"), "equals": q("fl0")},
                {"type": "next", "flop": f("fl2"), "equals": q("fl1")},
                {"type": "next", "flop": f("fl3"), "equals": q("fl2")}], sid="L")
    x["Y"] = S("synchronizer", [[f("fy0"), f("fy1")]], {"stages": 2}, {"input": n.n("ain")}, sid="Y")
    x["HG"] = S("shift_register", [[f("fhg0"), f("fhg1"), f("fhg2")]], {}, {"when": w(("gen", 1)), "hold": True},
                sid="HG")
    x["CG"] = S("shift_register", [[f("fcg0"), f("fcg1"), f("fcg2")]], {}, {"when": w(("icg_en", 1)), "hold": True},
                sid="CG")
    x["V"] = S("counter", [[f("fv0"), f("fv1"), f("fv2")]], {"direction": "up"},
               {"when": w(("en", 1)), "load": w(("ldv", 1)), "hold": True}, sid="V")   # legacy load COND
    # R: schema v2.1's multi-case lists -- two reset cases with their own values (clear to 0, reload
    # to 5) and one load case (the down step), so the hold region is what is left outside all four.
    x["R"] = S("counter", [[f("fr0"), f("fr1"), f("fr2")]], {"direction": "up", "modulus": 8},
               {"when": w(("en", 1)),
                "reset": [{"when": w(("srst", 1)), "value": {str(f(c)): 0 for c in ("fr0", "fr1", "fr2")}},
                          {"when": w(("ld", 1)),
                           "value": {str(f("fr0")): 1, str(f("fr1")): 0, str(f("fr2")): 1}}],
                "load": [w(("dec", 1))], "hold": True}, sid="R")
    xr = [f(f"fx{k}") for k in range(12)]
    x["X"] = S("lfsr_crc", [xr], {}, {"when": []},
               [{"type": "next", "flop": xr[0], "equals": {"xor": [{"q": c} for c in xr]}}] +
               [{"type": "next", "flop": xr[k], "equals": {"q": xr[k - 1]}} for k in range(1, 12)], sid="X")
    return x


# ----------------------------------------------------------------------------------------------
# templates


def test_every_template_verifies():
    n = N()
    xs = structures(n)
    rep = V.verify_result(n.nl, {"structures": list(xs.values())})
    got = {s["id"]: (s["verified"], s["reason"]) for s in rep["structures"]}
    assert all(v for v, _r in got.values()), got
    by = {s["id"]: s for s in rep["structures"]}
    assert by["Sh"]["inverted_edges"] == 1                      # stage c stores ~stage b
    assert by["M"]["checks"]["hold"].startswith("vacuous")      # free running: no hold case, not a failure
    assert by["K"]["checks"] == {"defining": 3, "hold": 3, "reset": 3}
    assert by["W"]["checks"]["defining_down"] == 2
    assert by["P"]["domain"]["top"] == 2 and by["U"]["template"].startswith("counter up by 1, saturating at 3")
    assert 0.2 < by["K"]["lane_share"]["when"] < 0.3 and by["K"]["lane_share"]["reset"] > 0.4   # en & ~srst; srst
    assert by["M"]["lane_share"]["when"] == 1.0 and by["P"]["lane_share"]["when"] < 0.5      # range 0..2 of 0..3
    # V reloads at its own terminal count: the coverage obligation ranges over the 3 own bits ~load
    # reads and finds the defining case reachable at every one of the 8 values (ld = 0)
    assert by["V"]["coverage"]["when"] == {"own_bits": 3, "values": 8, "status": "covered"}
    assert by["V"]["self_conditioned"]["load"] == 1 and by["K"]["coverage"]["when"]["status"] == "free"
    assert rep["summary"]["verified_by_kind"]["counter"] == [8, 8]
    assert rep["summary"]["method_bdd"] >= 1                     # X's dual-rail XOR goes through the BDD path
    assert rep["summary"].get("exceptions", 0) == 0
    # every counter bit is proven to MOVE in its defining region (schema v2.1's extent rule)
    assert by["K"]["live_bits"] == [0, 1, 2] and by["K"]["dead_bits"] == []
    assert by["W"]["live_bits"] == [0, 1] and by["R"]["live_bits"] == [0, 1, 2]
    # R names four cases; the hold region is what is left outside all of them
    assert by["R"]["cases"] == {"reset": 2, "load": 1, "when_down": False, "hold": True}
    assert by["R"]["checks"] == {"defining": 3, "hold": 3, "reset[0]": 3, "reset[1]": 3}
    assert by["R"]["nonvacuity"]["hold"] == "sat" and not by["R"].get("hold_vacuous")
    assert [c["own_bits_read"] for c in by["R"]["load_cases"]] == [0]
    assert 0.4 < by["R"]["load_hidden_share"] < 0.6                    # dec alone
    assert by["R"]["control_form"] == "v2.1" and by["K"]["control_form"] == "legacy"
    assert rep["summary"]["legacy_control_form"] >= 1 and rep["summary"]["multi_case_structures"] == 1


@pytest.mark.parametrize("sid,mutate,why", [
    ("K", lambda s: s["order"][0].reverse(), "refuted"),
    ("K", lambda s: s["params"].update(direction="down"), "refuted"),
    ("K", lambda s: s["params"].update(step=2), "template"),   # bit 0 then never moves: a dead bit
    ("K", lambda s: s["control"].update(when=[]), "refuted"),                      # holds when en = 0
    ("K", lambda s: s["control"].update(reset_value={k: 1 for k in s["control"]["reset_value"]}), "refuted"),
    ("K", lambda s: (s["control"].pop("reset"), s["control"].pop("reset_value")), "refuted"),  # hold under srst
    ("M", lambda s: s["params"].update(direction="up"), "refuted"),
    ("P", lambda s: s["params"].update(modulus=4), "refuted"),
    ("P", lambda s: s["params"].update(modulus=None), "refuted"),
    ("U", lambda s: s["params"].update(saturating=False), "refuted"),
    ("U", lambda s: s["params"].update(saturating=2), "refuted"),
    ("W", lambda s: s["control"].update(when_down=s["control"]["when"]), "vacuous"),
    ("W", lambda s: s["params"].update(direction="up"), "params"),     # a down case with no updown
    ("W", lambda s: (s["params"].update(direction="up"), s["control"].pop("when_down")), "refuted"),
    ("R", lambda s: s["control"]["reset"][1]["value"].update({str(s["flops"][1]): 1}), "refuted"),
    ("R", lambda s: s["control"]["reset"].reverse(), "refuted"),        # list order is priority
    ("R", lambda s: s["control"].pop("load"), "refuted"),               # dec then falls in the hold region
    ("R", lambda s: s["control"]["reset"].pop(), "refuted"),            # ld then falls in the hold region
    ("I", lambda s: s["control"].pop("inverted"), "refuted"),
    ("Sh", lambda s: s["order"][0].reverse(), "refuted"),
    ("Sh", lambda s: s["params"].update(depth=4), "params"),
    ("Sh", lambda s: s["control"].update(when=[]), "refuted"),
    ("Sh", lambda s: (s["order"][0].pop(), s["flops"].pop()), "template"),        # depth 2 < 3
    ("L", lambda s: s["proof"]["claims"][1].__setitem__("equals", {"xor": [{"q": s["flops"][0]},
                                                                          {"q": s["flops"][3]}]}), "refuted"),
    ("L", lambda s: s["proof"]["claims"][0]["equals"]["xor"].__setitem__(0, {"q": s["flops"][1]}), "form"),
    ("L", lambda s: s["proof"]["claims"][0]["equals"]["xor"].pop(0), "form"),     # one own bit left: a shift
    ("L", lambda s: s["control"].update(inputs=[]), "form"),                        # din not an input
    ("L", lambda s: s["proof"]["claims"].pop(), "form"),                            # a flop without a claim
    ("Y", lambda s: s["control"].update(when=[{"net": s["control"]["input"], "value": 1}]), "template"),
    ("Y", lambda s: s["params"].update(stages=3), "params"),
    ("X", lambda s: s["proof"]["claims"][0]["equals"]["xor"].pop(5), "refuted"),   # refuted by the BDD path
])
def test_template_mutations_do_not_verify(sid, mutate, why):
    n = N()
    s = copy.deepcopy(structures(n)[sid])
    mutate(s)
    r = verdict(n, s)
    assert not r["verified"] and r["bucket"] == why, r["reason"]


def test_kind_swaps_do_not_verify():
    """The kind binds the template: every verified structure relabelled to another scored kind fails,
    except where two definitions overlap by design (a Fibonacci LFSR is also a shift register whose
    stage 0 is logic; a 1-bit counter counts the same way up and down)."""
    n = N()
    for sid, s in structures(n).items():
        for k in V.schema.STRUCTURE_KINDS:
            if k == s["kind"] or (sid in ("L", "X") and k == "shift_register"):
                continue
            t = copy.deepcopy(s)
            t["kind"] = k
            t["control"] = {a: b for a, b in t["control"].items() if a in V.CONTROL_KEYS_BY_KIND[k]}
            assert not verdict(n, t)["verified"], (sid, k)
    t = copy.deepcopy(structures(n)["L"])
    t["kind"], t["control"]["hold"] = "shift_register", True   # hold is required for the kind (v2)
    t["control"].pop("inputs")                                 # control.inputs is not a shift's key
    assert verdict(n, t)["verified"]            # documented overlap (measured: 12 corpus LFSRs)


# ----------------------------------------------------------------------------------------------
# flop model: async controls and clocks (the proof-soundness review's reproductions)


def test_async_reset_is_never_a_claimable_case():
    """dfrtp stages with RESET_B = rstn: a defining case with rstn = 0 is vacuous (claims hold only
    with async controls inactive); so is a 'synchronous reset' case that is the async reset; the
    legacy single-claim check agrees ('next = din when rstn = 0' no longer verifies)."""
    n = N()
    s = copy.deepcopy(structures(n)["Sh"])
    s["control"]["when"] = n.w(("en", 1), ("rstn", 0))
    r = verdict(n, s)
    assert r["bucket"] == "vacuous", r["reason"]
    s = copy.deepcopy(structures(n)["Sh"])
    s["control"].update(reset=n.w(("rstn", 0)), reset_value={str(x): 0 for x in s["flops"]})
    r = verdict(n, s)
    assert r["bucket"] == "vacuous" and "reset" in r["reason"], r["reason"]
    ver = V.Verifier(n.nl)
    din = {"net": n.n("din")}
    assert ver.check_claim({"type": "next", "flop": n.f("fa"), "equals": din, "when": n.w(("en", 1)),
                            "role": "defining"})["verified"]
    for when in (n.w(("en", 1), ("rstn", 0)),):
        for eq in (din, {"const": 0}):
            v = ver.check_claim({"type": "next", "flop": n.f("fa"), "equals": eq, "when": when, "role": "defining"})
            assert not v["verified"] and v["reason"].startswith("vacuous"), v


def _partly_gated(n):
    """Chains whose LAST stage only is gated (and2(clk, gen) / or2(clk, gen) / an ICG / a scan flop):
    the defining case is right for that stage and wrong for the two before it, which copy every
    clock. Under schema v2 they are not shift registers: they do not hold outside `when`."""
    f, w = n.f, n.w
    return {"H": (S("shift_register", [[f("fh0"), f("fh1"), f("fh2")]], {}, {"when": w(("gen", 1))}, sid="H"),
                  n.w(("gen", 0))),
            "E": (S("shift_register", [[f("fe0"), f("fe1"), f("fe2")]], {}, {"when": w(("gen", 0))}, sid="E"),
                  n.w(("gen", 1))),
            "C": (S("shift_register", [[f("fc0"), f("fc1"), f("fc2")]], {}, {"when": w(("icg_en", 1))}, sid="C"),
                  n.w(("icg_en", 0))),
            "Q": (S("shift_register", [[f("fq0"), f("fq1"), f("fq2")]], {}, {"when": w(("scan_en", 0))}, sid="Q"),
                  n.w(("scan_en", 1)))}


def test_clock_gating_logic_is_an_enable():
    """and2(clk, gen): the stage copies only when gen = 1 (always -> refuted); or2(clk, gen): only when
    gen = 0; an ICG and a scan flop likewise; xor2(clk, gen) is binate: unsupported clock; a
    falling-edge stage in a rising-edge chain: two clock domains. A chain every stage of which is
    gated (HG, CG) is a shift register and holds; a chain only whose last stage is gated is not."""
    n = N()
    xs = structures(n)
    assert verdict(n, xs["HG"])["verified"] and verdict(n, xs["CG"])["verified"]
    for sid, (s, bad) in _partly_gated(n).items():
        r = verdict(n, dict(s, control=dict(s["control"], hold=True)))
        assert not r["verified"] and r["bucket"] == "refuted", (sid, r["reason"])   # stage 0/1 never hold
        assert verdict(n, s)["bucket"] == "hold", sid                               # and hold is required
        for when in ([], bad):
            t = copy.deepcopy(s)
            t["control"] = {"when": when, "hold": True}
            r = verdict(n, t)
            assert not r["verified"] and r["bucket"] in ("refuted", "vacuous"), (sid, when, r["reason"])
    r = verdict(n, S("shift_register", [[n.f("fb0"), n.f("fb1"), n.f("fb2")]], {}, {"hold": True}))
    assert r["bucket"] == "clock domains" or r["bucket"] == "unsupported clock", r["reason"]
    r = verdict(n, S("shift_register", [[n.f("fb2")]], {}, {"hold": True}))
    assert r["bucket"] == "unsupported clock" and "binate" in r["reason"]
    r = verdict(n, S("shift_register", [[n.f("ff0"), n.f("ff1"), n.f("ff2")]], {}, {"hold": True}))
    assert r["bucket"] == "clock domains"
    ver = V.Verifier(n.nl)
    assert ver.model[n.f("fh2")]["gated"] and ver.model[n.f("fe2")]["domain"] == ver.model[n.f("fe0")]["domain"]
    assert ver.model[n.f("ff2")]["domain"][1] == 1 and ver.model[n.f("fa")]["async"]


def test_synchronizer_input_rules():
    n = N()
    q = lambda c: {"q": n.f(c)}  # noqa: E731, F841
    z = S("synchronizer", [[n.f("fz0"), n.f("fz1")]], {}, {"input": n.n("sa")})
    r = verdict(n, z)
    assert r["bucket"] == "template" and "another clock domain" in r["reason"]
    r = verdict(n, S("synchronizer", [[n.f("fy0"), n.f("fy1")]], {}, {}))
    assert r["bucket"] == "template" and "control.input" in r["reason"]
    r = verdict(n, S("synchronizer", [[n.f("fy0"), n.f("fy1")]], {}, {"input": n.n("din")}))
    assert r["bucket"] == "refuted"
    r = verdict(n, S("synchronizer", [[n.f("fy0"), n.f("fy1")]], {}, {"input": n.n("ain"), "load": n.w(("en", 1))}))
    assert r["bucket"] == "template"


# ----------------------------------------------------------------------------------------------
# vacuity, carve-outs and restatements


def test_vacuous_conditions():
    n = N()
    k = copy.deepcopy(structures(n)["K"])
    k["control"]["when"] = n.w(("en", 1), ("en", 0))
    assert verdict(n, k)["bucket"] == "vacuous"
    k = copy.deepcopy(structures(n)["K"])
    k["control"]["when"] = n.w(("en", 1), ("srst", 1))          # only with the reset active
    assert verdict(n, k)["bucket"] == "vacuous"
    k = copy.deepcopy(structures(n)["K"])
    k["control"]["load"] = n.w(("en", 1))                       # the load covers the whole defining case
    assert verdict(n, k)["bucket"] == "vacuous"


def test_carve_outs_and_restatements_never_verify():
    """A condition may read the structure's own state only as the coverage obligation admits: any
    flop is otherwise a 1-bit 'counter' under when = [its D net = 1, its Q net = 0] (verified with
    the obligation off, to show why it exists), or under when = [D = 1] with load = [Q = 1]. An
    lfsr_crc input net that depends on the own state (a restatement of D), an XOR claim of a pure
    shift, an AND claim, a constant claim, and an unscored kind never verify."""
    n = N()
    f, f2 = n.f("fa"), n.f("fb")
    # the 1-bit reading of the carve-out is now refused for its width alone (COUNTER_MIN_WIDTH)
    r1 = verdict(n, S("counter", [[f]], {"direction": "up"}, {"when": n.w(("na", 1), ("sa", 0)), "hold": True}))
    assert r1["bucket"] == "template" and "width" in r1["reason"], r1["reason"]
    # a 2-bit word, so the refusal is the coverage obligation and not the width
    carve = S("counter", [[f, f2]], {"direction": "up"}, {"when": n.w(("na", 1), ("sa", 0)), "hold": True})
    r = verdict(n, carve)
    assert r["bucket"] == "coverage" and r["self_conditioned"]["when"] == 2, r["reason"]
    assert r["coverage"]["when"] == {"own_bits": 1, "values": 2, "status": "uncovered", "uncovered_bits": 1}
    # with the coverage obligation off the v2.1 liveness rule refuses it instead (bit 1 cannot move
    # in the carved region), and with both off the hold case did: three independent rules
    off = verdict(n, carve, self_conditions_allowed=True)
    assert off["bucket"] == "template" and "never move" in off["reason"], off["reason"]
    carve2 = S("counter", [[f, f2]], {"direction": "up"},
               {"when": n.w(("na", 1)), "load": n.w(("sa", 1)), "hold": True})
    assert verdict(n, carve2)["bucket"] == "coverage"
    off2 = verdict(n, carve2, self_conditions_allowed=True)
    assert off2["bucket"] == "template" and "never move" in off2["reason"], off2["reason"]
    xs = structures(n)
    lf = copy.deepcopy(xs["L"])
    lf["control"]["inputs"] = [n.n("din"), n.n("xb")]            # xb = D of l0
    lf["proof"]["claims"][0]["equals"] = {"net": n.n("xb")}
    r = verdict(n, lf)
    assert r["bucket"] == "form" and "own state" in r["reason"]
    ring = [n.f(c) for c in ("fl0", "fl1", "fl2", "fl3")]      # every row weight 1, every column read
    sh = S("lfsr_crc", [ring], {}, {},
           [{"type": "next", "flop": ring[k], "equals": {"q": ring[k - 1]}} for k in range(4)])
    r = verdict(n, sh)
    assert r["bucket"] == "form" and "permutation" in r["reason"], r["reason"]
    lf = copy.deepcopy(xs["L"])
    lf["proof"]["claims"][0]["equals"] = {"and": [{"q": n.f("fl3")}, {"q": n.f("fl2")}]}
    assert verdict(n, lf)["bucket"] == "form"
    one = S("lfsr_crc", [[f]], {}, {"when": n.w(("na", 1))}, [{"type": "next", "flop": f, "equals": {"const": 1}}])
    assert verdict(n, one)["bucket"] in ("form", "self-conditioned")
    dr = S("data_register", [[f]], {}, {}, [{"type": "next", "flop": f, "equals": {"net": n.n("na")}}])
    r = verdict(n, dr)
    assert r["bucket"] == "unscored kind" and not r["scored"]


# ----------------------------------------------------------------------------------------------
# the proof-soundness re-review's blockers (review[0] of the re-review round), one test each


def test_blocker_counter_width_modulus_limit_must_agree():
    """review[0] blockers 2 and 3(a) (WIDTH INFLATION, the `dom` carve-out). A word's width must
    need every one of its bits: 2^(w-1) < modulus <= 2^w and limit >= 2^(w-1). Without it the range
    assumption pins the claimed high bits to 0, so (a) any set of flops that a condition forces to 0
    verifies as a wide "saturating at 1" counter and (b) a real counter can be padded with foreign
    flops whose next state happens to be 0 whenever they are 0."""
    n = N()
    f, w = n.f, n.w
    wide = [f(c) for c in ("fk0", "fk1", "fk2", "fy0", "fy1")]          # a real 3-bit counter + 2 strangers
    for params, tag in (({"direction": "down", "saturating": 1}, "saturation limit 1"),
                        ({"direction": "up", "modulus": 8}, "params.modulus 8"),
                        ({"direction": "up", "modulus": 16}, "params.modulus 16")):   # 16 <= 2^(5-1): dead bit
        r = verdict(n, S("counter", [wide], params, {"when": w(("en", 1)), "hold": True}))
        assert r["bucket"] == "template" and tag in r["reason"], (params, r["reason"])
        assert "dead" in r["reason"]
    # the coherent declaration of the same padded word is refuted by the templates themselves
    r = verdict(n, S("counter", [wide], {"direction": "up", "modulus": 32}, {"when": w(("en", 1)), "hold": True}))
    assert r["bucket"] == "refuted", r["reason"]
    # and a modulus that does need every bit (mod 3 on 2 bits, mod 17 on 5 bits) is untouched
    assert verdict(n, structures(n)["P"])["verified"]
    r = verdict(n, S("counter", [[f("fk0"), f("fk1"), f("fk2")]], {"direction": "up", "modulus": 5},
                     {"when": w(("en", 1)), "hold": True}))
    assert r["bucket"] == "refuted", r["reason"]          # coherent (4 < 5 <= 8), simply not true here


def test_blocker_constant_or_word_independent_counter_templates():
    """review[0] blocker 1 (a width-1 saturating counter has a CONSTANT template, so any flop forced
    to a constant by a condition verified as a counter: 2,854 of 2,890 such structures on TEMPO).
    The saturating map is constant exactly when step >= limit; the built word is also checked."""
    n = N()
    f, w = n.f, n.w
    for d in ("up", "down"):
        p = {"direction": d, "step": 2, "saturating": 2}      # step >= limit: min(w + 2, 2) is constant
        r = verdict(n, S("counter", [[f("fk0"), f("fk1")]], p, {"when": w(("srst", 1)), "hold": True}))
        assert r["bucket"] == "template" and "constant" in r["reason"], (d, r["reason"])
        # the obligation is not the coverage one: switching coverage off changes nothing
        assert verdict(n, S("counter", [[f("fk0"), f("fk1")]], p, {"when": w(("srst", 1)), "hold": True}),
                       self_conditions_allowed=True)["bucket"] == "template"
    # 3 bits saturating at 4 is not constant (4 > step) and is checked on its merits
    r = verdict(n, S("counter", [[f("fk0"), f("fk1"), f("fk2")]], {"direction": "up", "saturating": 4},
                     {"when": w(("en", 1)), "hold": True}))
    assert r["bucket"] == "refuted", r["reason"]


def test_blocker_hold_is_required_and_non_vacuous(monkeypatch):
    """review[0]'s hold finding: control.hold is what refutes the degenerate counters, and it was
    optional, unrewarded by the scorer and the one case with no non-vacuity check. It is now
    required for counter and shift_register, and its region is decided by SAT and reported instead
    of passing silently on the syntactic `0 in region`. An empty hold region is accepted only when
    the VERIFIED cases empty it (see test_v5_hold_may_not_be_emptied_by_an_opaque_load);
    HOLD_MUST_BE_NONVACUOUS refuses every empty hold region."""
    n = N()
    xs = structures(n)
    for sid in ("K", "M", "P", "U", "W", "I", "Sh", "HG", "CG", "V"):
        s = copy.deepcopy(xs[sid])
        s["control"].pop("hold")
        r = verdict(n, s)
        assert r["bucket"] == "hold" and "required" in r["reason"], (sid, r["reason"])
        assert verdict(n, dict(s, control=dict(s["control"], hold=False)))["bucket"] == "hold", sid
    assert verdict(n, xs["L"])["verified"] and verdict(n, xs["Y"])["verified"]   # not required of these two
    # the free-running counter M (when = []) has no hold states at all: its empty hold region is
    # emptied by the DEFINING case, is accepted, reported and counted
    r = verdict(n, xs["M"])
    assert r["verified"] and r["hold_vacuous"] and r["hold_vacuous_cover"] == "verified"
    assert r["nonvacuity"]["hold"] == "unsat" and r["checks"]["hold"].startswith("vacuous")
    assert V.verify_result(n.nl, {"structures": [xs["M"], xs["K"]]})["summary"]["verified_vacuous_hold"] == 1
    # K's hold region is a real region and its obligations are really checked
    k = verdict(n, xs["K"])
    assert k["nonvacuity"]["hold"] == "sat" and k["checks"]["hold"] == 3
    # HOLD_MUST_BE_NONVACUOUS is the blunter measurement switch: it refuses EVERY empty hold region,
    # the free-running counter's included (it was "refuse one a load emptied" before 2026-09-23, a
    # test the lead's rule now subsumes). K, whose hold region is non-empty, is untouched by it.
    monkeypatch.setattr(V, "HOLD_MUST_BE_NONVACUOUS", True)
    r = verdict(n, xs["M"])
    assert r["bucket"] == "vacuous" and "hold region is empty" in r["reason"], r["reason"]
    assert verdict(n, xs["K"])["verified"]
    monkeypatch.setattr(V, "HOLD_MUST_BE_NONVACUOUS", False)
    assert verdict(n, xs["M"])["verified"] and verdict(n, xs["K"])["verified"]


def test_blocker_lfsr_own_matrix_bounds_the_structure():
    """review[0] blocker 3(b): a verified CRC could be extended with foreign flops, each carrying
    {"equals": {"net": <its own D net>}} (a zero row: an opaque restatement of D) or simply never
    read (a dead column). Both are refused, and the real LFSR still verifies."""
    n = N()
    xs = structures(n)
    own = xs["L"]["flops"]
    pad = copy.deepcopy(xs["L"])
    pad["flops"] = own + [n.f("fy0")]
    pad["order"] = [pad["flops"]]
    pad["control"]["inputs"] = [n.n("din"), n.n("ain")]                  # ain = D of fy0, no own state
    pad["proof"]["claims"].append({"type": "next", "flop": n.f("fy0"), "equals": {"net": n.n("ain")}})
    r = verdict(n, pad)
    assert r["bucket"] == "form" and "restates that flop's D" in r["reason"], r["reason"]
    assert r["own_matrix"]["zero_rows"] == 1
    dead = copy.deepcopy(pad)
    dead["proof"]["claims"][-1]["equals"] = {"xor": [{"q": own[3]}, {"q": own[2]}]}   # row fine, column dead
    r = verdict(n, dead)
    assert r["bucket"] == "form" and "dead column" in r["reason"], r["reason"]
    assert r["own_matrix"]["dead_columns"] == 1 and r["own_matrix"]["zero_rows"] == 0
    assert verdict(n, xs["L"])["verified"]


def test_blocker_async_controls_and_clock_enable_are_scanned():
    """review[0]'s flop-model finding: the async clear/preset and the clock-gating enable folded
    into the effective next state were outside the self-conditioning scan, so an async control
    decoding the structure's own state removed exactly those states from every obligation,
    unreported. TEMPO has neither (0 async, 0 logic-gated flops), so this is the synthetic case the
    review asked for: a counter async-cleared at its own terminal count, and a chain whose clock
    gate decodes its own last stage."""
    n = N()
    f, w = n.f, n.w
    ac = S("counter", [[f("fa0"), f("fa1")]], {"direction": "up"}, {"when": w(("en", 1)), "hold": True})
    r = verdict(n, ac)
    assert r["bucket"] == "coverage" and r["self_conditioned"]["async"] == 1, r["reason"]
    assert r["coverage"]["when"]["status"] == "uncovered" and r["coverage"]["when"]["uncovered_bits"] == 3
    assert verdict(n, ac, self_conditions_allowed=True)["verified"]    # what the scan used to miss
    j = S("shift_register", [[f("fj0"), f("fj1"), f("fj2")]], {}, {"when": [], "hold": True})
    r = verdict(n, j)
    assert r["bucket"] == "self-conditioned" and "clock-gating enable" in r["reason"], r["reason"]
    assert r["self_conditioned"]["clock_enable"] == 3
    # the rule is not switchable: coverage cannot express an enable folded into the next state
    assert verdict(n, j, self_conditions_allowed=True)["bucket"] == "self-conditioned"
    # the same gate read from outside the structure is an ordinary enable (fj2 left out)
    r = verdict(n, S("shift_register", [[f("fj0"), f("fj1")]], {}, {"when": [], "hold": True}))
    assert r["bucket"] == "template" and "depth" in r["reason"], r["reason"]   # depth 2 < 3, not self-conditioned


def test_blocker_coverage_replaces_the_blanket_self_conditioning_ban(monkeypatch):
    """review[0]'s coverage proposal: the defining region must be reachable for every own-word value
    in range. It admits a wrap or reload at a terminal count (V: 8 of 8 values reachable, the blanket
    ban refused it) and refuses a case carved down to some own states (the 1-bit carve-out above).
    Past COVERAGE_MAX_OWN_BITS read own bits the structure is refused, not admitted."""
    n = N()
    xs = structures(n)
    r = verdict(n, xs["V"])
    assert r["verified"] and r["self_conditioned"]["load"] == 1          # the old ban refused exactly this
    assert r["coverage"]["when"] == {"own_bits": 3, "values": 8, "status": "covered"}
    monkeypatch.setattr(V, "COVERAGE_MAX_OWN_BITS", 2)
    r = verdict(n, xs["V"])
    assert r["bucket"] == "coverage" and "not enumerable" in r["reason"], r["reason"]
    assert r["coverage"]["when"]["status"] == "too wide"
    monkeypatch.setattr(V, "COVERAGE_MAX_OWN_BITS", 12)
    monkeypatch.setattr(V, "COVERAGE_CALLS_PER_RUN", 2)
    r = verdict(n, xs["V"])
    assert r["bucket"] == "budget" and "coverage" in r["reason"], r["reason"]
    assert verdict(n, xs["K"])["verified"]        # a structure whose conditions read no own bit is free


def test_blocker_flat_order_is_malformed():
    """review[0]'s "order" finding: verify.py accepted a flat order that run.py's
    validate_result_types and schema.check_result reject, and a type problem invalidates the whole
    run. Only params.bit_order (one word, LSB first) may be flat."""
    n = N()
    k = structures(n)["K"]
    r = verdict(n, dict(k, order=k["flops"]))
    assert r["bucket"] == "malformed" and "flat list" in r["reason"], r["reason"]
    sh = structures(n)["Sh"]                       # params.order (shift / synchronizer) is lanes too
    r = verdict(n, dict(sh, order=None, params=dict(sh["params"], order=sh["flops"])))
    assert r["bucket"] == "malformed" and "flat list" in r["reason"], r["reason"]
    assert verdict(n, dict(k, order=None, params=dict(k["params"], bit_order=k["flops"])))["verified"]
    assert verdict(n, dict(k, params=dict(k["params"], bit_order=k["flops"])))["verified"]


def test_blocker_control_keys_follow_the_schema():
    """review[0]'s control finding: unknown control keys were processed and reported identically to
    a structure without them, so a result could carry arbitrary undeclared fields. The keys are
    exactly schema.py's, when_down and inverted included (both load-bearing here)."""
    n = N()
    xs = structures(n)
    r = verdict(n, dict(xs["K"], control=dict(xs["K"]["control"], bogus_field=1)))
    assert r["bucket"] == "malformed" and "unknown key" in r["reason"], r["reason"]
    assert set(V.CONTROL_KEYS) == {"when", "when_down", "reset", "reset_value", "load", "hold", "inverted",
                                   "input", "inputs"}
    wd = copy.deepcopy(xs["W"])
    wd["control"].pop("when_down")     # "updown" without the down case: half the claim is unproven
    r = verdict(n, wd)
    assert r["bucket"] == "params" and "when_down" in r["reason"], r["reason"]
    iv = copy.deepcopy(xs["I"])
    iv["control"].pop("inverted")
    assert verdict(n, iv)["bucket"] == "refuted"


# ----------------------------------------------------------------------------------------------
# the SECOND proof-soundness re-review (review[0] of the freeze round) and schema v2.1's
# multi-case control: one test per blocker and per major, named after what it closes


def _padded_counter(n, pad, real, step, modulus):
    """A real counter prepended with `pad` flops that merely HOLD under the defining case, declared
    with step = 2^len(pad) so the low template bits are the identity: the review's extent attack.
    The pad register (fcf*) is written only under wr, so wr is named as a load case."""
    f, w = n.f, n.w
    word = [f(c) for c in pad] + [f(c) for c in real]
    return S("counter", [word], {"direction": "up", "step": step, "modulus": modulus},
             {"when": w(("en", 1), ("wr", 0), ("srst", 0)), "load": [w(("wr", 1)), w(("srst", 1))],
              "hold": True}, sid="pad")


def test_blocker2_counter_extent_needs_per_bit_liveness(monkeypatch):
    """review[0] blocker 1 (the FIRST blocker of the second re-review): width / modulus / limit
    coherence does not bound a counter's extent, because a step of 2^k makes the low k template bits
    the IDENTITY. A real 3-bit counter prepended with 1 or 2 flops of a config register that holds
    under the defining case verifies as a 4- or 5-bit counter stepping by 2 or 4, and no real counter
    is needed at all. Every claimed bit must move in the defining region."""
    n = N()
    pad1 = _padded_counter(n, ("fcf0",), ("fk0", "fk1", "fk2"), 2, 16)
    pad2 = _padded_counter(n, ("fcf0", "fcf1"), ("fk0", "fk1", "fk2"), 4, 32)
    fab = _padded_counter(n, ("fcf0", "fcf1"), ("fk0",), 4, 8)          # no real counter word at all
    for s, dead in ((pad1, [0]), (pad2, [0, 1]), (fab, [0, 1])):
        r = verdict(n, s)
        assert r["bucket"] == "template" and "never move" in r["reason"], r["reason"]
        assert r["dead_bits"] == dead and r["live_bits"] == [i for i in range(r["n_flops"]) if i not in dead]
        # every v2.0 gate passed on it: this is what made the attack invisible in the verdict record
        assert r["coverage"]["when"]["status"] == "free" and r["nonvacuity"]["when"] == "sat"
    # and with the liveness rule switched off they verify, which is the measurement of what it costs
    monkeypatch.setattr(V._Ctx, "_liveness", lambda self, *a: None)
    for s in (pad1, pad2, fab):
        assert verdict(n, s)["verified"], s["id"]
    monkeypatch.undo()
    # the honest counters keep their bits and report them
    for sid in ("K", "M", "P", "U", "W", "I", "V", "R"):
        r = verdict(n, structures(n)[sid])
        assert r["verified"] and r["live_bits"] == list(range(r["n_flops"])) and r["dead_bits"] == []


def test_blocker2_lfsr_extent_needs_a_strongly_connected_own_matrix():
    """review[0] blocker 2: the v2.0 own-matrix gates (no zero row, no dead column, row weight >= 2)
    do not refuse a weight-1 SELF row, so a foreign flop that merely holds under control.when could
    be carried on a verified CRC with the claim {"equals": {"q": itself}} -- reproduced on TEMPO
    against its recorded result. Strong connectivity of the own matrix refuses it and subsumes the
    other two gates."""
    n = N()
    xs = structures(n)
    lf = copy.deepcopy(xs["L"])
    lf["control"]["when"] = n.w(("en", 0), ("srst", 0))    # a region in which fk0 holds
    assert verdict(n, lf)["verified"], "the real LFSR still verifies under the narrowed case"
    pad = copy.deepcopy(lf)
    pad["flops"] = pad["flops"] + [n.f("fk0")]
    pad["order"] = [pad["flops"]]
    pad["proof"]["claims"].append({"type": "next", "flop": n.f("fk0"), "equals": {"q": n.f("fk0")}})
    r = verdict(n, pad)
    assert r["bucket"] == "form" and "strongly connected" in r["reason"], r["reason"]
    om = r["own_matrix"]
    # the three v2.0 gates all pass on it -- that is exactly why it used to verify
    assert om["zero_rows"] == 0 and om["dead_columns"] == 0 and not om["permutation"] \
        and om["max_row_weight"] == 2
    assert om["strongly_connected"] is False and om["self_only_rows"] == 1
    assert verdict(n, xs["L"])["own_matrix"]["strongly_connected"] is True
    assert verdict(n, xs["X"])["own_matrix"]["strongly_connected"] is True


def test_blocker2_synchronizer_needs_two_stages():
    """review[0] blocker 3: there was no minimum stage count, so a single flop registering a pin, a
    black-box output, a latch or a foreign-domain flop verified as a synchronizer -- the input
    register whose metastability the second stage exists to absorb."""
    n = N()
    r = verdict(n, S("synchronizer", [[n.f("fy0")]], {"stages": 1}, {"input": n.n("ain")}))
    assert r["bucket"] == "template" and "depth 1 < 2" in r["reason"], r["reason"]
    r = verdict(n, S("synchronizer", [[n.f("fy0")], [n.f("fc0")]], {}, {"input": [n.n("ain"), n.n("din")]}))
    assert r["bucket"] == "template" and "< 2" in r["reason"], r["reason"]
    assert verdict(n, structures(n)["Y"])["verified"] and V.SYNC_MIN_STAGES == 2


def test_blocker2_counter_needs_two_bits():
    """review[0] minor: the coherence rule admits width 1 with modulus 2, whose template is w' = not
    q -- non-constant and word-dependent, so every gate passed and any toggle flop verified as
    "counter up by 1, mod 2^1, width 1"."""
    n = N()
    r = verdict(n, S("counter", [[n.f("fm0")]], {"direction": "up", "modulus": 2},
                     {"when": [], "hold": True}))
    assert r["bucket"] == "template" and "width 1 < 2" in r["reason"], r["reason"]
    assert V.COUNTER_MIN_WIDTH == 2 and verdict(n, structures(n)["M"])["verified"]


def test_blocker2_bdd_sat_is_inconclusive_and_never_refutes(monkeypatch):
    """review[0] major: bdd_check cuts at every control.inputs net that is an internal gate, which
    makes it a free variable; the relaxation is sound only for "unsat", so a "sat" may be a phantom
    that contradicts the cut gate's own definition, and it used to become a REFUTATION. It is now
    inconclusive and falls through to SAT on the real cones. Pinned by forcing every BDD call to say
    "sat": the correct structure must still verify, and a wrong claim must still be refuted by SAT."""
    n = N()
    xs = structures(n)
    monkeypatch.setattr(V._Ctx, "bdd_check", lambda self, *a: "sat")
    rep = V.verify_result(n.nl, {"structures": [xs["X"], xs["L"]]})
    assert all(r["verified"] for r in rep["structures"]), [r["reason"] for r in rep["structures"]]
    assert rep["summary"]["method_bdd inconclusive"] > 0 and rep["summary"].get("method_bdd", 0) == 0
    bad = copy.deepcopy(xs["X"])
    bad["proof"]["claims"][0]["equals"]["xor"].pop(5)
    r = verdict(n, bad)
    assert r["bucket"] == "refuted" and r["failed_check"]["method"] == "sat", r
    monkeypatch.undo()
    r = verdict(n, bad)                                  # unforced, the BDD proves the mismatch by SAT
    assert r["bucket"] == "refuted" and r["failed_check"]["method"] == "sat", r


def test_blocker2_params_are_certified_or_marked_unchecked():
    """review[0] major: "verified" did not certify the params the scorer scores. Now every declared
    param is reported as checked or unchecked, and the three the harness can check it does: an
    "updown" direction needs control.when_down, and the lfsr's polynomial and k_steps are
    reconstructed from the own matrix."""
    n = N()
    xs = structures(n)
    k = verdict(n, xs["K"])
    assert k["params_checked"] == ["direction"] and k["params_unchecked"] == []
    sh = copy.deepcopy(xs["Sh"])
    sh["params"].update(direction="left", serial_in=[n.n("din")], lanes_unordered=True)
    r = verdict(n, sh)
    assert r["verified"] and r["params_checked"] == ["depth", "lanes"]
    assert r["params_unchecked"] == ["direction", "lanes_unordered", "serial_in"], r["params_unchecked"]
    y = verdict(n, xs["Y"])
    assert y["params_checked"] == ["stages"] and y["params_unchecked"] == []


def test_blocker2_lfsr_polynomial_and_k_steps_are_reconstructed(monkeypatch):
    """The lfsr half of the same major: the review's P2_lfsr_wrong_params (the real CRC-16 declared
    with an invented polynomial, k_steps and n_inputs) verified untouched. L is a one-step Fibonacci
    LFSR whose polynomial the own matrix gives exactly (x^4 + x + 1 = 0x13), so a declared polynomial
    is compared with it; a matrix that is not one step is checked against the declared (poly,
    k_steps) pair by raising the companion to the power; anything else is marked unchecked."""
    n = N()
    xs = structures(n)
    good = copy.deepcopy(xs["L"])
    good["params"] = {"form": "fibonacci", "poly": 0x13, "k_steps": 1, "n_inputs": 1}
    r = verdict(n, good)
    assert r["verified"], r["reason"]
    lp = r["lfsr_params"]
    assert lp["one_step"] and lp["reading"] == "fibonacci" and lp["reconstructed_poly"] == 0x13
    assert lp["reconstructed_k_steps"] == 1 and lp["inputs_used"] == 1
    assert set(r["params_checked"]) == {"poly", "k_steps", "n_inputs"} and r["params_unchecked"] == ["form"]
    assert verdict(n, dict(good, params=dict(good["params"], poly=0x3)))["verified"]   # x^4 bit optional
    # and the REFLECTED polynomial, which is how tools/s3/corpus.py's truth writes it (measured: all
    # 62 corpus lfsr references) where tools/s3/lfsr.py writes bit i = the coefficient of x^i
    assert V._reciprocal(0x13, 4) == 0x19
    assert verdict(n, dict(good, params=dict(good["params"], poly=0x19)))["verified"]
    for bad, why in ((dict(poly=12345), "does not fit"),        # wider than a degree-4 polynomial
                     (dict(poly=0x1F), "poly"),                 # the right width, the wrong taps
                     (dict(poly=0x1F, k_steps=None), "poly"),   # compared with the one-step reading
                     (dict(k_steps=99), "k_steps"), (dict(n_inputs=7), "n_inputs")):
        r = verdict(n, dict(good, params=dict(good["params"], **bad)))
        assert r["bucket"] == "params" and why in r["reason"], (bad, r["reason"])
    # k_steps is checked against the DECLARED polynomial raised to it, not only against the one-step
    # reading, because C^k can itself have the companion shape for some k
    assert verdict(n, dict(good, params=dict(good["params"], poly=0x13, k_steps=5)))["bucket"] == "params"
    # off, the contradiction is reported instead of refusing (the measurement switch)
    monkeypatch.setattr(V, "LFSR_PARAM_CHECK", False)
    r = verdict(n, dict(good, params=dict(good["params"], poly=12345)))
    assert r["verified"] and "contradiction" in r["lfsr_params"]
    monkeypatch.undo()
    # X (xr0' = the XOR of all 12 bits, xr_k' = xr_(k-1)) is a one-step Fibonacci companion too, so
    # its polynomial is reconstructed; it declares none, so nothing is CHECKED and nothing claimed
    r = verdict(n, xs["X"])
    assert r["verified"] and r["lfsr_params"]["one_step"] and r["lfsr_params"]["checked"] == []
    assert r["lfsr_params"]["reconstructed_poly"] == (1 << 12) | ((1 << 12) - 1)
    # a word the harness has no stage coordinates for leaves the polynomial unchecked and says why
    two = copy.deepcopy(xs["L"])
    two["order"] = [two["flops"][:2], two["flops"][2:]]
    two["params"] = {"poly": 0x13, "k_steps": 1}
    r = verdict(n, two)
    assert r["verified"] and "stage coordinates" in r["lfsr_params"]["reason"]
    assert r["params_unchecked"] == ["k_steps", "poly"] and r["params_checked"] == []


def test_blocker2_control_keys_are_kind_bound():
    """review[0] minor: the nine keys were accepted for every kind, so control.input on a counter or
    control.when_down on a shift register was parsed or dropped in silence. Each kind now has its own
    set; the null / [] placeholders the recognizer writes uniformly are still allowed."""
    n = N()
    xs = structures(n)
    for sid, key, val in (("K", "input", 1), ("K", "inputs", [1]), ("Sh", "when_down", []),
                          ("Sh", "inverted", []), ("Y", "when_down", []), ("Y", "inputs", [1]),
                          ("L", "input", 1), ("L", "inverted", [1])):
        s = copy.deepcopy(xs[sid])
        s["control"][key] = val if val != [] else n.w(("en", 1))
        r = verdict(n, s)
        assert r["bucket"] == "malformed" and "do not belong" in r["reason"], (sid, key, r["reason"])
    # the placeholders a uniform control object carries are not a value
    s = copy.deepcopy(xs["K"])
    s["control"].update(input=None, inputs=[], when_down=None, hold=True)
    assert verdict(n, s)["verified"], verdict(n, s)["reason"]
    assert set(V.CONTROL_KEYS_BY_KIND) == set(V.schema.STRUCTURE_KINDS)


def test_v21_multi_case_reset_and_load_lists():
    """schema v2.1: control.reset is a LIST of cases, each with its own value, and control.load a
    LIST of CONDs, so a counter that clears AND reloads AND steps down can name every case and keep a
    hold region. R does exactly that (clear to 0 on srst, reload to 5 on ld, a down step on dec); the
    v2.0 single-case readings of the same counter are refuted on the hold template, which is the
    ceiling the lead's contract change lifts."""
    n = N()
    f, w = n.f, n.w
    flops = [f("fr0"), f("fr1"), f("fr2")]
    r = verdict(n, structures(n)["R"])
    assert r["verified"] and r["checks"] == {"defining": 3, "hold": 3, "reset[0]": 3, "reset[1]": 3}
    assert r["reset_cases"] == [{"literals": 1, "share": r["reset_cases"][0]["share"], "own_bits_read": 0,
                                 "ones": 0},
                                {"literals": 1, "share": r["reset_cases"][1]["share"], "own_bits_read": 0,
                                 "ones": 2}]
    when = w(("en", 1), ("srst", 0), ("ld", 0), ("dec", 0))       # the full defining cube
    for lost in ("dec", "ld"):
        control = {"when": when, "reset": w(("srst", 1)), "reset_value": {str(x): 0 for x in flops},
                   "load": w(("ld", 1)) if lost == "dec" else w(("dec", 1)), "hold": True}
        bad = S("counter", [flops], {"direction": "up", "modulus": 8}, control, sid="R20")
        rr = verdict(n, bad)
        assert rr["bucket"] == "refuted" and rr["failed_check"]["case"] == "hold", (lost, rr["reason"])
        assert rr["control_form"] == "legacy"
    # a reset case missing a flop's value, an unknown key in a case, and reset_value beside a case list
    good = structures(n)["R"]["control"]
    for mut in (lambda c: c["reset"][0]["value"].pop(str(flops[0])),
                lambda c: c["reset"][0].update(bogus=1),
                lambda c: c.update(reset_value={str(x): 0 for x in flops})):
        s = copy.deepcopy(structures(n)["R"])
        mut(s["control"])
        assert verdict(n, s)["bucket"] == "malformed", s["control"]
    assert good is not None


def test_v21_hold_is_outside_every_named_case():
    """The hold obligation is the complement of EVERY named case: naming one more case shrinks the
    hold region, and the shares of what each case takes out are reported."""
    n = N()
    xs = structures(n)
    r = verdict(n, xs["R"])
    assert r["nonvacuity"]["hold"] == "sat" and 0 < r["lane_share"]["hold"] < 0.2
    # K's hold region is en=0 & srst=0; a load case that takes the wr=1 half of it out shrinks it
    k = copy.deepcopy(xs["K"])
    k["control"]["load"] = [n.w(("en", 0), ("srst", 0), ("wr", 1))]
    r = verdict(n, k)
    assert r["verified"] and not r.get("hold_vacuous") and r["checks"]["hold"] == 3
    assert r["lane_share"]["hold"] < verdict(n, xs["K"])["lane_share"]["hold"]
    assert len(r["load_cases"]) == 1 and r["load_hidden_share"] > 0


def test_v21_load_cases_and_own_bit_reads_are_reported():
    """review[0] minor: the verdict record gave a consumer no way to separate a padded structure from
    an honest one, and control.load was the hiding mechanism. Each load case's share and own-bit
    reads are reported, with the share of the state space their union hides."""
    n = N()
    xs = structures(n)
    r = verdict(n, xs["V"])                      # V reloads at its own terminal count
    assert r["load_cases"] == [{"literals": 1, "share": r["load_cases"][0]["share"], "own_bits_read": 3}]
    assert r["load_hidden_share"] == r["load_cases"][0]["share"] and r["load_hidden_share"] < 0.2
    r = verdict(n, xs["R"])
    assert r["load_cases"][0]["own_bits_read"] == 0 and r["cases"]["load"] == 1
    r = verdict(n, xs["K"])
    assert r["load_cases"] == [] and "load_hidden_share" not in r


# ----------------------------------------------------------------------------------------------
# the freeze round (2026-09-23): the lead's decisions on review[0]'s two blockers and one major


def test_v5_hold_may_not_be_emptied_by_an_opaque_load(monkeypatch):
    """review[0] BLOCKER 0, closed by the lead's rule of 2026-09-23: the mandatory hold obligation was
    erasable by a CONTENT-FREE transform. A COND is a conjunction, so ~when is a disjunction of |when|
    single-literal CONDs -- exactly what schema v2.1's control.load LIST can name. Under
    load = [[~l] for l in control.when] the hold region is empty, nothing at all is checked outside
    the defining case, and the structure verified. Now an empty hold region is accepted ONLY when the
    VERIFIED cases (defining, when_down, reset) empty it by themselves."""
    n = N()
    xs = structures(n)

    def T(s):
        """The reviewer's transform: replace control.load with the complement of control.when."""
        s = copy.deepcopy(s)
        s["control"]["load"] = [[{"net": l["net"], "value": 1 - l["value"]}] for l in s["control"]["when"]]
        return s

    # (a) one-literal `when` (the shape that already worked under v2.0's single load COND)
    r = verdict(n, T(xs["K"]))
    assert r["bucket"] == "vacuous" and r["hold_vacuous"] and r["hold_vacuous_cover"] == "load"
    assert "erases the hold obligation" in r["reason"], r["reason"]
    assert r["nonvacuity"]["when"] == "sat" and r["nonvacuity"]["hold"] == "unsat"
    # (b) a SET of load cases whose UNION covers the complement: what schema v2.1's list added, and
    #     the shape v2.0's single load COND could not write. Neither case alone empties the region.
    k2 = copy.deepcopy(xs["K"])
    k2["control"]["load"] = [n.w(("en", 0), ("srst", 0)), n.w(("en", 0), ("srst", 1))]
    r = verdict(n, k2)
    assert r["bucket"] == "vacuous" and r["hold_vacuous_cover"] == "load" and len(r["load_cases"]) == 2
    one = copy.deepcopy(xs["K"])                           # one case covering what the reset leaves
    one["control"]["load"] = [n.w(("en", 0), ("srst", 0))]
    assert verdict(n, one)["hold_vacuous_cover"] == "load"
    # (c) a single load case [] ("always"): it hides the whole space, so the DEFINING case goes first
    k0 = copy.deepcopy(xs["K"])
    k0["control"]["load"] = [[]]
    r = verdict(n, k0)
    assert r["bucket"] == "vacuous" and "when" in r["reason"], r["reason"]
    # (d) the shift register, whose hold is required for the same reason
    r = verdict(n, T(xs["Sh"]))
    assert r["bucket"] == "vacuous" and r["hold_vacuous_cover"] == "load", r["reason"]
    # (e) what the rule does NOT refuse, and must not: a hold region the VERIFIED cases empty by
    #     themselves -- a free-running counter, with and without an unrelated load case beside it.
    #     This is the case the blunt HOLD_MUST_BE_NONVACUOUS switch could not separate.
    r = verdict(n, xs["M"])
    assert r["verified"] and r["hold_vacuous"] and r["hold_vacuous_cover"] == "verified"
    m2 = copy.deepcopy(xs["M"])
    m2["control"]["load"] = [n.w(("wr", 1))]
    r = verdict(n, m2)
    assert r["verified"] and r["hold_vacuous"] and r["hold_vacuous_cover"] == "verified"
    assert r["checks"]["hold"].startswith("vacuous") and len(r["load_cases"]) == 1
    # (f) the summary names the refusals, so a reader does not have to walk the structures
    rep = V.verify_result(n.nl, {"structures": [T(xs["K"]), xs["M"], xs["K"]]})
    assert rep["summary"]["hold_emptied_by_load"] == 1 and rep["summary"]["verified_vacuous_hold"] == 1
    assert rep["limits"]["hold_empty_needs_verified_cover"] is True
    # (g) the rule is one constant, and with it off the transform verifies again (the measurement)
    monkeypatch.setattr(V, "HOLD_EMPTY_NEEDS_VERIFIED_COVER", False)
    r = verdict(n, T(xs["K"]))
    assert r["verified"] and r["hold_vacuous"] and r["checks"]["hold"].startswith("vacuous")
    assert r["hold_vacuous_cover"] == V.HOLD_COVER_UNDECIDED


def test_v5_hold_message_states_only_what_was_decided():
    """review[0] minor 6(1): the vacuous-hold message asserted a cause it had not established -- the
    region whose unsatisfiability it reports also conjoins the async-controls-inactive literals and
    the counter's in-range literal, so the named cases are a hint, not the decision."""
    n = N()
    r = verdict(n, structures(n)["M"])
    assert r["checks"]["hold"] == "vacuous (the hold region is empty; named case(s): defining)"
    assert "cover every state in range" not in r["checks"]["hold"]
    assert r["hold_named_cases"] == ["defining"]


def test_v5_hold_cover_is_read_off_the_checked_cubes_not_the_case_conds(monkeypatch):
    """review[0] BLOCKER 1 of the freeze round, closed 2026-09-23. The cover test built its region
    from `self.n_r`, the complement of the reset CONDs AT FULL SIZE -- but a reset case is only ever
    CHECKED on its own priority cube, and that cube conjoins ~(each load case). So the reset CONDs
    could empty ~when on paper while the load-active part of every reset case was checked by nothing,
    and the harness still reported hold_vacuous_cover "verified". The reviewer's transform T2 (general,
    cheap, reads no own bits): turn each literal of `when` into its own LYING reset case and hide the
    lie behind a load case that forces the structure's real reset. Each lying case is then checked
    only inside the real reset, where it is true.

    Here K counts under en & ~srst and clears under srst. T2 asserts "when en = 0 the counter clears
    to 0" -- plainly false of this circuit, where it HOLDS -- and checks that case only on
    en = 0 & srst = 1, inside the real reset, where it is true."""
    n = N()
    k = copy.deepcopy(structures(n)["K"])
    zero = {str(n.f(c)): 0 for c in ("fk0", "fk1", "fk2")}
    k["control"] = {"when": n.w(("en", 1), ("srst", 0)),
                    "reset": [{"when": n.w(("en", 0)), "value": dict(zero)},       # THE LIE
                              {"when": n.w(("srst", 1)), "value": dict(zero)}],    # the real reset
                    "load": [n.w(("en", 0), ("srst", 0))],                         # where it hides
                    "hold": True}
    r = verdict(n, k)
    assert r["bucket"] == "vacuous" and r["hold_vacuous"] and r["hold_vacuous_cover"] == "load", r["reason"]
    # it is the SECOND test that catches it: the region without the load conjunct IS unsatisfiable
    # (that is the point of T2), so the message must be the checked-cube one, not the v5 one
    assert "OUTSIDE the defining case" in r["reason"], r["reason"]
    assert "erases the hold obligation" not in r["reason"], r["reason"]
    # the same lie WITHOUT the load case to hide in is refuted on the lying case's own template: the
    # flops do not clear at en = 0, which is exactly what the load was erasing
    bare = copy.deepcopy(k)
    bare["control"].pop("load")
    rb = verdict(n, bare)
    assert not rb["verified"] and rb["bucket"] == "refuted" and "reset[0]" in rb["reason"], rb["reason"]
    # and the rule is what refuses it: with the constant off, T2 verifies again with a vacuous hold,
    # ZERO hold obligations checked and a cover the harness states it did not decide
    monkeypatch.setattr(V, "HOLD_EMPTY_NEEDS_VERIFIED_COVER", False)
    r = verdict(n, k)
    assert r["verified"] and r["hold_vacuous"] and r["hold_vacuous_cover"] == V.HOLD_COVER_UNDECIDED
    assert r["checks"]["hold"].startswith("vacuous") and not isinstance(r["checks"]["hold"], int)


def test_v5_hold_cover_test_is_vacuous_without_load_cases():
    """The second test must cost a load-free structure nothing: with no load cases n_l = 1, so
    "a load case is satisfiable outside the defining cases" is unsatisfiable by construction. The
    free-running counter (when = [], hold region empty by definition) keeps cover "verified", with
    and without an unrelated load case beside it."""
    n = N()
    xs = structures(n)
    r = verdict(n, xs["M"])
    assert r["verified"] and r["hold_vacuous"] and r["hold_vacuous_cover"] == "verified"
    assert not r.get("load_cases")
    m2 = copy.deepcopy(xs["M"])
    m2["control"]["load"] = [n.w(("wr", 1))]
    r = verdict(n, m2)
    assert r["verified"] and r["hold_vacuous"] and r["hold_vacuous_cover"] == "verified"
    # and the honest multi-case counter, whose hold region is NOT empty, is untouched by either test
    r = verdict(n, xs["R"])
    assert r["verified"] and not r.get("hold_vacuous") and r["checks"]["hold"] == 3
    assert "hold_vacuous_cover" not in r


def test_v5_partial_complement_is_a_stated_limit_not_a_refusal():
    """RECORDED AS A LIMIT, not a fix. The lead's rule bounds the SHAPE of an empty hold region, not
    the SIZE of a non-empty one: a load list that covers all but one literal's worth of ~when leaves a
    sliver, and the hold obligation is then really checked -- on that sliver. The share of what is
    left is what a consumer must read (lane_share["hold"], load_hidden_share), and this test pins that
    the harness reports it rather than hiding it."""
    n = N()
    k = copy.deepcopy(structures(n)["K"])                  # hold region: en=0 & srst=0
    k["control"]["load"] = [n.w(("en", 0), ("wr", 1)), n.w(("en", 0), ("wr", 0), ("din", 1))]
    r = verdict(n, k)
    assert r["verified"] and not r.get("hold_vacuous") and r["checks"]["hold"] == 3
    assert 0 < r["lane_share"]["hold"] < 0.2 and r["load_hidden_share"] > 0.3
    rep = V.verify_result(n.nl, {"structures": [k]})
    assert rep["summary"]["verified_load_hidden_share_max"] == r["load_hidden_share"]


def test_v5_lfsr_bit_order_is_certified_only_when_the_stage_order_was_pinned():
    """review[0] BLOCKER 1: PARAMS_CHECKED["lfsr_crc"] listed bit_order unconditionally, but the only
    thing that constrains an lfsr's stage order is the polynomial reconstruction, which does not run
    for a matrix that is not a one-step companion carrying no declared (poly, k_steps) pair -- _lfsr's
    own obligations are per-flop EXPRs and never read the order. So a real CRC declared with a
    SCRAMBLED bit_order verified with bit_order reported as certified."""
    n = N()
    xs = structures(n)
    true_order = list(xs["L"]["flops"])                    # fl0 (the tap end) .. fl3
    scrambled = [true_order[1], true_order[0], true_order[3], true_order[2]]

    def with_order(order, **params):
        s = copy.deepcopy(xs["L"])
        s.pop("order")                                     # the order comes from params.bit_order now
        s["params"] = dict(params, bit_order=order)
        return s

    r = verdict(n, with_order(true_order))
    assert r["verified"] and r["lfsr_params"]["one_step"] and r["lfsr_params"]["bit_order_pinned"] == "stage"
    assert r["params_checked"] == ["bit_order"] and r["params_unchecked"] == []
    r = verdict(n, with_order(scrambled))
    assert r["verified"], r["reason"]                      # the EXPRs still hold: it IS the same CRC
    assert r["lfsr_params"]["bit_order_pinned"] is False and not r["lfsr_params"].get("one_step")
    assert r["params_checked"] == [] and r["params_unchecked"] == ["bit_order"]
    assert "not pinned" in r["params_notes"]["bit_order"]
    # a declared (poly, k_steps) pair that MATCHES pins the order just as the one-step reading does
    r = verdict(n, with_order(true_order, poly=0x13, k_steps=1))
    assert r["verified"] and set(r["params_checked"]) == {"bit_order", "k_steps", "poly"}
    # and the same pair on the scrambled order is a contradiction, so nothing is certified
    r = verdict(n, with_order(scrambled, poly=0x13, k_steps=1))
    assert r["bucket"] == "params", r["reason"]
    # no stage coordinates at all (two lanes): bit_order cannot be pinned either
    two = copy.deepcopy(xs["L"])
    two["order"] = [two["flops"][:2], two["flops"][2:]]
    two["params"] = {"bit_order": [two["flops"][:2], two["flops"][2:]]}
    r = verdict(n, two)
    assert r["verified"] and r["params_unchecked"] == ["bit_order"] and r["params_checked"] == []
    assert "bit_order" not in V.PARAMS_CHECKED["lfsr_crc"]


def test_v5_counter_modulus_is_unchecked_when_saturating_carries_the_limit():
    """review[0] major 3: with params.saturating an INTEGER the saturation limit comes from it, the
    `if not sat` branch that reads params.modulus is skipped and the template uses only the limit --
    yet modulus sat in PARAMS_CHECKED unconditionally, so a 2-bit counter could declare a modulus of
    3 beside a limit of 3 (i.e. modulus 4) and have it certified while unread."""
    n = N()
    u = copy.deepcopy(structures(n)["U"])                  # 2-bit up counter saturating at 3
    r = verdict(n, dict(u, params={"direction": "up", "saturating": 3, "modulus": 4}))
    assert r["verified"] and "modulus" in r["params_checked"], r["reason"]   # 4 - 1 == the limit 3
    r = verdict(n, dict(u, params={"direction": "up", "saturating": 3, "modulus": 3}))
    assert r["verified"] and r["params_unchecked"] == ["modulus"], (r["reason"], r.get("params_unchecked"))
    assert "never used" in r["params_notes"]["modulus"] and "modulus" not in r["params_checked"]
    # the bool form really does read the modulus (it is what sets the limit), so it stays certified
    r = verdict(n, dict(u, params={"direction": "up", "saturating": True, "modulus": 4}))
    assert r["verified"] and "modulus" in r["params_checked"] and r["template"].endswith("width 2")
    # and a plain modulo counter's modulus is read by the template as before
    assert "modulus" in verdict(n, structures(n)["P"])["params_checked"]
    assert "modulus" not in V.PARAMS_CHECKED["counter"]


def test_v21_legacy_control_form_is_a_shim_and_is_counted(monkeypatch):
    """The v2.0 single-case forms are accepted while the recognizer is moved over (every structure of
    the recorded TEMPO result uses them), normalised to one-element lists, reported per structure and
    counted in the summary. LEGACY_CONTROL_FORM switches them off in one line."""
    n = N()
    xs = structures(n)
    legacy = xs["K"]
    modern = copy.deepcopy(legacy)
    modern["control"] = {"when": n.w(("en", 1)), "hold": True,
                         "reset": [{"when": n.w(("srst", 1)), "value": {str(x): 0 for x in legacy["flops"]}}]}
    a, b = verdict(n, legacy), verdict(n, modern)
    assert a["verified"] and b["verified"] and a["checks"] == b["checks"]
    assert a["control_form"] == "legacy" and b["control_form"] == "v2.1"
    monkeypatch.setattr(V, "LEGACY_CONTROL_FORM", False)
    r = verdict(n, legacy)
    assert r["bucket"] == "malformed" and "reset_value" in r["reason"], r["reason"]
    assert verdict(n, modern)["verified"]
    r = verdict(n, xs["V"])                                      # its load is a bare COND
    assert r["bucket"] == "malformed" and "v2.1" in r["reason"], r["reason"]
    monkeypatch.undo()
    assert V.verify_result(n.nl, {"structures": [legacy, modern]})["summary"]["legacy_control_form"] == 1


def test_known_gap_clock_root_of_a_wholly_gated_design(tmp_path):
    """review[1] blocker 1(b), NOT fixed here (it is a completeness gap, and naming the clock root
    of a design no flop clocks directly needs a rule this module cannot decide soundly): when the
    clock cone has two primary inputs and no flop is clocked by either directly, _clock_logic
    refuses. The test records the behaviour so the fix flips it."""
    lib = _lib()
    if lib is None:
        pytest.skip("sky130 Liberty absent")
    src = ("module top(clk, en, din, o);\n  input clk, en, din;\n  output o;\n" +
           "\n".join([_c("and2_1", "g", A="clk", B="en", X="gclk"),
                      _dff("f0", "din", "a0", clk="gclk"), _dff("f1", "a0", "a1", clk="gclk"),
                      _dff("f2", "a1", "a2", clk="gclk"), _c("buf_1", "ob", A="a2", X="o")]) + "\nendmodule\n")
    p = tmp_path / "gated.v"
    p.write_text(src)
    nl, key = load_verilog(str(p), lib, seed=0)
    cell = {nm: i for i, nm in enumerate(key.cell_name)}
    s = S("shift_register", [[cell["f0"], cell["f1"], cell["f2"]]], {}, {"when": [], "hold": True})
    r = V.verify_result(nl, {"structures": [s]})["structures"][0]
    assert not r["verified"] and r["bucket"] == "unsupported clock", r["reason"]
    assert "one clock root" in r["reason"]


# ----------------------------------------------------------------------------------------------
# malformed input, budgets, replay


@pytest.mark.parametrize("bad", ["05", " 5", "+5", "٥", "²", "5 ", True, -1, 1.0, 10 ** 19, None, [1]])
def test_non_canonical_ids_are_malformed(bad):
    n = N()
    s = copy.deepcopy(structures(n)["K"])
    s["flops"][0] = bad
    s["order"][0][0] = bad
    r = verdict(n, s)
    assert not r["verified"] and r["bucket"] == "malformed", r["reason"]


def test_canonical_string_ids_are_accepted():
    n = N()
    s = copy.deepcopy(structures(n)["K"])
    s["flops"] = [str(x) for x in s["flops"]]
    s["order"] = [[str(x) for x in lane] for lane in s["order"]]
    s["control"]["when"] = [{"net": str(c["net"]), "value": c["value"]} for c in s["control"]["when"]]
    assert verdict(n, s)["verified"]


def test_malformed_shapes_never_crash():
    n = N()
    deep = {"const": 1}
    for _ in range(5000):                      # deeper than the recursion limit: rejected before any recursion
        deep = {"not": deep}
    lf = copy.deepcopy(structures(n)["L"])
    lf["proof"]["claims"][0]["equals"] = deep
    wide = copy.deepcopy(structures(n)["L"])
    wide["proof"]["claims"][0]["equals"] = {"xor": [{"q": n.f("fl3")}] * 300_000}
    k = structures(n)["K"]
    bads = ["x", 7, None, [k], dict(k, kind="nonsense"), dict(k, flops=[k["flops"][0]] * 2),
            dict(k, order=[[k["flops"][0]]]), dict(k, control="x"), dict(k, control={"when": "x"}),
            dict(k, control={"when": [{"net": n.n("en")}], "hold": True}),
            dict(k, control={"when": [], "reset": 5, "hold": True}),
            dict(k, control={"when": [], "reset": [{"when": [], "value": {}}], "hold": True}),
            dict(k, control={"when": [], "reset": [{"when": [], "value": {str(n.f("fk0")): 0}}], "hold": True}),
            dict(k, control={"when": [], "reset_value": {str(n.f("fk0")): 0}, "hold": True}),
            dict(k, control={"when": [], "load": [[{"net": n.n("en")}]], "hold": True}),
            dict(k, control={"when": [], "load": 5, "hold": True}),
            dict(k, control={"when": [], "hold": "yes"}), dict(k, params=[]), dict(k, flops=[n.f("fk0"), 10 ** 6]),
            dict(k, flops=[n.cell["xk0"]]), lf, wide, {"kind": "counter", "flops": {"a": 1}},
            dict(k, control={"when": [{"net": 10 ** 9, "value": 1}], "hold": True}),
            dict(k, control={"when": [{"net": 1, "value": True}], "hold": True}),
            dict(k, control={"when": [], "hold": True, "bogus_field": 1}),           # an unknown control key
            dict(k, order=k["flops"])]                                            # a flat "order"
    rep = V.verify_result(n.nl, {"structures": bads})
    for s, r in zip(bads, rep["structures"]):
        assert not r["verified"] and r["bucket"] in ("malformed", "unscored kind"), (str(s)[:80], r["reason"])
    assert rep["summary"].get("exceptions", 0) == 0
    assert V.verify_result(n.nl, {"structures": "x"})["structures"] == []
    assert V.verify_result(n.nl, ["x"])["structures"] == []


def test_exceptions_are_caught_per_structure(monkeypatch):
    n = N()
    xs = structures(n)

    def boom(self, *a, **k):
        raise RuntimeError("injected")
    monkeypatch.setattr(V._Ctx, "_sync", boom)
    rep = V.verify_result(n.nl, {"structures": [xs["Y"], xs["K"]]})
    y, k = rep["structures"]
    assert not y["verified"] and y["bucket"] == "malformed" and y.get("exception") and "injected" in y["reason"]
    assert k["verified"] and rep["summary"]["exceptions"] == 1


def test_conflict_budget_is_deterministic():
    n = N()
    xs = list(structures(n).values())
    rep = V.verify_result(n.nl, {"structures": xs}, conflicts_total=0)
    assert all(r["bucket"] == "budget" for r in rep["structures"])
    full = V.verify_result(n.nl, {"structures": xs})["summary"]["conflicts_used"]
    assert full > 0
    runs = [V.verify_result(n.nl, {"structures": xs}, conflicts_total=full // 2) for _ in range(2)]
    a, b = ([(r["verified"], r["reason"]) for r in x["structures"]] for x in runs)
    assert a == b and runs[0]["summary"]["conflicts_used"] == runs[1]["summary"]["conflicts_used"]
    assert any(r["bucket"] == "budget" for r in runs[0]["structures"])
    assert not any(r["bucket"] in ("refuted", "unknown") for r in runs[0]["structures"])


def test_report_hashes_and_replay():
    n = N()
    res = {"structures": list(structures(n).values())}
    rep = V.verify_result(n.nl, res)
    assert all(len(r["sha256"]) == 64 and len(r["claims_sha256"]) == 64 for r in rep["structures"])
    assert V.replay(n.nl, res, rep) == []
    changed = copy.deepcopy(res)
    changed["structures"][0]["params"]["direction"] = "down"
    d = V.replay(n.nl, changed, rep)
    assert {x[1] for x in d if x[0] == 0} >= {"sha256", "verified"}


# ----------------------------------------------------------------------------------------------
# permutation invariance


def test_verdicts_and_cnf_are_permutation_invariant(monkeypatch):
    """The same structures on four id permutations of the netlist (load_verilog seeds): identical
    verdicts and reasons (up to the flop id in a reason), identical per-check methods, and identical
    canonical CNF (the DIMACS of every SAT call, in order)."""
    seen = []
    orig = V._Ctx.cnf

    def rec(self, lits):
        out = orig(self, lits)
        seen[-1].append(repr(out))
        return out
    monkeypatch.setattr(V._Ctx, "cnf", rec)
    outs = []
    for seed in (None, 1, 2, 3):
        n = N(seed)
        xs = structures(n)
        bad = copy.deepcopy(xs["K"])
        bad["params"]["direction"] = "down"
        seen.append([])
        rep = V.verify_result(n.nl, {"structures": list(xs.values()) + [bad]})
        outs.append(([(r["verified"], r["reason"].split(" flop ")[0], r.get("inverted_edges"), r["conflicts"],
                       r.get("lane_share"))
                      for r in rep["structures"]],
                     {k: v for k, v in rep["summary"].items() if k.startswith("method_") or k == "conflicts_used"}))
    assert all(o == outs[0] for o in outs), outs
    assert len(seen[0]) > 0 and all(s == seen[0] for s in seen)


# ----------------------------------------------------------------------------------------------
# optional regression: the generalisation review's word-wide CRCs (reference claims, all flows)

GEN = os.path.join(ROOT, "out", "s3", "review_generalisation", "designs")


@pytest.mark.skipif(not os.path.exists(os.path.join(GEN, "fast", "crc32c_d32_sr", "claims.json")),
                    reason="generalisation regression set absent")
@pytest.mark.parametrize("flow", ["ref", "fast", "delay"])
def test_wide_crc_reference_claims_verify(flow):
    sys.path.insert(0, os.path.join(ROOT, "out", "s3", "verify"))
    import refv2
    from tools.s3 import corpus
    for name in ("crc16_d16_ar", "crc32c_d32_sr"):
        for lib in ("sky130", "ihp"):
            od = os.path.join(GEN, flow)
            nl, key, truth = corpus.load(name, lib, outdir=od, seed=3)
            ref = refv2.v2_reference(truth, corpus.claims(name, od), lib, nl, key)
            rep = V.verify_result(nl, ref)
            assert [r["verified"] for r in rep["structures"]] == [True], [r["reason"] for r in rep["structures"]]


def test_params_mirror_matches_the_harness():
    """tools/s3/params.py's HARNESS_* group is the recognizers' MIRROR of this module's published
    limits; the harness keeps the live value and never reads that file (a run may override it, and it
    is copied into the recognizer's sandbox). Integration of 2026-09-22: the four limits the second
    round added are mirrored too, and are fixed for every run. Freeze round (2026-09-23,
    review[1] minor / changes.jsonl PV10): ALL FIFTEEN mirrors are asserted here, including the six
    this round's contract changes added -- the lead's own hold decision among them, which was
    asserted nowhere, so a drift between params.py and verify.py on it would not have been caught."""
    from tools.s3 import params as P
    assert P.HARNESS_CONFLICTS == V.CONFLICTS_PER_CHECK
    assert P.HARNESS_EXPR_NODES == V.EXPR_NODES
    assert P.HARNESS_EXPR_DEPTH == V.EXPR_DEPTH
    assert P.HARNESS_COND_LITERALS == V.COND_LITERALS
    assert P.HARNESS_SHIFT_MIN_DEPTH == V.SHIFT_MIN_DEPTH
    assert P.HARNESS_CLOCK_SUPPORT == V.CLOCK_SUPPORT
    assert P.HARNESS_COVERAGE_MAX_OWN_BITS == V.COVERAGE_MAX_OWN_BITS
    assert P.HARNESS_COVERAGE_CALLS_PER_RUN == V.COVERAGE_CALLS_PER_RUN
    assert P.HARNESS_HOLD_MUST_BE_NONVACUOUS == V.HOLD_MUST_BE_NONVACUOUS
    # the six the freeze round added (two shape minima, the two multi-case list bounds, the legacy
    # control-form shim and HOLD_EMPTY_NEEDS_VERIFIED_COVER)
    assert P.HARNESS_COUNTER_MIN_WIDTH == V.COUNTER_MIN_WIDTH
    assert P.HARNESS_SYNC_MIN_STAGES == V.SYNC_MIN_STAGES
    assert P.HARNESS_RESET_CASES_MAX == V.RESET_CASES_MAX
    assert P.HARNESS_LOAD_CASES_MAX == V.LOAD_CASES_MAX
    assert P.HARNESS_LEGACY_CONTROL_FORM == V.LEGACY_CONTROL_FORM
    assert P.HARNESS_HOLD_EMPTY_NEEDS_VERIFIED_COVER == V.HOLD_EMPTY_NEEDS_VERIFIED_COVER
    for n in ("HARNESS_CLOCK_SUPPORT", "HARNESS_COVERAGE_MAX_OWN_BITS", "HARNESS_COVERAGE_CALLS_PER_RUN",
              "HARNESS_HOLD_MUST_BE_NONVACUOUS", "HARNESS_COUNTER_MIN_WIDTH", "HARNESS_SYNC_MIN_STAGES",
              "HARNESS_RESET_CASES_MAX", "HARNESS_LOAD_CASES_MAX", "HARNESS_LEGACY_CONTROL_FORM",
              "HARNESS_HOLD_EMPTY_NEEDS_VERIFIED_COVER"):
        assert n in P.NOT_PER_RUN
        with pytest.raises(KeyError):
            P.resolve({n: (not getattr(P, n)) if isinstance(getattr(P, n), bool) else getattr(P, n) + 1})
    # every HARNESS_* name in params.py is now asserted above -- the coverage hole itself is a test
    mirrored = {n for n in dir(P) if n.startswith("HARNESS_")}
    asserted = {"HARNESS_CONFLICTS", "HARNESS_EXPR_NODES", "HARNESS_EXPR_DEPTH", "HARNESS_COND_LITERALS",
                "HARNESS_SHIFT_MIN_DEPTH", "HARNESS_CLOCK_SUPPORT", "HARNESS_COVERAGE_MAX_OWN_BITS",
                "HARNESS_COVERAGE_CALLS_PER_RUN", "HARNESS_HOLD_MUST_BE_NONVACUOUS",
                "HARNESS_COUNTER_MIN_WIDTH", "HARNESS_SYNC_MIN_STAGES", "HARNESS_RESET_CASES_MAX",
                "HARNESS_LOAD_CASES_MAX", "HARNESS_LEGACY_CONTROL_FORM",
                "HARNESS_HOLD_EMPTY_NEEDS_VERIFIED_COVER"}
    assert mirrored == asserted, mirrored ^ asserted


def test_every_recognizer_threshold_is_a_params_entry():
    """The integration's own invariant: the four recognizer modules carry no threshold registry of
    their own any more, and every name their DEFAULTS / LOCAL / THRESHOLDS views expose resolves
    through tools/s3/params.py, so recognize.split_params validates and routes an override of it."""
    from tools.s3 import controls, counter, lfsr, params, shift
    assert not hasattr(controls, "NEW_THRESHOLDS") and not hasattr(shift, "NEW_THRESHOLDS")
    assert not hasattr(counter, "_NEW") and not hasattr(lfsr, "NEW_LOCAL")
    known = params.resolve()
    for mod, view in ((counter, counter.DEFAULTS), (lfsr, lfsr.LOCAL), (shift, shift.THRESHOLDS)):
        for name, value in view.items():
            assert name in known, (mod.__name__, name)
            assert known[name] == value, (mod.__name__, name)
    for name in ("CLOCK_GATE_FOLD", "CLOCK_GATE_FALLBACK", "MODE_SELECT", "MODE_SELECT_SHARE",
                 "MODE_SELECT_MIN_FLOPS", "MODE_SELECT_MARGIN", "MODE_SELECT_MAX_CANDS",
                 "MODE_SELECT_SCREEN", "MODE_SELECT_MIN_LIVE", "SHIFT_DECIDE_TIES", "MODE_STEPS_MAX",
                 "MODE_STEP_SOURCES", "QUIET_LANES", "SELF_COVERAGE", "COVER_VECTORS", "COVER_SAT",
                 "NET_COND", "ENABLE_TRIES", "RESET_TRIES", "LOAD_CUBE_ROUNDS", "HOLD_REQUIRED",
                 "LFSR_WIDE_CAP", "LFSR_PIN_POLY", "LFSR_OWN_GATE"):
        assert name in known, name
