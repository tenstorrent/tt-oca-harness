// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Replace the Chipyard non-sync reset shift-register black box.
//
// Substitutes an OCAH-compatible primitive for the generated non-sync reset box.
// Preserves the three-stage depth the generated cluster expects.

module OCAH4CORECluster_NonSyncResetSynchronizerPrimitiveShiftReg_d3 (
  input  clock,                         // Clock.
  io_d,  // @[generators/rocket-chip/src/main/scala/util/ShiftReg.scala:36:14].
  output io_q                           // @[generators/rocket-chip/src/main/scala/util/ShiftReg.scala:36:14].
);

  prim_flop_3sync u_prim_flop_3sync (
    .clk_i(clock),
    .d_i(io_d),
    .q_o(io_q)
  );

endmodule

