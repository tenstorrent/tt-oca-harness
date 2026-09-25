// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Cross Trigger Network (CTN) IP-level testbench top for the cocotb flow.
//
// Pin-level shape: every DUT connection is an ANSI port so cocotb drives the
// inputs and samples the outputs directly (same convention as the DTP and
// sibling cross_trigger tb_tops). The shared AXI VIP's AXI4-Lite master
// binds to the flattened axil_* ports via AxiLiteBus.from_prefix(dut,
// "axil"); the adapter below repacks them into the pulp-platform req/resp
// structs the DUT expects. Clock and reset are driven from cocotb.
//
// Internal CTP mode split: the lower half of the internal CT ports runs in
// wire-OR (pulse) mode and the upper half in point-to-point (handshake)
// mode, so both internal signal shapes are exercised in one build.
//
// Every CT_Req_out pad sits on an open-drain shared wire (ocah_open_drain_bus).
// A pad outside ctp_wire_group has a private wire with one bench-side chiplet
// driver; the pads inside the group share one wire, together with their
// chiplet drivers. cocotb sets each wire's pull and the drivers and observes
// the resolved wires, and each port's receive pulse is exposed for cycle
// checks. In point-to-point mode a pad is push-pull and the core ignores the
// pad input, so the wire model has no effect there.

