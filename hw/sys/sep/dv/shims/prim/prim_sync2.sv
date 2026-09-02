// SPDX-License-Identifier: Apache-2.0
//
// Compatibility OVERRIDE stub for prim_sync2 during public Verilator builds.
//
// The real prim_sync2 instantiates prim_flop_2sync with non-public ports
// (.i_CK/.i_D/.o_Q); the public primitive library exposes prim_flop_2sync with
// lowRISC-style ports (.clk_i/.rst_ni/.d_i/.q_o). This wrapper re-maps to the
// public ports so SEP DUT elaboration stays independent of non-public naming.
// Listed in [build].stubs ahead of the bender filelist so -Wno-MODDUP
// "first definition wins" selects this over the real prim_sync2.
//
// NOT a duplicate of hw/sys/{smc,dtp}/dv/tb/verilator_stubs/prim_sync2.sv, and it
// must NOT be "consolidated" onto them. Those replace the synchronizer with their
// own behavioral two-flop model; this one is a pure PORT REMAP that keeps the real
// prim_flop_2sync in the design, so SEP still exercises the actual synchronizer
// rather than a stand-in. Same module name, deliberately different strategy --
// collapsing them would silently lower SEP's CDC fidelity.

`timescale 1ps / 1fs

module prim_sync2 #(
  parameter int unsigned WIDTH                  = 1,
  parameter bit          RANDOM_DELAY_GRAY_CODE = 1'b0
) (
  input  logic             i_clk,
  input  logic [WIDTH-1:0] i_d,
  output logic [WIDTH-1:0] o_q
);

  prim_flop_2sync #(
    .Width(WIDTH)
  ) u_sync2 (
    .clk_i (i_clk),
    .rst_ni(1'b1),
    .d_i   (i_d),
    .q_o   (o_q)
  );

endmodule
