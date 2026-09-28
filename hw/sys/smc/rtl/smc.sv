// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Integrate the System Management Controller chiplet top.
//
// Instantiates reset, CPU, fabric, peripherals, and DFX under one SMC boundary. Bridges
// chiplet AXI ports, PLL clocks, powergood, and resets into smc_base and the peripheral
// domain.
// smc_base holds the fabric, internal registers, DFD and data accelerators;
// smc_cpu_wrapper holds the CPU cluster; smc_peripherals holds the peripherals, eFuse
// wrapper and reset unit. The ROM endianness bit comes from the eFuse shadow registers.
//
// EFUSE_SHIM_SIZE is a literal carve-out at the base of the opaque smc_external window
// for the vendor eFuse shim CSR block; integrations that model the block override it.
// Memory-interface types are parameters rather than localparams so the mem-swap layer can
// specialize them.

module smc #(
  parameter int unsigned MAX_TRANS = 2,  // Maximum outstanding transactions of the padring
                                         // GPIO demux and of each GPIO interface.
  parameter int unsigned EFUSE_SHIM_SIZE = 'h44,  // Vendor eFuse shim CSR block carved
                                                  // off the base of the smc_external
                                                  // window.
                                                  // The open smc_external map is one
                                                  // opaque region, so this is a literal
                                                  // here and is overridden by an
                                                  // integration that models the block.

  parameter  type         rom_req_t             = chipyard_4core_mem_pkg::rom_req_t,  // Boot ROM request
                                                                                      // type, passed to
                                                                                      // smc_cpu_wrapper.
  parameter  type         rom_rsp_t             = chipyard_4core_mem_pkg::rom_rsp_t,  // Boot ROM response
                                                                                      // type, passed to
                                                                                      // smc_cpu_wrapper.
  parameter  type         scratch_ram_req_t     = chipyard_4core_mem_pkg::scratch_ram_req_t,  // Scratch RAM bank
                                                                                              // request type.
  parameter  type         scratch_ram_rsp_t     = chipyard_4core_mem_pkg::scratch_ram_rsp_t,  // Scratch RAM bank
                                                                                              // response type.
  parameter  type         l1_icache_tag_req_t   = chipyard_4core_mem_pkg::l1_icache_tag_req_t,  // Instruction-cache
                                                                                                // tag bank request
                                                                                                // type.
  parameter  type         l1_icache_tag_rsp_t   = chipyard_4core_mem_pkg::l1_icache_tag_rsp_t,  // Instruction-cache
                                                                                                // tag bank response
                                                                                                // type.
  parameter  type         l1_icache_data_req_t  = chipyard_4core_mem_pkg::l1_icache_data_req_t,  // Instruction-cache
                                                                                                 // data bank request
                                                                                                 // type.
  parameter  type         l1_icache_data_rsp_t  = chipyard_4core_mem_pkg::l1_icache_data_rsp_t,  // Instruction-cache
                                                                                                 // data bank response
                                                                                                 // type.
  parameter  type         l1_dcache_tag_req_t   = chipyard_4core_mem_pkg::l1_dcache_tag_req_t,  // Data-cache tag
                                                                                                // bank request type.
  parameter  type         l1_dcache_tag_rsp_t   = chipyard_4core_mem_pkg::l1_dcache_tag_rsp_t,  // Data-cache tag
                                                                                                // bank response
                                                                                                // type.
  parameter  type         l1_dcache_data_req_t  = chipyard_4core_mem_pkg::l1_dcache_data_req_t,  // Data-cache data
                                                                                                 // bank request type.
  parameter  type         l1_dcache_data_rsp_t  = chipyard_4core_mem_pkg::l1_dcache_data_rsp_t,  // Data-cache data
                                                                                                 // bank response
                                                                                                 // type.

  localparam int unsigned NUM_CPU_CORES         = smc_4core_cpu_pkg::NUM_CPU_CORES,  // CPU cores in the SMC
                                                                                     // cluster; sizes the
                                                                                     // per-core writeback PC
                                                                                     // and watchdog timeout
                                                                                     // vectors.
  localparam int unsigned NUM_CPU_INTERRUPTS    = smc_4core_cpu_pkg::NUM_CPU_INTERRUPTS,  // Interrupt lines from
                                                                                          // smc_base to the CPU
                                                                                          // wrapper.
  localparam int unsigned NUM_EXT_INTERRUPTS    = smc_4core_cpu_pkg::NUM_EXT_INTERRUPTS,  // External interrupt
                                                                                          // lines accepted on
                                                                                          // smc_ext_interrupts_i.

  localparam int unsigned NUM_SRAM_BANKS        = chipyard_4core_mem_pkg::NUM_SRAM_BANKS,  // Scratch RAM banks;
                                                                                           // sizes the scratch RAM
                                                                                           // memory interface
                                                                                           // arrays.
  localparam int unsigned NUM_ICACHE_TAG_BANKS  = chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS,  // L1 instruction-cache
                                                                                                 // tag banks; sizes the
                                                                                                 // I-cache tag memory
                                                                                                 // interface arrays.
  localparam int unsigned NUM_ICACHE_DATA_BANKS = chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS,  // L1 instruction-cache
                                                                                                  // data banks; sizes the
                                                                                                  // I-cache data memory
                                                                                                  // interface arrays.
  localparam int unsigned NUM_DCACHE_TAG_BANKS  = chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS,  // L1 data-cache tag
                                                                                                 // banks; sizes the
                                                                                                 // D-cache tag memory
                                                                                                 // interface arrays.
  localparam int unsigned NUM_DCACHE_DATA_BANKS = chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS  // L1 data-cache data
                                                                                                 // banks; sizes the
                                                                                                 // D-cache data memory
                                                                                                 // interface arrays.
) (
  input logic clk_smc_i,                // SMC core clock for smc_base, the CPU wrapper and the
                                        // SMC-clock peripherals.
  input logic clk_ref_i,                // Reference clock for the reset unit, the CLA time tick,
                                        // the CPU wrapper and the AVSBus controller.
  input logic clk_periph_i,             // Peripheral clock for the UART, I2C, I3C and AVSBus
                                        // register interfaces.

  input logic powergood_i,              // Chip powergood from the pad, active-high; low
                                        // asynchronously holds the reset unit's powergood
                                        // stretcher and cold-reset de-glitcher in reset.

  output logic powergood_stable_o,      // Powergood from the reset unit: falls with
                                        // powergood_i and rises 32 reference clock cycles
                                        // after it.

  input logic rst_cold_ni,              // Cold reset, active-low, deglitched and extended in the
                                        // reset unit.

  output logic rst_cold_stable_ref_clk_no,  // De-glitched and extended cold reset,
                                            // active-low, synchronized to the reference
                                            // clock.

  output logic rst_primary_ref_clk_no,  // Primary reset (cold, cool and function-level reset
                                        // combined), active-low, synchronized to the
                                        // reference clock.
  output logic rst_primary_smc_clk_no,  // Primary reset, active-low, synchronized to the SMC
                                        // clock; also resets smc_base and the CPU wrapper.
  output logic rst_primary_periph_clk_no,  // Primary reset, active-low, synchronized to the
                                           // peripheral clock.
  output logic rst_wdt_smc_clk_no,      // Watchdog reset from the SEP watchdog or the
                                        // second-stage SMC watchdog timeout, active-low,
                                        // synchronized to the SMC clock.
  output logic gated_clk_periph_i3c_o,  // Peripheral clock after the I3C clock gate; the
                                        // clock of the I3C controllers.

  input  smc_pkg::smc_sys_in_56_64_6_12_axi_req_t  sys_axi_in_req_i,  // Inbound system AXI
                                                                      // request; passes the
                                                                      // inbound filters to SMC
                                                                      // local targets.
  output smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t sys_axi_in_resp_o,  // Inbound system AXI
                                                                       // response.

  input  smc_pkg::smc_jtag_56_64_2_12_axi_req_t  jtag_axi_in_req_i,  // JTAG debug AXI request,
                                                                     // routed to SMC local
                                                                     // targets or the output
                                                                     // AXI port.
  output smc_pkg::smc_jtag_56_64_2_12_axi_resp_t jtag_axi_in_resp_o,  // JTAG debug AXI
                                                                      // response.

  input  smc_pkg::smc_axil_32_32_req_t  axil_smc_otp_jtag_req_i,  // JTAG request into the
                                                                  // eFuse wrapper, filtered
                                                                  // by lifecycle state.
  output smc_pkg::smc_axil_32_32_resp_t axil_smc_otp_jtag_resp_o,  // Response to the JTAG
                                                                   // eFuse access path.

  input  smc_pkg::smc_sep_in_56_64_6_12_axi_req_t  sep_axi_in_req_i,  // Inbound SEP AXI request,
                                                                      // routed to SMC local
                                                                      // targets.
  output smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t sep_axi_in_resp_o,  // Inbound SEP AXI
                                                                       // response.

  output smc_pkg::smc_sys_out_56_64_8_12_axi_req_t  output_axi_req_o,  // Outbound AXI request
                                                                       // from the output fabric,
                                                                       // after the output remap
                                                                       // and outbound filters.
  input  smc_pkg::smc_sys_out_56_64_8_12_axi_resp_t output_axi_resp_i,  // Outbound AXI response
                                                                        // into the output
                                                                        // fabric.

  output smc_pkg::smc_axil_32_32_req_t  axil_dtp_csr_req_o,  // DTP CSR request with its
                                                             // address rebased to zero at
                                                             // the DTP control window.
  input  smc_pkg::smc_axil_32_32_resp_t axil_dtp_csr_resp_i,  // DTP CSR response.

  output smc_efuse_pkg::efuse_map_t shadow_regs_o,  // eFuse shadow-register contents;
                                                    // all zero until fuse sensing
                                                    // completes unless SEP security
                                                    // disable is set.

  output smc_pkg::smc_axil_32_32_req_t  smc_external_req_o,  // AXI-L interface for
                                                             // adopter peripheral
                                                             // request, covering the
                                                             // smc_external window above
                                                             // the eFuse shim carve-out.
  input  smc_pkg::smc_axil_32_32_resp_t smc_external_resp_i,  // Response from the adopter
                                                              // peripherals in the
                                                              // smc_external window.

  output smc_pkg::smc_axil_32_32_req_t  efuse_bank_ctrl_req_o,  // Request to the vendor eFuse
                                                                // shim CSRs.
  input  smc_pkg::smc_axil_32_32_resp_t efuse_bank_ctrl_resp_i,  // Response from the vendor
                                                                 // eFuse shim CSRs.

  output smc_efuse_pkg::fuse_command_req_t  efuse_shim_command_req_o,  // Fuse sense and
                                                                       // program command
                                                                       // request to the shim
                                                                       // state machine.
  input  smc_efuse_pkg::fuse_command_resp_t efuse_shim_command_resp_i,  // Fuse command
                                                                        // response from the
                                                                        // shim state machine.

  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0] lsio_interface_select_o,  // LSIO select per pad,
                                                                       // high where a
                                                                       // peripheral function
                                                                       // claims the pad.
  input  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core_i,  // Value received from each GPIO
                                                          // pad.
  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad_o,  // Value driven onto each GPIO
                                                          // pad.
  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core_en_o,  // Input enable of each GPIO
                                                             // pad.
  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad_en_o,  // Output enable of each GPIO
                                                             // pad.

  input logic rst_cool_n_from_pin_i,    // Cool reset from the external pin, active-low;
                                        // deglitched in the reset unit into the primary
                                        // reset.

  input  logic       spi_enable_i,      // Hands the SPI pads to the external SPI host,
                                        // active-high.
  input  logic       spi_clk_i,         // Serial clock from the external SPI host, driven
                                        // onto the SPI clock pad.
  input  logic [7:0] spi_txd_i,         // Transmit data from the external SPI host, one
                                        // bit per data pad.
  input  logic       spi_cs_n_i,        // Chip select from the external SPI host,
                                        // active-low.
  input  logic       spi_cs_oe_n_i,     // Output enable for the chip-select pad,
                                        // active-low.
  input  logic       spi_cs_ie_n_i,     // Input enable for the chip-select pad,
                                        // active-low.
  input  logic       spi_clk_ie_n_i,    // Input enable for the SPI clock pad, active-low.
  input  logic       spi_clk_oe_n_i,    // Output enable for the SPI clock pad, active-low.
  input  logic       spi_dqs_ie_n_i,    // Input enable for the data-strobe pad,
                                        // active-low.
  input  logic       spi_dqs_oe_n_i,    // Output enable for the data-strobe pad,
                                        // active-low; the pad drives zero when enabled.
  input  logic [7:0] spi_dq_ie_n_i,     // Input enables for the data pads, active-low,
                                        // one bit per data pad.
  input  logic [7:0] spi_dq_oe_n_i,     // Output enables for the data pads, active-low,
                                        // one bit per data pad.
  output logic [7:0] spi_rxd_o,         // Receive data sampled from the data pads, to the
                                        // external SPI host.
  output logic       spi_rxds_o,        // Read data strobe sampled from the data-strobe
                                        // pad, used in DDR mode.
  input  logic       spi_mem_rebar_oepad_i,  // Output enable for the SPI DQS loopback
                                             // pad, active-high.
  input  logic       spi_mem_rebar_opad_i,  // Data driven onto the SPI DQS loopback
                                            // pad.
  input  logic       spi_mem_rebar_iepad_i,  // Input enable for the SPI DQS loopback
                                             // pad, active-high.
  output logic       spi_mem_rebar_ipad_o,  // Value sampled from the SPI DQS loopback
                                            // pad.

  input logic clk_telemetry_i,          // Telemetry clock for the ATB inputs, gated by the
                                        // telemetry clock-gate enable.
  input logic rst_telemetry_ni,         // Telemetry-domain reset, active-low, passed to the
                                        // telemetry receivers without synchronization.

  input  telemetry_receiver_pkg::telemetry_data_t [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atdata_i,  // ATB telemetry data,
                                                                                                                     // one word per
                                                                                                                     // receiver, on the
                                                                                                                     // telemetry clock.
  input  telemetry_receiver_pkg::atb_id_t         [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atid_i,  // ATB source ID
                                                                                                                   // accompanying each
                                                                                                                   // telemetry data word.
  output logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atready_o,  // ATB ready from each
                                                                                                                      // telemetry receiver
                                                                                                                      // to its source.
  input  logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atvalid_i,  // ATB valid from each
                                                                                                                      // telemetry source.
  output logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_afvalid_o,  // ATB flush request
                                                                                                                      // from each telemetry
                                                                                                                      // receiver to its
                                                                                                                      // source.
  input  logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_afready_i,  // ATB flush
                                                                                                                      // acknowledge from
                                                                                                                      // each telemetry
                                                                                                                      // source.

  output logic smc_cluster_ded_o,       // Uncorrectable (double-error-detected) memory
                                        // error from the SMC CPU cluster, registered on the
                                        // SMC clock.

  output logic smc_wdt_first_timeout_o,  // First-stage watchdog timeout: OR of the
                                         // per-core CPU watchdog timeouts.
  output logic smc_wdt_second_timeout_o,  // Second-stage watchdog timeout from the CPU
                                          // control block, registered on the SMC clock;
                                          // asserts the watchdog reset in the reset unit.

  output smc_pkg::smc_axi_addr_t        smc_global_base_o,  // SMC global base address
                                                            // from the smc_base
                                                            // configuration registers.
  output logic [31:0]                   smc_region_size_o,  // SMC region size in bytes from
                                                            // the smc_base REGION_SIZE
                                                            // register.

  input logic [NUM_EXT_INTERRUPTS-1:0] smc_ext_interrupts_i,  // External interrupts,
                                                              // synchronized in smc_base
                                                              // onto the lowest CPU
                                                              // interrupt lines.
  input logic [7:0]                    sep_mailbox_interrupts_i,  // SEP mailbox interrupts,
                                                                  // placed on peripheral
                                                                  // interrupt bits 7:0.
  input logic                          sep_wdt_reset_n_i,  // SEP watchdog reset,
                                                           // active-low; drives the
                                                           // watchdog reset in the reset
                                                           // unit and a peripheral
                                                           // interrupt.

  output logic smc_fuse_sense_done_o,   // High once eFuse sensing into the shadow
                                        // registers completes; used to sequence MBIST and
                                        // memory repair.
  output logic smc_fuse_reset_n_delayed_o,  // Fuse-released reset, active-low, delayed
                                            // by 16 SMC clock pipeline stages; held low
                                            // while boot stall is asserted.

  output logic skip_mem_repair_o,       // Asserted during a function-level reset to skip
                                        // memory repair and MBIST.
  input  logic ext_boot_seq_done_i,     // External boot sequence done, active-high; the
                                        // fuse-released reset stays low until it is set.

  input logic sep_security_disable_i,   // Security disable from the SEP eFuse
                                        // controller, active-high; skips automatic fuse
                                        // sensing and releases the shadow registers
                                        // without it.

  input  logic [2*smc_pkg::LC_STATE_WIDTH-1:0] lc_state_i,  // Differentially encoded
                                                            // lifecycle state, used by the
                                                            // eFuse JTAG access filter and
                                                            // reported in chip_config.
  output logic                                 lc_sigint_err_o,  // Integrity error from the
                                                                 // differential decode of
                                                                 // lc_state_i, active-high.

  input  logic [smc_config_pkg::CPU_CLUSTER_COUNT - 1:0] smc_ndmreset_request_i,  // Asynchronous NDM reset
                                                                                  // request from each
                                                                                  // external CPU cluster;
                                                                                  // raised as a peripheral
                                                                                  // interrupt.
  output logic [smc_config_pkg::CPU_CLUSTER_COUNT - 1:0] smc_ndmreset_process_o,  // Firmware response to
                                                                                  // each cluster's NDM
                                                                                  // reset request, from
                                                                                  // the NDMRESET_PROCESS
                                                                                  // register.

  output logic [smc_pkg::NUM_MAILBOXES-1:0] smc_ext_mailbox_interrupts_o,  // Outbound
                                                                           // interrupts of the
                                                                           // SMC mailboxes, one
                                                                           // per mailbox.

  input  logic        cfg_flr_pf_active_i,  // PCIe function-level reset request, active-high;
                                            // starts the reset unit's isolation and cool
                                            // reset sequence.
  output logic [31:0] isolate_req_o,    // Per-subsystem isolation requests from the reset
                                        // unit.

  input  logic [31:0]                            ss_reset_complete_i,  // Per-subsystem reset
                                                                       // complete
                                                                       // acknowledgments,
                                                                       // synchronized to the
                                                                       // SMC clock in the
                                                                       // reset unit.
  output logic [31:0]                            ss_config_o,  // Per-subsystem configuration
                                                               // bits written through the
                                                               // reset-unit SS_CONFIG
                                                               // register; cleared by primary
                                                               // reset.
  output smc_reset_unit_pkg::reset_ctrl_t        ss_reset_ctrl_o [31:0],  // Per-subsystem cold and
                                                                          // warm resets, hold
                                                                          // controls and
                                                                          // force-to-reference-clock
                                                                          // select; the resets are
                                                                          // not synchronized to the
                                                                          // subsystem clock.

  output logic sync_irq_o,              // Global sync bit set by software through the
                                        // reset-unit SYNC_REG register.

  output rom_req_t            smc_rom_intf_req_o,  // Boot ROM read request from the CPU
                                                   // wrapper.
  input  rom_rsp_t            smc_rom_intf_rsp_i,  // Boot ROM read data.
  output scratch_ram_req_t    smc_scratch_ram_intf_req_o [NUM_SRAM_BANKS-1:0],  // Scratch RAM bank
                                                                                // requests, driven by
                                                                                // the zero-fill until
                                                                                // it completes.
  input  scratch_ram_rsp_t    smc_scratch_ram_intf_rsp_i [NUM_SRAM_BANKS-1:0],  // Scratch RAM bank
                                                                                // read data.
  output l1_icache_tag_req_t  smc_l1_icache_tag_intf_req_o [NUM_ICACHE_TAG_BANKS-1:0],  // Instruction-cache
                                                                                        // tag bank requests.
  input  l1_icache_tag_rsp_t  smc_l1_icache_tag_intf_rsp_i [NUM_ICACHE_TAG_BANKS-1:0],  // Instruction-cache
                                                                                        // tag bank read data.
  output l1_icache_data_req_t smc_l1_icache_data_intf_req_o [NUM_ICACHE_DATA_BANKS-1:0],  // Instruction-cache
                                                                                          // data bank requests.
  input  l1_icache_data_rsp_t smc_l1_icache_data_intf_rsp_i [NUM_ICACHE_DATA_BANKS-1:0],  // Instruction-cache
                                                                                          // data bank read
                                                                                          // data.
  output l1_dcache_tag_req_t  smc_l1_dcache_tag_intf_req_o [NUM_DCACHE_TAG_BANKS-1:0],  // Data-cache tag
                                                                                        // bank requests.
  input  l1_dcache_tag_rsp_t  smc_l1_dcache_tag_intf_rsp_i [NUM_DCACHE_TAG_BANKS-1:0],  // Data-cache tag
                                                                                        // bank read data.
  output l1_dcache_data_req_t smc_l1_dcache_data_intf_req_o [NUM_DCACHE_DATA_BANKS-1:0],  // Data-cache data
                                                                                          // bank requests.
  input  l1_dcache_data_rsp_t smc_l1_dcache_data_intf_rsp_i [NUM_DCACHE_DATA_BANKS-1:0],  // Data-cache data
                                                                                          // bank read data.

  input  logic smc_disable_sram_auto_init_i,  // Skips zeroing of the scratch RAM after
                                              // reset, active-high.
  output logic smc_init_mem_done_o,     // High once scratch RAM zeroing completes or is
                                        // skipped.

  input  logic        chiplet_is_primary_i,  // High on the primary chiplet: the system timer
                                             // drives the timer sync pads, and the CPU
                                             // wrapper reports it in SMC_ATTRIBUTES.
  output logic [63:0] timer_count_o,    // Live 64-bit system timer count.

  input  logic boot_stall_jtag_ovrd_i,  // Replaces the boot-stall pad value with
                                        // boot_stall_jtag_val_i when high.
  input  logic boot_stall_jtag_val_i,   // Boot-stall value used while the JTAG override is
                                        // set.
  output logic boot_stall_combined_o,   // Boot stall synchronized to the SMC clock and made
                                        // sticky: once low it stays low until the next
                                        // primary reset.

  input smc_pkg::jtag_smc_reset_ctrl_t jtag_reset_ctrl_i,  // JTAG override selects and values
                                                           // for the fuse, cold, cool, warm
                                                           // and per-subsystem resets.

  output logic [cla_pkg::CLA_NUMBER_OF_CUSTOM_ACTIONS-1:0] cla_ext_action_custom_o,  // Custom CLA
                                                                                     // external-action
                                                                                     // outputs, one bit per
                                                                                     // action.

  output smc_pkg::xtrigger_t      xtrigger_ss_o,  // Cross-trigger lanes from the SMC
                                                  // core logic analyzer to the subsystem
                                                  // cross-trigger matrix, masked by the
                                                  // clock-halt trigger mask.
  input  wire smc_pkg::xtrigger_t xtrigger_ss_i,  // Cross-trigger lanes from the
                                                  // subsystem cross-trigger matrix into
                                                  // the SMC core logic analyzer.

  input  wire logic tdr_dbg_ctrl_clock_stop_en_i,  // Enables reporting a CLA halt-clock
                                                   // action as a clock stop.
  output logic      tdr_dbg_ctrl_clocks_stopped_by_cla_o,  // High while an enabled CLA
                                                           // halt-clock action requests a
                                                           // clock stop.

  output trace_mem_pkg::SinkMemPktIn_s [tn_pkg::TRC_RAM_INSTANCES-1:0]  trace_mem_req_o,  // Requests from the DFD
                                                                                          // trace sink to the
                                                                                          // external trace RAMs.
  input  trace_mem_pkg::SinkMemPktOut_s [tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_resp_i,  // Read data from the
                                                                                           // external trace RAMs.

  input logic [511:0] ext_debug_bus_i,  // Adopter debug signals for the upper half of the
                                        // SMC debug bus. Note: Ensure signals are 16-bit
                                        // aligned within this bus.

  input logic test_en_i,                // DFT test-mode enable, active-high; bypasses
                                        // the clock gates and selects the scan reset.
  input logic scan_rst_ni,              // DFT scan reset, active-low, used in place of
                                        // functional resets while test_en_i is high.

  input logic mem_repair_done_i,        // Memory repair has finished; reported in the DFX
                                        // STATUS_SMU register.
  input logic mem_repair_success_i,     // Memory repair succeeded; reported in the DFX
                                        // STATUS_SMU register.
  input logic mem_repair_abort_i,       // Memory repair was aborted; reported in the DFX
                                        // STATUS_SMU register.
  input logic mbist_done_i,             // Memory BIST has finished; reported in the DFX
                                        // STATUS_SMU register.
  input logic mbist_pass_i,             // Memory BIST passed; reported in the DFX STATUS_SMU
                                        // register.
  input logic mbist_abort_i,            // Memory BIST was aborted; reported in the DFX
                                        // STATUS_SMU register.

  input  logic        smc_cpu_jtag_TCK_i,  // JTAG test clock for the CPU cluster debug
                                           // transport module.
  input  logic        smc_cpu_jtag_TMS_i,  // JTAG test mode select for the CPU cluster debug
                                           // transport module.
  input  logic        smc_cpu_jtag_TDI_i,  // JTAG test data into the CPU cluster debug
                                           // transport module.
  output logic        smc_cpu_jtag_TDO_data_o,  // JTAG test data out of the CPU cluster
                                                // debug transport module.
  input  logic        smc_cpu_jtag_reset_i,  // Active-high asynchronous reset of the CPU
                                             // cluster JTAG TAP and debug module interface.
  input  logic [10:0] smc_cpu_jtag_mfr_id_i,  // Manufacturer ID reported in the CPU cluster
                                              // JTAG IDCODE.
  input  logic [15:0] smc_cpu_jtag_part_number_i,  // Part number reported in the CPU
                                                   // cluster JTAG IDCODE.
  input  logic [3:0]  smc_cpu_jtag_version_i,  // Version reported in the CPU cluster JTAG
                                               // IDCODE.

  input  i3c_pkg::dat_mem_src_t [smc_config_pkg::NUM_I3C-1:0]  i3c_dat_mem_src_i,  // Read data from each
                                                                                   // I3C device address
                                                                                   // table memory.
  output i3c_pkg::dat_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_sink_o,  // Request to each I3C
                                                                                    // device address table
                                                                                    // memory.
  input  i3c_pkg::dct_mem_src_t [smc_config_pkg::NUM_I3C-1:0]  i3c_dct_mem_src_i,  // Read data from each
                                                                                   // I3C device
                                                                                   // characteristics table
                                                                                   // memory.
  output i3c_pkg::dct_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_sink_o,  // Request to each I3C
                                                                                    // device
                                                                                    // characteristics table
                                                                                    // memory.
  input  i3c_pkg::rlt_mem_src_t [smc_config_pkg::NUM_I3C-1:0]  i3c_rlt_mem_src_i,  // Read data from each
                                                                                   // I3C reverse-lookup
                                                                                   // table memory.
  output i3c_pkg::rlt_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_rlt_mem_sink_o,  // Request to each I3C
                                                                                    // reverse-lookup table
                                                                                    // memory.

  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0]  gpio_interrupt_o,  // Interrupt from each GPIO
                                                                 // interface, active-high,
                                                                 // in the SMC clock domain.
  output logic [smc_config_pkg::NUM_UART-1:0] uart_interrupt_o  // UART interrupt from each
                                                                // UART on the peripheral
                                                                // clock, excluding UART
                                                                // error and log-engine
                                                                // interrupts.
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
