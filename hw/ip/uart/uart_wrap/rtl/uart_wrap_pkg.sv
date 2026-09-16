// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// UART Wrapper Package
//
//-----------------------------------------------------------------------------

package uart_wrap_pkg;

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

  `AXI_LITE_TYPEDEF_ALL(csr_axil, reg_addr_t, reg_data_t, reg_strb_t)


  //////////////////////////////
  // UART Wrapper Definitions //
  //////////////////////////////

  localparam int unsigned MAX_NUM_UARTS = 4;
  localparam int unsigned UART_LOG_ENGINE_WRAP_SPACING = 32'h400; // Address spacing between UART instances

endpackage
