"""Final answer cross-check (Sprint 4, solve/answer).

Drives the chip from reset exactly as a solver would -- rst_n low, then enable=1 with
I set to the 121-bit sequence found independently by both solve routes (Route A:
analytical/z3 over the recovered RTL, docs/SOLVE_ANALYTICAL.md; Route B: SymbiYosys
BMC/cover over the extracted netlist, docs/SOLVE_FORMAL.md), then enable=0 while the
message prints -- and checks that `success` rises and stays high and that the decoded
message matches on both the extracted netlist (Icarus + PDK models) and the recovered
RTL (Icarus). Verilator (extracted netlist flattened through Liberty functions) is
included too when installed, as a third simulator.

Kept under ~60 s: one GDS extraction (~1 s) plus three small Icarus/Verilator runs.
"""

import functools
import os
import subprocess

import pytest

from tools.retrace.extract import Extraction
from tools.retrace.lef import read_lef

BIN = os.path.expanduser("~/ttsetup/oss-cad-suite/bin")
LEF = "pdk/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"
LIB = "pdk/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
MODELS = ["pdk/sky130_fd_sc_hd/verilog/primitives.v", "pdk/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v"]
BLOCKS = ["counter", "array", "left_top", "left_bottom", "check", "outgen"]

# The 121-bit I sequence both solve routes converged on independently (see
# docs/SOLUTION.md). bits[k] is the value of I on the (k+1)-th enabled cycle,
# k = 0..120, row-major over the 11x11 grid (row = k div 11, col = k mod 11).
BITS = "0000000101010000100000000000010101010000000000001010000001000001000000100000101000010000000100000010000010010001010000000"
assert len(BITS) == 121

EXPECTED_MESSAGE = "(* TWO STARS *)"

needs_eda = pytest.mark.skipif(not os.path.exists(f"{BIN}/iverilog"), reason="oss-cad-suite not installed")


def _drive_tb(dut_module, inst_name):
    """A self-checking testbench: reset, 121 enabled cycles of I=BITS, 40 idle cycles,
    then report every O byte and success value, one $display per cycle."""
    return f"""\
`timescale 1ns/1ps
module tb;
  reg clk = 0;
  reg rst_n = 0;
  reg enable = 0;
  reg I = 0;
  wire [7:0] O;
  wire success;

  {dut_module} {inst_name} (.clk(clk), .rst_n(rst_n), .enable(enable), .I(I), .O(O), .success(success));

  always #5 clk = ~clk;

  localparam [120:0] BITS = 121'b{BITS};
  integer k;

  initial begin
    rst_n = 0; enable = 0; I = 0;
    @(negedge clk); @(negedge clk); @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    for (k = 0; k < 121; k = k + 1) begin
      enable = 1;
      I = BITS[120 - k];
      @(negedge clk);
    end
    enable = 0;
    I = 0;
    repeat (40) @(negedge clk);
    $display("SOLUTION-DONE");
    $finish;
  end

  always @(posedge clk) begin
    #1;
    $display("CYCLE O=%02x success=%b", O, success);
  end
endmodule
"""


def _run_and_decode(stdout):
    """Return (message_bytes, success_seen_high, ever_dropped_after_first_high)."""
    o_bytes = []
    success_vals = []
    for line in stdout.splitlines():
        if not line.startswith("CYCLE"):
            continue
        parts = dict(kv.split("=") for kv in line.split()[1:])
        o_bytes.append(int(parts["O"], 16))
        success_vals.append(int(parts["success"]))
    assert any(success_vals), "success never rose"
    first = success_vals.index(1)
    dropped_after = 0 in success_vals[first:]
    msg_bytes = [b for b in o_bytes[first:] if b != 0]
    message = "".join(chr(b) for b in msg_bytes)
    return message, dropped_after


@functools.cache
def lef():
    return read_lef(LEF)


@functools.cache
def extracted_netlist():
    os.makedirs("out/confirm", exist_ok=True)
    ex = Extraction("upstream/puzzle.gds", lef())
    dirs = {p: "input" for p in ("clk", "rst_n", "enable", "I")} | {"O": "output", "success": "output"}
    path = "out/confirm/puzzle.v"
    with open(path, "w") as f:
        f.write(ex.to_verilog(dirs, lef()))
    return path


