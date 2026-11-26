// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Bridge one AXI-Lite manager to a single APB subordinate.
//
// Complete addresses outside [ADDR_START, ADDR_END) with a decode error on AXI-Lite.
// PIPELINE_REQUEST and PIPELINE_RESPONSE insert skid registers on the request and response
// paths.
// Hold only one APB transfer in flight at a time.

module prim_axi_lite_to_apb_single #(
  parameter bit PIPELINE_REQUEST     = 1'b0,  // Skid-registers the AXI-Lite to APB request path.
  parameter bit PIPELINE_RESPONSE    = 1'b0,  // Skid-registers the APB to AXI-Lite response path.
  parameter int unsigned AXI_DATA_WIDTH = 32,  // Shared data width.
  parameter int unsigned AXI_ADDR_WIDTH = 32,  // Shared address width.

  parameter bit [AXI_ADDR_WIDTH-1:0] ADDR_START = 32'h0,  // Inclusive APB decode base.
  parameter bit [AXI_ADDR_WIDTH:0]   ADDR_END   = 33'h0,  // Exclusive APB decode limit.

  parameter type axil_req_t  = logic,  // AXI-Lite request struct, AXI_ADDR_WIDTH-bit addresses.
  parameter type axil_resp_t = logic,  // AXI-Lite response struct.
  parameter type apb_req_t   = logic,  // APB request struct with paddr, pprot, psel, penable,
                                       // pwrite, pwdata and pstrb.
  parameter type apb_resp_t  = logic,  // APB response struct with pready, prdata and pslverr.

  localparam type data_t = logic [AXI_DATA_WIDTH-1:0],  // Data type alias.
  localparam type strb_t = logic [AXI_DATA_WIDTH/8-1:0]  // Strobe type alias.
) (
  input logic clk_i,  // Clock shared by the AXI-Lite and APB sides of the bridge.
  input logic rst_ni,  // Async reset, active-low.

  input  axil_req_t  axil_req_i,  // AXI-Lite request; addresses decode against [ADDR_START,
                                  // ADDR_END).
  output axil_resp_t axil_resp_o,  // AXI-Lite response; SLVERR on pslverr, DECERR outside the
                                   // decode range.

  output apb_req_t  apb_req_o,  // APB request to the single subordinate.
  input  apb_resp_t apb_resp_i  // APB response from the single subordinate.
);

  `include "axi/typedef.svh"

  // One extra address bit lets ADDR_END reach the top of the AXI_ADDR_WIDTH address space.
  localparam int unsigned ExtendedAddrWidth = AXI_ADDR_WIDTH + 1;

  typedef logic [ExtendedAddrWidth-1:0] ext_addr_t;

  `AXI_LITE_TYPEDEF_ALL(ext_axil, ext_addr_t, data_t, strb_t)

  typedef struct packed {
    ext_addr_t      paddr;
    axi_pkg::prot_t pprot;
    logic           psel;
    logic           penable;
    logic           pwrite;
    data_t          pwdata;
    strb_t          pstrb;
  } ext_apb_req_t;

  typedef struct packed {
    logic  pready;
    data_t prdata;
    logic  pslverr;
  } ext_apb_resp_t;

  typedef struct packed {
    int unsigned idx;
    ext_addr_t   start_addr;
    ext_addr_t   end_addr;
  } rule_t;

  localparam rule_t [0:0] ApbRule = '{
      '{idx: 32'd0, start_addr: {1'b0, ADDR_START}, end_addr: ADDR_END}
  };

  ext_axil_req_t  ext_axil_req;
  ext_axil_resp_t ext_axil_resp;
  ext_apb_req_t   ext_apb_req;
  ext_apb_resp_t  ext_apb_resp;

  assign ext_axil_req.aw_valid = axil_req_i.aw_valid;
  assign ext_axil_req.aw.addr  = {1'b0, axil_req_i.aw.addr};
  assign ext_axil_req.aw.prot  = axil_req_i.aw.prot;
  assign ext_axil_req.w_valid  = axil_req_i.w_valid;
  assign ext_axil_req.w.data   = axil_req_i.w.data;
  assign ext_axil_req.w.strb   = axil_req_i.w.strb;
  assign ext_axil_req.b_ready  = axil_req_i.b_ready;
  assign ext_axil_req.ar_valid = axil_req_i.ar_valid;
  assign ext_axil_req.ar.addr  = {1'b0, axil_req_i.ar.addr};
  assign ext_axil_req.ar.prot  = axil_req_i.ar.prot;
  assign ext_axil_req.r_ready  = axil_req_i.r_ready;

  assign axil_resp_o.aw_ready = ext_axil_resp.aw_ready;
  assign axil_resp_o.w_ready  = ext_axil_resp.w_ready;
  assign axil_resp_o.b_valid  = ext_axil_resp.b_valid;
  assign axil_resp_o.b.resp   = ext_axil_resp.b.resp;
  assign axil_resp_o.ar_ready = ext_axil_resp.ar_ready;
  assign axil_resp_o.r_valid  = ext_axil_resp.r_valid;
  assign axil_resp_o.r.data   = ext_axil_resp.r.data;
  assign axil_resp_o.r.resp   = ext_axil_resp.r.resp;

  axi_lite_to_apb #(
    .NoApbSlaves     (1),
    .NoRules         (1),
    .AddrWidth       (ExtendedAddrWidth),
    .DataWidth       (AXI_DATA_WIDTH),
    .PipelineRequest (PIPELINE_REQUEST),
    .PipelineResponse(PIPELINE_RESPONSE),
    .axi_lite_req_t  (ext_axil_req_t),
    .axi_lite_resp_t (ext_axil_resp_t),
    .apb_req_t       (ext_apb_req_t),
    .apb_resp_t      (ext_apb_resp_t),
    .rule_t          (rule_t)
  ) u_axi_lite_to_apb (
    .clk_i          (clk_i),
    .rst_ni         (rst_ni),
    .axi_lite_req_i (ext_axil_req),
    .axi_lite_resp_o(ext_axil_resp),
    .apb_req_o      (ext_apb_req),
    .apb_resp_i     (ext_apb_resp),
    .addr_map_i     (ApbRule)
  );

  assign apb_req_o.paddr   = ext_apb_req.paddr[AXI_ADDR_WIDTH-1:0];
  assign apb_req_o.pprot   = ext_apb_req.pprot;
  assign apb_req_o.psel    = ext_apb_req.psel;
  assign apb_req_o.penable = ext_apb_req.penable;
  assign apb_req_o.pwrite  = ext_apb_req.pwrite;
  assign apb_req_o.pwdata  = ext_apb_req.pwdata;
  assign apb_req_o.pstrb   = ext_apb_req.pstrb;

  assign ext_apb_resp.pready  = apb_resp_i.pready;
  assign ext_apb_resp.prdata  = apb_resp_i.prdata;
  assign ext_apb_resp.pslverr = apb_resp_i.pslverr;

endmodule : prim_axi_lite_to_apb_single
