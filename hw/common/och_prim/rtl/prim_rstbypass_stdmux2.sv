// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Reset Bypass Mux 2
//
// Selects the scan reset in test mode. Built on prim_rst_mux2_hf_n so that
// entering or leaving test mode cannot glitch the reset it drives.
//--------------------------------------------------
module prim_rstbypass_stdmux2 (
  input  logic rst_ni,
  input  logic test_rst_ni,
  input  logic test_mode_i,
  output logic rst_no
);

  prim_rst_mux2_hf_n rst_bypassmux (
    .rst0_ni(rst_ni),
    .rst1_ni(test_rst_ni),
    .sel_i  (test_mode_i),
    .rst_no (rst_no)
  );

endmodule