`timescale 1ns / 1ps

module cross_trigger_network_tb_top
  import cross_trigger_network_pkg::*;
(
  input  wire                                clk,
  input  wire                                rst_n,

  // AXI4-Lite management port (flattened, VIP master side)
  input  wire                                axil_awvalid,
  input  wire [31:0]                         axil_awaddr,
  input  wire [2:0]                          axil_awprot,
  output wire                                axil_awready,

  input  wire                                axil_wvalid,
  input  wire [31:0]                         axil_wdata,
  input  wire [3:0]                          axil_wstrb,
  output wire                                axil_wready,

  input  wire                                axil_bready,
  output wire                                axil_bvalid,
  output wire [1:0]                          axil_bresp,

  input  wire                                axil_arvalid,
  input  wire [31:0]                         axil_araddr,
  input  wire [2:0]                          axil_arprot,
  output wire                                axil_arready,

  input  wire                                axil_rready,
  output wire                                axil_rvalid,
  output wire [31:0]                         axil_rdata,
  output wire [1:0]                          axil_rresp,

  // Clock stop control interface
  input  wire [DEFAULT_NUM_CLK_STOP_REQ-1:0] clk_stop_req,
  input  wire                                jtag_clock_stop,
  output wire                                stop_clks,
  output wire                                cla_clock_stop,

  // Internal cross trigger interface (CLA side of the internal CT ports)
  output wire [DEFAULT_NUM_INT_CT-1:0]       ctm_src_req,
  input  wire [DEFAULT_NUM_INT_CT-1:0]       ctm_src_ack,
  input  wire [DEFAULT_NUM_INT_CT-1:0]       ctm_dst_req,
  output wire [DEFAULT_NUM_INT_CT-1:0]       ctm_dst_ack,

  // External CTP GPIO pad interface - CT_Req_out, and the shared wires the
  // pads sit on (pull per private wire, chiplet driver per pad, group mask
  // and group pull, resolved wire per pad, pull-mismatch flag per pad)
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_req_out_dout,
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_req_out_dout_en,
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_req_out_din,
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_req_out_din_en,
  input  wire [DEFAULT_NUM_CTP-1:0]          ctp_wire_pull,
  input  wire [DEFAULT_NUM_CTP-1:0]          ctp_wire_ext_assert,
  input  wire [DEFAULT_NUM_CTP-1:0]          ctp_wire_group,
  input  wire                                ctp_wire_group_pull,
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_wire_mismatch,

  // Receive pulses of the external and internal ports inside the DUT
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_ct_dst,
  output wire [DEFAULT_NUM_INT_CT-1:0]       int_ct_dst,

  // External CTP GPIO pad interface - CT_Req_in
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_req_in_dout,
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_req_in_dout_en,
  input  wire [DEFAULT_NUM_CTP-1:0]          ctp_req_in_din,
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_req_in_din_en,

  // External CTP GPIO pad interface - CT_Ack_in
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_ack_in_dout,
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_ack_in_dout_en,
  input  wire [DEFAULT_NUM_CTP-1:0]          ctp_ack_in_din,
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_ack_in_din_en,

  // External CTP GPIO pad interface - CT_Ack_out
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_ack_out_dout,
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_ack_out_dout_en,
  input  wire [DEFAULT_NUM_CTP-1:0]          ctp_ack_out_din,
  output wire [DEFAULT_NUM_CTP-1:0]          ctp_ack_out_din_en
);

  // Internal CTP mode split: lower half wire-OR (0), upper half P2P (1).
  localparam int unsigned NumIntCtWireOr = DEFAULT_NUM_INT_CT / 2;
  localparam int unsigned NumIntCtP2p = DEFAULT_NUM_INT_CT - NumIntCtWireOr;
  localparam logic [DEFAULT_NUM_INT_CT-1:0] IntCtMode = {
    {NumIntCtP2p{1'b1}}, {NumIntCtWireOr{1'b0}}
  };

  ctn_axil_req_t  axil_req;
  ctn_axil_resp_t axil_resp;

  // Shared wires: one private wire per pad, one wire for the group. A chiplet
  // driver pulls towards the level opposite its wire's pull.
  logic [DEFAULT_NUM_CTP-1:0] private_wire;
  logic [DEFAULT_NUM_CTP-1:0] private_mismatch;
  logic                       group_wire;
  logic                       group_mismatch;

  for (genvar i = 0; i < DEFAULT_NUM_CTP; i++) begin : gen_private_wire
    ocah_open_drain_bus #(
      .NumDrivers(2)
    ) u_wire (
      .pull_i     (ctp_wire_pull[i]),
      .dout_i     ({~ctp_wire_pull[i], ctp_req_out_dout[i]}),
      .dout_en_i  ({ctp_wire_ext_assert[i], ctp_req_out_dout_en[i]} & {2{~ctp_wire_group[i]}}),
      .wire_o     (private_wire[i]),
      .mismatch_o (private_mismatch[i])
    );
    assign ctp_req_out_din[i]   = ctp_wire_group[i] ? group_wire : private_wire[i];
    assign ctp_wire_mismatch[i] = ctp_wire_group[i] ? group_mismatch : private_mismatch[i];
    assign ctp_ct_dst[i]        = u_dut.gen_ext_ctp[i].u_ctp.ct_dst_o;
  end

  ocah_open_drain_bus #(
    .NumDrivers(2 * DEFAULT_NUM_CTP)
  ) u_group_wire (
    .pull_i     (ctp_wire_group_pull),
    .dout_i     ({{DEFAULT_NUM_CTP{~ctp_wire_group_pull}}, ctp_req_out_dout}),
    .dout_en_i  ({ctp_wire_ext_assert & ctp_wire_group, ctp_req_out_dout_en & ctp_wire_group}),
    .wire_o     (group_wire),
    .mismatch_o (group_mismatch)
  );

  for (genvar i = 0; i < DEFAULT_NUM_INT_CT; i++) begin : gen_int_ct_dst
    assign int_ct_dst[i] = u_dut.gen_int_ctp[i].u_int_ctp_core.ct_dst_o;
  end

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

  cross_trigger_network #(
    .INT_CT_MODE(IntCtMode)
  ) u_dut (
    .clk_i                 (clk),
    .rst_ni                (rst_n),

    .axil_req_i            (axil_req),
    .axil_resp_o           (axil_resp),

    .clk_stop_req_i        (clk_stop_req),
    .jtag_clock_stop_i     (jtag_clock_stop),
    .stop_clks_o           (stop_clks),
    .cla_clock_stop_o      (cla_clock_stop),

    .ctm_src_req_o         (ctm_src_req),
    .ctm_src_ack_i         (ctm_src_ack),
    .ctm_dst_req_i         (ctm_dst_req),
    .ctm_dst_ack_o         (ctm_dst_ack),

    .ctp_req_out_dout_o    (ctp_req_out_dout),
    .ctp_req_out_dout_en_o (ctp_req_out_dout_en),
    .ctp_req_out_din_i     (ctp_req_out_din),
    .ctp_req_out_din_en_o  (ctp_req_out_din_en),

    .ctp_req_in_dout_o     (ctp_req_in_dout),
    .ctp_req_in_dout_en_o  (ctp_req_in_dout_en),
    .ctp_req_in_din_i      (ctp_req_in_din),
    .ctp_req_in_din_en_o   (ctp_req_in_din_en),

    .ctp_ack_in_dout_o     (ctp_ack_in_dout),
    .ctp_ack_in_dout_en_o  (ctp_ack_in_dout_en),
    .ctp_ack_in_din_i      (ctp_ack_in_din),
    .ctp_ack_in_din_en_o   (ctp_ack_in_din_en),

    .ctp_ack_out_dout_o    (ctp_ack_out_dout),
    .ctp_ack_out_dout_en_o (ctp_ack_out_dout_en),
    .ctp_ack_out_din_i     (ctp_ack_out_din),
    .ctp_ack_out_din_en_o  (ctp_ack_out_din_en)
  );

endmodule : cross_trigger_network_tb_top
