// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// APB to AXI-Lite Bridge
//
//--------------------------------------------------
// Wraps axi_lite_from_mem with an APB-to-mem shim.

`include "apb/typedef.svh"
`include "axi/typedef.svh"

module apb2axil #(
  parameter int unsigned ADDR_WIDTH = 32,  // AXI address width
  parameter int unsigned MEM_ADDR_WIDTH = ADDR_WIDTH,  // APB/mem address width (may be narrower)
  parameter int unsigned DATA_WIDTH = 32,
  parameter bit [2:0] AXI_PROT_VALUE = 3'b000,  // AXI prot bits for all transactions
  parameter type apb_req_t = logic,  // APB request struct type
  parameter type apb_resp_t = logic,  // APB response struct type
  parameter type axi_req_t = logic,  // AXI-Lite request struct type
  parameter type axi_resp_t = logic  // AXI-Lite response struct type
) (
  input logic clk_i,
  input logic rst_ni,

  // APB Slave Interface (struct-based)
  input  apb_req_t  apb_req_i,
  output apb_resp_t apb_resp_o,

  // AXI-Lite Master Interface (struct-based)
  output axi_req_t  axi_req_o,
  input  axi_resp_t axi_resp_i
);

  logic mem_req;
  logic mem_gnt;
  // APB holds psel & penable high for the whole ACCESS phase (until pready), but
  // axi_lite_from_mem expects mem_req to drop after grant. Track the grant so mem_req
  // is asserted only until granted, else the req would stay high after grant (waiting
  // for pready) and violate the from_mem request-stability assertion when penable drops.
  logic apb_granted_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      apb_granted_q <= 1'b0;
    end else if (mem_gnt) begin
      apb_granted_q <= 1'b1;
    end else if (!apb_req_i.psel || !apb_req_i.penable) begin
      apb_granted_q <= 1'b0;
    end
  end

  assign mem_req = apb_req_i.psel & apb_req_i.penable & ~apb_granted_q;

  axi_lite_from_mem #(
    .MemAddrWidth(MEM_ADDR_WIDTH),
    .AxiAddrWidth(ADDR_WIDTH),
    .DataWidth   (DATA_WIDTH),
    .MaxRequests (1),
    .AxiProt     (AXI_PROT_VALUE),
    .axi_req_t   (axi_req_t),
    .axi_rsp_t   (axi_resp_t)
  ) u_axi_lite_from_mem (
    .clk_i,
    .rst_ni,
    .mem_req_i      (mem_req),
    .mem_addr_i     (apb_req_i.paddr),
    .mem_we_i       (apb_req_i.pwrite),
    .mem_wdata_i    (apb_req_i.pwdata),
    .mem_be_i       (apb_req_i.pstrb),
    .mem_gnt_o      (mem_gnt),
    .mem_rsp_valid_o(apb_resp_o.pready),
    .mem_rsp_rdata_o(apb_resp_o.prdata),
    .mem_rsp_error_o(apb_resp_o.pslverr),
    .axi_req_o      (axi_req_o),
    .axi_rsp_i      (axi_resp_i)
  );

endmodule
