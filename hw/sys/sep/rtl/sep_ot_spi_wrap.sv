// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP OpenTitan SPI Host Wrapper - AXI-Lite to TL-UL Bridge using axi_lite_to_tlul
//
// Follows the crypto-accelerator pattern (see hmac_wrapper / kmac_wrapper):
// the unmodified OpenTitan `spi_host` core is instantiated on its native
// TL-UL register interface, and `axi_lite_to_tlul` bridges the 32-bit
// AXI4-Lite bus that `sep_io` already presents. The register block is the
// upstream REGGEN block, so the OpenTitan SPI Host documentation is
// authoritative for the register map and interrupt semantics (INTR_STATE is
// RW1C, INTR_ENABLE gates only the interrupt output, INTR_TEST is a
// write pulse).
//
// Status and interrupt ports:
// - irq_o           : OR of the core's two interrupt lines (error, spi_event)
// - lsio_trigger_o  : passed through
//
// There is no busy output. The core keeps its activity state internal and
// publishes it only as STATUS.ACTIVE, which software reads over this wrapper's
// register interface.
//
// Tie-offs on the upstream core:
// - RACL is compiled out (EnableRacl = 0); policies are driven inactive.
// - The spi_device passthrough interface is held inactive.
// - The single fatal alert (bus integrity) is terminated here; `sep_io` has no
//   alert path.
//
// Features (from the upstream core):
// - Configurable number of chip selects (default: 1)
// - Up to Quad SPI (4-bit data width)
// - Single Transfer Rate (STR) only (no DTR/DDR support)
// - Software-driven command sequences; no memory-mapped (XIP) flash access

