// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module OCAH4CORECluster_InferredResetSynchronizerPrimitiveShiftReg_d3_i0 (
  input  clock,
  input  reset,
  input  io_d,
  output io_q
);

  wire io_rstbypass, io_rst_synced;

  prim_flop_3sync_r prim_flop_3sync_r (
    .clk_i(clock),
    .rst_ni(~reset),
    .d_i(io_d),
    .q_o(io_rst_synced)
  );

  assign io_rstbypass = io_rst_synced & ~reset;

  prim_rstbypass_stdmux2 rstbypass (
    .i_reset_n(io_rstbypass),
    .i_test_reset_n(1'b0),
    .i_test_mode(1'b0),
    .o_reset_n(io_q)
  );

endmodule

