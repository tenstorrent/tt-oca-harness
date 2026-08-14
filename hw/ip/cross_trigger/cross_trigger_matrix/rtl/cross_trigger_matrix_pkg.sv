// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Cross Trigger Matrix Package
//
// Description:
// Package containing types, parameters, and constants for the Cross Trigger Matrix
//------------------------------------------------------------------------------

`ifndef CROSS_TRIGGER_MATRIX_PKG_SV
`define CROSS_TRIGGER_MATRIX_PKG_SV

// Import AXI package (required for typedef macros)
import axi_pkg::*;
// Include AXI typedef macros

package cross_trigger_matrix_pkg;

    `include "axi/typedef.svh"

    // Default parameters
    localparam int unsigned DEFAULT_NUM_CT_SRC = 26;
    localparam int unsigned DEFAULT_NUM_CT_DST = 26;

    // Parameter constraints
    localparam int unsigned MIN_NUM_CT_SRC = 1;
    localparam int unsigned MAX_NUM_CT_SRC = 64;
    localparam int unsigned MIN_NUM_CT_DST = 1;
    // 64 select bits fill the 8 bytes each CT_Src port occupies in the register map.
    localparam int unsigned MAX_NUM_CT_DST = 64;

    // AXI-Lite Parameters
    localparam int unsigned AXI_LITE_ADDR_WIDTH = 32;
    localparam int unsigned AXI_LITE_DATA_WIDTH = 32;
    localparam int unsigned AXI_LITE_STRB_WIDTH = AXI_LITE_DATA_WIDTH / 8;

    // AXI-Lite Type Definitions
    typedef logic [AXI_LITE_ADDR_WIDTH-1:0] ctm_axil_addr_t;
    typedef logic [AXI_LITE_DATA_WIDTH-1:0] ctm_axil_data_t;
    typedef logic [AXI_LITE_STRB_WIDTH-1:0] ctm_axil_strb_t;

    // Define AXI-Lite request/response structures
    `AXI_LITE_TYPEDEF_ALL(ctm_axil, ctm_axil_addr_t, ctm_axil_data_t, ctm_axil_strb_t)

endpackage : cross_trigger_matrix_pkg

`endif // CROSS_TRIGGER_MATRIX_PKG_SV
