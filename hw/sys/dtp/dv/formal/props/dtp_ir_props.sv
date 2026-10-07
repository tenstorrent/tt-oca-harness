// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Formal properties for the instruction register and TDR selection of the primary TAP: the 6-bit
// shift register, the 64-bit one-hot decode, the bypass rule for undefined opcodes, the TDR select
// terms, the zero-length bypass, and the read-only IDCODE and CAPS captures. Attached to jtag_ptap
// by dtp_ir_bind.sv and checked with dtp as the formal top, with every optional feature of the
// DTP configuration enabled. Every property body is a boolean over current and one-cycle-past
// values (hw/common/dv/docs/formal-property-style.adoc).
//
// The instruction register is a negedge flop loaded while the TAP sits in Update-IR, so at the
// posedge that samples update_en high the decoded instruction already equals the decode of the
// shift register sampled at the same edge. The bypass register is clocked by more instructions
// than read it: its select term shares its default arm with the undefined opcodes, so IDCODE,
// INV_BYPASS and SELECT_IJTAG scans shift it too while TDO reads their own register.
//
// The open-path frontend sizes the operand of the decode's type cast on its own, so the power
// of an unsized literal it casts is 32 bits wide and the model decodes an opcode above 0x1E to
// zero or to a sign-extended pattern. The ir tasks bound the opcode an Update-IR loads to 0x1E
// (dtp_ir_sby_env.sv) and the opcode covers span that range, so on the open path no instruction
// from 0x1F up is loaded and no clause over one is checked: the SMC OTP series data instructions
// 0x1F and 0x20, the SEP OTP and SMC capability and bridge instructions, the undefined opcodes from
// 0x2D, ZERO_LENGTH_BYPASS, INV_BYPASS and BYPASS.

