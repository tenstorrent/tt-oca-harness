// SPDX-License-Identifier: Apache-2.0
//
// FIXME(SMU-DV): DEFERRED, not compiled by any active flow. This shadow was
// built against the old repository's integration layer: it references
// smc_ip_integration_pkg and efuse_otp_responder (both gone from this repo)
// and the pre-rewrite smc/sep_ip_integration port interfaces (pad-level SPI
// moved to struct ports; efuse models folded into the ip_integration
// modules). Rework it against hw/top/{smu_wrapper,smc_ip_integration,
// sep_ip_integration}.sv following the SEP wrapper migration before
// re-enabling the smu_wrapper flow.
//
// DV shadow of the legacy wrapper smu_wrapper.sv (issue #3357 flow).
// Identical to the hw/.bos source except that the internal
// `logic rst_cold_n;` declaration is removed: it redeclares the ANSI output
// port of the same name, which Verilator rejects as a duplicate declaration.
// The sim config excludes the hw/.bos copy from the filelist and
// compiles this file instead; drop this shadow once the hw fix lands.
//
//----------------------------------------------------------
// SMU Wrapper (OSS fork) -- OSS ip_integration + efuse OTP responders
//
// This module wraps the SMU (which contains DTP + SMC) along with
// the smc_ip_integration module (3rd party IP, macros, and shims).
//
// Copyright 2025 Tenstorrent Inc.
//----------------------------------------------------------

