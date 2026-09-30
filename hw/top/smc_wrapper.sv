// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SMC Wrapper -- OSS reference top
//
// Instantiates the bare smc.sv core alongside smc_ip_integration.sv (the
// open-source macro/model set for its technology-specific IP) and wires the
// two together for standalone SMC reference simulation. See the integrator
// guide (doc/integrator/modules/ROOT/pages/index.adoc, "Module Variants and
// IP Integration") and hw/top/README.md.
//
// The Chipyard CPU ROM/scratch/L1$ macros sit inside smc_ip_integration.sv
// alongside the rest of the technology-specific IP, so smu_wrapper.sv picks
// them up from the same module.
//-----------------------------------------------------------------------------

module smc_wrapper (
  input  logic powergood_i,
  output logic powergood_stable_o,

  input  logic rst_cold_ni,
  output logic rst_cold_stable_ref_clk_no,

  output logic rst_primary_ref_clk_no,
  output logic rst_primary_smc_clk_no,
  output logic rst_wdt_smc_clk_no,
  output logic rst_primary_periph_clk_no,

  input  smc_pkg::smc_sys_in_56_64_6_12_axi_req_t  sys_axi_in_req_i,
  output smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t sys_axi_in_resp_o,

  input  smc_pkg::smc_jtag_56_64_2_12_axi_req_t  jtag_axi_in_req_i,
  output smc_pkg::smc_jtag_56_64_2_12_axi_resp_t jtag_axi_in_resp_o,

  input  smc_pkg::smc_axil_32_32_req_t  axil_smc_otp_jtag_req_i,
  output smc_pkg::smc_axil_32_32_resp_t axil_smc_otp_jtag_resp_o,

  input  smc_pkg::smc_sep_in_56_64_6_12_axi_req_t  sep_axi_in_req_i,
  output smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t sep_axi_in_resp_o,

  output smc_pkg::smc_sys_out_56_64_8_12_axi_req_t  output_axi_req_o,
  input  smc_pkg::smc_sys_out_56_64_8_12_axi_resp_t output_axi_resp_i,

  output smc_pkg::smc_axil_32_32_req_t  axil_dtp_csr_req_o,
  input  smc_pkg::smc_axil_32_32_resp_t axil_dtp_csr_resp_i,

  output smc_efuse_pkg::efuse_map_t shadow_regs_o,

  // GPIO control (lsio select passed through; per-pin pad I/O replaced by
  // gpio_pad_io below)
  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0] lsio_interface_select_o,

  // Physical GPIO pad bus -- one prim_pad_shim.sv per pin stands in for the
  // padring here.
  inout  wire [smc_pkg::NUM_GPIO_WRAPS-1:0] gpio_pad_io,

  input  logic rst_cool_n_from_pin_i,

  // SPI (raw pad-facing signals, passed straight through)
  input  logic       spi_enable_i,
  input  logic       spi_clk_i,
  input  logic [7:0] spi_txd_i,
  input  logic       spi_cs_n_i,
  input  logic       spi_cs_oe_n_i,
  input  logic       spi_cs_ie_n_i,
  input  logic       spi_clk_ie_n_i,
  input  logic       spi_clk_oe_n_i,
  input  logic       spi_dqs_ie_n_i,
  input  logic       spi_dqs_oe_n_i,
  input  logic [7:0] spi_dq_ie_n_i,
  input  logic [7:0] spi_dq_oe_n_i,
  output logic [7:0] spi_rxd_o,
  output logic       spi_rxds_o,
  input  logic       spi_mem_rebar_oepad_i,
  input  logic       spi_mem_rebar_opad_i,
  input  logic       spi_mem_rebar_iepad_i,
  output logic       spi_mem_rebar_ipad_o,

  // ATB Telemetry (passed straight through)
  input  logic clk_telemetry_i,
  input  logic rst_telemetry_ni,

  input  telemetry_receiver_pkg::telemetry_data_t [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atdata_i,
  input  telemetry_receiver_pkg::atb_id_t         [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atid_i,
  output logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atready_o,
  input  logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atvalid_i,
  output logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_afvalid_o,
  input  logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_afready_i,

  output logic smc_cluster_ded_o,

  output logic smc_wdt_first_timeout_o,
  output logic smc_wdt_second_timeout_o,

  output smc_pkg::smc_axi_addr_t smc_global_base_o,
  output logic [31:0]            smc_region_size_o,

  input  logic [smc_4core_cpu_pkg::NUM_EXT_INTERRUPTS-1:0] smc_ext_interrupts_i,
  input  logic [7:0]                                       sep_mailbox_interrupts_i,
  input  logic                                             sep_wdt_reset_n_i,

  output logic smc_fuse_sense_done_o,
  output logic smc_fuse_reset_n_delayed_o,

  output logic skip_mem_repair_o,
  input  logic ext_boot_seq_done_i,

  input  logic sep_security_disable_i,

  input  logic [2*smc_pkg::LC_STATE_WIDTH-1:0] lc_state_i,
  output logic                                 lc_sigint_err_o,

  input  logic [smc_config_pkg::CPU_CLUSTER_COUNT-1:0] smc_ndmreset_request_i,
  output logic [smc_config_pkg::CPU_CLUSTER_COUNT-1:0] smc_ndmreset_process_o,

  output logic [smc_pkg::NUM_MAILBOXES-1:0] smc_ext_mailbox_interrupts_o,

  input  logic        cfg_flr_pf_active_i,
  output logic [31:0] isolate_req_o,

  input  logic [31:0]                     ss_reset_complete_i,
  output logic [31:0]                     ss_config_o,
  output smc_reset_unit_pkg::reset_ctrl_t ss_reset_ctrl_o [31:0],

  output logic sync_irq_o,

  // CPU ROM/scratch/L1$ are absorbed by smc_ip_integration (not ports).

  input  logic smc_disable_sram_auto_init_i,
  output logic smc_init_mem_done_o,

  input  logic        chiplet_is_primary_i,
  output logic [63:0] timer_count_o,

  input  logic boot_stall_jtag_ovrd_i,
  input  logic boot_stall_jtag_val_i,
  output logic boot_stall_combined_o,

  input  smc_pkg::jtag_smc_reset_ctrl_t jtag_reset_ctrl_i,

  output logic [cla_pkg::CLA_NUMBER_OF_CUSTOM_ACTIONS-1:0] cla_ext_action_custom_o,

  output smc_pkg::xtrigger_t      xtrigger_ss_o,
  input  wire smc_pkg::xtrigger_t xtrigger_ss_i,

  input  wire logic tdr_dbg_ctrl_clock_stop_en_i,
  output logic      tdr_dbg_ctrl_clocks_stopped_by_cla_o,

  // Trace sink memories are absorbed by smc_ip_integration (not ports).

  input  logic [511:0] ext_debug_bus_i,

  input  logic test_en_i,
  input  logic scan_rst_ni,


  input  logic mem_repair_done_i,
  input  logic mem_repair_success_i,
  input  logic mem_repair_abort_i,
  input  logic mbist_done_i,
  input  logic mbist_pass_i,
  input  logic mbist_abort_i,

  input  logic        smc_cpu_jtag_TCK_i,
  input  logic        smc_cpu_jtag_TMS_i,
  input  logic        smc_cpu_jtag_TDI_i,
  output logic        smc_cpu_jtag_TDO_data_o,
  input  logic        smc_cpu_jtag_reset_i,
  input  logic [10:0] smc_cpu_jtag_mfr_id_i,
  input  logic [15:0] smc_cpu_jtag_part_number_i,
  input  logic [3:0]  smc_cpu_jtag_version_i,

  // Gated I3C peripheral clock. The table memories it drives are absorbed by
  // smc_ip_integration, so this leaves the wrapper for observation only.
  output logic                                                 gated_clk_periph_i3c_o,

  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0]  gpio_interrupt_o,
  output logic [smc_config_pkg::NUM_UART-1:0] uart_interrupt_o,

  // eFuse debug bus (internal shim state, surfaced for DV visibility)
  output logic [15:0] efuse_debug_bus_o
);

  /////////////////////////////////////////////////
  // Internal signals (smc <-> smc_ip_integration) //
  /////////////////////////////////////////////////

  logic clk_sys;
  logic clk_ref;
  logic clk_periph;

  smc_pkg::smc_axil_32_32_req_t  smc_external_req;
  smc_pkg::smc_axil_32_32_resp_t smc_external_resp;

  smc_pkg::smc_axil_32_32_req_t     efuse_bank_ctrl_req;
  smc_pkg::smc_axil_32_32_resp_t    efuse_bank_ctrl_resp;
  smc_efuse_pkg::fuse_command_req_t  efuse_shim_command_req;
  smc_efuse_pkg::fuse_command_resp_t efuse_shim_command_resp;

  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core;
  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad;
  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core_en;
  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad_en;

  // I3C table memory macros (smc <-> smc_ip_integration)
  i3c_pkg::dat_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_src;
  i3c_pkg::dat_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_sink;
  i3c_pkg::dct_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_src;
  i3c_pkg::dct_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_sink;
  i3c_pkg::rlt_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_rlt_mem_src;
  i3c_pkg::rlt_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_rlt_mem_sink;

  // Trace sink memories (smc <-> smc_ip_integration)
  trace_mem_pkg::SinkMemPktIn_s  [tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_req;
  trace_mem_pkg::SinkMemPktOut_s [tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_resp;

  // CPU mem macros (smc <-> smc_ip_integration)
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

  /////////////////////
  // SMC core        //
  /////////////////////

  smc u_smc (
    .clk_smc_i    (clk_sys),
    .clk_ref_i    (clk_ref),
    .clk_periph_i (clk_periph),
    .powergood_i,
    .powergood_stable_o,
    .rst_cold_ni,
    .rst_cold_stable_ref_clk_no,
    .rst_primary_ref_clk_no,
    .rst_primary_smc_clk_no,
    .rst_primary_periph_clk_no,
    .rst_wdt_smc_clk_no,
    .gated_clk_periph_i3c_o,
    .sys_axi_in_req_i,
    .sys_axi_in_resp_o,
    .jtag_axi_in_req_i,
    .jtag_axi_in_resp_o,
    .axil_smc_otp_jtag_req_i,
    .axil_smc_otp_jtag_resp_o,
    .sep_axi_in_req_i,
    .sep_axi_in_resp_o,
    .output_axi_req_o,
    .output_axi_resp_i,
    .axil_dtp_csr_req_o,
    .axil_dtp_csr_resp_i,
    .shadow_regs_o,
    .lsio_interface_select_o,
    .rst_cool_n_from_pin_i,
    .spi_enable_i,
    .spi_clk_i,
    .spi_txd_i,
    .spi_cs_n_i,
    .spi_cs_oe_n_i,
    .spi_cs_ie_n_i,
    .spi_clk_ie_n_i,
    .spi_clk_oe_n_i,
    .spi_dqs_ie_n_i,
    .spi_dqs_oe_n_i,
    .spi_dq_ie_n_i,
    .spi_dq_oe_n_i,
    .spi_rxd_o,
    .spi_rxds_o,
    .spi_mem_rebar_oepad_i,
    .spi_mem_rebar_opad_i,
    .spi_mem_rebar_iepad_i,
    .spi_mem_rebar_ipad_o,
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
    .smc_ext_interrupts_i,
    .sep_mailbox_interrupts_i,
    .sep_wdt_reset_n_i,
    .smc_fuse_sense_done_o,
    .smc_fuse_reset_n_delayed_o,
    .skip_mem_repair_o,
    .ext_boot_seq_done_i,
    .sep_security_disable_i,
    .lc_state_i,
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
    .boot_stall_jtag_ovrd_i,
    .boot_stall_jtag_val_i,
    .boot_stall_combined_o,
    .jtag_reset_ctrl_i,
    .cla_ext_action_custom_o,
    .xtrigger_ss_o,
    .xtrigger_ss_i,
    .tdr_dbg_ctrl_clock_stop_en_i,
    .tdr_dbg_ctrl_clocks_stopped_by_cla_o,
    .ext_debug_bus_i,
    .test_en_i,
    .scan_rst_ni,
    .mem_repair_done_i,
    .mem_repair_success_i,
    .mem_repair_abort_i,
    .mbist_done_i,
    .mbist_pass_i,
    .mbist_abort_i,
    .smc_cpu_jtag_TCK_i,
    .smc_cpu_jtag_TMS_i,
    .smc_cpu_jtag_TDI_i,
    .smc_cpu_jtag_TDO_data_o,
    .smc_cpu_jtag_reset_i,
    .smc_cpu_jtag_mfr_id_i,
    .smc_cpu_jtag_part_number_i,
    .smc_cpu_jtag_version_i,
    .gpio_interrupt_o,
    .uart_interrupt_o,
    // The public port keeps the 64-bit strap image; smc consumes the bonded GPIO straps.

    .smc_external_req_o  (smc_external_req),
    .smc_external_resp_i (smc_external_resp),

    .efuse_bank_ctrl_req_o    (efuse_bank_ctrl_req),
    .efuse_bank_ctrl_resp_i   (efuse_bank_ctrl_resp),
    .efuse_shim_command_req_o (efuse_shim_command_req),
    .efuse_shim_command_resp_i(efuse_shim_command_resp),

    .pad2core_i    (pad2core),
    .core2pad_o    (core2pad),
    .pad2core_en_o (pad2core_en),
    .core2pad_en_o (core2pad_en),

    .i3c_dat_mem_src_i  (i3c_dat_mem_src),
    .i3c_dat_mem_sink_o (i3c_dat_mem_sink),
    .i3c_dct_mem_src_i  (i3c_dct_mem_src),
    .i3c_dct_mem_sink_o (i3c_dct_mem_sink),
    .i3c_rlt_mem_src_i  (i3c_rlt_mem_src),
    .i3c_rlt_mem_sink_o (i3c_rlt_mem_sink),

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

    .efuse_bank_ctrl_req_i     (efuse_bank_ctrl_req),
    .efuse_bank_ctrl_resp_o    (efuse_bank_ctrl_resp),
    .efuse_shim_command_req_i  (efuse_shim_command_req),
    .efuse_shim_command_resp_o (efuse_shim_command_resp),

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

    .efuse_debug_bus_o (efuse_debug_bus_o)
  );

endmodule
