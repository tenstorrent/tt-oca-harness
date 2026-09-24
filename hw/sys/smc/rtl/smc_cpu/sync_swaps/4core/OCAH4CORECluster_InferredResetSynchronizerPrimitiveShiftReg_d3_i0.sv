// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module OCAH4CORECluster_InferredResetSynchronizerPrimitiveShiftReg_d3_i0 (
  input  clock,
  input  reset,
  input  io_d,
  output io_q
);

  wire io_rstbypass, io_rst_synced;

  prim_flop_3sync_r u_prim_flop_3sync_r (
    .clk_i(clock),
    .rst_ni(~reset),
    .d_i(io_d),
    .q_o(io_rst_synced)
  );

  assign io_rstbypass = io_rst_synced & ~reset;

  prim_rst_mux2_hf_n u_rstbypass (
    .rst0_ni(io_rstbypass),
    .rst1_ni(1'b0),
    .sel_i  (1'b0),
    .rst_no (io_q)
  );

endmodule

