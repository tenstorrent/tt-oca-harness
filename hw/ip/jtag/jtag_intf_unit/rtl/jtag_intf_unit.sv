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
// Optional JTAG2AXI bridges reach SMC fabric AXI and SMC/SEP OTP AXI-Lite with
// programmable pipeline depths.
//
// dbg_disable_i comes from the SEP lifecycle controller; pwr_on_rst_ni resets JTAG logic.
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
  parameter bit  BSR_ENABLE          = 1,  // Enables all mandatory JTAG boundary scan instructions.
  parameter bit  EXTEST_TRAIN_ENABLE = 1,  // Enables optional JTAG EXTEST_TRAIN instruction.
  parameter bit  EXTEST_PULSE_ENABLE = 1,  // Enables optional JTAG EXTEST_PULSE instruction.
  parameter bit  INTEST_ENABLE       = 1,  // Enables optional JTAG INTEST instruction.
  parameter bit  CLAMP_ENABLE        = 1,  // Enables optional JTAG CLAMP instruction.
  parameter bit  HIGHZ_ENABLE        = 1,  // Enables optional JTAG HIGHZ instruction.
  parameter bit  RUNBIST_ENABLE      = 1,  // Enables optional JTAG RUNBIST instruction.
  parameter bit  TMP_ENABLE          = 1,  // Enables TMP controller functionality and instructions.
  parameter bit  IC_RESET_SMC_ENABLE = 0,  // Enables the SMC slice of the IC_RESET TDR.
  parameter bit  IC_RESET_SEP_ENABLE = 0,  // Enables the SEP slice of the IC_RESET TDR.
  parameter bit  IC_RESET_EXT_ENABLE = 0,  // Enables the external slice of the IC_RESET TDR.
  parameter bit  SMC_DBG_ENABLE      = 1,  // Enables optional JTAG2AXI ports for the SMC debug interface.
  parameter bit  SEP_DBG_ENABLE      = 1,  // Enables optional STAP for the SEP debug interface.
  parameter bit  STAP_IO_ENABLE      = 1,  // Enables the STAP for chiplet-to-chiplet connectivity.

  parameter int unsigned  NUM_EXTRA_STAPS = 0,  // The number of additional STAPs included in the DTP for local connectivity.

  parameter logic [10:0]  IDCODE_MFR_ID   = 11'h000,  // JTAG IDCODE manufacturer ID (11 bits).
  parameter logic [15:0]  IDCODE_PART_NUM = 16'h0000,  // JTAG IDCODE part number (16 bits).
  parameter logic [3:0]   IDCODE_SI_REV   = 4'h0,  // JTAG IDCODE silicon revision (4 bits).

  parameter int unsigned  NUM_XTRIG_CTP     = 8,  // The number of cross trigger ports.
  parameter int unsigned  NUM_XTRIG_INT_CT  = 1,  // Number of internal cross triggers.
  parameter logic [7:0]   OCH_VER           = 8'h00,  // DTP IP major version number.

  localparam int unsigned  NUM_EXTRA_STAP_PORTS = (NUM_EXTRA_STAPS > 0) ? NUM_EXTRA_STAPS : 1,  // Minimum of 1 for tie-off case.

  parameter type  jtag_tap_ctrl_t = prim_jtag_pkg::jtag_tap_ctrl_t,  // JTAG TAP-control struct type.
  parameter type  jtag_scan_ctrl_t = prim_jtag_pkg::jtag_scan_ctrl_t,  // JTAG scan-control struct type.

  parameter type  ic_reset_smc_t = jtag_tap_pkg::jtag_ic_reset_default_t,  // jtag ic reset default t type.
  parameter type  ic_reset_sep_t = jtag_tap_pkg::jtag_ic_reset_default_t,  // jtag ic reset default t type.
  parameter type  ic_reset_ext_t = jtag_tap_pkg::jtag_ic_reset_default_t,  // jtag ic reset default t type.

  parameter type  smc_jtag_axi_req_t = logic,  // SMC fabric debug AXI request type.
  parameter type  smc_jtag_axi_resp_t = logic,  // SMC fabric debug AXI response type.

  parameter type  smc_otp_axil_req_t = logic,  // SMC OTP debug AXI-Lite request type.
  parameter type  smc_otp_axil_resp_t = logic,  // SMC OTP debug AXI-Lite response type.

  parameter type  sep_otp_axil_req_t = logic,  // SEP OTP debug AXI-Lite request type.
  parameter type  sep_otp_axil_resp_t = logic,  // SEP OTP debug AXI-Lite response type.

  parameter logic [1:0]  SMC_OTP_RD_PL_DEPTH = 2'h3,  // SMC OTP read pipeline depth (0 = single outstanding transaction).
  parameter logic [1:0]  SMC_OTP_WR_PL_DEPTH = 2'h3,  // SMC OTP write pipeline depth (0 = single outstanding transaction).
  parameter logic [1:0]  SEP_OTP_RD_PL_DEPTH = 2'h3,  // SEP OTP read pipeline depth (0 = single outstanding transaction).
  parameter logic [1:0]  SEP_OTP_WR_PL_DEPTH = 2'h3,  // SEP OTP write pipeline depth (0 = single outstanding transaction).
  parameter logic [1:0]  SMC_RD_PL_DEPTH     = 2'h3,  // SMC fabric read pipeline depth (0 = single outstanding transaction).
  parameter logic [1:0]  SMC_WR_PL_DEPTH     = 2'h3  // SMC fabric write pipeline depth (0 = single outstanding transaction).
  /* verilator lint_on UNUSEDPARAM */
) (
  input  logic clk_i,                   // System clock.
  input  logic rst_n_i,                 // Active-low system reset.

  input  logic pwr_on_rst_ni,           // Power-on reset for JTAG logic.

  input  sep_lifecycle_ctrl_pkg::dbg_disable_t  dbg_disable_i,  // Dbg disable.

  input  jtag_tap_ctrl_t  ptap_client_tap_ctrl_i,  // Ptap client tap ctrl (Primary JTAG TAP interface).
  input  logic            ptap_client_tdi_i,  // Ptap client tdi.
  output logic            ptap_client_tdo_o,  // Ptap client tdo.
  output logic            ptap_client_tdo_oen_o,  // Ptap client tdo oen.

  output jtag_scan_ctrl_t  bsr_host_scan_ctrl_o,  // Bsr host scan ctrl (Boundary scan interface).
  input  logic             bsr_host_scan_in_i,  // Bsr host scan in.
  output logic             bsr_host_scan_out_o,  // Bsr host scan out.

  output jtag_tap_ctrl_t  stap_io_host_tap_ctrl_o,  // Stap io host tap ctrl (I/O STAP interface (chiplet-to-chiplet connectivity)).
  input  logic            stap_io_host_tdi_i,  // Stap io host tdi.
  output logic            stap_io_host_tdo_o,  // Stap io host tdo.
  output logic            stap_io_host_tdo_oen_o,  // Stap io host tdo oen.

  output jtag_tap_ctrl_t  stap_smc_host_tap_ctrl_o,  // Stap smc host tap ctrl (SMC Debug STAP interface).
  input  logic            stap_smc_host_tdi_i,  // Stap smc host tdi.
  output logic            stap_smc_host_tdo_o,  // Stap smc host tdo.
  output logic            stap_smc_host_tdo_oen_o,  // Stap smc host tdo oen.

  output jtag_tap_ctrl_t  stap_sep_host_tap_ctrl_o,  // Stap sep host tap ctrl (SEP Debug STAP interface).
  input  logic            stap_sep_host_tdi_i,  // Stap sep host tdi.
  output logic            stap_sep_host_tdo_o,  // Stap sep host tdo.
  output logic            stap_sep_host_tdo_oen_o,  // Stap sep host tdo oen.

  output jtag_tap_ctrl_t  stap_extra_host_tap_ctrl_o [NUM_EXTRA_STAP_PORTS-1:0],  // Stap extra host tap ctrl.
  /* verilator lint_off UNUSEDSIGNAL */
  input  logic            stap_extra_host_tdi_i      [NUM_EXTRA_STAP_PORTS-1:0],  // Stap extra host tdi.
  /* verilator lint_on UNUSEDSIGNAL */
  output logic            stap_extra_host_tdo_o      [NUM_EXTRA_STAP_PORTS-1:0],  // Stap extra host tdo.
  output logic            stap_extra_host_tdo_oen_o  [NUM_EXTRA_STAP_PORTS-1:0],  // Stap extra host tdo oen.

  output jtag_scan_ctrl_t  stap_host_scan_ctrl_o,  // Stap host scan ctrl (Extended JTAG STAP scan interface).
  input  logic             stap_host_scan_in_i,  // Stap host scan in.
  output logic             stap_host_scan_out_o,  // Stap host scan out.

  output jtag_scan_ctrl_t  dfd_host_scan_ctrl_o,  // Dfd host scan ctrl (JTAG (TCK domain)).
  input  logic             dfd_host_scan_in_i,  // Dfd host scan in.
  output logic             dfd_host_scan_out_o,  // Dfd host scan out.

  output jtag_scan_ctrl_t  dft_secure_host_scan_ctrl_o,  // Dft secure host scan ctrl (JTAG (TCK domain)).
  input  logic             dft_secure_host_scan_in_i,  // Dft secure host scan in.
  output logic             dft_secure_host_scan_out_o,  // Dft secure host scan out.

  output jtag_scan_ctrl_t  dft_host_scan_ctrl_o,  // Dft host scan ctrl (JTAG (TCK domain)).
  input  logic             dft_host_scan_in_i,  // Dft host scan in.
  output logic             dft_host_scan_out_o,  // Dft host scan out.

  output smc_jtag_axi_req_t   axi_smc_dbg_req_o,  // AXI smc dbg req (SMC fabric debug AXI manager interface).
  input  smc_jtag_axi_resp_t  axi_smc_dbg_resp_i,  // AXI smc dbg resp.

  output smc_otp_axil_req_t   axil_smc_otp_jtag_req_o,  // AXI-Lite smc otp jtag req (SMC OTP debug AXI-Lite manager interface).
  input  smc_otp_axil_resp_t  axil_smc_otp_jtag_resp_i,  // AXI-Lite smc otp jtag resp.

  output sep_otp_axil_req_t   axil_sep_otp_jtag_req_o,  // AXI-Lite sep otp jtag req (SEP OTP debug AXI-Lite manager interface).
  input  sep_otp_axil_resp_t  axil_sep_otp_jtag_resp_i,  // AXI-Lite sep otp jtag resp.

  output logic  jtag_clock_stop_o,      // JTAG stop clocks signal.

  input  logic  cla_clock_stop_i,       // CLA clock stop status.
  output logic  cla_clock_stop_en_o,    // CLA clock stop enable.

  output logic  boot_stall_ovrd_o,      // Gives the JTAG interface control over boot stall.
  output logic  boot_stall_o,           // Cause a boot stall if jtag_boot_stall_ovrd is asserted.

  output ic_reset_smc_t  ic_reset_smc_o,  // SMC slice (closest to TDI in IC_RESET TDR).
  output ic_reset_sep_t  ic_reset_sep_o,  // SEP slice (middle of IC_RESET TDR).
  output ic_reset_ext_t  ic_reset_ext_o,  // External slice (closest to TDO in IC_RESET TDR).

  output tap_state_e                 ptap_state_o,  // Current PTAP state.
  output jtag_instruction_decoded_e  ptap_inst_decoded_o  // Current PTAP instruction (decoded).
);

  //--------------------------------------------------------------------------
  // Local parameters
  //--------------------------------------------------------------------------
  localparam int unsigned DBG_DISABLE_WIDTH = $bits(sep_lifecycle_ctrl_pkg::dbg_disable_t);

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

  logic [DBG_DISABLE_WIDTH-1:0]           dbg_disable_bits;
  logic [DBG_DISABLE_WIDTH-1:0]           dbg_disable_bits_q_n0_scan;
  sep_lifecycle_ctrl_pkg::dbg_disable_t   dbg_disable_q;

  assign dbg_disable_bits = dbg_disable_i;
  assign dbg_disable_q    = sep_lifecycle_ctrl_pkg::dbg_disable_t'(dbg_disable_bits_q_n0_scan);

  // These synchronizers are downstream of the Class 1 LC_STATE, SIP_DIS, and
  // SYS_DIS fields and directly control JTAG/test enablement. Both stages
  // must therefore remain outside scan.
  for (genvar i = 0; i < DBG_DISABLE_WIDTH; i++) begin : gen_dbg_disable_sync_n0_scan
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
        .SCAN_OUT_LOCKUP     (NUM_EXTRA_STAPS-1),
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
