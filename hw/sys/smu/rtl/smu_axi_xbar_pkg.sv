// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SMU AXI crossbar types, configuration, and connectivity.
// Runtime address rules are defined by smu_axi_xbar.

package smu_axi_xbar_pkg;

  `include "axi/typedef.svh"

  import axi_pkg::*;

  // =========================================================================
  // Fabric Parameters
  // =========================================================================
  localparam int unsigned NumInputs = 3;
  localparam int unsigned NumOutputs = 3;
  localparam int unsigned NumAddrRules = 2;
  localparam int unsigned MaxInputIdW = 8;
  localparam int unsigned XbarOutputIdW = 10;

  // =========================================================================
  // Protocol Type Definitions
  // =========================================================================
  // Protocol: axi_56_64 (AXI4, 56-bit addr, 64-bit data)
  typedef logic [55:0] axi_56_64_addr_t;
  typedef logic [63:0] axi_56_64_data_t;
  typedef logic [7:0] axi_56_64_strb_t;
  typedef logic [7:0] axi_56_64_id_t;
  typedef logic [11:0] axi_56_64_user_t;

  `AXI_TYPEDEF_AW_CHAN_T(axi_56_64_aw_chan_t, axi_56_64_addr_t, axi_56_64_id_t, axi_56_64_user_t)
  `AXI_TYPEDEF_W_CHAN_T(axi_56_64_w_chan_t, axi_56_64_data_t, axi_56_64_strb_t, axi_56_64_user_t)
  `AXI_TYPEDEF_B_CHAN_T(axi_56_64_b_chan_t, axi_56_64_id_t, axi_56_64_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(axi_56_64_ar_chan_t, axi_56_64_addr_t, axi_56_64_id_t, axi_56_64_user_t)
  `AXI_TYPEDEF_R_CHAN_T(axi_56_64_r_chan_t, axi_56_64_data_t, axi_56_64_id_t, axi_56_64_user_t)
  `AXI_TYPEDEF_REQ_T(axi_56_64_req_t, axi_56_64_aw_chan_t, axi_56_64_w_chan_t, axi_56_64_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(axi_56_64_resp_t, axi_56_64_b_chan_t, axi_56_64_r_chan_t)

  // =========================================================================
  // Crossbar Internal Types
  // =========================================================================
  localparam int unsigned XbarDataWidth = 64;
  localparam int unsigned XbarStrbWidth = 8;
  localparam int unsigned XbarAddrWidth = 56;
  localparam int unsigned XbarUserWidth = 12;

  // =========================================================================
  // AXI4 Output Type Definition (unified type with expanded ID width)
  // =========================================================================
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

  // =========================================================================
  // Address Mapping
  // =========================================================================
  // Custom address rule type with end_addr 1 bit wider to handle overflow
  typedef struct packed {
    int unsigned idx;
    logic [55:0] start_addr;
    logic [56:0] end_addr;
  } addr_rule_t;

  // =========================================================================
  // Crossbar Configuration
  // =========================================================================
  localparam axi_pkg::xbar_cfg_t XbarCfg = '{
      NoSlvPorts: NumInputs,
      NoMstPorts: NumOutputs,
      MaxMstTrans: 8,
      MaxSlvTrans: 8,
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

  // =========================================================================
  // Connectivity Matrix
  // =========================================================================
  // Bit j of row i is 1 when input i can reach output j.
  //   row 0 = sep_out -> {smc_in, ext_out}     => 3'b110
  //   row 1 = smc_out -> {sep_in, ext_out}     => 3'b101
  //   row 2 = ext_in  -> {sep_in, smc_in}      => 3'b011
  localparam bit [NumInputs-1:0][NumOutputs-1:0] Connectivity = '{
      0: 3'b110,
      1: 3'b101,
      2: 3'b011
  };

endpackage : smu_axi_xbar_pkg
