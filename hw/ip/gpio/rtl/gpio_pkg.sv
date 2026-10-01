// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold GPIO AXI-Lite typedefs and shared parameters.
//
// Defines the 32-bit address and data widths and the AXI-Lite request/response structs used
// by gpio, gpio_filter and gpio_shim.

package gpio_pkg;

  `include "axi/typedef.svh"

  ///////////////////////////
  // Bus Types Definitions //
  ///////////////////////////

  localparam int unsigned ADDR_WIDTH = 32;
  localparam int unsigned DATA_WIDTH = 32;
  localparam int unsigned STRB_WIDTH = DATA_WIDTH / 8;

  typedef logic [ADDR_WIDTH    -1:0] addr_t;
  typedef logic [DATA_WIDTH    -1:0] data_t;
  typedef logic [STRB_WIDTH    -1:0] strb_t;
  `AXI_LITE_TYPEDEF_ALL(gpio_axil, addr_t, data_t, strb_t)

endpackage
