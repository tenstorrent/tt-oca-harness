// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Declare SMC internal AXI-Lite crossbar types and configuration.
//
// Defines initiator/target counts and AXI-Lite typedefs for the internal CSR xbar: one
// initiator, 8 targets and 8 address rules on a 32-bit address and 64-bit data bus, with
// four outstanding transactions per port, every port cut and full connectivity. The rule
// type carries a 33-bit end address so a window can end at 2^32; apb_addr_rule_t is
// declared but unused.
// Address rules are defined by smc_internal_axi_lite_xbar.

`include "axi/typedef.svh"

package smc_internal_axi_lite_xbar_pkg;


  // ===========================================================================
  // Fabric Parameters
  // ===========================================================================
  localparam int unsigned NumInputs     = 1;
  localparam int unsigned NumOutputs    = 8;
  localparam int unsigned NumAddrRules  = 8;

  // ===========================================================================
  // Protocol Type Definitions
  // ===========================================================================

  // Protocol: axi_lite64 (AXI4_LITE)
  typedef logic [31:0] axi_lite64_addr_t;
  typedef logic [63:0] axi_lite64_data_t;
  typedef logic [7:0] axi_lite64_strb_t;

  `AXI_LITE_TYPEDEF_AW_CHAN_T(axi_lite64_aw_chan_t, axi_lite64_addr_t)
  `AXI_LITE_TYPEDEF_W_CHAN_T(axi_lite64_w_chan_t, axi_lite64_data_t, axi_lite64_strb_t)
  `AXI_LITE_TYPEDEF_B_CHAN_T(axi_lite64_b_chan_t)
  `AXI_LITE_TYPEDEF_AR_CHAN_T(axi_lite64_ar_chan_t, axi_lite64_addr_t)
  `AXI_LITE_TYPEDEF_R_CHAN_T(axi_lite64_r_chan_t, axi_lite64_data_t)
  `AXI_LITE_TYPEDEF_REQ_T(axi_lite64_req_t, axi_lite64_aw_chan_t, axi_lite64_w_chan_t, axi_lite64_ar_chan_t)
  `AXI_LITE_TYPEDEF_RESP_T(axi_lite64_resp_t, axi_lite64_b_chan_t, axi_lite64_r_chan_t)
  // ===========================================================================
  // Crossbar Internal Types
  // ===========================================================================
  localparam int unsigned XbarDataWidth = 64;
  localparam int unsigned XbarStrbWidth = 8;
  localparam int unsigned XbarAddrWidth = 32;
  localparam int unsigned XbarUserWidth = 1;

  typedef logic [XbarAddrWidth-1:0] xbar_addr_t;
  typedef logic [XbarDataWidth-1:0] xbar_data_t;
  typedef logic [XbarStrbWidth-1:0] xbar_strb_t;

  // Crossbar slave port (input) types - AXI-Lite (no ID/user signals)
  `AXI_LITE_TYPEDEF_AW_CHAN_T(xbar_slv_aw_chan_t, xbar_addr_t)
  `AXI_LITE_TYPEDEF_W_CHAN_T(xbar_slv_w_chan_t, xbar_data_t, xbar_strb_t)
  `AXI_LITE_TYPEDEF_B_CHAN_T(xbar_slv_b_chan_t)
  `AXI_LITE_TYPEDEF_AR_CHAN_T(xbar_slv_ar_chan_t, xbar_addr_t)
  `AXI_LITE_TYPEDEF_R_CHAN_T(xbar_slv_r_chan_t, xbar_data_t)
  `AXI_LITE_TYPEDEF_REQ_T(xbar_slv_req_t, xbar_slv_aw_chan_t, xbar_slv_w_chan_t, xbar_slv_ar_chan_t)
  `AXI_LITE_TYPEDEF_RESP_T(xbar_slv_resp_t, xbar_slv_b_chan_t, xbar_slv_r_chan_t)

  // Crossbar master port (output) types - AXI-Lite (same as slave, no ID expansion)
  `AXI_LITE_TYPEDEF_AW_CHAN_T(xbar_mst_aw_chan_t, xbar_addr_t)
  `AXI_LITE_TYPEDEF_B_CHAN_T(xbar_mst_b_chan_t)
  `AXI_LITE_TYPEDEF_AR_CHAN_T(xbar_mst_ar_chan_t, xbar_addr_t)
  `AXI_LITE_TYPEDEF_R_CHAN_T(xbar_mst_r_chan_t, xbar_data_t)
  `AXI_LITE_TYPEDEF_REQ_T(xbar_mst_req_t, xbar_mst_aw_chan_t, xbar_slv_w_chan_t, xbar_mst_ar_chan_t)
  `AXI_LITE_TYPEDEF_RESP_T(xbar_mst_resp_t, xbar_mst_b_chan_t, xbar_mst_r_chan_t)

  // ===========================================================================
  // Input Conversion Intermediate Types
  // ===========================================================================
  // ===========================================================================
  // Output Conversion Chain Intermediate Types
  // ===========================================================================

  // ===========================================================================
  // Address Mapping
  // ===========================================================================
  // Custom address rule type with end_addr 1 bit wider to handle overflow
  typedef struct packed {
    int unsigned idx;
    logic [31:0] start_addr;
    logic [32:0] end_addr;
  } addr_rule_t;

  // APB address rule type for AXI-Lite to APB bridges (decode width = xbar AXI-Lite width)
  typedef struct packed {
    int unsigned idx;
    logic [31:0] start_addr;
    logic [32:0] end_addr;
  } apb_addr_rule_t;

  // ===========================================================================
  // Crossbar Configuration
  // ===========================================================================
  localparam axi_pkg::xbar_cfg_t XbarCfg = '{
    NoSlvPorts:         NumInputs,
    NoMstPorts:         NumOutputs,
    MaxMstTrans:        4,
    MaxSlvTrans:        4,
    FallThrough:        1'b0,
    LatencyMode:        axi_pkg::CUT_ALL_PORTS,
    PipelineStages:     1,
    AxiIdWidthSlvPorts: 32'd1,
    AxiIdUsedSlvPorts:  32'd1,
    UniqueIds:          1'b0,
    AxiAddrWidth:       XbarAddrWidth,
    AxiDataWidth:       XbarDataWidth,
    NoAddrRules:        NumAddrRules,
    SelHashIds:         1'b0
  };

  // ===========================================================================
  // Connectivity Matrix
  // ===========================================================================
  localparam bit [NumInputs-1:0][NumOutputs-1:0] Connectivity = '{
    0: 8'b11111111  // local_in.
  };

endpackage : smc_internal_axi_lite_xbar_pkg
