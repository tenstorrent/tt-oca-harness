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

  // Port counts, taken from the register map: one config register per CT_Src port
  // and one select bit per CT_Dst port. Resize the matrix by regenerating
  // regs/cross_trigger_matrix.rdl, not by overriding these.
  localparam int unsigned NUM_CT_SRC =
        int'(cross_trigger_matrix_addrmap_pkg::CROSS_TRIGGER_MATRIX_CT_SRC_NUM);
  localparam int unsigned NUM_CT_DST = int'(cross_trigger_matrix_reg_pkg::NUM_CT_DST);

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

`endif  // CROSS_TRIGGER_MATRIX_PKG_SV