@needs_eda
def test_answer_extracted_netlist_icarus():
    """Model (a): extracted netlist, Icarus, PDK Verilog cell models."""
    netlist = extracted_netlist()
    tb_path = "out/confirm/tb_answer_a.v"
    with open(tb_path, "w") as f:
        f.write(_drive_tb("puzzle", "puzzle"))
    subprocess.run([f"{BIN}/iverilog", "-g2012", "-DFUNCTIONAL", "-DUNIT_DELAY=", "-o",
                    "out/confirm/tb_answer_a.vvp", tb_path, netlist, *MODELS], check=True, capture_output=True)
    r = subprocess.run([f"{BIN}/vvp", "-n", "out/confirm/tb_answer_a.vvp"], check=True,
                        capture_output=True, text=True)
    message, dropped_after = _run_and_decode(r.stdout)
    assert not dropped_after, r.stdout[-2000:]
    assert message == EXPECTED_MESSAGE, (message, r.stdout[-2000:])


@needs_eda
def test_answer_recovered_rtl_icarus():
    """Model (c): rtl_recovered/puzzle_recovered.v, Icarus."""
    tb_path = "out/confirm/tb_answer_c.v"
    with open(tb_path, "w") as f:
        f.write(_drive_tb("puzzle_recovered", "puzzle_recovered"))
    srcs = ["rtl_recovered/puzzle_recovered.v"] + [f"rtl_recovered/{b}.v" for b in BLOCKS]
    subprocess.run([f"{BIN}/iverilog", "-g2012", "-o", "out/confirm/tb_answer_c.vvp", tb_path, *srcs],
                    check=True, capture_output=True)
    r = subprocess.run([f"{BIN}/vvp", "-n", "out/confirm/tb_answer_c.vvp"], check=True,
                        capture_output=True, text=True)
    message, dropped_after = _run_and_decode(r.stdout)
    assert not dropped_after, r.stdout[-2000:]
    assert message == EXPECTED_MESSAGE, (message, r.stdout[-2000:])


@pytest.mark.skipif(not os.path.exists(f"{BIN}/verilator"), reason="Verilator not installed")
def test_answer_extracted_netlist_verilator():
    """Model (b): extracted netlist flattened through Liberty functions, Verilator."""
    netlist = extracted_netlist()
    flat = "out/confirm/puzzle_libflat.v"
    subprocess.run([f"{BIN}/yosys", "-q", "-p",
                    f"read_liberty -ignore_miss_func {LIB}; read_verilog {netlist}; hierarchy -top puzzle; "
                    f"flatten; proc; opt_clean; write_verilog -noattr {flat}"], check=True)
    tb_path = "out/confirm/tb_answer_b.v"
    with open(tb_path, "w") as f:
        f.write(_drive_tb("puzzle", "puzzle"))
    import shutil
    shutil.rmtree("out/confirm/vl", ignore_errors=True)
    env = dict(os.environ, PATH=BIN + os.pathsep + os.environ["PATH"])
    subprocess.run([f"{BIN}/verilator", "--binary", "--timing", "-Wno-fatal", "-Wno-lint", "-Wno-style",
                    "--top-module", "tb", "-Mdir", "out/confirm/vl", tb_path, flat, "-o", "vtb"],
                   check=True, capture_output=True, env=env)
    r = subprocess.run(["out/confirm/vl/vtb"], check=True, capture_output=True, text=True)
    message, dropped_after = _run_and_decode(r.stdout)
    assert not dropped_after, r.stdout[-2000:]
    assert message == EXPECTED_MESSAGE, (message, r.stdout[-2000:])


@needs_eda
def test_answer_solution_vcd_self_consistent():
    """answer/solution.vcd replays with 0 errors on the extracted netlist (tools/retrace/vcdtb.py)."""
    from tools.retrace.vcdtb import read_vcd
    from tools.retrace.vcdtb import testbench as make_testbench

    netlist = extracted_netlist()
    widths, events = read_vcd("answer/solution.vcd")
    tb_path = "out/confirm/tb_replay_answer.v"
    with open(tb_path, "w") as f:
        f.write(make_testbench(widths, events, "puzzle", ["clk", "rst_n", "enable", "I"], ["O", "success"], "clk"))
    subprocess.run([f"{BIN}/iverilog", "-g2012", "-DFUNCTIONAL", "-DUNIT_DELAY=", "-o",
                    "out/confirm/tb_replay_answer.vvp", tb_path, netlist, *MODELS], check=True, capture_output=True)
    r = subprocess.run([f"{BIN}/vvp", "-n", "out/confirm/tb_replay_answer.vvp"], check=True,
                        capture_output=True, text=True)
    line = next(l for l in r.stdout.splitlines() if l.startswith("VCD-REPLAY"))
    res = dict(kv.split("=") for kv in line.split()[1:])
    assert res["errors"] == "0", r.stdout[-2000:]
