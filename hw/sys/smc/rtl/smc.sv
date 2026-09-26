// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Integrate the System Management Controller chiplet top.
//
// Instantiates reset, CPU, fabric, peripherals, and DFX under one SMC boundary. Bridges
// chiplet AXI ports, PLL clocks, powergood, and resets into smc_base and the peripheral
// domain.
//
// EFUSE_SHIM_SIZE is a literal carve-out at the base of the opaque smc_external window
// for the vendor eFuse shim CSR block; integrations that model the block override it.
// Memory-interface types are parameters rather than localparams so the mem-swap layer can
// specialize them.

module smc #(
  parameter int unsigned MAX_TRANS = 2,  // Maximum outstanding transactions.
  parameter int unsigned EFUSE_SHIM_SIZE = 'h44,  // Vendor eFuse shim CSR block carved
                                                  // off the base of the smc_external
                                                  // window.
                                                  // The open smc_external map is one
                                                  // opaque region, so this is a literal
                                                  // here and is overridden by an
                                                  // integration that models the block.

  parameter  type         rom_req_t             = chipyard_4core_mem_pkg::rom_req_t,  // Memory-interface
                                                                                      // types (cannot be
                                                                                      // localparams).
  parameter  type         rom_rsp_t             = chipyard_4core_mem_pkg::rom_rsp_t,  // Memory-interface
                                                                                      // types (cannot be
                                                                                      // localparams).
  parameter  type         scratch_ram_req_t     = chipyard_4core_mem_pkg::scratch_ram_req_t,  // Memory-interface
                                                                                              // types (cannot be
                                                                                              // localparams).
  parameter  type         scratch_ram_rsp_t     = chipyard_4core_mem_pkg::scratch_ram_rsp_t,  // Memory-interface
                                                                                              // types (cannot be
                                                                                              // localparams).
  parameter  type         l1_icache_tag_req_t   = chipyard_4core_mem_pkg::l1_icache_tag_req_t,  // Memory-interface
                                                                                                // types (cannot be
                                                                                                // localparams).
  parameter  type         l1_icache_tag_rsp_t   = chipyard_4core_mem_pkg::l1_icache_tag_rsp_t,  // Memory-interface
                                                                                                // types (cannot be
                                                                                                // localparams).
  parameter  type         l1_icache_data_req_t  = chipyard_4core_mem_pkg::l1_icache_data_req_t,  // Memory-interface
                                                                                                 // types (cannot be
                                                                                                 // localparams).
  parameter  type         l1_icache_data_rsp_t  = chipyard_4core_mem_pkg::l1_icache_data_rsp_t,  // Memory-interface
                                                                                                 // types (cannot be
                                                                                                 // localparams).
  parameter  type         l1_dcache_tag_req_t   = chipyard_4core_mem_pkg::l1_dcache_tag_req_t,  // Memory-interface
                                                                                                // types (cannot be
                                                                                                // localparams).
  parameter  type         l1_dcache_tag_rsp_t   = chipyard_4core_mem_pkg::l1_dcache_tag_rsp_t,  // Memory-interface
                                                                                                // types (cannot be
                                                                                                // localparams).
  parameter  type         l1_dcache_data_req_t  = chipyard_4core_mem_pkg::l1_dcache_data_req_t,  // Memory-interface
                                                                                                 // types (cannot be
                                                                                                 // localparams).
  parameter  type         l1_dcache_data_rsp_t  = chipyard_4core_mem_pkg::l1_dcache_data_rsp_t,  // Memory-interface
                                                                                                 // types (cannot be
                                                                                                 // localparams).

  localparam int unsigned NUM_CPU_CORES         = smc_4core_cpu_pkg::NUM_CPU_CORES,  // NUM CPU CORES.
  localparam int unsigned NUM_CPU_INTERRUPTS    = smc_4core_cpu_pkg::NUM_CPU_INTERRUPTS,  // NUM CPU Interrupts.
  localparam int unsigned NUM_EXT_INTERRUPTS    = smc_4core_cpu_pkg::NUM_EXT_INTERRUPTS,  // NUM EXT Interrupts.

  localparam int unsigned NUM_SRAM_BANKS        = chipyard_4core_mem_pkg::NUM_SRAM_BANKS,  // NUM SRAM BANKS.
  localparam int unsigned NUM_ICACHE_TAG_BANKS  = chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS,  // NUM Icache TAG
                                                                                                 // BANKS.
  localparam int unsigned NUM_ICACHE_DATA_BANKS = chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS,  // NUM Icache DATA
                                                                                                  // BANKS.
  localparam int unsigned NUM_DCACHE_TAG_BANKS  = chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS,  // NUM Dcache TAG
                                                                                                 // BANKS.
  localparam int unsigned NUM_DCACHE_DATA_BANKS = chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS  // NUM Dcache DATA
                                                                                                 // BANKS.
) (
  input logic clk_smc_i,                // Smc clock.
  input logic clk_ref_i,                // Ref clock.
  input logic clk_periph_i,             // Periph clock.

  input logic powergood_i,              // Powergood.

  output logic powergood_stable_o,      // Stable powergood signal.

  input logic rst_cold_ni,              // Cold Reset.

  output logic rst_cold_stable_ref_clk_no,  // Rst cold stable ref clk.

  output logic rst_primary_ref_clk_no,  // Synced Resets Out.
  output logic rst_primary_smc_clk_no,  // Synced Resets Out.
  output logic rst_primary_periph_clk_no,  // Synced Resets Out.
  output logic rst_wdt_smc_clk_no,      // Synced Resets Out.
  output logic gated_clk_periph_i3c_o,  // Synced Resets Out.

  input  smc_pkg::smc_sys_in_56_64_6_12_axi_req_t  sys_axi_in_req_i,  // Sys axi in request.
  output smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t sys_axi_in_resp_o,  // Sys axi in response.

  input  smc_pkg::smc_jtag_56_64_2_12_axi_req_t  jtag_axi_in_req_i,  // Jtag axi in request.
  output smc_pkg::smc_jtag_56_64_2_12_axi_resp_t jtag_axi_in_resp_o,  // Jtag axi in
                                                                      // response.

  input  smc_pkg::smc_axil_32_32_req_t  axil_smc_otp_jtag_req_i,  // Axil smc otp jtag
                                                                  // request.
  output smc_pkg::smc_axil_32_32_resp_t axil_smc_otp_jtag_resp_o,  // Axil smc otp jtag
                                                                   // response.

  input  smc_pkg::smc_sep_in_56_64_6_12_axi_req_t  sep_axi_in_req_i,  // Sep axi in request.
  output smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t sep_axi_in_resp_o,  // Sep axi in response.

  output smc_pkg::smc_sys_out_56_64_8_12_axi_req_t  output_axi_req_o,  // Output axi request.
  input  smc_pkg::smc_sys_out_56_64_8_12_axi_resp_t output_axi_resp_i,  // Output axi response.

  output smc_pkg::smc_axil_32_32_req_t  axil_dtp_csr_req_o,  // DTP CSR Interface.
  input  smc_pkg::smc_axil_32_32_resp_t axil_dtp_csr_resp_i,  // DTP CSR Interface.

  output smc_efuse_pkg::efuse_map_t shadow_regs_o,  // Shadow regs.

  output smc_pkg::smc_axil_32_32_req_t  smc_external_req_o,  // AXI-L interface for
                                                             // adopter peripheral
                                                             // request.
  input  smc_pkg::smc_axil_32_32_resp_t smc_external_resp_i,  // AXI-L interface for
                                                              // adopter peripheral
                                                              // response.

  output smc_pkg::smc_axil_32_32_req_t  efuse_bank_ctrl_req_o,  // eFuse Interface to SHIM
                                                                // AXI-Lite request.
  input  smc_pkg::smc_axil_32_32_resp_t efuse_bank_ctrl_resp_i,  // eFuse Interface to
                                                                 // SHIM AXI-Lite
                                                                 // response.

  output smc_efuse_pkg::fuse_command_req_t  efuse_shim_command_req_o,  // eFuse Command
                                                                       // Interface to SHIM.
  input  smc_efuse_pkg::fuse_command_resp_t efuse_shim_command_resp_i,  // eFuse Command
                                                                        // Interface to SHIM.

  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0] lsio_interface_select_o,  // GPIO Data Signals
                                                                       // (to external GPIO
                                                                       // macros via gpio_shim
                                                                       // instances).
  input  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core_i,  // GPIO Data Signals (to
                                                          // external GPIO macros via
                                                          // gpio_shim instances).
  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad_o,  // GPIO Data Signals (to
                                                          // external GPIO macros via
                                                          // gpio_shim instances).
  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core_en_o,  // GPIO Data Signals (to
                                                             // external GPIO macros via
                                                             // gpio_shim instances).
  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad_en_o,  // GPIO Data Signals (to
                                                             // external GPIO macros via
                                                             // gpio_shim instances).

  input logic rst_cool_n_from_pin_i,    // GPIO External Pins - cool reset from GPIO pin
                                        // 67.

  input  logic       spi_enable_i,      // Spi enable.
  input  logic       spi_clk_i,         // Spi clk.
  input  logic [7:0] spi_txd_i,         // Spi txd.
  input  logic       spi_cs_n_i,        // Spi cs n.
  input  logic       spi_cs_oe_n_i,     // Spi cs oe n.
  input  logic       spi_cs_ie_n_i,     // Spi cs ie n.
  input  logic       spi_clk_ie_n_i,    // Spi clk ie n.
  input  logic       spi_clk_oe_n_i,    // Spi clk oe n.
  input  logic       spi_dqs_ie_n_i,    // Spi dqs ie n.
  input  logic       spi_dqs_oe_n_i,    // Spi dqs oe n.
  input  logic [7:0] spi_dq_ie_n_i,     // Spi dq ie n.
  input  logic [7:0] spi_dq_oe_n_i,     // Spi dq oe n.
  output logic [7:0] spi_rxd_o,         // Spi rxd.
  output logic       spi_rxds_o,        // Spi rxds.
  input  logic       spi_mem_rebar_oepad_i,  // Spi mem rebar oepad.
  input  logic       spi_mem_rebar_opad_i,  // Spi mem rebar opad.
  input  logic       spi_mem_rebar_iepad_i,  // Spi mem rebar iepad.
  output logic       spi_mem_rebar_ipad_o,  // Spi mem rebar ipad.

  input logic clk_telemetry_i,          // ATB Telemetry.
  input logic rst_telemetry_ni,         // ATB Telemetry.

  input  telemetry_receiver_pkg::telemetry_data_t [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atdata_i,  // Telemetry atdata.
  input  telemetry_receiver_pkg::atb_id_t         [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atid_i,  // Telemetry atid.
  output logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atready_o,  // Telemetry atready.
  input  logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atvalid_i,  // Telemetry atvalid.
  output logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_afvalid_o,  // Telemetry afvalid.
  input  logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_afready_i,  // Telemetry afready.

  output logic smc_cluster_ded_o,       // Smc cluster ded.

  output logic smc_wdt_first_timeout_o,  // Smc wdt first timeout.
  output logic smc_wdt_second_timeout_o,  // Smc wdt second timeout.

  output smc_pkg::smc_axi_addr_t        smc_global_base_o,  // Region size.
  output logic [31:0]                   smc_region_size_o,  // Region size.

  input logic [NUM_EXT_INTERRUPTS-1:0] smc_ext_interrupts_i,  // External interrupts.
  input logic [7:0]                    sep_mailbox_interrupts_i,  // External interrupts.
  input logic                          sep_wdt_reset_n_i,  // External interrupts.

  output logic smc_fuse_sense_done_o,   // Smc fuse sense done.
  output logic smc_fuse_reset_n_delayed_o,  // Smc fuse reset n delayed.

  output logic skip_mem_repair_o,       // External boot / memory-repair signals.
  input  logic ext_boot_seq_done_i,     // External boot / memory-repair signals.

  input logic sep_security_disable_i,   // SEP security disable.

  input  logic [2*smc_pkg::LC_STATE_WIDTH-1:0] lc_state_i,  // Lifecycle state.
  output logic                                 lc_sigint_err_o,  // Lifecycle state.

  input  logic [smc_config_pkg::CPU_CLUSTER_COUNT - 1:0] smc_ndmreset_request_i,  // NDM reset.
  output logic [smc_config_pkg::CPU_CLUSTER_COUNT - 1:0] smc_ndmreset_process_o,  // NDM reset.

  output logic [smc_pkg::NUM_MAILBOXES-1:0] smc_ext_mailbox_interrupts_o,  // Mailbox interrupts.

  input  logic        cfg_flr_pf_active_i,  // Reset Unit signals.
  output logic [31:0] isolate_req_o,    // Reset Unit signals.

  input  logic [31:0]                            ss_reset_complete_i,  // Ss reset complete.
  output logic [31:0]                            ss_config_o,  // Ss config.
  output smc_reset_unit_pkg::reset_ctrl_t        ss_reset_ctrl_o [31:0],  // Ss reset ctrl.

  output logic sync_irq_o,              // Sync irq.

  output rom_req_t            smc_rom_intf_req_o,  // CPU Memory Signals.
  input  rom_rsp_t            smc_rom_intf_rsp_i,  // CPU Memory Signals.
  output scratch_ram_req_t    smc_scratch_ram_intf_req_o [NUM_SRAM_BANKS-1:0],  // CPU Memory Signals.
  input  scratch_ram_rsp_t    smc_scratch_ram_intf_rsp_i [NUM_SRAM_BANKS-1:0],  // CPU Memory Signals.
  output l1_icache_tag_req_t  smc_l1_icache_tag_intf_req_o [NUM_ICACHE_TAG_BANKS-1:0],  // CPU Memory Signals.
  input  l1_icache_tag_rsp_t  smc_l1_icache_tag_intf_rsp_i [NUM_ICACHE_TAG_BANKS-1:0],  // CPU Memory Signals.
  output l1_icache_data_req_t smc_l1_icache_data_intf_req_o [NUM_ICACHE_DATA_BANKS-1:0],  // CPU Memory Signals.
  input  l1_icache_data_rsp_t smc_l1_icache_data_intf_rsp_i [NUM_ICACHE_DATA_BANKS-1:0],  // CPU Memory Signals.
  output l1_dcache_tag_req_t  smc_l1_dcache_tag_intf_req_o [NUM_DCACHE_TAG_BANKS-1:0],  // CPU Memory Signals.
  input  l1_dcache_tag_rsp_t  smc_l1_dcache_tag_intf_rsp_i [NUM_DCACHE_TAG_BANKS-1:0],  // CPU Memory Signals.
  output l1_dcache_data_req_t smc_l1_dcache_data_intf_req_o [NUM_DCACHE_DATA_BANKS-1:0],  // CPU Memory Signals.
  input  l1_dcache_data_rsp_t smc_l1_dcache_data_intf_rsp_i [NUM_DCACHE_DATA_BANKS-1:0],  // CPU Memory Signals.

  input  logic smc_disable_sram_auto_init_i,  // Smc disable sram auto init.
  output logic smc_init_mem_done_o,     // Smc init mem done.

  input  logic        chiplet_is_primary_i,  // System Timer OCTS Interface.
  output logic [63:0] timer_count_o,    // System Timer OCTS Interface.

  input  logic boot_stall_jtag_ovrd_i,  // Boot Stall.
  input  logic boot_stall_jtag_val_i,   // Boot Stall.
  output logic boot_stall_combined_o,   // Boot Stall.

  input smc_pkg::jtag_smc_reset_ctrl_t jtag_reset_ctrl_i,  // JTAG reset control signals.

  output logic [cla_pkg::CLA_NUMBER_OF_CUSTOM_ACTIONS-1:0] cla_ext_action_custom_o,  // DFD signals.

  output smc_pkg::xtrigger_t      xtrigger_ss_o,  // Xtrigger ss.
  input  wire smc_pkg::xtrigger_t xtrigger_ss_i,  // Xtrigger ss.

  input  wire logic tdr_dbg_ctrl_clock_stop_en_i,  // TDR debug control signals.
  output logic      tdr_dbg_ctrl_clocks_stopped_by_cla_o,  // TDR debug control signals.

  output trace_mem_pkg::SinkMemPktIn_s [tn_pkg::TRC_RAM_INSTANCES-1:0]  trace_mem_req_o,  // Trace mem request.
  input  trace_mem_pkg::SinkMemPktOut_s [tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_resp_i,  // Trace mem response.

  input logic [511:0] ext_debug_bus_i,  // Note: Ensure signals are 16-bit aligned within
                                        // this bus.

  input logic test_en_i,                // Test en.
  input logic scan_rst_ni,              // Scan rst.

  input logic mem_repair_done_i,        // indicators for DFT status.
  input logic mem_repair_success_i,     // indicators for DFT status.
  input logic mem_repair_abort_i,       // indicators for DFT status.
  input logic mbist_done_i,             // indicators for DFT status.
  input logic mbist_pass_i,             // indicators for DFT status.
  input logic mbist_abort_i,            // indicators for DFT status.

  input  logic        smc_cpu_jtag_TCK_i,  // CPU Debug interfaces (JTAG).
  input  logic        smc_cpu_jtag_TMS_i,  // CPU Debug interfaces (JTAG).
  input  logic        smc_cpu_jtag_TDI_i,  // CPU Debug interfaces (JTAG).
  output logic        smc_cpu_jtag_TDO_data_o,  // CPU Debug interfaces (JTAG).
  input  logic        smc_cpu_jtag_reset_i,  // CPU Debug interfaces (JTAG).
  input  logic [10:0] smc_cpu_jtag_mfr_id_i,  // CPU Debug interfaces (JTAG).
  input  logic [15:0] smc_cpu_jtag_part_number_i,  // CPU Debug interfaces (JTAG).
  input  logic [3:0]  smc_cpu_jtag_version_i,  // CPU Debug interfaces (JTAG).

  input  i3c_pkg::dat_mem_src_t [smc_config_pkg::NUM_I3C-1:0]  i3c_dat_mem_src_i,  // I3C DAT/DCT memory
                                                                                   // interfaces.
  output i3c_pkg::dat_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_sink_o,  // I3C DAT/DCT memory
                                                                                    // interfaces.
  input  i3c_pkg::dct_mem_src_t [smc_config_pkg::NUM_I3C-1:0]  i3c_dct_mem_src_i,  // I3C DAT/DCT memory
                                                                                   // interfaces.
  output i3c_pkg::dct_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_sink_o,  // I3C DAT/DCT memory
                                                                                    // interfaces.
  input  i3c_pkg::rlt_mem_src_t [smc_config_pkg::NUM_I3C-1:0]  i3c_rlt_mem_src_i,  // I3C DAT/DCT memory
                                                                                   // interfaces.
  output i3c_pkg::rlt_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_rlt_mem_sink_o,  // I3C DAT/DCT memory
                                                                                    // interfaces.

  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0]  gpio_interrupt_o,  // Gpio interrupt.
  output logic [smc_config_pkg::NUM_UART-1:0] uart_interrupt_o  // Uart interrupt.
);

  //////////////
  // SMC Base //
  //////////////

  // Fuse Reset
  logic fuse_reset_n;

  // Clock Gating
  logic cg_ctrl_i3c_cg_en;
  logic cg_ctrl_avs_cg_en;
  logic cg_ctrl_i2c_cg_en;
  logic cg_ctrl_uart_cg_en;
  logic cg_ctrl_tel_cg_en;

  // Interrupt signals
  logic [31:0] peripheral_interrupts;
  logic        axi_hang_irq;

  // Debug
  logic [16:0] avsbus_cur_state_debug;
  logic [8:0]  system_timer_octs_credits_debug;
  logic        system_timer_octs_credits_left_debug;

  logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0][3:0] telemetry_debug;
  logic [smc_config_pkg::NUM_I2C-1:0][3:0]                 i2c_debug;
  logic [9:0]                                              efuse_debug;

  // ROM Flip Endianness bit from shadow registers
  logic rom_flip_endianness;

  // Integrity error from efuse controller
  logic efuse_lc_sigint_err;
  assign lc_sigint_err_o = efuse_lc_sigint_err;

  // Reset signals
  logic rst_warm_smc_clk_n;

  smc_pkg::smc_axil_56_64_req_t  axil_log_engine_req;
  smc_pkg::smc_axil_56_64_resp_t axil_log_engine_resp;

  smc_pkg::smc_axil_32_32_req_t  axil_peripherals_req;
  smc_pkg::smc_axil_32_32_resp_t axil_peripherals_resp;

  // CPU wrapper bridge signals crossing between smc_base and smc_cpu_wrapper
  logic [NUM_CPU_INTERRUPTS-1:0]              cpu_interrupts;
  smc_pkg::smc_local_32_64_8_12_axi_req_t     cpu_axi_front_port_req;
  smc_pkg::smc_local_32_64_8_12_axi_resp_t    cpu_axi_front_port_resp;
  smc_pkg::smc_cpu_mmio_axi_req_t             cpu_axi_mmio_port_req;
  smc_pkg::smc_cpu_mmio_axi_resp_t            cpu_axi_mmio_port_resp;
  logic [NUM_CPU_CORES-1:0][57:0]             cpu_wb_reg_pc;
  logic [NUM_CPU_CORES-1:0]                   cpu_wdt_timeout_cluster;

  smc_base #(
    .NO_ADDR_REMAP(smc_config_pkg::NO_ADDR_REMAP)  // Enable address remap in the output fabric
  ) u_smc_base (
    // Clocks from PLLs
    .clk_smc_i                              (clk_smc_i),
    .clk_ref_i                              (clk_ref_i),

    // Resets
    .rst_primary_smc_clk_ni                 (rst_primary_smc_clk_no),

    // Test mode
    .test_en_i                              (test_en_i),
    .scan_rst_ni                            (scan_rst_ni),

    // AXI Input
    .sys_axi_in_req_i                       (sys_axi_in_req_i),
    .sys_axi_in_resp_o                      (sys_axi_in_resp_o),
    .jtag_axi_in_req_i                      (jtag_axi_in_req_i),
    .jtag_axi_in_resp_o                     (jtag_axi_in_resp_o),
    .sep_axi_in_req_i                       (sep_axi_in_req_i),
    .sep_axi_in_resp_o                      (sep_axi_in_resp_o),

    // Log Engine AXI-Lite
    .axil_log_engine_req_i                  (axil_log_engine_req),
    .axil_log_engine_resp_o                 (axil_log_engine_resp),

    // AXI Output
    .output_axi_req_o                       (output_axi_req_o),
    .output_axi_resp_i                      (output_axi_resp_i),

    // Consolidated to 1 AXI-Lite interface for all peripherals
    .axil_peripherals_req_o                 (axil_peripherals_req),
    .axil_peripherals_resp_i                (axil_peripherals_resp),

    // WDT
    .wdt_first_timeout_o                    (smc_wdt_first_timeout_o),

    // External interrupts
    .ext_interrupts_i                       (smc_ext_interrupts_i),
    .peripheral_interrupts_i                (peripheral_interrupts),

    // Mailbox interrupts
    .ext_mailbox_interrupts_o               (smc_ext_mailbox_interrupts_o),

    // CPU wrapper bridge ports (outputs to smc_cpu_wrapper)
    .cpu_axi_front_port_req_o               (cpu_axi_front_port_req),
    .cpu_axi_front_port_resp_i              (cpu_axi_front_port_resp),
    .cpu_interrupts_o                       (cpu_interrupts),

    // CPU wrapper bridge ports (inputs from smc_cpu_wrapper)
    .cpu_axi_mmio_port_req_i                (cpu_axi_mmio_port_req),
    .cpu_axi_mmio_port_resp_o               (cpu_axi_mmio_port_resp),
    .cpu_wb_reg_pc_i                        (cpu_wb_reg_pc),
    .cpu_wdt_timeout_cluster_i              (cpu_wdt_timeout_cluster),
    .cpu_cluster_ded_i                      (smc_cluster_ded_o),
    .wdt_second_timeout_i                   (smc_wdt_second_timeout_o),

    // SMC address window from smc_base_config (in u_smc_base)
    .smc_global_base_o                      (smc_global_base_o),
    .smc_region_size_o                      (smc_region_size_o),

    // Peripheral clock-gate enables from smc_base_config (in u_smc_base)
    .cg_ctrl_i3c_cg_en_o                    (cg_ctrl_i3c_cg_en),
    .cg_ctrl_avs_cg_en_o                    (cg_ctrl_avs_cg_en),
    .cg_ctrl_i2c_cg_en_o                    (cg_ctrl_i2c_cg_en),
    .cg_ctrl_uart_cg_en_o                   (cg_ctrl_uart_cg_en),
    .cg_ctrl_tel_cg_en_o                    (cg_ctrl_tel_cg_en),

    // DFD Signals
    .cla_ext_action_custom_o                (cla_ext_action_custom_o),

    .xtrigger_ss_o                          (xtrigger_ss_o),
    .xtrigger_ss_i                          (xtrigger_ss_i),

    .tdr_dbg_ctrl_clock_stop_en_i           (tdr_dbg_ctrl_clock_stop_en_i),
    .tdr_dbg_ctrl_clocks_stopped_by_cla_o   (tdr_dbg_ctrl_clocks_stopped_by_cla_o),

    .trace_mem_req_o                        (trace_mem_req_o),
    .trace_mem_resp_i                       (trace_mem_resp_i),

    .ext_debug_bus_i                        (ext_debug_bus_i),

    // Debug
    .avsbus_cur_state_debug_i               (avsbus_cur_state_debug),
    .system_timer_octs_credits_debug_i      (system_timer_octs_credits_debug),
    .system_timer_octs_credits_left_debug_i (system_timer_octs_credits_left_debug),
    .telemetry_debug_i                      (telemetry_debug),
    .i2c_debug_i                            (i2c_debug),
    .efuse_debug_i                          (efuse_debug),

    // indicators for DFT status
    .mem_repair_done_i                      (mem_repair_done_i),
    .mem_repair_success_i                   (mem_repair_success_i),
    .mem_repair_abort_i                     (mem_repair_abort_i),
    .mbist_done_i                           (mbist_done_i),
    .mbist_pass_i                           (mbist_pass_i),
    .mbist_abort_i                          (mbist_abort_i),

    // AXI hang detector fault output.
    // The OR'd fault is routed into smc_peripherals peripheral_interrupts[30] so PLIC can see it.
    .axi_hang_irq_o                         (axi_hang_irq)
  );


  ///////////////////
  // SMC CPU       //
  ///////////////////

  smc_cpu_wrapper #(
    .NO_ADDR_REMAP                      (smc_config_pkg::NO_ADDR_REMAP),
    .rom_req_t                          (rom_req_t),
    .rom_rsp_t                          (rom_rsp_t),
    .scratch_ram_req_t                  (scratch_ram_req_t),
    .scratch_ram_rsp_t                  (scratch_ram_rsp_t),
    .l1_icache_tag_req_t                (l1_icache_tag_req_t),
    .l1_icache_tag_rsp_t                (l1_icache_tag_rsp_t),
    .l1_icache_data_req_t               (l1_icache_data_req_t),
    .l1_icache_data_rsp_t               (l1_icache_data_rsp_t),
    .l1_dcache_tag_req_t                (l1_dcache_tag_req_t),
    .l1_dcache_tag_rsp_t                (l1_dcache_tag_rsp_t),
    .l1_dcache_data_req_t               (l1_dcache_data_req_t),
    .l1_dcache_data_rsp_t               (l1_dcache_data_rsp_t)
  ) u_smc_cpu_wrapper (
    .clk_i                              (clk_smc_i),
    .clk_ref_i                          (clk_ref_i),
    .rst_isolate_ni                     (rst_primary_smc_clk_no),
    .rst_primary_smc_clk_ni             (rst_primary_smc_clk_no),
    .rst_warm_smc_clk_ni                (rst_warm_smc_clk_n),
    .fuse_reset_ni                      (fuse_reset_n),
    .scan_rst_ni                        (scan_rst_ni),

    .chiplet_is_primary_i               (chiplet_is_primary_i),

    // From smc_base
    .interrupts_i                       (cpu_interrupts),
    .axi_front_port_req_i               (cpu_axi_front_port_req),
    .axi_front_port_resp_o              (cpu_axi_front_port_resp),

    // To smc_base
    .axi_mmio_port_req_o                (cpu_axi_mmio_port_req),
    .axi_mmio_port_resp_i               (cpu_axi_mmio_port_resp),
    .wb_reg_pc_o                        (cpu_wb_reg_pc),
    .wdt_timeout_cluster_o              (cpu_wdt_timeout_cluster),
    .wdt_second_timeout_o               (smc_wdt_second_timeout_o),

    // DED output (goes to smc top-level port and smc_base debug bus)
    .cluster_ded_o                      (smc_cluster_ded_o),

    // CPU Memory Signals
    .rom_intf_req_o                     (smc_rom_intf_req_o),
    .rom_intf_rsp_i                     (smc_rom_intf_rsp_i),
    .scratch_ram_intf_req_o             (smc_scratch_ram_intf_req_o),
    .scratch_ram_intf_rsp_i             (smc_scratch_ram_intf_rsp_i),
    .l1_icache_tag_intf_req_o           (smc_l1_icache_tag_intf_req_o),
    .l1_icache_tag_intf_rsp_i          (smc_l1_icache_tag_intf_rsp_i),
    .l1_icache_data_intf_req_o          (smc_l1_icache_data_intf_req_o),
    .l1_icache_data_intf_rsp_i         (smc_l1_icache_data_intf_rsp_i),
    .l1_dcache_tag_intf_req_o           (smc_l1_dcache_tag_intf_req_o),
    .l1_dcache_tag_intf_rsp_i          (smc_l1_dcache_tag_intf_rsp_i),
    .l1_dcache_data_intf_req_o          (smc_l1_dcache_data_intf_req_o),
    .l1_dcache_data_intf_rsp_i         (smc_l1_dcache_data_intf_rsp_i),
    .disable_sram_auto_init_i           (smc_disable_sram_auto_init_i),
    .init_mem_done_o                    (smc_init_mem_done_o),

    // ROM Flip Endianness
    .rom_flip_endianness_i              (rom_flip_endianness),

    // Test mode
    .test_en_i                          (test_en_i),

    // CPU Debug interfaces (JTAG)
    .smc_cpu_jtag_TCK_i                 (smc_cpu_jtag_TCK_i),
    .smc_cpu_jtag_TMS_i                 (smc_cpu_jtag_TMS_i),
    .smc_cpu_jtag_TDI_i                 (smc_cpu_jtag_TDI_i),
    .smc_cpu_jtag_TDO_data_o            (smc_cpu_jtag_TDO_data_o),
    .smc_cpu_jtag_reset_i               (smc_cpu_jtag_reset_i),
    .smc_cpu_jtag_mfr_id_i              (smc_cpu_jtag_mfr_id_i),
    .smc_cpu_jtag_part_number_i         (smc_cpu_jtag_part_number_i),
    .smc_cpu_jtag_version_i             (smc_cpu_jtag_version_i)
  );


  //////////////////////
  // SMC Peripherals  //
  //////////////////////

  smc_peripherals #(
    .MAX_TRANS       (MAX_TRANS),
    .EFUSE_SHIM_SIZE (EFUSE_SHIM_SIZE)
  ) u_smc_peripherals (
    .clk_ref_i                             (clk_ref_i),
    .clk_smc_i                             (clk_smc_i),
    .clk_periph_i                          (clk_periph_i),
    .test_en_i                             (test_en_i),
    .scan_rst_ni                           (scan_rst_ni),

    // Telemetry Unit clock and reset
    .clk_telemetry_i                       (clk_telemetry_i),
    .rst_telemetry_ni                      (rst_telemetry_ni),

    // Clock Gating
    .i3c_cg_en_i                           (cg_ctrl_i3c_cg_en),
    .avs_cg_en_i                           (cg_ctrl_avs_cg_en),
    .i2c_cg_en_i                           (cg_ctrl_i2c_cg_en),
    .uart_cg_en_i                          (cg_ctrl_uart_cg_en),
    .tel_cg_en_i                           (cg_ctrl_tel_cg_en),

    .axil_peripherals_req_i                (axil_peripherals_req),
    .axil_peripherals_resp_o               (axil_peripherals_resp),
    .axil_log_engine_req_o                 (axil_log_engine_req),
    .axil_log_engine_resp_i                (axil_log_engine_resp),
    .axil_dtp_csr_req_o                    (axil_dtp_csr_req_o),
    .axil_dtp_csr_resp_i                   (axil_dtp_csr_resp_i),
    .smc_external_req_o                    (smc_external_req_o),
    .smc_external_resp_i                   (smc_external_resp_i),

    .axil_smc_otp_jtag_req_i               (axil_smc_otp_jtag_req_i),
    .axil_smc_otp_jtag_resp_o              (axil_smc_otp_jtag_resp_o),


    // GPIO Hardware Interface
    .lsio_interface_select_o               (lsio_interface_select_o),
    .pad2core_i                            (pad2core_i),
    .core2pad_o                            (core2pad_o),
    .pad2core_en_o                         (pad2core_en_o),
    .core2pad_en_o                         (core2pad_en_o),

    // SPI
    .spi_enable_i                          (spi_enable_i),
    .spi_clk_i                             (spi_clk_i),
    .spi_txd_i                             (spi_txd_i),
    .spi_cs_n_i                            (spi_cs_n_i),
    .spi_cs_oe_n_i                         (spi_cs_oe_n_i),
    .spi_cs_ie_n_i                         (spi_cs_ie_n_i),
    .spi_clk_ie_n_i                        (spi_clk_ie_n_i),
    .spi_clk_oe_n_i                        (spi_clk_oe_n_i),
    .spi_dqs_ie_n_i                        (spi_dqs_ie_n_i),
    .spi_dqs_oe_n_i                        (spi_dqs_oe_n_i),
    .spi_dq_ie_n_i                         (spi_dq_ie_n_i),
    .spi_dq_oe_n_i                         (spi_dq_oe_n_i),
    .spi_rxd_o                             (spi_rxd_o),
    .spi_rxds_o                            (spi_rxds_o),
    .spi_mem_rebar_oepad_i                 (spi_mem_rebar_oepad_i),
    .spi_mem_rebar_opad_i                  (spi_mem_rebar_opad_i),
    .spi_mem_rebar_iepad_i                 (spi_mem_rebar_iepad_i),
    .spi_mem_rebar_ipad_o                  (spi_mem_rebar_ipad_o),

    // ATB Telemetry
    .telemetry_atdata_i                    (telemetry_atdata_i),
    .telemetry_atid_i                      (telemetry_atid_i),
    .telemetry_atready_o                   (telemetry_atready_o),
    .telemetry_atvalid_i                   (telemetry_atvalid_i),
    .telemetry_afvalid_o                   (telemetry_afvalid_o),
    .telemetry_afready_i                   (telemetry_afready_i),

    // Efuse Interface from xBar
    .lc_state_i                            (lc_state_i),
    .lc_sigint_err_o                       (efuse_lc_sigint_err),

    // System Timer OCTS
    .chiplet_is_primary_i                  (chiplet_is_primary_i),
    .timer_count_o                         (timer_count_o),
    .system_timer_octs_credits_debug_o     (system_timer_octs_credits_debug),
    .system_timer_octs_credits_left_debug_o(system_timer_octs_credits_left_debug),

    // Efuse Interface to SHIM
    .fuse_bank_ctrl_req_o                  (efuse_bank_ctrl_req_o),
    .fuse_bank_ctrl_resp_i                 (efuse_bank_ctrl_resp_i),

    // Boot Stall
    .boot_stall_jtag_ovrd_i                (boot_stall_jtag_ovrd_i),
    .boot_stall_jtag_val_i                 (boot_stall_jtag_val_i),
    .boot_stall_processed_o                (boot_stall_combined_o),

    // Efuse Command Interface
    .efuse_shim_command_req_o              (efuse_shim_command_req_o),
    .efuse_shim_command_resp_i             (efuse_shim_command_resp_i),

    // Efuse dft signal
    .ext_boot_seq_done_i                   (ext_boot_seq_done_i),

    // SEP security disable
    .sep_security_disable_i                (sep_security_disable_i),

    .fuse_reset_n_o                        (fuse_reset_n),
    .fuse_reset_n_delayed_o                (smc_fuse_reset_n_delayed_o),
    .fuse_sense_done_o                     (smc_fuse_sense_done_o),  // Use this for signaling mbist & memory repair logic

    // Efuse Shadow Regs
    .shadow_regs_o                         (shadow_regs_o),

    .ndmreset_request_i                    (smc_ndmreset_request_i),
    .ndmreset_process_o                    (smc_ndmreset_process_o),

    // SMC Reset Unit Signals
    .powergood_i                           (powergood_i),
    .rst_cold_ni                           (rst_cold_ni),
    .rst_cool_ni                           (rst_cool_n_from_pin_i),
    .rst_cold_stable_ref_clk_no            (rst_cold_stable_ref_clk_no),
    .powergood_stable_o                    (powergood_stable_o),
    .rst_ext_wdt_ni                        (sep_wdt_reset_n_i),
    .smc_wdt_first_timeout_i               (smc_wdt_first_timeout_o),
    .smc_wdt_second_timeout_i              (smc_wdt_second_timeout_o),
    .cfg_flr_pf_active_i                   (cfg_flr_pf_active_i),
    .isolate_req_o                         (isolate_req_o),
    .skip_mem_repair_o                     (skip_mem_repair_o),
    .ss_reset_complete_i                   (ss_reset_complete_i),
    .ss_config_o                           (ss_config_o),
    .ss_reset_ctrl_o                       (ss_reset_ctrl_o),
    .rst_primary_ref_clk_no                (rst_primary_ref_clk_no),
    .rst_primary_smc_clk_no                (rst_primary_smc_clk_no),
    .rst_warm_smc_clk_no                   (rst_warm_smc_clk_n),
    .rst_wdt_smc_clk_no                    (rst_wdt_smc_clk_no),
    .rst_primary_periph_clk_no             (rst_primary_periph_clk_no),
    .sync_irq_o                            (sync_irq_o),

    .jtag_reset_ctrl_i                     (jtag_reset_ctrl_i),


    // interrupts
    .sep_mailbox_interrupts_i              (sep_mailbox_interrupts_i),
    .axi_hang_irq_i                        (axi_hang_irq),
    .peripheral_interrupts_o               (peripheral_interrupts),

    .gpio_interrupt_o                      (gpio_interrupt_o),
    .uart_interrupt_o                      (uart_interrupt_o),

    // I3C DAT/DCT memory interfaces
    .i3c_dat_mem_src_i                     (i3c_dat_mem_src_i),
    .i3c_dat_mem_sink_o                    (i3c_dat_mem_sink_o),
    .i3c_dct_mem_src_i                     (i3c_dct_mem_src_i),
    .i3c_dct_mem_sink_o                    (i3c_dct_mem_sink_o),
    .i3c_rlt_mem_src_i                     (i3c_rlt_mem_src_i),
    .i3c_rlt_mem_sink_o                    (i3c_rlt_mem_sink_o),
    .gated_clk_periph_i3c_o                (gated_clk_periph_i3c_o),

    // AVSBus Controller debug
    .avsbus_cur_state_debug_o              (avsbus_cur_state_debug),

    // Telemetry debug
    .telemetry_debug_o                     (telemetry_debug),

    // I2C debug
    .i2c_debug_o                           (i2c_debug),

    // Efuse debug
    .efuse_debug_o                         (efuse_debug)
  );
  assign rom_flip_endianness = shadow_regs_o.fields.smc_config.rom_flip_endianness;

endmodule
