// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Aggregate SMC peripherals, eFuse, and pad-facing I/O.
//
// Instantiates the peripheral CSR crossbar and its clock-domain crossings, the padring
// and GPIOs, UART, I2C, I3C, telemetry receivers, AVSBus controller, eFuse wrapper,
// system timer, misc registers and the SMC reset unit. The SPI controller is outside this
// module: its signals only pass through the padring to the SPI pads. Returns UART/GPIO
// interrupts, the gated I3C clock, and debug buses.
//
// EFUSE_SHIM_SIZE is the vendor eFuse shim CSR carve-out at the base of the opaque
// smc_external window. Each peripheral clock-gate enable stops its clock when high.

module smc_peripherals #(
  parameter int unsigned MAX_TRANS = 2,  // Maximum outstanding transactions of the padring
                                         // GPIO demux and of each GPIO interface.
  parameter int unsigned EFUSE_SHIM_SIZE = 'h44  // Vendor eFuse shim CSR block carved off
                                                 // the base of the smc_external window;
                                                 // literal because the open smc_external
                                                 // map is opaque. Passed to the peripheral
                                                 // crossbar.
) (
  input  logic clk_ref_i,               // Reference clock for the reset unit, the AVSBus
                                        // controller and the peripheral CDC.
  input  logic clk_smc_i,               // SMC core clock for the peripheral crossbar and the
                                        // SMC-clock peripherals.
  input  logic clk_periph_i,            // Peripheral clock for the UART, I2C, I3C and
                                        // AVSBus register interfaces.
  input  logic test_en_i,               // DFT test-mode enable, active-high; bypasses
                                        // the peripheral clock gates and selects the scan
                                        // reset.
  input  logic scan_rst_ni,             // DFT scan reset, active-low, used in place of
                                        // functional resets while test_en_i is high.

  input  logic clk_telemetry_i,         // Telemetry clock, gated by tel_cg_en_i before it
                                        // reaches the telemetry receivers.
  input  logic rst_telemetry_ni,        // Telemetry-domain reset, active-low, passed to the
                                        // telemetry receivers without synchronization.

  input  logic i3c_cg_en_i,             // Stops the I3C peripheral clock when high;
                                        // synchronized to the peripheral clock.
  input  logic avs_cg_en_i,             // Stops the AVSBus controller peripheral and
                                        // reference clocks when high.
  input  logic i2c_cg_en_i,             // Stops the I2C peripheral clock when high.
  input  logic uart_cg_en_i,            // Stops the UART peripheral clock when high.
  input  logic tel_cg_en_i,             // Stops the telemetry receivers' gated SMC and
                                        // telemetry clocks when high.

  input  smc_pkg::smc_axil_32_32_req_t  axil_peripherals_req_i,  // Request from the local
                                                                 // crossbar into the
                                                                 // peripheral crossbar.
  output smc_pkg::smc_axil_32_32_resp_t axil_peripherals_resp_o,  // Response to the local
                                                                  // crossbar.

  output smc_pkg::smc_axil_56_64_req_t  axil_log_engine_req_o,  // Log-engine fetch request
                                                                // from the UART, moved onto the
                                                                // SMC clock.
  input  smc_pkg::smc_axil_56_64_resp_t axil_log_engine_resp_i,  // Log-engine fetch
                                                                 // response on the SMC clock.

  output smc_pkg::smc_axil_32_32_req_t  axil_dtp_csr_req_o,  // DTP CSR request with its
                                                             // address rebased to zero at
                                                             // the DTP control window.
  input  smc_pkg::smc_axil_32_32_resp_t axil_dtp_csr_resp_i,  // DTP CSR response.

  output smc_pkg::smc_axil_32_32_req_t  smc_external_req_o,  // Request for the part of the
                                                             // smc_external window above
                                                             // the eFuse shim carve-out.
  input  smc_pkg::smc_axil_32_32_resp_t smc_external_resp_i,  // Response from the
                                                              // smc_external window.

  input  smc_pkg::smc_axil_32_32_req_t  axil_smc_otp_jtag_req_i,  // JTAG request into the
                                                                  // eFuse wrapper, filtered
                                                                  // by lifecycle state.
  output smc_pkg::smc_axil_32_32_resp_t axil_smc_otp_jtag_resp_o,  // Response to the JTAG
                                                                   // eFuse access path.

  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0] lsio_interface_select_o,  // LSIO select per pad
                                                                       // from the padring,
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

  input  telemetry_receiver_pkg::telemetry_data_t [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atdata_i,  // ATB trace data
                                                                                                                     // per telemetry
                                                                                                                     // receiver.
  input  telemetry_receiver_pkg::atb_id_t         [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atid_i,  // ATB trace source
                                                                                                                   // ID per receiver.
  output logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atready_o,  // ATB ready from
                                                                                                                      // each receiver.
  input  logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_atvalid_i,  // ATB data valid
                                                                                                                      // per receiver.
  output logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_afvalid_o,  // ATB flush
                                                                                                                      // request from
                                                                                                                      // each receiver.
  input  logic                                    [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_afready_i,  // ATB flush
                                                                                                                      // acknowledge per
                                                                                                                      // receiver.

  input  logic [2*smc_pkg::LC_STATE_WIDTH-1:0] lc_state_i,  // Differentially encoded
                                                            // lifecycle state, used by the
                                                            // eFuse JTAG access filter and
                                                            // reported in chip_config.
  output logic                                 lc_sigint_err_o,  // Integrity error from the
                                                                 // differential decode of
                                                                 // lc_state_i, active-high.

  input  logic        chiplet_is_primary_i,  // Makes the system timer drive the timer sync
                                             // pads when high and follow them when low.
  output logic [63:0] timer_count_o,    // Live 64-bit system timer count.
  output logic [8:0]  system_timer_octs_credits_debug_o,  // Current system timer credit
                                                          // count.
  output logic        system_timer_octs_credits_left_debug_o,  // High while system timer
                                                               // credits remain.

  output smc_pkg::smc_axil_32_32_req_t  fuse_bank_ctrl_req_o,  // Request to the vendor eFuse
                                                               // shim CSRs.
  input  smc_pkg::smc_axil_32_32_resp_t fuse_bank_ctrl_resp_i,  // Response from the vendor
                                                                // eFuse shim CSRs.

  input  logic boot_stall_jtag_ovrd_i,  // Replaces the boot-stall pad value with
                                        // boot_stall_jtag_val_i when high.
  input  logic boot_stall_jtag_val_i,   // Boot-stall value used while the JTAG override is
                                        // set.
  output logic boot_stall_processed_o,  // Boot stall synchronized to the SMC clock and made
                                        // sticky: once low it stays low until the next
                                        // primary reset; while high it holds fuse_reset_n_o
                                        // low.

  output smc_efuse_pkg::fuse_command_req_t  efuse_shim_command_req_o,  // Fuse sense and
                                                                       // program command
                                                                       // request to the shim
                                                                       // state machine.
  input  smc_efuse_pkg::fuse_command_resp_t efuse_shim_command_resp_i,  // Fuse command
                                                                        // response from the
                                                                        // shim state machine.

  input  logic ext_boot_seq_done_i,     // External boot sequence done, active-high; the
                                        // eFuse wrapper holds its released reset until it is
                                        // set.

  input  logic sep_security_disable_i,  // Security disable from the SEP eFuse
                                        // controller, active-high; skips automatic fuse
                                        // sensing and releases the shadow registers
                                        // without it.

  output logic fuse_reset_n_o,          // Efuse Released Reset.
                                        // Fuse sensing done && external boot sequence
                                        // done (includes memory repair and shadow reg
                                        // override being complete) - the rest of SMC can
                                        // now boot. Held low while the boot stall is set.
  output logic fuse_reset_n_delayed_o,  // fuse_reset_n_o after 16 SMC clock pipe stages
                                        // reset by the primary reset.
  output logic fuse_sense_done_o,       // Fuse sensing done.
                                        // High once shadow-register loading from the
                                        // fuses completes.

  output smc_efuse_pkg::efuse_map_t shadow_regs_o,  // eFuse shadow-register contents; zero
                                                    // until fuse sensing completes unless
                                                    // sep_security_disable_i is set.

  input  logic [smc_config_pkg::CPU_CLUSTER_COUNT-1:0] ndmreset_request_i,  // Asynchronous NDM reset
                                                                            // request from each
                                                                            // external CPU cluster;
                                                                            // synchronized to the SMC
                                                                            // clock and raised as a
                                                                            // peripheral interrupt.
  output logic [smc_config_pkg::CPU_CLUSTER_COUNT-1:0] ndmreset_process_o,  // Firmware response to
                                                                            // each cluster's NDM
                                                                            // reset request, from the
                                                                            // NDMRESET_PROCESS
                                                                            // register.

  input  logic powergood_i,             // Powergood, active-high; while low the reset unit
                                        // holds the cold, primary and warm resets.
  input  logic rst_cold_ni,             // Cold reset, active-low, deglitched and extended in
                                        // the reset unit.
  input  logic rst_cool_ni,             // Cool reset from the pin, active-low, deglitched in
                                        // the reset unit into the primary reset.

  output logic rst_cold_stable_ref_clk_no,  // De-glitched and extended cold reset,
                                            // active-low, synchronized to the reference
                                            // clock.
  output logic powergood_stable_o,      // Powergood from the reset unit: falls with
                                        // powergood_i and rises 32 reference clock cycles
                                        // after it.

  input  logic rst_ext_wdt_ni,          // SEP watchdog reset, active-low; drives the
                                        // watchdog reset in the reset unit and, once
                                        // synchronized, a peripheral interrupt.
  input  logic smc_wdt_first_timeout_i,  // First-stage SMC watchdog timeout, passed to
                                         // the reset unit.
  input  logic smc_wdt_second_timeout_i,  // Second-stage SMC watchdog timeout; asserts
                                          // the watchdog reset in the reset unit.

  input  logic        cfg_flr_pf_active_i,  // PCIe function-level reset request, active-high;
                                            // starts the reset unit's isolation and cool
                                            // reset sequence.
  output logic [31:0] isolate_req_o,    // Per-subsystem isolation requests from the reset
                                        // unit, raised by its registers, the isolate pin or
                                        // the function-level reset sequence.
  output logic        skip_mem_repair_o,  // Asserted during a function-level reset to
                                          // skip memory repair and MBIST.

  input  logic [31:0]                     ss_reset_complete_i,  // Per-subsystem reset
                                                                // complete acknowledgments,
                                                                // synchronized to the SMC
                                                                // clock in the reset unit.
  output logic [31:0]                     ss_config_o,  // Per-subsystem configuration
                                                        // bits written through the
                                                        // reset-unit SS_CONFIG register;
                                                        // cleared by primary reset.
  output smc_reset_unit_pkg::reset_ctrl_t ss_reset_ctrl_o [31:0],  // Per-subsystem cold and
                                                                   // warm resets, hold controls
                                                                   // and force-to-reference-clock
                                                                   // select; the resets are not
                                                                   // synchronized to the
                                                                   // subsystem clock.

  output logic rst_primary_ref_clk_no,  // Primary reset (cold, cool and function-level
                                        // reset combined), active-low, synchronized to the
                                        // reference clock.
  output logic rst_primary_smc_clk_no,  // Primary reset, active-low, synchronized to the
                                        // SMC clock; resets the peripheral crossbar and
                                        // SMC-clock peripherals.
  output logic rst_warm_smc_clk_no,     // Warm reset (primary, watchdog and fuse reset
                                        // combined), active-low, synchronized to the SMC
                                        // clock.
  output logic rst_wdt_smc_clk_no,      // Watchdog reset from the SEP watchdog or the
                                        // second-stage SMC watchdog timeout, active-low,
                                        // synchronized to the SMC clock.
  output logic rst_primary_periph_clk_no,  // Primary reset, active-low, synchronized to
                                           // the peripheral clock.

  output logic sync_irq_o,              // Global sync bit set by software through the
                                        // reset-unit SYNC_REG register.

  input  smc_pkg::jtag_smc_reset_ctrl_t jtag_reset_ctrl_i,  // JTAG override selects and
                                                            // values for the fuse, cold,
                                                            // cool, warm and per-subsystem
                                                            // resets, in the TCK domain.

  input  logic [7:0] sep_mailbox_interrupts_i,  // SEP mailbox interrupts, placed on
                                                // peripheral interrupt bits 7:0.

  input  logic        axi_hang_irq_i,   // OR of the smc_base AXI hang detectors, placed
                                        // on peripheral interrupt bit 30.
  output logic [31:0] peripheral_interrupts_o,  // Peripheral interrupt vector to the SMC
                                                // interrupt controller: SEP mailbox,
                                                // telemetry, NDM reset, I3C, UART, AVSBus,
                                                // I2C, SEP watchdog, eFuse locked-field,
                                                // GPIO and AXI hang sources.

  output logic [smc_pkg::NUM_GPIO_WRAPS-1:0]  gpio_interrupt_o,  // Per-GPIO interrupt from
                                                                 // the padring, on the SMC
                                                                 // clock.
  output logic [smc_config_pkg::NUM_UART-1:0] uart_interrupt_o,  // Per-UART interrupt on
                                                                 // the peripheral clock,
                                                                 // without the error and
                                                                 // log-engine sources.

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
  output logic gated_clk_periph_i3c_o,  // Gated I3C peripheral clock (same domain as
                                        // i3ccore_wrapper).

  output logic [16:0] avsbus_cur_state_debug_o,  // AVSBus controller state,
                                                 // synchronized to the SMC clock.

  output logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0][3:0] telemetry_debug_o,  // telemetry receiver
                                                                                      // debug (4 bits per;
                                                                                      // see
                                                                                      // telemetry_receiver.sv
                                                                                      // for field
                                                                                      // definitions).

  output logic [smc_config_pkg::NUM_I2C-1:0][3:0] i2c_debug_o,  // I2C debug (4 bits per
                                                                // I2C; see i2c_core.sv
                                                                // for field definitions).

  output logic [9:0] efuse_debug_o      // eFuse controller status for the SMC debug bus:
                                        // shadow-register write and read locks, program
                                        // and read locks, write-setup-only, LC-state
                                        // access, read and program timeouts, request
                                        // error and secure-test-mode block, from bit 0
                                        // upward.
);

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  // AXI-Lite interface signals
  smc_pkg::smc_axil_32_32_req_t  axil_padring_req;
  smc_pkg::smc_axil_32_32_resp_t axil_padring_resp;

  smc_pkg::smc_axil_32_32_req_t  axil_avsbus_controller_req_smc_clk;
  smc_pkg::smc_axil_32_32_resp_t axil_avsbus_controller_resp_smc_clk;
  smc_pkg::smc_axil_32_32_req_t  axil_avsbus_controller_req_periph_clk;
  smc_pkg::smc_axil_32_32_resp_t axil_avsbus_controller_resp_periph_clk;

  smc_pkg::smc_axil_32_32_req_t  axil_i2c_req_smc_clk;
  smc_pkg::smc_axil_32_32_resp_t axil_i2c_resp_smc_clk;
  smc_pkg::smc_axil_32_32_req_t  axil_i2c_req_periph_clk;
  smc_pkg::smc_axil_32_32_resp_t axil_i2c_resp_periph_clk;

  smc_pkg::smc_axil_32_32_req_t  axil_uart_req_smc_clk;
  smc_pkg::smc_axil_32_32_resp_t axil_uart_resp_smc_clk;
  smc_pkg::smc_axil_32_32_req_t  axil_uart_req_periph_clk;
  smc_pkg::smc_axil_32_32_resp_t axil_uart_resp_periph_clk;

  smc_pkg::smc_axil_56_64_req_t  axil_log_engine_req_smc_clk;
  smc_pkg::smc_axil_56_64_resp_t axil_log_engine_resp_smc_clk;
  smc_pkg::smc_axil_56_64_req_t  axil_log_engine_req_periph_clk;
  smc_pkg::smc_axil_56_64_resp_t axil_log_engine_resp_periph_clk;

  smc_pkg::smc_axil_32_32_req_t  axil_efuse_req;
  smc_pkg::smc_axil_32_32_resp_t axil_efuse_resp;

  smc_pkg::smc_axil_32_32_req_t  axil_external_req;
  smc_pkg::smc_axil_32_32_resp_t axil_external_resp;

  smc_pkg::smc_axil_32_32_req_t  axil_telemetry_req;
  smc_pkg::smc_axil_32_32_resp_t axil_telemetry_resp;

  smc_pkg::smc_axil_32_32_req_t  axil_system_timer_octs_req;
  smc_pkg::smc_axil_32_32_resp_t axil_system_timer_octs_resp;

  smc_pkg::smc_axil_32_32_req_t  axil_i3c_req_smc_clk;
  smc_pkg::smc_axil_32_32_resp_t axil_i3c_resp_smc_clk;
  smc_pkg::smc_axil_32_32_req_t  axil_i3c_req_periph_clk;
  smc_pkg::smc_axil_32_32_resp_t axil_i3c_resp_periph_clk;

  smc_pkg::smc_axil_32_32_req_t  axil_reset_unit_req;
  smc_pkg::smc_axil_32_32_resp_t axil_reset_unit_resp;

  smc_pkg::smc_axil_32_32_req_t  axil_misc_req;
  smc_pkg::smc_axil_32_32_resp_t axil_misc_resp;

  // DTP CSR request before the xbar base address is stripped off
  smc_pkg::smc_axil_32_32_req_t axil_dtp_csr_req;

  // Clock gate enable signals synchronized to destination domains
  logic i2c_cg_en_periph_clk;
  logic uart_cg_en_periph_clk;
  logic avs_cg_en_periph_clk;
  logic avs_cg_en_ref_clk;
  logic tel_cg_en_telemetry_clk;

  // AVSBus control signals
  logic avs_sdata;
  logic avs_mdata;
  logic avs_clock;
  logic avs_gpio_enable;

  // I2C control signals
  logic [smc_config_pkg::NUM_I2C-1:0] i2c_enable_smc_clk;
  logic [smc_config_pkg::NUM_I2C-1:0] i2c_enable_periph_clk;
  logic [smc_config_pkg::NUM_I2C-1:0] i2c_master_enable;

  logic [smc_config_pkg::NUM_I2C-1:0] i2c_scl_o;
  logic [smc_config_pkg::NUM_I2C-1:0] i2c_sda_o;
  logic [smc_config_pkg::NUM_I2C-1:0] i2c_smbsus_no;
  logic [smc_config_pkg::NUM_I2C-1:0] i2c_smbalert_no;

  logic [smc_config_pkg::NUM_I2C-1:0] i2c_smbsus_ni;
  logic [smc_config_pkg::NUM_I2C-1:0] i2c_smbalert_ni;

  logic [smc_config_pkg::NUM_I2C-1:0] i2c_scl_i;
  logic [smc_config_pkg::NUM_I2C-1:0] i2c_sda_i;

  // UART control signals
  logic [smc_config_pkg::NUM_UART-1:0] uart_enable_smc_clk;
  logic [smc_config_pkg::NUM_UART-1:0] uart_enable_periph_clk;
  logic [smc_config_pkg::NUM_UART-1:0] uart_rx;
  logic [smc_config_pkg::NUM_UART-1:0] uart_tx;
  logic [smc_config_pkg::NUM_UART-1:0] uart_rts_n;
  logic [smc_config_pkg::NUM_UART-1:0] uart_cts_n;

  // Clock gate enable signal from CDC
  logic i3c_cg_en_periph_clk;

  // I3C control signals
  logic [smc_config_pkg::NUM_I3C-1:0] i3c_scl_to_pad;  // SCL output from I3C core
  logic [smc_config_pkg::NUM_I3C-1:0] i3c_sda_to_pad;  // SDA output from I3C core
  logic [smc_config_pkg::NUM_I3C-1:0] i3c_scl_oe_to_pad;  // SCL output enable
  logic [smc_config_pkg::NUM_I3C-1:0] i3c_sda_oe_to_pad;  // SDA output enable
  logic [smc_config_pkg::NUM_I3C-1:0] i3c_sel_od_pp_to_pad;  // Select open-drain (0) or push-pull (1)
  logic [smc_config_pkg::NUM_I3C-1:0] i3c_scl_from_pad;  // SCL input to I3C core
  logic [smc_config_pkg::NUM_I3C-1:0] i3c_sda_from_pad;  // SDA input to I3C core

  // Boot Stall
  logic boot_stall_from_bp;
  logic boot_stall_combined;
  logic boot_stall_sticky;
  logic boot_stall_sticky_n;
  logic fuse_reset_stalled_n;

  // Reset Unit Signals
  logic rst_cold_stable_smc_clk_n;  // Cold reset stable synchronized to SMCCLK, used by the padring
  logic isolate_req_pin;
  logic rst_cool_from_primary_n;  // Generated by the reset
  logic rst_primary_periph_clk_n;
  logic powergood_stable;

  // peripheral interrupts
  logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] telemetry_irq;
  logic [smc_config_pkg::NUM_I3C-1:0] i3c_irqs_smc_clk, i3c_irqs_periph_clk;
  logic [smc_config_pkg::NUM_UART-1:0] uart_err_periph_clk;
  logic [smc_config_pkg::NUM_UART-1:0] uart_irq_periph_clk;
  logic [smc_config_pkg::NUM_UART-1:0] log_engine_irq_periph_clk;
  logic                                avsbus_irq;
  logic                                avsbus_irq_smc_clk;
  logic [smc_config_pkg::NUM_I2C-1:0] i2c_irqs_smc_clk, i2c_irqs_periph_clk;
  logic                                locked_field_access_interrupt;
  logic [smc_config_pkg::NUM_UART-1:0] uart_irq_combined_smc_clk;
  logic [smc_pkg::NUM_GPIO_WRAPS-1:0]  gpio_interrupt;

  // SEP WDT reset synchronized to SMCCLK (for interrupt use only; raw signal still feeds reset_unit)
  logic rst_ext_wdt_smc_clk;

  // NDM reset request synchronized to SMCCLK
  logic [smc_config_pkg::CPU_CLUSTER_COUNT-1:0] ndmreset_request_smc_clk;

  // debug signals
  logic [16:0]                             avsbus_cur_state_debug;
  logic [smc_config_pkg::NUM_I2C-1:0][3:0] i2c_debug_periph_clk;

  // System Timer OCTS signals
  logic timer_sync_load_primary;
  logic timer_cnt_credit_primary;
  logic timer_sync_load_secondary;
  logic timer_cnt_credit_secondary;
  logic timer_gpio_enable;

  ///////////////////
  // AXI-Lite XBar //
  ///////////////////

  smc_periph_axi_lite_xbar #(
    .EFUSE_SHIM_SIZE(EFUSE_SHIM_SIZE)
  ) u_smc_periph_axi_lite_xbar (
    .clk_i                            (clk_smc_i),
    .rst_ni                           (rst_primary_smc_clk_no),
    .test_i                           (test_en_i),

    // Input from smc_local_xbar
    .periph_in_req_i                  (axil_peripherals_req_i),
    .periph_in_resp_o                 (axil_peripherals_resp_o),

    // Output ports
    .gpio_req_o                       (axil_padring_req),
    .gpio_resp_i                      (axil_padring_resp),
    .apb2avsbus_req_o                 (axil_avsbus_controller_req_smc_clk),
    .apb2avsbus_resp_i                (axil_avsbus_controller_resp_smc_clk),
    .i2c_req_o                        (axil_i2c_req_smc_clk),
    .i2c_resp_i                       (axil_i2c_resp_smc_clk),
    .uart_req_o                       (axil_uart_req_smc_clk),
    .uart_resp_i                      (axil_uart_resp_smc_clk),
    .efuse_req_o                      (axil_efuse_req),
    .efuse_resp_i                     (axil_efuse_resp),
    .telemetry_req_o                  (axil_telemetry_req),
    .telemetry_resp_i                 (axil_telemetry_resp),
    .system_timer_octs_req_o          (axil_system_timer_octs_req),
    .system_timer_octs_resp_i         (axil_system_timer_octs_resp),
    .dtp_csr_req_o                    (axil_dtp_csr_req),
    .dtp_csr_resp_i                   (axil_dtp_csr_resp_i),
    .i3c_req_o                        (axil_i3c_req_smc_clk),
    .i3c_resp_i                       (axil_i3c_resp_smc_clk),
    .reset_unit_req_o                 (axil_reset_unit_req),
    .reset_unit_resp_i                (axil_reset_unit_resp),
    .misc_req_o                       (axil_misc_req),
    .misc_resp_i                      (axil_misc_resp),
    .external_req_o                   (axil_external_req),
    .external_resp_i                  (axil_external_resp)
  );

  assign smc_external_req_o = axil_external_req;
  assign axil_external_resp = smc_external_resp_i;

  // Rebase DTP CSR addresses to zero: the xbar routes on the full system
  // address, but the DTP CSR block expects an offset from its base.
  always_comb begin
    axil_dtp_csr_req_o         = axil_dtp_csr_req;
    axil_dtp_csr_req_o.aw.addr = axil_dtp_csr_req.aw.addr - smc_top_addrmap_pkg::SMC_TOP_DTP_CTRL_REG_BASE_ADDR;
    axil_dtp_csr_req_o.ar.addr = axil_dtp_csr_req.ar.addr - smc_top_addrmap_pkg::SMC_TOP_DTP_CTRL_REG_BASE_ADDR;
  end

  //////////////////////
  // Periph Clock CDC //
  //////////////////////

  smc_peripherals_cdc #(
    .SYNC_STAGES(3)
  ) u_smc_peripherals_cdc (
    .clk_smc_i                         (clk_smc_i),
    .clk_periph_i                      (clk_periph_i),
    .clk_ref_i                         (clk_ref_i),
    .clk_telemetry_i                   (clk_telemetry_i),

    .rst_smc_clk_ni                    (rst_primary_smc_clk_no),
    .rst_periph_clk_ni                 (rst_primary_periph_clk_n),

    .axil_avsbus_req_smc_clk_i         (axil_avsbus_controller_req_smc_clk),
    .axil_avsbus_resp_smc_clk_o        (axil_avsbus_controller_resp_smc_clk),
    .axil_avsbus_req_periph_clk_o      (axil_avsbus_controller_req_periph_clk),
    .axil_avsbus_resp_periph_clk_i     (axil_avsbus_controller_resp_periph_clk),

    .axil_i2c_req_smc_clk_i            (axil_i2c_req_smc_clk),
    .axil_i2c_resp_smc_clk_o           (axil_i2c_resp_smc_clk),
    .axil_i2c_req_periph_clk_o         (axil_i2c_req_periph_clk),
    .axil_i2c_resp_periph_clk_i        (axil_i2c_resp_periph_clk),

    .i2c_enable_smc_clk_o              (i2c_enable_smc_clk),
    .i2c_enable_periph_clk_i           (i2c_enable_periph_clk),
    .i2c_irqs_smc_clk_o                (i2c_irqs_smc_clk),
    .i2c_irqs_periph_clk_i             (i2c_irqs_periph_clk),

    .i2c_debug_periph_clk_i            (i2c_debug_periph_clk),
    .i2c_debug_smc_clk_o               (i2c_debug_o),

    .axil_uart_req_smc_clk_i           (axil_uart_req_smc_clk),
    .axil_uart_resp_smc_clk_o          (axil_uart_resp_smc_clk),
    .axil_uart_req_periph_clk_o        (axil_uart_req_periph_clk),
    .axil_uart_resp_periph_clk_i       (axil_uart_resp_periph_clk),

    .axil_log_engine_req_smc_clk_o     (axil_log_engine_req_smc_clk),
    .axil_log_engine_resp_smc_clk_i    (axil_log_engine_resp_smc_clk),
    .axil_log_engine_req_periph_clk_i  (axil_log_engine_req_periph_clk),
    .axil_log_engine_resp_periph_clk_o (axil_log_engine_resp_periph_clk),

    .uart_enable_smc_clk_o             (uart_enable_smc_clk),
    .uart_enable_periph_clk_i          (uart_enable_periph_clk),

    .uart_irq_combined_smc_clk_o       (uart_irq_combined_smc_clk),
    .uart_err_periph_clk_i             (uart_err_periph_clk),
    .uart_irq_periph_clk_i             (uart_irq_periph_clk),
    .log_engine_irq_periph_clk_i       (log_engine_irq_periph_clk),

    .axil_i3c_req_smc_clk_i            (axil_i3c_req_smc_clk),
    .axil_i3c_resp_smc_clk_o           (axil_i3c_resp_smc_clk),
    .axil_i3c_req_periph_clk_o         (axil_i3c_req_periph_clk),
    .axil_i3c_resp_periph_clk_i        (axil_i3c_resp_periph_clk),

    .i3c_irqs_smc_clk_o                (i3c_irqs_smc_clk),
    .i3c_irqs_periph_clk_i             (i3c_irqs_periph_clk),

    .avsbus_irq_periph_clk_i           (avsbus_irq),
    .avsbus_irq_smc_clk_o              (avsbus_irq_smc_clk),

    .i2c_cg_en_smc_clk_i              (i2c_cg_en_i),
    .i2c_cg_en_periph_clk_o           (i2c_cg_en_periph_clk),
    .uart_cg_en_smc_clk_i             (uart_cg_en_i),
    .uart_cg_en_periph_clk_o          (uart_cg_en_periph_clk),
    .avs_cg_en_smc_clk_i              (avs_cg_en_i),
    .avs_cg_en_periph_clk_o           (avs_cg_en_periph_clk),
    .i3c_cg_en_smc_clk_i              (i3c_cg_en_i),
    .i3c_cg_en_periph_clk_o           (i3c_cg_en_periph_clk),

    .avs_cg_en_ref_clk_o             (avs_cg_en_ref_clk),

    .tel_cg_en_smc_clk_i             (tel_cg_en_i),
    .tel_cg_en_telemetry_clk_o       (tel_cg_en_telemetry_clk),

    .ndmreset_request_i              (ndmreset_request_i),
    .ndmreset_request_smc_clk_o      (ndmreset_request_smc_clk),

    .avsbus_cur_state_debug_i         (avsbus_cur_state_debug),
    .avsbus_cur_state_debug_o         (avsbus_cur_state_debug_o)
  );

  /////////////
  // Padring //
  /////////////

  // Protect against truncation from casts
  `OCAH_OT_ASSERT_INIT(
      PadringGpioSizeFits_A,
      smc_top_addrmap_pkg::SMC_TOP_GPIO_INTF_SIZE < (64'd1 << gpio_pkg::ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(PadringGpioBaseFits_A, smc_top_addrmap_pkg::SMC_TOP_GPIO_INTF_BASE_ADDR(0
                       ) < (64'd1 << gpio_pkg::ADDR_WIDTH))

  smc_padring #(
    .MAX_TRANS                  (MAX_TRANS), // threaded from smc_wrapper (was hardcoded 2)
    .ADDRESS_MAP_SIZE_PER_GPIO  (gpio_pkg::ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_GPIO_INTF_SIZE)),
    .GPIO_INTF_BASE_ADDR        (gpio_pkg::ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_GPIO_INTF_BASE_ADDR(0)))
  ) u_smc_padring (
    .clk_i                      (clk_smc_i),
    .rst_primary_ni             (rst_primary_smc_clk_no),
    .rst_cold_stable_smc_clk_ni (rst_cold_stable_smc_clk_n),

    .test_en_i                  (test_en_i),
    .scan_rst_ni                (scan_rst_ni),

    // AXI-Lite Register Interface
    .axil_req_i                 (axil_padring_req),
    .axil_resp_o                (axil_padring_resp),

    // SPI
    .spi_enable_i               (spi_enable_i),
    .spi_clk_i                  (spi_clk_i),
    .spi_txd_i                  (spi_txd_i),
    .spi_cs_n_i                 (spi_cs_n_i),
    .spi_cs_oe_n_i              (spi_cs_oe_n_i),
    .spi_cs_ie_n_i              (spi_cs_ie_n_i),
    .spi_clk_ie_n_i             (spi_clk_ie_n_i),
    .spi_clk_oe_n_i             (spi_clk_oe_n_i),
    .spi_dqs_ie_n_i             (spi_dqs_ie_n_i),
    .spi_dqs_oe_n_i             (spi_dqs_oe_n_i),
    .spi_dq_ie_n_i              (spi_dq_ie_n_i),
    .spi_dq_oe_n_i              (spi_dq_oe_n_i),
    .spi_rxd_o                  (spi_rxd_o),
    .spi_rxds_o                 (spi_rxds_o),
    .spi_mem_rebar_oepad_i      (spi_mem_rebar_oepad_i),
    .spi_mem_rebar_opad_i       (spi_mem_rebar_opad_i),
    .spi_mem_rebar_iepad_i      (spi_mem_rebar_iepad_i),
    .spi_mem_rebar_ipad_o       (spi_mem_rebar_ipad_o),

    // UART
    .uart_enable_i              (uart_enable_smc_clk),
    .uart_rx_o                  (uart_rx),
    .uart_tx_i                  (uart_tx),
    .uart_rts_n_i               (uart_rts_n),
    .uart_cts_n_o               (uart_cts_n),

    // System Timer OCTS
    .chiplet_is_primary_i       (chiplet_is_primary_i),
    .timer_sync_load_i          (timer_sync_load_primary),
    .timer_cnt_credit_i         (timer_cnt_credit_primary),
    .timer_sync_load_o          (timer_sync_load_secondary),
    .timer_cnt_credit_o         (timer_cnt_credit_secondary),
    .timer_gpio_enable_i        (timer_gpio_enable),

    // Boot Stall
    .boot_stall_o               (boot_stall_from_bp),

    // I3C - OCA I3C instances
    .i3c_enable_i         ('1),
    .i3c_scl_o            (i3c_scl_from_pad),     // SCL from padring
    .i3c_sda_o            (i3c_sda_from_pad),     // SDA from padring
    .i3c_scl_i            (i3c_scl_to_pad),     // SCL to padring (OCA only)
    .i3c_scl_oen_i        (~i3c_scl_oe_to_pad),   // SCL OE (active-low)
    .i3c_sda_i            (i3c_sda_to_pad),     // SDA to padring (OCA only)
    .i3c_sda_oen_i        (~i3c_sda_oe_to_pad),   // SDA OE (active-low)
    .i3c_sda_pp_i         (i3c_sel_od_pp_to_pad), // Push-pull select

    // I2C
    .i2c_enable_i               (i2c_enable_smc_clk),
    .i2c_master_enable_i        (i2c_master_enable),
    .i2c_scl_o                  (i2c_scl_i),
    .i2c_sda_o                  (i2c_sda_i),
    .i2c_smbus_n_o              (i2c_smbsus_ni),
    .i2c_smbus_alert_n_o        (i2c_smbalert_ni),
    .i2c_scl_oen_i              (i2c_scl_o),
    .i2c_sda_oen_i              (i2c_sda_o),
    .i2c_smbus_n_i              (i2c_smbsus_no),
    .i2c_smbus_alert_oe_i       (~i2c_smbalert_no),

    // AVS
    .avs_enable_i               (avs_gpio_enable),
    .avs_clock_i                (avs_clock),
    .avs_mdata_i                (avs_mdata),
    .avs_sdata_o                (avs_sdata),

    // Cool Reset
    .rst_cool_ni                (rst_cool_from_primary_n),

    // Isolate Request Pin
    .isolate_req_pin_o          (isolate_req_pin),

    // GPIO Data Lines
    .lsio_interface_select_o    (lsio_interface_select_o),
    .core2pad_o                 (core2pad_o),
    .core2pad_en_o              (core2pad_en_o),
    .pad2core_i                 (pad2core_i),
    .pad2core_en_o              (pad2core_en_o),

    // GPIO Interrupts
    .gpio_interrupt_o           (gpio_interrupt)
  );

  ///////////////////////
  // AVSBus Controller //
  ///////////////////////

  logic gated_clk_ref_avs;
  logic gated_clk_periph_avs;

  prim_clock_gating u_avs_clk_ref_gater (
    .clk_i(clk_ref_i),
    .en_i(~avs_cg_en_ref_clk),
    .test_en_i(test_en_i),
    .clk_o(gated_clk_ref_avs)
  );

  prim_clock_gating u_avs_clk_periph_gater (
    .clk_i(clk_periph_i),
    .en_i(~avs_cg_en_periph_clk),
    .test_en_i(test_en_i),
    .clk_o(gated_clk_periph_avs)
  );

  avsbus_controller #(
    .COMMAND_FIFO_DEPTH         (smc_config_pkg::AVS_COMMAND_FIFO_DEPTH),
    .READBACK_FIFO_DEPTH        (smc_config_pkg::AVS_READBACK_FIFO_DEPTH)
  ) u_avsbus_controller (
    .clk_reg_i                  (gated_clk_periph_avs),
    .clk_ref_i                  (gated_clk_ref_avs),

    .rst_reg_ni                 (rst_primary_periph_clk_n),
    .rst_ref_ni                 (rst_primary_ref_clk_no),
    .rst_clk_div_ni             (powergood_stable),

    .avs_sdata_i                (avs_sdata),
    .avs_mdata_o                (avs_mdata),
    .avs_clock_o                (avs_clock),
    .avs_gpio_enable_o          (avs_gpio_enable),

    .axil_req_i                 (axil_avsbus_controller_req_periph_clk),
    .axil_resp_o                (axil_avsbus_controller_resp_periph_clk),

    .interrupt_o                (avsbus_irq),

    .test_en_i                  (test_en_i),
    .scan_rst_ni                (scan_rst_ni),
    .clk_test_i                 (clk_periph_i),

    .cur_state_debug_o          (avsbus_cur_state_debug)
  );

  /////////
  // I2C //
  /////////

  logic gated_clk_periph_i2c;

  prim_clock_gating u_i2c_clk_periph_gater (
    .clk_i(clk_periph_i),
    .en_i(~i2c_cg_en_periph_clk),
    .test_en_i(test_en_i),
    .clk_o(gated_clk_periph_i2c)
  );

  `OCAH_OT_ASSERT_INIT(
      I2cCtrlBaseFits_A,
      smc_top_addrmap_pkg::SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_BASE_ADDR < (64'd1 << i2c_wrap_pkg::REG_ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(
      I2cCtrlSizeFits_A,
      smc_top_addrmap_pkg::SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_SIZE < (64'd1 << i2c_wrap_pkg::REG_ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(I2c0BaseFits_A, smc_top_addrmap_pkg::SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0
                       ) < (64'd1 << i2c_wrap_pkg::REG_ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(
      I2c0SizeFits_A,
      smc_top_addrmap_pkg::SMC_TOP_SMC_I2C_WRAP_I2C_SIZE < (64'd1 << i2c_wrap_pkg::REG_ADDR_WIDTH))

  i2c_wrap #(
    .NUM_I2CS                 (smc_config_pkg::NUM_I2C),
    .CONTROLLER_TX_FIFO_DEPTH (smc_config_pkg::I2C_CONTROLLER_TX_FIFO_DEPTH),
    .CONTROLLER_RX_FIFO_DEPTH (smc_config_pkg::I2C_CONTROLLER_RX_FIFO_DEPTH),
    .TARGET_TX_FIFO_DEPTH     (smc_config_pkg::I2C_TARGET_TX_FIFO_DEPTH),
    .TARGET_RX_FIFO_DEPTH     (smc_config_pkg::I2C_TARGET_RX_FIFO_DEPTH),
    .INPUT_DELAY_CYCLES       (smc_config_pkg::I2C_INPUT_DELAY_CYCLES),

    .I2C_CTRL_REG_MAP_BASE_ADDR (i2c_wrap_pkg::REG_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_BASE_ADDR)),
    .I2C_CTRL_REG_MAP_SIZE      (i2c_wrap_pkg::REG_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_SIZE)),
    .I2C_0__REG_MAP_BASE_ADDR   (i2c_wrap_pkg::REG_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0))),
    .I2C_0__REG_MAP_SIZE        (i2c_wrap_pkg::REG_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_SMC_I2C_WRAP_I2C_SIZE)),
    .I2C_INSTANCE_SPACING       (i2c_wrap_pkg::I2C_INSTANCE_SPACING)
  ) u_i2c_wrap (
    .clk_i                    (gated_clk_periph_i2c),
    .rst_ni                   (rst_primary_periph_clk_n),

    .axil_req_i               (axil_i2c_req_periph_clk),
    .axil_resp_o              (axil_i2c_resp_periph_clk),

    .i2c_en_o                 (i2c_enable_periph_clk),
    .i2c_controller_mode_en_o (i2c_master_enable),

    .scl_i                    (i2c_scl_i),
    .scl_o                    (i2c_scl_o),
    .sda_i                    (i2c_sda_i),
    .sda_o                    (i2c_sda_o),

    .smbsus_ni                (i2c_smbsus_ni),
    .smbsus_no                (i2c_smbsus_no),
    .smbalert_ni              (i2c_smbalert_ni),
    .smbalert_no              (i2c_smbalert_no),

    .controller_tx_ready_o    (/* UNUSED */),
    .controller_rx_ready_o    (/* UNUSED */),
    .target_tx_ready_o        (/* UNUSED */),
    .target_rx_ready_o        (/* UNUSED */),

    .i2c_irq_o                (i2c_irqs_periph_clk),
    .i2c_debug_o              (i2c_debug_periph_clk)
  );

  //////////
  // UART //
  //////////

  logic gated_clk_periph_uart;

  prim_clock_gating u_uart_clk_periph_gater (
    .clk_i(clk_periph_i),
    .en_i(~uart_cg_en_periph_clk),
    .test_en_i(test_en_i),
    .clk_o(gated_clk_periph_uart)
  );

  `OCAH_OT_ASSERT_INIT(UartLogEngineWrapBaseFits_A,
                       smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_BASE_ADDR(0
                       ) < (64'd1 << uart_wrap_pkg::REG_ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(
      UartLogEngineWrapSizeFits_A,
      smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_SIZE < (64'd1 << uart_wrap_pkg::REG_ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(
      UartBaseFits_A,
      smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0
      ) < (64'd1 << uart_wrap_pkg::REG_ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(
      UartSizeFits_A,
      smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SIZE < (64'd1 << uart_wrap_pkg::REG_ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(
      LogEngineBaseFits_A,
      smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0
      ) < (64'd1 << uart_wrap_pkg::REG_ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(
      LogEngineSizeFits_A,
      smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_SIZE < (64'd1 << uart_wrap_pkg::REG_ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(
      UartLogEngineCtrlBaseFits_A,
      smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR(
      0) < (64'd1 << uart_wrap_pkg::REG_ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(
      UartLogEngineCtrlSizeFits_A,
      smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_SIZE < (64'd1 << uart_wrap_pkg::REG_ADDR_WIDTH))

  uart_wrap #(
    .NUM_UARTS             (smc_config_pkg::NUM_UART),
    .UART_TX_FIFO_DEPTH    (smc_config_pkg::UART_TX_FIFO_DEPTH),
    .UART_RX_FIFO_DEPTH    (smc_config_pkg::UART_RX_FIFO_DEPTH),
    .GEN_LOG_ENGINES       (smc_config_pkg::GEN_LOG_ENGINES),
    .LOG_ENGINE_FIFO_DEPTH (smc_config_pkg::LOG_ENGINE_FIFO_DEPTH),

    .UART_LOG_ENGINE_WRAP_0__REG_MAP_BASE_ADDR (uart_wrap_pkg::REG_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_BASE_ADDR(0))),
    .UART_LOG_ENGINE_WRAP_0__REG_MAP_SIZE      (uart_wrap_pkg::REG_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_SIZE)),
    .UART_LOG_ENGINE_WRAP_SPACING              (uart_wrap_pkg::UART_LOG_ENGINE_WRAP_SPACING),

    .UART_REG_MAP_BASE_ADDR                    (uart_wrap_pkg::REG_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))),
    .UART_REG_MAP_SIZE                         (uart_wrap_pkg::REG_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SIZE)),
    .LOG_ENGINE_REG_MAP_BASE_ADDR              (uart_wrap_pkg::REG_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))),
    .LOG_ENGINE_REG_MAP_SIZE                   (uart_wrap_pkg::REG_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_SIZE)),
    .UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR    (uart_wrap_pkg::REG_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR(0))),
    .UART_LOG_ENGINE_CTRL_REG_MAP_SIZE         (uart_wrap_pkg::REG_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_SIZE))
  ) u_uart_wrap (
    .clk_i                  (gated_clk_periph_uart),
    .rst_ni                 (rst_primary_periph_clk_n),
    .csr_axil_req_i         (axil_uart_req_periph_clk),
    .csr_axil_resp_o        (axil_uart_resp_periph_clk),
    .log_fetch_axil_req_o   (axil_log_engine_req_periph_clk),
    .log_fetch_axil_resp_i  (axil_log_engine_resp_periph_clk),

    .uart_en_o              (uart_enable_periph_clk),

    .uart_rx_i              (uart_rx),
    .uart_tx_o              (uart_tx),

    .uart_cts_ni            (uart_cts_n),
    .uart_dsr_ni            ({smc_config_pkg::NUM_UART{1'b1}}),
    .uart_ri_ni             ({smc_config_pkg::NUM_UART{1'b1}}),
    .uart_dcd_ni            ({smc_config_pkg::NUM_UART{1'b1}}),

    .uart_rts_no            (uart_rts_n),
    .uart_dtr_no            (/* UNUSED */),
    .uart_out1_no           (/* UNUSED */),
    .uart_out2_no           (/* UNUSED */),

    .uart_rxrdy_o           (/* UNUSED */),
    .uart_txrdy_o           (/* UNUSED */),

    .uart_err_o             (uart_err_periph_clk),
    .uart_irq_o             (uart_irq_periph_clk),
    .log_engine_irq_o       (log_engine_irq_periph_clk)
  );

  assign axil_log_engine_req_o = axil_log_engine_req_smc_clk;
  assign axil_log_engine_resp_smc_clk = axil_log_engine_resp_i;

  ////////////////////
  // Telemetry Unit //
  ////////////////////

  logic gated_clk_smc_tel;

  prim_clock_gating u_tel_clk_smc_gater (
    .clk_i(clk_smc_i),
    .en_i(~tel_cg_en_i),
    .test_en_i(test_en_i),
    .clk_o(gated_clk_smc_tel)
  );

  logic gated_clk_telemetry;

  prim_clock_gating u_tel_clk_telemetry_gater (
    .clk_i(clk_telemetry_i),
    .en_i(~tel_cg_en_telemetry_clk),
    .test_en_i(test_en_i),
    .clk_o(gated_clk_telemetry)
  );

  `OCAH_OT_ASSERT_INIT(
      TelemetryRxBaseFits_A,
      smc_top_addrmap_pkg::SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_BASE_ADDR(0
      ) < (64'd1 << telemetry_receiver_wrap_pkg::REG_ADDR_WIDTH))
  `OCAH_OT_ASSERT_INIT(
      TelemetryRxSizeFits_A,
      smc_top_addrmap_pkg::SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_SIZE < (64'd1 << telemetry_receiver_wrap_pkg::REG_ADDR_WIDTH))

  telemetry_receiver_wrap #(
    .NUM_TELEMETRY_RECEIVERS                            (smc_config_pkg::NUM_TELEMETRY_RECEIVERS),
    .TELEMETRY_RECEIVER_BUFFER_DEPTH                    (smc_config_pkg::TELEMETRY_RECEIVER_BUFFER_DEPTH),
    .TELEMETRY_RECEIVER_MAX_NUM_COUNTERS_PER_MESSAGE    (smc_config_pkg::TELEMETRY_RECEIVER_MAX_NUM_COUNTERS_PER_MESSAGE),

    .TELEMETRY_RECEIVER_0__REG_MAP_BASE_ADDR            (telemetry_receiver_wrap_pkg::REG_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_BASE_ADDR(0))),
    .TELEMETRY_RECEIVER_0__REG_MAP_SIZE                 (telemetry_receiver_wrap_pkg::REG_ADDR_WIDTH'(smc_top_addrmap_pkg::SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_SIZE))
  ) u_telemetry_receiver_wrap (
    .clk_i                      (gated_clk_smc_tel),
    .rst_ni                     (rst_primary_smc_clk_no),
    .clk_telemetry_i            (gated_clk_telemetry),
    .rst_telemetry_ni           (rst_telemetry_ni),

    .axil_req_i                 (axil_telemetry_req),
    .axil_resp_o                (axil_telemetry_resp),

    .atdata_i                   (telemetry_atdata_i),
    .atid_i                     (telemetry_atid_i),
    .atready_o                  (telemetry_atready_o),
    .atvalid_i                  (telemetry_atvalid_i),
    .afvalid_o                  (telemetry_afvalid_o),
    .afready_i                  (telemetry_afready_i),

    .telemetry_receiver_irq_o   (telemetry_irq),
    // telemetry_receiver_debug_o is launched on SMCCLK (clk_i =
    // gated_clk_smc_tel). It drives telemetry_debug_o directly — no CDC
    // required. The signal was previously routed through
    // u_smc_peripherals_cdc.telemetry_debug_telemetry_clk_i, which re-flopped
    // it onto clk_telemetry_i and then synced it back to clk_smc_i — that
    // manufactured a spurious SMCCLK -> TELEMETRYCLK -> SMCCLK crossing
    // reported by VC SpyGlass as CDC_UNSYNC_CTRL on
    // u_smc_peripherals_cdc/telemetry_debug_telemetry_clk_flopped/Q[*][*].
    .telemetry_receiver_debug_o (telemetry_debug_o)
  );

  /////////////////////
  // Efuse Interface //
  /////////////////////

  logic fuse_reset_n;

  smc_efuse_wrapper u_smc_efuse_wrapper (
    .clk_i                           (clk_smc_i),
    .rst_ni                          (rst_primary_smc_clk_no),
    .test_en_i                       (test_en_i),
    .scan_rst_ni                     (scan_rst_ni),

    // Functional AXI4-Lite slave (SMC peripherals xbar efuse leg + eFuse shim leg)
    .axil_req_i                      (axil_efuse_req),
    .axil_resp_o                     (axil_efuse_resp),

    // JTAG AXI4-Lite slave
    .axil_smc_otp_jtag_req_i         (axil_smc_otp_jtag_req_i),
    .axil_smc_otp_jtag_resp_o        (axil_smc_otp_jtag_resp_o),

    // LC state from SEP
    .lc_state_i                      (lc_state_i),
    .lc_sigint_err_o                 (lc_sigint_err_o),

    // SHIM CSR + custom command interface
    .fuse_bank_ctrl_req_o            (fuse_bank_ctrl_req_o),
    .fuse_bank_ctrl_resp_i           (fuse_bank_ctrl_resp_i),
    .efuse_shim_command_req_o        (efuse_shim_command_req_o),
    .efuse_shim_command_resp_i       (efuse_shim_command_resp_i),

    .sep_security_disable_i          (sep_security_disable_i),
    .ext_boot_seq_done_i             (ext_boot_seq_done_i),

    .reset_n_o                       (fuse_reset_n),
    .fuse_sense_done_o               (fuse_sense_done_o),
    .shadow_regs_o                   (shadow_regs_o),

    .efuse_debug_o                   (efuse_debug_o),
    .locked_field_access_interrupt_o (locked_field_access_interrupt)
  );

  // In the reference integration, fuse_reset_n goes through jtag override first and second rstbypass, and then pipe stages
  prim_pipe_stages #(
    .WIDTH(1),
    .NUM_STAGES(16)
  ) u_fuse_reset_n_delay (
    .clk_i(clk_smc_i),
    .rst_ni(rst_primary_smc_clk_no),
    .en_i(1'b1),
    .d_i(fuse_reset_stalled_n),
    .q_o(fuse_reset_n_delayed_o)
  );

  // choose JTAG override for boot stall if available
  assign boot_stall_combined = boot_stall_jtag_ovrd_i ? boot_stall_jtag_val_i : boot_stall_from_bp;

  logic boot_stall_combined_smc_clk;
  prim_sync3 u_boot_stall_combined_sync (
    .clk_i (clk_smc_i),
    .d_i   (boot_stall_combined),
    .q_o   (boot_stall_combined_smc_clk)
  );

  // Once boot stall is deasserted, it cannot be reasserted until next primary reset
  always_ff @(posedge clk_smc_i) begin
    if (~rst_primary_smc_clk_no) begin
      boot_stall_sticky <= boot_stall_combined_smc_clk;
    end else begin
      if (~boot_stall_combined_smc_clk) begin
        boot_stall_sticky <= 1'b0;
      end else begin
        boot_stall_sticky <= boot_stall_sticky;
      end
    end
  end

  // provide final boot stall in case needed by other blocks
  assign boot_stall_processed_o = boot_stall_sticky;

  prim_inv u_boot_stall_sticky_inv (
    .in_i  (boot_stall_sticky),
    .out_o (boot_stall_sticky_n)
  );

  prim_and2 #(
    .Width(1)
  ) u_fuse_reset_stall_and (
    .in0_i (fuse_reset_n),
    .in1_i (boot_stall_sticky_n),
    .out_o (fuse_reset_stalled_n)
  );

  assign fuse_reset_n_o = fuse_reset_stalled_n;


  ///////////////////////
  // System Timer OCTS //
  ///////////////////////

  // Sync signals from timer - only used in primary mode
  logic timer_sync_load_from_timer;
  logic timer_cnt_credit_from_timer;

  system_timer_octs u_system_timer_octs (
    .clk_i                 (clk_smc_i),
    .rst_ni                (rst_primary_smc_clk_no),
    .axil_req_i            (axil_system_timer_octs_req),
    .axil_resp_o           (axil_system_timer_octs_resp),

    .is_primary_i          (chiplet_is_primary_i),

    // Primary: inputs unused, outputs drive sync signals
    // Secondary: inputs receive sync signals, outputs unused
    .timer_sync_load_i     (chiplet_is_primary_i ? 1'b0 : timer_sync_load_secondary),
    .timer_cnt_credit_i    (chiplet_is_primary_i ? 1'b0 : timer_cnt_credit_secondary),
    .timer_sync_load_o     (timer_sync_load_from_timer),
    .timer_cnt_credit_o    (timer_cnt_credit_from_timer),

    .timer_count_o         (timer_count_o),

    .timer_gpio_enable_o   (timer_gpio_enable),
    .cur_credits_debug_o   (system_timer_octs_credits_debug_o),
    .credits_left_debug_o  (system_timer_octs_credits_left_debug_o)
  );

  // Route sync outputs to padring only when primary
  assign timer_sync_load_primary = timer_sync_load_from_timer;
  assign timer_cnt_credit_primary = timer_cnt_credit_from_timer;


  ////////////////////
  // I3C Controller //
  ////////////////////

  logic gated_clk_periph_i3c;

  prim_clock_gating u_i3c_clk_periph_gater (
    .clk_i(clk_periph_i),
    .en_i(~i3c_cg_en_periph_clk),  // Note: inverted - 1 = gate clock OFF
    .test_en_i(test_en_i),
    .clk_o(gated_clk_periph_i3c)
  );

  i3ccore_wrapper #(
    .NUM_I3C            (smc_config_pkg::NUM_I3C),
    .I3C_REG_ADDR_WIDTH (i3ccore_wrap_pkg::I3C_REG_ADDR_WIDTH),
    .BASE_ADDR          (smc_top_addrmap_pkg::SMC_TOP_OCA_I3C_WRAP_BASE_ADDR),
    .INSTANCE_SPACING   (i3ccore_wrap_pkg::I3C_INSTANCE_SPACING),

    // I3C Core parameters
    .DatAw              (i3c_pkg::DatAw),
    .DctAw              (i3c_pkg::DctAw),
    .CsrAddrWidth       (I3CCSR_pkg::I3CCSR_MIN_ADDR_WIDTH),
    .CsrDataWidth       (I3CCSR_pkg::I3CCSR_DATA_WIDTH)
  ) u_i3ccore_wrapper (
    .clk_i              (gated_clk_periph_i3c),
    .rst_ni             (rst_primary_periph_clk_n),

    // AXI4-Lite Write Address Channel
    .awvalid_i          (axil_i3c_req_periph_clk.aw_valid),
    .awready_o          (axil_i3c_resp_periph_clk.aw_ready),
    .awaddr_i           (axil_i3c_req_periph_clk.aw.addr),
    .awprot_i           (axil_i3c_req_periph_clk.aw.prot),

    // AXI4-Lite Write Data Channel
    .wvalid_i           (axil_i3c_req_periph_clk.w_valid),
    .wready_o           (axil_i3c_resp_periph_clk.w_ready),
    .wdata_i            (axil_i3c_req_periph_clk.w.data),
    .wstrb_i            (axil_i3c_req_periph_clk.w.strb),

    // AXI4-Lite Write Response Channel
    .bvalid_o           (axil_i3c_resp_periph_clk.b_valid),
    .bready_i           (axil_i3c_req_periph_clk.b_ready),
    .bresp_o            (axil_i3c_resp_periph_clk.b.resp),

    // AXI4-Lite Read Address Channel
    .arvalid_i          (axil_i3c_req_periph_clk.ar_valid),
    .arready_o          (axil_i3c_resp_periph_clk.ar_ready),
    .araddr_i           (axil_i3c_req_periph_clk.ar.addr),
    .arprot_i           (axil_i3c_req_periph_clk.ar.prot),

    // AXI4-Lite Read Data Channel
    .rvalid_o           (axil_i3c_resp_periph_clk.r_valid),
    .rready_i           (axil_i3c_req_periph_clk.r_ready),
    .rdata_o            (axil_i3c_resp_periph_clk.r.data),
    .rresp_o            (axil_i3c_resp_periph_clk.r.resp),

    // I3C Interrupts
    .irq_o              (i3c_irqs_periph_clk),

    // I3C bus signals
    .scl_i              (i3c_scl_from_pad),
    .scl_o              (i3c_scl_to_pad),
    .scl_oe_o           (i3c_scl_oe_to_pad),
    .sda_i              (i3c_sda_from_pad),
    .sda_o              (i3c_sda_to_pad),
    .sda_oe_o           (i3c_sda_oe_to_pad),
    .sel_od_pp_o        (i3c_sel_od_pp_to_pad),

    // Recovery signals (unused for now)
    .recovery_payload_available_o   (/* UNUSED */),
    .recovery_image_activated_o     (/* UNUSED */),
    .peripheral_reset_o             (/* UNUSED */),
    .peripheral_reset_done_i        ({smc_config_pkg::NUM_I3C{1'b0}}),
    .escalated_reset_o              (/* UNUSED */),

    // DAT/DCT memory interfaces
    .dat_mem_src_i  (i3c_dat_mem_src_i),
    .dat_mem_sink_o (i3c_dat_mem_sink_o),
    .dct_mem_src_i  (i3c_dct_mem_src_i),
    .dct_mem_sink_o (i3c_dct_mem_sink_o),
    .rlt_mem_src_i  (i3c_rlt_mem_src_i),
    .rlt_mem_sink_o (i3c_rlt_mem_sink_o)
  );

  ///////////////////
  // SMC Misc Wrap //
  ///////////////////

  smc_misc_wrap #(
    .CHIP_ID                    (smc_config_pkg::CHIP_ID),
    .LC_STATE_WIDTH             (2 * smc_pkg::LC_STATE_WIDTH)
  ) u_smc_misc_wrap (
    .clk_i                      (clk_smc_i),
    .rst_ni                     (rst_primary_smc_clk_no),
    .rst_warm_ni                (rst_warm_smc_clk_no),
    .test_en_i                  (test_en_i),
    .reg_axi_lite_req_i         (axil_misc_req),
    .reg_axi_lite_resp_o        (axil_misc_resp),

    .lc_state_i                 (lc_state_i),

    .ndmreset_request_i         (ndmreset_request_smc_clk),
    .ndmreset_process_o         (ndmreset_process_o)
  );

  ////////////////////
  // SMC Reset Unit //
  ////////////////////

  smc_reset_unit u_smc_reset_unit (
    .clk_ref_i                  (clk_ref_i),
    .clk_smc_i                  (clk_smc_i),
    .clk_periph_i               (clk_periph_i),

    .powergood_i                (powergood_i),
    .powergood_stable_o         (powergood_stable),

    .rst_cold_ni                (rst_cold_ni),

    .fuse_reset_ni              (fuse_reset_n_o),

    .rst_cold_stable_ref_clk_no (rst_cold_stable_ref_clk_no),
    .rst_cold_stable_smc_clk_no (rst_cold_stable_smc_clk_n),

    .jtag_reset_ctrl_i          (jtag_reset_ctrl_i),

    .reg_axi_lite_req_i         (axil_reset_unit_req),
    .reg_axi_lite_resp_o        (axil_reset_unit_resp),

    .rst_ext_wdt_ni             (rst_ext_wdt_ni),
    .smc_wdt_first_timeout_i    (smc_wdt_first_timeout_i),
    .smc_wdt_second_timeout_i   (smc_wdt_second_timeout_i),

    .isolate_req_pin_i          (isolate_req_pin),
    .cfg_flr_pf_active_i        (cfg_flr_pf_active_i),
    .rst_cool_ni                (rst_cool_ni),              // Driven from ip_integration - cool_rst_n_from_pin
    .isolate_req_o              (isolate_req_o),
    .skip_mem_repair_o          (skip_mem_repair_o),
    .rst_cool_no                (rst_cool_from_primary_n),

    .ss_reset_complete_i        (ss_reset_complete_i),
    .ss_config_o                (ss_config_o),
    .ss_reset_ctrl_o            (ss_reset_ctrl_o),
    .rst_primary_ref_clk_no     (rst_primary_ref_clk_no),
    .rst_primary_smc_clk_no     (rst_primary_smc_clk_no),
    .rst_warm_smc_clk_no        (rst_warm_smc_clk_no),
    .rst_wdt_smc_clk_no         (rst_wdt_smc_clk_no),
    .rst_primary_periph_clk_no  (rst_primary_periph_clk_n),

    .sync_irq_o                 (sync_irq_o),

    .test_en_i                  (test_en_i),
    .scan_rst_ni                (scan_rst_ni)
  );

  assign powergood_stable_o = powergood_stable;

  ////////////////////
  // Interrupts     //
  ////////////////////

  prim_sync3 u_rst_ext_wdt_irq_sync (
    .clk_i (clk_smc_i),
    .d_i   (~rst_ext_wdt_ni),
    .q_o   (rst_ext_wdt_smc_clk)
  );

  always_comb begin
    peripheral_interrupts_o          = '0;
    peripheral_interrupts_o[7:0]     = sep_mailbox_interrupts_i;
    peripheral_interrupts_o[10:8]    = telemetry_irq;
    peripheral_interrupts_o[11]      = |ndmreset_request_smc_clk; // Maybe also combine these in the same way as the uart combined interrupt
    peripheral_interrupts_o[17:12]   = i3c_irqs_smc_clk;
    peripheral_interrupts_o[21:18]   = uart_irq_combined_smc_clk;
    peripheral_interrupts_o[22]      = avsbus_irq_smc_clk;
    peripheral_interrupts_o[25:23]   = i2c_irqs_smc_clk;
    peripheral_interrupts_o[26]      = rst_ext_wdt_smc_clk; // synchronized active-high WDT reset assertion
    peripheral_interrupts_o[27]      = locked_field_access_interrupt;
    peripheral_interrupts_o[28]      = |gpio_interrupt[smc_pkg::NUM_BONDED_GPIO/2-1:0];                     // OR-reduced across lower half of GPIO wraps; SW reads GPIO status regs to identify source
    peripheral_interrupts_o[29]      = |gpio_interrupt[smc_pkg::NUM_BONDED_GPIO-1:smc_pkg::NUM_BONDED_GPIO/2]; // OR-reduced across upper half of GPIO wraps; SW reads GPIO status regs to identify source
    peripheral_interrupts_o[30]      = axi_hang_irq_i; // OR of the three smc_base AXI hang detectors; SW reads HANG_DET_*_CTRL to identify the master
  end

  // async assignment to top level ports
  assign gpio_interrupt_o = gpio_interrupt;
  assign uart_interrupt_o = uart_irq_periph_clk;

  assign gated_clk_periph_i3c_o = gated_clk_periph_i3c;
  assign rst_primary_periph_clk_no = rst_primary_periph_clk_n;

endmodule
