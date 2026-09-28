// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Implement wire-OR and point-to-point cross-trigger pad protocols without a register block.
//
// mode_wire_or_i is 1 for wire-OR and 0 for point-to-point; invert_i inverts the pad data levels;
// stretch_mult_i sets wire-OR stretch; handshake_reset_i recovers P2P deadlock.
// Synchronizes pad inputs, stretches or handshakes ct_src_i, and reports busy plus
// REQ/ACK status for CSR readback.
// ct_dst_o, busy_o, and the pad controls are registered and reset low.

module cross_trigger_port_core (
  input  logic        clk_i,            // System clock for the port logic.
  input  logic        rst_ni,           // Active-low asynchronous system reset.

  input  logic        mode_wire_or_i,   // Pad protocol select: 1'b1 = wire-OR, 1'b0 =
                                        // point-to-point.
  input  logic        invert_i,         // Inverts the synchronized pad inputs and the driven pad
                                        // data outputs; pad enables are not inverted.
  input  logic        handshake_reset_i,  // Resets the outgoing point-to-point handshake state
                                          // machine.
  input  logic [15:0] stretch_mult_i,   // Wire-OR pulse stretch: each outgoing pulse lasts
                                        // stretch_mult_i+1 clk_i cycles.

  input  logic        ct_src_i,         // Core-side cross-trigger pulse to transmit, synchronous to
                                        // clk_i.
  output logic        ct_dst_o,         // Core-side received cross-trigger pulse, registered.
  output logic        busy_o,           // High, one cycle late, while the stretched pulse is active
                                        // in wire-OR mode, or while the outgoing or incoming
                                        // handshake is active in point-to-point mode.

  output logic        ct_req_out_dout_en_o,  // Output enable for the CT_Req_out pad. Follows the
                                             // stretched outgoing pulse in wire-OR mode; high in
                                             // point-to-point mode.
  output logic        ct_req_out_din_en_o,  // Input enable for the CT_Req_out pad.
                                            // High in wire-OR mode; low in point-to-point mode.
  output logic        ct_req_out_dout_o,  // Output data for the CT_Req_out pad. Carries the
                                          // outgoing handshake request in point-to-point mode. Held
                                          // low in wire-OR mode, or high when invert_i is set.
  input  logic        ct_req_out_din_i,  // Input data from the CT_Req_out pad. In wire-OR mode its
                                         // synchronized assertion edge, falling unless inverted,
                                         // pulses ct_dst_o; unused in point-to-point mode.

  output logic        ct_req_in_din_en_o,  // Input enable for the CT_Req_in pad.
                                           // High in point-to-point mode; low in wire-OR mode.
  input  logic        ct_req_in_din_i,  // Input data from the CT_Req_in pad. In point-to-point mode
                                        // its synchronized request pulses ct_dst_o; unused in
                                        // wire-OR mode.

  output logic        ct_ack_in_din_en_o,  // Input enable for the CT_Ack_in pad.
                                           // High in point-to-point mode; low in wire-OR mode.
  input  logic        ct_ack_in_din_i,  // Input data from the CT_Ack_in pad. In point-to-point mode
                                        // its synchronized acknowledge clears the outgoing request;
                                        // unused in wire-OR mode.

  output logic        ct_ack_out_dout_en_o,  // Output enable for the CT_Ack_out pad.
                                             // High in point-to-point mode; low in wire-OR mode.
  output logic        ct_ack_out_dout_o,  // Output data for the CT_Ack_out pad. Acknowledges the
                                          // synchronized CT_Req_in request in point-to-point mode;
                                          // held low in wire-OR mode.

  output logic        status_busy_o,    // Copy of busy_o for the STATUS.BUSY field.
  output logic        status_req_out_o,  // Registered CT_Req_out pad data with invert_i undone;
                                         // always low in wire-OR mode.
  output logic        status_ack_in_o,  // Synchronized CT_Ack_in pad input, polarity-corrected by
                                        // invert_i.
  output logic        status_req_in_o,  // Synchronized CT_Req_in pad input, polarity-corrected by
                                        // invert_i.
  output logic        status_ack_out_o  // Registered CT_Ack_out pad data with invert_i undone; in
                                        // wire-OR mode it equals invert_i because the pad data is
                                        // held low without inversion.
);

  // Synchronizer module
  logic ct_req_out_din_sync;
  logic ct_req_in_din_sync;
  logic ct_ack_in_din_sync;

  ctp_synchronizer u_synchronizer (
    .clk_i                  (clk_i),
    .rst_ni                 (rst_ni),
    .ct_req_out_din_i       (ct_req_out_din_i),
    .ct_req_in_din_i        (ct_req_in_din_i),
    .ct_ack_in_din_i        (ct_ack_in_din_i),
    .ct_req_out_din_sync_o  (ct_req_out_din_sync),
    .ct_req_in_din_sync_o   (ct_req_in_din_sync),
    .ct_ack_in_din_sync_o   (ct_ack_in_din_sync)
  );

  // Apply inversion to synchronized signals if needed
  logic ct_req_out_din_sync_inv;
  logic ct_req_in_din_sync_inv;
  logic ct_ack_in_din_sync_inv;

  assign ct_req_out_din_sync_inv = invert_i ? ~ct_req_out_din_sync : ct_req_out_din_sync;
  assign ct_req_in_din_sync_inv  = invert_i ? ~ct_req_in_din_sync  : ct_req_in_din_sync;
  assign ct_ack_in_din_sync_inv  = invert_i ? ~ct_ack_in_din_sync  : ct_ack_in_din_sync;

  // Pulse stretcher for Wire-OR mode
  logic stretched_pulse;
  ctp_pulse_stretcher u_pulse_stretcher (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .pulse_i         (ct_src_i),
    .stretch_mult_i  (stretch_mult_i),
    .stretched_pulse_o (stretched_pulse)
  );

  // Edge detector for point-to-point mode (on receiver side)
  logic req_in_posedge_pulse;
  ctp_edge_detector u_edge_detector (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .signal_i        (ct_req_in_din_sync_inv),
    .posedge_pulse_o (req_in_posedge_pulse)
  );

  // Handshake controller for point-to-point mode
  logic handshake_ct_dst;
  logic handshake_ct_req_out;
  logic handshake_ct_ack_out;
  logic handshake_busy;

  ctp_handshake_ctrl u_handshake_ctrl (
    .clk_i              (clk_i),
    .rst_ni             (rst_ni),
    .ct_src_i           (ct_src_i),
    .ct_dst_o           (handshake_ct_dst),
    .reset_i            (handshake_reset_i),
    .ct_req_in_sync_i   (ct_req_in_din_sync_inv),
    .ct_ack_in_sync_i   (ct_ack_in_din_sync_inv),
    .ct_req_out_o       (handshake_ct_req_out),
    .ct_ack_out_o       (handshake_ct_ack_out),
    .busy_o             (handshake_busy)
  );

  // Wire-OR mode: ct_dst pulses on the falling (assertion) edge of ct_req_out_din.
  logic wire_or_ct_dst;
  logic wire_or_req_out_prev;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      wire_or_req_out_prev <= 1'b0;
    end else begin
      wire_or_req_out_prev <= ct_req_out_din_sync_inv;
    end
  end
  assign wire_or_ct_dst = ~ct_req_out_din_sync_inv & wire_or_req_out_prev;

  // Mode multiplexing for ct_dst output
  logic ct_dst_raw;
  assign ct_dst_raw = mode_wire_or_i ? wire_or_ct_dst : handshake_ct_dst;

  // Register ct_dst output
  logic ct_dst_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      ct_dst_q <= 1'b0;
    end else begin
      ct_dst_q <= ct_dst_raw;
    end
  end
  assign ct_dst_o = ct_dst_q;

  // Wire-OR mode pad control
  logic wire_or_req_out_dout_en;
  logic wire_or_req_out_din_en;
  logic wire_or_req_out_dout;

  assign wire_or_req_out_dout_en = stretched_pulse;  // Enable output during stretched pulse
  assign wire_or_req_out_din_en  = 1'b1;            // Always enable input in wire-OR mode
  assign wire_or_req_out_dout    = invert_i ? 1'b1 : 1'b0;  // Static low (or high if inverted)

  // Point-to-Point mode pad control
  logic p2p_req_out_dout_en;
  logic p2p_req_out_din_en;
  logic p2p_req_out_dout;
  logic p2p_req_in_din_en;
  logic p2p_ack_in_din_en;
  logic p2p_ack_out_dout_en;
  logic p2p_ack_out_dout;

  assign p2p_req_out_dout_en = 1'b1;  // Always enabled in point-to-point mode
  assign p2p_req_out_din_en  = 1'b0;  // Disabled in point-to-point mode
  assign p2p_req_out_dout    = invert_i ? ~handshake_ct_req_out : handshake_ct_req_out;

  assign p2p_req_in_din_en   = 1'b1;  // Always enabled in point-to-point mode
  assign p2p_ack_in_din_en   = 1'b1;  // Always enabled in point-to-point mode

  assign p2p_ack_out_dout_en = 1'b1;  // Always enabled in point-to-point mode
  assign p2p_ack_out_dout    = invert_i ? ~handshake_ct_ack_out : handshake_ct_ack_out;

  // Mode multiplexing for pad control signals
  logic ct_req_out_dout_en_raw, ct_req_out_dout_en_q;
  logic ct_req_out_din_en_raw, ct_req_out_din_en_q;
  logic ct_req_out_dout_raw, ct_req_out_dout_q;
  logic ct_req_in_din_en_raw, ct_req_in_din_en_q;
  logic ct_ack_in_din_en_raw, ct_ack_in_din_en_q;
  logic ct_ack_out_dout_en_raw, ct_ack_out_dout_en_q;
  logic ct_ack_out_dout_raw, ct_ack_out_dout_q;

  assign ct_req_out_dout_en_raw = mode_wire_or_i ? wire_or_req_out_dout_en : p2p_req_out_dout_en;
  assign ct_req_out_din_en_raw  = mode_wire_or_i ? wire_or_req_out_din_en  : p2p_req_out_din_en;
  assign ct_req_out_dout_raw    = mode_wire_or_i ? wire_or_req_out_dout    : p2p_req_out_dout;

  assign ct_req_in_din_en_raw   = mode_wire_or_i ? 1'b0 : p2p_req_in_din_en;
  assign ct_ack_in_din_en_raw   = mode_wire_or_i ? 1'b0 : p2p_ack_in_din_en;

  assign ct_ack_out_dout_en_raw = mode_wire_or_i ? 1'b0 : p2p_ack_out_dout_en;
  assign ct_ack_out_dout_raw    = mode_wire_or_i ? 1'b0 : p2p_ack_out_dout;

  // Register all pad control outputs
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      ct_req_out_dout_en_q <= 1'b0;
      ct_req_out_din_en_q  <= 1'b0;
      ct_req_out_dout_q    <= 1'b0;
      ct_req_in_din_en_q   <= 1'b0;
      ct_ack_in_din_en_q   <= 1'b0;
      ct_ack_out_dout_en_q <= 1'b0;
      ct_ack_out_dout_q    <= 1'b0;
    end else begin
      ct_req_out_dout_en_q <= ct_req_out_dout_en_raw;
      ct_req_out_din_en_q  <= ct_req_out_din_en_raw;
      ct_req_out_dout_q    <= ct_req_out_dout_raw;
      ct_req_in_din_en_q   <= ct_req_in_din_en_raw;
      ct_ack_in_din_en_q   <= ct_ack_in_din_en_raw;
      ct_ack_out_dout_en_q <= ct_ack_out_dout_en_raw;
      ct_ack_out_dout_q    <= ct_ack_out_dout_raw;
    end
  end

  assign ct_req_out_dout_en_o = ct_req_out_dout_en_q;
  assign ct_req_out_din_en_o  = ct_req_out_din_en_q;
  assign ct_req_out_dout_o    = ct_req_out_dout_q;
  assign ct_req_in_din_en_o   = ct_req_in_din_en_q;
  assign ct_ack_in_din_en_o   = ct_ack_in_din_en_q;
  assign ct_ack_out_dout_en_o = ct_ack_out_dout_en_q;
  assign ct_ack_out_dout_o    = ct_ack_out_dout_q;

  // BUSY signal generation
  logic wire_or_busy;
  assign wire_or_busy = stretched_pulse;

  logic busy_raw;
  assign busy_raw = mode_wire_or_i ? wire_or_busy : handshake_busy;

  // Register BUSY output
  logic busy_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      busy_q <= 1'b0;
    end else begin
      busy_q <= busy_raw;
    end
  end
  assign busy_o = busy_q;

  // Status outputs for CSR readback
  assign status_busy_o    = busy_q;
  assign status_req_out_o = invert_i ? ~ct_req_out_dout_q : ct_req_out_dout_q;
  assign status_ack_in_o = ct_ack_in_din_sync_inv;
  assign status_req_in_o = ct_req_in_din_sync_inv;
  assign status_ack_out_o = invert_i ? ~ct_ack_out_dout_q : ct_ack_out_dout_q;

endmodule : cross_trigger_port_core
