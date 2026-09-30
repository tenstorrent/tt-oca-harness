// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Run the primary IEEE 1149.1 TAP with instruction decode, TDRs, and optional JTAG2AXI bridges.
//
// Parameter enables select BSR and optional instructions, TMP, IC_RESET slices, SMC/SEP
// debug, and STAP I/O.
//
// IC_RESET slice types have .ovrd (per-port override, active-high) and .val (per-port
// reset control, active-low) of matching width; consumers use ovrd ? val :
// upstream_reset_n. IEEE §17 reset_enable is active-low in the TDR; jtag_ic_reset_reg
// already inverts it before .ovrd, so do not re-invert here. The aggregate TDR
// concatenates SMC → SEP → EXT from TDI to TDO, then reset_hold nearest TDO.
//
// Per-bridge security_disable inputs are active-high (1 disables the bridge),
// synchronized to TCK upstream.
//
// The STAP scan interface carries both IR and DR scans while the 3DCR STAP-select bit is set, and
// TDO then comes from stap_host_scan_in_i instead of the IR or selected TDR. While the bit is
// clear, the select, capture, shift and update strobes of the STAP scan interface stay low, so
// the STAP chain holds its state through every scan. TDO is retimed on the
// falling TCK edge, except during a ZERO_LENGTH_BYPASS DR shift, where TDI reaches TDO
// combinationally.
//
// System clk_i/rst_n_i clock jtag2axi; pwr_on_rst_ni is ANDed with trst_n for the JTAG logic
// and for the TRST forwarded on host_tap_ctrl_o.

