// rtl_recovered/left_bottom.v
//
// Block "left_bottom": an 8-bit synchronous up-counter with an external
// freeze input, implemented as a standard ripple-carry incrementer.
//
// Behaviour (combinational next-state function; the flops live outside
// this module, one dfrtp_2 -- async reset to 0 -- per bit):
//
//   if (q_f08)                 counter_next = counter;        // frozen
//   else if (I && enable)      counter_next = counter + 1;    // count up
//   else                       counter_next = counter;        // held
//
// i.e. counter_next = counter + (~q_f08 & I & enable), 8-bit wraparound
// (0xFF + 1 == 0x00). q_f08 is a flop that belongs to a different
// recovered block ("counter" in rtl_recovered/blocks.json); here it is
// only ever read, as a freeze/hold qualifier over the increment strobe
// (I & enable).
//
// This was verified two ways: (1) forcing q_f08=1 exhaustively over all
// 2^10 remaining input combinations leaves every d_fNN == q_fNN (proves
// the freeze); (2) with q_f08=0, exhaustive search over all 720
// permutations of {f69,f70,f71,f72,f73,f74} as bit-positions 1..6 (with
// f75 fixed at bit 0 and f76 fixed at bit 7, established first because
// their equations only reference a single running AND-chain "carry")
// found exactly one permutation for which every d_fNN, over the full
// 2^11-row truth table, equals a standard binary-incrementer bit
// (bit_i XOR (running AND of all lower bits, gated by the increment
// strobe)). That unique bit order is f75 (LSB) .. f76 (MSB), used below.
//
// Flop map (all sky130_fd_sc_hd__dfrtp_2, async reset to 0 -> counter
// resets to 8'h00):
//
//   fNN   counter bit   reset
//   f75   bit 0 (LSB)   0
//   f70   bit 1         0
//   f72   bit 2         0
//   f74   bit 3         0
//   f69   bit 4         0
//   f71   bit 5         0
//   f73   bit 6         0
//   f76   bit 7 (MSB)   0
//
module rec_left_bottom (
    I, enable,
    q_f08,
    q_f69, q_f70, q_f71, q_f72, q_f73, q_f74, q_f75, q_f76,
    d_f69, d_f70, d_f71, d_f72, d_f73, d_f74, d_f75, d_f76
);
  input  I;
  input  enable;
  input  q_f08;
  input  q_f69, q_f70, q_f71, q_f72, q_f73, q_f74, q_f75, q_f76;
  output d_f69, d_f70, d_f71, d_f72, d_f73, d_f74, d_f75, d_f76;

  // Current counter value, assembled from the flops in their true
  // bit-significance order (MSB .. LSB).
  wire [7:0] counter = {q_f76, q_f73, q_f71, q_f69, q_f74, q_f72, q_f70, q_f75};

  // Count up by one whenever I and enable are both asserted, unless
  // q_f08 freezes the counter for this cycle.
  wire count_up = ~q_f08 & I & enable;
  wire [7:0] counter_next = count_up ? (counter + 8'd1) : counter;

  // Scatter the next-state bits back out to each flop's D input, in the
  // same order used to assemble `counter`.
  assign {d_f76, d_f73, d_f71, d_f69, d_f74, d_f72, d_f70, d_f75} = counter_next;

endmodule
