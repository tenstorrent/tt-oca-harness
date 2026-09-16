// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// AXI-Lite Error Slave
//
//--------------------------------------------------

module prim_axil_err_slv #(
  // Interface configuration parameters
  parameter int unsigned AXI_DATA_WIDTH = 32,
  parameter int unsigned AXI_ADDR_WIDTH = 32,

  parameter type         axil_req_t  = logic, // AXI4-Lite request type
  parameter type         axil_resp_t  = logic, // AXI4-Lite response type

  // Derived parameters
  localparam int unsigned AXI_STRB_WIDTH = (AXI_DATA_WIDTH / 8),
  localparam type addr_t = logic [AXI_ADDR_WIDTH-1:0],
  localparam type data_t = logic [AXI_DATA_WIDTH-1:0],
  localparam type strb_t = logic [AXI_STRB_WIDTH-1:0]
) (
  // Clock and Reset (always first, active-low async reset)
  input  logic        clk_i,
  input  logic        rst_ni,

  // AXI-Lite slave interface (struct-based)
  input  axil_req_t   axil_req_i,
  output axil_resp_t  axil_resp_o
);

  `include "prim_assert.sv"
  `include "axi/typedef.svh"

  ////////////////////////////////////////////////////////////////////////////
  // Assertions
  ////////////////////////////////////////////////////////////////////////////

  // Parameter validation
  `OCAH_OT_ASSERT_INIT(DataWidthValid_A, AXI_DATA_WIDTH >= 8 && $countones(AXI_DATA_WIDTH) == 1)

  // AXI4-Lite protocol compliance
  // Write address channel: awvalid stays high until awready
  `OCAH_OT_ASSERT(AwValidStable_A,
                  axil_req_i.aw_valid && !axil_resp_o.aw_ready |=> axil_req_i.aw_valid, clk_i,
                  !rst_ni)

  // Write data channel: wvalid stays high until wready
  `OCAH_OT_ASSERT(WValidStable_A, axil_req_i.w_valid && !axil_resp_o.w_ready |=> axil_req_i.w_valid,
                  clk_i, !rst_ni)

  // Read address channel: arvalid stays high until arready
  `OCAH_OT_ASSERT(ArValidStable_A,
                  axil_req_i.ar_valid && !axil_resp_o.ar_ready |=> axil_req_i.ar_valid, clk_i,
                  !rst_ni)

  ////////////////////////////////////////////////////////////////////////////
  // Signal Declarations
  ////////////////////////////////////////////////////////////////////////////

  // Internal AXI4 full interface for error slave
  typedef logic id_t;
  typedef logic user_t;

  `AXI_TYPEDEF_ALL(axi, addr_t, id_t, data_t, strb_t, user_t)

  axi_req_t  axi_req;
  axi_resp_t axi_resp;

  ////////////////////////////////////////////////////////////////////////////
  // Module Instantiations
  ////////////////////////////////////////////////////////////////////////////

  // Convert AXI-Lite to AXI4 and instantiate error slave
  axi_lite_to_axi #(
    .AxiDataWidth (AXI_DATA_WIDTH),
    .req_lite_t   (axil_req_t),
    .resp_lite_t  (axil_resp_t),
    .axi_req_t    (axi_req_t),
    .axi_resp_t   (axi_resp_t)
  ) u_axil_to_axi (
    .slv_req_lite_i  (axil_req_i),
    .slv_resp_lite_o (axil_resp_o),
    .slv_aw_cache_i  (axi_pkg::cache_t'(0)),
    .slv_ar_cache_i  (axi_pkg::cache_t'(0)),
    .mst_req_o       (axi_req),
    .mst_resp_i      (axi_resp)
  );

  // AXI4 error slave - responds with DECERR to all transactions
  axi_err_slv #(
    .AxiIdWidth (1),
    .axi_req_t  (axi_req_t),
    .axi_resp_t (axi_resp_t),
    .Resp       (axi_pkg::RESP_DECERR),
    .RespWidth  (AXI_DATA_WIDTH),
    .RespData   ('hBADCAB1E),
    .ATOPs      (1'b0),
    .MaxTrans   (1)
  ) u_axi_err_slv (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (1'b0),
    .slv_req_i  (axi_req),
    .slv_resp_o (axi_resp)
  );

endmodule : prim_axil_err_slv
