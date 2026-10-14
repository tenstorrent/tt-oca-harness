// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Define types and configuration for the SEP system-peripherals AXI crossbar.
//
// Address decode rules live in sep_system_peripherals_xbar rather than this package; the
// named address-range constants here mirror its smn_inbound_from_xbar and mailbox rules and
// are not referenced by the crossbar. Its system_csr rules take each register block's bounds
// from sep_top_addrmap_pkg.
// Both initiators connect to all three targets.

`include "axi/typedef.svh"

package sep_system_peripherals_xbar_pkg;


  // ===========================================================================
  // Fabric Parameters
  // ===========================================================================
  localparam int unsigned NumInputs     = 2;
  localparam int unsigned NumOutputs    = 3;
  localparam int unsigned NumAddrRules  = 12;
  localparam int unsigned MaxInputIdW   = 6;
  localparam int unsigned XbarOutputIdW = 7;

  // ===========================================================================
  // Protocol Type Definitions
  // ===========================================================================

  // Protocol: axi64 (AXI4)
  typedef logic [55:0] axi64_addr_t;
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

  // Protocol: axi_lite64 (AXI4_LITE)
  typedef logic [55:0] axi_lite64_addr_t;
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
  localparam int unsigned XbarAddrWidth = 56;
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
  // AXI4 typedefs for xbar_out_mailbox
  typedef logic [55:0] xbar_out_mailbox_addr_t;
  typedef logic [63:0] xbar_out_mailbox_data_t;
  typedef logic [7:0] xbar_out_mailbox_strb_t;
  typedef logic [6:0] xbar_out_mailbox_id_t;
  typedef logic [11:0] xbar_out_mailbox_user_t;
  `AXI_TYPEDEF_AW_CHAN_T(xbar_out_mailbox_aw_chan_t, xbar_out_mailbox_addr_t, xbar_out_mailbox_id_t, xbar_out_mailbox_user_t)
  `AXI_TYPEDEF_W_CHAN_T(xbar_out_mailbox_w_chan_t, xbar_out_mailbox_data_t, xbar_out_mailbox_strb_t, xbar_out_mailbox_user_t)
  `AXI_TYPEDEF_B_CHAN_T(xbar_out_mailbox_b_chan_t, xbar_out_mailbox_id_t, xbar_out_mailbox_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(xbar_out_mailbox_ar_chan_t, xbar_out_mailbox_addr_t, xbar_out_mailbox_id_t, xbar_out_mailbox_user_t)
  `AXI_TYPEDEF_R_CHAN_T(xbar_out_mailbox_r_chan_t, xbar_out_mailbox_data_t, xbar_out_mailbox_id_t, xbar_out_mailbox_user_t)
  `AXI_TYPEDEF_REQ_T(xbar_out_mailbox_req_t, xbar_out_mailbox_aw_chan_t, xbar_out_mailbox_w_chan_t, xbar_out_mailbox_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(xbar_out_mailbox_resp_t, xbar_out_mailbox_b_chan_t, xbar_out_mailbox_r_chan_t)

  // AXI4-Lite typedefs for mailbox
  typedef logic [55:0] mailbox_addr_t;
  typedef logic [63:0] mailbox_data_t;
  typedef logic [7:0] mailbox_strb_t;
  `AXI_LITE_TYPEDEF_AW_CHAN_T(mailbox_aw_chan_t, mailbox_addr_t)
  `AXI_LITE_TYPEDEF_W_CHAN_T(mailbox_w_chan_t, mailbox_data_t, mailbox_strb_t)
  `AXI_LITE_TYPEDEF_B_CHAN_T(mailbox_b_chan_t)
  `AXI_LITE_TYPEDEF_AR_CHAN_T(mailbox_ar_chan_t, mailbox_addr_t)
  `AXI_LITE_TYPEDEF_R_CHAN_T(mailbox_r_chan_t, mailbox_data_t)
  `AXI_LITE_TYPEDEF_REQ_T(mailbox_req_t, mailbox_aw_chan_t, mailbox_w_chan_t, mailbox_ar_chan_t)
  `AXI_LITE_TYPEDEF_RESP_T(mailbox_resp_t, mailbox_b_chan_t, mailbox_r_chan_t)
  // AXI4 typedefs for xbar_out_system_csr
  typedef logic [55:0] xbar_out_system_csr_addr_t;
  typedef logic [63:0] xbar_out_system_csr_data_t;
  typedef logic [7:0] xbar_out_system_csr_strb_t;
  typedef logic [6:0] xbar_out_system_csr_id_t;
  typedef logic [11:0] xbar_out_system_csr_user_t;
  `AXI_TYPEDEF_AW_CHAN_T(xbar_out_system_csr_aw_chan_t, xbar_out_system_csr_addr_t, xbar_out_system_csr_id_t, xbar_out_system_csr_user_t)
  `AXI_TYPEDEF_W_CHAN_T(xbar_out_system_csr_w_chan_t, xbar_out_system_csr_data_t, xbar_out_system_csr_strb_t, xbar_out_system_csr_user_t)
  `AXI_TYPEDEF_B_CHAN_T(xbar_out_system_csr_b_chan_t, xbar_out_system_csr_id_t, xbar_out_system_csr_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(xbar_out_system_csr_ar_chan_t, xbar_out_system_csr_addr_t, xbar_out_system_csr_id_t, xbar_out_system_csr_user_t)
  `AXI_TYPEDEF_R_CHAN_T(xbar_out_system_csr_r_chan_t, xbar_out_system_csr_data_t, xbar_out_system_csr_id_t, xbar_out_system_csr_user_t)
  `AXI_TYPEDEF_REQ_T(xbar_out_system_csr_req_t, xbar_out_system_csr_aw_chan_t, xbar_out_system_csr_w_chan_t, xbar_out_system_csr_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(xbar_out_system_csr_resp_t, xbar_out_system_csr_b_chan_t, xbar_out_system_csr_r_chan_t)

  // AXI4-Lite typedefs for system_csr
  typedef logic [55:0] system_csr_addr_t;
  typedef logic [63:0] system_csr_data_t;
  typedef logic [7:0] system_csr_strb_t;
  `AXI_LITE_TYPEDEF_AW_CHAN_T(system_csr_aw_chan_t, system_csr_addr_t)
  `AXI_LITE_TYPEDEF_W_CHAN_T(system_csr_w_chan_t, system_csr_data_t, system_csr_strb_t)
  `AXI_LITE_TYPEDEF_B_CHAN_T(system_csr_b_chan_t)
  `AXI_LITE_TYPEDEF_AR_CHAN_T(system_csr_ar_chan_t, system_csr_addr_t)
  `AXI_LITE_TYPEDEF_R_CHAN_T(system_csr_r_chan_t, system_csr_data_t)
  `AXI_LITE_TYPEDEF_REQ_T(system_csr_req_t, system_csr_aw_chan_t, system_csr_w_chan_t, system_csr_ar_chan_t)
  `AXI_LITE_TYPEDEF_RESP_T(system_csr_resp_t, system_csr_b_chan_t, system_csr_r_chan_t)

  // ===========================================================================
  // Address Mapping
  // ===========================================================================
  // Custom address rule type with end_addr 1 bit wider to handle overflow
  typedef struct packed {
    int unsigned idx;
    logic [55:0] start_addr;
    logic [56:0] end_addr;
  } addr_rule_t;

  // APB address rule type for AXI-Lite to APB bridges (decode width = xbar AXI-Lite width)
  typedef struct packed {
    int unsigned idx;
    logic [55:0] start_addr;
    logic [56:0] end_addr;
  } apb_addr_rule_t;

  // ===========================================================================
  // Address Range Constants (Named)
  // ===========================================================================
  // Output: smn_inbound_from_xbar
  localparam logic [55:0] SMN_INBOUND_FROM_XBAR_REGION_0_BASE = 56'h0;
  localparam logic [55:0] SMN_INBOUND_FROM_XBAR_REGION_0_SIZE = 56'h10802000;
  localparam logic [56:0] SMN_INBOUND_FROM_XBAR_REGION_0_END  = 57'h10802000;
  localparam logic [55:0] SMN_INBOUND_FROM_XBAR_REGION_1_BASE = 56'h10802100;
  localparam logic [55:0] SMN_INBOUND_FROM_XBAR_REGION_1_SIZE = 56'h1fdf00;
  localparam logic [56:0] SMN_INBOUND_FROM_XBAR_REGION_1_END  = 57'h10a00000;
  localparam logic [55:0] SMN_INBOUND_FROM_XBAR_REGION_2_BASE = 56'h10a50000;
  localparam logic [55:0] SMN_INBOUND_FROM_XBAR_REGION_2_SIZE = 56'h2f5b0000;
  localparam logic [56:0] SMN_INBOUND_FROM_XBAR_REGION_2_END  = 57'h40000000;

  // Output: mailbox
  localparam logic [55:0] MAILBOX_MAIN_BASE = 56'h10a00000;
  localparam logic [55:0] MAILBOX_MAIN_SIZE = 56'h10000;
  localparam logic [56:0] MAILBOX_MAIN_END  = 57'h10a10000;

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
    0: 3'b111,  // sep_local_from_remap.
    1: 3'b111  // smn_inbound.
  };

endpackage : sep_system_peripherals_xbar_pkg
