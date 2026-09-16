// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//----------------------------------------------------------
// Copyright 2026 Tenstorrent Inc.
// drbg_edn_axis_adapter
//
// Native EDN endpoint to AXI-Stream adapter for the DRBG wrapper.
//----------------------------------------------------------

/**
 * @file drbg_edn_axis_adapter.sv
 * @brief Converts native EDN endpoint req/ack traffic into AXI-Stream outputs.
 *
 * @details Each endpoint is serviced independently with a local same-clock FIFO.
 *          The adapter keeps `edn_req` asserted whenever the endpoint FIFO has
 *          space, captures `{edn_fips, edn_bus}` on `edn_ack`, and presents
 *          the buffered words on 32-bit AXI-Stream outputs with
 *          `tstrb = 4'hF` and a per-beat `tuser` sideband carrying the FIPS
 *          provenance of the genbits.
 *
 * @param EDN_ENDPOINT_COUNT Number of exposed EDN endpoints.
 * @param ENDPOINT_FIFO_DEPTH FIFO depth for each endpoint AXI-Stream output.
 */
module drbg_edn_axis_adapter
  import drbg_pkg::*;
#(
  parameter int unsigned EDN_ENDPOINT_COUNT = DRBG_DEFAULT_EDN_ENDPOINT_COUNT,
  parameter int unsigned ENDPOINT_FIFO_DEPTH = DRBG_DEFAULT_ENDPOINT_FIFO_DEPTH
) (
  input  wire logic                                                   clk_i,
  input  wire logic                                                   rst_ni,

  output edn_pkg::edn_req_t [EDN_ENDPOINT_COUNT-1:0]                  edn_req_o,
  input  wire edn_pkg::edn_rsp_t [EDN_ENDPOINT_COUNT-1:0]             edn_rsp_i,

  output drbg_axis_req_t [EDN_ENDPOINT_COUNT-1:0]                     edn_axis_o,
  input  wire drbg_axis_rsp_t [EDN_ENDPOINT_COUNT-1:0]                edn_axis_i,

  output logic [EDN_ENDPOINT_COUNT-1:0]                               endpoint_fifo_full_o,
  output logic [EDN_ENDPOINT_COUNT-1:0][$clog2(ENDPOINT_FIFO_DEPTH + 1)-1:0]
                                                                      endpoint_fifo_depth_o
);

  `include "prim_assert.sv"

  // Each endpoint FIFO carries {edn_fips, edn_bus} so the per-beat FIPS
  // provenance is preserved on the AXI-Stream tuser sideband.
  localparam int unsigned EndpointFifoWidth = 33;

  logic [EDN_ENDPOINT_COUNT-1:0] endpoint_fifo_err;
  logic [EndpointFifoWidth-1:0]  endpoint_fifo_rdata [EDN_ENDPOINT_COUNT];

  for (genvar i = 0; i < EDN_ENDPOINT_COUNT; i++) begin : gen_endpoints
    prim_fifo_sync #(
      .Width            (EndpointFifoWidth),
      .Pass             (1'b0),
      .Depth            (ENDPOINT_FIFO_DEPTH),
      .OutputZeroIfEmpty(1'b1)
    ) u_endpoint_fifo (
      .clk_i    (clk_i),
      .rst_ni   (rst_ni),
      .clr_i    (1'b0),
      .wvalid_i (edn_rsp_i[i].edn_ack),
      .wready_o (/* unused */),
      .wdata_i  ({edn_rsp_i[i].edn_fips, edn_rsp_i[i].edn_bus}),
      .rvalid_o (edn_axis_o[i].tvalid),
      .rready_i (edn_axis_i[i].tready),
      .rdata_o  (endpoint_fifo_rdata[i]),
      .full_o   (endpoint_fifo_full_o[i]),
      .depth_o  (endpoint_fifo_depth_o[i]),
      .err_o    (endpoint_fifo_err[i])
    );

    assign edn_axis_o[i].tdata      = endpoint_fifo_rdata[i][31:0];
    assign edn_axis_o[i].tuser      = endpoint_fifo_rdata[i][32];
    assign edn_req_o[i].edn_req = rst_ni && !endpoint_fifo_full_o[i];
    assign edn_axis_o[i].tstrb = 4'hF;

    `OCAH_OT_ASSERT(EndpointAckRequiresReq_A, edn_rsp_i[i].edn_ack |-> edn_req_o[i].edn_req)
    `OCAH_OT_ASSERT(EndpointNoAckWhenFull_A, endpoint_fifo_full_o[i] |-> !edn_rsp_i[i].edn_ack)
    `OCAH_OT_ASSERT(EndpointOutputStable_A,
                    edn_axis_o[i].tvalid && !edn_axis_i[i].tready |=> $stable(edn_axis_o[i].tdata))
    `OCAH_OT_ASSERT(EndpointStrbStable_A,
                    edn_axis_o[i].tvalid && !edn_axis_i[i].tready |=> $stable(edn_axis_o[i].tstrb))

    `OCAH_OT_ASSERT_KNOWN(EndpointReqKnown_A, edn_req_o[i].edn_req)
    `OCAH_OT_ASSERT_KNOWN(EndpointAxisValidKnown_A, edn_axis_o[i].tvalid)
    `OCAH_OT_ASSERT_KNOWN_IF(EndpointAxisDataKnown_A, edn_axis_o[i].tdata, edn_axis_o[i].tvalid)
    `OCAH_OT_ASSERT_KNOWN_IF(EndpointAxisStrbKnown_A, edn_axis_o[i].tstrb, edn_axis_o[i].tvalid)
    `OCAH_OT_ASSERT_KNOWN(EndpointFifoFullKnown_A, endpoint_fifo_full_o[i])
    `OCAH_OT_ASSERT_KNOWN(EndpointFifoDepthKnown_A, endpoint_fifo_depth_o[i])
    `OCAH_OT_ASSERT(EndpointFifoHealthy_A, !endpoint_fifo_err[i])
  end : gen_endpoints

  `OCAH_OT_ASSERT_INIT(EndpointCountValid_A, EDN_ENDPOINT_COUNT > 0)
  `OCAH_OT_ASSERT_INIT(EndpointDepthValid_A, ENDPOINT_FIFO_DEPTH > 0)

endmodule : drbg_edn_axis_adapter
