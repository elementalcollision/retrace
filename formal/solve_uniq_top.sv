// Route B (formal), step 4: uniqueness re-run on the EXTRACTED NETLIST. Same reset/
// enable policy as formal/solve_top.sv (rst_n low only in cycle 0, enable high on every
// cycle after that, I free). In addition, a sticky `differs` register goes high the
// first time the free I disagrees with FOUND_I[] -- route B's own solution from step 1-3
// -- on one of the 121 enabled cycles before the decision. FOUND_I[] comes from
// out/solve_b/solve_found_bits.vh, written by tools/solve/formal_solve.py after a
// solution is found; it is NOT read from, or influenced by, the analytical route.
//
//   cover mode:  cover (success && differs)  -- reachable  => another input also wins.
//   bmc mode:    assert (!(success && differs)) -- holds   => no other CONTIGUOUS-ENABLE
//                input (I free every cycle, enable high every cycle from cycle 1, up to
//                this depth) reaches success while differing from FOUND_I[] in any of the
//                first 121 enabled cycles.
`include "solve_found_bits.vh"

module solve_uniq_top (input clk, input I);
  wire rst_n;
  wire enable;
  wire success;
  wire [7:0] O;

  reg init = 1'b1;
  always @(posedge clk) init <= 1'b0;

  assign rst_n  = !init;
  assign enable = !init;

  puzzle dut (
    .clk(clk),
    .rst_n(rst_n),
    .enable(enable),
    .I(I),
    .success(success),
    .O(O)
  );

  // 0-indexed count of enabled cycles seen so far (saturates at 121; harness enables
  // every cycle after reset, so this is just "cycles since reset" clamped to 121).
  reg [7:0] cyc = 8'd0;
  always @(posedge clk)
    if (enable && cyc < 8'd121)
      cyc <= cyc + 8'd1;
  wire sample_now = enable && (cyc < 8'd121);
  // FOUND_I is declared [127:0] (121 real bits, 7 defined-zero padding bits for the
  // unreachable codes 121-127 of the 7-bit index) rather than [120:0]: `FOUND_I[cyc[6:0]]`
  // is a hardware multiplexer selected by a 7-bit signal, and Yosys synthesizes ALL 128
  // decode branches whether or not cyc[6:0] can dynamically reach them -- with a [120:0]
  // array, the 121-127 branches read as Verilog's defined out-of-range value, 'x',
  // structurally baked into the netlist regardless of reachability, which the SMT2
  // backend tolerates but `write_aiger` (abc bmc3's engine) refuses outright ('Design
  // contains x or z bits'). Padding to a full 128-entry table keeps every branch defined.
  reg differs = 1'b0;
  always @(posedge clk)
    if (sample_now && I != FOUND_I[cyc[6:0]])
      differs <= 1'b1;

`ifdef SOLVE_BMC
  always @(*) assert (!(success && differs));
`else
  always @(*) cover (success && differs);
`endif
endmodule
