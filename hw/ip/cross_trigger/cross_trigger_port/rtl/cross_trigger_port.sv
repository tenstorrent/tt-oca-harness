// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Cross Trigger Port Top Module
//
// Description:
// Top-level module for the Cross Trigger Port IP. Supports both Wire-OR and
// Point-to-Point modes for inter-chiplet cross triggering via GPIO pads.
//------------------------------------------------------------------------------


module cross_trigger_port #(
  // Parameterized AXI-Lite bus interface types (default logic to force explicit definition)
  parameter type axil_req_t = cross_trigger_port_pkg::ctp_axil_req_t,
  parameter type axil_resp_t = cross_trigger_port_pkg::ctp_axil_resp_t
) (
  // Global Interface
  input  logic        clk_i,
  input  logic        rst_ni,

  // AXI4-Lite Register Interface
  input  axil_req_t   axil_req_i,
  output axil_resp_t  axil_resp_o,

  // Core-side cross trigger interface
  input  logic        ct_src_i,      // Cross trigger source pulse (synchronous)
  output logic        ct_dst_o,       // Cross trigger destination pulse (registered)
  output logic        busy_o,         // Optional: transfer in progress

  // GPIO pad interface - CT_Req_out
  output logic        ct_req_out_dout_en_o,  // Output enable for CT_Req_out pad
  output logic        ct_req_out_din_en_o,   // Input enable for CT_Req_out pad
  output logic        ct_req_out_dout_o,     // Output data for CT_Req_out pad
  input  logic        ct_req_out_din_i,      // Input data from CT_Req_out pad

  // GPIO pad interface - CT_Req_in (point-to-point mode only)
  output logic        ct_req_in_din_en_o,    // Input enable for CT_Req_in pad
  input  logic        ct_req_in_din_i,       // Input data from CT_Req_in pad

  // GPIO pad interface - CT_Ack_in (point-to-point mode only)
  output logic        ct_ack_in_din_en_o,     // Input enable for CT_Ack_in pad
  input  logic        ct_ack_in_din_i,       // Input data from CT_Ack_in pad

  // GPIO pad interface - CT_Ack_out (point-to-point mode only)
  output logic        ct_ack_out_dout_en_o,  // Output enable for CT_Ack_out pad
  output logic        ct_ack_out_dout_o       // Output data for CT_Ack_out pad
);

  import cross_trigger_port_reg_pkg::*;
  import cross_trigger_port_pkg::*;

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
