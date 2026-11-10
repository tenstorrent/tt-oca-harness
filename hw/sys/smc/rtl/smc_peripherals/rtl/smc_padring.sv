// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Mux SMC peripheral digital I/O onto chiplet pads.
//
// Instantiates one gpio interface per pad behind an AXI-Lite demux that routes each pad
// its own window and answers an address past the last pad's window with DECERR and read
// data 0xBADCAB1E. Assigns fixed pads to SPI, UART, I3C, I2C, AVSBus, PWM, the system
// timer, and the isolate-request, boot-stall and cool-reset pins; each function's enable
// drives the pad's LSIO select, which the gpio registers can disable. The pad mapping is
// combinational.

`include "ocah_assert.svh"

module smc_padring #(
  parameter int unsigned                   MAX_TRANS                 = 1,  // Maximum outstanding
                                                                           // transactions of the
                                                                           // demux and of each
                                                                           // gpio interface.
  parameter bit [gpio_pkg::AddrWidth-1:0] GPIO_INTF_BASE_ADDR       = 32'h00000000   // Base address of the
                                                                                     // first GPIO interface;
                                                                                     // a multiple of the
                                                                                     // 16-byte interface
                                                                                     // stride.

) (
  input  logic clk_i,                   // SMC core clock for the GPIO register demux and
                                        // the GPIO interfaces.
  input  logic rst_primary_ni,          // Primary reset, active-low, synchronized to
                                        // clk_i; resets the demux and GPIO registers.
  input  logic rst_cold_stable_smc_clk_ni,  // Stable cold reset, active-low,
                                            // synchronized to clk_i; while low, every
                                            // GPIO pad is held in its default direction
                                            // with the output disabled.

  input  logic test_en_i,               // DFT test-mode enable, active-high, passed to
                                        // the demux and the gpio interfaces.
  input  logic scan_rst_ni,             // DFT scan reset, active-low; unused.

  input  gpio_pkg::gpio_axil_req_t  axil_req_i,  // AXI-Lite Register Interface request.
  output gpio_pkg::gpio_axil_resp_t axil_resp_o,  // AXI-Lite Register Interface response.

  input  logic       spi_enable_i,      // Selects the SPI function on GPIO pads 0-10 and
                                        // 54, active-high.
  input  logic       spi_clk_i,         // Serial bit-rate clock driven onto GPIO 9.
  input  logic [7:0] spi_txd_i,         // Transmit data driven onto GPIO 0-7, one bit
                                        // per pad.
  input  logic       spi_cs_n_i,        // Chip select, active-low, driven onto GPIO 8.
  input  logic       spi_cs_oe_n_i,     // Output enable for the chip-select pad (GPIO 8),
                                        // active-low.
  input  logic       spi_cs_ie_n_i,     // Input enable for the chip-select pad (GPIO 8),
                                        // active-low.
  input  logic       spi_clk_ie_n_i,    // Input enable for the SPI clock pad (GPIO 9),
                                        // active-low.
  input  logic       spi_clk_oe_n_i,    // Output enable for the SPI clock pad (GPIO 9),
                                        // active-low.
  input  logic       spi_dqs_ie_n_i,    // Input enable for the data-strobe pad (GPIO 10),
                                        // active-low.
  input  logic       spi_dqs_oe_n_i,    // Output enable for the data-strobe pad (GPIO 10),
                                        // active-low; the pad drives zero when enabled.
  input  logic [7:0] spi_dq_ie_n_i,     // Input enables for the data pads (GPIO 0-7),
                                        // active-low.
  input  logic [7:0] spi_dq_oe_n_i,     // Output enables for the data pads (GPIO 0-7),
                                        // active-low.
  output logic [7:0] spi_rxd_o,         // Receive data sampled from GPIO 0-7.
  output logic       spi_rxds_o,        // Read data strobe sampled from GPIO 10, used in
                                        // DDR mode.
  input  logic       spi_mem_rebar_oepad_i,  // Output enable for the SPI DQS loopback
                                             // pad (GPIO 54), active-high.
  input  logic       spi_mem_rebar_opad_i,  // Data driven onto the SPI DQS loopback pad
                                            // (GPIO 54).
  input  logic       spi_mem_rebar_iepad_i,  // Input enable for the SPI DQS loopback pad
                                             // (GPIO 54), active-high.
  output logic       spi_mem_rebar_ipad_o,  // Value sampled from the SPI DQS loopback
                                            // pad (GPIO 54).

  input  logic [smc_config_pkg::NumUart-1:0] uart_enable_i,   // Selects each UART's
                                                              // four pads, active-high,
                                                              // one bit per UART; UART u
                                                              // uses GPIO 11+4u (RX),
                                                              // 12+4u (TX), 13+4u (RTS)
                                                              // and 14+4u (CTS).
  output logic [smc_config_pkg::NumUart-1:0] uart_rx_o,   // Receive data sampled from
                                                          // each UART's RX pad.
  input  logic [smc_config_pkg::NumUart-1:0] uart_tx_i,   // Transmit data driven onto
                                                          // each UART's TX pad.
  input  logic [smc_config_pkg::NumUart-1:0] uart_rts_n_i,   // Request-to-send,
                                                             // active-low, driven onto
                                                             // each UART's RTS pad.
  output logic [smc_config_pkg::NumUart-1:0] uart_cts_n_o,   // Clear-to-send,
                                                             // active-low, sampled from
                                                             // each UART's CTS pad.

  input  logic chiplet_is_primary_i,    // Timer pad direction: high drives GPIO 55 and
                                        // 56 from the timer inputs, low samples them.
  input  logic timer_sync_load_i,       // System timer sync-load, driven onto GPIO 55 on
                                        // the primary chiplet.
  input  logic timer_cnt_credit_i,      // System timer count credit, driven onto GPIO 56
                                        // on the primary chiplet.
  output logic timer_sync_load_o,       // System timer sync-load sampled from GPIO 55,
                                        // used on a secondary chiplet.
  output logic timer_cnt_credit_o,      // System timer count credit sampled from GPIO
                                        // 56, used on a secondary chiplet.
  input  logic timer_gpio_enable_i,     // Selects the system timer function on GPIO 55
                                        // and 56, active-high.

  output logic boot_stall_o,            // Boot-stall strap sampled from GPIO 57, not
                                        // synchronized to clk_i.

  input  logic [smc_config_pkg::NumI3c-1:0] i3c_enable_i,   // Selects each I3C
                                                            // instance's SCL and SDA
                                                            // pads, active-high:
                                                            // GPIO 27-28 for instance 0,
                                                            // 65-66 for instance 1, and
                                                            // from 29 upward for the
                                                            // rest.
  output logic [smc_config_pkg::NumI3c-1:0] i3c_scl_o,   // SCL sampled from each I3C
                                                         // instance's SCL pad.
  output logic [smc_config_pkg::NumI3c-1:0] i3c_sda_o,   // SDA sampled from each I3C
                                                         // instance's SDA pad.
  input  logic [smc_config_pkg::NumI3c-1:0] i3c_scl_i,   // SCL value driven onto each
                                                         // I3C instance's SCL pad.
  input  logic [smc_config_pkg::NumI3c-1:0] i3c_scl_oen_i,   // Output enable for each
                                                             // SCL pad, active-low.
  input  logic [smc_config_pkg::NumI3c-1:0] i3c_sda_i,   // SDA value driven onto each
                                                         // I3C instance's SDA pad.
  input  logic [smc_config_pkg::NumI3c-1:0] i3c_sda_oen_i,   // Output enable for SDA IO
                                                             // pad (active low).
  input  logic [smc_config_pkg::NumI3c-1:0] i3c_sda_pp_i,   // Push-pull select for each
                                                            // SDA pad; high enables the
                                                            // SDA output whatever
                                                            // i3c_sda_oen_i is.

  input  logic [smc_config_pkg::NumI2c-1:0] i2c_enable_i,   // Selects each I2C
                                                            // instance's SCL, SDA, SMBus
                                                            // alert and SMBus suspend
                                                            // pads, active-high; instance
                                                            // i uses GPIO 37+4i to 40+4i.
  input  logic [smc_config_pkg::NumI2c-1:0] i2c_master_enable_i,   // Controller mode per
                                                                   // I2C instance: the SMBus
                                                                   // alert pad is sampled and
                                                                   // the suspend pad driven;
                                                                   // in target mode the
                                                                   // directions reverse.
  output logic [smc_config_pkg::NumI2c-1:0] i2c_scl_o,   // SCL sampled from each I2C
                                                         // instance's SCL pad.
  output logic [smc_config_pkg::NumI2c-1:0] i2c_sda_o,   // SDA sampled from each I2C
                                                         // instance's SDA pad.
  output logic [smc_config_pkg::NumI2c-1:0] i2c_smbus_n_o,   // SMBus suspend, active-low,
                                                             // sampled from the pad in
                                                             // target mode; zero in
                                                             // controller mode.
  output logic [smc_config_pkg::NumI2c-1:0] i2c_smbus_alert_n_o,   // SMBus alert,
                                                                   // active-low, sampled
                                                                   // from the pad in
                                                                   // controller mode; zero
                                                                   // in target mode.
  input  logic [smc_config_pkg::NumI2c-1:0] i2c_scl_oen_i,   // Open-drain SCL control,
                                                             // active-low: low pulls the
                                                             // pad low, high releases it
                                                             // to the board pull-up.
  input  logic [smc_config_pkg::NumI2c-1:0] i2c_sda_oen_i,   // Open-drain SDA control,
                                                             // active-low: low pulls the
                                                             // pad low, high releases it
                                                             // to the board pull-up.
  input  logic [smc_config_pkg::NumI2c-1:0] i2c_smbus_n_i,   // SMBus suspend from the
                                                             // I2C core, active-low; in
                                                             // controller mode, low pulls
                                                             // the suspend pad low.
  input  logic [smc_config_pkg::NumI2c-1:0] i2c_smbus_alert_oe_i,   // In target mode,
                                                                    // high pulls the SMBus
                                                                    // alert pad low.

  input  logic avs_enable_i,            // Selects the AVSBus function on GPIO pads
                                        // 49-51, active-high.
  input  logic avs_clock_i,             // AVSBus clock from the AVSBus controller, driven
                                        // onto GPIO 49.
  input  logic avs_mdata_i,             // AVSBus controller-to-device data, driven onto
                                        // GPIO 50.
  output logic avs_sdata_o,             // AVSBus device-to-controller data, sampled from
                                        // GPIO 51.

  input  logic rst_cool_ni,             // Cool reset for other chiplets, active-low;
                                        // pulls GPIO 64 low while asserted and leaves it
                                        // undriven otherwise.
  output logic isolate_req_pin_o,       // Isolation request sampled from GPIO 53, not
                                        // synchronized to clk_i.

  input  logic [smc_config_pkg::NumPwmOutputs-1:0] pwm_i,   // PWM channel outputs; channel
                                                            // i is driven onto GPIO 59+i.
  input  logic [smc_config_pkg::NumPwmOutputs-1:0] pwm_pad_en_i,   // Selects GPIO 59+i for
                                                                   // PWM channel i,
                                                                   // active-high.

  output logic [smc_pkg::NumGpioWraps-1:0] lsio_interface_select_o,    // LSIO select per pad,
                                                                       // high where a
                                                                       // peripheral function
                                                                       // claims the pad; also
                                                                       // drives each gpio
                                                                       // interface's select.
  output logic [smc_pkg::NumGpioWraps-1:0] core2pad_o,    // Data driven to each pad by
                                                          // its gpio interface; zero
                                                          // during cold reset.
  output logic [smc_pkg::NumGpioWraps-1:0] core2pad_en_o,    // Output enable for each
                                                             // pad, active-high; low
                                                             // during cold reset.
  input  logic [smc_pkg::NumGpioWraps-1:0] pad2core_i,    // Value received from each
                                                          // pad, not synchronized to
                                                          // clk_i.
  output logic [smc_pkg::NumGpioWraps-1:0] pad2core_en_o,    // Input enable for each
                                                             // pad, active-high; the
                                                             // pad's default direction
                                                             // during cold reset.

  output logic [smc_pkg::NumGpioWraps-1:0] gpio_interrupt_o    // Interrupt from each gpio
                                                               // interface, active-high,
                                                               // registered on clk_i.

);

  ////////////////////
  // AXI-Lite Demux //
  ////////////////////

  // Each GPIO interface owns the addresses up to the next one; an address past the last
  // interface's window answers DECERR with read data 0xBADCAB1E.
  localparam int unsigned NumIntfRanges = smc_pkg::NumGpioWraps;

  typedef logic [gpio_pkg::AddrWidth-1:0] intf_range_addr_t[NumIntfRanges];

  function automatic intf_range_addr_t intf_range_base();
    intf_range_addr_t base;
    for (int unsigned i = 0; i < NumIntfRanges; i++) begin
      base[i] = GPIO_INTF_BASE_ADDR + gpio_pkg::AddrWidth'(
          i * smc_top_addrmap_pkg::SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_STRIDE);
    end
    return base;
  endfunction

  localparam intf_range_addr_t IntfRangeBase = intf_range_base();
  localparam intf_range_addr_t IntfRangeSize = '{
      default: gpio_pkg::AddrWidth'(smc_top_addrmap_pkg::SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_STRIDE)
  };

  gpio_pkg::gpio_axil_req_t  [NumIntfRanges-1:0] axil_reqs_to_intf;
  gpio_pkg::gpio_axil_resp_t [NumIntfRanges-1:0] axil_resps_from_intf;

  prim_axil_addr_demux #(
    .AXI_ADDR_WIDTH (gpio_pkg::AddrWidth),
    .AXI_DATA_WIDTH (gpio_pkg::DataWidth),
    .NUM_RANGES     (NumIntfRanges),
    .RANGE_BASE     (IntfRangeBase),
    .RANGE_SIZE     (IntfRangeSize),
    .MAX_TRANS      (MAX_TRANS),
    .aw_chan_t      (gpio_pkg::gpio_axil_aw_chan_t),
    .w_chan_t       (gpio_pkg::gpio_axil_w_chan_t),
    .b_chan_t       (gpio_pkg::gpio_axil_b_chan_t),
    .ar_chan_t      (gpio_pkg::gpio_axil_ar_chan_t),
    .r_chan_t       (gpio_pkg::gpio_axil_r_chan_t),
    .axil_req_t     (gpio_pkg::gpio_axil_req_t),
    .axil_resp_t    (gpio_pkg::gpio_axil_resp_t)
  ) u_gpio_intf_demux (
    .clk_i       (clk_i),
    .rst_ni      (rst_primary_ni),
    .test_en_i   (test_en_i),
    .slv_req_i   (axil_req_i),
    .slv_resp_o  (axil_resp_o),
    .mst_reqs_o  (axil_reqs_to_intf),
    .mst_resps_i (axil_resps_from_intf)
  );

  ////////////////////
  // LSIO Interface //
  ////////////////////

  localparam int unsigned PwmPadBase = 59;
  `OCAH_ASSERT_STATIC(PwmPadsFit_A, PwmPadBase + smc_config_pkg::NumPwmOutputs <= 63)

  logic [smc_pkg::NumGpioWraps-1:0] lsio_core2pad_en_n;
  logic [smc_pkg::NumGpioWraps-1:0] lsio_core2pad_data;
  logic [smc_pkg::NumGpioWraps-1:0] lsio_pad2core_en_n;
  logic [smc_pkg::NumGpioWraps-1:0] lsio_pad2core_data;

  always_comb begin
    // Disable all LSIO interface by default
    lsio_interface_select_o = '0;
    lsio_core2pad_en_n      = {smc_pkg::NumGpioWraps{smc_padring_pkg::DISABLED}};
    lsio_core2pad_data      = '0;
    lsio_pad2core_en_n      = {smc_pkg::NumGpioWraps{smc_padring_pkg::DISABLED}};

    // SPI
    for (int s = 0; s < 8; s = s + 1) begin : gen_spi_connections
      lsio_interface_select_o[s]  = spi_enable_i;
      lsio_core2pad_en_n[s]       = spi_dq_oe_n_i[s];
      lsio_core2pad_data[s]       = spi_txd_i[s];
      lsio_pad2core_en_n[s]       = spi_dq_ie_n_i[s];
      spi_rxd_o[s]                = lsio_pad2core_data[s];
    end

    lsio_interface_select_o[8]  = spi_enable_i;
    lsio_core2pad_en_n[8]       = spi_cs_oe_n_i;
    lsio_core2pad_data[8]       = spi_cs_n_i;
    lsio_pad2core_en_n[8]       = spi_cs_ie_n_i;

    lsio_interface_select_o[9]  = spi_enable_i;
    lsio_core2pad_en_n[9]       = spi_clk_oe_n_i;
    lsio_core2pad_data[9]       = spi_clk_i;
    lsio_pad2core_en_n[9]       = spi_clk_ie_n_i;

    lsio_interface_select_o[10] = spi_enable_i;
    lsio_core2pad_en_n[10]      = spi_dqs_oe_n_i;
    lsio_core2pad_data[10]      = 1'b0;
    lsio_pad2core_en_n[10]      = spi_dqs_ie_n_i;
    spi_rxds_o                  = lsio_pad2core_data[10];

    // UART
    for (integer u = 0; u < smc_config_pkg::NumUart; u = u + 1) begin : gen_uart_connections
      lsio_interface_select_o[11+4*u] = uart_enable_i[u];
      lsio_core2pad_en_n[11+4*u]      = smc_padring_pkg::DISABLED;
      lsio_core2pad_data[11+4*u]      = 1'b0;
      lsio_pad2core_en_n[11+4*u]      = smc_padring_pkg::ENABLED;
      uart_rx_o[u]                    = lsio_pad2core_data[11+4*u];

      lsio_interface_select_o[12+4*u] = uart_enable_i[u];
      lsio_core2pad_en_n[12+4*u]      = smc_padring_pkg::ENABLED;
      lsio_core2pad_data[12+4*u]      = uart_tx_i[u];
      lsio_pad2core_en_n[12+4*u]      = smc_padring_pkg::DISABLED;

      lsio_interface_select_o[13+4*u] = uart_enable_i[u];
      lsio_core2pad_en_n[13+4*u]      = smc_padring_pkg::ENABLED;
      lsio_core2pad_data[13+4*u]      = uart_rts_n_i[u];
      lsio_pad2core_en_n[13+4*u]      = smc_padring_pkg::DISABLED;

      lsio_interface_select_o[14+4*u] = uart_enable_i[u];
      lsio_core2pad_en_n[14+4*u]      = smc_padring_pkg::DISABLED;
      lsio_core2pad_data[14+4*u]      = 1'b0;
      lsio_pad2core_en_n[14+4*u]      = smc_padring_pkg::ENABLED;
      uart_cts_n_o[u]                 = lsio_pad2core_data[14+4*u];
    end

    lsio_interface_select_o[27] = i3c_enable_i[0];
    lsio_core2pad_en_n[27]      = i3c_scl_oen_i[0];
    lsio_core2pad_data[27]      = i3c_scl_i[0];
    lsio_pad2core_en_n[27]      = smc_padring_pkg::ENABLED;
    i3c_scl_o[0]                = lsio_pad2core_data[27];

    lsio_interface_select_o[28] = i3c_enable_i[0];
    lsio_core2pad_en_n[28]      = ~(~i3c_sda_oen_i[0] | i3c_sda_pp_i[0]);
    lsio_core2pad_data[28]      = i3c_sda_i[0];
    lsio_pad2core_en_n[28]      = smc_padring_pkg::ENABLED;
    i3c_sda_o[0]                = lsio_pad2core_data[28];

    // I3C 2 - 5 (I3C[1] is fully unbonded at GPIO[65,66])
    for (integer i = 0; i < (smc_config_pkg::NumI3c - 2); i = i + 1) begin : gen_i3c_connections
      lsio_interface_select_o[29+(2*i)] = i3c_enable_i[2+i];
      lsio_core2pad_en_n[29+(2*i)]      = i3c_scl_oen_i[2+i];
      lsio_core2pad_data[29+(2*i)]      = i3c_scl_i[2+i];
      lsio_pad2core_en_n[29+(2*i)]      = smc_padring_pkg::ENABLED;
      i3c_scl_o[2+i]                    = lsio_pad2core_data[29+(2*i)];

      lsio_interface_select_o[30+(2*i)] = i3c_enable_i[2+i];
      lsio_core2pad_en_n[30+(2*i)]      = ~(~i3c_sda_oen_i[2+i] | i3c_sda_pp_i[2+i]);
      lsio_core2pad_data[30+(2*i)]      = i3c_sda_i[2+i];
      lsio_pad2core_en_n[30+(2*i)]      = smc_padring_pkg::ENABLED;
      i3c_sda_o[2+i]                    = lsio_pad2core_data[30+(2*i)];
    end

    // I3C[1] fully unbonded (both SCL and SDA)

    lsio_interface_select_o[65] = i3c_enable_i[1];
    lsio_core2pad_en_n[65]      = i3c_scl_oen_i[1];
    lsio_core2pad_data[65]      = i3c_scl_i[1];
    lsio_pad2core_en_n[65]      = smc_padring_pkg::ENABLED;
    i3c_scl_o[1]                = lsio_pad2core_data[65];

    lsio_interface_select_o[66] = i3c_enable_i[1];
    lsio_core2pad_en_n[66]      = ~(~i3c_sda_oen_i[1] | i3c_sda_pp_i[1]);
    lsio_core2pad_data[66]      = i3c_sda_i[1];
    lsio_pad2core_en_n[66]      = smc_padring_pkg::ENABLED;
    i3c_sda_o[1]                = lsio_pad2core_data[66];

    // I2C
    for (integer i = 0; i < smc_config_pkg::NumI2c; i = i + 1) begin : gen_i2c_connections
      // SCL
      lsio_interface_select_o[37+4*i] = i2c_enable_i[i];
      if (i2c_master_enable_i[i]) begin
        lsio_core2pad_en_n[37+4*i]  = i2c_scl_oen_i[i];
        lsio_core2pad_data[37+4*i]  = 1'b0;     // drive 0 because board will have pullups
        lsio_pad2core_en_n[37+4*i]  = ~i2c_scl_oen_i[i];
        i2c_scl_o[i]                = lsio_pad2core_data[37+4*i];
      end else begin
        lsio_core2pad_en_n[37+4*i]  = i2c_scl_oen_i[i];
        lsio_core2pad_data[37+4*i]  = 1'b0;     // drive 0 because board will have pullups
        lsio_pad2core_en_n[37+4*i]  = ~i2c_scl_oen_i[i];
        i2c_scl_o[i]                = lsio_pad2core_data[37+4*i];
      end
      // SDA
      lsio_interface_select_o[38+4*i] = i2c_enable_i[i];
      if (i2c_master_enable_i[i]) begin
        lsio_core2pad_en_n[38+4*i]  = i2c_sda_oen_i[i];
        lsio_core2pad_data[38+4*i]  = 1'b0;     // drive 0 because board will have pullups
        lsio_pad2core_en_n[38+4*i]  = ~i2c_sda_oen_i[i];
        i2c_sda_o[i]                = lsio_pad2core_data[38+4*i];
      end else begin
        lsio_core2pad_en_n[38+4*i]  = i2c_sda_oen_i[i];
        lsio_core2pad_data[38+4*i]  = 1'b0;     // drive 0 because board will have pullups
        lsio_pad2core_en_n[38+4*i]  = ~i2c_sda_oen_i[i];
        i2c_sda_o[i]                = lsio_pad2core_data[38+4*i];
      end
      // SMBUS ALERT [0]
      // active low, goes low when as a target device, it wants to talk to host
      lsio_interface_select_o[39+4*i] = i2c_enable_i[i];
      if (~i2c_master_enable_i[i]) begin
        lsio_core2pad_en_n[39+4*i]  = ~i2c_smbus_alert_oe_i[i];
        lsio_core2pad_data[39+4*i]  = 1'b0;
        lsio_pad2core_en_n[39+4*i]  = smc_padring_pkg::DISABLED;
        i2c_smbus_alert_n_o[i]      = 1'b0;
      end else begin
        lsio_core2pad_en_n[39+4*i]  = smc_padring_pkg::DISABLED;
        lsio_core2pad_data[39+4*i]  = 1'b0;
        lsio_pad2core_en_n[39+4*i]  = smc_padring_pkg::ENABLED;
        i2c_smbus_alert_n_o[i]      = lsio_pad2core_data[39+4*i];
      end
      // SMBUS SUSPEND
      // active low, goes low when want to suspend as a host
      lsio_interface_select_o[40+4*i] = i2c_enable_i[i];
      if (i2c_master_enable_i[i]) begin
        lsio_core2pad_en_n[40+4*i]  = i2c_smbus_n_i[i];
        lsio_core2pad_data[40+4*i]  = 1'b0;
        lsio_pad2core_en_n[40+4*i]  = smc_padring_pkg::DISABLED;
        i2c_smbus_n_o[i]            = 1'b0;
      end else begin
        lsio_core2pad_en_n[40+4*i]  = smc_padring_pkg::DISABLED;
        lsio_core2pad_data[40+4*i]  = 1'b0;
        lsio_pad2core_en_n[40+4*i]  = smc_padring_pkg::ENABLED;
        i2c_smbus_n_o[i]            = lsio_pad2core_data[40+4*i];
      end
    end

    // AVS
    lsio_interface_select_o[49] = avs_enable_i;
    lsio_core2pad_en_n[49]      = smc_padring_pkg::ENABLED;
    lsio_core2pad_data[49]      = avs_clock_i;
    lsio_pad2core_en_n[49]      = smc_padring_pkg::DISABLED;

    lsio_interface_select_o[50] = avs_enable_i;
    lsio_core2pad_en_n[50]      = smc_padring_pkg::ENABLED;
    lsio_core2pad_data[50]      = avs_mdata_i;
    lsio_pad2core_en_n[50]      = smc_padring_pkg::DISABLED;

    lsio_interface_select_o[51] = avs_enable_i;
    lsio_core2pad_en_n[51]      = smc_padring_pkg::DISABLED;
    lsio_core2pad_data[51]      = 1'b0;
    lsio_pad2core_en_n[51]      = smc_padring_pkg::ENABLED;
    avs_sdata_o                 = lsio_pad2core_data[51];

    // Isolate Request Pin
    lsio_interface_select_o[53] = 1'b1;
    lsio_core2pad_en_n[53]      = smc_padring_pkg::DISABLED;
    lsio_core2pad_data[53]      = 1'b0;
    lsio_pad2core_en_n[53]      = smc_padring_pkg::ENABLED;
    isolate_req_pin_o           = lsio_pad2core_data[53];

    // SPI DQS Loopback
    lsio_interface_select_o[54] = spi_enable_i;
    lsio_core2pad_en_n[54]      = ~spi_mem_rebar_oepad_i;
    lsio_core2pad_data[54]      = spi_mem_rebar_opad_i;
    lsio_pad2core_en_n[54]      = ~spi_mem_rebar_iepad_i;
    spi_mem_rebar_ipad_o        = lsio_pad2core_data[54];

    // System Timer OCTS
    // Primary: drive sync load and credit cnt signals to pad
    // Secondary: receive sync load and credit cnt signals from pad
    lsio_interface_select_o[55] = timer_gpio_enable_i;
    lsio_core2pad_en_n[55]      = chiplet_is_primary_i ? smc_padring_pkg::ENABLED : smc_padring_pkg::DISABLED;
    lsio_core2pad_data[55]      = chiplet_is_primary_i ? timer_sync_load_i : 1'b0;
    lsio_pad2core_en_n[55]      = chiplet_is_primary_i ? smc_padring_pkg::DISABLED : smc_padring_pkg::ENABLED;
    timer_sync_load_o           = lsio_pad2core_data[55];

    lsio_interface_select_o[56] = timer_gpio_enable_i;
    lsio_core2pad_en_n[56]      = chiplet_is_primary_i ? smc_padring_pkg::ENABLED : smc_padring_pkg::DISABLED;
    lsio_core2pad_data[56]      = chiplet_is_primary_i ? timer_cnt_credit_i : 1'b0;
    lsio_pad2core_en_n[56]      = chiplet_is_primary_i ? smc_padring_pkg::DISABLED : smc_padring_pkg::ENABLED;
    timer_cnt_credit_o          = lsio_pad2core_data[56];

    // Boot Stall
    lsio_interface_select_o[57]   = 1'b1;
    lsio_core2pad_en_n[57]        = smc_padring_pkg::DISABLED;
    lsio_core2pad_data[57]        = '0;
    lsio_pad2core_en_n[57]        = smc_padring_pkg::ENABLED;
    boot_stall_o                  = lsio_pad2core_data[57];

    // OCCP interface software GPIO
    lsio_interface_select_o[58] = '0;
    lsio_core2pad_en_n[58]      = smc_padring_pkg::DISABLED;
    lsio_core2pad_data[58]      = '0;
    lsio_pad2core_en_n[58]      = smc_padring_pkg::DISABLED;

    // PWM
    for (int unsigned i = 0; i < smc_config_pkg::NumPwmOutputs; i++) begin : gen_pwm_connections
      lsio_interface_select_o[PwmPadBase+i] = pwm_pad_en_i[i];
      lsio_core2pad_en_n[PwmPadBase+i]      = smc_padring_pkg::ENABLED;
      lsio_core2pad_data[PwmPadBase+i]      = pwm_i[i];
      lsio_pad2core_en_n[PwmPadBase+i]      = smc_padring_pkg::DISABLED;
    end

    // Cool Reset In
    lsio_interface_select_o[63] = '0;
    lsio_core2pad_en_n[63]      = smc_padring_pkg::DISABLED;
    lsio_core2pad_data[63]      = '0;
    lsio_pad2core_en_n[63]      = smc_padring_pkg::DISABLED;

    // Cool Reset Out
    lsio_interface_select_o[64] = 1'b1;
    lsio_core2pad_en_n[64]      = rst_cool_ni;
    lsio_core2pad_data[64]      = 1'b0;
    lsio_pad2core_en_n[64]      = smc_padring_pkg::DISABLED;

  end

  ///////////
  // GPIOs //
  ///////////

  // Generate GPIO interfaces
  for (genvar i = 0; i < smc_pkg::NumGpioWraps; i++) begin : gen_gpio_intf

    // Pad allocation settings
    localparam bit InputByDefault = smc_padring_pkg::DefaultDirectionMap[i];

    // Assertion to protect against truncation on casts
    `OCAH_ASSERT_STATIC(
        GpioIntfSizeFits_A,
        smc_top_addrmap_pkg::SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_SIZE < (64'd1 << gpio_pkg::AddrWidth))

    // GPIO interface
    gpio #(
      .MAX_TRANS                  (MAX_TRANS),
      .INPUT_BY_DEFAULT           (InputByDefault),

      .GPIO_INTF_REG_MAP_SIZE     (gpio_pkg::AddrWidth'(
          smc_top_addrmap_pkg::SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_SIZE))
    ) u_gpio_interface (
      .clk_i                  (clk_i),
      .rst_primary_ni         (rst_primary_ni),
      .rst_cold_ni            (rst_cold_stable_smc_clk_ni),
      .test_en_i              (test_en_i),

      // AXI-Lite Register Interface from secondary demux
      .axil_req_i             (axil_reqs_to_intf[i]),
      .axil_resp_o            (axil_resps_from_intf[i]),

      // LSIO Interface
      .lsio_interface_select_i(lsio_interface_select_o[i]),
      .lsio_core2pad_en_ni    (lsio_core2pad_en_n[i]),
      .lsio_core2pad_data_i   (lsio_core2pad_data[i]),
      .lsio_pad2core_en_ni    (lsio_pad2core_en_n[i]),
      .lsio_pad2core_data_o   (lsio_pad2core_data[i]),

      // GPIO Interrupts
      .interrupt_o            (gpio_interrupt_o[i]),

      .core2pad_o             (core2pad_o[i]),
      .core2pad_en_o          (core2pad_en_o[i]),
      .pad2core_i             (pad2core_i[i]),
      .pad2core_en_o          (pad2core_en_o[i])

    );
  end

endmodule
