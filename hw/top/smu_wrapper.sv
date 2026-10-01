// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SMU Wrapper -- OSS reference top
//
// smu.sv is the composite full-chip module: it instantiates the bare
// sep/smc/dtp cores internally and re-exposes their technology-specific
// hook points (eFuse, PLL/PVT, GPIO pads, SEP memory macros, ...) directly
// at its own boundary. This wrapper attaches smc_ip_integration.sv and
// sep_ip_integration.sv -- the same open-source model sets smc_wrapper.sv /
// sep_wrapper.sv use -- directly to smu.sv's re-exposed ports, per the
// integrator guide's documented composition
// (doc/integrator/modules/ROOT/pages/index.adoc, "Module Variants and IP
// Integration").
//
// Modeled here (via smc_ip_integration.sv / sep_ip_integration.sv): the
// shared eFuse bank/shim model (one SEP instance, one SMC instance), PLL/PVT
// AXI-Lite stubs, one prim_pad_shim.sv per GPIO pin, the I3C DAT/DCT/RLT table
// memories, the SEP SRAM/boot-ROM/OTBN/Key-Manager memory macros (OpenTitan
// generic RAM/ROM primitives) and TCM (OpenTitan-derived ICCM/DCCM wrapper),
// and the trace sink RAM banks. The GPIO-shim CSR and
// adopter-extension AXI-Lite/AXI4 buses are terminated with DECERR slaves.
// sep_ip_integration's TRNG DECERR termination is instantiated for
// interface parity, tied off since smu.sv keeps its TRNG ports internal.
// Every other technology-specific interface (SMC CPU cache/SRAM/ROM macros,
// ATB telemetry, JTAG, ...) is passed straight through; see
// hw/top/README.md.
//
// This is a reference integration example, provided for adopters to
// substitute with their own vendor IP/macros.
//-----------------------------------------------------------------------------

module smu_wrapper
  import sep_pkg::*;
  import sep_crypto_pkg::*;
  import sep_io_pkg::*;
  import km_intf_pkg::*;
