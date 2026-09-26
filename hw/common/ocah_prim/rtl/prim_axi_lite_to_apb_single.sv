// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Bridge one AXI-Lite manager to a single APB subordinate.
//
// Complete addresses outside [ADDR_START, ADDR_END) with a decode error on AXI-Lite.
// PipelineRequest and PipelineResponse insert skid registers on the request and response
// paths.
// Hold only one APB transfer in flight at a time.

module prim_axi_lite_to_apb_single #(
  parameter bit PipelineRequest      = 1'b0,  // Skid-registers the AXI-Lite to APB request path.
  parameter bit PipelineResponse     = 1'b0,  // Skid-registers the APB to AXI-Lite response path.
  parameter int unsigned AXI_DATA_WIDTH = 32,  // Shared data width.
  parameter int unsigned AXI_ADDR_WIDTH = 32,  // Shared address width.

  parameter bit [AXI_ADDR_WIDTH-1:0] ADDR_START = 32'h0,  // Inclusive APB decode base.
  parameter bit [AXI_ADDR_WIDTH:0]   ADDR_END   = 33'h0,  // Exclusive APB decode limit.

  localparam type addr_t = logic [AXI_ADDR_WIDTH-1:0],  // Address type alias.
  localparam type data_t = logic [AXI_DATA_WIDTH-1:0],  // Data type alias.
  localparam type strb_t = logic [AXI_DATA_WIDTH/8-1:0]  // Strobe type alias.
) (
  input logic clk_i,  // Clock shared by the AXI-Lite and APB sides of the bridge.
  input logic rst_ni,  // Async reset, active-low.

  input  logic            axi_lite_awvalid_i,  // Write-address valid from the AXI-Lite manager.
  input  addr_t           axi_lite_awaddr_i,  // Write byte address, decoded against [ADDR_START,
                                              // ADDR_END).
  input  axi_pkg::prot_t  axi_lite_awprot_i,  // Write protection attributes, forwarded to pprot_o.
  output logic            axi_lite_awready_o,  // Write-address ready to the AXI-Lite manager.
  input  logic            axi_lite_wvalid_i,  // Write-data valid from the AXI-Lite manager.
  input  data_t           axi_lite_wdata_i,  // Write data, forwarded to pwdata_o.
  input  strb_t           axi_lite_wstrb_i,  // Write byte strobes, forwarded to pstrb_o.
  output logic            axi_lite_wready_o,  // Write-data ready to the AXI-Lite manager.
  output logic            axi_lite_bvalid_o,  // Write-response valid to the AXI-Lite manager.
  output axi_pkg::resp_t  axi_lite_bresp_o,  // Write response; SLVERR on pslverr_i, DECERR outside the decode range.
  input  logic            axi_lite_bready_i,  // Write-response ready from the AXI-Lite manager.
  input  logic            axi_lite_arvalid_i,  // Read-address valid from the AXI-Lite manager.
  input  addr_t           axi_lite_araddr_i,  // Read byte address, decoded against [ADDR_START, ADDR_END).
  input  axi_pkg::prot_t  axi_lite_arprot_i,  // Read protection attributes, forwarded to pprot_o.
  output logic            axi_lite_arready_o,  // Read-address ready to the AXI-Lite manager.
  output logic            axi_lite_rvalid_o,  // Read-data valid to the AXI-Lite manager.
  output data_t           axi_lite_rdata_o,  // Read data returned from prdata_i.
  output axi_pkg::resp_t  axi_lite_rresp_o,  // Read response; SLVERR on pslverr_i, DECERR outside the decode range.
  input  logic            axi_lite_rready_i,  // Read-data ready from the AXI-Lite manager.

  output logic       psel_o,  // APB PSEL.
  output logic       penable_o,  // APB PENABLE.
  output logic       pwrite_o,  // APB PWRITE.
  output addr_t      paddr_o,  // APB PADDR.
  output data_t      pwdata_o,  // APB PWDATA.
  output strb_t      pstrb_o,  // APB PSTRB.
  output logic [2:0] pprot_o,  // APB PPROT.
  input  logic       pready_i,  // APB PREADY.
  input  logic       pslverr_i,  // APB PSLVERR.
  input  data_t      prdata_i  // APB PRDATA.
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
  ) u_axi_lite_to_apb (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .slv(axi_lite),
    .paddr_o(paddr_out),
    .pprot_o(pprot_o),
    .pselx_o(psel_o),
    .penable_o(penable_o),
    .pwrite_o(pwrite_o),
    .pwdata_o(pwdata_o),
    .pstrb_o(pstrb_o),
    .pready_i(pready_i),
    .prdata_i(prdata_i),
    .pslverr_i(pslverr_i),
    .addr_map_i(ApbRuleT)
  );

  assign paddr_o = paddr_out[AXI_ADDR_WIDTH-1:0];

  // assign IOs to interface
  assign axi_lite.aw_valid = axi_lite_awvalid_i;
  assign axi_lite.aw_addr = {1'b0, axi_lite_awaddr_i};
  assign axi_lite.aw_prot = axi_lite_awprot_i;
  assign axi_lite.w_valid = axi_lite_wvalid_i;
  assign axi_lite.w_data = axi_lite_wdata_i;
  assign axi_lite.w_strb = axi_lite_wstrb_i;
  assign axi_lite.b_ready = axi_lite_bready_i;
  assign axi_lite.ar_valid = axi_lite_arvalid_i;
  assign axi_lite.ar_addr = {1'b0, axi_lite_araddr_i};
  assign axi_lite.ar_prot = axi_lite_arprot_i;
  assign axi_lite.r_ready = axi_lite_rready_i;

  assign axi_lite_awready_o = axi_lite.aw_ready;
  assign axi_lite_wready_o = axi_lite.w_ready;
  assign axi_lite_bvalid_o = axi_lite.b_valid;
  assign axi_lite_bresp_o = axi_lite.b_resp;
  assign axi_lite_arready_o = axi_lite.ar_ready;
  assign axi_lite_rvalid_o = axi_lite.r_valid;
  assign axi_lite_rdata_o = axi_lite.r_data;
  assign axi_lite_rresp_o = axi_lite.r_resp;

endmodule : prim_axi_lite_to_apb_single
