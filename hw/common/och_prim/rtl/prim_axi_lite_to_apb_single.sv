// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// AXI-Lite to APB Single Bridge
//
//--------------------------------------------------
module prim_axi_lite_to_apb_single #(
  parameter bit PipelineRequest      = 1'b0,   // Pipeline request path
  parameter bit PipelineResponse     = 1'b0,   // Pipeline response path
  parameter int unsigned AXI_DATA_WIDTH = 32,
  parameter int unsigned AXI_ADDR_WIDTH = 32,

  parameter bit [AXI_ADDR_WIDTH-1:0] ADDR_START = 32'h0,
  parameter bit [AXI_ADDR_WIDTH:0]   ADDR_END   = 33'h0,

  localparam type addr_t = logic [AXI_ADDR_WIDTH-1:0],
  localparam type data_t = logic [AXI_DATA_WIDTH-1:0],
  localparam type strb_t = logic [AXI_DATA_WIDTH/8-1:0]
) (
  input logic i_clk,
  input logic i_reset_n,

  input  logic            i_axi_lite_awvalid,
  input  addr_t           i_axi_lite_awaddr,
  input  axi_pkg::prot_t  i_axi_lite_awprot,
  output logic            o_axi_lite_awready,
  input  logic            i_axi_lite_wvalid,
  input  data_t           i_axi_lite_wdata,
  input  strb_t           i_axi_lite_wstrb,
  output logic            o_axi_lite_wready,
  output logic            o_axi_lite_bvalid,
  output axi_pkg::resp_t  o_axi_lite_bresp,
  input  logic            i_axi_lite_bready,
  input  logic            i_axi_lite_arvalid,
  input  addr_t           i_axi_lite_araddr,
  input  axi_pkg::prot_t  i_axi_lite_arprot,
  output logic            o_axi_lite_arready,
  output logic            o_axi_lite_rvalid,
  output data_t           o_axi_lite_rdata,
  output axi_pkg::resp_t  o_axi_lite_rresp,
  input  logic            i_axi_lite_rready,

  output logic       o_psel,
  output logic       o_penable,
  output logic       o_pwrite,
  output addr_t      o_paddr,
  output data_t      o_pwdata,
  output strb_t      o_pstrb,
  output logic [2:0] o_pprot,
  input  logic       i_pready,
  input  logic       i_pslverr,
  input  data_t      i_prdata
);

  localparam int unsigned EXTENDED_ADDR_WIDTH = AXI_ADDR_WIDTH + 1;

  logic [EXTENDED_ADDR_WIDTH-1:0] paddr_out;

  AXI_LITE #(
    .AXI_DATA_WIDTH(AXI_DATA_WIDTH),
    .AXI_ADDR_WIDTH(EXTENDED_ADDR_WIDTH)
  ) axi_lite ();

  typedef struct packed {
    int unsigned idx;
    logic [EXTENDED_ADDR_WIDTH-1:0] start_addr;
    logic [EXTENDED_ADDR_WIDTH-1:0] end_addr;
  } rule_t;

  localparam rule_t [0:0] ApbRuleT = '{
      '{idx: 32'd0, start_addr: {1'b0, ADDR_START}, end_addr: ADDR_END}  // reset_unit
  };

  axi_lite_to_apb_intf #(
    .NoApbSlaves(1),
    .NoRules(1),
    .AddrWidth(EXTENDED_ADDR_WIDTH),
    .DataWidth(AXI_DATA_WIDTH),
    .PipelineRequest(PipelineRequest),
    .PipelineResponse(PipelineResponse),
    .rule_t(rule_t)
  ) axi_lite_to_apb (
    .clk_i(i_clk),
    .rst_ni(i_reset_n),
    .slv(axi_lite),
    .paddr_o(paddr_out),
    .pprot_o(o_pprot),
    .pselx_o(o_psel),
    .penable_o(o_penable),
    .pwrite_o(o_pwrite),
    .pwdata_o(o_pwdata),
    .pstrb_o(o_pstrb),
    .pready_i(i_pready),
    .prdata_i(i_prdata),
    .pslverr_i(i_pslverr),
    .addr_map_i(ApbRuleT)
  );

  assign o_paddr = paddr_out[AXI_ADDR_WIDTH-1:0];

  // assign IOs to interface
  assign axi_lite.aw_valid = i_axi_lite_awvalid;
  assign axi_lite.aw_addr = {1'b0, i_axi_lite_awaddr};
  assign axi_lite.aw_prot = i_axi_lite_awprot;
  assign axi_lite.w_valid = i_axi_lite_wvalid;
  assign axi_lite.w_data = i_axi_lite_wdata;
  assign axi_lite.w_strb = i_axi_lite_wstrb;
  assign axi_lite.b_ready = i_axi_lite_bready;
  assign axi_lite.ar_valid = i_axi_lite_arvalid;
  assign axi_lite.ar_addr = {1'b0, i_axi_lite_araddr};
  assign axi_lite.ar_prot = i_axi_lite_arprot;
  assign axi_lite.r_ready = i_axi_lite_rready;

  assign o_axi_lite_awready = axi_lite.aw_ready;
  assign o_axi_lite_wready = axi_lite.w_ready;
  assign o_axi_lite_bvalid = axi_lite.b_valid;
  assign o_axi_lite_bresp = axi_lite.b_resp;
  assign o_axi_lite_arready = axi_lite.ar_ready;
  assign o_axi_lite_rvalid = axi_lite.r_valid;
  assign o_axi_lite_rdata = axi_lite.r_data;
  assign o_axi_lite_rresp = axi_lite.r_resp;

endmodule : prim_axi_lite_to_apb_single