#(
  parameter smu_pkg::smu_cfg_t CFG = smu_pkg::DefaultCfg,
  parameter bit           SEP                   = 1'b1,
  parameter bit [255:0]   SEP_SEC_DISABLE_TOKEN = 256'b0,
  parameter int unsigned  EXT_TRNG_NUM_AXIS     = 3,
  parameter type  ic_reset_ext_t = jtag_tap_pkg::jtag_ic_reset_default_t,

  localparam int unsigned  XTRIG_NUM_CTP          = CFG.XTRIG_NUM_CTP,
  localparam int unsigned  XTRIG_NUM_INT_CT       = CFG.XTRIG_NUM_INT_CT,
  localparam int unsigned  XTRIG_NUM_CLK_STOP_REQ = CFG.XTRIG_NUM_CLK_STOP_REQ,
  localparam int unsigned  JTAG_NUM_EXTRA_STAP_PORTS =
      (CFG.JTAG_NUM_EXTRA_STAPS > 0) ? CFG.JTAG_NUM_EXTRA_STAPS : 1
) (
  // Clock and Reset
  input  logic  rst_cold_ni,

  output logic  rst_cold_stable_ref_clk_no,

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

  output ic_reset_ext_t  jtag_ic_reset_ext_o,

  // Cross Trigger Matrix Interface
  output logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_src_req_o,
  input  logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_src_ack_i,
  input  logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_dst_req_i,
  output logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_dst_ack_o,

  // Clock Stop Request Interface
  input  logic [XTRIG_NUM_CLK_STOP_REQ-1:0]  xtrig_clk_stop_req_i,

  // Cross Trigger Port GPIO Interface
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

  // SMU AXI Crossbar External Ports (toward SMN)
  input  smu_axi_xbar_pkg::axi_56_64_req_t   smu_axi_in_req_i,
  output smu_axi_xbar_pkg::axi_56_64_resp_t  smu_axi_in_resp_o,
  output smu_axi_xbar_pkg::axi_out_req_t      smu_axi_out_req_o,
  input  smu_axi_xbar_pkg::axi_out_resp_t     smu_axi_out_resp_i,

  output smc_efuse_pkg::efuse_map_t           smc_shadow_regs_o,

  // GPIO control (lsio select passed through; per-pin pad I/O replaced by
  // gpio_pad_io below; per-pin CSR path terminated internally, see header)
  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0]  lsio_interface_select_o,

  // Physical GPIO pad bus -- one prim_pad_shim.sv per pin stands in for the
  // padring here.
  inout  wire  [smc_pkg::NUM_GPIO_WRAPS-1:0]  gpio_pad_io,

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

  output smc_pkg::smc_axi_addr_t                                   smc_global_base_o,
  output logic [31:0]                                              smc_region_size_o,
  output logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_global_base_o,
  output logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_region_size_o,

  // External Interrupts
  input  logic [CFG.NUM_INT_TO_SMC-1:0]  smc_ext_interrupts_i,

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

  // CPU ROM/scratch/L1$ are absorbed by smc_ip_integration (not ports).

  // Memory Init
  input  logic  smc_disable_sram_auto_init_i,
  output logic  smc_init_mem_done_o,

  // System Timer OCTS Interface
  input  logic  chiplet_is_primary_i,
  output logic [63:0]  timer_count_o,

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

  // OpenTitan SPI request, surfaced for observation; the loop closes in smu.sv
  output sep_io_pkg::sep_io_spi_req_t  sep_io_spi_req_o,

  output logic  secure_tm_o,

  // Ring-oscillator sample clock for SEP entropy_source (async to clk_smu_i)
  input  logic  entropy_rosc_sample_clk_i,

  output sep_pkg::sep_cpu_trace_t  sep_cpu_trace_o,
  input  sep_pkg::sep_lockstep_ctrl_t   sep_lockstep_ctrl_i,
  output sep_pkg::sep_lockstep_status_t sep_lockstep_status_o,

  input  wire logic [sep_pkg::NUM_EXTERNAL_IRQS-1:0]   sep_ext_interrupts_i,

  output logic [1:0]  lcc_demote_state_1_o,
  output logic [1:0]  lcc_demote_state_2_o,

  // Gates for the DFT-inserted OTP access paths, surfaced beside the eFuse shims
  // an adopter's DFT insertion attaches to.
  output logic  sep_fuse_dft_disable_o,
  output logic  smc_fuse_dft_disable_o,

  output logic  sep_fuse_sense_done_o,

  // SEP WDT clock
  input  logic  clk_sep_wdt_i,

  // SEP straps
  input  logic                  secure_tm_req_i,

  // Gated I3C peripheral clock. The table memories it drives are absorbed by
  // smc_ip_integration, so this leaves the wrapper for observation only.
  output logic                                                  gated_clk_periph_i3c_o,

  // Debug bus
  input  logic [127:0]  ext_debug_bus_i,

  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0]  gpio_interrupt_o,
  output logic [smc_config_pkg::NUM_UART-1:0] uart_interrupt_o,

  // eFuse debug buses (internal shim state, surfaced for DV visibility)
  output logic [15:0] sep_efuse_debug_bus_o,
  output logic [15:0] smc_efuse_debug_bus_o
);

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  logic clk_sys;
  logic clk_ref;
  logic clk_periph;

  // Single AXI-Lite window covering the whole smc_external map; PLL, PVT,
  // GPIO control and the extension slot are decoded inside
  // smc_ip_integration.
  smc_pkg::smc_axil_32_32_req_t  smc_external_req;
  smc_pkg::smc_axil_32_32_resp_t smc_external_resp;

  // Trace sink memories (smu <-> smc_ip_integration)
  trace_mem_pkg::SinkMemPktIn_s  [tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_req;
  trace_mem_pkg::SinkMemPktOut_s [tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_resp;

  // CPU mem macros (smu <-> smc_ip_integration)
  chipyard_4core_mem_pkg::rom_req_t            smc_rom_intf_req;
  chipyard_4core_mem_pkg::rom_rsp_t            smc_rom_intf_rsp;
  chipyard_4core_mem_pkg::scratch_ram_req_t    smc_scratch_ram_intf_req
        [chipyard_4core_mem_pkg::NUM_SRAM_BANKS-1:0];
  chipyard_4core_mem_pkg::scratch_ram_rsp_t    smc_scratch_ram_intf_rsp
        [chipyard_4core_mem_pkg::NUM_SRAM_BANKS-1:0];
  chipyard_4core_mem_pkg::l1_icache_tag_req_t  smc_l1_icache_tag_intf_req
        [chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS-1:0];
  chipyard_4core_mem_pkg::l1_icache_tag_rsp_t  smc_l1_icache_tag_intf_rsp
        [chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS-1:0];
  chipyard_4core_mem_pkg::l1_icache_data_req_t smc_l1_icache_data_intf_req
        [chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS-1:0];
  chipyard_4core_mem_pkg::l1_icache_data_rsp_t smc_l1_icache_data_intf_rsp
        [chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS-1:0];
  chipyard_4core_mem_pkg::l1_dcache_tag_req_t  smc_l1_dcache_tag_intf_req
        [chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS-1:0];
  chipyard_4core_mem_pkg::l1_dcache_tag_rsp_t  smc_l1_dcache_tag_intf_rsp
        [chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS-1:0];
  chipyard_4core_mem_pkg::l1_dcache_data_req_t smc_l1_dcache_data_intf_req
        [chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS-1:0];
  chipyard_4core_mem_pkg::l1_dcache_data_rsp_t smc_l1_dcache_data_intf_rsp
        [chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS-1:0];

  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core;
  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad;
  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core_en;
  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad_en;

  // I3C table memory macros (smu <-> smc_ip_integration)
  i3c_pkg::dat_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_src;
  i3c_pkg::dat_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_sink;
  i3c_pkg::dct_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_src;
  i3c_pkg::dct_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_sink;
  i3c_pkg::rlt_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_rlt_mem_src;
  i3c_pkg::rlt_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_rlt_mem_sink;

  smc_pkg::smc_axil_32_32_req_t     smc_efuse_bank_ctrl_req;
  smc_pkg::smc_axil_32_32_resp_t    smc_efuse_bank_ctrl_resp;
  smc_efuse_pkg::fuse_command_req_t  smc_efuse_shim_command_req;
  smc_efuse_pkg::fuse_command_resp_t smc_efuse_shim_command_resp;

  sep_efuse_pkg::efuse_axil_req_t    sep_efuse_bank_ctrl_req;
  sep_efuse_pkg::efuse_axil_resp_t   sep_efuse_bank_ctrl_resp;
  sep_efuse_pkg::fuse_command_req_t  sep_efuse_shim_command_req;
  sep_efuse_pkg::fuse_command_resp_t sep_efuse_shim_command_resp;

  // External TRNG loop: smu.sv exposes the SEP-side AXI-Lite master and AXI
  // stream sink, and sep_ip_integration provides the model that closes it.
  sep_pkg::sep_32_32_axil_req_t  ext_trng_axil_req;
  sep_pkg::sep_32_32_axil_resp_t ext_trng_axil_resp;

  ext_trng_axis_req_t ext_trng_axis_req [EXT_TRNG_NUM_AXIS-1:0];
  ext_trng_axis_rsp_t ext_trng_axis_rsp [EXT_TRNG_NUM_AXIS-1:0];

  logic ext_trng_irq;

  sep_crypto_pkg::abr_mem_req_t abr_mem_req;
  sep_crypto_pkg::abr_mem_rsp_t abr_mem_rsp;

  sep_pkg::sep_sram_req_t    sep_sram_req;
  sep_pkg::sep_sram_rsp_t    sep_sram_rsp;
  sep_pkg::sep_sram_req_t    sep_boot_rom_req;
  sep_pkg::sep_sram_rsp_t    sep_boot_rom_rsp;
  sep_pkg::sep_cpu_tcm_req_t sep_cpu_tcm_req;
  sep_pkg::sep_cpu_tcm_rsp_t sep_cpu_tcm_rsp;

  sep_crypto_pkg::sep_crypto_pka_imem_sram_req_t sep_crypto_pka_imem_sram_req;
  sep_crypto_pkg::sep_crypto_pka_imem_sram_rsp_t sep_crypto_pka_imem_sram_rsp;
  sep_crypto_pkg::sep_crypto_pka_dmem_sram_req_t sep_crypto_pka_dmem_sram_req;
  sep_crypto_pkg::sep_crypto_pka_dmem_sram_rsp_t sep_crypto_pka_dmem_sram_rsp;

  km_intf_pkg::km_rom_mem_req_t  km_rom_mem_req;
  km_intf_pkg::km_rom_mem_rsp_t  km_rom_mem_rsp;
  km_intf_pkg::km_sram_mem_req_t km_sram_mem_req;
  km_intf_pkg::km_sram_mem_rsp_t km_sram_mem_rsp;

  sep_pkg::sep_32_64_6_12_axi_req_t  sep_external_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t sep_external_resp;

  /////////////////////
  // SMU core        //
  /////////////////////

  smu #(
    .CFG                   (CFG),
    .SEP                   (SEP),
    .SEP_SEC_DISABLE_TOKEN (SEP_SEC_DISABLE_TOKEN),
    .EXT_TRNG_NUM_AXIS     (EXT_TRNG_NUM_AXIS),
    .ic_reset_ext_t         (ic_reset_ext_t)
  ) u_smu (
    .clk_smu_i    (clk_sys),
    .clk_ref_i    (clk_ref),
    .clk_periph_i (clk_periph),
    .rst_cold_ni,
    .rst_cold_stable_ref_clk_no,
    .powergood_i,
    .jtag_ptap_client_tap_ctrl_i,
    .jtag_ptap_client_tdi_i,
    .jtag_ptap_client_tdo_o,
    .jtag_ptap_client_tdo_oen_o,
    .jtag_bsr_host_scan_ctrl_o,
    .jtag_bsr_host_scan_in_i,
    .jtag_bsr_host_scan_out_o,
    .jtag_stap_io_host_tap_ctrl_o,
    .jtag_stap_io_host_tdi_i,
    .jtag_stap_io_host_tdo_o,
    .jtag_stap_io_host_tdo_oen_o,
    .jtag_stap_extra_host_tap_ctrl_o,
    .jtag_stap_extra_host_tdi_i,
    .jtag_stap_extra_host_tdo_o,
    .jtag_stap_extra_host_tdo_oen_o,
    .jtag_stap_host_scan_ctrl_o,
    .jtag_stap_host_scan_in_i,
    .jtag_stap_host_scan_out_o,
    .jtag_dfd_host_scan_ctrl_o,
    .jtag_dfd_host_scan_in_i,
    .jtag_dfd_host_scan_out_o,
    .jtag_dft_secure_host_scan_ctrl_o,
    .jtag_dft_secure_host_scan_in_i,
    .jtag_dft_secure_host_scan_out_o,
    .jtag_dft_host_scan_ctrl_o,
    .jtag_dft_host_scan_in_i,
    .jtag_dft_host_scan_out_o,
    .dtp_stop_clks_o,
    .jtag_ptap_state_o,
    .jtag_ptap_inst_decoded_o,
    .jtag_ic_reset_ext_o,
    .xtrig_ctm_src_req_o,
    .xtrig_ctm_src_ack_i,
    .xtrig_ctm_dst_req_i,
    .xtrig_ctm_dst_ack_o,
    .xtrig_clk_stop_req_i,
    .xtrig_ctp_req_out_dout_o,
    .xtrig_ctp_req_out_dout_en_o,
    .xtrig_ctp_req_out_din_i,
    .xtrig_ctp_req_out_din_en_o,
    .xtrig_ctp_req_in_dout_o,
    .xtrig_ctp_req_in_dout_en_o,
    .xtrig_ctp_req_in_din_i,
    .xtrig_ctp_req_in_din_en_o,
    .xtrig_ctp_ack_in_dout_o,
    .xtrig_ctp_ack_in_dout_en_o,
    .xtrig_ctp_ack_in_din_i,
    .xtrig_ctp_ack_in_din_en_o,
    .xtrig_ctp_ack_out_dout_o,
    .xtrig_ctp_ack_out_dout_en_o,
    .xtrig_ctp_ack_out_din_i,
    .xtrig_ctp_ack_out_din_en_o,
    .rst_primary_ref_clk_no,
    .rst_primary_smc_clk_no,
    .rst_primary_periph_clk_no,
    .smu_axi_in_req_i,
    .smu_axi_in_resp_o,
    .smu_axi_out_req_o,
    .smu_axi_out_resp_i,
    .lsio_interface_select_o,
    .rst_cool_n_from_pin_i,
    .clk_telemetry_i,
    .rst_telemetry_ni,
    .telemetry_atdata_i,
    .telemetry_atid_i,
    .telemetry_atready_o,
    .telemetry_atvalid_i,
    .telemetry_afvalid_o,
    .telemetry_afready_i,
    .smc_cluster_ded_o,
    .smc_wdt_first_timeout_o,
    .smc_wdt_second_timeout_o,
    .smc_global_base_o,
    .smc_region_size_o,
    .sep_global_base_o,
    .sep_region_size_o,
    .smc_ext_interrupts_i,
    .smc_fuse_sense_done_o,
    .smc_fuse_reset_n_delayed_o,
    .skip_mem_repair_o,
    .ext_boot_seq_done_i,
    .lc_state_o,
    .lc_sigint_err_o,
    .smc_ndmreset_request_i,
    .smc_ndmreset_process_o,
    .smc_ext_mailbox_interrupts_o,
    .cfg_flr_pf_active_i,
    .isolate_req_o,
    .ss_reset_complete_i,
    .ss_config_o,
    .ss_reset_ctrl_o,
    .sync_irq_o,
    .smc_disable_sram_auto_init_i,
    .smc_init_mem_done_o,
    .chiplet_is_primary_i,
    .timer_count_o,
    .test_en_i,
    .scan_rst_ni,
    .mem_repair_done_i,
    .mem_repair_success_i,
    .mem_repair_abort_i,
    .mbist_done_i,
    .mbist_pass_i,
    .mbist_abort_i,
    .entropy_rosc_sample_clk_i,
    .sep_io_spi_req_o,
    .sep_cpu_trace_o,
    .sep_lockstep_ctrl_i,
    .sep_lockstep_status_o,
    .sep_ext_interrupts_i,
    .lcc_demote_state_1_o,
    .lcc_demote_state_2_o,
    .secure_tm_o,
    .sep_fuse_dft_disable_o,
    .smc_fuse_dft_disable_o,
    .sep_fuse_sense_done_o,
    .clk_sep_wdt_i,
    .secure_tm_req_i,
    .gated_clk_periph_i3c_o,
    .ext_debug_bus_i,
    .gpio_interrupt_o,
    .uart_interrupt_o,
    .abr_mem_req_o (abr_mem_req),
    .abr_mem_rsp_i (abr_mem_rsp),

    .ext_trng_axil_req_o  (ext_trng_axil_req),
    .ext_trng_axil_resp_i (ext_trng_axil_resp),

    .ext_trng_axis_req_i (ext_trng_axis_req),
    .ext_trng_axis_rsp_o (ext_trng_axis_rsp),

    .ext_trng_irq_i (ext_trng_irq),

    .smc_external_req_o  (smc_external_req),
    .smc_external_resp_i (smc_external_resp),

    .pad2core_i    (pad2core),
    .core2pad_o    (core2pad),
    .pad2core_en_o (pad2core_en),
    .core2pad_en_o (core2pad_en),

    .smc_rom_intf_req_o            (smc_rom_intf_req),
    .smc_rom_intf_rsp_i            (smc_rom_intf_rsp),
    .smc_scratch_ram_intf_req_o    (smc_scratch_ram_intf_req),
    .smc_scratch_ram_intf_rsp_i    (smc_scratch_ram_intf_rsp),
    .smc_l1_icache_tag_intf_req_o  (smc_l1_icache_tag_intf_req),
    .smc_l1_icache_tag_intf_rsp_i  (smc_l1_icache_tag_intf_rsp),
    .smc_l1_icache_data_intf_req_o (smc_l1_icache_data_intf_req),
    .smc_l1_icache_data_intf_rsp_i (smc_l1_icache_data_intf_rsp),
    .smc_l1_dcache_tag_intf_req_o  (smc_l1_dcache_tag_intf_req),
    .smc_l1_dcache_tag_intf_rsp_i  (smc_l1_dcache_tag_intf_rsp),
    .smc_l1_dcache_data_intf_req_o (smc_l1_dcache_data_intf_req),
    .smc_l1_dcache_data_intf_rsp_i (smc_l1_dcache_data_intf_rsp),

    .i3c_dat_mem_src_i  (i3c_dat_mem_src),
    .i3c_dat_mem_sink_o (i3c_dat_mem_sink),
    .i3c_dct_mem_src_i  (i3c_dct_mem_src),
    .i3c_dct_mem_sink_o (i3c_dct_mem_sink),
    .i3c_rlt_mem_src_i  (i3c_rlt_mem_src),
    .i3c_rlt_mem_sink_o (i3c_rlt_mem_sink),

    .smc_efuse_bank_ctrl_req_o     (smc_efuse_bank_ctrl_req),
    .smc_efuse_bank_ctrl_resp_i    (smc_efuse_bank_ctrl_resp),
    .smc_efuse_shim_command_req_o  (smc_efuse_shim_command_req),
    .smc_efuse_shim_command_resp_i (smc_efuse_shim_command_resp),
    .smc_shadow_regs_o,
    .sep_efuse_bank_ctrl_req_o     (sep_efuse_bank_ctrl_req),
    .sep_efuse_bank_ctrl_resp_i    (sep_efuse_bank_ctrl_resp),
    .sep_efuse_shim_command_req_o  (sep_efuse_shim_command_req),
    .sep_efuse_shim_command_resp_i (sep_efuse_shim_command_resp),

    .sep_sram_req_o     (sep_sram_req),
    .sep_sram_rsp_i     (sep_sram_rsp),
    .sep_boot_rom_req_o (sep_boot_rom_req),
    .sep_boot_rom_rsp_i (sep_boot_rom_rsp),
    .sep_cpu_tcm_req_o  (sep_cpu_tcm_req),
    .sep_cpu_tcm_rsp_i  (sep_cpu_tcm_rsp),

    .sep_crypto_pka_imem_sram_req_o (sep_crypto_pka_imem_sram_req),
    .sep_crypto_pka_imem_sram_rsp_i (sep_crypto_pka_imem_sram_rsp),
    .sep_crypto_pka_dmem_sram_req_o (sep_crypto_pka_dmem_sram_req),
    .sep_crypto_pka_dmem_sram_rsp_i (sep_crypto_pka_dmem_sram_rsp),

    .sep_km_rom_mem_req_o  (km_rom_mem_req),
    .sep_km_rom_mem_rsp_i  (km_rom_mem_rsp),
    .sep_km_sram_mem_req_o (km_sram_mem_req),
    .sep_km_sram_mem_rsp_i (km_sram_mem_rsp),

    .sep_external_req_o  (sep_external_req),
    .sep_external_resp_i (sep_external_resp),

    .trace_mem_req_o  (trace_mem_req),
    .trace_mem_resp_i (trace_mem_resp)
  );

  /////////////////////////
  // SMC IP Integration  //
  /////////////////////////

  smc_ip_integration u_smc_ip_integration (
    .clk_ref_o    (clk_ref),
    .clk_sys_o    (clk_sys),
    .clk_periph_o (clk_periph),
    .rst_primary_smc_clk_ni  (rst_primary_smc_clk_no),

    .gated_clk_periph_i3c_i    (gated_clk_periph_i3c_o),
    .rst_primary_periph_clk_ni (rst_primary_periph_clk_no),

    .smc_external_req_i  (smc_external_req),
    .smc_external_resp_o (smc_external_resp),

    .test_en_i (test_en_i),

    .efuse_bank_ctrl_req_i     (smc_efuse_bank_ctrl_req),
    .efuse_bank_ctrl_resp_o    (smc_efuse_bank_ctrl_resp),
    .efuse_shim_command_req_i  (smc_efuse_shim_command_req),
    .efuse_shim_command_resp_o (smc_efuse_shim_command_resp),

    .pad2core_o    (pad2core),
    .core2pad_i    (core2pad),
    .pad2core_en_i (pad2core_en),
    .core2pad_en_i (core2pad_en),

    .gpio_pad_io (gpio_pad_io),

    .rom_intf_req            (smc_rom_intf_req),
    .rom_intf_rsp            (smc_rom_intf_rsp),
    .scratch_ram_intf_req    (smc_scratch_ram_intf_req),
    .scratch_ram_intf_rsp    (smc_scratch_ram_intf_rsp),
    .l1_icache_tag_intf_req  (smc_l1_icache_tag_intf_req),
    .l1_icache_tag_intf_rsp  (smc_l1_icache_tag_intf_rsp),
    .l1_icache_data_intf_req (smc_l1_icache_data_intf_req),
    .l1_icache_data_intf_rsp (smc_l1_icache_data_intf_rsp),
    .l1_dcache_tag_intf_req  (smc_l1_dcache_tag_intf_req),
    .l1_dcache_tag_intf_rsp  (smc_l1_dcache_tag_intf_rsp),
    .l1_dcache_data_intf_req (smc_l1_dcache_data_intf_req),
    .l1_dcache_data_intf_rsp (smc_l1_dcache_data_intf_rsp),

    .i3c_dat_mem_sink_i (i3c_dat_mem_sink),
    .i3c_dat_mem_src_o  (i3c_dat_mem_src),
    .i3c_dct_mem_sink_i (i3c_dct_mem_sink),
    .i3c_dct_mem_src_o  (i3c_dct_mem_src),
    .i3c_rlt_mem_sink_i (i3c_rlt_mem_sink),
    .i3c_rlt_mem_src_o  (i3c_rlt_mem_src),

    .trace_mem_req  (trace_mem_req),
    .trace_mem_resp (trace_mem_resp),

    .efuse_debug_bus_o (smc_efuse_debug_bus_o)
  );

  /////////////////////////
  // SEP IP Integration  //
  /////////////////////////

  sep_ip_integration #(
    .EXT_TRNG_NUM_AXIS (EXT_TRNG_NUM_AXIS),
    .ABR_MASKING_EN    (CFG.SEP_ABR_MASKING_EN)
  ) u_sep_ip_integration (
    .clk_i  (clk_sys),
    .rst_ni (rst_primary_smc_clk_no),

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

    .km_rom_mem_req_i (km_rom_mem_req),
    .km_rom_mem_rsp_o (km_rom_mem_rsp),
    .km_sram_mem_req_i (km_sram_mem_req),
    .km_sram_mem_rsp_o (km_sram_mem_rsp),

    .efuse_bank_ctrl_req_i     (sep_efuse_bank_ctrl_req),
    .efuse_bank_ctrl_resp_o    (sep_efuse_bank_ctrl_resp),
    .efuse_shim_command_req_i  (sep_efuse_shim_command_req),
    .efuse_shim_command_resp_o (sep_efuse_shim_command_resp),

    .ext_trng_axil_req_i  (ext_trng_axil_req),
    .ext_trng_axil_resp_o (ext_trng_axil_resp),

    .ext_trng_axis_req_o (ext_trng_axis_req),
    .ext_trng_axis_rsp_i (ext_trng_axis_rsp),

    .ext_trng_irq_o (ext_trng_irq),

    .abr_mem_req_i (abr_mem_req),
    .abr_mem_rsp_o (abr_mem_rsp),

    .axi_extension_axi_req_i  (sep_external_req),
    .axi_extension_axi_resp_o (sep_external_resp),

    .efuse_debug_bus_o (sep_efuse_debug_bus_o)
  );

endmodule
