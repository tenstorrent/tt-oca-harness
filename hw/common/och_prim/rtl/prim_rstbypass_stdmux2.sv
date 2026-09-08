// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Reset Bypass Mux 2
//
// Selects the scan reset in test mode. Built on prim_rst_mux2_hf_n so that
// entering or leaving test mode cannot glitch the reset it drives.
//--------------------------------------------------
module prim_rstbypass_stdmux2 (
  input  logic i_reset_n,
  input  logic i_test_reset_n,
  input  logic i_test_mode,
  output logic o_reset_n
);

  prim_rst_mux2_hf_n rst_bypassmux (
    .rst0_ni(i_reset_n),
    .rst1_ni(i_test_reset_n),
    .sel_i  (i_test_mode),
    .rst_no (o_reset_n)
  );

endmodule
