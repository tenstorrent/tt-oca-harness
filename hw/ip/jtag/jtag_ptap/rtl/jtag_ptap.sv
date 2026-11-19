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
// synchronized to clk_i upstream.
//
// The STAP scan interface carries both IR and DR scans while the 3DCR STAP-select bit is set, and
// TDO then comes from stap_host_scan_in_i instead of the IR or selected TDR. While the bit is
// clear, the select, capture, shift and update strobes of the STAP scan interface stay low, so
// the STAP chain holds its state through every scan. TDO is retimed on the
// falling TCK edge, except during a ZERO_LENGTH_BYPASS DR shift with the bit clear, where TDI
// reaches TDO combinationally. While the bit is set, ZERO_LENGTH_BYPASS behaves as BYPASS: the
// bypass register leads the STAP chain and its return is retimed.
//
// System clk_i/rst_n_i clock and reset the JTAG2AXI bridges, which TRST and Test-Logic-Reset
// do not reset; pwr_on_rst_ni is ANDed with trst_n for the JTAG logic
// and for the TRST forwarded on host_tap_ctrl_o.

module jtag_ptap
    import prim_jtag_pkg::jtag_tap_ctrl_t;
    import prim_jtag_pkg::jtag_scan_ctrl_t;

    `include "ocah_assert.svh"
    import jtag_tap_pkg::tap_state_e;
    import jtag_inst_reg_pkg::jtag_instruction_decoded_e;
    import jtag_inst_reg_pkg::RUNBIST_INSTR;
    import jtag_inst_reg_pkg::BYPASS_INSTR;
    import jtag_inst_reg_pkg::BYPASS_ALT_INSTR;
    import jtag_inst_reg_pkg::CLAMP_INSTR;
    import jtag_inst_reg_pkg::HIGHZ_INSTR;
    import jtag_inst_reg_pkg::IC_RESET_INSTR;
    import jtag_inst_reg_pkg::EXTEST_TRAIN_INSTR;
    import jtag_inst_reg_pkg::EXTEST_PULSE_INSTR;
    import jtag_inst_reg_pkg::INTEST_INSTR;
    import jtag_inst_reg_pkg::EXTEST_INSTR;
    import jtag_inst_reg_pkg::SAMPLE_PRELOAD_INSTR;
    import jtag_inst_reg_pkg::TMP_STATUS_INSTR;
    import jtag_inst_reg_pkg::TAP_3DCR_INSTR;
    import jtag_inst_reg_pkg::DEBUG_CONTROL_INSTR;
    import jtag_inst_reg_pkg::ZERO_LENGTH_BYPASS_INSTR;
    import jtag_inst_reg_pkg::JTAG_CAPS_INSTR;
    import jtag_inst_reg_pkg::SMC_OTP_DTMCS_INSTR;
    import jtag_inst_reg_pkg::SMC_OTP_DMI_INSTR;
    import jtag_inst_reg_pkg::SEP_OTP_DTMCS_INSTR;
    import jtag_inst_reg_pkg::SEP_OTP_DMI_INSTR;
    import jtag_inst_reg_pkg::SMC_DTMCS_INSTR;
    import jtag_inst_reg_pkg::SMC_DMI_INSTR;
    import jtag_inst_reg_pkg::INV_BYPASS_INSTR;
    import jtag_inst_reg_pkg::IDCODE_INSTR;
    import jtag_inst_reg_pkg::SELECT_IJTAG_INSTR;
    import jtag_inst_reg_pkg::CLAMP_HOLD_INSTR;
    import jtag_inst_reg_pkg::CLAMP_RELEASE_INSTR;
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
    parameter type  sep_otp_axil_resp_t = logic  // SEP OTP debug AXI-Lite interface response type.
    /* verilator lint_on UNUSEDPARAM */
) (
    input  jtag_tap_ctrl_t  client_tap_ctrl_i,  // Client TAP-control bundle: TCK, TMS, and
                                                // active-low TRST.
    input  logic            client_tdi_i,  // Client serial test data input.
    output logic            client_tdo_o,  // Client serial test data output, retimed on the falling
                                           // TCK edge except during a ZERO_LENGTH_BYPASS DR shift
                                           // with the 3DCR STAP-select bit clear.
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
    output logic             stap_host_scan_out_o,  // IR or selected TDR output toward the STAP
                                                    // chain; the bypass register under
                                                    // ZERO_LENGTH_BYPASS while the 3DCR
                                                    // STAP-select bit is set, and TDI while it
                                                    // is clear.

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
    input  logic                     test_en_i,  // DFT test-mode enable, active-high, for the
                                                 // JTAG2AXI bridges.
    input  logic                     scan_rst_ni,  // Scan reset, active-low, that resets the
                                                   // JTAG2AXI bridges while test_en_i is high.

    input  logic                     pwr_on_rst_ni,  // Power-on reset (active low), ANDed with the
                                                     // client TRST.

    input  logic  smc_jtag2axi_security_disable_i,  // Active-high disable of the SMC fabric
                                                    // JTAG2AXI bridge, in the clk_i domain; its
                                                    // requests complete with DECERR.
    input  logic  smc_otp_jtag2axi_security_disable_i,  // Active-high disable of the SMC OTP
                                                        // JTAG2AXI bridge, in the clk_i domain; its
                                                        // requests complete with DECERR.
    input  logic  sep_otp_jtag2axi_security_disable_i,  // Active-high disable of the SEP OTP
                                                        // JTAG2AXI bridge, in the clk_i domain; its
                                                        // requests complete with DECERR.

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
    jtag_scan_ctrl_t smc_otp_jtag2axi_dtmcs_scan_ctrl; // SMC OTP JTAG2AXI DTMCS TDR scan control
    jtag_scan_ctrl_t sep_otp_jtag2axi_dtmcs_scan_ctrl; // SEP OTP JTAG2AXI DTMCS TDR scan control
    jtag_scan_ctrl_t smc_jtag2axi_dtmcs_scan_ctrl;     // SMC fabric JTAG2AXI DTMCS TDR scan control
    jtag_scan_ctrl_t smc_otp_jtag2axi_scan_ctrl;       // SMC OTP JTAG2AXI DMI TDR scan control
    jtag_scan_ctrl_t sep_otp_jtag2axi_scan_ctrl;       // SEP OTP JTAG2AXI DMI TDR scan control
    jtag_scan_ctrl_t smc_jtag2axi_scan_ctrl;           // SMC fabric JTAG2AXI DMI TDR scan control

    logic inst_reg_scan_out;               // Instruction register scan chain
    logic byp_reg_scan_out;                // Bypass register scan chain
    logic inv_byp_reg_scan_out;            // Inverted bypass register scan chain
    logic tap_3dcr_reg_scan_out;           // 3DCR register scan chain
    logic idcode_reg_scan_out;             // IDCODE register scan chain
    logic tmp_status_reg_scan_out;         // TMP status register scan chain
    logic ic_reset_reg_scan_out;           // IC_RESET register scan chain
    logic debug_ctrl_reg_scan_out;         // DEBUG_CTRL register scan chain
    logic caps_reg_scan_out;               // JTAG_CAPS register scan chain

    logic persistence_mode;   // TMP persistence mode (from TMP controller)
    logic bypass_escape_bit;  // Bypass escape enable bit (from TMP status register)
    logic stap_select;        // STAP select (from 3DCR)
    logic tdr_mux;            // TDR multiplexer output
    logic tdo_mux;            // Final TDO multiplexer output (STAP or TDR)
    logic zlb_tdr_mux;        // Zero-length bypass TDR multiplexer intermediate output
    logic tdo_retimed;        // Retimed TDO output
    logic dr_scan_select_reg; // Registered DR scan select to avoid glitches
    logic zlb_select;         // ZERO_LENGTH_BYPASS DR scan with STAP select clear

    // JTAG2AXI scan chain outputs: the DMI TDR and the DTMCS TDR of each bridge
    logic smc_otp_jtag2axi_scan_out;
    logic sep_otp_jtag2axi_scan_out;
    logic smc_jtag2axi_scan_out;
    logic smc_otp_jtag2axi_dtmcs_scan_out;
    logic sep_otp_jtag2axi_dtmcs_scan_out;
    logic smc_jtag2axi_dtmcs_scan_out;
    logic smc_otp_jtag2axi_security_disable;
    logic sep_otp_jtag2axi_security_disable;
    logic smc_jtag2axi_security_disable;

    // 3DCR register is only needed when STAPs are enabled
    localparam bit Ptap3dcrEnable = (STAP_IO_ENABLE != 0 || SEP_DBG_ENABLE != 0 || NUM_EXTRA_STAPS != 0 ||
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
    localparam int unsigned NumSmcIcReset  = IC_RESET_SMC_ENABLE ? ($bits(ic_reset_smc_t) / 2) : 0;
    localparam int unsigned NumSepIcReset  = IC_RESET_SEP_ENABLE ? ($bits(ic_reset_sep_t) / 2) : 0;
    localparam int unsigned NumExtIcReset  = IC_RESET_EXT_ENABLE ? ($bits(ic_reset_ext_t) / 2) : 0;
    localparam int unsigned NumIcReset     = NumSmcIcReset + NumSepIcReset + NumExtIcReset;

    // Any-slice enable drives TAP-level IC_RESET instruction decode and CAPS reporting.
    localparam bit IcResetEnable = IC_RESET_SMC_ENABLE | IC_RESET_SEP_ENABLE | IC_RESET_EXT_ENABLE;

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
                byp_reg_scan_ctrl.select = dr_scan_ctrl.select && !IcResetEnable;
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
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && !Ptap3dcrEnable;
             end
             inst_decoded_o[RUNBIST_INSTR]: begin
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && !RUNBIST_ENABLE;
             end
             inst_decoded_o[DEBUG_CONTROL_INSTR]: begin
                 byp_reg_scan_ctrl.select = 1'b0;
             end
             // ZERO_LENGTH_BYPASS is BYPASS while STAP select is set.
             inst_decoded_o[ZERO_LENGTH_BYPASS_INSTR]: begin
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && stap_select;
             end
             inst_decoded_o[JTAG_CAPS_INSTR]: begin
                 byp_reg_scan_ctrl.select = 1'b0;
             end
             // JTAG2AXI bridge instructions
             inst_decoded_o[SMC_OTP_DTMCS_INSTR],
             inst_decoded_o[SMC_OTP_DMI_INSTR],
             inst_decoded_o[SMC_DTMCS_INSTR],
             inst_decoded_o[SMC_DMI_INSTR]: begin
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && !SMC_DBG_ENABLE;
             end
             inst_decoded_o[SEP_OTP_DTMCS_INSTR],
             inst_decoded_o[SEP_OTP_DMI_INSTR]: begin
                 byp_reg_scan_ctrl.select = dr_scan_ctrl.select && !SEP_DBG_ENABLE;
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
        tap_3dcr_reg_scan_ctrl.select = dr_scan_ctrl.select && Ptap3dcrEnable &&
                                         inst_decoded_o[TAP_3DCR_INSTR];
    end

    if (Ptap3dcrEnable) begin : gen_tap_3dcr_reg
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

    // JTAG2AXI bridge scan controls: a DTMCS TDR and a DMI TDR for each bridge
    always_comb begin
        smc_otp_jtag2axi_dtmcs_scan_ctrl = dr_scan_ctrl;
        smc_otp_jtag2axi_dtmcs_scan_ctrl.select = dr_scan_ctrl.select && SMC_DBG_ENABLE &&
            inst_decoded_o[SMC_OTP_DTMCS_INSTR];
        smc_otp_jtag2axi_scan_ctrl = dr_scan_ctrl;
        smc_otp_jtag2axi_scan_ctrl.select = dr_scan_ctrl.select && SMC_DBG_ENABLE &&
            inst_decoded_o[SMC_OTP_DMI_INSTR];
        sep_otp_jtag2axi_dtmcs_scan_ctrl = dr_scan_ctrl;
        sep_otp_jtag2axi_dtmcs_scan_ctrl.select = dr_scan_ctrl.select && SEP_DBG_ENABLE &&
            inst_decoded_o[SEP_OTP_DTMCS_INSTR];
        sep_otp_jtag2axi_scan_ctrl = dr_scan_ctrl;
        sep_otp_jtag2axi_scan_ctrl.select = dr_scan_ctrl.select && SEP_DBG_ENABLE &&
            inst_decoded_o[SEP_OTP_DMI_INSTR];
        smc_jtag2axi_dtmcs_scan_ctrl = dr_scan_ctrl;
        smc_jtag2axi_dtmcs_scan_ctrl.select = dr_scan_ctrl.select && SMC_DBG_ENABLE &&
            inst_decoded_o[SMC_DTMCS_INSTR];
        smc_jtag2axi_scan_ctrl = dr_scan_ctrl;
        smc_jtag2axi_scan_ctrl.select = dr_scan_ctrl.select && SMC_DBG_ENABLE &&
            inst_decoded_o[SMC_DMI_INSTR];
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
    //   SMC bits : [NumIcReset-1                  : NumSepIcReset+NumExtIcReset]
    //   SEP bits : [NumSepIcReset+NumExtIcReset-1 : NumExtIcReset]
    //   EXT bits : [NumExtIcReset-1               : 0]
    //
    // POLARITY: `ic_reset_ovrd_bus` is the ACTIVE-HIGH override signal
    // (i.e. `!reset_enable`) as emitted by jtag_ic_reset_reg; it is *not* the
    // raw IEEE §17 `reset_enable` TDR field. See `jtag_ic_reset_reg` header
    // for the full convention. The bus is forwarded verbatim into the
    // downstream `.ovrd` struct members below — no further inversion.
    logic [((NumIcReset == 0) ? 0 : NumIcReset-1):0]  ic_reset_ovrd_bus;
    logic [((NumIcReset == 0) ? 0 : NumIcReset-1):0]  ic_reset_ctrl_n_bus;

    if (IcResetEnable && (NumIcReset > 0)) begin : gen_ic_reset_reg
        jtag_ic_reset_reg #(
            .NUM_IC_RESET_PORTS(NumIcReset)
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
        `OCAH_ASSERT_STATIC(IcResetSmcOvrdValWidthMatch_A,
                                  $bits(smc_width_probe.ovrd) == $bits(smc_width_probe.val))

        ic_reset_smc_t smc_w;
        assign smc_w.ovrd = ic_reset_ovrd_bus[NumIcReset-1 -: NumSmcIcReset];
        assign smc_w.val  = ic_reset_ctrl_n_bus[NumIcReset-1 -: NumSmcIcReset];
        assign ic_reset_smc_o = smc_w;
    end else begin : gen_ic_reset_smc_tie
        assign ic_reset_smc_o = '0;
    end

    if (IC_RESET_SEP_ENABLE) begin : gen_ic_reset_sep_pack
        ic_reset_sep_t sep_width_probe;
        `OCAH_ASSERT_STATIC(IcResetSepOvrdValWidthMatch_A,
                                  $bits(sep_width_probe.ovrd) == $bits(sep_width_probe.val))

        ic_reset_sep_t sep_w;
        assign sep_w.ovrd = ic_reset_ovrd_bus[NumSepIcReset+NumExtIcReset-1 -: NumSepIcReset];
        assign sep_w.val  = ic_reset_ctrl_n_bus[NumSepIcReset+NumExtIcReset-1 -: NumSepIcReset];
        assign ic_reset_sep_o = sep_w;
    end else begin : gen_ic_reset_sep_tie
        assign ic_reset_sep_o = '0;
    end

    if (IC_RESET_EXT_ENABLE) begin : gen_ic_reset_ext_pack
        ic_reset_ext_t ext_width_probe;
        `OCAH_ASSERT_STATIC(IcResetExtOvrdValWidthMatch_A,
                                  $bits(ext_width_probe.ovrd) == $bits(ext_width_probe.val))

        ic_reset_ext_t ext_w;
        assign ext_w.ovrd = ic_reset_ovrd_bus[NumExtIcReset-1 -: NumExtIcReset];
        assign ext_w.val  = ic_reset_ctrl_n_bus[NumExtIcReset-1 -: NumExtIcReset];
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
        .IC_RESET_ENABLE     (IcResetEnable),
        .SMC_DBG_ENABLE      (SMC_DBG_ENABLE),
        .SEP_DBG_ENABLE      (SEP_DBG_ENABLE),
        .STAP_IO_ENABLE      (STAP_IO_ENABLE),
        .NUM_SMC_IC_RESET    (NumSmcIcReset),
        .NUM_SEP_IC_RESET    (NumSepIcReset),
        .NUM_EXT_IC_RESET    (NumExtIcReset),
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
    // JTAG2AXI Bridge Instances
    //--------------------------------------------------------------------------

    // SMC OTP AXI-Lite JTAG2AXI bridge
    if (SMC_DBG_ENABLE) begin : gen_smc_otp_jtag2axi
        jtag_dmi2axi #(
            .IS_AXI4_LITE (1'b1),
            .axi_req_t    (smc_otp_axil_req_t),
            .axi_resp_t   (smc_otp_axil_resp_t)
        ) u_smc_otp_jtag2axi (
            .dtmcs_scan_ctrl_i  (smc_otp_jtag2axi_dtmcs_scan_ctrl),
            .dmi_scan_ctrl_i    (smc_otp_jtag2axi_scan_ctrl),
            .scan_in_i          (client_tdi_i),
            .dtmcs_scan_out_o   (smc_otp_jtag2axi_dtmcs_scan_out),
            .dmi_scan_out_o     (smc_otp_jtag2axi_scan_out),

            .clk_i              (clk_i),
            .rst_ni             (rst_n_i),
            .test_en_i          (test_en_i),
            .scan_rst_ni        (scan_rst_ni),

            .security_disable_i (smc_otp_jtag2axi_security_disable),

            .axi_req_o          (axil_smc_otp_jtag_req_o),
            .axi_resp_i         (axil_smc_otp_jtag_resp_i)
        );
    end else begin : gen_no_smc_otp_jtag2axi
        assign smc_otp_jtag2axi_scan_out = client_tdi_i;
        assign smc_otp_jtag2axi_dtmcs_scan_out = client_tdi_i;
        assign axil_smc_otp_jtag_req_o = '0;
    end

    // SEP OTP AXI-Lite JTAG2AXI bridge
    if (SEP_DBG_ENABLE) begin : gen_sep_otp_jtag2axi
        jtag_dmi2axi #(
            .IS_AXI4_LITE (1'b1),
            .axi_req_t    (sep_otp_axil_req_t),
            .axi_resp_t   (sep_otp_axil_resp_t)
        ) u_sep_otp_jtag2axi (
            .dtmcs_scan_ctrl_i  (sep_otp_jtag2axi_dtmcs_scan_ctrl),
            .dmi_scan_ctrl_i    (sep_otp_jtag2axi_scan_ctrl),
            .scan_in_i          (client_tdi_i),
            .dtmcs_scan_out_o   (sep_otp_jtag2axi_dtmcs_scan_out),
            .dmi_scan_out_o     (sep_otp_jtag2axi_scan_out),

            .clk_i              (clk_i),
            .rst_ni             (rst_n_i),
            .test_en_i          (test_en_i),
            .scan_rst_ni        (scan_rst_ni),

            .security_disable_i (sep_otp_jtag2axi_security_disable),

            .axi_req_o          (axil_sep_otp_jtag_req_o),
            .axi_resp_i         (axil_sep_otp_jtag_resp_i)
        );
    end else begin : gen_no_sep_otp_jtag2axi
        assign sep_otp_jtag2axi_scan_out = client_tdi_i;
        assign sep_otp_jtag2axi_dtmcs_scan_out = client_tdi_i;
        assign axil_sep_otp_jtag_req_o = '0;
    end

    // SMC fabric AXI JTAG2AXI bridge
    if (SMC_DBG_ENABLE) begin : gen_smc_jtag2axi
        jtag_dmi2axi #(
            .IS_AXI4_LITE   (1'b0),
            .AXI_ID_WIDTH   ($bits(axi_smc_dbg_req_o.aw.id)),
            .AXI_USER_WIDTH ($bits(axi_smc_dbg_req_o.aw.user)),
            .axi_req_t      (smc_jtag_axi_req_t),
            .axi_resp_t     (smc_jtag_axi_resp_t)
        ) u_smc_jtag2axi (
            .dtmcs_scan_ctrl_i  (smc_jtag2axi_dtmcs_scan_ctrl),
            .dmi_scan_ctrl_i    (smc_jtag2axi_scan_ctrl),
            .scan_in_i          (client_tdi_i),
            .dtmcs_scan_out_o   (smc_jtag2axi_dtmcs_scan_out),
            .dmi_scan_out_o     (smc_jtag2axi_scan_out),

            .clk_i              (clk_i),
            .rst_ni             (rst_n_i),
            .test_en_i          (test_en_i),
            .scan_rst_ni        (scan_rst_ni),

            .security_disable_i (smc_jtag2axi_security_disable),

            .axi_req_o          (axi_smc_dbg_req_o),
            .axi_resp_i         (axi_smc_dbg_resp_i)
        );
    end else begin : gen_no_smc_jtag2axi
        assign smc_jtag2axi_scan_out = client_tdi_i;
        assign smc_jtag2axi_dtmcs_scan_out = client_tdi_i;
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
                    tdr_mux = IcResetEnable ? ic_reset_reg_scan_out : byp_reg_scan_out;

                inst_decoded_o[TAP_3DCR_INSTR]:
                    tdr_mux = Ptap3dcrEnable ? tap_3dcr_reg_scan_out : byp_reg_scan_out;

                inst_decoded_o[DEBUG_CONTROL_INSTR]:
                    tdr_mux = debug_ctrl_reg_scan_out;  // Debug control register

                inst_decoded_o[JTAG_CAPS_INSTR]:
                    tdr_mux = caps_reg_scan_out;  // JTAG capabilities register

                inst_decoded_o[SMC_OTP_DTMCS_INSTR]:
                    tdr_mux = SMC_DBG_ENABLE ? smc_otp_jtag2axi_dtmcs_scan_out : byp_reg_scan_out;

                inst_decoded_o[SMC_OTP_DMI_INSTR]:
                    tdr_mux = SMC_DBG_ENABLE ? smc_otp_jtag2axi_scan_out : byp_reg_scan_out;

                inst_decoded_o[SEP_OTP_DTMCS_INSTR]:
                    tdr_mux = SEP_DBG_ENABLE ? sep_otp_jtag2axi_dtmcs_scan_out : byp_reg_scan_out;

                inst_decoded_o[SEP_OTP_DMI_INSTR]:
                    tdr_mux = SEP_DBG_ENABLE ? sep_otp_jtag2axi_scan_out : byp_reg_scan_out;

                inst_decoded_o[SMC_DTMCS_INSTR]:
                    tdr_mux = SMC_DBG_ENABLE ? smc_jtag2axi_dtmcs_scan_out : byp_reg_scan_out;

                inst_decoded_o[SMC_DMI_INSTR]:
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
    // Logic: stap_select ? stap_host_scan_in_i : (zlb_select ? client_tdi_i : tdr_mux)

    // The zero-length path exists only while STAP select is clear. The STAP chain return must
    // leave TDO through the falling-edge retimer, so with STAP select set a ZERO_LENGTH_BYPASS
    // DR scan is a BYPASS scan.
    assign zlb_select = inst_decoded_o[ZERO_LENGTH_BYPASS_INSTR] && dr_scan_select_reg &&
                        !stap_select;

    // First mux: Select between client_tdi_i (zero-length bypass) and tdr_mux
    prim_stdmux2 u_zlb_tdr_mux (
        .i0_i  (tdr_mux),
        .i1_i  (client_tdi_i),
        .sel_i (zlb_select),
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
    // ZERO_LENGTH_BYPASS DR scan with STAP select clear: select tdo_mux, bypassing the retimer
    // Otherwise: select retimed TDO
    // Use registered DR scan select to avoid glitches
    prim_stdmux2 u_tdo_bypass_mux (
        .i0_i  (tdo_retimed),
        .i1_i  (tdo_mux),
        .sel_i (zlb_select),
        .y_o   (client_tdo_o)
    );

endmodule : jtag_ptap