module sep_ot_spi_wrap #(
  parameter int unsigned NUM_CS = 1  // Number of chip selects
) (
  // Global Interface
  input  logic clk_i,
  input  logic rst_ni,

  // Test/Scan Interface
  input  logic test_en_i,

  //=========================================================================
  // AXI4-Lite Register Interface
  // Address range: 0x10B0_0000 - 0x10B0_0037 (56 bytes)
  //=========================================================================
  input  sep_io_pkg::axil_req_t  axil_req_i,
  output sep_io_pkg::axil_resp_t axil_resp_o,

  //=========================================================================
  // SPI Pad Interface (directly active signals)
  //=========================================================================
  // Clock
  output logic              spi_sck_o,
  output logic              spi_sck_oe_o,

  // Chip Select (directly active-low, directly active OE)
  output logic [NUM_CS-1:0] spi_cs_no,     // Active-low chip select
  output logic [NUM_CS-1:0] spi_cs_oe_o,   // Output enable (directly active)

  // Data (directly active signals, only 4 bits for OpenTitan)
  output logic [3:0]        spi_sd_o,      // Data output (directly active)
  output logic [3:0]        spi_sd_oe_o,   // Output enable (directly active)
  input  logic [3:0]        spi_sd_i,      // Data input

  //=========================================================================
  // Status and Interrupt Interface
  //=========================================================================
  output logic              irq_o,            // interrupt (error | spi_event)
  output logic              lsio_trigger_o    // DMA trigger
);

  logic unused_test_en;
  assign unused_test_en = test_en_i;

  /////////////////////////////////////////////////////////////////////////////
  // Address masking for the upstream register decoder
  //
  // spi_host_reg_top decodes BlockAw (6) address bits, covering 0x00-0x3F, so
  // the aperture base must be BlockAw-aligned for the mask below to produce the
  // block-relative offset. The SEP base satisfies that and has zero in those
  // bits, which makes SpiBaseLower zero and the subtract a no-op today.
  /////////////////////////////////////////////////////////////////////////////

  localparam int unsigned SpiBlockAw = spi_host_reg_pkg::BlockAw;
  localparam logic [sep_io_pkg::ADDR_WIDTH-1:0] SpiAddrMask =
      sep_io_pkg::ADDR_WIDTH'((1 << SpiBlockAw) - 1);
  localparam logic [sep_io_pkg::ADDR_WIDTH-1:0] SpiBaseLower =
      sep_io_pkg::ADDR_WIDTH'(sep_top_addrmap_pkg::SEP_TOP_SPI_CONTROLLER_BASE_ADDR)
      & SpiAddrMask;

  sep_io_pkg::axil_req_t axil_req_masked;

  always_comb begin
    axil_req_masked         = axil_req_i;
    axil_req_masked.aw.addr = (axil_req_i.aw.addr - SpiBaseLower) & SpiAddrMask;
    axil_req_masked.ar.addr = (axil_req_i.ar.addr - SpiBaseLower) & SpiAddrMask;
  end

  /////////////////////////////////////////////////////////////////////////////
  // AXI-Lite to TL-UL conversion
  //
  // AckZeroStrobeWrite: the SEP crossbar is 64 bits wide and this block sits
  // behind the 64-to-32 downsizer in sep_io. A master that writes a 32-bit
  // register with a full-width (AxSIZE = 8 bytes) beat and byte strobes -- the
  // inbound port from the SoC, the debug master, or a verification master --
  // is split into two 32-bit writes, and the half outside the master's strobe
  // arrives with WSTRB == 0 on the neighbouring register. Masters that issue
  // exact-size beats are unaffected: the VeeR core does so for side-effect
  // regions (MRAC), and the Secure DMA's upsizer passes its FIXED,
  // non-modifiable beats through at their original size. The forked
  // controller's register block accepted zero-strobe writes silently; upstream
  // spi_host_reg_top returns d_error, which surfaces as SLVERR. The converter
  // therefore completes zero-strobe writes locally with OKAY, which is their
  // AXI meaning, and never presents them to the core.
  /////////////////////////////////////////////////////////////////////////////

  tlul_pkg::tl_h2d_t tl_req;
  tlul_pkg::tl_d2h_t tl_resp;

  axi_lite_to_tlul #(
    .AXI_ADDR_WIDTH     (sep_io_pkg::ADDR_WIDTH),
    .AXI_DATA_WIDTH     (sep_io_pkg::DATA_WIDTH),
    .axi_lite_req_t     (sep_io_pkg::axil_req_t),
    .axi_lite_rsp_t     (sep_io_pkg::axil_resp_t),
    .AckZeroStrobeWrite (1'b1)
  ) u_spi_axi_lite_to_tlul (
    .clk_i          (clk_i),
    .rst_ni         (rst_ni),
    .axi_lite_req_i (axil_req_masked),
    .axi_lite_rsp_o (axil_resp_o),
    .tl_o           (tl_req),
    .tl_i           (tl_resp),
    // Sticky bridge fault. Held until reset; no consumer in sep_io today.
    .err_o          (),
    .err_clr_i      (1'b0)
  );

  /////////////////////////////////////////////////////////////////////////////
  // OpenTitan SPI Host core (unmodified upstream, TL-UL)
  /////////////////////////////////////////////////////////////////////////////

  logic intr_error;
  logic intr_spi_event;

  spi_host #(
    .NumCS      (NUM_CS),
    .EnableRacl (1'b0)
  ) u_spi_host (
    .clk_i            (clk_i),
    .rst_ni           (rst_ni),

    // Register interface
    .tl_i             (tl_req),
    .tl_o             (tl_resp),

    // Alerts: terminated, see header
    .alert_rx_i       ({spi_host_reg_pkg::NumAlerts{prim_alert_pkg::ALERT_RX_DEFAULT}}),
    .alert_tx_o       (),

    // RACL: compiled out
    .racl_policies_i  ('0),
    .racl_error_o     (),

    // SPI pads
    .cio_sck_o        (spi_sck_o),
    .cio_sck_en_o     (spi_sck_oe_o),
    .cio_csb_o        (spi_cs_no),
    .cio_csb_en_o     (spi_cs_oe_o),
    .cio_sd_o         (spi_sd_o),
    .cio_sd_en_o      (spi_sd_oe_o),
    .cio_sd_i         (spi_sd_i),

    // spi_device passthrough: not used in SEP
    .passthrough_i    (spi_device_pkg::PASSTHROUGH_REQ_DEFAULT),
    .passthrough_o    (),

    // DMA trigger
    .lsio_trigger_o   (lsio_trigger_o),

    // Interrupts
    .intr_error_o     (intr_error),
    .intr_spi_event_o (intr_spi_event)
  );

  /////////////////////////////////////////////////////////////////////////////
  // Outputs
  /////////////////////////////////////////////////////////////////////////////

  // One line into the SEP interrupt controller, as before. Software reads
  // INTR_STATE to tell the two sources apart.
  assign irq_o = intr_error | intr_spi_event;

endmodule : sep_ot_spi_wrap
