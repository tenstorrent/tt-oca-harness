// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold address-map and AXI-Lite typedefs for the multi-instance I2C wrapper.
//
// Defines the 32-bit REG_ADDR_WIDTH and data width, the axil request/response types used by
// i2c_wrap, the instance limit MAX_NUM_I2CS that i2c_wrap asserts, and the default
// I2C_INSTANCE_SPACING.

package i2c_wrap_pkg;

  `include "axi/typedef.svh"

  ////////////////////////////////////
  // Register Interface Definitions //
  ////////////////////////////////////

  localparam int unsigned REG_ADDR_WIDTH = 32;
  localparam int unsigned REG_DATA_WIDTH = 32;
  localparam int unsigned REG_STRB_WIDTH = REG_DATA_WIDTH / 8;

  typedef logic [REG_ADDR_WIDTH-1:0] reg_addr_t;
  typedef logic [REG_DATA_WIDTH-1:0] reg_data_t;
  typedef logic [REG_STRB_WIDTH-1:0] reg_strb_t;

  `AXI_LITE_TYPEDEF_ALL(axil, reg_addr_t, reg_data_t, reg_strb_t)


  //////////////////////////////
  // I2C Wrapper Definitions //
  //////////////////////////////

  localparam int unsigned MAX_NUM_I2CS = 7;
  localparam int unsigned I2C_INSTANCE_SPACING = 32'h200;  // Address spacing between I2C instances.

endpackage
