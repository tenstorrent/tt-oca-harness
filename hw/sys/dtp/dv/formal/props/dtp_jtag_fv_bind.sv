// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Attaches the shared JTAG checker to the dtp formal top on the primary TAP: the DTP is the slave,
// whose TAP state, TDO and enable the instance asserts, and the host is the environment, whose
// TMS and TDI phase rule the instance assumes. The TAP's effective reset is TRST AND the power-on
// reset; the state observable is the top's own PTAP state output.

bind dtp ocah_jtag_fv #(
  .EN_STATE_RULES      (1'b1),
  .ASSUME_MASTER_RULES (1'b1),
  .ASSUME_SLAVE_RULES  (1'b0)
) u_ocah_jtag_fv (
  .tck         (jtag_ptap_client_tap_ctrl_i.tck),
  .tms         (jtag_ptap_client_tap_ctrl_i.tms),
  .tdi         (jtag_ptap_client_tdi_i),
  .trst_n      (jtag_ptap_client_tap_ctrl_i.trst_n & pwr_on_rst_ni),
  .tdo         (jtag_ptap_client_tdo_o),
  .tdo_oen     (jtag_ptap_client_tdo_oen_o),
  .tap_state_i (jtag_ptap_state_o)
);
