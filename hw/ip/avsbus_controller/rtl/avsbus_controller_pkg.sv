// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// AVSBus Package
//
//-----------------------------------------------------------------------------

package avsbus_controller_pkg;

  `include "axi/typedef.svh"
  `include "apb/typedef.svh"

  //////////////////////////////
  // Register Bus Definitions //
  //////////////////////////////

  localparam int unsigned ADDR_WIDTH = 32;
  localparam int unsigned DATA_WIDTH = 32;
  localparam int unsigned STRB_WIDTH = DATA_WIDTH / 8;

  typedef logic [ADDR_WIDTH-1:0] addr_t;
  typedef logic [DATA_WIDTH-1:0] data_t;
  typedef logic [STRB_WIDTH-1:0] strb_t;

  `AXI_LITE_TYPEDEF_ALL(avsbus_axil, addr_t, data_t, strb_t)
  `APB_TYPEDEF_ALL(avsbus_apb, addr_t, data_t, strb_t)

  // Address decoder rule type for axi_lite_to_apb bridge
  typedef struct packed {
    int unsigned idx;
    addr_t start_addr;
    addr_t end_addr;
  } rule_t;

endpackage
