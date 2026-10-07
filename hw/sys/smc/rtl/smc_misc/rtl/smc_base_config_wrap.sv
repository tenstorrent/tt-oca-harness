// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Expose SMC base-config CSRs for address windows and clock gates.
//
// Publishes address-window and clock-gate enables consumed by smc_base and the top.
// Sits on the internal AXI-Lite fabric as the smc_base_config target.
// Also publishes the configuration of the three AXI hang detectors in smc_base. Every
// output comes straight from a register field on the SMC core clock.

module smc_base_config_wrap (
  input  logic                                clk_i,  // SMC core clock.
  input  logic                                rst_n_i,  // Primary reset, active-low, synchronized
                                                        // to the SMC core clock; returns the
                                                        // base-config registers to their reset
                                                        // values.

  input  smc_pkg::smc_axil_32_64_req_t        axil_base_config_req_i,  // Request from the
                                                                       // internal CSR crossbar
                                                                       // for the base-config
                                                                       // window.
  output smc_pkg::smc_axil_32_64_resp_t       axil_base_config_resp_o,  // Response to the
                                                                        // internal CSR crossbar.

  output smc_pkg::smc_axi_addr_t              smc_global_base_o,  // SMC global base address from
                                                                  // GLOBAL_BASE.
  output smc_pkg::smc_axi_addr_t              smc_local_base_o,  // SMC local base address from
                                                                 // LOCAL_BASE; in the local
                                                                 // fabric it supplies the upper
                                                                 // bits of rebased addresses.
  output logic [31:0]                         smc_region_size_o,  // SMC region size in bytes from
                                                                  // REGION_SIZE, a power of two
                                                                  // by software contract.

  output logic                                cg_ctrl_dma_cg_en_o,  // Enables idle clock gating of
                                                                    // the DMA when high.
  output logic                                cg_ctrl_mailbox_cg_en_o,  // Enables idle clock gating
                                                                        // of the mailbox when high.
  output logic                                cg_ctrl_ob_filter_axi_cg_en_o,  // Enables idle clock
                                                                              // gating of the
                                                                              // outbound filter
                                                                              // datapath when high.
  output logic                                cg_ctrl_ob_filter_reg_cg_en_o,  // Enables idle clock
                                                                              // gating of the
                                                                              // outbound filter
                                                                              // registers when high.
  output logic                                cg_ctrl_ib_filter_axi_cg_en_o,  // Enables idle clock
                                                                              // gating of the
                                                                              // inbound filter
                                                                              // datapath when high.
  output logic                                cg_ctrl_ib_filter_reg_cg_en_o,  // Enables idle clock
                                                                              // gating of the
                                                                              // inbound filter
                                                                              // registers when high.
  output logic                                cg_ctrl_addr_remap_cg_en_o,  // Enables idle clock
                                                                           // gating of the alias,
                                                                           // M-mode and Xvisor
                                                                           // remap registers when
                                                                           // high.
  output logic                                cg_ctrl_output_fabric_cg_en_o,  // Enables idle clock
                                                                              // gating of the
                                                                              // output fabric when
                                                                              // high.
  output logic                                cg_ctrl_zeroer_cg_en_o,  // Enables idle clock gating
                                                                       // of the zeroer when high.
  output logic                                cg_ctrl_i3c_cg_en_o,  // In smc, stops the I3C
                                                                    // peripheral clock when high.
  output logic                                cg_ctrl_avs_cg_en_o,  // In smc, stops the AVSBus
                                                                    // controller peripheral and
                                                                    // reference clocks when high.
  output logic                                cg_ctrl_i2c_cg_en_o,  // In smc, stops the I2C
                                                                    // peripheral clock when high.
  output logic                                cg_ctrl_uart_cg_en_o,  // In smc, stops the UART
                                                                     // peripheral clock when high.
  output logic                                cg_ctrl_tel_cg_en_o,  // In smc, stops the telemetry
                                                                    // unit's gated SMC and
                                                                    // telemetry clocks when high.
  output smc_pkg::cg_hyster_t                 cg_ctrl_hysteresis_o,  // Idle SMC core clock cycles
                                                                     // the idle clock gates wait
                                                                     // before stopping their
                                                                     // clocks.

  output logic                                hang_det_sys_axi_enable_o,  // Enables the system AXI
                                                                          // hang detector.
  output logic                                hang_det_sys_axi_irq_en_o,  // Enables the system AXI
                                                                          // hang interrupt.
  output logic                                hang_det_sys_axi_irq_test_o,  // Forces the system AXI
                                                                            // hang interrupt high.
  output logic [19:0]                         hang_det_sys_axi_threshold_o,  // Stall cycles after
                                                                             // which the system AXI
                                                                             // hang detector fires.
  output logic                                hang_det_sep_axi_enable_o,  // Enables the SEP AXI
                                                                          // hang detector.
  output logic                                hang_det_sep_axi_irq_en_o,  // Enables the SEP AXI
                                                                          // hang interrupt.
  output logic                                hang_det_sep_axi_irq_test_o,  // Forces the SEP AXI
                                                                            // hang interrupt high.
  output logic [19:0]                         hang_det_sep_axi_threshold_o,  // Stall cycles after
                                                                             // which the SEP AXI
                                                                             // hang detector fires.
  output logic                                hang_det_data_accel_enable_o,  // Enables the
                                                                             // data-accelerator
                                                                             // AXI hang detector.
  output logic                                hang_det_data_accel_irq_en_o,  // Enables the
                                                                             // data-accelerator
                                                                             // AXI hang interrupt.
  output logic                                hang_det_data_accel_irq_test_o,  // Forces the
                                                                               // data-accelerator
                                                                               // AXI hang
                                                                               // interrupt high.
  output logic [19:0]                         hang_det_data_accel_threshold_o,  // Stall cycles
                                                                                // after which the
                                                                                // data-accelerator
                                                                                // AXI hang detector
                                                                                // fires.

  input  logic                                hang_det_sys_axi_irq_i,  // System AXI hang detector
                                                                       // interrupt, read back
                                                                       // through
                                                                       // HANG_DET_SYS_AXI_CTRL.irq.
  input  logic                                hang_det_sep_axi_irq_i,  // SEP AXI hang detector
                                                                       // interrupt, read back
                                                                       // through
                                                                       // HANG_DET_SEP_AXI_CTRL.irq.
  input  logic                                hang_det_data_accel_irq_i  // Data-accelerator AXI
                                                                         // hang detector
                                                                         // interrupt, read back
                                                                         // through the irq bit of
                                                                         // HANG_DET_DATA_ACCEL_CTRL.
);

  smc_base_config_reg_pkg::smc_base_config__in_t  hwif_in;
  smc_base_config_reg_pkg::smc_base_config__out_t hwif_out;

  assign hwif_in.HANG_DET_SYS_AXI_CTRL.irq.next    = hang_det_sys_axi_irq_i;
  assign hwif_in.HANG_DET_SEP_AXI_CTRL.irq.next    = hang_det_sep_axi_irq_i;
  assign hwif_in.HANG_DET_DATA_ACCEL_CTRL.irq.next = hang_det_data_accel_irq_i;

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

    .hwif_in        (hwif_in),
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
