// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Cross Trigger Port Package
//
// Description:
// Package containing types, parameters, and constants for the Cross Trigger Port
//------------------------------------------------------------------------------

`ifndef CROSS_TRIGGER_PORT_PKG_SV
`define CROSS_TRIGGER_PORT_PKG_SV

// Import AXI package (required for typedef macros)
import axi_pkg::*;
// Include AXI typedef macros

package cross_trigger_port_pkg;

  `include "axi/typedef.svh"

  // Operating modes
  typedef enum logic {
    MODE_WIRE_OR        = 1'b0,
    MODE_POINT_TO_POINT = 1'b1
  } ctp_mode_e;

  // AXI-Lite Parameters
  localparam int unsigned AXI_LITE_ADDR_WIDTH = 32;
  localparam int unsigned AXI_LITE_DATA_WIDTH = 32;
  localparam int unsigned AXI_LITE_STRB_WIDTH = AXI_LITE_DATA_WIDTH / 8;

  // AXI-Lite Type Definitions
  typedef logic [AXI_LITE_ADDR_WIDTH-1:0] ctp_axil_addr_t;
  typedef logic [AXI_LITE_DATA_WIDTH-1:0] ctp_axil_data_t;
  typedef logic [AXI_LITE_STRB_WIDTH-1:0] ctp_axil_strb_t;

  // Define AXI-Lite request/response structures
  `AXI_LITE_TYPEDEF_ALL(ctp_axil, ctp_axil_addr_t, ctp_axil_data_t, ctp_axil_strb_t)

endpackage : cross_trigger_port_pkg

`endif  // CROSS_TRIGGER_PORT_PKG_SV
