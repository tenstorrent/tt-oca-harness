// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP local AXI crossbar types and configuration.
//
// Hand-maintained: fabric_gen's static config cannot express this crossbar, so
// it is not regenerated. Address rules live in sep_local_axi_xbar.

`include "axi/typedef.svh"

package sep_local_axi_xbar_pkg;

  import axi_pkg::*;

  // ===========================================================================
  // Fabric Parameters
  // ===========================================================================
  localparam int unsigned NumInputs = 5;
  localparam int unsigned NumOutputs = 10;
  localparam int unsigned NumAddrRules = 15;
  localparam int unsigned MaxInputIdW = 3;
  localparam int unsigned XbarOutputIdW = 6;

  // ===========================================================================
  // Protocol Type Definitions
  // ===========================================================================

  // Protocol: axi64 (AXI4)
  typedef logic [31:0] axi64_addr_t;
  typedef logic [63:0] axi64_data_t;
  typedef logic [7:0] axi64_strb_t;
  typedef logic [2:0] axi64_id_t;
  typedef logic [11:0] axi64_user_t;

  `AXI_TYPEDEF_AW_CHAN_T(axi64_aw_chan_t, axi64_addr_t, axi64_id_t, axi64_user_t)
  `AXI_TYPEDEF_W_CHAN_T(axi64_w_chan_t, axi64_data_t, axi64_strb_t, axi64_user_t)
  `AXI_TYPEDEF_B_CHAN_T(axi64_b_chan_t, axi64_id_t, axi64_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(axi64_ar_chan_t, axi64_addr_t, axi64_id_t, axi64_user_t)
  `AXI_TYPEDEF_R_CHAN_T(axi64_r_chan_t, axi64_data_t, axi64_id_t, axi64_user_t)
  `AXI_TYPEDEF_REQ_T(axi64_req_t, axi64_aw_chan_t, axi64_w_chan_t, axi64_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(axi64_resp_t, axi64_b_chan_t, axi64_r_chan_t)
  // ===========================================================================
  // Crossbar Internal Types
  // ===========================================================================
  localparam int unsigned XbarDataWidth = 64;
  localparam int unsigned XbarStrbWidth = 8;
  localparam int unsigned XbarAddrWidth = 32;
  localparam int unsigned XbarUserWidth = 12;

  // ===========================================================================
  // AXI4 Output Type Definition (unified type with expanded ID width)
  // ===========================================================================
  // All AXI4 outputs use this type with xbar-expanded ID width
  typedef logic [XbarAddrWidth-1:0] axi_out_addr_t;
  typedef logic [XbarDataWidth-1:0] axi_out_data_t;
  typedef logic [XbarStrbWidth-1:0] axi_out_strb_t;
  typedef logic [XbarOutputIdW-1:0] axi_out_id_t;
  typedef logic [XbarUserWidth-1:0] axi_out_user_t;

  `AXI_TYPEDEF_AW_CHAN_T(axi_out_aw_chan_t, axi_out_addr_t, axi_out_id_t, axi_out_user_t)
  `AXI_TYPEDEF_W_CHAN_T(axi_out_w_chan_t, axi_out_data_t, axi_out_strb_t, axi_out_user_t)
  `AXI_TYPEDEF_B_CHAN_T(axi_out_b_chan_t, axi_out_id_t, axi_out_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(axi_out_ar_chan_t, axi_out_addr_t, axi_out_id_t, axi_out_user_t)
  `AXI_TYPEDEF_R_CHAN_T(axi_out_r_chan_t, axi_out_data_t, axi_out_id_t, axi_out_user_t)
  `AXI_TYPEDEF_REQ_T(axi_out_req_t, axi_out_aw_chan_t, axi_out_w_chan_t, axi_out_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(axi_out_resp_t, axi_out_b_chan_t, axi_out_r_chan_t)

  typedef logic [XbarAddrWidth-1:0] xbar_addr_t;
  typedef logic [XbarDataWidth-1:0] xbar_data_t;
  typedef logic [XbarStrbWidth-1:0] xbar_strb_t;
  typedef logic [MaxInputIdW-1:0] xbar_slv_id_t;
  typedef logic [XbarOutputIdW-1:0] xbar_mst_id_t;
  typedef logic [XbarUserWidth-1:0] xbar_user_t;

  // Crossbar slave port (input) types - Full AXI
  `AXI_TYPEDEF_AW_CHAN_T(xbar_slv_aw_chan_t, xbar_addr_t, xbar_slv_id_t, xbar_user_t)
  `AXI_TYPEDEF_W_CHAN_T(xbar_slv_w_chan_t, xbar_data_t, xbar_strb_t, xbar_user_t)
  `AXI_TYPEDEF_B_CHAN_T(xbar_slv_b_chan_t, xbar_slv_id_t, xbar_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(xbar_slv_ar_chan_t, xbar_addr_t, xbar_slv_id_t, xbar_user_t)
  `AXI_TYPEDEF_R_CHAN_T(xbar_slv_r_chan_t, xbar_data_t, xbar_slv_id_t, xbar_user_t)
  `AXI_TYPEDEF_REQ_T(xbar_slv_req_t, xbar_slv_aw_chan_t, xbar_slv_w_chan_t, xbar_slv_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(xbar_slv_resp_t, xbar_slv_b_chan_t, xbar_slv_r_chan_t)

  // Crossbar master port (output) types - Full AXI
  `AXI_TYPEDEF_AW_CHAN_T(xbar_mst_aw_chan_t, xbar_addr_t, xbar_mst_id_t, xbar_user_t)
  `AXI_TYPEDEF_B_CHAN_T(xbar_mst_b_chan_t, xbar_mst_id_t, xbar_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(xbar_mst_ar_chan_t, xbar_addr_t, xbar_mst_id_t, xbar_user_t)
  `AXI_TYPEDEF_R_CHAN_T(xbar_mst_r_chan_t, xbar_data_t, xbar_mst_id_t, xbar_user_t)
  `AXI_TYPEDEF_REQ_T(xbar_mst_req_t, xbar_mst_aw_chan_t, xbar_slv_w_chan_t, xbar_mst_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(xbar_mst_resp_t, xbar_mst_b_chan_t, xbar_mst_r_chan_t)

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
      NoSlvPorts: NumInputs,
      NoMstPorts: NumOutputs,
      MaxMstTrans: 4,
      MaxSlvTrans: 4,
      FallThrough: 1'b0,
      LatencyMode: axi_pkg::CUT_ALL_PORTS,
      PipelineStages: 1,
      AxiIdWidthSlvPorts: MaxInputIdW,
      AxiIdUsedSlvPorts: MaxInputIdW,
      UniqueIds: 1'b0,
      AxiAddrWidth: XbarAddrWidth,
      AxiDataWidth: XbarDataWidth,
      NoAddrRules: NumAddrRules,
      SelHashIds: 1'b0
  };

  // ===========================================================================
  // Connectivity Matrix
  // ===========================================================================
  localparam bit [NumInputs-1:0][NumOutputs-1:0] Connectivity = '{
      0: 10'b0000000010,  // ifu_sram
      1: 10'b1111111110,  // lsu
      2: 10'b1111111110,  // dbg
      3: 10'b1011111011,  // dma
      4: 10'b1110101110  // ext
  };

endpackage : sep_local_axi_xbar_pkg
