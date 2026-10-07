// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Formal properties for the cross-trigger transport: the four-phase handshake controller, the
// mode multiplexers and wire-OR edge detect of the port core, the pulse stretcher, and one source
// selector slice of the matrix. Attached to cross_trigger_network by dtp_ctn_xtrig_bind.sv, which
// names external port 0 and matrix slice 0 as the representatives of their arrays and packs the
// internal ports' mode and route signals into vectors, and checked with cross_trigger_network as
// the formal top. Every property body is a boolean over current and one-cycle-past values
// (hw/common/dv/docs/formal-property-style.adoc); the state machines are stated as their exact
// next-state functions of the handshake controller's own inputs, which the port core gates: wire-OR
// mode masks the source and holds the sender in reset, and the synchronized request and
// acknowledge pass only from two cycles after the point-to-point input enable rises.

`include "ocah_fv_macros.svh"

module dtp_ctn_xtrig_props #(
  parameter int unsigned NUM_INT_CT = 10,
  parameter int unsigned NUM_CT_DST = 26
) (
  input logic                  clk_i,
  input logic                  rst_ni,
  // External port 0: configuration
  input logic                  mode_wire_or_i,    // u_core.mode_wire_or_i
  input logic                  invert_i,          // u_core.invert_i
  input logic                  hs_reset_i,        // u_core.handshake_reset_i
  input logic [15:0]           stretch_mult_i,    // u_core.stretch_mult_i
  // External port 0: handshake controller
  input logic                  ct_src_i,          // u_core.ct_src_i
  input logic                  hs_src_i,          // u_handshake_ctrl.ct_src_i
  input logic                  hs_sender_reset_i, // u_handshake_ctrl.reset_i
  input logic                  hs_req_in_i,       // u_handshake_ctrl.ct_req_in_sync_i
  input logic                  hs_ack_in_i,       // u_handshake_ctrl.ct_ack_in_sync_i
  input logic [1:0]            sender_state_i,    // u_handshake_ctrl.sender_state_q
  input logic [1:0]            receiver_state_i,  // u_handshake_ctrl.receiver_state_q
  input logic                  hs_req_out_i,      // u_handshake_ctrl.ct_req_out_q
  input logic                  hs_ack_out_i,      // u_handshake_ctrl.ct_ack_out_q
  input logic                  hs_dst_i,          // u_handshake_ctrl.ct_dst_q
  input logic                  hs_busy_i,         // u_handshake_ctrl.busy_q
  input logic                  req_in_sync_i,     // u_core.ct_req_in_din_sync_inv
  input logic                  ack_in_sync_i,     // u_core.ct_ack_in_din_sync_inv
  // External port 0: wire-OR receive path and pad control
  input logic                  req_out_din_raw_sync_i,  // u_core.ct_req_out_din_sync
  input logic                  req_out_din_sync_i,  // u_core.ct_req_out_din_sync_inv
  input logic                  req_out_din_prev_i,  // u_core.wire_or_req_out_prev
  input logic                  ct_dst_i,            // u_core.ct_dst_q
  input logic                  req_out_dout_en_i,   // u_core.ct_req_out_dout_en_q
  input logic                  req_out_din_en_i,    // u_core.ct_req_out_din_en_q
  input logic                  req_out_dout_i,      // u_core.ct_req_out_dout_q
  input logic                  req_in_din_en_i,     // u_core.ct_req_in_din_en_q
  input logic                  ack_in_din_en_i,     // u_core.ct_ack_in_din_en_q
  input logic                  ack_out_dout_en_i,   // u_core.ct_ack_out_dout_en_q
  input logic                  ack_out_dout_i,      // u_core.ct_ack_out_dout_q
  // External port 0: pulse stretcher
  input logic                  stretch_active_i,  // u_pulse_stretcher.active_q
  input logic [15:0]           stretch_count_i,   // u_pulse_stretcher.counter_q
  // External port 0: STATUS readback
  input logic                  status_busy_i,     // reg_in.STATUS.BUSY.next
  input logic                  status_req_out_i,  // reg_in.STATUS.REQ_OUT.next
  input logic                  status_ack_in_i,   // reg_in.STATUS.ACK_IN.next
  input logic                  status_req_in_i,   // reg_in.STATUS.REQ_IN.next
  input logic                  status_ack_out_i,  // reg_in.STATUS.ACK_OUT.next
  // Matrix slice 0
  input logic [NUM_CT_DST-1:0] ctm_ct_dst_i,      // ctm_ct_dst
  input logic [NUM_CT_DST-1:0] ctm_select_i,      // u_ctm.gen_src_selectors[0].select_mask
  input logic                  ctm_ct_src_i,      // ctm_ct_src[0]
  // Internal ports, one bit per port
  input logic [NUM_INT_CT-1:0] int_mode_wire_or_i,   // u_int_ctp_core.mode_wire_or_i
  input logic [NUM_INT_CT-1:0] int_req_out_dout_en_i,// int_ct_req_out_dout_en
  input logic [NUM_INT_CT-1:0] ctm_src_req_i         // ctm_src_req_o
);

  // sender_state_e and receiver_state_e encodings of ctp_handshake_ctrl.
  localparam logic [1:0] SIdle = 2'd0;
  localparam logic [1:0] SReqAsserted = 2'd1;
  localparam logic [1:0] SWaitAckDeassert = 2'd2;
  localparam logic [1:0] RIdle = 2'd0;
  localparam logic [1:0] RAckAsserted = 2'd1;
  localparam logic [1:0] RWaitReqDeassert = 2'd2;

  function automatic logic [1:0] sender_next(input logic [1:0] state, input logic src,
                                             input logic ack, input logic reset);
    if (reset) return SIdle;
    case (state)
      SIdle:               return src ? SReqAsserted : SIdle;
      SReqAsserted:        return ack ? SWaitAckDeassert : SReqAsserted;
      SWaitAckDeassert:    return ack ? SWaitAckDeassert : SIdle;
      default:             return SIdle;
    endcase
  endfunction

  function automatic logic [1:0] receiver_next(input logic [1:0] state, input logic req);
    case (state)
      RIdle:               return req ? RAckAsserted : RIdle;
      RAckAsserted:        return req ? RAckAsserted : RWaitReqDeassert;
      RWaitReqDeassert:    return req ? RWaitReqDeassert : RIdle;
      default:             return RIdle;
    endcase
  endfunction

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(clk_i, rst_ni)

  // ---- Four-phase handshake controller ------------------------------------------------------
  `OCAH_FV_ASSERT(ast_hs_sender_states,
                  sender_state_i <= SWaitAckDeassert &&
                  `OCAH_FV_IMPLIES($past(rst_ni),
                                   sender_state_i == sender_next($past(sender_state_i),
                                                                 $past(hs_src_i),
                                                                 $past(hs_ack_in_i),
                                                                 $past(hs_sender_reset_i))),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_hs_receiver_states,
                  receiver_state_i <= RWaitReqDeassert &&
                  `OCAH_FV_IMPLIES($past(rst_ni),
                                   receiver_state_i == receiver_next($past(receiver_state_i),
                                                                     $past(hs_req_in_i))),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_hs_req_stable_until_ack,
                  hs_req_out_i == (sender_state_i == SReqAsserted) &&
                  `OCAH_FV_IMPLIES($past(rst_ni) && $past(hs_req_out_i) && !$past(hs_ack_in_i) &&
                                   !$past(hs_sender_reset_i),
                                   hs_req_out_i),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_hs_ack_mirrors_req,
                  hs_ack_out_i == (receiver_state_i == RAckAsserted) &&
                  `OCAH_FV_IMPLIES($past(rst_ni) && $past(receiver_state_i) == RIdle &&
                                   $past(hs_req_in_i),
                                   hs_ack_out_i) &&
                  `OCAH_FV_IMPLIES($past(rst_ni) && $past(receiver_state_i) == RAckAsserted &&
                                   !$past(hs_req_in_i),
                                   !hs_ack_out_i),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_hs_dst_is_one_pulse,
                  !($past(rst_ni) && hs_dst_i && $past(hs_dst_i)) &&
                  `OCAH_FV_IMPLIES($past(rst_ni) && `OCAH_FV_ROSE(hs_dst_i),
                                   $past(receiver_state_i) == RIdle && $past(hs_req_in_i)),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_hs_busy_lags_state,
                  `OCAH_FV_IMPLIES($past(rst_ni),
                                   hs_busy_i == ($past(sender_state_i) != SIdle ||
                                                 $past(receiver_state_i) != RIdle)),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_hs_reset_recovers_sender,
                  `OCAH_FV_IMPLIES($past(rst_ni) && $past(hs_sender_reset_i),
                                   sender_state_i == SIdle && !hs_req_out_i &&
                                   receiver_state_i == receiver_next($past(receiver_state_i),
                                                                     $past(hs_req_in_i))),
                  clk_i, rst_ni)

  // ---- Port core: mode multiplexers, wire-OR edge detect, status --------------------------
  `OCAH_FV_ASSERT(ast_ctp_mode_enables_exclusive,
                  `OCAH_FV_IMPLIES($past(rst_ni),
                                   req_out_din_en_i == $past(mode_wire_or_i) &&
                                   req_in_din_en_i == !$past(mode_wire_or_i) &&
                                   ack_in_din_en_i == !$past(mode_wire_or_i) &&
                                   ack_out_dout_en_i == !$past(mode_wire_or_i) &&
                                   req_out_dout_en_i ==
                                   ($past(mode_wire_or_i) ? $past(stretch_active_i) : 1'b1)) &&
                  hs_src_i == (ct_src_i && !mode_wire_or_i) &&
                  hs_sender_reset_i == (hs_reset_i || mode_wire_or_i) &&
                  int_mode_wire_or_i == '1 && ctm_src_req_i == int_req_out_dout_en_i,
                  clk_i, rst_ni)
  // The optional inversion sits after the synchronizer: INVERT=0 senses the raw wire, INVERT=1
  // its complement, so the sensed wire rests at 1 and reads 0 while asserted in either sense.
  `OCAH_FV_ASSERT(ast_ctp_wire_or_sense,
                  req_out_din_sync_i == (invert_i ? !req_out_din_raw_sync_i
                                                  : req_out_din_raw_sync_i),
                  clk_i, rst_ni)
  // A wire-OR trigger is the sensed wire moving from rest to asserted: the falling edge of the
  // raw wire for INVERT=0, its rising edge for INVERT=1; the release edge yields nothing.
  `OCAH_FV_ASSERT(ast_ctp_wire_or_edge_pulse,
                  `OCAH_FV_IMPLIES($past(rst_ni),
                                   req_out_din_prev_i == $past(req_out_din_sync_i) &&
                                   ct_dst_i == ($past(mode_wire_or_i)
                                                ? (!$past(req_out_din_sync_i) &&
                                                   $past(req_out_din_prev_i))
                                                : $past(hs_dst_i))),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_stretch_width,
                  `OCAH_FV_IMPLIES($past(rst_ni) && $past(ct_src_i),
                                   stretch_active_i && stretch_count_i == $past(stretch_mult_i)) &&
                  `OCAH_FV_IMPLIES($past(rst_ni) && !$past(ct_src_i) && $past(stretch_active_i) &&
                                   $past(stretch_count_i) != '0,
                                   stretch_active_i &&
                                   stretch_count_i == $past(stretch_count_i) - 16'd1) &&
                  `OCAH_FV_IMPLIES($past(rst_ni) && !$past(ct_src_i) &&
                                   (!$past(stretch_active_i) || $past(stretch_count_i) == '0),
                                   !stretch_active_i && stretch_count_i == '0),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_ctm_slice_route,
                  `OCAH_FV_IMPLIES($past(rst_ni),
                                   ctm_ct_src_i == |($past(ctm_ct_dst_i) & $past(ctm_select_i))),
                  clk_i, rst_ni)
  `OCAH_FV_ASSERT(ast_ctp_status_reflects_pins,
                  status_req_in_i == req_in_sync_i && status_ack_in_i == ack_in_sync_i &&
                  status_req_out_i == (invert_i ? !req_out_dout_i : req_out_dout_i) &&
                  status_ack_out_i == (!mode_wire_or_i &&
                                       (invert_i ? !ack_out_dout_i : ack_out_dout_i)) &&
                  `OCAH_FV_IMPLIES($past(rst_ni) && $past(mode_wire_or_i) &&
                                   invert_i == $past(invert_i),
                                   !status_req_out_i) &&
                  `OCAH_FV_IMPLIES($past(rst_ni),
                                   status_busy_i == ($past(mode_wire_or_i) ? $past(stretch_active_i)
                                                                           : $past(hs_busy_i))),
                  clk_i, rst_ni)

  // ---- Covers -------------------------------------------------------------------------------
  `OCAH_FV_COVER(cov_hs_four_phase_complete,
                 $past(sender_state_i) == SWaitAckDeassert && sender_state_i == SIdle,
                 clk_i, rst_ni)
  `OCAH_FV_COVER(cov_hs_request_received,
                 $past(receiver_state_i) == RWaitReqDeassert && receiver_state_i == RIdle,
                 clk_i, rst_ni)
  `OCAH_FV_COVER(cov_stretch_max_width,
                 mode_wire_or_i && $past(ct_src_i) && stretch_count_i == 16'd4, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_wire_or_receive_normal, mode_wire_or_i && !invert_i && ct_dst_i,
                 clk_i, rst_ni)
  `OCAH_FV_COVER(cov_wire_or_receive_inverted, mode_wire_or_i && invert_i && ct_dst_i,
                 clk_i, rst_ni)
  `OCAH_FV_COVER(cov_route_internal_to_external,
                 ct_src_i && |(ctm_select_i >> 16), clk_i, rst_ni)
  `OCAH_FV_COVER(cov_route_external_to_internal, |ctm_src_req_i, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_hs_reset_in_p2p, hs_reset_i && !mode_wire_or_i, clk_i, rst_ni)
  `OCAH_FV_COVER(cov_hs_reset_in_wire_or, hs_reset_i && mode_wire_or_i, clk_i, rst_ni)
  // verilog_format: on

endmodule : dtp_ctn_xtrig_props
