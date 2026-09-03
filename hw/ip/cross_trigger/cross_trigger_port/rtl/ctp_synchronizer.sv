// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Cross Trigger Port Synchronizer Module
//
// Description:
// Synchronizes asynchronous GPIO input signals to the CTP core clock domain.
// All outputs are registered to prevent glitches.
//------------------------------------------------------------------------------


module ctp_synchronizer (
  input  logic clk_i,
  input  logic rst_ni,

  // Asynchronous inputs from GPIO pads
  input  logic ct_req_out_din_i,  // Input from CT_Req_out pad (wire-OR mode)
  input  logic ct_req_in_din_i,  // Input from CT_Req_in pad (point-to-point mode)
  input  logic ct_ack_in_din_i,  // Input from CT_Ack_in pad (point-to-point mode)

  // Synchronized outputs
  output logic ct_req_out_din_sync_o,  // Synchronized CT_Req_out input
  output logic ct_req_in_din_sync_o,  // Synchronized CT_Req_in input
  output logic ct_ack_in_din_sync_o   // Synchronized CT_Ack_in input
);

  // Synchronize ct_req_out_din (used in wire-OR mode)
  prim_flop_2sync #(
    .Width(1),
    .ResetValue(1'b0)
  ) u_sync_req_out (
    .clk_i,
    .rst_ni,
    .d_i(ct_req_out_din_i),
    .q_o(ct_req_out_din_sync_o)
  );

  // Synchronize ct_req_in_din (used in point-to-point mode)
  prim_flop_2sync #(
    .Width(1),
    .ResetValue(1'b0)
  ) u_sync_req_in (
    .clk_i,
    .rst_ni,
    .d_i(ct_req_in_din_i),
    .q_o(ct_req_in_din_sync_o)
  );

  // Synchronize ct_ack_in_din (used in point-to-point mode)
  prim_flop_2sync #(
    .Width(1),
    .ResetValue(1'b0)
  ) u_sync_ack_in (
    .clk_i,
    .rst_ni,
    .d_i(ct_ack_in_din_i),
    .q_o(ct_ack_in_din_sync_o)
  );

endmodule : ctp_synchronizer
