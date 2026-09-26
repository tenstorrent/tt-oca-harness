// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold typedefs and AXI-Lite types for the OCTS system timer.
//
// Defines DATA_WIDTH and the axil request/response structs used by the wrapper.

package system_timer_octs_pkg;

  `include "axi/typedef.svh"

  ///////////////////////////
  // Bus Types Definitions //
  ///////////////////////////

  localparam int unsigned ADDR_WIDTH = 32;
  localparam int unsigned DATA_WIDTH = 32;
  localparam int unsigned STRB_WIDTH = DATA_WIDTH / 8;

  typedef logic [ADDR_WIDTH-1:0] addr_t;
  typedef logic [DATA_WIDTH-1:0] data_t;
  typedef logic [STRB_WIDTH-1:0] strb_t;

  `AXI_LITE_TYPEDEF_ALL(system_timer_octs_axil, addr_t, data_t, strb_t)

endpackage
