// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Detect rising edges on an already-synchronized CTP request and emit a registered pulse.
//
// Uses prim_edge_detector with EnSync disabled because signal_i is pre-synchronized.
// posedge_pulse_o is the registered positive-edge pulse for point-to-point mode.

module ctp_edge_detector (
  input  logic clk_i,                   // System clock.
  input  logic rst_ni,                  // Active-low reset.

  input  logic signal_i,                // Signal.

  output logic posedge_pulse_o          // Posedge pulse.
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
