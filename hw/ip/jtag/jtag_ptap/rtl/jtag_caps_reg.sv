// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Expose a read-only capabilities TDR built from elaboration-time feature parameters.
//
// Packs enable bits for BSR and optional instructions, IC_RESET port counts, STAP counts,
// cross-trigger counts, and OCH_VER into the 60-bit shift register, OCH_VER nearest TDO.
// The parameters only set the reported bits; they enable nothing in this module.
// Contents are fixed from parameters; scan_ctrl_i and scan_in_i/scan_out_o form the DR
// scan path.

module jtag_caps_reg
    import prim_jtag_pkg::*;

    `include "ocah_assert.svh"
#(
    parameter bit  BSR_ENABLE          = 1,  // Mandatory boundary-scan instructions present; bit 8.
    parameter bit  EXTEST_TRAIN_ENABLE = 1,  // Optional EXTEST_TRAIN present; bit 9.
    parameter bit  EXTEST_PULSE_ENABLE = 1,  // Optional EXTEST_PULSE present; bit 10.
    parameter bit  INTEST_ENABLE       = 1,  // Optional INTEST present; bit 11.
    parameter bit  CLAMP_ENABLE        = 1,  // Optional CLAMP present; bit 12.
    parameter bit  HIGHZ_ENABLE        = 1,  // Optional HIGHZ present; bit 13.
    parameter bit  RUNBIST_ENABLE      = 1,  // Optional RUNBIST present; bit 14.
    parameter bit  TMP_ENABLE          = 1,  // TMP controller and instructions present; bit 15.
    parameter bit  IC_RESET_ENABLE     = 1,  // IC_RESET TDR present; bit 16.
    parameter bit  SMC_DBG_ENABLE      = 1,  // SMC debug JTAG2AXI ports present; bit 41.
    parameter bit  SEP_DBG_ENABLE      = 1,  // SEP debug STAP present; bit 42.
    parameter bit  STAP_IO_ENABLE      = 1,  // Chiplet-to-chiplet STAP present; bit 43.

    parameter int unsigned  NUM_SMC_IC_RESET = 0,  // Port count of SMC IC_RESET slice (0..255);
                                                   // bits [40:33].
    parameter int unsigned  NUM_SEP_IC_RESET = 0,  // Port count of SEP IC_RESET slice (0..255);
                                                   // bits [32:25].
    parameter int unsigned  NUM_EXT_IC_RESET = 0,  // Port count of external IC_RESET slice
                                                   // (0..255); bits [24:17].
    parameter int unsigned  NUM_EXTRA_STAPS  = 0,  // Additional DTP STAP count (0..15); bits
                                                   // [47:44].

    parameter int unsigned  NUM_XTRIG_CTP     = 8,  // Cross-trigger port count (0..63); bits
                                                    // [53:48].
    parameter int unsigned  NUM_XTRIG_INT_CT  = 1,  // Internal cross-trigger count (0..63); bits
                                                    // [59:54].

    parameter logic [7:0]   OCH_VER = 8'h00  // DTP IP major version number; bits [7:0].
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
    localparam int unsigned RegWidth = 60;  // JTAG_CAPS register: 60 bits (bits 0-59)

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
    `OCAH_ASSERT_STATIC(NumXtrigCtpFits_A,   NUM_XTRIG_CTP    <= 63)
    `OCAH_ASSERT_STATIC(NumXtrigIntCtFits_A, NUM_XTRIG_INT_CT <= 63)
    `OCAH_ASSERT_STATIC(NumSmcIcResetFits_A, NUM_SMC_IC_RESET <= 255)
    `OCAH_ASSERT_STATIC(NumSepIcResetFits_A, NUM_SEP_IC_RESET <= 255)
    `OCAH_ASSERT_STATIC(NumExtIcResetFits_A, NUM_EXT_IC_RESET <= 255)
    `OCAH_ASSERT_STATIC(NumExtraStapsFits_A, NUM_EXTRA_STAPS  <= 15)

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

    localparam logic [RegWidth-1:0] CapsValue = {
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
    // Always captures the CapsValue on capture, shifts on shift
    prim_jtag_scan_reg #(
        .WIDTH(RegWidth),
        .RESET_VAL(CapsValue),
        .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
    ) u_caps_scan_reg (
        .scan_ctrl_i   (scan_ctrl_i),
        .scan_in_i     (scan_in_i),
        .scan_out_o    (scan_out_o),
        .data_in_i     (CapsValue),  // Always capture the capabilities value (read-only)
        /* verilator lint_off PINCONNECTEMPTY */
        .data_out_o    (/* UNUSED */) // No update register needed for read-only capabilities
        /* verilator lint_on PINCONNECTEMPTY */
    );

endmodule : jtag_caps_reg
