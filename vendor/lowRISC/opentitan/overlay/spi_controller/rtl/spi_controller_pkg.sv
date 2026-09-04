//-----------------------------------------------------------------------------
// SPI Controller Package
//
// Copyright 2025 Tenstorrent Inc.
//-----------------------------------------------------------------------------

// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0
//
// Command & Configuration Options structure for SPI HOST.
//

package spi_controller_pkg;

  `include "axi/typedef.svh"

  ////////////////////////////////////
  // Register Interface Definitions //
  ////////////////////////////////////

  localparam int unsigned REG_ADDR_WIDTH =
        spi_controller_reg_pkg::SPI_CONTROLLER_REG_MIN_ADDR_WIDTH;
  localparam int unsigned REG_DATA_WIDTH = 32;
  localparam int unsigned REG_STRB_WIDTH = REG_DATA_WIDTH / 8;

  typedef logic [REG_ADDR_WIDTH-1:0] reg_addr_t;
  typedef logic [REG_DATA_WIDTH-1:0] reg_data_t;
  typedef logic [REG_STRB_WIDTH-1:0] reg_strb_t;

  `AXI_LITE_TYPEDEF_ALL(axil, reg_addr_t, reg_data_t, reg_strb_t)


  ////////////////////////////////
  // SPI Controller Definitions //
  ////////////////////////////////

  typedef enum logic {
    BIG_ENDIAN    = 1'b0,
    LITTLE_ENDIAN = 1'b1
  } byte_order_e;

  // For decoding the direction register
  typedef enum logic [1:0] {
    Dummy  = 2'b00,
    RdOnly = 2'b01,
    WrOnly = 2'b10,
    Bidir  = 2'b11
  } reg_direction_t;

  // For decoding the direction register
  typedef enum logic [1:0] {
    Standard = 2'b00,
    Dual     = 2'b01,
    Quad     = 2'b10,
    RsvdSpd  = 2'b11
  } speed_t;

  typedef struct packed {
    logic [15:0] clkdiv;
    logic [3:0]  csnidle;
    logic [3:0]  csnlead;
    logic [3:0]  csntrail;
    logic        full_cyc;
    logic        cpha;
    logic        cpol;
  } configopts_t;

  typedef struct packed {
    logic [1:0]  speed;
    logic        cmd_wr_en;
    logic        cmd_rd_en;
    logic [19:0] len;
    logic        csaat;
  } segment_t;

  typedef struct packed {
    segment_t segment;
    configopts_t configopts;
  } command_t;

endpackage