module smu_wrapper #(
    parameter smu_pkg::smu_cfg_t Cfg = smu_pkg::DefaultCfg,

    // SEP (Secure Execution Processor) enable. Declared int unsigned (not bit) so VC
    // SpyGlass `elaborate -param SEP=0` can override it; -gfile cannot override bit-typed params.
    parameter int unsigned  SEP                   = 1,

    // Type parameter for the external IC_RESET TDR slice exposed to the SMU caller. Defaults to
    // `logic` (slice effectively unused); integrators override with a packed struct containing
    // `.ovrd` and `.val` sub-structs of matching width, and must either drive the resulting
    // struct output or disable the slice via `Cfg.JTAG_IC_RESET_ENABLE = 1'b0`.
    parameter type          ic_reset_ext_t        = jtag_tap_pkg::jtag_ic_reset_default_t,

    // IP Integration parameters
    localparam int unsigned NUM_CGMS = 2,
    localparam int unsigned NUM_AWMS = 2,
    localparam int unsigned NUM_USED_CGM_CLOCKS = 2,
    localparam int unsigned NUM_USED_AWM_CLOCKS = 5,

    localparam int unsigned JTAG_NUM_EXTRA_STAP_PORTS = (Cfg.JTAG_NUM_EXTRA_STAPS > 0) ? Cfg.JTAG_NUM_EXTRA_STAPS : 1,

    localparam int unsigned XTRIG_NUM_INT_CT = dtp_pkg::DEFAULT_NUM_INT_CT - 2
)(
    // Pad interfaces (to smc_ip_integration)
    output logic ref_clk_vdd_o,
    output logic rst_cold_n,

    // REFCLKs in
    input wire BP_REFCLK,

    // Chip reset
    input wire BP_RESETN,

    // Power good
    input wire BP_POWERGOOD,

    // JTAG pads (to smc_ip_integration)
    inout wire BP_P_TCK,
    inout wire BP_P_TMS,
    inout wire BP_P_TRSTN,
    inout wire BP_P_TDI,
    inout wire BP_P_TDO,

    inout wire BP_S_TCK,
    inout wire BP_S_TMS,
    inout wire BP_S_TRSTN,
    inout wire BP_S_TDI,
    inout wire BP_S_TDO,

    // Cross-trigger pads
    inout wire [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] BP_XTRIG_REQ_OUT,
    inout wire [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] BP_XTRIG_REQ_IN,
    inout wire [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] BP_XTRIG_ACK_IN,
    inout wire [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] BP_XTRIG_ACK_OUT,

    // GPIO PADs
    inout  wire [smc_pkg::NUM_BONDED_GPIO-1:0]  GPIO_PAD,

    // Unbonded GPIOs
    inout wire [smc_pkg::NUM_UNBONDED_GPIO-1:0] BP_UNBONDED_GPIO,

    // Efuse pads
    inout wire BP_FUSE_SMC_VPP,
    inout wire BP_FUSE_SMC_VREFM,
    inout wire BP_FUSE_SMC_VTDO,

    // Test/DFT
    // Default tie-offs when unused: test_en_i=1'b0, scan_rst_ni=1'b1.
    input  logic test_en_i,
    input  logic scan_rst_ni,

    // Security Signals
    input  logic secure_tm_i,
    input  logic [1:0] lcc_demote_state_1_i,
    input  logic [1:0] lcc_demote_state_2_i,

    // Memory initialization status
    output logic init_mem_done_o,

    // Reference Clock
    input  logic ref_clk_vdd_sys_dfx_i,

    // Boundary Scan Interface (from DTP)
    output prim_jtag_pkg::jtag_scan_ctrl_t  jtag_bsr_host_scan_ctrl_o,
    input  logic             jtag_bsr_host_scan_in_i,
    output logic             jtag_bsr_host_scan_out_o,

    // Extra STAP Interfaces (from DTP)
    output prim_jtag_pkg::jtag_tap_ctrl_t  jtag_stap_extra_host_tap_ctrl_o [JTAG_NUM_EXTRA_STAP_PORTS-1:0],
    input  logic            jtag_stap_extra_host_tdi_i      [JTAG_NUM_EXTRA_STAP_PORTS-1:0],
    output logic            jtag_stap_extra_host_tdo_o      [JTAG_NUM_EXTRA_STAP_PORTS-1:0],
    output logic            jtag_stap_extra_host_tdo_oen_o  [JTAG_NUM_EXTRA_STAP_PORTS-1:0],

    // Extended STAP Scan Interface (from DTP)
    output prim_jtag_pkg::jtag_scan_ctrl_t  jtag_stap_host_scan_ctrl_o,
    input  logic             jtag_stap_host_scan_in_i,
    output logic             jtag_stap_host_scan_out_o,

    // DFD iJTAG Interface (from DTP)
    output prim_jtag_pkg::jtag_scan_ctrl_t  jtag_dfd_host_scan_ctrl_o,
    input  logic             jtag_dfd_host_scan_in_i,
    output logic             jtag_dfd_host_scan_out_o,

    // Secure DFT iJTAG Interface (from DTP)
    output prim_jtag_pkg::jtag_scan_ctrl_t  jtag_dft_secure_host_scan_ctrl_o,
    input  logic             jtag_dft_secure_host_scan_in_i,
    output logic             jtag_dft_secure_host_scan_out_o,

    // Non-secure DFT iJTAG Interface (from DTP)
    output prim_jtag_pkg::jtag_scan_ctrl_t  jtag_dft_host_scan_ctrl_o,
    input  logic             jtag_dft_host_scan_in_i,
    output logic             jtag_dft_host_scan_out_o,

    // JTAG State Outputs (from DTP)
    output jtag_tap_pkg::tap_state_e                 jtag_ptap_state_o,
    output jtag_inst_reg_pkg::jtag_instruction_decoded_e  jtag_ptap_inst_decoded_o,

    // JTAG External IC_RESET TDR Slice (typed packed struct; `.ovrd` + `.val` halves).
    // Driven by the DTP's external IC_RESET slice when `Cfg.JTAG_IC_RESET_ENABLE = 1'b1`;
    // otherwise tied to '0 inside the SMU.
    output ic_reset_ext_t  jtag_ic_reset_ext_o,

    // Cross Trigger Matrix Interface (from DTP)
    output logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_src_req_o,
    input  logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_src_ack_i,
    input  logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_dst_req_i,
    output logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_dst_ack_o,

    // Clock Stop Request Interface (from DTP)
    input  logic [dtp_pkg::DEFAULT_NUM_CLK_STOP_REQ-2:0]  xtrig_clk_stop_req_i,

    // SMU AXI Crossbar External Ports (toward SMN)
    input  smu_axi_xbar_pkg::axi_56_64_req_t   smu_axi_in_req_i,
    output smu_axi_xbar_pkg::axi_56_64_resp_t  smu_axi_in_resp_o,
    output smu_axi_xbar_pkg::axi_out_req_t      smu_axi_out_req_o,
    input  smu_axi_xbar_pkg::axi_out_resp_t     smu_axi_out_resp_i,

    // AXI-L interface for adopter peripheral extension
    output smc_pkg::smc_axil_32_32_req_t  smc_axil_extension_req_o,
    input  smc_pkg::smc_axil_32_32_resp_t smc_axil_extension_resp_i,

    // PLL outputs (from smc_ip_integration)
    output logic [NUM_USED_CGM_CLOCKS-1:0] pll_cgm_clk_o,
    output logic [NUM_USED_AWM_CLOCKS-1:0] pll_awm_clk_o,
    input  logic [NUM_USED_CGM_CLOCKS-1:0] pll_cgm_clk_dfx_i,
    input  logic [NUM_USED_AWM_CLOCKS-1:0] pll_awm_clk_dfx_i,

    // PVT inputs
    input  logic [63:0][7:0] tile_event_i,

    // Efuse signals
    output logic                           fuse_sense_done_o,
    output logic                           fuse_reset_n_delayed_o,

    // Lifecycle integrity error signals
    output logic                           lc_sigint_err_o,
    output logic                           demote_sigint_err_o,

    // External boot / memory-repair signals
    output logic                           skip_mem_repair_o,
    input  logic                           ext_boot_seq_done_i,

    // interrupts
    input  logic [Cfg.NUM_INT_TO_SMC-1:0]  interrupts_i,
    output logic [smc_pkg::NUM_MAILBOXES-1:0]       ext_mailbox_interrupt_o,
    output logic [smc_config_pkg::NUM_UART-1:0]     uart_interrupt_o,
    output logic [smc_pkg::NUM_GPIO_WRAPS-1:0]      gpio_interrupt_o,

    // Captured straps
    output logic [smc_pkg::NUM_BONDED_GPIO-1:0]     captured_straps_o,

    output logic                           sync_irq_o,

    // ndmreset_request
    input  logic [smc_config_pkg::CPU_CLUSTER_COUNT - 1:0]  ndmreset_request_i, //TODO: Drive this wire
    output logic [smc_config_pkg::CPU_CLUSTER_COUNT - 1:0]  ndmreset_process_o,

    // Reset Unit Signals
    input  logic  cfg_flr_pf_active_i,
    output logic [31:0] isolate_req_o,
    input  logic [31:0] ss_reset_complete_i,
    output logic [31:0] ss_config_o,
    output smc_reset_unit_pkg::reset_ctrl_t ss_reset_ctrl_o[31:0],

    // SMC and SEP apertures (base + size) surfaced at the wrapper boundary
    output smc_pkg::smc_axi_addr_t                                   smc_global_base_addr_o,
    output logic [31:0]                                              smc_region_size_o,
    output logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_global_base_addr_o,
    output logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_region_size_o,

    // telemetry data
    input logic       telemetry_clk_i,
    input logic       telemetry_reset_n_i,
    input logic       noc_o_telemetry_atvalid_i,
    input logic [7:0] noc_o_telemetry_atdata_i,
    input logic       noc_m_telemetry_atvalid_i,
    input logic [7:0] noc_m_telemetry_atdata_i,
    input logic       noc_n_telemetry_atvalid_i,
    input logic [7:0] noc_n_telemetry_atdata_i,

    // SPI
    input  wire       spi_enable_i,
    input  wire       spi_clk_i,
    input  wire [7:0] spi_txd_i,
    input  wire       spi_cs_n_i,
    input  wire       spi_cs_oe_n_i,
    input  wire       spi_cs_ie_n_i,
    input  wire       spi_clk_ie_n_i,
    input  wire       spi_clk_oe_n_i,
    input  wire       spi_dqs_ie_n_i,
    input  wire       spi_dqs_oe_n_i,
    input  wire [7:0] spi_dq_ie_n_i,
    input  wire [7:0] spi_dq_oe_n_i,
    output wire [7:0] spi_rxd_o,
    output wire       spi_rxds_o,
    input  wire       spi_mem_rebar_oepad_i,
    input  wire       spi_mem_rebar_opad_i,
    input  wire       spi_mem_rebar_iepad_i,
    output wire       spi_mem_rebar_ipad_o,

    // PVT
    input wire              cat_therm_i,
    input logic [63:0][7:0] tile_event_i_pvt,
    input logic [2:0]       droop_event_i,

    // Powergood output from Pad
    output logic powergood_o,

    // System Timer OCTS Interface
    output logic [63:0] timer_count_o,

    // indicators for DFT status
    input  logic mem_repair_done_i,
    input  logic mem_repair_success_i,
    input  logic mem_repair_abort_i,
    input  logic mbist_done_i,
    input  logic mbist_pass_i,
    input  logic mbist_abort_i,

    // =========================================================================
    // SEP External Ports (SEP SPI is routed internally to SMC padring when SEP)
    // =========================================================================

    // SEP WDT clock
    input  logic  clk_sep_wdt_i,

    // SEP lifecycle demote outputs (now driven by SEP instead of external input)
    output logic [1:0]  lcc_demote_state_1_o,
    output logic [1:0]  lcc_demote_state_2_o,
    output logic        secure_tm_o,

    // SEP fuse sense done
    output logic  sep_fuse_sense_done_o,

    // SEP external interrupts
    input  wire logic [sep_pkg::NUM_EXTERNAL_IRQS-1:0]  sep_extintsrc_req_i,

    // I3C DAT/DCT memory interfaces
    input  i3c_pkg::dat_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_src_i,
    output i3c_pkg::dat_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_sink_o,
    input  i3c_pkg::dct_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_src_i,
    output i3c_pkg::dct_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_sink_o
);

    /////////////////////////
    // Signal Declarations //
    /////////////////////////

    // Clock signals
    logic smc_clk;
    logic ref_clk_vdd_sys;
    logic periph_clk;

    // Reset signals
    logic rst_cold_stable_ref_clk_n; // stable cold reset from pad to reset unit
    logic powergood;                 // powergood signal from pad to reset unit
    logic rst_primary_ref_clk_n;
    logic rst_primary_smc_clk_n;
    logic rst_primary_periph_clk_n;

    // Primary JTAG interface signals
    logic jtag_ptap_tck;
    logic jtag_ptap_tms;
    logic jtag_ptap_trstn;
    logic jtag_ptap_tdi;
    logic jtag_ptap_tdo;

    // Secondary JTAG interface signals
    logic jtag_stap_tdi;
    logic jtag_stap_tdo;

    // JTAG struct signal for SMU STAP IO host output
    prim_jtag_pkg::jtag_tap_ctrl_t jtag_stap_io_host_tap_ctrl;

    // GPIO AXI-Lite signals
    gpio_pkg::gpio_axil_req_t  axil_req_gpio_ctrl;
    gpio_pkg::gpio_axil_resp_t axil_resp_gpio_ctrl;

    // GPIO signals
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] lsio_interface_select;
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core;
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad;
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core_en;
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad_en;

    // GPIO capture straps
    logic [smc_pkg::NUM_BONDED_GPIO-1:0] captured_straps;

    // SEP straps derived from captured padring straps
    sep_pkg::sep_straps_t sep_straps;

    // Interface Shim AXI-Lite signals
    smc_pkg::smc_axil_32_32_req_t  axil_pll_req;
    smc_pkg::smc_axil_32_32_resp_t axil_pll_resp;
    smc_pkg::smc_axil_32_32_req_t  axil_pvt_req;
    smc_pkg::smc_axil_32_32_resp_t axil_pvt_resp;
    smc_pkg::smc_axil_32_32_req_t  axil_extension_req;
    smc_pkg::smc_axil_32_32_resp_t axil_extension_resp;

    // ATB Telemetry signals
    logic clk_telemetry;
    logic rst_telemetry_n;
    telemetry_receiver_pkg::telemetry_data_t [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atdata;
    telemetry_receiver_pkg::atb_id_t         [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atid;
    logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atready;
    logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atvalid;
    logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_afvalid;
    logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_afready;

    // RAS bank settings
    logic [3:0] ras_bank_chip_o;
    logic [3:0] ras_bank_instance_o;

    // Unused SMC outputs
    logic cluster_ded_o;
    logic wdt_first_timeout_o;
    logic wdt_second_timeout_o;

    // Efuse Signals
    smc_pkg::smc_axil_32_32_req_t smc_efuse_bank_ctrl_req;
    smc_pkg::smc_axil_32_32_resp_t smc_efuse_bank_ctrl_resp;
    smc_efuse_pkg::fuse_command_req_t smc_efuse_shim_command_req;
    smc_efuse_pkg::fuse_command_resp_t smc_efuse_shim_command_resp;
    smc_efuse_pkg::efuse_map_t smc_shadow_regs;

    // Interrupts
    logic [2:0] temp_interrupt;

    // Signals from IP integration
    logic disable_sram_auto_init;
    logic cool_rst_n_from_pin;

    // Lifecycle state
    logic [2*smc_pkg::LC_STATE_WIDTH-1:0] lc_state;

    // Integrity error signals
    logic efuse_lc_sigint_err;
    logic ip_integ_lc_sigint_err;
    logic ip_integ_demote_sigint_err;

    assign lc_sigint_err_o     = efuse_lc_sigint_err | ip_integ_lc_sigint_err;
    assign demote_sigint_err_o = ip_integ_demote_sigint_err;

    // Clock control signal from DTP to PLL
    logic dtp_stop_clks;

    // =========================================================================
    // SEP Passthrough Signals (smu <-> sep_ip_integration)
    // =========================================================================
    sep_pkg::sep_sram_req_t     sep_sram_req;
    sep_pkg::sep_sram_rsp_t     sep_sram_rsp;
    sep_pkg::sep_sram_req_t     sep_boot_rom_req;
    sep_pkg::sep_sram_rsp_t     sep_boot_rom_rsp;
    sep_pkg::sep_cpu_tcm_req_t  sep_cpu_tcm_req;
    sep_pkg::sep_cpu_tcm_rsp_t  sep_cpu_tcm_rsp;

    sep_efuse_pkg::efuse_axil_req_t    sep_efuse_bank_ctrl_req;
    sep_efuse_pkg::efuse_axil_resp_t   sep_efuse_bank_ctrl_resp;
    sep_efuse_pkg::fuse_command_req_t  sep_efuse_shim_command_req;
    sep_efuse_pkg::fuse_command_resp_t sep_efuse_shim_command_resp;

    sep_crypto_pkg::sep_crypto_pka_imem_sram_req_t  sep_crypto_pka_imem_sram_req;
    sep_crypto_pkg::sep_crypto_pka_imem_sram_rsp_t  sep_crypto_pka_imem_sram_rsp;
    sep_crypto_pkg::sep_crypto_pka_dmem_sram_req_t  sep_crypto_pka_dmem_sram_req;
    sep_crypto_pkg::sep_crypto_pka_dmem_sram_rsp_t  sep_crypto_pka_dmem_sram_rsp;

    km_intf_pkg::km_rom_mem_req_t   sep_km_rom_mem_req;
    km_intf_pkg::km_rom_mem_rsp_t   sep_km_rom_mem_rsp;
    km_intf_pkg::km_sram_mem_req_t  sep_km_sram_mem_req;
    km_intf_pkg::km_sram_mem_rsp_t  sep_km_sram_mem_rsp;

    sep_io_pkg::sep_io_spi_req_t  sep_io_spi_req;
    sep_io_pkg::sep_io_spi_rsp_t  sep_io_spi_rsp;

    // OT SPI IRQ (from SEP via SMU)
    logic ot_spi_irq;
    logic cdns_spi_irq;
    logic spi_irq;

    sep_pkg::sep_32_64_6_12_axi_req_t   sep_axi_extension_req;
    sep_pkg::sep_32_64_6_12_axi_resp_t  sep_axi_extension_resp;

    logic  sep_reset_n;
    logic [15:0] smc_efuse_debug_bus_o;
    logic [15:0] sep_efuse_debug_bus_o;

    sep_pkg::jtag_sep_reset_ctrl_t      jtag_sep_reset_ctrl;
    sep_pkg::sep_32_32_axil_req_t       sep_ext_trng_axil_req;
    sep_crypto_pkg::ext_trng_axis_rsp_t sep_ext_trng_axis_rsp [2];

    assign smc_efuse_debug_bus_o = '0;
    assign sep_efuse_debug_bus_o = '0;
    // Observe-only passthrough; SMC uses internal axil_extension_resp from I3C stub
    assign smc_axil_extension_req_o = axil_extension_req;
    assign jtag_sep_reset_ctrl     = '0;
    assign sep_ext_trng_axil_req   = '0;
    assign sep_ext_trng_axis_rsp   = '{default: '0};

    // SEP CPU trace: currently unused in SMU integration (no consumer connected)
    sep_pkg::sep_cpu_trace_t  sep_cpu_trace;

    logic [1:0]  lcc_demote_state_1;
    logic [1:0]  lcc_demote_state_2;
    logic [1:0]  lcc_demote_muxed_1;
    logic [1:0]  lcc_demote_muxed_2;

    // SEP SPI to SMC padring (internal path when SEP)
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
    logic                        sep_spi_mem_rebar_oepad;
    logic                        sep_spi_mem_rebar_opad;
    logic                        sep_spi_mem_rebar_iepad;
    logic [7:0]                  sep_spi_rxd;
    logic                        sep_spi_rxds;
    logic                        sep_spi_mem_rebar_ipad;

    // Cross Trigger Port GPIO signals (from SMU to smc_ip_integration)
    // TODO: Connect to smc_ip_integration when ready
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_req_out_dout;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_req_out_dout_en;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_req_out_din;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_req_out_din_en;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_req_in_dout;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_req_in_dout_en;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_req_in_din;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_req_in_din_en;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_ack_in_dout;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_ack_in_dout_en;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_ack_in_din;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_ack_in_din_en;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_ack_out_dout;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_ack_out_dout_en;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_ack_out_din;
    logic [dtp_pkg::DEFAULT_NUM_CTP-1:0]  xtrig_ctp_ack_out_din_en;

    // CTP input tie-offs (until connected to smc_ip_integration)
    assign xtrig_ctp_req_out_din = '0;
    assign xtrig_ctp_req_in_din = '0;
    assign xtrig_ctp_ack_in_din = '0;
    assign xtrig_ctp_ack_out_din = '0;

    // CPU Memory Signals
    chipyard_4core_mem_pkg::rom_req_t              rom_intf_req;
    chipyard_4core_mem_pkg::rom_rsp_t              rom_intf_rsp;
    chipyard_4core_mem_pkg::scratch_ram_req_t      scratch_ram_intf_req     [32-1:0];
    chipyard_4core_mem_pkg::scratch_ram_rsp_t      scratch_ram_intf_rsp     [32-1:0];
    chipyard_4core_mem_pkg::l1_icache_tag_req_t    l1_icache_tag_intf_req   [4-1:0];
    chipyard_4core_mem_pkg::l1_icache_tag_rsp_t    l1_icache_tag_intf_rsp   [4-1:0];
    chipyard_4core_mem_pkg::l1_icache_data_req_t   l1_icache_data_intf_req  [8-1:0];
    chipyard_4core_mem_pkg::l1_icache_data_rsp_t   l1_icache_data_intf_rsp  [8-1:0];
    chipyard_4core_mem_pkg::l1_dcache_tag_req_t    l1_dcache_tag_intf_req   [4-1:0];
    chipyard_4core_mem_pkg::l1_dcache_tag_rsp_t    l1_dcache_tag_intf_rsp   [4-1:0];
    chipyard_4core_mem_pkg::l1_dcache_data_req_t   l1_dcache_data_intf_req  [4-1:0];
    chipyard_4core_mem_pkg::l1_dcache_data_rsp_t   l1_dcache_data_intf_rsp   [4-1:0];

    // Debug Memory Signals
    dfd_trace_mem_pkg::SinkMemPktIn_s  [dfd_tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_req;
    dfd_trace_mem_pkg::SinkMemPktOut_s [dfd_tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_resp;

    // OCA I3C DAT/DCT Memory Signals
    i3c_pkg::dat_mem_src_t   [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_src;
    i3c_pkg::dat_mem_sink_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_sink;
    i3c_pkg::dct_mem_src_t   [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_src;
    i3c_pkg::dct_mem_sink_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_sink;

    // Debug signals
    logic [127:0] ext_debug_bus;
    assign ext_debug_bus = {96'b0, sep_efuse_debug_bus_o, smc_efuse_debug_bus_o};

    /////////////
    // SMU Top //
    /////////////

    // Derive the SEP strap struct from the captured padring straps.
    always_comb begin
        sep_straps = '0;
        sep_straps.test_straps.test_en           = captured_straps_o[smc_ip_integration_pkg::TEST_EN_STRAP_ID];
        sep_straps.boot_straps.bypass_mem_repair = captured_straps_o[smc_ip_integration_pkg::BYPASS_MEM_REPAIR_STRAP_ID];
    end

    smu #(
        .Cfg             (Cfg),
        .SEP             (SEP),
        .ic_reset_ext_t  (ic_reset_ext_t)
    ) u_smu (
        // Clock and Reset
        .clk_smu_i                              (smc_clk),
        .clk_ref_i                              (ref_clk_vdd_sys_dfx_i),
        .clk_periph_i                           (periph_clk),
        .rst_cold_ni                            (rst_cold_n),

        // Stable Cold Reset
        .rst_cold_stable_ref_clk_no             (rst_cold_stable_ref_clk_n),

        .powergood_i                            (powergood),

        // Primary JTAG TAP Interface
        .jtag_ptap_client_tap_ctrl_i            ('{tms: jtag_ptap_tms, trst_n: jtag_ptap_trstn, tck: jtag_ptap_tck}),
        .jtag_ptap_client_tdi_i                 (jtag_ptap_tdi),
        .jtag_ptap_client_tdo_o                 (jtag_ptap_tdo),
        .jtag_ptap_client_tdo_oen_o             (/* UNUSED */),

        // Boundary Scan Interface
        .jtag_bsr_host_scan_ctrl_o              (jtag_bsr_host_scan_ctrl_o),
        .jtag_bsr_host_scan_in_i                (jtag_bsr_host_scan_in_i),
        .jtag_bsr_host_scan_out_o               (jtag_bsr_host_scan_out_o),

        // I/O STAP Interface
        .jtag_stap_io_host_tap_ctrl_o           (jtag_stap_io_host_tap_ctrl),
        .jtag_stap_io_host_tdi_i                (jtag_stap_tdi),
        .jtag_stap_io_host_tdo_o                (jtag_stap_tdo),
        .jtag_stap_io_host_tdo_oen_o            (/* UNUSED */),

        // Extra STAP Interfaces
        .jtag_stap_extra_host_tap_ctrl_o        (jtag_stap_extra_host_tap_ctrl_o),
        .jtag_stap_extra_host_tdi_i             (jtag_stap_extra_host_tdi_i),
        .jtag_stap_extra_host_tdo_o             (jtag_stap_extra_host_tdo_o),
        .jtag_stap_extra_host_tdo_oen_o         (jtag_stap_extra_host_tdo_oen_o),

        // Extended STAP Scan Interface
        .jtag_stap_host_scan_ctrl_o             (jtag_stap_host_scan_ctrl_o),
        .jtag_stap_host_scan_in_i               (jtag_stap_host_scan_in_i),
        .jtag_stap_host_scan_out_o              (jtag_stap_host_scan_out_o),

        // DFD iJTAG Interface
        .jtag_dfd_host_scan_ctrl_o              (jtag_dfd_host_scan_ctrl_o),
        .jtag_dfd_host_scan_in_i                (jtag_dfd_host_scan_in_i),
        .jtag_dfd_host_scan_out_o               (jtag_dfd_host_scan_out_o),

        // Secure DFT iJTAG Interface
        .jtag_dft_secure_host_scan_ctrl_o       (jtag_dft_secure_host_scan_ctrl_o),
        .jtag_dft_secure_host_scan_in_i         (jtag_dft_secure_host_scan_in_i),
        .jtag_dft_secure_host_scan_out_o        (jtag_dft_secure_host_scan_out_o),

        // Non-secure DFT iJTAG Interface
        .jtag_dft_host_scan_ctrl_o              (jtag_dft_host_scan_ctrl_o),
        .jtag_dft_host_scan_in_i                (jtag_dft_host_scan_in_i),
        .jtag_dft_host_scan_out_o               (jtag_dft_host_scan_out_o),

        // Clock Control
        .dtp_stop_clks_o                        (dtp_stop_clks),

        // JTAG State Outputs
        .jtag_ptap_state_o                      (jtag_ptap_state_o),
        .jtag_ptap_inst_decoded_o               (jtag_ptap_inst_decoded_o),

        // JTAG External IC_RESET TDR Slice
        .jtag_ic_reset_ext_o                    (jtag_ic_reset_ext_o),

        // Cross Trigger Matrix Interface
        .xtrig_ctm_src_req_o                    (xtrig_ctm_src_req_o),
        .xtrig_ctm_src_ack_i                    (xtrig_ctm_src_ack_i),
        .xtrig_ctm_dst_req_i                    (xtrig_ctm_dst_req_i),
        .xtrig_ctm_dst_ack_o                    (xtrig_ctm_dst_ack_o),

        // Clock Stop Request Interface
        .xtrig_clk_stop_req_i                   (xtrig_clk_stop_req_i),

        // Cross Trigger Port GPIO Interface (internal signals - TODO: connect to smc_ip_integration)
        .xtrig_ctp_req_out_dout_o               (xtrig_ctp_req_out_dout),
        .xtrig_ctp_req_out_dout_en_o            (xtrig_ctp_req_out_dout_en),
        .xtrig_ctp_req_out_din_i                (xtrig_ctp_req_out_din),
        .xtrig_ctp_req_out_din_en_o             (xtrig_ctp_req_out_din_en),
        .xtrig_ctp_req_in_dout_o                (xtrig_ctp_req_in_dout),
        .xtrig_ctp_req_in_dout_en_o             (xtrig_ctp_req_in_dout_en),
        .xtrig_ctp_req_in_din_i                 (xtrig_ctp_req_in_din),
        .xtrig_ctp_req_in_din_en_o              (xtrig_ctp_req_in_din_en),
        .xtrig_ctp_ack_in_dout_o                (xtrig_ctp_ack_in_dout),
        .xtrig_ctp_ack_in_dout_en_o             (xtrig_ctp_ack_in_dout_en),
        .xtrig_ctp_ack_in_din_i                 (xtrig_ctp_ack_in_din),
        .xtrig_ctp_ack_in_din_en_o              (xtrig_ctp_ack_in_din_en),
        .xtrig_ctp_ack_out_dout_o               (xtrig_ctp_ack_out_dout),
        .xtrig_ctp_ack_out_dout_en_o            (xtrig_ctp_ack_out_dout_en),
        .xtrig_ctp_ack_out_din_i                (xtrig_ctp_ack_out_din),
        .xtrig_ctp_ack_out_din_en_o             (xtrig_ctp_ack_out_din_en),

        // SMU Resets
        .rst_primary_ref_clk_no                 (rst_primary_ref_clk_n),
        .rst_primary_smc_clk_no                 (rst_primary_smc_clk_n),
        .rst_primary_periph_clk_no              (rst_primary_periph_clk_n),

        // SMU AXI Crossbar External Ports
        .smu_axi_in_req_i                       (smu_axi_in_req_i),
        .smu_axi_in_resp_o                      (smu_axi_in_resp_o),
        .smu_axi_out_req_o                      (smu_axi_out_req_o),
        .smu_axi_out_resp_i                     (smu_axi_out_resp_i),

        // PLL Interface AXI-Lite
        .axil_pll_req_o                         (axil_pll_req),
        .axil_pll_resp_i                        (axil_pll_resp),

        // PVT Interface AXI-Lite
        .axil_pvt_req_o                         (axil_pvt_req),
        .axil_pvt_resp_i                        (axil_pvt_resp),

        // Adopter peripheral AXI-Lite extension (loopback to OSS I3C stub in ip_integration)
        .smc_axil_extension_req_o               (axil_extension_req),
        .smc_axil_extension_resp_i              (axil_extension_resp),

        // eFuse Interface
        .smc_efuse_bank_ctrl_req_o              (smc_efuse_bank_ctrl_req),
        .smc_efuse_bank_ctrl_resp_i             (smc_efuse_bank_ctrl_resp),
        .smc_efuse_shim_command_req_o           (smc_efuse_shim_command_req),
        .smc_efuse_shim_command_resp_i          (smc_efuse_shim_command_resp),
        .smc_shadow_regs_o                      (smc_shadow_regs),

        // GPIO Shim Interface
        .axil_req_gpio_ctrl_o                   (axil_req_gpio_ctrl),
        .axil_resp_gpio_ctrl_i                  (axil_resp_gpio_ctrl),

        // GPIO Data Signals
        .lsio_interface_select_o                (lsio_interface_select),
        .pad2core_i                             (pad2core),
        .core2pad_o                             (core2pad),
        .pad2core_en_o                          (pad2core_en),
        .core2pad_en_o                          (core2pad_en),

        // GPIO External Pins
        .rst_cool_n_from_pin_i                  (cool_rst_n_from_pin),

        // ATB Telemetry
        .clk_telemetry_i                        (clk_telemetry),
        .rst_telemetry_ni                       (rst_telemetry_n),
        .telemetry_atdata_i                     (telemetry_atdata),
        .telemetry_atid_i                       (telemetry_atid),
        .telemetry_atready_o                    (telemetry_atready),
        .telemetry_atvalid_i                    (telemetry_atvalid),
        .telemetry_afvalid_o                    (telemetry_afvalid),
        .telemetry_afready_i                    (telemetry_afready),

        // DED/WDT
        .cluster_ded_o                          (cluster_ded_o),
        .wdt_first_timeout_o                    (wdt_first_timeout_o),
        .wdt_second_timeout_o                   (wdt_second_timeout_o),

        // SMC and SEP apertures (base + size)
        .smc_global_base_o                      (smc_global_base_addr_o),
        .smc_region_size_o                      (smc_region_size_o),
        .sep_global_base_o                      (sep_global_base_addr_o),
        .sep_region_size_o                      (sep_region_size_o),

        // External Interrupts
        .ext_interrupts_i                       (interrupts_i),

        // Fuse Signals
        .fuse_sense_done_o                      (fuse_sense_done_o),
        .fuse_reset_n_delayed_o                 (fuse_reset_n_delayed_o),

        // DFT Signals
        .skip_mem_repair_o                      (skip_mem_repair_o),
        .ext_boot_seq_done_i                    (ext_boot_seq_done_i),

        // PVT
        .temp_interrupt_i                       (|temp_interrupt),

        // Lifecycle State (driven by SEP)
        .lc_state_o                             (lc_state),
        .lc_sigint_err_o                        (efuse_lc_sigint_err),

        // RAS Bank Settings
        .ras_bank_chip_o                        (ras_bank_chip_o),
        .ras_bank_instance_o                    (ras_bank_instance_o),

        // NDM Reset
        .ndmreset_request_i                     (ndmreset_request_i),
        .ndmreset_process_o                     (ndmreset_process_o),

        // Mailbox Interrupts
        .ext_mailbox_interrupts_o               (ext_mailbox_interrupt_o),

        // Reset Unit Signals
        .cfg_flr_pf_active_i                    (cfg_flr_pf_active_i),
        .isolate_req_o                          (isolate_req_o),
        .ss_reset_complete_i                    (ss_reset_complete_i),
        .ss_config_o                            (ss_config_o),
        .ss_reset_ctrl_o                        (ss_reset_ctrl_o),
        .sync_irq_o                             (sync_irq_o),

        // CPU Memory Signals
        .rom_intf_req_o                         (rom_intf_req),
        .rom_intf_rsp_i                         (rom_intf_rsp),
        .scratch_ram_intf_req_o                 (scratch_ram_intf_req),
        .scratch_ram_intf_rsp_i                 (scratch_ram_intf_rsp),
        .l1_icache_tag_intf_req_o               (l1_icache_tag_intf_req),
        .l1_icache_tag_intf_rsp_i               (l1_icache_tag_intf_rsp),
        .l1_icache_data_intf_req_o              (l1_icache_data_intf_req),
        .l1_icache_data_intf_rsp_i              (l1_icache_data_intf_rsp),
        .l1_dcache_tag_intf_req_o               (l1_dcache_tag_intf_req),
        .l1_dcache_tag_intf_rsp_i               (l1_dcache_tag_intf_rsp),
        .l1_dcache_data_intf_req_o              (l1_dcache_data_intf_req),
        .l1_dcache_data_intf_rsp_i              (l1_dcache_data_intf_rsp),

        // Memory Init
        .disable_sram_auto_init_i               (disable_sram_auto_init),
        .init_mem_done_o                        (init_mem_done_o),

        // System Timer OCTS Interface
        .chiplet_is_primary_i                   (captured_straps_o[smc_ip_integration_pkg::PRIMARY_CHIPLET_STRAP_ID]),
        .timer_count_o                          (timer_count_o),

        // Trace Memory
        .trace_mem_req_o                        (trace_mem_req),
        .trace_mem_resp_i                       (trace_mem_resp),

        // Test Mode
        .test_en_i                              (test_en_i),
        .scan_rst_ni                            (scan_rst_ni),

        // Captured Straps
        .captured_straps_i                      (captured_straps_o),

        // indicators for DFT status
        .mem_repair_done_i                      (mem_repair_done_i),
        .mem_repair_success_i                   (mem_repair_success_i),
        .mem_repair_abort_i                     (mem_repair_abort_i),
        .mbist_done_i                           (mbist_done_i),
        .mbist_pass_i                           (mbist_pass_i),
        .mbist_abort_i                          (mbist_abort_i),

        // SEP Passthrough Ports
        .sep_sram_req_o                         (sep_sram_req),
        .sep_sram_rsp_i                         (sep_sram_rsp),
        .sep_boot_rom_req_o                     (sep_boot_rom_req),
        .sep_boot_rom_rsp_i                     (sep_boot_rom_rsp),
        .sep_cpu_tcm_req_o                      (sep_cpu_tcm_req),
        .sep_cpu_tcm_rsp_i                      (sep_cpu_tcm_rsp),

        .sep_efuse_bank_ctrl_req_o              (sep_efuse_bank_ctrl_req),
        .sep_efuse_bank_ctrl_resp_i             (sep_efuse_bank_ctrl_resp),
        .sep_efuse_shim_command_req_o           (sep_efuse_shim_command_req),
        .sep_efuse_shim_command_resp_i          (sep_efuse_shim_command_resp),

        .sep_crypto_pka_imem_sram_req_o         (sep_crypto_pka_imem_sram_req),
        .sep_crypto_pka_imem_sram_rsp_i         (sep_crypto_pka_imem_sram_rsp),
        .sep_crypto_pka_dmem_sram_req_o         (sep_crypto_pka_dmem_sram_req),
        .sep_crypto_pka_dmem_sram_rsp_i         (sep_crypto_pka_dmem_sram_rsp),

        .sep_km_rom_mem_req_o                   (sep_km_rom_mem_req),
        .sep_km_rom_mem_rsp_i                   (sep_km_rom_mem_rsp),
        .sep_km_sram_mem_req_o                  (sep_km_sram_mem_req),
        .sep_km_sram_mem_rsp_i                  (sep_km_sram_mem_rsp),

        .ot_spi_irq_o                           (ot_spi_irq),

        .spi_irq_i                              (spi_irq),

        .sep_axi_extension_req_o                (sep_axi_extension_req),
        .sep_axi_extension_resp_i               (sep_axi_extension_resp),

        .sep_reset_n_o                          (sep_reset_n),

        .sep_cpu_trace_o                        (sep_cpu_trace),

        .lcc_demote_state_1_o                   (lcc_demote_state_1),
        .lcc_demote_state_2_o                   (lcc_demote_state_2),
        .secure_tm_o                            (secure_tm_o),

        .sep_fuse_sense_done_o                  (sep_fuse_sense_done_o),

        .sep_extintsrc_req_i                    (sep_extintsrc_req_i),

        .clk_sep_wdt_i                          (clk_sep_wdt_i),
        .sep_straps_i                           (sep_straps),

        // I3C DAT/DCT memory interfaces
        .i3c_dat_mem_src_i                      (i3c_dat_mem_src),
        .i3c_dat_mem_sink_o                     (i3c_dat_mem_sink),
        .i3c_dct_mem_src_i                      (i3c_dct_mem_src),
        .i3c_dct_mem_sink_o                     (i3c_dct_mem_sink),

        // Debug bus
        .ext_debug_bus_i                        (ext_debug_bus),

        .gpio_interrupt_o                       (gpio_interrupt_o),
        .uart_interrupt_o                       (uart_interrupt_o)
    );

    ////////////////////////////////////////////
    // IP Integration Module (3rd Party IP)  //
    ////////////////////////////////////////////

    // OSS efuse OTP responders (controller in u_smu → responder, not ip_integration)
    efuse_otp_responder #(
        .NumFuseWordsParam    (smc_efuse_pkg::NumFuseWords),
        .NumFuseWordWidthParam (smc_efuse_pkg::NumFuseWordWidth),
        .NumFuseBitsWidthParam (smc_efuse_pkg::NumFuseBitsWidth),
        .IsSmcInstance        (1'b1),
        .bank_ctrl_req_t      (smc_pkg::smc_axil_32_32_req_t),
        .bank_ctrl_resp_t     (smc_pkg::smc_axil_32_32_resp_t),
        .fuse_command_req_t   (smc_efuse_pkg::fuse_command_req_t),
        .fuse_command_resp_t  (smc_efuse_pkg::fuse_command_resp_t),
        .efuse_data_t         (smc_efuse_pkg::efuse_data_t),
        .efuse_addr_bit_t     (smc_efuse_pkg::efuse_addr_bit_t),
        .efuse_word_counter_t (smc_efuse_pkg::efuse_word_counter_t)
    ) u_smc_efuse_responder (
        .clk_i               (smc_clk),
        .rst_ni              (rst_primary_smc_clk_n),
        .bank_ctrl_req_i     (smc_efuse_bank_ctrl_req),
        .bank_ctrl_resp_o    (smc_efuse_bank_ctrl_resp),
        .fuse_command_req_i  (smc_efuse_shim_command_req),
        .fuse_command_resp_o (smc_efuse_shim_command_resp)
    );

    smc_ip_integration #(
        .NUM_CGMS(NUM_CGMS),
        .NUM_AWMS(NUM_AWMS),
        .NUM_USED_CGM_CLOCKS(NUM_USED_CGM_CLOCKS),
        .NUM_USED_AWM_CLOCKS(NUM_USED_AWM_CLOCKS)
    ) u_smc_ip_integration (
        // Clocks
        .smc_clk(smc_clk),
        .periph_clk(periph_clk),
        .ref_clk_vdd_sys(ref_clk_vdd_sys),
        .ref_clk_vdd_sys_dfx_i(ref_clk_vdd_sys_dfx_i),

        // Resets
        .rst_primary_smc_clk_n(rst_primary_smc_clk_n),
        .rst_primary_ref_clk_n(rst_primary_ref_clk_n),
        .rst_cold_stable_ref_clk_ni(rst_cold_stable_ref_clk_n),
        .fuse_reset_n_delayed_o(fuse_reset_n_delayed_o),
        .rst_primary_periph_clk_ni(rst_primary_periph_clk_n),

        // Test/DFT
        .test_en_i(test_en_i),
        .scan_rst_ni(scan_rst_ni),

        // Clock Control (from DTP)
        .dtp_stop_clks_i(dtp_stop_clks),

        // AXI-Lite from SMC - PLL
        .axil_pll_req(axil_pll_req),
        .axil_pll_resp(axil_pll_resp),

        // AXI-Lite from SMC - PVT
        .axil_pvt_req(axil_pvt_req),
        .axil_pvt_resp(axil_pvt_resp),

        // AXI-Lite from SMC - GPIO
        .axil_req_gpio_ctrl(axil_req_gpio_ctrl),
        .axil_resp_gpio_ctrl(axil_resp_gpio_ctrl),

        // AXI-Lite from AXIL Extension to OSS I3C stub (Cadence IP removed)
        .axil_cdni3c_req(axil_extension_req),
        .axil_cdni3c_resp(axil_extension_resp),

        // Efuse interfaces from SMC
        .shadow_regs(smc_shadow_regs),

        // Memory interfaces from SMC
        .rom_intf_req(rom_intf_req),
        .rom_intf_rsp(rom_intf_rsp),
        .scratch_ram_intf_req(scratch_ram_intf_req),
        .scratch_ram_intf_rsp(scratch_ram_intf_rsp),
        .l1_icache_tag_intf_req(l1_icache_tag_intf_req),
        .l1_icache_tag_intf_rsp(l1_icache_tag_intf_rsp),
        .l1_icache_data_intf_req(l1_icache_data_intf_req),
        .l1_icache_data_intf_rsp(l1_icache_data_intf_rsp),
        .l1_dcache_tag_intf_req(l1_dcache_tag_intf_req),
        .l1_dcache_tag_intf_rsp(l1_dcache_tag_intf_rsp),
        .l1_dcache_data_intf_req(l1_dcache_data_intf_req),
        .l1_dcache_data_intf_rsp(l1_dcache_data_intf_rsp),

        // Trace memory interfaces from SMC
        .trace_mem_req(trace_mem_req),
        .trace_mem_resp(trace_mem_resp),

        // GPIO signals to/from SMC
        .lsio_interface_select(lsio_interface_select),
        .pad2core_o(pad2core),
        .core2pad_i(core2pad),
        .pad2core_en_i(pad2core_en),
        .core2pad_en_i(core2pad_en),

        // Cross trigger interface (from DTP to drive GPIOs)
        // TODO: Wire to DTP cross-trigger when xtrig pad routing is implemented
        .ct_req_out_dout_i('0),
        .ct_req_out_dout_en_i('0),
        .ct_req_out_din_o(),
        .ct_req_out_din_en_i('0),

        .ct_req_in_dout_i('0),
        .ct_req_in_dout_en_i('0),
        .ct_req_in_din_o(),
        .ct_req_in_din_en_i('0),

        .ct_ack_in_dout_i('0),
        .ct_ack_in_dout_en_i('0),
        .ct_ack_in_din_o(),
        .ct_ack_in_din_en_i('0),

        .ct_ack_out_dout_i('0),
        .ct_ack_out_dout_en_i('0),
        .ct_ack_out_din_o(),
        .ct_ack_out_din_en_i('0),

        // CAT THERM (routed to GPIO pad via 2nd HW function override)
        .cat_therm_i(cat_therm_i),

        // PVT interrupt
        .temp_interrupt(temp_interrupt),

        // Lifecycle state (for PVT filtering)
        .lc_state_i(lc_state),
        .lcc_demote_state_1_i(lcc_demote_muxed_1),
        .lcc_demote_state_2_i(lcc_demote_muxed_2),
        .lc_sigint_err_o(ip_integ_lc_sigint_err),
        .demote_sigint_err_o(ip_integ_demote_sigint_err),

        // External pads
        .GPIO_PAD(GPIO_PAD),
        .BP_UNBONDED_GPIO(BP_UNBONDED_GPIO),
        .BP_P_TCK(BP_P_TCK),
        .BP_P_TMS(BP_P_TMS),
        .BP_P_TRSTN(BP_P_TRSTN),
        .BP_P_TDI(BP_P_TDI),
        .BP_P_TDO(BP_P_TDO),
        .BP_S_TCK(BP_S_TCK),
        .BP_S_TMS(BP_S_TMS),
        .BP_S_TRSTN(BP_S_TRSTN),
        .BP_S_TDI(BP_S_TDI),
        .BP_S_TDO(BP_S_TDO),

        .BP_XTRIG_REQ_OUT(BP_XTRIG_REQ_OUT),
        .BP_XTRIG_REQ_IN(BP_XTRIG_REQ_IN),
        .BP_XTRIG_ACK_IN(BP_XTRIG_ACK_IN),
        .BP_XTRIG_ACK_OUT(BP_XTRIG_ACK_OUT),

        .BP_REFCLK(BP_REFCLK),
        .BP_RESETN(BP_RESETN),
        .BP_POWERGOOD(BP_POWERGOOD),

        // PLL outputs
        .pll_cgm_clk_o(pll_cgm_clk_o),
        .pll_awm_clk_o(pll_awm_clk_o),
        .pll_cgm_clk_dfx_i(pll_cgm_clk_dfx_i),
        .pll_awm_clk_dfx_i(pll_awm_clk_dfx_i),

        // PVT inputs
        .tile_event_i(tile_event_i),

        // Padring outputs
        .ref_clk_vdd_sys_o(ref_clk_vdd_sys),
        .rst_cold_no(rst_cold_n),
        .powergood_o(powergood),
        .cool_rst_n_from_pin_o(cool_rst_n_from_pin),

        // Outputs to wrapper (for top-level ports)
        .ref_clk_vdd_o(ref_clk_vdd_o),
        .captured_straps_o(captured_straps_o),

        // Signals to SMC
        .disable_sram_auto_init_o(disable_sram_auto_init),
        .sep_mailbox_interrupts_o(),

        // ATB Telemetry signals (to SMC)
        .clk_telemetry(clk_telemetry),
        .rst_telemetry_n(rst_telemetry_n),
        .telemetry_atdata(telemetry_atdata),
        .telemetry_atid(telemetry_atid),
        .telemetry_atvalid(telemetry_atvalid),
        .telemetry_afready(telemetry_afready),
        .telemetry_atready(telemetry_atready),
        .telemetry_afvalid(telemetry_afvalid),

        // Primary JTAG interface (from pads to PTAP)
        .jtag_ptap_tck_o(jtag_ptap_tck),
        .jtag_ptap_tms_o(jtag_ptap_tms),
        .jtag_ptap_trstn_o(jtag_ptap_trstn),
        .jtag_ptap_tdi_o(jtag_ptap_tdi),
        .jtag_ptap_tdo_i(jtag_ptap_tdo),

        // Secondary JTAG interface (from STAP to pads)
        .jtag_stap_tck_i(jtag_stap_io_host_tap_ctrl.tck),
        .jtag_stap_tms_i(jtag_stap_io_host_tap_ctrl.tms),
        .jtag_stap_trstn_i(jtag_stap_io_host_tap_ctrl.trst_n),
        .jtag_stap_tdi_o(jtag_stap_tdi),
        .jtag_stap_tdo_i(jtag_stap_tdo),

        // SEP SPI signals (to GPIO override)
        .sep_spi_enable_i(sep_spi_enable),
        .sep_spi_clk_i(sep_spi_clk),
        .sep_spi_clk_oe_n_i(sep_spi_clk_oe_n),
        .sep_spi_clk_ie_n_i(sep_spi_clk_ie_n),
        .sep_spi_cs_n_i(sep_spi_cs_n),
        .sep_spi_cs_oe_n_i(sep_spi_cs_oe_n),
        .sep_spi_cs_ie_n_i(sep_spi_cs_ie_n),
        .sep_spi_txd_i(sep_spi_txd),
        .sep_spi_dq_oe_n_i(sep_spi_dq_oe_n),
        .sep_spi_dq_ie_n_i(sep_spi_dq_ie_n),
        .sep_spi_rxd_o(sep_spi_rxd),
        .sep_spi_dqs_oe_n_i(sep_spi_dqs_oe_n),
        .sep_spi_dqs_ie_n_i(sep_spi_dqs_ie_n),
        .sep_spi_rxds_o(sep_spi_rxds),
        .sep_spi_mem_rebar_oepad_i(sep_spi_mem_rebar_oepad),
        .sep_spi_mem_rebar_opad_i(sep_spi_mem_rebar_opad),
        .sep_spi_mem_rebar_iepad_i(sep_spi_mem_rebar_iepad),
        .sep_spi_mem_rebar_ipad_o(sep_spi_mem_rebar_ipad),

        // I3C DAT/DCT memory interfaces
        .i3c_dat_mem_sink_i(i3c_dat_mem_sink),
        .i3c_dat_mem_src_o(i3c_dat_mem_src),
        .i3c_dct_mem_sink_i(i3c_dct_mem_sink),
        .i3c_dct_mem_src_o(i3c_dct_mem_src)
    );

    assign powergood_o = powergood;

    //--------------------------------------------------------------------------
    // SEP-dependent IP integration and lcc_demote_state wiring
    //--------------------------------------------------------------------------

    if (SEP) begin : gen_sep_ip

        // LCC demote states driven by SEP (through SMU)
        assign lcc_demote_state_1_o = lcc_demote_state_1;
        assign lcc_demote_state_2_o = lcc_demote_state_2;


        efuse_otp_responder #(
            .NumFuseWordsParam    (sep_efuse_pkg::NumFuseWords),
            .NumFuseWordWidthParam (sep_efuse_pkg::NumFuseWordWidth),
            .NumFuseBitsWidthParam (sep_efuse_pkg::NumFuseBitsWidth),
            .IsSmcInstance        (1'b0),
            .bank_ctrl_req_t      (sep_efuse_pkg::efuse_axil_req_t),
            .bank_ctrl_resp_t     (sep_efuse_pkg::efuse_axil_resp_t),
            .fuse_command_req_t   (sep_efuse_pkg::fuse_command_req_t),
            .fuse_command_resp_t  (sep_efuse_pkg::fuse_command_resp_t),
            .efuse_data_t         (sep_efuse_pkg::efuse_data_t),
            .efuse_addr_bit_t     (sep_efuse_pkg::efuse_addr_bit_t),
            .efuse_word_counter_t (sep_efuse_pkg::efuse_word_counter_t)
        ) u_sep_efuse_responder (
        .clk_i               (smc_clk),
        .rst_ni              (rst_primary_smc_clk_n),
            .bank_ctrl_req_i     (sep_efuse_bank_ctrl_req),
            .bank_ctrl_resp_o    (sep_efuse_bank_ctrl_resp),
            .fuse_command_req_i  (sep_efuse_shim_command_req),
            .fuse_command_resp_o (sep_efuse_shim_command_resp)
        );

        sep_ip_integration u_sep_ip_integration (
            .clk_i                          (smc_clk),
            .rst_ni                         (rst_primary_smc_clk_n),

            .sep_reset_n_i                  (sep_reset_n),

            .test_en_i                      (test_en_i),
            .scan_rst_ni                    (scan_rst_ni),

            .sep_sram_req                   (sep_sram_req),
            .sep_sram_rsp                   (sep_sram_rsp),
            .sep_boot_rom_req               (sep_boot_rom_req),
            .sep_boot_rom_rsp               (sep_boot_rom_rsp),
            .sep_cpu_tcm_req                (sep_cpu_tcm_req),
            .sep_cpu_tcm_rsp                (sep_cpu_tcm_rsp),

            .shadow_regs                    ('0),  // TODO: wire SEP efuse shadow regs if needed

            .sep_io_spi_req_i               (sep_io_spi_req),
            .sep_io_spi_rsp_o               (sep_io_spi_rsp),

            .spi_enable_o                   (sep_spi_enable),
            .spi_clk_o                      (sep_spi_clk),
            .spi_txd_o                      (sep_spi_txd),
            .spi_cs_n_o                     (sep_spi_cs_n),
            .spi_cs_oe_n_o                  (sep_spi_cs_oe_n),
            .spi_cs_ie_n_o                  (sep_spi_cs_ie_n),
            .spi_clk_ie_n_o                 (sep_spi_clk_ie_n),
            .spi_clk_oe_n_o                 (sep_spi_clk_oe_n),
            .spi_dqs_ie_n_o                 (sep_spi_dqs_ie_n),
            .spi_dqs_oe_n_o                 (sep_spi_dqs_oe_n),
            .spi_dq_ie_n_o                  (sep_spi_dq_ie_n),
            .spi_dq_oe_n_o                  (sep_spi_dq_oe_n),
            .spi_rxd_i                      (sep_spi_rxd),
            .spi_rxds_i                     (sep_spi_rxds),
            .spi_mem_rebar_oepad_o          (sep_spi_mem_rebar_oepad),
            .spi_mem_rebar_opad_o           (sep_spi_mem_rebar_opad),
            .spi_mem_rebar_iepad_o          (sep_spi_mem_rebar_iepad),
            .spi_mem_rebar_ipad_i           (sep_spi_mem_rebar_ipad),

            .spi_irq_o                      (cdns_spi_irq),

            .axi_extension_axi_req_i        (sep_axi_extension_req),
            .axi_extension_axi_resp_o       (sep_axi_extension_resp),

            .km_rom_mem_req_i               (sep_km_rom_mem_req),
            .km_rom_mem_rsp_o               (sep_km_rom_mem_rsp),
            .km_sram_mem_req_i              (sep_km_sram_mem_req),
            .km_sram_mem_rsp_o              (sep_km_sram_mem_rsp),

            .jtag_sep_reset_ctrl_i          (jtag_sep_reset_ctrl),
            .otbn_imem_sram_req_i           (sep_crypto_pka_imem_sram_req),
            .otbn_imem_sram_rsp_o           (sep_crypto_pka_imem_sram_rsp),
            .otbn_dmem_sram_req_i           (sep_crypto_pka_dmem_sram_req),
            .otbn_dmem_sram_rsp_o           (sep_crypto_pka_dmem_sram_rsp),
            .ext_trng_axil_req_i            (sep_ext_trng_axil_req),
            .ext_trng_axil_resp_o           (),
            .ext_trng_axis_req_o            (),
            .ext_trng_axis_rsp_i            (sep_ext_trng_axis_rsp),
            .ext_trng_irq_o                 (),
            .ext_trng_alarm_o               ()
        );

        assign spi_irq = sep_spi_enable ? cdns_spi_irq : ot_spi_irq;

    end else begin : gen_no_sep_ip

        // LCC demote states from external inputs (original standalone behavior)
        assign lcc_demote_state_1_o = lcc_demote_state_1_i;
        assign lcc_demote_state_2_o = lcc_demote_state_2_i;

        // SPI IRQ tie-off (no sep_ip_integration when SEP not present)
        assign spi_irq                    = 1'b0;

        // SEP SPI tie-offs (no SEP SPI when SEP not present)
        assign sep_spi_enable        = 1'b0;
        assign sep_spi_clk           = 1'b0;
        assign sep_spi_txd           = '0;
        assign sep_spi_cs_n          = 1'b1;
        assign sep_spi_cs_oe_n       = 1'b1;
        assign sep_spi_cs_ie_n       = 1'b1;
        assign sep_spi_clk_ie_n      = 1'b1;
        assign sep_spi_clk_oe_n      = 1'b1;
        assign sep_spi_dqs_ie_n      = 1'b1;
        assign sep_spi_dqs_oe_n      = 1'b1;
        assign sep_spi_dq_ie_n       = '1;
        assign sep_spi_dq_oe_n       = '1;
        assign sep_spi_mem_rebar_oepad = 1'b0;
        assign sep_spi_mem_rebar_opad  = 1'b0;
        assign sep_spi_mem_rebar_iepad = 1'b0;

        // SEP passthrough response tie-offs (smu.sv gen_no_sep ties requests to '0)
        assign sep_sram_rsp              = '0;
        assign sep_boot_rom_rsp          = '0;
        assign sep_cpu_tcm_rsp           = '0;
        assign sep_efuse_bank_ctrl_resp  = '0;
        assign sep_efuse_shim_command_resp = '0;
        assign sep_crypto_pka_imem_sram_rsp = '0;
        assign sep_crypto_pka_dmem_sram_rsp = '0;
        assign sep_km_rom_mem_rsp        = '0;
        assign sep_km_sram_mem_rsp       = '0;
        assign sep_io_spi_rsp            = '0;
        assign sep_axi_extension_resp    = '0;
    end

    // smc_ip_integration uses lcc_demote from external inputs when Sep=0,
    // from SEP (via SMU) when Sep=1
    assign lcc_demote_muxed_1 = SEP ? lcc_demote_state_1 : lcc_demote_state_1_i;
    assign lcc_demote_muxed_2 = SEP ? lcc_demote_state_2 : lcc_demote_state_2_i;

endmodule
