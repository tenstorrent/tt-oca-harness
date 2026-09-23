// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module OCAH4CORECluster_AsyncResetSynchronizerPrimitiveShiftReg_d3_i0 (
  input  clock,
  reset,
  io_d,  // @[generators/rocket-chip/src/main/scala/util/ShiftReg.scala:36:14]
  output io_q   // @[generators/rocket-chip/src/main/scala/util/ShiftReg.scala:36:14]
);

  wire io_rstbypass, io_rst_synced, reset_n;

  prim_inv u_reset_inv (
    .in_i  (reset),
    .out_o (reset_n)
  );

  prim_flop_3sync_r u_prim_flop_3sync_r (
    .clk_i(clock),
    .rst_ni(reset_n),
    .d_i(io_d),
    .q_o(io_rst_synced)
  );

  prim_and2 #(
    .Width(1)
  ) u_rstbypass_and (
    .in0_i (io_rst_synced),
    .in1_i (reset_n),
    .out_o (io_rstbypass)
  );

  prim_rstbypass_stdmux2 u_rstbypass (
    .rst_ni(io_rstbypass),
    .test_rst_ni(1'b0),
    .test_mode_i(1'b0),
    .rst_no(io_q)
  );

endmodule

