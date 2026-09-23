// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module OCAH4CORECluster_NonSyncResetSynchronizerPrimitiveShiftReg_d3 (
  input  clock,
  io_d,  // @[generators/rocket-chip/src/main/scala/util/ShiftReg.scala:36:14]
  output io_q   // @[generators/rocket-chip/src/main/scala/util/ShiftReg.scala:36:14]
);

  prim_flop_3sync u_prim_flop_3sync (
    .clk_i(clock),
    .d_i(io_d),
    .q_o(io_q)
  );

endmodule

