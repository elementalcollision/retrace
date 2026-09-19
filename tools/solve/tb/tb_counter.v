`timescale 1ns/1ps
module tb;
  reg clk = 0, rst_n = 0, enable = 0;
  wire q_f00,q_f01,q_f02,q_f03,q_f04,q_f05,q_f06,q_f07,q_f08;
  reg  r_f00,r_f01,r_f02,r_f03,r_f04,r_f05,r_f06,r_f07,r_f08;
  wire d_f00,d_f01,d_f02,d_f03,d_f04,d_f05,d_f06,d_f07,d_f08;

  assign q_f00=r_f00; assign q_f01=r_f01; assign q_f02=r_f02; assign q_f03=r_f03;
  assign q_f04=r_f04; assign q_f05=r_f05; assign q_f06=r_f06; assign q_f07=r_f07;
  assign q_f08=r_f08;

  rec_counter dut(.enable(enable),
    .q_f00(q_f00),.q_f01(q_f01),.q_f02(q_f02),.q_f03(q_f03),.q_f04(q_f04),
    .q_f05(q_f05),.q_f06(q_f06),.q_f07(q_f07),.q_f08(q_f08),
    .d_f00(d_f00),.d_f01(d_f01),.d_f02(d_f02),.d_f03(d_f03),.d_f04(d_f04),
    .d_f05(d_f05),.d_f06(d_f06),.d_f07(d_f07),.d_f08(d_f08));

  always #5 clk = ~clk;

  integer k;
  // hi = {q_f01,q_f03,q_f02,q_f00}; lo = {q_f07,q_f04,q_f05,q_f06}
  function [3:0] hival; input a,b,c,d; hival = {a,b,c,d}; endfunction

  always @(posedge clk) begin
    if (!rst_n) begin
      r_f00<=0;r_f01<=0;r_f02<=0;r_f03<=0;r_f04<=0;r_f05<=0;r_f06<=0;r_f07<=0;r_f08<=0;
    end else begin
      r_f00<=d_f00;r_f01<=d_f01;r_f02<=d_f02;r_f03<=d_f03;r_f04<=d_f04;
      r_f05<=d_f05;r_f06<=d_f06;r_f07<=d_f07;r_f08<=d_f08;
    end
  end

  initial begin
    $dumpfile("out/solve_a/tb_counter.vcd");
    rst_n = 0; enable = 0;
    @(posedge clk); @(posedge clk);
    rst_n = 1;
    @(negedge clk);
    enable = 1;
    for (k=0; k<130; k=k+1) begin
      // print state BEFORE this enabled edge (i.e. what array/left_top see this cycle)
      $display("K=%0d HI=%0d LO=%0d DONE=%0d", k,
        {q_f01,q_f03,q_f02,q_f00}, {q_f07,q_f04,q_f05,q_f06}, q_f08);
      @(posedge clk);
    end
    $finish;
  end
endmodule
