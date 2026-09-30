// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Define typedefs and parameters for the SEP IO subsystem.
//
// AXI-Lite and SPI request/response structs are shared by sep_io and sep_ot_spi_wrap.

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

  //=========================================================================
  // Pad-facing SPI signals
  // smu.sv and the SEP standalone bench both map sep_io_spi_req_t onto these
  // same signals, the bench without smu.sv in the hierarchy, so the mapping
  // lives here rather than in either of them.
  //=========================================================================

  typedef struct packed {
    logic       enable;
    logic       clk;
    logic [7:0] txd;
    logic       cs_n;
    logic       cs_oe_n;
    logic       cs_ie_n;
    logic       clk_oe_n;
    logic       clk_ie_n;
    logic       dqs_oe_n;
    logic       dqs_ie_n;
    logic [7:0] dq_oe_n;
    logic [7:0] dq_ie_n;
    logic       mem_rebar_oepad;
    logic       mem_rebar_opad;
    logic       mem_rebar_iepad;
  } sep_io_spi_pads_t;

  function automatic sep_io_spi_pads_t ot_spi_pad_map(input sep_io_spi_req_t req);
    ot_spi_pad_map = '{
        enable          : 1'b1,
        clk             : req.sck,
        txd             : {4'b0, req.sd},
        cs_n            : req.cs_n,
        cs_oe_n         : ~req.cs_oe,
        cs_ie_n         : req.cs_oe,
        clk_oe_n        : ~req.sck_oe,
        clk_ie_n        : req.sck_oe,
        dqs_oe_n        : 1'b1,
        dqs_ie_n        : 1'b1,
        dq_oe_n         : {4'hF, ~req.sd_oe},
        dq_ie_n         : {4'hF, req.sd_oe},
        mem_rebar_oepad : 1'b0,
        mem_rebar_opad  : 1'b0,
        mem_rebar_iepad : 1'b0
    };
  endfunction

endpackage
