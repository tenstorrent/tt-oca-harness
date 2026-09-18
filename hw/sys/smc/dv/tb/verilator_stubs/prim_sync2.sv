// SPDX-License-Identifier: Apache-2.0
//
// Compatibility stub for prim_sync2 during public Verilator / Xcelium builds.
//
// The public primitive library exposes prim_flop_2sync with lowRISC-style
// ports, so this wrapper keeps SMC DUT elaboration independent of any
// non-public primitive port naming.
//
// Behavioral model: two-stage flop with explicit initial values so the
// synchronizer resolves cleanly without an external reset (the wrapper port
// does not expose ``rst_ni``). Without this, simulation starts with X on the
// first stage and the X persists indefinitely, breaking sanity tests that
// only check ``is_resolvable`` on downstream outputs.

module prim_sync2 #(
  parameter int unsigned WIDTH                  = 1,
  parameter bit          RANDOM_DELAY_GRAY_CODE = 1'b0
) (
  input  logic             clk_i,
  input  logic [WIDTH-1:0] d_i,
  output logic [WIDTH-1:0] q_o
);

  logic [WIDTH-1:0] q0;
  logic [WIDTH-1:0] q1;

  initial begin
    q0 = '0;
    q1 = '0;
  end

  always @(posedge clk_i) begin
    q0 <= d_i;
    q1 <= q0;
  end

  assign q_o = q1;

endmodule
