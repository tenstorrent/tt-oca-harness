// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Host the primary JTAG TAP and fan out scan, STAP, and debug-bridge interfaces for the chiplet.
//
// Parameters:
//
// - Enables select BSR instructions, optional EXTEST/INTEST/CLAMP/HIGHZ/RUNBIST, TMP,
//   IC_RESET slices, SMC/SEP debug, and STAP I/O.
// - NUM_EXTRA_STAPS sizes additional DTP STAPs.
// - IDCODE_* and OCH_VER program identification fields.
// - NUM_XTRIG_CTP and NUM_XTRIG_INT_CT report cross-trigger geometry in capabilities.
// - IC_RESET slice types carry .ovrd and .val members; stub defaults exist only for
//   standalone elaboration.
//
// jtag_ptap receives every parameter. Optional JTAG2AXI bridges in it reach SMC fabric AXI
// and SMC/SEP OTP AXI-Lite with programmable pipeline depths.
//
// The STAP chain runs from the PTAP STAP scan output through the I/O STAP (TDI lockup latch
// for the die crossing), the SMC debug STAP, the SEP debug STAP and the additional STAPs to
// stap_host_scan_out_o, and returns to the PTAP on stap_host_scan_in_i. A STAP whose enable is
// 0 is bypassed, and its host port drives only TCK with every other output low. The iJTAG chain
// runs from the PTAP through the secure DFT, non-secure DFT and DFD SIBs back to the PTAP.
//
// dbg_disable_i comes from the SEP lifecycle controller. Each bit passes through a two-flop TCK
// synchronizer kept out of scan and reset to 1 (disabled) by pwr_on_rst_ni, and disables one
// STAP class, SIB, JTAG2AXI bridge or the extended STAP scan interface. pwr_on_rst_ni is also
// ANDed with TRST inside the PTAP; clk_i and rst_n_i reach only the PTAP's JTAG2AXI bridges.
//
// Exported controls:
//
// - IC_RESET slices
// - boot-stall override/value
// - JTAG/CLA clock-stop controls
// - PTAP state/instruction

module jtag_intf_unit
  import prim_jtag_pkg::*;
  import jtag_tap_pkg::*;
  import jtag_inst_reg_pkg::*;
