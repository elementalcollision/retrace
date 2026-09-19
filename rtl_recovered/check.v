// Recovered intent of block "check" (rtl_recovered/blocks.json).
//
// This block owns 3 flops and the single-bit primary output `success`:
//
//   fNN   register name     reset   meaning
//   ---   ---------------   -----   -------------------------------------------------
//   f77   alt_latch         0       set instead of f78 when the trigger fires with
//                                   q_f64 == 1; otherwise unused (not wired to any
//                                   primary output of the design)
//   f78   success_latch     0       drives `success`; set on the trigger cycle when
//                                   q_f64 == 0 and every gate condition below holds
//   f79   armed             0       sticky "already evaluated" flag: becomes 1 the
//                                   first time the counter's top bit is seen high and
//                                   then stays 1 forever (until reset)
//
// It reads, but does not own:
//   q_f08          counter MSB (block "counter")
//   q_f09..q_f52   44 "array" flops (block "array")
//   q_f53, q_f64   2 "left_top" flops (block "left_top")
//   q_f69..q_f76   8 "left_bottom" flops (block "left_bottom")
//
// Behaviour
// ---------
// `trigger` is a one-shot pulse: it is high on the single cycle where the counter's
// top bit q_f08 is first seen 1 (f79 has not latched yet). Because f79 then latches
// high permanently (d_f79 = q_f08 | q_f79, an OR self-latch with no way back to 0
// except async reset), `trigger` can fire at most once per reset interval.
//
// On that one cycle, the block evaluates a single AND of four independent gate
// conditions ("pass"):
//   1. rows_ok         : q_f53 == 0 (left_top's row_count_err: every row held exactly 2 stars)
//   2. left_bottom_ok  : the 8 "left_bottom" flops equal a fixed pattern
//   3. array_ok        : the 44 "array" flops equal a fixed 44-bit constant
//                         (the netlist computes this as 22 independent
//                         AND2/AND2B "bit == 1" / "bit == 0" checks, one per array
//                         flop, so it reduces exactly to array bus == constant)
//   4. trigger itself
//
// If `pass` holds, exactly one of the two latches is set that cycle, chosen by
// q_f64 (f77 for 1, f78/success for 0); the other stays/gets cleared to 0. If
// `pass` does not hold, both latches are cleared to 0 that cycle. On every other
// cycle (trigger low) both latches simply hold their previous value, so whatever
// was decided on the trigger cycle is permanent thereafter.
//
// Net effect: `success` becomes and stays 1 iff, at the moment the counter's top
// bit first goes high, q_f53 == 0, q_f64 == 0, the left_bottom flops match their
// fixed pattern, and the array flops match their fixed 44-bit pattern. Otherwise
// success is (and remains) 0 for the rest of the run.

module rec_check (
  q_f08,
  q_f09, q_f10, q_f11, q_f12, q_f13, q_f14, q_f15, q_f16, q_f17, q_f18, q_f19,
  q_f20, q_f21, q_f22, q_f23, q_f24, q_f25, q_f26, q_f27, q_f28, q_f29,
  q_f30, q_f31, q_f32, q_f33, q_f34, q_f35, q_f36, q_f37, q_f38, q_f39,
  q_f40, q_f41, q_f42, q_f43, q_f44, q_f45, q_f46, q_f47, q_f48, q_f49,
  q_f50, q_f51, q_f52,
  q_f53, q_f64,
  q_f69, q_f70, q_f71, q_f72, q_f73, q_f74, q_f75, q_f76,
  q_f77, q_f78, q_f79,
  d_f77, d_f78, d_f79,
  success
);
  input q_f08;
  input q_f09, q_f10, q_f11, q_f12, q_f13, q_f14, q_f15, q_f16, q_f17, q_f18, q_f19;
  input q_f20, q_f21, q_f22, q_f23, q_f24, q_f25, q_f26, q_f27, q_f28, q_f29;
  input q_f30, q_f31, q_f32, q_f33, q_f34, q_f35, q_f36, q_f37, q_f38, q_f39;
  input q_f40, q_f41, q_f42, q_f43, q_f44, q_f45, q_f46, q_f47, q_f48, q_f49;
  input q_f50, q_f51, q_f52;
  input q_f53, q_f64;
  input q_f69, q_f70, q_f71, q_f72, q_f73, q_f74, q_f75, q_f76;
  input q_f77, q_f78, q_f79;
  output d_f77, d_f78, d_f79;
  output success;

  // --- the 44 "array" flops, MSB = f52 .. LSB = f09 -------------------------------
  wire [43:0] array_bits = {
    q_f52, q_f51, q_f50, q_f49, q_f48, q_f47, q_f46, q_f45, q_f44, q_f43,
    q_f42, q_f41, q_f40, q_f39, q_f38, q_f37, q_f36, q_f35, q_f34, q_f33,
    q_f32, q_f31, q_f30, q_f29, q_f28, q_f27, q_f26, q_f25, q_f24, q_f23,
    q_f22, q_f21, q_f20, q_f19, q_f18, q_f17, q_f16, q_f15, q_f14, q_f13,
    q_f12, q_f11, q_f10, q_f09
  };

  // Fixed target the array must match exactly (recovered from 22 AND2/AND2B gates,
  // each pinning one array flop to 1 and its partner to 0; together they cover all
  // 44 flops exactly once, i.e. the netlist is testing array_bits == this constant).
  localparam [43:0] ARRAY_TARGET =
    44'b1000_1110_0101_0101_0101_0101_0011_0101_0101_1100_0101;

  // --- the 8 "left_bottom" flops, MSB = f76 .. LSB = f69 --------------------------
  wire [7:0] left_bottom_bits =
    {q_f76, q_f75, q_f74, q_f73, q_f72, q_f71, q_f70, q_f69};

  // raw pattern in flop-id order f76..f69 = 0,0,0,0,1,0,1,1; with the counter's bit weights
  // (LSB->MSB f75,f70,f72,f74,f69,f71,f73,f76, see left_bottom.v) this is the count 22
  localparam [7:0] LEFT_BOTTOM_TARGET = 8'b0000_1011;

  wire array_ok        = (array_bits == ARRAY_TARGET);
  wire left_bottom_ok   = (left_bottom_bits == LEFT_BOTTOM_TARGET);
  wire rows_ok          = ~q_f53;   // left_top's row_count_err

  // One-shot: high only on the cycle the counter MSB is first seen high.
  wire trigger = q_f08 & ~q_f79;

  wire pass = trigger & rows_ok & left_bottom_ok & array_ok;

  assign d_f79 = q_f08 | q_f79;                              // sticky "armed" flag
  assign d_f77 = (pass & q_f64)  | (q_f77 & ~trigger);        // latch, alt outcome
  assign d_f78 = (pass & ~q_f64) | (q_f78 & ~trigger);        // latch, success outcome

  assign success = q_f78;

endmodule
