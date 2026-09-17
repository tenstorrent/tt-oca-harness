// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Cross Trigger Network Package
//
// Description:
// Package containing types, parameters, and constants for the Cross Trigger Network

`ifndef CROSS_TRIGGER_NETWORK_PKG_SV
`define CROSS_TRIGGER_NETWORK_PKG_SV

// Import AXI package (required for typedef macros)
import axi_pkg::*;
import cross_trigger_network_addrmap_pkg::*;
// Include AXI typedef macros

package cross_trigger_network_pkg;

  `include "axi/typedef.svh"

  // Default parameters; keep in step with dtp_pkg when used inside the DTP
  localparam int unsigned DEFAULT_NUM_CTP = 16;  // Number of external CTPs
  localparam int unsigned DEFAULT_NUM_INT_CT = 10;  // Number of internal CTPs
  localparam int unsigned DEFAULT_NUM_CLK_STOP_REQ = 9;  // Number of clock stop requests

  // Parameter constraints
  localparam int unsigned MIN_NUM_CTP = 1;
  localparam int unsigned MAX_NUM_CTP = 32;
  localparam int unsigned MIN_NUM_INT_CT = 0;
  localparam int unsigned MAX_NUM_INT_CT = 32;

  // Address space configuration
  // CTM gets 512 bytes (0x200) - enough for up to 64 CT_SRC register pairs (64 * 8 bytes)
  // Each CT_SRC uses 8 bytes (CONFIG_0 + CONFIG_1) to support up to 64 CT_DST ports
  // Each CTP gets 16 bytes (0x10) - enough for 3 registers (CONFIG, STATUS, STRETCH_MULT)
  localparam int unsigned CSR_ADDR_CTM_SIZE = int'(CROSS_TRIGGER_NETWORK_CTP_BASE_ADDR(0));
  localparam int unsigned CSR_ADDR_CTP_SIZE = int'(CROSS_TRIGGER_NETWORK_CTP_STRIDE);

  // AXI-Lite Parameters
  localparam int unsigned AXI_LITE_ADDR_WIDTH = 32;
  localparam int unsigned AXI_LITE_DATA_WIDTH = 32;
  localparam int unsigned AXI_LITE_STRB_WIDTH = AXI_LITE_DATA_WIDTH / 8;

  // AXI-Lite Type Definitions
  typedef logic [AXI_LITE_ADDR_WIDTH-1:0] ctn_axil_addr_t;
  typedef logic [AXI_LITE_DATA_WIDTH-1:0] ctn_axil_data_t;
  typedef logic [AXI_LITE_STRB_WIDTH-1:0] ctn_axil_strb_t;

  // Define AXI-Lite request/response structures
  `AXI_LITE_TYPEDEF_ALL(ctn_axil, ctn_axil_addr_t, ctn_axil_data_t, ctn_axil_strb_t)

  // Function to calculate the number of master ports for the AXI-Lite crossbar
  // NUM_CTP external CTPs + 1 CTM
  function automatic int unsigned calc_num_xbar_mst_ports(int unsigned num_ctp);
    return num_ctp + 1;  // External CTPs + CTM
  endfunction

  // Function to calculate the total number of CTM ports
  // NUM_CTP external + NUM_INT_CT internal
  // cast to 32 bits to avoid lint issues since integer tytpe is 32 bits (32bits + 32bits requires 33rd bit to prevent overflow, not realistic here)
  function automatic int unsigned calc_num_ctm_ports(int unsigned num_ctp, int unsigned num_int_ct);
    return 32'(num_ctp + num_int_ct);
  endfunction

  // Function to calculate the CTM base address (CTM is at address 0)
  function automatic logic [AXI_LITE_ADDR_WIDTH-1:0] calc_ctm_base_addr(int unsigned num_ctp);
    return AXI_LITE_ADDR_WIDTH'(CROSS_TRIGGER_NETWORK_CTM_BASE_ADDR);
  endfunction

  // Function to calculate CTP base address (CTPs start after CTM)
  function automatic logic [AXI_LITE_ADDR_WIDTH-1:0] calc_ctp_base_addr(int unsigned ctp_idx);
    return AXI_LITE_ADDR_WIDTH'(CROSS_TRIGGER_NETWORK_CTP_BASE_ADDR(ctp_idx));
  endfunction

endpackage : cross_trigger_network_pkg

`endif  // CROSS_TRIGGER_NETWORK_PKG_SV
