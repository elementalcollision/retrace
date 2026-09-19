`timescale 1ns/1ps
module tb;
  reg I=1, enable=1;
  reg q_f00,q_f01,q_f02,q_f03,q_f04,q_f05,q_f06,q_f07,q_f08;
  reg q_f09,q_f10,q_f11,q_f12,q_f13,q_f14,q_f15,q_f16,q_f17,q_f18,q_f19,q_f20;
  reg q_f21,q_f22,q_f23,q_f24,q_f25,q_f26,q_f27,q_f28,q_f29,q_f30;
  reg q_f31,q_f32,q_f33,q_f34,q_f35,q_f36,q_f37,q_f38,q_f39,q_f40;
  reg q_f41,q_f42,q_f43,q_f44,q_f45,q_f46,q_f47,q_f48,q_f49,q_f50,q_f51,q_f52;
  wire d_f09,d_f10,d_f11,d_f12,d_f13,d_f14,d_f15,d_f16,d_f17,d_f18,d_f19,d_f20;
  wire d_f21,d_f22,d_f23,d_f24,d_f25,d_f26,d_f27,d_f28,d_f29,d_f30;
  wire d_f31,d_f32,d_f33,d_f34,d_f35,d_f36,d_f37,d_f38,d_f39,d_f40;
  wire d_f41,d_f42,d_f43,d_f44,d_f45,d_f46,d_f47,d_f48,d_f49,d_f50,d_f51,d_f52;

  rec_array dut(.I(I),.enable(enable),
    .q_f00(q_f00),.q_f01(q_f01),.q_f02(q_f02),.q_f03(q_f03),.q_f04(q_f04),
    .q_f05(q_f05),.q_f06(q_f06),.q_f07(q_f07),.q_f08(q_f08),
    .q_f09(q_f09),.q_f10(q_f10),.q_f11(q_f11),.q_f12(q_f12),.q_f13(q_f13),
    .q_f14(q_f14),.q_f15(q_f15),.q_f16(q_f16),.q_f17(q_f17),.q_f18(q_f18),
    .q_f19(q_f19),.q_f20(q_f20),.q_f21(q_f21),.q_f22(q_f22),.q_f23(q_f23),
    .q_f24(q_f24),.q_f25(q_f25),.q_f26(q_f26),.q_f27(q_f27),.q_f28(q_f28),
    .q_f29(q_f29),.q_f30(q_f30),.q_f31(q_f31),.q_f32(q_f32),.q_f33(q_f33),
    .q_f34(q_f34),.q_f35(q_f35),.q_f36(q_f36),.q_f37(q_f37),.q_f38(q_f38),
    .q_f39(q_f39),.q_f40(q_f40),.q_f41(q_f41),.q_f42(q_f42),.q_f43(q_f43),
    .q_f44(q_f44),.q_f45(q_f45),.q_f46(q_f46),.q_f47(q_f47),.q_f48(q_f48),
    .q_f49(q_f49),.q_f50(q_f50),.q_f51(q_f51),.q_f52(q_f52),
    .d_f09(d_f09),.d_f10(d_f10),.d_f11(d_f11),.d_f12(d_f12),.d_f13(d_f13),
    .d_f14(d_f14),.d_f15(d_f15),.d_f16(d_f16),.d_f17(d_f17),.d_f18(d_f18),
    .d_f19(d_f19),.d_f20(d_f20),.d_f21(d_f21),.d_f22(d_f22),.d_f23(d_f23),
    .d_f24(d_f24),.d_f25(d_f25),.d_f26(d_f26),.d_f27(d_f27),.d_f28(d_f28),
    .d_f29(d_f29),.d_f30(d_f30),.d_f31(d_f31),.d_f32(d_f32),.d_f33(d_f33),
    .d_f34(d_f34),.d_f35(d_f35),.d_f36(d_f36),.d_f37(d_f37),.d_f38(d_f38),
    .d_f39(d_f39),.d_f40(d_f40),.d_f41(d_f41),.d_f42(d_f42),.d_f43(d_f43),
    .d_f44(d_f44),.d_f45(d_f45),.d_f46(d_f46),.d_f47(d_f47),.d_f48(d_f48),
    .d_f49(d_f49),.d_f50(d_f50),.d_f51(d_f51),.d_f52(d_f52));

  integer hi, lo;
  initial begin
    I=1; enable=1;
    q_f09=0;q_f10=0;q_f11=0;q_f12=0;q_f13=0;q_f14=0;q_f15=0;q_f16=0;q_f17=0;q_f18=0;
    q_f19=0;q_f20=0;q_f21=0;q_f22=0;q_f23=0;q_f24=0;q_f25=0;q_f26=0;q_f27=0;q_f28=0;
    q_f29=0;q_f30=0;q_f31=0;q_f32=0;q_f33=0;q_f34=0;q_f35=0;q_f36=0;q_f37=0;q_f38=0;
    q_f39=0;q_f40=0;q_f41=0;q_f42=0;q_f43=0;q_f44=0;q_f45=0;q_f46=0;q_f47=0;q_f48=0;
    q_f49=0;q_f50=0;q_f51=0;q_f52=0;
    q_f08 = 0;
    for (hi = 0; hi <= 10; hi = hi + 1) begin
      for (lo = 0; lo <= 10; lo = lo + 1) begin
        // hi = {q_f01,q_f03,q_f02,q_f00}; lo = {q_f07,q_f04,q_f05,q_f06}
        {q_f01,q_f03,q_f02,q_f00} = hi[3:0];
        {q_f07,q_f04,q_f05,q_f06} = lo[3:0];
        #1;
        $display("HI=%0d LO=%0d BINS=%b%b_%b%b_%b%b_%b%b_%b%b_%b%b_%b%b_%b%b_%b%b_%b%b_%b%b_%b%b_%b%b_%b%b_%b%b_%b%b_%b%b_%b%b_%b%b_%b%b",
          hi, lo,
          d_f09,d_f10, d_f11,d_f12, d_f16,d_f13, d_f15,d_f14, d_f17,d_f18, d_f19,d_f20,
          d_f21,d_f22, d_f23,d_f24, d_f25,d_f27, d_f26,d_f28, d_f29,d_f30,
          d_f31,d_f32, d_f33,d_f34, d_f35,d_f36, d_f37,d_f38, d_f39,d_f40, d_f41,d_f42,
          d_f43,d_f44, d_f46,d_f45, d_f47,d_f49, d_f48,d_f50, d_f52,d_f51);
      end
    end
    $finish;
  end
endmodule
