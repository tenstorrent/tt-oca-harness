// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Attaches the shared AXI checker to every cross_trigger_network instance under the formal top, on
// its AXI-Lite port: the network is the slave, whose responses the instance asserts, and the DTP's
// bridge is the master, whose handshake rules the instance assumes. The bridge issues one write
// and one read at a time. The Lite port has no ID, burst or LAST signals, so those inputs take
// the single-beat constants.

bind cross_trigger_network ocah_axi_fv #(
  .IS_LITE             (1'b1),
  .ADDR_WIDTH          (cross_trigger_network_pkg::AxiLiteAddrWidth),
  .DATA_WIDTH          (cross_trigger_network_pkg::AxiLiteDataWidth),
  .ID_WIDTH            (1),
  .MAX_OUTSTANDING     (1),
  .ASSUME_MASTER_RULES (1'b1),
  .ASSUME_SLAVE_RULES  (1'b0)
) u_ocah_axi_fv (
  .aclk    (clk_i),
  .aresetn (rst_ni),
  .awid    ('0),
  .awaddr  (axil_req_i.aw.addr),
  .awlen   ('0),
  .awsize  (3'd2),
  .awburst (2'b01),
  .awlock  (1'b0),
  .awprot  (axil_req_i.aw.prot),
  .awvalid (axil_req_i.aw_valid),
  .awready (axil_resp_o.aw_ready),
  .wdata   (axil_req_i.w.data),
  .wstrb   (axil_req_i.w.strb),
  .wlast   (1'b1),
  .wvalid  (axil_req_i.w_valid),
  .wready  (axil_resp_o.w_ready),
  .bid     ('0),
  .bresp   (axil_resp_o.b.resp),
  .bvalid  (axil_resp_o.b_valid),
  .bready  (axil_req_i.b_ready),
  .arid    ('0),
  .araddr  (axil_req_i.ar.addr),
  .arlen   ('0),
  .arsize  (3'd2),
  .arburst (2'b01),
  .arlock  (1'b0),
  .arprot  (axil_req_i.ar.prot),
  .arvalid (axil_req_i.ar_valid),
  .arready (axil_resp_o.ar_ready),
  .rid     ('0),
  .rdata   (axil_resp_o.r.data),
  .rresp   (axil_resp_o.r.resp),
  .rlast   (1'b1),
  .rvalid  (axil_resp_o.r_valid),
  .rready  (axil_req_i.r_ready)
);
