// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Expose a read-only capabilities TDR built from elaboration-time feature parameters.
//
// Packs enable bits for BSR and optional instructions, IC_RESET port counts, STAP counts,
// cross-trigger counts, and OCH_VER into the shift register.
// Contents are fixed from parameters; scan_ctrl_i and scan_in_i/scan_out_o form the DR
// scan path.

module jtag_caps_reg
    import prim_jtag_pkg::*;

    `include "prim_assert.sv"
#(
    parameter bit  BSR_ENABLE          = 1,  // Enable mandatory boundary-scan instructions.
    parameter bit  EXTEST_TRAIN_ENABLE = 1,  // Enable optional EXTEST_TRAIN.
    parameter bit  EXTEST_PULSE_ENABLE = 1,  // Enable optional EXTEST_PULSE.
    parameter bit  INTEST_ENABLE       = 1,  // Enable optional INTEST.
    parameter bit  CLAMP_ENABLE        = 1,  // Enable optional CLAMP.
    parameter bit  HIGHZ_ENABLE        = 1,  // Enable optional HIGHZ.
    parameter bit  RUNBIST_ENABLE      = 1,  // Enable optional RUNBIST.
    parameter bit  TMP_ENABLE          = 1,  // Enable TMP controller and instructions.
    parameter bit  IC_RESET_ENABLE     = 1,  // Enable the IC_RESET TDR.
    parameter bit  SMC_DBG_ENABLE      = 1,  // Enable SMC debug JTAG2AXI ports.
    parameter bit  SEP_DBG_ENABLE      = 1,  // Enable SEP debug STAP.
    parameter bit  STAP_IO_ENABLE      = 1,  // Enable chiplet-to-chiplet STAP.

    parameter int unsigned  NUM_SMC_IC_RESET = 0,  // Port count of SMC IC_RESET slice (0..255).
    parameter int unsigned  NUM_SEP_IC_RESET = 0,  // Port count of SEP IC_RESET slice (0..255).
    parameter int unsigned  NUM_EXT_IC_RESET = 0,  // Port count of external IC_RESET slice (0..255).
    parameter int unsigned  NUM_EXTRA_STAPS  = 0,  // Additional DTP STAP count.

    parameter int unsigned  NUM_XTRIG_CTP     = 8,  // Cross-trigger port count in CAPS.
    parameter int unsigned  NUM_XTRIG_INT_CT  = 1,  // Internal cross-trigger count in CAPS.

    parameter logic [7:0]   OCH_VER = 8'h00  // DTP IP major version number.
) (
    /* verilator lint_off UNUSEDSIGNAL */
    input  jtag_scan_ctrl_t  scan_ctrl_i,  // JTAG DR/IR scan control.
    /* verilator lint_on UNUSEDSIGNAL */
    input  logic             scan_in_i,  // Scan data in (TDI).
    output logic             scan_out_o  // Scan data out (TDO).
);

    //--------------------------------------------------------------------------
    // Local Parameters
    //--------------------------------------------------------------------------
    localparam int unsigned REG_WIDTH = 60;  // JTAG_CAPS register: 60 bits (bits 0-59)

    //--------------------------------------------------------------------------
    // Local Type Definitions
    //--------------------------------------------------------------------------
    typedef logic [7:0] u8_t;
    typedef logic [5:0] u6_t;
    typedef logic [3:0] u4_t;

    //--------------------------------------------------------------------------
    // Parameter Validation
    //--------------------------------------------------------------------------
    // Compile-time assertions to verify parameters fit in their allocated bit fields
    `OCAH_OT_ASSERT_STATIC_LINT_ERROR(NumXtrigCtpFits_A,   NUM_XTRIG_CTP    <= 63)
    `OCAH_OT_ASSERT_STATIC_LINT_ERROR(NumXtrigIntCtFits_A, NUM_XTRIG_INT_CT <= 63)
    `OCAH_OT_ASSERT_STATIC_LINT_ERROR(NumSmcIcResetFits_A, NUM_SMC_IC_RESET <= 255)
    `OCAH_OT_ASSERT_STATIC_LINT_ERROR(NumSepIcResetFits_A, NUM_SEP_IC_RESET <= 255)
    `OCAH_OT_ASSERT_STATIC_LINT_ERROR(NumExtIcResetFits_A, NUM_EXT_IC_RESET <= 255)
    `OCAH_OT_ASSERT_STATIC_LINT_ERROR(NumExtraStapsFits_A, NUM_EXTRA_STAPS  <= 15)

    //--------------------------------------------------------------------------
    // JTAG Capabilities Value Construction
    //--------------------------------------------------------------------------
    // Bit field layout (from MSB to LSB, closest to TDI):
    // [59:54] = num_xtrig_int_ct (6 bits)
    // [53:48] = num_xtrig_ctp (6 bits)
    // [47:44] = num_xtra_stap (4 bits)
    // [43]    = stap_io_en (1 bit)
    // [42]    = sep_dbg_en (1 bit)
    // [41]    = smc_dbg_en (1 bit)
    // [40:33] = num_smc_ic_rst (8 bits)
    // [32:25] = num_sep_ic_rst (8 bits)
    // [24:17] = num_ext_ic_rst (8 bits)
    // [16]    = ic_rst_inst_en (1 bit)
    // [15]    = tmp_inst_en (1 bit)
    // [14]    = runbist_inst_en (1 bit)
    // [13]    = highz_inst_en (1 bit)
    // [12]    = clamp_inst_en (1 bit)
    // [11]    = intest_inst_en (1 bit)
    // [10]    = extest_pulse_en (1 bit)
    // [9]     = extest_train_en (1 bit)
    // [8]     = bsr_inst_en (1 bit)
    // [7:0]   = och_ver (8 bits)

    localparam logic [REG_WIDTH-1:0] CAPS_VALUE = {
        u6_t'(NUM_XTRIG_INT_CT),       // Bits [59:54] - num_xtrig_int_ct
        u6_t'(NUM_XTRIG_CTP),          // Bits [53:48] - num_xtrig_ctp
        u4_t'(NUM_EXTRA_STAPS),        // Bits [47:44] - num_xtra_stap
        STAP_IO_ENABLE,                // Bit  [43]    - stap_io_en
        SEP_DBG_ENABLE,                // Bit  [42]    - sep_dbg_en
        SMC_DBG_ENABLE,                // Bit  [41]    - smc_dbg_en
        u8_t'(NUM_SMC_IC_RESET),       // Bits [40:33] - num_smc_ic_rst
        u8_t'(NUM_SEP_IC_RESET),       // Bits [32:25] - num_sep_ic_rst
        u8_t'(NUM_EXT_IC_RESET),       // Bits [24:17] - num_ext_ic_rst
        IC_RESET_ENABLE,               // Bit  [16]    - ic_rst_inst_en
        TMP_ENABLE,                    // Bit  [15]    - tmp_inst_en
        RUNBIST_ENABLE,                // Bit  [14]    - runbist_inst_en
        HIGHZ_ENABLE,                  // Bit  [13]    - highz_inst_en
        CLAMP_ENABLE,                  // Bit  [12]    - clamp_inst_en
        INTEST_ENABLE,                 // Bit  [11]    - intest_inst_en
        EXTEST_PULSE_ENABLE,           // Bit  [10]    - extest_pulse_en
        EXTEST_TRAIN_ENABLE,           // Bit  [9]     - extest_train_en
        BSR_ENABLE,                    // Bit  [8]     - bsr_inst_en
        OCH_VER                        // Bits [7:0]   - och_ver
    };

    //--------------------------------------------------------------------------
    // JTAG Capabilities Register
    //--------------------------------------------------------------------------
    // 60-bit read-only capabilities register
    // Always captures the CAPS_VALUE on capture, shifts on shift
    prim_jtag_scan_reg #(
        .WIDTH(REG_WIDTH),
        .RESET_VAL(CAPS_VALUE),
        .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
    ) u_caps_scan_reg (
        .scan_ctrl_i   (scan_ctrl_i),
        .scan_in_i     (scan_in_i),
        .scan_out_o    (scan_out_o),
        .data_in_i     (CAPS_VALUE),  // Always capture the capabilities value (read-only)
        /* verilator lint_off PINCONNECTEMPTY */
        .data_out_o    (/* UNUSED */) // No update register needed for read-only capabilities
        /* verilator lint_on PINCONNECTEMPTY */
    );

endmodule : jtag_caps_reg
