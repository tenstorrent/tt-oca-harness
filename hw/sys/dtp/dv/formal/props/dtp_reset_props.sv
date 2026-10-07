// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Formal properties for the reset hierarchy of the primary TAP: the combined asynchronous reset,
// the scan reset derived from Test-Logic-Reset, the TMP persistence controller, and the registers
// whose reset the standard reserves (IC_RESET behind reset_hold, the PTAP 3DCR behind config_hold).
// Attached to jtag_ptap by dtp_reset_bind.sv and checked with dtp as the formal top. Every property
// body is a boolean over current and one-cycle-past values
// (hw/common/dv/docs/formal-property-style.adoc).
//
// The scan reset and the register reset gates change only at tck negedges and hold until the next
// one, so a gate sampled high at two consecutive posedges was high throughout the cycle between
// them; the hold properties use that pair of samples. The asynchronous resets are asserted only
// before the first sampling edge, TRST and the power-on reset each alone or both together
// (dtp_sby_env.sv), so the properties on them are never disabled and describe the reset state
// itself.

`include "ocah_fv_macros.svh"

module dtp_reset_props
  import jtag_tap_pkg::*;
  import jtag_inst_reg_pkg::*;
#(
  parameter int unsigned NUM_IC_RESET = 3
) (
  input logic                      tck_i,
  input logic                      client_trst_ni,     // client_tap_ctrl_i.trst_n
  input logic                      pwr_on_rst_ni,
  input logic                      jtag_trst_ni,       // jtag_trst_n, the combined reset
  input tap_state_e                state_i,            // current_state_o
  input jtag_instruction_decoded_e inst_i,             // inst_decoded_o
  input logic                      tlr_flag_i,         // u_jtag_tap_ctrlr.test_logic_reset
  input logic                      dr_rst_ni,          // dr_scan_ctrl.rst_n
  input logic                      dr_chrst_ni,        // dr_scan_ctrl.chrst_n
  input logic                      ir_rst_ni,          // ir_scan_ctrl.rst_n
  input logic                      ir_chrst_ni,        // ir_scan_ctrl.chrst_n
  input logic                      ir_update_en_i,     // ir_scan_ctrl.update_en
  input logic                      persistence_i,      // persistence_mode
  input logic                      escape_i,           // bypass_escape_bit
  input logic                      ic_reset_hold_i,    // u_jtag_ic_reset_reg.reset_hold
  input logic                      ic_reset_gate_ni,   // u_jtag_ic_reset_reg.rst_n_gate
  input logic [2*NUM_IC_RESET-1:0] ic_reset_data_i,    // u_jtag_ic_reset_reg.reset_enable_control_data
  input logic [NUM_IC_RESET-1:0]   ic_ovrd_i,          // ic_reset_ovrd_bus
  input logic [NUM_IC_RESET-1:0]   ic_ctrl_ni,         // ic_reset_ctrl_n_bus
  input logic [1:0]                ptap_3dcr_i,        // {stap_select, config_hold}
  input logic                      ptap_3dcr_sticky_i, // u_jtag_3dcr_reg.config_hold_sticky
  input logic                      ptap_3dcr_gate_ni   // u_jtag_3dcr_reg.rst_n_gate
);

  // The bypass escape needs Update-IR, an explicit BYPASS opcode and the escape bit together.
  logic escape_now;
  assign escape_now = ir_update_en_i && escape_i &&
                      (inst_i[BYPASS_INSTR] || inst_i[BYPASS_ALT_INSTR]);

  // IC_RESET packs {reset_control, reset_enable} per port from TDI to TDO; the override output is
  // the inversion of the active-low reset_enable field.
  logic ovrd_is_not_enable;
  always_comb begin
    ovrd_is_not_enable = 1'b1;
    for (int unsigned k = 0; k < NUM_IC_RESET; k++) begin
      ovrd_is_not_enable &= (ic_ovrd_i[k] == !ic_reset_data_i[2*k]) &&
                            (ic_ctrl_ni[k] == ic_reset_data_i[2*k+1]);
    end
  end

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(tck_i, jtag_trst_ni)

  // ---- Reset sources ------------------------------------------------------------------------
  `OCAH_FV_ASSERT(ast_trst_or_por_resets_tap,
                  jtag_trst_ni == (client_trst_ni && pwr_on_rst_ni) &&
                  `OCAH_FV_IMPLIES(!jtag_trst_ni,
                                   state_i == TEST_LOGIC_RESET && tlr_flag_i &&
                                   inst_i == IDCODE_INSTR_DECODED),
                  tck_i, 1'b1)
  `OCAH_FV_ASSERT(ast_tlr_asserts_rst_n,
                  tlr_flag_i == (state_i == TEST_LOGIC_RESET) &&
                  dr_rst_ni == !tlr_flag_i && ir_rst_ni == dr_rst_ni,
                  tck_i, jtag_trst_ni)
  `OCAH_FV_ASSERT(ast_chrst_follows_rst_unless_persistent,
                  dr_chrst_ni == (dr_rst_ni || persistence_i) && ir_chrst_ni == dr_chrst_ni,
                  tck_i, jtag_trst_ni)

  // ---- TMP persistence controller -----------------------------------------------------------
  `OCAH_FV_ASSERT(ast_tmp_on_only_by_clamp_hold,
                  `OCAH_FV_IMPLIES($past(jtag_trst_ni) && !$past(persistence_i),
                                   persistence_i == $past(inst_i[CLAMP_HOLD_INSTR])),
                  tck_i, jtag_trst_ni)
  `OCAH_FV_ASSERT(ast_tmp_off_by_release_or_escape,
                  `OCAH_FV_IMPLIES($past(jtag_trst_ni) && $past(persistence_i),
                                   persistence_i ==
                                   !($past(inst_i[CLAMP_RELEASE_INSTR]) || $past(escape_now))),
                  tck_i, jtag_trst_ni)
  `OCAH_FV_ASSERT(ast_tmp_survives_tlr,
                  `OCAH_FV_IMPLIES($past(jtag_trst_ni) && $past(state_i) == TEST_LOGIC_RESET,
                                   persistence_i == $past(persistence_i)),
                  tck_i, jtag_trst_ni)

  // ---- IC_RESET: reset_hold gates the Test-Logic-Reset reset, TRST clears everything ---------
  `OCAH_FV_ASSERT(ast_ic_reset_hold_blocks_tlr,
                  ic_reset_gate_ni == (dr_rst_ni || !ic_reset_hold_i) &&
                  `OCAH_FV_IMPLIES(!ic_reset_gate_ni, ic_reset_data_i == '1) &&
                  `OCAH_FV_IMPLIES($past(jtag_trst_ni) &&
                                   $past(state_i) == TEST_LOGIC_RESET &&
                                   state_i == TEST_LOGIC_RESET &&
                                   ic_reset_gate_ni && $past(ic_reset_gate_ni),
                                   ic_reset_data_i == $past(ic_reset_data_i)),
                  tck_i, jtag_trst_ni)
  `OCAH_FV_ASSERT(ast_ic_reset_trst_clears_all,
                  `OCAH_FV_IMPLIES(!jtag_trst_ni, ic_reset_hold_i && ic_reset_data_i == '1),
                  tck_i, 1'b1)
  `OCAH_FV_ASSERT(ast_ic_reset_ovrd_is_not_enable, ovrd_is_not_enable, tck_i, jtag_trst_ni)

  // ---- PTAP 3DCR: config_hold gates the Test-Logic-Reset reset, TRST clears it ---------------
  `OCAH_FV_ASSERT(ast_3dcr_config_hold_blocks_tlr,
                  ptap_3dcr_gate_ni == (jtag_trst_ni && (ptap_3dcr_sticky_i || dr_rst_ni)) &&
                  `OCAH_FV_IMPLIES(!ptap_3dcr_gate_ni, ptap_3dcr_i == '0) &&
                  `OCAH_FV_IMPLIES($past(jtag_trst_ni) &&
                                   $past(state_i) == TEST_LOGIC_RESET &&
                                   state_i == TEST_LOGIC_RESET &&
                                   ptap_3dcr_gate_ni && $past(ptap_3dcr_gate_ni),
                                   ptap_3dcr_i == $past(ptap_3dcr_i)),
                  tck_i, 1'b1)

  // ---- Covers -------------------------------------------------------------------------------
  `OCAH_FV_COVER(cov_trst_alone_asserted, !client_trst_ni && pwr_on_rst_ni, tck_i, 1'b1)
  `OCAH_FV_COVER(cov_por_alone_asserted, client_trst_ni && !pwr_on_rst_ni, tck_i, 1'b1)
  `OCAH_FV_COVER(cov_tmp_on, `OCAH_FV_ROSE(persistence_i), tck_i, jtag_trst_ni)
  `OCAH_FV_COVER(cov_tmp_off_by_release,
                 `OCAH_FV_FELL(persistence_i) && $past(inst_i[CLAMP_RELEASE_INSTR]),
                 tck_i, jtag_trst_ni)
  `OCAH_FV_COVER(cov_tmp_off_by_escape,
                 `OCAH_FV_FELL(persistence_i) && !$past(inst_i[CLAMP_RELEASE_INSTR]),
                 tck_i, jtag_trst_ni)
  `OCAH_FV_COVER(cov_tmp_holds_chrst_in_tlr,
                 state_i == TEST_LOGIC_RESET && persistence_i && dr_chrst_ni,
                 tck_i, jtag_trst_ni)
  `OCAH_FV_COVER(cov_ic_reset_override_held_across_tlr,
                 state_i == TEST_LOGIC_RESET && !ic_reset_hold_i && ic_reset_data_i != '1,
                 tck_i, jtag_trst_ni)
  `OCAH_FV_COVER(cov_3dcr_held_across_tlr,
                 state_i == TEST_LOGIC_RESET && ptap_3dcr_i != '0,
                 tck_i, jtag_trst_ni)
  // verilog_format: on

endmodule : dtp_reset_props
