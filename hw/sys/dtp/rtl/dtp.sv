// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Debug and Test Ports
//
//-----------------------------------------------------------------------------

module dtp
  import prim_jtag_pkg::*;
  import jtag_tap_pkg::*;
  import jtag_inst_reg_pkg::*;
  import cross_trigger_network_pkg::*;
  import dtp_pkg::*;
#(
  // JTAG configuration parameters
  parameter bit  JTAG_BSR_ENABLE          = 1,  // Enables all mandatory JTAG boundary scan instructions
  parameter bit  JTAG_EXTEST_TRAIN_ENABLE = 1,  // Enables optional JTAG EXTEST_TRAIN instruction
  parameter bit  JTAG_EXTEST_PULSE_ENABLE = 1,  // Enables optional JTAG EXTEST_PULSE instruction
  parameter bit  JTAG_INTEST_ENABLE       = 1,  // Enables optional JTAG INTEST instruction
  parameter bit  JTAG_CLAMP_ENABLE        = 1,  // Enables optional JTAG CLAMP instruction
  parameter bit  JTAG_HIGHZ_ENABLE        = 1,  // Enables optional JTAG HIGHZ instruction
  parameter bit  JTAG_RUNBIST_ENABLE      = 1,  // Enables optional JTAG RUNBIST instruction
  parameter bit  JTAG_TMP_ENABLE          = 1,  // Enables TMP controller functionality and instructions
  parameter bit  JTAG_IC_RESET_SMC_ENABLE = 1,  // Enables the SMC slice of the IC_RESET TDR
  parameter bit  JTAG_IC_RESET_EXT_ENABLE = 1,  // Enables the external slice of the IC_RESET TDR
  parameter bit  JTAG_SMC_DBG_ENABLE      = 1,  // Enables optional JTAG2AXI ports for the SMC debug interface
  parameter bit  JTAG_STAP_IO_ENABLE      = 1,  // Enables the STAP for chiplet-to-chiplet connectivity

  // SEP-gated slices. Declared int unsigned (not bit) so VC SpyGlass
  // `elaborate -param ...=0` can override them when generating the no-SEP DTP CDC
  // signoff abstract model; -param/-gfile cannot override bit-typed params. These
  // are driven from the SMU `SEP` parameter at the smu.sv instantiation
  // (smu.sv:543,546), so the SAM param signature must match the no-SEP SMU build.
  parameter int unsigned JTAG_IC_RESET_SEP_ENABLE = 1,  // Enables the SEP slice of the IC_RESET TDR
  parameter int unsigned JTAG_SEP_DBG_ENABLE      = 1,  // Enables optional STAP for the SEP debug interface

  parameter int unsigned  JTAG_NUM_EXTRA_STAPS = 1,  // The number of additional STAPs included in the DTP for local connectivity

  parameter logic [10:0]  JTAG_IDCODE_MFR_ID   = 11'h000,   // JTAG IDCODE manufacturer ID (11 bits)
  parameter logic [15:0]  JTAG_IDCODE_PART_NUM = 16'h0000,  // JTAG IDCODE part number (16 bits)
  parameter logic [3:0]   JTAG_IDCODE_SI_REV   = 4'h0,      // JTAG IDCODE silicon revision (4 bits)
  parameter logic [7:0]   JTAG_OCH_VER         = 8'h00,     // DTP IP major version number

  localparam int unsigned  JTAG_NUM_EXTRA_STAP_PORTS = (JTAG_NUM_EXTRA_STAPS > 0) ? JTAG_NUM_EXTRA_STAPS : 1,  // Minimum of 1 for tie-off case

  // Cross trigger port counts, from dtp_pkg
  localparam int unsigned  XTRIG_NUM_CTP          = dtp_pkg::DEFAULT_NUM_CTP,           // The number of cross trigger ports
  localparam int unsigned  XTRIG_NUM_INT_CT       = dtp_pkg::DEFAULT_NUM_INT_CT,        // Number of internal cross triggers
  localparam int unsigned  XTRIG_NUM_CLK_STOP_REQ = dtp_pkg::DEFAULT_NUM_CLK_STOP_REQ,  // The number of incoming clock stop requests

  // Cross trigger matrix signaling protocol mode parameters
  // Each bit indicates the protocol for the corresponding CTM interface:
  // 0 = simple pulse synchronization (ack signals are unused in this mode)
  // 1 = req/ack four-phase handshaking
  parameter logic [XTRIG_NUM_INT_CT-1:0]  XTRIG_INT_CT_MODE = dtp_pkg::DEFAULT_INT_CT_MODE,  // Internal cross trigger port protocol modes (default: simple pulse synchronization)

  // Type parameters for JTAG TAP and scan control
  parameter type  jtag_tap_ctrl_t = prim_jtag_pkg::jtag_tap_ctrl_t,
  parameter type  jtag_scan_ctrl_t = prim_jtag_pkg::jtag_scan_ctrl_t,

  // Type parameters for IC_RESET TDR slices (each is a packed struct with `.ovrd` and `.val`
  // sub-structs of matching width). The stub default in `jtag_tap_pkg` exists only so synthesis
  // can elaborate this module standalone; real integrators override these per slice.
  parameter type  ic_reset_smc_t = jtag_tap_pkg::jtag_ic_reset_default_t,
  parameter type  ic_reset_sep_t = jtag_tap_pkg::jtag_ic_reset_default_t,
  parameter type  ic_reset_ext_t = jtag_tap_pkg::jtag_ic_reset_default_t,

  // Type parameters for SMC fabric debug AXI interface
  // Connect to AXI fabric interface type parameters defined in the SMC packages
  parameter type  smc_jtag_axi_req_t = jtag_dbg_56_64_2_12_axi_req_t,
  parameter type  smc_jtag_axi_resp_t = jtag_dbg_56_64_2_12_axi_resp_t,

  // Type parameters for SMC OTP debug AXI-Lite interface
  // Connect to AXI fabric interface type parameters defined in the SMC packages
  parameter type  smc_otp_axil_req_t = dtp_axil_32_32_req_t,
  parameter type  smc_otp_axil_resp_t = dtp_axil_32_32_resp_t,

  // Type parameters for SEP OTP debug AXI-Lite interface
  // Connect to AXI fabric interface type parameters defined in the SEP packages
  parameter type  sep_otp_axil_req_t = dtp_axil_32_32_req_t,
  parameter type  sep_otp_axil_resp_t = dtp_axil_32_32_resp_t,

  // Pipeline depth parameters for JTAG2AXI capabilities registers
  parameter logic [1:0]  SMC_OTP_RD_PL_DEPTH = 2'h3,  // SMC OTP read pipeline depth (0 = single outstanding transaction)
  parameter logic [1:0]  SMC_OTP_WR_PL_DEPTH = 2'h3,  // SMC OTP write pipeline depth (0 = single outstanding transaction)
  parameter logic [1:0]  SEP_OTP_RD_PL_DEPTH = 2'h3,  // SEP OTP read pipeline depth (0 = single outstanding transaction)
  parameter logic [1:0]  SEP_OTP_WR_PL_DEPTH = 2'h3,  // SEP OTP write pipeline depth (0 = single outstanding transaction)
  parameter logic [1:0]  SMC_RD_PL_DEPTH     = 2'h3,  // SMC fabric read pipeline depth (0 = single outstanding transaction)
  parameter logic [1:0]  SMC_WR_PL_DEPTH     = 2'h3,  // SMC fabric write pipeline depth (0 = single outstanding transaction)

  // Type parameters for cross trigger CSR AXI-Lite interface
  // Connect to AXI fabric interface type parameters defined in the SMC packages
  parameter type  xtrig_axil_req_t = dtp_pkg::dtp_axil_32_32_req_t,
  parameter type  xtrig_axil_resp_t = dtp_pkg::dtp_axil_32_32_resp_t
) (
  // System clock and reset (non-JTAG)
  input  logic clk_i,
  input  logic rst_n_i,

  // Power-on reset (for JTAG logic)
  input  logic pwr_on_rst_ni,  // Power-on reset for JTAG logic

  // Per-TAP debug/test disables from the SEP lifecycle controller (active-high)
  input  sep_lifecycle_ctrl_pkg::dbg_disable_t  dbg_disable_i,

  // Primary JTAG TAP interface
  input  jtag_tap_ctrl_t  jtag_ptap_client_tap_ctrl_i,
  input  logic            jtag_ptap_client_tdi_i,
  output logic            jtag_ptap_client_tdo_o,
  output logic            jtag_ptap_client_tdo_oen_o,

  // Boundary scan interface - tie scan in to scan out if BSR_ENABLE is not enabled!
  output jtag_scan_ctrl_t  jtag_bsr_host_scan_ctrl_o,
  input  logic             jtag_bsr_host_scan_in_i,
  output logic             jtag_bsr_host_scan_out_o,

  // I/O STAP interface (chiplet-to-chiplet connectivity) - tie off with 0 if JTAG_STAP_IO_ENABLE is not enabled
  output jtag_tap_ctrl_t  jtag_stap_io_host_tap_ctrl_o,
  input  logic            jtag_stap_io_host_tdi_i,
  output logic            jtag_stap_io_host_tdo_o,
  output logic            jtag_stap_io_host_tdo_oen_o,

  // SMC Debug STAP interface - tie off with 0 if JTAG_SMC_DBG_ENABLE is not enabled
  output jtag_tap_ctrl_t  jtag_stap_smc_host_tap_ctrl_o,
  input  logic            jtag_stap_smc_host_tdi_i,
  output logic            jtag_stap_smc_host_tdo_o,
  output logic            jtag_stap_smc_host_tdo_oen_o,

  // SEP Debug STAP interface - tie off with 0 if JTAG_SEP_DBG_ENABLE is not enabled
  output jtag_tap_ctrl_t  jtag_stap_sep_host_tap_ctrl_o,
  input  logic            jtag_stap_sep_host_tdi_i,
  output logic            jtag_stap_sep_host_tdo_o,
  output logic            jtag_stap_sep_host_tdo_oen_o,

  // Extra STAP interfaces - tie off with 0 if JTAG_NUM_EXTRA_STAPS == 0
  output jtag_tap_ctrl_t  jtag_stap_extra_host_tap_ctrl_o [JTAG_NUM_EXTRA_STAP_PORTS-1:0],
  input  logic            jtag_stap_extra_host_tdi_i      [JTAG_NUM_EXTRA_STAP_PORTS-1:0],
  output logic            jtag_stap_extra_host_tdo_o      [JTAG_NUM_EXTRA_STAP_PORTS-1:0],
  output logic            jtag_stap_extra_host_tdo_oen_o  [JTAG_NUM_EXTRA_STAP_PORTS-1:0],

  // Extended JTAG STAP scan interface - tie scan in to scan out if not used!
  output jtag_scan_ctrl_t  jtag_stap_host_scan_ctrl_o,
  input  logic             jtag_stap_host_scan_in_i,
  output logic             jtag_stap_host_scan_out_o,

  // External DFD iJTAG interface - tie scan in to scan out if not used!
  output jtag_scan_ctrl_t  jtag_dfd_host_scan_ctrl_o,
  input  logic             jtag_dfd_host_scan_in_i,
  output logic             jtag_dfd_host_scan_out_o,

  // External secure DFT iJTAG interface - tie scan in to scan out if not used!
  output jtag_scan_ctrl_t  jtag_dft_secure_host_scan_ctrl_o,
  input  logic             jtag_dft_secure_host_scan_in_i,
  output logic             jtag_dft_secure_host_scan_out_o,

  // External non-secure DFT iJTAG interface - tie scan in to scan out if not used!
  output jtag_scan_ctrl_t  jtag_dft_host_scan_ctrl_o,
  input  logic             jtag_dft_host_scan_in_i,
  output logic             jtag_dft_host_scan_out_o,

  // SMC fabric debug AXI manager interface - tie off with 0 if JTAG_SMC_DBG_ENABLE is not enabled
  output smc_jtag_axi_req_t   axi_smc_dbg_req_o,
  input  smc_jtag_axi_resp_t  axi_smc_dbg_resp_i,

  // SMC OTP debug AXI-Lite manager interface - tie off with 0 if JTAG_SMC_DBG_ENABLE is not enabled
  output smc_otp_axil_req_t   axil_smc_otp_jtag_req_o,
  input  smc_otp_axil_resp_t  axil_smc_otp_jtag_resp_i,

  // SEP OTP debug AXI-Lite manager interface - tie off with 0 if JTAG_SEP_DBG_ENABLE is not enabled
  output sep_otp_axil_req_t   axil_sep_otp_jtag_req_o,
  input  sep_otp_axil_resp_t  axil_sep_otp_jtag_resp_i,

  // Clock control
  output logic  stop_clks_o,          // Stops clocks: JTAG DEBUG_CONTROL or CLA clock-stop requests (via CTN)
  output logic  cla_clock_stop_en_o,  // Exported CLA clock stop enable from DEBUG_CONTROL

  // JTAG boot stall control
  output logic  jtag_boot_stall_ovrd_o,  // Gives the JTAG interface control over boot stall
  output logic  jtag_boot_stall_o,       // Cause a boot stall if jtag_boot_stall_ovrd is asserted

  // JTAG reset control (typed struct slices; each contains `.ovrd` + `.val` halves)
  output ic_reset_smc_t  jtag_ic_reset_smc_o,  // SMC slice (closest to TDI in IC_RESET TDR)
  output ic_reset_sep_t  jtag_ic_reset_sep_o,  // SEP slice (middle of IC_RESET TDR)
  output ic_reset_ext_t  jtag_ic_reset_ext_o,  // External slice (closest to TDO in IC_RESET TDR)

  // JTAG internal state
  output tap_state_e                 jtag_ptap_state_o,         // Current PTAP state
  output jtag_instruction_decoded_e  jtag_ptap_inst_decoded_o,  // Current PTAP instruction (decoded)

  // Cross trigger CSR AXI-Lite subordinate interface
  input  xtrig_axil_req_t   axil_xtrig_req_i,
  output xtrig_axil_resp_t  axil_xtrig_resp_o,

  // Cross trigger matrix interface
  // Note: ack signals are unused when the corresponding mode bit is 0 (pulse synchronization mode)
  output logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_src_req_o,  // Cross trigger request signals sourced from the CTM to a cross trigger destination sink (such as a CLA)
  input  logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_src_ack_i,  // Acknowledge signals for cross trigger requests sourced from the CTM (unused in pulse sync mode)
  input  logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_dst_req_i,  // Cross trigger request signals destined for the CTM from a cross trigger source generator (such as a CLA)
  output logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_dst_ack_o,  // Acknowledge signals for cross trigger requests destined for the CTM (unused in pulse sync mode)

  // CLA clock stop interface
  input  logic [XTRIG_NUM_CLK_STOP_REQ-1:0]  xtrig_clk_stop_req_i,  // Indicates that a CLA or other device in the chiplet wants to stop the clocks

  // Cross trigger port interface - connect to the GPIO pad ring interface
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_out_dout_o,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_out_dout_en_o,
  input  logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_out_din_i,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_out_din_en_o,

  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_in_dout_o,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_in_dout_en_o,
  input  logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_in_din_i,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_req_in_din_en_o,

  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_in_dout_o,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_in_dout_en_o,
  input  logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_in_din_i,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_in_din_en_o,

  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_out_dout_o,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_out_dout_en_o,
  input  logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_out_din_i,
  output logic [XTRIG_NUM_CTP-1:0]  xtrig_ctp_ack_out_din_en_o,

  // DFT
  input  logic  test_en_i,    // DFT test-enable (scan-enable) for clock gaters inside DTP
  input  logic  scan_rst_ni   // DFT scan reset (active-low) for reset synchronizer bypass inside DTP
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
    .INT_CT_MODE      (XTRIG_INT_CT_MODE),
    .axil_req_t       (xtrig_axil_req_t),
    .axil_resp_t      (xtrig_axil_resp_t)
  ) u_cross_trigger_network (
    .clk_i               (clk_i),
    .rst_ni              (rst_n_i),

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
