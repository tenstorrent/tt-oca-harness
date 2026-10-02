// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Cross Trigger Matrix (CTM) IP-level testbench top for the cocotb flow.
//
// Pin-level shape: every DUT connection is an ANSI port so cocotb drives the
// inputs and samples the outputs directly (same convention as the DTP and
// cross_trigger_port tb_tops). The shared AXI VIP's AXI4-Lite master binds
// to the flattened axil_* ports via AxiLiteBus.from_prefix(dut, "axil"); the
// adapter below repacks them into the pulp-platform req/resp structs the DUT
// expects. The matrix geometry (NumCtDst x NumCtSrc) comes from the
// register-map-derived package localparams. Clock and reset are driven from
// cocotb.

`timescale 1ns / 1ps

module cross_trigger_matrix_tb_top
  import cross_trigger_matrix_pkg::*;
(
  input  wire                   clk,
  input  wire                   rst_n,

  // AXI4-Lite management port (flattened, VIP master side)
  input  wire                   axil_awvalid,
  input  wire [31:0]            axil_awaddr,
  input  wire [2:0]             axil_awprot,
  output wire                   axil_awready,

  input  wire                   axil_wvalid,
  input  wire [31:0]            axil_wdata,
  input  wire [3:0]             axil_wstrb,
  output wire                   axil_wready,

  input  wire                   axil_bready,
  output wire                   axil_bvalid,
  output wire [1:0]             axil_bresp,

  input  wire                   axil_arvalid,
  input  wire [31:0]            axil_araddr,
  input  wire [2:0]             axil_arprot,
  output wire                   axil_arready,

  input  wire                   axil_rready,
  output wire                   axil_rvalid,
  output wire [31:0]            axil_rdata,
  output wire [1:0]             axil_rresp,

  // Cross trigger destination inputs (sources for the matrix)
  input  wire [NumCtDst-1:0]  ct_dst,

  // Cross trigger source outputs (sinks for the matrix)
  output wire [NumCtSrc-1:0]  ct_src
);

  ctm_axil_req_t  axil_req;
  ctm_axil_resp_t axil_resp;

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

  cross_trigger_matrix u_dut (
    .clk_i       (clk),
    .rst_ni      (rst_n),

    .axil_req_i  (axil_req),
    .axil_resp_o (axil_resp),

    .ct_dst_i    (ct_dst),
    .ct_src_o    (ct_src)
  );

endmodule : cross_trigger_matrix_tb_top
