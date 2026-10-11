// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Define defaults and AXI-Lite typedefs for the cross-trigger network.
//
// DefaultNumCtp, DefaultNumIntCt, and DefaultNumClkStopReq size the network.
// ctn_axil_req_t and ctn_axil_resp_t type the CSR subordinate port.

`ifndef CROSS_TRIGGER_NETWORK_PKG_SV
`define CROSS_TRIGGER_NETWORK_PKG_SV

package cross_trigger_network_pkg;

  import axi_pkg::data_t;
  import axi_pkg::strb_t;

  `include "axi/typedef.svh"

  // Default parameters; keep in step with dtp_pkg when used inside the DTP
  localparam int unsigned DefaultNumCtp = 16;  // Number of external CTPs.
  localparam int unsigned DefaultNumIntCt = 10;  // Number of internal CTPs.
  localparam int unsigned DefaultNumClkStopReq = 9;  // Number of clock stop requests.

  // Parameter constraints
  localparam int unsigned MinNumCtp = 1;
  localparam int unsigned MaxNumCtp = 32;
  localparam int unsigned MinNumIntCt = 0;
  localparam int unsigned MaxNumIntCt = 32;

  // Address space configuration
  // CTM gets 512 bytes (0x200) - enough for up to 64 CT_SRC ports (64 * 8 bytes)
  // Each CT_SRC uses one 8-byte CONFIG_0 slot, 32 bits wide for up to 32 CT_DST ports
  // and 64 bits wide for up to 64
  // Each CTP gets 16 bytes (0x10) - enough for 3 registers (CONFIG, STATUS, STRETCH_MULT)
  // verilog_format: off  // verible explodes this qualified call's argument list
  localparam int unsigned CsrAddrCtmSize =
      int'(cross_trigger_network_addrmap_pkg::CROSS_TRIGGER_NETWORK_CTP_BASE_ADDR(0));
  // verilog_format: on
  // Bytes of the CTM aperture its register map decodes; the rest of the aperture is unmapped.
  localparam int unsigned CsrAddrCtmRegSize =
      int'(cross_trigger_network_addrmap_pkg::CROSS_TRIGGER_NETWORK_CTM_SIZE);
  localparam int unsigned CsrAddrCtpSize =
      int'(cross_trigger_network_addrmap_pkg::CROSS_TRIGGER_NETWORK_CTP_STRIDE);

  // AXI-Lite Parameters
  localparam int unsigned AxiLiteAddrWidth = 32;
  localparam int unsigned AxiLiteDataWidth = 32;
  localparam int unsigned AxiLiteStrbWidth = AxiLiteDataWidth / 8;

  // AXI-Lite Type Definitions
  typedef logic [AxiLiteAddrWidth-1:0] ctn_axil_addr_t;
  typedef logic [AxiLiteDataWidth-1:0] ctn_axil_data_t;
  typedef logic [AxiLiteStrbWidth-1:0] ctn_axil_strb_t;

  // Define AXI-Lite request/response structures
  `AXI_LITE_TYPEDEF_ALL(ctn_axil, ctn_axil_addr_t, ctn_axil_data_t, ctn_axil_strb_t)

  // Function to calculate the number of master ports for the AXI-Lite crossbar
  // NUM_CTP external CTPs + 1 CTM
  function automatic int unsigned calc_num_xbar_mst_ports(int unsigned num_ctp);
    return num_ctp + 1;  // External CTPs + CTM.
  endfunction

  // Function to calculate the total number of CTM ports
  // NUM_CTP external + NUM_INT_CT internal
  // cast to 32 bits to avoid lint issues since integer type is 32 bits (32bits + 32bits requires 33rd bit to prevent overflow, not realistic here)
  function automatic int unsigned calc_num_ctm_ports(int unsigned num_ctp, int unsigned num_int_ct);
    return 32'(num_ctp + num_int_ct);
  endfunction

  // Function to calculate the CTM base address (CTM is at address 0)
  function automatic logic [AxiLiteAddrWidth-1:0] calc_ctm_base_addr(int unsigned num_ctp);
    return AxiLiteAddrWidth'(
        cross_trigger_network_addrmap_pkg::CROSS_TRIGGER_NETWORK_CTM_BASE_ADDR);
  endfunction

  // Function to calculate CTP base address (CTPs start after CTM)
  function automatic logic [AxiLiteAddrWidth-1:0] calc_ctp_base_addr(int unsigned ctp_idx);
    return AxiLiteAddrWidth
        '(cross_trigger_network_addrmap_pkg::CROSS_TRIGGER_NETWORK_CTP_BASE_ADDR(ctp_idx));
  endfunction

endpackage : cross_trigger_network_pkg

`endif  // CROSS_TRIGGER_NETWORK_PKG_SV
