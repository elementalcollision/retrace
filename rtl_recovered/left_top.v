// ============================================================================
// rec_left_top -- recovered intent for netlist block "left_top"
//
// Purely combinational: this block's 16 flops (f53..f68, all dfrtp_2 = async
// reset to 0, confirmed in rtl_recovered/blocks.json) live outside this
// module. This module computes next-state (d_fNN) as a function of current
// state (q_fNN) and the primary inputs I, enable, plus four bits (q_f04,
// q_f05, q_f06, q_f07, q_f08) read from the "counter" block.
//
// Structure (recovered from the gate netlist rtl_recovered/gold/gold_left_top.v
// by flattening with yosys/abc to boolean equations and simplifying by hand;
// every step below is re-checked bit-for-bit by the SAT proof in
// tools.analysis.cone, and independently cross-checked with a directed+random
// Icarus testbench against gold_left_top -- see the review note below):
//
//   1. A 12-stage shift register that records the last 12 samples of I,
//      one new sample per cycle that `shift_en` is asserted:
//
//          I -> f67 -> f66 -> f68 -> f63 -> f60 -> f58
//             -> f61 -> f56 -> f57 -> f59 -> f62 -> f65
//
//      (f67 is the newest tap = last-seen I; f65 is the oldest tap =
//      I from 12 shift_en cycles ago.) This matches the scout hint: a
//      12-stage enable-gated shift chain over f53..f68, and the block's
//      "check" outputs (below) read taps f53..f64 style state.
//
//   2. `shift_en` = enable & ~q_f08. q_f08 is the top bit of the 5-bit
//      counter block (f04..f08); the shift register only advances while
//      that bit is low, i.e. during the low half of each counter sweep.
//
//   3. `check_slot` = one specific value of the counter's low 4 bits
//      (q_f04, q_f05, q_f06, q_f07): true exactly when q_f04=0, q_f05=1,
//      q_f06=0, q_f07=1. (If those four bits are the counter's bits
//      [3:0] in that order, this is counter[3:0] == 4'd10; stated here
//      as an observation about the boolean condition, not a claim about
//      the counter block's own numbering.) This is the cycle each round
//      the two "checker" flops below evaluate their sticky verdicts.
//
//   4. The per-row star count (renamed 2026-09-19; first recovered as a
//      "serial comparator" match_ok/cmp_state/cmp_hold):
//        - {f54, f55} = row_stars, a 2-bit saturating count of the stars
//          (I = 1 cells) entered so far in the current row: 0, 1, 2, or
//          3 meaning three or more. Cleared at the row's last cell
//          (check_slot, column 10).
//        - f53 = row_count_err, a sticky ("once set, stays set" until
//          reset) error flag: set at a row's last cell when that row's
//          final count, including the current cell, is not exactly 2.
//          success needs it clear (check.v), i.e. two stars in every row.
//
//   5. f64 (hist_hit) is a second, independent sticky flag ("once true,
//      stays true" until reset): it latches whenever, during a shift_en
//      cycle with I=1, the shift-register taps f59/f62/f65/f67 and the
//      counter's low bits satisfy `hist_hit_cond` below, i.e. the new star
//      touches an earlier one (left, or the three cells above; no
//      wraparound). check.v routes pass & hist_hit to the TWO NOT TOUCH latch.
//
// Scope note (review, 2026-09-18): the claim that "downstream logic reads
// q_f53 and q_f64" comes from an external scout hint about connectivity
// *outside* this module, and cannot be confirmed from left_top.v alone --
// this file only produces q_f53/q_f64 as ordinary flop outputs like any
// other d_fNN here. Everything below the line -- shift_en, check_slot, the
// shift chain, and the row_count_err/hist_hit latch conditions -- is this
// module's own behavior and is fully proven (SAT-equivalent to
// gold_left_top.v via tools.analysis.cone: "V7 left_top PASS") and
// independently testbench-verified (612/612 checks, directed + 500-vector
// random cross-check, out/verify/left_top/tb_left_top.v).
//
// Flop map (all sky130_fd_sc_hd__dfrtp_2, async-reset-to-0 by rst_n,
// clocked by clk; per-flop next-state meaning):
//   f53 row_count_err -- sticky error flag. Set on a check_slot cycle (while
//                        shift_en) when row_stars + I != 2; never cleared
//                        until reset.
//   f54 row_stars_hi  -- row_stars bit 1. While shift_en: 0 on a check_slot
//                        cycle, else the saturating row_stars + I. Frozen when
//                        shift_en is low.
//   f55 row_stars_lo  -- row_stars bit 0, same update.
//   f56 shift[7]    -- shift-register tap: next = q_f61 when shift_en, else
//                      holds.
//   f57 shift[8]    -- shift-register tap: next = q_f56 when shift_en, else
//                      holds.
//   f58 shift[5]    -- shift-register tap: next = q_f60 when shift_en, else
//                      holds.
//   f59 shift[9]    -- shift-register tap: next = q_f57 when shift_en, else
//                      holds. Also feeds hist_hit_cond (tap_9_off_slot).
//   f60 shift[4]    -- shift-register tap: next = q_f63 when shift_en, else
//                      holds.
//   f61 shift[6]    -- shift-register tap: next = q_f58 when shift_en, else
//                      holds.
//   f62 shift[10]   -- shift-register tap: next = q_f59 when shift_en, else
//                      holds. Also feeds hist_hit_cond directly.
//   f63 shift[3]    -- shift-register tap: next = q_f68 when shift_en, else
//                      holds.
//   f64 hist_hit    -- sticky "history pattern seen" flag. Latches on a
//                      shift_en cycle with I=1 when hist_hit_cond holds
//                      (q_f62, or (q_f65|q_f67)&any_low_counter_bit, or
//                      q_f59&~check_slot). Holds thereafter until reset.
//   f65 shift[11]   -- shift-register tap (oldest, I from 12 shift_en
//                      cycles ago): next = q_f62 when shift_en, else holds.
//                      Also feeds hist_hit_cond (tap_0_or_11_hit).
//   f66 shift[1]    -- shift-register tap: next = q_f67 when shift_en, else
//                      holds.
//   f67 shift[0]    -- shift-register tap (newest = last-seen I): next = I
//                      when shift_en, else holds. Also feeds hist_hit_cond
//                      (tap_0_or_11_hit).
//   f68 shift[2]    -- shift-register tap: next = q_f66 when shift_en, else
//                      holds.
// ============================================================================

