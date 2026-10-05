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
  localparam int unsigned DefaultNumCtp = 16;

  // Number of internal cross trigger interfaces
  localparam int unsigned DefaultNumIntCt = 10;

  // Number of clock stop request inputs
  localparam int unsigned DefaultNumClkStopReq = 9;

  // Total number of CTM ports
  localparam int unsigned DefaultNumCtmPorts = DefaultNumCtp + DefaultNumIntCt;

  //-------------------------------------------------------------------------
  // Cross Trigger Configuration Checks
  //
  // cross_trigger_network_pkg restates these default counts. Nothing derives
  // one from another, so check that they agree. Failures are elaboration
  // errors, not lint.
  //-------------------------------------------------------------------------

  `OCAH_OT_ASSERT_STATIC_IN_PACKAGE(NumCtpMatchesCtn_A,
                                    DefaultNumCtp == cross_trigger_network_pkg::DefaultNumCtp)
  `OCAH_OT_ASSERT_STATIC_IN_PACKAGE(NumIntCtMatchesCtn_A,
                                    DefaultNumIntCt == cross_trigger_network_pkg::DefaultNumIntCt)
  `OCAH_OT_ASSERT_STATIC_IN_PACKAGE(
      NumClkStopReqMatchesCtn_A,
      DefaultNumClkStopReq == cross_trigger_network_pkg::DefaultNumClkStopReq)

  //-------------------------------------------------------------------------
  // Derived Parameters
  //-------------------------------------------------------------------------

  localparam logic [DefaultNumIntCt-1:0] DefaultIntCtMode = {DefaultNumIntCt{1'b0}};

  //-------------------------------------------------------------------------
  // AXI-Lite Parameters
  //-------------------------------------------------------------------------

  localparam int unsigned DtpAxilAddrWidth = 32;
  localparam int unsigned DtpAxilDataWidth = 32;

  localparam int unsigned JtagDbgAxiAddrWidth = 56;
  localparam int unsigned JtagDbgAxiDataWidth = 64;
  localparam int unsigned JtagDbgAxiIdWidth = 2;
  localparam int unsigned JtagDbgAxiUserWidth = 12;

  // AXI-Lite Typedefs
  typedef logic [DtpAxilAddrWidth-1:0] dtp_axi_lite_32_addr_t;
  typedef logic [DtpAxilDataWidth-1:0] dtp_axi_lite_32_data_t;
  typedef logic [DtpAxilDataWidth/8-1:0] dtp_axi_lite_32_strb_t;

  // JTAG Debug AXI Typedefs
  typedef logic [JtagDbgAxiAddrWidth-1:0] jtag_dbg_axi_addr_t;
  typedef logic [JtagDbgAxiDataWidth-1:0] jtag_dbg_axi_data_t;
  typedef logic [JtagDbgAxiIdWidth-1:0] jtag_dbg_axi_id_t;
  typedef logic [JtagDbgAxiDataWidth/8-1:0] jtag_dbg_axi_strb_t;
  typedef logic [JtagDbgAxiUserWidth-1:0] jtag_dbg_axi_user_t;


  // 32_32_0_0
  `AXI_LITE_TYPEDEF_ALL(dtp_axil_32_32, dtp_axi_lite_32_addr_t, dtp_axi_lite_32_data_t,
                        dtp_axi_lite_32_strb_t)

  // 56_64_2_12
  `AXI_TYPEDEF_ALL(jtag_dbg_56_64_2_12_axi, jtag_dbg_axi_addr_t, jtag_dbg_axi_id_t,
                   jtag_dbg_axi_data_t, jtag_dbg_axi_strb_t, jtag_dbg_axi_user_t)

endpackage : dtp_pkg
