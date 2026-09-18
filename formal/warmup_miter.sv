// V3c miter: extracted warm-up netlist (gate) vs upstream 01_netlist.v (gold).
// Both start from an asserted reset; after that S must agree forever.
module warmup_miter (input clk, input rst_n, input en, input A, input B);
  wire s_gold, s_gate;
  gold u_gold (.clk(clk), .rst_n(rst_n), .en(en), .A(A), .B(B), .S(s_gold));
  gate u_gate (.clk(clk), .rst_n(rst_n), .en(en), .A(A), .B(B), .S(s_gate));
  reg init = 1'b1;
  always @(posedge clk) init <= 1'b0;
  always @(*) begin
    if (init) assume (!rst_n);
    assert (s_gold == s_gate);
  end
endmodule
