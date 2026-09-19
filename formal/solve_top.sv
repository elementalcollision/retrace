// Route B (formal): SymbiYosys top-level for a blind search on the EXTRACTED NETLIST
// (out/solve_b/puzzle.v, copied into the SBY work dir as puzzle.v) for an input
// sequence that makes `success` go high. This harness assumes NOTHING about what the
// design does inside -- no Star Battle rules, no bit weights, no block boundaries. It
// only uses the facts given by the ports themselves and by the task: one clock, an
// active-low reset on rst_n, a free single-bit input I, and a hold-line enable.
//
// Reset/enable policy (the "simplest first" case from the task): rst_n is low only in
// the first cycle, then high forever; enable is driven high on every cycle after that
// (no gaps). I is left completely free every cycle -- the solver chooses it.
//
// Two properties are compiled in, selected by `SOLVE_BMC`:
//   - default (cover mode):            cover (success);
//   - `SOLVE_BMC` defined (bmc mode):  assert (!success);
// A cover-mode run must NOT also carry the `assert(!success)` -- SBY's cover engines
// (`smtbmc -c`) turn every `assert` into an `assume`, which would forbid success before
// the solver even starts looking. Each task in formal/solve.sby therefore reads this
// file with the right `-D` for its mode (see tools/solve/formal_solve.py).
module solve_top (input clk, input I);
  wire rst_n;
  wire enable;
  wire success;
  wire [7:0] O;

  reg init = 1'b1;
  always @(posedge clk) init <= 1'b0;

  assign rst_n  = !init;   // low in cycle 0, high from cycle 1 on
  assign enable = !init;   // high on every cycle once rst_n is high (no gaps)

  puzzle dut (
    .clk(clk),
    .rst_n(rst_n),
    .enable(enable),
    .I(I),
    .success(success),
    .O(O)
  );

`ifdef SOLVE_BMC
  always @(*) assert (!success);
`else
  always @(*) cover (success);
`endif
endmodule
