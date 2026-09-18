// rtl_recovered/puzzle_recovered.v
//
// Top-level integration of the six recovered blocks (rtl_recovered/{counter,array,
// left_top,left_bottom,check,outgen}.v) into module puzzle_recovered(clk, rst_n,
// enable, I, O[7:0], success), the same ports as the extracted netlist (see
// out/puzzle.v / test/test_crosscheck.py).
//
// This file owns ONLY the top level: the 92 register declarations (one per flop,
// named for what it holds instead of its raw fNN id -- see docs/INTENT.md for the
// full register map and the per-block behavioural summaries), their reset/set
// behaviour exactly as recorded in rtl_recovered/blocks.json (84 sky130_fd_sc_hd__
// dfrtp_2 flops async-reset to 0, 4 dfstp_2 flops async-set to 1: f81/f83/f84/f87,
// the outgen scrambler; 4 dfxtp_2 flops with no reset at all: f88-f91, the outgen
// "pos" playback counter), and the port-map instantiation of the six unmodified
// rec_* blocks. No combinational logic lives here -- every d_fNN next-state
// equation is exactly what its own rtl_recovered/<block>.v file computes and
// proves (V7, tools.analysis.cone) against the extracted netlist's gold cone.
//
// Flop id <-> meaningful name cross-reference: see the `reg <name>; // fNN, ...`
// comment on every declaration below, and docs/INTENT.md's register-map tables
// (one per block, reproduced from each block file's own header).
//
// dfxtp caveat (f88-f91, outgen's "pos" register): these 4 flops have NO reset
// pin in the gate netlist, so on real silicon (and in any faithful gate-level
// simulation) they power up to an arbitrary value. This RTL models that with
// plain `always @(posedge clk)` (no reset branch), so `pos` is X until the first
// clock edge in simulation (matching gold: the extracted netlist's own dfxtp_2
// instances are equally uninitialized). In practice this does not matter: `pos`'s
// own next-state equation (rtl_recovered/outgen.v) is `pos_next = armed ?
// next_pos(pos) : 0`, and `armed` (f79) has a real reset and is 0 the cycle right
// after rst_n deasserts, so `pos` is forced to a known value (0) by the second
// cycle regardless of its power-on state -- proven as part of the unconditional
// (no extra assumption needed) end-to-end proof; see tools/analysis/e2e.py
// and docs/INTENT.md section 6.3.

