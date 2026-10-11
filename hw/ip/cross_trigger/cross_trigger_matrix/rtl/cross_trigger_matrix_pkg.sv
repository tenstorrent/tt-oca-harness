// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Define types, port counts, and AXI-Lite typedefs for the cross-trigger matrix.
//
// NumCtSrc and NumCtDst match the generated RDL geometry.
// ctm_axil_req_t and ctm_axil_resp_t type the CSR port.

`ifndef CROSS_TRIGGER_MATRIX_PKG_SV
`define CROSS_TRIGGER_MATRIX_PKG_SV
import axi_pkg::data_t;
import axi_pkg::strb_t;
package cross_trigger_matrix_pkg;

  `include "axi/typedef.svh"

  // Port counts, taken from the register map: one config register per CT_Src port
  // and one select bit per CT_Dst port. Resize the matrix by regenerating
  // regs/cross_trigger_matrix.rdl, not by overriding these.
  localparam int unsigned NumCtSrc =
        int'(cross_trigger_matrix_addrmap_pkg::CROSS_TRIGGER_MATRIX_CT_SRC_NUM);
  localparam int unsigned NumCtDst = int'(cross_trigger_matrix_reg_pkg::NUM_CT_DST);

  // AXI-Lite Parameters
  localparam int unsigned AxiLiteAddrWidth = 32;
  localparam int unsigned AxiLiteDataWidth = 32;
  localparam int unsigned AxiLiteStrbWidth = AxiLiteDataWidth / 8;

  // AXI-Lite Type Definitions
  typedef logic [AxiLiteAddrWidth-1:0] ctm_axil_addr_t;
  typedef logic [AxiLiteDataWidth-1:0] ctm_axil_data_t;
  typedef logic [AxiLiteStrbWidth-1:0] ctm_axil_strb_t;

  // Define AXI-Lite request/response structures
  `AXI_LITE_TYPEDEF_ALL(ctm_axil, ctm_axil_addr_t, ctm_axil_data_t, ctm_axil_strb_t)

endpackage : cross_trigger_matrix_pkg

`endif  // CROSS_TRIGGER_MATRIX_PKG_SV
