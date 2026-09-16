// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Cross Trigger Port Handshake Controller Module
//
// Description:
// Implements four-phase handshaking protocol for point-to-point mode.
// Controls ct_req_out assertion/deassertion based on ct_ack_in.
// Controls ct_ack_out assertion/deassertion based on ct_req_in.
// Supports RESET signal for deadlock recovery.
//------------------------------------------------------------------------------


module ctp_handshake_ctrl (
  input  logic clk_i,
  input  logic rst_ni,

  // Core-side signals
  input  logic ct_src_i,      // Cross trigger source pulse (synchronous)
  output logic ct_dst_o,       // Cross trigger destination pulse (registered)

  // Handshake reset (from CONFIG.RESET register)
  input  logic reset_i,

  // Synchronized pad inputs
  input  logic ct_req_in_sync_i,   // Synchronized CT_Req_in
  input  logic ct_ack_in_sync_i,   // Synchronized CT_Ack_in

  // Pad outputs (all registered)
  output logic ct_req_out_o,       // CT_Req_out output
  output logic ct_ack_out_o,        // CT_Ack_out output

  // Status
  output logic busy_o               // Handshake in progress
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
        if (!ct_req_in_sync_i) begin
          receiver_state_d = RECEIVER_WAIT_REQ_DEASSERT;
          ct_ack_out_d     = 1'b0;
        end else begin
          ct_dst_d = 1'b0;  // Pulse is one cycle
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
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      sender_state_q   <= SENDER_IDLE;
      receiver_state_q <= RECEIVER_IDLE;
      ct_req_out_q     <= 1'b0;
      ct_ack_out_q     <= 1'b0;
      ct_dst_q         <= 1'b0;
      busy_q           <= 1'b0;
    end else begin
      sender_state_q   <= sender_state_d;
      receiver_state_q <= receiver_state_d;
      ct_req_out_q     <= ct_req_out_d;
      ct_ack_out_q     <= ct_ack_out_d;
      ct_dst_q         <= ct_dst_d;
      busy_q           <= busy_d;
    end
  end

  assign ct_req_out_o = ct_req_out_q;
  assign ct_ack_out_o = ct_ack_out_q;
  assign ct_dst_o     = ct_dst_q;
  assign busy_o       = busy_q;

endmodule : ctp_handshake_ctrl