module jtag_ptap
    import prim_jtag_pkg::*;

    `include "prim_assert.sv"
    import jtag_tap_pkg::*;
    import jtag_inst_reg_pkg::*;
#(
    /* verilator lint_off UNUSEDPARAM */
    parameter bit  BSR_ENABLE          = 1,  // Enables all mandatory IEEE 1149.1 boundary-scan
                                             // instructions.
                   EXTEST_TRAIN_ENABLE = 1,  // Enables the optional EXTEST_TRAIN instruction; requires BSR_ENABLE.
                   EXTEST_PULSE_ENABLE = 1,  // Enables the optional EXTEST_PULSE instruction; requires BSR_ENABLE.
                   INTEST_ENABLE       = 1,  // Enables the optional INTEST instruction; requires BSR_ENABLE.
                   CLAMP_ENABLE        = 1,  // Reports optional CLAMP support in JTAG_CAPS.
                                             // CLAMP is decoded on inst_decoded_o regardless of this setting.
                   HIGHZ_ENABLE        = 1,  // Reports optional HIGHZ support in JTAG_CAPS.
                                             // HIGHZ is decoded on inst_decoded_o regardless of this setting.
                   RUNBIST_ENABLE      = 1,  // Enables the optional RUNBIST instruction.
                   TMP_ENABLE          = 1,  // Enables the TMP controller and its instructions.
                   IC_RESET_SMC_ENABLE = 0,  // Enables the SMC slice of the IC_RESET TDR.
                   IC_RESET_SEP_ENABLE = 0,  // Enables the SEP slice of the IC_RESET TDR.
                   IC_RESET_EXT_ENABLE = 0,  // Enables the external slice of the IC_RESET TDR.
                   SMC_DBG_ENABLE      = 1,  // Enables the JTAG2AXI bridges to the SMC fabric and the SMC OTP; reported in JTAG_CAPS.
                   SEP_DBG_ENABLE      = 1,  // Enables the JTAG2AXI bridge to the SEP OTP and reports the SEP debug STAP in JTAG_CAPS.
                   STAP_IO_ENABLE      = 1,  // Reports the chiplet-to-chiplet STAP in JTAG_CAPS.
                                             // Setting this, SEP_DBG_ENABLE, SMC_DBG_ENABLE or a nonzero NUM_EXTRA_STAPS
                                             // enables the TAP_3DCR register.

    parameter int unsigned  NUM_EXTRA_STAPS = 0,  // Number of additional STAPs in the DTP for local
                                                  // connectivity, reported in JTAG_CAPS. At most
                                                  // 15.

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

    parameter type  ic_reset_smc_t = jtag_tap_pkg::jtag_ic_reset_default_t,  // SMC IC_RESET slice packed struct type.
                                                                             // Its .ovrd and .val members must have equal widths.
    parameter type  ic_reset_sep_t = jtag_tap_pkg::jtag_ic_reset_default_t,  // SEP IC_RESET slice packed struct type.
                                                                             // Its .ovrd and .val members must have equal widths.
    parameter type  ic_reset_ext_t = jtag_tap_pkg::jtag_ic_reset_default_t,  // External IC_RESET slice packed struct type.
                                                                             // Its .ovrd and .val members must have equal widths.

    parameter type  smc_jtag_axi_req_t = logic,  // SMC fabric debug AXI interface request type.
    parameter type  smc_jtag_axi_resp_t = logic,  // SMC fabric debug AXI interface response type.
    parameter type  smc_otp_axil_req_t = logic,  // SMC OTP debug AXI-Lite interface request type.
    parameter type  smc_otp_axil_resp_t = logic,  // SMC OTP debug AXI-Lite interface response type.
    parameter type  sep_otp_axil_req_t = logic,  // SEP OTP debug AXI-Lite interface request type.
    parameter type  sep_otp_axil_resp_t = logic,  // SEP OTP debug AXI-Lite interface response type.

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
    parameter logic [1:0]  SMC_RD_PL_DEPTH     = 2'h3,  // SMC fabric read pipeline depth (0 =
                                                        // single outstanding transaction), reported
                                                        // in SMC_JTAG2AXI_CAPS. Also sets the
                                                        // bridge's largest programmable series
                                                        // pipeline depth.
    parameter logic [1:0]  SMC_WR_PL_DEPTH     = 2'h3  // SMC fabric write pipeline depth (0 =
                                                       // single outstanding transaction), reported
                                                       // in SMC_JTAG2AXI_CAPS only; it does not
                                                       // configure the bridge.
    /* verilator lint_on UNUSEDPARAM */
) (
    input  jtag_tap_ctrl_t  client_tap_ctrl_i,  // Client TAP-control bundle: TCK, TMS, and
                                                // active-low TRST.
    input  logic            client_tdi_i,  // Client serial test data input.
    output logic            client_tdo_o,  // Client serial test data output, retimed on the falling
                                           // TCK edge except during a ZERO_LENGTH_BYPASS DR shift.
    output logic            client_tdo_oen_o,  // Client TDO output enable, active-high during
                                               // Shift-IR and Shift-DR.

    output jtag_tap_ctrl_t  host_tap_ctrl_o,  // Client TCK and TMS, and client TRST ANDed with
                                              // pwr_on_rst_ni, for the STAPs.

    output jtag_scan_ctrl_t  bsr_host_scan_ctrl_o,  // Boundary-scan DR control, selected under
                                                    // EXTEST and SAMPLE/PRELOAD and, when enabled,
                                                    // EXTEST_TRAIN, EXTEST_PULSE and INTEST.
    input  logic             bsr_host_scan_in_i,  // Boundary-scan return, used as the TDR under
                                                  // those instructions.
    output logic             bsr_host_scan_out_o,  // Client TDI forwarded to the boundary-scan
                                                   // chain.

    output jtag_scan_ctrl_t  ijtag_host_scan_ctrl_o,  // iJTAG DR control, selected under
                                                      // SELECT_IJTAG and, when RUNBIST_ENABLE is
                                                      // set, RUNBIST.
    input  logic             ijtag_host_scan_in_i,  // iJTAG network return, used as the TDR under
                                                    // SELECT_IJTAG and RUNBIST.
    output logic             ijtag_host_scan_out_o,  // Client TDI forwarded to the iJTAG network.

    output jtag_scan_ctrl_t  stap_host_scan_ctrl_o,  // DR scan control with select, capture, shift
                                                     // and update ORed with the IR scan control,
                                                     // and held low while the 3DCR STAP-select
                                                     // bit is clear.
    input  logic             stap_host_scan_in_i,  // STAP chain return; drives TDO while the 3DCR
                                                   // STAP-select bit is set.
    output logic             stap_host_scan_out_o,  // IR or selected TDR output, or TDI under
                                                    // ZERO_LENGTH_BYPASS, toward the STAP chain.

    output jtag_instruction_decoded_e  inst_decoded_o,  // Decoded PTAP instruction.

    output tap_state_e  current_state_o,  // Current TAP controller state.

    output ic_reset_smc_t  ic_reset_smc_o,  // SMC slice (highest scan indices, closest to TDI);
                                            // zero when IC_RESET_SMC_ENABLE is 0.
    output ic_reset_sep_t  ic_reset_sep_o,  // SEP slice (middle scan indices); zero when
                                            // IC_RESET_SEP_ENABLE is 0.
    output ic_reset_ext_t  ic_reset_ext_o,  // External slice (lowest scan indices, closest to TDO);
                                            // zero when IC_RESET_EXT_ENABLE is 0.

    input  logic                     cla_clock_stop_i,  // CLA clock-stop status, read back through
                                                        // DEBUG_CONTROL.
    output logic                     jtag_clock_stop_o,  // Clock-stop request from DEBUG_CONTROL.
    output logic                     cla_clock_stop_en_o,  // CLA clock-stop enable from
                                                           // DEBUG_CONTROL.
    output logic                     boot_stall_ovrd_o,  // Enable the JTAG boot-stall override,
                                                         // active-high.
    output logic                     boot_stall_o,  // Boot-stall value applied while
                                                    // boot_stall_ovrd_o is high.

    input  logic                     clk_i,  // System clock for the JTAG2AXI bridges.
    input  logic                     rst_n_i,  // Active-low system reset for the JTAG2AXI bridges.

    input  logic                     pwr_on_rst_ni,  // Power-on reset (active low), ANDed with the
                                                     // client TRST.

    input  logic  smc_jtag2axi_security_disable_i,  // Active-high disable of the SMC fabric
                                                    // JTAG2AXI bridge; blocks its Update-DR and
                                                    // keeps its AXI side idle.
    input  logic  smc_otp_jtag2axi_security_disable_i,  // Active-high disable of the SMC OTP
                                                        // JTAG2AXI bridge; blocks its Update-DR and
                                                        // keeps its AXI side idle.
    input  logic  sep_otp_jtag2axi_security_disable_i,  // Active-high disable of the SEP OTP
                                                        // JTAG2AXI bridge; blocks its Update-DR and
                                                        // keeps its AXI side idle.

    output smc_jtag_axi_req_t        axi_smc_dbg_req_o,  // SMC fabric debug AXI request to the
                                                         // target.
    input  smc_jtag_axi_resp_t       axi_smc_dbg_resp_i,  // SMC fabric debug AXI response from the
                                                          // target.

    output smc_otp_axil_req_t       axil_smc_otp_jtag_req_o,  // SMC OTP debug AXI-Lite request to
                                                              // the target.
    input  smc_otp_axil_resp_t      axil_smc_otp_jtag_resp_i,  // SMC OTP debug AXI-Lite response
                                                               // from the target.

    output sep_otp_axil_req_t       axil_sep_otp_jtag_req_o,  // SEP OTP debug AXI-Lite request to
                                                              // the target.
    input  sep_otp_axil_resp_t      axil_sep_otp_jtag_resp_i  // SEP OTP debug AXI-Lite response
                                                              // from the target.
);
    //--------------------------------------------------------------------------
    // Internal Signals
    //--------------------------------------------------------------------------

    // Combined reset: power-on reset AND external trst_n
    logic jtag_trst_n;
    jtag_tap_ctrl_t client_tap_ctrl_combined;

    // Combine power-on reset with external trst_n via primitive gate to prevent glitches
    prim_and2 #(.Width(1)) u_trst_n_and (
        .in0_i (client_tap_ctrl_i.trst_n),
        .in1_i (pwr_on_rst_ni),
        .out_o (jtag_trst_n)
    );

    // Create combined TAP control with power-on reset incorporated into trst_n
    always_comb begin
        client_tap_ctrl_combined = client_tap_ctrl_i;
        client_tap_ctrl_combined.trst_n = jtag_trst_n;
    end

    jtag_scan_ctrl_t ir_scan_ctrl;                     // IR scan control (internal)
    jtag_scan_ctrl_t dr_scan_ctrl;                     // DR scan control (internal)
    jtag_scan_ctrl_t byp_reg_scan_ctrl;                // Bypass register scan control
    jtag_scan_ctrl_t inv_byp_reg_scan_ctrl;            // Inverted bypass register scan control
    jtag_scan_ctrl_t tap_3dcr_reg_scan_ctrl;           // 3DCR register scan control
    jtag_scan_ctrl_t idcode_reg_scan_ctrl;             // IDCODE register scan control
    jtag_scan_ctrl_t tmp_status_reg_scan_ctrl;         // TMP status register scan control
    jtag_scan_ctrl_t ic_reset_reg_scan_ctrl;           // IC_RESET register scan control
    jtag_scan_ctrl_t debug_ctrl_reg_scan_ctrl;         // DEBUG_CTRL register scan control
    jtag_scan_ctrl_t caps_reg_scan_ctrl;               // JTAG_CAPS register scan control
    jtag_scan_ctrl_t smc_otp_2axi_caps_reg_scan_ctrl;  // SMC_OTP_JTAG2AXI_CAPS register scan control
    jtag_scan_ctrl_t sep_otp_2axi_caps_reg_scan_ctrl;  // SEP_OTP_JTAG2AXI_CAPS register scan control
    jtag_scan_ctrl_t smc_2axi_caps_reg_scan_ctrl;      // SMC_JTAG2AXI_CAPS register scan control
    jtag_scan_ctrl_t smc_otp_jtag2axi_scan_ctrl;       // SMC OTP jtag2axi scan control
    jtag_scan_ctrl_t sep_otp_jtag2axi_scan_ctrl;       // SEP OTP jtag2axi scan control
    jtag_scan_ctrl_t smc_jtag2axi_scan_ctrl;           // SMC Fabric jtag2axi scan control

    logic inst_reg_scan_out;               // Instruction register scan chain
    logic byp_reg_scan_out;                // Bypass register scan chain
    logic inv_byp_reg_scan_out;            // Inverted bypass register scan chain
    logic tap_3dcr_reg_scan_out;           // 3DCR register scan chain
    logic idcode_reg_scan_out;             // IDCODE register scan chain
    logic tmp_status_reg_scan_out;         // TMP status register scan chain
    logic ic_reset_reg_scan_out;           // IC_RESET register scan chain
    logic debug_ctrl_reg_scan_out;         // DEBUG_CTRL register scan chain
    logic caps_reg_scan_out;               // JTAG_CAPS register scan chain
    logic smc_otp_2axi_caps_reg_scan_out;  // SMC_OTP_JTAG2AXI_CAPS register scan chain
    logic sep_otp_2axi_caps_reg_scan_out;  // SEP_OTP_JTAG2AXI_CAPS register scan chain
    logic smc_2axi_caps_reg_scan_out;      // SMC_JTAG2AXI_CAPS register scan chain

    logic persistence_mode;   // TMP persistence mode (from TMP controller)
    logic bypass_escape_bit;  // Bypass escape enable bit (from TMP status register)
    logic stap_select;        // STAP select (from 3DCR)
    logic tdr_mux;            // TDR multiplexer output
    logic tdo_mux;            // Final TDO multiplexer output (STAP or TDR)
    logic zlb_tdr_mux;        // Zero-length bypass TDR multiplexer intermediate output
    logic tdo_retimed;        // Retimed TDO output
    logic dr_scan_select_reg; // Registered DR scan select to avoid glitches

    // jtag2axi scan chain outputs
    logic smc_otp_jtag2axi_scan_out;
    logic sep_otp_jtag2axi_scan_out;
    logic smc_jtag2axi_scan_out;
    logic smc_otp_jtag2axi_security_disable;
    logic sep_otp_jtag2axi_security_disable;
    logic smc_jtag2axi_security_disable;

    // 3DCR register is only needed when STAPs are enabled
    localparam bit PTAP_3DCR_ENABLE = (STAP_IO_ENABLE != 0 || SEP_DBG_ENABLE != 0 || NUM_EXTRA_STAPS != 0 ||
                                        SMC_DBG_ENABLE != 0);

    //--------------------------------------------------------------------------
    // IC_RESET TDR Geometry
    //
    // Width of each enabled IC_RESET slice is $bits(ic_reset_*_t) / 2, which equals the width of
    // each slice's `.ovrd` (equivalently `.val`) sub-struct. The per-struct equality of
    // `$bits(.ovrd)` and `$bits(.val)` is enforced via elaboration-time asserts below. When a
    // slice is disabled its width is 0 and the matching typed output is tied to `'0`. The
    // aggregate TDR is laid out as SMC || SEP || EXT from TDI (highest scan indices) to TDO
    // (lowest scan indices), matching IEEE 1149.1 §17 which interleaves
    // `{reset_enable, reset_control}` per port.
    //--------------------------------------------------------------------------
    localparam int unsigned NUM_SMC_IC_RESET = IC_RESET_SMC_ENABLE ? ($bits(ic_reset_smc_t) / 2) : 0;
    localparam int unsigned NUM_SEP_IC_RESET = IC_RESET_SEP_ENABLE ? ($bits(ic_reset_sep_t) / 2) : 0;
    localparam int unsigned NUM_EXT_IC_RESET = IC_RESET_EXT_ENABLE ? ($bits(ic_reset_ext_t) / 2) : 0;
    localparam int unsigned NUM_IC_RESET     = NUM_SMC_IC_RESET + NUM_SEP_IC_RESET + NUM_EXT_IC_RESET;

    // Any-slice enable drives TAP-level IC_RESET instruction decode and CAPS reporting.
    localparam bit IC_RESET_ENABLE = IC_RESET_SMC_ENABLE | IC_RESET_SEP_ENABLE | IC_RESET_EXT_ENABLE;

    // Bridge disables are derived in the LCC (see sep_lifecycle_ctrl.sv).
    // Local wire names preserved so downstream instances and DV probe paths
    // are unaffected.
    assign smc_jtag2axi_security_disable     = smc_jtag2axi_security_disable_i;
    assign smc_otp_jtag2axi_security_disable = smc_otp_jtag2axi_security_disable_i;
    assign sep_otp_jtag2axi_security_disable = sep_otp_jtag2axi_security_disable_i;

    //--------------------------------------------------------------------------
    // JTAG TAP Controller Instance
    //--------------------------------------------------------------------------

    jtag_tap_ctrlr #(
        .TMP_ENABLE (TMP_ENABLE)
    ) u_jtag_tap_ctrlr (
        // Standard JTAG interface
        .client_tap_ctrl_i    (client_tap_ctrl_combined),

        // TMP controller inputs
        .persistence_mode_i   (persistence_mode),

        // RUNBIST instruction input
        .runbist_i            (inst_decoded_o[RUNBIST_INSTR] && RUNBIST_ENABLE),

        // Internal JTAG interface
        .host_tap_ctrl_o      (host_tap_ctrl_o),

        // TDR scan interface
        .host_dr_scan_ctrl_o  (dr_scan_ctrl),
        .host_ir_scan_ctrl_o  (ir_scan_ctrl),

        // Debug and status signals
        .current_state_o      (current_state_o),

        // TDO output enable
        .tdo_oen_o            (client_tdo_oen_o)
    );

    //--------------------------------------------------------------------------
    // JTAG Instruction Register Instance
    //--------------------------------------------------------------------------

    jtag_inst_reg u_jtag_inst_reg (
        // JTAG IR scan control interface
        .scan_ctrl_i         (ir_scan_ctrl),
        .scan_in_i           (client_tdi_i),
        .scan_out_o          (inst_reg_scan_out),

        // Decoded instruction output
        .inst_decoded_o      (inst_decoded_o)
    );

    //--------------------------------------------------------------------------
    // JTAG Bypass Register Instance
    //--------------------------------------------------------------------------

    // Derive bypass register scan control from DR scan control
    // Select is asserted when BYPASS or BYPASS_ALT instruction is active
    always_comb begin
        byp_reg_scan_ctrl = dr_scan_ctrl;
        unique case (1'b1)
            inst_decoded_o[BYPASS_INSTR],
            inst_decoded_o[BYPASS_ALT_INSTR],
            inst_decoded_o[CLAMP_INSTR],
            inst_decoded_o[HIGHZ_INSTR]: begin
                byp_reg_scan_ctrl.select = dr_scan_ctrl.select;
            end
            inst_decoded_o[IC_RESET_INSTR]: begin
                byp_reg_scan_ctrl.select = dr_scan_ctrl.select && !IC_RESET_ENABLE;
            end
             inst_decoded_o[EXTEST_TRAIN_INSTR]: begin
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && (!EXTEST_TRAIN_ENABLE || !BSR_ENABLE);
             end
             inst_decoded_o[EXTEST_PULSE_INSTR]: begin
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && (!EXTEST_PULSE_ENABLE || !BSR_ENABLE);
             end
             inst_decoded_o[INTEST_INSTR]: begin
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && (!INTEST_ENABLE || !BSR_ENABLE);
             end
             inst_decoded_o[EXTEST_INSTR],
             inst_decoded_o[SAMPLE_PRELOAD_INSTR]: begin
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && !BSR_ENABLE;
             end
             inst_decoded_o[TMP_STATUS_INSTR]: begin
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && !TMP_ENABLE;
             end
             inst_decoded_o[TAP_3DCR_INSTR]: begin
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && !PTAP_3DCR_ENABLE;
             end
             inst_decoded_o[RUNBIST_INSTR]: begin
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && !RUNBIST_ENABLE;
             end
             inst_decoded_o[DEBUG_CONTROL_INSTR]: begin
                 byp_reg_scan_ctrl.select = 1'b0;
             end
             inst_decoded_o[ZERO_LENGTH_BYPASS_INSTR]: begin
                 byp_reg_scan_ctrl.select = 1'b0;  // Zero-length bypass: no register, bypass handled at TDO output mux
             end
             inst_decoded_o[JTAG_CAPS_INSTR]: begin
                 byp_reg_scan_ctrl.select = 1'b0;
             end
             inst_decoded_o[SMC_OTP_JTAG2AXI_CAPS_INSTR]: begin
                 byp_reg_scan_ctrl.select = 1'b0;
             end
             inst_decoded_o[SEP_OTP_JTAG2AXI_CAPS_INSTR]: begin
                 byp_reg_scan_ctrl.select = 1'b0;
             end
             inst_decoded_o[SMC_JTAG2AXI_CAPS_INSTR]: begin
                 byp_reg_scan_ctrl.select = 1'b0;
             end
             // SMC OTP AXI instructions
             inst_decoded_o[SMC_OTP_AXI_SINGLE_OP_INSTR],
             inst_decoded_o[SMC_OTP_AXI_SERIES_CTRL_INSTR],
             inst_decoded_o[SMC_OTP_AXI_SERIES_DATA_INCR_INSTR],
             inst_decoded_o[SMC_OTP_AXI_SERIES_DATA_NO_INCR_INSTR],
             inst_decoded_o[SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR]: begin
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && !SMC_DBG_ENABLE;
             end
             // SEP OTP AXI instructions
             inst_decoded_o[SEP_OTP_AXI_SINGLE_OP_INSTR],
             inst_decoded_o[SEP_OTP_AXI_SERIES_CTRL_INSTR],
             inst_decoded_o[SEP_OTP_AXI_SERIES_DATA_INCR_INSTR],
             inst_decoded_o[SEP_OTP_AXI_SERIES_DATA_NO_INCR_INSTR],
             inst_decoded_o[SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR]: begin
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && !SEP_DBG_ENABLE;
             end
             // SMC fabric AXI instructions
             inst_decoded_o[SMC_AXI_SINGLE_OP_INSTR],
             inst_decoded_o[SMC_AXI_SERIES_CTRL_INSTR],
             inst_decoded_o[SMC_AXI_SERIES_DATA_INCR_INSTR],
             inst_decoded_o[SMC_AXI_SERIES_DATA_NO_INCR_INSTR],
             inst_decoded_o[SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR]: begin
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && !SMC_DBG_ENABLE;
             end
             default: begin
                 // All undefined instructions select bypass register
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select;
             end
        endcase
    end

    jtag_byp_reg u_jtag_byp_reg (
        // JTAG DR scan control interface
        .scan_ctrl_i  (byp_reg_scan_ctrl),
        .scan_in_i    (client_tdi_i),
        .scan_out_o   (byp_reg_scan_out)
    );

    //--------------------------------------------------------------------------
    // JTAG Inverted Bypass Register Instance
    //--------------------------------------------------------------------------

    // Derive inverted bypass register scan control from DR scan control
    // Select is asserted when INV_BYPASS instruction is active
    always_comb begin
        inv_byp_reg_scan_ctrl = dr_scan_ctrl;
        inv_byp_reg_scan_ctrl.select = dr_scan_ctrl.select &&
                                       inst_decoded_o[INV_BYPASS_INSTR];
    end

    jtag_inv_byp_reg u_jtag_inv_byp_reg (
        // JTAG DR scan control interface
        .scan_ctrl_i  (inv_byp_reg_scan_ctrl),
        .scan_in_i    (client_tdi_i),
        .scan_out_o   (inv_byp_reg_scan_out)
    );

    //--------------------------------------------------------------------------
    // JTAG IDCODE Register Instance
    //--------------------------------------------------------------------------

    // Derive IDCODE register scan control from DR scan control
    // Select is asserted when IDCODE instruction is active
    always_comb begin
        idcode_reg_scan_ctrl = dr_scan_ctrl;
        idcode_reg_scan_ctrl.select = dr_scan_ctrl.select &&
                                       inst_decoded_o[IDCODE_INSTR];
    end

    jtag_idcode_reg #(
        .IDCODE_MFR_ID   (IDCODE_MFR_ID),
        .IDCODE_PART_NUM (IDCODE_PART_NUM),
        .IDCODE_SI_REV   (IDCODE_SI_REV)
    ) u_jtag_idcode_reg (
        // JTAG DR scan control interface
        .scan_ctrl_i  (idcode_reg_scan_ctrl),
        .scan_in_i    (client_tdi_i),
        .scan_out_o   (idcode_reg_scan_out)
    );

    //--------------------------------------------------------------------------
    // JTAG 3DCR Register Instance
    //--------------------------------------------------------------------------

    // Derive 3DCR register scan control from DR scan control
    // Select is asserted when TAP_3DCR instruction is active and 3DCR is enabled
    always_comb begin
        tap_3dcr_reg_scan_ctrl = dr_scan_ctrl;
        tap_3dcr_reg_scan_ctrl.select = dr_scan_ctrl.select && PTAP_3DCR_ENABLE &&
                                         inst_decoded_o[TAP_3DCR_INSTR];
    end

    if (PTAP_3DCR_ENABLE) begin : gen_tap_3dcr_reg
    jtag_3dcr_reg u_jtag_3dcr_reg (
        // JTAG DR scan control interface
        .scan_ctrl_i  (tap_3dcr_reg_scan_ctrl),
        .scan_in_i    (client_tdi_i),
        .scan_out_o   (tap_3dcr_reg_scan_out),

        // JTAG TAP control interface
        .tap_ctrl_i   (host_tap_ctrl_o),

        // STAP control output
        .stap_sel_o   (stap_select)
    );
    end else begin : gen_tap_3dcr_tie_off
        assign stap_select = 1'b0;
        assign tap_3dcr_reg_scan_out = 1'b0;
    end

    //--------------------------------------------------------------------------
    // TDR Scan Control and Data Outputs
    //--------------------------------------------------------------------------

    // BSR scan control
    always_comb begin
        bsr_host_scan_ctrl_o = dr_scan_ctrl;
        unique case (1'b1)
            inst_decoded_o[EXTEST_INSTR],
            inst_decoded_o[SAMPLE_PRELOAD_INSTR]:
                bsr_host_scan_ctrl_o.select = dr_scan_ctrl.select && BSR_ENABLE;
            inst_decoded_o[EXTEST_TRAIN_INSTR]:
                bsr_host_scan_ctrl_o.select = dr_scan_ctrl.select && BSR_ENABLE && EXTEST_TRAIN_ENABLE;
            inst_decoded_o[EXTEST_PULSE_INSTR]:
                bsr_host_scan_ctrl_o.select = dr_scan_ctrl.select && BSR_ENABLE && EXTEST_PULSE_ENABLE;
            inst_decoded_o[INTEST_INSTR]:
                bsr_host_scan_ctrl_o.select = dr_scan_ctrl.select && BSR_ENABLE && INTEST_ENABLE;
            default:
                bsr_host_scan_ctrl_o.select = 1'b0;
        endcase
    end

    // iJTAG scan control
    always_comb begin
        ijtag_host_scan_ctrl_o = dr_scan_ctrl;
        unique case (1'b1)
            inst_decoded_o[SELECT_IJTAG_INSTR]:
                ijtag_host_scan_ctrl_o.select = dr_scan_ctrl.select;
            inst_decoded_o[RUNBIST_INSTR]:
                ijtag_host_scan_ctrl_o.select = dr_scan_ctrl.select && RUNBIST_ENABLE;
            default:
                ijtag_host_scan_ctrl_o.select = 1'b0;
        endcase
    end

    // SMC OTP jtag2axi scan control
    always_comb begin
        smc_otp_jtag2axi_scan_ctrl = dr_scan_ctrl;
        unique case (1'b1)
            inst_decoded_o[SMC_OTP_AXI_SINGLE_OP_INSTR],
            inst_decoded_o[SMC_OTP_AXI_SERIES_CTRL_INSTR],
            inst_decoded_o[SMC_OTP_AXI_SERIES_DATA_INCR_INSTR],
            inst_decoded_o[SMC_OTP_AXI_SERIES_DATA_NO_INCR_INSTR],
            inst_decoded_o[SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR]:
                smc_otp_jtag2axi_scan_ctrl.select = dr_scan_ctrl.select && SMC_DBG_ENABLE;
            default:
                smc_otp_jtag2axi_scan_ctrl.select = 1'b0;
        endcase
    end

    // SEP OTP jtag2axi scan control
    always_comb begin
        sep_otp_jtag2axi_scan_ctrl = dr_scan_ctrl;
        unique case (1'b1)
            inst_decoded_o[SEP_OTP_AXI_SINGLE_OP_INSTR],
            inst_decoded_o[SEP_OTP_AXI_SERIES_CTRL_INSTR],
            inst_decoded_o[SEP_OTP_AXI_SERIES_DATA_INCR_INSTR],
            inst_decoded_o[SEP_OTP_AXI_SERIES_DATA_NO_INCR_INSTR],
            inst_decoded_o[SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR]:
                sep_otp_jtag2axi_scan_ctrl.select = dr_scan_ctrl.select && SEP_DBG_ENABLE;
            default:
                sep_otp_jtag2axi_scan_ctrl.select = 1'b0;
        endcase
    end

    // SMC Fabric jtag2axi scan control
    always_comb begin
        smc_jtag2axi_scan_ctrl = dr_scan_ctrl;
        unique case (1'b1)
            inst_decoded_o[SMC_AXI_SINGLE_OP_INSTR],
            inst_decoded_o[SMC_AXI_SERIES_CTRL_INSTR],
            inst_decoded_o[SMC_AXI_SERIES_DATA_INCR_INSTR],
            inst_decoded_o[SMC_AXI_SERIES_DATA_NO_INCR_INSTR],
            inst_decoded_o[SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR]:
                smc_jtag2axi_scan_ctrl.select = dr_scan_ctrl.select && SMC_DBG_ENABLE;
            default:
                smc_jtag2axi_scan_ctrl.select = 1'b0;
        endcase
    end

    // Forward TDI to TDR scan chains
    assign bsr_host_scan_out_o   = client_tdi_i;
    assign ijtag_host_scan_out_o = client_tdi_i;

    //--------------------------------------------------------------------------
    // TMP Controller Instance
    //--------------------------------------------------------------------------

    if (TMP_ENABLE) begin : gen_tmp_controller
    jtag_tmp u_jtag_tmp (
        // TAP control interface
        .tap_ctrl_i              (host_tap_ctrl_o),

        // IR update signal (from TAP controller)
        .update_ir_i             (ir_scan_ctrl.update_en),

        // Test logic reset (from TAP controller state)
        .test_logic_reset_i      (dr_scan_ctrl.test_logic_reset),

        // Centralized instruction decoding inputs
        .clamp_hold_selected_i   (inst_decoded_o[CLAMP_HOLD_INSTR]),
        .clamp_release_selected_i(inst_decoded_o[CLAMP_RELEASE_INSTR]),
        .bypass_selected_i       (inst_decoded_o[BYPASS_INSTR] ||
                                  inst_decoded_o[BYPASS_ALT_INSTR]),

        // TMP controller status outputs
        .persistence_mode_o      (persistence_mode),

        // TMP status register input
        .bypass_escape_enable_i  (bypass_escape_bit)
    );
    end else begin : gen_tmp_tie_off
        assign persistence_mode = 1'b0;
    end

    //--------------------------------------------------------------------------
    // TMP Status Register Instance
    //--------------------------------------------------------------------------

    // Derive TMP status register scan control from DR scan control
    // Select is asserted when TMP_STATUS instruction is active and TMP_ENABLE is 1
    always_comb begin
        tmp_status_reg_scan_ctrl = dr_scan_ctrl;
        tmp_status_reg_scan_ctrl.select = dr_scan_ctrl.select && TMP_ENABLE &&
                                         inst_decoded_o[TMP_STATUS_INSTR];
    end

    if (TMP_ENABLE) begin : gen_tmp_status_reg
    jtag_tmp_status_reg u_jtag_tmp_status_reg (
        // JTAG DR scan control interface
        .scan_ctrl_i         (tmp_status_reg_scan_ctrl),
        .scan_in_i           (client_tdi_i),
        .scan_out_o          (tmp_status_reg_scan_out),

        // TMP controller state input
        .persistence_mode_i  (persistence_mode),

        // TMP status output
        .bypass_escape_bit_o  (bypass_escape_bit)
    );
    end else begin : gen_tmp_status_tie_off
        assign bypass_escape_bit = 1'b0;
        assign tmp_status_reg_scan_out = 1'b0;
    end

    //--------------------------------------------------------------------------
    // JTAG IC_RESET Register Instance
    //--------------------------------------------------------------------------

    // Derive IC_RESET register scan control from DR scan control
    // Select is asserted when IC_RESET instruction is active
    always_comb begin
        ic_reset_reg_scan_ctrl = dr_scan_ctrl;
        ic_reset_reg_scan_ctrl.select = dr_scan_ctrl.select &&
                                       inst_decoded_o[IC_RESET_INSTR];
    end

    // Combined per-port scan outputs from jtag_ic_reset_reg, sliced into typed struct outputs
    // below. Index layout (high → low, matches TDI → TDO):
    //   SMC bits : [NUM_IC_RESET-1              : NUM_SEP_IC_RESET+NUM_EXT_IC_RESET]
    //   SEP bits : [NUM_SEP_IC_RESET+NUM_EXT_IC_RESET-1 : NUM_EXT_IC_RESET]
    //   EXT bits : [NUM_EXT_IC_RESET-1          : 0]
    //
    // POLARITY: `ic_reset_ovrd_bus` is the ACTIVE-HIGH override signal
    // (i.e. `!reset_enable`) as emitted by jtag_ic_reset_reg; it is *not* the
    // raw IEEE §17 `reset_enable` TDR field. See `jtag_ic_reset_reg` header
    // for the full convention. The bus is forwarded verbatim into the
    // downstream `.ovrd` struct members below — no further inversion.
    logic [((NUM_IC_RESET == 0) ? 0 : NUM_IC_RESET-1):0]  ic_reset_ovrd_bus;
    logic [((NUM_IC_RESET == 0) ? 0 : NUM_IC_RESET-1):0]  ic_reset_ctrl_n_bus;

    if (IC_RESET_ENABLE && (NUM_IC_RESET > 0)) begin : gen_ic_reset_reg
        jtag_ic_reset_reg #(
            .NUM_IC_RESET_PORTS(NUM_IC_RESET)
        ) u_jtag_ic_reset_reg (
            // JTAG DR scan control interface
            .scan_ctrl_i   (ic_reset_reg_scan_ctrl),
            .scan_in_i     (client_tdi_i),
            .scan_out_o    (ic_reset_reg_scan_out),

            // JTAG TAP control interface
            .tap_ctrl_i    (host_tap_ctrl_o),

            // IC Reset control outputs
            .ic_reset_ovrd_o    (ic_reset_ovrd_bus),
            .ic_reset_ctrl_n_o  (ic_reset_ctrl_n_bus)
        );
    end else begin : gen_ic_reset_tie_off
        assign ic_reset_ovrd_bus     = '0;
        assign ic_reset_ctrl_n_bus   = '1;
        assign ic_reset_reg_scan_out = 1'b0;
    end

    //--------------------------------------------------------------------------
    // IC_RESET Slice Packing / Elaboration Checks
    //
    // Pack the raw `{ovrd, ctrl_n}` port buses from jtag_ic_reset_reg into the three typed
    // struct outputs. Each struct's `.ovrd` / `.val` sub-structs must have identical bit widths
    // (enforced via `$bits` elaboration asserts) so that the SV bit-for-bit assignment is
    // unambiguous.
    //--------------------------------------------------------------------------
    if (IC_RESET_SMC_ENABLE) begin : gen_ic_reset_smc_pack
        ic_reset_smc_t smc_width_probe;
        `OCAH_OT_ASSERT_STATIC_LINT_ERROR(IcResetSmcOvrdValWidthMatch_A,
                                  $bits(smc_width_probe.ovrd) == $bits(smc_width_probe.val))

        ic_reset_smc_t smc_w;
        assign smc_w.ovrd = ic_reset_ovrd_bus[NUM_IC_RESET-1 -: NUM_SMC_IC_RESET];
        assign smc_w.val  = ic_reset_ctrl_n_bus[NUM_IC_RESET-1 -: NUM_SMC_IC_RESET];
        assign ic_reset_smc_o = smc_w;
    end else begin : gen_ic_reset_smc_tie
        assign ic_reset_smc_o = '0;
    end

    if (IC_RESET_SEP_ENABLE) begin : gen_ic_reset_sep_pack
        ic_reset_sep_t sep_width_probe;
        `OCAH_OT_ASSERT_STATIC_LINT_ERROR(IcResetSepOvrdValWidthMatch_A,
                                  $bits(sep_width_probe.ovrd) == $bits(sep_width_probe.val))

        ic_reset_sep_t sep_w;
        assign sep_w.ovrd = ic_reset_ovrd_bus[NUM_SEP_IC_RESET+NUM_EXT_IC_RESET-1 -: NUM_SEP_IC_RESET];
        assign sep_w.val  = ic_reset_ctrl_n_bus[NUM_SEP_IC_RESET+NUM_EXT_IC_RESET-1 -: NUM_SEP_IC_RESET];
        assign ic_reset_sep_o = sep_w;
    end else begin : gen_ic_reset_sep_tie
        assign ic_reset_sep_o = '0;
    end

    if (IC_RESET_EXT_ENABLE) begin : gen_ic_reset_ext_pack
        ic_reset_ext_t ext_width_probe;
        `OCAH_OT_ASSERT_STATIC_LINT_ERROR(IcResetExtOvrdValWidthMatch_A,
                                  $bits(ext_width_probe.ovrd) == $bits(ext_width_probe.val))

        ic_reset_ext_t ext_w;
        assign ext_w.ovrd = ic_reset_ovrd_bus[NUM_EXT_IC_RESET-1 -: NUM_EXT_IC_RESET];
        assign ext_w.val  = ic_reset_ctrl_n_bus[NUM_EXT_IC_RESET-1 -: NUM_EXT_IC_RESET];
        assign ic_reset_ext_o = ext_w;
    end else begin : gen_ic_reset_ext_tie
        assign ic_reset_ext_o = '0;
    end

    //--------------------------------------------------------------------------
    // JTAG DEBUG_CTRL Register Instance
    //--------------------------------------------------------------------------

    // Derive DEBUG_CTRL register scan control from DR scan control
    // Select is asserted when DEBUG_CONTROL instruction is active
    always_comb begin
        debug_ctrl_reg_scan_ctrl = dr_scan_ctrl;
        debug_ctrl_reg_scan_ctrl.select = dr_scan_ctrl.select &&
                                          inst_decoded_o[DEBUG_CONTROL_INSTR];
    end

    jtag_debug_ctrl_reg u_jtag_debug_ctrl_reg (
        // JTAG DR scan control interface
        .scan_ctrl_i         (debug_ctrl_reg_scan_ctrl),
        .scan_in_i           (client_tdi_i),
        .scan_out_o          (debug_ctrl_reg_scan_out),

        // Read-only status input
        .cla_clock_stop_i     (cla_clock_stop_i),

        // Debug control outputs
        .jtag_clock_stop_o   (jtag_clock_stop_o),
        .cla_clock_stop_en_o (cla_clock_stop_en_o),
        .boot_stall_ovrd_o   (boot_stall_ovrd_o),
        .boot_stall_o        (boot_stall_o)
    );

    //--------------------------------------------------------------------------
    // JTAG JTAG_CAPS Register Instance
    //--------------------------------------------------------------------------

    // Derive JTAG_CAPS register scan control from DR scan control
    // Select is asserted when JTAG_CAPS instruction is active
    always_comb begin
        caps_reg_scan_ctrl = dr_scan_ctrl;
        caps_reg_scan_ctrl.select = dr_scan_ctrl.select &&
                                     inst_decoded_o[JTAG_CAPS_INSTR];
    end

    jtag_caps_reg #(
        .BSR_ENABLE          (BSR_ENABLE),
        .EXTEST_TRAIN_ENABLE (EXTEST_TRAIN_ENABLE),
        .EXTEST_PULSE_ENABLE (EXTEST_PULSE_ENABLE),
        .INTEST_ENABLE       (INTEST_ENABLE),
        .CLAMP_ENABLE        (CLAMP_ENABLE),
        .HIGHZ_ENABLE        (HIGHZ_ENABLE),
        .RUNBIST_ENABLE      (RUNBIST_ENABLE),
        .TMP_ENABLE          (TMP_ENABLE),
        .IC_RESET_ENABLE     (IC_RESET_ENABLE),
        .SMC_DBG_ENABLE      (SMC_DBG_ENABLE),
        .SEP_DBG_ENABLE      (SEP_DBG_ENABLE),
        .STAP_IO_ENABLE      (STAP_IO_ENABLE),
        .NUM_SMC_IC_RESET    (NUM_SMC_IC_RESET),
        .NUM_SEP_IC_RESET    (NUM_SEP_IC_RESET),
        .NUM_EXT_IC_RESET    (NUM_EXT_IC_RESET),
        .NUM_EXTRA_STAPS     (NUM_EXTRA_STAPS),
        .NUM_XTRIG_CTP       (NUM_XTRIG_CTP),
        .NUM_XTRIG_INT_CT    (NUM_XTRIG_INT_CT),
        .OCH_VER             (OCH_VER)
    ) u_jtag_caps_reg (
        // JTAG DR scan control interface
        .scan_ctrl_i   (caps_reg_scan_ctrl),
        .scan_in_i     (client_tdi_i),
        .scan_out_o    (caps_reg_scan_out)
    );

    //--------------------------------------------------------------------------
    // SMC OTP JTAG2AXI Capabilities Register Instance
    //--------------------------------------------------------------------------

    // Derive SMC_OTP_JTAG2AXI_CAPS register scan control from DR scan control
    // Select is asserted when SMC_OTP_JTAG2AXI_CAPS instruction is active
    always_comb begin
        smc_otp_2axi_caps_reg_scan_ctrl = dr_scan_ctrl;
        smc_otp_2axi_caps_reg_scan_ctrl.select = dr_scan_ctrl.select &&
                                                 inst_decoded_o[SMC_OTP_JTAG2AXI_CAPS_INSTR];
    end

    jtag_jtag2axi_caps_reg #(
        .axi_req_t     (smc_otp_axil_req_t),
        .RD_PL_DEPTH   (SMC_OTP_RD_PL_DEPTH),
        .WR_PL_DEPTH   (SMC_OTP_WR_PL_DEPTH),
        .IS_AXI4_LITE  (1'b1)
    ) u_smc_otp_2axi_caps_reg (
        // JTAG DR scan control interface
        .scan_ctrl_i   (smc_otp_2axi_caps_reg_scan_ctrl),
        .scan_in_i     (client_tdi_i),
        .scan_out_o    (smc_otp_2axi_caps_reg_scan_out)
    );

    //--------------------------------------------------------------------------
    // SEP OTP JTAG2AXI Capabilities Register Instance
    //--------------------------------------------------------------------------

    // Derive SEP_OTP_JTAG2AXI_CAPS register scan control from DR scan control
    // Select is asserted when SEP_OTP_JTAG2AXI_CAPS instruction is active
    always_comb begin
        sep_otp_2axi_caps_reg_scan_ctrl = dr_scan_ctrl;
        sep_otp_2axi_caps_reg_scan_ctrl.select = dr_scan_ctrl.select &&
                                                 inst_decoded_o[SEP_OTP_JTAG2AXI_CAPS_INSTR];
    end

    jtag_jtag2axi_caps_reg #(
        .axi_req_t     (sep_otp_axil_req_t),
        .RD_PL_DEPTH   (SEP_OTP_RD_PL_DEPTH),
        .WR_PL_DEPTH   (SEP_OTP_WR_PL_DEPTH),
        .IS_AXI4_LITE  (1'b1)
    ) u_sep_otp_2axi_caps_reg (
        // JTAG DR scan control interface
        .scan_ctrl_i   (sep_otp_2axi_caps_reg_scan_ctrl),
        .scan_in_i     (client_tdi_i),
        .scan_out_o    (sep_otp_2axi_caps_reg_scan_out)
    );

    //--------------------------------------------------------------------------
    // SMC Fabric JTAG2AXI Capabilities Register Instance
    //--------------------------------------------------------------------------

    // Derive SMC_JTAG2AXI_CAPS register scan control from DR scan control
    // Select is asserted when SMC_JTAG2AXI_CAPS instruction is active
    always_comb begin
        smc_2axi_caps_reg_scan_ctrl = dr_scan_ctrl;
        smc_2axi_caps_reg_scan_ctrl.select = dr_scan_ctrl.select &&
                                            inst_decoded_o[SMC_JTAG2AXI_CAPS_INSTR];
    end

    jtag_jtag2axi_caps_reg #(
        .axi_req_t     (smc_jtag_axi_req_t),
        .RD_PL_DEPTH   (SMC_RD_PL_DEPTH),
        .WR_PL_DEPTH   (SMC_WR_PL_DEPTH),
        .IS_AXI4_LITE  (1'b0)
    ) u_smc_2axi_caps_reg (
        // JTAG DR scan control interface
        .scan_ctrl_i   (smc_2axi_caps_reg_scan_ctrl),
        .scan_in_i     (client_tdi_i),
        .scan_out_o    (smc_2axi_caps_reg_scan_out)
    );

    //--------------------------------------------------------------------------
    // Extract AXI Parameters from Type Parameters
    //--------------------------------------------------------------------------

    // SMC OTP AXI-Lite
    smc_otp_axil_req_t  smc_otp_dummy_req;
    localparam int unsigned SMC_OTP_ADDR_WIDTH = $bits(smc_otp_dummy_req.aw.addr);
    localparam int unsigned SMC_OTP_DATA_WIDTH = $bits(smc_otp_dummy_req.w.data);
    localparam int unsigned SMC_OTP_ID_WIDTH   = 1;  // AXI4-Lite has no ID
    localparam int unsigned SMC_OTP_USER_WIDTH = 1;  // Minimal user width

    // SEP OTP AXI-Lite
    sep_otp_axil_req_t  sep_otp_dummy_req;
    localparam int unsigned SEP_OTP_ADDR_WIDTH = $bits(sep_otp_dummy_req.aw.addr);
    localparam int unsigned SEP_OTP_DATA_WIDTH = $bits(sep_otp_dummy_req.w.data);
    localparam int unsigned SEP_OTP_ID_WIDTH   = 1;  // AXI4-Lite has no ID
    localparam int unsigned SEP_OTP_USER_WIDTH = 1;  // Minimal user width

    // SMC Fabric AXI
    smc_jtag_axi_req_t  smc_dummy_req;
    localparam int unsigned SMC_ADDR_WIDTH = $bits(smc_dummy_req.aw.addr);
    localparam int unsigned SMC_DATA_WIDTH = $bits(smc_dummy_req.w.data);
    localparam int unsigned SMC_ID_WIDTH   = $bits(smc_dummy_req.aw.id);
    localparam int unsigned SMC_USER_WIDTH = $bits(smc_dummy_req.aw.user);

    //--------------------------------------------------------------------------
    // jtag2axi Module Instantiations
    //--------------------------------------------------------------------------

    // SMC OTP AXI-Lite jtag2axi instance
    if (SMC_DBG_ENABLE) begin : gen_smc_otp_jtag2axi
        jtag2axi #(
            .ADDR_WIDTH  (SMC_OTP_ADDR_WIDTH),
            .DATA_WIDTH  (SMC_OTP_DATA_WIDTH),
            .ID_WIDTH    (SMC_OTP_ID_WIDTH),
            .USER_WIDTH  (SMC_OTP_USER_WIDTH),
            .FIFO_DEPTH  (SMC_OTP_RD_PL_DEPTH),
            .ATOP_WIDTH  (6)
        ) u_smc_otp_jtag2axi (
            // JTAG Interface (TCK Domain)
            .tck_i              (smc_otp_jtag2axi_scan_ctrl.tck),
            .trst_ni            (smc_otp_jtag2axi_scan_ctrl.rst_n),
            .scan_in_i          (client_tdi_i),
            .scan_out_o         (smc_otp_jtag2axi_scan_out),
            .capture_en_i       (smc_otp_jtag2axi_scan_ctrl.capture_en),
            .shift_en_i         (smc_otp_jtag2axi_scan_ctrl.shift_en),
            .update_en_i        (smc_otp_jtag2axi_scan_ctrl.update_en),

            // JTAG Scan Chain Select Signals
            .select_AXISingleOp_i                  (inst_decoded_o[SMC_OTP_AXI_SINGLE_OP_INSTR]),
            .select_AXISeriesCtrl_i                (inst_decoded_o[SMC_OTP_AXI_SERIES_CTRL_INSTR]),
            .select_AXISeriesDataIncr_i            (inst_decoded_o[SMC_OTP_AXI_SERIES_DATA_INCR_INSTR]),
            .select_AXISeriesDataNoIncr_i          (inst_decoded_o[SMC_OTP_AXI_SERIES_DATA_NO_INCR_INSTR]),
            .select_AXISeriesDataWithErrorStatus_i (inst_decoded_o[SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR]),
            .security_disable_i                    (smc_otp_jtag2axi_security_disable),

            // AXI Interface (ACLK Domain)
            .aclk_i    (clk_i),
            .arst_ni   (rst_n_i),

            // AXI-Lite Write Address Channel
            .awid_o     (/* UNUSED */),
            .awaddr_o   (axil_smc_otp_jtag_req_o.aw.addr),
            .awlen_o    (/* UNUSED */),
            .awsize_o   (/* UNUSED */),
            .awburst_o  (/* UNUSED */),
            .awlock_o   (/* UNUSED */),
            .awcache_o  (/* UNUSED */),
            .awprot_o   (axil_smc_otp_jtag_req_o.aw.prot),
            .awqos_o    (/* UNUSED */),
            .awregion_o (/* UNUSED */),
            .awuser_o   (/* UNUSED */),
            .awatop_o   (/* UNUSED */),
            .awvalid_o  (axil_smc_otp_jtag_req_o.aw_valid),
            .awready_i  (axil_smc_otp_jtag_resp_i.aw_ready),

            // AXI-Lite Write Data Channel
            .wdata_o   (axil_smc_otp_jtag_req_o.w.data),
            .wstrb_o   (axil_smc_otp_jtag_req_o.w.strb),
            .wlast_o   (/* UNUSED */),
            .wuser_o   (/* UNUSED */),
            .wvalid_o  (axil_smc_otp_jtag_req_o.w_valid),
            .wready_i  (axil_smc_otp_jtag_resp_i.w_ready),

            // AXI-Lite Write Response Channel
            .bid_i     ('0),
            .bresp_i   (axil_smc_otp_jtag_resp_i.b.resp),
            .buser_i   ('0),
            .bvalid_i  (axil_smc_otp_jtag_resp_i.b_valid),
            .bready_o  (axil_smc_otp_jtag_req_o.b_ready),

            // AXI-Lite Read Address Channel
            .arid_o     (/* UNUSED */),
            .araddr_o   (axil_smc_otp_jtag_req_o.ar.addr),
            .arlen_o    (/* UNUSED */),
            .arsize_o   (/* UNUSED */),
            .arburst_o  (/* UNUSED */),
            .arlock_o   (/* UNUSED */),
            .arcache_o  (/* UNUSED */),
            .arprot_o   (axil_smc_otp_jtag_req_o.ar.prot),
            .arqos_o    (/* UNUSED */),
            .arregion_o (/* UNUSED */),
            .aruser_o   (/* UNUSED */),
            .arvalid_o  (axil_smc_otp_jtag_req_o.ar_valid),
            .arready_i  (axil_smc_otp_jtag_resp_i.ar_ready),

            // AXI-Lite Read Data Channel
            .rid_i     ('0),
            .rdata_i   (axil_smc_otp_jtag_resp_i.r.data),
            .rresp_i   (axil_smc_otp_jtag_resp_i.r.resp),
            .rlast_i   ('1),
            .ruser_i   ('0),
            .rvalid_i  (axil_smc_otp_jtag_resp_i.r_valid),
            .rready_o  (axil_smc_otp_jtag_req_o.r_ready)
        );
    end else begin : gen_no_smc_otp_jtag2axi
        assign smc_otp_jtag2axi_scan_out = client_tdi_i;
        assign axil_smc_otp_jtag_req_o = '0;
    end

    // SEP OTP AXI-Lite jtag2axi instance
    if (SEP_DBG_ENABLE) begin : gen_sep_otp_jtag2axi
        jtag2axi #(
            .ADDR_WIDTH  (SEP_OTP_ADDR_WIDTH),
            .DATA_WIDTH  (SEP_OTP_DATA_WIDTH),
            .ID_WIDTH    (SEP_OTP_ID_WIDTH),
            .USER_WIDTH  (SEP_OTP_USER_WIDTH),
            .FIFO_DEPTH  (SEP_OTP_RD_PL_DEPTH),
            .ATOP_WIDTH  (6)
        ) u_sep_otp_jtag2axi (
            // JTAG Interface (TCK Domain)
            .tck_i              (sep_otp_jtag2axi_scan_ctrl.tck),
            .trst_ni            (sep_otp_jtag2axi_scan_ctrl.rst_n),
            .scan_in_i          (client_tdi_i),
            .scan_out_o         (sep_otp_jtag2axi_scan_out),
            .capture_en_i       (sep_otp_jtag2axi_scan_ctrl.capture_en),
            .shift_en_i         (sep_otp_jtag2axi_scan_ctrl.shift_en),
            .update_en_i        (sep_otp_jtag2axi_scan_ctrl.update_en),

            // JTAG Scan Chain Select Signals
            .select_AXISingleOp_i                  (inst_decoded_o[SEP_OTP_AXI_SINGLE_OP_INSTR]),
            .select_AXISeriesCtrl_i                (inst_decoded_o[SEP_OTP_AXI_SERIES_CTRL_INSTR]),
            .select_AXISeriesDataIncr_i            (inst_decoded_o[SEP_OTP_AXI_SERIES_DATA_INCR_INSTR]),
            .select_AXISeriesDataNoIncr_i          (inst_decoded_o[SEP_OTP_AXI_SERIES_DATA_NO_INCR_INSTR]),
            .select_AXISeriesDataWithErrorStatus_i (inst_decoded_o[SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR]),
            .security_disable_i                    (sep_otp_jtag2axi_security_disable),

            // AXI Interface (ACLK Domain)
            .aclk_i    (clk_i),
            .arst_ni   (rst_n_i),

            // AXI-Lite Write Address Channel
            .awid_o     (/* UNUSED */),
            .awaddr_o   (axil_sep_otp_jtag_req_o.aw.addr),
            .awlen_o    (/* UNUSED */),
            .awsize_o   (/* UNUSED */),
            .awburst_o  (/* UNUSED */),
            .awlock_o   (/* UNUSED */),
            .awcache_o  (/* UNUSED */),
            .awprot_o   (axil_sep_otp_jtag_req_o.aw.prot),
            .awqos_o    (/* UNUSED */),
            .awregion_o (/* UNUSED */),
            .awuser_o   (/* UNUSED */),
            .awatop_o   (/* UNUSED */),
            .awvalid_o  (axil_sep_otp_jtag_req_o.aw_valid),
            .awready_i  (axil_sep_otp_jtag_resp_i.aw_ready),

            // AXI-Lite Write Data Channel
            .wdata_o   (axil_sep_otp_jtag_req_o.w.data),
            .wstrb_o   (axil_sep_otp_jtag_req_o.w.strb),
            .wlast_o   (/* UNUSED */),
            .wuser_o   (/* UNUSED */),
            .wvalid_o  (axil_sep_otp_jtag_req_o.w_valid),
            .wready_i  (axil_sep_otp_jtag_resp_i.w_ready),

            // AXI-Lite Write Response Channel
            .bid_i     ('0),
            .bresp_i   (axil_sep_otp_jtag_resp_i.b.resp),
            .buser_i   ('0),
            .bvalid_i  (axil_sep_otp_jtag_resp_i.b_valid),
            .bready_o  (axil_sep_otp_jtag_req_o.b_ready),

            // AXI-Lite Read Address Channel
            .arid_o     (/* UNUSED */),
            .araddr_o   (axil_sep_otp_jtag_req_o.ar.addr),
            .arlen_o    (/* UNUSED */),
            .arsize_o   (/* UNUSED */),
            .arburst_o  (/* UNUSED */),
            .arlock_o   (/* UNUSED */),
            .arcache_o  (/* UNUSED */),
            .arprot_o   (axil_sep_otp_jtag_req_o.ar.prot),
            .arqos_o    (/* UNUSED */),
            .arregion_o (/* UNUSED */),
            .aruser_o   (/* UNUSED */),
            .arvalid_o  (axil_sep_otp_jtag_req_o.ar_valid),
            .arready_i  (axil_sep_otp_jtag_resp_i.ar_ready),

            // AXI-Lite Read Data Channel
            .rid_i     ('0),
            .rdata_i   (axil_sep_otp_jtag_resp_i.r.data),
            .rresp_i   (axil_sep_otp_jtag_resp_i.r.resp),
            .rlast_i   ('1),
            .ruser_i   ('0),
            .rvalid_i  (axil_sep_otp_jtag_resp_i.r_valid),
            .rready_o  (axil_sep_otp_jtag_req_o.r_ready)
        );
    end else begin : gen_no_sep_otp_jtag2axi
        assign sep_otp_jtag2axi_scan_out = client_tdi_i;
        assign axil_sep_otp_jtag_req_o = '0;
    end

    // SMC Fabric AXI jtag2axi instance
    if (SMC_DBG_ENABLE) begin : gen_smc_jtag2axi
        jtag2axi #(
            .ADDR_WIDTH  (SMC_ADDR_WIDTH),
            .DATA_WIDTH  (SMC_DATA_WIDTH),
            .ID_WIDTH    (SMC_ID_WIDTH),
            .USER_WIDTH  (SMC_USER_WIDTH),
            .FIFO_DEPTH  (SMC_RD_PL_DEPTH),
            .ATOP_WIDTH  (6)
        ) u_smc_jtag2axi (
            // JTAG Interface (TCK Domain)
            .tck_i              (smc_jtag2axi_scan_ctrl.tck),
            .trst_ni            (smc_jtag2axi_scan_ctrl.rst_n),
            .scan_in_i          (client_tdi_i),
            .scan_out_o         (smc_jtag2axi_scan_out),
            .capture_en_i       (smc_jtag2axi_scan_ctrl.capture_en),
            .shift_en_i         (smc_jtag2axi_scan_ctrl.shift_en),
            .update_en_i        (smc_jtag2axi_scan_ctrl.update_en),

            // JTAG Scan Chain Select Signals
            .select_AXISingleOp_i                  (inst_decoded_o[SMC_AXI_SINGLE_OP_INSTR]),
            .select_AXISeriesCtrl_i                (inst_decoded_o[SMC_AXI_SERIES_CTRL_INSTR]),
            .select_AXISeriesDataIncr_i            (inst_decoded_o[SMC_AXI_SERIES_DATA_INCR_INSTR]),
            .select_AXISeriesDataNoIncr_i          (inst_decoded_o[SMC_AXI_SERIES_DATA_NO_INCR_INSTR]),
            .select_AXISeriesDataWithErrorStatus_i (inst_decoded_o[SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR]),
            .security_disable_i                    (smc_jtag2axi_security_disable),

            // AXI Interface (ACLK Domain)
            .aclk_i    (clk_i),
            .arst_ni   (rst_n_i),

            // AXI Write Address Channel
            .awid_o     (axi_smc_dbg_req_o.aw.id),
            .awaddr_o   (axi_smc_dbg_req_o.aw.addr),
            .awlen_o    (axi_smc_dbg_req_o.aw.len),
            .awsize_o   (axi_smc_dbg_req_o.aw.size),
            .awburst_o  (axi_smc_dbg_req_o.aw.burst),
            .awlock_o   (axi_smc_dbg_req_o.aw.lock),
            .awcache_o  (axi_smc_dbg_req_o.aw.cache),
            .awprot_o   (axi_smc_dbg_req_o.aw.prot),
            .awqos_o    (axi_smc_dbg_req_o.aw.qos),
            .awregion_o (axi_smc_dbg_req_o.aw.region),
            .awuser_o   (axi_smc_dbg_req_o.aw.user),
            .awatop_o   (axi_smc_dbg_req_o.aw.atop),
            .awvalid_o  (axi_smc_dbg_req_o.aw_valid),
            .awready_i  (axi_smc_dbg_resp_i.aw_ready),

            // AXI Write Data Channel
            .wdata_o   (axi_smc_dbg_req_o.w.data),
            .wstrb_o   (axi_smc_dbg_req_o.w.strb),
            .wlast_o   (axi_smc_dbg_req_o.w.last),
            .wuser_o   (axi_smc_dbg_req_o.w.user),
            .wvalid_o  (axi_smc_dbg_req_o.w_valid),
            .wready_i  (axi_smc_dbg_resp_i.w_ready),

            // AXI Write Response Channel
            .bid_i     (axi_smc_dbg_resp_i.b.id),
            .bresp_i   (axi_smc_dbg_resp_i.b.resp),
            .buser_i   (axi_smc_dbg_resp_i.b.user),
            .bvalid_i  (axi_smc_dbg_resp_i.b_valid),
            .bready_o  (axi_smc_dbg_req_o.b_ready),

            // AXI Read Address Channel
            .arid_o     (axi_smc_dbg_req_o.ar.id),
            .araddr_o   (axi_smc_dbg_req_o.ar.addr),
            .arlen_o    (axi_smc_dbg_req_o.ar.len),
            .arsize_o   (axi_smc_dbg_req_o.ar.size),
            .arburst_o  (axi_smc_dbg_req_o.ar.burst),
            .arlock_o   (axi_smc_dbg_req_o.ar.lock),
            .arcache_o  (axi_smc_dbg_req_o.ar.cache),
            .arprot_o   (axi_smc_dbg_req_o.ar.prot),
            .arqos_o    (axi_smc_dbg_req_o.ar.qos),
            .arregion_o (axi_smc_dbg_req_o.ar.region),
            .aruser_o   (axi_smc_dbg_req_o.ar.user),
            .arvalid_o  (axi_smc_dbg_req_o.ar_valid),
            .arready_i  (axi_smc_dbg_resp_i.ar_ready),

            // AXI Read Data Channel
            .rid_i     (axi_smc_dbg_resp_i.r.id),
            .rdata_i   (axi_smc_dbg_resp_i.r.data),
            .rresp_i   (axi_smc_dbg_resp_i.r.resp),
            .rlast_i   (axi_smc_dbg_resp_i.r.last),
            .ruser_i   (axi_smc_dbg_resp_i.r.user),
            .rvalid_i  (axi_smc_dbg_resp_i.r_valid),
            .rready_o  (axi_smc_dbg_req_o.r_ready)
        );
    end else begin : gen_no_smc_jtag2axi
        assign smc_jtag2axi_scan_out = client_tdi_i;
        assign axi_smc_dbg_req_o = '0;
    end

    //--------------------------------------------------------------------------
    // TDR Multiplexer (IEEE 1149.1 Section 4.4)
    //--------------------------------------------------------------------------

    // Select active TDR based on current instruction and scan state
    // During IR scan: select instruction register
    // During DR scan: select appropriate DR based on decoded instruction
    always_comb begin
        if (ir_scan_ctrl.select) begin
            // IR scan: select instruction register
            tdr_mux = inst_reg_scan_out;
        end else begin
            // DR scan: select appropriate DR based on instruction
            unique case (1'b1)
                inst_decoded_o[BYPASS_INSTR],
                inst_decoded_o[BYPASS_ALT_INSTR]:
                    tdr_mux = byp_reg_scan_out;

                inst_decoded_o[IDCODE_INSTR]:
                    tdr_mux = idcode_reg_scan_out;  // IDCODE register

                inst_decoded_o[EXTEST_INSTR],
                inst_decoded_o[SAMPLE_PRELOAD_INSTR]:
                    tdr_mux = BSR_ENABLE ? bsr_host_scan_in_i : byp_reg_scan_out;

                inst_decoded_o[EXTEST_TRAIN_INSTR]:
                    tdr_mux = (BSR_ENABLE && EXTEST_TRAIN_ENABLE) ? bsr_host_scan_in_i : byp_reg_scan_out;

                inst_decoded_o[EXTEST_PULSE_INSTR]:
                    tdr_mux = (BSR_ENABLE && EXTEST_PULSE_ENABLE) ? bsr_host_scan_in_i : byp_reg_scan_out;

                inst_decoded_o[INTEST_INSTR]:
                    tdr_mux = (BSR_ENABLE && INTEST_ENABLE) ? bsr_host_scan_in_i : byp_reg_scan_out;

                inst_decoded_o[CLAMP_INSTR]:
                    tdr_mux = byp_reg_scan_out;  // Bypass (no DR for CLAMP, but only enabled when CLAMP_ENABLE)

                inst_decoded_o[HIGHZ_INSTR]:
                    tdr_mux = byp_reg_scan_out;  // Bypass (no DR for these)

                inst_decoded_o[RUNBIST_INSTR]:
                    tdr_mux = RUNBIST_ENABLE ? ijtag_host_scan_in_i : byp_reg_scan_out;

                inst_decoded_o[TMP_STATUS_INSTR]:
                    tdr_mux = TMP_ENABLE ? tmp_status_reg_scan_out : byp_reg_scan_out;

                inst_decoded_o[IC_RESET_INSTR]:
                    tdr_mux = IC_RESET_ENABLE ? ic_reset_reg_scan_out : byp_reg_scan_out;

                inst_decoded_o[TAP_3DCR_INSTR]:
                    tdr_mux = PTAP_3DCR_ENABLE ? tap_3dcr_reg_scan_out : byp_reg_scan_out;

                inst_decoded_o[DEBUG_CONTROL_INSTR]:
                    tdr_mux = debug_ctrl_reg_scan_out;  // Debug control register

                inst_decoded_o[JTAG_CAPS_INSTR]:
                    tdr_mux = caps_reg_scan_out;  // JTAG capabilities register

                inst_decoded_o[SMC_OTP_JTAG2AXI_CAPS_INSTR]:
                    tdr_mux = smc_otp_2axi_caps_reg_scan_out;  // SMC OTP JTAG2AXI capabilities register

                inst_decoded_o[SEP_OTP_JTAG2AXI_CAPS_INSTR]:
                    tdr_mux = sep_otp_2axi_caps_reg_scan_out;  // SEP OTP JTAG2AXI capabilities register

                inst_decoded_o[SMC_JTAG2AXI_CAPS_INSTR]:
                    tdr_mux = smc_2axi_caps_reg_scan_out;  // SMC fabric JTAG2AXI capabilities register

                // SMC OTP AXI instructions
                inst_decoded_o[SMC_OTP_AXI_SINGLE_OP_INSTR],
                inst_decoded_o[SMC_OTP_AXI_SERIES_CTRL_INSTR],
                inst_decoded_o[SMC_OTP_AXI_SERIES_DATA_INCR_INSTR],
                inst_decoded_o[SMC_OTP_AXI_SERIES_DATA_NO_INCR_INSTR],
                inst_decoded_o[SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR]:
                    tdr_mux = SMC_DBG_ENABLE ? smc_otp_jtag2axi_scan_out : byp_reg_scan_out;

                // SEP OTP AXI instructions
                inst_decoded_o[SEP_OTP_AXI_SINGLE_OP_INSTR],
                inst_decoded_o[SEP_OTP_AXI_SERIES_CTRL_INSTR],
                inst_decoded_o[SEP_OTP_AXI_SERIES_DATA_INCR_INSTR],
                inst_decoded_o[SEP_OTP_AXI_SERIES_DATA_NO_INCR_INSTR],
                inst_decoded_o[SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR]:
                    tdr_mux = SEP_DBG_ENABLE ? sep_otp_jtag2axi_scan_out : byp_reg_scan_out;

                // SMC fabric AXI instructions
                inst_decoded_o[SMC_AXI_SINGLE_OP_INSTR],
                inst_decoded_o[SMC_AXI_SERIES_CTRL_INSTR],
                inst_decoded_o[SMC_AXI_SERIES_DATA_INCR_INSTR],
                inst_decoded_o[SMC_AXI_SERIES_DATA_NO_INCR_INSTR],
                inst_decoded_o[SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR]:
                    tdr_mux = SMC_DBG_ENABLE ? smc_jtag2axi_scan_out : byp_reg_scan_out;

                inst_decoded_o[SELECT_IJTAG_INSTR]:
                    tdr_mux = ijtag_host_scan_in_i;  // iJTAG network

                inst_decoded_o[INV_BYPASS_INSTR]:
                    tdr_mux = inv_byp_reg_scan_out;  // Inverted bypass register

                default:
                    tdr_mux = byp_reg_scan_out;  // Default to bypass behavior
            endcase
        end
    end

    //--------------------------------------------------------------------------
    // Scan Data Input Selection (IEEE 1838 Section 5.4)
    //--------------------------------------------------------------------------

    // Scan input mux: Implements zero-length bypass and STAP selection using explicit mux cells
    // to avoid glitches.
    // Logic: stap_select ? stap_host_scan_in_i : ((inst_decoded_o[ZERO_LENGTH_BYPASS_INSTR] && dr_scan_select_reg) ? client_tdi_i : tdr_mux)

    // First mux: Select between client_tdi_i (zero-length bypass) and tdr_mux
    prim_stdmux2 u_zlb_tdr_mux (
        .i0_i  (tdr_mux),
        .i1_i  (client_tdi_i),
        .sel_i (inst_decoded_o[ZERO_LENGTH_BYPASS_INSTR] && dr_scan_select_reg),
        .y_o   (zlb_tdr_mux)
    );

    // Second mux: Select between stap_host_scan_in_i (STAP) and zlb_tdr_mux
    prim_stdmux2 u_tdo_mux (
        .i0_i  (zlb_tdr_mux),
        .i1_i  (stap_host_scan_in_i),
        .sel_i (stap_select),
        .y_o   (tdo_mux)
    );

    //--------------------------------------------------------------------------
    // STAP Clock/Control Outputs (IEEE 1838 Section 5.4)
    //--------------------------------------------------------------------------

    // STAP scan control signals (OR of IR and DR controls, gated by the 3DCR STAP-select bit)
    always_comb begin
        stap_host_scan_ctrl_o = dr_scan_ctrl;
        stap_host_scan_ctrl_o.select     = stap_select &&
                                           (dr_scan_ctrl.select     | ir_scan_ctrl.select);
        stap_host_scan_ctrl_o.capture_en = stap_select &&
                                           (dr_scan_ctrl.capture_en | ir_scan_ctrl.capture_en);
        stap_host_scan_ctrl_o.shift_en   = stap_select &&
                                           (dr_scan_ctrl.shift_en   | ir_scan_ctrl.shift_en);
        stap_host_scan_ctrl_o.update_en  = stap_select &&
                                           (dr_scan_ctrl.update_en  | ir_scan_ctrl.update_en);
    end

    // STAP scan data output (from zero-length bypass TDR multiplexer to STAP chain)
    assign stap_host_scan_out_o = zlb_tdr_mux;

    //--------------------------------------------------------------------------
    // TDO Retiming (IEEE 1149.1 Section 4.5.2)
    //--------------------------------------------------------------------------

    // TDO must be retimed to falling edge of TCK per IEEE 1149.1
    // Also register DR scan select to avoid glitches on mux select
    // Use combined reset (power-on reset AND external trst_n)
    always_ff @(negedge client_tap_ctrl_i.tck or negedge jtag_trst_n) begin
        if (!jtag_trst_n) begin
            tdo_retimed <= 1'b0;
            dr_scan_select_reg <= 1'b0;
        end else begin
            tdo_retimed <= tdo_mux;
            dr_scan_select_reg <= dr_scan_ctrl.select;
        end
    end

    //--------------------------------------------------------------------------
    // TDO Output Selection with Bypass for ZERO_LENGTH_BYPASS
    //--------------------------------------------------------------------------

    // Use explicit mux cell to bypass retimer for ZERO_LENGTH_BYPASS instruction
    // For ZERO_LENGTH_BYPASS: select tdo_mux directly (bypass retimer) during data shift only
    // For all other instructions: select retimed TDO
    // Use registered DR scan select to avoid glitches
    prim_stdmux2 u_tdo_bypass_mux (
        .i0_i  (tdo_retimed),
        .i1_i  (tdo_mux),
        .sel_i (inst_decoded_o[ZERO_LENGTH_BYPASS_INSTR] && dr_scan_select_reg),
        .y_o   (client_tdo_o)
    );

endmodule : jtag_ptap
