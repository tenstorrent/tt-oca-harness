// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold Debug and Test Ports configuration and interface typedefs.
//
// Define default CTP, internal-CT, and clock-stop counts, the AXI-Lite and JTAG-debug AXI
// typedefs, and static checks that these defaults match cross_trigger_network_pkg.
// Failures of those checks are elaboration errors, not lint.

package dtp_pkg;

  `include "prim_assert.sv"
  `include "axi/typedef.svh"

  //-------------------------------------------------------------------------
  // Cross Trigger Configuration Parameters
  //-------------------------------------------------------------------------

  // Number of external Cross Trigger Ports
  localparam int unsigned DEFAULT_NUM_CTP = 16;

  // Number of internal cross trigger interfaces
  localparam int unsigned DEFAULT_NUM_INT_CT = 10;

  // Number of clock stop request inputs
  localparam int unsigned DEFAULT_NUM_CLK_STOP_REQ = 9;

  // Total number of CTM ports
  localparam int unsigned DEFAULT_NUM_CTM_PORTS = DEFAULT_NUM_CTP + DEFAULT_NUM_INT_CT;

  //-------------------------------------------------------------------------
  // Cross Trigger Configuration Checks
  //
  // cross_trigger_network_pkg restates these default counts. Nothing derives
  // one from another, so check that they agree. Failures are elaboration
  // errors, not lint.
  //-------------------------------------------------------------------------

  `OCAH_OT_ASSERT_STATIC_IN_PACKAGE(NumCtpMatchesCtn_A,
                                    DEFAULT_NUM_CTP == cross_trigger_network_pkg::DEFAULT_NUM_CTP)
  `OCAH_OT_ASSERT_STATIC_IN_PACKAGE(
      NumIntCtMatchesCtn_A, DEFAULT_NUM_INT_CT == cross_trigger_network_pkg::DEFAULT_NUM_INT_CT)
  `OCAH_OT_ASSERT_STATIC_IN_PACKAGE(
      NumClkStopReqMatchesCtn_A,
      DEFAULT_NUM_CLK_STOP_REQ == cross_trigger_network_pkg::DEFAULT_NUM_CLK_STOP_REQ)

  //-------------------------------------------------------------------------
  // Derived Parameters
  //-------------------------------------------------------------------------

  localparam logic [DEFAULT_NUM_INT_CT-1:0] DEFAULT_INT_CT_MODE = {DEFAULT_NUM_INT_CT{1'b0}};

  //-------------------------------------------------------------------------
  // AXI-Lite Parameters
  //-------------------------------------------------------------------------

  localparam int unsigned DTP_AXIL_ADDR_WIDTH = 32;
  localparam int unsigned DTP_AXIL_DATA_WIDTH = 32;

  localparam int unsigned JTAG_DBG_AXI_ADDR_WIDTH = 56;
  localparam int unsigned JTAG_DBG_AXI_DATA_WIDTH = 64;
  localparam int unsigned JTAG_DBG_AXI_ID_WIDTH = 2;
  localparam int unsigned JTAG_DBG_AXI_USER_WIDTH = 12;

  // AXI-Lite Typedefs
  typedef logic [DTP_AXIL_ADDR_WIDTH-1:0] dtp_axi_lite_32_addr_t;
  typedef logic [DTP_AXIL_DATA_WIDTH-1:0] dtp_axi_lite_32_data_t;
  typedef logic [DTP_AXIL_DATA_WIDTH/8-1:0] dtp_axi_lite_32_strb_t;

  // JTAG Debug AXI Typedefs
  typedef logic [JTAG_DBG_AXI_ADDR_WIDTH-1:0] jtag_dbg_axi_addr_t;
  typedef logic [JTAG_DBG_AXI_DATA_WIDTH-1:0] jtag_dbg_axi_data_t;
  typedef logic [JTAG_DBG_AXI_ID_WIDTH-1:0] jtag_dbg_axi_id_t;
  typedef logic [JTAG_DBG_AXI_DATA_WIDTH/8-1:0] jtag_dbg_axi_strb_t;
  typedef logic [JTAG_DBG_AXI_USER_WIDTH-1:0] jtag_dbg_axi_user_t;


  // 32_32_0_0
  `AXI_LITE_TYPEDEF_ALL(dtp_axil_32_32, dtp_axi_lite_32_addr_t, dtp_axi_lite_32_data_t,
                        dtp_axi_lite_32_strb_t)

  // 56_64_2_12
  `AXI_TYPEDEF_ALL(jtag_dbg_56_64_2_12_axi, jtag_dbg_axi_addr_t, jtag_dbg_axi_id_t,
                   jtag_dbg_axi_data_t, jtag_dbg_axi_strb_t, jtag_dbg_axi_user_t)

endpackage : dtp_pkg
