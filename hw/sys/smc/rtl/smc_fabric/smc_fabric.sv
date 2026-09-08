// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// System Management Controller Fabric

`include "axi/assign.svh"
module smc_fabric #(
  parameter bit          NO_ADDR_REMAP   = 1'b1,
  parameter int unsigned SYS_IN_ID_WIDTH = 9,

  parameter int unsigned NumInboundFilters       = 16,
  parameter int unsigned NumOutboundFilters      = 16,
  parameter int unsigned MaxTrans                = smc_pkg::FABRIC_MAX_TRANS,
  parameter bit          FilterReqPipelineEnable = 1'b0,
  parameter bit          FilterRspPipelineEnable = 1'b0
) (
  input  logic clk_i,
  input  logic rst_ni,
  input  logic test_en_i,
  input  logic scan_rst_ni,

  // Configuration
  input  smc_pkg::smc_axi_addr_t global_base_addr_i,
  input  smc_pkg::smc_axi_addr_t local_base_addr_i,
  input  logic [31:0]            region_size_i,

  // Clock Gating
  input  logic                ob_filter_axi_cg_en_i,
  input  logic                ib_filter_axi_cg_en_i,
  input  logic                fabric_cg_en_i,
  input  smc_pkg::cg_hyster_t cg_hysteresis_i,

  // Input Fabric interfaces
  input  smc_pkg::smc_jtag_56_64_2_12_axi_req_t          axi_in_jtag_req_i,
  output smc_pkg::smc_jtag_56_64_2_12_axi_resp_t         axi_in_jtag_resp_o,
  input  smc_pkg::smc_cpu_mmio_axi_req_t                 axi_in_mmio_req_i,
  output smc_pkg::smc_cpu_mmio_axi_resp_t                axi_in_mmio_resp_o,
  input  smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_in_data_accel_req_i,
  output smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_in_data_accel_resp_o,
  input  smc_pkg::smc_axil_56_64_req_t                   axi_lite_log_req_i,
  output smc_pkg::smc_axil_56_64_resp_t                  axi_lite_log_resp_o,

  // System AXI Input
  input  smc_pkg::smc_sys_in_56_64_6_12_axi_req_t  sys_axi_in_req_i,
  output smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t sys_axi_in_resp_o,

  // SEP AXI Input
  input  smc_pkg::smc_sep_in_56_64_6_12_axi_req_t  sep_axi_in_req_i,
  output smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t sep_axi_in_resp_o,

  // Local Fabric interfaces to peripherals
  output smc_pkg::smc_local_32_64_8_12_axi_req_t  axi_front_port_req_o,
  input  smc_pkg::smc_local_32_64_8_12_axi_resp_t axi_front_port_rsp_i,
  output smc_pkg::smc_dfd_apb_req_t               apb_smc_dfd_reg_req_o,
  input  smc_pkg::smc_dfd_apb_resp_t              apb_smc_dfd_reg_resp_i,
  output smc_pkg::smc_local_32_64_8_12_axi_req_t  axi_data_accel_ctrl_req_o,
  input  smc_pkg::smc_local_32_64_8_12_axi_resp_t axi_data_accel_ctrl_rsp_i,
  output smc_pkg::smc_axil_32_32_req_t            axil_peripherals_req_o,
  input  smc_pkg::smc_axil_32_32_resp_t           axil_peripherals_resp_i,

  output smc_pkg::smc_axil_32_64_req_t  axil_aR_ctrl_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t axil_aR_ctrl_resp_i,
  output smc_pkg::smc_axil_32_64_req_t  axil_mR_ctrl_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t axil_mR_ctrl_resp_i,
  output smc_pkg::smc_axil_32_64_req_t  axil_xR_ctrl_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t axil_xR_ctrl_resp_i,
  output smc_pkg::smc_axil_32_64_req_t  axil_inbound_filter_ctrl_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t axil_inbound_filter_ctrl_resp_i,
  output smc_pkg::smc_axil_32_64_req_t  axil_outbound_filter_ctrl_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t axil_outbound_filter_ctrl_resp_i,
  output smc_pkg::smc_axil_32_64_req_t  axil_mailbox_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t axil_mailbox_resp_i,
  output smc_pkg::smc_axil_32_64_req_t  axil_smc_base_config_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t axil_smc_base_config_resp_i,
  output smc_pkg::smc_axil_32_64_req_t  axil_dfx_csr_req_o,
  input  smc_pkg::smc_axil_32_64_resp_t axil_dfx_csr_resp_i,

  // Output Fabric interfaces
  output smc_pkg::smc_sys_out_56_64_8_12_axi_req_t  axi_filtered_remapped_req_o,
  input  smc_pkg::smc_sys_out_56_64_8_12_axi_resp_t axi_filtered_remapped_resp_i,

  // CSR structs for filter configurations
  input  filter_ctrl_reg_pkg::filter_ctrl__out_t outbound_filter_ctrl_i [NumOutboundFilters-1:0],
  output filter_ctrl_reg_pkg::filter_ctrl__in_t  outbound_filter_status_o [NumOutboundFilters-1:0],
  input  filter_ctrl_reg_pkg::filter_ctrl__out_t inbound_filter_ctrl_i [NumInboundFilters-1:0],
  output filter_ctrl_reg_pkg::filter_ctrl__in_t  inbound_filter_status_o [NumInboundFilters-1:0],

  // CSR structs for remap configurations
  input  output_remap_reg_pkg::output_remap__out_t mR_ctrl_i [smc_pkg::NUM_MMODE_OUTPUT_REMAP_REGIONS-1:0],
  input  output_remap_reg_pkg::output_remap__out_t xR_ctrl_i [smc_pkg::NUM_XVISOR_OUTPUT_REMAP_REGIONS-1:0],
  input  alias_remap_reg_pkg::alias_remap__out_t   aR_ctrl_i [smc_pkg::NUM_ALIAS_REMAP_REGIONS-1:0],

  // Debug outputs
  output smc_pkg::remap_debug_t                 remap_debug_mmio_o,
  output smc_pkg::remap_debug_t                 remap_debug_jtag_o,
  output smc_pkg::remap_debug_t                 remap_debug_log_o,
  output smc_pkg::remap_debug_t                 remap_debug_dma_o,
  output logic [$clog2(NumInboundFilters)-1:0]  outbound_write_filter_hit_debug_o,
  output logic [$clog2(NumInboundFilters)-1:0]  outbound_read_filter_hit_debug_o,
  output logic [$clog2(NumOutboundFilters)-1:0] inbound_write_filter_hit_debug_o,
  output logic [$clog2(NumOutboundFilters)-1:0] inbound_read_filter_hit_debug_o,

  // Clock gater activity indicators
  output logic fabric_clk_active_o,
  output logic fabric_bus_active_o,
  output logic sys_out_filter_clk_active_o,
  output logic sys_out_filter_bus_active_o,
  output logic sys_in_filter_clk_active_o,
  output logic sys_in_filter_bus_active_o
);

  // Internal signals for fabric interconnections
  smc_pkg::smc_local_32_64_6_12_axi_req_t  axi_local_out_req;
  smc_pkg::smc_local_32_64_6_12_axi_resp_t axi_local_out_resp;
  smc_pkg::smc_56_64_6_12_axi_req_t  axi_to_output_fabric_req;
  smc_pkg::smc_56_64_6_12_axi_resp_t axi_to_output_fabric_resp;

  smc_pkg::smc_local_32_64_6_12_axi_req_t  filtered_sys_axi_out_req;
  smc_pkg::smc_local_32_64_6_12_axi_resp_t filtered_sys_axi_out_resp;
  smc_pkg::smc_local_32_64_6_12_axi_req_t  sep_axi_id_remap_req;
  smc_pkg::smc_local_32_64_6_12_axi_resp_t sep_axi_id_remap_resp;

  ////////////////////////
  // Input Fabric Logic //
  ////////////////////////

  smc_input_fabric #(
    .FilterReqPipelineEnable    (FilterReqPipelineEnable),
    .FilterRspPipelineEnable    (FilterRspPipelineEnable),
    .NumFilters                 (NumInboundFilters)
  ) u_smc_input_fabric (
    .clk_i                      (clk_i),
    .rst_ni                     (rst_ni),
    .test_en_i                  (test_en_i),
    .scan_rst_ni                (scan_rst_ni),

    .filter_axi_cg_en_i         (ib_filter_axi_cg_en_i),
    .cg_hysteresis_i            (cg_hysteresis_i),

    .global_base_addr_i         (global_base_addr_i),
    .local_base_addr_i          (local_base_addr_i),
    .region_size_i              (region_size_i),
    .axi_in_jtag_req_i          (axi_in_jtag_req_i),
    .axi_in_jtag_resp_o         (axi_in_jtag_resp_o),
    .axi_in_mmio_req_i          (axi_in_mmio_req_i),
    .axi_in_mmio_resp_o         (axi_in_mmio_resp_o),
    .axi_in_data_accel_req_i    (axi_in_data_accel_req_i),
    .axi_in_data_accel_resp_o   (axi_in_data_accel_resp_o),
    .axi_lite_log_req_i         (axi_lite_log_req_i),
    .axi_lite_log_resp_o        (axi_lite_log_resp_o),
    .axi_local_out_req_o        (axi_local_out_req),
    .axi_local_out_resp_i       (axi_local_out_resp),
    .axi_out_req_o              (axi_to_output_fabric_req),
    .axi_out_resp_i             (axi_to_output_fabric_resp),

    .sys_axi_in_req_i           (sys_axi_in_req_i),
    .sys_axi_in_resp_o          (sys_axi_in_resp_o),
    .filtered_sys_axi_out_req_o (filtered_sys_axi_out_req),
    .filtered_sys_axi_out_resp_i(filtered_sys_axi_out_resp),

    .sep_axi_in_req_i           (sep_axi_in_req_i),
    .sep_axi_in_resp_o          (sep_axi_in_resp_o),
    .sep_axi_id_remap_req_o     (sep_axi_id_remap_req),
    .sep_axi_id_remap_resp_i    (sep_axi_id_remap_resp),

    // CSR structs for filter configuration
    .filter_ctrl_i              (inbound_filter_ctrl_i),
    .filter_status_o            (inbound_filter_status_o),

    // CSR structs for remap configuration
    .aR_ctrl_i                  (aR_ctrl_i),

    // Debug outputs
    .remap_debug_mmio_o         (remap_debug_mmio_o),
    .remap_debug_jtag_o         (remap_debug_jtag_o),
    .remap_debug_log_o          (remap_debug_log_o),
    .remap_debug_dma_o          (remap_debug_dma_o),
    .write_filter_hit_debug_o   (outbound_write_filter_hit_debug_o),
    .read_filter_hit_debug_o    (outbound_read_filter_hit_debug_o),

    // Clock gater activity indicators
    .sys_in_filter_clk_active_o (sys_in_filter_clk_active_o),
    .sys_in_filter_bus_active_o (sys_in_filter_bus_active_o)
  );

  ///////////////////////
  // Local Fabric Logic //
  ///////////////////////

  smc_local_fabric u_smc_local_fabric (
    .clk_i                              (clk_i),
    .rst_ni                             (rst_ni),
    .test_en_i                          (test_en_i),
    .local_base_addr_i                  (local_base_addr_i),
    .region_size_i                      (region_size_i),
    .input_axi_req_i                    (filtered_sys_axi_out_req),
    .input_axi_rsp_o                    (filtered_sys_axi_out_resp),
    .sep_in_axi_req_i                   (sep_axi_id_remap_req),
    .sep_in_axi_rsp_o                   (sep_axi_id_remap_resp),
    .local_axi_req_i                    (axi_local_out_req),
    .local_axi_rsp_o                    (axi_local_out_resp),
    .axi_front_port_req_o               (axi_front_port_req_o),
    .axi_front_port_rsp_i               (axi_front_port_rsp_i),
    .apb_smc_dfd_reg_req_o              (apb_smc_dfd_reg_req_o),
    .apb_smc_dfd_reg_resp_i             (apb_smc_dfd_reg_resp_i),
    .axi_data_accel_ctrl_req_o          (axi_data_accel_ctrl_req_o),
    .axi_data_accel_ctrl_rsp_i          (axi_data_accel_ctrl_rsp_i),

    .periph_reg_req_o                   (axil_peripherals_req_o),
    .periph_reg_resp_i                  (axil_peripherals_resp_i),

    .axil_aR_ctrl_req_o                 (axil_aR_ctrl_req_o),
    .axil_aR_ctrl_resp_i                (axil_aR_ctrl_resp_i),
    .axil_mR_ctrl_req_o                 (axil_mR_ctrl_req_o),
    .axil_mR_ctrl_resp_i                (axil_mR_ctrl_resp_i),
    .axil_xR_ctrl_req_o                 (axil_xR_ctrl_req_o),
    .axil_xR_ctrl_resp_i                (axil_xR_ctrl_resp_i),
    .axil_inbound_filter_ctrl_req_o     (axil_inbound_filter_ctrl_req_o),
    .axil_inbound_filter_ctrl_resp_i    (axil_inbound_filter_ctrl_resp_i),
    .axil_outbound_filter_ctrl_req_o    (axil_outbound_filter_ctrl_req_o),
    .axil_outbound_filter_ctrl_resp_i   (axil_outbound_filter_ctrl_resp_i),
    .axil_mailbox_req_o                 (axil_mailbox_req_o),
    .axil_mailbox_resp_i                (axil_mailbox_resp_i),
    .axil_smc_base_config_req_o         (axil_smc_base_config_req_o),
    .axil_smc_base_config_resp_i        (axil_smc_base_config_resp_i),
    .axil_dfx_csr_req_o                 (axil_dfx_csr_req_o),
    .axil_dfx_csr_resp_i                (axil_dfx_csr_resp_i)
  );

  ////////////////////////
  // Output Fabric Logic //
  ////////////////////////

  smc_output_fabric #(
    .NO_ADDR_REMAP             (NO_ADDR_REMAP),
    .NumFilters                (NumOutboundFilters),
    .MaxTrans                  (MaxTrans),
    .FilterReqPipelineEnable   (FilterReqPipelineEnable),
    .FilterRspPipelineEnable   (FilterRspPipelineEnable)
  ) u_smc_output_fabric (
    .clk_i                        (clk_i),
    .rst_ni                       (rst_ni),
    .test_en_i                    (test_en_i),
    .global_base_addr_i           (global_base_addr_i),
    .local_base_addr_i            (local_base_addr_i),

    .filter_axi_cg_en_i           (ob_filter_axi_cg_en_i),
    .fabric_cg_en_i               (fabric_cg_en_i),
    .cg_hysteresis_i              (cg_hysteresis_i),

    // AXI Buses
    .axi_req_i                    (axi_to_output_fabric_req),
    .axi_resp_o                   (axi_to_output_fabric_resp),
    .axi_filtered_remapped_req_o  (axi_filtered_remapped_req_o),
    .axi_filtered_remapped_resp_i (axi_filtered_remapped_resp_i),

    // CSR structs for filter configurations
    .filter_ctrl_i                (outbound_filter_ctrl_i),
    .filter_status_o              (outbound_filter_status_o),

    // CSR structs for remap configurations
    .mR_ctrl_i                    (mR_ctrl_i),
    .xR_ctrl_i                    (xR_ctrl_i),

    // Debug outputs
    .write_filter_hit_debug_o     (inbound_write_filter_hit_debug_o),
    .read_filter_hit_debug_o      (inbound_read_filter_hit_debug_o),

    // Clock gater activity indicators
    .fabric_clk_active_o         (fabric_clk_active_o),
    .fabric_bus_active_o         (fabric_bus_active_o),
    .sys_out_filter_clk_active_o (sys_out_filter_clk_active_o),
    .sys_out_filter_bus_active_o (sys_out_filter_bus_active_o)
  );

endmodule
