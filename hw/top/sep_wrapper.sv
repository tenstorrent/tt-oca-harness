// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SEP Wrapper -- OSS reference top
//
// Instantiates the bare sep.sv core alongside sep_ip_integration.sv (the
// open-source macro/model set for its technology-specific IP) and wires
// the two together, for standalone SEP reference simulation and
// verification. See hw/top/README.md.
//-----------------------------------------------------------------------------

module sep_wrapper
  import sep_pkg::*;
  import secure_dma_reg_pkg::*;
  import sep_crypto_pkg::*;
  import sep_io_pkg::*;
  import sep_efuse_pkg::*;
  import km_intf_pkg::*;
#(
  parameter bit KM_LATCHED_MEM_RDATA = 1'b1,
  parameter bit ABR_MASKING_EN = 1'b1,
  parameter int unsigned ABR_SRAM_LATENCY = 1,
  parameter int unsigned EXT_TRNG_NUM_AXIS = sep_crypto_pkg::SEP_CRYPTO_EDN_ENDPOINT_COUNT,
  parameter bit [255:0] SEP_SEC_DISABLE_TOKEN = 256'b0
) (
  input  logic clk_i,
  input  logic clk_wdt_i,
  input  logic clk_ref_i,
  input  logic rst_ni,
  input  logic dbg_rstb_i,
  input  logic wdt_rst_ni,

  output logic wdt_timer_rst_req_o,

  input  logic jtag_tck_i,
  input  logic jtag_tms_i,
  input  logic jtag_tdi_i,
  input  logic jtag_trst_ni,
  output logic jtag_tdo_o,
  output logic jtag_tdoEn_o,

  input  sep_pkg::jtag_sep_reset_ctrl_t jtag_sep_reset_ctrl_i,

  input  sep_efuse_pkg::efuse_axil_req_t  axil_sep_otp_jtag_req_i,
  output sep_efuse_pkg::efuse_axil_resp_t axil_sep_otp_jtag_resp_o,

  input  logic mpc_debug_halt_req_i,
  input  logic mpc_debug_run_req_i,
  input  logic mpc_reset_run_req_i,

  input  logic cpu_halt_req_i,
  input  logic cpu_run_req_i,

  input  logic test_en_i,
  input  logic scan_rst_ni,

  input  logic ext_boot_seq_done_i,

  input  logic        dmi_core_enable,
  input  logic        dmi_uncore_enable,
  output logic        dmi_uncore_en,
  output logic        dmi_uncore_wr_en,
  output logic [6:0]  dmi_uncore_addr,
  output logic [31:0] dmi_uncore_wdata,
  input  logic [31:0] dmi_uncore_rdata,
  output logic        dmi_active,

  output sep_cpu_trace_t sep_cpu_trace,

  // CPU lockstep control/status
  input  sep_lockstep_ctrl_t   lockstep_ctrl_i,
  output sep_lockstep_status_t lockstep_status_o,

  input logic [31:1] rst_vec,
  input logic [31:1] jtag_id,

  input logic                      timer_int,
  input logic                      soft_int,
  input logic [sep_pkg::NUM_EXTERNAL_IRQS-1:0] sep_ext_interrupts_i,

  output sep_pkg::sep_system_peripherals_outbound_axi_req_t  smn_outbound_axi_req_o,
  input  sep_pkg::sep_system_peripherals_outbound_axi_resp_t smn_outbound_axi_resp_i,

  input  sep_pkg::sep_system_peripherals_internal_axi_req_t  smn_inbound_axi_req_i,
  output sep_pkg::sep_system_peripherals_internal_axi_resp_t smn_inbound_axi_resp_o,

  output sep_pkg::sep_system_peripherals_internal_axi_req_t  sep_ext_to_smc_axi_req_o,
  input  sep_pkg::sep_system_peripherals_internal_axi_resp_t sep_ext_to_smc_axi_resp_i,

  input logic entropy_rosc_sample_clk_i,

  output logic [1:0] lcc_demote_state_1_o,
  output logic [1:0] lcc_demote_state_2_o,

  output sep_io_spi_req_t sep_io_spi_req_o,
  input  sep_io_spi_rsp_t sep_io_spi_rsp_i,

  output logic [2*sep_pkg::LC_STATE_BIT_WIDTH-1:0] lc_state_o,
  output sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable_o,
  output logic sep_fuse_dft_disable_o,
  output logic smc_fuse_dft_disable_o,
  output logic lc_sigint_err_o,
  output logic security_disable_o,

  output logic [sep_pkg::NUM_MAILBOXES-1:0] smc_mailbox_interrupt_o,

  input  logic smc_fuse_sense_done_i,
  output logic sep_fuse_sense_done_o,

  input logic secure_tm_req_i,

  input  logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] smc_global_base_addr_i,
  input  logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] smc_region_size_i,

  output logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_global_base_addr_o,
  output logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_region_size_o,

  output logic km_unrecoverable_err_o,
  output logic km_recoverable_err_o,

  output logic [383:0] ext_debug_bus_o,

  output logic secure_tm_o,

  output logic [15:0] efuse_debug_bus_o
);

  /////////////////////////////////////////////////
  // Internal signals (sep <-> sep_ip_integration) //
  /////////////////////////////////////////////////

  sep_efuse_pkg::efuse_axil_req_t    efuse_bank_ctrl_req;
  sep_efuse_pkg::efuse_axil_resp_t   efuse_bank_ctrl_resp;
  sep_efuse_pkg::fuse_command_req_t  efuse_shim_command_req;
  sep_efuse_pkg::fuse_command_resp_t efuse_shim_command_resp;

  sep_sram_req_t sep_sram_req;
  sep_sram_rsp_t sep_sram_rsp;

  sep_sram_req_t sep_boot_rom_req;
  sep_sram_rsp_t sep_boot_rom_rsp;

  sep_cpu_tcm_req_t sep_cpu_tcm_req;
  sep_cpu_tcm_rsp_t sep_cpu_tcm_rsp;

  logic wdt_timer_rst_req;

  sep_crypto_pkg::abr_mem_req_t abr_mem_req;
  sep_crypto_pkg::abr_mem_rsp_t abr_mem_rsp;

  km_intf_pkg::km_rom_mem_req_t  km_rom_mem_req;
  km_intf_pkg::km_rom_mem_rsp_t  km_rom_mem_rsp;
  km_intf_pkg::km_sram_mem_req_t km_sram_mem_req;
  km_intf_pkg::km_sram_mem_rsp_t km_sram_mem_rsp;

  sep_32_64_6_12_axi_req_t  axi_extension_axi_req;
  sep_32_64_6_12_axi_resp_t axi_extension_axi_resp;

  // TRNG AXI-Lite between sep and sep_ip_integration
  sep_pkg::sep_32_32_axil_req_t  ext_trng_axil_req;
  sep_pkg::sep_32_32_axil_resp_t ext_trng_axil_resp;

  // TRNG AXI-Stream between sep_ip_integration and sep
  ext_trng_axis_req_t ext_trng_axis_req [EXT_TRNG_NUM_AXIS-1:0];
  ext_trng_axis_rsp_t ext_trng_axis_rsp [EXT_TRNG_NUM_AXIS-1:0];

  logic ext_trng_irq;

  // OTBN SRAM interfaces (sep <-> sep_ip_integration)
  sep_crypto_pka_imem_sram_req_t sep_crypto_pka_imem_sram_req;
  sep_crypto_pka_imem_sram_rsp_t sep_crypto_pka_imem_sram_rsp;
  sep_crypto_pka_dmem_sram_req_t sep_crypto_pka_dmem_sram_req;
  sep_crypto_pka_dmem_sram_rsp_t sep_crypto_pka_dmem_sram_rsp;

  assign wdt_timer_rst_req_o = wdt_timer_rst_req;

  /////////////////////
  // SEP core        //
  /////////////////////

  sep #(
    .KM_LATCHED_MEM_RDATA  (KM_LATCHED_MEM_RDATA),
    .ABR_MASKING_EN        (ABR_MASKING_EN),
    .ABR_SRAM_LATENCY      (ABR_SRAM_LATENCY),
    .EXT_TRNG_NUM_AXIS     (EXT_TRNG_NUM_AXIS),
    .SEP_SEC_DISABLE_TOKEN (SEP_SEC_DISABLE_TOKEN)
  ) u_sep (
    .clk_i,
    .clk_ref_i,
    .clk_wdt_i,
    .rst_ni,
    .dbg_rstb_i,
    .wdt_rst_ni,
    .jtag_tck_i,
    .jtag_tms_i,
    .jtag_tdi_i,
    .jtag_trst_ni,
    .jtag_tdo_o,
    .jtag_tdoEn_o,
    .jtag_sep_reset_ctrl_i,
    .axil_sep_otp_jtag_req_i,
    .axil_sep_otp_jtag_resp_o,
    .mpc_debug_halt_req_i,
    .mpc_debug_run_req_i,
    .mpc_reset_run_req_i,
    .cpu_halt_req_i,
    .cpu_run_req_i,
    .test_en_i,
    .scan_rst_ni,
    .ext_boot_seq_done_i,
    .dmi_core_enable,
    .dmi_uncore_enable,
    .dmi_uncore_en,
    .dmi_uncore_wr_en,
    .dmi_uncore_addr,
    .dmi_uncore_wdata,
    .dmi_uncore_rdata,
    .dmi_active,
    .sep_cpu_trace,
    .lockstep_ctrl_i,
    .lockstep_status_o,
    .jtag_id,
    .timer_int,
    .soft_int,
    .smn_outbound_axi_req_o,
    .smn_outbound_axi_resp_i,
    .smn_inbound_axi_req_i,
    .smn_inbound_axi_resp_o,
    .sep_ext_to_smc_axi_req_o,
    .sep_ext_to_smc_axi_resp_i,
    .entropy_rosc_sample_clk_i,
    .lcc_demote_state_1_o,
    .lcc_demote_state_2_o,
    .sep_io_spi_req_o,
    .sep_io_spi_rsp_i,
    .lc_state_o,
    .dbg_disable_o,
    .sep_fuse_dft_disable_o,
    .smc_fuse_dft_disable_o,
    .lc_sigint_err_o,
    .security_disable_o,
    .secure_tm_o,
    .smc_mailbox_interrupt_o,
    .smc_fuse_sense_done_i,
    .sep_fuse_sense_done_o,
    .secure_tm_req_i,
    .smc_global_base_addr_i,
    .smc_region_size_i,
    .sep_global_base_addr_o,
    .sep_region_size_o,
    .km_unrecoverable_err_o,
    .km_recoverable_err_o,
    .ext_debug_bus_o,
    .extintsrc_req       (sep_ext_interrupts_i),

    .wdt_timer_rst_req_o (wdt_timer_rst_req),


    .sep_cpu_tcm_req_o (sep_cpu_tcm_req),
    .sep_cpu_tcm_rsp_i (sep_cpu_tcm_rsp),

    .sep_sram_req,
    .sep_sram_rsp,
    .sep_boot_rom_req,
    .sep_boot_rom_rsp,
    .sep_crypto_pka_imem_sram_req,
    .sep_crypto_pka_imem_sram_rsp,
    .sep_crypto_pka_dmem_sram_req,
    .sep_crypto_pka_dmem_sram_rsp,
    .abr_mem_req,
    .abr_mem_rsp,
    .ext_trng_axil_req_o  (ext_trng_axil_req),
    .ext_trng_axil_resp_i (ext_trng_axil_resp),

    .ext_trng_axis_req_i (ext_trng_axis_req),
    .ext_trng_axis_rsp_o (ext_trng_axis_rsp),

    .ext_trng_irq_i (ext_trng_irq),

    .km_rom_mem_req_o (km_rom_mem_req),
    .km_rom_mem_rsp_i (km_rom_mem_rsp),
    .km_sram_mem_req_o (km_sram_mem_req),
    .km_sram_mem_rsp_i (km_sram_mem_rsp),

    .efuse_bank_ctrl_req_o     (efuse_bank_ctrl_req),
    .efuse_bank_ctrl_resp_i    (efuse_bank_ctrl_resp),
    .efuse_shim_command_req_o  (efuse_shim_command_req),
    .efuse_shim_command_resp_i (efuse_shim_command_resp),

    .sep_external_axi_req_o   (axi_extension_axi_req),
    .sep_external_axi_resp_i  (axi_extension_axi_resp)
  );

  /////////////////////////
  // SEP IP Integration  //
  /////////////////////////

  sep_ip_integration #(
    .EXT_TRNG_NUM_AXIS (EXT_TRNG_NUM_AXIS),
    .ABR_MASKING_EN    (ABR_MASKING_EN)
  ) u_sep_ip_integration (
    .clk_i  (clk_i),
    .rst_ni (rst_ni),


    .test_en_i (test_en_i),

    .sep_sram_req (sep_sram_req),
    .sep_sram_rsp (sep_sram_rsp),

    .sep_boot_rom_req (sep_boot_rom_req),
    .sep_boot_rom_rsp (sep_boot_rom_rsp),

    .sep_cpu_tcm_req_i (sep_cpu_tcm_req),
    .sep_cpu_tcm_rsp_o (sep_cpu_tcm_rsp),

    .sep_crypto_pka_imem_sram_req (sep_crypto_pka_imem_sram_req),
    .sep_crypto_pka_imem_sram_rsp (sep_crypto_pka_imem_sram_rsp),
    .sep_crypto_pka_dmem_sram_req (sep_crypto_pka_dmem_sram_req),
    .sep_crypto_pka_dmem_sram_rsp (sep_crypto_pka_dmem_sram_rsp),

    .abr_mem_req_i (abr_mem_req),
    .abr_mem_rsp_o (abr_mem_rsp),

    .km_rom_mem_req_i (km_rom_mem_req),
    .km_rom_mem_rsp_o (km_rom_mem_rsp),
    .km_sram_mem_req_i (km_sram_mem_req),
    .km_sram_mem_rsp_o (km_sram_mem_rsp),

    .efuse_bank_ctrl_req_i     (efuse_bank_ctrl_req),
    .efuse_bank_ctrl_resp_o    (efuse_bank_ctrl_resp),
    .efuse_shim_command_req_i  (efuse_shim_command_req),
    .efuse_shim_command_resp_o (efuse_shim_command_resp),

    .ext_trng_axil_req_i  (ext_trng_axil_req),
    .ext_trng_axil_resp_o (ext_trng_axil_resp),

    .ext_trng_axis_req_o (ext_trng_axis_req),
    .ext_trng_axis_rsp_i (ext_trng_axis_rsp),

    .ext_trng_irq_o (ext_trng_irq),

    .axi_extension_axi_req_i  (axi_extension_axi_req),
    .axi_extension_axi_resp_o (axi_extension_axi_resp),

    .efuse_debug_bus_o (efuse_debug_bus_o)
  );

endmodule
