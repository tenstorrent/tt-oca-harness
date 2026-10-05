// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold address-map constants for the multi-instance I3C core wrapper.
//
// Defines per-instance spacing and register address/data widths used by i3ccore_wrapper,
// the AXI-Lite axil request/response types, and MaxNumI3cs.

package i3ccore_wrap_pkg;

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


  /////////////////////////////////
  // I3C Core Wrapper Definitions //
  /////////////////////////////////

  localparam int unsigned MaxNumI3cs = 6;
  localparam int unsigned I3cInstanceSpacing = 32'h1000;  // Address spacing between I3C instances (I3CCSR rounds up to 0x1000).
  localparam int unsigned I3cRegAddrWidth = 12;  // Register address width per instance (0x1000).

endpackage
