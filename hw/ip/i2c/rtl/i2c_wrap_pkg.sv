// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold address-map and AXI-Lite typedefs for the multi-instance I2C wrapper.
//
// Defines the 32-bit RegAddrWidth and data width, the axil request/response types used by
// i2c_wrap, the instance limit MaxNumI2cs that i2c_wrap asserts, and the default
// I2cInstanceSpacing.

package i2c_wrap_pkg;

  `include "axi/typedef.svh"

  ////////////////////////////////////
  // Register Interface Definitions //
  ////////////////////////////////////

  localparam int unsigned RegAddrWidth = 32;
  localparam int unsigned RegDataWidth = 32;
  localparam int unsigned RegStrbWidth = RegDataWidth / 8;

  typedef logic [RegAddrWidth-1:0] reg_addr_t;
  typedef logic [RegDataWidth-1:0] reg_data_t;
  typedef logic [RegStrbWidth-1:0] reg_strb_t;

  `AXI_LITE_TYPEDEF_ALL(axil, reg_addr_t, reg_data_t, reg_strb_t)


  //////////////////////////////
  // I2C Wrapper Definitions //
  //////////////////////////////

  localparam int unsigned MaxNumI2cs = 7;
  localparam int unsigned I2cInstanceSpacing = 32'h200;  // Address spacing between I2C instances.

endpackage
