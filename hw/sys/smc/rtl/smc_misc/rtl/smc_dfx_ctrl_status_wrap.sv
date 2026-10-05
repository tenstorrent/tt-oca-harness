// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Expose SMC DFX control and status CSRs.
//
// Bridges software-visible DFX controls onto the internal AXI-Lite map.
// Reports memory-repair and MBIST status in STATUS_SMU and drives the DEBUG_CTRL and
// DEBUG_BUS_MUX fields that configure smc_dfd_wrap; debug-bus mux segments 8 to 15 and
// the fine-grain time field have no register and are tied to zero.

module smc_dfx_ctrl_status_wrap (
  input  logic                                clk_i,  // SMC core clock.
  input  logic                                rst_ni,  // Primary reset, active-low, synchronized to
                                                       // the SMC core clock; returns the DFX
                                                       // control and status registers to their
                                                       // reset values.

  input  smc_pkg::smc_axil_32_64_req_t        axil_dfx_csr_req_i,  // Request from the internal
                                                                   // CSR crossbar for the DFX
                                                                   // control window.
  output smc_pkg::smc_axil_32_64_resp_t       axil_dfx_csr_resp_o,  // Response to the internal
                                                                    // CSR crossbar.

  input  logic                                mem_repair_done_i,  // Memory repair has finished;
                                                                  // reported in STATUS_SMU.
  input  logic                                mem_repair_success_i,  // Memory repair succeeded;
                                                                     // reported in STATUS_SMU.
  input  logic                                mem_repair_abort_i,  // Memory repair was aborted;
                                                                   // reported in STATUS_SMU.
  input  logic                                mbist_done_i,  // Memory BIST has finished;
                                                             // reported in STATUS_SMU.
  input  logic                                mbist_pass_i,  // Memory BIST passed; reported
                                                             // in STATUS_SMU.
  input  logic                                mbist_abort_i,  // Memory BIST was aborted;
                                                              // reported in STATUS_SMU.

  output smc_pkg::dfd_enable_t                dfd_enables_o,  // DEBUG_CTRL clock-gate,
                                                              // force-clock, GPIO, DTB,
                                                              // cross-trigger halt mask and
                                                              // debug marker fields.
  output tt_dbm_pkg::DbgMuxSelMmr_s           dbg_mux_sel_csr_o  // Debug-bus mux mode, ID
                                                                 // and segment selects from
                                                                 // DEBUG_BUS_MUX.
);

  dfx_ctrl_status_reg_pkg::dfx_ctrl_status__in_t  dfx_csr_hwif_in;
  dfx_ctrl_status_reg_pkg::dfx_ctrl_status__out_t dfx_csr_hwif_out;

  always_comb begin
    dfx_csr_hwif_in = '{default: '0};  // Default all fields to zero

    dfx_csr_hwif_in.STATUS_SMU.mem_repair_done.next     = mem_repair_done_i;
    dfx_csr_hwif_in.STATUS_SMU.mem_repair_success.next  = mem_repair_success_i;
    dfx_csr_hwif_in.STATUS_SMU.mem_repair_abort.next    = mem_repair_abort_i;
    dfx_csr_hwif_in.STATUS_SMU.mbist_done.next          = mbist_done_i;
    dfx_csr_hwif_in.STATUS_SMU.mbist_pass.next          = mbist_pass_i;
    dfx_csr_hwif_in.STATUS_SMU.mbist_abort.next         = mbist_abort_i;

  end

  dfx_ctrl_status_reg u_dfx_ctrl_status_reg (
    .clk(clk_i),
    .arst_n(rst_ni),

    .s_axil_awready (axil_dfx_csr_resp_o.aw_ready),
    .s_axil_awvalid (axil_dfx_csr_req_i.aw_valid),
    .s_axil_awaddr  (axil_dfx_csr_req_i.aw.addr[dfx_ctrl_status_reg_pkg::DFX_CTRL_STATUS_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (axil_dfx_csr_req_i.aw.prot),
    .s_axil_wready  (axil_dfx_csr_resp_o.w_ready),
    .s_axil_wvalid  (axil_dfx_csr_req_i.w_valid),
    .s_axil_wdata   (axil_dfx_csr_req_i.w.data),
    .s_axil_wstrb   (axil_dfx_csr_req_i.w.strb),
    .s_axil_bready  (axil_dfx_csr_req_i.b_ready),
    .s_axil_bvalid  (axil_dfx_csr_resp_o.b_valid),
    .s_axil_bresp   (axil_dfx_csr_resp_o.b.resp),
    .s_axil_arready (axil_dfx_csr_resp_o.ar_ready),
    .s_axil_arvalid (axil_dfx_csr_req_i.ar_valid),
    .s_axil_araddr  (axil_dfx_csr_req_i.ar.addr[dfx_ctrl_status_reg_pkg::DFX_CTRL_STATUS_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (axil_dfx_csr_req_i.ar.prot),
    .s_axil_rready  (axil_dfx_csr_req_i.r_ready),
    .s_axil_rvalid  (axil_dfx_csr_resp_o.r_valid),
    .s_axil_rdata   (axil_dfx_csr_resp_o.r.data),
    .s_axil_rresp   (axil_dfx_csr_resp_o.r.resp),

    .hwif_in        (dfx_csr_hwif_in),
    .hwif_out       (dfx_csr_hwif_out)
  );

  // DFD config fields from the DEBUG_CTRL / DEBUG_BUS_MUX registers.
  assign dfd_enables_o.dfd_cg_en = dfx_csr_hwif_out.DEBUG_CTRL.cg_en.value;
  assign dfd_enables_o.dfd_force_clk_en = dfx_csr_hwif_out.DEBUG_CTRL.force_clk_en.value;
  assign dfd_enables_o.dfd_gpio_en = dfx_csr_hwif_out.DEBUG_CTRL.gpio_en.value;
  assign dfd_enables_o.dfd_dtb_ew_en = dfx_csr_hwif_out.DEBUG_CTRL.dtb_ew_en.value;
  assign dfd_enables_o.dfd_dtb_ns_en = dfx_csr_hwif_out.DEBUG_CTRL.dtb_ns_en.value;
  assign dfd_enables_o.xtrig_clk_halt_mask = dfx_csr_hwif_out.DEBUG_CTRL.xtrig_clk_halt_mask.value;
  assign dfd_enables_o.debug_marker = dfx_csr_hwif_out.DEBUG_CTRL.debug_marker.value;

  assign dbg_mux_sel_csr_o.DbmMode = dfx_csr_hwif_out.DEBUG_BUS_MUX.Dbmmode.value;
  assign dbg_mux_sel_csr_o.DbmId = dfx_csr_hwif_out.DEBUG_BUS_MUX.Dbmid.value;
  assign dbg_mux_sel_csr_o.Rsvd157 = dfx_csr_hwif_out.DEBUG_BUS_MUX.Rsvd158.value[6:0];
  assign dbg_mux_sel_csr_o.FineGrainTime = '0;
  assign dbg_mux_sel_csr_o.Muxselseg0 = dfx_csr_hwif_out.DEBUG_BUS_MUX.Muxselseg0.value;
  assign dbg_mux_sel_csr_o.Muxselseg1 = dfx_csr_hwif_out.DEBUG_BUS_MUX.Muxselseg1.value;
  assign dbg_mux_sel_csr_o.Muxselseg2 = dfx_csr_hwif_out.DEBUG_BUS_MUX.Muxselseg2.value;
  assign dbg_mux_sel_csr_o.Muxselseg3 = dfx_csr_hwif_out.DEBUG_BUS_MUX.Muxselseg3.value;
  assign dbg_mux_sel_csr_o.Muxselseg4 = dfx_csr_hwif_out.DEBUG_BUS_MUX.Muxselseg4.value;
  assign dbg_mux_sel_csr_o.Muxselseg5 = dfx_csr_hwif_out.DEBUG_BUS_MUX.Muxselseg5.value;
  assign dbg_mux_sel_csr_o.Muxselseg6 = dfx_csr_hwif_out.DEBUG_BUS_MUX.Muxselseg6.value;
  assign dbg_mux_sel_csr_o.Muxselseg7 = dfx_csr_hwif_out.DEBUG_BUS_MUX.Muxselseg7.value;
  // No CSR backing: the L2/L3 stages emit 4 lanes, so only seg0..3 are consulted.
  assign dbg_mux_sel_csr_o.Muxselseg8 = '0;
  assign dbg_mux_sel_csr_o.Muxselseg9 = '0;
  assign dbg_mux_sel_csr_o.Muxselseg10 = '0;
  assign dbg_mux_sel_csr_o.Muxselseg11 = '0;
  assign dbg_mux_sel_csr_o.Muxselseg12 = '0;
  assign dbg_mux_sel_csr_o.Muxselseg13 = '0;
  assign dbg_mux_sel_csr_o.Muxselseg14 = '0;
  assign dbg_mux_sel_csr_o.Muxselseg15 = '0;

endmodule
