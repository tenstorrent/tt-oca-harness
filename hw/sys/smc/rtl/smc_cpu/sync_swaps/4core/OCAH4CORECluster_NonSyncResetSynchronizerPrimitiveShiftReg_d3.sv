// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module OCAH4CORECluster_NonSyncResetSynchronizerPrimitiveShiftReg_d3 (
  input  clock,
  io_d,  // @[generators/rocket-chip/src/main/scala/util/ShiftReg.scala:36:14]
  output io_q   // @[generators/rocket-chip/src/main/scala/util/ShiftReg.scala:36:14]
);

  prim_flop_3sync prim_flop_3sync (
    .i_CK(clock),
    .i_D(io_d),
    .o_Q(io_q)
  );

endmodule

