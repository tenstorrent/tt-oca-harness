// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold shared types and constants for the AVSBus controller.
//
// Defines the 32-bit address and data AXI-Lite typedefs for the controller CSR port, the
// matching APB typedefs, and the address-rule type for its axi_lite_to_apb bridge.

package avsbus_controller_pkg;

  `include "axi/typedef.svh"
  `include "apb/typedef.svh"

  //////////////////////////////
  // Register Bus Definitions //
  //////////////////////////////

  localparam int unsigned AddrWidth = 32;
  localparam int unsigned DataWidth = 32;
  localparam int unsigned StrbWidth = DataWidth / 8;

  typedef logic [AddrWidth-1:0] addr_t;
  typedef logic [DataWidth-1:0] data_t;
  typedef logic [StrbWidth-1:0] strb_t;

  `AXI_LITE_TYPEDEF_ALL(avsbus_axil, addr_t, data_t, strb_t)
  `APB_TYPEDEF_ALL(avsbus_apb, addr_t, data_t, strb_t)

  // Address decoder rule type for axi_lite_to_apb bridge
  typedef struct packed {
    int unsigned idx;
    addr_t start_addr;
    addr_t end_addr;
  } rule_t;

endpackage
