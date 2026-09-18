// rtl_recovered/array.v -- recovered intent for netlist block "array"
// -----------------------------------------------------------------------
// STRUCTURE (verified by exhaustive Boolean simulation of gold_array.v,
// tools/analysis/cone.py's extracted gold cone for this block, over the
// full domain of every input listed below -- not just "reachable" states):
//
//   The block owns 44 of the design's flops (f09..f52, all
//   sky130_fd_sc_hd__dfrtp_2, async-reset-to-0), grouped into 22
//   independent, non-overlapping PAIRS.  Each pair forms a 2-bit
//   SATURATING UP-COUNTER ("bin"): on a cycle where I=1 and enable=1 and
//   this bin's private write-enable condition ("hitNN" below) is true,
//   the bin counts up by one (00->01->10->11) and then HOLDS at 11 (it
//   does not wrap back to 00).  Otherwise the bin holds its value.
//
//     d_msb = q_msb | (hit & q_lsb)
//     d_lsb = (hit & q_msb) | (hit ^ q_lsb)
//
//   which is exactly "increment, saturate at 3" for the 2-bit value
//   {q_msb, q_lsb}.
//
//   The 22 bins are addressed by the *other* block's 9-bit state
//   {q_f00..q_f08} (almost certainly the counter/FSM block, recovered
//   elsewhere as its own block -- this file only consumes its q_fNN
//   outputs, it does not explain them).  Two address styles are used,
//   split cleanly by which half of the state space is being decoded:
//
//   * Bins 0-10  (flops f09..f30): q_f08 must be 0, and the remaining
//     8 bits (q_f00..q_f07) are matched by a per-bin Boolean condition
//     ("hit00".."hit10") that was derived by exhaustively comparing
//     every one of the 256 (q_f08=0) states against the gold netlist
//     and minimizing the resulting exact truth table (sympy SOPform).
//     These 8-bit match sets are NOT simple numeric ranges or masks
//     (verified: not contiguous, not power-of-two sub-cubes) -- they
//     are the literal, exactly-equivalent decode the synthesized gold
//     netlist implements, most likely because the state variable that
//     picks bins 0-10 uses a non-trivial (probably synthesis-chosen)
//     encoding in the source block. The 11 match sets are disjoint and
//     together cover all 256 states of {q_f00..q_f07} when q_f08=0, so
//     bins 0-10 partition that half of the state space completely.
//
//   * Bins 11-21 (flops f31..f52): q_f08 must be 0, and the bin fires
//     on an exact 4-bit equality of {q_f04..q_f07} against one fixed
//     value per bin (q_f00..q_f03 are provably don't-cares here). This
//     half is a clean one-hot address decode.
//
// Flop -> register map (see rtl_recovered/blocks.json for placement):
//   bin  0: f09(msb)/f10(lsb)   bin  6: f21(msb)/f22(lsb)
//   bin  1: f11(msb)/f12(lsb)   bin  7: f23(msb)/f24(lsb)
//   bin  2: f16(msb)/f13(lsb)   bin  8: f25(msb)/f27(lsb)
//   bin  3: f15(msb)/f14(lsb)   bin  9: f26(msb)/f28(lsb)
//   bin  4: f17(msb)/f18(lsb)   bin 10: f29(msb)/f30(lsb)
//   bin  5: f19(msb)/f20(lsb)
//   bin 11: f31/f32   bin 15: f39/f40   bin 19: f47(msb)/f49(lsb)
//   bin 12: f33/f34   bin 16: f41/f42   bin 20: f48(msb)/f50(lsb)
//   bin 13: f35/f36   bin 17: f43/f44   bin 21: f52(msb)/f51(lsb)
//   bin 14: f37/f38   bin 18: f46(msb)/f45(lsb)
// All 44 flops reset asynchronously to 0 (sky130_fd_sc_hd__dfrtp_2), i.e.
// every bin's reset value is 2'b00 -- matched here for free since this
// module is purely combinational next-state logic; the flops themselves
// (outside this file) do the resetting.
//
// Ports q_f00..q_f08 are NOT owned by this block; they are the current
// value of another block's 9-bit state, consumed here combinationally.

