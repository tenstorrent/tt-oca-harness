// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Replace the Chipyard non-sync reset shift-register black box.
//
// Substitutes prim_flop_3sync, a three-flop synchronizer without reset, for the generated box.
// Preserves the three-stage depth the generated cluster expects.

module OCAH4CORECluster_NonSyncResetSynchronizerPrimitiveShiftReg_d3 (
  input  clock,                         // Destination clock for the three synchronizer flops.
  io_d,  // Data bit to synchronize into the clock domain.
  output io_q                           // Data bit after three clock-domain flops; not reset.
);

  prim_flop_3sync u_prim_flop_3sync (
    .clk_i(clock),
    .d_i(io_d),
    .q_o(io_q)
  );

endmodule