module puzzle_recovered (
    clk, rst_n, enable, I, O, success
);
  input clk, rst_n, enable, I;
  output [7:0] O;
  output success;

  // -- counter (f00-f08): mod-121 (11x11) cycle counter + done latch --
  reg hi0;  // f00, reset 0 (dfrtp)
  reg hi3;  // f01, reset 0 (dfrtp)
  reg hi1;  // f02, reset 0 (dfrtp)
  reg hi2;  // f03, reset 0 (dfrtp)
  reg lo2;  // f04, reset 0 (dfrtp)
  reg lo1;  // f05, reset 0 (dfrtp)
  reg lo0;  // f06, reset 0 (dfrtp)
  reg lo3;  // f07, reset 0 (dfrtp)
  reg cnt_done;  // f08, reset 0 (dfrtp)

  // -- array (f09-f52): 22 saturating 2-bit "hit bin" counters --
  reg bin00_msb;  // f09, reset 0 (dfrtp)
  reg bin00_lsb;  // f10, reset 0 (dfrtp)
  reg bin01_msb;  // f11, reset 0 (dfrtp)
  reg bin01_lsb;  // f12, reset 0 (dfrtp)
  reg bin02_lsb;  // f13, reset 0 (dfrtp)
  reg bin03_lsb;  // f14, reset 0 (dfrtp)
  reg bin03_msb;  // f15, reset 0 (dfrtp)
  reg bin02_msb;  // f16, reset 0 (dfrtp)
  reg bin04_msb;  // f17, reset 0 (dfrtp)
  reg bin04_lsb;  // f18, reset 0 (dfrtp)
  reg bin05_msb;  // f19, reset 0 (dfrtp)
  reg bin05_lsb;  // f20, reset 0 (dfrtp)
  reg bin06_msb;  // f21, reset 0 (dfrtp)
  reg bin06_lsb;  // f22, reset 0 (dfrtp)
  reg bin07_msb;  // f23, reset 0 (dfrtp)
  reg bin07_lsb;  // f24, reset 0 (dfrtp)
  reg bin08_msb;  // f25, reset 0 (dfrtp)
  reg bin09_msb;  // f26, reset 0 (dfrtp)
  reg bin08_lsb;  // f27, reset 0 (dfrtp)
  reg bin09_lsb;  // f28, reset 0 (dfrtp)
  reg bin10_msb;  // f29, reset 0 (dfrtp)
  reg bin10_lsb;  // f30, reset 0 (dfrtp)
  reg bin11_msb;  // f31, reset 0 (dfrtp)
  reg bin11_lsb;  // f32, reset 0 (dfrtp)
  reg bin12_msb;  // f33, reset 0 (dfrtp)
  reg bin12_lsb;  // f34, reset 0 (dfrtp)
  reg bin13_msb;  // f35, reset 0 (dfrtp)
  reg bin13_lsb;  // f36, reset 0 (dfrtp)
  reg bin14_msb;  // f37, reset 0 (dfrtp)
  reg bin14_lsb;  // f38, reset 0 (dfrtp)
  reg bin15_msb;  // f39, reset 0 (dfrtp)
  reg bin15_lsb;  // f40, reset 0 (dfrtp)
  reg bin16_msb;  // f41, reset 0 (dfrtp)
  reg bin16_lsb;  // f42, reset 0 (dfrtp)
  reg bin17_msb;  // f43, reset 0 (dfrtp)
  reg bin17_lsb;  // f44, reset 0 (dfrtp)
  reg bin18_lsb;  // f45, reset 0 (dfrtp)
  reg bin18_msb;  // f46, reset 0 (dfrtp)
  reg bin19_msb;  // f47, reset 0 (dfrtp)
  reg bin20_msb;  // f48, reset 0 (dfrtp)
  reg bin19_lsb;  // f49, reset 0 (dfrtp)
  reg bin20_lsb;  // f50, reset 0 (dfrtp)
  reg bin21_lsb;  // f51, reset 0 (dfrtp)
  reg bin21_msb;  // f52, reset 0 (dfrtp)

  // -- left_top (f53-f68): I-history shift register + 2 sticky checkers --
  reg match_ok;  // f53, reset 0 (dfrtp)
  reg cmp_state;  // f54, reset 0 (dfrtp)
  reg cmp_hold;  // f55, reset 0 (dfrtp)
  reg shift_tap7;  // f56, reset 0 (dfrtp)
  reg shift_tap8;  // f57, reset 0 (dfrtp)
  reg shift_tap5;  // f58, reset 0 (dfrtp)
  reg shift_tap9;  // f59, reset 0 (dfrtp)
  reg shift_tap4;  // f60, reset 0 (dfrtp)
  reg shift_tap6;  // f61, reset 0 (dfrtp)
  reg shift_tap10;  // f62, reset 0 (dfrtp)
  reg shift_tap3;  // f63, reset 0 (dfrtp)
  reg hist_hit;  // f64, reset 0 (dfrtp)
  reg shift_tap11;  // f65, reset 0 (dfrtp)
  reg shift_tap1;  // f66, reset 0 (dfrtp)
  reg shift_tap0;  // f67, reset 0 (dfrtp)
  reg shift_tap2;  // f68, reset 0 (dfrtp)

  // -- left_bottom (f69-f76): 8-bit up-counter, frozen while cnt_done --
  reg lb_bit4;  // f69, reset 0 (dfrtp)
  reg lb_bit1;  // f70, reset 0 (dfrtp)
  reg lb_bit5;  // f71, reset 0 (dfrtp)
  reg lb_bit2;  // f72, reset 0 (dfrtp)
  reg lb_bit6;  // f73, reset 0 (dfrtp)
  reg lb_bit3;  // f74, reset 0 (dfrtp)
  reg lb_bit0;  // f75, reset 0 (dfrtp)
  reg lb_bit7;  // f76, reset 0 (dfrtp)

  // -- check (f77-f79): one-shot pass/fail latch, drives success --
  reg alt_latch;  // f77, reset 0 (dfrtp)
  reg success_latch;  // f78, reset 0 (dfrtp)
  reg armed;  // f79, reset 0 (dfrtp)

  // -- outgen (f80-f91): scrambler register + message-ROM playback position --
  reg scr_bit6;  // f80, reset 0 (dfrtp)
  reg scr_bit7;  // f81, reset 1 (dfstp)
  reg scr_bit4;  // f82, reset 0 (dfrtp)
  reg scr_bit5;  // f83, reset 1 (dfstp)
  reg scr_bit2;  // f84, reset 1 (dfstp)
  reg scr_bit3;  // f85, reset 0 (dfrtp)
  reg scr_bit1;  // f86, reset 0 (dfrtp)
  reg scr_bit0;  // f87, reset 1 (dfstp)
  reg pos3;  // f88, no reset (dfxtp)
  reg pos2;  // f89, no reset (dfxtp)
  reg pos1;  // f90, no reset (dfxtp)
  reg pos0;  // f91, no reset (dfxtp)

  // -- combinational next-state values (d_fNN outputs of the rec_* blocks) --
  wire next_hi0;
  wire next_hi3;
  wire next_hi1;
  wire next_hi2;
  wire next_lo2;
  wire next_lo1;
  wire next_lo0;
  wire next_lo3;
  wire next_cnt_done;

  wire next_bin00_msb;
  wire next_bin00_lsb;
  wire next_bin01_msb;
  wire next_bin01_lsb;
  wire next_bin02_lsb;
  wire next_bin03_lsb;
  wire next_bin03_msb;
  wire next_bin02_msb;
  wire next_bin04_msb;
  wire next_bin04_lsb;
  wire next_bin05_msb;
  wire next_bin05_lsb;
  wire next_bin06_msb;
  wire next_bin06_lsb;
  wire next_bin07_msb;
  wire next_bin07_lsb;
  wire next_bin08_msb;
  wire next_bin09_msb;
  wire next_bin08_lsb;
  wire next_bin09_lsb;
  wire next_bin10_msb;
  wire next_bin10_lsb;
  wire next_bin11_msb;
  wire next_bin11_lsb;
  wire next_bin12_msb;
  wire next_bin12_lsb;
  wire next_bin13_msb;
  wire next_bin13_lsb;
  wire next_bin14_msb;
  wire next_bin14_lsb;
  wire next_bin15_msb;
  wire next_bin15_lsb;
  wire next_bin16_msb;
  wire next_bin16_lsb;
  wire next_bin17_msb;
  wire next_bin17_lsb;
  wire next_bin18_lsb;
  wire next_bin18_msb;
  wire next_bin19_msb;
  wire next_bin20_msb;
  wire next_bin19_lsb;
  wire next_bin20_lsb;
  wire next_bin21_lsb;
  wire next_bin21_msb;

  wire next_match_ok;
  wire next_cmp_state;
  wire next_cmp_hold;
  wire next_shift_tap7;
  wire next_shift_tap8;
  wire next_shift_tap5;
  wire next_shift_tap9;
  wire next_shift_tap4;
  wire next_shift_tap6;
  wire next_shift_tap10;
  wire next_shift_tap3;
  wire next_hist_hit;
  wire next_shift_tap11;
  wire next_shift_tap1;
  wire next_shift_tap0;
  wire next_shift_tap2;

  wire next_lb_bit4;
  wire next_lb_bit1;
  wire next_lb_bit5;
  wire next_lb_bit2;
  wire next_lb_bit6;
  wire next_lb_bit3;
  wire next_lb_bit0;
  wire next_lb_bit7;

  wire next_alt_latch;
  wire next_success_latch;
  wire next_armed;

  wire next_scr_bit6;
  wire next_scr_bit7;
  wire next_scr_bit4;
  wire next_scr_bit5;
  wire next_scr_bit2;
  wire next_scr_bit3;
  wire next_scr_bit1;
  wire next_scr_bit0;
  wire next_pos3;
  wire next_pos2;
  wire next_pos1;
  wire next_pos0;

  wire success;
  wire [7:0] O;

  // -- six recovered blocks, purely combinational next-state logic --
  rec_counter u_counter (
      .enable(enable),
      .q_f00(hi0),
      .q_f01(hi3),
      .q_f02(hi1),
      .q_f03(hi2),
      .q_f04(lo2),
      .q_f05(lo1),
      .q_f06(lo0),
      .q_f07(lo3),
      .q_f08(cnt_done),
      .d_f00(next_hi0),
      .d_f01(next_hi3),
      .d_f02(next_hi1),
      .d_f03(next_hi2),
      .d_f04(next_lo2),
      .d_f05(next_lo1),
      .d_f06(next_lo0),
      .d_f07(next_lo3),
      .d_f08(next_cnt_done)
  );

  rec_array u_array (
      .I(I),
      .enable(enable),
      .q_f00(hi0),
      .q_f01(hi3),
      .q_f02(hi1),
      .q_f03(hi2),
      .q_f04(lo2),
      .q_f05(lo1),
      .q_f06(lo0),
      .q_f07(lo3),
      .q_f08(cnt_done),
      .q_f09(bin00_msb),
      .q_f10(bin00_lsb),
      .q_f11(bin01_msb),
      .q_f12(bin01_lsb),
      .q_f13(bin02_lsb),
      .q_f14(bin03_lsb),
      .q_f15(bin03_msb),
      .q_f16(bin02_msb),
      .q_f17(bin04_msb),
      .q_f18(bin04_lsb),
      .q_f19(bin05_msb),
      .q_f20(bin05_lsb),
      .q_f21(bin06_msb),
      .q_f22(bin06_lsb),
      .q_f23(bin07_msb),
      .q_f24(bin07_lsb),
      .q_f25(bin08_msb),
      .q_f26(bin09_msb),
      .q_f27(bin08_lsb),
      .q_f28(bin09_lsb),
      .q_f29(bin10_msb),
      .q_f30(bin10_lsb),
      .q_f31(bin11_msb),
      .q_f32(bin11_lsb),
      .q_f33(bin12_msb),
      .q_f34(bin12_lsb),
      .q_f35(bin13_msb),
      .q_f36(bin13_lsb),
      .q_f37(bin14_msb),
      .q_f38(bin14_lsb),
      .q_f39(bin15_msb),
      .q_f40(bin15_lsb),
      .q_f41(bin16_msb),
      .q_f42(bin16_lsb),
      .q_f43(bin17_msb),
      .q_f44(bin17_lsb),
      .q_f45(bin18_lsb),
      .q_f46(bin18_msb),
      .q_f47(bin19_msb),
      .q_f48(bin20_msb),
      .q_f49(bin19_lsb),
      .q_f50(bin20_lsb),
      .q_f51(bin21_lsb),
      .q_f52(bin21_msb),
      .d_f09(next_bin00_msb),
      .d_f10(next_bin00_lsb),
      .d_f11(next_bin01_msb),
      .d_f12(next_bin01_lsb),
      .d_f13(next_bin02_lsb),
      .d_f14(next_bin03_lsb),
      .d_f15(next_bin03_msb),
      .d_f16(next_bin02_msb),
      .d_f17(next_bin04_msb),
      .d_f18(next_bin04_lsb),
      .d_f19(next_bin05_msb),
      .d_f20(next_bin05_lsb),
      .d_f21(next_bin06_msb),
      .d_f22(next_bin06_lsb),
      .d_f23(next_bin07_msb),
      .d_f24(next_bin07_lsb),
      .d_f25(next_bin08_msb),
      .d_f26(next_bin09_msb),
      .d_f27(next_bin08_lsb),
      .d_f28(next_bin09_lsb),
      .d_f29(next_bin10_msb),
      .d_f30(next_bin10_lsb),
      .d_f31(next_bin11_msb),
      .d_f32(next_bin11_lsb),
      .d_f33(next_bin12_msb),
      .d_f34(next_bin12_lsb),
      .d_f35(next_bin13_msb),
      .d_f36(next_bin13_lsb),
      .d_f37(next_bin14_msb),
      .d_f38(next_bin14_lsb),
      .d_f39(next_bin15_msb),
      .d_f40(next_bin15_lsb),
      .d_f41(next_bin16_msb),
      .d_f42(next_bin16_lsb),
      .d_f43(next_bin17_msb),
      .d_f44(next_bin17_lsb),
      .d_f45(next_bin18_lsb),
      .d_f46(next_bin18_msb),
      .d_f47(next_bin19_msb),
      .d_f48(next_bin20_msb),
      .d_f49(next_bin19_lsb),
      .d_f50(next_bin20_lsb),
      .d_f51(next_bin21_lsb),
      .d_f52(next_bin21_msb)
  );

  rec_left_top u_left_top (
      .I(I),
      .enable(enable),
      .q_f04(lo2),
      .q_f05(lo1),
      .q_f06(lo0),
      .q_f07(lo3),
      .q_f08(cnt_done),
      .q_f53(match_ok),
      .q_f54(cmp_state),
      .q_f55(cmp_hold),
      .q_f56(shift_tap7),
      .q_f57(shift_tap8),
      .q_f58(shift_tap5),
      .q_f59(shift_tap9),
      .q_f60(shift_tap4),
      .q_f61(shift_tap6),
      .q_f62(shift_tap10),
      .q_f63(shift_tap3),
      .q_f64(hist_hit),
      .q_f65(shift_tap11),
      .q_f66(shift_tap1),
      .q_f67(shift_tap0),
      .q_f68(shift_tap2),
      .d_f53(next_match_ok),
      .d_f54(next_cmp_state),
      .d_f55(next_cmp_hold),
      .d_f56(next_shift_tap7),
      .d_f57(next_shift_tap8),
      .d_f58(next_shift_tap5),
      .d_f59(next_shift_tap9),
      .d_f60(next_shift_tap4),
      .d_f61(next_shift_tap6),
      .d_f62(next_shift_tap10),
      .d_f63(next_shift_tap3),
      .d_f64(next_hist_hit),
      .d_f65(next_shift_tap11),
      .d_f66(next_shift_tap1),
      .d_f67(next_shift_tap0),
      .d_f68(next_shift_tap2)
  );

  rec_left_bottom u_left_bottom (
      .I(I),
      .enable(enable),
      .q_f08(cnt_done),
      .q_f69(lb_bit4),
      .q_f70(lb_bit1),
      .q_f71(lb_bit5),
      .q_f72(lb_bit2),
      .q_f73(lb_bit6),
      .q_f74(lb_bit3),
      .q_f75(lb_bit0),
      .q_f76(lb_bit7),
      .d_f69(next_lb_bit4),
      .d_f70(next_lb_bit1),
      .d_f71(next_lb_bit5),
      .d_f72(next_lb_bit2),
      .d_f73(next_lb_bit6),
      .d_f74(next_lb_bit3),
      .d_f75(next_lb_bit0),
      .d_f76(next_lb_bit7)
  );

  rec_check u_check (
      .q_f08(cnt_done),
      .q_f09(bin00_msb),
      .q_f10(bin00_lsb),
      .q_f11(bin01_msb),
      .q_f12(bin01_lsb),
      .q_f13(bin02_lsb),
      .q_f14(bin03_lsb),
      .q_f15(bin03_msb),
      .q_f16(bin02_msb),
      .q_f17(bin04_msb),
      .q_f18(bin04_lsb),
      .q_f19(bin05_msb),
      .q_f20(bin05_lsb),
      .q_f21(bin06_msb),
      .q_f22(bin06_lsb),
      .q_f23(bin07_msb),
      .q_f24(bin07_lsb),
      .q_f25(bin08_msb),
      .q_f26(bin09_msb),
      .q_f27(bin08_lsb),
      .q_f28(bin09_lsb),
      .q_f29(bin10_msb),
      .q_f30(bin10_lsb),
      .q_f31(bin11_msb),
      .q_f32(bin11_lsb),
      .q_f33(bin12_msb),
      .q_f34(bin12_lsb),
      .q_f35(bin13_msb),
      .q_f36(bin13_lsb),
      .q_f37(bin14_msb),
      .q_f38(bin14_lsb),
      .q_f39(bin15_msb),
      .q_f40(bin15_lsb),
      .q_f41(bin16_msb),
      .q_f42(bin16_lsb),
      .q_f43(bin17_msb),
      .q_f44(bin17_lsb),
      .q_f45(bin18_lsb),
      .q_f46(bin18_msb),
      .q_f47(bin19_msb),
      .q_f48(bin20_msb),
      .q_f49(bin19_lsb),
      .q_f50(bin20_lsb),
      .q_f51(bin21_lsb),
      .q_f52(bin21_msb),
      .q_f53(match_ok),
      .q_f64(hist_hit),
      .q_f69(lb_bit4),
      .q_f70(lb_bit1),
      .q_f71(lb_bit5),
      .q_f72(lb_bit2),
      .q_f73(lb_bit6),
      .q_f74(lb_bit3),
      .q_f75(lb_bit0),
      .q_f76(lb_bit7),
      .q_f77(alt_latch),
      .q_f78(success_latch),
      .q_f79(armed),
      .d_f77(next_alt_latch),
      .d_f78(next_success_latch),
      .d_f79(next_armed),
      .success(success)
  );

  rec_outgen u_outgen (
      .I(I),
      .enable(enable),
      .q_f08(cnt_done),
      .q_f69(lb_bit4),
      .q_f70(lb_bit1),
      .q_f71(lb_bit5),
      .q_f72(lb_bit2),
      .q_f73(lb_bit6),
      .q_f74(lb_bit3),
      .q_f75(lb_bit0),
      .q_f76(lb_bit7),
      .q_f77(alt_latch),
      .q_f78(success_latch),
      .q_f79(armed),
      .q_f80(scr_bit6),
      .q_f81(scr_bit7),
      .q_f82(scr_bit4),
      .q_f83(scr_bit5),
      .q_f84(scr_bit2),
      .q_f85(scr_bit3),
      .q_f86(scr_bit1),
      .q_f87(scr_bit0),
      .q_f88(pos3),
      .q_f89(pos2),
      .q_f90(pos1),
      .q_f91(pos0),
      .d_f80(next_scr_bit6),
      .d_f81(next_scr_bit7),
      .d_f82(next_scr_bit4),
      .d_f83(next_scr_bit5),
      .d_f84(next_scr_bit2),
      .d_f85(next_scr_bit3),
      .d_f86(next_scr_bit1),
      .d_f87(next_scr_bit0),
      .d_f88(next_pos3),
      .d_f89(next_pos2),
      .d_f90(next_pos1),
      .d_f91(next_pos0),
      .O(O)
  );

  // -- flop updates: async reset/set per rtl_recovered/blocks.json --
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      hi0 <= 1'b0;
      hi3 <= 1'b0;
      hi1 <= 1'b0;
      hi2 <= 1'b0;
      lo2 <= 1'b0;
      lo1 <= 1'b0;
      lo0 <= 1'b0;
      lo3 <= 1'b0;
      cnt_done <= 1'b0;
      bin00_msb <= 1'b0;
      bin00_lsb <= 1'b0;
      bin01_msb <= 1'b0;
      bin01_lsb <= 1'b0;
      bin02_lsb <= 1'b0;
      bin03_lsb <= 1'b0;
      bin03_msb <= 1'b0;
      bin02_msb <= 1'b0;
      bin04_msb <= 1'b0;
      bin04_lsb <= 1'b0;
      bin05_msb <= 1'b0;
      bin05_lsb <= 1'b0;
      bin06_msb <= 1'b0;
      bin06_lsb <= 1'b0;
      bin07_msb <= 1'b0;
      bin07_lsb <= 1'b0;
      bin08_msb <= 1'b0;
      bin09_msb <= 1'b0;
      bin08_lsb <= 1'b0;
      bin09_lsb <= 1'b0;
      bin10_msb <= 1'b0;
      bin10_lsb <= 1'b0;
      bin11_msb <= 1'b0;
      bin11_lsb <= 1'b0;
      bin12_msb <= 1'b0;
      bin12_lsb <= 1'b0;
      bin13_msb <= 1'b0;
      bin13_lsb <= 1'b0;
      bin14_msb <= 1'b0;
      bin14_lsb <= 1'b0;
      bin15_msb <= 1'b0;
      bin15_lsb <= 1'b0;
      bin16_msb <= 1'b0;
      bin16_lsb <= 1'b0;
      bin17_msb <= 1'b0;
      bin17_lsb <= 1'b0;
      bin18_lsb <= 1'b0;
      bin18_msb <= 1'b0;
      bin19_msb <= 1'b0;
      bin20_msb <= 1'b0;
      bin19_lsb <= 1'b0;
      bin20_lsb <= 1'b0;
      bin21_lsb <= 1'b0;
      bin21_msb <= 1'b0;
      match_ok <= 1'b0;
      cmp_state <= 1'b0;
      cmp_hold <= 1'b0;
      shift_tap7 <= 1'b0;
      shift_tap8 <= 1'b0;
      shift_tap5 <= 1'b0;
      shift_tap9 <= 1'b0;
      shift_tap4 <= 1'b0;
      shift_tap6 <= 1'b0;
      shift_tap10 <= 1'b0;
      shift_tap3 <= 1'b0;
      hist_hit <= 1'b0;
      shift_tap11 <= 1'b0;
      shift_tap1 <= 1'b0;
      shift_tap0 <= 1'b0;
      shift_tap2 <= 1'b0;
      lb_bit4 <= 1'b0;
      lb_bit1 <= 1'b0;
      lb_bit5 <= 1'b0;
      lb_bit2 <= 1'b0;
      lb_bit6 <= 1'b0;
      lb_bit3 <= 1'b0;
      lb_bit0 <= 1'b0;
      lb_bit7 <= 1'b0;
      alt_latch <= 1'b0;
      success_latch <= 1'b0;
      armed <= 1'b0;
      scr_bit6 <= 1'b0;
      scr_bit4 <= 1'b0;
      scr_bit3 <= 1'b0;
      scr_bit1 <= 1'b0;
    end else begin
      hi0 <= next_hi0;
      hi3 <= next_hi3;
      hi1 <= next_hi1;
      hi2 <= next_hi2;
      lo2 <= next_lo2;
      lo1 <= next_lo1;
      lo0 <= next_lo0;
      lo3 <= next_lo3;
      cnt_done <= next_cnt_done;
      bin00_msb <= next_bin00_msb;
      bin00_lsb <= next_bin00_lsb;
      bin01_msb <= next_bin01_msb;
      bin01_lsb <= next_bin01_lsb;
      bin02_lsb <= next_bin02_lsb;
      bin03_lsb <= next_bin03_lsb;
      bin03_msb <= next_bin03_msb;
      bin02_msb <= next_bin02_msb;
      bin04_msb <= next_bin04_msb;
      bin04_lsb <= next_bin04_lsb;
      bin05_msb <= next_bin05_msb;
      bin05_lsb <= next_bin05_lsb;
      bin06_msb <= next_bin06_msb;
      bin06_lsb <= next_bin06_lsb;
      bin07_msb <= next_bin07_msb;
      bin07_lsb <= next_bin07_lsb;
      bin08_msb <= next_bin08_msb;
      bin09_msb <= next_bin09_msb;
      bin08_lsb <= next_bin08_lsb;
      bin09_lsb <= next_bin09_lsb;
      bin10_msb <= next_bin10_msb;
      bin10_lsb <= next_bin10_lsb;
      bin11_msb <= next_bin11_msb;
      bin11_lsb <= next_bin11_lsb;
      bin12_msb <= next_bin12_msb;
      bin12_lsb <= next_bin12_lsb;
      bin13_msb <= next_bin13_msb;
      bin13_lsb <= next_bin13_lsb;
      bin14_msb <= next_bin14_msb;
      bin14_lsb <= next_bin14_lsb;
      bin15_msb <= next_bin15_msb;
      bin15_lsb <= next_bin15_lsb;
      bin16_msb <= next_bin16_msb;
      bin16_lsb <= next_bin16_lsb;
      bin17_msb <= next_bin17_msb;
      bin17_lsb <= next_bin17_lsb;
      bin18_lsb <= next_bin18_lsb;
      bin18_msb <= next_bin18_msb;
      bin19_msb <= next_bin19_msb;
      bin20_msb <= next_bin20_msb;
      bin19_lsb <= next_bin19_lsb;
      bin20_lsb <= next_bin20_lsb;
      bin21_lsb <= next_bin21_lsb;
      bin21_msb <= next_bin21_msb;
      match_ok <= next_match_ok;
      cmp_state <= next_cmp_state;
      cmp_hold <= next_cmp_hold;
      shift_tap7 <= next_shift_tap7;
      shift_tap8 <= next_shift_tap8;
      shift_tap5 <= next_shift_tap5;
      shift_tap9 <= next_shift_tap9;
      shift_tap4 <= next_shift_tap4;
      shift_tap6 <= next_shift_tap6;
      shift_tap10 <= next_shift_tap10;
      shift_tap3 <= next_shift_tap3;
      hist_hit <= next_hist_hit;
      shift_tap11 <= next_shift_tap11;
      shift_tap1 <= next_shift_tap1;
      shift_tap0 <= next_shift_tap0;
      shift_tap2 <= next_shift_tap2;
      lb_bit4 <= next_lb_bit4;
      lb_bit1 <= next_lb_bit1;
      lb_bit5 <= next_lb_bit5;
      lb_bit2 <= next_lb_bit2;
      lb_bit6 <= next_lb_bit6;
      lb_bit3 <= next_lb_bit3;
      lb_bit0 <= next_lb_bit0;
      lb_bit7 <= next_lb_bit7;
      alt_latch <= next_alt_latch;
      success_latch <= next_success_latch;
      armed <= next_armed;
      scr_bit6 <= next_scr_bit6;
      scr_bit4 <= next_scr_bit4;
      scr_bit3 <= next_scr_bit3;
      scr_bit1 <= next_scr_bit1;
    end
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      scr_bit7 <= 1'b1;
      scr_bit5 <= 1'b1;
      scr_bit2 <= 1'b1;
      scr_bit0 <= 1'b1;
    end else begin
      scr_bit7 <= next_scr_bit7;
      scr_bit5 <= next_scr_bit5;
      scr_bit2 <= next_scr_bit2;
      scr_bit0 <= next_scr_bit0;
    end
  end

  // no-reset flops (sky130_fd_sc_hd__dfxtp_2): plain D flops, arbitrary power-on state
  always @(posedge clk) begin
    pos3 <= next_pos3;
    pos2 <= next_pos2;
    pos1 <= next_pos1;
    pos0 <= next_pos0;
  end

endmodule
