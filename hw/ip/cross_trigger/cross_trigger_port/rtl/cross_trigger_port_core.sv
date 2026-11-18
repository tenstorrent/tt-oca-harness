// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Implement wire-OR, point-to-point, and toggle cross-trigger pad protocols without a register
// block.
//
// mode_i selects the protocol; invert_i inverts the pad data levels; stretch_mult_i sets the
// wire-OR stretch and the toggle hold; handshake_reset_i recovers P2P deadlock.
// Synchronizes pad inputs, stretches, handshakes, or toggles on ct_src_i, and reports busy plus
// REQ/ACK status for CSR readback.
// The handshake runs only in point-to-point mode. Point-to-point and toggle mode ignore the
// CT_Req_in and CT_Ack_in pad inputs until their synchronizers carry pad data.
// ct_dst_o, busy_o, and the pad controls are registered and reset low.

`include "ocah_assert.svh"
`include "ocah_registers.svh"

module cross_trigger_port_core
  import cross_trigger_port_pkg::ctp_mode_e;
  import cross_trigger_port_pkg::MODE_WIRE_OR;
  import cross_trigger_port_pkg::MODE_POINT_TO_POINT;
  import cross_trigger_port_pkg::MODE_TOGGLE;
(
  input  logic        clk_i,            // System clock for the port logic.
  input  logic        rst_ni,           // Active-low asynchronous system reset.

  input  ctp_mode_e   mode_i,           // Pad protocol select: wire-OR, point-to-point, or
                                        // toggle. Every mode other than point-to-point holds the
                                        // point-to-point handshake idle with its request low.
                                        // 2'b11 is not a mode.
  input  logic        invert_i,         // Inverts the synchronized pad inputs and the driven pad
                                        // data outputs; pad enables are not inverted.
  input  logic        handshake_reset_i,  // Resets the outgoing point-to-point handshake state
                                          // machine; no effect in the other modes.
  input  logic [15:0] stretch_mult_i,   // Wire-OR pulse stretch: each outgoing pulse lasts
                                        // stretch_mult_i+1 clk_i cycles. Toggle hold: each
                                        // CT_Req_out level lasts at least stretch_mult_i+2 clk_i
                                        // cycles.

  input  logic        ct_src_i,         // Core-side cross-trigger pulse to transmit, synchronous to
                                        // clk_i. In toggle mode a pulse during the hold is
                                        // discarded.
  output logic        ct_dst_o,         // Core-side received cross-trigger pulse, registered.
  output logic        busy_o,           // High, one cycle late, while the stretched pulse is active
                                        // in wire-OR mode, while the hold is active in toggle
                                        // mode, or while the outgoing or incoming handshake is
                                        // active in point-to-point mode.

  output logic        ct_req_out_dout_en_o,  // Output enable for the CT_Req_out pad. Follows the
                                             // stretched outgoing pulse in wire-OR mode; high in
                                             // point-to-point and toggle mode.
  output logic        ct_req_out_din_en_o,  // Input enable for the CT_Req_out pad. High in
                                            // wire-OR mode; low in point-to-point and toggle mode.
  output logic        ct_req_out_dout_o,  // Output data for the CT_Req_out pad. Carries the
                                          // outgoing handshake request in point-to-point mode and
                                          // the toggle level in toggle mode. Held low in wire-OR
                                          // mode, or high when invert_i is set.
  input  logic        ct_req_out_din_i,  // Input data from the CT_Req_out pad. In wire-OR mode its
                                         // synchronized assertion edge, falling unless inverted,
                                         // pulses ct_dst_o; unused in the other modes.

  output logic        ct_req_in_din_en_o,  // Input enable for the CT_Req_in pad. High in
                                           // point-to-point and toggle mode; low in wire-OR mode.
  input  logic        ct_req_in_din_i,  // Input data from the CT_Req_in pad. In point-to-point mode
                                        // its synchronized request pulses ct_dst_o; in toggle mode
                                        // each synchronized level change pulses ct_dst_o; unused
                                        // in wire-OR mode.

  output logic        ct_ack_in_din_en_o,  // Input enable for the CT_Ack_in pad.
                                           // High in point-to-point mode; low in the other modes.
  input  logic        ct_ack_in_din_i,  // Input data from the CT_Ack_in pad. In point-to-point mode
                                        // its synchronized acknowledge clears the outgoing request;
                                        // unused in the other modes.

  output logic        ct_ack_out_dout_en_o,  // Output enable for the CT_Ack_out pad.
                                             // High in point-to-point mode; low in the other modes.
  output logic        ct_ack_out_dout_o,  // Output data for the CT_Ack_out pad. Acknowledges the
                                          // synchronized CT_Req_in request in point-to-point mode;
                                          // held low in the other modes.

  output logic        status_busy_o,    // Copy of busy_o for the STATUS.BUSY field.
  output logic        status_req_out_o,  // Registered CT_Req_out pad data with invert_i undone;
                                         // always low in wire-OR mode.
  output logic        status_ack_in_o,  // Synchronized CT_Ack_in pad input, polarity-corrected by
                                        // invert_i.
  output logic        status_req_in_o,  // Synchronized CT_Req_in pad input, polarity-corrected by
                                        // invert_i.
  output logic        status_ack_out_o  // Registered CT_Ack_out pad data with invert_i undone;
                                        // always low outside point-to-point mode.
);

  // Mode decode
  logic mode_wire_or;
  logic mode_p2p;
  logic mode_toggle;

  assign mode_wire_or = (mode_i == MODE_WIRE_OR);
  assign mode_p2p     = (mode_i == MODE_POINT_TO_POINT);
  assign mode_toggle  = (mode_i == MODE_TOGGLE);

  `OCAH_ASSERT(ModeLegal_A, mode_i inside {MODE_WIRE_OR, MODE_POINT_TO_POINT, MODE_TOGGLE}, clk_i,
               !rst_ni)

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

  // The synchronized CT_Req_in and CT_Ack_in inputs carry pad data two cycles after the
  // registered CT_Req_in input enable rises; until then they carry the level of the disabled pad.
  logic       ct_req_in_din_en_q;
  logic [1:0] din_valid_q;
  logic       din_valid;
  `OCAH_FF(din_valid_q, {din_valid_q[0], ct_req_in_din_en_q}, 2'b00, clk_i, rst_ni)
  assign din_valid = din_valid_q[1];

  // A toggle-mode trigger is accepted only while the hold is inactive; a trigger during the hold
  // is discarded and does not restart it.
  logic stretched_pulse;
  logic toggle_accept;
  assign toggle_accept = mode_toggle & ct_src_i & ~stretched_pulse;

  // Pulse stretcher: the wire-OR output enable, and the hold after each toggle
  ctp_pulse_stretcher u_pulse_stretcher (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .pulse_i         (mode_toggle ? toggle_accept : ct_src_i),
    .stretch_mult_i  (stretch_mult_i),
    .stretched_pulse_o (stretched_pulse)
  );

  logic toggle_q;
  `OCAH_FF(toggle_q, toggle_q ^ toggle_accept, 1'b0, clk_i, rst_ni)

  // Toggle mode: ct_dst pulses on either edge of the synchronized CT_Req_in. The first valid
  // synchronized level after reset sets the reference and does not pulse.
  logic req_in_edge_pulse;
  ctp_edge_detector u_edge_detector (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .signal_i        (ct_req_in_din_sync_inv),
    .edge_pulse_o    (req_in_edge_pulse)
  );

  logic toggle_ct_dst;
  assign toggle_ct_dst = req_in_edge_pulse & din_valid;

  // Handshake controller for point-to-point mode
  logic handshake_ct_dst;
  logic handshake_ct_req_out;
  logic handshake_ct_ack_out;
  logic handshake_busy;

  ctp_handshake_ctrl u_handshake_ctrl (
    .clk_i              (clk_i),
    .rst_ni             (rst_ni),
    .ct_src_i           (ct_src_i & mode_p2p),
    .ct_dst_o           (handshake_ct_dst),
    .reset_i            (handshake_reset_i | ~mode_p2p),
    .ct_req_in_sync_i   (ct_req_in_din_sync_inv & din_valid),
    .ct_ack_in_sync_i   (ct_ack_in_din_sync_inv & din_valid),
    .ct_req_out_o       (handshake_ct_req_out),
    .ct_ack_out_o       (handshake_ct_ack_out),
    .busy_o             (handshake_busy)
  );

  // Wire-OR mode: ct_dst pulses on the falling (assertion) edge of ct_req_out_din.
  logic wire_or_ct_dst;
  logic wire_or_req_out_prev;
  `OCAH_FF(wire_or_req_out_prev, ct_req_out_din_sync_inv, 1'b0, clk_i, rst_ni)
  assign wire_or_ct_dst = ~ct_req_out_din_sync_inv & wire_or_req_out_prev;

  // Mode multiplexing for ct_dst output
  logic ct_dst_raw;
  assign ct_dst_raw = mode_wire_or ? wire_or_ct_dst :
                      mode_toggle  ? toggle_ct_dst  : handshake_ct_dst;

  // Register ct_dst output
  logic ct_dst_q;
  `OCAH_FF(ct_dst_q, ct_dst_raw, 1'b0, clk_i, rst_ni)
  assign ct_dst_o = ct_dst_q;

  // Wire-OR mode pad control
  logic wire_or_req_out_dout_en;
  logic wire_or_req_out_din_en;
  logic wire_or_req_out_dout;

  assign wire_or_req_out_dout_en = stretched_pulse;  // Enable output during stretched pulse
  assign wire_or_req_out_din_en  = 1'b1;            // Always enable input in wire-OR mode
  assign wire_or_req_out_dout    = invert_i ? 1'b1 : 1'b0;  // Static low (or high if inverted)

  // Point-to-Point mode pad control
  logic p2p_req_out_dout;
  logic p2p_ack_out_dout;

  assign p2p_req_out_dout    = invert_i ? ~handshake_ct_req_out : handshake_ct_req_out;
  assign p2p_ack_out_dout    = invert_i ? ~handshake_ct_ack_out : handshake_ct_ack_out;

  // Toggle mode pad control
  logic toggle_req_out_dout;
  assign toggle_req_out_dout = invert_i ? ~toggle_q : toggle_q;

  // Mode multiplexing for pad control signals. CT_Req_out is driven push-pull, and CT_Req_in
  // is an input, in both point-to-point and toggle mode; the CT_Ack pads are used only in
  // point-to-point mode.
  logic ct_req_out_dout_en_raw, ct_req_out_dout_en_q;
  logic ct_req_out_din_en_raw, ct_req_out_din_en_q;
  logic ct_req_out_dout_raw, ct_req_out_dout_q;
  logic ct_req_in_din_en_raw;
  logic ct_ack_in_din_en_raw, ct_ack_in_din_en_q;
  logic ct_ack_out_dout_en_raw, ct_ack_out_dout_en_q;
  logic ct_ack_out_dout_raw, ct_ack_out_dout_q;

  assign ct_req_out_dout_en_raw = mode_wire_or ? wire_or_req_out_dout_en : 1'b1;
  assign ct_req_out_din_en_raw  = mode_wire_or ? wire_or_req_out_din_en  : 1'b0;
  assign ct_req_out_dout_raw    = mode_wire_or ? wire_or_req_out_dout    :
                                  mode_toggle  ? toggle_req_out_dout     : p2p_req_out_dout;

  assign ct_req_in_din_en_raw   = ~mode_wire_or;
  assign ct_ack_in_din_en_raw   = mode_p2p;

  assign ct_ack_out_dout_en_raw = mode_p2p;
  assign ct_ack_out_dout_raw    = mode_p2p & p2p_ack_out_dout;

  // Register all pad control outputs
  `OCAH_FF(ct_req_out_dout_en_q, ct_req_out_dout_en_raw, 1'b0, clk_i, rst_ni)
  `OCAH_FF(ct_req_out_din_en_q, ct_req_out_din_en_raw, 1'b0, clk_i, rst_ni)
  `OCAH_FF(ct_req_out_dout_q, ct_req_out_dout_raw, 1'b0, clk_i, rst_ni)
  `OCAH_FF(ct_req_in_din_en_q, ct_req_in_din_en_raw, 1'b0, clk_i, rst_ni)
  `OCAH_FF(ct_ack_in_din_en_q, ct_ack_in_din_en_raw, 1'b0, clk_i, rst_ni)
  `OCAH_FF(ct_ack_out_dout_en_q, ct_ack_out_dout_en_raw, 1'b0, clk_i, rst_ni)
  `OCAH_FF(ct_ack_out_dout_q, ct_ack_out_dout_raw, 1'b0, clk_i, rst_ni)

  assign ct_req_out_dout_en_o = ct_req_out_dout_en_q;
  assign ct_req_out_din_en_o  = ct_req_out_din_en_q;
  assign ct_req_out_dout_o    = ct_req_out_dout_q;
  assign ct_req_in_din_en_o   = ct_req_in_din_en_q;
  assign ct_ack_in_din_en_o   = ct_ack_in_din_en_q;
  assign ct_ack_out_dout_en_o = ct_ack_out_dout_en_q;
  assign ct_ack_out_dout_o    = ct_ack_out_dout_q;

  // BUSY signal generation. In toggle mode the stretched pulse is the hold.
  logic busy_raw;
  assign busy_raw = mode_p2p ? handshake_busy : stretched_pulse;

  // Register BUSY output
  logic busy_q;
  `OCAH_FF(busy_q, busy_raw, 1'b0, clk_i, rst_ni)
  assign busy_o = busy_q;

  // Status outputs for CSR readback
  assign status_busy_o    = busy_q;
  assign status_req_out_o = invert_i ? ~ct_req_out_dout_q : ct_req_out_dout_q;
  assign status_ack_in_o = ct_ack_in_din_sync_inv;
  assign status_req_in_o = ct_req_in_din_sync_inv;
  assign status_ack_out_o = mode_p2p &
                            (invert_i ? ~ct_ack_out_dout_q : ct_ack_out_dout_q);

endmodule : cross_trigger_port_core
