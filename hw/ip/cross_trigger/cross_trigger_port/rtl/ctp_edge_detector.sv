// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Cross Trigger Port Edge Detector Module
//
// Description:
// Detects positive edges on the synchronized cross trigger request input signal
// for point-to-point mode. Outputs a registered pulse on positive edge detection.
//------------------------------------------------------------------------------


module ctp_edge_detector (
  input  logic clk_i,
  input  logic rst_ni,

  // Synchronized input signal
  input  logic signal_i,

  // Positive edge pulse output (registered)
  output logic posedge_pulse_o
);

  // Use prim_edge_detector with synchronization disabled since input is already synchronized
  prim_edge_detector #(
    .Width(1),
    .ResetValue(1'b0),
    .EnSync(1'b0)  // Input is already synchronized
  ) u_edge_detector (
    .clk_i,
    .rst_ni,
    .d_i(signal_i),
    .q_sync_o(),  // Not used
    .q_posedge_pulse_o(posedge_pulse_o),
    .q_negedge_pulse_o()  // Not used
  );

endmodule : ctp_edge_detector
