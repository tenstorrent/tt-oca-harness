// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Define address-map constants and AXI-Lite typedefs for the multi-UART wrap.
//
// Defines the 32-bit csr_axil types, MaxNumUarts and the per-UART address spacing.

package uart_wrap_pkg;

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

  `AXI_LITE_TYPEDEF_ALL(csr_axil, reg_addr_t, reg_data_t, reg_strb_t)


  //////////////////////////////
  // UART Wrapper Definitions //
  //////////////////////////////

  localparam int unsigned MaxNumUarts = 4;
  localparam int unsigned UartLogEngineWrapSpacing = 32'h400; // Address spacing between UART instances.

endpackage
