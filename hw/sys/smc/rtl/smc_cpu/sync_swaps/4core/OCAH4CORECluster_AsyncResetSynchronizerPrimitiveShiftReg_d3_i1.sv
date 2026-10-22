// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Replace the Chipyard async-set shift-register black box.
//
// Substitutes an OCAH synchronizer for the generated async reset primitive.
// Three flops synchronize io_d into the local clock domain; reset sets them asynchronously
// and also forces io_q high combinationally.

module OCAH4CORECluster_AsyncResetSynchronizerPrimitiveShiftReg_d3_i1 (
  input  clock,                         // Destination clock for the three synchronizer flops.
  reset,                                // Active-high reset; asynchronously sets the synchronizer
                                        // flops and forces io_q high.
  io_d,  // Data bit to synchronize into the clock domain.
  output io_q                           // Synchronized data bit, held high while reset is high.
);

  wire io_setbypass, io_set_synced, reset_n;

  prim_inv u_reset_inv (
    .in_i  (reset),
    .out_o (reset_n)
  );

  prim_flop_3sync_s u_prim_flop_3sync_s (
    .clk_i(clock),
    .set_ni(reset_n),
    .d_i(io_d),
    .q_o(io_set_synced)
  );

  prim_or2 u_setbypass_or (
    .in0_i (io_set_synced),
    .in1_i (reset),
    .out_o (io_setbypass)
  );

  prim_rst_mux2_hf_n u_setbypass (
    .rst0_ni(io_setbypass),
    .rst1_ni(1'b0),
    .sel_i  (1'b0),
    .rst_no (io_q)
  );

endmodule
