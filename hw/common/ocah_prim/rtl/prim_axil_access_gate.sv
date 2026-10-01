// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Answer AXI-Lite accesses with an error response while the subordinate is unavailable.
//
// While block_i is low every request passes to the subordinate port unchanged. While it is
// high each access completes locally with RESP, reads returning RESP_DATA zero-extended or
// truncated to DATA_WIDTH, and nothing reaches the subordinate. block_i is sampled when the
// AW or AR request is accepted, so a request already handed to the subordinate completes
// there even if block_i rises afterwards. Responses return in request order.
// clk_i must keep running while block_i is high: the gate sits in front of a subordinate
// whose own clock may be stopped.

module prim_axil_access_gate #(
  parameter int unsigned           ADDR_WIDTH = 32,  // AXI-Lite address width.
  parameter int unsigned           DATA_WIDTH = 32,  // AXI-Lite data width; a power of two of
                                                     // at least 8.
  parameter int unsigned           MAX_TRANS  = 1,  // Outstanding transactions per channel
                                                    // through the gate.
  parameter axi_pkg::resp_t        RESP       = axi_pkg::RESP_SLVERR,  // Response code while
                                                                        // blocked.
  parameter int unsigned           RESP_WIDTH = 32'd64,  // Width of RESP_DATA only.
  parameter logic [RESP_WIDTH-1:0] RESP_DATA  = 64'hBADCAB1EBADCAB1E,  // Read data while
                                                                       // blocked.

  parameter type axil_req_t     = logic,  // AXI-Lite request struct.
  parameter type axil_resp_t    = logic,  // AXI-Lite response struct.
  parameter type axil_aw_chan_t = logic,  // AW channel type.
  parameter type axil_w_chan_t  = logic,  // W channel type.
  parameter type axil_b_chan_t  = logic,  // B channel type.
  parameter type axil_ar_chan_t = logic,  // AR channel type.
  parameter type axil_r_chan_t  = logic  // R channel type.
) (
  input logic clk_i,  // AXI-Lite clock; runs while block_i is high.
  input logic rst_ni,  // Async reset, active-low.
  input logic test_en_i,  // DFT/test enable for the internal AXI-Lite demux.

  input logic block_i,  // Answer every newly accepted access with RESP while high.

  input  axil_req_t  axil_req_i,  // Request from the manager.
  output axil_resp_t axil_resp_o,  // Response toward the manager.

  output axil_req_t  axil_req_o,  // Request toward the subordinate.
  input  axil_resp_t axil_resp_i  // Response from the subordinate.
);

  localparam logic PassPort = 1'b0;
  localparam logic ErrPort  = 1'b1;

  axil_req_t  [1:0] axil_reqs;
  axil_resp_t [1:0] axil_resps;

  // SpillAw and SpillAr register block_i together with the accepted request, which keeps the
  // routed select stable while the request waits on a port that is not ready.
  axi_lite_demux #(
    .aw_chan_t   (axil_aw_chan_t),
    .w_chan_t    (axil_w_chan_t),
    .b_chan_t    (axil_b_chan_t),
    .ar_chan_t   (axil_ar_chan_t),
    .r_chan_t    (axil_r_chan_t),
    .axi_req_t   (axil_req_t),
    .axi_resp_t  (axil_resp_t),
    .NoMstPorts  (2),
    .MaxTrans    (MAX_TRANS),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_axi_lite_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .slv_req_i       (axil_req_i),
    .slv_aw_select_i (block_i ? ErrPort : PassPort),
    .slv_ar_select_i (block_i ? ErrPort : PassPort),
    .slv_resp_o      (axil_resp_o),
    .mst_reqs_o      (axil_reqs),
    .mst_resps_i     (axil_resps)
  );

  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH (ADDR_WIDTH),
    .AXI_DATA_WIDTH (DATA_WIDTH),
    .axil_req_t     (axil_req_t),
    .axil_resp_t    (axil_resp_t),
    .RESP           (RESP),
    .RESP_WIDTH     (RESP_WIDTH),
    .RESP_DATA      (RESP_DATA),
    .MAX_TRANS      (MAX_TRANS)
  ) u_err_slv (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .axil_req_i  (axil_reqs[ErrPort]),
    .axil_resp_o (axil_resps[ErrPort])
  );

  assign axil_req_o            = axil_reqs[PassPort];
  assign axil_resps[PassPort]  = axil_resp_i;

endmodule
