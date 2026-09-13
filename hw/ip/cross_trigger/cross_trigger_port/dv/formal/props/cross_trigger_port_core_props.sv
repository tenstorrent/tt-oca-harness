// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Formal properties for cross_trigger_port_core, attached by cross_trigger_port_core_bind.sv.
// Every property body is a boolean expression over current and one-cycle-past values, the subset
// that the open-source frontend and the licensed backends both elaborate
// (hw/common/dv/docs/formal-property-style.adoc).

`include "ocah_fv_macros.svh"

module cross_trigger_port_core_props (
  input logic        clk_i,
  input logic        rst_ni,
  // Configuration inputs of the core
  input logic        mode_wire_or_i,
  input logic        invert_i,
  input logic        handshake_reset_i,
  input logic [15:0] stretch_mult_i,
  // Core-side and pad-side ports of the core, named as on the core
  input logic        ct_src_i,
  input logic        ct_dst_o,
  input logic        busy_o,
  input logic        ct_req_out_dout_en_o,
  input logic        ct_req_out_din_en_o,
  input logic        ct_req_out_dout_o,
  input logic        ct_req_out_din_i,
  input logic        ct_req_in_din_en_o,
  input logic        ct_req_in_din_i,
  input logic        ct_ack_in_din_en_o,
  input logic        ct_ack_in_din_i,
  input logic        ct_ack_out_dout_en_o,
  input logic        ct_ack_out_dout_o,
  input logic        status_busy_o,
  input logic        status_req_out_o,
  input logic        status_ack_in_o,
  input logic        status_req_in_o,
  input logic        status_ack_out_o,
  // Internal state, connected in the bind file
  input logic        req_out_sync_lvl_i,   // ct_req_out_din_sync_inv
  input logic        req_in_sync_lvl_i,    // ct_req_in_din_sync_inv
  input logic        ack_in_sync_lvl_i,    // ct_ack_in_din_sync_inv
  input logic        wire_or_prev_i,       // wire_or_req_out_prev
  input logic [1:0]  hs_sender_state_i,    // u_handshake_ctrl.sender_state_q
  input logic [1:0]  hs_receiver_state_i,  // u_handshake_ctrl.receiver_state_q
  input logic        hs_req_out_i,         // u_handshake_ctrl.ct_req_out_q
  input logic        hs_ack_out_i,         // u_handshake_ctrl.ct_ack_out_q
  input logic        stretch_active_i,     // u_pulse_stretcher.active_q
  input logic [15:0] stretch_counter_i     // u_pulse_stretcher.counter_q
);

  // Encodings of the module-local sender_state_e and receiver_state_e enums in ctp_handshake_ctrl.
  localparam logic [1:0] SENDER_IDLE                = 2'd0;
  localparam logic [1:0] SENDER_REQ_ASSERTED        = 2'd1;
  localparam logic [1:0] SENDER_WAIT_ACK_DEASSERT   = 2'd2;
  localparam logic [1:0] RECEIVER_IDLE              = 2'd0;
  localparam logic [1:0] RECEIVER_ACK_ASSERTED      = 2'd1;
  localparam logic [1:0] RECEIVER_WAIT_REQ_DEASSERT = 2'd2;

  logic p2p;
  assign p2p = !mode_wire_or_i;

  // Pad levels with the CONFIG.INVERT sense removed.
  logic req_in_lvl, ack_in_lvl, req_out_lvl, ack_out_lvl;
  assign req_in_lvl  = ct_req_in_din_i ^ invert_i;
  assign ack_in_lvl  = ct_ack_in_din_i ^ invert_i;
  assign req_out_lvl = ct_req_out_dout_o ^ invert_i;
  assign ack_out_lvl = ct_ack_out_dout_o ^ invert_i;

  // verilog_format: off
  // ---- Assumptions --------------------------------------------------------------------------
  `OCAH_FV_INITIAL_RESET(clk_i, rst_ni)

  // CONFIG and STRETCH_MULT are programmed before a trigger is issued; a change during a transfer
  // is outside the checked behaviour.
  `OCAH_FV_ASSUME(asm_cfg_static,
                  `OCAH_FV_STABLE(mode_wire_or_i) && `OCAH_FV_STABLE(invert_i) &&
                  `OCAH_FV_STABLE(stretch_mult_i),
                  clk_i, rst_ni)

  // CONFIG.INVERT resets to 0, and the pad synchronizers reset to 0 as well: with inversion on,
  // the core reads an active request for the two cycles after reset, so the checked configuration
  // is the non-inverted one.
  `OCAH_FV_ASSUME(asm_invert_off, !invert_i, clk_i, rst_ni)

  // Four-phase partner on the pads in point-to-point mode: the remote sender holds its request
  // until it sees the acknowledge and raises the next one only after the acknowledge has dropped;
  // the remote receiver acknowledges only while the request is high and releases only after the
  // request has dropped.
  `OCAH_FV_ASSUME(asm_p2p_req_in_holds_until_ack,
                  `OCAH_FV_IMPLIES(p2p && `OCAH_FV_FELL(req_in_lvl), $past(ack_out_lvl)),
                  clk_i, rst_ni)
  `OCAH_FV_ASSUME(asm_p2p_req_in_waits_for_ack_release,
                  `OCAH_FV_IMPLIES(p2p && `OCAH_FV_ROSE(req_in_lvl), !$past(ack_out_lvl)),
                  clk_i, rst_ni)
  `OCAH_FV_ASSUME(asm_p2p_ack_in_follows_req_out,
                  `OCAH_FV_IMPLIES(p2p && `OCAH_FV_ROSE(ack_in_lvl), $past(req_out_lvl)),
                  clk_i, rst_ni)
  `OCAH_FV_ASSUME(asm_p2p_ack_in_releases_after_req_out,
                  `OCAH_FV_IMPLIES(p2p && `OCAH_FV_FELL(ack_in_lvl), !$past(req_out_lvl)),
                  clk_i, rst_ni)

  // ---- Handshake controller -----------------------------------------------------------------
  `OCAH_FV_ASSERT(ast_hs_req_out_tracks_sender_state,
                  hs_req_out_i == (hs_sender_state_i == SENDER_REQ_ASSERTED),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_hs_ack_out_tracks_receiver_state,
                  hs_ack_out_i == (hs_receiver_state_i == RECEIVER_ACK_ASSERTED),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_hs_states_encoded,
                  hs_sender_state_i != 2'd3 && hs_receiver_state_i != 2'd3,
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_hs_req_out_falls_on_ack_or_reset,
                  `OCAH_FV_IMPLIES(`OCAH_FV_FELL(hs_req_out_i),
                                   $past(ack_in_sync_lvl_i) || $past(handshake_reset_i)),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_hs_ack_out_falls_on_req_release,
                  `OCAH_FV_IMPLIES(`OCAH_FV_FELL(hs_ack_out_i), !$past(req_in_sync_lvl_i)),
                  clk_i, rst_ni)

  // ---- Pulse stretcher ----------------------------------------------------------------------
  `OCAH_FV_ASSERT(ast_stretch_counter_zero_when_idle,
                  `OCAH_FV_IMPLIES(!stretch_active_i, stretch_counter_i == 16'd0),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_stretch_starts_on_pulse,
                  `OCAH_FV_IMPLIES($past(rst_ni) && $past(ct_src_i), stretch_active_i),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_stretch_counts_down,
                  `OCAH_FV_IMPLIES($past(stretch_active_i) && $past(stretch_counter_i) != 16'd0 &&
                                   !$past(ct_src_i),
                                   stretch_counter_i == $past(stretch_counter_i) - 16'd1),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_stretch_ends_at_zero,
                  `OCAH_FV_IMPLIES(`OCAH_FV_FELL(stretch_active_i),
                                   $past(stretch_counter_i) == 16'd0 && !$past(ct_src_i)),
                  clk_i, rst_ni)

  // ---- Core outputs -------------------------------------------------------------------------
  // Pad control outputs are registered, so they reflect the configuration from the second cycle
  // after reset release; $past(rst_ni) excludes the first.
  `OCAH_FV_ASSERT(ast_wire_or_pad_enables,
                  `OCAH_FV_IMPLIES($past(rst_ni) && mode_wire_or_i,
                                   ct_req_out_din_en_o && !ct_req_in_din_en_o &&
                                   !ct_ack_in_din_en_o && !ct_ack_out_dout_en_o &&
                                   !ct_ack_out_dout_o),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_wire_or_req_out_dout_static,
                  `OCAH_FV_IMPLIES($past(rst_ni) && mode_wire_or_i, ct_req_out_dout_o == invert_i),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_wire_or_req_out_enable_is_busy,
                  `OCAH_FV_IMPLIES(mode_wire_or_i, ct_req_out_dout_en_o == busy_o),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_wire_or_dst_on_pad_rise,
                  `OCAH_FV_IMPLIES(mode_wire_or_i,
                                   ct_dst_o == $past(req_out_sync_lvl_i && !wire_or_prev_i)),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_p2p_pad_enables,
                  `OCAH_FV_IMPLIES($past(rst_ni) && p2p,
                                   ct_req_out_dout_en_o && !ct_req_out_din_en_o &&
                                   ct_req_in_din_en_o && ct_ack_in_din_en_o &&
                                   ct_ack_out_dout_en_o),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_p2p_req_out_pad_tracks_hs,
                  `OCAH_FV_IMPLIES($past(rst_ni) && p2p, req_out_lvl == $past(hs_req_out_i)),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_p2p_ack_out_pad_tracks_hs,
                  `OCAH_FV_IMPLIES($past(rst_ni) && p2p, ack_out_lvl == $past(hs_ack_out_i)),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_p2p_busy_follows_pads,
                  `OCAH_FV_IMPLIES(p2p && $past(req_out_lvl || ack_out_lvl), busy_o),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_dst_pulse_single_cycle,
                  !(ct_dst_o && $past(ct_dst_o)),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_status_mirrors_pads,
                  status_busy_o == busy_o && status_req_out_o == req_out_lvl &&
                  status_ack_out_o == ack_out_lvl && status_req_in_o == req_in_sync_lvl_i &&
                  status_ack_in_o == ack_in_sync_lvl_i,
                  clk_i, rst_ni)

  // ---- Covers: one per non-trivial antecedent and per mode -----------------------------------
  `OCAH_FV_COVER(cov_p2p_send_completes,
                 p2p && hs_sender_state_i == SENDER_IDLE &&
                 $past(hs_sender_state_i) == SENDER_WAIT_ACK_DEASSERT,
                 clk_i, rst_ni)
  `OCAH_FV_COVER(cov_p2p_receive_completes,
                 p2p && hs_receiver_state_i == RECEIVER_IDLE &&
                 $past(hs_receiver_state_i) == RECEIVER_WAIT_REQ_DEASSERT,
                 clk_i, rst_ni)
  `OCAH_FV_COVER(cov_p2p_dst_pulse, p2p && ct_dst_o, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_hs_req_out_falls_on_ack,
                 `OCAH_FV_FELL(hs_req_out_i) && !$past(handshake_reset_i),
                 clk_i, rst_ni)
  `OCAH_FV_COVER(cov_hs_req_out_falls_on_reset,
                 `OCAH_FV_FELL(hs_req_out_i) && $past(handshake_reset_i),
                 clk_i, rst_ni)
  `OCAH_FV_COVER(cov_hs_ack_out_falls, `OCAH_FV_FELL(hs_ack_out_i), clk_i, rst_ni)
  `OCAH_FV_COVER(cov_wire_or_dst_pulse, mode_wire_or_i && ct_dst_o, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_stretch_restart,
                 $past(ct_src_i) && $past(stretch_active_i) && $past(stretch_counter_i) != 16'd0,
                 clk_i, rst_ni)
  `OCAH_FV_COVER(cov_stretch_ends, `OCAH_FV_FELL(stretch_active_i), clk_i, rst_ni)
  // verilog_format: on

endmodule : cross_trigger_port_core_props
