// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Define instruction opcodes and the decode enum for the primary JTAG TAP.
//
// Holds IR width, opcode constants, the one-hot jtag_instruction_decoded_e, and the IDCODE
// reset default DEFAULT_INSTRUCTION for jtag_inst_reg.
// Shared by the PTAP and interface unit so decode stays in one package.

package jtag_inst_reg_pkg;

  //--------------------------------------------------------------------------
  // Constants
  //--------------------------------------------------------------------------
  localparam int unsigned IR_WIDTH = 6;
  localparam int unsigned DECODED_IR_WIDTH = 2 ** IR_WIDTH;

  //--------------------------------------------------------------------------
  // Standard JTAG Instructions (IEEE 1149.1/1838 compliance)
  //--------------------------------------------------------------------------
  typedef enum logic [IR_WIDTH-1:0] {
    BYPASS_ALT_INSTR                                 = 6'h00,  // Bypass register (all-zero encoding per IEEE 1149.1).
    IDCODE_INSTR                                     = 6'h01,  // Device identification.
    RUNBIST_INSTR                                    = 6'h02,  // Run built-in self test.
    SAMPLE_PRELOAD_INSTR                             = 6'h03,  // Sample/preload combined instruction.
    EXTEST_INSTR                                     = 6'h04,  // External test.
    EXTEST_TRAIN_INSTR                               = 6'h05,  // External test training mode.
    EXTEST_PULSE_INSTR                               = 6'h06,  // External test pulse mode.
    CLAMP_INSTR                                      = 6'h07,  // Clamp outputs.
    HIGHZ_INSTR                                      = 6'h08,  // High impedance.
    INTEST_INSTR                                     = 6'h09,  // Internal test.
    CLAMP_HOLD_INSTR                                 = 6'h0A,  // Clamp hold (TMP controller).
    CLAMP_RELEASE_INSTR                              = 6'h0B,  // Clamp release (TMP controller).
    TMP_STATUS_INSTR                                 = 6'h0C,  // TMP status register access.
    IC_RESET_INSTR                                   = 6'h0D,  // Integrated circuit reset.
    TAP_3DCR_INSTR                                   = 6'h0E,  // TAP 3D Control Register (IEEE 1838).
    UNDEFINED_BYPASS_0F_INSTR                        = 6'h0F,  // Undefined bypass instruction.
    // RISC-V reserved instructions
    RISCV_RESERVED_0_INSTR                           = 6'h10,  // Reserved for RISC-V debug.
    RISCV_RESERVED_1_INSTR                           = 6'h11,  // Reserved for RISC-V debug.
    RISCV_RESERVED_2_INSTR                           = 6'h12,  // Reserved for RISC-V debug.
    RISCV_RESERVED_3_INSTR                           = 6'h13,  // Reserved for RISC-V debug.
    RISCV_RESERVED_4_INSTR                           = 6'h14,  // Reserved for RISC-V debug.
    RISCV_RESERVED_5_INSTR                           = 6'h15,  // Reserved for RISC-V debug.
    RISCV_RESERVED_6_INSTR                           = 6'h16,  // Reserved for RISC-V debug.
    RISCV_RESERVED_7_INSTR                           = 6'h17,  // Reserved for RISC-V debug.
    DEBUG_CONTROL_INSTR                              = 6'h18,  // Debug control register access.
    JTAG_CAPS_INSTR                                  = 6'h19,  // JTAG capabilities register.
    SELECT_IJTAG_INSTR                               = 6'h1A,  // Select iJTAG (IEEE 1687) network.
    // SMC OTP AXI instructions for AXI transaction control
    SMC_OTP_JTAG2AXI_CAPS_INSTR                      = 6'h1B,  // SMC OTP JTAG2AXI capabilities register.
    SMC_OTP_AXI_SINGLE_OP_INSTR                      = 6'h1C,  // AXISingleOp: Single AXI transaction.
    SMC_OTP_AXI_SERIES_CTRL_INSTR                    = 6'h1D,  // AXISeriesCtrl: Series transaction control.
    SMC_OTP_AXI_SERIES_DATA_INCR_INSTR               = 6'h1E,  // AXISeriesDataIncr: Series data with address increment.
    SMC_OTP_AXI_SERIES_DATA_NO_INCR_INSTR            = 6'h1F,  // AXISeriesDataNoIncr: Series data no address increment.
    SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR  = 6'h20,  // AXISeriesDataWithErrorStatus: Series data with error status.
    // SEP OTP AXI instructions for AXI transaction control
    SEP_OTP_JTAG2AXI_CAPS_INSTR                      = 6'h21,  // SEP OTP JTAG2AXI capabilities register.
    SEP_OTP_AXI_SINGLE_OP_INSTR                      = 6'h22,  // AXISingleOp: Single AXI transaction.
    SEP_OTP_AXI_SERIES_CTRL_INSTR                    = 6'h23,  // AXISeriesCtrl: Series transaction control.
    SEP_OTP_AXI_SERIES_DATA_INCR_INSTR               = 6'h24,  // AXISeriesDataIncr: Series data with address increment.
    SEP_OTP_AXI_SERIES_DATA_NO_INCR_INSTR            = 6'h25,  // AXISeriesDataNoIncr: Series data no address increment.
    SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR  = 6'h26,  // AXISeriesDataWithErrorStatus: Series data with error status.
    // SMC fabric AXI instructions for AXI transaction control
    SMC_JTAG2AXI_CAPS_INSTR                          = 6'h27,  // SMC fabric JTAG2AXI capabilities register.
    SMC_AXI_SINGLE_OP_INSTR                          = 6'h28,  // AXISingleOp: Single AXI transaction.
    SMC_AXI_SERIES_CTRL_INSTR                        = 6'h29,  // AXISeriesCtrl: Series transaction control.
    SMC_AXI_SERIES_DATA_INCR_INSTR                   = 6'h2A,  // AXISeriesDataIncr: Series data with address increment.
    SMC_AXI_SERIES_DATA_NO_INCR_INSTR                = 6'h2B,  // AXISeriesDataNoIncr: Series data no address increment.
    SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR      = 6'h2C,  // AXISeriesDataWithErrorStatus: Series data with error status.
    UNDEFINED_BYPASS_2D_INSTR                        = 6'h2D,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_2E_INSTR                        = 6'h2E,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_2F_INSTR                        = 6'h2F,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_30_INSTR                        = 6'h30,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_31_INSTR                        = 6'h31,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_32_INSTR                        = 6'h32,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_33_INSTR                        = 6'h33,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_34_INSTR                        = 6'h34,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_35_INSTR                        = 6'h35,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_36_INSTR                        = 6'h36,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_37_INSTR                        = 6'h37,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_38_INSTR                        = 6'h38,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_39_INSTR                        = 6'h39,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_3A_INSTR                        = 6'h3A,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_3B_INSTR                        = 6'h3B,  // Undefined bypass instruction.
    UNDEFINED_BYPASS_3C_INSTR                        = 6'h3C,  // Undefined bypass instruction.
    ZERO_LENGTH_BYPASS_INSTR                         = 6'h3D,  // Zero length bypass - direct TDI to TDO; BYPASS while the 3DCR STAP-select bit is set.
    INV_BYPASS_INSTR                                 = 6'h3E,  // Inverted bypass.
    BYPASS_INSTR                                     = 6'h3F   // Bypass register (all-one encoding).
  } jtag_instruction_e;

  //--------------------------------------------------------------------------
  // Decoded JTAG Instructions (One-Hot Encoding)
  //--------------------------------------------------------------------------
  // Use shift operator (<<) to create one-hot decoded signals from instruction enumeration
  typedef enum logic [DECODED_IR_WIDTH-1:0] {
    BYPASS_ALT_INSTR_DECODED                                = DECODED_IR_WIDTH'(1'b1) << BYPASS_ALT_INSTR,
    IDCODE_INSTR_DECODED                                    = DECODED_IR_WIDTH'(1'b1) << IDCODE_INSTR,
    RUNBIST_INSTR_DECODED                                   = DECODED_IR_WIDTH'(1'b1) << RUNBIST_INSTR,
    SAMPLE_PRELOAD_INSTR_DECODED                            = DECODED_IR_WIDTH'(1'b1) << SAMPLE_PRELOAD_INSTR,
    EXTEST_INSTR_DECODED                                    = DECODED_IR_WIDTH'(1'b1) << EXTEST_INSTR,
    EXTEST_TRAIN_INSTR_DECODED                              = DECODED_IR_WIDTH'(1'b1) << EXTEST_TRAIN_INSTR,
    EXTEST_PULSE_INSTR_DECODED                              = DECODED_IR_WIDTH'(1'b1) << EXTEST_PULSE_INSTR,
    CLAMP_INSTR_DECODED                                     = DECODED_IR_WIDTH'(1'b1) << CLAMP_INSTR,
    HIGHZ_INSTR_DECODED                                     = DECODED_IR_WIDTH'(1'b1) << HIGHZ_INSTR,
    INTEST_INSTR_DECODED                                    = DECODED_IR_WIDTH'(1'b1) << INTEST_INSTR,
    CLAMP_HOLD_INSTR_DECODED                                = DECODED_IR_WIDTH'(1'b1) << CLAMP_HOLD_INSTR,
    CLAMP_RELEASE_INSTR_DECODED                             = DECODED_IR_WIDTH'(1'b1) << CLAMP_RELEASE_INSTR,
    TMP_STATUS_INSTR_DECODED                                = DECODED_IR_WIDTH'(1'b1) << TMP_STATUS_INSTR,
    IC_RESET_INSTR_DECODED                                  = DECODED_IR_WIDTH'(1'b1) << IC_RESET_INSTR,
    TAP_3DCR_INSTR_DECODED                                  = DECODED_IR_WIDTH'(1'b1) << TAP_3DCR_INSTR,
    UNDEFINED_BYPASS_0F_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_0F_INSTR,
    RISCV_RESERVED_0_INSTR_DECODED                          = DECODED_IR_WIDTH'(1'b1) << RISCV_RESERVED_0_INSTR,
    RISCV_RESERVED_1_INSTR_DECODED                          = DECODED_IR_WIDTH'(1'b1) << RISCV_RESERVED_1_INSTR,
    RISCV_RESERVED_2_INSTR_DECODED                          = DECODED_IR_WIDTH'(1'b1) << RISCV_RESERVED_2_INSTR,
    RISCV_RESERVED_3_INSTR_DECODED                          = DECODED_IR_WIDTH'(1'b1) << RISCV_RESERVED_3_INSTR,
    RISCV_RESERVED_4_INSTR_DECODED                          = DECODED_IR_WIDTH'(1'b1) << RISCV_RESERVED_4_INSTR,
    RISCV_RESERVED_5_INSTR_DECODED                          = DECODED_IR_WIDTH'(1'b1) << RISCV_RESERVED_5_INSTR,
    RISCV_RESERVED_6_INSTR_DECODED                          = DECODED_IR_WIDTH'(1'b1) << RISCV_RESERVED_6_INSTR,
    RISCV_RESERVED_7_INSTR_DECODED                          = DECODED_IR_WIDTH'(1'b1) << RISCV_RESERVED_7_INSTR,
    DEBUG_CONTROL_INSTR_DECODED                             = DECODED_IR_WIDTH'(1'b1) << DEBUG_CONTROL_INSTR,
    JTAG_CAPS_INSTR_DECODED                                 = DECODED_IR_WIDTH'(1'b1) << JTAG_CAPS_INSTR,
    SELECT_IJTAG_INSTR_DECODED                              = DECODED_IR_WIDTH'(1'b1) << SELECT_IJTAG_INSTR,
    SMC_OTP_JTAG2AXI_CAPS_INSTR_DECODED                     = DECODED_IR_WIDTH'(1'b1) << SMC_OTP_JTAG2AXI_CAPS_INSTR,
    SMC_OTP_AXI_SINGLE_OP_INSTR_DECODED                     = DECODED_IR_WIDTH'(1'b1) << SMC_OTP_AXI_SINGLE_OP_INSTR,
    SMC_OTP_AXI_SERIES_CTRL_INSTR_DECODED                   = DECODED_IR_WIDTH'(1'b1) << SMC_OTP_AXI_SERIES_CTRL_INSTR,
    SMC_OTP_AXI_SERIES_DATA_INCR_INSTR_DECODED              = DECODED_IR_WIDTH'(1'b1) << SMC_OTP_AXI_SERIES_DATA_INCR_INSTR,
    SMC_OTP_AXI_SERIES_DATA_NO_INCR_INSTR_DECODED           = DECODED_IR_WIDTH'(1'b1) << SMC_OTP_AXI_SERIES_DATA_NO_INCR_INSTR,
    SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR_DECODED = DECODED_IR_WIDTH'(1'b1) << SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR,
    SEP_OTP_JTAG2AXI_CAPS_INSTR_DECODED                     = DECODED_IR_WIDTH'(1'b1) << SEP_OTP_JTAG2AXI_CAPS_INSTR,
    SEP_OTP_AXI_SINGLE_OP_INSTR_DECODED                     = DECODED_IR_WIDTH'(1'b1) << SEP_OTP_AXI_SINGLE_OP_INSTR,
    SEP_OTP_AXI_SERIES_CTRL_INSTR_DECODED                   = DECODED_IR_WIDTH'(1'b1) << SEP_OTP_AXI_SERIES_CTRL_INSTR,
    SEP_OTP_AXI_SERIES_DATA_INCR_INSTR_DECODED              = DECODED_IR_WIDTH'(1'b1) << SEP_OTP_AXI_SERIES_DATA_INCR_INSTR,
    SEP_OTP_AXI_SERIES_DATA_NO_INCR_INSTR_DECODED           = DECODED_IR_WIDTH'(1'b1) << SEP_OTP_AXI_SERIES_DATA_NO_INCR_INSTR,
    SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR_DECODED = DECODED_IR_WIDTH'(1'b1) << SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR,
    SMC_JTAG2AXI_CAPS_INSTR_DECODED                         = DECODED_IR_WIDTH'(1'b1) << SMC_JTAG2AXI_CAPS_INSTR,
    SMC_AXI_SINGLE_OP_INSTR_DECODED                         = DECODED_IR_WIDTH'(1'b1) << SMC_AXI_SINGLE_OP_INSTR,
    SMC_AXI_SERIES_CTRL_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << SMC_AXI_SERIES_CTRL_INSTR,
    SMC_AXI_SERIES_DATA_INCR_INSTR_DECODED                  = DECODED_IR_WIDTH'(1'b1) << SMC_AXI_SERIES_DATA_INCR_INSTR,
    SMC_AXI_SERIES_DATA_NO_INCR_INSTR_DECODED               = DECODED_IR_WIDTH'(1'b1) << SMC_AXI_SERIES_DATA_NO_INCR_INSTR,
    SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR_DECODED     = DECODED_IR_WIDTH'(1'b1) << SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR,
    UNDEFINED_BYPASS_2D_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_2D_INSTR,
    UNDEFINED_BYPASS_2E_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_2E_INSTR,
    UNDEFINED_BYPASS_2F_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_2F_INSTR,
    UNDEFINED_BYPASS_30_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_30_INSTR,
    UNDEFINED_BYPASS_31_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_31_INSTR,
    UNDEFINED_BYPASS_32_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_32_INSTR,
    UNDEFINED_BYPASS_33_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_33_INSTR,
    UNDEFINED_BYPASS_34_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_34_INSTR,
    UNDEFINED_BYPASS_35_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_35_INSTR,
    UNDEFINED_BYPASS_36_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_36_INSTR,
    UNDEFINED_BYPASS_37_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_37_INSTR,
    UNDEFINED_BYPASS_38_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_38_INSTR,
    UNDEFINED_BYPASS_39_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_39_INSTR,
    UNDEFINED_BYPASS_3A_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_3A_INSTR,
    UNDEFINED_BYPASS_3B_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_3B_INSTR,
    UNDEFINED_BYPASS_3C_INSTR_DECODED                       = DECODED_IR_WIDTH'(1'b1) << UNDEFINED_BYPASS_3C_INSTR,
    ZERO_LENGTH_BYPASS_INSTR_DECODED                        = DECODED_IR_WIDTH'(1'b1) << ZERO_LENGTH_BYPASS_INSTR,
    INV_BYPASS_INSTR_DECODED                                = DECODED_IR_WIDTH'(1'b1) << INV_BYPASS_INSTR,
    BYPASS_INSTR_DECODED                                    = DECODED_IR_WIDTH'(1'b1) << BYPASS_INSTR
  } jtag_instruction_decoded_e;

  localparam jtag_instruction_decoded_e DEFAULT_INSTRUCTION = IDCODE_INSTR_DECODED;  // Default instruction on reset.

endpackage : jtag_inst_reg_pkg