module rec_left_top (
    I, enable,
    q_f04, q_f05, q_f06, q_f07, q_f08,
    q_f53, q_f54, q_f55, q_f56, q_f57, q_f58, q_f59,
    q_f60, q_f61, q_f62, q_f63, q_f64, q_f65, q_f66, q_f67, q_f68,
    d_f53, d_f54, d_f55, d_f56, d_f57, d_f58, d_f59,
    d_f60, d_f61, d_f62, d_f63, d_f64, d_f65, d_f66, d_f67, d_f68
);
  input I;
  input enable;
  input q_f04, q_f05, q_f06, q_f07, q_f08;
  input q_f53, q_f54, q_f55, q_f56, q_f57, q_f58, q_f59;
  input q_f60, q_f61, q_f62, q_f63, q_f64, q_f65, q_f66, q_f67, q_f68;
  output d_f53, d_f54, d_f55, d_f56, d_f57, d_f58, d_f59;
  output d_f60, d_f61, d_f62, d_f63, d_f64, d_f65, d_f66, d_f67, d_f68;

  // -- shared control -------------------------------------------------------
  wire shift_en   = enable & ~q_f08;
  wire check_slot = ~q_f04 & q_f05 & ~q_f06 & q_f07;

  // -- 1. 12-stage shift register over I, one tap per named flop ------------
  assign d_f67 = shift_en ? I     : q_f67;   // shift[0]  (newest)
  assign d_f66 = shift_en ? q_f67 : q_f66;   // shift[1]
  assign d_f68 = shift_en ? q_f66 : q_f68;   // shift[2]
  assign d_f63 = shift_en ? q_f68 : q_f63;   // shift[3]
  assign d_f60 = shift_en ? q_f63 : q_f60;   // shift[4]
  assign d_f58 = shift_en ? q_f60 : q_f58;   // shift[5]
  assign d_f61 = shift_en ? q_f58 : q_f61;   // shift[6]
  assign d_f56 = shift_en ? q_f61 : q_f56;   // shift[7]
  assign d_f57 = shift_en ? q_f56 : q_f57;   // shift[8]
  assign d_f59 = shift_en ? q_f57 : q_f59;   // shift[9]
  assign d_f62 = shift_en ? q_f59 : q_f62;   // shift[10]
  assign d_f65 = shift_en ? q_f62 : q_f65;   // shift[11] (oldest)

  // -- 5. hist_hit: sticky flag latched from shift-register taps ------------
  wire any_low_counter_bit = q_f04 | q_f05 | q_f06 | q_f07;
  wire tap_0_or_11_hit     = (q_f65 | q_f67) & any_low_counter_bit;
  wire tap_9_off_slot      = q_f59 & ~check_slot;
  wire hist_hit_cond       = q_f62 | tap_0_or_11_hit | tap_9_off_slot;

  assign d_f64 = q_f64 | (I & shift_en & hist_hit_cond);

  // -- 4. per-row star count and the row error flag --------------------------
  // row_stars: saturating count of stars so far in this row (3 = three or more),
  // cleared at the row's last cell (check_slot).
  wire [1:0] row_stars      = {q_f54, q_f55};
  wire [1:0] row_stars_inc  = (row_stars == 2'd3) ? 2'd3 : row_stars + {1'b0, I};
  wire [1:0] row_stars_next = check_slot ? 2'd0 : row_stars_inc;
  assign {d_f54, d_f55} = shift_en ? row_stars_next : row_stars;

  // row_count_err (f53): sticky; set at the row's last cell unless the row,
  // including this cell, holds exactly two stars.
  wire row_not_two = ({1'b0, row_stars} + {2'b0, I}) != 3'd2;
  assign d_f53 = q_f53 | (check_slot & shift_en & row_not_two);

endmodule
