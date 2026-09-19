`timescale 1ns/1ps
// Drives rec_left_top over a caller-supplied 121-cycle I sequence (read from
// a file, one '0'/'1' char per enabled cycle, in the same row-major cell
// order as the counter: k=0..120 <-> (hi,lo) row-major) together with the
// real rec_counter, and reports the final match_ok (f53) / hist_hit (f64).
module tb;
  reg clk=0, rst_n=0, enable=0;
  reg [0:2047] seqfile;
  integer fd, k, c;
  reg [120:0] iseq;

  // counter state
  reg cq_f00,cq_f01,cq_f02,cq_f03,cq_f04,cq_f05,cq_f06,cq_f07,cq_f08;
  wire cd_f00,cd_f01,cd_f02,cd_f03,cd_f04,cd_f05,cd_f06,cd_f07,cd_f08;
  rec_counter cnt(.enable(enable),
    .q_f00(cq_f00),.q_f01(cq_f01),.q_f02(cq_f02),.q_f03(cq_f03),.q_f04(cq_f04),
    .q_f05(cq_f05),.q_f06(cq_f06),.q_f07(cq_f07),.q_f08(cq_f08),
    .d_f00(cd_f00),.d_f01(cd_f01),.d_f02(cd_f02),.d_f03(cd_f03),.d_f04(cd_f04),
    .d_f05(cd_f05),.d_f06(cd_f06),.d_f07(cd_f07),.d_f08(cd_f08));

  // left_top state
  reg lq_f53,lq_f54,lq_f55,lq_f56,lq_f57,lq_f58,lq_f59,lq_f60,lq_f61,lq_f62,lq_f63,lq_f64,lq_f65,lq_f66,lq_f67,lq_f68;
  wire ld_f53,ld_f54,ld_f55,ld_f56,ld_f57,ld_f58,ld_f59,ld_f60,ld_f61,ld_f62,ld_f63,ld_f64,ld_f65,ld_f66,ld_f67,ld_f68;
  reg I;
  rec_left_top lt(.I(I), .enable(enable),
    .q_f04(cq_f04), .q_f05(cq_f05), .q_f06(cq_f06), .q_f07(cq_f07), .q_f08(cq_f08),
    .q_f53(lq_f53),.q_f54(lq_f54),.q_f55(lq_f55),.q_f56(lq_f56),.q_f57(lq_f57),
    .q_f58(lq_f58),.q_f59(lq_f59),.q_f60(lq_f60),.q_f61(lq_f61),.q_f62(lq_f62),
    .q_f63(lq_f63),.q_f64(lq_f64),.q_f65(lq_f65),.q_f66(lq_f66),.q_f67(lq_f67),.q_f68(lq_f68),
    .d_f53(ld_f53),.d_f54(ld_f54),.d_f55(ld_f55),.d_f56(ld_f56),.d_f57(ld_f57),
    .d_f58(ld_f58),.d_f59(ld_f59),.d_f60(ld_f60),.d_f61(ld_f61),.d_f62(ld_f62),
    .d_f63(ld_f63),.d_f64(ld_f64),.d_f65(ld_f65),.d_f66(ld_f66),.d_f67(ld_f67),.d_f68(ld_f68));

  always #5 clk = ~clk;

  always @(posedge clk) begin
    if (!rst_n) begin
      {cq_f00,cq_f01,cq_f02,cq_f03,cq_f04,cq_f05,cq_f06,cq_f07,cq_f08} <= 0;
      {lq_f53,lq_f54,lq_f55,lq_f56,lq_f57,lq_f58,lq_f59,lq_f60,lq_f61,lq_f62,lq_f63,lq_f64,lq_f65,lq_f66,lq_f67,lq_f68} <= 0;
    end else begin
      {cq_f00,cq_f01,cq_f02,cq_f03,cq_f04,cq_f05,cq_f06,cq_f07,cq_f08} <=
        {cd_f00,cd_f01,cd_f02,cd_f03,cd_f04,cd_f05,cd_f06,cd_f07,cd_f08};
      {lq_f53,lq_f54,lq_f55,lq_f56,lq_f57,lq_f58,lq_f59,lq_f60,lq_f61,lq_f62,lq_f63,lq_f64,lq_f65,lq_f66,lq_f67,lq_f68} <=
        {ld_f53,ld_f54,ld_f55,ld_f56,ld_f57,ld_f58,ld_f59,ld_f60,ld_f61,ld_f62,ld_f63,ld_f64,ld_f65,ld_f66,ld_f67,ld_f68};
    end
  end

  initial begin
    if (!$value$plusargs("seq=%s", seqfile)) begin
      $display("ERROR: need +seq=<121-char 0/1 file>");
      $finish;
    end
    fd = $fopen(seqfile, "r");
    for (k = 0; k < 121; k = k + 1) begin
      c = $fgetc(fd);
      iseq[120-k] = (c == "1") ? 1'b1 : 1'b0;
    end
    $fclose(fd);

    rst_n = 0; enable = 0; I = 0;
    @(posedge clk); @(posedge clk);
    rst_n = 1;
    @(negedge clk);
    enable = 1;
    for (k = 0; k < 121; k = k + 1) begin
      I = iseq[120-k];
      @(posedge clk);
    end
    #1;
    $display("RESULT match_ok=%b hist_hit=%b cnt_done=%b", lq_f53, lq_f64, cq_f08);
    $finish;
  end
endmodule
