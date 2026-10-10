// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Run four-phase req/ack handshaking for point-to-point CTP mode.
//
// Asserts and releases ct_req_out_o from ct_src_i against synchronized ct_ack_in_sync_i.
// Asserts and releases ct_ack_out_o from synchronized ct_req_in_sync_i and pulses
// ct_dst_o.
// reset_i recovers a sender deadlock and leaves the receiver untouched; busy_o is high while
// either side's handshake is in progress.
// Pad outputs are registered.

`include "ocah_registers.svh"

module ctp_handshake_ctrl (
  input  logic clk_i,                   // System clock.
  input  logic rst_ni,                  // Active-low asynchronous reset; returns both state
                                        // machines to idle.

  input  logic ct_src_i,                // Core-side pulse, synchronous to clk_i, that starts an
                                        // outgoing handshake; ignored unless the sender state
                                        // machine is idle.
  output logic ct_dst_o,                // Registered pulse raised when the receiver accepts a new
                                        // CT_Req_in request.

  input  logic reset_i,                 // Level-sensitive sender reset, from CONFIG.RESET in
                                        // cross_trigger_port; while high it holds the sender idle
                                        // with ct_req_out_o low.

  input  logic ct_req_in_sync_i,        // Incoming request level, synchronized to clk_i and
                                        // polarity-corrected.
  input  logic ct_ack_in_sync_i,        // Incoming acknowledge level, synchronized to clk_i and
                                        // polarity-corrected.

  output logic ct_req_out_o,            // Outgoing request level for the CT_Req_out pad, before pad
                                        // inversion; set by ct_src_i and cleared when
                                        // ct_ack_in_sync_i asserts or on reset_i.
  output logic ct_ack_out_o,            // Outgoing acknowledge level for the CT_Ack_out pad, before
                                        // pad inversion; set when ct_req_in_sync_i asserts and
                                        // cleared when it deasserts.

  output logic busy_o                   // High while the sender or receiver state machine is not
                                        // idle; registered.
);

  // Sender state machine states
  typedef enum logic [1:0] {
    SENDER_IDLE,
    SENDER_REQ_ASSERTED,
    SENDER_WAIT_ACK_DEASSERT
  } sender_state_e;

  // Receiver state machine states
  typedef enum logic [1:0] {
    RECEIVER_IDLE,
    RECEIVER_ACK_ASSERTED,
    RECEIVER_WAIT_REQ_DEASSERT
  } receiver_state_e;

  sender_state_e sender_state_q, sender_state_d;
  receiver_state_e receiver_state_q, receiver_state_d;

  logic ct_req_out_q, ct_req_out_d;
  logic ct_ack_out_q, ct_ack_out_d;
  logic ct_dst_q, ct_dst_d;
  logic busy_q, busy_d;

  // Sender state machine
  always_comb begin
    sender_state_d = sender_state_q;
    ct_req_out_d   = ct_req_out_q;

    if (reset_i) begin
      sender_state_d = SENDER_IDLE;
      ct_req_out_d   = 1'b0;
    end else begin
      case (sender_state_q)
        SENDER_IDLE: begin
          if (ct_src_i) begin
            sender_state_d = SENDER_REQ_ASSERTED;
            ct_req_out_d   = 1'b1;
          end
        end

        SENDER_REQ_ASSERTED: begin
          if (ct_ack_in_sync_i) begin
            sender_state_d = SENDER_WAIT_ACK_DEASSERT;
            ct_req_out_d   = 1'b0;
          end
        end

        SENDER_WAIT_ACK_DEASSERT: begin
          if (!ct_ack_in_sync_i) begin
            sender_state_d = SENDER_IDLE;
          end
        end

        default: begin
          sender_state_d = SENDER_IDLE;
          ct_req_out_d   = 1'b0;
        end
      endcase
    end
  end

  // Receiver state machine
  always_comb begin
    receiver_state_d = receiver_state_q;
    ct_ack_out_d     = ct_ack_out_q;
    ct_dst_d         = ct_dst_q;

    case (receiver_state_q)
      RECEIVER_IDLE: begin
        if (ct_req_in_sync_i) begin
          receiver_state_d = RECEIVER_ACK_ASSERTED;
          ct_ack_out_d     = 1'b1;
          ct_dst_d         = 1'b1;  // Generate pulse on ct_dst
        end else begin
          ct_dst_d = 1'b0;
        end
      end

      RECEIVER_ACK_ASSERTED: begin
        ct_dst_d = 1'b0;  // Pulse is one cycle
        if (!ct_req_in_sync_i) begin
          receiver_state_d = RECEIVER_WAIT_REQ_DEASSERT;
          ct_ack_out_d     = 1'b0;
        end
      end

      RECEIVER_WAIT_REQ_DEASSERT: begin
        if (!ct_req_in_sync_i) begin
          receiver_state_d = RECEIVER_IDLE;
        end
        ct_dst_d = 1'b0;
      end

      default: begin
        receiver_state_d = RECEIVER_IDLE;
        ct_ack_out_d     = 1'b0;
        ct_dst_d         = 1'b0;
      end
    endcase
  end

  // Busy signal: active when either state machine is not idle
  always_comb begin
    busy_d = (sender_state_q != SENDER_IDLE) || (receiver_state_q != RECEIVER_IDLE);
  end

  // Registered outputs
  `OCAH_FF(sender_state_q, sender_state_d, SENDER_IDLE, clk_i, rst_ni)
  `OCAH_FF(receiver_state_q, receiver_state_d, RECEIVER_IDLE, clk_i, rst_ni)
  `OCAH_FF(ct_req_out_q, ct_req_out_d, 1'b0, clk_i, rst_ni)
  `OCAH_FF(ct_ack_out_q, ct_ack_out_d, 1'b0, clk_i, rst_ni)
  `OCAH_FF(ct_dst_q, ct_dst_d, 1'b0, clk_i, rst_ni)
  `OCAH_FF(busy_q, busy_d, 1'b0, clk_i, rst_ni)

  assign ct_req_out_o = ct_req_out_q;
  assign ct_ack_out_o = ct_ack_out_q;
  assign ct_dst_o     = ct_dst_q;
  assign busy_o       = busy_q;

endmodule : ctp_handshake_ctrl
