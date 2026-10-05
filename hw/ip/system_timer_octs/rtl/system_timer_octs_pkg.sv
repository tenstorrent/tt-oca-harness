// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold typedefs and AXI-Lite types for the OCTS system timer.
//
// Defines the 32-bit AddrWidth and DataWidth and the axil request/response structs used by
// the wrapper.

package system_timer_octs_pkg;

  `include "axi/typedef.svh"

  ///////////////////////////
  // Bus Types Definitions //
  ///////////////////////////

  localparam int unsigned AddrWidth = 32;
  localparam int unsigned DataWidth = 32;
  localparam int unsigned StrbWidth = DataWidth / 8;

  typedef logic [AddrWidth-1:0] addr_t;
  typedef logic [DataWidth-1:0] data_t;
  typedef logic [StrbWidth-1:0] strb_t;

  `AXI_LITE_TYPEDEF_ALL(system_timer_octs_axil, addr_t, data_t, strb_t)

endpackage
