// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Detect rising edges on an already-synchronized CTP request.
//
// Uses prim_edge_detector with EnSync disabled because signal_i is pre-synchronized; the
// primitive registers the previous level and derives the edge pulse combinationally from
// signal_i.

module ctp_edge_detector (
  input  logic clk_i,                   // System clock.
  input  logic rst_ni,                  // Active-low asynchronous reset; clears the stored previous
                                        // level.

  input  logic signal_i,                // Level to edge-detect, already synchronized to clk_i and
                                        // polarity-corrected (the CT_Req_in pad input in the port
                                        // core).

  output logic posedge_pulse_o          // One-cycle pulse on each rising edge of signal_i,
                                        // combinational from signal_i; not consumed in
                                        // cross_trigger_port_core.
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
