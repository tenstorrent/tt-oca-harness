// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// System Management Unit

module smu #(
  parameter int unsigned MAX_TRANS = 2,
  // Vendor eFuse shim address sizes
  parameter int unsigned SEP_EFUSE_SHIM_SIZE = 'h4,
  parameter int unsigned SMC_EFUSE_SHIM_SIZE = 'h44,
  parameter smu_pkg::smu_cfg_t Cfg = smu_pkg::DefaultCfg,

  // SEP (Secure Execution Processor) enable. Declared int unsigned (not bit) so VC
  // SpyGlass `elaborate -param SEP=0` can override it; -gfile cannot override bit-typed params.
  parameter int unsigned  SEP                   = 1,

  // SEP security-disable token digest. Tied off to '0 at the SMU level; to be
  // replaced with the actual token digest embedded in the netlist at synthesis.
  parameter bit [255:0]   SEP_SEC_DISABLE_TOKEN = 256'b0,

  // Number of external-TRNG AXI-stream endpoints between SEP crypto and the TRNG.
  parameter int unsigned  EXT_TRNG_NUM_AXIS     = 3,

  // Type parameters for SMC CPU memory interfaces (cannot be in packed struct)
  parameter  type         smc_rom_req_t             = chipyard_4core_mem_pkg::rom_req_t,
  parameter  type         smc_rom_rsp_t             = chipyard_4core_mem_pkg::rom_rsp_t,
  parameter  type         smc_scratch_ram_req_t     = chipyard_4core_mem_pkg::scratch_ram_req_t,
  parameter  type         smc_scratch_ram_rsp_t     = chipyard_4core_mem_pkg::scratch_ram_rsp_t,
  parameter  type         smc_l1_icache_tag_req_t   = chipyard_4core_mem_pkg::l1_icache_tag_req_t,
  parameter  type         smc_l1_icache_tag_rsp_t   = chipyard_4core_mem_pkg::l1_icache_tag_rsp_t,
  parameter  type         smc_l1_icache_data_req_t  = chipyard_4core_mem_pkg::l1_icache_data_req_t,
  parameter  type         smc_l1_icache_data_rsp_t  = chipyard_4core_mem_pkg::l1_icache_data_rsp_t,
  parameter  type         smc_l1_dcache_tag_req_t   = chipyard_4core_mem_pkg::l1_dcache_tag_req_t,
  parameter  type         smc_l1_dcache_tag_rsp_t   = chipyard_4core_mem_pkg::l1_dcache_tag_rsp_t,
  parameter  type         smc_l1_dcache_data_req_t  = chipyard_4core_mem_pkg::l1_dcache_data_req_t,
  parameter  type         smc_l1_dcache_data_rsp_t  = chipyard_4core_mem_pkg::l1_dcache_data_rsp_t,

  // CPU cluster localparams
  localparam int unsigned NUM_CPU_CORES         = smc_4core_cpu_pkg::NUM_CPU_CORES,
  localparam int unsigned NUM_CPU_INTERRUPTS    = smc_4core_cpu_pkg::NUM_CPU_INTERRUPTS,
  localparam int unsigned NUM_EXT_INTERRUPTS    = smc_4core_cpu_pkg::NUM_EXT_INTERRUPTS,

  localparam int unsigned NUM_SRAM_BANKS        = chipyard_4core_mem_pkg::NUM_SRAM_BANKS,
  localparam int unsigned NUM_ICACHE_TAG_BANKS  = chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS,
  localparam int unsigned NUM_ICACHE_DATA_BANKS = chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS,
  localparam int unsigned NUM_DCACHE_TAG_BANKS  = chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS,
  localparam int unsigned NUM_DCACHE_DATA_BANKS = chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS,

  // Type parameter for the external IC_RESET TDR slice exposed to the SMU caller.
  parameter type  ic_reset_ext_t = jtag_tap_pkg::jtag_ic_reset_default_t,

  // Cross trigger configuration localparams
  // SMU exposes fewer ports than DTP: SMU [7:0] maps to DTP [9:2], with DTP [1:0] reserved for SMC
  localparam int unsigned  XTRIG_NUM_CTP          = dtp_pkg::DEFAULT_NUM_CTP,
  localparam int unsigned  XTRIG_NUM_INT_CT       = dtp_pkg::DEFAULT_NUM_INT_CT - 2,   // SMU exposes 8; DTP [1:0] reserved for SMC
  localparam int unsigned  XTRIG_NUM_CLK_STOP_REQ = dtp_pkg::DEFAULT_NUM_CLK_STOP_REQ - 1,  // SMU exposes 8; DTP [0] reserved for SMC
  localparam int unsigned  DTP_XTRIG_NUM_INT_CT = dtp_pkg::DEFAULT_NUM_INT_CT,
  localparam int unsigned  DTP_XTRIG_NUM_CLK_STOP_REQ = dtp_pkg::DEFAULT_NUM_CLK_STOP_REQ,
  localparam int unsigned  JTAG_NUM_EXTRA_STAP_PORTS = (Cfg.JTAG_NUM_EXTRA_STAPS > 0) ? Cfg.JTAG_NUM_EXTRA_STAPS : 1,
  localparam logic [DTP_XTRIG_NUM_INT_CT-1:0]  DTP_XTRIG_INT_CT_MODE = {Cfg.XTRIG_INT_CT_MODE, 2'b00}  // Bits [1:0] = 0 for SMC pulse sync
) (
  // Clock and Reset
  input  logic  clk_smu_i,
  input  logic  clk_ref_i,
  input  logic  clk_periph_i,
  input  logic  rst_cold_ni,

  // Stable Cold Reset
  output logic  rst_cold_stable_ref_clk_no,

  // Powergood signal
  input  logic  powergood_i,

  // Primary JTAG TAP Interface
  input  prim_jtag_pkg::jtag_tap_ctrl_t  jtag_ptap_client_tap_ctrl_i,
  input  logic            jtag_ptap_client_tdi_i,
  output logic            jtag_ptap_client_tdo_o,
  output logic            jtag_ptap_client_tdo_oen_o,

  // Boundary Scan Interface
  output prim_jtag_pkg::jtag_scan_ctrl_t  jtag_bsr_host_scan_ctrl_o,
  input  logic             jtag_bsr_host_scan_in_i,
  output logic             jtag_bsr_host_scan_out_o,

  // I/O STAP Interface
  output prim_jtag_pkg::jtag_tap_ctrl_t  jtag_stap_io_host_tap_ctrl_o,
  input  logic            jtag_stap_io_host_tdi_i,
  output logic            jtag_stap_io_host_tdo_o,
  output logic            jtag_stap_io_host_tdo_oen_o,

  // Extra STAP Interfaces
  output prim_jtag_pkg::jtag_tap_ctrl_t  jtag_stap_extra_host_tap_ctrl_o [JTAG_NUM_EXTRA_STAP_PORTS-1:0],
  input  logic            jtag_stap_extra_host_tdi_i      [JTAG_NUM_EXTRA_STAP_PORTS-1:0],
  output logic            jtag_stap_extra_host_tdo_o      [JTAG_NUM_EXTRA_STAP_PORTS-1:0],
  output logic            jtag_stap_extra_host_tdo_oen_o  [JTAG_NUM_EXTRA_STAP_PORTS-1:0],

  // Extended STAP Scan Interface
  output prim_jtag_pkg::jtag_scan_ctrl_t  jtag_stap_host_scan_ctrl_o,
  input  logic             jtag_stap_host_scan_in_i,
  output logic             jtag_stap_host_scan_out_o,

  // DFD iJTAG Interface
  output prim_jtag_pkg::jtag_scan_ctrl_t  jtag_dfd_host_scan_ctrl_o,
  input  logic             jtag_dfd_host_scan_in_i,
  output logic             jtag_dfd_host_scan_out_o,

  // Secure DFT iJTAG Interface
  output prim_jtag_pkg::jtag_scan_ctrl_t  jtag_dft_secure_host_scan_ctrl_o,
  input  logic             jtag_dft_secure_host_scan_in_i,
  output logic             jtag_dft_secure_host_scan_out_o,

  // Non-secure DFT iJTAG Interface
  output prim_jtag_pkg::jtag_scan_ctrl_t  jtag_dft_host_scan_ctrl_o,
  input  logic             jtag_dft_host_scan_in_i,
  output logic             jtag_dft_host_scan_out_o,

  // Clock Control
  output logic  dtp_stop_clks_o,

  // JTAG State Outputs
  output jtag_tap_pkg::tap_state_e                      jtag_ptap_state_o,
  output jtag_inst_reg_pkg::jtag_instruction_decoded_e  jtag_ptap_inst_decoded_o,

  // JTAG External IC_RESET TDR Slice (typed packed struct; `.ovrd` + `.val` halves)
  output ic_reset_ext_t  jtag_ic_reset_ext_o,

  // Cross Trigger Matrix Interface (ports [7:0] exposed; ports [1:0] internal to SMC)
  output logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_src_req_o,
  input  logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_src_ack_i,
  input  logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_dst_req_i,
  output logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_dst_ack_o,

  // Clock Stop Request Interface (ports [7:0] exposed; port [0] internal to SMC)
  input  logic [XTRIG_NUM_CLK_STOP_REQ-1:0]  xtrig_clk_stop_req_i,

  // Cross Trigger Port GPIO Interface (16 CTPs)
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_out_dout_o,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_out_dout_en_o,
  input  logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_out_din_i,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_out_din_en_o,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_in_dout_o,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_in_dout_en_o,
  input  logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_in_din_i,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_in_din_en_o,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_in_dout_o,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_in_dout_en_o,
  input  logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_in_din_i,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_in_din_en_o,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_out_dout_o,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_out_dout_en_o,
  input  logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_out_din_i,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_out_din_en_o,

  // SMC Resets
  output logic  rst_primary_ref_clk_no,
  output logic  rst_primary_smc_clk_no,
  output logic  rst_primary_periph_clk_no,

  // =========================================================================
  // SMU AXI Crossbar External Ports (toward SMN)
  // =========================================================================
  input  smu_axi_xbar_pkg::axi_56_64_req_t   smu_axi_in_req_i,
  output smu_axi_xbar_pkg::axi_56_64_resp_t  smu_axi_in_resp_o,
  output smu_axi_xbar_pkg::axi_out_req_t      smu_axi_out_req_o,
  input  smu_axi_xbar_pkg::axi_out_resp_t     smu_axi_out_resp_i,

  // AXI-L interface for adopter peripheral external
  output smc_pkg::smc_axil_32_32_req_t  smc_external_req_o,
  input  smc_pkg::smc_axil_32_32_resp_t smc_external_resp_i,

  // eFuse Interface
  output smc_pkg::smc_axil_32_32_req_t      smc_efuse_bank_ctrl_req_o,
  input  smc_pkg::smc_axil_32_32_resp_t     smc_efuse_bank_ctrl_resp_i,
  output smc_efuse_pkg::fuse_command_req_t    smc_efuse_shim_command_req_o,
  input  smc_efuse_pkg::fuse_command_resp_t   smc_efuse_shim_command_resp_i,
  output smc_efuse_pkg::efuse_map_t           smc_shadow_regs_o,

  // GPIO Data Signals
  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0]  lsio_interface_select_o,
  input  logic [smc_pkg::NUM_GPIO_WRAPS-1:0]  pad2core_i,
  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0]  core2pad_o,
  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0]  pad2core_en_o,
  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0]  core2pad_en_o,

  // GPIO External Pins
  input  logic  rst_cool_n_from_pin_i,

  // ATB Telemetry
  input  logic  clk_telemetry_i,
  input  logic  rst_telemetry_ni,
  input  telemetry_receiver_pkg::telemetry_data_t [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0]  telemetry_atdata_i,
  input  telemetry_receiver_pkg::atb_id_t [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0]  telemetry_atid_i,
  output logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0]  telemetry_atready_o,
  input  logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0]  telemetry_atvalid_i,
  output logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0]  telemetry_afvalid_o,
  input  logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0]  telemetry_afready_i,

  // DED/WDT
  output logic  smc_cluster_ded_o,
  output logic  smc_wdt_first_timeout_o,
  output logic  smc_wdt_second_timeout_o,

  // SMC and SEP apertures (from the respective CSRs). Surfaced at the
  // boundary so external address decoders / NoC routing logic can observe
  // both halves of each aperture symmetrically. Tied to '0 when SEP=0.
  output smc_pkg::smc_axi_addr_t                                   smc_global_base_o,
  output logic [31:0]                                              smc_region_size_o,
  output logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_global_base_o,
  output logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_region_size_o,

  // External Interrupts
  input  logic [Cfg.NUM_INT_TO_SMC-1:0]  smc_ext_interrupts_i,

  // Fuse Signals
  output logic  smc_fuse_sense_done_o,
  output logic  smc_fuse_reset_n_delayed_o,

  // External boot / memory-repair signals
  output logic  skip_mem_repair_o,
  input  logic  ext_boot_seq_done_i,

  // Lifecycle State (driven by SEP)
  output logic [2*smc_pkg::LC_STATE_WIDTH-1:0]  lc_state_o,
  output logic                                  lc_sigint_err_o,

  // NDM Reset signals
  input  logic [smc_config_pkg::CPU_CLUSTER_COUNT - 1:0]  smc_ndmreset_request_i,
  output logic [smc_config_pkg::CPU_CLUSTER_COUNT - 1:0]  smc_ndmreset_process_o,

  // Mailbox Interrupts
  output logic [smc_pkg::NUM_MAILBOXES-1:0]  smc_ext_mailbox_interrupts_o,

  // Reset Unit Signals
  input  logic  cfg_flr_pf_active_i,
  output logic [31:0]  isolate_req_o,
  input  logic [31:0]  ss_reset_complete_i,
  output logic [31:0]  ss_config_o,
  output smc_reset_unit_pkg::reset_ctrl_t ss_reset_ctrl_o[31:0],
  output logic  sync_irq_o,

  // CPU Memory Signals
  output smc_rom_req_t             smc_rom_intf_req_o,
  input  smc_rom_rsp_t             smc_rom_intf_rsp_i,
  output smc_scratch_ram_req_t     smc_scratch_ram_intf_req_o [NUM_SRAM_BANKS-1:0],
  input  smc_scratch_ram_rsp_t     smc_scratch_ram_intf_rsp_i [NUM_SRAM_BANKS-1:0],
  output smc_l1_icache_tag_req_t   smc_l1_icache_tag_intf_req_o [NUM_ICACHE_TAG_BANKS-1:0],
  input  smc_l1_icache_tag_rsp_t   smc_l1_icache_tag_intf_rsp_i [NUM_ICACHE_TAG_BANKS-1:0],
  output smc_l1_icache_data_req_t  smc_l1_icache_data_intf_req_o [NUM_ICACHE_DATA_BANKS-1:0],
  input  smc_l1_icache_data_rsp_t  smc_l1_icache_data_intf_rsp_i [NUM_ICACHE_DATA_BANKS-1:0],
  output smc_l1_dcache_tag_req_t   smc_l1_dcache_tag_intf_req_o [NUM_DCACHE_TAG_BANKS-1:0],
  input  smc_l1_dcache_tag_rsp_t   smc_l1_dcache_tag_intf_rsp_i [NUM_DCACHE_TAG_BANKS-1:0],
  output smc_l1_dcache_data_req_t  smc_l1_dcache_data_intf_req_o [NUM_DCACHE_DATA_BANKS-1:0],
  input  smc_l1_dcache_data_rsp_t  smc_l1_dcache_data_intf_rsp_i [NUM_DCACHE_DATA_BANKS-1:0],

  // Memory Init
  input  logic  smc_disable_sram_auto_init_i,
  output logic  smc_init_mem_done_o,

  // System Timer OCTS Interface
  input  logic  chiplet_is_primary_i,
  output logic [63:0]  timer_count_o,

  // Trace Memory
  output trace_mem_pkg::SinkMemPktIn_s [tn_pkg::TRC_RAM_INSTANCES-1:0]  trace_mem_req_o,
  input  trace_mem_pkg::SinkMemPktOut_s [tn_pkg::TRC_RAM_INSTANCES-1:0]  trace_mem_resp_i,

  // Test Mode
  input  logic  test_en_i,
  input  logic  scan_rst_ni,

  // DFT status indicators
  input  logic mem_repair_done_i,
  input  logic mem_repair_success_i,
  input  logic mem_repair_abort_i,
  input  logic mbist_done_i,
  input  logic mbist_pass_i,
  input  logic mbist_abort_i,

  // =========================================================================
  // SEP Passthrough Ports (to/from sep_ip_integration in smu_wrapper)
  // =========================================================================
  output sep_pkg::sep_sram_req_t     sep_sram_req_o,
  input  sep_pkg::sep_sram_rsp_t     sep_sram_rsp_i,
  output sep_pkg::sep_sram_req_t     sep_boot_rom_req_o,
  input  sep_pkg::sep_sram_rsp_t     sep_boot_rom_rsp_i,
  output sep_pkg::sep_cpu_tcm_req_t  sep_cpu_tcm_req_o,
  input  sep_pkg::sep_cpu_tcm_rsp_t  sep_cpu_tcm_rsp_i,

  output sep_efuse_pkg::efuse_axil_req_t    sep_efuse_bank_ctrl_req_o,
  input  sep_efuse_pkg::efuse_axil_resp_t   sep_efuse_bank_ctrl_resp_i,
  output sep_efuse_pkg::fuse_command_req_t  sep_efuse_shim_command_req_o,
  input  sep_efuse_pkg::fuse_command_resp_t sep_efuse_shim_command_resp_i,

  output sep_crypto_pkg::sep_crypto_pka_imem_sram_req_t  sep_crypto_pka_imem_sram_req_o,
  input  sep_crypto_pkg::sep_crypto_pka_imem_sram_rsp_t  sep_crypto_pka_imem_sram_rsp_i,
  output sep_crypto_pkg::sep_crypto_pka_dmem_sram_req_t  sep_crypto_pka_dmem_sram_req_o,
  input  sep_crypto_pkg::sep_crypto_pka_dmem_sram_rsp_t  sep_crypto_pka_dmem_sram_rsp_i,

  // Adams Bridge external SRAM interface (tech macros in sep_ip_integration)
  output sep_crypto_pkg::abr_mem_req_t                   abr_mem_req_o,
  input  sep_crypto_pkg::abr_mem_rsp_t                   abr_mem_rsp_i,

  // External TRNG
  output sep_pkg::sep_32_32_axil_req_t       ext_trng_axil_req_o,
  input  sep_pkg::sep_32_32_axil_resp_t      ext_trng_axil_resp_i,
  input  sep_crypto_pkg::ext_trng_axis_req_t ext_trng_axis_req_i [EXT_TRNG_NUM_AXIS-1:0],
  output sep_crypto_pkg::ext_trng_axis_rsp_t ext_trng_axis_rsp_o [EXT_TRNG_NUM_AXIS-1:0],
  input  logic                               ext_trng_irq_i,

  // Ring-oscillator sample clock for SEP entropy_source (async to clk_i)
  input  logic                               entropy_rosc_sample_clk_i,

  // SEP OpenTitan SPI request
  output sep_io_pkg::sep_io_spi_req_t        sep_io_spi_req_o,

  output km_intf_pkg::km_rom_mem_req_t   sep_km_rom_mem_req_o,
  input  km_intf_pkg::km_rom_mem_rsp_t   sep_km_rom_mem_rsp_i,
  output km_intf_pkg::km_sram_mem_req_t  sep_km_sram_mem_req_o,
  input  km_intf_pkg::km_sram_mem_rsp_t  sep_km_sram_mem_rsp_i,

  output sep_pkg::sep_32_64_6_12_axi_req_t   sep_external_req_o,
  input  sep_pkg::sep_32_64_6_12_axi_resp_t  sep_external_resp_i,

  output sep_pkg::sep_cpu_trace_t  sep_cpu_trace_o,
  input  sep_pkg::sep_lockstep_ctrl_t   sep_lockstep_ctrl_i,
  output sep_pkg::sep_lockstep_status_t sep_lockstep_status_o,

  input  wire logic [sep_pkg::NUM_EXTERNAL_IRQS-1:0]   sep_ext_interrupts_i,

  output logic [1:0]  lcc_demote_state_1_o,
  output logic [1:0]  lcc_demote_state_2_o,
  output logic secure_tm_o,

  // Gates for the DFT-inserted OTP access paths. Unconnected in the functional
  // design: an adopter's DFT insertion adds the paths and connects these.
  output logic sep_fuse_dft_disable_o,
  output logic smc_fuse_dft_disable_o,

  output logic  sep_fuse_sense_done_o,

  // SEP WDT clock (passthrough from smu_wrapper)
  input  logic  clk_sep_wdt_i,

  // SEP straps
  input  logic                  secure_tm_req_i,

  // I3C DAT/DCT memory interfaces
  input  i3c_pkg::dat_mem_src_t  [smc_config_pkg::NUM_I3C-1:0]  i3c_dat_mem_src_i,
  output i3c_pkg::dat_mem_sink_t [smc_config_pkg::NUM_I3C-1:0]  i3c_dat_mem_sink_o,
  input  i3c_pkg::dct_mem_src_t  [smc_config_pkg::NUM_I3C-1:0]  i3c_dct_mem_src_i,
  output i3c_pkg::dct_mem_sink_t [smc_config_pkg::NUM_I3C-1:0]  i3c_dct_mem_sink_o,
  input  i3c_pkg::rlt_mem_src_t  [smc_config_pkg::NUM_I3C-1:0]  i3c_rlt_mem_src_i,
  output i3c_pkg::rlt_mem_sink_t [smc_config_pkg::NUM_I3C-1:0]  i3c_rlt_mem_sink_o,
  output logic                                                  gated_clk_periph_i3c_o,

  // Debug bus
  input  logic [127:0]  ext_debug_bus_i,

  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0]  gpio_interrupt_o,
  output logic [smc_config_pkg::NUM_UART-1:0] uart_interrupt_o
);

  `include "axi/assign.svh"

  //--------------------------------------------------------------------------
  // Internal Signals
  //--------------------------------------------------------------------------

  // Zero-pad smc_ext_interrupts_i to full NUM_EXT_INTERRUPTS width for SMC
  logic [NUM_EXT_INTERRUPTS-1:0] smc_ext_interrupts_padded;
  assign smc_ext_interrupts_padded = NUM_EXT_INTERRUPTS'(smc_ext_interrupts_i);

  logic powergood_stable;

  // DTP-SMC AXI connections
  smc_pkg::smc_jtag_56_64_2_12_axi_req_t  dtp_axi_smc_dbg_req;
  smc_pkg::smc_jtag_56_64_2_12_axi_resp_t dtp_axi_smc_dbg_resp;
  smc_pkg::smc_axil_32_32_req_t  dtp_axil_smc_otp_jtag_req;
  smc_pkg::smc_axil_32_32_resp_t dtp_axil_smc_otp_jtag_resp;
  smc_pkg::smc_axil_32_32_req_t  dtp_axil_sep_otp_jtag_req;
  smc_pkg::smc_axil_32_32_resp_t dtp_axil_sep_otp_jtag_resp;
  smc_pkg::smc_axil_32_32_req_t  smc_axil_dtp_csr_req;
  smc_pkg::smc_axil_32_32_resp_t smc_axil_dtp_csr_resp;

  // DTP-SMC boot stall connections
  logic boot_stall_jtag_ovrd;
  logic boot_stall_jtag_val;
  logic boot_stall_combined; // currently unused but exposed in case DTP or SEP needs visibility of boot stall

  // DTP DEBUG_CONTROL CLA clock-stop enable to SMC TDR path
  logic dtp_cla_clock_stop_en;

  // DTP internal cross trigger signals (10 ports: [1:0] for SMC, [9:2] for external)
  logic [DTP_XTRIG_NUM_INT_CT-1:0]  dtp_xtrig_ctm_src_req;
  logic [DTP_XTRIG_NUM_INT_CT-1:0]  dtp_xtrig_ctm_src_ack;
  logic [DTP_XTRIG_NUM_INT_CT-1:0]  dtp_xtrig_ctm_dst_req;
  logic [DTP_XTRIG_NUM_INT_CT-1:0]  dtp_xtrig_ctm_dst_ack;

  // DTP internal clock stop signals (9 ports: [0] for SMC, [8:1] for external)
  logic [DTP_XTRIG_NUM_CLK_STOP_REQ-1:0]  dtp_xtrig_clk_stop_req;

  // SMC cross trigger output
  smc_pkg::xtrigger_t  smc_xtrigger_ss_o;

  // SMC cross trigger input
  smc_pkg::xtrigger_t  smc_xtrigger_ss_i;

  // CLA TDR debug status (SMC -> SMU)
  logic tdr_dbg_ctrl_clocks_stopped_by_cla;

  // DTP-to-SMC JTAG STAP signals (SMC CPU / system JTAG)
  prim_jtag_pkg::jtag_tap_ctrl_t  dtp_smc_stap_tap_ctrl;
  logic  dtp_smc_stap_tdo;
  /* verilator lint_off UNUSEDSIGNAL */
  logic  dtp_smc_stap_tdo_oen;
  /* verilator lint_on UNUSEDSIGNAL */
  logic  smc_stap_tdo_to_dtp;

  // DTP-to-SEP JTAG STAP signals
  prim_jtag_pkg::jtag_tap_ctrl_t  dtp_sep_stap_tap_ctrl;
  logic  dtp_sep_stap_tdo;
  logic  dtp_sep_stap_tdo_oen;
  logic  sep_stap_tdo_to_dtp;

  // JTAG SEP Reset Control Overrides (driven by DTP's SEP slice of the IC_RESET TDR).
  sep_pkg::jtag_sep_reset_ctrl_t jtag_sep_reset_ctrl;

  // CLA custom actions map to SEP CPU debug controls
  // cla_ext_action_custom[0] - mpc_debug_halt_req
  // cla_ext_action_custom[1] - mpc_debug_run_req
  // cla_ext_action_custom[2] - mpc_reset_run_req (inverted: action asserted = Debug Mode)
  // cla_ext_action_custom[3] - i_cpu_halt_req
  // cla_ext_action_custom[4] - i_cpu_run_req
  logic [cla_pkg::CLA_NUMBER_OF_CUSTOM_ACTIONS-1:0] cla_ext_action_custom;

  // SEP lifecycle and mailbox signals
  logic [2*smc_pkg::LC_STATE_WIDTH-1:0]  sep_lc_state;
  sep_lifecycle_ctrl_pkg::dbg_disable_t  sep_dbg_disable;
  logic  sep_lc_sigint_err;
  logic [sep_pkg::NUM_MAILBOXES-1:0]  sep_mailbox_interrupts;

  // SEP security disable
  logic  sep_security_disable;

  // SEP WDT reset request
  logic  sep_wdt_timer_rst_req;
  logic  rst_wdt_n;

  // SEP SPI (sourced from SEP when SEP, else tied off)
  sep_io_pkg::sep_io_spi_req_t  sep_io_spi_req;
  sep_io_pkg::sep_io_spi_rsp_t  sep_io_spi_rsp;

  logic                        sep_spi_enable;
  logic                        sep_spi_clk;
  logic [7:0]                  sep_spi_txd;
  logic                        sep_spi_cs_n;
  logic                        sep_spi_cs_oe_n;
  logic                        sep_spi_cs_ie_n;
  logic                        sep_spi_clk_ie_n;
  logic                        sep_spi_clk_oe_n;
  logic                        sep_spi_dqs_ie_n;
  logic                        sep_spi_dqs_oe_n;
  logic [7:0]                  sep_spi_dq_ie_n;
  logic [7:0]                  sep_spi_dq_oe_n;
  logic [7:0]                  sep_spi_rxd;
  logic                        sep_spi_rxds;
  logic                        sep_spi_mem_rebar_oepad;
  logic                        sep_spi_mem_rebar_opad;
  logic                        sep_spi_mem_rebar_iepad;
  logic                        sep_spi_mem_rebar_ipad;

  // SMC efuse lifecycle integrity error (always driven by SMC)
  logic  efuse_lc_sigint_err;

  // =========================================================================
  // SMU AXI Crossbar signals
  // =========================================================================
  // SEP outbound AXI (manager into xbar)
  sep_pkg::sep_system_peripherals_outbound_axi_req_t   sep_smn_outbound_axi_req;
  sep_pkg::sep_system_peripherals_outbound_axi_resp_t  sep_smn_outbound_axi_resp;

  // SEP inbound AXI (subordinate from xbar, after IW conversion)
  sep_pkg::sep_system_peripherals_internal_axi_req_t   sep_smn_inbound_axi_req;
  sep_pkg::sep_system_peripherals_internal_axi_resp_t  sep_smn_inbound_axi_resp;

  // SMC output AXI (manager into xbar)
  smc_pkg::smc_sys_out_56_64_8_12_axi_req_t   smc_output_axi_req;
  smc_pkg::smc_sys_out_56_64_8_12_axi_resp_t  smc_output_axi_resp;

  // SMC system input AXI (subordinate from xbar, after IW conversion)
  smc_pkg::smc_sys_in_56_64_6_12_axi_req_t    smc_sys_axi_in_req;
  smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t   smc_sys_axi_in_resp;

  // Xbar master port outputs (10-bit ID, before IW conversion)
  smu_axi_xbar_pkg::axi_out_req_t   xbar_to_sep_req;
  smu_axi_xbar_pkg::axi_out_resp_t  xbar_to_sep_resp;
  smu_axi_xbar_pkg::axi_out_req_t   xbar_to_smc_req;
  smu_axi_xbar_pkg::axi_out_resp_t  xbar_to_smc_resp;

  // SEP-to-SMC dedicated port
  sep_pkg::sep_system_peripherals_internal_axi_req_t   sep_ext_to_smc_axi_req;
  sep_pkg::sep_system_peripherals_internal_axi_resp_t  sep_ext_to_smc_axi_resp;

  sep_pkg::sep_system_peripherals_internal_axi_req_t   sep_ext_to_smc_axi_req_local;
  sep_pkg::sep_system_peripherals_internal_axi_resp_t  sep_ext_to_smc_axi_resp_local;

  // SMC sep_axi_in port (after cross-package assignment)
  smc_pkg::smc_sep_in_56_64_6_12_axi_req_t   smc_sep_axi_in_req;
  smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t  smc_sep_axi_in_resp;

  // External debug bus from SEP to SMC
  logic [383:0] sep_ext_debug_bus;

  // combined debug bus to SMC
  logic [511:0] ext_debug_bus;

  // JTAG SMC Reset Control Overrides (driven by DTP's SMC slice of the IC_RESET TDR)
  smc_pkg::jtag_smc_reset_ctrl_t jtag_smc_reset_ctrl;

  //--------------------------------------------------------------------------
  // DTP Instantiation
  //--------------------------------------------------------------------------

  dtp #(
    .JTAG_BSR_ENABLE          (Cfg.JTAG_BSR_ENABLE),
    .JTAG_EXTEST_TRAIN_ENABLE (Cfg.JTAG_EXTEST_TRAIN_ENABLE),
    .JTAG_EXTEST_PULSE_ENABLE (Cfg.JTAG_EXTEST_PULSE_ENABLE),
    .JTAG_INTEST_ENABLE       (Cfg.JTAG_INTEST_ENABLE),
    .JTAG_CLAMP_ENABLE        (Cfg.JTAG_CLAMP_ENABLE),
    .JTAG_HIGHZ_ENABLE        (Cfg.JTAG_HIGHZ_ENABLE),
    .JTAG_RUNBIST_ENABLE      (Cfg.JTAG_RUNBIST_ENABLE),
    .JTAG_TMP_ENABLE          (Cfg.JTAG_TMP_ENABLE),
    // The SMC / SEP IC_RESET slices are always enabled; the external slice follows the SMU
    // `JTAG_IC_RESET_ENABLE` Cfg bit.
    .JTAG_IC_RESET_SMC_ENABLE (1'b1),
    .JTAG_IC_RESET_SEP_ENABLE (SEP),
    .JTAG_IC_RESET_EXT_ENABLE (Cfg.JTAG_IC_RESET_ENABLE),
    .JTAG_SMC_DBG_ENABLE      (Cfg.JTAG_SMC_DBG_ENABLE),
    .JTAG_SEP_DBG_ENABLE      (SEP),
    .JTAG_STAP_IO_ENABLE      (Cfg.JTAG_STAP_IO_ENABLE),
    .JTAG_NUM_EXTRA_STAPS      (Cfg.JTAG_NUM_EXTRA_STAPS),
    .JTAG_IDCODE_MFR_ID        (Cfg.JTAG_IDCODE_MFR_ID),
    .JTAG_IDCODE_PART_NUM      (Cfg.JTAG_IDCODE_PART_NUM),
    .JTAG_IDCODE_SI_REV        (Cfg.JTAG_IDCODE_SI_REV),
    .JTAG_OCH_VER              (Cfg.JTAG_OCH_VER),
    .XTRIG_INT_CT_MODE         (DTP_XTRIG_INT_CT_MODE),
    .jtag_tap_ctrl_t           (prim_jtag_pkg::jtag_tap_ctrl_t),
    .jtag_scan_ctrl_t          (prim_jtag_pkg::jtag_scan_ctrl_t),
    .ic_reset_smc_t            (smc_pkg::jtag_smc_reset_ctrl_t),
    .ic_reset_sep_t            (sep_pkg::jtag_sep_reset_ctrl_t),
    .ic_reset_ext_t            (ic_reset_ext_t),
    .smc_jtag_axi_req_t        (smc_pkg::smc_jtag_56_64_2_12_axi_req_t),
    .smc_jtag_axi_resp_t       (smc_pkg::smc_jtag_56_64_2_12_axi_resp_t),
    .smc_otp_axil_req_t        (smc_pkg::smc_axil_32_32_req_t),
    .smc_otp_axil_resp_t       (smc_pkg::smc_axil_32_32_resp_t),
    .sep_otp_axil_req_t        (smc_pkg::smc_axil_32_32_req_t),
    .sep_otp_axil_resp_t       (smc_pkg::smc_axil_32_32_resp_t),
    .SMC_OTP_RD_PL_DEPTH       (Cfg.SMC_OTP_RD_PL_DEPTH),
    .SMC_OTP_WR_PL_DEPTH       (Cfg.SMC_OTP_WR_PL_DEPTH),
    .SEP_OTP_RD_PL_DEPTH       (2'h3),
    .SEP_OTP_WR_PL_DEPTH       (2'h3),
    .SMC_RD_PL_DEPTH           (Cfg.SMC_RD_PL_DEPTH),
    .SMC_WR_PL_DEPTH           (Cfg.SMC_WR_PL_DEPTH),
    .xtrig_axil_req_t          (smc_pkg::smc_axil_32_32_req_t),
    .xtrig_axil_resp_t         (smc_pkg::smc_axil_32_32_resp_t)
  ) u_dtp (
    .clk_i                           (clk_smu_i),
    .rst_n_i                         (rst_primary_smc_clk_no),
    .pwr_on_rst_ni                   (powergood_stable),
    .dbg_disable_i                   (sep_dbg_disable),
    .jtag_ptap_client_tap_ctrl_i     (jtag_ptap_client_tap_ctrl_i),
    .jtag_ptap_client_tdi_i          (jtag_ptap_client_tdi_i),
    .jtag_ptap_client_tdo_o          (jtag_ptap_client_tdo_o),
    .jtag_ptap_client_tdo_oen_o      (jtag_ptap_client_tdo_oen_o),
    .jtag_bsr_host_scan_ctrl_o       (jtag_bsr_host_scan_ctrl_o),
    .jtag_bsr_host_scan_in_i         (jtag_bsr_host_scan_in_i),
    .jtag_bsr_host_scan_out_o        (jtag_bsr_host_scan_out_o),
    .jtag_stap_io_host_tap_ctrl_o    (jtag_stap_io_host_tap_ctrl_o),
    .jtag_stap_io_host_tdi_i         (jtag_stap_io_host_tdi_i),
    .jtag_stap_io_host_tdo_o         (jtag_stap_io_host_tdo_o),
    .jtag_stap_io_host_tdo_oen_o     (jtag_stap_io_host_tdo_oen_o),
    .jtag_stap_smc_host_tap_ctrl_o   (dtp_smc_stap_tap_ctrl),
    .jtag_stap_smc_host_tdi_i        (smc_stap_tdo_to_dtp),
    .jtag_stap_smc_host_tdo_o        (dtp_smc_stap_tdo),
    .jtag_stap_smc_host_tdo_oen_o    (dtp_smc_stap_tdo_oen),
    .jtag_stap_sep_host_tap_ctrl_o   (dtp_sep_stap_tap_ctrl),
    .jtag_stap_sep_host_tdi_i        (sep_stap_tdo_to_dtp),
    .jtag_stap_sep_host_tdo_o        (dtp_sep_stap_tdo),
    .jtag_stap_sep_host_tdo_oen_o    (dtp_sep_stap_tdo_oen),
    .jtag_stap_extra_host_tap_ctrl_o (jtag_stap_extra_host_tap_ctrl_o),
    .jtag_stap_extra_host_tdi_i      (jtag_stap_extra_host_tdi_i),
    .jtag_stap_extra_host_tdo_o      (jtag_stap_extra_host_tdo_o),
    .jtag_stap_extra_host_tdo_oen_o  (jtag_stap_extra_host_tdo_oen_o),
    .jtag_stap_host_scan_ctrl_o      (jtag_stap_host_scan_ctrl_o),
    .jtag_stap_host_scan_in_i        (jtag_stap_host_scan_in_i),
    .jtag_stap_host_scan_out_o       (jtag_stap_host_scan_out_o),
    .jtag_dfd_host_scan_ctrl_o       (jtag_dfd_host_scan_ctrl_o),
    .jtag_dfd_host_scan_in_i         (jtag_dfd_host_scan_in_i),
    .jtag_dfd_host_scan_out_o        (jtag_dfd_host_scan_out_o),
    .jtag_dft_secure_host_scan_ctrl_o (jtag_dft_secure_host_scan_ctrl_o),
    .jtag_dft_secure_host_scan_in_i   (jtag_dft_secure_host_scan_in_i),
    .jtag_dft_secure_host_scan_out_o  (jtag_dft_secure_host_scan_out_o),
    .jtag_dft_host_scan_ctrl_o       (jtag_dft_host_scan_ctrl_o),
    .jtag_dft_host_scan_in_i         (jtag_dft_host_scan_in_i),
    .jtag_dft_host_scan_out_o        (jtag_dft_host_scan_out_o),
    .axi_smc_dbg_req_o              (dtp_axi_smc_dbg_req),
    .axi_smc_dbg_resp_i             (dtp_axi_smc_dbg_resp),
    .axil_smc_otp_jtag_req_o        (dtp_axil_smc_otp_jtag_req),
    .axil_smc_otp_jtag_resp_i       (dtp_axil_smc_otp_jtag_resp),
    .axil_sep_otp_jtag_req_o        (dtp_axil_sep_otp_jtag_req),
    .axil_sep_otp_jtag_resp_i       (dtp_axil_sep_otp_jtag_resp),
    .stop_clks_o                    (dtp_stop_clks_o),
    .cla_clock_stop_en_o            (dtp_cla_clock_stop_en),
    .jtag_boot_stall_ovrd_o         (boot_stall_jtag_ovrd),
    .jtag_boot_stall_o              (boot_stall_jtag_val),

    // IC_RESET TDR typed struct slices
    .jtag_ic_reset_smc_o            (jtag_smc_reset_ctrl),
    .jtag_ic_reset_sep_o            (jtag_sep_reset_ctrl),
    .jtag_ic_reset_ext_o            (jtag_ic_reset_ext_o),

    .jtag_ptap_state_o              (jtag_ptap_state_o),
    .jtag_ptap_inst_decoded_o       (jtag_ptap_inst_decoded_o),
    .axil_xtrig_req_i               (smc_axil_dtp_csr_req),
    .axil_xtrig_resp_o              (smc_axil_dtp_csr_resp),
    .xtrig_ctm_src_req_o            (dtp_xtrig_ctm_src_req),
    .xtrig_ctm_src_ack_i            (dtp_xtrig_ctm_src_ack),
    .xtrig_ctm_dst_req_i            (dtp_xtrig_ctm_dst_req),
    .xtrig_ctm_dst_ack_o            (dtp_xtrig_ctm_dst_ack),
    .xtrig_clk_stop_req_i           (dtp_xtrig_clk_stop_req),
    .xtrig_ctp_req_out_dout_o       (xtrig_ctp_req_out_dout_o),
    .xtrig_ctp_req_out_dout_en_o    (xtrig_ctp_req_out_dout_en_o),
    .xtrig_ctp_req_out_din_i        (xtrig_ctp_req_out_din_i),
    .xtrig_ctp_req_out_din_en_o     (xtrig_ctp_req_out_din_en_o),
    .xtrig_ctp_req_in_dout_o        (xtrig_ctp_req_in_dout_o),
    .xtrig_ctp_req_in_dout_en_o     (xtrig_ctp_req_in_dout_en_o),
    .xtrig_ctp_req_in_din_i         (xtrig_ctp_req_in_din_i),
    .xtrig_ctp_req_in_din_en_o      (xtrig_ctp_req_in_din_en_o),
    .xtrig_ctp_ack_in_dout_o        (xtrig_ctp_ack_in_dout_o),
    .xtrig_ctp_ack_in_dout_en_o     (xtrig_ctp_ack_in_dout_en_o),
    .xtrig_ctp_ack_in_din_i         (xtrig_ctp_ack_in_din_i),
    .xtrig_ctp_ack_in_din_en_o      (xtrig_ctp_ack_in_din_en_o),
    .xtrig_ctp_ack_out_dout_o       (xtrig_ctp_ack_out_dout_o),
    .xtrig_ctp_ack_out_dout_en_o    (xtrig_ctp_ack_out_dout_en_o),
    .xtrig_ctp_ack_out_din_i        (xtrig_ctp_ack_out_din_i),
    .xtrig_ctp_ack_out_din_en_o     (xtrig_ctp_ack_out_din_en_o),

    // DFT
    .test_en_i                      (test_en_i),
    .scan_rst_ni                    (scan_rst_ni)
  );

  //--------------------------------------------------------------------------
  // SMC Instantiation
  //--------------------------------------------------------------------------

  smc #(
    .MAX_TRANS(MAX_TRANS),
    .rom_req_t(smc_rom_req_t),
    .rom_rsp_t(smc_rom_rsp_t),
    .scratch_ram_req_t(smc_scratch_ram_req_t),
    .scratch_ram_rsp_t(smc_scratch_ram_rsp_t),
    .l1_icache_tag_req_t(smc_l1_icache_tag_req_t),
    .l1_icache_tag_rsp_t(smc_l1_icache_tag_rsp_t),
    .l1_icache_data_req_t(smc_l1_icache_data_req_t),
    .l1_icache_data_rsp_t(smc_l1_icache_data_rsp_t),
    .l1_dcache_tag_req_t(smc_l1_dcache_tag_req_t),
    .l1_dcache_tag_rsp_t(smc_l1_dcache_tag_rsp_t),
    .l1_dcache_data_req_t(smc_l1_dcache_data_req_t),
    .l1_dcache_data_rsp_t(smc_l1_dcache_data_rsp_t),
    .EFUSE_SHIM_SIZE(SMC_EFUSE_SHIM_SIZE)
  ) u_smc (
    .clk_smc_i                           (clk_smu_i),
    .clk_ref_i                           (clk_ref_i),
    .clk_periph_i                        (clk_periph_i),
    .powergood_i                         (powergood_i),
    .powergood_stable_o                  (powergood_stable),
    .rst_cold_ni                         (rst_cold_ni),
    .rst_cold_stable_ref_clk_no          (rst_cold_stable_ref_clk_no),
    .rst_primary_ref_clk_no              (rst_primary_ref_clk_no),
    .rst_primary_smc_clk_no              (rst_primary_smc_clk_no),
    .rst_primary_periph_clk_no           (rst_primary_periph_clk_no),
    .rst_wdt_smc_clk_no                  (rst_wdt_n),
    .sys_axi_in_req_i                    (smc_sys_axi_in_req),
    .sys_axi_in_resp_o                   (smc_sys_axi_in_resp),
    .jtag_axi_in_req_i                   (dtp_axi_smc_dbg_req),
    .jtag_axi_in_resp_o                  (dtp_axi_smc_dbg_resp),
    .axil_smc_otp_jtag_req_i             (dtp_axil_smc_otp_jtag_req),
    .axil_smc_otp_jtag_resp_o            (dtp_axil_smc_otp_jtag_resp),
    .sep_axi_in_req_i                    (smc_sep_axi_in_req),
    .sep_axi_in_resp_o                   (smc_sep_axi_in_resp),
    .output_axi_req_o                    (smc_output_axi_req),
    .output_axi_resp_i                   (smc_output_axi_resp),
    .axil_dtp_csr_req_o                  (smc_axil_dtp_csr_req),
    .axil_dtp_csr_resp_i                 (smc_axil_dtp_csr_resp),
    .smc_external_req_o                  (smc_external_req_o),
    .smc_external_resp_i                 (smc_external_resp_i),
    .efuse_bank_ctrl_req_o               (smc_efuse_bank_ctrl_req_o),
    .efuse_bank_ctrl_resp_i              (smc_efuse_bank_ctrl_resp_i),
    .efuse_shim_command_req_o            (smc_efuse_shim_command_req_o),
    .efuse_shim_command_resp_i           (smc_efuse_shim_command_resp_i),
    .shadow_regs_o                       (smc_shadow_regs_o),
    .lsio_interface_select_o             (lsio_interface_select_o),
    .pad2core_i                          (pad2core_i),
    .core2pad_o                          (core2pad_o),
    .pad2core_en_o                       (pad2core_en_o),
    .core2pad_en_o                       (core2pad_en_o),
    .rst_cool_n_from_pin_i               (rst_cool_n_from_pin_i),
    .spi_enable_i                        (sep_spi_enable),
    .spi_clk_i                           (sep_spi_clk),
    .spi_txd_i                           (sep_spi_txd),
    .spi_cs_n_i                          (sep_spi_cs_n),
    .spi_cs_oe_n_i                       (sep_spi_cs_oe_n),
    .spi_cs_ie_n_i                       (sep_spi_cs_ie_n),
    .spi_clk_ie_n_i                      (sep_spi_clk_ie_n),
    .spi_clk_oe_n_i                      (sep_spi_clk_oe_n),
    .spi_dqs_ie_n_i                      (sep_spi_dqs_ie_n),
    .spi_dqs_oe_n_i                      (sep_spi_dqs_oe_n),
    .spi_dq_ie_n_i                       (sep_spi_dq_ie_n),
    .spi_dq_oe_n_i                       (sep_spi_dq_oe_n),
    .spi_rxd_o                           (sep_spi_rxd),
    .spi_rxds_o                          (sep_spi_rxds),
    .spi_mem_rebar_oepad_i               (sep_spi_mem_rebar_oepad),
    .spi_mem_rebar_opad_i                (sep_spi_mem_rebar_opad),
    .spi_mem_rebar_iepad_i               (sep_spi_mem_rebar_iepad),
    .spi_mem_rebar_ipad_o                (sep_spi_mem_rebar_ipad),
    .clk_telemetry_i                     (clk_telemetry_i),
    .rst_telemetry_ni                    (rst_telemetry_ni),
    .telemetry_atdata_i                  (telemetry_atdata_i),
    .telemetry_atid_i                    (telemetry_atid_i),
    .telemetry_atready_o                 (telemetry_atready_o),
    .telemetry_atvalid_i                 (telemetry_atvalid_i),
    .telemetry_afvalid_o                 (telemetry_afvalid_o),
    .telemetry_afready_i                 (telemetry_afready_i),
    .smc_cluster_ded_o                   (smc_cluster_ded_o),
    .smc_wdt_first_timeout_o             (smc_wdt_first_timeout_o),
    .smc_wdt_second_timeout_o            (smc_wdt_second_timeout_o),
    .smc_global_base_o                   (smc_global_base_o),
    .smc_region_size_o                   (smc_region_size_o),
    .smc_ext_interrupts_i                (smc_ext_interrupts_padded),
    .sep_mailbox_interrupts_i            (sep_mailbox_interrupts),
    .sep_wdt_reset_n_i                   (~sep_wdt_timer_rst_req),
    .smc_fuse_sense_done_o               (smc_fuse_sense_done_o),
    .smc_fuse_reset_n_delayed_o          (smc_fuse_reset_n_delayed_o),
    .boot_stall_jtag_ovrd_i              (boot_stall_jtag_ovrd),
    .boot_stall_jtag_val_i               (boot_stall_jtag_val),
    .boot_stall_combined_o               (boot_stall_combined),
    .skip_mem_repair_o                   (skip_mem_repair_o),
    .ext_boot_seq_done_i                 (ext_boot_seq_done_i),
    .sep_security_disable_i              (sep_security_disable),
    .lc_state_i                          (sep_lc_state),
    .lc_sigint_err_o                     (efuse_lc_sigint_err),
    .smc_ndmreset_request_i              (smc_ndmreset_request_i),
    .smc_ndmreset_process_o              (smc_ndmreset_process_o),
    .smc_ext_mailbox_interrupts_o        (smc_ext_mailbox_interrupts_o),
    .cfg_flr_pf_active_i                 (cfg_flr_pf_active_i),
    .isolate_req_o                       (isolate_req_o),
    .ss_reset_complete_i                 (ss_reset_complete_i),
    .ss_config_o                         (ss_config_o),
    .ss_reset_ctrl_o                     (ss_reset_ctrl_o),
    .sync_irq_o                          (sync_irq_o),
    .smc_rom_intf_req_o                  (smc_rom_intf_req_o),
    .smc_rom_intf_rsp_i                  (smc_rom_intf_rsp_i),
    .smc_scratch_ram_intf_req_o          (smc_scratch_ram_intf_req_o),
    .smc_scratch_ram_intf_rsp_i          (smc_scratch_ram_intf_rsp_i),
    .smc_l1_icache_tag_intf_req_o        (smc_l1_icache_tag_intf_req_o),
    .smc_l1_icache_tag_intf_rsp_i        (smc_l1_icache_tag_intf_rsp_i),
    .smc_l1_icache_data_intf_req_o       (smc_l1_icache_data_intf_req_o),
    .smc_l1_icache_data_intf_rsp_i       (smc_l1_icache_data_intf_rsp_i),
    .smc_l1_dcache_tag_intf_req_o        (smc_l1_dcache_tag_intf_req_o),
    .smc_l1_dcache_tag_intf_rsp_i        (smc_l1_dcache_tag_intf_rsp_i),
    .smc_l1_dcache_data_intf_req_o       (smc_l1_dcache_data_intf_req_o),
    .smc_l1_dcache_data_intf_rsp_i       (smc_l1_dcache_data_intf_rsp_i),
    .smc_disable_sram_auto_init_i        (smc_disable_sram_auto_init_i),
    .smc_init_mem_done_o                 (smc_init_mem_done_o),
    .chiplet_is_primary_i                (chiplet_is_primary_i),
    .timer_count_o                       (timer_count_o),

    .jtag_reset_ctrl_i                   (jtag_smc_reset_ctrl),

    .cla_ext_action_custom_o             (cla_ext_action_custom),
    .xtrigger_ss_o                       (smc_xtrigger_ss_o),
    .xtrigger_ss_i                       (smc_xtrigger_ss_i),
    .tdr_dbg_ctrl_clock_stop_en_i        (dtp_cla_clock_stop_en),
    .tdr_dbg_ctrl_clocks_stopped_by_cla_o (tdr_dbg_ctrl_clocks_stopped_by_cla),
    .trace_mem_req_o                     (trace_mem_req_o),
    .trace_mem_resp_i                    (trace_mem_resp_i),
    .ext_debug_bus_i                     (ext_debug_bus),
    .test_en_i                           (test_en_i),
    .scan_rst_ni                         (scan_rst_ni),
    .mem_repair_done_i                   (mem_repair_done_i),
    .mem_repair_success_i                (mem_repair_success_i),
    .mem_repair_abort_i                  (mem_repair_abort_i),
    .mbist_done_i                        (mbist_done_i),
    .mbist_pass_i                        (mbist_pass_i),
    .mbist_abort_i                       (mbist_abort_i),

    // CPU Debug interfaces (JTAG) — from DTP SMC debug STAP (same ID fields as DTP IDCODE)
    .smc_cpu_jtag_TCK_i              (dtp_smc_stap_tap_ctrl.tck),
    .smc_cpu_jtag_TMS_i              (dtp_smc_stap_tap_ctrl.tms),
    .smc_cpu_jtag_TDI_i              (dtp_smc_stap_tdo),
    .smc_cpu_jtag_TDO_data_o         (smc_stap_tdo_to_dtp),
    .smc_cpu_jtag_reset_i            (~dtp_smc_stap_tap_ctrl.trst_n),
    .smc_cpu_jtag_mfr_id_i           (Cfg.JTAG_IDCODE_MFR_ID),
    .smc_cpu_jtag_part_number_i      (Cfg.JTAG_IDCODE_PART_NUM),
    .smc_cpu_jtag_version_i          (Cfg.JTAG_IDCODE_SI_REV),

    // I3C DAT/DCT memory interfaces
    .i3c_dat_mem_src_i               (i3c_dat_mem_src_i),
    .i3c_dat_mem_sink_o              (i3c_dat_mem_sink_o),
    .i3c_dct_mem_src_i               (i3c_dct_mem_src_i),
    .i3c_dct_mem_sink_o              (i3c_dct_mem_sink_o),
    .gated_clk_periph_i3c_o          (gated_clk_periph_i3c_o),
    .i3c_rlt_mem_src_i               (i3c_rlt_mem_src_i),
    .i3c_rlt_mem_sink_o              (i3c_rlt_mem_sink_o),

    .gpio_interrupt_o                (gpio_interrupt_o),
    .uart_interrupt_o                (uart_interrupt_o)
  );

  //--------------------------------------------------------------------------
  // SEP-dependent logic (if/else based on SEP)
  //--------------------------------------------------------------------------

  if (SEP) begin : gen_sep

    // ==================================================================
    // SEP Instantiation
    // ==================================================================

    sep #(
      .KM_LATCHED_MEM_RDATA  (Cfg.SEP_KM_LATCHED_MEM_RDATA),
      .ABR_MASKING_EN         (Cfg.SEP_ABR_MASKING_EN),
      .ABR_SRAM_LATENCY       (Cfg.SEP_ABR_SRAM_LATENCY),
      .SEP_SEC_DISABLE_TOKEN  (SEP_SEC_DISABLE_TOKEN),
      .EXT_TRNG_NUM_AXIS      (EXT_TRNG_NUM_AXIS),
      .EFUSE_SHIM_SIZE        (SEP_EFUSE_SHIM_SIZE)
    ) u_sep (
      .clk_i                         (clk_smu_i),
      .clk_ref_i                     (clk_ref_i),
      .clk_wdt_i                     (clk_sep_wdt_i),
      .rst_ni                        (rst_primary_smc_clk_no),
      .dbg_rstb_i                    (powergood_stable),
      .wdt_rst_ni                    (rst_wdt_n),

      .wdt_timer_rst_req_o           (sep_wdt_timer_rst_req),

      .jtag_tck                      (dtp_sep_stap_tap_ctrl.tck),
      .jtag_tms                      (dtp_sep_stap_tap_ctrl.tms),
      .jtag_tdi                      (dtp_sep_stap_tdo),
      .jtag_trst_n                   (dtp_sep_stap_tap_ctrl.trst_n),
      .jtag_tdo                      (sep_stap_tdo_to_dtp),
      .jtag_tdoEn                    (/* unused at smu level */),

      // JTAG SEP Reset Control Overrides
      .jtag_sep_reset_ctrl_i         (jtag_sep_reset_ctrl),

      .axil_sep_otp_jtag_req_i       (dtp_axil_sep_otp_jtag_req),
      .axil_sep_otp_jtag_resp_o      (dtp_axil_sep_otp_jtag_resp),

      .mpc_debug_halt_req            (cla_ext_action_custom[0]),
      .mpc_debug_run_req             (cla_ext_action_custom[1]),
      .mpc_reset_run_req             (~cla_ext_action_custom[2]), // inverted: default 0 = Normal Mode; CLA action = Debug Mode

      .i_cpu_halt_req                (cla_ext_action_custom[3]),
      .i_cpu_run_req                 (cla_ext_action_custom[4]),

      .test_en_i                     (test_en_i),
      .scan_rst_ni                   (scan_rst_ni),

      .ext_boot_seq_done_i           (ext_boot_seq_done_i),

      // STAP access is already gated by lifecycle; the core DM AXI master
      // reaches the SEP fabric, so the DMI uncore aperture is unused.
      .dmi_core_enable               (1'b1),
      .dmi_uncore_enable             (1'b0),
      .dmi_uncore_en                 (/* unused */),
      .dmi_uncore_wr_en              (/* unused */),
      .dmi_uncore_addr               (/* unused */),
      .dmi_uncore_wdata              (/* unused */),
      .dmi_uncore_rdata              (32'h0),
      .dmi_active                    (/* unused */),

      .sep_cpu_trace                 (sep_cpu_trace_o),
      .lockstep_ctrl_i               (sep_lockstep_ctrl_i),
      .lockstep_status_o             (sep_lockstep_status_o),

      .jtag_id                       ({Cfg.JTAG_IDCODE_SI_REV, Cfg.JTAG_IDCODE_PART_NUM, Cfg.JTAG_IDCODE_MFR_ID}),

      // No external CLINT; EL2 internal timers drive mip.MTIP / mip.MSIP
      .timer_int                     (1'b0),
      .soft_int                      (1'b0),
      .extintsrc_req                 (sep_ext_interrupts_i),

      .sep_cpu_tcm_req_o             (sep_cpu_tcm_req_o),
      .sep_cpu_tcm_rsp_i             (sep_cpu_tcm_rsp_i),

      .sep_sram_req                  (sep_sram_req_o),
      .sep_sram_rsp                  (sep_sram_rsp_i),

      .sep_boot_rom_req              (sep_boot_rom_req_o),
      .sep_boot_rom_rsp              (sep_boot_rom_rsp_i),

      .smn_outbound_axi_req_o        (sep_smn_outbound_axi_req),
      .smn_outbound_axi_resp_i       (sep_smn_outbound_axi_resp),

      .smn_inbound_axi_req_i         (sep_smn_inbound_axi_req),
      .smn_inbound_axi_resp_o        (sep_smn_inbound_axi_resp),

      .sep_ext_to_smc_axi_req_o      (sep_ext_to_smc_axi_req),
      .sep_ext_to_smc_axi_resp_i     (sep_ext_to_smc_axi_resp),

      .sep_crypto_pka_imem_sram_req  (sep_crypto_pka_imem_sram_req_o),
      .sep_crypto_pka_imem_sram_rsp  (sep_crypto_pka_imem_sram_rsp_i),

      .sep_crypto_pka_dmem_sram_req  (sep_crypto_pka_dmem_sram_req_o),
      .sep_crypto_pka_dmem_sram_rsp  (sep_crypto_pka_dmem_sram_rsp_i),

      .abr_mem_req                   (abr_mem_req_o),
      .abr_mem_rsp                   (abr_mem_rsp_i),

      // External TRNG loopback + entropy sample clock (closed in smu_wrapper)
      .entropy_rosc_sample_clk_i     (entropy_rosc_sample_clk_i),
      .ext_trng_axil_req_o           (ext_trng_axil_req_o),
      .ext_trng_axil_resp_i          (ext_trng_axil_resp_i),
      .ext_trng_axis_req_i           (ext_trng_axis_req_i),
      .ext_trng_axis_rsp_o           (ext_trng_axis_rsp_o),
      .ext_trng_irq_i                (ext_trng_irq_i),

      .lcc_demote_state_1_o          (lcc_demote_state_1_o),
      .lcc_demote_state_2_o          (lcc_demote_state_2_o),

      .km_rom_mem_req_o              (sep_km_rom_mem_req_o),
      .km_rom_mem_rsp_i              (sep_km_rom_mem_rsp_i),
      .km_sram_mem_req_o             (sep_km_sram_mem_req_o),
      .km_sram_mem_rsp_i             (sep_km_sram_mem_rsp_i),

      .efuse_bank_ctrl_req_o         (sep_efuse_bank_ctrl_req_o),
      .efuse_bank_ctrl_resp_i        (sep_efuse_bank_ctrl_resp_i),

      .efuse_shim_command_req_o      (sep_efuse_shim_command_req_o),
      .efuse_shim_command_resp_i     (sep_efuse_shim_command_resp_i),

      .sep_io_spi_req_o              (sep_io_spi_req),
      .sep_io_spi_rsp_i              (sep_io_spi_rsp),

      .lc_state_o                    (sep_lc_state),
      .dbg_disable_o                 (sep_dbg_disable),
      .sep_fuse_dft_disable_o        (sep_fuse_dft_disable_o),
      .smc_fuse_dft_disable_o        (smc_fuse_dft_disable_o),
      .lc_sigint_err_o               (sep_lc_sigint_err),
      .security_disable_o            (sep_security_disable),
      .secure_tm_o                   (secure_tm_o),

      .smc_mailbox_interrupt_o       (sep_mailbox_interrupts),

      .smc_fuse_sense_done_i         (smc_fuse_sense_done_o),
      .sep_fuse_sense_done_o         (sep_fuse_sense_done_o),

      .secure_tm_req_i               (secure_tm_req_i),

      .sep_external_axi_req_o       (sep_external_req_o),
      .sep_external_axi_resp_i      (sep_external_resp_i),

      .smc_global_base_addr_i        (smc_global_base_o),
      .smc_region_size_i             ({24'h0, smc_region_size_o}),

      .sep_global_base_addr_o        (sep_global_base_o),
      .sep_region_size_o             (sep_region_size_o),

      .km_unrecoverable_err_o        (),
      .km_recoverable_err_o          (),

      .ext_debug_bus_o               (sep_ext_debug_bus)
    );

    axi_window_remap #(
      .axi_req_t          (sep_pkg::sep_56_64_6_12_axi_req_t),
      .axi_resp_t         (sep_pkg::sep_56_64_6_12_axi_resp_t),
      .AXI_ADDR_WIDTH     (smu_pkg::AXI_ADDR_WIDTH)
    ) sep_ext_to_smc_axi_local_alias_remap (
      .slv_req_i          (sep_ext_to_smc_axi_req),
      .slv_resp_o         (sep_ext_to_smc_axi_resp),
      .mst_req_o          (sep_ext_to_smc_axi_req_local),
      .mst_resp_i         (sep_ext_to_smc_axi_resp_local),
      .local_alias_base_i (smu_pkg::SEP_SMC_REGION_BASE),
      .region_size_i      (smu_pkg::SEP_SMC_REGION_SIZE),
      .target_base_i      (smu_pkg::SEP_SMC_REGION_ALIAS_BASE)
    );

    // ==================================================================
    // SMU AXI Crossbar
    // ==================================================================

    smu_axi_xbar_pkg::axi_56_64_req_t   sep_out_xbar_req;
    smu_axi_xbar_pkg::axi_56_64_resp_t  sep_out_xbar_resp;
    `AXI_ASSIGN_REQ_STRUCT(sep_out_xbar_req, sep_smn_outbound_axi_req)
    `AXI_ASSIGN_RESP_STRUCT(sep_smn_outbound_axi_resp, sep_out_xbar_resp)

    smu_axi_xbar_pkg::axi_56_64_req_t   smc_out_xbar_req;
    smu_axi_xbar_pkg::axi_56_64_resp_t  smc_out_xbar_resp;
    `AXI_ASSIGN_REQ_STRUCT(smc_out_xbar_req, smc_output_axi_req)
    `AXI_ASSIGN_RESP_STRUCT(smc_output_axi_resp, smc_out_xbar_resp)

    smu_axi_xbar u_smu_axi_xbar (
      .clk_i                  (clk_smu_i),
      .rst_ni                 (rst_primary_smc_clk_no),
      .test_i                 (test_en_i),
      // Programmable apertures (CSR-driven; all on clk_smu_i).
      .sep_global_base_addr_i (sep_global_base_o),
      .sep_region_size_i      (sep_region_size_o[31:0]),
      .smc_global_base_addr_i (smc_global_base_o),
      .smc_region_size_i      (smc_region_size_o),
      // Initiator ports
      .sep_out_req_i          (sep_out_xbar_req),
      .sep_out_resp_o         (sep_out_xbar_resp),
      .smc_out_req_i          (smc_out_xbar_req),
      .smc_out_resp_o         (smc_out_xbar_resp),
      .ext_in_req_i           (smu_axi_in_req_i),
      .ext_in_resp_o          (smu_axi_in_resp_o),
      // Target ports
      .sep_in_req_o           (xbar_to_sep_req),
      .sep_in_resp_i          (xbar_to_sep_resp),
      .smc_in_req_o           (xbar_to_smc_req),
      .smc_in_resp_i          (xbar_to_smc_resp),
      .ext_out_req_o          (smu_axi_out_req_o),
      .ext_out_resp_i         (smu_axi_out_resp_i)
    );

    // ==================================================================
    // AXI ID Width Converters (xbar 10-bit ID -> 6-bit for SEP/SMC)
    // ==================================================================

    axi_iw_converter #(
      .AxiSlvPortIdWidth      (smu_axi_xbar_pkg::XbarOutputIdW),
      .AxiMstPortIdWidth      (sep_pkg::SEP_56_64_6_12_ID_WIDTH),
      .AxiSlvPortMaxUniqIds   (16),
      .AxiSlvPortMaxTxnsPerId (8),
      .AxiSlvPortMaxTxns      (0),
      .AxiMstPortMaxUniqIds   (0),
      .AxiMstPortMaxTxnsPerId (0),
      .AxiAddrWidth           (56),
      .AxiDataWidth           (64),
      .AxiUserWidth           (12),
      .slv_req_t              (smu_axi_xbar_pkg::axi_out_req_t),
      .slv_resp_t             (smu_axi_xbar_pkg::axi_out_resp_t),
      .mst_req_t              (sep_pkg::sep_56_64_6_12_axi_req_t),
      .mst_resp_t             (sep_pkg::sep_56_64_6_12_axi_resp_t)
    ) u_iw_conv_sep (
      .clk_i      (clk_smu_i),
      .rst_ni     (rst_primary_smc_clk_no),
      .slv_req_i  (xbar_to_sep_req),
      .slv_resp_o (xbar_to_sep_resp),
      .mst_req_o  (sep_smn_inbound_axi_req),
      .mst_resp_i (sep_smn_inbound_axi_resp)
    );

    axi_iw_converter #(
      .AxiSlvPortIdWidth      (smu_axi_xbar_pkg::XbarOutputIdW),
      .AxiMstPortIdWidth      (smc_pkg::SYS_IN_ID_WIDTH),
      .AxiSlvPortMaxUniqIds   (16),
      .AxiSlvPortMaxTxnsPerId (8),
      .AxiSlvPortMaxTxns      (0),
      .AxiMstPortMaxUniqIds   (0),
      .AxiMstPortMaxTxnsPerId (0),
      .AxiAddrWidth           (56),
      .AxiDataWidth           (64),
      .AxiUserWidth           (12),
      .slv_req_t              (smu_axi_xbar_pkg::axi_out_req_t),
      .slv_resp_t             (smu_axi_xbar_pkg::axi_out_resp_t),
      .mst_req_t              (smc_pkg::smc_sys_in_56_64_6_12_axi_req_t),
      .mst_resp_t             (smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t)
    ) u_iw_conv_smc (
      .clk_i      (clk_smu_i),
      .rst_ni     (rst_primary_smc_clk_no),
      .slv_req_i  (xbar_to_smc_req),
      .slv_resp_o (xbar_to_smc_resp),
      .mst_req_o  (smc_sys_axi_in_req),
      .mst_resp_i (smc_sys_axi_in_resp)
    );

    // ==================================================================
    // SEP-to-SMC Dedicated Port (cross-package AXI assignment)
    // ==================================================================
    `AXI_ASSIGN_REQ_STRUCT(smc_sep_axi_in_req, sep_ext_to_smc_axi_req_local)
    `AXI_ASSIGN_RESP_STRUCT(sep_ext_to_smc_axi_resp_local, smc_sep_axi_in_resp)

    // ==================================================================
    // Lifecycle & mailbox driven by SEP
    // ==================================================================
    assign lc_state_o      = sep_lc_state;

    // differential encoding error reported by either the SEP or SMC efuse interface
    assign lc_sigint_err_o = sep_lc_sigint_err | efuse_lc_sigint_err;

    // Export the OT SPI request to the wrapper-level SPI mux (u_sep_ip_integration).
    assign sep_io_spi_req_o = sep_io_spi_req;

    // ==================================================================
    // SEP SPI signal assignments (connect struct to intermediate signals)
    // ==================================================================
    assign sep_spi_enable       = 1'b1;
    assign sep_spi_clk          = sep_io_spi_req.sck;
    assign sep_spi_txd          = {4'b0, sep_io_spi_req.sd};
    assign sep_spi_cs_n         = sep_io_spi_req.cs_n;
    assign sep_spi_cs_oe_n      = ~sep_io_spi_req.cs_oe;
    assign sep_spi_cs_ie_n      = sep_io_spi_req.cs_oe;
    assign sep_spi_clk_ie_n     = sep_io_spi_req.sck_oe;
    assign sep_spi_clk_oe_n     = ~sep_io_spi_req.sck_oe;
    assign sep_spi_dqs_ie_n     = 1'b1;
    assign sep_spi_dqs_oe_n     = 1'b1;
    assign sep_spi_dq_ie_n      = {4'hF, sep_io_spi_req.sd_oe};
    assign sep_spi_dq_oe_n      = {4'hF, ~sep_io_spi_req.sd_oe};
    assign sep_spi_mem_rebar_oepad = 1'b0;
    assign sep_spi_mem_rebar_opad  = 1'b0;
    assign sep_spi_mem_rebar_iepad = 1'b0;

    // SEP SPI response (RX data from SMC to SEP)
    assign sep_io_spi_rsp.sd = sep_spi_rxd[3:0];

  end else begin : gen_no_sep

    // ==================================================================
    // DTP SEP OTP -- AXI-Lite error slave (no SEP to respond)
    // ==================================================================
    prim_axi_lite_err_slv #(
      .AXI_ADDR_WIDTH (32),
      .AXI_DATA_WIDTH (32),
      .axil_req_t     (smc_pkg::smc_axil_32_32_req_t),
      .axil_resp_t    (smc_pkg::smc_axil_32_32_resp_t),
      .RESP           (axi_pkg::RESP_DECERR),
      .RESP_WIDTH     (32),
      .RESP_DATA      (32'hBADCAB1E)
    ) u_sep_otp_axil_err_slv (
      .clk_i       (clk_ref_i),
      .rst_ni      (rst_primary_ref_clk_no),
      .axil_req_i  (dtp_axil_sep_otp_jtag_req),
      .axil_resp_o (dtp_axil_sep_otp_jtag_resp)
    );

    // ==================================================================
    // DTP SEP STAP tie-off (DTP drives tap_ctrl/tdo but nobody reads;
    // tie the TDI input back to DTP to 0)
    // ==================================================================
    assign sep_stap_tdo_to_dtp = 1'b0;

    // ==================================================================
    // SEP Security Disable & Secure TM
    // ==================================================================
    assign sep_security_disable = 1'b0;
    assign secure_tm_o = 1'b0;

    // No lifecycle controller in this configuration, so nothing can authorise the
    // inserted fuse paths; hold them disabled.
    assign sep_fuse_dft_disable_o = 1'b1;
    assign smc_fuse_dft_disable_o = 1'b1;

    // ==================================================================
    // Lifecycle state -- original standalone behavior
    // ==================================================================
    assign sep_lc_state      = 8'hf0;
    assign sep_dbg_disable   = '0;
    assign sep_lc_sigint_err = 1'b0;
    assign lc_state_o        = sep_lc_state;

    // differential encoding error reported by either the SEP or SMC efuse interface
    assign lc_sigint_err_o   = sep_lc_sigint_err | efuse_lc_sigint_err;

    // ==================================================================
    // SEP mailbox and WDT tie-offs
    // ==================================================================
    assign sep_mailbox_interrupts = '0;
    assign sep_wdt_timer_rst_req  = 1'b0;

    // ==================================================================
    // SMC dedicated SEP port tie-off (no incoming transactions from SEP)
    // ==================================================================
    assign smc_sep_axi_in_req = '0;

    // ==================================================================
    // Direct SMC-to-external AXI with ID-width adapters
    // (no xbar; external port types must remain stable)
    // ==================================================================

    // Output path: SMC output (8-bit ID) -> external output (10-bit ID)
    axi_iw_converter #(
      .AxiSlvPortIdWidth      (smc_pkg::SYS_OUT_ID_WIDTH),       // 8
      .AxiMstPortIdWidth      (smu_axi_xbar_pkg::XbarOutputIdW), // 10
      .AxiSlvPortMaxUniqIds   (16),
      .AxiSlvPortMaxTxnsPerId (8),
      .AxiSlvPortMaxTxns      (0),
      .AxiMstPortMaxUniqIds   (0),
      .AxiMstPortMaxTxnsPerId (0),
      .AxiAddrWidth           (56),
      .AxiDataWidth           (64),
      .AxiUserWidth           (12),
      .slv_req_t              (smc_pkg::smc_sys_out_56_64_8_12_axi_req_t),
      .slv_resp_t             (smc_pkg::smc_sys_out_56_64_8_12_axi_resp_t),
      .mst_req_t              (smu_axi_xbar_pkg::axi_out_req_t),
      .mst_resp_t             (smu_axi_xbar_pkg::axi_out_resp_t)
    ) u_iw_conv_smc_out (
      .clk_i      (clk_smu_i),
      .rst_ni     (rst_primary_smc_clk_no),
      .slv_req_i  (smc_output_axi_req),
      .slv_resp_o (smc_output_axi_resp),
      .mst_req_o  (smu_axi_out_req_o),
      .mst_resp_i (smu_axi_out_resp_i)
    );

    // Input path: external input (8-bit ID) -> SMC input (6-bit ID)
    axi_iw_converter #(
      .AxiSlvPortIdWidth      (smu_axi_xbar_pkg::MaxInputIdW),   // 8
      .AxiMstPortIdWidth      (smc_pkg::SYS_IN_ID_WIDTH),        // 6
      .AxiSlvPortMaxUniqIds   (16),
      .AxiSlvPortMaxTxnsPerId (8),
      .AxiSlvPortMaxTxns      (0),
      .AxiMstPortMaxUniqIds   (0),
      .AxiMstPortMaxTxnsPerId (0),
      .AxiAddrWidth           (56),
      .AxiDataWidth           (64),
      .AxiUserWidth           (12),
      .slv_req_t              (smu_axi_xbar_pkg::axi_56_64_req_t),
      .slv_resp_t             (smu_axi_xbar_pkg::axi_56_64_resp_t),
      .mst_req_t              (smc_pkg::smc_sys_in_56_64_6_12_axi_req_t),
      .mst_resp_t             (smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t)
    ) u_iw_conv_smc_in (
      .clk_i      (clk_smu_i),
      .rst_ni     (rst_primary_smc_clk_no),
      .slv_req_i  (smu_axi_in_req_i),
      .slv_resp_o (smu_axi_in_resp_o),
      .mst_req_o  (smc_sys_axi_in_req),
      .mst_resp_i (smc_sys_axi_in_resp)
    );

    // ==================================================================
    // SEP aperture tie-offs (no SEP CSR when SEP=0)
    // ==================================================================
    assign sep_global_base_o                = '0;
    assign sep_region_size_o                = '0;

    // ==================================================================
    // SEP passthrough port tie-offs
    // ==================================================================
    assign sep_sram_req_o                   = '0;
    assign sep_boot_rom_req_o               = '0;
    assign sep_cpu_tcm_req_o                = '0;
    assign sep_efuse_bank_ctrl_req_o        = '0;
    assign sep_efuse_shim_command_req_o     = '0;
    assign sep_crypto_pka_imem_sram_req_o   = '0;
    assign sep_crypto_pka_dmem_sram_req_o   = '0;
    assign abr_mem_req_o                    = '0;
    assign ext_trng_axil_req_o              = '0;
    assign ext_trng_axis_rsp_o              = '{default: '0};
    assign sep_km_rom_mem_req_o             = '0;
    assign sep_km_sram_mem_req_o            = '0;
    assign sep_io_spi_req                   = '0;
    assign sep_external_req_o          = '0;
    assign sep_cpu_trace_o                  = '0;
    assign sep_lockstep_status_o            = '0;
    assign lcc_demote_state_1_o             = '0;
    assign lcc_demote_state_2_o             = '0;
    assign sep_fuse_sense_done_o            = 1'b0;

    // SEP SPI intermediate signal tie-offs (no SEP to drive them)
    assign sep_spi_enable       = 1'b0;
    assign sep_spi_clk          = 1'b0;
    assign sep_spi_txd          = 8'b0;
    assign sep_spi_cs_n         = 1'b1;
    assign sep_spi_cs_oe_n      = 1'b1;
    assign sep_spi_cs_ie_n      = 1'b1;
    assign sep_spi_clk_ie_n     = 1'b1;
    assign sep_spi_clk_oe_n     = 1'b1;
    assign sep_spi_dqs_ie_n     = 1'b1;
    assign sep_spi_dqs_oe_n     = 1'b1;
    assign sep_spi_dq_ie_n      = 8'hFF;
    assign sep_spi_dq_oe_n      = 8'hFF;
    assign sep_spi_mem_rebar_oepad = 1'b0;
    assign sep_spi_mem_rebar_opad  = 1'b0;
    assign sep_spi_mem_rebar_iepad = 1'b0;
    assign sep_io_spi_rsp       = '0;

    // External debug bus tie-off
    assign sep_ext_debug_bus = '0;

  end

  // --------------------------
  // Debug Signal Concatenation
  // --------------------------

  assign ext_debug_bus = {
        ext_debug_bus_i,
        sep_ext_debug_bus
    };

  //--------------------------------------------------------------------------
  // DTP-SMC Internal Connections
  //--------------------------------------------------------------------------

  // Cross Trigger [1:0] (SMC to DTP)
  assign dtp_xtrig_ctm_dst_req[1:0] = smc_xtrigger_ss_o;

  // Cross Trigger [1:0] (DTP to SMC)
  assign smc_xtrigger_ss_i = dtp_xtrig_ctm_src_req[1:0];
  assign dtp_xtrig_ctm_src_ack[1:0] = 2'b00;

  // Clock Stop Request #0 (SMC TDR status -> DTP CTN).
  assign dtp_xtrig_clk_stop_req[0] = tdr_dbg_ctrl_clocks_stopped_by_cla;

  //--------------------------------------------------------------------------
  // Cross Trigger Port Remapping (DTP [9:2] <-> SMU [7:0])
  //--------------------------------------------------------------------------

  assign xtrig_ctm_src_req_o = dtp_xtrig_ctm_src_req[9:2];

  assign dtp_xtrig_ctm_src_ack[9:2] = xtrig_ctm_src_ack_i;

  assign dtp_xtrig_ctm_dst_req[9:2] = xtrig_ctm_dst_req_i;

  assign xtrig_ctm_dst_ack_o = dtp_xtrig_ctm_dst_ack[9:2];

  assign dtp_xtrig_clk_stop_req[8:1] = xtrig_clk_stop_req_i;

endmodule
