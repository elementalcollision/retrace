// Block "counter": a base-11x11 (mod-121) cycle counter with a one-shot "done" latch.
//
// Recovered intent: the design counts enabled clock cycles in two nested
// digits, `lo` and `hi`, each running 0..10 (11 states -- NOT a power of
// two, hence the comparator against decimal 10 instead of a plain binary
// wraparound). `lo` is the fast (ones) digit; it increments every enabled
// cycle. When `lo` reaches 10 it resets to 0 and `hi` (the elevens digit)
// increments. When BOTH `lo` and `hi` are at 10 (i.e. this is the 121st
// enabled cycle, count == 120), the whole thing resets to 0 and sets a
// permanent `done` latch instead of continuing to 121. Once `done` is set,
// every next-state output (`d_f00`..`d_f08`) freezes at its current value
// (enable is ignored) -- confirmed by the gold netlist, where an AND2B gate
// computes `enable & ~q_f08` (net n36) and that term gates every gate whose
// output feeds into a `d_fXX` output. Two small internal comparator
// sub-terms (the lo==10 digit-max detector n37, and a hi-comparator
// sub-term n456) are themselves computed without first going through n36 --
// necessarily so, since a term must be evaluated before it can be gated --
// but both are then gated downstream (via n36-derived signals such as n605
// and n560/n559) before reaching any `d_fXX` output, so the freeze-when-done
// property still holds for every flop's next-state value. This matches the
// sample trace: enable is held for exactly 121 cycles per run, so `done`
// locks in on the very last enabled cycle of a run, one cycle before enable
// falls.
//
// Flop map (all dfrtp, async reset to 0):
//   f06 -> lo[0] (LSB)   f05 -> lo[1]   f04 -> lo[2]   f07 -> lo[3] (MSB)
//   f00 -> hi[0] (LSB)   f02 -> hi[1]   f03 -> hi[2]   f01 -> hi[3] (MSB)
//   f08 -> done  (latched "cycle count has reached 121" flag)
//
// Reset value: lo = 0, hi = 0, done = 0 (count 0, not yet done), matching
// dfrtp reset-to-0 on all 9 flops.
//
// Other blocks' dependence on this counter (per the scout hint, confirmed
// by V4/structural placement): q_f04..q_f08 (hi[2], done, lo[2], lo[1],
// lo[0] in this naming -- i.e. bits of `lo` plus `done`) feed left_top;
// q_f08 (`done`) feeds left_bottom/check/outgen. So `done` is the signal
// the rest of the design uses to know "this run's counting is finished".

module rec_counter (enable, q_f00, q_f01, q_f02, q_f03, q_f04, q_f05, q_f06, q_f07, q_f08, d_f00, d_f01, d_f02, d_f03, d_f04, d_f05, d_f06, d_f07, d_f08);
  input enable;
  input q_f00;
  input q_f01;
  input q_f02;
  input q_f03;
  input q_f04;
  input q_f05;
  input q_f06;
  input q_f07;
  input q_f08;
  output d_f00;
  output d_f01;
  output d_f02;
  output d_f03;
  output d_f04;
  output d_f05;
  output d_f06;
  output d_f07;
  output d_f08;

  localparam [3:0] DIGIT_MAX = 4'd10; // 0..10 = 11 states per digit

  // Current-state digits, assembled from the current flop values.
  wire [3:0] lo = {q_f07, q_f04, q_f05, q_f06}; // lo[3:0], lo[0]=f06 .. lo[3]=f07
  wire [3:0] hi = {q_f01, q_f03, q_f02, q_f00}; // hi[3:0], hi[0]=f00 .. hi[3]=f01
  wire       done = q_f08;

  wire lo_wraps = enable && !done && (lo == DIGIT_MAX);
  wire hi_wraps = lo_wraps && (hi == DIGIT_MAX);

  wire [3:0] lo_next = !enable || done ? lo
                      : lo_wraps        ? 4'd0
                      :                   lo + 4'd1;

  wire [3:0] hi_next = !enable || done ? hi
                      : hi_wraps        ? 4'd0
                      : lo_wraps        ? hi + 4'd1
                      :                   hi;

  wire done_next = done || hi_wraps;

  assign d_f06 = lo_next[0];
  assign d_f05 = lo_next[1];
  assign d_f04 = lo_next[2];
  assign d_f07 = lo_next[3];

  assign d_f00 = hi_next[0];
  assign d_f02 = hi_next[1];
  assign d_f03 = hi_next[2];
  assign d_f01 = hi_next[3];

  assign d_f08 = done_next;

endmodule
