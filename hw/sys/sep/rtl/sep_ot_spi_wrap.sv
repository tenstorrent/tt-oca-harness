// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Bridge AXI4-Lite onto the OpenTitan spi_host TL-UL register interface.
//
// Follows the crypto-accelerator pattern: unmodified spi_host on native TL-UL, with
// axi_lite_to_tlul presenting the 32-bit AXI4-Lite bus from sep_io.
// Addresses are rebased by the SPI controller base and masked to the 6-bit spi_host window.
// Writes with all byte strobes low complete locally with OKAY and never reach the core.
//
// The upstream REGGEN block is authoritative for the register map:
//
// - INTR_STATE is RW1C.
// - INTR_ENABLE gates only the interrupt output.
// - INTR_TEST is a write pulse.
//
// irq_o is the OR of the core's error and spi_event lines. lsio_trigger_o is passed
// through. There is no busy output; activity is STATUS.ACTIVE over the register interface.
//
// RACL is compiled out (EnableRacl = 0) with inactive policies. The spi_device passthrough
// is held inactive. The single fatal alert (bus integrity) ends at a local
// prim_alert_receiver. bus_err_o is the OR of the bridge's sticky fault and a latch of that
// receiver's alert pulse and integrity fail; bus_err_clr_i clears both, and a fault in the
// same cycle still latches.
//
// Supports:
//
// - A configurable number of chip selects (default 1).
// - Up to Quad SPI.
// - Single transfer rate only (no DTR/DDR).
// - Software-driven command sequences without memory-mapped XIP flash access.

`include "ocah_registers.svh"

module sep_ot_spi_wrap #(
  parameter int unsigned NUM_CS = 1  // Number of SPI chip selects.
) (
  input  logic clk_i,                         // System clock.
  input  logic rst_ni,                        // Active-low reset.

  input  logic test_en_i,                     // DFT test-enable (scan-enable).

  input  sep_io_pkg::axil_req_t  axil_req_i,  // spi_host register request for the
                                              // 2^spi_host_reg_pkg::BlockAw bytes from
                                              // SEP_TOP_SPI_CONTROLLER_BASE_ADDR.
  output sep_io_pkg::axil_resp_t axil_resp_o,  // spi_host register response from the TL-UL bridge.

  output logic              spi_sck_o,        // SPI serial clock to the pad.
  output logic              spi_sck_oe_o,     // Output enable for the SPI serial clock pad,
                                              // active-high.

  output logic [NUM_CS-1:0] spi_cs_no,        // Active-low chip selects to the pads.
  output logic [NUM_CS-1:0] spi_cs_oe_o,      // Output enables for the chip-select pads,
                                              // active-high.

  output logic [3:0]        spi_sd_o,         // Output data on the four SPI data lanes.
  output logic [3:0]        spi_sd_oe_o,      // Per-lane output enables for the SPI data pads,
                                              // active-high.
  input  logic [3:0]        spi_sd_i,         // Input data from the four SPI data lanes.

  output logic              irq_o,            // SPI interrupt: OR of the spi_host error and
                                              // spi_event interrupts.
  output logic              lsio_trigger_o,   // spi_host DMA trigger, passed through.

  output logic              bus_err_o,        // Register-bridge TL-UL error response or fatal
                                              // alert; sticky until bus_err_clr_i.
  input  logic              bus_err_clr_i     // Single-cycle clear for bus_err_o, pulsed by
                                              // PERIPH_BUS_ERR_CLEAR.spi in sep.
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
  localparam logic [sep_io_pkg::AddrWidth-1:0] SpiAddrMask =
      sep_io_pkg::AddrWidth'((1 << SpiBlockAw) - 1);
  localparam logic [sep_io_pkg::AddrWidth-1:0] SpiBaseLower =
      sep_io_pkg::AddrWidth'(sep_top_addrmap_pkg::SEP_TOP_SPI_CONTROLLER_BASE_ADDR)
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
  // ACK_ZERO_STROBE_WRITE: the SEP crossbar is 64 bits wide and this block sits
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
  logic              bridge_err;

  axi_lite_to_tlul #(
    .AXI_ADDR_WIDTH        (sep_io_pkg::AddrWidth),
    .AXI_DATA_WIDTH        (sep_io_pkg::DataWidth),
    .axi_lite_req_t        (sep_io_pkg::axil_req_t),
    .axi_lite_rsp_t        (sep_io_pkg::axil_resp_t),
    .ACK_ZERO_STROBE_WRITE (1'b1)
  ) u_spi_axi_lite_to_tlul (
    .clk_i          (clk_i),
    .rst_ni         (rst_ni),
    .axi_lite_req_i (axil_req_masked),
    .axi_lite_rsp_o (axil_resp_o),
    .tl_o           (tl_req),
    .tl_i           (tl_resp),
    .err_o          (bridge_err),
    .err_clr_i      (bus_err_clr_i)
  );

  /////////////////////////////////////////////////////////////////////////////
  // OpenTitan SPI Host core (unmodified upstream, TL-UL)
  /////////////////////////////////////////////////////////////////////////////

  localparam int unsigned NumAlerts = spi_host_reg_pkg::NumAlerts;

  logic intr_error;
  logic intr_spi_event;

  prim_alert_pkg::alert_tx_t [NumAlerts-1:0] alert_tx;
  prim_alert_pkg::alert_rx_t [NumAlerts-1:0] alert_rx;
  logic [NumAlerts-1:0]                      alert_pulse;
  logic [NumAlerts-1:0]                      alert_integ_fail;

  spi_host #(
    .AlertAsyncOn    ({NumAlerts{1'b0}}),
    .AlertSkewCycles (1),
    .NumCS           (NUM_CS),
    .EnableRacl      (1'b0)
  ) u_spi_host (
    .clk_i            (clk_i),
    .rst_ni           (rst_ni),

    // Register interface
    .tl_i             (tl_req),
    .tl_o             (tl_resp),

    .alert_rx_i       (alert_rx),
    .alert_tx_o       (alert_tx),

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

  for (genvar i = 0; i < NumAlerts; i++) begin : gen_alert_receivers
    prim_alert_receiver #(
      .AsyncOn   (1'b0),
      .SkewCycles(1)
    ) u_alert_receiver (
      .clk_i,
      .rst_ni,
      .init_trig_i  (prim_mubi_pkg::MuBi4False),
      .ping_req_i   (1'b0),
      .ping_ok_o    (),
      .integ_fail_o (alert_integ_fail[i]),
      .alert_o      (alert_pulse[i]),
      .alert_rx_o   (alert_rx[i]),
      .alert_tx_i   (alert_tx[i])
    );
  end

  /////////////////////////////////////////////////////////////////////////////
  // Outputs
  /////////////////////////////////////////////////////////////////////////////

  logic alert_err_q;
  `OCAH_FF(alert_err_q, (alert_err_q & ~bus_err_clr_i) | (|alert_pulse) | (|alert_integ_fail),
           1'b0, clk_i, rst_ni)

  assign bus_err_o = bridge_err | alert_err_q;

  // One line into the SEP interrupt controller, as before. Software reads
  // INTR_STATE to tell the two sources apart.
  assign irq_o = intr_error | intr_spi_event;

endmodule : sep_ot_spi_wrap
