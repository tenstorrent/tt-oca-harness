// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// External boot-sequence-done qualifier
//
// Synchronizes an asynchronous integrator input onto clk_i, then latches it
// set-once until cold reset.
//-----------------------------------------------------------------------------

module ext_boot_seq_done_qual (
  input  logic clk_i,
  input  logic rst_ni,
  input  logic ext_boot_seq_done_i,
  output logic ext_boot_seq_done_qual_o
);

  logic ext_boot_seq_done_sync;
  logic ext_boot_seq_done_sticky;

  prim_flop_3sync u_ext_boot_seq_done_sync (
    .clk_i(clk_i),
    .d_i  (ext_boot_seq_done_i),
    .q_o  (ext_boot_seq_done_sync)
  );

  prim_flop #(
    .Width(1),
    .ResetValue(1'b0)
  ) u_ext_boot_seq_done_sticky (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .d_i  (ext_boot_seq_done_sync | ext_boot_seq_done_sticky),
    .q_o  (ext_boot_seq_done_sticky)
  );

  assign ext_boot_seq_done_qual_o = ext_boot_seq_done_sticky;

endmodule
