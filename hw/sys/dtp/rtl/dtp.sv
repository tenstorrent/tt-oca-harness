// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Integrate JTAG, debug STAPs, and the cross-trigger network.
//
// Instantiate jtag_intf_unit, which holds the primary TAP, optional boundary-scan and
// STAP paths, JTAG2AXI debug ports and IC_RESET TDR slices, and cross_trigger_network,
// which holds the cross-trigger matrix with CTP pad connections and the AXI-Lite CSRs.
// dbg_disable_i applies per-TAP debug/test disables from the SEP lifecycle controller.
// Unused STAP or scan ports must be tied off or looped back as noted on each port.

module dtp
  import prim_jtag_pkg::*;
  import jtag_tap_pkg::*;
  import jtag_inst_reg_pkg::*;
  import cross_trigger_network_pkg::*;
  import dtp_pkg::*;
#(
  parameter bit  JTAG_BSR_ENABLE          = 1,  // Enable all mandatory JTAG boundary-scan
                                                // instructions.
  parameter bit  JTAG_EXTEST_TRAIN_ENABLE = 1,  // Enable optional JTAG EXTEST_TRAIN instruction.
  parameter bit  JTAG_EXTEST_PULSE_ENABLE = 1,  // Enable optional JTAG EXTEST_PULSE instruction.
  parameter bit  JTAG_INTEST_ENABLE       = 1,  // Enable optional JTAG INTEST instruction.
  parameter bit  JTAG_CLAMP_ENABLE        = 1,  // Enable optional JTAG CLAMP instruction.
  parameter bit  JTAG_HIGHZ_ENABLE        = 1,  // Enable optional JTAG HIGHZ instruction.
  parameter bit  JTAG_RUNBIST_ENABLE      = 1,  // Enable optional JTAG RUNBIST instruction.
  parameter bit  JTAG_TMP_ENABLE          = 1,  // Enable TMP controller functionality and
                                                // instructions.
  parameter bit  JTAG_IC_RESET_SMC_ENABLE = 1,  // Enable the SMC slice of the IC_RESET TDR.
  parameter bit  JTAG_IC_RESET_EXT_ENABLE = 1,  // Enable the external slice of the IC_RESET TDR.
  parameter bit  JTAG_SMC_DBG_ENABLE      = 1,  // Enable optional JTAG2AXI ports for the SMC debug
                                                // interface.
  parameter bit  JTAG_STAP_IO_ENABLE      = 1,  // Enable the STAP for chiplet-to-chiplet
                                                // connectivity.

  parameter int unsigned JTAG_IC_RESET_SEP_ENABLE = 1,  // Bit 0 enables the SEP slice of the
                                                        // IC_RESET TDR. int unsigned so SpyGlass
                                                        // elaborate -param can override it; in smu
                                                        // it follows CFG.SEP.
  parameter int unsigned JTAG_SEP_DBG_ENABLE      = 1,  // Bit 0 enables the SEP debug STAP and the
                                                        // JTAG2AXI bridge to the SEP OTP. int
                                                        // unsigned so SpyGlass elaborate -param can
                                                        // override it; in smu it follows CFG.SEP.

  parameter int unsigned  JTAG_NUM_EXTRA_STAPS = 1,  // Number of additional STAPs for local
                                                     // connectivity.

  parameter logic [10:0]  JTAG_IDCODE_MFR_ID   = 11'h000,  // JTAG IDCODE manufacturer ID.
  parameter logic [15:0]  JTAG_IDCODE_PART_NUM = 16'h0000,  // JTAG IDCODE part number.
  parameter logic [3:0]   JTAG_IDCODE_SI_REV   = 4'h0,  // JTAG IDCODE silicon revision.
  parameter logic [7:0]   JTAG_OCH_VER         = 8'h00,  // DTP IP major version number reported in
                                                         // JTAG_CAPS.

  localparam int unsigned  JtagNumExtraStapPorts = (JTAG_NUM_EXTRA_STAPS > 0) ? JTAG_NUM_EXTRA_STAPS : 1,  // Extra STAP port count; at least one for tie-off.

  parameter int unsigned  XTRIG_NUM_CTP          = dtp_pkg::DefaultNumCtp,  // Number of external cross-trigger ports.
  parameter int unsigned  XTRIG_NUM_INT_CT       = dtp_pkg::DefaultNumIntCt,  // Number of internal cross-trigger interfaces.
  parameter int unsigned  XTRIG_NUM_CLK_STOP_REQ = dtp_pkg::DefaultNumClkStopReq,  // Number of clock-stop request inputs.

  parameter logic [XTRIG_NUM_INT_CT-1:0]  XTRIG_INT_CT_MODE = '0,  // Per-lane CTM protocol: 0 =
                                                                   // pulse sync (ack unused), 1 =
                                                                   // req/ack handshake.

  parameter type  jtag_tap_ctrl_t = prim_jtag_pkg::jtag_tap_ctrl_t,  // JTAG TAP control type.
  parameter type  jtag_scan_ctrl_t = prim_jtag_pkg::jtag_scan_ctrl_t,  // JTAG scan control type.

  parameter type  ic_reset_smc_t = jtag_tap_pkg::jtag_ic_reset_default_t,  // SMC IC_RESET TDR slice type (.ovrd/.val)
                                                                           // Stub default is for standalone elaboration; integrators override per slice.
  parameter type  ic_reset_sep_t = jtag_tap_pkg::jtag_ic_reset_default_t,  // SEP IC_RESET TDR slice type (.ovrd/.val)
                                                                           // Stub default is for standalone elaboration; integrators override per slice.
  parameter type  ic_reset_ext_t = jtag_tap_pkg::jtag_ic_reset_default_t,  // External IC_RESET TDR slice type (.ovrd/.val)
                                                                           // Stub default is for standalone elaboration; integrators override per slice.

  parameter type  smc_jtag_axi_req_t = jtag_dbg_56_64_2_12_axi_req_t,  // SMC fabric debug AXI request type.
  parameter type  smc_jtag_axi_resp_t = jtag_dbg_56_64_2_12_axi_resp_t,  // SMC fabric debug AXI response type.

  parameter type  smc_otp_axil_req_t = dtp_axil_32_32_req_t,  // SMC OTP debug AXI-Lite request
                                                              // type.
  parameter type  smc_otp_axil_resp_t = dtp_axil_32_32_resp_t,  // SMC OTP debug AXI-Lite response
                                                                // type.

  parameter type  sep_otp_axil_req_t = dtp_axil_32_32_req_t,  // SEP OTP debug AXI-Lite request
                                                              // type.
  parameter type  sep_otp_axil_resp_t = dtp_axil_32_32_resp_t,  // SEP OTP debug AXI-Lite response
                                                                // type.

  parameter logic [1:0]  SMC_OTP_RD_PL_DEPTH = 2'h3,  // SMC OTP read pipeline depth; 0 = single
                                                      // outstanding.
  parameter logic [1:0]  SMC_OTP_WR_PL_DEPTH = 2'h3,  // SMC OTP write pipeline depth; 0 = single
                                                      // outstanding.
  parameter logic [1:0]  SEP_OTP_RD_PL_DEPTH = 2'h3,  // SEP OTP read pipeline depth; 0 = single
                                                      // outstanding.
  parameter logic [1:0]  SEP_OTP_WR_PL_DEPTH = 2'h3,  // SEP OTP write pipeline depth; 0 = single
                                                      // outstanding.
  parameter logic [1:0]  SMC_RD_PL_DEPTH     = 2'h3,  // SMC fabric read pipeline depth; 0 = single
                                                      // outstanding.
  parameter logic [1:0]  SMC_WR_PL_DEPTH     = 2'h3,  // SMC fabric write pipeline depth; 0 = single
                                                      // outstanding.

  parameter type  xtrig_axil_req_t = dtp_pkg::dtp_axil_32_32_req_t,  // Cross-trigger CSR AXI-Lite request type.
  parameter type  xtrig_axil_resp_t = dtp_pkg::dtp_axil_32_32_resp_t  // Cross-trigger CSR AXI-Lite response type.
) (
  input  logic clk_i,                           // System clock for non-JTAG logic.
  input  logic rst_n_i,                         // Active-low reset for non-JTAG logic.

  input  logic pwr_on_rst_ni,                   // Power-on reset for JTAG logic, active-low.

  input  sep_lifecycle_ctrl_pkg::dbg_disable_t  dbg_disable_i,  // Per-TAP debug/test disables from
                                                                // SEP lifecycle; active-high,
                                                                // synchronized to TCK inside.

  input  jtag_tap_ctrl_t  jtag_ptap_client_tap_ctrl_i,  // Primary JTAG TAP control.
  input  logic            jtag_ptap_client_tdi_i,  // Primary JTAG TAP TDI.
  output logic            jtag_ptap_client_tdo_o,  // Primary JTAG TAP TDO.
  output logic            jtag_ptap_client_tdo_oen_o,  // Primary JTAG TAP TDO output enable.

  output jtag_scan_ctrl_t  jtag_bsr_host_scan_ctrl_o,  // Boundary-scan host scan control Tie scan
                                                       // in to scan out if JTAG_BSR_ENABLE is
                                                       // clear.
  input  logic             jtag_bsr_host_scan_in_i,  // Boundary-scan chain input.
  output logic             jtag_bsr_host_scan_out_o,  // Boundary-scan chain output.

  output jtag_tap_ctrl_t  jtag_stap_io_host_tap_ctrl_o,  // I/O STAP host TAP control
                                                         // (chiplet-to-chiplet) Tie off with 0 if
                                                         // JTAG_STAP_IO_ENABLE is not enabled.
  input  logic            jtag_stap_io_host_tdi_i,  // I/O STAP TDI.
  output logic            jtag_stap_io_host_tdo_o,  // I/O STAP TDO.
  output logic            jtag_stap_io_host_tdo_oen_o,  // I/O STAP TDO output enable.

  output jtag_tap_ctrl_t  jtag_stap_smc_host_tap_ctrl_o,  // SMC debug STAP host TAP control Tie off
                                                          // with 0 if JTAG_SMC_DBG_ENABLE is not
                                                          // enabled.
  input  logic            jtag_stap_smc_host_tdi_i,  // SMC debug STAP TDI.
  output logic            jtag_stap_smc_host_tdo_o,  // SMC debug STAP TDO.
  output logic            jtag_stap_smc_host_tdo_oen_o,  // SMC debug STAP TDO output enable.

  output jtag_tap_ctrl_t  jtag_stap_sep_host_tap_ctrl_o,  // SEP debug STAP host TAP control Tie off
                                                          // with 0 if JTAG_SEP_DBG_ENABLE is not
                                                          // enabled.
  input  logic            jtag_stap_sep_host_tdi_i,  // SEP debug STAP TDI.
  output logic            jtag_stap_sep_host_tdo_o,  // SEP debug STAP TDO.
  output logic            jtag_stap_sep_host_tdo_oen_o,  // SEP debug STAP TDO output enable.

  output jtag_tap_ctrl_t  jtag_stap_extra_host_tap_ctrl_o [JtagNumExtraStapPorts-1:0],      // Extra STAP host TAP controls
                                                                                            // Tie off with 0 if JTAG_NUM_EXTRA_STAPS == 0.
  input  logic            jtag_stap_extra_host_tdi_i      [JtagNumExtraStapPorts-1:0],      // Extra STAP TDI bits.
  output logic            jtag_stap_extra_host_tdo_o      [JtagNumExtraStapPorts-1:0],      // Extra STAP TDO bits.
  output logic            jtag_stap_extra_host_tdo_oen_o  [JtagNumExtraStapPorts-1:0],      // Extra STAP TDO output enables.

  output jtag_scan_ctrl_t  jtag_stap_host_scan_ctrl_o,  // Extended STAP scan control
                                                        // Tie scan in to scan out if unused.
  input  logic             jtag_stap_host_scan_in_i,  // Extended STAP scan input.
  output logic             jtag_stap_host_scan_out_o,  // Extended STAP scan output.

  output jtag_scan_ctrl_t  jtag_dfd_host_scan_ctrl_o,  // External DFD iJTAG scan control
                                                       // Tie scan in to scan out if unused.
  input  logic             jtag_dfd_host_scan_in_i,  // DFD iJTAG scan input.
  output logic             jtag_dfd_host_scan_out_o,  // DFD iJTAG scan output.

  output jtag_scan_ctrl_t  jtag_dft_secure_host_scan_ctrl_o,  // Secure DFT iJTAG scan control
                                                              // Tie scan in to scan out if unused.
  input  logic             jtag_dft_secure_host_scan_in_i,  // Secure DFT iJTAG scan input.
  output logic             jtag_dft_secure_host_scan_out_o,  // Secure DFT iJTAG scan output.

  output jtag_scan_ctrl_t  jtag_dft_host_scan_ctrl_o,  // Non-secure DFT iJTAG scan control
                                                       // Tie scan in to scan out if unused.
  input  logic             jtag_dft_host_scan_in_i,  // Non-secure DFT iJTAG scan input.
  output logic             jtag_dft_host_scan_out_o,  // Non-secure DFT iJTAG scan output.

  output smc_jtag_axi_req_t   axi_smc_dbg_req_o,  // SMC fabric debug AXI manager request Tie off
                                                  // with 0 if JTAG_SMC_DBG_ENABLE is not enabled.
  input  smc_jtag_axi_resp_t  axi_smc_dbg_resp_i,  // SMC fabric debug AXI manager response.

  output smc_otp_axil_req_t   axil_smc_otp_jtag_req_o,  // SMC OTP debug AXI-Lite manager request
                                                        // Tie off with 0 if JTAG_SMC_DBG_ENABLE is
                                                        // not enabled.
  input  smc_otp_axil_resp_t  axil_smc_otp_jtag_resp_i,  // SMC OTP debug AXI-Lite manager response.

  output sep_otp_axil_req_t   axil_sep_otp_jtag_req_o,  // SEP OTP debug AXI-Lite manager request
                                                        // Tie off with 0 if JTAG_SEP_DBG_ENABLE is
                                                        // not enabled.
  input  sep_otp_axil_resp_t  axil_sep_otp_jtag_resp_i,  // SEP OTP debug AXI-Lite manager response.

  output logic  stop_clks_o,                    // Registered OR of the DEBUG_CONTROL clock stop and
                                                // xtrig_clk_stop_req_i.
  output logic  cla_clock_stop_en_o,            // CLA clock-stop enable from DEBUG_CONTROL.

  output logic  jtag_boot_stall_ovrd_o,         // Give the JTAG interface control over boot stall.
  output logic  jtag_boot_stall_o,              // Cause a boot stall when jtag_boot_stall_ovrd_o is
                                                // asserted.

  output ic_reset_smc_t  jtag_ic_reset_smc_o,   // SMC IC_RESET TDR slice (closest to TDI).
  output ic_reset_sep_t  jtag_ic_reset_sep_o,   // SEP IC_RESET TDR slice (middle of the TDR).
  output ic_reset_ext_t  jtag_ic_reset_ext_o,   // External IC_RESET TDR slice (closest to TDO).

  output tap_state_e                 jtag_ptap_state_o,  // Current primary TAP FSM state.
  output jtag_instruction_decoded_e  jtag_ptap_inst_decoded_o,  // Current primary TAP instruction
                                                                // (decoded).

  input  xtrig_axil_req_t   axil_xtrig_req_i,   // Cross-trigger CSR AXI-Lite subordinate request.
  output xtrig_axil_resp_t  axil_xtrig_resp_o,  // Cross-trigger CSR AXI-Lite subordinate response.

  output logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_src_req_o,  // CTM source requests toward sinks
                                                             // (e.g. CLA) Ack unused when the
                                                             // corresponding mode bit is 0 (pulse
                                                             // sync).
  input  logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_src_ack_i,  // Acks for CTM-sourced requests Unused
                                                             // in pulse-synchronization mode.
  input  logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_dst_req_i,  // CTM destination requests from
                                                             // sources (e.g. CLA).
  output logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_dst_ack_o,  // Acks for CTM-destined requests
                                                             // Unused in pulse-synchronization
                                                             // mode.

  input  logic [XTRIG_NUM_CLK_STOP_REQ-1:0]  xtrig_clk_stop_req_i,  // CLA or other device requests to stop the clocks.

  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_out_dout_o,  // CTP req-out pad data; connect to
                                                               // the GPIO pad ring.
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_out_dout_en_o,  // CTP req-out pad output enable.
  input  logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_out_din_i,  // CTP req-out pad input.
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_out_din_en_o,  // CTP req-out pad input enable.

  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_in_dout_o,  // CTP req-in pad data.
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_in_dout_en_o,  // CTP req-in pad output enable.
  input  logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_in_din_i,  // CTP req-in pad input.
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_in_din_en_o,  // CTP req-in pad input enable.

  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_in_dout_o,  // CTP ack-in pad data.
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_in_dout_en_o,  // CTP ack-in pad output enable.
  input  logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_in_din_i,  // CTP ack-in pad input.
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_in_din_en_o,  // CTP ack-in pad input enable.

  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_out_dout_o,  // CTP ack-out pad data.
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_out_dout_en_o,  // CTP ack-out pad output enable.
  input  logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_out_din_i,  // CTP ack-out pad input.
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_out_din_en_o,  // CTP ack-out pad input enable.

  input  logic  test_en_i,                      // DFT test-mode enable, active-high, for the
                                                // JTAG2AXI bridges and the CTN CSR crossbar.
  input  logic  scan_rst_ni                     // DFT scan reset, active-low; unused. DTP has no
                                                // reset synchronizer, so rst_n_i must arrive
                                                // scan-controlled.
);

  //--------------------------------------------------------------------------
  // Internal Signals
  //--------------------------------------------------------------------------

  logic cla_clock_stop;         // OR of incoming CLA clock stop requests for DEBUG_CONTROL readback
  logic jtag_clock_stop;      // JTAG DEBUG_CONTROL clock stop (feeds CTN halt path)

  //--------------------------------------------------------------------------
  // JTAG Interface Unit Instantiation
  //--------------------------------------------------------------------------
  jtag_intf_unit #(
    .BSR_ENABLE          (JTAG_BSR_ENABLE),
    .EXTEST_TRAIN_ENABLE (JTAG_EXTEST_TRAIN_ENABLE),
    .EXTEST_PULSE_ENABLE (JTAG_EXTEST_PULSE_ENABLE),
    .INTEST_ENABLE       (JTAG_INTEST_ENABLE),
    .CLAMP_ENABLE        (JTAG_CLAMP_ENABLE),
    .HIGHZ_ENABLE        (JTAG_HIGHZ_ENABLE),
    .RUNBIST_ENABLE      (JTAG_RUNBIST_ENABLE),
    .TMP_ENABLE          (JTAG_TMP_ENABLE),
    .IC_RESET_SMC_ENABLE (JTAG_IC_RESET_SMC_ENABLE),
    .IC_RESET_SEP_ENABLE (JTAG_IC_RESET_SEP_ENABLE),
    .IC_RESET_EXT_ENABLE (JTAG_IC_RESET_EXT_ENABLE),
    .SMC_DBG_ENABLE      (JTAG_SMC_DBG_ENABLE),
    .SEP_DBG_ENABLE      (JTAG_SEP_DBG_ENABLE),
    .STAP_IO_ENABLE      (JTAG_STAP_IO_ENABLE),
    .NUM_EXTRA_STAPS     (JTAG_NUM_EXTRA_STAPS),
    .IDCODE_MFR_ID       (JTAG_IDCODE_MFR_ID),
    .IDCODE_PART_NUM     (JTAG_IDCODE_PART_NUM),
    .IDCODE_SI_REV       (JTAG_IDCODE_SI_REV),
    .NUM_XTRIG_CTP       (XTRIG_NUM_CTP),
    .NUM_XTRIG_INT_CT    (XTRIG_NUM_INT_CT),
    .OCH_VER             (JTAG_OCH_VER),
    .jtag_tap_ctrl_t     (jtag_tap_ctrl_t),
    .jtag_scan_ctrl_t    (jtag_scan_ctrl_t),
    .ic_reset_smc_t      (ic_reset_smc_t),
    .ic_reset_sep_t      (ic_reset_sep_t),
    .ic_reset_ext_t      (ic_reset_ext_t),
    .smc_jtag_axi_req_t  (smc_jtag_axi_req_t),
    .smc_jtag_axi_resp_t (smc_jtag_axi_resp_t),
    .smc_otp_axil_req_t  (smc_otp_axil_req_t),
    .smc_otp_axil_resp_t (smc_otp_axil_resp_t),
    .sep_otp_axil_req_t  (sep_otp_axil_req_t),
    .sep_otp_axil_resp_t (sep_otp_axil_resp_t),
    .SMC_OTP_RD_PL_DEPTH (SMC_OTP_RD_PL_DEPTH),
    .SMC_OTP_WR_PL_DEPTH (SMC_OTP_WR_PL_DEPTH),
    .SEP_OTP_RD_PL_DEPTH (SEP_OTP_RD_PL_DEPTH),
    .SEP_OTP_WR_PL_DEPTH (SEP_OTP_WR_PL_DEPTH),
    .SMC_RD_PL_DEPTH     (SMC_RD_PL_DEPTH),
    .SMC_WR_PL_DEPTH     (SMC_WR_PL_DEPTH)
  ) u_jtag_intf_unit (
    .clk_i                       (clk_i),
    .rst_n_i                     (rst_n_i),
    .test_en_i                   (test_en_i),
    .pwr_on_rst_ni               (pwr_on_rst_ni),
    .dbg_disable_i               (dbg_disable_i),
    .ptap_client_tap_ctrl_i      (jtag_ptap_client_tap_ctrl_i),
    .ptap_client_tdi_i           (jtag_ptap_client_tdi_i),
    .ptap_client_tdo_o           (jtag_ptap_client_tdo_o),
    .ptap_client_tdo_oen_o       (jtag_ptap_client_tdo_oen_o),
    .bsr_host_scan_ctrl_o        (jtag_bsr_host_scan_ctrl_o),
    .bsr_host_scan_in_i          (jtag_bsr_host_scan_in_i),
    .bsr_host_scan_out_o         (jtag_bsr_host_scan_out_o),
    .stap_io_host_tap_ctrl_o     (jtag_stap_io_host_tap_ctrl_o),
    .stap_io_host_tdi_i          (jtag_stap_io_host_tdi_i),
    .stap_io_host_tdo_o          (jtag_stap_io_host_tdo_o),
    .stap_io_host_tdo_oen_o      (jtag_stap_io_host_tdo_oen_o),
    .stap_smc_host_tap_ctrl_o    (jtag_stap_smc_host_tap_ctrl_o),
    .stap_smc_host_tdi_i         (jtag_stap_smc_host_tdi_i),
    .stap_smc_host_tdo_o         (jtag_stap_smc_host_tdo_o),
    .stap_smc_host_tdo_oen_o     (jtag_stap_smc_host_tdo_oen_o),
    .stap_sep_host_tap_ctrl_o    (jtag_stap_sep_host_tap_ctrl_o),
    .stap_sep_host_tdi_i         (jtag_stap_sep_host_tdi_i),
    .stap_sep_host_tdo_o         (jtag_stap_sep_host_tdo_o),
    .stap_sep_host_tdo_oen_o     (jtag_stap_sep_host_tdo_oen_o),
    .stap_extra_host_tap_ctrl_o  (jtag_stap_extra_host_tap_ctrl_o),
    .stap_extra_host_tdi_i       (jtag_stap_extra_host_tdi_i),
    .stap_extra_host_tdo_o       (jtag_stap_extra_host_tdo_o),
    .stap_extra_host_tdo_oen_o   (jtag_stap_extra_host_tdo_oen_o),
    .stap_host_scan_ctrl_o       (jtag_stap_host_scan_ctrl_o),
    .stap_host_scan_in_i         (jtag_stap_host_scan_in_i),
    .stap_host_scan_out_o        (jtag_stap_host_scan_out_o),
    .dfd_host_scan_ctrl_o        (jtag_dfd_host_scan_ctrl_o),
    .dfd_host_scan_in_i          (jtag_dfd_host_scan_in_i),
    .dfd_host_scan_out_o         (jtag_dfd_host_scan_out_o),
    .dft_secure_host_scan_ctrl_o (jtag_dft_secure_host_scan_ctrl_o),
    .dft_secure_host_scan_in_i   (jtag_dft_secure_host_scan_in_i),
    .dft_secure_host_scan_out_o  (jtag_dft_secure_host_scan_out_o),
    .dft_host_scan_ctrl_o        (jtag_dft_host_scan_ctrl_o),
    .dft_host_scan_in_i          (jtag_dft_host_scan_in_i),
    .dft_host_scan_out_o         (jtag_dft_host_scan_out_o),
    .axi_smc_dbg_req_o           (axi_smc_dbg_req_o),
    .axi_smc_dbg_resp_i          (axi_smc_dbg_resp_i),
    .axil_smc_otp_jtag_req_o     (axil_smc_otp_jtag_req_o),
    .axil_smc_otp_jtag_resp_i    (axil_smc_otp_jtag_resp_i),
    .axil_sep_otp_jtag_req_o     (axil_sep_otp_jtag_req_o),
    .axil_sep_otp_jtag_resp_i    (axil_sep_otp_jtag_resp_i),
    .jtag_clock_stop_o           (jtag_clock_stop),
    .cla_clock_stop_i            (cla_clock_stop),
    .cla_clock_stop_en_o         (cla_clock_stop_en_o),
    .boot_stall_ovrd_o           (jtag_boot_stall_ovrd_o),
    .boot_stall_o                (jtag_boot_stall_o),
    .ic_reset_smc_o              (jtag_ic_reset_smc_o),
    .ic_reset_sep_o              (jtag_ic_reset_sep_o),
    .ic_reset_ext_o              (jtag_ic_reset_ext_o),
    .ptap_state_o                (jtag_ptap_state_o),
    .ptap_inst_decoded_o         (jtag_ptap_inst_decoded_o)
  );

  //--------------------------------------------------------------------------
  // Cross Trigger Network Instantiation
  //--------------------------------------------------------------------------

  cross_trigger_network #(
    .NUM_CTP          (XTRIG_NUM_CTP),
    .NUM_INT_CT       (XTRIG_NUM_INT_CT),
    .NUM_CLK_STOP_REQ (XTRIG_NUM_CLK_STOP_REQ),
    .INT_CT_MODE      (XTRIG_INT_CT_MODE),
    .axil_req_t       (xtrig_axil_req_t),
    .axil_resp_t      (xtrig_axil_resp_t)
  ) u_cross_trigger_network (
    .clk_i               (clk_i),
    .rst_ni              (rst_n_i),
    .test_en_i           (test_en_i),

    // AXI-Lite CSR interface
    .axil_req_i          (axil_xtrig_req_i),
    .axil_resp_o         (axil_xtrig_resp_o),

    // Clock stop control
    .clk_stop_req_i      (xtrig_clk_stop_req_i),
    .jtag_clock_stop_i   (jtag_clock_stop),
    .stop_clks_o         (stop_clks_o),
    .cla_clock_stop_o    (cla_clock_stop),

    // Internal cross trigger interface
    .ctm_src_req_o       (xtrig_ctm_src_req_o),
    .ctm_src_ack_i       (xtrig_ctm_src_ack_i),
    .ctm_dst_req_i       (xtrig_ctm_dst_req_i),
    .ctm_dst_ack_o       (xtrig_ctm_dst_ack_o),

    // External CTP GPIO interface - CT_Req_out
    .ctp_req_out_dout_o    (xtrig_ctp_req_out_dout_o),
    .ctp_req_out_dout_en_o (xtrig_ctp_req_out_dout_en_o),
    .ctp_req_out_din_i     (xtrig_ctp_req_out_din_i),
    .ctp_req_out_din_en_o  (xtrig_ctp_req_out_din_en_o),

    // External CTP GPIO interface - CT_Req_in
    .ctp_req_in_dout_o     (xtrig_ctp_req_in_dout_o),
    .ctp_req_in_dout_en_o  (xtrig_ctp_req_in_dout_en_o),
    .ctp_req_in_din_i      (xtrig_ctp_req_in_din_i),
    .ctp_req_in_din_en_o   (xtrig_ctp_req_in_din_en_o),

    // External CTP GPIO interface - CT_Ack_in
    .ctp_ack_in_dout_o     (xtrig_ctp_ack_in_dout_o),
    .ctp_ack_in_dout_en_o  (xtrig_ctp_ack_in_dout_en_o),
    .ctp_ack_in_din_i      (xtrig_ctp_ack_in_din_i),
    .ctp_ack_in_din_en_o   (xtrig_ctp_ack_in_din_en_o),

    // External CTP GPIO interface - CT_Ack_out
    .ctp_ack_out_dout_o    (xtrig_ctp_ack_out_dout_o),
    .ctp_ack_out_dout_en_o (xtrig_ctp_ack_out_dout_en_o),
    .ctp_ack_out_din_i     (xtrig_ctp_ack_out_din_i),
    .ctp_ack_out_din_en_o  (xtrig_ctp_ack_out_din_en_o)
  );

endmodule
