// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//-----------------------------------------------------------------------------
// I3C Core Wrapper Package
//
//-----------------------------------------------------------------------------

package i3ccore_wrap_pkg;

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


  /////////////////////////////////
  // I3C Core Wrapper Definitions //
  /////////////////////////////////

  localparam int unsigned MAX_NUM_I3CS = 6;
  localparam int unsigned I3C_INSTANCE_SPACING = 32'h500;  // Address spacing between I3C instances
  localparam int unsigned I3C_REG_ADDR_WIDTH = 11;  // Register address width per instance

endpackage
