// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Define the operating modes and AXI-Lite typedefs for the cross-trigger port.
//
// ctp_axil_req_t and ctp_axil_resp_t type the CSR interface shared with the generated
// register block. The CSR selects only MODE_WIRE_OR and MODE_POINT_TO_POINT; MODE_TOGGLE is
// available only to a port core with a static configuration.

`ifndef CROSS_TRIGGER_PORT_PKG_SV
`define CROSS_TRIGGER_PORT_PKG_SV
package cross_trigger_port_pkg;

  `include "axi/typedef.svh"

  // Operating modes. The low bit matches the CONFIG.MODE CSR encoding. 2'b11 is not a mode.
  typedef enum logic [1:0] {
    MODE_WIRE_OR        = 2'b00,
    MODE_POINT_TO_POINT = 2'b01,
    MODE_TOGGLE         = 2'b10
  } ctp_mode_e;

  // AXI-Lite Parameters
  localparam int unsigned AxiLiteAddrWidth = 32;
  localparam int unsigned AxiLiteDataWidth = 32;
  localparam int unsigned AxiLiteStrbWidth = AxiLiteDataWidth / 8;

  // AXI-Lite Type Definitions
  typedef logic [AxiLiteAddrWidth-1:0] ctp_axil_addr_t;
  typedef logic [AxiLiteDataWidth-1:0] ctp_axil_data_t;
  typedef logic [AxiLiteStrbWidth-1:0] ctp_axil_strb_t;

  // Define AXI-Lite request/response structures
  `AXI_LITE_TYPEDEF_ALL(ctp_axil, ctp_axil_addr_t, ctp_axil_data_t, ctp_axil_strb_t)

endpackage : cross_trigger_port_pkg

`endif  // CROSS_TRIGGER_PORT_PKG_SV
