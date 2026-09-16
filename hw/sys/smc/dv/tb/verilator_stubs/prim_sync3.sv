// SPDX-License-Identifier: Apache-2.0
//
// Compatibility stub for prim_sync3 during public Verilator builds.
//
// Mirrors tb/verilator_stubs/prim_sync2.sv: three-stage flop with explicit
// initial zeros so the synchronizer resolves without an external reset.
// SMC peripherals CDC uses SYNC_STAGES=3 (prim_sync3) for i2c_enable into
// the LSIO mux; an unresolved X/0 on that path forces i2c_scl_i/sda_i to 0
// and deadlocks the OpenTitan I2C host (HOSTIDLE never asserts).

module prim_sync3 #(
  parameter int unsigned WIDTH                  = 1,
  parameter bit          RANDOM_DELAY_GRAY_CODE = 1'b0
) (
  input  logic             i_clk,
  input  logic [WIDTH-1:0] i_d,
  output logic [WIDTH-1:0] o_q
);

  logic [WIDTH-1:0] q0;
  logic [WIDTH-1:0] q1;
  logic [WIDTH-1:0] q2;

  initial begin
    q0 = '0;
    q1 = '0;
    q2 = '0;
  end

  always @(posedge i_clk) begin
    q0 <= i_d;
    q1 <= q0;
    q2 <= q1;
  end

  assign o_q = q2;

endmodule
