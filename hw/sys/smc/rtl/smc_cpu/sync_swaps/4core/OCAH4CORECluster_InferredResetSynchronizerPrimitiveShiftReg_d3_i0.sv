// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Replace the Chipyard inferred-reset shift-register black box.
//
// Substitutes an OCAH synchronizer for the generated inferred reset primitive.
// Three stages synchronize the reset into the local clock domain.

module OCAH4CORECluster_InferredResetSynchronizerPrimitiveShiftReg_d3_i0 (
  input  clock,                         // Clock.
  input  reset,                         // Reset.
  input  io_d,                          // Io d.
  output io_q                           // Io q.
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

  prim_rst_mux2_hf_n u_rstbypass (
    .rst0_ni(io_rstbypass),
    .rst1_ni(1'b0),
    .sel_i  (1'b0),
    .rst_no (io_q)
  );

endmodule

