// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Bridge core cross-trigger pulses to GPIO pads in wire-OR or point-to-point mode with AXI-Lite
// CSRs.
//
// Wraps cross_trigger_port_core; CSRs program mode, invert, stretch, and handshake reset.
// ct_src_i is the synchronous core source pulse; ct_dst_o is the registered destination
// pulse; busy_o marks a transfer in progress.
// Pad ports cover CT_Req_out/in and CT_Ack_in/out with dout, dout_en, din, and din_en as
// required by mode.
// The CSR MODE field selects wire-OR at 0 and point-to-point at 1; it resets to wire-OR.

module cross_trigger_port #(
  parameter type axil_req_t = cross_trigger_port_pkg::ctp_axil_req_t,  // CTP AXI-Lite request type.
  parameter type axil_resp_t = cross_trigger_port_pkg::ctp_axil_resp_t  // CTP AXI-Lite response type.
) (
  input  logic        clk_i,            // System clock for the AXI-Lite CSRs and the port logic.
  input  logic        rst_ni,           // Active-low asynchronous system reset.

  input  axil_req_t   axil_req_i,       // AXI-Lite CSR request; only address bits [3:0] are
                                        // decoded.
  output axil_resp_t  axil_resp_o,      // AXI-Lite CSR response.

  input  logic        ct_src_i,         // Core-side cross-trigger pulse to transmit, synchronous to
                                        // clk_i.
  output logic        ct_dst_o,         // Core-side received cross-trigger pulse, registered.
  output logic        busy_o,           // High while the stretched pulse is active in wire-OR mode,
                                        // or while the outgoing or incoming handshake is active in
                                        // point-to-point mode. Optional; leave unconnected when
                                        // unused.

  output logic        ct_req_out_dout_en_o,  // Output enable for the CT_Req_out pad. Follows the
                                             // stretched outgoing pulse in wire-OR mode; high in
                                             // point-to-point mode.
  output logic        ct_req_out_din_en_o,  // Input enable for the CT_Req_out pad.
                                            // High in wire-OR mode; low in point-to-point mode.
  output logic        ct_req_out_dout_o,  // Output data for the CT_Req_out pad. Carries the
                                          // outgoing handshake request in point-to-point mode. Held
                                          // low in wire-OR mode, or high when the CSR INVERT field
                                          // is set.
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
  output logic        ct_ack_out_dout_o  // Output data for the CT_Ack_out pad. Acknowledges the
                                         // synchronized CT_Req_in request in point-to-point mode;
                                         // held low in wire-OR mode.
);

  import cross_trigger_port_pkg::MODE_WIRE_OR;

  // Register interface
  cross_trigger_port_reg_pkg::cross_trigger_port__in_t  reg_in;
  cross_trigger_port_reg_pkg::cross_trigger_port__out_t reg_out;

  // Register module instantiation - wire AXI-Lite structs directly
  cross_trigger_port_reg u_reg (
    .clk           (clk_i),
    .arst_n        (rst_ni),

    // Write address channel
    .s_axil_awready (axil_resp_o.aw_ready),
    .s_axil_awvalid (axil_req_i.aw_valid),
    .s_axil_awaddr  (axil_req_i.aw.addr[3:0]),
    .s_axil_awprot  (axil_req_i.aw.prot),

    // Write data channel
    .s_axil_wready  (axil_resp_o.w_ready),
    .s_axil_wvalid  (axil_req_i.w_valid),
    .s_axil_wdata   (axil_req_i.w.data),
    .s_axil_wstrb   (axil_req_i.w.strb),

    // Write response channel
    .s_axil_bready  (axil_req_i.b_ready),
    .s_axil_bvalid  (axil_resp_o.b_valid),
    .s_axil_bresp   (axil_resp_o.b.resp),

    // Read address channel
    .s_axil_arready (axil_resp_o.ar_ready),
    .s_axil_arvalid (axil_req_i.ar_valid),
    .s_axil_araddr  (axil_req_i.ar.addr[3:0]),
    .s_axil_arprot  (axil_req_i.ar.prot),

    // Read data channel
    .s_axil_rready  (axil_req_i.r_ready),
    .s_axil_rvalid  (axil_resp_o.r_valid),
    .s_axil_rdata   (axil_resp_o.r.data),
    .s_axil_rresp   (axil_resp_o.r.resp),

    .hwif_in       (reg_in),
    .hwif_out      (reg_out)
  );

  // Configuration signals from registers
  logic mode_wire_or;
  logic invert;
  logic handshake_reset;

  assign mode_wire_or   = (reg_out.CONFIG.MODE.value == MODE_WIRE_OR);
  assign invert         = reg_out.CONFIG.INVERT.value;
  assign handshake_reset = reg_out.CONFIG.RESET.value;

  // Core module instantiation
  cross_trigger_port_core u_core (
    .clk_i                  (clk_i),
    .rst_ni                 (rst_ni),
    .mode_wire_or_i         (mode_wire_or),
    .invert_i               (invert),
    .handshake_reset_i      (handshake_reset),
    .stretch_mult_i         (reg_out.STRETCH_MULT.STRETCH_MULT.value),
    .ct_src_i               (ct_src_i),
    .ct_dst_o               (ct_dst_o),
    .busy_o                 (busy_o),
    .ct_req_out_dout_en_o   (ct_req_out_dout_en_o),
    .ct_req_out_din_en_o    (ct_req_out_din_en_o),
    .ct_req_out_dout_o      (ct_req_out_dout_o),
    .ct_req_out_din_i       (ct_req_out_din_i),
    .ct_req_in_din_en_o     (ct_req_in_din_en_o),
    .ct_req_in_din_i        (ct_req_in_din_i),
    .ct_ack_in_din_en_o     (ct_ack_in_din_en_o),
    .ct_ack_in_din_i        (ct_ack_in_din_i),
    .ct_ack_out_dout_en_o   (ct_ack_out_dout_en_o),
    .ct_ack_out_dout_o      (ct_ack_out_dout_o),
    .status_busy_o          (reg_in.STATUS.BUSY.next),
    .status_req_out_o       (reg_in.STATUS.REQ_OUT.next),
    .status_ack_in_o        (reg_in.STATUS.ACK_IN.next),
    .status_req_in_o        (reg_in.STATUS.REQ_IN.next),
    .status_ack_out_o       (reg_in.STATUS.ACK_OUT.next)
  );

endmodule : cross_trigger_port