#(
  /* verilator lint_off UNUSEDPARAM */
  parameter bit  BSR_ENABLE          = 1,  // Enables all mandatory IEEE 1149.1 boundary-scan
                                           // instructions.
  parameter bit  EXTEST_TRAIN_ENABLE = 1,  // Enables the optional EXTEST_TRAIN instruction;
                                           // requires BSR_ENABLE.
  parameter bit  EXTEST_PULSE_ENABLE = 1,  // Enables the optional EXTEST_PULSE instruction;
                                           // requires BSR_ENABLE.
  parameter bit  INTEST_ENABLE       = 1,  // Enables the optional INTEST instruction; requires
                                           // BSR_ENABLE.
  parameter bit  CLAMP_ENABLE        = 1,  // Reports optional CLAMP support in JTAG_CAPS. CLAMP is
                                           // decoded on ptap_inst_decoded_o regardless of this
                                           // setting.
  parameter bit  HIGHZ_ENABLE        = 1,  // Reports optional HIGHZ support in JTAG_CAPS. HIGHZ is
                                           // decoded on ptap_inst_decoded_o regardless of this
                                           // setting.
  parameter bit  RUNBIST_ENABLE      = 1,  // Enables the optional RUNBIST instruction.
  parameter bit  TMP_ENABLE          = 1,  // Enables the TMP controller and its instructions.
  parameter bit  IC_RESET_SMC_ENABLE = 0,  // Enables the SMC slice of the IC_RESET TDR.
  parameter bit  IC_RESET_SEP_ENABLE = 0,  // Enables the SEP slice of the IC_RESET TDR.
  parameter bit  IC_RESET_EXT_ENABLE = 0,  // Enables the external slice of the IC_RESET TDR.
  parameter bit  SMC_DBG_ENABLE      = 1,  // Enables the SMC debug STAP and the JTAG2AXI bridges to
                                           // the SMC fabric and the SMC OTP.
  parameter bit  SEP_DBG_ENABLE      = 1,  // Enables the SEP debug STAP and the JTAG2AXI bridge to
                                           // the SEP OTP.
  parameter bit  STAP_IO_ENABLE      = 1,  // Enables the I/O STAP for chiplet-to-chiplet
                                           // connectivity.

  parameter int unsigned  NUM_EXTRA_STAPS = 0,  // Number of additional STAPs in the DTP for local
                                                // connectivity; at most 15.

  parameter logic [10:0]  IDCODE_MFR_ID   = 11'h000,  // JEDEC manufacturer ID reported in IDCODE.
  parameter logic [15:0]  IDCODE_PART_NUM = 16'h0000,  // Part number reported in IDCODE,
                                                       // identifying the chiplet model.
  parameter logic [3:0]   IDCODE_SI_REV   = 4'h0,  // Silicon revision reported in IDCODE.

  parameter int unsigned  NUM_XTRIG_CTP     = 8,  // Number of cross-trigger ports reported in
                                                  // JTAG_CAPS; at most 63.
  parameter int unsigned  NUM_XTRIG_INT_CT  = 1,  // Number of internal cross triggers reported in
                                                  // JTAG_CAPS; at most 63.
  parameter logic [7:0]   OCH_VER           = 8'h00,  // DTP IP major version number reported in
                                                      // JTAG_CAPS.

  localparam int unsigned  NumExtraStapPorts = (NUM_EXTRA_STAPS > 0) ? NUM_EXTRA_STAPS : 1,     // Width of the additional-STAP port arrays.
                                                                                                // It is 1 when NUM_EXTRA_STAPS is 0, and that
                                                                                                // single slot is then unused.

  parameter type  jtag_tap_ctrl_t = prim_jtag_pkg::jtag_tap_ctrl_t,  // JTAG TAP-control struct type.
  parameter type  jtag_scan_ctrl_t = prim_jtag_pkg::jtag_scan_ctrl_t,  // JTAG scan-control struct type.

  parameter type  ic_reset_smc_t = jtag_tap_pkg::jtag_ic_reset_default_t,  // SMC IC_RESET slice packed struct type.
                                                                           // Its .ovrd and .val members must have equal widths.
  parameter type  ic_reset_sep_t = jtag_tap_pkg::jtag_ic_reset_default_t,  // SEP IC_RESET slice packed struct type.
                                                                           // Its .ovrd and .val members must have equal widths.
  parameter type  ic_reset_ext_t = jtag_tap_pkg::jtag_ic_reset_default_t,  // External IC_RESET slice packed struct type.
                                                                           // Its .ovrd and .val members must have equal widths.

  parameter type  smc_jtag_axi_req_t = logic,  // SMC fabric debug AXI request type.
  parameter type  smc_jtag_axi_resp_t = logic,  // SMC fabric debug AXI response type.

  parameter type  smc_otp_axil_req_t = logic,  // SMC OTP debug AXI-Lite request type.
  parameter type  smc_otp_axil_resp_t = logic,  // SMC OTP debug AXI-Lite response type.

  parameter type  sep_otp_axil_req_t = logic,  // SEP OTP debug AXI-Lite request type.
  parameter type  sep_otp_axil_resp_t = logic,  // SEP OTP debug AXI-Lite response type.

  parameter logic [1:0]  SMC_OTP_RD_PL_DEPTH = 2'h3,  // SMC OTP read pipeline depth (0 = single
                                                      // outstanding transaction), reported in
                                                      // SMC_OTP_JTAG2AXI_CAPS. Also sets the
                                                      // bridge's largest programmable series
                                                      // pipeline depth.
  parameter logic [1:0]  SMC_OTP_WR_PL_DEPTH = 2'h3,  // SMC OTP write pipeline depth (0 = single
                                                      // outstanding transaction), reported in
                                                      // SMC_OTP_JTAG2AXI_CAPS only; it does not
                                                      // configure the bridge.
  parameter logic [1:0]  SEP_OTP_RD_PL_DEPTH = 2'h3,  // SEP OTP read pipeline depth (0 = single
                                                      // outstanding transaction), reported in
                                                      // SEP_OTP_JTAG2AXI_CAPS. Also sets the
                                                      // bridge's largest programmable series
                                                      // pipeline depth.
  parameter logic [1:0]  SEP_OTP_WR_PL_DEPTH = 2'h3,  // SEP OTP write pipeline depth (0 = single
                                                      // outstanding transaction), reported in
                                                      // SEP_OTP_JTAG2AXI_CAPS only; it does not
                                                      // configure the bridge.
  parameter logic [1:0]  SMC_RD_PL_DEPTH     = 2'h3,  // SMC fabric read pipeline depth (0 = single
                                                      // outstanding transaction), reported in
                                                      // SMC_JTAG2AXI_CAPS. Also sets the bridge's
                                                      // largest programmable series pipeline depth.
  parameter logic [1:0]  SMC_WR_PL_DEPTH     = 2'h3  // SMC fabric write pipeline depth (0 = single
                                                     // outstanding transaction), reported in
                                                     // SMC_JTAG2AXI_CAPS only; it does not
                                                     // configure the bridge.
  /* verilator lint_on UNUSEDPARAM */
) (
  input  logic clk_i,                   // System clock for the JTAG2AXI bridges.
  input  logic rst_n_i,                 // Active-low system reset for the JTAG2AXI bridges.
  input  logic test_en_i,               // DFT test-mode enable, active-high, for the JTAG2AXI
                                        // bridges.

  input  logic pwr_on_rst_ni,           // Active-low power-on reset, ANDed with TRST for the PTAP
                                        // and STAPs; sets the dbg_disable_i synchronizers to
                                        // disabled.

  input  sep_lifecycle_ctrl_pkg::dbg_disable_t  dbg_disable_i,  // Active-high per-path lifecycle
                                                                // disables, synchronized to TCK
                                                                // inside this module; all disabled
                                                                // out of reset.

  input  jtag_tap_ctrl_t  ptap_client_tap_ctrl_i,  // PTAP client TAP-control bundle: TCK, TMS, and
                                                   // active-low TRST.
  input  logic            ptap_client_tdi_i,  // PTAP client serial test data input.
  output logic            ptap_client_tdo_o,  // PTAP client serial test data output, retimed on the
                                              // falling TCK edge except during a ZERO_LENGTH_BYPASS
                                              // DR shift with the PTAP 3DCR STAP-select bit clear.
  output logic            ptap_client_tdo_oen_o,  // PTAP client TDO output enable, active-high
                                                  // during Shift-IR and Shift-DR.

  output jtag_scan_ctrl_t  bsr_host_scan_ctrl_o,  // Boundary-scan DR control, selected under EXTEST
                                                  // and SAMPLE/PRELOAD and, when enabled,
                                                  // EXTEST_TRAIN, EXTEST_PULSE and INTEST.
  input  logic             bsr_host_scan_in_i,  // Boundary-scan return, used as the PTAP TDR under
                                                // those instructions.
  output logic             bsr_host_scan_out_o,  // PTAP client TDI forwarded to the boundary-scan
                                                 // chain.

  output jtag_tap_ctrl_t  stap_io_host_tap_ctrl_o,  // I/O STAP host (chiplet-to-chiplet)
                                                    // TAP-control bundle: TCK, TMS, and active-low
                                                    // TRST. Only TCK is driven when STAP_IO_ENABLE
                                                    // is 0.
  input  logic            stap_io_host_tdi_i,  // I/O STAP host serial test data input.
  output logic            stap_io_host_tdo_o,  // I/O STAP host serial test data output.
  output logic            stap_io_host_tdo_oen_o,  // I/O STAP host TDO output enable, active-high
                                                   // while that STAP is selected and shifting.

  output jtag_tap_ctrl_t  stap_smc_host_tap_ctrl_o,  // SMC debug STAP host TAP-control bundle: TCK,
                                                     // TMS, and active-low TRST. Only TCK is driven
                                                     // when SMC_DBG_ENABLE is 0.
  input  logic            stap_smc_host_tdi_i,  // SMC debug STAP host serial test data input.
  output logic            stap_smc_host_tdo_o,  // SMC debug STAP host serial test data output.
  output logic            stap_smc_host_tdo_oen_o,  // SMC debug STAP host TDO output enable,
                                                    // active-high while that STAP is selected and
                                                    // shifting.

  output jtag_tap_ctrl_t  stap_sep_host_tap_ctrl_o,  // SEP debug STAP host TAP-control bundle: TCK,
                                                     // TMS, and active-low TRST. Only TCK is driven
                                                     // when SEP_DBG_ENABLE is 0.
  input  logic            stap_sep_host_tdi_i,  // SEP debug STAP host serial test data input.
  output logic            stap_sep_host_tdo_o,  // SEP debug STAP host serial test data output.
  output logic            stap_sep_host_tdo_oen_o,  // SEP debug STAP host TDO output enable,
                                                    // active-high while that STAP is selected and
                                                    // shifting.

  output jtag_tap_ctrl_t  stap_extra_host_tap_ctrl_o [NumExtraStapPorts-1:0],     // Additional DTP STAP host TAP-control
                                                                                  // bundle: TCK, TMS, and active-low TRST.
                                                                                  // Only TCK is driven when NUM_EXTRA_STAPS is 0.
  /* verilator lint_off UNUSEDSIGNAL */
  input  logic            stap_extra_host_tdi_i      [NumExtraStapPorts-1:0],     // Additional DTP STAP host serial test data input; unused
                                                                                  // when NUM_EXTRA_STAPS is 0.
  /* verilator lint_on UNUSEDSIGNAL */
  output logic            stap_extra_host_tdo_o      [NumExtraStapPorts-1:0],     // Additional DTP STAP host serial test data output.
  output logic            stap_extra_host_tdo_oen_o  [NumExtraStapPorts-1:0],     // Additional DTP STAP host TDO output
                                                                                  // enable, active-high while that STAP is
                                                                                  // selected and shifting.

  output jtag_scan_ctrl_t  stap_host_scan_ctrl_o,  // PTAP STAP scan control for an external STAP
                                                   // chain; select, the enables, runbist and the
                                                   // TAP-state flags are forced low while
                                                   // dbg_disable_i.stap_host is set.
  input  logic             stap_host_scan_in_i,  // External STAP chain return to the PTAP; ignored
                                                 // while dbg_disable_i.stap_host is set, when
                                                 // stap_host_scan_out_o loops back instead.
  output logic             stap_host_scan_out_o,  // Scan output of the last internal STAP, toward
                                                  // the external STAP chain.

  output jtag_scan_ctrl_t  dfd_host_scan_ctrl_o,  // DFD (TCK domain) scan control from the third
                                                  // iJTAG SIB; selected while that SIB is open,
                                                  // enables gated off by dbg_disable_i.dfd.
  input  logic             dfd_host_scan_in_i,  // DFD (TCK domain) segment return, used while the
                                                // DFD SIB is open.
  output logic             dfd_host_scan_out_o,  // DFD SIB bit toward the DFD segment; low while
                                                 // dbg_disable_i.dfd is set.

  output jtag_scan_ctrl_t  dft_secure_host_scan_ctrl_o,  // Secure DFT (TCK domain) scan control
                                                         // from the first iJTAG SIB; selected while
                                                         // that SIB is open, enables gated off by
                                                         // dbg_disable_i.dft_secure.
  input  logic             dft_secure_host_scan_in_i,  // Secure DFT (TCK domain) segment return,
                                                       // used while its SIB is open.
  output logic             dft_secure_host_scan_out_o,  // Secure DFT SIB bit toward the segment;
                                                        // low while dbg_disable_i.dft_secure is
                                                        // set.

  output jtag_scan_ctrl_t  dft_host_scan_ctrl_o,  // Non-secure DFT (TCK domain) scan control from
                                                  // the second iJTAG SIB; selected while that SIB
                                                  // is open, enables gated off by
                                                  // dbg_disable_i.dft_nonsecure.
  input  logic             dft_host_scan_in_i,  // Non-secure DFT (TCK domain) segment return, used
                                                // while its SIB is open.
  output logic             dft_host_scan_out_o,  // Non-secure DFT SIB bit toward the segment; low
                                                 // while dbg_disable_i.dft_nonsecure is set.

  output smc_jtag_axi_req_t   axi_smc_dbg_req_o,  // SMC fabric debug AXI request to the target.
  input  smc_jtag_axi_resp_t  axi_smc_dbg_resp_i,  // SMC fabric debug AXI response from the target.

  output smc_otp_axil_req_t   axil_smc_otp_jtag_req_o,  // SMC OTP debug AXI-Lite request to the
                                                        // target.
  input  smc_otp_axil_resp_t  axil_smc_otp_jtag_resp_i,  // SMC OTP debug AXI-Lite response from the
                                                         // target.

  output sep_otp_axil_req_t   axil_sep_otp_jtag_req_o,  // SEP OTP debug AXI-Lite request to the
                                                        // target.
  input  sep_otp_axil_resp_t  axil_sep_otp_jtag_resp_i,  // SEP OTP debug AXI-Lite response from the
                                                         // target.

  output logic  jtag_clock_stop_o,      // Clock-stop request from DEBUG_CONTROL.

  input  logic  cla_clock_stop_i,       // CLA clock-stop status, read back through DEBUG_CONTROL.
  output logic  cla_clock_stop_en_o,    // CLA clock-stop enable from DEBUG_CONTROL.

  output logic  boot_stall_ovrd_o,      // Enable the JTAG boot-stall override, active-high.
  output logic  boot_stall_o,           // Boot-stall value applied while boot_stall_ovrd_o is high.

  output ic_reset_smc_t  ic_reset_smc_o,  // SMC slice (closest to TDI in IC_RESET TDR); .ovrd is
                                          // active-high and .val is active-low.
  output ic_reset_sep_t  ic_reset_sep_o,  // SEP slice (middle of IC_RESET TDR); .ovrd is
                                          // active-high and .val is active-low.
  output ic_reset_ext_t  ic_reset_ext_o,  // External slice (closest to TDO in IC_RESET TDR); .ovrd
                                          // is active-high and .val is active-low.

  output tap_state_e                 ptap_state_o,  // Current PTAP controller state.
  output jtag_instruction_decoded_e  ptap_inst_decoded_o  // Decoded PTAP instruction.
);

  //--------------------------------------------------------------------------
  // Local parameters
  //--------------------------------------------------------------------------
  localparam int unsigned DbgDisableWidth = $bits(sep_lifecycle_ctrl_pkg::dbg_disable_t);

  //--------------------------------------------------------------------------
  // Internal Signals
  //--------------------------------------------------------------------------

  jtag_tap_ctrl_t  ptap_host_tap_ctrl;
  jtag_scan_ctrl_t ptap_ijtag_host_scan_ctrl;
  logic            ptap_ijtag_host_scan_in;
  logic            ptap_ijtag_host_scan_out;
  jtag_scan_ctrl_t ptap_stap_host_scan_ctrl;
  logic            ptap_stap_host_scan_in;
  logic            ptap_stap_host_scan_out;

  // STAP internal signals
  logic                      stap_io_scan_out;
  logic                      stap_smc_dbg_scan_out;
  logic                      stap_sep_dbg_scan_out;
  logic [NUM_EXTRA_STAPS:0]  extra_stap_scan_out;  // Extra STAP scan outputs (index 0 = input to first extra STAP)

  logic stap_io_security_disable;
  logic stap_smc_security_disable;
  logic stap_sep_security_disable;
  logic stap_extra_security_disable;
  logic stap_host_security_disable;
  logic dft_secure_security_disable;
  logic dft_nonsecure_security_disable;
  logic dfd_security_disable;

  logic [DbgDisableWidth-1:0]             dbg_disable_bits;
  logic [DbgDisableWidth-1:0]             dbg_disable_bits_q_n0_scan;
  sep_lifecycle_ctrl_pkg::dbg_disable_t   dbg_disable_q;

  assign dbg_disable_bits = dbg_disable_i;
  assign dbg_disable_q    = sep_lifecycle_ctrl_pkg::dbg_disable_t'(dbg_disable_bits_q_n0_scan);

  // These synchronizers are downstream of the Class 1 LC_STATE, SIP_DIS, and
  // SYS_DIS fields and directly control JTAG/test enablement. Both stages
  // must therefore remain outside scan.
  for (genvar i = 0; i < DbgDisableWidth; i++) begin : gen_dbg_disable_sync_n0_scan
    prim_flop_2sync #(
      .Width(1),
      .ResetValue(1'b1)
    ) u_dbg_disable_sync_n0_scan (
      .clk_i  (ptap_client_tap_ctrl_i.tck),
      .rst_ni (pwr_on_rst_ni),
      .d_i    (dbg_disable_bits[i]),
      .q_o    (dbg_disable_bits_q_n0_scan[i])
    );
  end

  //--------------------------------------------------------------------------
  // JTAG Primary TAP Instantiation
  //--------------------------------------------------------------------------

  jtag_ptap #(
    .BSR_ENABLE          (BSR_ENABLE),
    .EXTEST_TRAIN_ENABLE (EXTEST_TRAIN_ENABLE),
    .EXTEST_PULSE_ENABLE (EXTEST_PULSE_ENABLE),
    .INTEST_ENABLE       (INTEST_ENABLE),
    .CLAMP_ENABLE        (CLAMP_ENABLE),
    .HIGHZ_ENABLE        (HIGHZ_ENABLE),
    .RUNBIST_ENABLE      (RUNBIST_ENABLE),
    .TMP_ENABLE          (TMP_ENABLE),
    .IC_RESET_SMC_ENABLE (IC_RESET_SMC_ENABLE),
    .IC_RESET_SEP_ENABLE (IC_RESET_SEP_ENABLE),
    .IC_RESET_EXT_ENABLE (IC_RESET_EXT_ENABLE),
    .SMC_DBG_ENABLE      (SMC_DBG_ENABLE),
    .SEP_DBG_ENABLE      (SEP_DBG_ENABLE),
    .STAP_IO_ENABLE      (STAP_IO_ENABLE),
    .NUM_EXTRA_STAPS     (NUM_EXTRA_STAPS),
    .IDCODE_MFR_ID       (IDCODE_MFR_ID),
    .IDCODE_PART_NUM     (IDCODE_PART_NUM),
    .IDCODE_SI_REV       (IDCODE_SI_REV),
    .NUM_XTRIG_CTP       (NUM_XTRIG_CTP),
    .NUM_XTRIG_INT_CT    (NUM_XTRIG_INT_CT),
    .OCH_VER             (OCH_VER),
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
  ) u_jtag_ptap (
    // Standard JTAG input interface
    .client_tap_ctrl_i              (ptap_client_tap_ctrl_i),
    .client_tdi_i                   (ptap_client_tdi_i),
    .client_tdo_o                   (ptap_client_tdo_o),
    .client_tdo_oen_o               (ptap_client_tdo_oen_o),

    // Internal JTAG interface
    .host_tap_ctrl_o                (ptap_host_tap_ctrl),

    // Boundary scan interface
    .bsr_host_scan_ctrl_o           (bsr_host_scan_ctrl_o),
    .bsr_host_scan_in_i             (bsr_host_scan_in_i),
    .bsr_host_scan_out_o            (bsr_host_scan_out_o),

    // TDR scan interface (iJTAG)
    .ijtag_host_scan_ctrl_o         (ptap_ijtag_host_scan_ctrl),
    .ijtag_host_scan_in_i           (ptap_ijtag_host_scan_in),
    .ijtag_host_scan_out_o          (ptap_ijtag_host_scan_out),

    // STAP scan interface
    .stap_host_scan_ctrl_o          (ptap_stap_host_scan_ctrl),
    .stap_host_scan_in_i            (ptap_stap_host_scan_in),
    .stap_host_scan_out_o           (ptap_stap_host_scan_out),

    // Instruction decoder output
    .inst_decoded_o                 (ptap_inst_decoded_o),

    // Debug and status signals
    .current_state_o                (ptap_state_o),

    // IC Reset control outputs (typed struct slices)
    .ic_reset_smc_o                 (ic_reset_smc_o),
    .ic_reset_sep_o                 (ic_reset_sep_o),
    .ic_reset_ext_o                 (ic_reset_ext_o),

    // Debug control interface
    .cla_clock_stop_i               (cla_clock_stop_i),
    .jtag_clock_stop_o              (jtag_clock_stop_o),
    .cla_clock_stop_en_o            (cla_clock_stop_en_o),
    .boot_stall_ovrd_o              (boot_stall_ovrd_o),
    .boot_stall_o                   (boot_stall_o),

    // System clock and reset (for jtag2axi modules)
    .clk_i                          (clk_i),
    .rst_n_i                        (rst_n_i),
    .test_en_i                      (test_en_i),

    // Power-on reset (for JTAG logic)
    .pwr_on_rst_ni                  (pwr_on_rst_ni),

    // Per-bridge debug-disable bits (TCK-synced, active-high)
    .smc_jtag2axi_security_disable_i     (dbg_disable_q.smc_jtag2axi),
    .smc_otp_jtag2axi_security_disable_i (dbg_disable_q.smc_otp_jtag2axi),
    .sep_otp_jtag2axi_security_disable_i (dbg_disable_q.sep_otp_jtag2axi),

    // SMC fabric debug AXI manager interface
    .axi_smc_dbg_req_o              (axi_smc_dbg_req_o),
    .axi_smc_dbg_resp_i             (axi_smc_dbg_resp_i),

    // SMC OTP debug AXI-Lite manager interface
    .axil_smc_otp_jtag_req_o        (axil_smc_otp_jtag_req_o),
    .axil_smc_otp_jtag_resp_i       (axil_smc_otp_jtag_resp_i),

    // SEP OTP debug AXI-Lite manager interface
    .axil_sep_otp_jtag_req_o         (axil_sep_otp_jtag_req_o),
    .axil_sep_otp_jtag_resp_i        (axil_sep_otp_jtag_resp_i)
  );

  //--------------------------------------------------------------------------
  // STAP I/O Port Instantiation (Chiplet-to-Chiplet Connectivity)
  //--------------------------------------------------------------------------

  // Local wire names are preserved so downstream instances and DV probe paths stay unchanged.
  assign stap_io_security_disable       = dbg_disable_q.stap_io;
  assign stap_smc_security_disable      = dbg_disable_q.stap_smc;
  assign stap_sep_security_disable      = dbg_disable_q.stap_sep;
  assign stap_extra_security_disable    = dbg_disable_q.stap_extra;
  assign stap_host_security_disable     = dbg_disable_q.stap_host;
  assign dft_secure_security_disable    = dbg_disable_q.dft_secure;
  assign dft_nonsecure_security_disable = dbg_disable_q.dft_nonsecure;
  assign dfd_security_disable           = dbg_disable_q.dfd;

  if (STAP_IO_ENABLE) begin : gen_stap_io
    jtag_stap #(
      .SCAN_IN_PIPE        (0),
      .TDI_LOCKUP          (1),  // Enable lockup latch for die boundary crossing
      .SCAN_OUT_LOCKUP     (0),
      .jtag_scan_ctrl_t    (jtag_scan_ctrl_t),
      .jtag_tap_ctrl_t     (jtag_tap_ctrl_t)
    ) u_stap_io (
      // Client interface (from PTAP)
      .client_scan_ctrl_i  (ptap_stap_host_scan_ctrl),
      .client_scan_in_i    (ptap_stap_host_scan_out),
      .client_scan_out_o   (stap_io_scan_out),
      .client_tap_ctrl_i   (ptap_host_tap_ctrl),
      .security_disable_i  (stap_io_security_disable),

      // Host interface (to I/O pads for chiplet-to-chiplet)
      .host_tap_ctrl_o     (stap_io_host_tap_ctrl_o),
      .host_tdo_oen_o      (stap_io_host_tdo_oen_o),
      .host_tdo_o          (stap_io_host_tdo_o),
      .host_tdi_i          (stap_io_host_tdi_i)
    );
  end else begin : gen_no_stap_io
    assign stap_io_scan_out = ptap_stap_host_scan_out;
    always_comb begin
      stap_io_host_tap_ctrl_o     = '0;
      stap_io_host_tap_ctrl_o.tck = ptap_host_tap_ctrl.tck;
    end
    assign stap_io_host_tdo_oen_o = '0;
    assign stap_io_host_tdo_o = '0;
  end

  //--------------------------------------------------------------------------
  // STAP SMC Debug Port Instantiation (between I/O STAP and SEP STAP)
  //--------------------------------------------------------------------------

  if (SMC_DBG_ENABLE) begin : gen_stap_smc_dbg
    jtag_stap #(
      .SCAN_IN_PIPE        (0),
      .TDI_LOCKUP          (0),  // No lockup latch needed for on-chip connection
      .SCAN_OUT_LOCKUP     (0),
      .jtag_scan_ctrl_t    (jtag_scan_ctrl_t),
      .jtag_tap_ctrl_t     (jtag_tap_ctrl_t)
    ) u_stap_smc_dbg (
      // Client interface (from I/O STAP)
      .client_scan_ctrl_i  (ptap_stap_host_scan_ctrl),
      .client_scan_in_i    (stap_io_scan_out),
      .client_scan_out_o   (stap_smc_dbg_scan_out),
      .client_tap_ctrl_i   (ptap_host_tap_ctrl),
      .security_disable_i  (stap_smc_security_disable),

      // Host interface (to SMC CPU JTAG)
      .host_tap_ctrl_o     (stap_smc_host_tap_ctrl_o),
      .host_tdo_oen_o      (stap_smc_host_tdo_oen_o),
      .host_tdo_o          (stap_smc_host_tdo_o),
      .host_tdi_i          (stap_smc_host_tdi_i)
    );
  end else begin : gen_no_stap_smc_dbg
    assign stap_smc_dbg_scan_out = stap_io_scan_out;
    always_comb begin
      stap_smc_host_tap_ctrl_o     = '0;
      stap_smc_host_tap_ctrl_o.tck = ptap_host_tap_ctrl.tck;
    end
    assign stap_smc_host_tdo_oen_o = '0;
    assign stap_smc_host_tdo_o = '0;
  end

  //--------------------------------------------------------------------------
  // STAP SEP Debug Port Instantiation
  //--------------------------------------------------------------------------

  if (SEP_DBG_ENABLE) begin : gen_stap_sep_dbg
    jtag_stap #(
      .SCAN_IN_PIPE        (0),
      .TDI_LOCKUP          (0),  // No lockup latch needed for on-chip connection
      .SCAN_OUT_LOCKUP     (0),
      .jtag_scan_ctrl_t    (jtag_scan_ctrl_t),
      .jtag_tap_ctrl_t     (jtag_tap_ctrl_t)
    ) u_stap_sep_dbg (
      // Client interface (from SMC STAP)
      .client_scan_ctrl_i  (ptap_stap_host_scan_ctrl),
      .client_scan_in_i    (stap_smc_dbg_scan_out),
      .client_scan_out_o   (stap_sep_dbg_scan_out),
      .client_tap_ctrl_i   (ptap_host_tap_ctrl),
      .security_disable_i  (stap_sep_security_disable),

      // Host interface (to SEP debugger)
      .host_tap_ctrl_o     (stap_sep_host_tap_ctrl_o),
      .host_tdo_oen_o      (stap_sep_host_tdo_oen_o),
      .host_tdo_o          (stap_sep_host_tdo_o),
      .host_tdi_i          (stap_sep_host_tdi_i)
    );
  end else begin : gen_no_stap_sep_dbg
    assign stap_sep_dbg_scan_out = stap_smc_dbg_scan_out;
    always_comb begin
      stap_sep_host_tap_ctrl_o     = '0;
      stap_sep_host_tap_ctrl_o.tck = ptap_host_tap_ctrl.tck;
    end
    assign stap_sep_host_tdo_oen_o = '0;
    assign stap_sep_host_tdo_o = '0;
  end

  //--------------------------------------------------------------------------
  // Extra STAP Ports Instantiation (Local Connectivity)
  //--------------------------------------------------------------------------

  // Connect input to first extra STAP (from SEP STAP or I/O STAP)
  assign extra_stap_scan_out[0] = stap_sep_dbg_scan_out;

  if (NUM_EXTRA_STAPS > 0) begin : gen_extra_staps
    for (genvar i = 0; i < NUM_EXTRA_STAPS; i++) begin : gen_extra_stap
      jtag_stap #(
        .SCAN_IN_PIPE        (0),
        .TDI_LOCKUP          (0),  // No lockup latch needed for on-chip connections
        .SCAN_OUT_LOCKUP     (0),
        .jtag_scan_ctrl_t    (jtag_scan_ctrl_t),
        .jtag_tap_ctrl_t     (jtag_tap_ctrl_t)
      ) u_stap_extra (
        // Client interface (from previous STAP in chain)
        .client_scan_ctrl_i  (ptap_stap_host_scan_ctrl),
        .client_scan_in_i    (extra_stap_scan_out[i]),
        .client_scan_out_o   (extra_stap_scan_out[i+1]),
        .client_tap_ctrl_i   (ptap_host_tap_ctrl),
        .security_disable_i  (stap_extra_security_disable),

        // Host interface (to local STAP port)
        .host_tap_ctrl_o     (stap_extra_host_tap_ctrl_o[i]),
        .host_tdo_oen_o      (stap_extra_host_tdo_oen_o[i]),
        .host_tdo_o          (stap_extra_host_tdo_o[i]),
        .host_tdi_i          (stap_extra_host_tdi_i[i])
      );
    end
  end else begin : gen_no_extra_staps
    always_comb begin
      stap_extra_host_tap_ctrl_o[0]     = '0;
      stap_extra_host_tap_ctrl_o[0].tck = ptap_host_tap_ctrl.tck;
    end
    assign stap_extra_host_tdo_oen_o[0] = '0;
    assign stap_extra_host_tdo_o[0] = '0;
  end

  //--------------------------------------------------------------------------
  // Extended STAP Scan Interface
  //--------------------------------------------------------------------------

  always_comb begin
    stap_host_scan_ctrl_o = ptap_stap_host_scan_ctrl;
    if (stap_host_security_disable) begin
      stap_host_scan_ctrl_o.select           = 1'b0;
      stap_host_scan_ctrl_o.capture_en       = 1'b0;
      stap_host_scan_ctrl_o.shift_en         = 1'b0;
      stap_host_scan_ctrl_o.update_en        = 1'b0;
      stap_host_scan_ctrl_o.runbist          = 1'b0;
      stap_host_scan_ctrl_o.test_logic_reset = 1'b0;
      stap_host_scan_ctrl_o.run_test_idle    = 1'b0;
    end
  end

  assign stap_host_scan_out_o = extra_stap_scan_out[NUM_EXTRA_STAPS];
  assign ptap_stap_host_scan_in = stap_host_security_disable ?
                                    extra_stap_scan_out[NUM_EXTRA_STAPS] :
                                    stap_host_scan_in_i;

  // ============================================================================
  // iJTAG Scan Chain with SIBs
  // ============================================================================
  // Chain: PTAP iJTAG scan out -> Secure DFT SIB -> Non-secure DFT SIB -> DFD SIB -> PTAP iJTAG scan in

  // Internal signals for SIB chaining
  logic dft_secure_sib_client_scan_out;
  logic dft_nonsecure_sib_client_scan_out;
  logic dfd_sib_client_scan_out;

  // Secure DFT SIB (first in chain after PTAP)
  prim_jtag_sib_mux_post #(
    .LOCKUP      (0),
    .SAFE_SELECT (0)
  ) u_dft_secure_sib (
    // Client interface (from PTAP)
    .client_scan_ctrl_i  (ptap_ijtag_host_scan_ctrl),
    .client_scan_in_i    (ptap_ijtag_host_scan_out),
    .client_scan_out_o   (dft_secure_sib_client_scan_out),
    .security_disable_i  (dft_secure_security_disable),

    // Host interface (to external secure DFT)
    .host_scan_ctrl_o    (dft_secure_host_scan_ctrl_o),
    .host_scan_in_i      (dft_secure_host_scan_in_i),
    .host_scan_out_o     (dft_secure_host_scan_out_o)
  );

  // Non-secure DFT SIB (second in chain)
  prim_jtag_sib_mux_post #(
    .LOCKUP      (0),
    .SAFE_SELECT (0)
  ) u_dft_nonsecure_sib (
    // Client interface (from secure DFT SIB)
    .client_scan_ctrl_i  (ptap_ijtag_host_scan_ctrl),
    .client_scan_in_i    (dft_secure_sib_client_scan_out),
    .client_scan_out_o   (dft_nonsecure_sib_client_scan_out),
    .security_disable_i  (dft_nonsecure_security_disable),

    // Host interface (to external non-secure DFT)
    .host_scan_ctrl_o    (dft_host_scan_ctrl_o),
    .host_scan_in_i      (dft_host_scan_in_i),
    .host_scan_out_o     (dft_host_scan_out_o)
  );

  // DFD SIB (third in chain)
  prim_jtag_sib_mux_post #(
    .LOCKUP      (0),
    .SAFE_SELECT (0)
  ) u_dfd_sib (
    // Client interface (from non-secure DFT SIB)
    .client_scan_ctrl_i  (ptap_ijtag_host_scan_ctrl),
    .client_scan_in_i    (dft_nonsecure_sib_client_scan_out),
    .client_scan_out_o   (dfd_sib_client_scan_out),
    .security_disable_i  (dfd_security_disable),

    // Host interface (to external DFD)
    .host_scan_ctrl_o    (dfd_host_scan_ctrl_o),
    .host_scan_in_i      (dfd_host_scan_in_i),
    .host_scan_out_o     (dfd_host_scan_out_o)
  );

  // Complete the scan chain back to PTAP
  assign ptap_ijtag_host_scan_in = dfd_sib_client_scan_out;

endmodule
