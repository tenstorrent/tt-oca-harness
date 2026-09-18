// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Attaches the shared AXI checker to every jtag2axi instance under the formal top, on the CDC's
// response side toward the request machine: the machine is the master, whose rules the instance
// asserts, and the CDC stands for the responder, whose rules it assumes. The AXI ports lie behind
// the clearable CDC, whose handshake after reset keeps them idle within the bounded depth of the
// task, and the machine sees the responder through this side alone. The machine admits up to
// FIFO_DEPTH + 1 requests.

bind jtag2axi ocah_axi_fv #(
  .IS_LITE             (1'b0),
  .ADDR_WIDTH          (ADDR_WIDTH),
  .DATA_WIDTH          (DATA_WIDTH),
  .ID_WIDTH            (ID_WIDTH),
  .MAX_OUTSTANDING     (FIFO_DEPTH + 1),
  .ASSUME_MASTER_RULES (1'b0),
  .ASSUME_SLAVE_RULES  (1'b1)
) u_ocah_axi_fv (
  .aclk    (tck_i),
  .aresetn (trst_ni),
  .awid    (src_req.aw.id),
  .awaddr  (src_req.aw.addr),
  .awlen   (src_req.aw.len),
  .awsize  (src_req.aw.size),
  .awburst (src_req.aw.burst),
  .awlock  (src_req.aw.lock),
  .awprot  (src_req.aw.prot),
  .awvalid (src_req.aw_valid),
  .awready (src_resp.aw_ready),
  .wdata   (src_req.w.data),
  .wstrb   (src_req.w.strb),
  .wlast   (src_req.w.last),
  .wvalid  (src_req.w_valid),
  .wready  (src_resp.w_ready),
  .bid     (src_resp.b.id),
  .bresp   (src_resp.b.resp),
  .bvalid  (src_resp.b_valid),
  .bready  (src_req.b_ready),
  .arid    (src_req.ar.id),
  .araddr  (src_req.ar.addr),
  .arlen   (src_req.ar.len),
  .arsize  (src_req.ar.size),
  .arburst (src_req.ar.burst),
  .arlock  (src_req.ar.lock),
  .arprot  (src_req.ar.prot),
  .arvalid (src_req.ar_valid),
  .arready (src_resp.ar_ready),
  .rid     (src_resp.r.id),
  .rdata   (src_resp.r.data),
  .rresp   (src_resp.r.resp),
  .rlast   (src_resp.r.last),
  .rvalid  (src_resp.r_valid),
  .rready  (src_req.r_ready)
);
