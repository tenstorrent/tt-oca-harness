// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Attaches dtp_dbgctl_props to every jtag_debug_ctrl_reg instance under the dtp formal top.
// Internal signals reach the property module through this port list only; the RTL carries no
// properties.

bind jtag_debug_ctrl_reg dtp_dbgctl_props u_dtp_dbgctl_props (
  .tck_i                 (scan_ctrl_i.tck),
  .rst_ni                (scan_ctrl_i.rst_n),
  .select_i              (scan_ctrl_i.select),
  .capture_en_i          (scan_ctrl_i.capture_en),
  .update_en_i           (scan_ctrl_i.update_en),
  .cla_clock_stop_i      (cla_clock_stop_i),
  .cla_clock_stop_sync_i (cla_clock_stop_sync),
  .update_q_i            (debug_ctrl_reg_q),
  .scan_data_i           (u_debug_ctrl_scan_reg.scan_data),
  .jtag_clock_stop_i     (jtag_clock_stop_o),
  .cla_clock_stop_en_i   (cla_clock_stop_en_o),
  .boot_stall_ovrd_i     (boot_stall_ovrd_o),
  .boot_stall_i          (boot_stall_o)
);
