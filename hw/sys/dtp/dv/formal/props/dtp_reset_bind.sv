// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Attaches dtp_reset_props to every jtag_ptap instance under the dtp formal top. Internal signals
// reach the property module through this port list only; the RTL carries no properties.

bind jtag_ptap dtp_reset_props #(
  .NUM_IC_RESET (NUM_IC_RESET)
) u_dtp_reset_props (
  .tck_i              (client_tap_ctrl_i.tck),
  .client_trst_ni     (client_tap_ctrl_i.trst_n),
  .pwr_on_rst_ni      (pwr_on_rst_ni),
  .jtag_trst_ni       (jtag_trst_n),
  .state_i            (current_state_o),
  .inst_i             (inst_decoded_o),
  .tlr_flag_i         (u_jtag_tap_ctrlr.test_logic_reset),
  .dr_rst_ni          (dr_scan_ctrl.rst_n),
  .dr_chrst_ni        (dr_scan_ctrl.chrst_n),
  .ir_rst_ni          (ir_scan_ctrl.rst_n),
  .ir_chrst_ni        (ir_scan_ctrl.chrst_n),
  .ir_update_en_i     (ir_scan_ctrl.update_en),
  .persistence_i      (persistence_mode),
  .escape_i           (bypass_escape_bit),
  .ic_reset_hold_i    (gen_ic_reset_reg.u_jtag_ic_reset_reg.reset_hold),
  .ic_reset_gate_ni   (gen_ic_reset_reg.u_jtag_ic_reset_reg.rst_n_gate),
  .ic_reset_data_i    (gen_ic_reset_reg.u_jtag_ic_reset_reg.reset_enable_control_data),
  .ic_ovrd_i          (ic_reset_ovrd_bus),
  .ic_ctrl_ni         (ic_reset_ctrl_n_bus),
  .ptap_3dcr_i        ({stap_select, gen_tap_3dcr_reg.u_jtag_3dcr_reg.config_hold}),
  .ptap_3dcr_sticky_i (gen_tap_3dcr_reg.u_jtag_3dcr_reg.config_hold_sticky),
  .ptap_3dcr_gate_ni  (gen_tap_3dcr_reg.u_jtag_3dcr_reg.rst_n_gate)
);
