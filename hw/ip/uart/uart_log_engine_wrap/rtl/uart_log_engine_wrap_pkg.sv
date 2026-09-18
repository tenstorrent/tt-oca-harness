// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// UART & Log Engine Wrapper Package
//
//-----------------------------------------------------------------------------

package uart_log_engine_wrap_pkg;

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
  // Register Map Definitions //
  //////////////////////////////

  localparam int unsigned NUM_REG_MAPS = 4;

  typedef enum logic [$clog2(
NUM_REG_MAPS
)-1:0] {
    UART_REG_MAP       = 2'd0,
    LOG_ENGINE_REG_MAP = 2'd1,
    CTRL_REG_MAP       = 2'd2,
    UNDEFINED_REG_MAP  = 2'd3
  } uart_log_engine_wrap_reg_map_e;

endpackage
