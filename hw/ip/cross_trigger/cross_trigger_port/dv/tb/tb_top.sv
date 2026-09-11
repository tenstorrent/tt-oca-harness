// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Cross Trigger Port (CTP) IP-level testbench top for the cocotb flow.
//
// Pin-level shape: every DUT connection is an ANSI port so cocotb drives the
// inputs and samples the outputs directly (same convention as the DTP
// tb_top). The shared AXI VIP's AXI4-Lite master binds to the flattened
// axil_* ports via AxiLiteBus.from_prefix(dut, "axil"); the adapter below
// repacks them into the pulp-platform req/resp structs the DUT expects.
// Clock and reset are driven from cocotb.

`timescale 1ns / 1ps

module cross_trigger_port_tb_top
  import cross_trigger_port_pkg::*;
(
  input  wire        clk,
  input  wire        rst_n,

  // AXI4-Lite management port (flattened, VIP master side)
  input  wire        axil_awvalid,
  input  wire [31:0] axil_awaddr,
  input  wire [2:0]  axil_awprot,
  output wire        axil_awready,

  input  wire        axil_wvalid,
  input  wire [31:0] axil_wdata,
  input  wire [3:0]  axil_wstrb,
  output wire        axil_wready,

  input  wire        axil_bready,
  output wire        axil_bvalid,
  output wire [1:0]  axil_bresp,

  input  wire        axil_arvalid,
  input  wire [31:0] axil_araddr,
  input  wire [2:0]  axil_arprot,
  output wire        axil_arready,

  input  wire        axil_rready,
  output wire        axil_rvalid,
  output wire [31:0] axil_rdata,
  output wire [1:0]  axil_rresp,

  // Core-side cross trigger interface
  input  wire        ct_src,
  output wire        ct_dst,
  output wire        busy,

  // GPIO pad interface - CT_Req_out
  output wire        ct_req_out_dout_en,
  output wire        ct_req_out_din_en,
  output wire        ct_req_out_dout,
  input  wire        ct_req_out_din,

  // GPIO pad interface - CT_Req_in (point-to-point mode only)
  output wire        ct_req_in_din_en,
  input  wire        ct_req_in_din,

  // GPIO pad interface - CT_Ack_in (point-to-point mode only)
  output wire        ct_ack_in_din_en,
  input  wire        ct_ack_in_din,

  // GPIO pad interface - CT_Ack_out (point-to-point mode only)
  output wire        ct_ack_out_dout_en,
  output wire        ct_ack_out_dout
);

  ctp_axil_req_t  axil_req;
  ctp_axil_resp_t axil_resp;

  assign axil_req.aw_valid = axil_awvalid;
  assign axil_req.aw.addr  = axil_awaddr;
  assign axil_req.aw.prot  = axil_awprot;
  assign axil_awready      = axil_resp.aw_ready;

  assign axil_req.w_valid  = axil_wvalid;
  assign axil_req.w.data   = axil_wdata;
  assign axil_req.w.strb   = axil_wstrb;
  assign axil_wready       = axil_resp.w_ready;

  assign axil_req.b_ready  = axil_bready;
  assign axil_bvalid       = axil_resp.b_valid;
  assign axil_bresp        = axil_resp.b.resp;

  assign axil_req.ar_valid = axil_arvalid;
  assign axil_req.ar.addr  = axil_araddr;
  assign axil_req.ar.prot  = axil_arprot;
  assign axil_arready      = axil_resp.ar_ready;

  assign axil_req.r_ready  = axil_rready;
  assign axil_rvalid       = axil_resp.r_valid;
  assign axil_rdata        = axil_resp.r.data;
  assign axil_rresp        = axil_resp.r.resp;

  cross_trigger_port u_dut (
    .clk_i                (clk),
    .rst_ni               (rst_n),

    .axil_req_i           (axil_req),
    .axil_resp_o          (axil_resp),

    .ct_src_i             (ct_src),
    .ct_dst_o             (ct_dst),
    .busy_o               (busy),

    .ct_req_out_dout_en_o (ct_req_out_dout_en),
    .ct_req_out_din_en_o  (ct_req_out_din_en),
    .ct_req_out_dout_o    (ct_req_out_dout),
    .ct_req_out_din_i     (ct_req_out_din),

    .ct_req_in_din_en_o   (ct_req_in_din_en),
    .ct_req_in_din_i      (ct_req_in_din),

    .ct_ack_in_din_en_o   (ct_ack_in_din_en),
    .ct_ack_in_din_i      (ct_ack_in_din),

    .ct_ack_out_dout_en_o (ct_ack_out_dout_en),
    .ct_ack_out_dout_o    (ct_ack_out_dout)
  );

endmodule : cross_trigger_port_tb_top
