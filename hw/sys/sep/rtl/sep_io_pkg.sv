// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP IO submodule typedefs and parameters

package sep_io_pkg;

  localparam int unsigned ADDR_WIDTH = 32;
  localparam int unsigned DATA_WIDTH = 32;
  localparam int unsigned STRB_WIDTH = DATA_WIDTH / 8;

  typedef logic [ADDR_WIDTH-1:0] addr_t;
  typedef logic [DATA_WIDTH-1:0] data_t;
  typedef logic [STRB_WIDTH-1:0] strb_t;

  `AXI_TYPEDEF_ALL(axi, addr_t, sep_pkg::sep_io_axi_id_t, data_t, strb_t,
                   sep_pkg::sep_io_axi_user_t)
  `AXI_LITE_TYPEDEF_ALL(axil, addr_t, data_t, strb_t)

  //=========================================================================
  // SPI Interface Types
  // Uses active-low OE/IE (_n suffix) to match tt_sep and smc_padring
  // Carries OE separately so a PHY that derives IE internally can ignore it
  // Quad SPI: 4 data lines (sd[3:0])
  //=========================================================================

  typedef struct packed {
    // Clock (directly active)
    logic       sck;
    logic       sck_oe;

    // Chip Select (directly active-low)
    logic       cs_n;
    logic       cs_oe;

    // Data (directly active signals) - 4 lanes (Quad SPI)
    logic [3:0] sd;
    logic [3:0] sd_oe;

    // Interrupt
    logic       irq;

    // DMA trigger
    logic        lsio_trigger;
  } sep_io_spi_req_t;

  typedef struct packed {
    // Data input from pad (4 lanes, Quad SPI)
    logic [3:0] sd;
  } sep_io_spi_rsp_t;

endpackage
