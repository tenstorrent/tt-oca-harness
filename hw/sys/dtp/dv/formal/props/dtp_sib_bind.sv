// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Attaches dtp_sib_props to every jtag_intf_unit instance under the dtp formal top. The per-SIB
// vectors list the SIBs in chain order, DFT secure at bit 0 and DFD at bit 2. Internal signals
// reach the property module through this port list only; the RTL carries no properties.

bind jtag_intf_unit dtp_sib_props #(
  .NUM_SIBS(3)
) u_dtp_sib_props (
  .tck_i               (ptap_ijtag_host_scan_ctrl.tck),
  .rst_ni              (ptap_ijtag_host_scan_ctrl.rst_n),
  .client_select_i     (ptap_ijtag_host_scan_ctrl.select),
  .client_capture_en_i (ptap_ijtag_host_scan_ctrl.capture_en),
  .client_shift_en_i   (ptap_ijtag_host_scan_ctrl.shift_en),
  .client_update_en_i  (ptap_ijtag_host_scan_ctrl.update_en),
  .ptap_scan_out_i     (ptap_ijtag_host_scan_out),
  .ptap_scan_in_i      (ptap_ijtag_host_scan_in),
  .sib_disable_i       ({u_dfd_sib.security_disable_i,
                         u_dft_nonsecure_sib.security_disable_i,
                         u_dft_secure_sib.security_disable_i}),
  .sib_en_i            ({u_dfd_sib.sib_en,
                         u_dft_nonsecure_sib.sib_en,
                         u_dft_secure_sib.sib_en}),
  .sib_en_masked_i     ({u_dfd_sib.sib_en_masked,
                         u_dft_nonsecure_sib.sib_en_masked,
                         u_dft_secure_sib.sib_en_masked}),
  .sib_scan_out_i      ({u_dfd_sib.scan_reg_scan_out,
                         u_dft_nonsecure_sib.scan_reg_scan_out,
                         u_dft_secure_sib.scan_reg_scan_out}),
  .client_scan_in_i    ({u_dfd_sib.client_scan_in_i,
                         u_dft_nonsecure_sib.client_scan_in_i,
                         u_dft_secure_sib.client_scan_in_i}),
  .client_scan_out_i   ({u_dfd_sib.client_scan_out_o,
                         u_dft_nonsecure_sib.client_scan_out_o,
                         u_dft_secure_sib.client_scan_out_o}),
  .host_scan_in_i      ({dfd_host_scan_in_i,
                         dft_host_scan_in_i,
                         dft_secure_host_scan_in_i}),
  .host_scan_out_i     ({dfd_host_scan_out_o,
                         dft_host_scan_out_o,
                         dft_secure_host_scan_out_o}),
  .host_capture_en_i   ({dfd_host_scan_ctrl_o.capture_en,
                         dft_host_scan_ctrl_o.capture_en,
                         dft_secure_host_scan_ctrl_o.capture_en}),
  .host_shift_en_i     ({dfd_host_scan_ctrl_o.shift_en,
                         dft_host_scan_ctrl_o.shift_en,
                         dft_secure_host_scan_ctrl_o.shift_en}),
  .host_update_en_i    ({dfd_host_scan_ctrl_o.update_en,
                         dft_host_scan_ctrl_o.update_en,
                         dft_secure_host_scan_ctrl_o.update_en}),
  .host_select_i       ({dfd_host_scan_ctrl_o.select,
                         dft_host_scan_ctrl_o.select,
                         dft_secure_host_scan_ctrl_o.select})
);
