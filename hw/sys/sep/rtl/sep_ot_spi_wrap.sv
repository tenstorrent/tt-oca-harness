// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP OpenTitan SPI Controller Wrapper
//
// Wrapper for the modified OpenTitan SPI Host IP (spi_controller)
// that uses AXI4-Lite instead of TileLink.
//
// This module encapsulates:
// - spi_controller (modified OpenTitan SPI Host with AXI4-Lite interface)
//
// The spi_controller is a software-controlled SPI controller that uses
// FIFO-based command/data transfer. It does NOT support direct
// memory-mapped flash access.
//
// Features:
// - Configurable number of chip selects (default: 1)
// - Up to Quad SPI (4-bit data width)
// - Single Transfer Rate (STR) only (no DTR/DDR support)
// - Software-driven command sequences
// - AXI4-Lite register interface (no TileLink)

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
  output logic              irq_o,     // interrupt
  output logic              busy_o,          // Controller busy (active transaction)
  output logic              lsio_trigger_o    // DMA trigger
);

  /////////////////////////////////////////////////////////////////////////////
  // Signal Declarations
  /////////////////////////////////////////////////////////////////////////////

  // Internal AXI-Lite signals (spi_controller uses its own pkg types)
  spi_controller_pkg::axil_req_t  spi_ctrl_axil_req;
  spi_controller_pkg::axil_resp_t spi_ctrl_axil_resp;

  /////////////////////////////////////////////////////////////////////////////
  // AXI-Lite Interface Conversion
  // Convert from sep_io_pkg types to spi_controller_pkg types
  /////////////////////////////////////////////////////////////////////////////

  // The spi_controller uses a narrower address width based on its register map
  // We need to map the wider sep_io address to the narrower spi_controller address

  always_comb begin
    // AW channel
    spi_ctrl_axil_req.aw_valid = axil_req_i.aw_valid;
    spi_ctrl_axil_req.aw.addr  = axil_req_i.aw.addr[spi_controller_pkg::REG_ADDR_WIDTH-1:0];
    spi_ctrl_axil_req.aw.prot  = axil_req_i.aw.prot;

    // W channel
    spi_ctrl_axil_req.w_valid  = axil_req_i.w_valid;
    spi_ctrl_axil_req.w.data   = axil_req_i.w.data;
    spi_ctrl_axil_req.w.strb   = axil_req_i.w.strb;

    // B channel
    spi_ctrl_axil_req.b_ready  = axil_req_i.b_ready;

    // AR channel
    spi_ctrl_axil_req.ar_valid = axil_req_i.ar_valid;
    spi_ctrl_axil_req.ar.addr  = axil_req_i.ar.addr[spi_controller_pkg::REG_ADDR_WIDTH-1:0];
    spi_ctrl_axil_req.ar.prot  = axil_req_i.ar.prot;

    // R channel
    spi_ctrl_axil_req.r_ready  = axil_req_i.r_ready;
  end

  always_comb begin
    // AW channel
    axil_resp_o.aw_ready = spi_ctrl_axil_resp.aw_ready;

    // W channel
    axil_resp_o.w_ready  = spi_ctrl_axil_resp.w_ready;

    // B channel
    axil_resp_o.b_valid  = spi_ctrl_axil_resp.b_valid;
    axil_resp_o.b.resp   = spi_ctrl_axil_resp.b.resp;

    // AR channel
    axil_resp_o.ar_ready = spi_ctrl_axil_resp.ar_ready;

    // R channel
    axil_resp_o.r_valid  = spi_ctrl_axil_resp.r_valid;
    axil_resp_o.r.data   = spi_ctrl_axil_resp.r.data;
    axil_resp_o.r.resp   = spi_ctrl_axil_resp.r.resp;
  end

  /////////////////////////////////////////////////////////////////////////////
  // SPI Controller (Modified OpenTitan SPI Host with AXI4-Lite)
  /////////////////////////////////////////////////////////////////////////////

  spi_controller #(
    .NUM_CS         (NUM_CS),
    .BYTE_ORDER     (spi_controller_pkg::LITTLE_ENDIAN),
    .TX_FIFO_DEPTH  (72),
    .RX_FIFO_DEPTH  (64),
    .CMD_FIFO_DEPTH (4)
  ) u_spi_controller (
    .clk_i,
    .rst_ni,

    // AXI4-Lite Register Interface
    .axil_req_i  (spi_ctrl_axil_req),
    .axil_resp_o (spi_ctrl_axil_resp),

    // SPI Interface
    .sck_o       (spi_sck_o),
    .sck_en_o    (spi_sck_oe_o),
    .cs_no       (spi_cs_no),
    .cs_en_o     (spi_cs_oe_o),
    .io_o        (spi_sd_o),
    .io_en_o     (spi_sd_oe_o),
    .io_i        (spi_sd_i),

    // DMA Interface
    .lsio_trigger_o (lsio_trigger_o),

    // Interrupt Interface
    .irq_o       (irq_o),

    // Status Interface
    .busy_o      (busy_o)
  );

endmodule
