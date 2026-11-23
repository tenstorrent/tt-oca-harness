// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`ifndef OCAH_DEBUG_AXI_SVH
`define OCAH_DEBUG_AXI_SVH

// Debug bus lanes for an AXI or AXI-Lite port. last is 0 on AXI-Lite lanes:
// [13] r.resp[1]  [12] b.resp[1]  [11] r.last  [10] w.last
// [9] r_ready  [8] r_valid  [7] ar_ready  [6] ar_valid  [5] b_ready  [4] b_valid
// [3] w_ready  [2] w_valid  [1] aw_ready  [0] aw_valid
// verilog_format: off
`define OCAH_DEBUG_AXI_LANE(axi_req, axi_rsp, r_last, w_last) \
      {2'h0, axi_rsp.r.resp[1], axi_rsp.b.resp[1], r_last, w_last, \
       axi_req.r_ready, axi_rsp.r_valid, axi_rsp.ar_ready, axi_req.ar_valid, \
       axi_req.b_ready, axi_rsp.b_valid, axi_rsp.w_ready, axi_req.w_valid, \
       axi_rsp.aw_ready, axi_req.aw_valid}
`define OCAH_DEBUG_AXI4_LANE(axi_req, axi_rsp) `OCAH_DEBUG_AXI_LANE(axi_req, axi_rsp, axi_rsp.r.last, axi_req.w.last)
`define OCAH_DEBUG_AXIL_LANE(axi_req, axi_rsp) `OCAH_DEBUG_AXI_LANE(axi_req, axi_rsp, 1'b0, 1'b0)
// verilog_format: on

`endif  // OCAH_DEBUG_AXI_SVH
