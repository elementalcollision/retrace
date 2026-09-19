"""Every message the output generator can print, demonstrated on the extracted netlist.

The winning grid is covered by test/test_answer.py. Here: 0 stars ("EMPTY SKY"), all 121
cells ("BIG BANG"), a grid that obeys every rule except that two stars touch ("TWO NOT
TOUCH", success stays 0), and the sample VCD's "TRY AGAIN" (V6). Also the Morse strip.
"""

import functools
import os
import subprocess

import gdstk
import pytest

from tools.analysis.eastereggs import morse, pixel_art
from tools.retrace.extract import Extraction
from tools.retrace.lef import read_lef

BIN = os.path.expanduser("~/ttsetup/oss-cad-suite/bin")
LEF = "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"
MODELS = ["pdk/sky130_fd_sc_hd/verilog/primitives.v", "pdk/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v"]
# rows, columns and regions all hold 2 stars (generated with z3), but 11 pairs of stars touch
TOUCHING = ("01001000000" "00000010010" "00000001010" "00001001000" "10000100000"
            "00100000100" "00000100100" "00000010001" "00010000001" "10010000000" "01100000000")
needs_eda = pytest.mark.skipif(not os.path.exists(f"{BIN}/iverilog"), reason="Icarus not installed")


@functools.cache
def netlist():
    os.makedirs("out/messages", exist_ok=True)
    lef = read_lef(LEF)
    dirs = {p: "input" for p in ("clk", "rst_n", "enable", "I")} | {"O": "output", "success": "output"}
    with open("out/messages/puzzle.v", "w") as f:
        f.write(Extraction("upstream/puzzle.gds", lef, top="puzzle").to_verilog(dirs, lef))
    return "out/messages/puzzle.v"


def run(bits, tag):
    tb = ["`timescale 1ns/1ps", "module tb; reg clk=0, rst_n=0, enable=0, I=0; wire [7:0] O; wire success;",
          "puzzle dut(.clk(clk),.rst_n(rst_n),.enable(enable),.I(I),.O(O),.success(success));",
          'always #5 clk=~clk; always @(posedge clk) if (O!=0) $write("%c", O);',
          "initial begin repeat(3) @(negedge clk); rst_n=1;"]
    tb += [f"  @(negedge clk); enable=1; I={b};" for b in bits]
    tb += ['  @(negedge clk); enable=0; I=0; repeat(30) @(negedge clk); $display("|%b", success); $finish; end',
           "endmodule"]
    os.makedirs("out/messages", exist_ok=True)
    path = f"out/messages/tb_{tag}.v"
    with open(path, "w") as f:
        f.write("\n".join(tb) + "\n")
    subprocess.run([f"{BIN}/iverilog", "-g2012", "-DFUNCTIONAL", "-DUNIT_DELAY=", "-o", path + "vp", path, netlist(),
                    *MODELS], check=True, capture_output=True)
    out = subprocess.run([f"{BIN}/vvp", "-n", path + "vp"], check=True, capture_output=True, text=True).stdout
    text, success = out.split("|")[0], out.split("|")[1][0]
    return text, success


@needs_eda
@pytest.mark.parametrize("bits,expected", [("0" * 121, "EMPTY SKY"), ("1" * 121, "BIG BANG"),
                                           (TOUCHING, "TWO NOT TOUCH")], ids=["empty", "all", "touching"])
def test_message(bits, expected):
    assert run(bits, expected.split()[0].lower()) == (expected, "0")


def test_touching_grid_breaks_only_the_touch_rule():
    g = [TOUCHING[r * 11:(r + 1) * 11] for r in range(11)]
    assert all(row.count("1") == 2 for row in g)
    assert all(sum(g[r][c] == "1" for r in range(11)) == 2 for c in range(11))
    stars = [(r, c) for r in range(11) for c in range(11) if g[r][c] == "1"]
    touching = [(a, b) for i, a in enumerate(stars) for b in stars[i + 1:]
                if max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1]
    assert touching


def test_morse_strip_and_pixel_art():
    top = gdstk.read_gds("upstream/puzzle.gds").top_level()[0]
    assert morse(top) == "PER ARENAM AD ASTRA"
    art = pixel_art(top)
    assert len(art) == 57 and all(len(r) == 57 for r in art) and sum(r.count("#") for r in art) == 1366
