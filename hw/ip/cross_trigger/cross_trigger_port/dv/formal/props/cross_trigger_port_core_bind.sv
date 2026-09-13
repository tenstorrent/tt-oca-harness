// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Attaches cross_trigger_port_core_props to every cross_trigger_port_core instance. Internal
// signals reach the property module through this port list only; the RTL carries no properties.

bind cross_trigger_port_core cross_trigger_port_core_props u_cross_trigger_port_core_props (
  .clk_i,
  .rst_ni,
  .mode_wire_or_i,
  .invert_i,
  .handshake_reset_i,
  .stretch_mult_i,
  .ct_src_i,
  .ct_dst_o,
  .busy_o,
  .ct_req_out_dout_en_o,
  .ct_req_out_din_en_o,
  .ct_req_out_dout_o,
  .ct_req_out_din_i,
  .ct_req_in_din_en_o,
  .ct_req_in_din_i,
  .ct_ack_in_din_en_o,
  .ct_ack_in_din_i,
  .ct_ack_out_dout_en_o,
  .ct_ack_out_dout_o,
  .status_busy_o,
  .status_req_out_o,
  .status_ack_in_o,
  .status_req_in_o,
  .status_ack_out_o,
  .req_out_sync_lvl_i  (ct_req_out_din_sync_inv),
  .req_in_sync_lvl_i   (ct_req_in_din_sync_inv),
  .ack_in_sync_lvl_i   (ct_ack_in_din_sync_inv),
  .wire_or_prev_i      (wire_or_req_out_prev),
  .hs_sender_state_i   (u_handshake_ctrl.sender_state_q),
  .hs_receiver_state_i (u_handshake_ctrl.receiver_state_q),
  .hs_req_out_i        (u_handshake_ctrl.ct_req_out_q),
  .hs_ack_out_i        (u_handshake_ctrl.ct_ack_out_q),
  .stretch_active_i    (u_pulse_stretcher.active_q),
  .stretch_counter_i   (u_pulse_stretcher.counter_q)
);
