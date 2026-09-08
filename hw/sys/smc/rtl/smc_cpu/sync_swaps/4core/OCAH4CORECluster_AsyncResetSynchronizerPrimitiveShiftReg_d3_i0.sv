// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module OCAH4CORECluster_AsyncResetSynchronizerPrimitiveShiftReg_d3_i0 (
  input  clock,
  reset,
  io_d,  // @[generators/rocket-chip/src/main/scala/util/ShiftReg.scala:36:14]
  output io_q   // @[generators/rocket-chip/src/main/scala/util/ShiftReg.scala:36:14]
);

  wire io_rstbypass, io_rst_synced;

  prim_flop_3sync_r prim_flop_3sync_r (
    .i_CK(clock),
    .i_RN(~reset),
    .i_D(io_d),
    .o_Q(io_rst_synced)
  );

  assign io_rstbypass = io_rst_synced & ~reset;

  prim_rstbypass_stdmux2 rstbypass (
    .i_reset_n(io_rstbypass),
    .i_test_reset_n(1'b0),
    .i_test_mode(1'b0),
    .o_reset_n(io_q)
  );

endmodule