`include "ocah_fv_macros.svh"

module dtp_ir_props
  import jtag_tap_pkg::*;
  import jtag_inst_reg_pkg::*;
#(
  parameter int unsigned IDCODE_WIDTH = 32,
  parameter int unsigned CAPS_WIDTH = 60
) (
  input logic                      tck_i,
  input logic                      jtag_trst_ni,         // jtag_trst_n, the combined reset
  input tap_state_e                state_i,              // current_state_o
  input jtag_instruction_decoded_e inst_i,               // inst_decoded_o
  input logic [IrWidth-1:0]        ir_shift_i,           // u_jtag_inst_reg.instruction_shift_reg_q
  input logic                      ir_rst_ni,            // ir_scan_ctrl.rst_n
  input logic                      ir_capture_en_i,      // ir_scan_ctrl.capture_en
  input logic                      ir_update_en_i,       // ir_scan_ctrl.update_en
  input logic                      dr_select_i,          // dr_scan_ctrl.select
  input logic                      dr_capture_en_i,      // dr_scan_ctrl.capture_en
  input logic                      dr_shift_en_i,        // dr_scan_ctrl.shift_en
  input logic                      dr_scan_select_reg_i, // dr_scan_select_reg
  input logic                      ir_select_i,          // ir_scan_ctrl.select
  input logic                      stap_select_i,        // stap_select
  input logic                      client_tdi_i,
  input logic                      client_tdo_i,         // client_tdo_o
  input logic                      tdr_mux_i,            // tdr_mux
  // TDR outputs the multiplexer chooses from
  input logic                      inst_reg_scan_out_i,  // inst_reg_scan_out
  input logic                      byp_scan_out_i,       // byp_reg_scan_out
  input logic                      inv_byp_scan_out_i,   // inv_byp_reg_scan_out
  input logic                      idcode_scan_out_i,    // idcode_reg_scan_out
  input logic                      tap_3dcr_scan_out_i,  // tap_3dcr_reg_scan_out
  input logic                      tmp_status_scan_out_i,// tmp_status_reg_scan_out
  input logic                      ic_reset_scan_out_i,  // ic_reset_reg_scan_out
  input logic                      debug_ctrl_scan_out_i,// debug_ctrl_reg_scan_out
  input logic                      caps_scan_out_i,      // caps_reg_scan_out
  input logic                      smc_otp_caps_scan_out_i, // smc_otp_2axi_caps_reg_scan_out
  input logic                      sep_otp_caps_scan_out_i, // sep_otp_2axi_caps_reg_scan_out
  input logic                      smc_caps_scan_out_i,  // smc_2axi_caps_reg_scan_out
  input logic                      smc_otp_j2a_scan_out_i, // smc_otp_jtag2axi_scan_out
  input logic                      sep_otp_j2a_scan_out_i, // sep_otp_jtag2axi_scan_out
  input logic                      smc_j2a_scan_out_i,   // smc_jtag2axi_scan_out
  input logic                      bsr_scan_in_i,        // bsr_host_scan_in_i
  input logic                      ijtag_scan_in_i,      // ijtag_host_scan_in_i
  // TDR select terms
  input logic                      byp_sel_i,            // byp_reg_scan_ctrl.select
  input logic                      inv_byp_sel_i,        // inv_byp_reg_scan_ctrl.select
  input logic                      idcode_sel_i,         // idcode_reg_scan_ctrl.select
  input logic                      tap_3dcr_sel_i,       // tap_3dcr_reg_scan_ctrl.select
  input logic                      tmp_status_sel_i,     // tmp_status_reg_scan_ctrl.select
  input logic                      ic_reset_sel_i,       // ic_reset_reg_scan_ctrl.select
  input logic                      debug_ctrl_sel_i,     // debug_ctrl_reg_scan_ctrl.select
  input logic                      caps_sel_i,           // caps_reg_scan_ctrl.select
  input logic                      smc_otp_caps_sel_i,   // smc_otp_2axi_caps_reg_scan_ctrl.select
  input logic                      sep_otp_caps_sel_i,   // sep_otp_2axi_caps_reg_scan_ctrl.select
  input logic                      smc_caps_sel_i,       // smc_2axi_caps_reg_scan_ctrl.select
  input logic                      smc_otp_j2a_sel_i,    // smc_otp_jtag2axi_scan_ctrl.select
  input logic                      sep_otp_j2a_sel_i,    // sep_otp_jtag2axi_scan_ctrl.select
  input logic                      smc_j2a_sel_i,        // smc_jtag2axi_scan_ctrl.select
  input logic                      bsr_sel_i,            // bsr_host_scan_ctrl_o.select
  input logic                      ijtag_sel_i,          // ijtag_host_scan_ctrl_o.select
  // Read-only captures
  input logic [IDCODE_WIDTH-1:0]   idcode_scan_i,        // u_idcode_scan_reg.scan_data
  input logic [IDCODE_WIDTH-1:0]   idcode_value_i,       // IdcodeValue
  input logic [CAPS_WIDTH-1:0]     caps_scan_i,          // u_caps_scan_reg.scan_data
  input logic [CAPS_WIDTH-1:0]     caps_value_i          // CapsValue
);

  localparam logic [DecodedIrWidth-1:0] AllOnesLowByte = {8{1'b1}};

  // Opcodes with no register of their own: 0x0F, the RISC-V reserved block 0x10 to 0x17, and
  // 0x2D to 0x3C. Each selects the bypass register.
  localparam logic [DecodedIrWidth-1:0] UndefinedMask =
      (DecodedIrWidth'(1) << UNDEFINED_BYPASS_0F_INSTR) |
      (AllOnesLowByte << RISCV_RESERVED_0_INSTR) |
      (DecodedIrWidth'(16'hFFFF) << UNDEFINED_BYPASS_2D_INSTR);

  // Opcodes whose DR scan reads the bypass register at TDO; ZERO_LENGTH_BYPASS reads it there
  // outside the shift states, where TDI takes over while the 3DCR STAP-select bit is clear.
  localparam logic [DecodedIrWidth-1:0] BypassUsersMask =
      UndefinedMask | BYPASS_INSTR_DECODED | BYPASS_ALT_INSTR_DECODED |
      CLAMP_INSTR_DECODED | HIGHZ_INSTR_DECODED | CLAMP_HOLD_INSTR_DECODED |
      CLAMP_RELEASE_INSTR_DECODED | ZERO_LENGTH_BYPASS_INSTR_DECODED;

  // Opcodes whose DR scan clocks the bypass register: every bypass user except
  // ZERO_LENGTH_BYPASS, plus IDCODE, INV_BYPASS and SELECT_IJTAG, whose select term falls into
  // the same default arm as the undefined opcodes while TDO reads their own register.
  // ZERO_LENGTH_BYPASS clocks it only while the 3DCR STAP-select bit is set.
  localparam logic [DecodedIrWidth-1:0] BypassSelectMask =
      (BypassUsersMask & ~ZERO_LENGTH_BYPASS_INSTR_DECODED) | IDCODE_INSTR_DECODED |
      INV_BYPASS_INSTR_DECODED | SELECT_IJTAG_INSTR_DECODED;

  localparam logic [DecodedIrWidth-1:0] BsrMask =
      EXTEST_INSTR_DECODED | SAMPLE_PRELOAD_INSTR_DECODED | EXTEST_TRAIN_INSTR_DECODED |
      EXTEST_PULSE_INSTR_DECODED | INTEST_INSTR_DECODED;

  localparam logic [DecodedIrWidth-1:0] IjtagMask =
      SELECT_IJTAG_INSTR_DECODED | RUNBIST_INSTR_DECODED;

  localparam logic [DecodedIrWidth-1:0] SmcOtpAxiMask =
      SMC_OTP_AXI_SINGLE_OP_INSTR_DECODED | SMC_OTP_AXI_SERIES_CTRL_INSTR_DECODED |
      SMC_OTP_AXI_SERIES_DATA_INCR_INSTR_DECODED | SMC_OTP_AXI_SERIES_DATA_NO_INCR_INSTR_DECODED |
      SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR_DECODED;

  localparam logic [DecodedIrWidth-1:0] SepOtpAxiMask =
      SEP_OTP_AXI_SINGLE_OP_INSTR_DECODED | SEP_OTP_AXI_SERIES_CTRL_INSTR_DECODED |
      SEP_OTP_AXI_SERIES_DATA_INCR_INSTR_DECODED | SEP_OTP_AXI_SERIES_DATA_NO_INCR_INSTR_DECODED |
      SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR_DECODED;

  localparam logic [DecodedIrWidth-1:0] SmcAxiMask =
      SMC_AXI_SINGLE_OP_INSTR_DECODED | SMC_AXI_SERIES_CTRL_INSTR_DECODED |
      SMC_AXI_SERIES_DATA_INCR_INSTR_DECODED | SMC_AXI_SERIES_DATA_NO_INCR_INSTR_DECODED |
      SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR_DECODED;

  logic [DecodedIrWidth-1:0] inst_bits;
  assign inst_bits = inst_i;

  // The selects of the registers with state of their own; the bypass select stands apart.
  logic [14:0] reg_selects;
  assign reg_selects = {
    inv_byp_sel_i,
    idcode_sel_i,
    tap_3dcr_sel_i,
    tmp_status_sel_i,
    ic_reset_sel_i,
    debug_ctrl_sel_i,
    caps_sel_i,
    smc_otp_caps_sel_i,
    sep_otp_caps_sel_i,
    smc_caps_sel_i,
    smc_otp_j2a_sel_i,
    sep_otp_j2a_sel_i,
    smc_j2a_sel_i,
    bsr_sel_i,
    ijtag_sel_i
  };

  // The register a DR scan reads at TDO under each instruction.
  logic tdr_route;
  always_comb begin
    if (|(inst_bits & BypassUsersMask)) tdr_route = byp_scan_out_i;
    else if (inst_i[IDCODE_INSTR]) tdr_route = idcode_scan_out_i;
    else if (inst_i[INV_BYPASS_INSTR]) tdr_route = inv_byp_scan_out_i;
    else if (inst_i[TAP_3DCR_INSTR]) tdr_route = tap_3dcr_scan_out_i;
    else if (inst_i[TMP_STATUS_INSTR]) tdr_route = tmp_status_scan_out_i;
    else if (inst_i[IC_RESET_INSTR]) tdr_route = ic_reset_scan_out_i;
    else if (inst_i[DEBUG_CONTROL_INSTR]) tdr_route = debug_ctrl_scan_out_i;
    else if (inst_i[JTAG_CAPS_INSTR]) tdr_route = caps_scan_out_i;
    else if (inst_i[SMC_OTP_JTAG2AXI_CAPS_INSTR]) tdr_route = smc_otp_caps_scan_out_i;
    else if (inst_i[SEP_OTP_JTAG2AXI_CAPS_INSTR]) tdr_route = sep_otp_caps_scan_out_i;
    else if (inst_i[SMC_JTAG2AXI_CAPS_INSTR]) tdr_route = smc_caps_scan_out_i;
    else if (|(inst_bits & SmcOtpAxiMask)) tdr_route = smc_otp_j2a_scan_out_i;
    else if (|(inst_bits & SepOtpAxiMask)) tdr_route = sep_otp_j2a_scan_out_i;
    else if (|(inst_bits & SmcAxiMask)) tdr_route = smc_j2a_scan_out_i;
    else if (|(inst_bits & BsrMask)) tdr_route = bsr_scan_in_i;
    else tdr_route = ijtag_scan_in_i;
  end

  // Each TDR is selected exactly while the DR path is selected under its own instruction.
  logic selects_match_instruction;
  assign selects_match_instruction =
      byp_sel_i          == (dr_select_i && (|(inst_bits & BypassSelectMask) ||
                                             (inst_i[ZERO_LENGTH_BYPASS_INSTR] &&
                                              stap_select_i))) &&
      inv_byp_sel_i      == (dr_select_i && inst_i[INV_BYPASS_INSTR]) &&
      idcode_sel_i       == (dr_select_i && inst_i[IDCODE_INSTR]) &&
      tap_3dcr_sel_i     == (dr_select_i && inst_i[TAP_3DCR_INSTR]) &&
      tmp_status_sel_i   == (dr_select_i && inst_i[TMP_STATUS_INSTR]) &&
      ic_reset_sel_i     == (dr_select_i && inst_i[IC_RESET_INSTR]) &&
      debug_ctrl_sel_i   == (dr_select_i && inst_i[DEBUG_CONTROL_INSTR]) &&
      caps_sel_i         == (dr_select_i && inst_i[JTAG_CAPS_INSTR]) &&
      smc_otp_caps_sel_i == (dr_select_i && inst_i[SMC_OTP_JTAG2AXI_CAPS_INSTR]) &&
      sep_otp_caps_sel_i == (dr_select_i && inst_i[SEP_OTP_JTAG2AXI_CAPS_INSTR]) &&
      smc_caps_sel_i     == (dr_select_i && inst_i[SMC_JTAG2AXI_CAPS_INSTR]) &&
      smc_otp_j2a_sel_i  == (dr_select_i && |(inst_bits & SmcOtpAxiMask))    &&
      sep_otp_j2a_sel_i  == (dr_select_i && |(inst_bits & SepOtpAxiMask))    &&
      smc_j2a_sel_i      == (dr_select_i && |(inst_bits & SmcAxiMask)) &&
      bsr_sel_i          == (dr_select_i && |(inst_bits & BsrMask)) &&
      ijtag_sel_i        == (dr_select_i && |(inst_bits & IjtagMask));

  // The highest opcode the open-path frontend decodes as the RTL does.
  localparam logic [IrWidth-1:0] OpenPathMaxOpcode = 6'h1E;

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(tck_i, jtag_trst_ni)

  // ---- Instruction register -----------------------------------------------------------------
  `OCAH_FV_ASSERT(ast_ir_decoded_one_hot, $countones(inst_bits) == 1, tck_i, jtag_trst_ni)
  `OCAH_FV_ASSERT(ast_ir_capture_loads_01,
                  `OCAH_FV_IMPLIES($past(jtag_trst_ni) && $past(ir_capture_en_i),
                                   ir_shift_i == IrWidth'(1)),
                  tck_i, jtag_trst_ni)
  `OCAH_FV_ASSERT(ast_ir_update_decodes_shift_reg,
                  `OCAH_FV_IMPLIES(ir_update_en_i,
                                   inst_bits == (DecodedIrWidth'(1) << ir_shift_i)) &&
                  `OCAH_FV_IMPLIES($past(jtag_trst_ni) && !ir_update_en_i && ir_rst_ni,
                                   inst_bits == $past(inst_bits)),
                  tck_i, jtag_trst_ni)
  `OCAH_FV_ASSERT(ast_ir_reset_is_idcode,
                  `OCAH_FV_IMPLIES(!jtag_trst_ni || state_i == TEST_LOGIC_RESET,
                                   inst_i == IDCODE_INSTR_DECODED),
                  tck_i, 1'b1)

  // ---- TDR selection and routing ------------------------------------------------------------
  `OCAH_FV_ASSERT(ast_tdr_select_one_hot,
                  $countones(reg_selects) <= 1 &&
                  `OCAH_FV_IMPLIES(!dr_select_i, reg_selects == '0 && !byp_sel_i) &&
                  `OCAH_FV_IMPLIES(dr_select_i, $countones(reg_selects) == 1 ||
                                                |(inst_bits & BypassUsersMask)) &&
                  selects_match_instruction &&
                  tdr_mux_i == (ir_select_i ? inst_reg_scan_out_i : tdr_route),
                  tck_i, jtag_trst_ni)
  `OCAH_FV_ASSERT(ast_undefined_selects_bypass,
                  `OCAH_FV_IMPLIES(dr_select_i && |(inst_bits & UndefinedMask),
                                   byp_sel_i && tdr_mux_i == byp_scan_out_i),
                  tck_i, jtag_trst_ni)
  `OCAH_FV_ASSERT(ast_zlb_bypasses_retimer,
                  `OCAH_FV_IMPLIES(inst_i[ZERO_LENGTH_BYPASS_INSTR] && dr_scan_select_reg_i &&
                                   !stap_select_i,
                                   client_tdo_i == client_tdi_i),
                  tck_i, jtag_trst_ni)
  `OCAH_FV_ASSERT(ast_idcode_caps_read_only,
                  `OCAH_FV_IMPLIES($past(jtag_trst_ni) && $past(idcode_sel_i && dr_capture_en_i),
                                   idcode_scan_i == idcode_value_i) &&
                  `OCAH_FV_IMPLIES($past(jtag_trst_ni) && $past(caps_sel_i && dr_capture_en_i),
                                   caps_scan_i == caps_value_i),
                  tck_i, jtag_trst_ni)

  // ---- Covers: one per opcode the open path decodes, and the reads the decode bound leaves ----
  for (genvar o = 0; o <= int'(OpenPathMaxOpcode); o++) begin : gen_opcode
    `OCAH_FV_COVER(cov_ir_opcode, inst_bits == (DecodedIrWidth'(1) << o), tck_i, jtag_trst_ni)
  end
  `OCAH_FV_COVER(cov_undefined_opcode_bypass,
                 byp_sel_i && inst_i[UNDEFINED_BYPASS_0F_INSTR] && dr_shift_en_i,
                 tck_i, jtag_trst_ni)
  `OCAH_FV_COVER(cov_reserved_opcode_bypass,
                 byp_sel_i && inst_i[RISCV_RESERVED_0_INSTR] && dr_shift_en_i,
                 tck_i, jtag_trst_ni)
  `OCAH_FV_COVER(cov_caps_read, caps_sel_i && dr_capture_en_i, tck_i, jtag_trst_ni)
  `OCAH_FV_COVER(cov_smc_otp_caps_read, smc_otp_caps_sel_i && dr_capture_en_i, tck_i, jtag_trst_ni)
  `OCAH_FV_COVER(cov_debug_control_shift, debug_ctrl_sel_i && dr_shift_en_i, tck_i, jtag_trst_ni)
  // verilog_format: on

endmodule : dtp_ir_props
