// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Attaches dtp_tap_props to every jtag_tap_ctrlr instance under the dtp formal top. Internal
// signals reach the property module through this port list only; the RTL carries no properties.

bind jtag_tap_ctrlr dtp_tap_props u_dtp_tap_props (
  .tck_i              (client_tap_ctrl_i.tck),
  .trst_ni            (client_tap_ctrl_i.trst_n),
  .tms_i              (client_tap_ctrl_i.tms),
  .state_i            (current_state_o),
  .tdo_oen_i          (tdo_oen_o),
  .dr_select_i        (host_dr_scan_ctrl_o.select),
  .dr_update_en_i     (host_dr_scan_ctrl_o.update_en),
  .ir_select_i        (host_ir_scan_ctrl_o.select),
  .ir_update_en_i     (host_ir_scan_ctrl_o.update_en),
  .run_test_idle_i    (host_dr_scan_ctrl_o.run_test_idle),
  .dr_capture_en_i    (host_dr_scan_ctrl_o.capture_en),
  .dr_shift_en_i      (host_dr_scan_ctrl_o.shift_en),
  .ir_capture_en_i    (host_ir_scan_ctrl_o.capture_en),
  .ir_shift_en_i      (host_ir_scan_ctrl_o.shift_en),
  .test_logic_reset_i (host_dr_scan_ctrl_o.test_logic_reset)
);
