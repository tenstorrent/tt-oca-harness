// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Expose SMC base-config CSRs for address windows and clock gates.
//
// Publishes address-window and clock-gate enables consumed by smc_base and the top.
// Sits on the internal AXI-Lite fabric as the smc_base_config target.

module smc_base_config_wrap (
  input  logic                                clk_i,  // Clock.
  input  logic                                rst_n_i,  // Rst n.

  input  smc_pkg::smc_axil_32_64_req_t        axil_base_config_req_i,  // AXI-Lite interface
                                                                       // to base config CSR
                                                                       // request.
  output smc_pkg::smc_axil_32_64_resp_t       axil_base_config_resp_o,  // AXI-Lite interface
                                                                        // to base config CSR
                                                                        // response.

  output smc_pkg::smc_axi_addr_t              smc_global_base_o,  // SMC address window.
  output smc_pkg::smc_axi_addr_t              smc_local_base_o,  // SMC address window.
  output logic [31:0]                         smc_region_size_o,  // SMC address window.

  output logic                                cg_ctrl_dma_cg_en_o,  // Clock-gate enables.
  output logic                                cg_ctrl_mailbox_cg_en_o,  // Clock-gate enables.
  output logic                                cg_ctrl_ob_filter_axi_cg_en_o,  // Clock-gate enables.
  output logic                                cg_ctrl_ob_filter_reg_cg_en_o,  // Clock-gate enables.
  output logic                                cg_ctrl_ib_filter_axi_cg_en_o,  // Clock-gate enables.
  output logic                                cg_ctrl_ib_filter_reg_cg_en_o,  // Clock-gate enables.
  output logic                                cg_ctrl_addr_remap_cg_en_o,  // Clock-gate enables.
  output logic                                cg_ctrl_output_fabric_cg_en_o,  // Clock-gate enables.
  output logic                                cg_ctrl_zeroer_cg_en_o,  // Clock-gate enables.
  output logic                                cg_ctrl_i3c_cg_en_o,  // Clock-gate enables.
  output logic                                cg_ctrl_avs_cg_en_o,  // Clock-gate enables.
  output logic                                cg_ctrl_i2c_cg_en_o,  // Clock-gate enables.
  output logic                                cg_ctrl_uart_cg_en_o,  // Clock-gate enables.
  output logic                                cg_ctrl_tel_cg_en_o,  // Clock-gate enables.
  output smc_pkg::cg_hyster_t                 cg_ctrl_hysteresis_o,  // Clock-gate enables.

  output logic                                hang_det_sys_axi_enable_o,  // AXI hang detector
                                                                          // config.
  output logic                                hang_det_sys_axi_irq_en_o,  // AXI hang detector
                                                                          // config.
  output logic                                hang_det_sys_axi_irq_test_o,  // AXI hang detector
                                                                            // config.
  output logic [19:0]                         hang_det_sys_axi_threshold_o,  // AXI hang detector
                                                                             // config.
  output logic                                hang_det_sep_axi_enable_o,  // AXI hang detector
                                                                          // config.
  output logic                                hang_det_sep_axi_irq_en_o,  // AXI hang detector
                                                                          // config.
  output logic                                hang_det_sep_axi_irq_test_o,  // AXI hang detector
                                                                            // config.
  output logic [19:0]                         hang_det_sep_axi_threshold_o,  // AXI hang detector
                                                                             // config.
  output logic                                hang_det_data_accel_enable_o,  // AXI hang detector
                                                                             // config.
  output logic                                hang_det_data_accel_irq_en_o,  // AXI hang detector
                                                                             // config.
  output logic                                hang_det_data_accel_irq_test_o,  // AXI hang detector
                                                                               // config.
  output logic [19:0]                         hang_det_data_accel_threshold_o  // AXI hang detector
                                                                               // config.
);

  smc_base_config_reg_pkg::smc_base_config__out_t hwif_out;

  smc_base_config_reg u_smc_base_config_reg (
    .clk(clk_i),
    .arst_n(rst_n_i),

    .s_axil_awready (axil_base_config_resp_o.aw_ready),
    .s_axil_awvalid (axil_base_config_req_i.aw_valid),
    .s_axil_awaddr  (axil_base_config_req_i.aw.addr[smc_base_config_reg_pkg::SMC_BASE_CONFIG_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot  (axil_base_config_req_i.aw.prot),
    .s_axil_wready  (axil_base_config_resp_o.w_ready),
    .s_axil_wvalid  (axil_base_config_req_i.w_valid),
    .s_axil_wdata   (axil_base_config_req_i.w.data),
    .s_axil_wstrb   (axil_base_config_req_i.w.strb),
    .s_axil_bready  (axil_base_config_req_i.b_ready),
    .s_axil_bvalid  (axil_base_config_resp_o.b_valid),
    .s_axil_bresp   (axil_base_config_resp_o.b.resp),
    .s_axil_arready (axil_base_config_resp_o.ar_ready),
    .s_axil_arvalid (axil_base_config_req_i.ar_valid),
    .s_axil_araddr  (axil_base_config_req_i.ar.addr[smc_base_config_reg_pkg::SMC_BASE_CONFIG_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot  (axil_base_config_req_i.ar.prot),
    .s_axil_rready  (axil_base_config_req_i.r_ready),
    .s_axil_rvalid  (axil_base_config_resp_o.r_valid),
    .s_axil_rdata   (axil_base_config_resp_o.r.data),
    .s_axil_rresp   (axil_base_config_resp_o.r.resp),

    .hwif_out       (hwif_out)
  );

  // SMC address window
  assign smc_global_base_o = hwif_out.GLOBAL_BASE.base.value;
  assign smc_local_base_o  = hwif_out.LOCAL_BASE.base.value;
  assign smc_region_size_o = hwif_out.REGION_SIZE.size.value;

  // Clock-gate enables
  assign cg_ctrl_dma_cg_en_o           = hwif_out.CLOCK_GATE_CONTROL.dma_cg_en.value;
  assign cg_ctrl_mailbox_cg_en_o       = hwif_out.CLOCK_GATE_CONTROL.mailbox_cg_en.value;
  assign cg_ctrl_ob_filter_axi_cg_en_o = hwif_out.CLOCK_GATE_CONTROL.filter_ob_axi_cg_en.value;
  assign cg_ctrl_ob_filter_reg_cg_en_o = hwif_out.CLOCK_GATE_CONTROL.filter_ob_reg_cg_en.value;
  assign cg_ctrl_ib_filter_axi_cg_en_o = hwif_out.CLOCK_GATE_CONTROL.filter_ib_axi_cg_en.value;
  assign cg_ctrl_ib_filter_reg_cg_en_o = hwif_out.CLOCK_GATE_CONTROL.filter_ib_reg_cg_en.value;
  assign cg_ctrl_addr_remap_cg_en_o    = hwif_out.CLOCK_GATE_CONTROL.addr_remap_cg_en.value;
  assign cg_ctrl_output_fabric_cg_en_o = hwif_out.CLOCK_GATE_CONTROL.output_fabric_cg_en.value;
  assign cg_ctrl_zeroer_cg_en_o        = hwif_out.CLOCK_GATE_CONTROL.zeroer_cg_en.value;
  assign cg_ctrl_i3c_cg_en_o           = hwif_out.CLOCK_GATE_CONTROL.i3c_cg_en.value;
  assign cg_ctrl_avs_cg_en_o           = hwif_out.CLOCK_GATE_CONTROL.avs_cg_en.value;
  assign cg_ctrl_i2c_cg_en_o           = hwif_out.CLOCK_GATE_CONTROL.i2c_cg_en.value;
  assign cg_ctrl_uart_cg_en_o          = hwif_out.CLOCK_GATE_CONTROL.uart_cg_en.value;
  assign cg_ctrl_tel_cg_en_o           = hwif_out.CLOCK_GATE_CONTROL.telemetry_cg_en.value;
  assign cg_ctrl_hysteresis_o          = hwif_out.CLOCK_GATE_CONTROL.cg_hysteresis.value;

  // AXI hang detector config
  assign hang_det_sys_axi_enable_o       = hwif_out.HANG_DET_SYS_AXI_CTRL.enable.value;
  assign hang_det_sys_axi_irq_en_o       = hwif_out.HANG_DET_SYS_AXI_CTRL.irq_en.value;
  assign hang_det_sys_axi_irq_test_o     = hwif_out.HANG_DET_SYS_AXI_CTRL.irq_test.value;
  assign hang_det_sys_axi_threshold_o    = hwif_out.HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD.value.value;
  assign hang_det_sep_axi_enable_o       = hwif_out.HANG_DET_SEP_AXI_CTRL.enable.value;
  assign hang_det_sep_axi_irq_en_o       = hwif_out.HANG_DET_SEP_AXI_CTRL.irq_en.value;
  assign hang_det_sep_axi_irq_test_o     = hwif_out.HANG_DET_SEP_AXI_CTRL.irq_test.value;
  assign hang_det_sep_axi_threshold_o    = hwif_out.HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD.value.value;
  assign hang_det_data_accel_enable_o    = hwif_out.HANG_DET_DATA_ACCEL_CTRL.enable.value;
  assign hang_det_data_accel_irq_en_o    = hwif_out.HANG_DET_DATA_ACCEL_CTRL.irq_en.value;
  assign hang_det_data_accel_irq_test_o  = hwif_out.HANG_DET_DATA_ACCEL_CTRL.irq_test.value;
  assign hang_det_data_accel_threshold_o = hwif_out.HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD.value.value;

endmodule
