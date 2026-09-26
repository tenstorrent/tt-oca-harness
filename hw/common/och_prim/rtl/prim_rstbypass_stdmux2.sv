// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Select the scan reset in test mode without glitching rst_no.
//
// Build on prim_rst_mux2_hf_n so entering or leaving test mode cannot glitch the reset it
// drives.
// Pass rst_ni in functional mode and test_rst_ni when test_mode_i is high.

module prim_rstbypass_stdmux2 (
  input  logic rst_ni,  // Functional reset, active-low.
  input  logic test_rst_ni,  // Scan/test reset, active-low.
  input  logic test_mode_i,  // Selects test_rst_ni when high.
  output logic rst_no  // Muxed reset, active-low; glitch-free across test_mode_i edges.
);

  prim_rst_mux2_hf_n u_rst_bypassmux (
    .rst0_ni(rst_ni),
    .rst1_ni(test_rst_ni),
    .sel_i  (test_mode_i),
    .rst_no (rst_no)
  );

endmodule