module rec_array (I, enable, q_f00, q_f01, q_f02, q_f03, q_f04, q_f05, q_f06, q_f07, q_f08, q_f09, q_f10, q_f11, q_f12, q_f13, q_f14, q_f15, q_f16, q_f17, q_f18, q_f19, q_f20, q_f21, q_f22, q_f23, q_f24, q_f25, q_f26, q_f27, q_f28, q_f29, q_f30, q_f31, q_f32, q_f33, q_f34, q_f35, q_f36, q_f37, q_f38, q_f39, q_f40, q_f41, q_f42, q_f43, q_f44, q_f45, q_f46, q_f47, q_f48, q_f49, q_f50, q_f51, q_f52, d_f09, d_f10, d_f11, d_f12, d_f13, d_f14, d_f15, d_f16, d_f17, d_f18, d_f19, d_f20, d_f21, d_f22, d_f23, d_f24, d_f25, d_f26, d_f27, d_f28, d_f29, d_f30, d_f31, d_f32, d_f33, d_f34, d_f35, d_f36, d_f37, d_f38, d_f39, d_f40, d_f41, d_f42, d_f43, d_f44, d_f45, d_f46, d_f47, d_f48, d_f49, d_f50, d_f51, d_f52);
  input I;
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
  input q_f09;
  input q_f10;
  input q_f11;
  input q_f12;
  input q_f13;
  input q_f14;
  input q_f15;
  input q_f16;
  input q_f17;
  input q_f18;
  input q_f19;
  input q_f20;
  input q_f21;
  input q_f22;
  input q_f23;
  input q_f24;
  input q_f25;
  input q_f26;
  input q_f27;
  input q_f28;
  input q_f29;
  input q_f30;
  input q_f31;
  input q_f32;
  input q_f33;
  input q_f34;
  input q_f35;
  input q_f36;
  input q_f37;
  input q_f38;
  input q_f39;
  input q_f40;
  input q_f41;
  input q_f42;
  input q_f43;
  input q_f44;
  input q_f45;
  input q_f46;
  input q_f47;
  input q_f48;
  input q_f49;
  input q_f50;
  input q_f51;
  input q_f52;
  output d_f09;
  output d_f10;
  output d_f11;
  output d_f12;
  output d_f13;
  output d_f14;
  output d_f15;
  output d_f16;
  output d_f17;
  output d_f18;
  output d_f19;
  output d_f20;
  output d_f21;
  output d_f22;
  output d_f23;
  output d_f24;
  output d_f25;
  output d_f26;
  output d_f27;
  output d_f28;
  output d_f29;
  output d_f30;
  output d_f31;
  output d_f32;
  output d_f33;
  output d_f34;
  output d_f35;
  output d_f36;
  output d_f37;
  output d_f38;
  output d_f39;
  output d_f40;
  output d_f41;
  output d_f42;
  output d_f43;
  output d_f44;
  output d_f45;
  output d_f46;
  output d_f47;
  output d_f48;
  output d_f49;
  output d_f50;
  output d_f51;
  output d_f52;

  // Shared write-enable qualifier for every bin.
  wire wr_en = I & enable;

  // ---- group A bins (0-10): full 8-bit state match (q_f08 must be 0) ----
  wire hit00 = wr_en & ~q_f08 & (
        (q_f01 & q_f03) |
        (q_f00 & q_f01 & q_f02) |
        (q_f01 & q_f02 & q_f04 & q_f07) |
        (q_f01 & q_f02 & q_f05 & q_f06 & q_f07) |
        (q_f03 & ~q_f02 & ~q_f04 & ~q_f06 & ~q_f07) |
        (q_f03 & q_f04 & q_f07 & ~q_f00 & ~q_f02 & ~q_f05) |
        (q_f04 & q_f06 & q_f07 & ~q_f01 & ~q_f03 & ~q_f05) |
        (q_f00 & q_f02 & q_f05 & q_f06 & q_f07 & ~q_f03 & ~q_f04) |
        (q_f00 & q_f03 & ~q_f02 & ~q_f04 & ~q_f05 & ~q_f07) |
        (q_f03 & q_f05 & q_f06 & q_f07 & ~q_f00 & ~q_f02 & ~q_f04) |
        (q_f00 & q_f05 & ~q_f01 & ~q_f02 & ~q_f04 & ~q_f06 & ~q_f07) |
        (q_f02 & q_f05 & ~q_f01 & ~q_f03 & ~q_f04 & ~q_f06 & ~q_f07)
      );
  assign d_f09 = q_f09 | (hit00 & q_f10);
  assign d_f10 = (hit00 & q_f09) | (hit00 ^ q_f10);

  wire hit01 = wr_en & ~q_f08 & (
        (q_f00 & q_f02 & q_f04 & ~q_f01 & ~q_f05 & ~q_f07) |
        (q_f00 & q_f02 & q_f04 & ~q_f01 & ~q_f06 & ~q_f07) |
        (q_f00 & q_f03 & q_f04 & ~q_f01 & ~q_f05 & ~q_f07) |
        (q_f00 & q_f03 & q_f04 & ~q_f01 & ~q_f06 & ~q_f07) |
        (q_f02 & q_f04 & q_f05 & q_f06 & q_f07 & ~q_f01 & ~q_f03) |
        (q_f03 & q_f04 & q_f05 & q_f06 & q_f07 & ~q_f00 & ~q_f01) |
        (q_f02 & q_f03 & q_f04 & q_f05 & ~q_f01 & ~q_f06 & ~q_f07) |
        (q_f03 & q_f04 & ~q_f01 & ~q_f02 & ~q_f05 & ~q_f06 & ~q_f07)
      );
  assign d_f11 = q_f11 | (hit01 & q_f12);
  assign d_f12 = (hit01 & q_f11) | (hit01 ^ q_f12);

  wire hit02 = wr_en & ~q_f08 & (
        (q_f01 & q_f04 & q_f05 & q_f07 & ~q_f00 & ~q_f02 & ~q_f03) |
        (q_f01 & q_f04 & q_f05 & q_f07 & ~q_f02 & ~q_f03 & ~q_f06) |
        (q_f00 & q_f02 & q_f03 & q_f04 & q_f05 & q_f07 & ~q_f01 & ~q_f06) |
        (q_f01 & q_f05 & q_f06 & ~q_f00 & ~q_f03 & ~q_f04 & ~q_f07) |
        (q_f01 & q_f05 & q_f06 & ~q_f02 & ~q_f03 & ~q_f04 & ~q_f07) |
        (q_f00 & q_f01 & q_f04 & ~q_f02 & ~q_f03 & ~q_f05 & ~q_f06 & ~q_f07)
      );
  assign d_f16 = q_f16 | (hit02 & q_f13);
  assign d_f13 = (hit02 & q_f16) | (hit02 ^ q_f13);

  wire hit03 = wr_en & ~q_f08 & (
        (q_f00 & q_f01 & q_f07 & ~q_f02 & ~q_f03 & ~q_f04 & ~q_f05) |
        (q_f00 & q_f01 & q_f07 & ~q_f02 & ~q_f03 & ~q_f04 & ~q_f06) |
        (q_f00 & q_f03 & q_f07 & ~q_f01 & ~q_f02 & ~q_f04 & ~q_f05) |
        (q_f00 & q_f03 & q_f07 & ~q_f01 & ~q_f02 & ~q_f04 & ~q_f06) |
        (q_f02 & q_f03 & q_f07 & ~q_f01 & ~q_f04 & ~q_f05 & ~q_f06) |
        (q_f01 & q_f07 & ~q_f02 & ~q_f03 & ~q_f04 & ~q_f05 & ~q_f06)
      );
  assign d_f15 = q_f15 | (hit03 & q_f14);
  assign d_f14 = (hit03 & q_f15) | (hit03 ^ q_f14);

  wire hit04 = wr_en & ~q_f08 & (
        (q_f07 & ~q_f01 & ~q_f02 & ~q_f03 & ~q_f04 & ~q_f05) |
        (q_f06 & q_f07 & ~q_f00 & ~q_f01 & ~q_f03 & ~q_f04 & ~q_f05)
      );
  assign d_f17 = q_f17 | (hit04 & q_f18);
  assign d_f18 = (hit04 & q_f17) | (hit04 ^ q_f18);

  wire hit05 = wr_en & ~q_f08 & (
        (q_f00 & q_f02 & q_f07 & ~q_f01 & ~q_f03 & ~q_f04 & ~q_f05) |
        (q_f00 & q_f04 & q_f05 & ~q_f01 & ~q_f02 & ~q_f03 & ~q_f07) |
        (q_f04 & q_f05 & q_f06 & ~q_f00 & ~q_f01 & ~q_f03 & ~q_f07) |
        (q_f02 & q_f07 & ~q_f01 & ~q_f03 & ~q_f04 & ~q_f05 & ~q_f06)
      );
  assign d_f19 = q_f19 | (hit05 & q_f20);
  assign d_f20 = (hit05 & q_f19) | (hit05 ^ q_f20);

  wire hit06 = wr_en & ~q_f08 & (
        (~q_f01 & ~q_f03 & ~q_f04 & ~q_f05 & ~q_f07) |
        (q_f04 & q_f07 & ~q_f01 & ~q_f03 & ~q_f05 & ~q_f06) |
        (q_f05 & q_f06 & ~q_f01 & ~q_f02 & ~q_f03 & ~q_f04) |
        (q_f04 & q_f05 & q_f07 & ~q_f00 & ~q_f01 & ~q_f02 & ~q_f03) |
        (q_f05 & q_f06 & q_f07 & ~q_f00 & ~q_f01 & ~q_f03 & ~q_f04) |
        (~q_f00 & ~q_f01 & ~q_f02 & ~q_f03 & ~q_f04 & ~q_f07) |
        (~q_f01 & ~q_f02 & ~q_f03 & ~q_f05 & ~q_f06 & ~q_f07) |
        (q_f06 & ~q_f00 & ~q_f01 & ~q_f02 & ~q_f04 & ~q_f05 & ~q_f07)
      );
  assign d_f21 = q_f21 | (hit06 & q_f22);
  assign d_f22 = (hit06 & q_f21) | (hit06 ^ q_f22);

  wire hit07 = wr_en & ~q_f08 & (
        (q_f02 & q_f03 & q_f04 & q_f07 & ~q_f01 & ~q_f05) |
        (q_f00 & q_f01 & q_f04 & q_f07 & ~q_f02 & ~q_f03 & ~q_f05) |
        (q_f00 & q_f02 & q_f03 & q_f05 & ~q_f01 & ~q_f04 & ~q_f07) |
        (q_f00 & q_f02 & q_f03 & q_f06 & ~q_f01 & ~q_f04 & ~q_f07) |
        (q_f01 & q_f04 & q_f06 & q_f07 & ~q_f02 & ~q_f03 & ~q_f05) |
        (q_f02 & q_f03 & q_f04 & q_f07 & ~q_f00 & ~q_f01 & ~q_f06) |
        (q_f01 & q_f05 & ~q_f00 & ~q_f03 & ~q_f04 & ~q_f06 & ~q_f07) |
        (q_f01 & q_f05 & ~q_f02 & ~q_f03 & ~q_f04 & ~q_f06 & ~q_f07) |
        (q_f01 & q_f06 & ~q_f00 & ~q_f03 & ~q_f04 & ~q_f05 & ~q_f07)
      );
  assign d_f23 = q_f23 | (hit07 & q_f24);
  assign d_f24 = (hit07 & q_f23) | (hit07 ^ q_f24);

  wire hit08 = wr_en & ~q_f08 & (
        (q_f00 & q_f03 & q_f04 & q_f07 & ~q_f01 & ~q_f02) |
        (q_f00 & q_f04 & q_f05 & q_f07 & ~q_f01 & ~q_f02) |
        (q_f02 & q_f03 & q_f05 & q_f06 & q_f07 & ~q_f01 & ~q_f04) |
        (q_f02 & q_f03 & ~q_f00 & ~q_f01 & ~q_f04 & ~q_f07) |
        (q_f02 & q_f04 & ~q_f00 & ~q_f01 & ~q_f05 & ~q_f07) |
        (q_f00 & q_f03 & q_f05 & q_f06 & ~q_f01 & ~q_f02 & ~q_f04) |
        (q_f01 & q_f05 & q_f06 & q_f07 & ~q_f02 & ~q_f03 & ~q_f04) |
        (q_f02 & q_f04 & q_f05 & q_f07 & ~q_f01 & ~q_f03 & ~q_f06) |
        (q_f03 & q_f04 & q_f05 & q_f07 & ~q_f01 & ~q_f02 & ~q_f06) |
        (q_f02 & q_f05 & q_f06 & ~q_f01 & ~q_f03 & ~q_f04 & ~q_f07) |
        (q_f03 & q_f05 & q_f06 & ~q_f01 & ~q_f02 & ~q_f04 & ~q_f07) |
        (q_f00 & q_f01 & ~q_f02 & ~q_f03 & ~q_f04 & ~q_f05 & ~q_f07) |
        (q_f02 & q_f03 & ~q_f01 & ~q_f04 & ~q_f05 & ~q_f06 & ~q_f07) |
        (q_f04 & q_f05 & ~q_f00 & ~q_f01 & ~q_f03 & ~q_f06 & ~q_f07) |
        (q_f04 & q_f06 & ~q_f01 & ~q_f02 & ~q_f03 & ~q_f05 & ~q_f07) |
        (q_f01 & ~q_f00 & ~q_f03 & ~q_f04 & ~q_f05 & ~q_f06 & ~q_f07) |
        (q_f01 & q_f04 & q_f07 & ~q_f00 & ~q_f02 & ~q_f03 & ~q_f05 & ~q_f06)
      );
  assign d_f25 = q_f25 | (hit08 & q_f27);
  assign d_f27 = (hit08 & q_f25) | (hit08 ^ q_f27);

  wire hit09 = wr_en & ~q_f08 & (
        (q_f01 & q_f04 & ~q_f00 & ~q_f03 & ~q_f07) |
        (q_f03 & q_f04 & q_f05 & q_f06 & ~q_f01 & ~q_f07) |
        (q_f00 & q_f02 & q_f03 & q_f04 & q_f05 & q_f06 & ~q_f01) |
        (q_f01 & q_f04 & q_f05 & ~q_f02 & ~q_f03 & ~q_f07) |
        (q_f01 & q_f04 & q_f06 & ~q_f02 & ~q_f03 & ~q_f07) |
        (q_f00 & q_f01 & q_f04 & q_f05 & q_f06 & ~q_f02 & ~q_f03) |
        (q_f00 & q_f02 & q_f04 & q_f05 & q_f06 & ~q_f01 & ~q_f07) |
        (q_f05 & q_f07 & ~q_f01 & ~q_f03 & ~q_f04 & ~q_f06) |
        (q_f01 & q_f02 & q_f07 & ~q_f00 & ~q_f03 & ~q_f04 & ~q_f05) |
        (q_f02 & q_f05 & q_f07 & ~q_f00 & ~q_f03 & ~q_f04 & ~q_f06) |
        (q_f03 & q_f04 & q_f05 & ~q_f00 & ~q_f01 & ~q_f02 & ~q_f07) |
        (q_f03 & q_f04 & q_f06 & ~q_f00 & ~q_f01 & ~q_f02 & ~q_f07) |
        (q_f03 & q_f07 & ~q_f00 & ~q_f01 & ~q_f02 & ~q_f04 & ~q_f05) |
        (q_f05 & q_f07 & ~q_f00 & ~q_f01 & ~q_f02 & ~q_f04 & ~q_f06)
      );
  assign d_f26 = q_f26 | (hit09 & q_f28);
  assign d_f28 = (hit09 & q_f26) | (hit09 ^ q_f28);

  wire hit10 = wr_en & ~q_f08 & (
        (q_f02 & q_f03 & q_f05 & q_f07 & ~q_f01 & ~q_f04 & ~q_f06) |
        (q_f02 & q_f03 & q_f06 & q_f07 & ~q_f01 & ~q_f04 & ~q_f05) |
        (q_f01 & q_f05 & q_f07 & ~q_f00 & ~q_f02 & ~q_f03 & ~q_f04 & ~q_f06) |
        (q_f01 & q_f06 & q_f07 & ~q_f00 & ~q_f02 & ~q_f03 & ~q_f04 & ~q_f05)
      );
  assign d_f29 = q_f29 | (hit10 & q_f30);
  assign d_f30 = (hit10 & q_f29) | (hit10 ^ q_f30);

  // ---- group B bins (11-21): direct 4-bit equality on q_f04..q_f07 (q_f08 must be 0) ----
  wire hit11 = wr_en & ~q_f08 & ~q_f04 & ~q_f05 & ~q_f06 & ~q_f07;
  assign d_f31 = q_f31 | (hit11 & q_f32);
  assign d_f32 = (hit11 & q_f31) | (hit11 ^ q_f32);

  wire hit12 = wr_en & ~q_f08 & ~q_f04 & ~q_f05 & q_f06 & ~q_f07;
  assign d_f33 = q_f33 | (hit12 & q_f34);
  assign d_f34 = (hit12 & q_f33) | (hit12 ^ q_f34);

  wire hit13 = wr_en & ~q_f08 & ~q_f04 & q_f05 & ~q_f06 & ~q_f07;
  assign d_f35 = q_f35 | (hit13 & q_f36);
  assign d_f36 = (hit13 & q_f35) | (hit13 ^ q_f36);

  wire hit14 = wr_en & ~q_f08 & ~q_f04 & q_f05 & q_f06 & ~q_f07;
  assign d_f37 = q_f37 | (hit14 & q_f38);
  assign d_f38 = (hit14 & q_f37) | (hit14 ^ q_f38);

  wire hit15 = wr_en & ~q_f08 & q_f04 & ~q_f05 & ~q_f06 & ~q_f07;
  assign d_f39 = q_f39 | (hit15 & q_f40);
  assign d_f40 = (hit15 & q_f39) | (hit15 ^ q_f40);

  wire hit16 = wr_en & ~q_f08 & q_f04 & ~q_f05 & q_f06 & ~q_f07;
  assign d_f41 = q_f41 | (hit16 & q_f42);
  assign d_f42 = (hit16 & q_f41) | (hit16 ^ q_f42);

  wire hit17 = wr_en & ~q_f08 & q_f04 & q_f05 & ~q_f06 & ~q_f07;
  assign d_f43 = q_f43 | (hit17 & q_f44);
  assign d_f44 = (hit17 & q_f43) | (hit17 ^ q_f44);

  wire hit18 = wr_en & ~q_f08 & q_f04 & q_f05 & q_f06 & ~q_f07;
  assign d_f46 = q_f46 | (hit18 & q_f45);
  assign d_f45 = (hit18 & q_f46) | (hit18 ^ q_f45);

  wire hit19 = wr_en & ~q_f08 & ~q_f04 & ~q_f05 & q_f06 & q_f07;
  assign d_f47 = q_f47 | (hit19 & q_f49);
  assign d_f49 = (hit19 & q_f47) | (hit19 ^ q_f49);

  wire hit20 = wr_en & ~q_f08 & ~q_f04 & ~q_f05 & ~q_f06 & q_f07;
  assign d_f48 = q_f48 | (hit20 & q_f50);
  assign d_f50 = (hit20 & q_f48) | (hit20 ^ q_f50);

  wire hit21 = wr_en & ~q_f08 & ~q_f04 & q_f05 & ~q_f06 & q_f07;
  assign d_f52 = q_f52 | (hit21 & q_f51);
  assign d_f51 = (hit21 & q_f52) | (hit21 ^ q_f51);


endmodule
