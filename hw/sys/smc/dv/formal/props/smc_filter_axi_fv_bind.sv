// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Attaches the shared AXI checker to every smc_internal_regs instance under the formal top, on
// the outbound filter-control AXI-Lite port: the filter-control side is the slave, whose
// responses the instance asserts, and the internal CSR crossbar is the master, whose handshake
// rules the instance assumes. The master issues one write and one read at a time
// (smc_filter_lock_props.sv states why). The Lite port has no ID, burst or LAST signals, so those
// inputs take the single-beat constants; every access is one 64-bit beat.

bind smc_internal_regs ocah_axi_fv #(
  .IS_LITE             (1'b1),
  .ADDR_WIDTH          (smc_pkg::SmcLocalAddrWidth),
  .DATA_WIDTH          (smc_pkg::AxiLite64DataWidth),
  .ID_WIDTH            (1),
  .MAX_OUTSTANDING     (1),
  .ASSUME_MASTER_RULES (1'b1),
  .ASSUME_SLAVE_RULES  (1'b0)
) u_ocah_axi_fv_ob_filter_ctrl (
  .aclk    (clk_smc_i),
  .aresetn (rst_primary_smc_clk_ni),
  .awid    ('0),
  .awaddr  (axil_outbound_filter_ctrl_req_i.aw.addr),
  .awlen   ('0),
  .awsize  (3'd3),
  .awburst (2'b01),
  .awlock  (1'b0),
  .awprot  (axil_outbound_filter_ctrl_req_i.aw.prot),
  .awvalid (axil_outbound_filter_ctrl_req_i.aw_valid),
  .awready (axil_outbound_filter_ctrl_resp_o.aw_ready),
  .wdata   (axil_outbound_filter_ctrl_req_i.w.data),
  .wstrb   (axil_outbound_filter_ctrl_req_i.w.strb),
  .wlast   (1'b1),
  .wvalid  (axil_outbound_filter_ctrl_req_i.w_valid),
  .wready  (axil_outbound_filter_ctrl_resp_o.w_ready),
  .bid     ('0),
  .bresp   (axil_outbound_filter_ctrl_resp_o.b.resp),
  .bvalid  (axil_outbound_filter_ctrl_resp_o.b_valid),
  .bready  (axil_outbound_filter_ctrl_req_i.b_ready),
  .arid    ('0),
  .araddr  (axil_outbound_filter_ctrl_req_i.ar.addr),
  .arlen   ('0),
  .arsize  (3'd3),
  .arburst (2'b01),
  .arlock  (1'b0),
  .arprot  (axil_outbound_filter_ctrl_req_i.ar.prot),
  .arvalid (axil_outbound_filter_ctrl_req_i.ar_valid),
  .arready (axil_outbound_filter_ctrl_resp_o.ar_ready),
  .rid     ('0),
  .rdata   (axil_outbound_filter_ctrl_resp_o.r.data),
  .rresp   (axil_outbound_filter_ctrl_resp_o.r.resp),
  .rlast   (1'b1),
  .rvalid  (axil_outbound_filter_ctrl_resp_o.r_valid),
  .rready  (axil_outbound_filter_ctrl_req_i.r_ready)
);
