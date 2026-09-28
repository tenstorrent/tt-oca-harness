// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Define AXI-Lite typedefs and constants for the cross-trigger port.
//
// ctp_axil_req_t and ctp_axil_resp_t type the CSR interface shared with the generated
// register block.

`ifndef CROSS_TRIGGER_PORT_PKG_SV
`define CROSS_TRIGGER_PORT_PKG_SV
import axi_pkg::*;
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
