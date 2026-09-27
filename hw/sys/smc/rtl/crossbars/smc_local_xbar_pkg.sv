// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Declare SMC local AXI crossbar types and configuration.
//
// Defines initiator/target counts and AXI typedefs for the local SMC xbar: three
// initiators with 6-bit IDs, five targets whose IDs widen to 8 bits, and 20 address
// rules on a 32-bit address and 64-bit data bus, with eight outstanding transactions per
// port, every port cut and full connectivity. It also declares the AXI-Lite and APB
// types of the converted CSR ports.
// Address rules are defined by smc_local_xbar.

`include "axi/typedef.svh"
`include "apb/typedef.svh"

package smc_local_xbar_pkg;

  import axi_pkg::*;

  // ===========================================================================
  // Fabric Parameters
  // ===========================================================================
  localparam int unsigned NumInputs     = 3;
  localparam int unsigned NumOutputs    = 5;
  localparam int unsigned NumAddrRules  = 20;
  localparam int unsigned MaxInputIdW   = 6;
  localparam int unsigned XbarOutputIdW = 8;

  // ===========================================================================
  // Protocol Type Definitions
  // ===========================================================================

  // Protocol: apb32 (APB4)
  typedef logic [31:0] apb32_addr_t;
  typedef logic [31:0] apb32_data_t;
  typedef logic [3:0] apb32_strb_t;

  `APB_TYPEDEF_REQ_T(apb32_req_t, apb32_addr_t, apb32_data_t, apb32_strb_t)
  `APB_TYPEDEF_RESP_T(apb32_resp_t, apb32_data_t)

  // Protocol: axi64 (AXI4)
  typedef logic [31:0] axi64_addr_t;
  typedef logic [63:0] axi64_data_t;
  typedef logic [7:0] axi64_strb_t;
  typedef logic [5:0] axi64_id_t;
  typedef logic [11:0] axi64_user_t;

  `AXI_TYPEDEF_AW_CHAN_T(axi64_aw_chan_t, axi64_addr_t, axi64_id_t, axi64_user_t)
  `AXI_TYPEDEF_W_CHAN_T(axi64_w_chan_t, axi64_data_t, axi64_strb_t, axi64_user_t)
  `AXI_TYPEDEF_B_CHAN_T(axi64_b_chan_t, axi64_id_t, axi64_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(axi64_ar_chan_t, axi64_addr_t, axi64_id_t, axi64_user_t)
  `AXI_TYPEDEF_R_CHAN_T(axi64_r_chan_t, axi64_data_t, axi64_id_t, axi64_user_t)
  `AXI_TYPEDEF_REQ_T(axi64_req_t, axi64_aw_chan_t, axi64_w_chan_t, axi64_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(axi64_resp_t, axi64_b_chan_t, axi64_r_chan_t)

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
  // AXI4 typedefs for xbar_out_local_reg
  typedef logic [31:0] xbar_out_local_reg_addr_t;
  typedef logic [63:0] xbar_out_local_reg_data_t;
  typedef logic [7:0] xbar_out_local_reg_strb_t;
  typedef logic [7:0] xbar_out_local_reg_id_t;
  typedef logic [11:0] xbar_out_local_reg_user_t;
  `AXI_TYPEDEF_AW_CHAN_T(xbar_out_local_reg_aw_chan_t, xbar_out_local_reg_addr_t, xbar_out_local_reg_id_t, xbar_out_local_reg_user_t)
  `AXI_TYPEDEF_W_CHAN_T(xbar_out_local_reg_w_chan_t, xbar_out_local_reg_data_t, xbar_out_local_reg_strb_t, xbar_out_local_reg_user_t)
  `AXI_TYPEDEF_B_CHAN_T(xbar_out_local_reg_b_chan_t, xbar_out_local_reg_id_t, xbar_out_local_reg_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(xbar_out_local_reg_ar_chan_t, xbar_out_local_reg_addr_t, xbar_out_local_reg_id_t, xbar_out_local_reg_user_t)
  `AXI_TYPEDEF_R_CHAN_T(xbar_out_local_reg_r_chan_t, xbar_out_local_reg_data_t, xbar_out_local_reg_id_t, xbar_out_local_reg_user_t)
  `AXI_TYPEDEF_REQ_T(xbar_out_local_reg_req_t, xbar_out_local_reg_aw_chan_t, xbar_out_local_reg_w_chan_t, xbar_out_local_reg_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(xbar_out_local_reg_resp_t, xbar_out_local_reg_b_chan_t, xbar_out_local_reg_r_chan_t)

  // AXI4-Lite typedefs for local_reg
  typedef logic [31:0] local_reg_addr_t;
  typedef logic [63:0] local_reg_data_t;
  typedef logic [7:0] local_reg_strb_t;
  `AXI_LITE_TYPEDEF_AW_CHAN_T(local_reg_aw_chan_t, local_reg_addr_t)
  `AXI_LITE_TYPEDEF_W_CHAN_T(local_reg_w_chan_t, local_reg_data_t, local_reg_strb_t)
  `AXI_LITE_TYPEDEF_B_CHAN_T(local_reg_b_chan_t)
  `AXI_LITE_TYPEDEF_AR_CHAN_T(local_reg_ar_chan_t, local_reg_addr_t)
  `AXI_LITE_TYPEDEF_R_CHAN_T(local_reg_r_chan_t, local_reg_data_t)
  `AXI_LITE_TYPEDEF_REQ_T(local_reg_req_t, local_reg_aw_chan_t, local_reg_w_chan_t, local_reg_ar_chan_t)
  `AXI_LITE_TYPEDEF_RESP_T(local_reg_resp_t, local_reg_b_chan_t, local_reg_r_chan_t)
  // AXI4 typedefs for xbar_out_periph_reg
  typedef logic [31:0] xbar_out_periph_reg_addr_t;
  typedef logic [63:0] xbar_out_periph_reg_data_t;
  typedef logic [7:0] xbar_out_periph_reg_strb_t;
  typedef logic [7:0] xbar_out_periph_reg_id_t;
  typedef logic [11:0] xbar_out_periph_reg_user_t;
  `AXI_TYPEDEF_AW_CHAN_T(xbar_out_periph_reg_aw_chan_t, xbar_out_periph_reg_addr_t, xbar_out_periph_reg_id_t, xbar_out_periph_reg_user_t)
  `AXI_TYPEDEF_W_CHAN_T(xbar_out_periph_reg_w_chan_t, xbar_out_periph_reg_data_t, xbar_out_periph_reg_strb_t, xbar_out_periph_reg_user_t)
  `AXI_TYPEDEF_B_CHAN_T(xbar_out_periph_reg_b_chan_t, xbar_out_periph_reg_id_t, xbar_out_periph_reg_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(xbar_out_periph_reg_ar_chan_t, xbar_out_periph_reg_addr_t, xbar_out_periph_reg_id_t, xbar_out_periph_reg_user_t)
  `AXI_TYPEDEF_R_CHAN_T(xbar_out_periph_reg_r_chan_t, xbar_out_periph_reg_data_t, xbar_out_periph_reg_id_t, xbar_out_periph_reg_user_t)
  `AXI_TYPEDEF_REQ_T(xbar_out_periph_reg_req_t, xbar_out_periph_reg_aw_chan_t, xbar_out_periph_reg_w_chan_t, xbar_out_periph_reg_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(xbar_out_periph_reg_resp_t, xbar_out_periph_reg_b_chan_t, xbar_out_periph_reg_r_chan_t)

  // AXI4 typedefs for periph_reg_stage1
  typedef logic [31:0] periph_reg_stage1_addr_t;
  typedef logic [31:0] periph_reg_stage1_data_t;
  typedef logic [3:0] periph_reg_stage1_strb_t;
  typedef logic [7:0] periph_reg_stage1_id_t;
  typedef logic [11:0] periph_reg_stage1_user_t;
  `AXI_TYPEDEF_AW_CHAN_T(periph_reg_stage1_aw_chan_t, periph_reg_stage1_addr_t, periph_reg_stage1_id_t, periph_reg_stage1_user_t)
  `AXI_TYPEDEF_W_CHAN_T(periph_reg_stage1_w_chan_t, periph_reg_stage1_data_t, periph_reg_stage1_strb_t, periph_reg_stage1_user_t)
  `AXI_TYPEDEF_B_CHAN_T(periph_reg_stage1_b_chan_t, periph_reg_stage1_id_t, periph_reg_stage1_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(periph_reg_stage1_ar_chan_t, periph_reg_stage1_addr_t, periph_reg_stage1_id_t, periph_reg_stage1_user_t)
  `AXI_TYPEDEF_R_CHAN_T(periph_reg_stage1_r_chan_t, periph_reg_stage1_data_t, periph_reg_stage1_id_t, periph_reg_stage1_user_t)
  `AXI_TYPEDEF_REQ_T(periph_reg_stage1_req_t, periph_reg_stage1_aw_chan_t, periph_reg_stage1_w_chan_t, periph_reg_stage1_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(periph_reg_stage1_resp_t, periph_reg_stage1_b_chan_t, periph_reg_stage1_r_chan_t)

  // AXI4-Lite typedefs for periph_reg
  typedef logic [31:0] periph_reg_addr_t;
  typedef logic [31:0] periph_reg_data_t;
  typedef logic [3:0] periph_reg_strb_t;
  `AXI_LITE_TYPEDEF_AW_CHAN_T(periph_reg_aw_chan_t, periph_reg_addr_t)
  `AXI_LITE_TYPEDEF_W_CHAN_T(periph_reg_w_chan_t, periph_reg_data_t, periph_reg_strb_t)
  `AXI_LITE_TYPEDEF_B_CHAN_T(periph_reg_b_chan_t)
  `AXI_LITE_TYPEDEF_AR_CHAN_T(periph_reg_ar_chan_t, periph_reg_addr_t)
  `AXI_LITE_TYPEDEF_R_CHAN_T(periph_reg_r_chan_t, periph_reg_data_t)
  `AXI_LITE_TYPEDEF_REQ_T(periph_reg_req_t, periph_reg_aw_chan_t, periph_reg_w_chan_t, periph_reg_ar_chan_t)
  `AXI_LITE_TYPEDEF_RESP_T(periph_reg_resp_t, periph_reg_b_chan_t, periph_reg_r_chan_t)
  // AXI4 typedefs for xbar_out_smc_dfd_reg
  typedef logic [31:0] xbar_out_smc_dfd_reg_addr_t;
  typedef logic [63:0] xbar_out_smc_dfd_reg_data_t;
  typedef logic [7:0] xbar_out_smc_dfd_reg_strb_t;
  typedef logic [7:0] xbar_out_smc_dfd_reg_id_t;
  typedef logic [11:0] xbar_out_smc_dfd_reg_user_t;
  `AXI_TYPEDEF_AW_CHAN_T(xbar_out_smc_dfd_reg_aw_chan_t, xbar_out_smc_dfd_reg_addr_t, xbar_out_smc_dfd_reg_id_t, xbar_out_smc_dfd_reg_user_t)
  `AXI_TYPEDEF_W_CHAN_T(xbar_out_smc_dfd_reg_w_chan_t, xbar_out_smc_dfd_reg_data_t, xbar_out_smc_dfd_reg_strb_t, xbar_out_smc_dfd_reg_user_t)
  `AXI_TYPEDEF_B_CHAN_T(xbar_out_smc_dfd_reg_b_chan_t, xbar_out_smc_dfd_reg_id_t, xbar_out_smc_dfd_reg_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(xbar_out_smc_dfd_reg_ar_chan_t, xbar_out_smc_dfd_reg_addr_t, xbar_out_smc_dfd_reg_id_t, xbar_out_smc_dfd_reg_user_t)
  `AXI_TYPEDEF_R_CHAN_T(xbar_out_smc_dfd_reg_r_chan_t, xbar_out_smc_dfd_reg_data_t, xbar_out_smc_dfd_reg_id_t, xbar_out_smc_dfd_reg_user_t)
  `AXI_TYPEDEF_REQ_T(xbar_out_smc_dfd_reg_req_t, xbar_out_smc_dfd_reg_aw_chan_t, xbar_out_smc_dfd_reg_w_chan_t, xbar_out_smc_dfd_reg_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(xbar_out_smc_dfd_reg_resp_t, xbar_out_smc_dfd_reg_b_chan_t, xbar_out_smc_dfd_reg_r_chan_t)

  // AXI4 typedefs for smc_dfd_reg_stage1
  typedef logic [31:0] smc_dfd_reg_stage1_addr_t;
  typedef logic [31:0] smc_dfd_reg_stage1_data_t;
  typedef logic [3:0] smc_dfd_reg_stage1_strb_t;
  typedef logic [7:0] smc_dfd_reg_stage1_id_t;
  typedef logic [11:0] smc_dfd_reg_stage1_user_t;
  `AXI_TYPEDEF_AW_CHAN_T(smc_dfd_reg_stage1_aw_chan_t, smc_dfd_reg_stage1_addr_t, smc_dfd_reg_stage1_id_t, smc_dfd_reg_stage1_user_t)
  `AXI_TYPEDEF_W_CHAN_T(smc_dfd_reg_stage1_w_chan_t, smc_dfd_reg_stage1_data_t, smc_dfd_reg_stage1_strb_t, smc_dfd_reg_stage1_user_t)
  `AXI_TYPEDEF_B_CHAN_T(smc_dfd_reg_stage1_b_chan_t, smc_dfd_reg_stage1_id_t, smc_dfd_reg_stage1_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(smc_dfd_reg_stage1_ar_chan_t, smc_dfd_reg_stage1_addr_t, smc_dfd_reg_stage1_id_t, smc_dfd_reg_stage1_user_t)
  `AXI_TYPEDEF_R_CHAN_T(smc_dfd_reg_stage1_r_chan_t, smc_dfd_reg_stage1_data_t, smc_dfd_reg_stage1_id_t, smc_dfd_reg_stage1_user_t)
  `AXI_TYPEDEF_REQ_T(smc_dfd_reg_stage1_req_t, smc_dfd_reg_stage1_aw_chan_t, smc_dfd_reg_stage1_w_chan_t, smc_dfd_reg_stage1_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(smc_dfd_reg_stage1_resp_t, smc_dfd_reg_stage1_b_chan_t, smc_dfd_reg_stage1_r_chan_t)

  // AXI4-Lite typedefs for smc_dfd_reg_stage2
  typedef logic [31:0] smc_dfd_reg_stage2_addr_t;
  typedef logic [31:0] smc_dfd_reg_stage2_data_t;
  typedef logic [3:0] smc_dfd_reg_stage2_strb_t;
  `AXI_LITE_TYPEDEF_AW_CHAN_T(smc_dfd_reg_stage2_aw_chan_t, smc_dfd_reg_stage2_addr_t)
  `AXI_LITE_TYPEDEF_W_CHAN_T(smc_dfd_reg_stage2_w_chan_t, smc_dfd_reg_stage2_data_t, smc_dfd_reg_stage2_strb_t)
  `AXI_LITE_TYPEDEF_B_CHAN_T(smc_dfd_reg_stage2_b_chan_t)
  `AXI_LITE_TYPEDEF_AR_CHAN_T(smc_dfd_reg_stage2_ar_chan_t, smc_dfd_reg_stage2_addr_t)
  `AXI_LITE_TYPEDEF_R_CHAN_T(smc_dfd_reg_stage2_r_chan_t, smc_dfd_reg_stage2_data_t)
  `AXI_LITE_TYPEDEF_REQ_T(smc_dfd_reg_stage2_req_t, smc_dfd_reg_stage2_aw_chan_t, smc_dfd_reg_stage2_w_chan_t, smc_dfd_reg_stage2_ar_chan_t)
  `AXI_LITE_TYPEDEF_RESP_T(smc_dfd_reg_stage2_resp_t, smc_dfd_reg_stage2_b_chan_t, smc_dfd_reg_stage2_r_chan_t)

  // APB4 typedefs for smc_dfd_reg
  typedef logic [31:0] smc_dfd_reg_addr_t;
  typedef logic [31:0] smc_dfd_reg_data_t;
  typedef logic [3:0] smc_dfd_reg_strb_t;

  typedef struct packed {
    smc_dfd_reg_addr_t     paddr;
    axi_pkg::prot_t     pprot;
    logic               psel;
    logic               penable;
    logic               pwrite;
    smc_dfd_reg_data_t     pwdata;
    smc_dfd_reg_strb_t     pstrb;
  } smc_dfd_reg_req_t;

  typedef struct packed {
    logic               pready;
    smc_dfd_reg_data_t     prdata;
    logic               pslverr;
  } smc_dfd_reg_resp_t;

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
    MaxMstTrans:        8,
    MaxSlvTrans:        8,
    FallThrough:        1'b0,
    LatencyMode:        axi_pkg::CUT_ALL_PORTS,
    PipelineStages:     1,
    AxiIdWidthSlvPorts: MaxInputIdW,
    AxiIdUsedSlvPorts:  MaxInputIdW,
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
    0: 5'b11111,  // system.
    1: 5'b11111,  // sep_in.
    2: 5'b11111  // local_in.
  };

endpackage : smc_local_xbar_pkg
