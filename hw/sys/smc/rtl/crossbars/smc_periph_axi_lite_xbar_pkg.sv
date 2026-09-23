// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SMC peripheral AXI-Lite crossbar types and configuration.
//
// Hand-maintained: the fabric_gen source configs for this crossbar were not
// carried into the open tree, so it cannot be regenerated. Address rules live
// in smc_periph_axi_lite_xbar and derive their boundaries from
// smc_top_addrmap_pkg.

`include "axi/typedef.svh"

package smc_periph_axi_lite_xbar_pkg;

  import axi_pkg::*;

  // ===========================================================================
  // Fabric Parameters
  // ===========================================================================
  localparam int unsigned NumInputs     = 1;
  localparam int unsigned NumOutputs    = 12;
  localparam int unsigned NumAddrRules  = 14;

  // ===========================================================================
  // Protocol Type Definitions
  // ===========================================================================

  // Protocol: axi_lite32 (AXI4_LITE)
  typedef logic [31:0] axi_lite32_addr_t;
  typedef logic [31:0] axi_lite32_data_t;
  typedef logic [3:0] axi_lite32_strb_t;

  `AXI_LITE_TYPEDEF_AW_CHAN_T(axi_lite32_aw_chan_t, axi_lite32_addr_t)
  `AXI_LITE_TYPEDEF_W_CHAN_T(axi_lite32_w_chan_t, axi_lite32_data_t, axi_lite32_strb_t)
  `AXI_LITE_TYPEDEF_B_CHAN_T(axi_lite32_b_chan_t)
  `AXI_LITE_TYPEDEF_AR_CHAN_T(axi_lite32_ar_chan_t, axi_lite32_addr_t)
  `AXI_LITE_TYPEDEF_R_CHAN_T(axi_lite32_r_chan_t, axi_lite32_data_t)
  `AXI_LITE_TYPEDEF_REQ_T(axi_lite32_req_t, axi_lite32_aw_chan_t, axi_lite32_w_chan_t, axi_lite32_ar_chan_t)
  `AXI_LITE_TYPEDEF_RESP_T(axi_lite32_resp_t, axi_lite32_b_chan_t, axi_lite32_r_chan_t)
  // ===========================================================================
  // Crossbar Internal Types
  // ===========================================================================
  localparam int unsigned XbarDataWidth = 32;
  localparam int unsigned XbarStrbWidth = 4;
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
    0: 12'b111111111111  // periph_in
  };

endpackage : smc_periph_axi_lite_xbar_pkg
