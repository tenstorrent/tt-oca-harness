// SPDX-License-Identifier: Apache-2.0
//
// Compatibility stub for prim_sync3 during public Verilator builds.
//
// Three-stage flop with explicit initial zeros so the synchronizer resolves
// without an external reset (the wrapper port does not expose ``rst_ni``).
// SMC peripherals CDC uses SYNC_STAGES=3 (prim_sync3) for i2c_enable into
// the LSIO mux; an unresolved X/0 on that path forces i2c_scl_i/sda_i to 0
// and deadlocks the OpenTitan I2C host (HOSTIDLE never asserts).

module prim_sync3 #(
  parameter int unsigned WIDTH = 1
) (
  input  logic             clk_i,
  input  logic [WIDTH-1:0] d_i,
  output logic [WIDTH-1:0] q_o
);

  logic [WIDTH-1:0] q0;
  logic [WIDTH-1:0] q1;
  logic [WIDTH-1:0] q2;

  initial begin
    q0 = '0;
    q1 = '0;
    q2 = '0;
  end

  always @(posedge clk_i) begin
    q0 <= d_i;
    q1 <= q0;
    q2 <= q1;
  end

  assign q_o = q2;

endmodule
